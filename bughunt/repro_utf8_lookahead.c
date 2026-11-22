// With JSON_TOKENER_VALIDATE_UTF8, a complete value followed by a valid
// multi-byte UTF-8 character fails with "invalid utf-8 string" and the value is
// dropped, while the same value followed by an ASCII character succeeds.
// Most visible with JSON_TOKENER_STRICT | JSON_TOKENER_ALLOW_TRAILING_CHARS,
// where trailing characters are documented as allowed.
// Build: cc repro_utf8_lookahead.c -ljson-c
#include <stdio.h>
#include <json-c/json.h>
static void t(const char *s, int flags)
{
	json_tokener *tok = json_tokener_new();
	json_tokener_set_flags(tok, flags);
	json_object *o = json_tokener_parse_ex(tok, s, -1);
	printf("flags=0x%02x %-14s -> %-20s end=%zu %s\n", flags, s, json_tokener_error_desc(json_tokener_get_error(tok)),
	       json_tokener_get_parse_end(tok), o ? json_object_to_json_string(o) : "(null)");
	json_object_put(o);
	json_tokener_free(tok);
}
int main(void)
{
	int f = JSON_TOKENER_STRICT | JSON_TOKENER_ALLOW_TRAILING_CHARS;
	t("{\"a\":1}x", f | JSON_TOKENER_VALIDATE_UTF8);            // success, { "a": 1 }
	t("{\"a\":1}\xc3\xa9", f);                                  // success, { "a": 1 }
	t("{\"a\":1}\xc3\xa9", f | JSON_TOKENER_VALIDATE_UTF8);     // invalid utf-8 string (bug: é is valid UTF-8)
	t("1 \xe2\x82\xac", JSON_TOKENER_VALIDATE_UTF8);            // invalid utf-8 string (bug), "1 x" succeeds
	return 0;
}
