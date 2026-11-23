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
 * followed by a final line "#done <number of inputs read>". Output is flushed
 * after each input, so if the candidate crashes the records written so far
 * show which input it was on.
 *
 * The answers go to their own file, not stdout, so anything the tokener itself
 * prints cannot corrupt them; the checker compares stdout separately.
 *
 * Adapted from bughunt/mutation/mut_driver.c.
 */
#include <ctype.h>
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

static const struct config CONFIGS[] = {
    {"default", 0},
    {"strict", JSON_TOKENER_STRICT},
    {"utf8", JSON_TOKENER_VALIDATE_UTF8},
    {"strict+utf8", JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8},
    {"strict+trailing", JSON_TOKENER_STRICT | JSON_TOKENER_ALLOW_TRAILING_CHARS},
    {"strict+trailing+utf8",
     JSON_TOKENER_STRICT | JSON_TOKENER_ALLOW_TRAILING_CHARS | JSON_TOKENER_VALIDATE_UTF8},
};
#define NCONFIGS (sizeof(CONFIGS) / sizeof(CONFIGS[0]))

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
}

int main(int argc, char **argv)
{
	if (argc != 2 || !(out = fopen(argv[1], "w")))
	{
		fprintf(stderr, "usage: recorder ANSWERS_FILE < inputs\n");
		return 3;
	}
	for (size_t c = 0; c < NCONFIGS; c++)
		reused[c] = new_tokener(0, CONFIGS[c].flags);
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
		record_input(index, buf, n);
		free(buf);
		fflush(out);
		index++;
	}
	free(line);
	for (size_t c = 0; c < NCONFIGS; c++)
		json_tokener_free(reused[c]);
	fprintf(out, "#done %zu\n", index);
	return fclose(out) == 0 ? 0 : 3;
}
