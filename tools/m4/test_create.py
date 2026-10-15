#!/usr/bin/env python3
"""CREATE A PLAYER (tools/m4/create.py) unit tests. Run:
  python3 -m pytest -q tools/m4/test_create.py tools/m4/test_create_c.py
Synthetic league in tmp_path: LEAGUE.MAJ, team V20 files, PORTRAIT.ANM and FACEGRP.DAT.
Render tests need the stock fonts in /mnt/nvme/tlrb2/files (skipped when MAIN.FNT is
missing)."""
import copy
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import pytest

import create as cr
import dynview
import rookies
import statline
import ratings as rt
import rosters

FILES = '/mnt/nvme/tlrb2/files'
HAVE_FONTS = os.path.exists(os.path.join(FILES, 'MAIN.FNT'))
need_fonts = pytest.mark.skipif(not HAVE_FONTS, reason='MAIN.FNT missing')

MAJ_SIZE = 59771
IMAGE = 295 + 80 * 143
ENTER, ESC = dynview.KEY_ENTER, dynview.KEY_ESC
UP, DOWN = dynview.KEY_UP, dynview.KEY_DOWN
LEFT, RIGHT = dynview.KEY_LEFT, dynview.KEY_RIGHT
PGUP, PGDN = dynview.KEY_PGUP, dynview.KEY_PGDN
BACK = 8

# lg -> (stem, V20 header name); lg 17 has no header name, so it shows the stem.
# team list order (index): 0 BOS (lg 0), 1 DET (lg 2), 2 NYA (lg 15), 3 CHI (lg 16), 4 SLN
TEAM_SPEC = {0: (b'BOS', b'BOSTON'), 2: (b'DET', b'DETROIT'), 15: (b'NYA', b'YANKEES'),
             16: (b'CHI', b'CUBS'), 17: (b'SLN', b'')}


def named_rec(last, first, age, pos, year=100):
    rec = bytearray(143)
    rec[0:len(last)] = last.encode('ascii')
    rec[12:12 + len(first)] = first.encode('ascii')
    rec[20] = age
    rec[21] = year
    rec[31] = pos
    rec[23] = 5          # games, a season stat byte
    rec[37] = 3          # AB low byte, a season stat byte
    rec[74] = 0x77       # ratings area, never touched by the season half
    return bytes(rec)


def make_v20(name, recs):
    """295 byte header (name in bytes 0..13, every slot list empty: 0xff) and 80 records;
    recs = {index: bytes}."""
    img = bytearray(IMAGE)
    img[0:len(name)] = name
    img[111:237] = b'\xff' * 126
    for r, rec in recs.items():
        off = 295 + 143 * r
        img[off:off + 143] = rec
    return bytes(img)


TEAM_RECS = {
    0: {0: named_rec('Adams', 'Joe', 30, 0, 111), 16: named_rec('Baker', 'Al', 25, 5, 115)},
    2: {},
    15: {20: named_rec('Cole', 'Dan', 27, 3, 99)},
    16: {17: named_rec('Diaz', 'Ed', 33, 1)},
    17: {},
}


def make_league(d, spec=TEAM_SPEC, recs=TEAM_RECS, majs=('LEAGUE.MAJ',)):
    os.makedirs(d, exist_ok=True)
    maj = bytearray(MAJ_SIZE)
    for lg, (stem, name) in spec.items():
        base = cr.AL_BASE if lg < 16 else cr.NL_BASE
        slot = lg if lg < 16 else lg - 16
        off = base + cr.MAJ_STEM_OFF + 8 * slot
        maj[off:off + 8] = stem.ljust(8, b'\0')
        with open(os.path.join(d, stem.decode('latin-1') + '.V20'), 'wb') as fh:
            fh.write(make_v20(name, recs.get(lg, {})))
    for m in majs:
        with open(os.path.join(d, m), 'wb') as fh:
            fh.write(maj)
    return d


def patch_maj(d, off, data):
    path = os.path.join(d, 'LEAGUE.MAJ')
    maj = bytearray(open(path, 'rb').read())
    maj[off:off + len(data)] = data
    open(path, 'wb').write(bytes(maj))


def make_anms(d, n=40, frames=None, faces=None):
    """PORTRAIT.ANM with n stored 48x56 frames (pixel value depends on frame and
    offset) and a FACEGRP.DAT of len(faces) bytes (default n odd/even mix)."""
    os.makedirs(d, exist_ok=True)
    buf = bytearray(struct.pack('<H', n))
    for k in range(n):
        buf += struct.pack('<6H', 0, 56, 48, 0, 0, 0)
        buf += bytes((k * 37 + i * 7) % 256 for i in range(48 * 56))
    if frames is not None:
        buf = bytearray(frames)
    with open(os.path.join(d, 'PORTRAIT.ANM'), 'wb') as fh:
        fh.write(buf)
    if faces is None:
        faces = bytes((k * 5 + 1) % 256 for k in range(n))
    with open(os.path.join(d, 'FACEGRP.DAT'), 'wb') as fh:
        fh.write(faces)
    return d


def frame_px(k):
    return bytes((k * 37 + i * 7) % 256 for i in range(48 * 56))


def ctx_for(league, anms=None, fonts=None):
    anms = anms or os.path.join(league, 'NOANMS')
    return {'league_dir': league, 'anms_dir': anms, 'teams': cr.teams(league),
            'faces': rookies.load_faces(anms), 'anm_count': cr.portrait_count(anms), 'fonts': fonts}


def walk(ctx, keys, st=None):
    st = st or cr.start_state()
    ex = False
    for k in keys:
        st, ex = cr.step(st, k, ctx)
    return st, ex


def fonts():
    return dynview.load_fonts(FILES)


def to_slot(ctx, team):
    return walk(ctx, [DOWN] * team + [ENTER])[0]


def to_edit(ctx, team=0, slot=0):
    return walk(ctx, [DOWN] * team + [ENTER] + [DOWN] * slot + [ENTER])[0]


def typed(s):
    return [ord(c) for c in s]


# ---------------------------------------------------------------- C44: C copies a player
def slot_keys(n):
    """Team screen ENTER plus n DOWNs: the slot list with the cursor on slot n."""
    return [ENTER] + [DOWN] * n


def rec_from(img, slot):
    return cr.record(img, slot)


def test_copy_key_open_occupied_pitcher(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st, _ = walk(ctx, slot_keys(0) + [67])         # C on slot 0: Adams, Joe
    assert (st['screen'], st['cursor'], st['slot']) == (cr.S_EDIT, 0, 0)
    f = st['form']
    assert (f['last'], f['first']) == ('Adams', 'Joe')
    assert (f['pos'], f['pos2'], f['hands']) == (0, rookies.POS2_OF[0], 1)   # byte 29 = 0: L bats, L throws
    assert f['age'] == 30 and f['face'] == 0
    rec = TEAM_RECS[0][0]
    want = []
    for _key, off, shift in rookies.PITCHER_RATING_ORDER:
        nib = rec[off] >> shift & 15
        want.append(1 if nib == 0 else (12 if nib > 12 else nib))
    assert f['r'] == want


def test_copy_key_open_batter(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st, _ = walk(ctx, slot_keys(16) + [99])        # lowercase c on slot 16: Baker
    assert (st['screen'], st['cursor'], st['slot']) == (cr.S_EDIT, 0, 16)
    f = st['form']
    assert (f['last'], f['first'], f['pos'], f['pos2']) == ('Baker', 'Al', 5,
                                                            rookies.POS2_OF[5])
    assert f['age'] == 25 and f['face'] == 0


def test_copy_key_on_empty_slot_noop(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st0 = to_slot(ctx, 0)
    st, _ = walk(ctx, [DOWN], st0)                 # slot 1 empty
    st_after_down = st
    st, _ = walk(ctx, [67], st_after_down)
    assert st == st_after_down
    st, _ = walk(ctx, [99], st_after_down)
    assert st == st_after_down


def test_copy_key_enter_unchanged(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st, _ = walk(ctx, slot_keys(0) + [ENTER])
    assert st['screen'] == cr.S_EDIT
    assert (st['form']['last'], st['form']['first']) == ('', '')
    assert st['form']['r'][:2] == [6, 6]           # default_form, not the record


def test_copy_name_filter_and_cut(tmp_path):
    """A record whose name bytes hold a char outside NAME_CHARS: that char is
    dropped and the rest copied, cut to LAST_MAX."""
    rec = bytearray(143)
    rec[0:12] = b'O\'BR!ENX#1Z'
    rec[12:18] = b'M@ARY'                              # '@' refused, cut at FIRST_MAX
    img = make_v20(b'X', {16: bytes(rec)})
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    ctx['teams'] = ctx['teams'][:1]
    st = cr.start_state()
    st['image'] = img
    st['screen'], st['cursor'] = cr.S_SLOT, 16
    st, _ = cr.step(st, 67, ctx)
    assert (st['form']['last'], st['form']['first']) == ("O'BRENXZ", 'MARY')
    assert st['image'] == img                          # nothing written yet


def test_copy_rating_nibbles_clamped(tmp_path):
    """A nibble of 0 reads as 1 and a nibble over 12 as 12; the pos2 hi nibble
    0 and the sports hi nibble 15 read back per the pos2 rules."""
    rec = bytearray(143)
    rec[0] = 65                                        # C only fires on byte 0 != 0
    rec[31] = 0xF9                                     # pos1 9 (RF), pos2 hi 15 (C3)
    rec[74] = 0x0F                                     # power 15 -> 12, bunt 0 -> 1
    rec[75] = 0xC8                                     # hit_run lo 8, exp nibbles
    rec[29] = 0x24                                     # speed hi 2; bats S, throws L
    rec[27] = 5                                        # face 5 (in list)
    img = make_v20(b'X', {16: bytes(rec)})
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = cr.start_state()
    st['image'] = img
    st['screen'], st['cursor'] = cr.S_SLOT, 16
    st, _ = cr.step(st, 67, ctx)
    f = st['form']
    assert (f['r'][0], f['r'][1]) == (12, 1)
    assert f['r'][2] == 8
    assert (f['pos'], f['pos2']) == (9, 15)
    # the record's speed hi nibble is read as speed, not taken from the form
    want_speed = rec[29] >> 4 & 15
    assert want_speed == 2
    assert f['r'][3] == want_speed
    assert (f['hands'], f['face']) == (5, 5)


def test_copy_pitcher_endurance_cap(tmp_path):
    """A pitcher's endurance nibble over 10 reads as 10 (PIT_ENDURANCE_CAP); control and
    velocity cap at 12."""
    rec = bytearray(143)
    rec[0] = 65
    rec[134] = 0xFF                                    # control 15, velocity 15
    rec[135] = 0xF0                                    # endurance 15
    img = make_v20(b'X', {2: bytes(rec)})
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = cr.start_state()
    st['image'] = img
    st['screen'], st['cursor'] = cr.S_SLOT, 2
    st, _ = cr.step(st, 67, ctx)
    assert st['form']['r'][:3] == [12, 12, cr.PIT_ENDURANCE_CAP]


def test_copy_age_clamped(tmp_path):
    rec = bytearray(143)
    rec[0] = 65                                        # C only fires on byte 0 != 0
    rec[20] = 9                                        # under AGE_MIN
    img = make_v20(b'X', {17: bytes(rec)})
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = cr.start_state()
    st['image'] = img
    st['screen'], st['cursor'] = cr.S_SLOT, 17
    st, _ = cr.step(st, 67, ctx)
    assert st['form']['age'] == cr.AGE_MIN
    rec2 = bytearray(rec)
    rec2[20] = 90
    img2 = make_v20(b'X', {17: bytes(rec2)})
    st2 = cr.start_state()
    st2['image'] = img2
    st2['screen'], st2['cursor'] = cr.S_SLOT, 17
    st2, _ = cr.step(st2, 67, ctx2 := ctx)
    assert st2['form']['age'] == cr.AGE_MAX


def test_copy_face_out_of_list_default(tmp_path):
    """A face id past the list (40 with 40 faces and no customs) falls back to
    default_form's face for the slot's kind."""
    anms = make_anms(str(tmp_path / 'A'), n=40)
    ctx = ctx_for(make_league(str(tmp_path / 'L')), anms)
    assert cr.face_walk_len(40, 40) == 40              # no customs: list is 0..39
    rec = bytearray(143)
    rec[0] = 65
    rec[27] = 40                                       # u16 40: one past the list
    img = make_v20(b'X', {16: bytes(rec)})
    st = cr.start_state()
    st['image'] = img
    st['screen'], st['cursor'] = cr.S_SLOT, 16
    st, _ = cr.step(st, 67, ctx)
    assert st['form']['face'] == 30                    # default_form's face (n > 30)
    # a face inside the list is kept
    rec[27] = 7
    img2 = make_v20(b'X', {16: bytes(rec)})
    st2 = cr.start_state()
    st2['image'] = img2
    st2['screen'], st2['cursor'] = cr.S_SLOT, 16
    st2, _ = cr.step(st2, 67, ctx)
    assert st2['form']['face'] == 7


def test_copy_save_writes_copied_record(tmp_path):
    """SAVE after C rebuilds the record from the form (C10 build_record): the
    name and every rating nibble equal the copied ones, and the season half is
    the implied stat line."""
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st, _ = walk(ctx, slot_keys(16) + [67])            # copy Baker
    st, _ = walk(ctx, [DOWN] * 13 + [ENTER], st)
    assert st['screen'] == cr.S_CONFIRM
    st, _ = walk(ctx, [ENTER], st)
    assert st['screen'] == cr.S_DONE
    rec = open(os.path.join(lg, 'BOS.V20'), 'rb').read()[295 + 143 * 16:
                                                         295 + 143 * 17]
    f = st['form']
    assert (rec[0:5], rec[12:14]) == (b'Baker', b'Al')
    order = rookies.BATTER_RATING_ORDER
    got = [rec[off] >> shift & 15 for _key, off, shift in order]
    assert got == f['r']
    want = cr.build_record(f, False, cr.year_byte(cr.read_v20(lg, 'BOS')),
                           ctx['faces'][1])
    assert rec == want
    srec = open(os.path.join(lg, 'BOS.V20'), 'rb').read()[295 + 143 * 56:
                                                          295 + 143 * 57]
    assert srec == cr.season_half(want)
    assert struct.unpack('<H', rec[27:29])[0] == f['face']


def test_copy_then_edit_but_not_saved(tmp_path):
    """The copy itself never touches the team file; editing without SAVE leaves
    the V20 alone."""
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    before = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    st, _ = walk(ctx, slot_keys(0) + [67, UP, LEFT, ESC])
    assert (st['screen'], st['cursor']) == (cr.S_SLOT, 0)
    assert open(os.path.join(lg, 'BOS.V20'), 'rb').read() == before


# ---------------------------------------------------------------- teams
def test_teams_order_and_names(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    assert cr.teams(lg) == [(0, 'BOS', 'BOSTON'), (2, 'DET', 'DETROIT'),
                            (15, 'NYA', 'YANKEES'), (16, 'CHI', 'CUBS'),
                            (17, 'SLN', 'SLN')]


def test_teams_no_maj_or_short_maj(tmp_path):
    d = make_league(str(tmp_path / 'none'), majs=())
    assert cr.teams(d) == []
    d2 = make_league(str(tmp_path / 'short'), majs=())
    with open(os.path.join(d2, 'SHORT.MAJ'), 'wb') as fh:
        fh.write(bytes(cr.MAJ_MIN_LEN - 1))
    assert cr.teams(d2) == []


def test_teams_first_sorted_maj_and_missing_v20(tmp_path):
    d = make_league(str(tmp_path / 'L'), majs=('B.MAJ', 'A.MAJ'))
    assert [t[1] for t in cr.teams(d)] == ['BOS', 'DET', 'NYA', 'CHI', 'SLN']
    os.remove(os.path.join(d, 'DET.V20'))
    assert [t[1] for t in cr.teams(d)] == ['BOS', 'NYA', 'CHI', 'SLN']


def test_teams_skips_empty_and_bad_stems(tmp_path):
    d = make_league(str(tmp_path / 'L'), spec={0: (b'BOS', b'BOSTON')})
    patch_maj(d, cr.NL_BASE + cr.MAJ_STEM_OFF + 8, b'BA/D\0\0\0')   # lg 17: bad stem
    patch_maj(d, cr.NL_BASE + cr.MAJ_STEM_OFF + 16, b'NOPE\0\0\0\0')  # lg 18: no file
    assert cr.teams(d) == [(0, 'BOS', 'BOSTON')]


def test_teams_stem_cut_at_nul(tmp_path):
    d = make_league(str(tmp_path / 'L'), spec={0: (b'BOS', b'BOSTON')})
    patch_maj(d, cr.AL_BASE + cr.MAJ_STEM_OFF, b'BOS\0JUNK')
    assert cr.teams(d) == [(0, 'BOS', 'BOSTON')]


# ---------------------------------------------------------------- team screen
def test_team_keys(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st, ex = walk(ctx, [UP])
    assert (st['cursor'], ex) == (0, False)
    st, _ = walk(ctx, [DOWN] * 9)
    assert st['cursor'] == 4                       # 5 teams, clamped at the last
    st, _ = walk(ctx, [PGUP], st)
    assert st['cursor'] == 0
    st, _ = walk(ctx, [PGDN], st)
    assert st['cursor'] == 4
    st, _ = walk(ctx, [ord('x')], st)
    assert st['cursor'] == 4                       # unknown key: no change
    assert walk(ctx, [ESC])[1] is True


def test_team_enter_reads_v20(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    st, _ = walk(ctx_for(lg), [DOWN, DOWN, ENTER])     # NYA
    assert (st['screen'], st['cursor'], st['team']) == (cr.S_SLOT, 0, 2)
    assert st['image'] == cr.read_v20(lg, 'NYA')
    assert len(st['image']) == IMAGE


def test_read_v20_pads_short_file(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    with open(os.path.join(lg, 'BOS.V20'), 'r+b') as fh:
        fh.truncate(400)
    img = cr.read_v20(lg, 'BOS')
    assert len(img) == IMAGE and img[:400] == open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    assert img[400:] == bytes(IMAGE - 400)
    assert cr.read_v20(lg, 'ZZZ') == bytes(IMAGE)


def test_no_teams(tmp_path):
    d = str(tmp_path / 'none')
    os.makedirs(d)
    ctx = ctx_for(d)
    st, ex = walk(ctx, [ENTER, DOWN, PGDN])
    assert (st['screen'], st['cursor'], ex) == (cr.S_TEAM, 0, False)
    title, cols, rows, footer, hl = cr._list_view(st, ctx)
    assert rows == [('NO TEAMS FOUND', '')] and hl is False
    assert footer == 'UP DOWN   ENTER PICK   ESC EXIT'
    assert walk(ctx, [ESC])[1] is True


# ---------------------------------------------------------------- slot screen
def test_slot_rows(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_slot(ctx, 0)
    title, cols, rows, footer, hl = cr._list_view(st, ctx)
    assert title == 'PICK A SLOT: BOSTON' and hl is True
    assert len(rows) == 40
    assert rows[0] == ('P1', 'Adams, Joe', 'P', '30', '')
    assert rows[1] == ('P2', '(EMPTY)', '', '', '')
    assert rows[16] == ('B1', 'Baker, Al', 'SS', '25', '')
    assert len(cols) == 5 and cols[4][0] == 'ROLE'

    assert footer == 'UP DOWN  ENTER NEW  C COPY  ESC TEAMS'


def test_slot_keys(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_slot(ctx, 0)
    st, _ = walk(ctx, [PGDN], st)
    assert st['cursor'] == 12
    st, _ = walk(ctx, [DOWN] * 50, st)
    assert st['cursor'] == 39
    st, _ = walk(ctx, [PGDN, PGUP], st)
    assert st['cursor'] == 27
    st, _ = walk(ctx, [UP] * 60, st)
    assert st['cursor'] == 0
    st, _ = walk(ctx, [DOWN, ESC], st)
    assert (st['screen'], st['cursor'], st['team']) == (cr.S_TEAM, 0, 0)
    st, _ = walk(ctx, [DOWN, ENTER, DOWN, ESC])
    assert (st['screen'], st['cursor'], st['team']) == (cr.S_TEAM, 1, 1)


# ---------------------------------------------------------------- edit defaults
def test_defaults_pitcher_batter_empty(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    f = to_edit(ctx, 0, 0)['form']                # P1 named pitcher
    assert (f['last'], f['first'], f['pos'], f['hands'], f['age']) == ('', '', 0, 0, 22)
    assert f['r'] == [6, 6, 5] and f['face'] == 0
    assert to_edit(ctx, 0, 1)['form']['r'] == [6, 6, 5]     # P2 empty pitcher
    assert to_edit(ctx, 0, 16)['form']['pos'] == 5          # B1 named occupant: SS
    assert to_edit(ctx, 0, 16)['form']['r'] == [6] * 6
    assert to_edit(ctx, 0, 17)['form']['pos'] == 1          # B2 empty batter


def test_default_face_with_more_than_30(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg, make_anms(str(tmp_path / 'A'), n=40))
    assert to_edit(ctx, 0, 0)['form']['face'] == 30


# ---------------------------------------------------------------- name typing
def test_name_typing_rules(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 0)
    st, _ = walk(ctx, [32], st)                    # space first: refused
    assert st['form']['last'] == ''
    st, _ = walk(ctx, typed("aB1 .'-"), st)        # digit refused, others allowed
    assert st['form']['last'] == "AB .'-"
    st, _ = walk(ctx, [BACK, BACK], st)
    assert st['form']['last'] == 'AB .'
    st, _ = walk(ctx, typed('abcdefghijklmnop'), st)
    assert st['form']['last'] == 'AB .ABCDEFG'     # max 11
    st, _ = walk(ctx, [DOWN] + typed('Jo') + [32], st)
    assert st['form']['first'] == 'JO '
    st, _ = walk(ctx, typed('xxxxxxxxx'), st)
    assert st['form']['first'] == 'JO XXXX'        # max 7
    st, _ = walk(ctx, [UP, BACK, LEFT, RIGHT], st)
    assert st['form']['last'] == 'AB .ABCDEF'      # name rows ignore LEFT and RIGHT


def test_first_name_space_rule(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 0)
    st, _ = walk(ctx, [DOWN, 32], st)
    assert st['form']['first'] == ''
    st, _ = walk(ctx, typed('A') + [32], st)
    assert st['form']['first'] == 'A '


def test_backspace_only_on_name_rows(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 0)
    st, _ = walk(ctx, typed('Ab') + [DOWN, DOWN, BACK], st)  # cursor 2: POSITION
    assert st['form']['last'] == 'AB'


# ---------------------------------------------------------------- field keys
def test_position_and_hands_wrap(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 16)                       # batter, pos 5
    st, _ = walk(ctx, [DOWN, DOWN] + [RIGHT] * 5, st)
    assert (st['cursor'], st['form']['pos']) == (2, 1)
    st, _ = walk(ctx, [LEFT], st)
    assert st['form']['pos'] == 9
    st, _ = walk(ctx, [DOWN, DOWN, LEFT], st)
    assert st['form']['hands'] == 5
    st, _ = walk(ctx, [RIGHT, RIGHT], st)
    assert st['form']['hands'] == 1


def test_pitcher_pos_fixed_and_ratings_clamp(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 0)
    st, _ = walk(ctx, [DOWN, DOWN, RIGHT, LEFT], st)
    assert st['form']['pos'] == 0                  # pitcher POSITION never changes
    st, _ = walk(ctx, [DOWN, DOWN, DOWN, RIGHT], st)       # CONTROL row 5
    assert (st['cursor'], st['form']['r'][0]) == (5, 7)
    st, _ = walk(ctx, [RIGHT] * 20, st)
    assert st['form']['r'][0] == 12
    st, _ = walk(ctx, [DOWN, DOWN] + [RIGHT] * 9, st)      # ENDURANCE row 7, cap 10
    assert (st['cursor'], st['form']['r'][2]) == (7, 10)
    st, _ = walk(ctx, [LEFT] * 12, st)
    assert st['form']['r'][2] == 1


def test_batter_ratings_age_clamp(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 17)                       # empty batter, all ratings 6
    st, _ = walk(ctx, [DOWN] * 6 + [LEFT] * 10, st)        # POWER row 6
    assert st['form']['r'][0] == 1
    st, _ = walk(ctx, [DOWN] + [RIGHT] * 4, st)            # BUNT row 7: 6 -> 10
    assert st['form']['r'][1] == 10
    st, _ = walk(ctx, [RIGHT] * 5, st)
    assert st['form']['r'][1] == 12
    st, _ = walk(ctx, [DOWN] * 4, st)                      # ARM row 11
    assert (st['cursor'], st['form']['r'][5]) == (11, 6)
    st, _ = walk(ctx, [UP] * 20, st)
    assert st['cursor'] == 0
    st, _ = walk(ctx, [DOWN] * 5 + [RIGHT] * 40, st)       # AGE row 5
    assert st['form']['age'] == 45
    st, _ = walk(ctx, [LEFT] * 40, st)
    assert st['form']['age'] == 18


def test_face_cycle(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')), make_anms(str(tmp_path / 'A')))
    st = to_edit(ctx, 0, 0)                        # faces: 40 from the synthetic ANMS
    st, _ = walk(ctx, [DOWN] * 8, st)              # pitcher FACE row 8
    assert (st['cursor'], st['form']['face']) == (8, 30)
    st, _ = walk(ctx, [RIGHT] * 10, st)
    assert st['form']['face'] == 0
    st, _ = walk(ctx, [LEFT], st)
    assert st['form']['face'] == 39


def test_up_down_and_enter_moves(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 0)
    st, _ = walk(ctx, [UP], st)
    assert st['cursor'] == 0
    st, _ = walk(ctx, [ENTER], st)                 # ENTER on a field row: next row
    assert st['cursor'] == 1
    st, _ = walk(ctx, [DOWN] * 20, st)
    assert st['cursor'] == 9                       # pitcher SAVE PLAYER is row 9


def test_save_with_empty_last_name(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 0)
    st, _ = walk(ctx, [DOWN] * 9 + [ENTER], st)
    assert (st['screen'], st['msg'], st['cursor']) == (cr.S_EDIT, 1, 9)
    st, _ = walk(ctx, [UP], st)
    assert st['msg'] == 0                          # every key clears the message
    st, _ = walk(ctx, [DOWN, ENTER], st)
    assert st['msg'] == 1
    st, _ = walk(ctx, [DOWN], st)
    assert st['msg'] == 0


def test_edit_esc_back_to_slots(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st, _ = walk(ctx, [DOWN, ENTER, DOWN, ENTER, ESC])
    assert (st['screen'], st['cursor']) == (cr.S_SLOT, 1)


# ---------------------------------------------------------------- confirm and save
def test_confirm_esc_then_enter_saves(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st = to_edit(ctx, 0, 0)                        # named pitcher Adams
    st, _ = walk(ctx, typed('Smith') + [DOWN] + typed('Al') + [DOWN] * 8 + [ENTER], st)
    assert st['screen'] == cr.S_CONFIRM
    st2, ex = walk(ctx, [ESC], st)
    assert (st2['screen'], st2['cursor'], ex) == (cr.S_EDIT, 9, False)
    assert (st2['form']['last'], st2['form']['first']) == ('SMITH', 'AL')
    before = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    st3, _ = walk(ctx, [ENTER], st)
    assert st3['screen'] == cr.S_DONE
    assert open(os.path.join(lg, 'BOS.V20'), 'rb').read() != before


def test_done_screen_and_keys(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st = to_edit(ctx, 0, 17)                       # empty batter B2
    st, _ = walk(ctx, typed('Oak') + [DOWN] * 13 + [ENTER], st)
    assert st['screen'] == cr.S_DONE
    title, cols, rows, footer, hl = cr._list_view(st, ctx)
    assert (title, rows, hl) == ('PLAYER SAVED', [('SAVED: OAK',), ('TEAM: BOSTON',),
                                                  ('SLOT: B2',)], False)
    st2, ex = walk(ctx, [DOWN, ENTER], st)
    assert (st2['screen'], st2['cursor'], ex) == (cr.S_TEAM, 0, False)
    assert walk(ctx, [ESC], st)[1] is True


def test_done_first_name_in_saved_line(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 17)
    st, _ = walk(ctx, typed('Oak') + [DOWN] + typed('Ray') + [DOWN] * 11 + [ENTER], st)
    assert cr._list_view(st, ctx)[2][0] == ('SAVED: RAY OAK',)


def test_save_writes_only_two_records(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    before = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    st = to_edit(ctx, 0, 1)                        # empty pitcher P2
    st, _ = walk(ctx, typed('Ruiz') + [DOWN] + typed('Tom') + [DOWN] * 8 + [ENTER], st)
    assert st['screen'] == cr.S_DONE
    after = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    assert len(after) == len(before) and after[:295] == before[:295]
    changed = [r for r in range(80)
               if after[295 + 143 * r:295 + 143 * r + 143]
               != before[295 + 143 * r:295 + 143 * r + 143]]
    assert changed == [1, 41]
    year = cr.year_byte(cr.read_v20(lg, 'BOS'))
    assert year == 111                             # first named record: Adams
    grp = ctx['faces'][1]
    form = st['form']
    rec = cr.build_record(form, True, year, grp)
    assert after[295 + 143:295 + 286] == rec
    assert after[295 + 143 * 41:295 + 143 * 42] == cr.season_half(rec)


def test_save_image_matches_file(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st = to_edit(ctx, 0, 16)                       # named batter B1: confirm first
    st, _ = walk(ctx, typed('Lowe') + [DOWN] * 13 + [ENTER], st)
    assert st['screen'] == cr.S_CONFIRM
    st, _ = walk(ctx, [ENTER], st)
    assert st['screen'] == cr.S_DONE
    assert st['image'] == open(os.path.join(lg, 'BOS.V20'), 'rb').read()


# ---------------------------------------------------------------- record bytes
def test_build_record_batter():
    form = {'last': 'Smith', 'first': 'Al', 'pos': 4, 'pos2': rookies.POS2_OF[4],
            'hands': 2, 'age': 25,
            'r': [7, 8, 9, 10, 11, 12], 'face': 3}
    grp = rookies.default_faces()[1]
    rec = cr.build_record(form, False, 117, grp)
    assert len(rec) == 143
    assert rec[0:5] == b'Smith' and rec[5:12] == bytes(7)
    assert rec[12:14] == b'Al' and rec[14:20] == bytes(6)
    assert (rec[20], rec[21], rec[22], rec[23]) == (25, 117, 0, 140)
    assert rec[29] == 0xAD                          # speed 10 hi; S, R, group 1
    assert rec[31] == 0xC4 and rec[30] == 0x02      # pos 3B, pos2 O/I (C20b)
    assert struct.unpack('<H', rec[27:29])[0] == 3
    assert (rec[74], rec[75], rec[94]) == (0x87, 0x79, 0xBC)
    assert (rec[76], rec[134], rec[135]) == (0x78, 0x31, 0x10)
    # the stat line: 500 AB split by bats (switch: 332 per mille left)
    assert struct.unpack('<H', rec[37:39])[0] == 166
    assert struct.unpack('<H', rec[39:41])[0] == 334
    assert struct.unpack('<H', rec[25:27])[0] == 2070          # C21: ratings.salary
    # the ratings read back from the stat line
    assert (rt.power(rec), rt.hit_and_run(rec), rt.speed(rec)) == (7, 9, 10)
    assert rt.arm(rec) == 12


def test_build_record_pitcher():
    form = {'last': 'Ruiz', 'first': 'Tom', 'pos': 7, 'pos2': 0, 'hands': 4, 'age': 30,
            'r': [9, 10, 6, 0, 0, 0], 'face': 0}
    rec = cr.build_record(form, True, 117, rookies.default_faces()[1])
    assert rec[31] == 0 and rec[29] == 0x78          # hands L bats, R throws, pos 0
    assert rec[134] == 0xA9 and rec[135] == 0x64     # control 9, velocity 10, endurance 6
    assert (rec[74], rec[75], rec[94]) == (0x11, 0x01, 0x77)
    assert rec[136:141] == bytes([0x77, 0x77, 0x77, 0x77, 7])
    # IP 185.0 from endurance 6: a starter (33 GS) with 4 complete games
    assert struct.unpack('<H', rec[101:103])[0] == 1850
    assert (rt.control(rec), rt.velocity(rec), rt.endurance(rec)) == (9, 10, 6)
    assert struct.unpack('<H', rec[25:27])[0] == 2633          # C21: ratings.salary
    assert rec[30] == 0x02 and rec[21] == 117


def test_build_record_hand_combinations():
    # hands index -> (bats, throws): R R, L L, S R, R L, L R, S L; lo nibble of byte 29
    want = {0: 0xA, 1: 0x0, 2: 0xC, 3: 0x2, 4: 0x8, 5: 0x4}
    grp = bytes(30)
    for h, lo in want.items():
        form = {'last': 'A', 'first': '', 'pos': 1, 'pos2': rookies.POS2_OF[1],
                'hands': h, 'age': 20, 'r': [6] * 6, 'face': 0}
        assert (cr.build_record(form, False, 1, grp)[29] & 0x0F) == lo, h
        pit = cr.build_record(dict(form, r=[6, 6, 6]), True, 1, grp)
        assert (pit[29] & 0x0F) == lo, h
    flagged = bytes([1] + [0] * 29)
    form = {'last': 'A', 'first': '', 'pos': 1, 'pos2': rookies.POS2_OF[1],
            'hands': 0, 'age': 20, 'r': [6] * 6, 'face': 0}
    assert cr.build_record(form, False, 1, flagged)[29] & 1 == 1
    assert cr.build_record(form, False, 1, bytes(30))[29] & 1 == 0


def test_season_half_zeroes_only_season_bytes():
    form = {'last': 'Smith', 'first': 'Al', 'pos': 4, 'pos2': rookies.POS2_OF[4],
            'hands': 0, 'age': 25, 'r': [7, 8, 9, 10, 11, 12], 'face': 0}
    rec = cr.build_record(form, False, 117, rookies.default_faces()[1])
    season = cr.season_half(rec)
    offs = set(statline.SEASON_STAT_BYTES)
    assert len(offs) == 98
    for i in range(143):
        if i in offs:
            assert season[i] == 0
        else:
            assert season[i] == rec[i]


def test_build_record_pos2_by_position():
    """C20b: a saved SS carries byte 31 = 0xB5, a saved LF 0xA6, a saved
    pitcher 0x00; every batter pos2 = POS2_OF[pos] by default (C21: pos2 now comes
    from the form, whose default is POS2_OF[pos])."""
    grp = bytes(30)
    for pos in range(1, 10):
        form = {'last': 'A', 'first': '', 'pos': pos, 'pos2': rookies.POS2_OF[pos],
                'hands': 0, 'age': 22, 'r': [6] * 6, 'face': 0}
        rec = cr.build_record(form, False, 1, grp)
        assert rec[31] == ((rookies.POS2_OF[pos] << 4) | pos), pos
    form = dict(form, r=[6, 6, 6])
    rec = cr.build_record(form, True, 1, grp)
    assert rec[31] == 0
    # the pinning cases from the task
    ss = cr.build_record({'last': 'A', 'first': '', 'pos': 5, 'pos2': rookies.POS2_OF[5],
                          'hands': 0, 'age': 22, 'r': [6] * 6, 'face': 0}, False, 1, grp)
    assert ss[31] == 0xB5
    lf = cr.build_record({'last': 'A', 'first': '', 'pos': 6, 'pos2': rookies.POS2_OF[6],
                          'hands': 0, 'age': 22, 'r': [6] * 6, 'face': 0}, False, 1, grp)
    assert lf[31] == 0xA6


def test_build_record_salary_pins():
    """C21: build_record stores ratings.salary of the filled record (SS 6s 1413, all-12s
    batter 6592, pitcher 12/12/10 3685) and the chosen pos2 nibble."""
    grp = bytes(30)
    ss6 = cr.build_record({'last': 'A', 'first': '', 'pos': 5, 'pos2': rookies.POS2_OF[5],
                           'hands': 0, 'age': 22, 'r': [6] * 6, 'face': 0}, False, 1, grp)
    assert struct.unpack('<H', ss6[25:27])[0] == 1413
    big = cr.build_record({'last': 'A', 'first': '', 'pos': 5, 'pos2': rookies.POS2_OF[5],
                           'hands': 0, 'age': 22, 'r': [12] * 6, 'face': 0}, False, 1, grp)
    assert struct.unpack('<H', big[25:27])[0] == 6592
    pit = cr.build_record({'last': 'A', 'first': '', 'pos': 0, 'pos2': 0, 'hands': 0,
                           'age': 22, 'r': [12, 12, 10, 0, 0, 0], 'face': 0}, True, 1, grp)
    assert struct.unpack('<H', pit[25:27])[0] == 3685
    # a chosen pos2 of 11 (IF) on a pos 5 batter goes into the high nibble
    rec = cr.build_record({'last': 'A', 'first': '', 'pos': 5, 'pos2': 11, 'hands': 0,
                           'age': 22, 'r': [6] * 6, 'face': 0}, False, 1, grp)
    assert rec[31] == 0xB5 | (11 << 4) - 0xB0      # 0xB5's pos nibble, hi nibble 11


def test_saved_salary_matches_ratings(tmp_path):
    """A saved SS with every rating 6 stores salary 1413 at +25 in the team V20."""
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st = to_edit(ctx, 0, 16)                       # named batter B1, SS
    st, _ = walk(ctx, typed('Lowe') + [DOWN] * 13 + [ENTER, ENTER], st)
    assert st['screen'] == cr.S_DONE
    img = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    rec = img[295 + 143 * 16:295 + 143 * 17]
    assert struct.unpack('<H', rec[25:27])[0] == 1413


def _edit_value_by_label(st, ctx, label):
    fields = cr._edit_fields(st['slot'] < cr.PITCHER_SLOTS)
    idx = [f for f, _l in fields].index([f for f, l in fields if l == label][0])
    return cr._edit_value(st, fields[idx][0], ctx, False)


def test_second_pos_walk_rules(tmp_path):
    """The SECOND POS row: defaults to POS2_OF[pos] (OF 10 for LF), LEFT/RIGHT cycles
    1..15 with POS_LABELS text, ENTER moves to the next row, and changing POSITION
    resets pos2 to POS2_OF[new pos]."""
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 16)                       # batter B1, occupant SS: pos 5
    st, _ = walk(ctx, [DOWN, DOWN, DOWN], st)      # row 3: SECOND POS
    assert (st['cursor'], st['form']['pos2']) == (3, rookies.POS2_OF[5])
    assert _edit_value_by_label(st, ctx, 'SECOND POS') == cr.POS_LABELS[rookies.POS2_OF[5]]
    st, _ = walk(ctx, [RIGHT], st)                 # IF (11) -> OI (12)
    assert st['form']['pos2'] == 12
    st, _ = walk(ctx, [RIGHT] * 5, st)             # 12 + 5 wraps to 2
    assert st['form']['pos2'] == 2
    st, _ = walk(ctx, [LEFT] * 4, st)              # 2 - 4 wraps to 13
    assert st['form']['pos2'] == 13
    st, _ = walk(ctx, [LEFT] * 13, st)             # 13 - 13 = 0 wraps to 15
    assert st['form']['pos2'] == 15
    st, _ = walk(ctx, [RIGHT], st)                 # 15 + 1 wraps to 1
    assert st['form']['pos2'] == 1
    st, _ = walk(ctx, [ENTER], st)                 # ENTER moves to the next row
    assert st['cursor'] == 4
    # changing POSITION resets SECOND POS
    st, _ = walk(ctx, [UP, UP], st)                # row 2: POSITION (5)
    st, _ = walk(ctx, [RIGHT], st)                 # 5 -> 6 (LF), pos2 resets to 10
    assert (st['form']['pos'], st['form']['pos2']) == (6, rookies.POS2_OF[6])
    st, _ = walk(ctx, [DOWN], st)
    assert st['form']['pos2'] == rookies.POS2_OF[6]


def test_position_reset_second_pos_saved_bytes(tmp_path):
    """C20b/C21 through the state machine: a saved SS carries 0xB5; after RIGHT on
    POSITION (5 -> 6) a saved LF carries 0xA6; after RIGHT on SECOND POS from IF (11)
    once the high nibble is 12."""
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st = to_edit(ctx, 0, 16)                       # B1, SS, confirm first
    st, _ = walk(ctx, typed('Lowe') + [DOWN] * 13 + [ENTER, ENTER], st)
    assert st['screen'] == cr.S_DONE
    rec = open(os.path.join(lg, 'BOS.V20'), 'rb').read()[295 + 143 * 16:295 + 143 * 17]
    assert rec[31] == 0xB5
    # RIGHT on POSITION: 5 -> 6 (LF), pos2 resets to OF (10): saves 0xA6
    lg2 = make_league(str(tmp_path / 'L2'))
    ctx2 = ctx_for(lg2)
    st = to_edit(ctx2, 0, 16)
    st, _ = walk(ctx2, typed('Lowe') + [DOWN, DOWN, RIGHT] + [DOWN] * 11
                 + [ENTER, ENTER], st)
    assert st['screen'] == cr.S_DONE
    rec = open(os.path.join(lg2, 'BOS.V20'), 'rb').read()[295 + 143 * 16:295 + 143 * 17]
    assert rec[31] == 0xA6
    # LEFT twice on POSITION: 5 -> 4 -> 3 (2B), pos2 11 (IF); RIGHT on SECOND POS twice
    # gives 13 (CO): saves 0xD3
    lg3 = make_league(str(tmp_path / 'L3'))
    ctx3 = ctx_for(lg3)
    st = to_edit(ctx3, 0, 16)
    keys = typed('Lowe') + [DOWN, DOWN, LEFT, LEFT, DOWN] + [RIGHT] * 2
    keys += [DOWN] * 10
    st, _ = walk(ctx3, keys + [ENTER, ENTER], st)
    assert st['screen'] == cr.S_DONE
    rec = open(os.path.join(lg3, 'BOS.V20'), 'rb').read()[295 + 143 * 16:295 + 143 * 17]
    assert rec[0:4] == b'LOWE'
    assert rec[31] == 0xD3                        # pos 2B, pos2 CO (13)


def _header_with(path, offs):
    """Write the team V20 at path with header bytes offs = {offset: value} set."""
    with open(path, 'r+b') as fh:
        for off, v in offs.items():
            fh.seek(off)
            fh.write(bytes([v]))


def test_saved_max_ratings_read_back_from_roster(tmp_path):
    """A saved batter with every rating 12 reads back 12 from his roster record and hits
    .350 or better; a saved pitcher with control 12, velocity 12, endurance 10 reads
    back exact."""
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st = to_edit(ctx, 0, 16)                       # named batter B1, SS: confirm first
    keys = typed('Lowe') + [DOWN] * 6 + ([RIGHT] * 6 + [DOWN]) * 6 + [DOWN, DOWN] \
        + [ENTER, ENTER]
    st, _ = walk(ctx, keys, st)
    assert st['screen'] == cr.S_DONE
    img = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    rec = img[295 + 143 * 16:295 + 143 * 17]
    assert rec[0:4] == b'LOWE'                  # typed names are stored upper case
    assert (rt.power(rec), rt.hit_and_run(rec), rt.speed(rec)) == (12, 12, 12)
    assert (rt.rng(rec), rt.arm(rec)) == (12, 12)
    assert rt.s2(rec, 41) * 1000 >= 350 * rt.s2(rec, 37)
    st = to_edit(ctx, 0, 1)                        # empty pitcher P2
    keys = typed('Ruiz') + [DOWN] + typed('Tom') + [DOWN] * 4 + ([RIGHT] * 6 + [DOWN]) * 2
    keys += [RIGHT] * 6 + [DOWN] * 2 + [ENTER]
    st, _ = walk(ctx, keys, st)
    assert st['screen'] == cr.S_DONE
    img = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    rec = img[295 + 143:295 + 143 * 2]
    assert (rt.control(rec), rt.velocity(rec), rt.endurance(rec)) == (12, 12, 10)


def test_slot_role_six_outcomes():
    """Each header list gives its role, the list edges included; a slot in no list is ''."""
    img = bytearray(b'\xff' * 295)
    img[111] = 1          # ROT
    img[115] = 2          # ROT, last byte of the list
    img[116] = 3          # PEN
    img[122] = 4          # START
    img[157] = 5          # START, last byte
    img[194] = 6          # BENCH
    img[221] = 7          # BENCH, last byte
    img[222] = 8          # RES
    img[236] = 9          # RES, last byte
    want = {1: 'ROT', 2: 'ROT', 3: 'PEN', 4: 'START', 5: 'START', 6: 'BENCH', 7: 'BENCH',
            8: 'RES', 9: 'RES', 10: ''}
    for s, role in want.items():
        assert cr.slot_role(bytes(img), s) == role, s
    img[158] = 11         # just past START: no list
    img[237] = 11         # just past RES
    assert cr.slot_role(bytes(img), 11) == ''


def test_role_cell_and_reserve_confirm_row(tmp_path):
    """The ROLE cell shows the slot's role; a RES slot's confirm screen gets the fourth
    row, any other slot keeps three."""
    lg = make_league(str(tmp_path / 'L'))
    _header_with(os.path.join(lg, 'BOS.V20'), {222: 16, 111: 1})   # B1 in RES, P2 in ROT
    ctx = ctx_for(lg)
    st = to_slot(ctx, 0)
    title, cols, rows, footer, hl = cr._list_view(st, ctx)
    assert rows[16] == ('B1', 'Baker, Al', 'SS', '25', 'RES')
    assert rows[0] == ('P1', 'Adams, Joe', 'P', '30', '')
    assert rows[1] == ('P2', '(EMPTY)', '', '', '')
    st = to_edit(ctx, 0, 16)
    st, _ = walk(ctx, typed('Lowe') + [DOWN] * 13 + [ENTER], st)
    assert st['screen'] == cr.S_CONFIRM
    title, cols, rows, footer, hl = cr._list_view(st, ctx)
    assert len(rows) == 4
    assert rows[3] == ('RESERVE SLOT: ACTIVATE HIM TO PLAY.',)
    st = to_edit(ctx, 0, 0)                        # P1 is not in RES: three rows
    st, _ = walk(ctx, typed('Lowe') + [DOWN] * 13 + [ENTER], st)
    assert st['screen'] == cr.S_CONFIRM
    assert len(cr._list_view(st, ctx)[2]) == 3


def test_year_byte_rules():
    assert cr.year_byte(bytes(IMAGE)) == 123
    img = make_v20(b'X', {45: named_rec('Lee', 'Ann', 20, 1, 77), 3: named_rec('Ray', 'A', 20, 1, 9)})
    assert cr.year_byte(img) == 9                  # first named record, roster half
    img2 = make_v20(b'X', {45: named_rec('Lee', 'Ann', 20, 1, 77)})
    assert cr.year_byte(img2) == 77                # season half records count too


# ---------------------------------------------------------------- portraits and faces
def test_portrait_frames(tmp_path):
    anms = make_anms(str(tmp_path / 'A'))
    w, h, px = cr.portrait(anms, 5)
    assert (w, h) == (48, 56) and px == frame_px(5)
    assert cr.portrait(anms, 40) is None           # k past the frame count
    assert cr.portrait(str(tmp_path / 'missing'), 0) is None


def test_portrait_compressed_and_wrong_size(tmp_path):
    frames = bytearray(struct.pack('<H', 6))
    for k in range(6):
        if k == 3:
            frames += struct.pack('<6H', 0, 56, 48, 0, 0, 10) + bytes(10)
        elif k == 4:
            frames += struct.pack('<6H', 0, 56, 47, 0, 0, 0) + bytes(56 * 47)
        else:
            frames += struct.pack('<6H', 0, 56, 48, 0, 0, 0) + frame_px(k)
    anms = make_anms(str(tmp_path / 'A'), n=6, frames=bytes(frames), faces=bytes(6))
    assert cr.portrait(anms, 3) is None            # compressed frame
    assert cr.portrait(anms, 4) is None            # 47 wide
    assert cr.portrait(anms, 5)[2] == frame_px(5)  # skipping the compressed frame works


def test_portrait_short_file(tmp_path):
    anms = make_anms(str(tmp_path / 'A'))
    path = os.path.join(anms, 'PORTRAIT.ANM')
    data = open(path, 'rb').read()
    open(path, 'wb').write(data[:2 + 2 * 2700 + 100])
    assert cr.portrait(anms, 1)[2] == frame_px(1)
    assert cr.portrait(anms, 2) is None            # frame 2 cut short
    open(path, 'wb').write(b'\x05')
    assert cr.portrait(anms, 0) is None


def test_load_faces(tmp_path):
    assert rookies.load_faces(None) == rookies.default_faces()
    anms = make_anms(str(tmp_path / 'A'), n=40)
    n, grp = rookies.load_faces(anms)
    assert n == 40 and grp == bytes((k * 5 + 1) & 1 for k in range(40))
    short = make_anms(str(tmp_path / 'S'), n=40, faces=bytes(20))
    assert rookies.load_faces(short) == rookies.default_faces()
    low = make_anms(str(tmp_path / 'L'), n=25, faces=bytes(40))
    assert rookies.load_faces(low) == rookies.default_faces()
    assert rookies.load_faces(str(tmp_path / 'nope')) == rookies.default_faces()
    big = make_anms(str(tmp_path / 'B'), n=40, faces=bytes(982))
    assert rookies.load_faces(big) == rookies.default_faces()


# ---------------------------------------------------------------- face list (C14.1)
def face_edit(ctx):
    """P2 (empty pitcher) with the cursor on the FACE row (8)."""
    return walk(ctx, [DOWN] * 8, to_edit(ctx, 0, 1))[0]


def face_value(st, ctx):
    return cr._edit_value(st, 'face', ctx, False)


def test_face_walk_len_rules(tmp_path):
    assert cr.portrait_count(str(tmp_path / 'nope')) == 0
    assert cr.face_walk_len(30, 0) == 30
    assert cr.face_walk_len(97, 97) == 97
    assert cr.face_walk_len(97, 400) == 97         # c = 400 exactly: no customs
    assert cr.face_walk_len(97, 401) == 98
    assert cr.face_walk_len(97, 403) == 100
    assert cr.face_walk_len(97, 1000) == 97 + 981 - 400     # c capped at 981


def test_face_list_generic_only(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')), make_anms(str(tmp_path / 'A'), n=97))
    st = face_edit(ctx)                            # default face 30 with 97 faces
    assert st['form']['face'] == 30
    st, _ = walk(ctx, [RIGHT] * 65, st)
    assert (st['form']['face'], face_value(st, ctx)) == (95, '96 OF 97')
    st, _ = walk(ctx, [PGDN], st)                  # 95 + 10 wraps to 8
    assert (st['form']['face'], face_value(st, ctx)) == (8, '9 OF 97')
    st, _ = walk(ctx, [PGUP], st)                  # 8 - 10 wraps to 95
    assert st['form']['face'] == 95
    st, _ = walk(ctx, [RIGHT] * 2, st)             # 95 + 2 wraps to 0
    assert (st['form']['face'], face_value(st, ctx)) == (0, '1 OF 97')
    st, _ = walk(ctx, [LEFT], st)                  # 0 - 1 wraps to 96
    assert (st['form']['face'], face_value(st, ctx)) == (96, '97 OF 97')
    st, _ = walk(ctx, [PGUP], st)                  # 96 - 10
    assert st['form']['face'] == 86
    seen, st = [], face_edit(ctx)
    for _ in range(97):                            # 97 is prime: PGDN laps every face
        st, _ = walk(ctx, [PGDN], st)
        seen.append(st['form']['face'])
    assert sorted(seen) == list(range(97))


def test_face_list_with_customs(tmp_path):
    faces = bytes(1 if k == 5 else 0 for k in range(97))
    ctx = ctx_for(make_league(str(tmp_path / 'L')), make_anms(str(tmp_path / 'A'), n=403, faces=faces))
    assert (ctx['faces'][0], ctx['anm_count']) == (97, 403)
    st = face_edit(ctx)                            # default 30
    st, _ = walk(ctx, [RIGHT] * 66, st)            # 96: the last generic face
    assert face_value(st, ctx) == '97 OF 97'
    for want, text in ((400, 'CUSTOM 1'), (401, 'CUSTOM 2'), (402, 'CUSTOM 3'), (0, '1 OF 97')):
        st, _ = walk(ctx, [RIGHT], st)
        assert (st['form']['face'], face_value(st, ctx)) == (want, text)
    st, _ = walk(ctx, [PGUP], st)                  # 0 - 10 wraps to list position 90
    assert (st['form']['face'], face_value(st, ctx)) == (90, '91 OF 97')
    st, _ = walk(ctx, [RIGHT] * 7, st)             # position 97: first custom
    assert (st['form']['face'], face_value(st, ctx)) == (400, 'CUSTOM 1')
    st, _ = walk(ctx, [PGDN], st)                  # 97 + 10 wraps to 7
    assert (st['form']['face'], face_value(st, ctx)) == (7, '8 OF 97')
    st, _ = walk(ctx, [LEFT] * 8, st)              # 7 - 8 wraps to position 99
    assert (st['form']['face'], face_value(st, ctx)) == (402, 'CUSTOM 3')


def test_face_list_exactly_400_has_no_customs(tmp_path):
    anms = make_anms(str(tmp_path / 'A'), n=400, faces=bytes(97))
    ctx = ctx_for(make_league(str(tmp_path / 'L')), anms)
    assert (ctx['faces'][0], ctx['anm_count']) == (97, 400)
    st = face_edit(ctx)
    st, _ = walk(ctx, [RIGHT] * 67, st)            # 30 + 67 wraps to 0
    assert (st['form']['face'], face_value(st, ctx)) == (0, '1 OF 97')
    st, _ = walk(ctx, [PGDN], st)
    assert st['form']['face'] == 10
    st, _ = walk(ctx, [LEFT] * 11, st)             # 10 - 11 wraps to 96
    assert st['form']['face'] == 96


def test_face_keys_on_other_rows_do_nothing(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')), make_anms(str(tmp_path / 'A'), n=97))
    st = to_edit(ctx, 0, 1)
    assert walk(ctx, [PGDN, PGUP], st)[0]['form'] == st['form']          # LAST NAME row
    st4 = walk(ctx, [DOWN] * 4, st)[0]                                    # AGE row
    assert walk(ctx, [PGDN, PGUP], st4)[0]['form'] == st4['form']


def test_custom_face_record_group_and_portrait(tmp_path):
    faces = bytes(1 if k == 5 else 0 for k in range(97))
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg, make_anms(str(tmp_path / 'A'), n=403, faces=faces))
    keys = [ENTER, DOWN, ENTER] + typed('Ruiz') + [DOWN] + typed('Tom') + [DOWN] * 7
    st, _ = walk(ctx, keys + [RIGHT] * 68 + [DOWN, ENTER])        # face 401, then SAVE
    assert st['screen'] == cr.S_DONE and st['form']['face'] == 401
    rec = cr.record(st['image'], 1)
    assert struct.unpack_from('<H', rec, rookies.OFF_PORTRAIT)[0] == 401
    assert rec[rookies.OFF_HAND] & 1 == 0                         # custom face: group 0
    assert open(os.path.join(lg, 'BOS.V20'), 'rb').read()[295 + 143:295 + 286] == rec
    form5 = dict(st['form'], face=5)                              # generic face 5: flag 1
    rec5 = cr.build_record(form5, True, 100, ctx['faces'][1])
    assert struct.unpack_from('<H', rec5, rookies.OFF_PORTRAIT)[0] == 5
    assert rec5[rookies.OFF_HAND] & 1 == 1


# ---------------------------------------------------------------- CONTROL
def test_control_return(tmp_path):
    p = str(tmp_path / 'CONTROL')
    open(p, 'wb').write(bytes([1, 9, 0, 0, 0, 0, 0, 0xff, 0xff]))
    cr.control_return(p)
    assert open(p, 'rb').read() == bytes([1, 1, 0, 0, 0, 0, 0, 0xff, 0xff])
    open(p, 'wb').write(b'\x07')
    cr.control_return(p)
    assert open(p, 'rb').read() == b'\x07'
    cr.control_return(str(tmp_path / 'absent'))
    assert not os.path.exists(str(tmp_path / 'absent'))


# ---------------------------------------------------------------- all keys, all screens
ALL_KEYS = list(range(0, 128)) + [LEFT, RIGHT, UP, DOWN, PGUP, PGDN, 0x4a00, 0xe000]


def test_every_key_on_every_screen(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg, make_anms(str(tmp_path / 'A')))
    starts = [cr.start_state(), to_slot(ctx, 0), to_edit(ctx, 0, 0),
              to_edit(ctx, 0, 16)]
    st = to_edit(ctx, 0, 16)
    starts.append(walk(ctx, typed('Lowe') + [DOWN] * 12 + [ENTER], st)[0])   # confirm
    starts.append(walk(ctx, [DOWN, ENTER, ENTER] + [DOWN] * 9)[0])            # SAVE row
    for s in starts:
        for k in ALL_KEYS:
            st2, ex = cr.step(s, k, ctx)
            assert isinstance(ex, bool)
            assert st2['screen'] in range(9)


# ---------------------------------------------------------------- render
@need_fonts
def test_render_every_screen(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    anms = make_anms(str(tmp_path / 'A'))
    ctx = ctx_for(lg, anms, fonts())
    states = [cr.start_state(), to_slot(ctx, 0), to_edit(ctx, 0, 0),
              walk(ctx, [DOWN, ENTER, ENTER] + [DOWN] * 9 + [ENTER])[0]]
    for s in states:
        fb = cr.render(s, ctx)
        assert len(fb) == 64000


@need_fonts
def test_render_portrait_and_gray_box(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    anms = make_anms(str(tmp_path / 'A'))
    ctx = ctx_for(lg, anms, fonts())
    st = to_edit(ctx, 0, 0)                        # default face 30 with 40 faces
    fb = cr.render(st, ctx)
    px = frame_px(30)
    assert fb[43 * 320 + 244] == px[0] and fb[98 * 320 + 291] == px[-1]
    ctx2 = ctx_for(lg, str(tmp_path / 'none'), fonts())
    fb2 = cr.render(to_edit(ctx2, 0, 0), ctx2)
    assert fb2[43 * 320 + 244] == dynview.C_GRID_GRAY
    assert fb2[98 * 320 + 291] == dynview.C_GRID_GRAY
    assert fb2[42 * 320 + 244] == dynview.C_BLACK


@need_fonts
def test_render_edit_msg_and_cursor_row(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg, make_anms(str(tmp_path / 'A')), fonts())
    st = to_edit(ctx, 0, 0)
    st, _ = walk(ctx, [DOWN] * 9 + [ENTER], st)    # SAVE row, empty last name: msg 1
    fb = cr.render(st, ctx)
    assert fb[127 * 320 + 215] == dynview.C_TITLE_RED       # cursor row, right of text
    assert any(fb[y * 320 + x] == dynview.C_DRED
               for y in range(172, 179) for x in range(10, 200))


# ---------------------------------------------------------------- C31: point budget
def test_budget_module_tables():
    assert cr.BUDGET_BAT == (0, 36, 45, 54) and cr.BUDGET_PIT == (0, 18, 24, 28)
    assert cr.BUDGET_NAMES == ('OFF', 'ROOKIE', 'REGULAR', 'STAR')
    assert cr.MSG_BUDGET == 'OVER THE POINT BUDGET, PRESS B'


def test_budget_cycle_on_rating_field(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 17)                       # empty batter, POWER row next
    st, _ = walk(ctx, [DOWN] * 6 + [66, 98], st)
    assert st['budget'] == 2                       # 0 -> 1 -> 2
    st, _ = walk(ctx, [66, 66], st)
    assert st['budget'] == 0                       # 3 wraps to OFF
    st2 = to_edit(ctx, 0, 17)                      # survives every screen change
    st2, _ = walk(ctx, [DOWN] * 6 + [98, ESC, DOWN, ENTER], st2)
    assert (st2['screen'], st2['budget']) == (cr.S_EDIT, 1)
    st3, _ = walk(ctx, [DOWN] * 13 + [ENTER], st2)  # save attempt with no name
    assert st3['screen'] == cr.S_EDIT
    st3, _ = walk(ctx, [ESC, ESC, ENTER, DOWN, ENTER], st3)   # back to a fresh slot
    assert (st3['screen'], st3['budget']) == (cr.S_EDIT, 1)


def test_budget_b_typed_in_names(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 17)
    st, _ = walk(ctx, [66, 98], st)                # LAST NAME row: letters, not the mode
    assert (st['budget'], st['form']['last']) == (0, 'BB')
    st, _ = walk(ctx, [DOWN, 66, 98, UP], st)      # FIRST NAME row too
    assert (st['budget'], st['form']['first']) == (0, 'BB')


def test_budget_spent_defaults(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    assert cr._budget_spent(to_edit(ctx, 0, 17)) == 36     # default batter: 6 * 6
    # pitcher spent = r0 + r1 + r2. blank_form is 6 + 6 + 6 = 18; an edit screen's
    # default_form starts ENDURANCE at 5, so 17.
    assert cr._budget_spent(to_edit(ctx, 0, 1)) == 17
    assert cr._budget_spent(dict(cr.start_state(), slot=1, form=cr.blank_form())) == 18


@need_fonts
def test_budget_star_saves_rookie_refused(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg, fonts=fonts())
    before = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    st = to_edit(ctx, 0, 17)                       # empty batter B2
    st, _ = walk(ctx, typed('Oak') + [DOWN] * 6, st)       # cursor on POWER (row 6)
    st, _ = walk(ctx, [98] + [RIGHT] * 6 + [DOWN] * 7 + [ENTER], st)   # ROOKIE mode
    # spent 42 > 36: refused, msg 2, nothing written
    assert (st['screen'], st['msg'], st['budget']) == (cr.S_EDIT, 2, 1)
    assert open(os.path.join(lg, 'BOS.V20'), 'rb').read() == before
    fb = cr.render(st, ctx)
    assert any(fb[y * 320 + x] == dynview.C_DRED
               for y in range(172, 179) for x in range(10, 250))
    st, _ = walk(ctx, [LEFT], st)                  # the next key clears msg 2
    assert st['msg'] == 0
    st, _ = walk(ctx, [98, 98], st)                # STAR (cap 54): the form now saves
    st, _ = walk(ctx, [DOWN] * 7 + [ENTER], st)
    assert st['screen'] == cr.S_DONE
    img = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    assert img != before
    assert cr.record(img, 17)[74] & 0x0f == 12     # POWER 12 written
    st, _ = walk(ctx, [ENTER], st)                 # CREATE ANOTHER keeps the mode
    assert (st['screen'], st['budget']) == (cr.S_TEAM, 3)
    st, _ = walk(ctx, [ENTER, ENTER], st)
    assert (st['screen'], st['budget']) == (cr.S_EDIT, 3)


def test_budget_empty_name_msg1_wins(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 17)                       # ROOKIE, no name, spent 42 over 36
    st, _ = walk(ctx, [DOWN] * 6 + [98] + [RIGHT] * 6 + [DOWN] * 7 + [ENTER], st)
    assert (st['msg'], st['screen']) == (1, cr.S_EDIT)     # the empty name check runs first


def test_budget_off_save_identical(tmp_path):
    """Mode OFF: an all-12s form (over every non-OFF batter budget) still saves, and the
    record equals build_record of the walked form."""
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st = to_edit(ctx, 0, 17)
    keys = typed('Oak') + [DOWN] * 6 + ([RIGHT] * 6 + [DOWN]) * 6 + [DOWN, ENTER]
    st, _ = walk(ctx, keys, st)
    assert (st['screen'], st['budget']) == (cr.S_DONE, 0)
    rec = open(os.path.join(lg, 'BOS.V20'), 'rb').read()[295 + 143 * 17:295 + 143 * 18]
    grp = ctx['faces'][1]
    form = cr.blank_form()
    form.update({'last': 'OAK', 'r': [12] * 6})
    want = cr.build_record(form, False, cr.year_byte(cr.read_v20(lg, 'BOS')), grp)
    assert rec == want

# ---------------------------------------------------------------- C34: A auto-fill
A_KEY, A_ALT = 65, 97                              # key A on the edit screen


def _no_seed_r(st):
    """Snapshot of a state with the seed and the ratings values removed."""
    import copy
    out = copy.deepcopy(st)
    out.pop('seed')
    out['form'].pop('r')
    return out


def _no_seed_r_names(st):
    """Snapshot of a state with the seed, the ratings and the typed names removed."""
    out = _no_seed_r(st)
    out['form'].pop('last')
    out['form'].pop('first')
    return out


def test_autofill_batter_each_mode(tmp_path):
    """A on a batter rating field fills to the mode's budget (REGULAR when OFF), every
    rating lands in 1..12, the seed carries the draw, and nothing else changes."""
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    for b, target, seed, r in ((0, 45, 429995104, [8, 5, 6, 10, 6, 10]),
                               (1, 36, 1686638315, [8, 4, 4, 9, 4, 7]),
                               (2, 45, 429995104, [8, 5, 6, 10, 6, 10]),
                               (3, 54, 1675280054, [9, 6, 10, 12, 6, 11])):
        st = to_edit(ctx, 0, 17)
        st, _ = walk(ctx, [DOWN] * 6 + [66] * b, st)   # POWER row, mode b
        before = _no_seed_r(st)
        st2, _ = walk(ctx, [A_ALT], st)
        assert st2['form']['r'] == r and st2['seed'] == seed, b
        assert all(1 <= v <= 12 for v in r), b
        assert st2['budget'] == b
        assert _no_seed_r(st2) == before, b            # cursor, msg, budget, names as before


def test_autofill_twice_different(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 17)
    st, _ = walk(ctx, [DOWN] * 6 + [A_ALT], st)        # OFF: REGULAR target 45
    assert (st['seed'], st['form']['r']) == (429995104, [8, 5, 6, 10, 6, 10])
    st, _ = walk(ctx, [A_KEY], st)                     # the next A draws another spread
    assert (st['seed'], st['form']['r']) == (1495896251, [9, 8, 7, 6, 9, 6])


def test_autofill_pitcher_star_caps_and_keeps_r3(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 0)                            # P1 pitcher
    st, _ = walk(ctx, [DOWN] * 5 + [66] * 3 + [A_KEY], st)   # CONTROL row, STAR
    assert (st['seed'], st['form']['r']) == (1303003706, [12, 7, 9])
    assert sum(st['form']['r']) == 28 and st['form']['r'][2] <= 10
    # a pitcher-slot form with 6 ratings: r[3..5] untouched
    st = dict(cr.start_state(), screen=cr.S_EDIT, slot=1, budget=3,
              form=cr.blank_form())
    st2, _ = walk(ctx, [DOWN] * 5 + [A_ALT], st)
    assert st2['form']['r'] == [12, 7, 9, 6, 6, 6] and st2['seed'] == 1303003706


def test_autofill_a_types_in_name_fields(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 16)
    st, _ = walk(ctx, [A_KEY], st)
    assert (st['form']['last'], st['seed'], st['budget']) == ('A', 1, 0)
    st, _ = walk(ctx, [DOWN, A_ALT, UP], st)
    assert (st['form']['first'], st['form']['last'], st['seed']) == ('A', 'A', 1)


def test_autofill_save_under_regula_no_msg2(tmp_path):
    """A under REGULAR: spent == cap 45, so SAVE saves (no msg 2)."""
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    before = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    st = to_edit(ctx, 0, 17)
    st, _ = walk(ctx, typed('Oak') + [DOWN] * 6 + [66, 66, A_ALT] + [DOWN] * 7
                 + [ENTER], st)
    assert (st['screen'], st['msg']) == (cr.S_DONE, 0)
    assert open(os.path.join(lg, 'BOS.V20'), 'rb').read() != before


def test_autofill_seed_survives_create_another(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 17)
    st, _ = walk(ctx, typed('Oak') + [DOWN] * 6 + [A_ALT] + [DOWN] * 7 + [ENTER], st)
    assert st['seed'] == 429995104
    st, _ = walk(ctx, [ENTER], st)                     # CREATE ANOTHER
    st, _ = walk(ctx, [ENTER, ENTER], st)              # back into an edit screen
    assert (st['screen'], st['seed']) == (cr.S_EDIT, 429995104)
    st, _ = walk(ctx, [DOWN] * 5 + [A_KEY], st)        # the next A draws from it
    assert (st['seed'], st['form']['r']) == (127474245, [9, 6, 9])


def test_foot_field_text_c37():
    """C37: the rating-field footer gained 'N NAME' (and lost a LEFT gap); the other
    footers are unchanged (C44: FOOT_SLOT gained C COPY)."""
    assert cr.FOOT_FIELD == 'UP DOWN LEFT RIGHT  A AUTO  N NAME  ESC'
    assert len(cr.FOOT_FIELD) == 39
    assert cr.FOOT_NAME == 'TYPE NAME   UP DOWN   ESC SLOTS'
    assert cr.FOOT_SAVE == 'ENTER SAVE   UP DOWN   ESC SLOTS'
    assert cr.FOOT_TEAM == 'UP DOWN   ENTER PICK   ESC EXIT'
    assert cr.FOOT_SLOT == 'UP DOWN  ENTER NEW  C COPY  ESC TEAMS'
    assert cr.FOOT_CONFIRM == 'ENTER REPLACE   ESC BACK'
    assert cr.FOOT_DONE == 'ENTER CREATE ANOTHER   ESC EXIT'


# ---------------------------------------------------------------- C37: N random name
N_KEY, N_ALT = 78, 110                             # key N on the edit screen


def _lcg(seed):
    return (seed * 1103515245 + 12345) % 2 ** 31


def test_random_name_batter_picks_from_pools(tmp_path):
    """N on a batter rating field picks last then first from the rookie pools with
    the session LCG (expected picks computed from the seed before the press), the
    seed advances twice, and nothing else changes."""
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    for nk in (N_KEY, N_ALT):
        st = to_edit(ctx, 0, 17)
        st, _ = walk(ctx, [DOWN] * 6, st)             # POWER row
        seed = st['seed']
        seed1 = _lcg(seed)
        want_last = rookies.LAST_NAMES[(seed1 >> 16) % len(rookies.LAST_NAMES)]
        seed2 = _lcg(seed1)
        want_first = rookies.FIRST_NAMES[(seed2 >> 16) % len(rookies.FIRST_NAMES)]
        st2, _ = walk(ctx, [nk], st)
        assert st2['form']['last'] == want_last, nk
        assert st2['form']['first'] == want_first, nk
        assert st2['seed'] == seed2, nk              # the seed advanced twice
        assert len(want_last) <= cr.LAST_MAX and len(want_first) <= cr.FIRST_MAX
        assert _no_seed_r_names(st2) == _no_seed_r_names(st), nk \
            # cursor, msg, budget, ratings as before


def test_random_name_second_n_gives_next_pick(tmp_path):
    """A second N gives the next pool entry the LCG picks from the kept seed."""
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 17)
    st, _ = walk(ctx, [DOWN] * 6 + [N_KEY], st)
    seed1, last1, first1 = st['seed'], st['form']['last'], st['form']['first']
    seed2 = _lcg(seed1)                            # the second N's last-name draw
    st, _ = walk(ctx, [N_ALT], st)
    seed3 = _lcg(seed2)                            # its first-name draw, then kept
    want_last = rookies.LAST_NAMES[(seed2 >> 16) % len(rookies.LAST_NAMES)]
    want_first = rookies.FIRST_NAMES[(seed3 >> 16) % len(rookies.FIRST_NAMES)]
    assert (st['seed'], st['form']['last'], st['form']['first']) == (seed3, want_last,
                                                                     want_first)
    assert (st['form']['last'], st['form']['first']) != (last1, first1)


def test_random_name_n_types_on_name_fields(tmp_path):
    """N on 'last' (and on 'first') types the letter N and leaves the seed alone."""
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 16)
    st, _ = walk(ctx, [N_KEY], st)
    assert (st['form']['last'], st['seed']) == ('N', 1)
    st, _ = walk(ctx, [110, DOWN, N_ALT], st)
    assert (st['form']['last'], st['form']['first'], st['seed']) == ('NN', 'N', 1)


def test_random_name_then_save_writes_picked_name(tmp_path):
    """After N, SAVE writes the picked name into the V20 record (bytes 0..11 last,
    12..19 first) and the ratings stay the form defaults N never touched."""
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st = to_edit(ctx, 0, 17)                          # empty batter B2, slot 17
    st, _ = walk(ctx, [DOWN] * 6 + [N_KEY] + [DOWN] * 7 + [ENTER], st)
    assert st['screen'] == cr.S_DONE
    rec = cr.record(st['image'], 17)
    want = st['form']['last'].encode('ascii')
    wantf = st['form']['first'].encode('ascii')
    assert rec[0:12] == want.ljust(12, b'\0')
    assert rec[12:20] == wantf.ljust(8, b'\0')
    assert (rec[74], rec[75] & 0xF, rec[29] >> 4, rec[94]) == (0x66, 6, 6, 0x66)


def test_random_name_leaves_ratings_cursor_budget(tmp_path):
    """N on every non-name row of both forms leaves ratings, cursor and budget
    untouched (N is only the name pick)."""
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    for slot, rows in ((17, 14), (0, 10)):
        st = to_edit(ctx, 0, slot)
        st, _ = walk(ctx, [DOWN] * 2, st)
        for row in range(2, rows):
            assert st['cursor'] == row
            before = _no_seed_r_names(st)
            st2, _ = walk(ctx, [N_KEY], st)
            assert _no_seed_r_names(st2) == before, (slot, row)
            if row + 1 < rows:
                st, _ = walk(ctx, [DOWN], st)
                assert st['cursor'] == row + 1


# ---------------------------------------------------------------- C68: unique name
def _picks(n):
    """The first n C37 (last, first) picks from seed 1 and the seed after them:
    pick 1 is ('Russell', 'Marvin'), the seed it leaves is 377401575."""
    out = []
    seed = 1
    for _ in range(n):
        seed = _lcg(seed)
        last = rookies.LAST_NAMES[(seed >> 16) % len(rookies.LAST_NAMES)]
        seed = _lcg(seed)
        first = rookies.FIRST_NAMES[(seed >> 16) % len(rookies.FIRST_NAMES)]
        out.append((last, first))
    return out, seed


def test_random_name_skips_planted_other_team_c68(tmp_path):
    """C68: N on a non-name row skips a pick that equals a named roster record of
    another league team (planted in DET slot 20) and keeps exactly the second
    pick with its seed; a clean league keeps the C37 pick byte-identical."""
    picks, _ = _picks(2)
    assert picks[0] == ('Russell', 'Marvin')
    assert _picks(1)[1] == 377401575
    recs = {**TEAM_RECS, 2: {**TEAM_RECS[2], 20: named_rec('Russell', 'Marvin', 25, 4)}}
    ctx = ctx_for(make_league(str(tmp_path / 'L'), recs=recs))
    st = to_edit(ctx, 0, 0)                        # P1 of BOS, the selected team
    st, _ = walk(ctx, [DOWN] * 2 + [N_KEY], st)    # POSITION row, one N press
    assert (st['form']['last'], st['form']['first']) != ('Russell', 'Marvin')
    assert (st['form']['last'], st['form']['first']) == picks[1]
    assert st['seed'] == _lcg(_lcg(377401575))     # the seed after the kept draw
    ctx2 = ctx_for(make_league(str(tmp_path / 'clean')))
    st2 = to_edit(ctx2, 0, 0)
    st2, _ = walk(ctx2, [DOWN] * 2 + [N_KEY], st2)
    assert (st2['form']['last'], st2['form']['first'], st2['seed']) \
        == ('Russell', 'Marvin', 377401575)        # collision-free: C37 unchanged


def test_random_name_plant_variants_c68(tmp_path):
    """C68: a plant in the SELECTED team's own image collides too; with all of
    pick1..pick8 planted in another team the 8th pick is kept after 16 draws;
    N typed on a name row is still the letter, seed untouched."""
    picks, seed8 = _picks(8)
    recs = {**TEAM_RECS, 0: {**TEAM_RECS[0], 1: named_rec('Russell', 'Marvin', 25, 0)}}
    ctx = ctx_for(make_league(str(tmp_path / 'self'), recs=recs))
    st = to_edit(ctx, 0, 1)                        # P2, the plant sits in the image
    st, _ = walk(ctx, [DOWN] * 2 + [N_KEY], st)
    assert (st['form']['last'], st['form']['first']) == picks[1]
    assert st['seed'] == _lcg(_lcg(377401575))
    recs8 = {**TEAM_RECS, 2: {20 + i: named_rec(p[0], p[1], 25, 4)
                              for i, p in enumerate(picks)}}
    ctx8 = ctx_for(make_league(str(tmp_path / 'all'), recs=recs8))
    st8 = to_edit(ctx8, 0, 0)
    st8, _ = walk(ctx8, [DOWN] * 2 + [N_KEY], st8)
    assert (st8['form']['last'], st8['form']['first']) == picks[7]
    assert st8['seed'] == seed8
    ctx3 = ctx_for(make_league(str(tmp_path / 'plain')))
    st3 = to_edit(ctx3, 0, 0)
    st3, _ = walk(ctx3, [N_KEY], st3)              # cursor still on LAST NAME
    assert (st3['form']['last'], st3['form']['first'], st3['seed']) == ('N', '', 1)



def test_random_name_selected_team_is_the_list_index_c68(tmp_path):
    """C68 (brain): st['team'] is the team list index, not the stable id. With ids
    0, 2, 15, 16, 17 the selected NYA (index 2, id 15) is checked from its image and
    DET (index 1, id 2) from its file: a plant in DET's file collides, and a plant
    only in the in-memory NYA image collides; a deleted DET file is skipped."""
    picks, _ = _picks(2)
    recs = {**TEAM_RECS, 2: {20: named_rec('Russell', 'Marvin', 25, 4)}}
    ctx = ctx_for(make_league(str(tmp_path / 'det'), recs=recs))
    st = to_edit(ctx, 2, 0)
    st, _ = walk(ctx, [DOWN] * 2 + [N_KEY], st)
    assert (st['form']['last'], st['form']['first']) == picks[1]
    ctx2 = ctx_for(make_league(str(tmp_path / 'img')))
    st2 = to_edit(ctx2, 2, 0)
    img = bytearray(st2['image'])
    img[295 + 143 * 30:295 + 143 * 31] = named_rec('Russell', 'Marvin', 25, 4)
    st2['image'] = bytes(img)
    st2, _ = walk(ctx2, [DOWN] * 2 + [N_KEY], st2)
    assert (st2['form']['last'], st2['form']['first']) == picks[1]
    os.remove(os.path.join(str(tmp_path / 'det'), 'DET.V20'))
    st3 = to_edit(ctx, 2, 0)
    st3, _ = walk(ctx, [DOWN] * 2 + [N_KEY], st3)
    assert (st3['form']['last'], st3['form']['first']) == picks[0]

def write_table(d, entries):
    """TEAMID.DAT of d: entries = {k: stem} (k 0..31), every other entry NUL."""
    tab = bytearray(256)
    for k, stem in entries.items():
        tab[8 * k:8 * k + len(stem)] = stem
    with open(os.path.join(d, 'TEAMID.DAT'), 'wb') as fh:
        fh.write(bytes(tab))


def test_teams_no_table_engine_ids(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    assert [t[0] for t in cr.teams(lg)] == [0, 2, 15, 16, 17]


def test_teams_table_gives_stable_ids(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    write_table(lg, {7: b'bos', 3: b'DET', 14: b'NYA', 20: b'CHI', 19: b'SLN'})
    assert cr.teams(lg) == [(3, 'DET', 'DETROIT'), (7, 'BOS', 'BOSTON'),
                            (14, 'NYA', 'YANKEES'), (19, 'SLN', 'SLN'),
                            (20, 'CHI', 'CUBS')]


def test_teams_table_skips_unlisted_stem(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    write_table(lg, {0: b'BOS', 2: b'DET', 15: b'NYA', 20: b'CHI'})
    assert cr.teams(lg) == [(0, 'BOS', 'BOSTON'), (2, 'DET', 'DETROIT'),
                            (15, 'NYA', 'YANKEES'), (20, 'CHI', 'CUBS')]


def test_teams_bad_table_size_counts_as_missing(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    write_table(lg, {7: b'BOS'})
    with open(os.path.join(lg, 'TEAMID.DAT'), 'r+b') as fh:
        fh.truncate(255)
    assert [t[0] for t in cr.teams(lg)] == [0, 2, 15, 16, 17]


def test_teams_reads_through_last_nl_stem(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    with open(os.path.join(lg, 'LEAGUE.MAJ'), 'r+b') as fh:
        fh.truncate(cr.MAJ_MIN_LEN)
    assert [t[0] for t in cr.teams(lg)] == [0, 2, 15, 16, 17]
    with open(os.path.join(lg, 'LEAGUE.MAJ'), 'r+b') as fh:
        fh.truncate(cr.MAJ_MIN_LEN - 1)
    assert cr.teams(lg) == []


def test_team_rows_label_by_id(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    write_table(lg, {7: b'BOS', 3: b'DET', 14: b'NYA', 20: b'CHI', 19: b'SLN'})
    _t, _c, rows, _f, _h = cr._list_view(cr.start_state(), ctx_for(lg))
    assert [r[1] for r in rows] == ['AMERICAN'] * 3 + ['NATIONAL'] * 2


def test_team_enter_reads_stable_id_row(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    write_table(lg, {7: b'BOS', 3: b'DET', 14: b'NYA', 20: b'CHI', 19: b'SLN'})
    st, _ = walk(ctx_for(lg), [ENTER])
    assert (st['screen'], st['team']) == (cr.S_SLOT, 0)
    assert st['image'] == cr.read_v20(lg, 'DET')


# ---------------------------------------------------------------- C69: D releases a player to the pool
def rel_league(d, pools=None, mut=None):
    """League with BOS slot 0 = Adams (P), slot 1 = Bloh (P); the header,
    otherwise all-0xff slot lists, holds slot 0 in ROT (+111) and slot 1 in
    the reserves (+222), so releasing slot 0 has a same-type reserve. pools =
    {name: bytes} POOL files written as-is; mut(d) rewrites BOS.V20 last."""
    import tempfile
    base = make_league(d, recs={
        0: {0: named_rec('Adams', 'Joe', 30, 0), 1: named_rec('Bloh', 'R', 26, 0)},
        2: {}, 15: {}, 16: {}, 17: {}})
    img = bytearray(open(os.path.join(base, 'BOS.V20'), 'rb').read())
    img[111:237] = b'\xff' * 126
    img[111] = 0                       # ROT holds slot 0
    img[222] = 1                       # reserves hold slot 1
    open(os.path.join(base, 'BOS.V20'), 'wb').write(bytes(img))
    for name, b in (pools or {}).items():
        open(os.path.join(base, name), 'wb').write(b)
    if mut:
        mut(base)
    return base


def add_b1(base):
    """Named batter Baker (1B) in slot 16, held by the bench (+194) and the
    reserves list (after the pitcher, +223)."""
    img = bytearray(open(os.path.join(base, 'BOS.V20'), 'rb').read())
    img[295 + 143 * 16:295 + 143 * 17] = bytearray(named_rec('Baker', 'Al', 25, 2))
    img[194] = 16
    img[223] = 16
    open(os.path.join(base, 'BOS.V20'), 'wb').write(bytes(img))


def pool_img(name=b'FULL', n_pit=0, n_bat=0, size=295 + 80 * 143):
    b = bytearray(size)
    b[0:14] = name.ljust(14, b'\0')[:14]
    for s in range(n_pit):
        b[295 + 143 * s] = 80
    for s in range(16, 16 + n_bat):
        b[295 + 143 * s] = 80
    return bytes(b)


def rel_walk(ctx, keys, st=None):
    return walk(ctx, keys, st)


def test_c69_d_open_and_keys(tmp_path):
    """D on an occupied slot opens S_RELEASE with the cursor's slot; d works
    too; D on an empty slot is a no-op; N and ESC return to S_SLOT on the
    slot; other keys are no-ops."""
    lg = rel_league(str(tmp_path / 'L'), mut=add_b1)
    ctx = ctx_for(lg)
    st, _ = walk(ctx, slot_keys(0) + [68])
    assert (st['screen'], st['slot'], st['cursor']) == (cr.S_RELEASE, 0, 0)
    # the row text of the highlighted slot is unchanged: rows equal S_SLOT's
    assert cr._list_view(st, ctx)[:3] == cr._list_view(dict(st, screen=cr.S_SLOT), ctx)[:3]
    assert cr._list_view(st, ctx)[3] == cr.FOOT_RELEASE
    st2, _ = walk(ctx, [ord('x')], st)
    assert st2 == st
    st3, _ = walk(ctx, [ord('N')], st)
    assert (st3['screen'], st3['cursor'], st3['msg']) == (cr.S_SLOT, 0, 0)
    st4, _ = walk(ctx, slot_keys(0) + [100, ESC])
    assert (st4['screen'], st4['cursor']) == (cr.S_SLOT, 0)
    before = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    st5 = to_slot(ctx, 0)
    walk(ctx, [DOWN, DOWN], st5)                 # slot 2 empty
    st6, _ = walk(ctx, [DOWN, DOWN], to_slot(ctx, 0))
    st7, _ = walk(ctx, [68], st6)
    assert st7 == st6
    assert open(os.path.join(lg, 'BOS.V20'), 'rb').read() == before


def test_c69_release_bench_batter_pool1(tmp_path):
    """Release of a bench batter with POOL1 missing: POOL1 created from
    pool_blank, the pair at slot 16 (record 16 and 56), byte 141 = 0 in both
    halves, the team slot vacated, and the header equal to vacate + repair
    (its leftover bench / reserve bytes holding 16 are 0xff)."""
    lg = rel_league(str(tmp_path / 'L'), mut=add_b1)
    ctx = ctx_for(lg)
    pre = bytearray(open(os.path.join(lg, 'BOS.V20'), 'rb').read())
    st, _ = walk(ctx, slot_keys(16) + [ord('D'), ord('Y')])
    assert (st['screen'], st['cursor'], st['msg']) == (cr.S_SLOT, 16,
                                                       'RELEASED TO POOL1')
    pool = open(os.path.join(lg, 'POOL1.V20'), 'rb').read()
    # the pool: a blank built from the team image with the released pair at
    # slot 16 and pool years 0 in both halves
    want = bytearray(rosters.pool_blank(pre))
    rosters.write_pair(want, 16, rosters.copy_pair(pre, 16))
    rosters.write_pool_years(want, 16, 0)
    assert pool == bytes(want)
    assert pool[295 + 141] == 0 and pool[295 + 143 * 56 + 141] == 0
    # the team: the header = vacate + repair with leftovers 0xff; the slot's
    # two records zeroed; the rest of the image untouched
    team = bytearray(open(os.path.join(lg, 'BOS.V20'), 'rb').read())
    ref = bytearray(pre)
    rosters.vacate(ref, 16)
    rosters.repair(ref, {16})
    for o in range(194, 237):
        if ref[o] == 16:
            ref[o] = 0xff
    assert team[:237] == bytes(ref[:237])
    assert team[295 + 143 * 16] == 0 and team[295 + 143 * 56] == 0
    assert team[237:295] == pre[237:295]
    assert team[295:295 + 143 * 16] == pre[295:295 + 143 * 16]
    assert team[295 + 143 * 17:] == pre[295 + 143 * 17:]


def test_c69_release_lineup_starter_reserve_fills(tmp_path):
    """A lineup starter (SLOT list holds him at a lineup byte with a DEF
    position) is released; a same-type reserve REPLACES him in the lineup
    places (repair) and the header equals vacate + repair."""
    def mut(base):
        # starter Cole (CF, slot 17) in both no-DH/DH away/home leadoffs;
        # reserve Dusty (CF-capable, slot 18) in the reserves list
        img = bytearray(open(os.path.join(base, 'BOS.V20'), 'rb').read())
        for o in (122, 131, 140, 149):
            img[o] = 17                       # r1 of each lineup
            img[o + 158 - 122] = 7            # DEF position 7 (CF) at +36..
        img[295 + 143 * 17:295 + 143 * 18] = bytearray(
            named_rec('Cole', 'Dan', 27, 7))
        img[295 + 143 * 18:295 + 143 * 19] = bytearray(
            named_rec('Dusty', 'Ray', 24, 7))
        img[224] = 18                         # reserves hold 17? no: 18
        img[222] = 1                          # the pitcher reserve from rel_league
        img[223] = 17                         # the starter is a reserve too
        img[225] = 0xff
        open(os.path.join(base, 'BOS.V20'), 'wb').write(bytes(img))
    lg = rel_league(str(tmp_path / 'L'), mut=mut)
    ctx = ctx_for(lg)
    pre = bytearray(open(os.path.join(lg, 'BOS.V20'), 'rb').read())
    st, _ = walk(ctx, slot_keys(17) + [ord('D'), ord('Y')])
    assert (st['screen'], st['msg']) == (cr.S_SLOT, 'RELEASED TO POOL1')
    pool = bytearray(open(os.path.join(lg, 'POOL1.V20'), 'rb').read())
    want = bytearray(rosters.pool_blank(pre))
    rosters.write_pair(want, 16, rosters.copy_pair(pre, 17))
    rosters.write_pool_years(want, 16, 0)
    assert bytes(pool) == bytes(want)
    team = bytearray(open(os.path.join(lg, 'BOS.V20'), 'rb').read())
    ref = bytearray(pre)
    rosters.vacate(ref, 17)
    rosters.repair(ref, {17})
    for o in range(194, 237):
        if ref[o] == 17:
            ref[o] = 0xff
    assert team[:237] == bytes(ref[:237])
    # a same-type reserve took every lineup place: no lineup byte holds 17
    assert 17 not in team[122:158]
    # the pair is gone from the team
    assert team[295 + 143 * 17] == 0 and team[295 + 143 * 57] == 0


def test_c69_pool1_full_uses_pool2(tmp_path):
    """POOL1 full of batters: a released batter lands in POOL2, POOL1's bytes
    unchanged, and the message names POOL2."""
    lg = rel_league(str(tmp_path / 'L'),
                    pools={'POOL1.V20': pool_img(n_bat=24)}, mut=add_b1)
    ctx = ctx_for(lg)
    pre = bytearray(open(os.path.join(lg, 'BOS.V20'), 'rb').read())
    st, _ = walk(ctx, slot_keys(16) + [ord('D'), ord('Y')])
    assert st['msg'] == 'RELEASED TO POOL2'
    pool2 = bytearray(open(os.path.join(lg, 'POOL2.V20'), 'rb').read())
    pool1 = bytearray(open(os.path.join(lg, 'POOL1.V20'), 'rb').read())
    # POOL2 was missing: a blank built from the team image, the released pair
    # at its lowest free batter slot (16), pool years 0
    want = bytearray(rosters.pool_blank(pre))
    rosters.write_pair(want, 16, rosters.copy_pair(pre, 16))
    rosters.write_pool_years(want, 16, 0)
    assert bytes(pool2) == bytes(want)
    # POOL1 (a full image with its 24 batter slots occupied) is unchanged
    assert bytes(pool1) == pool_img(n_bat=24)


def test_c69_all_pools_full_pool_full_no_writes(tmp_path):
    """All four pools hold 16 pitchers: a released pitcher labels POOL FULL,
    stays on S_RELEASE (Y repeats it), N backs out, and both files are
    unchanged."""
    lg = rel_league(str(tmp_path / 'L'),
                    pools={'POOL%d.V20' % i: pool_img(n_pit=16)
                           for i in (1, 2, 3, 4)})
    ctx = ctx_for(lg)
    pre = bytearray(open(os.path.join(lg, 'BOS.V20'), 'rb').read())
    pool_bytes = {i: open(os.path.join(lg, 'POOL%d.V20' % i), 'rb').read()
                  for i in (1, 2, 3, 4)}
    st, _ = walk(ctx, slot_keys(0) + [ord('D'), ord('Y'), ord('Y'), ord('N')])
    assert (st['screen'], st['cursor']) == (cr.S_SLOT, 0)
    assert open(os.path.join(lg, 'BOS.V20'), 'rb').read() == bytes(pre)
    for i in (1, 2, 3, 4):
        assert open(os.path.join(lg, 'POOL%d.V20' % i), 'rb').read() == pool_bytes[i]
    # Y again on a fresh release shows POOL FULL and stays on S_RELEASE
    st3, _ = walk(ctx, [ord('D')], st)
    st4, _ = walk(ctx, [ord('Y')], st3)
    assert st4['msg'] == 'POOL FULL' and st4['screen'] == cr.S_RELEASE


def test_c69_no_reserve_refused(tmp_path):
    """A starter (staff) with no same-type reserve anywhere: NO RESERVE, no
    file changes, and the state stays on S_RELEASE."""
    def mut(base):
        img = bytearray(open(os.path.join(base, 'BOS.V20'), 'rb').read())
        img[222] = 0xff                  # drop the pitcher reserve
        open(os.path.join(base, 'BOS.V20'), 'wb').write(bytes(img))
    lg = rel_league(str(tmp_path / 'L'), mut=mut)
    ctx = ctx_for(lg)
    before_bos = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    st, _ = walk(ctx, slot_keys(0) + [ord('D'), ord('Y')])
    assert (st['screen'], st['msg']) == (cr.S_RELEASE, 'NO RESERVE')
    assert open(os.path.join(lg, 'BOS.V20'), 'rb').read() == before_bos
    assert not os.path.exists(os.path.join(lg, 'POOL1.V20'))
    # the next key clears the message
    st2, _ = walk(ctx, [78], st)
    assert st2['msg'] == 0 and st2['screen'] == cr.S_SLOT


def test_c69_wrong_size_pool_skipped_and_unchanged(tmp_path):
    """A 100-byte POOL1 is not a candidate and is left byte-identical; the
    release lands in POOL2."""
    lg = rel_league(str(tmp_path / 'L'),
                    pools={'POOL1.V20': bytes(100)}, mut=add_b1)
    ctx = ctx_for(lg)
    pre = bytearray(open(os.path.join(lg, 'BOS.V20'), 'rb').read())
    st, _ = walk(ctx, slot_keys(16) + [ord('D'), ord('Y')])
    assert st['msg'] == 'RELEASED TO POOL2'
    assert open(os.path.join(lg, 'POOL1.V20'), 'rb').read() == bytes(100)
    pool2 = bytearray(open(os.path.join(lg, 'POOL2.V20'), 'rb').read())
    want = bytearray(rosters.pool_blank(pre))
    rosters.write_pair(want, 16, rosters.copy_pair(pre, 16))
    rosters.write_pool_years(want, 16, 0)
    assert bytes(pool2) == bytes(want)


def test_c69_msg_replaces_footer_and_clears(tmp_path):
    """On S_SLOT the released message replaces the footer text; any next key
    clears it first."""
    lg = rel_league(str(tmp_path / 'L'), mut=add_b1)
    ctx = ctx_for(lg, fonts=fonts()) if HAVE_FONTS else ctx_for(lg)
    st, _ = walk(ctx, slot_keys(0) + [ord('D'), ord('Y')])
    assert st['msg'] == 'RELEASED TO POOL1'
    st2, _ = walk(ctx, [RIGHT], st)      # any key clears the message first
    assert (st2['msg'], st2['screen']) == (0, cr.S_SLOT)


# ---------------------------------------------------------------- C76: T trades a player
import v20 as v20mod          # noqa: E402

TRADES_TXT = 'TRADES.TXT'
T_KEY, Y_KEY, N_KEY = ord('T'), ord('Y'), ord('N')


def _rated(last, first, age, pos1, pos2=0, **ratings):
    """A named record: ratings by v20 field name, position byte pos1 | pos2 << 4."""
    rec = bytearray(143)
    rec[0:len(last)] = last.encode('ascii')
    rec[12:12 + len(first)] = first.encode('ascii')
    rec[20] = age
    rec[21] = 100
    rec[31] = pos1 | (pos2 << 4)
    for k, v in ratings.items():
        v20mod._set(rec, *v20mod.F[k], v)
    return bytes(rec)


def _bat(last, first, v, pos2=0):
    """A 28 year old 1B (age 28: no age weight, no discount, so V = S = 3 power + 3 hit_run
    + speed + range) whose rosters.value is exactly v."""
    for p in range(15, -1, -1):
        for h in range(16):
            for s in range(16):
                rg = v - 3 * p - 3 * h - s
                if 0 <= rg <= 15:
                    rec = _rated(last, first, 28, 2, pos2, power=p, hit_run=h, speed=s, range=rg)
                    assert rosters.value(rec) == v
                    return rec
    raise AssertionError(v)


def _pit(last, first, v, end):
    """A 28 year old pitcher: V = 3 control + 3 velocity + 2 endurance = v."""
    rem, mod = divmod(v - 2 * end, 3)
    assert mod == 0 and rem >= 0
    c = min(15, rem)
    rec = _rated(last, first, 28, 0, control=c, velocity=rem - c, endurance=end)
    assert rosters.value(rec) == v
    return rec


def _pair(slot, rec):
    """roster record at slot and a distinct season twin at slot + 40."""
    srec = bytearray(rec)
    srec[23], srec[37], srec[38] = 99, slot, 5
    return {slot: rec, slot + 40: bytes(srec)}


def _team(*pairs):
    out = {}
    for p in pairs:
        out.update(p)
    return out


def _patch_hdr(path, edits):
    img = bytearray(open(path, 'rb').read())
    for off, v in edits.items():
        img[off] = v
    open(path, 'wb').write(bytes(img))


# team A = BOS (list index 0), team B = DET (list index 1, index 0 of the trade team list)
def trade_league(d, a, b, a_hdr=None, b_hdr=None, others=None, **kw):
    """others = {lg: recs} for NYA (15), CHI (16), SLN (17)."""
    recs = {0: a, 2: b, 15: {}, 16: {}, 17: {}}
    recs.update(others or {})
    lg = make_league(d, recs=recs, **kw)
    if a_hdr:
        _patch_hdr(os.path.join(lg, 'BOS.V20'), a_hdr)
    if b_hdr:
        _patch_hdr(os.path.join(lg, 'DET.V20'), b_hdr)
    return lg


def trade_keys(give, get, a=0, b=0, tail=()):
    """Team list ENTER (team a), slot give, T, trade team list row b, ENTER, slot get, ENTER."""
    return ([DOWN] * a + [ENTER] + [DOWN] * give + [T_KEY] + [DOWN] * b + [ENTER]
            + [DOWN] * get + [ENTER] + list(tail))


def read_file(lg, name):
    return open(os.path.join(lg, name), 'rb').read()


def expected_trade(a_img, give, b_img, get):
    """The two team images after the accepted trade (the C76 rule, on the pre-images)."""
    a, b = bytearray(a_img), bytearray(b_img)
    px, py = rosters.copy_pair(a, give), rosters.copy_pair(b, get)
    rosters.vacate(a, give)
    rosters.vacate(b, get)
    rosters.write_pair(a, give, py)
    rosters.write_pair(b, get, px)
    rosters.repair(a, {give})
    rosters.repair(b, {get})
    return bytes(a), bytes(b)


def snapshot(lg):
    return {n: read_file(lg, n) for n in sorted(os.listdir(lg))}


# standard fixture: A batters 16 (V40), 17 (V40), 18 (V30); A pitchers 0 (V40)
# B batters 16 (V70), 17 (V66), 18 (V62) the top 3, 19 (V40), 20 (V45), 21 (V30), all 1B
A_BATTERS = _team(_pair(16, _bat('Axe', 'Al', 40)), _pair(17, _bat('Bell', 'Bo', 40)),
                  _pair(18, _bat('Cobb', 'Cy', 30)), _pair(0, _pit('Dunn', 'Di', 40, 2)))
B_BATTERS = _team(_pair(16, _bat('Egan', 'Ed', 70)), _pair(17, _bat('Fox', 'Fay', 66)),
                  _pair(18, _bat('Gil', 'Gus', 62)), _pair(19, _bat('Hart', 'Hal', 40)),
                  _pair(20, _bat('Ivy', 'Ian', 45)), _pair(21, _bat('Jay', 'Jo', 30)))


OTHER_TEAMS = {15: _team(_pair(16, _bat('Nya', 'Ned', 40))),
               16: _team(_pair(16, _bat('Chi', 'Cal', 40))),
               17: _team(_pair(16, _bat('Sln', 'Sid', 40)))}


def std_league(d, **kw):
    return trade_league(d, A_BATTERS, B_BATTERS, others=OTHER_TEAMS, **kw)


def test_c76_t_opens_trade_team_list(tmp_path):
    """T and t on an occupied slot set st['give'] and open S_TRADE_TEAM with the cursor on row
    0; the slot list's own slot / form are untouched."""
    ctx = ctx_for(std_league(str(tmp_path / 'L')))
    for key in (T_KEY, ord('t')):
        st, _ = walk(ctx, slot_keys(17) + [key])
        assert (st['screen'], st['give'], st['cursor']) == (cr.S_TRADE_TEAM, 17, 0)
    base, _ = walk(ctx, slot_keys(17))
    assert base['screen'] == cr.S_SLOT


def test_c76_t_on_empty_slot_is_noop(tmp_path):
    ctx = ctx_for(std_league(str(tmp_path / 'L')))
    st0, _ = walk(ctx, slot_keys(1))                       # slot 1 is empty
    assert not cr.record(st0['image'], 1)[0]
    st, _ = walk(ctx, [T_KEY], st0)
    assert st == dict(st0, msg=0)
    st, _ = walk(ctx, [ord('t')], st0)
    assert st == dict(st0, msg=0)


def test_c76_trade_team_list_excludes_a(tmp_path):
    """The list is every team but A, in list order; the cursor moves like S_TEAM's."""
    ctx = ctx_for(std_league(str(tmp_path / 'L')))
    st, _ = walk(ctx, slot_keys(16) + [T_KEY])
    title, cols, rows, foot, hl = cr._list_view(st, ctx)
    assert cols == cr.COLS_TEAM and hl and foot == cr.FOOT_TRADE_TEAM
    assert [r[0] for r in rows] == ['DETROIT', 'YANKEES', 'CUBS', 'SLN']
    assert [r[1] for r in rows] == ['AMERICAN', 'AMERICAN', 'NATIONAL', 'NATIONAL']
    for keys, want in (([DOWN], 1), ([DOWN] * 9, 3), ([DOWN, UP, UP], 0), ([PGDN], 3),
                       ([PGDN, PGUP], 0), ([ord('x')], 0)):
        assert walk(ctx, keys, st)[0]['cursor'] == want
    # A = NYA (list index 2): the list is BOS, DET, CHI, SLN
    st, _ = walk(ctx, [DOWN, DOWN] + slot_keys(16) + [T_KEY])
    assert st['screen'] == cr.S_TRADE_TEAM and st['team'] == 2
    assert [r[0] for r in cr._list_view(st, ctx)[2]] == ['BOSTON', 'DETROIT', 'CUBS', 'SLN']


def test_c76_trade_team_enter_loads_b(tmp_path):
    lg = std_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st, _ = walk(ctx, slot_keys(16) + [T_KEY, ENTER])
    assert (st['screen'], st['cursor'], st['bteam']) == (cr.S_TRADE_PICK, 0, 1)
    assert st['bimage'] == cr.read_v20(lg, 'DET')
    for row, idx in ((1, 2), (2, 3), (3, 4)):
        st, _ = walk(ctx, slot_keys(16) + [T_KEY] + [DOWN] * row + [ENTER])
        assert st['bteam'] == idx and st['bimage'] == cr.read_v20(lg, ctx['teams'][idx][1])
    # A = CHI (index 3): the list is BOS, DET, NYA, SLN, so row 2 is NYA (2) and row 3 SLN (4)
    for row, idx in ((2, 2), (3, 4)):
        st, _ = walk(ctx, [DOWN] * 3 + slot_keys(16) + [T_KEY] + [DOWN] * row + [ENTER])
        assert st['team'] == 3 and st['bteam'] == idx


def test_c76_trade_team_esc_returns_to_slot_on_give(tmp_path):
    ctx = ctx_for(std_league(str(tmp_path / 'L')))
    st, _ = walk(ctx, slot_keys(17) + [T_KEY, DOWN, DOWN, ESC])
    assert (st['screen'], st['cursor'], st['give']) == (cr.S_SLOT, 17, 17)
    assert st['image'] == walk(ctx, slot_keys(17))[0]['image']


def test_c76_no_other_team(tmp_path):
    """A league of one team: the trade team list says NO TEAMS FOUND and ENTER does nothing."""
    lg = make_league(str(tmp_path / 'L'), spec={0: (b'BOS', b'BOSTON')}, recs={0: A_BATTERS})
    ctx = ctx_for(lg)
    st, _ = walk(ctx, slot_keys(16) + [T_KEY])
    title, cols, rows, foot, hl = cr._list_view(st, ctx)
    assert rows == [('NO TEAMS FOUND', '')] and not hl
    st2, _ = walk(ctx, [ENTER, DOWN, PGDN], st)
    assert st2['screen'] == cr.S_TRADE_TEAM and st2['cursor'] == 0
    st3, _ = walk(ctx, [ESC], st2)
    assert (st3['screen'], st3['cursor']) == (cr.S_SLOT, 16)


def test_c76_trade_pick_rows_are_b_slots_read_only(tmp_path):
    """B's 40 slots as S_SLOT draws them; keys other than the list keys, ENTER and ESC do
    nothing, ENTER on an empty slot does nothing."""
    lg = std_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st, _ = walk(ctx, slot_keys(16) + [T_KEY, ENTER])
    title, cols, rows, foot, hl = cr._list_view(st, ctx)
    ref = cr._list_view(dict(st, screen=cr.S_SLOT, image=st['bimage'], team=1), ctx)
    assert (title, cols, rows, hl) == ref[:3] + (ref[4],) and title == 'PICK A SLOT: DETROIT'
    assert foot == cr.FOOT_TRADE_PICK and len(rows) == 40
    assert rows[16][1] == 'Egan, Ed' and rows[1] == ('P2', '(EMPTY)', '', '', '')
    before = snapshot(lg)
    for key in (T_KEY, ord('t'), ord('D'), ord('C'), ord('x'), ord('Y'), 0x1234):
        assert walk(ctx, [key], st)[0] == dict(st, msg=0)
    # an empty slot: ENTER does nothing
    st2, _ = walk(ctx, [DOWN], st)
    assert not cr.record(st2['bimage'], 1)[0]
    st3, _ = walk(ctx, [ENTER], st2)
    assert (st3['screen'], st3['cursor']) == (cr.S_TRADE_PICK, 1)
    assert snapshot(lg) == before
    # list keys
    assert walk(ctx, [PGDN], st)[0]['cursor'] == 12
    assert walk(ctx, [PGDN] * 9, st)[0]['cursor'] == 39
    assert walk(ctx, [DOWN, UP, UP], st)[0]['cursor'] == 0


def test_c76_trade_pick_enter_and_esc(tmp_path):
    ctx = ctx_for(std_league(str(tmp_path / 'L')))
    st, _ = walk(ctx, slot_keys(16) + [T_KEY, ENTER] + [DOWN] * 19 + [ENTER])
    assert (st['screen'], st['get'], st['give']) == (cr.S_TRADE_OFFER, 19, 16)
    # ESC returns to the team list with the cursor on B's row (A = BOS: B row = bteam - 1)
    for row in range(4):
        st, _ = walk(ctx, slot_keys(16) + [T_KEY] + [DOWN] * row + [ENTER, DOWN, ESC])
        assert (st['screen'], st['cursor'], st['bteam']) == (cr.S_TRADE_TEAM, row, row + 1)
    # A = SLN (index 4): every team is below A, so B's row = bteam
    st, _ = walk(ctx, [DOWN] * 4 + slot_keys(16) + [T_KEY, DOWN, DOWN, ENTER, ESC])
    assert (st['screen'], st['cursor'], st['bteam']) == (cr.S_TRADE_TEAM, 2, 2)


def test_c76_offer_screen_and_keys(tmp_path):
    ctx = ctx_for(std_league(str(tmp_path / 'L')))
    st, _ = walk(ctx, trade_keys(17, 19))
    title, cols, rows, foot, hl = cr._list_view(st, ctx)
    assert cols == cr.COLS_ONE and not hl and foot == 'Y PROPOSE   N ESC BACK'
    assert rows == [('GIVE Bo Bell',), ('GET  Hal Hart',)]
    assert foot == cr.FOOT_TRADE_OFFER
    for key in (N_KEY, ord('n'), ESC):
        st2, _ = walk(ctx, [key], st)
        assert (st2['screen'], st2['cursor'], st2['get']) == (cr.S_TRADE_PICK, 19, 19)
        assert st2['give'] == 17 and st2['image'] == st['image']
    for key in (ord('x'), ENTER, UP, DOWN, T_KEY, ord('D'), 0x1234):
        assert walk(ctx, [key], st)[0] == dict(st, msg=0)
    # back on the pick list, ENTER on another slot re-opens the offer
    st3, _ = walk(ctx, [N_KEY, DOWN, ENTER], st)
    assert (st3['screen'], st3['get']) == (cr.S_TRADE_OFFER, 20)
    assert cr._list_view(st3, ctx)[2][1] == ('GET  Ian Ivy',)


def test_c76_accept_batter_for_batter_exact_bytes(tmp_path):
    """A's slot 17 (Bell) for B's slot 19 (Hart), equal V: both V20 files equal the C76 rule
    (copy_pair / vacate / write_pair / repair), the TRADES.TXT line is exact and the state is
    on S_SLOT with TRADE ACCEPTED."""
    hdr_a = {122: 17, 158: 2, 222: 18}              # lineup spot holds 17, 1B; reserve 18
    hdr_b = {194: 19, 222: 21}                      # bench holds 19; reserve 21
    lg = std_league(str(tmp_path / 'L'), a_hdr=hdr_a, b_hdr=hdr_b)
    ctx = ctx_for(lg)
    a0, b0 = read_file(lg, 'BOS.V20'), read_file(lg, 'DET.V20')
    st, _ = walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))
    ea, eb = expected_trade(a0, 17, b0, 19)
    a1, b1 = read_file(lg, 'BOS.V20'), read_file(lg, 'DET.V20')
    assert (a1, b1) == (ea, eb)
    assert (st['screen'], st['cursor'], st['msg']) == (cr.S_SLOT, 17, 'TRADE ACCEPTED')
    assert st['image'] == a1
    assert read_file(lg, TRADES_TXT) == b'TRADE 1 BOS Bo Bell DET Hal Hart\r\n'
    # what moved: A's slot 17 holds Hart (both halves), B's slot 19 holds Bell
    ro = lambda img, s: img[295 + 143 * s:295 + 143 * (s + 1)]       # noqa: E731
    assert ro(a1, 17) == ro(b0, 19) and ro(a1, 57) == ro(b0, 59)
    assert ro(b1, 19) == ro(a0, 17) and ro(b1, 59) == ro(a0, 57)
    assert ro(a1, 17)[0:20].rstrip(b'\0') .startswith(b'Hart')
    # the repair: A's lineup spot now holds the reserve 18, the reserve list holds 17;
    # B's bench holds 21 and its reserves 19
    assert a1[122] == 18 and a1[222] == 17
    assert b1[194] == 21 and b1[222] == 19
    # nothing else changed in either image beyond the slot pair and the header lists
    for pre, post, s in ((a0, a1, 17), (b0, b1, 19)):
        keep = [i for i in range(len(pre)) if not (295 + 143 * s <= i < 295 + 143 * (s + 1)
                or 295 + 143 * (s + 40) <= i < 295 + 143 * (s + 41) or 111 <= i < 237)]
        assert all(pre[i] == post[i] for i in keep)


def test_c76_repair_leaves_unfillable_header_bytes(tmp_path):
    """No reserve to replace the slot: repair leaves the lineup / bench bytes pointing at the
    slot (now the other team's player), the trade is not refused, and the files equal the
    rule's."""
    lg = std_league(str(tmp_path / 'L'), a_hdr={122: 17, 158: 2, 194: 17},
                    b_hdr={194: 19})
    ctx = ctx_for(lg)
    a0, b0 = read_file(lg, 'BOS.V20'), read_file(lg, 'DET.V20')
    st, _ = walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))
    ea, eb = expected_trade(a0, 17, b0, 19)
    assert st['msg'] == 'TRADE ACCEPTED'
    assert (read_file(lg, 'BOS.V20'), read_file(lg, 'DET.V20')) == (ea, eb)
    assert ea[122] == 17 and ea[194] == 17 and eb[194] == 19


def test_c76_accept_pitcher_for_pitcher_moves_pairs(tmp_path):
    a = _team(_pair(0, _pit('Dunn', 'Di', 40, 2)))
    b = _team(_pair(0, _pit('Fry', 'Fo', 92, 10)), _pair(1, _pit('Gum', 'Gi', 86, 10)),
              _pair(2, _pit('Hob', 'Hu', 80, 10)), _pair(5, _pit('Ing', 'Io', 40, 2)))
    lg = trade_league(str(tmp_path / 'L'), a, b)
    ctx = ctx_for(lg)
    a0, b0 = read_file(lg, 'BOS.V20'), read_file(lg, 'DET.V20')
    st, _ = walk(ctx, trade_keys(0, 5, tail=[ord('y')]))
    assert st['msg'] == 'TRADE ACCEPTED' and st['cursor'] == 0
    assert (read_file(lg, 'BOS.V20'), read_file(lg, 'DET.V20')) == expected_trade(a0, 0, b0, 5)
    assert read_file(lg, TRADES_TXT) == b'TRADE 1 BOS Di Dunn DET Io Ing\r\n'


def test_c76_declined_same_type(tmp_path):
    """A pitcher for a batter, and a batter for a pitcher: SAME TYPE ONLY, wins even over
    UNTOUCHABLE; nothing written, the state stays on S_TRADE_OFFER."""
    b = dict(B_BATTERS)
    b.update(_pair(0, _pit('Fry', 'Fo', 92, 10)))
    lg = trade_league(str(tmp_path / 'L'), A_BATTERS, b)
    ctx = ctx_for(lg)
    before = snapshot(lg)
    for give, get in ((0, 16), (0, 19), (16, 0), (17, 0)):      # B 16 and B pitcher 0 are top 3
        st, _ = walk(ctx, trade_keys(give, get, tail=[Y_KEY]))
        assert (st['screen'], st['msg']) == (cr.S_TRADE_OFFER, 'DECLINED: SAME TYPE ONLY')
        assert snapshot(lg) == before
        assert st['image'] == cr.read_v20(lg, 'BOS')
    assert not os.path.exists(os.path.join(lg, TRADES_TXT))


def test_c76_declined_untouchable_top3_ties_to_lower_slot(tmp_path):
    """Y among B's 3 best batters by V: UNTOUCHABLE even for a far better X. With equal V ties
    go to the lower slot: of four 50s, slots 16..18 are untouchable and 19 is not."""
    a = _team(_pair(16, _bat('Axe', 'Al', 90)), _pair(17, _bat('Bell', 'Bo', 50)))
    b = _team(*[_pair(16 + i, _bat('B%d' % i, 'X', 50)) for i in range(4)])
    lg = trade_league(str(tmp_path / 'L'), a, b)
    ctx = ctx_for(lg)
    before = snapshot(lg)
    for get in (0, 1, 2):
        st, _ = walk(ctx, trade_keys(16, 16 + get, tail=[Y_KEY]))
        assert st['msg'] == 'DECLINED: UNTOUCHABLE' and st['screen'] == cr.S_TRADE_OFFER
        assert snapshot(lg) == before
    assert cr.trade_top3(cr.read_v20(lg, 'DET'), False) == {16, 17, 18}
    st, _ = walk(ctx, trade_keys(16, 19, tail=[Y_KEY]))
    assert st['msg'] == 'TRADE ACCEPTED'


def test_c76_top3_counts_only_named_slots_of_the_type():
    """trade_top3 ranks by V then slot, over named slots of the type only."""
    img = bytearray(IMAGE)
    for slot, v in ((16, 10), (18, 30), (20, 30), (22, 20), (25, 5)):
        img[295 + 143 * slot:295 + 143 * (slot + 1)] = _bat('N%d' % slot, 'A', v)
    img[295:295 + 143] = _pit('Pit', 'A', 92, 10)
    assert cr.trade_top3(bytes(img), False) == {18, 20, 22}
    assert cr.trade_top3(bytes(img), True) == {0}


def test_c76_declined_not_enough_value_band_edge(tmp_path):
    """eff * 100 < V(Y) * 95 declines: V(Y) 40 takes X at 38 (3800 is not < 3800) and refuses 37."""
    a = _team(_pair(16, _bat('Ok', 'A', 38)), _pair(17, _bat('Low', 'B', 37)))
    lg = trade_league(str(tmp_path / 'L'), a, B_BATTERS)
    ctx = ctx_for(lg)
    before = snapshot(lg)
    st, _ = walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))
    assert (st['screen'], st['msg']) == (cr.S_TRADE_OFFER, 'DECLINED: NOT ENOUGH VALUE')
    assert snapshot(lg) == before and not os.path.exists(os.path.join(lg, TRADES_TXT))
    st, _ = walk(ctx, trade_keys(16, 19, tail=[Y_KEY]))
    assert (st['screen'], st['msg']) == (cr.S_SLOT, 'TRADE ACCEPTED')


def test_c76_decline_message_clears_on_next_key(tmp_path):
    a = _team(_pair(17, _bat('Low', 'B', 37)))
    ctx = ctx_for(trade_league(str(tmp_path / 'L'), a, B_BATTERS))
    st, _ = walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))
    assert st['msg'] == 'DECLINED: NOT ENOUGH VALUE'
    for key in (ord('x'), Y_KEY):
        st2, _ = walk(ctx, [key], st)
        assert st2['msg'] == ('DECLINED: NOT ENOUGH VALUE' if key == Y_KEY else 0)
    st3, _ = walk(ctx, [N_KEY], st)
    assert (st3['screen'], st3['msg']) == (cr.S_TRADE_PICK, 0)


def test_c76_need_bonus_accepts_what_value_alone_declines(tmp_path):
    """B's batters are all 1B, so B's thinnest position is 1 (C: nobody). X plays C as a
    second position: V(X) 36 + (36 * 32 >> 8 = 4) = 40 passes for V(Y) 40; the same X without
    the C second position (V 36 alone) is declined."""
    a = _team(_pair(16, _bat('Need', 'A', 36, pos2=1)), _pair(17, _bat('Plain', 'B', 36)),
              _pair(18, _bat('Elbow', 'C', 36, pos2=3)))
    lg = trade_league(str(tmp_path / 'L'), a, B_BATTERS)
    ctx = ctx_for(lg)
    assert cr.trade_need(cr.read_v20(lg, 'DET')) == 1
    st, _ = walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))
    assert st['msg'] == 'DECLINED: NOT ENOUGH VALUE'
    st, _ = walk(ctx, trade_keys(18, 19, tail=[Y_KEY]))
    assert st['msg'] == 'DECLINED: NOT ENOUGH VALUE'            # second pos 3B: not the need
    a1 = read_file(lg, 'BOS.V20')
    st, _ = walk(ctx, trade_keys(16, 19, tail=[Y_KEY]))
    assert st['msg'] == 'TRADE ACCEPTED'
    assert read_file(lg, 'BOS.V20') != a1


def test_c76_need_ties_to_lower_position(tmp_path):
    """One B batter covers C: counts are C 1, 1B n, every other position 0, so the need is the
    lowest of those, 3B (q 3); a group second position that covers 3B (IF, code 11) counts
    as playing it, an OF one does not."""
    b = dict(B_BATTERS)
    b.update(_pair(22, _bat('Cat', 'Cy', 20, pos2=1)))
    a = _team(_pair(16, _bat('Three', 'A', 36, pos2=3)), _pair(17, _bat('Four', 'B', 36, pos2=4)),
              _pair(18, _bat('Inf', 'C', 36, pos2=11)), _pair(19, _bat('Out', 'D', 36, pos2=10)))
    for give, ok in ((16, True), (17, False), (18, True), (19, False)):
        lg = trade_league(str(tmp_path / ('L%d' % give)), a, b)       # a trade changes DET
        ctx = ctx_for(lg)
        assert cr.trade_need(cr.read_v20(lg, 'DET')) == 3
        st, _ = walk(ctx, trade_keys(give, 19, tail=[Y_KEY]))
        assert (st['msg'] == 'TRADE ACCEPTED') == ok, give


def test_c76_need_ignores_pitchers_and_empty_slots():
    img = bytearray(IMAGE)
    # nobody named: every count 0, need 1
    assert cr.trade_need(bytes(img)) == 1
    # a named pitcher whose position byte says C does not count (slots 16..39 only)
    img[295 + 143 * 3:295 + 143 * 4] = _rated('P', 'A', 28, 1)
    assert cr.trade_need(bytes(img)) == 1
    # catchers in two slots, nothing else: C count 2, 2B..RF 0, need 2
    for slot in (16, 17):
        img[295 + 143 * slot:295 + 143 * (slot + 1)] = _rated('C%d' % slot, 'A', 28, 1)
    assert cr.trade_need(bytes(img)) == 2


def pitcher_trade_league(d, n_sp, x_end, x_v=35):
    """A: pitcher 0 (V x_v, endurance x_end). B: 3 SP pitchers (V 92 / 86 / 80), Y at slot 3
    (V 40, endurance 2), an RP at 4 and n_sp - 3 more SP at slots 5.. (V 30, endurance 6);
    B has n_sp SP in all."""
    a = _team(_pair(0, _pit('Xan', 'Xi', x_v, x_end)))
    b = _team(_pair(0, _pit('Fry', 'Fo', 92, 10)), _pair(1, _pit('Gum', 'Gi', 86, 10)),
              _pair(2, _pit('Hob', 'Hu', 80, 10)), _pair(3, _pit('Why', 'Yo', 40, 2)),
              _pair(4, _pit('Rel', 'Ri', 30, 0)),
              *[_pair(5 + i, _pit('Sp%d' % i, 'S', 30, 6)) for i in range(n_sp - 3)])
    return trade_league(d, a, b)


def test_c76_pitcher_sp_bonus(tmp_path):
    """An SP offered to a team with fewer than 5 named SP gets the bonus (35 + 4 = 39 passes
    for V(Y) 40); with 5 named SP, or an RP offered, V 35 alone is declined."""
    acc, no = 'TRADE ACCEPTED', 'DECLINED: NOT ENOUGH VALUE'
    # (named SP in B, X endurance, V(X)): endurance 5 is an RP (the V values keep V - 2 end
    # divisible by 3), endurance 6 the smallest SP
    for n_sp, x_end, v, want in ((3, 7, 35, acc), (4, 7, 35, acc), (5, 7, 35, no),
                                 (6, 7, 35, no), (3, 1, 35, no), (4, 5, 37, no),
                                 (4, 6, 36, acc)):
        lg = pitcher_trade_league(str(tmp_path / ('L%d_%d' % (n_sp, x_end))), n_sp, x_end, v)
        ctx = ctx_for(lg)
        st, _ = walk(ctx, trade_keys(0, 3, tail=[Y_KEY]))
        assert st['msg'] == want, (n_sp, x_end)


def test_c76_pitcher_untouchable_uses_pitcher_top3(tmp_path):
    lg = pitcher_trade_league(str(tmp_path / 'L'), 4, 7)
    ctx = ctx_for(lg)
    for get in (0, 1, 2):
        st, _ = walk(ctx, trade_keys(0, get, tail=[Y_KEY]))
        assert st['msg'] == 'DECLINED: UNTOUCHABLE'


def test_c76_value_helper_guards_bad_grade():
    """A development grade byte past 5 reads as 0 instead of raising; 0..5 is rosters.value."""
    rec = bytearray(_bat('Young', 'A', 40))
    rec[20] = 21
    for g in range(6):
        rec[142] = g
        assert cr._value(bytes(rec)) == rosters.value(bytes(rec))
    base = rosters.value(bytes(rec[:142]) + b'\0')
    for g in (6, 7, 200, 255):
        rec[142] = g
        with pytest.raises(IndexError):
            rosters.value(bytes(rec))
        assert cr._value(bytes(rec)) == base
    rec[20] = 30
    rec[142] = 200
    assert cr._value(bytes(rec)) == rosters.value(bytes(rec))


def test_c76_season_from_history(tmp_path):
    lg = std_league(str(tmp_path / 'L'))
    h = bytearray(32)
    h[4], h[5] = 44, 1                       # 300 seasons recorded
    open(os.path.join(lg, 'HISTORY.DAT'), 'wb').write(bytes(h))
    ctx = ctx_for(lg)
    walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))
    assert read_file(lg, TRADES_TXT) == b'TRADE 301 BOS Bo Bell DET Hal Hart\r\n'
    assert cr.trade_season(lg) == 301


def test_c76_season_without_or_with_bad_history(tmp_path):
    lg = std_league(str(tmp_path / 'L'))
    assert cr.trade_season(lg) == 1                                   # missing
    open(os.path.join(lg, 'HISTORY.DAT'), 'wb').write(b'')
    assert cr.trade_season(lg) == 1                                   # empty
    open(os.path.join(lg, 'HISTORY.DAT'), 'wb').write(bytes([1, 2, 3]))
    assert cr.trade_season(lg) == 1                                   # shorter than the header
    open(os.path.join(lg, 'HISTORY.DAT'), 'wb').write(bytes([0, 0, 0, 0, 7, 0]))
    assert cr.trade_season(lg) == 8                                   # six bytes are enough
    os.remove(os.path.join(lg, 'HISTORY.DAT'))
    os.mkdir(os.path.join(lg, 'HISTORY.DAT'))
    assert cr.trade_season(lg) == 1                                   # unreadable
    lg2 = std_league(str(tmp_path / 'M'))
    walk(ctx_for(lg2), trade_keys(17, 19, tail=[Y_KEY]))
    assert read_file(lg2, TRADES_TXT).startswith(b'TRADE 1 BOS ')


def test_c76_trades_txt_appended_not_rewritten(tmp_path):
    """An existing TRADES.TXT keeps its bytes (even without a final newline) and gets the new
    CRLF line; a second trade appends again, in order."""
    lg = std_league(str(tmp_path / 'L'))
    old = b'TRADE 3 AAA Old One BBB Old Two\r\nTRADE 3 CCC x DDD y'
    open(os.path.join(lg, TRADES_TXT), 'wb').write(old)
    h = bytearray(32)
    h[4] = 3
    open(os.path.join(lg, 'HISTORY.DAT'), 'wb').write(bytes(h))
    ctx = ctx_for(lg)
    st, _ = walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))
    first = b'TRADE 4 BOS Bo Bell DET Hal Hart\r\n'
    assert read_file(lg, TRADES_TXT) == old + first
    # second trade from the new state (cursor on slot 17): A's slot 18 for B's slot 21
    st, _ = walk(ctx, [DOWN, T_KEY, ENTER] + [DOWN] * 21 + [ENTER, Y_KEY], st)
    assert st['msg'] == 'TRADE ACCEPTED'
    assert read_file(lg, TRADES_TXT) == old + first + b'TRADE 4 BOS Cy Cobb DET Jo Jay\r\n'


def test_c76_second_trade_appends_a_line(tmp_path):
    """A's slot 16 (Axe, V40) for B's slot 19 (V40) and then, from the updated state, A's slot
    18 (Cobb V30) for B's slot 21 (Jay V30): two lines in order, three file writes each."""
    lg = std_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st, _ = walk(ctx, trade_keys(16, 19, tail=[Y_KEY]))
    assert st['msg'] == 'TRADE ACCEPTED' and st['cursor'] == 16
    keys = [DOWN, DOWN, T_KEY, ENTER] + [DOWN] * 21 + [ENTER, Y_KEY]
    st, _ = walk(ctx, keys, st)
    assert st['msg'] == 'TRADE ACCEPTED'
    assert read_file(lg, TRADES_TXT) == (b'TRADE 1 BOS Al Axe DET Hal Hart\r\n'
                                         b'TRADE 1 BOS Cy Cobb DET Jo Jay\r\n')
    # the slot pairs follow the players: A slot 16 holds Hart, A slot 18 holds Jay
    a = read_file(lg, 'BOS.V20')
    assert cr.record(a, 16)[0:4] == b'Hart' and cr.record(a, 18)[0:3] == b'Jay'
    b = read_file(lg, 'DET.V20')
    assert cr.record(b, 19)[0:3] == b'Axe' and cr.record(b, 21)[0:4] == b'Cobb'


def test_c76_state_after_accept(tmp_path):
    lg = std_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st, _ = walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))
    assert st['image'] == read_file(lg, 'BOS.V20')
    assert cr._list_view(st, ctx)[2][17][1] == 'Hart, Hal'
    # the next key clears the message and the slot list works as before
    st2, _ = walk(ctx, [DOWN], st)
    assert (st2['msg'], st2['screen'], st2['cursor']) == (0, cr.S_SLOT, 18)


def test_c76_write_errors_say_trade_failed(tmp_path):
    """TRADES.TXT unusable (a directory): both V20 files are written, msg TRADE FAILED."""
    lg = std_league(str(tmp_path / 'L'))
    os.mkdir(os.path.join(lg, TRADES_TXT))
    a0, b0 = read_file(lg, 'BOS.V20'), read_file(lg, 'DET.V20')
    st, _ = walk(ctx_for(lg), trade_keys(17, 19, tail=[Y_KEY]))
    assert (st['screen'], st['cursor'], st['msg']) == (cr.S_SLOT, 17, 'TRADE FAILED')
    assert (read_file(lg, 'BOS.V20'), read_file(lg, 'DET.V20')) == expected_trade(a0, 17, b0, 19)
    assert st['image'] == read_file(lg, 'BOS.V20')


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignores file modes')
@pytest.mark.parametrize('locked', ['BOS.V20', 'DET.V20'])
def test_c76_v20_write_error_skips_trades_txt(tmp_path, locked):
    """A read-only V20: TRADE FAILED, the other team's file is still written (best effort, no
    rollback) and no TRADES.TXT line is added."""
    lg = std_league(str(tmp_path / 'L'))
    a0, b0 = read_file(lg, 'BOS.V20'), read_file(lg, 'DET.V20')
    ctx = ctx_for(lg)
    os.chmod(os.path.join(lg, locked), 0o444)
    try:
        st, _ = walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))
    finally:
        os.chmod(os.path.join(lg, locked), 0o644)
    ea, eb = expected_trade(a0, 17, b0, 19)
    assert st['msg'] == 'TRADE FAILED' and st['screen'] == cr.S_SLOT
    assert read_file(lg, 'BOS.V20') == (a0 if locked == 'BOS.V20' else ea)
    assert read_file(lg, 'DET.V20') == (b0 if locked == 'DET.V20' else eb)
    assert not os.path.exists(os.path.join(lg, TRADES_TXT))


def test_c76_trade_with_each_other_team(tmp_path):
    """Any other team can be B: A = BOS trades with CHI (list row 2) and the CHI file changes."""
    chi = _team(_pair(16, _bat('Cub', 'Cy', 70)), _pair(17, _bat('Bear', 'Bo', 66)),
                _pair(18, _bat('Lion', 'Li', 62)), _pair(19, _bat('Wolf', 'Wi', 40)))
    lg = make_league(str(tmp_path / 'L'), recs={0: A_BATTERS, 2: {}, 15: {}, 16: chi, 17: {}})
    ctx = ctx_for(lg)
    a0, c0 = read_file(lg, 'BOS.V20'), read_file(lg, 'CHI.V20')
    st, _ = walk(ctx, trade_keys(17, 19, b=2, tail=[Y_KEY]))
    assert st['msg'] == 'TRADE ACCEPTED'
    assert (read_file(lg, 'BOS.V20'), read_file(lg, 'CHI.V20')) == expected_trade(a0, 17, c0, 19)
    assert read_file(lg, TRADES_TXT) == b'TRADE 1 BOS Bo Bell CHI Wi Wolf\r\n'
    assert read_file(lg, 'DET.V20') == cr.read_v20(lg, 'DET')


def test_c76_pname_strip_matches_rosters_pname():
    """trade lines use rosters.pname: an empty first name gives the last name alone."""
    rec = _rated('Solo', '', 28, 2)
    assert rosters.pname(rec) == 'Solo'


def test_c76_every_key_on_every_screen(tmp_path):
    """The all-keys walk of test_every_key_on_every_screen with the three trade screens
    added: every state stays on a known screen (0..8)."""
    lg = std_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg, make_anms(str(tmp_path / 'A')))
    starts = [cr.start_state(), to_slot(ctx, 0), walk(ctx, slot_keys(17) + [T_KEY])[0],
              walk(ctx, slot_keys(17) + [T_KEY, ENTER])[0], walk(ctx, trade_keys(17, 19))[0],
              walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))[0],
              walk(ctx, trade_keys(16, 19, tail=[Y_KEY]))[0]]
    seen = set()
    for s in starts:
        seen.add(s['screen'])
        for k in ALL_KEYS:
            st2, ex = cr.step(s, k, ctx)
            assert isinstance(ex, bool)
            assert st2['screen'] in range(9)
            seen.add(st2['screen'])
    assert {cr.S_TRADE_TEAM, cr.S_TRADE_PICK, cr.S_TRADE_OFFER} <= seen


def test_c76_screen_numbers_and_texts():
    assert (cr.S_TRADE_TEAM, cr.S_TRADE_PICK, cr.S_TRADE_OFFER) == (6, 7, 8)
    assert cr.FOOT_TRADE_OFFER == 'Y PROPOSE   N ESC BACK'
    assert cr.MSG_TRADE == ('DECLINED: SAME TYPE ONLY', 'DECLINED: UNTOUCHABLE',
                            'DECLINED: NOT ENOUGH VALUE', 'TRADE ACCEPTED', 'TRADE FAILED')
    for f in (cr.FOOT_TRADE_TEAM, cr.FOOT_TRADE_PICK, cr.FOOT_TRADE_OFFER):
        assert len(f) <= 44


def _c76_fonts(d):
    os.makedirs(d, exist_ok=True)
    for leaf, rows in (('MAIN.FNT', 7), ('BOLD.FNT', 8)):
        buf = bytearray(struct.pack('<H', 95))
        for g in range(95):
            buf += bytes((rows, 7, 7)) + bytes(((g * 29 + r * 13) % 127) << 1 for r in range(rows))
        open(os.path.join(d, leaf), 'wb').write(bytes(buf))
    return d


def test_c76_render_trade_screens_and_message_footer(tmp_path):
    """Every trade screen renders; on the offer screen a decline message and on the slot list
    TRADE ACCEPTED replace the footer text (the footer row's pixels change, nothing above)."""
    lg = std_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg, fonts=dynview.load_fonts(_c76_fonts(str(tmp_path / 'F'))))
    states = [walk(ctx, slot_keys(17) + [T_KEY])[0], walk(ctx, slot_keys(17) + [T_KEY, ENTER])[0],
              walk(ctx, trade_keys(17, 19))[0]]
    frames = [bytes(cr.render(s, ctx)) for s in states]
    assert len(set(frames)) == 3 and all(len(f) == 64000 for f in frames)
    offer = states[2]
    quiet = bytes(cr.render(offer, ctx))
    loud = bytes(cr.render(dict(offer, msg='DECLINED: UNTOUCHABLE'), ctx))
    assert quiet != loud and quiet[:185 * 320] == loud[:185 * 320]
    acc, _ = walk(ctx, trade_keys(17, 19, tail=[Y_KEY]))
    plain = bytes(cr.render(dict(acc, msg=0), ctx))
    msg = bytes(cr.render(acc, ctx))
    assert plain != msg and plain[:185 * 320] == msg[:185 * 320]
