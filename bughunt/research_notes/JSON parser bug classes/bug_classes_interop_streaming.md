# Known bug classes in JSON parsers: interoperability, incremental/streaming parsers, C memory safety, and lenient extensions (for testing json-c `json_tokener_parse_ex()`)

Scope: parsing only (text to object). Serializer-only CVEs are named once, flagged "out of scope", and not expanded.

**Already covered by the team.** These are not repeated as new classes. Where a finding below touches one, it is marked "(already covered)":
- Split and bytewise chunk equivalence
- Unterminated comments at EOF
- Block comments with even star runs
- UTF-8 validation lookahead past a value
- STRICT accepting single-quoted keys
- OOM error codes
- Quadratic time for long numbers fed in chunks
- Comment buffering memory
- Locale data race
- NUL in object keys
- Depth-limit BVA
- JSONTestSuite strict-mode differential against Python

Class IDs: IC = interoperability, SC = streaming/incremental, MC = memory-safety or resource exhaustion, LC = lenient mode.

---

## Q1. Which interoperability bug classes are documented (duplicate keys, key collision via truncation or invalid Unicode, comment truncation, numbers, BOM, NUL, lone surrogates, escaped vs raw characters)?

### Takeaway
The documented interoperability classes are:
- Which duplicate key wins, or whether both are kept
- Keys that collide after a parser drops or rewrites characters (lone surrogates, a stray backslash, CR, quotes, case-folding)
- Comments that hide or reveal members
- Inconsistent handling of huge numbers, overflow and `-0`
- Accepting trailing garbage
- Divergent treatment of lone surrogates, raw UTF-8 surrogates and invalid UTF-8

Neither Bishop Fox nor Seriot tested json-c. Every class below therefore needs a json-c-specific expected behaviour pinned down, ideally the same for whole-buffer and chunked feeding.

### Cited Findings

**IC-1 Duplicate-key precedence (first wins vs last wins)**
- Minimal input: `{"test": 1, "test": 2}`. These parsers keep the first value: Go jsonparser, Go gojay, C++ RapidJSON, Java json-iterator, Elixir Jason, Elixir Poison, Erlang jsone. Others keep the last. RFC 8259 calls the behaviour "unpredictable". — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)
- Go `encoding/json` keeps the last value. It resolves duplicates after case-folding, so `{"action": "Action1", "aCtIoN": "Action2"}` yields `Action2`. — [Trail of Bits](https://blog.trailofbits.com/2025/06/17/unexpected-security-footguns-in-gos-parsers/)
- A real exploit came from this class. In Apache CouchDB CVE-2017-12635, the JavaScript and Erlang parsers read the same duplicate `roles` key differently: one saw `"roles": []`, the other `["_admin"]`. The result was privilege escalation leading to RCE. — [Seriot, Parsing JSON is a Minefield](https://seriot.ch/projects/parsing_json.html); [Trail of Bits](https://blog.trailofbits.com/2025/06/17/unexpected-security-footguns-in-gos-parsers/)

**IC-2 Duplicates kept as two members in the DOM; lookup and re-serialization disagree**
- cJSON, R and Lua JSON keep `{"a":1,"a":2}` as two entries. cJSON and R also keep `{"a":0,"a":-0}` as `{"a":0,"a":0}`. — [Seriot](https://seriot.ch/projects/parsing_json.html)
- Java json-iterator: `obj["test"]` returns 1, but `toString()` gives `{"test": 2}`. RapidJSON's DOM keeps both members and re-serializes `{"test": 1, "test": 2}`. — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)
- Caveat: my extraction of the same article says RapidJSON's `obj["test"]` returns 2, yet the article also lists RapidJSON as first-key-wins. Treat the exact lookup value as unverified.

**IC-3 Key collision because a character is truncated, dropped or rewritten**
Bishop Fox payloads, where two distinct keys collapse into one and the second value overwrites the first — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities):
- `{"test": 1, "test\ud800": 2}`: Python ujson and PHP json5. ujson decodes it as `{u'test': 2}`.
- `{"test": 1, "test\` + raw CR byte `": 2}`: Rust json5 and PHP json5.
- `{"test": 1, "test"": 2}` (stray quote): Ruby simdjson.
- `{"test": 1, "te\st": 2}` (invalid escape `\s` silently dropped): C# Jayrock, Ruby stdlib ext and pure, JavaScript json5, Rust json5.

Related cases:
- ujson CVE-2022-31116: escaped surrogates that are not part of a valid pair were decoded incorrectly. Strings were corrupted, and dictionary keys could collide so that values were overwritten. Fixed in 5.4.0, which preserves lone surrogates the way Python's stdlib does. Fix commit 67ec071. — [OSV CVE-2022-31116](https://osv.dev/vulnerability/CVE-2022-31116)
- Case and Unicode folding collisions in Go: `{"aKtionſ": ...}` matches a field tagged `aktions`. Two non-ASCII characters fold to ASCII: `ſ` (U+017F) matches `s`, and the Kelvin sign (U+212A) matches `k`. — [Trail of Bits](https://blog.trailofbits.com/2025/06/17/unexpected-security-footguns-in-gos-parsers/)

**IC-4 Lone surrogates and raw UTF-8-encoded surrogates handled divergently**
All results from [Seriot](https://seriot.ch/projects/parsing_json.html):
- `["\uD800"]`: Python keeps the escape; Go and JavaScript substitute U+FFFD.
- Raw `ED A0 80` (U+D800 encoded in UTF-8, which is invalid UTF-8): cJSON, R rjson, jsonlite, Lua JSON and dkjson pass the bytes through unchanged. Go and JavaScript produce three U+FFFD characters. Python 3 raises `UnicodeDecodeError`.
- `["\uD800\uD800"]`: jsonlite yields `"U00010000"` and Ruby yields the bytes `F0 90 80 80`. Both are bogus combinations of two high surrogates.

**IC-5 Surrogate-range detection bug on full code points (json-c itself, fixed in 0.19)**
- json-c PR #893, "Fix bug involving supplemental code points that look like high surrogates". The macros were `IS_HIGH_SURROGATE(uc) (((uc)&0xFC00) == 0xD800)` and the matching low-surrogate one. The 16-bit mask was applied to a 32-bit code point, so a combined supplementary code point such as U+1DA87 (`"𝪇"`) was mistaken for a surrogate. The mask was widened to `0xFFFFFC00`.
- The PR added tests for the whole-buffer case, for a truncated `"[9,'\uDAD"`, and for the same character split across three chunks: `"\uD836`, then `\uDE87`, then `"`. — [json-c commit 2372e95 (mirror)](https://ide-kyxt.pcl.ac.cn/jdk-build-libs/json-c/commit/2372e9518e6ba95b48d37ec162bc7d93b297b52f)
- Earlier json-c surrogate fixes, from the [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog):
  - 0.13: "Issue #275: fix out of bounds read when handling unicode surrogate pairs"
  - 0.15: "#616 - Parsing of surrogate pairs in unicode escapes now properly handles incremental parsing"

**IC-6 Malformed escape after a high surrogate causes an assertion abort (yajl / yajl-ruby, CVE-2017-16516)**
- Inputs: `{"e":{"\uD800\\DC00":"a"}}`, `{"\uDBFF\\u "@: "`, and the smallest reproducer `"\uD800\\1"` (any final character works).
- Effect: SIGABRT from assertions in `yajl_string_decode` ("this should never happen") and `hexToDigit` (non-hex character). The decoder assumed that a high surrogate is always followed by a valid `\uXXXX` low surrogate. — [yajl-ruby issue #176](https://github.com/brianmario/yajl-ruby/issues/176); [OSV CVE-2017-16516](https://osv.dev/vulnerability/CVE-2017-16516)

**IC-7 Invalid UTF-8 accepted or crashing**
- Go `json.Valid` reports binary garbage inside quotes as valid JSON. — [golang/go#58517](https://golang.org/issue/58517)
- SBJSON (Obj-C) aborts with an uncaught exception on a raw `0xFF` byte in a string. — [Seriot](https://seriot.ch/projects/parsing_json.html)
- (UTF-8 validation lookahead past a value: already covered.)

**IC-8 NUL inside string values (escaped `\u0000`)**
- `["A\u0000B"]`: JSONKit and cJSON reject it; Freddy silently truncates to `["A"]`. — [Seriot](https://seriot.ch/projects/parsing_json.html)
- (NUL in object keys: already covered.)

**IC-9 Comment truncation and unexpected comment support**
- Payload: `{"description": "Comment support", "test": 1, "extra": "a"/*, "test": 2, "extra2": "b"*/}`. GSON yields `test: 1`; Ruby simdjson yields `test: 2` and `extra2: "b"`.
- Payload: `{"description": "Duplicate with comments", "test": 2, "extra": /*, "test": 1, "extra2": */}`. Go gojay yields `extra = ""`; json-iterator yields `extra = "/*"`, `extra2 = "*/"` and `test = 1`.
- These parsers accept comments without being asked to: Ruby stdlib ext and pure, Ruby oj, Ruby Yajl, Go jsonparser, Go gojay, GSON, Genson, fastjson, Newtonsoft.Json, Utf8Json, Jayrock, Manatee. — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)

**IC-10 Number representation: huge integers, huge exponents, precision, `-0`**
- A 96-digit run of `9`s decodes as `9.999999999999999e95`, `1E+96`, `0` or `9223372036854775807` depending on the parser. PHP jsonlint clamps to INT64_MAX. Newtonsoft.Json returns a string. — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)
- `1.0e4096` decodes as `0` in Go jsonparser (no error check), `3.0e14159265358979323846` in Ruby oj, and `9.218868437227405E+18` in C# Utf8Json. Others give Infinity, rendered variously as `"Infinity"`, `"Inf"` or `"+Infinity"`. In PHP, `0 == "Infinity"` is true, which enables type juggling. — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)
- From [Seriot](https://seriot.ch/projects/parsing_json.html):
  - cJSON parses `10000000000000000999` as a double, giving `10000000000000002048`.
  - `1.000000000000000005` keeps full precision only in Rust json.
  - `1E-999` becomes the string `"1E-999"` in Freddy.
  - `123123e100000` is rejected by Apple JSONSerialization.
  - `-0` is preserved by JSONKit, Go, JavaScript and Lua.
- json-c number-related fixes, from the [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog):
  - 0.13: "Tighten the number parsing algorithm to raise errors instead of truncating the results"
  - 0.15: "Strict mode now rejects missing exponents ("0e")"
  - 0.17: "When parsing with JSON_TOKENER_STRICT set, integer overflow/underflow now result in a json_tokener_error_parse_number"
  - 0.15: "#602 - Fix json_parse_uint64() internal error checking"
- RapidJSON commit d621dc9, "Fix parsing 0.184467440737095516159 with kParseFullPrecisionFlag": a full-precision path mis-parsed a long fraction whose digits look like UINT64_MAX. — [RapidJSON log (Chromium mirror)](https://chromium.googlesource.com/external/github.com/Tencent/rapidjson/+log)
- jsoncpp changed its overflow behaviour to "Parse large floats as infinity (#1349) (#1353)". I saw only the commit title. — [jsoncpp commit (Pigweed mirror)](https://pigweed.googlesource.com/third_party/github/open-source-parsers/jsoncpp/+/2d55c7445ffedf30db62231f223137ef02e611a9)

**IC-11 Byte order mark**
- RFC 8259 §8.1: parsers "MAY ignore the presence of a byte order mark rather than treating it as an error". An erratum asking to let a BOM signal an alternate encoding was rejected (EID 6208). The spec therefore allows both accept and reject, which is itself a differential. — [RFC Errata 6208](https://www.rfc-editor.org/errata/eid6208)
- Seriot gives no per-parser BOM results. He notes only that STJSON errors on UTF-16 and UTF-32 BOMs. — [Seriot](https://seriot.ch/projects/parsing_json.html)

**IC-12 Trailing garbage after the top-level value**
- `{"test": 1}=` sent as `application/x-www-form-urlencoded` enables form-based CSRF against services that parse any body as JSON. — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)
- SBJSON accepts `[]x`. — [Seriot](https://seriot.ch/projects/parsing_json.html)
- Go's `json.NewDecoder(r).Decode` accepts trailing garbage while `json.Unmarshal` rejects it (golang/go#36225, no planned fix). — [Trail of Bits](https://blog.trailofbits.com/2025/06/17/unexpected-security-footguns-in-gos-parsers/)
- json-c added an opt-in `JSON_TOKENER_ALLOW_TRAILING_CHARS` flag in 0.15. — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog)

**IC-13 Grammar-edge differentials (whitespace set, `[1.]`, DEL)**
- json-c 0.16: "Neither vertical tab nor formfeed are considered whitespace per the JSON spec". — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog)
- From [Seriot](https://seriot.ch/projects/parsing_json.html):
  - TouchJSON treats form feed as whitespace.
  - `[1.]` is accepted by TouchJSON, PHP, R rjson, json-rust, JSON.sh, jsmn and Lua dkjson.
  - JSON_Checker accepted `[1.]` and `[0.e1]` but rejected the valid `[0e1]`.
  - JSON.sh rejects a raw DEL (0x7F) in a string because its `:cntrl:` regex matches 0x7F.
- json-c 0.19: "Issue #867 - also disallow control characters in keys in JSON_TOKENER_STRICT mode", which means keys and values were previously checked differently. — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog)

### Inferences
- **IC-1/IC-2 for json-c.** Assert one documented outcome for `{"a":1,"a":2}`: last wins via `json_object_object_add` (to verify), plus a stable `json_object_object_length`. Assert the same outcome for every chunk split and in STRICT mode. Also test `{"a":0,"a":-0}` to check whether `-0` survives as a double and whether the type changes.
- **IC-3 for json-c.** Each of these must yield two distinct keys, or a parse error in STRICT mode. None may silently merge:
  - `{"test":1,"test\ud800":2}`
  - `{"test":1,"test\udc00":2}`
  - `{"test":1,"te\st":2}` (should be a parse error: `\s` is not a valid escape)
  - `{"test":1,"test\` + raw CR `":2}`
  - `{"test":1,"test"":2}`
  - Invalid-UTF-8 variants such as `"test\xff"` and `"test\xfe"`, with and without `JSON_TOKENER_VALIDATE_UTF8`
  If json-c maps lone surrogates or invalid bytes to U+FFFD (to verify), two different inputs can collide on one key. Write a test for that collision in particular.
- **IC-5 regression set.** Use code points whose low 16 bits fall in D800–DFFF; these hit the pre-0.19 mask bug. Feed each whole and split at every byte:

  | Escape pair | Code point |
  |---|---|
  | `𝠀` | U+1D800 |
  | `𝪇` | U+1DA87 |
  | `𝰀` | U+1DC00 |
  | `𭠀` | U+2D800 |
  | `􍠀` | U+10D800 |
  | `􏿿` | U+10FFFF |

  The code points were computed with the standard UTF-16 formula.
- **IC-6 for json-c.** Parse these whole and split at every byte. Each must either error cleanly or follow a documented replacement policy. None may abort, read out of bounds, or emit a merged code point:
  - `"\uD800\\1"`
  - `"\uD800\n"`
  - `"\uD800"` at EOF
  - `"\uD800A"`
  - `"\uD800\uD800"`
  - `"\uDC00"`
  - `"\uD800\u"`
  - `"\uD800\uDC0"` followed by EOF
- **IC-10 for json-c.** Run these in both default and STRICT mode, and check type, value and error code:
  - `9223372036854775807`, `9223372036854775808`, `-9223372036854775808`, `-9223372036854775809`
  - `18446744073709551615`, `18446744073709551616`
  - a 96-digit run of 9s
  - `1.0e4096`, `1e-999`, `-0`, `-0.0`, `0e`, `0e+`, `1E400`
  The 0.17 note means default mode still clamps or saturates on overflow. That is an interop decision to document, not necessarily a bug.
- **IC-11 for json-c.** Decide and test `EF BB BF {}` (UTF-8 BOM), a BOM in the middle of the input, and a BOM split across chunks (`EF` | `BB BF {}`). I found no source on json-c's BOM behaviour.

### Gaps
- Neither the Bishop Fox nor the Seriot study included json-c. I found no published json-c interop results.
- I did not fetch the Bishop Fox labs repository (`BishopFox/json-interop-vuln-labs`); I saw only that it exists.
- I found no per-parser BOM results in any source I could read.
- RapidJSON's duplicate-key lookup value is inconsistent in my extraction of the Bishop Fox article (see IC-2).

---

## Q2. What bug classes are specific to incremental, streaming or resumable parsers?

### Takeaway
The recurring streaming-only classes are:
- Limits and validation checked only when a token completes, so a token left open across chunks bypasses them
- Nesting, number or escape state not carried across a chunk boundary
- A truncated final chunk triggering reads past the end of the buffer
- Ambiguous termination of top-level scalars at EOF
- Wrong offsets or positions after EOF or a resume
- Wrappers that loop forever on "need more input"
- Leaks on abandon or error paths
- Line-oriented framing that splits inside strings

json-c's own ChangeLog shows three of these classes were real bugs in `json_tokener`: surrogate pairs (#616), numbers with exponents, and top-level numbers.

### Cited Findings

**SC-1 Limit enforced only at token completion, bypassed by chunked accumulation (Jackson async parser)**
- GHSA-72hv-8253-57qq (CVE-2026-18401): the non-blocking parser did not enforce `maxNumberLength` (default 1000). Its number path finalized through `_valueComplete()` instead of `resetInt()`/`resetFloat()`, which run the length checks. A PoC showed the sync parser rejecting a 5,000-digit number that the async parser accepted. The impact is unbounded text-buffer growth, plus quadratic BigInteger/BigDecimal conversion. Fixed in 2.18.6, 2.21.1 and 3.1.0. — [OSV GHSA-72hv-8253-57qq](https://api.osv.dev/v1/vulns/GHSA-72hv-8253-57qq)
- GHSA-r7wm-3cxj-wff9 shows the first fix was incomplete:
  - Integer digits fed in chunks leave the parser in `MINOR_NUMBER_INTEGER_DIGITS`, returning `NOT_AVAILABLE`.
  - `validateIntegerLength` ran only on terminating paths (`.`, exponent, whitespace, EOF on a complete value).
  - A PoC fed 16 KiB of digits 600 times and got about 9.83 MB accepted against a 1,000-digit limit. The value was rejected only when a terminator finally arrived.
  - The fraction path had been fixed correctly in 2.18.6; the integer path was not.
  - Fixed in 2.18.8 and 2.21.2 by validating before every mid-token `NOT_AVAILABLE` return. — [SecureLayer7 analysis](https://securelayer7.net/lab/jackson-core-async-parser-maxnumberlength-bypass-chunked-digits); [GHSA-r7wm-3cxj-wff9](https://github.com/FasterXML/jackson-core/security/advisories/GHSA-r7wm-3cxj-wff9)
- (Quadratic time for long numbers fed in chunks is already covered. The new class here is a limit or validation that never runs while the token is still open.)

**SC-2 Container nesting state not kept across calls (jsmn)**
- jsmn issue #183: a streaming user reset with `jsmn_init()` per 8 KiB chunk to keep memory O(1). Parsing then broke: a `]` arriving in a later chunk was treated as corrupt, and parsing stopped before later arrays. jsmn needs the whole token array to persist across calls, which costs O(n) memory. A chunk boundary inside a container looks the same as malformed input. The issue is still open. — [jsmn #183](https://www.github.com/zserge/jsmn/issues/183)

**SC-3 Multi-byte UTF-8 split across chunks (JS streaming parsers)**
- `jsonparse` (used by JSONStream) and `clarinet` decoded each Buffer chunk to a string separately. A multi-byte character split across a chunk boundary became U+FFFD, sometimes with a parse error. The output was non-deterministic for Russian, Arabic and Chinese text. The fix is to buffer incomplete trailing bytes. — [streaming-jsonparsers-utf8-bug-demo](https://github.com/jlank/streaming-jsonparsers-utf8-bug-demo)
- Search results also show clarinet's test suite has a dedicated `utf8-chunks.js` test (title only). — [clarinet test (mirror)](https://huggingface.co/spaces/reisarod/gradio/blob/main/node_modules/clarinet/test/utf8-chunks.js)
- (Generic split and bytewise equivalence: already covered.)

**SC-4 Escape and surrogate state split across chunks (json-c, fixed)**
- json-c 0.15: "#616 - Parsing of surrogate pairs in unicode escapes now properly handles incremental parsing". — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog)
- json-c 0.19 (PR #893): the regression test feeds `"\uD836`, `\uDE87` and `"` as separate chunks. The first two return continue and the third returns success. — [json-c commit 2372e95](https://ide-kyxt.pcl.ac.cn/jdk-build-libs/json-c/commit/2372e9518e6ba95b48d37ec162bc7d93b297b52f)

**SC-5 Numbers and top-level scalars at chunk or EOF boundaries**
- json-c 0.15 included two fixes in this area — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog):
  - "Fix incremental parsing of numbers, especially those with exponents".
  - "Successfully return number objects at the top level even when they are followed by a "-", "." or "e"". This means a top-level number followed by a character that could continue a number was previously mishandled.
- yajl needs `yajl_complete_parse()` to finish. EPICS fixed a leak ("Fixes leak when link parses OK but JSON errors follow") by adding the missing `yajl_complete_parse()` calls; its regression test includes the unterminated `{"z":{"good":6}`. — [EPICS commit cd14e2e](https://gitea.psi.ch/epics/epics-base/commit/cd14e2ee9fcd7faffd9b7134c762c67153807a03)

**SC-6 Truncated input: lookahead or SIMD reads past the end of the buffer**
- simdjson CVE-2026-88358: a truncated document whose last structural character closes a nested array or object makes `json_iterator::walk_document()` read `buf[len]`, a 1-byte heap out-of-bounds read. The path is `dom::parser::parse_unpadded()`. 4.6.1 is named as affected; Fedora ships 5.0.1. — [Red Hat Bugzilla 2543058](https://bugzilla.redhat.com/show_bug.cgi?id=2543058)
- Rust simd-json CVE-2019-15550: 32-byte SIMD loads near the end of a string read past the input, and can fault when the buffer ends at a page boundary. Fixed in 0.1.15 by copying the final read into a padding buffer. — [GHSA-gwfj-pw2x-h6c2](https://github.com/advisories/GHSA-gwfj-pw2x-h6c2)
- cJSON CVE-2023-53154: `{"1":1,` with no trailing newline, passed to `cJSON_ParseWithLength`, causes a heap over-read in `parse_string`. Fixed in 1.7.18 (commit acc7623). — [OSV CVE-2023-53154](https://osv.dev/vulnerability/CVE-2023-53154)
- cJSON CVE-2016-10749: a string that begins with `"` and ends with `\` causes a buffer over-read in `parse_string`. — [OSV CVE-2016-10749](https://osv.dev/vulnerability/CVE-2016-10749)
- (UTF-8 validation lookahead past a value: already covered.)

**SC-7 Multi-document streams: batch boundaries, truncated tail, separators (simdjson `iterate_many`/`parse_many`)**
All from the [simdjson iterate_many docs](https://simdjson.github.io/simdjson/md_doc_iterate_many.html):
- `batch_size` "has to be at least as big as the biggest document".
- The library "may truncate documents at the very end of the stream". `truncated_bytes()` is meaningful only after iterating all documents.
- Undelimited concatenation is recognized only for objects and arrays, e.g. `[1,2]{"32":1}`. Anything other than whitespace is parsed as a document.
- Comma-separated mode disables threading and ignores `batch_size`.

**SC-8 Trailing data and multi-value handling in stream decoders**
- Go `Decoder.Decode` accepts trailing garbage that `Unmarshal` rejects (golang/go#36225). — [Trail of Bits](https://blog.trailofbits.com/2025/06/17/unexpected-security-footguns-in-gos-parsers/)
- ijson 2.5 fixed "a bug in `multiple_values` support in the C backend (#8)". — [ijson CHANGELOG](https://github.com/ICRAR/ijson/blob/v3.2.3/CHANGELOG.md)

**SC-9 Wrong offset or position after EOF or resume**
- Go commit "encoding/json: fix Decoder.InputOffset regression after EOF": "After Decoder.Token reports EOF, the Decoder.InputOffset should include any upcoming colons or commas". The regression appeared when v1 was reimplemented on v2 (Fixes #79919). — [Go commit 7ecf1df](https://go.googlesource.com/go/+/7ecf1dff692a62278bdecc8e1223455fcff66ec9)

**SC-10 Wrappers or drivers that mishandle "need more input"**
- jackson-core #1144: `FilteringParserDelegate` over a non-blocking parser loops forever. It does not forward `canParseAsync()` or `getNonBlockingInputFeeder()`, and it treats `JsonToken.NOT_AVAILABLE` as a scalar, so it keeps calling `nextToken()`. Closed by PR #1417 in April 2025. — [jackson-core #1144](https://github.com/FasterXML/jackson-core/issues/1144)
- serde_json `StreamDeserializer`: a forum thread on stepping past errors implies that a naive loop can get the same error back forever. — [Rust users forum](https://users.rust-lang.org/t/step-past-errors-in-serde-json-streamdeserializer/84228/10)

**SC-11 Leaks or crashes on error and abandon paths of incremental wrappers**
From the [ijson CHANGELOG](https://github.com/ICRAR/ijson/blob/v3.2.3/CHANGELOG.md):
- 3.2.1: a leak in the yajl2_c backend "triggered only when the underlying `yajl` functions reported a failure (#97)".
- 3.0.2: a leak in the yajl2_c `parse` (#28).
- 3.0.3: a segfault caused by the 3.0.2 fix.
- 3.0.4: crashes and wrong results with an empty member name, `{"": 1}`.
- 3.1.4: the Python backend "now raises errors on incomplete JSON", which it previously missed.

Also: yajl CVE-2023-33460 is titled "Memory leak in yajl_tree_parse function". I could not read the patch itself. — [Red Hat Bugzilla 2221249](https://bugzilla.redhat.com/show_bug.cgi?id=2221249)

**SC-12 Line framing that splits inside a JSON string (JSON Lines readers)**
- Several reports describe JSONL readers that split records on U+2028 or U+2029, which are valid raw characters inside JSON strings. The result is truncation or "Unterminated string" errors. Reports seen: Node 24+ `readline`, Python `str.splitlines`, smart_open from S3, and an Agent SDK. I saw only the titles in search results; the pages were not read. — e.g. [smart_open u2028 report](https://lightrun.com/answers/rare-technologies-smart_open-line-splitting-on-u2028-from-s3), [Python splitlines report](https://kingy.ai/wp-content/plugins/kingy-workbench/assets/kingy-fix-008-report-v1.html)

### Inferences
- **SC-1 for json-c.** List every check json-c performs at token completion, then test each with the token held open across many `json_tokener_continue` calls. Candidates:
  - Integer overflow detection in STRICT (0.17)
  - The UTF-8 validation flag
  - Control-character checks in keys (0.19 #867)
  - The depth check
  - Literal validity (`tru` + `x`)
  Example: in STRICT mode, feed `9223372036854775808` one byte per call; it must still return `json_tokener_error_parse_number`. Feed `"a` + a raw control byte + `b"` split around the control byte; it must be rejected the same way as the whole-buffer case.
- **SC-5 for json-c.** The 0.15 fix implies a regression set of top-level inputs fed as one chunk, followed by a zero-length call or a terminator:
  - `1-`, `1.`, `1e`, `1e+`, `-`, `0e`, `-0`, `1.5e3`
  - `-Infinity` split as `-Inf` | `inity`
  - `NaN` split as `Na` | `N`
  - `tr` | `ue`, `nul` | `l`
  In each case, check that `json_tokener_continue` is returned while the number is still open and the final value or error once input ends. Also check that `json_tokener_get_parse_end()` is correct.
- **SC-6 for json-c.** Run every truncated prefix of a corpus under ASan, in exact-size `malloc` buffers with no NUL terminator, passing an explicit `len`. Pay most attention to prefixes ending:
  - immediately after a `}` or `]` that closes a nested container (simdjson CVE-2026-88358 shape)
  - after a lone `\`, after `\u` or `\uD8`
  - after `,` inside an object (cJSON `{"1":1,` shape)
  Also compare `len = -1`, which uses `strlen`, against an explicit `len` (see MC-4).
- **SC-7/SC-8 for json-c multi-value use.** Test `JSON_TOKENER_ALLOW_TRAILING_CHARS` and the pattern of calling `json_tokener_parse_ex()` repeatedly on concatenated documents. Inputs: `{}{}`, `[1][2]`, `1 2`, `12` (must not split into 1 and 2), `"a""b"`, `{} x`, and a document whose separator lands exactly on a chunk boundary. Assert that `json_tokener_get_parse_end()` advances to exactly the end of each value.
- **SC-9 for json-c.** Assert `json_tokener_get_parse_end()` and the tokener's char offset after an error that occurs in the second or later chunk. Do the same after `json_tokener_reset()`, and after a success that is followed by trailing whitespace or commas. Offsets should match the whole-buffer case once translated to the current chunk.
- **SC-10 for json-c.** A driver that loops on `json_tokener_continue` with zero new bytes, or calls again after an error without `json_tokener_reset()`, must either terminate or return a sticky error. Test what json-c returns on the second call after an error.
- **SC-11 for json-c.** Under LSan, call `json_tokener_free()` at every chunk boundary of a nested document. Also call `json_tokener_reset()` mid-object and mid-string. Nothing may leak.
- **SC-12** applies to callers of json-c that frame NDJSON by lines. As a harness check, a raw U+2028 (`E2 80 A8`) inside a string must parse, both whole and split across chunks.

### Gaps
- I found no published json-c bug about `json_tokener_get_parse_end()` or char offsets being wrong after resume. SC-9 above is drawn from Go only.
- I could not retrieve the Go `Decoder` sticky-error behaviour, or the serde_json `StreamDeserializer` documentation (`failed` flag, self-delineating values, `byte_offset`). The page I fetched was truncated before that code.
- yajl's upstream (lloyd/yajl) issue tracker produced no concrete chunk-boundary lexer bug in my searches.
- I found no specific simdjson ondemand bug about values that straddle the batch boundary, beyond the documented constraints.
- The JSON Lines U+2028 reports (SC-12) were seen as titles only.
- The web-fetch budget ran out before I could read the Node readline and Jackson non-blocking location reports.

---

## Q3. What memory-safety and resource-exhaustion bug classes appear in C JSON parsers (named CVEs)?

### Takeaway
The confirmed C/C++ parse-side classes are:
- Over-reads at the end of input or the end of a string, often after a trailing backslash or a truncated container
- Integer overflow in buffer growth on huge inputs, mainly on 32-bit builds
- Predictable-hash flooding of object keys
- Recursion-depth stack exhaustion
- Assertion aborts on malformed `\u` escapes
- Out-of-bounds reads in surrogate handling
- Signed-char misuse in ctype calls
- Exponent integer underflow
- Non-strict-mode structural invariant violations that corrupt consumers
- Bugs in auxiliary CLI tools

json-c itself has CVEs in four of these: buffer growth, hash flooding, ctype, and the CLI tools.

### Cited Findings

**MC-1 Integer overflow in buffer growth on huge input**
- json-c CVE-2020-12762 ("integer overflow and out-of-bounds write via a large JSON file", as demonstrated by `printbuf_memappend`): json-c through 0.14, fixed in 0.15-20200726 (commit 9021cdc, PR #592). — [OSV CVE-2020-12762](https://osv.dev/vulnerability/CVE-2020-12762)
- json-c CVE-2013-6370: the printbuf APIs used `int` for lengths, which was unsafe on 32-bit. Fixed in 0.12 (commit 64e3690). — [oss-security 2014/04/09](https://openwall.com/lists/oss-security/2014/04/09/9); [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2013-6370)
- yajl-ruby CVE-2022-24795: in `yajl_buf.c`, `need` wraps to 0 as data approaches 0x80000000 bytes (about 2 GB). The buffer is reallocated to a tiny chunk, but writes still use the original size, corrupting the heap. The risk is mainly on 32-bit `size_t` builds. Fixed in 1.4.2 (commit 7168bd7). — [OSV CVE-2022-24795](https://osv.dev/vulnerability/CVE-2022-24795)
- Out of scope (serializer side), named for completeness:
  - cJSON CVE-2026-16554 (`print_string_ptr`, a 32-bit escape-count overflow with about 858,993,460 control characters). — [Red Hat](https://access.redhat.com/security/cve/CVE-2026-16554)
  - simdjson CVE-2026-8295 (`string_builder::escape_and_append`, fixed in 4.6.4). — [OSV](https://api.osv.dev/v1/vulns/CVE-2026-8295)

**MC-2 Hash flooding of object keys**
- json-c CVE-2013-6371: a weak hash function caused "quadratic timing" when parsing "smallish JSON strings". Fixed in 0.12. — [oss-security 2014/04/09](https://openwall.com/lists/oss-security/2014/04/09/9)
- jansson CVE-2013-6401: versions up to 2.4 allowed attackers to trigger hash collisions predictably with a crafted JSON document, causing CPU exhaustion (commit 8f80c2d). — [OSV CVE-2013-6401](https://osv.dev/vulnerability/CVE-2013-6401)

**MC-3 Stack exhaustion through nesting depth**
- Seriot's table: cJSON and ccan (C), and JSONKit and SBJSON (Obj-C), crash on deeply nested structures. JSON.sh segfaults on 100,000 `[`. jansson, jsmn and json-parser did not crash. — [Seriot](https://seriot.ch/projects/parsing_json.html)
- jackson-databind CVE-2020-36518: deeply nested objects cause a StackOverflowError (fixed in 2.12.6.1 and 2.13.2.1). — [OSV CVE-2020-36518](https://osv.dev/CVE-2020-36518)
- Go `encoding/json` added a 10,000-level nesting limit "to protect against stack overflow" (Fixes #31789). — [Go commit 84afaa9](https://go.googlesource.com/go/+/84afaa9e9491d76ea43d7125b336030a0a2a902d)
- json-c 0.19: "Issue #881: don't allow json_tokener_new_ex() with a depth < 1". — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog)
- (Depth-limit BVA: already covered.)

**MC-4 Over-reads at end of input or end of string (C string assumptions)**
- cJSON:
  - CVE-2016-10749: a string ending in `\` at end of input. — [OSV](https://osv.dev/vulnerability/CVE-2016-10749)
  - CVE-2023-53154: `{"1":1,` passed to `cJSON_ParseWithLength`. — [OSV](https://osv.dev/vulnerability/CVE-2023-53154)
  - CVE-2019-11834: in `cJSON_Minify`, a backslash right before the terminator skips two characters without checking for `\0`, so reads and writes run past the buffer. Fixed in 1.7.11. — [cJSON #337](https://github.com/DaveGamble/cJSON/issues/337); [OSV](https://api.osv.dev/v1/vulns/CVE-2019-11834)
- jansson CVE-2020-36325: a fuzzer passed a buffer that was not NUL-terminated to `json_loads` (`[]` followed by many `g` bytes), causing a SEGV in `string_get`. Red Hat closed it NOTABUG as a fuzzer error, and upstream discussion suggested the CVE should be rejected. The lesson is that NUL-terminated APIs over-read when given raw buffers. — [Red Hat Bugzilla 1954173](https://bugzilla.redhat.com/show_bug.cgi?id=1954173); [jansson #548](https://github.com/akheron/jansson/issues/548)
- simdjson CVE-2026-88358 and Rust simd-json CVE-2019-15550 are covered under SC-6.
- json-c 0.13: "Issue #275: fix out of bounds read when handling unicode surrogate pairs". json-c 0.16: "Fix read past end of buffer in the "json_parse" command". — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog)

**MC-5 Assertion or abort on malformed escapes**
- yajl CVE-2017-16516 (see IC-6): `"\uD800\\1"` aborts the process. — [yajl-ruby #176](https://github.com/brianmario/yajl-ruby/issues/176)

**MC-6 Signed `char` passed to ctype functions (bytes ≥ 0x80)**
- From the [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog):
  - 0.14: "Issue #407: fix incorrect casts in calls to ctype functions (isdigit and isspace) so we don't crash".
  - 0.19: "Issue #875: cast to unsigned char so bytes above 0x7f aren't interpreted as negative".

**MC-7 Number exponent integer underflow (RapidJSON)**
- CVE-2024-38517: an integer underflow in `GenericReader::ParseNumber()` exponent handling (`reader.h`), CWE-191, CVSS 7.8. Fixed by commit 8269bc2 (PR #1261). — [OSV CVE-2024-38517](https://osv.dev/vulnerability/CVE-2024-38517)
- RapidJSON commit 24b5e7a: "Fix out of bounds read with kParseValidateEncodingFlag". — [RapidJSON log](https://chromium.googlesource.com/external/github.com/Tencent/rapidjson/+log)

**MC-8 Structural invariant broken in non-strict mode, so the consumer reads out of bounds (jsmn, 2026)**
- jsmn CVE-2026-95117 and CVE-2026-88369 (issue #249):
  - Trigger: a 1,534-byte malformed input of about 100 nested `{"a":`. At depth ~102 a key is followed by `{` instead of `:`, a stray quote follows, and the input ends with a run of `}`.
  - In non-strict mode, the `:` handler makes the last STRING or PRIMITIVE token the parent, and later handlers increment its `size`. That breaks the invariant that only OBJECT and ARRAY tokens have `size > 0`.
  - `dump()` in the bundled example then reads past the token array. `jsmn_parse` itself stays in bounds.
  - Strict mode (`-DJSMN_STRICT=1`) exits cleanly. Debian lists the issue as unfixed.
  — [jsmn #249](https://github.com/zserge/jsmn/issues/249); [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-95117); [Tenable](https://www.tenable.com/cve/CVE-2026-88369)

**MC-9 Sizing pass and parse pass disagree under option flags (sheredom json.h)**
- json.h CVE-2022-45491 is a buffer overflow in `json_parse_value`. — [PT dbugs](https://dbugs.ptsecurity.com/researchers/Hyrathon)
- A related advisory reports a heap out-of-bounds write in `json_parse_object()` when `json_parse_flags_allow_location_information` is set: `state->dom` is advanced by the larger extended-struct size and `offset`/`line_no`/`row_no` are written with no bounds check, landing 0 bytes past a 377-byte allocation. — [GHSA-wvpq-p7pp-cj6m](https://github.com/hyrathon/trophies/security/advisories/GHSA-wvpq-p7pp-cj6m)

**MC-10 Double free on reallocation error during string decode**
- ujson CVE-2022-31117: when an error occurs while the string buffer is being reallocated, the buffer is freed twice. The advisory says it cannot be triggered from Python. Fixed in 5.4.0. — [GHSA-fm67-cv37-96ff](https://github.com/advisories/GHSA-fm67-cv37-96ff)
- json-c had related allocation-failure bugs — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog):
  - 0.16: "Fix use-after-free in json_tokener_new_ex() in the event of printbuf_new() returning NULL".
  - 0.18: "duplocate can return NULL".
  (OOM error codes: already covered. The use-after-free and double-free shape on the failure path is the extra angle here.)

**MC-11 Comment lexer over-read (jsoncpp)**
- OSS-Fuzz issue 18140: a heap-buffer-overflow READ of 1 byte in `Json::OurReader::readComment`, fixed by commit 2e33c21. — [OSS-Fuzz jsoncpp entry](https://vulertsecurity.com/vuln-db/oss-fuzz-jsoncpp-12251)

**MC-12 Bundled CLI or sample tools (json-c)**
- CVE-2021-32292: a stack-buffer-overflow in `parseit` in `apps/json_parse`. Fixed by PR #655 and commit 4e9e44e. — [Debian tracker](https://security-tracker.debian.org/tracker/CVE-2021-32292)
- CVE-2026-11322: an information disclosure in `apps/json_parse` (issue #929, 0.19). — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog)

### Inferences
- **MC-1 for json-c.** Feeding chunks accumulates a long string or number in the tokener's printbuf across calls. On a 32-bit or `-m32` build, the overflow guard should be exercised with total accumulated length near `INT_MAX` and `SIZE_MAX/2`, reached only through many chunks. This is a streaming variant of CVE-2020-12762. A synthetic test can use a small-allocation hook rather than real 2 GB inputs.
- **MC-2 for json-c.** Add a timing guard: N distinct keys that collide under a fixed seed, if the seed can be fixed in a test build. Compare against random keys; a ratio that grows like O(N²) points to a weak or unseeded hash.
- **MC-4 for json-c.** Every truncated prefix in exact-size, non-NUL-terminated buffers under ASan (see SC-6). Explicitly include the trailing-backslash prefix (`"abc\`), the `\u` prefixes, and the `{"1":1,` shape.
- **MC-6 for json-c.** Put each byte 0x80–0xFF in every lexical position: whitespace position, number start, inside a number, after `-`, inside literals, inside `\u` hex digits, and in comment-start positions. Run in default and STRICT, under UBSan and with a signed-`char` toolchain flag (`-fsigned-char`).
- **MC-8 for json-c non-strict mode.** Fuzz deep nesting combined with missing colons, missing values, stray quotes and comma or colon substitutions in non-strict mode. Then walk the resulting object tree with a strict consumer that asserts invariants. Example invariant: no object member without a value; array lengths match the elements present.
- **MC-9 for json-c.** Where flags change the internal representation (for example `JSON_TOKENER_VALIDATE_UTF8`, STRICT, `ALLOW_TRAILING_CHARS`), run the same corpus under every flag combination with ASan. The json.h bug needed a specific flag combination.

### Gaps
- I did not retrieve the exact trigger for cJSON CVE-2019-11835 ("multiline comments", before 1.7.11) beyond the one-line description. The listing describes it as an out-of-bounds access; I believe it is in `cJSON_Minify` but did not confirm. — [vulners cJSON listing](https://vulners.com/search/vendors/davegamble/products/cjson/versions/*?year=2019)
- I found no parson CVE. A search for "parson" returned only unrelated Eclipse Parsson and json.h results.
- I did not verify RapidJSON CVE-2024-39684 or ujson CVE-2021-45958. The latter is probably encoder-side, so out of scope.
- I did not retrieve the OSS-Fuzz bug history for json-c.
- I did not obtain the root cause of jansson CVE-2013-6401 or the actual json-c CVE-2013-6371 fix (seeded hash or not). The sources name only the commits.

---

## Q4. Which lenient-mode extensions (comments, single quotes, trailing commas, NaN/Infinity, unquoted keys) have produced bugs in other parsers, and how?

### Takeaway
Lenient extensions fail in four ways:
- Comments hide or reveal members, or are mis-tokenized as separators.
- After a NaN or Infinity literal the parser keeps consuming number syntax.
- Lenient escapes or quoting drop characters, so keys collide.
- Non-strict structural recovery breaks tree invariants.

There is also a documented, deliberate ambiguity in how trailing commas interact with "missing values".

### Cited Findings

**LC-1 Comments mis-tokenized as separators (jsoncpp)**
- jsoncpp PR #1502, "Fix a parser bug where tokens are misidentified as commas": inside an object, a comment followed by any token other than `}` was treated as a comma, in both the old and new readers. The same change made the parser honour `allowComments == false`, which it had ignored before. — [jsoncpp commit 0a9b9d9 (Pigweed mirror)](https://pigweed.googlesource.com/third_party/github/open-source-parsers/jsoncpp/+/0a9b9d9c6ea04847af83c32930176ec42ba6c842)
- jsoncpp OSS-Fuzz 18140 is a heap over-read in `readComment` (see MC-11). — [OSS-Fuzz jsoncpp entry](https://vulertsecurity.com/vuln-db/oss-fuzz-jsoncpp-12251)

**LC-2 Comments hide or reveal members across parsers**
- See IC-9: the comment-truncation payloads, and the list of parsers that accept comments without being asked to. — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)
- cJSON CVE-2019-11835 is an out-of-bounds access "related to multiline comments", before 1.7.11. — [vulners cJSON listing](https://vulners.com/search/vendors/davegamble/products/cjson/versions/*?year=2019)
- (Unterminated comments at EOF, even star runs, and comment buffering memory: already covered.)

**LC-3 NaN/Infinity literal followed by number syntax (RapidJSON)**
- RapidJSON commit 7c73dd7 (fixes #2299): with `kParseNanAndInfFlag`, `NaN.2e2` parsed as `20`. The parser carried on into fraction and exponent parsing after a complete NaN or Inf. — [RapidJSON commit 7c73dd7](https://gitlab.cristal.univ-lille.fr/pirvi-public/rapidjson/-/commit/7c73dd7de7c4f14379b781418c6e947ad464c818)
- json-c 0.13: "Issue #371: fix parsing of "-Infinity"". json-c 0.12 STRICT: "only allow lowercase literals". — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog)
- Jackson's `ALLOW_NON_NUMERIC_NUMBERS` accepts `INF`, `-INF`, `NaN`, `Infinity` and `-Infinity`. That token set differs from other parsers, which is a differential in itself. — [Jackson JsonReadFeature 2.14 javadoc](https://fasterxml.github.io/jackson-core/javadoc/2.14/com/fasterxml/jackson/core/json/JsonReadFeature.html)
- Infinity is rendered differently across Python, ujson, Jackson and Jodd (`"Infinity"`, `"Inf"`, `"+Infinity"`). — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)

**LC-4 Trailing commas and missing values: deliberate ambiguity**
- In Jackson, `ALLOW_TRAILING_COMMA` "takes priority" over `ALLOW_MISSING_VALUES`:
  - `[true,true,]` is equivalent to `[true,true]`.
  - `[true,true,,]` is equivalent to `[true,true,null]`.
  - With `ALLOW_MISSING_VALUES` alone, `["value1",,"value3",]` becomes `["value1",null,"value3",null]`.
  So the same text gives different array lengths depending on which flags are set. — [Jackson JsonReadFeature 2.14 javadoc](https://fasterxml.github.io/jackson-core/javadoc/2.14/com/fasterxml/jackson/core/json/JsonReadFeature.html)

**LC-5 Lenient escapes or quoting drop characters, so keys collide**
- Invalid escapes such as `\s` are silently dropped by Jayrock, Ruby stdlib, and the JS and Rust json5 implementations. A backslash followed by a raw CR collapses keys in Rust and PHP json5. — [Bishop Fox](https://bishopfox.com/blog/json-interoperability-vulnerabilities)
- json-c 0.12 made STRICT reject single-quoted strings, comments, trailing characters and leading-zero numbers. — [json-c ChangeLog](https://raw.githubusercontent.com/json-c/json-c/master/ChangeLog)
- (STRICT accepting single-quoted keys: already covered.)

**LC-6 Non-strict structural recovery corrupts the tree (jsmn)**
- jsmn CVE-2026-95117 and CVE-2026-88369 occur only in non-strict mode (see MC-8). — [jsmn #249](https://github.com/zserge/jsmn/issues/249)

**LC-7 Leading zeros, leading `+` or `.`, and leniency regressions**
- ijson 3.1.3: the Python backend now raises errors for numbers with leading zeros and for fractions "where the decimal point is not surrounded" by digits. Both were accepted before. — [ijson CHANGELOG](https://github.com/ICRAR/ijson/blob/v3.2.3/CHANGELOG.md)
- Jackson offers `ALLOW_LEADING_PLUS_SIGN_FOR_NUMBERS` (`+123`) and `ALLOW_LEADING_DECIMAL_POINT_FOR_NUMBERS` (`.123`, read as `0.123`). — [Jackson javadoc](https://fasterxml.github.io/jackson-core/javadoc/2.14/com/fasterxml/jackson/core/json/JsonReadFeature.html)
- serde_json #1077: the map key `"01234"` deserialized into `HashMap<i64,_>` used to become 1234. Since 1.0.101 it fails, so a leniency change in key-to-number coercion broke users. — [serde_json #1077](https://github.com/serde-rs/json/issues/1077)

**LC-8 Lenient-extension support grafted onto a streaming parser (yajl)**
- EPICS added JSON5 extensions to its embedded yajl, including `\xXX` hex escapes. I saw the commit titles only. — [EPICS commit 55f4e55](https://gitea.psi.ch/epics/epics-base/commit/55f4e55383080ed78f0d5000d0124646f04b5c3e); [lloyd/yajl PR #211 (JSON5 support)](https://github.com/lloyd/yajl/pull/211)

### Inferences
- **LC-1 for json-c non-strict.** In each case, the comment must not act as a comma:
  - `{"a":1 /*c*/ "b":2}` must be an error, not `{"a":1,"b":2}`.
  - `[1 /*c*/ 2]` must be an error.
  - `{"a" /*c*/ : 1}` and `{"a": /*c*/ 1}` must be accepted, if comments are allowed in those positions.
  - `{"a":1, /*c*/ }` should follow whatever trailing-comma policy applies.
  - `// c` + LF + `{}` and `{}// c` at EOF, each split at every byte.
  In STRICT mode, each must be rejected with the same error whole and split.
- **LC-3 for json-c non-strict.** None of these should yield a number value:
  - `NaN.5`, `NaN.2e2`, `NaNe3`
  - `Infinity1`, `Infinity.0`, `-Infinity.5`
  - `Infinityx`, `-Infinit`, `-Inf`
  - `-NaN`, `+Infinity`, `nan`, `infinity`, `INFINITY`
  The expected outcome for each is either a clean error or `NaN`/`Infinity` followed by a trailing-character error. Check the split versions too, e.g. `NaN` | `.2e2` and `-Inf` | `inity`, because the post-literal state is where RapidJSON went wrong.
- **LC-4 for json-c non-strict.** Document and test `[1,]`, `[1,,2]`, `{"a":1,}`, `[,]`, `[,1]` and `{,}`. The array length or error must be deterministic and identical across chunk splits. `[1,,2]` must never become `[1,null,2]` silently unless that is a documented behaviour.
- **LC-5 for json-c non-strict.** Test single-quoted strings containing `\'`, `"` and raw control characters. Test invalid escapes `\s`, `\x41`, `\0`, `\` + CR and `\` + LF. Test an unterminated single-quoted key at a chunk boundary. Confirm json-c rejects invalid escapes rather than dropping the backslash; dropping it is the Bishop Fox key-collision vector.

### Gaps
- I found no documented bug reports about unquoted keys specifically in any parser I could read.
- I could not determine json-c's documented non-strict behaviour for trailing commas and empty array elements from the sources retrieved; the expected outcomes above are proposals.
- I saw only titles for "infinite loop in patched cJSON_Minify function" (Launchpad 1934643) and the yajl JSON5 escape commits; I did not read their contents. — [Launchpad 1934643](https://bugs.launchpad.net/bugs/1934643)
