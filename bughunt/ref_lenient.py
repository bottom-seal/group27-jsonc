"""Reference model of json-c's NON-STRICT grammar (as documented / intended):
ws = ' ' \t \n \r and comments /*...*/ (closed by the first */) and //...\n
(a // comment may also end at end of input); values: {..} [..] with optional
trailing comma, "..." or '...' strings, RFC numbers, case-insensitive
true/false/null/nan/infinity, -infinity. After the top-level value, anything
is ignored. Raises Reject on error. Returns Python value (NaN/inf as float)."""
import math
class Reject(Exception): pass
class KnownBug(Exception): pass
EMULATE_STAR_BUG = True
def find_close(t, i):
    # index of the '*' of the closing */, or -1
    if not EMULATE_STAR_BUG:
        return t.find('*/', i)
    # json-c: comment state scans for '*'; comment_end state: '/' closes,
    # anything else (even '*') goes back to comment state and is consumed.
    while True:
        j = t.find('*', i)
        if j < 0 or j + 1 >= len(t): return -1
        if t[j + 1] == '/': return j
        i = j + 2
def U(cp): return chr(cp).encode('utf-8').decode('latin-1')
REPL = '�'
def parse(s):
    p = Parser(s); v = p.value(top=True); return v
class Parser:
    def __init__(s, t): s.t = t; s.i = 0; s.depth = 0
    def peek(s): return s.t[s.i] if s.i < len(s.t) else ''
    def ws(s, top_after=False):
        t = s.t
        while s.i < len(t):
            c = t[s.i]
            if c in ' \t\n\r': s.i += 1
            elif c == '/':
                if t.startswith('/*', s.i):
                    j = find_close(t, s.i + 2)
                    if j < 0:
                        if top_after: s.i = len(t); return
                        raise KnownBug('open comment at EOF')
                    s.i = j + 2
                elif t.startswith('//', s.i):
                    j = t.find('\n', s.i)
                    if j < 0 and not top_after: raise KnownBug('// at EOF')
                    s.i = len(t) if j < 0 else j + 1
                else:
                    if top_after: return
                    raise Reject('bad comment')
            else: return
    def value(s, top=False):
        s.ws()
        c = s.peek()
        if c == '': raise Reject('eof')
        if c == '{': v = s.obj()
        elif c == '[': v = s.arr()
        elif c in '"\'': v = s.string()
        elif c == '-' or c.isdigit(): v = s.number()
        else: v = s.literal()
        if top: s.ws(top_after=True)
        return v
    def lit(s, word, val):
        if s.t[s.i:s.i + len(word)].lower() == word.lower(): s.i += len(word); return val
        raise Reject('literal')
    def literal(s):
        c = s.peek().lower()
        if c == 't': return s.lit('true', True)
        if c == 'f': return s.lit('false', False)
        if c == 'n':
            if s.t[s.i:s.i+2].lower() == 'na': return s.lit('nan', float('nan'))
            return s.lit('null', None)
        if c == 'i': return s.lit('infinity', float('inf'))
        raise Reject('unexpected')
    def number(s):
        t = s.t; j = s.i
        if t.startswith('-', j):
            if t[j+1:j+2].lower() == 'i': s.i += 1; return -s.lit('infinity', float('inf'))
            j += 1
        k = j
        while k < len(t) and t[k].isdigit(): k += 1
        if k == j: raise Reject('num')
        isd = False
        if t[k:k+1] == '.':
            k += 1; m = k
            while k < len(t) and t[k].isdigit(): k += 1
            if k == m: raise Reject('num'); 
            isd = True
        if t[k:k+1] in ('e', 'E'):
            k += 1
            if t[k:k+1] in ('+', '-'): k += 1
            m = k
            while k < len(t) and t[k].isdigit(): k += 1
            if k == m: raise Reject('num')
            isd = True
        txt = t[s.i:k]; s.i = k
        if s.depth > 0 and s.peek() not in (',', ']', '}', '/', ' ', '\t', '\n', '\r', ''):
            raise Reject('num trailing')
        if isd: return float(txt)
        v = int(txt)
        if v > 2**64 - 1: v = 2**64 - 1
        if v < -2**63: v = -2**63
        return v
    def string(s):
        q = s.t[s.i]; s.i += 1; out = []; t = s.t; hi = None
        while True:
            if s.i >= len(t): raise Reject('eof in string')
            c = t[s.i]
            if c == q: s.i += 1; break
            if c == '\\':
                e = t[s.i+1:s.i+2]; s.i += 2
                if e in '"\\/' and e: out.append(e)
                elif e and e in 'bnrtf': out.append({'b':'\b','n':'\n','r':'\r','t':'\t','f':'\f'}[e])
                elif e == 'u':
                    h = t[s.i:s.i+4]
                    if len(h) < 4 or any(x not in '0123456789abcdefABCDEF' for x in h): raise Reject('bad \\u')
                    s.i += 4; cp = int(h, 16)
                    out.append(('u', cp)); continue
                else: raise Reject('bad escape')
            else:
                out.append(c); s.i += 1
        # resolve surrogates the json-c way: pair -> char, lone -> U+FFFD
        res = []; k = 0
        while k < len(out):
            x = out[k]
            if isinstance(x, tuple):
                cp = x[1]
                if 0xD800 <= cp <= 0xDBFF:
                    if k + 1 < len(out) and isinstance(out[k+1], tuple) and 0xDC00 <= out[k+1][1] <= 0xDFFF:
                        res.append(U(0x10000 + ((cp - 0xD800) << 10) + (out[k+1][1] - 0xDC00))); k += 2; continue
                    res.append(U(0xFFFD))
                elif 0xDC00 <= cp <= 0xDFFF: res.append(U(0xFFFD))
                else: res.append(U(cp))
            else: res.append(x)
            k += 1
        return ''.join(res)
    def arr(s):
        s.i += 1; s.depth += 1; out = []
        if s.depth >= 32: raise Reject('depth')
        s.ws()
        if s.peek() == ']': s.i += 1; s.depth -= 1; return out
        while True:
            out.append(s.value()); s.ws()
            c = s.peek()
            if c == ']': s.i += 1; break
            if c != ',': raise Reject('array sep')
            s.i += 1; s.ws()
            if s.peek() == ']': s.i += 1; break
        s.depth -= 1; return out
    def obj(s):
        s.i += 1; s.depth += 1; out = {}
        if s.depth >= 32: raise Reject('depth')
        s.ws()
        if s.peek() == '}': s.i += 1; s.depth -= 1; return out
        while True:
            if s.peek() == '' or s.peek() not in ('"', "'"): raise Reject('key')
            k = s.string(); s.ws()
            if s.peek() != ':': raise Reject('colon')
            s.i += 1
            out[k] = s.value(); s.ws()
            c = s.peek()
            if c == '}': s.i += 1; break
            if c != ',': raise Reject('obj sep')
            s.i += 1; s.ws()
            if s.peek() == '}': s.i += 1; break
        s.depth -= 1; return out
