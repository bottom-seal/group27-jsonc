/* Oracle driver: one-shot json_tokener_parse_ex on a file; prints
 * err code, char_offset, and the plain serialization of the result. */
#include <stdio.h>
#include <stdlib.h>
#include "json.h"
int main(int argc, char **argv)
{
	int flags = atoi(argv[1]);
	FILE *f = fopen(argv[2], "rb"); static char buf[1 << 24];
	size_t n = fread(buf, 1, sizeof buf - 1, f); buf[n] = 0; fclose(f);
	json_tokener *tok = json_tokener_new();
	json_tokener_set_flags(tok, flags);
	json_object *o = json_tokener_parse_ex(tok, buf, (int)n + 1); /* include NUL = end of input */
	enum json_tokener_error e = json_tokener_get_error(tok);
	printf("%d\t%zu\t%s\n", e, json_tokener_get_parse_end(tok), o ? json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN) : "");
	json_object_put(o); json_tokener_free(tok);
	return 0;
}
