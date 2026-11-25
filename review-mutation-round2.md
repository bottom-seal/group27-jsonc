# Gate review, round 2: more mutation testing

2026-11-24 to 25. A second round of mutation testing on the Role A gate (`oracle/check.py`, branch `a/ci`), following `review-skills-before-after.md`. Everything was built and run in the session scratchpad; nothing in `oracle/`, `ci/` or `json-c/` was changed. "Current gate" means `oracle/check.py` with `oracle/recorder.c` and `oracle/inputs/core.txt` as they are on `a/ci`.

## What was run

Four sets of mutants of `json-c/json_tokener.c`, each a copy of the file with one deliberate change:

- **My generator** (from round 1): 1,157 mutants with mewt-style operators.
- **mewt 4.0.0** (Trail of Bits): 1,907 mutants.
- **Mull 0.39.1** (LLVM-based, made for C/C++): 565 mutants.
- **Refactor-style** (new this round): 692 mutants that imitate mistakes a rewrite of the state machine could make. Each one does one of these:
  - jumps to the wrong next state
  - forgets a value between calls
  - makes a per-reader field global
  - swaps two neighbouring statements
  - combines two earlier mutants

Each mutant went through these stages. Each stage ran only on what the stage before it left alive.

| Stage | What it adds | Answers compared per run |
|---|---|---|
| Current gate | 29 ways of calling × 3,402 inputs | 98,658 |
| Prototype (round 1) | Text fed in pieces; several documents on one reader; two readers taking turns; all 8 flag sets; edge-case API calls; 12 multi-document inputs | 343,303 |
| v2 | Failing memory requests on purpose while parsing; a decimal-comma locale (`de_DE`); checks that a reset clears everything; large inputs; 3 inputs found by the fuzzer | 433,179 |
| v3 | Failing memory requests while creating a reader and inside `json_tokener_parse_verbose`; two readers with different settings alive at once; 5 more fuzzer-found inputs | 488,625 |
| v3 + neighbours | 2,268 inputs made by replacing each structural character in short documents with the character just below or above it | 779,514 |

The original passes every stage against itself.

## Results at a glance

Share of mutants caught. Mutants that don't compile are left out.

| Mutants | Judged | Current gate | Prototype | v2 | v3 | v3 + neighbours |
|---|---|---|---|---|---|---|
| My generator | 1,060 | 82.6% | 86.1% | 92.2% | 92.9% | **93.1%** |
| mewt | 1,528 | 82.2% | 84.9% | 86.6% | 87.4% | **87.4%** |
| Mull | 565 | 88.1% | 90.8% | 95.2% | 95.9% | **96.1%** |
| Refactor-style | 692 | 86.0% | 88.4% | 89.5% | 89.7% | **89.7%** |
| The 9 hand-planted mistakes | 9 | 0 of 9 | 9 of 9 | 9 of 9 | 9 of 9 | 9 of 9 |

Most survivors at the end can be shown to be harmless, or can't be tested on this machine (see "What still survives"). With those left out, v3 + neighbours catches:

| Mutants | Caught |
|---|---|
| My generator | 98.0% |
| mewt | 95.3% |
| Mull | 98.5% |
| Refactor-style | 100% |

These figures count the 94 unproven survivors as catchable. If some of those are also harmless, the true rates are higher.

## What each addition caught

| Addition | Stage | Newly caught | Example |
|---|---|---|---|
| Pieces, streams, turns, all flag sets, edge-case API calls | Prototype | 37 / 42 / 15 / 17 (my generator / mewt / Mull / refactor-style) | All 9 planted mistakes. All 9 refactor-style "value forgotten between calls" mutants. |
| Failing memory requests while parsing | v2 | About 100 | `tok->err = json_tokener_error_memory` removed or changed; missing NULL checks; leaks on the failure path |
| German locale | v2 | 11 | The switch to the C number format inside the call removed or broken (lines 357 and 366). 195 answers differ. |
| Checks after a reset | v2 | 2 | `json_tokener_reset()` no longer clears the error |
| Large inputs and the first 3 fuzzer inputs | v2 | 10 | A STRICT fraction starting with 9 (`.9`); `1NUL2` as a stream |
| Failing memory requests while creating a reader or in `parse_verbose` | v3 | 20 | No NULL check after `calloc` in `json_tokener_new_ex` (crash); `free(tok)` missing on the failure path (leak) |
| Two readers with different settings alive at once | v3 | 1 | `max_depth` made global: the depth-5 reader takes the depth-64 limit and writes past its 5-level stack |
| 5 more fuzzer inputs | v3 | 5 | `c == '}'` became `c >= '}'`: revealed by `~` or DEL right after a value in an object |
| Neighbour inputs | v3 + neighbours | 3 | A resumed number wrongly accepts a sign (line 971) |

The big gains come from new **ways of calling** (pieces, streams, memory failure), not from more inputs. 2,268 neighbour inputs caught only 3 more mutants.

## The fuzzer as a source of inputs

All 137 survivors that reasoning couldn't settle were fuzzed for 60 s each against the original (12 at a time, 12 minutes in all). Five showed a difference:

| Mutant | Change | Input that revealed it |
|---|---|---|
| mewt, line 1260 | `c == '}'` → `c >= '}'` after `{` | `{` followed by DEL (0x7f), UTF-8 checking on |
| mewt, line 1367 | `c == '}'` → `c >= '}'` after an object value | `{"":{"":{"":{}}}~s` |
| mewt, line 554 | a `==` in the `null` check → `<=` | `2nux` as a second document |
| mewt, line 1490 | `>` → `!=` in UTF-8 validation | `1"` followed by bytes F4 89 |
| refactor-style, line 1249 | wrong next state after `,` in an array | `1.5[2⇥,2⇥,⇥⇥],[1]` as several documents |

I had guessed the last one was harmless; the fuzzer proved otherwise. Most of these inputs put a character just above or below one the parser compares against. That is why the neighbour inputs were tried next.

## Mull, mewt and my generator compared

| | My generator | mewt 4.0.0 | Mull 0.39.1 |
|---|---|---|---|
| How it changes the code | Regular expressions on the source | Syntax tree, with its C++ grammar | Inside the compiler (LLVM), mapped back to source lines |
| Mutants made | 1,157 | 1,907 | 565 |
| Don't compile | 97 (8.4%) | 379 (19.9%, after translating its C++ edits to C) | 0 |
| Current gate catches | 82.6% | 82.2% | 88.1% |
| After v3 + neighbours | 93.1% | 87.4% | 96.1% |
| Source lines with a survivor at the gate | 112 | 146 | 56 (only 1 not shared with the others, and that one is harmless) |
| Gate run | About 7 min, 12 workers | About 12.5 min on 10 workspace copies, plus 4 min retest | 5¾ min, 12 workers |
| Friction | None | No C support: needed a `.cpp` copy, a C translation wrapper, and 10 copies for parallelism | No sudo, so the `.deb` was unpacked by hand. Builds every mutant into one 118 MB program; that build ran the prototype at 46 s per check. 29 of its patch files left a stray statement and needed fixing to compile as source. |

Mull's mutants are cleaner (all compile, none on `#if` lines), so the gate scores highest on them. Its survivors add almost nothing the other two missed. mewt makes the most mutants and the most harmless survivors.

For Role C's official mutation score, mewt or Mull are the credible choices. For finding gate gaps, the refactor-style mutants told us the most.

## Refactor-style mutants

| Kind | Made | Current gate | Prototype | v2 | Final |
|---|---|---|---|---|---|
| Wrong next state | 291 | 99% | 99% | 100%* | 100% |
| **Value forgotten between calls** | 9 | **0%** | 100% | 100% | 100% |
| **Field made global, shared by all readers** | 7 | **14%** | 86% | 86% | **100%** (v3) |
| Two neighbouring statements swapped | 85 | 15% | 15% | 16% | 16% |
| Two earlier mutants at once | 300 | 97% | 98% | 100% | 100% |

\* The last one, at line 1249, was caught by a fuzzer input in v3.

- **The current gate catches none of the "forgotten between calls" mistakes.** These are the internal-state bugs most likely when `json_tokener_parse_ex` is split into per-state functions. Byte-by-byte feeding catches all of them.
- **Making `max_depth` global survived everything until v3.** No earlier stage had two readers with different nesting limits alive at the same time.
- **The 71 surviving swaps can't change behaviour.** A script and a read-through confirmed that in 70 of them, neither statement touches what the other reads or writes. The remaining one, line 1411 (`setlocale` / `free(oldlocale)`), would be a use-after-free, but that code is only compiled on systems without `uselocale`, so this machine can't test it.

## Internal state: stopping and resuming the reader

The gate compares only what the public functions return, never the stack or other internal fields. That is deliberate: a refactor is expected to change how state is stored. Internal state matters when a later call uses it, so it was measured by where the reader is stopped mid-text over `core.txt` (flags none, strict and utf8):

| | Current gate | Byte by byte (prototype) |
|---|---|---|
| States the reader is stopped in | 14 of 27 | 15 of 27 |
| Times it is stopped | About 1,700, once per text, at the very end | About 210,000 |
| Resumed afterwards? | **Never.** No second call follows. | Every time |
| (state, saved_state) combinations reached | not measured | 52 |

The other 12 states are pass-through states. When the text runs out there, the reader parks in `eatws` and records the next state in `saved_state`.

## What still survives (358)

| Group | Count | Harmless? |
|---|---|---|
| Fuzzed for 60 s and tested with the neighbour inputs, no difference found | 94 | **Unproven.** Some were argued harmless in round 1 (the STRICT leading-zero and exponent checks are backed by later checks; the int64 vs uint64 subtype isn't visible through the API; the `\u` state resets its own counters). |
| Swapped statements that don't touch each other | 70 | Yes |
| Code not compiled here (`#if`) | 49 | Untestable here |
| Exit-time cleanup of the C locale | 17 | Yes on glibc (its C locale is a static object) |
| Would need a string over 2 GB | 14 | Untestable in practice |
| Symmetric arguments (`json_min`, `calloc`, `strncasecmp` equality) | 14 | Yes |
| `\|` vs `^`, or `\|=` vs `^=`, on bits that never overlap | 13 | Yes |
| `obj` is always NULL on error | 10 | Yes |
| mewt mutated a preprocessor line | 10 | Untestable here |
| Buffer is NUL-terminated after a reset | 8 | Yes |
| mewt edit unchanged after translating to C (`nullptr` → `NULL`) | 8 | Yes, they are no-ops |
| Out-of-memory paths still alive | 13 | 8 need glibc's own `newlocale` to fail, which the wrapper can't force; 2 are the dead code-point branch; 3 are `!=` → `<` where both are the same |
| Other harmless groups (no exponent in a 1-char buffer, appending 0 bytes, buffer sizes, dead code, comment buffer, assert removed, break → continue after a goto, error-text bound) | 38 | Yes |

## Caveats before moving any of this into the real gate

1. **The memory-failure comparison is very strict.** It requires the refactor to make the same memory requests in the same order. A correct refactor that allocates differently (one buffer fewer, say) would fail. The real gate should use a weaker rule. Under any single failed request, the refactor must not crash and must not leak, and it must give either the original's answer or an out-of-memory error. I haven't measured how many mutants that weaker rule still catches. *(Done since: commit `b997720`, see "After the measurements" below.)*
2. **The German locale** is built with `localedef` into a user folder (no sudo) and found through `LOCPATH`. CI would build it the same way. glibc's `newlocale` keeps a small allocation when `LOCPATH` is set, so the recorder tells LeakSanitizer to ignore that one allocation.
3. **Time per check:**

   | Checker | Per mutant | Note |
   |---|---|---|
   | Current gate | About 3 s | Including both builds |
   | v2 | About 33 s | Measured with the original rebuilt for every mutant, as the real gate does |
   | v3 + neighbours | About 22 s | Measured with the scratch campaign checker, which builds and runs the original once |

   Most of the cost is the memory-failure mode. That is fine for one PR, but slow for big mutation campaigns.
4. **Neighbour inputs gave little:** 3 catches for 2,268 inputs.
5. **Fuzzer finds are single inputs.** The fuzzer itself should keep running as a separate job that never fails a PR, with each new find added to `oracle/inputs/`. *(Done since: the `fuzz` job, commit `18214b4`; not a required check.)*
6. **Not analysed:** under memory failure, the original sometimes answers "success" (2,264 times) or an error other than "out of memory". Bug-hunt finding 5 is one such case. The rest weren't checked.

## Suggested order for the real gate

*(Done since: steps 1–5 are committed, each with its tests; see "After the measurements" below. Step 6 went in differently: the large inputs are stored in `oracle/inputs/large.txt`, 1.5 MB, not generated at run time.)*

1. **Feeding in pieces, streams, readers taking turns, all 8 flag sets, edge-case API calls** (task 2). This is the biggest single gain.
2. **Checks after a reset, and two readers with different settings.** Both are cheap.
3. **Failing memory requests on purpose,** while parsing, while creating a reader and in `parse_verbose`, with the weaker rule from caveat 1.
4. **A run under the German locale.**
5. **Fuzzer-found inputs in `oracle/inputs/`,** plus the fuzzer as a job that never fails a PR (task 3).
6. **Large inputs,** generated at run time rather than stored.

Each step should come with tests in `oracle/tests/` that plant the matching mistakes and require FAIL, as `test_check.py` does today.

## After the measurements: what went into the gate

The iterations are on branch `a/gate-iterations`, one commit each, so each can be checked out and measured on its own (nothing is merged yet):

| Commit | Iteration | Answers per check |
|---|---|---|
| `d5483de` | 1, the prototype: pieces, streams, turns, 8 flag sets, edge-case API calls, `multi.txt` | 510,387 |
| `6b83848` | 2, v2: failed allocations, `de_DE`, after a reset, `large.txt`, first fuzzer finds | 600,566 |
| `f697874` | 3, v3: failures creating tokeners and in `parse_verbose`, two settings at once, 5 more fuzzer finds | 656,203 |
| `eb64d4e` | 4, neighbour inputs | 1,051,570 |

The committed iterations are clean rewrites of the scratch versions above, not copies, and were **not measured again**: the catch rates in this file are the scratch versions'. Differences from the scratch versions: multi-call parses also record how many calls they took; each answer is filed under its own input, with an `#input N` line so a crash is placed correctly; the edge-case API calls are filed after the last input and named as such in reports.

The rest is on branches of its own, each built on the one before: `a/ci` ← `a/metrics` ← `a/gate-iterations` ← `a/fuzz` ← `a/anti-cheat` ← `a/docs`.

| Branch | Commit | Change |
|---|---|---|
| `a/metrics` | `595a2e5` | `oracle/metrics.py`, report only |
| `a/gate-iterations` | `43a90e1` | CI no longer runs the gate's own tests (they test the gate, not a rewrite) |
| `a/gate-iterations` | `f159d33` | Fix: the locale was not found with a relative `--build-dir` |
| `a/gate-iterations` | `b997720` | The fairer failed-allocation rule (caveat 1). A correct rewrite with one extra allocation now passes; the planted out-of-memory mistakes of iterations 2 and 3 are still caught |
| `a/fuzz` | `23e3570`, `18214b4` | The differential fuzzer in `fuzz/`, and a `fuzz` job for rewrite PRs (not a required check) |
| `a/anti-cheat` | `f42ce65`, `5c837f1` | The anti-cheat check, below, and what Role B may use |
| `a/docs` | `76c4213` and later | README: how to run everything; these notes, the deck and the explainer pages |

Tests: 113 pass, plus 2 that need cmake (not installed on this machine).

## Do the checks overlap? Can any be dropped?

Every mutant v3 catches was rerun with a record of **which** ways of asking show the difference (2,160 mutants: my generator's, Mull's, refactor-style and the 9 planted; mewt left out, large inputs left out).

- 1,600 are caught by a difference in answers, so all the ways that catch them are known. 538 are caught by a crash, leak or timeout, which stops the run at the first way that hits them, so only that first way is known.
- The overlap is large. Most mutants are caught by 10 or more ways at once. A set of 11 of the 18 ways catches all 1,600; among the inputs, 52 of about 3,400 catch them all. 7 of the 8 flag sets catch nothing alone.

| Way of asking | Catches (of 1,600) | Caught by no other way |
|---|---|---|
| Split in two | 91% | 0 |
| Several documents on one reader | 90% | 12 |
| Length -1, whole text, reused reader, no end byte | 88–89% each | 3 in total |
| Two readers taking turns | 87% | 6 |
| Byte by byte | 87% | 0 |
| German locale | 82% | 5 |
| Two readers, different settings | 82% | 0 |
| `parse_verbose`, `parse`, nesting limits | 67–71% | 1 |
| Memory failure (parsing, `parse_verbose`, byte by byte) | 56–68% | 3 |
| After reset | 21% | 1 |
| Edge-case API calls | 1% | 8 |

Time per group in one run of v3 on the original (about 9 s of checking): pieces, streams and turns 45%; the 29 original ways 34% (inflated by the large inputs); memory failure 16%; locale, after reset and two settings 5%.

**Decision: nothing was trimmed.** Several ways that catch nothing alone each guard one kind of mistake the table cannot show (the 2 new flag sets catch the XOR mistake only together; "two settings" caught the shared `max_depth` by a crash, outside the difference-only data). Trimming the inputs to the 52 that matter here would fit the gate to these mutants. The safe trims (byte by byte under 3 flag sets instead of 8, no byte-by-byte memory failure) would save about 15–20% of a one-minute CI run.

## The last 94 unproven survivors

After the 60-second fuzzing and the 2,268 neighbour inputs, the 94 unproven survivors were fuzzed again for 3 minutes each with libFuzzer's value profiling (`-use_value_profile=1`, which steers inputs towards the constants the code compares against). **None showed a difference.** They are very likely harmless, but not proven.

## The anti-cheat check (`f42ce65`)

Before a rewrite is built, `oracle/cheats.py` compares it with the original and rejects it (exit 5, REJECTED) if it calls functions a parser has no use for (R1), defines names the C library or sanitizers own (R2), uses compiler tricks (R3), tests how it is being built (R4), or contains a new string of 4 or more characters found in the gate's inputs (R5).

Tested on 34 cheats in 5 groups and 11 honest refactors:

| Rule | Catches | Caught by no other rule |
|---|---|---|
| R1 calls | 17 | 16 |
| R2 definitions | 4 | 4 |
| R3 compiler tricks | 6 | 5 |
| R4 build detection | 4 | 4 |
| R5 copied inputs | 1 | 1 |

- No rule is redundant; only one cheat (a weak-symbol probe for ASan) was caught by two rules.
- All 11 honest refactors pass (helpers, macros, extra `malloc`, `assert`, `snprintf`, a lookup table, a new 3-letter literal), and none of the 2,401 mutants from the review was rejected.
- 3 cheats get through, all hard-coded answers not written as a string: the input spelled as characters, compared byte by byte, or matched by a hash. The fuzzer is the defence: special-casing the gate's inputs does not make a rewrite right on new ones.
- A loophole found while writing it: json-c's own file, logging, global-setting and random-seed functions were allowed at first; they are forbidden now.
- Open decisions: extend R5 to characters and byte-by-byte comparisons (about 20 lines of Python, no new dependency; Semgrep is installed in the scratchpad if rules are preferred), and a rule 6 that keeps existing functions outside `json_tokener_parse_ex` unchanged.

## Files (scratchpad, temporary)

`/tmp/claude-1000/-home-lmz-software-testing-group27-jsonc/788fb306-f376-4a3f-b007-0f68a562a3a6/scratchpad/`:

- `ext2/recorder.c`, `ext2/check_ext2.py`, `ext2/locale/`, `ext2/fuzzfound.txt`: v2 (memory failure, locale, after reset)
- `ext3/recorder.c`, `ext3/fuzzfound2.txt`, `ext3/neighbours.txt`: v3 and the neighbour inputs
- `refmut/gen_refactor.py`, `refmut/cascade.py`, `refmut/camp_check.py`: refactor-style mutants and the faster campaign checker
- `mull-dl/x/` (unpacked Mull), `mull-ws/` (Mull build, `gate_test.py`, results in `gate/` and `proto/`, patches in `patches/`)
- `fz2/fuzz_v2.sh`, `fz2/fuzz_v2.out`, `fz2/runs/`: fuzzing the unresolved survivors
- `v2_results.json`, `v3_results.json`, `v3n_results.json`, `final_groups.json`, `final_report.py`: results and the script that summarises them
- `explain/stops.c`: the stop-and-resume measurement
- `matrix/`, `matrix_run.py`, `matrix_analyze.py`: which ways of asking catch each mutant (the overlap analysis)
- `prof/`: the time per group of checks
- `fz2/fuzz_v3.sh`, `fz2/fuzz_v3.out`: the 3-minute fuzzing of the 94 unproven survivors
- `cheat_matrix.py`, `cheat_validate.py`: the anti-cheat test cases and the run over all mutants
- `semgrep-venv/`: Semgrep 1.187.0, not used by the gate
