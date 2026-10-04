#!/usr/bin/env python3
"""Submit the bundled ComfyUI workflow and download the generated images."""

import argparse
import json
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ENDPOINTS = (
    "http://10.112.16.2:8888",
    "http://192.168.31.209:8888",
)

SKILL_DIR = Path(__file__).resolve().parents[1]
TEXT2IMG_WORKFLOW = SKILL_DIR / "assets" / "text2img.json"
IMG2IMG_WORKFLOW = SKILL_DIR / "assets" / "img2img.json"
# Kept as a compatibility alias for callers that imported the old constant.
WORKFLOW = TEXT2IMG_WORKFLOW

IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"RIFF", "image/webp", ".webp"),
    (b"BM", "image/bmp", ".bmp"),
    (b"II*\x00", "image/tiff", ".tif"),
    (b"MM\x00*", "image/tiff", ".tif"),
)


def detect_url():
    """Return the first reachable ComfyUI endpoint."""
    for base_url in ENDPOINTS:
        try:
            with urlopen(f"{base_url}/system_stats", timeout=1) as response:
                if 200 <= response.status < 300:
                    return base_url
        except (HTTPError, URLError, OSError, TimeoutError):
            pass
    raise RuntimeError("两个 ComfyUI 地址都无法连接")


def _http_error_detail(error):
    try:
        return error.read().decode("utf-8", "replace")
    except Exception:
        return str(error)


def request_json(url, payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if body is not None else {}
    try:
        with urlopen(Request(url, data=body, headers=headers), timeout=30) as response:
            raw = response.read()
    except HTTPError as error:
        raise RuntimeError(f"ComfyUI 返回 {error.code}: {_http_error_detail(error)}") from error
    except (URLError, OSError, TimeoutError) as error:
        raise RuntimeError(f"请求 ComfyUI 失败: {error}") from error

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"ComfyUI 返回了无法解析的 JSON: {raw[:500]!r}") from error


def validate_source_image(path):
    """Validate a local binary image before attempting an img2img upload."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise RuntimeError(f"源图不存在或不是文件: {path}")

    try:
        with path.open("rb") as stream:
            header = stream.read(16)
    except OSError as error:
        raise RuntimeError(f"无法读取源图 {path}: {error}") from error

    if not header:
        raise RuntimeError(f"源图为空: {path}")

    for signature, mime_type, extension in IMAGE_SIGNATURES:
        if header.startswith(signature) and (
            signature != b"RIFF" or header[8:12] == b"WEBP"
        ):
            return path, mime_type, extension

    raise RuntimeError(
        f"源文件不是可识别的图片（二进制签名校验失败）: {path}。"
        "请传入实际的 PNG/JPEG/WebP/GIF/BMP/TIFF 文件，而不是文本占位符或 Markdown 路径。"
    )


def _multipart_field(boundary, name, value):
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{value}\r\n"
    ).encode("utf-8")


def upload_image(base_url, path, mime_type, extension):
    """Upload an image to ComfyUI's input directory and return its LoadImage name."""
    boundary = f"----pi-comfy-{uuid.uuid4().hex}"
    remote_filename = f"pi-{uuid.uuid4().hex}{extension}"
    image_bytes = path.read_bytes()

    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("ascii"))
    body.extend(
        f'Content-Disposition: form-data; name="image"; filename="{remote_filename}"\r\n'.encode(
            "ascii"
        )
    )
    body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("ascii"))
    body.extend(image_bytes)
    body.extend(b"\r\n")
    body.extend(_multipart_field(boundary, "type", "input"))
    body.extend(_multipart_field(boundary, "overwrite", "true"))
    body.extend(f"--{boundary}--\r\n".encode("ascii"))

    request = Request(
        f"{base_url}/upload/image",
        data=bytes(body),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read()
    except HTTPError as error:
        raise RuntimeError(
            f"上传源图失败，ComfyUI 返回 {error.code}: {_http_error_detail(error)}"
        ) from error
    except (URLError, OSError, TimeoutError) as error:
        raise RuntimeError(f"上传源图失败: {error}") from error

    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"上传接口返回了无法解析的 JSON: {raw[:500]!r}") from error

    name = result.get("name") if isinstance(result, dict) else None
    if not name:
        raise RuntimeError(f"ComfyUI 未返回上传文件名: {result}")

    subfolder = result.get("subfolder", "")
    return f"{subfolder.strip('/')}/{name}" if subfolder else name


def load_image_nodes(workflow):
    return [
        (node_id, node)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == "LoadImage"
    ]


def set_source_image(workflow, remote_name):
    nodes = load_image_nodes(workflow)
    if not nodes:
        raise RuntimeError("img2img 工作流没有 LoadImage 节点，源图不会被使用")
    if len(nodes) > 1:
        node_ids = ", ".join(node_id for node_id, _ in nodes)
        raise RuntimeError(
            f"img2img 工作流包含多个 LoadImage 节点（{node_ids}），无法安全判断要替换哪一个"
        )
    nodes[0][1].setdefault("inputs", {})["image"] = remote_name
    return nodes[0][0]


def find_positive_prompt_node(workflow):
    """Find the CLIP text node connected to a sampler's positive input."""
    # These are the IDs in the bundled workflows and avoid ambiguity immediately.
    for node_id in ("57:27", "7"):
        node = workflow.get(node_id)
        if (
            isinstance(node, dict)
            and node.get("class_type") == "CLIPTextEncode"
            and "text" in node.get("inputs", {})
        ):
            return node_id

    positive_ids = set()
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") not in {"KSampler", "KSamplerAdvanced"}:
            continue
        reference = node.get("inputs", {}).get("positive")
        if isinstance(reference, list) and reference and isinstance(reference[0], str):
            positive_ids.add(reference[0])

    candidates = [
        node_id
        for node_id in positive_ids
        if node_id in workflow
        and workflow[node_id].get("class_type") == "CLIPTextEncode"
        and "text" in workflow[node_id].get("inputs", {})
    ]
    if len(candidates) == 1:
        return candidates[0]

    text_nodes = [
        node_id
        for node_id, node in workflow.items()
        if isinstance(node, dict)
        and node.get("class_type") == "CLIPTextEncode"
        and "text" in node.get("inputs", {})
    ]
    if len(text_nodes) == 1:
        return text_nodes[0]
    raise RuntimeError("无法唯一定位正向提示词节点，请使用包含明确正向 CLIPTextEncode 的工作流")


def sampler_nodes(workflow):
    return [
        node
        for node in workflow.values()
        if isinstance(node, dict)
        and node.get("class_type") in {"KSampler", "KSamplerAdvanced"}
    ]


def apply_sampler_options(workflow, seed=None, steps=None, cfg=None, denoise=None):
    if all(value is None for value in (seed, steps, cfg, denoise)):
        return

    nodes = sampler_nodes(workflow)
    if not nodes:
        raise RuntimeError("工作流没有 KSampler/KSamplerAdvanced 节点，无法应用采样参数")

    for node in nodes:
        inputs = node.setdefault("inputs", {})
        if seed is not None:
            if "seed" in inputs:
                inputs["seed"] = seed
            elif "noise_seed" in inputs:
                inputs["noise_seed"] = seed
            else:
                raise RuntimeError("采样器没有 seed/noise_seed 输入")
        if steps is not None and "steps" in inputs:
            inputs["steps"] = steps
        if cfg is not None and "cfg" in inputs:
            inputs["cfg"] = cfg
        if denoise is not None and "denoise" in inputs:
            inputs["denoise"] = denoise


def apply_dimensions(workflow, width=None, height=None, megapixels=None):
    if (width is None) != (height is None):
        raise RuntimeError("--width 和 --height 必须同时提供")
    if width is not None and (width <= 0 or height <= 0):
        raise RuntimeError("--width 和 --height 必须为正数")
    if megapixels is not None and megapixels <= 0:
        raise RuntimeError("--megapixels 必须为正数")

    dimension_nodes = [
        node
        for node in workflow.values()
        if isinstance(node, dict)
        and "width" in node.get("inputs", {})
        and "height" in node.get("inputs", {})
    ]
    scale_nodes = [
        node
        for node in workflow.values()
        if isinstance(node, dict)
        and node.get("class_type") == "ImageScaleToTotalPixels"
        and "megapixels" in node.get("inputs", {})
    ]

    if width is not None:
        if dimension_nodes:
            if len(dimension_nodes) > 1:
                raise RuntimeError("工作流包含多个尺寸节点，无法安全应用 --width/--height")
            dimension_nodes[0]["inputs"]["width"] = width
            dimension_nodes[0]["inputs"]["height"] = height
        elif scale_nodes:
            if len(scale_nodes) > 1:
                raise RuntimeError("工作流包含多个图像缩放节点，无法安全应用尺寸")
            # img2img preserves the source aspect ratio and targets this pixel budget.
            scale_nodes[0]["inputs"]["megapixels"] = width * height / 1_000_000
        else:
            raise RuntimeError("工作流没有可调节的尺寸节点")

    if megapixels is not None:
        if not scale_nodes:
            raise RuntimeError("当前工作流没有 ImageScaleToTotalPixels 节点，不能使用 --megapixels")
        if len(scale_nodes) > 1:
            raise RuntimeError("工作流包含多个图像缩放节点，无法安全应用 --megapixels")
        scale_nodes[0]["inputs"]["megapixels"] = megapixels


def choose_workflow(args, source_image):
    if args.mode == "text2img" and source_image is not None:
        raise RuntimeError("--mode text2img 不能同时使用 --image；请改用 img2img")
    if args.mode == "img2img" and source_image is None:
        raise RuntimeError("--mode img2img 必须提供 --image PATH")

    if args.workflow:
        return Path(args.workflow).expanduser()
    if source_image is not None or args.mode == "img2img":
        return IMG2IMG_WORKFLOW
    return TEXT2IMG_WORKFLOW


def main():
    parser = argparse.ArgumentParser(description="调用 ComfyUI 工作流并下载图片")
    parser.add_argument("prompt", nargs="?", help="正向提示词")
    parser.add_argument("--mode", choices=("text2img", "img2img"), help="明确选择工作流模式")
    parser.add_argument("--image", "--source-image", dest="image", help="img2img 源图路径")
    parser.add_argument("--url", default=os.getenv("COMFY_URL"), help="直接指定 ComfyUI 地址")
    parser.add_argument("--workflow", help="自定义 API-format 工作流 JSON")
    parser.add_argument("--output", default="outputs")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--megapixels", type=float, help="img2img 的目标像素数（百万像素）")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--cfg", type=float)
    parser.add_argument("--denoise", type=float, help="img2img 去噪强度，范围 0 到 1")
    parser.add_argument("--timeout", type=int, default=3600, help="最长等待秒数")
    args = parser.parse_args()

    if args.steps is not None and args.steps <= 0:
        parser.error("--steps 必须为正数")
    if args.cfg is not None and args.cfg < 0:
        parser.error("--cfg 不能为负数")
    if args.denoise is not None and not 0 <= args.denoise <= 1:
        parser.error("--denoise 必须在 0 到 1 之间")

    source_image = validate_source_image(args.image) if args.image else None
    workflow_path = choose_workflow(args, source_image)
    if not workflow_path.is_file():
        raise RuntimeError(f"工作流文件不存在: {workflow_path}")

    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"无法读取工作流 {workflow_path}: {error}") from error
    if not isinstance(workflow, dict):
        raise RuntimeError(f"工作流必须是 API-format JSON 对象: {workflow_path}")

    image_nodes = load_image_nodes(workflow)
    if source_image is None and image_nodes:
        raise RuntimeError(
            "所选工作流包含 LoadImage，但没有提供 --image；为避免误用 example.png，已停止提交"
        )
    if source_image is not None and not image_nodes:
        raise RuntimeError("已提供 --image，但所选工作流没有 LoadImage 节点")

    base_url = args.url.rstrip("/") if args.url else detect_url()
    print(f"使用 ComfyUI: {base_url}")
    print(f"使用工作流: {workflow_path}")

    if source_image is not None:
        source_path, mime_type, extension = source_image
        remote_name = upload_image(base_url, source_path, mime_type, extension)
        node_id = set_source_image(workflow, remote_name)
        print(f"已上传源图并绑定 LoadImage 节点 {node_id}: {source_path}")

    if args.prompt is not None:
        prompt_node = find_positive_prompt_node(workflow)
        workflow[prompt_node]["inputs"]["text"] = args.prompt
        print(f"已更新正向提示词节点: {prompt_node}")

    apply_dimensions(workflow, args.width, args.height, args.megapixels)
    apply_sampler_options(workflow, args.seed, args.steps, args.cfg, args.denoise)

    result = request_json(
        f"{base_url}/prompt",
        {"prompt": workflow, "client_id": str(uuid.uuid4())},
    )
    if result.get("node_errors"):
        raise RuntimeError(json.dumps(result["node_errors"], ensure_ascii=False))
    if "prompt_id" not in result:
        raise RuntimeError(f"提交失败: {result}")

    prompt_id = result["prompt_id"]
    print(f"已提交: {prompt_id}")
    deadline = time.monotonic() + args.timeout

    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("等待 ComfyUI 超时")
        history = request_json(f"{base_url}/history/{quote(prompt_id, safe='')}")
        record = history.get(prompt_id)
        if record:
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False))
            if status.get("completed") or "outputs" in record:
                break
        time.sleep(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for node_output in record.get("outputs", {}).values():
        for image in node_output.get("images", []):
            query = urlencode(
                {
                    "filename": image["filename"],
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                }
            )
            path = output_dir / Path(image["filename"]).name
            try:
                with urlopen(f"{base_url}/view?{query}", timeout=30) as response:
                    path.write_bytes(response.read())
            except (HTTPError, URLError, OSError, TimeoutError) as error:
                raise RuntimeError(f"下载输出图片失败: {error}") from error
            print(f"已保存: {path}")
            count += 1

    if not count:
        print("任务完成，但没有找到输出图片")


if __name__ == "__main__":
    main()
