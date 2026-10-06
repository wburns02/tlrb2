#!/usr/bin/env python3
"""CLASSIC.MAJ reader/writer (59771 B). Layout: notes/FORMATS.md "MAJ".
usage: maj.py FILE [hdr|stand|sched DAY|runs DAY|setwl LG TEAM W L OUT]"""
import sys

SIZE = 59771
LG = {'AL': 0x21d, 'NL': 0x758c}
DAYS = 244
H = dict(day=0x20a, games=0x20b, first=0x214, last=0x215, lcs_al=0x216, lcs_nl=0x217, ws=0x218,
         lcs_len=0x21a, ws_len=0x21b, allstar=0x21c)
O_DH, O_ORDER, O_W, O_L, O_GB, O_SCHED = 0x297, 0x2b3, 0x2cb, 0x2e3, 0x2fb, 0x3eb
O_RUNS, O_HITS, O_ERR, O_PLAYED = 0x1607, 0x3487, 0x5307, 0x7187


class Maj:
    def __init__(self, data):
        assert len(data) == SIZE, len(data)
        self.d = bytearray(data)

    @classmethod
    def load(cls, p): return cls(open(p, 'rb').read())
    def save(self, p): open(p, 'wb').write(self.d)
    def hdr(self): return {k: self.d[v] for k, v in H.items()}
    def set_hdr(self, k, v): self.d[H[k]] = v

    def _s(self, lg): return LG[lg]
    def wl(self, lg, t):
        s = self._s(lg); return self.d[s + O_W + t], self.d[s + O_L + t]
    def set_wl(self, lg, t, w, l):
        s = self._s(lg); self.d[s + O_W + t] = w; self.d[s + O_L + t] = l
    def gb(self, lg, t):
        s = self._s(lg) + O_GB + 2 * t; return (self.d[s] | self.d[s + 1] << 8) / 10
    def order(self, lg):
        """standings-sorted team slots per division (slot = div*8+i, so west is 8..14); empty before play starts.
        schedule pairs use league-global ids: NL = slot+16"""
        s = self._s(lg) + O_ORDER; r = bytes(self.d[s:s + 24])
        out, cur = [], []
        for b in r:
            if b == 0xff:
                out.append(cur); cur = []
            else: cur.append(b)
        return [x for x in out if x]
    def schedule(self, lg, day):
        s = self._s(lg) + O_SCHED + 16 * day; r = self.d[s:s + 16]
        return [(r[i], r[i + 1]) for i in range(0, 16, 2) if not (r[i] == 0 and r[i + 1] == 0)]
    def results(self, lg, day, table='runs'):
        o = dict(runs=O_RUNS, hits=O_HITS, err=O_ERR)[table]
        s = self._s(lg) + o + 32 * day; return list(self.d[s:s + 16])
    def dh(self, lg): return self.d[self._s(lg) + O_DH]


def main(a):
    m = Maj.load(a[1]); c = a[2] if len(a) > 2 else 'hdr'
    if c == 'hdr': print(m.hdr())
    elif c == 'stand':
        for lg in LG:
            print(lg, m.order(lg))
            for t in range(14): print(' ', t, m.wl(lg, t), m.gb(lg, t))
    elif c == 'sched':
        for lg in LG: print(lg, m.schedule(lg, int(a[3])))
    elif c == 'runs':
        for lg in LG: print(lg, m.results(lg, int(a[3])))
    elif c == 'setwl':
        m.set_wl(a[3], int(a[4]), int(a[5]), int(a[6])); m.save(a[7])


if __name__ == '__main__': main(sys.argv)
