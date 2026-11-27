# How does json_tokener_parse_ex read JSON? {#parse-ex}

`json_tokener_parse_ex` is one loop that reads the input **one byte at a time** and hands each byte to the current state of a **27-state machine**. Each nesting level keeps its own state on a stack inside the tokener. So when the input runs out mid-value, the call returns "continue" and the next call resumes at the same place.

- Each state handles a byte in one of three ways: consume it (`break`), look at it again in a new state (`goto redo_char`), or stop (`goto out`).[](source:loop)
- `[` or `{` opens a container. Each child value is parsed one level deeper and handed back to the parent when it finishes.[](source:array)
- Everything the next call needs is stored in the tokener `tok`. A few local variables are not, and those cause known bugs when input arrives in pieces.
- A final block, `out:`, decides the error code and, after a success, resets the tokener for the next document.[](source:out)

@answer scope="json-c d2ce61e · json_tokener.c lines 327–1433 (about 1,100 lines) · traces measured with a print added at redo_char: in a scratch copy"
@meta locale=en
@source header title="States, per-level record and tokener struct" path=json-c/json_tokener.h lines=50:121
@source macros title="state, saved_state, current and obj_field_name are macros over the stack" path=json-c/json_tokener.c lines=262:265
@source peek title="PEEK_CHAR and ADVANCE_CHAR: how a byte is read and consumed" path=json-c/json_tokener.c lines=280:301
@source entry title="Entry: length check and C-numeric locale" path=json-c/json_tokener.c lines=327:383
@source loop title="Main loop, eatws, start and finish" path=json-c/json_tokener.c lines=385:493
@source literals title="inf, null/NaN and the comment states" path=json-c/json_tokener.c lines=495:655
@source strings title="String state and escape states" path=json-c/json_tokener.c lines=657:892
@source boolean title="Boolean state" path=json-c/json_tokener.c lines=896:943
@source number title="Number state, resume logic and strict grammar" path=json-c/json_tokener.c lines=945:1194
@source array title="Array states" path=json-c/json_tokener.c lines=1196:1256
@source object title="Object states" path=json-c/json_tokener.c lines=1258:1387
@source out title="The out: epilogue" path=json-c/json_tokener.c lines=1389:1433
@source resetlevel title="json_tokener_reset_level" path=json-c/json_tokener.c lines=196:204
@source bugs title="Bug hunt findings 1–8" path=bughunt/README.md lines=5:78

## What happens in one call? {#one-call}

@workflow id=call-loop title="One call of json_tokener_parse_ex"
| entry | Check length, set locale | backend |
| peek | Bytes left? | backend |
| dispatch | Run current state | backend |
| redo | Same byte, new state | backend |
| advance | Consume the byte | backend |
| out | Epilogue out: | security |
| ret | Return object or NULL | external |
| entry > peek | |
| peek > dispatch | yes |
| peek > out | no |
| dispatch > advance | break |
| dispatch > redo | goto redo_char |
| redo > dispatch | |
| dispatch > out | goto out | dashed |
| advance > peek | next byte |
| out > ret | | emphasis |

@steps id=call-steps
| s-entry | Check length, set locale | Rejects `len < -1`, then switches to the C number locale so `1.5` parses the same everywhere. | call-loop | entry |
| s-peek | Bytes left? | `PEEK_CHAR` reads the next byte. At the end of the input it sets "success" if a top-level value is complete, otherwise "continue". With `VALIDATE_UTF8` it also checks the byte. | call-loop | peek |
| s-dispatch | Run current state | A `switch` on the current level's state. Strings, comments, numbers and keys use inner loops that read many bytes at once. | call-loop | dispatch |
| s-redo | Same byte, new state | `goto redo_char` re-runs the switch on the same byte, for example when `eatws` finds a non-space byte and hands it to the saved state. | call-loop | redo |
| s-advance | Consume the byte | `ADVANCE_CHAR` moves on one byte. After a NUL byte the loop stops: NUL means end of text. | call-loop | advance |
| s-out | Epilogue out: | Sets end-of-input, trailing-character and UTF-8 errors, restores the locale, and resets the levels after a success. | call-loop | out |

## What are the 27 states? {#states}

| Group | States (`json_tokener_state_` prefix dropped) |
| --- | --- |
| Flow control (3) | `eatws`, `start`, `finish` |
| Comments (4) | `comment_start`, `comment`, `comment_eol`, `comment_end` |
| Strings (5) | `string`, `string_escape`, `escape_unicode`, `escape_unicode_need_escape`, `escape_unicode_need_u` |
| Literals and numbers (4) | `null` (also NaN), `boolean`, `inf`, `number` |
| Arrays (4) | `array`, `array_add`, `array_sep`, `array_after_sep` |
| Objects (7) | `object_field_start`, `object_field_start_after_sep`, `object_field`, `object_field_end`, `object_value`, `object_value_add`, `object_sep` |

@facts
| The switch | 25 `case` bodies: `array` shares its code with `array_after_sep`, and `object_field_start` with `object_field_start_after_sep` |
| `eatws` | A trampoline: skips whitespace and comments, then jumps to the level's `saved_state` |
| Literals | `true`, `null` and `Infinity` are matched one byte per visit, counting with `tok->st_pos`; outside STRICT mode case is ignored |

## How do the states of one level connect? {#level-states}

@diagram lifecycle id=array-level source=array-level.lifecycle.json title="An array level"

@diagram lifecycle id=object-level source=object-level.lifecycle.json title="An object level"

Every level starts in `start` and ends in `finish`. A container never parses its own children: `array` and `object_value` push a new level, and the child's `finish` pops back into `array_add` or `object_value_add`.[](source:object)

## What does a real parse look like? {#trace}

Measured trace of `[1,{"a":true}]` passed in one call: **42 state visits** on three levels (14 on level 0, 19 on level 1, 9 on level 2). Each row lists the states that saw that byte, with the level number in front.

| Byte (offset) | States visited, in order |
| --- | --- |
| `[` (0) | L0 eatws → start, which opens an array |
| `1` (1) | L0 eatws → array, which pushes L1: eatws → start → number |
| `,` (2) | L1 eatws → finish, which pops to L0: array_add → eatws → array_sep |
| `{` (3) | L0 eatws → array_after_sep, which pushes L1: eatws → start |
| `"` (4) | L1 eatws → object_field_start |
| `a"` (5–6) | L1 object_field: the inner loop reads the key up to the closing quote |
| `:` (7) | L1 eatws → object_field_end |
| `t` (8) | L1 eatws → object_value, which pushes L2: eatws → start → boolean |
| `rue` (9–11) | L2 boolean, once per byte |
| `}` (12) | L2 boolean: the byte after `true` completes it → eatws → finish, which pops to L1: object_value_add → eatws → object_sep |
| `]` (13) | L1 eatws → finish, which pops to L0: array_add → eatws → array_sep |
| NUL (14) | L0 eatws → finish, which at depth 0 jumps to `out:` |

A number or literal ends only when the next byte arrives. So `[1]` needs the `]`, and a top-level `true` needs the final NUL or another call.

## What happens when the input runs out? {#chunks}

@sequence id=two-calls title="One document over two calls (measured)"
| actor app | Caller | frontend |
| actor tok | json_tokener_parse_ex | backend |
| actor saved | Tokener fields | database |
| app | tok | parse `{"a":tr` (7 bytes) |
| tok | saved | L0 waits in object_value_add, key "a" |
| tok | saved | L1 in boolean, pb "tr", st_pos 2 |
| tok | app | NULL, continue, parse end 7 | return |
| app | tok | parse `ue}` plus NUL | emphasis |
| saved | tok | resume L1 boolean at "u" | return |
| tok | app | {"a":true}, success, parse end 3 | return |

| Kept in the tokener, so it survives | What it holds |
| --- | --- |
| `stack[depth]`: state, saved_state, current, obj_field_name | Where each level is, its partly built container and its key |
| `depth`, `max_depth` | Current nesting level and the limit (default 32) |
| `pb` | Text of the current string, key, number or literal so far |
| `st_pos`, `ucs_char`, `high_surrogate` | Position inside a literal or `\uXXXX`, and the code point being decoded |
| `quote_char`, `is_double` | Which quote opened the string; whether the number has `.` or `e` |

| Local only, so lost at return | Effect when input is split |
| --- | --- |
| `obj` | None: a finished child is handed to its parent within the same call |
| `nBytes` (UTF-8 progress) | A multi-byte character split across calls fails with `VALIDATE_UTF8` (open PR #1014) |
| `is_exponent`, `neg_sign_ok`, `pos_sign_ok` | Rebuilt from `pb` with `strchr` on every resume: quadratic time (finding 6) and wrong results such as `[12` + `-3]` giving `[12]` (open PR #1006) |

## What does the out: epilogue decide? {#epilogue}

@steps id=out-steps
| e-utf8 | Incomplete UTF-8 | With `VALIDATE_UTF8`, a pending multi-byte count (`nBytes != 0`) becomes `parse_utf8_string`. This is where findings 3 and 3b come from. |
| e-trailing | Trailing characters | Stopped on a byte at depth 0 in `finish`, with STRICT but not `ALLOW_TRAILING_CHARS`: `parse_unexpected`. |
| e-eof | End of text too early | Hit the NUL while neither `state` nor `saved_state` is `finish`: `parse_eof`. It can overwrite an earlier error (finding 5) and miss an open comment (finding 1). |
| e-locale | Restore locale | Puts back the caller's number locale. |
| e-success | Success or failure | On success, take a reference to `current`, reset every level from `depth` down to 0, and return it. Otherwise release `obj` and return NULL. |

## Where do the known bugs live? {#bugs}

| Bug hunt finding | Where in the function |
| --- | --- |
| 1. `[1,2/*` returns `2` | Comment states jump to `out:`, and the EOF check passes because `saved_state` is still `finish` |
| 2. `/** x **/` is not closed | `comment_end` sends a second `*` back to `comment`, which then skips the next byte |
| 3, 3b. UTF-8 errors after a value | `PEEK_CHAR` validates the lookahead byte; `out:` turns the pending count into an error |
| 4. STRICT accepts `{'a':1}` | `object_field_start` accepts `'` with no STRICT check |
| 5. Memory error reported as EOF | The `out:` EOF check overwrites `json_tokener_error_memory` |
| 6. Quadratic chunked numbers | `number` rescans all saved digits with `strchr` on every resume |
| 7. Comments held in memory | Comment states append every byte to `pb`, which nothing reads |
| 8. Locale race between threads | Entry creates `c_numeric_locale` lazily without a lock |

The gate treats fixing any of these as a change in behaviour, so a refactor must keep them.[](source:bugs)

## What must a split into per-state functions keep? {#split}

- `state`, `saved_state`, `current` and `obj_field_name` are macros for `tok->stack[tok->depth]`, so their meaning changes whenever `depth` changes.[](source:macros)
- Each state ends in one of three ways: consume, re-check the same byte, or stop. A state function has to report which one.
- `printbuf_memappend_checked` hides a `goto out` inside a macro, so memory errors leave from deep inside loops.
- `obj`, `c`, `str` and `nBytes` are shared by all states within one call and must be passed between the new functions.
- State the next call needs must stay in `tok`. The struct in `json_tokener.h` is fixed, so there is no room for new fields, and a `static` variable would be shared by every tokener.[](source:header)
