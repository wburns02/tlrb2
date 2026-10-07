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
