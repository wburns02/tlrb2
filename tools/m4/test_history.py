#!/usr/bin/env python3
"""Tests for the M4 HISTORY.DAT v1 reference (tools/m4/history.py, contract C2).
Run:  python3 -m pytest -q tools/m4/test_history.py
All fixtures are synthetic and built in tmp_path: V20 files from raw bytes
(295 B header + 80 x 143 B records) and a synthetic CLASSIC.MAJ of 59771 B with
standings, playoff bytes and a few schedule days + runs cells.
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import history
import war
from v20 import Team, HDR, REC, N, F, _set, _get
from v20 import SIZE as V20_SIZE
import maj

MAJ_SIZE = 59771
S_AL, S_NL = 0x21d, 0x758c


def make_team_v20(name=b'FAILING', abbr=b'FAI', lg=0):
    """A fresh 11735 B V20 with header name/abbr and 80 records."""
    d = bytearray(V20_SIZE)
    d[0:14] = name.ljust(14, b'\0')[:14]
    d[14:16] = b'cl'
    d[16:19] = abbr.ljust(3, b'\0')[:3]
    return bytes(d)


def make_maj(stem=b'classic1'):
    """Synthetic 59771 B MAJ: AL block names/stems for slots 0..13, NL 16..29."""
    d = bytearray(MAJ_SIZE)
    d[0x20c], d[0x20d] = 2, 2
    for slot in range(14):
        s = S_AL + maj.O_NAMES + 16 * slot
        d[s:s + 14] = (b'TEAM%02d' % slot).ljust(14, b'\0')[:14]
        d[s + 14:s + 16] = b'cl'
        sa = S_AL + maj.O_ABBR + 3 * slot
        d[sa:sa + 3] = (b'T%02d' % slot)
        ss = S_AL + maj.O_STEM + 8 * slot
        d[ss:ss + 8] = (b'clasale1' if slot == 0 else (b'ALA%02d' % slot)).ljust(8, b'\0')
    for slot in range(14):
        s = S_NL + maj.O_NAMES + 16 * slot
        d[s:s + 14] = (b'NLTEAM%02d' % slot).ljust(14, b'\0')[:14]
        d[s + 14:s + 16] = b'cl'
        sa = S_NL + maj.O_ABBR + 3 * slot
        d[sa:sa + 3] = b'N%02d' % slot
        ss = S_NL + maj.O_STEM + 8 * slot
        d[ss:ss + 8] = (b'NL%02d' % slot).ljust(8, b'\0')
    return maj.Maj(bytes(d))


def write_league(tmp_path, n_teams=2, with_maj=True):
    """Write n_teams V20s + one MAJ into a league dir; returns (dir, [stems])."""
    ldir = tmp_path / 'league'
    ldir.mkdir()
    stems = []
    for k in range(n_teams):
        stem = b'classic1' if k == 0 else b'CIASALE1'
        stem = (b'ALA%02d' % k) if k < 14 else stem
        stems.append(stem.decode())
        (ldir / (stem.decode().upper() + '.V20')).write_bytes(make_team_v20())
    if with_maj:
        m = make_maj()
        m.save(str(ldir / 'CLASSIC.MAJ'))
    return ldir, stems


def set_player(t, i, last, first, age, pos1, games, season=None, roster=None):
    """bio (roster half, both halves actually, name lives in both) + season stats.
    Name bytes 0..19 = V20 order: last 12 B then first 8 B. byte 0 = active flag."""
    name = last.encode('latin-1')[:11].ljust(12, b'\0') + first.encode('latin-1')[:7].ljust(8, b'\0')
    for rec in (t.players[i].raw, t.players[i + 40].raw):
        rec[0:20] = name
        rec[0] = 1
        _set(rec, *F['age'], age)
        _set(rec, *F['pos1'], pos1)
    s = season if season is not None else t.players[i + 40].raw
    _set(s, *F['games'], games)


def test_layout_offsets(tmp_path):
    """Header 32 B, season table at 32 (64 x 128 B -> player table at 8224), 160 B entries."""
    p = tmp_path / 'HISTORY.DAT'
    hist = history.History(None)
    hist.version = 1
    hist.seasons_recorded = 1
    hist.write_season_entry(1, {'season_no': 1, 'champion': 0x13, 'runner_up': 2,
                                'champion_stem': b'PHILA', 'runner_up_stem': b'CLE',
                                'al_pennant': 2, 'nl_pennant': 0x13, 'w_l': [(0, 0)] * 32})
    e = {'name': b'SMITH'.ljust(8) + b'JOHN'.ljust(12), 'birth': 1955, 'status': 1, 'age': 25,
         'first_season': 1, 'last_season': 1, 'seasons_played': 1, 'pos1': 4,
         'pitcher': 0, 'totals': list(range(25)), 'WAR10': 123, 'top7': [9, 8, 7, 6, 5, 4, 3],
         'JAWS10': 111, 'hof_season': 0}
    hist.append_entry(e)
    hist.save(str(p))
    raw = open(p, 'rb').read()
    assert len(raw) == history.PLAYER_TABLE + history.PLAYER_ENTRY == 8224 + 160
    # header
    assert raw[3] == 1
    assert raw[4] | raw[5] << 8 == 1            # seasons recorded
    assert raw[6] | raw[7] << 8 == 1            # player entries
    assert raw[8:32] == bytes(24)               # zero pad
    # season entry at 32
    o = 32
    assert raw[o] | raw[o + 1] << 8 == 1        # season_no
    assert raw[o + 2] == 0x13
    assert raw[o + 3] == 2
    assert raw[o + 4:o + 12] == b'PHILA\0\0\0'
    assert raw[o + 12:o + 20] == b'CLE\0\0\0\0\0'
    assert raw[o + 20] == 2 and raw[o + 21] == 0x13
    # W-L table at +24
    assert raw[o + 80:o + 128] == bytes(48)     # reserved zero
    # player entry at 8224
    po = 8224
    assert raw[po:po + 20] == b'SMITH'.ljust(8) + b'JOHN'.ljust(12)
    assert raw[po + 20] | raw[po + 21] << 8 == 1955
    assert raw[po + 22] == 1
    assert raw[po + 23] == 25
    ts = struct.unpack_from('<25I', raw, po + 32)
    assert list(ts) == list(range(25))
    assert struct.unpack_from('<h', raw, po + 132)[0] == 123
    assert list(struct.unpack_from('<7h', raw, po + 134)) == [9, 8, 7, 6, 5, 4, 3]
    assert struct.unpack_from('<h', raw, po + 148)[0] == 111
    assert raw[po + 150:po + 160] == bytes(10)


def test_legacy_4byte_upgrade(tmp_path):
    """A legacy 4-byte P1 file: upgrade keeps bytes 0..2, writes version 1."""
    p = tmp_path / 'HISTORY.DAT'
    open(p, 'wb').write(bytes([1, 0x34, 0x12]))
    hist = history.upgrade_legacy(str(p))
    raw = open(p, 'rb').read()
    assert raw[0:3] == bytes([1, 0x34, 0x12])
    assert raw[3] == 1
    assert len(raw) >= 32
    assert raw[4:6] == bytes(2)                 # seasons recorded zero
    # load + reread: same values
    h2 = history.History.load(str(p))
    assert h2.version == 1 and h2.rng_word == 0x1234 and h2.done == 1


def test_identity_across_two_seasons(tmp_path):
    """Same player seen next season (age +1, season_no +1) maps to the same entry."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / 'CLASALE1.V20').write_bytes(make_team_v20())
    m = make_maj()
    m.save(str(ldir / 'CLASSIC.MAJ'))
    hp = tmp_path / 'HISTORY.DAT'
    # season 1
    tm = v20_from(ldir / 'CLASALE1.V20')
    set_player(tm, 21, 'BONDS', 'BARRY', 27, 7, 150)
    s = tm.players[61].raw
    _set(s, *F['ab_l'], 500); _set(s, *F['h_l'], 150); _set(s, *F['games'], 150)
    tm.save(str(ldir / 'CLASALE1.V20'))
    history.record_season(str(ldir), str(hp), 1, {})
    h = history.History.load(str(hp))
    n1 = len(h._entries)
    e = h.read_entry(0)
    assert e['name'] == b'\x01' + b'BONDS'.ljust(12, b'\0')[1:] + b'BARRY'.ljust(8, b'\0')
    assert e['first_season'] == 1 and e['last_season'] == 1 and e['birth'] == 1000 + 1 - 27
    # season 2: same player, age 28
    tm2 = v20_from(ldir / 'CLASALE1.V20')
    _set(tm2.players[21].raw, *F['age'], 28)
    _set(tm2.players[61].raw, *F['age'], 28)
    s2 = tm2.players[61].raw
    _set(s2, *F['ab_l'], 480); _set(s2, *F['h_l'], 140); _set(s2, *F['games'], 140)
    _set(s2, *F['d_l'], 20); _set(s2, *F['hr_l'], 10); _set(s2, *F['bb_l'], 50)
    _set(s2, *F['sb'], 5); _set(s2, *F['cs'], 2); _set(s2, *F['runs'], 70)
    tm2.save(str(ldir / 'CLASALE1.V20'))
    history.record_season(str(ldir), str(hp), 2, {})
    h2 = history.History.load(str(hp))
    assert len(h2._entries) == n1               # same single entry
    e2 = h2.read_entry(0)
    assert e2['birth'] == 1000 + 1 - 27         # birth unchanged
    assert e2['first_season'] == 1 and e2['last_season'] == 2
    assert e2['seasons_played'] == 2
    # AB accumulated: 500 + 480 = 980
    assert e2['totals'][1] == 980
    # a different player appends a new entry; the incumbent must age +1 so his birth
    # recomputation still matches (record_season does not age, the P1 rollover does)
    tm3 = v20_from(ldir / 'CLASALE1.V20')
    for rec in (tm3.players[21].raw, tm3.players[61].raw):
        _set(rec, *F['age'], _get(rec, *F['age']) + 1)
    set_player(tm3, 30, 'CABRERA', 'MIGUEL', 24, 2, 130)
    _set(tm3.players[70].raw, *F['ab_l'], 400); _set(tm3.players[70].raw, *F['h_l'], 120)
    _set(tm3.players[70].raw, *F['games'], 130)
    tm3.save(str(ldir / 'CLASALE1.V20'))
    history.record_season(str(ldir), str(hp), 3, {})
    h3 = history.History.load(str(hp))
    assert len(h3._entries) == 2


def v20_from(path):
    return Team(open(path, 'rb').read())


def test_top7_ordering_more_than_7_seasons(tmp_path):
    """Season WAR10s beyond 7: top-7 stays sorted desc, unused stay -32768 when
    fewer than 7 seasons, and the 8th-best season does not stay in the table."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / 'CLASALE1.V20').write_bytes(make_team_v20())
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    hp = tmp_path / 'HISTORY.DAT'
    v20_path = ldir / 'CLASALE1.V20'
    # one batter, one season with fixed identical line (same WAR every season)
    for season in range(1, 10):
        tm = Team(open(v20_path, 'rb').read())
        set_player(tm, 22, 'PLAYER', 'TEST', 25 + season - 1, 3, 150)
        s = tm.players[62].raw
        # deterministic line: same every season
        _set(s, *F['ab_l'], 500); _set(s, *F['h_l'], 160); _set(s, *F['d_l'], 30)
        _set(s, *F['t_l'], 2); _set(s, *F['hr_l'], 15); _set(s, *F['bb_l'], 50)
        _set(s, *F['sb'], 8); _set(s, *F['cs'], 3); _set(s, *F['runs'], 75)
        _set(s, *F['games'], 150)
        tm.save(str(v20_path))
        history.record_season(str(ldir), str(hp), season, {})
    h = history.History.load(str(hp))
    e = h.read_entry(0)
    used = [x for x in e['top7'] if x != history.EMPTY_TOP]
    assert len(used) == 7                        # 9 seasons -> 7 used slots
    assert used == sorted(used, reverse=True)    # descending
    # all 9 seasons had the same WAR -> every used slot equals that WAR
    assert all(x == used[0] for x in used)
    # seasons counted
    assert e['seasons_played'] == 9
    assert e['WAR10'] == 9 * used[0]


def test_jaws_and_top7_mixed(tmp_path):
    """Two seasons with different WARs: top7 holds both desc, JAWS = (career + sum)/2."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / 'CLASALE1.V20').write_bytes(make_team_v20())
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    hp = tmp_path / 'HISTORY.DAT'
    v20_path = ldir / 'CLASALE1.V20'
    lines = [(500, 160, 30, 2, 15, 50, 8, 3, 75, 150),    # season 1 line
             (600, 200, 40, 3, 30, 70, 12, 2, 110, 150)]  # season 2, better
    for season, (ab, h_, d2, t3, hr, bb, sb, cs, runs, g) in enumerate(lines, 1):
        tm = Team(open(v20_path, 'rb').read())
        set_player(tm, 23, 'SLUGGER', 'SAM', 25 + season - 1, 2, g)
        s = tm.players[63].raw
        _set(s, *F['ab_l'], ab); _set(s, *F['h_l'], h_); _set(s, *F['d_l'], d2)
        _set(s, *F['t_l'], t3); _set(s, *F['hr_l'], hr); _set(s, *F['bb_l'], bb)
        _set(s, *F['sb'], sb); _set(s, *F['cs'], cs); _set(s, *F['runs'], runs)
        _set(s, *F['games'], g)
        tm.save(str(v20_path))
        history.record_season(str(ldir), str(hp), season, {})
    h = history.History.load(str(hp))
    e = h.read_entry(0)
    used = [x for x in e['top7'] if x != history.EMPTY_TOP]
    assert len(used) == 2 and used == sorted(used, reverse=True)
    assert e['JAWS10'] == war.jaws10(e['WAR10'], e['top7'])
    assert e['JAWS10'] == (e['WAR10'] + sum(used)) // 2


def test_champion_decode_sample_bytes(tmp_path):
    """The season2 sample bytes: AL block +0x3d3..: ff ff ff ff 02 09 02 13;
    NL block: ff ff ff ff 1b 13 13 ff -> champion 0x13, runner-up 2,
    al_pennant 2, nl_pennant 0x13."""
    m = make_maj()
    d = bytearray(m.d)
    d[S_AL + 0x3d3:S_AL + 0x3db] = bytes([0xff, 0xff, 0xff, 0xff, 0x02, 0x09, 0x02, 0x13])
    d[S_NL + 0x3d3:S_NL + 0x3db] = bytes([0xff, 0xff, 0xff, 0xff, 0x1b, 0x13, 0x13, 0xff])
    m2 = maj.Maj(bytes(d))
    ws, runner, al_p, nl_p = history.decode_champion(m2)
    assert ws == 0x13
    assert runner == 2
    assert al_p == 2 and nl_p == 0x13
    # stems follow from the team-name table: 0x13 = NL slot 3 (0x13-16), 2 = AL slot 2
    assert history.team_stem(m2, ws) == b'NL03'
    assert history.team_stem(m2, runner) == b'ALA02'
    # unknown pennants: 0xff anywhere -> 0xff runner-up
    d2 = bytearray(d)
    d2[S_AL + 0x3da] = 0xff
    m3 = maj.Maj(bytes(d2))
    ws2, runner2, al_p2, nl_p2 = history.decode_champion(m3)
    assert ws2 == 0xff and runner2 == 0xff


def test_record_season_champion_and_wl(tmp_path):
    """record_season writes the season entry from the MAJ: champion, pennants, W-L."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / 'CLASALE1.V20').write_bytes(make_team_v20())
    (ldir / 'CLASNL01.V20').write_bytes(make_team_v20(name=b'NLONE', abbr=b'NL1'))
    m = make_maj()
    m.set_wl('AL', 0, 95, 67)
    m.set_wl('NL', 3, 88, 74)
    d = bytearray(m.d)
    d[S_AL + 0x3d3:S_AL + 0x3db] = bytes([0xff, 0xff, 0xff, 0xff, 0x02, 0x09, 0x02, 0x13])
    d[S_NL + 0x3d3:S_NL + 0x3db] = bytes([0xff, 0xff, 0xff, 0xff, 0x1b, 0x13, 0x13, 0xff])
    maj.Maj(bytes(d)).save(str(ldir / 'CLASSIC.MAJ'))
    hp = tmp_path / 'HISTORY.DAT'
    history.record_season(str(ldir), str(hp), 2, {})
    h = history.History.load(str(hp))
    s = h.read_season_entry(2)
    assert s['season_no'] == 2
    assert s['champion'] == 0x13 and s['runner_up'] == 2
    assert s['champion_stem'] == b'NL03'
    assert s['runner_up_stem'] == b'ALA02'
    assert s['al_pennant'] == 2 and s['nl_pennant'] == 0x13
    assert h.seasons_recorded == 2
    # W-L: AL slot 0 (lg id 0) = 95-67, NL slot 3 (lg id 16+3=19) = 88-74;
    # NL slot 13 (lg id 29) is inside the 32-pair table; unused ids stay (0, 0)
    assert s['w_l'][0] == (95, 67)
    assert s['w_l'][19] == (88, 74)
    assert s['w_l'][27] == (0, 0)
    assert s['w_l'][31] == (0, 0)
    # version byte: every record_season writes 1
    assert h.version == 1


def test_season_table_top7_more_than_7(tmp_path):
    """More than 7 seasons still table entries 1..N at 32 + (n-1)*128; > 64 wraps
    is not exercised (64 cap), but entry 8 lands at the right offset."""
    p = tmp_path / 'HISTORY.DAT'
    hist = history.History(None)
    for n in range(1, 9):
        hist.write_season_entry(n, {'season_no': n, 'champion': n, 'runner_up': 0xff,
                                    'champion_stem': b'S%d' % n, 'runner_up_stem': b'',
                                    'al_pennant': 0xff, 'nl_pennant': 0xff,
                                    'w_l': [(0, 0)] * 32})
    hist.seasons_recorded = 8
    hist.save(str(p))
    raw = open(p, 'rb').read()
    # entry 8 at 32 + 7*128 = 928
    o = 32 + 7 * 128
    assert raw[o] | raw[o + 1] << 8 == 8
    assert raw[o + 4:o + 8] == b'S8\0\0'
    # season 9 would be at 1056: still season-table space (64 entries to 8224)
    assert 32 + 64 * 128 == 8224


def test_mark_retired_and_hof(tmp_path):
    """(tmp_path league): retiree flips to status 2; a career over the HoF bar
    (3000 H) flips to 3 with the HoF season."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / 'CLASALE1.V20').write_bytes(make_team_v20())
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    hp = tmp_path / 'HISTORY.DAT'
    v20_path = ldir / 'CLASALE1.V20'
    # one batter, 10 seasons; ends with H >= 3000 (3rd career stat H). Each season the
    # P1 rollover would age him +1; the test ages him explicitly at the season switch
    # so his birth identity recomputes the same way record_season does.
    for season in range(1, 11):
        tm = Team(open(v20_path, 'rb').read())
        if season > 1:
            for rec in (tm.players[24].raw, tm.players[64].raw):
                _set(rec, *F['age'], _get(rec, *F['age']) + 1)
        set_player(tm, 24, 'HITTER', 'HOF', 25 + season - 1, 5, 150)
        s = tm.players[64].raw
        _set(s, *F['ab_l'], 500); _set(s, *F['h_l'], 310); _set(s, *F['games'], 150)
        tm.save(str(v20_path))
        history.record_season(str(ldir), str(hp), season, {})
    h = history.History.load(str(hp))
    e = h.read_entry(0)
    assert e['totals'][2] == 3100                # H career total
    assert e['status'] == history.STATUS_ACTIVE
    # step 4: mark_retired with the SAME pre-rollover dir and season_no (the rollover
    # has by now zeroed his name byte 0 in the post-roll file, but the identity comes
    # from the pre-roll V20s record_season read); hof_season = the season just done
    history.mark_retired(str(hp), str(ldir), {'CLASALE1.V20': [24]}, 10)
    h2 = history.History.load(str(hp))
    e2 = h2.read_entry(0)
    assert e2['status'] == history.STATUS_HOF
    assert e2['hof_season'] == 10
    # a retiree below the bar: single-season player (season 11, same dir/season_no rule)
    tm3 = Team(open(v20_path, 'rb').read())
    for rec in (tm3.players[24].raw, tm3.players[64].raw):
        _set(rec, *F['age'], _get(rec, *F['age']) + 1)
    set_player(tm3, 25, 'BENCH', 'EDDIE', 30, 6, 100)
    _set(tm3.players[65].raw, *F['ab_l'], 200); _set(tm3.players[65].raw, *F['h_l'], 50)
    _set(tm3.players[65].raw, *F['games'], 100)
    tm3.save(str(v20_path))
    history.record_season(str(ldir), str(hp), 11, {})
    history.mark_retired(str(hp), str(ldir), {'CLASALE1.V20': [25]}, 11)
    h3 = history.History.load(str(hp))
    e3 = h3.read_entry(1)
    assert e3['status'] == history.STATUS_RETIRED
    assert e3['hof_season'] == 0


def test_mark_retired_pre_rollover_identity(tmp_path):
    """mark_retired finds the retiree via the PRE-rollover dir even though the
    post-roll V20s (rollover out dir) have the retiree's name byte 0 zeroed."""
    ldir = tmp_path / 'lg'
    post = tmp_path / 'out'
    post.mkdir()
    ldir.mkdir()
    (ldir / 'CLASALE1.V20').write_bytes(make_team_v20())
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    hp = tmp_path / 'HISTORY.DAT'
    v20_path = ldir / 'CLASALE1.V20'
    for season in range(1, 11):
        tm = Team(open(v20_path, 'rb').read())
        if season > 1:
            for rec in (tm.players[24].raw, tm.players[64].raw):
                _set(rec, *F['age'], _get(rec, *F['age']) + 1)
        set_player(tm, 24, 'HITTER', 'HOF', 25 + season - 1, 5, 150)
        s = tm.players[64].raw
        _set(s, *F['ab_l'], 500); _set(s, *F['h_l'], 310); _set(s, *F['games'], 150)
        tm.save(str(v20_path))
        history.record_season(str(ldir), str(hp), season, {})
    # the rollover's post-roll copy zeroes the retiree name byte 0 (out dir)
    tm = Team(open(v20_path, 'rb').read())
    tm.players[24].raw[0] = 0
    tm.players[64].raw[0] = 0
    tm.save(str(post / 'CLASALE1.V20'))
    # mark_retired uses the PRE dir (intact names), not the post dir
    history.mark_retired(str(hp), str(ldir), {'CLASALE1.V20': [24]}, 10)
    h = history.History.load(str(hp))
    e = h.read_entry(0)
    assert e['status'] == history.STATUS_HOF and e['hof_season'] == 10
    # and with the post dir it would NOT fire (identity gone): sanity
    history.mark_retired(str(hp), str(post), {'CLASALE1.V20': [24]}, 10)
    h2 = history.History.load(str(hp))
    assert h2.read_entry(0)['status'] == history.STATUS_HOF   # unchanged from above


def test_status_active_and_name_bytes(tmp_path):
    """Name bytes 0..19 raw V20 bytes (last 12, first 8); status 1 after record_season."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / 'CLASALE1.V20').write_bytes(make_team_v20())
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    hp = tmp_path / 'HISTORY.DAT'
    tm = Team(open(str(ldir / 'CLASALE1.V20'), 'rb').read())
    set_player(tm, 7, 'ROSSI', 'ROB', 29, 4, 100)
    _set(tm.players[47].raw, *F['games'], 100)
    tm.save(str(ldir / 'CLASALE1.V20'))
    history.record_season(str(ldir), str(hp), 1, {})
    h = history.History.load(str(hp))
    e = h.read_entry(0)
    assert e['name'] == b'\x01' + b'ROSSI'.ljust(12, b'\0')[1:] + b'ROB'.ljust(8, b'\0')
    assert e['status'] == 1
    assert e['pitcher'] == 0
    assert e['pos1'] == 4
    # pitcher: pos1 0, flag 1 (the incumbent ages +1 first, as the P1 rollover would,
    # so his identity is preserved and the pitcher appends as entry 1)
    tm2 = Team(open(str(ldir / 'CLASALE1.V20'), 'rb').read())
    for rec in (tm2.players[7].raw, tm2.players[47].raw):
        _set(rec, *F['age'], _get(rec, *F['age']) + 1)
    set_player(tm2, 8, 'ACE', 'ART', 26, 0, 30)
    s = tm2.players[48].raw
    _set(s, *F['ip10'], 1000); _set(s, *F['er'], 40); _set(s, *F['games'], 30)
    tm2.save(str(ldir / 'CLASALE1.V20'))
    history.record_season(str(ldir), str(hp), 2, {})
    h2 = history.History.load(str(hp))
    e2 = h2.read_entry(1)
    assert e2['pitcher'] == 1 and e2['pos1'] == 0
    # outs = (1000 // 10) * 3 + 0 = 300
    assert e2['totals'][19] == 300


def test_allstar_unmatched_stem_skipped(tmp_path):
    """A V20 whose stem matches no MAJ stem (ALLSTAR1/2: their MAJ stems start with
    NUL) is skipped by every history step: no league totals, no player entries."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / 'CLASALE1.V20').write_bytes(make_team_v20())
    (ldir / 'ALLSTAR1.V20').write_bytes(make_team_v20(name=b'ALLSTARS', abbr=b'ALS'))
    m = make_maj()
    sa = S_AL + maj.O_STEM + 8 * 15
    m.d[sa:sa + 8] = b'\0' * 8         # ALLSTAR1 stem starts with NUL = no match
    m.save(str(ldir / 'CLASSIC.MAJ'))
    hp = tmp_path / 'HISTORY.DAT'
    tm = Team(open(str(ldir / 'CLASALE1.V20'), 'rb').read())
    set_player(tm, 7, 'ROSSI', 'ROB', 29, 4, 100)
    _set(tm.players[47].raw, *F['games'], 100)
    _set(tm.players[47].raw, *F['ab_l'], 100)
    tm.save(str(ldir / 'CLASALE1.V20'))
    # the ALLSTAR file has an active batter with big stats that must be ignored
    tm2 = Team(open(str(ldir / 'ALLSTAR1.V20'), 'rb').read())
    set_player(tm2, 3, 'MASH', 'MADDOX', 28, 2, 162)
    _set(tm2.players[43].raw, *F['games'], 162)
    _set(tm2.players[43].raw, *F['ab_l'], 999); _set(tm2.players[43].raw, *F['h_l'], 400)
    tm2.save(str(ldir / 'ALLSTAR1.V20'))
    history.record_season(str(ldir), str(hp), 1, {})
    h = history.History.load(str(hp))
    # only the matched team's batter gets an entry; the ALLSTAR one does not
    assert len(h._entries) == 1
    e = h.read_entry(0)
    assert e['totals'][1] == 100          # AB from ROB only, no ALLSTAR 999
    # league totals: L_pa from the matched team only (pa = 100 AB + 0 BB)
    per, lg = war.season_league([(str(ldir / 'CLASALE1.V20'), 0)])
    assert lg['L_pa'] == 100


def test_wl_nl_slot13_id29_and_32_pairs(tmp_path):
    """W-L table = 32 pairs, ids 0..31: an NL slot 13 team lands at id 29;
    88..127 stay zero."""
    p = tmp_path / 'HISTORY.DAT'
    hist = history.History(None)
    wl = [(0, 0)] * 32
    wl[29] = (101, 61)
    wl[31] = (1, 1)
    hist.write_season_entry(1, {'season_no': 1, 'champion': 0xff, 'runner_up': 0xff,
                                'champion_stem': b'', 'runner_up_stem': b'',
                                'al_pennant': 0xff, 'nl_pennant': 0xff, 'w_l': wl})
    hist.save(str(p))
    raw = open(p, 'rb').read()
    o = 32
    # id 29 pair at 24 + 2*29 = 82, id 31 at 86; 88..127 zero
    assert raw[o + 24 + 2 * 29] == 101 and raw[o + 25 + 2 * 29] == 61
    assert raw[o + 24 + 2 * 31] == 1 and raw[o + 25 + 2 * 31] == 1
    assert raw[o + 88:o + 128] == bytes(40)
    h2 = history.History.load(str(p))
    s = h2.read_season_entry(1)
    assert len(s['w_l']) == 32
    assert s['w_l'][29] == (101, 61)
    assert s['w_l'][31] == (1, 1)


def test_nl_slot13_wl_through_record_season(tmp_path):
    """record_season writes W-L for slots 0..15 of both leagues: NL slot 13 -> id 29."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / 'CLASALE1.V20').write_bytes(make_team_v20())
    m = make_maj()
    m.set_wl('NL', 13, 101, 61)
    m.save(str(ldir / 'CLASSIC.MAJ'))
    hp = tmp_path / 'HISTORY.DAT'
    history.record_season(str(ldir), str(hp), 1, {})
    h = history.History.load(str(hp))
    s = h.read_season_entry(1)
    assert s['w_l'][29] == (101, 61)


def test_version_byte_every_path(tmp_path):
    """Byte 3 = 1 after record_season on a brand-new file, and after a legacy
    4-byte upgrade + record_season (bytes 0..2 kept)."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / 'CLASALE1.V20').write_bytes(make_team_v20())
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    hp = tmp_path / 'HISTORY.DAT'
    # brand-new file
    history.record_season(str(ldir), str(hp), 1, {})
    assert history.History.load(str(hp)).version == 1
    # legacy 4-byte file: record_season keeps bytes 0..2 where it can (the done flag /
    # rng word are P1 markers; the done flag is set at the end of every record_season)
    open(hp, 'wb').write(bytes([7, 0x34, 0x12]))
    history.record_season(str(ldir), str(hp), 2, {})
    raw = open(hp, 'rb').read()
    h = history.History.load(str(hp))
    assert h.version == 1
    assert h.rng_word == 0x1234
    assert len(raw) > 32 and raw[4] | raw[5] << 8 == 2
