// Comment text is copied into tok->pb as it is parsed (used only by MC_DEBUG),
// so a streaming reader that feeds a long comment in fixed 64 KiB chunks needs
// memory equal to the whole comment, while the same amount of whitespace needs none.
// Usage: ./a.out BYTES WS   (WS=1 whitespace, WS=0 comment)
// Build: cc -O2 repro_comment_memory.c -ljson-c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <json-c/json.h>
static long hwm(void){ FILE*f=fopen("/proc/self/status","r"); char l[256]; long v=0; while(fgets(l,256,f)) if(!strncmp(l,"VmHWM:",6)) v=atol(l+6); fclose(f); return v; }
int main(int c, char **v){ size_t n=atol(v[1]); int ws=atoi(v[2]); size_t ch=65536; char *buf=malloc(ch); json_tokener *t=json_tokener_new(); json_object *o;
 o=json_tokener_parse_ex(t, ws ? "[1 " : "[1 /*", ws ? 3 : 5); memset(buf, ws ? ' ' : 'x', ch);
 for(size_t i=0;i<n;i+=ch) o=json_tokener_parse_ex(t,buf,ch);
 o=json_tokener_parse_ex(t, ws ? "]" : "*/]", ws ? 2 : 4);
 printf("%s, %zu MB of %s fed in 64 KiB chunks: peak RSS %ld MB, result %s\n", v[0], n>>20, ws ? "whitespace" : "comment text", hwm()>>10, o?json_object_to_json_string(o):json_tokener_error_desc(json_tokener_get_error(t))); json_object_put(o); json_tokener_free(t); }
