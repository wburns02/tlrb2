/* DYNVIEW: C port of tools/m4/dynview.py (T5a reference renderer). Host build
 * with gcc for parity tests, DOS build with OpenWatcom (16-bit real mode).
 * Streams HISTORY.DAT (one 160 B player entry at a time) and keeps sorted
 * top-LIST_MAX list buffers; screen output matches the Python reference pixel
 * for pixel.
 * usage: DYNVIEW [/REVIEW] [/OFFSEASON] [/TITLE] [/MENU] [/KEYS:k,k,...] [/RAW:FILE]
 *                [/ANMS:DIR] [/GAME:DIR] [LEAGUE_DIR [FONT_DIR]]
 * LEAGUE_DIR defaults to the current league's dir (league.h, C16.1; TEAMS\CLASSIC without SYSTEM).
 * /KEYS tokens: a key code, Lx.y a left click at (x, y), R a right click (ESC)
 * (precedence /OFFSEASON, /REVIEW, /TITLE, /MENU; /MENU opens the item CONTROL holds
 * in the current directory and then sets CONTROL[1] = CONTROL[0])
 * exit 0 ok, 2 on bad usage, font failure or /RAW write failure.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* teamids.h (TEAMID.DAT, C12.3) and realign.h (the playoff format apply, C12.4 to C12.6).
 * dynview uses some of their helpers only (the host parity harness uses the rest), so the
 * unused-function warning is off for this include under GCC */
#ifdef __GNUC__
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#endif
#include "../realign.h"
#include "../league.h"
#ifdef __GNUC__
#pragma GCC diagnostic pop
#endif

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
#define KEY_HOME 0x4700
#define KEY_END 0x4f00

#define SCREEN_MENU 0
#define SCREEN_HISTORY 1
#define SCREEN_HOF 2
#define SCREEN_LEADERS 3
#define SCREEN_MILESTONES 4
#define SCREEN_REVIEW 5
#define SCREEN_OFFSEASON 6
#define SCREEN_SETTINGS 7
#define SCREEN_ABOUT 8
#define SCREEN_AWARDS 9
#define SCREEN_STANDINGS 10
#define SCREEN_SERIES 11
#define SCREEN_BOX 12
#define SCREEN_CARD 13
#define SCREEN_PLAYOFFS 14
#define SCREEN_PBOX 15
#define SCREEN_AWHIST 16

/* FIND PLAYER (C50): F on the menu opens a last-name prefix search (18, page, 0, row);
 * the query is a static buffer of FIND_MAX + 1 */
#define SCREEN_FIND 18
#define FIND_MAX 12
#define FIND_LIST 300     /* dynview.FIND_LIST: 300 * 28 B fits the DOS far data budget */
#define KEY_BKSP 8

#define SCREEN_TEAMHIST 17
/* LEADERS modes (C13.3, C39): the state cat is mode * MODE_SHIFT + category index */
#define MODE_CAREER 0
#define MODE_SEASON 1
#define MODE_BYYEAR 2
#define MODE_POST 3
#define MODE_SHIFT 32
#define N_CAREER_CATS 18
#define N_SEASON_CATS 17
#define N_POST_CATS 7
/* POSTSEASON leaders (C39): the top POST_MAX over BOXSCORE.DAT player rows of
 * entries below POST_ENTRY_MAX */
#define POST_MAX 50
#define POST_ENTRY_MAX 4096
#define NO_POST_TEXT "NO POSTSEASON GAMES RECORDED YET."
/* SEASON and BY YEAR leaders keep the top SEASON_MAX lines */
#define SEASON_MAX 50
#define NO_LINES_TEXT "NO SEASON LINES RECORDED YET."
/* PLAYER CARD (C13.5): CARD_SEASON_ROWS season rows a page, then the CAREER row; the entry's
 * SEASLINE lines are collected up to CARD_MAX (the newest of a longer career are cut) */
#define CARD_SEASON_ROWS 7
#define CARD_HDR_Y 84
#define CARD_ROW_Y0 95
#define CARD_CAREER_Y (CARD_ROW_Y0 + CARD_SEASON_ROWS * ROW_H)
#define CARD_MAX 256
#define CARD_CELLS 10
#define NO_CARD_TEXT "NO SEASON LINES RECORDED"
#define NO_RATINGS_TEXT "NO RATINGS RECORDED"
/* PLAYER CARD portraits (C13.5): stock PORTRAIT.ANM frames below OLD_FACE, OLDPORT.ANM from it */
#define PORTRAIT_W 48
#define PORTRAIT_H 56
#define PORTRAIT_X 12
#define PORTRAIT_Y 24
#define OLD_FACE 981
#define OLD_FACE_END 1509
#define OLD_FRAME (12 + PORTRAIT_W * PORTRAIT_H)
#define INFO_X 70
#define DEF_ANMS "ANMS"
#define DEF_GAME "."
/* click bands (C13.6): list and hub body rows start at y 35, title band 8..20, footer from 183 */
#define BODY_Y0 35
#define TITLE_Y0 8
#define TITLE_Y1 20
#define FOOTER_Y0 183
/* DYNASTY SETTINGS cursor rows: 0 ERA RULES, 1 PLAYOFF FORMAT, 2 START YEAR, 3 and up the teams */
#define SET_START 2
#define SET_TEAM0 3
/* ASCII keys of the screens (C13.1, C13.3, C13.5) */
#define KEY_TAB 9
#define KEY_MINUS 45
#define KEY_PLUS 43
#define KEY_EQUALS 61
#define KEY_CARD_CAP 67
#define KEY_CARD_LOW 99
/* C54 LEADERS active-only toggle (CAREER mode) */
#define KEY_ACTIVE_CAP 65
#define KEY_ACTIVE_LOW 97
/* START YEAR (C13.1): u16 LE at HISTORY bytes 18..19; 0 or outside START_MIN..START_MAX counts as
 * START_DEFAULT */
#define HDR_START 18
#define START_MIN 1871
#define START_MAX 2100
#define START_DEFAULT 1993
/* SEASLINE.DAT (C13.2): 16 B header ('SL', version 1, byte 3 zero, u16 line size 80), 80 B lines */
#define SEASLINE_FILE "SEASLINE.DAT"
#define SEASLINE_HDR 16
#define SEASLINE_REC 80
#define SEASLINE_VERSION 1
/* SEASLINE line totals (TOTALS order) used by the SEASON qualifiers */
#define T_G 0
#define T_AB 1
#define T_BB 8
#define T_OUTS 19
#define T_ER 20

/* the hub rows (SCREEN_MENU) and the ABOUT THE MODS rows */
#define N_MENU_ROWS 12
#define N_ABOUT_ROWS 57
#define N_TITLE_ROWS 11

/* MILESTON.DAT kinds from AWARD_KIND_MIN up are award and leader records (C7), not
 * milestones; SEASON AWARDS keeps at most AWARD_MAX rows; SEASON STANDINGS at most
 * STAND_MAX (six header rows, one per division, 32 teams and up to six blank rows that
 * keep a header off a page's last row: 44 rows, 48 with a margin) */
#define AWARD_KIND_MIN 64
#define AWARD_MAX 64
#define STAND_MAX 48
/* AWARD HISTORY (C28): the rows of the award code on the screen (cat L * 20 + k),
 * at most AWHIST_MAX (the fixed buffer of the DOS port); the C28 award kinds are
 * 64 + k (AL) and 96 + k (NL), k 0..19 */
#define AWHIST_MAX LIST_MAX
#define N_AWHIST_CODES 40
/* WORLD SERIES: kind 192 + g game records and 200 + g hits and errors (g 0..6), at most
 * 7 games of 3 rows and the summary row */
#define SERIES_GAME_KIND 192
#define SERIES_HE_KIND 200
#define SERIES_GAMES 7
#define SERIES_MAX 22
/* MILESTONES WATCH (C27): one (need, mark, kind, entry, now) item per active player
 * within 10% of an unreached MILESTONE_CAREER mark, at most LIST_MAX */
#define WATCH_MAX LIST_MAX
typedef struct {
    uint32_t need, mark, now;
    uint8_t kind;               /* the MILESTONE_CAREER kind */
    uint16_t key;               /* TOTALS index of the stat (H 2, HR 5, ...) */
    uint32_t entry;
} WatchItem;
/* BOX SCORE (C7 fourth amendment BOXSCORE.DAT): the first BOX_MAX_RECS records of one
 * (season, game), in file order */
#define BOX_MAX_RECS 112
/* PLAYOFFS (C23c): the flags-4 round header records of one season, at most 48 kept
 * (PLAYOFF_HDR_MAX); the round g is 16..63 */
#define PLAYOFF_HDR_MAX 48
#define PLAYOFF_G_MIN 16
#define PLAYOFF_G_MAX 63

/* C29 TEAM HISTORY: the season rows of one team (at most all 64 seasons) */
#define TEAMHIST_MAX 64

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
/* DYNASTY SETTINGS: byte 10 the era, bytes 12..15 the managed-team mask; MAJ team stems
 * AL slot s (lg s) at MAJ_S_AL, NL slot s (lg s + 16) at MAJ_S_NL, 8 bytes each from
 * MAJ_O_STEM. MAJ_MIN is the smallest MAJ that holds them all. */
#define MAJ_S_AL 0x21d
#define MAJ_S_NL 0x758c
#define MAJ_O_STEM 0x1d7
#define MAJ_MIN (MAJ_S_NL + MAJ_O_STEM + 128L)
/* the team .V20 file layout (v20.HDR, v20.REC; C17 draft POS reads 40 records):
 * record byte 0x1f low nibble is pos1 */
#define V20_HDR 295
#define V20_REC 143
#define V20_SCAN (V20_HDR + V20_REC * 40)
/* the bytes load_teams reads of a MAJ: every stem of both leagues (24 slots each) */
#define TEAM_SPAN (TI_S_NL + TI_O_STEM + 8L * TI_SLOTS)
#define N_TEAM_MAX 32
#define MAJ_NAME_MAX 64
/* PLAYOFF FORMAT (C12.4, C12.6): HISTORY byte 11 is the format, byte 0 the rolled flag; the
 * MAJ day (byte 0x20a) is 7 for a season set up and 0xf3 when the season is over. A MAJ over
 * MAJ_APPLY_MAX bytes is never rewritten here */
#define HDR_FORMAT 11
#define HDR_ROLLED 0
#define MAJ_DAY 0x20a
#define DAY_SETUP 7
#define DAY_OVER 0xf3
#define MAJ_APPLY_MAX 60000L
/* /MENU reads and rewrites CONTROL in the current directory (TONY2.BAT) */
#define CONTROL_FILE "CONTROL"
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

/* HALL OF FAME position filters (C53): the cat of the screen is one of them and TAB
 * cycles it; F_P is any pitcher, the OF filter covers LF CF and RF */
#define N_HOF_FILTERS 9
#define HOF_F_P 1                                  /* the filter index of P */

#define CHAR_W 7
#define SLEN 64             /* cell / line text cap */
#define NAME_CAP_MAX 96
#define MAX_ROWS 12

#ifdef __WATCOMC__
#define FARDATA __far
#else
#define FARDATA
#endif


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
    uint8_t pos1;
    uint16_t first_season;
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
    uint8_t champion, al_pennant, nl_pennant;   /* ids, 0xff unknown */
    uint8_t wl[32][2];          /* W and L by league-global id */
    uint8_t ndiv;               /* divisions of the entry (byte 22); 0 for a legacy entry */
    uint8_t divmap[16];         /* C12.7 division nibbles: id k in byte k / 2, low nibble for even k */
} SeasonEntry;

/* C18 managed-id helper: 1 when stable id tid has its mask bit set */
static int id_managed(int tid);

/* one MILESTON.DAT record: u16 season, u16 idx, u8 kind, u8 zero, u16 value */
typedef struct {
    uint16_t season, idx, value;
    uint8_t kind;
} MsRec;

/* one BOXSCORE.DAT record (16 B on disk, the same fields in the same order): u16 season,
 * u8 g, u8 flags (bit0 side, bit1 pitching), u16 idx, u8 b, u8 i, u8 s[8] stats */
typedef struct {
    uint16_t season;
    uint8_t g, flags;
    uint16_t idx;
    uint8_t b, i, s[8];
} BoxRec;

/* the screen state (dynview.pack): cat is the category, entry or cursor, row the cursor row of
 * the cursor screens (C13.4) and year the BY YEAR season (0: the default season) */
typedef struct {
    int16_t screen, page;
    int32_t cat, row, year;
} State;

/* a state with no cursor, row and year */
static State mk_state(int screen, int page, int32_t cat);

/* a leader category (C13.3): title label, kind (CK_*) and TOTALS index */
enum { CK_COUNT, CK_AVG, CK_ERA, CK_WAR, CK_AW0, CK_AW3, CK_IP };
typedef struct {
    const char *label;
    uint8_t kind, idx;
} CatDef;

/* one SEASLINE.DAT line (C13.2), decoded */
typedef struct {
    uint16_t entry, season, face;
    uint8_t team, pitcher, age, pos1, hand, dev;
    uint8_t ratings[9];
    uint32_t tot[NUM_TOT];
    int16_t war10;
} Line;

/* one SEASON or BY YEAR leader: value, season, entry and team */
typedef struct {
    int32_t val;
    uint16_t season, entry;
    uint8_t team;
} SItem;

/* one PLAYER CARD line: its SEASLINE.DAT offset and season */
typedef struct {
    uint32_t off;
    uint16_t season;
} CardLine;

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

static const ColDef COLS_TEAMHIST[];        /* C29, defined with the other tables */

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

/* SEASON AWARDS: all rows of the season (AWARD_MAX at most) and the award and leader
 * records kept for them, in (kind, file position) order */
static Row FARDATA g_awd[AWARD_MAX];
static MsRec FARDATA g_arec[AWARD_MAX];
/* the player entry of each g_awd row (-1 for none: a message, the GG SS row, an empty slot) */
static int32_t FARDATA g_awd_idx[AWARD_MAX];

/* AWARD HISTORY (C28): the rows of the award code on the screen (AWHIST_MAX at most,
 * kept compact and formatted per page: a Row array of LIST_MAX is far over one segment)
 * and each row's player entry (-1 none) */
typedef struct {
    uint16_t season, idx, value;
    uint8_t fallback;
} AhItem;
static AhItem FARDATA g_ah[AWHIST_MAX];
static int32_t FARDATA g_ah_idx[AWHIST_MAX];
static long g_ah_kind;

/* SEASON and BY YEAR leaders: the top SEASON_MAX of the category (g_sn of them) */
static SItem FARDATA g_sbuf[SEASON_MAX];
static int g_sn;

/* PLAYER CARD: the SEASLINE offsets of the card's entry in season order (g_ncard of them) */
static CardLine FARDATA g_card[CARD_MAX];
static int g_ncard;
static State g_card_back;       /* the list state the PLAYER CARD was opened from (C13.5) */
/* C54: the LEADERS CAREER active-only filter, a session value like the card back state */
static int g_lead_active;
/* C28: the SEASON AWARDS state AWARD HISTORY was opened from, and whether one was */
static State g_awh_back;
static int g_awh_have;

/* FIND PLAYER (C50, find_scan): the matching entries in (last upper, first upper, index)
 * order, capped at LIST_MAX; key in the List keybox of ((last << 32) | (first << 24) |
 * index) is not possible in 32 bits, so the struct holds the sort values directly */
typedef struct {
    uint32_t entry;             /* the entry index (a List idx would need the same width) */
    uint8_t last_u[13], first_u[9];  /* the sort keys, upper case */
    uint8_t pad[2];
} FindItem;
static FindItem FARDATA g_find[FIND_LIST];
static int32_t g_nfind;

/* C26 PLAYER CARD POST row: the postseason sums of the entry (g_post_entry; POST_UNSET is
 * none yet), recomputed only when the entry changes. g_post_games 0 = no player rows
 * (dynview.post_totals returns None), else the distinct (season, g) game count. */
#define POST_UNSET (-1)
#define POST_PAIR_MAX 1024
static int32_t g_post_entry = POST_UNSET;
static int g_post_games, g_post_pairs;
static uint32_t FARDATA g_post_tot[NUM_TOT];
static uint32_t FARDATA g_post_pair[POST_PAIR_MAX];   /* (season << 8) | g, each once */

/* C39 POSTSEASON LEADERS: the totals of every entry below POST_ENTRY_MAX with at
 * least one player row, in ONE pass over BOXSCORE.DAT, cached like the other scans
 * (g_post_cache; POST_CACHE_NONE is none yet). g_post_acc holds one PostAcc per
 * entry: g the distinct games (the value of the G category), the six nonzero stat
 * sums of the POST_CATS value indexes, and the last counted (season, g) key (the
 * records of a game are contiguous, so a differing key is a first record). The top
 * POST_MAX in post order (value descending, entry ascending) live in g_post_top. */
#define POST_CACHE_NONE (-2)
static int32_t g_post_cache = POST_CACHE_NONE;
typedef struct {
    uint32_t val;                     /* the scanned category's sum (G: unused) */
    uint16_t g, last_season;          /* games; the last counted key's season */
    uint8_t last_g, has_last;         /* the last counted key's box g byte */
} PostAcc;                            /* 12 B x POST_ENTRY_MAX fits one far segment */
static PostAcc FARDATA g_post_acc[POST_ENTRY_MAX];
static int g_post_n;                  /* entries now in g_post_top */
/* one top item: value descending, entry ascending (C39) */
typedef struct {
    uint32_t val;
    uint16_t entry, games;
} PostItem;
static PostItem FARDATA g_post_top[POST_MAX];

/* portrait pixels of the PLAYER CARD (48 x 56) */
static uint8_t FARDATA g_portrait[PORTRAIT_W * PORTRAIT_H];

/* SEASON STANDINGS: the rows of the season (STAND_MAX at most) and, per row, the team
 * id it shows (C57): 0xff on a header, blank and message row, else the stable id the
 * cursor's ENTER opens (dynview.standings_teams). The 32 B id table is no far segment. */
#define STAND_NONE 0xff
static Row FARDATA g_stnd[STAND_MAX];
static uint8_t g_stnd_tid[STAND_MAX];

/* MILESTONES WATCH (C27): the watch items in sorted order (WATCH_MAX at most) */
static WatchItem FARDATA g_watch[WATCH_MAX];
static int32_t g_nwatch;

/* WORLD SERIES: the rows of the season (SERIES_MAX at most); per row the game number
 * (C64): g on the header, visitor and home rows of game g, -1 on the summary and
 * message rows */
static Row FARDATA g_ser[SERIES_MAX];
static int8_t FARDATA g_ser_game[SERIES_MAX];

/* PLAYOFFS (C23c): the rows of one season's rounds (PLAYOFF_ROWS_MAX at most: six
 * series of a title, 7 games of 3 rows and the summary) */
#define PLAYOFF_ROWS_MAX 140
static Row FARDATA g_pser[PLAYOFF_ROWS_MAX];

/* BOX SCORE: the records of the game on the screen (BOX_MAX_RECS at most); the file is
 * read again only for another (season, game): g_box_g -1 is none yet */
static BoxRec FARDATA g_box[BOX_MAX_RECS];
static long g_box_season;
static int g_box_g = -1, g_box_n;
/* C62 row cursor: g_box_idx[r] is the player entry of row r (or -1: a header row,
 * '' entry 0xffff, or a row past the walk); filled while the rows build */
static int16_t g_box_idx[BOX_MAX_RECS + 4];

/* PLAYOFFS (C23c): the season's flags-4 round headers, (g, idx, b, i, stats) streamed
 * from BOXSCORE.DAT like the BOX screen does (never the whole file) */
typedef struct {
    uint8_t g, i;
    uint16_t idx;
    uint8_t b;
    uint8_t s[8];
} PlHdr;
static PlHdr FARDATA g_pl[PLAYOFF_HDR_MAX];
/* C30 POSTSEASON LEADERS: the per-entry season sums of build_playoffs's tally, one slot
 * a distinct entry, streamed from BOXSCORE.DAT (post_leader_tally; g_pldr tidied with
 * the headers' g_pl_season cache). {H, HR, RBI, SB, SO, ER, OUTS} u16 sums, 8 slots a
 * 16 B line (one far segment) x POST_LEADER_MAX entries */
#define POST_LEADER_MAX 256
typedef struct {
    uint16_t idx;
    uint16_t s[7];              /* H, HR, RBI, SB, SO, ER, OUTS */
} PlDr;
static PlDr FARDATA g_pldr[POST_LEADER_MAX];
static int g_pldr_n;
/* PLAYOFF BOX: the non-header records of the round game on the screen */
static BoxRec FARDATA g_pbox[BOX_MAX_RECS];
static long g_pl_season;
static int g_pl_n;

/* C29 TEAM HISTORY: the rows of the team on the screen (TEAMHIST_MAX at most) */
/* a TEAM HISTORY row: six short cells (the longest the 19-char message), not a full Row,
 * to stay inside the DOS far data budget */
#define TH_CW 20
typedef struct {
    char cells[6][TH_CW];
    int ncells;
    int season;                 /* C60: the row's season number, 0 on the message row */
} ThRow;
static ThRow FARDATA g_th[TEAMHIST_MAX];
/* the kept SEASON STANDINGS state (data['th_back']) now carries the absolute row in
 * State.row too (C57); th_live marks it set */
static State g_th_back;
static int g_th_live;
/* C56: the state kept for ESC (data['st_back']): the SEASON HISTORY state (cursor kept)
 * SEASON STANDINGS was opened from; g_st_have marks it set */
static State g_st_back;
static int g_st_have;

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
/* base of the release ords on the phase OFF_FA screen: g_rc.fa of the roster_count
 * pre-pass (the final free agent count), kept out of the row pass's own g_rc */
static uint32_t g_fabase;

static State g_state;
static int g_exit;

/* DYNASTY SETTINGS: era and managed-team mask (HISTORY.DAT bytes 10, 12..15), the
 * MAJ teams by stable id (g_tlg, display g_tdisp), the playoff format wanted and now
 * (g_fmt_wanted, g_fmt_now; realign.wanted_for_dir) and the redraw flag of an ENTER */
static uint8_t g_era;
static uint32_t g_mask;
static int g_nteams;
static uint8_t g_tlg[N_TEAM_MAX];
static char g_tdisp[N_TEAM_MAX][16];
/* C17.2 mapped stems (the same walk load_teams does): the ASCII upper case stem of
 * every listed team and its stable id, matched by the ROSTERS.TXT token */
static char g_tstem[N_TEAM_MAX][9];
static int g_fmt_wanted, g_fmt_now;
static int g_dirty;

/* TEAM column (C13.3): the MAJ 3-letter abbreviation of each team id with one */
static uint8_t g_abid[TI_MAX_TEAMS];
static char g_abtxt[TI_MAX_TEAMS][4];
static int g_nab;

/* C17 draft POS: the raw bytes of every team token's V20 the screen read so far
 * (NULL for a token with no readable file); the file is read at most once per build */
static char g_postok[DRAFT_KEEP][16];
static uint8_t *g_posraw[DRAFT_KEEP];
static int g_npostok;

/* the cache of one draft screen build: freed and cleared before the rows are made */
static void pos_cache_reset(void)
{
    int i;
    for (i = 0; i < g_npostok; i++)
        if (g_posraw[i])
            free(g_posraw[i]);
    g_npostok = 0;
}

/* /ANMS:dir (PORTRAIT.ANM) and /GAME:dir (OLDPORT.ANM) */
static char g_anms[260] = DEF_ANMS;
static char g_game[260] = DEF_GAME;

#ifdef __WATCOMC__
/* INT 33h: 1 when a mouse driver answered AX=0; g_mbtn the buttons of the last poll */
static int g_mouse;
static int g_mbtn;
#endif

/* ABOUT THE MODS rows (dynview.ABOUT_ROWS) */
static const char *ABOUT_LINES[N_ABOUT_ROWS] = {
    "DYNASTY MODE",
    "YOUR LEAGUE PLAYS SEASON AFTER SEASON.",
    "AFTER THE WORLD SERIES PICK SEASON >",
    "START NEW SEASON. THE OFFSEASON AGES",
    "EVERY PLAYER A YEAR. RATINGS RISE OR FALL,",
    "VETERANS RETIRE, ROOKIES ARE DRAFTED, AND",
    "TRADES AND FREE AGENCY RUN. EACH SEASON IS",
    "ARCHIVED FIRST TO C:\\SEASONS OR C:\\DYNLG.",
    "",
    "DYNASTY > DYNASTY MODE ON THE MENU BAR",
    "SHOWS HISTORY, HALL OF FAME, LEADERS,",
    "MILESTONES, SEASON AWARDS, STANDINGS",
    "AND THE LAST OFFSEASON.",
    "CREATE A PLAYER",
    "DYNASTY > CREATE A PLAYER PUTS A NEW",
    "PLAYER ON ANY TEAM: NAME, POSITION,",
    "HANDS, AGE, RATINGS AND FACE. THE NEW",
    "PLAYER TAKES THE ROSTER SLOT YOU PICK.",
    "",
    "DYNASTY SETTINGS",
    "ERA RULES: REAL CALENDAR GIVES THE",
    "RESERVE CLAUSE UNTIL 1975 AND FREE",
    "AGENCY FROM 1976, OR FIX EITHER ONE.",
    "TEAMS YOU MANAGE KEEP THEIR ROSTERS:",
    "NO AI RELEASES, TRADES OR DEPARTURES.",
    "A HOLE ON YOUR TEAM TAKES THE BEST",
    "ROOKIE LEFT IN THE DRAFT CLASS, AND YOUR",
    "LINEUP IS REPAIRED, NOT REBUILT.",
    "PLAYOFF FORMAT: 2 DIVISIONS AND AN LCS,",
    "OR 3 DIVISIONS AND A WILD CARD WITH A",
    "DIVISION SERIES. IT TAKES EFFECT AT ONCE",
    "BEFORE A SEASON STARTS, ELSE AT THE ROLL.",
    "THEN START THE NEW SEASON WITH THE",
    "GENERATED SCHEDULE.",
    "",
    "LEADERS: CAREER, SINGLE SEASON AND BY",
    "YEAR. TAB SWITCHES. ENTER OR A CLICK ON A",
    "PLAYER OPENS HIS CARD.",
    "START YEAR: DYNASTY SETTINGS, LEFT RIGHT.",
    "",
    "NUMBER OF TEAMS",
    "UTILITIES > SETUP LEAGUES: NEW TEAM, THEN",
    "CLICK IT AND AN EMPTY DIVISION ROW.",
    "CLICK A PLACED TEAM TO REMOVE IT. NEW",
    "TEAMS DRAFT FROM AI TEAMS, WHICH KEEP 15",
    "EACH, THEN SIGN FREE AGENTS. PLAYERS OF",
    "A REMOVED TEAM BECOME FREE AGENTS. START",
    "THE SEASON WITH A SCHEDULE THAT FITS,",
    "ELSE GENERATED.",
    "",
    "NEW FACES",
    "323 NEW FACES JOIN THE 30 STOCK ONES.",
    "ROOKIES AND CREATED PLAYERS USE THEM.",
    "",
    "MODERN BALLPARKS",
    "UTILITIES > ASSIGN STADIUMS LETS ANY TEAM",
    "PLAY IN A NEW PARK." };

/* CAREER LEADERS categories (C13.3, dynview.CATS), in list order */
static const CatDef CAREER_CATS[N_CAREER_CATS] = {
    { "H", CK_COUNT, 2 }, { "HR", CK_COUNT, 5 }, { "RBI", CK_COUNT, 7 },
    { "R", CK_COUNT, 6 }, { "2B", CK_COUNT, 3 }, { "3B", CK_COUNT, 4 },
    { "SB", CK_COUNT, 10 }, { "BB", CK_COUNT, 8 }, { "AVG", CK_AVG, 0 },
    { "WAR", CK_WAR, 0 }, { "W", CK_COUNT, 13 }, { "SV", CK_COUNT, 15 },
    { "SO", CK_COUNT, 23 }, { "ERA", CK_ERA, 0 }, { "IP", CK_IP, 19 },
    { "SHO", CK_COUNT, 18 }, { "MVP AWARDS", CK_AW0, 0 },
    { "GG AWARDS", CK_AW3, 0 } };
/* SEASON and BY YEAR categories (C13.3, dynview.SEASON_CATS), over SEASLINE.DAT lines */
static const CatDef SEASON_CATS[N_SEASON_CATS] = {
    { "AVG", CK_AVG, 0 }, { "HR", CK_COUNT, 5 }, { "RBI", CK_COUNT, 7 },
    { "H", CK_COUNT, 2 }, { "R", CK_COUNT, 6 }, { "2B", CK_COUNT, 3 },
    { "3B", CK_COUNT, 4 }, { "SB", CK_COUNT, 10 }, { "BB", CK_COUNT, 8 },
    { "WAR", CK_WAR, 0 }, { "W", CK_COUNT, 13 }, { "ERA", CK_ERA, 0 },
    { "SO", CK_COUNT, 23 }, { "SV", CK_COUNT, 15 }, { "IP", CK_IP, 19 },
    { "CG", CK_COUNT, 17 }, { "SHO", CK_COUNT, 18 } };
/* POSTSEASON categories (C39, dynview.POST_CATS), over the BOXSCORE.DAT player rows
 * (C26 sums): the value index is the TOTALS index, 0 = G = the distinct game count */
static const CatDef POST_CATS[N_POST_CATS] = {
    { "G", CK_COUNT, 0 }, { "H", CK_COUNT, 2 }, { "HR", CK_COUNT, 5 },
    { "RBI", CK_COUNT, 7 }, { "SB", CK_COUNT, 10 }, { "SO", CK_COUNT, 23 },
    { "IP", CK_IP, 19 } };
/* the position names of the PLAYER CARD (dynview.POS_NAMES) and the bats code (byte 29 bits 2..1) */
static const char *POS_NAMES[16] = {
    "P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "OF", "IF",
    "OI", "CO", "CI", "C3" };
static const char BATS_NAMES[5] = "LRS?";
/* PLAYER CARD info rows (C13.5): x INFO_X, y INFO_Y[0..4] */
static const int INFO_Y[5] = { 26, 37, 48, 59, 70 };

int main(int argc, char **argv);
static void render(State st);
static void build_no_hist_rows(void);
static const char *pos_name(int p);
static const ColDef *body_cols(State st);
static int offseason_body(State st, int page, const ColDef **cols);
static int awards_body(State st, int page, const ColDef **cols);
static int awhist_body(State st, int page, const ColDef **cols);
static int standings_body(State st, int page, const ColDef **cols);
static int teamhist_body(State st, int page, const ColDef **cols);
static void screen_title(State st, char *dst);
static void fmt_avg(int32_t v, char *dst);
static int playoff_headers(long season);
static void year_text(int32_t n, char *dst);
static void star_cell(char *c);
static int series_body(State st, int page, const ColDef **cols);
static int box_body(State st, int page, const ColDef **cols);
static int playoffs_body(State st, int page, const ColDef **cols);
static int pbox_body(State st, int page, const ColDef **cols);
static int msg_row(int page, const char *text);
static Row *box_next(int *ord, int page);
static void box_set(Row *row, const char *c0, const char *c1, const char *c2,
                    const char *c3, const char *c4, const char *c5, const char *c6);
static void box_rec_row(Row *row, const BoxRec *r, int pitch);
static int16_t *box_idx_base(void);
static void box_idx_put(int ord, const BoxRec *r);
static void box_idx_clear(void);
static int32_t box_row_entry(State st);
static int32_t pbox_row_entry(State st);
static int leaders_body(State st, int page, const ColDef **cols);
static int post_scan(const CatDef *c);
static int build_post_rows(const CatDef *c, int page);

/* C40 HONORS: the row count (total_rows), the page's rows into g_rows, and the columns
 * (COLS_HONORS, where the other column tables are) */
static int honors_rows_count(int32_t entry);
static int honors_rows(int32_t entry, int page);
#define HONOR_ROWS 9
static const ColDef COLS_HONORS[2];

static int find_body(State st, int page, const ColDef **cols);
static const ColDef COLS_FIND[4];       /* defined below, FIND PLAYER needs it early */
/* ---- helpers ---- */

/* the FIND PLAYER query (C50): ASCII upper case letters, FIND_MAX chars at most */
static char g_find_q[FIND_MAX + 1];

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
            long base;
            if (py < 0 || py >= FB_H)
                continue;
            /* long: py * FB_W passes 32767 from y 103 on a 16-bit int (DOS) */
            base = (long)py * FB_W;
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
        uint8_t *row = g_fb + (long)y * FB_W;
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

/* C18 champion star: 1 when se->champion_stem (ASCII upper case, stripped like
 * dynview.stems_managed) maps through g_tstem (the same walk load_teams builds) to a
 * managed stable id */
static int champ_managed(const SeasonEntry *se)
{
    char stem[9];
    int i, m;
    field_of(se->champion_stem, 8, stem);       /* NUL-or-space cut, trailing spaces gone */
    if (!stem[0])
        return 0;                               /* '?' like stem_display; never managed */
    for (m = 0; stem[m] && m < 8; m++)
        stem[m] = (char)ascii_up((uint8_t)stem[m]);
    stem[m] = 0;
    for (i = 0; i < g_nteams; i++)
        if (strcmp(g_tstem[i], stem) == 0)
            return id_managed(g_tlg[i]);
    return 0;
}

/* C17 draft POS name of a record: rosters.pname = First Last from the record bytes
 * (last 0..12, first 12..20), into dst */
static void rec_pname(const uint8_t *rec, char *dst)
{
    char last[13], first[9];
    int i, n = 0;
    field_of(rec, 12, last);
    field_of(rec + 12, 8, first);
    for (i = 0; first[i]; i++)
        dst[n++] = first[i];
    if (first[0] && last[0])
        dst[n++] = ' ';
    for (i = 0; last[i]; i++)
        dst[n++] = last[i];
    dst[n] = 0;
}

/* C17 draft POS column of a pick on team token s (n bytes): the v20 pos1 (record byte
 * 0x1f low nibble) of the first on slot (record byte 0 non-zero) 0..39 of the team file
 * whose rosters.pname equals name (nname bytes), "" when the file is missing, shorter
 * than V20_SCAN or no slot matches. The team file is read at most once per screen. */
static int posraw_of(const uint8_t *s, int n, uint8_t **out)
{
    int i, found = 0;
    uint8_t *cache = NULL;
    *out = NULL;
    if (n < 1 || n > 8)                     /* no V20 stem is longer than 8 */
        return 1;
    for (i = 0; i < g_npostok && !found; i++) {
        if (g_postok[i][n] == 0 && memcmp(g_postok[i], s, (size_t)n) == 0) {
            cache = g_posraw[i];
            found = 1;
        }
    }
    if (found) {
        *out = cache;
        return 1;
    }
    if (g_npostok >= DRAFT_KEEP)
        return 1;
    memcpy(g_postok[g_npostok], s, (size_t)n);
    g_postok[g_npostok][n] = 0;
    if (1) {
        FILE *f = open_v20(s, n);
        if (f) {
            uint8_t *d = (uint8_t *)malloc((size_t)V20_SCAN);
            if (d) {
                memset(d, 0, (size_t)V20_SCAN);
                if (fread(d, 1, (size_t)V20_SCAN, f) == (size_t)V20_SCAN)
                    *out = d;
                else
                    free(d);
            }
            fclose(f);
        }
    }
    g_posraw[g_npostok] = *out;
    g_npostok++;
    return 1;
}

static void draft_pos(const uint8_t *s, int n, const uint8_t *name, int nname, char *dst)
{
    uint8_t *raw;
    int slot, i;
    dst[0] = 0;
    posraw_of(s, n, &raw);
    if (!raw)
        return;
    for (slot = 0; slot < 40; slot++) {
        const uint8_t *rec = raw + (long)V20_HDR + (long)V20_REC * slot;
        char pn[32];
        if (rec[0] == 0)
            continue;
        rec_pname(rec, pn);
        if ((int)strlen(pn) != nname)
            continue;
        for (i = 0; i < nname && pn[i] == (char)name[i]; i++)
            ;
        if (i < nname)
            continue;
        strcpy(dst, pos_name(rec[0x1f] & 15));
        return;
    }
}

/* C17 managed mark of a team token (n bytes): 1 when its ASCII upper case equals a
 * mapped stem (g_tstem, built with g_tdisp/g_tlg by load_teams) and the bit of that
 * stem's stable id is set in g_mask. A token with no stem match is not managed. */
static int team_managed(const uint8_t *s, int n)
{
    char up[9];
    int i, m, tid;
    if (n < 1 || n > 8)
        return 0;
    for (m = 0; m < n; m++) {
        if (s[m] == 0)
            return 0;
        up[m] = (char)ascii_up(s[m]);
    }
    up[m] = 0;
    for (i = 0; i < g_nteams; i++) {
        if (strcmp(g_tstem[i], up) != 0)
            continue;
        tid = g_tlg[i];
        return tid < 32 && ((g_mask >> tid) & 1u) != 0;
    }
    return 0;
}

/* C18 managed-id helper: 1 when stable id tid has its mask bit set */
static int id_managed(int tid)
{
    return tid < 32 && ((g_mask >> tid) & 1u) != 0;
}

/* C17 '*' prefix of a TEAM cell, the text kept NUL terminated within SLEN. */
static void star_cell(char *c)
{
    size_t n = strlen(c);
    if (n > SLEN - 2)
        n = SLEN - 2;
    memmove(c + 1, c, n);
    c[0] = '*';
    c[n + 1] = 0;
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

/* outs = OUTS: whole innings and thirds, '1234.2' (dynview.fmt_ip) */
static void fmt_ip(uint32_t outs, char *dst)
{
    sprintf(dst, "%lu.%lu", (unsigned long)(outs / 3u), (unsigned long)(outs % 3u));
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
    e->pos1 = eb[30];
    e->first_season = (uint16_t)(eb[24] | ((uint16_t)eb[25] << 8));
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
    se->champion = sb[2];
    se->al_pennant = sb[20];
    se->nl_pennant = sb[21];
    se->ndiv = sb[22];
    memcpy(se->divmap, sb + 100, 16);
    for (k = 0; k < 32; k++) {
        se->wl[k][0] = sb[24 + 2 * k];
        se->wl[k][1] = sb[25 + 2 * k];
    }
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

/* ---------------- DYNASTY SETTINGS: HISTORY.DAT header, MAJ teams ---------------- */

/* the first 32 bytes of HISTORY.DAT: era = byte 10, mask = u32 LE of bytes 12..15; a
 * missing or unreadable file is all zero */
static void load_settings(void)
{
    char path[600];
    uint8_t d[HDR_SIZE];
    FILE *f;
    memset(d, 0, sizeof d);
    path_join(path, g_lgdir, "HISTORY.DAT");
    f = fopen(path, "rb");
    if (f) {
        (void)fread(d, 1, HDR_SIZE, f);
        fclose(f);
    }
    g_era = d[10];
    g_mask = (uint32_t)d[12] | ((uint32_t)d[13] << 8)
           | ((uint32_t)d[14] << 16) | ((uint32_t)d[15] << 24);
}

/* keep the smallest name ending in .MAJ (strcmp order: the first of the sorted list) */
static void maj_consider(char *best, int *have, const char *name)
{
    size_t l = strlen(name);
    if (l <= 4 || l >= MAJ_NAME_MAX || strcmp(name + l - 4, ".MAJ") != 0)
        return;
    if (!*have || strcmp(name, best) < 0) {
        strcpy(best, name);
        *have = 1;
    }
}

/* the first *.MAJ of the league directory into best (1 found). The DOS listing is
 * upper case already; the host match is case-sensitive, like history.maj_or_none */
static int find_maj(char *best)
{
    int have = 0;
#ifdef __WATCOMC__
    char pat[300];
    struct find_t ft;
    path_join(pat, g_lgdir, "*.MAJ");
    if (_dos_findfirst(pat, _A_NORMAL, &ft) == 0) {
        do
            maj_consider(best, &have, ft.name);
        while (_dos_findnext(&ft) == 0);
    }
#else
    DIR *dirp = opendir(g_lgdir);
    struct dirent *de;
    if (!dirp)
        return 0;
    while ((de = readdir(dirp)) != NULL)
        maj_consider(best, &have, de->d_name);
    closedir(dirp);
#endif
    return have;
}

/* 1 when name is TEAMID.DAT in any case (teamids.TABLE_NAME, upper cased) */
static int table_name(const char *name)
{
    static const char want[] = "TEAMID.DAT";
    int i;
    if (strlen(name) != sizeof want - 1)
        return 0;
    for (i = 0; want[i]; i++)
        if (ascii_up((uint8_t)name[i]) != (uint8_t)want[i])
            return 0;
    return 1;
}

/* the TEAMID.DAT name of g_lgdir into best (the smallest in strcmp order, as
 * teamids.table_path); on DOS the 8.3 name directly. 1 when there is one */
static int find_table(char *best)
{
    int have = 0;
#ifdef __WATCOMC__
    char pat[300];
    struct find_t ft;
    path_join(pat, g_lgdir, "TEAMID.DAT");
    if (_dos_findfirst(pat, _A_NORMAL, &ft) == 0 && table_name(ft.name)) {
        strcpy(best, ft.name);
        have = 1;
    }
#else
    DIR *dirp = opendir(g_lgdir);
    struct dirent *de;
    if (!dirp)
        return 0;
    while ((de = readdir(dirp)) != NULL) {
        if (table_name(de->d_name) && (!have || strcmp(de->d_name, best) < 0)) {
            strcpy(best, de->d_name);
            have = 1;
        }
    }
    closedir(dirp);
#endif
    return have;
}

/* the TEAMID.DAT path of g_lgdir into path; 0 when there is none */
static int table_file(char *path)
{
    char best[MAJ_NAME_MAX];
    if (!find_table(best))
        return 0;
    path_join(path, g_lgdir, best);
    return 1;
}

/* the first *.MAJ of g_lgdir as a path; 0 when there is none */
static int maj_file(char *path)
{
    char best[MAJ_NAME_MAX];
    if (!find_maj(best))
        return 0;
    path_join(path, g_lgdir, best);
    return 1;
}

/* TEAMID.DAT as the table of the stable ids (teamids.load_table): tab gets its 256 B when the
 * file is exactly 256 B; 1 when it did, 0 when there is no such table */
static int load_table(uint8_t *tab)
{
    char path[600];
    FILE *f;
    int ok = 0;
    if (!table_file(path))
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

/* the MAJ teams by stable id (C12.3, teamids.teams: TEAMID.DAT when it is a table, else
 * engine ids), in id order. A team whose stem is empty or has no team file is skipped. No
 * MAJ, a read error or a file shorter than MAJ_MIN gives no teams. The first TEAM_SPAN bytes
 * are read into a zeroed buffer (a short MAJ reads as zero padding). */
static void load_teams(void)
{
    char path[600];
    uint8_t *d, tab[TI_TABLE_SIZE];
    TiTeam t[TI_MAX_TEAMS];
    FILE *f;
    long sz;
    size_t want;
    int have_tab, n, i, m;
    g_nteams = 0;
    g_nab = 0;
    if (!maj_file(path))
        return;
    f = fopen(path, "rb");
    if (!f)
        return;
    if (fseek(f, 0, SEEK_END) != 0 || (sz = ftell(f)) < MAJ_MIN) {
        fclose(f);
        return;
    }
    want = sz < TEAM_SPAN ? (size_t)sz : (size_t)TEAM_SPAN;
    d = (uint8_t *)malloc((size_t)TEAM_SPAN);
    if (!d) {
        fclose(f);
        return;
    }
    memset(d, 0, (size_t)TEAM_SPAN);
    if (fseek(f, 0, SEEK_SET) != 0 || fread(d, 1, want, f) != want) {
        fclose(f);
        free(d);
        return;
    }
    fclose(f);
    have_tab = load_table(tab);
    n = ti_teams(d, TEAM_SPAN, have_tab ? tab : NULL, t);
    /* the TEAM column names (dynview.team_abbrs): every team with a non-blank abbreviation */
    for (i = 0; i < n && g_nab < TI_MAX_TEAMS; i++) {
        uint8_t ab[3];
        memcpy(ab, d + ti_league_s(t[i].L) + TI_O_ABBR + 3L * t[i].slot, 3);
        field_of(ab, 3, g_abtxt[g_nab]);
        if (g_abtxt[g_nab][0]) {
            g_abid[g_nab] = t[i].id;
            g_nab++;
        }
    }
    free(d);
    for (i = 0; i < n; i++) {
        m = 0;
        while (m < 8 && t[i].stem[m])
            m++;
        if (m == 0 || !team_file(t[i].stem, m))
            continue;
        g_tlg[g_nteams] = t[i].id;
        team_disp(t[i].stem, m, g_tdisp[g_nteams]);
        for (m = 0; m < 8 && t[i].stem[m]; m++)
            g_tstem[g_nteams][m] = (char)ascii_up(t[i].stem[m]);
        g_tstem[g_nteams][m] = 0;
        g_nteams++;
    }
}

/* g_fmt_wanted and g_fmt_now (realign.wanted_for_dir): now from the MAJ's first 0x20e bytes
 * (no MAJ reads as an empty buffer, now 2), wanted from HISTORY.DAT's first 12 bytes */
static void load_fmt(void)
{
    char path[600];
    uint8_t mb[0x20e], hb[12];
    FILE *f;
    long mlen = 0, hlen = 0;
    memset(mb, 0, sizeof mb);
    memset(hb, 0, sizeof hb);
    if (maj_file(path)) {
        f = fopen(path, "rb");
        if (f) {
            mlen = (long)fread(mb, 1, sizeof mb, f);
            fclose(f);
        }
    }
    path_join(path, g_lgdir, "HISTORY.DAT");
    f = fopen(path, "rb");
    if (f) {
        hlen = (long)fread(hb, 1, sizeof hb, f);
        fclose(f);
    }
    g_fmt_now = ra_now_divs(mb, mlen);
    g_fmt_wanted = ra_wanted(hb, hlen, mb, mlen);
}

/* HISTORY.DAT: byte 10 = g_era, bytes 12..15 = g_mask (u32 LE); nothing else changes.
 * A missing file is created (32 zero bytes first), a shorter one zero-extended to 32
 * bytes. Open and write failures are ignored, like the Python OSError rule. */
static void save_settings(void)
{
    char path[600];
    uint8_t zero[HDR_SIZE], mb[4], era = g_era;
    FILE *f;
    long sz;
    path_join(path, g_lgdir, "HISTORY.DAT");
    f = fopen(path, "r+b");
    if (!f) {
        memset(zero, 0, sizeof zero);
        f = fopen(path, "wb");
        if (!f)
            return;
        (void)fwrite(zero, 1, HDR_SIZE, f);
        fclose(f);
        f = fopen(path, "r+b");
        if (!f)
            return;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return;
    }
    sz = ftell(f);
    if (sz < 0) {
        fclose(f);
        return;
    }
    if (sz < HDR_SIZE) {
        memset(zero, 0, sizeof zero);
        (void)fwrite(zero, 1, (size_t)(HDR_SIZE - sz), f);
    }
    mb[0] = (uint8_t)(g_mask & 0xffu);
    mb[1] = (uint8_t)((g_mask >> 8) & 0xffu);
    mb[2] = (uint8_t)((g_mask >> 16) & 0xffu);
    mb[3] = (uint8_t)((g_mask >> 24) & 0xffu);
    if (fseek(f, 10, SEEK_SET) == 0)
        (void)fwrite(&era, 1, 1, f);
    if (fseek(f, 12, SEEK_SET) == 0)
        (void)fwrite(mb, 1, 4, f);
    fclose(f);
}

/* the byte at pos of the file path, -1 when the file is missing, unreadable or shorter */
static int file_byte(const char *path, long pos)
{
    uint8_t b = 0;
    int r = -1;
    FILE *f = fopen(path, "rb");
    if (!f)
        return -1;
    if (fseek(f, pos, SEEK_SET) == 0 && fread(&b, 1, 1, f) == 1)
        r = b;
    fclose(f);
    return r;
}

/* HISTORY.DAT byte pos, -1 when there is none (dynview.hist_byte) */
static int hist_byte(int pos)
{
    char path[600];
    path_join(path, g_lgdir, "HISTORY.DAT");
    return file_byte(path, pos);
}

/* the MAJ day byte, -1 when there is no MAJ or it is short (dynview.maj_day) */
static int maj_day(void)
{
    char path[600];
    if (!maj_file(path))
        return -1;
    return file_byte(path, MAJ_DAY);
}

/* HISTORY.DAT byte pos = value, with the save_settings rules: a missing file is created, a
 * short one zero-extended to HDR_SIZE bytes, no other byte changes; errors are ignored
 * (dynview.put_hist_byte) */
static void put_hist_byte(int pos, int value)
{
    char path[600];
    uint8_t zero[HDR_SIZE], b = (uint8_t)value;
    FILE *f;
    long sz;
    path_join(path, g_lgdir, "HISTORY.DAT");
    f = fopen(path, "r+b");
    if (!f) {
        memset(zero, 0, sizeof zero);
        f = fopen(path, "wb");
        if (!f)
            return;
        (void)fwrite(zero, 1, HDR_SIZE, f);
        fclose(f);
        f = fopen(path, "r+b");
        if (!f)
            return;
    }
    if (fseek(f, 0, SEEK_END) != 0 || (sz = ftell(f)) < 0) {
        fclose(f);
        return;
    }
    if (sz < HDR_SIZE) {
        memset(zero, 0, sizeof zero);
        (void)fwrite(zero, 1, (size_t)(HDR_SIZE - sz), f);
    }
    if (fseek(f, pos, SEEK_SET) == 0)
        (void)fwrite(&b, 1, 1, f);
    fclose(f);
}

/* the start year (C13.1, dynview.start_year): HISTORY bytes 18..19 as u16 LE, START_DEFAULT when
 * that is 0 or outside START_MIN..START_MAX */
static int32_t start_year(void)
{
    int32_t v = g_hdr[HDR_START] | (g_hdr[HDR_START + 1] << 8);
    return v >= START_MIN && v <= START_MAX ? v : START_DEFAULT;
}

/* the calendar year of season n (1-based): start year + n - 1 (dynview.year_of) */
static int32_t year_of(int32_t n)
{
    return start_year() + n - 1;
}

/* year_of(n) as text (dynview.year_text) */
static void year_text(int32_t n, char *dst)
{
    sprintf(dst, "%ld", (long)year_of(n));
}

/* LEFT / RIGHT / '-' / '+' / '=' on START YEAR (C13.1, dynview.start_year_step): the start year moves
 * by delta, clamped to START_MIN..START_MAX; HISTORY bytes 18..19 are written (the rest of the file
 * is untouched) and the header in memory follows, so every season label relabels */
static void start_year_step(int32_t delta)
{
    int32_t v = start_year() + delta;
    if (v < START_MIN)
        v = START_MIN;
    if (v > START_MAX)
        v = START_MAX;
    put_hist_byte(HDR_START, (int)(v & 255));
    put_hist_byte(HDR_START + 1, (int)(v >> 8));
    g_hdr[HDR_START] = (uint8_t)(v & 255);
    g_hdr[HDR_START + 1] = (uint8_t)(v >> 8);
    g_dirty = 1;
}

/* realign.apply (C12.5, C12.6): the MAJ of g_lgdir realigned to the wanted format by ra_plan,
 * TEAMID.DAT written first when the plan made it (no table, or one not 256 B), then the MAJ.
 * After a rewrite on day 7, HISTORY byte 0 = 1. A refused plan, a MAJ over MAJ_APPLY_MAX bytes
 * or one that cannot be read changes nothing */
static void realign_apply(int day)
{
    char mpath[600], tpath[600], hpath[600];
    uint8_t *d, hb[HDR_SIZE], tab[TI_TABLE_SIZE];
    const char *reason = NULL;
    FILE *f;
    long sz, hlen = 0;
    size_t got;
    int have_tab, tab_new = 0, rc;

    if (!maj_file(mpath))
        return;
    f = fopen(mpath, "rb");
    if (!f)
        return;
    if (fseek(f, 0, SEEK_END) != 0 || (sz = ftell(f)) <= 0 || sz > MAJ_APPLY_MAX
        || fseek(f, 0, SEEK_SET) != 0) {
        fclose(f);
        return;
    }
    d = (uint8_t *)malloc((size_t)sz);
    if (!d) {
        fclose(f);
        return;
    }
    got = fread(d, 1, (size_t)sz, f);
    fclose(f);
    if (got != (size_t)sz) {
        free(d);
        return;
    }
    path_join(hpath, g_lgdir, "HISTORY.DAT");
    f = fopen(hpath, "rb");
    if (f) {
        hlen = (long)fread(hb, 1, sizeof hb, f);
        fclose(f);
    }
    have_tab = load_table(tab);
    rc = ra_plan(d, sz, hb, hlen, have_tab, tab, &tab_new, &reason);
    if (rc == 0) {
        if (tab_new) {
            if (!table_file(tpath))
                path_join(tpath, g_lgdir, "TEAMID.DAT");
            f = fopen(tpath, "wb");
            if (f) {
                (void)fwrite(tab, 1, TI_TABLE_SIZE, f);
                fclose(f);
            }
        }
        f = fopen(mpath, "wb");
        if (f) {
            (void)fwrite(d, 1, (size_t)sz, f);
            fclose(f);
        }
        if (day == DAY_SETUP)
            put_hist_byte(HDR_ROLLED, 1);
    }
    free(d);
}

/* ENTER on PLAYOFF FORMAT (dynview.set_playoff_format): HISTORY byte 11 = 5 - wanted, then the
 * apply at once when the MAJ day is 0xf3 with HISTORY byte 0 = 1, or the day is 7. A missing
 * MAJ or HISTORY byte 0 leaves it at byte 11 */
static void set_playoff_format(int wanted)
{
    int day, rolled;
    put_hist_byte(HDR_FORMAT, 5 - wanted);
    day = maj_day();
    rolled = hist_byte(HDR_ROLLED);
    if (day < 0 || rolled < 0)
        return;
    if ((day == DAY_OVER && rolled == 1) || day == DAY_SETUP)
        realign_apply(day);
}

/* /MENU item: CONTROL[1] = 8 + item (item 0..3) in the current directory; 0 when the file
 * is missing, shorter than 2 bytes or holds any other value */
static int control_item(void)
{
    uint8_t d[2];
    FILE *f = fopen(CONTROL_FILE, "rb");
    int item = 0;
    if (!f)
        return 0;
    if (fread(d, 1, 2, f) == 2 && d[1] >= 8 && d[1] <= 11)
        item = d[1] - 8;
    fclose(f);
    return item;
}

/* CONTROL[1] = CONTROL[0] in place, so TONY2.BAT restarts MAIN; a missing file or one
 * under 2 bytes is left alone */
static void control_return(void)
{
    uint8_t d[2];
    FILE *f = fopen(CONTROL_FILE, "r+b");
    if (!f)
        return;
    if (fread(d, 1, 2, f) == 2) {
        (void)fseek(f, 1, SEEK_SET);
        (void)fwrite(&d[0], 1, 1, f);
    }
    fclose(f);
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

/* the count pre-pass of the phase OFF_FA screen: roster_pass with page < 0 fills g_rc
 * with the final counts, and g_fabase takes g_rc.fa so the release ords of the row pass
 * are (final free agent count) + the file-order release index, like Python's rows. */
static void roster_pass(int phase, int page);

static void roster_count(void)
{
    g_fabase = 0;
    roster_pass(-1, -1);
    g_fabase = g_rc.fa;
}

/* one ROSTERS.TXT pass: every SIGN, TRADE and REL line is counted in g_rc (uncapped).
 * The rows of phase (OFF_DRAFT, OFF_TRADES or OFF_FA) that page shows go to g_rows;
 * any other phase or page < 0 only counts. When a phase OFF_FA row pass follows
 * roster_count, g_rc.fa is the final free agent count from the pre-pass and the
 * release ords are right; any other use recomputes the counts from scratch. */
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
                    if (team_managed(buf + toff[1], tlen[1]))
                        star_cell(r->cells[1]);
                    draft_pos(buf + toff[1], tlen[1], (const uint8_t *)nm, nname,
                              r->cells[2]);
                    put_cell(r->cells[3], nm, nname);
                    r->ncells = 4;
                }
            } else {
                uint32_t ord = g_rc.fa++;
                int s = phase == OFF_FA ? row_slot(ord, page) : -1;
                if (s >= 0) {
                    Row *r = &g_rows[s];
                    team_disp(buf + toff[1], tlen[1], r->cells[0]);
                    if (team_managed(buf + toff[1], tlen[1]))
                        star_cell(r->cells[0]);
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
                    if (team_managed(buf + toff[1], tlen[1]))
                        star_cell(r->cells[0]);
                    put_cell(r->cells[1], nm, xl);
                    team_disp(buf + toff[j], tlen[j], r->cells[2]);
                    r->ncells = 3;
                }
                if (sb >= 0) {
                    Row *r = &g_rows[sb];
                    int yl = join_toks(buf, toff, tlen, j + 1, n, nm);
                    team_disp(buf + toff[j], tlen[j], r->cells[0]);
                    if (team_managed(buf + toff[j], tlen[j]))
                        star_cell(r->cells[0]);
                    put_cell(r->cells[1], nm, yl);
                    team_disp(buf + toff[1], tlen[1], r->cells[2]);
                    r->ncells = 3;
                }
            }
        } else if (n >= 3 && tok_eq(buf + toff[0], tlen[0], "REL", 0)) {
            uint32_t ord2 = g_fabase + g_rc.rel;    /* free agent rows, then releases */
            int s = phase == OFF_FA ? row_slot(ord2, page) : -1;
            int nl = join_toks(buf, toff, tlen, 2, n, nm);
            g_rc.rel++;
            if (s >= 0) {
                Row *r = &g_rows[s];
                team_disp(buf + toff[1], tlen[1], r->cells[0]);
                if (team_managed(buf + toff[1], tlen[1]))
                    star_cell(r->cells[0]);
                put_cell(r->cells[1], (const uint8_t *)nm, nl);
                strcpy(r->cells[2], "RELEASED");
                r->ncells = 3;
            }
        }
    }
    fclose(f);
}

/* ---------------- categories ---------------- */

/* the value of a category over the 25 totals t and WAR10 war10 (career entry or SEASLINE line);
 * the award kinds are not totals and are read by cat_value */
static uint32_t tot_value(const uint32_t *t, int32_t war10, const CatDef *c)
{
    switch (c->kind) {
    case CK_AVG: return avg_of(t);
    case CK_ERA: return era100_of(t);
    case CK_WAR: return (uint32_t)war10;
    default: return t[c->idx];
    }
}

static uint32_t cat_value(const Entry *e, const CatDef *c)
{
    if (c->kind == CK_AW0)
        return e->awards[0];
    if (c->kind == CK_AW3)
        return e->awards[3];
    return tot_value(e->tot, e->war10, c);
}

/* career qualifiers (C7 and C13.3) */
static int cat_qualifies(const Entry *e, const CatDef *c)
{
    switch (c->kind) {
    case CK_COUNT:
    case CK_IP: return e->tot[c->idx] > 0;
    case CK_AVG: return e->tot[1] >= 3000;
    case CK_ERA: return e->tot[19] >= 4500;
    case CK_AW0:
    case CK_AW3: return cat_value(e, c) > 0;
    default: return 1;
    }
}

/* SEASON and BY YEAR qualifiers (C13.3, dynview.season_qualifies): AVG needs AB > 0 and
 * AB + BB >= 502; ERA needs OUTS >= 486; WAR needs G > 0; counts and IP need value > 0 */
static int season_qualifies(const Line *ln, const CatDef *c)
{
    switch (c->kind) {
    case CK_AVG: return ln->tot[T_AB] > 0 && ln->tot[T_AB] + ln->tot[T_BB] >= 502;
    case CK_ERA: return ln->tot[T_OUTS] >= 486;
    case CK_WAR: return ln->tot[T_G] > 0;
    default: return tot_value(ln->tot, ln->war10, c) > 0;
    }
}

static void cat_format(const CatDef *c, uint32_t v, char *dst)
{
    switch (c->kind) {
    case CK_AVG: fmt_avg((int32_t)v, dst); return;
    case CK_ERA: fmt_era100((int32_t)v, dst); return;
    case CK_WAR: fmt_war10((int32_t)v, dst); return;
    case CK_IP: fmt_ip(v, dst); return;
    default: fmt_count((int32_t)v, dst); return;
    }
}

/* ---------------- top-K list scans ---------------- */

/* the filter label texts (C53): 'HALL OF FAME: ' + label when the cat is not ALL */
static const char *const HOF_FILTER_LABELS[N_HOF_FILTERS] = {
    "ALL", "P", "C", "1B", "2B", "3B", "SS", "OF", "DH" };

/* one-byte hof_match table (C53): bit set = the entry of pitcher p (0 / 1) and pos1
 * pos (0..15) shows under filter f */
static uint8_t HOF_MATCH[N_HOF_FILTERS][2][16];

/* fill HOF_MATCH from the Python rules: ALL everything, P any pitcher, else a batter
 * whose pos1 is one of the filter's positions (a pitcher never matches a position) */
static void hof_match_init(void)
{
    static const uint8_t poss[N_HOF_FILTERS][4] = {
        { 255, 255, 255, 255 },       /* ALL: everything (fill below) */
        { 255, 255, 255, 255 },       /* P: any pitcher */
        { 1, 255, 255, 255 },         /* C */
        { 2, 255, 255, 255 },         /* 1B */
        { 3, 255, 255, 255 },         /* 2B */
        { 4, 255, 255, 255 },         /* 3B */
        { 5, 255, 255, 255 },         /* SS */
        { 6, 7, 8, 255 },             /* OF */
        { 9, 255, 255, 255 }          /* DH */
    };
    int f, p, pos, k;
    uint8_t hit;
    for (f = 0; f < N_HOF_FILTERS; f++) {
        for (p = 0; p < 2; p++) {
            for (pos = 0; pos < 16; pos++) {
                hit = 0;
                if (f == 0)
                    hit = 1;
                else if (f == HOF_F_P)
                    hit = (uint8_t)p;
                else if (!p) {
                    for (k = 0; k < 4 && !hit; k++)
                        if (poss[f][k] != 255 && poss[f][k] == (uint8_t)pos)
                            hit = 1;
                }
                HOF_MATCH[f][p][pos] = hit;
            }
        }
    }
}

/* hof_match (C53): f 0 always 1, f 1 any pitcher, else a batter at one of the filter
 * positions (the prebuilt HOF_MATCH table; pos1 over 15 never matches) */
static int hof_match(int f, const Entry *e)
{
    int p = e->pitcher != 0;
    if (f == 0)
        return 1;
    if (f == HOF_F_P)
        return p;
    return e->pos1 < 16 ? HOF_MATCH[f][p][e->pos1] : 0;
}

/* HoF: status 3 by (hof_season desc, index asc), the filter applied before the
 * LIST_MAX cut (C53) */
static void hof_scan(List *b, int f)
{
    uint32_t i;
    Entry e;
    b->n = 0;
    for (i = 0; i < n_entries(); i++) {
        read_entry(&e, i);
        if (e.status == STATUS_HOF && hof_match(f, &e))
            list_add_desc(b, (int32_t)e.hof_season, i);
    }
}

/* career leaders: value desc (ERA asc), index asc; g_lead_active keeps only STATUS_ACTIVE
 * entries (C54, filtered before the LIST_MAX cut) */
static void leaders_scan(List *b, int cat)
{
    uint32_t i;
    Entry e;
    const CatDef *c = &CAREER_CATS[cat];
    b->n = 0;
    for (i = 0; i < n_entries(); i++) {
        read_entry(&e, i);
        if (g_lead_active && e.status != STATUS_ACTIVE)
            continue;
        if (cat_qualifies(&e, c)) {
            if (c->kind == CK_ERA)
                list_add_asc(b, (int32_t)cat_value(&e, c), i);
            else
                list_add_desc(b, (int32_t)cat_value(&e, c), i);
        }
    }
}

/* ---------------- SEASLINE.DAT (C13.2): streamed 80 B lines, never all in memory ---------------- */

/* SEASLINE.DAT of g_lgdir, its 16 B header checked like load_lines (not 'SL', version 1, byte 3
 * nonzero or line size other than 80: NULL; a short header too). The stream is left at line 0 */
static FILE *seasline_open(void)
{
    char path[600];
    uint8_t hd[SEASLINE_HDR];
    FILE *f;
    path_join(path, g_lgdir, SEASLINE_FILE);
    f = fopen(path, "rb");
    if (!f)
        return NULL;
    if (fread(hd, 1, SEASLINE_HDR, f) != SEASLINE_HDR || hd[0] != 'S' || hd[1] != 'L'
        || hd[2] != SEASLINE_VERSION || hd[3] != 0
        || (hd[4] | (hd[5] << 8)) != SEASLINE_REC) {
        fclose(f);
        return NULL;
    }
    return f;
}

/* one 80 B line (read_line): the stable fields and the TOTALS */
static void line_decode(const uint8_t *r, Line *ln)
{
    int k;
    ln->entry = (uint16_t)(r[0] | (r[1] << 8));
    ln->season = (uint16_t)(r[2] | (r[3] << 8));
    ln->team = r[4];
    ln->pitcher = r[5] & 1;
    ln->age = r[6];
    ln->pos1 = r[7];
    ln->face = (uint16_t)(r[8] | (r[9] << 8));
    ln->hand = r[10];
    ln->dev = r[11];
    for (k = 0; k < 9; k++)
        ln->ratings[k] = r[12 + k];
    for (k = 0; k < NUM_TOT; k++)
        ln->tot[k] = (uint32_t)(r[22 + 2 * k] | (r[23 + 2 * k] << 8));
    ln->war10 = (int16_t)(r[72] | (r[73] << 8));
}

/* the next whole line of f into ln; 0 at the end, a short tail line is dropped */
static int line_next(FILE *f, Line *ln)
{
    uint8_t rec[SEASLINE_REC];
    if (fread(rec, 1, SEASLINE_REC, f) != SEASLINE_REC)
        return 0;
    line_decode(rec, ln);
    return 1;
}

/* the BY YEAR season when none is chosen (C13.3, dynview.default_year): the newest season with
 * lines, else the newest season recorded */
static int32_t default_year(void)
{
    FILE *f = seasline_open();
    Line ln;
    int32_t best = g_hdr_seasons;
    int any = 0;
    if (!f)
        return best;
    while (line_next(f, &ln)) {
        if (!any || ln.season > best) {
            best = ln.season;
            any = 1;
        }
    }
    fclose(f);
    return best;
}

/* the BY YEAR season of st (dynview.leaders_year): its year, or the default season at 0 */
static int32_t leaders_year(State st)
{
    return st.year ? st.year : default_year();
}

/* the nearest season with lines after cur (newer) or before it (older), into *out (dynview.step's
 * '+' and '-'); 1 when there is one */
static int season_near(int32_t cur, int newer, int32_t *out)
{
    FILE *f = seasline_open();
    Line ln;
    int found = 0;
    if (!f)
        return 0;
    while (line_next(f, &ln)) {
        int32_t sn = ln.season;
        if (newer ? sn > cur : sn < cur) {
            if (!found || (newer ? sn < *out : sn > *out)) {
                *out = sn;
                found = 1;
            }
        }
    }
    fclose(f);
    return found;
}

/* the SEASON order (dynview.season_order): value desc (ERA asc), then season asc, then entry asc */
static int sitem_before(const SItem *a, const SItem *b, int asc)
{
    if (a->val != b->val)
        return asc ? a->val < b->val : a->val > b->val;
    if (a->season != b->season)
        return a->season < b->season;
    return a->entry < b->entry;
}

/* insert one leader into g_sbuf, keeping the top SEASON_MAX in sitem_before order */
static void sitem_add(int asc, int32_t val, uint16_t season, uint16_t entry, uint8_t team)
{
    SItem it;
    int i, n = g_sn;
    it.val = val;
    it.season = season;
    it.entry = entry;
    it.team = team;
    if (n == SEASON_MAX && !sitem_before(&it, &g_sbuf[n - 1], asc))
        return;
    i = n < SEASON_MAX ? n : n - 1;
    while (i > 0 && sitem_before(&it, &g_sbuf[i - 1], asc)) {
        g_sbuf[i] = g_sbuf[i - 1];
        i--;
    }
    g_sbuf[i] = it;
    if (n < SEASON_MAX)
        g_sn++;
}

/* SEASON leaders (C13.3, dynview.season_order) over the SEASLINE lines, all of them or only the
 * lines of season when by_year, into g_sbuf. *seen gets the number of lines of the season (any
 * line when not by_year); returns the leader count */
static int season_scan(const CatDef *c, int by_year, int32_t season, int *seen)
{
    FILE *f = seasline_open();
    Line ln;
    int asc = c->kind == CK_ERA;
    *seen = 0;
    g_sn = 0;
    if (!f)
        return 0;
    while (line_next(f, &ln)) {
        if (by_year && ln.season != season)
            continue;
        (*seen)++;
        if (season_qualifies(&ln, c))
            sitem_add(asc, (int32_t)tot_value(ln.tot, ln.war10, c), ln.season, ln.entry,
                      ln.team);
    }
    fclose(f);
    return g_sn;
}

/* the PLAYER CARD lines of entry (C13.5, dynview.card_lines): their offsets in season order (stable,
 * file order within a season) into g_card, at most CARD_MAX */
static void card_collect(int32_t entry)
{
    FILE *f = seasline_open();
    Line ln;
    long off = SEASLINE_HDR;
    g_ncard = 0;
    if (!f)
        return;
    while (line_next(f, &ln)) {
        if ((int32_t)ln.entry == entry && g_ncard < CARD_MAX) {
            CardLine cl;
            int i = g_ncard;
            cl.off = (uint32_t)off;
            cl.season = ln.season;
            while (i > 0 && g_card[i - 1].season > cl.season) {
                g_card[i] = g_card[i - 1];
                i--;
            }
            g_card[i] = cl;
            g_ncard++;
        }
        off += SEASLINE_REC;
    }
    fclose(f);
}

/* the SEASLINE line at offset off (a card_collect offset) into ln; 1 when read */
static int card_line(uint32_t off, Line *ln)
{
    FILE *f = seasline_open();
    int ok = 0;
    if (!f)
        return 0;
    if (fseek(f, (long)off, SEEK_SET) == 0)
        ok = line_next(f, ln);
    fclose(f);
    return ok;
}

/* the postseason totals of entry (C26, dynview.post_totals) from the BOXSCORE.DAT player
 * rows: idx == entry and flags != 4 (a flags 4 record is a round header, not a player row).
 * Batting rows (bit1 clear) sum AB H RBI HR SB; pitching rows OUTS (IP10 = whole innings
 * * 10 + thirds, so outs = 3 * (IP10 / 10) + IP10 % 10), ER and PSO. The distinct
 * (season, g) pairs are one u32 key each, (season << 8) | g. g_post_games = the number of
 * distinct keys (also the G total), g_post_tot the 25-int TOTALS sums, every other field 0.
 * Returns g_post_games (0 when the entry has no player row); a missing BOXSCORE.DAT
 * counts as no rows. */
static int post_totals(int32_t entry)
{
    char path[600];
    FILE *f;
    uint8_t rb[16];
    int had_any = 0;
    if (g_post_entry == entry)
        return g_post_games;
    memset(g_post_tot, 0, sizeof g_post_tot);
    g_post_games = 0;
    g_post_pairs = 0;
    do {
        uint16_t season, idx;
        uint8_t flags, pitch;
        const uint8_t *st;
        uint32_t key;
        int k;
        path_join(path, g_lgdir, "BOXSCORE.DAT");
        f = fopen(path, "rb");
        if (!f)
            break;
        while (fread(rb, 1, sizeof rb, f) == sizeof rb) {
            season = (uint16_t)(rb[0] | ((uint16_t)rb[1] << 8));
            idx = (uint16_t)(rb[4] | ((uint16_t)rb[5] << 8));
            if (idx != (uint16_t)entry)
                continue;
            flags = rb[3];
            if (flags == 4)
                continue;
            if (!had_any)
                had_any = 1;
            key = ((uint32_t)season << 8) | rb[2];
            for (k = 0; k < g_post_pairs && g_post_pair[k] != key; k++)
                ;
            if (k == g_post_pairs && g_post_pairs < POST_PAIR_MAX) {
                g_post_pair[g_post_pairs++] = key;
                g_post_games++;
            }
            st = rb + 8;
            pitch = flags & 2;
            if (pitch) {
                g_post_tot[19] += 3u * ((uint32_t)st[0] / 10u) + (uint32_t)(st[0] % 10);
                g_post_tot[20] += st[3];
                g_post_tot[23] += st[6];
            } else {
                g_post_tot[1] += st[0];
                g_post_tot[2] += st[2];
                g_post_tot[7] += st[3];
                g_post_tot[5] += st[4];
                g_post_tot[10] += st[7];
            }
        }
        fclose(f);
    } while (0);
    g_post_tot[0] = (uint32_t)g_post_games;
    g_post_entry = entry;
    return g_post_games;
}

/* insert one entry into the top POST_MAX in post order (C39): value descending,
 * then entry ascending */
static void post_top_add(uint32_t val, uint16_t entry, uint32_t games)
{
    int i;
    if (g_post_n == POST_MAX && (val < g_post_top[POST_MAX - 1].val
                                 || (val == g_post_top[POST_MAX - 1].val
                                     && entry > g_post_top[POST_MAX - 1].entry)))
        return;
    i = g_post_n < POST_MAX ? g_post_n : POST_MAX - 1;
    while (i > 0 && (val > g_post_top[i - 1].val
                     || (val == g_post_top[i - 1].val
                         && entry < g_post_top[i - 1].entry))) {
        g_post_top[i] = g_post_top[i - 1];
        i--;
    }
    g_post_top[i].val = val;
    g_post_top[i].entry = entry;
    g_post_top[i].games = (uint16_t)(games > 0xffffu ? 0xffffu : games);
    if (g_post_n < POST_MAX)
        g_post_n++;
}

/* POSTSEASON LEADERS of cat (C39, dynview.post_order): ONE pass over BOXSCORE.DAT
 * into the per-entry accumulators (games through the entry's last counted (season, g)
 * key, the records of one game being contiguous), then the top POST_MAX into
 * g_post_top. The scan is cached like the other scans; DYNVIEW writes no
 * BOXSCORE.DAT, so there is nothing else to invalidate. */
static int post_scan(const CatDef *c)
{
    char path[600];
    FILE *f;
    uint8_t rb[16];
    int vi = c->idx, k;
    if (g_post_cache == vi)
        return g_post_n;
    memset(g_post_acc, 0, sizeof g_post_acc);
    g_post_n = 0;
    path_join(path, g_lgdir, "BOXSCORE.DAT");
    f = fopen(path, "rb");
    if (f) {
        while (fread(rb, 1, sizeof rb, f) == sizeof rb) {
            uint16_t season = (uint16_t)(rb[0] | ((uint16_t)rb[1] << 8));
            uint16_t idx = (uint16_t)(rb[4] | ((uint16_t)rb[5] << 8));
            uint8_t flags = rb[3];
            PostAcc *a;
            const uint8_t *st;
            if (idx >= POST_ENTRY_MAX || flags == 4)
                continue;
            a = &g_post_acc[idx];
            /* a player row whose key differs from the entry's last counted one is the
             * first record of another game (the records of a game are contiguous) */
            if (!a->has_last || a->last_season != season || a->last_g != rb[2]) {
                a->has_last = 1;
                a->last_season = season;
                a->last_g = rb[2];
                a->g++;
            }
            st = rb + 8;
            if (flags & 2) {
                if (vi == 19)
                    a->val += 3u * ((uint32_t)st[0] / 10u) + (uint32_t)(st[0] % 10);
                else if (vi == 23)
                    a->val += st[6];
            } else if (vi == 2) {
                a->val += st[2];
            } else if (vi == 7) {
                a->val += st[3];
            } else if (vi == 5) {
                a->val += st[4];
            } else if (vi == 10) {
                a->val += st[7];
            }
        }
        fclose(f);
    }
    g_post_cache = vi;
    /* the category's value index (TOTALS order): 0 G = the game count, 2 H, 5 HR,
     * 7 RBI, 10 SB, 19 OUTS (IP), 23 PSO (SO); the other POST_CATS never reach here */
    for (k = 0; k < POST_ENTRY_MAX; k++) {
        PostAcc *a = &g_post_acc[k];
        uint32_t val;
        if (!a->has_last)
            continue;
        switch (vi) {
        case 0: val = a->g; break;
        case 2: case 5: case 7: case 10: case 19: case 23: val = a->val; break;
        default: continue;                  /* not a POST_CATS index: no value */
        }
        if (val > 0)
            post_top_add(val, (uint16_t)k, a->g);
    }
    return g_post_n;
}

/* the file WANT (upper case) of dir: DOS names are case-blind, the host finds it in any case;
 * NULL when there is none (dynview.find_upper) */
static FILE *open_upper(const char *dir, const char *want)
{
#ifdef __WATCOMC__
    char path[300];
    path_join(path, dir, want);
    return fopen(path, "rb");
#else
    char path[300];
    DIR *dirp = opendir(dir);
    struct dirent *de;
    FILE *f = NULL;
    if (!dirp)
        return NULL;
    while ((de = readdir(dirp)) != NULL) {
        if (tok_eq((const uint8_t *)de->d_name, (int)strlen(de->d_name), want, 1)) {
            path_join(path, dir, de->d_name);
            f = fopen(path, "rb");
            break;
        }
    }
    closedir(dirp);
    return f;
#endif
}

/* PORTRAIT.ANM frame k into g_portrait (create's portrait() rules, dynview.portrait_stock): the
 * frame must be stored (clen 0) at PORTRAIT_W x PORTRAIT_H and fit the file; the frames before it
 * are skipped by their 12 B headers. 1 when it was read */
static int portrait_stock(int32_t k)
{
    FILE *f = open_upper(g_anms, "PORTRAIT.ANM");
    uint8_t hd[12], head[2];
    long size = 0, p = 2;
    uint32_t count;
    int32_t i;
    int ok = 0;
    if (!f)
        return 0;
    if (fseek(f, 0L, SEEK_END) != 0 || (size = ftell(f)) < 0 || fseek(f, 0L, SEEK_SET) != 0
        || fread(head, 1, 2, f) != 2) {
        fclose(f);
        return 0;
    }
    count = (uint32_t)(head[0] | (head[1] << 8));
    if (k >= (int32_t)count) {
        fclose(f);
        return 0;
    }
    for (i = 0;; i++) {
        int h, w, clen;
        if (fseek(f, p, SEEK_SET) != 0 || fread(hd, 1, 12, f) != 12)
            break;
        h = hd[2] | (hd[3] << 8);
        w = hd[4] | (hd[5] << 8);
        clen = hd[10] | (hd[11] << 8);
        if (i < k) {
            p += 12 + (clen == 0 ? (long)h * w : (long)clen);
            continue;
        }
        if (clen == 0 && w == PORTRAIT_W && h == PORTRAIT_H && p + 12 + (long)h * w <= size
            && fseek(f, p + 12, SEEK_SET) == 0
            && fread(g_portrait, 1, PORTRAIT_W * PORTRAIT_H, f) == PORTRAIT_W * PORTRAIT_H)
            ok = 1;
        break;
    }
    fclose(f);
    return ok;
}

/* OLDPORT.ANM frame k into g_portrait (dynview.portrait_old): no count word, frame k at
 * k * OLD_FRAME, a 12 B header with clen 0 and PORTRAIT_W x PORTRAIT_H, then the pixels */
static int portrait_old(int32_t k)
{
    FILE *f = open_upper(g_game, "OLDPORT.ANM");
    uint8_t hd[12];
    int h, w, clen, ok = 0;
    if (!f)
        return 0;
    if (fseek(f, (long)k * OLD_FRAME, SEEK_SET) == 0 && fread(hd, 1, 12, f) == 12) {
        h = hd[2] | (hd[3] << 8);
        w = hd[4] | (hd[5] << 8);
        clen = hd[10] | (hd[11] << 8);
        if (clen == 0 && w == PORTRAIT_W && h == PORTRAIT_H
            && fread(g_portrait, 1, PORTRAIT_W * PORTRAIT_H, f) == PORTRAIT_W * PORTRAIT_H)
            ok = 1;
    }
    fclose(f);
    return ok;
}

/* the portrait of a face into g_portrait (dynview.portrait_of, C13.5): stock frames below OLD_FACE,
 * OLDPORT frames up to OLD_FACE_END; 1 when there is one */
static int portrait_of(int face)
{
    if (face < OLD_FACE)
        return portrait_stock(face);
    if (face < OLD_FACE_END)
        return portrait_old(face - OLD_FACE);
    return 0;
}

/* milestones (award records skipped): season desc, file position asc */
static void ms_scan(List *b)
{
    int32_t i;
    b->n = 0;
    for (i = 0; i < g_nms; i++) {
        if (g_ms[i].kind >= AWARD_KIND_MIN)
            continue;
        list_add_desc(b, (int32_t)g_ms[i].season, (uint32_t)i);
    }
}

/* ---------------- MILESTONES WATCH (C27) ---------------- */

/* the MILESTONE_CAREER marks: (kind, TOTALS key index, mark) */
static const uint8_t WATCH_KIND[] = { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
                                      13, 14, 15, 16, 17 };
static const uint8_t WATCH_KEY[] = { 2, 2, 5, 5, 5, 5, 5, 7, 7, 10, 13, 13,
                                     23, 23, 23, 15, 15 };
static const uint16_t WATCH_MARK[] = { 2000, 3000, 300, 400, 500, 600, 700, 1500, 2000,
                                       500, 200, 300, 2000, 3000, 4000, 300, 400 };
#define WATCH_NMARKS 17
/* the WATCH_MARK indexes of the distinct keys, first occurrence per key (7 keys:
 * H, HR, RBI, SB, W, PSO, SV); watch_items makes one item per key */
static const uint8_t WATCH_KEYS0[7] = { 0, 2, 7, 9, 10, 12, 15 };
#define WATCH_NKEYS 7
/* the WATCH MARK label of each kind; PSO shown as SO */
static const char *const WATCH_LABEL[] = {
    "H", "H", "HR", "HR", "HR", "HR", "HR", "RBI", "RBI", "SB", "W", "W",
    "SO", "SO", "SO", "SV", "SV" };

/* watch_items: the active players within 10% of an unreached mark. For each entry and
 * stat key the lowest mark of that key with now < mark is the item's mark; kept when
 * now * 10 >= mark * 9. Sorted by (need * 1000 / mark, need, entry, kind) ascending
 * (32-bit need per mille; the C keys are need < 1000 so the product fits 32 bits) */
static int watch_lt(const WatchItem *a, const WatchItem *b)
{
    if (a->need * 1000u / a->mark != b->need * 1000u / b->mark)
        return a->need * 1000u / a->mark < b->need * 1000u / b->mark;
    if (a->need != b->need)
        return a->need < b->need;
    if (a->entry != b->entry)
        return a->entry < b->entry;
    return a->kind < b->kind;
}

static void watch_scan(void)
{
    uint32_t i;
    int32_t j;
    g_nwatch = 0;
    for (i = 0; i < n_entries(); i++) {
        Entry e;
        WatchItem best[WATCH_NMARKS];
        int nbest = 0;
        read_entry(&e, i);
        if (e.status != STATUS_ACTIVE)
            continue;
        for (j = 0; j < WATCH_NKEYS; j++) {
            int ji = WATCH_KEYS0[j];
            uint32_t now = e.tot[WATCH_KEY[ji]];
            uint32_t lowest = 0;
            int have = 0, k, lk = ji;
            WatchItem it;
            /* the lowest mark of this key with now < mark; skip when none */
            for (k = 0; k < WATCH_NMARKS; k++) {
                if (WATCH_KEY[k] == WATCH_KEY[ji] && now < WATCH_MARK[k]
                    && (!have || WATCH_MARK[k] < lowest)) {
                    lowest = WATCH_MARK[k];
                    lk = k;
                    have = 1;
                }
            }
            if (!have)
                continue;
            if (now >= lowest)
                continue;
            if (now * 10u < lowest * 9u)
                continue;
            it.need = lowest - now;
            it.mark = lowest;
            it.now = now;
            it.kind = WATCH_KIND[lk];      /* the kind of the chosen mark */
            it.key = WATCH_KEY[ji];
            it.entry = i;
            best[nbest++] = it;
        }
        for (j = 0; j < nbest; j++) {
            int32_t lo = 0, hi = g_nwatch, mid;
            if (g_nwatch >= WATCH_MAX
                && !watch_lt(&best[j], &g_watch[g_nwatch - 1]))
                continue;
            while (lo < hi) {
                mid = (lo + hi) / 2;
                if (watch_lt(&g_watch[mid], &best[j]))
                    lo = mid + 1;
                else
                    hi = mid;
            }
            if (lo >= WATCH_MAX)
                continue;
            if (g_nwatch < WATCH_MAX)
                g_nwatch++;
            if (g_nwatch - 1 > lo)
                memmove(&g_watch[lo + 1], &g_watch[lo],
                        (size_t)(g_nwatch - 1 - lo) * sizeof(g_watch[0]));
            g_watch[lo] = best[j];
        }
    }
}

/* FIND PLAYER scan (C50): every entry with status in (1, 2, 3) whose one_field(name[0:12])
 * ASCII upper case starts with find_q, in (last upper, first upper, index) order, capped at
 * FIND_LIST. g_find holds that many items. *seen gets the full list length (for the row
 * count); returns the held count. A non-NULL *order (page >= 0) takes up to ROWS_PER_PAGE
 * items of page into *order rows. */
static int find_lt(const FindItem *a, const FindItem *b)
{
    int c;
    c = strcmp((const char *)a->last_u, (const char *)b->last_u);
    if (c)
        return c < 0;
    c = strcmp((const char *)a->first_u, (const char *)b->first_u);
    if (c)
        return c < 0;
    return a->entry < b->entry;
}

/* how many characters of the query the last name starts with (0 when it is not a match) */
static int find_prefix(const uint8_t *last_u, const char *q)
{
    int i;
    for (i = 0; q[i]; i++) {
        if (last_u[i] != (uint8_t)q[i])
            return 0;
    }
    return 1;
}

static int find_scan(const char *q, int page, Row *order, int *seen)
{
    uint32_t i;
    Entry e;
    int32_t n;
    char last[13], first[9];
    uint8_t last_u[13], first_u[9];
    if (!q[0]) {
        *seen = 0;
        return 0;
    }
    (void)page;
    (void)order;
    n = 0;
    for (i = 0; i < n_entries(); i++) {
        FindItem it;
        int kl, kf;
        read_entry(&e, i);
        if (e.status != STATUS_ACTIVE && e.status != STATUS_RETIRED && e.status != STATUS_HOF)
            continue;
        field_of(e.name, 12, last);
        field_of(e.name + 12, 8, first);
        for (kl = 0; last[kl] && kl < 12; kl++)
            last_u[kl] = ascii_up((uint8_t)last[kl]);
        last_u[kl] = 0;
        if (!find_prefix(last_u, q))
            continue;
        for (kf = 0; first[kf] && kf < 8; kf++)
            first_u[kf] = ascii_up((uint8_t)first[kf]);
        first_u[kf] = 0;
        it.entry = i;
        memcpy(it.last_u, last_u, (size_t)kl + 1);
        memcpy(it.first_u, first_u, (size_t)kf + 1);
        it.pad[0] = it.pad[1] = 0;
        if (n >= FIND_LIST && !find_lt(&it, &g_find[n - 1]))
            continue;
        {
            int32_t j = n < FIND_LIST ? n : n - 1;
            while (j > 0 && find_lt(&it, &g_find[j - 1])) {
                g_find[j] = g_find[j - 1];
                j--;
            }
            g_find[j] = it;
        }
        if (n < FIND_LIST)
            n++;
    }
    g_nfind = n;
    *seen = (int)n;
    return (int)n;
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

/* ---------------- SEASON AWARDS (C7 award and leader records) ---------------- */

static const char *AWARD_POS[10] = {
    "", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH" };
static const char *AWARD_FALLBACK[6] = {
    "AL MVP", "AL CY YOUNG", "AL ROOKIE", "NL MVP", "NL CY YOUNG", "NL ROOKIE" };
static const char *LEADER_CATS[9] = {
    "BA", "HR", "RBI", "H", "SB", "W", "ERA", "SO", "SV" };

/* an award record kind: 64..83 (AL) or 96..115 (NL) */
static int award_kind(int kind)
{
    return (kind >= 64 && kind <= 83) || (kind >= 96 && kind <= 115);
}

/* k = kind - 64 (AL) or kind - 96 (NL) */
static int award_k(int kind)
{
    return kind >= 96 ? kind - 96 : kind - 64;
}

/* award_label: 'AL MVP', 'NL GLOVE CF', 'AL SLUGGER DH' and so on */
static void award_label(int kind, char *dst)
{
    int k = award_k(kind);
    strcpy(dst, kind >= 96 ? "NL " : "AL ");
    if (k == 0)
        strcat(dst, "MVP");
    else if (k == 1)
        strcat(dst, "CY YOUNG");
    else if (k == 2)
        strcat(dst, "ROOKIE");
    else if (k <= 10) {
        strcat(dst, "GLOVE ");
        strcat(dst, AWARD_POS[k - 2]);
    } else {
        strcat(dst, "SLUGGER ");
        strcat(dst, AWARD_POS[k - 10]);
    }
}

/* award_value: the stored u16 read as s16; WAR10 for MVP, CY and ROOKIE, fp1000 for a
 * GLOVE, bat100 for a SLUGGER (runs, v / 10 truncated toward zero) */
static void award_value(int kind, uint16_t value, char *dst)
{
    int k = award_k(kind);
    int16_t v = (int16_t)value;
    if (k <= 2) {
        fmt_war10(v, dst);
        strcat(dst, " WAR");
    } else if (k <= 10) {
        fmt_avg(v, dst);
        strcat(dst, " FLD");
    } else {
        fmt_war10(v / 10, dst);
        strcat(dst, " RUNS");
    }
}

/* a leader record kind: 128..136 (AL) or 160..168 (NL) */
static int leader_kind(int kind)
{
    return (kind >= 128 && kind <= 136) || (kind >= 160 && kind <= 168);
}

/* k = kind - 128 (AL) or kind - 160 (NL), an index into LEADER_CATS */
static int leader_k(int kind)
{
    return kind >= 160 ? kind - 160 : kind - 128;
}

/* leader_label: 'AL BA LEADER', 'NL ERA LEADER' and so on */
static void leader_label(int kind, char *dst)
{
    strcpy(dst, kind >= 160 ? "NL " : "AL ");
    strcat(dst, LEADER_CATS[leader_k(kind)]);
    strcat(dst, " LEADER");
}

/* leader_value: the stored u16 with no sign: BA as fp1000, ERA as x100 (d.dd), else a
 * count */
static void leader_value(int kind, uint16_t value, char *dst)
{
    int k = leader_k(kind);
    if (k == 0) {
        fmt_avg((int32_t)value, dst);
        strcat(dst, " BA");
    } else if (k == 6) {
        fmt_era100((int32_t)value, dst);
        strcat(dst, " ERA");
    } else {
        fmt_count((int32_t)value, dst);
        strcat(dst, " ");
        strcat(dst, LEADER_CATS[k]);
    }
}

/* the award and leader records of season into g_arec: the AWARD_MAX first in (kind,
 * file position) order; returns how many. Equal kinds keep file order (insertion). */
static int award_recs(long season)
{
    int32_t i;
    int n = 0, j;
    for (i = 0; i < g_nms; i++) {
        MsRec *rec = &g_ms[i];
        if (rec->season != season || (!award_kind(rec->kind) && !leader_kind(rec->kind)))
            continue;
        if (n == AWARD_MAX && rec->kind >= g_arec[n - 1].kind)
            continue;               /* after the last kept record */
        j = n < AWARD_MAX ? n : n - 1;
        while (j > 0 && g_arec[j - 1].kind > rec->kind) {
            g_arec[j] = g_arec[j - 1];
            j--;
        }
        g_arec[j] = *rec;
        if (n < AWARD_MAX)
            n++;
    }
    return n;
}

/* SEASON AWARDS rows of season into g_awd (dynview.awards_rows); returns the count:
 * the award and leader records, else the six winners and the GG SS row of a season
 * recorded before the award records, else one message row past the history table */
static int build_awards(long season)
{
    int n, k;
    n = award_recs(season);
    if (n > 0) {
        for (k = 0; k < n; k++) {
            Row *row = &g_awd[k];
            if (leader_kind(g_arec[k].kind)) {
                leader_label(g_arec[k].kind, row->cells[0]);
                leader_value(g_arec[k].kind, g_arec[k].value, row->cells[2]);
            } else {
                award_label(g_arec[k].kind, row->cells[0]);
                award_value(g_arec[k].kind, g_arec[k].value, row->cells[2]);
            }
            entry_name(g_arec[k].idx, 16, row->cells[1]);
            row->ncells = 3;
            g_awd_idx[k] = g_arec[k].idx;
        }
        return n;
    }
    if (season <= SEASON_COUNT) {
        SeasonEntry se;
        read_season(&se, (int)season);
        for (k = 0; k < 6; k++) {
            Row *row = &g_awd[k];
            strcpy(row->cells[0], AWARD_FALLBACK[k]);
            entry_name(se.awards[k], 16, row->cells[1]);
            row->cells[2][0] = 0;
            row->ncells = 3;
            g_awd_idx[k] = se.awards[k];
        }
        strcpy(g_awd[6].cells[0], "GG SS");
        strcpy(g_awd[6].cells[1], "NOT RECORDED");
        g_awd[6].cells[2][0] = 0;
        g_awd[6].ncells = 3;
        g_awd_idx[6] = -1;
        return 7;
    }
    strcpy(g_awd[0].cells[0], "NO AWARDS RECORDED");
    g_awd[0].ncells = 1;
    g_awd_idx[0] = -1;
    return 1;
}

/* ---------------- AWARD HISTORY (C28) ---------------- */

/* the rows of the award code a (cat L * 20 + k) into g_ah, at most AWHIST_MAX, with each
 * row's player entry in g_ah_idx (-1 for none); returns the row count (0: no row, the
 * caller shows 'NO WINNERS RECORDED'). Newest season first: the first file record of the
 * season with kind (64, 96)[L] + k gives the row; a season with no record of the kind
 * falls back to the season entry's winner aw[L * 3 + k] with value '' when the season is
 * in the table, k <= 2 and it has no award record of any kind (NO_AWARD gives no row);
 * every other season is skipped. */
static int build_awhist(long a)
{
    long L = a >= 20, k = a - L * 20, kind = (L ? 96 : 64) + k;
    int32_t season;
    int n = 0;
    g_ah_kind = kind;
    for (season = (long)g_hdr_seasons; season >= 1 && n < AWHIST_MAX; season--) {
        uint16_t idx = 0, value = 0;
        int32_t had = 0, fallback = 0;
        const MsRec *first = NULL;
        int32_t i;
        for (i = 0; i < g_nms; i++) {
            if (g_ms[i].season != season)
                continue;
            if (g_ms[i].kind == kind && !first)
                first = &g_ms[i];
            if (award_kind(g_ms[i].kind) || leader_kind(g_ms[i].kind))
                had = 1;
        }
        if (first) {
            idx = first->idx;
            value = first->value;
        } else if (k < 3 && season <= SEASON_COUNT && !had) {
            SeasonEntry se;
            if (!read_season(&se, (int)season))
                continue;
            idx = se.awards[L * 3 + k];
            if (idx == NO_AWARD)
                continue;
            fallback = 1;
        } else {
            continue;
        }
        g_ah[n].season = (uint16_t)season;
        g_ah[n].idx = idx;
        g_ah[n].value = value;
        g_ah[n].fallback = (uint8_t)fallback;
        g_ah_idx[n] = (idx >= n_entries() || idx == NO_AWARD) ? -1 : (int32_t)idx;
        n++;
    }
    return n;
}

/* the AWARD HISTORY row r (r < build_awhist's count) formatted into *row */
static void awhist_row(int r, Row *row)
{
    const AhItem *it = &g_ah[r];
    year_text((int32_t)it->season, row->cells[0]);
    entry_name(it->idx, 16, row->cells[1]);
    if (it->fallback)
        row->cells[2][0] = 0;
    else
        award_value((int)g_ah_kind, it->value, row->cells[2]);
    row->ncells = 3;
}

/* ---------------- SEASON STANDINGS (C2 season entry w_l) ---------------- */

/* the header rows: the league name for one division with games, else the short league name
 * and the division suffix. The divisions come in dynview.STAND_DIVS order (2 WEST, 3 CENTRAL,
 * 1 EAST) */
static const char *STAND_HEAD[2] = { "AMERICAN LEAGUE", "NATIONAL LEAGUE" };
static const char *STAND_SHORT[2] = { "AL", "NL" };
static const int STAND_DIV_NUM[3] = { 2, 3, 1 };
static const char *STAND_DIV_SUF[3] = { " WEST", " CENTRAL", " EAST" };

/* the team column of league-global id t: its MAJ display name, else 'TEAM t' (no star;
 * stand_name adds the C18 managed star) */
static void stand_name_plain(int t, char *dst)
{
    int i;
    for (i = 0; i < g_nteams; i++) {
        if (g_tlg[i] == t) {
            strcpy(dst, g_tdisp[i]);
            break;
        }
    }
    if (i == g_nteams)
        sprintf(dst, "TEAM %d", t);
}

/* stand_name with the C18 managed star (standings and series; the box score uses
 * stand_name_plain, as Python's box rows carry no star) */
static void stand_name(int t, char *dst)
{
    stand_name_plain(t, dst);
    if (id_managed(t))
        star_cell(dst);
}

/* standings order (dynview.standings_rows key): PCT desc, W desc, id asc; the PCT is
 * W * 1000 / (W + L) truncated, a long so that 255 * 1000 does not overflow 16 bits */
static int stand_before(const SeasonEntry *se, int a, int b)
{
    long pa = (long)se->wl[a][0] * 1000 / (se->wl[a][0] + se->wl[a][1]);
    long pb = (long)se->wl[b][0] * 1000 / (se->wl[b][0] + se->wl[b][1]);
    if (pa != pb)
        return pa > pb;
    if (se->wl[a][0] != se->wl[b][0])
        return se->wl[a][0] > se->wl[b][0];
    return a < b;
}

/* games behind from d = (leader W - W) + (L - leader L): '-', '4.0', '4.5', '-2.0' */
static void gb_text(int d, char *dst)
{
    int a = d < 0 ? -d : d;
    if (d == 0) {
        strcpy(dst, "-");
        return;
    }
    sprintf(dst, "%s%d%s", d < 0 ? "-" : "", a / 2, a % 2 ? ".5" : ".0");
}

/* the cells of a non-team row into g_stnd[n] (a header, a page-last blank, the message
 * row): ncells 6 blank cells, or the one message cell; the team id is STAND_NONE */
static int stand_plain_row(int n, const char *msg)
{
    Row *row = &g_stnd[n];
    int i;
    if (msg) {
        strcpy(row->cells[0], msg);
        row->ncells = 1;
    } else {
        for (i = 0; i < 6; i++)
            row->cells[i][0] = 0;
        row->ncells = 6;
    }
    g_stnd_tid[n] = STAND_NONE;
    return n + 1;
}

/* the cells of a team row into g_stnd[n], with its stable id in g_stnd_tid[n]; gb is the
 * row's doubled games behind (from the block's first row), held by the caller */
static int stand_team_row(const SeasonEntry *se, int n, int t, int gb)
{
    Row *row = &g_stnd[n];
    int w = se->wl[t][0], l = se->wl[t][1];
    long pct = (long)w * 1000 / (w + l);
    stand_name(t, row->cells[0]);
    sprintf(row->cells[1], "%d", w);
    sprintf(row->cells[2], "%d", l);
    fmt_avg((int32_t)pct, row->cells[3]);
    gb_text(gb, row->cells[4]);
    if (t == se->champion)
        strcpy(row->cells[5], "WS");
    else if (t == se->al_pennant || t == se->nl_pennant)
        strcpy(row->cells[5], "P");
    else
        row->cells[5][0] = 0;
    row->ncells = 6;
    g_stnd_tid[n] = (uint8_t)t;
    return n + 1;
}

/* the ids of one block sorted and the block's rows appended to g_stnd from row n (a blank
 * first when the header would fall on a page's last row): returns the next row index */
static int stand_block(const SeasonEntry *se, int n, const char *head, int *ids, int m)
{
    int i, j, t, gb;
    /* insertion sort: stand_before is a total order, so the result is exact */
    for (i = 1; i < m; i++) {
        t = ids[i];
        for (j = i; j > 0 && stand_before(se, t, ids[j - 1]); j--)
            ids[j] = ids[j - 1];
        ids[j] = t;
    }
    if (n % ROWS_PER_PAGE == ROWS_PER_PAGE - 1)
        n = stand_plain_row(n, NULL);     /* no header alone on a page's last row */
    {
        Row *row = &g_stnd[n];
        strcpy(row->cells[0], head);
        for (i = 1; i < 6; i++)
            row->cells[i][0] = 0;
        row->ncells = 6;
        g_stnd_tid[n] = STAND_NONE;
        n++;
    }
    for (i = 0; i < m; i++) {
        t = ids[i];
        gb = (se->wl[ids[0]][0] - se->wl[t][0]) + (se->wl[t][1] - se->wl[ids[0]][1]);
        n = stand_team_row(se, n, t, gb);
    }
    return n;
}

/* history.division_of (C12.7): the division of league-global id k in a season entry, 1 East,
 * 2 West, 3 Central, 0 none; a legacy entry (ndiv 0) has East for (k & 15) < 8, else West */
static int division_of(const SeasonEntry *se, int k)
{
    if (se->ndiv == 0)
        return (k & 15) < 8 ? 1 : 2;
    return (se->divmap[k / 2] >> (4 * (k & 1))) & 15;
}

/* SEASON STANDINGS rows of season into g_stnd (dynview.standings_rows); returns the count.
 * Per league the played teams (W + L > 0) are grouped by division: two or more divisions give
 * one block each in STAND_DIVS order under AL WEST and so on, one division one block under
 * the league name, none nothing. Past the history table or with no games in either league,
 * one message row. */
static int build_standings(long season)
{
    SeasonEntry se;
    char head[24];
    int lg, t, q, dv, shown, n, cnt[3], ids[3][16];
    if (season > SEASON_COUNT)
        return stand_plain_row(0, "NO STANDINGS RECORDED");
    n = 0;
    memset(&se, 0, sizeof se);
    read_season(&se, (int)season);
    for (lg = 0; lg < 2; lg++) {
        for (q = 0; q < 3; q++)
            cnt[q] = 0;
        for (t = lg * 16; t < lg * 16 + 16; t++) {
            if (se.wl[t][0] + se.wl[t][1] == 0)
                continue;
            dv = division_of(&se, t);
            for (q = 0; q < 3; q++)
                if (dv == STAND_DIV_NUM[q])
                    ids[q][cnt[q]++] = t;
        }
        shown = 0;
        for (q = 0; q < 3; q++)
            if (cnt[q] > 0)
                shown++;
        for (q = 0; q < 3; q++) {
            if (cnt[q] == 0)
                continue;
            if (shown >= 2)
                sprintf(head, "%s%s", STAND_SHORT[lg], STAND_DIV_SUF[q]);
            else
                strcpy(head, STAND_HEAD[lg]);
            n = stand_block(&se, n, head, ids[q], cnt[q]);
        }
    }
    if (n == 0)
        return stand_plain_row(0, "NO STANDINGS RECORDED");
    return n;
}

/* ---------------- WORLD SERIES (C7 third amendment records) ---------------- */

/* the first MILESTON.DAT record of season and kind (file order) into *idx and *value;
 * 0 when there is none */
static int ms_first(long season, int kind, uint16_t *idx, uint16_t *value)
{
    int32_t i;
    for (i = 0; i < g_nms; i++) {
        if (g_ms[i].season == season && g_ms[i].kind == kind) {
            *idx = g_ms[i].idx;
            *value = g_ms[i].value;
            return 1;
        }
    }
    return 0;
}

/* the game g (0..6) of season has its kind 192 + g record */
static int ws_game(long season, int g)
{
    uint16_t idx = 0, val = 0;
    return ms_first(season, SERIES_GAME_KIND + g, &idx, &val);
}

/* the five cells of g_ser[k] (TEAM, R, H, E, the last column); "" for an empty one */
static void ser_put(int k, const char *c0, const char *c1, const char *c2,
                    const char *c3, const char *c4)
{
    strcpy(g_ser[k].cells[0], c0);
    strcpy(g_ser[k].cells[1], c1);
    strcpy(g_ser[k].cells[2], c2);
    strcpy(g_ser[k].cells[3], c3);
    strcpy(g_ser[k].cells[4], c4);
    g_ser[k].ncells = 5;
}

/* the visitor or home row of a game into g_ser[k]: team t, R, then H and E (empty
 * without the kind 200 + g record, he 0), W when the side won */
static void ser_team(int k, int t, int r, int he, int hits, int errs, int won)
{
    char nm[SLEN], rs[SLEN], hs[SLEN], es[SLEN];
    stand_name(t, nm);
    sprintf(rs, "%d", r);
    hs[0] = 0;
    es[0] = 0;
    if (he) {
        sprintf(hs, "%d", hits);
        sprintf(es, "%d", errs);
    }
    ser_put(k, nm, rs, hs, es, won ? "W" : "");
}

/* the one message row of WORLD SERIES */
static int series_message(void)
{
    strcpy(g_ser[0].cells[0], "NO WORLD SERIES RECORDED");
    g_ser[0].ncells = 1;
    g_ser_game[0] = -1;
    return 1;
}

/* WORLD SERIES rows of season into g_ser (dynview.series_rows); returns the count. Per
 * game g with a kind 192 + g record (the first of its kind): a header row, the visitor
 * and home rows, then the summary row (the first game's visitor and home ids t1, t2 and
 * their wins). Past the history table or with no game record, one message row. */
static int build_series(long season)
{
    int g, n = 0, games = 0, t1 = 0, t2 = 0, w1 = 0, w2 = 0;
    char nm[SLEN], tmp[SLEN];
    if (season > SEASON_COUNT)
        return series_message();
    for (g = 0; g < SERIES_GAMES; g++) {
        uint16_t gidx = 0, gval = 0, hidx = 0, hval = 0;
        int v, h, vr, hr, he;
        if (!ms_first(season, SERIES_GAME_KIND + g, &gidx, &gval))
            continue;
        he = ms_first(season, SERIES_HE_KIND + g, &hidx, &hval);
        v = gidx >> 8;
        h = gidx & 255;
        vr = gval >> 8;
        hr = gval & 255;
        if (games == 0) {
            t1 = v;
            t2 = h;
        }
        games++;
        if (vr != hr) {
            int win = vr > hr ? v : h;
            if (win == t1)
                w1++;
            if (win == t2)
                w2++;
        }
        sprintf(tmp, "GAME %d", g + 1);
        ser_put(n++, tmp, "", "", "", "");
        g_ser_game[n - 1] = (int8_t)g;
        ser_team(n++, v, vr, he, hidx >> 8, hval >> 8, vr > hr);
        g_ser_game[n - 1] = (int8_t)g;
        ser_team(n++, h, hr, he, hidx & 255, hval & 255, hr > vr);
        g_ser_game[n - 1] = (int8_t)g;
    }
    if (games == 0)
        return series_message();
    if (w1 == w2) {
        sprintf(tmp, "TIED %d-%d", w1, w2);
        ser_put(n++, "SERIES", "", "", "", tmp);
    } else {
        int lead = w1 > w2 ? t1 : t2, a = w1 > w2 ? w1 : w2, b = w1 > w2 ? w2 : w1;
        stand_name(lead, nm);
        sprintf(tmp, "%s %d-%d", a >= 4 ? "WINS" : "LEADS", a, b);
        ser_put(n++, nm, "", "", "", tmp);
    }
    g_ser_game[n - 1] = -1;
    return n;
}

/* forward declarations: the PLAYOFFS bodies below sit before the ColDef tables */
static const ColDef COLS_SINGLE[1];
static const ColDef COLS_SERIES[5];
static const ColDef COLS_BOX[7];
static const ColDef COLS_WATCH[4];      /* C27 WATCH */
/* ---------------- PLAYOFFS (C23c round header records) ---------------- */

/* the season's flags-4 round headers into g_pl (playoff_games), streamed from
 * BOXSCORE.DAT: at most PLAYOFF_HDR_MAX in g-ascending order (insertion sort on the
 * stable g order; the file already holds them g-ascending). The read happens once per
 * season: g_pl_season -1 is none yet. Returns the count. */
static int playoff_headers(long season)
{
    char path[600];
    FILE *f;
    uint8_t rb[16];
    int n = 0;
    if (season == g_pl_season)
        return g_pl_n;
    g_pl_n = 0;
    g_pl_season = season;
    path_join(path, g_lgdir, "BOXSCORE.DAT");
    f = fopen(path, "rb");
    if (!f)
        return 0;
    while (fread(rb, 1, sizeof rb, f) == sizeof rb) {
        uint16_t season_r = (uint16_t)(rb[0] | ((uint16_t)rb[1] << 8));
        uint16_t idx = (uint16_t)(rb[4] | ((uint16_t)rb[5] << 8));
        uint8_t g = rb[2], j, k;
        if (season_r != season || rb[3] != 4 || g < PLAYOFF_G_MIN)
            continue;
        if (n == PLAYOFF_HDR_MAX)
            break;
        /* insertion sort by g (equal g keeps the first file order) */
        for (j = n; j > 0 && g_pl[j - 1].g > g; j--)
            g_pl[j] = g_pl[j - 1];
        g_pl[j].g = g;
        g_pl[j].i = rb[7];
        g_pl[j].idx = idx;
        g_pl[j].b = rb[6];
        for (k = 0; k < 8; k++)
            g_pl[j].s[k] = rb[8 + k];
        n++;
    }
    if (ferror(f))
        n = 0;
    fclose(f);
    g_pl_n = n;
    return g_pl_n;
}

/* the one message row of PLAYOFFS */
static int playoff_message(void)
{
    strcpy(g_pser[0].cells[0], "NO PLAYOFF ROUNDS RECORDED");
    g_pser[0].ncells = 1;
    return 1;
}

/* C30: the PLDR slot of idx, or NULL past POST_LEADER_MAX distinct entries; entries
 * already in the tally keep counting (dynview's seen/n_seen rule) */
static PlDr *pldr_slot(uint16_t idx, uint16_t nent)
{
    int i;
    if (idx == NO_AWARD || idx >= nent)
        return NULL;
    for (i = 0; i < g_pldr_n; i++)
        if (g_pldr[i].idx == idx)
            return &g_pldr[i];
    if (g_pldr_n == POST_LEADER_MAX)
        return NULL;
    g_pldr[g_pldr_n].idx = idx;
    memset(g_pldr[g_pldr_n].s, 0, sizeof g_pldr[0].s);
    return &g_pldr[g_pldr_n++];
}

/* C30: one BOXSCORE.DAT pass of season into g_pldr, the way playoff_headers streams
 * the file (no whole-file buffer); player rows only (flags & 4 == 0), any g. Batting
 * rows sum H s[2], HR s[4], RBI s[3], SB s[7]; pitching rows SO s[6], ER s[3] and
 * outs = 3 * (IP10 / 10) + IP10 % 10. Returns the distinct entry count. */
static int post_leader_tally(long season)
{
    char path[600];
    FILE *f;
    uint8_t rb[16];
    g_pldr_n = 0;
    path_join(path, g_lgdir, "BOXSCORE.DAT");
    f = fopen(path, "rb");
    if (!f)
        return 0;
    while (fread(rb, 1, sizeof rb, f) == sizeof rb) {
        uint16_t season_r = (uint16_t)(rb[0] | ((uint16_t)rb[1] << 8));
        uint16_t idx = (uint16_t)(rb[4] | ((uint16_t)rb[5] << 8));
        PlDr *d;
        const uint8_t *st;
        if (season_r != season || (rb[3] & 4) != 0)
            continue;
        d = pldr_slot(idx, n_entries());
        if (!d)
            continue;
        st = rb + 8;
        if (rb[3] & 2) {
            d->s[4] = (uint16_t)(d->s[4] + st[6]);
            d->s[6] = (uint16_t)(d->s[6] + 3u * ((unsigned)st[0] / 10u)
                                 + (unsigned)st[0] % 10u);
            d->s[5] = (uint16_t)(d->s[5] + st[3]);
        } else {
            d->s[0] = (uint16_t)(d->s[0] + st[2]);
            d->s[1] = (uint16_t)(d->s[1] + st[4]);
            d->s[2] = (uint16_t)(d->s[2] + st[3]);
            d->s[3] = (uint16_t)(d->s[3] + st[7]);
        }
    }
    fclose(f);
    return g_pldr_n;
}

/* ser_put / ser_team into the PLAYOFFS row buffer g_pser (g_ser is the WS rows') */
static void ser_pser_put(int k, const char *c0, const char *c1, const char *c2,
                         const char *c3, const char *c4);

/* C30: the leader rows of the tally into g_pser from row n (at most 3 a category,
 * ties by entry index ascending): (name 17, '', '', '', value text). The categories
 * run H HR RBI SB SO IP (sum descending, above 0) and ERA (ER * 2700 / OUTS ascending,
 * only entries with at least 27 outs). keys[][1] is the tally slot. Returns the count. */
static int pldr_asc(const void *a, const void *b)
{
    const uint32_t *p = a, *q = b;
    if (p[0] != q[0])
        return p[0] < q[0] ? -1 : 1;                    /* ERA: value ascending */
    if (g_pldr[p[1]].idx != g_pldr[q[1]].idx)
        return g_pldr[p[1]].idx < g_pldr[q[1]].idx ? -1 : 1;
    return 0;
}

static int post_leader_rows(int n)
{
    uint32_t FARDATA keys[POST_LEADER_MAX][2];
    static const char *const fmts[] = { "%d H", "%d HR", "%d RBI", "%d SB", "%d SO" };
    int cat, k, i;
    for (cat = 0; cat < 7; cat++) {
        int nk = 0;
        for (k = 0; k < g_pldr_n; k++) {
            const PlDr *d = &g_pldr[k];
            uint32_t val;
            if (cat == 5) {                             /* IP: OUTS */
                if (d->s[6] == 0)
                    continue;
                val = d->s[6];
            } else if (cat == 6) {                      /* ERA */
                if (d->s[6] < 27)
                    continue;
                val = (uint32_t)d->s[5] * 2700u / d->s[6];
            } else {
                if (d->s[cat] == 0)
                    continue;
                val = d->s[cat];
            }
            keys[nk][0] = val;
            keys[nk][1] = (uint32_t)k;
            nk++;
        }
        if (cat == 6)
            qsort(keys, nk, sizeof keys[0], pldr_asc);
        else
            for (i = 1; i < nk; i++) {                  /* descending val, entry asc */
                uint32_t v = keys[i][0], sl = keys[i][1];
                uint16_t e = g_pldr[sl].idx;
                for (k = i - 1; k >= 0
                     && (keys[k][0] < v
                         || (keys[k][0] == v && g_pldr[keys[k][1]].idx > e)); k--) {
                    keys[k + 1][0] = keys[k][0];
                    keys[k + 1][1] = keys[k][1];
                }
                keys[k + 1][0] = v;
                keys[k + 1][1] = sl;
            }
        for (i = 0; i < 3 && i < nk && n < PLAYOFF_ROWS_MAX; i++) {
            char nm[NAME_CAP_MAX], txt[SLEN];
            const PlDr *d = &g_pldr[keys[i][1]];
            entry_name(d->idx, 17, nm);
            if (cat == 5)
                sprintf(txt, "%u.%u IP", (unsigned)(d->s[6] / 3),
                        (unsigned)(d->s[6] % 3));
            else if (cat == 6)
                sprintf(txt, "%u.%02u ERA", (unsigned)(keys[i][0] / 100u),
                        (unsigned)(keys[i][0] % 100u));   /* the 32-bit key */
            else
                sprintf(txt, fmts[cat], (unsigned)d->s[cat]);
            ser_pser_put(n++, nm, "", "", "", txt);
        }
    }
    return n;
}

/* ser_put / ser_team into the PLAYOFFS row buffer g_pser (g_ser is the WS rows') */
static void ser_pser_put(int k, const char *c0, const char *c1, const char *c2,
                         const char *c3, const char *c4)
{
    strcpy(g_pser[k].cells[0], c0);
    strcpy(g_pser[k].cells[1], c1);
    strcpy(g_pser[k].cells[2], c2);
    strcpy(g_pser[k].cells[3], c3);
    strcpy(g_pser[k].cells[4], c4);
    g_pser[k].ncells = 5;
}

/* the visitor or home row of a round game into g_pser[k] */
static void ser_team_pser(int k, int t, int r, int hits, int errs, int won)
{
    char nm[SLEN], rs[SLEN], hs[SLEN], es[SLEN];
    stand_name(t, nm);
    sprintf(rs, "%d", r);
    sprintf(hs, "%d", hits);
    sprintf(es, "%d", errs);
    ser_pser_put(k, nm, rs, hs, es, won ? "W" : "");
}

/* the g_pser cells of the PLAYOFFS rows of season (dynview.playoff_rows): per series
 * (consecutive headers with the same b) the title row, then per game the three rows
 * series_rows makes for a WS game, then the summary (WINS 3+ in a division series,
 * 4 in a championship series). Past the history table or with no game, one message
 * row. Returns the row count into g_ser. */
static int build_playoffs(long season)
{
    int n = 0, k = 0, count;
    char tmp[SLEN], aux[SLEN];
    if (season > SEASON_COUNT)
        return playoff_message();
    count = playoff_headers(season);
    if (count == 0)
        return playoff_message();
    post_leader_tally(season);
    while (k < count) {
        uint8_t b = g_pl[k].b;
        int rnd = b & 3, L = (b >> 2) & 1;
        int wins[2] = { 0, 0 };
        int v1, h1, last = k;
        while (last < count && g_pl[last].b == b)
            last++;
        strcpy(tmp, L ? "NL " : "AL ");
        strcat(tmp, rnd == 2 ? "CHAMPIONSHIP SERIES" : "DIVISION SERIES");
        ser_pser_put(n++, tmp, "", "", "", "");
        v1 = g_pl[k].idx >> 8;
        h1 = g_pl[k].idx & 255;
        while (k < last) {
            int v = g_pl[k].idx >> 8, h = g_pl[k].idx & 255;
            int vr = g_pl[k].s[0], hr = g_pl[k].s[1];
            sprintf(tmp, "GAME %d", g_pl[k].i);
            ser_pser_put(n++, tmp, "", "", "", "");
            ser_team_pser(n++, v, vr, g_pl[k].s[2], g_pl[k].s[4], vr > hr);
            ser_team_pser(n++, h, hr, g_pl[k].s[3], g_pl[k].s[5], hr > vr);
            if (vr != hr) {
                if ((vr > hr ? v : h) == v1)
                    wins[0]++;
                if ((vr > hr ? v : h) == h1)
                    wins[1]++;
            }
            k++;
        }
        if (wins[0] == wins[1]) {
            sprintf(tmp, "TIED %d-%d", wins[0], wins[1]);
            ser_pser_put(n++, "SERIES", "", "", "", tmp);
        } else {
            int lead = wins[0] > wins[1] ? v1 : h1;
            int a = wins[0] > wins[1] ? wins[0] : wins[1];
            int b2 = wins[0] > wins[1] ? wins[1] : wins[0];
            stand_name(lead, tmp);
            sprintf(aux, "%s %d-%d", a >= (rnd == 1 ? 3 : 4) ? "WINS" : "LEADS",
                    a, b2);
            ser_pser_put(n++, tmp, "", "", "", aux);
        }
    }
    if (g_pldr_n > 0 && n + 1 < PLAYOFF_ROWS_MAX) {  /* C30: the POSTSEASON LEADERS block */
        int m;
        ser_pser_put(n, "POSTSEASON LEADERS", "", "", "", "");
        m = post_leader_rows(n + 1);
        if (m > n + 1)                      /* the title only over a leader row */
            n = m;
    }
    return n;
}

/* the flags-4 header record of round game g of season into *out; 1 when there is one
 * (dynview.pbox_rows' header lookup) */
static int playoff_header_of(long season, int g, PlHdr *out)
{
    int i, count = playoff_headers(season);
    for (i = 0; i < count; i++) {
        if (g_pl[i].g == g) {
            *out = g_pl[i];
            return 1;
        }
    }
    return 0;
}

/* ---------------- C29 TEAM HISTORY ---------------- */

/* the 1-based rank as an ordinal standing label: '1ST' .. '3RD', then '%dTH'
 * (dynview.ordinal_label; 11..13 always TH) */
static void ordinal_label(int rank, char *dst)
{
    static const char *suf[3] = { "ST", "ND", "RD" };
    int ones = rank % 10;
    if (rank % 100 != 11 && rank % 100 != 12 && rank % 100 != 13
        && ones >= 1 && ones <= 3)
        sprintf(dst, "%d%s", rank, suf[ones - 1]);
    else
        sprintf(dst, "%dTH", rank);
}

/* the display name of t (stand_name_plain): the C18 star is not used on TEAM HISTORY
 * (dynview.teamhist_name reads data['teams'], the same walk stand_name_plain mirrors) */
static void th_name(int t, char *dst)
{
    stand_name_plain(t, dst);
}

/* one TEAM HISTORY message row */
static int th_message(void)
{
    strcpy(g_th[0].cells[0], "NO SEASONS RECORDED");
    g_th[0].ncells = 1;
    return 1;
}

/* TEAM HISTORY rows of team id t into g_th (dynview.team_history_rows); returns the
 * count. Newest season first, one row per season where t has W + L > 0: YEAR, W, L,
 * PCT, FINISH (the 1-based rank among the teams of t's league with games in t's
 * division of the entry, the standings order), RESULT (CHAMPION, PENNANT, LCS over any
 * rnd 2 round header of the season, DS over any rnd 1 one, else ''). */
static int build_teamhist(long season_hi, int t)
{
    SeasonEntry se;
    int n = 0, season, u, lo, mates[16], nm = 0, i, j, k, dd;
    lo = season_hi < SEASON_COUNT ? (int)season_hi : SEASON_COUNT;
    for (season = lo; season >= 1; season--) {
        int result;
        ThRow *row;
        memset(&se, 0, sizeof se);
        read_season(&se, season);
        if (se.wl[t][0] + se.wl[t][1] == 0)
            continue;
        nm = 0;
        for (u = (t / 16) * 16; u < (t / 16) * 16 + 16; u++) {
            if (se.wl[u][0] + se.wl[u][1] == 0)
                continue;
            dd = division_of(&se, u);
            if (dd != division_of(&se, t))
                continue;
            /* insertion sort as the teams come in id order; the standings order is
             * (PCT desc, W desc, id asc): keep shifting while the stored mate ranks
             * after u (a strictly worse record, or the full tie with a higher id);
             * equal keys with a lower id stay ahead */
            for (j = nm; j > 0; j--) {
                int p = mates[j - 1];
                long pp = (long)se.wl[p][0] * 1000 / (se.wl[p][0] + se.wl[p][1]);
                long pu = (long)se.wl[u][0] * 1000 / (se.wl[u][0] + se.wl[u][1]);
                if (pp > pu || (pp == pu && se.wl[p][0] > se.wl[u][0])
                    || (pp == pu && se.wl[p][0] == se.wl[u][0] && p < u))
                    break;
            }
            for (k = nm; k > j; k--)
                mates[k] = mates[k - 1];
            mates[j] = u;
            nm++;
        }
        result = 0;
        if (t == se.champion)
            result = 1;
        else if (t == se.al_pennant || t == se.nl_pennant)
            result = 2;
        else {
            int count = (int)playoff_headers(season);
            for (i = 0; i < count && result == 0; i++) {
                if ((g_pl[i].b & 3) == 2
                    && ((g_pl[i].idx >> 8) == t || (g_pl[i].idx & 255) == t))
                    result = 3;
            }
            for (i = 0; i < count && result == 0; i++) {
                if ((g_pl[i].b & 3) == 1
                    && ((g_pl[i].idx >> 8) == t || (g_pl[i].idx & 255) == t))
                    result = 4;
            }
        }
        row = &g_th[n++];
        year_text(season, row->cells[0]);
        sprintf(row->cells[1], "%d", se.wl[t][0]);
        sprintf(row->cells[2], "%d", se.wl[t][1]);
        fmt_avg((int32_t)((long)se.wl[t][0] * 1000 / (se.wl[t][0] + se.wl[t][1])),
                row->cells[3]);
        for (i = 0; i < nm && mates[i] != t; i++)
            ;
        ordinal_label(i + 1, row->cells[4]);
        strcpy(row->cells[5], result == 1 ? "CHAMPION" : result == 2 ? "PENNANT"
                              : result == 3 ? "LCS" : result == 4 ? "DS" : "");
        row->ncells = 6;
        row->season = season;
    }
    if (n == 0) {
        g_th[0].season = 0;
        return th_message();
    }
    return n;
}

/* the TEAM HISTORY title: '%s  %d TITLES  %d PENNANTS' of the team on the screen */
static void teamhist_title(State st, char *dst)
{
    char nm[NAME_CAP_MAX];
    SeasonEntry se;
    int titles = 0, pennants = 0, season, lo;
    long n = g_hdr_seasons;
    lo = n < SEASON_COUNT ? (int)n : SEASON_COUNT;
    for (season = lo; season >= 1; season--) {
        memset(&se, 0, sizeof se);
        read_season(&se, season);
        if (se.wl[st.cat][0] + se.wl[st.cat][1] == 0)
            continue;
        if (st.cat == se.champion) {
            titles++;
            pennants++;
        } else if (st.cat == se.al_pennant || st.cat == se.nl_pennant)
            pennants++;
    }
    th_name((int)st.cat, nm);
    sprintf(dst, "%s  %d TITLES  %d PENNANTS", nm, titles, pennants);
}

/* TEAM HISTORY page: the rows of the team st.cat (page < 0 counts only). Returns
 * the row count; *cols is COLS_SINGLE for the lone message row, else COLS_TEAMHIST. */
static int teamhist_body(State st, int page, const ColDef **cols)
{
    int n, k, r;
    *cols = COLS_TEAMHIST;
    n = build_teamhist((long)g_hdr_seasons, (int)st.cat);
    if (n == 1 && g_th[0].ncells == 1)
        *cols = COLS_SINGLE;
    if (page >= 0) {
        for (k = 0, r = page * ROWS_PER_PAGE; r < n && k < ROWS_PER_PAGE; r++, k++) {
            int c;
            for (c = 0; c < g_th[r].ncells; c++)
                strcpy(g_rows[k].cells[c], g_th[r].cells[c]);
            g_rows[k].ncells = g_th[r].ncells;
        }
    }
    return n;
}

/* PLAYOFF BOX rows of round game g of season into g_box (dynview.pbox_rows): the box_rows
 * layout from the (season, g) records that are not the flags-4 header, the two teams from
 * the header's idx; one message row without a header or without any other record. The
 * records stream the way box_body streams them (g_box_season / g_box_g cache). */
static int build_pbox(long season, int g, int page)
{
    static PlHdr hd;
    int n, ord = 0, t, k, nrec = 0, gmode;
    uint16_t v, h;
    Row *row;
    gmode = g_hdr_seasons != 0 && season >= 1 && season <= SEASON_COUNT
            && playoff_header_of(season, g, &hd);
    box_idx_clear();
    if (!gmode)
        return msg_row(0, "NO BOX SCORE RECORDED");
    /* stream the records of (season, g) that are not the header, first BOX_MAX_RECS */
    {
        char path[600];
        FILE *f;
        uint8_t rb[16];
        path_join(path, g_lgdir, "BOXSCORE.DAT");
        f = fopen(path, "rb");
        if (!f)
            return msg_row(0, "NO BOX SCORE RECORDED");
        while (fread(rb, 1, sizeof rb, f) == sizeof rb) {
            BoxRec rec;
            rec.season = (uint16_t)(rb[0] | ((uint16_t)rb[1] << 8));
            rec.g = rb[2];
            rec.flags = rb[3];
            rec.idx = (uint16_t)(rb[4] | ((uint16_t)rb[5] << 8));
            rec.b = rb[6];
            rec.i = rb[7];
            memcpy(rec.s, rb + 8, 8);
            if (rec.season != season || rec.g != g || rec.flags == 4)
                continue;
            if (nrec == BOX_MAX_RECS)
                break;
            g_pbox[nrec++] = rec;
        }
        fclose(f);
    }
    if (nrec == 0)
        return msg_row(0, "NO BOX SCORE RECORDED");
    n = nrec;
    v = hd.idx >> 8;
    h = hd.idx & 255;
    for (t = 0; t < 2; t++) {
        uint16_t tid = t == 0 ? v : h;
        int pitch;
        row = box_next(&ord, page);
        if (row) {
            char nm[SLEN];
            stand_name_plain(tid, nm);
            box_set(row, nm, "AB", "R", "H", "RBI", "BB", "SO");
        }
        for (pitch = 0; pitch < 2; pitch++) {
            if (pitch) {
                row = box_next(&ord, page);
                if (row)
                    box_set(row, "PITCHING", "IP", "H", "R", "ER", "BB", "SO");
            }
            for (k = 0; k < n; k++) {
                const BoxRec *r = &g_pbox[k];
                if ((r->flags & 1) != t || ((r->flags >> 1) & 1) != pitch)
                    continue;
                box_idx_put(ord, r);
                row = box_next(&ord, page);
                if (row)
                    box_rec_row(row, r, pitch);
            }
        }
    }
    return ord;
}

/* the PLAYOFFS rows of the season build_playoffs into g_ser; the page rows of them into
 * g_rows (dynview.playoffs_body / pbox_body shape: page < 0 counts only) */
static int playoffs_body(State st, int page, const ColDef **cols)
{
    int n, k, r;
    *cols = COLS_SERIES;
    if (g_hdr_seasons == 0) {
        *cols = COLS_SINGLE;
        return 0;
    }
    n = build_playoffs((long)g_hdr_seasons - st.cat);
    if (n == 1 && g_pser[0].ncells == 1)
        *cols = COLS_SINGLE;
    if (page >= 0) {
        for (k = 0, r = page * ROWS_PER_PAGE; r < n && k < ROWS_PER_PAGE; r++, k++)
            g_rows[k] = g_pser[r];
    }
    return n;
}

/* the PLAYOFF BOX page: round game (st.cat & 63) + 16 of the season st.cat >> 6 seasons
 * back from the newest; *cols is COLS_SINGLE for the message row, else COLS_BOX */
static int pbox_body(State st, int page, const ColDef **cols)
{
    int g = (int)(st.cat & 63) + PLAYOFF_G_MIN, n;
    long season = (long)g_hdr_seasons - (st.cat >> 6);
    *cols = COLS_BOX;
    if (g_hdr_seasons == 0) {
        *cols = COLS_SINGLE;
        return 0;
    }
    n = build_pbox(season, g, page);
    if (n == 1) {
        *cols = COLS_SINGLE;
        return msg_row(page, "NO BOX SCORE RECORDED");
    }
    return n;
}

/* history rows: YEAR, CHAMPION, RUNNER-UP, AL MVP, NL MVP */
static int build_hist_rows(int page)
{
    SeasonEntry se;
    char nm[NAME_CAP_MAX];
    int n = 0, k, r0 = page * ROWS_PER_PAGE, r;
    for (r = r0; r < g_histl.n && r < (page + 1) * ROWS_PER_PAGE; r++, n++) {
        read_season(&se, (int)g_histl.idx[r]);
        year_text(se.season_no, g_rows[n].cells[0]);
        stem_display(se.champion_stem, g_rows[n].cells[1]);
        if (champ_managed(&se))
            star_cell(g_rows[n].cells[1]);
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

/* HOF row of page from the g_hofl scan (dynview.hof_rows; the filter was already
 * applied by hof_scan): NAME, IND, YRS, H/W, HR/SO(PSO), AVG/ERA, WAR */
static int build_hof_rows(int page)
{
    int n = 0, k, r0 = page * ROWS_PER_PAGE, r;
    Entry e;
    char nm[NAME_CAP_MAX];
    for (r = r0; r < g_hofl.n && r < (page + 1) * ROWS_PER_PAGE; r++, n++) {
        read_entry(&e, g_hofl.idx[r]);
        g_rows[n].ncells = 7;
        name_display(e.name, 12, nm);
        strcpy(g_rows[n].cells[0], nm[0] ? nm : "?");
        year_text(e.hof_season, g_rows[n].cells[1]);
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
{    const CatDef *c = &CAREER_CATS[cat];
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
        cat_format(c, cat_value(&e, c), val);
        strcpy(g_rows[n].cells[4], val);
    }
    for (k = n; k < MAX_ROWS; k++)
        g_rows[k].ncells = 0;
    return n;
}

/* POSTSEASON LEADERS row of page from g_post_top (C39): rank, NAME, status mark, G
 * (the entry's distinct postseason games), value */
static int build_post_rows(const CatDef *c, int page)
{
    int n = 0, k, r0 = page * ROWS_PER_PAGE, r;
    for (r = r0; r < g_post_n && r < (page + 1) * ROWS_PER_PAGE; r++, n++) {
        Entry e;
        char nm[NAME_CAP_MAX], val[24];
        const PostItem *it = &g_post_top[r];
        memset(&e, 0, sizeof e);
        /* a BOXSCORE.DAT index past HISTORY.DAT's entries: name '?', no mark */
        if (it->entry < g_entry_count)
            read_entry(&e, it->entry);
        g_rows[n].ncells = 5;
        sprintf(g_rows[n].cells[0], "#%u", (unsigned)r + 1u);
        name_display(e.name, 16, nm);
        strcpy(g_rows[n].cells[1], nm[0] ? nm : "?");
        g_rows[n].cells[2][0] = e.status == STATUS_RETIRED ? 'R'
                              : (e.status == STATUS_HOF ? 'H' : ' ');
        g_rows[n].cells[2][1] = 0;
        sprintf(g_rows[n].cells[3], "%u", (unsigned)it->games);
        cat_format(c, it->val, val);
        strcpy(g_rows[n].cells[4], val);
    }
    for (k = n; k < MAX_ROWS; k++)
        g_rows[k].ncells = 0;
    return n;
}

/* the TEAM column of a team id: its MAJ abbreviation, else '?' (dynview.team_abbrs) */
static const char *abbr_of(uint8_t id)
{
    int i;
    for (i = 0; i < g_nab; i++)
        if (g_abid[i] == id)
            return g_abtxt[i];
    return "?";
}

/* SEASON and BY YEAR leader rows of page from g_sbuf (C13.3): rank, NAME, YEAR (blank for BY YEAR),
 * TEAM, VALUE; the rank counts from the top of the list */
static int build_season_rows(const CatDef *c, int by_year, int page)
{
    int n = 0, k, r;
    for (r = page * ROWS_PER_PAGE; r < g_sn && r < (page + 1) * ROWS_PER_PAGE; r++, n++) {
        const SItem *it = &g_sbuf[r];
        Row *row = &g_rows[n];
        sprintf(row->cells[0], "#%d", r + 1);
        entry_name(it->entry, 16, row->cells[1]);
        if (by_year)
            row->cells[2][0] = 0;
        else
            year_text(it->season, row->cells[2]);
        strcpy(row->cells[3], abbr_of(it->team));
        cat_format(c, (uint32_t)it->val, row->cells[4]);
        row->ncells = 5;
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
        year_text(rec->season, g_rows[n].cells[0]);
        entry_name(rec->idx, 16, nm);
        strcpy(g_rows[n].cells[1], nm);
        event_text(rec->kind, (int32_t)rec->value, ev);
        strcpy(g_rows[n].cells[2], ev);
    }
    for (k = n; k < MAX_ROWS; k++)
        g_rows[k].ncells = 0;
    return n;
}

/* WATCH rows of page (C27): NAME, '%d %s' (mark, label), NOW, NEED; no item at all:
 * one message row. Returns the drawn row count. */
static int build_watch_rows(int page)
{
    int n = 0, k, r0 = page * ROWS_PER_PAGE, r;
    for (r = r0; r < g_nwatch && r < (page + 1) * ROWS_PER_PAGE; r++, n++) {
        const WatchItem *it = &g_watch[r];
        char nm[NAME_CAP_MAX];
        Row *row = &g_rows[n];
        row->ncells = 4;
        entry_name((uint16_t)it->entry, 16, nm);
        strcpy(row->cells[0], nm);
        sprintf(row->cells[1], "%lu %s", (unsigned long)it->mark,
                WATCH_LABEL[it->kind - 1]);
        sprintf(row->cells[2], "%lu", (unsigned long)it->now);
        sprintf(row->cells[3], "%lu", (unsigned long)it->need);
    }
    if (n == 0 && page == 0) {
        strcpy(g_rows[0].cells[0], "NO ACTIVE PLAYER NEAR A MILESTONE");
        g_rows[0].ncells = 1;
        n = 1;
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
        if (rec->season != last || rec->kind >= AWARD_KIND_MIN)
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

/* the hub rows (dynview.MENU_ROWS): the key of row k is its first char; the row's
 * ENTER sends the same key (C67) */
static const char *MENU_ITEMS[N_MENU_ROWS] = {
    "1  SEASON HISTORY", "2  HALL OF FAME", "3  LEADERS",
    "4  MILESTONES", "5  LAST SEASON REVIEW", "6  OFFSEASON",
    "7  DYNASTY SETTINGS", "8  ABOUT THE MODS", "9  SEASON AWARDS",
    "0  SEASON STANDINGS", "W  WORLD SERIES", "P  PLAYOFFS" };

static void build_menu_rows(void)
{
    int k;
    for (k = 0; k < N_MENU_ROWS; k++) {
        strcpy(g_rows[k].cells[0], MENU_ITEMS[k]);
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
        "THE DYNASTY MENU ON THE MENU BAR HOLDS",
        "HISTORY, CREATE A PLAYER, SETTINGS AND",
        "A GUIDE TO EVERY MOD." };
    int k;
    for (k = 0; k < N_TITLE_ROWS; k++) {
        strcpy(g_rows[k].cells[0], lines[k]);
        g_rows[k].ncells = 1;
    }
    g_nrows = N_TITLE_ROWS;
}

/* the ERA RULES value of g_era (dynview.era_label) */
static const char *era_label(void)
{
    if (g_era == 0)
        return "REAL CALENDAR";
    if (g_era == 2)
        return "FREE AGENCY";
    return "RESERVE CLAUSE";
}

/* the PLAYOFF FORMAT value of g_fmt_wanted and g_fmt_now (dynview.playoff_label) */
static const char *playoff_label(void)
{
    int three = g_fmt_wanted == 3;
    if (g_fmt_wanted == g_fmt_now)
        return three ? "3 DIV + WILDCARD" : "2 DIVISIONS";
    return three ? "3 DIV NEXT YEAR" : "2 DIV NEXT YEAR";
}

/* DYNASTY SETTINGS page: row 0 ERA RULES, row 1 PLAYOFF FORMAT, row 2 START YEAR (C13.1), row c
 * the team g_tlg[c - SET_TEAM0] (cursor c) */
static void build_settings_rows(int page)
{
    int i, k = 0;
    for (i = page * ROWS_PER_PAGE; i < SET_TEAM0 + g_nteams && k < ROWS_PER_PAGE; i++, k++) {
        Row *row = &g_rows[k];
        if (i == 0) {
            strcpy(row->cells[0], "ERA RULES");
            strcpy(row->cells[1], era_label());
        } else if (i == 1) {
            strcpy(row->cells[0], "PLAYOFF FORMAT");
            strcpy(row->cells[1], playoff_label());
        } else if (i == SET_START) {
            strcpy(row->cells[0], "START YEAR");
            sprintf(row->cells[1], "%ld", (long)start_year());
        } else {
            strcpy(row->cells[0], g_tdisp[i - SET_TEAM0]);
            strcpy(row->cells[1], ((g_mask >> g_tlg[i - SET_TEAM0]) & 1u)
                                  ? "YOU MANAGE" : "AI MANAGES");
        }
        row->ncells = 2;
    }
    g_nrows = k;
}

/* ABOUT THE MODS page: ROWS_PER_PAGE lines of dynview.ABOUT_ROWS */
static void build_about_rows(int page)
{
    int r, k = 0;
    for (r = page * ROWS_PER_PAGE; r < N_ABOUT_ROWS && k < ROWS_PER_PAGE; r++, k++) {
        strcpy(g_rows[k].cells[0], ABOUT_LINES[r]);
        g_rows[k].ncells = 1;
    }
    g_nrows = k;
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
    char yr[16];
    int k;
    year_text((int32_t)g_hdr_seasons + 1, yr);
    sprintf(g_rows[0].cells[0], "RETIRED: %lu   NEW HALL OF FAME: %lu",
            (unsigned long)nret, (unsigned long)nhof);
    sprintf(g_rows[1].cells[0], "ROOKIES DRAFTED: %lu", (unsigned long)g_rc.picks);
    sprintf(g_rows[2].cells[0], "TRADES: %lu", (unsigned long)g_rc.trades);
    sprintf(g_rows[3].cells[0], "FREE AGENT SIGNINGS: %lu", (unsigned long)g_rc.fa);
    sprintf(g_rows[4].cells[0], "PLAYERS RELEASED: %lu", (unsigned long)g_rc.rel);
    strcpy(g_rows[5].cells[0], "EVERY PLAYER AGED A YEAR AND DEVELOPED");
    if (launched)
        sprintf(g_rows[6].cells[0], "ENTER: ON TO %s", yr);
    else
        strcpy(g_rows[6].cells[0], "ENTER: BACK TO THE MENU");
    for (k = 0; k < 7; k++)
        g_rows[k].ncells = 1;
}

/* FIND PLAYER page (C50, dynview.rows SCREEN_FIND): the empty query is one prompt row
 * (COLS_SINGLE), no match one NO PLAYER FOUND row (COLS_SINGLE), else the page's search
 * rows in COLS_FIND (find_scan fills g_rows directly). Returns the row count of the page. */
static int find_body(State st, int page, const ColDef **cols)
{
    int seen;
    (void)st;
    if (!g_find_q[0]) {
        *cols = COLS_SINGLE;
        return msg_row(page, "TYPE THE START OF A LAST NAME.");
    }
    find_scan(g_find_q, -1, NULL, &seen);
    if (seen == 0) {
        /* a lone message row of a screen with its own columns: the FIND headers stay,
         * the message renders from the first column (the body_cols rule above) */
        *cols = COLS_FIND;
        return msg_row(page, "NO PLAYER FOUND.");
    }
    *cols = COLS_FIND;
    if (page >= 0) {
        int k = 0, m;
        char nm[NAME_CAP_MAX];
        for (m = page * ROWS_PER_PAGE; m < seen && k < ROWS_PER_PAGE; m++, k++) {
            Row *row = &g_rows[k];
            Entry rd;
            if (!read_entry(&rd, g_find[m].entry))
                break;
            name_display(rd.name, 20, nm);
            put_cell(row->cells[0], (const uint8_t *)nm, (int)strlen(nm));
            strcpy(row->cells[1], pos_name(rd.pos1));
            sprintf(row->cells[2], "%u", (unsigned)rd.seasons_played);
            strcpy(row->cells[3], rd.status == STATUS_RETIRED ? "RETIRED"
                                  : (rd.status == STATUS_HOF ? "HALL OF FAME" : "ACTIVE"));
            row->ncells = 4;
        }
    }
    return seen;
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

/* the NO HALL OF FAMERS message text (C53) of filter f: the label appended */
static const char *hof_msg(int f)
{
    static char msg[48];
    strcpy(msg, "NO HALL OF FAMERS AT ");
    strcat(msg, HOF_FILTER_LABELS[f]);
    return msg;
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
        if (!g_hdr_seasons)
            return 0;
        hof_scan(&g_hofl, (int)st.cat);
        return g_hofl.n;
    case SCREEN_LEADERS:
        return leaders_body(st, -1, &cols);
    case SCREEN_MILESTONES: {
        List b;
        if (!g_hdr_seasons)
            return 0;
        if (st.cat != 1) {
            ms_scan(&b);
            return (int)b.n;
        }
        watch_scan();
        return (int)g_nwatch;
    }
    case SCREEN_CARD:
        if (st.row)
            return honors_rows_count(st.cat);
        card_collect(st.cat);
        return g_ncard;
    case SCREEN_REVIEW:
        return build_review_rows();
    case SCREEN_OFFSEASON:
        return offseason_body(st, -1, &cols);
    case SCREEN_AWARDS:
        return awards_body(st, -1, &cols);
    case SCREEN_AWHIST:
        return awhist_body(st, -1, &cols);
    case SCREEN_STANDINGS:
        return standings_body(st, -1, &cols);
    case SCREEN_SERIES:
        return series_body(st, -1, &cols);
    case SCREEN_BOX:
        return box_body(st, -1, &cols);
    case SCREEN_PLAYOFFS:
        return playoffs_body(st, -1, &cols);
    case SCREEN_PBOX:
        return pbox_body(st, -1, &cols);
    case SCREEN_TEAMHIST:
        return teamhist_body(st, -1, &cols);
    case SCREEN_SETTINGS:
        return SET_TEAM0 + g_nteams;
    case SCREEN_ABOUT:
        return N_ABOUT_ROWS;
    case SCREEN_FIND: {
        int seen;
        find_scan(g_find_q, -1, NULL, &seen);
        return seen ? seen : 1;
    }
    default:
        return N_MENU_ROWS;
    }
}

/* the hub MENU_ROWS cursor (C67): true outside the /TITLE welcome mode, where a league
 * with no recorded season and cat >> 4 shows TITLE_ROWS */
static int hub_cursor(State st)
{
    return !(g_hdr_seasons == 0 && (st.cat >> 4));
}

/* rows of the current page into g_rows (matches dynview.rows; every screen
 * shows 'NO DYNASTY HISTORY YET' on a new file) and their columns into *cols */
static int refresh_rows(State st, const ColDef **cols)
{
    *cols = body_cols(st);
    if (st.screen == SCREEN_SETTINGS) {
        build_settings_rows(st.page);
        return g_nrows;
    }
    if (st.screen == SCREEN_ABOUT) {
        build_about_rows(st.page);
        return g_nrows;
    }
    if (st.screen == SCREEN_MENU) {
        if (g_hdr_seasons == 0 && (st.cat >> 4)) {
            build_title_rows();
            return g_nrows;
        }
        build_menu_rows();
        return N_MENU_ROWS;
    }
    /* FIND PLAYER shows its prompt and search with no recorded season too (dynview.rows),
     * in COLS_SINGLE then (dynview.body_cols) */
    if (st.screen == SCREEN_FIND) {
        int n = find_body(st, st.page, cols);
        if (g_hdr_seasons == 0)
            *cols = COLS_SINGLE;
        return n;
    }
    if (g_hdr_seasons == 0) {
        build_no_hist_rows();
        return g_nrows;
    }
    switch (st.screen) {
    case SCREEN_LEADERS:
        return page_rows(leaders_body(st, st.page, cols), st.page);
    case SCREEN_HISTORY:
        hist_scan(&g_histl);
        return build_hist_rows(st.page);
    case SCREEN_HOF:
        hof_scan(&g_hofl, (int)st.cat);
        if (g_hofl.n == 0 && st.cat != 0)
            return msg_row(st.page, hof_msg(st.cat));
        return build_hof_rows(st.page);
    case SCREEN_MILESTONES:
        if (st.cat != 1) {
            ms_scan(&g_msl);
            return build_ms_rows(st.page);
        }
        *cols = COLS_WATCH;
        watch_scan();
        if (g_nwatch == 0)
            *cols = COLS_SINGLE;
        return build_watch_rows(st.page);
    case SCREEN_OFFSEASON:
        return page_rows(offseason_body(st, st.page, cols), st.page);
    case SCREEN_AWARDS:
        return page_rows(awards_body(st, st.page, cols), st.page);
    case SCREEN_AWHIST:
        return page_rows(awhist_body(st, st.page, cols), st.page);
    case SCREEN_STANDINGS:
        return page_rows(standings_body(st, st.page, cols), st.page);
    case SCREEN_SERIES:
        return page_rows(series_body(st, st.page, cols), st.page);
    case SCREEN_BOX:
        return page_rows(box_body(st, st.page, cols), st.page);
    case SCREEN_PLAYOFFS:
        return page_rows(playoffs_body(st, st.page, cols), st.page);
    case SCREEN_PBOX:
        return page_rows(pbox_body(st, st.page, cols), st.page);
    case SCREEN_FIND:
        return find_body(st, st.page, cols);

    case SCREEN_TEAMHIST:
        return page_rows(teamhist_body(st, st.page, cols), st.page);
    default:
        return build_review_rows();
    }
}

/* a state with no cursor, row and year (dynview.pack of a 3-tuple) */
static State mk_state(int screen, int page, int32_t cat)
{
    State s;
    s.screen = (int16_t)screen;
    s.page = (int16_t)page;
    s.cat = cat;
    s.row = 0;
    s.year = 0;
    return s;
}

/* the category list of a LEADERS mode (dynview.leader_cats): CAREER = CATS, SEASON and
 * BY YEAR = SEASON_CATS, POST = POST_CATS */
static const CatDef *leader_cats(int mode)
{
    if (mode == MODE_CAREER)
        return CAREER_CATS;
    if (mode == MODE_POST)
        return POST_CATS;
    return SEASON_CATS;
}

static int leader_ncats(int mode)
{
    if (mode == MODE_CAREER)
        return N_CAREER_CATS;
    if (mode == MODE_POST)
        return N_POST_CATS;
    return N_SEASON_CATS;
}

/* the screens with a row cursor (C13.4): HALL OF FAME, LEADERS (every mode), SEASON AWARDS,
 * AWARD HISTORY (C28), SEASON HISTORY (C56), SEASON STANDINGS (C57), TEAM HISTORY (C60),
 * the offseason RETIREMENTS phase, MILESTONES (C27/C61: cat 0 the milestones list,
 * cat 1 WATCH), WORLD SERIES (C64) and PLAYOFFS (C65); the hub MENU keeps its own
 * cursor (C67, step and hub_cursor) */
static int cursor_screen(State st)
{
    if (st.screen == SCREEN_HOF || st.screen == SCREEN_LEADERS
        || st.screen == SCREEN_AWARDS || st.screen == SCREEN_AWHIST
        || st.screen == SCREEN_HISTORY || st.screen == SCREEN_STANDINGS
        || st.screen == SCREEN_BOX || st.screen == SCREEN_PBOX
        || st.screen == SCREEN_TEAMHIST || st.screen == SCREEN_SERIES
        || st.screen == SCREEN_PLAYOFFS)
        return 1;
    if (st.screen == SCREEN_MILESTONES)
        return 1;
    if (st.screen == SCREEN_FIND)
        return 1;
    return st.screen == SCREEN_OFFSEASON && (st.cat & 15) == OFF_RETIRE;
}

/* st with the cursor on row; the page follows (page = row / ROWS_PER_PAGE) */
static State cursor_state(State st, int32_t row)
{
    st.row = row;
    st.page = (int16_t)(row / ROWS_PER_PAGE);
    return st;
}

/* UP / DOWN move the cursor one row within the list; PGUP / PGDN move the page and put the cursor
 * on its first row, only when the page changes; HOME / END jump to the first and last
 * row (dynview.cursor_move) */
static State cursor_move(State st, int32_t key)
{
    int32_t n = total_rows(st), row = st.row;
    int32_t page = st.page;
    if (key == KEY_UP && row > 0)
        row--;
    else if (key == KEY_DOWN && row < n - 1)
        row++;
    else if (key == KEY_PGDN && page * ROWS_PER_PAGE + ROWS_PER_PAGE < n)
        row = (page + 1) * ROWS_PER_PAGE;
    else if (key == KEY_PGUP && page > 0)
        row = (page - 1) * ROWS_PER_PAGE;
    else if (key == KEY_HOME && row > 0)
        row = 0;
    else if (key == KEY_END && row < n - 1)
        row = n - 1;
    else
        return st;
    return cursor_state(st, row);
}

/* an AWARDS entry index as a player (dynview.award_entry): -1 for none, NO_AWARD or an index past
 * the entry table */
static int32_t award_entry(int32_t idx)
{
    if (idx < 0 || idx == NO_AWARD || (uint32_t)idx >= n_entries())
        return -1;
    return idx;
}

/* the entry of the BOX SCORE screen's cursor row (dynview.row_entry C62): g_box_idx as
 * box_body last filled it, -1 past its end */
static int32_t box_row_entry(State st)
{
    const ColDef *cols;
    int32_t n = box_body(mk_state(SCREEN_BOX, -1, st.cat), -1, &cols);
    if (st.row >= n)
        return -1;
    return g_box_idx[st.row];
}

/* the entry of the PLAYOFF BOX screen's cursor row (dynview.row_entry C62), likewise */
static int32_t pbox_row_entry(State st)
{
    const ColDef *cols;
    int32_t n = pbox_body(st, -1, &cols);
    if (st.row >= n)
        return -1;
    return g_box_idx[st.row];
}

/* the player entry named by the cursor row of st (dynview.row_entry), -1 for none: a message row, an
 * award with no player, an empty list or no history */
static int32_t row_entry(State st)
{
    int32_t row = st.row;
    if (g_hdr_seasons == 0)
        return -1;
    if (st.screen == SCREEN_STANDINGS || st.screen == SCREEN_TEAMHIST
        || st.screen == SCREEN_SERIES)
        return -1;              /* C57, C60: no player card; C64: the WS ENTER opens a box */
    if (st.screen == SCREEN_PLAYOFFS)
        return -1;              /* C65: the PLAYOFFS ENTER opens the row game's PBOX */
    if (st.screen == SCREEN_HOF) {
        hof_scan(&g_hofl, (int)st.cat);
        return row < (int32_t)g_hofl.n ? (int32_t)g_hofl.idx[row] : -1;
    }
    if (st.screen == SCREEN_LEADERS) {
        int mode = (int)(st.cat >> 5), idx = (int)(st.cat & 31), seen = 0;
        if (mode == MODE_CAREER) {
            leaders_scan(&g_leadl, idx);
            return row < (int32_t)g_leadl.n ? (int32_t)g_leadl.idx[row] : -1;
        }
        if (mode == MODE_POST) {
            int n = post_scan(&POST_CATS[idx]);
            return row < n ? (int32_t)g_post_top[row].entry : -1;
        }
        season_scan(&SEASON_CATS[idx], mode == MODE_BYYEAR,
                    mode == MODE_BYYEAR ? leaders_year(st) : 0, &seen);
        return row < g_sn ? (int32_t)g_sbuf[row].entry : -1;
    }
    if (st.screen == SCREEN_AWARDS) {
        int n = build_awards((long)g_hdr_seasons - st.cat);
        return row < n ? award_entry(g_awd_idx[row]) : -1;
    }
    if (st.screen == SCREEN_AWHIST) {
        int n = build_awhist(st.cat);
        return row < n ? g_ah_idx[row] : -1;
    }
    if (st.screen == SCREEN_MILESTONES && st.cat == 1) {
        watch_scan();
        return row < g_nwatch ? (int32_t)g_watch[row].entry : -1;
    }
    if (st.screen == SCREEN_BOX)
        return box_row_entry(st);
    if (st.screen == SCREEN_PBOX)
        return pbox_row_entry(st);
    if (st.screen == SCREEN_MILESTONES) {
        int32_t idx;
        ms_scan(&g_msl);
        if (row >= (int32_t)g_msl.n)
            return -1;
        idx = (int32_t)g_ms[g_msl.idx[row]].idx;
        if (idx == NO_AWARD || (uint32_t)idx >= n_entries())
            return -1;
        return idx;
    }
    if (st.screen == SCREEN_OFFSEASON) {
        uint32_t nret = 0, nhof = 0;
        retire_scan(&nret, &nhof);
        return row < (int32_t)g_retl.n ? (int32_t)g_retl.idx[row] : -1;
    }
    if (st.screen == SCREEN_FIND) {
        int seen;
        find_scan(g_find_q, -1, NULL, &seen);
        return row < seen ? (int32_t)g_find[row].entry : -1;
    }
    return -1;
}

/* the PLAYER CARD of entry, opened from the list state st (C13.5): ESC returns to st */
static State open_card(State st, int32_t entry)
{
    g_card_back = st;
    return mk_state(SCREEN_CARD, 0, entry);
}

/* st with the cursor on row (dynview.cursor_to): the SETTINGS cursor, or the row cursor (C13.4) */
static State cursor_to(State st, int32_t row)
{
    if (st.screen == SCREEN_SETTINGS)
        return mk_state(SCREEN_SETTINGS, (int)(row / ROWS_PER_PAGE), row);
    return cursor_state(st, row);
}

/* the screens LEFT and RIGHT step a season on (TEAM HISTORY steps teams instead, C29) */
static int season_screen(int screen)
{
    return screen == SCREEN_AWARDS || screen == SCREEN_STANDINGS
           || screen == SCREEN_SERIES || screen == SCREEN_PLAYOFFS;
}

/* step: ESC exits from MENU, otherwise goes back to MENU; PGUP/PGDN page by
 * 12; LEFT/RIGHT cycle the LEADERS category or step the SEASON AWARDS, SEASON
 * STANDINGS or WORLD SERIES season; key 0 on the hub opens SEASON STANDINGS, W or w
 * WORLD SERIES; keys 1..7 on WORLD SERIES open the BOX SCORE of that game (ESC there goes
 * back to the series, LEFT and RIGHT step between the season's games); the hub is a
 * cursor screen (C67) and its ENTER sends the cursor row's key */
static State step(State in, int32_t key)
{
    State s = in;
    int tid = 0;
    if (key == KEY_ESC) {
        if (s.screen == SCREEN_BOX) {
            /* the box score goes back to its season's WORLD SERIES, not the hub
             * (a 3-tuple in dynview.step: the row cursor resets, C64) */
            s.screen = SCREEN_SERIES;
            s.page = 0;
            s.cat = (int16_t)(s.cat >> 3);
            s.row = 0;
            return s;
        }
        if (s.screen == SCREEN_PBOX) {
            /* the round box goes back to its season's PLAYOFFS, not the hub
             * (a 3-tuple in dynview.step: the row cursor resets, C64) */
            s.screen = SCREEN_PLAYOFFS;
            s.page = 0;
            s.cat = (int16_t)(s.cat >> 6);
            s.row = 0;
            return s;
        }
        /* the PLAYER CARD goes back to the list state it was opened from (C13.5) */
        if (s.screen == SCREEN_CARD)
            return g_card_back;
        /* the AWARD HISTORY goes back to the SEASON AWARDS state it was opened from (C28) */
        if (s.screen == SCREEN_AWHIST) {
            if (!g_awh_have)
                return mk_state(SCREEN_AWARDS, 0, 0);
            return g_awh_back;
        }

        /* TEAM HISTORY goes back to the SEASON STANDINGS state it was opened from (C29),
         * cursor row included (C57); it was never opened: the default (STANDINGS, 0, 0)
         * like Python's data.get */
        if (s.screen == SCREEN_TEAMHIST) {
            if (!g_th_live)
                return mk_state(SCREEN_STANDINGS, 0, 0);
            return g_th_back;
        }
        /* C59: a typed query clears first, the state resets to the prompt row */
        if (s.screen == SCREEN_FIND && g_find_q[0]) {
            g_find_q[0] = 0;
            return mk_state(SCREEN_FIND, 0, 0);
        }
        /* C56: SEASON STANDINGS returns one level to the HISTORY state that opened it */
        if (s.screen == SCREEN_STANDINGS && g_st_have) {
            g_st_have = 0;
            return g_st_back;
        }
        if (s.screen == SCREEN_MENU)
            g_exit = 1;
        return mk_state(SCREEN_MENU, 0, 0);
    }
    if (s.screen == SCREEN_MENU) {
        /* C67 rule 2: outside the /TITLE welcome mode ENTER sends the cursor row's key */
        if (key == KEY_ENTER && hub_cursor(s) && s.row < N_MENU_ROWS)
            key = (int32_t)(unsigned char)MENU_ITEMS[s.row][0];
        if (key == 48) {
            g_st_have = 0;      /* C56: another way in clears the kept HISTORY back state */
            s.screen = SCREEN_STANDINGS;
            s.page = 0;
            s.row = 0;
            s.cat = 0;
        } else if (49 <= key && key <= 57) {
            s.screen = (int16_t)(key - 48);
            s.page = 0;
            s.cat = 0;
            s.row = 0;
        } else if (key == 87 || key == 119) {
            /* W or w: WORLD SERIES */
            s.screen = SCREEN_SERIES;
            s.page = 0;
            s.cat = 0;
            s.row = 0;
        } else if (key == 80 || key == 112) {
            /* P or p: PLAYOFFS */
            s.screen = SCREEN_PLAYOFFS;
            s.page = 0;
            s.cat = 0;
            s.row = 0;
        } else if (key == 70 || key == 102) {
            /* F or f: FIND PLAYER (C50), the query cleared */
            s.screen = SCREEN_FIND;
            s.page = 0;
            s.cat = 0;
            s.row = 0;
            s.year = 0;
            g_find_q[0] = 0;
        } else if (key == KEY_ENTER || key == KEY_CARD_CAP || key == KEY_CARD_LOW) {
            /* the welcome text's ENTER (ENTER elsewhere became the row's key above) and
             * C or c (C67 rule 3): on /TITLE they go on to the game, else no-ops */
            if (s.cat >> 4)
                g_exit = 1;
        } else if (hub_cursor(s) && (key == KEY_UP || key == KEY_DOWN || key == KEY_PGUP
                                     || key == KEY_PGDN || key == KEY_HOME || key == KEY_END)) {
            /* C67: the cursor keys move the row (one page: PGUP is HOME, PGDN is END) */
            if (key == KEY_UP) {
                if (s.row > 0)
                    s.row--;
            } else if (key == KEY_DOWN) {
                if (s.row < N_MENU_ROWS - 1)
                    s.row++;
            } else if (key == KEY_HOME || key == KEY_PGUP) {
                s.row = 0;
            } else {
                s.row = N_MENU_ROWS - 1;
            }
            s.page = 0;
        }
        return s;
    }
    /* FIND PLAYER (C50): a letter appends its upper case (FIND_MAX at most), BACKSPACE
     * removes the last char; either edit resets page, cat and row. Other printable keys
     * do nothing; the row cursor (below) and ESC (handled first, C59 clearing a typed
     * query) stay. */
    if (s.screen == SCREEN_FIND && key >= 65 && key <= 90) {
        int n = (int)strlen(g_find_q);
        if (n < FIND_MAX) {
            g_find_q[n] = (char)key;
            g_find_q[n + 1] = 0;
        }
        s.page = 0;
        s.cat = 0;
        s.row = 0;
        return s;
    }
    if (s.screen == SCREEN_FIND && key >= 97 && key <= 122) {
        int n = (int)strlen(g_find_q);
        if (n < FIND_MAX) {
            g_find_q[n] = (char)(key - 32);
            g_find_q[n + 1] = 0;
        }
        s.page = 0;
        s.cat = 0;
        s.row = 0;
        return s;
    }
    if (s.screen == SCREEN_FIND && key == KEY_BKSP) {
        int n = (int)strlen(g_find_q);
        if (n > 0)
            g_find_q[n - 1] = 0;
        s.page = 0;
        s.cat = 0;
        s.row = 0;
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
            s.row = 0;
            return s;
        }
        if (s.cat >> 4) {
            g_exit = 1;
            return s;
        }
        return mk_state(SCREEN_MENU, 0, 0);
    }
    /* C on the RETIREMENTS phase opens the PLAYER CARD of the highlighted retiree (C13.4); ENTER
     * keeps its walk meaning, and with no player the key does nothing */
    if (s.screen == SCREEN_OFFSEASON && (key == KEY_CARD_CAP || key == KEY_CARD_LOW)
        && (s.cat & 15) == OFF_RETIRE) {
        int32_t entry = row_entry(s);
        if (entry >= 0)
            return open_card(s, entry);
    }
    /* DYNASTY SETTINGS: cat is the cursor (0 ERA RULES, 1 PLAYOFF FORMAT, 2 START YEAR, c >= 3
     * team c - 3); ENTER on PLAYOFF FORMAT sets the format and reloads the teams, the other rows
     * flip and save HISTORY.DAT; then the format is read again. START YEAR steps with LEFT and
     * RIGHT (-1, +1), '-' (-10), '+' and '=' (+10). The rest moves the cursor */
    if (s.screen == SCREEN_SETTINGS) {
        int n = SET_TEAM0 + g_nteams;
        if (s.cat == SET_START && (key == KEY_LEFT || key == KEY_RIGHT || key == KEY_MINUS
                                   || key == KEY_PLUS || key == KEY_EQUALS)) {
            start_year_step(key == KEY_LEFT ? -1 : key == KEY_RIGHT ? 1
                            : key == KEY_MINUS ? -10 : 10);
            return s;
        }
        if (key == KEY_ENTER) {
            if (s.cat == SET_START)
                return s;
            if (s.cat == 1) {
                set_playoff_format(g_fmt_wanted);
                load_teams();
            } else {
                if (s.cat == 0)
                    g_era = (uint8_t)(g_era == 0 ? 1 : (g_era == 2 ? 0 : 2));
                else
                    g_mask ^= (uint32_t)1 << g_tlg[s.cat - SET_TEAM0];
                save_settings();
            }
            load_fmt();
            g_dirty = 1;
            return s;
        }
        if (key == KEY_UP && s.cat > 0)
            s.cat = (int16_t)(s.cat - 1);
        else if (key == KEY_DOWN && s.cat < n - 1)
            s.cat = (int16_t)(s.cat + 1);
        else if (key == KEY_PGDN) {
            int c = s.cat + ROWS_PER_PAGE;
            s.cat = (int16_t)(c < n - 1 ? c : n - 1);
        } else if (key == KEY_PGUP) {
            int c = s.cat - ROWS_PER_PAGE;
            s.cat = (int16_t)(c > 0 ? c : 0);
        } else
            return s;
        s.page = (int16_t)(s.cat / ROWS_PER_PAGE);
        return s;
    }
    /* PLAYER CARD (C40): H or h toggles the view (row 0 SEASONS 7 rows a page, C13.5 and
     * C26; row 1 HONORS HONOR_ROWS rows a page), page reset; ESC returns card_back from
     * both views. PGUP/PGDN page the view (the season table card_rows lines a page).
     * C58: LEFT and RIGHT browse the entry rows of the list the card was opened from. */
    if (s.screen == SCREEN_CARD) {
        int per = post_totals(s.cat) > 0 ? 6 : CARD_SEASON_ROWS;
        if (key == 'H' || key == 'h') {
            s.row = s.row ? 0 : 1;
            s.page = 0;
            return s;
        }
        if (key == KEY_LEFT || key == KEY_RIGHT) {
            /* C58: the next (RIGHT) or previous (LEFT) row of g_card_back whose row_entry
             * names a player: the card's entry and the view, page reset; the back state
             * follows the row. No cursor back (never opened, or a non-cursor screen):
             * the state is unchanged. */
            int dir = (key == KEY_RIGHT) ? 1 : -1;
            if (cursor_screen(g_card_back)) {
                int32_t r = g_card_back.row + dir;
                int n = total_rows(g_card_back);
                while (r >= 0 && r < n) {
                    int32_t e = row_entry(cursor_state(g_card_back, r));
                    if (e >= 0) {
                        g_card_back = cursor_state(g_card_back, r);
                        s.page = 0;
                        s.cat = e;
                        return s;
                    }
                    r += dir;
                }
            }
            return s;
        }
        if (s.row) {
            if (key == KEY_PGDN) {
                if ((s.page + 1) * HONOR_ROWS < honors_rows_count(s.cat))
                    s.page++;
            } else if (key == KEY_PGUP && s.page > 0) {
                s.page--;
            }
            return s;
        }
        if (key == KEY_PGDN) {
            card_collect(s.cat);
            if ((s.page + 1) * per < g_ncard)
                s.page++;
        } else if (key == KEY_PGUP && s.page > 0) {
            s.page--;
        }
        return s;
    }
    /* the row cursor (C13.4): UP / DOWN / PGUP / PGDN / HOME / END move it; ENTER opens the card of
     * its row, except on SEASON HISTORY, where it opens the season's STANDINGS (C56),
     * and on SEASON STANDINGS, where it opens the row team's TEAM HISTORY (C57) */
    if (cursor_screen(s) && (key == KEY_UP || key == KEY_DOWN || key == KEY_PGUP
                             || key == KEY_PGDN || key == KEY_HOME || key == KEY_END))
        return cursor_move(s, key);
    if (cursor_screen(s) && key == KEY_ENTER) {
        if (s.screen == SCREEN_HISTORY) {
            if (!g_hdr_seasons)
                return s;
            hist_scan(&g_histl);
            if (s.row < (int32_t)g_histl.n) {
                long c = (long)g_hdr_seasons - (int32_t)g_histl.idx[s.row];
                if (c >= 0) {
                    g_st_back = s;
                    g_st_have = 1;
                    return mk_state(SCREEN_STANDINGS, 0, (int32_t)c);
                }
            }
            return s;
        }
        if (s.screen == SCREEN_STANDINGS) {
            /* C57: the team of the cursor row tid (-1: a header, a blank row, the message
             * row or past the rows; the ids run 0..31). No history leaves no rows, and
             * g_st_back is untouched here. */
            tid = -1;
            if (g_hdr_seasons) {
                int n = build_standings((long)g_hdr_seasons - s.cat);
                if (s.row < n && g_stnd_tid[s.row] != STAND_NONE)
                    tid = g_stnd_tid[s.row];
            }
            if (tid < 0)
                return s;
            g_th_back = s;
            g_th_live = 1;
            return mk_state(SCREEN_TEAMHIST, 0, tid);
        }
        if (s.screen == SCREEN_TEAMHIST) {
            /* C60: the season of the cursor row opens its SEASON STANDINGS (cat = the
             * seasons back from the newest); the TEAM HISTORY state (cursor kept)
             * replaces any earlier g_st_back. The message row, a row past the end
             * (no history) and an empty league do nothing. */
            if (!g_hdr_seasons)
                return s;
            {
                int n = build_teamhist((long)g_hdr_seasons, (int)s.cat);
                if (s.row < n && g_th[s.row].season != 0) {
                    int32_t c = (int32_t)((long)g_hdr_seasons - g_th[s.row].season);
                    g_st_back = s;
                    g_st_have = 1;
                    return mk_state(SCREEN_STANDINGS, 0, c);
                }
            }
            return s;
        }
        if (s.screen == SCREEN_SERIES) {
            /* C64: the row's game opens its BOX SCORE, exactly what key '1' + g gives; the
             * summary row, the message row, a row past the end and no history do nothing */
            const ColDef *cols;
            if (!g_hdr_seasons)
                return s;
            {
                int n = series_body(s, -1, &cols);
                if (s.row < n && g_ser_game[s.row] >= 0)
                    return mk_state(SCREEN_BOX, 0, s.cat * 8 + g_ser_game[s.row]);
            }
            return s;
        }
        if (s.screen == SCREEN_PLAYOFFS) {
            /* C65: the row game's PLAYOFF BOX (the row's GAME, visitor or home row); a
             * title, summary, POSTSEASON LEADERS or message row, a row past the end, no
             * history and no round game keep the state. No static table: the GAME row is
             * the row itself, row - 1 or row - 2 (the first of those whose first cell
             * starts with "GAME "; a summary row is 3 below a GAME row, a title row sits
             * directly above one, so neither ever matches), and k = the number of GAME
             * rows before it: build_playoffs's rows come in the games' order, so the
             * GAME row count before a game's GAME row is the game's g_pl index. */
            const ColDef *cols;
            int n, gr = -1, seen = 0, i;
            if (!g_hdr_seasons)
                return s;
            n = playoffs_body(s, -1, &cols);
            if (s.row >= n)
                return s;
            if (strncmp(g_pser[s.row].cells[0], "GAME ", 5) == 0)
                gr = (int)s.row;
            else if (s.row >= 1
                     && strncmp(g_pser[s.row - 1].cells[0], "GAME ", 5) == 0)
                gr = (int)s.row - 1;
            else if (s.row >= 2
                     && strncmp(g_pser[s.row - 2].cells[0], "GAME ", 5) == 0)
                gr = (int)s.row - 2;
            if (gr < 0)
                return s;
            for (i = 0; i < gr; i++)
                if (strncmp(g_pser[i].cells[0], "GAME ", 5) == 0)
                    seen++;
            if (seen < g_pl_n)
                return mk_state(SCREEN_PBOX, 0,
                                (int32_t)(s.cat * 64 + g_pl[seen].g - PLAYOFF_G_MIN));
            return s;
        }
        {
            int32_t entry = row_entry(s);
            if (entry >= 0)
                return open_card(s, entry);
        }
        return s;
    }
    /* C28: H on SEASON AWARDS opens the AWARD HISTORY of the cursor row's award record
     * (kind (64, 96)[L] + k as the code L * 20 + k), or code 0 on any other row; the
     * awards state is kept for ESC */
    if (s.screen == SCREEN_AWARDS && (key == 72 || key == 104)) {
        long a = 0;
        g_awh_back = s;
        g_awh_have = 1;
        if (g_hdr_seasons) {
            /* the award and leader records of the shown season in (kind, file position)
             * order; the cursor row's kind is the code when it is an award record */
            int32_t season = (long)g_hdr_seasons - s.cat;
            int nrecs = 0, i;
            uint8_t K[AWARD_MAX * 2];
            for (i = 0; i < g_nms; i++) {
                if (g_ms[i].season != season
                    || (!award_kind(g_ms[i].kind) && !leader_kind(g_ms[i].kind)))
                    continue;
                {
                    int j = nrecs < AWARD_MAX * 2 ? nrecs : AWARD_MAX * 2 - 1;
                    while (j > 0 && K[j - 1] > g_ms[i].kind) {
                        K[j] = K[j - 1];
                        j--;
                    }
                    K[j] = g_ms[i].kind;
                    if (nrecs < AWARD_MAX * 2)
                        nrecs++;
                }
            }
            if (s.row < nrecs && award_kind(K[s.row])) {
                int lg = K[s.row] >= 96;
                a = lg * 20L + K[s.row] - (lg ? 96 : 64);
            }
        }
        return mk_state(SCREEN_AWHIST, 0, a);
    }
    if (s.screen == SCREEN_AWHIST && (key == KEY_LEFT || key == KEY_RIGHT)) {
        /* the previous (LEFT) or next (RIGHT) award code modulo 40 (page and row reset) */
        long a = s.cat + (key == KEY_RIGHT ? 1 : N_AWHIST_CODES - 1);
        return mk_state(SCREEN_AWHIST, 0, a % N_AWHIST_CODES);
    }
    /* WORLD SERIES keys 1..7: the box score of game key - 49 of the season (cat seasons
     * back) when the season is 1..64 and has that game; other keys leave it as it is */
    if (s.screen == SCREEN_SERIES && 49 <= key && key <= 55) {
        int g = (int)key - 49;
        long season = (long)g_hdr_seasons - s.cat;
        if (season >= 1 && season <= SEASON_COUNT && ws_game(season, g)) {
            s.screen = SCREEN_BOX;
            s.page = 0;
            s.cat = (int16_t)(s.cat * 8 + g);
        }
        return s;
    }
    /* BOX SCORE: LEFT and RIGHT step to the previous or next game of the season that has
     * a game record; none: the state is unchanged */
    if (s.screen == SCREEN_BOX && (key == KEY_LEFT || key == KEY_RIGHT)) {
        long season = (long)g_hdr_seasons - (s.cat >> 3);
        int g = s.cat & 7, k, to = -1;
        if (key == KEY_LEFT) {
            for (k = g - 1; k >= 0 && to < 0; k--)
                if (ws_game(season, k))
                    to = k;
        } else {
            for (k = g + 1; k < SERIES_GAMES && to < 0; k++)
                if (ws_game(season, k))
                    to = k;
        }
        if (to >= 0) {
            s.cat = (int16_t)((s.cat >> 3) * 8 + to);
            s.page = 0;
            return s;
        }
        /* LEFT on the season's first WS game with a record, when the season has round
         * games: the last round game's PLAYOFF BOX (dynview.step's BOX LEFT rule) */
        if (key == KEY_LEFT && season >= 1 && season <= SEASON_COUNT) {
            int first = -1, count, lastp;
            for (k = 0; k < SERIES_GAMES && first < 0; k++)
                if (ws_game(season, k))
                    first = k;
            if (first >= 0 && g == first && (count = playoff_headers(season)) > 0
                && (lastp = g_pl[count - 1].g) >= PLAYOFF_G_MIN) {
                return mk_state(SCREEN_PBOX, 0,
                                (int32_t)((s.cat >> 3) * 64 + lastp - PLAYOFF_G_MIN));
            }
        }
        return s;
    }

    if (s.screen == SCREEN_PBOX && (key == KEY_LEFT || key == KEY_RIGHT)) {
        /* to the previous (LEFT) or next (RIGHT) round game of the season (by g); RIGHT
         * past the last opens the first WORLD SERIES box of the season that has one */
        long season = (long)g_hdr_seasons - (s.cat >> 6);
        int g = (int)(s.cat & 63) + PLAYOFF_G_MIN, k, to = -1;
        if (season >= 1 && season <= SEASON_COUNT) {
            PlHdr hd;
            if (key == KEY_LEFT) {
                for (k = g - 1; k >= PLAYOFF_G_MIN && to < 0; k--)
                    if (playoff_header_of(season, k, &hd))
                        to = k;
            } else {
                for (k = g + 1; k <= PLAYOFF_G_MAX && to < 0; k++)
                    if (playoff_header_of(season, k, &hd))
                        to = k;
                if (to < 0) {
                    for (k = 0; k < SERIES_GAMES; k++)
                        if (ws_game(season, k))
                            return mk_state(SCREEN_BOX, 0,
                                            (int32_t)((s.cat >> 6) * 8 + k));
                }
            }
        }
        if (to >= PLAYOFF_G_MIN)
            return mk_state(SCREEN_PBOX, 0, (int32_t)((s.cat >> 6) * 64 + to - PLAYOFF_G_MIN));
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
    /* C66: HOME and END jump to the first and last page on screens without a row cursor */
    if (key == KEY_HOME) {
        s.page = 0;
        return s;
    }
    if (key == KEY_END) {
        int n = total_rows(s);
        s.page = n > 0 ? (n - 1) / ROWS_PER_PAGE : 0;
        return s;
    }
    /* C53: TAB on HALL OF FAME cycles the position filter; page and cursor reset.
     * Every other screen's TAB does nothing. */
    if (s.screen == SCREEN_HOF && key == KEY_TAB)
        return mk_state(SCREEN_HOF, 0, (s.cat + 1) % N_HOF_FILTERS);

    /* C54: A or a in CAREER mode flips the session-only active-only filter; page and row
     * reset, the category and the BY YEAR season stay. Other modes are untouched. */
    if (s.screen == SCREEN_LEADERS && (key == KEY_ACTIVE_CAP || key == KEY_ACTIVE_LOW)
        && (s.cat >> 5) == MODE_CAREER) {
        g_lead_active = !g_lead_active;
        s.page = 0;
        s.row = 0;
        return s;
    }
    if (s.screen == SCREEN_LEADERS && (key == KEY_LEFT || key == KEY_RIGHT)) {
        /* the category of the mode cycles; BY YEAR keeps its season (C13.3) */
        int d = (key == KEY_LEFT) ? -1 : 1;
        int mode = (int)(s.cat >> 5), idx = (int)(s.cat & 31);
        int n = leader_ncats(mode);
        return mk_state(SCREEN_LEADERS, 0, mode * MODE_SHIFT + (idx + d + n) % n);
    }
    /* TAB cycles the LEADERS mode CAREER -> SEASON -> BY YEAR -> POSTSEASON; the category
     * stays when the new mode has it (by label), else the first one. Entering BY YEAR picks
     * the default season */
    if (s.screen == SCREEN_LEADERS && key == KEY_TAB) {
        int mode = (int)(s.cat >> 5), idx = (int)(s.cat & 31), nmode = (mode + 1) % 4;
        const char *label = leader_cats(mode)[idx].label;
        int j, nidx = 0;
        State r;
        for (j = 0; j < leader_ncats(nmode); j++) {
            if (strcmp(leader_cats(nmode)[j].label, label) == 0) {
                nidx = j;
                break;
            }
        }
        r = mk_state(SCREEN_LEADERS, 0, nmode * MODE_SHIFT + nidx);
        if (nmode == MODE_BYYEAR)
            r.year = default_year();
        return r;
    }
    /* BY YEAR: '-' steps to the older season with lines, '+' or '=' to the newer; nothing past
     * either end (C13.3) */
    if (s.screen == SCREEN_LEADERS && (s.cat >> 5) == MODE_BYYEAR
        && (key == KEY_MINUS || key == KEY_PLUS || key == KEY_EQUALS)) {
        int32_t cur = leaders_year(s), to = 0;
        if (key == KEY_MINUS) {
            if (!season_near(cur, 0, &to))
                return s;
        } else if (!season_near(cur, 1, &to)) {
            return s;
        }
        s.row = 0;
        s.page = 0;
        s.year = to;
        return s;
    }
    /* SEASON AWARDS, SEASON STANDINGS and WORLD SERIES: LEFT goes back a season while the
     * shown one is above 1 (season = seasons recorded - cat), RIGHT forward; otherwise
     * the state is unchanged */
    /* MILESTONES (C27): LEFT and RIGHT toggle the mode (cat 0 milestones, cat 1 WATCH);
     * page and row reset. Other screens' season stepping first. */
    if (s.screen == SCREEN_MILESTONES && (key == KEY_LEFT || key == KEY_RIGHT))
        return mk_state(SCREEN_MILESTONES, 0, s.cat == 1 ? 0 : 1);
    /* C29 TEAM HISTORY keys */
    if (s.screen == SCREEN_STANDINGS && (key == 84 || key == 116)) {
        /* T opens the TEAM HISTORY of the lowest managed team id, else the first of
         * g_teams (nothing happens with no teams). The standings state is kept for ESC,
         * the cursor row included (C57). */
        int first = -1, i;
        if (g_nteams == 0)
            return s;
        for (i = 0; i < g_nteams; i++)
            if (g_tlg[i] < 32 && ((g_mask >> g_tlg[i]) & 1u) != 0
                && (first < 0 || g_tlg[i] < g_tlg[first]))
                first = i;
        g_th_back = mk_state(SCREEN_STANDINGS, s.page, s.cat);
        g_th_back.row = s.row;
        g_th_live = 1;
        return mk_state(SCREEN_TEAMHIST, 0, g_tlg[first >= 0 ? first : 0]);
    }
    if (s.screen == SCREEN_TEAMHIST && (key == KEY_LEFT || key == KEY_RIGHT)) {
        /* LEFT / RIGHT step to the previous / next id of the MAJ teams (the listed order),
         * wrapping; the page resets to 0 */
        int k = 0, d, i;
        for (i = 0; i < g_nteams; i++)
            if (g_tlg[i] == s.cat)
                k = i;
        d = key == KEY_LEFT ? (k + g_nteams - 1) % g_nteams : (k + 1) % g_nteams;
        return mk_state(SCREEN_TEAMHIST, 0, g_tlg[d]);
    }
    if (season_screen(s.screen) && key == KEY_LEFT) {
        if ((long)g_hdr_seasons - s.cat > 1) {
            s.cat = (int16_t)(s.cat + 1);
            s.page = 0;
            s.row = 0;
        }
        return s;
    }
    if (season_screen(s.screen) && key == KEY_RIGHT) {
        if (s.cat > 0) {
            s.cat = (int16_t)(s.cat - 1);
            s.page = 0;
            s.row = 0;
        }
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

/* WATCH (C27) */
static const ColDef COLS_WATCH[] = {
    { "NAME", CX(0), 16, 0 }, { "MARK", CX(17), 9, 0 },
    { "NOW", CX(27), 6, 1 }, { "NEED", CX(35), 6, 1 } };

static const ColDef COLS_RETIRE[] = {
    { "NAME", CX(0), 18, 0 }, { "AGE", CX(18), 5, 1 }, { "YRS", CX(23), 5, 1 },
    { "WAR", CX(28), 7, 1 }, { "HOF", CX(36), 6, 1 } };

static const ColDef COLS_SETTINGS[] = {
    { "SETTING", CX(0), 24, 0 }, { "VALUE", CX(26), 16, 0 } };

static const ColDef COLS_DRAFT[] = {
    { "#", CX(0), 4, 0 }, { "TEAM", CX(4), 13, 0 }, { "POS", CX(18), 3, 0 },
    { "PLAYER", CX(22), 20, 0 } };

static const ColDef COLS_MOVE[] = {
    { "TEAM", CX(0), 13, 0 }, { "PLAYER", CX(14), 15, 0 }, { "FROM", CX(30), 12, 0 } };

static const ColDef COLS_AWARDS[] = {
    { "AWARD", CX(0), 13, 0 }, { "NAME", CX(14), 16, 0 }, { "VALUE", CX(30), 12, 1 } };

/* AWARD HISTORY (C28) */
static const ColDef COLS_AWHIST[] = {
    { "YEAR", CX(0), 4, 0 }, { "NAME", CX(5), 16, 0 }, { "VALUE", CX(22), 20, 1 } };

static const ColDef COLS_STANDINGS[] = {
    { "TEAM", CX(0), 17, 0 }, { "W", CX(17), 5, 1 }, { "L", CX(22), 5, 1 },
    { "PCT", CX(27), 6, 1 }, { "GB", CX(33), 6, 1 }, { " ", CX(39), 3, 1 } };

static const ColDef COLS_SERIES[] = {
    { "TEAM", CX(0), 17, 0 }, { "R", CX(17), 5, 1 }, { "H", CX(22), 5, 1 },
    { "E", CX(27), 5, 1 }, { " ", CX(32), 10, 1 } };

static const ColDef COLS_BOX[] = {
    { " ", CX(0), 18, 0 }, { " ", CX(18), 4, 1 }, { " ", CX(22), 4, 1 },
    { " ", CX(26), 4, 1 }, { " ", CX(30), 4, 1 }, { " ", CX(34), 4, 1 },
    { " ", CX(38), 4, 1 } };

static const ColDef COLS_SEASON_LEADERS[] = {
    { "#", CX(0), 4, 0 }, { "NAME", CX(4), 16, 0 }, { "YEAR", CX(20), 5, 1 },
    { "TEAM", CX(25), 4, 1 }, { "VALUE", CX(29), 12, 1 } };

/* POSTSEASON LEADERS (C39), the career table's shape with G for YRS */
static const ColDef COLS_POST_LEADERS[] = {
    { "#", CX(0), 5, 0 }, { "NAME", CX(5), 16, 0 }, { " ", CX(22), 1, 0 },
    { "G", CX(23), 5, 1 }, { "VALUE", CX(28), 14, 1 } };

/* FIND PLAYER (C50) */
static const ColDef COLS_FIND[4] = {
    { "NAME", CX(0), 20, 0 }, { "POS", CX(21), 3, 0 }, { "YRS", CX(25), 3, 1 },
    { "STATUS", CX(30), 12, 0 } };

/* C29 TEAM HISTORY */
static const ColDef COLS_TEAMHIST[] = {
    { "YEAR", CX(0), 4, 0 }, { "W", CX(5), 4, 1 }, { "L", CX(10), 4, 1 },
    { "PCT", CX(15), 5, 1 }, { "FINISH", CX(22), 6, 0 },
    { "RESULT", CX(30), 12, 0 } };

/* PLAYER CARD season tables (C13.5): batters and pitchers */
static const ColDef COLS_CARD_BAT[] = {
    { "YEAR", CX(0), 4, 0 }, { "TM", CX(4), 4, 1 }, { "G", CX(8), 4, 1 },
    { "AB", CX(12), 5, 1 }, { "H", CX(17), 4, 1 }, { "HR", CX(21), 4, 1 },
    { "RBI", CX(25), 4, 1 }, { "SB", CX(29), 4, 1 }, { "AVG", CX(33), 5, 1 },
    { "WAR", CX(38), 5, 1 } };

static const ColDef COLS_CARD_PIT[] = {
    { "YEAR", CX(0), 4, 0 }, { "TM", CX(4), 4, 1 }, { "G", CX(8), 4, 1 },
    { "W", CX(12), 3, 1 }, { "L", CX(15), 3, 1 }, { "SV", CX(18), 4, 1 },
    { "IP", CX(22), 6, 1 }, { "SO", CX(28), 4, 1 }, { "ERA", CX(32), 5, 1 },
    { "WAR", CX(37), 5, 1 } };

#define NCOLS(a) ((int)(sizeof(a) / sizeof((a)[0])))

static int n_cols(const ColDef *cols)
{
    if (cols == COLS_SINGLE)
        return NCOLS(COLS_SINGLE);
    if (cols == COLS_WATCH)
        return NCOLS(COLS_WATCH);
    if (cols == COLS_FIND)
        return NCOLS(COLS_FIND);
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
    if (cols == COLS_SETTINGS)
        return NCOLS(COLS_SETTINGS);
    if (cols == COLS_AWARDS)
        return NCOLS(COLS_AWARDS);
    if (cols == COLS_AWHIST)
        return NCOLS(COLS_AWHIST);
    if (cols == COLS_STANDINGS)
        return NCOLS(COLS_STANDINGS);
    if (cols == COLS_SERIES)
        return NCOLS(COLS_SERIES);
    if (cols == COLS_BOX)
        return NCOLS(COLS_BOX);
    if (cols == COLS_SEASON_LEADERS)
        return NCOLS(COLS_SEASON_LEADERS);
    if (cols == COLS_POST_LEADERS)
        return NCOLS(COLS_POST_LEADERS);
    if (cols == COLS_TEAMHIST)
        return NCOLS(COLS_TEAMHIST);
    if (cols == COLS_CARD_BAT)
        return NCOLS(COLS_CARD_BAT);
    if (cols == COLS_CARD_PIT)
        return NCOLS(COLS_CARD_PIT);
    if (cols == COLS_HONORS)
        return NCOLS(COLS_HONORS);
    return NCOLS(COLS_MILESTONES);
}

static const ColDef *body_cols(State st)
{
    /* the one-cell 'NO DYNASTY HISTORY YET' row always uses COLS_SINGLE so it
     * is never cut to a narrow first column. The offseason's per-phase columns
     * come from offseason_body, which refresh_rows calls after this. SETTINGS
     * shows its columns and ABOUT its rows with no history too. */
    if (st.screen == SCREEN_SETTINGS)
        return COLS_SETTINGS;
    if (g_hdr_seasons == 0 || st.screen == SCREEN_ABOUT)
        return COLS_SINGLE;
    switch (st.screen) {
    case SCREEN_MENU:
        return COLS_SINGLE;
    case SCREEN_HISTORY:
        return COLS_HISTORY;
    case SCREEN_HOF:
        /* C53: the filtered-empty message row uses COLS_SINGLE */
        hof_scan(&g_hofl, (int)st.cat);
        return g_hofl.n == 0 && st.cat != 0 ? COLS_SINGLE : COLS_HOF;
    case SCREEN_LEADERS:
        return COLS_LEADERS;
    case SCREEN_FIND:
        return g_find_q[0] ? COLS_FIND : COLS_SINGLE;
    case SCREEN_MILESTONES: {
        /* WATCH: the message row (no item) uses COLS_SINGLE, as the cursors do (C15.8) */
        if (st.cat == 1) {
            watch_scan();
            return g_nwatch ? COLS_WATCH : COLS_SINGLE;
        }
        return COLS_MILESTONES;
    }
    case SCREEN_AWARDS:
        return COLS_AWARDS;
    case SCREEN_AWHIST:
        return COLS_AWHIST;
    case SCREEN_STANDINGS:
        return COLS_STANDINGS;
    case SCREEN_SERIES:
        return COLS_SERIES;
    case SCREEN_BOX:
        return COLS_BOX;
    case SCREEN_PLAYOFFS: {
        const ColDef *c2;
        playoffs_body(st, -1, &c2);
        return c2;
    }
    case SCREEN_PBOX:
        return COLS_SERIES;
    case SCREEN_TEAMHIST: {
        const ColDef *c2;
        teamhist_body(st, -1, &c2);
        return c2;
    }
    default:
        return COLS_SINGLE;
    }
}

/* LEADERS (C13.3, C39, dynview.leaders_body): the row count of st's mode and category; the rows
 * of page into g_rows (page < 0 counts only) and their columns into *cols. A season mode with
 * no line of the season (SEASON: no line at all) is one NO_LINES_TEXT row; POST with no item
 * (value > 0) one NO_POST_TEXT row */
static int leaders_body(State st, int page, const ColDef **cols)
{
    int mode = (int)(st.cat >> 5), idx = (int)(st.cat & 31), seen = 0, n;
    int by_year = mode == MODE_BYYEAR;
    const CatDef *c;
    if (mode == MODE_CAREER) {
        leaders_scan(&g_leadl, idx);
        if (g_lead_active && g_leadl.n == 0) {
            *cols = COLS_SINGLE;
            return msg_row(page, "NO ACTIVE QUALIFIERS.");
        }
        *cols = COLS_LEADERS;
        if (page >= 0)
            build_lead_rows(idx, page);
        return (int)g_leadl.n;
    }
    if (mode == MODE_POST) {
        c = &POST_CATS[idx];
        n = post_scan(c);
        if (n == 0) {
            *cols = COLS_SINGLE;
            return msg_row(page, NO_POST_TEXT);
        }
        *cols = COLS_POST_LEADERS;
        if (page >= 0)
            build_post_rows(c, page);
        return n;
    }
    c = &SEASON_CATS[idx];
    n = season_scan(c, by_year, by_year ? leaders_year(st) : 0, &seen);
    if (seen == 0) {
        *cols = COLS_SINGLE;
        return msg_row(page, NO_LINES_TEXT);
    }
    *cols = COLS_SEASON_LEADERS;
    if (page >= 0)
        build_season_rows(c, by_year, page);
    return n;
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
        pos_cache_reset();
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
        roster_count();             /* final fa count first: a release's ord is fa + k */
        roster_pass(OFF_FA, page);
        total = capped(g_rc.fa + g_rc.rel);
        if (total == 0)
            return msg_row(page, "NO SIGNINGS OR RELEASES");
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

/* SEASON AWARDS page: the rows of the season cat seasons back from the newest into
 * g_rows for page (page < 0 counts only). Returns the row count; *cols is COLS_SINGLE
 * for the lone message row and with no history, else COLS_AWARDS. */
static int awards_body(State st, int page, const ColDef **cols)
{
    int n, k, r;
    *cols = COLS_AWARDS;
    if (g_hdr_seasons == 0) {
        *cols = COLS_SINGLE;
        return 0;
    }
    n = build_awards((long)g_hdr_seasons - st.cat);
    if (n == 1 && g_awd[0].ncells == 1)
        *cols = COLS_SINGLE;
    if (page >= 0) {
        for (k = 0, r = page * ROWS_PER_PAGE; r < n && k < ROWS_PER_PAGE; r++, k++)
            g_rows[k] = g_awd[r];
    }
    return n;
}

/* AWARD HISTORY page (C28): the rows of the award code st.cat into g_rows for page
 * (page < 0 counts only). Returns the row count; *cols is COLS_SINGLE for the lone
 * message row and with no history, else COLS_AWHIST. */
static int awhist_body(State st, int page, const ColDef **cols)
{
    int n, k, r;
    *cols = COLS_AWHIST;
    if (g_hdr_seasons == 0) {
        *cols = COLS_SINGLE;
        return 0;
    }
    n = build_awhist(st.cat);
    if (n == 0) {
        *cols = COLS_SINGLE;
        if (page == 0) {
            strcpy(g_rows[0].cells[0], "NO WINNERS RECORDED");
            g_rows[0].ncells = 1;
        }
        return 1;
    }
    if (page >= 0) {
        for (k = 0, r = page * ROWS_PER_PAGE; r < n && k < ROWS_PER_PAGE; r++, k++)
            awhist_row(r, &g_rows[k]);
    }
    return n;
}

/* SEASON STANDINGS page: the rows of the season cat seasons back from the newest into
 * g_rows for page (page < 0 counts only). Returns the row count; *cols is COLS_SINGLE
 * for the lone message row and with no history, else COLS_STANDINGS. */
static int standings_body(State st, int page, const ColDef **cols)
{
    int n, k, r;
    *cols = COLS_STANDINGS;
    if (g_hdr_seasons == 0) {
        *cols = COLS_SINGLE;
        return 0;
    }
    n = build_standings((long)g_hdr_seasons - st.cat);
    if (n == 1 && g_stnd[0].ncells == 1)
        *cols = COLS_SINGLE;
    if (page >= 0) {
        for (k = 0, r = page * ROWS_PER_PAGE; r < n && k < ROWS_PER_PAGE; r++, k++)
            g_rows[k] = g_stnd[r];
    }
    return n;
}

/* WORLD SERIES page: the rows of the season cat seasons back from the newest into
 * g_rows for page (page < 0 counts only). Returns the row count; *cols is COLS_SINGLE
 * for the lone message row and with no history, else COLS_SERIES. */
static int series_body(State st, int page, const ColDef **cols)
{
    int n, k, r;
    *cols = COLS_SERIES;
    if (g_hdr_seasons == 0) {
        *cols = COLS_SINGLE;
        return 0;
    }
    n = build_series((long)g_hdr_seasons - st.cat);
    if (n == 1 && g_ser[0].ncells == 1)
        *cols = COLS_SINGLE;
    if (page >= 0) {
        for (k = 0, r = page * ROWS_PER_PAGE; r < n && k < ROWS_PER_PAGE; r++, k++)
            g_rows[k] = g_ser[r];
    }
    return n;
}

/* BOXSCORE.DAT streamed once (LEAGUE_DIR): the first BOX_MAX_RECS records of (season, g)
 * into g_box in file order; returns their count, 0 when the file is missing or unreadable */
static int box_recs(long season, int g)
{
    char path[600];
    FILE *f;
    uint8_t rb[16];
    int n = 0;
    path_join(path, g_lgdir, "BOXSCORE.DAT");
    f = fopen(path, "rb");
    if (!f)
        return 0;
    while (fread(rb, 1, sizeof rb, f) == sizeof rb) {
        BoxRec rec;
        rec.season = (uint16_t)(rb[0] | ((uint16_t)rb[1] << 8));
        rec.g = rb[2];
        rec.flags = rb[3];
        rec.idx = (uint16_t)(rb[4] | ((uint16_t)rb[5] << 8));
        rec.b = rb[6];
        rec.i = rb[7];
        memcpy(rec.s, rb + 8, 8);
        if (rec.season != season || rec.g != g)
            continue;
        if (n == BOX_MAX_RECS)
            break;
        g_box[n++] = rec;
    }
    if (ferror(f))
        n = 0;
    fclose(f);
    return n;
}

/* the g_rows slot of the next box row (*ord counts the rows from 0), NULL when page does
 * not show it */
static Row *box_next(int *ord, int page)
{
    int r = *ord - page * ROWS_PER_PAGE;
    (*ord)++;
    if (page < 0 || r < 0 || r >= ROWS_PER_PAGE)
        return NULL;
    return &g_rows[r];
}

/* a row of seven cells */
static void box_set(Row *row, const char *c0, const char *c1, const char *c2,
                    const char *c3, const char *c4, const char *c5, const char *c6)
{
    strcpy(row->cells[0], c0);
    strcpy(row->cells[1], c1);
    strcpy(row->cells[2], c2);
    strcpy(row->cells[3], c3);
    strcpy(row->cells[4], c4);
    strcpy(row->cells[5], c5);
    strcpy(row->cells[6], c6);
    row->ncells = 7;
}

/* g_box_idx (the C62 row cursor entries); one table for both box screens */
static int16_t *box_idx_base(void)
{
    return g_box_idx;
}

/* every entry off (-1): a fresh walk starts all headers */
static void box_idx_clear(void)
{
    memset(box_idx_base(), 0xff, (BOX_MAX_RECS + 4) * sizeof(int16_t));
}

/* the record idx of player row ord as the card target (-1 on '?' or a header) */
static void box_idx_put(int ord, const BoxRec *r)
{
    int16_t ix = -1;
    if (r->idx != NO_AWARD && (uint32_t)r->idx < n_entries())
        ix = (int16_t)r->idx;
    box_idx_base()[ord] = ix;
}

/* the batting row (pitch 0) or pitching row (pitch 1) of record r: NAME ('?' for entry
 * 0xffff), then stats 0, 1, 2, 3, 5, 6 (IP as d.d for a pitching row) */
static void box_rec_row(Row *row, const BoxRec *r, int pitch)
{
    static const uint8_t slot[6] = { 0, 1, 2, 3, 5, 6 };
    int k;
    if (r->idx == NO_AWARD)
        strcpy(row->cells[0], "?");
    else
        entry_name(r->idx, 18, row->cells[0]);
    for (k = 0; k < 6; k++) {
        unsigned v = r->s[slot[k]];
        if (k == 0 && pitch)
            sprintf(row->cells[1], "%u.%u", v / 10, v % 10);
        else
            sprintf(row->cells[k + 1], "%u", v);
    }
    row->ncells = 7;
}

/* BOX SCORE page: the rows of game st.cat & 7 of the season st.cat >> 3 seasons back from
 * the newest (dynview.box_rows) into g_rows for page (page < 0 counts only). Per side: a
 * team row, its batting rows, a PITCHING row and its pitching rows. Returns the row count;
 * *cols is COLS_SINGLE for the message row and with no history, else COLS_BOX. */
static int box_body(State st, int page, const ColDef **cols)
{
    int g = st.cat & 7, n = 0, ord = 0, t, k;
    long season = (long)g_hdr_seasons - (st.cat >> 3);
    uint16_t gidx = 0, gval = 0;
    *cols = COLS_BOX;
    if (g_hdr_seasons == 0) {
        *cols = COLS_SINGLE;
        return 0;
    }
    if (season <= SEASON_COUNT && ms_first(season, SERIES_GAME_KIND + g, &gidx, &gval)) {
        if (season != g_box_season || g != g_box_g) {
            g_box_n = box_recs(season, g);
            g_box_season = season;
            g_box_g = g;
        }
        n = g_box_n;
    }
    box_idx_clear();
    if (n == 0) {
        *cols = COLS_SINGLE;
        return msg_row(page, "NO BOX SCORE RECORDED");
    }
    for (t = 0; t < 2; t++) {
        uint16_t tid = t == 0 ? (uint16_t)(gidx >> 8) : (uint16_t)(gidx & 255);
        int pitch;
        Row *row = box_next(&ord, page);
        if (row) {
            char nm[SLEN];
            stand_name_plain(tid, nm);
            box_set(row, nm, "AB", "R", "H", "RBI", "BB", "SO");
        }
        for (pitch = 0; pitch < 2; pitch++) {
            if (pitch) {
                row = box_next(&ord, page);
                if (row)
                    box_set(row, "PITCHING", "IP", "H", "R", "ER", "BB", "SO");
            }
            for (k = 0; k < n; k++) {
                const BoxRec *r = &g_box[k];
                if ((r->flags & 1) != t || ((r->flags >> 1) & 1) != pitch)
                    continue;
                box_idx_put(ord, r);
                row = box_next(&ord, page);
                if (row)
                    box_rec_row(row, r, pitch);
            }
        }
    }
    return ord;
}

/* 1 when entry names a player of the history (PLAYER CARD, C13.5) */
static int card_valid(int32_t entry)
{
    return entry >= 0 && (uint32_t)entry < n_entries();
}

/* the card's player name (dynview.card_name): first then last, upper case, '?' when blank */
static void card_name(const Entry *e, char *dst)
{
    char first[9], last[13];
    int i;
    field_of(e->name + 12, 8, first);
    field_of(e->name, 12, last);
    dst[0] = 0;
    if (first[0])
        strcpy(dst, first);
    if (first[0] && last[0])
        strcat(dst, " ");
    if (last[0])
        strcat(dst, last);
    if (!dst[0]) {
        strcpy(dst, "?");
        return;
    }
    for (i = 0; dst[i]; i++)
        dst[i] = (char)ascii_up((uint8_t)dst[i]);
}

/* ---------------- PLAYER CARD HONORS view (C40) ---------------- */

/* the HONORS rows a page: the season table's 9 middle rows between the header and CAREER */
#define HONOR_ROWS 9
#define HONOR_FALLBACK_ORDER 100000
#define HONOR_MAX 240    /* 240 * 74 B: a 20-season career with every honor fits */

/* HONORS columns: YEAR where the season table's first five are, HONOR on from it */
static const ColDef COLS_HONORS[] = {
    { "YEAR", CX(0), 5, 0 }, { "HONOR", CX(5), 37, 0 } };

/* one honor item before the (season, group, order) sort: the text is the HONOR cell */
typedef struct {
    int32_t season;
    int group;
    int32_t order;
    char text[SLEN];
} HonorItem;

static HonorItem FARDATA g_honor[HONOR_MAX];

/* all the HONORS texts of entry into g_honor in display order; the count is returned
 * (dynview.honors_items): group 0 the MILESTON.DAT records with idx == entry (award
 * records the award label, leader records the leader label and value, milestone records
 * the event text, other kinds skipped; order the file position) and the six
 * AWARD_FALLBACK winners of seasons without award or leader records (order 100000 + k);
 * group 1 the HALL OF FAME row of a status 3 entry at its hof_season. Seasons read only
 * to the season table (SEASON_COUNT records), like the C7 fallback. The insertion sort
 * keeps equal keys in the order the items were added (award records in file order, then
 * the fallback items, then the HOF item). */
static int honors_collect(int32_t entry)
{
    int32_t i;
    int season, k, n = 0;
    Entry e;
    uint8_t seen[SEASON_COUNT];
    HonorItem tmp;
    memset(seen, 0, sizeof seen);
    if (!card_valid(entry) || !read_entry(&e, (uint32_t)entry))
        return 0;
    for (i = 0; i < g_nms && n < HONOR_MAX; i++) {
        const MsRec *rec = &g_ms[i];
        int j;
        if ((int32_t)rec->idx != entry)
            continue;
        if (award_kind(rec->kind) || leader_kind(rec->kind)) {
            if (rec->season >= 1 && rec->season <= SEASON_COUNT)
                seen[rec->season - 1] = 1;
        } else if (rec->kind >= AWARD_KIND_MIN) {
            continue;                           /* other kinds are skipped */
        }
        tmp.season = rec->season;
        tmp.group = 0;
        tmp.order = (int32_t)i;
        if (leader_kind(rec->kind)) {
            leader_label(rec->kind, tmp.text);
            strcat(tmp.text, " ");
            leader_value(rec->kind, rec->value, tmp.text + strlen(tmp.text));
        } else if (award_kind(rec->kind)) {
            award_label(rec->kind, tmp.text);
        } else {
            event_text(rec->kind, (int32_t)rec->value, tmp.text);
        }
        j = n++;
        while (j > 0 && (g_honor[j - 1].season > tmp.season
                         || (g_honor[j - 1].season == tmp.season && g_honor[j - 1].group > tmp.group)
                         || (g_honor[j - 1].season == tmp.season
                             && g_honor[j - 1].group == tmp.group
                             && g_honor[j - 1].order > tmp.order))) {
            g_honor[j] = g_honor[j - 1];
            j--;
        }
        g_honor[j] = tmp;
    }
    for (season = 1; season <= (int)g_hdr_seasons && season <= SEASON_COUNT
             && n < HONOR_MAX; season++) {
        SeasonEntry se;
        if (seen[season - 1])
            continue;
        read_season(&se, season);
        for (k = 0; k < 6 && n < HONOR_MAX; k++) {
            int j;
            if (se.awards[k] != (uint16_t)entry)
                continue;
            tmp.season = season;
            tmp.group = 0;
            tmp.order = HONOR_FALLBACK_ORDER + k;
            strcpy(tmp.text, AWARD_FALLBACK[k]);
            j = n++;
            while (j > 0 && (g_honor[j - 1].season > tmp.season
                             || (g_honor[j - 1].season == tmp.season
                                 && g_honor[j - 1].group > tmp.group)
                             || (g_honor[j - 1].season == tmp.season
                                 && g_honor[j - 1].group == tmp.group
                                 && g_honor[j - 1].order > tmp.order))) {
                g_honor[j] = g_honor[j - 1];
                j--;
            }
            g_honor[j] = tmp;
        }
    }
    if (e.status == STATUS_HOF && n < HONOR_MAX) {
        int j;
        tmp.season = e.hof_season;
        tmp.group = 1;
        tmp.order = 0;
        strcpy(tmp.text, "HALL OF FAME");
        j = n++;
        while (j > 0 && (g_honor[j - 1].season > tmp.season
                         || (g_honor[j - 1].season == tmp.season
                             && g_honor[j - 1].group > tmp.group))) {
            g_honor[j] = g_honor[j - 1];
            j--;
        }
        g_honor[j] = tmp;
    }
    return n;
}

/* the HONORS row count of entry (dynview.total_rows on the HONORS view): the first row
 * plus the collected texts, paged HONOR_ROWS a page */
static int honors_rows_count(int32_t entry)
{
    int n = honors_collect(entry) + 1;
    return n;
}

/* the (YEAR, HONOR) rows of the HONORS view of entry into g_rows (page first, dynview.
 * honors_rows): the career award counts first, then the collected texts with their YEAR
 * cells. The first row shows on an entry with no item too. Returns the page's row count. */
static int honors_rows(int32_t entry, int page)
{
    Entry e;
    int n, r, at;
    if (page == 0) {
        strcpy(g_rows[0].cells[0], "");
        if (card_valid(entry) && read_entry(&e, (uint32_t)entry))
            sprintf(g_rows[0].cells[1], "MVP %u  CY %u  ROY %u  GG %u  SS %u",
                    (unsigned)e.awards[0], (unsigned)e.awards[1], (unsigned)e.awards[2],
                    (unsigned)e.awards[3], (unsigned)e.awards[4]);
        else
            strcpy(g_rows[0].cells[1], "MVP 0  CY 0  ROY 0  GG 0  SS 0");
        g_rows[0].ncells = 2;
    }
    n = honors_collect(entry);
    for (r = 0, at = (page == 0 ? 1 : 0); r + at < HONOR_ROWS; r++) {
        int k = page * HONOR_ROWS + r - (page ? 1 : 0);  /* the full-row index -> item */
        if (k < 0 || k >= n)
            break;
        year_text(g_honor[k].season, g_rows[r + at].cells[0]);
        strcpy(g_rows[r + at].cells[1], g_honor[k].text);
        g_rows[r + at].ncells = 2;
    }
    return r + at;
}

/* footer line: the offseason's ENTER label follows its phase, FIND PLAYER's ESC label
 * follows the query (C59) */
static const char *footer_of(State st)
{
    static const char *footers[6] = {
        "ENTER 0-9 W P F SELECT   ESC EXIT",
        "ENTER STANDINGS   PGUP PGDN   ESC MENU",
        "TAB POSITION   PGUP PGDN   ESC MENU",
        "LEFT RIGHT  TAB MODE  A ACTIVE  ENTER CARD",
        "ENTER CARD  LEFT RIGHT WATCH  PGUP PGDN  ESC",
        "ENTER MENU   ESC MENU" };
    if (st.screen == SCREEN_FIND)
        return g_find_q[0] ? "TYPE NAME  BKSP  ENTER CARD  ESC CLEAR"
                           : "TYPE NAME  BKSP  ENTER CARD  ESC MENU";
    if (st.screen == SCREEN_LEADERS && (st.cat >> 5) == MODE_BYYEAR)
        return "LEFT RIGHT STAT  - + YEAR  TAB MODE";
    if (st.screen == SCREEN_MILESTONES && st.cat == 1)
        return "ENTER CARD  LEFT RIGHT MODE  PGUP PGDN  ESC";
    if (st.screen == SCREEN_CARD)
        return st.row ? "LEFT RIGHT  PGUP PGDN  H SEASONS  ESC"
                      : "LEFT RIGHT  PGUP PGDN  H HONORS  ESC";
    if (st.screen == SCREEN_MENU && (st.cat >> 4))
        return g_hdr_seasons == 0 ? "ENTER PLAY BALL"
                                  : "ENTER 0-9 W SELECT   C PLAY BALL";
    if (st.screen == SCREEN_SETTINGS)
        return "UP DOWN MOVE   ENTER CHANGE   ESC MENU";
    if (st.screen == SCREEN_ABOUT)
        return "PGUP PGDN   ESC MENU";
    if (st.screen == SCREEN_AWARDS)
        return "H HISTORY  LEFT RIGHT SEASON  PGUP PGDN  ESC";
    if (st.screen == SCREEN_AWHIST)
        return "ENTER CARD  LEFT RIGHT AWARD  PGUP PGDN  ESC";
    if (st.screen == SCREEN_STANDINGS)
        return "ENTER TEAM  LEFT RIGHT SEASON  PGUP PGDN ESC";
    if (st.screen == SCREEN_TEAMHIST)
        return "ENTER SEASON  LEFT RIGHT TEAM  PGUP PGDN ESC";
    if (st.screen == SCREEN_SERIES)
        return "ENTER BOX  LEFT RIGHT SEASON  PGUP PGDN  ESC";
    if (st.screen == SCREEN_BOX)
        return "ENTER CARD  LEFT RIGHT GAME  PGUP PGDN  ESC";
    if (st.screen == SCREEN_PLAYOFFS)
        return "ENTER BOX  LEFT RIGHT SEASON  PGUP PGDN  ESC";
    if (st.screen == SCREEN_PBOX)
        return "ENTER CARD  LEFT RIGHT GAME  PGUP PGDN  ESC";
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
        sprintf(dst, "DYNASTY MODE: %ld", (long)year_of((int32_t)g_hdr_seasons + 1));
    else if (st.screen == SCREEN_MENU)
        strcpy(dst, "DYNASTY");
    else if (st.screen == SCREEN_HISTORY)
        strcpy(dst, "SEASON HISTORY");
    else if (st.screen == SCREEN_HOF) {
        /* C53: the filter label after 'HALL OF FAME: ' when the cat is not ALL */
        if (st.cat != 0) {
            strcpy(dst, "HALL OF FAME: ");
            strcat(dst, HOF_FILTER_LABELS[st.cat]);
        } else {
            strcpy(dst, "HALL OF FAME");
        }
    }
    else if (st.screen == SCREEN_LEADERS) {
        int mode = (int)(st.cat >> 5);
        const char *label = leader_cats(mode)[st.cat & 31].label;
        if (mode == MODE_CAREER) {
            strcpy(dst, g_lead_active ? "ACTIVE LEADERS: " : "CAREER LEADERS: ");
            strcat(dst, label);
        } else if (mode == MODE_SEASON) {
            strcpy(dst, "SEASON LEADERS: ");
            strcat(dst, label);
        } else if (mode == MODE_POST) {
            strcpy(dst, "POSTSEASON LEADERS: ");
            strcat(dst, label);
        } else
            sprintf(dst, "%ld LEADERS: %s", (long)year_of(leaders_year(st)), label);
    } else if (st.screen == SCREEN_CARD) {
        /* the player's name, first then last, upper case; '?' for no entry (C13.5) */
        if (!card_valid(st.cat))
            strcpy(dst, "?");
        else {
            Entry e;
            read_entry(&e, (uint32_t)st.cat);
            card_name(&e, dst);
        }
    } else if (st.screen == SCREEN_FIND) {
        strcpy(dst, "FIND PLAYER: ");
        strcat(dst, g_find_q);
        strcat(dst, "_");
    } else if (st.screen == SCREEN_MILESTONES)
        strcpy(dst, st.cat == 1 ? "MILESTONE WATCH" : "MILESTONES");
    else if (st.screen == SCREEN_SETTINGS)
        strcpy(dst, "DYNASTY SETTINGS");
    else if (st.screen == SCREEN_ABOUT)
        sprintf(dst, "ABOUT THE MODS %d/%d", st.page + 1,
                (N_ABOUT_ROWS + ROWS_PER_PAGE - 1) / ROWS_PER_PAGE);
    else if (st.screen == SCREEN_AWARDS) {
        /* no recorded season: no season number to show (it would read a year of 0) */
        if (g_hdr_seasons)
            sprintf(dst, "%ld AWARDS", (long)year_of((int32_t)g_hdr_seasons - st.cat));
        else
            strcpy(dst, "SEASON AWARDS");
    } else if (st.screen == SCREEN_STANDINGS) {
        if (g_hdr_seasons)
            sprintf(dst, "%ld STANDINGS", (long)year_of((int32_t)g_hdr_seasons - st.cat));
        else
            strcpy(dst, "SEASON STANDINGS");
    } else if (st.screen == SCREEN_TEAMHIST) {
        teamhist_title(st, dst);
    } else if (st.screen == SCREEN_SERIES) {
        if (g_hdr_seasons)
            sprintf(dst, "%ld WORLD SERIES", (long)year_of((int32_t)g_hdr_seasons - st.cat));
        else
            strcpy(dst, "WORLD SERIES");
    } else if (st.screen == SCREEN_BOX) {
        if (g_hdr_seasons)
            sprintf(dst, "%ld WS GAME %d",
                    (long)year_of((int32_t)g_hdr_seasons - (st.cat >> 3)), (st.cat & 7) + 1);
        else
            strcpy(dst, "WS BOX SCORE");
    }
    else if (st.screen == SCREEN_PLAYOFFS) {
        if (g_hdr_seasons)
            sprintf(dst, "%ld PLAYOFFS", (long)year_of((int32_t)g_hdr_seasons - st.cat));
        else
            strcpy(dst, "PLAYOFFS");
    }
    else if (st.screen == SCREEN_PBOX) {
        /* '%d %s %s GAME %d' of the round game's header; PLAYOFF BOX SCORE without a
         * season or without the header */
        if (g_hdr_seasons) {
            PlHdr hd;
            long season = (long)g_hdr_seasons - (st.cat >> 6);
            int g = (int)(st.cat & 63) + PLAYOFF_G_MIN;
            if (season >= 1 && season <= SEASON_COUNT
                && playoff_header_of(season, g, &hd)) {
                int rnd = hd.b & 3, L = (hd.b >> 2) & 1;
                sprintf(dst, "%ld %s %s GAME %d",
                        (long)year_of((int32_t)season), L ? "NL" : "AL",
                        rnd == 2 ? "LCS" : "DS", hd.i);
            } else {
                strcpy(dst, "PLAYOFF BOX SCORE");
            }
        } else {
            strcpy(dst, "PLAYOFF BOX SCORE");
        }
    }
    else if (st.screen == SCREEN_AWHIST) {
        /* C28: the award label of the code (L * 20 + k) + ' HISTORY'; no recorded
         * season: no season number to show */
        if (g_hdr_seasons) {
            char lb[SLEN];
            int lg = st.cat >= 20;
            award_label((int)((lg ? 96 : 64) + st.cat - lg * 20), lb);
            strcpy(dst, lb);
            strcat(dst, " HISTORY");
        } else {
            strcpy(dst, "AWARD HISTORY");
        }
    }    else if (st.screen == SCREEN_OFFSEASON) {
        int phase = st.cat & 15;
        if (phase == OFF_REVIEW)
            sprintf(dst, "1/6 %ld IN REVIEW", (long)year_of((int32_t)g_hdr_seasons));
        else if (phase == OFF_RETIRE)
            strcpy(dst, "2/6 RETIREMENTS");
        else if (phase == OFF_DRAFT)
            strcpy(dst, "3/6 ROOKIE DRAFT");
        else if (phase == OFF_TRADES)
            strcpy(dst, "4/6 TRADES");
        else if (phase == OFF_FA)
            strcpy(dst, "5/6 SIGNINGS AND RELEASES");
        else
            sprintf(dst, "6/6 %ld IS READY", (long)year_of((int32_t)g_hdr_seasons + 1));
    } else if (g_hdr_seasons)
        sprintf(dst, "%ld IN REVIEW", (long)year_of((int32_t)g_hdr_seasons));
    else
        strcpy(dst, "LAST SEASON REVIEW");
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

/* ---------------- PLAYER CARD (C13.5) ---------------- */

/* the POS name of a pos1 byte (dynview.pos_name): '?' out of range */
static const char *pos_name(int p)
{
    return p >= 0 && p < (int)(sizeof POS_NAMES / sizeof POS_NAMES[0]) ? POS_NAMES[p] : "?";
}

/* the season table cells of one PLAYER CARD row (dynview.card_cells) from the totals t, WAR10 and
 * the entry's pitcher flag: the batter columns, or the pitcher columns */
static void card_cells(const uint32_t *t, int32_t war10, int pitcher, const char *first,
                       const char *team, char cells[][SLEN])
{
    strcpy(cells[0], first);
    strcpy(cells[1], team);
    if (pitcher) {
        fmt_count((int32_t)t[0], cells[2]);
        fmt_count((int32_t)t[13], cells[3]);
        fmt_count((int32_t)t[14], cells[4]);
        fmt_count((int32_t)t[15], cells[5]);
        fmt_ip(t[19], cells[6]);
        fmt_count((int32_t)t[23], cells[7]);
        fmt_era100((int32_t)era100_of(t), cells[8]);
        fmt_war10(war10, cells[9]);
    } else {
        fmt_count((int32_t)t[0], cells[2]);
        fmt_count((int32_t)t[1], cells[3]);
        fmt_count((int32_t)t[2], cells[4]);
        fmt_count((int32_t)t[5], cells[5]);
        fmt_count((int32_t)t[7], cells[6]);
        fmt_count((int32_t)t[10], cells[7]);
        fmt_avg((int32_t)avg_of(t), cells[8]);
        fmt_war10(war10, cells[9]);
    }
}

/* the five info rows of the PLAYER CARD (dynview.card_info): position and hands, status, years and
 * seasons, then the ratings of the latest line (last, NULL with none) */
static void card_info(const Entry *e, const Line *last, char info[][SLEN])
{
    char a[SLEN], b[SLEN];
    const uint8_t *r;
    if (!last)
        strcpy(info[0], pos_name(e->pos1));
    else
        sprintf(info[0], "%s  BATS %c  THROWS %c", pos_name(last->pos1),
                BATS_NAMES[(last->hand >> 1) & 3], (last->hand & 8) ? 'R' : 'L');
    if (e->status == STATUS_ACTIVE) {
        sprintf(info[1], "ACTIVE, AGE %u", (unsigned)e->age + 1u);
    } else if (e->status == STATUS_RETIRED) {
        year_text(e->last_season, a);
        sprintf(info[1], "RETIRED %s", a);
    } else if (e->status == STATUS_HOF) {
        year_text(e->hof_season, a);
        sprintf(info[1], "HALL OF FAME %s", a);
    } else {
        info[1][0] = 0;
    }
    year_text(e->first_season, a);
    year_text(e->last_season, b);
    sprintf(info[2], "%s-%s  %u SEASONS", a, b, (unsigned)e->seasons_played);
    if (!last) {
        strcpy(info[3], NO_RATINGS_TEXT);
        info[4][0] = 0;
        return;
    }
    r = last->ratings;
    if (e->pitcher) {
        sprintf(info[3], "CTL %u  VEL %u  END %u", (unsigned)r[6], (unsigned)r[7],
                (unsigned)r[8]);
        info[4][0] = 0;
    } else {
        sprintf(info[3], "POW %u  H&R %u  SPD %u", (unsigned)r[0], (unsigned)r[2],
                (unsigned)r[3]);
        sprintf(info[4], "RNG %u  ARM %u  BUNT %u", (unsigned)r[4], (unsigned)r[5],
                (unsigned)r[1]);
    }
}

/* the column headers of a table at y (the render rules: right aligned columns end at their edge) */
static void draw_headers(const ColDef *cols, int ncols, int y)
{
    int ci;
    for (ci = 0; ci < ncols; ci++) {
        const ColDef *cd = &cols[ci];
        uint8_t h[16];
        int hl = (int)strlen(cd->header);
        if (hl > cd->w)
            hl = cd->w;
        memcpy(h, cd->header, (size_t)hl);
        h[hl] = 0;
        if (cd->ralign)
            draw_text(g_fb, g_main, cd->x + cd->w * CHAR_W - text_width(g_main, h), y, h,
                      C_BLACK);
        else
            draw_text(g_fb, g_main, cd->x, y, h, C_BLACK);
    }
}

/* one PLAYER CARD table row at y0 (dynview.draw_row): the tan band with the grid line under it,
 * the cells cut to their columns; a row of one cell is drawn unclipped from the first column */
static void draw_card_row(const ColDef *cols, char cells[][SLEN], int ncells, int y0)
{
    int ci;
    rect_fb(8, y0, 311, y0 + 9, C_ROW_TAN);
    if (ncells == 1) {
        draw_text(g_fb, g_main, cols[0].x, y0 + 2, (const uint8_t *)cells[0], C_BLACK);
    } else {
        for (ci = 0; ci < ncells; ci++) {
            const ColDef *cd = &cols[ci];
            uint8_t shown[SLEN];
            int cl = (int)strlen(cells[ci]);
            if (cl > cd->w)
                cl = cd->w;
            memcpy(shown, cells[ci], (size_t)cl);
            shown[cl] = 0;
            if (cd->ralign)
                draw_text(g_fb, g_main, cd->x + cd->w * CHAR_W - text_width(g_main, shown),
                          y0 + 2, shown, C_BLACK);
            else
                draw_text(g_fb, g_main, cd->x, y0 + 2, shown, C_BLACK);
        }
    }
    rect_fb(8, y0 + 10, 311, y0 + 10, C_GRID_GRAY);
}

/* the PLAYER CARD body of entry on the season page (dynview.draw_card, C13.5): the portrait of the
 * latest line's face (or a gray box with a ?), the five info rows, the season table header, the
 * page's season rows (newest first) and the CAREER row at its fixed slot */
/* the PLAYER CARD head (C13.5, C40): the portrait of the latest line's face (or the gray
 * box with a ?) and the five info lines, shared by the SEASONS and HONORS views */
static void card_head(int32_t entry, int valid)
{
    int has_last = 0, k;
    Entry e;
    Line last;
    char info[5][SLEN];
    memset(&e, 0, sizeof e);
    memset(&last, 0, sizeof last);
    if (valid)
        read_entry(&e, (uint32_t)entry);
    if (valid) {
        card_collect(entry);
        has_last = g_ncard > 0 && card_line(g_card[g_ncard - 1].off, &last);
    }
    if (has_last && portrait_of(last.face)) {
        for (k = 0; k < PORTRAIT_H; k++)
            memcpy(g_fb + (long)(PORTRAIT_Y + k) * FB_W + PORTRAIT_X, g_portrait + k * PORTRAIT_W,
                   PORTRAIT_W);
    } else {
        int q = glyph_of(g_main, '?')->rows;
        rect_fb(PORTRAIT_X, PORTRAIT_Y, PORTRAIT_X + PORTRAIT_W - 1,
                PORTRAIT_Y + PORTRAIT_H - 1, C_GRID_GRAY);
        draw_text(g_fb, g_main,
                  PORTRAIT_X + (PORTRAIT_W - text_width(g_main, (const uint8_t *)"?")) / 2,
                  PORTRAIT_Y + (PORTRAIT_H - q) / 2, (const uint8_t *)"?", C_WHITE);
    }
    if (!valid) {
        strcpy(info[0], "?");
        info[1][0] = 0;
        info[2][0] = 0;
        strcpy(info[3], NO_RATINGS_TEXT);
        info[4][0] = 0;
    } else {
        card_info(&e, has_last ? &last : NULL, info);
    }
    for (k = 0; k < 5; k++)
        draw_text(g_fb, g_main, INFO_X, INFO_Y[k], (const uint8_t *)info[k], C_WHITE);
}

static void draw_card(int32_t entry, int page)
{
    int valid = card_valid(entry), has_last = 0, pitch = 0, ncols, k, r, per;
    Entry e;
    Line last;
    char info[5][SLEN], cells[CARD_CELLS][SLEN], yr[SLEN];
    const ColDef *cols;
    memset(&e, 0, sizeof e);
    memset(&last, 0, sizeof last);
    if (valid) {
        read_entry(&e, (uint32_t)entry);
        pitch = e.pitcher != 0;
        card_collect(entry);
        has_last = g_ncard > 0 && card_line(g_card[g_ncard - 1].off, &last);
    }
    if (has_last && portrait_of(last.face)) {
        for (k = 0; k < PORTRAIT_H; k++)
            memcpy(g_fb + (long)(PORTRAIT_Y + k) * FB_W + PORTRAIT_X, g_portrait + k * PORTRAIT_W,
                   PORTRAIT_W);
    } else {
        int q = glyph_of(g_main, '?')->rows;
        rect_fb(PORTRAIT_X, PORTRAIT_Y, PORTRAIT_X + PORTRAIT_W - 1,
                PORTRAIT_Y + PORTRAIT_H - 1, C_GRID_GRAY);
        draw_text(g_fb, g_main,
                  PORTRAIT_X + (PORTRAIT_W - text_width(g_main, (const uint8_t *)"?")) / 2,
                  PORTRAIT_Y + (PORTRAIT_H - q) / 2, (const uint8_t *)"?", C_WHITE);
    }
    if (!valid) {
        strcpy(info[0], "?");
        info[1][0] = 0;
        info[2][0] = 0;
        strcpy(info[3], NO_RATINGS_TEXT);
        info[4][0] = 0;
    } else {
        card_info(&e, has_last ? &last : NULL, info);
    }
    for (k = 0; k < 5; k++)
        draw_text(g_fb, g_main, INFO_X, INFO_Y[k], (const uint8_t *)info[k], C_WHITE);
    cols = pitch ? COLS_CARD_PIT : COLS_CARD_BAT;
    ncols = pitch ? NCOLS(COLS_CARD_PIT) : NCOLS(COLS_CARD_BAT);
    rect_fb(8, CARD_HDR_Y, 311, CARD_HDR_Y + 9, C_HEADER_GOLD);
    draw_headers(cols, ncols, CARD_HDR_Y + 2);
    if (!valid || g_ncard == 0) {
        strcpy(cells[0], NO_CARD_TEXT);
        draw_card_row(cols, cells, 1, CARD_ROW_Y0);
    } else {
        per = post_totals(entry) > 0 ? 6 : CARD_SEASON_ROWS;
        for (r = 0; r < per; r++) {
            int idx = g_ncard - 1 - (page * per + r);
            Line ln;
            if (idx < 0 || !card_line(g_card[idx].off, &ln))
                break;
            year_text(ln.season, yr);
            card_cells(ln.tot, ln.war10, pitch, yr, abbr_of(ln.team), cells);
            draw_card_row(cols, cells, ncols, CARD_ROW_Y0 + r * ROW_H);
        }
    }
    /* CAREER: the entry's totals at the fixed slot after the season rows; its label is not
     * cut. With a POST row (C26) it sits one season row up, and the POSTSEASON row (the
     * postseason sums of the entry) sits at CARD_CAREER_Y: WAR '-', for a pitcher also
     * W, L and SV '-', the labels not cut (POSTSEASON runs into the blank TM column). */
    if (valid && post_totals(entry) > 0) {
        int ci;
        card_cells(e.tot, e.war10, pitch, "", "", cells);
        draw_card_row(cols, cells, ncols, CARD_CAREER_Y - ROW_H);
        draw_text(g_fb, g_main, cols[0].x, CARD_CAREER_Y - ROW_H + 2,
                  (const uint8_t *)"CAREER", C_BLACK);
        card_cells(g_post_tot, 0, pitch, "", "", cells);
        cells[0][0] = 0;
        cells[1][0] = 0;
        cells[9][0] = '-';
        cells[9][1] = 0;
        if (pitch) {
            for (ci = 3; ci <= 5; ci++) {
                cells[ci][0] = '-';
                cells[ci][1] = 0;
            }
        }
        draw_card_row(cols, cells, ncols, CARD_CAREER_Y);
        draw_text(g_fb, g_main, cols[0].x, CARD_CAREER_Y + 2,
                  (const uint8_t *)"POSTSEASON", C_BLACK);
    } else if (valid) {
        card_cells(e.tot, e.war10, pitch, "", "", cells);
        draw_card_row(cols, cells, ncols, CARD_CAREER_Y);
    } else {
        cells[0][0] = 0;
        draw_card_row(cols, cells, 1, CARD_CAREER_Y);
    }
    if (!(valid && post_totals(entry) > 0))
        draw_text(g_fb, g_main, cols[0].x, CARD_CAREER_Y + 2, (const uint8_t *)"CAREER", C_BLACK);
}

/* render into g_fb: panel, bold title with a drop shadow, gold header row,
 * tan rows with a gray underline, footer. Matches dynview.render exactly. */
static void render(State st)
{
    const ColDef *cols;
    uint8_t up[160];
    int tx, r, ci, hot;
    draw_panel();
    /* screen_title then the centered bold title with its shadow */
    {
        char tbuf[160];
        screen_title(st, tbuf);
        strcpy((char *)up, tbuf);
    }
    tx = 8 + (304 - text_width(g_bold, up)) / 2;
    draw_text(g_fb, g_bold, tx + 1, 11, up, C_BLACK);
    draw_text(g_fb, g_bold, tx, 10, up, C_WHITE);
    if (st.screen == SCREEN_CARD) {
        if (st.row) {
            /* HONORS (C40): the portrait and info lines as the SEASONS view, the two
             * columns where the season table is (header at CARD_HDR_Y), the page's
             * honors_rows rows from CARD_ROW_Y0 (9 rows between the header and CAREER) */
            card_head(st.cat, card_valid(st.cat));
            rect_fb(8, CARD_HDR_Y, 311, CARD_HDR_Y + 9, C_HEADER_GOLD);
            draw_headers(COLS_HONORS, NCOLS(COLS_HONORS), CARD_HDR_Y + 2);
            {
                int nr = honors_rows(st.cat, st.page);
                int rr;
                for (rr = 0; rr < nr; rr++)
                    draw_card_row(COLS_HONORS, g_rows[rr].cells, g_rows[rr].ncells,
                                  CARD_ROW_Y0 + rr * ROW_H);
            }
        } else {
            draw_card(st.cat, st.page);
        }
        draw_text(g_fb, g_main, 10, 185, (const uint8_t *)footer_of(st), C_WHITE);
        return;
    }
    /* the highlighted row of the page: SETTINGS' cat row, the cursor row (C13.4) on the cursor
     * screens, none on a single message row (C15.8) */
    g_nrows = refresh_rows(st, &cols);
    if (st.screen == SCREEN_SETTINGS)
        hot = st.cat - (int)st.page * ROWS_PER_PAGE;
    else if (cursor_screen(st) && cols != COLS_SINGLE)
        hot = (int)st.row - (int)st.page * ROWS_PER_PAGE;
    else if (st.screen == SCREEN_MENU && hub_cursor(st))
        hot = (int)st.row - (int)st.page * ROWS_PER_PAGE;   /* C67 */
    else
        hot = -1;
    rect_fb(8, 24, 311, 33, C_HEADER_GOLD);
    draw_headers(cols, n_cols(cols), 26);
    for (r = 0; r < g_nrows; r++) {
        const Row *row = &g_rows[r];
        int y0 = 35 + r * ROW_H;
        int tc = (r == hot) ? C_WHITE : C_BLACK;
        rect_fb(8, y0, 311, y0 + 9, (r == hot) ? C_TITLE_RED : C_ROW_TAN);
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
                              y0 + 2, shown, tc);
                else
                    draw_text(g_fb, g_main, cd->x, y0 + 2, shown, tc);
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

/* ---------------- clicks (C13.6) ---------------- */

/* the body row (0..ROWS_PER_PAGE - 1) whose band (BODY_Y0 + r * ROW_H .. + 9) holds y, -1 for none */
static int band_row(int y)
{
    int r, off;
    if (y < BODY_Y0)
        return -1;
    r = (y - BODY_Y0) / ROW_H;
    off = (y - BODY_Y0) % ROW_H;
    return off <= 9 && r < ROWS_PER_PAGE ? r : -1;
}

/* the screens where LEFT and RIGHT step something (a title click there is LEFT or RIGHT) */
static int left_right_screen(int screen)
{
    return screen == SCREEN_LEADERS || screen == SCREEN_AWARDS || screen == SCREEN_STANDINGS
           || screen == SCREEN_SERIES || screen == SCREEN_BOX || screen == SCREEN_PLAYOFFS
           || screen == SCREEN_MILESTONES   /* C27: a title click toggles the mode */
           || screen == SCREEN_AWHIST       /* C28: a title click steps the award code */
           || screen == SCREEN_TEAMHIST;    /* C29: a title click steps the team */
}

/* the key of a left click at (x, y) (dynview.click_to_key, C13.6), in order: a hub row band is that
 * row's key (none on the /TITLE welcome text); a SETTINGS row band is the row with ENTER
 * (START YEAR: LEFT when x < 160, else RIGHT); a band of a cursor screen row is the row with ENTER
 * (the RETIREMENTS phase: C); a title band where LEFT and RIGHT act is LEFT or RIGHT; a footer band
 * is PGUP or PGDN. *row is the cursor row to set first (-1: none), *key is -1 when the click does
 * nothing */
static void click_to_key(State st, int x, int y, int32_t *key, int32_t *row)
{
    int r = band_row(y);
    int title_menu = g_hdr_seasons == 0 && (st.cat >> 4) != 0;
    *key = -1;
    *row = -1;
    if (st.screen == SCREEN_MENU && r >= 0 && r < N_MENU_ROWS && !title_menu) {
        *key = (int32_t)(unsigned char)MENU_ITEMS[r][0];
        return;
    }
    if (st.screen == SCREEN_SETTINGS && r >= 0) {
        int32_t cur = st.page * ROWS_PER_PAGE + r;
        if (cur < SET_TEAM0 + g_nteams) {
            *row = cur;
            if (cur == SET_START)
                *key = x < 160 ? KEY_LEFT : KEY_RIGHT;
            else
                *key = KEY_ENTER;
            return;
        }
    }
    if (cursor_screen(st) && r >= 0) {
        int32_t cur = st.page * ROWS_PER_PAGE + r;
        if (cur < total_rows(st)) {
            *row = cur;
            *key = st.screen == SCREEN_OFFSEASON ? KEY_CARD_CAP : KEY_ENTER;
            return;
        }
    }
    if (y >= TITLE_Y0 && y <= TITLE_Y1
        && (left_right_screen(st.screen) || (st.screen == SCREEN_SETTINGS && st.cat == SET_START))) {
        *key = x < 160 ? KEY_LEFT : KEY_RIGHT;
        return;
    }
    if (y >= FOOTER_Y0)
        *key = x < 160 ? KEY_PGUP : KEY_PGDN;
}

/* one key on the screen state (dynview.step) */
static void apply_key(int32_t key)
{
    g_state = step(g_state, key);
}

/* a left click at (x, y): click_to_key, the cursor row set first when there is one, then the key
 * (dynview main) */
static void apply_click(int x, int y)
{
    int32_t key, row;
    click_to_key(g_state, x, y, &key, &row);
    if (key < 0)
        return;
    if (row >= 0)
        g_state = cursor_to(g_state, row);
    apply_key(key);
}

/* apply the /KEYS tokens in order (dynview.parse_keys, C13.6): a number is a key, Lx.y a left
 * click at (x, y), R a right click (ESC); the exit flag is ignored */
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
        if (i == 1 && tok[0] == 'R') {
            apply_key(KEY_ESC);
        } else if (i > 0 && tok[0] == 'L') {
            int x = 0, y = 0;
            if (sscanf((const char *)tok + 1, "%d.%d", &x, &y) == 2)
                apply_click(x, y);
        } else if (i > 0) {
            apply_key(parse_key(tok));
        }
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
    fprintf(stderr, "usage: DYNVIEW [/REVIEW] [/OFFSEASON] [/TITLE] [/MENU] "
            "[/KEYS:k,k,...] [/RAW:FILE] [/ANMS:DIR] [/GAME:DIR] [LEAGUE_DIR [FONT_DIR]]\n");
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

/* INT 33h at start (AX=0): g_mouse is 1 when a driver answers; no mouse means keyboard only */
static void mouse_reset(void)
{
    union REGS rg;
    rg.x.ax = 0;
    int86(0x33, &rg, &rg);
    g_mouse = rg.x.ax != 0;
    g_mbtn = 0;
}

/* the range of the mode 13h screen after the mode set: x = CX in 0..319, y = DX in 0..199 */
static void mouse_range(void)
{
    union REGS rg;
    if (!g_mouse)
        return;
    rg.x.ax = 7;
    rg.x.cx = 0;
    rg.x.dx = 319;
    int86(0x33, &rg, &rg);
    rg.x.ax = 8;
    rg.x.cx = 0;
    rg.x.dx = 199;
    int86(0x33, &rg, &rg);
}

/* the pointer shown (AX=1) while waiting, hidden (AX=2) while the screen is drawn */
static void mouse_show(int on)
{
    union REGS rg;
    if (!g_mouse)
        return;
    rg.x.ax = on ? 1 : 2;
    int86(0x33, &rg, &rg);
}

/* the state of the screen equal in every field */
static int state_eq(State a, State b)
{
    return a.screen == b.screen && a.page == b.page && a.cat == b.cat && a.row == b.row
           && a.year == b.year;
}

/* the next input of the interactive loop (C13.6): 1 a key (*key), 2 a left click at (*x, *y),
 * 3 a right click, 0 none yet. With no mouse it waits for a key. A click fires on the release of
 * a button, at the pointer position then */
static int next_input(int32_t *key, int *x, int *y)
{
    union REGS rg;
    int b, released;
    if (!g_mouse || kbhit()) {
        *key = (int32_t)read_key();
        return 1;
    }
    rg.x.ax = 3;
    int86(0x33, &rg, &rg);
    b = rg.x.bx & 3;
    released = g_mbtn & ~b;
    g_mbtn = b;
    if (released & 1) {
        *x = (int)rg.x.cx;
        *y = (int)rg.x.dx;
        return 2;
    }
    if (released & 2)
        return 3;
    return 0;
}

#endif /* __WATCOMC__ */

int main(int argc, char **argv)
{
    const char *league = NULL;
    char deflg[24];                 /* TEAMS<sep><L>: 15 B at most */
    const char *font_dir = NULL;
    const uint8_t *keys = NULL, *raw_path = NULL;
    int have_fonts, raw_mode = 0, review = 0, offseason = 0, title = 0, menu = 0;
    int i, npos = 0;
    State st;

#ifdef __WATCOMC__
    _harderr(_hard_err_handler);
#endif

    hof_match_init();
    memset(g_hdr, 0, sizeof g_hdr);
    for (i = 1; i < argc; i++) {
        const uint8_t *v;
        if (arg_flag((const uint8_t *)argv[i], "review")) {
            review = 1;
        } else if (arg_flag((const uint8_t *)argv[i], "offseason")) {
            offseason = 1;
        } else if (arg_flag((const uint8_t *)argv[i], "title")) {
            title = 1;
        } else if (arg_flag((const uint8_t *)argv[i], "menu")) {
            menu = 1;
        } else if ((v = arg_switch((const uint8_t *)argv[i], "keys")) != NULL) {
            keys = v;
        } else if ((v = arg_switch((const uint8_t *)argv[i], "raw")) != NULL) {
            raw_path = v;
            raw_mode = 1;
        } else if ((v = arg_switch((const uint8_t *)argv[i], "anms")) != NULL) {
            if (strlen((const char *)v) >= sizeof g_anms)
                return usage();
            strcpy(g_anms, (const char *)v);
        } else if ((v = arg_switch((const uint8_t *)argv[i], "game")) != NULL) {
            if (strlen((const char *)v) >= sizeof g_game)
                return usage();
            strcpy(g_game, (const char *)v);
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

    if (league == NULL) {
        /* no LEAGUE_DIR: the current league's dir (C16.3) */
        char lg[LG_NAME_MAX + 1];
        lg_current(".", lg);
        if (!lg_path(deflg, (int)sizeof deflg, LG_DIR, lg, DIR_SEP))
            return usage();
        league = deflg;
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
    load_settings();
    load_teams();
    load_fmt();

    /* /OFFSEASON starts at phase 0 with the launched flag (cat 16); /TITLE is the
     * MENU with cat 16; /MENU opens the item CONTROL holds: 2 DYNASTY SETTINGS,
     * 3 ABOUT THE MODS, else the hub (precedence /OFFSEASON, /REVIEW, /TITLE, /MENU) */
    st = mk_state(SCREEN_MENU, 0, 0);
    if (offseason) {
        st.screen = SCREEN_OFFSEASON;
        st.cat = 16;
    } else if (review) {
        st.screen = SCREEN_REVIEW;
    } else if (title) {
        st.cat = 16;
    } else if (menu) {
        int item = control_item();
        if (item == 2)
            st.screen = SCREEN_SETTINGS;
        else if (item == 3)
            st.screen = SCREEN_ABOUT;
    }
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
        if (menu)
            control_return();
        return 0;
    }
#ifdef __WATCOMC__
    {
        int quit = 0;
        mouse_reset();
        save_video();
        init_vga_mode13();
        mouse_range();
        load_dac();
        render(g_state);
        fb_to_vram();
        g_dirty = 0;
        mouse_show(1);
        while (!quit) {
            int32_t key = 0;
            int x = 0, y = 0, ev;
            State prev = g_state;
            ev = next_input(&key, &x, &y);
            if (ev == 0)
                continue;
            if (ev == 1)
                apply_key(key);
            else if (ev == 2)
                apply_click(x, y);
            else
                apply_key(KEY_ESC);
            if (g_exit) {
                mouse_show(0);
                restore_video();
                quit = 1;
            } else if (!state_eq(prev, g_state) || g_dirty) {
                /* render after a key or click changed the state or an ENTER changed the
                 * settings (the state itself is the same then); the pointer is hidden meanwhile */
                mouse_show(0);
                render(g_state);
                fb_to_vram();
                g_dirty = 0;
                mouse_show(1);
            }
        }
        if (menu)
            control_return();
        return 0;
    }
#endif
    return 0;
}

