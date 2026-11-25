# How does the gate judge a rewrite of json_tokener_parse_ex? {#gate-design}

A rewrite passes only if it gives the original's answers to about 1 million questions, asked in more than 30 ways, and does not cheat. Four iterations raised the share of planted mistakes it catches from **82–88% to 87–96%**.

- The path rules keep a rewrite PR to `json-c/json_tokener.c`, so `main`'s own checker judges it.[](source:paths)
- Before anything is built, the anti-cheat check rejects code that looks at its surroundings, switches checks off or carries test answers.[](source:cheats)
- The checker feeds the original and the rewrite 5,698 inputs in more than 30 ways and compares every answer.[](source:recorder)
- On rewrite PRs, a fuzzer also tries inputs nobody wrote; what it finds becomes a permanent input.[](source:fuzz)

@answer scope="Branch a/gate-iterations at 600453c (local; up to c6c6d9c pushed) · baseline json-c d2ce61e · numbers measured in the gate review, 24–25 Nov 2026"
@meta locale=en
@source paths title="Path rules" path=ci/check_paths.py lines=1:20
@source workflow title="CI workflow" path=.github/workflows/gate.yml lines=1:87
@source check title="Checker" path=oracle/check.py lines=1:24
@source cheats title="Anti-cheat check" path=oracle/cheats.py lines=1:30
@source recorder title="Recorder: every way of asking" path=oracle/recorder.c lines=555:600
@source compare title="Comparison and the failed-allocation rule" path=oracle/compare.py lines=115:135
@source fuzz title="Differential fuzzer" path=fuzz/fuzz.py lines=1:20
@source readme title="oracle/README.md: verdicts, inputs, known gaps" path=oracle/README.md lines=1:60

## How is a rewrite PR judged? {#judging}

@workflow id=pr-judging title="From rewrite PR to merge"
| role security | Rule check |
| role backend | Checker step |
| role external | Outcome |
| role frontend | Merge |
| lane ci | CI on the pull request |
| lane gate | Inside oracle/check.py |
| pr | Rewrite PR opened | external | ci |
| onlyfile | Only json_tokener.c? | security | ci |
| clean | Free of cheats? | security | gate |
| build | Build both versions | backend | gate |
| ask | Ask both 30+ ways | backend | gate |
| same | Same answers? | backend | gate |
| merge | Can merge | frontend | ci |
| blocked | Blocked | external | ci |
| pr > onlyfile | |
| onlyfile > clean | yes |
| onlyfile > blocked | no |
| clean > build | yes |
| clean > blocked | no |
| build > ask | |
| ask > same | |
| same > merge | yes | emphasis |
| same > blocked | no |

@steps id=judging-steps
| s1 | Only json_tokener.c? | The `paths` job runs `ci/check_paths.py`. A rewrite PR may change nothing but `json-c/json_tokener.c`, so it cannot weaken the tests or the checker that judge it. | pr-judging | onlyfile |
| s2 | Free of cheats? | `oracle/cheats.py` compares the rewrite with the original before building it. A cheat ends here as REJECTED (exit 5); the rewrite is never built or run. | pr-judging | clean |
| s3 | Build both versions | Both tokeners are compiled with cmake's exact command, with ASan and UBSan, and linked with the recorder and its allocation wrappers. | pr-judging | build |
| s4 | Ask both 30+ ways | The original runs first; its time sets the rewrite's limit, 20 times as long and at least 10 seconds. | pr-judging | ask |
| s5 | Same answers? | `oracle/compare.py` matches every answer exactly. A difference is FAIL (exit 1); a crash, leak, sanitizer report or timeout is CRASH (exit 2). | pr-judging | same |
| s6 | Can merge | Once branch protection is on, `paths` and `gate` must pass and a teammate must approve. It is not on yet. | pr-judging | merge |

A separate `fuzz` job fuzzes rewrite PRs for 5 minutes. It is not a required check, because a short run can miss things.[](source:workflow)

## What does the gate ask both versions? {#questions}

| Group | Ways of asking | Catches mistakes such as |
| --- | --- | --- |
| One call | Whole text, no end byte, length -1 and a reused tokener, each under all 8 flag sets; `json_tokener_parse`; `json_tokener_parse_verbose`; nesting limits 1, 5 and 64 | Wrong values, wrong errors, a limit off by one |
| Several calls | One byte per call; every cut in two (texts up to 64 bytes); several documents on one tokener; two tokeners fed in turns | A value forgotten between calls, state shared by all tokeners |
| Failures and settings | The k-th allocation fails (while parsing, in `parse_verbose`, while creating a tokener); a `de_DE` locale; stop, reset and parse again; two tokeners with different settings | Wrong out-of-memory handling, leaks, the wrong number format, settings kept in one place |
| Edge-case API calls | `len` of -2 and `INT_MIN`, `json_tokener_new_ex(0)`, error texts for -2 to 19, freeing and resetting NULL | Wrong answers to arguments no input file can express |

Every answer records the type of each value, the exact value of each double, the error and how far the parser read.[](source:recorder)

@facts
| Inputs | 5,698: `core.txt` 3,402, `neighbours.txt` 2,268, `multi.txt` 12, `large.txt` 9, `fuzz.txt` 7 |
| Answers per check | 1,051,570 (98,658 before iteration 1) |
| Time per check | About 25 seconds here, both versions built and run |
| Verdicts | 0 PASS, 1 FAIL, 2 CRASH, 3 BUILD ERROR, 4 CHECKER ERROR, 5 REJECTED |

@callout level=note title="One exception to exact matching"
| Answers given while an allocation fails on purpose are judged by what they say. A rewrite may allocate in another order, so its k-th allocation need not be the original's k-th. |
| It may give any answer the original gave for that input under some failed allocation, report out of memory, or give the normal answer. A crash or leak still fails. |

## How did the questions grow, iteration by iteration? {#iterations}

| Iteration (commit) | What it adds | Answers per check |
| --- | --- | --- |
| Before (`a/ci`) | 29 ways of asking, `core.txt` only | 98,658 |
| 1, the prototype (`d5483de`) | Several calls, all 8 flag sets, edge-case API calls, `multi.txt` | 510,387 |
| 2, v2 (`6b83848`) | Failed allocations while parsing, `de_DE`, after a reset, `large.txt`, the first fuzzer finds | 600,566 |
| 3, v3 (`f697874`) | Failures creating tokeners and in `parse_verbose`, two settings at once, 5 more fuzzer finds | 656,203 |
| 4, neighbours (`eb64d4e`) | 2,268 inputs with one character swapped for its neighbour | 1,051,570 |

The other commits on the branch support the iterations:

| Commit | Change |
| --- | --- |
| `595a2e5` | `metrics.py`: coverage, timing and lines no input runs, report only |
| `43a90e1`, `ee627ee` | CI stops running the gate's own tests; a `fuzz` job for rewrite PRs |
| `a06005a` | The differential fuzzer in `fuzz/` |
| `c6c6d9c` | Fix: the locale was not found with a relative `--build-dir` |
| `f6b5f24` | The failed-allocation rule, so a rewrite may allocate in another order |
| `600453c` | The anti-cheat check |

The tests went from 77 after iteration 1 to 113 now, plus 2 that need cmake. CI no longer runs them; run them before changing the gate.

## How much stronger did each iteration make it? {#strength}

```mermaid title="Share of planted mistakes caught (%), measured in the gate review with the scratch versions of each iteration"
xychart-beta
  x-axis ["Before", "It. 1", "It. 2", "It. 3", "It. 4"]
  y-axis "% caught" 80 --> 100
  line "Mull (565)" [88.1, 90.8, 95.2, 95.9, 96.1]
  line "My generator (1,060)" [82.6, 86.1, 92.2, 92.9, 93.1]
  line "Refactor-style (692)" [86.0, 88.4, 89.5, 89.7, 89.7]
  line "mewt (1,528)" [82.2, 84.9, 86.6, 87.4, 87.4]
```

- Iterations 1 and 2 did most of the work: new ways of asking, not more inputs. Iteration 4's 2,268 inputs caught only 3 more mutants.
- The 9 mistakes planted by hand: 0 caught before, all 9 from iteration 2 (iteration 1 misses the one that is only slow on large inputs).
- Mistakes that forget a value between calls: 0 of 9 caught before, 9 of 9 from iteration 1.
- Leaving out mutants shown to be harmless, the last stage catches 95–100%. 94 survivors are unproven: fuzzing found no difference, but nobody proved them harmless.

@callout level=warning title="What these numbers measured"
| The mutation runs used the scratch versions of each iteration. The committed iterations are clean rewrites of them and were not measured again. |
| The failed-allocation rule came after the measurement and may catch fewer allocation mistakes. Its tests show the planted ones are still caught. |

## How does the anti-cheat check work? {#anticheat}

It compares the rewrite with the original, so whatever the original does stays allowed. It reads three things: the list of functions the compiled code calls and defines (`nm`), the code after macros are expanded, and the raw text.[](source:cheats)

| Rule | Rejects | Only this rule catches |
| --- | --- | --- |
| R1 Calls | Functions a parser has no use for: the environment, files, the clock, printing, exiting, `__real_malloc` | 16 of 34 cheats |
| R2 Definitions | Names the C library or the sanitizers own, such as `malloc` and `__lsan_is_turned_off` | 4 |
| R3 Compiler tricks | `no_sanitize`, `constructor` and `optimize` attributes, inline assembly, pragmas | 5 |
| R4 Build detection | Tests on `__SANITIZE_ADDRESS__`, `FUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION`, `__OPTIMIZE__` | 4 |
| R5 Copied inputs | A new string of 4 or more characters that occurs in the gate's inputs | 1 |

@facts
| Cheats tried | 34 in 5 groups; 31 caught, only 1 by two rules |
| Honest refactors tried | 11, all pass: helpers, macros, extra `malloc`, `assert`, `snprintf`, lookup tables |
| Mutants from the review | 2,401 honest code changes, none rejected |

@callout level=open-question title="What it cannot see"
| A test answer spelled as characters, compared byte by byte, or matched by a hash of the input contains no string R5 can find. |
| The fuzzer is the defence: a rewrite that special-cases the gate's inputs is still wrong on new ones. |

## What does the fuzzer add? {#fuzzer}

@steps id=fuzzer-steps
| f1 | One program, two versions | `fuzz/fuzz.py` compiles the original and the rewrite separately and renames every global symbol of each, so both link into one program. |
| f2 | New inputs | libFuzzer keeps changing inputs, starting from the gate's inputs and the bug hunt's 27,000-input corpus. Byte 0 picks the flags, byte 1 the cut point. |
| f3 | Four ways each | Both versions parse each input whole, cut in two, byte by byte and as several documents. Any difference stops the run with both answers. |
| f4 | Finds become inputs | It prints the input as a line for `oracle/inputs/fuzz.txt`. From then on the gate checks it on every run. |

Run against the original itself, an earlier version of this harness found no difference in about 26 million inputs.[](source:fuzz)

## What is still open? {#open}

- [ ] Review the 11 commits on `a/gate-iterations`; the last 2 are not pushed yet.
- [ ] After the first PR run, check the `de_DE` locale step and the `fuzz` job, which have not run on GitHub yet.
- [ ] Add a second code owner to `.github/CODEOWNERS`, then run `ci/protect-main.sh`.
- [ ] Tell Role B the anti-cheat rules before the refactors start.
- [ ] Decide on rule 6 (existing functions outside `json_tokener_parse_ex` stay unchanged) and on extending R5.
- [ ] Ask the team to reword spec item ③: pieces must match the original fed the same pieces.
