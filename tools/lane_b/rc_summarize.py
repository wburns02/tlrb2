#!/usr/bin/env python3
"""Summarize rc_sniff logs: one row per moment DS:ab4b becomes != 0xff (first sighting of each code per play).
usage: rc_summarize.py LOG... ; prints  code  count  and example (zone ab3a, fly ab3b, class ab3d, ab3e, ab48, ab49, ab4a, err 3298, 35eb, af36, af23)"""
import sys, collections
rows = collections.defaultdict(list)
for fn in sys.argv[1:]:
    prev = None
    for l in open(fn):
        p = l.split()
        if len(p) < 4 or p[1] != 'c1': continue
        rec = bytes.fromhex(p[2]); x = bytes.fromhex(p[3])
        code = rec[0x11]
        if code != 0xff and (prev is None or prev != code or True) and (prev == 0xff or prev is None or prev != code):
            rows[code].append((rec[0], rec[1], rec[3], rec[4], rec[0xe], rec[0xf], rec[0x10], x[0], x[1], x[2], x[3]))
        prev = code
for code in sorted(rows):
    r = rows[code]
    print(f'0x{code:02x} n={len(r):3d}  class/zone/fly/e/48/49/4a/err/35eb/af36/af23 e.g.',
          ' '.join(f'c{a[2]}z{a[0]}f{a[1]}e{a[3]}/{a[4]}{a[5]}/a{a[6]}/E{a[7]}o{a[8]}' for a in collections.Counter(r).most_common(4) for a in [a[0]]))
