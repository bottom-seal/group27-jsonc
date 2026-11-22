# json-c bug hunt: json_tokener_parse_ex

Baseline: json-c master `d2ce61e` (2026-11-21). Built with gcc ASan/UBSan; fuzzing with clang 18 libFuzzer.

## Finding 1 (new): unterminated comment at end of input inside a container returns the inner value as success

`json_tokener_parse("[1,2/*")` and `"[1,2//"` return success with the value `2`; `{"a":"x" /*` returns `"x"`; `[[1]/*` returns `[1]`.
Without the comment (`[1,2`) or with a closed one (`[1,2/**/`) it is correctly "unexpected end of data".
Cause: in the comment states, hitting the NUL jumps to `out:`, and the EOF check there
(`state != finish && saved_state != finish`) is skipped because `saved_state` is still `finish` from the
inner value just completed at depth > 0; `current` is that inner value. Present since at least 2013, still on master and all open PRs.
Found by the R2 stream oracle in `reuse_meta.c`. Reproducer: `repro_comment_eof.c`.
Side effect: the tokener is left at depth > 0 after the bogus success, so the next document on the same tokener (`3`) fails with "unexpected end of data" unless the caller resets it.

## Finding 2 (new): block comments ending in an even run of stars are not closed

`/** doc **/ 1` fails with "unexpected end of data"; `[1 /***/ ]` returns `1` (combines with finding 1);
`[1 /* x **/ ] */ ]` parses as `[1]` because the comment runs on to the later `*/`.
`*/` preceded by 1, 3, 5 stars works; 2, 4, 6 fails. Cause: `json_tokener_state_comment_end` sends any non-`/`
char, including another `*`, back to `json_tokener_state_comment`, which then skips the next char.
Code unchanged since the 2007 import. Found by the MR-comment test in `comment_meta.c` (inserting `/** c **/` at a token boundary changes the result). Reproducer: `repro_comment_stars.c`.

## Finding 3 (new): VALIDATE_UTF8 rejects a valid multi-byte character right after a complete value

With `JSON_TOKENER_VALIDATE_UTF8`, `{"a":1}é` fails with "invalid utf-8 string" and returns NULL, while `{"a":1}x` succeeds.
Most visible with `STRICT | ALLOW_TRAILING_CHARS | VALIDATE_UTF8`, where trailing characters are documented as allowed; also `1 €` with VALIDATE_UTF8 alone.
Cause: `PEEK_CHAR` runs the UTF-8 validator on the lookahead byte that ends the value (it is never consumed: parse_end stays 7),
leaving a pending multi-byte count, and the check at `out:` (`nBytes != 0`) turns the success into an error. Open PR #1014 keeps the count in the tokener but still fails this case (tested with it applied).
Found while reading the validator path, then confirmed with `batch.c`. Reproducer: `repro_utf8_lookahead.c`.

**Finding 3b (new, found in round 8, same root cause): VALIDATE_UTF8 reports syntax errors on non-ASCII characters as "invalid utf-8 string".** Whenever the state machine stops on the lead byte of a *valid* multi-byte character, the epilogue replaces the real error with `json_tokener_error_parse_utf8_string`.
- A UTF-8 BOM before a document (`\xef\xbb\xbf{}`) is valid UTF-8 but is reported as invalid UTF-8. Without the flag it gives "unexpected character".
- Other examples: `[é]` (should be unexpected character), `{é:1}` (object key expected), `[1é]` (number expected) and `[trué]` (boolean expected). ASCII errors such as `[x]` keep the right code.
- PR #1014 doesn't change this, and neither did my first local fix for finding 3.
- Suggested fix: drop the `out:` overwrite. With #1014, a byte that really is invalid is already reported inside `PEEK_CHAR`, so a pending count at `out:` only ever means "stopped on a valid lead byte".
- With that change (patch 2/2 in `local_fixes_findings_1-5.patch`), all of these still pass: test_parse OK=321 ERROR=0, the 2.37M-sequence UTF-8 BVA, chunk relations, 3M escape-equivalence checks and flag monotonicity.
- Found by testing BOM handling, an idea from the literature review. Reproducer: `repro_utf8_relabel.c`.

## Finding 4 (new): STRICT mode accepts single-quoted object keys

`JSON_TOKENER_STRICT` rejects `['a']` but accepts `{'a':1}` and returns `{"a":1}`.
Commit a07ef3d (2013) added the strict check only to `json_tokener_state_start`;
`json_tokener_state_object_field_start` (json_tokener.c:1271, `c == '"' || c == '\''`) has no strict check.
Found by the oracle (JSONTestSuite `n_object_single_quote.json`, json-c STRICT vs Python json).
No matching issue or PR upstream (searched issues/PRs; open PRs 1006/1007/1013/1014 don't touch this line). No test in tests/test_parse.c covers it.
Reproducer: `repro_strict_single_quote_key.c`.

## Finding 5 (new, low severity): out-of-memory on a top-level scalar is reported as "unexpected end of data"

If the allocation for a top-level scalar fails (`true`, `-12`, `1.5`, `NaN`, `Infinity`), `json_tokener_get_error()` returns
`json_tokener_error_parse_eof`, not `json_tokener_error_memory`. The same failure inside a container (`[true]`) is reported correctly.
Cause: a top-level scalar is only built when the terminating NUL is seen, so `c == 0` at `out:`, and the EOF check there
overwrites `tok->err`. Commit 99c14de ("tokener: preserve number errors at EOF", 2026-11-09) fixed the same clobbering for
number-range errors only. Found by allocation-failure injection (`oom_inject.c`, wraps malloc/calloc/realloc/strdup and fails
the Nth call for every N). The same run found no leaks, use-after-free or double free on any OOM path (ASan/LSan, 420 inputs x 2 flag sets x one-shot/bytewise).
Reproducer: `repro_oom_eof.c`.

## Finding 6 (new): quadratic time when a long number is fed in chunks

Feeding a long number through json_tokener_parse_ex in small pieces is O(n^2): a 1.28 MB number in 1-byte chunks takes 15.6 s (a string of the same size takes 0.02 s), and doubling the length quadruples the time.
At a realistic 32 KiB chunk size (the block size apps/json_parse reads), a 50 MB number takes 2.8 s against 0.15 s one-shot, and the gap keeps growing with size, so an attacker-supplied huge number is a CPU cost multiplier for streaming readers.
Cause: every call that resumes `json_tokener_state_number` runs `strchr(tok->pb->buf, 'e')` and then `strchr(..., 'E')` over all digits saved so far, to rebuild the exponent state (callgrind: 94% of instructions in strchr). Open PR #1006 rewrites this resume path but keeps both strchr calls (measured: same timings).
Found by `perf_chunk.c` (one-shot vs 1-byte feeding per token type). Reproducer: `repro_quadratic_number.c`.

## Finding 7 (new, low severity): comment text is buffered in memory even though it is discarded

Every byte of a comment is appended to `tok->pb` (only `MC_DEBUG` ever reads it). Feeding 200 MB of comment text in 64 KiB chunks peaks at 201 MB RSS, and 800 MB peaks at 801 MB. The same amount of whitespace peaks at 1 MB. So a streaming reader's memory is bounded by the largest comment, not by its chunk size.
The mutation analysis backs this up: the four mutants that drop those `printbuf_memappend` calls in the comment states have no observable effect on any result.
Because `printbuf` caps at INT_MAX, this is also a hard limit on valid input. Tested: `[1 /*` + 2.2 GB of comment text + `*/]` fed in 64 KiB chunks fails with "out of memory" after 2047 MB (peak RSS 2049 MB), while the same 2.2 GB of whitespace parses to `[1]` with 1 MB RSS.
Reproducer: `repro_comment_memory.c` (with `./a.out 209715200 0` for comment and `... 1` for whitespace).

## Finding 8 (new, low severity, master-only regression): data race on the cached C locale

Commit fd92d58 (2026-09-28, after the 0.19 release) replaced the per-call `duplocale`/`newlocale` with a lazily created static
`c_numeric_locale`. The check-then-create at json_tokener.c:357-359 is not synchronised, so two threads making their first
`json_tokener_parse_ex` calls at the same time, each with its own tokener, race on it. ThreadSanitizer reports it on every run
(`repro_tsan_locale_race.c`). On glibc the effect is benign because `newlocale(LC_NUMERIC_MASK, "C", 0)` returns the static C locale. On platforms
where it allocates a new object each time (for example AIX, the platform the commit targeted, as far as I can tell from its message), the losing thread's locale object leaks, and the access is formally undefined behaviour.
A `pthread_once` or an atomic compare-and-swap would fix it. Open issue #855 is about setlocale-only platforms, not this.

## Observations (not claimed as bugs)
- Related to finding 5: a top-level STRICT number that breaks the RFC grammar at end of input (`01`, `1.`, `1e`, `1.-5`) is also reported as "unexpected end of data", while `[01]` gives "number expected". Commit 99c14de calls this a bug and fixed it for overflow only, but tests/test_parse.c line 411 still pins `0e` -> parse_eof in strict mode, so maintainers need to decide which code is right.
- STRICT rejects integer overflow (`-9223372036854775809`, `18446744073709551616`) with ERANGE but silently accepts double overflow (`1e400` becomes inf, `1e-400` becomes 0).
- Header doc bug: the `json_tokener_parse_ex()` example in json_tokener.h tells callers to add 1 to `stringlen` for the final `'\0'` and then to check `json_tokener_get_parse_end(tok) < stringlen` for trailing characters. parse_end never counts the NUL (`"1"` with len 2 gives parse_end 1), so following the example reports trailing characters for every complete input.
- Embedded raw NUL bytes act as end of input, but the error offset is inconsistent: in the string and comment states the NUL is consumed (`["a<NUL>b"]` gives parse_end 4, one past the NUL), while everywhere else parse_end stops at the NUL (`[1<NUL>,2]` gives 2). In STRICT the string state's control-character error is also overwritten with parse_eof, the same `out:` override as finding 5. The cause is that `ADVANCE_CHAR` runs before the NUL is seen.
- Interop (Bishop Fox's key-collision class): lone surrogate escapes become U+FFFD, so distinct keys collide and members are silently dropped. `{"a\ud800":1,"a\udbff":2,"a\udfff":3}` gives one member `{"a\ufffd":3}`, also with STRICT and VALIDATE_UTF8, while Python keeps three keys. RFC 8259 section 8.2 calls unpaired surrogates unpredictable, so this is implementation-defined, but the silent loss of members could be documented or rejected under STRICT. No upstream issue found. Reproducer: `repro_surrogate_key_collision.c`.
- Object keys containing `\u0000` are truncated (`{"a\u0000b":1,"a\u0000c":2}` gives `{"a":2}`, also in STRICT). This is already known: issue #715 and PR #1007.
- Non-strict mode ignores trailing characters after a top-level value (`1x` -> 1), except when the trailing text starts with `/` that is not a comment (`1/`, `[]/x`), which fails with "expected comment". Found by the lenient reference-model oracle.

Upstream search (issues + PRs: "comment", "unterminated", "block comment", "ALLOW_TRAILING_CHARS", "VALIDATE_UTF8", "error_memory", etc., 2026-11-21) found nothing for any of the eight findings. Round 8 search (2026-11-22: "surrogate key", "lone surrogate", "U+FFFD", "BOM", "byte order mark", "VALIDATE_UTF8 error", etc.) found nothing for finding 3b or the key-collision observation.

## Rediscovered (already known upstream, good for validating the harnesses)
- VALIDATE_UTF8 rejects a multibyte char split across parse_ex calls (`"\xc3` + `\xa9"`): open PR #1014.
- Numbers split across calls (`" --1"` split after the space, `[1` + `-1]`): open PR #1006.
- Key with `\u0000` truncated (`{"foo\u0000bar":42}` -> `{"foo":42}`): open PR #1007.
- Design limitation, not reported: STRICT trailing-character rejection depends on chunking (`1 2` one-shot = error, `1 ` + `2` = success with 1), because a chunk ending right after a complete value returns it.

## Clean results (after applying PRs 1006 + 1014 locally)
- Metamorphic: 100k generated inputs x 5 flag sets x every 2-split + bytewise: 0 mismatches in result and error code (60k of them also checked for error char_offset).
- libFuzzer (fuzz_meta.c: metamorphic oracle + ASan/UBSan), 8 workers x 9 min, about 5.5M execs per worker, cov 808: no crash, no mismatch.
- EP/BVA (4,727 number/string/literal cases x 3 wrappings, STRICT vs Python): only documented differences (NaN/Infinity accepted, >int64 rejected with ERANGE).
- gcov on json_tokener.c with the fuzz corpus: 91.6% lines, 85.1% branches taken; all 27 states hit. Uncovered lines are mostly OOM paths.

## Round 2 clean results
- Tokener reuse after `json_tokener_reset` (R1, 12k pairs x 3 flag sets x 3 prefix modes): 0 mismatches.
- libFuzzer `fuzz_meta2.c` (3-piece split + reset reuse), 8 workers x 15 min, about 10.4M execs per worker, cov 825: no crash, no mismatch.
- Depth BVA (`depth_bva.c`, max_depth 1,2,3,32,100 at max-1/max/max+1): one-shot and bytewise agree. Note `json_tokener_new_ex(1)` rejects `[1]`: nesting k needs max_depth >= k+1. Doc only says "max nesting depth", so this is a doc ambiguity, not claimed as a bug.

## Round 3 clean results
- Lenient reference model (`ref_lenient.py` + `ref_oracle.py`, json-c non-strict vs a Python model of its documented grammar): 200k generated + mutated inputs. With the model emulating findings 1 and 2, the only remaining differences are known or by design (lenient `1e` -> 1, number text like `05e+1` kept verbatim in output, which open PR #1013 addresses, and the trailing `/` observation).
- Strict generated-input oracle (`strict_oracle.py`, json-c STRICT and STRICT|VALIDATE_UTF8 vs Python json): 120k inputs, only documented differences (ERANGE on huge ints, lone surrogates -> U+FFFD, raw bytes accepted without VALIDATE_UTF8).

## Round 4 clean results
- libFuzzer `fuzz_wrap.c` (wrap relations, one-shot + bytewise, flags 0 / VALIDATE_UTF8, PRs 1006+1014 applied), 6 workers x 20 min, about 18 to 30M execs per worker: no crash and no real mismatch. The only abort was a 31-deep array that goes past the default depth of 32 once wrapped, which is a limitation of the relation, not a bug.
- Literal edge cases (`[truex]`, `[NaN1]`, `[-x]`, `-`, ...) and json_tokener_new_ex(0) guard: consistent.

## Round 5: local fixes and runs on the fixed build
- `local_fixes_findings_1-5.patch`: small fixes for all five findings (applied on top of PRs 1006 + 1014). With them, json-c's own ctest suite gives the same result as master: only `test_json_parse_cli` (the apps/json_parse EOF-scalar case, open PR #1001) and `test_tokener_oom` (fails only under the valgrind wrapper here) fail, and they fail on master too. `test_parse` differs only by the lines PR 1006 adds to the expected output.
- Reference-model oracle with the bug emulation turned off (`ref_lenient.py` with `EMULATE_STAR_BUG = False`, open comments rejected): 120k inputs, only the known by-design classes left. So the model and the fixed parser agree.
- `term_meta.c` termination modes (len+1, len=-1, len then a separate NUL call, an extra zero-length call): 48k checks on master and on the fixed build, 0 mismatches.
- 20-minute fuzz runs on the fixed build: `fuzz_wrap.c` with comments allowed (4 workers, about 18 to 22M execs each) and `fuzz_meta2.c` (4 workers, 13 to 20M execs each). No crashes and no real mismatches. The only aborts were the 31-deep array depth-limit case.

## Round 6 results
- Exhaustive VALIDATE_UTF8 BVA (`utf8_bva.py`): every 1- and 2-byte sequence, every 3-byte lead with all second bytes and boundary third bytes, and every 4-byte lead with boundary bytes, each inside a string value, a key and mid-string (2.37M docs). json-c and Python's strict UTF-8 decoder agree on all of them, so the new overlong/surrogate checks from b99d91f are right.
- Performance per token type (`perf_chunk.c`): found finding 6. Strings, keys, comments and whitespace are linear.
- Cross-version differential (a dry run of the Role A old-vs-new oracle): `batch.c` built against json-c 0.18, 0.19 and master, run over 111k inputs (fuzz corpora plus generated) with flags 0, STRICT, VALIDATE_UTF8 and STRICT|ALLOW_TRAILING; `regdiff.py` groups every changed (error, value) pair. Non-strict behaviour is identical across all three versions. Every strict and UTF-8 change traces to an intended commit (UTF-8 accepted in strict mode since 0.19 (#875/#892), control characters in keys rejected, the RFC number grammar from e222189/ff18c75, the overlong/surrogate checks from b99d91f). No regressions found.
- Strict and non-strict oracles rerun on the 107k stripped fuzz-corpus inputs: nothing beyond the findings and by-design classes.
- Long fuzz runs on the fixed build (all 5 fixes plus PRs 1006/1014), max_len 1024: `fuzz_meta2.c` 3 workers (about 52M execs total) and `fuzz_wrap.c` with comments allowed and the depth guard, 3 workers (about 62M execs total). No crashes and no mismatches. Both runs ended early, around 20 to 27 minutes per worker, when the container's background processes were stopped.
- On the fixed build: chunked metamorphic test on 100k more generated inputs plus 6k UTF-8-heavy inputs, the reuse/stream oracle, the comment-insertion test and the reference-model oracle (300k inputs). All clean, which also suggests the local fixes don't introduce new mismatches.

## Mutation analysis of the oracle (how strong a Role A gate built from these harnesses is)
`mutation/mutate.py` makes single-point mutants of json_tokener_parse_ex and the UTF-8 validator (swapping relational and logical operators, 0/1 constants, `!`, `break`, `goto redo_char`). It builds each mutant and runs `mutation/mut_driver.c`, which acts as an old-vs-new oracle: for 3,400 inputs it records error code, char_offset, value and a type signature, one-shot and byte-by-byte, under flags 0, STRICT and VALIDATE_UTF8, plus a two-documents-on-one-tokener stream mode.
- 250 mutants (seed 7, `mut7b.txt`): 2 did not compile; of the other 248, 199 were killed by both one-shot and chunked comparison, 12 only by one-shot, 4 **only by chunked feeding**, 7 by timeout and 4 by crash. 22 survived, which is 89% killed.
- Nearly all survivors are equivalent mutants: the locale setup, the `len` range check, `default: break;`, and the four `printbuf_memappend` calls that copy comment text into `tok->pb`. The last group shows that buffering comments has no observable effect: it is dead work kept only for MC_DEBUG, and a large comment costs memory equal to its size.
- What the survivors taught us about the oracle (worth building into the gate): (1) compare value **types**, not just serialized text (the first input set missed int-vs-uint64 and int-vs-double kinds of change), (2) include a **stream/reuse mode** (one surviving mutant skipped resetting level 0 after success, and only reuse exposes that), (3) include **boundary inputs** for every range check: `\u0800`, `\u07ff`, `\ud800\udc00` (U+10000), `\xe0\xa0\x80`, a key with raw `\x1f` in strict mode, `[00]`, and INT64_MAX. Adding those 34 inputs killed 3 more mutants in each run.
- The 4 chunked-only kills (number resume path: `is_exponent`, `neg_sign_ok`, `pos_sign_ok`, the uint64 branch) are concrete evidence that the metamorphic chunked tests add detection power over one-shot oracle comparison.

## Round 7 (code analysis) clean results
- Read every state of json_tokener_parse_ex plus printbuf.c, json_parse_int64/uint64 and json_tokener_parse_double. The literal, escape, surrogate, depth and number-trim logic all hold up. Note: json_parse_int64 doesn't check that strtoll consumed the whole text, but the number state only ever hands it `-?digits`, so nothing can reach that gap.
- Built with `-funsigned-char` (as on ARM): 111k inputs x 3 flag sets give byte-identical results to the signed-char build.
- clang `-fsanitize=integer,implicit-conversion,float-cast-overflow`: the tokener only reports the intended char-to-unsigned-char conversion in the UTF-8 validator. Everything else is the intentional wraparound in linkhash's hash function and random_seed.
- ThreadSanitizer with concurrent first calls: finding 8.
- Error-position differential (STRICT char_offset vs Python `JSONDecodeError.pos` on the regression corpus): offsets agree or differ by one for literals and numbers, because json-c reports the position after the bad byte. The big gaps are all inputs where Python stops at the first non-JSON construct (single quotes, comments, `#`) and json-c gets further. Hand checks of 22 strict error cases found no wrong localization.
- Number edge cases (31 inputs, lenient and strict), surrogate escapes (14 inputs vs Python: lone surrogates become U+FFFD, and the following character is never lost) and embedded NUL bytes (8 inputs x 2 modes under ASan): no bugs beyond the observations above.
- New libFuzzer target `fuzz_neg1.c` runs the `len = -1` mode on an exact-size heap buffer, so any read past the terminating NUL would trip ASan (all earlier fuzzers passed an explicit length). 10 minutes on 4 workers (about 46M execs, each running both `-1` and `len+1` on all flag combinations): no crashes and no ASan/UBSan reports.

## Round 8 (skill-guided: variant analysis, spec-vs-code, coverage gaps)
Method: searched the skills.sh registry and used Trail of Bits' `variant-analysis`, `spec-to-code-compliance` and `coverage-analysis` skills (trailofbits/skills @ 149d7b2) as checklists. A literature review of known JSON parser bug classes is in `reports/` when it finishes.
- **Variant analysis of finding 6.** Root cause: when the number state resumes, it rebuilds its micro-state from the saved text, and the rebuild is incomplete. Following that root cause rediscovered open PR #1006, with a sharper picture of the impact. On master, `[12` + `-3]` returns `[12]` and silently drops `-3`. `[12` + `-3,4]` returns `[12,4]`. `[-1` + `-Infinity]` returns `[-Infinity]`, so the -1 is replaced. One-shot, all three are "number expected". Present in 0.18, 0.19 and master. Lenient mode only, because STRICT's RFC grammar check catches it.
  - The silent drop comes from a second gap. `json_parse_int64()` and `json_parse_uint64()` never check that strtoll/strtoull consumed the whole text, so `"12-3"` becomes 12. That makes it a defence-in-depth fix worth adding next to #1006.
  - Exhaustive check: every string of up to 5 characters over `0 1 9 - + . e E I`, in five wrappers (147,620 inputs), at every 2-split and bytewise, in lenient and STRICT. Master gives 168,710 mismatches. The PR #1006 build and the local fixed build give 0, so #1006 looks complete for numbers.
- **Variants of findings 1, 2, 4 and 5.**
  - Finding 1: the only states entered while `saved_state` is still `finish` are the four comment states, all already in finding 1.
  - Finding 2: no other state consumes a delimiter it should re-examine. The surrogate need-escape and need-u states re-process the character correctly (`"\ud800x"`, `"\ud800\n"`).
  - Finding 4: every lenient extension other than single-quoted keys has its STRICT guard. That covers comments, single-quoted values, trailing commas, case-insensitive literals, control characters in strings and keys, number grammar and trailing characters.
  - Finding 5: the `out:` overwrite only hits errors that are detected while `c` is the NUL. Memory errors and strict number errors are already in finding 5 and its observation, and nothing else is affected.
- **Spec vs code (json_tokener.h as the spec).** Most documented behaviours hold. Divergences:
  - Already reported: findings 3 and 4, and the parse_end example bug.
  - The header says a valid value always gives a non-NULL object, but `null` returns NULL with success. That's a long-standing documentation problem.
  - `json_tokener_error_size` is documented as "string longer than INT32_MAX" but is also returned for any `len < -1`.
  - The depth limit counts values, not containers: depth 1 accepts `[]` but rejects `[1]`, and depth 2 accepts `[[]]` but rejects `[[1]]`. "Max nesting depth" in the header doesn't say this.
  - Checked and holding: error_desc on out-of-range values, `STRICT|ALLOW_TRAILING_CHARS` multi-document streams, and new_ex(depth < 1) returning NULL.
- **Literature review (deep-research):** `reports/JSON parser bug classes.md`, with the raw notes in `research_notes/`. It maps 45 known bug classes, json-c's CVE and fix history, and published differential-testing studies onto what we already cover, and ranks 14 remaining directions. Two of the 2026 CVE numbers cited in json-c's own ChangeLog don't match their public records; the report flags them. I tested these directions from it:
  - **Flag monotonicity:** if a stricter flag set accepts an input, every laxer set must accept it with the same value and parse end. 0 violations over 38,835 corpus and JSONTestSuite files, one-shot and bytewise.
  - **Escape equivalence:** raw UTF-8, `\uXXXX` in both hex cases, and surrogate pairs for 30 boundary code points, as values and keys, one-shot, bytewise and every 2-split, under 3 flag sets: 3.0M checks. On master the only mismatches (118,476) are VALIDATE_UTF8 with a split inside a raw multi-byte character, which is the known split-UTF-8 issue fixed by #1014. With #1014 there are 0. Calling reset between the halves of a surrogate pair gives U+FFFD, which is correct.
  - **Exact-size heap chunks with no terminating NUL**, plus a 0-length final call, under ASan: 1.18M calls, clean. Any read at `str[len]` would trip it.
  - **MemorySanitizer** with origin tracking over all corpora, 7 feeding modes x 6 flag sets: clean.
  - **Decimal-comma locale (de_DE.UTF-8)** with the uselocale build and with the setlocale-fallback build: numbers parse correctly and the caller's locale is restored.
  - **BOM:** finding 3b.
  - **Key collisions:** see Observations.
  - **32-bit (`-m32`) build with ASan+UBSan:** 263k inputs x 5 flag sets give byte-identical results to the 64-bit build, with no sanitizer reports. Chunk relations on 3,052 inputs give the same mismatch count (2,467, all known master issues) for the 32-bit build and a 64-bit build of the same sources.
- **Coverage-gap hunt.** I built a gcov driver (`cov_driver.c`) that runs every input in 7 feeding modes (len+1, -1, bytewise, 2-split, stream, depth 4, no NUL) under 6 flag sets, over the fuzz corpora, JSONTestSuite, the regression inputs and the number set. Result: 90.8% of lines and 85.1% of branches in json_tokener.c. Every reachable non-OOM branch of `json_tokener_parse_ex` is taken. The leftovers are OOM paths, the `json_tokener_parse`/`parse_verbose` wrappers, a PEEK_CHAR sub-branch that can't be true in those states, and line 850 (code point >= 0x110000), which is dead code. So what remains to find is semantic, and only oracles will find it; more coverage won't.

## Files
- `chunk_meta.c` metamorphic harness: one-shot vs every split point and bytewise, compares error code, output and error char_offset. Input: one case per line, `\xNN` escapes. Set `KEEP_TRAILING=1` to include the strict trailing-chars class.
- `gen.py` grammar-based random generator for chunk_meta (`python3 gen.py SEED COUNT`).
- `oneshot.c` + `oracle.py` differential oracle vs Python json (`python3 oracle.py DIR FLAGS`).
- `fuzz_meta.c` libFuzzer target (byte0 = flags, byte1 = split point), `json.dict`, `fuzz_corpus.tgz`.
- `reuse_meta.c` R1 reset-reuse oracle and R2 multi-document stream oracle.
- `comment_meta.c` MR-comment: inserting a comment or space at a token boundary must not change the result.
- `depth_bva.c` depth limit BVA. `fuzz_meta2.c` round-2 libFuzzer target.
- `batch.c` batch one-shot driver used by the Python oracles (`./batch FLAGS < lines`).
- `ref_lenient.py` reference model of the non-strict grammar (set `EMULATE_STAR_BUG = False` to see finding 2 again); `ref_oracle.py SEED COUNT [x]`.
- `strict_oracle.py SEED COUNT [x] [FLAGS]` generated-input strict oracle.
- `oom_inject.c` allocation-failure injection (link with `-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup`), seeds in `oom_seeds.txt`.
- `flagmono.c` (flag monotonicity), `esceq.c` (escape equivalence), `exact.c` (exact-size unterminated chunks under ASan), round 8.
- `repro_utf8_relabel.c` (finding 3b), `repro_surrogate_key_collision.c` (interop observation).
- `reports/JSON parser bug classes.md` literature review; notes in `research_notes/JSON parser bug classes/`.
- `cov_driver.c` gcov driver: 7 feeding modes x 6 flag sets per input (round 8).
- `fuzz_neg1.c` libFuzzer target for the `len = -1` mode on an exact-size buffer (catches reads past the NUL).
- `fuzz_wrap.c` libFuzzer target for wrapping relations: if x parses fully, `[x]`, `{"k":x}` and `x ` must give the matching results, one-shot and bytewise.
- `term_meta.c` termination-mode metamorphic test. `local_fixes_findings_1-5.patch` suggested fixes.
- `utf8_bva.py` exhaustive VALIDATE_UTF8 BVA (2.37M sequences in values, keys and mid-string) vs Python's decoder: 0 mismatches.
- `perf_chunk.c` one-shot vs 1-byte feeding time per token type.
- `regdiff.py OLD.txt NEW.txt` groups behaviour changes between two `batch` runs (cross-version or old-vs-refactored).
- `mutation/` mutant generator, oracle driver, input set and two result logs.
- `replay.c` replays corpus files through the target for gcov.

Build (example): `gcc -fsanitize=address,undefined -I json-c -I json-c/build chunk_meta.c json-c/build/libjson-c.a -lm`;
fuzzer: build json-c with `-fsanitize=fuzzer-no-link,address,undefined`, then `clang -fsanitize=fuzzer,address,undefined -I... fuzz_meta.c libjson-c.a -lm`.
