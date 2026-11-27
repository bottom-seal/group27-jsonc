"""Tests for fuzz/fuzz.py. Each builds the differential fuzzer (the rest of
json-c is built once into .build/fuzz) and runs it briefly from the gate's
inputs only, so the results do not depend on luck."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FUZZ = REPO / "fuzz" / "fuzz.py"


def baseline_with(tmp_path: Path, old: str = "", new: str = "", after: str = "") -> Path:
    src = subprocess.run(["git", "show", "baseline:json-c/json_tokener.c"], cwd=REPO, check=True,
                         capture_output=True, text=True).stdout
    if old:
        at = src.index(old, src.index(after) if after else 0)
        src = src[:at] + new + src[at + len(old):]
    path = tmp_path / "json_tokener.c"
    path.write_text(src)
    return path


def run_fuzz(cand: Path, seconds: int) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(FUZZ), str(cand), "--seconds", str(seconds), "--no-corpus"],
                          cwd=REPO, capture_output=True, text=True, timeout=900)


def test_the_baseline_against_itself_finds_nothing(tmp_path):
    result = run_fuzz(baseline_with(tmp_path), 15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NOTHING FOUND" in result.stdout


def test_a_difference_is_found_and_printed_as_an_input_line(tmp_path):
    # An object end accepted for any character from '}' up: a gate input with
    # "~" after a value in an object shows it at once.
    mistake = baseline_with(tmp_path, "if (c == '}')", "if (c >= '}')", after="case json_tokener_state_object_sep:")
    result = run_fuzz(mistake, 120)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "DIFFERENCE" in result.stdout and "--- candidate:" in result.stdout
    assert "as a line for oracle/inputs/fuzz.txt" in result.stdout


def test_a_candidate_that_does_not_build_is_a_build_error(tmp_path):
    broken = baseline_with(tmp_path, "\tstruct json_object *obj = NULL;\n",
                           "\tstruct json_object *obj = NULL;\n\tthis does not compile;\n")
    result = run_fuzz(broken, 5)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "BUILD ERROR" in result.stdout
