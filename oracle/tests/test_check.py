"""End-to-end tests for the checker (seam 1).

Each test builds a candidate json_tokener.c from the baseline source, runs
`oracle/check.py` on it and checks the verdict. These compile C code, so the
first run takes a minute (it builds json-c once into .build/); later runs reuse
that build.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "oracle" / "check.py"


def baseline_source() -> str:
    return subprocess.run(
        ["git", "show", "baseline:json-c/json_tokener.c"],
        cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout


def candidate(tmp_path: Path, old: str = "", new: str = "") -> Path:
    """Write the baseline tokener with one exact text replacement applied."""
    src = baseline_source()
    if old:
        assert src.count(old) == 1, f"replacement anchor must be unique: {old!r}"
        src = src.replace(old, new)
    path = tmp_path / "json_tokener.c"
    path.write_text(src)
    return path


def run_check(cand: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK), str(cand), *extra],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )


def test_unchanged_tokener_passes(tmp_path):
    result = run_check(candidate(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout
