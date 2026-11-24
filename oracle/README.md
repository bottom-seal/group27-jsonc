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

Each input is given to the tokener in these ways (`record_input` in
`recorder.c`).

**One call:**

- `oneshot`, `noterm` (no final NUL, so incomplete input answers "continue"),
  `minus1` (`len = -1`, as `json_tokener_parse()` uses) and `reuse` (one
  tokener for all inputs, `json_tokener_reset()` after each), each under all 8
  combinations of `STRICT`, `VALIDATE_UTF8` and `ALLOW_TRAILING_CHARS`:
  `default`, `strict`, `utf8`, `strict+utf8`, `strict+trailing`,
  `strict+trailing+utf8`, `trailing`, `trailing+utf8`
- `parse` (`json_tokener_parse()`) and `verbose` (`json_tokener_parse_verbose()`)
- `depth1`, `depth5`, `depth64` (`json_tokener_new_ex()` with that depth)

**More than one call:**

- `bytewise`: one byte per call, under all 8 flag settings, and
  `bytewise-depth5` with nesting limit 5. Texts over 4,096 bytes go in
  4,096-byte pieces.
- `split<k>`: texts up to 64 bytes cut in two after byte k, for every k, under
  `default`, `strict` and `utf8`.
- `stream<d>`: one tokener per flag setting reads document after document from
  the same text, without a reset in between (up to 8). It is reset before each
  input and stops at an embedded NUL byte: past either point the baseline
  itself leaks after bug-hunt finding 1.
- `turns-with-previous` and `turns-with-next`: this input and the previous one
  on two tokeners, fed one byte at a time in turns, under `default`, `strict`
  and `utf8`. Each answer is filed under the input it is about. (The recorder
  writes `#input N` before each input, so a crash is still reported on the
  input it was working on.)
- Every multi-call way also records how many calls it took (`bytewise-calls`,
  `split<k>-calls`).

Text in pieces is compared with the baseline fed the same pieces, never with
the one-call answer: the baseline itself answers differently in pieces in a
few known cases (`[12-3]`, a UTF-8 character split across calls, `1 2` under
`STRICT`; see `bughunt/README.md`), and a rewrite must keep those.

**Edge-case API calls, once** (`record_api`): `len` = -2 and `INT_MIN`,
`json_tokener_new_ex(0)` and `(-1)`, `json_tokener_error_desc()` for -2 to 19,
and `json_tokener_free(NULL)` / `json_tokener_reset(NULL)`. They are filed one
past the last input, and the report calls them "the edge-case API calls".

For each, the recorder writes one answer:

- **type**: the type of every value in the result, and the exact value of every
  double (json-c prints a parsed double from its original text, so a wrong
  value would otherwise look right)
- **error**: the error code and its description
- **end**: how far into the input the parser read
- **value**: the parsed result, serialized

The candidate must give exactly the baseline's set of answers. Answers go to
their own file, and what the process prints to stdout is compared separately.

Inputs, one per line: `inputs/core.txt` is the bug hunt's input set (3,402
inputs, one of them the empty line), and `inputs/multi.txt` holds 12 texts with
several documents each, for `stream`. A full check is 510,387 answers. `\xNN`
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

## Metrics (report only)

```bash
python3 oracle/metrics.py                          # the working tree's json_tokener.c
python3 oracle/metrics.py path/to/json_tokener.c --json metrics.json
```

`metrics.py` makes the same comparison as `check.py` and prints its verdict
line, then numbers about what the gate's inputs exercise. They never change the
verdict: the exit code is 0 whenever the report is written (3 if the candidate
does not build, 4 if the script cannot run). A run takes a few seconds.

- **Time**: best of `--repeat` (3) runs of the gate's own build, for the
  baseline and the candidate, and the ratio. The gate fails a candidate only
  above 20 times the baseline's time.
- **Coverage**: lines and branches of `json_tokener.c` that the inputs run, for
  both versions and per function, from a second build with gcov (the tokener
  at `-O0` without sanitizers, so the counts follow the source).
- **Unrun lines** of the candidate, matched to the baseline's lines (ignoring
  indentation) and split three ways:
  - *unrun in the baseline too*: mostly out-of-memory handling;
  - *ran in the baseline, not here*: the inputs no longer reach code they
    reached before;
  - *new or changed code*: no input runs it, so the gate says nothing about it.
    A special case hidden in a rewrite shows up here.
- **States**: how often the inputs enter each state of `json_tokener_parse_ex`,
  for a source that keeps the `case json_tokener_state_...:` labels.
- **Answers**: which error codes the baseline's answers contain, and which never
  appear.
- **Inputs**: how many, the longest, how many are over 1,000 bytes.

Coverage shows which code the inputs reach, not how well the answers there are
checked: code can run on every input and still be wrong in a way no input
shows. Needs gcc's `gcov` (set `GCOV` to use another).

## Tests

```bash
python3 -m pytest oracle/tests     # about 2 minutes
```

- `tests/test_check.py` runs the whole checker on planted versions of
  `json_tokener.c`: unchanged; quietly fixing known bugs 1–4 (each must differ
  only where that bug shows); a wrong double value; mistakes in every entry
  point; crashes, hidden memory errors, leaks, endless loops and slowness;
  build errors, symbol clashes and an `#include` of the baseline; printing to
  stdout and faking the end of the run; a tampered cache; two first runs at
  once; and broken input files.
- It also plants mistakes that only show across calls or through the API: state
  not reset or not kept between calls, values shared by all tokeners, the
  trailing-characters check rewritten for the flag sets without `STRICT`, and
  wrong answers for `len < -1` and `json_tokener_new_ex(0)`.
- `tests/test_compare.py` checks the comparison and the report on hand-written
  recorder output.
- `tests/test_metrics.py` runs `metrics.py` on planted versions: unchanged (the
  same numbers as the baseline); a special case no input reaches (listed as new
  code the gate never runs, though the verdict is PASS); a change that stops
  the inputs reaching some states; a crash; and a build error.

## Known gaps

Not checked yet, mostly left for later tasks:

- **Fuzzing** (task 3).
- **Large inputs.** The longest input is 1,000 bytes, so code that only gets
  slow on long texts (quadratic in the length, say) passes the time limit.
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
