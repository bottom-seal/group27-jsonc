// Escape equivalence: raw UTF-8, \uXXXX (lower/upper hex) and surrogate-pair spellings of the
// same code points must parse to identical bytes, as values and as keys, one-shot, bytewise
// and at every 2-split, under flags 0 / STRICT / VALIDATE_UTF8. Plus reset between surrogate halves.
#include "json.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int enc8(unsigned cp,char*o){ if(cp<0x80){o[0]=cp;return 1;} if(cp<0x800){o[0]=0xC0|cp>>6;o[1]=0x80|(cp&63);return 2;}
 if(cp<0x10000){o[0]=0xE0|cp>>12;o[1]=0x80|((cp>>6)&63);o[2]=0x80|(cp&63);return 3;} o[0]=0xF0|cp>>18;o[1]=0x80|((cp>>12)&63);o[2]=0x80|((cp>>6)&63);o[3]=0x80|(cp&63);return 4;}
static int escu(unsigned cp,char*o,int up){ const char*f=up?"\\u%04X":"\\u%04x"; if(cp<0x10000) return sprintf(o,f,cp); unsigned v=cp-0x10000; int n=sprintf(o,f,0xD800+(v>>10)); return n+sprintf(o+n,f,0xDC00+(v&0x3FF)); }
static char*val(const char*s,size_t n,int fl,int mode,size_t cut){ struct json_tokener*t=json_tokener_new(); json_tokener_set_flags(t,fl); json_object*o=NULL; enum json_tokener_error e;
 if(mode==0){o=json_tokener_parse_ex(t,s,(int)n+1);} else if(mode==1){ for(size_t i=0;i<=n;i++){o=json_tokener_parse_ex(t,s+i,1); if(json_tokener_get_error(t)!=json_tokener_continue)break;} }
 else { o=json_tokener_parse_ex(t,s,(int)cut); if(json_tokener_get_error(t)==json_tokener_continue) o=json_tokener_parse_ex(t,s+cut,(int)(n-cut)+1); }
 e=json_tokener_get_error(t); char*r=NULL;
 if(e==json_tokener_success && o){ json_object*x=json_object_get_type(o)==json_type_array?json_object_array_get_idx(o,0):NULL;
   if(x){ r=malloc(json_object_get_string_len(x)+1); memcpy(r,json_object_get_string(x),json_object_get_string_len(x)+1); r[json_object_get_string_len(x)]=0; size_t L=json_object_get_string_len(x); r=realloc(r,L+20); sprintf(r+L,"|len=%zu",L);} 
   else { json_object_object_foreach(o,k,v){ (void)v; r=strdup(k); } } }
 else { r=malloc(64); sprintf(r,"ERR%d",e); }
 json_object_put(o); json_tokener_free(t); return r; }
static const unsigned CPS[]={'a',0,1,0x1f,'"','\\','/',0x7f,0x80,0xff,0x100,0x7ff,0x800,0xfff,0x1000,0xd7ff,0xe000,0xfeff,0xfffd,0xfffe,0xffff,0x10000,0x1f600,0x1da87,0xfffff,0x100000,0x10fffe,0x10ffff,0x2028,0x2029};
int main(){ srand(7); long bad=0, tests=0; const int FL[]={0,1,0x10};
 for(int it=0;it<20000;it++){ int k=1+rand()%4; unsigned cp[4]; for(int j=0;j<k;j++) cp[j]=CPS[rand()%(sizeof CPS/sizeof*CPS)];
  int key=rand()%2; char raw[64],esc[128],mix[128]; int a=0,b=0,c=0; int up=rand()%2;
  const char*pre=key?"{\"":"[\""; const char*suf=key?"\":1}":"\"]";
  a+=sprintf(raw+a,"%s",pre); b+=sprintf(esc+b,"%s",pre); c+=sprintf(mix+c,"%s",pre);
  int rawok=1; for(int j=0;j<k;j++){ unsigned x=cp[j]; if(x<0x20||x=='"'||x=='\\') rawok=0; a+=enc8(x,raw+a); b+=escu(x,esc+b,up); if(rand()%2) c+=escu(x,mix+c,!up); else if(x<0x20||x=='"'||x=='\\'){ c+=escu(x,mix+c,up);} else c+=enc8(x,mix+c);} 
  if(k==1 && cp[0]==0 && key) continue; /* NUL in key: known truncation (#715) */
  int hasnul=0; for(int j=0;j<k;j++) if(cp[j]==0) hasnul=1; if(key&&hasnul) continue;
  a+=sprintf(raw+a,"%s",suf); b+=sprintf(esc+b,"%s",suf); c+=sprintf(mix+c,"%s",suf);
  for(int f=0;f<3;f++){ char*ref=val(esc,b,FL[f],0,0);
   const char*vs[3]={esc,mix,raw}; int ls[3]={b,c,a};
   for(int w=0;w<3;w++){ if(w==2&&!rawok) continue;
    for(int mode=0;mode<3;mode++){ int cuts = mode==2? ls[w]:1; for(int cut=1; cut<=cuts; cut++){ if(mode==2 && cut>=ls[w]) break; char*r=val(vs[w],ls[w],FL[f],mode,cut); tests++;
      if(strcmp(r,ref)){ if(getenv("ALL")) printf("flags=%#x mode=%d cut=%d\n  ref %s -> %s\n  got %s -> %s\n",FL[f],mode,cut,esc,ref,vs[w],r); bad++; } free(r);} } }
   free(ref);} }
 /* reset between surrogate halves */
 struct json_tokener*t=json_tokener_new(); json_object*o=json_tokener_parse_ex(t,"\"\\ud83d",7); json_tokener_reset(t); o=json_tokener_parse_ex(t,"\"\\ude00x\"",10);
 printf("reset-between-halves: %s (expect \"\\ufffdx\")\n", o?json_object_to_json_string(o):"NULL"); json_object_put(o); json_tokener_free(t);
 printf("tests=%ld mismatches=%ld\n",tests,bad); return 0; }
