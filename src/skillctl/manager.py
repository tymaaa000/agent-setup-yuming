"""Serialize syncs and commit generated skills with local policy applied."""

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Callable, Iterator, Literal

from .config import load_config
from .contracts import ProgressCallback, ProgressEvent, SkillError, SkillSpec, SyncResult
from .gitignore import sync_gitignore
from .render import render_skill, skill_name
from .source import fetch_skill
from .store import install_skill, tree_hash
from .validation import require_name


def default_home() -> Path:
    return Path(os.environ.get("SKILLCTL_HOME", "~/.agents")).expanduser().resolve()


def _reject_link(path: Path) -> None:
    if path.is_symlink():
        raise SkillError(f"Refusing symlink: {path}")


@contextmanager
def _locked(home: Path) -> Iterator[None]:
    try:
        home.mkdir(parents=True, exist_ok=True)
        _reject_link(home / "skills")
        for path in (home / ".state", home / ".state/staging"):
            _reject_link(path)
            path.mkdir(exist_ok=True)
        for path in (home / "config.toml", home / ".state/installed.json"):
            _reject_link(path)
        lock = home / ".state/operation.lock"
        _reject_link(lock)
        with lock.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
    except OSError as exc:
        raise SkillError(str(exc)) from exc


def _config(home: Path) -> dict[str, SkillSpec]:
    file = home / "config.toml"
    try:
        mode = file.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise SkillError(f"Config must be a regular, nonsymlink file: {file}")
    except OSError as exc:
        raise SkillError(f"Cannot read config {file}: {exc}") from exc
    config = load_config(file)
    # load_config treats a missing file as an empty registry; sync must not.
    if not file.exists():
        raise SkillError(f"Config disappeared while reading: {file}")
    return config


def _state(home: Path) -> dict:
    file = home / ".state/installed.json"
    try:
        mode = file.lstat().st_mode
    except FileNotFoundError:
        return {"version": 1, "skills": {}}
    except OSError as exc:
        raise SkillError(f"Cannot read state {file}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise SkillError(f"State must be a regular, nonsymlink file: {file}")
    try:
        value = json.loads(file.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "skills"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or not isinstance(value["skills"], dict)
        ):
            raise ValueError("invalid state schema")
        for name, item in value["skills"].items():
            require_name(name)
            git_record = (
                isinstance(item, dict)
                and set(item) == {"commit", "hash"}
                and all(isinstance(item[k], str) and item[k] for k in item)
            )
            local_record = (
                isinstance(item, dict)
                and set(item) == {"kind", "hash"}
                and item["kind"] == "local"
                and isinstance(item["hash"], str)
                and bool(item["hash"])
            )
            if not (git_record or local_record):
                raise ValueError(f"invalid state record: {name}")
        return value
    except (ValueError, UnicodeError, OSError) as exc:
        raise SkillError(f"Cannot read state {file}: {exc}") from exc


def _atomic_bytes(file: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{file.name}-", dir=file.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, file)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _save_state(home: Path, state: dict) -> None:
    _atomic_bytes(
        home / ".state/installed.json",
        (json.dumps(state, indent=2, sort_keys=True) + "\n").encode(),
    )


def _expected(target: Path, record: dict | None) -> str | None:
    _reject_link(target)
    if not target.exists():
        return None
    if record is None:
        raise SkillError(f"Refusing unmanaged directory: {target}")
    if tree_hash(target) != record["hash"]:
        raise SkillError(f"Local changes in {target}; back them up and restore before retrying")
    return record["hash"]


@dataclass
class _Receipt:
    backup: Path
    existed: bool
    changed: bool = False


@contextmanager
def _transaction(home: Path, target: Path, *, detach: bool = False) -> Iterator[_Receipt]:
    """Rollback target and state; retain recovery data if restoration fails."""
    file = home / ".state/installed.json"
    original = file.read_bytes() if file.exists() else None
    temporary = Path(tempfile.mkdtemp(dir=home / ".state/staging"))
    retain = False
    try:
        _reject_link(target)
        receipt = _Receipt(temporary / "previous", target.exists())
        if receipt.existed and not detach:
            shutil.copytree(target, receipt.backup)
        try:
            yield receipt
        except BaseException:
            # A rejected install has not changed target. Never erase edits
            # discovered by install_skill after the backup was taken.
            restoration_error = None
            try:
                if receipt.changed:
                    if os.path.lexists(target):
                        os.replace(target, temporary / "discarded")
                    if receipt.existed:
                        os.replace(receipt.backup, target)
            except Exception as exc:
                restoration_error = exc
            try:
                if original is None:
                    file.unlink(missing_ok=True)
                elif not file.exists() or file.read_bytes() != original:
                    _atomic_bytes(file, original)
            except Exception as exc:
                restoration_error = restoration_error or exc
            if restoration_error is not None:
                retain = True
                raise SkillError(
                    f"Cannot restore {target}; recovery data retained at {temporary}: {restoration_error}"
                ) from restoration_error
            raise
    finally:
        if not retain:
            # Cleanup must not turn a successful commit into a failure. A
            # read-only directory may leave safe staging debris behind.
            shutil.rmtree(temporary, ignore_errors=True)


def _emit(progress: ProgressCallback | None, event: ProgressEvent) -> None:
    if progress is not None:
        try:
            progress(event)
        except Exception:
            pass


def _materialize(
    home: Path,
    name: str,
    spec: SkillSpec,
    state: dict,
    phase: Callable[[Literal["fetching", "rendering", "installing"]], None],
) -> None:
    target = home / "skills" / name
    expected = _expected(target, state["skills"].get(name))
    with tempfile.TemporaryDirectory(dir=home / ".state/staging") as temporary:
        phase("fetching")
        fetched = fetch_skill(spec, Path(temporary))
        phase("rendering")
        markdown = fetched.directory / "SKILL.md"
        upstream = markdown.read_bytes().decode("utf-8")
        if skill_name(upstream) != name:
            raise SkillError(f"Upstream skill name does not match configured name {name!r}")
        markdown.write_bytes(render_skill(upstream, spec.frontmatter).encode("utf-8"))
        phase("installing")
        with _transaction(home, target) as transaction:
            digest = install_skill(fetched.directory, target, expected)
            transaction.changed = True
            new_state = {"version": 1, "skills": dict(state["skills"])}
            new_state["skills"][name] = {"commit": fetched.commit, "hash": digest}
            _save_state(home, new_state)
        state.clear()
        state.update(new_state)


def _materialize_local(
    home: Path,
    name: str,
    spec: SkillSpec,
    state: dict,
    phase: Callable[[Literal["rendering", "installing"]], None],
) -> None:
    target = home / "skills" / name
    _reject_link(target)
    try:
        if not stat.S_ISDIR(target.lstat().st_mode):
            raise SkillError(f"Local skill is not a directory: {target}")
    except FileNotFoundError as exc:
        raise SkillError(f"Local skill is missing: {target}") from exc
    # Hash before reading anything from the skill, rejecting links and special nodes.
    original_hash = tree_hash(target)
    temporary = Path(tempfile.mkdtemp(dir=home / ".state/staging"))
    try:
        staged = temporary / "local"
        shutil.copytree(target, staged, symlinks=True)
        if tree_hash(staged) != original_hash:
            raise SkillError(f"Local skill changed while staging: {target}")
        phase("rendering")
        markdown = staged / "SKILL.md"
        upstream = markdown.read_bytes().decode("utf-8")
        if skill_name(upstream) != name:
            raise SkillError(f"Local skill name does not match configured name {name!r}")
        rendered = render_skill(upstream, spec.frontmatter).encode("utf-8")
        mode = stat.S_IMODE(markdown.stat().st_mode)
        if not mode & stat.S_IWUSR:
            markdown.chmod(mode | stat.S_IWUSR)
        try:
            markdown.write_bytes(rendered)
        finally:
            markdown.chmod(mode)
        phase("installing")
        with _transaction(home, target) as transaction:
            digest = install_skill(staged, target, original_hash)
            transaction.changed = True
            new_state = {"version": 1, "skills": dict(state["skills"])}
            new_state["skills"][name] = {"kind": "local", "hash": digest}
            _save_state(home, new_state)
        state.clear()
        state.update(new_state)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _remove(home: Path, name: str, state: dict) -> None:
    target = home / "skills" / name
    _expected(target, state["skills"][name])
    with _transaction(home, target, detach=True) as transaction:
        if transaction.existed:
            os.replace(target, transaction.backup)
            transaction.changed = True
            if tree_hash(transaction.backup) != state["skills"][name]["hash"]:
                raise SkillError(f"Local changes in {target}; back them up and restore before retrying")
        new_state = {"version": 1, "skills": dict(state["skills"])}
        del new_state["skills"][name]
        _save_state(home, new_state)
    state.clear()
    state.update(new_state)


def sync(home: Path, *, progress: ProgressCallback | None = None) -> SyncResult:
    _emit(progress, ProgressEvent("sync", "waiting"))
    with _locked(home):
        config = _config(home)
        state = _state(home)
        sync_gitignore(home, (name for name, spec in config.items() if spec.repo == "local"))
        updates = sorted(config)
        removals = sorted(state["skills"].keys() - config.keys())
        total = len(updates) + len(removals)
        completed = 0
        updated: list[str] = []
        removed: list[str] = []
        errors: dict[str, str] = {}
        for name in updates + removals:
            _emit(progress, ProgressEvent("sync", "checking", name, completed, total))
            try:
                if name in config:
                    def phase(value: Literal["fetching", "rendering", "installing"]) -> None:
                        _emit(progress, ProgressEvent("sync", value, name, completed, total))

                    if config[name].repo == "local":
                        _materialize_local(home, name, config[name], state, phase)
                    else:
                        _materialize(home, name, config[name], state, phase)
                    updated.append(name)
                else:
                    _emit(progress, ProgressEvent("sync", "removing", name, completed, total))
                    _remove(home, name, state)
                    removed.append(name)
                completed += 1
                _emit(progress, ProgressEvent("sync", "done", name, completed, total))
            except (SkillError, OSError, UnicodeError) as exc:
                errors[name] = str(exc) or type(exc).__name__
                completed += 1
                _emit(progress, ProgressEvent("sync", "failed", name, completed, total))
        _emit(progress, ProgressEvent("sync", "finished", completed=total, total=total))
        return SyncResult(tuple(updated), tuple(removed), errors)
