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
