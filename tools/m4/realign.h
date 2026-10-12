/* REALIGN: C port of tools/m4/realign.py (playoff format, contract C12.4 setting and C12.5 realignment) with
 * the plan step. Includes teamids.h. Byte-identical to realign.realign() and realign.plan() (test_teamids_c.py
 * checks it). Every function is static. No malloc: the MAJ is rewritten in place, after every team entry the
 * rewrite needs has been copied out (ra_realign). Refusals leave the MAJ untouched.
 */
#ifndef RA_REALIGN_H
#define RA_REALIGN_H

#include <stdint.h>
#include "teamids.h"

#define RA_MAJ_SIZE 59771L

/* realign.KNOWN: [target 3 ? 1 : 0][L] -> the division sizes (East, West, Central) and the abbreviations
 * division by division. Unused entries stay NULL. */
static const int RA_KSIZE[2][2][3] = {
    { { 7, 7, 0 }, { 6, 6, 0 } },
    { { 5, 4, 5 }, { 4, 3, 5 } } };
static const char *const RA_KNOWN[2][2][14] = {
    { { "BAL", "BOS", "CLE", "DET", "MIL", "NYA", "TOR", "CAL", "CHA", "KC", "MIN", "OAK", "SEA", "TEX" },
      { "CHN", "MON", "NYN", "PHI", "PIT", "SL", "ATL", "CIN", "HOU", "LA", "SD", "SF" } },
    { { "BAL", "BOS", "DET", "NYA", "TOR", "CAL", "OAK", "SEA", "TEX", "CHA", "CLE", "KC", "MIL", "MIN" },
      { "ATL", "MON", "NYN", "PHI", "LA", "SD", "SF", "CHN", "CIN", "HOU", "PIT", "SL" } } };

/* one team entry of a league: the 16 B name, 3 B abbreviation and 8 B stem */
typedef struct {
    uint8_t name[16], abbr[3], stem[8];
} RaTeam;

/* realign.now_divs: 2 for short MAJs and 0x20d 1, else 0x20d */
static int ra_now_divs(const uint8_t *d, long len)
{
    if (len <= 0x20d)
        return 2;
    return d[0x20d] == 1 ? 2 : d[0x20d];
}

/* realign.wanted: HISTORY.DAT byte 11 when 2 or 3, else now (hist may be NULL with hlen 0) */
static int ra_wanted(const uint8_t *hist, long hlen, const uint8_t *d, long len)
{
    int b = hlen > 11 ? hist[11] : 0;
    return (b == 2 || b == 3) ? b : ra_now_divs(d, len);
}

/* a refusal: the reason goes out (when reason is not NULL) and the return is 1 */
static int ra_refuse(const char **reason, const char *why)
{
    if (reason)
        *reason = why;
    return 1;
}

/* realign._abbr: the 3 B abbreviation with every NUL removed equals the known string k */
static int ra_abbr_is(const uint8_t *a, const char *k)
{
    int i, j = 0;
    for (i = 0; i < 3; i++) {
        if (a[i] == 0)
            continue;
        if ((uint8_t)k[j] != a[i])
            return 0;
        j++;
    }
    return k[j] == 0;
}

/* realign._divisions, the known branch test: the league's abbreviation set equals the table's set */
static int ra_known_set(const RaTeam *lg, int n, int t, int L)
{
    int nk = RA_KSIZE[t][L][0] + RA_KSIZE[t][L][1] + RA_KSIZE[t][L][2];
    int i, f, hit;
    for (i = 0; i < n; i++) {
        hit = 0;
        for (f = 0; f < nk && !hit; f++)
            hit = ra_abbr_is(lg[i].abbr, RA_KNOWN[t][L][f]);
        if (!hit)
            return 0;
    }
    for (f = 0; f < nk; f++) {
        hit = 0;
        for (i = 0; i < n && !hit; i++)
            hit = ra_abbr_is(lg[i].abbr, RA_KNOWN[t][L][f]);
        if (!hit)
            return 0;
    }
    return 1;
}

/* realign._divisions: the division lists (East, West, Central) of league L in div[][] with counts dn[]. The
 * known alignment when the set matches (each abbreviation takes the LAST team that has it, the Python dict), else
 * the generic split in list order. */
static void ra_divide(const RaTeam *lg, int n, int target, int L, RaTeam div[3][TI_SLOTS], int dn[3])
{
    int t = target == 3 ? 1 : 0;
    int v, i, j, f = 0, last;
    if (ra_known_set(lg, n, t, L)) {
        for (v = 0; v < 3; v++) {
            dn[v] = RA_KSIZE[t][L][v];
            for (i = 0; i < dn[v]; i++, f++) {
                last = 0;
                for (j = 0; j < n; j++)
                    if (ra_abbr_is(lg[j].abbr, RA_KNOWN[t][L][f]))
                        last = j;
                div[v][i] = lg[last];
            }
        }
        return;
    }
    if (target == 3) {
        dn[0] = n / 3 + (n % 3 > 0);
        dn[1] = n / 3 + (n % 3 > 1);
        dn[2] = n / 3;
    } else {
        dn[0] = (n + 1) / 2;
        dn[1] = n / 2;
        dn[2] = 0;
    }
    j = 0;
    for (v = 0; v < 3; v++)
        for (i = 0; i < dn[v]; i++)
            div[v][i] = lg[j++];
}

/* realign.realign: 0 rewrites d in place (the new bytes of the Python), 1 refuses and leaves d untouched with
 * the Python reason in *reason. Every refusal check runs before the first write. */
static int ra_realign(uint8_t *d, long len, int target, const char **reason)
{
    TiTeam all[TI_MAX_TEAMS];
    RaTeam lg[2][TI_SLOTS], dv[3][TI_SLOTS];
    RaTeam *c;
    const RaTeam *t;
    long s;
    int n[2], dn[3], keep15[2], cap, nall, i, j, L, v, slot;

    if (target != 2 && target != 3)
        return ra_refuse(reason, "BAD TARGET");
    if (len < RA_MAJ_SIZE)
        return ra_refuse(reason, "SHORT MAJ");
    if (d[0x20c] != 2)
        return ra_refuse(reason, "NOT 2 LEAGUES");
    if (d[0x20d] < 1 || d[0x20d] > 3)
        return ra_refuse(reason, "BAD DIVISIONS");
    if (target == ra_now_divs(d, len))
        return ra_refuse(reason, "ALREADY");

    /* copy every team entry of both leagues out before the first write */
    nall = ti_maj_teams(d, len, all);
    n[0] = 0;
    n[1] = 0;
    for (i = 0; i < nall; i++) {
        L = all[i].L;
        s = ti_league_s(L);
        slot = all[i].slot;
        c = &lg[L][n[L]++];
        for (j = 0; j < 16; j++)
            c->name[j] = d[s + TI_O_NAMES + 16L * slot + j];
        for (j = 0; j < 3; j++)
            c->abbr[j] = d[s + TI_O_ABBR + 3L * slot + j];
        for (j = 0; j < 8; j++)
            c->stem[j] = all[i].stem[j];
    }
    cap = target == 3 ? 15 : 14;
    for (L = 0; L < 2; L++) {
        if (n[L] > cap)
            return ra_refuse(reason, L ? "NL TOO MANY TEAMS" : "AL TOO MANY TEAMS");
        if (target == 3 && n[L] % 2)
            return ra_refuse(reason, L ? "NL ODD COUNT" : "AL ODD COUNT");
    }

    /* slot 15 keeps its entries when the ORIGINAL stem starts with NUL (the all-star entry) */
    for (L = 0; L < 2; L++)
        keep15[L] = d[ti_league_s(L) + TI_O_STEM + 8L * 15] == 0;

    for (L = 0; L < 2; L++) {
        s = ti_league_s(L);
        ra_divide(lg[L], n[L], target, L, dv, dn);
        for (slot = 0; slot < TI_SLOTS; slot++) {
            if (slot == 15 && keep15[L])
                continue;
            for (j = 0; j < 16; j++)
                d[s + TI_O_NAMES + 16L * slot + j] = 0;
            for (j = 0; j < 3; j++)
                d[s + TI_O_ABBR + 3L * slot + j] = 0;
            for (j = 0; j < 8; j++)
                d[s + TI_O_STEM + 8L * slot + j] = 0;
        }
        for (v = 0; v < 3; v++) {
            for (i = 0; i < dn[v]; i++) {
                t = &dv[v][i];
                slot = v * 8 + i;
                for (j = 0; j < 16; j++)
                    d[s + TI_O_NAMES + 16L * slot + j] = t->name[j];
                for (j = 0; j < 3; j++)
                    d[s + TI_O_ABBR + 3L * slot + j] = t->abbr[j];
                for (j = 0; j < 8; j++)
                    d[s + TI_O_STEM + 8L * slot + j] = t->stem[j];
            }
            d[s + 0x298 + v] = (uint8_t)dn[v];
            d[0x20e + 3 * L + v] = (uint8_t)dn[v];
        }
        /* standings order 0xff (24 B), then W, L and GB zero (96 B) */
        for (j = 0; j < 24; j++)
            d[s + 0x2b3 + j] = 0xff;
        for (j = 0; j < 96; j++)
            d[s + 0x2cb + j] = 0;
    }
    d[0x20a] = 0xf3;
    d[0x20d] = (uint8_t)target;
    return 0;
}

/* realign.plan: 1 when wanted == now (nothing), 2 when refused (d untouched, *reason set), 0 when d is
 * realigned in place. On 0 with have_table 0, tab_out256 gets make_table of the ORIGINAL MAJ and *tab_new = 1;
 * otherwise *tab_new = 0. */
static int ra_plan(uint8_t *d, long len, const uint8_t *hist, long hlen, int have_table,
                   uint8_t *tab_out256, int *tab_new, const char **reason)
{
    int want;
    *tab_new = 0;
    want = ra_wanted(hist, hlen, d, len);
    if (want == ra_now_divs(d, len))
        return 1;
    /* the table is taken from the MAJ before the rewrite */
    if (!have_table)
        ti_make_table(d, len, tab_out256);
    if (ra_realign(d, len, want, reason))
        return 2;
    *tab_new = !have_table;
    return 0;
}

#endif /* RA_REALIGN_H */
