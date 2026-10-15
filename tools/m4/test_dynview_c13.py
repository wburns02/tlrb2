#!/usr/bin/env python3
"""Tests for DYNVIEW C13 (tools/m4/dynview.py): season lines, leaders, player card, mouse and the
start year. Synthetic HISTORY.DAT, SEASLINE.DAT, MILESTON.DAT, MAJ, fonts and portrait ANM files
are built in tmp_path; nothing needs /mnt/nvme.
Run:  python3 -m pytest -q tools/m4/test_dynview_c13.py
"""
import os, struct, sys, tempfile
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import dynview
import history
from test_teamids import build_maj
from test_dynview import box_rec, write_box, game_ms

ENTER, ESC = dynview.KEY_ENTER, dynview.KEY_ESC
UP, DOWN = dynview.KEY_UP, dynview.KEY_DOWN
LEFT, RIGHT = dynview.KEY_LEFT, dynview.KEY_RIGHT
PGUP, PGDN = dynview.KEY_PGUP, dynview.KEY_PGDN
TAB = dynview.KEY_TAB
HUB = (dynview.SCREEN_MENU, 0, 0)
LEAD = dynview.SCREEN_LEADERS
SA, SS, SW, SB = (dynview.SCREEN_AWARDS, dynview.SCREEN_STANDINGS,
                  dynview.SCREEN_SERIES, dynview.SCREEN_BOX)
SET, ABOUT, HOF = dynview.SCREEN_SETTINGS, dynview.SCREEN_ABOUT, dynview.SCREEN_HOF
SO, CARD = dynview.SCREEN_OFFSEASON, dynview.SCREEN_CARD
OFF_RETIRE = dynview.OFF_RETIRE
BY_YEAR, SEASON = 2 * 32, 1 * 32

# TOTALS indexes (C2 order)
S = dict(G=0, AB=1, H=2, D2=3, T3=4, HR=5, R=6, RBI=7, BB=8, SO=9, SB=10, CS=11, E=12,
         W=13, L=14, SV=15, GS=16, CG=17, SHO=18, OUTS=19, ER=20, PH=21, PBB=22, PSO=23, PHR=24)
SEASON_LABELS = [c[0] for c in dynview.SEASON_CATS]
CAREER_LABELS = [c[0] for c in dynview.CATS]
POST_LABELS = [c[0] for c in dynview.POST_CATS]


def sidx(label):
    """The SEASON category index of a label."""
    return SEASON_LABELS.index(label)


def cidx(label):
    """The CAREER category index of a label."""
    return CAREER_LABELS.index(label)


def tot(**kw):
    t = [0] * 25
    for k, v in kw.items():
        t[S[k]] = v
    return t


def player(last, first='A', status=1, first_season=1, last_season=3, played=3, pitcher=0,
           hof=0, age=27, pos1=3, war10=0, totals=None, awards=(0, 0, 0, 0, 0)):
    return dict(last=last, first=first, status=status, first_season=first_season,
                last_season=last_season, played=played, pitcher=pitcher, hof=hof, age=age,
                pos1=pos1, war10=war10, totals=totals or tot(), awards=awards)


def write_league(ldir, players, seasons=3, start=None, lines=None, ms=None):
    """HISTORY.DAT with the players as entries 0..n-1 (and the season table), SEASLINE.DAT when
    lines (80 B records) is given, MILESTON.DAT when ms ((season, idx, kind, value) records) is."""
    ldir.mkdir(parents=True, exist_ok=True)
    d = bytearray(32 + 64 * 128 + 160 * len(players))
    d[3] = 1
    d[4:6] = seasons.to_bytes(2, 'little')
    d[6:8] = len(players).to_bytes(2, 'little')
    if start is not None:
        d[18:20] = start.to_bytes(2, 'little')
    for n in range(1, seasons + 1):
        o = 32 + (n - 1) * 128
        struct.pack_into('<H', d, o, n)
        d[o + 4:o + 12] = (b'ALA%02d' % n).ljust(8, b'\0')
    for i, p in enumerate(players):
        o = 8224 + i * 160
        d[o:o + 20] = p['last'].encode().ljust(12, b'\0')[:12] + p['first'].encode().ljust(8, b'\0')[:8]
        d[o + 22] = p['status']
        d[o + 23] = p['age']
        struct.pack_into('<HHH', d, o + 24, p['first_season'], p['last_season'], p['played'])
        d[o + 30] = p['pos1']
        d[o + 31] = p['pitcher']
        for k, v in enumerate(p['totals']):
            struct.pack_into('<I', d, o + 32 + 4 * k, v)
        struct.pack_into('<h', d, o + 132, p['war10'])
        struct.pack_into('<H', d, o + 150, p['hof'])
        d[o + 152:o + 157] = bytes(p['awards'])
    (ldir / 'HISTORY.DAT').write_bytes(bytes(d))
    if lines is not None:
        write_lines(ldir, lines)
    if ms is not None:
        out = bytearray()
        for season, idx, kind, value in ms:
            out += struct.pack('<HHBBH', season, idx, kind, 0, value)
        (ldir / 'MILESTON.DAT').write_bytes(bytes(out))


def line(entry, season, team=0, pitcher=0, age=25, pos1=3, face=0, hand=0x0A, dev=0,
         ratings=(9, 8, 7, 6, 5, 4, 3, 2, 1), totals=None, war10=0):
    """One 80 B SEASLINE.DAT record (C13.2). hand 0x0A: bats R (bits 2..1 = 1), throws R (bit 3)."""
    r = bytearray(80)
    struct.pack_into('<HHBBBBHBB', r, 0, entry, season, team, pitcher & 1, age, pos1, face, hand, dev)
    r[12:21] = bytes(ratings)
    struct.pack_into('<25H', r, 22, *(totals or tot()))
    struct.pack_into('<h', r, 72, war10)
    return bytes(r)


def write_lines(ldir, recs):
    head = bytearray(16)
    head[0:2] = b'SL'
    head[2] = 1
    head[4:6] = (80).to_bytes(2, 'little')
    head[6:8] = max([int.from_bytes(r[2:4], 'little') for r in recs] or [0]).to_bytes(2, 'little')
    (ldir / 'SEASLINE.DAT').write_bytes(bytes(head) + b''.join(recs))


def make_fonts(d):
    """Synthetic MAIN.FNT (7 rows, advance 7) and BOLD.FNT (8 rows, advance 8), 95 glyphs each."""
    d.mkdir(parents=True, exist_ok=True)

    def fnt(rows, bits, adv):
        out = bytearray(struct.pack('<H', 95))
        for k in range(95):
            out += bytes([rows, bits, adv])
            for r in range(rows):
                out.append(0x55 if (r + k) % 2 else 0xAA)
        return bytes(out)
    (d / 'MAIN.FNT').write_bytes(fnt(7, 5, 7))
    (d / 'BOLD.FNT').write_bytes(fnt(8, 6, 8))
    return str(d)


def press(state, key, data):
    return dynview.step(state, key, data)[0]


def load(ldir, fonts=None, game_dir='.', anms_dir='ANMS'):
    return dynview.load_data(str(ldir), fonts, game_dir, anms_dir)


def season_lines_fixture():
    """Eight SEASLINE lines over entries 0..7 (the expectations are in the tests below). Teams:
    entry 2 is team 2 (DET), entry 5 team 9 (no abbreviation), the rest team 0 (BOS)."""
    return [
        # A: batter, season 1, pa 502 (AVG .300); HR 30, RBI 100, H 150
        line(0, 1, totals=tot(G=150, AB=500, BB=2, H=150, HR=30, R=90, RBI=100, SB=10, D2=20,
                              T3=5), war10=60),
        # B: batter, season 2, pa 502 (AVG .325); BB 102
        line(1, 2, totals=tot(G=140, AB=400, BB=102, H=130, HR=30, R=80, RBI=90, D2=25, T3=2),
             war10=40),
        # C: batter, season 1, AB 600 (AVG .300, ties A: season then entry put A first); DET
        line(2, 1, team=2, totals=tot(G=120, AB=600, H=180, HR=30, R=70, RBI=60, SB=10, D2=30),
             war10=40),
        # D: batter, season 1, pa 501 (not an AVG qualifier) though its AVG is .600
        line(3, 1, totals=tot(G=130, AB=500, BB=1, H=300, HR=10, R=0), war10=0),
        # P1: pitcher, season 1, 300 IP, ER 60 -> ERA 180 (1.80); SHO 2
        line(4, 1, pitcher=1, pos1=0, totals=tot(G=30, W=15, L=5, OUTS=900, ER=60, PSO=200,
                                                 CG=4, SHO=2), war10=50),
        # P2: pitcher, season 2, 162 IP (486 outs qualifies), ER 24 -> ERA 133; team 9
        line(5, 2, team=9, pitcher=1, pos1=0, totals=tot(G=40, W=12, L=3, SV=30, OUTS=486,
                                                         ER=24, PSO=150), war10=30),
        # P3: pitcher, season 2, 485 outs (not an ERA qualifier), no ER
        line(6, 2, pitcher=1, pos1=0, totals=tot(G=30, W=10, OUTS=485, PSO=100), war10=20),
        # P4: no games: never a WAR leader, whatever its WAR10
        line(7, 1, totals=tot(), war10=99),
    ]


def player_set():
    """Eight career entries 0..7 (the names match the season fixture's entries)."""
    return [
        player('ALPHA', totals=tot(H=3000, AB=9000, HR=400, RBI=1500, R=1200, D2=500, T3=50,
                                   SB=100, BB=1000), war10=650),
        player('BRAVO', totals=tot(H=2000, AB=2999, HR=300, RBI=1000, R=900, D2=300, T3=30,
                                   SB=300, BB=500), war10=300),
        player('CHARLIE', totals=tot(H=2000, AB=3000, HR=300, RBI=1000, R=900, D2=300, T3=30,
                                     SB=300, BB=500), war10=300),
        player('DELTA', totals=tot(H=10), war10=0, awards=(2, 0, 0, 1, 0)),
        player('ECHO', pitcher=1, totals=tot(W=300, OUTS=3704, ER=900, PSO=3000, SHO=18, G=500),
               war10=500),
        player('FOXTROT', pitcher=1, totals=tot(W=200, OUTS=4499, ER=1000, PSO=2000, SHO=18),
               war10=100),
        player('GOLF', pitcher=1, totals=tot(W=200, OUTS=4500, ER=1000, PSO=2000, SHO=17),
               war10=100),
        player('HOTEL', totals=tot(), war10=0),
    ]


# ---------------------------------------------------------------- years and start year (C13.1)
def test_year_of_start_rules():
    for raw, start in ((0, 1993), (1870, 1993), (2101, 1993), (1871, 1871), (2100, 2100),
                       (1992, 1992)):
        d = bytearray(32)
        d[18:20] = raw.to_bytes(2, 'little')
        h = history.History(bytes(d))
        assert dynview.start_year(h) == start, raw
        assert dynview.year_of(h, 1) == start
        assert dynview.year_of(h, 3) == start + 2
    assert dynview.year_of(history.History(None), 1) == 1993     # no HISTORY.DAT: the shipped year


def test_load_lines_header_and_tail(tmp_path):
    assert dynview.load_lines(str(tmp_path)) == []                # missing file
    write_lines(tmp_path, [line(0, 1, totals=tot(G=1)), line(1, 2, totals=tot(G=2))])
    path = tmp_path / 'SEASLINE.DAT'
    good = path.read_bytes()
    got = dynview.load_lines(str(tmp_path))
    assert [(r['entry'], r['season'], r['totals'][0]) for r in got] == [(0, 1, 1), (1, 2, 2)]
    assert got[0]['ratings'] == [9, 8, 7, 6, 5, 4, 3, 2, 1]
    path.write_bytes(good + b'\x01' * 40)                         # a short tail record is dropped
    assert len(dynview.load_lines(str(tmp_path))) == 2
    for patch in ({0: b'XL'}, {2: b'\x02'}, {4: (79).to_bytes(2, 'little')}):
        raw = bytearray(good)
        for off, v in patch.items():
            raw[off:off + len(v)] = v
        path.write_bytes(bytes(raw))
        assert dynview.load_lines(str(tmp_path)) == [], patch   # a bad header gives []
    path.write_bytes(b'SL')                                       # shorter than the header
    assert dynview.load_lines(str(tmp_path)) == []


def test_year_in_every_title_and_label(tmp_path):
    ldir = tmp_path / 'lg'
    write_league(ldir, [player('ALPHA', totals=tot(H=5), hof=2, status=3)], seasons=3,
                 start=1990, ms=[(3, 0, 2, 3000)], lines=season_lines_fixture())
    data = load(ldir)
    cases = {
        (SA, 0, 0): '1992 AWARDS', (SA, 0, 1): '1991 AWARDS',
        (SS, 0, 0): '1992 STANDINGS', (SS, 0, 2): '1990 STANDINGS',
        (SW, 0, 0): '1992 WORLD SERIES', (SB, 0, 0): '1992 WS GAME 1',
        (SB, 0, 8 + 2): '1991 WS GAME 3',
        (dynview.SCREEN_REVIEW, 0, 0): '1992 IN REVIEW',
        (dynview.SCREEN_HISTORY, 0, 0): 'SEASON HISTORY',
        (SO, 0, 0): '1/6 1992 IN REVIEW', (SO, 0, 5): '6/6 1993 IS READY',
        (SO, 0, 5 + 16): '6/6 1993 IS READY',
        (dynview.SCREEN_MENU, 0, 16): 'DYNASTY MODE: 1993',
        (LEAD, 0, BY_YEAR + sidx('H')): '1991 LEADERS: H',         # the newest line season is 2
        (LEAD, 0, BY_YEAR + sidx('H'), 0, 1): '1990 LEADERS: H',
        (LEAD, 0, 0): 'CAREER LEADERS: H',
        (LEAD, 0, SEASON): 'SEASON LEADERS: AVG',
    }
    for state, want in cases.items():
        assert dynview.screen_title(state, data) == want, state
    assert dynview.ready_lines(data, 1)[-1] == 'ENTER: ON TO 1993'
    assert dynview.ready_lines(data, 0)[-1] == 'ENTER: BACK TO THE MENU'
    assert dynview.rows((dynview.SCREEN_HISTORY, 0, 0), data)[0][0] == '1992'
    assert dynview.milestone_rows(data['hist'], data['ms'])[0][0] == '1992'
    assert dynview.hof_rows(data['hist'])[0][1] == '1991'        # IND: the HoF season's year
    assert dynview.screen_title((SET, 0, 0), data) == 'DYNASTY SETTINGS'


def test_start_year_label_and_no_history_default(tmp_path):
    ldir = tmp_path / 'nohist'
    ldir.mkdir()
    data = load(ldir)
    assert dynview.settings_rows(data)[2] == ('START YEAR', '1993')
    assert dynview.screen_title((dynview.SCREEN_MENU, 0, 16), data) == 'DYNASTY MODE: 1993'


# ---------------------------------------------------------------- SEASON and BY YEAR (C13.3)
def season_pairs(label):
    """(entry, season) of the SEASON leader order of the fixture lines for label."""
    lines = [dynview.read_line(r) for r in season_lines_fixture()]
    cat = dynview.SEASON_CATS[sidx(label)]
    return [(e, s) for _v, s, e, _ln in dynview.season_order(lines, cat)]


def test_season_categories_order_qualifiers_and_ties():
    assert season_pairs('AVG') == [(1, 2), (0, 1), (2, 1)]            # D (pa 501) and AB 0 out
    assert season_pairs('HR') == [(0, 1), (2, 1), (1, 2), (3, 1)]      # ties: season, then entry
    assert season_pairs('WAR') == [(0, 1), (4, 1), (2, 1), (1, 2), (5, 2), (6, 2), (3, 1)]
    assert season_pairs('H') == [(3, 1), (2, 1), (0, 1), (1, 2)]
    assert season_pairs('R') == [(0, 1), (1, 2), (2, 1)]              # D has R 0: out
    assert season_pairs('2B') == [(2, 1), (1, 2), (0, 1)]
    assert season_pairs('3B') == [(0, 1), (1, 2)]
    assert season_pairs('SB') == [(0, 1), (2, 1)]
    assert season_pairs('RBI') == [(0, 1), (1, 2), (2, 1)]
    assert season_pairs('BB') == [(1, 2), (0, 1), (3, 1)]
    assert season_pairs('W') == [(4, 1), (5, 2), (6, 2)]
    assert season_pairs('ERA') == [(5, 2), (4, 1)]                    # ascending; P3 485 outs out
    assert season_pairs('SO') == [(4, 1), (5, 2), (6, 2)]             # SO is PSO
    assert season_pairs('SV') == [(5, 2)]
    assert season_pairs('IP') == [(4, 1), (5, 2), (6, 2)]             # IP is OUTS
    assert season_pairs('CG') == [(4, 1)]
    assert season_pairs('SHO') == [(4, 1)]


def test_season_ties_across_seasons_break_by_season_then_entry():
    lines = [dynview.read_line(line(e, s, totals=tot(G=5, HR=9)))
             for e, s in ((4, 3), (1, 2), (0, 2), (2, 1))]
    cat = dynview.SEASON_CATS[sidx('HR')]
    got = [(s, e) for _v, s, e, _ln in dynview.season_order(lines, cat)]
    assert got == [(1, 2), (2, 0), (2, 1), (3, 4)]


def test_season_sho_and_era_ties():
    lines = [dynview.read_line(line(3, 1, totals=tot(G=9, SHO=3, OUTS=486, ER=24))),
             dynview.read_line(line(1, 1, totals=tot(G=9, SHO=3, OUTS=486, ER=24))),
             dynview.read_line(line(2, 2, totals=tot(G=9, SHO=5, OUTS=486, ER=24)))]
    sho = dynview.SEASON_CATS[sidx('SHO')]
    era = dynview.SEASON_CATS[sidx('ERA')]
    assert [e for _v, _s, e, _ln in dynview.season_order(lines, sho)] == [2, 1, 3]
    # equal ERA (133 each): season then entry, ascending
    assert [e for _v, _s, e, _ln in dynview.season_order(lines, era)] == [1, 3, 2]


def test_season_leaders_rows_team_column_and_columns(tmp_path):
    ldir = tmp_path / 'lg'
    write_league(ldir, player_set(), seasons=3, lines=season_lines_fixture())
    (ldir / 'LEAGUE.MAJ').write_bytes(build_maj({0: [(0, 'BOS'), (2, 'DET')], 1: [(0, 'NYA')]}))
    data = load(ldir)
    assert data['abbrs'] == {0: 'BOS', 2: 'DET', 16: 'NYA'}
    hr = (LEAD, 0, SEASON + sidx('HR'))
    assert dynview.rows(hr, data) == [
        ('#1', 'ALPHA, A', '1993', 'BOS', '30'),
        ('#2', 'CHARLIE, A', '1993', 'DET', '30'),
        ('#3', 'BRAVO, A', '1994', 'BOS', '30'),
        ('#4', 'DELTA, A', '1993', 'BOS', '10')]
    assert dynview.body_cols(hr, data) == dynview.COLS_SEASON_LEADERS
    assert dynview.screen_title(hr, data) == 'SEASON LEADERS: HR'
    assert dynview.footer_text(hr, data) == 'LEFT RIGHT  TAB MODE  A ACTIVE  ENTER CARD'  # C54
    era = (LEAD, 0, SEASON + sidx('ERA'))
    rows = dynview.rows(era, data)
    assert rows[0] == ('#1', 'FOXTROT, A', '1994', '?', '1.33')      # team 9: no abbreviation
    assert rows[1] == ('#2', 'ECHO, A', '1993', 'BOS', '1.80')


def test_season_no_lines_message(tmp_path):
    ldir = tmp_path / 'nolines'
    write_league(ldir, player_set(), seasons=3)
    data = load(ldir)
    season = (LEAD, 0, SEASON)
    assert dynview.rows(season, data) == [('NO SEASON LINES RECORDED YET.',)]
    assert dynview.body_cols(season, data) == dynview.COLS_SINGLE
    assert dynview.total_rows(season, data) == 1
    assert dynview.rows((LEAD, 0, BY_YEAR), data) == [('NO SEASON LINES RECORDED YET.',)]


def test_career_categories_order_qualifiers_and_ties(tmp_path):
    ldir = tmp_path / 'career'
    write_league(ldir, player_set(), seasons=3)
    data = load(ldir)
    assert CAREER_LABELS == ['H', 'HR', 'RBI', 'R', '2B', '3B', 'SB', 'BB', 'AVG', 'WAR', 'W',
                             'SV', 'SO', 'ERA', 'IP', 'SHO', 'MVP AWARDS', 'GG AWARDS']
    assert dynview.N_CATS == 18 == len(dynview.CATS)

    def order(label):
        return [i for _v, i, _e in dynview.career_order(data['hist'], cidx(label))]
    assert order('H') == [0, 1, 2, 3]                 # 3000, then the 2000 tie by entry, then 10
    assert order('R') == [0, 1, 2]                    # DELTA R 0 is out
    assert order('2B') == [0, 1, 2]
    assert order('3B') == [0, 1, 2]
    assert order('BB') == [0, 1, 2]
    assert order('SB') == [1, 2, 0]                   # BRAVO 300, CHARLIE 300, ALPHA 100
    assert order('SHO') == [4, 5, 6]                  # 18, 18 (tie by entry), 17
    assert order('IP') == [6, 5, 4]                   # OUTS 4500, 4499, 3704
    assert order('SO') == [4, 5, 6]                   # PSO 3000, 2000 (tie by entry), 2000
    assert order('W') == [4, 5, 6]                    # 300, 200 (tie), 200
    assert order('SV') == []                          # no career saves
    # AVG needs AB >= 3000: BRAVO (2999) is out; CHARLIE .666 leads ALPHA .333
    assert order('AVG') == [2, 0]
    # ERA needs OUTS >= 4500: only GOLF
    assert order('ERA') == [6]
    # WAR has no qualifier: every entry, WAR10 descending, the 0s last by entry
    assert order('WAR') == [0, 4, 1, 2, 5, 6, 3, 7]
    assert order('MVP AWARDS') == [3]                 # awards[0] = 2
    assert order('GG AWARDS') == [3]                  # awards[3] = 1


def test_career_ip_format_and_leader_rows(tmp_path):
    ldir = tmp_path / 'ip'
    write_league(ldir, player_set(), seasons=3)
    data = load(ldir)
    rows = dynview.leaders_rows(data['hist'], cidx('IP'))
    assert rows[0] == ('#1', 'GOLF, A', ' ', '3', '1500.0')
    assert rows[2] == ('#3', 'ECHO, A', ' ', '3', '1234.2')          # 3704 outs: 1234 and two
    assert dynview.fmt_ip(4499) == '1499.2'


def test_career_award_counts_and_tie_break_order(tmp_path):
    ldir = tmp_path / 'aw'
    players = player_set()
    players[1]['awards'] = (2, 0, 0, 0, 0)                            # BRAVO ties DELTA on MVP
    write_league(ldir, players, seasons=3)
    data = load(ldir)
    got = [i for _v, i, _e in dynview.career_order(data['hist'], cidx('MVP AWARDS'))]
    assert got == [1, 3]                                              # equal value: entry ascending


def test_by_year_stepping_and_ends(tmp_path):
    ldir = tmp_path / 'lg'
    write_league(ldir, player_set(), seasons=3, lines=season_lines_fixture())
    (ldir / 'LEAGUE.MAJ').write_bytes(build_maj({0: [(0, 'BOS')]}))
    data = load(ldir)
    s = press((LEAD, 0, SEASON + sidx('H')), TAB, data)
    # BY YEAR starts at the newest season with lines (2 here: the fixture has seasons 1 and 2)
    assert s == (LEAD, 0, BY_YEAR + sidx('H'), 0, 2)
    assert dynview.screen_title(s, data) == '1994 LEADERS: H'
    assert dynview.rows(s, data) == [('#1', 'BRAVO, A', '', 'BOS', '130')]
    assert dynview.footer_text(s, data) == 'LEFT RIGHT STAT  - + YEAR  TAB MODE'
    s = press(s, dynview.KEY_MINUS, data)                             # the older season
    assert s[4] == 1 and dynview.screen_title(s, data) == '1993 LEADERS: H'
    assert [r[1] for r in dynview.rows(s, data)] == ['DELTA, A', 'CHARLIE, A', 'ALPHA, A']
    assert press(s, dynview.KEY_MINUS, data) == s                     # nothing older than 1
    s = press(s, dynview.KEY_EQUALS, data)                            # '=' steps newer
    assert s[4] == 2
    assert press(s, dynview.KEY_PLUS, data) == s                      # nothing past the newest
    s = press(s, dynview.KEY_MINUS, data)                             # back to 1 and forward to 2
    s = press(s, dynview.KEY_PLUS, data)
    assert s[4] == 2


def test_by_year_no_lines_uses_the_last_season(tmp_path):
    ldir = tmp_path / 'nolines'
    write_league(ldir, player_set(), seasons=3)
    data = load(ldir)
    s = press((LEAD, 0, SEASON), TAB, data)                           # SEASON -> BY YEAR
    assert s == (LEAD, 0, BY_YEAR, 0, 3)                              # no lines: season 3
    assert dynview.rows(s, data) == [('NO SEASON LINES RECORDED YET.',)]
    assert press(s, dynview.KEY_MINUS, data) == s and press(s, dynview.KEY_PLUS, data) == s


def test_tab_cycles_modes_and_keeps_the_category_by_label(tmp_path):
    ldir = tmp_path / 'lg'
    write_league(ldir, player_set(), seasons=3, lines=season_lines_fixture())
    data = load(ldir)
    s = press((LEAD, 0, cidx('SV')), TAB, data)                       # CAREER SV -> SEASON SV
    assert s == (LEAD, 0, SEASON + sidx('SV'))
    s = press(s, TAB, data)                                           # -> BY YEAR, newest season
    assert s == (LEAD, 0, BY_YEAR + sidx('SV'), 0, 2)
    s = press(s, TAB, data)                                           # -> POSTSEASON, fallback G
    assert s == (LEAD, 0, 3 * 32)                                      # no SV in POST_CATS
    s = press(s, TAB, data)                                           # -> CAREER, cat from label
    assert s == (LEAD, 0, 0)                                           # G -> index 0
    # MVP AWARDS has no SEASON counterpart: the category falls back to 0
    assert press((LEAD, 2, cidx('MVP AWARDS')), TAB, data) == (LEAD, 0, SEASON)
    # page and cursor reset on TAB
    assert press((LEAD, 0, 0, 2), TAB, data) == (LEAD, 0, SEASON + sidx('H'))


def test_season_top_fifty_cap(tmp_path):
    lines = [line(e, 1, totals=tot(G=1, H=100 + e, AB=500)) for e in range(60)]
    ldir = tmp_path / 'cap'
    write_league(ldir, [player('P%02d' % e, first='A') for e in range(60)], seasons=1, lines=lines)
    data = load(ldir)
    h = (LEAD, 0, SEASON + sidx('H'))
    assert dynview.total_rows(h, data) == 50
    rows = dynview.rows((LEAD, 4, SEASON + sidx('H')), data)
    assert rows[0][0] == '#49' and len(rows) == 2


# ---------------------------------------------------------------- cursor (C13.4)
def test_cursor_up_down_and_page_boundaries(tmp_path):
    ldir = tmp_path / 'cur'
    write_league(ldir, [player('P%02d' % e, first='A', totals=tot(H=10 + e)) for e in range(30)],
                 seasons=3)
    data = load(ldir)
    s = (LEAD, 0, 0)
    assert dynview.total_rows(s, data) == 30
    for _ in range(12):
        s = press(s, DOWN, data)
    assert s == (LEAD, 1, 0, 12)                          # the page follows the cursor
    assert dynview.rows(s, data)[0][0] == '#13'
    assert press(s, UP, data) == (LEAD, 0, 0, 11)
    s = press((LEAD, 0, 0), PGDN, data)
    assert s == (LEAD, 1, 0, 12)                          # PGDN: the page's first row
    s = press(s, PGDN, data)
    assert s == (LEAD, 2, 0, 24)
    assert press(s, PGDN, data) == s                       # the last page: nothing moves
    assert press(s, PGUP, data) == (LEAD, 1, 0, 12)
    assert press((LEAD, 0, 0), UP, data) == (LEAD, 0, 0)   # UP at the top: nothing
    s = (LEAD, 0, 0)
    for _ in range(29):
        s = press(s, DOWN, data)
    assert s == (LEAD, 2, 0, 29)
    assert press(s, DOWN, data) == s                       # DOWN at the last row: nothing


def test_cursor_rows_of_hall_of_fame_awards_and_retire(tmp_path):
    ldir = tmp_path / 'lists'
    players = [player('HOFA', first='A', status=3, hof=2, totals=tot(H=5)),
               player('HOFB', first='B', status=3, hof=3, totals=tot(H=6)),
               player('RET', first='C', status=2, last_season=3, war10=100),
               player('RET2', first='D', status=2, last_season=3, war10=50)]
    write_league(ldir, players, seasons=3, ms=[(3, 2, 64, 1), (3, 0, 96, 1)])
    data = load(ldir)
    assert press((HOF, 0, 0), DOWN, data) == (HOF, 0, 0, 1)
    # HALL OF FAME: the newer HoF season first (HOFB, entry 1), then HOFA (entry 0)
    assert dynview.row_entry((HOF, 0, 0, 0), data) == 1
    assert dynview.row_entry((HOF, 0, 0, 1), data) == 0
    assert dynview.row_entry((HOF, 0, 0, 2), data) is None
    # SEASON AWARDS: the AL MVP (kind 64, entry 2) first, the NL MVP (kind 96, entry 0) second
    assert dynview.row_entry((SA, 0, 0, 0), data) == 2
    assert dynview.row_entry((SA, 0, 0, 1), data) == 0
    assert dynview.row_entry((SA, 0, 0, 2), data) is None
    # RETIREMENTS: WAR descending (RET 100, RET2 50), then the WAR 0 HoF entries by index
    assert dynview.row_entry((SO, 0, OFF_RETIRE, 0), data) == 2
    assert dynview.row_entry((SO, 0, OFF_RETIRE, 1), data) == 3
    assert dynview.row_entry((SO, 0, OFF_RETIRE, 2), data) == 0
    # the cursor screens move with UP and DOWN; the offseason only in its RETIREMENTS phase
    assert press((SA, 0, 0), DOWN, data) == (SA, 0, 0, 1)
    assert press((SO, 0, OFF_RETIRE), DOWN, data) == (SO, 0, OFF_RETIRE, 1)
    assert press((SO, 0, 0), DOWN, data) == (SO, 0, 0)


def test_empty_rows_have_no_entry(tmp_path):
    ldir = tmp_path / 'e'
    write_league(ldir, [player('ONLY', first='A', totals=tot(H=5))], seasons=3)
    data = load(ldir)
    assert dynview.row_entry((LEAD, 0, 0, 5), data) is None
    assert dynview.row_entry((HOF, 0, 0, 0), data) is None
    assert dynview.row_entry((SO, 0, OFF_RETIRE, 0), data) is None


# ---------------------------------------------------------------- ENTER and the PLAYER CARD (C13.4/5)
def award_league(tmp_path):
    players = [player('HOFA', first='A', status=3, hof=2, totals=tot(H=5)),
               player('HOFB', first='B', status=3, hof=3, totals=tot(H=6)),
               player('RET', first='C', status=2, last_season=3, war10=100),
               player('RET2', first='D', status=2, last_season=3, war10=50)]
    ldir = tmp_path / 'open'
    write_league(ldir, players, seasons=3, ms=[(3, 2, 64, 1), (3, 0, 96, 1)],
                 lines=[line(1, 3, totals=tot(G=3, H=6))])
    return ldir


def test_enter_opens_card_from_leaders_hof_awards_and_c_from_retire(tmp_path):
    data = load(award_league(tmp_path))
    # LEADERS career H: HOFB (6, entry 1) then HOFA (5, entry 0)
    s, _ex = dynview.step((LEAD, 0, 0), ENTER, data)
    assert s == (CARD, 0, 1)
    assert press(s, ESC, data) == (LEAD, 0, 0)
    # HALL OF FAME row 1 is HOFA (entry 0)
    s, _ex = dynview.step((HOF, 0, 0, 1), ENTER, data)
    assert s == (CARD, 0, 0)
    assert press(s, ESC, data) == (HOF, 0, 0, 1)
    # SEASON AWARDS row 0 is the AL MVP of entry 2
    s, _ex = dynview.step((SA, 0, 0), ENTER, data)
    assert s == (CARD, 0, 2) and press(s, ESC, data) == (SA, 0, 0)
    # a row past the awards does nothing
    assert dynview.step((SA, 0, 0, 2), ENTER, data) == ((SA, 0, 0, 2), 0)
    # RETIREMENTS: ENTER walks the phases; C opens the card of the highlighted retiree
    off = (SO, 0, OFF_RETIRE)
    assert press(off, ENTER, data) == (SO, 0, OFF_RETIRE + 1)
    s = press(off, DOWN, data)
    assert s == (SO, 0, OFF_RETIRE, 1)
    s, _ex = dynview.step(s, 67, data)                                 # C
    assert s == (CARD, 0, 3)
    assert press(s, ESC, data) == (SO, 0, OFF_RETIRE, 1)
    s, _ex = dynview.step((SO, 0, OFF_RETIRE), 99, data)              # c
    assert s == (CARD, 0, 2)
    assert dynview.step((SO, 0, 0), 67, data) == ((SO, 0, 0), 0)     # C outside RETIREMENTS


def test_enter_on_row_without_player_does_nothing(tmp_path):
    ldir = tmp_path / 'empty'
    write_league(ldir, player_set(), seasons=3, lines=season_lines_fixture())
    data = load(ldir)
    shows = (LEAD, 0, SEASON + sidx('SHO'))                           # one qualifier: P1 (entry 4)
    assert dynview.step(shows, ENTER, data)[0] == (CARD, 0, 4)
    past = (LEAD, 0, SEASON + sidx('SHO'), 3)                         # row 3: no row
    assert dynview.step(past, ENTER, data) == (past, 0)


def test_card_esc_returns_to_the_identical_state(tmp_path):
    ldir = tmp_path / 'esc'
    write_league(ldir, player_set(), seasons=3, lines=season_lines_fixture())
    data = load(ldir)
    lead = (LEAD, 0, 0, 2)                                           # CHARLIE, a cursor row
    s = press(lead, ENTER, data)
    assert s == (CARD, 0, 2)
    assert press(s, ESC, data) == lead
    by = (LEAD, 0, BY_YEAR + sidx('H'), 0, 2)                          # BY YEAR keeps its year
    s = press(by, ENTER, data)
    assert s == (CARD, 0, 1)
    assert press(s, ESC, data) == by


def test_card_season_rows_newest_first_and_paging(tmp_path):
    ldir = tmp_path / 'card'
    recs = [line(0, n, face=7, totals=tot(G=n, AB=400 + n, H=100 + n, HR=n, RBI=n, SB=n, BB=n),
                 war10=10 * n) for n in range(1, 10)]
    write_league(ldir, [player('ALPHA', first='B', totals=tot(G=45, AB=3645, H=945, HR=45),
                               war10=90)], seasons=9, lines=recs)
    data = load(ldir)
    s = (CARD, 0, 0)
    rows = dynview.rows(s, data)
    assert len(rows) == 8                                             # seven seasons and CAREER
    assert [r[0] for r in rows[:7]] == ['2001', '2000', '1999', '1998', '1997', '1996', '1995']
    assert rows[0][2] == '9' and rows[0][3] == '409'                  # G and AB of season 9
    assert rows[7][0] == 'CAREER' and rows[7][2] == '45' and rows[7][3] == '3645'
    s = press(s, PGDN, data)
    assert s == (CARD, 1, 0)
    rows = dynview.rows(s, data)
    assert [r[0] for r in rows[:2]] == ['1994', '1993'] and rows[-1][0] == 'CAREER'
    assert press(s, PGDN, data) == s                                  # the last page stays
    assert press(s, PGUP, data) == (CARD, 0, 0)
    assert press((CARD, 0, 0), PGUP, data) == (CARD, 0, 0)
    assert dynview.total_rows(s, data) == 9
    assert dynview.screen_title(s, data) == 'B ALPHA'
    assert dynview.footer_text(s, data) == 'LEFT RIGHT  PGUP PGDN  H HONORS  ESC'


def test_card_with_no_lines_and_missing_entry(tmp_path):
    ldir = tmp_path / 'nolines'
    write_league(ldir, [player('LONE', first='A', pitcher=1, pos1=0,
                               totals=tot(W=3, OUTS=300, ER=30, PSO=40))], seasons=3)
    data = load(ldir)
    rows = dynview.rows((CARD, 0, 0), data)
    assert rows[0] == ('NO SEASON LINES RECORDED',)
    assert rows[1][0] == 'CAREER' and rows[1][3] == '3' and rows[1][6] == '100.0'
    info, last = dynview.card_info((CARD, 0, 0), data)
    assert last is None
    assert info == ['P', 'ACTIVE, AGE 28', '1993-1995  3 SEASONS', 'NO RATINGS RECORDED', '']
    # an entry index that is not in the table: a blank card, no crash
    assert dynview.rows((CARD, 0, 99), data)[0] == ('NO SEASON LINES RECORDED',)
    assert dynview.screen_title((CARD, 0, 99), data) == '?'


def test_card_info_lines_status_and_ratings(tmp_path):
    ldir = tmp_path / 'info'
    recs = [line(0, 2, pos1=6, hand=0x08, ratings=(12, 3, 11, 9, 7, 6, 0, 0, 0)),
            line(0, 1, pos1=5, hand=0x0E, ratings=(1, 1, 1, 1, 1, 1, 1, 1, 1))]
    write_league(ldir, [player('RETIRED', first='JOE', status=2, first_season=1, last_season=2,
                               played=2, age=34, pos1=5)], seasons=2, start=2000, lines=recs)
    data = load(ldir)
    info, last = dynview.card_info((CARD, 0, 0), data)
    # the latest line is season 2: LF, bats L (hand bits 2..1 = 0), throws R (bit 3)
    assert info[0] == 'LF  BATS L  THROWS R'
    assert info[1] == 'RETIRED 2001'                                  # year_of(2) with start 2000
    assert info[2] == '2000-2001  2 SEASONS'
    assert info[3] == 'POW 12  H&R 11  SPD 9'
    assert info[4] == 'RNG 7  ARM 6  BUNT 3'
    assert last['season'] == 2
    assert dynview.card_title((CARD, 0, 0), data) == 'JOE RETIRED'
    write_league(ldir, [player('HOFMAN', first='A', status=3, hof=2, first_season=1,
                               last_season=2, played=2, age=40)], seasons=2, start=2000, lines=recs)
    info, _ = dynview.card_info((CARD, 0, 0), load(ldir))
    assert info[1] == 'HALL OF FAME 2001'
    pit = [line(0, 1, pitcher=1, pos1=0, ratings=(0, 0, 0, 0, 0, 0, 14, 13, 12))]
    write_league(ldir, [player('ACE', first='A', pitcher=1, pos1=0, totals=tot(W=1))],
                 seasons=1, lines=pit)
    info, _ = dynview.card_info((CARD, 0, 0), load(ldir))
    assert info[0] == 'P  BATS R  THROWS R'
    assert info[3] == 'CTL 14  VEL 13  END 12'
    assert info[4] == ''


def test_card_pitcher_season_columns_and_career(tmp_path):
    ldir = tmp_path / 'pit'
    recs = [line(0, 1, pitcher=1, pos1=0, totals=tot(G=30, W=15, L=5, SV=2, OUTS=900, ER=60,
                                                    PSO=200), war10=50)]
    write_league(ldir, [player('ACE', first='A', pitcher=1, pos1=0,
                               totals=tot(G=30, W=15, L=5, SV=2, OUTS=900, ER=60, PSO=200),
                               war10=50)], seasons=1, lines=recs)
    (ldir / 'LEAGUE.MAJ').write_bytes(build_maj({0: [(0, 'BOS')]}))
    data = load(ldir)
    assert dynview.card_pitcher((CARD, 0, 0), data)
    season, career, post = dynview.card_table((CARD, 0, 0), data)
    assert post is None
    assert season[0] == ('1993', 'BOS', '30', '15', '5', '2', '300.0', '200', '1.80', '5.0')
    assert career[2:] == ('30', '15', '5', '2', '300.0', '200', '1.80', '5.0')


# ---------------------------------------------------------------- portraits (C13.5)
def portrait_frame(value):
    """One stored frame: 12 B header (flags, h 56, w 48, yo, xo, clen 0) and 2688 B of value."""
    return struct.pack('<6H', 0, 56, 48, 0, 0, 0) + bytes([value]) * (48 * 56)


def write_portraits(anms, game):
    anms.mkdir(parents=True, exist_ok=True)
    body = b''.join(portrait_frame(10 + k) for k in range(4))
    (anms / 'PORTRAIT.ANM').write_bytes(struct.pack('<H', 4) + body)
    game.mkdir(parents=True, exist_ok=True)
    (game / 'OLDPORT.ANM').write_bytes(portrait_frame(100) + portrait_frame(101))


def test_portrait_stock_old_and_missing(tmp_path):
    anms, game = tmp_path / 'ANMS', tmp_path / 'game'
    write_portraits(anms, game)
    data = {'anms_dir': str(anms), 'game_dir': str(game)}
    w, h, px = dynview.portrait_of(data, 2)                           # PORTRAIT.ANM frame 2
    assert (w, h) == (48, 56) and px[0] == 12 and len(px) == 48 * 56
    assert dynview.portrait_of(data, 980) is None                     # past the 4 stock frames
    assert dynview.portrait_of(data, 981)[2][0] == 100                # OLDPORT frame 0
    assert dynview.portrait_of(data, 982)[2][0] == 101                # OLDPORT frame 1
    assert dynview.portrait_of(data, 983) is None                     # past the file
    assert dynview.portrait_of(data, 1509) is None                    # 1509 and up: no frame
    bad = bytearray(portrait_frame(100))
    bad[10:12] = (5).to_bytes(2, 'little')                            # clen must be 0
    (game / 'OLDPORT.ANM').write_bytes(bytes(bad))
    assert dynview.portrait_of(data, 981) is None
    assert dynview.portrait_of({'anms_dir': str(tmp_path / 'none'), 'game_dir': str(tmp_path)},
                               3) is None


def test_card_portrait_from_oldport_and_missing_box(tmp_path):
    ldir = tmp_path / 'lg'
    anms, game = tmp_path / 'ANMS', tmp_path / 'game'
    write_portraits(anms, game)
    fonts = make_fonts(tmp_path / 'fonts')
    write_league(ldir, [player('ALPHA', first='B', totals=tot(G=1, AB=1))], seasons=2,
                 lines=[line(0, 1, face=2), line(0, 2, face=981)])
    data = load(ldir, fonts, str(game), str(anms))
    fb = dynview.render((CARD, 0, 0), data)
    assert fb[24 * 320 + 12] == 100                                   # the latest line: OLDPORT 0
    assert fb[79 * 320 + 59] == 100
    # a face past the old portraits: the gray box with a ? in its middle
    write_league(ldir, [player('ALPHA', first='B', totals=tot(G=1, AB=1))], seasons=2,
                 lines=[line(0, 2, face=1600)])
    data = load(ldir, fonts, str(game), str(anms))
    fb = dynview.render((CARD, 0, 0), data)
    assert fb[24 * 320 + 12] == dynview.C_GRID_GRAY and fb[79 * 320 + 59] == dynview.C_GRID_GRAY
    assert any(fb[y * 320 + x] == dynview.C_WHITE for y in range(24, 80) for x in range(12, 60))
    # no line at all: the box as well
    write_league(ldir, [player('ALPHA', first='B', totals=tot(G=1, AB=1))], seasons=2)
    data = load(ldir, fonts, str(game), str(anms))
    assert dynview.render((CARD, 0, 0), data)[24 * 320 + 12] == dynview.C_GRID_GRAY


def test_stock_portrait_drawn_from_anms(tmp_path):
    ldir = tmp_path / 'lg'
    anms, game = tmp_path / 'ANMS', tmp_path / 'game'
    write_portraits(anms, game)
    fonts = make_fonts(tmp_path / 'fonts')
    write_league(ldir, [player('ALPHA', first='B', totals=tot(G=1, AB=1))], seasons=1,
                 lines=[line(0, 1, face=3)])
    data = load(ldir, fonts, str(game), str(anms))
    assert dynview.render((CARD, 0, 0), data)[24 * 320 + 12] == 13   # PORTRAIT.ANM frame 3


# ---------------------------------------------------------------- START YEAR (C13.1)
def diff_positions(a, b):
    assert len(a) == len(b)
    return {i for i in range(len(a)) if a[i] != b[i]}


def test_start_year_steps_clamp_and_write_only_bytes_18_19(tmp_path):
    ldir = tmp_path / 'sy'
    write_league(ldir, [player('ALPHA', first='B', totals=tot(H=1))], seasons=3, start=1900)
    hp = ldir / 'HISTORY.DAT'
    before = hp.read_bytes()
    data = load(ldir)
    s = (SET, 0, 2)
    assert dynview.settings_rows(data)[2] == ('START YEAR', '1900')
    assert press(s, RIGHT, data) == s                                 # the state does not move
    after = hp.read_bytes()
    assert diff_positions(before, after) <= {18, 19}
    assert int.from_bytes(after[18:20], 'little') == 1901
    assert data['hist'].d[18:20] == after[18:20]                      # the labels follow now
    assert dynview.settings_rows(data)[2] == ('START YEAR', '1901')
    press(s, LEFT, data)
    assert int.from_bytes(hp.read_bytes()[18:20], 'little') == 1900
    press(s, dynview.KEY_MINUS, data)                                 # '-' = -10
    assert int.from_bytes(hp.read_bytes()[18:20], 'little') == 1890
    press(s, dynview.KEY_PLUS, data)                                  # '+' = +10
    assert int.from_bytes(hp.read_bytes()[18:20], 'little') == 1900
    press(s, dynview.KEY_EQUALS, data)                                # '=' = +10
    assert int.from_bytes(hp.read_bytes()[18:20], 'little') == 1910
    assert diff_positions(before, hp.read_bytes()) <= {18, 19}
    # clamps at 1871 and 2100
    hp.write_bytes(before[:18] + (1872).to_bytes(2, 'little') + before[20:])
    data = load(ldir)
    press(s, dynview.KEY_MINUS, data)
    assert int.from_bytes(hp.read_bytes()[18:20], 'little') == 1871
    press(s, LEFT, data)
    assert int.from_bytes(hp.read_bytes()[18:20], 'little') == 1871
    hp.write_bytes(before[:18] + (2095).to_bytes(2, 'little') + before[20:])
    data = load(ldir)
    press(s, dynview.KEY_PLUS, data)
    assert int.from_bytes(hp.read_bytes()[18:20], 'little') == 2100
    press(s, RIGHT, data)
    assert int.from_bytes(hp.read_bytes()[18:20], 'little') == 2100
    # ENTER on the row does nothing; the other rows ignore the year keys
    b4 = hp.read_bytes()
    assert press(s, ENTER, data) == s and hp.read_bytes() == b4
    assert press((SET, 0, 0), RIGHT, data) == (SET, 0, 0)
    assert hp.read_bytes() == b4


def test_start_year_zero_is_1993_and_missing_history_is_created(tmp_path):
    ldir = tmp_path / 'zero'
    ldir.mkdir()
    data = load(ldir)
    assert data['hist'].seasons_recorded == 0
    press((SET, 0, 2), RIGHT, data)
    hp = ldir / 'HISTORY.DAT'
    got = hp.read_bytes()
    assert len(got) == 32
    assert int.from_bytes(got[18:20], 'little') == 1994               # 0 counts as 1993, + 1
    assert got[:18] == bytes(18) and got[20:] == bytes(12)
    # a short file is zero extended and only bytes 18..19 change
    hp.write_bytes(b'\x01\x02\x03\x04')
    data = load(ldir)
    press((SET, 0, 2), dynview.KEY_MINUS, data)                       # 1993 - 10
    got = hp.read_bytes()
    assert len(got) == 32 and got[:4] == b'\x01\x02\x03\x04'
    assert int.from_bytes(got[18:20], 'little') == 1983


# ---------------------------------------------------------------- clicks and --keys (C13.6)
def test_parse_keys_tokens_and_backward_compatibility():
    assert dynview.parse_keys('') == []
    assert dynview.parse_keys('13,0x4b00, 9') == [13, 0x4b00, 9]
    assert dynview.parse_keys('L100.60,R,51') == [('L', 100, 60), ESC, 51]


def test_click_hub_rows_title_footer_and_right_side(tmp_path):
    ldir = tmp_path / 'hub'
    write_league(ldir, player_set(), seasons=3)
    data = load(ldir)
    assert dynview.click_to_key(HUB, data, 100, 60) == (ord('3'), None)     # body row 2
    assert dynview.click_to_key(HUB, data, 100, 40) == (ord('1'), None)     # body row 0
    assert dynview.click_to_key(HUB, data, 100, 148) == (ord('W'), None)    # body row 10
    assert dynview.click_to_key(HUB, data, 100, 67) == (None, None)         # the gap after row 2
    assert dynview.click_to_key(HUB, data, 100, 14) == (None, None)         # title, not LEFT/RIGHT
    assert dynview.click_to_key(HUB, data, 100, 190) == (PGUP, None)        # footer, left
    assert dynview.click_to_key(HUB, data, 250, 190) == (PGDN, None)        # footer, right
    assert dynview.click_to_key(HUB, data, 100, 0) == (None, None)
    assert press(HUB, ord('3'), data) == (LEAD, 0, 0)


def test_click_list_row_opens_card_and_empty_row_does_nothing(tmp_path):
    ldir = tmp_path / 'list'
    write_league(ldir, player_set(), seasons=3)
    data = load(ldir)
    lead = (LEAD, 0, 0)
    key, row = dynview.click_to_key(lead, data, 100, 35 + 11 + 4)     # row 1
    assert (key, row) == (ENTER, 1)
    s = press(dynview.cursor_to(lead, row), key, data)
    assert s == (CARD, 0, dynview.career_order(data['hist'], 0)[1][1])
    assert dynview.total_rows(lead, data) == 4
    assert dynview.click_to_key(lead, data, 100, 35 + 11 * 6 + 2) == (None, None)  # row 6: empty
    assert dynview.click_to_key(lead, data, 100, 28) == (None, None)           # header band


def test_click_settings_rows_and_start_year_sides(tmp_path):
    ldir = tmp_path / 'set'
    write_league(ldir, player_set(), seasons=3, start=1993)
    data = load(ldir)
    st = (SET, 0, 0)
    assert dynview.click_to_key(st, data, 100, 35 + 22 + 3) == (LEFT, 2)     # START YEAR, left
    assert dynview.click_to_key(st, data, 200, 35 + 22 + 3) == (RIGHT, 2)    # START YEAR, right
    assert dynview.click_to_key(st, data, 100, 35 + 11 + 3) == (ENTER, 1)    # PLAYOFF FORMAT
    assert dynview.click_to_key(st, data, 100, 35 + 33 + 3) == (None, None)  # no team row here
    s = press(dynview.cursor_to(st, 2), LEFT, data)                       # the START YEAR click
    assert int.from_bytes((ldir / 'HISTORY.DAT').read_bytes()[18:20], 'little') == 1992
    assert s == (SET, 0, 2)


def test_click_retirement_row_sends_c_and_opens_card(tmp_path):
    data = load(award_league(tmp_path))
    off = (SO, 0, OFF_RETIRE)
    key, row = dynview.click_to_key(off, data, 100, 35 + 11 + 4)      # RETIREMENTS row 1
    assert (key, row) == (67, 1)                                      # C, not ENTER (ENTER walks)
    assert press(dynview.cursor_to(off, row), key, data) == (CARD, 0, 3)
    assert dynview.click_to_key((SO, 0, 0), data, 100, 35 + 11 + 4) == (None, None)


def test_click_title_band_left_right_and_footer_pages(tmp_path):
    ldir = tmp_path / 'tb'
    write_league(ldir, [player('P%02d' % e, first='A', totals=tot(H=10 + e)) for e in range(30)],
                 seasons=3)
    data = load(ldir)
    lead = (LEAD, 0, 0)
    assert dynview.click_to_key(lead, data, 100, 14) == (LEFT, None)
    assert dynview.click_to_key(lead, data, 250, 14) == (RIGHT, None)
    assert press(lead, LEFT, data) == (LEAD, 0, 17)                    # LEFT wraps to GG AWARDS
    assert press(lead, RIGHT, data) == (LEAD, 0, 1)
    assert dynview.click_to_key(lead, data, 250, 190) == (PGDN, None)
    s = press(lead, PGDN, data)
    assert s == (LEAD, 1, 0, 12)
    assert dynview.click_to_key(s, data, 100, 190) == (PGUP, None)
    assert dynview.click_to_key((SA, 0, 0), data, 100, 14) == (LEFT, None)
    assert dynview.click_to_key((dynview.SCREEN_HISTORY, 0, 0), data, 100, 14) == (None, None)


def test_main_applies_click_and_right_click_tokens(tmp_path):
    ldir = tmp_path / 'main'
    fonts = make_fonts(tmp_path / 'fonts')
    write_league(ldir, player_set(), seasons=3, lines=season_lines_fixture())
    data = dynview.load_data(str(ldir), fonts)
    out = tmp_path / 'out.raw'

    def run(keys):
        dynview.main(['--keys', keys, '--raw', str(out), str(ldir), fonts])
        return out.read_bytes()
    assert run('L100.60') == bytes(dynview.render((LEAD, 0, 0), data))       # hub row 3
    assert run('L100.60,L100.50') == bytes(dynview.render((CARD, 0, 1), data))   # row 1's card
    # a right click returns from the card to the list state it came from (the cursor on row 1)
    assert run('L100.60,L100.50,R') == bytes(dynview.render((LEAD, 0, 0, 1), data))


def test_main_game_dir_anms_dir_options(tmp_path):
    ldir = tmp_path / 'opts'
    fonts = make_fonts(tmp_path / 'fonts')
    anms, game = tmp_path / 'ANMS', tmp_path / 'game'
    write_portraits(anms, game)
    write_league(ldir, [player('ALPHA', first='B', totals=tot(H=5))], seasons=1,
                 lines=[line(0, 1, face=981)])                       # OLDPORT frame 0 (pixel 100)
    out = tmp_path / 'o.raw'
    # the hub, then row 0 of the LEADERS (ALPHA): the PLAYER CARD with its OLDPORT portrait
    dynview.main(['--keys', 'L100.60,L100.38', '--raw', str(out), '--game-dir', str(game),
                  '--anms-dir', str(anms), str(ldir), fonts])
    got = out.read_bytes()
    assert got[24 * 320 + 12] == 100 and got[79 * 320 + 59] == 100
    data = dynview.load_data(str(ldir), fonts, str(game), str(anms))
    assert got == bytes(dynview.render((CARD, 0, 0), data))
    # without the game dir the OLDPORT frame is missing: the gray box
    dynview.main(['--keys', 'L100.60,L100.38', '--raw', str(out), '--game-dir', str(tmp_path),
                  '--anms-dir', str(anms), str(ldir), fonts])
    assert out.read_bytes()[24 * 320 + 12] == dynview.C_GRID_GRAY


# ---------------------------------------------------------------- renders per new screen state
def test_render_every_new_screen_state_to_png(tmp_path):
    ldir = tmp_path / 'render'
    fonts = make_fonts(tmp_path / 'fonts')
    anms, game = tmp_path / 'ANMS', tmp_path / 'game'
    write_portraits(anms, game)
    players = player_set() + [player('RET', first='Z', status=2, last_season=3, war10=100),
                              player('HALL', first='H', status=3, hof=2),
                              player('HALLTWO', first='I', status=3, hof=3)]
    write_league(ldir, players, seasons=3, start=1990, lines=season_lines_fixture(),
                 ms=[(3, 2, 64, 1), (3, 0, 96, 1), (3, 0, 2, 3000)])
    (ldir / 'LEAGUE.MAJ').write_bytes(build_maj({0: [(0, 'BOS'), (2, 'DET')], 1: [(0, 'NYA')]}))
    data = dynview.load_data(str(ldir), fonts, str(game), str(anms))
    out = tmp_path / 'png'
    out.mkdir()
    states = [
        (LEAD, 0, 0), (LEAD, 0, 1, 0), (LEAD, 1, SEASON + sidx('HR')),
        (LEAD, 0, BY_YEAR + sidx('H'), 0, 2), (HOF, 0, 0, 0), (SA, 0, 0, 1),
        (SO, 0, OFF_RETIRE, 0), (SET, 0, 2), (ABOUT, 0, 0), (dynview.SCREEN_MENU, 0, 0),
        (CARD, 0, 0), (CARD, 0, 4), (CARD, 0, 7), (CARD, 1, 4),
    ]
    for i, state in enumerate(states):
        fb = dynview.render(state, data)
        assert len(fb) == dynview.FB_SIZE
        dynview.write_png(str(out / ('s%02d.png' % i)), fb, dynview.load_palette())
    assert len(list(out.iterdir())) == len(states)
    # the cursor row is C_TITLE_RED; the other rows of a list are C_ROW_TAN
    fb = dynview.render((HOF, 0, 0, 1), data)
    assert fb[(35 + 11 + 1) * 320 + 9] == dynview.C_TITLE_RED
    assert fb[(35 + 1) * 320 + 9] == dynview.C_ROW_TAN
    assert dynview.render((LEAD, 0, 0), data)[(35 + 1) * 320 + 9] == dynview.C_TITLE_RED


def test_render_list_screens_with_no_season_lines(tmp_path):
    ldir = tmp_path / 'nl'
    fonts = make_fonts(tmp_path / 'fonts')
    write_league(ldir, player_set(), seasons=3)
    data = load(ldir, fonts)
    for state in ((LEAD, 0, SEASON), (LEAD, 0, BY_YEAR), (CARD, 0, 0)):
        assert len(dynview.render(state, data)) == dynview.FB_SIZE


def test_about_gains_the_leaders_and_start_year_block():
    rows = dynview.ABOUT_ROWS
    assert 'LEADERS: CAREER, SINGLE SEASON AND BY' in rows
    assert 'YEAR. TAB SWITCHES. ENTER OR A CLICK ON A' in rows
    assert 'PLAYER OPENS HIS CARD.' in rows
    assert 'START YEAR: DYNASTY SETTINGS, LEFT RIGHT.' in rows
    i = rows.index('LEADERS: CAREER, SINGLE SEASON AND BY')
    assert rows[i - 1] == '' and rows[i - 2] == 'GENERATED SCHEDULE.'
    assert dynview.MENU_ROWS[2] == '3  LEADERS'
    assert all(len(t) <= 42 for t in rows)


def test_by_year_left_right_keep_the_season(tmp_path):
    ldir = tmp_path / 'lg'
    write_league(ldir, player_set(), seasons=3, lines=season_lines_fixture())
    data = load(ldir)
    s = (LEAD, 0, BY_YEAR + sidx('H'), 0, 1)
    s = press(s, dynview.KEY_RIGHT, data)
    assert s[4] == 1 and dynview.screen_title(s, data) == '1993 LEADERS: ' + dynview.SEASON_CATS[sidx('H') + 1][0]
    s = press(s, dynview.KEY_LEFT, data)
    assert s == (LEAD, 0, BY_YEAR + sidx('H'), 0, 1)


def test_seasline_header_byte_3_must_be_zero(tmp_path):
    ldir = tmp_path / 'lg'
    write_league(ldir, player_set(), seasons=3, lines=season_lines_fixture())
    p = ldir / 'SEASLINE.DAT'
    assert dynview.load_lines(str(ldir))
    b = bytearray(p.read_bytes())
    b[3] = 1
    p.write_bytes(bytes(b))
    assert dynview.load_lines(str(ldir)) == []


# ---------------------------------------------------------------- C23c hub and clicks
def test_hub_rows_and_key_p(tmp_path):
    """C23c: the 12-row hub, key P and p (80/112) opening PLAYOFFS, a click on the hub's
    PLAYOFFS row giving ord('P'), and the hub footer unchanged"""
    ldir = tmp_path / 'hub'
    write_league(ldir, player_set(), seasons=3)
    data = load(ldir)
    assert dynview.MENU_ROWS[11] == 'P  PLAYOFFS'
    assert len(dynview.MENU_ROWS) == 12
    assert dynview.total_rows(HUB, data) == 12
    assert dynview.rows(HUB, data)[11] == ('P  PLAYOFFS',)
    assert dynview.SCREEN_PLAYOFFS == 14 and dynview.SCREEN_PBOX == 15
    for key in (80, 112):
        assert press(HUB, key, data) == (dynview.SCREEN_PLAYOFFS, 0, 0)
    assert dynview.click_to_key(HUB, data, 100, 35 + 11 * 11 + 3) == (80, None)
    assert dynview.footer_text(HUB, data) == '0-9 W P F SELECT   ESC EXIT'
    assert dynview.TITLE_FOOTER == '0-9 W SELECT   ENTER PLAY BALL'
    assert dynview.FOOTERS[dynview.SCREEN_PLAYOFFS] == \
        'ENTER BOX  LEFT RIGHT SEASON  PGUP PGDN  ESC'
    assert dynview.FOOTERS[dynview.SCREEN_PBOX] == \
        'ENTER CARD  LEFT RIGHT GAME  PGUP PGDN  ESC'


def test_playoffs_keys_titles_and_walk_no_fonts(tmp_path):
    """C23c state machine without fonts: LEFT and RIGHT seasons, PGUP and PGDN, ENTER's
    box choice by page, the PBOX walk and ESC, LEFT from the WS box into the PBOX, the
    empty season's keys and the titles"""
    ldir = tmp_path / 'pl'
    write_league(ldir, player_set(), seasons=3, ms=[(3, 0, 192, 5 * 256 + 3)])
    write_box(ldir, [
        box_rec(3, 16, 4, 0 * 256 + 16, (5, 3, 9, 7, 1, 0, 0, 0), b=1, i=1),
        box_rec(3, 16, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)),
        box_rec(3, 16, 2, 0xffff, (80, 5, 2, 2, 1, 1, 8, 30)),
        box_rec(3, 17, 4, 0 * 256 + 16, (2, 6, 8, 6, 0, 1, 0, 0), b=1, i=2),
        box_rec(3, 17, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)),
        box_rec(3, 17, 2, 0xffff, (80, 5, 2, 2, 1, 1, 8, 30)),
    ])
    data = load(ldir)
    SP, SPB, SB = dynview.SCREEN_PLAYOFFS, dynview.SCREEN_PBOX, dynview.SCREEN_BOX
    assert dynview.screen_title((SP, 0, 0), data) == '1995 PLAYOFFS'
    assert dynview.screen_title((SP, 0, 1), data) == '1994 PLAYOFFS'
    assert dynview.screen_title((SPB, 0, 0), data) == '1995 AL DS GAME 1'
    assert dynview.screen_title((SPB, 0, 1), data) == '1995 AL DS GAME 2'
    # one AL DS series of 2 games (1-1: SERIES)
    rows = dynview.playoffs_body((SP, 0, 0), data)[1]
    assert rows[0][0] == 'AL DIVISION SERIES'
    assert rows[1] == ('GAME 1', '', '', '', '')
    assert rows[-1] == ('SERIES', '', '', '', 'TIED 1-1')
    assert dynview.step((SP, 0, 0), ENTER, data) == ((SPB, 0, 0), 0)
    # ESC from PBOX to PLAYOFFS, LEFT and RIGHT walk the round games
    assert dynview.step((SPB, 0, 1), ESC, data) == ((SP, 0, 0), 0)
    assert dynview.step((SPB, 0, 0), RIGHT, data) == ((SPB, 0, 1), 0)
    assert dynview.step((SPB, 0, 1), LEFT, data) == ((SPB, 0, 0), 0)
    # the season's WS game 1 (kind 192 record): LEFT from it opens the last round box
    assert dynview.step((SB, 0, 0), LEFT, data) == ((SPB, 0, 1), 0)
    # the empty season (cat 1): the message row and the no-op keys
    assert dynview.rows((SP, 0, 1), data) == [('NO PLAYOFF ROUNDS RECORDED',)]
    assert dynview.step((SP, 0, 1), ENTER, data) == ((SP, 0, 1), 0)
    assert dynview.body_cols((SP, 0, 1), data) == dynview.COLS_SINGLE
    assert dynview.step((SP, 0, 1), LEFT, data) == ((SP, 0, 2), 0)
    assert dynview.step((SP, 0, 2), RIGHT, data) == ((SP, 0, 1), 0)
    assert dynview.step((SP, 0, 0), RIGHT, data) == ((SP, 0, 0), 0)
    # PGUP and PGDN page as every list screen
    assert dynview.step((SP, 0, 0), PGDN, data) == ((SP, 0, 0), 0)
    assert dynview.screen_title((SPB, 0, 0), data) == '1995 AL DS GAME 1'


# ---------------------------------------------------------------- C26 POSTSEASON row
def test_post_totals_sums_by_entry(tmp_path):
    """post_totals over a batter in 3 WS games and 2 round games (a round header with each
    round game), a pitcher with IP10 72 + 15, a record of another entry ignored"""
    ldir = tmp_path / 'post'
    write_league(ldir, player_set(), seasons=3)
    box = [box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0)),
           box_rec(3, 1, 0, 0, (3, 0, 1, 2, 1, 0, 0, 2)),
           box_rec(3, 2, 0, 0, (3, 1, 1, 0, 1, 0, 0, 1)),
           box_rec(3, 16, 4, 0 * 256 + 16, (5, 3, 9, 7, 1, 0, 0, 0), b=1, i=1),
           box_rec(3, 16, 0, 0, (2, 0, 1, 0, 0, 0, 1, 1)),
           box_rec(3, 17, 4, 0 * 256 + 16, (2, 6, 8, 6, 0, 1, 0, 0), b=1, i=2),
           box_rec(3, 17, 0, 0, (1, 0, 0, 1, 0, 0, 0, 0)),
           # another entry's rows are ignored
           box_rec(3, 0, 0, 1, (10, 0, 9, 9, 9, 0, 0, 9)),
           # the pitcher: IP10 72 (7 2/3: outs 23) then 12 (1 2/3: outs 5), total 28 = 9.1 IP
           box_rec(3, 0, 2, 5, (72, 5, 2, 2, 1, 1, 8, 30)),
           box_rec(3, 16, 2, 5, (12, 1, 1, 0, 0, 0, 2, 6)),
           # a flags 4 record carrying the same idx is a header, skipped
           box_rec(3, 2, 4, 5, (9, 9, 9, 9, 9, 9, 9, 9))]
    write_box(ldir, box)
    data = load(ldir)
    games, t = dynview.post_totals(data['box'], 0)
    assert (games, t[0]) == (5, 5)                                    # 3 WS + 2 round games
    assert t[1] == 4 + 3 + 3 + 2 + 1 and t[2] == 2 + 1 + 1 + 1 + 0
    assert t[7] == 1 + 2 + 0 + 0 + 1 and t[5] == 0 + 1 + 1 + 0 + 0
    assert t[10] == 0 + 2 + 1 + 1 + 0
    assert all(t[i] == 0 for i in (3, 4, 6, 8, 9, 11, 12, 13, 14, 15, 19, 20, 23))
    games, t = dynview.post_totals(data['box'], 5)
    assert games == 2
    assert t[19] == 28 and t[20] == 2 and t[23] == 10
    assert t[0] == 2 and all(t[i] == 0 for i in (1, 2, 5, 7, 10, 13, 14, 15))
    assert dynview.post_totals(data['box'], 6) is None                # no rows for entry 6
    assert dynview.post_totals([], 0) is None


def test_card_post_row_cells_and_paging(tmp_path):
    """card_table's POST row: a batter with AVG from H/AB and a pitcher with IP '9.1',
    ERA from ER/OUTS, W L SV and WAR '-'; 6 season rows per page with POST, 7 without;
    the 8-line entry pages 6 + 2"""
    ldir = tmp_path / 'postbat'
    recs = [line(0, n, totals=tot(G=100 + n, AB=400 + n, H=100 + n, HR=n, RBI=n, SB=n),
                 war10=10 * n) for n in range(1, 9)]
    write_league(ldir, [player('ALPHA', first='B', totals=tot(G=800, AB=3604, H=904, HR=36),
                               war10=80)], seasons=8, lines=recs)
    write_box(ldir, [box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0)),
                     box_rec(3, 1, 0, 0, (3, 0, 1, 2, 1, 0, 0, 2)),
                     box_rec(3, 6, 0, 0, (3, 1, 1, 0, 1, 0, 0, 1)),
                     box_rec(3, 16, 4, 0 * 256 + 16, (5, 3, 9, 7, 1, 0, 0, 0), b=1, i=1),
                     box_rec(3, 16, 0, 0, (2, 0, 1, 0, 0, 0, 1, 1)),
                     box_rec(3, 17, 4, 0 * 256 + 16, (2, 6, 8, 6, 0, 1, 0, 0), b=1, i=2),
                     box_rec(3, 17, 0, 0, (1, 0, 0, 1, 0, 0, 0, 0))])
    data = load(ldir)
    assert dynview.card_rows((CARD, 0, 0), data) == 6
    season, career, post = dynview.card_table((CARD, 0, 0), data)
    assert len(season) == 6 and [r[0] for r in season] == \
        ['2000', '1999', '1998', '1997', '1996', '1995']
    # 3 WS games and 2 round games: G 5, AB 13, H 5 (AVG .384), HR 2, RBI 4, SB 4
    assert post == ('POSTSEASON', '', '5', '13', '5', '2', '4', '4', '.384', '-')
    assert career[0] == 'CAREER'
    # the newest line first, 6 to a page: page 1 holds the last two seasons
    s = press((CARD, 0, 0), PGDN, data)
    assert s == (CARD, 1, 0)
    season, _career, _post = dynview.card_table(s, data)
    assert [r[0] for r in season] == ['1994', '1993']
    assert dynview.rows(s, data)[-2][0] == 'CAREER'
    assert dynview.rows(s, data)[-1] == post
    assert dynview.total_rows(s, data) == 8
    assert press(s, PGDN, data) == s                                  # the last page stays
    # a pitcher: IP '9.1' (28 outs), ERA from ER / OUTS (2 * 2700 / 28), W L SV '-'
    ldir2 = tmp_path / 'postpit'
    write_league(ldir2, [player('ACE', first='A', pitcher=1, pos1=0,
                                totals=tot(W=10, OUTS=500, ER=100, PSO=50))], seasons=2,
                 lines=[line(0, 1, pitcher=1, pos1=0, totals=tot(G=20, W=5, OUTS=300,
                                                                  ER=50, PSO=30), war10=20)])
    # header records only: the idx here is the entry, so post_totals finds the player rows
    write_box(ldir2, [box_rec(3, 0, 2, 0, (72, 5, 2, 2, 1, 1, 8, 30)),
                      box_rec(3, 3, 2, 0, (12, 1, 1, 0, 0, 0, 2, 6)),
                      box_rec(3, 0, 4, 0, (1, 2, 3, 4, 5, 6, 7, 8))])
    data2 = load(ldir2)
    assert dynview.card_pitcher((CARD, 0, 0), data2)
    _season, _career, post = dynview.card_table((CARD, 0, 0), data2)
    assert post == ('POSTSEASON', '', '2', '-', '-', '-', '9.1', '10', '1.92', '-')
    # no box rows: the third item None and 7 season rows per page
    ldir3 = tmp_path / 'nopost'
    recs3 = [line(0, n, totals=tot(G=n, AB=100 + n, H=10 + n)) for n in range(1, 9)]
    write_league(ldir3, [player('LONE', first='A')], seasons=8, lines=recs3)
    data3 = load(ldir3)
    assert dynview.post_totals(data3['box'], 0) is None
    assert dynview.card_rows((CARD, 0, 0), data3) == 7
    season, _career, post = dynview.card_table((CARD, 0, 0), data3)
    assert post is None and len(season) == 7
    assert dynview.total_rows((CARD, 0, 0), data3) == 8
    # an entry that is not in the table: no crash, no POST row
    assert dynview.card_table((CARD, 0, 99), data3) == \
        ([(dynview.NO_CARD_TEXT,)], ('CAREER',), None)


# ---------------------------------------------------------------- C27 MILESTONES WATCH
MS = dynview.SCREEN_MILESTONES


def watch_league(tmp_path):
    """The C27 fixture: active batters at H 2950 (row) and 1700 (no row, 85% cut), HR 298
    and HR 395 rows, a retired H 2990 (no row), a PSO 2995 pitcher, H 3100 (no higher H
    mark) and two 500-SB ties (entry order breaks them)"""
    players = [
        player('HIT2950', first='A', totals=tot(H=2950, AB=8000)),
        player('HIT1700', first='B', totals=tot(H=1700, AB=5000)),
        player('HIT3100', first='C', totals=tot(H=3100, AB=9000)),
        player('HR298', first='D', totals=tot(HR=298, AB=3000, H=800)),
        player('HR395', first='E', totals=tot(HR=395, AB=3000, H=800)),
        player('RETIRED', first='F', status=2, totals=tot(H=2990, AB=8000)),
        player('KMAN', first='G', pitcher=1, pos1=0, totals=tot(PSO=2995, G=400,
                                                               OUTS=8000)),
        player('SBTIE1', first='H', totals=tot(SB=490)),
        player('SBTIE2', first='I', totals=tot(SB=490)),
    ]
    ldir = tmp_path / 'watch'
    write_league(ldir, players, seasons=3)
    return load(ldir)


def test_watch_items_selection_and_sort(tmp_path):
    """active only, the lowest unreached mark per key, the 90% floor (now * 10 >= mark * 9),
    no row once a key's top mark is reached; sorted by need per mille, need, entry, kind"""
    data = watch_league(tmp_path)
    hist = data['hist']
    items = dynview.watch_items(hist)
    # (need, mark, kind, entry, now); 1700 H (85%) and the retired 2990 are out, 3100 H too
    assert items[0] == (5, 3000, 14, 6, 2995)          # PSO 2995: 1 per mille
    assert items[1] == (2, 300, 3, 3, 298)             # HR 298: 6
    assert items[2] == (5, 400, 4, 4, 395)             # HR 395: 12 (kind 4, the chosen
    assert items[3] == (50, 3000, 2, 0, 2950)          #   mark's kind)
    assert items[4][0] == items[5][0] == 10 and items[4][3] == 7 and items[5][3] == 8
    assert len(items) == 6
    # boundary: H 1815 is not within 10% of 2000 (1815 * 10 = 18150 < 18000 is false? the
    # check is now * 10 >= mark * 9, and 1815 * 10 = 18150 >= 18000, so it IS kept, need 185);
    # H 2700 is over 90% of 3000 too; H 2600 is not (26000 < 27000)
    ldir2 = tmp_path / 'edge'
    write_league(ldir2, [player('EDGE', totals=tot(H=1815))], seasons=1)
    assert dynview.watch_items(load(ldir2)['hist']) == [(185, 2000, 1, 0, 1815)]
    write_league(ldir2, [player('EDGE', totals=tot(H=2600))], seasons=1)
    assert dynview.watch_items(load(ldir2)['hist']) == []


def test_watch_rows_and_message(tmp_path):
    """the rows, the SO label, the empty message row and COLS_SINGLE for it"""
    data = watch_league(tmp_path)
    assert dynview.watch_rows(data['hist']) == [
        ('KMAN, G', '3000 SO', '2995', '5'),
        ('HR298, D', '300 HR', '298', '2'),
        ('HR395, E', '400 HR', '395', '5'),
        ('HIT2950, A', '3000 H', '2950', '50'),
        ('SBTIE1, H', '500 SB', '490', '10'),
        ('SBTIE2, I', '500 SB', '490', '10')]
    assert dynview.COLS_WATCH == [
        ('NAME', dynview._cx(0), 16, 'L'), ('MARK', dynview._cx(17), 9, 'L'),
        ('NOW', dynview._cx(27), 6, 'R'), ('NEED', dynview._cx(35), 6, 'R')]
    ldir2 = tmp_path / 'nowatch'
    write_league(ldir2, [player('NONE', totals=tot(H=10))], seasons=1)
    data2 = load(ldir2)
    assert dynview.rows((MS, 0, 1), data2) == \
        [('NO ACTIVE PLAYER NEAR A MILESTONE',)]
    assert dynview.body_cols((MS, 0, 1), data2) == dynview.COLS_SINGLE


def test_watch_left_right_titles_footers_toggle(tmp_path):
    """LEFT and RIGHT toggle the mode and reset page and row; titles and both footers"""
    data = watch_league(tmp_path)
    press = lambda s, k: dynview.step(s, k, data)[0]
    s = press((MS, 2, 0), dynview.KEY_RIGHT)
    assert s == (MS, 0, 1)
    assert press(s, dynview.KEY_RIGHT) == (MS, 0, 0)
    assert press((MS, 0, 0), dynview.KEY_LEFT) == (MS, 0, 1)
    assert press((MS, 0, 1), dynview.KEY_LEFT) == (MS, 0, 0)
    assert dynview.screen_title((MS, 0, 0), data) == 'MILESTONES'
    assert dynview.screen_title((MS, 0, 1), data) == 'MILESTONE WATCH'
    assert dynview.footer_text((MS, 0, 0), data) == \
        'ENTER CARD  LEFT RIGHT WATCH  PGUP PGDN  ESC'      # C61: the cat 0 footer
    assert dynview.footer_text((MS, 0, 1), data) == \
        'ENTER CARD  LEFT RIGHT MODE  PGUP PGDN  ESC'
    assert dynview.body_cols((MS, 0, 0), data) == dynview.COLS_MILESTONES
    assert dynview.body_cols((MS, 0, 1), data) == dynview.COLS_WATCH
    # a click on the title band is LEFT or RIGHT on both modes; a click on the footer PGDNs
    assert dynview.click_to_key((MS, 0, 0), data, 100, 14) == (dynview.KEY_LEFT, None)
    assert dynview.click_to_key((MS, 0, 1), data, 200, 20) == (dynview.KEY_RIGHT, None)


def test_watch_cursor_enter_and_mode0_plain(tmp_path):
    """WATCH cursor: DOWN moves, PGDN pages, ENTER opens the card, ESC returns to the same
    WATCH state, ENTER on the message row does nothing; mode 0 is a cursor screen too
    (C61): DOWN moves, ENTER opens, PGDN moves the cursor like every cursor screen"""
    data = watch_league(tmp_path)
    press = lambda s, k: dynview.step(s, k, data)[0]
    assert dynview.cursor_screen((MS, 0, 0))                # C61: mode 0 is a cursor screen
    assert dynview.cursor_screen((MS, 0, 1))
    s = press((MS, 0, 1), dynview.KEY_DOWN)
    assert s == (MS, 0, 1, 1)
    assert dynview.row_entry(s, data) == 3                       # HR298
    s2, _ex = dynview.step(s, dynview.KEY_ENTER, data)
    assert s2 == (dynview.SCREEN_CARD, 0, 3)
    assert dynview.step(s2, dynview.KEY_ESC, data)[0] == s       # the identical WATCH state
    # the same state (MS, 0, 1) with 14 rows: cursor PGDN moves to row 12 on page 1
    ldir2 = tmp_path / 'pages'
    players = [player('FILL%02d' % k, totals=tot(SB=490 - k, H=100)) for k in range(14)]
    write_league(ldir2, players, seasons=1)
    data2 = load(ldir2)
    press2 = lambda s, k: dynview.step(s, k, data2)[0]
    s3 = press2((MS, 0, 1), dynview.KEY_PGDN)
    assert s3 == (MS, 1, 1, 12)
    assert dynview.step((MS, 0, 1, 11), dynview.KEY_ENTER, data2)[0] == \
        (dynview.SCREEN_CARD, 0, 11)
    # the message row: no entry, ENTER keeps the state
    ldir3 = tmp_path / 'msg'
    write_league(ldir3, [player('QUIET', totals=tot(H=10))], seasons=1)
    data3 = load(ldir3)
    assert dynview.row_entry((MS, 0, 1, 0), data3) is None
    assert dynview.step((MS, 0, 1), dynview.KEY_ENTER, data3) == ((MS, 0, 1), 0)
    # mode 0 (C61): DOWN moves the milestone cursor, ENTER opens the row's card,
    # PGDN moves the cursor to the new page's first row
    assert dynview.step((MS, 0, 0), dynview.KEY_DOWN, data)[0] == (MS, 0, 0)
    ldir4 = tmp_path / 'mspage'
    from test_dynview import write_mileston
    write_league(ldir4, [player('A%02d' % k) for k in range(9)], seasons=3)
    write_mileston(str(ldir4 / 'MILESTON.DAT'), [(3, k % 9, 3, 300) for k in range(14)])
    data4 = load(ldir4)
    assert dynview.step((MS, 0, 0), dynview.KEY_DOWN, data4)[0] == (MS, 0, 0, 1)
    assert dynview.step((MS, 0, 0, 1), dynview.KEY_ENTER, data4)[0] == \
        (dynview.SCREEN_CARD, 0, 1)
    assert dynview.step((MS, 1, 0), dynview.KEY_PGDN, data4)[0] == (MS, 1, 0)
    assert dynview.step((MS, 0, 0), dynview.KEY_PGDN, data4)[0] == (MS, 1, 0, 12)
# ---------------------------------------------------------------- C28 AWARD HISTORY
AH = dynview.SCREEN_AWHIST
K_HUP, K_HLOW = 72, 104


def awhist_league(tmp_path):
    """4 seasons, 8 players. AL MVP records in seasons 2, 3, 4 (season 1 instead has
    fallback winners from its season entry and no award record of any kind), an NL GLOVE C
    record (kind 98) in season 3 only, leader records (kinds 128 and up) the H key ignores.
    Negative and zero values exercise the sign and rounding."""
    players = [player(n, totals=tot(H=100 + e), war10=50 + e) for e, n in
               enumerate(['WIN1X', 'WIN2X', 'WIN3X', 'WIN4X', 'GLOVE', 'LEADR', 'FILLA',
                          'FILLB'])]
    ldir = tmp_path / 'awh'
    write_league(ldir, players, seasons=4, start=1990,
                 ms=[(2, 1, 64, 30), (2, 6, 128, 312),          # AL MVP, AL BA leader
                     (3, 2, 64, (-25) & 0xffff), (3, 4, 99, 987),   # AL MVP, NL GLOVE C
                     (3, 5, 160, 205),                          # an NL leader
                     (4, 3, 64, 0),                             # 0 WAR
                     (4, 0, 192, 5 * 256 + 3)])                 # a WS record, not an award
    # season 1's fallback winners (its entries 0..5, none NO_AWARD)
    hp = ldir / 'HISTORY.DAT'
    d = bytearray(hp.read_bytes())
    d[32 + 88:32 + 100] = bytes((0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0))
    hp.write_bytes(bytes(d))
    return load(ldir)


def test_awhist_rows_newest_first_and_fallback(tmp_path):
    data = awhist_league(tmp_path)
    hist, ms = data['hist'], data['ms']
    # a = 0 (AL MVP): records of seasons 4 (0.0 WAR), 3 (-2.5 WAR) and 2 (3.0 WAR), then
    # season 1's fallback AL MVP with an empty value
    got = dynview.award_history_items(hist, ms, 0)
    assert [r for r, _e in got] == [
        ('1993', 'WIN4X, A', '0.0 WAR'), ('1992', 'WIN3X, A', '-2.5 WAR'),
        ('1991', 'WIN2X, A', '3.0 WAR'), ('1990', 'WIN1X, A', '')]
    assert [e for _r, e in got] == [3, 2, 1, 0]         # the fallback winner keeps its
    # entry: the card of row 3 opens entry 0
    assert dynview.row_entry((AH, 0, 0, 3), data) == 0
    # the fallback value cell is empty (not a war string)
    assert got[3][0][2] == ''
    # a = 20 (NL MVP): only season 1 has no award record of any kind, so only it shows;
    # its NL MVP fallback winner is aw[3] (WIN4X), value ''
    assert dynview.award_history_items(hist, ms, 20) == [(('1990', 'WIN4X, A', ''), 3)]
    # a = 23 (NL GLOVE C, kind 99): season 3 only, value '.987 FLD'
    assert dynview.award_history_items(hist, ms, 23) == \
        [(('1992', 'GLOVE, A', '.987 FLD'), 4)]
    # a = 3 (AL GLOVE C, kind 67): no record of the kind anywhere and k > 2: no row
    assert dynview.award_history_items(hist, ms, 3) == \
        [(('NO WINNERS RECORDED',), None)]
    # a value past the entry table is not a card row (the out-of-range name is '?')
    ldir = tmp_path / 'oob'
    write_league(ldir, [player('ONLY', first='A')], seasons=2,
                 ms=[(2, 9, 64, 10)])
    data2 = load(ldir)
    assert dynview.award_history_items(data2['hist'], data2['ms'], 0) == \
        [(('1994', '?', '1.0 WAR'), None), (('1993', 'ONLY, A', ''), 0)]
    assert dynview.row_entry((AH, 0, 0, 0), data2) is None


def test_awhist_message_row_and_columns(tmp_path):
    data = awhist_league(tmp_path)
    # an award never given (no record of the kind in any season, and the fallback rule
    # does not apply to k > 2): one message row with COLS_SINGLE
    assert dynview.award_history_rows(data['hist'], data['ms'], 39) == \
        [('NO WINNERS RECORDED',)]
    rows, cols = dynview.awhist_body((AH, 0, 39), data)[1], dynview.awhist_body((AH, 0, 39),
                                                                                data)[0]
    assert rows == [('NO WINNERS RECORDED',)] and cols == dynview.COLS_SINGLE
    assert dynview.total_rows((AH, 0, 39), data) == 1
    # an award with rows: COLS_AWHIST, and no history gives no rows
    assert dynview.awhist_body((AH, 0, 0), data) == \
        (dynview.COLS_AWHIST, [('1993', 'WIN4X, A', '0.0 WAR'),
                               ('1992', 'WIN3X, A', '-2.5 WAR'),
                               ('1991', 'WIN2X, A', '3.0 WAR'),
                               ('1990', 'WIN1X, A', '')])
    ldir = tmp_path / 'nohist'
    ldir.mkdir()
    data3 = load(ldir)
    assert dynview.awhist_body((AH, 0, 0), data3) == (dynview.COLS_SINGLE, [])
    assert dynview.rows((AH, 0, 0), data3) == [('NO DYNASTY HISTORY YET',)]
    assert dynview.COLS_AWHIST == [
        ('YEAR', dynview._cx(0), 4, 'L'), ('NAME', dynview._cx(5), 16, 'L'),
        ('VALUE', dynview._cx(22), 20, 'R')]


def test_awhist_left_right_wrap_cursor_and_paging(tmp_path):
    data = awhist_league(tmp_path)
    # LEFT wraps from code 0 to 39 (page and row reset); RIGHT from 38 to 39
    s = (AH, 2, 39, 25)
    assert press(s, LEFT, data) == (AH, 0, 38)
    assert press((AH, 0, 38), RIGHT, data) == (AH, 0, 39)
    assert press((AH, 0, 20), RIGHT, data) == (AH, 0, 21)
    # the cursor moves like on HALL OF FAME: DOWN caps at the last row (4), PGDN pages
    # only when there is a next page (the 4 rows here fit one, so it stays)
    s = press((AH, 0, 0), DOWN, data)
    assert s == (AH, 0, 0, 1)
    for _ in range(4):
        s = press(s, DOWN, data)
    assert s == (AH, 0, 0, 3)                        # the last row of 4
    assert press(s, PGDN, data) == s                 # no page 2
    assert dynview.screen_title((AH, 0, 0), data) == 'AL MVP HISTORY'
    assert dynview.screen_title((AH, 0, 18), data) == 'AL SLUGGER RF HISTORY'
    assert dynview.screen_title((AH, 0, 20), data) == 'NL MVP HISTORY'
    assert dynview.screen_title((AH, 0, 23), data) == 'NL GLOVE C HISTORY'
    assert dynview.screen_title((AH, 0, 39), data) == 'NL SLUGGER DH HISTORY'
    assert dynview.footer_text((AH, 0, 0), data) == \
        'ENTER CARD  LEFT RIGHT AWARD  PGUP PGDN  ESC'


def test_awhist_open_from_awards_and_esc_back(tmp_path):
    data = awhist_league(tmp_path)
    # SEASON AWARDS of season 4: award records (AL MVP), then the leader record; the
    # kind 192 WS record does not show
    awards_now = dynview.awards_items(data['hist'], data['ms'], 4)
    assert awards_now == [(('AL MVP', 'WIN4X, A', '0.0 WAR'), 3)]
    # H (both cases) on the award record row opens that award's history and keeps the
    # awards state in data['awh_back']; ESC returns it exactly
    for h in (K_HUP, K_HLOW):
        sa = (SA, 0, 0, 0)
        s2, _ex = dynview.step(sa, h, data)
        assert s2 == (AH, 0, 0), h
        assert data['awh_back'] == (SA, 0, 0)          # pack drops the 0 row and page
        assert dynview.unpack(press(s2, ESC, data)) == dynview.unpack(sa)
    # H on a leader record row keeps code 0
    s2 = press((SA, 0, 0), DOWN, data)
    assert press(s2, K_HUP, data) == (AH, 0, 0)
    # H on a fallback row (season 1 has no award records) and on the message row: code 0
    for cat in (2, 5):
        assert press((SA, 0, cat), K_HLOW, data) == (AH, 0, 0)
    # the state after ESC is exactly what H saw, cursor included
    sa = (SA, 1, 2, 13)
    s2, _ex = dynview.step(sa, K_HUP, data)
    assert data['awh_back'] == sa and press(s2, ESC, data) == sa
    # ESC on a code reached without an H (nothing kept this session): the default
    # (9, 0, 0); here data['awh_back'] still holds the H from above, so a fresh data dict
    data3 = load((tmp_path / 'awh'))
    assert press((AH, 2, 7, 9), ESC, data3) == (SA, 0, 0)
    # ENTER on the history row opens the card, ESC goes back to the identical state twice:
    # card -> history, then history -> awards with the backed-up state
    sa = (SA, 0, 0, 0)
    data2 = load((tmp_path / 'awh'))                          # a fresh data dict
    ah, _ex = dynview.step(sa, K_HUP, data2)
    card, _ex2 = dynview.step(ah, ENTER, data2)
    assert card == (CARD, 0, 3)
    assert press(card, ESC, data2) == ah
    assert dynview.unpack(press(ah, ESC, data2)) == dynview.unpack(sa)


# ---------------------------------------------------------------- C53 HOF position filters
def hof53_league(tmp_path):
    """Five HoF entries (PITCHA P, CATCHR C, SSMAN SS, LFMAN LF and CFMAN CF) among
    actives; start 1990 so the IND years read 1990 season + n - 1."""
    players = [
        player('PITCHA', first='A', status=3, hof=2, pitcher=1, pos1=0,
               totals=tot(W=300, OUTS=3704, ER=900, PSO=2995), war10=500),
        player('CATCHR', first='C', status=3, hof=3, pitcher=0, pos1=1,
               totals=tot(H=2000, AB=6000, HR=150), war10=400),
        player('SSMAN', first='S', status=3, hof=3, pitcher=0, pos1=5,
               totals=tot(H=2500, AB=8000, HR=80), war10=450),
        player('LFMAN', first='L', status=3, hof=3, pitcher=0, pos1=6,
               totals=tot(H=2300, AB=7800, HR=300), war10=430),
        player('CFMAN', first='C', status=3, hof=2, pitcher=0, pos1=7,
               totals=tot(H=2100, AB=7400, HR=250), war10=410),
        player('DHIGN', first='D', status=1, pitcher=0, pos1=9, totals=tot(H=30, AB=100)),
        player('ACT', first='X', totals=tot(H=100, AB=300)),
    ]
    ldir = tmp_path / 'hof53'
    write_league(ldir, players, seasons=4, start=1990,
                 lines=[line(1, 3, totals=tot(G=40, AB=100, H=30))])
    return load(ldir)


def test_hof53_filters_and_titles():
    data = hof53_league(Path(tempfile.mkdtemp()))
    for f in range(9):
        s = (HOF, 0, f)
        assert dynview.screen_title(s, data) == \
            ('HALL OF FAME' if f == 0 else 'HALL OF FAME: ' + dynview.HOF_FILTERS[f][0])
        assert dynview.footer_text(s, data) == 'TAB POSITION   PGUP PGDN   ESC MENU'
    # every hof_order / hof_rows caller sees the state's cat: row_entry filters too
    def lastof(e):
        return dynview.one_field(e['name'][0:12])
    names = {f: [lastof(e) for _i, e in dynview.hof_order(data['hist'], f)]
             for f in range(9)}
    assert names[0] == ['CATCHR', 'SSMAN', 'LFMAN', 'PITCHA', 'CFMAN']
    assert names[0] == [r[0].split(',')[0] for r in dynview.hof_rows(data['hist'], 0)]
    assert names[1] == ['PITCHA']
    assert names[2] == ['CATCHR']
    assert names[6] == ['SSMAN']
    assert names[7] == ['LFMAN', 'CFMAN']           # OF covers LF and CF
    for f in (3, 4, 5, 8):
        assert names[f] == []
    # IND keeps (season desc, index asc): season 3 members by index, then season 2
    assert dynview.rows((HOF, 0, 0), data)[0][1] == '1992'
    assert dynview.rows((HOF, 0, 7), data) == \
        [('LFMAN, L', '1992', '3', '2300', '300', '.294', '43.0'),
         ('CFMAN, C', '1991', '3', '2100', '250', '.283', '41.0')]


def test_hof53_tab_state_and_enter_esc():
    data = hof53_league(Path(tempfile.mkdtemp()))
    s = press((HOF, 1, 0, 3), TAB, data)
    assert s == (HOF, 0, 1)                          # page and cursor reset, f 1
    for f in range(2, 9):
        s = press(s, TAB, data)
    assert s == (HOF, 0, 8)
    assert press(s, TAB, data) == (HOF, 0, 0)        # the wrap
    # ENTER on the SS list opens SSMAN (the only one), ESC comes back to the same state
    s, _ex = dynview.step((HOF, 0, 6), ENTER, data)
    assert s == (CARD, 0, 2)
    assert press(s, ESC, data) == (HOF, 0, 6)
    # an empty filter: ENTER does nothing, the cursor names no entry
    assert press((HOF, 0, 8), ENTER, data) == (HOF, 0, 8)
    assert dynview.row_entry((HOF, 0, 8, 0), data) is None


def test_hof53_empty_message_and_full_table():
    data = hof53_league(Path(tempfile.mkdtemp()))
    # the DH filter has no member while history exists: one COLS_SINGLE message row
    assert dynview.rows((HOF, 0, 8), data) == [('NO HALL OF FAMERS AT DH',)]
    assert dynview.body_cols((HOF, 0, 8), data) == dynview.COLS_SINGLE
    assert dynview.total_rows((HOF, 0, 8), data) == 1
    # cat 0 keeps the table (COLS_HOF) even when the ALL list has members
    assert dynview.body_cols((HOF, 0, 0), data) == dynview.COLS_HOF
    # a league with no HoF member at all: cat 0 stays the empty table
    ldir = Path(tempfile.mkdtemp()) / 'nohof'
    write_league(ldir, [player('ACT', totals=tot(H=1, AB=4))], seasons=2)
    data2 = load(ldir)
    assert dynview.rows((HOF, 0, 0), data2) == []
    assert dynview.body_cols((HOF, 0, 0), data2) == dynview.COLS_HOF
    assert dynview.rows((HOF, 0, 2), data2) == [('NO HALL OF FAMERS AT C',)]
# ---------------------------------------------------------------- C54 LEADERS active-only
def test_c54_active_filter_and_frames_model(tmp_path):
    """A on CAREER flips the flag, resets page and row and re-ranks; the title, the footers
    and the empty-active row; A on the other LEADERS modes is a no-op (C54)."""
    ldir = tmp_path / 'c54'
    players = [player('ALPHA', totals=tot(H=3000, AB=9000)),
               player('BRAVO', totals=tot(H=2000, AB=2999)),    # AVG: AB under the line
               player('CHARLIE', totals=tot(H=2000, AB=3000)),
               player('DELTA', status=2, totals=tot(H=2000, AB=3000)),
               player('ECHO', status=3, totals=tot(H=2000, AB=3000)),
               player('FOXTROT', status=2, totals=tot(H=100))]
    write_league(ldir, players, seasons=3)
    data = load(ldir)
    assert data['lead_active'] is False
    s = press((LEAD, 1, cidx('H'), 21), ord('A'), data)          # A: flip, page and row reset
    assert s == (LEAD, 0, cidx('H')) and data['lead_active'] is True
    assert [i for _v, i, _e in dynview.career_order(data['hist'], cidx('H'), True)] == \
        [0, 1, 2]                    # DELTA and ECHO are out: H 2000 tie by entry index
    rows = dynview.rows(s, data)
    assert rows == [('#1', 'ALPHA, A', ' ', '3', '3000'),
                    ('#2', 'BRAVO, A', ' ', '3', '2000'),
                    ('#3', 'CHARLIE, A', ' ', '3', '2000')]
    assert [r[0] for r in rows] == ['#1', '#2', '#3']            # ranks recount
    assert dynview.screen_title(s, data) == 'ACTIVE LEADERS: H'
    assert dynview.footer_text(s, data) == \
        'LEFT RIGHT  TAB MODE  A ACTIVE  ENTER CARD'
    assert dynview.career_leader_cells(data['hist'], cidx('H'), True) == rows
    s = press(s, ord('a'), data)                                 # a back off, same reset
    assert s == (LEAD, 0, cidx('H')) and data['lead_active'] is False
    assert dynview.screen_title(s, data) == 'CAREER LEADERS: H'
    # other modes: no-op with the flag untouched
    for before in ((LEAD, 1, SEASON + sidx('H'), 9), (LEAD, 1, BY_YEAR + sidx('H'), 9, 2),
                   (LEAD, 1, 3 * 32, 9)):
        assert press(before, 65, data) == before
        assert press(before, 97, data) == before
    assert data['lead_active'] is False
    # TAB round trip and the filter again (the state tuple never holds the flag)
    s = press((LEAD, 0, cidx('SV')), ord('A'), data)
    assert data['lead_active'] is True
    for _n in range(4):
        s = press(s, TAB, data)                                  # SEASON, BY YEAR, POST, CAREER:
    assert s == (LEAD, 0, cidx('H'))    # SV falls back to the first category (no SEASON SV)
    assert data['lead_active'] is True
    assert dynview.screen_title((LEAD, 0, cidx('H')), data) == 'ACTIVE LEADERS: H'
    # the cursor entry opens the filtered order's entry card, ESC back
    entry = dynview.row_entry((LEAD, 0, cidx('H')), data)
    assert entry == 0
    card = press((LEAD, 0, cidx('H')), ENTER, data)
    assert card == (CARD, 0, 0) and data['lead_active'] is True
    assert press(card, ESC, data) == (LEAD, 0, cidx('H'))


def test_c54_no_active_qualifiers(tmp_path):
    """All entries non-active: one message row with COLS_SINGLE; left unfiltered the list
    shows the retired marks."""
    ldir = tmp_path / 'c54none'
    players = [player('ALPHA', status=2, totals=tot(H=3000, AB=9000)),
               player('BRAVO', status=3, totals=tot(H=2000, AB=3000))]
    write_league(ldir, players, seasons=3)
    data = load(ldir)
    data['lead_active'] = True
    assert dynview.leaders_body((LEAD, 0, 0), data) == \
        (dynview.COLS_SINGLE, [('NO ACTIVE QUALIFIERS.',)])
    assert dynview.total_rows((LEAD, 0, 0), data) == 1
    assert dynview.career_leader_cells(data['hist'], 0)[0][2] == 'R'
    # categories other than H: WAR has no qualifier, but the filter empties it too
    assert dynview.leaders_body((LEAD, 0, cidx('WAR')), data) == \
        (dynview.COLS_SINGLE, [('NO ACTIVE QUALIFIERS.',)])

# ---------------------------------------------------------------- C58 (the DOS frames are in test_dynview_c13_c.py)
def test_c58_hof_browse_esc_state(tmp_path):
    """HOF card of row 1, RIGHT to row 2, ESC lands on HOF with the cursor on row 2"""
    players = player_set()
    for i, hof in ((0, 2), (1, 3), (2, 3)):
        players[i].update(status=3, hof=hof)
    ldir = tmp_path / 'c58hof'
    write_league(ldir, players, seasons=3, start=1990)
    data = load(ldir)
    s = (dynview.SCREEN_MENU, 0, 0)
    for k in (ord('2'), DOWN, ENTER, RIGHT, ESC):
        s, _ex = dynview.step(s, k, data)
    assert s == (dynview.SCREEN_HOF, 0, 0, 2)
    assert dynview.footer_text((dynview.SCREEN_CARD, 0, 0), data) == \
        'LEFT RIGHT  PGUP PGDN  H HONORS  ESC'
    assert dynview.footer_text((dynview.SCREEN_CARD, 0, 0, 1), data) == \
        'LEFT RIGHT  PGUP PGDN  H SEASONS  ESC'
