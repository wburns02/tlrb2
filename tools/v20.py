#!/usr/bin/env python3
"""TLRB2 team file (.V20) reader / differ. Layout so far (2026-10-06, from ALLSTAR1.V20):
  11735 B = 295 B team header + 80 player records x 143 B.
  header: +0 team name (12 B, NUL padded), +16 stadium name. rest undecoded.
  player: +0 last name (12 B), +12 first name; rest undecoded (ratings, positions, stats?).
usage: v20.py dump FILE            players with names + raw hex of each record
       v20.py diff OLD NEW         every changed byte as (header|player N, field offset, old -> new)
Decode method: change ONE field in the game's Utilities editor on the work install, save, then diff
against the pre-edit snapshot (scripts/snap.sh). Record each confirmed field below and in notes/FORMATS.md."""
import sys
HDR, REC, N = 295, 143, 80
def where(o):
    return ('header', o) if o < HDR else (f'player {(o - HDR) // REC:2d}', (o - HDR) % REC)
def cstr(b): return b.split(b'\0')[0].decode('latin-1')
def dump(p):
    d = open(p, 'rb').read(); assert len(d) == HDR + REC * N, len(d)
    print(f'team={cstr(d[0:16])!r} stadium={cstr(d[16:32])!r}')
    for i in range(N):
        r = d[HDR + REC * i:HDR + REC * (i + 1)]
        if r[0]: print(f'{i:2d} {cstr(r[12:24]):<12} {cstr(r[0:12]):<12} {r[24:].hex()}')
def diff(a, b):
    x, y = open(a, 'rb').read(), open(b, 'rb').read(); assert len(x) == len(y)
    for o in range(len(x)):
        if x[o] != y[o]:
            w, f = where(o); print(f'{o:#06x} {w:<10} +{f:#05x}  {x[o]:#04x} -> {y[o]:#04x}  ({x[o]} -> {y[o]})')
if __name__ == '__main__':
    {'dump': lambda: dump(sys.argv[2]), 'diff': lambda: diff(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
