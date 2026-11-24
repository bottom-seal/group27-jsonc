#!/usr/bin/env python3
"""Differential fuzzing of a candidate json_tokener.c against the baseline.

Builds fuzz/diff_fuzz.c with libFuzzer: the baseline tokener (the git tree
oracle/check.py pins) and the candidate in one program, every global symbol
of each renamed old_* and new_*. Runs it for --seconds, starting from the
gate's inputs (oracle/inputs/*.txt), the bug hunt's corpus
(bughunt/fuzz_corpus.tgz) and whatever earlier runs kept (.build/fuzz/corpus).
A difference in the answers or a sanitizer error stops it: the input is
saved, and printed as a line ready for oracle/inputs/fuzz.txt, which makes it
a permanent case of the gate.

Usage: python3 fuzz/fuzz.py [CANDIDATE] [--seconds N] [--jobs N] [--no-corpus]
       (CANDIDATE defaults to json-c/json_tokener.c in the working tree)

Exit codes: 0 nothing found, 1 a difference or crash found, 3 the candidate
does not build, 4 the script could not run. Needs clang with libFuzzer, nm
and objcopy, plus what oracle/check.py needs.
"""
import argparse
import fcntl
import hashlib
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "oracle"))
import check  # noqa: E402

CLANG = os.environ.get("FUZZ_CC", "clang")
CFLAGS = ["-g", "-O1", "-fsanitize=fuzzer-no-link,address,undefined", "-fno-sanitize-recover=undefined",
          "-D_GNU_SOURCE"]
LDFLAGS = ["-fsanitize=fuzzer,address,undefined"]
# The tokener's public functions: other json-c files (json_util.c) call some
# of them, and those calls go to the baseline.
TOKENER_API = ["json_tokener_new", "json_tokener_new_ex", "json_tokener_free", "json_tokener_reset",
               "json_tokener_set_flags", "json_tokener_parse_ex", "json_tokener_get_error",
               "json_tokener_get_parse_end", "json_tokener_error_desc", "json_tokener_parse",
               "json_tokener_parse_verbose"]
EXIT_NOTHING, EXIT_FOUND, EXIT_BUILD, EXIT_INTERNAL = 0, 1, 3, 4
MAX_LEN = 4096


def globals_defined(obj: Path) -> list:
    """External symbols the object defines, except compiler-made ones (__*)."""
    out = check.must(["nm", "--defined-only", "-g", str(obj)]).stdout
    names = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and not parts[2].startswith("__"):
            names.append(parts[2])
    return names


def rename(obj: Path, prefix: str, names: list):
    if names:
        check.must(["objcopy", *[f"--redefine-sym={n}={prefix}{n}" for n in names], str(obj)])


class FuzzBuild:
    """The rest of json-c built once with clang for libFuzzer, in a cache
    folder named after the baseline, the compiler and the flags."""

    def __init__(self, oracle_build: Path, fuzz_root: Path):
        self.baseline = check.Baseline(oracle_build)  # json-c's sources and config headers
        compiler = check.must([CLANG, "--version"]).stdout.split("\n")[0]
        key = hashlib.sha256(repr([check.BASELINE_TREE, compiler, CFLAGS]).encode()).hexdigest()[:12]
        self.root = fuzz_root
        self.rest = fuzz_root / f"rest-{key}"
        self.include = ["-I", str(self.baseline.src), "-I", str(self.baseline.cmake_dir)]
        fuzz_root.mkdir(parents=True, exist_ok=True)
        with open(fuzz_root / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not (self.rest / "ready").exists():
                self._build_rest()

    def _build_rest(self):
        shutil.rmtree(self.rest, ignore_errors=True)
        self.rest.mkdir(parents=True)
        members = check.must(["ar", "t", str(self.baseline.cmake_dir / "libjson-c.a")]).stdout.split()
        for member in members:
            source = member[:-2] if member.endswith(".o") else member  # "printbuf.c.o" -> "printbuf.c"
            if source == "json_tokener.c":
                continue
            obj = self.rest / member
            check.must([CLANG, *CFLAGS, *self.include, "-c", str(self.baseline.src / source), "-o", str(obj)])
            rename(obj, "old_", TOKENER_API)  # json_util.c's calls into the tokener
        (self.rest / "ready").write_text("")

    def compile_tokener(self, source: Path, obj: Path, prefix: str) -> str:
        """Compile one json_tokener.c and rename all its globals. Returns ""
        or the compiler's complaint."""
        placed = obj.parent / prefix / "json_tokener.c"  # so messages name json_tokener.c
        placed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, placed)
        result = check.sh([CLANG, *CFLAGS, *self.include, "-c", str(placed), "-o", str(obj)])
        if result.returncode != 0:
            return (result.stdout + result.stderr).replace(str(placed), str(source)).strip()
        rename(obj, prefix, globals_defined(obj))
        return ""

    def link(self, candidate: Path, tmp: Path, out: Path) -> str:
        old_source = tmp / "baseline_json_tokener.c"
        old_source.write_bytes(check.baseline_tokener_source())
        problem = self.compile_tokener(old_source, tmp / "old.o", "old_")
        if problem:
            raise check.CheckerError("the baseline does not build for fuzzing:\n" + problem)
        problem = self.compile_tokener(candidate, tmp / "new.o", "new_")
        if problem:
            return problem
        check.must([CLANG, *CFLAGS, *self.include, "-c", str(REPO / "fuzz" / "diff_fuzz.c"),
                    "-o", str(tmp / "harness.o")])
        result = check.sh([CLANG, *LDFLAGS, str(tmp / "harness.o"), str(tmp / "old.o"), str(tmp / "new.o"),
                           *sorted(str(p) for p in self.rest.glob("*.o")), "-lm", "-o", str(out)])
        return "" if result.returncode == 0 else (result.stdout + result.stderr).strip()


def write_input_seeds(folder: Path):
    """Every gate input as a seed, once under default flags (byte 0 = 0) and
    once under strict (1), cut after its first byte."""
    folder.mkdir(parents=True, exist_ok=True)
    for path in sorted((REPO / "oracle" / "inputs").glob("*.txt")):
        for line in check.load_inputs([path]):
            doc = re.sub(rb"\\x([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), line.encode("latin-1"))
            if len(doc) > MAX_LEN - 2:
                continue
            for flags in (0, 1):
                seed = bytes([flags, 1]) + doc
                (folder / hashlib.sha1(seed).hexdigest()).write_bytes(seed)


def bughunt_corpus(fuzz_root: Path) -> Path:
    folder = fuzz_root / "bughunt-corpus"
    if not (folder / "ready").exists():
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        with tarfile.open(REPO / "bughunt" / "fuzz_corpus.tgz") as tar:
            tar.extractall(folder, filter="data")
        (folder / "ready").write_text("")
    return folder


def as_input_line(data: bytes) -> str:
    """A fuzzer input as a line for oracle/inputs/*.txt (bytes 0-1 dropped)."""
    return "".join(chr(b) if 0x20 <= b < 0x7F and b != 0x5C else f"\\x{b:02x}" for b in data[2:])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidate", nargs="?", default=str(REPO / "json-c" / "json_tokener.c"))
    ap.add_argument("--seconds", type=int, default=300, help="how long to fuzz (default 300)")
    ap.add_argument("--jobs", type=int, default=1, help="parallel fuzzing processes (default 1)")
    ap.add_argument("--no-corpus", action="store_true",
                    help="start from the gate's inputs only, not the bug hunt's 27,000-input corpus")
    ap.add_argument("--build-dir", default=str(REPO / ".build"))
    args = ap.parse_args(argv)
    try:
        return fuzz(args)
    except check.CheckerError as e:
        print(f"FUZZ ERROR: {e}")
    except Exception:  # a bug in this script must not look like a result
        import traceback
        print("FUZZ ERROR: unexpected failure\n" + traceback.format_exc())
    return EXIT_INTERNAL


def fuzz(args) -> int:
    candidate = Path(args.candidate).resolve()
    if not candidate.is_file():
        raise check.CheckerError(f"candidate {candidate} is not a file")
    build_root = Path(args.build_dir)
    fuzz_root = build_root / "fuzz"
    builder = FuzzBuild(build_root / "oracle", fuzz_root)
    findings = fuzz_root / "findings"
    corpus = fuzz_root / "corpus"
    findings.mkdir(parents=True, exist_ok=True)
    corpus.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fuzz-") as tmp:
        tmp = Path(tmp)
        problem = builder.link(candidate, tmp, tmp / "fuzzer")
        if problem:
            print(f"BUILD ERROR: the candidate {candidate} does not build for fuzzing\n{problem}")
            return EXIT_BUILD
        write_input_seeds(tmp / "inputs")
        seed_dirs = [str(tmp / "inputs")] + ([] if args.no_corpus else [str(bughunt_corpus(fuzz_root))])
        cmd = [str(tmp / "fuzzer"), f"-dict={REPO / 'fuzz' / 'json.dict'}", f"-max_len={MAX_LEN}",
               f"-max_total_time={args.seconds}", "-timeout=10", "-rss_limit_mb=4096", "-print_final_stats=1",
               f"-artifact_prefix={findings}/", str(corpus), *seed_dirs]
        if args.jobs > 1:
            cmd.insert(1, f"-fork={args.jobs}")
        started = time.time()
        result = check.sh(cmd, timeout=args.seconds + 600, cwd=tmp, env=check.recorder_env())
    log = result.stdout + result.stderr
    runs = re.findall(r"Done (\d+) runs", log)
    if result.returncode == 0:
        print(f"NOTHING FOUND: {runs[-1] if runs else '?'} inputs in {args.seconds} s, no difference from the baseline")
        return EXIT_NOTHING
    found = sorted((p for p in findings.iterdir() if p.stat().st_mtime >= started - 1),
                   key=lambda p: p.stat().st_mtime)
    start = log.find("DIFFERENCE")
    if start >= 0:  # the harness's report, up to libFuzzer's "deadly signal" trace
        end = log.find("\n==", start)
        print("FOUND: the candidate answers differently from the baseline")
    else:  # a sanitizer report or a timeout: its headline and stack
        start = next((m.start() for m in re.finditer(r"==\d+==ERROR|runtime error:|ALARM: working on", log)),
                     max(0, len(log) - 3000))
        end = log.find("\nSUMMARY", start)
        print("FOUND: the candidate crashed, leaked or hung")
    print(log[start:end if end > start else start + 4000][:6000].rstrip())
    if found:
        print(f"\ninput saved: {found[-1]}")
        print("as a line for oracle/inputs/fuzz.txt (bytes 0-1, flags and cut point, dropped):")
        print(as_input_line(found[-1].read_bytes()))
    return EXIT_FOUND


if __name__ == "__main__":
    sys.exit(main())
