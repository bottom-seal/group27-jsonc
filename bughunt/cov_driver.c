#include "json.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static const int FL[]={0,1,3,0x10,0x11,0x13};
static void one(const char*b,size_t n,int fl,int mode){
  struct json_tokener*t=json_tokener_new_ex(mode==5?4:32); json_tokener_set_flags(t,fl); json_object*o=NULL;
  if(mode==0) o=json_tokener_parse_ex(t,b,(int)n+1);
  else if(mode==1) o=json_tokener_parse_ex(t,b,-1);
  else if(mode==2){ for(size_t i=0;i<=n;i++){ o=json_tokener_parse_ex(t,b+i,1); if(json_tokener_get_error(t)!=json_tokener_continue)break; } }
  else if(mode==3){ size_t h=n/2; o=json_tokener_parse_ex(t,b,(int)h); if(json_tokener_get_error(t)==json_tokener_continue) o=json_tokener_parse_ex(t,b+h,(int)(n-h)+1); }
  else if(mode==4){ size_t off=0; for(int k=0;k<64&&off<=n;k++){ o=json_tokener_parse_ex(t,b+off,(int)(n-off)+1); enum json_tokener_error e=json_tokener_get_error(t); json_object_put(o); o=NULL; if(e!=json_tokener_success) { json_tokener_reset(t); off++; continue;} size_t pe=json_tokener_get_parse_end(t); if(pe==0) off++; else off+=pe; } }
  else if(mode==5) o=json_tokener_parse_ex(t,b,(int)n+1);
  else if(mode==6) o=json_tokener_parse_ex(t,b,(int)n); /* no NUL: continue paths */
  json_object_put(o); json_tokener_free(t);
}
int main(int argc,char**argv){ static char buf[1<<16];
  for(int i=1;i<argc;i++){ FILE*f=fopen(argv[i],"rb"); if(!f)continue;
    /* .txt files: one input per line; others: whole file */
    size_t L=strlen(argv[i]); int lines = L>4 && !strcmp(argv[i]+L-4,".txt");
    if(lines){ char *line=NULL; size_t cap=0; ssize_t r; while((r=getline(&line,&cap,f))>0){ if(line[r-1]=='\n') line[--r]=0; for(int a=0;a<6;a++) for(int m=0;m<7;m++) one(line,(size_t)r,FL[a],m);} free(line);}
    else { size_t n=fread(buf,1,sizeof buf-1,f); buf[n]=0; for(int a=0;a<6;a++) for(int m=0;m<7;m++) one(buf,n,FL[a],m); }
    fclose(f);} return 0; }
