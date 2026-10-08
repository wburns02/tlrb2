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

usage: python3 tools/m4/dynview.py [--review] [--keys K,K,...] [--png OUT.png]
       [--raw OUT.RAW] LEAGUE_DIR FONT_DIR
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

# BIOS int 16h codes; ASCII keys are their char code
KEY_ESC, KEY_ENTER = 27, 13
KEY_LEFT, KEY_RIGHT = 0x4b00, 0x4d00
KEY_PGUP, KEY_PGDN = 0x4900, 0x5100
KEY_UP, KEY_DOWN = 0x4800, 0x5000

SCREEN_MENU, SCREEN_HISTORY, SCREEN_HOF = 0, 1, 2
SCREEN_LEADERS, SCREEN_MILESTONES, SCREEN_REVIEW = 3, 4, 5
N_CATS = 12

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
    return {'hist': hist, 'ms': ms, 'fonts': fonts, 'league_dir': league_dir}


def team_name(league_dir, stem):
    """V20 header name (bytes 0..13, NUL ended) of LEAGUE_DIR/<STEM>.V20, '' when
    the file is missing or the name is blank. Stems are stored lower case."""
    if not league_dir or not stem:
        return ''
    want = stem.decode('latin-1').upper() + '.V20'
    try:
        names = os.listdir(league_dir)
    except OSError:
        return ''
    for f in names:
        if f.upper() == want:
            try:
                with open(os.path.join(league_dir, f), 'rb') as fh:
                    raw = fh.read(14)
            except OSError:
                return ''
            return one_field(raw)
    return ''


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
    else:
        return 5
    return len(n)


def rows(state, data):
    """Model rows of the current page as cell tuples (no fonts needed)."""
    hist = data['hist']
    if hist is None or hist.seasons_recorded == 0:
        return [('NO DYNASTY HISTORY YET',)]
    screen, page, cat = state
    if screen == SCREEN_MENU:
        return [('1  SEASON HISTORY',), ('2  HALL OF FAME',), ('3  CAREER LEADERS',),
                ('4  MILESTONES',), ('5  LAST SEASON REVIEW',)]
    if screen == SCREEN_LEADERS:
        return leaders_rows(hist, cat, page)
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
    to MENU. PGUP/PGDN page by 12; LEFT/RIGHT cycle the LEADERS category."""
    screen, page, cat = state
    if key == KEY_ESC:
        if screen == SCREEN_MENU:
            return (SCREEN_MENU, 0, 0), 1
        return (SCREEN_MENU, 0, 0), 0
    if screen == SCREEN_MENU:
        if 49 <= key <= 53:
            return (key - 48, 0, 0), 0
        return state, 0
    if screen == SCREEN_REVIEW and key == KEY_ENTER:
        return (SCREEN_MENU, 0, 0), 0
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

FOOTERS = {SCREEN_MENU: '1-5 SELECT   ESC EXIT',
           SCREEN_HISTORY: 'PGUP PGDN   ESC MENU',
           SCREEN_HOF: 'PGUP PGDN   ESC MENU',
           SCREEN_LEADERS: 'LEFT RIGHT CATEGORY   ESC MENU',
           SCREEN_MILESTONES: 'PGUP PGDN   ESC MENU',
           SCREEN_REVIEW: 'ENTER MENU   ESC MENU'}


def screen_title(state, data):
    screen, _page, cat = state
    if screen == SCREEN_MENU:
        return 'DYNASTY'
    if screen == SCREEN_HISTORY:
        return 'SEASON HISTORY'
    if screen == SCREEN_HOF:
        return 'HALL OF FAME'
    if screen == SCREEN_LEADERS:
        return 'CAREER LEADERS: ' + CATS[cat][0]
    if screen == SCREEN_MILESTONES:
        return 'MILESTONES'
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
    always uses COLS_SINGLE so it is never cut to a narrow first column."""
    hist = data['hist']
    if hist is None or hist.seasons_recorded == 0:
        return COLS_SINGLE
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
    _screen, _page, _cat = state
    cols = body_cols(state, data)
    rect(fb, 8, 24, 311, 33, C_HEADER_GOLD)
    for header, x, w, align in cols:
        h = header[:w]
        if align == 'R':
            draw_text(fb, main_ft, x + w * CHAR_W - text_width(main_ft, h), 26, h, C_BLACK)
        else:
            draw_text(fb, main_ft, x, 26, h, C_BLACK)
    for r, cells in enumerate(rows(state, data)):
        y0 = 35 + r * ROW_H
        rect(fb, 8, y0, 311, y0 + 9, C_ROW_TAN)
        for ci, cell in enumerate(cells):
            _h, x, w, align = cols[ci]
            s = cell[:w]
            if align == 'R':
                draw_text(fb, main_ft, x + w * CHAR_W - text_width(main_ft, s),
                          y0 + 2, s, C_BLACK)
            else:
                draw_text(fb, main_ft, x, y0 + 2, s, C_BLACK)
        rect(fb, 8, y0 + 10, 311, y0 + 10, C_GRID_GRAY)
    draw_text(fb, main_ft, 10, 185, FOOTERS[_screen], C_WHITE)
    return fb


# ---------------------------------------------------------------- main
def parse_keys(s):
    return [int(t, 0) for t in s.split(',') if t.strip()]


def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--review', action='store_true')
    ap.add_argument('--keys', default='')
    ap.add_argument('--png', default=None)
    ap.add_argument('--raw', default=None)
    ap.add_argument('league_dir')
    ap.add_argument('font_dir')
    a = ap.parse_args(argv)
    data = load_data(a.league_dir, a.font_dir)
    if a.review:
        state = (SCREEN_REVIEW, 0, 0)
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


if __name__ == '__main__':
    main(sys.argv[1:])
