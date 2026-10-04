"""Read and write the skill registry without losing retained TOML comments."""

import os
import tempfile
from pathlib import Path
from typing import Mapping

import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import InlineTable, Table

from .contracts import SkillError, SkillSpec
# Retain config.valid_name / config.valid_path for existing callers.
from .validation import validate_spec, valid_name, valid_path

_FIELDS = frozenset({"name", "repo", "path", "ref", "frontmatter"})


def _plain(value):
    """Unwrap TOMLKit containers and scalars, including nested fields."""
    return value.unwrap() if hasattr(value, "unwrap") else value


def _same_value(left, right) -> bool:
    left, right = _plain(left), _plain(right)
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            _same_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same_value(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right) and left == right


def _parse(document: object) -> dict[str, SkillSpec]:
    if not isinstance(document, Mapping) or set(document) - {"skills"}:
        raise SkillError("Configuration must contain only a skills array")
    skills = document.get("skills", [])
    if not isinstance(skills, list):
        raise SkillError("skills must be an array; use [[skills]] with an explicit name")
    result: dict[str, SkillSpec] = {}
    for entry in skills:
        if not isinstance(entry, Mapping):
            raise SkillError("Each skills entry must be a TOML table")
        name = entry.get("name")
        if set(entry) - _FIELDS:
            raise SkillError(f"Unknown fields in skill {name!r}")
        spec = SkillSpec(
            repo=entry.get("repo"),
            path=entry.get("path", "."),
            ref=entry.get("ref"),
            frontmatter=_plain(entry.get("frontmatter", {})),
        )
        validate_spec(name, spec)
        if name in result:
            raise SkillError(f"Duplicate skill name: {name!r}")
        result[name] = spec
    return result


def _read_document(path: Path):
    try:
        return tomlkit.parse(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return tomlkit.document()
    except (OSError, UnicodeError, TOMLKitError, ValueError) as exc:
        raise SkillError(f"Cannot read config {path}: {exc}") from exc


def load_config(path: Path) -> dict[str, SkillSpec]:
    """Load a TOML skill registry; absent files represent empty registries."""
    return _parse(_read_document(path))


def save_config(path: Path, specs: Mapping[str, SkillSpec]) -> None:
    """Atomically update the registry, retaining comments on surviving entries."""
    try:
        desired = dict(specs)
        for name, spec in desired.items():
            validate_spec(name, spec)
        document = _read_document(path)
        _parse(document)  # Never silently discard malformed existing configuration.
        retained = {
            entry["name"]: entry for entry in document.get("skills", [])
            if entry["name"] in desired
        }
        names = list(retained) + [name for name in desired if name not in retained]
        skills = tomlkit.aot()
        for name in names:
            spec = desired[name]
            original = retained.get(name)
            if isinstance(original, Table):
                entry = original
            else:
                entry = tomlkit.table()
                if original is not None:
                    entry.update(original)
            if "name" not in entry:
                entry["name"] = name
            if entry.get("repo") != spec.repo:
                entry["repo"] = spec.repo
            # Leave unchanged defaults (and their comments) alone.
            if entry.get("path", ".") != spec.path:
                if spec.path == ".":
                    entry.pop("path", None)
                else:
                    entry["path"] = spec.path
            if entry.get("ref") != spec.ref:
                if spec.ref is None:
                    entry.pop("ref", None)
                else:
                    entry["ref"] = spec.ref
            if not spec.frontmatter:
                entry.pop("frontmatter", None)
            else:
                previous = entry.get("frontmatter")
                if isinstance(previous, InlineTable):
                    overrides = previous
                else:
                    overrides = tomlkit.inline_table()
                    if previous is not None:
                        comment = previous.trivia.comment
                        if comment:
                            overrides.comment(comment.lstrip("#").strip())
                    entry["frontmatter"] = overrides
                for key in list(overrides):
                    if key not in spec.frontmatter:
                        del overrides[key]
                for key, value in spec.frontmatter.items():
                    if key not in overrides or not _same_value(overrides[key], value):
                        overrides[key] = value
            skills.append(entry)
        document["skills"] = skills if names else tomlkit.array()
        content = tomlkit.dumps(document)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                delete=False,
            ) as temp:
                temp_name = temp.name
                temp.write(content)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_name, path)
        finally:
            if temp_name is not None and os.path.exists(temp_name):
                os.unlink(temp_name)
    except SkillError:
        raise
    except (OSError, UnicodeError, TOMLKitError, ValueError, TypeError) as exc:
        raise SkillError(f"Cannot save config {path}: {exc}") from exc
