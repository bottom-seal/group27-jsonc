"""Exhaustive EP/BVA of JSON_TOKENER_VALIDATE_UTF8 vs Python's strict UTF-8
decoder. Inputs are 1-4 byte sequences inside a string value and a key."""
import subprocess, itertools, collections
B = [0x00, 0x01, 0x22, 0x41, 0x5c, 0x7f, 0x80, 0x81, 0x8f, 0x90, 0x9f, 0xa0, 0xbf, 0xc0, 0xc1, 0xc2, 0xdf, 0xe0, 0xe1, 0xec, 0xed, 0xee, 0xef, 0xf0, 0xf1, 0xf3, 0xf4, 0xf5, 0xf7, 0xf8, 0xfb, 0xfc, 0xfe, 0xff]
seqs = set()
for a in range(256):
    seqs.add(bytes([a]))
    for b in range(256): seqs.add(bytes([a, b]))
for a in range(0xe0, 0x100):
    for b in range(256):
        for c in B: seqs.add(bytes([a, b, c]))
for a in range(0xf0, 0x100):
    for b in B:
        for c in B:
            for d in B: seqs.add(bytes([a, b, c, d]))
seqs = [s for s in seqs if not any(x in s for x in (0x00, 0x22, 0x5c, 0x0a))]
def enc(b): return ''.join(chr(c) if 0x20 <= c < 0x7f and c != 0x5c else '\\x%02x' % c for c in b)
docs = []
for s in seqs:
    docs.append(b'"' + s + b'"'); docs.append(b'{"' + s + b'":1}'); docs.append(b'["' + s + b'x"]')
out = subprocess.run(['./batch', '16'], input='\n'.join(enc(d) for d in docs) + '\n', capture_output=True, text=True).stdout.split('\n')
cats = collections.Counter(); ex = {}
for d, line in zip(docs, out):
    err = line.split('\t')[0]
    try: d.decode('utf-8'); pok = True
    except UnicodeDecodeError: pok = False
    cok = err == '0'
    if cok != pok:
        k = ('jsonc-accepts-invalid' if cok else 'jsonc-rejects-valid', d[:2])
        cats[k] += 1; ex.setdefault(k, (d, line))
print('docs', len(docs), 'mismatches', sum(cats.values()))
for k, v in sorted(cats.items(), key=lambda x: -x[1])[:30]: print(v, k[0], ex[k][0], ex[k][1][:40])
