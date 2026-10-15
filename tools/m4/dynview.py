#!/usr/bin/env python3
"""DYNVIEW reference renderer for the dynasty history screens (T5a).

Pure Python reference for a later C port (OpenWatcom, DOS, VGA mode 13h) that must
match this output pixel for pixel. Integers only; every sort has an explicit total
key; draws are C-reproducible (fill/rect/draw_text only).

Display primitives (decor per notes/M4_CONTRACT.md integer rules):
- framebuffer bytearray(64000), 320x200, one palette index per pixel, row-major
- MAIN.FNT body glyphs (7 rows, advance 7), BOLD.FNT titles (8 rows); parsed with
  assets.parse_fnt: u16 count, per glyph u8 rows, u8 bits, u8 adv, rows*ceil(bits/8)
  bytes, MSB first; glyph k = char 32 + k, anything else draws '?'
- palette DEFAULT.PAL raw 6-bit bytes; PNG output scales (c & 63) * 255 // 63

usage: python3 tools/m4/dynview.py [--review | --offseason | --title | --menu N]
       [--control CONTROL] [--keys K,K,...] [--png OUT.png] [--raw OUT.RAW]
       [--game-dir DIR] [--anms-dir DIR] LEAGUE_DIR FONT_DIR
(precedence --offseason, --review, --title, --menu; --menu 2 opens DYNASTY SETTINGS,
--menu 3 ABOUT THE MODS; --control reads the menu item from CONTROL and writes
CONTROL[1] = CONTROL[0] when the session ends)
--keys takes key codes (numbers), Lx.y = a left click at (x, y) and R = a right click (C13.6);
--game-dir holds OLDPORT.ANM (default .), --anms-dir PORTRAIT.ANM (default ANMS).
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import Counter
import history
import realign
import rosters
import teamids
from assets import parse_fnt

FB_W, FB_H, FB_SIZE = 320, 200, 64000
C_BLACK, C_WHITE, C_DRED = 0, 15, 4
C_TITLE_RED, C_HEADER_GOLD, C_ROW_TAN = 208, 207, 188
C_FRAME_TAN, C_BG_BROWN, C_GRID_GRAY = 193, 215, 7

ROW_H = 11
ROWS_PER_PAGE = 12
# list screens keep at most LIST_MAX rows after sorting (100 pages) so the DOS port can
# hold them in a fixed top-K buffer
LIST_MAX = 1200
# ROSTERS.TXT (offseason): lines over ROSTER_LINE_MAX bytes are ignored whole; DRAFT
# lines past DRAFT_KEEP are dropped
ROSTER_LINE_MAX = 127
DRAFT_KEEP = 400

# BIOS int 16h codes; ASCII keys are their char code
KEY_ESC, KEY_ENTER = 27, 13
KEY_LEFT, KEY_RIGHT = 0x4b00, 0x4d00
KEY_PGUP, KEY_PGDN = 0x4900, 0x5100
KEY_UP, KEY_DOWN = 0x4800, 0x5000
# ASCII keys of the screens: TAB cycles the LEADERS mode, '-' '+' '=' step the BY YEAR season
# and the START YEAR setting, C / c open the PLAYER CARD from the offseason RETIREMENTS phase
KEY_TAB = 9
KEY_MINUS, KEY_PLUS, KEY_EQUALS = 45, 43, 61
KEY_CARD = (67, 99)
CURSOR_KEYS = (KEY_UP, KEY_DOWN, KEY_PGUP, KEY_PGDN)
YEAR_KEYS = (KEY_MINUS, KEY_PLUS, KEY_EQUALS)

SCREEN_MENU, SCREEN_HISTORY, SCREEN_HOF = 0, 1, 2
SCREEN_LEADERS, SCREEN_MILESTONES, SCREEN_REVIEW = 3, 4, 5
SCREEN_OFFSEASON = 6
SCREEN_SETTINGS, SCREEN_ABOUT = 7, 8
SCREEN_AWARDS = 9
SCREEN_STANDINGS = 10
SCREEN_SERIES = 11
SCREEN_BOX = 12
SCREEN_CARD = 13
SCREEN_PLAYOFFS = 14
SCREEN_PBOX = 15
# LEADERS modes (C13.3, C39): cat = mode * 32 + category index
MODE_CAREER, MODE_SEASON, MODE_BYYEAR, MODE_POST = 0, 1, 2, 3
MODE_SHIFT = 32
# rows of a list page; the cursor (C13.4) is the absolute row index, page = row // ROWS_PER_PAGE
# PLAYER CARD season table: CARD_SEASON_ROWS season rows, then the CAREER row at CARD_CAREER_Y
CARD_SEASON_ROWS = 7
CARD_HDR_Y, CARD_ROW_Y0, CARD_CAREER_Y = 84, 95, 95 + 7 * 11
# SEASON and BY YEAR leaders keep the top SEASON_MAX lines
SEASON_MAX = 50
NO_LINES_TEXT = 'NO SEASON LINES RECORDED YET.'
# click bands (C13.6): hub and list body rows start at y 35, title band 8..20, footer from y 183
BODY_Y0, TITLE_Y0, TITLE_Y1, FOOTER_Y0 = 35, 8, 20, 183
# SETTINGS: START YEAR is the third row (cursor 2)
SET_START = 2
# the screens where LEFT and RIGHT step something (a title click there is LEFT or RIGHT).
# MILESTONES (C27): LEFT/RIGHT toggle the mode (cat 0 milestones, cat 1 WATCH)
LEFT_RIGHT_SCREENS = (SCREEN_LEADERS, SCREEN_AWARDS, SCREEN_STANDINGS, SCREEN_SERIES,
                      SCREEN_BOX, SCREEN_PLAYOFFS, SCREEN_MILESTONES)
N_CATS = 18

# MILESTON.DAT kinds from this one up are award and leader records (C7), not milestones
AWARD_KIND_MIN = 64
# SEASON AWARDS keeps at most this many rows (the DOS port's fixed buffer)
AWARD_MAX = 64

# the hub (SCREEN_MENU) rows: key 1..9 opens screen key - 48, key 0 SEASON STANDINGS,
# key W (87 or 119) WORLD SERIES, key P (80 or 112) PLAYOFFS
MENU_ROWS = ['1  SEASON HISTORY', '2  HALL OF FAME', '3  LEADERS',
             '4  MILESTONES', '5  LAST SEASON REVIEW', '6  OFFSEASON',
             '7  DYNASTY SETTINGS', '8  ABOUT THE MODS', '9  SEASON AWARDS',
             '0  SEASON STANDINGS', 'W  WORLD SERIES', 'P  PLAYOFFS']

# HISTORY.DAT header fields used by DYNASTY SETTINGS: byte 10 era, bytes 12..15 mask
HDR_SIZE = 32
# playoff format (C12.4): HISTORY byte 11; byte 0 is the rolled flag (C12.6)
HDR_FORMAT, HDR_ROLLED = 11, 0
# start year (C13.1): u16 LE at bytes 18..19; 0 or outside START_MIN..START_MAX counts as START_DEFAULT
HDR_START = 18
START_MIN, START_MAX, START_DEFAULT = 1871, 2100, 1993
START_STEP_SMALL, START_STEP_BIG = 1, 10
# START YEAR step per key (C13.1): LEFT / RIGHT = -1 / +1, '-' = -10, '+' and '=' = +10
START_STEPS = {KEY_LEFT: -START_STEP_SMALL, KEY_RIGHT: START_STEP_SMALL,
               KEY_MINUS: -START_STEP_BIG, KEY_PLUS: START_STEP_BIG, KEY_EQUALS: START_STEP_BIG}
# SEASLINE.DAT (C13.2): 16 B header, 80 B lines, version 1
SEASLINE_FILE, SEASLINE_HDR, SEASLINE_REC, SEASLINE_VERSION = 'SEASLINE.DAT', 16, 80, 1
# MAJ day (C12.1, byte 0x20a): 7 new season set up, 0xf3 season over
MAJ_DAY = 0x20a
DAY_SETUP, DAY_OVER = 7, 0xf3
# MAJ team stems: AL slot s (lg s) at 0x21d, NL slot s (lg s + 16) at 0x758c (the teamids
# layout, C12.1); MAJ_MIN is the shortest MAJ read as a valid one
MAJ_S_AL, MAJ_S_NL = 0x21d, 0x758c
MAJ_O_STEM = 0x1d7
MAJ_MIN = MAJ_S_NL + MAJ_O_STEM + 128
# bytes a MAJ needs for every slot of both leagues (teamids reads 24 slots a league)
TEAM_SPAN = teamids.S[1] + teamids.O_STEM + 8 * teamids.SLOTS
# CONTROL file of /MENU (TONY2.BAT): byte 1 is 8 + item, the request; when DYNVIEW exits
# it copies byte 0 (the program TONY2.BAT restarts) over byte 1
CONTROL_FILE = 'CONTROL'

# offseason phases: cat & 15 is the phase, cat >> 4 the launched flag
OFF_REVIEW, OFF_RETIRE, OFF_DRAFT, OFF_TRADES, OFF_FA, OFF_READY = range(6)
OFF_TITLES = ['1/6 %d IN REVIEW', '2/6 RETIREMENTS', '3/6 ROOKIE DRAFT',
              '4/6 TRADES', '5/6 SIGNINGS AND RELEASES', '6/6 %d IS READY']
OFF_LAUNCH_TEXT = 'ENTER: ON TO %d'
OFF_STAY_TEXT = 'ENTER: BACK TO THE MENU'

# /TITLE (run by TONY2.BAT at boot): the MENU with cat 16. ENTER or ESC goes on to the
# game; a league with no recorded season shows TITLE_ROWS instead of the menu items
TITLE_FLAG = 16
TITLE_ROWS = ['YOUR LEAGUE NOW PLAYS SEASON AFTER SEASON.',
              '',
              'PLAY THROUGH THE WORLD SERIES, THEN PICK',
              'SEASON > START NEW SEASON. THE OFFSEASON',
              'RUNS: RETIREMENTS, ROOKIE DRAFT, TRADES',
              'AND FREE AGENTS. EVERY SEASON IS ARCHIVED',
              'FIRST, SO NOTHING IS LOST.',
              '',
              'THE DYNASTY MENU ON THE MENU BAR HOLDS',
              'HISTORY, CREATE A PLAYER, SETTINGS AND',
              'A GUIDE TO EVERY MOD.']

# ABOUT THE MODS (key 8, /MENU item 3): read-only pages of 12 rows
ABOUT_ROWS = ['DYNASTY MODE',
              'YOUR LEAGUE PLAYS SEASON AFTER SEASON.',
              'AFTER THE WORLD SERIES PICK SEASON >',
              'START NEW SEASON. THE OFFSEASON AGES',
              'EVERY PLAYER A YEAR. RATINGS RISE OR FALL,',
              'VETERANS RETIRE, ROOKIES ARE DRAFTED, AND',
              'TRADES AND FREE AGENCY RUN. EACH SEASON IS',
              'ARCHIVED FIRST TO C:\\SEASONS OR C:\\DYNLG.',
              '',
              'DYNASTY > DYNASTY MODE ON THE MENU BAR',
              'SHOWS HISTORY, HALL OF FAME, LEADERS,',
              'MILESTONES, SEASON AWARDS, STANDINGS',
              'AND THE LAST OFFSEASON.',
              'CREATE A PLAYER',
              'DYNASTY > CREATE A PLAYER PUTS A NEW',
              'PLAYER ON ANY TEAM: NAME, POSITION,',
              'HANDS, AGE, RATINGS AND FACE. THE NEW',
              'PLAYER TAKES THE ROSTER SLOT YOU PICK.',
              '',
              'DYNASTY SETTINGS',
              'ERA RULES: REAL CALENDAR GIVES THE',
              'RESERVE CLAUSE UNTIL 1975 AND FREE',
              'AGENCY FROM 1976, OR FIX EITHER ONE.',
              'TEAMS YOU MANAGE KEEP THEIR ROSTERS:',
              'NO AI RELEASES, TRADES OR DEPARTURES.',
              'A HOLE ON YOUR TEAM TAKES THE BEST',
              'ROOKIE LEFT IN THE DRAFT CLASS, AND YOUR',
              'LINEUP IS REPAIRED, NOT REBUILT.',
              'PLAYOFF FORMAT: 2 DIVISIONS AND AN LCS,',
              'OR 3 DIVISIONS AND A WILD CARD WITH A',
              'DIVISION SERIES. IT TAKES EFFECT AT ONCE',
              'BEFORE A SEASON STARTS, ELSE AT THE ROLL.',
              'THEN START THE NEW SEASON WITH THE',
              'GENERATED SCHEDULE.',
              '',
              'LEADERS: CAREER, SINGLE SEASON AND BY',
              'YEAR. TAB SWITCHES. ENTER OR A CLICK ON A',
              'PLAYER OPENS HIS CARD.',
              'START YEAR: DYNASTY SETTINGS, LEFT RIGHT.',
              '',
              'NUMBER OF TEAMS',
              'UTILITIES > SETUP LEAGUES: NEW TEAM, THEN',
              'CLICK IT AND AN EMPTY DIVISION ROW.',
              'CLICK A PLACED TEAM TO REMOVE IT. NEW',
              'TEAMS DRAFT FROM AI TEAMS, WHICH KEEP 15',
              'EACH, THEN SIGN FREE AGENTS. PLAYERS OF',
              'A REMOVED TEAM BECOME FREE AGENTS. START',
              'THE SEASON WITH A SCHEDULE THAT FITS,',
              'ELSE GENERATED.',
              '',
              'NEW FACES',
              '323 NEW FACES JOIN THE 30 STOCK ONES.',
              'ROOKIES AND CREATED PLAYERS USE THEM.',
              '',
              'MODERN BALLPARKS',
              'UTILITIES > ASSIGN STADIUMS LETS ANY TEAM',
              'PLAY IN A NEW PARK.']

# career leader categories (C13.3): (title label, kind, TOTALS index)
# kind: 'count' | 'ip' (OUTS, shown as innings) | 'avg' | 'era' | 'war' | 'aw0' (MVP awards) |
# 'aw3' (GG awards)
CATS = [('H', 'count', 2), ('HR', 'count', 5), ('RBI', 'count', 7), ('R', 'count', 6),
        ('2B', 'count', 3), ('3B', 'count', 4), ('SB', 'count', 10), ('BB', 'count', 8),
        ('AVG', 'avg', 0), ('WAR', 'war', 0), ('W', 'count', 13), ('SV', 'count', 15),
        ('SO', 'count', 23), ('ERA', 'era', 0), ('IP', 'ip', 19), ('SHO', 'count', 18),
        ('MVP AWARDS', 'aw0', 0), ('GG AWARDS', 'aw3', 0)]
# SEASON and BY YEAR leader categories (C13.3), over SEASLINE.DAT lines
SEASON_CATS = [('AVG', 'avg', 0), ('HR', 'count', 5), ('RBI', 'count', 7), ('H', 'count', 2),
               ('R', 'count', 6), ('2B', 'count', 3), ('3B', 'count', 4), ('SB', 'count', 10),
               ('BB', 'count', 8), ('WAR', 'war', 0), ('W', 'count', 13), ('ERA', 'era', 0),
               ('SO', 'count', 23), ('SV', 'count', 15), ('IP', 'ip', 19), ('CG', 'count', 17),
               ('SHO', 'count', 18)]
# POSTSEASON career leader categories (C39), over the BOXSCORE.DAT player rows
# (C26 sums): TOTALS indexes of the post_totals t lists
POST_CATS = [('G', 'count', 0), ('H', 'count', 2), ('HR', 'count', 5), ('RBI', 'count', 7),
             ('SB', 'count', 10), ('SO', 'count', 23), ('IP', 'ip', 19)]
# POSTSEASON keeps the top POST_MAX lines of one category over POST_ENTRY_MAX entries
POST_MAX, POST_ENTRY_MAX = 50, 4096
NO_POST_TEXT = 'NO POSTSEASON GAMES RECORDED YET.'
# TOTALS indexes used by the SEASON qualifiers
T_G, T_AB, T_BB, T_OUTS, T_ER = 0, 1, 8, 19, 20
# SEASLINE ratings (C13.2 bytes 12..20) in order, and the position names as the game shows them
RATING_NAMES = ['POW', 'BUNT', 'H&R', 'SPD', 'RNG', 'ARM', 'CTL', 'VEL', 'END']
POS_NAMES = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH', 'OF', 'IF',
             'OI', 'CO', 'CI', 'C3']
BATS_NAMES = 'LRS?'                           # bats code (byte 29 bits 2..1): 0 L, 1 R, 2 S
# portrait frames (CREATE's portrait() rules): stock PORTRAIT.ANM below OLD_FACE, OLDPORT.ANM
# from OLD_FACE to OLD_FACE_END - 1
PORTRAIT_W, PORTRAIT_H = 48, 56
PORTRAIT_X, PORTRAIT_Y = 12, 24
OLD_FACE, OLD_FACE_END = 981, 1509
OLD_FRAME = 12 + PORTRAIT_W * PORTRAIT_H      # 12 B header + 2688 B pixels, no count word
INFO_X, INFO_Y = 70, (26, 37, 48, 59, 70)

# milestone kinds (C7): one fixed phrase per kind
CAREER_EVENTS = {1: '2000 HITS', 2: '3000 HITS',
                 3: '300 HOME RUNS', 4: '400 HOME RUNS', 5: '500 HOME RUNS',
                 6: '600 HOME RUNS', 7: '700 HOME RUNS',
                 8: '1500 RBI', 9: '2000 RBI', 10: '500 STOLEN BASES',
                 11: '200 WINS', 12: '300 WINS',
                 13: '2000 STRIKEOUTS', 14: '3000 STRIKEOUTS', 15: '4000 STRIKEOUTS',
                 16: '300 SAVES', 17: '400 SAVES'}


# ---------------------------------------------------------------- fonts / palette
def load_fonts(font_dir):
    """(main_glyphs, bold_glyphs) parsed with assets.parse_fnt layout."""
    main = parse_fnt(open(os.path.join(font_dir, 'MAIN.FNT'), 'rb').read())
    bold = parse_fnt(open(os.path.join(font_dir, 'BOLD.FNT'), 'rb').read())
    return main, bold


def load_palette(path=None):
    """Raw 6-bit palette triples [(r, g, b)] for the C port; deterministic gray ramp
    fallback when DEFAULT.PAL is missing."""
    if path is not None and os.path.exists(path):
        d = open(path, 'rb').read()[:768]
        return [(d[i * 3], d[i * 3 + 1], d[i * 3 + 2]) for i in range(256)]
    return [(i & 63, i & 63, i & 63) for i in range(256)]


def png_palette(pal6):
    """assets.load_pal semantics applied to raw 6-bit triples (PNG output only)."""
    out = []
    for r, g, b in pal6:
        out += [min(255, (c & 63) * 255 // 63) for c in (r, g, b)]
    return out


def write_png(path, fb, pal6):
    from PIL import Image
    im = Image.frombytes('P', (FB_W, FB_H), bytes(fb))
    im.putpalette(png_palette(pal6))
    im.save(path)


# ---------------------------------------------------------------- data loading
def load_data(league_dir, font_dir=None, game_dir='.', anms_dir='ANMS'):
    """data dict shared by step/render/rows. A missing HISTORY.DAT loads as a
    brand-new file (0 seasons): every screen then shows 'NO DYNASTY HISTORY YET'.
    game_dir holds OLDPORT.ANM and anms_dir PORTRAIT.ANM (PLAYER CARD portraits)."""
    hp = os.path.join(league_dir, 'HISTORY.DAT')
    hist = history.History.load(hp)
    ms = history.milestone_entries(hp)
    fonts = load_fonts(font_dir) if font_dir else None
    era, mask = load_settings(league_dir)
    return {'hist': hist, 'ms': ms, 'fonts': fonts, 'league_dir': league_dir,
            'events': parse_rosters(league_dir), 'era': era, 'mask': mask,
            'teams': settings_teams(league_dir), 'box': load_box(league_dir),
            'team_stems': settings_team_stems(league_dir),
            'fmt': realign.wanted_for_dir(league_dir),
            'lines': load_lines(league_dir), 'abbrs': team_abbrs(league_dir),
            'game_dir': game_dir, 'anms_dir': anms_dir}


def load_lines(league_dir):
    """SEASLINE.DAT lines (C13.2) in file order, as read_line dicts. A missing file, a bad
    header (not 'SL', version 1, byte 3 zero, line size 80) or a short header gives []; a short tail line
    is dropped."""
    try:
        with open(os.path.join(league_dir, SEASLINE_FILE), 'rb') as fh:
            raw = fh.read()
    except OSError:
        return []
    if len(raw) < SEASLINE_HDR or raw[0:2] != b'SL' or raw[2] != SEASLINE_VERSION \
            or raw[3] != 0 or int.from_bytes(raw[4:6], 'little') != SEASLINE_REC:
        return []
    out = []
    for off in range(SEASLINE_HDR, len(raw) - SEASLINE_REC + 1, SEASLINE_REC):
        out.append(read_line(raw[off:off + SEASLINE_REC]))
    return out


def read_line(r):
    """One 80 B SEASLINE.DAT line (C13.2) as a dict: entry, season, team (stable id), pitcher
    (flags bit0), age, pos1, face, hand (roster byte 29 raw), dev, ratings (9 nibbles in
    RATING_NAMES order), totals (25 season stats in TOTALS order) and WAR10."""
    return {'entry': int.from_bytes(r[0:2], 'little'),
            'season': int.from_bytes(r[2:4], 'little'),
            'team': r[4], 'pitcher': r[5] & 1, 'age': r[6], 'pos1': r[7],
            'face': int.from_bytes(r[8:10], 'little'), 'hand': r[10], 'dev': r[11],
            'ratings': list(r[12:21]),
            'totals': list(struct.unpack_from('<25H', r, 22)),
            'WAR10': struct.unpack_from('<h', r, 72)[0]}


def team_abbrs(league_dir):
    """{stable team id: 3-letter MAJ abbreviation} of the current league (C13.3 TEAM column);
    {} with no MAJ or an unreadable one. A blank abbreviation is '?' (not in the map)."""
    mp = history.maj_or_none(league_dir)
    if mp is None:
        return {}
    try:
        with open(mp, 'rb') as fh:
            d = fh.read()
        table = teamids.load_table(league_dir)
    except OSError:
        return {}
    if len(d) < MAJ_MIN:
        return {}
    d = d.ljust(TEAM_SPAN, b'\0')
    out = {}
    for tid, L, slot, _st in teamids.teams(d, table):
        a = teamids.S[L] + teamids.O_ABBR + 3 * slot
        ab = one_field(d[a:a + 3])
        if ab:
            out[tid] = ab
    return out


def load_box(league_dir):
    """BOXSCORE.DAT records as (season, g, flags, idx, b, i, stats) in file order, stats a
    tuple of 8 ints; a short tail is dropped. [] when the file is missing or unreadable."""
    try:
        with open(os.path.join(league_dir, BOX_FILE), 'rb') as fh:
            raw = fh.read()
    except OSError:
        return []
    out = []
    for off in range(0, len(raw) - BOX_REC + 1, BOX_REC):
        r = raw[off:off + BOX_REC]
        out.append((int.from_bytes(r[0:2], 'little'), r[2], r[3],
                    int.from_bytes(r[4:6], 'little'), r[6], r[7], tuple(r[8:16])))
    return out


def find_upper(league_dir, want):
    """Path of the LEAGUE_DIR entry whose ASCII upper case is want; None when there is
    none or the directory cannot be listed."""
    if not league_dir:
        return None
    try:
        names = os.listdir(league_dir)
    except OSError:
        return None
    for f in names:
        if ascii_upper(f) == want:
            return os.path.join(league_dir, f)
    return None


def v20_path(league_dir, stem):
    """LEAGUE_DIR/<STEM>.V20 for a stem (bytes) of 1..8 bytes without NUL, a slash, a
    backslash or a colon; None when the stem is unusable or the file is missing."""
    if not 1 <= len(stem) <= 8 or any(c in b'\0/\\:' for c in stem):
        return None
    return find_upper(league_dir, ascii_upper(stem.decode('latin-1')) + '.V20')


def team_name(league_dir, stem):
    """V20 header name (bytes 0..13, NUL ended) of LEAGUE_DIR/<STEM>.V20, '' when
    the file is missing or the name is blank. Stems are stored lower case."""
    path = v20_path(league_dir, stem)
    if path is None:
        return ''
    try:
        with open(path, 'rb') as fh:
            raw = fh.read(14)
    except OSError:
        return ''
    return one_field(raw)


def team_disp(league_dir, stem):
    """Team column for a latin-1 team token: the V20 header name, else the token
    upper-cased."""
    return team_name(league_dir, stem.encode('latin-1')) or ascii_upper(stem)


def draft_pos(league_dir, stem, name, cache=None):
    """POS column of an offseason DRAFT pick (C17): the v20.F pos1 field of the first
    record slot 0..39 of the drafting team's <STEM>.V20 that is on (first byte non-zero)
    and whose rosters.pname matches the pick name exactly, as dynview.pos_name. '' when
    the file is missing, shorter than HDR + REC * 40, or no slot matches. The team file
    is read at most once per screen build (cache maps the token to its raw bytes, None
    when there is no readable file)."""
    if cache is not None and stem in cache:
        raw = cache[stem]
    else:
        path = v20_path(league_dir, stem.encode('latin-1'))
        raw = None
        if path is not None:
            try:
                with open(path, 'rb') as fh:
                    raw = fh.read()
            except OSError:
                raw = None
        if cache is not None:
            cache[stem] = raw
    if raw is None or len(raw) < rosters.HDR + rosters.REC * 40:
        return ''
    for slot in range(40):
        off = rosters.HDR + rosters.REC * slot
        rec = raw[off:off + rosters.REC]
        if rec[0] == 0 or rosters.pname(rec) != name:
            continue
        return pos_name(rosters._get(rec, *rosters.F['pos1']) & 15)
    return ''


def parse_rosters(league_dir):
    """ROSTERS.TXT as offseason events, in file order: ('DRAFT', stem, name) for the
    first DRAFT_KEEP valid DRAFT lines; ('SIGN', team, name, frm); ('TRADE', a, x, b,
    y) where b is the first token from index 3 that names a team file; ('REL', stem,
    name) for `REL <stem> <name...>`. LF lines with one trailing CR stripped; a line over
    ROSTER_LINE_MAX bytes is ignored whole. A missing or unreadable file gives []."""
    path = find_upper(league_dir, 'ROSTERS.TXT')
    if path is None:
        return []
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except OSError:
        return []
    out = []
    drafts = 0
    for line in raw.split(b'\n'):
        if line.endswith(b'\r'):
            line = line[:-1]
        if len(line) > ROSTER_LINE_MAX:
            continue
        tok = [t for t in line.decode('latin-1').split(' ') if t]
        n = len(tok)
        if n == 0:
            continue
        kind = tok[0]
        if kind == 'DRAFT' and n >= 3:
            if drafts < DRAFT_KEEP:
                drafts += 1
                out.append(('DRAFT', tok[1], ' '.join(tok[2:])))
        elif kind == 'SIGN' and n >= 4:
            out.append(('SIGN', tok[1], ' '.join(tok[2:-1]), tok[-1]))
        elif kind == 'TRADE' and n >= 5:
            for j in range(3, n - 1):
                if v20_path(league_dir, tok[j].encode('latin-1')) is not None:
                    out.append(('TRADE', tok[1], ' '.join(tok[2:j]), tok[j],
                                ' '.join(tok[j + 1:])))
                    break
        elif kind == 'REL' and n >= 3:
            out.append(('REL', tok[1], ' '.join(tok[2:])))
    return out


# ---------------------------------------------------------------- settings / control
def load_settings(league_dir):
    """(era, mask) from the first 32 bytes of HISTORY.DAT, zero padded: era is byte 10,
    mask the u32 LE of bytes 12..15. A missing or unreadable file is all zero."""
    try:
        with open(os.path.join(league_dir, 'HISTORY.DAT'), 'rb') as fh:
            d = fh.read(HDR_SIZE)
    except OSError:
        d = b''
    d = d.ljust(HDR_SIZE, b'\0')
    return d[10], int.from_bytes(d[12:16], 'little')


def settings_teams(league_dir):
    """[(id, display)] of the MAJ teams in id order (C12.3: teamids.teams with the league's
    TEAMID.DAT, engine ids without one). Empty with no MAJ, on a read error or a MAJ shorter
    than MAJ_MIN; a team whose stem is empty or has no V20 file is skipped. The whole MAJ is
    read (the 3 division slots past MAJ_MIN are real teams); a short one is NUL padded."""
    mp = history.maj_or_none(league_dir)
    if mp is None:
        return []
    try:
        with open(mp, 'rb') as fh:
            d = fh.read()
        table = teamids.load_table(league_dir)
    except OSError:
        return []
    if len(d) < MAJ_MIN:
        return []
    d = d.ljust(TEAM_SPAN, b'\0')
    out = []
    for tid, _L, _slot, st in teamids.teams(d, table):
        stem = st.split(b'\0')[0]
        if not stem or v20_path(league_dir, stem) is None:
            continue
        out.append((tid, team_disp(league_dir, stem.decode('latin-1'))))
    return out


def settings_team_stems(league_dir):
    """{ASCII upper case stem: stable id} of the MAJ teams (C17.2): the same walk
    settings_teams does (teamids.teams with the league's TEAMID.DAT, a team whose stem
    is empty or has no V20 file skipped), so the map holds exactly the listed teams.
    {} with no MAJ, on a read error or a MAJ shorter than MAJ_MIN."""
    mp = history.maj_or_none(league_dir)
    if mp is None:
        return {}
    try:
        with open(mp, 'rb') as fh:
            d = fh.read()
        table = teamids.load_table(league_dir)
    except OSError:
        return {}
    if len(d) < MAJ_MIN:
        return {}
    d = d.ljust(TEAM_SPAN, b'\0')
    out = {}
    for tid, _L, _slot, st in teamids.teams(d, table):
        stem = st.split(b'\0')[0]
        if not stem or v20_path(league_dir, stem) is None:
            continue
        out[ascii_upper(stem.decode('latin-1'))] = tid
    return out


def era_label(era):
    if era == 0:
        return 'REAL CALENDAR'
    if era == 2:
        return 'FREE AGENCY'
    return 'RESERVE CLAUSE'


def era_next(era):
    if era == 0:
        return 1
    if era == 2:
        return 0
    return 2


def playoff_label(fmt):
    """PLAYOFF FORMAT value from fmt = (wanted, now) (C12.4): '2 DIVISIONS' or
    '3 DIV + WILDCARD', and '2 DIV NEXT YEAR' / '3 DIV NEXT YEAR' when wanted and now differ."""
    wanted, now = fmt
    three = wanted == 3
    if wanted == now:
        return '3 DIV + WILDCARD' if three else '2 DIVISIONS'
    return '3 DIV NEXT YEAR' if three else '2 DIV NEXT YEAR'


def start_year(hist):
    """The start year (C13.1): HISTORY bytes 18..19 as u16 LE, START_DEFAULT when it is 0 or
    outside START_MIN..START_MAX."""
    v = hist.d[HDR_START] | hist.d[HDR_START + 1] << 8
    return v if START_MIN <= v <= START_MAX else START_DEFAULT


def year_of(hist, n):
    """The calendar year shown for season n (1-based): start year + n - 1 (C13.1)."""
    return start_year(hist) + n - 1


def settings_rows(data):
    """ERA RULES, PLAYOFF FORMAT, START YEAR (C13.1), then one row per team of data['teams']
    (YOU MANAGE / AI MANAGES); the cursor categories are 0, 1, 2 and 3 + the team index."""
    mask = data['mask']
    return [('ERA RULES', era_label(data['era'])),
            ('PLAYOFF FORMAT', playoff_label(data['fmt'])),
            ('START YEAR', '%d' % start_year(data['hist']))] + \
        [(disp, 'YOU MANAGE' if (mask >> tid) & 1 else 'AI MANAGES')
         for tid, disp in data['teams']]


def start_year_step(data, delta):
    """LEFT / RIGHT / '-' / '+' / '=' on START YEAR (C13.1): the start year moves by delta,
    clamped to START_MIN..START_MAX, and bytes 18..19 of HISTORY.DAT are written (the rest of
    the file is untouched). The in-memory header follows, so every season label relabels."""
    hist = data['hist']
    new = min(max(start_year(hist) + delta, START_MIN), START_MAX)
    put_hist_u16(data['league_dir'], HDR_START, new)
    hist.d[HDR_START], hist.d[HDR_START + 1] = new & 255, new >> 8


def save_settings(league_dir, era, mask):
    """Write byte 10 (era) and bytes 12..15 (mask, u32 LE) of HISTORY.DAT. A missing file
    is created and a short one zero-extended to 32 bytes; no other byte changes.
    OSError is ignored."""
    path = os.path.join(league_dir, 'HISTORY.DAT')
    try:
        try:
            with open(path, 'rb') as fh:
                d = bytearray(fh.read())
        except FileNotFoundError:
            d = bytearray()
        d += bytes(max(0, HDR_SIZE - len(d)))
        d[10] = era & 255
        d[12:16] = (mask & 0xffffffff).to_bytes(4, 'little')
        with open(path, 'wb') as fh:
            fh.write(d)
    except OSError:
        pass


def put_hist_byte(league_dir, pos, value):
    """Write byte pos of HISTORY.DAT with the save_settings rules: a missing file is created,
    a short one zero-extended to 32 bytes, no other byte changes; OSError is ignored."""
    path = os.path.join(league_dir, 'HISTORY.DAT')
    try:
        try:
            with open(path, 'rb') as fh:
                d = bytearray(fh.read())
        except FileNotFoundError:
            d = bytearray()
        d += bytes(max(0, HDR_SIZE - len(d)))
        d[pos] = value & 255
        with open(path, 'wb') as fh:
            fh.write(d)
    except OSError:
        pass


def put_hist_u16(league_dir, pos, value):
    """Write the u16 LE at pos, pos + 1 of HISTORY.DAT with the put_hist_byte rules: a missing
    file is created, a short one zero-extended to 32 bytes, no other byte changes."""
    path = os.path.join(league_dir, 'HISTORY.DAT')
    try:
        try:
            with open(path, 'rb') as fh:
                d = bytearray(fh.read())
        except FileNotFoundError:
            d = bytearray()
        d += bytes(max(0, HDR_SIZE - len(d)))
        d[pos], d[pos + 1] = value & 255, (value >> 8) & 255
        with open(path, 'wb') as fh:
            fh.write(d)
    except OSError:
        pass


def hist_byte(league_dir, pos):
    """Byte pos of HISTORY.DAT, or None when the file is missing, short or unreadable."""
    try:
        with open(os.path.join(league_dir, 'HISTORY.DAT'), 'rb') as fh:
            d = fh.read(pos + 1)
    except OSError:
        return None
    return d[pos] if len(d) > pos else None


def maj_day(league_dir):
    """The MAJ day byte (0x20a), or None when there is no MAJ or it is unreadable or short."""
    mp = history.maj_or_none(league_dir)
    if mp is None:
        return None
    try:
        with open(mp, 'rb') as fh:
            d = fh.read(MAJ_DAY + 1)
    except OSError:
        return None
    return d[MAJ_DAY] if len(d) > MAJ_DAY else None


def set_playoff_format(league_dir, wanted):
    """ENTER on PLAYOFF FORMAT (C12.4, C12.6): HISTORY byte 11 = 5 - wanted, then the apply at
    once: realign.apply when the MAJ day is 0xf3 and HISTORY byte 0 is 1, or the day is 7; after
    an apply on day 7, byte 0 = 1. A missing MAJ or an unreadable HISTORY leaves it at byte 11."""
    put_hist_byte(league_dir, HDR_FORMAT, 5 - wanted)
    day = maj_day(league_dir)
    rolled = hist_byte(league_dir, HDR_ROLLED)
    if day is None or rolled is None:
        return
    if not ((day == DAY_OVER and rolled == 1) or day == DAY_SETUP):
        return
    try:
        rc = realign.apply(league_dir)
    except OSError:
        return
    if rc == 0 and day == DAY_SETUP:
        put_hist_byte(league_dir, HDR_ROLLED, 1)


def control_item(path):
    """The /MENU item N in CONTROL[1] = 8 + N (N in 0..3); 0 when the file is missing,
    shorter than 2 bytes or holds any other value."""
    try:
        with open(path, 'rb') as fh:
            d = fh.read(2)
    except OSError:
        return 0
    if len(d) >= 2 and 8 <= d[1] <= 11:
        return d[1] - 8
    return 0


def control_return(path):
    """CONTROL[1] = CONTROL[0] in place so TONY2.BAT restarts MAIN. A file under 2 bytes
    is left alone; a missing file is not created; OSError is ignored."""
    try:
        with open(path, 'r+b') as fh:
            d = fh.read(2)
            if len(d) < 2:
                return
            fh.seek(1)
            fh.write(d[:1])
    except OSError:
        pass


# ---------------------------------------------------------------- portraits (C13.5)
def portrait_stock(anms_dir, k):
    """(w, h, pixels) of PORTRAIT.ANM frame k, or None. A copy of create.portrait (create imports
    dynview, so it cannot be imported here): frame k must be stored (clen 0) at 48 x 56 and fit
    the file; frames before it are skipped by their 12 B headers (flags, h, w, yo, xo, clen)."""
    path = find_upper(anms_dir, 'PORTRAIT.ANM')
    if path is None:
        return None
    try:
        with open(path, 'rb') as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(0)
            head = fh.read(2)
            if len(head) < 2:
                return None
            count = struct.unpack('<H', head)[0]
            if k >= count:
                return None
            p = 2
            for i in range(k + 1):
                fh.seek(p)
                hdr = fh.read(12)
                if len(hdr) < 12:
                    return None
                _flags, h, w, _yo, _xo, clen = struct.unpack('<6H', hdr)
                if i < k:
                    p += 12 + (h * w if clen == 0 else clen)
                    continue
                if clen != 0 or w != PORTRAIT_W or h != PORTRAIT_H \
                        or p + 12 + h * w > size:
                    return None
                fh.seek(p + 12)
                px = fh.read(h * w)
                if len(px) != h * w:
                    return None
                return (w, h, px)
    except OSError:
        return None
    return None


def portrait_old(game_dir, k):
    """(w, h, pixels) of OLDPORT.ANM frame k, or None: no count word, frame k at k * OLD_FRAME,
    a 12 B header with clen 0 and 48 x 56, then 2688 B of pixels."""
    path = find_upper(game_dir, 'OLDPORT.ANM')
    if path is None:
        return None
    try:
        with open(path, 'rb') as fh:
            fh.seek(k * OLD_FRAME)
            hdr = fh.read(12)
            if len(hdr) < 12:
                return None
            _flags, h, w, _yo, _xo, clen = struct.unpack('<6H', hdr)
            if clen != 0 or w != PORTRAIT_W or h != PORTRAIT_H:
                return None
            px = fh.read(h * w)
            if len(px) != h * w:
                return None
            return (w, h, px)
    except OSError:
        return None


def portrait_of(data, face):
    """The portrait of a face (C13.5): stock frames below OLD_FACE, OLDPORT frames up to
    OLD_FACE_END; None when the frame is missing or the face is out of range."""
    if face < OLD_FACE:
        return portrait_stock(data.get('anms_dir', 'ANMS'), face)
    if face < OLD_FACE_END:
        return portrait_old(data.get('game_dir', '.'), face - OLD_FACE)
    return None


# ---------------------------------------------------------------- primitives
def glyph_of(font, ch):
    k = ord(ch) - 32
    if k < 0 or k > 94:
        k = ord('?') - 32                       # glyph 31
    return font[k]


def ascii_upper(s):
    """a-z only, like DOS: str.upper() would turn latin-1 0xDF into 'SS'."""
    return ''.join(chr(ord(c) - 32) if 'a' <= c <= 'z' else c for c in s)


def draw_text(fb, font, x, y, s, color):
    for ch in ascii_upper(s):
        rows, bits, adv, data_, bpr = glyph_of(font, ch)
        for r in range(rows):
            py = y + r
            if py < 0 or py >= FB_H:
                continue
            row = data_[r * bpr:(r + 1) * bpr]
            base = py * FB_W
            for c in range(bits):
                if row[c // 8] & (0x80 >> (c % 8)):
                    px = x + c
                    if 0 <= px < FB_W:
                        fb[base + px] = color
        x += adv


def text_width(font, s):
    w = 0
    for ch in ascii_upper(s):
        w += glyph_of(font, ch)[2]
    return w


def fill(fb, color):
    fb[:] = bytes([color]) * FB_SIZE


def rect(fb, x0, y0, x1, y1, color):
    for y in range(max(y0, 0), min(y1, FB_H - 1) + 1):
        base = y * FB_W
        for x in range(max(x0, 0), min(x1, FB_W - 1) + 1):
            fb[base + x] = color


# ---------------------------------------------------------------- formatting
def one_field(b):
    """NUL-or-space terminated field, trailing spaces stripped, latin-1."""
    return b.split(b'\0')[0].rstrip(b' ').decode('latin-1')


def name_display(name20, cap=18):
    """V20 name bytes 0..19 (last 12, first 8): 'LAST, F' style, cut to cap chars.
    A name with an empty first part, or no room for one first-name char, is just
    the last name (never a dangling comma)."""
    last = one_field(name20[0:12])
    first = one_field(name20[12:20])
    if first and len(last) + 3 <= cap:
        return (last + ', ' + first)[:cap]
    return last[:cap]


def stem_display(stem8, league_dir=None):
    if stem8.strip(b'\0') == b'':
        return '?'
    return team_name(league_dir, one_field(stem8).encode('latin-1')) or one_field(stem8).upper()


def fmt_count(v):
    return '%d' % v


def fmt_avg(v):
    """v = batting average x 1000: '.ddd' (or '1.000')."""
    if v <= 0:
        return '.000'
    if v >= 1000:
        return '1.000'
    return '.%03d' % v


def fmt_era100(v):
    """v = ERA x 100: 'd.dd'."""
    neg = v < 0
    if neg:
        v = -v
    s = '%d.%02d' % (v // 100, v % 100)
    return ('-' + s) if neg else s


def fmt_war10(v):
    """v = WAR10 (WAR x 10): '-d.d' / 'd.d'."""
    neg = v < 0
    a = -v if neg else v
    s = '%d.%d' % (a // 10, a % 10)
    return ('-' + s) if neg else s


def fmt_ip(outs):
    """outs = OUTS: whole innings and thirds, '1234.2'."""
    return '%d.%d' % (outs // 3, outs % 3)


def avg_of(t):
    return t[2] * 1000 // t[1] if t[1] else 0


def era100_of(t):
    return t[20] * 2700 // t[19] if t[19] else 0


def event_text(kind, value):
    s = CAREER_EVENTS.get(kind)
    if s is not None:
        return s
    if kind == 32:
        return '%d HR SEASON' % value
    if kind == 33:
        return '%d HIT SEASON' % value
    if kind == 34:
        return '%d SB SEASON' % value
    if kind == 35:
        return fmt_avg(value) + ' SEASON'
    if kind == 36:
        return '%d WIN SEASON' % value
    if kind == 37:
        return '%d STRIKEOUT SEASON' % value
    if kind == 38:
        return fmt_era100(value) + ' ERA SEASON'
    if kind == 39:
        return '%d SAVE SEASON' % value
    return '?'


# ---------------------------------------------------------------- categories
# cat_value / season_qualifies take a career entry or a SEASLINE line: both carry 'totals'
# (TOTALS order) and 'WAR10'; only career entries carry 'awards'
def cat_value(e, cat):
    _label, kind, idx = cat
    if kind == 'count' or kind == 'ip':
        return e['totals'][idx]
    if kind == 'avg':
        return avg_of(e['totals'])
    if kind == 'era':
        return era100_of(e['totals'])
    if kind == 'war':
        return e['WAR10']
    if kind == 'aw0':
        return e['awards'][0]
    return e['awards'][3]


def cat_qualifies(e, cat):
    """Career qualifiers (C7 and C13.3)."""
    _label, kind, idx = cat
    t = e['totals']
    if kind == 'count' or kind == 'ip':
        return t[idx] > 0
    if kind == 'avg':
        return t[1] >= 3000
    if kind == 'era':
        return t[19] >= 4500
    if kind == 'aw0' or kind == 'aw3':
        return cat_value(e, cat) > 0
    return True                               # WAR: no qualifier


def season_qualifies(ln, cat):
    """SEASON and BY YEAR qualifiers (C13.3) over one SEASLINE line: AVG needs AB > 0 and
    pa = AB + BB >= 502; ERA needs OUTS >= 486; WAR needs G > 0; counts and IP need value > 0."""
    kind = cat[1]
    t = ln['totals']
    if kind == 'avg':
        return t[T_AB] > 0 and t[T_AB] + t[T_BB] >= 502
    if kind == 'era':
        return t[T_OUTS] >= 486
    if kind == 'war':
        return t[T_G] > 0
    return cat_value(ln, cat) > 0


def cat_format(cat, value):
    kind = cat[1]
    if kind == 'avg':
        return fmt_avg(value)
    if kind == 'era':
        return fmt_era100(value)
    if kind == 'war':
        return fmt_war10(value)
    if kind == 'ip':
        return fmt_ip(value)
    return fmt_count(value)


# ---------------------------------------------------------------- row builders
def n_entries(hist):
    """Player entries written by the recorder (header count, guarded)."""
    cnt = hist.d[6] | hist.d[7] << 8
    if 0 < cnt <= len(hist._entries):
        return cnt
    return len(hist._entries)


def entry_name(hist, idx, cap):
    if idx == history.NO_AWARD:
        return 'NONE'
    if idx < 0 or idx >= n_entries(hist):
        return '?'
    return name_display(hist.read_entry(idx)['name'], cap) or '?'


def history_rows(hist, league_dir=None, stems=None, mask=0):
    """One row per season, newest first: YEAR, CHAMPION, AL MVP, NL MVP (the
    runner-up is on REVIEW; dropping it leaves room for full team names). The
    CHAMPION cell is starred when the champion stem maps through stems (the
    settings_team_stems walk, C18) to a managed id (bit set in mask)."""
    n = min(hist.seasons_recorded, history.SEASON_COUNT)
    items = []
    for pos in range(1, n + 1):
        se = hist.read_season_entry(pos)
        items.append((-se['season_no'], pos, se))
    items.sort(key=lambda t: (t[0], t[1]))
    out = []
    for _s, _p, se in items:
        champ = stem_display(se['champion_stem'], league_dir)
        if stems:
            champ = managed_cell_id(stems, se['champion_stem'], mask, champ)
        out.append((year_text(hist, se['season_no']),
                    champ,
                    entry_name(hist, se['awards'][0], 11),
                    entry_name(hist, se['awards'][3], 11)))
    return out


def stems_managed(stems, stem8, mask):
    """True when the 8 byte champion stem (cut at the first NUL, trailing spaces dropped,
    ASCII upper case) maps through stems to a managed id (C18: tid < 32, mask bit set)."""
    stem = stem8.split(b'\0')[0].rstrip(b' ').decode('latin-1')   # as C's field_of
    tid = stems.get(ascii_upper(stem)) if stem else None
    return tid is not None and tid < 32 and ((mask >> tid) & 1) != 0


def managed_cell_id(stems, stem8, mask, text):
    """CHAMPION cell of a managed team (C18): '*' + the display text."""
    return ('*' if stems_managed(stems, stem8, mask) else '') + text


def year_text(hist, n):
    return '%d' % year_of(hist, n)


def hof_order(hist):
    """[(entry index, entry)] of status 3 entries by (HoF season descending, index ascending),
    at most LIST_MAX (the HALL OF FAME rows and their cursor entries)."""
    items = []
    for i in range(n_entries(hist)):
        e = hist.read_entry(i)
        if e['status'] == history.STATUS_HOF:
            items.append((-e['hof_season'], i, e))
    items.sort(key=lambda t: (t[0], t[1]))
    return [(i, e) for _s, i, e in items[:LIST_MAX]]


def hof_rows(hist):
    """Status 3 entries by (HoF season descending, index ascending):
    NAME, IND, YRS, H/W, HR/SO(PSO), AVG/ERA, WAR."""
    out = []
    for _i, e in hof_order(hist):
        t = e['totals']
        if e['pitcher']:
            s1, s2, s3 = fmt_count(t[13]), fmt_count(t[23]), fmt_era100(era100_of(t))
        else:
            s1, s2, s3 = fmt_count(t[2]), fmt_count(t[5]), fmt_avg(avg_of(t))
        out.append((name_display(e['name'], 12) or '?',
                    year_text(hist, e['hof_season']), '%d' % e['seasons_played'],
                    s1, s2, s3, fmt_war10(e['WAR10'])))
    return out


def career_order(hist, cat_index):
    """[(value, entry index, entry)] of the career qualifiers of CATS[cat_index] in leader order
    (value descending, the ERA ascending; then entry index ascending), at most LIST_MAX."""
    cat = CATS[cat_index]
    cands = []
    for i in range(n_entries(hist)):
        e = hist.read_entry(i)
        if cat_qualifies(e, cat):
            cands.append((cat_value(e, cat), i, e))
    if cat[1] == 'era':
        cands.sort(key=lambda t: (t[0], t[1]))
    else:
        cands.sort(key=lambda t: (-t[0], t[1]))
    return cands[:LIST_MAX]


def career_leader_cells(hist, cat_index):
    """Every career leader row (rank counted from the top of the list): rank, NAME, status
    mark, YRS, value."""
    cat = CATS[cat_index]
    out = []
    for rank, (val, _i, e) in enumerate(career_order(hist, cat_index)):
        status = e['status']
        if status == history.STATUS_RETIRED:
            mark = 'R'
        elif status == history.STATUS_HOF:
            mark = 'H'
        else:
            mark = ' '
        out.append(('#%d' % (rank + 1), name_display(e['name'], 16) or '?', mark,
                    '%d' % e['seasons_played'], cat_format(cat, val)))
    return out


def leaders_rows(hist, cat_index, page=0):
    """Career leaders, the rows of one page: see career_leader_cells."""
    return career_leader_cells(hist, cat_index)[page * ROWS_PER_PAGE:
                                                (page + 1) * ROWS_PER_PAGE]


def season_order(lines, cat, season=None):
    """[(value, season, entry index, line)] of the SEASON leader order over lines (or only
    the lines of one season): value descending (ERA ascending), then season ascending, then
    entry index ascending; the top SEASON_MAX. Qualifiers as season_qualifies."""
    items = []
    for ln in lines:
        if season is not None and ln['season'] != season:
            continue
        if season_qualifies(ln, cat):
            items.append((cat_value(ln, cat), ln['season'], ln['entry'], ln))
    if cat[1] == 'era':
        items.sort(key=lambda t: (t[0], t[1], t[2]))
    else:
        items.sort(key=lambda t: (-t[0], t[1], t[2]))
    return items[:SEASON_MAX]


def line_seasons(lines):
    """Distinct season numbers with lines, ascending."""
    return sorted({ln['season'] for ln in lines})


def milestone_rows(hist, ms):
    """MILESTON.DAT records (award records skipped), newest season first, within a
    season in file order: YEAR, NAME, EVENT."""
    items = []
    for pos, rec in enumerate(ms):
        season, _idx, kind, _value = rec
        if kind < AWARD_KIND_MIN:
            items.append((-season, pos, rec))
    items.sort(key=lambda t: (t[0], t[1]))
    out = []
    for _s, _p, (season, idx, kind, value) in items[:LIST_MAX]:
        out.append((year_text(hist, season), entry_name(hist, idx, 16),
                    event_text(kind, value)))
    return out


# WATCH (C27): the stat labels of the WATCH MARK column; PSO is shown as SO.
WATCH_LABELS = {'H': 'H', 'HR': 'HR', 'RBI': 'RBI', 'SB': 'SB', 'W': 'W',
                'PSO': 'SO', 'SV': 'SV'}
# MILESTONE_CAREER kind -> stat label ('PSO' shown as SO)
WATCH_KIND_LABELS = {kind: WATCH_LABELS[key] for kind, key, _mark in history.MILESTONE_CAREER}


def watch_rows(hist):
    """WATCH rows (C27): one row per watch_items item, NAME, '%d %s' % (mark, label),
    '%d' % now, '%d' % need (label = the item kind's stat key, PSO shown as SO). No item:
    one COLS_SINGLE row 'NO ACTIVE PLAYER NEAR A MILESTONE'."""
    out = []
    for need, mark, kind, entry, now in watch_items(hist):
        out.append((entry_name(hist, entry, 16), '%d %s' % (mark, WATCH_KIND_LABELS[kind]),
                    '%d' % now, '%d' % need))
    return out or [('NO ACTIVE PLAYER NEAR A MILESTONE',)]


def watch_item_sort(item):
    """The watch_items sort key: (need * 1000 // mark, need, entry, kind) ascending
    (integer math; the C port must build the same key)."""
    need, mark, kind, entry, _now = item
    return (need * 1000 // mark, need, entry, kind)


def watch_marks():
    """The distinct stat keys of MILESTONE_CAREER in first-seen order."""
    out = []
    for _kind, key, _mark in history.MILESTONE_CAREER:
        if key not in [k for _k, k in out]:
            out.append((_kind, key))
    return out


def watch_items(hist):
    """[(need, mark, kind, entry, now)] of the active players (status STATUS_ACTIVE) within
    10% of an unreached MILESTONE_CAREER mark: for each entry and stat key the lowest mark
    of that key with now < mark (now = the entry's career total of the key, via
    history.TOTALS.index(key)); keep it when now * 10 >= mark * 9 (within 10%).
    need = mark - now. Sorted by (need * 1000 // mark, need, entry, kind) ascending, at
    most LIST_MAX."""
    items = []
    for i in range(n_entries(hist)):
        e = hist.read_entry(i)
        if e['status'] != history.STATUS_ACTIVE:
            continue
        for _kind, key in watch_marks():
            now = e['totals'][history.TOTALS.index(key)]
            above = [(m, k) for k, k2, m in history.MILESTONE_CAREER if k2 == key and now < m]
            if not above:
                continue
            mark, mkind = min(above)                   # the lowest unreached mark and its kind
            if now * 10 < mark * 9:
                continue
            items.append((mark - now, mark, mkind, i, now))
    items.sort(key=watch_item_sort)
    return items[:LIST_MAX]


def review_rows(hist, ms, league_dir=None):
    """REVIEW lines for the last recorded season; None when there is no history.
    Champion/runner-up, six award lines, new HoF entries, that season's milestones
    (award records skipped); cut at 12 lines."""
    if hist.seasons_recorded <= 0:
        return None
    last = hist.seasons_recorded
    se = hist.read_season_entry(min(last, history.SEASON_COUNT))
    aw = se['awards']
    lines = [('CHAMPION ' + stem_display(se['champion_stem'], league_dir),),
             ('RUNNER-UP ' + stem_display(se['runner_up_stem'], league_dir),),
             ('AL MVP ' + entry_name(hist, aw[0], 16),),
             ('AL CY YOUNG ' + entry_name(hist, aw[1], 16),),
             ('AL ROOKIE ' + entry_name(hist, aw[2], 16),),
             ('NL MVP ' + entry_name(hist, aw[3], 16),),
             ('NL CY YOUNG ' + entry_name(hist, aw[4], 16),),
             ('NL ROOKIE ' + entry_name(hist, aw[5], 16),)]
    for i in range(n_entries(hist)):
        e = hist.read_entry(i)
        if e['status'] == history.STATUS_HOF and e['hof_season'] == last:
            lines.append(('NEW HALL OF FAME: ' + (name_display(e['name']) or '?'),))
    for pos, rec in enumerate(ms):
        season, idx, kind, value = rec
        if season == last and kind < AWARD_KIND_MIN:
            lines.append((entry_name(hist, idx, 16) + ' ' + event_text(kind, value),))
    return lines[:ROWS_PER_PAGE]


# ---------------------------------------------------------------- awards
# SEASON AWARDS (C7 award records): kind 64 + k (AL) or 96 + k (NL); k 0 MVP, 1 CY YOUNG,
# 2 ROOKIE, 2 + q GLOVE at position q (1..8), 10 + q SLUGGER at position q (1..9)
AWARD_POS = ['', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH']
AWARD_FALLBACK = ['AL MVP', 'AL CY YOUNG', 'AL ROOKIE',
                  'NL MVP', 'NL CY YOUNG', 'NL ROOKIE']
# SEASON AWARDS leader records (C7 second amendment): kind 128 + k (AL) or 160 + k (NL),
# k indexes LEADER_CATS; idx = the leader's entry index, value = the stat as u16
LEADER_CATS = ['BA', 'HR', 'RBI', 'H', 'SB', 'W', 'ERA', 'SO', 'SV']


def award_kind(kind):
    return 64 <= kind <= 83 or 96 <= kind <= 115


def award_k(kind):
    return kind - 96 if kind >= 96 else kind - 64


def leader_kind(kind):
    return 128 <= kind <= 136 or 160 <= kind <= 168


def leader_k(kind):
    return kind - 160 if kind >= 160 else kind - 128


def award_label(kind):
    k = award_k(kind)
    lg = 'NL' if kind >= 96 else 'AL'
    if k == 0:
        what = 'MVP'
    elif k == 1:
        what = 'CY YOUNG'
    elif k == 2:
        what = 'ROOKIE'
    elif k <= 10:
        what = 'GLOVE ' + AWARD_POS[k - 2]
    else:
        what = 'SLUGGER ' + AWARD_POS[k - 10]
    return lg + ' ' + what


def award_value(kind, value):
    """value is the stored u16 (an s16): WAR10 for MVP, CY and ROOKIE, fp1000 for a
    GLOVE, bat100 for a SLUGGER (shown as runs, truncated toward zero)."""
    v = value - 65536 if value >= 32768 else value
    k = award_k(kind)
    if k <= 2:
        return fmt_war10(v) + ' WAR'
    if k <= 10:
        return fmt_avg(v) + ' FLD'
    t = -((-v) // 10) if v < 0 else v // 10
    return fmt_war10(t) + ' RUNS'


def leader_label(kind):
    lg = 'NL' if kind >= 160 else 'AL'
    return lg + ' ' + LEADER_CATS[leader_k(kind)] + ' LEADER'


def leader_value(kind, value):
    """value is the stored u16 with no sign: BA as .ddd, ERA as d.dd (x100), else a count"""
    cat = LEADER_CATS[leader_k(kind)]
    if cat == 'BA':
        return fmt_avg(value) + ' BA'
    if cat == 'ERA':
        return '%d.%02d ERA' % (value // 100, value % 100)
    return '%d %s' % (value, cat)


def awards_items(hist, ms, season):
    """[(row cells, entry index or None)] of SEASON AWARDS rows of season (see awards_rows);
    the entry index is the row's player entry for the PLAYER CARD, None for a message row, the
    GG SS row, an empty slot (NO_AWARD) or an index past the entry table."""
    recs = [(kind, pos, idx, value) for pos, (s, idx, kind, value) in enumerate(ms)
            if s == season and (award_kind(kind) or leader_kind(kind))]
    if recs:
        recs.sort(key=lambda t: (t[0], t[1]))
        out = []
        for kind, _pos, idx, value in recs[:AWARD_MAX]:
            if leader_kind(kind):
                label, text = leader_label(kind), leader_value(kind, value)
            else:
                label, text = award_label(kind), award_value(kind, value)
            out.append(((label, entry_name(hist, idx, 16), text), idx))
        return out
    if season <= history.SEASON_COUNT:
        aw = hist.read_season_entry(season)['awards']
        out = [((label, entry_name(hist, aw[k], 16), ''), aw[k])
               for k, label in enumerate(AWARD_FALLBACK)]
        return out + [(('GG SS', 'NOT RECORDED', ''), None)]
    return [(('NO AWARDS RECORDED',), None)]


def awards_rows(hist, ms, season):
    """SEASON AWARDS rows of season: its award and leader records of ms in (kind, file
    position) order (AL and NL awards, then AL and NL leaders); a season recorded before
    the award records shows its six winners and a GG SS row; past the history table one
    message row. At most AWARD_MAX rows."""
    return [cells for cells, _idx in awards_items(hist, ms, season)]


def award_entry(hist, idx):
    """idx as a player entry for the PLAYER CARD: a valid entry index, else None (NO_AWARD, a
    message row or an index past the entry table)."""
    if idx is None or idx == history.NO_AWARD or idx >= n_entries(hist):
        return None
    return idx


def awards_body(state, data):
    """(cols, rows) of SEASON AWARDS: the season cat seasons back from the newest. A
    lone message row uses COLS_SINGLE (as the offseason's); no history gives no rows."""
    hist = data['hist']
    if hist.seasons_recorded == 0:
        return COLS_SINGLE, []
    rows = awards_rows(hist, data['ms'], hist.seasons_recorded - state[2])
    if len(rows) == 1 and len(rows[0]) == 1:
        return COLS_SINGLE, rows
    return COLS_AWARDS, rows


# ---------------------------------------------------------------- standings
# SEASON STANDINGS (C2 season entry w_l): AL ids 0..15, NL ids 16..31 (stable ids, C12.3).
# The divisions of a team come from the entry (history.division_of, C12.7)
STAND_LEAGUES = [('AL', 'AMERICAN LEAGUE', 0), ('NL', 'NATIONAL LEAGUE', 16)]
# C12.8 division blocks in display order: (division number, header suffix)
STAND_DIVS = [(2, ' WEST'), (3, ' CENTRAL'), (1, ' EAST')]


def gb_text(d):
    """games behind from d = (leader W - W) + (L - leader L): '-', '4.0', '4.5', '-2.0'."""
    if d == 0:
        return '-'
    a = abs(d)
    s = '%d.5' % (a // 2) if a % 2 else '%d.0' % (a // 2)
    return '-' + s if d < 0 else s


def standings_block(se, names, head, ids, stems=None, mask=0):
    """header row head, then the teams ids (all with games) by (PCT desc, W desc, id asc):
    TEAM, W, L, PCT, GB from the block's first row, and the mark (WS champion, P a pennant
    winner). A managed team id (bit set of mask, C18) has '*' prepended to its TEAM cell."""
    wl = se['w_l']
    pct = {t: wl[t][0] * 1000 // (wl[t][0] + wl[t][1]) for t in ids}
    ids = sorted(ids, key=lambda t: (-pct[t], -wl[t][0], t))
    lw, ll = wl[ids[0]]
    out = [(head, '', '', '', '', '')]
    for t in ids:
        w, l = wl[t]
        if t == se['champion']:
            mark = 'WS'
        elif t in (se['al_pennant'], se['nl_pennant']):
            mark = 'P'
        else:
            mark = ''
        name = names.get(t, 'TEAM %d' % t)
        if stems is not None and t < 32 and ((mask >> t) & 1) != 0:
            name = '*' + name
        out.append((name, '%d' % w, '%d' % l, fmt_avg(pct[t]),
                    gb_text((lw - w) + (l - ll)), mark))
    return out


def standings_rows(hist, teams, season, stems=None, mask=0):
    """SEASON STANDINGS rows of season. Per league the teams that played (W + L > 0) are
    grouped by division (history.division_of). When two or more divisions have such teams,
    one block per division in STAND_DIVS order (WEST, CENTRAL, EAST) under a header row
    `AL WEST` and so on; with one division, one block under the league's long name; none
    otherwise. A header that would fall on a page's last row gets a blank row before it.
    Managed team ids have '*' prepended to their TEAM cell (C18). Past the history table,
    or with no games in either league, one message row."""
    if season > history.SEASON_COUNT:
        return [('NO STANDINGS RECORDED',)]
    se = hist.read_season_entry(season)
    names = dict(teams)
    played = {t for t, (w, l) in enumerate(se['w_l']) if w + l > 0}
    out = []
    for short, long_name, base in STAND_LEAGUES:
        by_div = {}
        for t in range(base, base + 16):
            if t in played:
                by_div.setdefault(history.division_of(se, t), []).append(t)
        found = [(div, suffix) for div, suffix in STAND_DIVS if div in by_div]
        if len(found) >= 2:
            blocks = [(short + suffix, by_div[div]) for div, suffix in found]
        elif found:
            blocks = [(long_name, by_div[found[0][0]])]
        else:
            blocks = []
        for head, ids in blocks:
            if len(out) % ROWS_PER_PAGE == ROWS_PER_PAGE - 1:
                out.append(('', '', '', '', '', ''))     # no header alone on a page's last row
            out += standings_block(se, names, head, ids, stems, mask)
    return out or [('NO STANDINGS RECORDED',)]


def standings_body(state, data):
    """(cols, rows) of SEASON STANDINGS: the season cat seasons back from the newest. A
    lone message row uses COLS_SINGLE (as SEASON AWARDS'); no history gives no rows."""
    hist = data['hist']
    if hist.seasons_recorded == 0:
        return COLS_SINGLE, []
    rows = standings_rows(hist, data['teams'], hist.seasons_recorded - state[2],
                          data.get('team_stems'), data['mask'])
    if len(rows) == 1 and len(rows[0]) == 1:
        return COLS_SINGLE, rows
    return COLS_STANDINGS, rows


# ---------------------------------------------------------------- world series
# WORLD SERIES (C7 third amendment): MILESTON.DAT kind 192 + g (g 0..6) is game g + 1, idx =
# visitor id * 256 + home id, value = visitor runs * 256 + home runs; kind 200 + g is the
# same game's hits and errors, idx = visitor hits * 256 + home hits, value = visitor errors
# * 256 + home errors. Team ids are league-global (AL 0..15, NL 16..31).
SERIES_GAME_KIND, SERIES_HE_KIND, SERIES_GAMES = 192, 200, 7
# BOXSCORE.DAT (C7 fourth amendment, next to HISTORY.DAT): 16 B records, u16 season, u8 game
# g, u8 flags (bit0 side: 0 visitor, 1 home; bit1 pitching row), u16 player entry index
# (0xffff none), u8 batting-slot byte b, u8 player id i, 8 u8 stats. Batting stats AB R H
# RBI HR BB SO SB; pitching stats IP10 (innings x 10), H, R, ER, HR, BB, SO, BF
BOX_FILE, BOX_REC, BOX_RECS_MAX = 'BOXSCORE.DAT', 16, 112


def first_record(ms, season, kind):
    """(idx, value) of the first MILESTON.DAT record of season and kind in file order;
    None when there is none."""
    for s, idx, k, value in ms:
        if s == season and k == kind:
            return idx, value
    return None


def series_rows(hist, ms, teams, season, stems=None, mask=0):
    """WORLD SERIES rows of season: per game with a kind 192 + g record (g ascending),
    a header row GAME g+1, the visitor and home rows (R, then H and E from the kind
    200 + g record, empty without one, W in the last column of the side with more runs),
    then one summary row over the first game's two teams t1 (visitor) and t2 (home): the
    one with more game wins (WINS a-b with 4 or more, else LEADS a-b), or SERIES with
    TIED a-a for equal wins. Managed team ids have '*' prepended to their TEAM cell,
    game headers never (C18). Past the history table or with no game record, one
    message row."""
    if season > history.SEASON_COUNT:
        return [('NO WORLD SERIES RECORDED',)]
    names = dict(teams)

    def starred(t):
        name = names.get(t, 'TEAM %d' % t)
        if stems is not None and t < 32 and ((mask >> t) & 1) != 0:
            name = '*' + name
        return name

    games = []
    for g in range(SERIES_GAMES):
        game = first_record(ms, season, SERIES_GAME_KIND + g)
        if game is not None:
            games.append((g, game, first_record(ms, season, SERIES_HE_KIND + g)))
    if not games:
        return [('NO WORLD SERIES RECORDED',)]
    out = []
    wins = Counter()
    for g, (idx, value), he in games:
        v, h = idx >> 8, idx & 255
        vr, hr = value >> 8, value & 255
        if he is None:
            hits = errs = ('', '')
        else:
            hits = ('%d' % (he[0] >> 8), '%d' % (he[0] & 255))
            errs = ('%d' % (he[1] >> 8), '%d' % (he[1] & 255))
        out.append(('GAME %d' % (g + 1), '', '', '', ''))
        out.append((starred(v), '%d' % vr, hits[0], errs[0],
                    'W' if vr > hr else ''))
        out.append((starred(h), '%d' % hr, hits[1], errs[1],
                    'W' if hr > vr else ''))
        if vr != hr:
            wins[v if vr > hr else h] += 1
    t1, t2 = games[0][1][0] >> 8, games[0][1][0] & 255
    w1, w2 = wins[t1], wins[t2]
    if w1 == w2:
        out.append(('SERIES', '', '', '', 'TIED %d-%d' % (w1, w2)))
    else:
        lead, a, b = (t1, w1, w2) if w1 > w2 else (t2, w2, w1)
        out.append((starred(lead), '', '', '',
                    ('WINS %d-%d' if a >= 4 else 'LEADS %d-%d') % (a, b)))
    return out


def series_body(state, data):
    """(cols, rows) of WORLD SERIES: the season cat seasons back from the newest. A lone
    message row uses COLS_SINGLE (as SEASON STANDINGS'); no history gives no rows."""
    hist = data['hist']
    if hist.seasons_recorded == 0:
        return COLS_SINGLE, []
    rows = series_rows(hist, data['ms'], data['teams'], hist.seasons_recorded - state[2],
                       data.get('team_stems'), data['mask'])
    if len(rows) == 1 and len(rows[0]) == 1:
        return COLS_SINGLE, rows
    return COLS_SERIES, rows


def playoff_games(box, season):
    """[(g, idx, b, i, stats)] of the season's flags-4 header records with g >= 16, g
    ascending (the round headers come in g order; the sort keeps that when they don't)."""
    games = [(r[1], r[3], r[4], r[5], r[6]) for r in box
             if r[0] == season and r[2] == 4 and r[1] >= 16]
    games.sort(key=lambda t: t[0])
    return games


def playoff_rows(hist, box, teams, season, stems=None, mask=0):
    """PLAYOFFS rows of season: past the history table or with no game, one message row.
    Otherwise per series (consecutive games with the same b), a title row
    (`AL DIVISION SERIES` and the like), then per game the three rows series_rows makes
    for a WS game, then the summary row series_rows makes over the series' first game's
    two teams with the WINS threshold 3 for the division series and 4 for the LCS. Managed
    team ids have '*' prepended to their TEAM cell; game and title header rows never."""
    if season > history.SEASON_COUNT:
        return [('NO PLAYOFF ROUNDS RECORDED',)]
    names = dict(teams)

    def starred(t):
        name = names.get(t, 'TEAM %d' % t)
        if stems is not None and t < 32 and ((mask >> t) & 1) != 0:
            name = '*' + name
        return name

    games = playoff_games(box, season)
    if not games:
        return [('NO PLAYOFF ROUNDS RECORDED',)]
    out = []
    k = 0
    while k < len(games):
        b = games[k][2]
        rnd, L = b & 3, (b >> 2) & 1
        rows = [games[k]]
        j = k + 1
        while j < len(games) and games[j][2] == b:
            rows.append(games[j])
            j += 1
        k = j
        out.append(('%s %s' % (('AL', 'NL')[L], ('DIVISION SERIES',
                                                'CHAMPIONSHIP SERIES')[rnd - 1]),
                    '', '', '', ''))
        wins = Counter()
        v1, h1 = rows[0][1] >> 8, rows[0][1] & 255
        for g, idx, _b, i, stats in rows:
            v, h = idx >> 8, idx & 255
            vr, hr = stats[0], stats[1]
            out.append(('GAME %d' % i, '', '', '', ''))
            out.append((starred(v), '%d' % vr, '%d' % stats[2], '%d' % stats[4],
                        'W' if vr > hr else ''))
            out.append((starred(h), '%d' % hr, '%d' % stats[3], '%d' % stats[5],
                        'W' if hr > vr else ''))
            if vr != hr:
                wins[v if vr > hr else h] += 1
        w1, w2 = wins[v1], wins[h1]
        if w1 == w2:
            out.append(('SERIES', '', '', '', 'TIED %d-%d' % (w1, w2)))
        else:
            lead, a, b2 = (v1, w1, w2) if w1 > w2 else (h1, w2, w1)
            out.append((starred(lead), '', '', '',
                        ('WINS %d-%d' if a >= (3 if rnd == 1 else 4)
                         else 'LEADS %d-%d') % (a, b2)))
    return out


def playoffs_body(state, data):
    """(cols, rows) of PLAYOFFS: the season cat seasons back from the newest. A lone
    message row uses COLS_SINGLE (as WORLD SERIES does); no history gives no rows."""
    hist = data['hist']
    if hist.seasons_recorded == 0:
        return COLS_SINGLE, []
    rows = playoff_rows(hist, data['box'], data['teams'],
                        hist.seasons_recorded - state[2],
                        data.get('team_stems'), data['mask'])
    if len(rows) == 1 and len(rows[0]) == 1:
        return COLS_SINGLE, rows
    return COLS_SERIES, rows


def box_line(hist, rec):
    """one BOXSCORE.DAT record as a row: NAME, then the batting numbers AB R H RBI BB SO, or
    for a pitching row IP (d.d), H R ER BB SO"""
    _season, _g, flags, idx, _b, _i, s = rec
    name = '?' if idx == history.NO_AWARD else entry_name(hist, idx, 18)
    if flags & 2:
        ip = '%d.%d' % (s[0] // 10, s[0] % 10)
        return (name, ip) + tuple('%d' % v for v in (s[1], s[2], s[3], s[5], s[6]))
    return (name,) + tuple('%d' % v for v in (s[0], s[1], s[2], s[3], s[5], s[6]))


def box_rows(hist, ms, box, teams, season, g):
    """BOX SCORE rows of game g of season: the visitor, then the home side. Each side is a
    team row (AB R H RBI BB SO), its batting rows, a PITCHING row (IP H R ER BB SO) and
    its pitching rows; box records of (season, g) in file order, at most BOX_RECS_MAX.
    One message row past the history table, without the game's kind 192 + g record or
    without any box record of it."""
    msg = [('NO BOX SCORE RECORDED',)]
    if season > history.SEASON_COUNT:
        return msg
    game = first_record(ms, season, SERIES_GAME_KIND + g)
    if game is None:
        return msg
    recs = [r for r in box if r[0] == season and r[1] == g][:BOX_RECS_MAX]
    if not recs:
        return msg
    v, h = game[0] >> 8, game[0] & 255
    names = dict(teams)
    out = []
    for t, tid in ((0, v), (1, h)):
        out.append((names.get(tid, 'TEAM %d' % tid), 'AB', 'R', 'H', 'RBI', 'BB', 'SO'))
        side = [r for r in recs if (r[2] & 1) == t]
        out += [box_line(hist, r) for r in side if not (r[2] & 2)]
        out.append(('PITCHING', 'IP', 'H', 'R', 'ER', 'BB', 'SO'))
        out += [box_line(hist, r) for r in side if r[2] & 2]
    return out


def box_body(state, data):
    """(cols, rows) of the BOX SCORE in state: game cat & 7 of the season cat >> 3 seasons
    back from the newest. A lone message row uses COLS_SINGLE; no history gives no rows."""
    hist = data['hist']
    if hist.seasons_recorded == 0:
        return COLS_SINGLE, []
    cat = state[2]
    rows = box_rows(hist, data['ms'], data['box'], data['teams'],
                    hist.seasons_recorded - (cat >> 3), cat & 7)
    if len(rows) == 1 and len(rows[0]) == 1:
        return COLS_SINGLE, rows
    return COLS_BOX, rows


def series_game(ms, season, g):
    """True when season has its WORLD SERIES game g (kind 192 + g record)."""
    return first_record(ms, season, SERIES_GAME_KIND + g) is not None


def pbox_rows(hist, box, teams, season, g):
    """PLAYOFF BOX rows of round game g of season: box_rows' layout for the records of
    (season, g) excluding the flags-4 header, at most BOX_RECS_MAX, the two teams from
    the header's idx. One message row without a flags-4 header record or without any
    other record of the game."""
    msg = [('NO BOX SCORE RECORDED',)]
    if season > history.SEASON_COUNT:
        return msg
    heads = [r for r in box if r[0] == season and r[1] == g and r[2] == 4
             and g >= 16][:1]
    if not heads:
        return msg
    recs = [r for r in box if r[0] == season and r[1] == g and r[2] != 4]
    recs = recs[:BOX_RECS_MAX]
    if not recs:
        return msg
    v, h = heads[0][3] >> 8, heads[0][3] & 255
    names = dict(teams)
    out = []
    for t, tid in ((0, v), (1, h)):
        out.append((names.get(tid, 'TEAM %d' % tid), 'AB', 'R', 'H', 'RBI', 'BB', 'SO'))
        side = [r for r in recs if (r[2] & 1) == t]
        out += [box_line(hist, r) for r in side if not (r[2] & 2)]
        out.append(('PITCHING', 'IP', 'H', 'R', 'ER', 'BB', 'SO'))
        out += [box_line(hist, r) for r in side if r[2] & 2]
    return out


def pbox_body(state, data):
    """(cols, rows) of the PLAYOFF BOX in state: round game cat & 63 + 16 of the season
    cat >> 6 seasons back from the newest. A lone message row uses COLS_SINGLE; no
    history gives no rows."""
    hist = data['hist']
    if hist.seasons_recorded == 0:
        return COLS_SINGLE, []
    cat = state[2]
    rows = pbox_rows(hist, data['box'], data['teams'],
                     hist.seasons_recorded - (cat >> 6), (cat & 63) + 16)
    if len(rows) == 1 and len(rows[0]) == 1:
        return COLS_SINGLE, rows
    return COLS_BOX, rows


# ---------------------------------------------------------------- offseason
def retire_entries(hist):
    """(index, entry) of the players who retired with the season just recorded (status
    2 or 3 with last_season == N), WAR10 descending then index ascending."""
    last = hist.seasons_recorded
    items = []
    for i in range(n_entries(hist)):
        e = hist.read_entry(i)
        if e['status'] in (history.STATUS_RETIRED, history.STATUS_HOF) \
                and e['last_season'] == last:
            items.append((-e['WAR10'], i, e))
    items.sort(key=lambda t: (t[0], t[1]))
    return [(i, e) for _w, i, e in items]


def new_hof_count(hist):
    """Entries inducted with the season just recorded (status 3, hof_season == N)."""
    last = hist.seasons_recorded
    n = 0
    for i in range(n_entries(hist)):
        e = hist.read_entry(i)
        if e['status'] == history.STATUS_HOF and e['hof_season'] == last:
            n += 1
    return n


def sign_split(events):
    """SIGN events in file order, split into draft picks [(team, name)] and free agent
    signings [(team, name, frm)]. A SIGN is a pick when an unconsumed DRAFT event has
    the same stem (ASCII upper case) as frm and the same name; it consumes the first
    such DRAFT in file order."""
    # unconsumed DRAFTs per (stem upper, name); equal keys are interchangeable, so a
    # count gives the same picks as taking the first one in file order
    open_drafts = Counter((ascii_upper(ev[1]), ev[2]) for ev in events if ev[0] == 'DRAFT')
    picks, fa = [], []
    for ev in events:
        if ev[0] != 'SIGN':
            continue
        _k, team, name, frm = ev
        key = (ascii_upper(frm), name)
        if open_drafts[key] > 0:
            open_drafts[key] -= 1
            picks.append((team, name))
        else:
            fa.append((team, name, frm))
    return picks, fa


def draft_managed(data, team):
    """True when a team token (latin-1) is managed (C17.2): a mapped stem of
    data['team_stems'] (the settings_teams walk, built once per data load) whose ASCII
    upper case equals the token's, and bit tid of the HISTORY mask is set (tid < 32)."""
    tid = data.get('team_stems', {}).get(ascii_upper(team))
    return tid is not None and tid < 32 and ((data['mask'] >> tid) & 1) != 0


def managed_cell(data, team, text):
    """TEAM column cell of a managed team (C17): '*' + the display text."""
    return ('*' if draft_managed(data, team) else '') + text


def ready_lines(data, launched):
    """The six counts and the closing line of phase 5 (uncapped totals)."""
    hist = data['hist']
    ev = data['events']
    picks, fa = sign_split(ev)
    return ['RETIRED: %d   NEW HALL OF FAME: %d' % (len(retire_entries(hist)),
                                                    new_hof_count(hist)),
            'ROOKIES DRAFTED: %d' % len(picks),
            'TRADES: %d' % sum(1 for e in ev if e[0] == 'TRADE'),
            'FREE AGENT SIGNINGS: %d' % len(fa),
            'PLAYERS RELEASED: %d' % sum(1 for e in ev if e[0] == 'REL'),
            'EVERY PLAYER AGED A YEAR AND DEVELOPED',
            (OFF_LAUNCH_TEXT % year_of(hist, hist.seasons_recorded + 1)) if launched
            else OFF_STAY_TEXT]


def offseason_body(state, data):
    """(cols, rows) of the offseason phase in state: every row, capped at LIST_MAX. A
    phase with nothing to show is one message row with COLS_SINGLE. With no history
    the body is empty (rows() then shows the NO DYNASTY row)."""
    hist = data['hist']
    if hist.seasons_recorded == 0:
        return COLS_SINGLE, []
    cat = state[2]
    phase = cat & 15
    ld = data.get('league_dir')
    ev = data['events']
    last = hist.seasons_recorded
    shown = {}                                # team token -> display, once per call

    def disp(stem):
        if stem not in shown:
            shown[stem] = team_disp(ld, stem)
        return shown[stem]

    if phase == OFF_REVIEW:
        return COLS_SINGLE, review_rows(hist, data['ms'], ld) or []
    if phase == OFF_READY:
        return COLS_SINGLE, [(s,) for s in ready_lines(data, cat >> 4)]
    if phase == OFF_RETIRE:
        cols, msg = COLS_RETIRE, 'NO RETIREMENTS'
        rows = [(name_display(e['name'], 18), '%d' % e['age'],
                 '%d' % e['seasons_played'], fmt_war10(e['WAR10']),
                 'HOF' if e['status'] == history.STATUS_HOF and e['hof_season'] == last
                 else '')
                for _i, e in retire_entries(hist)][:LIST_MAX]
    elif phase == OFF_DRAFT:
        cols, msg = COLS_DRAFT, 'NO DRAFT PICKS'
        picks, _fa = sign_split(ev)
        cache = {}                                # team token -> V20 bytes, once per build
        rows = [('#%d' % k, managed_cell(data, team, disp(team)),
                 draft_pos(ld, team, name, cache), name)
                for k, (team, name) in enumerate(picks[:LIST_MAX], 1)]
    elif phase == OFF_TRADES:
        cols, msg = COLS_MOVE, 'NO TRADES'
        rows = []
        for e in ev:
            if e[0] == 'TRADE':
                _k, a, x, b, y = e
                rows.append((managed_cell(data, a, disp(a)), x, disp(b)))
                rows.append((managed_cell(data, b, disp(b)), y, disp(a)))
        rows = rows[:LIST_MAX]
    elif phase == OFF_FA:
        cols, msg = COLS_MOVE, 'NO SIGNINGS OR RELEASES'
        _picks, fa = sign_split(ev)
        rows = [(managed_cell(data, team, disp(team)),
                 name, 'FREE AGENT' if ascii_upper(frm) == 'POOL' else disp(frm))
                for team, name, frm in fa[:LIST_MAX]]
        for e in ev:
            if e[0] == 'REL' and len(rows) < LIST_MAX:
                rows.append((managed_cell(data, e[1], disp(e[1])), e[2], 'RELEASED'))
        rows = rows[:LIST_MAX]
    if not rows:
        return COLS_SINGLE, [(msg,)]
    return cols, rows


# ---------------------------------------------------------------- state helpers (C13)
NO_CARD_TEXT = 'NO SEASON LINES RECORDED'
NO_RATINGS_TEXT = 'NO RATINGS RECORDED'


def pack(screen, page, cat, row=0, year=0):
    """The state tuple (screen, page, cat, row, year). Row and year are left out while they
    are 0, so the tuples of the screens without a cursor stay (screen, page, cat)."""
    if year:
        return (screen, page, cat, row, year)
    if row:
        return (screen, page, cat, row)
    return (screen, page, cat)


def unpack(state):
    """The five fields of a state tuple of 3 to 5 items; a missing row or year is 0."""
    t = tuple(state)
    return (t[0], t[1], t[2], t[3] if len(t) > 3 else 0, t[4] if len(t) > 4 else 0)


def cursor_screen(s):
    """True on the screens with a row cursor (C13.4): HALL OF FAME, LEADERS (every mode),
    SEASON AWARDS, the offseason RETIREMENTS phase and MILESTONES WATCH (C27, cat 1;
    the milestones mode 0 has none)."""
    if s[0] in (SCREEN_HOF, SCREEN_LEADERS, SCREEN_AWARDS):
        return True
    if s[0] == SCREEN_MILESTONES and s[2] == 1:
        return True
    return s[0] == SCREEN_OFFSEASON and (s[2] & 15) == OFF_RETIRE


def cursor_state(s, row):
    """s with the cursor on row; the page follows (page = row // ROWS_PER_PAGE)."""
    return pack(s[0], row // ROWS_PER_PAGE, s[2], row, s[4])


def cursor_move(state, s, key, data):
    """UP / DOWN move the cursor one row within the list; PGUP / PGDN move the page and put the
    cursor on its first row, only when the page changes. state comes back as it was when
    nothing moves."""
    page, row = s[1], s[3]
    n = total_rows(s, data)
    if key == KEY_UP and row > 0:
        row -= 1
    elif key == KEY_DOWN and row < n - 1:
        row += 1
    elif key == KEY_PGDN and page * ROWS_PER_PAGE + ROWS_PER_PAGE < n:
        row = (page + 1) * ROWS_PER_PAGE
    elif key == KEY_PGUP and page > 0:
        row = (page - 1) * ROWS_PER_PAGE
    else:
        return state
    return cursor_state(s, row)


def leader_cats(mode):
    """The category list of a LEADERS mode (C13.3, C39): CAREER = CATS, SEASON and
    BY YEAR = SEASON_CATS, POST = POST_CATS."""
    if mode == MODE_CAREER:
        return CATS
    if mode == MODE_POST:
        return POST_CATS
    return SEASON_CATS


def post_leader_totals(box):
    """{entry: (games, t)} of every entry with at least one BOXSCORE.DAT player row
    (C39), exactly post_totals(box, entry): one pass, entries >= POST_ENTRY_MAX
    ignored, games the distinct (season, g) pairs, t the 25-int TOTALS sums."""
    acc = {}
    games = {}
    for rec in box:
        if rec[3] >= POST_ENTRY_MAX or rec[2] == 4:          # idx overflow, or a header
            continue
        idx = rec[3]
        season, g, flags, stats = rec[0], rec[1], rec[2], rec[6]
        d = acc.get(idx)
        if d is None:
            d = acc[idx] = [0] * 25
            games[idx] = set()
        seen = games[idx]
        if (season, g) not in seen:
            seen.add((season, g))
        if flags & 2:
            d[19] += 3 * (stats[0] // 10) + stats[0] % 10
            d[20] += stats[3]
            d[23] += stats[6]
        else:
            d[1] += stats[0]
            d[2] += stats[2]
            d[7] += stats[3]
            d[5] += stats[4]
            d[10] += stats[7]
    return {idx: (len(games[idx]), [len(games[idx])] + t[1:])
            for idx, t in acc.items()}


def post_order(box, cat):
    """[(value, entry, games)] of the POSTSEASON leaders of cat (C39): value = t[index]
    (index 0 is G = games), only value > 0, sorted value descending then entry
    ascending, the first POST_MAX."""
    index = cat[2]
    items = []
    for entry, (games, t) in post_leader_totals(box).items():
        value = games if index == 0 else t[index]
        if value > 0:
            items.append((value, entry, games))
    items.sort(key=lambda it: (-it[0], it[1]))
    return items[:POST_MAX]


def default_year(data):
    """The BY YEAR season used when none is selected: the newest season with lines, else the
    newest season recorded (0 with no history)."""
    seasons = line_seasons(data['lines'])
    return seasons[-1] if seasons else data['hist'].seasons_recorded


def leaders_year(s, data):
    """The BY YEAR season of s: its year field, or the default season when that is 0."""
    return s[4] or default_year(data)


def season_items(s, data):
    """season_order over the lines of the SEASON mode (every line) or of the BY YEAR season."""
    mode, idx = s[2] >> 5, s[2] & 31
    season = leaders_year(s, data) if mode == MODE_BYYEAR else None
    return season_order(data['lines'], SEASON_CATS[idx], season)


def leaders_body(state, data):
    """(cols, rows) of LEADERS, every row (the caller pages them). CAREER: the career leader
    cells. SEASON and BY YEAR: TEAM from the MAJ abbreviations, the YEAR column blank in BY
    YEAR; a season mode with no line (of the season) shows NO_LINES_TEXT as one message row."""
    s = unpack(state)
    hist = data['hist']
    mode, idx = s[2] >> 5, s[2] & 31
    if mode == MODE_CAREER:
        return COLS_LEADERS, career_leader_cells(hist, idx)
    if mode == MODE_POST:
        items = post_order(data['box'], POST_CATS[idx])
        if not items:
            return COLS_SINGLE, [(NO_POST_TEXT,)]
        out = []
        for k, (val, entry, games) in enumerate(items, 1):
            status = hist.read_entry(entry)['status']
            mark = 'R' if status == history.STATUS_RETIRED \
                else ('H' if status == history.STATUS_HOF else ' ')
            out.append(('#%d' % k, entry_name(hist, entry, 16), mark, '%d' % games,
                        cat_format(POST_CATS[idx], val)))
        return COLS_POST_LEADERS, out
    season = leaders_year(s, data) if mode == MODE_BYYEAR else None
    if not any(season is None or ln['season'] == season for ln in data['lines']):
        return COLS_SINGLE, [(NO_LINES_TEXT,)]
    cat = SEASON_CATS[idx]
    out = []
    for k, (val, _season, entry, ln) in enumerate(season_items(s, data), 1):
        year = '' if mode == MODE_BYYEAR else year_text(hist, ln['season'])
        out.append(('#%d' % k, entry_name(hist, entry, 16), year,
                    data['abbrs'].get(ln['team'], '?'), cat_format(cat, val)))
    return COLS_SEASON_LEADERS, out


def row_entry(s, data):
    """The player entry named by the cursor row of s (C13.4), or None: a message row, an award
    with no player, an empty list, or no history."""
    hist = data['hist']
    if hist.seasons_recorded == 0:
        return None
    row = s[3]
    if s[0] == SCREEN_HOF:
        order = hof_order(hist)
        return order[row][0] if row < len(order) else None
    if s[0] == SCREEN_LEADERS:
        if s[2] >> 5 == MODE_CAREER:
            cands = career_order(hist, s[2] & 31)
            return cands[row][1] if row < len(cands) else None
        if s[2] >> 5 == MODE_POST:
            items = post_order(data['box'], POST_CATS[s[2] & 31])
            return items[row][1] if row < len(items) else None
        items = season_items(s, data)
        return items[row][2] if row < len(items) else None
    if s[0] == SCREEN_AWARDS:
        items = awards_items(hist, data['ms'], hist.seasons_recorded - s[2])
        return award_entry(hist, items[row][1]) if row < len(items) else None
    if s[0] == SCREEN_MILESTONES and s[2] == 1:
        items = watch_items(hist)
        return items[row][3] if row < len(items) else None
    if s[0] == SCREEN_OFFSEASON:
        ret = retire_entries(hist)
        return ret[row][0] if row < len(ret) else None
    return None


def open_card(s, entry, data):
    """(PLAYER CARD state, 0) for entry. The list state s is kept in data (one level, C13.5) so
    ESC returns to it exactly."""
    data['card_back'] = pack(s[0], s[1], s[2], s[3], s[4])
    return (SCREEN_CARD, 0, entry), 0


def card_lines(s, data):
    """The SEASLINE lines of the card's entry (s[2]) in season order, the latest last (C13.5)."""
    return sorted((ln for ln in data['lines'] if ln['entry'] == s[2]),
                  key=lambda ln: ln['season'])


def pos_name(p):
    return POS_NAMES[p] if 0 <= p < len(POS_NAMES) else '?'


def card_name(e):
    """The player's name, first then last, upper case (C13.5)."""
    first = one_field(e['name'][12:20])
    last = one_field(e['name'][0:12])
    return ascii_upper(' '.join(p for p in (first, last) if p)) or '?'


def card_cells(t, war10, pitcher, first, team):
    """One PLAYER CARD season row from the stats t (TOTALS order): the batter columns, or the
    pitcher columns when pitcher."""
    if pitcher:
        return (first, team, '%d' % t[0], '%d' % t[13], '%d' % t[14], '%d' % t[15],
                fmt_ip(t[19]), '%d' % t[23], fmt_era100(era100_of(t)), fmt_war10(war10))
    return (first, team, '%d' % t[0], '%d' % t[1], '%d' % t[2], '%d' % t[5],
            '%d' % t[7], '%d' % t[10], fmt_avg(avg_of(t)), fmt_war10(war10))


def post_totals(box, entry):
    """The postseason totals of entry from the BOXSCORE.DAT player rows (C26): WS and C23b
    round games, the records with idx == entry and flags != 4 (a flags 4 record is a round
    header, not a player row), None when there is none. Batting rows (bit1 clear) sum
    AB H RBI HR SB; pitching rows OUTS (IP10 = whole innings * 10 + thirds), ER and PSO.
    Returns (games, t): games the number of distinct (season, g) pairs, t a 25-int
    TOTALS-order list with G = games and the sums above, every other field 0."""
    t, games = None, set()
    for season, g, flags, idx, _b, _i, st in box:
        if idx != entry or flags == 4:
            continue
        if t is None:
            t = [0] * 25
        games.add((season, g))
        if flags & 2:
            t[19] += 3 * (st[0] // 10) + st[0] % 10
            t[20] += st[3]
            t[23] += st[6]
        else:
            t[1] += st[0]
            t[2] += st[2]
            t[7] += st[3]
            t[5] += st[4]
            t[10] += st[7]
    if t is None:
        return None
    t[0] = len(games)
    return t[0], t


def card_rows(s, data):
    """Season rows per page of the PLAYER CARD (C26): 6 when the entry has a POSTSEASON row,
    else CARD_SEASON_ROWS (7)."""
    return 6 if post_totals(data['box'], s[2]) is not None else CARD_SEASON_ROWS


def card_table(s, data):
    """(season rows of the page, CAREER row, POST row or None) of the PLAYER CARD (C13.5,
    C26): the entry's lines newest first, card_rows to a page; one NO_CARD_TEXT row with no
    lines. CAREER is the entry's totals, not the sum of the lines. POST the postseason
    totals of the entry (post_totals): card_cells with 'POSTSEASON' as the label and '-'
    for WAR (and W, L, SV for a pitcher)."""
    hist = data['hist']
    if not 0 <= s[2] < n_entries(hist):
        return [(NO_CARD_TEXT,)], ('CAREER',), None
    e = hist.read_entry(s[2])
    lines = card_lines(s, data)
    post = post_totals(data['box'], s[2])
    if not lines:
        season = [(NO_CARD_TEXT,)]
    else:
        per = card_rows(s, data)
        newest = lines[::-1][s[1] * per:(s[1] + 1) * per]
        season = [card_cells(ln['totals'], ln['WAR10'], e['pitcher'],
                             year_text(hist, ln['season']),
                             data['abbrs'].get(ln['team'], '?')) for ln in newest]
    career = card_cells(e['totals'], e['WAR10'], e['pitcher'], 'CAREER', '')
    if post is None:
        return season, career, None
    cells = list(card_cells(post[1], 0, e['pitcher'], 'POSTSEASON', ''))
    cells[9] = '-'
    if e['pitcher']:
        cells[3] = cells[4] = cells[5] = '-'
    return season, career, tuple(cells)


def card_info(s, data):
    """(the five info lines (C13.5), the latest SEASLINE line or None) of the PLAYER CARD."""
    hist = data['hist']
    if not 0 <= s[2] < n_entries(hist):
        return ['?', '', '', NO_RATINGS_TEXT, ''], None
    e = hist.read_entry(s[2])
    lines = card_lines(s, data)
    last = lines[-1] if lines else None
    if last is None:
        head = pos_name(e['pos1'])
    else:
        hand = last['hand']
        head = '%s  BATS %s  THROWS %s' % (pos_name(last['pos1']), BATS_NAMES[(hand >> 1) & 3],
                                           'R' if hand & 8 else 'L')
    st = e['status']
    if st == history.STATUS_ACTIVE:
        status = 'ACTIVE, AGE %d' % (e['age'] + 1)
    elif st == history.STATUS_RETIRED:
        status = 'RETIRED %d' % year_of(hist, e['last_season'])
    elif st == history.STATUS_HOF:
        status = 'HALL OF FAME %d' % year_of(hist, e['hof_season'])
    else:
        status = ''
    span = '%d-%d  %d SEASONS' % (year_of(hist, e['first_season']),
                                  year_of(hist, e['last_season']), e['seasons_played'])
    if last is None:
        r4, r5 = NO_RATINGS_TEXT, ''
    elif e['pitcher']:
        r = last['ratings']
        r4, r5 = 'CTL %d  VEL %d  END %d' % (r[6], r[7], r[8]), ''
    else:
        r = last['ratings']
        r4 = 'POW %d  H&R %d  SPD %d' % (r[0], r[2], r[3])
        r5 = 'RNG %d  ARM %d  BUNT %d' % (r[4], r[5], r[1])
    return [head, status, span, r4, r5], last


def card_title(s, data):
    hist = data['hist']
    if not 0 <= s[2] < n_entries(hist):
        return '?'
    return card_name(hist.read_entry(s[2]))


# ---------------------------------------------------------------- state machine
def leaders_count(hist, cat_index):
    """Number of qualifying candidates (paging bound), not the on-screen 12."""
    cat = CATS[cat_index]
    n = 0
    for i in range(n_entries(hist)):
        if cat_qualifies(hist.read_entry(i), cat):
            n += 1
    return min(n, LIST_MAX)


def total_rows(state, data):
    hist = data['hist']
    s = unpack(state)
    screen = s[0]
    if screen == SCREEN_HISTORY:
        n = history_rows(hist) if hist.seasons_recorded else []
    elif screen == SCREEN_HOF:
        n = hof_rows(hist) if hist.seasons_recorded else []
    elif screen == SCREEN_LEADERS:
        n = leaders_body(s, data)[1]
    elif screen == SCREEN_MILESTONES:
        if hist.seasons_recorded:
            n = watch_items(hist) if s[2] == 1 else milestone_rows(hist, data['ms'])
        else:
            n = []
    elif screen == SCREEN_REVIEW:
        n = review_rows(hist, data['ms']) or []
    elif screen == SCREEN_OFFSEASON:
        n = offseason_body(s, data)[1]
    elif screen == SCREEN_AWARDS:
        n = awards_body(s, data)[1]
    elif screen == SCREEN_STANDINGS:
        n = standings_body(s, data)[1]
    elif screen == SCREEN_SERIES:
        n = series_body(s, data)[1]
    elif screen == SCREEN_BOX:
        n = box_body(s, data)[1]
    elif screen == SCREEN_PLAYOFFS:
        n = playoffs_body(s, data)[1]
    elif screen == SCREEN_PBOX:
        n = pbox_body(s, data)[1]
    elif screen == SCREEN_SETTINGS:
        n = settings_rows(data)
    elif screen == SCREEN_ABOUT:
        n = ABOUT_ROWS
    elif screen == SCREEN_CARD:
        n = card_lines(s, data)
    else:
        n = MENU_ROWS
    return len(n)


def rows(state, data):
    """Model rows of the current page as cell tuples (no fonts needed). On the PLAYER CARD:
    the page's season rows, then the CAREER row (see card_table)."""
    hist = data['hist']
    s = unpack(state)
    screen, page, cat = s[0], s[1], s[2]
    if screen == SCREEN_CARD:
        season, career, post = card_table(s, data)
        out = season + [career]
        if post is not None:
            out.append(post)
        return out
    if screen == SCREEN_SETTINGS:
        return settings_rows(data)[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
    if screen == SCREEN_ABOUT:
        return [(t,) for t in ABOUT_ROWS[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]]
    if screen == SCREEN_MENU:
        if (hist is None or hist.seasons_recorded == 0) and cat >> 4:
            return [(t,) for t in TITLE_ROWS]
        return [(t,) for t in MENU_ROWS]
    if hist is None or hist.seasons_recorded == 0:
        return [('NO DYNASTY HISTORY YET',)]
    if screen == SCREEN_LEADERS:
        return leaders_body(s, data)[1][page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
    if screen == SCREEN_OFFSEASON:
        body = offseason_body(state, data)[1]
        return body[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
    if screen == SCREEN_AWARDS:
        body = awards_body(state, data)[1]
        return body[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
    if screen == SCREEN_STANDINGS:
        body = standings_body(state, data)[1]
        return body[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
    if screen == SCREEN_SERIES:
        body = series_body(state, data)[1]
        return body[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
    if screen == SCREEN_BOX:
        body = box_body(state, data)[1]
        return body[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
    if screen == SCREEN_PLAYOFFS:
        body = playoffs_body(state, data)[1]
        return body[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
    if screen == SCREEN_PBOX:
        body = pbox_body(state, data)[1]
        return body[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
    if screen == SCREEN_HISTORY:
        all_rows = history_rows(hist, data.get('league_dir'), data.get('team_stems'),
                                data['mask'])
    elif screen == SCREEN_HOF:
        all_rows = hof_rows(hist)
    elif screen == SCREEN_MILESTONES:
        if cat != 1:
            all_rows = milestone_rows(hist, data['ms'])
        else:
            all_rows = watch_rows(hist)
    else:
        all_rows = review_rows(hist, data['ms'], data.get('league_dir'))
        if all_rows is None:
            return []
    return all_rows[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]


def step(state, key, data):
    """(state, exit_flag). The state is (screen, page, cat, row, year), see pack: row is the
    cursor (C13.4, the absolute row index on HALL OF FAME, LEADERS, SEASON AWARDS and the
    offseason RETIREMENTS phase; page = row // 12 there), year the BY YEAR season (C13.3).
    LEADERS: cat = mode * 32 + category, mode 0 CAREER, 1 SEASON, 2 BY YEAR; TAB (9) cycles
    the mode, keeping the category by label; in BY YEAR '-' steps to the older season with
    lines, '+' or '=' to the newer, nothing past either end. PLAYER CARD (13): cat = the entry
    index, page = the season table page of 7 rows; ESC returns to data['card_back'], the list
    state it was opened from. ESC exits from MENU; from any other screen it goes back
    to MENU. PGUP/PGDN page by 12 (on a cursor screen the cursor goes to the new page's first
    row when the page changes); UP/DOWN move the cursor; ENTER on a cursor row whose row
    names a player entry opens the PLAYER CARD (the offseason RETIREMENTS phase: C or c).
    LEFT/RIGHT cycle the LEADERS category or step the SEASON AWARDS, SEASON STANDINGS or
    WORLD SERIES season. ENTER on REVIEW goes to MENU. ENTER walks the offseason phases;
    past the last one it exits when the offseason was launched (cat >> 4) and goes to MENU
    otherwise. ENTER on the /TITLE menu (cat >> 4) exits. Key 0 on the hub opens SEASON STANDINGS, W or w
    WORLD SERIES. On WORLD SERIES keys 1..7 open the BOX SCORE of that game; ESC there
    goes back to the series, LEFT and RIGHT step between the season's games.
    SETTINGS: cat is the cursor, 0 ERA RULES, 1 PLAYOFF FORMAT, 2 START YEAR (LEFT RIGHT
    -1 +1, '-' -10, '+' or '=' +10), c >= 3 the team c - 3."""
    s = unpack(state)
    screen, page, cat = s[0], s[1], s[2]
    if key == KEY_ESC:
        if screen == SCREEN_MENU:
            return (SCREEN_MENU, 0, 0), 1
        if screen == SCREEN_BOX:
            return (SCREEN_SERIES, 0, cat >> 3), 0
        if screen == SCREEN_PBOX:
            return (SCREEN_PLAYOFFS, 0, cat >> 6), 0
        if screen == SCREEN_CARD:
            return data.get('card_back', (SCREEN_MENU, 0, 0)), 0
        return (SCREEN_MENU, 0, 0), 0
    if screen == SCREEN_MENU:
        if key == 48:
            return (SCREEN_STANDINGS, 0, 0), 0
        if 49 <= key <= 57:
            return (key - 48, 0, 0), 0
        if key in (87, 119):
            return (SCREEN_SERIES, 0, 0), 0
        if key in (80, 112):
            return (SCREEN_PLAYOFFS, 0, 0), 0
        if key == KEY_ENTER and cat >> 4:
            return state, 1
        return state, 0
    if screen == SCREEN_REVIEW and key == KEY_ENTER:
        return (SCREEN_MENU, 0, 0), 0
    if screen == SCREEN_OFFSEASON and key == KEY_ENTER:
        if (cat & 15) < OFF_READY and data['hist'].seasons_recorded > 0:
            return (SCREEN_OFFSEASON, 0, cat + 1), 0
        if cat >> 4:
            return state, 1
        return (SCREEN_MENU, 0, 0), 0
    if screen == SCREEN_OFFSEASON and key in KEY_CARD and (cat & 15) == OFF_RETIRE:
        # C opens the PLAYER CARD of the highlighted retiree (C13.4); ENTER keeps the walk
        entry = row_entry(s, data)
        if entry is not None:
            return open_card(s, entry, data)
    if screen == SCREEN_SETTINGS:
        # cat is the cursor: 0 the ERA RULES row, 1 the PLAYOFF FORMAT row, 2 the START YEAR
        # row (C13.1), c >= 3 the team teams[c - 3]
        n = len(settings_rows(data))
        if cat == SET_START and key in START_STEPS:
            start_year_step(data, START_STEPS[key])
            return state, 0
        if key == KEY_ENTER:
            if cat == SET_START:
                return state, 0
            if cat == 1:
                set_playoff_format(data['league_dir'], data['fmt'][0])
                data['teams'] = settings_teams(data['league_dir'])
            else:
                if cat == 0:
                    data['era'] = era_next(data['era'])
                else:
                    data['mask'] ^= 1 << data['teams'][cat - 3][0]
                save_settings(data['league_dir'], data['era'], data['mask'])
            data['fmt'] = realign.wanted_for_dir(data['league_dir'])
            return state, 0
        if key == KEY_UP and cat > 0:
            cat -= 1
        elif key == KEY_DOWN and cat < n - 1:
            cat += 1
        elif key == KEY_PGDN:
            cat = min(cat + ROWS_PER_PAGE, n - 1)
        elif key == KEY_PGUP:
            cat = max(cat - ROWS_PER_PAGE, 0)
        else:
            return state, 0
        return (SCREEN_SETTINGS, cat // ROWS_PER_PAGE, cat), 0
    if screen == SCREEN_CARD:
        # PGUP/PGDN page the season table, card_rows lines a page (C13.5, C26: 6 with a
        # POST row, else CARD_SEASON_ROWS)
        per = card_rows(s, data)
        n = len(card_lines(s, data))
        if key == KEY_PGDN and (page + 1) * per < n:
            return (SCREEN_CARD, page + 1, cat), 0
        if key == KEY_PGUP and page > 0:
            return (SCREEN_CARD, page - 1, cat), 0
        return state, 0
    if cursor_screen(s) and key in CURSOR_KEYS:
        return cursor_move(state, s, key, data), 0
    if cursor_screen(s) and key == KEY_ENTER:
        entry = row_entry(s, data)
        if entry is not None:
            return open_card(s, entry, data)
        return state, 0
    if screen == SCREEN_SERIES and 49 <= key <= 55:
        # game key - 49 of the season (cat seasons back), when the season is 1..64 and has it
        g = key - 49
        season = data['hist'].seasons_recorded - cat
        if 1 <= season <= history.SEASON_COUNT and series_game(data['ms'], season, g):
            return (SCREEN_BOX, 0, cat * 8 + g), 0
        return state, 0
    if screen == SCREEN_BOX and key in (KEY_LEFT, KEY_RIGHT):
        # to the previous (LEFT) or next (RIGHT) game of the season that has a record
        bcat, g = cat >> 3, cat & 7
        season = data['hist'].seasons_recorded - bcat
        have = [k for k in range(SERIES_GAMES) if series_game(data['ms'], season, k)]
        if key == KEY_LEFT:
            to = [k for k in have if k < g][-1:]
        else:
            to = [k for k in have if k > g][:1]
        if to:
            return (SCREEN_BOX, 0, bcat * 8 + to[0]), 0
        if key == KEY_LEFT and have and g == have[0] \
                and 1 <= season <= history.SEASON_COUNT:
            # LEFT on the season's first WS game with a record, when the season has
            # round games: the last round game's PLAYOFF BOX
            games = playoff_games(data['box'], season)
            if games:
                return (SCREEN_PBOX, 0, bcat * 64 + games[-1][0] - 16), 0
        return state, 0
    if screen == SCREEN_PBOX and key in (KEY_LEFT, KEY_RIGHT):
        # to the previous (LEFT) or next (RIGHT) round game of the season (by g); RIGHT
        # past the last opens the first WORLD SERIES box of the season that has one
        bcat, g = cat >> 6, (cat & 63) + 16
        season = data['hist'].seasons_recorded - bcat
        games = playoff_games(data['box'], season)
        if key == KEY_LEFT:
            to = [q for q in games if q[0] < g][-1:]
        else:
            to = [q for q in games if q[0] > g][:1]
        if to:
            return (SCREEN_PBOX, 0, bcat * 64 + to[0][0] - 16), 0
        if key == KEY_RIGHT:
            have = [k for k in range(SERIES_GAMES) if series_game(data['ms'], season, k)]
            if have:
                return (SCREEN_BOX, 0, bcat * 8 + have[0]), 0
        return state, 0
    if screen == SCREEN_PLAYOFFS and key == KEY_ENTER:
        # the box of the first game whose GAME row is on the current page (the season's
        # first round game when none is), when the season has one. The GAME rows come in
        # the games' order, so the nth GAME row of the season is the nth playoff game.
        season = data['hist'].seasons_recorded - cat
        games = playoff_games(data['box'], season)
        if not games:
            return state, 0
        all_rows = playoffs_body((SCREEN_PLAYOFFS, 0, cat), data)[1]
        lo = page * ROWS_PER_PAGE
        seen = 0
        for r in all_rows[:lo]:
            if r[0].startswith('GAME '):
                seen += 1
        choose = games[0][0]
        for r in all_rows[lo:lo + ROWS_PER_PAGE]:
            if r[0].startswith('GAME '):
                if seen < len(games):
                    choose = games[seen][0]
                break
        return (SCREEN_PBOX, 0, cat * 64 + choose - 16), 0
    if key == KEY_PGDN:
        n = total_rows(state, data)
        if page * ROWS_PER_PAGE + ROWS_PER_PAGE < n:
            page += 1
        return (screen, page, cat), 0
    if key == KEY_PGUP:
        if page > 0:
            page -= 1
        return (screen, page, cat), 0
    if screen == SCREEN_LEADERS and key in (KEY_LEFT, KEY_RIGHT):
        d = -1 if key == KEY_LEFT else 1
        mode, idx = cat >> 5, cat & 31
        # BY YEAR keeps its season (s[4]) while the category changes
        return pack(SCREEN_LEADERS, 0, mode * MODE_SHIFT + (idx + d) % len(leader_cats(mode)),
                    0, s[4]), 0
    if screen == SCREEN_LEADERS and key == KEY_TAB:
        # the mode cycles CAREER -> SEASON -> BY YEAR -> POSTSEASON; the category stays
        # when the new mode has it (by label), else the first
        mode, idx = cat >> 5, cat & 31
        new = (mode + 1) % 4
        label = leader_cats(mode)[idx][0]
        labels = [c[0] for c in leader_cats(new)]
        year = default_year(data) if new == MODE_BYYEAR else 0
        return pack(SCREEN_LEADERS, 0, new * MODE_SHIFT + (labels.index(label)
                                                           if label in labels else 0),
                    0, year), 0
    if screen == SCREEN_LEADERS and cat >> 5 == MODE_BYYEAR and key in YEAR_KEYS:
        # '-' steps to the older season with lines, '+' or '=' to the newer; nothing past the ends
        seasons = line_seasons(data['lines'])
        cur = leaders_year(s, data)
        if key == KEY_MINUS:
            older = [x for x in seasons if x < cur]
            if not older:
                return state, 0
            return pack(SCREEN_LEADERS, 0, cat, 0, older[-1]), 0
        newer = [x for x in seasons if x > cur]
        if not newer:
            return state, 0
        return pack(SCREEN_LEADERS, 0, cat, 0, newer[0]), 0
    if screen == SCREEN_MILESTONES and key in (KEY_LEFT, KEY_RIGHT):
        # C27: the mode toggles (cat 0 milestones, cat 1 WATCH); page and row reset
        return (SCREEN_MILESTONES, 0, 0 if cat == 1 else 1), 0
    if screen in (SCREEN_AWARDS, SCREEN_STANDINGS, SCREEN_SERIES, SCREEN_PLAYOFFS) \
            and key in (KEY_LEFT, KEY_RIGHT):
        # LEFT goes back a season while one is left (shown season > 1), RIGHT forward
        if key == KEY_LEFT and data['hist'].seasons_recorded - cat > 1:
            return (screen, 0, cat + 1), 0
        if key == KEY_RIGHT and cat > 0:
            return (screen, 0, cat - 1), 0
    return state, 0


# ---------------------------------------------------------------- rendering
# columns: (header, x, width_chars, align). Every MAIN.FNT glyph advances CHAR_W, so a
# row holds 42 chars from x 10; x = 10 + CHAR_W * char_pos; right-aligned widths
# include one leading separator char.
CHAR_W = 7


def _cx(pos):
    return 10 + CHAR_W * pos


COLS_SINGLE = [(' ', _cx(0), 42, 'L')]
COLS_HISTORY = [('YEAR', _cx(0), 4, 'L'), ('CHAMPION', _cx(5), 13, 'L'),
                ('AL MVP', _cx(19), 11, 'L'), ('NL MVP', _cx(31), 11, 'L')]
COLS_HOF = [('NAME', _cx(0), 12, 'L'), ('IND', _cx(12), 4, 'R'), ('YRS', _cx(16), 4, 'R'),
            ('H/W', _cx(20), 5, 'R'), ('HR/K', _cx(25), 5, 'R'),
            ('AV/ER', _cx(30), 6, 'R'), ('WAR', _cx(36), 6, 'R')]
COLS_LEADERS = [('#', _cx(0), 5, 'L'), ('NAME', _cx(5), 16, 'L'), (' ', _cx(22), 1, 'L'),
                ('YRS', _cx(23), 5, 'R'), ('VALUE', _cx(28), 14, 'R')]
COLS_MILESTONES = [('YEAR', _cx(0), 4, 'L'), ('NAME', _cx(5), 16, 'L'),
                   ('EVENT', _cx(22), 20, 'L')]
# WATCH (C27)
COLS_WATCH = [('NAME', _cx(0), 16, 'L'), ('MARK', _cx(17), 9, 'L'),
              ('NOW', _cx(27), 6, 'R'), ('NEED', _cx(35), 6, 'R')]
COLS_RETIRE = [('NAME', _cx(0), 18, 'L'), ('AGE', _cx(18), 5, 'R'), ('YRS', _cx(23), 5, 'R'),
               ('WAR', _cx(28), 7, 'R'), ('HOF', _cx(36), 6, 'R')]
COLS_DRAFT = [('#', _cx(0), 4, 'L'), ('TEAM', _cx(4), 13, 'L'), ('POS', _cx(18), 3, 'L'),
              ('PLAYER', _cx(22), 20, 'L')]
COLS_MOVE = [('TEAM', _cx(0), 13, 'L'), ('PLAYER', _cx(14), 15, 'L'), ('FROM', _cx(30), 12, 'L')]
COLS_AWARDS = [('AWARD', _cx(0), 13, 'L'), ('NAME', _cx(14), 16, 'L'),
               ('VALUE', _cx(30), 12, 'R')]
COLS_STANDINGS = [('TEAM', _cx(0), 17, 'L'), ('W', _cx(17), 5, 'R'),
                  ('L', _cx(22), 5, 'R'), ('PCT', _cx(27), 6, 'R'),
                  ('GB', _cx(33), 6, 'R'), (' ', _cx(39), 3, 'R')]
COLS_SERIES = [('TEAM', _cx(0), 17, 'L'), ('R', _cx(17), 5, 'R'), ('H', _cx(22), 5, 'R'),
               ('E', _cx(27), 5, 'R'), (' ', _cx(32), 10, 'R')]
COLS_BOX = [(' ', _cx(0), 18, 'L')] + [(' ', _cx(18 + 4 * k), 4, 'R') for k in range(6)]
COLS_SETTINGS = [('SETTING', _cx(0), 24, 'L'), ('VALUE', _cx(26), 16, 'L')]
COLS_SEASON_LEADERS = [('#', _cx(0), 4, 'L'), ('NAME', _cx(4), 16, 'L'),
                       ('YEAR', _cx(20), 5, 'R'), ('TEAM', _cx(25), 4, 'R'),
                       ('VALUE', _cx(29), 12, 'R')]
# POSTSEASON LEADERS (C39): the same shape as the career table
COLS_POST_LEADERS = [('#', _cx(0), 5, 'L'), ('NAME', _cx(5), 16, 'L'), (' ', _cx(22), 1, 'L'),
                     ('G', _cx(23), 5, 'R'), ('VALUE', _cx(28), 14, 'R')]
# PLAYER CARD season table (C13.5): batters and pitchers; the widths run on from x 10
COLS_CARD_BAT = [('YEAR', _cx(0), 4, 'L'), ('TM', _cx(4), 4, 'R'), ('G', _cx(8), 4, 'R'),
                 ('AB', _cx(12), 5, 'R'), ('H', _cx(17), 4, 'R'), ('HR', _cx(21), 4, 'R'),
                 ('RBI', _cx(25), 4, 'R'), ('SB', _cx(29), 4, 'R'), ('AVG', _cx(33), 5, 'R'),
                 ('WAR', _cx(38), 5, 'R')]
COLS_CARD_PIT = [('YEAR', _cx(0), 4, 'L'), ('TM', _cx(4), 4, 'R'), ('G', _cx(8), 4, 'R'),
                 ('W', _cx(12), 3, 'R'), ('L', _cx(15), 3, 'R'), ('SV', _cx(18), 4, 'R'),
                 ('IP', _cx(22), 6, 'R'), ('SO', _cx(28), 4, 'R'), ('ERA', _cx(32), 5, 'R'),
                 ('WAR', _cx(37), 5, 'R')]
OFF_COLS = [COLS_SINGLE, COLS_RETIRE, COLS_DRAFT, COLS_MOVE, COLS_MOVE, COLS_SINGLE]

FOOTERS = {SCREEN_MENU: '0-9 W SELECT   ESC EXIT',
           SCREEN_HISTORY: 'PGUP PGDN   ESC MENU',
           SCREEN_HOF: 'PGUP PGDN   ESC MENU',
           SCREEN_LEADERS: 'LEFT RIGHT STAT  TAB MODE  ENTER CARD',
           SCREEN_CARD: 'PGUP PGDN SEASONS   ESC BACK',
           SCREEN_MILESTONES: 'LEFT RIGHT WATCH   PGUP PGDN   ESC MENU',
           SCREEN_REVIEW: 'ENTER MENU   ESC MENU',
           SCREEN_SETTINGS: 'UP DOWN MOVE   ENTER CHANGE   ESC MENU',
           SCREEN_ABOUT: 'PGUP PGDN   ESC MENU',
           SCREEN_AWARDS: 'LEFT RIGHT SEASON   PGUP PGDN   ESC MENU',
           SCREEN_STANDINGS: 'LEFT RIGHT SEASON   PGUP PGDN   ESC MENU',
           SCREEN_SERIES: '1-7 BOX  LEFT RIGHT SEASON  PGUP PGDN  ESC',
           SCREEN_BOX: 'LEFT RIGHT GAME   PGUP PGDN   ESC SERIES',
           SCREEN_PLAYOFFS: 'ENTER BOX  LEFT RIGHT SEASON  PGUP PGDN  ESC',
           SCREEN_PBOX: 'LEFT RIGHT GAME   PGUP PGDN   ESC PLAYOFFS'}


TITLE_FOOTER = '0-9 W SELECT   ENTER PLAY BALL'
TITLE_FOOTER_NEW = 'ENTER PLAY BALL'


def footer_text(state, data=None):
    """Footer line of state; the offseason's ENTER label follows its phase, the /TITLE
    menu's follows whether any season is recorded, MILESTONES WATCH its mode (C27)."""
    s = unpack(state)
    screen, cat = s[0], s[2]
    if screen == SCREEN_MILESTONES and cat == 1:
        return 'ENTER CARD  LEFT RIGHT MODE  PGUP PGDN  ESC'
    if screen == SCREEN_LEADERS and cat >> 5 == MODE_BYYEAR:
        return 'LEFT RIGHT STAT  - + YEAR  TAB MODE'
    if screen == SCREEN_MENU and cat >> 4:
        hist = data['hist'] if data else None
        if hist is None or hist.seasons_recorded == 0:
            return TITLE_FOOTER_NEW
        return TITLE_FOOTER
    if screen == SCREEN_OFFSEASON:
        if (cat & 15) < OFF_READY:
            return 'ENTER NEXT   PGUP PGDN   ESC MENU'
        return 'ENTER CONTINUE   ESC MENU' if cat >> 4 else 'ENTER MENU   ESC MENU'
    return FOOTERS[screen]


def screen_title(state, data):
    s = unpack(state)
    screen, page, cat = s[0], s[1], s[2]
    hist = data['hist']
    if screen == SCREEN_MENU:
        if cat >> 4:
            return 'DYNASTY MODE: %d' % year_of(hist, hist.seasons_recorded + 1)
        return 'DYNASTY'
    if screen == SCREEN_HISTORY:
        return 'SEASON HISTORY'
    if screen == SCREEN_HOF:
        return 'HALL OF FAME'
    if screen == SCREEN_LEADERS:
        mode = cat >> 5
        label = leader_cats(mode)[cat & 31][0]
        if mode == MODE_CAREER:
            return 'CAREER LEADERS: ' + label
        if mode == MODE_SEASON:
            return 'SEASON LEADERS: ' + label
        if mode == MODE_POST:
            return 'POSTSEASON LEADERS: ' + label
        return '%d LEADERS: %s' % (year_of(hist, leaders_year(s, data)), label)
    if screen == SCREEN_CARD:
        return card_title(s, data)
    if screen == SCREEN_MILESTONES:
        return 'MILESTONE WATCH' if cat == 1 else 'MILESTONES'
    if screen == SCREEN_OFFSEASON:
        n = data['hist'].seasons_recorded
        phase = cat & 15
        if phase == OFF_REVIEW:
            return OFF_TITLES[OFF_REVIEW] % year_of(hist, n)
        if phase == OFF_READY:
            return OFF_TITLES[OFF_READY] % year_of(hist, n + 1)
        return OFF_TITLES[phase]
    if screen == SCREEN_SETTINGS:
        return 'DYNASTY SETTINGS'
    if screen == SCREEN_ABOUT:
        return 'ABOUT THE MODS %d/%d' % (page + 1, (len(ABOUT_ROWS) + ROWS_PER_PAGE - 1)
                                         // ROWS_PER_PAGE)
    n = data['hist'].seasons_recorded
    # A league with no recorded season has no season number to show (it would read SEASON 0).
    if screen == SCREEN_BOX:
        return '%d WS GAME %d' % (year_of(hist, n - (cat >> 3)), (cat & 7) + 1) if n \
            else 'WS BOX SCORE'
    if screen == SCREEN_PLAYOFFS:
        return '%d PLAYOFFS' % year_of(hist, n - cat) if n else 'PLAYOFFS'
    if screen == SCREEN_PBOX:
        heads = [r for r in data['box']
                 if r[0] == n - (cat >> 6) and r[1] == (cat & 63) + 16 and r[2] == 4][:1]
        if heads and n:
            b, i = heads[0][4], heads[0][5]
            rnd, L = b & 3, (b >> 2) & 1
            return '%d %s %s GAME %d' % (year_of(hist, n - (cat >> 6)),
                                         ('AL', 'NL')[L], ('DS', 'LCS')[rnd - 1], i)
        return 'PLAYOFF BOX SCORE'
    if screen == SCREEN_AWARDS:
        return '%d AWARDS' % year_of(hist, n - cat) if n else 'SEASON AWARDS'
    if screen == SCREEN_STANDINGS:
        return '%d STANDINGS' % year_of(hist, n - cat) if n else 'SEASON STANDINGS'
    if screen == SCREEN_SERIES:
        return '%d WORLD SERIES' % year_of(hist, n - cat) if n else 'WORLD SERIES'
    return '%d IN REVIEW' % year_of(hist, n) if n else 'LAST SEASON REVIEW'


def draw_panel(fb):
    fill(fb, C_BG_BROWN)
    rect(fb, 4, 4, 315, 195, C_FRAME_TAN)
    rect(fb, 8, 8, 311, 20, C_TITLE_RED)
    rect(fb, 4, 4, 315, 4, C_BLACK)
    rect(fb, 4, 195, 315, 195, C_BLACK)
    rect(fb, 4, 4, 4, 195, C_BLACK)
    rect(fb, 315, 4, 315, 195, C_BLACK)


def body_cols(state, data):
    """Column table of the current screen; the one-cell 'NO DYNASTY HISTORY YET' row
    always uses COLS_SINGLE so it is never cut to a narrow first column. SETTINGS and
    ABOUT show their rows with no history too."""
    if state[0] == SCREEN_SETTINGS:
        return COLS_SETTINGS
    hist = data['hist']
    if state[0] == SCREEN_ABOUT or hist is None or hist.seasons_recorded == 0:
        return COLS_SINGLE
    if state[0] == SCREEN_OFFSEASON:
        return offseason_body(state, data)[0]
    if state[0] == SCREEN_AWARDS:
        return awards_body(state, data)[0]
    if state[0] == SCREEN_STANDINGS:
        return standings_body(state, data)[0]
    if state[0] == SCREEN_SERIES:
        return series_body(state, data)[0]
    if state[0] == SCREEN_BOX:
        return box_body(state, data)[0]
    if state[0] == SCREEN_PLAYOFFS:
        return playoffs_body(state, data)[0]
    if state[0] == SCREEN_PBOX:
        return pbox_body(state, data)[0]
    if state[0] == SCREEN_LEADERS:
        return leaders_body(state, data)[0]
    if state[0] == SCREEN_MILESTONES and unpack(state)[2] == 1:
        return COLS_WATCH if watch_items(data['hist']) else COLS_SINGLE
    return {SCREEN_MENU: COLS_SINGLE, SCREEN_HISTORY: COLS_HISTORY,
            SCREEN_HOF: COLS_HOF, SCREEN_MILESTONES: COLS_MILESTONES,
            SCREEN_REVIEW: COLS_SINGLE, SCREEN_CARD: COLS_SINGLE}[state[0]]


def draw_row(fb, font, cols, cells, y0, color, band):
    """One table row at y0 (band colour, grid line under it): a cell per column, text cut to
    its column; a row of one text is drawn unclipped from the first column (a message)."""
    rect(fb, 8, y0, 311, y0 + 9, band)
    if len(cells) == 1:
        draw_text(fb, font, cols[0][1], y0 + 2, cells[0], color)
    else:
        for ci, cell in enumerate(cells):
            _h, x, w, align = cols[ci]
            s = cell[:w]
            if align == 'R':
                draw_text(fb, font, x + w * CHAR_W - text_width(font, s), y0 + 2, s, color)
            else:
                draw_text(fb, font, x, y0 + 2, s, color)
    rect(fb, 8, y0 + 10, 311, y0 + 10, C_GRID_GRAY)


def card_pitcher(s, data):
    hist = data['hist']
    return 0 <= s[2] < n_entries(hist) and bool(hist.read_entry(s[2])['pitcher'])


def draw_card(fb, s, data, main_ft):
    """The PLAYER CARD body (C13.5): the portrait (or the gray box with a ?), the five info
    lines, the season table header, its rows and the CAREER row at its fixed slot."""
    info, last = card_info(s, data)
    pic = portrait_of(data, last['face']) if last is not None else None
    px, py = PORTRAIT_X, PORTRAIT_Y
    if pic is None:
        rect(fb, px, py, px + PORTRAIT_W - 1, py + PORTRAIT_H - 1, C_GRID_GRAY)
        q = glyph_of(main_ft, '?')[0]
        draw_text(fb, main_ft, px + (PORTRAIT_W - text_width(main_ft, '?')) // 2,
                  py + (PORTRAIT_H - q) // 2, '?', C_WHITE)
    else:
        w, h, pixels = pic
        for y in range(h):
            base = (py + y) * FB_W + px
            fb[base:base + w] = pixels[y * w:(y + 1) * w]
    for y, text in zip(INFO_Y, info):
        draw_text(fb, main_ft, INFO_X, y, text, C_WHITE)
    cols = COLS_CARD_PIT if card_pitcher(s, data) else COLS_CARD_BAT
    rect(fb, 8, CARD_HDR_Y, 311, CARD_HDR_Y + 9, C_HEADER_GOLD)
    for header, x, w, align in cols:
        h = header[:w]
        if align == 'R':
            draw_text(fb, main_ft, x + w * CHAR_W - text_width(main_ft, h), CARD_HDR_Y + 2,
                      h, C_BLACK)
        else:
            draw_text(fb, main_ft, x, CARD_HDR_Y + 2, h, C_BLACK)
    season, career, post = card_table(s, data)
    for r, cells in enumerate(season):
        draw_row(fb, main_ft, cols, cells, CARD_ROW_Y0 + r * ROW_H, C_BLACK, C_ROW_TAN)
    # CAREER (with a POST row: one season row up, card_rows rows per page) at its fixed slot
    careery = CARD_CAREER_Y - ROW_H if post is not None else CARD_CAREER_Y
    draw_row(fb, main_ft, cols, ('',) + career[1:], careery, C_BLACK, C_ROW_TAN)
    draw_text(fb, main_ft, cols[0][1], careery + 2, 'CAREER', C_BLACK)
    if post is not None:
        # POSTSEASON (C26): the postseason totals under CAREER, the label not cut
        draw_row(fb, main_ft, cols, ('',) + post[1:], CARD_CAREER_Y, C_BLACK, C_ROW_TAN)
        draw_text(fb, main_ft, cols[0][1], CARD_CAREER_Y + 2, 'POSTSEASON', C_BLACK)


def render(state, data):
    fonts = data['fonts']
    main_ft, bold_ft = fonts
    fb = bytearray(FB_SIZE)
    title = screen_title(state, data)
    draw_panel(fb)
    tx = 8 + (304 - text_width(bold_ft, title)) // 2
    draw_text(fb, bold_ft, tx + 1, 11, title, C_BLACK)
    draw_text(fb, bold_ft, tx, 10, title, C_WHITE)
    s = unpack(state)
    screen, page, cat = s[0], s[1], s[2]
    if screen == SCREEN_CARD:
        draw_card(fb, s, data, main_ft)
        draw_text(fb, main_ft, 10, 185, footer_text(state, data), C_WHITE)
        return fb
    cols = body_cols(state, data)
    # the highlighted row of the page: SETTINGS' cat row, the cursor row (C13.4) on the cursor
    # screens, none on a single message row (C15.8)
    if screen == SCREEN_SETTINGS:
        hot = cat - page * ROWS_PER_PAGE
    elif cursor_screen(s) and cols is not COLS_SINGLE:
        hot = s[3] - page * ROWS_PER_PAGE
    else:
        hot = -1
    rect(fb, 8, 24, 311, 33, C_HEADER_GOLD)
    for header, x, w, align in cols:
        h = header[:w]
        if align == 'R':
            draw_text(fb, main_ft, x + w * CHAR_W - text_width(main_ft, h), 26, h, C_BLACK)
        else:
            draw_text(fb, main_ft, x, 26, h, C_BLACK)
    for r, cells in enumerate(rows(state, data)):
        y0 = 35 + r * ROW_H
        on = r == hot
        rect(fb, 8, y0, 311, y0 + 9, C_TITLE_RED if on else C_ROW_TAN)
        color = C_WHITE if on else C_BLACK
        for ci, cell in enumerate(cells):
            _h, x, w, align = cols[ci]
            s = cell[:w]
            if align == 'R':
                draw_text(fb, main_ft, x + w * CHAR_W - text_width(main_ft, s),
                          y0 + 2, s, color)
            else:
                draw_text(fb, main_ft, x, y0 + 2, s, color)
        rect(fb, 8, y0 + 10, 311, y0 + 10, C_GRID_GRAY)
    draw_text(fb, main_ft, 10, 185, footer_text(state, data), C_WHITE)
    return fb


# ---------------------------------------------------------------- main
def parse_keys(s):
    """The --keys list (C13.6): a number is a key code (int(t, 0)); Lx.y is a left click at
    (x, y), returned as ('L', x, y); R is a right click, which is ESC."""
    out = []
    for t in s.split(','):
        t = t.strip()
        if not t:
            continue
        if t == 'R':
            out.append(KEY_ESC)
        elif t[0] == 'L':
            x, y = t[1:].split('.')
            out.append(('L', int(x), int(y)))
        else:
            out.append(int(t, 0))
    return out


def _band(y):
    """The body row of the page (0..ROWS_PER_PAGE - 1) whose band (35 + 11r .. 35 + 11r + 9)
    holds y, else None."""
    if y < BODY_Y0:
        return None
    r, off = divmod(y - BODY_Y0, ROW_H)
    return r if off <= 9 and r < ROWS_PER_PAGE else None


def click_to_key(state, data, x, y):
    """(key, row) of a left click at (x, y), by the rules of C13.6 in order: a hub row band is
    that row's key; a SETTINGS row band is the row with ENTER (START YEAR: LEFT when x < 160,
    else RIGHT); a list row band of a cursor screen is the row with ENTER (the offseason
    RETIREMENTS phase: C, as ENTER walks there); a title band on a screen where LEFT and RIGHT
    act is LEFT or RIGHT; a footer band is PGUP or PGDN. row is the cursor row to set before the
    key (None when no cursor moves). (None, None) when the click does nothing."""
    s = unpack(state)
    screen, page = s[0], s[1]
    r = _band(y)
    hist = data['hist']
    title_menu = (hist is None or hist.seasons_recorded == 0) and s[2] >> 4
    if screen == SCREEN_MENU and r is not None and r < len(MENU_ROWS) and not title_menu:
        return ord(MENU_ROWS[r][0]), None
    if screen == SCREEN_SETTINGS and r is not None:
        row = page * ROWS_PER_PAGE + r
        if row < len(settings_rows(data)):
            if row == SET_START:
                return (KEY_LEFT if x < 160 else KEY_RIGHT), row
            return KEY_ENTER, row
    if cursor_screen(s) and r is not None:
        row = page * ROWS_PER_PAGE + r
        if row < total_rows(s, data):
            return (KEY_CARD[0] if screen == SCREEN_OFFSEASON else KEY_ENTER), row
    if TITLE_Y0 <= y <= TITLE_Y1 and (screen in LEFT_RIGHT_SCREENS or
                                      (screen == SCREEN_SETTINGS and s[2] == SET_START)):
        return (KEY_LEFT if x < 160 else KEY_RIGHT), None
    if y >= FOOTER_Y0:
        return (KEY_PGUP if x < 160 else KEY_PGDN), None
    return None, None


def cursor_to(state, row):
    """state with the cursor on row: SETTINGS' cursor (its page follows), or the row cursor of a
    cursor screen (C13.4)."""
    s = unpack(state)
    if s[0] == SCREEN_SETTINGS:
        return pack(SCREEN_SETTINGS, row // ROWS_PER_PAGE, row)
    return cursor_state(s, row)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--review', action='store_true')
    ap.add_argument('--offseason', action='store_true')
    ap.add_argument('--title', action='store_true')
    ap.add_argument('--menu', type=int, default=None)
    ap.add_argument('--control', default=None)
    ap.add_argument('--keys', default='')
    ap.add_argument('--png', default=None)
    ap.add_argument('--raw', default=None)
    ap.add_argument('--game-dir', default='.')
    ap.add_argument('--anms-dir', default='ANMS')
    ap.add_argument('league_dir')
    ap.add_argument('font_dir')
    a = ap.parse_args(argv)
    menu = a.menu
    if a.control is not None and menu is None:
        menu = control_item(a.control)
    data = load_data(a.league_dir, a.font_dir, a.game_dir, a.anms_dir)
    if a.offseason:
        state = (SCREEN_OFFSEASON, 0, 16)
    elif a.review:
        state = (SCREEN_REVIEW, 0, 0)
    elif a.title:
        state = (SCREEN_MENU, 0, TITLE_FLAG)
    elif menu == 2:
        state = (SCREEN_SETTINGS, 0, 0)
    elif menu == 3:
        state = (SCREEN_ABOUT, 0, 0)
    else:
        state = (SCREEN_MENU, 0, 0)
    for k in parse_keys(a.keys):
        if isinstance(k, tuple):                  # ('L', x, y): a left click
            key, row = click_to_key(state, data, k[1], k[2])
            if key is None:
                continue
            if row is not None:
                state = cursor_to(state, row)
            state, _ex = step(state, key, data)
        else:
            state, _ex = step(state, k, data)
    fb = render(state, data)
    if a.png:
        pal = load_palette(os.path.join(a.font_dir, 'DEFAULT.PAL'))
        write_png(a.png, fb, pal)
    if a.raw:
        open(a.raw, 'wb').write(bytes(fb))
    if a.control is not None:
        control_return(a.control)


if __name__ == '__main__':
    main(sys.argv[1:])
