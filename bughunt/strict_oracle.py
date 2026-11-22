"""Differential oracle on generated inputs: json-c JSON_TOKENER_STRICT vs
Python json (RFC 8259). NaN/Infinity (accepted by json-c strict by design)
are excluded from the generator. Usage: python3 strict_oracle.py SEED COUNT"""
import random, subprocess, sys, json, collections
R = random.Random(int(sys.argv[1])); N = int(sys.argv[2])
WS = ['', '', ' ', '\n', '\t', '\r', '\x0c', '\x0b', '\xa0']
NUMS = ['0', '-0', '1', '-12', '3.25', '1e3', '-2E-2', '0.5e+1', '9223372036854775807', '-9223372036854775808', '1.0', '10', '0e0']
STRS = ['""', '"a"', '"\\n\\t"', '"\\u0041"', '"\\u00e9"', '"\\ud83d\\ude00"', '"\\/"', '"\xc3\xa9"', '"\\""', '"\\\\"', '"\\b\\f\\r"']
LITS = ['true', 'false', 'null']
def w(): return R.choice(WS)
def val(d=0):
    r = R.random()
    if d > 4 or r < 0.45: return R.choice(NUMS + STRS + LITS)
    if r < 0.72: return '[' + w() + ','.join(w() + val(d + 1) + w() for _ in range(R.randint(0, 3))) + ']'
    return '{' + w() + ','.join(w() + R.choice(['"k"', '"a"', '""', '"\\u0062"', '"\\n"']) + w() + ':' + w() + val(d + 1) + w() for _ in range(R.randint(0, 3))) + '}'
TOK = list('[]{},:"\'-+.eE0123456789\\/ tfnu') + ['\x00', '\x01', '\x1f', '\x7f', 'true', 'null', '\\u', '\\ud800', '//', '/*', '*/', ',]', ',}']
def mutate(s):
    for _ in range(R.choice([0, 1, 1, 2])):
        i = R.randrange(len(s) + 1); op = R.random()
        if op < 0.45: s = s[:i] + R.choice(TOK) + s[i:]
        elif op < 0.8: s = s[:i] + s[i + 1:]
        else: s = s[:i] + R.choice(TOK) + s[i + 1:]
    return s
cases = [c for c in (mutate(w() + val() + w()) for _ in range(N)) if '\x00' not in c and 'nan' not in c.lower() and 'inf' not in c.lower()]
enc = lambda s: ''.join(chr(c) if 0x20 <= c < 0x7f and c != 0x5c else '\\x%02x' % c for c in s.encode('latin-1'))
out = subprocess.run(['./batch', sys.argv[4] if len(sys.argv) > 4 else '1'], input='\n'.join(enc(c) for c in cases) + '\n', capture_output=True, text=True, encoding='latin-1').stdout.split('\n')
def rej(x): raise ValueError(x)
cats = collections.Counter(); ex = {}
for c, line in zip(cases, out):
    err, end, ser = line.split('\t', 2)
    try: pv = json.loads(c.encode('latin-1').decode('utf-8'), parse_constant=rej); pok = True
    except (ValueError, UnicodeDecodeError): pok = False
    cok = err == '0'
    if cok == pok:
        if not cok: continue
        try:
            if json.loads(ser.encode('latin-1').decode('utf-8')) == pv: continue
        except Exception: pass
        k = 'value-differs'
    else: k = ('ACCEPTS' if cok else 'REJECTS') + ' err' + err
    cats[k] += 1
    if k not in ex or len(c) < len(ex[k][0]): ex[k] = (c, line)
    if len(sys.argv) > 3: print('EX', k, repr(c), repr(line[:100]))
for k, v in cats.most_common(): print(v, k, '  e.g.', repr(ex[k][0]), '->', repr(ex[k][1][:80]))
print('cases', len(cases))
