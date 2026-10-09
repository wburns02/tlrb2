/* CREATE: C port of tools/m4/create.py (CREATE A PLAYER, CREATE.EXE). Host build
 * with gcc for parity tests, DOS build with OpenWatcom (16-bit real mode, large
 * model). Reads the team V20 of the first league team picked, lets the player type
 * a new player into a roster slot, writes the roster and season records of that slot
 * in place, then sets CONTROL[1] = CONTROL[0] so TONY2.BAT restarts MAIN. Screen
 * output matches the Python reference pixel for pixel.
 * usage: CREATE [/KEYS:k,k,...] [/RAW:FILE] [LEAGUE_DIR [FONT_DIR [ANMS_DIR]]]
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
#include <dirent.h>
#define DIR_SEP '/'
#endif

#define FB_W   320
#define FB_H   200
#define FB_SIZE 64000

#define C_BLACK  0
#define C_WHITE  15
#define C_DRED   4
#define C_TITLE_RED 208
#define C_HEADER_GOLD 207
#define C_ROW_TAN 188
#define C_FRAME_TAN 193
#define C_BG_BROWN 215
#define C_GRID_GRAY 7

#define ROW_H 11
#define ROWS_PER_PAGE 12
#define CHAR_W 7
#define SLEN 64             /* cell / line text cap */

/* BIOS int 16h codes; ASCII keys are their char code */
#define KEY_ESC 27
#define KEY_ENTER 13
#define KEY_BACK 8
#define KEY_LEFT 0x4b00
#define KEY_RIGHT 0x4d00
#define KEY_PGUP 0x4900
#define KEY_PGDN 0x5100
#define KEY_UP 0x4800
#define KEY_DOWN 0x5000

#define S_TEAM 0
#define S_SLOT 1
#define S_EDIT 2
#define S_CONFIRM 3
#define S_DONE 4

/* V20 layout: 295 byte header, then 80 records of 143 bytes; record s is the roster
 * half of slot s, record s + 40 its season half */
#define RECORD_LEN 143
#define HEADER_LEN 295
#define ROSTER_SLOTS 40
#define PITCHER_SLOTS 16
#define IMAGE_LEN (HEADER_LEN + 80 * RECORD_LEN)
#define DEFAULT_YEAR_BYTE 123
#define SALARY_PITCHER 255
#define SALARY_BATTER 109

/* *.MAJ: AL stems at 0x21d, NL stems at 0x758c, 8 bytes per slot after 0x1d7 */
#define AL_BASE 0x21d
#define NL_BASE 0x758c
#define MAJ_STEM_OFF 0x1d7
#define MAJ_MIN_LEN (NL_BASE + MAJ_STEM_OFF + 8 * 15 + 8)
#define MAXV 64

#define LAST_MAX 11
#define FIRST_MAX 7
#define AGE_MIN 18
#define AGE_MAX 45
#define DEFAULT_AGE 22
#define DEFAULT_RATING 6
#define RATING_CAP 12
#define PIT_ENDURANCE_CAP 10
#define FACE_DEFAULT_N 30
#define FACE_TABLE_MAX 981
#define FACE_READ_MAX 982
#define PORTRAIT_W 48
#define PORTRAIT_H 56
#define FACE_X 244
#define FACE_Y 43

#ifdef __WATCOMC__
#define FARDATA __far
#else
#define FARDATA
#endif

#define DEF_LEAGUE "TEAMS\\CLASSIC"
#define DEF_LEAGUE_HOST "TEAMS/CLASSIC"
#define DEF_ANMS "ANMS"

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

/* the new player being typed (create.py form): names as typed, NUL ended */
typedef struct {
    char last[12];
    char first[8];
    int16_t pos, hands, age, face;
    int16_t r[6];
} Form;

/* the program state (create.py state dict; the image lives in g_image) */
typedef struct {
    int16_t screen, cursor, team, slot, msg;
    Form form;
} State;

/* one team of the league: lg 0..31, stem (NUL ended), display text */
typedef struct {
    int lg;
    char stem[9];
    char disp[SLEN];
} Team;

/* list screen: column table, row count, highlight flag and footer */
typedef struct {
    const char *header;
    int x, w, ralign;
} ColDef;

typedef struct {
    char title[SLEN];
    const ColDef *cols;
    int ncols;
    int nrows;
    int hl;
    const char *footer;
} ListView;

static Font *g_main, *g_bold;
static uint8_t FARDATA g_fb[FB_SIZE];
static uint8_t FARDATA g_pal[768];
static uint8_t FARDATA g_image[IMAGE_LEN];   /* team V20 image, in place saves */
static Team g_teams[32];
static int g_nteams;
static char g_lgdir[260];        /* LEAGUE_DIR, for the team V20 files */
static char g_anms[260];         /* ANMS_DIR, for PORTRAIT.ANM and FACEGRP.DAT */
static int g_face_n;             /* face table size (faces.py load_faces) */
static uint8_t g_face_grp[FACE_TABLE_MAX];
static uint8_t g_px[PORTRAIT_W * PORTRAIT_H];
static State g_state;
static int g_saved;

/* stock face groups (rookies.STOCK_FACE_GROUP) for faces 0..29 */
static const uint8_t STOCK_GRP[30] = {
    0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    1, 0, 1, 0, 1, 1, 1, 0, 0, 1, 0, 1, 0, 0 };

static const char *POS_LABELS[16] = {
    "P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "OF", "IF",
    "OI", "CO", "CI", "C3" };
/* hands index -> bats and throws letters (create.py HANDS) */
static const char HANDS_BATS[6] = { 'R', 'L', 'S', 'R', 'L', 'S' };
static const char HANDS_THROWS[6] = { 'R', 'L', 'R', 'L', 'R', 'L' };

/* edit rows: field ids, then the row labels (batter 13 rows, pitcher 10 rows) */
enum { FLD_LAST, FLD_FIRST, FLD_POS, FLD_HANDS, FLD_AGE, FLD_R0, FLD_R1, FLD_R2,
       FLD_R3, FLD_R4, FLD_R5, FLD_FACE, FLD_SAVE };
static const uint8_t BAT_FIELDS[13] = { FLD_LAST, FLD_FIRST, FLD_POS, FLD_HANDS,
    FLD_AGE, FLD_R0, FLD_R1, FLD_R2, FLD_R3, FLD_R4, FLD_R5, FLD_FACE, FLD_SAVE };
static const uint8_t PIT_FIELDS[10] = { FLD_LAST, FLD_FIRST, FLD_POS, FLD_HANDS,
    FLD_AGE, FLD_R0, FLD_R1, FLD_R2, FLD_FACE, FLD_SAVE };
static const char *BAT_LABEL[13] = { "LAST NAME", "FIRST NAME", "POSITION", "HANDS",
    "AGE", "POWER", "BUNT", "HIT AND RUN", "SPEED", "RANGE", "ARM", "FACE",
    "SAVE PLAYER" };
static const char *PIT_LABEL[10] = { "LAST NAME", "FIRST NAME", "POSITION", "HANDS",
    "AGE", "CONTROL", "VELOCITY", "ENDURANCE", "FACE", "SAVE PLAYER" };

static const char *FOOT_TEAM = "UP DOWN   ENTER PICK   ESC EXIT";
static const char *FOOT_SLOT = "UP DOWN   ENTER PICK   ESC TEAMS";
static const char *FOOT_CONFIRM = "ENTER REPLACE   ESC BACK";
static const char *FOOT_DONE = "ENTER CREATE ANOTHER   ESC EXIT";
static const char *FOOT_NAME = "TYPE NAME   UP DOWN   ESC SLOTS";
static const char *FOOT_SAVE = "ENTER SAVE   UP DOWN   ESC SLOTS";
static const char *FOOT_FIELD = "UP DOWN   LEFT RIGHT CHANGE   ESC SLOTS";
static const char *MSG_NAME = "TYPE A LAST NAME FIRST";

/* season stat bytes zeroed in the season half (team_fill._SEASON_STAT_OFFSETS) */
static const uint8_t SEASON_OFFS[] = {
    23, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 49, 50, 51, 52, 53, 54, 55, 56,
    57, 58, 101, 102, 111, 112, 121, 122, 125, 126 };

#define CX(pos) (10 + CHAR_W * (pos))
static const ColDef COLS_TEAM[] = {
    { "TEAM", CX(0), 20, 0 }, { "LEAGUE", CX(30), 12, 0 } };
static const ColDef COLS_SLOT[] = {
    { "SLOT", CX(0), 4, 0 }, { "PLAYER", CX(5), 20, 0 }, { "POS", CX(26), 4, 0 },
    { "AGE", CX(31), 4, 1 } };
static const ColDef COLS_ONE[] = {
    { " ", CX(0), 42, 0 } };

#define NCOLS(a) ((int)(sizeof(a) / sizeof((a)[0])))

int main(int argc, char **argv);
static void render(const State *st);

/* ---------------- helpers ---------------- */

/* create.py uses floor division for the title centring; this is exact for any width */
static int floor_div2(int a)
{
    if (a >= 0)
        return a / 2;
    return -((-a + 1) / 2);
}

/* path_join: a + DIR_SEP + b (no separator when a already ends in one) */
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

/* char-string wrappers over the byte versions */
static void dtext(const Font *ft, int x, int y, const char *s, int color)
{
    draw_text(g_fb, ft, x, y, (const uint8_t *)s, color);
}

static int twidth(const Font *ft, const char *s)
{
    return text_width(ft, (const uint8_t *)s);
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

/* ---------------- strings / names ---------------- */

/* ASCII upper case of one byte (a-z only, like DOS) */
static uint8_t ascii_up(uint8_t c)
{
    return (uint8_t)((c >= 'a' && c <= 'z') ? c - 32 : c);
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

/* ---------------- league files ---------------- */

/* LEAGUE_DIR\<STEM>.V20 (STEM: n bytes, upper-cased) opened with mode: NULL when
 * the stem is not a 1..8 byte leaf (no NUL, slash, backslash or colon), the path is
 * too long or the file cannot be opened */
static FILE *v20_fopen(const uint8_t *s, int n, const char *mode)
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
    return fopen(path, mode);
}

/* team_name: V20 header name (bytes 0..13, NUL ended, trailing spaces cut) of the
 * team file for the stem s (n bytes); "" when there is no file or the name blank */
static void team_name(const uint8_t *s, int n, char *dst)
{
    uint8_t raw[14];
    FILE *f;
    dst[0] = 0;
    f = v20_fopen(s, n, "rb");
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

/* upper-cased copy of a file name (8.3 listing) */
static void upname(char *dst, const char *src)
{
    int i;
    for (i = 0; src[i] && i < 15; i++) {
        char c = src[i];
        dst[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : c;
    }
    dst[i] = 0;
}

static int cmpname(const void *a, const void *b)
{
    return strcmp((const char *)a, (const char *)b);
}

/* --- *.MAJ listing: upper-cased 8.3 names, sorted (matches Python sorted() on
 *     these names); copied from histwr.c --- */
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

/* 1 when the stem names a team file (v20_fopen opens it) */
static int team_file(const uint8_t *s, int n)
{
    FILE *f = v20_fopen(s, n, "rb");
    if (!f)
        return 0;
    fclose(f);
    return 1;
}

/* teams(league_dir): the first sorted *.MAJ; a file shorter than MAJ_MIN_LEN has no
 * teams. A stem is the 8 bytes at the team's name slot cut at the first NUL; an
 * empty stem or one without a team file is skipped. Teams come lg 0..31 ascending. */
static void load_teams(const char *league)
{
    static char names[MAXV][16];
    char path[300];
    FILE *f;
    int n, lg;
    g_nteams = 0;
    n = scan_dir(league, ".MAJ", names);
    if (n < 1)
        return;
    path_join(path, league, names[0]);
    f = fopen(path, "rb");
    if (!f)
        return;
    if (fseek(f, 0L, SEEK_END) != 0 || ftell(f) < (long)MAJ_MIN_LEN) {
        fclose(f);
        return;
    }
    for (lg = 0; lg < 32; lg++) {
        uint8_t stem[8];
        int base = lg < 16 ? AL_BASE : NL_BASE;
        int slot = lg < 16 ? lg : lg - 16;
        int off = base + MAJ_STEM_OFF + 8 * slot;
        int len = 0;
        memset(stem, 0, sizeof stem);
        if (fseek(f, (long)off, SEEK_SET) != 0)
            break;
        (void)fread(stem, 1, sizeof stem, f);
        while (len < 8 && stem[len])
            len++;
        if (len == 0 || !team_file(stem, len))
            continue;
        g_teams[g_nteams].lg = lg;
        memcpy(g_teams[g_nteams].stem, stem, (size_t)len);
        g_teams[g_nteams].stem[len] = 0;
        team_disp(stem, len, g_teams[g_nteams].disp);
        g_nteams++;
    }
    fclose(f);
}

/* the team image: header plus 80 records, zero padded when the file is shorter or
 * missing */
static void read_image(int team)
{
    FILE *f;
    const char *stem = g_teams[team].stem;
    memset(g_image, 0, IMAGE_LEN);
    f = v20_fopen((const uint8_t *)stem, (int)strlen(stem), "rb");
    if (!f)
        return;
    (void)fread(g_image, 1, IMAGE_LEN, f);
    fclose(f);
}

/* ---------------- faces and portraits ---------------- */

/* load_faces(anms_dir): PORTRAIT.ANM first u16 c and FACEGRP.DAT of length L, with
 * 30 <= L <= 981 and min(L, c) >= 30: n = min(L, c), group = first n bytes & 1;
 * otherwise the default 30 faces with the stock groups */
static void load_faces(const char *anms)
{
    char path[300];
    FILE *f;
    uint8_t head[2];
    uint8_t data[FACE_READ_MAX];
    size_t length, c, n, i;
    g_face_n = FACE_DEFAULT_N;
    memcpy(g_face_grp, STOCK_GRP, sizeof STOCK_GRP);
    path_join(path, anms, "PORTRAIT.ANM");
    f = fopen(path, "rb");
    if (!f)
        return;
    if (fread(head, 1, 2, f) != 2) {
        fclose(f);
        return;
    }
    fclose(f);
    path_join(path, anms, "FACEGRP.DAT");
    f = fopen(path, "rb");
    if (!f)
        return;
    length = fread(data, 1, FACE_READ_MAX, f);
    fclose(f);
    c = (size_t)head[0] | ((size_t)head[1] << 8);
    if (length < FACE_DEFAULT_N || length > FACE_TABLE_MAX)
        return;
    n = length < c ? length : c;
    if (n < FACE_DEFAULT_N)
        return;
    g_face_n = (int)n;
    for (i = 0; i < n; i++)
        g_face_grp[i] = (uint8_t)(data[i] & 1);
}

/* portrait(anms_dir, k) into g_px: 1 when frame k is usable (stored, 48 x 56, fits
 * the file), else 0. Frames before k are skipped by their 12 byte headers. */
static int portrait_load(int k)
{
    char path[300];
    FILE *f;
    uint8_t hdr[12];
    unsigned long p = 2, size;
    int i, count;
    path_join(path, g_anms, "PORTRAIT.ANM");
    f = fopen(path, "rb");
    if (!f)
        return 0;
    if (fseek(f, 0L, SEEK_END) != 0 || ftell(f) < 0) {
        fclose(f);
        return 0;
    }
    size = (unsigned long)ftell(f);
    if (fseek(f, 0L, SEEK_SET) != 0 || fread(hdr, 1, 2, f) != 2) {
        fclose(f);
        return 0;
    }
    count = hdr[0] | (hdr[1] << 8);
    if (k >= count) {
        fclose(f);
        return 0;
    }
    for (i = 0; i <= k; i++) {
        unsigned long w, h, clen, fr;
        if (fseek(f, (long)p, SEEK_SET) != 0 || fread(hdr, 1, 12, f) != 12) {
            fclose(f);
            return 0;
        }
        h = (unsigned long)(hdr[2] | (hdr[3] << 8));
        w = (unsigned long)(hdr[4] | (hdr[5] << 8));
        clen = (unsigned long)(hdr[10] | (hdr[11] << 8));
        if (i < k) {
            fr = clen == 0 ? h * w : clen;
            if (fr > size) {
                fclose(f);
                return 0;
            }
            p += 12 + fr;
            continue;
        }
        if (clen != 0 || w != PORTRAIT_W || h != PORTRAIT_H
                || p + 12 + h * w > size) {
            fclose(f);
            return 0;
        }
        if (fseek(f, (long)(p + 12), SEEK_SET) != 0
                || fread(g_px, 1, (size_t)(h * w), f) != (size_t)(h * w)) {
            fclose(f);
            return 0;
        }
        fclose(f);
        return 1;
    }
    fclose(f);
    return 0;
}

/* ---------------- record build and save ---------------- */

/* record r of the image (roster half for r < 40, season half for r >= 40) */
static uint8_t *recp(int r)
{
    return &g_image[HEADER_LEN + RECORD_LEN * r];
}

/* year_byte: byte 21 of the first named record among records 0..79, else 123 */
static uint8_t year_of_image(void)
{
    int r;
    for (r = 0; r < 2 * ROSTER_SLOTS; r++) {
        const uint8_t *rec = recp(r);
        if (rec[0])
            return rec[21];
    }
    return DEFAULT_YEAR_BYTE;
}

static void set_lo(uint8_t *b, int off, int v)
{
    b[off] = (uint8_t)((b[off] & 0xf0) | (v & 0x0f));
}

static void set_hi(uint8_t *b, int off, int v)
{
    b[off] = (uint8_t)((b[off] & 0x0f) | ((v & 0x0f) << 4));
}

/* build_record: the 143 byte roster record of the new player (create.py
 * build_record with the rookies.RookieGen draws replaced by the form values) */
static void build_record(const Form *f, int pitcher, uint8_t year, uint8_t *rec)
{
    int face = f->face, hands = f->hands, bats_code, left, right, sal;
    char bats = HANDS_BATS[hands], throws = HANDS_THROWS[hands];
    size_t ll = strlen(f->last), fl = strlen(f->first);
    memset(rec, 0, RECORD_LEN);
    memcpy(rec + 0, f->last, ll);
    memcpy(rec + 12, f->first, fl);
    rec[20] = (uint8_t)f->age;
    rec[21] = year;
    bats_code = bats == 'R' ? 1 : (bats == 'S' ? 2 : 0);
    rec[29] = (uint8_t)((throws == 'R' ? 8 : 0) | (bats_code << 1)
                        | (g_face_grp[face] & 1));
    rec[31] = (uint8_t)(pitcher ? 0 : (f->pos & 15));
    rec[27] = (uint8_t)(face & 0xff);
    rec[28] = (uint8_t)((face >> 8) & 0xff);
    rec[30] = 0x02;                             /* exper 0, consist 2 */
    /* stat constants (rookies.RookieGen._write_stat_constants) */
    if (pitcher) {
        rec[101] = 200;
        rec[102] = 0;
        rec[135] |= 0x04;
        rec[136] = 0x77;
        rec[137] = 0x77;
        rec[138] = 0x77;
        rec[139] = 0x77;
        rec[140] = 7;
        rec[74] = 0x11;
        rec[75] |= 0x01;
        rec[29] |= 0x70;
        rec[94] = 0x77;
    } else {
        rec[75] |= 0x70;
        rec[76] = 0x78;
        rec[134] = 0x31;
        rec[135] |= 0x10;
        bats_code = (rec[29] >> 1) & 3;
        if (bats_code == 2) {
            left = 20;
            right = 20;
        } else if (bats_code == 0) {
            left = 34;
            right = 6;
        } else {
            left = 4;
            right = 36;
        }
        rec[37] = (uint8_t)(left & 0xff);
        rec[38] = (uint8_t)((left >> 8) & 0xff);
        rec[39] = (uint8_t)(right & 0xff);
        rec[40] = (uint8_t)((right >> 8) & 0xff);
    }
    /* ratings: batter power 74 lo, bunt 74 hi, hit_run 75 lo, speed 29 hi, range 94
     * hi, arm 94 lo; pitcher control 134 lo, velocity 134 hi, endurance 135 hi */
    if (pitcher) {
        set_lo(rec, 134, f->r[0]);
        set_hi(rec, 134, f->r[1]);
        set_hi(rec, 135, f->r[2]);
    } else {
        set_lo(rec, 74, f->r[0]);
        set_hi(rec, 74, f->r[1]);
        set_lo(rec, 75, f->r[2]);
        set_hi(rec, 29, f->r[3]);
        set_hi(rec, 94, f->r[4]);
        set_lo(rec, 94, f->r[5]);
    }
    sal = pitcher ? SALARY_PITCHER : SALARY_BATTER;
    rec[25] = (uint8_t)(sal & 0xff);
    rec[26] = (uint8_t)((sal >> 8) & 0xff);
}

/* save: the roster record of the slot and its season half go into the team V20 in
 * place, and into the image; write errors are ignored */
static void save_form(const State *st)
{
    uint8_t rec[RECORD_LEN], srec[RECORD_LEN];
    int slot = st->slot, pitcher = slot < PITCHER_SLOTS, i;
    long off_r = HEADER_LEN + RECORD_LEN * slot;
    long off_s = HEADER_LEN + RECORD_LEN * (slot + ROSTER_SLOTS);
    const char *stem = g_teams[st->team].stem;
    FILE *f;
    build_record(&st->form, pitcher, year_of_image(), rec);
    memcpy(srec, rec, RECORD_LEN);
    for (i = 0; i < (int)sizeof SEASON_OFFS; i++)
        srec[SEASON_OFFS[i]] = 0;
    f = v20_fopen((const uint8_t *)stem, (int)strlen(stem), "r+b");
    if (f) {
        (void)fseek(f, off_r, SEEK_SET);
        (void)fwrite(rec, 1, RECORD_LEN, f);
        (void)fseek(f, off_s, SEEK_SET);
        (void)fwrite(srec, 1, RECORD_LEN, f);
        fclose(f);
    }
    memcpy(recp(slot), rec, RECORD_LEN);
    memcpy(recp(slot + ROSTER_SLOTS), srec, RECORD_LEN);
}

/* CONTROL[1] = CONTROL[0] in place, when the file has at least 2 bytes */
static void control_return(void)
{
    FILE *f = fopen("CONTROL", "r+b");
    uint8_t d[2];
    if (!f)
        return;
    if (fread(d, 1, 2, f) == 2) {
        (void)fseek(f, 1L, SEEK_SET);
        (void)fputc(d[0], f);
    }
    fclose(f);
}

/* ---------------- state machine ---------------- */

/* blank_form: no names, position 1, age 22, every rating 6, hands 0, face 0 */
static void blank_form(Form *f)
{
    int i;
    memset(f, 0, sizeof *f);
    f->pos = 1;
    f->age = DEFAULT_AGE;
    for (i = 0; i < 6; i++)
        f->r[i] = DEFAULT_RATING;
}

/* default_form(image, slot, n): batter position from the named occupant (1..9, else
 * 1), pitcher position 0 with ratings 6, 6, 5; face 30 when there are more than 30
 * faces, else 0 */
static void default_form(Form *f, int slot)
{
    const uint8_t *rec = recp(slot);
    blank_form(f);
    if (slot < PITCHER_SLOTS) {
        f->pos = 0;
        f->r[2] = 5;
    } else if (rec[0] && (rec[31] & 15) >= 1 && (rec[31] & 15) <= 9) {
        f->pos = rec[31] & 15;
    }
    f->face = (int16_t)(g_face_n > FACE_DEFAULT_N ? FACE_DEFAULT_N : 0);
}

static void make_slot_label(int s, char *dst)
{
    if (s < PITCHER_SLOTS)
        sprintf(dst, "P%d", s + 1);
    else
        sprintf(dst, "B%d", s - PITCHER_SLOTS + 1);
}

static int list_key(int cur, int32_t key, int n)
{
    if (n == 0)
        return 0;
    if (key == KEY_UP && cur > 0)
        return cur - 1;
    if (key == KEY_DOWN && cur < n - 1)
        return cur + 1;
    if (key == KEY_PGDN)
        return cur + ROWS_PER_PAGE < n - 1 ? cur + ROWS_PER_PAGE : n - 1;
    if (key == KEY_PGUP)
        return cur - ROWS_PER_PAGE > 0 ? cur - ROWS_PER_PAGE : 0;
    return cur;
}

static int edit_rows(int pitcher)
{
    return pitcher ? 10 : 13;
}

static int edit_field(int pitcher, int r)
{
    return pitcher ? PIT_FIELDS[r] : BAT_FIELDS[r];
}

static const char *edit_label(int pitcher, int r)
{
    return pitcher ? PIT_LABEL[r] : BAT_LABEL[r];
}

/* name row key: ASCII letter, space (not first), '.', apostrophe or '-' */
static int name_ok(const char *name, int mx, int32_t key)
{
    size_t len = strlen(name);
    if ((int)len >= mx || key <= 0 || key >= 128)
        return 0;
    if (key == ' ' && len == 0)
        return 0;
    return (key >= 'a' && key <= 'z') || (key >= 'A' && key <= 'Z') || key == ' '
           || key == '.' || key == '\'' || key == '-';
}

static void finish_save(State *st)
{
    save_form(st);
    st->screen = S_DONE;
    st->cursor = 0;
    g_saved = 1;
}

static void adjust(State *st, int fld, int d)
{
    Form *f = &st->form;
    int pitcher = st->slot < PITCHER_SLOTS;
    int i, cap, v;
    if (fld == FLD_POS) {
        if (!pitcher)
            f->pos = (int16_t)((f->pos - 1 + d + 9) % 9 + 1);
    } else if (fld == FLD_HANDS) {
        f->hands = (int16_t)((f->hands + d + 6) % 6);
    } else if (fld == FLD_AGE) {
        v = f->age + d;
        f->age = (int16_t)(v < AGE_MIN ? AGE_MIN : (v > AGE_MAX ? AGE_MAX : v));
    } else if (fld == FLD_FACE) {
        f->face = (int16_t)((f->face + d + g_face_n) % g_face_n);
    } else if (fld >= FLD_R0 && fld <= FLD_R5) {
        i = fld - FLD_R0;
        cap = (pitcher && i == 2) ? PIT_ENDURANCE_CAP : RATING_CAP;
        v = f->r[i] + d;
        f->r[i] = (int16_t)(v < 1 ? 1 : (v > cap ? cap : v));
    }
}

static int step_team(State *st, int32_t key)
{
    if (key == KEY_ESC)
        return 1;
    if (key == KEY_ENTER && g_nteams) {
        st->team = st->cursor;
        read_image(st->team);
        st->screen = S_SLOT;
        st->cursor = 0;
        return 0;
    }
    st->cursor = (int16_t)list_key(st->cursor, key, g_nteams);
    return 0;
}

static int step_slot(State *st, int32_t key)
{
    if (key == KEY_ESC) {
        st->screen = S_TEAM;
        st->cursor = st->team;
        return 0;
    }
    if (key == KEY_ENTER) {
        st->slot = st->cursor;
        default_form(&st->form, st->slot);
        st->screen = S_EDIT;
        st->cursor = 0;
        return 0;
    }
    st->cursor = (int16_t)list_key(st->cursor, key, ROSTER_SLOTS);
    return 0;
}

static int step_edit(State *st, int32_t key)
{
    int pitcher = st->slot < PITCHER_SLOTS;
    int fld = edit_field(pitcher, st->cursor);
    Form *f = &st->form;
    if (key == KEY_ESC) {
        st->screen = S_SLOT;
        st->cursor = st->slot;
        return 0;
    }
    if (key == KEY_UP || key == KEY_DOWN) {
        st->cursor = (int16_t)list_key(st->cursor, key, edit_rows(pitcher));
        return 0;
    }
    if (key == KEY_ENTER) {
        if (fld == FLD_SAVE) {
            if (f->last[0] == 0)
                st->msg = 1;
            else if (recp(st->slot)[0]) {
                st->screen = S_CONFIRM;
                st->cursor = 0;
            } else
                finish_save(st);
        } else {
            st->cursor++;
        }
        return 0;
    }
    if (fld == FLD_LAST || fld == FLD_FIRST) {
        int mx = fld == FLD_LAST ? LAST_MAX : FIRST_MAX;
        char *name = fld == FLD_LAST ? f->last : f->first;
        size_t len = strlen(name);
        if (key == KEY_BACK) {
            if (len)
                name[len - 1] = 0;
        } else if (name_ok(name, mx, key)) {
            name[len] = (char)ascii_up((uint8_t)key);   /* stock names are upper case */
            name[len + 1] = 0;
        }
        return 0;
    }
    if ((key == KEY_LEFT || key == KEY_RIGHT) && fld != FLD_SAVE)
        adjust(st, fld, key == KEY_LEFT ? -1 : 1);
    return 0;
}

static int step_confirm(State *st, int32_t key)
{
    if (key == KEY_ESC) {
        st->screen = S_EDIT;
        st->cursor = (int16_t)(edit_rows(st->slot < PITCHER_SLOTS) - 1);
    } else if (key == KEY_ENTER) {
        finish_save(st);
    }
    return 0;
}

static int step_done(State *st, int32_t key)
{
    if (key == KEY_ESC)
        return 1;
    if (key == KEY_ENTER) {
        st->screen = S_TEAM;
        st->cursor = st->team;
    }
    return 0;
}

/* (exit flag). Every key first clears msg. ESC on TEAM and on DONE exits; every
 * other ESC goes back one screen. */
static int step(State *st, int32_t key)
{
    st->msg = 0;
    switch (st->screen) {
    case S_TEAM:
        return step_team(st, key);
    case S_SLOT:
        return step_slot(st, key);
    case S_EDIT:
        return step_edit(st, key);
    case S_CONFIRM:
        return step_confirm(st, key);
    default:
        return step_done(st, key);
    }
}

/* ---------------- rendering ---------------- */

/* list_view: title, columns, row count, highlight and footer of a list screen */
static void list_view(const State *st, ListView *lv)
{
    lv->hl = 1;
    switch (st->screen) {
    case S_TEAM:
        strcpy(lv->title, "CREATE A PLAYER");
        lv->cols = COLS_TEAM;
        lv->ncols = NCOLS(COLS_TEAM);
        lv->footer = FOOT_TEAM;
        lv->nrows = g_nteams;
        if (g_nteams == 0) {
            lv->nrows = 1;
            lv->hl = 0;
        }
        break;
    case S_SLOT:
        strcpy(lv->title, "PICK A SLOT: ");
        strcat(lv->title, g_teams[st->team].disp);
        lv->cols = COLS_SLOT;
        lv->ncols = NCOLS(COLS_SLOT);
        lv->footer = FOOT_SLOT;
        lv->nrows = ROSTER_SLOTS;
        break;
    case S_CONFIRM:
        strcpy(lv->title, "REPLACE PLAYER");
        lv->cols = COLS_ONE;
        lv->ncols = NCOLS(COLS_ONE);
        lv->footer = FOOT_CONFIRM;
        lv->nrows = 3;
        lv->hl = 0;
        break;
    default:
        strcpy(lv->title, "PLAYER SAVED");
        lv->cols = COLS_ONE;
        lv->ncols = NCOLS(COLS_ONE);
        lv->footer = FOOT_DONE;
        lv->nrows = 3;
        lv->hl = 0;
        break;
    }
}

/* the cells of list row i (create.py _list_view rows) */
static void list_cells(const State *st, int i, char cells[4][SLEN])
{
    int k;
    for (k = 0; k < 4; k++)
        cells[k][0] = 0;
    switch (st->screen) {
    case S_TEAM:
        if (g_nteams == 0) {
            strcpy(cells[0], "NO TEAMS FOUND");
            break;
        }
        strcpy(cells[0], g_teams[i].disp);
        strcpy(cells[1], g_teams[i].lg < 16 ? "AMERICAN" : "NATIONAL");
        break;
    case S_SLOT: {
        const uint8_t *rec = recp(i);
        make_slot_label(i, cells[0]);
        if (rec[0]) {
            name_display(rec, 20, cells[1]);
            strcpy(cells[2], POS_LABELS[rec[31] & 15]);
            sprintf(cells[3], "%d", rec[20]);
        } else {
            strcpy(cells[1], "(EMPTY)");
        }
        break;
    }
    case S_CONFIRM:
        if (i == 0) {
            char nm[SLEN];
            name_display(recp(st->slot), 18, nm);
            strcpy(cells[0], "THIS REPLACES ");
            strcat(cells[0], nm);
        } else if (i == 1) {
            char lab[16];
            make_slot_label(st->slot, lab);
            strcpy(cells[0], "IN SLOT ");
            strcat(cells[0], lab);
            strcat(cells[0], " OF ");
            strcat(cells[0], g_teams[st->team].disp);
        } else {
            strcpy(cells[0], "THE OLD PLAYER LEAVES THE LEAGUE.");
        }
        break;
    default:
        if (i == 0) {
            strcpy(cells[0], "SAVED: ");
            if (st->form.first[0]) {
                strcat(cells[0], st->form.first);
                strcat(cells[0], " ");
            }
            strcat(cells[0], st->form.last);
        } else if (i == 1) {
            strcpy(cells[0], "TEAM: ");
            strcat(cells[0], g_teams[st->team].disp);
        } else {
            char lab[16];
            make_slot_label(st->slot, lab);
            strcpy(cells[0], "SLOT: ");
            strcat(cells[0], lab);
        }
        break;
    }
}

static void draw_title(const char *t)
{
    int tx = 8 + floor_div2(304 - twidth(g_bold, t));
    dtext(g_bold, tx + 1, 11, t, C_BLACK);
    dtext(g_bold, tx, 10, t, C_WHITE);
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

static void draw_list(const State *st, const ListView *lv)
{
    int ci, r, page;
    rect_fb(8, 24, 311, 33, C_HEADER_GOLD);
    for (ci = 0; ci < lv->ncols; ci++) {
        const ColDef *cd = &lv->cols[ci];
        char h[16];
        int hl = (int)strlen(cd->header);
        if (hl > cd->w)
            hl = cd->w;
        memcpy(h, cd->header, (size_t)hl);
        h[hl] = 0;
        if (cd->ralign)
            dtext(g_main, cd->x + cd->w * CHAR_W - twidth(g_main, h), 26, h, C_BLACK);
        else
            dtext(g_main, cd->x, 26, h, C_BLACK);
    }
    page = st->cursor / ROWS_PER_PAGE;
    for (r = 0; r < ROWS_PER_PAGE; r++) {
        int i = page * ROWS_PER_PAGE + r, y0, cur, color;
        char cells[4][SLEN];
        if (i >= lv->nrows)
            break;
        y0 = 35 + r * ROW_H;
        cur = lv->hl && i == st->cursor;
        color = cur ? C_WHITE : C_BLACK;
        list_cells(st, i, cells);
        rect_fb(8, y0, 311, y0 + 9, cur ? C_TITLE_RED : C_ROW_TAN);
        for (ci = 0; ci < lv->ncols; ci++) {
            const ColDef *cd = &lv->cols[ci];
            char s[SLEN];
            int cl = (int)strlen(cells[ci]);
            if (cl > cd->w)
                cl = cd->w;
            memcpy(s, cells[ci], (size_t)cl);
            s[cl] = 0;
            if (cd->ralign)
                dtext(g_main, cd->x + cd->w * CHAR_W - twidth(g_main, s), y0 + 2,
                      s, color);
            else
                dtext(g_main, cd->x, y0 + 2, s, color);
        }
        rect_fb(8, y0 + 10, 311, y0 + 10, C_GRID_GRAY);
    }
    dtext(g_main, 10, 185, lv->footer, C_WHITE);
}

/* the value text of an edit field (create.py _edit_value) */
static void edit_value(const State *st, int fld, int cur, char *dst)
{
    const Form *f = &st->form;
    int i = fld - FLD_R0;
    if (fld == FLD_LAST || fld == FLD_FIRST) {
        const char *s = fld == FLD_LAST ? f->last : f->first;
        int mx = fld == FLD_LAST ? LAST_MAX : FIRST_MAX;
        strcpy(dst, s);
        if (cur && (int)strlen(s) < mx)
            strcat(dst, "_");
    } else if (fld == FLD_POS) {
        strcpy(dst, POS_LABELS[f->pos]);
    } else if (fld == FLD_HANDS) {
        sprintf(dst, "BATS %c THROWS %c", HANDS_BATS[f->hands], HANDS_THROWS[f->hands]);
    } else if (fld == FLD_AGE) {
        sprintf(dst, "%d", f->age);
    } else if (fld == FLD_FACE) {
        sprintf(dst, "%d OF %d", f->face + 1, g_face_n);
    } else if (fld == FLD_SAVE) {
        dst[0] = 0;
    } else {
        sprintf(dst, "%d", f->r[i]);
    }
}

static void draw_edit(const State *st)
{
    int pitcher = st->slot < PITCHER_SLOTS, nrows = edit_rows(pitcher), r, fld;
    char title[SLEN], val[SLEN];
    draw_panel();
    strcpy(title, "NEW PLAYER: ");
    strcat(title, g_teams[st->team].disp);
    draw_title(title);
    rect_fb(8, 24, 311, 33, C_HEADER_GOLD);
    dtext(g_main, CX(0), 26, "FIELD", C_BLACK);
    dtext(g_main, CX(13), 26, "VALUE", C_BLACK);
    dtext(g_main, 236, 26, "FACE", C_BLACK);
    for (r = 0; r < nrows; r++) {
        int y0 = 35 + r * 10, cur = r == st->cursor, color = cur ? C_WHITE : C_BLACK;
        rect_fb(8, y0, 219, y0 + 8, cur ? C_TITLE_RED : C_ROW_TAN);
        dtext(g_main, 10, y0 + 1, edit_label(pitcher, r), color);
        edit_value(st, edit_field(pitcher, r), cur, val);
        dtext(g_main, CX(13), y0 + 1, val, color);
    }
    rect_fb(226, 35, 309, 106, C_BLACK);
    if (portrait_load(st->form.face)) {
        int y;
        for (y = 0; y < PORTRAIT_H; y++) {
            uint8_t *row = g_fb + (FACE_Y + y) * FB_W + FACE_X;
            memcpy(row, g_px + y * PORTRAIT_W, PORTRAIT_W);
        }
    } else {
        rect_fb(FACE_X, FACE_Y, FACE_X + PORTRAIT_W - 1, FACE_Y + PORTRAIT_H - 1,
                C_GRID_GRAY);
    }
    if (st->msg == 1)
        dtext(g_main, 10, 172, MSG_NAME, C_DRED);
    fld = edit_field(pitcher, st->cursor);
    if (fld == FLD_LAST || fld == FLD_FIRST)
        dtext(g_main, 10, 185, FOOT_NAME, C_WHITE);
    else if (fld == FLD_SAVE)
        dtext(g_main, 10, 185, FOOT_SAVE, C_WHITE);
    else
        dtext(g_main, 10, 185, FOOT_FIELD, C_WHITE);
}

/* render into g_fb (create.py render) */
static void render(const State *st)
{
    ListView lv;
    if (st->screen == S_EDIT) {
        draw_edit(st);
        return;
    }
    list_view(st, &lv);
    draw_panel();
    draw_title(lv.title);
    draw_list(st, &lv);
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
            (void)step(&g_state, parse_key(tok));
        if (s[0] == ',')
            s++;
    }
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
    fprintf(stderr, "usage: CREATE [/KEYS:k,k,...] [/RAW:FILE] "
            "[LEAGUE_DIR [FONT_DIR [ANMS_DIR]]]\n");
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

static void start_state(void)
{
    memset(&g_state, 0, sizeof g_state);
    g_state.screen = S_TEAM;
    blank_form(&g_state.form);
}

int main(int argc, char **argv)
{
    const char *league = (DIR_SEP == '\\') ? DEF_LEAGUE : DEF_LEAGUE_HOST;
    const char *anms = DEF_ANMS;
    const char *font_dir = NULL;
    const uint8_t *keys = NULL, *raw_path = NULL;
    int have_fonts, raw_mode = 0, i, npos = 0;

#ifdef __WATCOMC__
    _harderr(_hard_err_handler);
#endif

    for (i = 1; i < argc; i++) {
        const uint8_t *v;
        if ((v = arg_switch((const uint8_t *)argv[i], "keys")) != NULL) {
            keys = v;
        } else if ((v = arg_switch((const uint8_t *)argv[i], "raw")) != NULL) {
            raw_path = v;
            raw_mode = 1;
        } else if (argv[i][0] == '/' && !(DIR_SEP == '/' && strchr(argv[i] + 1, '/')
                                          != NULL)) {
            return usage();
        } else if (npos == 0) {
            league = argv[i];
            npos++;
        } else if (npos == 1) {
            font_dir = argv[i];
            npos++;
        } else if (npos == 2) {
            anms = argv[i];
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
        fprintf(stderr, "CREATE: FONTS NOT FOUND\n");
        return 2;
    }
    if (strlen(league) >= sizeof g_lgdir || strlen(anms) >= sizeof g_anms)
        return 2;
    strcpy(g_lgdir, league);
    strcpy(g_anms, anms);
    load_teams(league);
    load_faces(anms);
    start_state();
    g_saved = 0;
    if (keys != NULL)
        parse_keys(keys);

    if (raw_mode) {
        /* /RAW: after the keys, render once and write the 64000 B framebuffer;
         * never touch video, keyboard or palette in this mode */
        FILE *f;
        render(&g_state);
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
        control_return();
        return 0;
    }
#ifdef __WATCOMC__
    {
        int quit = 0;
        save_video();
        init_vga_mode13();
        load_dac();
        render(&g_state);
        fb_to_vram();
        while (!quit) {
            unsigned k = read_key();
            State prev = g_state;
            int exit_flag;
            g_saved = 0;
            exit_flag = step(&g_state, (int32_t)k);
            if (exit_flag) {
                restore_video();
                control_return();
                quit = 1;
            } else if (memcmp(&prev, &g_state, sizeof g_state) != 0 || g_saved) {
                /* render only after a key changed the state or a save */
                render(&g_state);
                fb_to_vram();
            }
        }
        return 0;
    }
#endif
}
