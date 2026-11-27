"""End-to-end tests for oracle/metrics.py, the gate's report-only metrics.

Like test_check.py, these build candidates from the baseline source and reuse
the json-c build in .build/. Every run passes --inputs and --repeat 1, so the
numbers refer to oracle/inputs/core.txt and each run takes a few seconds.
"""
import json
import subprocess
import sys
from pathlib import Path

from test_check import CORE_INPUTS, REPO, candidate

METRICS = REPO / "oracle" / "metrics.py"
START = "\ttok->char_offset = 0;\n\ttok->err = json_tokener_success;\n"
KEY_SEPARATOR = "\t\tcase json_tokener_state_object_field_end:\n\t\t\tif (c == ':')\n"


def run_metrics(cand: Path, tmp_path: Path):
    """Run metrics.py on cand; returns the process and its JSON (None if none)."""
    out = tmp_path / "metrics.json"
    result = subprocess.run(
        [sys.executable, str(METRICS), str(cand), "--inputs", str(CORE_INPUTS), "--repeat", "1",
         "--json", str(out)],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    return result, json.loads(out.read_text()) if out.exists() else None


def line_of(path: Path, text: str) -> int:
    lines = path.read_text().split("\n")
    return next(i for i, line in enumerate(lines, 1) if text in line)


def test_unchanged_tokener_measures_like_the_baseline(tmp_path):
    result, m = run_metrics(candidate(tmp_path), tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert m["verdict"]["status"] == "pass" and m["verdict"]["checks"] > 0
    assert m["coverage"]["candidate"] == m["coverage"]["baseline"]
    assert 0 < m["coverage"]["baseline"]["lines_run"] < m["coverage"]["baseline"]["lines"]
    assert m["unrun"]["same"] and not m["unrun"]["lost"] and not m["unrun"]["new"]
    assert m["states"]["candidate"] == m["states"]["baseline"]
    assert all(count for _, count in m["states"]["baseline"])  # core.txt enters every state
    assert m["time"]["candidate_s"] > 0 and m["time"]["ratio"] > 0
    # The recorder makes allocations fail on purpose, so "out of memory" is answered too.
    assert "error_memory" not in m["answers"]["never"] and m["answers"]["by_error"]["success"] > 0
    assert m["inputs"]["count"] == 3402
    assert result.stdout.startswith("METRICS for ")


def test_code_that_no_input_runs_is_listed_as_new(tmp_path):
    # A special case for one input length: the gate passes it, because no
    # input has that length. This is what the metrics are for.
    cand = candidate(tmp_path, START, START + "\tif (len == 123456789)\n\t{\n"
                     "\t\ttok->err = json_tokener_error_parse_eof;\n\t\treturn NULL;\n\t}\n")
    result, m = run_metrics(cand, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert m["verdict"]["status"] == "pass"
    planted = line_of(cand, "123456789")
    assert [(p["first"], p["last"]) for p in m["unrun"]["new"]] == [(planted + 2, planted + 3)]
    assert not m["unrun"]["lost"]
    assert "the gate checks nothing here" in result.stdout


def test_code_that_stops_running_is_listed_even_when_the_verdict_is_fail(tmp_path):
    # Never accepting the ':' after an object key changes answers (FAIL), and
    # the states that read an object's values, which the baseline runs, are
    # never reached.
    cand = candidate(tmp_path, KEY_SEPARATOR, KEY_SEPARATOR.replace("(c == ':')", "(0 && c == ':')"))
    result, m = run_metrics(cand, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert m["verdict"]["status"] == "different"
    assert result.stdout.split("\n")[2].startswith("Verdict   FAIL")
    value_state = line_of(cand, "case json_tokener_state_object_value:")
    assert any(p["first"] <= value_state <= p["last"] for p in m["unrun"]["lost"])
    assert not m["unrun"]["new"]
    assert dict((tuple(names), count) for names, count in m["states"]["candidate"])[("object_value",)] == 0


def test_a_crash_is_reported_without_candidate_coverage(tmp_path):
    cand = candidate(tmp_path, START, START + "\tif (len > 1 && str[0] == '{' && str[1] == '}')\n\t\tabort();\n")
    result, m = run_metrics(cand, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert m["verdict"]["status"] == "crash"
    assert m["time"]["candidate_s"] is None
    assert m["coverage"]["candidate"] is None and m["unrun"] is None
    assert "no coverage" in result.stdout


def test_candidate_that_does_not_compile_is_a_build_error(tmp_path):
    result, m = run_metrics(candidate(tmp_path, START, START + "\tthis is not C;\n"), tmp_path)
    assert result.returncode == 3
    assert "BUILD ERROR" in result.stdout and m is None
