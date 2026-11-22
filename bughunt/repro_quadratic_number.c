// json_tokener_parse_ex is quadratic when a long number is fed in small
// chunks: every call that resumes json_tokener_state_number runs
// strchr(tok->pb->buf, 'e') and strchr(tok->pb->buf, 'E') over all the digits
// saved so far. Other long tokens (strings, comments, whitespace) stay linear.
// Build: cc -O2 repro_quadratic_number.c -ljson-c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <json-c/json.h>
static double feed(const char *s, size_t n, size_t chunk)
{
	struct timespec a, b;
	json_tokener *t = json_tokener_new();
	clock_gettime(CLOCK_MONOTONIC, &a);
	for (size_t i = 0; i <= n; i += chunk) {
		size_t l = i + chunk <= n + 1 ? chunk : n + 1 - i; // last chunk includes the NUL
		json_object *o = json_tokener_parse_ex(t, s + i, (int)l);
		if (json_tokener_get_error(t) != json_tokener_continue) { json_object_put(o); break; }
	}
	clock_gettime(CLOCK_MONOTONIC, &b);
	json_tokener_free(t);
	return (b.tv_sec - a.tv_sec) + (b.tv_nsec - a.tv_nsec) / 1e9;
}
int main(void)
{
	for (size_t n = 160000; n <= 1280000; n *= 2) {
		char *num = malloc(n + 1), *str = malloc(n + 1);
		memset(num, '1', n); num[n] = 0;                       // 111...1
		memset(str, 'a', n); str[0] = str[n - 1] = '"'; str[n] = 0; // "aaa...a"
		printf("n=%8zu  number, 1-byte chunks: %7.3f s   string, 1-byte chunks: %7.3f s\n",
		       n, feed(num, n, 1), feed(str, n, 1));
		free(num); free(str);
	}
	return 0;
}
