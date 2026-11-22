/* libFuzzer target, round 2: three-piece chunk split (bytes 1,2 pick cuts) and
 * tokener reuse after json_tokener_reset (byte 3 picks where the input is
 * split into a "garbage" prefix X and a document Y). ASan/UBSan on. */
#define NO_MAIN
#include "chunk_meta.c"
int LLVMFuzzerTestOneInput(const unsigned char *d, size_t n)
{
	if (n < 5 || n > 4096) return 0;
	int f = FLAGS[d[0] % (sizeof(FLAGS) / sizeof(FLAGS[0]))];
	char *s = malloc(n - 4 + 1); memcpy(s, d + 4, n - 4); s[n - 4] = 0;
	size_t len = strlen(s);
	if (len >= 3) {
		size_t c[2] = {1 + d[1] % (len - 1), 1 + d[2] % (len - 1)};
		if (c[0] > c[1]) { size_t t = c[0]; c[0] = c[1]; c[1] = t; }
		int nc = c[0] == c[1] ? 1 : 2;
		res_t one = run(s, len, NULL, 0, f), three = run(s, len, c, nc, f);
		if (!same(&one, &three)) { printf("flags=0x%x cuts@%zu,%zu\n", f, c[0], c[1]); show("oneshot", &one); show("split3", &three); abort(); }
		free(three.out);
		/* reuse: parse prefix X (without NUL, may be left mid-value), reset, parse Y */
		size_t xl = d[3] % len; const char *y = s + xl; size_t yl = len - xl;
		res_t fy = run(y, yl, NULL, 0, f);
		json_tokener *tok = json_tokener_new(); json_tokener_set_flags(tok, f);
		json_object_put(json_tokener_parse_ex(tok, s, (int)xl));
		json_tokener_reset(tok);
		json_object *o = json_tokener_parse_ex(tok, y, (int)yl + 1);
		int e = json_tokener_get_error(tok);
		char *ro = o ? strdup(json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN)) : NULL;
		if (e != fy.err || (ro == NULL) != (fy.out == NULL) || (ro && strcmp(ro, fy.out))) {
			printf("reuse flags=0x%x xlen=%zu\n  fresh %s %s\n  reuse %s %s\n", f, xl, json_tokener_error_desc(fy.err), fy.out ? fy.out : "-", json_tokener_error_desc(e), ro ? ro : "-"); abort();
		}
		free(ro); json_object_put(o); json_tokener_free(tok); free(fy.out); free(one.out);
	}
	free(s);
	return 0;
}
