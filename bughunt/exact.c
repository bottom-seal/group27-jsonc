// Every chunk lives in its own exact-size heap allocation with no NUL after it,
// so any read at str[len] or beyond trips ASan.
#include "json.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned long long CALLS=0;
static void feed(const unsigned char*d,size_t n,int fl,size_t step){
  struct json_tokener*t=json_tokener_new(); json_tokener_set_flags(t,fl); json_object*o=NULL;
  for(size_t i=0;i<n;i+=step){ size_t k = n-i<step? n-i: step; char*c=malloc(k); memcpy(c,d+i,k);
    o=json_tokener_parse_ex(t,c,(int)k); free(c); CALLS++; enum json_tokener_error e=json_tokener_get_error(t);
    json_object_put(o); o=NULL; if(e!=json_tokener_continue){ if(e==json_tokener_success){ json_tokener_reset(t);} else break; } }
  /* final zero-length call with a 0-byte allocation */
  char*z=malloc(1); o=json_tokener_parse_ex(t,z,0); free(z); json_object_put(o);
  json_tokener_free(t);}
int main(int argc,char**argv){ static unsigned char buf[1<<16]; const int FL[]={0,1,3,0x10,0x13};
  for(int i=1;i<argc;i++){ FILE*f=fopen(argv[i],"rb"); if(!f)continue; size_t n=fread(buf,1,sizeof buf,f); fclose(f);
    if(n==0) continue; const unsigned char*d=buf+1; size_t m=n-1; (void)d; // use whole file
    for(int a=0;a<5;a++){ feed(buf,n,FL[a],n); feed(buf,n,FL[a],1); feed(buf,n,FL[a],3); } }
  fprintf(stderr,"calls=%llu\n",CALLS); return 0;}
