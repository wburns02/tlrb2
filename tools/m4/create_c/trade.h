/* trade.h: the CREATE TRADE decision (C76, create.py trade_verdict). Pure record and
 * image views, no file access: the ROSTERS value V (rosters.value), SP / RP
 * (rosters.sp_rp), the thinnest field position of a team (dynview.draft_need), the
 * top 3 of a type by V (rosters step 6) and the verdict of team B on a 1-for-1 offer.
 * The value code is copied from rosters_c/rosters.c (v_of, spot_of, g_sum, w_of,
 * discount_of) and the need count from dynview.draft_need; those files are not
 * included or edited. Needs repair.h (layout macros, can_play, score, fld_w), which
 * it includes. Every symbol is static; C89.
 */
#ifndef TLRB2_TRADE_H
#define TLRB2_TRADE_H

/* the helpers a translation unit does not call would fail a gcc -Werror build */
#if defined(__GNUC__) && !defined(__WATCOMC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#endif

#include <stdint.h>
#include <string.h>  /* repair.h uses memcpy / memset and does not include it */
#include "../repair.h"

#define TR_SP_END 6             /* rosters.T['SP_END'] */
#define TR_BAND   5             /* rosters.T['BAND'] */
#define TR_NEED_BONUS 32        /* the need bonus, /256 of V(X) */
#define TR_SP_WANTED 5          /* a team with fewer named SP than this wants one */

static int tr_w_of(int age)
{
    static const int16_t WA[7][2] = { { 20, 179 }, { 22, 154 }, { 23, 141 },
        { 24, 102 }, { 25, 77 }, { 26, 38 }, { 27, 13 } };
    int i;
    for (i = 0; i < 7; i++)
        if (age <= WA[i][0])
            return WA[i][1];
    return 0;
}

static int tr_discount_of(int age)
{
    static const int16_t DA[5][2] = { { 29, 256 }, { 31, 248 }, { 33, 236 },
        { 35, 220 }, { 37, 200 } };
    int i;
    for (i = 0; i < 5; i++)
        if (age <= DA[i][0])
            return DA[i][1];
    return 180;
}

static int tr_g_of(int x)
{
    return (x <= 22) ? 90 : (x <= 24) ? 64 : 32;
}

/* rollover.GM, by development grade 0..5 */
static const uint16_t TR_GM[6] = { 0, 1, 3, 4, 5, 7 };

/* G[age] = sum of g(x) for x = age+1..26 (0 from age 26), each term scaled by the
 * grade when it is 1..5; a grade byte past 5 reads as 0 (create.py _value) */
static int32_t tr_g_sum(int age, int grade)
{
    int x;
    int32_t sum = 0;
    if (age >= 26)
        return 0;
    if (grade > 5)
        grade = 0;
    if (grade)
        for (x = age + 1; x <= 26; x++)
            sum += (tr_g_of(x) * (int32_t)TR_GM[grade]) >> 2;
    else
        for (x = age + 1; x <= 26; x++)
            sum += tr_g_of(x);
    return sum;
}

/* Spot = S computed on the pot ratings (cap 10 endurance, 12 else) */
static int32_t tr_spot(const uint8_t *r)
{
    int add = (int)((tr_g_sum(r[R_AGE], r[R_GRADE]) + 128) >> 8);
    int ctrl = r[R_CV] & 15, vel = r[R_CV] >> 4, end = r[R_ENDUR] >> 4;
    int power = r[R_POWER] & 15, hit_run = r[R_HITRUN] & 15;
    int speed = r[R_SPEED] >> 4, rng_ = r[R_RANGE] >> 4, arm = r[R_RANGE] & 15;
    int rw, aw;
    if (is_pitcher(r)) {
        if (ctrl < 12) ctrl = (ctrl + add < 12) ? ctrl + add : 12;
        if (vel < 12) vel = (vel + add < 12) ? vel + add : 12;
        if (end < 10) end = (end + add < 10) ? end + add : 10;
        return 3 * ctrl + 3 * vel + 2 * end;
    }
    if (power < 12) power = (power + add < 12) ? power + add : 12;
    if (hit_run < 12) hit_run = (hit_run + add < 12) ? hit_run + add : 12;
    if (speed < 12) speed = (speed + add < 12) ? speed + add : 12;
    if (rng_ < 12) rng_ = (rng_ + add < 12) ? rng_ + add : 12;
    if (arm < 12) arm = (arm + add < 12) ? arm + add : 12;
    fld_w(pos1f(r), &rw, &aw);
    return 3 * power + 3 * hit_run + speed + rw * rng_ + aw * arm;
}

/* rosters.value: V = (S*(256 - w) + Spot*w) >> 8 by age, then (V * discount) >> 8;
 * r is a 143 byte roster record */
static int32_t value(const uint8_t *r)
{
    int age = r[R_AGE];
    int w = tr_w_of(age);
    int32_t v = ((int32_t)score(r) * (256 - w) + (int32_t)tr_spot(r) * w) >> 8;
    return (v * tr_discount_of(age)) >> 8;
}

/* rosters.sp_rp: 1 = SP (endurance >= TR_SP_END), 0 = RP */
static int sp_rp(const uint8_t *r)
{
    return (r[R_ENDUR] >> 4) >= TR_SP_END;
}

/* dynview.draft_need: the field position q 1..8 with the fewest named batters
 * (slots 16..39) that can play it, ties to the lower q */
static int tr_need(const uint8_t *img)
{
    int q, s, n, best = 1, best_n = -1;
    for (q = 1; q <= 8; q++) {
        n = 0;
        for (s = 16; s < 40; s++)
            if (IS_ON(img, s) && can_play(RIMG(img, s), q))
                n++;
        if (best_n < 0 || n < best_n) {
            best = q;
            best_n = n;
        }
    }
    return best;
}

/* named slots 0..15 whose record is a SP */
static int tr_sp_count(const uint8_t *img)
{
    int s, n = 0;
    for (s = 0; s < 16; s++)
        if (IS_ON(img, s) && sp_rp(RIMG(img, s)))
            n++;
    return n;
}

/* 1 when the named slot is one of the 3 named slots of its type (pitchers 0..15,
 * batters 16..39) with the highest V, ties to the lower slot (rosters step 6 top3) */
static int tr_top3(const uint8_t *img, int slot)
{
    int lo = slot < 16 ? 0 : 16;
    int hi = slot < 16 ? 16 : 40;
    int s, ahead = 0;
    int32_t vs = value(RIMG(img, slot)), v;
    for (s = lo; s < hi; s++) {
        if (s == slot || !IS_ON(img, s))
            continue;
        v = value(RIMG(img, s));
        if (v > vs || (v == vs && s < slot))
            ahead++;
    }
    return ahead < 3;
}

/* the verdict of team B (image bimg) on the offer of aimg's slot give for bimg's
 * slot get: 0 accepted, 1 SAME TYPE ONLY, 2 UNTOUCHABLE, 3 NOT ENOUGH VALUE.
 * First match wins (create.py trade_verdict). */
static int tr_verdict(const uint8_t *aimg, int give, const uint8_t *bimg, int get)
{
    const uint8_t *x = RIMG(aimg, give);
    const uint8_t *y = RIMG(bimg, get);
    int32_t vx, vy, eff;
    if ((give < 16) != (get < 16))
        return 1;
    if (tr_top3(bimg, get))
        return 2;
    vx = value(x);
    vy = value(y);
    eff = vx;
    if (give >= 16) {
        if (can_play(x, tr_need(bimg)))
            eff += (vx * TR_NEED_BONUS) >> 8;
    } else if (sp_rp(x) && tr_sp_count(bimg) < TR_SP_WANTED) {
        eff += (vx * TR_NEED_BONUS) >> 8;
    }
    if (eff * 100 < vy * (100 - TR_BAND))
        return 3;
    return 0;
}

/* a latin-1 character str.strip() removes (Python str.isspace) */
static int tr_is_space(int c)
{
    return (c >= 9 && c <= 13) || (c >= 28 && c <= 32) || c == 0x85 || c == 0xa0;
}

/* rosters.pname: 'First Last' from the record bytes (each part cut at its first
 * NUL), stripped like str.strip(); dst holds 24 bytes at least */
static void tr_pname(const uint8_t *rec, char *dst)
{
    char tmp[24];
    int i, n = 0, a, b;
    for (i = 0; i < 8 && rec[12 + i]; i++)
        tmp[n++] = (char)rec[12 + i];
    tmp[n++] = ' ';
    for (i = 0; i < 12 && rec[i]; i++)
        tmp[n++] = (char)rec[i];
    a = 0;
    b = n;
    while (a < b && tr_is_space((uint8_t)tmp[a]))
        a++;
    while (b > a && tr_is_space((uint8_t)tmp[b - 1]))
        b--;
    for (i = a; i < b; i++)
        dst[i - a] = tmp[i];
    dst[b - a] = 0;
}

#if defined(__GNUC__) && !defined(__WATCOMC__)
#pragma GCC diagnostic pop
#endif

#endif /* TLRB2_TRADE_H */
