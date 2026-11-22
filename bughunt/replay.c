#include <stdio.h>
int LLVMFuzzerTestOneInput(const unsigned char *d, size_t n);
int main(int argc, char **argv)
{
	static unsigned char buf[1 << 16];
	for (int i = 1; i < argc; i++) {
		FILE *f = fopen(argv[i], "rb"); if (!f) continue;
		size_t n = fread(buf, 1, sizeof buf, f); fclose(f);
		LLVMFuzzerTestOneInput(buf, n);
	}
	return 0;
}
