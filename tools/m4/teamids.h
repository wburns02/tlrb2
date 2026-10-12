/* TEAMIDS: C port of tools/m4/teamids.py (contract C12.1 engine ids, C12.3 stable ids and TEAMID.DAT).
 * Included by realign.h and teamids_c/ti_host.c. Every function is static and works on the raw MAJ bytes
 * (and a 256 B table). No file I/O, no malloc, no globals. Offsets that can pass 32767 are long, so the
 * 16-bit DOS build (int is 16 bits) gives the host results. Byte-identical to teamids.py
 * (test_teamids_c.py checks it).
 */
#ifndef TI_TEAMIDS_H
#define TI_TEAMIDS_H

#include <stdint.h>

/* each tool uses only some helpers: OpenWatcom -wx -we would fail the build on W202 (unused static) */
#ifdef __WATCOMC__
#pragma disable_message(202)
#endif

#define TI_S_AL 0x21dL
#define TI_S_NL 0x758cL
#define TI_O_NAMES 0x0f
#define TI_O_ABBR 0x18f
#define TI_O_STEM 0x1d7
#define TI_SLOTS 24
#define TI_TABLE_SIZE 256
#define TI_MAX_TEAMS 48

typedef struct {
    uint8_t id, L, slot;
    uint8_t stem[8];
} TiTeam;

/* teamids.S: the league block of L (0 AL, 1 NL) */
static long ti_league_s(int L)
{
    return L ? TI_S_NL : TI_S_AL;
}

/* teamids.ndiv: 2 when the MAJ is short or 0x20d is not 1..3, else 0x20d */
static int ti_ndiv(const uint8_t *d, long len)
{
    if (len <= 0x20d || d[0x20d] < 1 || d[0x20d] > 3)
        return 2;
    return d[0x20d];
}

/* teamids.slot_to_engine: engine id L * 16 + c, c compacted with 3 divisions */
static int ti_slot_to_engine(int L, int slot, int nd)
{
    int c = slot;
    if (nd == 3)
        c = slot < 8 ? slot : (slot < 16 ? slot - 3 : slot - 6);
    return L * 16 + c;
}

/* teamids.engine_to_slot */
static void ti_engine_to_slot(int e, int nd, int *L, int *slot)
{
    int i = e & 15;
    *L = (e >> 4) & 1;
    *slot = i;
    if (nd == 3)
        *slot = i < 5 ? i : (i < 10 ? i + 3 : i + 6);
}

/* teamids.maj_teams: the teams in order L 0 then 1, slot ascending (id left 0). Returns the count. */
static int ti_maj_teams(const uint8_t *d, long len, TiTeam *out)
{
    int nd, L, slot, j, n = 0;
    long a;
    if (len < TI_S_NL + TI_O_STEM + 8L * TI_SLOTS)
        return 0;
    nd = ti_ndiv(d, len);
    for (L = 0; L < 2; L++) {
        for (slot = 0; slot < TI_SLOTS; slot++) {
            if (nd == 3 ? (slot % 8 >= 5) : (slot >= 16))
                continue;
            a = ti_league_s(L) + TI_O_STEM + 8L * slot;
            if (d[a] == 0)
                continue;
            out[n].id = 0;
            out[n].L = (uint8_t)L;
            out[n].slot = (uint8_t)slot;
            for (j = 0; j < 8; j++)
                out[n].stem[j] = d[a + j];
            n++;
        }
    }
    return n;
}

/* teamids.make_table: entry k = the stem of the team at engine id k (first team wins), zero elsewhere */
static void ti_make_table(const uint8_t *d, long len, uint8_t *tab256)
{
    TiTeam t[TI_MAX_TEAMS];
    uint8_t seen[32];
    int n, nd, i, j, k;
    for (i = 0; i < TI_TABLE_SIZE; i++)
        tab256[i] = 0;
    for (k = 0; k < 32; k++)
        seen[k] = 0;
    nd = ti_ndiv(d, len);
    n = ti_maj_teams(d, len, t);
    for (i = 0; i < n; i++) {
        k = ti_slot_to_engine(t[i].L, t[i].slot, nd);
        if (k >= 32 || seen[k])
            continue;
        seen[k] = 1;
        for (j = 0; j < 8; j++)
            tab256[8 * k + j] = t[i].stem[j];
    }
}

/* the length of an 8 B field without its trailing NULs (embedded NULs stay) */
static int ti_trim(const uint8_t *p, int n)
{
    while (n > 0 && p[n - 1] == 0)
        n--;
    return n;
}

/* ASCII lower case of one byte (only A..Z change) */
static int ti_lower(int c)
{
    return (c >= 'A' && c <= 'Z') ? c + ('a' - 'A') : c;
}

/* the first n bytes of a and b equal after ASCII lower casing */
static int ti_same_ci(const uint8_t *a, const uint8_t *b, int n)
{
    int i;
    for (i = 0; i < n; i++)
        if (ti_lower(a[i]) != ti_lower(b[i]))
            return 0;
    return 1;
}

/* teamids._id_of_stem: the lowest k whose entry matches the stem (trailing NULs and ASCII case ignored); an
 * entry whose first byte is NUL never matches. -1 when none. */
static int ti_id_of_stem(const uint8_t *tab, const uint8_t *st)
{
    int k, n = ti_trim(st, 8), m;
    for (k = 0; k < 32; k++) {
        const uint8_t *e = tab + 8 * k;
        if (e[0] == 0)
            continue;
        m = ti_trim(e, 8);
        if (m == n && ti_same_ci(e, st, n))
            return k;
    }
    return -1;
}

/* teamids.teams: the teams sorted by id (tab NULL: id = engine id, ids 32 and up left out). Returns the count. */
static int ti_teams(const uint8_t *d, long len, const uint8_t *tab, TiTeam *out)
{
    uint8_t taken[32];
    TiTeam t;
    int n, m = 0, nd, i, j, k;
    nd = ti_ndiv(d, len);
    n = ti_maj_teams(d, len, out);
    for (k = 0; k < 32; k++)
        taken[k] = 0;
    for (i = 0; i < n; i++) {
        k = tab ? ti_id_of_stem(tab, out[i].stem) : ti_slot_to_engine(out[i].L, out[i].slot, nd);
        if (k < 0 || k >= 32 || taken[k])
            continue;
        taken[k] = 1;
        out[m] = out[i];
        out[m].id = (uint8_t)k;
        m++;
    }
    /* insertion sort by id (the ids are unique) */
    for (i = 1; i < m; i++) {
        t = out[i];
        for (j = i - 1; j >= 0 && out[j].id > t.id; j--)
            out[j + 1] = out[j];
        out[j + 1] = t;
    }
    return m;
}

/* teamids.id_of_slot: the stable id of (L, slot), -1 when no team */
static int ti_id_of_slot(const uint8_t *d, long len, const uint8_t *tab, int L, int slot)
{
    TiTeam t[TI_MAX_TEAMS];
    int n = ti_teams(d, len, tab, t), i;
    for (i = 0; i < n; i++)
        if (t[i].L == L && t[i].slot == slot)
            return t[i].id;
    return -1;
}

/* teamids.slot_of_id: 1 and (L, slot) when id k is a team, else 0 */
static int ti_slot_of_id(const uint8_t *d, long len, const uint8_t *tab, int k, int *L, int *slot)
{
    TiTeam t[TI_MAX_TEAMS];
    int n = ti_teams(d, len, tab, t), i;
    for (i = 0; i < n; i++) {
        if (t[i].id == k) {
            *L = t[i].L;
            *slot = t[i].slot;
            return 1;
        }
    }
    return 0;
}

/* teamids.id_of_engine: 0xff for 0xff, engine ids 32 and up, and a slot with no team */
static int ti_id_of_engine(const uint8_t *d, long len, const uint8_t *tab, int e)
{
    int L, slot, k;
    if (e == 0xff || e >= 32)
        return 0xff;
    ti_engine_to_slot(e, ti_ndiv(d, len), &L, &slot);
    k = ti_id_of_slot(d, len, tab, L, slot);
    return k < 0 ? 0xff : k;
}

/* teamids.stem_of_id: the 8 raw bytes of id k's stem (all zero when no team); the return value is the
 * length without trailing NULs, 0 when no team */
static int ti_stem_of_id(const uint8_t *d, long len, const uint8_t *tab, int k, uint8_t *out8)
{
    TiTeam t[TI_MAX_TEAMS];
    int n = ti_teams(d, len, tab, t), i, j;
    for (i = 0; i < n; i++) {
        if (t[i].id == k) {
            for (j = 0; j < 8; j++)
                out8[j] = t[i].stem[j];
            return ti_trim(t[i].stem, 8);
        }
    }
    for (j = 0; j < 8; j++)
        out8[j] = 0;
    return 0;
}

#endif /* TI_TEAMIDS_H */
