/* An unterminated comment at end of input inside an open array/object makes
 * json_tokener_parse() report success and return the *last inner element*
 * instead of failing.  Build: cc repro.c -ljson-c */
#include <stdio.h>
#include <json-c/json.h>
static void t(const char *s)
{
	enum json_tokener_error e;
	json_object *o = json_tokener_parse_verbose(s, &e);
	printf("%-14s -> %-22s %s\n", s, json_tokener_error_desc(e), o ? json_object_to_json_string(o) : "(null)");
	json_object_put(o);
}
int main(void)
{
	t("[1,2");        /* unexpected end of data (correct) */
	t("[1,2/**/");    /* unexpected end of data (correct) */
	t("[1,2/*");      /* success, returns 2       (bug) */
	t("[1,2//");      /* success, returns 2       (bug) */
	t("{\"a\":\"x\" /*"); /* success, returns "x"     (bug) */
	t("[[1]/*");      /* success, returns [ 1 ]   (bug) */
	return 0;
}
