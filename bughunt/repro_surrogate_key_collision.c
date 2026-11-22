// Lone surrogate escapes are replaced with U+FFFD, so distinct escaped keys collide
// and members are silently dropped, also in STRICT mode and with VALIDATE_UTF8.
// Python's json keeps all three keys in the last example.
// Build: cc repro_surrogate_key_collision.c -ljson-c
#include <stdio.h>
#include <string.h>
#include <json-c/json.h>
int main(void)
{
	const char *in[] = {"{\"\\ud800\":1,\"\\udc00\":2}", "{\"\\ud800\":1,\"\\ufffd\":2}",
	                    "{\"a\\ud800\":1,\"a\\udbff\":2,\"a\\udfff\":3}"};
	for (int i = 0; i < 3; i++)
	{
		struct json_tokener *tok = json_tokener_new();
		json_tokener_set_flags(tok, JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8);
		json_object *o = json_tokener_parse_ex(tok, in[i], (int)strlen(in[i]) + 1);
		printf("%-40s -> %d member(s): %s\n", in[i], o ? json_object_object_length(o) : -1,
		       o ? json_object_to_json_string(o) : json_tokener_error_desc(json_tokener_get_error(tok)));
		json_object_put(o);
		json_tokener_free(tok);
	}
	return 0;
}
