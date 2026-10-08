#!/usr/bin/env python3
"""Sample the live GAME.TMP buffer (7446 B) from a running DOSBox-X process every STEP s plus a screenshot.
usage: gt_sample.py PID PREFIX N STEP [HOMESTEM+VISSTEM]   writes /mnt/nvme/tlrb2/s6/PREFIX_KKK.bin (only when changed) and shots PREFIX_KKK.png
The buffer is found by regex: two 8 char lowercase team stems + 'classic\\0' at buffer offset 7169 (home stem first)."""
import os, re, sys, time, subprocess
pid = int(sys.argv[1]); pre = sys.argv[2]; n = int(sys.argv[3]); step = float(sys.argv[4])
pat = re.compile((sys.argv[5] if len(sys.argv) > 5 else 'clasale1clasale3').encode() + b'classic\x00', re.S)
last = None
for k in range(n):
    t0 = time.time()
    mem = open(f'/proc/{pid}/mem', 'rb', 0)
    best = None
    for l in open(f'/proc/{pid}/maps'):
        m = re.match(r'([0-9a-f]+)-([0-9a-f]+) (rw)', l)
        if not m: continue
        a, b = int(m[1], 16), int(m[2], 16)
        if b - a < 0x10000 or b - a > 0x40000000: continue
        try: mem.seek(a); d = mem.read(b - a)
        except Exception: continue
        for mm in pat.finditer(d):
            base = mm.start() - 7169
            if base < 0: continue
            x = d[base:base + 7446]
            if len(x) == 7446 and x[7419:7423] != b'\0\0\0\0' or True:
                if best is None or sum(1 for v in x[4800:6763] if v not in (0, 255)) > best[0]:
                    best = (sum(1 for v in x[4800:6763] if v not in (0, 255)), x)
    if best and best[1] != last:
        last = best[1]
        open(f'/mnt/nvme/tlrb2/s6/{pre}_{k:03d}.bin', 'wb').write(last)
    subprocess.run([os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts', 'xc.sh'), 'shot', f'../s6/{pre}_{k:03d}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(max(0, step - (time.time() - t0)))
