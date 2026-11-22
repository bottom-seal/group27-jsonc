/* BVA on json_tokener_new_ex(max_depth): nesting max_depth-1, max_depth, max_depth+1
 * for arrays and objects, one-shot and bytewise. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "json.h"
static int go(int maxd, const char *s, int bytewise)
{
	json_tokener *t = json_tokener_new_ex(maxd); json_object *o = NULL; int n = strlen(s), e;
	if (!bytewise) { o = json_tokener_parse_ex(t, s, n + 1); e = json_tokener_get_error(t); }
	else { for (int i = 0; i <= n; i++) { o = json_tokener_parse_ex(t, s + i, 1); e = json_tokener_get_error(t); if (e != json_tokener_continue) break; } }
	json_object_put(o); json_tokener_free(t); return e;
}
int main(void)
{
	int ds[] = {1, 2, 3, 32, 100};
	for (int di = 0; di < 5; di++) for (int k = ds[di] - 1; k <= ds[di] + 1; k++) for (int obj = 0; obj < 2; obj++) {
		if (k < 0) continue;
		char s[4096] = ""; for (int i = 0; i < k; i++) strcat(s, obj ? "{\"a\":" : "[");
		strcat(s, "1"); for (int i = 0; i < k; i++) strcat(s, obj ? "}" : "]");
		int a = go(ds[di], s, 0), b = go(ds[di], s, 1);
		printf("max=%3d nest=%3d %s oneshot=%-28s bytewise=%s%s\n", ds[di], k, obj ? "obj" : "arr", json_tokener_error_desc(a), json_tokener_error_desc(b), a != b ? "   <-- DIFF" : "");
	}
	return 0;
}
