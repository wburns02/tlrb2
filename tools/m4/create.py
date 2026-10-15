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
import ratings  # noqa: E402
import rookies  # noqa: E402
import rosters  # noqa: E402
import statline  # noqa: E402
import teamids  # noqa: E402
from dynview import (C_BLACK, C_WHITE, C_DRED, C_TITLE_RED, C_HEADER_GOLD,  # noqa: E402
                     C_ROW_TAN, C_GRID_GRAY, FB_SIZE, FB_W, KEY_ESC, KEY_ENTER,  # noqa: E402
                     KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_PGUP, KEY_PGDN,  # noqa: E402
                     ROW_H, ROWS_PER_PAGE, CHAR_W, _cx, draw_text, text_width,  # noqa: E402
                     rect, draw_panel, name_display, team_disp, v20_path,  # noqa: E402
                     parse_keys, load_fonts, load_palette, write_png)  # noqa: E402

# ---------------------------------------------------------------- constants
S_TEAM, S_SLOT, S_EDIT, S_CONFIRM, S_DONE, S_RELEASE = range(6)
KEY_BACK = 8

RECORD_LEN = rookies.RECORD_LEN           # 143
HEADER_LEN = 295                          # V20 header before the first record
ROSTER_SLOTS = 40                         # records 0..39; slot s is record s
SEASON_BASE = ROSTER_SLOTS                # record s + 40 is the season half of slot s
PITCHER_SLOTS = 16                        # slots 0..15 pitchers, 16..39 batters
IMAGE_LEN = HEADER_LEN + 80 * RECORD_LEN  # 11735: header + 80 records
AL_BASE, NL_BASE = 0x21d, 0x758c          # *.MAJ offsets of the AL and NL stem tables
MAJ_STEM_OFF = 0x1d7                      # first stem inside each 8 slot table
MAJ_MIN_LEN = NL_BASE + MAJ_STEM_OFF + 8 * 24      # 30755: last byte of the 24 NL stems
DEFAULT_YEAR_BYTE = 123

LAST_MAX, FIRST_MAX = 11, 7
NAME_CHARS = frozenset(string.ascii_letters + " .'-")
AGE_MIN, AGE_MAX = 18, 45
DEFAULT_AGE = 22
DEFAULT_RATING = 6
PIT_ENDURANCE_CAP = 10
RATING_CAP = 12
FACE_DEFAULT_N = 30
FACE_CUSTOM_BASE = 400                    # custom (Portrait Studio) faces are ids 400..c-1 (C14.1)
FACE_PAGE = 10                            # PGUP / PGDN step on the FACE field
FACE_X, FACE_Y = 244, 43                  # portrait pixels (48 x 56)
PORTRAIT_W, PORTRAIT_H = 48, 56

POS_LABELS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH', 'OF', 'IF',
              'OI', 'CO', 'CI', 'C3']
# (bats, throws) per hands index, as the screen shows them
HANDS = [('R', 'R'), ('L', 'L'), ('S', 'R'), ('R', 'L'), ('L', 'R'), ('S', 'L')]
BATS_CODE = {'R': 1, 'S': 2, 'L': 0}      # record byte 29 bits 2..1

# edit rows: (field, label); batter 14 rows, pitcher 10 rows
BAT_FIELDS = [('last', 'LAST NAME'), ('first', 'FIRST NAME'), ('pos', 'POSITION'),
              ('pos2', 'SECOND POS'), ('hands', 'HANDS'), ('age', 'AGE'), ('r0', 'POWER'),
              ('r1', 'BUNT'), ('r2', 'HIT AND RUN'), ('r3', 'SPEED'), ('r4', 'RANGE'),
              ('r5', 'ARM'), ('face', 'FACE'), ('save', 'SAVE PLAYER')]
PIT_FIELDS = [('last', 'LAST NAME'), ('first', 'FIRST NAME'), ('pos', 'POSITION'),
              ('hands', 'HANDS'), ('age', 'AGE'), ('r0', 'CONTROL'), ('r1', 'VELOCITY'),
              ('r2', 'ENDURANCE'), ('face', 'FACE'), ('save', 'SAVE PLAYER')]

COLS_TEAM = [('TEAM', _cx(0), 20, 'L'), ('LEAGUE', _cx(30), 12, 'L')]
COLS_SLOT = [('SLOT', _cx(0), 4, 'L'), ('PLAYER', _cx(5), 20, 'L'),
             ('POS', _cx(26), 4, 'L'), ('AGE', _cx(31), 4, 'R'),
             ('ROLE', _cx(36), 5, 'L')]
COLS_ONE = [(' ', _cx(0), 42, 'L')]

FOOT_TEAM = 'UP DOWN   ENTER PICK   ESC EXIT'
FOOT_SLOT = 'UP DOWN  ENTER NEW  C COPY  ESC TEAMS'
FOOT_RELEASE = 'Y RELEASE   N ESC BACK'
FOOT_CONFIRM = 'ENTER REPLACE   ESC BACK'
FOOT_DONE = 'ENTER CREATE ANOTHER   ESC EXIT'
FOOT_NAME = 'TYPE NAME   UP DOWN   ESC SLOTS'
FOOT_SAVE = 'ENTER SAVE   UP DOWN   ESC SLOTS'
FOOT_FIELD = 'UP DOWN LEFT RIGHT  A AUTO  N NAME  ESC'
MSG_NAME = 'TYPE A LAST NAME FIRST'
MSG_BUDGET = 'OVER THE POINT BUDGET, PRESS B'
MSG_POOL = ('POOL FULL', 'NO RESERVE')
BUDGET_BAT = (0, 36, 45, 54)              # C31: points per budget mode, batters
BUDGET_PIT = (0, 18, 24, 28)              # pitchers
BUDGET_NAMES = ('OFF', 'ROOKIE', 'REGULAR', 'STAR')


# ---------------------------------------------------------------- league data
def teams(league_dir):
    """[(id, stem, display)] in id order (C12.3). The ids are the stable ids of
    teamids.teams with the league's TEAMID.DAT (none: the engine ids). The MAJ is
    the first sorted *.MAJ of league_dir; a file shorter than MAJ_MIN_LEN has no
    teams. A stem is cut at its first NUL; a team whose stem is empty or has no
    team file is skipped."""
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
    for k, _L, _slot, st in teamids.teams(d, teamids.load_table(league_dir)):
        stem = st.split(b'\0')[0]
        if not stem or v20_path(league_dir, stem) is None:
            continue
        s = stem.decode('latin-1')
        out.append((k, s, team_disp(league_dir, s)))
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


def portrait_count(anms_dir):
    """c, PORTRAIT.ANM's frame count (first u16); 0 when the file is missing or shorter than 2 bytes."""
    try:
        with open(os.path.join(anms_dir, 'PORTRAIT.ANM'), 'rb') as fh:
            head = fh.read(2)
    except OSError:
        return 0
    return struct.unpack('<H', head)[0] if len(head) == 2 else 0


def face_walk_len(n, c):
    """Entries in the FACE list (C14.1): generic ids 0..n-1, then custom ids 400..c-1 when c > 400.
    c is capped at rookies.FACE_TABLE_MAX (BB reads PORTRAIT.ANM only below 981)."""
    if c <= FACE_CUSTOM_BASE:
        return n
    return n + min(c, rookies.FACE_TABLE_MAX) - FACE_CUSTOM_BASE


def face_pos(face, n):
    """Position of face id in the FACE list."""
    return face if face < n else n + face - FACE_CUSTOM_BASE


def face_at(pos, n):
    """Face id at position pos of the FACE list."""
    return pos if pos < n else FACE_CUSTOM_BASE + pos - n


def face_text(face, n):
    """FACE value text: '<id + 1> OF <n>' for a generic face, 'CUSTOM <id - 399>' for a custom one."""
    if face < n:
        return '%d OF %d' % (face + 1, n)
    return 'CUSTOM %d' % (face - FACE_CUSTOM_BASE + 1)


def load_ctx(league_dir, font_dir, anms_dir='ANMS'):
    return {'league_dir': league_dir, 'anms_dir': anms_dir,
            'teams': teams(league_dir), 'faces': rookies.load_faces(anms_dir),
            'anm_count': portrait_count(anms_dir), 'fonts': load_fonts(font_dir)}


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
    flag = grp[face] & 1 if face < FACE_CUSTOM_BASE else 0      # a custom face has group 0 (C14.1)
    rec[rookies.OFF_HAND] = ((8 if throws == 'R' else 0)
                             | (BATS_CODE[bats] << 1) | flag)
    if pitcher:
        rec[rookies.OFF_POS] = 0
    else:
        # C20b/C21: pos1 in the low nibble, the chosen pos2 in the high nibble.
        rec[rookies.OFF_POS] = ((form['pos2'] & 0x0F) << 4) | (form['pos'] & 0x0F)
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
    statline.fill(rec)                           # the stat line the ratings imply
    sal = ratings.salary(rec)                    # C21: the game's own salary
    struct.pack_into('<H', rec, rookies.OFF_SALARY, sal)
    return bytes(rec)


def season_half(rec):
    """The season record of a new player: the roster record with every season
    stat byte (statline.SEASON_STAT_BYTES) zeroed."""
    out = bytearray(rec)
    for off in statline.SEASON_STAT_BYTES:
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


# team header slot lists (byte ranges of the team image, each byte a slot index or 0xff)
ROLE_LISTS = (('ROT', 111, 115), ('PEN', 116, 120), ('START', 122, 157),
              ('BENCH', 194, 221), ('RES', 222, 236))


def slot_role(image, s):
    """Role of roster slot s in the team header: ROT, PEN, START, BENCH or RES, else ''."""
    for role, lo, hi in ROLE_LISTS:
        if s in image[lo:hi + 1]:
            return role
    return ''


# ---------------------------------------------------------------- release
def pool_path(league_dir, n):
    """The league's POOLn file: v20_path's find when the file exists (any case),
    else the plain uppercase path (the file that would be created)."""
    p = v20_path(league_dir, b'POOL%d' % n)
    return p if p is not None else os.path.join(league_dir, 'POOL%d.V20' % n)


def release_slot(st, ctx):
    """Release roster slot st['slot'] to the lowest free slot of the first
    POOLn (1..4) that has room. Returns ('ok', pool_path), ('pool', None) when
    every pool is full or ('res', None) when no same-type reserve could fill
    the slot's staff or lineup places. Nothing is written on a refusal; on a
    release the pool file is written whole, then the team file, write errors
    ignored (like save_slot). st['image'] and the team file take the released
    state: the slot vacated, repair applied and any leftover bench or reserve
    byte holding the slot emptied to 0xff."""
    s = st['slot']
    pitch = s < PITCHER_SLOTS
    slots = range(PITCHER_SLOTS) if pitch else range(PITCHER_SLOTS, ROSTER_SLOTS)
    target = None
    for n in (1, 2, 3, 4):
        p = pool_path(ctx['league_dir'], n)
        if os.path.isfile(p) and os.path.getsize(p) != IMAGE_LEN:
            continue
        img = bytearray(open(p, 'rb').read()) if os.path.isfile(p) \
            else rosters.pool_blank(bytearray(st['image']))
        for ps in slots:
            if not img[HEADER_LEN + RECORD_LEN * ps]:
                target = (n, p, img, ps)
                break
        if target:
            break
    if target is None:
        return 'pool', None
    n, p, pimg, ps = target
    img = bytearray(st['image'])
    rosters.vacate(img, s)
    rosters.repair(img, {s})
    if s in img[111:121] or s in img[122:158]:
        return 'res', None
    for o in range(194, 237):
        if img[o] == s:
            img[o] = 0xff
    rosters.write_pair(pimg, ps, rosters.copy_pair(bytearray(st['image']), s))
    rosters.write_pool_years(pimg, ps, 0)
    try:
        with open(p, 'wb') as fh:
            fh.write(bytes(pimg))
    except OSError:
        pass
    stem = ctx['teams'][st['team']][1].encode('latin-1')
    tp = v20_path(ctx['league_dir'], stem)
    if tp is not None:
        try:
            with open(tp, 'wb') as fh:
                fh.write(bytes(img))
        except OSError:
            pass
    st['image'] = bytes(img)
    return 'ok', n


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
    return {'last': '', 'first': '', 'pos': 1, 'pos2': rookies.POS2_OF[1],
            'hands': 0, 'age': DEFAULT_AGE, 'r': [DEFAULT_RATING] * 6, 'face': 0}


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
    return {'last': '', 'first': '', 'pos': pos, 'pos2': rookies.POS2_OF[pos],
            'hands': 0, 'age': DEFAULT_AGE,
            'r': r, 'face': FACE_DEFAULT_N if n_faces > FACE_DEFAULT_N else 0}


def copy_form(image, slot, ctx):
    """C44: form of a copy of the slot's record. Names come from the record bytes
    (NAME_CHARS filter, then cut), everything else is the record decoded and
    clamped; a face id outside the FACE list falls back to default_form's face;
    callers only copy an occupied slot."""
    rec = record(image, slot)
    last = rec[rookies.OFF_LAST:rookies.OFF_FIRST]
    first = rec[rookies.OFF_FIRST:rookies.OFF_AGE]
    def _name(b, mx):
        s = ''
        for byte in b.split(b'\0', 1)[0]:
            ch = chr(byte)
            if ch not in NAME_CHARS:
                continue
            s += ch
            if len(s) == mx:
                break
        return s
    if slot < PITCHER_SLOTS:
        pos, pos2 = 0, rookies.POS2_OF[0]
    else:
        pos1, pos2hi = rec[rookies.OFF_POS] & 15, rec[rookies.OFF_POS] >> 4
        pos = pos1 if 1 <= pos1 <= 9 else 1
        pos2 = pos2hi if 1 <= pos2hi <= 15 else rookies.POS2_OF[pos]
    hands_code = rec[rookies.OFF_HAND]
    bats_nib = hands_code >> 1 & 3
    bats = 'R' if bats_nib == 1 or bats_nib == 3 else ('S' if bats_nib == 2 else 'L')
    throws = 'R' if hands_code & 8 else 'L'
    hands = HANDS.index((bats, throws))
    age = min(AGE_MAX, max(AGE_MIN, rec[rookies.OFF_AGE]))
    order = (rookies.PITCHER_RATING_ORDER if slot < PITCHER_SLOTS
             else rookies.BATTER_RATING_ORDER)
    r = []
    for i, (_key, off, shift) in enumerate(order):
        cap = PIT_ENDURANCE_CAP if slot < PITCHER_SLOTS and i == 2 else RATING_CAP
        nib = rec[off] >> shift & 15
        r.append(1 if nib == 0 else (cap if nib > cap else nib))
    n_faces = ctx['faces'][0]
    default = default_form(image, slot, n_faces)
    face = struct.unpack('<H', rec[rookies.OFF_PORTRAIT:rookies.OFF_PORTRAIT + 2])[0]
    if face >= n_faces and not (FACE_CUSTOM_BASE <= face
                                < FACE_CUSTOM_BASE
                                + face_walk_len(n_faces, ctx['anm_count'])
                                - n_faces):
        face = default['face']
    return {'last': _name(last, LAST_MAX), 'first': _name(first, FIRST_MAX),
            'pos': pos, 'pos2': pos2, 'hands': hands, 'age': age,
            'r': r, 'face': face}


def start_state():
    return {'screen': S_TEAM, 'cursor': 0, 'team': 0, 'slot': 0, 'form': blank_form(),
            'msg': '', 'budget': 0, 'seed': 1, 'image': bytes(IMAGE_LEN)}


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
            form['pos2'] = rookies.POS2_OF[form['pos']]      # C21: reset on POSITION
    elif fld == 'pos2':
        form['pos2'] = (form['pos2'] - 1 + d) % 15 + 1
    elif fld == 'hands':
        form['hands'] = (form['hands'] + d) % 6
    elif fld == 'age':
        form['age'] = min(AGE_MAX, max(AGE_MIN, form['age'] + d))
    elif fld == 'face':
        n = ctx['faces'][0]
        size = face_walk_len(n, ctx['anm_count'])
        form['face'] = face_at((face_pos(form['face'], n) + d) % size, n)
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
    if key in (67, 99):                      # C44: copy an occupied slot's player
        if record(st['image'], st['cursor'])[0]:
            st['slot'] = st['cursor']
            st['form'] = copy_form(st['image'], st['slot'], ctx)
            st['screen'], st['cursor'] = S_EDIT, 0
        return st, False
    if key in (68, 100):                     # C69: release an occupied slot
        if record(st['image'], st['cursor'])[0]:
            st['slot'] = st['cursor']
            st['screen'] = S_RELEASE
        return st, False
    st['cursor'] = _list_key(st['cursor'], key, ROSTER_SLOTS)
    return st, False


def _step_release(st, key, ctx):
    if key == KEY_ESC or key in (78, 110):
        st['screen'], st['cursor'] = S_SLOT, st['slot']
        return st, False
    if key in (89, 121):
        how, n = release_slot(st, ctx)
        if how == 'ok':
            st['msg'] = 'RELEASED TO POOL%d' % n
            st['screen'], st['cursor'] = S_SLOT, st['slot']
        elif how == 'pool':
            st['msg'] = MSG_POOL[0]
        else:
            st['msg'] = MSG_POOL[1]
    return st, False


def _budget_spent(st):
    """Points spent: the sum of the form's ratings (C31)."""
    return sum(st['form']['r'][:3] if st['slot'] < PITCHER_SLOTS
               else st['form']['r'])


def _budget_cap(st):
    return (BUDGET_PIT if st['slot'] < PITCHER_SLOTS else BUDGET_BAT)[st['budget']]


def _autofill(st):
    """C34: key A auto-fill of the ratings from the session seed. The n ratings
    (3 on a pitcher slot) start at 1 and gain one point per seeded LCG step until
    they sum to the current mode's budget (REGULAR when the mode is OFF):
    seed = (seed * 1103515245 + 12345) % 2**31, i = (seed >> 16) % n, and a step
    adds nothing when r[i] is at its cap. st['seed'] keeps the final value, so the
    next A gives another spread. Nothing else in the state changes."""
    pitcher = st['slot'] < PITCHER_SLOTS
    n = 3 if pitcher else 6
    target = (BUDGET_PIT if pitcher else BUDGET_BAT)[st['budget'] or 2]
    r = [1] * n
    seed = st['seed']
    while sum(r) < target:
        seed = (seed * 1103515245 + 12345) % 2 ** 31
        i = (seed >> 16) % n
        cap = PIT_ENDURANCE_CAP if pitcher and i == 2 else RATING_CAP
        if r[i] < cap:
            r[i] += 1
    st['seed'] = seed
    st['form']['r'][:n] = r


def _random_name(st, ctx):
    """C68: C37, then draw again when the pick collides with a named roster
    record (slots 0..39, roster halves only) of any league team: last and
    first both equal the pick exactly (after the cut at the first 0 byte).
    Up to 8 picks in sequence; when all 8 collide the 8th is kept anyway.
    st['seed'] keeps the seed after the last draw used. The league's names are
    read once per press (_league_names)."""
    used = _league_names(st, ctx)
    seed = st['seed']
    for pick in range(8):
        seed = (seed * 1103515245 + 12345) % 2 ** 31
        last = rookies.LAST_NAMES[(seed >> 16) % len(rookies.LAST_NAMES)]
        seed = (seed * 1103515245 + 12345) % 2 ** 31
        first = rookies.FIRST_NAMES[(seed >> 16) % len(rookies.FIRST_NAMES)]
        if pick == 7 or (last.encode('ascii'), first.encode('ascii')) not in used:
            break
    st['seed'] = seed
    st['form']['last'], st['form']['first'] = last, first


def _league_names(st, ctx):
    """{(last, first)} name bytes (each cut at its first 0) of every named roster
    record (slots 0..39, byte 0 != 0) of the ctx['teams'] teams. The selected team
    (st['team'] is the list index, not the stable id) comes from st['image'];
    every other team from its V20 file, skipped when the file is missing or
    shorter than the 40 roster records (raw length, so not read_v20, which pads)."""
    need = HEADER_LEN + RECORD_LEN * ROSTER_SLOTS
    used = set()
    for i, (_k, stem, _d) in enumerate(ctx['teams']):
        if i == st['team']:
            image = st['image']
        else:
            path = v20_path(ctx['league_dir'], stem.encode('latin-1'))
            if path is None:
                continue
            try:
                with open(path, 'rb') as fh:
                    image = fh.read(need)
            except OSError:
                continue
            if len(image) < need:
                continue
        for r in range(ROSTER_SLOTS):
            rec = record(image, r)
            if rec[0]:
                used.add((bytes(rec[rookies.OFF_LAST:rookies.OFF_FIRST]).split(b'\0', 1)[0],
                          bytes(rec[rookies.OFF_FIRST:rookies.OFF_AGE]).split(b'\0', 1)[0]))
    return used


def _step_edit(st, key, ctx):
    fields = _edit_fields(st['slot'] < PITCHER_SLOTS)
    fld = fields[st['cursor']][0]
    form = st['form']
    if key == KEY_ESC:
        st['screen'], st['cursor'] = S_SLOT, st['slot']
    elif key in (KEY_UP, KEY_DOWN):
        st['cursor'] = _list_key(st['cursor'], key, len(fields))
    elif key in (66, 98) and fld not in ('last', 'first'):
        st['budget'] = (st['budget'] + 1) % 4              # C31: cycle the point budget
    elif key in (65, 97) and fld not in ('last', 'first'):
        _autofill(st)                                      # C34: the A auto-fill
    elif key in (78, 110) and fld not in ('last', 'first'):
        _random_name(st, ctx)                              # C37/C68: the N random name
    elif key == KEY_ENTER:
        if fld == 'save':
            if form['last'] == '':
                st['msg'] = 1
            elif st['budget'] and _budget_spent(st) > _budget_cap(st):
                st['msg'] = 2                              # C31: over the point budget
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
            form[fld] += chr(key).upper()      # stock names are all upper case
    elif key in (KEY_LEFT, KEY_RIGHT) and fld != 'save':
        _adjust(st, fld, -1 if key == KEY_LEFT else 1, ctx)
    elif key in (KEY_PGUP, KEY_PGDN) and fld == 'face':
        _adjust(st, fld, -FACE_PAGE if key == KEY_PGUP else FACE_PAGE, ctx)
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
          S_CONFIRM: _step_confirm, S_DONE: _step_done,
          S_RELEASE: _step_release}


def step(state, key, ctx):
    """(state, exit_flag). Every key first clears msg (0; a pool message on
    S_SLOT / S_RELEASE is a string, falsy when cleared either way). ESC on TEAM
    and on DONE exits; every other ESC goes back one screen."""
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
        rows = [(d, 'AMERICAN' if k < 16 else 'NATIONAL') for k, _s, d in tm]
        return 'CREATE A PLAYER', COLS_TEAM, rows, FOOT_TEAM, True
    if scr == S_SLOT:
        rows = []
        for s in range(ROSTER_SLOTS):
            rec = record(st['image'], s)
            if rec[0]:
                rows.append((slot_label(s), name_display(rec[0:20], 20),
                             POS_LABELS[rec[rookies.OFF_POS] & 15],
                             '%d' % rec[rookies.OFF_AGE], slot_role(st['image'], s)))
            else:
                rows.append((slot_label(s), '(EMPTY)', '', '', ''))
        title = 'PICK A SLOT: ' + ctx['teams'][st['team']][2]
        return title, COLS_SLOT, rows, FOOT_SLOT, True
    if scr == S_RELEASE:
        title, cols, rows, _foot, hl = _list_view(dict(st, screen=S_SLOT), ctx)
        return title, cols, rows, FOOT_RELEASE, hl
    if scr == S_CONFIRM:
        old = record(st['image'], st['slot'])
        rows = [('THIS REPLACES ' + name_display(old[0:20], 18),),
                ('IN SLOT ' + slot_label(st['slot']) + ' OF '
                 + ctx['teams'][st['team']][2],),
                ('THE OLD PLAYER LEAVES THE LEAGUE.',)]
        if slot_role(st['image'], st['slot']) == 'RES':
            rows.append(('RESERVE SLOT: ACTIVATE HIM TO PLAY.',))
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


# name-entry cursor: '^' draws a filled ball in MAIN.FNT; '_' draws a down arrow there
CURSOR = '^'


def _edit_value(st, fld, ctx, cur):
    form = st['form']
    if fld in ('last', 'first'):
        s = form[fld]
        mx = LAST_MAX if fld == 'last' else FIRST_MAX
        return s + CURSOR if cur and len(s) < mx else s
    if fld == 'pos':
        return POS_LABELS[form['pos']]
    if fld == 'pos2':
        return POS_LABELS[form['pos2']]
    if fld == 'hands':
        return 'BATS %s THROWS %s' % HANDS[form['hands']]
    if fld == 'age':
        return '%d' % form['age']
    if fld == 'face':
        return face_text(form['face'], ctx['faces'][0])
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
        draw_text(fb, main_ft, 10, 175, MSG_NAME, C_DRED)      # C21: 14 rows end at 173
    elif st['msg'] == 2:
        draw_text(fb, main_ft, 10, 175, MSG_BUDGET, C_DRED)    # C31: over the budget
    fld = fields[st['cursor']][0]
    foot = FOOT_NAME if fld in ('last', 'first') else (FOOT_SAVE if fld == 'save'
                                                       else FOOT_FIELD)
    draw_text(fb, main_ft, 10, 185, foot, C_WHITE)
    # C21: the salary of the record this form would save (derived, updates on every key)
    rec = build_record(st['form'], st['slot'] < PITCHER_SLOTS,
                       year_byte(st['image']), ctx['faces'][1])
    draw_text(fb, main_ft, 228, 110, 'SALARY', C_BLACK)
    draw_text(fb, main_ft, 228, 120, '%d' % ratings.salary(rec), C_BLACK)
    # C31: the point budget block
    spent, cap = _budget_spent(st), _budget_cap(st)
    off = st['budget'] == 0
    draw_text(fb, main_ft, 228, 135, 'BUDGET', C_BLACK)
    draw_text(fb, main_ft, 228, 145, BUDGET_NAMES[st['budget']] if off
              else '%d/%d' % (spent, cap), C_BLACK if (off or spent <= cap) else C_DRED)
    if not off:
        draw_text(fb, main_ft, 228, 155, BUDGET_NAMES[st['budget']], C_BLACK)


def render(st, ctx):
    fb = bytearray(FB_SIZE)
    main_ft, bold_ft = ctx['fonts']
    if st['screen'] == S_EDIT:
        _draw_edit(fb, st, ctx, main_ft, bold_ft)
        return fb
    title, cols, rows, footer, hl = _list_view(st, ctx)
    draw_panel(fb)
    _draw_title(fb, bold_ft, title)
    _draw_list(fb, main_ft, cols, rows, st['cursor'], hl,
               st['msg'] if st['msg'] and st['screen'] in (S_SLOT, S_RELEASE)
               else footer)
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
