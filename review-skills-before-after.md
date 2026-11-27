# Gate review: before and after the Trail of Bits skills

2026-11-24. Two review passes of the Role A gate (`oracle/check.py` and `ci/`, branch `a/ci`), done by Claude on the same day:

- **Pass 1, without testing skills.** The only skill used was `find-skills`, to search the registry. Method: read the code, run the gate and its self-tests, measure coverage, and hand-write 9 mistakes a refactor could make.
- **Pass 2, with skills.** Four Trail of Bits skills were installed from skills.sh: `mutation-testing`, `property-based-testing`, `fuzzing-obstacles` and `fuzzing-dictionary`. The tests were then redone following their methods.

This is not a controlled experiment. Pass 2 started from what pass 1 had found and took more time, so the "credit" column below is a judgement, not a measurement.

## Results at a glance

| | Pass 1 (no skills) | Pass 2 (with skills) |
|---|---|---|
| Mistakes run through the gate | 9, hand-written | 1,157 generated (every candidate, mewt-style operators), plus the 9 |
| Gate's kill rate | unknown; 0 of the 9 caught | **82.6%**: 876 of the 1,060 that compile (97 don't compile) |
| With the extended recorder prototype | proposed only | **86.1%** (37 more caught); **9 of 9** hand-written caught |
| Differential fuzzer (old vs new in one binary) | proposed only | built; baseline vs itself clean over ~26M runs; catches 3 of the 78 remaining survivors in executed code (60 s each) |
| Surviving mutants explained | no | all 147 sorted into out-of-memory paths, equivalent, not compiled here, and real gaps (below) |
| Kill rate, leaving out the 74 equivalent or not-compiled mutants | unknown | gate **88.8%** (876 of 986), then prototype 92.6% (913), then prototype + fuzzing **92.9%** (916 of 986) |
| New json-c bug | none | 1: a memory leak after finding 1's false success (below) |
| Ways to cheat the gate | sanitizer macros and hooks, hard-coded answers, no refactor at all | the same, plus the macro libFuzzer defines automatically |

## What each skill contributed

| Skill | What it said | What I did with it | Credit |
|---|---|---|---|
| `mutation-testing` | Measure the kill rate; use operator classes (error replacement, statement deletion, if-true/false, negation removal, operator swaps); check five things before calling a mutant "equivalent" (types, reachability, whether the value is used, semantics, try to build a distinguishing input). | Ran all 1,157 mutants against the real gate on 12 workers, then sorted the 184 survivors. | **High.** Turned 9 anecdotes into a measured rate with a per-operator breakdown. The equivalence checklist kept out-of-memory and `#if 0` survivors from being reported as gate gaps. Its tool `mewt` was not used: running the downloaded binary was blocked by a permission check, and `mewt` supports C++ but not C. So the help came from the method, not the tool. |
| `property-based-testing` | For a refactor, the strongest property is the oracle, new(x) == old(x). Pin known edge cases as fixed examples. Put constraints in the generator rather than filtering. Adding a library such as Hypothesis is the user's call. | Kept old-vs-new as the only verdict, including for chunked feeding. Added `multi.txt` (12 pinned multi-document inputs). Kept the prototype in C, with no new dependency. | **Low to medium.** It confirmed the design rather than changing it: the new calling modes had already come out of pass 1. |
| `fuzzing-obstacles` | Find what makes a target non-deterministic or blocks progress. libFuzzer defines `FUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION`. Check that the harness gives no false alarms. | Found json-c's only random input (the hash seed in `linkhash.c`); it doesn't change output, because objects keep insertion order. Ran the baseline against itself as the false-alarm check. | **Medium.** Two concrete gains: (1) a new cheat channel, because a candidate can `#ifdef` on that macro and behave correctly only under the fuzzer, so the cheat check must reject it; (2) the false-alarm run found that the baseline leaks inside a single input, which forced the stream modes to stop at an embedded NUL. |
| `fuzzing-dictionary` | 50–200 atomic tokens: delimiters, boundary values, hex escapes for binary bytes. | Grew `bughunt/json.dict` from 19 to 91 tokens (`jsonc.dict`). | **Low and unmeasured.** I didn't compare fuzzing with and without the dictionary, so I can't claim it helped. |
| `find-skills` | Search the skills.sh registry and check install counts and source. | Found the four skills above. There is no maintained skill for old-vs-new differential testing (the best match has 2 installs). | Discovery only. |

**What did not come from a skill:**
- The main diagnosis, that the gate only asks one call on a fresh tokener about a short input, came from pass 1.
- The new leak was found by running the pass-1 stream mode on the baseline, then shrinking the input automatically.

**Overall:** the skills mostly changed how much evidence there is (a measured kill rate instead of 9 examples), and they added two specific ideas: the fuzzer macro as a cheat channel, and a discipline for deciding whether a mutant is equivalent.

## Why the 9 planted mistakes were hard to detect

The gate asks one question: *what does a single call on a fresh tokener answer for a short input?* All 9 mistakes change something else. Line coverage gave no warning: the gate's run covers 92% of lines and 84% of branches of `json_tokener.c`, and 7 of the 9 mistakes sit on lines it runs thousands of times.

| # | Mistake | Line run by the gate? (gcov count) | Why the gate can't see it | Caught by |
|---|---|---|---|---|
| 1 | Success path skips resetting level 0 (`ii >= 0` became `ii > 0`) | yes (49,257) | The reset exists for the *next* call on the same tokener. The recorder always uses a fresh tokener or calls `json_tokener_reset()`, which hides the missing reset. | stream without reset (e.g. `1 2`) |
| 2 | String state drops the bytes read so far when a call ends mid-string | yes (2,331) | Runs when a call ends inside a string (`noterm` mode), but the lost bytes would only be used by a follow-up call, and the gate never makes one. | split / byte-by-byte feeding |
| 3 | Number sign flag wrong when resuming (`pos_sign_ok = 1`) | yes (163,929) | In one call the value is overwritten before it is read (a number never starts with `+`). It only matters when a number continues from a previous call, and that code (lines 958–971) never runs in the gate. | split / byte-by-byte feeding |
| 4 | `st_pos` (position inside `true`, `null`, `\uXXXX`) reset at every call | yes (every call) | A fresh tokener already has `st_pos = 0`, so the extra reset changes nothing within one call. | split / byte-by-byte feeding |
| 5 | `quote_char` kept in a `static` instead of the tokener | yes (159,175) | With one document in progress at a time, a `static` behaves exactly like a per-tokener field. The struct in `json_tokener.h` can't grow, so a refactor that needs new state is pushed towards `static`. | two tokeners interleaved |
| 6 | Trailing-character check rewritten as an XOR of two flags | yes (9,849) | XOR gives the same result on all 6 flag sets the recorder uses. It differs only for `ALLOW_TRAILING_CHARS` without `STRICT`, a flag set never used. The gap is in configurations, not in the JSON inputs. | all 8 flag sets |
| 7 | `len < -1` reports the wrong error code | **no** (line 351 never runs) | No input file can express it: the recorder only passes `len` = n, n+1 or −1. | API edge calls |
| 8 | `json_tokener_new_ex(0)` returns a tokener instead of NULL | **no** (branch never taken) | The recorder only creates tokeners with depth 1, 5, 64 or the default. | API edge calls |
| 9 | Quadratic work per string character | yes (every character) | Answers are identical; only time differs. The longest input is 1,000 bytes, so n² is about 10⁶ steps, far inside the limit (at least 10 s, or 20× the baseline). On a 200 KB string it takes 4.5 s against 0.00 s. | large-input file (times out at 171 s; baseline 8.5 s) |

**Three groups:**
- **State carried between calls** (1–5). The bug's effect only appears in a later call, on the same tokener or another one. These matter most for this project: splitting `json_tokener_parse_ex` into per-state functions means deciding, for every variable, whether it lives in a local, the tokener or somewhere else.
- **Calling patterns the input file can't express** (6–8). Flag sets and API arguments live in `recorder.c`, not in `oracle/inputs/`. Adding JSON inputs can never reach them.
- **Behaviour that isn't an answer** (9). Time, and similarly memory use, needs inputs chosen for size, not for variety.

## What still survives

The extended prototype leaves 147 of the 1,060 compiling mutants alive. Each was classified with the `mutation-testing` skill's checks: is the line reachable, is the changed value used, can an input tell the two apart. Where reasoning was not enough, I tried a distinguishing input. The 78 survivors in executed code were also fuzzed against the baseline for 60 s each.

| Group | Count | Gap? | Why |
|---|---|---|---|
| Out-of-memory branches | 64 | **Yes** | Reached only when an allocation fails. Allocation-failure injection (`bughunt/oom_inject.c`, compared old vs new) would cover them. Known bug 5 lives here. |
| Equivalent | 46 | No | Examples: the escape branch only ever sees `b n r t f`; the `\u` state resets `ucs_char`/`st_pos` itself; the strict leading-zero and exponent checks are backed by later checks (tested on `[1e]`, `[1e+]`, `{"a":1E-}`); buffer sizes; strings over 2 GB; the dead `>= 0x110000` branch; `obj` always NULL on error; the int64 vs uint64 subtype is not visible through the API tried. |
| Not compiled in this build | 11 | No (on glibc) | `#if 0`, the `setlocale` branch (only used without `uselocale`), Windows `DllMain`. |
| Comment text buffered and never read | 10 | No | As the bug hunt found (finding 7). |
| Exit-time cleanup of the C locale | 7 | No (on glibc) | glibc's C locale is a static object, so freeing it or not changes nothing. |
| `json_object_array_shrink` removed or changed | 4 | Memory only | Answers are identical; only memory use differs. |
| Caught by the differential fuzzer in 60 s | 3 | Caught | Inputs the fixed set lacks: `1NUL2` fed as a stream (the mutant reports the error at position 1 instead of 3); a strict fraction starting with `9`. |
| `uselocale(c_numeric_locale)` removed | 1 | **Yes** | Needs a run under a decimal-comma locale such as `de_DE`. Already in Known gaps in `oracle/README.md`. |
| `json_tokener_reset()` no longer clears the error | 1 | **Yes, small** | Visible only by calling `json_tokener_get_error()` right after a reset; add it to the API edge calls. |

So of the 986 mutants that can be caught at all, the gate catches 876, the prototype 913, and prototype plus fuzzing 916. The 70 left are 64 out-of-memory paths, 4 memory-only, 1 locale and 1 reset edge case. Two cheap additions would catch almost all of them: an allocation-failure run and a `de_DE` run.

## New json-c bug found on the way

`[[1/*` followed by `""""` on the same tokener, with no reset in between (allowed after a success), leaks a 57-byte string object. It is a consequence of bug-hunt finding 1: the false success leaves the tokener inside the outer array. It can also happen within one input, when an embedded NUL ends a comment inside a container and the caller keeps parsing.

What it means for the gate: the baseline itself fails LeakSanitizer in this pattern. So the stream mode must reset between inputs and stop at an embedded NUL, or the gate would reject every candidate, the baseline included.

## Files

The prototypes are in the session scratchpad, which is temporary. Copy them out if you want to keep them.
`/tmp/claude-1000/-home-lmz-software-testing-group27-jsonc/788fb306-f376-4a3f-b007-0f68a562a3a6/scratchpad/`:

- `mut/gen_mutants.py`, `mut/run_campaign.py`: mutant generator and parallel campaign runner; results in `mut/gate_results.json` and `mut/ext_results.json`
- `ext/recorder.c`, `ext/check_ext.py`, `ext/multi.txt`, `ext/big.txt`: the extended recorder prototype, run through the real `check.py`
- `fz/diff_fuzz.c`, `fz/build.sh`, `fz/jsonc.dict`, `fz/fuzz_all.sh`: the differential fuzzer and the per-mutant fuzzing run
- `plant.py`, `probe.c`, `probe_all.py`: the 9 hand-written mistakes and the program that confirms each changes behaviour
- `rl3.c`: reproducer for the leak above (`FL=0 ./rl3 '[[1/*' '""""'`)
