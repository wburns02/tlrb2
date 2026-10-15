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
import statline
import ratings as rt

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


def test_foot_field_text_c34():
    """C34: the rating-field footer gained 'A AUTO'; the other footers are unchanged."""
    assert cr.FOOT_FIELD == 'UP DOWN  LEFT RIGHT  A AUTO  ESC SLOTS'
    assert cr.FOOT_NAME == 'TYPE NAME   UP DOWN   ESC SLOTS'
    assert cr.FOOT_SAVE == 'ENTER SAVE   UP DOWN   ESC SLOTS'
    assert cr.FOOT_TEAM == 'UP DOWN   ENTER PICK   ESC EXIT'
    assert cr.FOOT_SLOT == 'UP DOWN   ENTER PICK   ESC TEAMS'
    assert cr.FOOT_CONFIRM == 'ENTER REPLACE   ESC BACK'
    assert cr.FOOT_DONE == 'ENTER CREATE ANOTHER   ESC EXIT'


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
