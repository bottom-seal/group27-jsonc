# Differential-testing, fuzzing and metamorphic-testing studies of JSON parsers, and what they mean for json-c's `json_tokener_parse_ex()`

Scope note: these notes cover published studies, tools and harnesses, plus json-c's own bug history, which I read from a clone of github.com/json-c/json-c (master at d2ce61e, 2026-11-19). Serializer round-trips are out of scope. "Team-covered" techniques are taken from the assignment's constraint list. They are flagged when mentioned and are not recommended as new.

## Q1. What did Seriot's "Parsing JSON is a Minefield" / JSONTestSuite find, including json-c, and what do the i_ cases say about json-c?

### Takeaway
Seriot tested more than 30 parsers with more than 300 handcrafted and AFL-derived files and found that no two parsers behaved the same. The crashes came mainly from unbounded nesting depth and invalid UTF-8. The article never mentions json-c. The repo does run json-c, but the harness is pinned to **json-c-0.12** (2014), uses default lenient flags, makes one `json_tokener_parse_ex(tok, data, strlen(data))` call, and never checks the error code or the consumed length. Its published json-c column has 52 SHOULD_HAVE_FAILED, 5 SHOULD_HAVE_PASSED, 30 i_ accepted, 5 i_ rejected and 0 crashes. That mostly records 0.12 leniency and harness artefacts, not current json-c behaviour.

### Cited Findings
**Article (study-wide):**
- More than 30 parsers and more than 300 test files. The main conclusion is that no two parsers behaved the same, which "may cause serious interoperability issues" — [Seriot, Parsing JSON is a Minefield](https://seriot.ch/projects/parsing_json.html)
- Crashes:
  - Xcode and Bash JSON.sh segfault on 100,000 `[`.
  - Among C parsers, ccan and cJSON crash on deeply nested structures. jsmn, jansson and json-parser do not.
  - JSONKit crashes on nesting. SBJSON asserts on invalid UTF-8 `["\xFF"]`.
  - Freddy crashed on `["`, on unclosed structures and on a single space.
  - [Seriot](https://seriot.ch/projects/parsing_json.html)
- Number findings:
  - `1E-999` becomes 0.0 in most parsers, but a string in Freddy.
  - `[0.e1]` and `[1.]` are accepted by some parsers, including JSON_Checker, which also rejected the valid `[0e1]` until 2017.
  - cJSON turns `10000000000000000999` into `10000000000000002048`.
  - [Seriot](https://seriot.ch/projects/parsing_json.html)
- String and Unicode findings:
  - A lone `\uD800` is handled differently (Python keeps it; Go and JS substitute U+FFFD).
  - `["\u0000"]` is rejected by JSONKit and cJSON. `"A\u0000B"` gives `["A"]` in Freddy (NUL truncation).
  - Raw invalid UTF-8 and encoded surrogates (`ED A0 80`) are passed through by several parsers.
  - [Seriot](https://seriot.ch/projects/parsing_json.html)
- Duplicate keys: `{"a":1,"a":2}` gives last-wins, first-wins, or both entries kept (cJSON, R, Lua JSON). A CouchDB RCE was linked to this discrepancy. NFC and NFD forms of a key are kept separate by most parsers, but Swift normalizes them — [Seriot](https://seriot.ch/projects/parsing_json.html)
- Methodology:
  - Tests were handcrafted from the RFCs and existing suites, then supplemented with AFL-generated inputs that were deduplicated and minimized to the fewest characters giving the same result.
  - `run_tests.py` classifies each run by exit code: 0 = accept, 1 = reject, crash, or a 5 s timeout.
  - Results are rendered as cross-parser HTML tables sorted to make similar behaviour stand out. This is a differential approach in effect, though the article doesn't use the word.
  - Some tests were moved from y_/n_ to i_ after feedback: number range/precision and invalid UTF-8.
  - [Seriot](https://seriot.ch/projects/parsing_json.html)

**Repo (my inspection of [nst/JSONTestSuite](https://github.com/nst/JSONTestSuite) at commit 1ef36fa, 2024-11-22):**
- `test_parsing/` holds 95 y_, 188 n_ and 35 i_ files. A separate `test_transform/` set covers semantic cases: `number_-9223372036854775809`, `number_10000000000000000999`, `number_1e-999`, `object_same_key_*`, `object_key_nfc_nfd`, `string_with_escaped_NULL` and others — [JSONTestSuite repo](https://github.com/nst/JSONTestSuite)
- `run_tests.py` registers "C JSON-C" → `parsers/test_json-c/bin/test_json-c`. `parsers/test_json-c/get_json-c.sh` runs `git checkout json-c-0.12`, so the published results are for 0.12 — [run_tests.py](https://github.com/nst/JSONTestSuite/blob/master/run_tests.py), [get_json-c.sh](https://github.com/nst/JSONTestSuite/blob/master/parsers/test_json-c/get_json-c.sh)
- Harness defects in `parsers/test_json-c/test_json-c/main.c`:
  - It calls `json_tokener_parse_ex(tokener, data, strlen(data))` once with default flags.
  - It never calls `json_tokener_get_error()` and never compares the parse end with the length.
  - `strlen` truncates the input at an embedded NUL.
  - It leaks the tokener.
  - It calls `free()` on the `json_object_to_json_string()` result after `json_object_put()`, although that buffer is owned by the object.
  - [main.c](https://github.com/nst/JSONTestSuite/blob/master/parsers/test_json-c/test_json-c/main.c)
- json-c's own docs explain two of the artefacts:
  - "Trailing characters after the parsed value do not automatically cause an error". Callers must compare `json_tokener_get_parse_end()` with `len`.
  - "If the caller knows that they are at the end of their input, the length passed MUST include the final '\0' character, so values with no inherent end (i.e. numbers) can be properly parsed, rather than just returning json_tokener_continue".
  - [json_tokener.h on master](https://github.com/json-c/json-c/blob/master/json_tokener.h)
- json-c rows in `results/logs.txt`: 52 SHOULD_HAVE_FAILED, 5 SHOULD_HAVE_PASSED, 30 IMPLEMENTATION_PASS, 5 IMPLEMENTATION_FAIL, and no CRASH or TIMEOUT — [logs.txt](https://github.com/nst/JSONTestSuite/blob/master/results/logs.txt)
  - **SHOULD_HAVE_PASSED (5):** `y_structure_lonely_false`, `_int`, `_negative_real`, `_null`, `_true`. All are top-level scalars that end exactly at the buffer end.
  - **SHOULD_HAVE_FAILED (52), grouped:**
    - Trailing garbage or extra closers: `n_structure_array_trailing_garbage`, `n_object_with_trailing_garbage`, `n_structure_trailing_#`, `n_array_extra_close`, `n_structure_double_array`, `n_structure_number_with_trailing_garbage`, `n_string_with_trailing_garbage`, `n_structure_object_followed_by_closing_object`, `n_array_comma_after_close`, `n_structure_close_unopened_array`, `n_structure_array_with_extra_array_close`, and others.
    - Lenient numbers: `-01`, `-1.0.`, `-2.`, `0.1.2`, `0.3e`, `0.3e+`, `0.e1`, `0e`, `0e+`, `0E`, `0E+`, `1.0e`, `1.0e+`, `1.0e-`, `1eE2`, `2.e3`, `2.e+3`, `2.e-3`, `9.e+`, `NaN`, `infinity`, `-infinity`, `+-`, the expression `1+2`, leading zeros.
    - Single quotes in keys and strings.
    - Comments: `n_object_trailing_comment`, `n_structure_object_with_comment`.
    - Trailing commas in arrays and objects.
    - Raw TAB and newline inside strings.
    - A form-feed as whitespace.
    - Capitalised `True`.
    - `n_object_lone_continuation_byte_in_key_and_trailing_comma`.
  - **i_ rejected (5):** `i_string_UTF-16LE_with_BOM`, `i_string_utf16BE_no_BOM`, `i_string_utf16LE_no_BOM`, `i_structure_UTF-8_BOM_empty_object`, `i_structure_500_nested_arrays`. The last is consistent with `JSON_TOKENER_DEFAULT_DEPTH 32` in `json_tokener.h`.
  - **i_ accepted (30):**
    - All 10 `i_number_*` cases: `huge_exp`, `neg_int_huge_exp`, `pos_double_huge_exp`, `double_huge_neg_exp`, `real_pos_overflow`, `real_neg_overflow`, `real_underflow`, `too_big_pos_int`, `too_big_neg_int`, `very_big_negative_int`.
    - All 20 invalid-Unicode string and key cases: lone and inverted surrogates, `1st_surrogate_but_2nd_missing`, `incomplete_surrogate*`, invalid UTF-8, overlong 2- and 6-byte sequences (including `_null`), ISO-Latin-1, truncated UTF-8, lone continuation byte, not-in-Unicode-range, `UTF8_surrogate_U+D800`, `i_object_key_lone_2nd_surrogate`.
- `y_object_escaped_null_in_key.json` is `{"foo\u0000bar": 42}`. JSONTestSuite judges only accept or reject, so it cannot see what the parser does to the key — [test file](https://github.com/nst/JSONTestSuite/blob/master/test_parsing/y_object_escaped_null_in_key.json)
- Current json-c builds object keys with `obj_field_name = strdup(tok->pb->buf);` in the `json_tokener_state_object_field` case (json_tokener.c around line 1294). A key containing `\u0000` is therefore cut at the first NUL — [json_tokener.c on master](https://github.com/json-c/json-c/blob/master/json_tokener.c)
- json-c has since added `JSON_TOKENER_VALIDATE_UTF8` (0x10) alongside `JSON_TOKENER_STRICT` (0x01) and `JSON_TOKENER_ALLOW_TRAILING_CHARS` (0x02) — [json_tokener.h](https://github.com/json-c/json-c/blob/master/json_tokener.h). The i_string_overlong/surrogate class kept producing fixes as late as 2026: commit b99d91f (2026-10-05), "reject overlong and surrogate forms in json_tokener_validate_utf8" — [json-c commit b99d91f](https://github.com/json-c/json-c/commit/b99d91f)

### Inferences
- The published json-c column is stale (0.12) and limited by the harness. The 5 SHOULD_HAVE_PASSED results are almost certainly the documented "include the final '\0'" end-of-input rule, not a grammar bug. The trailing-garbage n_ results come from the missing parse-end check. The team's own strict-mode JSONTestSuite run supersedes these results.
- The i_ files are most useful as a checklist of implementation-defined dimensions that json-c exposes through flags and options:
  - integer range and clamping
  - double overflow and underflow
  - UTF-8 validation, which is opt-in
  - BOM handling
  - UTF-16 input, which is unsupported
  - depth limit
  For these files, semantic oracles (what value comes out) matter more than accept/reject.
- The key-NUL truncation is invisible to every accept/reject suite. It is the same class as Bishop Fox's "character truncation" and Crossy's "truncation at U+0000" (see Q2).

### Gaps
- I could not tell when the json-c rows in `logs.txt` were last regenerated, because I used a shallow clone. Only the 0.12 pin in `get_json-c.sh` is certain.
- `results/transform.html` contains no json-c entries that I could find, so there is no published json-c result for the `test_transform` semantic cases.
- The harness's `free()`-after-`put` bug did not show up as crashes. It may be that a different binary was used.

## Q2. Which academic papers and tools apply differential testing, grammar-based fuzzing or metamorphic testing to JSON parsers, and what bugs and bug types did they report?

### Takeaway
The only peer-reviewed study that included json-c is **Crossy** (ACM AsiaCCS 2024): coverage-guided cross-language differential fuzzing of 22 parsers. json-c sat in the fully compatible cluster, with 0 differences against jansson, jsmn, libjson, yajl, jsoncpp, nlohmann and jackson, and was flagged only for accepting raw control characters. Other studies are listed below. The JSON-specific grammar-fuzzing results are mostly about coverage and "accept-invalid" findings, not memory bugs. I found no paper dedicated to metamorphic testing of JSON parsers.

| Study | Subjects | Main result |
|---|---|---|
| Gmutator (TOSEM 2025) | cJSON, Parson, simdjson | Accept-invalid bugs in cJSON and Parson, a heap overflow in old cJSON, nothing in simdjson |
| Bishop Fox (2021) | 49 parsers | About 10 interoperability classes |
| Harrand et al. (ISSRE 2021) | 20 Java libraries | They agree on only 0.75% of ill-formed files |
| JSONTestGen (arXiv 2024) | fastjson2 | 34 bugs via LLM tests plus cross-version differential |
| pFuzzer, tribble/k-paths, EvoGFuzz | cJSON, Java JSON libraries | Better token or structure coverage; few parser bugs |

### Cited Findings
**Crossy — "Cross-Language Differential Testing of JSON Parsers" (AsiaCCS '24):**
- Subjects: 22 parsers in C, C++, Rust, Java and Python.
  - C (11): ccan, cJSON, frozen, jansson, jsmn, **json-c**, json-parser, json.h, libjson, poco, yajl.
  - C++: boost, jsoncpp, nlohmann, SpiderMonkey, rapidjson, v8.
  - Java: gson, jackson. Python: json, simplejson. Rust: serde_json.
  - [Crossy paper PDF](https://www.mlsec.tu-berlin.de/docs/2024b-asiaccs.pdf), [ACM DL](https://dl.acm.org/doi/10.1145/3634737.3657003), [code](https://github.com/j-moeller/crossy)
- Technique:
  - Built on libFuzzer. Control-flow edges from all targets go into **one shared coverage map**. Python and Java run through modified Atheris and Jazzer over pipes and shared memory.
  - Uses Nezha-style path δ-diversity (coarse and fine variants).
  - 566 seed files from 8 parser repositories; 24 h × 96 parallel instances.
  - Outputs are normalized by a consensus ensemble (jsmn, json.h, libjson), confirmed by majority vote, and compared node by node: objects by name/value pairs, arrays in order, numbers as int or float, strings code unit by code unit.
  - [Crossy PDF](https://www.mlsec.tu-berlin.de/docs/2024b-asiaccs.pdf)
- Results:
  - 29,266 unique discrepancy-inducing inputs.
  - Taxonomy: name, length, integer, float, precision, type and Unicode errors, plus parse errors.
  - Examples:
    - cJSON, jansson and poco give no output for large numbers.
    - json-parser mishandles UTF-16 surrogate pairs.
    - Several parsers truncate strings at U+0000.
    - frozen drops or restructures members whose names are empty or end in `.` or `]` (CVE-2023-48891).
    - gson drops null members.
    - ccan, jsmn, json-parser and json.h serialize control characters as invalid JSON.
  - No crashes were reported.
  - [Crossy PDF](https://www.mlsec.tu-berlin.de/docs/2024b-asiaccs.pdf)
- json-c specifics:
  - 1,560 edges and about 12,818 exec/s.
  - 0 differences with jansson, jsmn, libjson, yajl, jsoncpp, nlohmann and jackson.
  - 5 with ccan and json-parser, 4 with cJSON, 3 with serde, 2 with frozen, boost, rapidjson, SpiderMonkey, v8 and gson.
  - Listed among parsers that accept inputs containing control characters.
  - [Crossy PDF](https://www.mlsec.tu-berlin.de/docs/2024b-asiaccs.pdf)

**Gmutator — "Grammar Mutation for Testing Input Parsers" (Bendrissou, Cadar, Donaldson; ACM TOSEM 2025, DOI 10.1145/3708517):**
- Technique:
  - Mutates the ANTLR grammar itself with four operator types: repetition, concatenation, relaxed excluded character sets, and introduced choice. Mutants are monotonic supersets of the original language. Each mutant grammar yields 40 inputs.
  - G+M variant: generate a valid input, then apply 1–3 string mutations (duplication, deletion, token insertion).
  - Oracles: differential validity against an ANTLR parser built from the original grammar, classed as accept-invalid or reject-valid; plus crashes (3 s timeout, ASan to confirm).
  - [TOSEM PDF](https://www.doc.ic.ac.uk/~afd/papers/2024/TOSEM.pdf)
- JSON subjects: cJSON 1.7.8, Parson 1.4, simdjson 3.2.0. **json-c was not tested.** — [TOSEM PDF](https://www.doc.ic.ac.uk/~afd/papers/2024/TOSEM.pdf)
- Averages over three 24 h runs (accept-invalid / reject-valid):

  | SUT | Grammarinator | Gmutator | G+M |
  |---|---|---|---|
  | cJSON | 0 / 753 | 1,645 / 366 | 1,927 / 95 |
  | Parson | 0 / 7,890 | 7,574 / 4,157 | 31,962 / 686 |
  | simdjson | 0 / 2,292 | 0 / 1,355 | 0 / 296 |

  Source: [TOSEM PDF](https://www.doc.ic.ac.uk/~afd/papers/2024/TOSEM.pdf)
- Bugs:
  - cJSON: failure to reject an invalid escape (confirmed), and acceptance of invalid integers.
  - Parson: accepting an invalid array (`[true, ]`) and "EOF not enforced" (`{} {}`). The developers rejected both, citing the robustness principle.
  - G+M found a heap-buffer-overflow in cJSON with unbalanced quotes (`"""`). It was already gone from the latest cJSON.
  - [TOSEM PDF](https://www.doc.ic.ac.uk/~afd/papers/2024/TOSEM.pdf)

**Bishop Fox — "An Exploration of JSON Interoperability Vulnerabilities" (2021):**
- Surveyed 49 parsers in 10 languages. No pure-C parser and not json-c; rapidjson was the only C/C++ parser with findings — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)
- Classes found, with examples:
  - Duplicate-key precedence: first-key-wins in Go jsonparser, gojay, rapidjson, json-iterator, Jason, Poison and jsone.
  - Key collision by character truncation: unpaired surrogates (ujson, PHP json5), stray backslash or quote, backslash-CR.
  - Comment truncation (json-iterator, Ruby simdjson).
  - Unexpected comment support in 13 non-JSON5 parsers.
  - Stringified duplicate keys (rapidjson, MessagePack).
  - Large numbers turned into strings or `Infinity`, heavily rounded, or returned as 0 without error (Go jsonparser).
  - Segfault DoS in 2 unnamed parsers.
  - Trailing garbage enabling CSRF.
  - Recommended fixes: fatal errors on duplicate keys, U+FFFD instead of truncation, a strict RFC 8259 mode, and errors on numbers that cannot be represented.
  - [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)

**Harrand, Durieux, Broman, Baudry — "The Behavioral Diversity of Java JSON Libraries" (ISSRE 2021):**
- 20 Java libraries and 473 files (206 well-formed, 267 ill-formed) drawn from json.org, the Native JSON Benchmark, Seriot's suite and the jansson suite.
- 17 of 20 are conforming on more than 80% of well-formed files. 89 well-formed files (43.2%) trigger an Error in at least one library.
- On ill-formed files, the libraries agree on only 0.75%.
- A 64-bit float overflow case is handled without error by only 6 libraries.
- [arXiv/ar5iv 2104.14323](https://ar5iv.labs.arxiv.org/html/2104.14323)

**JSONTestGen — "Advancing Bug Detection in Fastjson2 with LLM-Driven Unit Test Generation" (arXiv 2410.09414):**
- Two-stage LLM prompting seeded from 681 issue-linked unit tests, plus 5 JSON-specific mutation rules.
- Oracle: **differential** outcomes across fastjson 1.2.83, fastjson-compatible and fastjson2.
- Found **34 real bugs (30 fixed; 12 non-crashing)**. Examples include a BigDecimal overflow giving -9223372036854775808.
- Zest (JQF) reached lower coverage and found 1 bug, against 8 for JSONTestGen in that comparison.
- [arXiv 2410.09414v2](https://arxiv.org/html/2410.09414v2)

**JFuzz proposal (arXiv 2410.21806):**
- An LLM few-shot test generator plus a multi-parser differential with a judge parser.
- It is a proposal with **no bug results**. It names null-field handling, trailing commas and number precision as discrepancy classes.
- [arXiv 2410.21806](https://arxiv.org/html/2410.21806v1)

**Grammar-based and parser-directed fuzzers evaluated on JSON:**
- pFuzzer, "Parser-Directed Fuzzing" (PLDI 2019):
  - Subject: cJSON (2,483 LOC), with 12 tokens.
  - AFL missed all JSON keywords (`true`, `false`, `null`). KLEE missed the comma. pFuzzer covered all tokens.
  - On cJSON, AFL and KLEE still reached higher code coverage, because pFuzzer missed the UTF-16→UTF-8 conversion code.
  - No bugs reported.
  - [pFuzzer paper](https://core.ac.uk/download/249327981.pdf)
- Havrikov & Zeller, k-path coverage (tribble):
  - Subjects: 11 Java JSON libraries (argo, fastjson, genson, gson, jackson-databind, json-flattener, json-java, json-simple, json-cliftonlabs, minimal-json, pojo).
  - At k=2 and k=3, k-path generation beat Grammarinator on branch coverage for most subjects.
  - Found NullPointerExceptions in json-flattener and genson and a StringIndexOutOfBounds in pojo.
  - [k-paths paper](https://core.ac.uk/download/491262466.pdf)
- EvoGFuzz (SSBSE 2020):
  - Evolves probabilistic-grammar rule weights.
  - Ten subjects (JSON, JavaScript, CSS3); up to 48% more median line coverage; 11 unique defects, 5 of them missed by the baseline.
  - [arXiv 2008.01150](https://arxiv.org/abs/2008.01150)
- Grammarinator + AFL++ (SANER-C 2026):
  - Evaluated only on JerryScript. Subtree-pool replacement was the most effective mutator.
  - Baseline libFuzzer found many crashes but often rediscovered the same faults.
  - [Hodován & Kiss 2026](https://www.inf.u-szeged.hu/~akiss/pub/fulltext/hodovan2026grammar.pdf)

**Tooling with JSON support:**
- AFL++ Grammar-Mutator:
  - Ships `grammars/json.json` and `grammars/json_no_ws.json` and accepts ANTLR `.g4` grammars (e.g. `JSON.g4`).
  - Tree mutations: rules, random, random-recursive, splicing. Trimming: subtree and recursive.
  - Built on F1 for generation and Nautilus for mutations. Used via `AFL_CUSTOM_MUTATOR_LIBRARY`.
  - [Grammar-Mutator README](https://github.com/AFLplusplus/Grammar-Mutator)
- Chromium `json.proto` for libprotobuf-mutator:
  - An ECMA-404-based proto with object, array, number (integer, float, exponent with upper/lower-case `E`), string and boolean. Null is an empty oneof.
  - [Chromium json.proto](https://chromium.googlesource.com/chromium/src/+/ef290da170d481d1ef1c9ca4e11d156cfaf09afe/testing/libfuzzer/proto/json.proto)
- OSS-Fuzz's jsoncpp LPM fuzzer:
  - Converts that proto to text and uses an `int32 settings` bitmask to toggle 11 reader options (comments, strict root, duplicate-key rejection, special floats, trailing commas and others).
  - Some option keys have inconsistent spellings (`failIfExtra` vs `failIfExtra_`), so it is unverified whether every bit takes effect.
  - [jsoncpp_fuzz_proto.cc](https://android.googlesource.com/platform/external/oss-fuzz/+/68a075473fa0aadbf64d22a14349d22d338e317d/projects/jsoncpp/jsoncpp_fuzz_proto.cc)
- JSON Schema validators — Bowtie:
  - A meta-validator that runs many implementations in containers (12 implementations in 9 languages at launch) against the official JSON Schema Test Suite through a harness protocol, and publishes comparison reports.
  - No bug counts are given in the intro post.
  - [Bowtie intro](https://json-schema.org/blog/posts/bowtie-intro)

### Inferences
- Crossy's 0-difference result suggests that more broad cross-parser value differentials will find little in json-c's core value semantics, at least under default flags and Crossy's normalization. That normalization compares strings code unit by code unit, but likely through each parser's serialized output, and json-c's key truncation would only show up if a test key contained NUL.
- The remaining yield is in dimensions those studies did not exercise: the incremental API, flag combinations, depth parameters, key handling, resource behaviour, and very large sizes.
- Gmutator's accept-invalid class is the main outcome of near-valid grammar mutation. For json-c it matters only under `JSON_TOKENER_STRICT`, because default mode accepts a documented superset. The parallel with Parson is that maintainers may reject such reports under the robustness principle.

### Gaps
- I found **no peer-reviewed metamorphic-testing study of JSON parsers**. Metamorphic relations for JSON appear only in tool and test harnesses (see Q4).
- I did not confirm the evaluation subjects of Nautilus, Gramatron, Superion, FormatFuzzer or ISLa in this session. None of the pages I read reported JSON-parser bugs from them. Treat "they were not evaluated on JSON parsers" as unverified.
- The fetched text of Crossy does not name all eight of its bug classes.
- JSONTestGen gives no per-category bug counts.

## Q3. Which techniques found bugs that coverage-guided byte-level fuzzing misses?

### Takeaway
Byte-level libFuzzer plus ASan catches memory errors in json-c quickly. OSS-Fuzz flagged a global-buffer-overflow in `json_tokener_parse_ex` the day after the change that introduced it.

The bug classes it structurally misses are:
- **resource and complexity bugs**: hash-flooding (CVE-2013-6371), found by a timing oracle; SlowFuzz and PerfFuzz show resource feedback beats coverage feedback
- **size-threshold bugs above 2 GB** (json-c CVE-2020-12762, yajl CVE-2022-24795)
- **semantic truncation and duplicate-key bugs**, which need value oracles
- **state carried across calls**: json-c's surrogate, number-exponent and reset-surrogate fixes
- **multi-byte magic and keyword comparisons**: pFuzzer, Redqueen/CmpLog and IJON address these

### Cited Findings
- Tokens and comparisons:
  - On cJSON, AFL missed all of `true`, `false` and `null`.
  - Across all subjects, AFL covered 5% of tokens longer than 3 characters, KLEE 7.5% and pFuzzer 52.5%.
  - [pFuzzer](https://core.ac.uk/download/249327981.pdf)
- Redqueen (NDSS 2019):
  - Input-to-state correspondence: trace comparison operands, colorize the input, and splice the compared values into the input. This solves multi-byte magic values and checksums.
  - 65 bugs and 16 CVEs.
  - Stated limitation: it fails when input is transformed before the comparison (base64, compression, **hash-map lookups**). JSON's `\uXXXX` and number decoding are such transforms.
  - [Redqueen paper](https://www.ndss-symposium.org/wp-content/uploads/2019/02/ndss2019_04A-2_Aschermann_paper.pdf)
- IJON (IEEE S&P 2020):
  - Small, usually one-line analyst annotations feed program state into the fuzzer.
  - It solved Super Mario Bros and hash-map lookups, and found issues that previously needed a custom grammar.
  - [IJON (CISPA)](https://cispa.de/en/research/publications/68621-ijon-exploring-deep-state-spaces-via-fuzzing)
- SlowFuzz (CCS 2017):
  - libFuzzer guided by instruction count.
  - On PHP's hash table, 64 insertions produced 20 collisions, about 31.25% of the worst case. Coverage-guided fuzzing never exceeded 8.
  - It mentions 2015 DoS attacks that used PHP JSON parsing into hash tables.
  - [SlowFuzz](https://ar5iv.arxiv.org/html/1708.08437)
- PerfFuzz (ISSTA 2018):
  - Tracks the maximum hit count per edge.
  - 1.9×–24.7× longer paths and 5×–69× hotter hot spots than SlowFuzz; 2×–18× hotter hot spots than AFL.
  - Found hash-collision chains (the wf word counter) and quadratic error-context printing in libxml2 on malformed input.
  - [PerfFuzz](https://wcventure.github.io/FuzzingPaper/Paper/ISSTA18_PerfFuzz.pdf)
- json-c CVE-2013-6371 and CVE-2013-6370 (found by Florian Weimer, Red Hat):
  - 6371: a weak hash function let "smallish JSON strings" cause quadratic timing.
  - 6370: printbuf used `int` lengths.
  - Both were fixed in commit 64e36901.
  - [oss-security 2014/04/09](https://openwall.com/lists/oss-security/2014/04/09/9)
- json-c CVE-2020-12762:
  - linkhash and printbuf were "limited to 2 GB in size due to a signed integer being used to track their current size". The overflow allows an out-of-bounds write on 64-bit systems.
  - Fixed in commit d07b910 (2020-05-04), with backports to 0.12–0.14.
  - [json-c commit d07b910](https://github.com/json-c/json-c/commit/d07b910)
  - Red Hat titles it "integer overflow and out-of-bounds write via a large JSON file" — [Red Hat bug 1835255](https://bugzilla.redhat.com/show_bug.cgi?id=1835255)
- `json_tokener_parse_ex()` still takes `int len` and rejects inputs over INT32_MAX — [json_tokener.h](https://github.com/json-c/json-c/blob/master/json_tokener.h)
- yajl CVE-2022-24795, the same class:
  - At about 2 GB of input, a 32-bit `need` in `yajl_buf.c` wraps to 0. A small chunk is allocated and then overwritten (heap corruption).
  - The 2.x branch uses `size_t`, which mostly avoids this on 64-bit builds but not on 32-bit ones.
  - [Ubuntu CVE-2022-24795](https://ubuntu.com/security/CVE-2022-24795)
- Python CVE-2020-10735:
  - `int()` on long decimal strings is quadratic; the page gives about 5 s for 1,000,000 digits.
  - Upstream added a digit limit, which the page calls a breaking change.
  - [Ubuntu CVE-2020-10735](https://ubuntu.com/security/CVE-2020-10735)
- OSS-Fuzz issue 23619, "json-c:tokener_parse_ex_fuzzer: Global-buffer-overflow in json_tokener_parse_ex":
  - READ of 4 bytes; libFuzzer + ASan; reported 2020-06-21.
  - [vulners OSSFUZZ-23619](https://vulners.com/ossfuzz/OSSFUZZ-23619)
  - Introduced by da76ee2 (2020-06-20, the merge of PR #633 "fix issue 616: support the surrogate pair in split file") and fixed by 36118b6 (2020-06-21), which rearranged the `\u` escape state handling — [vulert record](https://vulertsecurity.com/vuln-db/oss-fuzz-json-c-11807), [json-c commit 36118b6](https://github.com/json-c/json-c/commit/36118b681ea3b8e99735beee73cbd25a63e942cd)
- Later json-c fixes in the same family were semantic or state bugs rather than ASan crashes:
  - a68566b (2020-06-21): surrogate-pair parsing moved to extra states "to ensure that we correctly handle various cases of incremental parsing".
  - 6eac698 (2020-06-27): "Fix incremental parsing of invalid numbers with exponents, such as '0e+-' and '12.3E12E12'".
  - 2372e95 (2025-08-07, PR #893): "supplemental code points that look like high surrogates".
  - 7662139 (2026-10-10): "tokener: clear pending surrogate on reset", fixing #984. Without it, the next document can gain a replacement character or combine with an abandoned surrogate.
  - e0a1735 (2026-10-15): leak when inserting into the parent fails during OOM.
  - fd92d58 (2026-09-28): leak caused by `duplocale`.
  - Sources: [a68566b](https://github.com/json-c/json-c/commit/a68566b), [6eac698](https://github.com/json-c/json-c/commit/6eac698), [2372e95](https://github.com/json-c/json-c/commit/2372e95), [7662139](https://github.com/json-c/json-c/commit/7662139), [e0a1735](https://github.com/json-c/json-c/commit/e0a1735), [fd92d58](https://github.com/json-c/json-c/commit/fd92d58)
- The upstream OSS-Fuzz harness `fuzz/tokener_parse_ex_fuzzer.cc` makes one whole-buffer `json_tokener_parse_ex(tok, data, size)` call with default flags. It touches values and pretty-prints, with **no semantic oracle and no chunking**. json-c also has `json_object`, `json_array` and `json_pointer` fuzzers (added in 839fbe0, 2024-11) — [fuzz/ directory](https://github.com/json-c/json-c/tree/master/fuzz)
- Semantic oracles found what crash oracles cannot:
  - truncation and key collision, duplicate-key precedence, and silent large-number corruption — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)
  - normalized-tree differential results — [Crossy](https://www.mlsec.tu-berlin.de/docs/2024b-asiaccs.pdf)
- Fuzzing guides:
  - Trail of Bits covers dictionaries (claiming "10-100x faster bug discovery" for structured formats), `-max_len` at about 2× a realistic input, `-timeout`, FuzzedDataProvider, LPM and custom mutators. It does **not** cover `-use_value_profile` or oracles beyond sanitizers — [ToB Testing Handbook: libFuzzer](https://trailofbits.com/skills/libfuzzer/)
  - Chromium says coverage plateaus usually mean magic values or checksums, and that a seed corpus can raise coverage "by an order of magnitude" — [Chromium efficient fuzzing](https://chromium.googlesource.com/chromium/src/+/main/testing/libfuzzer/efficient_fuzzing.md)

### Inferences
- For a mature C tokener that has run on OSS-Fuzz for years with a dictionary, the most likely remaining finds are:
  - wrong values (truncation, numbers, Unicode)
  - wrong state across calls (surrogates, exponents, reset)
  - resource blow-ups
  - size-boundary arithmetic
  More byte-level crash fuzzing is less likely to pay off.
- json-c's bug history points to the incremental `\u` escape and surrogate state machine as the densest bug area: at least 5 fixes from 2020 to 2026.
- The Python reference differential has its own resource limit (CVE-2020-10735's digit cap). Very long integer literals will raise in Python, so they need special handling to avoid false positives.

### Gaps
- I found no JSON-specific measurement of `-use_value_profile` or CmpLog benefit.
- I could not access OSV.dev (proxy refused) to enumerate every json-c OSS-Fuzz issue. Only issue 23619 was confirmed.
- I did not find whether json-c's OSS-Fuzz project runs MSan.

## Q4. Are there studies of streaming or incremental parsers, or of error recovery and error-message/offset correctness?

### Takeaway
I found no peer-reviewed study of incremental or streaming JSON parser correctness, or of JSON error-offset accuracy. The best evidence is in test harnesses:
- Go's `encoding/json/jsontext` compares resumable decoding over short reads with whole-buffer decoding, and checks that validity is monotonic across option sets. It does **not** compare error offsets.
- tree-sitter fuzzes random edits plus undo with incremental reparse.
- json-c has its own `TEST_PARSE_CHUNKSIZE`.

Error-recovery research (Diekmann & Tratt) targets LR parsers and measures cascading errors. That metric does not carry over to json-c, which stops at the first error.

### Cited Findings
- Go `encoding/json/jsontext/fuzz_test.go`:
  - `FuzzResumableDecoder` decodes through `FaultyBuffer{MaxBytes: 8}` (random short reads) and through a `bytes.Reader`, for both `ReadToken` and `ReadValue`. Results and errors must be identical; error offsets are not compared.
  - `FuzzValueFormat` checks validity monotonicity across RFC 7159, 8259 and 7493 option sets ("invalid input per RFC 7159 implies invalid per RFC 8259"). It also requires `Compact` and `Indent` to succeed iff the input is valid and to preserve content modulo whitespace, and `Canonicalize` to succeed iff the input is RFC 7493-valid.
  - `FuzzCoder` re-encodes mixed token/value reads and requires the same token sequence.
  - [Go jsontext fuzz_test.go](https://tip.golang.org/src/encoding/json/jsontext/fuzz_test.go)
- tree-sitter CLI fuzzer:
  - Applies random edits, records inverse edits, reparses incrementally from the old tree, and checks size consistency and changed ranges.
  - It then undoes all edits, reparses incrementally again, and compares the result with the expected corpus output.
  - [tree-sitter fuzz.rs](https://docs.rs/tree-sitter-cli/latest/src/tree_sitter_cli/fuzz.rs.html)
- pFuzzer runs every candidate twice, with and without an appended random character, "because not all parsers perform an EOF check". Prefix acceptance and end-of-input handling are a known blind spot — [pFuzzer](https://core.ac.uk/download/249327981.pdf)
- json-c's own incremental test hooks:
  - 197e372 (2020-06-21) added an optional `$TEST_PARSE_CHUNKSIZE` for all `single_basic_parse` tests.
  - 5f3bf70 validates that setting.
  - Incremental bugs fixed since: a68566b (surrogates), 6eac698 (exponent numbers), 7662139 (reset leaves a pending surrogate).
  - [json-c commit 197e372](https://github.com/json-c/json-c/commit/197e372), [5f3bf70](https://github.com/json-c/json-c/commit/5f3bf70), [7662139](https://github.com/json-c/json-c/commit/7662139)
- Error offsets in json-c: commit 1d65898 (2026-06-21), "Issue #929: fix bad calculation of error offset when parsing in the apps/json_parse tool". That bug was in the demo tool's offset arithmetic, not in the tokener — [json-c commit 1d65898](https://github.com/json-c/json-c/commit/1d65898)
- json-c's docs define the incremental contract:
  - `json_tokener_continue` means more input is needed.
  - The caller must include the final `'\0'` at end of input.
  - Extra characters are found by comparing `json_tokener_get_parse_end()` with `len`.
  - The tokener keeps no internal buffer, so the caller must re-feed trailing characters.
  - [json_tokener.h](https://github.com/json-c/json-c/blob/master/json_tokener.h)
- Diekmann & Tratt, "Don't Panic! Better, Fewer, Syntax Errors for LR Parsers" (ECOOP 2020):
  - CPCT+ computes the complete set of minimum-cost repair sequences.
  - Evaluated on 200,000 real syntactically invalid Java files: 98.37% repaired within 0.5 s, and 435,812 error locations reported against 981,628 for panic mode (about 56% fewer cascading errors).
  - [arXiv 1804.07133](https://arxiv.org/abs/1804.07133)

### Inferences
- Taken together, Go, tree-sitter and json-c's own tests use chunk-invariance of *results and errors* as the standard incremental oracle. The team already covers this with split, bytewise and 3-way chunk relations.
- Possibly not covered:
  - **error-code and absolute-error-offset invariance across chunkings**, which Go does not check either
  - **flag-set monotonicity**, which Go does check
  - **prefix-closure and EOF-signal relations** (pFuzzer's blind spot, and the cause of JSONTestSuite's `lonely_*` artefacts for json-c)
- Error-recovery metrics such as cascading-error counts don't apply, because json-c has no recovery. The relevant oracle is precision of the *first* error: its code and offset.

### Gaps
- I found no academic study of error-message quality or offset accuracy for JSON parsers.
- I found no study comparing streaming JSON parsers such as yajl, json-c, jsmn and simdjson iterate_many under chunked input.

## Q5. Which concrete techniques or oracles has the team not yet tried, ranked for json-c's `json_tokener_parse_ex()`?

### Takeaway
Already covered, so not recommended:
- libFuzzer with ASan, UBSan and a dictionary
- split, bytewise and 3-way chunk relations
- wrap relations
- reset/reuse and multi-document relations
- comment insertion
- the JSONTestSuite-vs-Python strict differential
- the Python lenient-grammar model
- cross-version differential
- malloc fault injection
- gcov coverage and mutation analysis
- TSan, integer sanitizers and the unsigned-char build
- error-offset comparison against Python

The best untried bets target the areas where json-c's own history and the literature show bugs that byte-level fuzzing misses:
1. flag-lattice monotonicity
2. escape-equivalence relations that split inside escapes
3. state-at-chunk-boundary feedback (IJON-style)
4. a key-NUL semantic oracle
5. error and offset invariance under chunking, plus EOF-signal relations
6. resource oracles: amplification, chunk cost, hash flooding
7. tests at the INT32_MAX size boundary

### Cited Findings
Each recommendation below builds on the precedents already cited in Q1–Q4:
- Go `FuzzValueFormat` monotonicity — [Go jsontext fuzz_test.go](https://tip.golang.org/src/encoding/json/jsontext/fuzz_test.go)
- json-c surrogate and escape fixes — [a68566b](https://github.com/json-c/json-c/commit/a68566b), [2372e95](https://github.com/json-c/json-c/commit/2372e95), [7662139](https://github.com/json-c/json-c/commit/7662139)
- IJON — [IJON](https://cispa.de/en/research/publications/68621-ijon-exploring-deep-state-spaces-via-fuzzing)
- Key truncation via `strdup` — [json_tokener.c](https://github.com/json-c/json-c/blob/master/json_tokener.c)
- Bishop Fox truncation class — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)
- SlowFuzz and PerfFuzz — [SlowFuzz](https://ar5iv.arxiv.org/html/1708.08437), [PerfFuzz](https://wcventure.github.io/FuzzingPaper/Paper/ISSTA18_PerfFuzz.pdf)
- CVE-2013-6371 — [oss-security](https://openwall.com/lists/oss-security/2014/04/09/9)
- CVE-2020-12762 — [d07b910](https://github.com/json-c/json-c/commit/d07b910)
- yajl CVE-2022-24795 — [Ubuntu](https://ubuntu.com/security/CVE-2022-24795)
- Redqueen — [Redqueen](https://www.ndss-symposium.org/wp-content/uploads/2019/02/ndss2019_04A-2_Aschermann_paper.pdf)
- Grammar-Mutator — [README](https://github.com/AFLplusplus/Grammar-Mutator)
- LPM JSON proto — [Chromium json.proto](https://chromium.googlesource.com/chromium/src/+/ef290da170d481d1ef1c9ca4e11d156cfaf09afe/testing/libfuzzer/proto/json.proto)
- Gmutator — [TOSEM](https://www.doc.ic.ac.uk/~afd/papers/2024/TOSEM.pdf)
- Crossy — [Crossy](https://www.mlsec.tu-berlin.de/docs/2024b-asiaccs.pdf)
- Float test data from Nigel Tao's parse-number-fxx-test-data, mirrored at fastfloat/supplemental_test_files — [ecosyste.ms entry](https://awesome.ecosyste.ms/projects/github.com%2Ffastfloat%2Fsupplemental_test_files)
- json-c locale switching: `json_tokener_parse_ex` calls `uselocale(c_numeric_locale)` or, in the fallback, the process-global `setlocale(LC_NUMERIC, "C")` on every call, and restores it at exit (json_tokener.c around lines 335–381 and 1409–1411). There were locale leak fixes in fd92d58 and 653a12c — [json_tokener.c](https://github.com/json-c/json-c/blob/master/json_tokener.c), [fd92d58](https://github.com/json-c/json-c/commit/fd92d58)
- json-c's selectable string hash: `json_global_set_string_hash(JSON_C_STR_HASH_DFLT | JSON_C_STR_HASH_PERLLIKE)` — [linkhash.h](https://github.com/json-c/json-c/blob/master/linkhash.h)
- Object deletion is recursive: `json_object_object_delete` → `lh_table_free` → `json_object_lh_entry_free` → `json_object_put` on each child — [json_object.c](https://github.com/json-c/json-c/blob/master/json_object.c)
- Depth default is 32, and `json_tokener_new_ex(depth)` is configurable — [json_tokener.h](https://github.com/json-c/json-c/blob/master/json_tokener.h)

### Inferences
**Ranked list of untried techniques and oracles for json-c.** The ranking weighs expected yield given json-c's bug history against implementation cost.

1. **Flag-lattice monotonicity oracle** (after Go's `FuzzValueFormat`). Parse each fuzz input under all 8 combinations of `{STRICT, ALLOW_TRAILING_CHARS, VALIDATE_UTF8}`, and also under each chunking already in use. Assert all of the following:
   - accept(STRICT|F) ⇒ accept(F), with `json_object_equal` values
   - accept(VALIDATE_UTF8|F) ⇒ accept(F), with the same value
   - ALLOW_TRAILING_CHARS changes only trailing-data handling, never the parsed value
   - error codes are consistent: a stricter flag set never succeeds where a laxer one errors
   Put the flags into the libFuzzer input, using the bitmask trick from OSS-Fuzz's jsoncpp proto fuzzer, so that coverage feedback reaches the flag-gated branches.
2. **Escape-equivalence metamorphic relation with splits inside escapes.** Rewrite string characters to equivalent forms and expect equal objects:
   - any character → `\uXXXX` (upper and lower hex)
   - a non-BMP character → its surrogate-pair escapes
   - `/` → `\/`
   - raw UTF-8 → its escaped form
   Then feed the result with chunk boundaries forced at every offset inside `😀`. Also try reset or abandoned documents between a high and a low surrogate. This aims directly at the bug-dense surrogate state (a68566b, 36118b6, 2372e95, 7662139).
3. **IJON-style state-at-boundary feedback.** At each `json_tokener_parse_ex` return with `json_tokener_continue`, hash this tuple into the coverage map (e.g. via an `IJON_SET`-like annotation or a libFuzzer extra counter):
   - `tok->state`, `saved_state`, `depth`
   - `st_pos`, pending high surrogate, quote char, `is_double`
   - the last character class
   Pair it with a FuzzedDataProvider-chosen split vector, so the fuzzer seeks new *(state at chunk boundary)* combinations rather than only new edges. This is the class behind 6eac698, a68566b and 7662139.
4. **Key byte-length and NUL semantic oracle.** For every object member, compare json-c's key with the reference model's decoded key by byte length. Keys are built with `strdup`, so `{"a\u0000b":1}` gives key `"a"`, and `{"a\u0000x":1,"a\u0000y":2}` should collapse to one member (last wins). Add duplicate-key-precedence and member-count checks (the Bishop Fox classes). Then decide whether json-c should reject NUL in keys under STRICT or document the behaviour. If the existing Python differential already compares member counts and key lengths, this is covered.
5. **Error-identity and offset invariance under chunking, plus EOF-signal relations.** Strengthen the existing chunk relations with these checks:
   - **Same error at the same position.** For any chunking, the first fatal error must have the same `json_tokener_error` code and the same absolute offset: the sum of fed lengths plus `json_tokener_get_parse_end()`. Go's resumable fuzzer explicitly does not check offsets.
   - **Prefix-closure.** Every proper prefix of an accepted document must return `json_tokener_continue`, never a fatal error or a completed object. The exception is top-level scalars, which complete only when the final `'\0'` is included.
   - **EOF signalling.** `len` and `len+1` (including the `'\0'`) must differ only in whether a top-level number or literal completes.
6. **Resource-usage oracles** (SlowFuzz/PerfFuzz style, CVE-2013-6371 class). Three checks:
   - **(a) Amplification bounds.** Count malloc bytes and calls and instructions, using a counting allocator or `perf stat`. Flag inputs with more than k bytes allocated per input byte, or with superlinear growth when the input is scaled ×2 and ×4.
   - **(b) Chunk-cost ratio.** Require cost(1-byte chunks) / cost(whole) ≤ a constant, which catches rescanning or `strlen` on each call.
   - **(c) Hash-flood regression.** Build many keys that collide under both `JSON_C_STR_HASH_DFLT` and `PERLLIKE`, then assert near-linear parse time.
   Optionally run a PerfFuzz-style max-hit-count feedback build.
7. **Size-boundary scale tests (CVE-2020-12762 and yajl CVE-2022-24795 class).** Stream inputs incrementally so they don't all sit in memory:
   - single string, key or number tokens of 2^31 ± k bytes
   - total input over INT32_MAX
   - more than 2^31 array elements or object members where feasible
   Do this on 64-bit and on `-m32` builds, and check printbuf, linkhash and arraylist growth for wraparound. Fuzzers never reach these sizes under `-max_len`.
8. **Number semantic oracles.** Three parts:
   - **Correct rounding.** Wrap each line of Nigel Tao's parse-number-fxx test data in `[...]` and compare the bits of `json_object_get_double()` with the expected value.
   - **int64 boundaries.** Check `json_object_get_int64()` clamping and `errno=ERANGE` semantics against exact big-integer arithmetic. Cover `INT64_MIN`/`MAX` ±1 and the JSONTestSuite `test_transform/number_*` files.
   - **Equivalent spellings.** `1E2`, `1e+2`, `100.0` and `-0` must give the same double where the type allows.
   Exclude Python-side digit-limit cases (CVE-2020-10735).
9. **CmpLog/Redqueen or `-use_value_profile=1`.** An AFL++ `-c` CmpLog build or libFuzzer value profile is cheap and helps solve multi-byte comparisons: `NaN`, `Infinity`, `true`/`false`/`null` with casing, hex digits, and depth and `st_pos` counters. Redqueen's own limitation means it will not help through `\u` decoding or hash lookups.
10. **Environment-invariance relations.** Two variants:
    - **Locale.** Parse a number-heavy corpus after `setlocale(LC_ALL, "de_DE.UTF-8")` (decimal comma) and in a build forced onto the `HAVE_SETLOCALE` fallback. The results must equal the C locale, and the caller's locale must be restored afterwards. Run concurrent parses under TSan in the fallback build, because `setlocale` is process-global.
    - **Hash function.** Parse under `JSON_C_STR_HASH_DFLT` vs `PERLLIKE`. Trees and key iteration order must be identical.
11. **Depth sweep and deep-teardown stack oracle** (Seriot's crash class 1).
    - For `json_tokener_new_ex(d)` with d ∈ {1, 2, 31, 32, 33, 1e4, 1e6}, nesting d must be accepted and d+1 rejected with `json_tokener_error_depth` at the right offset.
    - With very large d, run `json_object_put`, `json_object_equal` and `to_json_string` under a reduced `ulimit -s`. Object deletion recurses through children, so stack exhaustion is plausible, though unverified.
12. **Structure-aware generation**, with modest expected yield since Crossy found 0 differences and Gmutator found nothing in simdjson. Options:
    - AFL++ Grammar-Mutator with `grammars/json.json`, extended with json-c's lenient extensions (comments, trailing commas, NaN/Infinity, single quotes)
    - LPM using Chromium's `json.proto`, extended with `flags` and `split_points` fields
    - Gmutator-style mutated grammars for accept-invalid testing under STRICT
13. **MSan and/or Valgrind memcheck runs** over the corpus and the chunk relations. These catch uninitialized reads, which ASan, UBSan and TSan do not detect. MSan is feasible because json-c has few dependencies.
14. **N-version differential against other C streaming parsers**, at the lowest rank. Use yajl, which is also chunk-fed, plus jansson and cJSON with consensus normalization, or run the public Crossy harness against json-c master. Crossy already reported 0 json-c differences against yajl and jansson, so expect little beyond the leniency classes.

### Gaps
- I did not check whether the team's existing split relations already compare error codes and absolute offsets, or whether the Python differential compares key byte lengths. If they do, items 4 and 5 shrink to small additions.
- I did not run any of these oracles. All rankings are judgments from the literature and json-c's history, not measured yields.
- Stack exhaustion with a huge depth (item 11) and json-c's behaviour on colliding keys under the current hash (item 6c) are hypotheses that need testing.
