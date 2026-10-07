"""Stats-to-ratings formulas used by the Utilities player import path (UTIL 5000:e298 / 5000:e477).

Decoded statically from UTIL 1000:b02a b121 b1cd (pitchers), b29c b3d8 (fielding), b541 b68e b74a b82f (batters),
tables at UTIL ds:7490 (fielding weights) and ds:7a14/7a28 (PO/A per 130 games by position).
All functions take a 143 B player record (bytes) and return the 1..12 rating that would be stored.

    python3 tools/ratings.py TEAMFILE.V20      # compare computed ratings with stored ones
"""
import sys

# ds:7490, 7 classes x 5 words: [PO w, A w, DP w, arm A w, arm DP w]; class by pos nibble (pos-1): C0 1B1 2B2 SS3 3B4 OF5
FIELD_W = [(140, 200, 0, 500, 2500), (67, 250, 300, 200, 340), (270, 100, 100, 50, 450),
           (320, 130, 100, 133, 100), (600, 200, 200, 200, 300), (350, 0, 100, 4000, 3000)]
POS_CLASS = {1: 0, 2: 1, 3: 2, 4: 4, 5: 3, 6: 5, 7: 5, 8: 5}   # pos code -> row (3B and SS rows are swapped vs. code order)
# ds:7a14 PO and ds:7a28 A per 130 games by pos code 0..9 (P C 1B 2B 3B SS LF CF RF DH)
PO130 = [29, 657, 982, 233, 82, 189, 193, 300, 206, 0]
A130 = [60, 56, 83, 317, 218, 352, 4, 5, 8, 0]


def u8(r, o): return r[o]
def u16(r, o): return r[o] | (r[o + 1] << 8)
def s2(r, o): return u16(r, o) + u16(r, o + 2)          # L+R pair of u16
def b2(r, o): return r[o] + r[o + 1]                    # L+R pair of u8


def per_mille(num, den):
    return ((num & 0xffff) * 1000 + (den & 0xffff) // 2) // (den & 0xffff) & 0xffff if den & 0xffff else 0


def ladder(x, thr):
    return 1 + sum(1 for t in thr if x >= t)


def _batter_stats(r):
    ab, h, d, t3, hr, bb, so = s2(r, 37), s2(r, 41), s2(r, 45), b2(r, 49), b2(r, 51), s2(r, 53), s2(r, 57)
    return ab, h, d, t3, hr, bb, so


def power(r):
    ab, h, d, t3, hr, bb, so = _batter_stats(r)
    return ladder(per_mille(h + d + 2 * t3 + 3 * hr, ab), [250, 275, 300, 325, 350, 375, 425, 450, 500, 575, 700])


def hit_and_run(r):
    ab, h, d, t3, hr, bb, so = _batter_stats(r)
    pa = (ab + bb) & 0xffff
    a = (4 * h + 2 * bb) & 0xffff
    c = (3 * so) & 0xffff
    if a <= c and c - a != 0: c = a
    x = (a - c) * 10 // pa if pa else (a - c) * 10
    return 1 + (x != 0) + sum(1 for t in (1, 2, 3, 4, 5, 6, 7, 8, 10, 12) if x > t)


def bunt(r):
    ab, h, d, t3, hr, bb, so = _batter_stats(r)
    s10 = (h - d - t3 - hr) * 10
    sub = min((3 * so + 6 * hr) & 0xffff, s10)
    x = (s10 - sub) * 20
    pa = (ab + bb) & 0xffff
    if pa: x //= pa
    return ladder(x, [4, 8, 12, 16, 19, 21, 23, 27, 31, 35, 40])


def speed(r):
    ab, h, d, t3, hr, bb, so = _batter_stats(r)
    sb, cs = r[35], r[36]
    x = max(sb - 2 * cs, 0) * 1000
    den = h + bb - d - t3 - hr
    x += den >> 1
    if den: x //= den
    y = t3 * 1000
    den2 = d * 30
    y += den2 >> 1
    if den2: y //= den2
    return ladder(x + y, [1, 2, 4, 6, 9, 15, 20, 25, 90, 150, 240])


def _field_class(r):
    pos = r[31] & 15
    return POS_CLASS.get(pos)


def rng(r):
    c = _field_class(r)
    if c is None: return 7
    w = FIELD_W[c]
    g = r[23]
    x = u16(r, 77) * w[0] + u16(r, 81) * w[1] + r[87] * w[2]
    x = max(x - r[85] * 100, 0) + g * 100 // 2
    if g: x //= g * 100
    return max(1, min(12, x))


def arm(r):
    c = _field_class(r)
    if c is None: return 7
    w = FIELD_W[c]
    g = r[23]
    x = u16(r, 81) * w[3] + r[87] * w[4]
    x = max(x - r[85] * 100, 0) + g * 50 // 2
    if g: x //= g * 50
    return max(1, min(12, x))


def _outs(r):
    ip10 = u16(r, 101)
    return (ip10 // 10) * 3 + ip10 % 10


def velocity(r):
    o = _outs(r); h = s2(r, 111); so = s2(r, 125)
    x = o * 507 + so * 540
    x = x - h * 1080 if h * 1080 < x else 0
    x += o * 20
    if o: x //= o * 40
    return 1 if x == 0 else min(x, 12)


def control(r):
    o = _outs(r); bb = s2(r, 121)
    x = bb * 999 + o * 10
    if o: x //= o * 20
    x = max(x, 2)
    return 14 - x if x < 14 else 1


def endurance(r):
    g = r[23]; ip10 = u16(r, 101)
    x = (min(r[97], 20) * g + (ip10 % 10) * 2 + ip10) * 10
    if g: x //= g
    x = (x + 50) // 100
    x = min(x, 10)
    return 1 if x == 0 else x


# ---- salary ("overall rating" 109..9999, stored at record +25 u16) -----------------------------------------------------------
# UTIL 5000:f382 (batters), 5000:f697 (pitchers, stores) and 5000:a5aa (pitchers, returns), class helper 5000:a719, ERA helper 1000:9e5f.
# Called by the import path 5000:e298 after the ratings. Decoded 2026-10-06 (Lane B session 4).
def era100(r):
    """UTIL 1000:9e5f: ERA x100 from IP10 (+101) and ER (+103), thirds-aware, capped 9999."""
    a = u16(r, 101) * 100
    if a % 1000 == 100: a += 0xe9
    if a % 1000 == 200: a += 0x1d3
    n = u16(r, 103) * 900000 + (a >> 1)
    n = (n // a) if a else (9999 if n else 0)
    return min(n, 9999)


def pitcher_class(r):
    """UTIL 5000:a719: 1/4 = starter, 2/3/5/6 = reliever. endurance = hi nibble of +135, G +23, GS +98, IP10 +101."""
    end, g, gs, ip10 = r[135] >> 4, r[23], r[98], u16(r, 101)
    c = 0
    if end > 5 or (g * 33 <= gs * 100 and ip10 > 1000): c = 1
    if end < 3 and c == 0: c = 2
    if end > 1 and gs < g // 2: c += 3
    return c or 3


def salary_pitcher(r):
    w, so, sv, era, inn = r[95], (u16(r, 125) + u16(r, 127)) & 0xffff, r[100], era100(r), u16(r, 101) // 10
    if pitcher_class(r) in (1, 4):
        x = w * 50 + so * 5
        if era < 400: x += (400 - era) * 5
        if w > 20: x += (w - 20) * 100
        if so > 200: x += (so - 200) * 5
        if inn < 180: x = (x & 0xffff) * inn // 180
    else:
        x = sv * 20 + so * 5
        if era < 400: x += (400 - era) * 25 // 10
        if sv > 30: x += (sv - 30) * 10
        if inn < 50: x = (x & 0xffff) * inn // 50
    return max(109, min(9999, (x & 0xffff) * 115 // 100))


def salary_batter(r):
    ab, h, d, t3, hr, bb, so = _batter_stats(r)
    slg = per_mille(h + d + 2 * t3 + 3 * hr, ab)          # 9d04
    obp = per_mille(h + bb, ab + bb)                       # 9d43
    ba = per_mille(h, ab)                                  # 9cc5
    sb, cs, rbi, runs, hrs = r[35], r[36], r[33], r[32], r[51] + r[52]
    pos, rg, am = r[31] & 15, r[94] >> 4, r[94] & 15
    pa = s2(r, 37) + s2(r, 53) & 0xffff
    x = obp + slg + hrs * 30 + rbi * 75 // 10
    if runs > rbi: x += (runs - rbi) * 75 // 10
    if hrs > 30: x += (hrs - 30) * 50
    if sb > cs: x += (sb - cs) * 10
    if sb > 50: x += (sb - 50) * 20
    if ba > 300: x += (ba - 300) * 20
    if pos == 1:
        if am > 7: x += (am - 7) * 100
    elif pos == 3:
        if rg > 8: x += (rg - 8) * 50
        if rg == 12: x -= 50
    elif pos == 4:
        if rg > 8: x += (rg - 8) * 50
        if am > 8: x += (am - 8) * 50
        if rg + am > 22: x -= (rg + am - 22) * 50
    elif pos == 5:
        if rg > 8: x += (rg - 8) * 100
        if am > 8: x += (am - 8) * 100
    elif pos in (6, 8):
        if am > 8: x += (am - 8) * 100
    elif pos == 7:
        if am > 8: x += (am - 8) * 50
        if rg > 8: x += (rg - 8) * 50
        if rg == 12: x -= 50
    x &= 0xffff
    if pa < 0x20d: x = x * pa // 0x23f
    return max(109, min(9999, x))


def salary(r):
    return salary_pitcher(r) if r[31] & 15 == 0 else salary_batter(r)


def hi(r, o): return r[o] >> 4
def lo(r, o): return r[o] & 15


def compare(path):
    sys.path.insert(0, __file__.rsplit('/', 1)[0])
    import v20
    t = v20.Team(open(path, 'rb').read())
    tot = {}
    for p in t.players:
        r = p.raw
        if not r[0]: continue
        if r[31] & 15 == 0:
            pairs = [('velocity', velocity(r), hi(r, 134)), ('control', control(r), lo(r, 134)), ('endurance', endurance(r), hi(r, 135))]
        else:
            pairs = [('speed', speed(r), hi(r, 29)), ('bunt', bunt(r), hi(r, 74)), ('power', power(r), lo(r, 74)),
                     ('hit_run', hit_and_run(r), lo(r, 75)), ('range', rng(r), hi(r, 94)), ('arm', arm(r), lo(r, 94))]
        for k, calc, stored in pairs:
            n, ok, near = tot.get(k, (0, 0, 0))
            tot[k] = (n + 1, ok + (calc == stored), near + (abs(calc - stored) <= 1))
    return tot


if __name__ == '__main__':
    agg = {}
    for f in sys.argv[1:]:
        for k, (n, ok, near) in compare(f).items():
            a = agg.get(k, (0, 0, 0)); agg[k] = (a[0] + n, a[1] + ok, a[2] + near)
    for k, (n, ok, near) in agg.items():
        print(f'{k:10s} n={n:4d} exact={ok:4d} ({100 * ok / n:5.1f}%) within1={100 * near / n:5.1f}%')
