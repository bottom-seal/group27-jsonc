# What did the json-c bug hunt find? {#bughunt}

The bug hunt found **8 new bugs** in json-c's tokener at commit `d2ce61e`, and **all 8 still reproduce** on the baseline today. They sit in less-used paths: comments, `VALIDATE_UTF8`, STRICT mode, input split across calls, out-of-memory handling and threads. The gate treats the baseline as the specification, so a refactor must keep every one of them.

- Findings 1, 2 and 4 give a wrong result, and 3, 3b and 5 report the wrong error. Findings 6, 7 and 8 are about time, memory and threads.[](source:findings)
- The search combined reference oracles, metamorphic relations, libFuzzer with sanitizers, fault injection and exhaustive boundary sets.
- It also re-found issues that were already open upstream (PRs #1006, #1007, #1014), which shows the harnesses work.[](source:rediscovered)
- Its mutation analysis showed which checks a Role A gate needs, and shaped `oracle/recorder.c`.[](source:mutation)

@answer scope="json-c master d2ce61e (2026-11-21) · findings from bughunt/README.md · reproducers re-run 2026-11-24 on ASan, -O2 and ThreadSanitizer builds of the baseline"
@meta locale=en
@source findings title="Bug hunt: findings 1–8" path=bughunt/README.md lines=5:79
@source observations title="Observations not claimed as bugs" path=bughunt/README.md lines=81:90
@source rediscovered title="Rediscovered upstream issues" path=bughunt/README.md lines=92:96
@source clean title="Clean results, rounds 1–7" path=bughunt/README.md lines=98:146
@source mutation title="Mutation analysis of the oracle" path=bughunt/README.md lines=131:137
@source round8 title="Round 8: variant analysis, spec vs code, literature review, coverage" path=bughunt/README.md lines=147:172
@source mut7b title="Raw mutation results, seed 7" path=bughunt/mutation/mut7b.txt lines=1:7
@source mut1b title="Raw mutation results, first run" path=bughunt/mutation/mut1b.txt lines=1:6
@source r1 title="Reproducer: finding 1" path=bughunt/repro_comment_eof.c lines=1:22
@source r2 title="Reproducer: finding 2" path=bughunt/repro_comment_stars.c lines=1:21
@source r3 title="Reproducer: finding 3" path=bughunt/repro_utf8_lookahead.c lines=1:27
@source r3b title="Reproducer: finding 3b" path=bughunt/repro_utf8_relabel.c lines=1:31
@source r4 title="Reproducer: finding 4" path=bughunt/repro_strict_single_quote_key.c lines=1:20
@source r5 title="Reproducer: finding 5" path=bughunt/repro_oom_eof.c lines=1:33
@source r6 title="Reproducer: finding 6" path=bughunt/repro_quadratic_number.c lines=1:36
@source r7 title="Reproducer: finding 7" path=bughunt/repro_comment_memory.c lines=1:15
@source r8 title="Reproducer: finding 8" path=bughunt/repro_tsan_locale_race.c lines=1:29

## What are the 8 findings? {#findings}

Each row shows the reproducer's input and what the baseline did when re-run on 2026-11-24.

| Finding | Input and what json-c does | What it should do |
| --- | --- | --- |
| 1. Open comment at the end of a container | `[1,2/*` returns success with the value `2` | Fail with "unexpected end of data", as `[1,2` does[](source:r1) |
| 2. Even run of stars before `/` | `/** doc **/ 1` fails; `[1 /***/ ]` returns `1` | Parse both; the second is `[1]`[](source:r2) |
| 3. UTF-8 character after a value | `{"a":1}é` with STRICT, `ALLOW_TRAILING_CHARS` and `VALIDATE_UTF8` fails with "invalid utf-8 string" | Succeed, as `{"a":1}x` does[](source:r3) |
| 3b. Syntax error on a UTF-8 character | `[é]` with `VALIDATE_UTF8` says "invalid utf-8 string" | Say "unexpected character", as without the flag[](source:r3b) |
| 4. Single-quoted key in STRICT mode | `{'a':1}` returns `{"a":1}` | Reject it, as `['a']` is rejected[](source:r4) |
| 5. Out of memory on a top-level value | `true` or `-12` with a failed allocation says "unexpected end of data" | Say "out of memory", as `[true]` does[](source:r5) |
| 6. Long number fed in small pieces | 640,000 digits in 1-byte calls take 3.58 s; a string of the same length takes 0.01 s | Take linear time[](source:r6) |
| 7. Long comment fed in pieces | 100 MB of comment in 64 KiB calls peaks at 101 MB of memory; whitespace peaks at 1.7 MB | Use constant memory[](source:r7) |
| 8. First calls from two threads | ThreadSanitizer reports a data race on the cached C locale (lines 357 and 359), 5 of 5 runs | No race[](source:r8) |

```mermaid title="Finding 6: time to feed a number or a string one byte per call (measured 2026-11-24, -O2 build)"
xychart-beta
  x-axis "length (bytes)" ["160,000", "320,000", "640,000"]
  y-axis "seconds" 0 --> 4
  line "Number" [0.221, 0.881, 3.583]
  line "String" [0.003, 0.005, 0.010]
```

Doubling the number's length multiplies the time by about 4: 0.221 → 0.881 → 3.583 s. That is quadratic growth, while the string stays linear.

## Why does each bug happen? {#causes}

| Finding | Cause in `json_tokener_parse_ex` | Found by |
| --- | --- | --- |
| 1 | The comment states jump to `out:` at the end of input. The end-of-input check passes because `saved_state` is still `finish` from the inner value. | Stream oracle: two documents on one tokener |
| 2 | `comment_end` sends any byte other than `/`, including a second `*`, back to `comment`, which then skips one byte | Inserting a comment between tokens must not change the result |
| 3, 3b | `PEEK_CHAR` validates the byte after a value without consuming it. `out:` turns the pending multi-byte count into a UTF-8 error. | Reading the validator; a BOM test from the literature review |
| 4 | The STRICT check for `'` was added to `start` in 2013 but not to `object_field_start` | STRICT json-c against Python's `json` on JSONTestSuite |
| 5 | A top-level value is built only when the NUL arrives, and the end-of-input check at `out:` overwrites the memory error | Failing the Nth allocation for every N |
| 6 | On every resume, `number` searches all saved digits for `e` and `E` with `strchr` | Timing one-shot against 1-byte feeding per token type |
| 7 | The comment states append every comment byte to `pb`, which only debug output reads | Mutation analysis: removing those appends changes no result |
| 8 | `c_numeric_locale` is created on first use without a lock (commit `fd92d58`, after release 0.19) | ThreadSanitizer with two concurrent first calls |

Finding 1 has a second effect, found during the gate review on 2026-11-24 and not yet in the bug hunt notes. If the caller keeps parsing on the same tokener after the false success, `[[1/*` followed by `""""` leaks a 57-byte string.

## How was the tokener searched? {#methods}

@workflow id=hunt-flow title="How the bug hunt searched json_tokener_parse_ex"
| lane gen | Inputs |
| lane check | Checks |
| lane triage | Triage |
| inputs | Inputs and corpora | external | gen |
| oracles | Compare with references | backend | check |
| relations | Metamorphic relations | backend | check |
| fuzz | Fuzz with sanitizers | backend | check |
| faults | Faults, time, threads | backend | check |
| repro | Minimal reproducer | backend | triage |
| upstream | Search upstream | external | triage |
| fix | Fix locally, rerun | backend | triage |
| inputs > oracles | |
| inputs > relations | |
| inputs > fuzz | |
| inputs > faults | |
| oracles > repro | |
| relations > repro | |
| fuzz > repro | |
| faults > repro | |
| repro > upstream | |
| upstream > fix | new | emphasis |

@steps id=hunt-steps
| h-inputs | Inputs and corpora | A grammar-based generator, fuzz corpora, JSONTestSuite and exhaustive sets: 2.37M UTF-8 sequences and 147,620 short number strings. | hunt-flow | inputs |
| h-oracles | Compare with references | STRICT json-c against Python's `json` (120k inputs), lenient json-c against a Python model of its grammar (200k), and 0.18 / 0.19 / master against each other (111k). Found finding 4. | hunt-flow | oracles |
| h-relations | Metamorphic relations | Rules that must hold without knowing the answer: split input equals one-shot input; an inserted comment changes nothing; wrapping `x` as `[x]` keeps its value; stricter flags never accept more; equal escapes give equal strings. Found findings 1 and 2. | hunt-flow | relations |
| h-fuzz | Fuzz with sanitizers | Four libFuzzer targets, each also checking a relation, under ASan and UBSan: for example about 46 million runs of the `len = -1` target in 10 minutes. Plus MemorySanitizer, a 32-bit build and unsigned `char`. No crash. | hunt-flow | fuzz |
| h-faults | Faults, time, threads | Failing every allocation in turn (finding 5), timing per token type (finding 6), measuring memory (finding 7) and ThreadSanitizer (finding 8). | hunt-flow | faults |
| h-repro | Minimal reproducer | Each finding got a small `repro_*.c` file in `bughunt/`. | hunt-flow | repro |
| h-upstream | Search upstream | Searched json-c issues and pull requests on 2026-11-21 and 2026-11-22: none of the 8 findings was reported. | hunt-flow | upstream |
| h-fix | Fix locally, rerun | `local_fixes_findings_1-5.patch` fixes findings 1–5. With it, json-c's own tests give the same result as master, and every harness runs clean. | hunt-flow | fix |

## What else did it turn up? {#others}

These were noted but not claimed as bugs, because the right behaviour is a judgement call or already known.[](source:observations)

| Kind | What was seen |
| --- | --- |
| Already open upstream | A UTF-8 character split across calls fails with `VALIDATE_UTF8` (PR #1014). A number split across calls loses or replaces parts: `[12` + `-3]` gives `[12]` (PR #1006). A key with `\u0000` is cut short (PR #1007). |
| Design limit | STRICT rejects `1 2` in one call but returns `1` when the input is split after the space |
| Observation | Lone surrogate escapes all become U+FFFD, so distinct keys collide and members are silently dropped |
| Observation | A top-level STRICT `01`, `1.` or `1e` says "unexpected end of data" instead of "number expected" |
| Observation | The header's `json_tokener_parse_ex` example checks trailing characters in a way that reports them for every input |
| Observation | `null` returns NULL with success, although the header says a valid value always gives an object |

The re-found upstream issues matter: the harnesses discovered them on their own, so they can find real bugs.[](source:rediscovered)

## What came back clean? {#clean}

| Check | Size | Result |
| --- | --- | --- |
| Split-input relation, every 2-way split and byte by byte | 100k inputs × 5 flag sets | 0 mismatches with PRs #1006 and #1014 applied |
| Exhaustive UTF-8 boundary set against Python's decoder | 2.37M sequences | 0 mismatches |
| Escape equivalence | 3.0M checks | Only the known split-UTF-8 issue |
| Flag monotonicity | 38,835 files | 0 violations |
| Reading past the end of exact-size, unterminated input | 1.18M calls under ASan | Clean |
| MemorySanitizer and a 32-bit build | All corpora | Clean |
| Line and branch coverage of `json_tokener.c` | 7 feeding modes × 6 flag sets | 90.8% lines, 85.1% branches; the rest is mostly out-of-memory code |

"Clean" means these checks found nothing new beyond the 8 findings, not that the tokener has no other bugs.[](source:clean)

## How strong would a gate built from these harnesses be? {#mutation}

```mermaid title="250 single-point mutants of the tokener, seed 7 (from mut7b.txt)"
pie
  "Killed: one-shot and split" : 199
  "Killed: one-shot only" : 12
  "Killed: split input only" : 4
  "Killed: timeout" : 7
  "Killed: crash" : 4
  "Survived" : 22
  "Did not compile" : 2
```

226 of the 248 compiling mutants were killed (91.1%). An earlier run killed 130 of 150 (86.7%).[](source:mut7b)[](source:mut1b) The README's "89%" matches both runs combined: 356 of 398 = 89.4%.

| Lesson from the survivors | Where it went |
| --- | --- |
| Compare the type of every value, not just its text | The recorder's type signature, including exact doubles |
| Include a mode where one tokener reads several inputs | The recorder's `reuse` mode |
| Add boundary inputs for every range check | `oracle/inputs/core.txt` is this input set, boundary inputs included |
| 4 mutants die only when input is split | Not yet in the gate; the 2026-11-24 review measured the gap |

## What happens to these bugs now? {#next}

@callout level=note title="Keep, then report"
For the refactoring experiment the 8 findings are part of the specification. Fixing one is a change in behaviour, and the gate's own tests plant fixes for findings 1–4 to prove it notices.
Reporting them upstream with the reproducers and the local patch is planned for week 15, as Role C's work.

- [ ] Record the new leak (`[[1/*` then `""""`) with the upstream report. `bughunt/` is read-only under the CI path rules, so it cannot go into its README.
- [ ] Re-run all reproducers on the baseline before the upstream report; on 2026-11-24 all 8 still reproduce.
- [ ] Note that ThreadSanitizer needs `setarch -R` on this kernel, or it stops with "unexpected memory mapping".
- [ ] When quoting the mutation result, use 91.1% for the seed-7 run or 89.4% for both runs, not the README's bare "89%".
