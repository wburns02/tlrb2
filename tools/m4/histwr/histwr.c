/* HISTWR: C port of history.record_season + mark_retired (notes/M4_CONTRACT.md
 * C5, C7). Builds on the host with gcc for parity tests and in DOS with
 * OpenWatcom (large model). Streams player entries from HIST_PATH to HISTWR.TMP
 * beside it; never holds the whole player table in memory. C7: awards (season
 * entry bytes 88..99, player entry award counts 152..156) and MILESTON.DAT
 * beside HISTORY.DAT. C13.2: SEASLINE.DAT beside HISTORY.DAT (one 80 B line per active record
 * per season); HISTWR /LINES backfills it from the season archives.
 * C16.2: HISTWR /SNAP copies the current league's dir into its snap dir; HISTWR /ARCHIVE copies the snap
 * into the first free season slot. The no-argument paths are the current league's (league.h, C16.1).
 * usage: HISTWR [PRE_DIR HIST_PATH RETIRED_PATH]
 *        HISTWR /LINES [HIST_PATH SEASONS_DIR]
 *        HISTWR /SNAP [LEAGUE_DIR SNAP_DIR]
 *        HISTWR /ARCHIVE [SNAP_DIR SEASONS_DIR]
 * exit 0 on success, 2 after any error (HIST_PATH left unchanged). /SNAP and /ARCHIVE exit 1 when a
 * directory cannot be made or listed or a copy fails.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#ifdef __WATCOMC__
#include <dos.h>
#include <direct.h>
#define DIR_SEP '\\'
#define MK_DIR(p) mkdir(p)
#else
#include <dirent.h>
#include <sys/stat.h>
#define DIR_SEP '/'
#define MK_DIR(p) mkdir((p), 0777)
#endif

/* teamids.h has helpers this file does not call; gcc -Werror would stop on them */
#if defined(__GNUC__) && !defined(__WATCOMC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#endif
#include "../teamids.h"
#if defined(__GNUC__) && !defined(__WATCOMC__)
#pragma GCC diagnostic pop
#endif

#include "../league.h"

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
#define MS_NAME        "MILESTON.DAT"
#define MS_TMP_NAME    "MILESTON.TMP"
#define MS_BAK_NAME    "MILESTON.BAK"
#define BOX_NAME       "BOXSCORE.DAT"
#define BOX_TMP_NAME   "BOXSCORE.TMP"
#define BOX_BAK_NAME   "BOXSCORE.BAK"
#define SL_NAME        "SEASLINE.DAT"
#define SL_TMP_NAME    "SEASLINE.TMP"
#define SL_BAK_NAME    "SEASLINE.BAK"
#define SL_HDR         16
#define SL_LINE        80
#define SWAP_N         4              /* HISTORY, MILESTON, BOXSCORE, SEASLINE */
#define RUN_PATHS      11             /* PATH_CAP blocks of a run: 2 history, 3 milestone, 3 box, 3 seasline */
#define BOX_REC        16
#define NO_AWARD       0xffff
#define NO_ENTRY       0xffff
#define PATH_CAP       600
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
#define R_EXP    0x16
#define R_PO1    0x4d
#define R_A1     0x51
#define R_PORTRAIT 0x1b
#define R_SPEED  0x1d
#define R_B29    29
#define R_POWER  0x4a
#define R_HITRUN 0x4b
#define R_CONTROL 0x86
#define R_ENDUR  0x87
#define R_DEV    142

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
#define TOT_RBI 7
#define TOT_BB 8
#define TOT_SB 10
#define TOT_W 13
#define TOT_SV 15
#define TOT_OUTS 19
#define TOT_ER 20
#define TOT_PSO 23

#define ARCH_MAX 99
#define PATH_BUF 128                   /* the /SNAP and /ARCHIVE paths: every path buffer of them */
#define CP_MAX   256                   /* regular files one /SNAP or /ARCHIVE copy handles */
#define CP_NAME  16                    /* 8.3 names on DOS; host names up to 15 bytes */
#ifdef __WATCOMC__
#define FARDATA __far
#else
#define FARDATA
#endif

typedef struct {
    uint8_t *d;
    char stem_raw[32][9];           /* by stable id (C12.3), empty when no team */
    char stem_up[32][9];
    uint8_t ws, runner, al_p, nl_p;
    uint8_t table[TI_TABLE_SIZE];   /* TEAMID.DAT of the MAJ's dir, when have_table */
    int have_table;
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
    /* C7 award inputs (season, per record; chain records overwrite) */
    uint8_t exp;
    uint32_t outs;
    uint32_t ab;
    int32_t bat100;                 /* batters only: lw100 - (L_lw*pa)/L_pa - park100 */
    uint8_t rng, arm;
    uint16_t po1, a1, e1;
    uint8_t rec_no;                 /* V20 record number (the box rows key) */
    int32_t entry_index;            /* player entry index of its slot (box rows) */
} CurPlayer;

typedef struct {
    char fname[16];
    uint8_t lg_slot;
    uint16_t ncur;
    CurPlayer cur[40];
} TeamInfo;

/* C7 milestone career-total keys, as TOT indexes (H, HR, RBI, SB, W, SV, PSO) */
#define MS_KEYS 7
static const uint8_t ms_tot[MS_KEYS] = {
    TOT_H, TOT_HR, TOT_RBI, TOT_SB, TOT_W, TOT_SV, TOT_PSO };
/* MILESTONE_CAREER (kind, ms-key index, mark) */
static const int16_t ms_career[][3] = {
    { 1, 0, 2000 }, { 2, 0, 3000 }, { 3, 1, 300 }, { 4, 1, 400 },
    { 5, 1, 500 }, { 6, 1, 600 }, { 7, 1, 700 }, { 8, 2, 1500 },
    { 9, 2, 2000 }, { 10, 3, 500 }, { 11, 4, 200 }, { 12, 4, 300 },
    { 13, 6, 2000 }, { 14, 6, 3000 }, { 15, 6, 4000 },
    { 16, 5, 300 }, { 17, 5, 400 } };
#define MS_CAREER_N 17

typedef struct {
    int32_t first_cur;
    int32_t entry_index;
    int32_t next;
} Slot;

/* C7 award candidate: one named record. Compact: a single array of these
 * must stay under the DOS 64 KB allocation limit (G_ncaps ~1120). The
 * milestone before/after is computed at emit time from the written entry
 * totals minus the record's season totals. */
typedef struct {
    int32_t ref;                    /* ((team << 8) | rec) */
    int32_t slot;                   /* identity slot owning this record */
    int32_t idx;                    /* player entry index (-1 until assigned) */
    int32_t bat100;
    int16_t w10;
    uint16_t pa, outs, ab, h, er;
    uint16_t s_h, s_hr, s_sb, s_rbi, s_w, s_sv, s_pso;   /* season stats */
    uint16_t po1, a1;
    uint8_t league;                 /* 0 AL, 1 NL */
    uint8_t pos1, exp, games;
    uint8_t rng, arm, e1;
} Cand;

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
static Cand *g_cands;
static int32_t g_ncands, g_cands_cap;
/* /LINES (C13.2 backfill): the archive being read goes in g_maj (series_id reads it), the Snn subdirs by nn, the archives that hold a
 * MAJ in nn order, the season -> archive match, and the directory listing scratch */
static char FARDATA g_adir[600];
static char FARDATA g_snn[100][16];
static char FARDATA g_arch[ARCH_MAX][16];
static int g_arch_cnt;
static int FARDATA g_arch_sel[SEASON_COUNT + 1];
static char FARDATA g_mnames[MAXV][16];
static uint8_t FARDATA g_line[SL_LINE];
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

/* war.park_factors: per MAJ team (C12.3 stable id k), its engine id (the team byte of the
 * schedule pairs, C12.1) is matched in its league's block */
static void compute_pf(const uint8_t *d, const uint8_t *tab)
{
    TiTeam t[TI_MAX_TEAMS];
    int nd, nt, ti, day;
    nd = ti_ndiv(d, MAJ_SIZE);
    nt = ti_teams(d, MAJ_SIZE, tab, t);
    for (ti = 0; ti < nt; ti++) {
        int lg = t[ti].L;
        int s = lg ? MAJ_S_NL : MAJ_S_AL;
        int32_t lg_id = t[ti].id;
        int eng = ti_slot_to_engine(lg, t[ti].slot, nd);
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
                if (home == eng) {
                    hrs += row[2 * jog0 + 1]; hra += row[2 * jog0]; home_g++;
                } else if (away == eng) {
                    ars += row[2 * jog0]; ara += row[2 * jog0 + 1]; away_g++;
                }
                if ((dhmask & bit) && (mask2 & bit)) {
                    if (home == eng) {
                        hrs += row2[2 * jog0 + 1]; hra += row2[2 * jog0]; home_g++;
                    } else if (away == eng) {
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

static int32_t pf_of(int32_t lg_id)
{
    return g_pf_valid[lg_id] ? g_pf[lg_id] : 1000;
}

static char g_scan[MAXV][16];
static char g_path[600];

/* TEAMID.DAT of dir (any case in the listing, C12.3) into tab when it is exactly 256 B: 1 when
 * loaded, else 0 (the table is then not used) */
static int load_table(const char *dir, uint8_t *tab)
{
    static char names[MAXV][16];
    char path[600];
    FILE *f;
    int n, i, ok = 0;
    n = scan_dir(dir, ".DAT", names);
    for (i = 0; i < n; i++)
        if (strcmp(names[i], "TEAMID.DAT") == 0)
            break;
    if (i == n)
        return 0;
    if (!path_join(path, 600, dir, names[i]))
        return 0;
    f = fopen(path, "rb");
    if (!f)
        return 0;
    if (fseek(f, 0, SEEK_END) == 0 && ftell(f) == TI_TABLE_SIZE
        && fseek(f, 0, SEEK_SET) == 0
        && fread(tab, 1, TI_TABLE_SIZE, f) == TI_TABLE_SIZE)
        ok = 1;
    fclose(f);
    return ok;
}

static int read_maj(const char *dir, Maj *m)
{
    char (*names)[16] = g_scan;
    char *path = g_path;
    uint8_t *buf;
    FILE *f;
    size_t n;
    const uint8_t *tab;
    TiTeam t[TI_MAX_TEAMS];
    int nt, i, j;
    uint8_t t0, t1;
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
    m->have_table = load_table(dir, m->table);
    tab = m->have_table ? m->table : NULL;
    /* stems by stable id (C12.3): every MAJ team's stem cut at its first NUL */
    memset(m->stem_raw, 0, sizeof m->stem_raw);
    memset(m->stem_up, 0, sizeof m->stem_up);
    nt = ti_teams(buf, MAJ_SIZE, tab, t);
    for (i = 0; i < nt; i++) {
        int k = t[i].id;
        for (j = 0; j < 8 && t[i].stem[j]; j++)
            m->stem_raw[k][j] = (char)t[i].stem[j];
        m->stem_raw[k][j] = 0;
        strcpy(m->stem_up[k], m->stem_raw[k]);
        to_upper((uint8_t *)m->stem_up[k]);
    }
    /* C2 amended 2026-10-08: WS teams AL S+0x3d9 / S+0x3da, their wins S+0x3e1 / S+0x3e2;
     * the winner is the side with more wins, a tie is unknown. C12.3: every engine id
     * is read as its stable id (0xff for no team, 32 and up included) */
    t0 = (uint8_t)ti_id_of_engine(buf, MAJ_SIZE, tab, buf[MAJ_S_AL + 0x3d9]);
    t1 = (uint8_t)ti_id_of_engine(buf, MAJ_SIZE, tab, buf[MAJ_S_AL + 0x3da]);
    m->al_p = (uint8_t)ti_id_of_engine(buf, MAJ_SIZE, tab, buf[MAJ_S_AL + 0x3d9]);
    m->nl_p = (uint8_t)ti_id_of_engine(buf, MAJ_SIZE, tab, buf[MAJ_S_NL + 0x3d9]);
    if (buf[MAJ_S_AL + 0x3e1] > buf[MAJ_S_AL + 0x3e2])
        m->ws = t0;
    else if (buf[MAJ_S_AL + 0x3e2] > buf[MAJ_S_AL + 0x3e1])
        m->ws = t1;
    else
        m->ws = 0xff;
    m->runner = 0xff;
    if (m->ws != 0xff) {
        if (m->al_p == m->ws)
            m->runner = m->nl_p;
        else if (m->nl_p == m->ws)
            m->runner = m->al_p;
    }
    compute_pf(buf, tab);
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

/* war.batter_bat100 (C3): lw100 - (L_lw * pa) / L_pa - park100.
 * pa == 0 batters: lw100 (park100 = 0, the C3 amendment); L_pa == 0: no division. */
static int32_t batter_bat100(const uint8_t *rec, int32_t pf1000)
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
    int64_t lw100 = (int64_t)47 * s1 + (int64_t)78 * d + (int64_t)109 * t
                  + (int64_t)140 * hr + (int64_t)33 * bb + (int64_t)20 * sb
                  - (int64_t)41 * cs - (int64_t)27 * (ab - h);
    if (pa > 0 && g_L_pa > 0) {
        int32_t bat100 = (int32_t)(lw100 - idiv64((int64_t)g_L_lw * pa, g_L_pa));
        bat100 -= idiv64(idiv64((int64_t)(pf1000 - 1000) * g_L_runs, 20) * pa,
                         g_L_pa);
        return bat100;
    }
    return (int32_t)lw100;
}

/* history.gold_glove_fp1000: 1000 if the denominator is 0 */
static int32_t gg_fp1000(int32_t po1, int32_t a1, int32_t e1)
{
    int32_t den = po1 + a1 + e1;
    if (den == 0)
        return 1000;
    return idiv64((int64_t)(po1 + a1) * 1000, den);
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
            cp->exp = roster[R_EXP];
            cp->rng = (uint8_t)(roster[R_RANGE] >> 4);
            cp->arm = (uint8_t)(roster[R_ARM] & 15);
            cp->po1 = rd16(rec + R_PO1);
            cp->a1 = rd16(rec + R_A1);
            cp->e1 = rec[R_E1];
            cp->rec_no = (uint8_t)i;
            cp->entry_index = NO_ENTRY;
            cp->outs = (uint32_t)outs_of(rd16(rec + R_IP10));
            cp->ab = bat_l(rec, R_AB_L, R_AB_R);
            cp->bat100 = (pos1 == 0)
                       ? 0 : batter_bat100(rec, pf_of(ti->lg_slot));
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
    memset(eb + 152, 0, 8);
}

/* team index from a TeamInfo pointer */
static int32_t team_ix(const TeamInfo *ti)
{
    int32_t k;
    for (k = 0; k < g_nt; k++)
        if (g_tp[k] == ti)
            return k;
    return -1;
}

/* propagate a slot's player entry index to its collected candidates */
static void slots_assign(int32_t s, int32_t idx)
{
    int32_t ci;
    for (ci = 0; ci < g_ncands; ci++)
        if (g_cands[ci].slot == s)
            g_cands[ci].idx = idx;
}

/* add the C7 award candidate for the incumbent record (record rt of team ti)
 * with its milestone before/after career totals */
static void cand_collect(TeamInfo *ti, int rt, int32_t slot)
{
    const CurPlayer *p = &ti->cur[rt];
    Cand *cd;
    if (g_ncands >= g_cands_cap)
        return;
    cd = &g_cands[g_ncands++];
    cd->ref = (team_ix(ti) << 8) | rt;
    cd->slot = slot;
    cd->idx = -1;
    cd->w10 = p->w10;
    cd->bat100 = p->bat100;
    cd->pa = (uint16_t)(p->ab + p->tot[TOT_BB]);
    cd->outs = (uint16_t)p->outs;
    cd->ab = (uint16_t)p->ab;
    cd->h = (uint16_t)p->tot[TOT_H];
    cd->er = (uint16_t)p->tot[TOT_ER];
    cd->s_h = (uint16_t)p->tot[TOT_H];
    cd->s_hr = (uint16_t)p->tot[TOT_HR];
    cd->s_sb = (uint16_t)p->tot[TOT_SB];
    cd->s_w = (uint16_t)p->tot[TOT_W];
    cd->s_sv = (uint16_t)p->tot[TOT_SV];
    cd->s_pso = (uint16_t)p->tot[TOT_PSO];
    cd->league = (ti->lg_slot < 16) ? 0 : 1;
    cd->pos1 = p->pos1;
    cd->exp = p->exp;
    cd->games = (uint8_t)p->games;
    cd->rng = p->rng;
    cd->arm = p->arm;
    cd->po1 = p->po1;
    cd->a1 = p->a1;
    cd->e1 = p->e1;
    cd->s_rbi = (uint16_t)p->tot[TOT_RBI];
}

/* every current player with the slot's identity, in league order.
 * The entry's award counters (152..156) are kept: they carry the career counts
 * accumulated by earlier record_season calls; this season's come from the
 * candidates after phase B assigns entry indices. collect adds the C7
 * candidate for this record (the last chain record of an identity wins, like
 * the reference's exps[idx] overwrite) with its milestone before/after. The
 * team is the slot's first_cur owner. */
static void apply_chain(int32_t s, uint8_t *eb, int collect)
{
    TeamInfo *ti = g_tp[(int)(g_slots[s].first_cur >> 8)];
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
        memset(eb + 157, 0, 3);
        if (collect) {
            /* the reference collects one candidate per named record, keyed by
             * entry index; the LAST chain record's stats win: drop a
             * candidate collected on an earlier chain record and re-append */
            int32_t ci;
            for (ci = g_ncands - 1; ci >= 0; ci--)
                if (g_cands[ci].slot == s) {
                    g_cands[ci] = g_cands[--g_ncands];
                    break;
                }
            cand_collect(ti, (int)(c & 255), s);
        }
        c = p->next_dup;
    }
}

/* history.record_season step 1 (C12.7): W/L by stable id, byte 22 and the division map (bytes
 * 100..115) only when the MAJ has 3 divisions or TEAMID.DAT exists; else both stay 0 */
/* history.league_wl (C2 step 1, C12.3): W and L by stable id, 0 for a team with no games */
static void maj_wl(const Maj *m, uint8_t *wl_w, uint8_t *wl_l)
{
    const uint8_t *tab = m->have_table ? m->table : NULL;
    TiTeam t[TI_MAX_TEAMS];
    int nt, i;
    memset(wl_w, 0, 32);
    memset(wl_l, 0, 32);
    nt = ti_teams(m->d, MAJ_SIZE, tab, t);
    for (i = 0; i < nt; i++) {
        int s = t[i].L ? MAJ_S_NL : MAJ_S_AL;
        uint8_t w = m->d[s + MAJ_O_W + t[i].slot];
        uint8_t l = m->d[s + MAJ_O_L + t[i].slot];
        if (w || l) {
            wl_w[t[i].id] = w;
            wl_l[t[i].id] = l;
        }
    }
}

static void write_season_entry(uint16_t season_no, const Maj *m)
{
    uint32_t o = SEASON_TABLE + (uint32_t)(season_no - 1) * SEASON_ENTRY;
    const uint8_t *tab = m->have_table ? m->table : NULL;
    TiTeam t[TI_MAX_TEAMS];
    uint8_t wl_w[32], wl_l[32], dmap[16];
    int nd, nt, map_on, i, k;
    memset(dmap, 0, 16);
    maj_wl(m, wl_w, wl_l);
    nd = ti_ndiv(m->d, MAJ_SIZE);
    map_on = nd == 3 || m->have_table;
    nt = ti_teams(m->d, MAJ_SIZE, tab, t);
    for (i = 0; i < nt; i++) {
        k = t[i].id;
        if (map_on)
            dmap[k / 2] |= (uint8_t)((t[i].slot / 8 + 1) << (4 * (k & 1)));
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
    g_tab[o + 22] = map_on ? (uint8_t)nd : 0;
    g_tab[o + 23] = 0;
    for (i = 0; i < 32; i++) {
        g_tab[o + 24 + 2 * i] = wl_w[i];
        g_tab[o + 25 + 2 * i] = wl_l[i];
    }
    memset(g_tab + o + 88, 0, 40);
    memcpy(g_tab + o + 100, dmap, 16);      /* after the awards clear: 100..115 */
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

/* ---------------- C7: awards and milestones ---------------- */

static const char *bak_of(const char *hpath, char *dst, size_t cap);

/* the per-league award pick, one C7 rule class at a time. cands = the
 * league's records in ascending entry-index order (cand order is file order:
 * re-sorting by entry index happens on the merged array before this runs) */
static const Cand *pick_max(const Cand *cands, int nc, int32_t (*key)(const Cand *))
{
    const Cand *best = NULL;
    int i;
    for (i = 0; i < nc; i++) {
        if (best == NULL || key(&cands[i]) > key(best))
            best = &cands[i];
    }
    return best;
}

static int32_t key_w10(const Cand *c) { return c->w10; }
static int32_t key_bat100(const Cand *c) { return c->bat100; }
/* history.gold_glove_score: fp1000 + 10 * (2 * range + arm) */
static int32_t key_field(const Cand *c)
{
    return gg_fp1000(c->po1, c->a1, c->e1) + 10L * (2 * (int32_t)c->rng + (int32_t)c->arm);
}
static int32_t key_fp1000(const Cand *c)
{
    return gg_fp1000(c->po1, c->a1, c->e1);
}

/* history.pick_awards on one league's candidates: fills the 20 winners
 * (MVP, CY, ROY, GG 1..8, SS 1..9) as entry indices, or -1 when none, and
 * their award values (history.award_records: WAR10, gg fp1000, bat100), or 0.
 * Filters the merged ascending-entry-index array by league (0 AL, 1 NL). */
static void pick_league(const Cand *lc, int nlc, int league, int32_t *win,
                        int32_t *val)
{
    int q, i, n2;
    Cand *sub;
    const Cand *best;
    sub = (Cand *)calloc((size_t)nlc, sizeof(Cand));
    if (!sub) {
        for (i = 0; i < 20; i++) {
            win[i] = -1;
            val[i] = 0;
        }
        return;
    }
    for (i = 0; i < 20; i++) {
        win[i] = -1;
        val[i] = 0;
    }
    /* MVP: batters pa >= 502, max w10 */
    n2 = 0;
    for (i = 0; i < nlc; i++)
        if (lc[i].league == league && lc[i].pos1 != 0
            && lc[i].pa >= 502)
            sub[n2++] = lc[i];
    best = pick_max(sub, n2, key_w10);
    if (best) {
        win[0] = best->idx;
        val[0] = best->w10;
    }
    /* CY: outs >= 486, fallback any pitcher outs > 0 */
    n2 = 0;
    for (i = 0; i < nlc; i++)
        if (lc[i].league == league && lc[i].pos1 == 0
            && lc[i].outs >= 486)
            sub[n2++] = lc[i];
    best = pick_max(sub, n2, key_w10);
    if (!best) {
        n2 = 0;
        for (i = 0; i < nlc; i++)
            if (lc[i].league == league && lc[i].pos1 == 0
                && lc[i].outs > 0)
                sub[n2++] = lc[i];
        best = pick_max(sub, n2, key_w10);
    }
    if (best) {
        win[1] = best->idx;
        val[1] = best->w10;
    }
    /* ROY: exp 0 and (pa >= 130 or outs >= 150) */
    n2 = 0;
    for (i = 0; i < nlc; i++)
        if (lc[i].league == league && lc[i].exp == 0
            && (lc[i].pa >= 130 || lc[i].outs >= 150))
            sub[n2++] = lc[i];
    best = pick_max(sub, n2, key_w10);
    if (best) {
        win[2] = best->idx;
        val[2] = best->w10;
    }
    /* GG positions 1..8: games gate, max gold_glove_score, then fp1000 on the tie tier */
    for (q = 1; q <= 8; q++) {
        int32_t top;
        int need = (q == 1) ? 90 : 100;
        n2 = 0;
        for (i = 0; i < nlc; i++)
            if (lc[i].league == league && lc[i].pos1 == q
                && lc[i].games >= need)
                sub[n2++] = lc[i];
        best = pick_max(sub, n2, key_field);
        if (!best)
            continue;
        top = key_field(best);
        {
            int m = 0;
            for (i = 0; i < n2; i++)
                if (key_field(&sub[i]) == top)
                    sub[m++] = sub[i];
            best = pick_max(sub, m, key_fp1000);
        }
        if (best) {
            win[2 + q] = best->idx;
            val[2 + q] = gg_fp1000(best->po1, best->a1, best->e1);
        }
    }
    /* SS positions 1..9: pa >= 300, max bat100 */
    for (q = 1; q <= 9; q++) {
        n2 = 0;
        for (i = 0; i < nlc; i++)
            if (lc[i].league == league && lc[i].pos1 == q && lc[i].pa >= 300)
                sub[n2++] = lc[i];
        best = pick_max(sub, n2, key_bat100);
        if (best) {
            win[10 + q] = best->idx;
            val[10 + q] = best->bat100;
        }
    }
    free(sub);
}

/* history.leader_value: the C7 leader value of one candidate for category cat
 * (0 BA .. 8 SV). Returns 0 when it does not qualify: BA h * 1000 / ab over
 * pa >= 502 and ab > 0; ERA er * 2700 / outs over outs >= 486; the others are
 * the season stat, qualifying when > 0. */
static int leader_value(const Cand *c, int cat, int32_t *v)
{
    switch (cat) {
    case 0:
        if (c->pa < 502 || c->ab == 0)
            return 0;
        *v = (int32_t)c->h * 1000 / (int32_t)c->ab;
        return 1;
    case 6:
        if (c->outs < 486)
            return 0;
        *v = (int32_t)c->er * 2700 / (int32_t)c->outs;
        return 1;
    case 1: *v = c->s_hr; break;
    case 2: *v = c->s_rbi; break;
    case 3: *v = c->s_h; break;
    case 4: *v = c->s_sb; break;
    case 5: *v = c->s_w; break;
    case 7: *v = c->s_pso; break;
    case 8: *v = c->s_sv; break;
    default: return 0;
    }
    return *v > 0;
}

/* history.leader_records for one category of one league: cands are in ascending
 * entry index order and only a strictly better candidate replaces the leader
 * (ERA: strictly smaller), so a tie keeps the lower index. Sets *idx and *val
 * and returns 1, or returns 0 when the league has no leader. */
static int leader_pick(const Cand *cands, int nc, int league, int cat,
                       int32_t *idx, int32_t *val)
{
    int i, found = 0;
    for (i = 0; i < nc; i++) {
        int32_t v;
        if (cands[i].league != league || !leader_value(&cands[i], cat, &v))
            continue;
        if (!found || (cat == 6 ? v < *val : v > *val)) {
            *val = v;
            *idx = cands[i].idx;
            found = 1;
        }
    }
    return found;
}

/* patch the entry's award counters on the temp file: counts[k] += 1,
 * saturating at 255 (bytes 152..156; 157..159 already zeroed) */
static int add_award_count(FILE *g, int32_t idx, int k)
{
    static uint8_t eb[PLAYER_ENTRY];
    long off = (long)PLAYER_TABLE + (long)idx * PLAYER_ENTRY;
    uint8_t v;
    if (fseek(g, off + 152, SEEK_SET) != 0)
        return -1;
    if (fread(eb, 1, 5, g) != 5)
        return -1;
    v = (uint8_t)(eb[k] + 1);
    eb[k] = v;
    if (fseek(g, off + 152, SEEK_SET) != 0)
        return -1;
    if (fwrite(eb, 1, 5, g) != 5)
        return -1;
    return 0;
}

/* season entry bytes 88..99: the 6 award winners as u16 entry indices */
static int write_season_awards(FILE *g, uint16_t season_no,
                               const int32_t *al, const int32_t *nl)
{
    uint8_t b[12];
    int i;
    long off = (long)SEASON_TABLE + (long)(season_no - 1) * SEASON_ENTRY + 88;
    for (i = 0; i < 6; i++) {
        int32_t ix = (i < 3) ? al[i] : nl[i - 3];
        wr16(b + 2 * i, (ix < 0) ? (uint16_t)NO_AWARD : (uint16_t)ix);
    }
    if (fseek(g, off, SEEK_SET) != 0)
        return -1;
    if (fwrite(b, 1, 12, g) != 12)
        return -1;
    return 0;
}

/* one milestone record (8 B, little endian) */
static void ms_rec(uint8_t *r, uint16_t season, uint16_t idx, uint8_t kind,
                   int32_t value)
{
    wr16(r, season);
    wr16(r + 2, idx);
    r[4] = kind;
    r[5] = 0;
    wr16(r + 6, (value > 0xffff) ? 0xffffu : (uint16_t)value);
}

/* season milestones for one record (entry-assigned Cand): the career kinds
 * compute before/after from the WRITTEN entry totals (read by the caller
 * into tot[]) minus this record's season totals; the season kinds use the
 * SEASON stats (s_h/s_hr/s_sb/s_w/s_sv/s_pso, h, er, outs) */
/* the record's season total for milestone key k (ms_tot order) */
static uint32_t cand_season_tot(const Cand *c, int k)
{
    switch (ms_tot[k]) {
    case TOT_H: return c->s_h;
    case TOT_HR: return c->s_hr;
    case TOT_RBI: return c->s_rbi;
    case TOT_SB: return c->s_sb;
    case TOT_W: return c->s_w;
    case TOT_SV: return c->s_sv;
    default: return c->s_pso;
    }
}

static int c7_milestones(const Cand *c, uint16_t season,
                         const uint32_t *wtot, uint8_t *out)
{
    int n = 0, i;
    uint8_t r[8];
    for (i = 0; i < MS_CAREER_N; i++) {
        int k = ms_career[i][1];
        uint32_t after = wtot[k];
        uint32_t before = after - cand_season_tot(c, k);
        if (before < (uint32_t)ms_career[i][2]
            && after >= (uint32_t)ms_career[i][2]) {
            ms_rec(r, season, (uint16_t)c->idx, (uint8_t)ms_career[i][0],
                   (int32_t)((after > 0xffffu) ? 0xffffu : after));
            memcpy(out + 8 * n++, r, 8);
        }
    }
    if (c->s_hr >= 50) {
        ms_rec(r, season, (uint16_t)c->idx, 32, c->s_hr);
        memcpy(out + 8 * n++, r, 8);
    }
    if (c->s_h >= 200) {
        ms_rec(r, season, (uint16_t)c->idx, 33, c->s_h);
        memcpy(out + 8 * n++, r, 8);
    }
    if (c->s_sb >= 100) {
        ms_rec(r, season, (uint16_t)c->idx, 34, c->s_sb);
        memcpy(out + 8 * n++, r, 8);
    }
    if (c->pa >= 502 && c->ab > 0
        && idiv64((int64_t)c->h * 1000, c->ab) >= 400) {
        ms_rec(r, season, (uint16_t)c->idx, 35,
               idiv64((int64_t)c->h * 1000, c->ab));
        memcpy(out + 8 * n++, r, 8);
    }
    if (c->s_w >= 20) {
        ms_rec(r, season, (uint16_t)c->idx, 36, c->s_w);
        memcpy(out + 8 * n++, r, 8);
    }
    if (c->s_pso >= 300) {
        ms_rec(r, season, (uint16_t)c->idx, 37, c->s_pso);
        memcpy(out + 8 * n++, r, 8);
    }
    if (c->outs >= 486
        && idiv64((int64_t)c->er * 2700, c->outs) < 200) {
        ms_rec(r, season, (uint16_t)c->idx, 38,
               idiv64((int64_t)c->er * 2700, c->outs));
        memcpy(out + 8 * n++, r, 8);
    }
    if (c->s_sv >= 50) {
        ms_rec(r, season, (uint16_t)c->idx, 39, c->s_sv);
        memcpy(out + 8 * n++, r, 8);
    }
    return n;
}

/* C7 World Series records (history.series_records): PLAYOFFS.AL in the pre dir,
 * byte 0 = games n (1..7), game g at 1 + GAME_REC * g. A game stem (8 B cut at the
 * first NUL, upper-cased) maps to the last matching MAJ stem: AL slots 0..15, then NL. */
#define PO_NAME     "PLAYOFFS.AL"
#define GAME_REC    7446L
#define GAME_MAX    7
#define SER_KIND    192
#define SER_HE_KIND 200

/* league-global team id of an 8 B game stem, or -1 (an empty stem never maps) */
static int32_t series_id(const uint8_t *s8)
{
    char up[9];
    int32_t id = -1;
    int j, k;
    for (j = 0; j < 8 && s8[j]; j++)
        up[j] = (char)s8[j];
    up[j] = 0;
    if (j == 0)
        return -1;
    to_upper((uint8_t *)up);
    for (k = 0; k < 32; k++) {
        if (strcmp(up, g_maj.stem_up[k]) == 0)
            id = k;
    }
    return id;
}

/* the sum of the 80 bytes at off, capped at 255 */
static int sum80(FILE *p, long off, int32_t *out)
{
    uint8_t b[80];
    uint32_t s = 0;
    int i;
    if (fseek(p, off, SEEK_SET) != 0)
        return -1;
    if (fread(b, 1, sizeof b, p) != sizeof b)
        return -1;
    for (i = 0; i < 80; i++)
        s += b[i];
    *out = (s > 255) ? 255 : (int32_t)s;
    return 0;
}

/* C7 box score rows (history.box_records). Team block offsets of the stats: singles are the
 * u8 at OFF + i, pairs the sum of OFF + 2i and OFF + 2i + 1 capped at 255. The span
 * BOX_LO .. BOX_LO + BOX_SPAN - 1 of a team block is read in one go. */
#define BOX_B_OFF  6975L            /* b bytes: r + BOX_B_OFF + 40 * t + i */
#define BOX_TEAM   0x8e8L           /* team block stride */
#define BOX_LO     0xf0L
#define BOX_SPAN   0x898            /* 0x988 - 0xf0 */

typedef struct {
    uint16_t off;
    uint8_t pair;
} BoxStat;

/* AB R H RBI HR BB SO SB */
static const BoxStat box_bat[8] = {
    { 0x1b8, 1 }, { 0xf0, 0 }, { 0x208, 1 }, { 0x118, 0 },
    { 0x2f8, 1 }, { 0x348, 1 }, { 0x398, 1 }, { 0x168, 0 } };
/* IP10 H R ER HR BB SO BF */
static const BoxStat box_pit[8] = {
    { 0x6e0, 0 }, { 0x7a8, 1 }, { 0x730, 0 }, { 0x708, 0 },
    { 0x898, 1 }, { 0x8e8, 1 }, { 0x938, 1 }, { 0x758, 1 } };

/* the player entry index of V20 record i on team id tid: the last team in g_tp order with that id
 * whose record i is active (rec_idx of history.record_season); NO_ENTRY when none */
static int32_t box_idx(int32_t tid, int i)
{
    int32_t k, idx = NO_ENTRY;
    int j;
    for (k = 0; k < g_nt; k++) {
        const TeamInfo *ti = g_tp[k];
        if (ti->lg_slot != tid)
            continue;
        for (j = 0; j < ti->ncur; j++)
            if (ti->cur[j].rec_no == i)
                idx = ti->cur[j].entry_index;
    }
    return idx;
}

/* every current record takes its slot's player entry index (phase B has set them all) */
static void cur_entries(void)
{
    int32_t s, c;
    for (s = 0; s < g_nslots; s++)
        for (c = g_slots[s].first_cur; c >= 0; c = cur_of(c)->next_dup)
            ((CurPlayer *)cur_of(c))->entry_index = g_slots[s].entry_index;
}

/* one box stat of id i from the span of a team block */
static uint8_t box_val(const uint8_t *span, const BoxStat *bs, int i)
{
    const uint8_t *p = span + (bs->off - BOX_LO);
    uint32_t s;
    if (!bs->pair)
        return p[i];
    s = (uint32_t)p[2 * i] + p[2 * i + 1];
    return (uint8_t)(s > 255 ? 255 : s);
}

/* one 16 B box record: season, g, flags, entry index, b, i, 8 stats */
static int box_put(FILE *f, uint16_t season_no, uint8_t g, uint8_t flags, int32_t idx,
                   uint8_t b, uint8_t i, const uint8_t *st)
{
    uint8_t rec[BOX_REC];
    int k;
    wr16(rec, season_no);
    rec[2] = g;
    rec[3] = flags;
    wr16(rec + 4, (uint16_t)idx);
    rec[6] = b;
    rec[7] = i;
    for (k = 0; k < 8; k++)
        rec[8 + k] = st[k];
    return fwrite(rec, 1, BOX_REC, f) == BOX_REC ? 0 : -1;
}

/* the box rows of one team side of the game at r (side t, team id tid): the 40 b bytes, then
 * the stats span. Batting rows by (slot, entry order, id), then pitching rows by (entry order,
 * id); the span buffer is span[BOX_SPAN]. */
static int box_side(FILE *p, FILE *bx, long r, int t, uint16_t season_no, uint8_t g,
                    int32_t tid, uint8_t *span)
{
    uint8_t b[40], st[8];
    int slot, ord, i, k;
    if (fseek(p, r + BOX_B_OFF + 40L * t, SEEK_SET) != 0
        || fread(b, 1, 40, p) != 40)
        return -1;
    if (fseek(p, r + BOX_TEAM * t + BOX_LO, SEEK_SET) != 0
        || fread(span, 1, BOX_SPAN, p) != BOX_SPAN)
        return -1;
    for (slot = 0; slot <= 8; slot++)
        for (ord = 0; ord < 16; ord++)
            for (i = 0; i < 40; i++) {
                if (b[i] == 0 || (b[i] & 15) != slot || (b[i] >> 4) != ord)
                    continue;
                for (k = 0; k < 8; k++)
                    st[k] = box_val(span, &box_bat[k], i);
                if (box_put(bx, season_no, g, (uint8_t)t, box_idx(tid, i),
                            b[i], (uint8_t)i, st) != 0)
                    return -1;
            }
    for (ord = 0; ord < 16; ord++)
        for (i = 0; i < 16; i++) {
            if (b[i] == 0 || (b[i] >> 4) != ord)
                continue;
            for (k = 0; k < 8; k++)
                st[k] = box_val(span, &box_pit[k], i);
            if ((b[i] & 15) != 9 && st[0] == 0 && st[7] == 0)
                continue;             /* IP10 and BF both 0, not the slot 9 pitcher */
            if (box_put(bx, season_no, g, (uint8_t)(t | 2), box_idx(tid, i),
                        b[i], (uint8_t)i, st) != 0)
                return -1;
        }
    return 0;
}

/* the season's World Series records, appended to the open milestone temp ms after the
 * leader records; the kept games' box rows go to the open box temp bx. A missing, short
 * or out-of-range PLAYOFFS.AL writes nothing. Returns -1 on a read or write error; the
 * file is closed on every path. */
static int series_pass(const char *pre_dir, FILE *ms, FILE *bx, uint16_t season_no)
{
    char *path = g_path;
    FILE *p;
    long len, r;
    int n, g;
    uint8_t *span = NULL;
    path_join(path, 600, pre_dir, PO_NAME);
    p = fopen(path, "rb");
    if (!p)
        return 0;
    if (fseek(p, 0, SEEK_END) != 0)
        goto bad;
    len = ftell(p);
    if (len < 0)
        goto bad;
    if (len < 1)
        goto none;
    if (fseek(p, 0, SEEK_SET) != 0)
        goto bad;
    n = fgetc(p);
    if (n < 1 || n > GAME_MAX || len < 1 + GAME_REC * n)
        goto none;
    span = (uint8_t *)malloc(BOX_SPAN);
    if (!span)
        goto bad;
    for (g = 0; g < n; g++) {
        uint8_t runs[2], st[16], rec[8];
        int32_t hits[2], errs[2];
        int32_t vid, hid;
        int t;
        r = 1 + GAME_REC * g;
        if (fseek(p, r + 0x1beb, SEEK_SET) != 0 || fread(runs, 1, 2, p) != 2)
            goto bad;
        if (fseek(p, r + 0x1c01, SEEK_SET) != 0 || fread(st, 1, 16, p) != 16)
            goto bad;
        hid = series_id(st);
        vid = series_id(st + 8);
        if (vid < 0 || hid < 0 || (vid < 16) == (hid < 16))
            continue;                 /* unmapped stem or both teams in one league */
        for (t = 0; t < 2; t++) {
            if (sum80(p, r + 0x208 + 0x8e8L * t, &hits[t]) != 0
                || sum80(p, r + 0x5c8 + 0x8e8L * t, &errs[t]) != 0)
                goto bad;
        }
        ms_rec(rec, season_no, (uint16_t)(vid * 256 + hid), (uint8_t)(SER_KIND + g),
               runs[0] * 256 + runs[1]);
        if (fwrite(rec, 1, 8, ms) != 8)
            goto bad;
        ms_rec(rec, season_no, (uint16_t)(hits[0] * 256 + hits[1]),
               (uint8_t)(SER_HE_KIND + g), errs[0] * 256 + errs[1]);
        if (fwrite(rec, 1, 8, ms) != 8)
            goto bad;
        if (box_side(p, bx, r, 0, season_no, (uint8_t)g, vid, span) != 0
            || box_side(p, bx, r, 1, season_no, (uint8_t)g, hid, span) != 0)
            goto bad;
    }
none:
    free(span);
    fclose(p);
    return 0;
bad:
    free(span);
    fclose(p);
    return -1;
}

/* MILESTON.DAT / BOXSCORE.DAT keep rule (C7): copy the rec-byte records of the file at path
 * whose u16 season (bytes 0..1) is below season_no to out; a short tail is dropped and a
 * missing file copies nothing. Returns -1 on a read or write error. */
static int keep_old(const char *path, int rec, uint16_t season_no, FILE *out)
{
    FILE *mo = fopen(path, "rb");
    uint8_t r[BOX_REC];
    long msz, kept;
    if (!mo)
        return 0;
    if (fseek(mo, 0, SEEK_END) != 0 || (msz = ftell(mo)) < 0
        || fseek(mo, 0, SEEK_SET) != 0)
        goto bad;
    for (kept = 0; kept + rec <= msz; kept += rec) {
        if (fread(r, 1, (size_t)rec, mo) != (size_t)rec)
            goto bad;
        if (rd16(r) >= season_no)
            continue;                 /* drop-then-append */
        if (fwrite(r, 1, (size_t)rec, out) != (size_t)rec)
            goto bad;
    }
    fclose(mo);
    return 0;
bad:
    fclose(mo);
    return -1;
}

/* one file of the swap: fin is replaced by tmp; bak keeps the original */
typedef struct {
    const char *fin;
    char *tmp, *bak;
    int moved, landed;
} Swap;

/* put one file back as it was: the new file goes (when it landed), the original comes back
 * from its bak (when it was moved aside), and the temp never outlives the swap */
static void swap_undo(Swap *s)
{
    if (s->landed)
        remove(s->fin);
    if (s->moved)
        rename(s->bak, s->fin);
    remove(s->tmp);
    s->landed = 0;
    s->moved = 0;
}

/* the mapped teams of dir (its *.V20 files whose stem names a team of m, in sorted order) into g_tp,
 * and the identity slot table for them. 0 on success, -1 when memory runs out */
static int load_teams(const char *dir, const Maj *m)
{
    int nv, k;
    nv = scan_dir(dir, ".V20", g_names);
    for (k = 0; k < nv; k++) {
        static char stem[16];
        int kid, lg_slot = -1;         /* lg_slot: the stable id (C12.3) */
        size_t l = strlen(g_names[k]);
        TeamInfo *ti;
        if (l <= 4 || l - 4 > 12)
            continue;
        memcpy(stem, g_names[k], l - 4);
        stem[l - 4] = 0;
        to_upper((uint8_t *)stem);
        for (kid = 0; kid < 32; kid++) {
            if (strcmp(stem, m->stem_up[kid]) == 0)
                lg_slot = kid;
        }
        if (lg_slot < 0)
            continue;
        ti = (TeamInfo *)calloc(1, sizeof(TeamInfo));
        if (!ti)
            return -1;
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
                return -1;
            g_slots_cap = ncap;
        }
    }
    return 0;
}

/* ---------------- C13.2: SEASLINE.DAT ---------------- */

/* one SEASLINE.DAT line (history.line_bytes): bio, dev grade and ratings from the roster half, stats
 * (cp->tot = season_stats_inputs, TOTALS order) and the season WAR10 (cp->w10) from the record */
static void line_put(int32_t idx, uint16_t season_no, int team_id,
                     const uint8_t *roster, const CurPlayer *cp)
{
    uint8_t *b = g_line;
    int k;
    memset(b, 0, SL_LINE);
    wr16(b, (uint16_t)idx);
    wr16(b + 2, season_no);
    b[4] = (uint8_t)team_id;
    b[5] = (cp->pos1 == 0) ? 1 : 0;
    b[6] = roster[R_AGE];
    b[7] = (uint8_t)(roster[R_POS1] & 15);
    wr16(b + 8, rd16(roster + R_PORTRAIT));
    b[10] = roster[R_B29];
    b[11] = roster[R_DEV];
    /* power, bunt, hit_run, speed, range, arm, control, velocity, endurance (the nibbles) */
    b[12] = (uint8_t)(roster[R_POWER] & 15);
    b[13] = (uint8_t)(roster[R_POWER] >> 4);
    b[14] = (uint8_t)(roster[R_HITRUN] & 15);
    b[15] = (uint8_t)(roster[R_SPEED] >> 4);
    b[16] = (uint8_t)(roster[R_RANGE] >> 4);
    b[17] = (uint8_t)(roster[R_ARM] & 15);
    b[18] = (uint8_t)(roster[R_CONTROL] & 15);
    b[19] = (uint8_t)(roster[R_CONTROL] >> 4);
    b[20] = (uint8_t)(roster[R_ENDUR] >> 4);
    for (k = 0; k < NUM_TOT; k++)
        wr16(b + 22 + 2 * k, (uint16_t)(cp->tot[k] > 0xffffu ? 0xffffu : cp->tot[k]));
    wr16(b + 72, (uint16_t)cp->w10);
}

/* the 16 B SEASLINE.DAT header: S L, version 1, 0, line size 80, highest season in 6..7, 8 zero */
static int sl_header(FILE *f, uint16_t highest)
{
    uint8_t h[SL_HDR];
    memset(h, 0, sizeof h);
    h[0] = 'S';
    h[1] = 'L';
    h[2] = VERSION_ONE;
    wr16(h + 4, SL_LINE);
    wr16(h + 6, highest);
    return fwrite(h, 1, SL_HDR, f) == SL_HDR ? 0 : -1;
}

/* the lines of old (a SEASLINE.DAT) below season_no, copied to out in file order. A missing or bad
 * header keeps none; a short tail is dropped */
static int sl_keep(FILE *old, FILE *out, uint16_t season_no)
{
    uint8_t h[SL_HDR];
    if (fread(h, 1, SL_HDR, old) != SL_HDR)
        return 0;
    if (h[0] != 'S' || h[1] != 'L' || h[2] != VERSION_ONE || h[3] != 0
        || rd16(h + 4) != SL_LINE)
        return 0;
    while (fread(g_line, 1, SL_LINE, old) == SL_LINE) {
        if (rd16(g_line + 2) < season_no
            && fwrite(g_line, 1, SL_LINE, out) != SL_LINE)
            return -1;
    }
    return 0;
}

/* the lines of the mapped teams' active records in step 3 order (g_tp order, records 0..39), with
 * the player entry indexes of cur_entries; a record with no entry (-1) gets no line. dir holds the
 * V20 files */
static int season_lines(FILE *out, const char *dir, uint16_t season_no)
{
    char *path = g_path;
    int k, i;
    for (k = 0; k < g_nt; k++) {
        TeamInfo *ti = g_tp[k];
        int j = 0;
        if (!path_join(path, 600, dir, ti->fname) || !load_v20(path))
            return -1;
        for (i = 0; i < 40; i++) {
            const uint8_t *roster = g_v20 + V20_HDR + V20_REC * i;
            const CurPlayer *cp;
            if (roster[R_ACTIVE] == 0)
                continue;
            cp = &ti->cur[j++];
            if (cp->entry_index < 0)
                continue;
            line_put(cp->entry_index, season_no, ti->lg_slot, roster, cp);
            if (fwrite(g_line, 1, SL_LINE, out) != SL_LINE)
                return -1;
        }
    }
    return 0;
}

/* the SEASLINE.DAT of this season into the temp file sltmp: the header, the lines of the file slpath
 * below season_no (season_no >= current is dropped), then this season's lines */
static int seasline_write(const char *pre_dir, const char *slpath, const char *sltmp,
                          uint16_t season_no)
{
    FILE *old = fopen(slpath, "rb");
    FILE *out = fopen(sltmp, "wb");
    int rc = -1;
    if (!out)
        goto done;
    if (sl_header(out, season_no) != 0)
        goto done;
    if (old && sl_keep(old, out, season_no) != 0)
        goto done;
    if (season_lines(out, pre_dir, season_no) != 0)
        goto done;
    rc = 0;
done:
    if (old)
        fclose(old);
    if (out && fclose(out) != 0)
        rc = -1;
    return rc;
}

/* the per-run state of one archive: teams, identity slots, park factors and league totals start clean */
static void lines_reset(void)
{
    int k;
    for (k = 0; k < g_nt; k++) {
        free(g_tp[k]);
        g_tp[k] = NULL;
    }
    g_nt = 0;
    free(g_slots);
    g_slots = NULL;
    g_slots_cap = 0;
    g_nslots = 0;
    for (k = 0; k < HASH_BUCKETS; k++)
        g_hhead[k] = -1;
    memset(g_pf_valid, 0, sizeof g_pf_valid);
    g_L_lw = 0;
    g_L_pa = 0;
    g_L_runs = 0;
    g_L_er = 0;
    g_L_outs = 0;
}

/* history.find_entry for the current players: each identity slot takes the lowest HISTORY.DAT entry
 * index with its name and birth (-1 when none). hf is HISTORY.DAT, n player entries. Reads only. */
static int hist_identities(FILE *hf, long n)
{
    static uint8_t eb[PLAYER_ENTRY];
    long i;
    if (fseek(hf, PLAYER_TABLE, SEEK_SET) != 0)
        return -1;
    for (i = 0; i < n; i++) {
        int32_t s;
        if (fread(eb, 1, PLAYER_ENTRY, hf) != (size_t)PLAYER_ENTRY)
            return -1;
        s = hash_find(eb, rd16(eb + 20));
        if (s >= 0 && g_slots[s].entry_index < 0)
            g_slots[s].entry_index = (int32_t)i;
    }
    return 0;
}

/* history.archive_dirs name test: S (either case) and two digits, nn 1..99 */
static int snn_of(const char *name, int *nn)
{
    if (strlen(name) != 3 || (name[0] != 'S' && name[0] != 's'))
        return 0;
    if (name[1] < '0' || name[1] > '9' || name[2] < '0' || name[2] > '9')
        return 0;
    *nn = (name[1] - '0') * 10 + (name[2] - '0');
    return *nn >= 1;
}

/* the Snn subdirs of sdir into g_snn[nn] (the first name of each nn wins) */
#ifdef __WATCOMC__

static void snn_list(const char *sdir)
{
    struct find_t ft;
    int nn = 0;
    if (!path_join(g_path, 600, sdir, "*.*"))
        return;
    if (_dos_findfirst(g_path, _A_SUBDIR, &ft) != 0)
        return;
    do {
        if ((ft.attrib & _A_SUBDIR) && snn_of(ft.name, &nn) && g_snn[nn][0] == 0)
            strcpy(g_snn[nn], ft.name);
    } while (_dos_findnext(&ft) == 0);
}

#else

static void snn_list(const char *sdir)
{
    DIR *dirp = opendir(sdir);
    struct dirent *de;
    int nn = 0;
    if (!dirp)
        return;
    while ((de = readdir(dirp)) != NULL)
        if (snn_of(de->d_name, &nn) && g_snn[nn][0] == 0)
            strcpy(g_snn[nn], de->d_name);
    closedir(dirp);
}

#endif

/* the archive dir sdir\name into g_adir; 0 when it does not fit */
static int arch_dir(const char *sdir, const char *name)
{
    return path_join(g_adir, sizeof g_adir, sdir, name);
}

/* history.archive_dirs: the Snn subdirs of sdir that hold a *.MAJ, in nn order, into g_arch */
static int arch_list(const char *sdir)
{
    int nn;
    memset(g_snn, 0, sizeof g_snn);
    g_arch_cnt = 0;
    snn_list(sdir);
    for (nn = 1; nn <= 99; nn++) {
        if (g_snn[nn][0] == 0 || !arch_dir(sdir, g_snn[nn])
            || scan_dir(g_adir, ".MAJ", g_mnames) < 1)
            continue;
        strcpy(g_arch[g_arch_cnt++], g_snn[nn]);
    }
    return g_arch_cnt;
}

/* 1 when the 32 (W, L) pairs of st (the stored season entry) equal wl_w / wl_l */
static int wl_equal(const uint8_t *wl_w, const uint8_t *wl_l, const uint8_t *st)
{
    int k;
    for (k = 0; k < 32; k++) {
        if (wl_w[k] != st[2 * k] || wl_l[k] != st[2 * k + 1])
            return 0;
    }
    return 1;
}

/* history.backfill_lines match: archives in nn order, each takes the lowest season s (1..limit, not
 * yet taken) whose stored W-L (g_tab's season table) equals its own, when it has a game. Sets
 * g_arch_sel. -1 on a read or memory failure */
static int lines_match(const char *sdir, int limit)
{
    int a, s, k, played;
    for (s = 0; s <= SEASON_COUNT; s++)
        g_arch_sel[s] = -1;
    for (a = 0; a < g_arch_cnt; a++) {
        uint8_t wl_w[32], wl_l[32];
        if (!arch_dir(sdir, g_arch[a]) || !read_maj(g_adir, &g_maj))
            return -1;
        maj_wl(&g_maj, wl_w, wl_l);
        free(g_maj.d);
        g_maj.d = NULL;
        played = 0;
        for (k = 0; k < 32; k++)
            played |= wl_w[k] || wl_l[k];
        if (!played)
            continue;
        for (s = 1; s <= limit; s++) {
            const uint8_t *st = g_tab + SEASON_TABLE + (s - 1) * SEASON_ENTRY + 24;
            if (g_arch_sel[s] < 0 && wl_equal(wl_w, wl_l, st)) {
                g_arch_sel[s] = a;
                break;
            }
        }
    }
    return 0;
}

/* the lines of one archive (the pre-roll league of season s, history.archive_lines) appended to out.
 * Entry indexes come from hf, the HISTORY.DAT as it stands (n entries); nothing is written to it */
static int archive_lines(FILE *hf, long n, uint16_t s, FILE *out)
{
    int rc;
    lines_reset();
    g_season_no = s;
    rc = read_maj(g_adir, &g_maj) ? 0 : -1;
    if (rc == 0 && (load_teams(g_adir, &g_maj) != 0 || league_pass(g_adir) != 0
                    || player_pass(g_adir) != 0 || hist_identities(hf, n) != 0))
        rc = -1;
    if (rc == 0) {
        cur_entries();
        rc = season_lines(out, g_adir, s);
    }
    lines_reset();
    free(g_maj.d);
    g_maj.d = NULL;
    return rc;
}

/* HISTWR /LINES (history.backfill_lines): SEASLINE.DAT beside hpath from the season archives of
 * sdir, only when SEASLINE.DAT does not exist yet and HISTORY.DAT has seasons recorded. The file is
 * written even when nothing matched. 0 on success and on nothing to do, 2 on an I/O or memory failure */
static int run_lines(const char *hpath, const char *sdir)
{
    static char FARDATA slname[PATH_CAP];
    static char FARDATA sltmp[PATH_CAP];
    FILE *f, *out = NULL, *sl;
    long len = 0, n = 0;
    size_t want;
    int limit, s, highest = 0;
    tmp_of(hpath, slname, PATH_CAP, SL_NAME);
    tmp_of(hpath, sltmp, PATH_CAP, SL_TMP_NAME);
    sl = fopen(slname, "rb");
    if (sl) {
        fclose(sl);
        return 0;                      /* exists: the backfill never runs twice */
    }
    f = fopen(hpath, "rb");
    if (!f)
        return 0;
    if (fseek(f, 0, SEEK_END) != 0 || (len = ftell(f)) < 0)
        goto fail;
    memset(g_tab, 0, sizeof g_tab);
    want = len < (long)sizeof g_tab ? (size_t)len : sizeof g_tab;
    if (fseek(f, 0, SEEK_SET) != 0 || fread(g_tab, 1, want, f) != want)
        goto fail;
    limit = rd16(g_tab + 4);
    if (limit == 0) {
        fclose(f);
        return 0;
    }
    if (limit > SEASON_COUNT)
        limit = SEASON_COUNT;
    if (len >= (long)PLAYER_TABLE)
        n = (len - PLAYER_TABLE) / PLAYER_ENTRY;
    arch_list(sdir);
    if (lines_match(sdir, limit) != 0)
        goto fail;
    for (s = 1; s <= limit; s++) {
        if (g_arch_sel[s] >= 0)
            highest = s;
    }
    out = fopen(sltmp, "wb");
    if (!out || sl_header(out, (uint16_t)highest) != 0)
        goto fail;
    for (s = 1; s <= limit; s++) {
        if (g_arch_sel[s] < 0)
            continue;
        if (!arch_dir(sdir, g_arch[g_arch_sel[s]])
            || archive_lines(f, n, (uint16_t)s, out) != 0)
            goto fail;
    }
    if (fclose(out) != 0) {
        out = NULL;
        goto fail;
    }
    out = NULL;
    if (rename(sltmp, slname) != 0)
        goto fail;
    fclose(f);
    return 0;
fail:
    if (out)
        fclose(out);
    fclose(f);
    remove(sltmp);
    return 2;
}

/* a switch (/LINES, /SNAP, /ARCHIVE), case-insensitive; want is upper case */
static int arg_is(const char *s, const char *want)
{
    size_t i;
    if (strlen(s) != strlen(want))
        return 0;
    for (i = 0; want[i]; i++) {
        char c = s[i];
        if (c >= 'a' && c <= 'z')
            c = (char)(c - 32);
        if (c != want[i])
            return 0;
    }
    return 1;
}

static int do_run(const char *pre_dir, const char *hpath)
{
    FILE *f = NULL, *g = NULL, *ms = NULL, *bx = NULL;
    long old_len = 0, remaining = 0;
    uint16_t sr_raw, season_no, sr_new;
    uint32_t out_index = 0;
    static uint8_t eb[PLAYER_ENTRY];
    int32_t s;
    int nrt;
    int k;
    RetTeam *rt = NULL;
    /* every path of the run in one block: history temp and backup, milestone and box
     * temps, backups and finals */
    char *paths, *tmp, *bak, *mstmp, *msbak, *msname, *boxtmp, *boxbak, *boxname;
    char *sltmp, *slbak, *slname;
    Swap sw[SWAP_N];

    paths = (char *)malloc(RUN_PATHS * PATH_CAP);
    if (!paths)
        return 2;
    tmp = paths;
    bak = paths + PATH_CAP;
    mstmp = paths + 2 * PATH_CAP;
    msbak = paths + 3 * PATH_CAP;
    msname = paths + 4 * PATH_CAP;
    boxtmp = paths + 5 * PATH_CAP;
    boxbak = paths + 6 * PATH_CAP;
    boxname = paths + 7 * PATH_CAP;
    sltmp = paths + 8 * PATH_CAP;
    slbak = paths + 9 * PATH_CAP;
    slname = paths + 10 * PATH_CAP;
    tmp_of(hpath, tmp, PATH_CAP, TMP_NAME);
    bak_of(hpath, bak, PATH_CAP);
    tmp_of(hpath, mstmp, PATH_CAP, MS_TMP_NAME);
    tmp_of(hpath, msbak, PATH_CAP, MS_BAK_NAME);
    tmp_of(hpath, msname, PATH_CAP, MS_NAME);
    tmp_of(hpath, boxtmp, PATH_CAP, BOX_TMP_NAME);
    tmp_of(hpath, boxbak, PATH_CAP, BOX_BAK_NAME);
    tmp_of(hpath, boxname, PATH_CAP, BOX_NAME);
    tmp_of(hpath, sltmp, PATH_CAP, SL_TMP_NAME);
    tmp_of(hpath, slbak, PATH_CAP, SL_BAK_NAME);
    tmp_of(hpath, slname, PATH_CAP, SL_NAME);
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
    /* a header count of 0xffff wraps season_no to 0: no entry, as for any count past the table */
    if (season_no >= 1 && season_no <= SEASON_COUNT)
        write_season_entry(season_no, &g_maj);
    g_tab[3] = VERSION_ONE;

    /* candidates: one per active record (ncur is known after player_pass);
     * a single calloc must stay under the DOS 64 KB allocation limit */
    {
        int32_t tc = 0;
        for (k = 0; k < g_nt; k++)
            tc += g_tp[k]->ncur;
        g_cands = NULL;
        g_ncands = 0;
        g_cands_cap = 0;
        if (tc > 0) {
            g_cands = (Cand *)calloc((size_t)tc, sizeof(Cand));
            if (!g_cands)
                goto fail;
            g_cands_cap = tc;
        }
    }

    /* MILESTON.TMP: old records with season_no < current, then this season's
     * appended in entry order during phase B (drop-then-append) */
    ms = fopen(mstmp, "wb");
    if (!ms)
        goto fail;
    if (f && old_len > 0 && keep_old(msname, 8, season_no, ms) != 0)
        goto fail;

    /* BOXSCORE.TMP (C7 fourth amendment): the same keep rule over 16 B records; this
     * season's box rows are appended by series_pass */
    bx = fopen(boxtmp, "wb");
    if (!bx)
        goto fail;
    if (f && old_len > 0 && keep_old(boxname, BOX_REC, season_no, bx) != 0)
        goto fail;

    /* milestone records for this season were accumulated on the candidates by
     * apply_chain during phase B; they are appended below by entry index */

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
            apply_chain(h, eb, 1);
            slots_assign(h, (int32_t)out_index);
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
        apply_chain(s, eb, 1);
        slots_assign(s, (int32_t)out_index);
        if (fwrite(eb, 1, PLAYER_ENTRY, g) != (size_t)PLAYER_ENTRY)
            goto fail;
        out_index++;
    }
    cur_entries();

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

    /* C7: resolved below, after this close of the milestone temp */
    if (ms != NULL) {
        if (fclose(ms) != 0) {
            ms = NULL;
            goto fail;
        }
        ms = NULL;
    }

    /* reopen the milestone temp for the season's records */
    ms = fopen(mstmp, "ab");
    if (!ms)
        goto fail;
    if (g_cands != NULL) {
        static int32_t alwin[20], nlwin[20], alval[20], nlval[20];
        int32_t ci;
        int k, q, i;
        Cand *c;
        /* history sorts the collected records by player ENTRY index (stable),
         * so ties go to the lower entry index; cand order is collection
         * order, which is not entry index order for returning players:
         * insertion-sort by idx */
        for (ci = 1; ci < g_ncands; ci++) {
            Cand t = g_cands[ci];
            int32_t j = ci - 1;
            while (j >= 0 && g_cands[j].idx > t.idx) {
                g_cands[j + 1] = g_cands[j];
                j--;
            }
            g_cands[j + 1] = t;
        }
        /* both leagues scan the whole array (pick_league filters by
         * league): sorted by entry index, AL and NL interleave once
         * ROSTERS trades and appended entries mix the index order */
        pick_league(g_cands, (int)g_ncands, 0, alwin, alval);
        pick_league(g_cands, (int)g_ncands, 1, nlwin, nlval);
        /* award counts on the temp entries (already written): seek and patch */
        g = fopen(tmp, "r+b");
        if (!g)
            goto fail;
        for (k = 0; k < 2; k++) {
            const int32_t *win = k ? nlwin : alwin;
            /* ckind: MVP/CY/ROY = 0..2, GG 1..8 = 3, SS 1..9 = 4 */
            for (i = 0; i < 3; i++)
                if (win[i] >= 0 && add_award_count(g, win[i], i) != 0)
                    goto fail;
            for (q = 1; q <= 8; q++)
                if (win[2 + q] >= 0 && add_award_count(g, win[2 + q], 3) != 0)
                    goto fail;
            for (q = 1; q <= 9; q++)
                if (win[10 + q] >= 0 && add_award_count(g, win[10 + q], 4) != 0)
                    goto fail;
        }
        if (season_no >= 1 && season_no <= SEASON_COUNT
            && write_season_awards(g, season_no, alwin, nlwin) != 0)
            goto fail;
        if (fclose(g) != 0) {
            g = NULL;
            goto fail;
        }
        g = NULL;                 /* closed: fail must not fclose it again */
        /* season milestones appended by entry index, kinds ascending per
         * player; out is small because the records are written per cand.
         * The wtot read uses the already-open temp handle parked at the
         * entry: reopen a dedicated read handle to keep the count patches
         * and the reads independent. */
        {
            static uint8_t out[8 * 25];
            int32_t acc = 0;
            FILE *r = fopen(tmp, "rb");
            uint32_t wtot[MS_KEYS];
            int k2;
            long off;
            if (!r)
                goto fail;
            for (ci = 0; ci < g_ncands; ci++) {
                c = &g_cands[ci];
                off = (long)PLAYER_TABLE + (long)c->idx * PLAYER_ENTRY;
                for (k2 = 0; k2 < MS_KEYS; k2++) {
                    uint8_t b4[4];
                    if (fseek(r, off + 32 + 4 * ms_tot[k2], SEEK_SET) != 0
                        || fread(b4, 1, 4, r) != 4)
                        goto rfail;
                    wtot[k2] = rd32(b4);
                }
                acc += c7_milestones(c, season_no, wtot, out);
                if (acc > 0) {
                    if (fwrite(out, 1, (size_t)acc * 8, ms)
                        != (size_t)acc * 8)
                        goto rfail;
                    acc = 0;
                }
            }
            fclose(r);
            goto racc;
rfail:
            fclose(r);
            goto fail;
racc:
            ;
        }
        /* C7 award records after this season's milestones: AL block (kind
         * 64 + k) then NL block (96 + k), k ascending, one per winner. The
         * value is stored as u16 (value & 0xffff), not saturated as ms_rec does */
        for (k = 0; k < 2; k++) {
            const int32_t *win = k ? nlwin : alwin;
            const int32_t *val = k ? nlval : alval;
            for (i = 0; i < 20; i++) {
                uint8_t ar[8];
                if (win[i] < 0)
                    continue;
                wr16(ar, season_no);
                wr16(ar + 2, (uint16_t)win[i]);
                ar[4] = (uint8_t)((k ? 96 : 64) + i);
                ar[5] = 0;
                wr16(ar + 6, (uint16_t)(val[i] & 0xffff));
                if (fwrite(ar, 1, 8, ms) != 8)
                    goto fail;
            }
        }
        /* C7 leader records after the award records: AL block (kind 128 + cat)
         * then NL block (160 + cat), cat ascending, one per category with a
         * leader; value saturates at 65535 (not wrapped, unlike the awards) */
        for (k = 0; k < 2; k++) {
            for (i = 0; i < 9; i++) {
                uint8_t ar[8];
                int32_t lidx = 0, lval = 0;
                if (!leader_pick(g_cands, (int)g_ncands, k, i, &lidx, &lval))
                    continue;
                wr16(ar, season_no);
                wr16(ar + 2, (uint16_t)lidx);
                ar[4] = (uint8_t)((k ? 160 : 128) + i);
                ar[5] = 0;
                wr16(ar + 6, (lval > 0xffff) ? 0xffffu : (uint16_t)lval);
                if (fwrite(ar, 1, 8, ms) != 8)
                    goto fail;
            }
        }
    }
    /* C7 World Series records after the leader records (PLAYOFFS.AL in the pre dir), and
     * the kept games' box rows into BOXSCORE.TMP */
    if (series_pass(pre_dir, ms, bx, season_no) != 0)
        goto fail;
    if (ms != NULL) {
        if (fclose(ms) != 0) {
            ms = NULL;
            goto fail;
        }
        ms = NULL;
    }
    if (bx != NULL) {
        if (fclose(bx) != 0) {
            bx = NULL;
            goto fail;
        }
        bx = NULL;
    }

    /* C13.2 SEASLINE.DAT: the earlier seasons' lines, then this season's step 3 lines */
    if (seasline_write(pre_dir, slname, sltmp, season_no) != 0)
        goto fail;
    nrt = load_retired(g_retpath, &rt);
    if (nrt < 0)
        goto fail;
    if (nrt > 0 && do_marks(pre_dir, tmp, rt, nrt) != 0)
        goto fail;
    free(rt);
    rt = NULL;
    if (f) {
        fclose(f);
        f = NULL;
    }
    /* swap the four temp files in: each original moves to its BAK first (a failed move
     * counts as a failed rename), then each temp lands in the order HISTORY, MILESTON,
     * BOXSCORE, SEASLINE. All four temps are complete before the first rename; a failure at
     * any step restores all four originals, removes the new files and leaves no TMP or BAK
     * behind (exit 2) */
    sw[0].fin = hpath;
    sw[0].tmp = tmp;
    sw[0].bak = bak;
    sw[1].fin = msname;
    sw[1].tmp = mstmp;
    sw[1].bak = msbak;
    sw[2].fin = boxname;
    sw[2].tmp = boxtmp;
    sw[2].bak = boxbak;
    sw[3].fin = slname;
    sw[3].tmp = sltmp;
    sw[3].bak = slbak;
    for (k = 0; k < SWAP_N; k++) {
        sw[k].moved = 0;
        sw[k].landed = 0;
    }
    for (k = 0; k < SWAP_N; k++) {
        FILE *probe = fopen(sw[k].fin, "rb");
        if (!probe)
            continue;
        fclose(probe);
        remove(sw[k].bak);
        if (rename(sw[k].fin, sw[k].bak) != 0)
            goto restore;
        sw[k].moved = 1;
    }
    for (k = 0; k < SWAP_N; k++) {
        if (rename(sw[k].tmp, sw[k].fin) != 0)
            goto restore;
        sw[k].landed = 1;
#ifdef TEST_FAIL_RENAME
        /* host-only test build: the last rename counts as failed after all temps landed */
        if (k == SWAP_N - 1)
            goto restore;
#endif
    }
    for (k = 0; k < SWAP_N; k++)
        if (sw[k].moved)
            remove(sw[k].bak);
    free(paths);
    return 0;
restore:
    for (k = 0; k < SWAP_N; k++)
        swap_undo(&sw[k]);
    free(paths);
    return 2;
fail:
    if (ms)
        fclose(ms);
    if (bx)
        fclose(bx);
    if (g)
        fclose(g);
    if (f)
        fclose(f);
    remove(tmp);
    remove(mstmp);
    remove(boxtmp);
    remove(sltmp);
    free(rt);
    free(paths);
    return 2;
}

static const char *bak_of(const char *hpath, char *dst, size_t cap)
{
    tmp_of(hpath, dst, cap, BAK_NAME);
    return dst;
}

/* ---------------- C16.2: /SNAP and /ARCHIVE ---------------- */

static char FARDATA g_p_scan[PATH_BUF];    /* list and stat scratch */
static char FARDATA g_p_from[PATH_BUF];
static char FARDATA g_p_to[PATH_BUF];
static char FARDATA g_p_mk[PATH_BUF];      /* make_dirs scratch */
static char FARDATA g_p_arch[PATH_BUF];    /* the Snn dir of /ARCHIVE */
static char FARDATA g_cpnames[CP_MAX][CP_NAME];
static uint8_t FARDATA g_cpbuf[2048];
static char FARDATA g_d_dir[PATH_BUF];     /* the current league's paths (lg_default) */
static char FARDATA g_d_snap[PATH_BUF];
static char FARDATA g_d_hist[PATH_BUF];
static char FARDATA g_d_ret[PATH_BUF];
static char FARDATA g_d_seas[PATH_BUF];

/* 1 when path is a directory */
static int is_dir(const char *path)
{
#ifdef __WATCOMC__
    unsigned attr = 0;
    return _dos_getfileattr(path, &attr) == 0 && (attr & _A_SUBDIR) != 0;
#else
    struct stat st;
    return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
#endif
}

/* makes path and each missing parent. DOS skips the drive ("C:"); the host makes it, a relative directory.
 * An existing directory is not an error. 1 when path is a directory afterwards */
static int make_dirs(const char *path)
{
    size_t i, l = strlen(path);
    if (l == 0 || l >= PATH_BUF)
        return 0;
    memcpy(g_p_mk, path, l + 1);
    for (i = 1; i <= l; i++) {
        char keep;
        if (i < l && g_p_mk[i] != '/' && g_p_mk[i] != '\\')
            continue;
#ifdef __WATCOMC__
        if (i == 2 && g_p_mk[1] == ':')
            continue;
#endif
        keep = g_p_mk[i];
        g_p_mk[i] = 0;
        (void)MK_DIR(g_p_mk);
        g_p_mk[i] = keep;
    }
    return is_dir(path);
}

/* the regular files directly in dir (no subdirectories) into g_cpnames, as named on disk. Returns their count,
 * -1 when dir cannot be listed, a name does not fit CP_NAME or there are more than CP_MAX */
#ifdef __WATCOMC__

static int list_files(const char *dir)
{
    struct find_t ft;
    int n = 0;
    if (!is_dir(dir) || !path_join(g_p_scan, PATH_BUF, dir, "*.*"))
        return -1;
    if (_dos_findfirst(g_p_scan, _A_NORMAL, &ft) != 0)
        return 0;
    do {
        if (ft.attrib & (_A_SUBDIR | _A_VOLID))
            continue;
        if (n >= CP_MAX || strlen(ft.name) >= CP_NAME)
            return -1;
        strcpy(g_cpnames[n], ft.name);
        n++;
    } while (_dos_findnext(&ft) == 0);
    return n;
}

#else

static int list_files(const char *dir)
{
    DIR *dirp = opendir(dir);
    struct dirent *de;
    int n = 0;
    if (!dirp)
        return -1;
    while ((de = readdir(dirp)) != NULL) {
        struct stat st;
        size_t l = strlen(de->d_name);
        if (!path_join(g_p_scan, PATH_BUF, dir, de->d_name)) {
            closedir(dirp);
            return -1;
        }
        if (stat(g_p_scan, &st) != 0 || !S_ISREG(st.st_mode))
            continue;
        if (n >= CP_MAX || l >= CP_NAME) {
            closedir(dirp);
            return -1;
        }
        memcpy(g_cpnames[n], de->d_name, l + 1);
        n++;
    }
    closedir(dirp);
    return n;
}

#endif

/* src copied byte for byte over dst (dst is overwritten): 0 on any failure */
static int copy_file(const char *src, const char *dst)
{
    FILE *in = fopen(src, "rb"), *out;
    size_t n;
    int ok = 1;
    if (!in)
        return 0;
    out = fopen(dst, "wb");
    if (!out) {
        fclose(in);
        return 0;
    }
    while ((n = fread(g_cpbuf, 1, sizeof g_cpbuf, in)) > 0) {
        if (fwrite(g_cpbuf, 1, n, out) != n) {
            ok = 0;
            break;
        }
    }
    if (ferror(in))
        ok = 0;
    if (fclose(out) != 0)
        ok = 0;
    fclose(in);
    return ok;
}

/* every regular file directly in src copied into dst, overwriting: 0 on success, 1 when src cannot be listed
 * or a copy fails. The same directory copies nothing (a file copied onto itself would be truncated first) */
static int copy_files(const char *src, const char *dst)
{
    int i, n = list_files(src);
    if (n < 0)
        return 1;
    if (strcmp(src, dst) == 0)
        return 0;
    for (i = 0; i < n; i++) {
        if (!path_join(g_p_from, PATH_BUF, src, g_cpnames[i])
            || !path_join(g_p_to, PATH_BUF, dst, g_cpnames[i])
            || !copy_file(g_p_from, g_p_to))
            return 1;
    }
    return 0;
}

/* the Snn dir of seasons for nn (S01..S99, as ARCHIVE.BAT names them) into out */
static int snn_path(const char *seasons, int nn, char *out)
{
    char sn[4];
    sn[0] = 'S';
    sn[1] = (char)('0' + nn / 10);
    sn[2] = (char)('0' + nn % 10);
    sn[3] = 0;
    return path_join(out, PATH_BUF, seasons, sn);
}

/* HISTWR /SNAP (C16.2): SNAP_DIR and its missing parents, then every regular file of LEAGUE_DIR copied in.
 * 0 on success, 1 when SNAP_DIR cannot be made, LEAGUE_DIR cannot be listed or a copy fails */
static int run_snap(const char *ldir, const char *sdir)
{
    if (!make_dirs(sdir))
        return 1;
    return copy_files(ldir, sdir);
}

/* HISTWR /ARCHIVE (C16.2): the first Snn of SEASONS_DIR with no *.MAJ (a missing one counts as free) gets every
 * regular file of SNAP_DIR. All 99 full: nothing copied, 0. 1 when SNAP_DIR is not a directory, a directory
 * cannot be made or a copy fails */
static int run_archive(const char *sdir, const char *seasons)
{
    int nn;
    if (!is_dir(sdir) || !make_dirs(seasons))
        return 1;
    for (nn = 1; nn <= ARCH_MAX; nn++) {
        if (!snn_path(seasons, nn, g_p_arch))
            return 1;
        if (scan_dir(g_p_arch, ".MAJ", g_mnames) < 1)
            break;
    }
    if (nn > ARCH_MAX)
        return 0;
    if (!make_dirs(g_p_arch))
        return 1;
    return copy_files(sdir, g_p_arch);
}

/* a path of the current league (C16.1) into out; 0 when it does not fit */
static int lg_default(int which, char *out)
{
    char lg[9];
    lg_current(".", lg);
    return lg_path(out, PATH_BUF, which, lg, DIR_SEP);
}

int main(int argc, char **argv)
{
    const char *pre, *hpath, *rpath;
    int k, rc;
    if (argc >= 2 && arg_is(argv[1], "/SNAP")) {
        if (argc == 2) {
            if (!lg_default(LG_DIR, g_d_dir) || !lg_default(LG_SNAP, g_d_snap))
                return 2;
            return run_snap(g_d_dir, g_d_snap);
        }
        return argc == 4 ? run_snap(argv[2], argv[3]) : 2;
    }
    if (argc >= 2 && arg_is(argv[1], "/ARCHIVE")) {
        if (argc == 2) {
            if (!lg_default(LG_SNAP, g_d_snap) || !lg_default(LG_SEASONS, g_d_seas))
                return 2;
            return run_archive(g_d_snap, g_d_seas);
        }
        return argc == 4 ? run_archive(argv[2], argv[3]) : 2;
    }
    if (argc >= 2 && arg_is(argv[1], "/LINES")) {
        const char *lh, *ls;
        if (argc == 4) {
            lh = argv[2];
            ls = argv[3];
        } else if (argc == 2) {
            if (!lg_default(LG_HIST, g_d_hist) || !lg_default(LG_SEASONS, g_d_seas))
                return 2;
            lh = g_d_hist;
            ls = g_d_seas;
        } else {
            return 2;
        }
        if (strlen(lh) >= 600 || strlen(ls) >= 600)
            return 2;
        return run_lines(lh, ls);
    }
    if (argc >= 4) {
        pre = argv[1];
        hpath = argv[2];
        rpath = argv[3];
    } else {
        if (!lg_default(LG_SNAP, g_d_snap) || !lg_default(LG_HIST, g_d_hist)
            || !lg_default(LG_RET, g_d_ret))
            return 2;
        pre = g_d_snap;
        hpath = g_d_hist;
        rpath = g_d_ret;
    }
    if (!fit_copy(g_retpath, sizeof g_retpath, rpath))
        return 2;                     /* RETIRED path too long */
    if (strlen(hpath) >= 600 || strlen(pre) >= 600)
        return 2;                     /* HIST/PRE path too long for built paths */
    if (!read_maj(pre, &g_maj))
        return 2;
    if (load_teams(pre, &g_maj) != 0)
        return 2;
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
