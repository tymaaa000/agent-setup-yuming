"""Keep local skill exceptions in a clearly delimited, generated Git block."""

from collections.abc import Iterable
import os
from pathlib import Path
import stat
import tempfile

from .contracts import SkillError
from .validation import validate_local_names

_BEGIN = "# BEGIN skillctl managed skills"
_END = "# END skillctl managed skills"


def sync_gitignore(home: Path, local_names: Iterable[str]) -> bool:
    """Update only the managed block, preserving handwritten rules and file mode."""
    names = list(local_names)
    validate_local_names(names)
    rules = [_BEGIN, "!/skills/", "/skills/*"]
    rules.extend(f"!/skills/{name}/" for name in sorted(set(names)))
    block = "\n".join([*rules, _END]) + "\n"
    path = home / ".gitignore"
    temporary: str | None = None
    try:
        try:
            info = path.lstat()
        except FileNotFoundError:
            original = ""
            mode = 0o644
        else:
            if not stat.S_ISREG(info.st_mode):
                raise SkillError(f".gitignore must be a regular, nonsymlink file: {path}")
            original = path.read_bytes().decode("utf-8")
            mode = stat.S_IMODE(info.st_mode)
        lines = original.splitlines(keepends=True)
        starts = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == _BEGIN]
        ends = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == _END]
        if starts or ends:
            if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
                raise SkillError("Malformed or duplicate skillctl markers in .gitignore")
            content = "".join(lines[:starts[0]]) + block + "".join(lines[ends[0] + 1:])
        else:
            separator = "" if not original or original.endswith("\n") else "\n"
            content = original + separator + block
        if content == original:
            return False
        home.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".gitignore-", dir=home)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except (OSError, UnicodeError) as exc:
        raise SkillError(f"Cannot update {path}: {exc}") from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
