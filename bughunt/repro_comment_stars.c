// A block comment that ends in an even run of stars before the slash
// ("/* x **" "/", "/***" "/", "/* x ****" "/") is not recognised as closed.
// Build: cc repro_comment_stars.c -ljson-c
#include <stdio.h>
#include <json-c/json.h>
static void t(const char *s)
{
	enum json_tokener_error e;
	json_object *o = json_tokener_parse_verbose(s, &e);
	printf("%-22s -> %-22s %s\n", s, json_tokener_error_desc(e), o ? json_object_to_json_string(o) : "(null)");
	json_object_put(o);
}
int main(void)
{
	t("[1 /* x */ ]");       // [ 1 ]                    correct
	t("[1 /****/ ]");        // [ 1 ]                    correct
	t("/** doc **/ 1");      // unexpected end of data   bug: should be 1
	t("[1 /***/ ]");         // success, returns 1       bug: should be [ 1 ]
	t("[1 /* x **/ ] */ ]"); // [ 1 ]: comment runs on to the later star-slash  bug
	return 0;
}
