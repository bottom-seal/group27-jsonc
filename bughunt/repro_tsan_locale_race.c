/* Two threads make their first json_tokener_parse_ex calls at the same time,
 * each with its own tokener. ThreadSanitizer reports a data race on the
 * unsynchronised lazy init of the static c_numeric_locale (json_tokener.c:357/359).
 * Build json-c and this file with -fsanitize=thread, e.g.
 *   clang -fsanitize=thread repro_tsan_locale_race.c libjson-c.a -lm -lpthread */
#include <pthread.h>
#include <stdio.h>
#include "json.h"
static pthread_barrier_t bar;
static void *worker(void *arg)
{
	(void)arg;
	pthread_barrier_wait(&bar);
	json_tokener *t = json_tokener_new();
	json_object *o = json_tokener_parse_ex(t, "[1.5, 2]", 9);
	json_object_put(o);
	json_tokener_free(t);
	return NULL;
}
int main(void)
{
	pthread_t a, b;
	pthread_barrier_init(&bar, NULL, 2);
	pthread_create(&a, NULL, worker, NULL);
	pthread_create(&b, NULL, worker, NULL);
	pthread_join(a, NULL); pthread_join(b, NULL);
	puts("done");
	return 0;
}
