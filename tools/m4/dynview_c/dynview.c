/* DYNVIEW: C port of tools/m4/dynview.py (T5a reference renderer). Host build
 * with gcc for parity tests, DOS build with OpenWatcom (16-bit real mode).
 * Streams HISTORY.DAT (one 160 B player entry at a time) and keeps sorted
 * top-LIST_MAX list buffers; screen output matches the Python reference pixel
 * for pixel.
 * usage: DYNVIEW [/REVIEW] [/OFFSEASON] [/KEYS:k,k,...] [/RAW:FILE] [LEAGUE_DIR [FONT_DIR]]
 * (/OFFSEASON wins when both are given)
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
#define SCREEN_OFFSEASON 6
#define N_CATS 12

/* offseason phases: cat & 15 is the phase, cat >> 4 the launched flag */
#define OFF_REVIEW 0
#define OFF_RETIRE 1
#define OFF_DRAFT 2
#define OFF_TRADES 3
#define OFF_FA 4
#define OFF_READY 5

/* ROSTERS.TXT: lines over ROSTER_LINE_MAX bytes are ignored whole, DRAFT lines past
 * DRAFT_KEEP are dropped; TOK_MAX bounds the tokens of one line (127 B holds 64) */
#define ROSTER_LINE_MAX 127
#define DRAFT_KEEP 400
#define TOK_MAX 64

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
    uint8_t age;
    uint16_t seasons_played;
    uint16_t last_season;
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

/* column of a table: header, x, width in chars, right-aligned */
typedef struct {
    const char *header;
    int x, w, ralign;
} ColDef;

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
static List FARDATA g_list_buf[5];
#define g_histl  (g_list_buf[0])
#define g_hofl   (g_list_buf[1])
#define g_leadl  (g_list_buf[2])
#define g_msl    (g_list_buf[3])
#define g_retl   (g_list_buf[4])

static Row FARDATA g_rows[MAX_ROWS];
static int g_nrows;

/* ROSTERS.TXT draft table (loaded once): the first DRAFT_KEEP valid DRAFT lines.
 * Slot: [0] stem length, [1] name length, then the upper-case stem and the joined
 * name. g_used marks the DRAFT lines consumed by SIGN picks in one pass. */
static uint8_t FARDATA g_drafts[DRAFT_KEEP][128];
static int g_ndrafts;
static uint8_t g_used[DRAFT_KEEP];

/* uncapped counts of one ROSTERS.TXT pass */
typedef struct {
    uint32_t picks, fa, trades, rel;
} RosterCounts;
static RosterCounts g_rc;

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
static const ColDef *body_cols(State st);
static int offseason_body(State st, int page, const ColDef **cols);
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

/* ASCII upper case of one byte (a-z only, like DOS) */
static uint8_t ascii_up(uint8_t c)
{
    return (uint8_t)((c >= 'a' && c <= 'z') ? c - 32 : c);
}

/* n bytes into a cell (SLEN - 1 max); NUL shows as '?', the glyph of any byte
 * outside 32..126 */
static void put_cell(char *dst, const uint8_t *s, int n)
{
    int i;
    if (n > SLEN - 1)
        n = SLEN - 1;
    for (i = 0; i < n; i++)
        dst[i] = s[i] ? (char)s[i] : '?';
    dst[n] = 0;
}

/* the token (n bytes at s) equals the upper-case literal t; ci folds a-z first */
static int tok_eq(const uint8_t *s, int n, const char *t, int ci)
{
    int i;
    if (n != (int)strlen(t))
        return 0;
    for (i = 0; i < n; i++) {
        uint8_t c = ci ? ascii_up(s[i]) : s[i];
        if (c != (uint8_t)t[i])
            return 0;
    }
    return 1;
}

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

/* LEAGUE_DIR\<STEM>.V20 (STEM: n bytes, upper-cased) opened for reading: NULL when
 * the stem is not a 1..8 byte leaf (no NUL, slash, backslash or colon), the path is
 * too long or the file is missing */
static FILE *open_v20(const uint8_t *s, int n)
{
    char path[300], leaf[16];
    int i;
    if (n < 1 || n > 8)
        return NULL;
    for (i = 0; i < n; i++) {
        if (s[i] == 0 || s[i] == '/' || s[i] == '\\' || s[i] == ':')
            return NULL;
        leaf[i] = (char)ascii_up(s[i]);
    }
    strcpy(leaf + n, ".V20");
    if (strlen(g_lgdir) + 2 + (size_t)n + 4 >= sizeof path)
        return NULL;
    path_join(path, g_lgdir, leaf);
    return fopen(path, "rb");
}

/* 1 when the token names a team file (see open_v20) */
static int team_file(const uint8_t *s, int n)
{
    FILE *f = open_v20(s, n);
    if (!f)
        return 0;
    fclose(f);
    return 1;
}

/* team_name: V20 header name (bytes 0..13, NUL ended, trailing spaces cut) of the
 * team file for the stem s (n bytes); "" when there is no file or the name blank */
static void team_name(const uint8_t *s, int n, char *dst)
{
    uint8_t raw[14];
    FILE *f;
    dst[0] = 0;
    f = open_v20(s, n);
    if (!f)
        return;
    memset(raw, 0, sizeof raw);
    (void)fread(raw, 1, sizeof raw, f);
    fclose(f);
    field_of(raw, 14, dst);
}

/* team column of a team token: the V20 header name, else the token upper-cased */
static void team_disp(const uint8_t *s, int n, char *dst)
{
    int i;
    team_name(s, n, dst);
    if (dst[0])
        return;
    put_cell(dst, s, n);
    for (i = 0; dst[i]; i++)
        dst[i] = (char)ascii_up((uint8_t)dst[i]);
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
    team_name((const uint8_t *)stem, (int)strlen(stem), dst);
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
    e->age = eb[23];
    e->pitcher = eb[31];
    e->seasons_played = (uint16_t)(eb[28] | ((uint16_t)eb[29] << 8));
    e->last_season = (uint16_t)(eb[26] | ((uint16_t)eb[27] << 8));
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

/* ---------------- ROSTERS.TXT (offseason) ---------------- */

/* next usable line into buf (*len bytes): LF split, one trailing CR stripped, a
 * line over ROSTER_LINE_MAX bytes skipped whole. 0 at end of file. */
static int roster_line(FILE *f, uint8_t *buf, int *len)
{
    for (;;) {
        long total = 0;
        int c, n = 0;
        while ((c = fgetc(f)) != EOF && c != '\n') {
            if (n < 128)
                buf[n++] = (uint8_t)c;
            total++;
        }
        if (c == EOF && total == 0)
            return 0;
        if (total <= 128) {
            int content = (int)total;
            if (content > 0 && buf[content - 1] == '\r')
                content--;
            if (content <= ROSTER_LINE_MAX) {
                *len = content;
                return 1;
            }
        }
    }
}

/* tokens of buf[0..len): split on spaces, empty ones dropped; returns the count */
static int tokenize(const uint8_t *buf, int len, int *toff, int *tlen)
{
    int i = 0, n = 0;
    while (i < len) {
        while (i < len && buf[i] == ' ')
            i++;
        if (i >= len)
            break;
        toff[n] = i;
        while (i < len && buf[i] != ' ')
            i++;
        tlen[n] = i - toff[n];
        n++;
    }
    return n;
}

/* tokens from..to-1 joined with single spaces into dst (NUL ended); returns the length */
static int join_toks(const uint8_t *buf, const int *toff, const int *tlen,
                     int from, int to, uint8_t *dst)
{
    int k, n = 0;
    for (k = from; k < to; k++) {
        if (k > from)
            dst[n++] = ' ';
        memcpy(dst + n, buf + toff[k], (size_t)tlen[k]);
        n += tlen[k];
    }
    dst[n] = 0;
    return n;
}

/* the DRAFT table: the first DRAFT_KEEP DRAFT lines with 3 or more tokens */
static void load_drafts(void)
{
    char path[600];
    uint8_t buf[128], joined[128];
    int toff[TOK_MAX], tlen[TOK_MAX], len, n, k;
    FILE *f;
    g_ndrafts = 0;
    path_join(path, g_lgdir, "ROSTERS.TXT");
    f = fopen(path, "rb");
    if (!f)
        return;
    while (roster_line(f, buf, &len)) {
        n = tokenize(buf, len, toff, tlen);
        if (n >= 3 && g_ndrafts < DRAFT_KEEP
            && tok_eq(buf + toff[0], tlen[0], "DRAFT", 0)) {
            uint8_t *rec = g_drafts[g_ndrafts];
            int nl = join_toks(buf, toff, tlen, 2, n, joined);
            rec[0] = (uint8_t)tlen[1];
            rec[1] = (uint8_t)nl;
            for (k = 0; k < tlen[1]; k++)
                rec[2 + k] = ascii_up(buf[toff[1] + k]);
            memcpy(rec + 2 + tlen[1], joined, (size_t)nl);
            g_ndrafts++;
        }
    }
    fclose(f);
}

/* a SIGN pick: the first unconsumed DRAFT whose upper-case stem and name match
 * consumes it and returns 1; 0 when none does */
static int draft_take(const uint8_t *from_up, int nfrom, const uint8_t *name, int nname)
{
    int i;
    for (i = 0; i < g_ndrafts; i++) {
        const uint8_t *rec = g_drafts[i];
        if (g_used[i] || rec[0] != nfrom || rec[1] != nname)
            continue;
        if (memcmp(rec + 2, from_up, (size_t)nfrom) == 0
            && memcmp(rec + 2 + nfrom, name, (size_t)nname) == 0) {
            g_used[i] = 1;
            return 1;
        }
    }
    return 0;
}

/* g_rows slot of row ord when page shows it, else -1 (page < 0 shows nothing) */
static int row_slot(uint32_t ord, int page)
{
    uint32_t lo;
    if (page < 0 || ord >= LIST_MAX)
        return -1;
    lo = (uint32_t)page * ROWS_PER_PAGE;
    if (ord < lo || ord >= lo + ROWS_PER_PAGE)
        return -1;
    return (int)(ord - lo);
}

/* one ROSTERS.TXT pass: every SIGN, TRADE and REL line is counted in g_rc (uncapped).
 * The rows of phase (OFF_DRAFT, OFF_TRADES or OFF_FA) that page shows go to g_rows;
 * any other phase or page < 0 only counts. */
static void roster_pass(int phase, int page)
{
    char path[600];
    uint8_t buf[128], nm[128], from_up[128];
    int toff[TOK_MAX], tlen[TOK_MAX], len, n;
    FILE *f;
    memset(g_used, 0, sizeof g_used);
    memset(&g_rc, 0, sizeof g_rc);
    path_join(path, g_lgdir, "ROSTERS.TXT");
    f = fopen(path, "rb");
    if (!f)
        return;
    while (roster_line(f, buf, &len)) {
        n = tokenize(buf, len, toff, tlen);
        if (n >= 4 && tok_eq(buf + toff[0], tlen[0], "SIGN", 0)) {
            int nname = join_toks(buf, toff, tlen, 2, n - 1, nm);
            int nfrom = tlen[n - 1], k;
            for (k = 0; k < nfrom; k++)
                from_up[k] = ascii_up(buf[toff[n - 1] + k]);
            if (draft_take(from_up, nfrom, nm, nname)) {
                uint32_t ord = g_rc.picks++;
                int s = phase == OFF_DRAFT ? row_slot(ord, page) : -1;
                if (s >= 0) {
                    Row *r = &g_rows[s];
                    sprintf(r->cells[0], "#%lu", (unsigned long)(ord + 1));
                    team_disp(buf + toff[1], tlen[1], r->cells[1]);
                    put_cell(r->cells[2], nm, nname);
                    r->ncells = 3;
                }
            } else {
                uint32_t ord = g_rc.fa++;
                int s = phase == OFF_FA ? row_slot(ord, page) : -1;
                if (s >= 0) {
                    Row *r = &g_rows[s];
                    team_disp(buf + toff[1], tlen[1], r->cells[0]);
                    put_cell(r->cells[1], nm, nname);
                    if (tok_eq(buf + toff[n - 1], nfrom, "POOL", 1))
                        strcpy(r->cells[2], "FREE AGENT");
                    else
                        team_disp(buf + toff[n - 1], nfrom, r->cells[2]);
                    r->ncells = 3;
                }
            }
        } else if (n >= 5 && tok_eq(buf + toff[0], tlen[0], "TRADE", 0)) {
            int j;
            /* B: the first team token from index 3 that names a team file */
            for (j = 3; j <= n - 2; j++)
                if (team_file(buf + toff[j], tlen[j]))
                    break;
            if (j <= n - 2) {
                uint32_t ord = 2u * g_rc.trades;
                int sa = phase == OFF_TRADES ? row_slot(ord, page) : -1;
                int sb = phase == OFF_TRADES ? row_slot(ord + 1u, page) : -1;
                g_rc.trades++;
                if (sa >= 0) {
                    Row *r = &g_rows[sa];
                    int xl = join_toks(buf, toff, tlen, 2, j, nm);
                    team_disp(buf + toff[1], tlen[1], r->cells[0]);
                    put_cell(r->cells[1], nm, xl);
                    team_disp(buf + toff[j], tlen[j], r->cells[2]);
                    r->ncells = 3;
                }
                if (sb >= 0) {
                    Row *r = &g_rows[sb];
                    int yl = join_toks(buf, toff, tlen, j + 1, n, nm);
                    team_disp(buf + toff[j], tlen[j], r->cells[0]);
                    put_cell(r->cells[1], nm, yl);
                    team_disp(buf + toff[1], tlen[1], r->cells[2]);
                    r->ncells = 3;
                }
            }
        } else if (n >= 3 && tok_eq(buf + toff[0], tlen[0], "REL", 0)) {
            g_rc.rel++;
        }
    }
    fclose(f);
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
    static const char *items[6] = {
        "1  SEASON HISTORY", "2  HALL OF FAME", "3  CAREER LEADERS",
        "4  MILESTONES", "5  LAST SEASON REVIEW", "6  OFFSEASON" };
    int k;
    for (k = 0; k < 6; k++) {
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

/* /TITLE menu of a league with no recorded season (dynview.TITLE_ROWS) */
#define N_TITLE_ROWS 10
static void build_title_rows(void)
{
    static const char *lines[N_TITLE_ROWS] = {
        "YOUR LEAGUE NOW PLAYS SEASON AFTER SEASON.",
        "",
        "PLAY THROUGH THE WORLD SERIES, THEN PICK",
        "SEASON > START NEW SEASON. THE OFFSEASON",
        "RUNS: RETIREMENTS, ROOKIE DRAFT, TRADES",
        "AND FREE AGENTS. EVERY SEASON IS ARCHIVED",
        "FIRST, SO NOTHING IS LOST.",
        "",
        "HISTORY, HALL OF FAME, CAREER LEADERS AND",
        "MILESTONES COLLECT HERE AS SEASONS PASS." };
    int k;
    for (k = 0; k < N_TITLE_ROWS; k++) {
        strcpy(g_rows[k].cells[0], lines[k]);
        g_rows[k].ncells = 1;
    }
    g_nrows = N_TITLE_ROWS;
}

/* retirees of the season just recorded (status 2 or 3, last_season == N) into g_retl:
 * WAR10 descending, index ascending, capped. *count gets the uncapped retirees and
 * *new_hof the status 3 entries with hof_season == N. */
static void retire_scan(uint32_t *count, uint32_t *new_hof)
{
    uint32_t i;
    Entry e;
    g_retl.n = 0;
    *count = 0;
    *new_hof = 0;
    for (i = 0; i < n_entries(); i++) {
        read_entry(&e, i);
        if (e.status == STATUS_HOF && e.hof_season == g_hdr_seasons)
            (*new_hof)++;
        if ((e.status == STATUS_RETIRED || e.status == STATUS_HOF)
            && e.last_season == g_hdr_seasons) {
            (*count)++;
            list_add_desc(&g_retl, (int32_t)e.war10, i);
        }
    }
}

/* retirement rows of page (g_retl holds the sorted list): NAME, AGE, YRS, WAR, HOF */
static void build_ret_rows(int page)
{
    int r;
    for (r = page * ROWS_PER_PAGE;
         r < g_retl.n && r < (page + 1) * ROWS_PER_PAGE; r++) {
        Entry e;
        Row *row = &g_rows[r - page * ROWS_PER_PAGE];
        char nm[NAME_CAP_MAX], w[24];
        read_entry(&e, g_retl.idx[r]);
        name_display(e.name, 18, nm);
        put_cell(row->cells[0], (const uint8_t *)nm, (int)strlen(nm));
        sprintf(row->cells[1], "%u", (unsigned)e.age);
        sprintf(row->cells[2], "%u", (unsigned)e.seasons_played);
        fmt_war10(e.war10, w);
        strcpy(row->cells[3], w);
        strcpy(row->cells[4], (e.status == STATUS_HOF && e.hof_season == g_hdr_seasons)
                              ? "HOF" : "");
        row->ncells = 5;
    }
}

/* the seven phase 5 lines (the counts are uncapped totals) */
static void build_ready_rows(uint32_t nret, uint32_t nhof, int launched)
{
    unsigned long n = (unsigned long)g_hdr_seasons;
    int k;
    sprintf(g_rows[0].cells[0], "RETIRED: %lu   NEW HALL OF FAME: %lu",
            (unsigned long)nret, (unsigned long)nhof);
    sprintf(g_rows[1].cells[0], "ROOKIES DRAFTED: %lu", (unsigned long)g_rc.picks);
    sprintf(g_rows[2].cells[0], "TRADES: %lu", (unsigned long)g_rc.trades);
    sprintf(g_rows[3].cells[0], "FREE AGENT SIGNINGS: %lu", (unsigned long)g_rc.fa);
    sprintf(g_rows[4].cells[0], "PLAYERS RELEASED: %lu", (unsigned long)g_rc.rel);
    strcpy(g_rows[5].cells[0], "EVERY PLAYER AGED A YEAR AND DEVELOPED");
    if (launched)
        sprintf(g_rows[6].cells[0], "ENTER: ON TO SEASON %lu", n + 1);
    else
        strcpy(g_rows[6].cells[0], "ENTER: BACK TO THE MENU");
    for (k = 0; k < 7; k++)
        g_rows[k].ncells = 1;
}

/* the one message row of an empty phase: page 0 holds it, any page counts 1 */
static int msg_row(int page, const char *text)
{
    if (page == 0) {
        strcpy(g_rows[0].cells[0], text);
        g_rows[0].ncells = 1;
    }
    return 1;
}

/* a row count capped at LIST_MAX */
static uint32_t capped(uint32_t n)
{
    return n < LIST_MAX ? n : LIST_MAX;
}

/* rows on page of a phase with total rows */
static int page_rows(int total, int page)
{
    int n = total - page * ROWS_PER_PAGE;
    if (n < 0)
        n = 0;
    if (n > ROWS_PER_PAGE)
        n = ROWS_PER_PAGE;
    return n;
}

/* ---------------- state machine ---------------- */

/* number of model rows of the current state (paging bound) */
static int total_rows(State st)
{
    const ColDef *cols;
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
    case SCREEN_OFFSEASON:
        return offseason_body(st, -1, &cols);
    default:
        return 6;
    }
}

/* rows of the current page into g_rows (matches dynview.rows; every screen
 * shows 'NO DYNASTY HISTORY YET' on a new file) and their columns into *cols */
static int refresh_rows(State st, const ColDef **cols)
{
    *cols = body_cols(st);
    if (g_hdr_seasons == 0 && st.screen == SCREEN_MENU && (st.cat >> 4)) {
        build_title_rows();
        return g_nrows;
    }
    if (g_hdr_seasons == 0) {
        build_no_hist_rows();
        return g_nrows;
    }
    switch (st.screen) {
    case SCREEN_MENU:
        build_menu_rows();
        return 6;
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
    case SCREEN_OFFSEASON:
        return page_rows(offseason_body(st, st.page, cols), st.page);
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
        if (49 <= key && key <= 54) {
            s.screen = (int16_t)(key - 48);
            s.page = 0;
            s.cat = 0;
        } else if (key == KEY_ENTER && (s.cat >> 4)) {
            /* /TITLE: ENTER goes on to the game */
            g_exit = 1;
        }
        return s;
    }
    if (s.screen == SCREEN_REVIEW && key == KEY_ENTER) {
        s.screen = SCREEN_MENU;
        s.page = 0;
        s.cat = 0;
        return s;
    }
    /* offseason ENTER: next phase; past the last one exit when launched, else MENU */
    if (s.screen == SCREEN_OFFSEASON && key == KEY_ENTER) {
        if ((s.cat & 15) < OFF_READY && g_hdr_seasons > 0) {
            s.cat = (int16_t)(s.cat + 1);
            s.page = 0;
            return s;
        }
        if (s.cat >> 4) {
            g_exit = 1;
            return s;
        }
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

static const ColDef COLS_RETIRE[] = {
    { "NAME", CX(0), 18, 0 }, { "AGE", CX(18), 5, 1 }, { "YRS", CX(23), 5, 1 },
    { "WAR", CX(28), 7, 1 }, { "HOF", CX(36), 6, 1 } };

static const ColDef COLS_DRAFT[] = {
    { "#", CX(0), 4, 0 }, { "TEAM", CX(4), 15, 0 }, { "PLAYER", CX(19), 23, 0 } };

static const ColDef COLS_MOVE[] = {
    { "TEAM", CX(0), 13, 0 }, { "PLAYER", CX(14), 15, 0 }, { "FROM", CX(30), 12, 0 } };

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
    if (cols == COLS_RETIRE)
        return NCOLS(COLS_RETIRE);
    if (cols == COLS_DRAFT)
        return NCOLS(COLS_DRAFT);
    if (cols == COLS_MOVE)
        return NCOLS(COLS_MOVE);
    return NCOLS(COLS_MILESTONES);
}

static const ColDef *body_cols(State st)
{
    /* the one-cell 'NO DYNASTY HISTORY YET' row always uses COLS_SINGLE so it
     * is never cut to a narrow first column. The offseason's per-phase columns
     * come from offseason_body, which refresh_rows calls after this. */
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

/* offseason phase of st: its rows for page into g_rows (page < 0 counts only).
 * Returns the body row count (capped at LIST_MAX; one message row when the phase
 * is empty; 0 with no history) and sets *cols. */
static int offseason_body(State st, int page, const ColDef **cols)
{
    int phase = st.cat & 15, launched = st.cat >> 4;
    uint32_t nret, nhof, total;
    *cols = COLS_SINGLE;
    if (g_hdr_seasons == 0)
        return 0;
    switch (phase) {
    case OFF_REVIEW:
        return build_review_rows();
    case OFF_RETIRE:
        retire_scan(&nret, &nhof);
        total = capped(nret);
        if (total == 0)
            return msg_row(page, "NO RETIREMENTS");
        if (page >= 0)
            build_ret_rows(page);
        *cols = COLS_RETIRE;
        return (int)total;
    case OFF_DRAFT:
        roster_pass(OFF_DRAFT, page);
        total = capped(g_rc.picks);
        if (total == 0)
            return msg_row(page, "NO DRAFT PICKS");
        *cols = COLS_DRAFT;
        return (int)total;
    case OFF_TRADES:
        roster_pass(OFF_TRADES, page);
        total = capped(2u * g_rc.trades);
        if (total == 0)
            return msg_row(page, "NO TRADES");
        *cols = COLS_MOVE;
        return (int)total;
    case OFF_FA:
        roster_pass(OFF_FA, page);
        total = capped(g_rc.fa);
        if (total == 0)
            return msg_row(page, "NO FREE AGENT SIGNINGS");
        *cols = COLS_MOVE;
        return (int)total;
    default:
        retire_scan(&nret, &nhof);
        roster_pass(-1, -1);
        if (page == 0)
            build_ready_rows(nret, nhof, launched);
        return 7;
    }
}

/* footer line: the offseason's ENTER label follows its phase */
static const char *footer_of(State st)
{
    static const char *footers[6] = {
        "1-6 SELECT   ESC EXIT",
        "PGUP PGDN   ESC MENU",
        "PGUP PGDN   ESC MENU",
        "LEFT RIGHT CATEGORY   ESC MENU",
        "PGUP PGDN   ESC MENU",
        "ENTER MENU   ESC MENU" };
    if (st.screen == SCREEN_MENU && (st.cat >> 4))
        return g_hdr_seasons == 0 ? "ENTER PLAY BALL" : "1-6 SELECT   ENTER PLAY BALL";
    if (st.screen == SCREEN_OFFSEASON) {
        if ((st.cat & 15) < OFF_READY)
            return "ENTER NEXT   PGUP PGDN   ESC MENU";
        return (st.cat >> 4) ? "ENTER CONTINUE   ESC MENU" : "ENTER MENU   ESC MENU";
    }
    return footers[st.screen];
}

static void screen_title(State st, char *dst)
{
    if (st.screen == SCREEN_MENU && (st.cat >> 4))
        sprintf(dst, "DYNASTY MODE: SEASON %lu", (unsigned long)g_hdr_seasons + 1);
    else if (st.screen == SCREEN_MENU)
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
    else if (st.screen == SCREEN_OFFSEASON) {
        int phase = st.cat & 15;
        unsigned long n = (unsigned long)g_hdr_seasons;
        if (phase == OFF_REVIEW)
            sprintf(dst, "1/6 SEASON %lu IN REVIEW", n);
        else if (phase == OFF_RETIRE)
            strcpy(dst, "2/6 RETIREMENTS");
        else if (phase == OFF_DRAFT)
            strcpy(dst, "3/6 ROOKIE DRAFT");
        else if (phase == OFF_TRADES)
            strcpy(dst, "4/6 TRADES");
        else if (phase == OFF_FA)
            strcpy(dst, "5/6 FREE AGENT SIGNINGS");
        else
            sprintf(dst, "6/6 SEASON %lu IS READY", n + 1);
    } else
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
    g_nrows = refresh_rows(st, &cols);
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
    draw_text(g_fb, g_main, 10, 185, (const uint8_t *)footer_of(st), C_WHITE);
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
    fprintf(stderr, "usage: DYNVIEW [/REVIEW] [/OFFSEASON] [/TITLE] [/KEYS:k,k,...] "
            "[/RAW:FILE] [LEAGUE_DIR [FONT_DIR]]\n");
    return 2;
}

#ifdef __WATCOMC__

static void init_vga_mode13(void)
{
    union REGS rg;
    rg.w.ax = 0x0013;
    int86(0x10, &rg, &rg);
}

/* the caller's video state, put back on exit so the next program in TONY2.BAT
 * finds the screen as it left it (MAIN after BACK expects mode 13h with BACK's
 * registers and palette and never sets the mode itself) */
static uint8_t g_vmode;
static uint8_t g_vdac[768];
static uint8_t g_vregs[8];      /* mode 13h only: seq 2, 4; CRTC 0Ch, 0Dh, 14h, 17h; GC 5, 6 */

static uint8_t reg_in(unsigned port, unsigned idx)
{
    outp(port, idx);
    return (uint8_t)inp(port + 1);
}

static void reg_out(unsigned port, unsigned idx, uint8_t v)
{
    outp(port, idx);
    outp(port + 1, v);
}

/* BIOS mode (int 10h AH=0Fh), the 768 DAC bytes (3C7h/3C9h) and, in mode 13h,
 * the registers that unchained (mode X) setups change */
static void save_video(void)
{
    union REGS rg;
    int i;
    rg.h.ah = 0x0f;
    int86(0x10, &rg, &rg);
    g_vmode = (uint8_t)(rg.h.al & 0x7f);
    outp(0x3c7, 0);
    for (i = 0; i < 768; i++)
        g_vdac[i] = (uint8_t)(inp(0x3c9) & 0x3f);
    if (g_vmode == 0x13) {
        g_vregs[0] = reg_in(0x3c4, 2);
        g_vregs[1] = reg_in(0x3c4, 4);
        g_vregs[2] = reg_in(0x3d4, 0x0c);
        g_vregs[3] = reg_in(0x3d4, 0x0d);
        g_vregs[4] = reg_in(0x3d4, 0x14);
        g_vregs[5] = reg_in(0x3d4, 0x17);
        g_vregs[6] = reg_in(0x3ce, 5);
        g_vregs[7] = reg_in(0x3ce, 6);
    }
}

/* back to the saved mode with a cleared screen, then the saved registers and DAC */
static void restore_video(void)
{
    union REGS rg;
    int i;
    rg.h.ah = 0;
    rg.h.al = g_vmode;
    int86(0x10, &rg, &rg);
    if (g_vmode == 0x13) {
        reg_out(0x3c4, 4, g_vregs[1]);
        reg_out(0x3d4, 0x14, g_vregs[4]);
        reg_out(0x3d4, 0x17, g_vregs[5]);
        reg_out(0x3ce, 5, g_vregs[6]);
        reg_out(0x3ce, 6, g_vregs[7]);
        reg_out(0x3d4, 0x0c, g_vregs[2]);
        reg_out(0x3d4, 0x0d, g_vregs[3]);
        /* all four planes, so an unchained caller gets a clear 256 KB too */
        reg_out(0x3c4, 2, 0x0f);
        memset((void _far *)MK_FP(0xa000, 0), 0, 0xffffu);
        *(uint8_t _far *)MK_FP(0xa000, 0xffff) = 0;
        reg_out(0x3c4, 2, g_vregs[0]);
    }
    outp(0x3c8, 0);
    for (i = 0; i < 768; i++)
        outp(0x3c9, g_vdac[i]);
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
    int have_fonts, raw_mode = 0, review = 0, offseason = 0, title = 0, i, npos = 0;
    State st;

#ifdef __WATCOMC__
    _harderr(_hard_err_handler);
#endif

    memset(g_hdr, 0, sizeof g_hdr);
    for (i = 1; i < argc; i++) {
        const uint8_t *v;
        if (arg_flag((const uint8_t *)argv[i], "review")) {
            review = 1;
        } else if (arg_flag((const uint8_t *)argv[i], "offseason")) {
            offseason = 1;
        } else if (arg_flag((const uint8_t *)argv[i], "title")) {
            title = 1;
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
    load_drafts();

    /* /OFFSEASON starts at phase 0 with the launched flag (cat 16); /TITLE is the
     * MENU with cat 16 (precedence /OFFSEASON, /REVIEW, /TITLE) */
    st.screen = offseason ? SCREEN_OFFSEASON : (review ? SCREEN_REVIEW : SCREEN_MENU);
    st.page = 0;
    st.cat = (offseason || (title && !review)) ? 16 : 0;
    g_state = st;
    if (keys != NULL)
        parse_keys(keys);
    st = g_state;
    /* an exit flag set by a /KEYS step (ESC on MENU, ENTER past the last offseason
     * phase) must not end the interactive session */
    g_exit = 0;

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
        save_video();
        init_vga_mode13();
        load_dac();
        render(st);
        fb_to_vram();
        while (!quit) {
            unsigned k = read_key();
            State prev = st;
            st = step(st, (int32_t)k);
            if (g_exit) {
                restore_video();
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

