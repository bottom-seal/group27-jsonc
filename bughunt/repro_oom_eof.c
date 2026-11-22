// When allocating a top-level scalar fails (true, -12, 1.5, NaN, ...), the
// json_tokener_error_memory set by the tokener is overwritten at "out:" by
// json_tokener_error_parse_eof, because the scalar is only built when the
// terminating NUL is seen (c == 0). Commit 99c14de fixed the same clobbering
// for number-range errors but not for memory errors.
// Build (static lib, so the allocator can be wrapped):
//   cc repro_oom_eof.c libjson-c.a -lm -Wl,--wrap=malloc,--wrap=calloc
#include <stdio.h>
#include <stdlib.h>
#include <json-c/json.h>
void *__real_malloc(size_t); void *__real_calloc(size_t, size_t);
static int fail_next = 0;
void *__wrap_malloc(size_t n) { if (fail_next) { fail_next = 0; return NULL; } return __real_malloc(n); }
void *__wrap_calloc(size_t a, size_t b) { if (fail_next) { fail_next = 0; return NULL; } return __real_calloc(a, b); }
static void t(const char *s)
{
	json_tokener *tok = json_tokener_new();
	fail_next = 1; // fail the first allocation made while parsing
	json_object *o = json_tokener_parse_ex(tok, s, -1 /* strlen */ );
	fail_next = 0;
	printf("%-8s -> %s\n", s, json_tokener_error_desc(json_tokener_get_error(tok)));
	json_object_put(o);
	json_tokener_free(tok);
}
int main(void)
{
	// warm up: the first parse creates a cached C locale
	json_object_put(json_tokener_parse("0"));
	t("[true]");  // memory allocation failed (correct)
	t("true");    // unexpected end of data   (bug: should be memory allocation failed)
	t("-12");     // unexpected end of data   (bug)
	return 0;
}
