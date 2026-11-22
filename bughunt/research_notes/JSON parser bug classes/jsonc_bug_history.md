# json-c parser bug and CVE history (json_tokener, printbuf, linkhash, json_util number parsing)

Scope and method. These notes cover parsing (`json_tokener.c`, `json_tokener_parse_ex`) and the buffer and number code it relies on (`printbuf.c`, `linkhash.c`, `json_util.c`). Sources:
- the upstream git history, cloned on 2026-11-22. Master HEAD is `d2ce61e` (2026-11-19). The latest release is 0.19 (tag `json-c-0.19-20260627`).
- `ChangeLog` and `issues_closed_for_0.1x.md`.
- pull-request heads fetched read-only through `refs/pull/N/head`.
- OSS-Fuzz and oss-fuzz-vulns configs.
- the CVE trackers listed below.

Claims marked **"local repro"** are my own tests. I built master `d2ce61e` with ASan+UBSan (one build also with TSan) and fed it inputs from a small C driver. The links for those claims point at the exact source lines on master.

The team already knows these open upstream items, and they are marked **[KNOWN]** where they appear: PR #1006, #1007, #1013, #1014, #1001, issue #984, #715, #855.

---

## Q1. Which CVEs affect json-c, and what exactly were the root cause and fix of each?

### Takeaway
Only four CVE records clearly belong to json-c: CVE-2013-6370, CVE-2013-6371, CVE-2020-12762 and CVE-2021-32292. Two "2026 CVEs" named in json-c 0.19's ChangeLog do not check out. CVE-2026-9146 was rejected, and the CVE-2026-11322 record describes an unrelated product. Both CVE families that touch parsing had incomplete first fixes:
- The 2014 printbuf "fix" only capped the input length of each call. The cumulative int overflow came back as CVE-2020-12762.
- The 2020 json_parse fix bounded reads by buffer capacity rather than by the bytes actually read. That gap was reopened as the 2026 issue #929.

### Cited Findings

**Master list of json-c CVEs.** OpenCVE lists exactly four json-c CVEs: CVE-2021-32292 (CVSS 3.1 9.8), CVE-2020-12762 (7.8), CVE-2013-6370 (CVSS 2.0 5.0) and CVE-2013-6371 (5.0) — [OpenCVE](https://app.opencve.io/cve/?product=json-c&vendor=json-c). The Debian source-package tracker lists the same four, all resolved, with no open entries — [Debian tracker](https://security-tracker.debian.org/tracker/source-package/json-c).

**CVE-2013-6371: hash-collision DoS (CPU)**
- Found by Florian Weimer (Red Hat Product Security) and announced on oss-security on 2014-04-09.
- Root cause: a weak string hash in linkhash, so parsing small crafted JSON objects took quadratic time.
- Fixed by upstream commit `64e36901` — [oss-security 2014/04/09/9](https://openwall.com/lists/oss-security/2014/04/09/9).
- The fix commit (2014-04-09, Michael Clark) adds `random_seed.c` and a seeded hash in `linkhash.c` (379 lines added) — [commit 64e3690](https://github.com/json-c/json-c/commit/64e36901a0614bf64a19bc3396469c66dcd0b015).
- Released in 0.12, whose ChangeLog lists "CVE-2013-6371: hash collision denial of service" — [ChangeLog @ d2ce61e](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/ChangeLog).
- Trigger shape: one object with many keys whose hashes collide.

**CVE-2013-6370: printbuf buffer overflow "if size_t is larger than int"**
- Root cause: the printbuf APIs used `int` for lengths. The advisory suggested moving to `size_t` or rejecting negative values — [oss-security 2014/04/09/9](https://openwall.com/lists/oss-security/2014/04/09/9).
- What the fix actually changed: commit 64e3690 does not touch `printbuf.c`. In `json_tokener_parse_ex()` it only adds a guard, `if ((len < -1) || (len == -1 && strlen(str) > INT32_MAX)) { tok->err = json_tokener_error_size; return NULL; }`, plus a new "buffer size overflow" error string — [commit 64e3690](https://github.com/json-c/json-c/commit/64e36901a0614bf64a19bc3396469c66dcd0b015). (Verified with `git show --stat` in the clone.)

**CVE-2020-12762: integer overflow and out-of-bounds write in printbuf/linkhash** ("json-c through 0.14 ... via a large JSON file", shown through `printbuf_memappend`)
- Red Hat bug 1835253 was opened 2020-05-13. Red Hat rated it reduced impact and usually local. Fix PR #592; backports in PRs 607 (0.13), 608 (0.14), 611 (0.12), 612 (0.11) and 613 (0.10). libfastjson was also affected — [Red Hat BZ 1835253](https://bugzilla.redhat.com/show_bug.cgi?id=1835253).
- Root cause, from the commit message: "linkhash and printbuf are limited to 2 GB in size due to a signed integer being used to track their current size ... printbuf is vulnerable to an out of boundary write on 64 bit systems." The fix adds INT_MAX guards in `printbuf_extend()` (`min_size > INT_MAX - 8`, `p->size > INT_MAX/2`), `printbuf_memappend()` (`size > INT_MAX - p->bpos - 1`), `printbuf_memset()` (`len > INT_MAX - offset`) and `lh_table_insert_w_hash()` (doubling the size) — [commit d07b910](https://github.com/json-c/json-c/commit/d07b91014986900a3a75f306d302e13e005e9d67), 2020-05-04, Tobias Stoeckmann.
- Companion commits:
  - `lh_table_new()` gets `assert(size > 0)` to prevent division by zero — [77d935b](https://github.com/json-c/json-c/commit/77d935b7ae7871a1940cd827e850e6063044ec45).
  - `array_list_del_idx` gets a size_t overflow guard — [099016b](https://github.com/json-c/json-c/commit/099016b7e8d70a6d5dd814e788bba08d33d48426).
- The security fix caused a regression. Its new `lh_table_insert_w_hash()` check was written backwards (`INT_MAX / 2 < t->size ? t->size * 2 : INT_MAX`), so objects could hold no more than 11 keys (issue #599). It was fixed 6 days later — [519dfe1](https://github.com/json-c/json-c/commit/519dfe1591d85432986f9762d41d1a883198c157). Debian's notes also flag the d07b910 regression (#599, fix PR #610) — [Debian CVE-2020-12762](https://security-tracker.debian.org/tracker/CVE-2020-12762).
- Released in 0.15 ("#592 - Fix integer overflows to prevert out of bounds write on large input") — [ChangeLog](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/ChangeLog). Debian fixed versions: jessie 0.11-4+deb8u2, stretch 0.12.1-1.1+deb9u1, buster 0.12.1+ds-2+deb10u1 (DSA-4741-1) — [Debian CVE-2020-12762](https://security-tracker.debian.org/tracker/CVE-2020-12762).
- Trigger shape: more than 2 GB of string or array data accumulated into one printbuf, for example a huge string value. Because json_tokener appends every chunk to `tok->pb`, incremental feeding with per-call `len` values that each pass the 64e3690 guard still reaches the overflow.

**CVE-2021-32292: stack-buffer-overflow in `parseit()` of the `apps/json_parse` sample program** (json-c 20200420 through 0.15-20200726; CVSS 9.8 per OpenCVE)
- Sources: [OpenCVE](https://app.opencve.io/cve/?product=json-c&vendor=json-c); [Debian DSA-5486](https://security-tracker.debian.org/tracker/DSA-5486) (bullseye fixed in 0.15-2+deb11u1).
- Upstream issue #654 ("A stack-buffer-overflow in json_parse.c:89:44") and fix PR #655 — [issues_closed_for_0.16.md](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/issues_closed_for_0.16.md).
- Fix commit 2020-08-07: `aterr = &buf[start_pos + parse_end]` became `(start_pos + parse_end < sizeof(buf)) ? ... : ""` — [4e9e44e](https://github.com/json-c/json-c/commit/4e9e44e5258dee7654f74948b0dd5da39c28beec).
- Root cause: the caller did arithmetic on `json_tokener_get_parse_end()` without bounding the result.

**"CVE-2026-11322" (json-c issue #929): information disclosure in apps/json_parse**
- The 0.19 ChangeLog says "Issue #929: CVE-2026-11322 - fix information disclosure bug in apps/json_parse (not installed by default)" — [ChangeLog](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/ChangeLog).
- The fix (2026-06-21) changes the bound from `< (int)sizeof(buf)` to `< retu` (bytes actually read). The 2020 CVE-2021-32292 fix still let the error message print stale stack bytes past the valid data — [1d65898](https://github.com/json-c/json-c/commit/1d658982e591389341a92aae2ee54cd26e81beb5).
- **Conflict:** the public CVE-2026-11322 record (VulnCheck CNA, published 2026-06-04) describes a Hermes WebUI symlink path traversal, not json-c. The only json-c link is an openSUSE json-c-devel advisory (SU-2026:11188-1) that lists the ID — [GCVE CVE-2026-11322](https://db.gcve.eu/vuln/cve-2026-11322). Treat this ID as mis-assigned or mis-cited.

**"CVE-2026-9146" (json-c issue #927)**
- The ChangeLog links it to a documentation change: modifying an object invalidates `json_object_iterator` — [ChangeLog](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/ChangeLog); [dee128f](https://github.com/json-c/json-c/commit/dee128f4d6dc0a305fc3d4b6a7ab3e3186a1306b).
- SUSE says "This CVE ID has been rejected or withdrawn by its CVE Numbering Authority" — [SUSE CVE-2026-9146](https://suse.com/security/cve/CVE-2026-9146). It is not parser-related.

**Not json-c, despite showing up in json-c searches.**
- CVE-2026-16554 is an integer overflow in cJSON's `print_string_ptr` on 32-bit; package `cjson` — [Debian CVE-2026-16554](https://security-tracker.debian.org/tracker/CVE-2026-16554).
- CVE-2026-67215, -67216 and -67217 are cJSON issues (33 bugs; oss-security, 2026-07-30) — [oss-security 2026/07/30/22](https://www.openwall.com/lists/oss-security/2026/07/30/22).

### Inferences
- The 2014 CVE-2013-6370 fix only checked the length of each call. It did nothing for growth across calls or for serializer growth. CVE-2020-12762, six years later, is the same int-length overflow reached cumulatively. Any remaining `int` length path should still be tested with cumulative input, for example many `json_tokener_parse_ex()` chunks adding up to more than INT_MAX bytes in one string. Note that `printbuf_memappend` failure (EFBIG) is reported as `json_tokener_error_memory`, not `json_tokener_error_size` (from reading `printbuf_memappend_checked` in [json_tokener.c#L307-L316](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L307-L316)).
- Two of the four real CVEs (CVE-2021-32292 and #929) come from callers misusing `json_tokener_get_parse_end()` / `char_offset` against their own buffers. The parse-end contract — relative to the last call, and not cumulative — is a recurring hazard for consumers.

### Gaps
- I could not open the NVD pages; WebFetch returned only the NVD shell. CVSS and descriptions come from OpenCVE, Debian and Red Hat instead.
- I could not see the original reporter details or PoC for CVE-2021-32292 beyond the issue title and the fix diff.
- I did not read the openSUSE SU-2026:11188-1 advisory text, because the fetch budget ran out. It is unclear which four CVEs it lists.

---

## Q2. Which tokener and buffer bugs appear in the ChangeLog, release notes and GitHub history (0.13 → master, late 2026)?

### Takeaway
More than 45 parser and buffer fixes fall into a handful of families:
- incremental, chunk-boundary state loss: numbers, -Infinity, surrogates, UTF-8
- error-code handling in the `out:` epilogue and on OOM paths
- signed-char and ctype misuse
- locale switching, with six rounds of fixes
- int-length limits in printbuf and linkhash
- strict-mode grammar gaps

Several fixes needed a follow-up fix (fix-of-fix): 86dd55a→56df93d, 4091b9c→fa76e4a, d07b910→519dfe1, bcb6d7d→9361d8d, PR #633→36118b6, 6bfab90→565f181→7cee523, 3dad694→ad8b8af, 4e9e44e→1d65898, 99c14de (partial).

### Cited Findings — dated list (oldest first; short hash → link)

**Pre-0.13 foundations**
- 2009-08-27 — linkhash lookup could hang after all slots were filled and then freed (tombstone handling) — [f5dd43a](https://github.com/json-c/json-c/commit/f5dd43a9d10abb2de50956d23505da08896f0c64).
- 2012-03-31 — linkhash resize check changed from `count > size` to `count >= size` to avoid an infinite loop with high load factors and a full table — [64c0ca3](https://github.com/json-c/json-c/commit/64c0ca3690f98e978fd2fc8c6ca645243c27e3db).
- 2012-03-31 — reusing a tokener for multiple objects was broken; `json_tokener_reset()` is no longer needed after a successful parse — [d809fa6](https://github.com/json-c/json-c/commit/d809fa60c5d0bb91d1c444dfa01b9ab5cb22112e).
- 2012-04-03 — wrong buffer-size calculations in `printbuf_memset` and an off-by-one in `printbuf_memappend` — [0d79b53](https://github.com/json-c/json-c/commit/0d79b534568f609a9444c3466ae1f5a2864f702f).
- 2012-11-27 and 2012-12-13 — float parsing made locale-independent by calling `setlocale` around the parse (process-global, not thread-safe) — [16a4a32](https://github.com/json-c/json-c/commit/16a4a32e294e80ca8c89ec83e62baa0c59947ac9), [a01b659](https://github.com/json-c/json-c/commit/a01b659ace168d85a3e9e47848eaaba2bea31078).
- 2012-12-09 — Issue #53: strings given with an explicit length were not NUL-terminated, and `\u0000` handling was fixed (Debian bug 687269) — [4e4af93](https://github.com/json-c/json-c/commit/4e4af93d667ae0d3cb9779f5a3c3f964cc9d7d81).
- 2013-09-08 — OOB read in `json_tokener_error_desc()`: the bound used `sizeof` (bytes) instead of the element count. The follow-up fix on 2014-02-11 (Issue #111) corrected an off-by-one (`>` → `>=`) — [86dd55a](https://github.com/json-c/json-c/commit/86dd55a74a6634a1018feac7f5ef5579d033ce2a), [56df93d](https://github.com/json-c/json-c/commit/56df93d12857fb3d13f7e14391954e3b59708261).
- 2014-04-09 — the CVE-2013-6370 and CVE-2013-6371 patch (see Q1) — [64e3690](https://github.com/json-c/json-c/commit/64e36901a0614bf64a19bc3396469c66dcd0b015).
- 2015-02-05 — "Tightening the number parsing algorithm" (Issue #168): `12.3.4` and `2015-01-15` now error instead of being truncated — [99d8fc9](https://github.com/json-c/json-c/commit/99d8fc975e059a5e1749d4dc6c07a02e9a629921); [ChangeLog 0.13](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/ChangeLog).
- 2016-01-11 — "Fix various potential null ptr deref and int32 overflows" (Even Rouault, PR #219). It added `if(current == NULL) goto out;` after allocations without setting `tok->err`, so an allocation failure could return NULL with success. That gap stayed until the 2022–2024 OOM work — [77a4276](https://github.com/json-c/json-c/commit/77a4276a8c210e1faa2e8c13421e9a3d62772340).
- 2016-07-30 and 31 — Issue #195: switch to `uselocale()`. The first commit did not actually call `uselocale()`; the next day's fix did, and also freed the correct `locale_t` on failure — [4091b9c](https://github.com/json-c/json-c/commit/4091b9c87ea293fd8bc3b05bc5b032e09697eefe), [fa76e4a](https://github.com/json-c/json-c/commit/fa76e4a8c96c9678712534fd59cce8e8d9d98fa1).
- 2016-10-05 — Issue #275: OOB read in surrogate-pair handling. The code looked ahead at `str[1]` and `str[2]` (expecting `\u`) without checking `len`, and `strchr(json_hex_chars, c)` matched the NUL terminator — [36a28fc](https://github.com/json-c/json-c/commit/36a28fcb0c4abf66361d1539380112a1dfe601b2).

**0.13 (2017-12) / 0.13.1 (2018-03)**
- 2017-11-26/27 — Issue #371: `-Infinity` parsing, including a `-` and `Infinity` split across calls; the inf state was rewritten to avoid copying input — [4d1e0b4](https://github.com/json-c/json-c/commit/4d1e0b44099c85b118f6cdb2c7b116fd92e6f2a4), [48f7e38](https://github.com/json-c/json-c/commit/48f7e389fb90c3647d0c846694a9456a7bf8ca3f), [f81da5e](https://github.com/json-c/json-c/commit/f81da5e57a2c85c283080be18d1bc5a94cd91345).
- 2018-02-05 — fuzzers added for OSS-Fuzz — [1e08150](https://github.com/json-c/json-c/commit/1e0815083881f509893d320c87d0d470cad35d2d).

**0.14 (2020-04)**
- 2018-03-25 — Issue #407: `isdigit()` / `isspace()` called with a negative `char` crashed when asserts were enabled and bytes above 127 were parsed (signed char) — [f8c632f](https://github.com/json-c/json-c/commit/f8c632f579c71012f9aca81543b880a579f634fc).
- 2019-09-08 — Issue #463: `newlocale()` was called with `LC_NUMERIC` instead of `LC_NUMERIC_MASK`; it only worked by accident because `LC_TIME == LC_NUMERIC_MASK` on some platforms — [374ffe8](https://github.com/json-c/json-c/commit/374ffe87c61bff2a230cd84274fe3ca494da4017).
- 2019-09-08 — `json_tokener_get_parse_end()` added to replace direct `char_offset` access; `JSON_TOKENER_VALIDATE_UTF8` added; uint64 support (parse up to UINT64_MAX) — [05b41b1](https://github.com/json-c/json-c/commit/05b41b159e98154820044826259eb2a8adf692ce); [ChangeLog 0.14](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/ChangeLog).

**0.15 (2020-07-26)**
- 2020-04-20 — `JSON_TOKENER_ALLOW_TRAILING_CHARS` flag added — [f6f76f9](https://github.com/json-c/json-c/commit/f6f76f9430f0f468a18c937fa7fdd9bf84041d8a).
- 2020-05-04/10 — CVE-2020-12762 set plus the #599 regression fix (see Q1).
- 2020-05-10 — `json_parse_uint64()` misused errno (#601: `json_tokener_parse()` left errno=1 "Operation not permitted"; #602) — [003b587](https://github.com/json-c/json-c/commit/003b58782b12798da3da8b952152988a88dfb532); [issues_closed_for_0.15.md](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/issues_closed_for_0.15.md).
- 2020-06-02/20 — PR #633 (issue #616: a surrogate pair split across chunks failed to parse) introduced an OSS-Fuzz global-buffer-overflow, fixed on 2020-06-21 by a rewrite (see Q3). The proper fix used extra tokener states instead of assuming the low surrogate is already in the buffer — [c1b872d](https://github.com/json-c/json-c/commit/c1b872d8174c9946f8d9383fe600e8ff6650647e), [36118b6](https://github.com/json-c/json-c/commit/36118b681ea3b8e99735beee73cbd25a63e942cd), [a68566b](https://github.com/json-c/json-c/commit/a68566bf6a2b44b5932072e85261a971097bc0a9).
- 2020-06-27 — incremental parsing of numbers with exponents: `"[0","e+","-]"` now errors, `"0e+-"` and `"12.3E12E12"` are rejected, strict mode rejects `"0e"`, and `json_parse_double()` is deprecated — [6eac698](https://github.com/json-c/json-c/commit/6eac6986c9a734b183e55a80e84fa67e58c637ff).
- 2020-06-29 — micro-states for number characters. A top-level number followed by `-`, `.` or `e` is returned (`"123-456"` → 123); callers must check `json_tokener_get_parse_end()` — [f23486a](https://github.com/json-c/json-c/commit/f23486a3217ed85ed4a0d7f95a10c4013250c987).
- 2020-07-21 — Issue #645: `tolower((int)*str)` → `(unsigned char)` (signed-char UB) — [1962ba7](https://github.com/json-c/json-c/commit/1962ba7de30b999a9d08c716fe588b8e562101e3).

**0.16 (2022-04-14)**
- 2020-08-02 — ctype.h removed from the tokener, and vertical tab and formfeed are no longer whitespace — [8c7849e](https://github.com/json-c/json-c/commit/8c7849e6e3b985825be770041af2b948fa6d8918), [f3d8006](https://github.com/json-c/json-c/commit/f3d8006d3487a806092f3379d8cdb6a8c9c5dce9).
- 2020-08-22 → 2021-09-04 — "Handle allocation failure in json_tokener_new_ex" introduced a use-after-free (`free(tok); free(tok->stack);`), fixed by swapping the two calls (PR #722) — [bcb6d7d](https://github.com/json-c/json-c/commit/bcb6d7d3474b687718cbaee7bf203db4456fb6b3), [9361d8d](https://github.com/json-c/json-c/commit/9361d8d3a89475f5aadcac2c5473da1c4c47c7e2).
- 2022-02/03 — printbuf hardening (each with a commit link):
  - `printbuf_memappend` / `printbuf_memset` reject `len < 0` and totals above INT_MAX — [4355242](https://github.com/json-c/json-c/commit/435524247782e8fc64a96e9e18e7d1bfecbb9dd0)
  - `printbuf_memset` zeroes gaps — [63c602f](https://github.com/json-c/json-c/commit/63c602ff808f777341b1d9a83b28762b137909a9)
  - `sprintbuf` propagates errors — [d07da04](https://github.com/json-c/json-c/commit/d07da04c14d9677506e95aa58dc0cb10322ed79f)
  - `sprintbuf` handles every vsnprintf error value — [94b2a0c](https://github.com/json-c/json-c/commit/94b2a0cb29af1bc1fd5dece8c1fbf83acd210cb5)
  - the local `vasprintf` no longer makes out-of-memory accesses — [5c72257](https://github.com/json-c/json-c/commit/5c722572200e998736317090281f5dddc13bc311)
- 2022-03-20 — `json_tokener_parse_ex` OOM handling: out-of-memory errors silently truncated values or skipped entries (PoC: 8 MB string value) — [9e6acc9](https://github.com/json-c/json-c/commit/9e6acc9a4eefe9f092aa3a3890a6e5c6ca2d5ed1).
- 2022-03-20 — `json_object_from_fd_ex` fails if the file is INT_MAX bytes or larger — [5accae0](https://github.com/json-c/json-c/commit/5accae04bbc727fd447c2db4c1c541a4142bd4a0).
- 0.16 also caps string length at INT_MAX ("to avoid various issues with very long strings") — [ChangeLog 0.16](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/ChangeLog).

**0.17 (2023-08) — "DO NOT USE"**
- 2022-10-26/30 — `json_parse_int64` / `json_parse_uint64` set `errno=EINVAL` on failure (Issue #792). Overflow is documented as not an error but sets ERANGE. In strict mode, integer overflow now gives `json_tokener_error_parse_number`; without strict, values are clamped to INT64_MIN / UINT64_MAX — [57bef5e](https://github.com/json-c/json-c/commit/57bef5edc48ad30e794f64fdfc855e955046d25d), [c50bf9d](https://github.com/json-c/json-c/commit/c50bf9df9cb7dacd682104d844029938522f0bda), [d6f46ae](https://github.com/json-c/json-c/commit/d6f46ae104871360f84695737864870c97adfd14).
- 2023-07-30 — #668: `newlocale()` leak on older FreeBSD; adds the `-DUSELOCALE_NEEDS_FREELOCALE` workaround — [71d845e](https://github.com/json-c/json-c/commit/71d845e819d5efb0265905798e8a2b3ae0958515).
- 2023-08-12 → 2023-09-22 — `json_tokener_error_memory` was inserted mid-enum in 0.17, which broke ABI. The fix took two attempts ("json_tokener_error_size is an actual error, *not* a measure of the size of the enum!") — [3dad694](https://github.com/json-c/json-c/commit/3dad6941daf87bcdb5c750225ba655e414c4045b), [ad8b8af](https://github.com/json-c/json-c/commit/ad8b8afa7d567053b87f2d37ee4a534e13c210c7).

**0.18 (2024-09-15)**
- 2024-03-29 / 04-21 / 04-22 — the tokener did not return `json_tokener_error_memory` in several places:
  - #854: `json_tokener_parse_verbose` when allocating the tokener fails — [e93ae70](https://github.com/json-c/json-c/commit/e93ae70417867dac9ff87614f3e7bc50e79ef951)
  - #857: the return value of `json_object_object_add` was ignored — [31a22fb](https://github.com/json-c/json-c/commit/31a22fb2dabae30a759ae3346b493b44cedf1647)
  - `duplocale` returning NULL — [833233f](https://github.com/json-c/json-c/commit/833233faa8d6835276ebbd48b92c7feeb141270d)

**0.19 (2026-06-27)**
- 2024-09-02 → 2024-11-08 → 2025-04-03 — #867 strict mode disallows control characters — [6bfab90](https://github.com/json-c/json-c/commit/6bfab90c87c27e79eae28b775938756d2fdaf6c9). That check used a signed `c <= 0x1f`, so every byte 0x80 or above was rejected (#875, #892: U+00BA rejected); fixed with an `(unsigned char)` cast — [565f181](https://github.com/json-c/json-c/commit/565f181f656439847ef79650caad5c0b6c20171b). Keys had been missed and got the same check later — [7cee523](https://github.com/json-c/json-c/commit/7cee5237dc6c0831e3f9dc490394eaea44636861).
- 2024-11-17 — #881: `json_tokener_new_ex(0)` segfaulted; depth below 1 is now rejected — [ff8ed0f](https://github.com/json-c/json-c/commit/ff8ed0f094ddb48edad8169b711097f69fe8efea). (Local repro on master: `new_ex(0)` returns NULL; `new_ex(1)` rejects `[1]` with "nesting too deep".)
- 2025-07/08 — PR #893 "supplemental code points that look like high surrogates". `IS_HIGH_SURROGATE` / `IS_LOW_SURROGATE` masked with `0xFC00`, so an already-decoded supplementary code point (for example 0x1D800) was misclassified. The fix uses the mask `0xFFFFFC00` — merge [2372e95](https://github.com/json-c/json-c/commit/2372e9518e6ba95b48d37ec162bc7d93b297b52f).
- 2026-01-21 — #914: `newlocale` leak on macOS (about 1,472 bytes per parse); `NEWLOCALE_NEEDS_FREELOCALE` is now enabled automatically — [653a12c](https://github.com/json-c/json-c/commit/653a12c7c2f765f397fe74d34995262bd7fa92e0).
- 2026-04-24 — #923: `json_object_put()` recursion caused stack overflow on deep trees; the tokener's depth limit bounds parse depth but not the cost of freeing — [17328a6](https://github.com/json-c/json-c/commit/17328a6713418c91afc7d2e4d49a5647d84a7a3a).
- The 0.19 ChangeLog also lists: `json_tokener_free(NULL)` as a no-op, NaN→int handling (#880/#882), and #930 locale-dependent strtod in `json_object_get_double` — [ChangeLog 0.19](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/ChangeLog).

**Post-0.19 on master (2026-06-28 → 2026-11-19); none released yet**
- 2026-07-28 — strict mode accepted leading zeros (`01`), now rejected — [ff18c75](https://github.com/json-c/json-c/commit/ff18c75286d92045d37702e3ea59fea6b97241de).
- 2026-08-16 — strict mode now checks the full RFC 8259 number grammar; before, it accepted `.5`, `-.123`, `1.`, `2.e3` and `1e` (PR #957) — [e222189](https://github.com/json-c/json-c/commit/e222189360ff5a6201d42582a0fe15abc9d4cc11).
- 2026-08-01 — printbuf self-append use-after-free: when the appended source points into `p->buf`, `realloc` invalidates it; the fix saves the source offset across growth and switches to `memmove` (PR #955) — [62bb838](https://github.com/json-c/json-c/commit/62bb838c5734b863872c7c9ed4a8b6cbdb280714).
- 2026-08-17 — `json_parse_uint64` accepted a negative value behind a tab or newline. `strtoull` skips whitespace and then quietly negates a `-`, but the code only skipped spaces before checking for `-` (PR #958) — [510d68b](https://github.com/json-c/json-c/commit/510d68bd357403c3c734cf05a80f2ec622d36502).
- 2026-08-21 — object key leaked when insertion fails (PR #962) — [2094974](https://github.com/json-c/json-c/commit/2094974201fc75b07673110cc40a3e144cbd3b0d).
- 2026-09-28 — AIX leaked about 776 bytes per parse through `duplocale`. The per-call `duplocale + newlocale + uselocale` was replaced by a single static `newlocale(LC_NUMERIC_MASK,"C",0)` created lazily on first use, plus a destructor (PR #976) — [fd92d58](https://github.com/json-c/json-c/commit/fd92d58f2d2392aae2ec32d482871042531d0964).
- 2026-09-29 — `printbuf_memset` did not keep `buf[bpos]=='\0'`, so reading after `indent()` consumed uninitialized bytes (PR #980) — [b5cd62d](https://github.com/json-c/json-c/commit/b5cd62dcad3b5fbd5e33276f99073e1ff80a6a3a).
- 2026-10-05 — `json_tokener_validate_utf8` only checked byte framing. It accepted overlong forms (C0/C1 leads, E0 80–9F, F0 80–8F), UTF-16 surrogates (ED A0–BF) and code points above U+10FFFF (F4 90+, F5+). The fix keeps the lead byte in bits 8–15 of `nBytes` (PR #982) — [b99d91f](https://github.com/json-c/json-c/commit/b99d91fa659c1bd5f2e7fbc793099f19bac2fbac). Local repro: overlong, surrogate and above-U+10FFFF inputs are all rejected on master.
- 2026-10-10 — **[KNOWN] issue #984**: `json_tokener_reset()` did not clear `high_surrogate`, so the next document's `\u` escape could combine with a surrogate from the abandoned document (PR #986) — [7662139](https://github.com/json-c/json-c/commit/7662139501603434eba79aa7b916d1497d3d9cf4).
- 2026-10-15 — leak of the detached value when `json_object_object_add` / `json_object_array_add` fails. Found by allocation-failure injection (469 injection points); adds `tests/test_tokener_oom.c` (PR #987) — [e0a1735](https://github.com/json-c/json-c/commit/e0a173518f20640511def9842cea33183ddfe992).
- 2026-11-09 — strict-mode ERANGE number errors at a NUL-terminated EOF were overwritten with `parse_eof`. The fix sets `state = json_tokener_state_finish` before `goto out`, but **only on the two ERANGE branches** (PR #1002) — [99c14de](https://github.com/json-c/json-c/commit/99c14deceb959ee399018c74372250b2ce71f946).
- 2026-11-09 — **[KNOWN] PR #1001** content landed: `json_object_from_fd_ex` now passes `printbuf_length(pb) + 1`, so a top-level scalar at EOF in a file parses instead of returning "continue" — [0be2f37](https://github.com/json-c/json-c/commit/0be2f373614315f149cae2745a5a43319ec8d344).
- 2026-11-19 — serializers ignored `printbuf_memappend` and `json_escape_str` failures, giving "successful" output with an empty key or a missing number (PR #1012) — [d2ce61e](https://github.com/json-c/json-c/commit/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad).

**Open PRs as of 2026-11-22.** Titles come from each PR's head commit, read through `refs/pull/N/head`; the PR pages could not be read.
- **[KNOWN] #1006** "fix numbers split across json_tokener_parse_ex calls". It recomputes `neg_sign_ok` / `pos_sign_ok` from the last saved character, and changes the `-Infinity` check from `case_len <= 1` to `printbuf_length(tok->pb) == 1` — [PR #1006](https://github.com/json-c/json-c/pull/1006).
- **[KNOWN] #1014** "keep utf-8 validation state across json_tokener_parse_ex calls". It moves `nBytes` into the new field `tok->utf8_state`, only fails on an open sequence when the error is not `continue`, and clears the state in reset — [PR #1014](https://github.com/json-c/json-c/pull/1014).
- **[KNOWN] #1007** "reject object keys containing \u0000" — [PR #1007](https://github.com/json-c/json-c/pull/1007).
- **[KNOWN] #1013** "only keep RFC-valid number text for doubles": in non-strict mode `[1.]` re-serializes as `[ 1. ]`, which is not valid JSON — [PR #1013](https://github.com/json-c/json-c/pull/1013).
- Not on the team's list:
  - **#1010** linkhash: `LH_FREED` tombstones are not counted toward the load factor, so add/delete churn fills the table without resizing and every miss scans the whole table — [PR #1010](https://github.com/json-c/json-c/pull/1010).
  - **#1011** `printbuf_memappend_fast` macro evaluates its arguments twice; replaced with a static inline — [PR #1011](https://github.com/json-c/json-c/pull/1011).
  - **#1008** `json_pointer` index wraps on 32-bit — [PR #1008](https://github.com/json-c/json-c/pull/1008).
  - **#981** NULL guards across public APIs — [PR #981](https://github.com/json-c/json-c/pull/981).
- PRs #982, #987, #991, #1001, #1002 and #1012 landed on master as rebased commits. Their PR heads are not ancestors of master, so the PR pages may still show them open (git ancestry check in the clone).

### Inferences
- Six rounds of locale fixes have gone in: 2012 (setlocale), 2016 (#195, two commits), 2019 (#463), 2023 (#668), 2026-01 (#914) and 2026-09 (AIX, fd92d58). Each changed the lifecycle of the locale object. fd92d58 introduced a lazily created static global (see Q4, variant V3).
- The strict-mode rules have been tightened piece by piece: #867 control characters → #875 signed-char regression → keys missed → leading zeros → full number grammar. Each step left something accepted by strict mode. The same pattern suggests NaN/Infinity (still accepted under STRICT; see Q4) is the next item.

### Gaps
- I could not read issues #715 and #855, or the GitHub pages for PRs #1001, #1006, #1007, #1013 and #1014. github.com returned rate limits, and the API was refused by this session's proxy. I could not confirm whether #715 or #855 already cover variants V1–V3 in Q4. Neither number appears in `issues_closed_for_0.13`–`0.19.md` (grep), which is consistent with both being open.
- I did not read distribution patch sets. sources.debian.org, salsa.debian.org and src.fedoraproject.org were all refused by the proxy. Debian and Red Hat trackers show only the CVE backports listed in Q1.

---

## Q3. What has OSS-Fuzz found in json-c, which harnesses exist, and what do they not exercise?

### Takeaway
OSS-Fuzz has one public json-c finding: a 2020 global-buffer-overflow READ in `json_tokener_parse_ex`, introduced and fixed within a day. The main harness makes a single default-flag, non-NUL-terminated `json_tokener_parse_ex` call. It cannot reach chunk-boundary state, flags, reset or reuse, allocation failure, or the NUL/EOF epilogue. Those are exactly the areas where the 2026 bugs were found (by people, AI review and fault injection).

### Cited Findings
- **OSV-2020-252 / OSS-Fuzz issue 23619** (published 2020-06-26): "Global-buffer-overflow READ 4" in `json_tokener_parse_ex`, from `tokener_parse_ex_fuzzer.cc`. Introduced by `da76ee26` and fixed by `36118b68` — [OSV-2020-252](https://osv.dev/vulnerability/OSV-2020-252); [oss-fuzz-vulns yaml](https://github.com/google/oss-fuzz-vulns/blob/main/vulns/json-c/OSV-2020-252.yaml). This is the only file under `vulns/json-c/` in oss-fuzz-vulns (sparse clone checked 2026-11-22), and the only json-c entry OSV's OSS-Fuzz listing returned — [OSV list](https://osv.dev/list?ecosystem=OSS-Fuzz&q=json-c).
  - `da76ee2` is the 2020-06-20 merge of PR #633 ("support the surrogate pair in split file", issue #616) — [da76ee2](https://github.com/json-c/json-c/commit/da76ee26e7977cc4d796ed8c7e263d95cd94a199).
  - The fix `36118b6` rewrote the `\u` escape state and removed the code that compared `tok->pb->buf` against `utf8_replacement_char` with `strcmp` — [36118b6](https://github.com/json-c/json-c/commit/36118b681ea3b8e99735beee73cbd25a63e942cd). That global is declared `static unsigned char utf8_replacement_char[3] = {0xEF, 0xBF, 0xBD};` with no NUL terminator ([json_tokener.c @ d2ce61e](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L151)).
- **OSS-Fuzz configuration** — [oss-fuzz projects/json-c](https://github.com/google/oss-fuzz/tree/master/projects/json-c) (files read from a sparse clone, HEAD 2026-11-21):
  - engines: libfuzzer, afl, honggfuzz
  - sanitizers: address and undefined (no memory sanitizer, no thread sanitizer)
  - architectures: x86_64 and i386
  - the build compiles every `fuzz/*_fuzzer.cc` against a static lib built with `-DBUILD_TESTING=ON`; `run_tests.sh` runs `make test`
- **Harnesses in `fuzz/`** — [fuzz/ @ d2ce61e](https://github.com/json-c/json-c/tree/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/fuzz):
  - `tokener_parse_ex_fuzzer.cc`:
    - creates one tokener with `json_tokener_new()` (default depth 32), and never calls `json_tokener_set_flags`
    - makes a single `json_tokener_parse_ex(tok, data, size)` call, with `len = size`, so no terminating NUL is added
    - iterates object members if the result is an object, then serializes with `PRETTY|SPACED`
  - `json_array_fuzzer.cc`, `json_object_fuzzer.cc` and `json_pointer_fuzzer.cc` were added 2024-11-08 (PR #883) — [839fbe0](https://github.com/json-c/json-c/commit/839fbe0d63b58ecfd5b82578a02a24f03e5c359c). They mostly test object, array and pointer APIs, and get their inputs from `json_tokener_parse()` on short strings; `json_array_fuzzer` uses `ConsumeRandomLengthString(10)` three times.
  - All four dictionaries are the same 21 tokens (`{`, `}`, `e+`, `NaN`, `Infinity`, `-Infinity`, ...). There are no `\u` escapes, no `/*`, and no UTF-8 multibyte tokens.
- Harness maintenance history:
  - 2022-04-13 "Improve a bit the coverage" — [558d48a](https://github.com/json-c/json-c/commit/558d48a6f30a97939d0fd69e607481eff3cec33f)
  - 2023 issue #836 "Null pointer dereference in tokener_parse_ex_fuzzer.cc" was a harness bug (`json_object_object_foreach` on a non-object), fixed with a type check — [a907f7d](https://github.com/json-c/json-c/commit/a907f7dd1bd9885c9df728ce23663c32c2e3ecde); [issues_closed_for_0.18.md](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/issues_closed_for_0.18.md)
  - 2023-09-05 build fix — [1a7defa](https://github.com/json-c/json-c/commit/1a7defaa69cf32002d5434bb3ba297c7c218c760)
- The allocation-failure injection that found the 2026-10 leak ran as a unit test (`tests/test_tokener_oom.c`), not in OSS-Fuzz — [e0a1735](https://github.com/json-c/json-c/commit/e0a173518f20640511def9842cea33183ddfe992).

### Inferences
What the harnesses do not exercise, each tied to bugs that went unfound until 2026:
1. **Chunked feeding.** There is only one `parse_ex` call, so no differential between one-shot and split parsing. This is where the chunk bugs live: #616 surrogates (2020), the UTF-8 split [KNOWN #1014], the number sign and `-Infinity` [KNOWN #1006], and #984 reset (2026).
2. **Flags.** STRICT, VALIDATE_UTF8 and ALLOW_TRAILING_CHARS are never set. That leaves untested: the 2026 UTF-8 validator gaps (b99d91f), the strict-number grammar (ff18c75, e222189), the strict ERANGE-at-EOF bug (99c14de), and #875 (the strict control-character check that misfired on bytes ≥0x80).
3. **The NUL/EOF epilogue.** With `len = size`, the `if (!c)` path at the end of `out:` is reached only when the fuzz input contains an embedded 0x00. Top-level scalars at the end of input return `continue` and are never converted, so the number-conversion and error paths at EOF are barely covered. This is the V1 family in Q4.
4. **Reuse and reset.** One tokener is used per input. Multi-document streams, reuse after an error, and `json_tokener_reset` are never covered, which is why #984 was missed.
5. **Custom depth.** `json_tokener_new_ex(depth)` is never called, so the #881 depth=0 crash and boundary depths 1/2 are not covered.
6. **OOM.** No allocation-failure injection, so the e0a1735 leak, #857 and the 9e6acc9 truncation family are not covered.
7. **Threads.** No TSan run and no concurrent first use, so the race in Q4 V3 is not covered.
8. **Large inputs.** libFuzzer's default max_len makes the CVE-2020-12762-class INT_MAX paths unreachable.

A differential harness would cover items 1–4. It would split each input at every offset (or at fuzzer-chosen offsets), use a fuzzer-chosen flag byte and `+1` NUL, and assert identical (error, value, parse_end) results.

### Gaps
- OSS-Fuzz issue 23619 itself (bugs.chromium.org / issues.oss-fuzz.com) was not readable, so the faulting line is my inference from the fix diff, not confirmed.
- I could not list any non-public or still-embargoed OSS-Fuzz issues for json-c, or OSS-Fuzz coverage reports (introspector).

---

## Q4. Which root causes recur, and where might a variant still exist in current master (d2ce61e, 2026-11-19)?

### Takeaway
Six root-cause families recur:
- (A) per-call state that is lost, or rebuilt wrongly, across chunk boundaries
- (B) the shared `out:` epilogue overwriting or relabeling an already-set error
- (C) error and ownership handling on OOM and insertion failure
- (D) signed char and int-length arithmetic
- (E) locale-switching lifecycle
- (F) strict-mode grammar gaps

Local repro on master confirms three variants not covered by the known PRs, plus two conformance and API gaps:
- V1: strict-number errors at a NUL-terminated EOF are still misreported; 99c14de was a partial fix.
- V2: the UTF-8 epilogue relabels other errors and changes trailing-data semantics.
- V3: a TSan data race on the new static locale.
- V4 (conformance): STRICT accepts NaN and Infinity.
- V5 (API gap): `printbuf_memappend_fast` overlap and negative-size issues.

### Cited Findings — families with evidence

**(A) Chunk-boundary state loss.** Most of the parser's state lives in `struct json_tokener` (`pb`, `st_pos`, `is_double`, `ucs_char`, `high_surrogate`, `quote_char`, `stack[]`) — [json_tokener.h#L101-L121](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.h#L101-L121). The UTF-8 validator counter is a local, `unsigned int nBytes = 0;`, reset on every call — [json_tokener.c#L331](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L331). The number state does not save its micro-state; it rebuilds it from `tok->pb` and starts each resumed chunk with `neg_sign_ok = 1` — [json_tokener.c#L951-L974](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L951-L974).

Local repro on master:
- VALIDATE_UTF8 with `"\xc3` | `\xa9"` → `invalid utf-8 string` (one-shot succeeds) [KNOWN #1014]
- `[-1` | `Infinity]` → `[-Infinity]` (one-shot `[-1Infinity]` errors), because of `case_len <= 1` ([L1032](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L1032)) [KNOWN #1006]
- `[1` | `-2]` → `[1]`, silently accepted; one-shot gives `number expected` [KNOWN #1006]

The `[1-2]` case works because `json_parse_uint64` / `json_parse_int64` never check that `strtoull` / `strtoll` consumed the whole string (`end` is only compared with `buf`) — [json_util.c#L243-L286](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_util.c#L243-L286). With PRs #1006 and #1014 cherry-picked locally, all of these one-shot/chunked mismatches go away.

These chunk splits behave the same as one-shot on master (local repro), so they make good regression cases: `nu|ll`, `tr|ue`, `Inf|inity`, `[-|Infinity]`, `/|* c */`, `/*|*/`, `// x|\n`, a key split mid-string, `"\|n"`, `\ud83d|\ude00`, `\ud83d\|ude00`, `\ud83d\u|de00`, `1.|5`, `1e|5`, `1e|-5`, `1e-|5`, `-|1`, and `[0|1]` (strict errors; non-strict gives 1, same as one-shot `[01]`).

Earlier members of this family:
- #616 surrogates split across chunks (2020) — [a68566b](https://github.com/json-c/json-c/commit/a68566bf6a2b44b5932072e85261a971097bc0a9)
- exponent splits (2020) — [6eac698](https://github.com/json-c/json-c/commit/6eac6986c9a734b183e55a80e84fa67e58c637ff)
- `-`|`Infinity` (2017) — [48f7e38](https://github.com/json-c/json-c/commit/48f7e389fb90c3647d0c846694a9456a7bf8ca3f)
- reset not clearing `high_surrogate` (2026) — [7662139](https://github.com/json-c/json-c/commit/7662139501603434eba79aa7b916d1497d3d9cf4)

**(B) Errors overwritten or relabeled in the `out:` epilogue.** The epilogue runs three unconditional rewrites, in order — [json_tokener.c#L1389-L1406](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L1389-L1406):
1. `if (VALIDATE_UTF8 && nBytes != 0) err = parse_utf8_string`
2. the strict trailing-character check
3. `if (!c) { if (state != finish && saved_state != finish) err = parse_eof; }`

99c14de (2026-11-09) only worked around rule 3 on the two strict ERANGE branches, by setting `state = json_tokener_state_finish` before `goto out` ([L1130-L1152](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L1130-L1152)) — [99c14de](https://github.com/json-c/json-c/commit/99c14deceb959ee399018c74372250b2ce71f946).

- **V1 (NEW, local repro on master and on master+PR #1006+PR #1014).** In STRICT mode with the input NUL-terminated (`len = -1`, or `len` counting the NUL), `"01"`, `"-01"`, `"1."`, `"1e"`, `"1e+"` and `"1.e3"` all return `json_tokener_error_parse_eof` ("unexpected end of data"). The expected error is `json_tokener_error_parse_number`. The same inputs return `number expected` when followed by a space or wrapped in `[...]`. Only the ERANGE inputs (`99999999999999999999`, `-9999...`) return `number expected`. The strict grammar checks added in ff18c75 and e222189 ([L1038-L1103](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L1038-L1103)) and the generic `else { err = parse_number }` branch ([L1185-L1189](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L1185-L1189)) are all exposed to rule 3. Since 0be2f37, `json_object_from_fd_ex` / `json_object_from_file` pass the NUL, so file parsing now runs this path for every top-level scalar ([json_util.c#L135](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_util.c#L135)).
- **V2 (NEW, local repro).** Rule 1 rewrites whatever error was set while a lead byte is pending. VALIDATE_UTF8 with `[\xc3` gives `invalid utf-8 string`, where the same input without the flag gives `unexpected character`. The lead byte is validated in `PEEK_CHAR` ([L285-L294](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L285-L294)) before the state machine rejects it. Rule 1 also turns a successful parse into a failure because of lookahead bytes. With VALIDATE_UTF8, `[1]\xc3\xa9` and `[1]\xff` → `invalid utf-8 string` with no object. Without the flag, `[1]\xc3\xa9` → `[1]`, parse_end=3. PR #1014 keeps rule 1 for every non-`continue` exit, so it still relabels errors (read from the PR head diff).
- History of the family: 77a4276 (2016) added `goto out` on allocation failure without setting `tok->err`, so callers saw NULL with `success` — [77a4276](https://github.com/json-c/json-c/commit/77a4276a8c210e1faa2e8c13421e9a3d62772340). The 2022 and 2024 fixes then added the missing `json_tokener_error_memory` assignments — [9e6acc9](https://github.com/json-c/json-c/commit/9e6acc9a4eefe9f092aa3a3890a6e5c6ca2d5ed1), [31a22fb](https://github.com/json-c/json-c/commit/31a22fb2dabae30a759ae3346b493b44cedf1647).

**(C) OOM and ownership on error paths.** Members of this family:
- 2016: NULL with success (above)
- 2020→2021: UAF in `json_tokener_new_ex` (bcb6d7d→9361d8d)
- 2022: silent truncation (9e6acc9)
- 2024: ignored `json_object_object_add` result (#857)
- 2026: key leak (2094974), detached-value leak (e0a1735)
- 2026-11: double-format UAF on strdup failure, in json_object (0f8fe5d) — [0f8fe5d](https://github.com/json-c/json-c/commit/0f8fe5dd5382734d7668ab887873b2c3d7b2756f)

e0a1735's fix puts a `json_object_put(obj)` on the shared error exit ([L1422-L1425](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L1426-L1429)). Its correctness depends on `obj` being cleared on every successful transfer. Today only the array and object insert sites clear it.

**(D) Signed char and int-length arithmetic.**
- Signed char: #407 (2018, ctype on negative char), #645 (2020, tolower), #875 (2024, strict control-char check misfiring on bytes ≥0x80).
- `IS_HIGH_SURROGATE` 16-bit mask (2025, #893).
- int lengths: CVE-2013-6370 → CVE-2020-12762 → INT_MAX caps (2022), with the backwards check regression #599 in between.
- `char_offset` is still `int`, and `json_tokener_get_parse_end()` only `assert`s it is non-negative — [json_tokener.c#L1508-L1512](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L1512-L1516).
- **V5 (NEW, API/buffer, read from code).** The `printbuf.h` comment, updated alongside 62bb838, says "The source may point into p->buf, including a region that overlaps the appended destination". Yet the `printbuf_memappend_fast` macro's fast path still uses `memcpy`. Its guard `(p->size - p->bpos) > bufsize` passes for a negative `bufsize`, which then goes to `memcpy` as a huge `size_t`, and the slow path's return value is discarded — [printbuf.h#L48-L73](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/printbuf.h#L48-L73). Open PR #1011 turns it into an inline function but keeps `memcpy` and the same guard (PR head diff). The tokener no longer calls the macro (grep finds no use in library `.c` files), so this is a public-API hazard, not a parser-reachable bug.

**(E) Locale lifecycle.** History is in Q2. Since fd92d58 (2026-09-28), `json_tokener_parse_ex` lazily runs `if (c_numeric_locale == (locale_t)0) c_numeric_locale = newlocale(...)` on a file-scope static with no synchronization, and a destructor frees it at unload — [json_tokener.c#L318-L366](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L318-L366), [L1523-L1557](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L1523-L1557).
- **V3 (NEW, local repro with TSan).** Four threads calling `json_tokener_parse()` at the same moment of first use produce "ThreadSanitizer: data race ... Location is global 'c_numeric_locale'", with a read at line 357 racing a write at line 359. Possible effects: several `newlocale` objects, all but one leaked, and a race between the destructor and parses still running at `dlclose` or exit. The non-uselocale fallback still calls process-global `setlocale(LC_NUMERIC, "C")` on every parse ([L367-L381](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L367-L381)), the thread-unsafety #195 originally complained about. Separately, `linkhash`'s random-seed init is also "potentially racy" on compilers without compare-and-swap, per the source comment — [linkhash.c#L458-L492](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/linkhash.c#L458-L492).

**(F) Strict-mode grammar gaps.** These keep getting found one at a time: #867 control characters (2024), keys (2025), leading zeros (2026-07), the full number grammar (2026-08).
- **V4 (NEW conformance, local repro).** Under `JSON_TOKENER_STRICT`, `[NaN]`, `[Infinity]` and `[-Infinity]` parse successfully, although RFC 8259 does not allow them. Strict mode only enforces case: `[nan]` → `null expected`, `[TRUE]` → `boolean expected`. In non-strict mode, `[nAn]`, `[NULL]` and `[TRUE]` are accepted. The strict flag's documentation warns that it "may become more restrictive from one release to the next" — [json_tokener.h#L144-L159](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.h#L144-L159).
- Related [KNOWN #1007]: `{"a\u0000b":1,"a":2}` → `{"a":2}`. Keys are stored as C strings (`strdup`, and `lh_char_hash` hashes up to `strlen`), so `\u0000` truncates the key and lets it collide with another key (local repro; [linkhash.c#L491](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/linkhash.c#L491)).
- A raw 0x00 byte inside a string with an explicit `len` is treated as end of input (`"a\0b"` len 5 → `unexpected end of data`; local repro), because `if (!c) break;` treats the NUL as EOF ([L1384-L1386](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/json_tokener.c#L1384-L1386)).

**Hash-DoS residue (CVE-2013-6371 family).**
- The opt-in `JSON_C_STR_HASH_PERLLIKE` hash is unseeded (`unsigned hashval = 1;`), so an application that picks it with `json_global_set_string_hash()` can be hit by collision flooding again — [linkhash.c#L447-L456](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/linkhash.c#L447-L456).
- The default `lh_char_hash` uses a 32-bit seed from `json_c_get_random_seed()`. That draws on getrandom, /dev/urandom, RDRAND and finally the time; broken RDRAND detection was fixed in 0.15 (#588/#589) — [ChangeLog 0.15](https://github.com/json-c/json-c/blob/d2ce61eb214e4dac14b76b10de32a1cb7186d7ad/ChangeLog).
- Open PR #1010 (tombstone churn) is the third linkhash slot-accounting bug, after the 2009 hang and the 2012 infinite loop — [f5dd43a](https://github.com/json-c/json-c/commit/f5dd43a9d10abb2de50956d23505da08896f0c64), [64c0ca3](https://github.com/json-c/json-c/commit/64c0ca3690f98e978fd2fc8c6ca645243c27e3db). Pure parsing never deletes keys; duplicate keys replace the value in place, so the tokener cannot reach it.

### Inferences — targeted test ideas, ranked
1. **Differential chunking oracle (family A).** For every input and every split offset (including splitting into single bytes), with each flag combination and with or without a trailing NUL, require the same error, value and parse_end as a one-shot parse. On master this catches #1014 and #1006 [KNOWN]. It also guards the rewrite those PRs make: rebuilding `neg_sign_ok` from the last character, and the new `utf8_state` lifetime across successful multi-document calls.
2. **Error-code fidelity at EOF (V1, family B).** Assert `parse_number`, not `parse_eof`, for STRICT `01\0`, `-01\0`, `1.\0`, `1e\0`, `1e+\0` and `1.e3\0`, and for `json_object_from_file` on files containing those bytes once a strict-flag variant exists. More generally, inject each `goto out` error at the last byte before a NUL. Candidates: `error_memory` from `printbuf_memappend_checked`, `parse_null` on `nul\0`, `parse_boolean` on `tru\0`, the inf state on `Infin\0`. Then check whether rule 3 relabels them. This is an incomplete-fix pattern: 99c14de patched two call sites instead of the epilogue.
3. **UTF-8 error relabeling (V2).** With VALIDATE_UTF8, check every "unexpected char" error that follows a pending lead byte, and multi-document streams where the next document's first byte is not ASCII. Expected under PR #1014: still relabeled.
4. **Locale concurrency (V3).** Run a TSan test with N threads making their first `json_tokener_parse()` call at once, plus a run where `dlclose()` / exit happens during a parse. Run the AIX, macOS and FreeBSD `NEWLOCALE_NEEDS_FREELOCALE` combinations under LeakSanitizer.
5. **OOM sweep (family C).** Extend `tests/test_tokener_oom.c` to chunked parses and to the inf, nan and surrogate states, and assert that no error is reported as `success` and nothing leaks.
6. **Strict conformance (V4, F).** Check NaN, Infinity and -Infinity under STRICT. Check that key control characters are rejected after `\u` escapes (for example `{"\u0001":1}`, which is legal JSON and should be accepted, versus a raw 0x01, which should be rejected). Check `\u0000` in keys [KNOWN #1007] and a raw NUL inside keys and strings with an explicit `len`.
7. **Cumulative INT_MAX (family D).** Feed more than 2^31 bytes of one string in 64 KB chunks and expect a clean error, not `success` and not a crash. Large-memory CI only.

### Gaps
- I did not test 32-bit builds. OSS-Fuzz does run i386; CVE-2013-6370 and PR #1008 are 32-bit specific.
- I could not tell whether issues #715 or #855 [KNOWN] already describe V1, V2 or V3, because those pages were not readable.
- I did not check MSVC/Windows (the DllMain destructor in e77ca4f, from PR #991) or setlocale-only platforms at runtime.
- The V5 assessment (`printbuf_memappend_fast` negative size and overlap) comes from reading the code only; no test was run.
