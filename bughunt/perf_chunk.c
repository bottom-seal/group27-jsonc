/* Time json_tokener_parse_ex on a long token fed in one call vs 1-byte chunks. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "json.h"
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }
static void run(const char *name, char *s, size_t n, size_t chunk)
{
	json_tokener *t = json_tokener_new(); json_object *o = NULL; double t0 = now();
	for (size_t i = 0; i <= n; i += chunk) { size_t l = (i + chunk <= n + 1) ? chunk : n + 1 - i; o = json_tokener_parse_ex(t, s + i, (int)l); if (json_tokener_get_error(t) != json_tokener_continue) break; }
	printf("%-10s n=%7zu chunk=%5zu  %8.3f s  err=%s\n", name, n, chunk, now() - t0, json_tokener_error_desc(json_tokener_get_error(t)));
	json_object_put(o); json_tokener_free(t);
}
int main(int argc, char **argv)
{
	size_t n = atoi(argv[1]); char *s = malloc(n + 8);
	memset(s, '1', n); s[n] = 0; run("int", s, n, n + 1); run("int", s, n, 1);
	memset(s, '1', n); s[1] = '.'; run("double", s, n, n + 1); run("double", s, n, 1);
	memset(s, '1', n); s[1] = 'e'; run("exp", s, n, n + 1); run("exp", s, n, 1);
	memset(s, 'a', n); s[0] = '"'; s[n - 1] = '"'; run("string", s, n, n + 1); run("string", s, n, 1);
	memset(s, ' ', n); s[n - 1] = '1'; run("ws", s, n, n + 1); run("ws", s, n, 1);
	memset(s, 'x', n); memcpy(s, "/*", 2); memcpy(s + n - 3, "*/1", 3); run("comment", s, n, n + 1); run("comment", s, n, 1);
	return 0;
}
