#!/usr/bin/env python3
"""Sniff the BB play-result record in a running DOSBox-X: DS:ab3a..ab4c (class ab3d, zone ab3a, ab3b fly flag, ab48,
ab49, ab4a fielder idx, ab4b result code) plus DS:3298 (error flag), DS:35eb, DS:af36, and the 3 base-runner slots
buf+0x1c60 (stride 3). Logs every change as a text line.  usage: rc_sniff.py PID OUT.log SECONDS
DS host base is found from the string 'alltime.box\\0ab\\0' at DS:3be2 (every candidate is polled, tagged by index)."""
import re, sys, time, os
pid, out, secs = int(sys.argv[1]), sys.argv[2], float(sys.argv[3])
stems = sys.argv[4] if len(sys.argv) > 4 else 'clasale1clasale3'
mem = os.open(f'/proc/{pid}/mem', os.O_RDONLY)
pat = re.compile(rb'alltime\.box\x00ab\x00', re.I)
cands = []
for l in open(f'/proc/{pid}/maps'):
    m = re.match(r'([0-9a-f]+)-([0-9a-f]+) (rw)', l)
    if not m: continue
    a, b = int(m[1], 16), int(m[2], 16)
    if b - a < 0x10000 or b - a > 0x40000000: continue
    try: d = os.pread(mem, b - a, a)
    except Exception: continue
    for mm in pat.finditer(d): cands.append(a + mm.start() - 0x3be2)
bpat = re.compile(stems.encode() + b'classic\x00', re.S)
bufs = []
for l in open(f'/proc/{pid}/maps'):
    m = re.match(r'([0-9a-f]+)-([0-9a-f]+) (rw)', l)
    if not m: continue
    a, b = int(m[1], 16), int(m[2], 16)
    if b - a < 0x10000 or b - a > 0x40000000: continue
    try: d = os.pread(mem, b - a, a)
    except Exception: continue
    for mm in bpat.finditer(d):
        if mm.start() >= 7169: bufs.append(a + mm.start() - 7169)
print('buf candidates', [hex(c) for c in bufs], flush=True)
print('DS candidates', [hex(c) for c in cands], flush=True)
f = open(out, 'a')
last = {}
t0 = time.time()
def rd(h, off, n): return os.pread(mem, n, h + off)
while time.time() - t0 < secs:
    for i, h in enumerate(cands):
        try:
            rec = rd(h, 0xab3a, 0x13); x = rd(h, 0x3298, 1) + rd(h, 0x35eb, 1) + rd(h, 0xaf36, 1) + rd(h, 0xaf23, 1)
        except OSError: continue
        for j, bh in enumerate(bufs):
            x += os.pread(mem, 9, bh + 0x1c60) + os.pread(mem, 1, bh + 0x1c79)
        key = rec + x
        if last.get(i) != key:
            last[i] = key
            f.write(f'{time.time()-t0:8.2f} c{i} {rec.hex()} {x.hex()}\n'); f.flush()
    time.sleep(0.002)
