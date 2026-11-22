/* Batch driver: each stdin line (\xNN escapes) is parsed one-shot with the
 * given flags; prints err<TAB>parse_end<TAB>plain-serialization. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "json.h"
int main(int argc, char **argv)
{
	int flags = argc > 1 ? atoi(argv[1]) : 0;
	static char line[1 << 16], buf[1 << 16];
	while (fgets(line, sizeof line, stdin)) {
		size_t L = strcspn(line, "\n"), n = 0;
		for (size_t i = 0; i < L; i++) {
			if (line[i] == '\\' && line[i + 1] == 'x') { unsigned v; sscanf(line + i + 2, "%2x", &v); buf[n++] = (char)v; i += 3; }
			else buf[n++] = line[i];
		}
		buf[n] = 0;
		json_tokener *t = json_tokener_new(); json_tokener_set_flags(t, flags);
		json_object *o = json_tokener_parse_ex(t, buf, (int)n + 1);
		printf("%d\t%zu\t%s\n", json_tokener_get_error(t), json_tokener_get_parse_end(t),
		       o ? json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN) : (json_tokener_get_error(t) == 0 ? "null" : ""));
		json_object_put(o); json_tokener_free(t);
	}
	return 0;
}
