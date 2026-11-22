"""Compare the recorder output of the baseline and a candidate build.

The recorder prints one tab-separated record per (input, config):

    <input index> <config> <type signature> <error> <parse end> <value>

and a final "#done" line. This module turns two such outputs into a verdict
and a human-readable report.
"""
from collections import Counter
from dataclasses import dataclass, field

FIELDS = ("type", "error", "end", "value")


@dataclass(frozen=True)
class Run:
    """What one recorder process produced."""
    output: str
    returncode: int
    timed_out: bool = False
    stderr: str = ""


@dataclass(frozen=True)
class Mismatch:
    index: int  # 0-based position in the input list
    config: str
    old: tuple  # the baseline's answer, one entry per FIELDS
    new: tuple  # the candidate's answer

    @property
    def fields(self) -> list:
        return [name for name, a, b in zip(FIELDS, self.old, self.new) if a != b]


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
        index, config, *answer = line.split("\t", len(FIELDS) + 1)
        records[(int(index), config)] = tuple(answer)
    return records


def compare(old: Run, new: Run) -> Verdict:
    old_records = _records(old.output)
    new_records = _records(new.output)
    mismatches = [
        Mismatch(index, config, answer, new_records[(index, config)])
        for (index, config), answer in old_records.items()
        if (index, config) in new_records and new_records[(index, config)] != answer
    ]
    status = "different" if mismatches else "pass"
    return Verdict(status, checks=len(old_records), mismatches=mismatches)


def _answer(values: tuple) -> str:
    return "  ".join(f"{name}={value}" for name, value in zip(FIELDS, values))


def _counts(counter: Counter) -> str:
    return ", ".join(f"{key} {n}" for key, n in counter.most_common())


def report(verdict: Verdict, inputs: list, max_examples: int = 10) -> str:
    if verdict.status == "pass":
        return f"PASS: {verdict.checks} checks, no differences from the baseline"

    by_input = {}
    for m in verdict.mismatches:
        by_input.setdefault(m.index, []).append(m)
    lines = [
        f"FAIL: {len(verdict.mismatches)} of {verdict.checks} checks differ from the baseline"
        f" ({len(by_input)} inputs)",
        f"  by config: {_counts(Counter(m.config for m in verdict.mismatches))}",
        f"  by field:  {_counts(Counter(f for m in verdict.mismatches for f in m.fields))}",
        "",
    ]
    # Smallest inputs first: they are the easiest to debug.
    shown = sorted(by_input, key=lambda i: (len(inputs[i]), i))[:max_examples]
    lines.append(f"Smallest differing inputs ({len(shown)} of {len(by_input)}):")
    for index in shown:
        first, *rest = by_input[index]
        lines.append(f"  input #{index + 1}: {inputs[index]}")
        lines.append(f"    config {first.config}" + (f" (also {', '.join(m.config for m in rest)})" if rest else ""))
        lines.append(f"      baseline:  {_answer(first.old)}")
        lines.append(f"      candidate: {_answer(first.new)}")
    return "\n".join(lines)
