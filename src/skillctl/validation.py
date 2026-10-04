"""Validate skill names, configuration inputs, metadata and Git source arguments."""

import re
from pathlib import PurePosixPath
from typing import Mapping
from urllib.parse import urlsplit

from .contracts import InvalidSkill, SkillError, SkillSpec

_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_HEX = re.compile(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?\Z")
_SCP = re.compile(r"(?:[a-zA-Z0-9_.-]+@)?[a-zA-Z0-9_.-]+:[^\s]+\Z")


def valid_name(name: object) -> bool:
    return isinstance(name, str) and len(name) <= 64 and _NAME.fullmatch(name) is not None


def require_name(name: object) -> None:
    if not valid_name(name):
        raise SkillError(f"Invalid skill name: {name!r}")


def valid_path(path: object) -> bool:
    return (
        isinstance(path, str)
        and bool(path)
        and "\\" not in path
        and "\x00" not in path
        and not PurePosixPath(path).is_absolute()
        and ".." not in path.split("/")
    )


def validate_overrides(overrides: object, *, name: str | None = None) -> None:
    if not isinstance(overrides, Mapping):
        if name is None:
            raise SkillError("Frontmatter overrides must be a mapping")
        raise SkillError(f"Invalid frontmatter for {name!r}")
    for key in overrides:
        if not isinstance(key, str):
            if name is None:
                raise SkillError(f"Invalid frontmatter override: {key!r}")
            raise SkillError(f"Invalid frontmatter override for {name!r}: {key!r}")


def validate_spec(name: object, spec: object) -> None:
    require_name(name)
    if not isinstance(spec, SkillSpec):
        raise SkillError(f"Invalid specification for {name!r}")
    if not isinstance(spec.repo, str) or not spec.repo.strip():
        raise SkillError(f"Invalid repository for {name!r}")
    if not valid_path(spec.path):
        raise SkillError(f"Invalid path for {name!r}")
    if spec.ref is not None and (not isinstance(spec.ref, str) or not spec.ref):
        raise SkillError(f"Invalid ref for {name!r}")
    if spec.repo == "local" and (spec.path != "." or spec.ref is not None):
        raise SkillError(f"Local skill {name!r} cannot specify a Git path or ref")
    validate_overrides(spec.frontmatter, name=name)


def validate_frontmatter(metadata: object) -> None:
    if not isinstance(metadata, Mapping):
        raise InvalidSkill("Skill frontmatter must be a mapping")


def validate_metadata(metadata: Mapping) -> None:
    if not valid_name(metadata.get("name")):
        raise InvalidSkill("Skill frontmatter needs a valid name")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise InvalidSkill("Skill frontmatter needs a nonblank description (max 1024 characters)")


def validate_markdown(markdown: object) -> None:
    if not isinstance(markdown, str):
        raise InvalidSkill("Skill markdown must be text")


def validate_original_name(metadata: Mapping, overrides: Mapping) -> None:
    """Reject renaming before merging overrides into upstream metadata."""
    original_name = metadata.get("name")
    if not valid_name(original_name):
        raise InvalidSkill("Skill frontmatter needs a valid name")
    if "name" in overrides and overrides["name"] != original_name:
        raise InvalidSkill("Frontmatter override cannot change the skill name")


def repository(repo: str) -> str:
    if not isinstance(repo, str) or not repo or "\x00" in repo or any(ord(c) < 32 for c in repo):
        raise SkillError("Invalid repository URL")
    if repo.startswith("/"):
        return repo
    if repo.startswith("-"):
        raise SkillError("Option-like repository URL")
    if "://" not in repo:
        if _SCP.fullmatch(repo):
            host, remote_path = repo.split(":", 1)
            if (
                host.split("@")[-1].startswith("-")
                or remote_path.startswith(("-", ":"))
                or re.fullmatch(r"[A-Za-z0-9_./~+-]+", remote_path) is None
            ):
                raise SkillError("Unsafe SSH repository")
            return repo
        raise SkillError("Unsupported repository URL")
    try:
        url = urlsplit(repo)
        if url.scheme not in {"https", "ssh"} or not url.hostname or not url.path:
            raise ValueError("Unsupported repository URL")
        if url.hostname.startswith("-") or url.query or url.fragment:
            raise ValueError("Invalid repository URL")
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError("Invalid port")
        if url.path.lstrip("/").startswith("-"):
            raise ValueError("Option-like repository path")
        if url.scheme == "ssh" and (
            url.password is not None
            or (url.username is not None and re.fullmatch(r"[A-Za-z0-9_.-]+", url.username) is None)
            or re.fullmatch(r"/[A-Za-z0-9_./~+-]+", url.path) is None
        ):
            raise ValueError("Unsafe SSH repository")
    except ValueError as exc:
        raise SkillError(f"Invalid repository URL: {exc}") from exc
    return repo


def git_ref(ref: str | None) -> str:
    if ref is None:
        return "HEAD"
    if not isinstance(ref, str) or not ref or ref.startswith("-"):
        raise SkillError("Invalid Git ref")
    if _HEX.fullmatch(ref):
        return ref
    # Leave legal Unicode and punctuation to Git's own refname validator; reject
    # refspec/revision operators and option-like refs before invoking Git.
    if (
        any(ord(char) < 33 or ord(char) == 127 for char in ref)
        or any(char in ref for char in ":~^?*[\\")
        or "@{" in ref
        or ref == "@"
        or (ref.startswith("refs/") and not ref.startswith(("refs/heads/", "refs/tags/")))
    ):
        raise SkillError("Invalid Git ref")
    return ref


def validate_local_names(names: list[str]) -> None:
    if any(not valid_name(name) for name in names):
        raise SkillError("Invalid local skill name for .gitignore")


def validate_fetch_spec(spec: object) -> tuple[str, str]:
    """Validate fetch arguments; return the repository and normalized ref."""
    if not isinstance(spec, SkillSpec):
        raise SkillError("Invalid skill specification")
    repo = repository(spec.repo)
    ref = git_ref(spec.ref)
    if not valid_path(spec.path):
        raise SkillError("Invalid skill subpath")
    return repo, ref
