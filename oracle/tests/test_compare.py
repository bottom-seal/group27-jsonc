"""Tests for the comparison step (seam 2), using hand-written recorder output."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compare import Run, compare, report  # noqa: E402

INPUTS = ["[1]", "[2]", "[3]"]


def recorder_output(*records, done=True):
    """Build recorder output from (index, config, type, error, end, value) tuples."""
    lines = ["\t".join(map(str, r)) for r in records]
    return "\n".join(lines) + ("\n#done\n" if done else "\n")


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
