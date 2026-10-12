#!/usr/bin/env python3
"""Tests for the C13.2 SEASLINE.DAT writer and backfill, and the C13.1 start year (tools/m4/history.py).
Run:  python3 -m pytest -q tools/m4/test_seaslines.py
Synthetic fixtures only (the builders of test_history.py): V20 teams, CLASSIC.MAJ, HISTORY.DAT in tmp_path.
"""
import sys, os, struct, shutil, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import history
import war
from v20 import Team, F, _set
from test_history import make_team_v20, make_maj, set_player

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = ['power', 'bunt', 'hit_run', 'speed', 'range', 'arm', 'control', 'velocity', 'endurance']
RATINGS = {'power': 7, 'bunt': 3, 'hit_run': 12, 'speed': 9, 'range': 5, 'arm': 11,
           'control': 6, 'velocity': 14, 'endurance': 2}


def record_pair(pitcher):
    """Roster half and season half of one hand-built player: a pitcher in slot 2 (pos1 0) or a CF in slot
    21 (pos1 7). Byte 29 0x9d = speed 9, bats S, throws R, flag bit 0; dev grade 4; face 1234."""
    t = Team(make_team_v20())
    i, pos1 = (2, 0) if pitcher else (21, 7)
    set_player(t, i, 'BONDS', 'BARRY', 27, pos1, 150)
    roster, rec = t.players[i].raw, t.players[i + 40].raw
    roster[history.B29_OFF] = 0x9d
    roster[history.DEV_OFF] = 4
    _set(roster, *F['portrait'], 1234)
    for k in ORDER:
        _set(roster, *F[k], RATINGS[k])
    for k, v in (('ab_l', 500), ('ab_r', 20), ('h_l', 150), ('h_r', 10), ('d_l', 30), ('t_l', 2),
                 ('hr_l', 15), ('runs', 75), ('rbi', 90), ('bb_l', 50), ('so_l', 100), ('sb', 8),
                 ('cs', 3), ('ip10', 1000), ('er', 40)):
        _set(rec, *F[k], v)
    return roster, rec


def pre_roll_league(ldir, season, wl=(95, 67)):
    """The pre-roll league of one season in ldir: CLASALE1 (team id 0) with a pitcher (slot 2) and a CF
    (slot 21), both one year older each season so their identities carry across seasons; CLASSIC.MAJ
    with team 0 at wl."""
    m = make_maj()
    m.set_wl('AL', 0, *wl)
    m.save(str(ldir / 'CLASSIC.MAJ'))
    t = Team(make_team_v20())
    set_player(t, 2, 'ACE', 'ART', 25 + season - 1, 0, 30)
    set_player(t, 21, 'BONDS', 'BARRY', 27 + season - 1, 7, 150)
    _set(t.players[42].raw, *F['ip10'], 900 + 30 * season)
    _set(t.players[42].raw, *F['er'], 40 + season)
    _set(t.players[61].raw, *F['ab_l'], 480 + 20 * season)
    _set(t.players[61].raw, *F['h_l'], 140 + season)
    t.save(str(ldir / 'CLASALE1.V20'))


def make_backfill(tmp_path):
    """Two recorded seasons, each with a Snn archive of its pre-roll league. Returns (ldir, hist path,
    seasons dir, the SEASLINE.DAT that record_season wrote)."""
    ldir = tmp_path / 'TEAMS' / 'CLASSIC'
    ldir.mkdir(parents=True)
    seasons = tmp_path / 'SEASONS'
    hp = str(ldir / 'HISTORY.DAT')
    for s, wl in ((1, (95, 67)), (2, (88, 74))):
        pre_roll_league(ldir, s, wl)
        arch = seasons / ('S%02d' % s)
        arch.mkdir(parents=True)
        for name in ('CLASALE1.V20', 'CLASSIC.MAJ'):
            shutil.copy(str(ldir / name), str(arch / name))
        history.record_season(str(ldir), hp, s, {})
    return ldir, hp, seasons, (ldir / 'SEASLINE.DAT').read_bytes()


@pytest.mark.parametrize('pitcher', [False, True])
def test_line_layout(pitcher):
    """Every C13.2 field offset on a hand-built record pair."""
    roster, rec = record_pair(pitcher)
    pos1 = 0 if pitcher else 7
    # the fixture's own bytes: ratings sit in the nibbles C13.2 names (74 hi bunt lo power, 75 lo H&R,
    # 94 hi range lo arm, 134 hi velocity lo control, 135 hi endurance)
    assert roster[74] == (3 << 4) | 7 and roster[75] & 15 == 12
    assert roster[94] == (5 << 4) | 11 and roster[134] == (14 << 4) | 6 and roster[135] >> 4 == 2
    totals = war.season_stats_inputs(rec)
    b = history.line_bytes(5, 3, 17, roster, rec, -12, totals)
    assert len(b) == history.LINE_SIZE == 80
    assert struct.unpack_from('<H', b, 0)[0] == 5          # 0 u16 player entry index
    assert struct.unpack_from('<H', b, 2)[0] == 3          # 2 u16 season_no
    assert b[4] == 17                                      # 4 u8 stable team id
    assert b[5] == (1 if pitcher else 0)                   # 5 u8 flags, bit0 pitcher (pos1 == 0)
    assert b[6] == 27                                      # 6 u8 age (roster half)
    assert b[7] == pos1                                    # 7 u8 pos1 & 15
    assert struct.unpack_from('<H', b, 8)[0] == 1234       # 8 u16 face (roster half +27)
    assert b[10] == 0x9d                                   # 10 u8 roster half byte 29 raw
    assert b[11] == 4                                      # 11 u8 dev grade (byte 142)
    assert list(b[12:21]) == [RATINGS[k] for k in ORDER]   # 12..20 nibbles, C13.2 order
    assert b[21] == 0
    stats = struct.unpack_from('<25H', b, 22)              # 22..71 u16 TOTALS order
    assert list(stats) == [totals[k] for k in history.TOTALS]
    assert stats[history.TOTALS.index('G')] == 150 and stats[history.TOTALS.index('H')] == 160
    assert struct.unpack_from('<h', b, 72)[0] == -12       # 72 s16 WAR10
    assert b[74:80] == bytes(6)


def test_line_stats_capped_at_ffff():
    roster, rec = record_pair(False)
    totals = war.season_stats_inputs(rec)
    totals['AB'] = 70000
    b = history.line_bytes(0, 1, 0, roster, rec, 0, totals)
    assert struct.unpack_from('<H', b, 22 + 2 * history.TOTALS.index('AB'))[0] == 0xffff


def test_header_and_read_lines_round_trip(tmp_path):
    roster, rec = record_pair(True)
    line = history.line_bytes(9, 4, 2, roster, rec, 37, war.season_stats_inputs(rec))
    p = str(tmp_path / 'SEASLINE.DAT')
    history.write_lines(p, [line], 4)
    raw = open(p, 'rb').read()
    assert len(raw) == 16 + 80
    assert raw[0:2] == b'SL' and raw[2] == 1 and raw[3] == 0
    assert struct.unpack_from('<H', raw, 4)[0] == 80
    assert struct.unpack_from('<H', raw, 6)[0] == 4        # highest season written
    assert raw[8:16] == bytes(8)
    (d,) = history.read_lines(p)
    assert d['entry'] == 9 and d['season'] == 4 and d['team'] == 2 and d['flags'] == 1
    assert d['age'] == 27 and d['pos1'] == 0 and d['face'] == 1234 and d['b29'] == 0x9d
    assert d['dev'] == 4 and d['ratings'] == [RATINGS[k] for k in ORDER]
    assert d['stats'][history.TOTALS.index('H')] == 160 and d['war10'] == 37


def test_read_lines_missing_bad_header_and_tail(tmp_path):
    p = tmp_path / 'SEASLINE.DAT'
    assert history.read_lines(str(p)) == []                 # missing
    p.write_bytes(b'XL' + bytes(14) + bytes(80))
    assert history.read_lines(str(p)) == []                 # bad magic
    p.write_bytes(b'SL\x01\x00' + struct.pack('<HH', 64, 0) + bytes(8) + bytes(80))
    assert history.read_lines(str(p)) == []                 # wrong line size
    p.write_bytes(b'SL\x01\x00' + struct.pack('<HH', 80, 2) + bytes(8) + bytes(80) + bytes(5))
    assert len(history.read_lines(str(p))) == 1             # a short tail is dropped


def test_record_season_lines_not_duplicated(tmp_path):
    """record_season twice for season 1, then once for season 2: season 1 lines not duplicated,
    header 6..7 = 2."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    hp = str(ldir / 'HISTORY.DAT')
    sl = ldir / 'SEASLINE.DAT'
    pre_roll_league(ldir, 1)
    history.record_season(str(ldir), hp, 1, {})
    once = sl.read_bytes()
    history.record_season(str(ldir), hp, 1, {})
    assert sl.read_bytes() == once
    pre_roll_league(ldir, 2)
    history.record_season(str(ldir), hp, 2, {})
    raw = sl.read_bytes()
    assert struct.unpack_from('<H', raw, 6)[0] == 2
    lines = history.read_lines(str(sl))
    assert [x['season'] for x in lines] == [1, 1, 2, 2]
    assert [x['entry'] for x in lines] == [0, 1, 0, 1]      # pitcher (slot 2) first, then the CF
    assert [x['flags'] for x in lines] == [1, 0, 1, 0]
    assert all(x['team'] == 0 for x in lines)


def test_record_season_no_64_cap(tmp_path):
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    hp = str(ldir / 'HISTORY.DAT')
    pre_roll_league(ldir, 65)
    history.record_season(str(ldir), hp, 65, {})
    lines = history.read_lines(str(ldir / 'SEASLINE.DAT'))
    assert [x['season'] for x in lines] == [65, 65]
    assert struct.unpack_from('<H', (ldir / 'SEASLINE.DAT').read_bytes(), 6)[0] == 65


def test_other_outputs_unchanged_without_seaslines(tmp_path, monkeypatch):
    """The SEASLINE rewrite adds a file and changes nothing else: HISTORY, MILESTON and BOXSCORE bytes
    match a run with write_lines stubbed out."""
    outs = {}
    for tag in ('with', 'without'):
        if tag == 'without':
            monkeypatch.setattr(history, 'write_lines', lambda *a, **k: None)
        ldir = tmp_path / tag
        ldir.mkdir()
        hp = str(ldir / 'HISTORY.DAT')
        for s in (1, 2):
            pre_roll_league(ldir, s, (95 - s, 67 + s))
            history.record_season(str(ldir), hp, s, {})
        outs[tag] = [(ldir / n).read_bytes() for n in ('HISTORY.DAT', 'MILESTON.DAT', 'BOXSCORE.DAT')]
        assert (ldir / 'SEASLINE.DAT').exists() == (tag == 'with')
    assert outs['with'] == outs['without']


def test_backfill_matches_record_season(tmp_path):
    ldir, hp, seasons, want = make_backfill(tmp_path)
    sl = ldir / 'SEASLINE.DAT'
    hist_before = open(hp, 'rb').read()
    marks = [(ldir / n).read_bytes() for n in ('MILESTON.DAT', 'BOXSCORE.DAT')]
    sl.unlink()
    assert history.backfill_lines(hp, str(seasons)) == 2
    assert sl.read_bytes() == want
    assert open(hp, 'rb').read() == hist_before
    assert [(ldir / n).read_bytes() for n in ('MILESTON.DAT', 'BOXSCORE.DAT')] == marks
    # a second call does nothing: the file exists now
    assert history.backfill_lines(hp, str(seasons)) == 0
    assert sl.read_bytes() == want


def test_backfill_skips_archive_matching_no_season(tmp_path):
    ldir, hp, seasons, want = make_backfill(tmp_path)
    x = seasons / 'S03'
    x.mkdir()
    pre_roll_league(x, 3, (33, 129))                        # W-L matches no recorded season
    sl = ldir / 'SEASLINE.DAT'
    sl.unlink()
    assert history.backfill_lines(hp, str(seasons)) == 2
    assert sl.read_bytes() == want


def test_backfill_needs_history_with_seasons(tmp_path):
    seasons = tmp_path / 'SEASONS'
    (seasons / 'S01').mkdir(parents=True)
    pre_roll_league(seasons / 'S01', 1)
    lg = tmp_path / 'none'
    lg.mkdir()
    assert history.backfill_lines(str(lg / 'HISTORY.DAT'), str(seasons)) == 0
    assert not (lg / 'SEASLINE.DAT').exists()               # no HISTORY.DAT: nothing written


def test_backfill_cli_prints_count(tmp_path):
    ldir, hp, seasons, want = make_backfill(tmp_path)
    (ldir / 'SEASLINE.DAT').unlink()
    out = subprocess.run([sys.executable, os.path.join(HERE, 'history.py'), 'lines', hp, str(seasons)],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == '2'
    assert (ldir / 'SEASLINE.DAT').read_bytes() == want


def test_year_of_default_and_set():
    h = history.History(None)
    assert h.start_year == 0
    assert history.year_of(h, 1) == 1993                    # 0 counts as the shipped 1993
    h.start_year = 1950
    assert history.year_of(h, 3) == 1952
    for bad in (0, 1870, 2101, 65535):
        h.start_year = bad
        assert history.year_of(h, 1) == 1993
    for ok in (1871, 2100):
        h.start_year = ok
        assert history.year_of(h, 1) == ok


def test_start_year_write_keeps_other_header_bytes():
    raw = bytes(range(1, 33))
    h = history.History(raw)
    h.start_year = 1950
    assert bytes(h.d[0:18]) == raw[0:18]
    assert bytes(h.d[20:32]) == raw[20:32]
    assert bytes(h.d[18:20]) == struct.pack('<H', 1950)
    assert h.start_year == 1950
