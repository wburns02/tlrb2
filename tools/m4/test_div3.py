"""Three-division tests (contract C12): the stable team ids (C12.3), the realignment planner (C12.5), the
HISTORY season entry (C12.7), the displays (C12.8) and the ROSTERS / CREATE / WAR tools on a 3-division MAJ.
Two-division and legacy cases stay in the suites of their own modules.
Run:  python3 -m pytest -q tools/m4/test_div3.py
Fixtures: the synthetic CLASSIC league of test_teamids.build_maj, realigned to 3 divisions by realign.realign.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import history  # noqa: E402
import maj  # noqa: E402
import realign as ra  # noqa: E402
import teamids as ti  # noqa: E402
import war  # noqa: E402
from test_teamids import build_maj, CLASSIC, S  # noqa: E402
from test_history import make_team_v20  # noqa: E402
from test_rosters import rookie_league, _write_hist, _read  # noqa: E402
import dynview  # noqa: E402
import rosters  # noqa: E402

S_AL, S_NL = S
D2 = build_maj(CLASSIC, divs=2)                # 2 divisions, stems at the engine ids (C12.1)
D3 = ra.realign(D2, 3)[0]                      # the same teams in 3 divisions (C12.5)


def identities_only(d):
    """The MAJ with the team tables and counts of d and every game table zeroed (the synthetic noise of
    build_maj would otherwise read as schedule pairs and playoff results)."""
    z = bytearray(maj.SIZE)
    z[0x20c], z[0x20d] = d[0x20c], d[0x20d]
    z[10:266] = d[10:266]
    for s0 in S:
        z[s0 + 0x0f:s0 + 0x297] = d[s0 + 0x0f:s0 + 0x297]     # names, abbreviations, stems
        z[s0 + 0x298:s0 + 0x29b] = d[s0 + 0x298:s0 + 0x29b]   # division counts
    return bytes(z)


BASE3 = identities_only(D3)
TABLE = ti.make_table(D2)                      # TEAMID.DAT as the realignment writes it (C12.3)
# the 3-division engine ids (C12.1): AL East 0..4 (BAL BOS DET NYA TOR), West 5..8 (CAL OAK SEA TEX),
# Central 10..14 (CHA CLE KC MIL MIN); NL East 16..19 (ATL MON NYN PHI), West 21..23 (LA SD SF),
# Central 26..30 (CHN CIN HOU PIT SL). The stable ids (TABLE, the 2-division ids) differ for Central.
ENG = {'CLE': 11, 'CAL': 5, 'BAL': 0, 'CHN': 26, 'ATL': 16, 'SL': 30}
STABLE = {'CLE': 2, 'CAL': 8, 'BAL': 0, 'CHN': 16, 'ATL': 24, 'SL': 21}


def hist_bytes(n):
    h = bytearray(32)
    h[11] = n
    return bytes(h)


def stems(d):
    """{stem: stable id under TABLE} of the MAJ teams, for a readable assertion."""
    return {st.rstrip(b'\0').decode('latin-1'): k for k, _L, _s, st in ti.teams(d, TABLE)}


def test_3div_layout_engine_ids():
    """The realigned fixture has the C12.1 compact engine ids; the TABLE stems give the 2-division ids."""
    assert ti.ndiv(D3) == 3
    got = {st.rstrip(b'\0').decode('latin-1'): k for k, _L, _s, st in ti.teams(D3, None)}
    assert got['ACLE'] == ENG['CLE'] and got['ACAL'] == ENG['CAL'] and got['ABAL'] == ENG['BAL']
    assert got['NCHN'] == ENG['CHN'] and got['NATL'] == ENG['ATL'] and got['NSL'] == ENG['SL']
    assert len(got) == 26                       # 14 AL and 12 NL teams, all with stems
    st = stems(D3)
    assert st['ACLE'] == STABLE['CLE'] and st['NCHN'] == STABLE['CHN']


def test_engine_ids_without_table_and_stable_ids_with_it():
    """Engine-id playoff bytes decode to the right stable ids and stems, with and without TEAMID.DAT."""
    m = maj.Maj(D3)
    d = bytearray(m.d)
    d[S_AL + 0x3d9] = ENG['CLE']               # AL pennant winner (engine id 11, CLE)
    d[S_AL + 0x3da] = ENG['SL']                # NL pennant winner (engine id 30, SL) in the AL block
    d[S_NL + 0x3d9] = ENG['SL']                # NL pennant winner, the NL block copy
    d[S_AL + 0x3e1], d[S_AL + 0x3e2] = 4, 2    # WS wins: the AL pennant winner (team0) takes it
    m = maj.Maj(bytes(d))
    assert history.decode_champion(m) == (11, 30, 11, 30)
    assert history.decode_champion(m, TABLE) == (2, 21, 2, 21)
    assert history.team_stem(m, 11) == b'ACLE' and history.team_stem(m, 30) == b'NSL'
    assert history.team_stem(m, 2, TABLE) == b'ACLE' and history.team_stem(m, 21, TABLE) == b'NSL'
    assert history.team_stem(m, 0xff, TABLE) == b''
    # an engine id whose slot holds no team (AL 9 = West slot 12, AL 15 = the all-star slot), and any id >= 32
    assert history.decode_champion(maj.Maj(bytes(_with(D3, S_AL + 0x3d9, 9))))[2] == 0xff
    assert history.decode_champion(maj.Maj(bytes(_with(D3, S_AL + 0x3d9, 15))))[2] == 0xff
    assert history.decode_champion(maj.Maj(bytes(_with(D3, S_AL + 0x3d9, 40))))[2] == 0xff


def _with(d, off, v):
    b = bytearray(d)
    b[off] = v
    return b


def test_mapped_teams_stable_ids(tmp_path):
    """mapped_teams keys each V20 by the stable id: the engine id without TEAMID.DAT, the table id with it."""
    m = maj.Maj(D3)
    for stem in ('ACLE', 'NCHN', 'ABAL', 'NSL'):
        (tmp_path / (stem + '.V20')).write_bytes(make_team_v20())
    (tmp_path / 'ALLSTAR1.V20').write_bytes(make_team_v20())
    got = [(os.path.basename(p), k) for p, k in history.mapped_teams(str(tmp_path), m)]
    assert got == [('ABAL.V20', 0), ('ACLE.V20', 11), ('NCHN.V20', 26), ('NSL.V20', 30)]
    (tmp_path / ti.TABLE_NAME).write_bytes(TABLE)
    got = [(os.path.basename(p), k) for p, k in history.mapped_teams(str(tmp_path), m)]
    assert got == [('ABAL.V20', 0), ('ACLE.V20', 2), ('NCHN.V20', 16), ('NSL.V20', 21)]


def test_series_stem_ids_cover_the_central_slots():
    """series_stem_ids reads slots 16..20 too (3 divisions), by stable id."""
    m = maj.Maj(D3)
    assert history.series_stem_ids(m)['nchn'] == 26
    assert history.series_stem_ids(m, TABLE)['nchn'] == 16
    assert history.series_stem_ids(m, TABLE)['acle'] == 2
    assert history.series_stem_ids(m, TABLE)['nsl'] == 21


def test_season_entry_bytes_22_23_and_the_division_map():
    """write_season_entry: byte 22 = ndiv, byte 23 = 0, the 16 B map at 100..115, 116..127 zero."""
    h = history.History(None)
    divmap = history.divmap_of(D3, TABLE)
    h.write_season_entry(1, {'season_no': 1, 'champion': 0xff, 'runner_up': 0xff, 'champion_stem': b'',
                             'runner_up_stem': b'', 'al_pennant': 0xff, 'nl_pennant': 0xff,
                             'ndiv': 3, 'divmap': divmap})
    o = h.season_offset(1)
    assert h.d[o + 22] == 3 and h.d[o + 23] == 0
    assert bytes(h.d[o + 100:o + 116]) == divmap and bytes(h.d[o + 116:o + 128]) == bytes(12)
    e = h.read_season_entry(1)
    assert e['ndiv'] == 3 and e['divmap'] == divmap
    assert e['al_pennant'] == 0xff and e['w_l'][0] == (0, 0)


def test_divmap_and_division_of():
    """divmap_of: nibble = division + 1 by stable id; division_of reads it; a legacy entry uses the k & 15 rule."""
    divmap = history.divmap_of(D3, TABLE)
    assert len(divmap) == 16
    e = {'ndiv': 3, 'divmap': divmap}
    assert history.division_of(e, 0) == 1          # BAL East
    assert history.division_of(e, 2) == 3          # CLE Central (2-division id 2, slot 17)
    assert history.division_of(e, 8) == 2          # CAL West
    assert history.division_of(e, 16) == 3         # CHN Central
    assert history.division_of(e, 24) == 1         # ATL East
    assert history.division_of(e, 21) == 3         # SL (stable 21) is Central
    assert history.division_of(e, 21) == (divmap[10] >> 4) & 15
    assert history.division_of(e, 1) == 1 and history.division_of(e, 9) == 3   # BOS East, CHA Central
    assert history.division_of({'ndiv': 0}, 7) == 1      # legacy: East below 8
    assert history.division_of({'ndiv': 0}, 8) == 2      # legacy: West from 8
    assert history.division_of({'ndiv': 0}, 17) == 1     # legacy: NL slot 1 is East
    assert history.division_of({'ndiv': 0}, 25) == 2     # legacy: NL slot 9 is West


def test_record_season_three_divisions(tmp_path):
    """record_season on a 3-division league: w_l for the slots 16..23 teams (by stable id), ndiv 3, the map."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    for stem in ('ACLE', 'NCHN', 'NSL'):
        (ldir / (stem + '.V20')).write_bytes(make_team_v20())
    m = maj.Maj(BASE3)
    m.set_wl('NL', 16, 90, 72)                     # slot 16 = CHN (NL Central), stable 16
    m.set_wl('NL', 20, 85, 77)                     # slot 20 = SL (NL Central), stable 21
    m.set_wl('AL', 16, 81, 81)                     # slot 16 = CHA (AL Central), stable 9
    d = bytearray(m.d)
    d[S_AL + 0x3d9] = ENG['CLE']
    d[S_AL + 0x3da] = ENG['SL']
    d[S_NL + 0x3d9] = ENG['SL']
    d[S_AL + 0x3e1], d[S_AL + 0x3e2] = 4, 2
    maj.Maj(bytes(d)).save(str(ldir / 'CLASSIC.MAJ'))
    (ldir / ti.TABLE_NAME).write_bytes(TABLE)
    hp = tmp_path / 'HISTORY.DAT'
    history.record_season(str(ldir), str(hp), 1, {})
    s = history.History.load(str(hp)).read_season_entry(1)
    assert s['ndiv'] == 3
    assert s['champion'] == 2 and s['champion_stem'] == b'ACLE'
    assert s['runner_up'] == 21 and s['runner_up_stem'] == b'NSL'
    assert s['w_l'][16] == (90, 72) and s['w_l'][21] == (85, 77) and s['w_l'][9] == (81, 81)
    assert s['w_l'][26] == (0, 0)                  # HOU (stable 26) has no games: engine 26 is CHN, not read
    assert history.division_of(s, 16) == 3 and history.division_of(s, 8) == 2
    assert history.division_of(s, 0) == 1
    assert s['divmap'] == history.divmap_of(D3, TABLE)


def test_park_factors_keyed_by_stable_id(tmp_path):
    """park_factors matches each team by its engine id in the compact schedule pairs and keys the result by
    the stable id. ATL plays CHN at home and away: CHN 933, ATL 1071 (the test_war fixture numbers)."""
    d = bytearray(BASE3)
    nl = S_NL
    def game(day, away, home, ra_away, rh_home):
        d[nl + maj.O_SCHED + 16 * day:nl + maj.O_SCHED + 16 * day + 2] = bytes([away, home])
        rb = nl + maj.O_RUNS + 32 * day
        d[rb], d[rb + 1] = ra_away, rh_home
        d[nl + maj.O_PLAYED + 2 * day] = 0x80
    game(8, ENG['ATL'], ENG['CHN'], 2, 12)        # ATL at CHN: CHN home 12-2
    game(9, ENG['CHN'], ENG['ATL'], 5, 10)        # CHN at ATL: CHN road 5-10
    p = tmp_path / 'CLASSIC.MAJ'
    p.write_bytes(bytes(d))
    pf = war.park_factors(str(p))                 # no TEAMID.DAT: the engine ids
    assert pf[ENG['CHN']] == 933 and pf[ENG['ATL']] == 1071
    (tmp_path / ti.TABLE_NAME).write_bytes(TABLE)
    pf = war.park_factors(str(p))                 # with TEAMID.DAT: the stable ids
    assert pf[STABLE['CHN']] == 933 and pf[STABLE['ATL']] == 1071
    assert ENG['CHN'] not in pf or ENG['CHN'] == STABLE['CHN']


def test_slot_from_stem_stable_id(tmp_path):
    p = tmp_path / 'CLASSIC.MAJ'
    p.write_bytes(D3)
    assert war.slot_from_stem(str(p), 'NCHN') == 26
    assert war.slot_from_stem(str(p), 'nchn') == 26
    assert war.slot_from_stem(str(p), 'ALLSTAR1') is None
    assert war.slot_from_stem(None, 'NCHN') is None
    (tmp_path / ti.TABLE_NAME).write_bytes(TABLE)
    assert war.slot_from_stem(str(p), 'NCHN') == 16
    assert war.slot_from_stem(str(p), 'ACLE') == 2


def test_plan_codes():
    """realign.plan: 1 nothing, 2 refused (reason), 0 realigned with a table only when none exists."""
    assert ra.plan(D2, b'', None) == (1, None, None, None)
    assert ra.plan(D2, hist_bytes(2), TABLE) == (1, None, None, None)
    assert ra.plan(D3, hist_bytes(3), TABLE) == (1, None, None, None)
    code, new, tab, why = ra.plan(D2, hist_bytes(3), None)
    assert code == 0 and why is None and new == D3 and tab == ti.make_table(D2)
    code, new, tab, why = ra.plan(D2, hist_bytes(3), TABLE)
    assert code == 0 and new == D3 and tab is None      # an existing table is never rewritten
    code, new, tab, why = ra.plan(D2, hist_bytes(3), b'\0' * 10)
    assert code == 0 and tab == ti.make_table(D2)       # a table of the wrong size counts as missing
    code, new, tab, why = ra.plan(D3, hist_bytes(2), TABLE)
    assert code == 0 and new[0x20d] == 2 and new[0x20a] == 0xf3
    odd = build_maj({0: [(s, 'X%02d' % s) for s in (0, 1, 2, 8, 9)]}, divs=2)
    assert ra.plan(odd, hist_bytes(3), None) == (2, None, None, 'AL ODD COUNT')
    assert ra.plan(b'', hist_bytes(3), None)[0] == 2


def test_rosters_run_switches_to_three_divisions_and_keeps_the_ids(tmp_path):
    """A roll with HISTORY byte 11 = 3 on a 2-division league: the MAJ is realigned (day 0xf3, 3 divisions),
    TEAMID.DAT is written from the pre-realignment MAJ, ROSTERS.TXT ends with FORMAT 3, and every team keeps
    its 2-division id. The next roll has nothing to do: no FORMAT line, the table kept."""
    league, snap, hist, retired = rookie_league(str(tmp_path))
    _write_hist(hist, 3)
    maj_path = os.path.join(league, 'CLASSIC.MAJ')
    before = _read(maj_path)
    assert rosters.run(league, snap, hist, retired) == 0
    after = _read(maj_path)
    assert ti.ndiv(after) == 3 and after[0x20a] == 0xf3
    tbl = _read(os.path.join(league, ti.TABLE_NAME))
    assert tbl == ti.make_table(before)
    assert sorted(k for k, *_ in ti.teams(after, tbl)) == sorted(k for k, *_ in ti.teams(before, None))
    assert _read(os.path.join(league, 'ROSTERS.TXT')).endswith(b'FORMAT 3\r\n')
    assert not [n for n in os.listdir(league) if n.endswith('.TMP')]
    assert rosters.run(league, snap, hist, retired) == 0
    assert _read(maj_path) == after
    assert _read(os.path.join(league, ti.TABLE_NAME)) == tbl
    assert b'FORMAT' not in _read(os.path.join(league, 'ROSTERS.TXT'))


def test_create_teams_lists_a_slot_16_team(tmp_path):
    """create.teams: an NL Central team (slot 16 in 3 divisions) is listed under its stable id."""
    import create
    (tmp_path / 'CLASSIC.MAJ').write_bytes(D3)
    (tmp_path / 'NCHN.V20').write_bytes(make_team_v20(name=b'CHICAGO', abbr=b'CHN'))
    (tmp_path / 'ABAL.V20').write_bytes(make_team_v20(name=b'BALTIMORE', abbr=b'BAL'))
    got = [(k, s) for k, s, _d in create.teams(str(tmp_path))]
    assert got == [(0, 'ABAL'), (26, 'NCHN')]
    (tmp_path / ti.TABLE_NAME).write_bytes(TABLE)
    got = [(k, s) for k, s, _d in create.teams(str(tmp_path))]
    assert got == [(0, 'ABAL'), (16, 'NCHN')]


SET = dynview.SCREEN_SETTINGS
STAND_3 = ['AL WEST', 'AL CENTRAL', 'AL EAST', 'NL WEST', 'NL CENTRAL', 'NL EAST']


def blocks_of(rows):
    """{header: set of team names} of a standings row list (blank padding rows skipped)."""
    out, cur = {}, None
    for r in rows:
        if not r[0]:
            continue
        if r[1] == '':
            cur = r[0]
            out[cur] = set()
        else:
            out[cur].add(r[0])
    return out


def season_hist(ndiv_map, ids):
    """A HISTORY object with season 1: every id in ids played 80-82; ndiv_map None = a legacy entry."""
    h = history.History(None)
    w_l = [(0, 0)] * 32
    for k in ids:
        w_l[k] = (80, 82)
    e = {'season_no': 1, 'champion': 0xff, 'runner_up': 0xff, 'champion_stem': b'',
         'runner_up_stem': b'', 'al_pennant': 0xff, 'nl_pennant': 0xff, 'w_l': w_l}
    if ndiv_map is not None:
        e['ndiv'] = 3
        e['divmap'] = ndiv_map
    h.write_season_entry(1, e)
    h.seasons_recorded = 1
    return h


def test_standings_three_divisions_six_blocks_in_order():
    """Six blocks, WEST CENTRAL EAST per league, by the stable ids of the TABLE layout."""
    ids = sorted(k for k, *_ in ti.teams(D3, TABLE))
    hist = season_hist(history.divmap_of(D3, TABLE), ids)
    rows = dynview.standings_rows(hist, [(k, 'T%d' % k) for k in ids], 1)
    got = blocks_of(rows)
    assert list(got) == STAND_3
    assert got['AL WEST'] == {'T8', 'T12', 'T13', 'T14'}
    assert got['AL CENTRAL'] == {'T9', 'T2', 'T10', 'T4', 'T11'}
    assert got['AL EAST'] == {'T0', 'T1', 'T3', 'T5', 'T6'}
    assert got['NL EAST'] == {'T24', 'T17', 'T18', 'T19'}
    assert got['NL WEST'] == {'T27', 'T28', 'T29'}
    assert got['NL CENTRAL'] == {'T16', 'T25', 'T26', 'T20', 'T21'}


def test_standings_legacy_entry_keeps_four_blocks():
    """A legacy entry (no ndiv): the k & 15 rule, WEST then EAST per league, as before C12."""
    ids = [*range(0, 7), *range(8, 15), *range(16, 22), *range(24, 30)]
    rows = dynview.standings_rows(season_hist(None, ids), [(k, 'T%d' % k) for k in ids], 1)
    got = blocks_of(rows)
    assert list(got) == ['AL WEST', 'AL EAST', 'NL WEST', 'NL EAST']
    assert got['AL WEST'] == {'T%d' % k for k in range(8, 15)}
    assert got['NL EAST'] == {'T%d' % k for k in range(16, 22)}


def test_settings_rows_labels():
    """PLAYOFF FORMAT is the second row, with the wanted label and NEXT YEAR when it differs from now."""
    teams = [(0, 'BAL'), (2, 'CLE')]
    base = {'mask': 0, 'era': 0, 'teams': teams}
    cases = {(2, 2): '2 DIVISIONS', (3, 3): '3 DIV + WILDCARD',
             (3, 2): '3 DIV NEXT YEAR', (2, 3): '2 DIV NEXT YEAR'}
    for fmt, label in cases.items():
        rows = dynview.settings_rows(dict(base, fmt=fmt))
        assert rows[0] == ('ERA RULES', 'REAL CALENDAR')
        assert rows[1] == ('PLAYOFF FORMAT', label)
        assert rows[2:] == [('BAL', 'AI MANAGES'), ('CLE', 'AI MANAGES')]


def hist_file(root, byte0=0, byte11=0):
    h = bytearray(32)
    h[0], h[11] = byte0, byte11
    (root / 'HISTORY.DAT').write_bytes(bytes(h))


def league(root, maj_bytes, byte0=0, byte11=0):
    """A league dir: the MAJ, a HISTORY.DAT and a V20 for every team of the MAJ (settings_teams needs them)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / 'CLASSIC.MAJ').write_bytes(maj_bytes)
    hist_file(root, byte0, byte11)
    for _k, _L, _s, st in ti.teams(maj_bytes, None):
        (root / (st.rstrip(b'\0').decode('latin-1') + '.V20')).write_bytes(make_team_v20())
    return str(root)


def with_day(d, day):
    b = bytearray(d)
    b[0x20a] = day
    return bytes(b)


def test_enter_playoff_format_at_day_7_applies_and_sets_rolled(tmp_path):
    """Set up, no game played (day 7): byte 11 = 3, the MAJ realigned to 3 divisions at 0xf3, TEAMID.DAT
    written from the 2-division MAJ, HISTORY byte 0 = 1."""
    root = tmp_path / 'lg'
    ldir = league(root, with_day(D2, 7))
    data = dynview.load_data(ldir)
    assert data['fmt'] == (2, 2)
    assert dynview.step((SET, 0, 1), dynview.KEY_ENTER, data) == ((SET, 0, 1), 0)
    h = _rd(root / 'HISTORY.DAT')
    assert h[11] == 3 and h[0] == 1
    maj = _rd(root / 'CLASSIC.MAJ')
    assert ti.ndiv(maj) == 3 and maj[0x20a] == 0xf3
    assert _rd(root / ti.TABLE_NAME) == ti.make_table(with_day(D2, 7))
    assert data['fmt'] == (3, 3)
    assert dynview.settings_rows(data)[1] == ('PLAYOFF FORMAT', '3 DIV + WILDCARD')
    assert sorted(k for k, *_ in data['teams']) == sorted(k for k, *_ in ti.teams(maj, _rd(root / ti.TABLE_NAME)))


def test_enter_playoff_format_at_day_f3_after_roll_applies(tmp_path):
    """Rolled and the next season not started (day 0xf3, byte 0 = 1): the apply runs at once, byte 0 stays 1."""
    root = tmp_path / 'lg'
    ldir = league(root, with_day(D2, 0xf3), byte0=1)
    data = dynview.load_data(ldir)
    dynview.step((SET, 0, 1), dynview.KEY_ENTER, data)
    h = _rd(root / 'HISTORY.DAT')
    assert h[11] == 3 and h[0] == 1
    maj = _rd(root / 'CLASSIC.MAJ')
    assert ti.ndiv(maj) == 3 and maj[0x20a] == 0xf3
    assert data['fmt'] == (3, 3)


def test_enter_playoff_format_mid_season_writes_byte_11_only(tmp_path):
    """Mid-season (day 0x40) or day 0xf3 with byte 0 = 0: only HISTORY byte 11 changes; the change waits."""
    for day, byte0 in ((0x40, 0), (0xf3, 0)):
        root = tmp_path / ('d%x_%d' % (day, byte0))
        maj_before = with_day(D2, day)
        ldir = league(root, maj_before, byte0=byte0)
        data = dynview.load_data(ldir)
        hist_before = _rd(root / 'HISTORY.DAT')
        dynview.step((SET, 0, 1), dynview.KEY_ENTER, data)
        h = _rd(root / 'HISTORY.DAT')
        assert h[11] == 3 and h[0] == byte0
        assert bytes(h[:11]) == hist_before[:11] and bytes(h[12:]) == hist_before[12:]
        assert _rd(root / 'CLASSIC.MAJ') == maj_before
        assert not (root / ti.TABLE_NAME).exists()
        assert data['fmt'] == (3, 2)
        assert dynview.settings_rows(data)[1] == ('PLAYOFF FORMAT', '3 DIV NEXT YEAR')


def test_enter_playoff_format_toggles_back_to_two(tmp_path):
    """ENTER again on a 3-division wanted value writes byte 11 = 2 (5 - 3)."""
    root = tmp_path / 'lg'
    ldir = league(root, with_day(D2, 0x40), byte11=3)
    data = dynview.load_data(ldir)
    assert data['fmt'] == (3, 2)
    dynview.step((SET, 0, 1), dynview.KEY_ENTER, data)
    assert _rd(root / 'HISTORY.DAT')[11] == 2 and data['fmt'] == (2, 2)


def test_cursor_rows_map_to_era_playoff_and_teams(tmp_path):
    """Cursor 0 is ERA RULES, cursor 1 PLAYOFF FORMAT, cursor 2 the first team (its mask bit toggles)."""
    root = tmp_path / 'lg'
    ldir = league(root, with_day(D2, 0x40))
    data = dynview.load_data(ldir)
    tid = data['teams'][0][0]
    assert dynview.step((SET, 0, 0), dynview.KEY_DOWN, data) == ((SET, 0, 1), 0)
    assert dynview.step((SET, 0, 1), dynview.KEY_DOWN, data) == ((SET, 0, 2), 0)
    dynview.step((SET, 0, 2), dynview.KEY_ENTER, data)
    assert data['mask'] == 1 << tid
    assert _rd(root / 'HISTORY.DAT')[11] == 0           # the team row does not touch byte 11


def _rd(path):
    return open(path, 'rb').read()
