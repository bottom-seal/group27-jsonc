import random, sys
random.seed(int(sys.argv[1]) if len(sys.argv)>1 else 0)
atoms = ['0','-0','1','-1','12','1.5','-1.5e3','1e5','1E+2','1e-2','0.0','1.','.5','01','-','+1','1e','1e+','--1','1.2.3',
 'NaN','nan','-NaN','Infinity','-Infinity','infinity','inf','-inf','INF','Inf','iNfInItY','Infinit','NaNx',
 'true','false','null','True','FALSE','nul','tru','nullx','truex',
 '""','"a"','"\\n"','"\\u0041"','"\\u00e9"','"\\ud83d\\ude00"','"\\ud83d"','"\\ude00"','"\\ud83dx"','"\\ud83d\\u0041"','"\\ud83d\\\\"',
 '"\\u12"','"\\x"','"\\/"','"\\\\"','"\\""', '"\\u0000"','"a\\u0000b"', "'s'", "'a\\'b'", '"\xc3\xa9"','"\xe2\x82\xac"','"\xf0\x9f\x98\x80"',
 '"\xc3"','"\xff"','"\xed\xa0\x80"','"\x01"','"\t"','12345678901234567890','-9223372036854775808','9223372036854775808','18446744073709551616',
 '1e400','-1e400','1e-400','123456789012345678901234567890.5']
ws = ['', ' ', '\t', '\n', '\r', '/*c*/', '//c\n', '/**/', '/* * */', '#c\n', '/', '/*', ' \x0c']
def val(d=0):
    r = random.random()
    if d>3 or r<0.5: return random.choice(atoms)
    if r<0.75:
        n=random.randint(0,3)
        sep=random.choice([',',',',',',' ,',',,',''])
        s='['+random.choice(ws)+sep.join(val(d+1)+random.choice(ws) for _ in range(n))
        if random.random()<0.1: s+=','
        return s+(']' if random.random()<0.95 else '')
    n=random.randint(0,3)
    def key(): return random.choice(['"k"','"a"','""','k','"\\u0041"',"'q'",'"k\\u0000x"','1'])
    s='{'+random.choice(ws)+','.join(key()+random.choice(ws)+random.choice([':',':',':','',' :','::'])+random.choice(ws)+val(d+1)+random.choice(ws) for _ in range(n))
    if random.random()<0.1: s+=','
    return s+('}' if random.random()<0.95 else '')
def enc(s):
    b=s.encode('latin-1') if all(ord(c)<256 for c in s) else s.encode()
    return ''.join(chr(c) if 0x20<=c<0x7f and c!=0x5c else '\\x%02x'%c for c in b)
for _ in range(int(sys.argv[2]) if len(sys.argv)>2 else 5000):
    s=random.choice(ws)+val()+random.choice(ws)
    if random.random()<0.1: s+=random.choice(['x',' 1','{}','[]',']','}',','])
    print(enc(s))
