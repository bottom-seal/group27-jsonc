/* Metamorphic oracles for tokener state carried between documents.
 *  R1 reset:  parse X (any outcome, any chunking), json_tokener_reset, parse Y
 *             == fresh parse of Y.
 *  R2 stream: one tokener fed "X Y" (non-strict) via repeated parse_ex calls on
 *             the leftover, as documented for multi-object streams, must give
 *             fresh(X) then fresh(Y) when both are valid on their own.
 * Input file: lines of \xNN-escaped documents; every pair (i, j) in a window
 * is tested. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "json.h"

static char *ser(json_object *o) { return strdup(o ? json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN) : "<null>"); }

static size_t last_end;
static int fresh(const char *s, size_t n, int flags, char **out)
{
	json_tokener *t = json_tokener_new(); json_tokener_set_flags(t, flags);
	json_object *o = json_tokener_parse_ex(t, s, (int)n + 1);
	int e = json_tokener_get_error(t);
	last_end = json_tokener_get_parse_end(t);
	*out = ser(o); json_object_put(o); json_tokener_free(t); return e;
}

static void esc(const char *s, size_t n) { for (size_t i = 0; i < n; i++) { unsigned char c = s[i]; if (c >= 0x20 && c < 0x7f && c != '\\') putchar(c); else printf("\\x%02x", c); } }

static int bad = 0;
static const int FL[] = {0, JSON_TOKENER_STRICT, JSON_TOKENER_VALIDATE_UTF8};

static void r1(const char *x, size_t xn, const char *y, size_t yn)
{
	for (int fi = 0; fi < 3; fi++) for (int mode = 0; mode < 3; mode++) {
		int f = FL[fi]; char *fo, *ro;
		int fe = fresh(y, yn, f, &fo);
		json_tokener *t = json_tokener_new(); json_tokener_set_flags(t, f);
		/* mode 0: X complete with NUL; 1: X without NUL (may stay mid-value); 2: half of X */
		size_t len = mode == 0 ? xn + 1 : mode == 1 ? xn : xn / 2;
		json_object_put(json_tokener_parse_ex(t, x, (int)len));
		json_tokener_reset(t);
		json_object *o = json_tokener_parse_ex(t, y, (int)yn + 1);
		int re = json_tokener_get_error(t); ro = ser(o); json_object_put(o); json_tokener_free(t);
		if (re != fe || strcmp(ro, fo)) {
			bad++; printf("R1 flags=%d mode=%d X='", f, mode); esc(x, xn); printf("' Y='"); esc(y, yn);
			printf("'\n   fresh: %s %s\n   reuse: %s %s\n", json_tokener_error_desc(fe), fo, json_tokener_error_desc(re), ro);
		}
		free(fo); free(ro);
	}
}

static void r2(const char *x, size_t xn, const char *y, size_t yn, const char *sep)
{
	char *fx, *fy;
	/* both must be valid alone and X must be fully consumed (no trailing junk) */
	int ex = fresh(x, xn, 0, &fx); size_t xend = last_end;
	int ey = fresh(y, yn, 0, &fy);
	/* an X ending inside an open comment would swallow Y; skip those */
	const char *lo = NULL, *lc = NULL; for (const char *p = x; (p = strstr(p, "/*")); p++) lo = p;
	for (const char *p = x; (p = strstr(p, "*/")); p++) lc = p;
	int open_cmt = (lo && (!lc || lc < lo + 1)) || (xn >= 2 && strstr(x, "//") && !memchr(strstr(x, "//"), '\n', xn - (strstr(x, "//") - x)));
	if (ex != 0 || ey != 0 || xend < xn || open_cmt) { free(fx); free(fy); return; }
	size_t sl = strlen(sep); size_t n = xn + sl + yn; char *s = malloc(n + 1);
	memcpy(s, x, xn); memcpy(s + xn, sep, sl); memcpy(s + xn + sl, y, yn); s[n] = 0;
	json_tokener *t = json_tokener_new();
	size_t pos = 0; char *got[2] = {NULL, NULL}; int k = 0, e = 0;
	while (k < 2) {
		json_object *o = json_tokener_parse_ex(t, s + pos, (int)(n + 1 - pos));
		e = json_tokener_get_error(t);
		if (e != json_tokener_success) break;
		got[k++] = ser(o); json_object_put(o);
		pos += json_tokener_get_parse_end(t);
		if (pos > n) break;
	}
	if (k != 2 || strcmp(got[0], fx) || strcmp(got[1], fy)) {
		bad++; printf("R2 sep='"); esc(sep, sl); printf("' X='"); esc(x, xn); printf("' Y='"); esc(y, yn);
		printf("'\n   want: %s | %s\n   got(%d, last err %s): %s | %s\n", fx, fy, k, json_tokener_error_desc(e), got[0] ? got[0] : "-", got[1] ? got[1] : "-");
	}
	free(got[0]); free(got[1]); free(fx); free(fy); free(s); json_tokener_free(t);
}

int main(int argc, char **argv)
{
	static char docs[4000][512]; static size_t dl[4000]; int nd = 0; char line[4096];
	FILE *in = fopen(argv[1], "rb");
	while (nd < 4000 && fgets(line, sizeof line, in)) {
		size_t L = strcspn(line, "\n"), n = 0;
		for (size_t i = 0; i < L && n < 500; i++) {
			if (line[i] == '\\' && line[i + 1] == 'x') { unsigned v; sscanf(line + i + 2, "%2x", &v); docs[nd][n++] = (char)v; i += 3; }
			else docs[nd][n++] = line[i];
		}
		if (memchr(docs[nd], 0, n)) continue;
		docs[nd][n] = 0; dl[nd++] = n;
	}
	const char *seps[] = {" ", "", "\n", "/*c*/", "//c\n"};
	for (int i = 0; i < nd; i++) for (int d = 1; d <= 3; d++) {
		int j = (i + d * 7) % nd;
		r1(docs[i], dl[i], docs[j], dl[j]);
		r2(docs[i], dl[i], docs[j], dl[j], seps[(i + d) % 5]);
	}
	printf("docs=%d mismatches=%d\n", nd, bad);
	return 0;
}
