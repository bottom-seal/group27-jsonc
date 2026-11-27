# Group 27: a verification gate for AI refactoring of json-c

json-c is a C library that reads JSON text. Its reader, `json_tokener_parse_ex`
in `json-c/json_tokener.c`, is a single function of about 1,100 lines. In this project an
AI (and, for comparison, a person) splits it into smaller functions, and an
automatic **gate** decides whether each rewrite still behaves exactly like the
original. The aim is a gate the AI cannot switch off or fake; what it does not
catch yet is listed in `oracle/README.md`.

## Layout

| Path | What it is | Who changes it |
|---|---|---|
| `json-c/` | json-c at commit `d2ce61e`, tagged `baseline` | Only rewrite PRs, and only `json-c/json_tokener.c` |
| `oracle/` | The gate's checks: old-vs-new comparison, including text fed in pieces, allocation failures and a decimal-comma locale | Role A |
| `fuzz/` | Differential fuzzer: the baseline and a rewrite in one program, fed generated inputs. See `fuzz/README.md` | Role A |
| `bughunt/` | Earlier bug hunt: 8 json-c bugs, reproducers and harnesses. Reference only | Nobody |
| `ci/`, `.github/` | The checks every pull request must pass, path rules, code owners. See `ci/README.md` | Role A |

## Baseline

The reference version is json-c commit
[`d2ce61e`](https://github.com/json-c/json-c/commit/d2ce61eb214e) (2026-11-21),
tagged `baseline` in this repo. A rewrite passes when it gives the same answers
as this version on every input, including the known bugs listed in
`bughunt/README.md`. Fixing a bug counts as a change in behaviour.

## Running the gate and its tests

Scripts that judge a rewrite (each defaults to `json-c/json_tokener.c`):

| Script | What it does | Command | Time |
|---|---|---|---|
| `oracle/check.py` | The gate: PASS, FAIL, CRASH, BUILD ERROR, CHECKER ERROR or REJECTED (see `oracle/README.md`) | `python3 oracle/check.py [path/to/json_tokener.c]` | about 25 s |
| `oracle/metrics.py` | Report only: coverage, time against the baseline, lines no input runs | `python3 oracle/metrics.py [path/to/json_tokener.c]` | about 1 min |
| `fuzz/fuzz.py` | Differential fuzzer: generated inputs against the baseline (see `fuzz/README.md`) | `python3 fuzz/fuzz.py [path/to/json_tokener.c] --seconds 300` | as long as set |
| `ci/check_paths.py` | The path rules CI applies to a pull request | `python3 ci/check_paths.py origin/main HEAD` | seconds |

`ci/protect-main.sh` is not a test: it changes the repository's settings on
GitHub (see `ci/README.md`).

Tests of the gate itself:

| Suite | Tests | What they check |
|---|---|---|
| `oracle/tests/test_check.py` | 77 | Planted mistakes for each iteration fail; cheats are rejected; crashes, leaks, timeouts, build errors, cache tampering, bad input files |
| `oracle/tests/test_compare.py` | 21 | The comparison and the report, on hand-written answers |
| `oracle/tests/test_metrics.py` | 5 | `metrics.py` |
| `ci/tests/test_check_paths.py` | 9 | The path rules |
| `fuzz/tests/test_fuzz.py` | 3 | The fuzzer |

```bash
python3 -m pytest oracle/tests ci/tests fuzz/tests       # all 115, about 9 minutes
python3 -m pytest oracle/tests/test_compare.py           # under a second
python3 -m pytest oracle/tests/test_check.py -k cheats   # only the anti-cheat tests
```

CI does not run these tests (it runs `paths`, `gate` and `fuzz`), so run them
before changing anything under `oracle/`, `ci/` or `fuzz/`.

Needed: `gcc`, `cmake`, `git` with the full history, Python 3 with `pytest`,
glibc's `localedef` with the `de_DE` locale sources (Ubuntu/Debian: the
`locales` package), and for the fuzzer `clang` with libFuzzer, `nm` and
`objcopy`. cmake is needed when json-c is first built into `.build/oracle/`,
and by two tests (`test_a_tampered_cache_does_not_change_the_baseline`,
`test_two_first_runs_at_once_both_work`) that build it again.

## Working on this repo

- `main` holds the agreed starting point. Nobody commits to it directly.
- Each piece of work goes on its own branch, named `<role>/<topic>`
  (for example `a/oracle`, `b/agent-state-string`), and is merged by pull request.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`.
