/* repair.h: the managed-team repair core shared by ROSTERS (rosters_c) and
 * CREATE (create_c, C69 pool release). Moved verbatim from
 * tools/m4/rosters_c/rosters.c (the image / header layout macros, the pure
 * record views and the managed repair with its rp_* state, all static).
 * Include once per translation unit; every symbol is static so nothing leaks
 * into a linker unit that also compiles rosters.c.
 */
#ifndef TLRB2_REPAIR_H
#define TLRB2_REPAIR_H

/* ---------------- image / header layout ---------------- */

#define V20_HDR  295
#define V20_REC  143
#define V20_N    80
#define V20_SIZE (V20_HDR + V20_REC * V20_N)

#define H_STAFF   111
#define H_LINEUP  122
#define H_DEF     158
#define H_BENCH   194
#define H_RESERVE 222

/* record field offsets (v20.py F table) */
#define R_ACTIVE 0
#define R_YEAR   21
#define R_AGE    0x14
#define R_EXP    0x16
#define R_GAMES  0x17
#define R_SPEED  0x1d
#define R_POS    0x1f
#define R_AB_L   0x25
#define R_AB_R   0x27
#define R_BB_L   0x35
#define R_BB_R   0x37
#define R_IP10   0x65
#define R_POWER  0x4a
#define R_HITRUN 0x4b
#define R_RANGE  0x5e
#define R_PYEAR  0x8d    /* pool years, byte 141 */
#define R_CV     0x86    /* control lo, velocity hi */
#define R_ENDUR  0x87    /* endurance hi */
#define R_GRADE  142     /* C1b hidden development grade */

/* ---------------- pure record views ---------------- */

#define RIMG(img, s) ((img) + V20_HDR + V20_REC * (s))
#define IS_ON(img, s) ((img)[V20_HDR + V20_REC * (s)] != 0)

static int pos1f(const uint8_t *r)
{
    return r[R_POS] & 15;
}

static int pos2f(const uint8_t *r)
{
    return r[R_POS] >> 4;
}

static int is_pitcher(const uint8_t *r)
{
    return (r[R_POS] & 15) == 0;
}

/* group code -> covered positions */
static int covers(int p, int q)
{
    switch (p) {
    case 10: return q >= 6 && q <= 8;
    case 11: return q >= 2 && q <= 5;
    case 12: return q >= 2 && q <= 8;
    case 13: return q == 1 || (q >= 6 && q <= 8);
    case 14: return q >= 1 && q <= 5;
    case 15: return q == 1 || q == 4;
    default: return 0;
    }
}

static int can_play(const uint8_t *r, int q)
{
    if (q < 1 || q > 8)
        return 0;
    if (pos1f(r) == q || pos2f(r) == q)
        return 1;
    return covers(pos1f(r), q) || covers(pos2f(r), q);
}

/* (rw, aw) by primary position */
static void fld_w(int q, int *rw, int *aw)
{
    static const uint8_t W[16][2] = {
        { 0, 0 }, { 1, 3 }, { 1, 0 }, { 3, 1 }, { 2, 2 }, { 3, 2 },
        { 1, 1 }, { 3, 1 }, { 1, 2 }, { 0, 0 }, { 2, 1 }, { 2, 2 },
        { 2, 1 }, { 1, 3 }, { 1, 3 }, { 1, 3 } };
    *rw = W[q][0];
    *aw = W[q][1];
}

/* Fld(q) = rw[q]*range + aw[q]*arm (weights of q, not of p) */
static int fld_of(const uint8_t *r, int q)
{
    int rw, aw;
    fld_w(q, &rw, &aw);
    return rw * (r[R_RANGE] >> 4) + aw * (r[R_RANGE] & 15);
}

/* Off = 3*power + 3*hit_run + speed */
static int offv(const uint8_t *r)
{
    return 3 * (r[R_POWER] & 15) + 3 * (r[R_HITRUN] & 15)
         + (r[R_SPEED] >> 4);
}

/* batter S = Off + Fld(pos1); pitcher S = 3*control + 3*velocity + 2*endur */
static int score(const uint8_t *r)
{
    if (is_pitcher(r))
        return 3 * (r[R_CV] & 15) + 3 * (r[R_CV] >> 4) + 2 * (r[R_ENDUR] >> 4);
    return offv(r) + fld_of(r, pos1f(r));
}

static int pitch_score4(const uint8_t *r)
{
    return 3 * (r[R_CV] & 15) + 3 * (r[R_CV] >> 4) + 4 * (r[R_ENDUR] >> 4);
}

static int relief_score2(const uint8_t *r)
{
    return 3 * (r[R_CV] & 15) + 3 * (r[R_CV] >> 4);
}

/* ---------------- managed repair ---------------- */

static uint8_t rp_newres[15];
static const uint8_t *rp_img;
static const uint8_t *rp_chg;
static uint8_t rp_repl[40];
static uint8_t rp_repl_set[40];

static int rp_choose(int slot, int pitch, int pos)
{
    int i, best = -1;
    int32_t bv = 0;
    if (rp_repl_set[slot])
        return rp_repl[slot];
    for (i = 0; i < 15; i++) {
        int r = rp_newres[i];
        const uint8_t *rec;
        if (r == 0xff || r == slot || r >= 40 || !IS_ON(rp_img, r)
            || rp_chg[r])
            continue;
        rec = RIMG(rp_img, r);
        if (is_pitcher(rec) != pitch)
            continue;
        if (pos >= 1 && pos <= 8 && !can_play(rec, pos))
            continue;
        if (best < 0 || score(rec) > bv
            || (score(rec) == bv && r < best)) {
            best = r;
            bv = score(rec);
        }
    }
    if (best < 0)
        return -1;
    for (i = 0; i < 15; i++)
        if (rp_newres[i] == best) {
            rp_newres[i] = (uint8_t)slot;
            break;
        }
    rp_repl_set[slot] = 1;
    rp_repl[slot] = (uint8_t)best;
    return best;
}

static void repair(uint8_t *img, const uint8_t *chg)
{
    struct {
        uint8_t kind;
        int8_t pos;
        int addr;
        uint8_t val;
    } entries[74];
    int ne = 0;
    int e, i, dh, vs;

    for (e = 0; e < 40; e++)
        if (chg[e]) break;
    if (e >= 40)
        return;
    memcpy(rp_newres, img + H_RESERVE, 15);
    rp_img = img;
    rp_chg = chg;
    memset(rp_repl_set, 0, sizeof rp_repl_set);
    for (i = 0; i < 10; i++) {
        entries[ne].kind = 'P';
        entries[ne].pos = -1;
        entries[ne].addr = H_STAFF + i;
        entries[ne].val = img[H_STAFF + i];
        ne++;
    }
    for (dh = 0; dh <= 1; dh++)
        for (vs = 0; vs <= 1; vs++) {
            int o;
            for (i = 0; i < 9; i++) {
                o = H_LINEUP + dh * 18 + vs * 9 + i;
                entries[ne].kind = 'B';
                entries[ne].pos = (int8_t)img[H_DEF + dh * 18 + vs * 9 + i];
                entries[ne].addr = o;
                entries[ne].val = img[o];
                ne++;
            }
            for (i = 0; i < 7; i++) {
                o = H_BENCH + dh * 14 + vs * 7 + i;
                entries[ne].kind = 'B';
                entries[ne].pos = -1;
                entries[ne].addr = o;
                entries[ne].val = img[o];
                ne++;
            }
        }
    for (e = 0; e < ne; e++) {
        int slot = entries[e].val;
        int pitch = (entries[e].kind == 'P');
        int pos = entries[e].pos;
        int best;
        if (slot == 0xff || slot >= 40)     /* C69 gate: a corrupt header byte never indexes chg[40] */
            continue;
        if (!chg[slot] && IS_ON(img, slot))
            continue;
        best = rp_choose(slot, pitch, pos);
        if (best < 0)
            continue;
        if (pos < 1 || pos > 8 || can_play(RIMG(img, best), pos)) {
            img[entries[e].addr] = (uint8_t)best;
            continue;
        }
        /* a later lineup entry the replacement cannot play: pick the best
         * reserve that can, for this entry only */
        {
            int b2 = -1;
            int32_t bv = 0;
            for (i = 0; i < 15; i++) {
                int r = rp_newres[i];
                const uint8_t *rec;
                if (r == 0xff || r >= 40)
                    continue;
                if (r == slot || !IS_ON(img, r) || chg[r])
                    continue;
                rec = RIMG(img, r);
                if (is_pitcher(rec) != pitch)
                    continue;
                if (pos >= 1 && pos <= 8 && !can_play(rec, pos))
                    continue;
                if (b2 < 0 || score(rec) > bv
                    || (score(rec) == bv && r < b2)) {
                    b2 = r;
                    bv = score(rec);
                }
            }
            img[entries[e].addr] = (uint8_t)(b2 >= 0 ? b2 : best);
        }
    }
    memcpy(img + H_RESERVE, rp_newres, 15);
}

#endif /* TLRB2_REPAIR_H */
