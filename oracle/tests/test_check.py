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


# Fixes from bughunt/local_fixes_findings_1-5.patch. Each one changes behaviour,
# so the gate must reject it; the expected text is the input that shows the bug.
KNOWN_BUG_FIXES = {
    "bug1-unclosed-comment-after-value": (
        "\t\tif (state != json_tokener_state_finish && saved_state != json_tokener_state_finish)",
        "\t\tif ((state != json_tokener_state_finish && saved_state != json_tokener_state_finish) ||\n"
        "\t\t    (tok->err == json_tokener_success && tok->depth > 0))",
    ),
    "bug2-even-stars-close-comment": (
        "\t\t\telse\n\t\t\t{\n\t\t\t\tstate = json_tokener_state_comment;\n\t\t\t}",
        "\t\t\telse if (c != '*')\n\t\t\t{\n\t\t\t\tstate = json_tokener_state_comment;\n\t\t\t}",
    ),
    "bug3-utf8-lookahead-after-value": (
        "if ((tok->flags & JSON_TOKENER_VALIDATE_UTF8) && (nBytes != 0))",
        "if ((tok->flags & JSON_TOKENER_VALIDATE_UTF8) && (nBytes != 0) && tok->err != json_tokener_success)",
    ),
}


@pytest.mark.parametrize("bug", sorted(KNOWN_BUG_FIXES))
def test_fixing_any_known_bug_is_rejected(tmp_path, bug):
    old, new = KNOWN_BUG_FIXES[bug]
    result = run_check(candidate(tmp_path, old, new))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL" in result.stdout


def test_a_wrong_number_value_is_caught_even_when_its_text_is_kept(tmp_path):
    # json-c stores each double with its original text and prints that text,
    # so only the recorded value itself shows this change.
    wrong = candidate(
        tmp_path,
        "current = json_object_new_double_s(numd, tok->pb->buf);",
        "current = json_object_new_double_s(numd + 1.0, tok->pb->buf);",
    )
    result = run_check(wrong)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "by field:  type" in result.stdout


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


def test_candidate_that_does_not_compile_is_a_build_error(tmp_path):
    broken = candidate(tmp_path, PARSE_EX_START, PARSE_EX_START + "\tthis does not compile;\n")
    result = run_check(broken)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "BUILD ERROR" in result.stdout
    # The planted line is line 331; the message must point at it in the candidate file.
    assert f"{broken}:331" in result.stdout


# Planted only for the input "[]", so the baseline-vs-candidate answers still match.
ON_EMPTY_ARRAY = "\tif (len >= 2 && str[0] == '[' && str[1] == ']')\n"


def test_hidden_memory_error_fails_even_when_answers_match(tmp_path):
    overflow = candidate(
        tmp_path,
        PARSE_EX_START,
        PARSE_EX_START + ON_EMPTY_ARRAY
        # volatile index: the compiler cannot see the overflow, only ASan can
        + "\t{ char *p = calloc(1, 4); volatile int i = 4; volatile char x = p[i]; (void)x; free(p); }\n",
    )
    result = run_check(overflow)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "input #50: []" in result.stdout
    # The sanitizer report points at the planted line, in the candidate's own file.
    assert f"{overflow}:332" in result.stdout


def test_memory_leak_fails(tmp_path):
    leak = candidate(tmp_path, PARSE_EX_START, PARSE_EX_START + ON_EMPTY_ARRAY + "\t{ void *volatile leaked = malloc(16); (void)leaked; }\n")
    result = run_check(leak)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "LeakSanitizer" in result.stdout
    assert "at exit" in result.stdout  # leaks are only reported once all inputs are answered


def test_endless_loop_fails_as_a_timeout(tmp_path):
    hang = candidate(tmp_path, PARSE_EX_START, PARSE_EX_START + ON_EMPTY_ARRAY + "\t\tfor (;;) {}\n")
    result = run_check(hang, "--timeout", "10")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "timed out" in result.stdout
    assert "input #50: []" in result.stdout


@pytest.mark.parametrize("anchor", [
    "\t\t\t{\n\t\t\t\tif (tok->depth >= tok->max_depth - 1)",  # array element
    "\t\tcase json_tokener_state_object_value:\n\t\t\tif (tok->depth >= tok->max_depth - 1)",  # object value
])
def test_off_by_one_in_the_nesting_limit_is_caught(tmp_path, anchor):
    # One level too many overruns the tokener's per-level stack, so ASan stops
    # it on the first 32-deep input before any answer can differ.
    result = run_check(candidate(tmp_path, anchor, anchor.replace(">=", ">")))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "heap-buffer-overflow" in result.stdout
