"""End-to-end tests for the checker (seam 1).

Each test builds a candidate json_tokener.c from the baseline source, runs
`oracle/check.py` on it and checks the verdict. These compile C code: the first
run builds json-c once into .build/ (about 10 seconds); later runs reuse it.
Every test passes --inputs explicitly, so input numbers in the assertions
refer to oracle/inputs/core.txt and do not move when input files are added.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "oracle" / "check.py"
CORE_INPUTS = REPO / "oracle" / "inputs" / "core.txt"


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


def run_check(cand: Path, *extra: str, env: dict = None) -> subprocess.CompletedProcess:
    inputs = [] if "--inputs" in extra else ["--inputs", str(CORE_INPUTS)]
    return subprocess.run(
        [sys.executable, str(CHECK), str(cand), *inputs, *extra],
        cwd=REPO, capture_output=True, text=True, timeout=600,
        env=None if env is None else {**os.environ, **env},
    )


def test_unchanged_tokener_passes(tmp_path):
    result = run_check(candidate(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def configs_in_report(stdout: str) -> list:
    """The config names on the report's "by config:" line."""
    line = next(l for l in stdout.split("\n") if l.startswith("  by config:"))
    return [entry.rsplit(" ", 1)[0] for entry in line.split(":", 1)[1].strip().split(", ")]


# Quiet fixes of known bugs (bughunt/README.md). Each changes behaviour, so the
# gate must reject it, and only where that bug shows. Entry: (text to replace,
# replacement, the smallest differing input as reported, a rule every
# differing config must satisfy). Bugs 1 and 2 use the fixes from
# bughunt/local_fixes_findings_1-5.patch; that patch's bug-3 fix edits code
# the baseline does not have, so bug 3 uses an equivalent one-line fix.
KNOWN_BUG_FIXES = {
    "bug1-unclosed-comment-after-value": (
        "\t\tif (state != json_tokener_state_finish && saved_state != json_tokener_state_finish)",
        "\t\tif ((state != json_tokener_state_finish && saved_state != json_tokener_state_finish) ||\n"
        "\t\t    (tok->err == json_tokener_success && tok->depth > 0))",
        "input #2616: [[1/*",
        lambda config: "strict" not in config,  # STRICT rejects comments anyway
    ),
    "bug2-even-stars-close-comment": (
        "\t\t\telse\n\t\t\t{\n\t\t\t\tstate = json_tokener_state_comment;\n\t\t\t}",
        "\t\t\telse if (c != '*')\n\t\t\t{\n\t\t\t\tstate = json_tokener_state_comment;\n\t\t\t}",
        "input #990: /*[/**/",
        lambda config: "strict" not in config,
    ),
    "bug3-utf8-lookahead-after-value": (
        "if ((tok->flags & JSON_TOKENER_VALIDATE_UTF8) && (nBytes != 0))",
        "if ((tok->flags & JSON_TOKENER_VALIDATE_UTF8) && (nBytes != 0) && tok->err != json_tokener_success)",
        "input #2591: {}\\xc6",
        lambda config: "utf8" in config,
    ),
    "bug4-strict-single-quoted-key": (
        "else if (c == '\"' || c == '\\'')",
        "else if (c == '\"' || (c == '\\'' && !(tok->flags & JSON_TOKENER_STRICT)))",
        "input #2082: {'r",
        lambda config: "strict" in config,
    ),
}


@pytest.mark.parametrize("bug", sorted(KNOWN_BUG_FIXES))
def test_fixing_any_known_bug_is_rejected_where_that_bug_shows(tmp_path, bug):
    old, new, smallest_input, config_rule = KNOWN_BUG_FIXES[bug]
    result = run_check(candidate(tmp_path, old, new))
    assert result.returncode == 1, result.stdout + result.stderr
    first_example = result.stdout.split("Smallest differing inputs")[1].split("\n")[1]
    assert first_example == "  " + smallest_input
    configs = configs_in_report(result.stdout)
    assert configs and all(config_rule(c) for c in configs), configs


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
        # volatile index: the compiler cannot see the overflow, only the sanitizers can
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


LEAK_ON_EMPTY_ARRAY = "\t{ void *volatile leaked = malloc(16); (void)leaked; }\n"


def test_sanitizer_settings_in_the_environment_cannot_hide_a_leak(tmp_path):
    leak = candidate(tmp_path, PARSE_EX_START, PARSE_EX_START + ON_EMPTY_ARRAY + LEAK_ON_EMPTY_ARRAY)
    result = run_check(leak, env={"ASAN_OPTIONS": "detect_leaks=0:exitcode=0", "LSAN_OPTIONS": "exitcode=0"})
    assert result.returncode == 2, result.stdout + result.stderr
    assert "LeakSanitizer" in result.stdout


def test_candidate_cannot_switch_off_leak_detection_with_default_options(tmp_path):
    # ASan reads __asan_default_options() first; the checker's environment
    # settings are applied after it and win.
    leak = candidate(tmp_path, PARSE_EX_START, PARSE_EX_START + ON_EMPTY_ARRAY + LEAK_ON_EMPTY_ARRAY)
    leak.write_text(leak.read_text() + (
        "\nconst char *__asan_default_options(void);\n"
        "const char *__asan_default_options(void)\n{\n\treturn \"detect_leaks=0\";\n}\n"
    ))
    result = run_check(leak)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "LeakSanitizer" in result.stdout


def test_endless_loop_fails_as_a_timeout(tmp_path):
    hang = candidate(tmp_path, PARSE_EX_START, PARSE_EX_START + ON_EMPTY_ARRAY + "\t\tfor (;;) {}\n")
    result = run_check(hang, "--timeout", "1", "--slowdown", "2")
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


def test_printing_to_stdout_is_a_difference(tmp_path):
    # The baseline tokener prints nothing; a leftover debug print changes
    # what a program using json-c outputs, and must not corrupt the answers.
    noisy = candidate(tmp_path, PARSE_EX_START, PARSE_EX_START + ON_EMPTY_ARRAY + '\t\tprintf("debug: got []\\n");\n')
    result = run_check(noisy)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "printed to stdout" in result.stdout
    assert "debug: got []" in result.stdout


def test_quitting_early_after_faking_the_end_marker_is_a_crash(tmp_path):
    # Cheat found in review: print the recorder's end marker and exit 0
    # on the first call, so nothing is ever compared.
    fake = candidate(
        tmp_path, PARSE_EX_START,
        PARSE_EX_START + '\t{ printf("#done 3402\\n"); fflush(stdout); _exit(0); }\n',
    )
    fake.write_text("#include <unistd.h>\n" + fake.read_text())
    result = run_check(fake)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "stopped before the last input on input #1:" in result.stdout


def test_exiting_normally_partway_is_a_crash(tmp_path):
    quits = candidate(tmp_path, PARSE_EX_START, PARSE_EX_START + ON_EMPTY_ARRAY + "\t\texit(0);\n")
    result = run_check(quits)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "stopped before the last input on input #50: []" in result.stdout


# Mistakes in the other ways programs call the tokener. The recorder used to
# call only json_tokener_parse_ex(tok, buf, len + 1) on a fresh tokener, so
# all of these passed. Each entry: (text to replace, replacement, exit code).
DIFFERENT, CRASH = 1, 2
API_MISTAKES = {
    "parse_ex rejects len == -1 (used by json_tokener_parse)": (
        "if ((len < -1) || (len == -1 && strlen(str) > INT32_MAX))",
        "if ((len <= -1) || (len == -1 && strlen(str) > INT32_MAX))",
        DIFFERENT,
    ),
    "input without a final NUL ends with an error instead of 'continue'": (
        "(((tok)->err = json_tokener_continue), 0))",
        "(((tok)->err = json_tokener_error_parse_eof), 0))",
        DIFFERENT,
    ),
    # The per-level stack is sized by the depth given, so a larger max_depth
    # overruns it: ASan reports it on the first nested input.
    "json_tokener_new_ex ignores its depth": (
        "\ttok->max_depth = depth;",
        "\ttok->max_depth = JSON_TOKENER_DEFAULT_DEPTH;",
        CRASH,
    ),
    "json_tokener_new_ex caps depth at the default": (
        "\ttok->max_depth = depth;",
        "\ttok->max_depth = depth < JSON_TOKENER_DEFAULT_DEPTH ? depth : JSON_TOKENER_DEFAULT_DEPTH;",
        DIFFERENT,
    ),
    # Levels above the stale depth are never freed: LeakSanitizer reports it.
    "json_tokener_reset forgets the nesting level": (
        "\ttok->depth = 0;\n\ttok->err = json_tokener_success;\n\ttok->high_surrogate = 0;\n}",
        "\ttok->err = json_tokener_success;\n\ttok->high_surrogate = 0;\n}",
        CRASH,
    ),
    "json_tokener_parse drops its result": (
        "obj = json_tokener_parse_verbose(str, &jerr_ignored);\n\treturn obj;",
        "obj = json_tokener_parse_verbose(str, &jerr_ignored);\n\tjson_object_put(obj);\n\treturn NULL;",
        DIFFERENT,
    ),
}


@pytest.mark.parametrize("mistake", sorted(API_MISTAKES))
def test_mistakes_in_other_entry_points_are_caught(tmp_path, mistake):
    old, new, expected = API_MISTAKES[mistake]
    result = run_check(candidate(tmp_path, old, new))
    assert result.returncode == expected, result.stdout + result.stderr


def test_deleting_a_public_function_is_a_build_error(tmp_path):
    # json_tokener_parse() and json_tokener_parse_verbose() removed.
    src = candidate(tmp_path)
    text = src.read_text()
    start = text.index("struct json_object *json_tokener_parse(const char *str)")
    verbose_end = text.index("\n}\n", text.index("struct json_object *json_tokener_parse_verbose(")) + 3
    src.write_text(text[:start] + text[verbose_end:])
    result = run_check(src)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "json_tokener_parse" in result.stdout


def test_defining_a_function_that_another_json_c_file_owns_is_a_build_error(tmp_path):
    # json_pointer_get lives in json_pointer.c; the real json-c build fails
    # with "multiple definition", so the gate must too.
    clash = candidate(tmp_path)
    clash.write_text(clash.read_text() + (
        '\n#include "json_pointer.h"\n'
        "int json_pointer_get(struct json_object *obj, const char *path, struct json_object **res)\n"
        "{\n\t(void)obj;\n\t(void)path;\n\t(void)res;\n\treturn -1;\n}\n"
    ))
    result = run_check(clash)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "multiple definition of `json_pointer_get'" in result.stdout


def test_a_much_slower_rewrite_fails_as_a_timeout(tmp_path):
    # 0.2 ms extra per call is several times slower than the baseline over
    # ~100k calls; with --slowdown 2 the limit is twice the baseline's time.
    slow = candidate(tmp_path, PARSE_EX_START, PARSE_EX_START + "\tusleep(200);\n")
    slow.write_text("#include <unistd.h>\n" + slow.read_text())
    result = run_check(slow, "--timeout", "1", "--slowdown", "2")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "timed out" in result.stdout
    assert "the baseline took" in result.stdout


def test_including_the_baseline_source_is_a_build_error(tmp_path):
    # Cheat found in review: a one-line "rewrite" that includes the original.
    sneaky = tmp_path / "json_tokener.c"
    sneaky.write_text("#include <json_tokener.c>\n")
    result = run_check(sneaky)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "includes another .c file" in result.stdout


def test_compiler_message_with_non_utf8_bytes_is_still_a_build_error(tmp_path):
    broken = candidate(tmp_path, PARSE_EX_START, PARSE_EX_START + "\tthis does not compile; /* \xff */\n")
    broken.write_bytes(broken.read_text().encode("latin-1"))
    result = run_check(broken)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "BUILD ERROR" in result.stdout


BUG4_FIX = KNOWN_BUG_FIXES["bug4-strict-single-quoted-key"][:2]


def test_a_tampered_cache_does_not_change_the_baseline(tmp_path):
    # Review showed a candidate can overwrite the cached baseline source, so
    # that later runs compare candidates against the tampered copy.
    build = tmp_path / "build"
    assert run_check(candidate(tmp_path), "--build-dir", str(build)).returncode == 0
    (cached,) = build.glob("baseline-*/src/json-c/json_tokener.c")
    fixed = candidate(tmp_path, *BUG4_FIX)
    cached.write_text(fixed.read_text())
    result = run_check(fixed, "--build-dir", str(build))
    assert result.returncode == 1, result.stdout + result.stderr


def test_two_first_runs_at_once_both_work(tmp_path):
    build = tmp_path / "build"
    same = candidate(tmp_path)
    procs = [
        subprocess.Popen([sys.executable, str(CHECK), str(same), "--build-dir", str(build)],
                         cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(2)
    ]
    outputs = [p.communicate(timeout=600)[0] for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outputs


@pytest.mark.parametrize("problem", ["missing inputs file", "missing candidate", "malformed escape"])
def test_problems_with_the_checker_setup_are_checker_errors(tmp_path, problem):
    cand, inputs = candidate(tmp_path), tmp_path / "inputs.txt"
    inputs.write_text("[1]\n")
    if problem == "missing inputs file":
        inputs = tmp_path / "nonexistent.txt"
    elif problem == "missing candidate":
        cand = tmp_path / "nonexistent.c"
    else:
        inputs.write_text('"\\x4"\n')  # \x must be followed by two hex digits
    result = run_check(cand, "--inputs", str(inputs))
    assert result.returncode == 4, result.stdout + result.stderr
    assert "CHECKER ERROR" in result.stdout


def test_last_input_line_without_a_newline_is_still_checked(tmp_path):
    inputs = tmp_path / "inputs.txt"
    inputs.write_text("[1]\n{'a':0}")  # no final newline
    result = run_check(candidate(tmp_path, *BUG4_FIX), "--inputs", str(inputs))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "input #2: {'a':0}" in result.stdout


def test_a_very_long_input_line_is_one_input(tmp_path):
    inputs = tmp_path / "inputs.txt"
    inputs.write_text('"' + "x" * 200_000 + '"\n' + "{'a':0}\n")
    result = run_check(candidate(tmp_path, *BUG4_FIX), "--inputs", str(inputs))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "input #2: {'a':0}" in result.stdout


def test_inputs_option_before_the_candidate_does_not_swallow_it(tmp_path):
    # `--inputs FILE CANDIDATE` once read CANDIDATE as a second input file and
    # silently checked json-c/json_tokener.c instead.
    fixed = candidate(tmp_path, *BUG4_FIX)
    result = subprocess.run([sys.executable, str(CHECK), "--inputs", str(CORE_INPUTS), str(fixed)],
                            cwd=REPO, capture_output=True, text=True, timeout=600)
    assert result.returncode == 1, result.stdout + result.stderr
