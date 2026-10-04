---
name: comfyui-imagegen
description: Generate, modify, restyle, and enhance images through the local ComfyUI API, with explicit text-to-image and image-to-image routing, source-image validation/upload, and bundled workflows. Use when a user asks to create an image from a prompt or transform a supplied image.
---

# ComfyUI Image Generation

Use `scripts/generate.py`. It uses only Python's standard library and saves downloaded results under `outputs/` relative to the current directory.

## Route before running

- Use text-to-image when the user asks for a new image and provides no source image.
- Use image-to-image when a valid source image is supplied and the user asks to modify, restyle, redraw, enhance, or transform it.
- Honor an explicit `text2img`/`img2img` request. Do not silently fall back from img2img to text2img.
- If an attachment is shown only as a chat placeholder or its intended use is unclear, ask one concise clarification question.
- A path ending in `.png` is not proof that it is an image. Validate the actual file before choosing img2img. Invalid or missing sources must stop with an actionable error.

## Generate

Text-to-image:

```bash
python3 ~/.agents/skills/comfyui-imagegen/scripts/generate.py \
  "描述要生成的图片"
```

Image-to-image:

```bash
python3 ~/.agents/skills/comfyui-imagegen/scripts/generate.py \
  --mode img2img --image /path/to/source.png \
  "描述如何修改源图"
```

Useful overrides:

```bash
# text2img: exact latent dimensions
python3 scripts/generate.py "竖版城市信息图" --width 576 --height 1024 --seed 123

# img2img: preserve source aspect ratio and target about 1.5 megapixels
python3 scripts/generate.py --mode img2img --image source.jpg \
  --megapixels 1.5 --denoise 0.45 --seed 123 "改成水彩风格"
```

The script automatically:

1. Selects the first responding endpoint: `http://10.112.16.2:8888`, then `http://192.168.31.209:8888` (override with `--url` or `COMFY_URL`).
2. Selects `assets/text2img.json` or `assets/img2img.json`; `--image` implies img2img unless an explicit conflicting mode is supplied.
3. For img2img, validates the binary image, uploads it with `POST /upload/image`, and replaces the bundled workflow's `LoadImage.image` with the returned ComfyUI input filename before submitting. It never submits the placeholder `example.png`.
4. Replaces the positive prompt by locating the positive `CLIPTextEncode` node (`57:27` in text2img and `7` in the bundled img2img workflow).
5. Applies dimensions and sampler overrides (`--seed`, `--steps`, `--cfg`, `--denoise`) without changing the bundled workflow on disk.
6. Submits with `POST /prompt`, polls `GET /history/{prompt_id}`, then downloads every result through `/view`.

For img2img, `--width`/`--height` set the target pixel budget while preserving the source aspect ratio when the workflow uses `ImageScaleToTotalPixels`; `--megapixels` is the direct control. Use a denoise value around `0.35–0.65` for moderate restyling and lower values for stronger source preservation.

After a successful run, include every saved image in the final response using a Markdown image embed and report its path. Surface ComfyUI, upload, validation, and workflow errors instead of retrying or silently changing modes.

## Why a supplied image may not have been used

The earlier run generated from text only for two independent reasons:

- The supplied `/tmp/pi-clipboard-...png` was actually UTF-8 text, not a PNG; binary validation/PIL could not identify it as an image.
- The old script was hard-wired to `assets/text2img.json`; it did not accept an image argument, upload the source, switch to `assets/img2img.json`, or replace that workflow's `LoadImage` node. The img2img asset also contained the placeholder `example.png`.

The script now fails clearly for an invalid attachment and requires a successful upload plus `LoadImage` binding before an img2img job can be submitted.

## Workflow rules

- Keep the bundled API-format JSON workflows unchanged unless a workflow structure change is explicitly requested.
- Never use img2img without a real local source image.
- Do not submit a custom workflow containing `LoadImage` without `--image`; this prevents accidental use of stale example files.
- If a custom workflow has multiple `LoadImage` nodes or ambiguous positive prompt nodes, stop and report the ambiguity rather than guessing.
