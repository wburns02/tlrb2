"""Holdout suite, part 1: code that WRITES game files (byte layout, refusals, isolation).

Offline and deterministic. No game data: every fixture is built from raw bytes in tmp_path.
Run:  cd tools/m4 && python3 -m pytest -q -p no:cacheprovider holdout
"""
import os

import pytest

import create as cr
import history
import menu_patch as mp
import patchlib
import statline
from rig import bat_patch
from v20 import HDR, REC, SIZE, Player, Team
from holdout_util import blank_team, make_maj, put_player, v20_bytes


# ---------------------------------------------------------------- v20 reader/writer

def test_v20_size_gate_and_field_isolation():
    """Team refuses any image that is not exactly 11735 B; nibble and u16 setters touch only their
    own bits; Team.set mirrors ratings to the twin half and writes stats to one record only."""
    img = v20_bytes(7)
    assert SIZE == 11735
    assert Team(img).to_bytes() == img                      # decode then encode is the identity
    for bad in (img[:-1], img + b'\0', b'', img[:HDR]):
        with pytest.raises(AssertionError):
            Team(bad)

    t = Team(img)
    p = t.players[3]
    before = bytes(p.raw)
    p['bunt'] = 9                                           # high nibble of +0x4a
    assert p.raw[0x4a] >> 4 == 9 and p.raw[0x4a] & 15 == before[0x4a] & 15
    p['power'] = 3                                          # low nibble of +0x4a
    assert p.raw[0x4a] == (9 << 4) | 3
    p['bunt'] = 0x1f                                        # masked to 4 bits, never spills sideways
    assert p.raw[0x4a] == (15 << 4) | 3
    p['salary'] = 0x1234                                    # u16 little endian at +0x19
    assert bytes(p.raw[0x19:0x1b]) == b'\x34\x12'
    assert all(p.raw[i] == before[i] for i in range(REC) if i not in (0x4a, 0x19, 0x1a))

    # Team.set: age and power go to both halves, games to record 5 only, names to both halves
    t = Team(img)
    t.set(5, power=7, age=33, games=9, last='Ruiz')
    want = bytearray(img)
    for r in (5, 45):
        b = HDR + REC * r
        want[b + 0x4a] = (want[b + 0x4a] & 0xf0) | 7
        want[b + 0x14] = 33
        want[b:b + 12] = b'Ruiz'.ljust(12, b'\0')
    want[HDR + REC * 5 + 0x17] = 9
    assert t.to_bytes() == bytes(want)


# ---------------------------------------------------------------- EXE patch primitives

def test_patchlib_apply_is_all_or_nothing_and_reverts(tmp_path):
    """apply() checks every old byte string before writing anything, backs up once, refuses a
    second patch, and revert() restores the original bytes."""
    exe = tmp_path / 'X.EXE'
    orig = bytes(range(64))
    exe.write_bytes(orig)
    good = [(10, orig[10:12], b'\xaa\xbb'), (40, orig[40:41], b'\xcc')]

    stale = [good[0], (20, b'\xff\xff', b'\x00\x00')]       # second site does not match
    with pytest.raises(AssertionError):
        patchlib.apply(str(exe), stale)
    assert exe.read_bytes() == orig                         # the first site was NOT written
    assert not (tmp_path / 'X.EXE.m4.bak').exists()

    with pytest.raises(AssertionError):                     # new bytes of a different length
        patchlib.apply(str(exe), [(10, orig[10:12], b'\xaa')])
    assert exe.read_bytes() == orig

    bak = patchlib.apply(str(exe), good)
    out = exe.read_bytes()
    assert open(bak, 'rb').read() == orig
    assert out[10:12] == b'\xaa\xbb' and out[40:41] == b'\xcc'
    assert out[:10] == orig[:10] and out[12:40] == orig[12:40] and out[41:] == orig[41:]
    assert len(out) == len(orig)

    with pytest.raises(AssertionError):                     # a double patch is refused, file untouched
        patchlib.apply(str(exe), [(10, b'\xaa\xbb', b'\x01\x02')])
    assert exe.read_bytes() == out
    patchlib.revert(str(exe))
    assert exe.read_bytes() == orig


def test_menu_patch_file_states_and_refusals(tmp_path):
    """patch_file moves a file between stock and patched only when EVERY site holds one of the two
    expected values; anything else aborts with no write. patch() refuses a pristine tree."""
    exe = tmp_path / 'MAIN.EXE'
    orig = bytes(range(100))
    exe.write_bytes(orig)
    hdr = [(5, orig[5:7], b'\xaa\xbb'), (30, orig[30:31], b'\x09')]

    assert mp.patch_file(str(exe), [], header=hdr, check_only=True) == 'stock'
    assert exe.read_bytes() == orig                         # check_only never writes
    assert mp.patch_file(str(exe), [], header=hdr) == 'patched'
    got = exe.read_bytes()
    assert got[5:7] == b'\xaa\xbb' and got[30] == 9
    assert got[:5] == orig[:5] and got[7:30] == orig[7:30] and got[31:] == orig[31:]
    assert mp.patch_file(str(exe), [], header=hdr) == 'already'
    assert exe.read_bytes() == got
    assert mp.patch_file(str(exe), [], revert=True, header=hdr) == 'reverted'
    assert exe.read_bytes() == orig

    # one site unknown (neither stock nor patched): abort, the stock site is NOT written
    mixed = bytearray(orig)
    mixed[30] = 0x55
    exe.write_bytes(bytes(mixed))
    with pytest.raises(SystemExit):
        mp.patch_file(str(exe), [], header=hdr)
    assert exe.read_bytes() == bytes(mixed)

    # half patched (site 1 patched, site 2 stock) is not a state either: abort, no write
    half = bytearray(orig)
    half[5:7] = b'\xaa\xbb'
    exe.write_bytes(bytes(half))
    with pytest.raises(SystemExit):
        mp.patch_file(str(exe), [], header=hdr)
    assert exe.read_bytes() == bytes(half)

    pristine = tmp_path / 'pristine' / 'TONY2'
    pristine.mkdir(parents=True)
    with pytest.raises(SystemExit):
        mp.patch(str(pristine))


def test_bat_patch_roundtrip_and_refuses_protected_installs(tmp_path, monkeypatch, capsys):
    """TONY2.BAT patcher: CRLF only, idempotent, exact revert, ARCHIVE.BAT lifecycle, and a
    protected install path is refused with the BAT left untouched."""
    root = tmp_path / 'TONY2'
    root.mkdir()
    stock = b'@echo off\r\n:start\r\ncontrol\r\nif errorlevel 1 goto end\r\n:end\r\n'
    (root / 'TONY2.BAT').write_bytes(stock)

    assert bat_patch.patch(str(root)) is True
    patched = (root / 'TONY2.BAT').read_bytes()
    txt = patched.decode('cp437')
    assert ':start\r\nrosters /expand\r\nhistwr /snap\r\ndynasty\r\n' in txt
    assert txt.endswith(':ctl\r\ncontrol\r\nif errorlevel 1 goto end\r\n:end\r\n')
    assert txt.count('\n') == txt.count('\r\n')             # no bare LF
    assert (root / 'ARCHIVE.BAT').exists()
    assert (tmp_path / 'DYNSNAP').is_dir()                  # C:\DYNSNAP is the parent of the install

    assert bat_patch.patch(str(root)) is True               # a second run changes nothing
    assert (root / 'TONY2.BAT').read_bytes() == patched

    assert bat_patch.patch(str(root), revert=True) is True
    assert (root / 'TONY2.BAT').read_bytes() == stock
    assert not (root / 'ARCHIVE.BAT').exists()

    # protected paths: use a tmp stand-in so a broken guard can never touch the real install
    for live in ('/mnt/nvme/tlrb2/c/', '/mnt/nvme/tlrb2/pristine/', '/mnt/nvme/tlrb2/work/c/'):
        assert live in bat_patch.REFUSE
    live = tmp_path / 'live' / 'TONY2'
    live.mkdir(parents=True)
    (live / 'TONY2.BAT').write_bytes(stock)
    monkeypatch.setattr(bat_patch, 'REFUSE', (str(tmp_path / 'live') + '/',))
    capsys.readouterr()
    assert bat_patch.patch(str(live)) is False
    assert 'refusing' in capsys.readouterr().err
    assert bat_patch.patch(str(live), revert=True) is False
    assert (live / 'TONY2.BAT').read_bytes() == stock
    assert not (live / 'ARCHIVE.BAT').exists()


# ---------------------------------------------------------------- CREATE A PLAYER writer

def _create_ctx(tmp_path, n_teams=2):
    d = tmp_path / 'league'
    d.mkdir()
    for k in range(n_teams):
        (d / ('TEAM%d.V20' % k)).write_bytes(v20_bytes(100 + k))
    teams = [(k, 'TEAM%d' % k, 'TEAM%d' % k) for k in range(n_teams)]
    grp = bytes((k * 5 + 1) & 255 for k in range(40))
    return d, {'league_dir': str(d), 'teams': teams, 'faces': (len(grp), grp)}


def test_create_save_slot_writes_only_the_two_target_records(tmp_path):
    """save_slot rewrites the roster record and the season record of ONE slot in ONE team file
    (same length) and nothing else, for the first and last pitcher and batter slots; the season half
    carries no season stats; a missing team file is never created; a stem with a path separator
    writes nowhere."""
    for slot in (0, 15, 16, 39):
        _save_slot_case(tmp_path / ('s%d' % slot), slot)


def _save_slot_case(tmp_path, slot):
    tmp_path.mkdir()
    d, ctx = _create_ctx(tmp_path)
    t0_before = (d / 'TEAM0.V20').read_bytes()
    t1_before = (d / 'TEAM1.V20').read_bytes()
    form = cr.blank_form()
    form.update(last='Ruiz', first='Tom', age=23)
    st = dict(cr.start_state(), slot=slot, team=1, form=form, image=t1_before)

    img = cr.save_slot(st, ctx)
    after = (d / 'TEAM1.V20').read_bytes()
    assert (d / 'TEAM0.V20').read_bytes() == t0_before      # the other team is untouched
    assert len(after) == cr.IMAGE_LEN and img == after      # no growth, the image mirrors the disk
    roster = HDR + REC * slot
    season = HDR + REC * (slot + 40)
    changed = {i for i in range(len(after)) if after[i] != t1_before[i]}
    allowed = set(range(roster, roster + REC)) | set(range(season, season + REC))
    assert changed and changed <= allowed
    assert after[roster:roster + 4] == b'Ruiz' and after[roster + 12:roster + 15] == b'Tom'
    srec, rrec = after[season:season + REC], after[roster:roster + REC]
    for off in statline.SEASON_STAT_BYTES:
        assert srec[off] == 0                               # season stats start at zero
    stat = set(statline.SEASON_STAT_BYTES)
    assert all(srec[i] == rrec[i] for i in range(REC) if i not in stat)

    # a team file that is missing is not created
    (d / 'TEAM1.V20').unlink()
    listing = sorted(os.listdir(d))
    cr.save_slot(st, ctx)
    assert sorted(os.listdir(d)) == listing

    # a stem that climbs out of the league dir writes nowhere
    outside = tmp_path / 'OUT.V20'
    outside.write_bytes(v20_bytes(5))
    keep = outside.read_bytes()
    ctx['teams'] = [(0, '../OUT', '../OUT')]
    st['team'] = 0
    cr.save_slot(st, ctx)
    assert outside.read_bytes() == keep


def test_create_build_record_and_autofill_pins():
    """decode(encode(form)) == form for every hand code, both roles, stock and custom faces; the
    C34 autofill reproduces the contract's pinned seeds and spreads."""
    grp = bytes((k * 5 + 1) & 255 for k in range(400))
    hands = {0: (1, 1), 1: (0, 0), 2: (2, 1), 3: (1, 0), 4: (0, 1), 5: (2, 0)}   # (bats code, throws R)
    for hi, (bats, throws) in hands.items():
        for face in (0, 7, 399, 400):
            for pitcher in (False, True):
                form = cr.blank_form()
                form.update(last='Quintero', first='Wes', age=29, hands=hi, face=face,
                            pos=5, pos2=11, r=[3, 5, 7, 9, 11, 12])
                if pitcher:
                    form['r'] = [4, 8, 10, 6, 6, 6]
                rec = cr.build_record(form, pitcher, 120, grp)
                p = Player(rec, 0)
                assert len(rec) == REC
                assert p['last'] == 'Quintero' and p['first'] == 'Wes'
                assert rec[8:12] == bytes(4) and rec[15:20] == bytes(5)   # NUL padded, no spill
                assert p['age'] == 29 and rec[0x15] == 120
                assert p['bats'] == bats and p['throws'] == throws
                assert p['flag3'] == (grp[face] & 1 if face < 400 else 0)
                assert p['portrait'] == face
                if pitcher:
                    assert (p['pos1'], p['pos2']) == (0, 0)
                    assert [p[k] for k in ('control', 'velocity', 'endurance')] == [4, 8, 10]
                else:
                    assert (p['pos1'], p['pos2']) == (5, 11)
                    assert [p[k] for k in ('power', 'bunt', 'hit_run', 'speed', 'range', 'arm')] \
                        == [3, 5, 7, 9, 11, 12]

    # C34 pins (notes/M4_CONTRACT.md): batter REGULAR from seed 1, a second A, pitcher STAR
    st = dict(cr.start_state(), slot=20, budget=0)
    cr._autofill(st)
    assert (st['seed'], st['form']['r']) == (429995104, [8, 5, 6, 10, 6, 10])
    cr._autofill(st)
    assert (st['seed'], st['form']['r']) == (1495896251, [9, 8, 7, 6, 9, 6])
    st = dict(cr.start_state(), slot=3, budget=3)
    cr._autofill(st)
    assert (st['seed'], st['form']['r'][:3]) == (1303003706, [12, 7, 9])


# ---------------------------------------------------------------- HISTORY.DAT writer

def test_history_entries_roundtrip_without_bleeding():
    """Player and season entries decode to what was encoded and stay inside their own slots,
    including u32 extremes, negative WAR and the last season row (which ends at the player table)."""
    h = history.History(None)
    ents = []
    for k in range(3):
        ents.append({'name': (b'NAME%d' % k).ljust(20, b'\0'), 'birth': 900 + k, 'status': 1 + k,
                     'age': 20 + k, 'first_season': 1 + k, 'last_season': 5 + k,
                     'seasons_played': 4 + k, 'pos1': k, 'pitcher': 1 if k == 0 else 0,
                     'totals': [0xffffffff - k] * 25, 'WAR10': -123 - k,
                     'top7': [30 - k, 20, 10, 0, -5, -10, -32768], 'JAWS10': -7 + k,
                     'hof_season': 40 + k, 'awards': [k, 2, 3, 4, 5]})
        h.append_entry(ents[-1])
    assert (h.d[6] | h.d[7] << 8) == 3
    for k in range(3):
        assert h.read_entry(k) == ents[k]
    o1 = h.entry_offset(1)
    snap = bytes(h.d)
    e1 = dict(ents[1], name=b'X' * 30, status=3, totals=[1] * 25)
    h.write_entry(1, e1)
    assert bytes(h.d[:o1]) == snap[:o1]                     # header and earlier entry untouched
    assert bytes(h.d[o1 + 160:]) == snap[o1 + 160:]         # later entry untouched
    assert h.read_entry(1)['name'] == b'X' * 20             # an over long name is cut, birth not clobbered
    assert h.read_entry(1)['birth'] == ents[1]['birth']
    assert h.read_entry(2) == ents[2]

    se = {'season_no': 64, 'champion': 0x13, 'runner_up': 2, 'champion_stem': b'BOSTON',
          'runner_up_stem': b'CLE', 'al_pennant': 3, 'nl_pennant': 0x14, 'ndiv': 3,
          'divmap': bytes(range(16)), 'w_l': [(i, 162 - i) for i in range(32)],
          'awards': [1, 2, 3, 0xffff, 5, 6]}
    before = bytes(h.d)
    h.write_season_entry(64, se)
    assert h.read_season_entry(64) == se
    last = 32 + 63 * 128
    after = bytes(h.d)
    assert after[:last] == before[:last]                    # header and seasons 1..63 untouched
    assert after[last + 128:] == before[last + 128:]        # the player table (byte 8224 on) intact
    assert history.PLAYER_TABLE == last + 128


def test_history_season_past_64_never_lands_on_the_player_table(tmp_path):
    """record_season for season 65 must not write a season row (it would overwrite player 0), but
    careers still update."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    img = blank_team()
    for r in (7, 47):
        put_player(img, r, 'Rossi', 'Rob', 29, 4, games=100)
    (ldir / 'CLASALE1.V20').write_bytes(bytes(img))
    (ldir / 'CLASSIC.MAJ').write_bytes(make_maj([(0, 'BAL', 'clasale1')], []))
    hp = tmp_path / 'HISTORY.DAT'
    history.record_season(str(ldir), str(hp), 1, {})
    before = hp.read_bytes()
    h1 = history.History(before)
    assert h1.seasons_recorded == 1 and len(h1._entries) == 1
    history.record_season(str(ldir), str(hp), 65, {})
    after = hp.read_bytes()
    assert after[32:8224] == before[32:8224]                # the season table is unchanged
    assert after[8224:8224 + 160] == before[8224:8224 + 160]    # player 0 is intact
    h2 = history.History(after)
    assert h2.seasons_recorded == 65 and len(h2._entries) == 2
    assert h2.read_entry(1)['first_season'] == 65           # a different birth year: a new identity
