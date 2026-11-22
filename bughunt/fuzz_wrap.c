/* libFuzzer target, round 4: structural metamorphic relations.
 * If x (no '/', no NUL) parses non-strict with every byte consumed, then
 *   "[" x "]"         must give [fresh(x)]
 *   "{\"k\":" x "}"   must give {"k":fresh(x)}
 *   x " "             must give fresh(x)
 * and the same holds for x fed byte-by-byte. Byte 0 picks flags (0 or VALIDATE_UTF8). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "json.h"
static char *p1(const char *s, size_t n, int f, int *err, size_t *end)
{
	json_tokener *t = json_tokener_new(); json_tokener_set_flags(t, f);
	json_object *o = json_tokener_parse_ex(t, s, (int)n + 1);
	*err = json_tokener_get_error(t); *end = json_tokener_get_parse_end(t);
	char *r = strdup(o ? json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN) : "null");
	json_object_put(o); json_tokener_free(t); return r;
}
static char *pb(const char *s, size_t n, int f, int *err)
{
	json_tokener *t = json_tokener_new(); json_tokener_set_flags(t, f); json_object *o = NULL;
	for (size_t i = 0; i <= n; i++) { o = json_tokener_parse_ex(t, s + i, 1); *err = json_tokener_get_error(t); if (*err != json_tokener_continue) break; }
	char *r = strdup(o ? json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN) : "null");
	json_object_put(o); json_tokener_free(t); return r;
}
int LLVMFuzzerTestOneInput(const unsigned char *d, size_t n)
{
	if (n < 2 || n > 2048) return 0;
	int f = (d[0] & 1) ? JSON_TOKENER_VALIDATE_UTF8 : 0;
	size_t xn = n - 1; char *x = malloc(xn + 1); memcpy(x, d + 1, xn); x[xn] = 0;
	if (memchr(x, 0, xn) || memchr(x, '/', xn)) { free(x); return 0; }
	{ /* depth guard: wrapping adds a level, so skip x near the default limit of 32 */
		int dep = 0, mx = 0; for (size_t i = 0; i < xn; i++) { if (x[i] == '[' || x[i] == '{') { if (++dep > mx) mx = dep; } else if (x[i] == ']' || x[i] == '}') dep--; }
		if (mx >= 30) { free(x); return 0; }
	}
	int e; size_t end; char *fx = p1(x, xn, f, &e, &end);
	if (e != 0 || end != xn) { free(fx); free(x); return 0; }
	char *buf = malloc(xn + 16), *want = malloc(strlen(fx) + 16);
	const char *pre[] = {"[", "{\"k\":", ""}, *suf[] = {"]", "}", " "}, *wpre[] = {"[", "{\"k\":", ""}, *wsuf[] = {"]", "}", ""};
	for (int k = 0; k < 3; k++) {
		size_t pl = strlen(pre[k]), sl = strlen(suf[k]);
		memcpy(buf, pre[k], pl); memcpy(buf + pl, x, xn); memcpy(buf + pl + xn, suf[k], sl); buf[pl + xn + sl] = 0;
		sprintf(want, "%s%s%s", wpre[k], fx, wsuf[k]);
		int e2; size_t end2; char *g = p1(buf, pl + xn + sl, f, &e2, &end2);
		int e3; char *gb = pb(buf, pl + xn + sl, f, &e3);
		if (e2 != 0 || strcmp(g, want) || e3 != 0 || strcmp(gb, want)) {
			printf("WRAP%d x=", k); fwrite(x, 1, xn, stdout);
			printf("\n  want %s\n  oneshot err=%s %s\n  bytewise err=%s %s\n", want, json_tokener_error_desc(e2), g, json_tokener_error_desc(e3), gb);
			abort();
		}
		free(g); free(gb);
	}
	free(buf); free(want); free(fx); free(x);
	return 0;
}
