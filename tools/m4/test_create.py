#!/usr/bin/env python3
"""CREATE A PLAYER (tools/m4/create.py) unit tests. Run:
  python3 -m pytest -q tools/m4/test_create.py tools/m4/test_create_c.py
Synthetic league in tmp_path: LEAGUE.MAJ, team V20 files, PORTRAIT.ANM and FACEGRP.DAT.
Render tests need the stock fonts in /mnt/nvme/tlrb2/files (skipped when MAIN.FNT is
missing)."""
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
import team_fill

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
    """295 byte header (name in bytes 0..13) and 80 records; recs = {index: bytes}."""
    img = bytearray(IMAGE)
    img[0:len(name)] = name
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
            'faces': rookies.load_faces(anms), 'fonts': fonts}


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
    assert rows[0] == ('P1', 'Adams, Joe', 'P', '30')
    assert rows[1] == ('P2', '(EMPTY)', '', '')
    assert rows[16] == ('B1', 'Baker, Al', 'SS', '25')
    assert footer == 'UP DOWN   ENTER PICK   ESC TEAMS'


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
    assert st['form']['last'] == "aB .'-"
    st, _ = walk(ctx, [BACK, BACK], st)
    assert st['form']['last'] == 'aB .'
    st, _ = walk(ctx, typed('abcdefghijklmnop'), st)
    assert st['form']['last'] == 'aB .abcdefg'     # max 11
    st, _ = walk(ctx, [DOWN] + typed('Jo') + [32], st)
    assert st['form']['first'] == 'Jo '
    st, _ = walk(ctx, typed('xxxxxxxxx'), st)
    assert st['form']['first'] == 'Jo xxxx'        # max 7
    st, _ = walk(ctx, [UP, BACK, LEFT, RIGHT], st)
    assert st['form']['last'] == 'aB .abcdef'      # name rows ignore LEFT and RIGHT


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
    assert st['form']['last'] == 'Ab'


# ---------------------------------------------------------------- field keys
def test_position_and_hands_wrap(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 16)                       # batter, pos 5
    st, _ = walk(ctx, [DOWN, DOWN] + [RIGHT] * 5, st)
    assert (st['cursor'], st['form']['pos']) == (2, 1)
    st, _ = walk(ctx, [LEFT], st)
    assert st['form']['pos'] == 9
    st, _ = walk(ctx, [DOWN, LEFT], st)
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
    st, _ = walk(ctx, [DOWN] * 5 + [LEFT] * 10, st)        # POWER row 5
    assert st['form']['r'][0] == 1
    st, _ = walk(ctx, [DOWN] + [RIGHT] * 4, st)            # BUNT row 6: 6 -> 10
    assert st['form']['r'][1] == 10
    st, _ = walk(ctx, [RIGHT] * 5, st)
    assert st['form']['r'][1] == 12
    st, _ = walk(ctx, [DOWN] * 4, st)                      # ARM row 10
    assert (st['cursor'], st['form']['r'][5]) == (10, 6)
    st, _ = walk(ctx, [UP] * 20, st)
    assert st['cursor'] == 0
    st, _ = walk(ctx, [DOWN] * 4 + [RIGHT] * 40, st)       # AGE row 4
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
    assert (st2['form']['last'], st2['form']['first']) == ('Smith', 'Al')
    before = open(os.path.join(lg, 'BOS.V20'), 'rb').read()
    st3, _ = walk(ctx, [ENTER], st)
    assert st3['screen'] == cr.S_DONE
    assert open(os.path.join(lg, 'BOS.V20'), 'rb').read() != before


def test_done_screen_and_keys(tmp_path):
    lg = make_league(str(tmp_path / 'L'))
    ctx = ctx_for(lg)
    st = to_edit(ctx, 0, 17)                       # empty batter B2
    st, _ = walk(ctx, typed('Oak') + [DOWN] * 12 + [ENTER], st)
    assert st['screen'] == cr.S_DONE
    title, cols, rows, footer, hl = cr._list_view(st, ctx)
    assert (title, rows, hl) == ('PLAYER SAVED', [('SAVED: Oak',), ('TEAM: BOSTON',),
                                                  ('SLOT: B2',)], False)
    st2, ex = walk(ctx, [DOWN, ENTER], st)
    assert (st2['screen'], st2['cursor'], ex) == (cr.S_TEAM, 0, False)
    assert walk(ctx, [ESC], st)[1] is True


def test_done_first_name_in_saved_line(tmp_path):
    ctx = ctx_for(make_league(str(tmp_path / 'L')))
    st = to_edit(ctx, 0, 17)
    st, _ = walk(ctx, typed('Oak') + [DOWN] + typed('Ray') + [DOWN] * 11 + [ENTER], st)
    assert cr._list_view(st, ctx)[2][0] == ('SAVED: Ray Oak',)


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
    st, _ = walk(ctx, typed('Lowe') + [DOWN] * 12 + [ENTER], st)
    assert st['screen'] == cr.S_CONFIRM
    st, _ = walk(ctx, [ENTER], st)
    assert st['screen'] == cr.S_DONE
    assert st['image'] == open(os.path.join(lg, 'BOS.V20'), 'rb').read()


# ---------------------------------------------------------------- record bytes
def test_build_record_batter():
    form = {'last': 'Smith', 'first': 'Al', 'pos': 4, 'hands': 2, 'age': 25,
            'r': [7, 8, 9, 10, 11, 12], 'face': 3}
    grp = rookies.default_faces()[1]
    rec = cr.build_record(form, False, 117, grp)
    assert len(rec) == 143
    assert rec[0:5] == b'Smith' and rec[5:12] == bytes(7)
    assert rec[12:14] == b'Al' and rec[14:20] == bytes(6)
    assert (rec[20], rec[21], rec[22], rec[23]) == (25, 117, 0, 0)
    assert rec[29] == 0xAD                          # speed 10 hi; S, R, group 1
    assert rec[31] == 4 and rec[30] == 0x02
    assert struct.unpack('<H', rec[27:29])[0] == 3
    assert (rec[74], rec[75], rec[94]) == (0x87, 0x79, 0xBC)
    assert (rec[76], rec[134], rec[135]) == (0x78, 0x31, 0x10)
    assert struct.unpack('<H', rec[37:39])[0] == 20
    assert struct.unpack('<H', rec[39:41])[0] == 20
    assert struct.unpack('<H', rec[25:27])[0] == rookies.SALARY_BATTER


def test_build_record_pitcher():
    form = {'last': 'Ruiz', 'first': 'Tom', 'pos': 7, 'hands': 4, 'age': 30,
            'r': [9, 10, 6, 0, 0, 0], 'face': 0}
    rec = cr.build_record(form, True, 117, rookies.default_faces()[1])
    assert rec[31] == 0 and rec[29] == 0x78          # hands L bats, R throws, pos 0
    assert rec[134] == 0xA9 and rec[135] == 0x64     # control 9, velocity 10, endurance 6
    assert (rec[74], rec[75], rec[94]) == (0x11, 0x01, 0x77)
    assert rec[136:141] == bytes([0x77, 0x77, 0x77, 0x77, 7])
    assert struct.unpack('<H', rec[101:103])[0] == 200
    assert struct.unpack('<H', rec[25:27])[0] == rookies.SALARY_PITCHER
    assert rec[30] == 0x02 and rec[21] == 117


def test_build_record_hand_combinations():
    # hands index -> (bats, throws): R R, L L, S R, R L, L R, S L; lo nibble of byte 29
    want = {0: 0xA, 1: 0x0, 2: 0xC, 3: 0x2, 4: 0x8, 5: 0x4}
    grp = bytes(30)
    for h, lo in want.items():
        form = {'last': 'A', 'first': '', 'pos': 1, 'hands': h, 'age': 20,
                'r': [6] * 6, 'face': 0}
        assert (cr.build_record(form, False, 1, grp)[29] & 0x0F) == lo, h
        pit = cr.build_record(dict(form, r=[6, 6, 6]), True, 1, grp)
        assert (pit[29] & 0x0F) == lo, h
    flagged = bytes([1] + [0] * 29)
    form = {'last': 'A', 'first': '', 'pos': 1, 'hands': 0, 'age': 20,
            'r': [6] * 6, 'face': 0}
    assert cr.build_record(form, False, 1, flagged)[29] & 1 == 1
    assert cr.build_record(form, False, 1, bytes(30))[29] & 1 == 0


def test_season_half_zeroes_only_season_bytes():
    form = {'last': 'Smith', 'first': 'Al', 'pos': 4, 'hands': 0, 'age': 25,
            'r': [7, 8, 9, 10, 11, 12], 'face': 0}
    rec = cr.build_record(form, False, 117, rookies.default_faces()[1])
    season = cr.season_half(rec)
    offs = team_fill._SEASON_STAT_OFFSETS
    for i in range(143):
        if i in offs:
            assert season[i] == 0
        else:
            assert season[i] == rec[i]


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
            assert st2['screen'] in range(5)


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
