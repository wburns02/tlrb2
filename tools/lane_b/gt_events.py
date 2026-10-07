#!/usr/bin/env python3
"""Correlate play-log events with accumulator changes in a gt_poll.py pickle.
usage: gt_events.py PKL [HOSTADDR_HEX]   (default: series with most changes)
Accumulator layout (decoded session 6 from BB 6000:3407, team t block stride 0x8e8, 40 slots by player id):
  singles (40 B): f0 R, 118 RBI, 140 SH, 168 SB, 190 CS, 3e8 GBcnt, 410 gb_pull, 438 gb_opp, 460 fb_pull, 488 fb_opp,
                  4b0 pinchAB, 4d8 pinchH, 500 pinchHR, 668 PB, 690 RTO_a, 6b8 RTO_b, 6e0 outs, 708 ER, 730 R allowed, 988 BK, 9b0 WP
  pairs (2*id+split, 80 B): 1b8 AB, 208 H, 258 2B, 2a8 3B, 2f8 HR, 348 BB, 398 SO, 528 PO, 578 A, 5c8 E, 618 DP,
                  758 BF, 7a8 pH, 7f8 p2B, 848 p3B, 898 pHR, 8e8 pBB, 938 pSO"""
import sys, pickle
SINGLE = {0xf0: 'R', 0x118: 'RBI', 0x140: 'SH', 0x168: 'SB', 0x190: 'CS', 0x3e8: 'GBc', 0x410: 'gbpull', 0x438: 'gbopp',
          0x460: 'fbpull', 0x488: 'fbopp', 0x4b0: 'pAB', 0x4d8: 'pH', 0x500: 'pHR', 0x668: 'PB', 0x690: 'RTOa',
          0x6b8: 'RTOb', 0x6e0: 'outs', 0x708: 'ER', 0x730: 'RA', 0x988: 'BK', 0x9b0: 'WP'}
PAIR = {0x1b8: 'AB', 0x208: 'H', 0x258: '2B', 0x2a8: '3B', 0x2f8: 'HR', 0x348: 'BB', 0x398: 'SO', 0x528: 'PO', 0x578: 'A',
        0x5c8: 'E', 0x618: 'DP', 0x758: 'BF', 0x7a8: 'pH', 0x7f8: 'p2B', 0x848: 'p3B', 0x898: 'pHR', 0x8e8: 'pBB', 0x938: 'pSO'}
STRIDE = 0x8e8
LOG, ROWCNT = 0x12d3, 0x12c0


def name(off):
    """offset -> (team, label) or None"""
    for t in (0, 1):
        r = off - t * STRIDE
        for b, n in SINGLE.items():
            if b <= r < b + 40: return t, '%s[%d]' % (n, r - b)
        for b, n in PAIR.items():
            if b <= r < b + 80: return t, '%s[%d.%d]' % (n, (r - b) // 2, (r - b) % 2)
    return None


def evs(x):
    out = {}
    for r in range(18):
        for i in range(18):
            o = LOG + r * 108 + i * 6
            e = x[o:o + 6]
            if e not in (bytes([0, 0, 0, 255, 255, 255]), bytes(6), bytes([255] * 6)): out[(r, i)] = e
    return out


if __name__ == '__main__':
    s = pickle.load(open(sys.argv[1], 'rb'))
    k = max(s, key=lambda h: len(s[h])) if len(sys.argv) < 3 else int(sys.argv[2], 16)
    ser = s[k]
    prev = ser[0][1]
    for t, x in ser[1:]:
        ch = [i for i in range(0x1bd0 if False else 0, 0x1c30) if x[i] != prev[i]]
        acc = []
        for i in ch:
            if i < 0xf0 or i >= ROWCNT + 1 and i < 0x1bd0: continue
            n = name(i)
            if n: acc.append('t%d %s %d->%d' % (n[0], n[1], prev[i], x[i]))
        new = [(k2, e.hex()) for k2, e in evs(x).items() if evs(prev).get(k2) != e]
        other = [i for i in ch if i >= 0x1bd0]
        if acc or new:
            print('%7.1f' % t, 'cnt', x[ROWCNT], 'runs', x[0x1beb], x[0x1bec], 'ev', new, '|', ' '.join(acc), '| hdr', ' '.join('%x:%d>%d' % (i, prev[i], x[i]) for i in other))
        prev = x
