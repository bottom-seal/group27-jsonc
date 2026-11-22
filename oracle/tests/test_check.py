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


def test_fixing_a_known_bug_counts_as_a_difference(tmp_path):
    # Bug 4: STRICT accepts single-quoted object keys. A rewrite that quietly
    # fixes it changes behaviour, so the gate must reject it.
    fixed = candidate(
        tmp_path,
        "else if (c == '\"' || c == '\\'')",
        "else if (c == '\"' || (c == '\\'' && !(tok->flags & JSON_TOKENER_STRICT)))",
    )
    result = run_check(fixed)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL" in result.stdout
    assert "{'a':0}" in result.stdout  # the report names a differing input
    assert "strict" in result.stdout  # ... and the config it differed under


PARSE_EX_START = "\tstruct json_object *obj = NULL;\n\tchar c = '\\1';\n"


def test_crash_is_reported_with_the_input_it_crashed_on(tmp_path):
    crashing = candidate(
        tmp_path,
        PARSE_EX_START,
        PARSE_EX_START + "\tif (len >= 2 && str[0] == '[' && str[1] == ']')\n"
                         "\t\t*(volatile int *)0 = 1; /* planted crash */\n",
    )
    result = run_check(crashing)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "CRASH" in result.stdout
    assert "input #50: []" in result.stdout  # first "[]" in oracle/inputs/core.txt
