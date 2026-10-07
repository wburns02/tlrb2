/* HISTWR: C port of history.record_season + mark_retired (notes/M4_CONTRACT.md C5).
 * Builds on the host with gcc for parity tests and in DOS with OpenWatcom
 * (large model). Streams player entries from HIST_PATH to HISTWR.TMP beside it;
 * never holds the whole player table in memory.
 * usage: HISTWR [PRE_DIR HIST_PATH RETIRED_PATH]
 * exit 0 on success, 2 after any error (HIST_PATH left unchanged).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#ifdef __WATCOMC__
#include <dos.h>
#define DIR_SEP '\\'
#else
#include <dirent.h>
#define DIR_SEP '/'
#endif

#define HDR_SIZE       32
#define SEASON_TABLE   32
#define SEASON_ENTRY   128
#define SEASON_COUNT   64
#define PLAYER_TABLE   (SEASON_TABLE + 64 * SEASON_ENTRY)
#define PLAYER_ENTRY   160
#define NUM_TOT        25
#define EMPTY_TOP      ((int16_t)-32768)
#define TMP_NAME       "HISTWR.TMP"
#define BAK_NAME       "HISTWR.BAK"
#define STATUS_ACTIVE  1
#define STATUS_RETIRED 2
#define STATUS_HOF     3
#define VERSION_ONE    1

#define V20_HDR  295
#define V20_REC  143
#define V20_N    80
#define V20_SIZE (V20_HDR + V20_REC * V20_N)

#define R_ACTIVE 0
#define R_AGE    0x14
#define R_GAMES  0x17
#define R_POS1   0x1f
#define R_RUNS   0x20
#define R_RBI    0x21
#define R_SB     0x23
#define R_CS     0x24
#define R_AB_L   0x25
#define R_AB_R   0x27
#define R_H_L    0x29
#define R_H_R    0x2b
#define R_D_L    0x2d
#define R_D_R    0x2f
#define R_T_L    0x31
#define R_T_R    0x32
#define R_HR_L   0x33
#define R_HR_R   0x34
#define R_BB_L   0x35
#define R_BB_R   0x37
#define R_SO_L   0x39
#define R_SO_R   0x3b
#define R_E1     0x55
#define R_E2     0x56
#define R_W      0x5f
#define R_L      0x60
#define R_CG     0x61
#define R_GS     0x62
#define R_SHO    0x63
#define R_SV     0x64
#define R_IP10   0x65
#define R_ER     0x67
#define R_PH_L   0x6f
#define R_PH_R   0x71
#define R_PBB_L  0x79
#define R_PBB_R  0x7b
#define R_PSO_L  0x7d
#define R_PSO_R  0x7f
#define R_PHR_L  0x81
#define R_PHR_R  0x82
#define R_RANGE  0x5e
#define R_ARM    0x5e

#define MAJ_SIZE     59771
#define MAJ_DAYS     244
#define MAJ_S_AL     0x21d
#define MAJ_S_NL     0x758c
#define MAJ_O_W      0x2cb
#define MAJ_O_L      0x2e3
#define MAJ_O_SCHED  0x3eb
#define MAJ_O_RUNS   0x1607
#define MAJ_O_PLAYED 0x7187
#define MAJ_O_STEM   0x1d7
#define MAJ_O_DHVAL  0x297

#define MAXV        64
#define HASH_BUCKETS 1024
#define TOT_G 0
#define TOT_AB 1
#define TOT_H 2
#define TOT_HR 5
#define TOT_W 13
#define TOT_SV 15
#define TOT_OUTS 19
#define TOT_PSO 23

#define DEF_PRE  "C:\\DYNSNAP"
#define DEF_HIST "TEAMS\\CLASSIC\\HISTORY.DAT"
#define DEF_RET  "C:\\DYNSNAP\\RETIRED.DAT"

typedef struct {
    uint8_t *d;
    char stem_raw[32][9];
    char stem_up[32][9];
    uint8_t ws, runner, al_p, nl_p;
} Maj;

typedef struct {
    uint8_t name[20];
    uint16_t birth;
    uint16_t games;
    uint8_t age;
    uint8_t pos1;
    int32_t next_dup;
    uint32_t tot[NUM_TOT];
    int16_t w10;
} CurPlayer;

typedef struct {
    char fname[16];
    uint8_t lg_slot;
    uint16_t ncur;
    CurPlayer cur[40];
} TeamInfo;

typedef struct {
    int32_t first_cur;
    int32_t entry_index;
    int32_t next;
} Slot;

typedef struct {
    char name[13];
    uint8_t flags[40];
    int32_t team_ix;
} RetTeam;

static char g_names[MAXV][16];
static uint8_t g_v20[V20_SIZE];
static uint8_t g_tab[PLAYER_TABLE];
static TeamInfo *g_tp[MAXV];
static int32_t g_nt;
static Slot *g_slots;
static int32_t g_nslots, g_slots_cap;
static int32_t g_hhead[HASH_BUCKETS];
static int32_t g_L_lw, g_L_pa, g_L_runs, g_L_er, g_L_outs;
static int32_t g_pf[32];
static uint8_t g_pf_valid[32];
static uint16_t g_season_no;
static Maj g_maj;
static char g_retpath[512];
static uint16_t rd16(const uint8_t *p)
{
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static int16_t rd16s(const uint8_t *p)
{
    return (int16_t)rd16(p);
}

static void wr16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xffu);
    p[1] = (uint8_t)((v >> 8) & 0xffu);
}

static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void wr32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xffu);
    p[1] = (uint8_t)((v >> 8) & 0xffu);
    p[2] = (uint8_t)((v >> 16) & 0xffu);
    p[3] = (uint8_t)((v >> 24) & 0xffu);
}

/* war.idiv: signed division truncating toward zero (C99 / already does). */
static int32_t idiv64(int64_t a, int64_t b)
{
    return (int32_t)(a / b);
}

static int32_t outs_of(int32_t ip10)
{
    return idiv64(ip10, 10) * 3 + ip10 % 10;
}

static void upname(char *dst, const char *src)
{
    int i;
    for (i = 0; src[i] && i < 15; i++) {
        char c = src[i];
        dst[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : c;
    }
    dst[i] = 0;
}

static void to_upper(uint8_t *s)
{
    for (; *s; s++)
        if (*s >= 'a' && *s <= 'z') *s = (uint8_t)(*s - 32);
}

static int path_join(char *dst, size_t cap, const char *a, const char *b)
{
    size_t l = strlen(a);
    if (l + 1 + strlen(b) + 1 > cap)
        return 0;                     /* would not fit: caller exits 2 */
    memcpy(dst, a, l);
    if (l > 0 && dst[l - 1] != '/' && dst[l - 1] != '\\')
        dst[l++] = DIR_SEP;
    memcpy(dst + l, b, strlen(b) + 1);
    return 1;
}

static int fit_copy(char *dst, size_t cap, const char *src)
{
    size_t l = strlen(src);
    if (l >= cap)
        return 0;
    memcpy(dst, src, l + 1);
    return 1;
}

static void tmp_of(const char *hpath, char *dst, size_t cap, const char *leaf)
{
    int i, last = -1;
    for (i = 0; hpath[i]; i++)
        if (hpath[i] == '/' || hpath[i] == '\\') last = i;
    if (last < 0) {
        fit_copy(dst, cap, leaf);
    } else if ((size_t)last + 1 + strlen(leaf) + 1 <= cap) {
        memcpy(dst, hpath, (size_t)last + 1);
        dst[last + 1] = 0;
        strcat(dst, leaf);
    }
}

static int cmpname(const void *a, const void *b)
{
    return strcmp((const char *)a, (const char *)b);
}

/* --- *.V20 / *.MAJ listing: upper-cased 8.3 names, sorted (matches Python
 *     sorted() on these names) --- */
#ifdef __WATCOMC__

static int scan_dir(const char *dir, const char *ext, char names[][16])
{
    static char pat[280];
    struct find_t ft;
    int dir_len = (int)strlen(dir);
    int n = 0;
    if (dir_len + 6 + strlen(ext) >= (int)sizeof pat)
        return 0;
    memcpy(pat, dir, (size_t)dir_len);
    if (dir_len > 0 && pat[dir_len - 1] != '\\' && pat[dir_len - 1] != '/')
        pat[dir_len++] = '\\';
    pat[dir_len++] = '*';
    strcpy(pat + dir_len, ext);
    if (_dos_findfirst(pat, _A_NORMAL, &ft) != 0)
        return 0;
    do {
        if (n >= MAXV)
            break;
        upname(names[n], ft.name);
        n++;
    } while (_dos_findnext(&ft) == 0);
    qsort(names, (size_t)n, 16, cmpname);
    return n;
}

#else

static int scan_dir(const char *dir, const char *ext, char names[][16])
{
    DIR *dirp = opendir(dir);
    struct dirent *de;
    size_t el = strlen(ext);
    int n = 0;
    if (!dirp)
        return 0;
    while ((de = readdir(dirp)) != NULL) {
        size_t l = strlen(de->d_name);
        if (l > el && strcmp(de->d_name + (l - el), ext) == 0) {
            if (n >= MAXV)
                break;
            upname(names[n], de->d_name);
            n++;
        }
    }
    closedir(dirp);
    qsort(names, (size_t)n, 16, cmpname);
    return n;
}

#endif

/* ---------------- MAJ ---------------- */

static int32_t park_factor1000(int32_t hrs, int32_t hra, int32_t away_g,
                               int32_t ars, int32_t ara, int32_t home_g)
{
    int32_t dh, da, pf;
    dh = hrs + hra;
    da = ars + ara;
    if (dh == 0 || da == 0 || away_g == 0 || home_g == 0)
        return 1000;
    pf = idiv64((int64_t)1000 * dh * away_g, (int64_t)da * home_g);
    if (pf < 900)
        pf = 900;
    if (pf > 1100)
        pf = 1100;
    return pf;
}

static void compute_pf(const uint8_t *d)
{
    int lg, slot, day;
    for (lg = 0; lg < 2; lg++) {
        int s = lg ? MAJ_S_NL : MAJ_S_AL;
        for (slot = 0; slot < 16; slot++) {
            int32_t lg_id = (lg ? 16 : 0) + slot;
            int32_t hrs = 0, hra = 0, ars = 0, ara = 0;
            int32_t home_g = 0, away_g = 0;
            uint8_t dhmask = d[s + MAJ_O_DHVAL];
            for (day = 0; day < MAJ_DAYS; day++) {
                const uint8_t *row = d + s + MAJ_O_RUNS + 32 * day;
                const uint8_t *row2 = row + 16;
                const uint8_t *sched = d + s + MAJ_O_SCHED + 16 * day;
                uint8_t mask = d[s + MAJ_O_PLAYED + 2 * day];
                uint8_t mask2 = d[s + MAJ_O_PLAYED + 2 * day + 1];
                int si, jog;
                jog = 0;                          /* real-pair index: bit and cell */
                for (si = 0; si < 8; si++) {
                    int away = sched[2 * si];
                    int home = sched[2 * si + 1];
                    int jog0;
                    uint8_t bit;
                    if (away == 0 && home == 0)
                        continue;                 /* dropped pair: slot keeps its bit */
                    jog0 = jog;
                    bit = (uint8_t)(0x80u >> jog0);   /* py enumerate: every real pair */
                    jog++;
                    if (!(mask & bit))
                        continue;
                    if (home == lg_id) {
                        hrs += row[2 * jog0 + 1]; hra += row[2 * jog0]; home_g++;
                    } else if (away == lg_id) {
                        ars += row[2 * jog0]; ara += row[2 * jog0 + 1]; away_g++;
                    }
                    if ((dhmask & bit) && (mask2 & bit)) {
                        if (home == lg_id) {
                            hrs += row2[2 * jog0 + 1]; hra += row2[2 * jog0]; home_g++;
                        } else if (away == lg_id) {
                            ars += row2[2 * jog0]; ara += row2[2 * jog0 + 1]; away_g++;
                        }
                    }
                }
            }
            if (home_g || away_g) {
                g_pf[lg_id] = park_factor1000(hrs, hra, away_g, ars, ara, home_g);
                g_pf_valid[lg_id] = 1;
            }
        }
    }
}

static int32_t pf_of(int32_t lg_id)
{
    return g_pf_valid[lg_id] ? g_pf[lg_id] : 1000;
}

static char g_scan[MAXV][16];
static char g_path[600];

static int read_maj(const char *dir, Maj *m)
{
    char (*names)[16] = g_scan;
    char *path = g_path;
    uint8_t *buf;
    FILE *f;
    size_t n;
    int lg, slot;
    if (scan_dir(dir, ".MAJ", names) < 1)
        return 0;
    path_join(path, 600, dir, names[0]);
    f = fopen(path, "rb");
    if (!f)
        return 0;
    buf = (uint8_t *)malloc(MAJ_SIZE + 1);
    if (!buf) {
        fclose(f);
        return 0;
    }
    n = fread(buf, 1, MAJ_SIZE + 1, f);
    fclose(f);
    if (n != MAJ_SIZE) {
        free(buf);
        return 0;
    }
    m->d = buf;
    for (lg = 0; lg < 2; lg++) {
        int s = lg ? MAJ_S_NL : MAJ_S_AL;
        for (slot = 0; slot < 16; slot++) {
            char tmp[9];
            int j;
            for (j = 0; j < 8; j++)
                tmp[j] = (char)buf[s + MAJ_O_STEM + 8 * slot + j];
            tmp[8] = 0;
            for (j = 0; j < 9; j++) {
                m->stem_raw[lg * 16 + slot][j] = tmp[j];
                if (tmp[j] == 0)
                    break;
            }
            m->stem_raw[lg * 16 + slot][8] = 0;
            strcpy(m->stem_up[lg * 16 + slot], m->stem_raw[lg * 16 + slot]);
            to_upper((uint8_t *)m->stem_up[lg * 16 + slot]);
        }
    }
    m->ws = buf[MAJ_S_AL + 0x3da];
    m->al_p = buf[MAJ_S_AL + 0x3d9];
    m->nl_p = buf[MAJ_S_NL + 0x3d9];
    /* C2 amended: any index >= 32 is unknown (0xff) BEFORE the runner-up rule, so no
     * MAJ byte can index the stem tables out of bounds */
    if (m->ws >= 32)
        m->ws = 0xff;
    if (m->al_p >= 32)
        m->al_p = 0xff;
    if (m->nl_p >= 32)
        m->nl_p = 0xff;
    m->runner = 0xff;
    if (m->ws != 0xff) {
        if (m->al_p == m->ws)
            m->runner = m->nl_p;
        else if (m->nl_p == m->ws)
            m->runner = m->al_p;
    }
    compute_pf(buf);
    return 1;
}

/* ---------------- team files ---------------- */

static int load_v20(const char *path)
{
    FILE *f = fopen(path, "rb");
    size_t n;
    if (!f)
        return 0;
    n = fread(g_v20, 1, (size_t)V20_SIZE, f);
    fclose(f);
    return n == (size_t)V20_SIZE;
}

static uint32_t bat_l(const uint8_t *rec, int off_l, int off_r)
{
    return (uint32_t)(rd16(rec + off_l) + rd16(rec + off_r));
}

/* war.season_stats_inputs (C2 order, 25 values) */
static void stats_inputs(const uint8_t *rec, uint32_t *tot)
{
    tot[0] = (uint32_t)rec[R_GAMES];
    tot[1] = bat_l(rec, R_AB_L, R_AB_R);
    tot[2] = bat_l(rec, R_H_L, R_H_R);
    tot[3] = bat_l(rec, R_D_L, R_D_R);
    tot[4] = (uint32_t)(rec[R_T_L] + rec[R_T_R]);
    tot[5] = (uint32_t)(rec[R_HR_L] + rec[R_HR_R]);
    tot[6] = (uint32_t)rec[R_RUNS];
    tot[7] = (uint32_t)rec[R_RBI];
    tot[8] = bat_l(rec, R_BB_L, R_BB_R);
    tot[9] = bat_l(rec, R_SO_L, R_SO_R);
    tot[10] = (uint32_t)rec[R_SB];
    tot[11] = (uint32_t)rec[R_CS];
    tot[12] = (uint32_t)(rec[R_E1] + rec[R_E2]);
    tot[13] = (uint32_t)rec[R_W];
    tot[14] = (uint32_t)rec[R_L];
    tot[15] = (uint32_t)rec[R_SV];
    tot[16] = (uint32_t)rec[R_GS];
    tot[17] = (uint32_t)rec[R_CG];
    tot[18] = (uint32_t)rec[R_SHO];
    tot[19] = (uint32_t)outs_of(rd16(rec + R_IP10));
    tot[20] = (uint32_t)rd16(rec + R_ER);
    tot[21] = bat_l(rec, R_PH_L, R_PH_R);
    tot[22] = bat_l(rec, R_PBB_L, R_PBB_R);
    tot[23] = bat_l(rec, R_PSO_L, R_PSO_R);
    tot[24] = (uint32_t)(rec[R_PHR_L] + rec[R_PHR_R]);
}

static int16_t batter_war10(const uint8_t *rec, const uint8_t *roster,
                            int32_t games, int32_t pf1000)
{
    int32_t ab = (int32_t)bat_l(rec, R_AB_L, R_AB_R);
    int32_t h = (int32_t)bat_l(rec, R_H_L, R_H_R);
    int32_t d = (int32_t)bat_l(rec, R_D_L, R_D_R);
    int32_t t = rec[R_T_L] + rec[R_T_R];
    int32_t hr = rec[R_HR_L] + rec[R_HR_R];
    int32_t bb = (int32_t)bat_l(rec, R_BB_L, R_BB_R);
    int32_t sb = rec[R_SB], cs = rec[R_CS];
    int32_t s1 = h - d - t - hr;
    int32_t pa = ab + bb;
    int32_t pos1 = roster[R_POS1] & 15;
    int64_t lw100, outv;
    static const int16_t pos100[10] = { 0, 1250, -1250, 300, 250, 750,
                                        -750, 250, -750, -1750 };
    lw100 = (int64_t)47 * s1 + (int64_t)78 * d + (int64_t)109 * t
          + (int64_t)140 * hr + (int64_t)33 * bb + (int64_t)20 * sb
          - (int64_t)41 * cs - (int64_t)27 * (ab - h);
    if (pa > 0 && g_L_pa > 0) {
        int64_t bat100 = lw100 - idiv64((int64_t)g_L_lw * pa, g_L_pa);
        bat100 -= idiv64(idiv64((int64_t)(pf1000 - 1000) * g_L_runs, 20) * pa,
                         g_L_pa);
        outv = bat100 + idiv64((int64_t)2000 * pa, 600);
    } else {
        outv = lw100;
    }
    {
        int32_t padj = (pos1 <= 9) ? pos100[pos1] : 0;
        int32_t rng = roster[R_RANGE] >> 4;
        int32_t arm = roster[R_ARM] & 15;
        int64_t raw = (int64_t)(rng - 6) * 150 + (arm - 6) * 50;
        outv += idiv64((int64_t)padj * games, 162);
        outv += idiv64(raw * games, 162);
    }
    return (int16_t)idiv64(outv, 100);
}

static int16_t pitcher_war10(const uint8_t *rec)
{
    int32_t ip10 = rd16(rec + R_IP10);
    int32_t outs = outs_of(ip10);
    int32_t er = rd16(rec + R_ER);
    int64_t pit100;
    if (g_L_outs == 0 || outs == 0)
        return 0;
    pit100 = idiv64((int64_t)g_L_er * 120 * outs, g_L_outs) - (int64_t)er * 100;
    return (int16_t)idiv64(pit100, 100);
}

/* phase A2: league totals over all mapped teams */
static int league_pass(const char *pre_dir)
{
    int32_t L_lw = 0, L_pa = 0, L_runs = 0, L_er = 0, L_outs = 0;
    char *path = g_path;
    int k, i;
    for (k = 0; k < g_nt; k++) {
        TeamInfo *ti = g_tp[k];
        path_join(path, 600, pre_dir, ti->fname);
        if (!load_v20(path))
            return -1;
        for (i = 0; i < 40; i++) {
            const uint8_t *roster = g_v20 + V20_HDR + V20_REC * i;
            const uint8_t *rec = roster + V20_REC * 40;
            int32_t pos1;
            if (roster[R_ACTIVE] == 0)
                continue;
            pos1 = roster[R_POS1] & 15;
            if (pos1 == 0) {
                int32_t outs = outs_of(rd16(rec + R_IP10));
                if (outs > 0) {
                    L_er += rd16(rec + R_ER);
                    L_outs += outs;
                }
            } else {
                int32_t ab = (int32_t)bat_l(rec, R_AB_L, R_AB_R);
                int32_t h = (int32_t)bat_l(rec, R_H_L, R_H_R);
                int32_t d = (int32_t)bat_l(rec, R_D_L, R_D_R);
                int32_t t = rec[R_T_L] + rec[R_T_R];
                int32_t hr = rec[R_HR_L] + rec[R_HR_R];
                int32_t bb = (int32_t)bat_l(rec, R_BB_L, R_BB_R);
                int32_t sb = rec[R_SB], cs = rec[R_CS];
                int32_t runs = rec[R_RUNS];
                int32_t pa = ab + bb;
                if (pa > 0) {
                    int64_t s1 = h - d - t - hr;
                    int64_t lw100 = (int64_t)47 * s1 + (int64_t)78 * d
                                  + (int64_t)109 * t + (int64_t)140 * hr
                                  + (int64_t)33 * bb + (int64_t)20 * sb
                                  - (int64_t)41 * cs - (int64_t)27 * (ab - h);
                    L_lw += (int32_t)lw100;
                    L_pa += pa;
                    L_runs += runs;
                }
            }
        }
    }
    g_L_lw = L_lw; g_L_pa = L_pa; g_L_runs = L_runs;
    g_L_er = L_er; g_L_outs = L_outs;
    return 0;
}

/* ---------------- identity hash ---------------- */

static uint32_t hvalue(const uint8_t *name, uint16_t birth)
{
    uint32_t h = 2166136261u;
    int i;
    for (i = 0; i < 20; i++) {
        h ^= name[i];
        h *= 16777619u;
    }
    h ^= (uint8_t)(birth & 0xffu);
    h *= 16777619u;
    h ^= (uint8_t)(birth >> 8);
    h *= 16777619u;
    return h;
}

static const CurPlayer *cur_of(int32_t ref)
{
    return &g_tp[(int)(ref >> 8)]->cur[(int)(ref & 255)];
}

static int slot_ident(int32_t s, const uint8_t *name, uint16_t birth)
{
    const CurPlayer *cp = cur_of(g_slots[s].first_cur);
    return memcmp(cp->name, name, 20) == 0 && cp->birth == birth;
}

static int32_t hash_find(const uint8_t *name, uint16_t birth)
{
    uint32_t b = hvalue(name, birth) & (uint32_t)(HASH_BUCKETS - 1);
    int32_t s;
    for (s = g_hhead[b]; s >= 0; s = g_slots[s].next)
        if (slot_ident(s, name, birth))
            return s;
    return -1;
}

static void hash_add(int32_t ref, const uint8_t *name, uint16_t birth)
{
    uint32_t b = hvalue(name, birth) & (uint32_t)(HASH_BUCKETS - 1);
    int32_t s;
    for (s = g_hhead[b]; s >= 0; s = g_slots[s].next) {
        if (slot_ident(s, name, birth)) {
            int32_t c = g_slots[s].first_cur;
            CurPlayer *cp;
            for (;;) {
                cp = (CurPlayer *)cur_of(c);
                if (cp->next_dup < 0)
                    break;
                c = cp->next_dup;
            }
            cp->next_dup = ref;
            return;
        }
    }
    s = g_nslots++;
    g_slots[s].first_cur = ref;
    g_slots[s].entry_index = -1;
    g_slots[s].next = g_hhead[b];
    g_hhead[b] = s;
}

/* phase A3: current-player lists + hash (league order) */
static int player_pass(const char *pre_dir)
{
    char *path = g_path;
    int k, i;
    for (k = 0; k < g_nt; k++) {
        TeamInfo *ti = g_tp[k];
        path_join(path, 600, pre_dir, ti->fname);
        if (!load_v20(path))
            return -1;
        ti->ncur = 0;
        for (i = 0; i < 40; i++) {
            const uint8_t *roster = g_v20 + V20_HDR + V20_REC * i;
            const uint8_t *rec = roster + V20_REC * 40;
            CurPlayer *cp;
            int32_t games, age, pos1;
            if (roster[R_ACTIVE] == 0)
                continue;
            cp = &ti->cur[ti->ncur];
            ti->ncur++;
            games = rec[R_GAMES];
            age = roster[R_AGE];
            pos1 = roster[R_POS1] & 15;
            memcpy(cp->name, roster, 20);
            cp->birth = (uint16_t)(1000 + g_season_no - age);
            cp->games = (uint16_t)games;
            cp->age = (uint8_t)age;
            cp->pos1 = (uint8_t)pos1;
            cp->next_dup = -1;
            stats_inputs(rec, cp->tot);
            cp->w10 = (pos1 == 0)
                    ? pitcher_war10(rec)
                    : batter_war10(rec, roster, games, pf_of(ti->lg_slot));
            if (g_nslots < g_slots_cap)
                hash_add(((int32_t)k << 8) | (ti->ncur - 1), cp->name, cp->birth);
        }
    }
    return 0;
}

/* ---------------- history entries ---------------- */

static void fresh_entry(uint8_t *eb, const CurPlayer *p)
{
    int i;
    memset(eb, 0, PLAYER_ENTRY);
    memcpy(eb, p->name, 20);
    wr16(eb + 20, p->birth);
    eb[22] = STATUS_ACTIVE;
    eb[23] = p->age;
    wr16(eb + 24, g_season_no);
    wr16(eb + 26, g_season_no);
    wr16(eb + 28, 0);
    eb[30] = p->pos1;
    eb[31] = (p->pos1 == 0) ? 1 : 0;
    wr16(eb + 132, 0);
    for (i = 0; i < 7; i++)
        wr16(eb + 134 + 2 * i, (uint16_t)EMPTY_TOP);
    wr16(eb + 148, 0);
    wr16(eb + 150, 0);
}

/* every current player with the slot's identity, in league order */
static void apply_chain(int32_t s, uint8_t *eb)
{
    int32_t c = g_slots[s].first_cur;
    while (c >= 0) {
        const CurPlayer *p = cur_of(c);
        int32_t k;
        for (k = 0; k < NUM_TOT; k++)
            wr32(eb + 32 + 4 * k, rd32(eb + 32 + 4 * k) + p->tot[k]);
        eb[22] = STATUS_ACTIVE;
        eb[23] = p->age;
        wr16(eb + 26, g_season_no);
        if (p->games > 0)
            wr16(eb + 28, (uint16_t)(rd16(eb + 28) + 1u));
        eb[30] = p->pos1;
        eb[31] = (p->pos1 == 0) ? 1 : 0;
        wr16(eb + 132, (uint16_t)(rd16s(eb + 132) + p->w10));
        {
            int32_t a[8];
            int32_t idx, j;
            for (idx = 0; idx < 7; idx++)
                a[idx] = rd16s(eb + 134 + 2 * idx);
            a[7] = p->w10;
            for (idx = 1; idx < 8; idx++) {
                int32_t v = a[idx];
                for (j = idx - 1; j >= 0 && a[j] < v; j--)
                    a[j + 1] = a[j];
                a[j + 1] = v;
            }
            for (idx = 0; idx < 7; idx++)
                wr16(eb + 134 + 2 * idx, (uint16_t)a[idx]);
        }
        {
            int64_t sum = rd16s(eb + 132);
            int32_t idx;
            for (idx = 0; idx < 7; idx++) {
                int32_t v = rd16s(eb + 134 + 2 * idx);
                if (v != EMPTY_TOP)
                    sum += v;
            }
            wr16(eb + 148, (uint16_t)idiv64(sum, 2));
        }
        memset(eb + 152, 0, 8);
        c = p->next_dup;
    }
}

static void write_season_entry(uint16_t season_no, const Maj *m)
{
    uint32_t o = SEASON_TABLE + (uint32_t)(season_no - 1) * SEASON_ENTRY;
    uint8_t wl_w[32], wl_l[32];
    int lg, slot, i;
    memset(wl_w, 0, 32);
    memset(wl_l, 0, 32);
    for (lg = 0; lg < 2; lg++) {
        int s = lg ? MAJ_S_NL : MAJ_S_AL;
        for (slot = 0; slot < 16; slot++) {
            uint8_t w = m->d[s + MAJ_O_W + slot];
            uint8_t l = m->d[s + MAJ_O_L + slot];
            if (w || l) {
                wl_w[lg * 16 + slot] = w;
                wl_l[lg * 16 + slot] = l;
            }
        }
    }
    wr16(g_tab + o, season_no);
    g_tab[o + 2] = m->ws;
    g_tab[o + 3] = m->runner;
    memset(g_tab + o + 4, 0, 8);
    memset(g_tab + o + 12, 0, 8);
    if (m->ws != 0xff)
        for (i = 0; i < 8 && m->stem_raw[m->ws][i]; i++)
            g_tab[o + 4 + i] = (uint8_t)m->stem_raw[m->ws][i];
    if (m->runner != 0xff)
        for (i = 0; i < 8 && m->stem_raw[m->runner][i]; i++)
            g_tab[o + 12 + i] = (uint8_t)m->stem_raw[m->runner][i];
    g_tab[o + 20] = m->al_p;
    g_tab[o + 21] = m->nl_p;
    g_tab[o + 22] = 0;
    g_tab[o + 23] = 0;
    for (i = 0; i < 32; i++) {
        g_tab[o + 24 + 2 * i] = wl_w[i];
        g_tab[o + 25 + 2 * i] = wl_l[i];
    }
    memset(g_tab + o + 88, 0, 40);
}

static int hof_passes(const uint8_t *eb)
{
    if (rd16(eb + 28) < 10)
        return 0;
    if (rd32(eb + 32 + 4 * TOT_H) >= 3000)
        return 1;
    if (rd32(eb + 32 + 4 * TOT_HR) >= 500)
        return 1;
    {
        uint32_t ab = rd32(eb + 32 + 4 * TOT_AB);
        if (ab >= 5000
            && idiv64((int64_t)rd32(eb + 32 + 4 * TOT_H) * 1000, ab) >= 300)
            return 1;
    }
    if (rd32(eb + 32 + 4 * TOT_W) >= 300)
        return 1;
    if (rd32(eb + 32 + 4 * TOT_PSO) >= 3000)
        return 1;
    if (rd32(eb + 32 + 4 * TOT_SV) >= 400)
        return 1;
    if (rd16s(eb + 132) >= 600)
        return 1;
    if (rd16s(eb + 148) >= 500)
        return 1;
    return 0;
}

/* RETIRED.DAT: u8 nteam, then nteam x (13 B name + 40 B flags) */
static int load_retired(const char *rpath, RetTeam **out)
{
    FILE *f = fopen(rpath, "rb");
    int c, n, t;
    RetTeam *rt;
    *out = NULL;
    if (!f)
        return 0;
    c = fgetc(f);
    if (c == EOF) {
        fclose(f);
        return 0;
    }
    n = c;
    if (n <= 0) {
        fclose(f);
        return 0;
    }
    rt = (RetTeam *)calloc((size_t)n, sizeof(RetTeam));
    if (!rt) {
        fclose(f);
        return -1;
    }
    for (t = 0; t < n; t++) {
        static uint8_t raw[53];
        size_t got;
        int j;
        memset(raw, 0, sizeof raw);
        got = fread(raw, 1, sizeof raw, f);
        (void)got;
        for (j = 0; j < 13; j++) {
            if (raw[j] == 0)
                break;
            if (j < 12)
                rt[t].name[j] = (char)raw[j];
        }
        if (j == 13)
            rt[t].name[12] = 0;
        else
            rt[t].name[j] = 0;
        memcpy(rt[t].flags, raw + 13, 40);
        rt[t].team_ix = -1;
        for (j = 0; j < g_nt; j++) {
            if (strcmp(rt[t].name, g_tp[j]->fname) == 0) {
                rt[t].team_ix = j;
                break;
            }
        }
    }
    fclose(f);
    *out = rt;
    return n;
}

/* mark_retired on the already-written temp file */
static int do_marks(const char *pre_dir, const char *tmp, const RetTeam *rt, int nrt)
{
    FILE *g = fopen(tmp, "r+b");
    char *path = g_path;
    static uint8_t eb[PLAYER_ENTRY];
    int t, i;
    if (!g)
        return -1;
    for (t = 0; t < nrt; t++) {
        if (rt[t].team_ix < 0)
            continue;
        path_join(path, 600, pre_dir, g_tp[rt[t].team_ix]->fname);
        if (!load_v20(path)) {
            fclose(g);
            return -1;
        }
        for (i = 0; i < 40; i++) {
            const uint8_t *roster = g_v20 + V20_HDR + V20_REC * i;
            uint16_t birth;
            int32_t s;
            long off;
            if (!rt[t].flags[i])
                continue;
            if (roster[R_ACTIVE] == 0)
                continue;
            birth = (uint16_t)(1000 + g_season_no - roster[R_AGE]);
            s = hash_find(roster, birth);
            if (s < 0 || g_slots[s].entry_index < 0)
                continue;
            off = (long)PLAYER_TABLE + (long)g_slots[s].entry_index * PLAYER_ENTRY;
            if (fseek(g, off, SEEK_SET) != 0)
                goto fail;
            if (fread(eb, 1, PLAYER_ENTRY, g) != (size_t)PLAYER_ENTRY)
                goto fail;
            eb[22] = STATUS_RETIRED;
            if (hof_passes(eb)) {
                eb[22] = STATUS_HOF;
                wr16(eb + 150, g_season_no);
            }
            memset(eb + 152, 0, 8);
            if (fseek(g, off, SEEK_SET) != 0)
                goto fail;
            if (fwrite(eb, 1, PLAYER_ENTRY, g) != (size_t)PLAYER_ENTRY)
                goto fail;
        }
    }
    if (fclose(g) != 0)
        return -1;
    return 0;
fail:
    fclose(g);
    return -1;
}

/* phase B: stream old entries, append new, write, then mark */
static const char *bak_of(const char *hpath, char *dst, size_t cap);

static int do_run(const char *pre_dir, const char *hpath)
{
    FILE *f = NULL, *g = NULL;
    long old_len = 0, remaining = 0;
    uint16_t sr_raw, season_no, sr_new;
    static char tmp[600], bak[600];
    uint32_t out_index = 0;
    static uint8_t eb[PLAYER_ENTRY];
    int32_t s;
    int nrt;
    RetTeam *rt = NULL;
    int swapped = 0;

    f = fopen(hpath, "rb");
    if (f) {
        if (fseek(f, 0, SEEK_END) != 0)
            goto fail;
        old_len = ftell(f);
        if (old_len < 0)
            goto fail;
    }
    memset(g_tab, 0, sizeof g_tab);
    if (f && old_len > 0) {
        size_t want = old_len < (long)sizeof g_tab
                    ? (size_t)old_len : sizeof g_tab;
        if (fseek(f, 0, SEEK_SET) != 0)
            goto fail;
        if (fread(g_tab, 1, want, f) != want)
            goto fail;
    }
    sr_raw = rd16(g_tab + 4);
    season_no = (uint16_t)(((f && old_len >= 6) ? sr_raw : 0) + 1);
    g_season_no = season_no;
    if (season_no <= SEASON_COUNT)
        write_season_entry(season_no, &g_maj);
    g_tab[3] = VERSION_ONE;

    tmp_of(hpath, tmp, 600, TMP_NAME);
    g = fopen(tmp, "wb");
    if (!g)
        goto fail;
    if (fwrite(g_tab, 1, sizeof g_tab, g) != sizeof g_tab)
        goto fail;

    if (f && old_len > (long)PLAYER_TABLE) {
        if (fseek(f, PLAYER_TABLE, SEEK_SET) != 0)
            goto fail;
        remaining = old_len - (long)PLAYER_TABLE;
    }
    while (remaining >= PLAYER_ENTRY) {
        int32_t h;
        if (fread(eb, 1, PLAYER_ENTRY, f) != (size_t)PLAYER_ENTRY)
            goto fail;
        h = hash_find(eb, rd16(eb + 20));
        if (h >= 0) {
            g_slots[h].entry_index = (int32_t)out_index;
            apply_chain(h, eb);
        }
        if (fwrite(eb, 1, PLAYER_ENTRY, g) != (size_t)PLAYER_ENTRY)
            goto fail;
        out_index++;
        remaining -= PLAYER_ENTRY;
    }
    if (remaining > 0) {
        static uint8_t tail[PLAYER_ENTRY];
        if (fread(tail, 1, (size_t)remaining, f) != (size_t)remaining)
            goto fail;
        if (fwrite(tail, 1, (size_t)remaining, g) != (size_t)remaining)
            goto fail;
    }
    for (s = 0; s < g_nslots; s++) {
        if (g_slots[s].entry_index >= 0)
            continue;
        fresh_entry(eb, cur_of(g_slots[s].first_cur));
        g_slots[s].entry_index = (int32_t)out_index;
        apply_chain(s, eb);
        if (fwrite(eb, 1, PLAYER_ENTRY, g) != (size_t)PLAYER_ENTRY)
            goto fail;
        out_index++;
    }

    sr_new = (sr_raw > season_no) ? sr_raw : season_no;
    wr16(g_tab + 4, sr_new);
    wr16(g_tab + 6, (uint16_t)out_index);
    g_tab[0] = 1;
    if (fseek(g, 0, SEEK_SET) != 0)
        goto fail;
    if (fwrite(g_tab, 1, HDR_SIZE, g) != (size_t)HDR_SIZE)
        goto fail;
    if (fclose(g) != 0) {
        g = NULL;
        goto fail;
    }
    g = NULL;

    nrt = load_retired(g_retpath, &rt);
    if (nrt < 0)
        goto fail;
    if (nrt > 0 && do_marks(pre_dir, tmp, rt, nrt) != 0)
        goto fail;
    if (rt)
        free(rt);
    if (f)
        fclose(f);
    /* swap in the temp file without ever leaving HIST_PATH missing:
     * old -> HISTWR.BAK (stale BAK removed first), temp -> HIST_PATH, BAK back on
     * failure, BAK dropped on success */
    swapped = 0;
    bak[0] = 0;
    {
        FILE *probe = fopen(hpath, "rb");
        if (probe) {
            fclose(probe);
            bak_of(hpath, bak, sizeof bak);
            remove(bak);
            if (rename(hpath, bak) == 0)
                swapped = 1;
            else
                bak[0] = 0;           /* no backup: hpath still in place */
        }
    }
#ifdef TEST_FAIL_RENAME
    /* host-only test build: pretend the second rename failed, exercise the restore */
    remove(tmp);
    if (swapped)
        rename(bak, hpath);           /* put the old file back: HIST_PATH unchanged */
    return 2;
#else
    if (rename(tmp, hpath) != 0) {
        remove(tmp);
        if (swapped)
            rename(bak, hpath);       /* put the old file back: HIST_PATH unchanged */
        return 2;
    }
#endif
    if (swapped)
        remove(bak);
    return 0;
fail:
    if (g)
        fclose(g);
    if (f)
        fclose(f);
    tmp_of(hpath, tmp, 600, TMP_NAME);
    remove(tmp);
    return 2;
}

static const char *bak_of(const char *hpath, char *dst, size_t cap)
{
    tmp_of(hpath, dst, cap, BAK_NAME);
    return dst;
}

int main(int argc, char **argv)
{
    const char *pre, *hpath, *rpath;
    int nv, k, rc;
    if (argc >= 4) {
        pre = argv[1];
        hpath = argv[2];
        rpath = argv[3];
    } else {
        pre = DEF_PRE;
        hpath = DEF_HIST;
        rpath = DEF_RET;
    }
    if (!fit_copy(g_retpath, sizeof g_retpath, rpath))
        return 2;                     /* RETIRED path too long */
    if (strlen(hpath) >= 600 || strlen(pre) >= 600)
        return 2;                     /* HIST/PRE path too long for built paths */
    if (!read_maj(pre, &g_maj))
        return 2;
    nv = scan_dir(pre, ".V20", g_names);
    for (k = 0; k < nv; k++) {
        static char stem[16];
        int lg, slot, lg_slot = -1;
        size_t l = strlen(g_names[k]);
        TeamInfo *ti;
        if (l <= 4 || l - 4 > 12)
            continue;
        memcpy(stem, g_names[k], l - 4);
        stem[l - 4] = 0;
        to_upper((uint8_t *)stem);
        for (lg = 0; lg < 2; lg++) {
            for (slot = 0; slot < 16; slot++) {
                if (strcmp(stem, g_maj.stem_up[lg * 16 + slot]) == 0)
                    lg_slot = lg * 16 + slot;
            }
        }
        if (lg_slot < 0)
            continue;
        ti = (TeamInfo *)calloc(1, sizeof(TeamInfo));
        if (!ti)
            return 2;
        strcpy(ti->fname, g_names[k]);
        ti->lg_slot = (uint8_t)lg_slot;
        ti->ncur = 0;
        if (g_nt < MAXV)
            g_tp[g_nt++] = ti;
        else
            free(ti);
    }
    {
        int32_t ncap = (int32_t)g_nt * 40;
        g_slots = NULL;
        g_slots_cap = 0;
        if (ncap > 0) {
            g_slots = (Slot *)calloc((size_t)ncap, sizeof(Slot));
            if (!g_slots)
                return 2;
            g_slots_cap = ncap;
        }
    }
    for (k = 0; k < HASH_BUCKETS; k++)
        g_hhead[k] = -1;
    {
        int saved = g_nt;
        uint16_t saved_season = g_season_no;
            if (league_pass(pre) != 0)
            return 2;
        /* season_no needs the old history header, read here: */
        {
            FILE *f = fopen(hpath, "rb");
            static uint8_t h[HDR_SIZE];
            long len = 0;
            if (f) {
                if (fseek(f, 0, SEEK_END) == 0)
                    len = ftell(f);
                if (len >= 6) {
                    if (fseek(f, 0, SEEK_SET) == 0
                        && fread(h, 1, 6, f) == 6) {
                        saved_season =
                            (uint16_t)((h[4] | (h[5] << 8)) + 1);
                    } else {
                        saved_season = 1;
                    }
                } else {
                    saved_season = 1;
                }
                fclose(f);
            } else {
                saved_season = 1;
            }
        }
        g_nt = saved;
        g_season_no = saved_season;
    }
    if (player_pass(pre) != 0)
        return 2;
    rc = do_run(pre, hpath);
    if (rc != 0)
        return rc;
    return 0;
}
