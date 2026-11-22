// Flag monotonicity: if a stricter flag set accepts an input, every laxer set
// (drop STRICT, drop VALIDATE_UTF8, add ALLOW_TRAILING_CHARS) must accept it
// with the same value and the same parse end. One-shot and bytewise.
#include "json.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { int ok; size_t end; char *v; } R;
static R run(const char*b,size_t n,int fl,int bytewise){ R r={0,0,NULL}; struct json_tokener*t=json_tokener_new(); json_tokener_set_flags(t,fl); json_object*o=NULL; enum json_tokener_error e;
  if(!bytewise){ o=json_tokener_parse_ex(t,b,(int)n+1); e=json_tokener_get_error(t); r.end=json_tokener_get_parse_end(t);}
  else { size_t i=0; for(;i<=n;i++){ o=json_tokener_parse_ex(t,b+i,1); e=json_tokener_get_error(t); if(e!=json_tokener_continue) break; } r.end=i+json_tokener_get_parse_end(t); }
  r.ok = (e==json_tokener_success); if(r.ok) r.v=strdup(o?json_object_to_json_string_ext(o,JSON_C_TO_STRING_PLAIN):"(null)");
  json_object_put(o); json_tokener_free(t); return r; }
static long bad=0;
static void cmp(const char*name,const char*b,size_t n,int strict_fl,int lax_fl,int bw){ R s=run(b,n,strict_fl,bw); if(!s.ok) {return;} R l=run(b,n,lax_fl,bw);
  if(!l.ok || strcmp(s.v,l.v) || s.end!=l.end){ if(bad<40){ printf("%s bw=%d flags %#x accepts but %#x %s: ", name,bw,strict_fl,lax_fl, l.ok?"differs":"rejects"); fwrite(b,1,n>60?60:n,stdout); printf("  | %s end=%zu vs %s end=%zu\n",s.v,s.end,l.ok?l.v:"ERR",l.end);} bad++; }
  free(s.v); free(l.v); }
int main(int argc,char**argv){ static char buf[1<<16];
  for(int i=1;i<argc;i++){ FILE*f=fopen(argv[i],"rb"); if(!f)continue; size_t n=fread(buf,1,sizeof buf-1,f); fclose(f); buf[n]=0;
    for(int bw=0;bw<2;bw++) for(int fl=0;fl<0x20;fl++){ if(fl&~0x13) continue;
      if((fl&1)&&!(fl&2)) cmp("drop-STRICT",buf,n,fl,fl&~1,bw);
      if(fl&0x10) cmp("drop-UTF8",buf,n,fl,fl&~0x10,bw);
      if((fl&1)&&!(fl&2)) cmp("add-TRAILING",buf,n,fl,fl|2,bw); } }
  printf("violations: %ld\n",bad); return 0; }
