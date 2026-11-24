"""Compare the recorder output of the baseline and a candidate build.

The recorder prints one tab-separated record per (input, config):

    <input index> <config> <type signature> <error> <parse end> <value>

and, once every input is answered, a final line "#done <number of inputs>".
This module turns two such outputs into a verdict and a human-readable report.
The candidate must give exactly the baseline's set of answers: a missing,
extra, duplicated or unreadable line is a difference, never ignored.

The one exception is answers given while an allocation fails on purpose
(see _acceptable_under_failure): a rewrite may allocate in a different order,
so those are judged by what they say, not by matching the baseline's k.
"""
import re
from collections import Counter
from dataclasses import dataclass, field

FIELDS = ("type", "error", "end", "value")

# Answers given while the k-th allocation failed on purpose (recorder.c):
# "oom<k>/<flags>", "oomb<k>/<flags>", "oomv<k>/default", "api/oomnew<k>/<which>".
_UNDER_FAILURE = re.compile(r"^(?:(oomb|oomv|oom)\d+|api/(oomnew)\d+)/(.*)$")
_SAME_PARSE_WITHOUT_FAILURE = {"oom": "oneshot", "oomb": "bytewise"}
OUT_OF_MEMORY = "16 out of memory"


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
        if _failure_group(self.config):
            return ["answer under a failed allocation"]
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
    started: "int | None" = None  # the last "#input" line: the input being worked on


def parse_output(text: str) -> Output:
    # Text after the last "\n" is a line cut off by a crash or a timeout.
    # Split on "\n" only: values can hold bytes like 0x85 that splitlines() treats as breaks.
    complete = text.rpartition("\n")[0]
    out = Output({}, [], None)
    for line in complete.split("\n") if complete else []:
        fields = line.split("\t", len(FIELDS) + 1)
        if line.startswith("#done ") and line[6:].isdigit() and out.done is None:
            out.done = int(line[6:])
        elif line.startswith("#input ") and line[7:].isdigit():
            out.started = int(line[7:])
        elif len(fields) != len(FIELDS) + 2 or not fields[0].isdigit():
            out.problems.append(f"unreadable line: {line[:200]}")
        elif (int(fields[0]), fields[1]) in out.records:
            out.problems.append(f"input #{int(fields[0]) + 1} config {fields[1]} answered twice")
        else:
            out.records[(int(fields[0]), fields[1])] = tuple(fields[2:])
    return out


def _failure_group(config: str) -> "tuple | None":
    """(way, flags) for an answer given while an allocation failed, else None."""
    m = _UNDER_FAILURE.match(config)
    return (m.group(1) or m.group(2), m.group(3)) if m else None


def _answers_under_failure(records: dict) -> dict:
    """For each (input, way, flags): every (type, error, value) the baseline
    gave with some allocation failing, whichever k it was."""
    seen = {}
    for (index, config), (typ, err, _end, value) in records.items():
        group = _failure_group(config)
        if group:
            seen.setdefault((index, *group), set()).add((typ, err, value))
    return seen


def _acceptable_under_failure(index: int, group: tuple, answer: tuple, seen: dict, base: dict) -> bool:
    """A rewrite may allocate differently, so its k-th allocation is not the
    baseline's k-th. Under a failed allocation it may answer anything the
    baseline answered for this input and way under some failed allocation
    (so the baseline's quirks are allowed wherever they move), report "out of
    memory", or give the answer of the same parse with nothing failing.
    Where it stopped (parse end) is not compared. Crashes and leaks still fail
    through the sanitizers, and having more or fewer allocations is fine."""
    typ, err, _end, value = answer
    way, flags = group
    if (typ, err, value) in seen.get((index, way, flags), ()):
        return True
    if way == "oomnew":  # creating a tokener: NULL is the only other right answer
        return value == "NULL"
    if err == OUT_OF_MEMORY and value == "-":
        return True
    normal = base.get((index, "verbose" if way == "oomv" else f"{_SAME_PARSE_WITHOUT_FAILURE[way]}/{flags}"))
    return normal is not None and (typ, err, value) == (normal[0], normal[1], normal[3])


def compare(old: Run, new: Run) -> Verdict:
    base = parse_output(old.output)
    if base.problems or base.done is None:
        raise ValueError(f"baseline output is malformed: {base.problems[:3] or 'no #done line'}")
    cand = parse_output(new.output)
    reason = _crash_reason(new, cand)

    mismatches = []
    for key, answer in base.records.items():
        if _failure_group(key[1]):
            continue  # judged from the candidate's answers, below
        got = cand.records.get(key)
        if got != answer and not (got is None and reason):  # after a crash, missing answers are expected
            mismatches.append(Mismatch(*key, answer, got))
    seen = _answers_under_failure(base.records)
    for key, got in cand.records.items():
        group = _failure_group(key[1])
        if group:
            if not _acceptable_under_failure(key[0], group, got, seen, base.records):
                mismatches.append(Mismatch(*key, base.records.get(key), got))
        elif key not in base.records:
            mismatches.append(Mismatch(*key, None, got))

    problems = list(cand.problems)
    if new.printed != old.printed:
        problems.append(f"printed to stdout (the baseline printed {len(old.printed)} bytes): {new.printed[:300]!r}")
    if not reason and cand.done != base.done:
        problems.append(f"read {cand.done} inputs, the baseline read {base.done}")

    status = "crash" if reason else "different" if mismatches or problems else "pass"
    verdict = Verdict(status, checks=len(base.records), mismatches=mismatches, problems=problems)
    if reason:
        verdict.crash_reason = reason
        verdict.crash_log = new.stderr
        # The input the candidate was working on: the last "#input" line it
        # wrote, or, for output without those lines, the first input with a
        # missing answer. Nothing missing means it stopped after the last answer.
        missing = [index for (index, config) in base.records if (index, config) not in cand.records]
        if not missing:
            verdict.crash_index = None
        else:
            verdict.crash_index = cand.started if cand.started is not None else min(missing)
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


def _which(inputs: list, index: int) -> str:
    """Name the input an answer belongs to. The recorder files its edge-case
    API calls, which use no input, one past the last input."""
    if index == len(inputs):
        return "the edge-case API calls (after the last input)"
    return f"input #{index + 1}: {_input_text(inputs, index)}"


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
        where = f"on {_which(inputs, verdict.crash_index)}"
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
            lines.append(f"  {_which(inputs, index)}")
            lines.append(f"    config {first.config}" + (f" (also {', '.join(m.config for m in rest)})" if rest else ""))
            lines.append(f"      baseline:  {_answer(first.old)}")
            lines.append(f"      candidate: {_answer(first.new)}")
    return lines
