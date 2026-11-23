"""Tests for the comparison step (seam 2), using hand-written recorder output."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compare import Run, compare, report  # noqa: E402

INPUTS = ["[1]", "[2]", "[3]"]


def recorder_output(*records, done=True, inputs=3):
    """Build recorder output from (index, config, type, error, end, value)
    tuples. A finished run ends with "#done <number of inputs read>"."""
    lines = ["\t".join(map(str, r)) for r in records]
    return "\n".join(lines) + (f"\n#done {inputs}\n" if done else "\n")


BASELINE = recorder_output(
    (0, "default", "a[i]", "0 success", 3, "[1]"),
    (0, "strict", "a[i]", "0 success", 3, "[1]"),
    (1, "default", "a[i]", "0 success", 3, "[2]"),
    (1, "strict", "a[i]", "0 success", 3, "[2]"),
    (2, "default", "a[i]", "0 success", 3, "[3]"),
    (2, "strict", "a[i]", "0 success", 3, "[3]"),
)


def test_crash_partway_names_the_input_it_was_on():
    # Candidate finished input 0 and one config of input 1, then died.
    new = Run(
        recorder_output(
            (0, "default", "a[i]", "0 success", 3, "[1]"),
            (0, "strict", "a[i]", "0 success", 3, "[1]"),
            (1, "default", "a[i]", "0 success", 3, "[2]"),
            done=False,
        ),
        returncode=1,
        stderr="==123==ERROR: AddressSanitizer: SEGV on unknown address",
    )
    verdict = compare(Run(BASELINE, 0), new)
    assert verdict.status == "crash"
    assert verdict.crash_index == 1
    text = report(verdict, INPUTS)
    assert "CRASH" in text
    assert "[2]" in text  # the input it crashed on
    assert "AddressSanitizer: SEGV" in text  # the sanitizer's explanation


ASAN_LOG = """\
=================================================================
==4242==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x51d000000a80 at pc 0x5f2e bp 0x7ffc sp 0x7ffc
WRITE of size 4 at 0x51d000000a80 thread T0
    #0 0x5f2eea263300 in json_tokener_reset_level json_tokener.c:199
    #1 0x5f2eea265a10 in json_tokener_parse_ex json_tokener.c:1220
""" + "".join(f"    #{i} 0x5f2eea2600{i:02d} in frame_{i} somewhere.c:{i}\n" for i in range(2, 40)) + """\
0x51d000000a80 is located 0 bytes after 2048-byte region
SUMMARY: AddressSanitizer: heap-buffer-overflow json_tokener.c:199 in json_tokener_reset_level
Shadow bytes around the buggy address:
""" + "  0x51d000000800: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00\n" * 30 + "==4242==ABORTING\n"


def test_crash_log_keeps_the_sanitizer_headline_and_drops_the_memory_dump():
    new = Run(recorder_output((0, "default", "a[i]", "0 success", 3, "[1]"), done=False), 1, stderr=ASAN_LOG)
    text = report(compare(Run(BASELINE, 0), new), INPUTS)
    assert "ERROR: AddressSanitizer: heap-buffer-overflow" in text  # what went wrong
    assert "json_tokener_parse_ex json_tokener.c:1220" in text  # where
    assert "SUMMARY: AddressSanitizer" in text
    assert "Shadow bytes" not in text  # hex dump of memory: noise for the reader
    assert "frame_39" not in text  # deep stack frames are cut


def without(output: str, line_prefix: str) -> str:
    return "".join(line for line in output.splitlines(keepends=True) if not line.startswith(line_prefix))


def test_answers_missing_after_a_normal_exit_are_a_difference():
    # Exit code 0 and "#done", but input 1 under "strict" was never answered.
    new = Run(without(BASELINE, "1\tstrict\t"), 0)
    verdict = compare(Run(BASELINE, 0), new)
    assert verdict.status == "different"
    text = report(verdict, INPUTS)
    assert "input #2: [2]" in text
    assert "candidate: (no answer)" in text


def test_extra_answers_are_a_difference():
    new = Run(BASELINE.replace("#done", "1\tlenient\ta[i]\t0 success\t3\t[2]\n#done"), 0)
    verdict = compare(Run(BASELINE, 0), new)
    assert verdict.status == "different"
    assert "baseline:  (no answer)" in report(verdict, INPUTS)


def test_an_answer_given_twice_is_a_difference():
    new = Run(BASELINE.replace("#done", "0\tdefault\ta[i]\t0 success\t3\t[1]\n#done"), 0)
    verdict = compare(Run(BASELINE, 0), new)
    assert verdict.status == "different"
    assert "answered twice" in report(verdict, INPUTS)


def test_unreadable_lines_are_reported_not_a_checker_crash():
    new = Run(BASELINE.replace("#done", "debug: got here\n#done"), 0)
    verdict = compare(Run(BASELINE, 0), new)
    assert verdict.status == "different"
    assert "unreadable line: debug: got here" in report(verdict, INPUTS)


def test_wrong_input_count_in_done_line_is_a_difference():
    new = Run(BASELINE.replace("#done 3", "#done 2"), 0)
    verdict = compare(Run(BASELINE, 0), new)
    assert verdict.status == "different"
    assert "read 2 inputs, the baseline read 3" in report(verdict, INPUTS)


def test_line_cut_off_by_a_crash_is_not_read_as_an_answer():
    # The process died while writing input 1's strict answer: half a line.
    new = Run(without(BASELINE, "1\tstrict").split("1\tdefault")[0] + "1\tdefault\ta[", 1)
    verdict = compare(Run(BASELINE, 0), new)
    assert verdict.status == "crash"
    assert verdict.crash_index == 1
    assert verdict.mismatches == []


def test_sanitizer_report_is_a_crash_even_with_exit_code_0():
    # e.g. ASAN_OPTIONS=exitcode=0, or a candidate that changed the exit code
    new = Run(BASELINE, 0, stderr="==7==ERROR: AddressSanitizer: heap-use-after-free on address 0x1")
    verdict = compare(Run(BASELINE, 0), new)
    assert verdict.status == "crash"
    assert "heap-use-after-free" in report(verdict, INPUTS)


@pytest.mark.parametrize("field, record", [
    ("type", (1, "strict", "a[d(0x1p+1)]", "0 success", 3, "[2]")),
    ("error", (1, "strict", "a[i]", "1 continue", 3, "[2]")),
    ("end", (1, "strict", "a[i]", "0 success", 2, "[2]")),
    ("value", (1, "strict", "a[i]", "0 success", 3, "[2.0]")),
])
def test_each_kind_of_difference_is_reported_under_its_own_field(field, record):
    new = Run(BASELINE.replace("1\tstrict\ta[i]\t0 success\t3\t[2]", "\t".join(map(str, record))), 0)
    verdict = compare(Run(BASELINE, 0), new)
    assert verdict.status == "different"
    text = report(verdict, INPUTS)
    assert f"by field:  {field} 1" in text
    # baseline's answer first, then the candidate's
    assert "      baseline:  type=a[i]  error=0 success  end=3  value=[2]\n" in text
    candidate_answer = dict(zip(("type", "error", "end", "value"), map(str, record[2:])))
    assert text.endswith("      candidate: " + "  ".join(f"{k}={v}" for k, v in candidate_answer.items()))


def test_long_inputs_are_shortened_in_the_report():
    inputs = ["[1]", "[" + "7," * 2500 + "7]", "[3]"]
    new = Run(without(BASELINE, "1\t"), 1)  # crashed on input #2
    text = report(compare(Run(BASELINE, 0), new), inputs)
    first_line = text.split("\n")[0]
    assert len(first_line) < 300
    assert "(5003 bytes)" in first_line
