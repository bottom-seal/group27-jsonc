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


def plant(tmp_path: Path, *edits) -> Path:
    """The baseline tokener with several edits applied in order. An edit is
    (old, new) for an exact text found once, (old, new, "all") to replace every
    occurrence, or ("after:" + anchor, old, new) for the first `old` after the
    unique `anchor`."""
    src = baseline_source()
    for edit in edits:
        if edit[0].startswith("after:"):
            anchor, old, new = edit[0][len("after:"):], edit[1], edit[2]
            assert src.count(anchor) == 1, f"anchor must be unique: {anchor!r}"
            at = src.index(old, src.index(anchor))
            src = src[:at] + new + src[at + len(old):]
        elif len(edit) == 3:
            assert edit[0] in src, edit[0]
            src = src.replace(edit[0], edit[1])
        else:
            assert src.count(edit[0]) == 1, f"replacement anchor must be unique: {edit[0]!r}"
            src = src.replace(edit[0], edit[1])
    path = tmp_path / "json_tokener.c"
    path.write_text(src)
    return path


CALL_START = "\ttok->char_offset = 0;\n\ttok->err = json_tokener_success;\n"
SAVE_STRING_SO_FAR = ("printbuf_memappend_checked(tok->pb, case_start,\n"
                      "\t\t\t\t\t                           str - case_start);\n\t\t\t\t\tgoto out;")

# Mistakes that show only when a tokener is used for more than one call or in
# a way no input file can express: text arriving in pieces, several documents
# on one reader, two readers taking turns, the two flag sets without STRICT
# that use ALLOW_TRAILING_CHARS, and unusual API arguments. All of these passed
# the gate when it only made one call per fresh tokener. Entry: (edits, exit code).
MULTI_CALL_MISTAKES = {
    # The success path must reset level 0 for the next document on the same tokener.
    "level 0 not reset after a success": (
        [("for (ii = tok->depth; ii >= 0; ii--)", "for (ii = tok->depth; ii > 0; ii--)")], DIFFERENT),
    "string forgets the text read so far when a call ends inside it": (
        [("after:case json_tokener_state_string:", SAVE_STRING_SO_FAR, "goto out;")], DIFFERENT),
    "resumed number accepts a + sign": ([("int pos_sign_ok = 0;", "int pos_sign_ok = 1;")], DIFFERENT),
    # Values that must survive between calls, cleared at the start of each call.
    "position inside true/null/\\u cleared at every call": (
        [(CALL_START, CALL_START + "\ttok->st_pos = 0;\n")], DIFFERENT),
    "number's is_double cleared at every call": ([(CALL_START, CALL_START + "\ttok->is_double = 0;\n")], DIFFERENT),
    "text so far dropped at every call": ([(CALL_START, CALL_START + "\tprintbuf_reset(tok->pb);\n")], DIFFERENT),
    # A per-tokener value moved to a static: one document at a time can't tell.
    "quote character shared by all tokeners": (
        [("static unsigned char utf8_replacement_char[3]",
          "static char g_quote_char;\nstatic unsigned char utf8_replacement_char[3]"),
         ("tok->quote_char", "g_quote_char", "all")], DIFFERENT),
    "st_pos shared by all tokeners": (
        [("static unsigned char utf8_replacement_char[3]",
          "static int g_st_pos;\nstatic unsigned char utf8_replacement_char[3]"),
         ("tok->st_pos", "g_st_pos", "all")], DIFFERENT),
    # Same answers on the 6 flag sets with STRICT or none; differs only for
    # ALLOW_TRAILING_CHARS without STRICT.
    "trailing-characters check written as an xor": (
        [("(tok->flags & (JSON_TOKENER_STRICT | JSON_TOKENER_ALLOW_TRAILING_CHARS)) ==\n\t        JSON_TOKENER_STRICT",
          "(!(tok->flags & JSON_TOKENER_STRICT) != !(tok->flags & JSON_TOKENER_ALLOW_TRAILING_CHARS))")], DIFFERENT),
    "len < -1 gives the wrong error": (
        [("tok->err = json_tokener_error_size;", "tok->err = json_tokener_error_parse_eof;")], DIFFERENT),
    # A tokener with no room for even one level: ASan stops it.
    "json_tokener_new_ex(0) returns a tokener": (
        [("\tif (depth < 1)\n\t\treturn NULL;", "\tif (depth < 0)\n\t\treturn NULL;")], CRASH),
}


@pytest.mark.parametrize("mistake", sorted(MULTI_CALL_MISTAKES))
def test_mistakes_seen_only_across_calls_or_through_the_api_are_caught(tmp_path, mistake):
    edits, expected = MULTI_CALL_MISTAKES[mistake]
    result = run_check(plant(tmp_path, *edits))
    assert result.returncode == expected, result.stdout + result.stderr


LARGE_INPUTS = REPO / "oracle" / "inputs" / "large.txt"
FUZZ_INPUTS = REPO / "oracle" / "inputs" / "fuzz.txt"

# Mistakes that show only when an allocation fails, under a locale with a
# decimal comma, right after a reset, or on inputs the fuzzer found. Entry:
# (edits, exit code, input file or None for core.txt).
ITERATION2_MISTAKES = {
    "running out of memory for an object reported as a syntax error": (
        [("current = json_object_new_object();\n\t\t\t\tif (current == NULL)\n\t\t\t\t{\n"
          "\t\t\t\t\ttok->err = json_tokener_error_memory;",
          "current = json_object_new_object();\n\t\t\t\tif (current == NULL)\n\t\t\t\t{\n"
          "\t\t\t\t\ttok->err = json_tokener_error_parse_unexpected;")], DIFFERENT, None),
    "numbers read in the caller's locale": ([("\t\tuselocale(c_numeric_locale);\n", "")], DIFFERENT, None),
    "the caller's locale not put back": ([("\tuselocale(oldlocale);\n", "\t(void)oldlocale;\n")], DIFFERENT, None),
    "a reset leaves the error set": (
        [("\ttok->depth = 0;\n\ttok->err = json_tokener_success;\n\ttok->high_surrogate = 0;\n}",
          "\ttok->depth = 0;\n\ttok->high_surrogate = 0;\n}")], DIFFERENT, None),
    # Found by the differential fuzzer: no core input has a 9 right after the
    # point of a STRICT fraction.
    "strict fraction rejects a 9 after the point": (
        [("if (*num == '.')\n\t\t\t\t{\n\t\t\t\t\tnum++;\n\t\t\t\t\tif (!(*num >= '0' && *num <= '9'))",
          "if (*num == '.')\n\t\t\t\t{\n\t\t\t\t\tnum++;\n\t\t\t\t\tif (!(*num >= '0' && *num < '9'))")],
        DIFFERENT, FUZZ_INPUTS),
}


# Mistakes that show only when creating a tokener runs out of memory, inside
# json_tokener_parse_verbose, with two tokeners of different settings, or on
# inputs the fuzzer found later.
ITERATION3_MISTAKES = {
    "no NULL check after allocating the tokener": (
        [("\ttok = (struct json_tokener *)calloc(1, sizeof(struct json_tokener));\n\tif (!tok)\n\t\treturn NULL;\n",
          "\ttok = (struct json_tokener *)calloc(1, sizeof(struct json_tokener));\n")], CRASH, None),
    "the tokener leaks when its stack cannot be allocated": (
        [("\tif (!tok->stack)\n\t{\n\t\tfree(tok);\n\t\treturn NULL;\n\t}",
          "\tif (!tok->stack)\n\t{\n\t\treturn NULL;\n\t}")], CRASH, None),
    "parse_verbose loses its out-of-memory error": (
        [("\t\t*error = json_tokener_error_memory;\n\t\treturn NULL;", "\t\treturn NULL;")], DIFFERENT, None),
    # The depth-5 tokener takes the depth-64 limit and overruns its own stack.
    "max_depth shared by all tokeners": (
        [("static unsigned char utf8_replacement_char[3]",
          "static int g_max_depth;\nstatic unsigned char utf8_replacement_char[3]"),
         ("tok->max_depth", "g_max_depth", "all")], CRASH, None),
    # Found by the fuzzer: "~" right after a value inside an object.
    "object end accepted for any character from '}' up": (
        [("after:case json_tokener_state_object_sep:", "if (c == '}')", "if (c >= '}')")], DIFFERENT, FUZZ_INPUTS),
}


@pytest.mark.parametrize("mistake", sorted(ITERATION3_MISTAKES))
def test_mistakes_seen_creating_tokeners_or_with_two_settings_are_caught(tmp_path, mistake):
    edits, expected, inputs = ITERATION3_MISTAKES[mistake]
    extra = ("--inputs", str(inputs)) if inputs else ()
    result = run_check(plant(tmp_path, *edits), *extra)
    assert result.returncode == expected, result.stdout + result.stderr


@pytest.mark.parametrize("mistake", sorted(ITERATION2_MISTAKES))
def test_mistakes_seen_under_memory_failure_locale_reset_or_fuzzer_inputs_are_caught(tmp_path, mistake):
    edits, expected, inputs = ITERATION2_MISTAKES[mistake]
    extra = ("--inputs", str(inputs)) if inputs else ()
    result = run_check(plant(tmp_path, *edits), *extra)
    assert result.returncode == expected, result.stdout + result.stderr


def test_work_that_grows_with_the_square_of_a_string_times_out_on_large_inputs(tmp_path):
    # Rescans the string read so far at every character: answers are the same,
    # and on core.txt (at most 1,000 bytes) it is not even noticeably slower.
    slow = plant(tmp_path, ("after:case json_tokener_state_string:", "\t\t\t\tif (c == tok->quote_char)\n",
                            "\t\t\t\t{ volatile const char *p = case_start; while (p < str) p++; }\n"
                            "\t\t\t\tif (c == tok->quote_char)\n"))
    result = run_check(slow, "--inputs", str(LARGE_INPUTS), "--timeout", "5", "--slowdown", "5")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "timed out" in result.stdout


def test_a_mistake_in_the_api_calls_is_reported_as_such(tmp_path):
    result = run_check(plant(tmp_path, *MULTI_CALL_MISTAKES["len < -1 gives the wrong error"][0]))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "the edge-case API calls (after the last input)" in result.stdout


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
