/* libFuzzer target for json_tokener_parse_ex: ASan/UBSan catch memory bugs,
 * and a metamorphic oracle aborts when a split feed disagrees with the
 * one-shot parse.  Byte 0 picks flags, byte 1 picks the split point. */
#define NO_MAIN
#include "chunk_meta.c"
int LLVMFuzzerTestOneInput(const unsigned char *d, size_t n)
{
	if (n < 2 || n > 4096) return 0;
	int f = FLAGS[d[0] % (sizeof(FLAGS) / sizeof(FLAGS[0]))];
	char *s = malloc(n - 2 + 1); memcpy(s, d + 2, n - 2); s[n - 2] = 0;
	size_t len = strlen(s); /* NUL ends input for json-c */
	if (len >= 2) {
		size_t cut = 1 + d[1] % (len - 1);
		res_t one = run(s, len, NULL, 0, f), two = run(s, len, &cut, 1, f);
		if (!same(&one, &two)) { printf("flags=0x%x split@%zu\n", f, cut); show("oneshot", &one); show("split", &two); abort(); }
		free(one.out); free(two.out);
		size_t cuts[4096]; for (size_t k = 1; k < len; k++) cuts[k - 1] = k;
		one = run(s, len, NULL, 0, f); two = run(s, len, cuts, (int)len - 1, f);
		if (!same(&one, &two)) { printf("flags=0x%x bytewise\n", f); show("oneshot", &one); show("bytewise", &two); abort(); }
		free(one.out); free(two.out);
	}
	free(s);
	return 0;
}
