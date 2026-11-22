"""Differential oracle: json-c non-strict one-shot parse vs ref_lenient model.
Usage: python3 ref_oracle.py SEED COUNT"""
import random, subprocess, sys, json, math, collections
sys.path.insert(0, '.')
from ref_lenient import parse, Reject, KnownBug
R = random.Random(int(sys.argv[1])); N = int(sys.argv[2])
WS = ['', '', ' ', '\n', '\t', '/**/', '/* c */', '// c\n', '/*\n*/', '/* ** */', '/*/*/']
NUMS = ['0', '-0', '1', '-12', '3.25', '1e3', '-2E-2', '0.5e+1', '123456789', '9223372036854775807', '-9223372036854775808', '18446744073709551615']
STRS = ['""', '"a"', "'b'", '"\\n\\t"', '"\\u0041"', '"\\u00e9"', '"\\ud83d\\ude00"', '"\\ud83d"', '"q\'"', "'d\"'", '"\\/"', '"\xc3\xa9"', '"\x01"']
LITS = ['true', 'false', 'null', 'TRUE', 'Null', 'NaN', 'nan', 'Infinity', '-Infinity', 'infinity', '-inf'.replace('inf', 'Infinity')]
def w(): return R.choice(WS)
def val(d=0):
    r = R.random()
    if d > 4 or r < 0.45: return R.choice(NUMS + STRS + LITS)
    if r < 0.72:
        items = [w() + val(d + 1) + w() for _ in range(R.randint(0, 3))]
        return '[' + w() + ','.join(items) + (',' + w() if items and R.random() < 0.2 else '') + ']'
    items = [w() + R.choice(['"k"', "'k2'", '"a"', '""', '"\\u0062"']) + w() + ':' + w() + val(d + 1) + w() for _ in range(R.randint(0, 3))]
    return '{' + w() + ','.join(items) + (',' + w() if items and R.random() < 0.2 else '') + '}'
def mutate(s):
    if R.random() < 0.5 or not s: return s
    i = R.randrange(len(s) + 1); op = R.random()
    ch = R.choice(list('[]{},:"\'/* \n') + ['/*', '*/', '//', '**/'])
    if op < 0.4: return s[:i] + ch + s[i:]
    if op < 0.7: return s[:i] + s[i + 1:]
    return s[:i]  # truncate
cases = []
for _ in range(N):
    s = w() + val() + w()
    cases.append(mutate(s))
enc = lambda s: ''.join(chr(c) if 0x20 <= c < 0x7f and c != 0x5c else '\\x%02x' % c for c in s.encode('latin-1'))
cases = [c for c in cases if '\x00' not in c]
out = subprocess.run(['./batch', '0'], input='\n'.join(enc(c) for c in cases) + '\n', capture_output=True, text=True, encoding='latin-1').stdout.split('\n')
def eq(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b): return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool): return a == b
    if type(a) != type(b): return False
    if isinstance(a, list): return len(a) == len(b) and all(eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict): return a.keys() == b.keys() and all(eq(a[k], b[k]) for k in a)
    return a == b
cats = collections.Counter(); ex = {}
for c, line in zip(cases, out):
    err, end, ser = line.split('\t', 2)
    try: rv = parse(c); rok = True
    except Reject as e: rok = False; why = str(e)
    except RecursionError: continue
    except KnownBug: continue
    cok = err == '0'
    if cok != rok: k = ('jsonc-accepts' if cok else 'jsonc-rejects', why if not rok else 'err' + err)
    elif cok:
        try: cv = json.loads(ser)
        except ValueError:
            k = ('jsonc-output-not-json', ''); cats[k] += 1
            if k not in ex or len(c) < len(ex[k][0]): ex[k] = (c, line)
            continue
        if eq(cv, rv): continue
        k = ('value-differs', '')
    else: continue
    cats[k] += 1
    if len(sys.argv) > 3: print('EX', k, repr(c), repr(line[:100]))
    if k not in ex or len(c) < len(ex[k][0]): ex[k] = (c, line)
for k, v in cats.most_common():
    print(v, k); print('    input:', repr(ex[k][0])); print('    jsonc:', repr(ex[k][1][:120]))
print('cases', len(cases))
