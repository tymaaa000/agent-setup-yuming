"""Black-box fixtures for the public skillctl contracts."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Import only the public modules named in contracts.py; never import internals.
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))


def markdown(name="demo", *, invocation=True, body="\n# Instructions\nKeep this body.\n"):
    flag = "true" if invocation else "false"
    return (
        f"---\nname: {name}\ndescription: Example skill\n"
        f"disable-model-invocation: {flag}\n---\n{body}"
    )


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def commit(repo: Path, message="revision") -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test Author")
    git(repo, "config", "user.email", "test@example.invalid")
    skill = repo / "catalog" / "demo"
    (skill / "scripts").mkdir(parents=True)
    (skill / "assets").mkdir()
    (skill / "SKILL.md").write_text(markdown(), encoding="utf-8")
    (skill / "scripts" / "run.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (skill / "scripts" / "run.sh").chmod(0o755)
    (skill / "assets" / "data.bin").write_bytes(b"\x00\xff\x01")
    (skill / ".hidden").write_text("secret\n", encoding="utf-8")
    (repo / "not-selected.txt").write_text("not a skill", encoding="utf-8")
    commit(repo, "initial")
    return repo


def skill_dir(repo):
    return repo / "catalog" / "demo"


def python_environment(home: Path):
    env = os.environ.copy()
    env["SKILLCTL_HOME"] = str(home)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return env
