#!/usr/bin/env python3
"""Ratings-implied "last season" stat line for a player who has none (M4_DESIGN Q8).

BACK drives a batter's hitting from the roster-half stat line (records 0..39), not from the
rating nibbles: a created player or dynasty rookie carried the placeholder line (batters AB 40
and nothing else, pitchers IP 20.0 and nothing else) and hit .000 whatever his ratings said.
fill() writes a full season line whose tools/ratings.py ratings equal the stored nibbles:

- batters (pos code 1..15): 140 G, 500 AB. hit and run exact; power exact except where the
  hits make it impossible (power is at least the BA ladder step, at most the 4 x BA step);
  speed lands on the target or 1 to 2 below it on 375 of 5184 power/hit-run/speed triples.
  Fielding (pos 1..8): range exact unless PO 0 already reaches higher, arm exact.
- pitchers (pos code 0): starter (33 GS) when endurance >= 5, else reliever (50 G).
  Control, velocity and endurance exact on every triple.

Pure integer arithmetic with the same order of operations as tools/m4/statline.h (the C port
used by CREATE.EXE and ROSTERS.EXE); test_statline.py checks the two byte for byte.

    python3 tools/m4/statline.py TEAM.V20     # list the records repair_image() would fill
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import ratings as rt  # noqa: E402

HEADER_LEN = 295
RECORD_LEN = 143
ROSTER_RECORDS = 40

# every season stat byte: the bytes the shipped season halves (records 40..79) hold at zero
SEASON_STAT_BYTES = tuple([23] + list(range(32, 74)) + list(range(77, 94))
                          + list(range(95, 133)))
GB_DEFAULT = (532, 450, 200, 450, 200)   # u16 at 61 63 65 67 69, every shipped batter

AB = 500
G_BAT = 140
AVG = [0, 170, 190, 210, 225, 240, 250, 262, 272, 282, 300, 329, 366]   # per mille, by hit and run
BBK = [0, 90, 90, 85, 80, 80, 90, 95, 95, 97, 102, 111, 112]           # BB per 1000 AB
SOK = [0, 300, 290, 282, 260, 240, 223, 177, 160, 128, 102, 66, 42]    # SO per 1000 AB
SLG_T = [250, 275, 300, 325, 350, 375, 425, 450, 500, 575, 700]        # the power ladder
SLG_AIM = ([0, 230] + [SLG_T[p - 2] + (SLG_T[p - 1] - SLG_T[p - 2]) // 3 for p in range(2, 12)]
           + [720])
HRB = [0, 0, 10, 10, 20, 20, 30, 39, 48, 56, 66, 73, 71]   # percent of extra bases from HR
T3P = [0, 0, 0, 0, 5, 5, 5, 10, 10, 15, 15, 15, 15]        # triples, percent of 2B + 3B, by speed
CSK = [0, 3, 2, 4, 4, 4, 4, 4, 4, 5, 10, 13, 12]           # CS by speed
SPD_T = [1, 2, 4, 6, 9, 15, 20, 25, 90, 150, 240]          # the speed ladder
E_BASE = [0, 10, 11, 15, 19, 25, 7, 7, 7]                   # errors by pos code 1..8 at range 9
SPLIT_P = (335, 219)                                        # pitcher share vs left: LHP, RHP


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _put16(r, o, v):
    r[o] = v & 0xff
    r[o + 1] = (v >> 8) & 0xff


def _split(r, total, frac, o, wide):
    """total into a L/R pair at o: left = total * frac // 1000, right = the rest."""
    left = total * frac // 1000
    if wide:
        _put16(r, o, left)
        _put16(r, o + 2, total - left)
    else:
        r[o] = left
        r[o + 1] = total - left


def _bat_frac(r):
    return 223 if ((r[29] >> 1) & 3) == 0 else 332


def _write_bat(r, ab, h, d, t3, hr, bb, so, frac):
    _split(r, ab, frac, 37, 1)
    _split(r, h, frac, 41, 1)
    _split(r, d, frac, 45, 1)
    _split(r, t3, frac, 49, 0)
    _split(r, hr, frac, 51, 0)
    _split(r, bb, frac, 53, 1)
    _split(r, so, frac, 57, 1)


def _speed_x(r):
    """the raw speed score ratings.speed() ladders"""
    h, d, t3, hr, bb = rt.s2(r, 41), rt.s2(r, 45), rt.b2(r, 49), rt.b2(r, 51), rt.s2(r, 53)
    sb, cs = r[35], r[36]
    x = max(sb - 2 * cs, 0) * 1000
    den = h + bb - d - t3 - hr
    x += den >> 1
    if den:
        x //= den
    y = t3 * 1000
    den2 = d * 30
    y += den2 >> 1
    if den2:
        y //= den2
    return x + y


def _runs(r, h, hr, bb):
    r[32] = min(255, (h + bb) * 40 // 100 + hr // 2)
    r[33] = min(255, h * 35 // 100 + hr)


def _batter(r):
    P = _clamp(r[74] & 15, 1, 12)
    K = _clamp(r[75] & 15, 1, 12)
    S = _clamp(r[29] >> 4, 1, 12)
    frac = _bat_frac(r)
    r[23] = G_BAT
    bb = AB * BBK[K] // 1000
    so = AB * SOK[K] // 1000
    h = AB * AVG[K] // 1000
    # hits: nudge until hit and run is exact
    for _ in range(AB):
        _write_bat(r, AB, h, 0, 0, 0, bb, so, frac)
        k = rt.hit_and_run(r)
        if k < K and h < AB:
            h += 1
        elif k > K and h > 0:
            h -= 1
        else:
            break
    # extra bases: aim inside the power step, split HR / 2B / 3B
    tb = AB * SLG_AIM[P] // 1000
    extra = max(0, tb - h)
    hr = extra * HRB[P] // 300
    rem = extra - 3 * hr
    t3 = rem * T3P[S] // (200 - T3P[S])
    d = rem - 2 * t3
    while d + t3 + hr > h and d >= 3:
        d -= 3
        hr += 1
    while d + t3 + hr > h and d > 0:
        d -= 1
    while d + t3 + hr > h and t3 > 0:
        t3 -= 1
    while d + t3 + hr > h and hr > 0:
        hr -= 1
    _write_bat(r, AB, h, d, t3, hr, bb, so, frac)
    for _ in range(200):
        p = rt.power(r)
        if p < P and d + t3 + hr < h:
            d += 1
        elif p < P and d > 0:
            d -= 1
            hr += 1
        elif p > P and d > 0:
            d -= 1
        elif p > P and hr > 0:
            hr -= 1
        else:
            break
        _write_bat(r, AB, h, d, t3, hr, bb, so, frac)
    # speed: SB - 2CS gives the coarse part, doubles turned into triples the fine part
    cs = CSK[S]
    r[36] = cs
    lo = SPD_T[S - 2] if S >= 2 else 0
    sb = 2 * cs
    r[35] = sb
    if S >= 2:
        for _ in range(255):
            if sb + 1 > 255:
                break
            r[35] = sb + 1
            if rt.speed(r) > S:
                break
            r[35] = sb
            if _speed_x(r) >= lo:
                break
            sb += 1
        r[35] = sb
        for _ in range(h):
            if rt.speed(r) >= S or d == 0:
                break
            d -= 1
            t3 += 1
            _write_bat(r, AB, h, d, t3, hr, bb, so, frac)
            if rt.speed(r) > S:
                d += 1
                t3 -= 1
                _write_bat(r, AB, h, d, t3, hr, bb, so, frac)
                break
        for _ in range(h):
            if rt.power(r) <= P or (d == 0 and t3 == 0):
                break
            if t3 > 0:
                t3 -= 1
                d += 1
            else:
                d -= 1
            _write_bat(r, AB, h, d, t3, hr, bb, so, frac)
        for _ in range(255):
            if rt.speed(r) >= S or sb >= 255:
                break
            r[35] = sb + 1
            if rt.speed(r) > S:
                r[35] = sb
                break
            sb += 1
    _runs(r, h, hr, bb)


def _fielding(r):
    pos = r[31] & 15
    c = rt.POS_CLASS.get(pos)
    g = r[23]
    if c is None or g == 0:
        return
    rg = _clamp(r[94] >> 4, 1, 12)
    am = _clamp(r[94] & 15, 1, 12)
    w = rt.FIELD_W[c]
    e = E_BASE[pos] * (21 - rg) // 12
    r[85] = e
    # arm: A*d - 100E + 25G >= am*50G, A the smallest such
    need = am * 50 * g - 25 * g + 100 * e
    a = max(0, -(-need // w[3]))
    # range: PO*a + A*b - 100E + 50G >= rg*100G
    need = rg * 100 * g - 50 * g + 100 * e - a * w[1]
    po = max(0, -(-need // w[0]))
    _put16(r, 77, po)
    _put16(r, 81, a)
    if pos == 1:
        _put16(r, 90, 220 + 26 * am)     # catcher caught-stealing per mille, the shipped curve


def _pitcher(r):
    C = _clamp(r[134] & 15, 1, 12)
    V = _clamp(r[134] >> 4, 1, 12)
    E = _clamp(r[135] >> 4, 1, 10)
    starter = E >= 5
    g = 33 if starter else 50
    gs = 33 if starter else 0
    cg = min(20, (E - 4) * 2) if starter else 0
    ip10 = (g * (10 * E - cg) + 5) // 10 * 10
    _put16(r, 101, ip10)
    r[23] = g
    r[98] = gs
    r[97] = cg
    r[99] = cg // 3
    o = rt._outs(r)
    x = 14 - C if C >= 2 else 13
    bb = -(-((20 * x - 10) * o) // 999)
    so = o * (20 + 4 * V) // 270
    h = max(0, (527 * o + 540 * so - 40 * o * V - 20 * o) // 1080)
    hr = h * 7 // 100
    frac = SPLIT_P[(r[29] >> 3) & 1]

    def wr():
        _split(r, o + h + bb, frac, 107, 1)
        _split(r, h, frac, 111, 1)
        _split(r, h * 16 // 100, frac, 115, 1)
        _split(r, h * 3 // 100, frac, 119, 0)
        _split(r, bb, frac, 121, 1)
        _split(r, so, frac, 125, 1)
        _split(r, hr, frac, 129, 0)

    wr()
    for _ in range(400):
        v = rt.velocity(r)
        if v < V and h > 0:
            h -= 1
        elif v > V:
            h += 1
        else:
            break
        hr = h * 7 // 100
        wr()
    for _ in range(400):
        c = rt.control(r)
        if c < C and bb > 0:
            bb -= 1
        elif c > C:
            bb += 1
        else:
            break
        wr()
    er = (25 * h + 15 * bb + 50 * hr) // 100
    _put16(r, 103, er)
    _put16(r, 105, er)
    era100 = er * 2700 // max(o, 1)
    diff = 350 - era100
    wp = _clamp(50 + (diff // 5 if diff >= 0 else -(-diff // 5)), 30, 70)   # truncating, as C /
    if starter:
        dec = gs * 6 // 10
        r[95] = dec * wp // 100
        r[96] = dec - r[95]
        r[100] = 0
    else:
        r[95] = 5 * wp // 50
        r[96] = 10 - r[95]
        r[100] = 10
    r[131] = 0
    r[132] = 3
    # his own batting line (he bats in no-DH games): .150, matching the stock pitcher
    # batting nibbles (power 1, hit and run 1)
    _write_bat(r, 60, 9, 1, 0, 0, 3, 20, _bat_frac(r))
    _runs(r, 9, 0, 3)


def fill(rec):
    """Overwrite every season stat byte of a 143 B record (bytearray, in place) with the
    line its rating nibbles imply. Names, bio, ratings and bytes outside
    SEASON_STAT_BYTES are untouched. Pitcher iff pos code (byte 31 low nibble) is 0."""
    for o in SEASON_STAT_BYTES:
        rec[o] = 0
    for i, v in enumerate(GB_DEFAULT):
        _put16(rec, 61 + 2 * i, v)
    if rec[31] & 15 == 0:
        _pitcher(rec)
    else:
        _batter(rec)
        _fielding(rec)
    return rec


def is_placeholder(rec):
    """The C4 / CREATE placeholder line: named, 0 G, and either a pitcher (pos code 0) with
    IP10 200 and no H, BB or SO, or a batter with AB 40 and no H, BB or SO."""
    if rec[0] == 0 or rec[23] != 0:
        return False
    if rec[31] & 15 == 0:
        return (rt.u16(rec, 101) == 200 and rt.s2(rec, 111) == 0 and rt.s2(rec, 121) == 0
                and rt.s2(rec, 125) == 0)
    return (rt.s2(rec, 37) == 40 and rt.s2(rec, 41) == 0 and rt.s2(rec, 53) == 0
            and rt.s2(rec, 57) == 0)


def repair_image(img):
    """fill() every placeholder roster record (records 0..39) of a V20 image (bytearray of
    at least 295 + 40 * 143 B, in place). Season records 40..79 are untouched. Returns the
    list of repaired record indices."""
    done = []
    for i in range(ROSTER_RECORDS):
        o = HEADER_LEN + RECORD_LEN * i
        rec = bytearray(img[o:o + RECORD_LEN])
        if is_placeholder(rec):
            fill(rec)
            img[o:o + RECORD_LEN] = rec
            done.append(i)
    return done


def main(argv):
    for p in argv[1:]:
        img = bytearray(open(p, 'rb').read())
        for i in repair_image(img):
            o = HEADER_LEN + RECORD_LEN * i
            print('%s rec %d %s' % (p, i, bytes(img[o:o + 12]).split(b'\0')[0].decode('latin-1')))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
