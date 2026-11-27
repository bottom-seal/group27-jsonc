#!/usr/bin/env python3
"""Metrics for the old-vs-new gate: what the gate's inputs exercise in
json_tokener.c, and how a candidate compares with the baseline.

Report only. The verdict is oracle/check.py's: this script makes the same
comparison and prints its first line, so the numbers can be read next to it,
but its exit code never depends on the verdict.

Usage: python3 oracle/metrics.py [CANDIDATE] [--inputs FILE]... [--repeat N] [--json FILE]
       (CANDIDATE defaults to json-c/json_tokener.c in the working tree)

Reported:
  verdict   the comparison check.py makes: PASS, FAIL or CRASH
  time      best of --repeat runs of the gate's own (sanitizer) build, for the
            baseline and the candidate, and the ratio the time limit applies to
  coverage  lines and branches of json_tokener.c that the inputs run, for both
            versions and per function, from a second build with gcov (the
            tokener at -O0 without sanitizers, so the counts follow the source)
  unrun     the candidate's lines that no input runs, in three groups: unrun in
            the baseline too (mostly out-of-memory paths), ran in the baseline
            but not here, and new or changed code. The gate says nothing about
            the last two.
  states    how often the inputs enter each state of json_tokener_parse_ex
            (for a source that keeps the `case json_tokener_state_...:` labels)
  answers   which error codes the baseline's answers contain, and which never
  inputs    how many, the longest, how many over 1,000 bytes

Exit codes: 0 report written (whatever the verdict), 3 the candidate does not
build, 4 the script could not run. Needs gcc's gcov (or set GCOV).
"""
import argparse
import difflib
import json
import os
import re
import shlex
import sys
import tempfile
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import (BASELINE_TIME_LIMIT, CC, EXIT_BUILD, EXIT_INTERNAL, LINK_WRAP, REPO, SANITIZE,  # noqa: E402
                   Baseline, CheckerError, baseline_tokener_source, build, load_inputs,
                   placed_source, run_recorder, sh)
from compare import compare, parse_output, report  # noqa: E402

EXIT_REPORTED = 0
GCOV = os.environ.get("GCOV", "gcov")
# Appended to cmake's command for json_tokener.c; later flags win over its -O1
# and sanitizer flags.
COVERAGE_FLAGS = ["-O0", "-fno-sanitize=all", "--coverage"]
STATE_LABEL = re.compile(r"^\s*case\s+json_tokener_state_(\w+)\s*:")
ESCAPE = re.compile(r"\\x[0-9A-Fa-f]{2}")
BIG_INPUT = 1000  # bytes; the inputs are small, so big ones are counted separately

UNRUN_GROUPS = (
    ("same", "unrun in the baseline too"),
    ("lost", "ran in the baseline, not here"),
    ("new", "new or changed code"),
)


class CoverageBuild:
    """Builds a tokener for gcov through check.build(): cmake's command for
    json_tokener.c plus COVERAGE_FLAGS, linked against the same sanitizer
    build of the rest of json-c and the recorder."""

    def __init__(self, baseline: Baseline, tmp: Path):
        entry = json.loads(baseline.tokener_cmd.read_text())
        entry["arguments"] = (entry.get("arguments") or shlex.split(entry["command"])) + COVERAGE_FLAGS
        self.tokener_cmd = tmp / "coverage-compile.json"
        self.tokener_cmd.write_text(json.dumps(entry))
        self.rest_lib = baseline.rest_lib

    # Baseline.compile_tokener only reads self.tokener_cmd, so the gate's own
    # compile step is reused with the extra flags.
    compile_tokener = Baseline.compile_tokener

    def link(self, tokener_obj: Path, recorder_obj: Path, out: Path):
        return sh([CC, *SANITIZE, "--coverage", str(recorder_obj), str(tokener_obj), "-Wl,--whole-archive",
                   str(self.rest_lib), "-Wl,--no-whole-archive", *LINK_WRAP, "-lm", "-o", str(out)])


class Coverage:
    """gcov's counts for one json_tokener.c: lines {line: count}, branches
    [count, ...] and functions [{name, start, lines, run, calls}]."""

    def __init__(self, gcov_json: dict, source: Path):
        files = [f for f in gcov_json["files"] if Path(f["file"]).resolve() == source.resolve()]
        if len(files) != 1:
            raise CheckerError(f"gcov has no data for {source}: {[f['file'] for f in gcov_json['files']]}")
        lines = files[0]["lines"]
        self.lines = {}
        for line in lines:  # a line can be listed more than once (e.g. inlined code); keep the most
            self.lines[line["line_number"]] = max(line["count"], self.lines.get(line["line_number"], 0))
        self.branches = [b["count"] for line in lines for b in line["branches"]]
        per_function = Counter(), Counter()
        for line in lines:
            per_function[0][line["function_name"]] += 1
            per_function[1][line["function_name"]] += line["count"] > 0
        self.functions = [{"name": f["name"], "start": f["start_line"], "lines": per_function[0][f["name"]],
                           "run": per_function[1][f["name"]], "calls": f["execution_count"]}
                          for f in sorted(files[0]["functions"], key=lambda f: f["start_line"])]

    def summary(self) -> dict:
        return {"lines": len(self.lines), "lines_run": sum(1 for c in self.lines.values() if c),
                "branches": len(self.branches), "branches_taken": sum(1 for c in self.branches if c)}


def read_coverage(obj: Path) -> "tuple[Coverage | None, str]":
    """Coverage from the .gcda the run left next to obj, or (None, why not)."""
    if not obj.with_suffix(".gcda").exists():
        return None, "the coverage run left no data (it crashed or was killed before exiting)"
    result = sh([GCOV, "--json-format", "--stdout", "--branch-probabilities", obj.name], cwd=obj.parent)
    if result.returncode != 0:
        raise CheckerError(f"{GCOV} failed:\n{result.stdout}{result.stderr}")
    return Coverage(json.loads(result.stdout), placed_source(obj)), ""


def finished(run) -> bool:
    return run.returncode == 0 and not run.timed_out


def unrun_lines(old_text: str, old: Coverage, new_text: str, new: Coverage) -> dict:
    """The candidate's lines that no input runs, grouped as in UNRUN_GROUPS.
    Lines are matched to the baseline with difflib, ignoring indentation."""
    old_lines = [line.strip() for line in old_text.split("\n")]
    new_lines = [line.strip() for line in new_text.split("\n")]
    to_old = {}
    for a, b, size in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_matching_blocks():
        for k in range(size):
            to_old[b + k + 1] = a + k + 1
    groups = {key: [] for key, _ in UNRUN_GROUPS}
    for number, count in sorted(new.lines.items()):
        if count:
            continue
        before = old.lines.get(to_old.get(number))
        groups["same" if before == 0 else "lost" if before else "new"].append(number)
    # Report places, not lines: unrun lines with no other executable line
    # between them form one place.
    order = {number: i for i, number in enumerate(sorted(new.lines))}
    places = {}
    for key, numbers in groups.items():
        places[key] = []
        for number in numbers:
            if places[key] and order[number] == order[places[key][-1]["last"]] + 1:
                places[key][-1].update(last=number, lines=places[key][-1]["lines"] + 1)
            else:
                places[key].append({"first": number, "last": number, "lines": 1,
                                    "text": new_text.split("\n")[number - 1].strip()[:70]})
    return places


def state_visits(text: str, cov: Coverage) -> list:
    """[[state names], times entered] for each `case json_tokener_state_X:`.
    Labels on consecutive lines share their code, so they share one count."""
    groups = []
    last = None
    for number, line in enumerate(text.split("\n"), 1):
        match = STATE_LABEL.match(line)
        if not match:
            continue
        count = cov.lines.get(number)
        if last == number - 1:
            groups[-1][0].append(match.group(1))
            if count is not None:
                groups[-1][1] = max(groups[-1][1] or 0, count)
        else:
            groups.append([[match.group(1)], count])
        last = number
    return groups


def error_names(baseline: Baseline) -> list:
    """The enum json_tokener_error names in order, without the json_tokener_ prefix."""
    header = (baseline.src / "json_tokener.h").read_text()
    body = re.search(r"enum\s+json_tokener_error\s*\{(.*?)\}", header, re.S).group(1)
    return re.findall(r"json_tokener_(\w+)", body)


def answer_mix(output: str, names: list) -> dict:
    records = parse_output(output).records
    codes = Counter(int(err.split(" ", 1)[0]) for (_, _), (_, err, _, _) in records.items() if err != "-")
    default = [err for (_, mode), (_, err, _, _) in records.items() if mode == "oneshot/default"]
    return {"checks": len(records),
            "by_error": {names[code] if code < len(names) else str(code): n for code, n in sorted(codes.items())},
            "never": [name for code, name in enumerate(names) if code not in codes],
            "default_accepted": sum(1 for err in default if err.startswith("0 ")),
            "default_rejected": sum(1 for err in default if not err.startswith("0 "))}


def input_stats(inputs: list) -> dict:
    sizes = [len(ESCAPE.sub("x", line)) for line in inputs]
    non_ascii = sum(1 for line in inputs
                    if any(ord(ch) > 0x7F for ch in line) or re.search(r"\\x[89A-Fa-f][0-9A-Fa-f]", line))
    return {"count": len(inputs), "bytes": sum(sizes), "longest": max(sizes, default=0),
            "over_1000_bytes": sum(1 for s in sizes if s > BIG_INPUT), "with_non_ascii": non_ascii}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidate", nargs="?", default=str(REPO / "json-c" / "json_tokener.c"))
    ap.add_argument("--inputs", action="append", metavar="FILE",
                    help="input file; repeat for several (default: every oracle/inputs/*.txt)")
    ap.add_argument("--repeat", type=int, default=3, help="timed runs of each version; the best counts (default 3)")
    ap.add_argument("--show", type=int, default=8, help="places to list per group of unrun lines (default 8)")
    ap.add_argument("--json", metavar="FILE", help="also write every number to this JSON file")
    ap.add_argument("--timeout", type=float, default=10, help="as in check.py (default 10)")
    ap.add_argument("--slowdown", type=float, default=20, help="as in check.py (default 20)")
    ap.add_argument("--build-dir", default=str(REPO / ".build" / "oracle"))
    args = ap.parse_args(argv)
    args.inputs = args.inputs or sorted(str(p) for p in (REPO / "oracle" / "inputs").glob("*.txt"))
    args.repeat = max(1, args.repeat)
    try:
        return measure(args)
    except CheckerError as e:
        print(f"METRICS ERROR: {e}")
    except Exception:  # a bug in this script must not look like a result
        print("METRICS ERROR: unexpected failure\n" + traceback.format_exc())
    return EXIT_INTERNAL


def measure(args) -> int:
    candidate = Path(args.candidate)
    if not candidate.is_file():
        raise CheckerError(f"candidate {candidate} is not a file")
    baseline = Baseline(Path(args.build_dir))
    inputs = load_inputs(args.inputs)
    old_text = baseline_tokener_source().decode("latin-1")
    new_text = candidate.read_bytes().decode("latin-1")

    with tempfile.TemporaryDirectory(prefix="oracle-metrics-") as tmp:
        tmp = Path(tmp)
        baseline.compile_recorder(tmp / "recorder.o")
        old_source = tmp / "baseline_json_tokener.c"
        old_source.write_text(old_text, encoding="latin-1")
        gcov_build = CoverageBuild(baseline, tmp)
        for builder, name in ((baseline, "old"), (gcov_build, "oldcov")):
            problem = build(builder, old_source, tmp, name)
            if problem:
                raise CheckerError(f"the baseline does not build ({name}):\n{problem}")
        problem = build(baseline, candidate, tmp, "new")
        if problem:
            print(f"BUILD ERROR: the candidate {candidate} does not build\n{problem}")
            return EXIT_BUILD
        new_cov_problem = build(gcov_build, candidate, tmp, "newcov")

        old_runs = [run_recorder(tmp / "old", inputs, BASELINE_TIME_LIMIT, baseline.locale_dir) for _ in range(args.repeat)]
        if not all(finished(run) for run in old_runs):
            raise CheckerError("the baseline recorder failed:\n" + next(r for r in old_runs if not finished(r)).stderr[-3000:])
        old_cov_run = run_recorder(tmp / "oldcov", inputs, BASELINE_TIME_LIMIT, baseline.locale_dir)
        old_cov, why = read_coverage(tmp / "oldcov.o")
        if old_cov is None:
            raise CheckerError(f"no coverage for the baseline: {why}\n{old_cov_run.stderr[-3000:]}")
        # As in check.py, the candidate never runs while a baseline binary exists.
        (tmp / "old").unlink()
        (tmp / "oldcov").unlink()

        limit = max(args.timeout, args.slowdown * old_runs[0].elapsed)  # the gate's own limit
        new_runs = [run_recorder(tmp / "new", inputs, limit, baseline.locale_dir)]
        while len(new_runs) < args.repeat and finished(new_runs[-1]):
            new_runs.append(run_recorder(tmp / "new", inputs, limit, baseline.locale_dir))
        if new_cov_problem:
            new_cov, new_cov_why = None, "the candidate does not build with --coverage -O0:\n" + new_cov_problem
        else:
            run_recorder(tmp / "newcov", inputs, max(args.timeout, args.slowdown * old_cov_run.elapsed), baseline.locale_dir)
            new_cov, new_cov_why = read_coverage(tmp / "newcov.o")

    verdict = compare(old_runs[0], new_runs[0])
    old_best = min(run.elapsed for run in old_runs)
    new_times = [run.elapsed for run in new_runs if finished(run)]
    new_best = min(new_times) if len(new_times) == len(new_runs) else None
    names = error_names(baseline)
    result = {
        "candidate": str(candidate),
        "verdict": {"status": verdict.status, "checks": verdict.checks,
                    "line": report(verdict, inputs).split("\n")[0]},
        "time": {"runs": args.repeat, "baseline_s": round(old_best, 3),
                 "candidate_s": None if new_best is None else round(new_best, 3),
                 "ratio": None if new_best is None else round(new_best / old_best, 2),
                 "limit_s": round(limit, 1), "allowed_ratio": args.slowdown, "min_limit_s": args.timeout},
        "coverage": {"baseline": old_cov.summary(), "candidate": new_cov.summary() if new_cov else None,
                     "candidate_missing": new_cov_why},
        "functions": {"baseline": old_cov.functions, "candidate": new_cov.functions if new_cov else None},
        "unrun": unrun_lines(old_text, old_cov, new_text, new_cov) if new_cov else None,
        "states": {"baseline": state_visits(old_text, old_cov),
                   "candidate": state_visits(new_text, new_cov) if new_cov else None},
        "answers": answer_mix(old_runs[0].output, names),
        "inputs": input_stats(inputs),
    }
    print(render(result, args.show))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1) + "\n")
    return EXIT_REPORTED


def percent(part: int, whole: int) -> str:
    """"645/704  91.6%", the fraction padded so the percentages line up."""
    return f"{part}/{whole}".ljust(9) + (f"{part / whole:6.1%}" if whole else "")


def render(m: dict, show: int) -> str:
    out = [f"METRICS for {m['candidate']}  (report only; check.py gives the verdict)", ""]
    out.append(f"Verdict   {m['verdict']['line']}")

    t = m["time"]
    runs = f"best of {t['runs']} runs" if t["runs"] > 1 else "1 run"
    out += ["", f"Time      {runs} of the gate's sanitizer build",
            f"  baseline   {t['baseline_s']:7.2f} s"]
    if t["candidate_s"] is None:
        out.append("  candidate  did not finish every run (see the verdict)")
    else:
        out.append(f"  candidate  {t['candidate_s']:7.2f} s   {t['ratio']:.2f}x the baseline")
    out.append(f"  the gate's time limit on this run: {t['limit_s']:.1f} s"
               f" ({t['allowed_ratio']:g}x the baseline's first run, at least {t['min_limit_s']:g} s)")

    c = m["coverage"]
    out += ["", "Coverage  json_tokener.c run by the inputs (gcov build: tokener at -O0, no sanitizers)",
            f"  {'':11}{'lines':18}branches"]
    for who in ("baseline", "candidate"):
        s = c[who]
        if s:
            out.append(f"  {who:11}{percent(s['lines_run'], s['lines']):18}{percent(s['branches_taken'], s['branches'])}")
    if not c["candidate"]:
        out.append(f"  candidate  no coverage: {c['candidate_missing']}")

    funcs = m["functions"]["candidate"]
    if funcs:
        old = {f["name"]: f for f in m["functions"]["baseline"]}
        partly = [f for f in funcs if f["run"] < f["lines"] or f["name"] not in old]
        out += ["", "  Functions not fully run, or new (candidate; the baseline in brackets):"]
        for f in partly:
            before = old.get(f["name"])
            was = f"({before['run']}/{before['lines']})" if before else "(new)"
            out.append(f"    {f['name']:30}{percent(f['run'], f['lines']):18}{was:12}called {f['calls']:,} times")
        gone = sorted(set(old) - {f["name"] for f in funcs})
        out.append(f"    {len(funcs) - len(partly)} other functions fully run"
                   + (f"; gone from the baseline: {', '.join(gone)}" if gone else ""))

    if m["unrun"] is not None:
        total = sum(p["lines"] for places in m["unrun"].values() for p in places)
        out += ["", f"Unrun     candidate lines that no input runs: {total}"]
        for key, label in UNRUN_GROUPS:
            places = m["unrun"][key]
            lines = sum(p["lines"] for p in places)
            note = {"same": "", "lost": "  <- the inputs no longer reach this; check why",
                    "new": "  <- the gate checks nothing here"}[key] if places else ""
            out.append(f"  {label:31}{lines:4} lines in {len(places)} place{'' if len(places) == 1 else 's'}{note}")
            for p in places[:show]:
                where = f"L{p['first']}" + (f"-{p['last']}" if p["last"] != p["first"] else "")
                out.append(f"    {where:11}{p['text']}")
            if len(places) > show:
                out.append(f"    ... and {len(places) - show} more (--show, --json)")

    out += ["", "States    times the inputs enter each state of json_tokener_parse_ex"]
    for who in ("baseline", "candidate"):
        groups = m["states"][who]
        if groups is None:
            continue
        if not groups:
            out.append(f"  {who:11}no `case json_tokener_state_...:` labels in this source")
            continue
        states = sum(len(names) for names, _ in groups)
        never = ["/".join(names) for names, count in groups if not count]
        least = sorted((g for g in groups if g[1]), key=lambda g: g[1])[:4]
        out.append(f"  {who:11}{states} states, " + (f"never entered: {', '.join(never)}" if never else "all entered")
                   + "; least: " + ", ".join(f"{'/'.join(names)} {count:,}" for names, count in least))

    a = m["answers"]
    out += ["", f"Answers   error codes in the baseline's {a['checks']:,} answers"]
    out += [f"  {name:31}{n:8,}" for name, n in a["by_error"].items()]
    out.append(f"  never produced: {', '.join(a['never']) or 'none'}")
    out.append(f"  oneshot with default flags: {a['default_accepted']:,} inputs accepted,"
               f" {a['default_rejected']:,} rejected")

    i = m["inputs"]
    out += ["", f"Inputs    {i['count']:,} inputs, {i['bytes']:,} bytes; longest {i['longest']:,} bytes;"
            f" {i['over_1000_bytes']} over {BIG_INPUT:,} bytes; {i['with_non_ascii']:,} with non-ASCII bytes"]
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
