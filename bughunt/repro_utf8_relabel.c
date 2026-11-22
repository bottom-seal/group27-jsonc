// With JSON_TOKENER_VALIDATE_UTF8, a syntax error that lands on a valid multi-byte
// UTF-8 character is reported as "invalid utf-8 string" instead of the real error.
// Same root cause as finding 3: PEEK_CHAR leaves a pending multi-byte count for the
// lead byte, and the epilogue at out: overwrites tok->err with parse_utf8_string.
// Build: cc repro_utf8_relabel.c -ljson-c
#include <stdio.h>
#include <string.h>
#include <json-c/json.h>
static void t(const char *s)
{
	for (int fl = 0; fl <= JSON_TOKENER_VALIDATE_UTF8; fl += JSON_TOKENER_VALIDATE_UTF8)
	{
		struct json_tokener *tok = json_tokener_new();
		json_tokener_set_flags(tok, fl);
		json_object *o = json_tokener_parse_ex(tok, s, (int)strlen(s) + 1);
		printf("%-22s %-14s -> %s\n", s, fl ? "VALIDATE_UTF8" : "default",
		       json_tokener_error_desc(json_tokener_get_error(tok)));
		json_object_put(o);
		json_tokener_free(tok);
	}
}
int main(void)
{
	t("\xef\xbb\xbf{}"); /* UTF-8 BOM, valid UTF-8 */
	t("[\xc3\xa9]");     /* [é] */
	t("{\xc3\xa9:1}");   /* {é:1} */
	t("[1\xc3\xa9]");    /* [1é] */
	t("[tru\xc3\xa9]");  /* [trué] */
	t("[x]");            /* ASCII: error is reported correctly */
	return 0;
}
