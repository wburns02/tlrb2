"""PKWARE Data Compression Library 'explode' (blast), pure Python. explode(data) -> (bytes, consumed)."""

_LITLEN = [11,124,8,7,28,7,188,13,76,4,10,8,12,10,12,10,8,23,8,9,7,6,7,8,7,6,55,8,23,24,12,11,7,9,11,12,6,7,22,5,7,24,6,11,9,6,7,22,7,11,38,7,9,8,25,11,8,11,9,12,8,12,5,38,5,38,5,11,7,5,6,21,6,10,53,8,7,24,10,27,44,253,253,253,252,252,252,13,12,45,12,45,12,61,12,45,44,173]
_LENLEN = [2,35,36,53,38,23]
_DISTLEN = [2,20,53,230,247,151,248]
_BASE = [3,2,4,5,6,7,8,9,10,12,16,24,40,72,136,264]
_EXTRA = [0,0,0,0,0,0,0,0,1,2,3,4,5,6,7,8]

class _Huff:
    def __init__(self, rep):
        self.count=[0]*16; self.symbol=[]
        lens=[]
        for b in rep:
            n=(b&15); r=(b>>4)+1
            lens += [n]*r
        for l in lens: self.count[l]+=1
        self.count[0]=0
        offs=[0]*16
        for i in range(1,15): offs[i+1]=offs[i]+self.count[i]
        self.symbol=[0]*len(lens)
        for s,l in enumerate(lens):
            if l: self.symbol[offs[l]]=s; offs[l]+=1

class _St:
    def __init__(s,data): s.d=data; s.p=0; s.bb=0; s.bc=0
    def bits(s,need):
        v=s.bb
        while s.bc<need:
            if s.p>=len(s.d): raise EOFError
            v|=s.d[s.p]<<s.bc; s.p+=1; s.bc+=8
        s.bb=v>>need; s.bc-=need
        return v&((1<<need)-1)
    def decode(s,h):
        code=first=index=0
        bb=s.bb; bc=s.bc
        for l in range(1,16):
            # codes are stored bit-inverted
            if bc==0:
                if s.p>=len(s.d): raise EOFError
                bb=s.d[s.p]; s.p+=1; bc=8
            code |= (bb&1)^1; bb>>=1; bc-=1
            c=h.count[l]
            if code-c<first:
                s.bb=bb; s.bc=bc
                return h.symbol[index+(code-first)]
            index+=c; first+=c; first<<=1; code<<=1
        raise ValueError('bad code')

_lit=_Huff(_LITLEN); _len=_Huff(_LENLEN); _dist=_Huff(_DISTLEN)

def explode(data, start=0):
    s=_St(data); s.p=start
    lit=s.bits(8); dict_=s.bits(8)
    if lit>1 or not 4<=dict_<=6: raise ValueError('bad DCL header %d %d'%(lit,dict_))
    out=bytearray()
    try:
        while True:
            if s.bits(1):
                sym=s.decode(_len)
                ln=_BASE[sym]+s.bits(_EXTRA[sym])
                if ln==519: break
                sh = 2 if ln==2 else dict_
                dist=s.decode(_dist)<<sh
                dist|=s.bits(sh)
                dist+=1
                if dist>len(out): raise ValueError('dist too far')
                for _ in range(ln): out.append(out[-dist])
            else:
                out.append(s.decode(_lit) if lit else s.bits(8))
    except EOFError:
        pass
    return bytes(out), s.p

# ---------------------------------------------------------------------------
# Encoder: implode(data, dict_bits) -> DCL stream readable by explode().

def _stream_codes(h):
    """sym -> (value, nbits): stream bits LSB first, each bit = code bit ^ 1, code MSB first."""
    table = {}
    code = index = 0
    for l in range(1, 16):
        c = h.count[l]
        for k in range(c):
            sym = h.symbol[index + k]
            v = 0
            for i in range(l):
                bit = (((code + k) >> (l - 1 - i)) & 1) ^ 1
                v |= bit << i
            table[sym] = (v, l)
        index += c
        code = (code + c) << 1
    return table

def _len_symbol(L):
    for sym in range(16):
        if _BASE[sym] <= L < _BASE[sym] + (1 << _EXTRA[sym]):
            return sym
    raise ValueError('no length symbol for %d' % L)

_LEN_CODES = _stream_codes(_len)
_DIST_CODES = _stream_codes(_dist)
_LEN_SYM = [None, None] + [_len_symbol(L) for L in range(2, 520)]

def implode(data, dict_bits=6):
    if dict_bits not in (4, 5, 6):
        raise ValueError('dict_bits must be 4, 5 or 6')
    data = bytes(data)
    n = len(data)
    maxd = 64 << dict_bits
    out = bytearray([0, dict_bits])
    acc = 0
    nacc = 0
    head = {}
    prev = [-1] * n

    def put(v, nb):
        nonlocal acc, nacc
        acc |= v << nacc
        nacc += nb
        while nacc >= 8:
            out.append(acc & 255)
            acc >>= 8
            nacc -= 8

    i = 0
    while i < n:
        best_len = 0
        best_d = 0
        if i + 2 < n:
            key = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
            cand = head.get(key, -1)
            maxlen = min(518, n - i)
            depth = 0
            lo = i - maxd
            while cand >= 0 and cand >= lo and depth < 64:
                if best_len == 0 or (best_len < maxlen and data[cand + best_len] == data[i + best_len]):
                    k = 0
                    while k < maxlen and data[cand + k] == data[i + k]:
                        k += 1
                    if k > best_len:
                        best_len = k
                        best_d = i - cand
                        if k == maxlen:
                            break
                cand = prev[cand]
                depth += 1
        if best_len >= 3:
            L = best_len
            sym = _LEN_SYM[L]
            put(1, 1)
            v, nb = _LEN_CODES[sym]
            put(v, nb)
            put(L - _BASE[sym], _EXTRA[sym])
            d = best_d - 1
            v, nb = _DIST_CODES[d >> dict_bits]
            put(v, nb)
            put(d & ((1 << dict_bits) - 1), dict_bits)
            step = L
        else:
            put(0, 1)
            put(data[i], 8)
            step = 1
        for j in range(i, min(i + step, n - 2)):
            key = (data[j] << 16) | (data[j + 1] << 8) | data[j + 2]
            prev[j] = head.get(key, -1)
            head[key] = j
        i += step

    # End marker: length 519 (sym 15, extra 255), no distance.
    put(1, 1)
    v, nb = _LEN_CODES[15]
    put(v, nb)
    put(255, _EXTRA[15])
    if nacc:
        out.append(acc & 255)
    return bytes(out)
