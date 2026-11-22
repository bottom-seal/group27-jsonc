/* MR-comment: in non-strict mode, inserting a comment at a point where
 * whitespace is legal (between tokens, outside strings) must not change the
 * result.  Also MR-ws: inserting a space there must not change it. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "json.h"
static int parse(const char *s, size_t n, char **out)
{
	json_tokener *t = json_tokener_new();
	json_object *o = json_tokener_parse_ex(t, s, (int)n + 1);
	int e = json_tokener_get_error(t);
	*out = strdup(o ? json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN) : "<null>");
	json_object_put(o); json_tokener_free(t); return e;
}
static const char *CM[] = {" ", "/**/", "/* c */", "/* * */", "/** c **/", "/***/", "/*/ */", "// c\n", "//\n", "/* // */", "/*\n*/"};
#define NCM (sizeof CM / sizeof CM[0])
int main(int argc, char **argv)
{
	char line[8192], buf[8192], tmp[9000]; int bad = 0, done = 0, hits[NCM] = {0};
	FILE *in = fopen(argv[1], "rb");
	while (fgets(line, sizeof line, in)) {
		size_t L = strcspn(line, "\n"), n = 0;
		for (size_t i = 0; i < L; i++) {
			if (line[i] == '\\' && line[i + 1] == 'x') { unsigned v; sscanf(line + i + 2, "%2x", &v); buf[n++] = (char)v; i += 3; }
			else buf[n++] = line[i];
		}
		buf[n] = 0; if (strlen(buf) != n) continue;
		char *base; int be = parse(buf, n, &base);
		if (be != 0) { free(base); continue; } /* only inputs that parse; bytes past parse_end ignored */
		/* insertion points: between two structural tokens, outside strings, before parse end */
		int instr = 0; char q = 0;
		for (size_t i = 0; i <= n; i++) {
			char prev = i ? buf[i - 1] : 0, cur = buf[i];
			int boundary = !instr && (i == 0 || strchr("[]{},:", prev) || strchr("[]{},:", cur));
			if (boundary && !(i && prev == '/') && !(cur == '*' || cur == '/')) {
				for (size_t c = 0; c < NCM; c++) {
					size_t cl = strlen(CM[c]);
					memcpy(tmp, buf, i); memcpy(tmp + i, CM[c], cl); memcpy(tmp + i + cl, buf + i, n - i); tmp[n + cl] = 0;
					char *o; int e = parse(tmp, n + cl, &o); done++;
					if (e != be || strcmp(o, base)) {
						if (hits[c]++ < 3) printf("MISMATCH comment='%s' at %zu input='%s'\n  base: %s\n  mut:  err=%s %s\n", CM[c], i, buf, base, json_tokener_error_desc(e), o);
						bad++;
					}
					free(o);
				}
			}
			if (instr) { if (cur == '\\') i++; else if (cur == q) instr = 0; }
			else if (cur == '"' || cur == '\'') { instr = 1; q = cur; }
			else if (cur == '/' && buf[i + 1] == '*') { char *e2 = strstr(buf + i + 2, "*/"); if (!e2) break; i = e2 + 1 - buf; }
			else if (cur == '/' && buf[i + 1] == '/') { char *e2 = strchr(buf + i, '\n'); if (!e2) break; i = e2 - buf; }
		}
		free(base);
	}
	printf("mutants=%d mismatches=%d per-comment:", done, bad);
	for (size_t c = 0; c < NCM; c++) printf(" [%zu]=%d", c, hits[c]);
	printf("\n");
	return 0;
}
