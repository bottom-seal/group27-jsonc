/*
 * Differential fuzzer: the baseline json_tokener.c and a candidate in one
 * program, fed the same inputs by libFuzzer. fuzz.py builds it, renaming
 * every global symbol of the baseline to old_* and of the candidate to new_*.
 *
 * Input: byte 0 picks one of the 8 flag sets, byte 1 picks where to cut the
 * text in two, and the rest is the text. Both versions parse it four ways:
 * the whole text plus its end byte, cut in two, one byte per call, and as
 * several documents on one tokener. Any difference in the answers (error,
 * parse end, type of every value, exact doubles, the value itself) prints
 * both and aborts, and libFuzzer saves the input.
 */
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "json.h"

#define DECLARE(p)                                                                   \
	json_tokener *p##json_tokener_new(void);                                         \
	void p##json_tokener_free(json_tokener *);                                       \
	void p##json_tokener_set_flags(json_tokener *, int);                             \
	json_object *p##json_tokener_parse_ex(json_tokener *, const char *, int);        \
	enum json_tokener_error p##json_tokener_get_error(json_tokener *);               \
	size_t p##json_tokener_get_parse_end(json_tokener *);
DECLARE(old_)
DECLARE(new_)

struct version
{
	const char *name;
	json_tokener *(*create)(void);
	void (*destroy)(json_tokener *);
	void (*set_flags)(json_tokener *, int);
	json_object *(*parse)(json_tokener *, const char *, int);
	enum json_tokener_error (*error)(json_tokener *);
	size_t (*end)(json_tokener *);
};
static const struct version OLD = {"baseline", old_json_tokener_new, old_json_tokener_free,
                                   old_json_tokener_set_flags, old_json_tokener_parse_ex,
                                   old_json_tokener_get_error, old_json_tokener_get_parse_end};
static const struct version NEW = {"candidate", new_json_tokener_new, new_json_tokener_free,
                                   new_json_tokener_set_flags, new_json_tokener_parse_ex,
                                   new_json_tokener_get_error, new_json_tokener_get_parse_end};

static const struct
{
	const char *name;
	int flags;
} FLAGS[8] = {
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

/* Everything one version answered for one input, as text. */
struct answers
{
	char text[1 << 16];
	size_t len;
};

static void add(struct answers *a, const char *fmt, ...)
{
	if (a->len >= sizeof a->text - 1)
		return;
	va_list ap;
	va_start(ap, fmt);
	int k = vsnprintf(a->text + a->len, sizeof a->text - a->len, fmt, ap);
	va_end(ap);
	if (k > 0)
		a->len += (size_t)k;
	if (a->len > sizeof a->text - 1)
		a->len = sizeof a->text - 1;
}

/* The type of every value and the exact value of every double, as the
 * gate's recorder does: json-c prints a parsed double from its text. */
static void add_signature(struct answers *a, json_object *o)
{
	if (!o)
	{
		add(a, "n");
		return;
	}
	enum json_type ty = json_object_get_type(o);
	if (ty == json_type_int)
		add(a, json_object_get_int64(o) == INT64_MAX && json_object_get_uint64(o) > (uint64_t)INT64_MAX
		           ? "U"
		           : "i");
	else if (ty == json_type_double)
		add(a, "d(%a)", json_object_get_double(o));
	else
		add(a, "%c", "nbdioas"[ty]);
	if (ty == json_type_array)
	{
		add(a, "[");
		for (size_t i = 0; i < json_object_array_length(o); i++)
			add_signature(a, json_object_array_get_idx(o, i));
		add(a, "]");
	}
	if (ty == json_type_object)
	{
		add(a, "{");
		json_object_object_foreach(o, key, val)
		{
			(void)key;
			add_signature(a, val);
		}
		add(a, "}");
	}
}

/* One answer: error, parse end, types, value. Takes ownership of obj. */
static void add_answer(struct answers *a, const struct version *v, json_tokener *tok, json_object *obj)
{
	add(a, "%d/%zu/", (int)v->error(tok), v->end(tok));
	add_signature(a, obj);
	add(a, "/%s; ", obj ? json_object_to_json_string_ext(obj, JSON_C_TO_STRING_PLAIN) : "-");
	json_object_put(obj);
}

/* doc[0..n) in pieces: `first` bytes, then `step` bytes per call, until a
 * value or an error other than "continue"; then the end byte if needed. */
static void in_pieces(struct answers *a, const struct version *v, int flags, const char *doc, size_t n,
                      size_t first, size_t step)
{
	json_tokener *tok = v->create();
	v->set_flags(tok, flags);
	json_object *obj = NULL;
	size_t off = 0;
	int calls = 0;
	while (off < n)
	{
		size_t k = (off == 0 && first) ? first : step;
		if (k > n - off)
			k = n - off;
		obj = v->parse(tok, doc + off, (int)k);
		calls++;
		off += k;
		if (obj || v->error(tok) != json_tokener_continue)
			break;
	}
	if (!obj && v->error(tok) == json_tokener_continue)
	{
		obj = v->parse(tok, "", 1);
		calls++;
	}
	add(a, "%d calls: ", calls);
	add_answer(a, v, tok, obj);
	v->destroy(tok);
}

static void parse_all_ways(struct answers *a, const struct version *v, int flags, const char *doc, size_t n,
                           size_t cut)
{
	a->len = 0;
	a->text[0] = '\0';

	add(a, "whole: ");
	json_tokener *tok = v->create();
	v->set_flags(tok, flags);
	add_answer(a, v, tok, v->parse(tok, doc, (int)n + 1));
	v->destroy(tok);

	add(a, "\ncut in two: ");
	in_pieces(a, v, flags, doc, n, cut, n);

	add(a, "\nbyte by byte: ");
	in_pieces(a, v, flags, doc, n, 0, 1);

	/* Several documents on one tokener, without a reset in between. Stops at
	 * an embedded NUL byte: past it the baseline itself leaks (see
	 * oracle/README.md, "stream"). */
	add(a, "\ndocuments: ");
	size_t len = strlen(doc), off = 0;
	tok = v->create();
	v->set_flags(tok, flags);
	for (int d = 0; d < 8; d++)
	{
		json_object *obj = v->parse(tok, doc + off, (int)(len - off) + 1);
		int err = (int)v->error(tok);
		size_t end = v->end(tok);
		add_answer(a, v, tok, obj);
		if (err != json_tokener_success || end == 0)
			break;
		off += end;
		if (off >= len)
			break;
	}
	v->destroy(tok);
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
	static struct answers old_answers, new_answers;
	if (size < 2 || size > 4096)
		return 0;
	int set = data[0] & 7;
	size_t n = size - 2;
	char *doc = malloc(n + 1);
	memcpy(doc, data + 2, n);
	doc[n] = '\0';
	size_t cut = n ? data[1] % (n + 1) : 0;

	parse_all_ways(&old_answers, &OLD, FLAGS[set].flags, doc, n, cut);
	parse_all_ways(&new_answers, &NEW, FLAGS[set].flags, doc, n, cut);
	if (strcmp(old_answers.text, new_answers.text) != 0)
	{
		fprintf(stderr, "DIFFERENCE (flags %s, cut after byte %zu)\n--- baseline:\n%.3000s\n--- candidate:\n%.3000s\n",
		        FLAGS[set].name, cut, old_answers.text, new_answers.text);
		abort();
	}
	free(doc);
	return 0;
}
