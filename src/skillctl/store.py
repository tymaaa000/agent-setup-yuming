"""Safe, content-addressed installation of local skill trees.

Callers serialize mutations and maintain ownership records; this module only
validates trees and performs the single-directory replacement.
"""

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Iterator

from .contracts import InvalidSkill, SkillError


def _stat_node(path: Path) -> os.stat_result:
    """Stat without following links, rejecting unsafe filesystem nodes."""
    info = path.lstat()
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise InvalidSkill(f"Symlink or special file in skill tree: {path}")
    return info


def _entries(directory: Path) -> Iterator[tuple[Path, Path, os.stat_result]]:
    """Yield descendants in reproducible order, including empty directories."""
    if not stat.S_ISDIR(_stat_node(directory).st_mode):
        raise InvalidSkill(f"Skill tree is not a directory: {directory}")

    def visit(parent: Path, relative: Path) -> Iterator[tuple[Path, Path, os.stat_result]]:
        for child in sorted(parent.iterdir(), key=lambda entry: os.fsencode(entry.name)):
            child_relative = relative / child.name
            info = _stat_node(child)
            yield child, child_relative, info
            if stat.S_ISDIR(info.st_mode):
                yield from visit(child, child_relative)

    yield from visit(directory, Path())


def _open_regular(path: Path) -> tuple[int, os.stat_result]:
    """Open without following a last-component symlink, including during races."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise InvalidSkill(f"Symlink or special file in skill tree: {path}")
        return fd, info
    except BaseException:
        os.close(fd)
        raise


def _add_path(digest: "hashlib._Hash", relative: Path) -> None:
    raw = os.fsencode(str(relative))
    digest.update(len(raw).to_bytes(8, "big"))
    digest.update(raw)


def tree_hash(directory: Path) -> str:
    """Hash names, contents, and executable bits, rejecting unsafe nodes."""
    try:
        digest = hashlib.sha256()
        for path, relative, info in _entries(directory):
            if stat.S_ISDIR(info.st_mode):
                digest.update(b"D")
                _add_path(digest, relative)
                continue
            digest.update(b"F")
            _add_path(digest, relative)
            fd, opened = _open_regular(path)
            try:
                digest.update((opened.st_mode & 0o111).to_bytes(2, "big"))
                contents = hashlib.sha256()
                length = 0
                with os.fdopen(fd, "rb") as stream:
                    fd = -1
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        contents.update(chunk)
                        length += len(chunk)
                if length != opened.st_size:
                    raise SkillError(f"Skill file changed while hashing: {path}")
                digest.update(length.to_bytes(8, "big"))
                digest.update(contents.digest())
            finally:
                if fd != -1:
                    os.close(fd)
        return digest.hexdigest()
    except OSError as exc:
        raise SkillError(f"Cannot hash skill tree {directory}: {exc}") from exc


def _reject_symlink_ancestors(path: Path) -> None:
    """Reject redirection of the target via any existing parent component."""
    for parent in (path, *path.parents):
        try:
            mode = parent.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise InvalidSkill(f"Symlink in installation path: {parent}")


def _check_disjoint(source: Path, target: Path) -> None:
    for left, right in ((source.absolute(), target.absolute()), (source.resolve(), target.resolve())):
        if left == right or left.is_relative_to(right) or right.is_relative_to(left):
            raise InvalidSkill(f"Source and target overlap: {source}, {target}")


def _copy_tree(source: Path, destination: Path) -> None:
    """Copy regular files without following source links, retaining mode bits."""
    destination.mkdir()
    directories: list[tuple[Path, int]] = [(destination, source.lstat().st_mode)]
    for path, relative, info in _entries(source):
        copy_path = destination / relative
        if stat.S_ISDIR(info.st_mode):
            copy_path.mkdir()
            directories.append((copy_path, info.st_mode))
        else:
            fd, opened = _open_regular(path)
            try:
                with os.fdopen(fd, "rb") as input_file:
                    fd = -1
                    with copy_path.open("xb") as output_file:
                        shutil.copyfileobj(input_file, output_file)
                copy_path.chmod(stat.S_IMODE(opened.st_mode))
            finally:
                if fd != -1:
                    os.close(fd)
    for path, mode in reversed(directories):
        path.chmod(stat.S_IMODE(mode))


def install_skill(source: Path, target: Path, expected_hash: str | None = None) -> str:
    """Install a validated source, safely replacing only an unchanged target."""
    try:
        _reject_symlink_ancestors(source)
        _reject_symlink_ancestors(target)
        _check_disjoint(source, target)
        staging_root = target.parent.parent / ".state" / "staging"
        # Reject unsupported layouts before creating target.parent or staging.
        # In particular, staging must not be a skill in the scanned directory.
        _check_disjoint(target, staging_root)
        if staging_root.absolute().is_relative_to(target.parent.absolute()) or staging_root.resolve().is_relative_to(
            target.parent.resolve()
        ):
            raise SkillError(f"Staging area is inside the skill scan directory: {target.parent}")
        original_hash = tree_hash(source)
        skill_file = source / "SKILL.md"
        try:
            skill_mode = _stat_node(skill_file).st_mode
        except FileNotFoundError as exc:
            raise InvalidSkill(f"Missing SKILL.md: {skill_file}") from exc
        if not stat.S_ISREG(skill_mode):
            raise InvalidSkill(f"Missing regular SKILL.md: {skill_file}")
        from .render import skill_name

        fd, _ = _open_regular(skill_file)
        with os.fdopen(fd, "r", encoding="utf-8") as metadata:
            skill_name(metadata.read())

        try:
            target.lstat()
            exists = True
        except FileNotFoundError:
            exists = False
        if expected_hash is None:
            if exists:
                raise SkillError(f"Skill target already exists: {target}")
        else:
            if not exists:
                raise SkillError(f"Skill target is missing: {target}")
            if tree_hash(target) != expected_hash:
                raise SkillError(f"Skill target has local modifications: {target}")

        # A downloaded source may live inside staging_root, but creating the
        # transaction must never modify the source tree itself.
        if staging_root.absolute().is_relative_to(source.absolute()) or staging_root.resolve().is_relative_to(
            source.resolve()
        ):
            raise InvalidSkill(f"Staging area is inside the skill source: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_ancestors(target)
        _reject_symlink_ancestors(staging_root)
        staging_root.mkdir(parents=True, exist_ok=True)
        _reject_symlink_ancestors(staging_root)
        if staging_root.stat().st_dev != target.parent.stat().st_dev:
            raise SkillError("Staging area and skill target must be on the same filesystem")

        transaction = Path(tempfile.mkdtemp(prefix="install-", dir=staging_root))
        backup = transaction / "old"
        staged = transaction / "new"
        backup_held = False
        try:
            _check_disjoint(source, transaction)
            _copy_tree(source, staged)
            installed_hash = tree_hash(staged)
            if installed_hash != original_hash or tree_hash(source) != original_hash:
                raise SkillError(f"Skill source changed during installation: {source}")
            # Recheck immediately before moving the old installation away.
            if expected_hash is None:
                try:
                    target.lstat()
                except FileNotFoundError:
                    pass
                else:
                    raise SkillError(f"Skill target already exists: {target}")
            elif tree_hash(target) != expected_hash:
                raise SkillError(f"Skill target has local modifications: {target}")

            try:
                if expected_hash is not None:
                    os.replace(target, backup)
                    backup_held = True
                os.replace(staged, target)
            except BaseException:
                if backup_held:
                    try:
                        os.replace(backup, target)
                        backup_held = False
                    except OSError as restore_error:
                        raise SkillError(
                            f"Could not restore old skill; backup retained at {backup}: {restore_error}"
                        ) from restore_error
                raise
            backup_held = False
            return installed_hash
        finally:
            if not backup_held:
                shutil.rmtree(transaction, ignore_errors=True)
    except UnicodeError as exc:
        raise InvalidSkill(f"Invalid SKILL.md encoding: {exc}") from exc
    except OSError as exc:
        raise SkillError(f"Cannot install skill {source} at {target}: {exc}") from exc
