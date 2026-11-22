/* For each input line: one-shot and bytewise results for 3 flag sets. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "json.h"
/* type signature of the value tree, so int64-vs-uint64 or int-vs-double changes are seen */
static void sig(json_object *o)
{
	if (!o) { putchar('n'); return; }
	enum json_type ty = json_object_get_type(o);
	if (ty == json_type_int) putchar(json_object_get_int64(o) == INT64_MAX && json_object_get_uint64(o) > (uint64_t)INT64_MAX ? 'U' : 'i');
	else putchar("nbdiosa"[ty]);
	if (ty == json_type_array) { putchar('['); for (size_t i = 0; i < json_object_array_length(o); i++) sig(json_object_array_get_idx(o, i)); putchar(']'); }
	if (ty == json_type_object) { putchar('{'); json_object_object_foreach(o, k, v) { (void)k; sig(v); } putchar('}'); }
}
static void out(json_tokener *t, json_object *o, size_t base)
{
	sig(o); putchar(':');
	printf("%d:%zu:%s|", json_tokener_get_error(t), base + json_tokener_get_parse_end(t), o ? json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN) : "-");
	json_object_put(o); json_tokener_free(t);
}
int main(void)
{
	static char line[1 << 16], buf[1 << 16]; int FL[] = {0, 1, 16};
	while (fgets(line, sizeof line, stdin)) {
		size_t L = strcspn(line, "\n"), n = 0;
		for (size_t i = 0; i < L; i++) { if (line[i] == '\\' && line[i + 1] == 'x') { unsigned v; sscanf(line + i + 2, "%2x", &v); buf[n++] = (char)v; i += 3; } else buf[n++] = line[i]; }
		buf[n] = 0;
		for (int f = 0; f < 3; f++) {
			json_tokener *t = json_tokener_new(); json_tokener_set_flags(t, FL[f]);
			out(t, json_tokener_parse_ex(t, buf, (int)n + 1), 0);
			t = json_tokener_new(); json_tokener_set_flags(t, FL[f]); json_object *o = NULL; size_t i;
			for (i = 0; i <= n; i++) { o = json_tokener_parse_ex(t, buf + i, 1); if (json_tokener_get_error(t) != json_tokener_continue) break; }
			out(t, o, i > n ? n : i);
		}
		/* stream mode: same tokener, no reset, input twice ("x x") */
		{
			json_tokener *t = json_tokener_new(); json_object *o1 = json_tokener_parse_ex(t, buf, (int)n);
			int e1 = json_tokener_get_error(t); json_object_put(o1);
			if (e1 == json_tokener_success) { json_object *o2 = json_tokener_parse_ex(t, buf, (int)n + 1); out(t, o2, 0); } else { printf("e%d|", e1); json_tokener_free(t); }
		}
		putchar('\n');
	}
	return 0;
}
