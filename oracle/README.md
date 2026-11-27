# oracle: the old-vs-new checker

Checks whether a rewritten `json_tokener.c` behaves exactly like the baseline
(json-c commit `d2ce61e`). It builds both versions, feeds them the same inputs
in many ways, and compares every answer.

## Running it

```bash
python3 oracle/check.py                     # checks json-c/json_tokener.c in the working tree
python3 oracle/check.py path/to/json_tokener.c
```

Needs `gcc`, `cmake`, `git` (a clone with full history) and Python 3. The first
run builds json-c once into `.build/oracle/` (about 10 seconds); after that a
check takes a few seconds.

Options: `--inputs FILE` (repeat it for several files; default: every
`oracle/inputs/*.txt`),
`--timeout` and `--slowdown` (time limit, below), `--build-dir`.

## Verdicts

| Exit code | Verdict | Meaning |
|---|---|---|
| 0 | `PASS` | Every answer matches the baseline, and the candidate printed nothing the baseline did not. |
| 1 | `FAIL` | Some answers differ, are missing or extra, or the candidate printed to stdout. The report lists the smallest differing inputs, with the baseline's answer next to the candidate's. |
| 2 | `CRASH` | The candidate crashed, stopped early, leaked memory, a sanitizer (ASan/UBSan/LSan) reported an error even if every answer was right, or it ran too long: more than `--slowdown` (20) times the baseline's time, and at least `--timeout` (10) seconds. The report names the input it was on and the sanitizer's explanation. |
| 3 | `BUILD ERROR` | The candidate does not compile or link as part of json-c, or it `#include`s another `.c` file. json-c builds with `-Werror`, so new compiler warnings count too. |
| 4 | `CHECKER ERROR` | The checker could not run: a missing file, a malformed input file, missing tools, or a bug in the checker. Never a verdict on the candidate. |

Fixing one of the known json-c bugs (see `bughunt/README.md`) is a change in
behaviour, so it fails the check.

## What is compared

Each input is given to the tokener 29 ways (`record_input` in `recorder.c`):

- `oneshot`, `noterm` (no final NUL, so incomplete input answers "continue"),
  `minus1` (`len = -1`, as `json_tokener_parse()` uses) and `reuse` (one
  tokener for all inputs, `json_tokener_reset()` after each), each under 6 flag
  settings: `default`, `strict`, `utf8`, `strict+utf8`, `strict+trailing`,
  `strict+trailing+utf8`
- `parse` (`json_tokener_parse()`) and `verbose` (`json_tokener_parse_verbose()`)
- `depth1`, `depth5`, `depth64` (`json_tokener_new_ex()` with that depth)

For each, the recorder writes one answer:

- **type**: the type of every value in the result, and the exact value of every
  double (json-c prints a parsed double from its original text, so a wrong
  value would otherwise look right)
- **error**: the error code and its description
- **end**: how far into the input the parser read
- **value**: the parsed result, serialized

The candidate must give exactly the baseline's set of answers. Answers go to
their own file, and what the process prints to stdout is compared separately.

`inputs/core.txt` is the bug hunt's input set: 3,402 inputs (one of them the
empty line), so a full check is 98,658 answers. One input per line; `\xNN`
(exactly two hex digits) stands for the byte 0xNN, and a literal backslash
before `x` is written `\x5c`.

## How it works

1. **The baseline** is the git tree `6471b8b` (`json-c/` at `d2ce61e`), pinned
   in `check.py`, so moving the `baseline` tag cannot change it. Its
   `json_tokener.c` is read from git on every run, never from the cache.
2. **The rest of json-c** is built once with ASan/UBSan into a cache folder
   named after the baseline, compiler and flags; a file lock serializes that
   build. Both versions link against it with `--whole-archive`, as the real
   library build does, so they can only differ in the tokener.
3. **Both tokeners** are compiled with the exact command cmake uses, in a
   temporary folder outside the cache, then linked with `recorder.c`.
4. **The baseline runs first**; its time sets the candidate's time limit, and
   its binary is deleted before the candidate runs. Both run with fixed
   sanitizer settings, in their own process group, which is killed afterwards.
5. **`compare.py`** compares the answers and prints the report.

## Tests

```bash
python3 -m pytest oracle/tests     # about 90 seconds
```

- `tests/test_check.py` runs the whole checker on planted versions of
  `json_tokener.c`: unchanged; quietly fixing known bugs 1–4 (each must differ
  only where that bug shows); a wrong double value; mistakes in every entry
  point; crashes, hidden memory errors, leaks, endless loops and slowness;
  build errors, symbol clashes and an `#include` of the baseline; printing to
  stdout and faking the end of the run; a tampered cache; two first runs at
  once; and broken input files.
- `tests/test_compare.py` checks the comparison and the report on hand-written
  recorder output.

## Known gaps

Not checked yet, mostly left for later tasks:

- **Feeding input in pieces** (task 2) and **fuzzing** (task 3).
- **Deliberate tampering** (task 5). The candidate still runs with the user's
  permissions, so it could write to the cached headers and library, or to
  other files. It could also use sanitizer hooks (`__lsan_is_turned_off`),
  `no_sanitize` attributes, or detect the sanitizer build and behave
  differently there. The planned defences are running the candidate without
  write access, checking which symbols it defines and uses, and comparing a
  second build without sanitizers.
- **Other files in a rewrite PR.** The checker compiles the candidate against
  the baseline headers and ignores changes to any other file. CI must reject
  rewrite PRs that touch anything besides `json-c/json_tokener.c`.
- **Locale.** The recorder runs in the C locale, so a rewrite that drops
  json-c's switch to the C number format would only misbehave under a locale
  with a decimal comma (such as `de_DE`), which is not installed here.
- **Bugs 5–8** in `bughunt/README.md` and allocation-failure paths in general:
  an answer comparison cannot see out-of-memory handling, threads, or
  memory growth.
