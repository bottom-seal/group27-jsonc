/*
 * Recorder: parses each input with json_tokener_parse_ex and prints what the
 * tokener answered, so two builds (baseline and candidate) can be compared.
 *
 * Input (stdin): one JSON document per line. "\xNN" stands for the byte 0xNN,
 * so documents can contain newlines, NUL bytes and invalid UTF-8.
 *
 * Output (stdout): for every input and every config, one tab-separated record
 *
 *     <input index> <config> <type signature> <error> <parse end> <value>
 *
 * followed by a final line "#done <number of inputs read>". Output is flushed
 * after each input, so if the candidate crashes the records written so far
 * show which input it was on.
 *
 * Adapted from bughunt/mutation/mut_driver.c.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "json.h"

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
		putchar('n');
		return;
	}
	enum json_type ty = json_object_get_type(o);
	if (ty == json_type_int)
		putchar(json_object_get_int64(o) == INT64_MAX &&
		                json_object_get_uint64(o) > (uint64_t)INT64_MAX
		            ? 'U'
		            : 'i');
	else if (ty == json_type_double)
		printf("d(%a)", json_object_get_double(o));
	else
		putchar("nbdioas"[ty]); /* indexed by enum json_type, see json_types.h */
	if (ty == json_type_array)
	{
		putchar('[');
		for (size_t i = 0; i < json_object_array_length(o); i++)
			print_signature(json_object_array_get_idx(o, i));
		putchar(']');
	}
	if (ty == json_type_object)
	{
		putchar('{');
		json_object_object_foreach(o, key, val)
		{
			(void)key;
			print_signature(val);
		}
		putchar('}');
	}
}

static size_t decode_line(const char *line, size_t len, char *buf)
{
	size_t n = 0;
	for (size_t i = 0; i < len; i++)
	{
		unsigned v;
		if (line[i] == '\\' && line[i + 1] == 'x' && sscanf(line + i + 2, "%2x", &v) == 1)
		{
			buf[n++] = (char)v;
			i += 3;
		}
		else
			buf[n++] = line[i];
	}
	buf[n] = '\0';
	return n;
}

static void record_oneshot(size_t index, const struct config *cfg, const char *buf, size_t n)
{
	json_tokener *tok = json_tokener_new();
	if (!tok)
	{
		fprintf(stderr, "recorder: json_tokener_new failed\n");
		exit(3);
	}
	json_tokener_set_flags(tok, cfg->flags);
	/* n + 1: include the terminating NUL so the tokener sees end of input */
	json_object *obj = json_tokener_parse_ex(tok, buf, (int)n + 1);
	enum json_tokener_error err = json_tokener_get_error(tok);

	printf("%zu\t%s\t", index, cfg->name);
	print_signature(obj);
	printf("\t%d %s\t%zu\t%s\n", (int)err, json_tokener_error_desc(err),
	       json_tokener_get_parse_end(tok),
	       obj ? json_object_to_json_string_ext(obj, JSON_C_TO_STRING_PLAIN) : "-");

	json_object_put(obj);
	json_tokener_free(tok);
}

int main(void)
{
	static char line[1 << 17], buf[1 << 17];
	size_t index = 0;
	while (fgets(line, sizeof line, stdin))
	{
		size_t len = strcspn(line, "\n");
		size_t n = decode_line(line, len, buf);
		for (size_t c = 0; c < NCONFIGS; c++)
			record_oneshot(index, &CONFIGS[c], buf, n);
		fflush(stdout);
		index++;
	}
	printf("#done %zu\n", index);
	return 0;
}
