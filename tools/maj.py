#!/usr/bin/env python3
"""CLASSIC.MAJ reader/writer (59771 B). Layout: notes/FORMATS.md "MAJ".
usage: maj.py FILE [hdr|names|stand|sched DAY|runs DAY|flags DAY|setwl LG TEAM W L OUT|setname LG SLOT NAME OUT|setabbr LG SLOT ABBR OUT]"""
import sys

SIZE = 59771
LG = {'AL': 0x21d, 'NL': 0x758c}
DAYS = 244
H = dict(day=0x20a, games=0x20b, first=0x214, last=0x215, lcs_al=0x216, lcs_nl=0x217, ws=0x218,
         lcs_len=0x21a, ws_len=0x21b, allstar=0x21c)
O_DH, O_ORDER, O_W, O_L, O_GB, O_SCHED = 0x297, 0x2b3, 0x2cb, 0x2e3, 0x2fb, 0x3eb
O_RUNS, O_HITS, O_ERR, O_PLAYED = 0x1607, 0x3487, 0x5307, 0x7187
# per-league-block tables decoded in lane B session 3 (team names, abbreviations, file stems, per-day flag bytes)
O_LGNAME, O_NAMES, O_ABBR, O_STEM = 0x00, 0x0f, 0x18f, 0x1d7   # 15 B / 16 slots x 16 B (name14 + code2) / 16 x 3 B / 16 x 8 B
O_DHFLAG, O_CANCEL, O_NIGHT = 0x132b, 0x141f, 0x1513            # 244 B each, one byte per day, bit 0x80>>g = game slot g


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
    def set_dh(self, lg, v): self.d[self._s(lg) + O_DH] = v
    # -- names (slot = division*8 + i, slot 15 = all-star team) --
    @staticmethod
    def _cs(b): return bytes(b).split(b'\0')[0].decode('latin-1')
    def league_name(self, lg): s = self._s(lg) + O_LGNAME; return self._cs(self.d[s:s + 15])
    def set_league_name(self, lg, name):
        s = self._s(lg) + O_LGNAME; self.d[s:s + 15] = name.encode('latin-1')[:14].ljust(15, b'\0')
    def team_name(self, lg, slot): s = self._s(lg) + O_NAMES + 16 * slot; return self._cs(self.d[s:s + 14])
    def set_team_name(self, lg, slot, name):
        s = self._s(lg) + O_NAMES + 16 * slot; self.d[s:s + 14] = name.encode('latin-1')[:13].ljust(14, b'\0')
    def team_code(self, lg, slot): s = self._s(lg) + O_NAMES + 16 * slot + 14; return bytes(self.d[s:s + 2]).decode('latin-1')
    def abbr(self, lg, slot): s = self._s(lg) + O_ABBR + 3 * slot; return self._cs(self.d[s:s + 3])
    def set_abbr(self, lg, slot, a):
        s = self._s(lg) + O_ABBR + 3 * slot; self.d[s:s + 3] = a.encode('latin-1')[:3].ljust(3, b'\0')
    def stem(self, lg, slot): s = self._s(lg) + O_STEM + 8 * slot; return bytes(self.d[s:s + 8]).decode('latin-1').rstrip('\0')
    def counts(self, lg): s = self._s(lg); return self.d[s + 0x298], self.d[s + 0x299]
    def leagues_divisions(self): return self.d[0x20c], self.d[0x20d]
    # -- per-day flags: bit 0x80>>g set = game slot g --
    def flags(self, lg, day):
        s = self._s(lg) + day
        return dict(doubleheader=self.d[s + O_DHFLAG], cancelled=self.d[s + O_CANCEL], night=self.d[s + O_NIGHT])
    def played(self, lg, day):
        """(game1 mask, game2 mask) of the u16 at +0x7187+2*day; game2 = second game of a doubleheader"""
        s = self._s(lg) + O_PLAYED + 2 * day; return self.d[s], self.d[s + 1]
    def results2(self, lg, day, table='runs'):
        """second game of a doubleheader: second 16 B half of the 32 B day row"""
        o = dict(runs=O_RUNS, hits=O_HITS, err=O_ERR)[table]
        s = self._s(lg) + o + 32 * day + 16; return list(self.d[s:s + 16])


def main(a):
    m = Maj.load(a[1]); c = a[2] if len(a) > 2 else 'hdr'
    if c == 'hdr': print(m.hdr())
    elif c == 'names':
        print('leagues/divisions', m.leagues_divisions())
        for lg in LG:
            print(lg, repr(m.league_name(lg)), 'dh', m.dh(lg), 'counts', m.counts(lg))
            for sl in range(16):
                if m.team_name(lg, sl): print(' ', sl, repr(m.team_name(lg, sl)), m.abbr(lg, sl), m.team_code(lg, sl), m.stem(lg, sl))
    elif c == 'flags':
        for lg in LG: print(lg, m.flags(lg, int(a[3])), 'played', m.played(lg, int(a[3])), 'game2 runs', m.results2(lg, int(a[3])))
    elif c == 'setname': m.set_team_name(a[3], int(a[4]), a[5]); m.save(a[6])
    elif c == 'setabbr': m.set_abbr(a[3], int(a[4]), a[5]); m.save(a[6])
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
