#!/usr/bin/env python3
"""Fast poller of the live BB game buffer (7446 B, same layout as GAME.TMP) in a running DOSBox-X.
usage: gt_poll.py PID OUT.pkl SECONDS [HOMESTEM+VISSTEM] [HZ]
Finds the buffer once (regex stems+'classic\\0' at buffer+7169), then polls it and stores [(t, bytes)] for every change.
Load with pickle. Also exposes find_base(pid, stems)."""
import re, sys, time, pickle


def find_base(pid, stems):
    pat = re.compile(stems.encode() + b'classic\x00', re.S)
    mem = open(f'/proc/{pid}/mem', 'rb', 0)
    hits = []
    for l in open(f'/proc/{pid}/maps'):
        m = re.match(r'([0-9a-f]+)-([0-9a-f]+) (rw)', l)
        if not m: continue
        a, b = int(m[1], 16), int(m[2], 16)
        if b - a < 0x10000 or b - a > 0x40000000: continue
        try: mem.seek(a); d = mem.read(b - a)
        except Exception: continue
        for mm in pat.finditer(d):
            if mm.start() >= 7169: hits.append(a + mm.start() - 7169)
    return hits


if __name__ == '__main__':
    pid = int(sys.argv[1]); out = sys.argv[2]; secs = float(sys.argv[3])
    stems = sys.argv[4] if len(sys.argv) > 4 else 'clasale1clasale3'
    hz = float(sys.argv[5]) if len(sys.argv) > 5 else 10
    hits = find_base(pid, stems)
    print('hits', [hex(h) for h in hits], flush=True)
    mem = open(f'/proc/{pid}/mem', 'rb', 0)
    # choose the hit that changes during play: poll all hits, keep every hit's series
    series = {h: [] for h in hits}; last = {h: None for h in hits}
    t0 = time.time()
    while time.time() - t0 < secs:
        for h in hits:
            mem.seek(h); x = mem.read(7446)
            if x != last[h]:
                last[h] = x; series[h].append((time.time() - t0, x))
        time.sleep(1.0 / hz)
        if int((time.time() - t0)) % 30 == 0:
            pickle.dump(series, open(out, 'wb'))
    pickle.dump(series, open(out, 'wb'))
    print('done', {hex(h): len(v) for h, v in series.items()})
