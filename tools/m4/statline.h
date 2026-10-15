/* STATLINE: C port of tools/m4/statline.py (the ratings-implied last season stat line,
 * M4 Q8) with the tools/ratings.py functions it calls. Included by create.c (CREATE),
 * rosters.c (ROSTERS, defines STATLINE_REPAIR first) and statline_c/sl_host.c.
 * Every function is static. All arithmetic is long, which is 32 bits on the host and
 * in the 16-bit DOS build, so no intermediate can wrap. Byte-identical to statline.py
 * for every 143 B record (test_statline.py checks it).
 */
#ifndef SL_STATLINE_H
#define SL_STATLINE_H

#include <stdint.h>

#define SL_RECORD_LEN 143
#define SL_HEADER_LEN 295
#define SL_ROSTER_RECORDS 40

#define SL_AB 500L
#define SL_G_BAT 140L

/* the stat bytes fill() zeroes (statline.SEASON_STAT_BYTES: 23, 32..73, 77..93, 95..132) */
static const uint8_t SL_SEASON_OFFS[98] = {
    23, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46,
    47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62,
    63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 77, 78, 79, 80, 81,
    82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 95, 96, 97, 98,
    99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114,
    115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130,
    131, 132 };

static const long SL_GB_DEFAULT[5] = { 532, 450, 200, 450, 200 };
static const long SL_AVG[13] = { 0, 170, 190, 210, 225, 240, 250, 262, 272, 282, 300, 329, 366 };
static const long SL_BBK[13] = { 0, 90, 90, 85, 80, 80, 90, 95, 95, 97, 102, 111, 112 };
static const long SL_SOK[13] = { 0, 300, 290, 282, 260, 240, 223, 177, 160, 128, 102, 66, 42 };
static const long SL_SLG_T[11] = { 250, 275, 300, 325, 350, 375, 425, 450, 500, 575, 700 };
static const long SL_SLG_AIM[13] = { 0, 230, 258, 283, 308, 333, 358, 391, 433, 466, 525, 616, 720 };
static const long SL_HRB[13] = { 0, 0, 10, 10, 20, 20, 30, 39, 48, 56, 66, 73, 71 };
static const long SL_T3P[13] = { 0, 0, 0, 0, 5, 5, 5, 10, 10, 15, 15, 15, 15 };
static const long SL_CSK[13] = { 0, 3, 2, 4, 4, 4, 4, 4, 4, 5, 10, 13, 12 };
static const long SL_SPD_T[11] = { 1, 2, 4, 6, 9, 15, 20, 25, 90, 150, 240 };
static const long SL_E_BASE[9] = { 0, 10, 11, 15, 19, 25, 7, 7, 7 };
static const long SL_SPLIT_P[2] = { 335, 219 };
static const long SL_HR_T[10] = { 1, 2, 3, 4, 5, 6, 7, 8, 10, 12 };

/* ratings.FIELD_W: per class [PO, A, DP, arm A, arm DP] */
static const long SL_FIELD_W[6][5] = {
    { 140, 200, 0, 500, 2500 }, { 67, 250, 300, 200, 340 }, { 270, 100, 100, 50, 450 },
    { 320, 130, 100, 133, 100 }, { 600, 200, 200, 200, 300 }, { 350, 0, 100, 4000, 3000 } };
/* ratings.POS_CLASS by pos code 0..8 (-1 when the code has no class) */
static const int SL_POS_CLASS[9] = { -1, 0, 1, 2, 4, 3, 5, 5, 5 };

/* ---------------- helpers (statline._clamp, _put16, _split) ---------------- */

static long sl_clamp(long v, long lo, long hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

static long sl_min(long a, long b)
{
    return a < b ? a : b;
}

static long sl_max(long a, long b)
{
    return a > b ? a : b;
}

/* ratings.u16, s2 (L+R pair of u16), b2 (L+R pair of u8) */
static long sl_u16(const uint8_t *r, int o)
{
    return (long)r[o] | ((long)r[o + 1] << 8);
}

static long sl_s2(const uint8_t *r, int o)
{
    return sl_u16(r, o) + sl_u16(r, o + 2);
}

static long sl_b2(const uint8_t *r, int o)
{
    return (long)r[o] + (long)r[o + 1];
}

static void sl_put16(uint8_t *r, int o, long v)
{
    r[o] = (uint8_t)(v & 0xff);
    r[o + 1] = (uint8_t)((v >> 8) & 0xff);
}

/* total into a L/R pair at o: left = total * frac // 1000, right = the rest */
static void sl_split(uint8_t *r, long total, long frac, int o, int wide)
{
    long left = total * frac / 1000;
    if (wide) {
        sl_put16(r, o, left);
        sl_put16(r, o + 2, total - left);
    } else {
        r[o] = (uint8_t)left;
        r[o + 1] = (uint8_t)(total - left);
    }
}

static long sl_bat_frac(const uint8_t *r)
{
    return ((r[29] >> 1) & 3) == 0 ? 223L : 332L;
}

static void sl_write_bat(uint8_t *r, long ab, long h, long d, long t3, long hr, long bb,
                         long so, long frac)
{
    sl_split(r, ab, frac, 37, 1);
    sl_split(r, h, frac, 41, 1);
    sl_split(r, d, frac, 45, 1);
    sl_split(r, t3, frac, 49, 0);
    sl_split(r, hr, frac, 51, 0);
    sl_split(r, bb, frac, 53, 1);
    sl_split(r, so, frac, 57, 1);
}

/* ---------------- ratings.py: the rating functions the fill loops call ---------------- */

/* ratings.per_mille: (num * 1000 + den // 2) // den, both masked to 16 bits; 0 when den is 0 */
static long sl_per_mille(long num, long den)
{
    long n = num & 0xffffL, d = den & 0xffffL;
    if (!d)
        return 0;
    return ((n * 1000 + d / 2) / d) & 0xffffL;
}

/* ratings.ladder: 1 + the number of thresholds at or below x */
static long sl_ladder(long x, const long *thr, int n)
{
    long k = 1;
    int i;
    for (i = 0; i < n; i++)
        if (x >= thr[i])
            k++;
    return k;
}

/* ratings.power */
static long sl_power(const uint8_t *r)
{
    long ab = sl_s2(r, 37), h = sl_s2(r, 41), d = sl_s2(r, 45);
    long t3 = sl_b2(r, 49), hr = sl_b2(r, 51);
    return sl_ladder(sl_per_mille(h + d + 2 * t3 + 3 * hr, ab), SL_SLG_T, 11);
}

/* ratings.hit_and_run: masks as in ratings.py (a, c, pa are u16 sums) */
static long sl_hit_and_run(const uint8_t *r)
{
    long bb = sl_s2(r, 53), so = sl_s2(r, 57), h = sl_s2(r, 41), ab = sl_s2(r, 37);
    long pa = (ab + bb) & 0xffffL;
    long a = (4 * h + 2 * bb) & 0xffffL;
    long c = (3 * so) & 0xffffL;
    long x, k = 0;
    int i;
    if (a <= c && c - a != 0)
        c = a;
    /* a - c is never negative here (c was lowered to a whenever a < c) */
    x = pa ? (a - c) * 10 / pa : (a - c) * 10;
    for (i = 0; i < 10; i++)
        if (x > SL_HR_T[i])
            k++;
    return 1 + (x != 0) + k;
}

/* ratings.speed before the ladder: the raw score statline._speed_x returns. Every
 * divisor here is nonnegative (d + t3 + hr never exceeds h while fill runs), so the
 * shifts and the division truncate exactly as ratings.py */
static long sl_speed_x(const uint8_t *r)
{
    long h = sl_s2(r, 41), d = sl_s2(r, 45), t3 = sl_b2(r, 49), hr = sl_b2(r, 51);
    long bb = sl_s2(r, 53);
    long sb = r[35], cs = r[36];
    long x = sl_max(sb - 2 * cs, 0) * 1000;
    long den = h + bb - d - t3 - hr;
    long y = t3 * 1000;
    long den2 = d * 30;
    x += den / 2;
    if (den)
        x /= den;
    y += den2 / 2;
    if (den2)
        y /= den2;
    return x + y;
}

/* ratings.speed */
static long sl_speed(const uint8_t *r)
{
    return sl_ladder(sl_speed_x(r), SL_SPD_T, 11);
}

/* ratings._outs: outs from IP10 (+101) */
static long sl_outs(const uint8_t *r)
{
    long ip10 = sl_u16(r, 101);
    return (ip10 / 10) * 3 + ip10 % 10;
}

/* ratings.velocity */
static long sl_velocity(const uint8_t *r)
{
    long o = sl_outs(r), h = sl_s2(r, 111), so = sl_s2(r, 125);
    long x = o * 507 + so * 540;
    x = h * 1080 < x ? x - h * 1080 : 0;
    x += o * 20;
    if (o)
        x /= o * 40;
    if (x == 0)
        return 1;
    return sl_min(x, 12);
}

/* ratings.control */
static long sl_control(const uint8_t *r)
{
    long o = sl_outs(r), bb = sl_s2(r, 121);
    long x = bb * 999 + o * 10;
    if (o)
        x /= o * 20;
    x = sl_max(x, 2);
    return x < 14 ? 14 - x : 1;
}

/* ---------------- statline._runs, _fielding, _batter, _pitcher ---------------- */

static void sl_runs(uint8_t *r, long h, long hr, long bb)
{
    r[32] = (uint8_t)sl_min((h + bb) * 40 / 100 + hr / 2, 255);
    r[33] = (uint8_t)sl_min(h * 35 / 100 + hr, 255);
}

/* pos code -> FIELD_W class, -1 when the code has none */
static int sl_pos_class(long pos)
{
    return (pos >= 0 && pos <= 8) ? SL_POS_CLASS[pos] : -1;
}

static void sl_fielding(uint8_t *r)
{
    long pos = r[31] & 15;
    int c = sl_pos_class(pos);
    long g = r[23];
    long rg, am, e, need, a, po;
    const long *w;
    if (c < 0 || g == 0)
        return;
    rg = sl_clamp(r[94] >> 4, 1, 12);
    am = sl_clamp(r[94] & 15, 1, 12);
    w = SL_FIELD_W[c];
    e = SL_E_BASE[pos] * (21 - rg) / 12;
    r[85] = (uint8_t)e;
    /* arm: A*d - 100E + 25G >= am*50G, A the smallest such (ceil, 0 when need <= 0) */
    need = am * 50 * g - 25 * g + 100 * e;
    a = need > 0 ? (need + w[3] - 1) / w[3] : 0;
    /* range: PO*a + A*b - 100E + 50G >= rg*100G */
    need = rg * 100 * g - 50 * g + 100 * e - a * w[1];
    po = need > 0 ? (need + w[0] - 1) / w[0] : 0;
    sl_put16(r, 77, po);
    sl_put16(r, 81, a);
    if (pos == 1)
        sl_put16(r, 90, 220 + 26 * am);     /* catcher caught-stealing per mille */
}

static void sl_batter(uint8_t *r)
{
    long P = sl_clamp(r[74] & 15, 1, 12);
    long K = sl_clamp(r[75] & 15, 1, 12);
    long S = sl_clamp(r[29] >> 4, 1, 12);
    long frac = sl_bat_frac(r);
    long bb, so, h, hk, tb, extra, hr, rem, t3, d, cs, lo, sb, p;
    int i;
    r[23] = (uint8_t)SL_G_BAT;
    bb = SL_AB * SL_BBK[K] / 1000;
    so = SL_AB * SL_SOK[K] / 1000;
    h = SL_AB * SL_AVG[K] / 1000;
    /* hits: nudge until hit and run is exact */
    for (i = 0; i < SL_AB; i++) {
        sl_write_bat(r, SL_AB, h, 0, 0, 0, bb, so, frac);
        hk = sl_hit_and_run(r);
        if (hk < K && h < SL_AB)
            h++;
        else if (hk > K && h > 0)
            h--;
        else
            break;
    }
    /* extra bases: aim inside the power step, split HR / 2B / 3B */
    tb = SL_AB * SL_SLG_AIM[P] / 1000;
    extra = sl_max(0, tb - h);
    hr = extra * SL_HRB[P] / 300;
    rem = extra - 3 * hr;
    t3 = rem * SL_T3P[S] / (200 - SL_T3P[S]);
    d = rem - 2 * t3;
    while (d + t3 + hr > h && d >= 3) {
        d -= 3;
        hr++;
    }
    while (d + t3 + hr > h && d > 0)
        d--;
    while (d + t3 + hr > h && t3 > 0)
        t3--;
    while (d + t3 + hr > h && hr > 0)
        hr--;
    sl_write_bat(r, SL_AB, h, d, t3, hr, bb, so, frac);
    for (i = 0; i < 200; i++) {
        p = sl_power(r);
        if (p < P && d + t3 + hr < h)
            d++;
        else if (p < P && d > 0) {
            d--;
            hr++;
        } else if (p > P && d > 0)
            d--;
        else if (p > P && hr > 0)
            hr--;
        else
            break;
        sl_write_bat(r, SL_AB, h, d, t3, hr, bb, so, frac);
    }
    /* speed: SB - 2CS gives the coarse part, doubles turned into triples the fine part */
    cs = SL_CSK[S];
    r[36] = (uint8_t)cs;
    lo = S >= 2 ? SL_SPD_T[S - 2] : 0;
    sb = 2 * cs;
    r[35] = (uint8_t)sb;
    if (S >= 2) {
        for (i = 0; i < 255; i++) {
            if (sb + 1 > 255)
                break;
            r[35] = (uint8_t)(sb + 1);
            if (sl_speed(r) > S)
                break;
            r[35] = (uint8_t)sb;
            if (sl_speed_x(r) >= lo)
                break;
            sb++;
        }
        r[35] = (uint8_t)sb;
        for (i = 0; i < h; i++) {
            if (sl_speed(r) >= S || d == 0)
                break;
            d--;
            t3++;
            sl_write_bat(r, SL_AB, h, d, t3, hr, bb, so, frac);
            if (sl_speed(r) > S) {
                d++;
                t3--;
                sl_write_bat(r, SL_AB, h, d, t3, hr, bb, so, frac);
                break;
            }
        }
        for (i = 0; i < h; i++) {
            if (sl_power(r) <= P || (d == 0 && t3 == 0))
                break;
            if (t3 > 0) {
                t3--;
                d++;
            } else
                d--;
            sl_write_bat(r, SL_AB, h, d, t3, hr, bb, so, frac);
        }
        for (i = 0; i < 255; i++) {
            if (sl_speed(r) >= S || sb >= 255)
                break;
            r[35] = (uint8_t)(sb + 1);
            if (sl_speed(r) > S) {
                r[35] = (uint8_t)sb;
                break;
            }
            sb++;
        }
    }
    sl_runs(r, h, hr, bb);
}

/* pitcher season writer: the closure wr() of statline._pitcher */
static void sl_pit_wr(uint8_t *r, long o, long h, long bb, long so, long hr, long frac)
{
    sl_split(r, o + h + bb, frac, 107, 1);
    sl_split(r, h, frac, 111, 1);
    sl_split(r, h * 16 / 100, frac, 115, 1);
    sl_split(r, h * 3 / 100, frac, 119, 0);
    sl_split(r, bb, frac, 121, 1);
    sl_split(r, so, frac, 125, 1);
    sl_split(r, hr, frac, 129, 0);
}

static void sl_pitcher(uint8_t *r)
{
    long C = sl_clamp(r[134] & 15, 1, 12);
    long V = sl_clamp(r[134] >> 4, 1, 12);
    long E = sl_clamp(r[135] >> 4, 1, 10);
    int starter = E >= 5;
    long g = starter ? 33 : 50;
    long gs = starter ? 33 : 0;
    long cg = starter ? sl_min(20, (E - 4) * 2) : 0;
    long ip10 = (g * (10 * E - cg) + 5) / 10 * 10;
    long o, x, bb, so, h, hn, hr, frac, er, era100, diff, wp, dec, w95;
    long v, c;
    int i;
    sl_put16(r, 101, ip10);
    r[23] = (uint8_t)g;
    r[98] = (uint8_t)gs;
    r[97] = (uint8_t)cg;
    r[99] = (uint8_t)(cg / 3);
    o = sl_outs(r);
    x = C >= 2 ? 14 - C : 13;
    /* ceil((20x - 10) * o / 999), the numerator is never negative */
    bb = ((20 * x - 10) * o + 998) / 999;
    so = o * (20 + 4 * V) / 270;
    /* the numerator may go negative: the result is clamped to 0 */
    hn = 527 * o + 540 * so - 40 * o * V - 20 * o;
    h = hn > 0 ? hn / 1080 : 0;
    hr = h * 7 / 100;
    frac = SL_SPLIT_P[(r[29] >> 3) & 1];
    sl_pit_wr(r, o, h, bb, so, hr, frac);
    for (i = 0; i < 400; i++) {
        v = sl_velocity(r);
        if (v < V && h > 0)
            h--;
        else if (v > V)
            h++;
        else
            break;
        hr = h * 7 / 100;
        sl_pit_wr(r, o, h, bb, so, hr, frac);
    }
    for (i = 0; i < 400; i++) {
        c = sl_control(r);
        if (c < C && bb > 0)
            bb--;
        else if (c > C)
            bb++;
        else
            break;
        sl_pit_wr(r, o, h, bb, so, hr, frac);
    }
    er = (25 * h + 15 * bb + 50 * hr) / 100;
    sl_put16(r, 103, er);
    sl_put16(r, 105, er);
    era100 = er * 2700 / sl_max(o, 1);
    diff = 350 - era100;
    /* truncating division by 5, as C / */
    wp = sl_clamp(50 + diff / 5, 30, 70);
    if (starter) {
        dec = gs * 6 / 10;
        w95 = dec * wp / 100;
        r[95] = (uint8_t)w95;
        r[96] = (uint8_t)(dec - w95);
        r[100] = 0;
    } else {
        w95 = 5 * wp / 50;
        r[95] = (uint8_t)w95;
        r[96] = (uint8_t)(10 - w95);
        r[100] = 10;
    }
    r[131] = 0;
    r[132] = 3;
    /* his own batting line (he bats in no-DH games): .150, matching the stock pitcher
     * batting nibbles (power 1, hit and run 1) */
    sl_write_bat(r, 60, 9, 1, 0, 0, 3, 20, sl_bat_frac(r));
    sl_runs(r, 9, 0, 3);
}

/* ---------------- ratings.py: the game salary (C21) ---------------- */

/* ratings.era100: (u16(103) * 900000 + era100base >> 1) // era100base, capped 9999;
 * the +0xe9 / +0x1d3 bumps reproduce the game's ERA rounding to hundredths */
static long sl_era100(const uint8_t *r)
{
    unsigned long a = (unsigned long)sl_u16(r, 101) * 100;
    unsigned long er = (unsigned long)sl_u16(r, 103);
    unsigned long n;
    if (a % 1000 == 100)
        a += 0xe9;
    if (a % 1000 == 200)
        a += 0x1d3;
    n = er * 900000 + (a >> 1);
    return a ? sl_min((long)(n / a), 9999) : (n ? 9999 : 0);
}

/* ratings.pitcher_class: 1 starters, 2 unscored c = 0 end < 3, 4 that plus a high
 * endurance starter, 3 the rest */
static long sl_pitcher_class(const uint8_t *r)
{
    long end = r[135] >> 4, g = r[23], gs = r[98], ip10 = sl_u16(r, 101);
    long c = 0;
    if (end > 5 || (g * 33 <= gs * 100 && ip10 > 1000))
        c = 1;
    if (end < 3 && c == 0)
        c = 2;
    if (end > 1 && gs < g / 2)
        c += 3;
    return c ? c : 3;
}

/* ratings.salary_pitcher. Python's // floors; every division here sees a
 * nonnegative dividend, except none: w/so/sv are u8, (400 - era) > 0 in the taken
 * branches and the inn / 180 and inn / 50 shrink factors have inn >= 0, so plain
 * C division truncates exactly like ratings.py */
static long sl_salary_pitcher(const uint8_t *r)
{
    long w = r[95], so = (sl_u16(r, 125) + sl_u16(r, 127)) & 0xffffL;
    long sv = r[100], era = sl_era100(r), inn = sl_u16(r, 101) / 10;
    long x;
    if (sl_pitcher_class(r) == 1 || sl_pitcher_class(r) == 4) {
        x = w * 50 + so * 5;
        if (era < 400)
            x += (400 - era) * 5;
        if (w > 20)
            x += (w - 20) * 100;
        if (so > 200)
            x += (so - 200) * 5;
        if (inn < 180)
            x = (x & 0xffffL) * inn / 180;
    } else {
        x = sv * 20 + so * 5;
        if (era < 400)
            x += (400 - era) * 25 / 10;
        if (sv > 30)
            x += (sv - 30) * 10;
        if (inn < 50)
            x = (x & 0xffffL) * inn / 50;
    }
    return sl_max(109, sl_min(9999, (x & 0xffffL) * 115 / 100));
}

/* ratings.salary_batter */
static long sl_salary_batter(const uint8_t *r)
{
    long ab = sl_s2(r, 37), h = sl_s2(r, 41), d = sl_s2(r, 45);
    long t3 = sl_b2(r, 49), hr = sl_b2(r, 51), bb = sl_s2(r, 53);
    long slg = sl_per_mille(h + d + 2 * t3 + 3 * hr, ab);
    long obp = sl_per_mille(h + bb, ab + bb);
    long ba = sl_per_mille(h, ab);
    long sb = r[35], cs = r[36], rbi = r[33], runs = r[32];
    long hrs = r[51] + r[52];
    long pos = r[31] & 15, rg = r[94] >> 4, am = r[94] & 15;
    long pa = (ab + bb) & 0xffffL;
    long x = obp + slg + hrs * 30 + rbi * 75 / 10;
    if (runs > rbi)
        x += (runs - rbi) * 75 / 10;
    if (hrs > 30)
        x += (hrs - 30) * 50;
    if (sb > cs)
        x += (sb - cs) * 10;
    if (sb > 50)
        x += (sb - 50) * 20;
    if (ba > 300)
        x += (ba - 300) * 20;
    if (pos == 1) {
        if (am > 7)
            x += (am - 7) * 100;
    } else if (pos == 3) {
        if (rg > 8)
            x += (rg - 8) * 50;
        if (rg == 12)
            x -= 50;
    } else if (pos == 4) {
        if (rg > 8)
            x += (rg - 8) * 50;
        if (am > 8)
            x += (am - 8) * 50;
        if (rg + am > 22)
            x -= (rg + am - 22) * 50;
    } else if (pos == 5) {
        if (rg > 8)
            x += (rg - 8) * 100;
        if (am > 8)
            x += (am - 8) * 100;
    } else if (pos == 6 || pos == 8) {
        if (am > 8)
            x += (am - 8) * 100;
    } else if (pos == 7) {
        if (am > 8)
            x += (am - 8) * 50;
        if (rg > 8)
            x += (rg - 8) * 50;
        if (rg == 12)
            x -= 50;
    }
    x &= 0xffffL;
    if (pa < 0x20d)
        x = x * pa / 0x23f;
    return sl_max(109, sl_min(9999, x));
}

/* ratings.salary: the pitcher formula when the pos code (byte 31 low nibble) is 0 */
static long sl_salary(const uint8_t *r)
{
    return (r[31] & 15) == 0 ? sl_salary_pitcher(r) : sl_salary_batter(r);
}

/* statline.fill: overwrite every season stat byte of a 143 B record in place with the
 * line its rating nibbles imply. Pitcher iff pos code (byte 31 low nibble) is 0. */
static void sl_fill(uint8_t *rec)
{
    int i;
    for (i = 0; i < (int)sizeof SL_SEASON_OFFS; i++)
        rec[SL_SEASON_OFFS[i]] = 0;
    for (i = 0; i < 5; i++)
        sl_put16(rec, 61 + 2 * i, SL_GB_DEFAULT[i]);
    if ((rec[31] & 15) == 0) {
        sl_pitcher(rec);
    } else {
        sl_batter(rec);
        sl_fielding(rec);
    }
}

#ifdef STATLINE_REPAIR

/* statline.is_placeholder: named, 0 G, and either a pitcher with IP10 200 and no H, BB
 * or SO, or a batter with AB 40 and no H, BB or SO */
static int sl_is_placeholder(const uint8_t *rec)
{
    if (rec[0] == 0 || rec[23] != 0)
        return 0;
    if ((rec[31] & 15) == 0)
        return sl_u16(rec, 101) == 200 && sl_s2(rec, 111) == 0 && sl_s2(rec, 121) == 0
            && sl_s2(rec, 125) == 0;
    return sl_s2(rec, 37) == 40 && sl_s2(rec, 41) == 0 && sl_s2(rec, 53) == 0
        && sl_s2(rec, 57) == 0;
}

/* statline.repair_image: fill every placeholder roster record (0..39) of a V20 image in
 * place. Returns the number of records repaired. */
static int sl_repair_image(uint8_t *img)
{
    int i, n = 0;
    for (i = 0; i < SL_ROSTER_RECORDS; i++) {
        uint8_t *rec = img + SL_HEADER_LEN + SL_RECORD_LEN * i;
        if (sl_is_placeholder(rec)) {
            sl_fill(rec);
            n++;
        }
    }
    return n;
}

#endif /* STATLINE_REPAIR */

#endif /* SL_STATLINE_H */
