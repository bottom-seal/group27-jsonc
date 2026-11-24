/*
 * Recorder: parses each input with json_tokener_parse_ex and prints what the
 * tokener answered, so two builds (baseline and candidate) can be compared.
 *
 * Input (stdin): one JSON document per line. "\xNN" stands for the byte 0xNN,
 * so documents can contain newlines, NUL bytes and invalid UTF-8.
 *
 * Usage: recorder ANSWERS_FILE < inputs
 *
 * Output (ANSWERS_FILE): for every input and every way of asking the tokener
 * (see record_input), one tab-separated record
 *
 *     <input index> <config> <type signature> <error> <parse end> <value>
 *
 * then the answers to the edge-case API calls (record_api), filed under the
 * index one past the last input, and a final line "#done <number of inputs
 * read>". Before each input (and before the API calls) a line "#input <index>"
 * is written and flushed, so if the candidate crashes the checker knows which
 * input it was working on.
 *
 * The answers go to their own file, not stdout, so anything the tokener itself
 * prints cannot corrupt them; the checker compares stdout separately.
 *
 * Linked with -Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup
 * (see record_memory_failures) and run with LOCPATH pointing at a de_DE.UTF-8
 * locale (see record_locale); check.py does both.
 *
 * Adapted from bughunt/mutation/mut_driver.c.
 */
#include <ctype.h>
#include <limits.h>
#include <locale.h>
#include <sanitizer/lsan_interface.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "json.h"

static FILE *out; /* the answers file */

struct config
{
	const char *name;
	int flags;
};

/* All 8 combinations of the three flags. The first NFEW are used where
 * running all 8 would cost too much. */
static const struct config CONFIGS[] = {
    {"default", 0},
    {"strict", JSON_TOKENER_STRICT},
    {"utf8", JSON_TOKENER_VALIDATE_UTF8},
    {"strict+utf8", JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8},
    {"strict+trailing", JSON_TOKENER_STRICT | JSON_TOKENER_ALLOW_TRAILING_CHARS},
    {"strict+trailing+utf8",
     JSON_TOKENER_STRICT | JSON_TOKENER_ALLOW_TRAILING_CHARS | JSON_TOKENER_VALIDATE_UTF8},
    {"trailing", JSON_TOKENER_ALLOW_TRAILING_CHARS},
    {"trailing+utf8", JSON_TOKENER_ALLOW_TRAILING_CHARS | JSON_TOKENER_VALIDATE_UTF8},
};
#define NCONFIGS (sizeof(CONFIGS) / sizeof(CONFIGS[0]))
#define NFEW 3 /* default, strict, utf8 */

/* Type signature of the value tree. The serialized value alone hides some
 * changes, so the type of every node is recorded too: n=null b=boolean
 * i=int U=uint64 above INT64_MAX o=object a=array s=string, and d(<value>)
 * for a double. json-c serializes a parsed double from its original text, so
 * a wrong numeric value would print exactly like the right one; the value is
 * therefore recorded in %a (hex float) form, which is exact. */
static void print_signature(json_object *o)
{
	if (!o)
	{
		fputc('n', out);
		return;
	}
	enum json_type ty = json_object_get_type(o);
	if (ty == json_type_int)
		fputc(json_object_get_int64(o) == INT64_MAX &&
		                json_object_get_uint64(o) > (uint64_t)INT64_MAX
		            ? 'U'
		            : 'i', out);
	else if (ty == json_type_double)
		fprintf(out, "d(%a)", json_object_get_double(o));
	else
		fputc("nbdioas"[ty], out); /* indexed by enum json_type, see json_types.h */
	if (ty == json_type_array)
	{
		fputc('[', out);
		for (size_t i = 0; i < json_object_array_length(o); i++)
			print_signature(json_object_array_get_idx(o, i));
		fputc(']', out);
	}
	if (ty == json_type_object)
	{
		fputc('{', out);
		json_object_object_foreach(o, key, val)
		{
			(void)key;
			print_signature(val);
		}
		fputc('}', out);
	}
}

static int hex_value(char c)
{
	return isdigit((unsigned char)c) ? c - '0' : tolower((unsigned char)c) - 'a' + 10;
}

/* Decode "\xNN" (exactly two hex digits) into one byte; everything else is
 * copied. check.py rejects input files with any other "\x". */
static size_t decode_line(const char *line, size_t len, char *buf)
{
	size_t n = 0;
	for (size_t i = 0; i < len; i++)
	{
		if (i + 3 < len && line[i] == '\\' && line[i + 1] == 'x' &&
		    isxdigit((unsigned char)line[i + 2]) && isxdigit((unsigned char)line[i + 3]))
		{
			buf[n++] = (char)(hex_value(line[i + 2]) * 16 + hex_value(line[i + 3]));
			i += 3;
		}
		else
			buf[n++] = line[i];
	}
	buf[n] = '\0';
	return n;
}

/* One answer line. err < 0 or end < 0 print "-": json_tokener_parse() has
 * no tokener to ask. Takes ownership of obj. */
static void write_answer(size_t index, const char *mode, const char *flags, json_object *obj,
                         int err, long end)
{
	fprintf(out, "%zu\t%s%s%s\t", index, mode, flags ? "/" : "", flags ? flags : "");
	print_signature(obj);
	if (err < 0)
		fputs("\t-", out);
	else
		fprintf(out, "\t%d %s", err, json_tokener_error_desc((enum json_tokener_error)err));
	if (end < 0)
		fputs("\t-", out);
	else
		fprintf(out, "\t%ld", end);
	fprintf(out, "\t%s\n", obj ? json_object_to_json_string_ext(obj, JSON_C_TO_STRING_PLAIN) : "-");
	json_object_put(obj);
}

/* A line whose only content is a short text (a count, NULL or not, ...). */
static void write_note(size_t index, const char *config, const char *text)
{
	fprintf(out, "%zu\t%s\tn\t-\t-\t%s\n", index, config, text);
}

static json_tokener *new_tokener(int depth, int flags)
{
	json_tokener *tok = depth ? json_tokener_new_ex(depth) : json_tokener_new();
	if (!tok)
	{
		fprintf(stderr, "recorder: could not create a tokener (depth %d)\n", depth);
		exit(3);
	}
	json_tokener_set_flags(tok, flags);
	return tok;
}

/* Parse buf[0..len) on tok and record the answer. */
static void parse_and_record(size_t index, const char *mode, const char *flags_name,
                             json_tokener *tok, const char *buf, int len)
{
	json_object *obj = json_tokener_parse_ex(tok, buf, len);
	write_answer(index, mode, flags_name, obj, (int)json_tokener_get_error(tok),
	             (long)json_tokener_get_parse_end(tok));
}

/* Tokeners kept across all inputs, reset after each: checks json_tokener_reset. */
static json_tokener *reused[NCONFIGS];

static const int DEPTHS[] = {1, 5, 64}; /* json_tokener_new_ex; the default is 32 */
#define NDEPTHS (sizeof(DEPTHS) / sizeof(DEPTHS[0]))

/* ---- Text arriving in pieces ------------------------------------------------
 * A tokener keeps its state between calls, so a program can hand it the text
 * piece by piece. The original json-c does not always answer the same in
 * pieces as in one call (bughunt/README.md), so the pieces are compared with
 * the original fed the same pieces, never with the one-call answer. */

/* Feed buf[0..n) in pieces: the first `first` bytes (0: `step`), then `step`
 * bytes per call, until the tokener returns a value or an error other than
 * "continue"; if it still wants more after the last byte, one more call with
 * just the end byte. Records the final answer and the number of calls. */
static void parse_in_pieces(size_t index, const char *mode, const char *flags_name, int depth,
                            int flags, const char *buf, size_t n, size_t first, size_t step)
{
	json_tokener *tok = new_tokener(depth, flags);
	json_object *obj = NULL;
	size_t off = 0;
	long calls = 0;
	while (off < n)
	{
		size_t k = (off == 0 && first) ? first : step;
		if (k > n - off)
			k = n - off;
		obj = json_tokener_parse_ex(tok, buf + off, (int)k);
		calls++;
		off += k;
		if (obj || json_tokener_get_error(tok) != json_tokener_continue)
			break;
	}
	if (!obj && json_tokener_get_error(tok) == json_tokener_continue)
	{
		obj = json_tokener_parse_ex(tok, "", 1);
		calls++;
	}
	write_answer(index, mode, flags_name, obj, (int)json_tokener_get_error(tok),
	             (long)json_tokener_get_parse_end(tok));
	char config[64], count[24];
	snprintf(config, sizeof config, "%s-calls/%s", mode, flags_name);
	snprintf(count, sizeof count, "%ld", calls);
	write_note(index, config, count);
	json_tokener_free(tok);
}

/* One byte per call under every flag set, and once with nesting limit 5;
 * texts over 4096 bytes go in 4096-byte pieces to keep the run short. Texts
 * up to 64 bytes are also cut in two at every position (NFEW flag sets). */
static void record_pieces(size_t index, const char *buf, size_t n)
{
	size_t step = n > 4096 ? 4096 : 1;
	for (size_t c = 0; c < NCONFIGS; c++)
		parse_in_pieces(index, "bytewise", CONFIGS[c].name, 0, CONFIGS[c].flags, buf, n, 0, step);
	parse_in_pieces(index, "bytewise-depth5", "default", 5, 0, buf, n, 0, step);
	if (n > 64)
		return;
	for (size_t c = 0; c < NFEW; c++)
		for (size_t cut = 1; cut < n; cut++)
		{
			char mode[16];
			snprintf(mode, sizeof mode, "split%zu", cut);
			parse_in_pieces(index, mode, CONFIGS[c].name, 0, CONFIGS[c].flags, buf, n, cut, n);
		}
}

/* ---- Several documents on one reader -----------------------------------------
 * One reader per flag set, kept across inputs: it reads document after
 * document from the same text without a reset in between (allowed after each
 * success), as a program reading a stream of JSON values does. It is reset
 * before each input, and the text stops at an embedded NUL byte: past either,
 * the original itself leaks after bug-hunt finding 1's false success. */
static json_tokener *doc_tok[NCONFIGS];
#define MAX_DOCS 8

static void record_documents(size_t index, const char *buf)
{
	size_t n = strlen(buf);
	for (size_t c = 0; c < NCONFIGS; c++)
	{
		json_tokener *tok = doc_tok[c];
		size_t off = 0;
		json_tokener_reset(tok);
		for (int d = 0; d < MAX_DOCS; d++)
		{
			char mode[16];
			snprintf(mode, sizeof mode, "stream%d", d);
			json_object *obj = json_tokener_parse_ex(tok, buf + off, (int)(n - off) + 1);
			int err = (int)json_tokener_get_error(tok);
			size_t end = json_tokener_get_parse_end(tok);
			write_answer(index, mode, CONFIGS[c].name, obj, err, (long)end);
			if (err != json_tokener_success || end == 0)
				break;
			off += end;
			if (off >= n)
				break;
		}
	}
}

/* ---- Two readers taking turns -------------------------------------------------
 * This input and the previous one, each on its own reader, fed one byte at a
 * time in turns. A value that should belong to each reader but is shared
 * (for example kept in a static) shows up here. Each answer is filed under the
 * input it is about: "turns-with-previous" for this input, "turns-with-next"
 * for the previous one. */
static char *prev_buf;
static size_t prev_n;

struct turn
{
	json_tokener *tok;
	const char *buf;
	size_t n, i;
	json_object *obj;
	int done;
};

static void take_turn(struct turn *t)
{
	if (t->done)
		return;
	if (t->i < t->n)
		t->obj = json_tokener_parse_ex(t->tok, t->buf + t->i++, 1);
	else
	{
		t->obj = json_tokener_parse_ex(t->tok, "", 1); /* the end byte */
		t->done = 1;
	}
	if (t->obj || json_tokener_get_error(t->tok) != json_tokener_continue)
		t->done = 1;
}

static void record_turns(size_t index, const char *buf, size_t n)
{
	if (!prev_buf)
		return;
	for (size_t c = 0; c < NFEW; c++)
	{
		struct turn a = {new_tokener(0, CONFIGS[c].flags), buf, n, 0, NULL, 0};
		struct turn b = {new_tokener(0, CONFIGS[c].flags), prev_buf, prev_n, 0, NULL, 0};
		while (!a.done || !b.done)
		{
			take_turn(&a);
			take_turn(&b);
		}
		write_answer(index, "turns-with-previous", CONFIGS[c].name, a.obj,
		             (int)json_tokener_get_error(a.tok), (long)json_tokener_get_parse_end(a.tok));
		write_answer(index - 1, "turns-with-next", CONFIGS[c].name, b.obj,
		             (int)json_tokener_get_error(b.tok), (long)json_tokener_get_parse_end(b.tok));
		json_tokener_free(a.tok);
		json_tokener_free(b.tok);
	}
}

/* ---- Edge-case API calls, once --------------------------------------------------
 * Arguments no input file can express. Filed under the index one past the
 * last input; the report names them as the edge-case API calls. */
static void record_api(size_t index)
{
	json_tokener *tok = new_tokener(0, 0);
	parse_and_record(index, "api", "len=-2", tok, "1", -2);
	parse_and_record(index, "api", "len=INT_MIN", tok, "1", INT_MIN);
	json_tokener_free(tok);

	static const int depths[] = {0, -1};
	for (size_t i = 0; i < sizeof depths / sizeof depths[0]; i++)
	{
		char config[32];
		json_tokener *t = json_tokener_new_ex(depths[i]);
		snprintf(config, sizeof config, "api/new_ex(%d)", depths[i]);
		write_note(index, config, t ? "a tokener" : "NULL");
		json_tokener_free(t);
	}
	for (int e = -2; e < 20; e++)
	{
		char config[32];
		const char *desc = json_tokener_error_desc((enum json_tokener_error)e);
		snprintf(config, sizeof config, "api/error_desc(%d)", e);
		write_note(index, config, desc ? desc : "NULL");
	}
	json_tokener_free(NULL); /* both must accept NULL */
	json_tokener_reset(NULL);
}

/* ---- Memory running out ------------------------------------------------------
 * Every malloc, calloc, realloc and strdup in the program, the tokener's
 * included, goes through these wrappers. While fail_at > 0, the fail_at-th
 * call fails, as if memory had run out. */
void *__real_malloc(size_t);
void *__real_calloc(size_t, size_t);
void *__real_realloc(void *, size_t);
char *__real_strdup(const char *);
static long fail_at = -1, alloc_calls;
static int fail_now(void)
{
	return fail_at > 0 && ++alloc_calls == fail_at;
}
void *__wrap_malloc(size_t n)
{
	return fail_now() ? NULL : __real_malloc(n);
}
void *__wrap_calloc(size_t a, size_t b)
{
	return fail_now() ? NULL : __real_calloc(a, b);
}
void *__wrap_realloc(void *p, size_t n)
{
	return fail_now() ? NULL : __real_realloc(p, n);
}
char *__wrap_strdup(const char *str)
{
	return fail_now() ? NULL : __real_strdup(str);
}

#define OOM_MAX_LEN 1000   /* longer inputs are skipped */
#define OOM_MAX_POINTS 400 /* at most this many failure points per input and way */

/* For k = 1, 2, ...: a fresh tokener, then the k-th allocation of the parse
 * fails. The answer is recorded ("oom<k>", or "oomb<k>" byte by byte) only
 * when that failure happened, and the loop stops at the first parse that makes
 * fewer than k allocations. One call under default and strict flags; byte by
 * byte under default flags for inputs up to 64 bytes.
 * A rewrite may allocate in another order, so compare.py does not match
 * these answers k by k (see _acceptable_under_failure there). */
static void record_memory_failures(size_t index, const char *buf, size_t n)
{
	if (n > OOM_MAX_LEN)
		return;
	for (size_t c = 0; c < 2; c++) /* default, strict */
		for (int bytewise = 0; bytewise < 2; bytewise++)
		{
			if (bytewise && (c || n > 64))
				continue;
			for (long k = 1; k <= OOM_MAX_POINTS; k++)
			{
				json_tokener *tok = new_tokener(0, CONFIGS[c].flags);
				json_object *obj = NULL;
				alloc_calls = 0;
				fail_at = k;
				if (!bytewise)
					obj = json_tokener_parse_ex(tok, buf, (int)n + 1);
				else
					for (size_t i = 0; i <= n && !obj; i++) /* i == n: the end byte */
					{
						obj = json_tokener_parse_ex(tok, buf + i, 1);
						if (json_tokener_get_error(tok) != json_tokener_continue)
							break;
					}
				long made = alloc_calls;
				fail_at = -1;
				if (made >= k)
				{
					char mode[24];
					snprintf(mode, sizeof mode, bytewise ? "oomb%ld" : "oom%ld", k);
					write_answer(index, mode, CONFIGS[c].name, obj, (int)json_tokener_get_error(tok),
					             (long)json_tokener_get_parse_end(tok));
				}
				else
					json_object_put(obj);
				json_tokener_free(tok);
				if (made < k)
					break;
			}
		}
}

/* ---- A locale with a decimal comma --------------------------------------------
 * strtod reads numbers by the caller's locale, so json-c switches to the C
 * locale's number format inside each call and back afterwards. Parse under
 * de_DE.UTF-8, whose decimal point is ',', and check that the caller's locale
 * is back after the call. */
static locale_t de_locale;

static void record_locale(size_t index, const char *buf, size_t n)
{
	for (size_t c = 0; c < 2; c++) /* default, strict */
	{
		char config[48];
		json_tokener *tok = new_tokener(0, CONFIGS[c].flags);
		locale_t before = uselocale(de_locale);
		json_object *obj = json_tokener_parse_ex(tok, buf, (int)n + 1);
		int restored = uselocale((locale_t)0) == de_locale;
		uselocale(before);
		write_answer(index, "de_DE", CONFIGS[c].name, obj, (int)json_tokener_get_error(tok),
		             (long)json_tokener_get_parse_end(tok));
		snprintf(config, sizeof config, "de_DE-restored/%s", CONFIGS[c].name);
		write_note(index, config, restored ? "yes" : "no");
		json_tokener_free(tok);
	}
}

/* ---- What a reset leaves behind ------------------------------------------------
 * Stop partway (no end byte), reset: the error must read "success", and a
 * fixed document must parse as on a fresh tokener. */
static void record_after_reset(size_t index, const char *buf, size_t n)
{
	static const char doc[] = "[1,{\"a\":[\"x\",2.5]},null]";
	json_tokener *tok = new_tokener(0, 0);
	json_object_put(json_tokener_parse_ex(tok, buf, (int)n));
	json_tokener_reset(tok);
	write_answer(index, "afterreset", "error", NULL, (int)json_tokener_get_error(tok), -1);
	parse_and_record(index, "afterreset", "next", tok, doc, (int)sizeof doc);
	json_tokener_free(tok);
}

/* ---- Memory running out in json_tokener_parse_verbose ---------------------------
 * It creates and frees its own tokener, so failures while creating one are
 * reached too: "oomv<k>", recorded only when the k-th allocation failed. */
static void record_parse_verbose_failures(size_t index, const char *buf, size_t n)
{
	if (n > OOM_MAX_LEN)
		return;
	for (long k = 1; k <= OOM_MAX_POINTS; k++)
	{
		enum json_tokener_error err = json_tokener_success;
		alloc_calls = 0;
		fail_at = k;
		json_object *obj = json_tokener_parse_verbose(buf, &err);
		long made = alloc_calls;
		fail_at = -1;
		if (made >= k)
		{
			char mode[24];
			snprintf(mode, sizeof mode, "oomv%ld", k);
			write_answer(index, mode, "default", obj, (int)err, -1);
		}
		else
			json_object_put(obj);
		if (made < k)
			break;
	}
}

/* ---- Two tokeners with different settings alive at once ------------------------
 * A strict one with nesting limit 5 and a lenient one with limit 64, both
 * created before either is used: settings must belong to each tokener. */
static void record_two_settings(size_t index, const char *buf, size_t n)
{
	json_tokener *a = new_tokener(5, JSON_TOKENER_STRICT);
	json_tokener *b = new_tokener(64, 0);
	parse_and_record(index, "two", "strict-depth5", a, buf, (int)n + 1);
	parse_and_record(index, "two", "default-depth64", b, buf, (int)n + 1);
	json_tokener_free(a);
	json_tokener_free(b);
}

/* ---- Memory running out while creating a tokener --------------------------------
 * Once, after the edge-case API calls and filed with them: the k-th allocation
 * in json_tokener_new() and json_tokener_new_ex(5) fails, and each must return
 * NULL without leaking ("api/oomnew<k>"). */
static void record_creation_failures(size_t index)
{
	for (int d = 0; d < 2; d++)
		for (long k = 1; k <= 50; k++)
		{
			char config[40];
			alloc_calls = 0;
			fail_at = k;
			json_tokener *t = d ? json_tokener_new_ex(5) : json_tokener_new();
			long made = alloc_calls;
			fail_at = -1;
			if (made >= k)
			{
				snprintf(config, sizeof config, "api/oomnew%ld/%s", k, d ? "depth5" : "default");
				write_note(index, config, t ? "a tokener" : "NULL");
			}
			json_tokener_free(t);
			if (made < k)
				break;
		}
}

/* Every way the recorder asks the tokener about one input. buf holds n bytes
 * followed by a NUL. */
static void record_input(size_t index, const char *buf, size_t n)
{
	for (size_t c = 0; c < NCONFIGS; c++)
	{
		const char *name = CONFIGS[c].name;
		int flags = CONFIGS[c].flags;
		json_tokener *tok;

		/* oneshot: the whole input plus its NUL, so the tokener sees the end */
		tok = new_tokener(0, flags);
		parse_and_record(index, "oneshot", name, tok, buf, (int)n + 1);
		json_tokener_free(tok);

		/* noterm: no NUL, as when a caller passes exactly the bytes it has */
		tok = new_tokener(0, flags);
		parse_and_record(index, "noterm", name, tok, buf, (int)n);
		json_tokener_free(tok);

		/* minus1: len -1 means "use strlen", which json_tokener_parse() relies on */
		tok = new_tokener(0, flags);
		parse_and_record(index, "minus1", name, tok, buf, -1);
		json_tokener_free(tok);

		/* reuse: one tokener for all inputs, reset after each */
		parse_and_record(index, "reuse", name, reused[c], buf, (int)n + 1);
		json_tokener_reset(reused[c]);
	}

	write_answer(index, "parse", NULL, json_tokener_parse(buf), -1, -1);

	enum json_tokener_error err = json_tokener_success;
	json_object *obj = json_tokener_parse_verbose(buf, &err);
	write_answer(index, "verbose", NULL, obj, (int)err, -1);

	for (size_t d = 0; d < NDEPTHS; d++)
	{
		char mode[16];
		snprintf(mode, sizeof mode, "depth%d", DEPTHS[d]);
		json_tokener *tok = new_tokener(DEPTHS[d], 0);
		parse_and_record(index, mode, NULL, tok, buf, (int)n + 1);
		json_tokener_free(tok);
	}

	record_pieces(index, buf, n);
	record_documents(index, buf);
	record_turns(index, buf, n);
	record_memory_failures(index, buf, n);
	record_locale(index, buf, n);
	record_after_reset(index, buf, n);
	record_parse_verbose_failures(index, buf, n);
	record_two_settings(index, buf, n);
}

int main(int argc, char **argv)
{
	if (argc != 2 || !(out = fopen(argv[1], "w")))
	{
		fprintf(stderr, "usage: recorder ANSWERS_FILE < inputs\n");
		return 3;
	}
	/* glibc keeps the LOCPATH list it allocates here for the process's life */
	__lsan_disable();
	de_locale = newlocale(LC_ALL_MASK, "de_DE.UTF-8", (locale_t)0);
	__lsan_enable();
	if (!de_locale)
	{
		fprintf(stderr, "recorder: no de_DE.UTF-8 locale (check.py builds one and sets LOCPATH)\n");
		return 3;
	}
	for (size_t c = 0; c < NCONFIGS; c++)
	{
		reused[c] = new_tokener(0, CONFIGS[c].flags);
		doc_tok[c] = new_tokener(0, CONFIGS[c].flags);
	}
	char *line = NULL;
	size_t cap = 0;
	ssize_t got;
	size_t index = 0;
	/* getline: any length; the line may contain raw NUL bytes */
	while ((got = getline(&line, &cap, stdin)) != -1)
	{
		size_t len = (size_t)got;
		if (len > 0 && line[len - 1] == '\n')
			len--;
		char *buf = malloc(len + 1);
		if (!buf)
		{
			fprintf(stderr, "recorder: out of memory\n");
			return 3;
		}
		size_t n = decode_line(line, len, buf);
		fprintf(out, "#input %zu\n", index); /* where a crash happened */
		fflush(out);
		record_input(index, buf, n);
		free(prev_buf); /* this input becomes the previous one for the next */
		prev_buf = buf;
		prev_n = n;
		fflush(out);
		index++;
	}
	free(line);
	free(prev_buf);
	fprintf(out, "#input %zu\n", index);
	fflush(out);
	record_api(index);
	record_creation_failures(index);
	for (size_t c = 0; c < NCONFIGS; c++)
	{
		json_tokener_free(reused[c]);
		json_tokener_free(doc_tok[c]);
	}
	freelocale(de_locale);
	fprintf(out, "#done %zu\n", index);
	return fclose(out) == 0 ? 0 : 3;
}
