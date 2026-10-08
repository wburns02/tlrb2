/* DYNVIEW: C port of tools/m4/dynview.py (T5a reference renderer). Host build
 * with gcc for parity tests, DOS build with OpenWatcom (16-bit real mode).
 * Streams HISTORY.DAT (one 160 B player entry at a time) and keeps sorted
 * top-LIST_MAX list buffers; screen output matches the Python reference pixel
 * for pixel.
 * usage: DYNVIEW [/REVIEW] [/KEYS:k,k,...] [/RAW:FILE] [LEAGUE_DIR [FONT_DIR]]
 * exit 0 ok, 2 on bad usage, font failure or /RAW write failure.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#ifdef __WATCOMC__
#include <dos.h>
#include <i86.h>
#include <conio.h>
#define DIR_SEP '\\'
#else
#define DIR_SEP '/'
#endif

#define FB_W   320
#define FB_H   200
#define FB_SIZE 64000

#define C_BLACK  0
#define C_WHITE  15
#define C_TITLE_RED 208
#define C_HEADER_GOLD 207
#define C_ROW_TAN 188
#define C_FRAME_TAN 193
#define C_BG_BROWN 215
#define C_GRID_GRAY 7

#define ROW_H 11
#define ROWS_PER_PAGE 12
#define LIST_MAX 1200

/* BIOS int 16h codes; ASCII keys are their char code */
#define KEY_ESC 27
#define KEY_ENTER 13
#define KEY_LEFT 0x4b00
#define KEY_RIGHT 0x4d00
#define KEY_PGUP 0x4900
#define KEY_PGDN 0x5100
#define KEY_UP 0x4800
#define KEY_DOWN 0x5000

#define SCREEN_MENU 0
#define SCREEN_HISTORY 1
#define SCREEN_HOF 2
#define SCREEN_LEADERS 3
#define SCREEN_MILESTONES 4
#define SCREEN_REVIEW 5
#define N_CATS 12

#define HDR_SIZE 32
#define SEASON_TABLE 32
#define SEASON_ENTRY 128
#define SEASON_COUNT 64
#define PLAYER_TABLE (SEASON_TABLE + 64 * SEASON_ENTRY)
#define PLAYER_ENTRY 160
#define NUM_TOT 25

#define STATUS_ACTIVE 1
#define STATUS_RETIRED 2
#define STATUS_HOF 3
#define NO_AWARD 0xffff

#define CHAR_W 7
#define SLEN 64             /* cell / line text cap */
#define NAME_CAP_MAX 96
#define MAX_ROWS 12

#ifdef __WATCOMC__
#define FARDATA __far
#else
#define FARDATA
#endif

#define DEF_LEAGUE "TEAMS\\CLASSIC"
#define DEF_LEAGUE_HOST "TEAMS/CLASSIC"

/* font glyph: assets.parse_fnt layout (MSB first, rows * ceil(bits/8) bytes) */
typedef struct {
    uint8_t rows, bits, adv, bpr;
    uint16_t off;               /* offset into font->bytes */
} Glyph;

/* one font file: 95 glyphs of char 32..126 (parse_fnt requires count 95) */
typedef struct {
    Glyph g[95];
    uint16_t count;             /* u16 count from the file header */
    uint8_t *bytes;
} Font;

/* one player entry streamed from HISTORY.DAT;
 * totals are the 25 u32 career totals, WAR10 is s16 */
typedef struct {
    uint8_t name[20];
    uint8_t status;
    uint8_t pitcher;
    uint16_t seasons_played;
    uint32_t tot[NUM_TOT];
    int16_t war10;
    uint16_t hof_season;
    uint8_t awards[5];
} Entry;

/* one season-table entry (fields the renderer needs) */
typedef struct {
    uint16_t season_no;
    uint8_t champion_stem[8];
    uint8_t runner_up_stem[8];
    uint16_t awards[6];
} SeasonEntry;

/* one MILESTON.DAT record: u16 season, u16 idx, u8 kind, u8 zero, u16 value */
typedef struct {
    uint16_t season, idx, value;
    uint8_t kind;
} MsRec;

typedef struct {
    int16_t screen, page, cat;
} State;

/* sorted top-K list: (key, index) pairs keyed for the exact Python total
 * order, capped at LIST_MAX; equal keys keep insertion (file) order */
typedef struct {
    int32_t n;
    uint32_t key[LIST_MAX];     /* unsigned-mapped sort key */
    uint32_t idx[LIST_MAX];     /* entry index / season position / file pos */
} List;

/* model row: up to 7 cells */
typedef struct {
    char cells[7][SLEN];
    int ncells;
} Row;

static Font *g_main, *g_bold;
static uint8_t FARDATA g_fb[FB_SIZE];
static uint8_t FARDATA g_pal[768];
static uint8_t g_hdr[HDR_SIZE];
static FILE *g_hist;            /* HISTORY.DAT, read with fseek per entry */
static uint16_t g_hdr_seasons;
static uint32_t g_file_entries; /* full 160 B entries in the file */
static uint16_t g_entry_count;  /* the count the row builders iterate */
static MsRec *g_ms;
static int32_t g_nms;

/* the top-K buffers and the row cells are far too (DOS DGROUP cap) */
static List FARDATA g_list_buf[4];
#define g_histl  (g_list_buf[0])
#define g_hofl   (g_list_buf[1])
#define g_leadl  (g_list_buf[2])
#define g_msl    (g_list_buf[3])

static Row FARDATA g_rows[MAX_ROWS];
static int g_nrows;

static State g_state;
static int g_exit;

static const char *CAT_LABEL[N_CATS] = {
    "H", "HR", "RBI", "SB", "AVG", "WAR", "W", "SV", "PSO", "ERA",
    "MVP AWARDS", "GG AWARDS" };
/* kind 0 count, 1 avg, 2 era, 3 war, 4 aw0, 5 aw3 */
static const uint8_t CAT_KIND[N_CATS] = { 0, 0, 0, 0, 1, 3, 0, 0, 0, 2, 4, 5 };
static const uint8_t CAT_IDX[N_CATS] = { 2, 5, 7, 10, 0, 0, 13, 15, 23, 0, 0, 0 };

int main(int argc, char **argv);
static void render(State st);
static void build_no_hist_rows(void);
/* ---- helpers ---- */

/* signed division truncating toward zero == C99 / (x86 idiv) */
static int32_t idiv_(int64_t a, int64_t b)
{
    return (int32_t)(a / b);
}

/* unsigned map of a signed sort key: the exact Python total order */
static uint32_t keybox(int32_t v)
{
    return (uint32_t)v ^ 0x80000000u;
}

/* ordered top-K insert, descending key (ties keep insertion/file order):
 * the list stays ascending by keybox, so a descending key lands first by
 * negating it once (largest value -> smallest keybox -> idx[0]) */
static void list_add_desc(List *b, int32_t key, uint32_t idx)
{
    uint32_t k = keybox(-key);
    int32_t lo = 0, hi, mid;
    if (b->n >= LIST_MAX && k >= b->key[b->n - 1])
        return;
    hi = b->n;
    while (lo < hi) {
        mid = (lo + hi) / 2;
        if (b->key[mid] <= k)
            lo = mid + 1;
        else
            hi = mid;
    }
    if (lo >= LIST_MAX)
        return;
    if (b->n < LIST_MAX)
        b->n++;
    if (b->n - 1 > lo) {
        memmove(&b->key[lo + 1], &b->key[lo],
                (size_t)(b->n - 1 - lo) * sizeof(b->key[0]));
        memmove(&b->idx[lo + 1], &b->idx[lo],
                (size_t)(b->n - 1 - lo) * sizeof(b->idx[0]));
    }
    b->key[lo] = k;
    b->idx[lo] = idx;
}

/* ordered top-K insert, ascending key */
static void list_add_asc(List *b, int32_t key, uint32_t idx)
{
    uint32_t k = keybox(key);
    int32_t lo = 0, hi, mid;
    if (b->n >= LIST_MAX && k <= b->key[b->n - 1])
        return;
    hi = b->n;
    while (lo < hi) {
        mid = (lo + hi) / 2;
        if (b->key[mid] <= k)
            lo = mid + 1;
        else
            hi = mid;
    }
    if (lo >= LIST_MAX)
        return;
    if (b->n < LIST_MAX)
        b->n++;
    if (b->n - 1 > lo) {
        memmove(&b->key[lo + 1], &b->key[lo],
                (size_t)(b->n - 1 - lo) * sizeof(b->key[0]));
        memmove(&b->idx[lo + 1], &b->idx[lo],
                (size_t)(b->n - 1 - lo) * sizeof(b->idx[0]));
    }
    b->key[lo] = k;
    b->idx[lo] = idx;
}

static void path_join(char *dst, const char *a, const char *b)
{
    size_t l = strlen(a);
    strcpy(dst, a);
    if (l > 0 && dst[l - 1] != '/' && dst[l - 1] != '\\')
        strcat(dst, DIR_SEP == '/' ? "/" : "\\");
    strcat(dst, b);
}

/* ---------------- text ---------------- */

/* glyph_of(font, ch): any byte outside 32..126 draws glyph 31 ('?') */
static const Glyph *glyph_of(const Font *ft, uint8_t ch)
{
    int k = (int)ch - 32;
    if (k < 0 || k > 94)
        k = '?' - 32;
    return &ft->g[k];
}

/* draw_text upper-cases a-z only; any byte outside 32..126 after upper()
 * draws glyph 31 ('?') */
static void draw_text(uint8_t *fb, const Font *ft, int x, int y,
                      const uint8_t *s, int color)
{
    int i;
    for (i = 0; s[i]; i++) {
        uint8_t ch = s[i];
        const Glyph *g;
        int r, c;
        if (ch >= 'a' && ch <= 'z')
            ch = (uint8_t)(ch - 32);
        g = glyph_of(ft, ch);
        for (r = 0; r < g->rows; r++) {
            int py = y + r;
            const uint8_t *row = ft->bytes + g->off + r * g->bpr;
            int base;
            if (py < 0 || py >= FB_H)
                continue;
            base = py * FB_W;
            for (c = 0; c < g->bits; c++) {
                if (row[c / 8] & (0x80u >> (c % 8))) {
                    int px = x + c;
                    if (0 <= px && px < FB_W)
                        fb[base + px] = (uint8_t)color;
                }
            }
        }
        x += g->adv;
    }
}

static int text_width(const Font *ft, const uint8_t *s)
{
    int w = 0, i;
    for (i = 0; s[i]; i++) {
        uint8_t ch = s[i];
        if (ch >= 'a' && ch <= 'z')
            ch = (uint8_t)(ch - 32);
        w += glyph_of(ft, ch)->adv;
    }
    return w;
}

static void fill_fb(int color)
{
    memset(g_fb, color, (size_t)FB_SIZE);
}

/* clamped rect (Python's rect clips to the framebuffer) */
static void rect_fb(int x0, int y0, int x1, int y1, int color)
{
    int y, x;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > FB_W - 1) x1 = FB_W - 1;
    if (y1 > FB_H - 1) y1 = FB_H - 1;
    for (y = y0; y <= y1; y++) {
        uint8_t *row = g_fb + y * FB_W;
        for (x = x0; x <= x1; x++)
            row[x] = (uint8_t)color;
    }
}

/* ---------------- strings / formatting ---------------- */

/* NUL-or-space terminated field, trailing spaces stripped */
static void field_of(const uint8_t *b, int n, char *dst)
{
    int i, end = 0;
    for (i = 0; i < n && b[i]; i++) {
        dst[i] = (char)b[i];
        if (b[i] != ' ')
            end = i + 1;
    }
    dst[end] = 0;
}

/* name_display: V20 name bytes 0..19 (last 12, first 8), 'LAST, F' style,
 * cut to cap chars; empty first part or no room for one first-name char: just
 * the last name (never a dangling comma) */
static void name_display(const uint8_t *name20, int cap, char *dst)
{
    char last[13], first[9];
    int ll, fl;
    field_of(name20, 12, last);
    field_of(name20 + 12, 8, first);
    ll = (int)strlen(last);
    fl = (int)strlen(first);
    if (ll > cap)
        ll = cap;
    if (fl > 0 && ll + 3 <= cap) {
        int i, j = 0;
        for (i = 0; i < ll; i++)
            dst[j++] = last[i];
        dst[j++] = ',';
        dst[j++] = ' ';
        for (i = 0; i < fl && j < cap; i++)
            dst[j++] = first[i];
        dst[j] = 0;
    } else {
        memcpy(dst, last, (size_t)ll);
        dst[ll] = 0;
    }
}

static char g_lgdir[260];       /* LEAGUE_DIR, for the team V20 names */

/* team_name: V20 header name (bytes 0..13, NUL ended, trailing spaces cut)
 * of LEAGUE_DIR\<STEM>.V20; "" when the file is missing or the name blank */
static void team_name(const char *stem, char *dst)
{
    char path[300], leaf[16];
    uint8_t raw[14];
    size_t i, n;
    FILE *f;
    dst[0] = 0;
    n = strlen(stem);
    if (n == 0 || n > 8 || strlen(g_lgdir) + 2 + n + 4 >= sizeof path)
        return;
    for (i = 0; i < n; i++)
        leaf[i] = (char)(stem[i] >= 'a' && stem[i] <= 'z' ? stem[i] - 32 : stem[i]);
    strcpy(leaf + n, ".V20");
    path_join(path, g_lgdir, leaf);
    f = fopen(path, "rb");
    if (!f)
        return;
    memset(raw, 0, sizeof raw);
    (void)fread(raw, 1, sizeof raw, f);
    fclose(f);
    field_of(raw, 14, dst);
}

static void stem_display(const uint8_t *stem8, char *dst)
{
    int i;
    char stem[9];
    for (i = 0; i < 8; i++)
        if (stem8[i])
            break;
    if (i == 8) {
        dst[0] = '?';
        dst[1] = 0;
        return;
    }
    field_of(stem8, 8, stem);
    team_name(stem, dst);
    if (dst[0])
        return;
    strcpy(dst, stem);
    for (i = 0; dst[i]; i++)
        if (dst[i] >= 'a' && dst[i] <= 'z')
            dst[i] = (char)(dst[i] - 32);
}

static void fmt_count(int32_t v, char *dst)
{
    sprintf(dst, "%lu", (unsigned long)(uint32_t)v);
}

static void fmt_avg(int32_t v, char *dst)
{
    if (v <= 0)
        strcpy(dst, ".000");
    else if (v >= 1000)
        strcpy(dst, "1.000");
    else
        sprintf(dst, ".%03lu", (unsigned long)(uint32_t)v);
}

static void fmt_era100(int32_t v, char *dst)
{
    int neg = v < 0;
    uint32_t a = neg ? (uint32_t)(-(int64_t)v) : (uint32_t)v;
    sprintf(dst, "%s%lu.%02lu", neg ? "-" : "",
            (unsigned long)(a / 100u), (unsigned long)(a % 100u));
}

static void fmt_war10(int32_t v, char *dst)
{
    int neg = v < 0;
    uint32_t a = neg ? (uint32_t)(-(int64_t)v) : (uint32_t)v;
    sprintf(dst, "%s%lu.%lu", neg ? "-" : "",
            (unsigned long)(a / 10u), (unsigned long)(a % 10u));
}

/* u32 career totals: Python // on a nonnegative quotient (the dividend fits
 * int32 for these ratios) */
static uint32_t avg_of(const uint32_t *t)
{
    if (t[1] == 0)
        return 0;
    return (uint32_t)idiv_((int64_t)t[2] * 1000, (int64_t)t[1]);
}

static uint32_t era100_of(const uint32_t *t)
{
    if (t[19] == 0)
        return 0;
    return (uint32_t)idiv_((int64_t)t[20] * 2700, (int64_t)t[19]);
}

/* CAREER_EVENTS, then season kinds 32..39, then '?' */
static void event_text(int32_t kind, int32_t value, char *dst)
{
    static const char *ev[18] = {
        NULL, "2000 HITS", "3000 HITS", "300 HOME RUNS", "400 HOME RUNS",
        "500 HOME RUNS", "600 HOME RUNS", "700 HOME RUNS", "1500 RBI",
        "2000 RBI", "500 STOLEN BASES", "200 WINS", "300 WINS",
        "2000 STRIKEOUTS", "3000 STRIKEOUTS", "4000 STRIKEOUTS",
        "300 SAVES", "400 SAVES" };
    if (kind >= 1 && kind <= 17) {
        strcpy(dst, ev[kind]);
        return;
    }
    if (kind == 32) {
        fmt_count(value, dst);
        strcat(dst, " HR SEASON");
    } else if (kind == 33) {
        fmt_count(value, dst);
        strcat(dst, " HIT SEASON");
    } else if (kind == 34) {
        fmt_count(value, dst);
        strcat(dst, " SB SEASON");
    } else if (kind == 35) {
        fmt_avg(value, dst);
        strcat(dst, " SEASON");
    } else if (kind == 36) {
        fmt_count(value, dst);
        strcat(dst, " WIN SEASON");
    } else if (kind == 37) {
        fmt_count(value, dst);
        strcat(dst, " STRIKEOUT SEASON");
    } else if (kind == 38) {
        fmt_era100(value, dst);
        strcat(dst, " ERA SEASON");
    } else if (kind == 39) {
        fmt_count(value, dst);
        strcat(dst, " SAVE SEASON");
    } else {
        strcpy(dst, "?");
    }
}

/* ---------------- data loading ---------------- */

/* History.__init__ edge rules: missing or empty file = seasons 0; shorter
 * than 32 B = zero padded; file entries = (size - 8224) / 160 when
 * size > 8224 else 0; bytes past EOF read as zero */
static int load_hist(const char *league_dir)
{
    char path[600];
    FILE *f;
    long fsz;
    uint32_t hdr_n;
    uint16_t want;
    size_t got;
    path_join(path, league_dir, "HISTORY.DAT");
    f = fopen(path, "rb");
    g_hdr_seasons = 0;
    g_file_entries = 0;
    g_entry_count = 0;
    g_hist = NULL;
    if (!f)
        return 1;
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return 1;
    }
    fsz = ftell(f);
    if (fsz < 0)
        fsz = 0;
    if (fsz == 0) {
        fclose(f);                  /* empty file = seasons 0 */
        return 1;
    }
    if (fseek(f, 0, SEEK_SET) != 0) {
        fclose(f);
        return 1;
    }
    memset(g_hdr, 0, HDR_SIZE);
    /* shorter than 32 B: the rest reads as zero padding */
    got = fread(g_hdr, 1, HDR_SIZE, f);
    if (got == 0 && fsz > 0) {
        fclose(f);
        return 1;
    }
    g_hdr_seasons = (uint16_t)(g_hdr[4] | ((uint16_t)g_hdr[5] << 8));
    g_file_entries = (fsz > PLAYER_TABLE)
                   ? (uint32_t)(fsz - PLAYER_TABLE) / PLAYER_ENTRY : 0;
    hdr_n = (uint32_t)(g_hdr[6] | ((uint32_t)g_hdr[7] << 8));
    /* n_entries: header count when 0 < cnt <= len(entries), else len(entries) */
    want = (uint16_t)g_file_entries;
    if (hdr_n > 0 && hdr_n <= g_file_entries)
        want = (uint16_t)hdr_n;
    g_entry_count = want;
    g_hist = f;                     /* stays open for fseek reads */
    return 1;
}

/* one player entry with fseek; bytes past EOF read as zero */
static int read_entry(Entry *e, uint32_t idx)
{
    static uint8_t eb[PLAYER_ENTRY];
    long off;
    int k;
    if (!g_hist)
        return 0;
    off = (long)PLAYER_TABLE + (long)idx * PLAYER_ENTRY;
    if (fseek(g_hist, off, SEEK_SET) != 0)
        return 0;
    memset(eb, 0, sizeof eb);
    if (fread(eb, 1, PLAYER_ENTRY, g_hist) != PLAYER_ENTRY) {
        /* short read past EOF keeps the zero padding */
    }
    memcpy(e->name, eb, 20);
    e->status = eb[22];
    e->pitcher = eb[31];
    e->seasons_played = (uint16_t)(eb[28] | ((uint16_t)eb[29] << 8));
    for (k = 0; k < NUM_TOT; k++)
        e->tot[k] = (uint32_t)eb[32 + 4 * k]
                  | ((uint32_t)eb[33 + 4 * k] << 8)
                  | ((uint32_t)eb[34 + 4 * k] << 16)
                  | ((uint32_t)eb[35 + 4 * k] << 24);
    e->war10 = (int16_t)((uint16_t)eb[132] | ((uint16_t)eb[133] << 8));
    e->hof_season = (uint16_t)((uint16_t)eb[150] | ((uint16_t)eb[151] << 8));
    for (k = 0; k < 5; k++)
        e->awards[k] = eb[152 + k];
    return 1;
}

static uint32_t n_entries(void)
{
    return g_entry_count;
}

static int read_season(SeasonEntry *se, int season_no)
{
    static uint8_t sb[SEASON_ENTRY];
    long off;
    int k;
    if (!g_hist || season_no < 1 || season_no > SEASON_COUNT)
        return 0;
    off = (long)SEASON_TABLE + (long)(season_no - 1) * SEASON_ENTRY;
    if (fseek(g_hist, off, SEEK_SET) != 0)
        return 0;
    memset(sb, 0, sizeof sb);
    if (fread(sb, 1, SEASON_ENTRY, g_hist) != SEASON_ENTRY) {
        /* short read keeps zero padding */
    }
    se->season_no = (uint16_t)((uint16_t)sb[0] | ((uint16_t)sb[1] << 8));
    memcpy(se->champion_stem, sb + 4, 8);
    memcpy(se->runner_up_stem, sb + 12, 8);
    for (k = 0; k < 6; k++)
        se->awards[k] = (uint16_t)((uint16_t)sb[88 + 2 * k]
                                 | ((uint16_t)sb[89 + 2 * k] << 8));
    return 1;
}

/* stream MILESTON.DAT (8 B records; a short tail is dropped like Python) */
#define MS_MAX 7000L

static int load_ms(const char *league_dir)
{
    char path[600];
    FILE *f;
    int32_t cap = 256;
    g_nms = 0;
    if (g_ms) {
        free(g_ms);
        g_ms = NULL;
    }
    g_ms = (MsRec *)malloc((size_t)cap * sizeof(MsRec));
    if (!g_ms)
        return 0;
    path_join(path, league_dir, "MILESTON.DAT");
    f = fopen(path, "rb");
    if (!f)
        return 1;
    for (;;) {
        uint8_t rec[8];
        size_t r = fread(rec, 1, 8, f);
        if (r < 8)
            break;
        if (g_nms >= cap) {
            MsRec *nm;
            /* 16-bit size_t: stop below one 64 KB block (MS_MAX records,
             * hundreds of seasons); the rest of the file is not shown */
            if (cap >= MS_MAX)
                break;
            cap = cap * 2 > MS_MAX ? MS_MAX : cap * 2;
            nm = (MsRec *)realloc(g_ms, (size_t)cap * sizeof(MsRec));
            if (!nm) {
                fclose(f);
                return 0;
            }
            g_ms = nm;
        }
        g_ms[g_nms].season = (uint16_t)((uint16_t)rec[0] | ((uint16_t)rec[1] << 8));
        g_ms[g_nms].idx = (uint16_t)((uint16_t)rec[2] | ((uint16_t)rec[3] << 8));
        g_ms[g_nms].kind = rec[4];
        g_ms[g_nms].value = (uint16_t)((uint16_t)rec[6] | ((uint16_t)rec[7] << 8));
        g_nms++;
    }
    fclose(f);
    return 1;
}

/* entry_name: NONE for NO_AWARD; '?' for out of range / an empty display name */
static void entry_name(uint16_t idx, int cap, char *dst)
{
    Entry e;
    char nm[NAME_CAP_MAX];
    if (idx == NO_AWARD) {
        strcpy(dst, "NONE");
        return;
    }
    if (idx >= n_entries()) {
        dst[0] = '?';
        dst[1] = 0;
        return;
    }
    if (!read_entry(&e, idx)) {
        dst[0] = '?';
        dst[1] = 0;
        return;
    }
    name_display(e.name, cap, nm);
    if (nm[0])
        memcpy(dst, nm, strlen(nm) + 1);
    else {
        dst[0] = '?';
        dst[1] = 0;
    }
}

/* ---------------- categories ---------------- */

static uint32_t cat_value(const Entry *e, int cat)
{
    switch (CAT_KIND[cat]) {
    case 0: return e->tot[CAT_IDX[cat]];
    case 1: return avg_of(e->tot);
    case 2: return era100_of(e->tot);
    case 3: return (uint32_t)(int32_t)e->war10;
    case 4: return e->awards[0];
    default: return e->awards[3];
    }
}

static int cat_qualifies(const Entry *e, int cat)
{
    switch (CAT_KIND[cat]) {
    case 0: return e->tot[CAT_IDX[cat]] > 0;
    case 1: return e->tot[1] >= 3000;
    case 2: return e->tot[19] >= 4500;
    case 4:
    case 5: return cat_value(e, cat) > 0;
    default: return 1;
    }
}

static void cat_format(int cat, uint32_t v, char *dst)
{
    switch (CAT_KIND[cat]) {
    case 1: fmt_avg((int32_t)v, dst); return;
    case 2: fmt_era100((int32_t)v, dst); return;
    case 3: fmt_war10((int32_t)v, dst); return;
    default: fmt_count((int32_t)v, dst); return;
    }
}

/* ---------------- top-K list scans ---------------- */

/* HoF: status 3 by (hof_season desc, index asc) */
static void hof_scan(List *b)
{
    uint32_t i;
    Entry e;
    b->n = 0;
    for (i = 0; i < n_entries(); i++) {
        read_entry(&e, i);
        if (e.status == STATUS_HOF)
            list_add_desc(b, (int32_t)e.hof_season, i);
    }
}

/* leaders: value desc (ERA asc), index asc */
static void leaders_scan(List *b, int cat)
{
    uint32_t i;
    Entry e;
    b->n = 0;
    for (i = 0; i < n_entries(); i++) {
        read_entry(&e, i);
        if (cat_qualifies(&e, cat)) {
            if (CAT_KIND[cat] == 2)
                list_add_asc(b, (int32_t)cat_value(&e, cat), i);
            else
                list_add_desc(b, (int32_t)cat_value(&e, cat), i);
        }
    }
}

/* milestones: season desc, file position asc */
static void ms_scan(List *b)
{
    int32_t i;
    b->n = 0;
    for (i = 0; i < g_nms; i++)
        list_add_desc(b, (int32_t)g_ms[i].season, (uint32_t)i);
}

/* history: one row per season, newest first (at most 64 seasons) */
static void hist_scan(List *b)
{
    int pos;
    uint16_t n;
    SeasonEntry se;
    b->n = 0;
    n = g_hdr_seasons < SEASON_COUNT ? g_hdr_seasons : SEASON_COUNT;
    for (pos = 1; pos <= (int)n; pos++) {
        if (!read_season(&se, pos))
            break;
        list_add_desc(b, (int32_t)se.season_no, (uint32_t)pos);
    }
}

/* qualifying candidates (paging bound), not the on-screen 12 */
static int leaders_count(int cat)
{
    List b;
    leaders_scan(&b, cat);
    return (int)b.n;
}

/* ---------------- row builders ---------------- */

/* history rows: YEAR, CHAMPION, RUNNER-UP, AL MVP, NL MVP */
static int build_hist_rows(int page)
{
    SeasonEntry se;
    char nm[NAME_CAP_MAX];
    int n = 0, k, r0 = page * ROWS_PER_PAGE, r;
    for (r = r0; r < g_histl.n && r < (page + 1) * ROWS_PER_PAGE; r++, n++) {
        read_season(&se, (int)g_histl.idx[r]);
        sprintf(g_rows[n].cells[0], "%u", (unsigned)se.season_no);
        stem_display(se.champion_stem, g_rows[n].cells[1]);
        entry_name(se.awards[0], 11, nm);
        strcpy(g_rows[n].cells[2], nm);
        entry_name(se.awards[3], 11, nm);
        strcpy(g_rows[n].cells[3], nm);
        g_rows[n].ncells = 4;
    }
    for (k = n; k < MAX_ROWS; k++)
        g_rows[k].ncells = 0;
    return n;
}

/* HOF row: NAME, IND, YRS, H/W, HR/SO(PSO), AVG/ERA, WAR */
static int build_hof_rows(int page)
{
    int n = 0, k, r0 = page * ROWS_PER_PAGE, r;
    for (r = r0; r < g_hofl.n && r < (page + 1) * ROWS_PER_PAGE; r++, n++) {
        Entry e;
        char nm[NAME_CAP_MAX];
        read_entry(&e, g_hofl.idx[r]);
        g_rows[n].ncells = 7;
        name_display(e.name, 12, nm);
        strcpy(g_rows[n].cells[0], nm[0] ? nm : "?");
        sprintf(g_rows[n].cells[1], "%u", (unsigned)e.hof_season);
        sprintf(g_rows[n].cells[2], "%u", (unsigned)e.seasons_played);
        if (e.pitcher) {
            fmt_count((int32_t)e.tot[13], g_rows[n].cells[3]);
            fmt_count((int32_t)e.tot[23], g_rows[n].cells[4]);
            fmt_era100((int32_t)era100_of(e.tot), g_rows[n].cells[5]);
        } else {
            fmt_count((int32_t)e.tot[2], g_rows[n].cells[3]);
            fmt_count((int32_t)e.tot[5], g_rows[n].cells[4]);
            fmt_avg((int32_t)avg_of(e.tot), g_rows[n].cells[5]);
        }
        fmt_war10(e.war10, g_rows[n].cells[6]);
    }
    for (k = n; k < MAX_ROWS; k++)
        g_rows[k].ncells = 0;
    return n;
}

/* leaders row: rank (restarted per page), NAME, status mark, YRS, value */
static int build_lead_rows(int cat, int page)
{
    int n = 0, k, r0 = page * ROWS_PER_PAGE, r;
    for (r = r0; r < g_leadl.n && r < (page + 1) * ROWS_PER_PAGE; r++, n++) {
        Entry e;
        char nm[NAME_CAP_MAX], val[24];
        read_entry(&e, g_leadl.idx[r]);
        g_rows[n].ncells = 5;
        sprintf(g_rows[n].cells[0], "#%u", (unsigned)r + 1u);
        name_display(e.name, 16, nm);
        strcpy(g_rows[n].cells[1], nm[0] ? nm : "?");
        g_rows[n].cells[2][0] = e.status == STATUS_RETIRED ? 'R'
                              : (e.status == STATUS_HOF ? 'H' : ' ');
        g_rows[n].cells[2][1] = 0;
        sprintf(g_rows[n].cells[3], "%u", (unsigned)e.seasons_played);
        cat_format(cat, cat_value(&e, cat), val);
        strcpy(g_rows[n].cells[4], val);
    }
    for (k = n; k < MAX_ROWS; k++)
        g_rows[k].ncells = 0;
    return n;
}

/* milestone row: YEAR, NAME, EVENT */
static int build_ms_rows(int page)
{
    int n = 0, k, r0 = page * ROWS_PER_PAGE, r;
    for (r = r0; r < g_msl.n && r < (page + 1) * ROWS_PER_PAGE; r++, n++) {
        MsRec *rec = &g_ms[g_msl.idx[r]];
        char nm[NAME_CAP_MAX], ev[64];
        g_rows[n].ncells = 3;
        sprintf(g_rows[n].cells[0], "%u", (unsigned)rec->season);
        entry_name(rec->idx, 16, nm);
        strcpy(g_rows[n].cells[1], nm);
        event_text(rec->kind, (int32_t)rec->value, ev);
        strcpy(g_rows[n].cells[2], ev);
    }
    for (k = n; k < MAX_ROWS; k++)
        g_rows[k].ncells = 0;
    return n;
}

/* REVIEW lines for the last recorded season; 0 lines when there is no
 * history; cut at 12 lines */
static int build_review_rows(void)
{
    SeasonEntry se;
    char nm[NAME_CAP_MAX], ev[64];
    int n = 0, i, k, pos;
    uint32_t last;
    static const char *labels[6] = { "AL MVP ", "AL CY YOUNG ",
        "AL ROOKIE ", "NL MVP ", "NL CY YOUNG ", "NL ROOKIE " };
    if (g_hdr_seasons == 0)
        return 0;
    last = g_hdr_seasons;
    pos = (int)(last < SEASON_COUNT ? last : SEASON_COUNT);
    read_season(&se, pos);
    strcpy(g_rows[n].cells[0], "CHAMPION ");
    stem_display(se.champion_stem,
                 g_rows[n].cells[0] + strlen(g_rows[n].cells[0]));
    g_rows[n].ncells = 1;
    n++;
    strcpy(g_rows[n].cells[0], "RUNNER-UP ");
    stem_display(se.runner_up_stem,
                 g_rows[n].cells[0] + strlen(g_rows[n].cells[0]));
    g_rows[n].ncells = 1;
    n++;
    for (i = 0; i < 6; i++) {
        strcpy(g_rows[n].cells[0], labels[i]);
        entry_name(se.awards[i], 16, nm);
        strcat(g_rows[n].cells[0], nm);
        g_rows[n].ncells = 1;
        n++;
    }
    for (i = 0; i < (int)n_entries(); i++) {
        Entry e;
        read_entry(&e, (uint32_t)i);
        if (e.status == STATUS_HOF && e.hof_season == last) {
            name_display(e.name, 18, nm);
            strcpy(g_rows[n].cells[0], "NEW HALL OF FAME: ");
            strcat(g_rows[n].cells[0], nm[0] ? nm : "?");
            g_rows[n].ncells = 1;
            n++;
            if (n >= ROWS_PER_PAGE)
                goto done;
        }
    }
    for (i = 0; i < g_nms; i++) {
        MsRec *rec = &g_ms[i];
        if (rec->season != last)
            continue;
        entry_name(rec->idx, 16, nm);
        event_text(rec->kind, (int32_t)rec->value, ev);
        strcpy(g_rows[n].cells[0], nm);
        strcat(g_rows[n].cells[0], " ");
        strcat(g_rows[n].cells[0], ev);
        g_rows[n].ncells = 1;
        n++;
        if (n >= ROWS_PER_PAGE)
            goto done;
    }
done:
    for (k = n; k < MAX_ROWS; k++)
        g_rows[k].ncells = 0;
    return n;
}

static void build_menu_rows(void)
{
    static const char *items[5] = {
        "1  SEASON HISTORY", "2  HALL OF FAME", "3  CAREER LEADERS",
        "4  MILESTONES", "5  LAST SEASON REVIEW" };
    int k;
    for (k = 0; k < 5; k++) {
        strcpy(g_rows[k].cells[0], items[k]);
        g_rows[k].ncells = 1;
    }
    for (; k < MAX_ROWS; k++)
        g_rows[k].ncells = 0;
}

static void build_no_hist_rows(void)
{
    strcpy(g_rows[0].cells[0], "NO DYNASTY HISTORY YET");
    g_rows[0].ncells = 1;
    g_nrows = 1;
}

/* ---------------- state machine ---------------- */

/* number of model rows of the current state (paging bound) */
static int total_rows(State st)
{
    switch (st.screen) {
    case SCREEN_HISTORY:
        hist_scan(&g_histl);
        return g_histl.n;
    case SCREEN_HOF:
        hof_scan(&g_hofl);
        return g_hofl.n;
    case SCREEN_LEADERS:
        return leaders_count(st.cat);
    case SCREEN_MILESTONES: {
        List b;
        ms_scan(&b);
        return (int)b.n;
    }
    case SCREEN_REVIEW:
        return build_review_rows();
    default:
        return 5;
    }
}

/* rows of the current page into g_rows (matches dynview.rows; every screen
 * shows 'NO DYNASTY HISTORY YET' on a new file) */
static int refresh_rows(State st)
{
    if (g_hdr_seasons == 0) {
        build_no_hist_rows();
        return g_nrows;
    }
    switch (st.screen) {
    case SCREEN_MENU:
        build_menu_rows();
        return 5;
    case SCREEN_LEADERS:
        leaders_scan(&g_leadl, st.cat);
        return build_lead_rows(st.cat, st.page);
    case SCREEN_HISTORY:
        hist_scan(&g_histl);
        return build_hist_rows(st.page);
    case SCREEN_HOF:
        hof_scan(&g_hofl);
        return build_hof_rows(st.page);
    case SCREEN_MILESTONES:
        ms_scan(&g_msl);
        return build_ms_rows(st.page);
    default:
        return build_review_rows();
    }
}

/* step: ESC exits from MENU, otherwise goes back to MENU; PGUP/PGDN page by
 * 12; LEFT/RIGHT cycle the LEADERS category */
static State step(State in, int32_t key)
{
    State s = in;
    if (key == KEY_ESC) {
        if (s.screen == SCREEN_MENU)
            g_exit = 1;
        s.screen = SCREEN_MENU;
        s.page = 0;
        s.cat = 0;
        return s;
    }
    if (s.screen == SCREEN_MENU) {
        if (49 <= key && key <= 53) {
            s.screen = (int16_t)(key - 48);
            s.page = 0;
            s.cat = 0;
        }
        return s;
    }
    if (s.screen == SCREEN_REVIEW && key == KEY_ENTER) {
        s.screen = SCREEN_MENU;
        s.page = 0;
        s.cat = 0;
        return s;
    }
    if (key == KEY_PGDN) {
        int n = total_rows(s);
        if (s.page * ROWS_PER_PAGE + ROWS_PER_PAGE < n)
            s.page++;
        return s;
    }
    if (key == KEY_PGUP) {
        if (s.page > 0)
            s.page--;
        return s;
    }
    if (s.screen == SCREEN_LEADERS && (key == KEY_LEFT || key == KEY_RIGHT)) {
        int d = (key == KEY_LEFT) ? -1 : 1;
        s.page = 0;
        s.cat = (int16_t)((s.cat + d + N_CATS) % N_CATS);
        return s;
    }
    return s;
}

/* ---------------- rendering ---------------- */

/* columns: (header, x, width_chars, right-aligned). Every MAIN.FNT glyph
 * advances CHAR_W, so a row holds 42 chars from x 10; right-aligned widths
 * include one leading separator char */
typedef struct {
    const char *header;
    int x, w, ralign;
} ColDef;

#define CX(pos) (10 + CHAR_W * (pos))

static const ColDef COLS_SINGLE[] = {
    { " ", CX(0), 42, 0 } };

static const ColDef COLS_HISTORY[] = {
    { "YEAR", CX(0), 4, 0 }, { "CHAMPION", CX(5), 13, 0 },
    { "AL MVP", CX(19), 11, 0 }, { "NL MVP", CX(31), 11, 0 } };

static const ColDef COLS_HOF[] = {
    { "NAME", CX(0), 12, 0 }, { "IND", CX(12), 4, 1 }, { "YRS", CX(16), 4, 1 },
    { "H/W", CX(20), 5, 1 }, { "HR/K", CX(25), 5, 1 },
    { "AV/ER", CX(30), 6, 1 }, { "WAR", CX(36), 6, 1 } };

static const ColDef COLS_LEADERS[] = {
    { "#", CX(0), 5, 0 }, { "NAME", CX(5), 16, 0 }, { " ", CX(22), 1, 0 },
    { "YRS", CX(23), 5, 1 }, { "VALUE", CX(28), 14, 1 } };

static const ColDef COLS_MILESTONES[] = {
    { "YEAR", CX(0), 4, 0 }, { "NAME", CX(5), 16, 0 },
    { "EVENT", CX(22), 20, 0 } };

#define NCOLS(a) ((int)(sizeof(a) / sizeof((a)[0])))

static int n_cols(const ColDef *cols)
{
    if (cols == COLS_SINGLE)
        return NCOLS(COLS_SINGLE);
    if (cols == COLS_HISTORY)
        return NCOLS(COLS_HISTORY);
    if (cols == COLS_HOF)
        return NCOLS(COLS_HOF);
    if (cols == COLS_LEADERS)
        return NCOLS(COLS_LEADERS);
    return NCOLS(COLS_MILESTONES);
}

static const ColDef *body_cols(State st)
{
    /* the one-cell 'NO DYNASTY HISTORY YET' row always uses COLS_SINGLE so it
     * is never cut to a narrow first column */
    if (g_hdr_seasons == 0)
        return COLS_SINGLE;
    switch (st.screen) {
    case SCREEN_MENU:
        return COLS_SINGLE;
    case SCREEN_HISTORY:
        return COLS_HISTORY;
    case SCREEN_HOF:
        return COLS_HOF;
    case SCREEN_LEADERS:
        return COLS_LEADERS;
    case SCREEN_MILESTONES:
        return COLS_MILESTONES;
    default:
        return COLS_SINGLE;
    }
}

static void screen_title(State st, char *dst)
{
    if (st.screen == SCREEN_MENU)
        strcpy(dst, "DYNASTY");
    else if (st.screen == SCREEN_HISTORY)
        strcpy(dst, "SEASON HISTORY");
    else if (st.screen == SCREEN_HOF)
        strcpy(dst, "HALL OF FAME");
    else if (st.screen == SCREEN_LEADERS) {
        strcpy(dst, "CAREER LEADERS: ");
        strcat(dst, CAT_LABEL[st.cat]);
    } else if (st.screen == SCREEN_MILESTONES)
        strcpy(dst, "MILESTONES");
    else
        sprintf(dst, "SEASON %u IN REVIEW", (unsigned)g_hdr_seasons);
}

static void draw_panel(void)
{
    fill_fb(C_BG_BROWN);
    rect_fb(4, 4, 315, 195, C_FRAME_TAN);
    rect_fb(8, 8, 311, 20, C_TITLE_RED);
    rect_fb(4, 4, 315, 4, C_BLACK);
    rect_fb(4, 195, 315, 195, C_BLACK);
    rect_fb(4, 4, 4, 195, C_BLACK);
    rect_fb(315, 4, 315, 195, C_BLACK);
}

/* render into g_fb: panel, bold title with a drop shadow, gold header row,
 * tan rows with a gray underline, footer. Matches dynview.render exactly. */
static void render(State st)
{
    static const char *footers[6] = {
        "1-5 SELECT   ESC EXIT",
        "PGUP PGDN   ESC MENU",
        "PGUP PGDN   ESC MENU",
        "LEFT RIGHT CATEGORY   ESC MENU",
        "PGUP PGDN   ESC MENU",
        "ENTER MENU   ESC MENU" };
    const ColDef *cols;
    uint8_t up[64];
    int tx, r, ci;
    draw_panel();
    /* screen_title then the centered bold title with its shadow */
    {
        char tbuf[64];
        screen_title(st, tbuf);
        strcpy((char *)up, tbuf);
    }
    tx = 8 + (304 - text_width(g_bold, up)) / 2;
    draw_text(g_fb, g_bold, tx + 1, 11, up, C_BLACK);
    draw_text(g_fb, g_bold, tx, 10, up, C_WHITE);
    cols = body_cols(st);
    rect_fb(8, 24, 311, 33, C_HEADER_GOLD);
    for (ci = 0; ci < n_cols(cols); ci++) {
        const ColDef *cd = &cols[ci];
        uint8_t h[16];
        int hl = (int)strlen(cd->header);
        if (hl > cd->w)
            hl = cd->w;
        memcpy(h, cd->header, (size_t)hl);
        h[hl] = 0;
        if (cd->ralign)
            draw_text(g_fb, g_main, cd->x + cd->w * CHAR_W - text_width(g_main, h),
                      26, h, C_BLACK);
        else
            draw_text(g_fb, g_main, cd->x, 26, h, C_BLACK);
    }
    g_nrows = refresh_rows(st);
    for (r = 0; r < g_nrows; r++) {
        const Row *row = &g_rows[r];
        int y0 = 35 + r * ROW_H;
        rect_fb(8, y0, 311, y0 + 9, C_ROW_TAN);
        for (ci = 0; ci < row->ncells && ci < n_cols(cols); ci++) {
            const ColDef *cd = &cols[ci];
            const uint8_t *cell = (const uint8_t *)row->cells[ci];
            /* cells cut to the column width in bytes (Python cell[:w]) */
            int cl = (int)strlen((const char *)cell);
            if (cl > cd->w)
                cl = cd->w;
            {
                uint8_t shown[256];
                if (cl > (int)sizeof shown - 1)
                    cl = (int)sizeof shown - 1;
                memcpy(shown, cell, (size_t)cl);
                shown[cl] = 0;
                if (cd->ralign)
                    draw_text(g_fb, g_main,
                              cd->x + cd->w * CHAR_W - text_width(g_main, shown),
                              y0 + 2, shown, C_BLACK);
                else
                    draw_text(g_fb, g_main, cd->x, y0 + 2, shown, C_BLACK);
            }
        }
        rect_fb(8, y0 + 10, 311, y0 + 10, C_GRID_GRAY);
    }
    draw_text(g_fb, g_main, 10, 185, (const uint8_t *)footers[st.screen],
              C_WHITE);
}

/* ---------------- fonts / palette ---------------- */

static int read_fnt_file(const char *path, Font **out)
{
    uint8_t *fbuf;
    FILE *f;
    Font *ft;
    uint16_t count, i;
    size_t p = 2, n;
    long len;
    f = fopen(path, "rb");
    if (!f)
        return 0;
    if (fseek(f, 0L, SEEK_END) != 0 || (len = ftell(f)) < 2 || len > 65000L
            || fseek(f, 0L, SEEK_SET) != 0) {
        fclose(f);
        return 0;
    }
    fbuf = (uint8_t *)malloc((size_t)len);
    if (!fbuf) {
        fclose(f);
        return 0;
    }
    n = fread(fbuf, 1, (size_t)len, f);
    fclose(f);
    if (n != (size_t)len) {
        free(fbuf);
        return 0;
    }
    count = (uint16_t)(fbuf[0] | ((uint16_t)fbuf[1] << 8));
    if (count < 95) {
        free(fbuf);
        return 0;
    }
    ft = (Font *)calloc(1, sizeof(Font));
    if (!ft) {
        free(fbuf);
        return 0;
    }
    ft->count = count;
    /* parse_fnt layout: per glyph u8 rows, u8 bits, u8 adv, rows*ceil(bits/8)
     * bytes, MSB first; the whole file must be consumed (assert p == len) */
    for (i = 0; i < 95; i++) {
        uint8_t rows, bits, adv;
        size_t bpr, sz;
        if (p + 3 > n) {
            free(ft);
            free(fbuf);
            return 0;
        }
        rows = fbuf[p];
        bits = fbuf[p + 1];
        adv = fbuf[p + 2];
        p += 3;
        bpr = ((size_t)bits + 7) / 8;
        sz = (size_t)rows * bpr;
        if (p + sz > n) {
            free(ft);
            free(fbuf);
            return 0;
        }
        ft->g[i].rows = rows;
        ft->g[i].bits = bits;
        ft->g[i].adv = adv;
        ft->g[i].bpr = (uint8_t)bpr;
        ft->g[i].off = (uint16_t)p;
        p += sz;
    }
    /* parse_fnt length check: the glyphs must consume exactly the file */
    if (p != n) {
        free(ft);
        free(fbuf);
        return 0;
    }
    ft->bytes = fbuf;
    *out = ft;
    return 1;
}

static void free_font(Font **ft)
{
    if (*ft) {
        free((*ft)->bytes);
        free(*ft);
        *ft = NULL;
    }
}

static int load_font_file(const char *dir, const char *leaf, Font **out)
{
    char path[600];
    if (2 + strlen(dir) + strlen(leaf) >= sizeof path)
        return 0;
    path_join(path, dir, leaf);
    return read_fnt_file(path, out);
}

/* DEFAULT.PAL raw 6-bit triples; missing file: gray-ramp fallback */
static void load_palette_file(const char *dir)
{
    char path[600];
    FILE *f;
    int i;
    for (i = 0; i < 768; i++)
        g_pal[i] = 0;
    path_join(path, dir, "DEFAULT.PAL");
    f = fopen(path, "rb");
    if (!f) {
        /* load_palette fallback: deterministic gray ramp (i & 63) */
        for (i = 0; i < 256; i++)
            g_pal[i * 3] = g_pal[i * 3 + 1] = g_pal[i * 3 + 2]
                           = (uint8_t)(i & 63);
        return;
    }
    if (fread(g_pal, 1, 768, f) != 768) {
        fclose(f);
        for (i = 0; i < 256; i++)
            g_pal[i * 3] = g_pal[i * 3 + 1] = g_pal[i * 3 + 2]
                           = (uint8_t)(i & 63);
        return;
    }
    fclose(f);
}

#ifdef __WATCOMC__

/* critical-error handler: never show Abort, Retry, Fail on an empty CD drive.
 * The Watcom __harderr form: _WCHANDLER + _WCFAR pointer (dos.h's _DOSFAR
 * does not parse under this wcl). */
static int _WCHANDLER _hard_err_handler(unsigned deverr, unsigned errcode,
                                        unsigned _WCFAR *devhdr)
{
    (void)deverr;
    (void)errcode;
    (void)devhdr;
    return _HARDERR_FAIL;
}

#endif

/* FONT_DIR given: MAIN.FNT, BOLD.FNT, DEFAULT.PAL from it. When not given:
 * try the current directory then drives D:..Z: (X:\MAIN.FNT), first hit wins
 * (all three files from that dir). Host: only the current directory. */
static int load_fonts_probe(const char *font_dir, int have_dir)
{
    if (have_dir) {
        if (!load_font_file(font_dir, "MAIN.FNT", &g_main))
            return 0;
        if (!load_font_file(font_dir, "BOLD.FNT", &g_bold)) {
            free_font(&g_main);
            return 0;
        }
        load_palette_file(font_dir);
        return 1;
    }
#ifdef __WATCOMC__
    {
        char cand[4];
        int drv;
        strcpy(cand, ".");
        if (load_font_file(cand, "MAIN.FNT", &g_main)
            && load_font_file(cand, "BOLD.FNT", &g_bold)) {
            load_palette_file(cand);
            return 1;
        }
        if (g_main) {
            free_font(&g_main);
        }
        for (drv = 'D'; drv <= 'Z'; drv++) {
            cand[0] = (char)drv;
            cand[1] = ':';
            cand[2] = '\0';
            if (load_font_file(cand, "MAIN.FNT", &g_main)
                && load_font_file(cand, "BOLD.FNT", &g_bold)) {
                load_palette_file(cand);
                return 1;
            }
            if (g_main) {
                free_font(&g_main);
            }
        }
        return 0;
    }
#else
    (void)have_dir;
    if (load_font_file(".", "MAIN.FNT", &g_main)
        && load_font_file(".", "BOLD.FNT", &g_bold)) {
        load_palette_file(".");
        return 1;
    }
    if (g_main) {
        free_font(&g_main);
    }
    return 0;
#endif
}

/* ---------------- argv ---------------- */

/* each token decimal or 0x hex (Python int(t, 0)) */
static int32_t parse_key(const uint8_t *t)
{
    return (int32_t)strtol((const char *)t, NULL, 0);
}

/* apply step() for each token in order, ignoring the exit flag */
static void parse_keys(const uint8_t *s)
{
    uint8_t tok[64];
    while (s[0]) {
        int i = 0;
        while (s[0] && s[0] != ',') {
            if ((size_t)i + 1 < sizeof tok)
                tok[i++] = s[0];
            s++;
        }
        tok[i] = 0;
        if (i > 0)
            g_state = step(g_state, parse_key(tok));
        if (s[0] == ',')
            s++;
    }
}

static int arg_flag(const uint8_t *a, const char *name)
{
    uint8_t up[16];
    size_t i;
    if (a[0] != '/')
        return 0;
    a++;
    for (i = 0; a[i] && i + 1 < sizeof up; i++)
        up[i] = (uint8_t)((a[i] >= 'A' && a[i] <= 'Z') ? a[i] + 32 : a[i]);
    up[i] = 0;
    return strcmp((const char *)up, name) == 0;
}

/* match /NAME:VALUE in any case, VALUE returned */
static const uint8_t *arg_switch(const uint8_t *a, const char *name)
{
    uint8_t up[16];
    size_t n = strlen(name), i;
    if (a[0] != '/')
        return NULL;
    a++;
    for (i = 0; a[i] && i + 1 < sizeof up; i++)
        up[i] = (uint8_t)((a[i] >= 'A' && a[i] <= 'Z') ? a[i] + 32 : a[i]);
    up[i] = 0;
    if (strncmp((const char *)up, name, n) != 0 || up[n] != ':')
        return NULL;
    return a + n + 1;
}

static int usage(void)
{
    fprintf(stderr, "usage: DYNVIEW [/REVIEW] [/KEYS:k,k,...] [/RAW:FILE] "
            "[LEAGUE_DIR [FONT_DIR]]\n");
    return 2;
}

#ifdef __WATCOMC__

static void init_vga_mode13(void)
{
    union REGS rg;
    rg.w.ax = 0x0013;
    int86(0x10, &rg, &rg);
}

static void exit_vga_text(void)
{
    union REGS rg;
    rg.w.ax = 0x0003;
    int86(0x10, &rg, &rg);
}

/* the 256 DEFAULT.PAL triples to the DAC: port 3C8h index 0, then 768 bytes
 * to 3C9h, raw 6-bit values */
static void load_dac(void)
{
    int i;
    outp(0x3c8, 0);
    for (i = 0; i < 768; i++)
        outp(0x3c9, (unsigned)(g_pal[i] & 0x3fu));
}

static void fb_to_vram(void)
{
    memcpy((void _far *)MK_FP(0xa000, 0), g_fb, FB_SIZE);
}

/* int 16h AH=0: key = AL when AL is nonzero and not E0h, else AX & FF00h */
static unsigned read_key(void)
{
    union REGS rg;
    rg.h.ah = 0;
    int86(0x16, &rg, &rg);
    if (rg.h.al != 0 && rg.h.al != 0xe0)
        return rg.h.al;
    return (unsigned)(rg.x.ax & 0xff00u);
}

#endif /* __WATCOMC__ */

int main(int argc, char **argv)
{
    const char *league = (DIR_SEP == '\\') ? DEF_LEAGUE : DEF_LEAGUE_HOST;
    const char *font_dir = NULL;
    const uint8_t *keys = NULL, *raw_path = NULL;
    int have_fonts, raw_mode = 0, review = 0, i, npos = 0;
    State st;

#ifdef __WATCOMC__
    _harderr(_hard_err_handler);
#endif

    memset(g_hdr, 0, sizeof g_hdr);
    for (i = 1; i < argc; i++) {
        const uint8_t *v;
        if (arg_flag((const uint8_t *)argv[i], "review")) {
            review = 1;
        } else if ((v = arg_switch((const uint8_t *)argv[i], "keys")) != NULL) {
            keys = v;
        } else if ((v = arg_switch((const uint8_t *)argv[i], "raw")) != NULL) {
            raw_path = v;
            raw_mode = 1;
        } else if (argv[i][0] == '/') {
            if (DIR_SEP == '/' && strchr(argv[i] + 1, '/') != NULL) {
                /* host absolute path (never a DOS switch): positional */
                if (npos == 0) {
                    league = argv[i];
                    npos++;
                } else if (npos == 1) {
                    font_dir = argv[i];
                    npos++;
                } else {
                    return usage();
                }
            } else {
                return usage();
            }
        } else if (npos == 0) {
            league = argv[i];
            npos++;
        } else if (npos == 1) {
            font_dir = argv[i];
            npos++;
        } else {
            return usage();
        }
    }

#ifndef __WATCOMC__
    /* the host binary without /RAW prints usage and exits 2 (before the
     * font check: the host never has a video mode to touch) */
    if (!raw_mode)
        return usage();
#endif

    /* MAIN.FNT or BOLD.FNT missing or failing the parse_fnt length check:
     * print the message and exit 2 without touching the video mode */
    have_fonts = load_fonts_probe(font_dir, font_dir != NULL);
    if (!have_fonts) {
        fprintf(stderr, "DYNVIEW: FONTS NOT FOUND\n");
        return 2;
    }
    if (strlen(league) >= sizeof g_lgdir)
        return 2;
    strcpy(g_lgdir, league);
    if (!load_hist(league))
        return 2;
    if (!load_ms(league))
        return 2;

    st.screen = review ? SCREEN_REVIEW : SCREEN_MENU;
    st.page = 0;
    st.cat = 0;
    g_state = st;
    if (keys != NULL)
        parse_keys(keys);
    st = g_state;

    if (raw_mode) {
        /* /RAW: after the keys, render once and write the 64000 B framebuffer;
         * never touch video, keyboard or palette in this mode */
        FILE *f;
        render(st);
        f = fopen((const char *)raw_path, "wb");
        if (!f)
            return 2;
        if (fwrite(g_fb, 1, FB_SIZE, f) != FB_SIZE) {
            fclose(f);
            remove((const char *)raw_path);
            return 2;
        }
        if (fclose(f) != 0)
            return 2;
        return 0;
    }
#ifdef __WATCOMC__
    {
        int quit = 0;
        init_vga_mode13();
        load_dac();
        render(st);
        fb_to_vram();
        while (!quit) {
            unsigned k = read_key();
            State prev = st;
            st = step(st, (int32_t)k);
            if (g_exit) {
                exit_vga_text();
                quit = 1;
            } else if (st.screen != prev.screen || st.page != prev.page
                       || st.cat != prev.cat) {
                /* render only after a key changed the state */
                render(st);
                fb_to_vram();
            }
        }
        return 0;
    }
#endif
}

