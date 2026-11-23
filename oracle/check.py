#!/usr/bin/env python3
"""Old-vs-new checker for json_tokener.c.

Builds the baseline json_tokener.c (git tag `baseline`) and a candidate
json_tokener.c against the same baseline copy of the rest of json-c, runs both
on every input in oracle/inputs/, and reports any difference in behaviour.

Usage: python3 oracle/check.py [CANDIDATE]
       (CANDIDATE defaults to json-c/json_tokener.c in the working tree)

Exit codes:
  0  pass: the candidate answers exactly like the baseline
  1  different: some answer differs
  2  crash: the candidate crashed, hung, or a sanitizer reported an error
  3  build error: the candidate does not compile or link
  4  internal error: the checker itself could not run (e.g. baseline broken)

Needs gcc, cmake and git on PATH (or set CC / CMAKE).
"""
import argparse
import dataclasses
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare import Run, compare, parse_output, report  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ORACLE = REPO / "oracle"
CC = os.environ.get("CC", "gcc")
CMAKE = os.environ.get("CMAKE", "cmake")
SANITIZE = ["-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
            "-fno-omit-frame-pointer", "-g", "-O1"]

# Fixed sanitizer settings for both recorders. Environment options are applied
# after a program's own __asan_default_options(), so these also override a
# candidate that tries to switch checks off that way.
SANITIZER_ENV = {
    "ASAN_OPTIONS": "detect_leaks=1:exitcode=1:halt_on_error=1",
    "LSAN_OPTIONS": "exitcode=1",
    "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
}

BASELINE_TIME_LIMIT = 600  # seconds; the baseline takes a few
COMMAND_TIME_LIMIT = 120  # seconds for one compile or link
CMAKE_TIME_LIMIT = 900  # seconds for building the baseline library

EXIT_PASS, EXIT_DIFFERENT, EXIT_CRASH, EXIT_BUILD, EXIT_INTERNAL = 0, 1, 2, 3, 4


class CheckerError(Exception):
    """The checker could not do its job; not the candidate's fault."""


def sh(cmd, timeout: float = COMMAND_TIME_LIMIT, **kw):
    """Run a build command: no stdin, a time limit, and output decoded without
    ever failing on odd bytes (compiler messages quote the source)."""
    kw.setdefault("text", True)
    if kw["text"]:
        kw.setdefault("errors", "replace")
    try:
        return subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        empty = "" if kw["text"] else b""
        return subprocess.CompletedProcess(cmd, 124, empty, f"{cmd[0]} did not finish within {timeout:.0f} s"
                                           if kw["text"] else b"timed out")


def must(cmd, **kw):
    result = sh(cmd, **kw)
    if result.returncode != 0:
        raise CheckerError(f"command failed: {shlex.join(map(str, cmd))}\n{result.stdout}{result.stderr}")
    return result


def placed_source(obj: Path) -> Path:
    """Where a tokener source is copied before compiling it to obj. Compiler
    and sanitizer messages name this path; reports swap it for the real one."""
    return obj.parent / f"{obj.stem}-src" / "json_tokener.c"


class Baseline:
    """The baseline json-c, extracted from the `baseline` tag and built once per
    baseline commit. Everything except json_tokener.c is shared by the old and
    new builds, so the two can only differ in the tokener."""

    def __init__(self, build_root: Path):
        commit = must(["git", "rev-parse", "baseline^{commit}"], cwd=REPO).stdout.strip()
        self.root = build_root / f"baseline-{commit[:12]}"
        self.src = self.root / "src" / "json-c"
        self.cmake_dir = self.root / "cmake"
        self.rest_lib = self.root / "libjson-c-without-tokener.a"
        self.tokener_cmd = self.root / "tokener-compile.json"
        if not (self.root / "ready").exists():
            self._build()

    def _build(self):
        shutil.rmtree(self.root, ignore_errors=True)
        self.src.parent.mkdir(parents=True)
        archive = must(["git", "archive", "--format=tar", "baseline", "json-c"], cwd=REPO, text=False)
        subprocess.run(["tar", "-x", "-C", str(self.src.parent)], input=archive.stdout, check=True)
        must([CMAKE, "-S", str(self.src), "-B", str(self.cmake_dir),
              "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_TESTING=OFF", "-DCMAKE_BUILD_TYPE=Debug",
              f"-DCMAKE_C_COMPILER={CC}", "-DCMAKE_C_FLAGS=" + " ".join(SANITIZE),
              "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"])
        must([CMAKE, "--build", str(self.cmake_dir), "--target", "json-c", "-j", str(os.cpu_count() or 2)],
             timeout=CMAKE_TIME_LIMIT)

        lib = self.cmake_dir / "libjson-c.a"
        shutil.copy(lib, self.rest_lib)
        members = must(["ar", "t", str(self.rest_lib)]).stdout.split()
        tokener = [m for m in members if m.startswith("json_tokener.c.")]
        if len(tokener) != 1:
            raise CheckerError(f"expected one json_tokener object in {lib}, found {tokener}")
        must(["ar", "d", str(self.rest_lib), tokener[0]])

        commands = json.loads((self.cmake_dir / "compile_commands.json").read_text())
        entry = next(c for c in commands if Path(c["file"]).name == "json_tokener.c")
        self.tokener_cmd.write_text(json.dumps(entry))
        (self.root / "ready").write_text("")

    def compile_tokener(self, source: Path, obj: Path) -> subprocess.CompletedProcess:
        """Compile a json_tokener.c with exactly the flags cmake uses for the
        baseline one. The source is copied into its own folder under its real
        name, so compiler messages point at json_tokener.c lines, and its
        #include "..." lines fall through to the baseline headers via -I."""
        entry = json.loads(self.tokener_cmd.read_text())
        args = entry.get("arguments") or shlex.split(entry["command"])
        placed = placed_source(obj)
        placed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, placed)
        cmd = []
        skip = False
        for arg in args:
            if skip:
                skip = False
            elif arg == "-o":
                cmd += ["-o", str(obj)]
                skip = True
            elif arg != "-c" and Path(arg).name != "json_tokener.c":
                cmd.append(arg)
        # -MD writes the list of files the compiler read, checked in build()
        return sh(cmd + ["-MD", "-MF", str(obj.with_suffix(".d")), "-c", str(placed)], cwd=entry["directory"])

    def link(self, tokener_obj: Path, recorder_obj: Path, out: Path):
        # --whole-archive links every json-c object, as the real library build
        # does, so a candidate defining a symbol another json-c file owns gets
        # the same "multiple definition" error instead of silently winning.
        return sh([CC, *SANITIZE, str(recorder_obj), str(tokener_obj),
                   "-Wl,--whole-archive", str(self.rest_lib), "-Wl,--no-whole-archive", "-lm", "-o", str(out)])

    def compile_recorder(self, out: Path):
        must([CC, *SANITIZE, "-I", str(self.src), "-I", str(self.cmake_dir),
              "-c", str(ORACLE / "recorder.c"), "-o", str(out)])


def load_inputs(paths):
    lines = []
    for path in paths:
        lines += Path(path).read_text(encoding="latin-1").split("\n")[:-1]
    return lines


def recorder_env() -> dict:
    """The caller's environment without any sanitizer settings or preloads,
    plus the checker's own sanitizer settings."""
    env = {key: value for key, value in os.environ.items()
           if not key.endswith("SAN_OPTIONS") and key != "LD_PRELOAD"}
    env.update(SANITIZER_ENV)
    return env


def run_recorder(binary: Path, inputs: list, timeout: float) -> Run:
    """Run one recorder. Its answers go to a file next to the binary; what the
    process prints on stdout is kept separately (the tokener should print
    nothing). It runs in its own process group, which is killed afterwards, so
    nothing it started outlives the run."""
    answers = binary.with_suffix(".answers")
    data = ("\n".join(inputs) + "\n").encode("latin-1")
    start = time.monotonic()
    proc = subprocess.Popen([str(binary), str(answers)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=recorder_env(), cwd=binary.parent,
                            start_new_session=True)
    try:
        printed, err = proc.communicate(data, timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        printed, err = proc.communicate()
        timed_out = True
    finally:
        _kill_group(proc)
    elapsed = time.monotonic() - start
    output = answers.read_bytes().decode("latin-1") if answers.exists() else ""
    return Run(output, -1 if timed_out else proc.returncode, timed_out, err.decode("latin-1"),
               printed.decode("latin-1"), elapsed, timeout)


def _kill_group(proc: subprocess.Popen):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def build(baseline: Baseline, source: Path, tmp: Path, name: str, max_lines: int = 40) -> str:
    """Compile and link one recorder binary at tmp/name. Returns "" on success,
    otherwise the first lines of the compiler or linker output."""
    obj = tmp / f"{name}.o"
    result = baseline.compile_tokener(source, obj)
    if result.returncode == 0:
        # json_tokener.c must be the rewrite itself, not a wrapper that
        # #includes another implementation (such as the baseline source).
        included = [dep for dep in obj.with_suffix(".d").read_text().replace("\\\n", " ").split()[1:]
                    if dep.endswith(".c") and Path(dep) != placed_source(obj)]
        if included:
            return "the candidate includes another .c file: " + ", ".join(included)
        result = baseline.link(obj, tmp / "recorder.o", tmp / name)
    if result.returncode == 0:
        return ""
    # Show the user's path, not the temporary copy the compiler saw.
    text = (result.stdout + result.stderr).replace(str(placed_source(obj)), str(source))
    return "\n".join(text.strip().split("\n")[:max_lines])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidate", nargs="?", default=str(REPO / "json-c" / "json_tokener.c"))
    ap.add_argument("--inputs", nargs="+", default=sorted(str(p) for p in (ORACLE / "inputs").glob("*.txt")))
    ap.add_argument("--timeout", type=float, default=10,
                    help="minimum time limit for the candidate, in seconds (default 10)")
    ap.add_argument("--slowdown", type=float, default=20,
                    help="the candidate may take this many times the baseline's time (default 20)")
    ap.add_argument("--build-dir", default=str(REPO / ".build" / "oracle"))
    args = ap.parse_args(argv)

    try:
        baseline = Baseline(Path(args.build_dir))
        inputs = load_inputs(args.inputs)
        with tempfile.TemporaryDirectory(dir=baseline.root) as tmp:
            tmp = Path(tmp)
            baseline.compile_recorder(tmp / "recorder.o")

            problem = build(baseline, baseline.src / "json_tokener.c", tmp, "old")
            if problem:
                raise CheckerError("the baseline does not build:\n" + problem)
            problem = build(baseline, Path(args.candidate), tmp, "new")
            if problem:
                print(f"BUILD ERROR: the candidate {args.candidate} does not build\n{problem}")
                return EXIT_BUILD

            old = run_recorder(tmp / "old", inputs, BASELINE_TIME_LIMIT)
            base = parse_output(old.output)
            if old.returncode != 0 or old.timed_out or base.problems or base.done != len(inputs):
                raise CheckerError(
                    f"baseline recorder failed (exit {old.returncode}, read {base.done} of {len(inputs)} inputs,"
                    f" problems {base.problems[:3]}):\n{old.stderr[-3000:]}")
            new = run_recorder(tmp / "new", inputs, max(args.timeout, args.slowdown * old.elapsed))
            # Sanitizer reports should name the candidate file, not the temporary copy.
            new = dataclasses.replace(new, stderr=new.stderr.replace(str(placed_source(tmp / "new.o")), args.candidate))
    except CheckerError as e:
        print(f"CHECKER ERROR: {e}")
        return EXIT_INTERNAL

    verdict = compare(old, new)
    if verdict.status == "crash" and new.timed_out:
        verdict.crash_reason = (f"timed out after {new.time_limit:.1f} s"
                                f" (the baseline took {old.elapsed:.1f} s)")
    print(report(verdict, inputs))
    return {"pass": EXIT_PASS, "different": EXIT_DIFFERENT, "crash": EXIT_CRASH}[verdict.status]


if __name__ == "__main__":
    sys.exit(main())
