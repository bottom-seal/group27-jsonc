# fuzz: differential fuzzing of a rewrite

The gate (`oracle/`) compares a rewrite with the baseline on a fixed list of
inputs. The fuzzer looks for inputs nobody wrote: libFuzzer keeps generating
new ones, and each goes to the baseline and the rewrite in the same program.

```bash
python3 fuzz/fuzz.py                          # json-c/json_tokener.c, 5 minutes
python3 fuzz/fuzz.py path/to/json_tokener.c --seconds 600 --jobs 4
```

Needs `clang` with libFuzzer, `nm` and `objcopy`, plus what `oracle/check.py`
needs (it reuses its baseline build in `.build/oracle/`). The rest of json-c is
built for libFuzzer once into `.build/fuzz/`.

| Exit code | Meaning |
|---|---|
| 0 | nothing found in the time given |
| 1 | the rewrite answered differently, crashed, leaked or hung on some input |
| 3 | the rewrite does not build with clang |
| 4 | the script itself could not run |

## How it works

- `diff_fuzz.c` holds both versions: `fuzz.py` compiles the baseline tokener
  (read from the git tree `check.py` pins) and the rewrite separately and
  renames every global symbol of each to `old_*` and `new_*` with `objcopy`,
  so they can be linked into one program.
- Byte 0 of each generated input picks one of the 8 flag sets, byte 1 picks
  where to cut the text in two, and the rest is the text. Both versions parse
  it four ways: whole, cut in two, one byte per call, and as several
  documents on one tokener. Any difference in error, parse end, the type of
  every value, exact doubles or the value stops the run with both answers.
  ASan and UBSan stop it on memory errors and undefined behaviour.
- It starts from the gate's inputs (`oracle/inputs/*.txt`, under default and
  strict flags), the bug hunt's corpus (`bughunt/fuzz_corpus.tgz`, skipped
  with `--no-corpus`) and the inputs earlier runs kept in `.build/fuzz/corpus`.
  `json.dict` lists JSON tokens for libFuzzer to splice in.

## When it finds something

It prints both versions' answers and the input as a line for
`oracle/inputs/*.txt` (without bytes 0 and 1). Add that line to
`oracle/inputs/fuzz.txt`: from then on the gate checks it on every run, under
all its ways of calling, so the finding no longer depends on luck. The raw
input is kept in `.build/fuzz/findings/`.

The fuzzer is not a pass/fail check: a short run can miss what a long one
finds. Run against the baseline itself, an earlier version of this harness
found no difference in about 26 million inputs during the gate review.

## Tests

```bash
python3 -m pytest fuzz/tests     # about 40 seconds
```

The baseline against itself finds nothing; an object end accepted for `~` is
found and printed as an input line; a rewrite that does not compile is a build
error.
