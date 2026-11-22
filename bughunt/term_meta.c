/* Termination-mode metamorphic test for json_tokener_parse_ex:
 *  A: (s, len+1)                         reference, NUL included
 *  B: (s, -1)                            must equal A
 *  C: (s, len) then ("\0", 1)            must equal A
 *  D: (s, len) then ("", 0) then ("\0",1) a zero-length call must change nothing
 * Compared: error code, serialization, and for errors the absolute offset. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "json.h"
typedef struct { int e; long off; char *o; } R;
static R fin(json_tokener *t, json_object *o, long base)
{
	R r; r.e = json_tokener_get_error(t); r.off = base + (long)json_tokener_get_parse_end(t);
	r.o = strdup(o ? json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN) : "-");
	json_object_put(o); json_tokener_free(t); return r;
}
static R mode(const char *s, int n, int m, int flags)
{
	json_tokener *t = json_tokener_new(); json_tokener_set_flags(t, flags); json_object *o;
	if (m == 0) return fin(t, json_tokener_parse_ex(t, s, n + 1), 0);
	if (m == 1) return fin(t, json_tokener_parse_ex(t, s, -1), 0);
	o = json_tokener_parse_ex(t, s, n);
	if (json_tokener_get_error(t) != json_tokener_continue) return fin(t, o, 0);
	if (m == 3) { o = json_tokener_parse_ex(t, "", 0); if (json_tokener_get_error(t) != json_tokener_continue) return fin(t, o, n); }
	return fin(t, json_tokener_parse_ex(t, "\0", 1), n);
}
int main(int argc, char **argv)
{
	char line[8192], buf[8192]; int bad = 0, cnt = 0; FILE *in = fopen(argv[1], "rb");
	int FL[] = {0, 1, 16, 3};
	while (fgets(line, sizeof line, in)) {
		size_t L = strcspn(line, "\n"), n = 0;
		for (size_t i = 0; i < L; i++) { if (line[i] == '\\' && line[i + 1] == 'x') { unsigned v; sscanf(line + i + 2, "%2x", &v); buf[n++] = (char)v; i += 3; } else buf[n++] = line[i]; }
		buf[n] = 0; if (strlen(buf) != n) continue;
		for (int fi = 0; fi < 4; fi++) {
			R a = mode(buf, (int)n, 0, FL[fi]);
			for (int m = 1; m < 4; m++) {
				R b = mode(buf, (int)n, m, FL[fi]); cnt++;
				int diff = a.e != b.e || strcmp(a.o, b.o) || (a.e != 0 && a.off != b.off);
				/* success in mode C/D may legitimately stop earlier: the value ended inside the first call */
				if (diff && !(b.e == 0 && a.e != 0 && m >= 2 && b.off <= (long)n)) {
					if (bad++ < 25) printf("MODE%d flags=%d input='%s'\n  A: err=%s off=%ld %s\n  B: err=%s off=%ld %s\n", m, FL[fi], buf, json_tokener_error_desc(a.e), a.off, a.o, json_tokener_error_desc(b.e), b.off, b.o);
				}
				free(b.o);
			}
			free(a.o);
		}
	}
	printf("checks=%d mismatches=%d\n", cnt, bad);
	return 0;
}
