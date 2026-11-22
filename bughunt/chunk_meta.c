/* Metamorphic test: parsing input in 2 chunks (every split point) and
 * byte-by-byte must give the same result as a one-shot parse. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "json.h"

typedef struct { int err; int consumed; char *out; int early; } res_t;

static res_t run(const char *s, size_t n, const size_t *cuts, int ncuts, int flags)
{
	res_t r = {0, 0, NULL, 0};
	json_tokener *tok = json_tokener_new();
	json_tokener_set_flags(tok, flags);
	json_object *o = NULL;
	size_t start = 0;
	enum json_tokener_error e = json_tokener_continue;
	for (int i = 0; i <= ncuts; i++) {
		size_t end = (i < ncuts) ? cuts[i] : n + 1; /* last chunk includes NUL */
		o = json_tokener_parse_ex(tok, s + start, (int)(end - start));
		e = json_tokener_get_error(tok);
		if (e != json_tokener_continue) {
			r.consumed = (int)start + json_tokener_get_parse_end(tok);
			r.early = (i < ncuts) && e == json_tokener_success;
			break;
		}
		start = end;
	}
	r.err = e;
	if (o) { r.out = strdup(json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN)); json_object_put(o); }
	json_tokener_free(tok);
	return r;
}

static int same(res_t *a, res_t *b)
{
	if (getenv("KEEP_TRAILING") == NULL && b->early && a->err != json_tokener_success) return 1;
	if (a->err != b->err) return 0;
	if ((a->out == NULL) != (b->out == NULL)) return 0;
	if (a->out && strcmp(a->out, b->out)) return 0;
	/* char_offset oracle: an error must be reported at the same input position */
	if (a->err != json_tokener_success && a->err != json_tokener_continue && a->consumed != b->consumed) return 0;
	return 1;
}

static void show(const char *tag, res_t *r)
{
	printf("    %-8s err=%s consumed=%d out=%s\n", tag, json_tokener_error_desc(r->err), r->consumed, r->out ? r->out : "(null)");
}

static void esc(const char *s, size_t n)
{
	for (size_t i = 0; i < n; i++) {
		unsigned char c = s[i];
		if (c >= 0x20 && c < 0x7f && c != '\\') putchar(c); else printf("\\x%02x", c);
	}
}

static const int FLAGS[] = {0, JSON_TOKENER_STRICT, JSON_TOKENER_VALIDATE_UTF8,
	JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8, JSON_TOKENER_STRICT | JSON_TOKENER_ALLOW_TRAILING_CHARS};

int check(const char *s, size_t n, int verbose)
{
	int bad = 0;
	for (size_t fi = 0; fi < sizeof(FLAGS) / sizeof(FLAGS[0]); fi++) {
		int f = FLAGS[fi];
		res_t one = run(s, n, NULL, 0, f);
		for (size_t k = 1; k < n; k++) {
			size_t cut = k;
			res_t two = run(s, n, &cut, 1, f);
			if (!same(&one, &two)) {
				bad++;
				if (verbose) { printf("MISMATCH flags=0x%x split@%zu input='", f, k); esc(s, n); printf("'\n"); show("oneshot", &one); show("split", &two); }
			}
			free(two.out);
		}
		if (n > 1) {
			size_t *cuts = malloc(n * sizeof(size_t));
			for (size_t k = 1; k < n; k++) cuts[k - 1] = k;
			res_t bb = run(s, n, cuts, (int)n - 1, f);
			if (!same(&one, &bb)) {
				bad++;
				if (verbose) { printf("MISMATCH flags=0x%x bytewise input='", f); esc(s, n); printf("'\n"); show("oneshot", &one); show("bytewise", &bb); }
			}
			free(bb.out); free(cuts);
		}
		free(one.out);
	}
	return bad;
}

#ifndef NO_MAIN
int main(int argc, char **argv)
{
	/* each line of stdin (or argv) is one input; \xNN escapes allowed */
	char line[65536]; int total = 0;
	FILE *in = argc > 1 ? fopen(argv[1], "rb") : stdin;
	while (fgets(line, sizeof line, in)) {
		size_t L = strcspn(line, "\n"); line[L] = 0;
		char buf[65536]; size_t n = 0;
		for (size_t i = 0; i < L; i++) {
			if (line[i] == '\\' && line[i+1] == 'x' && i + 3 < L + 1) { unsigned v; sscanf(line + i + 2, "%2x", &v); buf[n++] = (char)v; i += 3; }
			else buf[n++] = line[i];
		}
		buf[n] = 0;
		total += check(buf, n, 1);
	}
	printf("total mismatches: %d\n", total);
	return 0;
}
#endif
