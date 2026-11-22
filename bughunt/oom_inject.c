/* Fault injection: fail the Nth heap allocation made inside
 * json_tokener_parse_ex (malloc/calloc/realloc/strdup wrapped at link time),
 * for every N until the parse no longer allocates N times. ASan/LSan report
 * memory errors and leaks; we also check the API contract: on allocation
 * failure the call must return NULL (or a complete, correct value). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sanitizer/lsan_interface.h>
#include "json.h"
void *__real_malloc(size_t); void *__real_calloc(size_t, size_t); void *__real_realloc(void *, size_t); char *__real_strdup(const char *);
static long countdown = -1, calls = 0;
static int fail_now(void) { if (countdown < 0) return 0; calls++; return calls == countdown; }
void *__wrap_malloc(size_t n) { return fail_now() ? NULL : __real_malloc(n); }
void *__wrap_calloc(size_t a, size_t b) { return fail_now() ? NULL : __real_calloc(a, b); }
void *__wrap_realloc(void *p, size_t n) { return fail_now() ? NULL : __real_realloc(p, n); }
char *__wrap_strdup(const char *s) { if (fail_now()) return NULL; size_t l = strlen(s) + 1; char *r = __real_malloc(l); memcpy(r, s, l); return r; }

static int bad = 0;
static void one(const char *s, int flags, int chunked)
{
	/* reference */
	json_tokener *t = json_tokener_new(); json_tokener_set_flags(t, flags);
	json_object *o = json_tokener_parse_ex(t, s, (int)strlen(s) + 1);
	char *want = strdup(o ? json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN) : "<null>");
	int werr = json_tokener_get_error(t);
	json_object_put(o); json_tokener_free(t);
	for (long n = 1; n < 5000; n++) {
		t = json_tokener_new(); json_tokener_set_flags(t, flags);
		calls = 0; countdown = n;
		size_t L = strlen(s); json_object *r = NULL; int e = 0;
		if (!chunked) { r = json_tokener_parse_ex(t, s, (int)L + 1); e = json_tokener_get_error(t); }
		else for (size_t i = 0; i <= L; i++) { r = json_tokener_parse_ex(t, s + i, 1); e = json_tokener_get_error(t); if (e != json_tokener_continue) break; }
		long used = calls; countdown = -1;
		char *got = strdup(r ? json_object_to_json_string_ext(r, JSON_C_TO_STRING_PLAIN) : "<null>");
		if (used >= n) { /* the injected failure happened */
			if (e == json_tokener_success && strcmp(got, want)) { bad++; printf("WRONG-VALUE n=%ld flags=%d chunked=%d input=%s\n  want %s got %s\n", n, flags, chunked, s, want, got); }
			if (e != json_tokener_success && e != json_tokener_error_memory && werr == 0) { bad++; printf("WRONG-ERR n=%ld flags=%d chunked=%d input=%s err=%s\n", n, flags, chunked, s, json_tokener_error_desc(e)); }
			if (e != json_tokener_success && r) { bad++; printf("NONNULL-ON-ERR n=%ld input=%s\n", n, s); }
		}
		free(got); json_object_put(r); json_tokener_free(t);
		if (__lsan_do_recoverable_leak_check()) { bad++; printf("LEAK n=%ld flags=%d chunked=%d input=%s\n", n, flags, chunked, s); }
		if (used < n) break;
	}
	free(want);
}
int main(int argc, char **argv)
{
	char line[4096];
	FILE *in = fopen(argv[1], "r");
	while (fgets(line, sizeof line, in)) {
		line[strcspn(line, "\n")] = 0;
		for (int f = 0; f < 2; f++) for (int c = 0; c < 2; c++) one(line, f ? JSON_TOKENER_STRICT : 0, c);
	}
	printf("problems: %d\n", bad);
	return 0;
}
