/* JSON_TOKENER_STRICT rejects single-quoted string values but still accepts
 * single-quoted object keys.  Build: cc repro.c -ljson-c */
#include <stdio.h>
#include <json-c/json.h>
static void t(const char *s)
{
	json_tokener *tok = json_tokener_new();
	json_tokener_set_flags(tok, JSON_TOKENER_STRICT);
	json_object *o = json_tokener_parse_ex(tok, s, -1);
	printf("%-10s -> %s %s\n", s, json_tokener_error_desc(json_tokener_get_error(tok)),
	       o ? json_object_to_json_string(o) : "");
	json_object_put(o);
	json_tokener_free(tok);
}
int main(void)
{
	t("['a']");    /* rejected: unexpected character (correct) */
	t("{'a':1}");  /* accepted: { "a": 1 }  (bug: should be rejected) */
	return 0;
}
