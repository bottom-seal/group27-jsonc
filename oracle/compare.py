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
    status: str  # "pass", "different" or "crash"
    checks: int = 0
    mismatches: list = field(default_factory=list)
    crash_index: "int | None" = None  # input the candidate was on when it stopped
    crash_reason: str = ""
    crash_log: str = ""  # the candidate's stderr, e.g. the sanitizer report


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
    verdict = Verdict("different" if mismatches else "pass", checks=len(old_records), mismatches=mismatches)

    reason = _crash_reason(new)
    if reason:
        verdict.status = "crash"
        verdict.crash_reason = reason
        verdict.crash_log = new.stderr
        missing = [index for (index, config) in old_records if (index, config) not in new_records]
        verdict.crash_index = min(missing) if missing else None
    return verdict


def _crash_reason(run: Run) -> str:
    if run.timed_out:
        return "timed out"
    if run.returncode != 0:
        return f"exited with code {run.returncode}"
    if not run.output.endswith("#done\n"):
        return "stopped before the last input"
    return ""


def _answer(values: tuple) -> str:
    return "  ".join(f"{name}={value}" for name, value in zip(FIELDS, values))


def _counts(counter: Counter) -> str:
    return ", ".join(f"{key} {n}" for key, n in counter.most_common())


def _crash_report(verdict: Verdict, inputs: list, log_lines: int = 40) -> list:
    if verdict.crash_index is None:
        where = "after answering every input (at exit)"
    else:
        where = f"on input #{verdict.crash_index + 1}: {inputs[verdict.crash_index]}"
    lines = [f"CRASH: candidate {verdict.crash_reason} {where}"]
    log = verdict.crash_log.strip().split("\n")
    if log != [""]:
        lines.append(f"  last {min(len(log), log_lines)} lines of its error output:")
        lines += ["    " + line for line in log[-log_lines:]]
    return lines


def report(verdict: Verdict, inputs: list, max_examples: int = 10) -> str:
    if verdict.status == "pass":
        return f"PASS: {verdict.checks} checks, no differences from the baseline"
    if verdict.status == "crash":
        lines = _crash_report(verdict, inputs)
        if verdict.mismatches:
            lines += ["", "Before stopping, it also answered differently:"]
            lines += _difference_report(verdict, inputs, max_examples)
        return "\n".join(lines)
    return "\n".join(_difference_report(verdict, inputs, max_examples))


def _difference_report(verdict: Verdict, inputs: list, max_examples: int) -> list:
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
    return lines
