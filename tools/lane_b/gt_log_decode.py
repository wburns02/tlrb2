#!/usr/bin/env python3
"""Decode the TLRB2 play log and accumulators from a GAME.TMP, ALLTIME.BOX record or raw buffer dump.

usage: gt_log_decode.py FILE [--box] [--selftest]
  GAME.TMP / dump: buffer offset == file offset (7446 B).
  ALLTIME.BOX: 7196 B record = 2 byte header + buffer bytes 0..7193.
"""
import sys

LOG_ROW = 0x12d3        # 18 rows x 108 B
ROW_CNT = 0x12c0        # scoring half-inning row counter (cap 0x12)
RUNS = 0x1beb           # [0] visitor runs, [1] home runs
EMPTY = bytes([0, 0, 0, 255, 255, 255])
PAIR_K = {0: 'AB', 1: 'H', 2: '2B', 3: '3B', 4: 'HR', 5: 'BB', 6: 'SO', 13: 'E'}


def load(path, box=False):
    d = open(path, 'rb').read()
    if box or len(d) == 7196:
        d = d[2:]
    return d


def events(b):
    """Yield (row, slot, dict) for every non-empty event."""
    for r in range(18):
        o = LOG_ROW + r * 108
        for i in range(18):
            e = b[o + i * 6:o + i * 6 + 6]
            if len(e) < 6 or e == EMPTY:
                continue
            run = []
            for x in e[3:6]:
                run.append(None if x == 0xff else (x & 0x3f, x >> 6))
            yield r, i, dict(side=e[0] & 1, pitcher=e[0] >> 1, batter=e[1] >> 2,
                             split=e[1] & 3, result=e[2], runners=run)


def scores(run, base):
    """Runner on base (0..2) scores if idx+adv >= 3 (idx 0 = first)."""
    return run is not None and base + run[1] >= 3


def accum(b):
    out = {}
    for k, name in PAIR_K.items():
        base = 440 + 80 * k
        out[name] = {i: (b[base + 2 * i], b[base + 2 * i + 1]) for i in range(40)}
    out['R'] = {i: b[0xf0 + i] for i in range(40)}
    out['RBI'] = {i: b[0x118 + i] for i in range(40)}
    return out


def dump(b):
    print('rows', b[ROW_CNT], 'runs V', b[RUNS], 'H', b[RUNS + 1])
    for r, i, e in events(b):
        rn = ''.join('-' if x is None else '%d+%d%s' % (x[0], x[1], '*' if scores(x, j) else '') for j, x in enumerate(e['runners']))
        print('r%02d.%02d side%d P%d B%d.%d res%02x %s' % (r, i, e['side'], e['pitcher'], e['batter'], e['split'], e['result'], rn))


def selftest(path):
    b = load(path, True)
    ev = list(events(b))
    cnt = b[ROW_CNT]
    # game 2 box ground truth: visitor 3 runs, home 5 runs (header bytes), 7 scoring rows
    assert (b[RUNS], b[RUNS + 1]) == (3, 5), (b[RUNS], b[RUNS + 1])
    assert cnt == 7, cnt
    per_row = [sum(1 for r, _, _ in ev if r == k) for k in range(cnt)]
    assert all(per_row), per_row
    ac = accum(b)
    # arrays cover the visitor team (CAL) only, summed over all 40 slots (pair sum over split)
    got = {n: sum(sum(ac[n][i]) for i in range(40)) for n in ('AB', 'H', '2B', 'HR', 'BB', 'SO', 'E')}
    want = dict(AB=30, H=4, **{'2B': 1}, HR=2, BB=3, SO=4, E=1)
    assert got == want, (got, want)
    print('selftest ok: rows', cnt, 'events', len(ev))


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if '--selftest' in a:
        selftest(a[0])
    else:
        dump(load(a[0], '--box' in a))
