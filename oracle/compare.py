"""Compare the recorder output of the baseline and a candidate build.

The recorder prints one tab-separated record per (input, config):

    <input index> <config> <type signature> <error> <parse end> <value>

and, once every input is answered, a final line "#done <number of inputs>".
This module turns two such outputs into a verdict and a human-readable report.
The candidate must give exactly the baseline's set of answers: a missing,
extra, duplicated or unreadable line is a difference, never ignored.
"""
from collections import Counter
from dataclasses import dataclass, field

FIELDS = ("type", "error", "end", "value")


@dataclass(frozen=True)
class Run:
    """What one recorder process produced."""
    output: str  # the answers file
    returncode: int
    timed_out: bool = False
    stderr: str = ""
    printed: str = ""  # what the process wrote to stdout
    elapsed: float = 0.0  # seconds
    time_limit: float = 0.0  # seconds it was allowed


@dataclass(frozen=True)
class Mismatch:
    index: int  # 0-based position in the input list
    config: str
    old: "tuple | None"  # the baseline's answer, one entry per FIELDS; None if it gave none
    new: "tuple | None"  # the candidate's answer; None if it gave none

    @property
    def fields(self) -> list:
        if self.old is None:
            return ["extra answer"]
        if self.new is None:
            return ["missing answer"]
        return [name for name, a, b in zip(FIELDS, self.old, self.new) if a != b]


@dataclass
class Verdict:
    status: str  # "pass", "different" or "crash"
    checks: int = 0
    mismatches: list = field(default_factory=list)
    problems: list = field(default_factory=list)  # output that is not a well-formed answer
    crash_index: "int | None" = None  # input the candidate was on when it stopped
    crash_reason: str = ""
    crash_log: str = ""  # the candidate's stderr, e.g. the sanitizer report


@dataclass
class Output:
    records: dict
    problems: list
    done: "int | None"  # inputs read, from the "#done" line; None if it never came


def parse_output(text: str) -> Output:
    # Text after the last "\n" is a line cut off by a crash or a timeout.
    # Split on "\n" only: values can hold bytes like 0x85 that splitlines() treats as breaks.
    complete = text.rpartition("\n")[0]
    out = Output({}, [], None)
    for line in complete.split("\n") if complete else []:
        fields = line.split("\t", len(FIELDS) + 1)
        if line.startswith("#done ") and line[6:].isdigit() and out.done is None:
            out.done = int(line[6:])
        elif len(fields) != len(FIELDS) + 2 or not fields[0].isdigit():
            out.problems.append(f"unreadable line: {line[:200]}")
        elif (int(fields[0]), fields[1]) in out.records:
            out.problems.append(f"input #{int(fields[0]) + 1} config {fields[1]} answered twice")
        else:
            out.records[(int(fields[0]), fields[1])] = tuple(fields[2:])
    return out


def compare(old: Run, new: Run) -> Verdict:
    base = parse_output(old.output)
    if base.problems or base.done is None:
        raise ValueError(f"baseline output is malformed: {base.problems[:3] or 'no #done line'}")
    cand = parse_output(new.output)
    reason = _crash_reason(new, cand)

    mismatches = []
    for key, answer in base.records.items():
        got = cand.records.get(key)
        if got != answer and not (got is None and reason):  # after a crash, missing answers are expected
            mismatches.append(Mismatch(*key, answer, got))
    mismatches += [Mismatch(*key, None, got) for key, got in cand.records.items() if key not in base.records]

    problems = list(cand.problems)
    if new.printed != old.printed:
        problems.append(f"printed to stdout (the baseline printed {len(old.printed)} bytes): {new.printed[:300]!r}")
    if not reason and cand.done != base.done:
        problems.append(f"read {cand.done} inputs, the baseline read {base.done}")

    status = "pass"  # CI test: a PR that weakens the checker
    verdict = Verdict(status, checks=len(base.records), mismatches=mismatches, problems=problems)
    if reason:
        verdict.crash_reason = reason
        verdict.crash_log = new.stderr
        missing = [index for (index, config) in base.records if (index, config) not in cand.records]
        verdict.crash_index = min(missing) if missing else None
    return verdict


def _is_sanitizer_headline(line: str) -> bool:
    return "runtime error:" in line or ("ERROR:" in line and "Sanitizer" in line)


def _crash_reason(run: Run, output: Output) -> str:
    if run.timed_out:
        return "timed out"
    if run.returncode != 0:
        return f"exited with code {run.returncode}"
    if any(_is_sanitizer_headline(line) for line in run.stderr.split("\n")):
        return "reported a sanitizer error"
    if output.done is None:
        return "stopped before the last input"
    return ""


def _input_text(inputs: list, index: int, limit: int = 120) -> str:
    """The input as written in the input file, shortened if long."""
    if not 0 <= index < len(inputs):
        return "(no such input)"
    text = inputs[index]
    return text if len(text) <= limit else f"{text[:limit]}... ({len(text)} bytes)"


def _answer(values: "tuple | None") -> str:
    if values is None:
        return "(no answer)"
    return "  ".join(f"{name}={value}" for name, value in zip(FIELDS, values))


def _counts(counter: Counter) -> str:
    return ", ".join(f"{key} {n}" for key, n in counter.most_common())


def _log_excerpt(log: str, max_lines: int) -> list:
    """The useful part of a crash log. Sanitizer reports start with a headline
    ("ERROR: AddressSanitizer: ..." or "... runtime error: ...") and end with a
    hex dump of memory ("Shadow bytes around ..."); keep the headline and stack,
    drop the dump. Without a sanitizer headline, keep the last lines."""
    lines = log.strip().split("\n")
    if lines == [""]:
        return []
    start = next((i for i, line in enumerate(lines) if _is_sanitizer_headline(line)), None)
    if start is None:
        return lines[-max_lines:]
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("Shadow bytes")), len(lines))
    excerpt = lines[start:end]
    if len(excerpt) > max_lines:
        summary = [line for line in excerpt if line.startswith("SUMMARY:")]
        excerpt = excerpt[:max_lines - len(summary) - 1] + ["..."] + summary
    return excerpt


def _crash_report(verdict: Verdict, inputs: list, log_lines: int = 40) -> list:
    if verdict.crash_index is None:
        where = "after answering every input (at exit)"
    else:
        where = f"on input #{verdict.crash_index + 1}: {_input_text(inputs, verdict.crash_index)}"
    lines = [f"CRASH: candidate {verdict.crash_reason} {where}"]
    excerpt = _log_excerpt(verdict.crash_log, log_lines)
    if excerpt:
        lines.append("  its error output:")
        lines += ["    " + line for line in excerpt]
    return lines


def report(verdict: Verdict, inputs: list, max_examples: int = 10) -> str:
    if verdict.status == "pass":
        return f"PASS: {verdict.checks} checks, no differences from the baseline"
    if verdict.status == "crash":
        lines = _crash_report(verdict, inputs)
        if verdict.mismatches or verdict.problems:
            lines += ["", "Before stopping, it also answered differently:"]
            lines += _difference_report(verdict, inputs, max_examples)
        return "\n".join(lines)
    return "\n".join(_difference_report(verdict, inputs, max_examples))


def _difference_report(verdict: Verdict, inputs: list, max_examples: int) -> list:
    by_input = {}
    for m in verdict.mismatches:
        by_input.setdefault(m.index, []).append(m)
    if not verdict.mismatches:
        lines = ["FAIL: the candidate's output does not match the baseline's"]
    else:
        lines = [
            f"FAIL: {len(verdict.mismatches)} of {verdict.checks} checks differ from the baseline"
            f" ({len(by_input)} inputs)",
            f"  by config: {_counts(Counter(m.config for m in verdict.mismatches))}",
            f"  by field:  {_counts(Counter(f for m in verdict.mismatches for f in m.fields))}",
        ]
    if verdict.problems:
        lines += ["", f"Problems in the candidate's output ({len(verdict.problems)}):"]
        lines += ["  " + p for p in verdict.problems[:max_examples]]
    if by_input:
        # Smallest inputs first: they are the easiest to debug.
        shown = sorted(by_input, key=lambda i: (len(inputs[i]) if 0 <= i < len(inputs) else 0, i))[:max_examples]
        lines += ["", f"Smallest differing inputs ({len(shown)} of {len(by_input)}):"]
        for index in shown:
            first, *rest = by_input[index]
            lines.append(f"  input #{index + 1}: {_input_text(inputs, index)}")
            lines.append(f"    config {first.config}" + (f" (also {', '.join(m.config for m in rest)})" if rest else ""))
            lines.append(f"      baseline:  {_answer(first.old)}")
            lines.append(f"      candidate: {_answer(first.new)}")
    return lines
