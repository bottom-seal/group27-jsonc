"""Compare the recorder output of the baseline and a candidate build.

The recorder prints one tab-separated record per (input, config):

    <input index> <config> <type signature> <error> <parse end> <value>

and a final "#done" line. This module turns two such outputs into a verdict.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Run:
    """What one recorder process produced."""
    output: str
    returncode: int
    timed_out: bool = False
    stderr: str = ""


@dataclass
class Verdict:
    status: str  # "pass" or "different"
    checks: int = 0
    mismatches: list = field(default_factory=list)


def _records(output: str) -> dict:
    records = {}
    # split on "\n" only: values can hold bytes like 0x85 that splitlines() treats as breaks
    for line in output.split("\n"):
        if not line or line == "#done":
            continue
        index, config, *answer = line.split("\t")
        records[(int(index), config)] = tuple(answer)
    return records


def compare(old: Run, new: Run) -> Verdict:
    old_records = _records(old.output)
    new_records = _records(new.output)
    mismatches = [key for key, answer in old_records.items() if new_records.get(key) != answer]
    status = "different" if mismatches else "pass"
    return Verdict(status, checks=len(old_records), mismatches=mismatches)


def report(verdict: Verdict, inputs: list) -> str:
    if verdict.status == "pass":
        return f"PASS: {verdict.checks} checks, no differences from the baseline"
    return f"FAIL: {len(verdict.mismatches)} of {verdict.checks} checks differ from the baseline"
