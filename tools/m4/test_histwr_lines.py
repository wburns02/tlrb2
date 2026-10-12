#!/usr/bin/env python3
"""C13.2 tests for the HISTWR C port: SEASLINE.DAT from the normal run and the /LINES backfill, each
checked against tools/m4/history.py (record_season, backfill_lines) byte for byte on the same fixture.
Run:  python3 -m pytest -q tools/m4/test_histwr_lines.py
Builders come from test_histwr.py (host binary, HISTWR, first_diff) and test_seaslines.py (pre-roll leagues,
backfill archives, the ratings of record_pair); nothing is copied from them."""
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import history
import pytest
import test_histwr as TH
from test_history import make_maj, make_team_v20, set_player
from test_seaslines import ORDER, RATINGS, make_backfill, pre_roll_league
from v20 import F, Team, _set

SL_OUTS = ('HISTORY.DAT', 'MILESTON.DAT', 'BOXSCORE.DAT', 'SEASLINE.DAT')
RET_EMPTY = bytes(1)


def host(*args, cwd=None):
    return subprocess.run([TH.HOST, *args], capture_output=True, text=True, cwd=cwd)


def custom_league(ldir, wl=(95, 67), park=False):
    """CLASALE1: a pitcher (slot 2), a CF with a negative season WAR10 (slot 21) and a 2B whose strikeouts
    total 70000 (above 65535: the line caps the stat) with a dev grade and face of its own (slot 22).
    park: the MAJ's day 0 games give clasale1 a park factor of 1100 (the batters' runs make it count)."""
    m = make_maj()
    m.set_wl('AL', 0, *wl)
    d = bytes(m.d)
    if park:
        d = TH.park_games(d, TH.id_of(d, None, b'clasale1'), TH.id_of(d, None, b'ALA13'))
    (ldir / 'CLASSIC.MAJ').write_bytes(d)
    t = Team(make_team_v20())
    set_player(t, 2, 'ACE', 'ART', 27, 0, 30)
    set_player(t, 21, 'BONDS', 'BARRY', 31, 7, 150)
    set_player(t, 22, 'GOOD', 'GUS', 29, 3, 150)
    for i, shift in ((2, 0), (21, 1), (22, 2)):
        roster = t.players[i].raw
        for k in ORDER:
            _set(roster, *F[k], (RATINGS[k] + shift) & 15)
    roster = t.players[22].raw
    roster[history.B29_OFF] = 0x9d
    roster[history.DEV_OFF] = 4
    _set(roster, *F['portrait'], 1234)
    s = t.players[42].raw
    for k, v in (('ip10', 900), ('er', 40), ('w', 10), ('l', 5), ('gs', 30)):
        _set(s, *F[k], v)
    s = t.players[61].raw
    for k, v in (('ab_l', 300), ('h_l', 30), ('bb_l', 5), ('so_l', 150), ('runs', 10), ('rbi', 20)):
        _set(s, *F[k], v)
    s = t.players[62].raw
    for k, v in (('ab_l', 500), ('h_l', 200), ('d_l', 40), ('hr_l', 30), ('bb_l', 50), ('so_l', 40000),
                 ('so_r', 30000), ('runs', 90), ('rbi', 100), ('sb', 10), ('cs', 2)):
        _set(s, *F[k], v)
    t.save(str(ldir / 'CLASALE1.V20'))


class Pair:
    """One league dir (the pre-roll leagues) run through history.record_season (py/H.DAT) and HISTWR
    (c/H.DAT); every season both sides must agree on all four files."""

    def __init__(self, tmp_path):
        self.ldir = tmp_path / 'lg'
        self.ldir.mkdir()
        self.py = tmp_path / 'py'
        self.py.mkdir()
        self.c = tmp_path / 'c'
        self.c.mkdir()
        self.ret = tmp_path / 'R.DAT'
        self.ret.write_bytes(RET_EMPTY)

    def run(self, season, setup=None):
        if setup is None:
            pre_roll_league(self.ldir, season)
        else:
            setup(self.ldir)
        history.record_season(str(self.ldir), str(self.py / 'H.DAT'), season, None)
        rc = TH.HISTWR(str(self.ldir), str(self.c / 'H.DAT'), str(self.ret))
        assert rc.returncode == 0, rc.stderr
        self.same(f'season {season}')

    def same(self, what):
        for name in SL_OUTS:
            a, b = self.py / name, self.c / name
            assert a.exists() == b.exists(), f'{what}: {name} exists differs'
            if not a.exists():
                continue
            da, db = a.read_bytes(), b.read_bytes()
            if name == 'HISTORY.DAT':
                off, ent = TH.first_diff(da, db)
                assert off < 0, f'{what}: HISTORY.DAT first diff at {off} (entry {ent})'
            else:
                assert da == db, f'{what}: {name} differs ({len(da)} vs {len(db)} bytes)'

    def lines(self):
        return history.read_lines(str(self.c / 'SEASLINE.DAT'))


# ---------------- normal run: SEASLINE.DAT beside HISTORY.DAT ----------------

def test_one_season_seasline_matches_python(tmp_path):
    p = Pair(tmp_path)
    p.run(1)
    lines = p.lines()
    assert [x['season'] for x in lines] == [1, 1]
    assert [x['entry'] for x in lines] == [0, 1]
    assert [x['flags'] for x in lines] == [1, 0]
    assert (p.c / 'SEASLINE.DAT').stat().st_size == 16 + 2 * 80


def test_second_season_appended_matches_python(tmp_path):
    p = Pair(tmp_path)
    p.run(1)
    p.run(2)
    raw = (p.c / 'SEASLINE.DAT').read_bytes()
    assert struct.unpack_from('<H', raw, 6)[0] == 2
    assert [x['season'] for x in p.lines()] == [1, 1, 2, 2]


def test_rerun_season_replaces_its_lines(tmp_path):
    """Season 2 run again from the season-1 history: its old lines go, the new ones take their place."""
    p = Pair(tmp_path)
    p.run(1)
    hist1 = {side: (side / 'H.DAT').read_bytes() for side in (p.py, p.c)}
    p.run(2)
    once = (p.c / 'SEASLINE.DAT').read_bytes()
    for side, data in hist1.items():
        (side / 'H.DAT').write_bytes(data)
    p.run(2)
    assert (p.c / 'SEASLINE.DAT').read_bytes() == once
    assert [x['season'] for x in p.lines()] == [1, 1, 2, 2]


def test_bad_header_seasline_starts_empty(tmp_path):
    p = Pair(tmp_path)
    for side in (p.py, p.c):
        (side / 'SEASLINE.DAT').write_bytes(b'XL' + bytes(14) + bytes(160))
    p.run(1)
    assert [x['season'] for x in p.lines()] == [1, 1]


def test_trailing_partial_line_is_ignored(tmp_path):
    p = Pair(tmp_path)
    p.run(1)
    for side in (p.py, p.c):
        with open(side / 'SEASLINE.DAT', 'ab') as f:
            f.write(bytes(37))
    p.run(2)
    assert [x['season'] for x in p.lines()] == [1, 1, 2, 2]


def test_pitcher_batter_negative_war_and_capped_stat(tmp_path):
    p = Pair(tmp_path)
    p.run(1, setup=custom_league)
    lines = p.lines()
    assert [x['flags'] for x in lines] == [1, 0, 0]
    assert [x['entry'] for x in lines] == [0, 1, 2]
    pitcher, cf, twob = lines
    assert cf['war10'] < 0, cf['war10']                       # a negative season WAR10 (s16, clamped)
    assert pitcher['pos1'] == 0 and cf['pos1'] == 7 and twob['pos1'] == 3
    assert twob['stats'][history.TOTALS.index('SO')] == 0xffff   # 70000 capped
    assert twob['stats'][history.TOTALS.index('AB')] == 500
    assert twob['face'] == 1234 and twob['b29'] == 0x9d and twob['dev'] == 4
    expect = [(RATINGS[k] + 2) & 15 for k in ORDER]
    expect[ORDER.index('speed')] = 9      # byte 29 (= speed's byte) is set to 0x9d after the ratings
    assert twob['ratings'] == expect
    assert pitcher['stats'][history.TOTALS.index('ER')] == 40


# ---------------- /LINES: the backfill ----------------

def backfill_both(tmp_path, hp, seasons, tag='bf'):
    """history.backfill_lines and HISTWR /LINES, each on its own copy of HISTORY.DAT (the archives are
    read in place). Returns (python count, py dir, c dir)."""
    py, c = tmp_path / (tag + '_py'), tmp_path / (tag + '_c')
    for d in (py, c):
        d.mkdir()
        shutil.copy(hp, d / 'HISTORY.DAT')
    before = Path(hp).read_bytes()
    n = history.backfill_lines(str(py / 'HISTORY.DAT'), str(seasons))
    rc = host('/LINES', str(c / 'HISTORY.DAT'), str(seasons))
    assert rc.returncode == 0, rc.stderr
    assert (c / 'HISTORY.DAT').read_bytes() == before, 'HISTORY.DAT changed by /LINES'
    assert (py / 'HISTORY.DAT').read_bytes() == before, 'HISTORY.DAT changed by backfill_lines'
    return n, py, c


def test_lines_two_archives_match_seasons(tmp_path):
    ldir, hp, seasons, want = make_backfill(tmp_path)
    (ldir / 'SEASLINE.DAT').unlink()
    n, py, c = backfill_both(tmp_path, hp, seasons)
    assert n == 2
    assert (c / 'SEASLINE.DAT').read_bytes() == (py / 'SEASLINE.DAT').read_bytes() == want


def test_lines_unmatched_archive_is_skipped(tmp_path):
    ldir, hp, seasons, want = make_backfill(tmp_path)
    (ldir / 'SEASLINE.DAT').unlink()
    x = seasons / 'S03'
    x.mkdir()
    pre_roll_league(x, 3, (33, 129))                         # W-L matches no recorded season
    n, py, c = backfill_both(tmp_path, hp, seasons)
    assert n == 2
    assert (c / 'SEASLINE.DAT').read_bytes() == (py / 'SEASLINE.DAT').read_bytes() == want


def test_lines_identical_wl_lower_season_to_first_archive(tmp_path):
    """Seasons 1 and 2 with the same W-L: S01 (the first archive) takes season 1, S02 takes season 2."""
    ldir = tmp_path / 'TEAMS' / 'CLASSIC'
    ldir.mkdir(parents=True)
    seasons = tmp_path / 'SEASONS'
    hp = str(ldir / 'HISTORY.DAT')
    for s in (1, 2):
        pre_roll_league(ldir, s, (95, 67))
        arch = seasons / ('S%02d' % s)
        arch.mkdir(parents=True)
        for name in ('CLASALE1.V20', 'CLASSIC.MAJ'):
            shutil.copy(str(ldir / name), str(arch / name))
        history.record_season(str(ldir), hp, s, {})
    want = (ldir / 'SEASLINE.DAT').read_bytes()
    (ldir / 'SEASLINE.DAT').unlink()
    n, py, c = backfill_both(tmp_path, hp, seasons)
    assert n == 2
    assert (c / 'SEASLINE.DAT').read_bytes() == (py / 'SEASLINE.DAT').read_bytes() == want


def test_lines_park_factor_is_per_archive(tmp_path):
    """S01 has park games for clasale1 (park factor 1100), S02 none: S02's batter lines use its own
    park factor (1000), not S01's left over in the run state."""
    ldir = tmp_path / 'TEAMS' / 'CLASSIC'
    ldir.mkdir(parents=True)
    seasons = tmp_path / 'SEASONS'
    hp = str(ldir / 'HISTORY.DAT')
    for s, wl, park in ((1, (95, 67), True), (2, (88, 74), False)):
        custom_league(ldir, wl, park)
        arch = seasons / ('S%02d' % s)
        arch.mkdir(parents=True)
        for name in ('CLASALE1.V20', 'CLASSIC.MAJ'):
            shutil.copy(str(ldir / name), str(arch / name))
        history.record_season(str(ldir), hp, s, {})
    want = (ldir / 'SEASLINE.DAT').read_bytes()
    (ldir / 'SEASLINE.DAT').unlink()
    n, py, c = backfill_both(tmp_path, hp, seasons)
    assert n == 2
    assert (c / 'SEASLINE.DAT').read_bytes() == (py / 'SEASLINE.DAT').read_bytes() == want


def test_lines_header_highest_is_the_highest_matched_season(tmp_path):
    """Only the season 1 archive present: the file keeps season 1's lines and header 6..7 = 1; with no
    archive matching at all, the file is the bare header (highest 0)."""
    ldir, hp, seasons, want = make_backfill(tmp_path)
    (ldir / 'SEASLINE.DAT').unlink()
    shutil.rmtree(str(seasons / 'S02'))
    n, py, c = backfill_both(tmp_path, hp, seasons)
    assert n == 1
    raw = (c / 'SEASLINE.DAT').read_bytes()
    assert struct.unpack_from('<H', raw, 6)[0] == 1
    assert (c / 'SEASLINE.DAT').read_bytes() == (py / 'SEASLINE.DAT').read_bytes()
    assert [x['season'] for x in history.read_lines(str(c / 'SEASLINE.DAT'))] == [1, 1]
    shutil.rmtree(str(seasons / 'S01'))
    (seasons / 'S01').mkdir()                                  # no MAJ: nothing matches
    n, py, c = backfill_both(tmp_path, hp, seasons, tag='none')
    assert n == 0
    assert (c / 'SEASLINE.DAT').read_bytes() == (py / 'SEASLINE.DAT').read_bytes()
    assert len((c / 'SEASLINE.DAT').read_bytes()) == 16
    assert struct.unpack_from('<H', (c / 'SEASLINE.DAT').read_bytes(), 6)[0] == 0


def test_lines_dir_without_maj_and_non_snn_dirs_are_ignored(tmp_path):
    ldir, hp, seasons, want = make_backfill(tmp_path)
    (ldir / 'SEASLINE.DAT').unlink()
    no_maj = seasons / 'S04'                                # Snn with no MAJ: skipped
    no_maj.mkdir()
    shutil.copy(str(ldir / 'CLASALE1.V20'), str(no_maj / 'CLASALE1.V20'))
    for name in ('X01', 'S1', 'S100'):                      # not Snn: ignored, although the W-L would match
        d = seasons / name
        d.mkdir()
        for f in ('CLASALE1.V20', 'CLASSIC.MAJ'):
            shutil.copy(str(seasons / 'S01' / f), str(d / f))
    n, py, c = backfill_both(tmp_path, hp, seasons)
    assert n == 2
    assert (c / 'SEASLINE.DAT').read_bytes() == (py / 'SEASLINE.DAT').read_bytes() == want


def test_lines_record_without_entry_gets_no_line(tmp_path):
    """A player in an archive that HISTORY.DAT never recorded: no line for him, the others as Python."""
    ldir, hp, seasons, want = make_backfill(tmp_path)
    (ldir / 'SEASLINE.DAT').unlink()
    path = seasons / 'S01' / 'CLASALE1.V20'
    t = Team(path.read_bytes())
    set_player(t, 30, 'NEWGUY', 'NEW', 22, 3, 100)
    t.save(str(path))
    n, py, c = backfill_both(tmp_path, hp, seasons)
    assert n == 2
    lines = history.read_lines(str(c / 'SEASLINE.DAT'))
    assert len(lines) == 4                                  # 2 in season 1 (no NEWGUY), 2 in season 2
    assert (c / 'SEASLINE.DAT').read_bytes() == (py / 'SEASLINE.DAT').read_bytes()


def test_lines_existing_seasline_unchanged(tmp_path):
    ldir, hp, seasons, want = make_backfill(tmp_path)
    before = (ldir / 'SEASLINE.DAT').read_bytes()
    hist_before = Path(hp).read_bytes()
    rc = host('/LINES', hp, str(seasons))
    assert rc.returncode == 0, rc.stderr
    assert (ldir / 'SEASLINE.DAT').read_bytes() == before == want
    assert Path(hp).read_bytes() == hist_before


def test_lines_without_history_writes_nothing(tmp_path):
    seasons = tmp_path / 'SEASONS'
    (seasons / 'S01').mkdir(parents=True)
    pre_roll_league(seasons / 'S01', 1)
    lg = tmp_path / 'none'
    lg.mkdir()
    rc = host('/LINES', str(lg / 'HISTORY.DAT'), str(seasons))
    assert rc.returncode == 0, rc.stderr
    assert not (lg / 'SEASLINE.DAT').exists()


def test_lines_zero_seasons_writes_nothing(tmp_path):
    ldir, hp, seasons, want = make_backfill(tmp_path)
    (ldir / 'SEASLINE.DAT').unlink()
    zero = tmp_path / 'zero'
    zero.mkdir()
    Path(zero / 'HISTORY.DAT').write_bytes(bytes(history.PLAYER_TABLE))   # seasons recorded 0
    rc = host('/LINES', str(zero / 'HISTORY.DAT'), str(seasons))
    assert rc.returncode == 0, rc.stderr
    assert not (zero / 'SEASLINE.DAT').exists()


def test_lines_args_case_insensitive_and_usage(tmp_path):
    ldir, hp, seasons, want = make_backfill(tmp_path)
    (ldir / 'SEASLINE.DAT').unlink()
    c = tmp_path / 'c'
    c.mkdir()
    shutil.copy(hp, c / 'HISTORY.DAT')
    rc = host('/lines', str(c / 'HISTORY.DAT'), str(seasons))
    assert rc.returncode == 0, rc.stderr
    assert (c / 'SEASLINE.DAT').read_bytes() == want
    bad = tmp_path / 'bad'
    bad.mkdir()
    shutil.copy(hp, bad / 'HISTORY.DAT')
    rc = host('/LINES', str(bad / 'HISTORY.DAT'))            # one path short: usage, exit 2
    assert rc.returncode == 2
    assert not (bad / 'SEASLINE.DAT').exists()


def test_lines_defaults_in_empty_dir(tmp_path):
    rc = host('/LINES', cwd=str(tmp_path))
    assert rc.returncode == 0, rc.stderr
    assert os.listdir(str(tmp_path)) == []


def test_fail_rename_keeps_seasline_and_history(tmp_path):
    """A failing last rename (SEASLINE.DAT, host build with -DTEST_FAIL_RENAME) on season 2: all four
    files byte-identical to before the run, rc 2, no TMP or BAK left."""
    hc = os.path.join(TH.HERE_H, 'histwr_host_failrename_lines')
    p = Pair(tmp_path)
    p.run(1)
    before = {name: (p.c / name).read_bytes() for name in ('H.DAT', 'MILESTON.DAT', 'BOXSCORE.DAT',
                                                            'SEASLINE.DAT') if (p.c / name).exists()}
    TH._build_special(hc, ['-DTEST_FAIL_RENAME'])
    try:
        rc = subprocess.run([hc, str(p.ldir), str(p.c / 'H.DAT'), str(p.ret)],
                            capture_output=True, text=True)
    finally:
        if os.path.exists(hc):
            os.remove(hc)
    assert rc.returncode == 2, rc.returncode
    for name, data in before.items():
        assert (p.c / name).read_bytes() == data, f'{name} not restored'
    for leftover in ('HISTWR.TMP', 'HISTWR.BAK', 'MILESTON.TMP', 'MILESTON.BAK',
                     'BOXSCORE.TMP', 'BOXSCORE.BAK', 'SEASLINE.TMP', 'SEASLINE.BAK'):
        assert not (p.c / leftover).exists(), f'{leftover} left'


@pytest.mark.skipif(not os.path.isdir(TH.WATCOM), reason='OpenWatcom not installed')
def test_dos_build_exit_zero():
    r = subprocess.run([sys.executable, os.path.join(TH.HERE_H, 'build_histwr.py')],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
