// libFuzzer: len=-1 mode on an exact-size heap buffer (NUL is last byte), plus
// an embedded-NUL variant with explicit len covering bytes after the NUL.
#include "json.h"
#include <stdlib.h>
#include <string.h>
int LLVMFuzzerTestOneInput(const unsigned char *d, size_t n){
  if(n<1) return 0;
  int flags = d[0] & 0x13; d++; n--;
  char *b = malloc(n+1); memcpy(b,d,n); b[n]=0;
  struct json_tokener *t = json_tokener_new_ex(16);
  json_tokener_set_flags(t,flags);
  json_object *o = json_tokener_parse_ex(t,b,-1);
  json_object_put(o);
  json_tokener_reset(t);
  o = json_tokener_parse_ex(t,b,(int)n+1);
  json_object_put(o);
  json_tokener_free(t); free(b); return 0;}
