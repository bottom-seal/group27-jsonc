# oracle: the old-vs-new checker

Checks whether a rewritten `json_tokener.c` behaves exactly like the baseline
(json-c commit `d2ce61e`, tag `baseline`). It builds both versions, feeds them
the same inputs, and compares their answers.

## Running it

```bash
python3 oracle/check.py                     # checks json-c/json_tokener.c in the working tree
python3 oracle/check.py path/to/json_tokener.c
```

Needs `gcc`, `cmake`, `git` and Python 3. The first run builds json-c once into
`.build/oracle/` (about 10 seconds); later runs take a few seconds.

## Verdicts

| Exit code | Verdict | Meaning |
|---|---|---|
| 0 | `PASS` | Every answer matches the baseline. |
| 1 | `FAIL` | Some answers differ. The report lists the smallest differing inputs, with the baseline's answer next to the candidate's. |
| 2 | `CRASH` | The candidate crashed, hung (`--timeout`, default 300 s), leaked memory, or a sanitizer (ASan/UBSan) found a memory error, even if every answer was right. The report names the input it was on and the sanitizer's explanation. |
| 3 | `BUILD ERROR` | The candidate does not compile or link. json-c builds with `-Werror`, so new compiler warnings count too. |
| 4 | `CHECKER ERROR` | The checker itself could not run (for example, the baseline does not build). Not the candidate's fault. |

Fixing one of the known json-c bugs (see `bughunt/README.md`) is a change in
behaviour, so it fails the check.

## What is compared

For every input in `inputs/*.txt` and each of 6 flag settings (`default`,
`strict`, `utf8`, `strict+utf8`, `strict+trailing`, `strict+trailing+utf8`), the
recorder (`recorder.c`) records:

- **type**: the type of every value in the result, so an int that became a
  double is caught even when both print the same
- **error**: the error code and its description
- **end**: how far into the input the parser read
- **value**: the parsed result, serialized

Inputs are one per line; `\xNN` stands for the byte 0xNN. `inputs/core.txt` is
the bug hunt's input set (3,401 inputs).

## How it works

1. Extract json-c from the `baseline` tag and build it once with ASan/UBSan.
   The library without `json_tokener.c` is shared by both versions, so they can
   only differ in the tokener, and changes to other files are ignored.
2. Compile the baseline and the candidate `json_tokener.c` with the exact
   command cmake uses, link each with `recorder.c`.
3. Run both recorders on the inputs; the baseline's answers are produced fresh
   every run, never read from a file.
4. Compare (`compare.py`) and print the report.

## Tests

```bash
python3 -m pytest oracle/tests
```

- `tests/test_check.py` runs the whole checker on planted versions of
  `json_tokener.c`: unchanged, quietly fixing known bugs 1–4, crashing, not
  compiling, a hidden memory error, a leak, an endless loop, and an off-by-one
  in the nesting limit.
- `tests/test_compare.py` checks the comparison and report on hand-written
  recorder output.

## Not covered yet

- Feeding input in pieces (task 2) and fuzzing (task 3).
- Bugs 5–8 in `bughunt/README.md`: they need allocation failures, timing,
  memory measurement or threads, which an answer comparison cannot see.
