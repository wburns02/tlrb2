#!/usr/bin/env python3
"""Sum per-field V20 deltas (before vs after one season game) per team and print them next to the box score.
usage: gt_merge_check.py BEFORE.V20 AFTER.V20   (records 40..79 hold the season stats; 0..39 are the twin/bio half)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import v20
HDR, REC = v20.HDR, v20.REC
U8 = {'R': 0x20, 'RBI': 0x21, 'SH': 0x22, 'SB': 0x23, 'CS': 0x24, 'G': 0x17, 'PB': 0x59, 'W': 0x5f, 'L': 0x60, 'CG': 0x61,
      'GS': 0x62, 'SHO': 0x63, 'SV': 0x64, 'BK': 0x83, 'WP': 0x84, 'cnt85': 0x85, 'E': 0x55, 'DP': 0x57}
U16 = {'AB': 0x25, 'H': 0x29, '2B': 0x2d, 'BB': 0x35, 'SO': 0x39, 'PO': 0x4d, 'A': 0x51, 'RTOa': 0x5a, 'RTOb': 0x5c,
       'IP10': 0x65, 'ER': 0x67, 'RA': 0x69, 'BF': 0x6b, 'pH': 0x6f, 'p2B': 0x73, 'pBB': 0x79, 'pSO': 0x7d}
U8P = {'3B': 0x31, 'HR': 0x33, 'p3B': 0x77, 'pHR': 0x81, 'E': 0x55, 'DP': 0x57}
def rec(d, i): return d[HDR + REC * i:HDR + REC * (i + 1)]
a, b = open(sys.argv[1], 'rb').read(), open(sys.argv[2], 'rb').read()
tot = {}
for i in range(40, 80):
    x, y = rec(a, i), rec(b, i)
    for n, o in U8.items(): tot[n] = tot.get(n, 0) + y[o] - x[o]
    for n, o in U16.items():
        for s in (0, 2):
            tot[n] = tot.get(n, 0) + (y[o + s] | y[o + s + 1] << 8) - (x[o + s] | x[o + s + 1] << 8) if n not in ('RTOa', 'RTOb', 'IP10', 'ER', 'RA', 'PO', 'A') or s == 0 else tot.get(n, 0)
    for n, o in U8P.items():
        for s in (0, 1): tot[n + '_sum'] = tot.get(n + '_sum', 0) + y[o + s] - x[o + s]
    for n, o in (('3B', 0x31), ('HR', 0x33), ('p3B', 0x77), ('pHR', 0x81)):
        tot[n] = tot.get(n, 0) + (y[o] - x[o]) + (y[o + 1] - x[o + 1])
    tot['PO'] = tot.get('PO', 0) + sum((y[o] | y[o + 1] << 8) - (x[o] | x[o + 1] << 8) for o in (0x4d, 0x4f))
    tot['A'] = tot.get('A', 0) + sum((y[o] | y[o + 1] << 8) - (x[o] | x[o + 1] << 8) for o in (0x51, 0x53))
print({k: v for k, v in sorted(tot.items()) if v and not k.endswith('_sum')})
