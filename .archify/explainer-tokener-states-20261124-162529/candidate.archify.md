# What does each json_tokener state do? {#tokener-states}

The tokener keeps **one small record per nesting level** on a stack. Each record says what the level does with the next byte (`state`), where it goes after whitespace (`saved_state`), what value it is building (`current`) and which object key is pending (`obj_field_name`). The **27 states** are the steps of reading one value. A container never reads its own elements: it pushes a new level for each element and adds the result when that level finishes.

- Most states finish by setting `saved_state` to their next step and `state` to `eatws`, so whitespace and comments are handled in one place.[](source:loop)
- Fields shared by all levels (`pb`, `st_pos`, `quote_char` and others) hold the token being read right now, such as the text of a string or number.[](source:structs)
- A local variable, `obj`, carries a finished child value from the child's `finish` state to its parent's `array_add` or `object_value_add`.[](source:finish)
- Every example on this page is a measured trace of the baseline, taken with a stack dump added at `redo_char:` in a scratch copy.

@answer scope="json-c d2ce61e · json_tokener.c and json_tokener.h · traces measured 2026-11-24 with a print at redo_char: (scratch copy, not committed)"
@meta locale=en
@source structs title="struct json_tokener_srec and struct json_tokener" path=json-c/json_tokener.h lines=84:121
@source states title="enum json_tokener_state" path=json-c/json_tokener.h lines=50:79
@source newex title="json_tokener_new_ex: the stack is one array of max_depth records" path=json-c/json_tokener.c lines=153:179
@source resetlevel title="json_tokener_reset_level" path=json-c/json_tokener.c lines=196:204
@source macros title="state, saved_state, current, obj_field_name are macros" path=json-c/json_tokener.c lines=262:265
@source loop title="Main loop, eatws and start" path=json-c/json_tokener.c lines=385:485
@source finish title="finish: pop a level and hand the value to the parent" path=json-c/json_tokener.c lines=487:493
@source literals title="inf and null/NaN" path=json-c/json_tokener.c lines=495:588
@source comments title="Comment states" path=json-c/json_tokener.c lines=590:655
@source strings title="string and the escape states" path=json-c/json_tokener.c lines=657:892
@source boolean title="boolean" path=json-c/json_tokener.c lines=896:943
@source number title="number" path=json-c/json_tokener.c lines=945:1194
@source arrays title="Array states" path=json-c/json_tokener.c lines=1196:1256
@source objects title="Object states" path=json-c/json_tokener.c lines=1258:1382

## What data does the state machine keep? {#data}

@erd id=tokener-structs title="The tokener and its stack of level records"
| entity tok | struct json_tokener |
| entity srec | struct json_tokener_srec |
| tok.stack | srec pointer |
| tok.depth | int |
| tok.max_depth | int |
| tok.pb | printbuf pointer |
| tok.st_pos | int |
| tok.is_double | int |
| tok.quote_char | char |
| tok.ucs_char | unsigned int |
| tok.high_surrogate | unsigned int |
| tok.char_offset | int |
| tok.err | enum json_tokener_error |
| tok.flags | int |
| srec.state | enum json_tokener_state |
| srec.saved_state | enum json_tokener_state |
| srec.current | json_object pointer |
| srec.obj_field_name | char pointer |
| tok > srec | one:many | stack, max_depth records |

| Per-level field (`stack[i]`) | What it holds |
| --- | --- |
| `state` | What this level does with the next byte |
| `saved_state` | Where `eatws` sends the level after whitespace and comments |
| `current` | The value this level is building: `{}` growing to `{"a":1}`, or a finished `1` |
| `obj_field_name` | The key of the member being parsed, from the key's end until the member is added |

| Shared field (`tok`) | What it holds |
| --- | --- |
| `depth`, `max_depth` | Which record is the current level; how many records exist (default 32) |
| `pb` | Text of the token being read: a string, key, number, literal or comment |
| `st_pos` | Position inside `true`, `null`, `Infinity` or the 4 hex digits of `\uXXXX` |
| `quote_char` | The quote that opened the current string or key, `"` or `'` |
| `ucs_char`, `high_surrogate` | The code point being decoded; a pending first half of a surrogate pair |
| `is_double` | Whether the number has `.` or `e`, so it becomes a double |
| `char_offset`, `err`, `flags` | Bytes read in this call; the result code; the STRICT and UTF-8 options |

@facts
| No real variables | `state`, `saved_state`, `current` and `obj_field_name` are macros for `tok->stack[tok->depth]`, so they always mean the current level |
| Fixed array | `json_tokener_new_ex(depth)` allocates `depth` records once; push is `depth++`, pop is `depth--` |
| Unused fields | `srec.obj` and `tok->str` exist in the structs but the parser never uses them; it hands values over in a local `obj` |

## How does a level get pushed and popped? {#push-pop}

@steps id=push-pop-steps
| p-push | Push | `array` and `object_value` check `depth < max_depth - 1` (else error `depth`), set their own state to `array_add` or `object_value_add`, then `depth++`. |
| p-reset | New level | `json_tokener_reset_level` sets the new record to `state = eatws`, `saved_state = start`, `current = NULL`, no key. The same byte is then re-checked on the new level. |
| p-child | Child parses | The child level runs through `start` and the states for its kind of value, building its own `current`. |
| p-pop | Pop | The child's `finish` sets `obj` to its `current`, resets the child record, `depth--`, and re-checks the same byte on the parent. |
| p-add | Parent adds | The parent is waiting in `array_add` or `object_value_add`, so it adds `obj` to its own `current` and moves on to `eatws`, then a separator state. |

Because the limit check is `depth < max_depth - 1`, a depth limit counts values, not containers: `json_tokener_new_ex(1)` rejects `[1]`.[](source:resetlevel)

## What do the flow-control states do? {#flow}

| State | What it does | Next state |
| --- | --- | --- |
| `eatws` | Skips whitespace. A `/` outside STRICT mode starts a comment. Any other byte is re-checked in `saved_state`. | `saved_state`, or `comment_start` |
| `start` | Reads the first byte of a value and picks its kind: `{` creates an empty object, `[` an empty array; quote, `t`/`f`, `n`, `i`, digit or `-` start a string, literal or number. Anything else is error `parse_unexpected`. | `eatws` (then `object_field_start` or `array`), or a value state |
| `finish` | The level's value is complete. At depth 0 the call jumps to `out:` and returns it. Deeper, it pops and hands `current` to the parent in `obj`. | Parent's `array_add` or `object_value_add` |

## What do the comment states do? {#comments}

Comments are allowed only outside STRICT mode. They leave `saved_state` untouched, so parsing resumes exactly where it was.[](source:comments)

| State | What it does | Next state |
| --- | --- | --- |
| `comment_start` | After `/`: a `*` starts a block comment and a second `/` a line comment; anything else is error `parse_comment` | `comment` or `comment_eol` |
| `comment` | Inside `/* */`: skips bytes up to the next `*` | `comment_end` |
| `comment_end` | After a `*`: a `/` closes the comment, anything else goes back. A second `*` is lost here (bug hunt finding 2). | `eatws` or `comment` |
| `comment_eol` | Inside `//`: skips bytes up to the newline | `eatws` |

Measured on `[/*x*/1]`: level 0 stays `array` as its `saved_state` through `comment_start`, `comment` and `comment_end`, then `eatws` hands `1` to `array`. Every comment byte is also copied into `pb`, which nothing reads (finding 7).

## What do the string states do? {#strings}

| State | What it does | Next state |
| --- | --- | --- |
| `string` | Copies bytes into `pb` until the closing `quote_char`, then creates the string in `current`. In STRICT mode a control byte is error `parse_string`. | `eatws` (then `finish`), or `string_escape` on a backslash |
| `string_escape` | The byte after a backslash: quote, backslash and `/` are copied; `b f n r t` become control characters; `u` starts a code point. Others are error `parse_string`. | `saved_state` (`string` or `object_field`), or `escape_unicode` |
| `escape_unicode` | Reads 4 hex digits into `ucs_char`, counting with `st_pos`, then writes UTF-8 into `pb`. A first surrogate half is kept in `high_surrogate`. | `saved_state`, or `escape_unicode_need_escape` |
| `escape_unicode_need_escape` | After a first surrogate half, expects a backslash. Otherwise writes U+FFFD and re-checks the byte. | `escape_unicode_need_u`, or `saved_state` |
| `escape_unicode_need_u` | After that backslash, expects `u` for the second half. Otherwise writes U+FFFD and treats it as a normal escape. | `escape_unicode`, or `string_escape` |

Measured on `["hé"]`: `string` copies `h` into `pb`, stops at the backslash, `string_escape` sees `u`, and `escape_unicode` turns `00e9` into `é`. Then `string` reaches the closing quote with `pb` holding `hé`.[](source:strings)

## What do the literal and number states do? {#literals}

| State | What it does | Next state |
| --- | --- | --- |
| `null` | Matches `null` or `NaN` one byte per visit, counting with `st_pos`. Case is ignored outside STRICT mode. Creates `NULL` or a NaN double; a mismatch is error `parse_null`. | `eatws` (then `finish`) |
| `boolean` | Same for `true` and `false`; a mismatch is error `parse_boolean` | `eatws` (then `finish`) |
| `inf` | Matches `Infinity` byte by byte and creates ±Infinity. The minus sign comes from `pb`, where `number` left it. | `eatws` (then `finish`) |
| `number` | Copies digits, `-`, `+`, `.`, `e` into `pb` while they fit the number's shape. Then it creates an int64, uint64 or double. STRICT mode checks the RFC grammar first. | `eatws` (then `finish`), or `inf` after `-I` |

A literal or number is complete only when the next byte arrives. In the trace of `[true]`, `pb` holds `true]` at the moment `boolean` creates the value, and the `]` is then re-checked by the parent.[](source:boolean)

## How is an array parsed? {#arrays}

| State | What it does | Next state |
| --- | --- | --- |
| `array` | Right after `[`: a `]` closes an empty array. Any other byte pushes a level for the first element. | `eatws` (then `finish`), or `array_add` while the child parses |
| `array_add` | The child finished: appends `obj` to `current` | `eatws` (then `array_sep`) |
| `array_sep` | A `,` means another element; a `]` closes the array. Anything else is error `parse_array`. | `eatws` (then `array_after_sep` or `finish`) |
| `array_after_sep` | After a comma. Same code as `array`, but a `]` here is a trailing comma, an error in STRICT mode. | `array_add` while the child parses |

Measured stack after each byte of `[1,[2]]`. Each level is shown as `state / saved_state / current`.

| Byte | Stack after this byte |
| --- | --- |
| `[` (0) | L0 `eatws / array / []` |
| `1` (1) | L0 `array_add / array / []` · L1 `eatws / finish / 1` |
| `,` (2) | L0 `eatws / array_after_sep / [1]`; L1 was popped and `obj` = 1 was appended |
| `[` (3) | L0 `array_add / array_after_sep / [1]` · L1 `eatws / array / []` |
| `2` (4) | L0 `array_add / array_after_sep / [1]` · L1 `array_add / array / []` · L2 `eatws / finish / 2` |
| `]` (5) | L0 `array_add / array_after_sep / [1]` · L1 `eatws / finish / [2]`; L2 was popped into L1 |
| `]` (6) | L0 `eatws / finish / [1,[2]]`; L1 was popped into L0 |
| end (7) | L0 `finish` at depth 0: the call returns `[1,[2]]` |

The `1` is not added at byte 1. It is added at byte 2, because the number only ends when the `,` arrives. While a level waits in `array_add`, its `saved_state` is a leftover from the step before; it is overwritten as soon as the level resumes.[](source:arrays)

## How is an object parsed? {#objects}

| State | What it does | Next state |
| --- | --- | --- |
| `object_field_start` | Right after `{`: a `}` closes an empty object. A quote starts a key; even a single quote is accepted in STRICT mode (finding 4). Anything else is error `parse_object_key_name`. | `object_field`, or `eatws` (then `finish`) |
| `object_field` | Copies key bytes into `pb` until the closing quote, then copies the key into `obj_field_name` | `eatws` (then `object_field_end`), or `string_escape` |
| `object_field_end` | Expects `:`, else error `parse_object_key_sep` | `eatws` (then `object_value`) |
| `object_value` | Pushes a level for the member's value | `object_value_add` while the child parses |
| `object_value_add` | The child finished: adds `obj` to `current` under `obj_field_name`, then frees the key | `eatws` (then `object_sep`) |
| `object_sep` | A `,` means another member; a `}` closes the object. Anything else is error `parse_object_value_sep`. | `eatws` (then `object_field_start_after_sep` or `finish`) |
| `object_field_start_after_sep` | After a comma. Same code as `object_field_start`, but a `}` here is a trailing comma, an error in STRICT mode. | `object_field` |

@sequence id=object-levels title="Levels while parsing the object example (measured)"
| actor l0 | Level 0: the object | backend |
| actor l1 | Level 1 | backend |
| actor l2 | Level 2 | backend |
| phase | Member "a" |
| l0 | l1 | push at 1, key "a" waiting in L0 |
| l1 | l0 | obj = 1, added at the comma | return |
| phase | Member "b" |
| l0 | l1 | push at [, key "b" waiting in L0 |
| l1 | l2 | push at t, first element |
| l2 | l1 | obj = true, appended at ] | return |
| l1 | l0 | obj = [true], added at } | return |

Measured stack after each byte of `{"a":1,"b":[true]}`. Each level is shown as `state / saved_state / current`, plus its key when it has one.

| Byte | Stack after this byte |
| --- | --- |
| `{` (0) | L0 `eatws / object_field_start / {}` |
| `"a"` (1–3) | L0 `eatws / object_field_end / {}`, key `a` |
| `:` (4) | L0 `eatws / object_value / {}`, key `a` |
| `1` (5) | L0 `object_value_add / object_value / {}`, key `a` · L1 `eatws / finish / 1` |
| `,` (6) | L0 `eatws / object_field_start_after_sep / {"a":1}`, key freed |
| `"b"` (7–9) | L0 `eatws / object_field_end / {"a":1}`, key `b` |
| `:` (10) | L0 `eatws / object_value / {"a":1}`, key `b` |
| `[` (11) | L0 `object_value_add / object_value / {"a":1}`, key `b` · L1 `eatws / array / []` |
| `true` (12–15) | L0 waiting, key `b` · L1 `array_add / array / []` · L2 `boolean / start / NULL`, `pb` = `true` |
| `]` (16) | L0 waiting, key `b` · L1 `eatws / finish / [true]`; L2 was popped into L1 |
| `}` (17) | L0 `eatws / finish / {"a":1,"b":[true]}`; L1 was popped into L0 |
| end (18) | L0 `finish` at depth 0: the call returns the object |

The key lives in the parent level, not the child: level 0 holds `b` while levels 1 and 2 build `[true]`.[](source:objects)
