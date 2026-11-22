"""Differential oracle: json-c (JSON_TOKENER_STRICT) vs Python json (RFC 8259,
NaN/Infinity rejected) on JSONTestSuite test_parsing files."""
import json, os, subprocess, sys, math
D = sys.argv[1]; flags = sys.argv[2] if len(sys.argv) > 2 else '1'
def rej(x): raise ValueError(x)
def py(b):
    try:
        s = b.decode('utf-8')   # strict UTF-8
        return True, json.loads(s, parse_constant=rej)
    except Exception as e: return False, None
def norm(v):
    if isinstance(v, float) and v.is_integer() and abs(v) < 2**63: return int(v)
    if isinstance(v, list): return [norm(x) for x in v]
    if isinstance(v, dict): return {k: norm(x) for k, x in v.items()}
    return v
for name in sorted(os.listdir(D)):
    b = open(os.path.join(D, name), 'rb').read()
    pok, pv = py(b)
    r = subprocess.run(['./oneshot', flags, os.path.join(D, name)], capture_output=True, timeout=20)
    if r.returncode != 0:
        print('CRASH', name, r.stderr[-300:]); continue
    err, off, out = r.stdout.decode('utf-8', 'replace').rstrip('\n').split('\t', 2)
    cok = err == '0'
    if cok != pok:
        print(('ACCEPTS' if cok else 'REJECTS'), name, 'jsonc_err=%s off=%s/%d out=%r' % (err, off, len(b), out[:80]))
    elif cok:
        try: cv = json.loads(out)
        except Exception as e: print('BADOUT', name, out[:80]); continue
        if norm(cv) != norm(pv): print('VALUE', name, 'jsonc=%r py=%r' % (out[:80], pv))
