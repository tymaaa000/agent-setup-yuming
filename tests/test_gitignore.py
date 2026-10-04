"""Black-box tests for the managed .gitignore contract and sync integration."""

import json
import os
import stat
import subprocess

import pytest

from skillctl.config import save_config
from skillctl.contracts import SkillError, SkillSpec
from skillctl.gitignore import sync_gitignore
from skillctl.manager import sync

from conftest import git, markdown


BEGIN = "# BEGIN skillctl managed skills\n"
END = "# END skillctl managed skills\n"


def block(*names):
    return BEGIN + "!/skills/\n/skills/*\n" + "".join(f"!/skills/{name}/\n" for name in names) + END


def ignored(repo, path):
    result = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", "--", path],
        capture_output=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


def local_skill(home, name):
    target = home / "skills" / name
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(markdown(name=name), encoding="utf-8")
    return target


def installed_state(home):
    return (home / ".state" / "installed.json").read_bytes()


def test_creates_missing_file_with_sorted_unique_exceptions_and_baseline(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert sync_gitignore(home, (name for name in ["zeta", "alpha", "zeta"])) is True
    assert (home / ".gitignore").read_bytes() == block("alpha", "zeta").encode()
    assert sync_gitignore(home, ["zeta", "alpha", "alpha"]) is False

    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    assert sync_gitignore(empty_home, []) is True
    assert (empty_home / ".gitignore").read_bytes() == block().encode()


@pytest.mark.parametrize("original", [b"", b"# mine\n*.tmp\n", b"# mine\n*.tmp"])
def test_appends_to_unmanaged_file_without_rewriting_original_bytes(tmp_path, original):
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".gitignore"
    path.write_bytes(original)
    assert sync_gitignore(home, ["personal"]) is True
    separator = b"\n" if original and not original.endswith(b"\n") else b""
    assert path.read_bytes() == original + separator + block("personal").encode()


def test_replaces_block_in_place_preserving_external_bytes_and_removing_stale_names(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".gitignore"
    prefix = b"# handwritten  \n*.tmp\r\n\n"
    suffix = b"# after block  \r\n!keep-me.tmp\n\n"
    path.write_bytes(prefix + block("obsolete", "zeta").encode() + suffix)
    assert sync_gitignore(home, ["beta", "alpha", "beta"]) is True
    assert path.read_bytes() == prefix + block("alpha", "beta").encode() + suffix
    assert sync_gitignore(home, []) is True
    assert path.read_bytes() == prefix + block().encode() + suffix


def test_same_content_is_no_write_and_preserves_mtime_and_mode(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".gitignore"
    path.write_bytes(b"# keep\n" + block("personal").encode())
    path.chmod(0o640)
    os.utime(path, ns=(1_500_000_000_000_000_000, 1_500_000_000_000_000_000))
    before = path.stat()
    assert sync_gitignore(home, ["personal", "personal"]) is False
    after = path.stat()
    assert (after.st_mtime_ns, after.st_ino, stat.S_IMODE(after.st_mode)) == (
        before.st_mtime_ns, before.st_ino, 0o640
    )
    assert path.read_bytes() == b"# keep\n" + block("personal").encode()
    assert sync_gitignore(home, ["next"]) is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert path.read_bytes() == b"# keep\n" + block("next").encode()


@pytest.mark.parametrize(
    "text",
    [
        BEGIN,
        END,
        END + BEGIN,
        BEGIN + END + BEGIN + END,
        BEGIN + END + END,
        BEGIN + BEGIN + END,
        "# manual\n" + BEGIN + "!/skills/\n" + END + "# tail\n" + BEGIN + END,
    ],
)
def test_rejects_unmatched_duplicate_or_reversed_markers_without_writing(tmp_path, text):
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".gitignore"
    before = text.encode()
    path.write_bytes(before)
    with pytest.raises(SkillError):
        sync_gitignore(home, ["personal"])
    assert path.read_bytes() == before


@pytest.mark.parametrize("bad", ["", "Bad", "a--b", "-a", "a-", "../outside", "a/b", "a\\b", "a\n!/*.py", "a" * 65])
def test_rejects_invalid_names_before_changing_file(tmp_path, bad):
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".gitignore"
    original = b"# user rule\n"
    path.write_bytes(original)
    with pytest.raises(SkillError):
        sync_gitignore(home, iter(["valid", bad]))
    assert path.read_bytes() == original


def test_invalid_name_does_not_create_missing_gitignore(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    with pytest.raises(SkillError):
        sync_gitignore(home, ["good", "Not-Valid"])
    assert not (home / ".gitignore").exists()


@pytest.mark.parametrize("bad_bytes", [b"# mine\n\xff\n", BEGIN.encode() + b"\xff\n" + END.encode()])
def test_rejects_invalid_utf8_without_writing(tmp_path, bad_bytes):
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".gitignore"
    path.write_bytes(bad_bytes)
    with pytest.raises(SkillError):
        sync_gitignore(home, ["personal"])
    assert path.read_bytes() == bad_bytes


@pytest.mark.parametrize("kind", ["symlink", "broken-symlink", "directory"])
def test_refuses_symlink_and_nonregular_gitignore(tmp_path, kind):
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".gitignore"
    outside = tmp_path / "outside"
    if kind == "directory":
        path.mkdir()
        (path / "keep").write_bytes(b"untouched")
    else:
        if kind == "symlink":
            outside.write_bytes(b"# outside\n")
        path.symlink_to(outside)
    with pytest.raises(SkillError):
        sync_gitignore(home, ["personal"])
    if kind == "directory":
        assert (path / "keep").read_bytes() == b"untouched"
    else:
        assert path.is_symlink()
        if kind == "symlink":
            assert outside.read_bytes() == b"# outside\n"
        else:
            assert not outside.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory permissions")
def test_filesystem_write_failure_keeps_original_bytes_and_mode(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".gitignore"
    original = b"# handwritten\n" + block("old").encode()
    path.write_bytes(original)
    path.chmod(0o444)
    home.chmod(0o555)
    try:
        with pytest.raises(SkillError):
            sync_gitignore(home, ["new"])
        assert path.read_bytes() == original
        assert stat.S_IMODE(path.stat().st_mode) == 0o444
    finally:
        home.chmod(0o755)
        path.chmod(0o644)


def test_git_check_ignore_parent_exception_remote_blanket_and_local_cache(tmp_path):
    home = tmp_path / "repo"
    home.mkdir()
    git(home, "init")
    path = home / ".gitignore"
    path.write_text("# authored rules\n/skills/\n**/__pycache__/\n", encoding="utf-8")
    assert sync_gitignore(home, ["personal"]) is True
    local_skill(home, "personal")
    for relative in ("skills/remote/SKILL.md", "skills/personal/__pycache__/cached.pyc"):
        target = home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"data")
    (home / "skills" / "note.txt").write_bytes(b"note")
    assert ignored(home, "skills/remote/SKILL.md")
    assert ignored(home, "skills/note.txt")
    assert not ignored(home, "skills/personal/SKILL.md")
    assert ignored(home, "skills/personal/__pycache__/cached.pyc")


def test_manager_sync_exposes_only_desired_local_skills_and_keeps_handwritten_rules(repository, tmp_path):
    home = tmp_path / "home"
    for name in ("zeta", "alpha"):
        local_skill(home, name)
    path = home / ".gitignore"
    handwritten = b"# user's rules\n*.tmp\n"
    path.write_bytes(handwritten)
    save_config(home / "config.toml", {
        "zeta": SkillSpec("local"),
        "demo": SkillSpec(str(repository), "catalog/demo"),
        "alpha": SkillSpec("local"),
    })
    result = sync(home)
    assert result.updated == ("alpha", "demo", "zeta") and result.errors == {}
    assert path.read_bytes() == handwritten + block("alpha", "zeta").encode()
    assert (home / "skills" / "alpha" / "SKILL.md").read_text(encoding="utf-8") == markdown(name="alpha")
    assert (home / "skills" / "demo" / "SKILL.md").is_file()
    before = path.stat().st_mtime_ns
    assert sync(home).errors == {}
    assert path.stat().st_mtime_ns == before


def test_manager_sync_without_locals_still_generates_baseline(tmp_path):
    home = tmp_path / "home"
    save_config(home / "config.toml", {})
    result = sync(home)
    assert result.updated == result.removed == () and result.errors == {}
    assert (home / ".gitignore").read_bytes() == block().encode()


@pytest.mark.parametrize("problem", ["missing", "bad-config", "corrupt-state"])
def test_manager_invalid_inputs_do_not_change_gitignore_or_skill(tmp_path, problem):
    home = tmp_path / "home"
    target = local_skill(home, "personal")
    config = home / "config.toml"
    save_config(config, {"personal": SkillSpec("local")})
    assert sync(home).updated == ("personal",)
    path = home / ".gitignore"
    path.write_bytes(b"# handwritten only, no managed block\n")
    if problem == "missing":
        config.unlink()
    elif problem == "bad-config":
        config.write_bytes(b"not TOML = [")
    else:
        (home / ".state" / "installed.json").write_text(
            json.dumps({"version": 1, "skills": {"personal": {"target": "/tmp/other"}}}),
            encoding="utf-8",
        )
        save_config(config, {})
    original_config = config.read_bytes() if config.exists() else None
    original_state = installed_state(home)
    original_skill = (target / "SKILL.md").read_bytes()
    original_ignore = path.read_bytes()
    with pytest.raises(SkillError):
        sync(home)
    assert path.read_bytes() == original_ignore
    assert (target / "SKILL.md").read_bytes() == original_skill
    assert installed_state(home) == original_state
    assert (config.read_bytes() if config.exists() else None) == original_config


def test_manager_bad_gitignore_is_global_failure_before_skill_mutations(tmp_path):
    home = tmp_path / "home"
    old = local_skill(home, "old")
    new = local_skill(home, "new")
    config = home / "config.toml"
    save_config(config, {"old": SkillSpec("local")})
    assert sync(home).updated == ("old",)
    save_config(config, {"new": SkillSpec("local")})
    path = home / ".gitignore"
    broken = BEGIN.encode() + b"!/skills/\n"
    path.write_bytes(broken)
    before_state = installed_state(home)
    before_config = config.read_bytes()
    before_old = (old / "SKILL.md").read_bytes()
    before_new = (new / "SKILL.md").read_bytes()
    with pytest.raises(SkillError):
        sync(home)
    assert path.read_bytes() == broken
    assert installed_state(home) == before_state
    assert config.read_bytes() == before_config
    assert (old / "SKILL.md").read_bytes() == before_old
    assert (new / "SKILL.md").read_bytes() == before_new


def test_manager_keeps_desired_exceptions_even_when_later_item_fails(tmp_path):
    home = tmp_path / "home"
    old = local_skill(home, "old")
    local_skill(home, "good")
    save_config(home / "config.toml", {"old": SkillSpec("local")})
    assert sync(home).updated == ("old",)
    save_config(home / "config.toml", {
        "missing": SkillSpec("local"),
        "good": SkillSpec("local"),
    })
    result = sync(home)
    assert result.updated == ("good",) and result.removed == ("old",)
    assert result.errors.get("missing")
    assert not old.exists()
    assert not (home / "skills" / "missing").exists()
    assert (home / ".gitignore").read_bytes() == block("good", "missing").encode()
    assert set(json.loads(installed_state(home))["skills"]) == {"good"}
