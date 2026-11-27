#!/usr/bin/env python3
"""Path rules every pull request must follow.

Usage: python3 ci/check_paths.py BASE HEAD
       (BASE and HEAD are git revisions; CI passes the PR's base and merge commit)

Rules:
  1. bughunt/ is a read-only record of the bug hunt.
  2. In json-c/, only json-c/json_tokener.c may change, and it may not be
     deleted or renamed: everything else in json-c/ is the baseline the
     rewrite is compiled against.
  3. A PR that changes json-c/json_tokener.c (a rewrite) changes nothing
     else. That keeps every rewrite judged by main's own checker and CI:
     a PR that changes the gate never also carries a rewrite, and needs
     Role A's approval through .github/CODEOWNERS.

Exit codes: 0 the rules hold, 1 a rule is broken, 2 git failed.
"""
import subprocess
import sys

REWRITE = "json-c/json_tokener.c"


def changed_files(base: str, head: str) -> list:
    """(status, path) for every file that differs. --no-renames shows a
    rename as a delete plus an add, so both paths are checked."""
    out = subprocess.run(["git", "diff", "--name-status", "--no-renames", base, head],
                         check=True, capture_output=True, text=True).stdout
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if line]


def broken_rules(changes: list) -> list:
    paths = [path for _, path in changes]
    problems = []
    for status, path in changes:
        if path.startswith("bughunt/"):
            problems.append(f"{path}: bughunt/ is a read-only record")
        elif path.startswith("json-c/") and path != REWRITE:
            problems.append(f"{path}: only {REWRITE} may change in json-c/")
        elif path == REWRITE and status == "D":
            problems.append(f"{path}: the tokener may not be deleted or renamed")
    if REWRITE in paths:
        others = [p for p in paths if p != REWRITE and not p.startswith(("json-c/", "bughunt/"))]
        problems += [f"{p}: a rewrite PR may only change {REWRITE}" for p in others]
    return problems


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        changes = changed_files(*argv)
    except subprocess.CalledProcessError as e:
        print(f"git diff failed: {e.stderr.strip()}")
        return 2
    problems = broken_rules(changes)
    kind = "rewrite PR" if any(path == REWRITE for _, path in changes) else "not a rewrite PR"
    if problems:
        print(f"PATH RULES BROKEN ({kind}, {len(changes)} files changed):")
        print("\n".join("  " + p for p in problems))
        return 1
    print(f"PATH RULES OK ({kind}, {len(changes)} files changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
