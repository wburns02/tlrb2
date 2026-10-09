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
       LEAGUE_DIR FONT_DIR
(precedence --offseason, --review, --title, --menu; --menu 2 opens DYNASTY SETTINGS,
--menu 3 ABOUT THE MODS; --control reads the menu item from CONTROL and writes
CONTROL[1] = CONTROL[0] when the session ends)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import Counter
import history
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

SCREEN_MENU, SCREEN_HISTORY, SCREEN_HOF = 0, 1, 2
SCREEN_LEADERS, SCREEN_MILESTONES, SCREEN_REVIEW = 3, 4, 5
SCREEN_OFFSEASON = 6
SCREEN_SETTINGS, SCREEN_ABOUT = 7, 8
N_CATS = 12

# the hub (SCREEN_MENU) rows: key 1..8 opens screen key - 48
MENU_ROWS = ['1  SEASON HISTORY', '2  HALL OF FAME', '3  CAREER LEADERS',
             '4  MILESTONES', '5  LAST SEASON REVIEW', '6  OFFSEASON',
             '7  DYNASTY SETTINGS', '8  ABOUT THE MODS']

# HISTORY.DAT header fields used by DYNASTY SETTINGS: byte 10 era, bytes 12..15 mask
HDR_SIZE = 32
# MAJ team stems: AL slot s (lg s) at 0x21d, NL slot s (lg s + 16) at 0x758c
MAJ_S_AL, MAJ_S_NL = 0x21d, 0x758c
MAJ_O_STEM = 0x1d7
MAJ_MIN = MAJ_S_NL + MAJ_O_STEM + 128
# CONTROL file of /MENU (TONY2.BAT): byte 1 is 8 + item, the request; when DYNVIEW exits
# it copies byte 0 (the program TONY2.BAT restarts) over byte 1
CONTROL_FILE = 'CONTROL'

# offseason phases: cat & 15 is the phase, cat >> 4 the launched flag
OFF_REVIEW, OFF_RETIRE, OFF_DRAFT, OFF_TRADES, OFF_FA, OFF_READY = range(6)
OFF_TITLES = ['1/6 SEASON %d IN REVIEW', '2/6 RETIREMENTS', '3/6 ROOKIE DRAFT',
              '4/6 TRADES', '5/6 FREE AGENT SIGNINGS', '6/6 SEASON %d IS READY']
OFF_LAUNCH_TEXT = 'ENTER: ON TO SEASON %d'
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
              'ARCHIVED FIRST TO C:\\SEASONS.',
              '',
              'DYNASTY > DYNASTY MODE ON THE MENU BAR',
              'SHOWS HISTORY, HALL OF FAME, LEADERS,',
              'MILESTONES AND THE LAST OFFSEASON.',
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
              '',
              'NEW FACES',
              '67 NEW PORTRAITS JOIN THE 30 STOCK ONES.',
              'ROOKIES AND CREATED PLAYERS USE THEM.',
              '',
              'MODERN BALLPARKS',
              'UTILITIES > ASSIGN STADIUMS LETS ANY TEAM',
              'PLAY IN A NEW PARK.']

# career leader categories: (title label, kind, TOTALS index)
# kind: 'count' | 'avg' | 'era' | 'war' | 'aw0' (MVP awards) | 'aw3' (GG awards)
CATS = [('H', 'count', 2), ('HR', 'count', 5), ('RBI', 'count', 7),
        ('SB', 'count', 10), ('AVG', 'avg', 0), ('WAR', 'war', 0),
        ('W', 'count', 13), ('SV', 'count', 15), ('PSO', 'count', 23),
        ('ERA', 'era', 0), ('MVP AWARDS', 'aw0', 0), ('GG AWARDS', 'aw3', 0)]

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
def load_data(league_dir, font_dir=None):
    """data dict shared by step/render/rows. A missing HISTORY.DAT loads as a
    brand-new file (0 seasons): every screen then shows 'NO DYNASTY HISTORY YET'."""
    hp = os.path.join(league_dir, 'HISTORY.DAT')
    hist = history.History.load(hp)
    ms = history.milestone_entries(hp)
    fonts = load_fonts(font_dir) if font_dir else None
    era, mask = load_settings(league_dir)
    return {'hist': hist, 'ms': ms, 'fonts': fonts, 'league_dir': league_dir,
            'events': parse_rosters(league_dir), 'era': era, 'mask': mask,
            'teams': settings_teams(league_dir)}


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


def parse_rosters(league_dir):
    """ROSTERS.TXT as offseason events, in file order: ('DRAFT', stem, name) for the
    first DRAFT_KEEP valid DRAFT lines; ('SIGN', team, name, frm); ('TRADE', a, x, b,
    y) where b is the first token from index 3 that names a team file; ('REL',).
    LF lines with one trailing CR stripped; a line over ROSTER_LINE_MAX bytes is
    ignored whole. A missing or unreadable file gives []."""
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
            out.append(('REL',))
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
    """[(lg, display)] for the MAJ team slots in ascending lg (AL slot s is lg s, NL slot
    s is lg s + 16). Empty with no MAJ, on a read error or a MAJ shorter than MAJ_MIN; a
    slot whose stem is empty or has no team file is skipped."""
    mp = history.maj_or_none(league_dir)
    if mp is None:
        return []
    try:
        with open(mp, 'rb') as fh:
            d = fh.read(MAJ_MIN)
    except OSError:
        return []
    if len(d) < MAJ_MIN:
        return []
    out = []
    for lg in range(32):
        s = MAJ_S_AL if lg < 16 else MAJ_S_NL
        o = s + MAJ_O_STEM + 8 * (lg & 15)
        stem = d[o:o + 8].split(b'\0')[0]
        if not stem or v20_path(league_dir, stem) is None:
            continue
        out.append((lg, team_disp(league_dir, stem.decode('latin-1'))))
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


def settings_rows(data):
    """ERA RULES, then one row per team of data['teams'] (YOU MANAGE / AI MANAGES)."""
    mask = data['mask']
    return [('ERA RULES', era_label(data['era']))] + \
        [(disp, 'YOU MANAGE' if (mask >> lg) & 1 else 'AI MANAGES')
         for lg, disp in data['teams']]


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
def cat_value(e, cat):
    _label, kind, idx = cat
    if kind == 'count':
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
    _label, kind, idx = cat
    t = e['totals']
    if kind == 'count':
        return t[idx] > 0
    if kind == 'avg':
        return t[1] >= 3000
    if kind == 'era':
        return t[19] >= 4500
    if kind == 'aw0' or kind == 'aw3':
        return cat_value(e, cat) > 0
    return True                               # WAR: no qualifier


def cat_format(cat, value):
    kind = cat[1]
    if kind == 'avg':
        return fmt_avg(value)
    if kind == 'era':
        return fmt_era100(value)
    if kind == 'war':
        return fmt_war10(value)
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


def history_rows(hist, league_dir=None):
    """One row per season, newest first: YEAR, CHAMPION, AL MVP, NL MVP (the
    runner-up is on REVIEW; dropping it leaves room for full team names)."""
    n = min(hist.seasons_recorded, history.SEASON_COUNT)
    items = []
    for pos in range(1, n + 1):
        se = hist.read_season_entry(pos)
        items.append((-se['season_no'], pos, se))
    items.sort(key=lambda t: (t[0], t[1]))
    out = []
    for _s, _p, se in items:
        out.append(('%d' % se['season_no'],
                    stem_display(se['champion_stem'], league_dir),
                    entry_name(hist, se['awards'][0], 11),
                    entry_name(hist, se['awards'][3], 11)))
    return out


def hof_rows(hist):
    """Status 3 entries by (HoF season descending, index ascending):
    NAME, IND, YRS, H/W, HR/SO(PSO), AVG/ERA, WAR."""
    items = []
    for i in range(n_entries(hist)):
        e = hist.read_entry(i)
        if e['status'] == history.STATUS_HOF:
            items.append((-e['hof_season'], i, e))
    items.sort(key=lambda t: (t[0], t[1]))
    out = []
    for _s, _i, e in items[:LIST_MAX]:
        t = e['totals']
        if e['pitcher']:
            s1, s2, s3 = fmt_count(t[13]), fmt_count(t[23]), fmt_era100(era100_of(t))
        else:
            s1, s2, s3 = fmt_count(t[2]), fmt_count(t[5]), fmt_avg(avg_of(t))
        out.append((name_display(e['name'], 12) or '?',
                    '%d' % e['hof_season'], '%d' % e['seasons_played'],
                    s1, s2, s3, fmt_war10(e['WAR10'])))
    return out


def leaders_rows(hist, cat_index, page=0):
    """Career leaders, top 12 (rank restarted per page): rank, NAME, status mark,
    YRS, value."""
    cat = CATS[cat_index]
    kind = cat[1]
    cands = []
    for i in range(n_entries(hist)):
        e = hist.read_entry(i)
        if cat_qualifies(e, cat):
            cands.append((cat_value(e, cat), i, e))
    if kind == 'era':
        cands.sort(key=lambda t: (t[0], t[1]))
    else:
        cands.sort(key=lambda t: (-t[0], t[1]))
    cands = cands[:LIST_MAX]
    out = []
    for rank in range(page * ROWS_PER_PAGE, min((page + 1) * ROWS_PER_PAGE,
                                                len(cands))):
        val, _i, e = cands[rank]
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


def milestone_rows(hist, ms):
    """MILESTON.DAT records, newest season first, within a season in file order:
    YEAR, NAME, EVENT."""
    items = []
    for pos, rec in enumerate(ms):
        season, _idx, _kind, _value = rec
        items.append((-season, pos, rec))
    items.sort(key=lambda t: (t[0], t[1]))
    out = []
    for _s, _p, (season, idx, kind, value) in items[:LIST_MAX]:
        out.append(('%d' % season, entry_name(hist, idx, 16),
                    event_text(kind, value)))
    return out


def review_rows(hist, ms, league_dir=None):
    """REVIEW lines for the last recorded season; None when there is no history.
    Champion/runner-up, six award lines, new HoF entries, that season's milestones;
    cut at 12 lines."""
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
        if season == last:
            lines.append((entry_name(hist, idx, 16) + ' ' + event_text(kind, value),))
    return lines[:ROWS_PER_PAGE]


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
            (OFF_LAUNCH_TEXT % (hist.seasons_recorded + 1)) if launched
            else OFF_STAY_TEXT]


def offseason_body(state, data):
    """(cols, rows) of the offseason phase in state: every row, capped at LIST_MAX. A
    phase with nothing to show is one message row with COLS_SINGLE. With no history
    the body is empty (rows() then shows the NO DYNASTY row)."""
    hist = data['hist']
    if hist.seasons_recorded == 0:
        return COLS_SINGLE, []
    _screen, _page, cat = state
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
        rows = [('#%d' % k, disp(team), name)
                for k, (team, name) in enumerate(picks[:LIST_MAX], 1)]
    elif phase == OFF_TRADES:
        cols, msg = COLS_MOVE, 'NO TRADES'
        rows = []
        for e in ev:
            if e[0] == 'TRADE':
                _k, a, x, b, y = e
                rows.append((disp(a), x, disp(b)))
                rows.append((disp(b), y, disp(a)))
        rows = rows[:LIST_MAX]
    else:
        cols, msg = COLS_MOVE, 'NO FREE AGENT SIGNINGS'
        _picks, fa = sign_split(ev)
        rows = [(disp(team), name, 'FREE AGENT' if ascii_upper(frm) == 'POOL' else disp(frm))
                for team, name, frm in fa[:LIST_MAX]]
    if not rows:
        return COLS_SINGLE, [(msg,)]
    return cols, rows


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
    screen, _page, cat = state
    if screen == SCREEN_HISTORY:
        n = history_rows(hist) if hist.seasons_recorded else []
    elif screen == SCREEN_HOF:
        n = hof_rows(hist) if hist.seasons_recorded else []
    elif screen == SCREEN_LEADERS:
        n = range(leaders_count(hist, cat))
    elif screen == SCREEN_MILESTONES:
        n = milestone_rows(hist, data['ms']) if hist.seasons_recorded else []
    elif screen == SCREEN_REVIEW:
        n = review_rows(hist, data['ms']) or []
    elif screen == SCREEN_OFFSEASON:
        n = offseason_body(state, data)[1]
    elif screen == SCREEN_SETTINGS:
        n = settings_rows(data)
    elif screen == SCREEN_ABOUT:
        n = ABOUT_ROWS
    else:
        n = MENU_ROWS
    return len(n)


def rows(state, data):
    """Model rows of the current page as cell tuples (no fonts needed)."""
    hist = data['hist']
    screen, page, cat = state
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
        return leaders_rows(hist, cat, page)
    if screen == SCREEN_OFFSEASON:
        body = offseason_body(state, data)[1]
        return body[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]
    if screen == SCREEN_HISTORY:
        all_rows = history_rows(hist, data.get('league_dir'))
    elif screen == SCREEN_HOF:
        all_rows = hof_rows(hist)
    elif screen == SCREEN_MILESTONES:
        all_rows = milestone_rows(hist, data['ms'])
    else:
        all_rows = review_rows(hist, data['ms'], data.get('league_dir'))
        if all_rows is None:
            return []
    return all_rows[page * ROWS_PER_PAGE:(page + 1) * ROWS_PER_PAGE]


def step(state, key, data):
    """(state, exit_flag). ESC exits from MENU; from any other screen it goes back
    to MENU. PGUP/PGDN page by 12; LEFT/RIGHT cycle the LEADERS category. ENTER on
    REVIEW goes to MENU. ENTER walks the offseason phases; past the last one it exits
    when the offseason was launched (cat >> 4) and goes to MENU otherwise. ENTER on the
    /TITLE menu (cat >> 4) exits."""
    screen, page, cat = state
    if key == KEY_ESC:
        if screen == SCREEN_MENU:
            return (SCREEN_MENU, 0, 0), 1
        return (SCREEN_MENU, 0, 0), 0
    if screen == SCREEN_MENU:
        if 49 <= key <= 56:
            return (key - 48, 0, 0), 0
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
    if screen == SCREEN_SETTINGS:
        # cat is the cursor: 0 the ERA RULES row, c >= 1 the team teams[c - 1]
        n = len(settings_rows(data))
        if key == KEY_ENTER:
            if cat == 0:
                data['era'] = era_next(data['era'])
            else:
                data['mask'] ^= 1 << data['teams'][cat - 1][0]
            save_settings(data['league_dir'], data['era'], data['mask'])
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
        return (SCREEN_LEADERS, 0, (cat + d) % N_CATS), 0
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
COLS_RETIRE = [('NAME', _cx(0), 18, 'L'), ('AGE', _cx(18), 5, 'R'), ('YRS', _cx(23), 5, 'R'),
               ('WAR', _cx(28), 7, 'R'), ('HOF', _cx(36), 6, 'R')]
COLS_DRAFT = [('#', _cx(0), 4, 'L'), ('TEAM', _cx(4), 15, 'L'), ('PLAYER', _cx(19), 23, 'L')]
COLS_MOVE = [('TEAM', _cx(0), 13, 'L'), ('PLAYER', _cx(14), 15, 'L'), ('FROM', _cx(30), 12, 'L')]
COLS_SETTINGS = [('SETTING', _cx(0), 24, 'L'), ('VALUE', _cx(26), 16, 'L')]
OFF_COLS = [COLS_SINGLE, COLS_RETIRE, COLS_DRAFT, COLS_MOVE, COLS_MOVE, COLS_SINGLE]

FOOTERS = {SCREEN_MENU: '1-8 SELECT   ESC EXIT',
           SCREEN_HISTORY: 'PGUP PGDN   ESC MENU',
           SCREEN_HOF: 'PGUP PGDN   ESC MENU',
           SCREEN_LEADERS: 'LEFT RIGHT CATEGORY   ESC MENU',
           SCREEN_MILESTONES: 'PGUP PGDN   ESC MENU',
           SCREEN_REVIEW: 'ENTER MENU   ESC MENU',
           SCREEN_SETTINGS: 'UP DOWN MOVE   ENTER CHANGE   ESC MENU',
           SCREEN_ABOUT: 'PGUP PGDN   ESC MENU'}


TITLE_FOOTER = '1-8 SELECT   ENTER PLAY BALL'
TITLE_FOOTER_NEW = 'ENTER PLAY BALL'


def footer_text(state, data=None):
    """Footer line of state; the offseason's ENTER label follows its phase, the /TITLE
    menu's follows whether any season is recorded."""
    screen, _page, cat = state
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
    screen, page, cat = state
    if screen == SCREEN_MENU:
        if cat >> 4:
            return 'DYNASTY MODE: SEASON %d' % (data['hist'].seasons_recorded + 1)
        return 'DYNASTY'
    if screen == SCREEN_HISTORY:
        return 'SEASON HISTORY'
    if screen == SCREEN_HOF:
        return 'HALL OF FAME'
    if screen == SCREEN_LEADERS:
        return 'CAREER LEADERS: ' + CATS[cat][0]
    if screen == SCREEN_MILESTONES:
        return 'MILESTONES'
    if screen == SCREEN_OFFSEASON:
        n = data['hist'].seasons_recorded
        phase = cat & 15
        if phase == OFF_REVIEW:
            return OFF_TITLES[OFF_REVIEW] % n
        if phase == OFF_READY:
            return OFF_TITLES[OFF_READY] % (n + 1)
        return OFF_TITLES[phase]
    if screen == SCREEN_SETTINGS:
        return 'DYNASTY SETTINGS'
    if screen == SCREEN_ABOUT:
        return 'ABOUT THE MODS %d/%d' % (page + 1, (len(ABOUT_ROWS) + ROWS_PER_PAGE - 1)
                                         // ROWS_PER_PAGE)
    return 'SEASON %d IN REVIEW' % data['hist'].seasons_recorded


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
    return {SCREEN_MENU: COLS_SINGLE, SCREEN_HISTORY: COLS_HISTORY,
            SCREEN_HOF: COLS_HOF, SCREEN_LEADERS: COLS_LEADERS,
            SCREEN_MILESTONES: COLS_MILESTONES, SCREEN_REVIEW: COLS_SINGLE}[state[0]]


def render(state, data):
    fonts = data['fonts']
    main_ft, bold_ft = fonts
    fb = bytearray(FB_SIZE)
    title = screen_title(state, data)
    draw_panel(fb)
    tx = 8 + (304 - text_width(bold_ft, title)) // 2
    draw_text(fb, bold_ft, tx + 1, 11, title, C_BLACK)
    draw_text(fb, bold_ft, tx, 10, title, C_WHITE)
    screen, page, cat = state
    cols = body_cols(state, data)
    # SETTINGS: the cursor (cat) row of the page is highlighted
    hot = cat - page * ROWS_PER_PAGE if screen == SCREEN_SETTINGS else -1
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
    return [int(t, 0) for t in s.split(',') if t.strip()]


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
    ap.add_argument('league_dir')
    ap.add_argument('font_dir')
    a = ap.parse_args(argv)
    menu = a.menu
    if a.control is not None and menu is None:
        menu = control_item(a.control)
    data = load_data(a.league_dir, a.font_dir)
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
