/* ROSTERS: C port of tools/m4/rosters.py, the C6 offseason
 * (notes/M4_CONTRACT.md C6; rosters.py is authoritative for every byte).
 * Host build: gcc (parity tests). DOS build: OpenWatcom 32-bit with the
 * DOS/32A extender bound in (build_rosters.py; a 16-bit large-model build ran
 * out of conventional memory on a mature league). The code still keeps every
 * object under 64 KB. One malloc per team image (11735 B) and per pool image; snapshots are
 * reduced to per-slot compact structs at load (no whole snapshot image kept).
 * Outputs all land in <path>.TMP files first and are renamed over the
 * originals only after every TMP write succeeded.
 * usage: ROSTERS [LEAGUE_DIR SNAP_DIR HIST_PATH RETIRED_PATH]
 * exit 0 ok, 2 on any error with every file untouched.
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

/* MAJ */
#define MAJ_SIZE   59771
#define MAJ_S_AL   0x21d
#define MAJ_S_NL   0x758c
#define MAJ_O_W    0x2cb
#define MAJ_O_L    0x2e3
#define MAJ_O_STEM 0x1d7

/* ---------------- T table (contract C6 module defaults) ---------------- */

#define T_SP_END       6
#define T_POOL_YEARS   1
#define T_KEEP_P       7
#define T_KEEP_B       10
#define T_REL_CAP      8
#define T_MKT          64
#define T_NEED         8
#define T_BAND         5
#define T_MAX_TRADES   6
#define T_POOL_KEEP_P  32
#define T_POOL_KEEP_B  48
#define T_FORM_A       16
static const uint8_t T_REL[4][4] = {
    { 32, 138, 66, 10 }, { 96, 240, 82, 10 },
    { 192, 255, 102, 16 }, { 255, 255, 154, 36 } };

#define POOL_FILES 4

#define DEF_LEAGUE "TEAMS\\CLASSIC"
#define DEF_SNAP   "C:\\DYNSNAP"
#define DEF_HIST   "TEAMS\\CLASSIC\\HISTORY.DAT"
#define DEF_RET    "C:\\DYNSNAP\\RETIRED.DAT"

#define MAXT 64
#define HIST_HDR_SIZE 32

/* ---------------- small utils ---------------- */

static uint16_t rd16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int path_join(char *dst, size_t cap, const char *a, const char *b)
{
    size_t l = strlen(a);
    if (l + 1 + strlen(b) + 1 > cap)
        return 0;
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

static void upname(char *dst, const char *src, int cap)
{
    int i;
    for (i = 0; src[i] && i < cap - 1; i++) {
        char c = src[i];
        dst[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : c;
    }
    dst[i] = 0;
}

static void to_upper_str(char *s)
{
    for (; *s; s++)
        if (*s >= 'a' && *s <= 'z') *s = (char)(*s - 32);
}

static void to_lower_str(char *s)
{
    for (; *s; s++)
        if (*s >= 'A' && *s <= 'Z') *s = (char)(*s + 32);
}

static int cmpname(const void *a, const void *b)
{
    return strcmp((const char *)a, (const char *)b);
}

static int issp(char c)
{
    return c == ' ' || (c >= 9 && c <= 13);
}

/* pname: First Last from the record name bytes, stripped */
static void pname(const uint8_t *r, char *dst)
{
    char last[13], first[9];
    int i, o, a;
    for (i = 0; i < 12 && r[i] != 0; i++) last[i] = (char)r[i];
    last[i] = 0;
    for (i = 0; i < 8 && r[12 + i] != 0; i++) first[i] = (char)r[12 + i];
    first[i] = 0;
    o = 0;
    for (i = 0; first[i]; i++) dst[o++] = first[i];
    dst[o++] = ' ';
    for (i = 0; last[i]; i++) dst[o++] = last[i];
    dst[o] = 0;
    a = 0;
    while (dst[a] && issp(dst[a])) a++;
    while (o > a && issp(dst[o - 1])) o--;
    if (a > 0) {
        for (i = 0; a + i <= o; i++) dst[i] = dst[a + i];
    } else {
        dst[o] = 0;
    }
}

/* ---------------- rng (m4.rollover.Rng, xorshift16) ---------------- */

static uint16_t g_rng;

static uint16_t rng_draw(void)
{
    unsigned int s = g_rng;
    s ^= (s << 7) & 0xffffu;
    s ^= s >> 9;
    s ^= (s << 8) & 0xffffu;
    g_rng = (uint16_t)(s & 0xffffu);
    return g_rng;
}

/* ---------------- directory listing ---------------- */

static char g_scan[MAXT][32];

#ifdef __WATCOMC__

static int scan_dir(const char *dir, const char *ext, char names[][32])
{
    static char pat[280];
    struct find_t ft;
    int dir_len = (int)strlen(dir);
    int n = 0;
    if (dir_len + 6 + (int)strlen(ext) >= (int)sizeof pat)
        return 0;
    memcpy(pat, dir, (size_t)dir_len);
    if (dir_len > 0 && pat[dir_len - 1] != '\\' && pat[dir_len - 1] != '/')
        pat[dir_len++] = '\\';
    pat[dir_len++] = '*';
    strcpy(pat + dir_len, ext);
    if (_dos_findfirst(pat, _A_NORMAL, &ft) != 0)
        return 0;
    do {
        if (n >= MAXT)
            break;
        upname(names[n], ft.name, 32);
        n++;
    } while (_dos_findnext(&ft) == 0);
    qsort(names, (size_t)n, 32, cmpname);
    return n;
}

#else

static int scan_dir(const char *dir, const char *ext, char names[][32])
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
            if (n >= MAXT)
                break;
            upname(names[n], de->d_name, 32);
            n++;
        }
    }
    closedir(dirp);
    qsort(names, (size_t)n, 32, cmpname);
    return n;
}

#endif

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

static int w_of(int age)
{
    static const int16_t WA[7][2] = { { 20, 179 }, { 22, 154 }, { 23, 141 },
        { 24, 102 }, { 25, 77 }, { 26, 38 }, { 27, 13 } };
    int i;
    for (i = 0; i < 7; i++)
        if (age <= WA[i][0])
            return WA[i][1];
    return 0;
}

static int discount_of(int age)
{
    static const int16_t DA[5][2] = { { 29, 256 }, { 31, 248 }, { 33, 236 },
        { 35, 220 }, { 37, 200 } };
    int i;
    for (i = 0; i < 5; i++)
        if (age <= DA[i][0])
            return DA[i][1];
    return 180;
}

static int g_of(int x)
{
    return (x <= 22) ? 90 : (x <= 24) ? 64 : 32;
}

static const uint16_t GM[6] = { 0, 1, 3, 4, 5, 7 };

static int32_t g_sum(int age, int grade)
{
    int x;
    int32_t sum = 0;
    if (age >= 26)
        return 0;
    if (grade)
        for (x = age + 1; x <= 26; x++)
            sum += (g_of(x) * (int32_t)GM[grade]) >> 2;
    else
        for (x = age + 1; x <= 26; x++)
            sum += g_of(x);
    return sum;
}

/* pot ratings then Spot = S computed on them (cap 10 endurance, 12 else) */
static int32_t spot_of(const uint8_t *r)
{
    int add = (int)((g_sum(r[R_AGE], r[R_GRADE]) + 128) >> 8);
    int ctrl = r[R_CV] & 15, vel = r[R_CV] >> 4, end = r[R_ENDUR] >> 4;
    int power = r[R_POWER] & 15, hit_run = r[R_HITRUN] & 15;
    int speed = r[R_SPEED] >> 4, rng_ = r[R_RANGE] >> 4, arm = r[R_RANGE] & 15;
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
    {
        int rw, aw;
        fld_w(pos1f(r), &rw, &aw);
        return 3 * power + 3 * hit_run + speed + rw * rng_ + aw * arm;
    }
}

/* V = (S*(256 - w) + Spot*w) >> 8 by age, then the age discount */
static int32_t v_of(const uint8_t *r)
{
    int age = r[R_AGE];
    int w = w_of(age);
    int32_t v = ((int32_t)score(r) * (256 - w) + (int32_t)spot_of(r) * w) >> 8;
    return (v * discount_of(age)) >> 8;
}

/* SP = 100, RP = 101 */
static int sp_rp(const uint8_t *r)
{
    return (r[R_ENDUR] >> 4) >= T_SP_END ? 100 : 101;
}

/* outs = (ip10 / 10) * 3 + ip10 % 10 (ip10 >= 0 here) */
static int32_t ipiv_outs(int32_t ip10)
{
    return (ip10 / 10) * 3 + ip10 % 10;
}

static int pt_class(int32_t games, int32_t pa, int32_t outs, int pitcher)
{
    if (games == 0)
        return 0;
    if (pitcher)
        return (outs < 90) ? 1 : (outs <= 299) ? 2 : 3;
    return (pa < 100) ? 1 : (pa <= 399) ? 2 : 3;
}

static int32_t lower_median(const int32_t *vals, int n)
{
    int32_t a[280];
    int i, j;
    for (i = 0; i < n; i++) a[i] = vals[i];
    for (i = 1; i < n; i++) {
        int32_t v = a[i];
        for (j = i - 1; j >= 0 && a[j] > v; j--)
            a[j + 1] = a[j];
        a[j + 1] = v;
    }
    return a[(n - 1) / 2];
}

/* ascending by (k1, k2), stable enough: k2 is always the slot so the key is
 * a total order */
typedef struct {
    int32_t k1;
    int32_t k2;
} SK;

static void sk_sort(SK *a, int n)
{
    int i, j;
    for (i = 1; i < n; i++) {
        SK v = a[i];
        for (j = i - 1; j >= 0 && (a[j].k1 > v.k1
             || (a[j].k1 == v.k1 && a[j].k2 > v.k2)); j--)
            a[j + 1] = a[j];
        a[j + 1] = v;
    }
}

/* ---------------- image helpers ---------------- */

static void vacate(uint8_t *img, int slot)
{
    uint8_t *ro = img + V20_HDR + V20_REC * slot;
    uint8_t *so = img + V20_HDR + V20_REC * (slot + 40);
    memset(ro, 0, V20_REC);
    memset(so, 0, V20_REC);
}

static void write_pair(uint8_t *img, int slot, const uint8_t *pair)
{
    memcpy(img + V20_HDR + V20_REC * slot, pair, V20_REC);
    memcpy(img + V20_HDR + V20_REC * (slot + 40), pair + V20_REC, V20_REC);
}

static void write_pool_years(uint8_t *img, int slot, int v)
{
    img[V20_HDR + V20_REC * slot + R_PYEAR] = (uint8_t)(v & 0xff);
    img[V20_HDR + V20_REC * (slot + 40) + R_PYEAR] = (uint8_t)(v & 0xff);
}

/* Year = record byte 21 + 1870 of the first named record, -1 when none */
static int image_year(const uint8_t *img)
{
    int i;
    for (i = 0; i < V20_N; i++) {
        int32_t base = V20_HDR + V20_REC * i;
        if (img[base])
            return img[base + R_YEAR] + 1870;
    }
    return -1;
}

static uint8_t *pool_blank_new(const uint8_t *t0)
{
    uint8_t *d = (uint8_t *)malloc(V20_SIZE);
    if (!d)
        return NULL;
    memset(d, 0, V20_SIZE);
    memcpy(d, "FREE AGENTS", 11);
    memcpy(d + 14, t0 + 14, 2);
    return d;
}

/* ---------------- team state ---------------- */

typedef struct {
    int16_t ap[10];
    int n_ap;
    int16_t rot[5];
    int n_rot;
    int16_t relief[5];
    int n_relief;
    int16_t fslot[8];
    int8_t fpos[8];
    int n_field;
    int16_t dh;
    int16_t backupc;
    int16_t ab[15];
    int n_ab;
    int16_t order[10];
    int n_order;
    int16_t bench7[16];
    int n_b7;
} Part;

typedef struct {
    uint8_t *img;                  /* 11735 B, one malloc per team */
    char fname[32];                /* upper-case 8.3 file name with .V20 */
    char stem_lc[32];
    char stem_up[32];
    int32_t lg;                    /* league-global id 0..31 */
    uint8_t managed;
    uint8_t retflag[40];
    int has_snap;
    /* per-slot compact snapshot: what offseason() reads of SNAP_DIR files */
    uint8_t snap_named[40];        /* snapshot roster byte 0 != 0 */
    uint8_t snap_rookie[40];       /* both halves vacant in the snapshot */
    uint8_t snap_name[40][20];     /* snapshot name bytes (zero filled) */
    uint8_t snap_pt_pitcher[40];
    uint8_t snap_pt_games[40];
    uint32_t snap_pt_pa[40];       /* pa (bat) or outs (pit) class input */
    Part part;
} Team;

/* One pool-list capture, order-preserving. Nodes are malloc'd one by one so
 * no allocation exceeds the DOS 64 KB object limit. */
typedef struct {
    int32_t team;                  /* team index, -1 = a pool file player */
    int32_t pi;                    /* pool file index */
    int32_t pslot;                 /* pool slot or team slot */
    uint8_t pair[2][V20_REC];
    uint8_t state;                 /* 0 free, 1 signed, 2 taken this round */
} Move;

static Team *g_tp[MAXT];
static int g_nt;
static uint8_t *g_pool[POOL_FILES];
static Move **g_pmv, **g_tmv;      /* pool list players / team move order */
static int32_t g_npm, g_pcap, g_ntm, g_tcap;
static uint8_t g_stand_w[32], g_stand_l[32];
static char g_maj_stem[32][9];
static uint8_t g_maj_cmp[32];      /* stem has no interior NUL */
static uint8_t g_hist32[HIST_HDR_SIZE];   /* working header (offseason) */
static char g_lgdir[600], g_snapdir[600], g_histpath[600], g_retpath[600];
static FILE *g_ev;
static int g_era, g_fa, g_year;

static int32_t n_moves(void)
{
    return g_npm + g_ntm;
}

static Move *move_at(int32_t i)
{
    return (i < g_npm) ? g_pmv[i] : g_tmv[i - g_npm];
}

static Move *list_add(Move ***arr, int32_t *n, int32_t *cap)
{
    Move *m;
    if (*n >= *cap) {
        Move **nn;
        int32_t nc = *cap + 64;
        nn = (Move **)realloc(*arr, (size_t)nc * sizeof(Move *));
        if (!nn)
            return NULL;
        *arr = nn;
        *cap = nc;
    }
    m = (Move *)calloc(1, sizeof(Move));
    if (!m)
        return NULL;
    m->team = -1;
    m->pi = -1;
    (*arr)[(*n)++] = m;
    return m;
}

static Move *pm_add(void)
{
    return list_add(&g_pmv, &g_npm, &g_pcap);
}

static Move *tm_add(void)
{
    return list_add(&g_tmv, &g_ntm, &g_tcap);
}

/* ---------------- event log (ROSTERS.TMP, CRLF lines) ---------------- */

static void ev_p(const char *code, const char *p1, const char *p2,
                 const char *p3, const char *p4)
{
    char line[200];
    size_t o = 0, l;
    l = strlen(code);
    memcpy(line, code, l);
    o = l;
    if (p1) { l = strlen(p1); line[o++] = ' '; memcpy(line + o, p1, l); o += l; }
    if (p2) { l = strlen(p2); line[o++] = ' '; memcpy(line + o, p2, l); o += l; }
    if (p3) { l = strlen(p3); line[o++] = ' '; memcpy(line + o, p3, l); o += l; }
    if (p4) { l = strlen(p4); line[o++] = ' '; memcpy(line + o, p4, l); o += l; }
    line[o++] = '\r';
    line[o++] = '\n';
    if (g_ev)
        fwrite(line, 1, o, g_ev);
}

/* ---------------- MAJ: stems + standings ---------------- */

static int load_maj(const char *dir)
{
    int n, k;
    char path[640];
    FILE *f;
    long sz;
    uint8_t *buf;
    n = scan_dir(dir, ".MAJ", g_scan);
    if (n < 1)
        return -1;
    if (!path_join(path, sizeof path, dir, g_scan[0]))
        return -1;
    f = fopen(path, "rb");
    if (!f)
        return -1;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return -1; }
    sz = ftell(f);
    if (sz != MAJ_SIZE) { fclose(f); return -1; }
    if (fseek(f, 0, SEEK_SET) != 0) { fclose(f); return -1; }
    buf = (uint8_t *)malloc(MAJ_SIZE);
    if (!buf) { fclose(f); return -1; }
    if (fread(buf, 1, MAJ_SIZE, f) != MAJ_SIZE) {
        free(buf);
        fclose(f);
        return -1;
    }
    fclose(f);
    for (k = 0; k < 2; k++) {
        int s0 = k ? MAJ_S_NL : MAJ_S_AL;
        int slot, i;
        for (slot = 0; slot < 16; slot++) {
            int idx = k * 16 + slot;
            const uint8_t *sp = buf + s0 + MAJ_O_STEM + 8 * slot;
            int e = 8;
            while (e > 0 && sp[e - 1] == 0)
                e--;
            for (i = 0; i < e; i++)
                g_maj_stem[idx][i] = (char)sp[i];
            g_maj_stem[idx][e] = 0;
            to_lower_str(g_maj_stem[idx]);
            for (i = 0; i < e && sp[i] != 0; i++)
                ;
            g_maj_cmp[idx] = (i == e) ? 1 : 0;    /* interior NUL */
            g_stand_w[idx] = buf[s0 + MAJ_O_W + slot];
            g_stand_l[idx] = buf[s0 + MAJ_O_L + slot];
        }
    }
    free(buf);
    return 0;
}

/* ---------------- team files ---------------- */

static int load_team_file(const char *dir, const char *fname,
                          const char *stemlc, int32_t lg)
{
    char path[640];
    FILE *f;
    uint8_t *img;
    Team *t;
    if (!path_join(path, sizeof path, dir, fname))
        return -1;
    f = fopen(path, "rb");
    if (!f)
        return -1;
    img = (uint8_t *)malloc(V20_SIZE);
    if (!img) { fclose(f); return -1; }
    if (fread(img, 1, V20_SIZE, f) != V20_SIZE) {
        free(img);
        fclose(f);
        return -1;                    /* not a full team image */
    }
    fclose(f);
    t = (Team *)calloc(1, sizeof(Team));
    if (!t) { free(img); return -1; }
    t->img = img;
    fit_copy(t->fname, sizeof t->fname, fname);
    fit_copy(t->stem_lc, sizeof t->stem_lc, stemlc);
    fit_copy(t->stem_up, sizeof t->stem_up, stemlc);
    to_upper_str(t->stem_up);
    t->lg = lg;
    g_tp[g_nt++] = t;
    return 0;
}

static int load_teams(const char *dir)
{
    int n = scan_dir(dir, ".V20", g_scan);
    int k;
    for (k = 0; k < n; k++) {
        char stem[32];
        int32_t lg = -1;
        int s, l = (int)strlen(g_scan[k]);
        if (l <= 4 || l - 4 > 30)
            continue;
        memcpy(stem, g_scan[k], (size_t)l - 4);
        stem[l - 4] = 0;
        to_lower_str(stem);
        /* mapped_teams: every matching MAJ slot, the last one wins (AL
         * slots 0..15 then NL 16..31) */
        for (s = 0; s < 32; s++) {
            if (!g_maj_cmp[s])
                continue;
            if (strcmp(stem, g_maj_stem[s]) == 0)
                lg = s;
        }
        if (lg < 0)
            continue;
        if (g_nt >= MAXT)
            return -1;
        if (load_team_file(dir, g_scan[k], stem, lg) != 0)
            return -1;
    }
    {
        int slot;
        for (slot = 0; slot < g_nt; slot++)
            if (g_tp[slot] == NULL)
                return -1;
    }
    return 0;
}
static int load_pools(void)
{
    int p;
    for (p = 0; p < POOL_FILES; p++) {
        char nm[16], path[640];
        FILE *f;
        uint8_t *img;
        sprintf(nm, "POOL%d.V20", p + 1);
        if (!path_join(path, sizeof path, g_lgdir, nm))
            return -1;
        f = fopen(path, "rb");
        if (!f) {
            g_pool[p] = pool_blank_new(g_tp[0]->img);
            if (!g_pool[p])
                return -1;
            continue;
        }
        img = (uint8_t *)malloc(V20_SIZE);
        if (!img) { fclose(f); return -1; }
        if (fread(img, 1, V20_SIZE, f) != V20_SIZE) {
            free(img);
            fclose(f);
            return -1;
        }
        fclose(f);
        g_pool[p] = img;
    }
    return 0;
}

/* ---------------- snapshots ---------------- */

/* Reduce SNAP_DIR/<STEM>.V20 to the per-slot compact struct. An unreadable
 * or truncated file is an error (the reference would IndexError), except a
 * plain missing file = snap None semantics. */
static int load_snap(Team *t)
{
    char path[640];
    FILE *f;
    long sz;
    uint8_t *buf;
    size_t got;
    int s;
    if (!path_join(path, sizeof path, g_snapdir, t->stem_up))
        return -1;
    strcat(path, ".V20");
    f = fopen(path, "rb");
    if (!f) {
        t->has_snap = 0;
        return 0;
    }
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return -1; }
    sz = ftell(f);
    if (sz < 0 || sz > 60000L) { fclose(f); return -1; }   /* one DOS object; a V20 is 11735 B */
    if (fseek(f, 0, SEEK_SET) != 0) { fclose(f); return -1; }
    buf = (uint8_t *)malloc((size_t)sz);
    if (!buf) { fclose(f); return -1; }
    got = fread(buf, 1, (size_t)sz, f);
    fclose(f);
    if (got != (size_t)sz) { free(buf); return -1; }
    /* rookie_flag and pt_of index snap[base] and snap[base_so] of every
     * slot, and the pt read needs the season record through ip10/bb_r */
    if ((int32_t)got < V20_HDR + V20_REC * 40 + 0x18
        || (int32_t)got < V20_HDR + V20_REC * 40 + 0x39) {
        free(buf);
        return -1;
    }
    t->has_snap = 1;
    for (s = 0; s < 40; s++) {
        int32_t base = V20_HDR + V20_REC * s;
        int32_t base_so = V20_HDR + V20_REC * (s + 40);
        if (t->img[base] == 0)
            continue;                  /* vacant now: no snapshot access */
        if (buf[base] != 0) {
            int j;
            t->snap_named[s] = 1;
            for (j = 0; j < 20; j++)
                t->snap_name[s][j] = buf[base + j];
            if (base + 0x20 > (int32_t)got) { free(buf); return -1; }
            t->snap_pt_pitcher[s] = (uint8_t)((buf[base + 0x1f] & 15) == 0);
            t->snap_pt_games[s] = buf[base_so + 0x17];
            if (t->snap_pt_pitcher[s]) {
                if (base_so + 0x67 > (int32_t)got) { free(buf); return -1; }
                t->snap_pt_pa[s] = (uint32_t)ipiv_outs(
                    (int32_t)rd16(buf + base_so + 0x65));
            } else {
                if (base_so + 0x39 > (int32_t)got) { free(buf); return -1; }
                t->snap_pt_pa[s] = (uint32_t)rd16(buf + base_so + 0x25)
                                 + (uint32_t)rd16(buf + base_so + 0x27)
                                 + (uint32_t)rd16(buf + base_so + 0x35)
                                 + (uint32_t)rd16(buf + base_so + 0x37);
            }
        } else {
            /* vacant in the snapshot: the C4 rookie needs both halves */
            t->snap_rookie[s] = (uint8_t)(buf[base_so] == 0);
        }
    }
    free(buf);
    return 0;
}

/* ---------------- RETIRED.DAT ---------------- */

typedef struct {
    char stem[32];
    uint8_t flags[40];
} RetEntry;

static RetEntry g_ret[MAXT];
static int g_nret;

static void parse_retired(const char *path)
{
    FILE *f;
    long sz;
    uint8_t *b;
    size_t got;
    int off, i, n;
    g_nret = 0;
    if (!path || !path[0])
        return;
    f = fopen(path, "rb");
    if (!f)
        return;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return; }
    sz = ftell(f);
    if (sz <= 0 || sz > MAXT * 54) { fclose(f); return; }
    if (fseek(f, 0, SEEK_SET) != 0) { fclose(f); return; }
    b = (uint8_t *)malloc((size_t)sz);
    if (!b) { fclose(f); return; }
    got = fread(b, 1, (size_t)sz, f);
    fclose(f);
    if ((long)got < 1) { free(b); return; }
    n = b[0];
    off = 1;
    for (i = 0; i < n && g_nret < MAXT; i++) {
        int j;
        char nm[16];
        int l = 0;
        if (off + 53 > (long)got)
            break;
        for (j = 0; j < 13 && b[off + j] != 0; j++) nm[l++] = (char)b[off + j];
        nm[l] = 0;
        for (j = 0; j < l; j++)
            if (nm[j] == '.') { nm[j] = 0; break; }
        to_lower_str(nm);
        fit_copy(g_ret[g_nret].stem, sizeof g_ret[g_nret].stem, nm);
        for (j = 0; j < 40; j++)
            g_ret[g_nret].flags[j] = b[off + 13 + j] ? 1 : 0;
        g_nret++;
        off += 53;
    }
    free(b);
}

static void ret_apply(void)
{
    int k, e;
    for (k = 0; k < g_nt; k++)
        memset(g_tp[k]->retflag, 0, 40);
    for (e = 0; e < g_nret; e++)
        for (k = 0; k < g_nt; k++)
            if (strcmp(g_ret[e].stem, g_tp[k]->stem_lc) == 0)
                memcpy(g_tp[k]->retflag, g_ret[e].flags, 40);
}

/* ---------------- rebuild: step 7 assignment ---------------- */

static int32_t fmv(const int32_t *form, int s)
{
    return form ? form[s] : 0;
}

static void build_partition(const uint8_t *img, Part *p, const int32_t *form)
{
    SK a[40];
    int na;
    int pits[16], np = 0, bats[24], nb = 0;
    uint8_t assigned[40];
    int i, s, qi;
    static const int FIELD_ORDER[8] = { 1, 5, 3, 7, 4, 8, 6, 2 };

    memset(p, 0, sizeof *p);
    memset(assigned, 0, sizeof assigned);
    p->dh = -1;
    p->backupc = -1;
    for (s = 0; s < 16; s++) if (IS_ON(img, s)) pits[np++] = s;
    for (s = 16; s < 40; s++) if (IS_ON(img, s)) bats[nb++] = s;

    /* active_p: 10 pitchers by (-S + fm, slot) */
    na = 0;
    for (i = 0; i < np; i++) {
        a[na].k1 = -((int32_t)score(RIMG(img, pits[i])) + fmv(form, pits[i]));
        a[na].k2 = pits[i];
        na++;
    }
    sk_sort(a, na);
    p->n_ap = (na < 10) ? na : 10;
    for (i = 0; i < p->n_ap; i++) p->ap[i] = (int16_t)a[i].k2;

    /* rotation: up to 5 by (-3c+3v+4e, slot) */
    na = 0;
    for (i = 0; i < p->n_ap; i++) {
        s = p->ap[i];
        a[na].k1 = -pitch_score4(RIMG(img, s));
        a[na].k2 = s;
        na++;
    }
    sk_sort(a, na);
    p->n_rot = (na < 5) ? na : 5;
    for (i = 0; i < p->n_rot; i++) p->rot[i] = (int16_t)a[i].k2;

    /* relief: the other active pitchers by (-3c+3v, slot) */
    na = 0;
    for (i = 0; i < p->n_ap; i++) {
        int j, inrot = 0;
        s = p->ap[i];
        for (j = 0; j < p->n_rot; j++)
            if (p->rot[j] == s) { inrot = 1; break; }
        if (!inrot) {
            a[na].k1 = -relief_score2(RIMG(img, s));
            a[na].k2 = s;
            na++;
        }
    }
    sk_sort(a, na);
    p->n_relief = na;
    for (i = 0; i < na; i++) p->relief[i] = (int16_t)a[i].k2;

    /* field: 8 (slot, q) greedy in C SS 2B CF 3B RF LF 1B order, ties lowest
     * slot; the -20 fallback every time no can_play candidate exists */
    for (qi = 0; qi < 8; qi++) {
        int q = FIELD_ORDER[qi];
        int best = -1;
        int32_t bv = 0;
        int any = 0, i2;
        for (i2 = 0; i2 < nb; i2++) {
            s = bats[i2];
            if (!assigned[s] && can_play(RIMG(img, s), q)) {
                any = 1;
                break;
            }
        }
        for (i = 0; i < nb; i++) {
            int32_t v;
            s = bats[i];
            if (assigned[s])
                continue;
            if (any != can_play(RIMG(img, s), q))
                continue;              /* cands = same group as the first */
            if (any) {
                v = offv(RIMG(img, s)) + fld_of(RIMG(img, s), q)
                  + fmv(form, s);
            } else {
                v = offv(RIMG(img, s)) + fld_of(RIMG(img, s), q) - 20
                  + fmv(form, s);
            }
            if (best < 0 || v > bv) { best = s; bv = v; }
        }
        if (best >= 0) {
            p->fslot[p->n_field] = (int16_t)best;
            p->fpos[p->n_field] = (int8_t)q;
            p->n_field++;
            assigned[best] = 1;
        }
    }

    /* DH: the best Off + fm of the rest */
    {
        int best = -1;
        int32_t bv = 0;
        for (i = 0; i < nb; i++) {
            int32_t v;
            s = bats[i];
            if (assigned[s])
                continue;
            v = offv(RIMG(img, s)) + fmv(form, s);
            if (best < 0 || v > bv) { best = s; bv = v; }
        }
        if (best >= 0) { p->dh = (int16_t)best; assigned[best] = 1; }
    }

    /* backup C: the best Fld(1) of the rest, no form offset */
    {
        int best = -1;
        int32_t bv = 0;
        for (i = 0; i < nb; i++) {
            int32_t v;
            s = bats[i];
            if (assigned[s] || !can_play(RIMG(img, s), 1))
                continue;
            v = fld_of(RIMG(img, s), 1);
            if (best < 0 || v > bv) { best = s; bv = v; }
        }
        if (best >= 0) { p->backupc = (int16_t)best; assigned[best] = 1; }
    }

    /* the rest of the active batters fill to 15 by (-S + fm, slot) */
    {
        int n_reserved = p->n_field + (p->dh >= 0 ? 1 : 0)
                       + (p->backupc >= 0 ? 1 : 0);
        int take = 15 - n_reserved;
        if (take < 0)
            take = 0;
        na = 0;
        for (i = 0; i < nb; i++) {
            s = bats[i];
            if (assigned[s])
                continue;
            a[na].k1 = -((int32_t)score(RIMG(img, s)) + fmv(form, s));
            a[na].k2 = s;
            na++;
        }
        sk_sort(a, na);
        if (take > na)
            take = na;
        p->n_ab = 0;
        for (i = 0; i < p->n_field; i++) p->ab[p->n_ab++] = p->fslot[i];
        if (p->dh >= 0) p->ab[p->n_ab++] = p->dh;
        if (p->backupc >= 0) p->ab[p->n_ab++] = p->backupc;
        for (i = 0; i < take; i++) p->ab[p->n_ab++] = (int16_t)a[i].k2;

        /* batting order over the 9 starters (DH sets), no form offsets */
        na = 0;
        for (i = 0; i < p->n_field; i++) {
            a[na].k1 = -offv(RIMG(img, p->fslot[i]));
            a[na].k2 = p->fslot[i];
            na++;
        }
        if (p->dh >= 0) {
            a[na].k1 = -offv(RIMG(img, p->dh));
            a[na].k2 = p->dh;
            na++;
        }
        sk_sort(a, na);
        p->n_order = na;
        for (i = 0; i < na; i++) p->order[i] = (int16_t)a[i].k2;

        /* bench7: the other active batters by (-S + fm, slot) */
        na = 0;
        for (i = 0; i < p->n_ab; i++) {
            int j, infield = 0;
            s = p->ab[i];
            for (j = 0; j < p->n_field; j++)
                if (p->fslot[j] == s) { infield = 1; break; }
            if (infield)
                continue;
            if (s < 16 || s > 39 || !IS_ON(img, s))
                continue;              /* bench7 = named slots only */
            a[na].k1 = -((int32_t)score(RIMG(img, s)) + fmv(form, s));
            a[na].k2 = s;
            na++;
        }
        sk_sort(a, na);
        p->n_b7 = na;
        for (i = 0; i < na; i++) p->bench7[i] = (int16_t)a[i].k2;
    }
}

/* one order_lineup pick: max key, ties lowest slot, removed from left */
static int32_t ol_key(int mode, const uint8_t *r)
{
    switch (mode) {
    case 0: return 3 * (r[R_SPEED] >> 4) + 2 * (r[R_HITRUN] & 15);
    case 1: return 2 * (r[R_HITRUN] & 15) + (r[R_SPEED] >> 4);
    case 2: return offv(r);
    case 3: return r[R_POWER] & 15;
    case 4: return 3 * (r[R_POWER] & 15) + (r[R_HITRUN] & 15);
    default: return offv(r);
    }
}

static int ol_pick(int16_t *left, int *nl, const uint8_t *img, int mode)
{
    int i, bi = 0;
    int32_t bv = ol_key(mode, RIMG(img, left[0]));
    for (i = 1; i < *nl; i++) {
        int32_t v = ol_key(mode, RIMG(img, left[i]));
        if (v > bv || (v == bv && left[i] < left[bi])) { bv = v; bi = i; }
    }
    i = left[bi];
    for (; bi + 1 < *nl; bi++) left[bi] = left[bi + 1];
    (*nl)--;
    return i;
}

static int ol_pos(const Part *p, int s)
{
    int i;
    for (i = 0; i < p->n_field; i++)
        if (p->fslot[i] == s)
            return p->fpos[i];
    return 9;                          /* the DH */
}

static void order_lineup(const uint8_t *img, int16_t *starters, int n,
                         const Part *p, int16_t *out_s, int8_t *out_q)
{
    int16_t left[10];
    int nl = n, i, o = 0;
    static const int MODES[5] = { 0, 1, 2, 3, 4 };
    for (i = 0; i < n; i++) left[i] = starters[i];
    for (i = 0; i < 5 && nl > 0; i++)
        out_s[o++] = (int16_t)ol_pick(left, &nl, img, MODES[i]);
    while (nl > 0)
        out_s[o++] = (int16_t)ol_pick(left, &nl, img, 5);
    for (i = 0; i < o; i++)
        out_q[i] = (int8_t)ol_pos(p, out_s[i]);
}

static void depth_rebuild(Team *t, const int32_t *form)
{
    uint8_t *img = t->img;
    Part *p = &t->part;
    int i, dh_flag, vs, s;
    int16_t dsl[10], ndl[10];
    int8_t dq[10], nq[10];
    int nd, nn;

    build_partition(img, p, form);
    /* staff +111..+120 (rotation then relievers), +110 = 0, +121 = 0xff */
    for (i = 0; i < 5; i++)
        img[H_STAFF + i] = (i < p->n_rot) ? (uint8_t)p->rot[i] : 0xff;
    for (i = 0; i < 5; i++)
        img[H_STAFF + 5 + i] = (i < p->n_relief) ? (uint8_t)p->relief[i]
                                                 : 0xff;
    img[H_STAFF - 1] = 0;
    img[H_STAFF + 10] = 0xff;

    nd = p->n_field + (p->dh >= 0 ? 1 : 0);
    for (i = 0; i < p->n_field; i++) dsl[i] = p->fslot[i];
    if (p->dh >= 0) dsl[p->n_field] = p->dh;
    order_lineup(img, dsl, nd, p, dsl, dq);
    nn = p->n_field;
    for (i = 0; i < nn; i++) ndl[i] = p->fslot[i];
    order_lineup(img, ndl, nn, p, ndl, nq);

    for (dh_flag = 0; dh_flag <= 1; dh_flag++) {
        int16_t *sl = dh_flag ? dsl : ndl;
        int8_t *qq = dh_flag ? dq : nq;
        int nf = dh_flag ? nd : nn;
        for (vs = 0; vs <= 1; vs++) {
            int lo = H_LINEUP + dh_flag * 18 + vs * 9;
            int po = H_DEF + dh_flag * 18 + vs * 9;
            for (i = 0; i < 9; i++) {
                if (i < nf) {
                    img[lo + i] = (uint8_t)sl[i];
                    img[po + i] = (uint8_t)qq[i];
                } else {
                    img[lo + i] = 0xff;
                    img[po + i] = 0;
                }
            }
            /* bench +194: the other active batters by S desc (no-DH: 7
             * entries incl. the DH; DH: 6 then 0xff) */
            {
                int b = H_BENCH + dh_flag * 14 + vs * 7;
                uint8_t bench[20];
                int nb2 = 0;
                int n = dh_flag ? 6 : 7;
                for (i = 0; i < p->n_b7; i++) {
                    s = p->bench7[i];
                    if (dh_flag && p->dh >= 0 && s == p->dh)
                        continue;
                    bench[nb2++] = (uint8_t)s;
                    if (nb2 == n)
                        break;
                }
                for (i = 0; i < 7; i++)
                    img[b + i] = (i < nb2) ? bench[i] : 0xff;
            }
        }
    }
    /* reserves +222..+236: the 6 inactive pitchers, then 9 inactive batters */
    {
        uint8_t res[15];
        int nr = 0;
        for (i = 0; i < 16 && nr < 6; i++) {
            int j, used = 0;
            if (!IS_ON(img, i))
                continue;
            for (j = 0; j < p->n_ap; j++)
                if (p->ap[j] == i) { used = 1; break; }
            if (!used)
                res[nr++] = (uint8_t)i;
        }
        for (i = 16; i < 40 && nr < 15; i++) {
            int j, used = 0;
            if (!IS_ON(img, i))
                continue;
            for (j = 0; j < p->n_ab; j++)
                if (p->ab[j] == i) { used = 1; break; }
            if (!used)
                res[nr++] = (uint8_t)i;
        }
        for (i = 0; i < 15; i++)
            img[H_RESERVE + i] = (i < nr) ? res[i] : 0xff;
    }
}

/* ---------------- C9 All-Star refresh ---------------- */

/* candidates: (team index, slot) pairs in file order then slot order; the
 * records are re-read at compare time (the team images do not change during
 * the refresh), so this stays under the DOS 64 KB object limit */
static uint8_t g_star_cand[2560][2];
static uint8_t g_star_used[2560];
static int g_nstar_cand;
static uint8_t *g_star_img[2];     /* the loaded ALLSTAR1 / ALLSTAR2 images */
static int32_t g_star_tmp[2];      /* g_tmps index of each, -1 = skipped */

/* one best() over the star candidates. ok: 0 = any pitcher, 1 = batter with
 * pos1 == q, 2 = batter that can play q, 3 = any batter. key: 0 = Score,
 * 1 = Off + Fld(q). Max key, ties keep the earliest candidate. -1 = none. */
static int star_best(int ok, int q, int key)
{
    int k, pick = -1;
    int32_t pv = 0;
    for (k = 0; k < g_nstar_cand; k++) {
        const uint8_t *r;
        int32_t v;
        if (g_star_used[k])
            continue;
        r = RIMG(g_tp[g_star_cand[k][0]]->img, g_star_cand[k][1]);
        if (ok == 0) {
            if (!is_pitcher(r))
                continue;
        } else {
            if (is_pitcher(r))
                continue;
            if (ok == 1 && pos1f(r) != q)
                continue;
            if (ok == 2 && !can_play(r, q))
                continue;
        }
        v = key ? offv(r) + fld_of(r, q) : (int32_t)score(r);
        if (pick < 0 || v > pv) { pick = k; pv = v; }
    }
    return pick;
}

/* rebuild one ALLSTAR image in place from the teams whose league-global id
 * is in lg_base..lg_base + 15 (rosters.py allstar_refresh) */
static void allstar_refresh(uint8_t *star, int32_t lg_base)
{
    int t, s, i;
    g_nstar_cand = 0;
    for (t = 0; t < g_nt; t++) {
        if (g_tp[t]->lg < lg_base || g_tp[t]->lg >= lg_base + 16)
            continue;
        for (s = 0; s < 40; s++) {
            if (!IS_ON(g_tp[t]->img, s))
                continue;
            g_star_cand[g_nstar_cand][0] = (uint8_t)t;
            g_star_cand[g_nstar_cand][1] = (uint8_t)s;
            g_nstar_cand++;
        }
    }
    memset(g_star_used, 0, sizeof g_star_used);
    for (i = 0; i < 40; i++) {
        uint8_t *o = RIMG(star, i);
        int k;
        if (o[0] == 0)
            continue;
        if (i < 16) {
            k = star_best(0, 0, 0);
        } else {
            int q = pos1f(o);
            k = star_best(1, q, 0);
            if (k < 0)
                k = star_best(2, q, 1);
            if (k < 0)
                k = star_best(3, q, 0);
        }
        if (k < 0) {
            vacate(star, i);
            continue;
        }
        g_star_used[k] = 1;
        {
            uint8_t *img = g_tp[g_star_cand[k][0]]->img;
            s = g_star_cand[k][1];
            memcpy(o, RIMG(img, s), V20_REC);
            memcpy(RIMG(star, i + 40), RIMG(img, s + 40), V20_REC);
        }
    }
    {
        static Team st;                /* depth_rebuild reads img and part only */
        memset(&st, 0, sizeof st);
        st.img = star;
        depth_rebuild(&st, NULL);
    }
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

static void changed_slots(const Team *t, uint8_t *chg)
{
    int s;
    for (s = 0; s < 40; s++) {
        int32_t base = V20_HDR + V20_REC * s;
        if (t->img[base] == 0) { chg[s] = 1; continue; }
        chg[s] = 0;
        if (!t->has_snap)
            continue;
        /* the reference compares snap[base:base+20] with img[base:base+20]:
         * a shorter snapshot slice or any byte difference = changed (the
         * active flag check is then redundant) */
        if (memcmp(t->snap_name[s], t->img + base, 20) != 0)
            chg[s] = 1;
    }
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
        if (slot == 0xff)
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

/* ---------------- offseason core ---------------- */

static int pt_of(const Team *t, int slot)
{
    if (!t->has_snap || t->snap_named[slot] == 0 || t->snap_rookie[slot]
        || t->retflag[slot] == 1)
        return 0;
    if (t->snap_pt_pitcher[slot])
        return pt_class(t->snap_pt_games[slot], 0,
                        (int32_t)t->snap_pt_pa[slot], 1);
    return pt_class(t->snap_pt_games[slot], (int32_t)t->snap_pt_pa[slot],
                    0, 0);
}

static void rev_order(int *idx, int n)
{
    int a, b;
    for (a = 0; a < n; a++) idx[a] = a;
    for (a = 0; a < n; a++)
        for (b = a + 1; b < n; b++) {
            int ka = idx[a], kb = idx[b];
            int32_t w1 = g_stand_w[g_tp[ka]->lg], l1 = g_stand_l[g_tp[ka]->lg];
            int32_t w2 = g_stand_w[g_tp[kb]->lg], l2 = g_stand_l[g_tp[kb]->lg];
            int32_t s1 = (w1 || l1) ? w1 * (w2 + l2) : (w2 + l2);
            int32_t s2 = (w2 || l2) ? w2 * (w1 + l1) : (w1 + l1);
            if (s1 > s2 || (s1 == s2 && ka > kb)) {
                idx[a] = kb;
                idx[b] = ka;
            }
        }
}

static void team_ranks(const Team *t, int32_t rb[16], uint8_t rbv[16],
                       int32_t *rsp, int32_t *rrp)
{
    int s, i, j, p;
    int32_t sp[16], rp[16];
    int nsp = 0, nrp = 0;
    for (i = 0; i < 16; i++) rbv[i] = 0;
    for (s = 16; s < 40; s++) {
        const uint8_t *r;
        int32_t v;
        if (!IS_ON(t->img, s))
            continue;
        r = RIMG(t->img, s);
        p = pos1f(r);
        v = v_of(r);
        if (!rbv[p] || v > rb[p]) {
            rb[p] = (int32_t)v;
            rbv[p] = 1;
        }
    }
    for (s = 0; s < 16; s++) {
        const uint8_t *r;
        if (!IS_ON(t->img, s))
            continue;
        r = RIMG(t->img, s);
        if (sp_rp(r) == 100) sp[nsp++] = v_of(r);
        else rp[nrp++] = v_of(r);
    }
    for (i = 0; i < nsp; i++)
        for (j = i + 1; j < nsp; j++)
            if (sp[j] > sp[i]) { int32_t tv = sp[i]; sp[i] = sp[j]; sp[j] = tv; }
    for (i = 0; i < nrp; i++)
        for (j = i + 1; j < nrp; j++)
            if (rp[j] > rp[i]) { int32_t tv = rp[i]; rp[i] = rp[j]; rp[j] = tv; }
    *rsp = (nsp >= 5) ? sp[4] : 0;
    *rrp = (nrp >= 5) ? rp[4] : 0;
}

static int draft_class(const Move *m)
{
    return m->pair[0][R_EXP] == 0 && m->pair[0][R_PYEAR] == 0;
}

static void sign_place(Team *t, Move *m, int dst)
{
    char nm[32];
    const char *src;
    write_pair(t->img, dst, m->pair[0]);
    write_pool_years(t->img, dst, 0);
    m->state = 1;
    if (m->team < 0)
        vacate(g_pool[m->pi], m->pslot);
    pname(m->pair[0], nm);
    src = (m->team < 0) ? "pool" : g_tp[m->team]->stem_lc;
    ev_p("SIGN", t->stem_up, nm, src, NULL);
}

/* step 6 helpers (trade pass) */

static int team_need_a(const Team *t, int q, const int32_t *tmed, int qi)
{
    const Part *p = &t->part;
    int j, n, worst;
    const int16_t *src;
    if (q < 100) {
        for (j = 0; j < p->n_field; j++)
            if (p->fpos[j] == q)
                return tmed[qi] - score(RIMG(t->img, p->fslot[j]));
        return 0;
    }
    n = (q == 100) ? p->n_rot : p->n_relief;
    src = (q == 100) ? p->rot : p->relief;
    if (n == 0)
        return 0;
    worst = score(RIMG(t->img, src[0]));
    for (j = 1; j < n; j++) {
        int v = score(RIMG(t->img, src[j]));
        if (v < worst)
            worst = v;
    }
    return tmed[qi] - worst;
}

static int surplus_of(const Team *t, int q, int32_t med, int *out)
{
    const Part *p = &t->part;
    uint8_t used[40];
    int s, j, n = 0;
    if (med < 0)
        return 0;
    memset(used, 0, sizeof used);
    for (j = 0; j < p->n_field; j++) used[p->fslot[j]] = 1;
    for (j = 0; j < p->n_rot; j++) used[p->rot[j]] = 1;
    for (j = 0; j < p->n_relief; j++) used[p->relief[j]] = 1;
    if (p->dh >= 0) used[p->dh] = 1;
    for (s = 0; s < 40; s++) {
        const uint8_t *r;
        if (used[s] || !IS_ON(t->img, s))
            continue;
        r = RIMG(t->img, s);
        if (q < 100) {
            if (is_pitcher(r) || !can_play(r, q))
                continue;
        } else {
            if (!is_pitcher(r) || sp_rp(r) != q)
                continue;
        }
        if (score(r) >= med)
            out[n++] = s;
    }
    return n;
}

static void top3_of(const Team *t, int pitch, int16_t *out, int *n)
{
    SK a[40];
    int na = 0, s, i;
    int lo = pitch ? 0 : 16;
    int hi = pitch ? 16 : 40;
    for (s = lo; s < hi; s++)
        if (IS_ON(t->img, s)) {
            a[na].k1 = -v_of(RIMG(t->img, s));
            a[na].k2 = s;
            na++;
        }
    sk_sort(a, na);
    *n = (na < 3) ? na : 3;
    for (i = 0; i < *n; i++) out[i] = (int16_t)a[i].k2;
}

static int in3(const int16_t *a, int n, int s)
{
    int i;
    for (i = 0; i < n; i++)
        if (a[i] == s)
            return 1;
    return 0;
}

static int offseason(void)
{
    int rev[MAXT], fwd[MAXT];
    uint32_t mask, start_word;
    int k, s, slot, p, i, j, ri;
    static const int qorder[10] = { 1, 2, 3, 4, 5, 6, 7, 8, 100, 101 };
    int32_t tmed[10];

    g_era = g_hist32[10];
    mask = rd32(g_hist32 + 12);
    for (k = 0; k < g_nt; k++)
        g_tp[k]->managed = (uint8_t)((mask >> g_tp[k]->lg) & 1u);
    start_word = (uint32_t)g_hist32[1] | ((uint32_t)g_hist32[2] << 8);
    if (start_word == 0)
        start_word = 1;
    g_year = -1;
    for (k = 0; k < g_nt; k++) {
        int y = image_year(g_tp[k]->img);
        if (y >= 0) { g_year = y; break; }
    }
    g_fa = (g_era == 2) || (g_era == 0 && g_year >= 1976);
    rev_order(rev, g_nt);
    for (k = 0; k < g_nt; k++) fwd[k] = rev[g_nt - 1 - k];

    /* ---- 1. pool cleanup ---- */
    for (p = 0; p < POOL_FILES; p++)
        for (slot = 0; slot < 40; slot++) {
            uint8_t *img = g_pool[p];
            int32_t base = V20_HDR + V20_REC * slot;
            char nm[32];
            if (img[base] != 0 && img[base + R_PYEAR] >= T_POOL_YEARS) {
                pname(img + base, nm);
                vacate(img, slot);
                ev_p("POOLRET", nm, NULL, NULL, NULL);
            }
        }

    /* ---- 2. draft class ---- */
    for (k = 0; k < g_nt; k++) {
        Team *t = g_tp[k];
        for (slot = 0; slot < 40; slot++) {
            int32_t base = V20_HDR + V20_REC * slot;
            Move *m;
            char nm[32];
            if (t->img[base] == 0)
                continue;
            if (!t->snap_rookie[slot] && t->retflag[slot] != 1)
                continue;
            m = tm_add();
            if (!m) return -1;
            m->team = k;
            m->pi = -1;
            m->pslot = slot;
            memcpy(m->pair[0], t->img + base, V20_REC);
            memcpy(m->pair[1],
                   t->img + V20_HDR + V20_REC * (slot + 40), V20_REC);
            vacate(t->img, slot);
            pname(m->pair[0], nm);
            ev_p("DRAFT", t->stem_up, nm, NULL, NULL);
        }
    }

    /* ---- 3. release (AI teams only) ---- */
    for (k = 0; k < g_nt; k++) {
        Team *t = g_tp[k];
        int pitchers[16], np = 0, batters[24], nb = 0;
        uint8_t prot[40];
        int32_t pv[16], bv[24];
        int32_t med_p = -1, med_b = -1;
        int count = 0, idx, iq, j2;
        static const int POSP[4] = { 1, 5, 3, 7 };
        SK a[24];
        int na;
        if (t->managed)
            continue;
        for (s = 0; s < 16; s++) if (IS_ON(t->img, s)) pitchers[np++] = s;
        for (s = 16; s < 40; s++) if (IS_ON(t->img, s)) batters[nb++] = s;
        memset(prot, 0, sizeof prot);
        for (idx = 0; idx < np; idx++)
            pv[idx] = v_of(RIMG(t->img, pitchers[idx]));
        for (idx = 0; idx < nb; idx++)
            bv[idx] = v_of(RIMG(t->img, batters[idx]));
        na = 0;
        for (idx = 0; idx < np; idx++) {
            a[na].k1 = -pv[idx];
            a[na].k2 = pitchers[idx];
            na++;
        }
        sk_sort(a, na);
        for (j2 = 0; j2 < T_KEEP_P && j2 < na; j2++) prot[a[j2].k2] = 1;
        na = 0;
        for (idx = 0; idx < nb; idx++) {
            a[na].k1 = -bv[idx];
            a[na].k2 = batters[idx];
            na++;
        }
        sk_sort(a, na);
        for (j2 = 0; j2 < T_KEEP_B && j2 < na; j2++) prot[a[j2].k2] = 1;
        for (iq = 0; iq < 4; iq++) {
            int bp = -1;
            int32_t bv2 = 0;
            for (idx = 0; idx < nb; idx++) {
                int sb = batters[idx];
                if (pos1f(RIMG(t->img, sb)) != POSP[iq])
                    continue;
                if (bp < 0 || bv[idx] > bv2) { bp = sb; bv2 = bv[idx]; }
            }
            if (bp >= 0)
                prot[bp] = 1;
        }
        for (idx = 0; idx < np; idx++) {
            const uint8_t *r = RIMG(t->img, pitchers[idx]);
            if (r[R_EXP] <= 1 && r[R_AGE] <= 24)
                prot[pitchers[idx]] = 1;
        }
        for (idx = 0; idx < nb; idx++) {
            const uint8_t *r = RIMG(t->img, batters[idx]);
            if (r[R_EXP] <= 1 && r[R_AGE] <= 24)
                prot[batters[idx]] = 1;
        }
        if (np)
            med_p = lower_median(pv, np);
        if (nb)
            med_b = lower_median(bv, nb);
        for (idx = 0; idx < np + nb; idx++) {
            Move *m;
            const uint8_t *r;
            int age, band, rel;
            int32_t med, vv;
            char nm[32];
            if (count >= T_REL_CAP)
                break;
            if (idx < np)
                s = pitchers[idx];
            else
                s = batters[idx - np];
            if (prot[s])
                continue;
            r = RIMG(t->img, s);
            age = r[R_AGE];
            band = (age <= 24) ? 0 : (age <= 29) ? 1 : (age <= 33) ? 2 : 3;
            rel = T_REL[band][pt_of(t, s)];
            med = (s < 16) ? med_p : med_b;
            vv = v_of(r);
            if (med >= 0 && vv >= med)
                rel >>= 1;
            if ((int)(rng_draw() & 0xffu) >= rel)
                continue;
            m = tm_add();
            if (!m) return -1;
            m->team = k;
            m->pi = -1;
            m->pslot = s;
            memcpy(m->pair[0], r, V20_REC);
            memcpy(m->pair[1],
                   t->img + V20_HDR + V20_REC * (s + 40), V20_REC);
            vacate(t->img, s);
            pname(m->pair[0], nm);
            ev_p("REL", t->stem_up, nm, NULL, NULL);
            count++;
        }
    }

    /* ---- 4. market (AI teams only, only when free agency is on) ---- */
    if (g_fa)
        for (k = 0; k < g_nt; k++) {
            Team *t = g_tp[k];
            for (slot = 0; slot < 40; slot++) {
                int32_t base = V20_HDR + V20_REC * slot;
                Move *m;
                char nm[32];
                if (t->img[base] == 0)
                    continue;
                if (t->snap_rookie[slot] || t->retflag[slot] == 1)
                    continue;
                if (t->img[base + R_EXP] < 6)
                    continue;
                if ((int)(rng_draw() & 0xffu) >= T_MKT)
                    continue;
                m = tm_add();
                if (!m) return -1;
                m->team = k;
                m->pi = -1;
                m->pslot = slot;
                memcpy(m->pair[0], t->img + base, V20_REC);
                memcpy(m->pair[1],
                       t->img + V20_HDR + V20_REC * (slot + 40), V20_REC);
                vacate(t->img, slot);
                pname(m->pair[0], nm);
                ev_p("MKT", t->stem_up, nm, NULL, NULL);
            }
        }

    /* ---- 5. signing ---- */
    /* pool list = pool file players (files sorted, slots ascending), then
     * the moved players in the order they moved */
    for (p = 0; p < POOL_FILES; p++)
        for (slot = 0; slot < 40; slot++) {
            uint8_t *img = g_pool[p];
            int32_t base = V20_HDR + V20_REC * slot;
            Move *m;
            if (img[base] == 0)
                continue;
            m = pm_add();
            if (!m) return -1;
            m->team = -1;
            m->pi = p;
            m->pslot = slot;
            memcpy(m->pair[0], img + base, V20_REC);
            memcpy(m->pair[1], img + V20_HDR + V20_REC * (slot + 40),
                   V20_REC);
        }
    /* rounds repeat until a full round signs nobody */
    for (;;) {
        int acted = 0;
        for (i = 0; i < (int)n_moves(); i++) {
            Move *m = move_at(i);
            if (m->state == 2)
                m->state = 0;
        }
        for (ri = 0; ri < g_nt; ri++) {
            Team *t = g_tp[rev[ri]];
            int vacp = -1, vacb = -1;
            int32_t rb[16];
            uint8_t rbv[16];
            int32_t rsp = 0, rrp = 0;
            Move *best = NULL;
            int32_t bestv = 0;
            int bdst = 0;
            int32_t mi;
            for (s = 0; s < 16; s++)
                if (!IS_ON(t->img, s)) { vacp = s; break; }
            for (s = 16; s < 40; s++)
                if (!IS_ON(t->img, s)) { vacb = s; break; }
            if (vacp < 0 && vacb < 0)
                continue;
            if (!t->managed)
                team_ranks(t, rb, rbv, &rsp, &rrp);
            for (mi = 0; mi < n_moves(); mi++) {
                Move *m = move_at(mi);
                const uint8_t *pr = m->pair[0];
                int pitch = is_pitcher(pr);
                int vacs = pitch ? vacp : vacb;
                int32_t sc;
                if (m->state)
                    continue;
                if (vacs < 0)
                    continue;
                if (t->managed) {
                    /* draft-class players of a vacant slot type; max V */
                    if (!draft_class(m))
                        continue;
                    sc = v_of(pr);
                } else {
                    int32_t best_v, v;
                    if (pitch) {
                        best_v = (sp_rp(pr) == 100) ? rsp : rrp;
                    } else {
                        int pos = pos1f(pr);
                        best_v = rbv[pos] ? rb[pos] : 0;
                    }
                    v = v_of(pr);
                    sc = v + 2 * (v > best_v ? v - best_v : 0);
                }
                if (!best || sc > bestv) {
                    best = m;
                    bestv = sc;
                    bdst = vacs;
                }
            }
            if (best) {
                best->state = 2;
                sign_place(t, best, bdst);
                acted = 1;
            }
        }
        if (!acted)
            break;
    }

    /* ---- 6. trades (AI teams only, no draws) ---- */
    for (k = 0; k < g_nt; k++)
        if (!g_tp[k]->managed)
            build_partition(g_tp[k]->img, &g_tp[k]->part, NULL);
    for (i = 0; i < 10; i++) {
        int32_t vals[280];
        int nv = 0;
        int q = qorder[i];
        for (k = 0; k < g_nt; k++) {
            Team *t = g_tp[k];
            Part *pp;
            int n, j2;
            int16_t *src;
            if (t->managed)
                continue;
            pp = &t->part;
            if (q < 100) {
                for (j2 = 0; j2 < pp->n_field; j2++)
                    if (pp->fpos[j2] == q)
                        vals[nv++] = score(RIMG(t->img, pp->fslot[j2]));
            } else {
                n = (q == 100) ? pp->n_rot : pp->n_relief;
                src = (q == 100) ? pp->rot : pp->relief;
                for (j2 = 0; j2 < n; j2++)
                    vals[nv++] = score(RIMG(t->img, src[j2]));
            }
        }
        tmed[i] = nv ? lower_median(vals, nv) : -1;
    }
    {
        uint8_t traded[MAXT];
        int trade_count = 0, fi;
        memset(traded, 0, sizeof traded);
        for (fi = 0; fi < g_nt; fi++) {
            int kA = fwd[fi];
            Team *tA = g_tp[kA];
            int bi, q, qtypeP, done, kb;
            if (trade_count >= T_MAX_TRADES)
                break;
            if (tA->managed || traded[kA])
                continue;
            bi = -1;
            for (i = 0; i < 10; i++)
                if (tmed[i] >= 0
                    && team_need_a(tA, qorder[i], tmed, i) > T_NEED) {
                    bi = i;
                    break;
                }
            if (bi < 0)
                continue;
            q = qorder[bi];
            qtypeP = (q >= 100);
            done = 0;
            for (kb = 0; kb < g_nt && !done; kb++) {
                Team *tB = g_tp[kb];
                int sXbuf[40], nX = 0, xi;
                if (kb == kA || tB->managed || traded[kb])
                    continue;
                nX = surplus_of(tB, q, tmed[bi], sXbuf);
                for (xi = 0; xi < nX && !done; xi++) {
                    int sX = sXbuf[xi];
                    for (i = 0; i < 10 && !done; i++) {
                        int q2 = qorder[i], nY, yi;
                        int sYbuf[40];
                        if (qtypeP != (q2 >= 100))
                            continue;
                        if (tmed[i] < 0)
                            continue;
                        if (team_need_a(tB, q2, tmed, i) <= T_NEED)
                            continue;
                        nY = surplus_of(tA, q2, tmed[i], sYbuf);
                        for (yi = 0; yi < nY && !done; yi++) {
                            int sY = sYbuf[yi];
                            int16_t x3[3], y3[3];
                            int n3a, n3b;
                            int32_t vx, vy, top, d;
                            uint8_t px[2][V20_REC], py[2][V20_REC];
                            char nA[32], nB[32];
                            top3_of(tB, qtypeP, x3, &n3a);
                            top3_of(tA, qtypeP, y3, &n3b);
                            if (in3(x3, n3a, sX) || in3(y3, n3b, sY))
                                continue;
                            vx = v_of(RIMG(tB->img, sX));
                            vy = v_of(RIMG(tA->img, sY));
                            top = (vx > vy) ? vx : vy;
                            d = (vx > vy) ? vx - vy : vy - vx;
                            if (top != 0 && d * 100 > T_BAND * top)
                                continue;
                            /* swap x and y: the records AND their season
                             * twins move together. RIMG(img, s) points at
                             * the roster half; the season twin lives at
                             * RIMG(img, s + 40). */
                            memcpy(px[0], RIMG(tB->img, sX), V20_REC);
                            memcpy(px[1], RIMG(tB->img, sX + 40), V20_REC);
                            memcpy(py[0], RIMG(tA->img, sY), V20_REC);
                            memcpy(py[1], RIMG(tA->img, sY + 40), V20_REC);
                            vacate(tB->img, sX);
                            vacate(tA->img, sY);
                            write_pair(tA->img, sY, px[0]);
                            write_pair(tB->img, sX, py[0]);
                            pname(px[0], nB);
                            pname(py[0], nA);
                            ev_p("TRADE", tA->stem_up, nB, tB->stem_up, nA);
                            traded[kA] = 1;
                            traded[kb] = 1;
                            trade_count++;
                            done = 1;
                        }
                    }
                }
            }
        }
    }

    /* ---- 7. depth rebuild (AI) or repair (managed) ---- */
    for (k = 0; k < g_nt; k++) {
        Team *t = g_tp[k];
        if (t->managed) {
            uint8_t chg[40];
            changed_slots(t, chg);
            repair(t->img, chg);
        } else {
            int32_t form[40];
            for (slot = 0; slot < 40; slot++) form[slot] = 0;
            for (slot = 0; slot < 40; slot++)
                if (IS_ON(t->img, slot))
                    form[slot] = (int32_t)(rng_draw() & 0xffu)
                               % (2 * T_FORM_A + 1) - T_FORM_A;
            depth_rebuild(t, form);
        }
    }

    /* ---- unsigned pool list: keep / drop ---- */
    {
        int32_t *uidx;
        int nu = 0, ki;
        uidx = (int32_t *)malloc(sizeof(int32_t) * (size_t)(n_moves() + 1));
        if (!uidx)
            return -1;
        for (i = 0; i < (int)n_moves(); i++)
            if (move_at(i)->state != 1)
                uidx[nu++] = i;
        /* sort by V descending, ties earliest list position: insertion sort */
        for (ki = 1; ki < nu; ki++) {
            int32_t cur = uidx[ki];
            for (j = ki - 1; j >= 0; j--) {
                int32_t va = v_of(move_at(uidx[j])->pair[0]);
                int32_t vb = v_of(move_at(cur)->pair[0]);
                if (va < vb || (va == vb && uidx[j] > cur))
                    uidx[j + 1] = uidx[j];
                else
                    break;
            }
            uidx[j + 1] = cur;
        }
        /* every unsigned entity first vacates its source (a pool-file
         * player his file slot, a moved player his team slot, already
         * vacated) */
        for (ki = 0; ki < nu; ki++) {
            Move *m = move_at(uidx[ki]);
            if (m->team < 0)
                vacate(g_pool[m->pi], m->pslot);
        }
        /* the first T.POOL_KEEP (pitchers and batters counted separately)
         * are written to POOL1..POOL4 lowest vacant slots of their type
         * with byte 141 += 1 (both halves); the rest retire unsigned */
        {
            int32_t cntp = 0, cntb = 0;
            for (ki = 0; ki < nu; ki++) {
                Move *m = move_at(uidx[ki]);
                int pitch = is_pitcher(m->pair[0]);
                int32_t cnt = pitch ? cntp : cntb;
                if (cnt < (pitch ? T_POOL_KEEP_P : T_POOL_KEEP_B)) {
                    int pimg = -1, pslot = -1;
                    int lo = pitch ? 0 : 16;
                    int hi = pitch ? 16 : 40;
                    for (p = 0; p < POOL_FILES && pimg < 0; p++)
                        for (s = lo; s < hi; s++)
                            if (!IS_ON(g_pool[p], s)) {
                                pimg = p;
                                pslot = s;
                                break;
                            }
                    if (pimg >= 0) {
                        write_pair(g_pool[pimg], pslot, m->pair[0]);
                        for (i = 0; i < 2; i++) {
                            uint8_t *o = g_pool[pimg] + V20_HDR
                                       + V20_REC * (pslot + 40 * i) + R_PYEAR;
                            *o = (uint8_t)((*o + 1) & 0xff);
                        }
                    }
                    if (pitch)
                        cntp++;
                    else
                        cntb++;
                } else {
                    char nm[32];
                    pname(m->pair[0], nm);
                    ev_p("POOLRET", nm, NULL, NULL, NULL);
                }
            }
        }
        free(uidx);
    }

    /* ---- 8. HISTORY bytes 16..17 = start word, 1..2 = end word ---- */
    g_hist32[16] = (uint8_t)(start_word & 0xffu);
    g_hist32[17] = (uint8_t)((start_word >> 8) & 0xffu);
    g_hist32[1] = (uint8_t)(g_rng & 0xffu);
    g_hist32[2] = (uint8_t)((g_rng >> 8) & 0xffu);
    return 0;
}

/* ---------------- file wrapper. 0 ok, 2 error (files untouched) -------- */

static char *g_tmps[70];
static char *g_fins[70];
static int g_ntmps;

/* heap copy: one malloc per path (BSS must stay under the DOS 64 KB DGROUP) */
static int heap_copy(char **dst, const char *src, const char *tail)
{
    size_t l = strlen(src) + (tail ? strlen(tail) : 0) + 1;
    *dst = (char *)malloc(l);
    if (!*dst)
        return -1;
    strcpy(*dst, src);
    if (tail)
        strcat(*dst, tail);
    return 0;
}

static int reg_tmp(const char *fin)
{
    if (g_ntmps >= 70)
        return -1;
    /* 8.3-safe DOS name: the stem compressed to 8 chars + .TMP (a full-name
     * extension like CLASALE1.V20.TMP has no DOS 8.3 alias for rename) */
    {
        char stm[280];
        size_t l2;
        const char *sep = NULL;
        const char *q;
        for (q = fin; *q; q++)
            if (*q == '/' || *q == '\\')
                sep = q;
        q = sep ? sep + 1 : fin;
        l2 = strcspn(q, ".");
        if (l2 > 8)
            l2 = 8;
        memcpy(stm, q, l2);
        stm[l2] = 0;
        if (heap_copy(&g_tmps[g_ntmps], fin, NULL) != 0)
            return -1;
        g_tmps[g_ntmps][sep ? (size_t)(sep + 1 - fin) : 0] = 0;
        strcat(g_tmps[g_ntmps], stm);
        strcat(g_tmps[g_ntmps], ".TMP");
    }
    if (heap_copy(&g_fins[g_ntmps], fin, NULL) != 0) {
        free(g_tmps[g_ntmps]);
        g_tmps[g_ntmps] = NULL;
        return -1;
    }
    g_ntmps++;
    return 0;
}

static int reg_tmp2(const char *tmp, const char *fin)
{
    if (g_ntmps >= 70)
        return -1;
    if (heap_copy(&g_tmps[g_ntmps], tmp, NULL) != 0)
        return -1;
    if (heap_copy(&g_fins[g_ntmps], fin, NULL) != 0) {
        free(g_tmps[g_ntmps]);
        g_tmps[g_ntmps] = NULL;
        return -1;
    }
    g_ntmps++;
    return 0;
}

static void cleanup_tmps(void)
{
    int i;
    if (g_ev) {
        fclose(g_ev);
        g_ev = NULL;
    }
    for (i = 0; i < g_ntmps; i++) {
        if (g_tmps[i])
            remove(g_tmps[i]);
    }
    g_ntmps = 0;
}

/* every TMP is complete: swap them in with the BAK scheme (as HISTWR). Each
 * existing final is renamed to its BAK (the TMP name with .BAK), then each
 * TMP to its final; any failure puts every original back and removes the
 * TMPs, so exit 2 leaves the league exactly as it was. DOS rename never
 * replaces an existing file, hence the BAK step. */
/* the BAK name of TMP k: the TMP path with .BAK (0 when it does not fit) */
static int bak_name(int k, char *dst, size_t cap)
{
    size_t l = strlen(g_tmps[k]);
    if (l < 4 || l + 1 > cap)
        return 0;
    memcpy(dst, g_tmps[k], l + 1);
    memcpy(dst + l - 4, ".BAK", 4);
    return 1;
}

static int commit_tmps(void)
{
    static uint8_t had[70];
    char bak[644];
    int k, j, fail = 0;
    memset(had, 0, sizeof had);
    for (k = 0; k < g_ntmps && !fail; k++) {
        FILE *probe;
        if (!bak_name(k, bak, sizeof bak)) {
            fail = 1;
            break;
        }
        probe = fopen(g_fins[k], "rb");
        if (probe) {
            fclose(probe);
            remove(bak);
            if (rename(g_fins[k], bak) != 0)
                fail = 1;
            else
                had[k] = 1;
        }
    }
    if (!fail) {
        for (k = 0; k < g_ntmps; k++) {
#ifdef TEST_FAIL_RENAME_AT
            if (k == TEST_FAIL_RENAME_AT) {
                fail = 1;
                break;
            }
#endif
            if (rename(g_tmps[k], g_fins[k]) != 0) {
                fail = 1;
                break;
            }
        }
        if (fail)
            for (j = 0; j < k; j++)
                remove(g_fins[j]);      /* the new files already swapped in */
    }
    for (j = 0; j < g_ntmps; j++) {
        if (!had[j] || !bak_name(j, bak, sizeof bak))
            continue;
        if (fail)
            rename(bak, g_fins[j]);     /* put the original back */
        else
            remove(bak);
    }
    return fail ? 2 : 0;                /* on 2 the caller removes the TMPs */
}

static void free_all(void)
{
    int k, p, i;
    for (k = 0; k < g_nt; k++) {
        if (g_tp[k]) {
            free(g_tp[k]->img);
            free(g_tp[k]);
            g_tp[k] = NULL;
        }
    }
    g_nt = 0;
    for (p = 0; p < POOL_FILES; p++) {
        free(g_pool[p]);
        g_pool[p] = NULL;
    }
    for (i = 0; i < (int)g_npm; i++) free(g_pmv[i]);
    free(g_pmv);
    g_pmv = NULL;
    g_npm = 0;
    g_pcap = 0;
    for (i = 0; i < (int)g_ntm; i++) free(g_tmv[i]);
    free(g_tmv);
    g_tmv = NULL;
    g_ntm = 0;
    g_tcap = 0;
    for (i = 0; i < 2; i++) {
        free(g_star_img[i]);
        g_star_img[i] = NULL;
    }
    for (i = 0; i < 70; i++) {
        free(g_tmps[i]);
        g_tmps[i] = NULL;
        free(g_fins[i]);
        g_fins[i] = NULL;
    }
    g_ntmps = 0;
}

/* one write of a whole buffer to a fresh file, 0 on any failure */
static int write_file(const char *path, const uint8_t *b, size_t n)
{
    FILE *f = fopen(path, "wb");
    if (!f)
        return 0;
    if (fwrite(b, 1, n, f) != n || fclose(f) != 0)
        return 0;
    return 1;
}

static int do_run(void)
{
    int rc = 2, k, p, s;
    uint8_t hist0[HIST_HDR_SIZE];
    int32_t histlen;

    for (s = 0; s < 2; s++) { g_star_img[s] = NULL; g_star_tmp[s] = -1; }

    do {
        /* read the raw HISTORY bytes first (length kept on output) */
        {
            FILE *f = fopen(g_histpath, "rb");
            long sz;
            if (!f)
                break;
            if (fseek(f, 0, SEEK_END) != 0) { fclose(f); break; }
            sz = ftell(f);
            if (sz < 0) { fclose(f); break; }
            if (fseek(f, 0, SEEK_SET) != 0) { fclose(f); break; }
            histlen = (int32_t)sz;
            memset(hist0, 0, HIST_HDR_SIZE);
            if (sz > 0) {
                size_t want = (sz < HIST_HDR_SIZE) ? (size_t)sz
                                                   : HIST_HDR_SIZE;
                if (fread(hist0, 1, want, f) != want) { fclose(f); break; }
            }
            fclose(f);
        }
        memcpy(g_hist32, hist0, HIST_HDR_SIZE);
        if (load_maj(g_lgdir) != 0)
            break;
        if (load_teams(g_lgdir) != 0)
            break;
        if (g_nt == 0)
            break;
        if (load_pools() != 0)
            break;
        {
            int failed = 0;
            for (k = 0; k < g_nt && !failed; k++)
                failed = (load_snap(g_tp[k]) != 0);
            if (failed)
                break;
        }
        parse_retired(g_retpath);
        ret_apply();
        {
            uint16_t seed = (uint16_t)((uint16_t)g_hist32[1]
                         | ((uint16_t)g_hist32[2] << 8));
            g_rng = seed ? seed : (uint16_t)1;
        }
        /* the TMP paths (names are known before the pipeline runs). Order:
         * ROSTERS.TXT first (the event log appends to it as events happen),
         * then the team V20s, the pool V20s, HISTORY.DAT last. */
        {
            char path[640];
            if (!path_join(path, sizeof path, g_lgdir, "ROSTERS.TXT"))
                break;
            if (reg_tmp(path) != 0)
                break;
        }
        g_ev = fopen(g_tmps[0], "wb");
        if (!g_ev)
            break;
        for (k = 0; k < g_nt; k++) {
            char path[640];
            if (!path_join(path, sizeof path, g_lgdir, g_tp[k]->fname))
                break;
            if (reg_tmp(path) != 0)
                break;
        }
        if (k < g_nt)
            break;
        for (p = 0; p < POOL_FILES; p++) {
            char nm[16], path[640];
            sprintf(nm, "POOL%d.V20", p + 1);
            if (!path_join(path, sizeof path, g_lgdir, nm))
                break;
            if (reg_tmp(path) != 0)
                break;
        }
        if (p < POOL_FILES)
            break;
        /* the HISTORY TMP: <hist path without extension>.TMP in the same
         * directory as the history file */
        {
            char dirhh[600], leaf[280], pathhh[640];
            int last = -1, c, dot = -1, l;
            if (!fit_copy(pathhh, sizeof pathhh, g_histpath))
                break;
            for (c = 0; pathhh[c]; c++)
                if (pathhh[c] == '/' || pathhh[c] == '\\') last = c;
            if (last >= 0) {
                memcpy(dirhh, pathhh, (size_t)last + 1);
                dirhh[last + 1] = 0;
                if (!fit_copy(leaf, sizeof leaf, pathhh + last + 1))
                    break;
            } else {
                memcpy(dirhh, ".", 2);
                if (!fit_copy(leaf, sizeof leaf, pathhh))
                    break;
            }
            l = (int)strlen(leaf);
            for (c = 0; c < l; c++)
                if (leaf[c] == '.')
                    dot = c;
            if (dot < 0)
                dot = l;
            if (dot > (int)sizeof leaf - 5 || !path_join(pathhh, sizeof pathhh,
                                                         dirhh, leaf))
                break;
            pathhh[last >= 0 ? last + 1 + dot : dot] = 0;
            strcat(pathhh, ".TMP");
            if (reg_tmp2(pathhh, g_histpath) != 0)
                break;
        }
        /* C9: the star files AFTER the HISTORY TMP (missing, or one whose
         * size is not V20_SIZE, is skipped: never created, never written) */
        k = 0;                         /* 1 = a star TMP failed to register */
        for (s = 0; s < 2 && !k; s++) {
            char path[640];
            int i, n;
            g_star_tmp[s] = -1;
            g_star_img[s] = NULL;
            n = scan_dir(g_lgdir, ".V20", g_scan);
            for (i = 0; i < n; i++) {
                    static const char *NAMES[2] = { "ALLSTAR1.V20",
                                                    "ALLSTAR2.V20" };
                    long sz;
                    FILE *f;
                    if (strcmp(g_scan[i], NAMES[s]) != 0)
                        continue;
                    if (!path_join(path, sizeof path, g_lgdir, g_scan[i]))
                        break;
                    f = fopen(path, "rb");
                    if (!f)
                        break;
                    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); break; }
                    sz = ftell(f);
                    if (sz != V20_SIZE) { fclose(f); break; }
                    if (fseek(f, 0, SEEK_SET) != 0) { fclose(f); break; }
                    g_star_img[s] = (uint8_t *)malloc(V20_SIZE);
                    if (!g_star_img[s]) { fclose(f); break; }
                    if (fread(g_star_img[s], 1, V20_SIZE, f) != V20_SIZE) {
                        free(g_star_img[s]);
                        g_star_img[s] = NULL;
                        fclose(f);
                        break;
                    }
                    fclose(f);
                    if (reg_tmp(path) != 0) {
                        k = 1;
                        break;
                    }
                    g_star_tmp[s] = g_ntmps - 1;
                    break;
                }
        }
        if (k)
            break;
        if (offseason() != 0)
            break;
        /* C9: the refresh runs after the offseason, before the TMP writes */
        for (s = 0; s < 2; s++) {
            static const int32_t LG_BASE[2] = { 0, 16 };
            if (g_star_img[s])
                allstar_refresh(g_star_img[s], LG_BASE[s]);
        }
        /* the TMP writes: team images, pools, HISTORY */
        {
            int wfail = 0;
            for (k = 0; k < g_nt && !wfail; k++)
                wfail = !write_file(g_tmps[1 + k], g_tp[k]->img, V20_SIZE);
            for (p = 0; p < POOL_FILES && !wfail; p++)
                wfail = !write_file(g_tmps[1 + g_nt + p], g_pool[p],
                                    V20_SIZE);
            if (!wfail) {
                int hi = 1 + g_nt + POOL_FILES;
                /* HISTORY header bytes 1..2 and 16..17 only; padded to 32 B
                 * if shorter, otherwise length kept. Only the 32 B header is
                 * buffered (a long dynasty's HISTORY is far past the 64 KB a
                 * DOS object can hold); the rest streams through. */
                static uint8_t out[HIST_HDR_SIZE];
                FILE *src;
                memset(out, 0, sizeof out);
                if (histlen > 0) {
                    size_t want = (histlen < HIST_HDR_SIZE)
                        ? (size_t)histlen : HIST_HDR_SIZE;
                    src = fopen(g_histpath, "rb");
                    if (!src) {
                        wfail = 1;
                    } else {
                        if (fread(out, 1, want, src) != want)
                            wfail = 1;
                        fclose(src);
                    }
                }
                if (!wfail) {
                    out[1] = g_hist32[1];
                    out[2] = g_hist32[2];
                    out[16] = g_hist32[16];
                    out[17] = g_hist32[17];
                    if (!write_file(g_tmps[hi], out, sizeof out))
                        wfail = 1;
                }
                for (s = 0; s < 2 && !wfail; s++)
                    if (g_star_tmp[s] >= 0 && g_star_img[s])
                        wfail = !write_file(g_tmps[g_star_tmp[s]],
                                            g_star_img[s], V20_SIZE);
                if (!wfail && histlen > HIST_HDR_SIZE) {
                    /* append the rest of the original history through */
                    FILE *g = fopen(g_tmps[hi], "ab");
                    static uint8_t chunk[8192];
                    long rem;
                    if (!g) {
                        wfail = 1;
                    } else {
                        src = fopen(g_histpath, "rb");
                        if (!src) {
                            wfail = 1;
                        } else if (fseek(src, HIST_HDR_SIZE,
                                         SEEK_SET) != 0) {
                            fclose(src);
                            wfail = 1;
                        } else {
                            rem = histlen - HIST_HDR_SIZE;
                            while (rem > 0 && !wfail) {
                                size_t want = (rem > 8192) ? 8192
                                                           : (size_t)rem;
                                size_t got = fread(chunk, 1, want, src);
                                if (got == 0
                                    || fwrite(chunk, 1, got, g) != got)
                                    wfail = 1;
                                rem -= (long)got;
                            }
                            fclose(src);
                        }
                        if (fclose(g) != 0)
                            wfail = 1;
                    }
                }
            }
            if (wfail)
                break;
        }
        /* every TMP write succeeded: close the log, then on DOS remove the
         * original and rename */
        if (g_ev) {
            if (fclose(g_ev) != 0)
                break;
            g_ev = NULL;
        }
        rc = commit_tmps();
    } while (0);
    if (rc != 0)
        cleanup_tmps();
    else if (g_ev) {
        fclose(g_ev);
        g_ev = NULL;
    }
    free_all();
    return rc;
}

int main(int argc, char **argv)
{
    if (argc >= 5) {
        if (!fit_copy(g_lgdir, sizeof g_lgdir, argv[1])
            || !fit_copy(g_snapdir, sizeof g_snapdir, argv[2])
            || !fit_copy(g_histpath, sizeof g_histpath, argv[3])
            || !fit_copy(g_retpath, sizeof g_retpath, argv[4]))
            return 2;
    } else {
        if (!fit_copy(g_lgdir, sizeof g_lgdir, DEF_LEAGUE)
            || !fit_copy(g_snapdir, sizeof g_snapdir, DEF_SNAP)
            || !fit_copy(g_histpath, sizeof g_histpath, DEF_HIST)
            || !fit_copy(g_retpath, sizeof g_retpath, DEF_RET))
            return 2;
    }
    return do_run();
}
