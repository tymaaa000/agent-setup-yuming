import os
import pytest

from skillctl.contracts import SkillError, SkillSpec
from skillctl.source import fetch_skill
from skillctl.store import install_skill, tree_hash

from conftest import commit, git, markdown, skill_dir


def fetch(tmp_path, repo, *, path="catalog/demo", ref=None):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = fetch_skill(SkillSpec(str(repo), path, ref), workspace)
    return result, workspace


def test_fetch_full_selected_subtree_and_resolved_commit(repository, tmp_path):
    result, workspace = fetch(tmp_path, repository)
    assert result.commit == git(repository, "rev-parse", "HEAD")
    assert len(result.commit) == 40
    assert result.directory.is_relative_to(workspace)
    assert (result.directory / "SKILL.md").read_bytes() == (skill_dir(repository) / "SKILL.md").read_bytes()
    assert (result.directory / "assets" / "data.bin").read_bytes() == b"\x00\xff\x01"
    assert (result.directory / "scripts" / "run.sh").stat().st_mode & 0o111
    assert (result.directory / ".hidden").read_text(encoding="utf-8") == "secret\n"
    assert not (result.directory / ".git").exists()
    assert not (result.directory / "not-selected.txt").exists()
    assert not any(p.name == ".git" for p in result.directory.rglob(".git"))


@pytest.mark.parametrize("branch", ["release+fix", "版本/修复"])
def test_fetch_accepts_valid_non_ascii_or_plus_branch(repository, tmp_path, branch):
    git(repository, "branch", branch)
    result, _ = fetch(tmp_path, repository, ref=branch)
    assert result.commit == git(repository, "rev-parse", branch)
    assert (result.directory / "SKILL.md").is_file()


def test_fetch_ref_uses_exact_revision_not_latest(repository, tmp_path):
    original = git(repository, "rev-parse", "HEAD")
    git(repository, "tag", "old-version")
    (skill_dir(repository) / "SKILL.md").write_text(markdown(body="\nNEW REVISION\n"), encoding="utf-8")
    latest = commit(repository, "new version")
    old, _ = fetch(tmp_path, repository, ref="old-version")
    assert old.commit == original
    assert "NEW REVISION" not in (old.directory / "SKILL.md").read_text(encoding="utf-8")
    current_workspace = tmp_path / "current"
    current_workspace.mkdir()
    current = fetch_skill(SkillSpec(str(repository), "catalog/demo", latest), current_workspace)
    assert current.commit == latest
    assert "NEW REVISION" in (current.directory / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ["../demo", "catalog/../demo", "/catalog/demo", "catalog\\demo", "missing"])
def test_fetch_rejects_unsafe_or_missing_subpaths(repository, tmp_path, path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(SkillError):
        fetch_skill(SkillSpec(str(repository), path), workspace)


@pytest.mark.parametrize(
    "repo,ref",
    [
        ("file:///tmp/repo", None),
        ("ext::/definitely/not-a-real-executable", None),
        ("ftp://127.0.0.1:1/not-a-repository.git", None),
        ("-c core.hooksPath=x", None),
        ("/tmp/anything", "--upload-pack=evil"),
        ("/tmp/anything", "nonexistent"),
    ],
)
def test_fetch_rejects_invalid_source_or_ref(repository, tmp_path, repo, ref):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(SkillError):
        fetch_skill(SkillSpec(str(repository) if repo == "/tmp/anything" else repo, "catalog/demo", ref), workspace)


def test_fetch_rejects_invalid_spec_before_touching_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(SkillError, match="Invalid skill specification"):
        fetch_skill({}, workspace)
    assert list(workspace.iterdir()) == []


def test_fetch_rejects_symlinks_submodules_and_invalid_metadata(repository, tmp_path):
    source = skill_dir(repository)
    (source / "linked").symlink_to(source / "SKILL.md")
    commit(repository, "symlink")
    workspace = tmp_path / "symlink-fetch"
    workspace.mkdir()
    with pytest.raises(SkillError):
        fetch_skill(SkillSpec(str(repository), "catalog/demo"), workspace)
    (source / "linked").unlink()
    (source / "SKILL.md").write_text(markdown(name="invalid_name"), encoding="utf-8")
    commit(repository, "bad metadata")
    other = tmp_path / "invalid-fetch"
    other.mkdir()
    with pytest.raises(SkillError):
        fetch_skill(SkillSpec(str(repository), "catalog/demo"), other)


def test_tree_hash_is_stable_for_mtime_and_changes_for_tree_content_and_mode(tmp_path):
    source = tmp_path / "skill"
    source.mkdir()
    (source / "SKILL.md").write_text(markdown(), encoding="utf-8")
    original = tree_hash(source)
    os.utime(source / "SKILL.md", (123456789, 123456789))
    assert tree_hash(source) == original
    extra = source / ".extra"
    extra.write_bytes(b"a")
    added = tree_hash(source)
    assert added != original
    extra.write_bytes(b"b")
    changed = tree_hash(source)
    assert changed != added
    extra.chmod(0o755)
    executable = tree_hash(source)
    assert executable != changed
    extra.unlink()
    assert tree_hash(source) == original
    (source / "link").symlink_to("SKILL.md")
    with pytest.raises(SkillError):
        tree_hash(source)


def test_install_replaces_only_matching_target_and_preserves_source(repository, tmp_path):
    source = skill_dir(repository)
    target = tmp_path / "skills" / "demo"
    target.parent.mkdir()
    initial = install_skill(source, target)
    assert initial == tree_hash(source) == tree_hash(target)
    assert (target / ".hidden").read_bytes() == (source / ".hidden").read_bytes()
    with pytest.raises(SkillError):
        install_skill(source, target)
    (source / "assets" / "data.bin").write_bytes(b"updated")
    updated = install_skill(source, target, initial)
    assert updated != initial
    assert tree_hash(target) == updated
    assert (source / "assets" / "data.bin").read_bytes() == b"updated"
    (target / "SKILL.md").write_text(markdown(body="\nlocal change\n"), encoding="utf-8")
    before = tree_hash(target)
    with pytest.raises(SkillError):
        install_skill(source, target, updated)
    assert tree_hash(target) == before
    assert (source / "assets" / "data.bin").read_bytes() == b"updated"


def test_install_to_state_staging_path_is_successful_or_safely_rejected(repository, tmp_path):
    source = skill_dir(repository)
    target = tmp_path / "home" / ".state" / "staging"
    target.parent.mkdir(parents=True)
    try:
        installed_hash = install_skill(source, target)
    except SkillError:
        assert not target.exists() and not target.is_symlink()
    else:
        assert installed_hash == tree_hash(target) == tree_hash(source)
    assert (source / "SKILL.md").is_file()


def test_install_refuses_symlink_target_overlap_and_bad_source(repository, tmp_path):
    source = skill_dir(repository)
    target = tmp_path / "demo"
    target.symlink_to(source, target_is_directory=True)
    with pytest.raises(SkillError):
        install_skill(source, target)
    target.unlink()
    target.symlink_to(tmp_path / "nonexistent", target_is_directory=True)
    with pytest.raises(SkillError):
        install_skill(source, target)
    target.unlink()
    with pytest.raises(SkillError):
        install_skill(source, source / "nested")
    assert not (source / "nested").exists()
    (source / "SKILL.md").write_text("invalid", encoding="utf-8")
    with pytest.raises(SkillError):
        install_skill(source, target)
    assert not target.exists()
