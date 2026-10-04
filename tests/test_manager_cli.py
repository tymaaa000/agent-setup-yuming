"""Black-box sync and CLI tests against contracts.py only."""

import json
import os
import shutil
import subprocess
import sys

import pytest
from ruamel.yaml import YAML

from skillctl.cli import main
from skillctl.config import save_config
from skillctl.contracts import SkillError, SkillSpec
from skillctl.manager import default_home, sync
from skillctl.store import tree_hash

from conftest import commit, git, markdown, python_environment, skill_dir


def state(home):
    return json.loads((home / ".state" / "installed.json").read_text(encoding="utf-8"))


def configure(home, specs):
    save_config(home / "config.toml", specs)


def demo_spec(repository, override=None):
    return SkillSpec(str(repository), "catalog/demo", frontmatter=override or {})


def test_sync_first_install_tracks_complete_tree_and_preserves_unrelated_files(repository, tmp_path):
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "skills" / "unrelated.txt").write_text("leave alone", encoding="utf-8")
    (home / "notes.txt").write_text("untouched\n", encoding="utf-8")
    configure(home, {"demo": demo_spec(repository)})
    original_config = (home / "config.toml").read_bytes()

    result = sync(home)
    assert result.updated == ("demo",) and result.removed == () and result.errors == {}
    installed = home / "skills" / "demo"
    assert (installed / ".hidden").read_text(encoding="utf-8") == "secret\n"
    assert (installed / "assets" / "data.bin").read_bytes() == b"\x00\xff\x01"
    assert (installed / "scripts" / "run.sh").stat().st_mode & 0o111
    assert state(home) == {
        "version": 1,
        "skills": {"demo": {"commit": git(repository, "rev-parse", "HEAD"), "hash": tree_hash(installed)}},
    }
    assert (home / "config.toml").read_bytes() == original_config
    assert (home / "skills" / "unrelated.txt").read_text(encoding="utf-8") == "leave alone"
    assert (home / "notes.txt").read_text(encoding="utf-8") == "untouched\n"


def test_sync_refreshes_source_and_reapplies_true_false_and_inheritance(repository, tmp_path):
    home = tmp_path / "home"
    target = home / "skills" / "demo"
    configure(home, {"demo": demo_spec(repository, {"disable-model-invocation": False})})
    assert sync(home).updated == ("demo",)
    assert "disable-model-invocation: false" in (target / "SKILL.md").read_text(encoding="utf-8")
    assert sync(home).updated == ("demo",)  # Same commit still applies the override.

    configure(home, {"demo": demo_spec(repository, {"disable-model-invocation": True})})
    assert sync(home).errors == {}
    assert "disable-model-invocation: true" in (target / "SKILL.md").read_text(encoding="utf-8")
    configure(home, {"demo": demo_spec(repository)})
    assert sync(home).errors == {}
    assert "disable-model-invocation: true" in (target / "SKILL.md").read_text(encoding="utf-8")

    (skill_dir(repository) / "SKILL.md").write_text(markdown(invocation=False, body="\nNEW REVISION\n"), encoding="utf-8")
    revision = commit(repository, "upstream changed")
    before_config = (home / "config.toml").read_bytes()
    assert sync(home).updated == ("demo",)
    assert "disable-model-invocation: false" in (target / "SKILL.md").read_text(encoding="utf-8")
    assert "NEW REVISION" in (target / "SKILL.md").read_text(encoding="utf-8")
    assert state(home)["skills"]["demo"] == {"commit": revision, "hash": tree_hash(target)}
    assert (home / "config.toml").read_bytes() == before_config


def test_sync_arbitrary_config_frontmatter_and_name_safety(repository, tmp_path):
    home = tmp_path / "home"
    target = home / "skills" / "demo" / "SKILL.md"
    config = home / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        f'[[skills]]\nname = "demo"\nrepo = "{repository}"\npath = "catalog/demo"\n'
        'frontmatter = { description = "configured", count = 8, active = false, '
        'tags = ["one", "two"], settings = { nested = { key = "value", at = 10:11:12 } } }\n',
        encoding="utf-8",
    )
    before = config.read_bytes()
    assert sync(home).errors == {}
    rendered = target.read_text(encoding="utf-8")
    metadata = YAML(typ="safe").load(rendered.split("---", 2)[1])
    assert metadata["description"] == "configured"
    assert metadata["settings"] == {"nested": {"key": "value", "at": "10:11:12"}}
    assert metadata["tags"] == ["one", "two"]
    assert metadata["count"] == 8 and metadata["active"] is False
    assert rendered.endswith("# Instructions\nKeep this body.\n")
    assert sync(home).errors == {}
    assert target.read_text(encoding="utf-8") == rendered
    assert config.read_bytes() == before
    config.write_text(config.read_text(encoding="utf-8").replace(
        'description = "configured"', 'name = "other", description = "configured"'), encoding="utf-8")
    result = sync(home)
    assert "demo" in result.errors
    assert target.read_text(encoding="utf-8") == rendered


def test_sync_config_deletion_removes_only_tracked_skills(repository, tmp_path):
    home = tmp_path / "home"
    other = skill_dir(repository).parent / "other"
    other.mkdir()
    (other / "SKILL.md").write_text(markdown(name="other"), encoding="utf-8")
    commit(repository, "add other")
    configure(home, {
        "demo": demo_spec(repository),
        "other": SkillSpec(str(repository), "catalog/other"),
    })
    assert sync(home).updated == ("demo", "other")
    configure(home, {"other": SkillSpec(str(repository), "catalog/other")})
    config_bytes = (home / "config.toml").read_bytes()
    result = sync(home)
    assert result.updated == ("other",) and result.removed == ("demo",) and result.errors == {}
    assert not (home / "skills" / "demo").exists()
    assert (home / "skills" / "other" / "SKILL.md").is_file()
    assert set(state(home)["skills"]) == {"other"}
    assert (home / "config.toml").read_bytes() == config_bytes


def test_empty_config_cleans_managed_but_not_self_authored_or_unrelated(repository, tmp_path):
    home = tmp_path / "home"
    configure(home, {"demo": demo_spec(repository)})
    sync(home)
    personal = home / "skills" / "personal"
    personal.mkdir()
    (personal / "SKILL.md").write_text(markdown(name="personal"), encoding="utf-8")
    (home / "skills" / "note.txt").write_text("keep", encoding="utf-8")
    configure(home, {})
    before = (home / "config.toml").read_bytes()
    result = sync(home)
    assert result.updated == () and result.removed == ("demo",) and result.errors == {}
    assert state(home) == {"version": 1, "skills": {}}
    assert not (home / "skills" / "demo").exists()
    assert (personal / "SKILL.md").read_text(encoding="utf-8") == markdown(name="personal")
    assert (home / "skills" / "note.txt").read_text(encoding="utf-8") == "keep"
    assert (home / "config.toml").read_bytes() == before
    assert sync(home).updated == sync(home).removed == ()


def test_sync_rejects_untracked_target_and_upstream_name_mismatch(repository, tmp_path):
    home = tmp_path / "home"
    target = home / "skills" / "demo"
    target.mkdir(parents=True)
    (target / "keep").write_text("do not replace", encoding="utf-8")
    configure(home, {"demo": demo_spec(repository), "wrong": demo_spec(repository)})
    result = sync(home)
    assert result.updated == () and result.removed == ()
    assert set(result.errors) == {"demo", "wrong"}
    assert all(result.errors.values())
    assert (target / "keep").read_text(encoding="utf-8") == "do not replace"
    assert not (home / "skills" / "wrong").exists()
    if (home / ".state" / "installed.json").exists():
        assert state(home)["skills"] == {}


@pytest.mark.parametrize("bad_config", ["missing", "malformed", "symlink", "directory"])
def test_sync_invalid_config_fails_closed_without_deleting_tracked_skill(repository, tmp_path, bad_config):
    home = tmp_path / "home"
    configure(home, {"demo": demo_spec(repository)})
    sync(home)
    previous = state(home)
    config = home / "config.toml"
    config.unlink()
    if bad_config == "malformed":
        config.write_text("not TOML = [", encoding="utf-8")
    elif bad_config == "symlink":
        outside = tmp_path / "outside.toml"
        outside.write_text("", encoding="utf-8")
        config.symlink_to(outside)
    elif bad_config == "directory":
        config.mkdir()
    with pytest.raises(SkillError):
        sync(home)
    assert (home / "skills" / "demo" / "SKILL.md").is_file()
    assert state(home) == previous


def test_sync_duplicate_config_fails_without_touching_installed_skills(repository, tmp_path):
    home = tmp_path / "home"
    configure(home, {"demo": demo_spec(repository)})
    assert sync(home).updated == ("demo",)
    installed = home / "skills" / "demo"
    before_hash = tree_hash(installed)
    before_skill = (installed / "SKILL.md").read_bytes()
    before_state = (home / ".state" / "installed.json").read_bytes()
    config = home / "config.toml"
    config.write_text(
        '[[skills]]\nname = "demo"\nrepo = "local"\n'
        '[[skills]]\nname = "demo"\nrepo = "local"\n',
        encoding="utf-8",
    )
    before_config = config.read_bytes()

    with pytest.raises(SkillError):
        sync(home)

    assert tree_hash(installed) == before_hash
    assert (installed / "SKILL.md").read_bytes() == before_skill
    assert (home / ".state" / "installed.json").read_bytes() == before_state
    assert config.read_bytes() == before_config


def test_corrupt_state_fails_closed_even_with_empty_config(repository, tmp_path):
    home = tmp_path / "home"
    configure(home, {"demo": demo_spec(repository)})
    sync(home)
    configure(home, {})
    (home / ".state" / "installed.json").write_text(
        '{"version": 1, "skills": {"demo": {"target": "/tmp/elsewhere"}}}', encoding="utf-8"
    )
    with pytest.raises(SkillError):
        sync(home)
    assert (home / "skills" / "demo" / "SKILL.md").is_file()


@pytest.mark.parametrize("mode", ["update", "remove"])
def test_sync_refuses_local_changes_and_keeps_record_for_retry(repository, tmp_path, mode):
    home = tmp_path / "home"
    configure(home, {"demo": demo_spec(repository)})
    sync(home)
    target = home / "skills" / "demo"
    (target / "local").write_text("changed", encoding="utf-8")
    previous = state(home)
    if mode == "remove":
        configure(home, {})
    before = (home / "config.toml").read_bytes()
    result = sync(home)
    assert result.updated == result.removed == ()
    assert result.errors.get("demo")
    assert (target / "local").read_text(encoding="utf-8") == "changed"
    assert state(home) == previous
    assert (home / "config.toml").read_bytes() == before
    (target / "local").unlink()
    retry = sync(home)
    assert (retry.removed if mode == "remove" else retry.updated) == ("demo",)


@pytest.mark.parametrize("mode", ["update", "remove"])
def test_sync_refuses_symlink_target_without_touching_outside(repository, tmp_path, mode):
    home = tmp_path / "home"
    configure(home, {"demo": demo_spec(repository)})
    sync(home)
    previous = state(home)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("untouched", encoding="utf-8")
    target = home / "skills" / "demo"
    shutil.rmtree(target)
    target.symlink_to(outside, target_is_directory=True)
    if mode == "remove":
        configure(home, {})
    result = sync(home)
    assert result.errors.get("demo")
    assert result.updated == result.removed == ()
    assert target.is_symlink()
    assert (outside / "keep").read_text(encoding="utf-8") == "untouched"
    assert state(home) == previous


def test_missing_tracked_target_reinstalls_or_clears_record(repository, tmp_path):
    home = tmp_path / "home"
    configure(home, {"demo": demo_spec(repository)})
    sync(home)
    shutil.rmtree(home / "skills" / "demo")
    assert sync(home).updated == ("demo",)
    assert state(home)["skills"]["demo"]["hash"] == tree_hash(home / "skills" / "demo")
    shutil.rmtree(home / "skills" / "demo")
    configure(home, {})
    result = sync(home)
    assert result.removed == ("demo",) and result.errors == {}
    assert state(home)["skills"] == {}


def test_per_item_failure_continues_through_install_and_removal(repository, tmp_path):
    home = tmp_path / "home"
    other = skill_dir(repository).parent / "other"
    other.mkdir()
    (other / "SKILL.md").write_text(markdown(name="other"), encoding="utf-8")
    commit(repository, "add other")
    configure(home, {"demo": demo_spec(repository)})
    sync(home)
    configure(home, {
        "bad": SkillSpec(str(repository), "catalog/missing"),
        "other": SkillSpec(str(repository), "catalog/other"),
    })
    before = (home / "config.toml").read_bytes()
    result = sync(home)
    assert result.updated == ("other",) and result.removed == ("demo",)
    assert result.errors.get("bad")
    assert set(state(home)["skills"]) == {"other"}
    assert not (home / "skills" / "demo").exists()
    assert (home / "config.toml").read_bytes() == before


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory permissions")
def test_state_write_failure_rolls_back_target_and_state_but_not_config(repository, tmp_path):
    home = tmp_path / "home"
    configure(home, {"demo": demo_spec(repository)})
    sync(home)
    target = home / "skills" / "demo"
    old_hash = tree_hash(target)
    old_skill = (target / "SKILL.md").read_bytes()
    state_dir = home / ".state"
    state_file = state_dir / "installed.json"
    old_state = state_file.read_bytes()
    (skill_dir(repository) / "SKILL.md").write_text(markdown(body="\nupstream change\n"), encoding="utf-8")
    commit(repository, "upstream revision")
    configure(home, {"demo": demo_spec(repository, {"disable-model-invocation": False})})
    new_config = (home / "config.toml").read_bytes()
    state_file.chmod(0o444)
    state_dir.chmod(0o555)
    try:
        result = sync(home)
    finally:
        state_dir.chmod(0o755)
        state_file.chmod(0o644)
    assert result.updated == () and result.errors.get("demo")
    assert tree_hash(target) == old_hash
    assert (target / "SKILL.md").read_bytes() == old_skill
    assert state_file.read_bytes() == old_state
    assert (home / "config.toml").read_bytes() == new_config


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory permissions")
def test_local_state_write_failure_rolls_back_complete_target_with_readonly_assets(tmp_path):
    home = tmp_path / "home"
    target = home / "skills" / "personal"
    assets = target / "assets"
    assets.mkdir(parents=True)
    (target / "SKILL.md").write_text(markdown(name="personal"), encoding="utf-8")
    (assets / "x").write_bytes(b"\x00\xfforiginal")
    configure(home, {"personal": SkillSpec("local")})
    assert sync(home).updated == ("personal",)

    # Preserve an unwritable nested directory while the override changes SKILL.md.
    assets.chmod(0o555)
    old_skill = (target / "SKILL.md").read_bytes()
    old_asset = (assets / "x").read_bytes()
    old_hash = tree_hash(target)
    state_dir = home / ".state"
    state_file = state_dir / "installed.json"
    old_state = state_file.read_bytes()
    (state_dir / "staging").mkdir(exist_ok=True)
    (state_dir / "operation.lock").touch(exist_ok=True)
    configure(home, {"personal": SkillSpec("local", frontmatter={"disable-model-invocation": False})})
    new_config = (home / "config.toml").read_bytes()
    state_file.chmod(0o444)
    state_dir.chmod(0o555)
    try:
        result = sync(home)
        asset_mode = assets.stat().st_mode & 0o777
    finally:
        state_dir.chmod(0o755)
        state_file.chmod(0o644)
        if assets.is_dir():
            assets.chmod(0o755)
    assert result.updated == result.removed == () and result.errors.get("personal")
    assert asset_mode == 0o555
    assert (target / "SKILL.md").read_bytes() == old_skill
    assert (assets / "x").read_bytes() == old_asset
    assert tree_hash(target) == old_hash
    assert state_file.read_bytes() == old_state
    assert (home / "config.toml").read_bytes() == new_config


def test_explicit_local_adoption_preserves_authored_files_and_edits_without_git(tmp_path):
    home = tmp_path / "home"
    target = home / "skills" / "personal"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(markdown(name="personal"), encoding="utf-8")
    (target / "notes.txt").write_text("authored", encoding="utf-8")
    configure(home, {"personal": SkillSpec("local")})
    config_bytes = (home / "config.toml").read_bytes()
    # There is no repository anywhere in this fixture: local sync must not fetch.
    assert sync(home).updated == ("personal",)
    assert state(home) == {"version": 1, "skills": {"personal": {"kind": "local", "hash": tree_hash(target)}}}
    (target / "notes.txt").write_text("edited after sync", encoding="utf-8")
    (target / "SKILL.md").write_text(markdown(name="personal", body="\nlocal edit\n"), encoding="utf-8")
    result = sync(home)
    assert result.updated == ("personal",) and result.errors == {}
    assert (target / "notes.txt").read_text(encoding="utf-8") == "edited after sync"
    assert "local edit" in (target / "SKILL.md").read_text(encoding="utf-8")
    assert state(home)["skills"]["personal"] == {"kind": "local", "hash": tree_hash(target)}
    assert (home / "config.toml").read_bytes() == config_bytes


@pytest.mark.parametrize("record", [
    {"kind": "unknown", "hash": "abc"},
    {"kind": "local", "hash": "abc", "commit": "invented"},
])
def test_corrupt_local_state_fails_closed(tmp_path, record):
    home = tmp_path / "home"
    target = home / "skills" / "personal"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(markdown(name="personal"), encoding="utf-8")
    configure(home, {"personal": SkillSpec("local")})
    sync(home)
    state_file = home / ".state" / "installed.json"
    state_file.write_text(json.dumps({"version": 1, "skills": {"personal": record}}), encoding="utf-8")
    configure(home, {})
    with pytest.raises(SkillError):
        sync(home)
    assert (target / "SKILL.md").read_text(encoding="utf-8") == markdown(name="personal")


def test_local_adoption_rejects_symlink_target(tmp_path):
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text(markdown(name="personal"), encoding="utf-8")
    (home / "skills").mkdir(parents=True)
    target = home / "skills" / "personal"
    target.symlink_to(outside, target_is_directory=True)
    configure(home, {"personal": SkillSpec("local")})
    result = sync(home)
    assert result.errors.get("personal") and result.updated == ()
    assert target.is_symlink()
    assert (outside / "SKILL.md").read_text(encoding="utf-8") == markdown(name="personal")


def test_local_override_applies_to_current_content_and_removal_keeps_value(tmp_path):
    home = tmp_path / "home"
    target = home / "skills" / "personal"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(markdown(name="personal", invocation=True), encoding="utf-8")
    (target / "asset").write_bytes(b"\x00\xff")
    configure(home, {"personal": SkillSpec("local", frontmatter={"disable-model-invocation": False})})
    assert sync(home).updated == ("personal",)
    assert "disable-model-invocation: false" in (target / "SKILL.md").read_text(encoding="utf-8")
    configure(home, {"personal": SkillSpec("local", frontmatter={"disable-model-invocation": True})})
    assert sync(home).updated == ("personal",)
    assert "disable-model-invocation: true" in (target / "SKILL.md").read_text(encoding="utf-8")
    configure(home, {"personal": SkillSpec("local")})
    assert sync(home).updated == ("personal",)
    assert "disable-model-invocation: true" in (target / "SKILL.md").read_text(encoding="utf-8")
    assert (target / "asset").read_bytes() == b"\x00\xff"


@pytest.mark.parametrize("problem", ["missing", "mismatch", "symlink", "invalid"])
def test_local_adoption_rejects_missing_mismatched_linked_or_invalid_tree(tmp_path, problem):
    home = tmp_path / "home"
    target = home / "skills" / "personal"
    if problem != "missing":
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text(
            markdown(name="different" if problem == "mismatch" else "personal"), encoding="utf-8"
        )
        if problem == "symlink":
            (target / "linked").symlink_to("SKILL.md")
        if problem == "invalid":
            (target / "SKILL.md").write_text("invalid metadata", encoding="utf-8")
    configure(home, {"personal": SkillSpec("local", frontmatter={"disable-model-invocation": False})})
    old_bytes = (target / "SKILL.md").read_bytes() if target.exists() else None
    result = sync(home)
    assert result.updated == () and result.removed == () and result.errors.get("personal")
    assert ((target / "SKILL.md").read_bytes() if target.exists() else None) == old_bytes
    if (home / ".state" / "installed.json").exists():
        assert "personal" not in state(home)["skills"]


@pytest.mark.parametrize("edited", [False, True])
def test_removing_local_config_deletes_only_unchanged_tracked_local(tmp_path, edited):
    home = tmp_path / "home"
    target = home / "skills" / "personal"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(markdown(name="personal"), encoding="utf-8")
    untracked = home / "skills" / "untracked"
    untracked.mkdir()
    (untracked / "SKILL.md").write_text(markdown(name="untracked"), encoding="utf-8")
    configure(home, {"personal": SkillSpec("local")})
    assert sync(home).updated == ("personal",)
    if edited:
        (target / "SKILL.md").write_text(markdown(name="personal", body="\nunsynced edit\n"), encoding="utf-8")
    configure(home, {})
    result = sync(home)
    if edited:
        assert result.removed == () and result.errors.get("personal")
        assert "personal" in state(home)["skills"]
        assert "unsynced edit" in (target / "SKILL.md").read_text(encoding="utf-8")
    else:
        assert result.removed == ("personal",) and result.errors == {}
        assert not target.exists()
        assert state(home)["skills"] == {}
    assert (untracked / "SKILL.md").is_file()


def test_parallel_syncs_serialize_and_leave_consistent_state(repository, tmp_path):
    home = tmp_path / "parallel-home"
    configure(home, {"demo": demo_spec(repository)})
    script = "from skillctl.cli import main; import sys; sys.exit(main(['sync']))"
    env = python_environment(home)
    processes = [
        subprocess.Popen([sys.executable, "-c", script], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    results = [p.communicate(timeout=30) for p in processes]
    assert [p.returncode for p in processes] == [0, 0], results
    assert state(home)["skills"]["demo"] == {
        "commit": git(repository, "rev-parse", "HEAD"), "hash": tree_hash(home / "skills" / "demo")
    }
    assert all("Traceback" not in out + err for out, err in results)


def test_default_home_and_cli_sync_success_empty_failure_and_legacy_usage(repository, tmp_path, monkeypatch, capsys):
    home = tmp_path / "custom-home"
    monkeypatch.setenv("SKILLCTL_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    assert default_home() == home.resolve()
    configure(home, {"demo": demo_spec(repository)})
    assert main(["sync"]) == 0
    output = capsys.readouterr()
    assert "Updated demo" in output.out and "/reload" in output.out
    configure(home, {})
    assert main(["sync"]) == 0
    output = capsys.readouterr()
    assert "Removed demo" in output.out and "/reload" in output.out
    assert main(["sync"]) == 0
    assert "Nothing to sync." in capsys.readouterr().out
    for args in (["add", str(repository)], ["update"], ["remove", "demo"], ["sync", "demo"], ["sync", "--path", "catalog/demo"]):
        with pytest.raises(SystemExit) as exc:
            main(args)
        assert exc.value.code == 2
    (home / "config.toml").unlink()
    assert main(["sync"]) == 1
    output = capsys.readouterr()
    assert "Traceback" not in output.err + output.out
