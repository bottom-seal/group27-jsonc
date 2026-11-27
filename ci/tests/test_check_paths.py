"""Tests for ci/check_paths.py, the path rules every pull request must follow.

Each test builds a small throwaway git repo shaped like ours, commits a base,
makes the change a PR would make, and runs the script on the two commits.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check_paths.py"
FILES = ["json-c/json_tokener.c", "json-c/json_tokener.h", "oracle/check.py",
         "bughunt/README.md", "README.md", ".github/workflows/gate.yml"]


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "test")
    for f in FILES:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text(f"original {f}\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def change(repo, edit=(), delete=(), add=(), rename=()):
    for f in edit:
        (repo / f).write_text("changed\n")
    for f in add:
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_text("new\n")
    for f in delete:
        git(repo, "rm", "-q", f)
    for old, new in rename:
        git(repo, "mv", old, new)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "pr")
    return subprocess.run([sys.executable, str(SCRIPT), "HEAD~1", "HEAD"],
                          cwd=repo, capture_output=True, text=True)


def test_a_rewrite_that_only_changes_the_tokener_passes(repo):
    result = change(repo, edit=["json-c/json_tokener.c"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rewrite PR" in result.stdout


def test_a_pr_that_does_not_touch_the_tokener_may_change_the_gate(repo):
    # Role A's own PRs; they need Role A's approval through CODEOWNERS instead.
    result = change(repo, edit=["oracle/check.py", ".github/workflows/gate.yml", "README.md"])
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("extra", ["oracle/check.py", ".github/workflows/gate.yml", "README.md"])
def test_a_rewrite_may_not_change_anything_else(repo, extra):
    result = change(repo, edit=["json-c/json_tokener.c", extra])
    assert result.returncode == 1, result.stdout + result.stderr
    assert extra in result.stdout


def test_other_json_c_files_may_not_change(repo):
    result = change(repo, edit=["json-c/json_tokener.h"])
    assert result.returncode == 1, result.stdout + result.stderr
    assert "json-c/json_tokener.h" in result.stdout


def test_new_files_in_json_c_are_not_allowed(repo):
    # a rewrite must stay in json_tokener.c, so the checker compiles all of it
    result = change(repo, edit=["json-c/json_tokener.c"], add=["json-c/json_tokener_states.c"])
    assert result.returncode == 1, result.stdout + result.stderr
    assert "json-c/json_tokener_states.c" in result.stdout


def test_the_tokener_may_not_be_deleted_or_renamed(repo):
    result = change(repo, rename=[("json-c/json_tokener.c", "json-c/tokener.c")])
    assert result.returncode == 1, result.stdout + result.stderr
    assert "json-c/json_tokener.c" in result.stdout


def test_the_bug_hunt_record_is_read_only(repo):
    result = change(repo, edit=["bughunt/README.md"])
    assert result.returncode == 1, result.stdout + result.stderr
    assert "bughunt/README.md" in result.stdout
