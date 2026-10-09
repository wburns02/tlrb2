#!/usr/bin/env python3
"""CREATE A PLAYER reference (CREATE.EXE): pure Python state machine and renderer.

TONY2.BAT runs CREATE from DYNASTY > CREATE A PLAYER. The player picks a team of the
league and a roster slot of that team, types a new player into the slot and saves.
The team V20 gets the new roster record (slot s = record s) and its season half
(record s + 40); CONTROL[1] is then set so TONY2.BAT restarts MAIN.

The C port tools/m4/create_c/create.c (OpenWatcom, DOS, VGA mode 13h) must match this
module pixel for pixel and the saved V20 bytes exactly. Integers only; draws use the
dynview primitives (fill, rect, draw_text).

usage: python3 tools/m4/create.py [--keys K,K,...] [--png OUT.png] [--raw OUT.RAW]
       [--control PATH] LEAGUE_DIR FONT_DIR [ANMS_DIR]
"""
import argparse
import glob
import os
import string
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import rookies  # noqa: E402
import team_fill  # noqa: E402
from dynview import (C_BLACK, C_WHITE, C_DRED, C_TITLE_RED, C_HEADER_GOLD,  # noqa: E402
                     C_ROW_TAN, C_GRID_GRAY, FB_SIZE, FB_W, KEY_ESC, KEY_ENTER,  # noqa: E402
                     KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_PGUP, KEY_PGDN,  # noqa: E402
                     ROW_H, ROWS_PER_PAGE, CHAR_W, _cx, draw_text, text_width,  # noqa: E402
                     rect, draw_panel, name_display, team_disp, v20_path,  # noqa: E402
                     parse_keys, load_fonts, load_palette, write_png)  # noqa: E402

# ---------------------------------------------------------------- constants
S_TEAM, S_SLOT, S_EDIT, S_CONFIRM, S_DONE = range(5)
KEY_BACK = 8

RECORD_LEN = rookies.RECORD_LEN           # 143
HEADER_LEN = 295                          # V20 header before the first record
ROSTER_SLOTS = 40                         # records 0..39; slot s is record s
SEASON_BASE = ROSTER_SLOTS                # record s + 40 is the season half of slot s
PITCHER_SLOTS = 16                        # slots 0..15 pitchers, 16..39 batters
IMAGE_LEN = HEADER_LEN + 80 * RECORD_LEN  # 11735: header + 80 records
AL_BASE, NL_BASE = 0x21d, 0x758c          # *.MAJ offsets of the AL and NL stem tables
MAJ_STEM_OFF = 0x1d7                      # first stem inside each 8 slot table
MAJ_MIN_LEN = NL_BASE + MAJ_STEM_OFF + 8 * 15 + 8   # 30691: last byte of the NL stems
DEFAULT_YEAR_BYTE = 123

LAST_MAX, FIRST_MAX = 11, 7
NAME_CHARS = frozenset(string.ascii_letters + " .'-")
AGE_MIN, AGE_MAX = 18, 45
DEFAULT_AGE = 22
DEFAULT_RATING = 6
PIT_ENDURANCE_CAP = 10
RATING_CAP = 12
FACE_DEFAULT_N = 30
FACE_X, FACE_Y = 244, 43                  # portrait pixels (48 x 56)
PORTRAIT_W, PORTRAIT_H = 48, 56

POS_LABELS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH', 'OF', 'IF',
              'OI', 'CO', 'CI', 'C3']
# (bats, throws) per hands index, as the screen shows them
HANDS = [('R', 'R'), ('L', 'L'), ('S', 'R'), ('R', 'L'), ('L', 'R'), ('S', 'L')]
BATS_CODE = {'R': 1, 'S': 2, 'L': 0}      # record byte 29 bits 2..1

# edit rows: (field, label); batter 13 rows, pitcher 10 rows
BAT_FIELDS = [('last', 'LAST NAME'), ('first', 'FIRST NAME'), ('pos', 'POSITION'),
              ('hands', 'HANDS'), ('age', 'AGE'), ('r0', 'POWER'), ('r1', 'BUNT'),
              ('r2', 'HIT AND RUN'), ('r3', 'SPEED'), ('r4', 'RANGE'), ('r5', 'ARM'),
              ('face', 'FACE'), ('save', 'SAVE PLAYER')]
PIT_FIELDS = [('last', 'LAST NAME'), ('first', 'FIRST NAME'), ('pos', 'POSITION'),
              ('hands', 'HANDS'), ('age', 'AGE'), ('r0', 'CONTROL'), ('r1', 'VELOCITY'),
              ('r2', 'ENDURANCE'), ('face', 'FACE'), ('save', 'SAVE PLAYER')]

COLS_TEAM = [('TEAM', _cx(0), 20, 'L'), ('LEAGUE', _cx(30), 12, 'L')]
COLS_SLOT = [('SLOT', _cx(0), 4, 'L'), ('PLAYER', _cx(5), 20, 'L'),
             ('POS', _cx(26), 4, 'L'), ('AGE', _cx(31), 4, 'R')]
COLS_ONE = [(' ', _cx(0), 42, 'L')]

FOOT_TEAM = 'UP DOWN   ENTER PICK   ESC EXIT'
FOOT_SLOT = 'UP DOWN   ENTER PICK   ESC TEAMS'
FOOT_CONFIRM = 'ENTER REPLACE   ESC BACK'
FOOT_DONE = 'ENTER CREATE ANOTHER   ESC EXIT'
FOOT_NAME = 'TYPE NAME   UP DOWN   ESC SLOTS'
FOOT_SAVE = 'ENTER SAVE   UP DOWN   ESC SLOTS'
FOOT_FIELD = 'UP DOWN   LEFT RIGHT CHANGE   ESC SLOTS'
MSG_NAME = 'TYPE A LAST NAME FIRST'


# ---------------------------------------------------------------- league data
def teams(league_dir):
    """[(lg, stem, display)] for lg 0..31 ascending. The MAJ is the first sorted
    *.MAJ of league_dir; a file shorter than MAJ_MIN_LEN has no teams. A stem is
    the 8 bytes at the team's name slot cut at the first NUL; an empty stem or one
    without a team file is skipped."""
    majs = sorted(glob.glob(os.path.join(league_dir, '*.MAJ')))
    if not majs:
        return []
    try:
        with open(majs[0], 'rb') as fh:
            d = fh.read(MAJ_MIN_LEN)
    except OSError:
        return []
    if len(d) < MAJ_MIN_LEN:
        return []
    out = []
    for lg in range(32):
        base, slot = (AL_BASE, lg) if lg < 16 else (NL_BASE, lg - 16)
        off = base + MAJ_STEM_OFF + 8 * slot
        stem = d[off:off + 8].split(b'\0')[0]
        if not stem or v20_path(league_dir, stem) is None:
            continue
        s = stem.decode('latin-1')
        out.append((lg, s, team_disp(league_dir, s)))
    return out


def read_v20(league_dir, stem):
    """The team image: header plus 80 records, zero padded when the file is shorter
    (or missing)."""
    path = v20_path(league_dir, stem.encode('latin-1'))
    data = b''
    if path is not None:
        try:
            with open(path, 'rb') as fh:
                data = fh.read(IMAGE_LEN)
        except OSError:
            data = b''
    return data.ljust(IMAGE_LEN, b'\0')


def record(image, r):
    off = HEADER_LEN + RECORD_LEN * r
    return image[off:off + RECORD_LEN]


def year_byte(image):
    """Byte 21 of the first named record among records 0..79, else 123."""
    for r in range(2 * ROSTER_SLOTS):
        rec = record(image, r)
        if rec[0]:
            return rec[rookies.OFF_YEAR]
    return DEFAULT_YEAR_BYTE


def slot_label(s):
    return 'P%d' % (s + 1) if s < PITCHER_SLOTS else 'B%d' % (s - PITCHER_SLOTS + 1)


def portrait(anms_dir, k):
    """(w, h, pixels) of PORTRAIT.ANM frame k, or None. Frame k must be stored
    (clen 0) at 48 x 56 and fit the file; frames before it are skipped by their
    headers (12 bytes: flags, h, w, yo, xo, clen as u16 LE)."""
    try:
        with open(os.path.join(anms_dir, 'PORTRAIT.ANM'), 'rb') as fh:
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


def load_ctx(league_dir, font_dir, anms_dir='ANMS'):
    return {'league_dir': league_dir, 'anms_dir': anms_dir,
            'teams': teams(league_dir), 'faces': rookies.load_faces(anms_dir),
            'fonts': load_fonts(font_dir)}


# ---------------------------------------------------------------- record build
def build_record(form, pitcher, year, grp):
    """143 byte roster record of the new player: rookies.RookieGen with the random
    draws replaced by the form values. grp is the face group table (bytes)."""
    gen = rookies.RookieGen(None, faces=(len(grp), grp))
    rec = bytearray(RECORD_LEN)
    last = form['last'].encode('ascii')
    first = form['first'].encode('ascii')
    rec[rookies.OFF_LAST:rookies.OFF_LAST + len(last)] = last
    rec[rookies.OFF_FIRST:rookies.OFF_FIRST + len(first)] = first
    rec[rookies.OFF_AGE] = form['age']
    rec[rookies.OFF_YEAR] = year
    bats, throws = HANDS[form['hands']]
    face = form['face']
    rec[rookies.OFF_HAND] = ((8 if throws == 'R' else 0)
                             | (BATS_CODE[bats] << 1) | (grp[face] & 1))
    rec[rookies.OFF_POS] = 0 if pitcher else form['pos'] & 0x0F
    struct.pack_into('<H', rec, rookies.OFF_PORTRAIT, face)
    rec[rookies.OFF_EXP_CONSIST] = 0x02          # exper 0, consist 2
    position = rookies.POS_P if pitcher else form['pos']
    gen._write_stat_constants(rec, position)
    order = rookies.PITCHER_RATING_ORDER if pitcher else rookies.BATTER_RATING_ORDER
    for (_key, off, shift), v in zip(order, form['r']):
        if shift == 4:
            rookies._set_nibble_hi(rec, off, v)
        else:
            rookies._set_nibble_lo(rec, off, v)
    gen._write_salary(rec, position)
    return bytes(rec)


def season_half(rec):
    """The season record of a new player: the roster record with every season
    stat byte zeroed."""
    out = bytearray(rec)
    for off in team_fill._SEASON_STAT_OFFSETS:
        out[off] = 0
    return bytes(out)


def save_slot(st, ctx):
    """Write the new player into the team V20 in place (roster record and season
    record, nothing else) and return the updated image. Write errors are ignored."""
    slot = st['slot']
    image = st['image']
    rec = build_record(st['form'], slot < PITCHER_SLOTS, year_byte(image),
                       ctx['faces'][1])
    srec = season_half(rec)
    off_r = HEADER_LEN + RECORD_LEN * slot
    off_s = HEADER_LEN + RECORD_LEN * (slot + SEASON_BASE)
    stem = ctx['teams'][st['team']][1].encode('latin-1')
    path = v20_path(ctx['league_dir'], stem)
    if path is not None:
        try:
            with open(path, 'r+b') as fh:
                fh.seek(off_r)
                fh.write(rec)
                fh.seek(off_s)
                fh.write(srec)
        except OSError:
            pass
    img = bytearray(image)
    img[off_r:off_r + RECORD_LEN] = rec
    img[off_s:off_s + RECORD_LEN] = srec
    return bytes(img)


def control_return(path):
    """CONTROL[1] = CONTROL[0] in place, when the file has at least 2 bytes."""
    try:
        with open(path, 'r+b') as fh:
            d = fh.read(2)
            if len(d) < 2:
                return
            fh.seek(1)
            fh.write(d[0:1])
    except OSError:
        pass


# ---------------------------------------------------------------- state machine
def blank_form():
    return {'last': '', 'first': '', 'pos': 1, 'hands': 0, 'age': DEFAULT_AGE,
            'r': [DEFAULT_RATING] * 6, 'face': 0}


def default_form(image, slot, n_faces):
    """Form of a new player for slot: a batter takes the named occupant's position
    when it is 1..9, else 1; face 30 when there are more than 30 faces, else 0."""
    rec = record(image, slot)
    if slot < PITCHER_SLOTS:
        pos, r = 0, [DEFAULT_RATING, DEFAULT_RATING, 5]
    else:
        occupant = rec[rookies.OFF_POS] & 15
        pos = occupant if rec[0] and 1 <= occupant <= 9 else 1
        r = [DEFAULT_RATING] * 6
    return {'last': '', 'first': '', 'pos': pos, 'hands': 0, 'age': DEFAULT_AGE,
            'r': r, 'face': FACE_DEFAULT_N if n_faces > FACE_DEFAULT_N else 0}


def start_state():
    return {'screen': S_TEAM, 'cursor': 0, 'team': 0, 'slot': 0, 'form': blank_form(),
            'msg': 0, 'image': bytes(IMAGE_LEN)}


def _copy(st):
    out = dict(st)
    out['form'] = dict(st['form'], r=list(st['form']['r']))
    return out


def _list_key(cur, key, n):
    """Cursor after a list key over n rows (cursor stays 0 when n is 0)."""
    if n == 0:
        return 0
    if key == KEY_UP and cur > 0:
        return cur - 1
    if key == KEY_DOWN and cur < n - 1:
        return cur + 1
    if key == KEY_PGDN:
        return min(cur + ROWS_PER_PAGE, n - 1)
    if key == KEY_PGUP:
        return max(cur - ROWS_PER_PAGE, 0)
    return cur


def _edit_fields(pitcher):
    return PIT_FIELDS if pitcher else BAT_FIELDS


def _name_ok(name, mx, key):
    if len(name) >= mx or not 0 < key < 128:
        return False
    ch = chr(key)
    if ch == ' ' and name == '':
        return False
    return ch in NAME_CHARS


def _adjust(st, fld, d, ctx):
    form = st['form']
    pitcher = st['slot'] < PITCHER_SLOTS
    if fld == 'pos':
        if not pitcher:
            form['pos'] = (form['pos'] - 1 + d) % 9 + 1
    elif fld == 'hands':
        form['hands'] = (form['hands'] + d) % 6
    elif fld == 'age':
        form['age'] = min(AGE_MAX, max(AGE_MIN, form['age'] + d))
    elif fld == 'face':
        form['face'] = (form['face'] + d) % ctx['faces'][0]
    else:
        i = int(fld[1])
        cap = PIT_ENDURANCE_CAP if (pitcher and i == 2) else RATING_CAP
        form['r'][i] = min(cap, max(1, form['r'][i] + d))


def _finish_save(st, ctx):
    st['image'] = save_slot(st, ctx)
    st['screen'], st['cursor'] = S_DONE, 0


def _step_team(st, key, ctx):
    n = len(ctx['teams'])
    if key == KEY_ESC:
        return st, True
    if key == KEY_ENTER and n:
        st['team'] = st['cursor']
        st['image'] = read_v20(ctx['league_dir'], ctx['teams'][st['team']][1])
        st['screen'], st['cursor'] = S_SLOT, 0
        return st, False
    st['cursor'] = _list_key(st['cursor'], key, n)
    return st, False


def _step_slot(st, key, ctx):
    if key == KEY_ESC:
        st['screen'], st['cursor'] = S_TEAM, st['team']
        return st, False
    if key == KEY_ENTER:
        st['slot'] = st['cursor']
        st['form'] = default_form(st['image'], st['slot'], ctx['faces'][0])
        st['screen'], st['cursor'] = S_EDIT, 0
        return st, False
    st['cursor'] = _list_key(st['cursor'], key, ROSTER_SLOTS)
    return st, False


def _step_edit(st, key, ctx):
    fields = _edit_fields(st['slot'] < PITCHER_SLOTS)
    fld = fields[st['cursor']][0]
    form = st['form']
    if key == KEY_ESC:
        st['screen'], st['cursor'] = S_SLOT, st['slot']
    elif key in (KEY_UP, KEY_DOWN):
        st['cursor'] = _list_key(st['cursor'], key, len(fields))
    elif key == KEY_ENTER:
        if fld == 'save':
            if form['last'] == '':
                st['msg'] = 1
            elif record(st['image'], st['slot'])[0]:
                st['screen'], st['cursor'] = S_CONFIRM, 0
            else:
                _finish_save(st, ctx)
        else:
            st['cursor'] += 1
    elif fld in ('last', 'first'):
        mx = LAST_MAX if fld == 'last' else FIRST_MAX
        if key == KEY_BACK:
            form[fld] = form[fld][:-1]
        elif _name_ok(form[fld], mx, key):
            form[fld] += chr(key)
    elif key in (KEY_LEFT, KEY_RIGHT) and fld != 'save':
        _adjust(st, fld, -1 if key == KEY_LEFT else 1, ctx)
    return st, False


def _step_confirm(st, key, ctx):
    if key == KEY_ESC:
        st['screen'] = S_EDIT
        st['cursor'] = len(_edit_fields(st['slot'] < PITCHER_SLOTS)) - 1
    elif key == KEY_ENTER:
        _finish_save(st, ctx)
    return st, False


def _step_done(st, key, ctx):
    if key == KEY_ESC:
        return st, True
    if key == KEY_ENTER:
        st['screen'], st['cursor'] = S_TEAM, st['team']
    return st, False


_STEPS = {S_TEAM: _step_team, S_SLOT: _step_slot, S_EDIT: _step_edit,
          S_CONFIRM: _step_confirm, S_DONE: _step_done}


def step(state, key, ctx):
    """(state, exit_flag). Every key first clears msg. ESC on TEAM and on DONE
    exits; every other ESC goes back one screen."""
    st = _copy(state)
    st['msg'] = 0
    return _STEPS[st['screen']](st, key, ctx)


# ---------------------------------------------------------------- rendering
def _list_view(st, ctx):
    """(title, cols, rows, footer, highlight) of a list-style screen."""
    scr = st['screen']
    if scr == S_TEAM:
        tm = ctx['teams']
        if not tm:
            return ('CREATE A PLAYER', COLS_TEAM, [('NO TEAMS FOUND', '')], FOOT_TEAM,
                    False)
        rows = [(d, 'AMERICAN' if lg < 16 else 'NATIONAL') for lg, _s, d in tm]
        return 'CREATE A PLAYER', COLS_TEAM, rows, FOOT_TEAM, True
    if scr == S_SLOT:
        rows = []
        for s in range(ROSTER_SLOTS):
            rec = record(st['image'], s)
            if rec[0]:
                rows.append((slot_label(s), name_display(rec[0:20], 20),
                             POS_LABELS[rec[rookies.OFF_POS] & 15],
                             '%d' % rec[rookies.OFF_AGE]))
            else:
                rows.append((slot_label(s), '(EMPTY)', '', ''))
        title = 'PICK A SLOT: ' + ctx['teams'][st['team']][2]
        return title, COLS_SLOT, rows, FOOT_SLOT, True
    if scr == S_CONFIRM:
        old = record(st['image'], st['slot'])
        rows = [('THIS REPLACES ' + name_display(old[0:20], 18),),
                ('IN SLOT ' + slot_label(st['slot']) + ' OF '
                 + ctx['teams'][st['team']][2],),
                ('THE OLD PLAYER LEAVES THE LEAGUE.',)]
        return 'REPLACE PLAYER', COLS_ONE, rows, FOOT_CONFIRM, False
    f = st['form']
    who = (f['first'] + ' ' + f['last']) if f['first'] else f['last']
    rows = [('SAVED: ' + who,),
            ('TEAM: ' + ctx['teams'][st['team']][2],),
            ('SLOT: ' + slot_label(st['slot']),)]
    return 'PLAYER SAVED', COLS_ONE, rows, FOOT_DONE, False


def _draw_title(fb, bold_ft, title):
    tx = 8 + (304 - text_width(bold_ft, title)) // 2
    draw_text(fb, bold_ft, tx + 1, 11, title, C_BLACK)
    draw_text(fb, bold_ft, tx, 10, title, C_WHITE)


def _draw_list(fb, main_ft, cols, rows, cursor, hl, footer):
    rect(fb, 8, 24, 311, 33, C_HEADER_GOLD)
    for header, x, w, align in cols:
        h = header[:w]
        if align == 'R':
            draw_text(fb, main_ft, x + w * CHAR_W - text_width(main_ft, h), 26, h, C_BLACK)
        else:
            draw_text(fb, main_ft, x, 26, h, C_BLACK)
    page = cursor // ROWS_PER_PAGE
    for r in range(ROWS_PER_PAGE):
        i = page * ROWS_PER_PAGE + r
        if i >= len(rows):
            break
        y0 = 35 + r * ROW_H
        cur = hl and i == cursor
        color = C_WHITE if cur else C_BLACK
        rect(fb, 8, y0, 311, y0 + 9, C_TITLE_RED if cur else C_ROW_TAN)
        for ci, cell in enumerate(rows[i]):
            _h, x, w, align = cols[ci]
            s = cell[:w]
            if align == 'R':
                draw_text(fb, main_ft, x + w * CHAR_W - text_width(main_ft, s), y0 + 2,
                          s, color)
            else:
                draw_text(fb, main_ft, x, y0 + 2, s, color)
        rect(fb, 8, y0 + 10, 311, y0 + 10, C_GRID_GRAY)
    draw_text(fb, main_ft, 10, 185, footer, C_WHITE)


def _edit_value(st, fld, ctx, cur):
    form = st['form']
    if fld in ('last', 'first'):
        s = form[fld]
        mx = LAST_MAX if fld == 'last' else FIRST_MAX
        return s + '_' if cur and len(s) < mx else s
    if fld == 'pos':
        return POS_LABELS[form['pos']]
    if fld == 'hands':
        return 'BATS %s THROWS %s' % HANDS[form['hands']]
    if fld == 'age':
        return '%d' % form['age']
    if fld == 'face':
        return '%d OF %d' % (form['face'] + 1, ctx['faces'][0])
    if fld == 'save':
        return ''
    return '%d' % form['r'][int(fld[1])]


def _draw_edit(fb, st, ctx, main_ft, bold_ft):
    draw_panel(fb)
    _draw_title(fb, bold_ft, 'NEW PLAYER: ' + ctx['teams'][st['team']][2])
    rect(fb, 8, 24, 311, 33, C_HEADER_GOLD)
    draw_text(fb, main_ft, _cx(0), 26, 'FIELD', C_BLACK)
    draw_text(fb, main_ft, _cx(13), 26, 'VALUE', C_BLACK)
    draw_text(fb, main_ft, 236, 26, 'FACE', C_BLACK)
    fields = _edit_fields(st['slot'] < PITCHER_SLOTS)
    for r, (fld, label) in enumerate(fields):
        y0 = 35 + r * 10
        cur = r == st['cursor']
        color = C_WHITE if cur else C_BLACK
        rect(fb, 8, y0, 219, y0 + 8, C_TITLE_RED if cur else C_ROW_TAN)
        draw_text(fb, main_ft, 10, y0 + 1, label, color)
        draw_text(fb, main_ft, _cx(13), y0 + 1, _edit_value(st, fld, ctx, cur), color)
    rect(fb, 226, 35, 309, 106, C_BLACK)
    pic = portrait(ctx['anms_dir'], st['form']['face'])
    if pic is None:
        rect(fb, FACE_X, FACE_Y, FACE_X + PORTRAIT_W - 1, FACE_Y + PORTRAIT_H - 1, C_GRID_GRAY)
    else:
        w, h, px = pic
        for y in range(h):
            base = (FACE_Y + y) * FB_W + FACE_X
            fb[base:base + w] = px[y * w:(y + 1) * w]
    if st['msg'] == 1:
        draw_text(fb, main_ft, 10, 172, MSG_NAME, C_DRED)
    fld = fields[st['cursor']][0]
    foot = FOOT_NAME if fld in ('last', 'first') else (FOOT_SAVE if fld == 'save'
                                                       else FOOT_FIELD)
    draw_text(fb, main_ft, 10, 185, foot, C_WHITE)


def render(st, ctx):
    fb = bytearray(FB_SIZE)
    main_ft, bold_ft = ctx['fonts']
    if st['screen'] == S_EDIT:
        _draw_edit(fb, st, ctx, main_ft, bold_ft)
        return fb
    title, cols, rows, footer, hl = _list_view(st, ctx)
    draw_panel(fb)
    _draw_title(fb, bold_ft, title)
    _draw_list(fb, main_ft, cols, rows, st['cursor'], hl, footer)
    return fb


# ---------------------------------------------------------------- main
def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--keys', default='')
    ap.add_argument('--png', default=None)
    ap.add_argument('--raw', default=None)
    ap.add_argument('--control', default=None)
    ap.add_argument('league_dir')
    ap.add_argument('font_dir')
    ap.add_argument('anms_dir', nargs='?', default='ANMS')
    a = ap.parse_args(argv)
    ctx = load_ctx(a.league_dir, a.font_dir, a.anms_dir)
    st = start_state()
    for k in parse_keys(a.keys):
        st, _ex = step(st, k, ctx)
    fb = render(st, ctx)
    if a.png:
        write_png(a.png, fb, load_palette(os.path.join(a.font_dir, 'DEFAULT.PAL')))
    if a.raw:
        with open(a.raw, 'wb') as fh:
            fh.write(bytes(fb))
    if a.control:
        control_return(a.control)


if __name__ == '__main__':
    main(sys.argv[1:])
