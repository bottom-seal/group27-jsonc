"""Generate single-point mutants of json_tokener.c inside json_tokener_parse_ex
and json_tokener_validate_utf8, build each, run the Role-A style oracle
(one-shot and bytewise results vs the original build), and report kill rates."""
import re, random, subprocess, os, sys, collections
SRC = '/home/user/json-c/json_tokener.c'
B = '/home/user/json-c/build-test'
OBJS = sorted(os.path.join(B, 'CMakeFiles/json-c-static.dir', f) for f in os.listdir(os.path.join(B, 'CMakeFiles/json-c-static.dir')) if f.endswith('.o') and 'json_tokener' not in f)
src = open(SRC).read().split('\n')
start = next(i for i, l in enumerate(src) if l.startswith('struct json_object *json_tokener_parse_ex('))
end = len(src)
OPS = [(r'==', '!='), (r'!=', '=='), (r'<=', '<'), (r'>=', '>'), (r'(?<![<>=!])<(?![<=])', '<='), (r'(?<![<>=!-])>(?![>=])', '>='), (r'&&', '||'), (r'\|\|', '&&'),
       (r'\+\+', '--'), (r'(?<![\w])1(?![\w.x])', '0'), (r'(?<![\w])0(?![\w.x])', '1'), (r'!\(', '('), (r'\bbreak;', ';'), (r'goto redo_char;', 'break;')]
cands = []
for i in range(start, end):
    l = src[i]; s = l.strip()
    if not s or s.startswith(('//', '/*', '*', '#')) or 'MC_DEBUG' in l: continue
    for pat, rep in OPS:
        for m in re.finditer(pat, l):
            cands.append((i, m.start(), m.end(), rep))
R = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
N = int(sys.argv[1]); pick = R.sample(cands, min(N, len(cands)))
orig = open('orig.out', encoding='latin-1').read().split('\n')
res = collections.Counter(); rows = []
for k, (i, a, b, rep) in enumerate(pick):
    m = list(src); m[i] = src[i][:a] + rep + src[i][b:]
    open('m.c', 'w').write('\n'.join(m))
    if subprocess.run(['gcc', '-O1', '-w', '-I/home/user/json-c', '-I' + B, '-c', 'm.c', '-o', 'm.o']).returncode:
        res['nocompile'] += 1; continue
    subprocess.run(['gcc', 'mut_driver.o', 'm.o'] + OBJS + ['-lm', '-o', 'drv_m'], check=True)
    try:
        p = subprocess.run(['./drv_m'], stdin=open('inputs3.txt', 'rb'), capture_output=True, timeout=20)
        if p.returncode != 0: status = 'killed-crash'
        else:
            out = p.stdout.decode('latin-1').split('\n')
            one = bat = stream = 0
            for x, y in zip(orig, out):
                if x == y: continue
                xs, ys = x.split('|'), y.split('|')
                for j in range(0, min(len(xs), len(ys)) - 2, 2):
                    if xs[j] != ys[j]: one = 1
                    if xs[j + 1] != ys[j + 1]: bat = 1
                if len(xs) != len(ys): one = bat = 1
                if xs[-2:] != ys[-2:]: stream = 1
            status = 'killed-both' if one and bat else 'killed-oneshot-only' if one else 'killed-chunked-only' if bat else 'killed-stream-only' if stream else 'survived'
    except subprocess.TimeoutExpired: status = 'killed-timeout'
    res[status] += 1
    rows.append((status, i + 1, src[i].strip()[:70], rep))
for s, v in res.most_common(): print(v, s)
for r in rows:
    if r[0] in ('survived', 'killed-chunked-only'): print(r)
