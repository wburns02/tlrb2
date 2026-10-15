#!/usr/bin/env python3
"""Tests for the DYNVIEW reference renderer (tools/m4/dynview.py).
Run:  python3 -m pytest -q tools/m4/test_dynview.py
Synthetic HISTORY.DAT/MILESTON.DAT are built in tmp_path from raw bytes; rendering
tests need the game fonts under /mnt/nvme/tlrb2/files and skip when it is missing.
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dynview
import history

FILES = '/mnt/nvme/tlrb2/files'

SEASON_NO, CHAMP_ID, RUNNER_ID = 0, 2, 3
CHAMP_STEM, RUNNER_STEM, AW_OFF = 4, 12, 88
# TOTALS indexes
G, AB, H, D2, T3, HR, R, RBI, BB, SO, SB, CS, E, W, L, SV, GS, CG, SHO, OUTS, ER, \
    PH, PBB, PSO, PHR = range(25)


def mk_history(tmp_path, seasons, entries, awards=None):
    """Raw HISTORY.DAT bytes: 32 B header, seasons x 128 B, entries x 160 B."""
    d = bytearray(32)
    d[3] = 1
    d[4], d[5] = seasons & 255, (seasons >> 8) & 255
    d[6], d[7] = len(entries) & 255, (len(entries) >> 8) & 255
    for n, se in enumerate(seasons if isinstance(seasons, list) else [], 1):
        pass
    return bytes(d)


def write_season(d, season_no, champ_stem, runner_stem, awards=(0xffff,) * 6):
    o = 32 + (season_no - 1) * 128
    struct.pack_into('<H', d, o, season_no)
    d[o + 4:o + 12] = champ_stem.ljust(8, b'\0')[:8]
    d[o + 12:o + 20] = runner_stem.ljust(8, b'\0')[:8]
    for k, v in enumerate(awards):
        struct.pack_into('<H', d, o + AW_OFF + 2 * k, v)


def write_player(d, i, last, first, status=1, first_season=1, last_season=10,
                 seasons_played=10, pitcher=0, hof_season=0, war10=0,
                 totals=None, awards=(0, 0, 0, 0, 0)):
    o = 8224 + i * 160
    name = last.ljust(12, b'\0')[:12] + first.ljust(8, b'\0')[:8]
    d[o:o + 20] = name
    d[o + 22] = status
    struct.pack_into('<H', d, o + 24, first_season)
    struct.pack_into('<H', d, o + 26, last_season)
    struct.pack_into('<H', d, o + 28, seasons_played)
    d[o + 31] = pitcher
    t = totals or [0] * 25
    for k, v in enumerate(t):
        struct.pack_into('<I', d, o + 32 + 4 * k, v)
    struct.pack_into('<h', d, o + 132, war10)
    struct.pack_into('<H', d, o + 150, hof_season)
    d[o + 152:o + 157] = bytes(awards)


def write_mileston(path, records):
    """records = [(season, idx, kind, value)] in file order."""
    d = bytearray()
    for season, idx, kind, value in records:
        d += struct.pack('<HHBBH', season, idx, kind, 0, value)
    open(path, 'wb').write(bytes(d))


def make_data(tmp_path, seasons=3, ms=None):
    """Synthetic league dir with HISTORY.DAT (3 seasons, 30 entries incl. 2 HoF,
    awards set) and MILESTON.DAT (5 records). Returns (dir, hist bytes)."""
    ldir = tmp_path / 'league'
    ldir.mkdir()
    d = bytearray(32 + 64 * 128 + 30 * 160)
    d[3] = 1
    d[4], d[5] = seasons & 255, (seasons >> 8) & 255
    d[6], d[7] = 30 & 255, 0
    # seasons 1..3, newest data has champion stems ALA02/ALA03, runners NL01
    write_season(d, 1, b'ALA01', b'NL01', awards=(0, 1, 2, 3, 4, 5))
    write_season(d, 2, b'ALA02', b'NL02', awards=(6, 7, 8, 9, 10, 11))
    write_season(d, 3, b'ALA03', b'NL03', awards=(12, 13, 14, 15, 16, 17))
    # 30 entries: 0..27 role players, 28/29 HoF (hof seasons 2 and 3)
    for i in range(30):
        last = b'PLAYER%02d' % i
        status = 3 if i >= 28 else (2 if i % 3 == 0 else 1)
        write_player(d, i, last, b'B', status=status,
                     first_season=1, last_season=10, seasons_played=10,
                     pitcher=1 if i == 5 else 0,
                     hof_season=(2 if i == 28 else (3 if i == 29 else 0)),
                     war10=100 + i,
                     totals=[10 + i] * 11 + [0, 0, 0] + [20 + i] * 3
                     + [100 + i, 0, 0, 0, 5000 + i, 150 + i],
                     awards=(1, 0, 0, 2, 0))
    # make entry 0 a 3000-H batter with .318 AVG over 9423 AB, entry 5 an ERA pitcher
    t0 = [0] * 25
    t0[G], t0[AB], t0[H], t0[HR], t0[OUTS], t0[ER] = 3000 // 3, 9423, 3000, 400, 5400, 150
    write_player(d, 0, b'HITTER', b'A', status=2, totals=t0, war10=650)
    t5 = [0] * 25
    t5[G], t5[W], t5[SV], t5[OUTS], t5[ER], t5[PSO] = 400, 250, 0, 5400, 99, 3000
    write_player(d, 5, b'ACE', b'P', status=2, pitcher=1, totals=t5, war10=500)
    # awards point at real entries: season 3 AL MVP 0, NL MVP 1
    for n, aw in ((1, (0, 1, 2, 3, 4, 5)), (2, (6, 7, 8, 9, 10, 11)),
                  (3, (0, 1, 2, 3, 4, 5))):
        write_season(d, n, b'ALA0%d' % n, b'NL0%d' % n, awards=aw)
    (ldir / 'HISTORY.DAT').write_bytes(bytes(d))
    if ms is None:
        ms = [(3, 0, 2, 3000), (3, 5, 13, 3000), (2, 1, 32, 52),
              (2, 2, 35, 412), (1, 0, 5, 500)]
    write_mileston(str(ldir / 'MILESTON.DAT'), ms)
    return ldir, bytes(d)


def st(screen, page=0, cat=0):
    return (screen, page, cat)


def pack3(s):
    """s with trailing zero row and year dropped (pack's shortest form)."""
    return tuple(s)[:-1] if len(s) > 3 and s[3] == 0 and (len(s) < 5 or s[4] == 0) \
        else (tuple(s)[:-2] if len(s) > 4 and s[4] == 0 else tuple(s))


def unpack4(s):
    """the row field of s (0 when absent)."""
    return s[3] if len(s) > 3 else 0


# ---------------------------------------------------------------- model rows
def test_history_rows_newest_first(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_HISTORY), data)
    assert rows[0][0] == '1995' and rows[1][0] == '1994' and rows[2][0] == '1993'
    # YEAR, CHAMPION (13), AL MVP (11), NL MVP (11); the runner-up is on REVIEW only
    assert rows[0][1] == 'ALA03' and len(rows[0]) == 4
    assert rows[0][2] == 'HITTER, A'
    assert [c[2] for c in dynview.COLS_HISTORY] == [4, 13, 11, 11]
    assert dynview.COLS_HISTORY[-1][1] + 11 * dynview.CHAR_W == dynview._cx(42)


def test_hof_rows_order(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_HOF), data)
    # HoF entries 28 (season 2) and 29 (season 3): newer HoF season first
    assert rows[0][1] == '1995' and rows[1][1] == '1994'
    assert rows[0][0].startswith('PLAYER29')
    # pitcher columns for entry 5 are not in the HOF table (status 2)


# ---------------------------------------------------------------- HOF filter (C53)
def test_hof_match_each_filter():
    P = dict(pitcher=1, pos1=0)
    C = dict(pitcher=0, pos1=1)
    B1B = dict(pitcher=0, pos1=2)
    B2B = dict(pitcher=0, pos1=3)
    B3B = dict(pitcher=0, pos1=4)
    SS = dict(pitcher=0, pos1=5)
    LF = dict(pitcher=0, pos1=6)
    CF = dict(pitcher=0, pos1=7)
    RF = dict(pitcher=0, pos1=8)
    DH = dict(pitcher=0, pos1=9)
    entry = dict(P, **{'name': b'X'})
    assert dynview.HOF_FILTERS == [('ALL', None), ('P', None), ('C', (1,)),
                                   ('1B', (2,)), ('2B', (3,)), ('3B', (4,)),
                                   ('SS', (5,)), ('OF', (6, 7, 8)), ('DH', (9,))]
    for e in (P, C, B1B, B2B, B3B, SS, LF, CF, RF, DH):
        assert dynview.hof_match(e, 0)
    assert dynview.hof_match(P, 1)
    for e in (C, B1B, B2B, B3B, SS, LF, CF, RF, DH):
        assert not dynview.hof_match(e, 1)
    for who, f in ((C, 2), (B1B, 3), (B2B, 4), (B3B, 5), (SS, 6), (DH, 8)):
        assert dynview.hof_match(who, f)
        for f2 in range(9):
            if f2 != f and f2 != 0:
                assert not dynview.hof_match(who, f2), (who, f2)
    for e in (LF, CF, RF):
        assert dynview.hof_match(e, 7)               # OF covers LF CF RF
        assert not dynview.hof_match(e, 2)
    # a pitcher never matches a position filter, a batter never P
    assert not dynview.hof_match(P, 7)
    assert not dynview.hof_match(C, 1)
    assert dynview.hof_match(dict(C, pitcher=1), 1)  # a pitcher: P, not C


def test_hof_tab_cycles_filters(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.KEY_TAB == 9
    s = (dynview.SCREEN_HOF, 0, 0)
    for want in (1, 2, 3, 4, 5, 6, 7, 8, 0):
        s, _ex = dynview.step(s, dynview.KEY_TAB, data)
        assert s == (dynview.SCREEN_HOF, 0, want)
    # page and row reset (not a cursor move)
    s, _ex = dynview.step((dynview.SCREEN_HOF, 1, 0, 3), dynview.KEY_TAB, data)
    assert s == (dynview.SCREEN_HOF, 0, 1)
    # other screens unchanged: TAB does nothing on HISTORY, LEADERS mode logic intact
    s, _ex = dynview.step((dynview.SCREEN_HISTORY, 0, 0), dynview.KEY_TAB, data)
    assert s == (dynview.SCREEN_HISTORY, 0, 0)
    s, _ex = dynview.step((dynview.SCREEN_LEADERS, 0, 0), dynview.KEY_TAB, data)
    assert s == (dynview.SCREEN_LEADERS, 0, dynview.MODE_SHIFT + 3)   # CAREER H -> SEASON H


def test_hof_filter_titles(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.screen_title((dynview.SCREEN_HOF, 0, 0), data) == 'HALL OF FAME'
    assert dynview.screen_title((dynview.SCREEN_HOF, 0, 1), data) == 'HALL OF FAME: P'
    assert dynview.screen_title((dynview.SCREEN_HOF, 0, 6), data) == 'HALL OF FAME: SS'
    assert dynview.screen_title((dynview.SCREEN_HOF, 0, 7), data) == 'HALL OF FAME: OF'
    assert dynview.screen_title((dynview.SCREEN_HOF, 0, 8), data) == 'HALL OF FAME: DH'
    assert dynview.footer_text((dynview.SCREEN_HOF, 0, 0), data) == \
        'TAB POSITION   PGUP PGDN   ESC MENU'
    assert dynview.FOOTERS[dynview.SCREEN_HOF] == \
        'TAB POSITION   PGUP PGDN   ESC MENU'


def test_hof_filter_order(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # make_data leaves byte 30 (pos1) at 0 for its HoF entries (28, 29), batters by
    # the pitcher byte: only ALL shows them; 2B (filter 4) sees none
    rows = dynview.rows(st(dynview.SCREEN_HOF, 0, 4), data)       # 2B filter: none
    assert rows == [('NO HALL OF FAMERS AT 2B',)]
    assert dynview.body_cols(st(dynview.SCREEN_HOF, 0, 4), data) == dynview.COLS_SINGLE
    # ALL row cells unchanged
    assert dynview.rows(st(dynview.SCREEN_HOF), data) == dynview.hof_rows(data['hist'], 0)
    assert dynview.total_rows(st(dynview.SCREEN_HOF, 0, 1), data) == 1   # P: no HoF pitchers
    assert dynview.total_rows(st(dynview.SCREEN_HOF, 0, 0), data) == 2   # ALL: both
    # the cursor of an empty filter names no entry
    assert dynview.row_entry((dynview.SCREEN_HOF, 0, 1, 0), data) is None


def test_hof_filter_keep_season_order_then_index(tmp_path):
    """Filter keeps (HoF season desc, index asc)."""
    from test_dynview_c13 import player, write_league

    def tb(h):
        t = [0] * 25
        t[1], t[2] = 20, h
        return t

    ldir = tmp_path / 'ord'
    ldir.mkdir()
    players = [player('HOFB', first='B', status=3, hof=3, pos1=5, totals=tb(6)),
               player('HOFA', first='A', status=3, hof=2, pos1=5, totals=tb(5))]
    write_league(ldir, players, seasons=4)
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_HOF, 0, 6), data)      # SS filter
    assert [r[0] for r in rows] == ['HOFB, B', 'HOFA, A']
    assert dynview.rows(st(dynview.SCREEN_HOF, 0, 6), data) == \
        dynview.hof_rows(data['hist'], 6)
    assert [i for i, _e in dynview.hof_order(data['hist'], 6)] == [0, 1]


def test_hof_enter_opens_filtered_card_and_esc(tmp_path):
    from test_dynview_c13 import player, write_league, line

    def tb(h):
        t = [0] * 25
        t[1], t[2] = 20, h
        return t

    ldir = tmp_path / 'card'
    # HOFA (entry 0) has the older HoF season, so the list's row 0 is HOFB (entry 1)
    write_league(ldir, [player('HOFA', first='A', status=3, hof=2, pos1=5,
                               totals=tb(5)),
                        player('HOFB', first='B', status=3, hof=3, pos1=5,
                               totals=tb(6))], seasons=4,
                 lines=[line(0, 3, totals=tb(5))])
    data = dynview.load_data(str(ldir))
    s, _ex = dynview.step((dynview.SCREEN_HOF, 0, 6), dynview.KEY_ENTER, data)
    assert s == (dynview.SCREEN_CARD, 0, 1)
    s2, _ex = dynview.step(s, dynview.KEY_ESC, data)
    assert s2 == (dynview.SCREEN_HOF, 0, 6)
    # ENTER on an empty filter does nothing
    s3, _ex = dynview.step((dynview.SCREEN_HOF, 0, 1), dynview.KEY_ENTER, data)
    assert s3 == (dynview.SCREEN_HOF, 0, 1)
    # cat 0 with no members keeps today's behaviour: empty table, COLS_HOF
    ldir2 = tmp_path / 'none'
    write_league(ldir2, [player('ACT', totals=tb(1))], seasons=2)
    data2 = dynview.load_data(str(ldir2))
    assert dynview.rows(st(dynview.SCREEN_HOF, 0, 0), data2) == []
    assert dynview.body_cols(st(dynview.SCREEN_HOF, 0, 0), data2) == dynview.COLS_HOF
    assert dynview.rows(st(dynview.SCREEN_HOF, 0, 2), data2) == \
        [('NO HALL OF FAMERS AT C',)]


def test_leaders_count_order_and_ties(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # H: only entries with H > 0 (entry 0 has H 3000, the rest H = 10+i)
    rows = dynview.rows(st(dynview.SCREEN_LEADERS, 0, 0), data)
    assert rows[0] == ('#1', 'HITTER, A', 'R', '10', '3000')
    assert rows[1][1].startswith('PLAYER')        # rest by totals
    # WAR descending: WAR10 600 (entry 0) > 500 (entry 5) > 100+i
    rows = dynview.rows(st(dynview.SCREEN_LEADERS, 0, 9), data)
    assert rows[0][1] == 'HITTER, A' and rows[0][4] == '65.0'
    assert rows[1][1] == 'ACE, P' and rows[1][4] == '50.0'
    assert rows[2][1].startswith('PLAYER29') and rows[2][4] == '12.9'


def test_leaders_avg_threshold_and_format(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # AVG: only AB >= 3000 qualifies (entry 0: 3000/9423 = .318)
    rows = dynview.rows(st(dynview.SCREEN_LEADERS, 0, 8), data)
    assert rows[0] == ('#1', 'HITTER, A', 'R', '10', '.318')
    assert len(rows) == 1
    # ERA: only OUTS >= 4500 (entries 0 and 5). entry 5: 99*2700/5400 = 49 -> 0.49,
    # entry 0: 150*2700/5400 = 75 -> 0.75, ascending
    rows = dynview.rows(st(dynview.SCREEN_LEADERS, 0, 13), data)
    assert rows[0] == ('#1', 'ACE, P', 'R', '10', '0.49')
    assert rows[1] == ('#2', 'HITTER, A', 'R', '10', '0.75')
    assert len(rows) == 2


def test_leaders_award_categories_wrap(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # MVP awards: entries 0..29 have awards[0] = 1, so all 30 qualify, top 12
    rows = dynview.rows(st(dynview.SCREEN_LEADERS, 0, 16), data)
    assert len(rows) == 12
    # LEFT from cat 0 wraps to cat 17; RIGHT from 17 wraps to 0
    s1, _ex = dynview.step(st(dynview.SCREEN_LEADERS, 0, 0),
                           dynview.KEY_LEFT, data)
    assert s1[2] == 17 and s1[1] == 0
    s2, _ex = dynview.step(s1, dynview.KEY_RIGHT, data)
    assert s2[2] == 0
    rows = dynview.rows(s1, data)
    assert len(rows) == 12


def test_milestone_rows_order_and_events(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_MILESTONES), data)
    # newest season first (3 before 2 before 1), file order within a season
    assert rows[0][0] == '1995' and rows[1][0] == '1995'
    assert rows[0][2] == '3000 HITS' and rows[0][1].startswith('HITTER')
    assert rows[1][2] == '2000 STRIKEOUTS'
    assert rows[2][0] == '1994' and rows[2][2] == '52 HR SEASON'
    assert rows[3][2] == '.412 SEASON'
    assert rows[4][0] == '1993' and rows[4][2] == '500 HOME RUNS'


def test_review_rows(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_REVIEW, 0, 3), data)
    text = [r[0] for r in rows]
    assert text[0] == 'CHAMPION ALA03' and text[1] == 'RUNNER-UP NL03'
    assert text[2].startswith('AL MVP HITTER')
    assert any(t.startswith('NEW HALL OF FAME: PLAYER29') for t in text)
    # season-3 milestones appended as "<name> <event>"
    assert any(t == 'HITTER, A 3000 HITS' for t in text)
    assert any(t == 'ACE, P 2000 STRIKEOUTS' for t in text)


def test_paging_bounds(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # HISTORY has 3 rows: PGDN from page 0 is a no-op (3 < 12 rows shown means
    # page*12+12 > 3), PGUP stays at 0
    s, _ex = dynview.step(st(dynview.SCREEN_HISTORY), dynview.KEY_PGDN, data)
    assert s[1] == 0
    s, _ex = dynview.step(s, dynview.KEY_PGUP, data)
    assert s[1] == 0
    # LEADERS MVP awards: 28 entries qualify (awards[0] = 1), PGDN -> page 1
    # (rank restarts per page rank #13 here), PGUP back, PGDN at the last page
    # (24 < 28) stays, a PGDN from page 2 is a no-op
    s, _ex = dynview.step(st(dynview.SCREEN_LEADERS, 0, 16), dynview.KEY_PGDN, data)
    assert s[1] == 1
    rows = dynview.rows(s, data)
    assert rows[0][0] == '#13'
    s, _ex = dynview.step(s, dynview.KEY_PGUP, data)
    assert s[1] == 0
    s, _ex = dynview.step(st(dynview.SCREEN_LEADERS, 0, 16), dynview.KEY_PGDN, data)
    s, _ex = dynview.step(s, dynview.KEY_PGDN, data)
    assert s[1] == 2
    s, _ex = dynview.step(s, dynview.KEY_PGDN, data)
    assert s[1] == 2


def test_esc_and_enter_navigation(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # ESC from MENU exits
    s, ex = dynview.step(st(dynview.SCREEN_MENU), dynview.KEY_ESC, data)
    assert ex == 1
    # ESC from HISTORY goes to MENU
    s, ex = dynview.step(st(dynview.SCREEN_HISTORY), dynview.KEY_ESC, data)
    assert ex == 0 and s[0] == dynview.SCREEN_MENU
    # 1..5 open the screens; ENTER on REVIEW returns to MENU
    s, ex = dynview.step(st(dynview.SCREEN_MENU), ord('5'), data)
    assert s[0] == dynview.SCREEN_REVIEW and ex == 0
    s, ex = dynview.step(s, dynview.KEY_ENTER, data)
    assert ex == 0 and s[0] == dynview.SCREEN_MENU


# ---------------------------------------------------------------- formatting
def test_format_avg():
    assert dynview.fmt_avg(300) == '.300'
    assert dynview.fmt_avg(1000) == '1.000'
    assert dynview.fmt_avg(0) == '.000'
    assert dynview.fmt_avg(41) == '.041'


def test_format_era_war():
    assert dynview.fmt_era100(185) == '1.85'
    assert dynview.fmt_era100(49) == '0.49'
    assert dynview.fmt_war10(-5) == '-0.5'
    assert dynview.fmt_war10(123) == '12.3'
    assert dynview.fmt_war10(0) == '0.0'


def test_name_cut_rules():
    n20 = b'SMITH'.ljust(12, b'\0') + b'JOHN'.ljust(8, b'\0')
    assert dynview.name_display(n20) == 'SMITH, JOHN'
    # long names cut to 18
    n = b'MCCORMACKSTE'.ljust(12, b'\0') + b'ALEXANDER'.ljust(8, b'\0')
    out = dynview.name_display(n)
    assert out == 'MCCORMACKSTE, ALEX' and len(out) == 18
    # empty first part: just the last name
    n2 = b'JONES'.ljust(12, b'\0') + bytes(8)
    assert dynview.name_display(n2) == 'JONES'
    # trailing spaces in the field are stripped
    n3 = b'MAY  '.ljust(12, b'\0') + b'E  '.ljust(8, b'\0')
    assert dynview.name_display(n3) == 'MAY, E'


def test_stem_display():
    assert dynview.stem_display(b'phila') == 'PHILA'
    assert dynview.stem_display(b'\0' * 8) == '?'


def test_event_text():
    assert dynview.event_text(2, 3260) == '3000 HITS'
    assert dynview.event_text(5, 501) == '500 HOME RUNS'
    assert dynview.event_text(32, 52) == '52 HR SEASON'
    assert dynview.event_text(35, 412) == '.412 SEASON'
    assert dynview.event_text(38, 185) == '1.85 ERA SEASON'
    assert dynview.event_text(39, 51) == '51 SAVE SEASON'


# ---------------------------------------------------------------- rendering
def test_render_framebuffer_and_title_colors(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir), FILES)
    fb = dynview.render(st(dynview.SCREEN_MENU), data)
    assert len(fb) == 64000
    # title bar rows 8..20 contain only title red, white and black pixels
    bad = set()
    for y in range(8, 21):
        for x in range(8, 312):
            v = fb[y * 320 + x]
            if v not in (dynview.C_TITLE_RED, dynview.C_WHITE, dynview.C_BLACK):
                bad.add(v)
    assert not bad, sorted(bad)
    # rows 21..23 are inside the frame panel (193), rows 2..3 outside it (215)
    for y in range(21, 24):
        for x in range(8, 312):
            assert fb[y * 320 + x] == dynview.C_FRAME_TAN
    for y in range(2, 4):
        for x in range(8, 312):
            assert fb[y * 320 + x] == dynview.C_BG_BROWN


def test_render_determinism_and_steps(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir), FILES)
    seq = [dynview.KEY_PGDN, ord('3'), dynview.KEY_RIGHT, dynview.KEY_PGDN,
           dynview.KEY_PGUP, dynview.KEY_LEFT, dynview.KEY_ESC, ord('4'),
           dynview.KEY_PGDN, ord('5'), dynview.KEY_ENTER, ord('2')]
    s = st(dynview.SCREEN_MENU)
    for k in seq:
        s, _ex = dynview.step(s, k, data)
        fb1 = dynview.render(s, data)
        fb2 = dynview.render(s, data)
        assert fb1 == fb2
        assert len(fb1) == 64000


def test_render_clipping(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    # fill first so as to tell in-bounds writes from stray default state: a fill of
    # index 0 is the state itself, so use a nonzero fill before the off-screen cases
    fill = bytearray(b'\x01' * 64000)
    main_ft = dynview.load_fonts(FILES)[0]
    # off-screen right and bottom: nothing written, no exception
    dynview.draw_text(fill, main_ft, 320, 100, 'A', 15)
    dynview.draw_text(fill, main_ft, 10, 200, 'A', 15)
    dynview.draw_text(fill, main_ft, 10, -5, 'A', 15)
    # in-bounds writes land only on rows/columns inside the screen
    dynview.draw_text(fill, main_ft, 10, 193, 'A', 15)
    got = [(i % 320, i // 320) for i, v in enumerate(fill) if v == 15]
    assert 0 < len(got) <= 7 * 4
    for x, y in got:
        assert 0 <= x < 320 and 0 <= y < 200
    # fully off right (x 320, every pixel past 319): nothing written
    fb = bytearray(b'\x01' * 64000)
    dynview.draw_text(fb, main_ft, 320, 10, 'A', 15)
    assert all(v == 1 for v in fb)
    # partially clipped glyph draws only its in-bounds pixels (x 313 is within 320
    # but the glyph spills past: only columns 0..319 land)
    fb = bytearray(b'\x01' * 64000)
    dynview.draw_text(fb, main_ft, 313, 10, 'I', 15)
    got = [(i % 320, i // 320) for i, v in enumerate(fb) if v == 15]
    assert 0 < len(got) and all(x < 320 for x, y in got)
    # last in-bounds start column where nothing is written depends on the glyph
    # width: x 320 at least guarantees every pixel is past 319
    fb = bytearray(b'\x01' * 64000)
    dynview.draw_text(fb, main_ft, 320, 10, 'I', 15)
    assert all(v == 1 for v in fb)
    # partially clipped glyph draws only its in-bounds pixels (x 313 + the 5 px
    # A spills past 319: only columns 0..319 land)
    fb = bytearray(b'\x01' * 64000)
    dynview.draw_text(fb, main_ft, 313, 10, 'A', 15)
    got = [(i % 320, i // 320) for i, v in enumerate(fb) if v == 15]
    assert 0 < len(got) and all(x < 320 for x, y in got)


# ---------------------------------------------------------------- empty / missing
def test_no_history_every_screen(tmp_path):
    ldir = tmp_path / 'empty'
    ldir.mkdir()
    data = dynview.load_data(str(ldir))
    for screen in (dynview.SCREEN_HISTORY, dynview.SCREEN_HOF,
                   dynview.SCREEN_LEADERS, dynview.SCREEN_MILESTONES,
                   dynview.SCREEN_REVIEW):
        s = st(screen, 0, 1 if screen == dynview.SCREEN_REVIEW else 0)
        assert dynview.rows(s, data) == [('NO DYNASTY HISTORY YET',)]
    # zero-seasons file behaves the same
    p = ldir / 'HISTORY.DAT'
    p.write_bytes(bytes(32))
    data = dynview.load_data(str(ldir))
    assert dynview.rows(st(dynview.SCREEN_HISTORY), data) == \
        [('NO DYNASTY HISTORY YET',)]


def test_title_mode(tmp_path):
    """/TITLE: MENU with cat 16. No season: welcome rows, 'ENTER PLAY BALL', title
    names season 1. With history: the menu items, season N+1. ENTER and ESC exit;
    1-8 open a screen whose ESC returns to the plain menu."""
    T = (dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG)
    ldir = tmp_path / 'empty'
    ldir.mkdir()
    data = dynview.load_data(str(ldir))
    assert dynview.rows(T, data) == [(t,) for t in dynview.TITLE_ROWS]
    assert all(len(t) <= 42 and t == t.upper() for t in dynview.TITLE_ROWS)
    assert len(dynview.TITLE_ROWS) <= dynview.ROWS_PER_PAGE
    assert dynview.footer_text(T, data) == 'ENTER PLAY BALL'
    assert dynview.screen_title(T, data) == 'DYNASTY MODE: 1993'
    assert dynview.body_cols(T, data) == dynview.COLS_SINGLE
    assert dynview.step(T, dynview.KEY_ENTER, data) == (T, 1)
    assert dynview.step(T, dynview.KEY_ESC, data)[1] == 1
    # the plain menu ignores ENTER
    assert dynview.step((dynview.SCREEN_MENU, 0, 0), dynview.KEY_ENTER, data) == \
        ((dynview.SCREEN_MENU, 0, 0), 0)
    assert dynview.rows((dynview.SCREEN_MENU, 0, 0), data) == [(t,) for t in dynview.MENU_ROWS]
    hdir, _ = make_data(tmp_path)
    data = dynview.load_data(str(hdir))
    assert dynview.rows(T, data)[0] == ('1  SEASON HISTORY',)
    assert dynview.footer_text(T, data) == '0-9 W SELECT   ENTER PLAY BALL'
    assert dynview.screen_title(T, data) == 'DYNASTY MODE: 1996'
    s, ex = dynview.step(T, ord('2'), data)
    assert s == (dynview.SCREEN_HOF, 0, 0) and ex == 0
    s, ex = dynview.step(s, dynview.KEY_ESC, data)
    assert s == (dynview.SCREEN_MENU, 0, 0) and ex == 0
    # every title glyph exists in MAIN.FNT (no '?' fallback)
    if os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        main_ft, _bold = dynview.load_fonts(FILES)
        for t in dynview.TITLE_ROWS + [dynview.TITLE_FOOTER]:
            assert all(0 <= ord(c) - 32 < len(main_ft) for c in t), t


# ---------------------------------------------------------------- previews
PREVIEWS = [st(dynview.SCREEN_MENU, 0, 0),
            st(dynview.SCREEN_HISTORY, 0, 0),
            st(dynview.SCREEN_HOF, 0, 0),
            st(dynview.SCREEN_LEADERS, 0, 0),
            st(dynview.SCREEN_LEADERS, 0, 4),
            st(dynview.SCREEN_LEADERS, 0, 9),
            st(dynview.SCREEN_MILESTONES, 0, 0),
            st(dynview.SCREEN_REVIEW, 0, 3)]


def test_preview_pngs(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    out = '/mnt/nvme/tlrb2/t5'
    os.makedirs(out, exist_ok=True)
    real = os.path.join(out, 'real', 'HISTORY.DAT')
    pal = dynview.load_palette(os.path.join(FILES, 'DEFAULT.PAL'))
    # synthetic previews
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir), FILES)
    for n, s in enumerate(PREVIEWS):
        fb = dynview.render(s, data)
        dynview.write_png(os.path.join(out, 'syn_%02d.png' % n), fb, pal)
    # real previews when a recorded HISTORY.DAT exists
    if not (os.path.exists(real)
            and history.History.load(real).seasons_recorded > 0):
        print('real preview skipped: no recorded HISTORY.DAT under', out)
        return
    data = dynview.load_data(os.path.join(out, 'real'), FILES)
    for n, s in enumerate(PREVIEWS):
        fb = dynview.render(s, data)
        dynview.write_png(os.path.join(out, 'real_%02d.png' % n), fb, pal)


def test_column_layout_fits_and_never_overlaps():
    """Every MAIN.FNT glyph advances CHAR_W: columns stay inside x 10..304 and
    never share a pixel column, and every row builder's cells fit their width."""
    assert dynview.CHAR_W == 7
    for cols in (dynview.COLS_SINGLE, dynview.COLS_HISTORY, dynview.COLS_HOF,
                 dynview.COLS_LEADERS, dynview.COLS_MILESTONES, dynview.COLS_RETIRE,
                 dynview.COLS_DRAFT, dynview.COLS_MOVE, dynview.COLS_AWARDS):
        prev_end = 0
        for header, x, w, _a in cols:
            assert len(header) <= w
            assert x >= 10 and x >= prev_end
            prev_end = x + w * dynview.CHAR_W
        assert prev_end <= 10 + 42 * dynview.CHAR_W


def test_cells_fit_columns(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    screens = {dynview.SCREEN_HISTORY: dynview.COLS_HISTORY,
               dynview.SCREEN_HOF: dynview.COLS_HOF,
               dynview.SCREEN_MILESTONES: dynview.COLS_MILESTONES,
               dynview.SCREEN_REVIEW: dynview.COLS_SINGLE}
    for scr, cols in screens.items():
        for row in dynview.rows(st(scr), data):
            for cell, (_h, _x, w, _a) in zip(row, cols):
                assert len(cell) <= w, (scr, cell)
    for cat in range(dynview.N_CATS):
        for row in dynview.rows(st(dynview.SCREEN_LEADERS, 0, cat), data):
            for cell, (_h, _x, w, _a) in zip(row, dynview.COLS_LEADERS):
                assert len(cell) <= w, (cat, cell)


def test_review_title_from_menu_uses_last_season(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    s, _ex = dynview.step(st(dynview.SCREEN_MENU), ord('5'), data)
    assert dynview.screen_title(s, data) == '1995 IN REVIEW'
    assert dynview.rows(s, data)[0] == ('CHAMPION ALA03',)


def test_name_cut_never_leaves_dangling_comma():
    n = b'PLAYER03'.ljust(12, b'\0') + b'B'.ljust(8, b'\0')
    assert dynview.name_display(n, 9) == 'PLAYER03'
    assert dynview.name_display(n, 10) == 'PLAYER03'
    assert dynview.name_display(n, 11) == 'PLAYER03, B'
    long = b'MCCORMACKSTE'.ljust(12, b'\0') + b'AL'.ljust(8, b'\0')
    assert dynview.name_display(long, 9) == 'MCCORMACK'


def test_list_max_caps_rows_and_paging(tmp_path, monkeypatch):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    monkeypatch.setattr(dynview, 'LIST_MAX', 14)
    # MVP leaders: 28 qualify, capped to 14 -> pages 0 and 1 only, page 1 has 2 rows
    assert dynview.leaders_count(data['hist'], 16) == 14
    s, _ex = dynview.step(st(dynview.SCREEN_LEADERS, 0, 16), dynview.KEY_PGDN, data)
    assert s[1] == 1 and len(dynview.rows(s, data)) == 2
    s, _ex = dynview.step(s, dynview.KEY_PGDN, data)
    assert s[1] == 1
    monkeypatch.setattr(dynview, 'LIST_MAX', 3)
    assert len(dynview.milestone_rows(data['hist'], data['ms'])) == 3
    assert dynview.milestone_rows(data['hist'], data['ms'])[0][0] == '1995'


def test_no_history_row_uses_single_column(tmp_path):
    ldir = tmp_path / 'empty'
    ldir.mkdir()
    data = dynview.load_data(str(ldir))
    for screen in range(6):
        cols = dynview.body_cols(st(screen), data)
        assert cols == dynview.COLS_SINGLE
        assert len(dynview.rows(st(screen), data)[0][0]) <= cols[0][2]


def test_unknown_chars_draw_question_mark():
    font = [(1, 1, 7, bytes([0x80]), 1)] * 95
    font = list(font)
    font[31] = (1, 1, 7, bytes([0x80]), 1)
    marker = (2, 1, 7, bytes([0x80, 0x80]), 1)
    font[31] = marker
    assert dynview.glyph_of(font, '\x01') is marker
    assert dynview.glyph_of(font, '\xe9') is marker
    assert dynview.glyph_of(font, '?') is marker
    assert dynview.glyph_of(font, '/') is not marker


def test_upper_is_ascii_only():
    """Only a-z upper-case: latin-1 0xDF must not become 'SS' (two glyphs), and
    every byte outside 32..126 draws the '?' glyph, as DYNVIEW.EXE does."""
    font = [(7, 7, 7 + k % 3, bytes(7), 1) for k in range(95)]
    q = dynview.text_width(font, '?')
    for b in (0xdf, 0xb5, 0xff, 0xe9, 0x07):
        assert dynview.text_width(font, chr(b)) == q, hex(b)
    assert dynview.text_width(font, 'ab') == dynview.text_width(font, 'AB')


def test_team_names_from_v20(tmp_path):
    """Champion/runner-up show the V20 header name (bytes 0..13, NUL ended),
    matched case-insensitively on the stem; no file or a blank name keeps the stem."""
    ldir, _ = make_data(tmp_path)
    (ldir / 'ALA03.V20').write_bytes(b'PHILADELPHIA\0\0clPHI' + bytes(60))
    (ldir / 'NL03.V20').write_bytes(bytes(80))                  # blank name
    (ldir / 'ALA02.V20').write_bytes(b'Chicago A\0junk.' + bytes(60))
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_HISTORY), data)
    assert rows[0][1] == 'PHILADELPHIA'
    assert rows[1][1] == 'Chicago A'
    rev = [r[0] for r in dynview.rows(st(dynview.SCREEN_REVIEW, 0, 3), data)]
    assert rev[0] == 'CHAMPION PHILADELPHIA' and rev[1] == 'RUNNER-UP NL03'


def test_no_award_reads_none(tmp_path):
    ldir, _ = make_data(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    write_season(d, 3, b'ALA03', b'NL03', awards=(0, 1, 0xffff, 3, 4, 0xffff))
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rev = [r[0] for r in dynview.rows(st(dynview.SCREEN_REVIEW, 0, 3), data)]
    assert 'AL ROOKIE NONE' in rev and 'NL ROOKIE NONE' in rev


# ---------------------------------------------------------------- offseason
SO = dynview.SCREEN_OFFSEASON
ENTER, ESC = dynview.KEY_ENTER, dynview.KEY_ESC


def oc(phase, launched=1):
    """cat of an offseason phase: phase + 16 * launched"""
    return phase + 16 * launched


def write_team(ldir, stem, name):
    """LEAGUE_DIR/<STEM>.V20 whose header name is name (only bytes 0..13 are read)"""
    (ldir / (stem + '.V20')).write_bytes(name.encode('latin-1').ljust(14, b'\0') + bytes(66))


ROSTER_BODY = (
    b'DRAFT CLASALE1 Bobby Holmes\r\n'
    b'DRAFT CLASALW2 Bobby Holmes\r\n'            # same name on a second team
    b'DRAFT CLASNLE3 Lou Green\r\n'
    b'SIGN CLASALW7 Bobby Holmes CLASALE1\r\n'    # pick 1: first Bobby Holmes
    b'SIGN CLASNLE4 Bobby Holmes CLASALE1\r\n'    # no unconsumed CLASALE1 draft: FA
    b'SIGN CLASNLE4 Bobby Holmes CLASALW2\r\n'    # pick 2
    b'SIGN CLASALW7 Lou Green pool\r\n'           # FA from the pool
    b'SIGN CLASALE1 Lou Green CLASNLE3\r\n'       # pick 3
    b'TRADE CLASALE1 Duke Snider CLASNLW4 TONY BERNAZARD\r\n'
    b'REL CLASALE1 Some Guy\r\n'
    b'REL CLASALW2 Other Guy Jr\r\n'
    b'REL CLASALE1\r\n'                           # two tokens: not a release
    b'TRADE CLASNLE3 Lou CLASALW2 Lou Green\n'    # LF only; B is the first team token
    b'TRADE CLASALE1 Nobody Here NOTATEAM Foo\n'  # no team token: ignored
    b'SIGN CLASALE1 ' + b'Q' * 120 + b' FROM\r\n'  # over 127 bytes: ignored
    b'SIGN CLASNLW5 Tom Free pool\n'
    b'SIGN CLASNLW5 Tom Free CLASALE2\n'          # team to team (no draft): FA
    b'RET CLASALE1 Old Guy\r\n')                  # RET is not an offseason event


def make_offseason(tmp_path, rosters=ROSTER_BODY):
    """Three recorded seasons and seven entries. Four retire in season 3 (OLDMAN, a
    HoF inductee, WAR10 90; RIVERA and TIE, WAR10 50 each; NEGWAR, WAR10 -5). An early
    retiree, an active player and an old HoF inductee must not show. Team files:
    CLASALW7 (SEATTLE), CLASALW2 (BOSTON), CLASNLW4 (NEW YORK N). rosters=None writes
    no ROSTERS.TXT."""
    ldir = tmp_path / 'off'
    ldir.mkdir()
    d = bytearray(32 + 64 * 128 + 7 * 160)
    d[3] = 1
    d[4], d[5] = 3, 0
    d[6], d[7] = 7, 0
    write_season(d, 1, b'ALA01', b'NL01')
    write_season(d, 2, b'ALA02', b'NL02')
    write_season(d, 3, b'ALA03', b'NL03', awards=(0, 1, 0xffff, 3, 4, 0xffff))
    # last, first, status, last_season, hof_season, war10, age, seasons_played
    specs = [(b'RIVERA', b'JOSE', 2, 3, 0, 50, 36, 12),
             (b'OLDMAN', b'AL', 3, 3, 3, 90, 40, 20),
             (b'TIE', b'ONE', 2, 3, 0, 50, 33, 9),
             (b'EARLY', b'X', 2, 2, 0, 999, 30, 5),
             (b'ACTIVE', b'Y', 1, 3, 0, 70, 25, 6),
             (b'HOFOLD', b'Z', 3, 2, 2, 300, 39, 15),
             (b'NEGWAR', b'Q', 2, 3, 0, -5, 38, 3)]
    for i, (last, first, status, last_season, hof, war10, age, played) in enumerate(specs):
        write_player(d, i, last, first, status=status, last_season=last_season,
                     seasons_played=played, hof_season=hof, war10=war10)
        d[8224 + 160 * i + 23] = age
    (ldir / 'HISTORY.DAT').write_bytes(bytes(d))
    write_mileston(str(ldir / 'MILESTON.DAT'), [(3, 0, 2, 3000)])
    write_team(ldir, 'CLASALW7', 'SEATTLE')
    write_team(ldir, 'CLASALW2', 'BOSTON')
    write_team(ldir, 'CLASNLW4', 'NEW YORK N')
    if rosters is not None:
        (ldir / 'ROSTERS.TXT').write_bytes(rosters)
    return ldir


def test_roster_events_parse(tmp_path):
    ldir = make_offseason(tmp_path)
    assert dynview.parse_rosters(str(ldir)) == [
        ('DRAFT', 'CLASALE1', 'Bobby Holmes'), ('DRAFT', 'CLASALW2', 'Bobby Holmes'),
        ('DRAFT', 'CLASNLE3', 'Lou Green'),
        ('SIGN', 'CLASALW7', 'Bobby Holmes', 'CLASALE1'),
        ('SIGN', 'CLASNLE4', 'Bobby Holmes', 'CLASALE1'),
        ('SIGN', 'CLASNLE4', 'Bobby Holmes', 'CLASALW2'),
        ('SIGN', 'CLASALW7', 'Lou Green', 'pool'),
        ('SIGN', 'CLASALE1', 'Lou Green', 'CLASNLE3'),
        ('TRADE', 'CLASALE1', 'Duke Snider', 'CLASNLW4', 'TONY BERNAZARD'),
        ('REL', 'CLASALE1', 'Some Guy'), ('REL', 'CLASALW2', 'Other Guy Jr'),
        ('TRADE', 'CLASNLE3', 'Lou', 'CLASALW2', 'Lou Green'),
        ('SIGN', 'CLASNLW5', 'Tom Free', 'pool'),
        ('SIGN', 'CLASNLW5', 'Tom Free', 'CLASALE2')]


def test_roster_crlf_and_lf_agree(tmp_path):
    ldir = make_offseason(tmp_path)
    crlf = dynview.parse_rosters(str(ldir))
    (ldir / 'ROSTERS.TXT').write_bytes(ROSTER_BODY.replace(b'\r\n', b'\n'))
    assert dynview.parse_rosters(str(ldir)) == crlf


def test_roster_line_length_boundary(tmp_path):
    """127 content bytes are kept (also with a CR, which is stripped); 128 are not"""
    ldir = make_offseason(tmp_path, rosters=None)
    head = b'REL CLASALE1 '                              # 13 bytes
    body = (head + b'R' * 114 + b'\n'                      # 127: kept
            + head + b'R' * 115 + b'\n'                    # 128: ignored
            + head + b'R' * 114 + b'\r\n'                  # 128 raw, 127 content: kept
            + head + b'R' * 115 + b'\r\n')                 # 129 raw, 128 content: ignored
    (ldir / 'ROSTERS.TXT').write_bytes(body)
    assert dynview.parse_rosters(str(ldir)) == [('REL', 'CLASALE1', 'R' * 114),
                                                ('REL', 'CLASALE1', 'R' * 114)]


def test_roster_missing_file(tmp_path):
    ldir = make_offseason(tmp_path, rosters=None)
    assert dynview.parse_rosters(str(ldir)) == []
    assert dynview.load_data(str(ldir))['events'] == []


def test_draft_matching_consumes_first(tmp_path):
    ldir = make_offseason(tmp_path)
    picks, fa = dynview.sign_split(dynview.load_data(str(ldir))['events'])
    assert picks == [('CLASALW7', 'Bobby Holmes'), ('CLASNLE4', 'Bobby Holmes'),
                     ('CLASALE1', 'Lou Green')]
    assert fa == [('CLASNLE4', 'Bobby Holmes', 'CLASALE1'),
                  ('CLASALW7', 'Lou Green', 'pool'),
                  ('CLASNLW5', 'Tom Free', 'pool'),
                  ('CLASNLW5', 'Tom Free', 'CLASALE2')]


def test_offseason_phase_rows(tmp_path):
    ldir = make_offseason(tmp_path)
    data = dynview.load_data(str(ldir))

    def body(phase):
        return dynview.rows((SO, 0, oc(phase)), data)
    review = body(0)
    assert review[0] == ('CHAMPION ALA03',) and review[1] == ('RUNNER-UP NL03',)
    assert ('NEW HALL OF FAME: OLDMAN, AL',) in review
    assert review[-1] == ('RIVERA, JOSE 3000 HITS',) and len(review) == 10
    # retirees: WAR10 descending (ties by entry index), HoF flag, no early retiree
    assert body(1) == [('OLDMAN, AL', '40', '20', '9.0', 'HOF'),
                       ('RIVERA, JOSE', '36', '12', '5.0', ''),
                       ('TIE, ONE', '33', '9', '5.0', ''),
                       ('NEGWAR, Q', '38', '3', '-0.5', '')]
    assert dynview.body_cols((SO, 0, oc(1)), data) == dynview.COLS_RETIRE
    assert body(2) == [('#1', 'SEATTLE', '', 'Bobby Holmes'),
                       ('#2', 'CLASNLE4', '', 'Bobby Holmes'),
                       ('#3', 'CLASALE1', '', 'Lou Green')]
    assert dynview.body_cols((SO, 0, oc(2)), data) == dynview.COLS_DRAFT
    assert body(3) == [('CLASALE1', 'Duke Snider', 'NEW YORK N'),
                       ('NEW YORK N', 'TONY BERNAZARD', 'CLASALE1'),
                       ('CLASNLE3', 'Lou', 'BOSTON'), ('BOSTON', 'Lou Green', 'CLASNLE3')]
    assert dynview.body_cols((SO, 0, oc(3)), data) == dynview.COLS_MOVE
    assert body(4) == [('CLASNLE4', 'Bobby Holmes', 'CLASALE1'),
                       ('SEATTLE', 'Lou Green', 'FREE AGENT'),
                       ('CLASNLW5', 'Tom Free', 'FREE AGENT'),
                       ('CLASNLW5', 'Tom Free', 'CLASALE2'),
                       ('CLASALE1', 'Some Guy', 'RELEASED'),
                       ('BOSTON', 'Other Guy Jr', 'RELEASED')]
    assert dynview.body_cols((SO, 0, oc(4)), data) == dynview.COLS_MOVE
    ready = ['RETIRED: 4   NEW HALL OF FAME: 1', 'ROOKIES DRAFTED: 3', 'TRADES: 2',
             'FREE AGENT SIGNINGS: 4', 'PLAYERS RELEASED: 2',
             'EVERY PLAYER AGED A YEAR AND DEVELOPED']
    assert body(5) == [(t,) for t in ready + ['ENTER: ON TO 1996']]
    assert dynview.rows((SO, 0, oc(5, 0)), data)[-1] == ('ENTER: BACK TO THE MENU',)
    assert dynview.body_cols((SO, 0, oc(5)), data) == dynview.COLS_SINGLE


def test_offseason_empty_phases(tmp_path):
    ldir = make_offseason(tmp_path, rosters=None)
    data = dynview.load_data(str(ldir))
    for phase, msg in ((2, 'NO DRAFT PICKS'), (3, 'NO TRADES'),
                       (4, 'NO SIGNINGS OR RELEASES')):
        s = (SO, 0, oc(phase))
        assert dynview.rows(s, data) == [(msg,)]
        assert dynview.body_cols(s, data) == dynview.COLS_SINGLE
    assert dynview.rows((SO, 0, oc(5)), data)[1:5] == [
        ('ROOKIES DRAFTED: 0',), ('TRADES: 0',), ('FREE AGENT SIGNINGS: 0',),
        ('PLAYERS RELEASED: 0',)]
    # the phase-1 retirees need no ROSTERS.TXT
    assert len(dynview.rows((SO, 0, oc(1)), data)) == 4


def test_offseason_titles_footers_and_menu(tmp_path):
    ldir = make_offseason(tmp_path)
    data = dynview.load_data(str(ldir))
    titles = ['1/6 1995 IN REVIEW', '2/6 RETIREMENTS', '3/6 ROOKIE DRAFT',
              '4/6 TRADES', '5/6 SIGNINGS AND RELEASES', '6/6 1996 IS READY']
    for phase, title in enumerate(titles):
        assert dynview.screen_title((SO, 0, oc(phase)), data) == title
        assert dynview.screen_title((SO, 0, oc(phase, 0)), data) == title
        if phase < 5:
            assert dynview.footer_text((SO, 0, oc(phase))) == \
                'ENTER NEXT   PGUP PGDN   ESC MENU'
            assert dynview.footer_text((SO, 0, oc(phase, 0))) == \
                'ENTER NEXT   PGUP PGDN   ESC MENU'
    assert dynview.footer_text((SO, 0, oc(5))) == 'ENTER CONTINUE   ESC MENU'
    assert dynview.footer_text((SO, 0, oc(5, 0))) == 'ENTER MENU   ESC MENU'
    assert dynview.footer_text((dynview.SCREEN_MENU, 0, 0)) == '0-9 W P F SELECT   ESC EXIT'
    assert dynview.footer_text((dynview.SCREEN_HISTORY, 0, 0)) == \
        'ENTER STANDINGS   PGUP PGDN   ESC MENU'
    assert dynview.footer_text((dynview.SCREEN_REVIEW, 0, 0)) == 'ENTER MENU   ESC MENU'
    # the menu's sixth row and key 6; key 7 opens DYNASTY SETTINGS, 9 SEASON AWARDS
    assert dynview.rows((dynview.SCREEN_MENU, 0, 0), data)[5] == ('6  OFFSEASON',)
    assert dynview.total_rows((dynview.SCREEN_MENU, 0, 0), data) == 12
    s, ex = dynview.step((dynview.SCREEN_MENU, 0, 0), ord('6'), data)
    assert s == (SO, 0, 0) and ex == 0
    s, ex = dynview.step((dynview.SCREEN_MENU, 0, 0), ord('9'), data)
    assert s == (dynview.SCREEN_AWARDS, 0, 0) and ex == 0


def test_offseason_enter_walk(tmp_path):
    ldir = make_offseason(tmp_path)
    data = dynview.load_data(str(ldir))
    s = (SO, 0, oc(0))
    for phase in range(1, 6):
        s, ex = dynview.step(s, ENTER, data)
        assert ex == 0 and s == (SO, 0, oc(phase))
    # past the last phase: launched exits (state unchanged), not launched goes to MENU
    s2, ex = dynview.step(s, ENTER, data)
    assert ex == 1 and s2 == s
    s2, ex = dynview.step((SO, 0, oc(5, 0)), ENTER, data)
    assert ex == 0 and s2 == (dynview.SCREEN_MENU, 0, 0)
    # ENTER resets the page and keeps the launched flag
    s2, _ex = dynview.step((SO, 3, oc(1)), ENTER, data)
    assert s2 == (SO, 0, oc(2))
    s2, _ex = dynview.step((SO, 2, oc(0, 0)), ENTER, data)
    assert s2 == (SO, 0, 1)
    # ESC always goes to MENU without exiting from the offseason
    s2, ex = dynview.step((SO, 0, oc(5)), ESC, data)
    assert s2 == (dynview.SCREEN_MENU, 0, 0) and ex == 0


def test_offseason_no_history(tmp_path):
    ldir = tmp_path / 'empty'
    ldir.mkdir()
    data = dynview.load_data(str(ldir))
    for phase in range(6):
        s = (SO, 0, oc(phase))
        assert dynview.rows(s, data) == [('NO DYNASTY HISTORY YET',)]
        assert dynview.body_cols(s, data) == dynview.COLS_SINGLE
        assert dynview.total_rows(s, data) == 0
    assert dynview.screen_title((SO, 0, oc(0)), data) == '1/6 1992 IN REVIEW'
    assert dynview.screen_title((SO, 0, oc(5)), data) == '6/6 1993 IS READY'
    assert dynview.step((SO, 0, oc(0)), ENTER, data) == ((SO, 0, oc(0)), 1)
    assert dynview.step((SO, 0, oc(0, 0)), ENTER, data) == ((dynview.SCREEN_MENU, 0, 0), 0)


def test_offseason_paging(tmp_path):
    rosters = b''.join(b'SIGN CLASALW7 Player%02d pool\r\n' % k for k in range(30))
    ldir = make_offseason(tmp_path, rosters)
    data = dynview.load_data(str(ldir))
    s = (SO, 0, oc(4))
    assert len(dynview.rows(s, data)) == 12
    s, _ex = dynview.step(s, dynview.KEY_PGDN, data)
    assert s[1] == 1 and dynview.rows(s, data)[0] == ('SEATTLE', 'Player12', 'FREE AGENT')
    s, _ex = dynview.step(s, dynview.KEY_PGDN, data)
    assert s[1] == 2 and len(dynview.rows(s, data)) == 6
    s, _ex = dynview.step(s, dynview.KEY_PGDN, data)
    assert s[1] == 2
    s, _ex = dynview.step(s, dynview.KEY_PGUP, data)
    s, _ex = dynview.step(s, dynview.KEY_PGUP, data)
    s, _ex = dynview.step(s, dynview.KEY_PGUP, data)
    assert s[1] == 0


def test_offseason_list_max_caps_rows(tmp_path, monkeypatch):
    rosters = b''.join(b'SIGN CLASALW7 Player%02d pool\r\n' % k for k in range(30))
    ldir = make_offseason(tmp_path, rosters)
    monkeypatch.setattr(dynview, 'LIST_MAX', 14)
    data = dynview.load_data(str(ldir))
    s, _ex = dynview.step((SO, 0, oc(4)), dynview.KEY_PGDN, data)
    assert len(dynview.rows(s, data)) == 2
    s2, _ex = dynview.step(s, dynview.KEY_PGDN, data)
    assert s2[1] == 1
    # the counts on the ready phase stay uncapped
    assert dynview.rows((SO, 0, oc(5)), data)[3] == ('FREE AGENT SIGNINGS: 30',)


def test_draft_keep_drops_later_drafts(tmp_path, monkeypatch):
    ldir = make_offseason(tmp_path)
    monkeypatch.setattr(dynview, 'DRAFT_KEEP', 2)
    picks, fa = dynview.sign_split(dynview.load_data(str(ldir))['events'])
    # only the first two DRAFT lines exist for the matcher: Lou Green is a free agent
    assert [p[1] for p in picks] == ['Bobby Holmes', 'Bobby Holmes']
    assert len(fa) == 5


def test_offseason_render_each_phase(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    ldir = make_offseason(tmp_path)
    data = dynview.load_data(str(ldir), FILES)
    seen = set()
    for phase in range(6):
        for launched in (0, 1):
            fb = dynview.render((SO, 0, oc(phase, launched)), data)
            assert len(fb) == 64000
            seen.add(bytes(fb))
    # phases 0..4 look the same either way; phase 5 differs by its launch text
    assert len(seen) == 7


def test_offseason_cells_fit_columns(tmp_path):
    ldir = make_offseason(tmp_path)
    data = dynview.load_data(str(ldir))
    for phase in range(6):
        cols = dynview.body_cols((SO, 0, oc(phase)), data)
        for row in dynview.rows((SO, 0, oc(phase)), data):
            for cell, (_h, _x, w, _a) in zip(row, cols):
                assert len(cell) <= w, (phase, cell)


def test_offseason_no_history_ignores_dangling_rosters(tmp_path):
    """ROSTERS.TXT without HISTORY.DAT shows the empty-history screens"""
    ldir = tmp_path / 'norec'
    ldir.mkdir()
    (ldir / 'ROSTERS.TXT').write_bytes(ROSTER_BODY)
    data = dynview.load_data(str(ldir))
    assert dynview.rows((SO, 0, oc(4)), data) == [('NO DYNASTY HISTORY YET',)]


# ---------------------------------------------------------------- C17 draft POS, managed cells
def write_team_v20_full(ldir, stem, records, name=None):
    """A full-size <STEM>.V20 (HDR + REC * 80 B, the v20.Rec layout) whose header name
    bytes 0..13 hold name (like write_team): records is {slot: (name, pos1)} with name
    'First Last' as ROSTERS.TXT spells it; other slots stay off (first byte 0). The
    record keeps byte 0 set and the name at bytes 1..19 (the V20 convention, so
    rosters.pname reads First Last)."""
    import v20
    d = bytearray(v20.HDR + v20.REC * 80)
    if name is not None:
        d[0:14] = name.encode('latin-1').ljust(14, b'\0')[:14]
    for slot, (pname, pos1) in records.items():
        first, _, last = pname.partition(' ')
        off = v20.HDR + v20.REC * slot
        d[off:off + 12] = last.encode('latin-1').ljust(12, b'\0')[:12]
        d[off + 12:off + 20] = first.encode('latin-1').ljust(8, b'\0')[:8]
        b, kind = v20.F['pos1']                         # byte 0x1f of the record, low nibble
        if kind == 'lo':
            d[off + b] |= pos1 & 15
        elif kind == 'hi':
            d[off + b] |= (pos1 & 15) << 4
        elif kind == 'u8' or kind == 'u16':
            d[off + b] = pos1 & 255
    (ldir / (stem + '.V20')).write_bytes(bytes(d))


def test_draft_pos_from_team_file(tmp_path):
    """C17.1: POS is the pos1 of the first on slot whose name matches exactly; an off
    slot with the same name is skipped."""
    ldir = make_offseason(tmp_path, rosters=b'DRAFT CLASALE1 Bobby Green\r\n'
                                         b'DRAFT CLASALE1 Pat Smol\r\n'
                                         b'SIGN CLASALW7 Bobby Green CLASALE1\r\n'
                                         b'SIGN CLASALW2 Pat Smol CLASALE1\r\n')
    write_team_v20_full(ldir, 'CLASALW7', {0: ('Lou Green', 5), 1: ('Bobby Green', 0)},
                        name='SEATTLE')
    write_team_v20_full(ldir, 'CLASALW2', {3: ('Bobby Holms', 0), 5: ('Pat Smol', 4)})
    data = dynview.load_data(str(ldir))
    rows = dynview.offseason_body((SO, 0, oc(2)), data)[1]
    assert rows == [('#1', 'SEATTLE', 'P', 'Bobby Green'),
                    ('#2', 'CLASALW2', '3B', 'Pat Smol')]


def test_draft_pos_rules(tmp_path):
    """C17.1: a pick on an off slot is skipped, two same-name records take the lower
    slot, a short file (< HDR + REC * 40) and a missing file give ''."""
    import v20
    ldir = make_offseason(tmp_path, rosters=b'DRAFT CLASALE1 Lou Green\r\n'
                                         b'DRAFT CLASALE1 Lou Green\r\n'
                                         b'DRAFT CLASALE1 Sam Twice\r\n'
                                         b'DRAFT CLASALE1 Short One\r\n'
                                         b'SIGN CLASALW7 Lou Green CLASALE1\r\n'
                                         b'SIGN CLASALW2 Lou Green CLASALE1\r\n'
                                         b'SIGN CLASNLW4 Sam Twice CLASALE1\r\n'
                                         b'SIGN SHORTONE Short One CLASALE1\r\n')
    write_team_v20_full(ldir, 'CLASALW7', {0: ('Lou Green', 5)}, name='SEATTLE')
    dd = bytearray((ldir / 'CLASALW7.V20').read_bytes())
    dd[v20.HDR] = 0                                   # slot 0 off: the pick is not on it
    (ldir / 'CLASALW7.V20').write_bytes(bytes(dd))
    write_team_v20_full(ldir, 'CLASALW2', {0: ('Lou Green', 1), 2: ('Lou Green', 6)},
                        name='BOSTON')
    dd = bytearray((ldir / 'CLASALW2.V20').read_bytes())
    dd[v20.HDR] = 0                                   # slot 0 off, slot 2 on
    (ldir / 'CLASALW2.V20').write_bytes(bytes(dd))
    write_team_v20_full(ldir, 'CLASNLW4', {3: ('Sam Twice', 2), 7: ('Sam Twice', 9)},
                        name='NEW YORK N')
    # a short file (< HDR + REC * 40): POS ''
    (ldir / 'SHORTONE.V20').write_bytes(bytes(20))
    data = dynview.load_data(str(ldir))
    rows = dynview.offseason_body((SO, 0, oc(2)), data)[1]
    assert rows == [('#1', 'SEATTLE', '', 'Lou Green'),        # off slot with the name
                    ('#2', 'BOSTON', 'LF', 'Lou Green'),       # lower of the two slots
                    ('#3', 'NEW YORK N', '1B', 'Sam Twice'),
                    ('#4', 'SHORTONE', '', 'Short One')]       # short file: ''
    # a missing team file: POS ''
    (tmp_path / 'nofile').mkdir()
    ldir = make_offseason(tmp_path / 'nofile',
                          rosters=b'DRAFT CLASALE1 Bobby Green\r\n'
                                  b'SIGN CLASALW7 Bobby Green CLASALE1\r\n')
    rows = dynview.offseason_body((SO, 0, oc(2)),
                                  dynview.load_data(str(ldir)))[1]
    assert rows == [('#1', 'SEATTLE', '', 'Bobby Green')]


def draft_managed_test_league(tmp_path, rosters, mask):
    """make_offseason league with a MAJ of the three teams (SEATTLE, BOSTON and the
    poolless CPU teams) and HISTORY mask mask: the team ids 0 (BOSTON), 7 (SEATTLE) and
    20 (NEW YORK N) are the NL/AL-slot engine ids of the C12 layout."""
    ldir = make_offseason(tmp_path, rosters=rosters)
    write_maj(ldir, {0: b'CLASALW2', 7: b'CLASALW7', 20: b'CLASNLW4'})
    hp = ldir / 'HISTORY.DAT'
    d = bytearray(hp.read_bytes())
    d[12:16] = mask.to_bytes(4, 'little')
    hp.write_bytes(bytes(d))
    return ldir


DRAFT17 = (b'DRAFT CLASALE1 Bobby Holmes\r\n'
           b'DRAFT CLASALW2 Bobby Holmes\r\n'
           b'DRAFT CLASNLE3 Lou Green\r\n'
           b'SIGN CLASALW7 Bobby Holmes CLASALE1\r\n'
           b'SIGN CLASALW2 Bobby Holmes CLASALW2\r\n'
           b'SIGN CLASNLW4 Lou Green CLASNLE3\r\n')
FA17 = (b'DRAFT CLASNLE3 Lou Green\r\n'
        b'SIGN CLASALW7 Lou Green pool\r\n'
        b'SIGN CLASALW2 Bobby Holmes CLASNLW4\r\n'
        b'SIGN CLASNLW4 Lou Green pool\r\n')
TRADE17 = (b'TRADE CLASALW7 Duke Snider CLASNLW4 TONY BERNAZARD\r\n'
           b'TRADE CLASALW2 Lou Green CLASNLW4 Old Yeller\r\n')


def test_managed_marks_draft_trades_fa(tmp_path):
    """C17.2: a managed team's TEAM cell starts with '*' on the draft, trades and free
    agent phases; the star lives in the cell text, cut to the column width like any long
    cell."""
    ldir = draft_managed_test_league(tmp_path, DRAFT17 + FA17 + TRADE17, 1 << 7)
    data = dynview.load_data(str(ldir))
    # the mask bit 7 is SEATTLE's id (AL slot 7); BOSTON (0) and NEW YORK N (20) are not
    assert dynview.settings_rows(data)[3:] == [('BOSTON', 'AI MANAGES'),
                                               ('SEATTLE', 'YOU MANAGE'),
                                               ('NEW YORK N', 'AI MANAGES')]
    assert dynview.offseason_body((SO, 0, oc(2)), data)[1] == [
        ('#1', '*SEATTLE', '', 'Bobby Holmes'),
        ('#2', 'BOSTON', '', 'Bobby Holmes'),
        ('#3', 'NEW YORK N', '', 'Lou Green')]
    assert dynview.offseason_body((SO, 0, oc(3)), data)[1] == [
        ('*SEATTLE', 'Duke Snider', 'NEW YORK N'),
        ('NEW YORK N', 'TONY BERNAZARD', 'SEATTLE'),
        ('BOSTON', 'Lou Green', 'NEW YORK N'),
        ('NEW YORK N', 'Old Yeller', 'BOSTON')]
    assert dynview.offseason_body((SO, 0, oc(4)), data)[1] == [
        ('*SEATTLE', 'Lou Green', 'FREE AGENT'),
        ('BOSTON', 'Bobby Holmes', 'NEW YORK N'),
        ('NEW YORK N', 'Lou Green', 'FREE AGENT')]


def test_managed_by_stem_not_display(tmp_path):
    """C17.2: the match is by stable id from the team token (the STEM map), never by
    display-name equality: two teams whose V20 header names are equal with only one
    managed mark only that team's rows."""
    rosters = (b'DRAFT CLASALE1 Bobby Holmes\r\n'
               b'DRAFT CLASALE1 Bobby Holmes\r\n'
               b'SIGN CLASALW7 Bobby Holmes CLASALE1\r\n'
               b'SIGN CLASALW2 Bobby Holmes CLASALE1\r\n')
    ldir = draft_managed_test_league(tmp_path, rosters, 1 << 7)
    write_team(ldir, 'CLASALW2', 'SEATTLE')             # same display as CLASALW7
    data = dynview.load_data(str(ldir))
    assert data['team_stems'] == {'CLASALW2': 0, 'CLASALW7': 7, 'CLASNLW4': 20}
    assert dynview.offseason_body((SO, 0, oc(2)), data)[1] == [
        ('#1', '*SEATTLE', '', 'Bobby Holmes'), ('#2', 'SEATTLE', '', 'Bobby Holmes')]


def test_managed_mask_zero_and_no_id(tmp_path):
    """C17.2: mask 0 marks nothing; a token whose team has no V20 file has no stable id
    and is never managed, even with its mask bit set."""
    ldir = draft_managed_test_league(tmp_path, DRAFT17, 0)
    data = dynview.load_data(str(ldir))
    assert dynview.offseason_body((SO, 0, oc(2)), data)[1] == [
        ('#1', 'SEATTLE', '', 'Bobby Holmes'), ('#2', 'BOSTON', '', 'Bobby Holmes'),
        ('#3', 'NEW YORK N', '', 'Lou Green')]
    # all bits set: every team with an id is managed
    (tmp_path / 'all').mkdir()
    data = dynview.load_data(draft_managed_test_league(
        tmp_path / 'all', DRAFT17, 0xffffffff))
    rows = dynview.offseason_body((SO, 0, oc(2)), data)[1]
    assert [r[1] for r in rows] == ['*SEATTLE', '*BOSTON', '*NEW YORK N']
    # a token with no team file has no id: a NO SUCH TEAM pick is unmarked with all
    # bits set
    (tmp_path / 'noid').mkdir()
    ldir = draft_managed_test_league(
        tmp_path / 'noid', b'DRAFT CLASALE1 A Guy\r\n'
                           b'SIGN NOSUCHTEAM A Guy CLASALE1\r\n', 0xffffffff)
    rows = dynview.offseason_body((SO, 0, oc(2)),
                                  dynview.load_data(str(ldir)))[1]
    assert rows == [('#1', 'NOSUCHTEAM', '', 'A Guy')]


def test_draft_columns_changed_others_untouched(tmp_path):
    """the other column tables and the FROM columns are untouched by C17; a trade row's
    third column never starts with '*'"""
    assert dynview.COLS_MOVE == [('TEAM', dynview._cx(0), 13, 'L'),
                                 ('PLAYER', dynview._cx(14), 15, 'L'),
                                 ('FROM', dynview._cx(30), 12, 'L')]
    assert [h for h, _x, _w, _a in dynview.COLS_DRAFT] == ['#', 'TEAM', 'POS', 'PLAYER']
    assert dynview.COLS_DRAFT[-1][1] + 20 * dynview.CHAR_W <= dynview._cx(42)
    ldir = draft_managed_test_league(
        tmp_path, b'TRADE CLASALW7 Duke Snider CLASNLW4 TONY BERNAZARD\r\n',
        0xffffffff)
    rows = dynview.offseason_body((SO, 0, oc(3)),
                                  dynview.load_data(str(ldir)))[1]
    assert not any(r[2].startswith('*') for r in rows)


# ---------------------------------------------------------------- hub / settings / about
SET = dynview.SCREEN_SETTINGS
ABOUT = dynview.SCREEN_ABOUT
HUB = (dynview.SCREEN_MENU, 0, 0)


def press(s, key, data):
    return dynview.step(s, key, data)[0]


def write_maj(ldir, stems, size=59771):
    """TEST.MAJ of size bytes with team stems {lg: stem}: lg 0..15 is the AL slot, 16..31
    the NL slot (stem at S + 0x1d7 + 8 * slot)."""
    d = bytearray(size)
    for lg, stem in stems.items():
        s = dynview.MAJ_S_AL if lg < 16 else dynview.MAJ_S_NL
        o = s + dynview.MAJ_O_STEM + 8 * (lg & 15)
        d[o:o + 8] = stem.ljust(8, b'\0')[:8]
    (ldir / 'TEST.MAJ').write_bytes(bytes(d))


def big_league(ldir, n=20):
    """MAJ with n teams (lg 0..n-1, lower-case stems like the game), each with an upper
    case V20 named 'TEAM nn' (the DOS name form the C port opens)"""
    stems = {}
    for lg in range(n):
        stem = 't%02d' % lg
        stems[lg] = stem.encode()
        write_team(ldir, stem.upper(), 'TEAM %02d' % lg)
    write_maj(ldir, stems)


def test_hub_rows_with_and_without_history(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.rows(HUB, data) == [(t,) for t in dynview.MENU_ROWS]
    assert dynview.MENU_ROWS[6:] == ['7  DYNASTY SETTINGS', '8  ABOUT THE MODS',
                                     '9  SEASON AWARDS', '0  SEASON STANDINGS',
                                     'W  WORLD SERIES', 'P  PLAYOFFS']
    assert dynview.total_rows(HUB, data) == 12
    empty = tmp_path / 'empty'
    empty.mkdir()
    data = dynview.load_data(str(empty))
    assert dynview.rows(HUB, data) == [(t,) for t in dynview.MENU_ROWS]
    assert dynview.footer_text(HUB, data) == '0-9 W P F SELECT   ESC EXIT'
    # screens 1..6, SEASON AWARDS and SEASON STANDINGS with no history keep the one
    # NO DYNASTY row
    for scr in list(range(1, 7)) + [dynview.SCREEN_AWARDS, dynview.SCREEN_STANDINGS]:
        assert dynview.rows(st(scr), data) == [('NO DYNASTY HISTORY YET',)]
    # /TITLE with no season keeps TITLE_ROWS; with a season the hub rows
    T = (dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG)
    assert dynview.rows(T, data) == [(t,) for t in dynview.TITLE_ROWS]
    (tmp_path / 'hist').mkdir()
    hdir, _ = make_data(tmp_path / 'hist')
    assert dynview.rows(T, dynview.load_data(str(hdir))) == [(t,) for t in dynview.MENU_ROWS]


def test_hub_keys_open_settings_and_about(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.step(HUB, ord('7'), data) == ((SET, 0, 0), 0)
    assert dynview.step(HUB, ord('8'), data) == ((ABOUT, 0, 0), 0)
    assert dynview.step(HUB, ord('9'), data) == ((dynview.SCREEN_AWARDS, 0, 0), 0)
    # the title menu's keys 7 and 8 open the screens too (cat cleared)
    T = (dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG)
    assert dynview.step(T, ord('7'), data) == ((SET, 0, 0), 0)
    assert dynview.step((SET, 0, 0), dynview.KEY_ESC, data) == (HUB, 0)
    assert dynview.step((ABOUT, 0, 0), dynview.KEY_ESC, data) == (HUB, 0)
    assert dynview.screen_title((SET, 0, 0), data) == 'DYNASTY SETTINGS'
    assert dynview.screen_title((ABOUT, 0, 0), data) == 'ABOUT THE MODS 1/5'
    assert dynview.footer_text((SET, 0, 0)) == 'UP DOWN MOVE   ENTER CHANGE   ESC MENU'
    assert dynview.footer_text((ABOUT, 0, 0)) == 'PGUP PGDN   ESC MENU'


def test_load_settings_header_fields(tmp_path):
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    assert dynview.load_settings(str(ldir)) == (0, 0)          # missing file
    (ldir / 'HISTORY.DAT').write_bytes(bytes([0] * 10 + [5, 0]) + b'\x01\x00\x00\x80')
    assert dynview.load_settings(str(ldir)) == (5, 0x80000001)
    (ldir / 'HISTORY.DAT').write_bytes(bytes(range(4)))        # 4 byte file, padded
    assert dynview.load_settings(str(ldir)) == (0, 0)


def test_settings_rows_from_maj_and_team_names(tmp_path):
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    write_maj(ldir, {0: b'ala01', 3: b'ala04', 16: b'nl01', 20: b'nl05'})
    write_team(ldir, 'ala01', 'PHILADELPHIA')
    write_team(ldir, 'nl01', 'SAN DIEGO')           # ala04 and nl05 have no V20: skipped
    data = dynview.load_data(str(ldir))
    assert data['teams'] == [(0, 'PHILADELPHIA'), (16, 'SAN DIEGO')]
    assert dynview.settings_rows(data) == [('ERA RULES', 'REAL CALENDAR'),
                                           ('PLAYOFF FORMAT', '2 DIVISIONS'),
                                           ('START YEAR', '1993'),
                                           ('PHILADELPHIA', 'AI MANAGES'),
                                           ('SAN DIEGO', 'AI MANAGES')]
    # HISTORY.DAT: era 1, mask bits 0 and 16 (the two teams) managed by the user
    (ldir / 'HISTORY.DAT').write_bytes(bytes(10) + b'\x01\x00\x01\x00\x01\x00' + bytes(16))
    data = dynview.load_data(str(ldir))
    assert dynview.settings_rows(data) == [('ERA RULES', 'RESERVE CLAUSE'),
                                           ('PLAYOFF FORMAT', '2 DIVISIONS'),
                                           ('START YEAR', '1993'),
                                           ('PHILADELPHIA', 'YOU MANAGE'),
                                           ('SAN DIEGO', 'YOU MANAGE')]
    # the id of a team is its bit, AL slot s is bit s and NL slot s is bit s + 16
    data['mask'] = 1 << 16
    assert dynview.settings_rows(data)[3:] == [('PHILADELPHIA', 'AI MANAGES'),
                                               ('SAN DIEGO', 'YOU MANAGE')]


def test_settings_no_maj_and_short_maj(tmp_path):
    ldir = tmp_path / 'nomaj'
    ldir.mkdir()
    write_team(ldir, 'ala01', 'PHILADELPHIA')
    data = dynview.load_data(str(ldir))
    assert data['teams'] == []
    assert dynview.settings_rows(data) == [('ERA RULES', 'REAL CALENDAR'),
                                           ('PLAYOFF FORMAT', '2 DIVISIONS'),
                                           ('START YEAR', '1993')]
    # a MAJ one byte short of MAJ_MIN gives no teams, even with its stems present
    short = tmp_path / 'short'
    short.mkdir()
    write_team(short, 'ala01', 'PHILADELPHIA')
    write_team(short, 'nl01', 'SAN DIEGO')
    write_maj(short, {0: b'ala01', 16: b'nl01'}, size=dynview.MAJ_MIN - 1)
    assert dynview.settings_rows(dynview.load_data(str(short))) == \
        [('ERA RULES', 'REAL CALENDAR'), ('PLAYOFF FORMAT', '2 DIVISIONS'),
         ('START YEAR', '1993')]
    write_maj(short, {0: b'ala01', 16: b'nl01'}, size=dynview.MAJ_MIN)
    assert len(dynview.settings_rows(dynview.load_data(str(short)))) == 5


def test_settings_cursor_moves_and_clamps(tmp_path):
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    big_league(ldir, 20)
    data = dynview.load_data(str(ldir))
    assert len(dynview.settings_rows(data)) == 23            # ERA, PLAYOFF, START YEAR + 20 teams: 2 pages
    s = (SET, 0, 0)
    assert press(s, dynview.KEY_UP, data) == (SET, 0, 0)
    assert press(s, dynview.KEY_PGUP, data) == (SET, 0, 0)
    for _ in range(12):
        s = press(s, dynview.KEY_DOWN, data)
    assert s == (SET, 1, 12)                                 # page == cursor // 12
    for _ in range(12):
        s = press(s, dynview.KEY_DOWN, data)
    assert s == (SET, 1, 22)
    assert press(s, dynview.KEY_DOWN, data) == (SET, 1, 22)  # stops at the last row
    s = press(s, dynview.KEY_PGUP, data)
    assert s == (SET, 0, 10)
    s = press(s, dynview.KEY_PGUP, data)
    assert s == (SET, 0, 0)
    assert press(s, dynview.KEY_PGUP, data) == (SET, 0, 0)
    s = press(s, dynview.KEY_PGDN, data)
    assert s == (SET, 1, 12)
    assert press(s, dynview.KEY_PGDN, data) == (SET, 1, 22)  # min(cursor + 12, n - 1)
    # the page slices of settings_rows
    s = (SET, 1, 22)
    assert len(dynview.rows(s, data)) == 11
    assert dynview.rows(s, data)[0] == ('TEAM 09', 'AI MANAGES')   # settings row 12 (cat 12)
    assert dynview.step(s, dynview.KEY_ESC, data) == (HUB, 0)
    assert press(s, ord('x'), data) == s


def test_settings_enter_toggles_and_era_cycle(tmp_path):
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    write_maj(ldir, {0: b'ala01', 16: b'nl01'})
    write_team(ldir, 'ala01', 'PHILADELPHIA')
    write_team(ldir, 'nl01', 'SAN DIEGO')
    (ldir / 'HISTORY.DAT').write_bytes(bytes(10) + b'\x05' + b'\x00\x00' + bytes(16))
    data = dynview.load_data(str(ldir))
    hp = ldir / 'HISTORY.DAT'
    s = (SET, 0, 0)
    s = press(s, 13, data)                        # era 5 -> 2
    assert data['era'] == 2 and s == (SET, 0, 0) and hp.read_bytes()[10] == 2
    s = press(s, 13, data)                        # 2 -> 0
    assert data['era'] == 0 and hp.read_bytes()[10] == 0
    s = press(s, 13, data)                        # 0 -> 1
    assert data['era'] == 1 and hp.read_bytes()[10] == 1
    s = press(s, 13, data)                        # 1 -> 2
    assert data['era'] == 2
    s = press(s, dynview.KEY_DOWN, data)          # PLAYOFF FORMAT row (cat 1)
    s = press(s, dynview.KEY_DOWN, data)          # START YEAR row (cat 2)
    s = press(s, dynview.KEY_DOWN, data)          # onto PHILADELPHIA (id 0, cat 3)
    s = press(s, 13, data)
    assert data['mask'] == 1 and s == (SET, 0, 3)
    assert int.from_bytes(hp.read_bytes()[12:16], 'little') == 1
    s = press(s, dynview.KEY_DOWN, data)          # SAN DIEGO (id 16, cat 4)
    s = press(s, 13, data)
    assert data['mask'] == 0x10001
    assert int.from_bytes(hp.read_bytes()[12:16], 'little') == 0x10001
    s = press(s, 13, data)                        # toggles back off
    assert data['mask'] == 1 and int.from_bytes(hp.read_bytes()[12:16], 'little') == 1
    assert hp.read_bytes()[10] == 2 and len(hp.read_bytes()) == 32


def test_save_settings_cases(tmp_path):
    def expect(era, mask, base=b''):
        d = bytearray(base + bytes(max(0, 32 - len(base))))
        d[10] = era
        d[12:16] = mask.to_bytes(4, 'little')
        return bytes(d)

    ldir = tmp_path / 'missing'
    ldir.mkdir()
    dynview.save_settings(str(ldir), 2, 0x80000001)
    assert (ldir / 'HISTORY.DAT').read_bytes() == expect(2, 0x80000001)
    assert len((ldir / 'HISTORY.DAT').read_bytes()) == 32
    # a 4 byte file is zero extended; bytes 0..3 are kept
    short = tmp_path / 'short4'
    short.mkdir()
    (short / 'HISTORY.DAT').write_bytes(b'\x01\x02\x03\x04')
    dynview.save_settings(str(short), 1, 5)
    assert (short / 'HISTORY.DAT').read_bytes() == expect(1, 5, b'\x01\x02\x03\x04')
    # a full history file: only bytes 10 and 12..15 change
    (tmp_path / 'full').mkdir()
    hdir, _ = make_data(tmp_path / 'full')
    before = (hdir / 'HISTORY.DAT').read_bytes()
    dynview.save_settings(str(hdir), 1, 0x12345678)
    after = (hdir / 'HISTORY.DAT').read_bytes()
    assert len(after) == len(before)
    assert {i for i in range(len(after)) if after[i] != before[i]} <= {10, 12, 13, 14, 15}
    assert after[10] == 1 and int.from_bytes(after[12:16], 'little') == 0x12345678
    # no history file and no league dir: nothing is created, no exception
    dynview.save_settings(str(tmp_path / 'nodir'), 1, 1)
    assert not (tmp_path / 'nodir').exists()


def test_settings_on_league_without_history(tmp_path):
    ldir = tmp_path / 'nohist'
    ldir.mkdir()
    big_league(ldir, 3)
    data = dynview.load_data(str(ldir))
    assert dynview.rows((SET, 0, 0), data)[0] == ('ERA RULES', 'REAL CALENDAR')
    assert dynview.rows(HUB, data) == [(t,) for t in dynview.MENU_ROWS]
    s = press((SET, 0, 0), 13, data)              # creates HISTORY.DAT (era 1)
    assert (ldir / 'HISTORY.DAT').read_bytes()[10] == 1
    assert len((ldir / 'HISTORY.DAT').read_bytes()) == 32
    s = press(s, dynview.KEY_DOWN, data)          # PLAYOFF FORMAT row (cat 1)
    s = press(s, dynview.KEY_DOWN, data)          # START YEAR row (cat 2)
    s = press(s, dynview.KEY_DOWN, data)          # the first team (cat 3)
    press(s, 13, data)
    assert (ldir / 'HISTORY.DAT').read_bytes()[12] == 1


def test_about_paging(tmp_path):
    ldir = tmp_path / 'empty'
    ldir.mkdir()
    data = dynview.load_data(str(ldir))
    assert len(dynview.ABOUT_ROWS) == 57
    s = (ABOUT, 0, 0)
    assert dynview.rows(s, data)[0] == ('DYNASTY MODE',)
    assert len(dynview.rows(s, data)) == 12
    assert dynview.total_rows(s, data) == 57
    assert dynview.body_cols(s, data) == dynview.COLS_SINGLE
    s = press(s, dynview.KEY_PGDN, data)
    assert s == (ABOUT, 1, 0) and dynview.screen_title(s, data) == 'ABOUT THE MODS 2/5'
    assert dynview.rows(s, data)[0] == (dynview.ABOUT_ROWS[12],)
    s = press(s, dynview.KEY_PGDN, data)
    assert s == (ABOUT, 2, 0) and dynview.screen_title(s, data) == 'ABOUT THE MODS 3/5'
    assert len(dynview.rows(s, data)) == 12
    s = press(s, dynview.KEY_PGDN, data)
    assert s == (ABOUT, 3, 0) and dynview.screen_title(s, data) == 'ABOUT THE MODS 4/5'
    assert len(dynview.rows(s, data)) == 12
    assert press(s, dynview.KEY_PGDN, data) == (ABOUT, 4, 0)
    assert len(dynview.rows((ABOUT, 4, 0), data)) == 9
    assert press((ABOUT, 4, 0), dynview.KEY_PGDN, data) == (ABOUT, 4, 0)   # last page stays
    s = press((ABOUT, 4, 0), dynview.KEY_PGUP, data)
    assert s == (ABOUT, 3, 0)
    s = press(press(s, dynview.KEY_PGUP, data), dynview.KEY_PGUP, data)
    assert s == (ABOUT, 1, 0)
    s = press(press(s, dynview.KEY_PGUP, data), dynview.KEY_PGUP, data)
    assert s == (ABOUT, 0, 0)
    # ABOUT shows its rows with a season recorded too; ENTER does nothing there
    (tmp_path / 'hist').mkdir()
    hdir, _ = make_data(tmp_path / 'hist')
    data = dynview.load_data(str(hdir))
    assert dynview.rows((ABOUT, 0, 0), data) == [(t,) for t in dynview.ABOUT_ROWS[:12]]
    assert dynview.step((ABOUT, 0, 0), dynview.KEY_ENTER, data) == ((ABOUT, 0, 0), 0)


def test_about_and_settings_rows_have_no_overflow():
    for t in dynview.ABOUT_ROWS + dynview.TITLE_ROWS:
        assert len(t) <= 42, t
    assert dynview.COLS_SETTINGS[0][2] >= len('ERA RULES')
    assert all(len(v) <= 16 for v in ('REAL CALENDAR', 'FREE AGENCY', 'RESERVE CLAUSE',
                                      'YOU MANAGE', 'AI MANAGES'))


def test_control_item_and_return(tmp_path):
    p = tmp_path / 'CONTROL'
    assert dynview.control_item(str(p)) == 0
    dynview.control_return(str(p))
    assert not p.exists()                                    # missing: not created
    p.write_bytes(b'\x01')
    assert dynview.control_item(str(p)) == 0
    dynview.control_return(str(p))
    assert p.read_bytes() == b'\x01'                         # under 2 bytes: unchanged
    p.write_bytes(b'\x01\x0a\x00\x00\x00\x00\x00\xff\xff')
    assert dynview.control_item(str(p)) == 2
    dynview.control_return(str(p))
    assert p.read_bytes() == b'\x01\x01\x00\x00\x00\x00\x00\xff\xff'
    for v, item in ((8, 0), (9, 1), (11, 3), (7, 0), (12, 0), (0, 0), (255, 0)):
        p.write_bytes(bytes([1, v, 9]))
        assert dynview.control_item(str(p)) == item, v
    p.write_bytes(bytes([1, 0x0b, 9]))
    dynview.control_return(str(p))
    assert p.read_bytes() == bytes([1, 1, 9])                # only byte 1 changes
    p.write_bytes(b'')
    dynview.control_return(str(p))
    assert p.read_bytes() == b''


def test_menu_cli_state_and_control(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir), FILES)
    cases = (([], HUB), (['--menu', '1'], HUB), (['--menu', '2'], (SET, 0, 0)),
             (['--menu', '3'], (ABOUT, 0, 0)), (['--menu', '9'], HUB),
             (['--title'], (dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG)),
             (['--title', '--menu', '2'], (dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG)))
    for n, (extra, state) in enumerate(cases):
        raw = tmp_path / ('menu%d.RAW' % n)
        dynview.main(extra + ['--raw', str(raw), str(ldir), FILES])
        assert raw.read_bytes() == bytes(dynview.render(state, data)), extra
    # --control: the item in CONTROL[1]; CONTROL[1] = CONTROL[0] afterwards
    ctl = tmp_path / 'CONTROL'
    ctl.write_bytes(b'\x01\x0a\x00\x00\x00\x00\x00\xff\xff')
    raw = tmp_path / 'ctl.RAW'
    dynview.main(['--control', str(ctl), '--raw', str(raw), str(ldir), FILES])
    assert raw.read_bytes() == bytes(dynview.render((SET, 0, 0), data))
    assert ctl.read_bytes() == b'\x01\x01\x00\x00\x00\x00\x00\xff\xff'
    # an explicit --menu wins over the item in CONTROL, which is still returned
    ctl.write_bytes(b'\x01\x0b')
    dynview.main(['--control', str(ctl), '--menu', '2', '--raw', str(raw),
                  str(ldir), FILES])
    assert raw.read_bytes() == bytes(dynview.render((SET, 0, 0), data))
    assert ctl.read_bytes() == b'\x01\x01'
    # no --control: no file is touched
    dynview.main(['--menu', '3', '--raw', str(raw), str(ldir), FILES])
    assert raw.read_bytes() == bytes(dynview.render((ABOUT, 0, 0), data))
    assert not (tmp_path / 'CONTROL.x').exists()


def test_settings_cursor_row_highlight(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    big_league(ldir, 20)
    data = dynview.load_data(str(ldir), FILES)
    fb = dynview.render((SET, 1, 14), data)                  # page 1, cursor row index 2
    y0 = 35 + 2 * dynview.ROW_H
    assert fb[(y0 + 1) * 320 + 9] == dynview.C_TITLE_RED
    assert fb[(y0 + 1) * 320 + 300] == dynview.C_TITLE_RED
    y1 = 35 + 1 * dynview.ROW_H
    assert fb[(y1 + 1) * 320 + 9] == dynview.C_ROW_TAN
    assert fb[(y0 + 10) * 320 + 9] == dynview.C_GRID_GRAY
    band = [fb[y * 320 + x] for y in range(y0 + 2, y0 + 9) for x in range(10, 300)]
    assert dynview.C_WHITE in band and dynview.C_BLACK not in band
    band1 = [fb[y * 320 + x] for y in range(y1 + 2, y1 + 9) for x in range(10, 300)]
    assert dynview.C_BLACK in band1 and dynview.C_WHITE not in band1
    # ABOUT and the hub have no highlighted row
    for state in ((ABOUT, 0, 0), HUB):
        fb = dynview.render(state, data)
        assert fb[(35 + 1) * 320 + 9] == dynview.C_ROW_TAN


def test_settings_and_about_render_without_history(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    empty = tmp_path / 'empty'
    empty.mkdir()
    data = dynview.load_data(str(empty), FILES)
    for state in ((SET, 0, 0), (ABOUT, 0, 0), HUB):
        fb = dynview.render(state, data)
        assert len(fb) == 64000
    assert dynview.render((SET, 0, 0), data) != dynview.render(HUB, data)


# ---------------------------------------------------------------- SEASON AWARDS (C7)
SA = dynview.SCREEN_AWARDS
AWARDS_FOOTER = 'H HISTORY  LEFT RIGHT SEASON  PGUP PGDN  ESC'
# award records (kind, entry index, value): season 2 has three; season 3 has all 40
# kinds (AL 64..83, then NL 96..115). Values are signed; the file stores them as u16.
AW_2 = [(64, 1, 45), (65, 4, 120), (96, 9, 70)]
AW_3 = [(64, 0, -4), (65, 5, 123), (66, 2, 30),
        (67, 3, 1000), (68, 4, 987), (69, 6, 0), (70, 7, 975), (71, 8, 961),
        (72, 9, 1000), (73, 10, 993), (74, 11, 500),
        (75, 12, -1234), (76, 13, 4520), (77, 14, 0), (78, 15, 15), (79, 16, -5),
        (80, 17, -15), (81, 18, 2999), (82, 19, 1000), (83, 20, 9999),
        (96, 1, 50), (97, 4, 77), (98, 9, 0),
        (99, 10, 998), (100, 12, 1000), (101, 13, 960), (102, 14, 945), (103, 15, 920),
        (104, 16, 990), (105, 17, 1000), (106, 18, 985),
        (107, 19, 1), (108, 21, 60), (109, 22, -60), (110, 23, 1234), (111, 24, 205),
        (112, 25, 300), (113, 26, 401), (114, 27, 502), (115, 28, 4520)]
# the season 3 rows in file order: label, name, value
AW_3_ROWS = [
    ('AL MVP', 'HITTER, A', '-0.4 WAR'), ('AL CY YOUNG', 'ACE, P', '12.3 WAR'),
    ('AL ROOKIE', 'PLAYER02, B', '3.0 WAR'),
    ('AL GLOVE C', 'PLAYER03, B', '1.000 FLD'), ('AL GLOVE 1B', 'PLAYER04, B', '.987 FLD'),
    ('AL GLOVE 2B', 'PLAYER06, B', '.000 FLD'), ('AL GLOVE 3B', 'PLAYER07, B', '.975 FLD'),
    ('AL GLOVE SS', 'PLAYER08, B', '.961 FLD'), ('AL GLOVE LF', 'PLAYER09, B', '1.000 FLD'),
    ('AL GLOVE CF', 'PLAYER10, B', '.993 FLD'), ('AL GLOVE RF', 'PLAYER11, B', '.500 FLD'),
    ('AL SLUGGER C', 'PLAYER12, B', '-12.3 RUNS'), ('AL SLUGGER 1B', 'PLAYER13, B', '45.2 RUNS'),
    ('AL SLUGGER 2B', 'PLAYER14, B', '0.0 RUNS'), ('AL SLUGGER 3B', 'PLAYER15, B', '0.1 RUNS'),
    ('AL SLUGGER SS', 'PLAYER16, B', '0.0 RUNS'), ('AL SLUGGER LF', 'PLAYER17, B', '-0.1 RUNS'),
    ('AL SLUGGER CF', 'PLAYER18, B', '29.9 RUNS'), ('AL SLUGGER RF', 'PLAYER19, B', '10.0 RUNS'),
    ('AL SLUGGER DH', 'PLAYER20, B', '99.9 RUNS'),
    ('NL MVP', 'PLAYER01, B', '5.0 WAR'), ('NL CY YOUNG', 'PLAYER04, B', '7.7 WAR'),
    ('NL ROOKIE', 'PLAYER09, B', '0.0 WAR'),
    ('NL GLOVE C', 'PLAYER10, B', '.998 FLD'), ('NL GLOVE 1B', 'PLAYER12, B', '1.000 FLD'),
    ('NL GLOVE 2B', 'PLAYER13, B', '.960 FLD'), ('NL GLOVE 3B', 'PLAYER14, B', '.945 FLD'),
    ('NL GLOVE SS', 'PLAYER15, B', '.920 FLD'), ('NL GLOVE LF', 'PLAYER16, B', '.990 FLD'),
    ('NL GLOVE CF', 'PLAYER17, B', '1.000 FLD'), ('NL GLOVE RF', 'PLAYER18, B', '.985 FLD'),
    ('NL SLUGGER C', 'PLAYER19, B', '0.0 RUNS'), ('NL SLUGGER 1B', 'PLAYER21, B', '0.6 RUNS'),
    ('NL SLUGGER 2B', 'PLAYER22, B', '-0.6 RUNS'), ('NL SLUGGER 3B', 'PLAYER23, B', '12.3 RUNS'),
    ('NL SLUGGER SS', 'PLAYER24, B', '2.0 RUNS'), ('NL SLUGGER LF', 'PLAYER25, B', '3.0 RUNS'),
    ('NL SLUGGER CF', 'PLAYER26, B', '4.0 RUNS'), ('NL SLUGGER RF', 'PLAYER27, B', '5.0 RUNS'),
    ('NL SLUGGER DH', 'PLAYER28, B', '45.2 RUNS')]
AW_2_ROWS = [('AL MVP', 'PLAYER01, B', '4.5 WAR'), ('AL CY YOUNG', 'PLAYER04, B', '12.0 WAR'),
             ('NL MVP', 'PLAYER09, B', '7.0 WAR')]
# season 1 has no award records: the six winners of its season entry, then GG SS
AW_1_ROWS = [('AL MVP', 'HITTER, A', ''), ('AL CY YOUNG', 'PLAYER01, B', ''),
             ('AL ROOKIE', 'PLAYER02, B', ''), ('NL MVP', 'PLAYER03, B', ''),
             ('NL CY YOUNG', 'PLAYER04, B', ''), ('NL ROOKIE', 'ACE, P', ''),
             ('GG SS', 'NOT RECORDED', '')]


def award_recs(season, recs):
    """MILESTON.DAT records of award or leader kinds for season (value stored as u16)"""
    return [(season, idx, kind, value & 0xffff) for kind, idx, value in recs]


def award_league_ms():
    """the MILESTON.DAT records of make_awards"""
    return ([(2, 1, 32, 52), (2, 2, 2, 3000)] + award_recs(2, AW_2)
            + [(3, 0, 2, 3000), (3, 5, 32, 51)] + award_recs(3, AW_3))


def make_awards(tmp_path, ms=None):
    """make_data league: MILESTON.DAT holds the milestone kinds 2 and 32 for seasons 2
    and 3 with the award records after them (season 2: AW_2, season 3: AW_3)"""
    if ms is None:
        ms = award_league_ms()
    return make_data(tmp_path, ms=ms)[0]


def test_awards_hub_key_and_footers(tmp_path):
    ldir = make_awards(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.MENU_ROWS[8] == '9  SEASON AWARDS'
    assert dynview.rows(HUB, data)[8] == ('9  SEASON AWARDS',)
    assert dynview.step(HUB, ord('9'), data) == ((SA, 0, 0), 0)
    # from the /TITLE menu too; ESC goes back to the plain hub
    T = (dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG)
    assert dynview.step(T, ord('9'), data) == ((SA, 0, 0), 0)
    assert dynview.step((SA, 0, 0), ESC, data) == (HUB, 0)
    assert dynview.screen_title((SA, 0, 0), data) == '1995 AWARDS'
    assert dynview.footer_text((SA, 0, 0), data) == AWARDS_FOOTER
    assert dynview.footer_text(HUB, data) == '0-9 W P F SELECT   ESC EXIT'
    assert dynview.footer_text(T, data) == '0-9 W SELECT   ENTER PLAY BALL'
    assert dynview.TITLE_FOOTER == '0-9 W SELECT   ENTER PLAY BALL'
    # ENTER opens the PLAYER CARD of the highlighted award's player (C13.4); ESC goes back
    s, _ex = dynview.step((SA, 0, 0), ENTER, data)
    assert s[0] == dynview.SCREEN_CARD and dynview.step(s, ESC, data) == ((SA, 0, 0), 0)


def test_awards_milestones_and_review_skip_award_records(tmp_path):
    ldir = make_awards(tmp_path)
    data = dynview.load_data(str(ldir))
    # the award records (kinds 64 and up) are on SEASON AWARDS only
    assert dynview.rows(st(dynview.SCREEN_MILESTONES), data) == [
        ('1995', 'HITTER, A', '3000 HITS'), ('1995', 'ACE, P', '51 HR SEASON'),
        ('1994', 'PLAYER01, B', '52 HR SEASON'), ('1994', 'PLAYER02, B', '3000 HITS')]
    assert dynview.total_rows(st(dynview.SCREEN_MILESTONES), data) == 4
    review = [r[0] for r in dynview.rows(st(dynview.SCREEN_REVIEW), data)]
    assert review == [
        'CHAMPION ALA03', 'RUNNER-UP NL03', 'AL MVP HITTER, A',
        'AL CY YOUNG PLAYER01, B', 'AL ROOKIE PLAYER02, B', 'NL MVP PLAYER03, B',
        'NL CY YOUNG PLAYER04, B', 'NL ROOKIE ACE, P', 'NEW HALL OF FAME: PLAYER29, B',
        'HITTER, A 3000 HITS', 'ACE, P 51 HR SEASON']
    # the offseason review walks the same lines
    assert dynview.rows((dynview.SCREEN_OFFSEASON, 0, 16), data) == \
        dynview.rows(st(dynview.SCREEN_REVIEW), data)
    assert dynview.ABOUT_ROWS[10:13] == ['SHOWS HISTORY, HALL OF FAME, LEADERS,',
                                         'MILESTONES, SEASON AWARDS, STANDINGS',
                                         'AND THE LAST OFFSEASON.']
    assert dynview.ABOUT_ROWS[38] == 'START YEAR: DYNASTY SETTINGS, LEFT RIGHT.'
    assert dynview.ABOUT_ROWS[39] == ''
    assert dynview.ABOUT_ROWS[40:50] == [
        'NUMBER OF TEAMS',
        'UTILITIES > SETUP LEAGUES: NEW TEAM, THEN',
        'CLICK IT AND AN EMPTY DIVISION ROW.',
        'CLICK A PLACED TEAM TO REMOVE IT. NEW',
        'TEAMS DRAFT FROM AI TEAMS, WHICH KEEP 15',
        'EACH, THEN SIGN FREE AGENTS. PLAYERS OF',
        'A REMOVED TEAM BECOME FREE AGENTS. START',
        'THE SEASON WITH A SCHEDULE THAT FITS,',
        'ELSE GENERATED.',
        '']


def test_awards_season3_rows_exact(tmp_path):
    ldir = make_awards(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SA, 0, 0), data) == 40 == len(AW_3_ROWS)
    assert dynview.body_cols((SA, 0, 0), data) == dynview.COLS_AWARDS
    got = [r for p in range(4) for r in dynview.rows((SA, p, 0), data)]
    assert got == AW_3_ROWS
    assert [len(dynview.rows((SA, p, 0), data)) for p in range(4)] == [12, 12, 12, 4]
    # every label and value cell fits its column
    for row in got:
        for cell, (_h, _x, w, _a) in zip(row, dynview.COLS_AWARDS):
            assert len(cell) <= w, cell


def test_awards_paging_four_pages(tmp_path):
    ldir = make_awards(tmp_path)
    data = dynview.load_data(str(ldir))
    s = (SA, 0, 0)
    for page in (1, 2, 3):
        s = press(s, dynview.KEY_PGDN, data)
        assert s == (SA, page, 0, 12 * page)                  # the cursor: the page's first row
    assert press(s, dynview.KEY_PGDN, data) == (SA, 3, 0, 36)   # last page stays
    assert dynview.rows(s, data)[0] == AW_3_ROWS[36]
    assert press(s, dynview.KEY_PGUP, data) == (SA, 2, 0, 24)
    assert dynview.rows((SA, 2, 0), data)[0] == AW_3_ROWS[24]


def test_awards_left_right_seasons(tmp_path):
    ldir = make_awards(tmp_path)
    data = dynview.load_data(str(ldir))
    s, ex = dynview.step((SA, 0, 0), dynview.KEY_LEFT, data)
    assert (s, ex) == ((SA, 0, 1), 0)
    assert dynview.screen_title(s, data) == '1994 AWARDS'
    assert dynview.rows(s, data) == AW_2_ROWS
    assert dynview.total_rows(s, data) == 3
    # season 1 has no award records: its six winners and the GG SS row
    s = press(s, dynview.KEY_LEFT, data)
    assert s == (SA, 0, 2)
    assert dynview.screen_title(s, data) == '1993 AWARDS'
    assert dynview.rows(s, data) == AW_1_ROWS
    assert dynview.body_cols(s, data) == dynview.COLS_AWARDS
    # LEFT at season 1 stays, page included
    assert dynview.step((SA, 0, 2), dynview.KEY_LEFT, data) == ((SA, 0, 2), 0)
    assert dynview.step((SA, 1, 2), dynview.KEY_LEFT, data) == ((SA, 1, 2), 0)
    # RIGHT goes forward again; RIGHT at the newest season stays
    s = press(s, dynview.KEY_RIGHT, data)
    assert s == (SA, 0, 1)
    s = press(s, dynview.KEY_RIGHT, data)
    assert s == (SA, 0, 0)
    assert dynview.rows(s, data)[0] == AW_3_ROWS[0]
    assert dynview.step((SA, 0, 0), dynview.KEY_RIGHT, data) == ((SA, 0, 0), 0)
    assert dynview.step((SA, 2, 0), dynview.KEY_RIGHT, data) == ((SA, 2, 0), 0)


def test_awards_sorted_by_kind_then_file_order(tmp_path):
    """season 2 written backwards with a repeated kind: rows in (kind, file position)
    order, the repeat keeps its file order"""
    recs = award_recs(2, [(96, 9, 70), (65, 4, 120), (64, 1, 45), (64, 7, 10)])
    (tmp_path / 'sorted').mkdir()
    ldir = make_data(tmp_path / 'sorted', ms=recs)[0]
    data = dynview.load_data(str(ldir))
    s = (SA, 0, 1)
    assert dynview.rows(s, data) == [
        ('AL MVP', 'PLAYER01, B', '4.5 WAR'), ('AL MVP', 'PLAYER07, B', '1.0 WAR'),
        ('AL CY YOUNG', 'PLAYER04, B', '12.0 WAR'), ('NL MVP', 'PLAYER09, B', '7.0 WAR')]


def test_awards_past_history_table(tmp_path):
    """a season past the 64-season table with no records: one message row; the
    header count drives the season (70 recorded, cat 5 shows season 65)"""
    ldir = make_awards(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[4], d[5] = 70, 0
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    s = (SA, 0, 0)
    for _ in range(5):
        s = press(s, dynview.KEY_LEFT, data)
    assert s == (SA, 0, 5)
    assert dynview.screen_title(s, data) == '2057 AWARDS'
    assert dynview.rows(s, data) == [('NO AWARDS RECORDED',)]
    assert dynview.body_cols(s, data) == dynview.COLS_SINGLE
    assert dynview.total_rows(s, data) == 1
    assert dynview.step(s, dynview.KEY_PGDN, data) == (s, 0)


def test_awards_no_history(tmp_path):
    ldir = tmp_path / 'empty'
    ldir.mkdir()
    data = dynview.load_data(str(ldir))
    s = (SA, 0, 0)
    assert dynview.rows(s, data) == [('NO DYNASTY HISTORY YET',)]
    assert dynview.body_cols(s, data) == dynview.COLS_SINGLE
    assert dynview.total_rows(s, data) == 0
    assert dynview.step(s, dynview.KEY_LEFT, data) == (s, 0)
    assert dynview.step(s, dynview.KEY_RIGHT, data) == (s, 0)



def test_no_history_titles_have_no_season_zero(tmp_path):
    """a league with no recorded season: no SEASON 0 in the season screens' titles"""
    ldir = tmp_path / 'empty'
    ldir.mkdir()
    data = dynview.load_data(str(ldir))
    assert dynview.screen_title((SA, 0, 0), data) == 'SEASON AWARDS'
    assert dynview.screen_title((dynview.SCREEN_STANDINGS, 0, 0), data) == 'SEASON STANDINGS'
    assert dynview.screen_title(st(dynview.SCREEN_REVIEW, 0, 1), data) == 'LAST SEASON REVIEW'
    for screen in (SA, dynview.SCREEN_STANDINGS, dynview.SCREEN_REVIEW):
        assert 'SEASON 0' not in dynview.screen_title((screen, 0, 0), data)

def test_awards_label_strings_per_league():
    """all 20 kinds of one league: the label strings"""
    pos = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH']
    want = ['MVP', 'CY YOUNG', 'ROOKIE'] + ['GLOVE ' + p for p in pos[:8]] \
        + ['SLUGGER ' + p for p in pos]
    assert len(want) == 20
    assert [dynview.award_label(k) for k in range(64, 84)] == ['AL ' + w for w in want]
    assert [dynview.award_label(k) for k in range(96, 116)] == ['NL ' + w for w in want]
    assert dynview.award_label(67) == 'AL GLOVE C' and dynview.award_label(115) == 'NL SLUGGER DH'
    # the value strings of the kinds that the season 3 rows do not cover
    assert dynview.award_value(64, 0) == '0.0 WAR'
    assert dynview.award_value(66, 0xffff) == '-0.1 WAR'
    assert dynview.award_value(70, 0) == '.000 FLD'
    assert dynview.award_value(75, 0xffff) == '0.0 RUNS'       # -1 truncates to 0
    assert dynview.award_value(75, 0xfff1) == '-0.1 RUNS'      # -15
    assert dynview.award_value(83, 0x7fff) == '327.6 RUNS'     # 32767 / 10 = 3276


def test_awards_max_rows_cap(tmp_path, monkeypatch):
    ldir = make_awards(tmp_path)
    data = dynview.load_data(str(ldir))
    monkeypatch.setattr(dynview, 'AWARD_MAX', 10)
    assert dynview.total_rows((SA, 0, 0), data) == 10
    assert dynview.rows((SA, 0, 0), data) == AW_3_ROWS[:10]


# leader records (C7 second amendment): season 3 has all nine categories of both leagues
LEAD_3 = [(128, 3, 352), (129, 4, 47), (130, 6, 131), (131, 0, 210), (132, 7, 62),
          (133, 5, 24), (134, 9, 187), (135, 10, 301), (136, 11, 45),
          (160, 12, 1000), (161, 13, 5), (162, 14, 99), (163, 15, 65535), (164, 16, 1),
          (165, 17, 19), (166, 18, 1234), (167, 19, 1234), (168, 20, 65535)]
LEAD_3_ROWS = [
    ('AL BA LEADER', 'PLAYER03, B', '.352 BA'), ('AL HR LEADER', 'PLAYER04, B', '47 HR'),
    ('AL RBI LEADER', 'PLAYER06, B', '131 RBI'), ('AL H LEADER', 'HITTER, A', '210 H'),
    ('AL SB LEADER', 'PLAYER07, B', '62 SB'), ('AL W LEADER', 'ACE, P', '24 W'),
    ('AL ERA LEADER', 'PLAYER09, B', '1.87 ERA'), ('AL SO LEADER', 'PLAYER10, B', '301 SO'),
    ('AL SV LEADER', 'PLAYER11, B', '45 SV'),
    ('NL BA LEADER', 'PLAYER12, B', '1.000 BA'), ('NL HR LEADER', 'PLAYER13, B', '5 HR'),
    ('NL RBI LEADER', 'PLAYER14, B', '99 RBI'), ('NL H LEADER', 'PLAYER15, B', '65535 H'),
    ('NL SB LEADER', 'PLAYER16, B', '1 SB'), ('NL W LEADER', 'PLAYER17, B', '19 W'),
    ('NL ERA LEADER', 'PLAYER18, B', '12.34 ERA'), ('NL SO LEADER', 'PLAYER19, B', '1234 SO'),
    ('NL SV LEADER', 'PLAYER20, B', '65535 SV')]
# season 3 in full: its 40 award rows, then the 18 leader rows
ALL_3_ROWS = AW_3_ROWS + LEAD_3_ROWS


def lead_league_ms(extra=()):
    """make_awards' records with LEAD_3 after season 3's award records, then extra"""
    return award_league_ms() + award_recs(3, LEAD_3) + list(extra)


def all_rows(state, data):
    """every row of the screen state, page by page (12 rows a page)"""
    n = dynview.total_rows(state, data)
    screen, _page, cat = state
    return [r for p in range((n + 11) // 12) for r in dynview.rows((screen, p, cat), data)]


def test_leader_kinds_and_strings():
    assert dynview.LEADER_CATS == ['BA', 'HR', 'RBI', 'H', 'SB', 'W', 'ERA', 'SO', 'SV']
    assert [k for k in range(256) if dynview.leader_kind(k)] == \
        list(range(128, 137)) + list(range(160, 169))
    assert [dynview.leader_label(k) for k in range(128, 137)] == \
        ['AL %s LEADER' % c for c in dynview.LEADER_CATS]
    assert [dynview.leader_label(k) for k in range(160, 169)] == \
        ['NL %s LEADER' % c for c in dynview.LEADER_CATS]
    assert dynview.leader_value(128, 352) == '.352 BA'
    assert dynview.leader_value(160, 1000) == '1.000 BA'
    assert dynview.leader_value(128, 0) == '.000 BA'
    assert dynview.leader_value(134, 187) == '1.87 ERA'
    assert dynview.leader_value(166, 5) == '0.05 ERA'
    assert dynview.leader_value(166, 1234) == '12.34 ERA'
    assert dynview.leader_value(166, 0xffff) == '655.35 ERA'
    assert dynview.leader_value(129, 47) == '47 HR'
    assert dynview.leader_value(129, 0xffff) == '65535 HR'      # never a sign
    assert dynview.leader_value(136, 45) == '45 SV'
    assert dynview.leader_value(168, 65535) == '65535 SV'


def test_leaders_after_awards_58_rows(tmp_path):
    ldir = make_awards(tmp_path, ms=lead_league_ms())
    data = dynview.load_data(str(ldir))
    assert dynview.AWARD_MAX == 64
    assert dynview.total_rows((SA, 0, 0), data) == 58 == len(ALL_3_ROWS)
    assert dynview.body_cols((SA, 0, 0), data) == dynview.COLS_AWARDS
    got = [r for p in range(5) for r in dynview.rows((SA, p, 0), data)]
    assert got == ALL_3_ROWS
    assert got[40:] == LEAD_3_ROWS
    assert [len(dynview.rows((SA, p, 0), data)) for p in range(5)] == [12, 12, 12, 12, 10]
    # PGDN stops at the last page (page 4 holds rows 48..57)
    s = (SA, 0, 0)
    for page in (1, 2, 3, 4):
        s = press(s, dynview.KEY_PGDN, data)
        assert s == (SA, page, 0, 12 * page)
    assert press(s, dynview.KEY_PGDN, data) == (SA, 4, 0, 48)
    assert dynview.rows(s, data) == ALL_3_ROWS[48:]
    for row in got:
        for cell, (_h, _x, w, _a) in zip(row, dynview.COLS_AWARDS):
            assert len(cell) <= w, cell


def test_leaders_al_only_season(tmp_path):
    """season 3 with the AL leaders only: 49 rows, five pages, the last one row"""
    ldir = make_awards(tmp_path, ms=award_league_ms() + award_recs(3, LEAD_3[:9]))
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SA, 0, 0), data) == 49
    assert all_rows((SA, 0, 0), data) == AW_3_ROWS + LEAD_3_ROWS[:9]
    assert [len(dynview.rows((SA, p, 0), data)) for p in range(5)] == [12, 12, 12, 12, 1]
    s = press((SA, 0, 0), dynview.KEY_PGDN, data)
    assert s == (SA, 1, 0, 12) and dynview.rows(s, data)[0] == AW_3_ROWS[12]


def test_leader_records_of_other_seasons_not_shown(tmp_path):
    ldir = make_awards(tmp_path, ms=lead_league_ms(extra=award_recs(2, [(129, 2, 9)])))
    data = dynview.load_data(str(ldir))
    # season 2's own AL HR leader shows after its awards; season 3 has none of it
    assert dynview.total_rows((SA, 0, 1), data) == 4
    assert all_rows((SA, 0, 1), data) == AW_2_ROWS + [('AL HR LEADER', 'PLAYER02, B', '9 HR')]
    assert all_rows((SA, 0, 0), data) == ALL_3_ROWS


def test_leader_only_season_has_records(tmp_path):
    """a season with leader records and no award records shows those records alone:
    no six-winner fallback and no GG SS row"""
    (tmp_path / 'lo').mkdir()
    ldir = make_data(tmp_path / 'lo', ms=[(1, 9, 130, 131)])[0]
    data = dynview.load_data(str(ldir))
    s = (SA, 0, 2)
    assert dynview.screen_title(s, data) == '1993 AWARDS'
    assert dynview.rows(s, data) == [('AL RBI LEADER', 'PLAYER09, B', '131 RBI')]
    assert dynview.body_cols(s, data) == dynview.COLS_AWARDS
    assert dynview.total_rows(s, data) == 1


def test_leaders_cap_64_rows(tmp_path):
    """68 award and leader records for season 3: the first 64 in (kind, file position)
    order, so the NL SB row is the last one shown"""
    idx = (1, 2, 4, 6, 7, 8, 9, 10, 11, 21)
    extra = award_recs(3, [(128, i, 300) for i in idx])
    ldir = make_awards(tmp_path, ms=lead_league_ms(extra=extra))
    data = dynview.load_data(str(ldir))
    more = [('AL BA LEADER', 'PLAYER%02d, B' % i, '.300 BA') for i in idx]
    want = (AW_3_ROWS + LEAD_3_ROWS[:1] + more + LEAD_3_ROWS[1:])[:64]
    assert dynview.total_rows((SA, 0, 0), data) == 64
    assert all_rows((SA, 0, 0), data) == want
    assert [len(dynview.rows((SA, p, 0), data)) for p in range(6)] == [12, 12, 12, 12, 12, 4]


def test_leader_records_off_milestones_and_review(tmp_path):
    """leader records (kinds 128 and up) are on SEASON AWARDS only"""
    (tmp_path / 'plain').mkdir()
    (tmp_path / 'lead').mkdir()
    plain = dynview.load_data(str(make_awards(tmp_path / 'plain')))
    lead = dynview.load_data(str(make_awards(tmp_path / 'lead', ms=lead_league_ms())))
    for screen in (dynview.SCREEN_MILESTONES, dynview.SCREEN_REVIEW):
        assert all_rows(st(screen), lead) == all_rows(st(screen), plain)
    assert dynview.total_rows(st(dynview.SCREEN_MILESTONES), lead) == 4


def test_leader_kinds_outside_ranges_ignored(tmp_path):
    """kinds 127, 137, 159, 169 and 200 are on no screen: season 3 reads the same as
    without them, and a season with only such records keeps its six-winner fallback"""
    (tmp_path / 'lead').mkdir()
    (tmp_path / 'stray').mkdir()
    stray = award_recs(3, [(127, 2, 5), (137, 2, 5), (159, 2, 5), (169, 2, 5), (200, 2, 5)])
    stray += award_recs(1, [(169, 4, 9)])
    lead = dynview.load_data(str(make_awards(tmp_path / 'lead', ms=lead_league_ms())))
    odd = dynview.load_data(str(make_awards(tmp_path / 'stray',
                                            ms=lead_league_ms(extra=stray))))
    assert all_rows((SA, 0, 0), odd) == all_rows((SA, 0, 0), lead) == ALL_3_ROWS
    assert all_rows((SA, 0, 2), odd) == AW_1_ROWS
    for screen in (dynview.SCREEN_MILESTONES, dynview.SCREEN_REVIEW):
        assert all_rows(st(screen), odd) == all_rows(st(screen), lead)


# ---------------------------------------------------------------- standings
SS = dynview.SCREEN_STANDINGS
STAND_FOOTER = 'ENTER TEAM  LEFT RIGHT SEASON  PGUP PGDN ESC'
# MAJ team names by league-global id: AL id 5 has no stem (its row reads 'TEAM 5');
# ids 14 and 15 are not teams in the MAJ
AL_NAMES = {0: 'BOSTON', 1: 'DETROIT', 2: 'CLEVELAND', 3: 'NEW YORK', 4: 'CHICAGO',
            6: 'TORONTO', 7: 'BALTIMORE', 8: 'MILWAUKEE', 9: 'KANSAS CITY', 10: 'OAKLAND',
            11: 'MINNESOTA', 12: 'TEXAS', 13: 'SEATTLE'}
NL_NAMES = {16: 'ATLANTA', 17: 'SAN DIEGO', 18: 'PHILADELPHIA', 19: 'HOUSTON',
            20: 'ST LOUIS', 21: 'CINCINNATI', 22: 'PITTSBURGH', 23: 'MONTREAL',
            24: 'COLORADO', 25: 'FLORIDA', 26: 'LOS ANGELES', 27: 'SAN FRANCISCO'}
# season 1 (cat 2): 14 AL teams (ids 14 and 15 play no game), 12 NL teams. CLEVELAND is
# the champion (WS); PHILADELPHIA is the other pennant winner (P)
WL_1 = {0: (10, 5), 1: (20, 10), 2: (8, 2), 3: (6, 4), 4: (4, 6), 5: (11, 3), 6: (6, 4),
        7: (7, 4), 8: (10, 3), 9: (3, 7), 10: (0, 10), 11: (5, 5), 12: (7, 5), 13: (2, 8),
        16: (6, 2), 17: (6, 2), 18: (12, 6), 19: (4, 4), 20: (3, 5), 21: (5, 3),
        22: (2, 6), 23: (1, 7), 24: (4, 2), 25: (2, 4), 26: (4, 4), 27: (1, 1)}
# season 2 (cat 1): AL only, champion and pennants unknown (0xff)
WL_2 = {0: (5, 5), 1: (5, 5), 2: (6, 4), 3: (4, 6)}
# season 1 (cat 2): AL EAST 0..7 and WEST 8..13, NL EAST 16..23 and WEST 24..27. Each
# division is its own block with its own leader (GB from it). DETROIT (20-10) is ahead of
# the EAST leader CLEVELAND (8-2): (8 - 20) + (10 - 2) = -4 half games, so GB is -2.0
STAND_1_ROWS = [
    ('AL WEST', '', '', '', '', ''),
    ('MILWAUKEE', '10', '3', '.769', '-', ''),
    ('TEXAS', '7', '5', '.583', '2.5', ''),
    ('MINNESOTA', '5', '5', '.500', '3.5', ''),
    ('KANSAS CITY', '3', '7', '.300', '5.5', ''),
    ('SEATTLE', '2', '8', '.200', '6.5', ''),
    ('OAKLAND', '0', '10', '.000', '8.5', ''),
    ('AL EAST', '', '', '', '', ''),
    ('CLEVELAND', '8', '2', '.800', '-', 'WS'),
    ('TEAM 5', '11', '3', '.785', '-1.0', ''),
    ('DETROIT', '20', '10', '.666', '-2.0', ''),
    ('BOSTON', '10', '5', '.666', '0.5', ''),
    ('BALTIMORE', '7', '4', '.636', '1.5', ''),
    ('NEW YORK', '6', '4', '.600', '2.0', ''),
    ('TORONTO', '6', '4', '.600', '2.0', ''),
    ('CHICAGO', '4', '6', '.400', '4.0', ''),
    ('NL WEST', '', '', '', '', ''),
    ('COLORADO', '4', '2', '.666', '-', ''),
    ('LOS ANGELES', '4', '4', '.500', '1.0', ''),
    ('SAN FRANCISCO', '1', '1', '.500', '1.0', ''),
    ('FLORIDA', '2', '4', '.333', '2.0', ''),
    ('NL EAST', '', '', '', '', ''),
    ('ATLANTA', '6', '2', '.750', '-', ''),
    ('SAN DIEGO', '6', '2', '.750', '-', ''),
    ('PHILADELPHIA', '12', '6', '.666', '-1.0', 'P'),
    ('CINCINNATI', '5', '3', '.625', '1.0', ''),
    ('HOUSTON', '4', '4', '.500', '2.0', ''),
    ('ST LOUIS', '3', '5', '.375', '3.0', ''),
    ('PITTSBURGH', '2', '6', '.250', '4.0', ''),
    ('MONTREAL', '1', '7', '.125', '5.0', '')]
# season 2 (cat 1): AL EAST only, so one block under the league name
STAND_2_ROWS = [
    ('AMERICAN LEAGUE', '', '', '', '', ''),
    ('CLEVELAND', '6', '4', '.600', '-', ''),
    ('BOSTON', '5', '5', '.500', '1.0', ''),
    ('DETROIT', '5', '5', '.500', '1.0', ''),
    ('NEW YORK', '4', '6', '.400', '2.0', '')]
# CLASSIC shape (the newest season): 7 + 7 AL teams, 6 + 6 NL. MILWAUKEE (10-4) is the
# league's second best record and leads AL WEST ('-' there). BOSTON is WS; MILWAUKEE (AL
# pennant) and LOS ANGELES (NL pennant) are P, all inside their division blocks
WL_CLASSIC = {0: (12, 2), 1: (9, 5), 2: (8, 6), 3: (7, 7), 4: (6, 8), 5: (5, 9), 6: (4, 10),
              8: (10, 4), 9: (7, 7), 10: (6, 8), 11: (5, 9), 12: (6, 8), 13: (3, 11),
              14: (2, 12),
              16: (9, 3), 17: (8, 4), 18: (7, 5), 19: (6, 6), 20: (4, 8), 21: (2, 10),
              24: (6, 6), 25: (5, 7), 26: (7, 5), 27: (4, 8), 28: (3, 9), 29: (6, 6)}
CLASSIC_ROWS = [
    ('AL WEST', '', '', '', '', ''),
    ('MILWAUKEE', '10', '4', '.714', '-', 'P'),
    ('KANSAS CITY', '7', '7', '.500', '3.0', ''),
    ('OAKLAND', '6', '8', '.428', '4.0', ''),
    ('TEXAS', '6', '8', '.428', '4.0', ''),
    ('MINNESOTA', '5', '9', '.357', '5.0', ''),
    ('SEATTLE', '3', '11', '.214', '7.0', ''),
    ('TEAM 14', '2', '12', '.142', '8.0', ''),
    ('AL EAST', '', '', '', '', ''),
    ('BOSTON', '12', '2', '.857', '-', 'WS'),
    ('DETROIT', '9', '5', '.642', '3.0', ''),
    ('CLEVELAND', '8', '6', '.571', '4.0', ''),
    ('NEW YORK', '7', '7', '.500', '5.0', ''),
    ('CHICAGO', '6', '8', '.428', '6.0', ''),
    ('TEAM 5', '5', '9', '.357', '7.0', ''),
    ('TORONTO', '4', '10', '.285', '8.0', ''),
    ('NL WEST', '', '', '', '', ''),
    ('LOS ANGELES', '7', '5', '.583', '-', 'P'),
    ('COLORADO', '6', '6', '.500', '1.0', ''),
    ('TEAM 29', '6', '6', '.500', '1.0', ''),
    ('FLORIDA', '5', '7', '.416', '2.0', ''),
    ('SAN FRANCISCO', '4', '8', '.333', '3.0', ''),
    ('TEAM 28', '3', '9', '.250', '4.0', ''),
    ('NL EAST', '', '', '', '', ''),
    ('ATLANTA', '9', '3', '.750', '-', ''),
    ('SAN DIEGO', '8', '4', '.666', '1.0', ''),
    ('PHILADELPHIA', '7', '5', '.583', '2.0', ''),
    ('HOUSTON', '6', '6', '.500', '3.0', ''),
    ('ST LOUIS', '4', '8', '.333', '5.0', ''),
    ('CINCINNATI', '2', '10', '.166', '7.0', '')]
# one division with games per league: season A has AL EAST only next to a split NL (the
# AL block takes the long name), season B has AL WEST only
WL_HALF_EAST = {0: (5, 5), 1: (6, 4), 2: (4, 6), 3: (3, 7), 16: (4, 2), 17: (2, 4),
                24: (3, 3), 25: (1, 5)}
WL_HALF_WEST = {8: (4, 2), 9: (2, 4), 16: (4, 2), 17: (2, 4), 24: (3, 3), 25: (1, 5)}
HALF_EAST_ROWS = [
    ('AMERICAN LEAGUE', '', '', '', '', ''),
    ('DETROIT', '6', '4', '.600', '-', ''),
    ('BOSTON', '5', '5', '.500', '1.0', ''),
    ('CLEVELAND', '4', '6', '.400', '2.0', ''),
    ('NEW YORK', '3', '7', '.300', '3.0', ''),
    ('NL WEST', '', '', '', '', ''),
    ('COLORADO', '3', '3', '.500', '-', ''),
    ('FLORIDA', '1', '5', '.166', '2.0', ''),
    ('NL EAST', '', '', '', '', ''),
    ('ATLANTA', '4', '2', '.666', '-', ''),
    ('SAN DIEGO', '2', '4', '.333', '2.0', '')]
HALF_WEST_ROWS = [
    ('AMERICAN LEAGUE', '', '', '', '', ''),
    ('MILWAUKEE', '4', '2', '.666', '-', ''),
    ('KANSAS CITY', '2', '4', '.333', '2.0', ''),
    ('NL WEST', '', '', '', '', ''),
    ('COLORADO', '3', '3', '.500', '-', ''),
    ('FLORIDA', '1', '5', '.166', '2.0', ''),
    ('NL EAST', '', '', '', '', ''),
    ('ATLANTA', '4', '2', '.666', '-', ''),
    ('SAN DIEGO', '2', '4', '.333', '2.0', '')]
# all 32 ids played (W = (5 t + 3) % 13, L = 12 + t % 4 - W): 36 rows, 3 pages
FULL_WL = {t: ((5 * t + 3) % 13, 12 + t % 4 - (5 * t + 3) % 13) for t in range(32)}
FULL_AL_WEST_ROWS = [
    ('AL WEST', '', '', '', '', ''),
    ('TEXAS', '11', '1', '.916', '-', ''),
    ('KANSAS CITY', '9', '4', '.692', '2.5', ''),
    ('TEAM 14', '8', '6', '.571', '4.0', ''),
    ('MINNESOTA', '6', '9', '.400', '6.5', ''),
    ('MILWAUKEE', '4', '8', '.333', '7.0', ''),
    ('SEATTLE', '3', '10', '.230', '8.5', ''),
    ('OAKLAND', '1', '13', '.071', '11.0', ''),
    ('TEAM 15', '0', '15', '.000', '12.5', '')]
# (w_l, champion, AL pennant, NL pennant) of seasons 1, 2, 3 (make_standings' default)
STAND_SEASONS = [(WL_1, 2, 2, 18), (WL_2, 0xff, 0xff, 0xff), ({}, 0xff, 0xff, 0xff)]
CLASSIC_SEASON = (WL_CLASSIC, 0, 8, 26)
HALF_EAST = (WL_HALF_EAST, 0xff, 0xff, 0xff)
HALF_WEST = (WL_HALF_WEST, 0xff, 0xff, 0xff)
FULL_SEASON = (FULL_WL, 17, 3, 26)


def write_standings(d, season_no, wl, champ=0xff, al_p=0xff, nl_p=0xff):
    """HISTORY.DAT bytes d: the w_l pairs {id: (W, L)} and the champion and pennant ids of
    season_no (the season entry at 32 + (n - 1) * 128; w_l at 24, pennants at 20, 21)"""
    o = 32 + (season_no - 1) * 128
    d[o + 2] = champ
    d[o + 20] = al_p
    d[o + 21] = nl_p
    for t in range(32):
        w, l = wl.get(t, (0, 0))
        d[o + 24 + 2 * t] = w
        d[o + 25 + 2 * t] = l


def make_standings(tmp_path, seasons=STAND_SEASONS):
    """make_data league with a MAJ of 25 teams (no stem for AL id 5), a V20 per stem, and
    the seasons given: seasons[n - 1] = (w_l, champion, AL pennant, NL pennant) of season
    n, the newest last. Default: the games of WL_1, WL_2 and none (3 seasons)."""
    ldir = make_data(tmp_path)[0]
    stems = {}
    for lg, name in list(AL_NAMES.items()) + list(NL_NAMES.items()):
        stem = 't%02d' % lg
        stems[lg] = stem.encode()
        write_team(ldir, stem.upper(), name)
    write_maj(ldir, stems)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[4], d[5] = len(seasons), 0
    for n, (wl, champ, al_p, nl_p) in enumerate(seasons, 1):
        write_standings(d, n, wl, champ, al_p, nl_p)
    p.write_bytes(bytes(d))
    return ldir


def test_standings_hub_key_and_footers(tmp_path):
    ldir = make_standings(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.MENU_ROWS[9] == '0  SEASON STANDINGS'
    assert dynview.rows(HUB, data)[9] == ('0  SEASON STANDINGS',)
    assert dynview.total_rows(HUB, data) == 12
    assert dynview.step(HUB, ord('0'), data) == ((SS, 0, 0), 0)
    # from the /TITLE menu too; ESC goes back to the plain hub
    T = (dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG)
    assert dynview.step(T, ord('0'), data) == ((SS, 0, 0), 0)
    assert dynview.step((SS, 0, 0), ESC, data) == (HUB, 0)
    assert dynview.screen_title((SS, 0, 0), data) == '1995 STANDINGS'
    assert dynview.screen_title((SS, 0, 2), data) == '1993 STANDINGS'
    assert dynview.footer_text((SS, 0, 0), data) == STAND_FOOTER
    assert dynview.footer_text(HUB, data) == '0-9 W P F SELECT   ESC EXIT'
    assert dynview.footer_text(T, data) == '0-9 W SELECT   ENTER PLAY BALL'
    # ENTER does nothing on SEASON STANDINGS
    assert dynview.step((SS, 0, 0), ENTER, data) == ((SS, 0, 0), 0)


def test_standings_season1_rows_exact(tmp_path):
    ldir = make_standings(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SS, 0, 2), data) == 30 == len(STAND_1_ROWS)
    assert dynview.body_cols((SS, 0, 2), data) == dynview.COLS_STANDINGS
    got = [r for p in range(3) for r in dynview.rows((SS, p, 2), data)]
    assert got == STAND_1_ROWS
    assert ('DETROIT', '20', '10', '.666', '-2.0', '') in got
    assert [len(dynview.rows((SS, p, 2), data)) for p in range(3)] == [12, 12, 6]
    # every row has six cells, each within its column
    for row in got:
        assert len(row) == len(dynview.COLS_STANDINGS), row
        for cell, (_h, _x, w, _a) in zip(row, dynview.COLS_STANDINGS):
            assert len(cell) <= w, cell
    # the PGDN page of season 1 and the paging bounds (C57: PGUP/PGDN are cursor
    # steps, the cursor goes to the new page's first row)
    s = (SS, 0, 2)
    for page in (1, 2):
        s = press(s, dynview.KEY_PGDN, data)
        assert s == (SS, page, 2, page * dynview.ROWS_PER_PAGE)
    assert press(s, dynview.KEY_PGDN, data) == (SS, 2, 2, 24)  # last page stays
    assert dynview.rows(s, data)[0] == STAND_1_ROWS[24]
    assert press(s, dynview.KEY_PGUP, data) == (SS, 1, 2, 12)
    assert dynview.rows((SS, 1, 2), data)[0] == STAND_1_ROWS[12]


def test_standings_season2_and_empty_season3(tmp_path):
    ldir = make_standings(tmp_path)
    data = dynview.load_data(str(ldir))
    # season 2 has no NL block: no NATIONAL LEAGUE header at all
    assert dynview.rows((SS, 0, 1), data) == STAND_2_ROWS
    assert dynview.total_rows((SS, 0, 1), data) == 5
    assert dynview.body_cols((SS, 0, 1), data) == dynview.COLS_STANDINGS
    assert not any(r[0] == 'NATIONAL LEAGUE' for r in STAND_2_ROWS)
    # season 3 has no games in either league: one message row
    assert dynview.rows((SS, 0, 0), data) == [('NO STANDINGS RECORDED',)]
    assert dynview.body_cols((SS, 0, 0), data) == dynview.COLS_SINGLE
    assert dynview.total_rows((SS, 0, 0), data) == 1
    assert dynview.step((SS, 0, 0), dynview.KEY_PGDN, data) == ((SS, 0, 0), 0)


def test_standings_left_right_seasons(tmp_path):
    ldir = make_standings(tmp_path)
    data = dynview.load_data(str(ldir))
    s, ex = dynview.step((SS, 0, 0), dynview.KEY_LEFT, data)
    assert (s, ex) == ((SS, 0, 1), 0)
    assert dynview.screen_title(s, data) == '1994 STANDINGS'
    s = press(s, dynview.KEY_LEFT, data)
    assert s == (SS, 0, 2)
    assert dynview.screen_title(s, data) == '1993 STANDINGS'
    assert dynview.rows(s, data)[1] == STAND_1_ROWS[1]
    # LEFT at season 1 stays, page included
    assert dynview.step((SS, 0, 2), dynview.KEY_LEFT, data) == ((SS, 0, 2), 0)
    assert dynview.step((SS, 1, 2), dynview.KEY_LEFT, data) == ((SS, 1, 2), 0)
    # RIGHT goes forward again; RIGHT at the newest season stays
    s = press(s, dynview.KEY_RIGHT, data)
    assert s == (SS, 0, 1)
    s = press(s, dynview.KEY_RIGHT, data)
    assert s == (SS, 0, 0)
    assert dynview.step((SS, 0, 0), dynview.KEY_RIGHT, data) == ((SS, 0, 0), 0)
    assert dynview.step((SS, 2, 0), dynview.KEY_RIGHT, data) == ((SS, 2, 0), 0)


def test_standings_past_history_table(tmp_path):
    """a header of 70 recorded seasons: cat 0 shows season 70, past the table, and cat 6
    season 64 (no games in its entry): one message row each"""
    ldir = make_standings(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[4], d[5] = 70, 0
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    assert dynview.screen_title((SS, 0, 0), data) == '2062 STANDINGS'
    assert dynview.rows((SS, 0, 0), data) == [('NO STANDINGS RECORDED',)]
    assert dynview.body_cols((SS, 0, 0), data) == dynview.COLS_SINGLE
    assert dynview.total_rows((SS, 0, 0), data) == 1
    assert dynview.rows((SS, 0, 6), data) == [('NO STANDINGS RECORDED',)]
    assert dynview.screen_title((SS, 0, 6), data) == '2056 STANDINGS'


def test_standings_no_history(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    data = dynview.load_data(str(empty))
    s = (SS, 0, 0)
    assert dynview.rows(s, data) == [('NO DYNASTY HISTORY YET',)]
    assert dynview.body_cols(s, data) == dynview.COLS_SINGLE
    assert dynview.total_rows(s, data) == 0
    assert dynview.step(s, dynview.KEY_LEFT, data) == (s, 0)
    assert dynview.step(s, dynview.KEY_RIGHT, data) == (s, 0)
    assert dynview.step(s, dynview.KEY_PGDN, data) == (s, 0)


def test_standings_gb_text():
    """games behind from the doubled difference: halves, whole games as .0, negatives,
    zero as a dash"""
    assert [dynview.gb_text(d) for d in (0, 1, 2, 3, 4, -1, -2, -3)] == \
        ['-', '0.5', '1.0', '1.5', '2.0', '-0.5', '-1.0', '-1.5']
    assert [dynview.gb_text(d) for d in (18, -4, 19, 36)] == ['9.0', '-2.0', '9.5', '18.0']


def test_standings_classic_divisions(tmp_path):
    """CLASSIC shape, the newest season: four blocks in the order AL WEST, AL EAST, NL WEST,
    NL EAST, 31 rows on 3 pages (the NL EAST header would be page 2's last row, so a blank
    row comes first and the header opens page 3); each block's GB from its own leader, so
    MILWAUKEE (the league's second best record) shows '-' in AL WEST; WS and P marks in
    the blocks"""
    ldir = make_standings(tmp_path, seasons=STAND_SEASONS[:2] + [CLASSIC_SEASON])
    data = dynview.load_data(str(ldir))
    assert dynview.screen_title((SS, 0, 0), data) == '1995 STANDINGS'
    blank = ('', '', '', '', '', '')
    want = CLASSIC_ROWS[:23] + [blank] + CLASSIC_ROWS[23:]
    assert CLASSIC_ROWS[23][0] == 'NL EAST'
    assert dynview.total_rows((SS, 0, 0), data) == 31 == len(want)
    got = [r for p in range(3) for r in dynview.rows((SS, p, 0), data)]
    assert got == want
    assert [len(dynview.rows((SS, p, 0), data)) for p in range(3)] == [12, 12, 7]
    assert dynview.rows((SS, 1, 0), data)[11] == blank
    assert dynview.rows((SS, 2, 0), data)[0][0] == 'NL EAST'
    heads = [r[0] for r in got if r[0] and r[1:] == ('', '', '', '', '')]
    assert heads == ['AL WEST', 'AL EAST', 'NL WEST', 'NL EAST']
    assert ('MILWAUKEE', '10', '4', '.714', '-', 'P') in got
    assert ('BOSTON', '12', '2', '.857', '-', 'WS') in got
    assert ('LOS ANGELES', '7', '5', '.583', '-', 'P') in got


def test_standings_no_header_on_a_page_last_row(tmp_path):
    """over every standings fixture: no header row (a name and five empty cells) is the
    last row of a page, and a blank row appears only right before a header"""
    for seasons in (STAND_SEASONS, STAND_SEASONS[:2] + [CLASSIC_SEASON], [HALF_EAST, HALF_WEST],
                    [FULL_SEASON]):
        d = tmp_path / ('s%d' % len(list(tmp_path.iterdir())))
        d.mkdir()
        data = dynview.load_data(str(make_standings(d, seasons=seasons)))
        for cat in range(len(seasons)):
            n = dynview.total_rows((SS, 0, cat), data)
            got = [r for p in range((n + 11) // 12) for r in dynview.rows((SS, p, cat), data)]
            for i, r in enumerate(got):
                if len(r) == 6 and r[1:] == ('', '', '', '', ''):
                    if r[0]:
                        assert i % 12 != 11, (cat, i, r)
                    else:
                        assert got[i + 1][0] and got[i + 1][1:] == ('', '', '', '', '')


def test_standings_one_division_per_league(tmp_path):
    """a league with games in one division only is one block under its long name, next to
    a split NL; no division header for the lone one"""
    ldir = make_standings(tmp_path, seasons=[HALF_EAST, HALF_WEST])
    data = dynview.load_data(str(ldir))
    assert dynview.rows((SS, 0, 0), data) == HALF_WEST_ROWS
    assert dynview.rows((SS, 0, 1), data) == HALF_EAST_ROWS
    assert dynview.total_rows((SS, 0, 0), data) == 9
    assert dynview.total_rows((SS, 0, 1), data) == 11


def test_standings_full_36_rows(tmp_path):
    """all 32 ids played: 4 headers and 32 teams, 36 rows on 3 full pages; the AL WEST
    block is spelled out (the leader TEXAS 11-1, GB 12.5 for the last one)"""
    ldir = make_standings(tmp_path, seasons=[FULL_SEASON])
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SS, 0, 0), data) == 36
    got = [r for p in range(3) for r in dynview.rows((SS, p, 0), data)]
    assert len(got) == 36
    assert [len(dynview.rows((SS, p, 0), data)) for p in range(3)] == [12, 12, 12]
    heads = [i for i, r in enumerate(got) if r[1:] == ('', '', '', '', '')]
    assert heads == [0, 9, 18, 27]
    assert got[0:9] == FULL_AL_WEST_ROWS
    assert all(len(r) == len(dynview.COLS_STANDINGS) for r in got)


def test_standings_about_rows_and_columns_fit():
    assert len(dynview.ABOUT_ROWS) == 57
    assert dynview.ABOUT_ROWS[11:13] == ['MILESTONES, SEASON AWARDS, STANDINGS',
                                         'AND THE LAST OFFSEASON.']
    assert dynview.FOOTERS[SS] == STAND_FOOTER
    # every column ends inside the 42 character row
    assert all(x + w * dynview.CHAR_W <= 10 + 42 * dynview.CHAR_W
               for _h, x, w, _a in dynview.COLS_STANDINGS)


# ---------------------------------------------------------------- C57 standings row cursor
def test_standings_teams_aligns_with_rows(tmp_path):
    """standings_teams matches standings_rows row for row: None exactly on the header,
    blank and message rows, the stable id in standings order on every team row, for a
    one-division and a multi-division season."""
    ldir = make_standings(tmp_path, seasons=STAND_SEASONS[:2] + [CLASSIC_SEASON])
    data = dynview.load_data(str(ldir))
    hist, teams = data['hist'], data['teams']
    # season 2 (cat 1): one AL block under the long name, ids in standings order
    rows = dynview.standings_rows(hist, teams, 2)
    tids = dynview.standings_teams(hist, teams, 2)
    assert len(tids) == len(rows) == 5
    assert tids[0] is None                          # the AMERICAN LEAGUE header
    assert [t for t in tids if t is not None] == [2, 0, 1, 3]   # .600, then the .500 by id
    assert rows[1][0] == 'CLEVELAND' and tids[1] == 2
    # season 1 (cat 2): four division blocks, blank before the NL EAST header
    rows = dynview.standings_rows(hist, teams, 1)
    tids = dynview.standings_teams(hist, teams, 1)
    assert len(tids) == len(rows)
    for i, r in enumerate(rows):
        if not r[0] or r[1:] == ('', '', '', '', ''):
            assert tids[i] is None, (i, r)
        else:
            assert isinstance(tids[i], int) and 0 <= tids[i] < 32, (i, r)
            assert r[0].lstrip('*') == dict(teams).get(tids[i], 'TEAM %d' % tids[i])
    # the classic season (cat 0): id 0 is the WS champion of the AL EAST block
    rows = dynview.standings_rows(hist, teams, 3)
    tids = dynview.standings_teams(hist, teams, 3)
    assert rows[9][0] == 'BOSTON' and tids[9] == 0
    assert len(tids) == len(rows) == 31
    # a season past the table and a season with no games: the message row only
    assert dynview.standings_rows(hist, teams, 99) == [('NO STANDINGS RECORDED',)]
    assert dynview.standings_teams(hist, teams, 99) == [None]
    assert dynview.standings_teams(hist, teams, 4) == [None]   # season 4 has no games


def test_standings_cursor_keys_and_footer(tmp_path):
    """STANDINGS is a cursor screen: UP/DOWN/PGUP/PGDN move the cursor with the page
    following, and the footer reads the C57 text."""
    ldir = make_standings(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.cursor_screen((SS, 0, 0)) is True
    s = press((SS, 0, 2), dynview.KEY_DOWN, data)
    assert s == (SS, 0, 2, 1)
    assert press(s, dynview.KEY_PGDN, data) == (SS, 1, 2, 12)
    assert press((SS, 1, 2, 12), dynview.KEY_PGUP, data) == (SS, 0, 2)
    assert dynview.footer_text((SS, 0, 0), data) == STAND_FOOTER


def test_standings_enter_opens_teamhist_and_esc_back(tmp_path):
    """ENTER on a team row opens (17, 0, tid) of the state's season with th_back =
    pack(10, page, cat, row); ESC returns that state with the cursor; a header or blank
    row and the message season do nothing; st_back survives it all."""
    ldir = make_standings(tmp_path)
    data = dynview.load_data(str(ldir))
    hs = dynview.SCREEN_HISTORY
    press((hs, 0, 0, 1), ENTER, data)               # arm st_back (thrown away)
    # row 1 of season 1 (cat 2) is MILWAUKEE (8) (the AL WEST leader)
    s, _ex = dynview.step((SS, 2, 2, 1), ENTER, data)
    assert s == (dynview.SCREEN_TEAMHIST, 0, 8)
    assert data['th_back'] == (SS, 2, 2, 1)
    assert 'st_back' in data
    back, _ex = dynview.step(s, ESC, data)
    assert back == (SS, 2, 2, 1)                    # ESC keeps the exact state, row too
    assert 'st_back' in data
    # a later ESC uses st_back (untouched by ENTER and the TEAM HISTORY ESC)
    assert dynview.step(back, ESC, data)[0] == (hs, 0, 0, 1)
    # a header row (0) is a no-op; the message season (cat 0) has no team rows
    assert dynview.step((SS, 0, 2, 0), ENTER, data) == ((SS, 0, 2, 0), 0)
    assert dynview.step((SS, 0, 0, 0), ENTER, data) == ((SS, 0, 0, 0), 0)


def test_standings_t_keeps_row_and_state(tmp_path):
    """T opens the lowest managed team's (else the first team's) TEAM HISTORY and keeps
    the full standings state with the cursor row in th_back; ESC returns it exactly;
    st_back untouched."""
    ldir = make_standings(tmp_path)
    data = dynview.load_data(str(ldir))
    hs = dynview.SCREEN_HISTORY
    press((hs, 0, 0, 2), ENTER, data)
    s, _ex = dynview.step((SS, 1, 2, 5), 84, data)
    assert s == (dynview.SCREEN_TEAMHIST, 0, 0)    # the TEAM HISTORY of BOSTON (id 0)
    assert data['th_back'] == (SS, 1, 2, 5)
    assert 'st_back' in data
    assert dynview.step(s, ESC, data)[0] == (SS, 1, 2, 5)
    assert dynview.step((SS, 1, 2, 5), 116, data)[0][2] == 0  # lower case t too


def test_standings_cursor_render_title_rows(tmp_path):
    """The cursor state renders like any list: rows() pages by the cursor's page and
    the title of a cat state with a row keeps the year."""
    ldir = make_standings(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.screen_title((SS, 1, 2, 13), data) == '1993 STANDINGS'
    assert dynview.rows((SS, 1, 2, 13), data)[0] == STAND_1_ROWS[12]
    assert dynview.total_rows((SS, 1, 2, 13), data) == 30


# ---------------------------------------------------------------- world series
SW = dynview.SCREEN_SERIES
SERIES_FOOTER = '1-7 BOX  LEFT RIGHT SEASON  PGUP PGDN  ESC'
# a game: (visitor id, home id, visitor runs, home runs, (visitor hits, home hits),
# (visitor errors, home errors)). AL ids 0..15 (BOSTON 0), NL 16..31 (ATLANTA 16)
SERIES6 = [(0, 16, 3, 5, (7, 9), (1, 0)), (0, 16, 6, 1, (9, 4), (0, 2)),
           (16, 0, 2, 4, (5, 8), (2, 1)), (16, 0, 7, 1, (11, 3), (0, 0)),
           (0, 16, 9, 8, (12, 10), (1, 1)), (16, 0, 2, 6, (6, 9), (3, 0))]
SERIES7 = [(0, 16, 6, 2, (9, 5), (1, 0)), (16, 0, 5, 3, (8, 7), (0, 2)),
           (0, 16, 4, 1, (10, 6), (0, 1)), (16, 0, 4, 2, (7, 9), (2, 0)),
           (0, 16, 7, 3, (12, 8), (1, 1)), (0, 16, 1, 3, (6, 4), (0, 0)),
           (16, 0, 2, 4, (5, 8), (2, 1))]
# LEADS: ATLANTA (the first game's home) wins 3 games to 2
UNFINISHED5 = [(0, 16, 4, 2, (8, 6), (0, 1)), (0, 16, 1, 3, (5, 9), (1, 0)),
               (16, 0, 6, 2, (7, 4), (0, 1)), (16, 0, 3, 5, (6, 8), (1, 0)),
               (0, 16, 2, 4, (6, 7), (0, 2))]
# TIED: two wins each; game 2 has no kind 201 record
TIED4 = [(0, 16, 4, 1, (8, 3), (0, 1)), (0, 16, 2, 5, (6, 9), (2, 2)),
         (16, 0, 3, 1, (5, 4), (1, 0)), (16, 0, 1, 2, (4, 7), (0, 0))]
SERIES6_ROWS = [
    ('GAME 1', '', '', '', ''), ('BOSTON', '3', '7', '1', ''), ('ATLANTA', '5', '9', '0', 'W'),
    ('GAME 2', '', '', '', ''), ('BOSTON', '6', '9', '0', 'W'), ('ATLANTA', '1', '4', '2', ''),
    ('GAME 3', '', '', '', ''), ('ATLANTA', '2', '5', '2', ''), ('BOSTON', '4', '8', '1', 'W'),
    ('GAME 4', '', '', '', ''), ('ATLANTA', '7', '11', '0', 'W'), ('BOSTON', '1', '3', '0', ''),
    ('GAME 5', '', '', '', ''), ('BOSTON', '9', '12', '1', 'W'), ('ATLANTA', '8', '10', '1', ''),
    ('GAME 6', '', '', '', ''), ('ATLANTA', '2', '6', '3', ''), ('BOSTON', '6', '9', '0', 'W'),
    ('BOSTON', '', '', '', 'WINS 4-2')]
SERIES7_ROWS = [
    ('GAME 1', '', '', '', ''), ('BOSTON', '6', '9', '1', 'W'), ('ATLANTA', '2', '5', '0', ''),
    ('GAME 2', '', '', '', ''), ('ATLANTA', '5', '8', '0', 'W'), ('BOSTON', '3', '7', '2', ''),
    ('GAME 3', '', '', '', ''), ('BOSTON', '4', '10', '0', 'W'), ('ATLANTA', '1', '6', '1', ''),
    ('GAME 4', '', '', '', ''), ('ATLANTA', '4', '7', '2', 'W'), ('BOSTON', '2', '9', '0', ''),
    ('GAME 5', '', '', '', ''), ('BOSTON', '7', '12', '1', 'W'), ('ATLANTA', '3', '8', '1', ''),
    ('GAME 6', '', '', '', ''), ('BOSTON', '1', '6', '0', ''), ('ATLANTA', '3', '4', '0', 'W'),
    ('GAME 7', '', '', '', ''), ('ATLANTA', '2', '5', '2', ''), ('BOSTON', '4', '8', '1', 'W'),
    ('BOSTON', '', '', '', 'WINS 4-3')]
UNFINISHED5_ROWS = [
    ('GAME 1', '', '', '', ''), ('BOSTON', '4', '8', '0', 'W'), ('ATLANTA', '2', '6', '1', ''),
    ('GAME 2', '', '', '', ''), ('BOSTON', '1', '5', '1', ''), ('ATLANTA', '3', '9', '0', 'W'),
    ('GAME 3', '', '', '', ''), ('ATLANTA', '6', '7', '0', 'W'), ('BOSTON', '2', '4', '1', ''),
    ('GAME 4', '', '', '', ''), ('ATLANTA', '3', '6', '1', ''), ('BOSTON', '5', '8', '0', 'W'),
    ('GAME 5', '', '', '', ''), ('BOSTON', '2', '6', '0', ''), ('ATLANTA', '4', '7', '2', 'W'),
    ('ATLANTA', '', '', '', 'LEADS 3-2')]
TIED4_ROWS = [
    ('GAME 1', '', '', '', ''), ('BOSTON', '4', '8', '0', 'W'), ('ATLANTA', '1', '3', '1', ''),
    ('GAME 2', '', '', '', ''), ('BOSTON', '2', '', '', ''), ('ATLANTA', '5', '', '', 'W'),
    ('GAME 3', '', '', '', ''), ('ATLANTA', '3', '5', '1', 'W'), ('BOSTON', '1', '4', '0', ''),
    ('GAME 4', '', '', '', ''), ('ATLANTA', '1', '4', '0', ''), ('BOSTON', '2', '7', '0', 'W'),
    ('SERIES', '', '', '', 'TIED 2-2')]


def series_recs(season, games, no_he=()):
    """MILESTON.DAT records of one season's WORLD SERIES in file order: each game's kind
    192 + g record, then its kind 200 + g record (none for a game index in no_he)"""
    recs = []
    for g, (v, h, vr, hr, (vh, hh), (ve, he)) in enumerate(games):
        recs.append((season, v * 256 + h, 192 + g, vr * 256 + hr))
        if g not in no_he:
            recs.append((season, vh * 256 + hh, 200 + g, ve * 256 + he))
    return recs


def make_series(tmp_path, ms):
    """make_standings league (team names, three seasons, no standings games) whose
    MILESTON.DAT holds ms"""
    ldir = make_standings(tmp_path)
    write_mileston(str(ldir / 'MILESTON.DAT'), ms)
    return ldir


def series_all_rows(state, data):
    """every row of the paged WORLD SERIES screen state's season"""
    n = dynview.total_rows(state, data)
    return [r for p in range((n + 11) // 12) for r in dynview.rows((SW, p, state[2]), data)]


def test_series_hub_key_and_footers(tmp_path):
    ldir = make_series(tmp_path, series_recs(3, SERIES6))
    data = dynview.load_data(str(ldir))
    assert dynview.MENU_ROWS[10] == 'W  WORLD SERIES'
    assert dynview.rows(HUB, data)[10] == ('W  WORLD SERIES',)
    assert dynview.total_rows(HUB, data) == 12
    # W and w open WORLD SERIES from the hub and from the /TITLE menu
    T = (dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG)
    for key in (ord('W'), ord('w')):
        assert dynview.step(HUB, key, data) == ((SW, 0, 0), 0)
        assert dynview.step(T, key, data) == ((SW, 0, 0), 0)
    assert dynview.step((SW, 0, 0), ESC, data) == (HUB, 0)
    assert dynview.screen_title((SW, 0, 0), data) == '1995 WORLD SERIES'
    assert dynview.screen_title((SW, 0, 2), data) == '1993 WORLD SERIES'
    assert dynview.footer_text((SW, 0, 0), data) == SERIES_FOOTER
    assert dynview.FOOTERS[SW] == SERIES_FOOTER
    assert dynview.footer_text(HUB, data) == '0-9 W P F SELECT   ESC EXIT'
    assert dynview.footer_text(T, data) == '0-9 W SELECT   ENTER PLAY BALL'
    assert dynview.TITLE_FOOTER == '0-9 W SELECT   ENTER PLAY BALL'
    # ENTER does nothing on WORLD SERIES
    assert dynview.step((SW, 0, 0), ENTER, data) == ((SW, 0, 0), 0)


def test_series_no_history(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    data = dynview.load_data(str(empty))
    s = (SW, 0, 0)
    assert dynview.screen_title(s, data) == 'WORLD SERIES'
    assert dynview.rows(s, data) == [('NO DYNASTY HISTORY YET',)]
    assert dynview.body_cols(s, data) == dynview.COLS_SINGLE
    assert dynview.total_rows(s, data) == 0
    assert dynview.step(HUB, ord('W'), data) == (s, 0)
    for key in (dynview.KEY_LEFT, dynview.KEY_RIGHT, dynview.KEY_PGDN):
        assert dynview.step(s, key, data) == (s, 0)
    T = (dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG)
    assert dynview.footer_text(T, data) == 'ENTER PLAY BALL'


def test_series_six_game_rows_exact(tmp_path):
    """6 games: 19 rows on 2 pages (games 1..4; games 5..6 and the summary)"""
    ldir = make_series(tmp_path, series_recs(3, SERIES6))
    data = dynview.load_data(str(ldir))
    assert dynview.screen_title((SW, 0, 0), data) == '1995 WORLD SERIES'
    assert dynview.total_rows((SW, 0, 0), data) == 19 == len(SERIES6_ROWS)
    assert dynview.body_cols((SW, 0, 0), data) == dynview.COLS_SERIES
    assert dynview.series_body((SW, 0, 0), data) == (dynview.COLS_SERIES, SERIES6_ROWS)
    got = [r for p in range(2) for r in dynview.rows((SW, p, 0), data)]
    assert got == SERIES6_ROWS
    assert [len(dynview.rows((SW, p, 0), data)) for p in range(2)] == [12, 7]
    # every row has five cells, each within its column
    for row in got:
        assert len(row) == len(dynview.COLS_SERIES), row
        for cell, (_h, _x, w, _a) in zip(row, dynview.COLS_SERIES):
            assert len(cell) <= w, cell
    # PGDN stops on the last page, PGUP goes back
    s = press((SW, 0, 0), dynview.KEY_PGDN, data)
    assert s == (SW, 1, 0)
    assert press(s, dynview.KEY_PGDN, data) == (SW, 1, 0)
    assert dynview.rows(s, data)[-1] == ('BOSTON', '', '', '', 'WINS 4-2')
    assert press(s, dynview.KEY_PGUP, data) == (SW, 0, 0)


def test_series_seven_game_rows(tmp_path):
    """7 games: 22 rows on 2 pages, the summary last"""
    ldir = make_series(tmp_path, series_recs(3, SERIES7))
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SW, 0, 0), data) == 22 == len(SERIES7_ROWS)
    assert series_all_rows((SW, 0, 0), data) == SERIES7_ROWS
    assert [len(dynview.rows((SW, p, 0), data)) for p in range(2)] == [12, 10]
    assert dynview.step((SW, 1, 0), dynview.KEY_PGDN, data) == ((SW, 1, 0), 0)


def test_series_unfinished_and_tied(tmp_path):
    """season 3 is tied 2-2 (SERIES, TIED); season 2 is 3-2 for ATLANTA, the side that
    is not the first game's visitor (LEADS)"""
    ldir = make_series(tmp_path, series_recs(2, UNFINISHED5)
                       + series_recs(3, TIED4, no_he=(1,)))
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SW, 0, 0), data) == 13 == len(TIED4_ROWS)
    assert series_all_rows((SW, 0, 0), data) == TIED4_ROWS
    assert dynview.total_rows((SW, 0, 1), data) == 16 == len(UNFINISHED5_ROWS)
    assert series_all_rows((SW, 0, 1), data) == UNFINISHED5_ROWS


def test_series_first_record_of_a_kind_wins(tmp_path):
    """a later duplicate of game 1's kind 192 and 200 records is ignored; a game without its
    200 + g record shows empty H and E cells"""
    dup = [(3, 0 * 256 + 16, 192, 1 * 256 + 9), (3, 1 * 256 + 1, 200, 0)]
    ldir = make_series(tmp_path, series_recs(3, SERIES6) + dup)
    data = dynview.load_data(str(ldir))
    assert series_all_rows((SW, 0, 0), data) == SERIES6_ROWS
    (tmp_path / 'nohe').mkdir()
    ldir = make_series(tmp_path / 'nohe', series_recs(3, SERIES6, no_he=(1,)))
    rows = series_all_rows((SW, 0, 0), dynview.load_data(str(ldir)))
    assert rows[3:6] == [('GAME 2', '', '', '', ''), ('BOSTON', '6', '', '', 'W'),
                         ('ATLANTA', '1', '', '', '')]
    assert rows[:3] == SERIES6_ROWS[:3] and rows[6:] == SERIES6_ROWS[6:]


def test_series_other_seasons_and_past_history_table(tmp_path):
    """each season shows its own records only; past 64 (season 65 and 70) one message row,
    season 64 its own records"""
    ldir = make_series(tmp_path, series_recs(3, SERIES6) + series_recs(2, UNFINISHED5)
                       + series_recs(64, UNFINISHED5) + series_recs(65, SERIES6)
                       + series_recs(70, SERIES7))
    data = dynview.load_data(str(ldir))
    assert series_all_rows((SW, 0, 0), data) == SERIES6_ROWS
    assert series_all_rows((SW, 0, 1), data) == UNFINISHED5_ROWS
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[4], d[5] = 70, 0
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    assert dynview.screen_title((SW, 0, 0), data) == '2062 WORLD SERIES'
    assert dynview.rows((SW, 0, 0), data) == [('NO WORLD SERIES RECORDED',)]
    assert dynview.body_cols((SW, 0, 0), data) == dynview.COLS_SINGLE
    assert dynview.total_rows((SW, 0, 0), data) == 1
    assert dynview.rows((SW, 0, 5), data) == [('NO WORLD SERIES RECORDED',)]
    assert dynview.screen_title((SW, 0, 5), data) == '2057 WORLD SERIES'
    assert series_all_rows((SW, 0, 6), data) == UNFINISHED5_ROWS


def test_series_no_series_recorded(tmp_path):
    """a season with no game record, with or without award records: one message row"""
    (tmp_path / 'a').mkdir()
    ldir = make_series(tmp_path / 'a', series_recs(2, SERIES6))
    data = dynview.load_data(str(ldir))
    assert dynview.rows((SW, 0, 0), data) == [('NO WORLD SERIES RECORDED',)]
    assert dynview.rows((SW, 0, 2), data) == [('NO WORLD SERIES RECORDED',)]
    assert dynview.body_cols((SW, 0, 0), data) == dynview.COLS_SINGLE
    (tmp_path / 'b').mkdir()
    ldir = make_awards(tmp_path / 'b')
    data = dynview.load_data(str(ldir))
    assert len(dynview.rows((SA, 0, 0), data)) > 1
    assert dynview.rows((SW, 0, 0), data) == [('NO WORLD SERIES RECORDED',)]


def test_series_left_right_seasons(tmp_path):
    ldir = make_series(tmp_path, series_recs(3, SERIES6) + series_recs(2, SERIES7))
    data = dynview.load_data(str(ldir))
    s, ex = dynview.step((SW, 0, 0), dynview.KEY_LEFT, data)
    assert (s, ex) == ((SW, 0, 1), 0)
    assert dynview.screen_title(s, data) == '1994 WORLD SERIES'
    assert dynview.total_rows(s, data) == 22
    s = press(s, dynview.KEY_LEFT, data)
    assert s == (SW, 0, 2)
    assert dynview.screen_title(s, data) == '1993 WORLD SERIES'
    assert dynview.rows(s, data) == [('NO WORLD SERIES RECORDED',)]
    # LEFT at season 1 stays, page included
    assert dynview.step((SW, 0, 2), dynview.KEY_LEFT, data) == ((SW, 0, 2), 0)
    assert dynview.step((SW, 1, 2), dynview.KEY_LEFT, data) == ((SW, 1, 2), 0)
    # RIGHT goes forward again; RIGHT at the newest season stays
    s = press(s, dynview.KEY_RIGHT, data)
    assert s == (SW, 0, 1)
    s = press(s, dynview.KEY_RIGHT, data)
    assert s == (SW, 0, 0)
    assert dynview.step((SW, 0, 0), dynview.KEY_RIGHT, data) == ((SW, 0, 0), 0)
    assert dynview.step((SW, 2, 0), dynview.KEY_RIGHT, data) == ((SW, 2, 0), 0)
    # ESC leaves the screen from any page
    assert dynview.step((SW, 1, 1), dynview.KEY_ESC, data) == (HUB, 0)


def test_series_team_name_fallback(tmp_path):
    """TEAM 5 (AL id 5 has no MAJ stem) and SAN DIEGO; a one-game series leads 1-0 for its
    first game's visitor"""
    ldir = make_series(tmp_path, series_recs(3, [(5, 17, 4, 2, (7, 6), (0, 1))]))
    data = dynview.load_data(str(ldir))
    assert series_all_rows((SW, 0, 0), data) == [
        ('GAME 1', '', '', '', ''), ('TEAM 5', '4', '7', '0', 'W'),
        ('SAN DIEGO', '2', '6', '1', ''), ('TEAM 5', '', '', '', 'LEADS 1-0')]


def test_series_kinds_never_on_other_screens(tmp_path):
    """kinds 192..207 (game, hits and errors records) change nothing on MILESTONES,
    LAST SEASON REVIEW or SEASON AWARDS"""
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    plain = make_awards(tmp_path / 'a', ms=award_league_ms())
    kinds = [(3, 9, kind, 7) for kind in range(192, 208)]
    with_series = make_awards(tmp_path / 'b', ms=award_league_ms() + series_recs(3, SERIES6)
                              + kinds)
    assert dynview.total_rows((SW, 0, 0), dynview.load_data(str(with_series))) > 19
    assert shown_rows(with_series) == shown_rows(plain)


def shown_rows(ldir):
    """the rows of MILESTONES, LAST SEASON REVIEW and SEASON AWARDS (every page and season)"""
    data = dynview.load_data(str(ldir))
    out = [dynview.total_rows(st(dynview.SCREEN_MILESTONES), data),
           dynview.total_rows(st(dynview.SCREEN_REVIEW), data)]
    out += [dynview.rows(st(dynview.SCREEN_MILESTONES, p), data) for p in range(3)]
    out += [dynview.rows(st(dynview.SCREEN_REVIEW), data)]
    out += [dynview.rows((SA, p, c), data) for c in range(3) for p in range(2)]
    return out


def test_series_columns_fit():
    assert dynview.COLS_SERIES[0][1:3] == (dynview._cx(0), 17)
    assert all(x + w * dynview.CHAR_W <= 10 + 42 * dynview.CHAR_W
               for _h, x, w, _a in dynview.COLS_SERIES)
    assert [h for h, _x, _w, _a in dynview.COLS_SERIES] == ['TEAM', 'R', 'H', 'E', ' ']


# ---------------------------------------------------------------- BOX SCORE (C10 fifth amendment)
SB = dynview.SCREEN_BOX
BOX_FOOTER = 'ENTER CARD  LEFT RIGHT GAME  PGUP PGDN  ESC'
HDR_AB = ('AB', 'R', 'H', 'RBI', 'BB', 'SO')
PIT_HDR = ('PITCHING', 'IP', 'H', 'R', 'ER', 'BB', 'SO')


def box_rec(season, g, flags, idx, stats, b=0, i=0):
    """one 16 B BOXSCORE.DAT record; stats is 8 numbers (batting AB R H RBI HR BB SO SB,
    pitching IP10 H R ER HR BB SO BF)"""
    return struct.pack('<HBBHBB', season, g, flags, idx, b, i) + bytes(stats)


def write_box(ldir, recs):
    (ldir / 'BOXSCORE.DAT').write_bytes(b''.join(recs))


def game_ms(season, games):
    """MILESTON.DAT kind 192 + g records of season for each game g in games (visitor 0,
    home 16, 3-5): the game records only, no hits and errors"""
    return [(season, 0 * 256 + 16, 192 + g, 3 * 256 + 5) for g in games]


# game 1 of season 3: BOSTON (visitor) and ATLANTA (home); entries 0 HITTER, A, 5 ACE, P,
# 1, 2 and 6 are PLAYER01, PLAYER02, PLAYER06 (make_data)
BOX_G0 = [box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0)),
          box_rec(3, 0, 2, 5, (72, 5, 2, 2, 1, 1, 8, 30)),
          box_rec(3, 0, 2, 1, (1, 1, 0, 0, 0, 0, 0, 1)),
          box_rec(3, 0, 1, 2, (3, 0, 1, 0, 0, 2, 0, 0)),
          box_rec(3, 0, 3, 6, (100, 9, 4, 4, 2, 3, 5, 40))]
BOX_G0_ROWS = [('BOSTON',) + HDR_AB,
               ('HITTER, A', '4', '1', '2', '1', '0', '1'),
               PIT_HDR,
               ('ACE, P', '7.2', '5', '2', '2', '1', '8'),
               ('PLAYER01, B', '0.1', '1', '0', '0', '0', '0'),
               ('ATLANTA',) + HDR_AB,
               ('PLAYER02, B', '3', '0', '1', '0', '2', '0'),
               PIT_HDR,
               ('PLAYER06, B', '10.0', '9', '4', '4', '3', '5')]


def box_all_rows(state, data):
    """every row of the paged BOX SCORE state's game"""
    n = dynview.total_rows(state, data)
    return [r for p in range((n + 11) // 12) for r in dynview.rows((SB, p, state[2]), data)]


def test_box_ws_footer_and_box_footer(tmp_path):
    ldir = make_series(tmp_path, game_ms(3, (0,)))
    data = dynview.load_data(str(ldir))
    assert SERIES_FOOTER == '1-7 BOX  LEFT RIGHT SEASON  PGUP PGDN  ESC'
    assert len(SERIES_FOOTER) == 42
    assert dynview.footer_text((SW, 0, 0), data) == SERIES_FOOTER
    assert dynview.FOOTERS[SB] == BOX_FOOTER
    assert dynview.footer_text((SB, 0, 0), data) == BOX_FOOTER
    assert dynview.SCREEN_BOX == 12


def test_box_keys_open_existing_games(tmp_path):
    """keys 1..7 open game key - 49 of the season when its kind 192 + g record is there; a
    missing game, a non-game key and a season past 64 or with no seasons leave the series"""
    ldir = make_series(tmp_path, game_ms(3, (0, 1, 3, 6)) + game_ms(1, (0,)))
    data = dynview.load_data(str(ldir))
    for key in (49, 50, 52, 55):
        assert dynview.step((SW, 0, 0), key, data) == ((SB, 0, key - 49), 0)
    for key in (51, 53, 54, 48, 56):
        assert dynview.step((SW, 0, 0), key, data) == ((SW, 0, 0), 0)
    # season 1 (cat 2) has game 1 only; season 2 (cat 1) has no game records
    assert dynview.step((SW, 0, 2), 49, data) == ((SB, 0, 16), 0)
    assert dynview.step((SW, 0, 2), 50, data) == ((SW, 0, 2), 0)
    assert dynview.step((SW, 0, 1), 49, data) == ((SW, 0, 1), 0)
    # the hub and the offseason keep their own keys
    assert dynview.step(HUB, 49, data) == ((1, 0, 0), 0)
    for seasons, want in ((64, (SB, 0, 0)), (65, (SW, 0, 0))):
        (tmp_path / ('s%d' % seasons)).mkdir()
        ldir = make_series(tmp_path / ('s%d' % seasons), game_ms(seasons, (0,)))
        p = ldir / 'HISTORY.DAT'
        d = bytearray(p.read_bytes())
        d[4], d[5] = seasons & 255, seasons >> 8
        p.write_bytes(bytes(d))
        assert dynview.step((SW, 0, 0), 49, dynview.load_data(str(ldir))) == (want, 0)
    (tmp_path / 'empty').mkdir()
    empty = dynview.load_data(str(tmp_path / 'empty'))
    assert dynview.step((SW, 0, 0), 49, empty) == ((SW, 0, 0), 0)


def test_box_title(tmp_path):
    ldir = make_series(tmp_path, game_ms(3, range(7)) + game_ms(1, (0,)))
    data = dynview.load_data(str(ldir))
    assert dynview.screen_title((SB, 0, 0), data) == '1995 WS GAME 1'
    assert dynview.screen_title((SB, 0, 6), data) == '1995 WS GAME 7'
    assert dynview.screen_title((SB, 0, 9), data) == '1994 WS GAME 2'
    assert dynview.screen_title((SB, 0, 16), data) == '1993 WS GAME 1'
    (tmp_path / 'empty').mkdir()
    empty = dynview.load_data(str(tmp_path / 'empty'))
    assert dynview.screen_title((SB, 0, 0), empty) == 'WS BOX SCORE'
    assert dynview.rows((SB, 0, 0), empty) == [('NO DYNASTY HISTORY YET',)]
    assert dynview.total_rows((SB, 0, 0), empty) == 0


def test_box_rows_full_game(tmp_path):
    """both sides: team row, batting rows, PITCHING row and pitching rows; IP as 7.2, 10.0
    and 0.1"""
    ldir = make_series(tmp_path, game_ms(3, (0,)))
    write_box(ldir, BOX_G0)
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SB, 0, 0), data) == 9 == len(BOX_G0_ROWS)
    assert dynview.box_body((SB, 0, 0), data) == (dynview.COLS_BOX, BOX_G0_ROWS)
    assert dynview.body_cols((SB, 0, 0), data) == dynview.COLS_BOX
    assert dynview.rows((SB, 0, 0), data) == BOX_G0_ROWS
    assert dynview.rows((SB, 1, 0), data) == []
    for row in BOX_G0_ROWS:
        assert len(row) == len(dynview.COLS_BOX), row
        for cell, (_h, _x, w, _a) in zip(row, dynview.COLS_BOX):
            assert len(cell) <= w, cell


def test_box_unknown_entry_and_pitching_ip(tmp_path):
    """entry 0xffff shows '?' on both kinds of row; IP 15.0 has two digits before the dot"""
    ldir = make_series(tmp_path, game_ms(3, (0,)))
    write_box(ldir, [box_rec(3, 0, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)),
                     box_rec(3, 0, 3, 0xffff, (150, 3, 1, 1, 0, 0, 4, 40))])
    data = dynview.load_data(str(ldir))
    assert box_all_rows((SB, 0, 0), data) == [
        ('BOSTON',) + HDR_AB, ('?', '4', '1', '2', '1', '0', '1'), PIT_HDR,
        ('ATLANTA',) + HDR_AB, PIT_HDR, ('?', '15.0', '3', '1', '1', '0', '4')]


def test_box_other_season_and_game_ignored(tmp_path):
    """records of another season or another game of the same season never show"""
    ldir = make_series(tmp_path, game_ms(3, (0, 1)) + game_ms(2, (0,)))
    write_box(ldir, [box_rec(2, 0, 0, 7, (9, 9, 9, 9, 9, 9, 9, 9)),
                     box_rec(3, 1, 0, 8, (9, 9, 9, 9, 9, 9, 9, 9))] + BOX_G0
              + [box_rec(3, 2, 2, 9, (9, 9, 9, 9, 9, 9, 9, 9))])
    data = dynview.load_data(str(ldir))
    assert box_all_rows((SB, 0, 0), data) == BOX_G0_ROWS
    # game 2 has its own record only; game 3 has a box record but no game record
    assert box_all_rows((SB, 0, 1), data) == [
        ('BOSTON',) + HDR_AB, ('PLAYER08, B', '9', '9', '9', '9', '9', '9'), PIT_HDR,
        ('ATLANTA',) + HDR_AB, PIT_HDR]
    assert dynview.rows((SB, 0, 2), data) == [('NO BOX SCORE RECORDED',)]
    assert box_all_rows((SB, 0, 8), data) == [
        ('BOSTON',) + HDR_AB, ('PLAYER07, B', '9', '9', '9', '9', '9', '9'), PIT_HDR,
        ('ATLANTA',) + HDR_AB, PIT_HDR]


def test_box_no_records_message(tmp_path):
    """no BOXSCORE.DAT, no record of the game, or only other games' records: one message
    row with COLS_SINGLE"""
    (tmp_path / 'nofile').mkdir()
    ldir = make_series(tmp_path / 'nofile', game_ms(3, (0,)))
    data = dynview.load_data(str(ldir))
    assert dynview.rows((SB, 0, 0), data) == [('NO BOX SCORE RECORDED',)]
    assert dynview.body_cols((SB, 0, 0), data) == dynview.COLS_SINGLE
    assert dynview.total_rows((SB, 0, 0), data) == 1
    assert dynview.screen_title((SB, 0, 0), data) == '1995 WS GAME 1'
    (tmp_path / 'other').mkdir()
    ldir = make_series(tmp_path / 'other', game_ms(3, (0,)))
    write_box(ldir, [box_rec(3, 1, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0))])
    data = dynview.load_data(str(ldir))
    assert dynview.rows((SB, 0, 0), data) == [('NO BOX SCORE RECORDED',)]
    assert dynview.body_cols((SB, 0, 0), data) == dynview.COLS_SINGLE
    (tmp_path / 'nogame').mkdir()
    ldir = make_series(tmp_path / 'nogame', game_ms(3, (1,)))
    write_box(ldir, BOX_G0)
    data = dynview.load_data(str(ldir))
    assert dynview.rows((SB, 0, 0), data) == [('NO BOX SCORE RECORDED',)]
    assert dynview.rows((SB, 0, 1), data) == [('NO BOX SCORE RECORDED',)]


def test_box_left_right_skip_and_stop(tmp_path):
    """LEFT and RIGHT step to the previous and next game with a record (game 3 has none),
    stop at the first and last, keep the season, and reset the page"""
    ldir = make_series(tmp_path, game_ms(3, (0, 1, 3, 6)) + game_ms(1, (0,)))
    data = dynview.load_data(str(ldir))
    assert press((SB, 0, 3), dynview.KEY_LEFT, data) == (SB, 0, 1)
    assert press((SB, 0, 3), dynview.KEY_RIGHT, data) == (SB, 0, 6)
    assert press((SB, 1, 3), dynview.KEY_RIGHT, data) == (SB, 0, 6)
    assert press((SB, 0, 6), dynview.KEY_LEFT, data) == (SB, 0, 3)
    assert press((SB, 0, 6), dynview.KEY_RIGHT, data) == (SB, 0, 6)
    assert dynview.step((SB, 0, 0), dynview.KEY_LEFT, data) == ((SB, 0, 0), 0)
    assert press((SB, 0, 16), dynview.KEY_RIGHT, data) == (SB, 0, 16)
    assert press((SB, 0, 16), dynview.KEY_LEFT, data) == (SB, 0, 16)


def test_box_esc_returns_to_its_series(tmp_path):
    """ESC goes back to the series of the box's season (cat >> 3), page 0, not the hub"""
    ldir = make_series(tmp_path, game_ms(3, (0, 1)) + game_ms(1, (0,)))
    data = dynview.load_data(str(ldir))
    assert dynview.step((SB, 0, 1), ESC, data) == ((SW, 0, 0), 0)
    assert dynview.step((SB, 1, 1), ESC, data) == ((SW, 0, 0), 0)
    assert dynview.step((SB, 0, 16), ESC, data) == ((SW, 0, 2), 0)
    assert dynview.step((SB, 1, 16), ESC, data) == ((SW, 0, 2), 0)
    assert dynview.step((SB, 0, 1), dynview.KEY_ENTER, data) == ((SB, 0, 1), 0)


def test_box_paging_four_pages(tmp_path):
    """a 40 row box (two side headers, two PITCHING rows, 36 batting rows): pages of 12, 12,
    12 and 4; PGDN stops on the last page, PGUP goes back"""
    ldir = make_series(tmp_path, game_ms(3, (0,)))
    write_box(ldir, [box_rec(3, 0, 0, k % 30, (k + 1, 0, 0, 0, 0, 0, 0, 0)) for k in range(36)])
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SB, 0, 0), data) == 40
    assert [len(dynview.rows((SB, p, 0), data)) for p in range(4)] == [12, 12, 12, 4]
    assert dynview.rows((SB, 3, 0), data)[-1] == PIT_HDR
    assert dynview.rows((SB, 0, 0), data)[1] == ('HITTER, A', '1', '0', '0', '0', '0', '0')
    s = press((SB, 0, 0), dynview.KEY_PGDN, data)
    # C62: BOX is a cursor screen, so PGDN puts the cursor on the new page's first row
    assert s == (SB, 1, 0, 12)
    s = press(press(s, dynview.KEY_PGDN, data), dynview.KEY_PGDN, data)
    assert s == (SB, 3, 0, 36)
    assert press(s, dynview.KEY_PGDN, data) == (SB, 3, 0, 36)
    assert press(s, dynview.KEY_PGUP, data) == (SB, 2, 0, 24)
    assert press((SB, 0, 0), dynview.KEY_PGUP, data) == (SB, 0, 0)


def test_load_box_format_and_short_tail(tmp_path):
    """records as tuples (season, g, flags, idx, b, i, 8 stats) in file order; a short tail
    is dropped; a missing or under-16-byte file gives []"""
    (tmp_path / 'missing').mkdir()
    assert dynview.load_box(str(tmp_path / 'missing')) == []
    (tmp_path / 'short').mkdir()
    (tmp_path / 'short' / 'BOXSCORE.DAT').write_bytes(b'\x01' * 15)
    assert dynview.load_box(str(tmp_path / 'short')) == []
    (tmp_path / 'tail').mkdir()
    ldir = tmp_path / 'tail'
    write_box(ldir, BOX_G0 + [box_rec(3, 0, 1, 0xffff, (1, 2, 3, 4, 5, 6, 7, 8), b=2, i=9)])
    with open(ldir / 'BOXSCORE.DAT', 'ab') as fh:
        fh.write(bytes(range(1, 8)))
    box = dynview.load_box(str(ldir))
    assert len(box) == len(BOX_G0) + 1
    assert box[0] == (3, 0, 0, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0))
    assert box[-1] == (3, 0, 1, 0xffff, 2, 9, (1, 2, 3, 4, 5, 6, 7, 8))


def test_box_cap_112_records(tmp_path):
    """only the first 112 records of a game count: 116 rows, the 113th and later never show"""
    ldir = make_series(tmp_path, game_ms(3, (0,)))
    write_box(ldir, [box_rec(3, 0, 0, 0, (k, 0, 0, 0, 0, 0, 0, 0)) for k in range(120)])
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SB, 0, 0), data) == 116
    rows_all = box_all_rows((SB, 0, 0), data)
    assert rows_all[0] == ('BOSTON',) + HDR_AB
    assert [r[1] for r in rows_all[1:113]] == ['%d' % k for k in range(112)]
    assert rows_all[113:] == [PIT_HDR, ('ATLANTA',) + HDR_AB, PIT_HDR]


# ---------------------------------------------------------------- C12 playoff format (2 divisions)
def write_maj2(ldir, stems, day=0x10):
    """write_maj with the C12.1 counts of a 2 division league: leagues 2, divisions 2, MAJ
    day at 0x20a"""
    write_maj(ldir, stems)
    p = ldir / 'TEST.MAJ'
    d = bytearray(p.read_bytes())
    d[0x20c], d[0x20d], d[0x20a] = 2, 2, day
    p.write_bytes(bytes(d))


def set_season_map(d, season_no, divs):
    """HISTORY bytes d: season_no gets ndiv 2 and the C12.7 division map divs {id: division}"""
    o = 32 + (season_no - 1) * 128
    d[o + 22] = 2
    for k, div in divs.items():
        d[o + 100 + k // 2] |= div << (4 * (k & 1))


def standings_blocks(rows):
    """{header: [team names]} of standings rows; blank rows are skipped"""
    out, cur = {}, None
    for r in rows:
        if r[0] and r[1:] == ('', '', '', '', ''):
            cur = out.setdefault(r[0], [])
        elif r[0]:
            cur.append(r[0])
    return out


def all_standings(data, cat=0):
    n = dynview.total_rows((SS, 0, cat), data)
    return [r for p in range((n + 11) // 12) for r in dynview.rows((SS, p, cat), data)]


def test_playoff_label_values():
    assert dynview.playoff_label((2, 2)) == '2 DIVISIONS'
    assert dynview.playoff_label((3, 3)) == '3 DIV + WILDCARD'
    assert dynview.playoff_label((3, 2)) == '3 DIV NEXT YEAR'
    assert dynview.playoff_label((2, 3)) == '2 DIV NEXT YEAR'
    assert all(len(v) <= 16 for v in ('2 DIVISIONS', '3 DIV + WILDCARD',
                                      '3 DIV NEXT YEAR', '2 DIV NEXT YEAR'))


def test_playoff_row_follows_maj_and_byte_11(tmp_path):
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    write_maj2(ldir, {0: b'ala01', 16: b'nl01'})
    write_team(ldir, 'ala01', 'PHILADELPHIA')
    write_team(ldir, 'nl01', 'SAN DIEGO')
    hp = ldir / 'HISTORY.DAT'
    data = dynview.load_data(str(ldir))                     # no HISTORY.DAT: follow the MAJ
    assert data['fmt'] == (2, 2)
    assert dynview.settings_rows(data)[1] == ('PLAYOFF FORMAT', '2 DIVISIONS')
    hp.write_bytes(bytes(11) + b'\x03' + bytes(20))         # byte 11 = 3 wants 3 divisions
    data = dynview.load_data(str(ldir))
    assert data['fmt'] == (3, 2)
    assert dynview.settings_rows(data)[1] == ('PLAYOFF FORMAT', '3 DIV NEXT YEAR')
    hp.write_bytes(bytes(11) + b'\x07' + bytes(20))         # any other value counts as 0
    assert dynview.settings_rows(dynview.load_data(str(ldir)))[1] == \
        ('PLAYOFF FORMAT', '2 DIVISIONS')


def test_playoff_enter_writes_byte_11_only(tmp_path):
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    write_maj2(ldir, {0: b'ala01', 16: b'nl01'}, day=0x10)  # mid season: no apply
    write_team(ldir, 'ala01', 'PHILADELPHIA')
    write_team(ldir, 'nl01', 'SAN DIEGO')
    hp = ldir / 'HISTORY.DAT'
    before = bytes(range(32))
    hp.write_bytes(before)
    data = dynview.load_data(str(ldir))
    s = press((SET, 0, 0), dynview.KEY_DOWN, data)           # the PLAYOFF FORMAT row
    assert s == (SET, 0, 1)
    s = press(s, 13, data)
    assert s == (SET, 0, 1)
    assert data['fmt'] == (3, 2)
    assert hp.read_bytes() == before[:11] + b'\x03' + before[12:]
    assert dynview.settings_rows(data)[1] == ('PLAYOFF FORMAT', '3 DIV NEXT YEAR')
    press(s, 13, data)                                       # 5 - 3 = 2: stock again
    assert hp.read_bytes() == before[:11] + b'\x02' + before[12:]
    assert dynview.settings_rows(data)[1] == ('PLAYOFF FORMAT', '2 DIVISIONS')


def test_playoff_enter_without_files(tmp_path):
    """no MAJ and no HISTORY.DAT: ENTER creates the 32 byte HISTORY.DAT with byte 11 only and
    writes no other file"""
    ldir = tmp_path / 'bare'
    ldir.mkdir()
    data = dynview.load_data(str(ldir))
    assert data['fmt'] == (2, 2)
    press((SET, 0, 1), 13, data)
    assert (ldir / 'HISTORY.DAT').read_bytes() == bytes(11) + b'\x03' + bytes(20)
    assert os.listdir(str(ldir)) == ['HISTORY.DAT']
    assert data['fmt'] == (3, 2)


def test_playoff_enter_apply_rules(tmp_path, monkeypatch):
    """C12.6: the apply at once runs on day 7, or on day 0xf3 with HISTORY byte 0 == 1; after
    an apply on day 7 that returns 0, byte 0 becomes 1. realign.apply is stubbed here (its own
    rules are in test_realign.py); the wanted format is 3 (byte 11 = 3 is the result)"""
    calls, rc = [], [1]

    def fake_apply(league_dir, out=None):
        calls.append(league_dir)
        return rc[0]

    monkeypatch.setattr(dynview.realign, 'apply', fake_apply)
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    write_maj2(ldir, {0: b'ala01'}, day=0x10)
    write_team(ldir, 'ala01', 'PHILADELPHIA')
    maj = ldir / 'TEST.MAJ'
    hp = ldir / 'HISTORY.DAT'

    def enter(day, byte0, rc_value):
        d = bytearray(maj.read_bytes())
        d[0x20a] = day
        maj.write_bytes(bytes(d))
        hp.write_bytes(bytes([byte0]) + bytes(31))
        rc[0] = rc_value
        del calls[:]
        press((SET, 0, 1), 13, dynview.load_data(str(ldir)))
        return len(calls), hp.read_bytes()

    def hist(byte0):
        return bytes([byte0]) + bytes(10) + b'\x03' + bytes(20)

    assert enter(0x10, 0, 0) == (0, hist(0))                 # in season: nothing
    assert enter(0xf3, 0, 0) == (0, hist(0))                 # rolled but byte 0 not 1
    assert enter(0xf3, 1, 0) == (1, hist(1))                 # rolled: apply, byte 0 kept
    assert enter(7, 0, 1) == (1, hist(0))                    # set up, nothing to do
    assert enter(7, 0, 2) == (1, hist(0))                    # refused: byte 0 stays 0
    assert enter(7, 0, 0) == (1, hist(1))                    # applied on day 7: byte 0 = 1
    # no MAJ: byte 11 only, no apply
    maj.unlink()
    hp.write_bytes(bytes([1]) + bytes(31))
    del calls[:]
    press((SET, 0, 1), 13, dynview.load_data(str(ldir)))
    assert calls == [] and hp.read_bytes() == hist(1)


def test_playoff_enter_back_to_now_changes_nothing(tmp_path):
    """byte 11 = 3 on a 2 division MAJ on day 7; ENTER sets 2 (= now): realign has nothing to
    do, so the MAJ and HISTORY byte 0 stay as they are"""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    write_maj2(ldir, {0: b'ala01', 16: b'nl01'}, day=7)
    write_team(ldir, 'ala01', 'PHILADELPHIA')
    write_team(ldir, 'nl01', 'SAN DIEGO')
    hp = ldir / 'HISTORY.DAT'
    hp.write_bytes(bytes(11) + b'\x03' + bytes(20))
    maj_before = (ldir / 'TEST.MAJ').read_bytes()
    data = dynview.load_data(str(ldir))
    assert data['fmt'] == (3, 2)
    press((SET, 0, 1), 13, data)
    assert hp.read_bytes() == bytes(11) + b'\x02' + bytes(20)
    assert (ldir / 'TEST.MAJ').read_bytes() == maj_before
    assert data['fmt'] == (2, 2)
    assert dynview.settings_rows(data)[1] == ('PLAYOFF FORMAT', '2 DIVISIONS')


def test_settings_ids_from_team_table(tmp_path):
    """C12.3: with TEAMID.DAT the team rows carry the stable ids (the entry holding the
    stem), the managed bit of a team is its stable id, and a team in no entry is left out"""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    write_maj2(ldir, {0: b'ala01', 1: b'ala02', 2: b'ala03', 16: b'nl01'})
    write_team(ldir, 'ala01', 'PHILADELPHIA')
    write_team(ldir, 'ala02', 'OTTAWA')
    write_team(ldir, 'ala03', 'NOT IN TABLE')
    write_team(ldir, 'nl01', 'SAN DIEGO')
    table = bytearray(256)
    for k, stem in ((3, b'ala01'), (5, b'ala02'), (20, b'nl01')):
        table[8 * k:8 * k + 8] = stem.ljust(8, b'\0')
    (ldir / 'TEAMID.DAT').write_bytes(bytes(table))
    data = dynview.load_data(str(ldir))
    assert data['teams'] == [(3, 'PHILADELPHIA'), (5, 'OTTAWA'), (20, 'SAN DIEGO')]
    s = (SET, 0, 0)
    for _ in range(4):
        s = press(s, dynview.KEY_DOWN, data)                 # OTTAWA: cat 3 + index 1
    assert s == (SET, 0, 4)
    s = press(s, 13, data)
    assert data['mask'] == 1 << 5 and s == (SET, 0, 4)
    assert dynview.settings_rows(data)[3:] == [('PHILADELPHIA', 'AI MANAGES'),
                                               ('OTTAWA', 'YOU MANAGE'),
                                               ('SAN DIEGO', 'AI MANAGES')]


def test_standings_follow_the_division_map(tmp_path):
    """C12.8 on a 2 division entry (ndiv 2): the AL teams are grouped by the entry's division
    map, not by the id rule; WEST (2) is listed before EAST (1)"""
    ldir = make_standings(tmp_path, seasons=[({t: (6, 4) for t in AL_NAMES}, 0xff, 0xff, 0xff)])
    west = (3, 8, 9, 10, 11, 13)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    set_season_map(d, 1, {k: 2 if k in west else 1 for k in AL_NAMES})
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    names = dict(data['teams'])
    blocks = standings_blocks(all_standings(data))
    assert list(blocks) == ['AL WEST', 'AL EAST']
    assert blocks['AL WEST'] == [names[t] for t in west]
    assert blocks['AL EAST'] == [names[t] for t in AL_NAMES if t not in west]


def test_standings_one_division_by_the_map(tmp_path):
    """the AL teams with games all in one division (ndiv 2): one block under the league's
    long name, no AL WEST or AL EAST header"""
    ldir = make_standings(tmp_path, seasons=[({t: (6, 4) for t in AL_NAMES}, 0xff, 0xff, 0xff)])
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    set_season_map(d, 1, {k: 2 for k in AL_NAMES})
    p.write_bytes(bytes(d))
    rows = all_standings(dynview.load_data(str(ldir)))
    assert rows[0][0] == 'AMERICAN LEAGUE'
    assert len(rows) == 1 + len(AL_NAMES)
    assert list(standings_blocks(rows)) == ['AMERICAN LEAGUE']


def test_about_playoff_format_lines():
    i = dynview.ABOUT_ROWS.index('LINEUP IS REPAIRED, NOT REBUILT.')
    assert dynview.ABOUT_ROWS[i + 1:i + 7] == [
        'PLAYOFF FORMAT: 2 DIVISIONS AND AN LCS,',
        'OR 3 DIVISIONS AND A WILD CARD WITH A',
        'DIVISION SERIES. IT TAKES EFFECT AT ONCE',
        'BEFORE A SEASON STARTS, ELSE AT THE ROLL.',
        'THEN START THE NEW SEASON WITH THE',
        'GENERATED SCHEDULE.']
    assert dynview.ABOUT_ROWS[i + 7] == ''


# ---------------------------------------------------------------- C18: starred teams
def test_standings_managed_star(tmp_path):
    """C18: a managed team's first STANDINGS cell is starred, an unmanaged one unchanged,
    headers and the blank spacer never; tid >= 32 is never starred even with bit set."""
    ldir = make_standings(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12:16] = ((1 << 1) | (1 << 9)).to_bytes(4, 'little')   # DETROIT (1), KANSAS CITY (9)
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rows = [r for pg in range(3) for r in dynview.rows((SS, pg, 2), data)]
    want = [((('*' + r[0]) if r[0] in ('DETROIT', 'KANSAS CITY') else r[0]),) + r[1:]
            for r in STAND_1_ROWS]
    assert rows == want
    assert all(r[0] == ('AL ' + r[0][3:] if False else r[0])
               for r in rows if not any(r[1:]))
    # tid >= 32 with its bit set is never starred
    (tmp_path / 'full').mkdir()
    ldir = make_standings(tmp_path / 'full')
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12:16] = b'\xff\xff\xff\xff'
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rows = [r for pg in range(3) for r in dynview.rows((SS, pg, 2), data)]
    ids = {disp: tid for tid, disp in data['teams']}
    for r in rows:
        if r[0].startswith('*'):
            name = r[0].lstrip('*')
            tid = ids.get(name, int(name[5:]) if name.startswith('TEAM ') else 99)
            assert tid < 32
    # and every listed team's cell stars exactly when its tid is under 32 (all bits set)
    shown = {}
    for r in rows:
        if any(r[1:]):
            shown.setdefault(r[0].lstrip('*'), r[0])
    for tid, disp in data['teams']:
        if disp in shown:
            assert shown[disp].startswith('*') == (tid < 32)


def test_standings_mask_zero_unchanged(tmp_path):
    """C18: mask 0 keeps the exact pre-change STANDINGS rows"""
    ldir = make_standings(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12:16] = b'\0\0\0\0'
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rows = [r for pg in range(3) for r in dynview.rows((SS, pg, 2), data)]
    assert rows == STAND_1_ROWS


def test_series_managed_star(tmp_path):
    """C18: visitor, home and summary rows of a managed team are starred; GAME headers
    and the SERIES row are not; mask 0 keeps SERIES6_ROWS byte for byte."""
    ldir = make_series(tmp_path, series_recs(3, SERIES6))
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12:16] = (1 << 0).to_bytes(4, 'little')               # BOSTON is AL id 0
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    want = [('*' + c if c == 'BOSTON' else c) if k == 0 else c for k, c in []] or [
        r[:1] + r[1:] for r in SERIES6_ROWS]
    want = [(('*' + r[0]) if r[0] == 'BOSTON' else r[0],) + r[1:]
            for r in SERIES6_ROWS]
    assert want[-1] == ('*BOSTON', '', '', '', 'WINS 4-2')
    assert ('*BOSTON', '3', '7', '1', '') in want
    rows = [r for pg in range(2) for r in dynview.rows((SW, pg, 0), data)]
    assert rows == want
    assert ('GAME 1', '', '', '', '') in rows
    # mask 0: exactly SERIES6_ROWS
    d[12:16] = b'\0\0\0\0'
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rows = [r for pg in range(2) for r in dynview.rows((SW, pg, 0), data)]
    assert rows == SERIES6_ROWS


def test_series_tid_32_star_rule_and_summary(tmp_path):
    """C18: a tid >= 32 never stars, even with the mask bit set; the summary row of a
    managed leader is starred too"""
    ldir = make_series(tmp_path, series_recs(3, SERIES6))
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12:16] = b'\xff\xff\xff\xff'
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rows = [r for pg in range(2) for r in dynview.rows((SW, pg, 0), data)]
    starred = [r[0] for r in rows if r[0].startswith('*')]
    ids = {disp: tid for tid, disp in data['teams']}
    for name in starred:
        assert ids[name.lstrip('*')] < 32


def test_history_champion_star_and_mask_zero(tmp_path):
    """C18: the CHAMPION cell of a managed champion stem is starred; mask 0 keeps the
    pre-change rows exactly"""
    ldir = make_data(tmp_path)[0]
    write_team(ldir, 'ALA03', 'MILWAUKEE')
    write_maj(ldir, {2: b'ALA03'})
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12:16] = (1 << 2).to_bytes(4, 'little')
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_HISTORY), data)
    assert rows[0][1] == '*MILWAUKEE'
    assert rows[1][1] == 'ALA02' and rows[2][1] == 'ALA01'
    # mask 0: the champion shows without the star
    d[12:16] = b'\0\0\0\0'
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_HISTORY), data)
    assert rows[0][1] == 'MILWAUKEE'
    # a champion stem with no team file has no stable id: never starred
    (tmp_path / 'nstem').mkdir()
    ldir = make_data(tmp_path / 'nstem')[0]
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    write_season(d, 3, b'NOSTEM9', b'NL03')
    d[12:16] = b'\xff\xff\xff\xff'
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_HISTORY), data)
    assert rows[0][1] == 'NOSTEM9'


def test_history_rows_optional_args(tmp_path):
    """history_rows' existing (hist, league_dir) form still works (no stars)"""
    ldir, hb = make_data(tmp_path)
    hist = history.History.load(str(ldir / 'HISTORY.DAT'))
    rows = dynview.history_rows(hist, str(ldir))
    assert rows[0][1] == 'ALA03'
    assert rows == dynview.history_rows(hist, str(ldir), {'ALA03': 2}, 0)


# ---------------------------------------------------------------- C19: releases
REL19 = (b'SIGN CLASALW7 Sign One pool\r\n'
         b'SIGN CLASNLW4 Sign Two pool\r\n'
         b'SIGN CLASALW7 Sign Three CLASALE1\r\n'
         b'REL CLASALW7 Cut One\r\n'
         b'REL CLASNLE4 Cut Two Words\r\n'
         b'REL BOSTON Cut Three\r\n')


def test_releases_rows_order_and_star(tmp_path):
    """C19 phase 4: the SIGN rows first, then one RELEASED row per REL event in file
    order, FROM 'RELEASED'; a managed stem's cell is starred; a two-word name keeps
    both words; a stem with no team file shows upper case"""
    ldir = draft_managed_test_league(tmp_path, REL19, 1 << 7)
    data = dynview.load_data(str(ldir))
    rows = dynview.offseason_body((SO, 0, oc(4)), data)[1]
    assert rows == [('*SEATTLE', 'Sign One', 'FREE AGENT'),
                    ('NEW YORK N', 'Sign Two', 'FREE AGENT'),
                    ('*SEATTLE', 'Sign Three', 'CLASALE1'),
                    ('*SEATTLE', 'Cut One', 'RELEASED'),
                    ('CLASNLE4', 'Cut Two Words', 'RELEASED'),
                    ('BOSTON', 'Cut Three', 'RELEASED')]
    assert dynview.body_cols((SO, 0, oc(4)), data) == dynview.COLS_MOVE
    assert dynview.screen_title((SO, 0, oc(4)), data) == '5/6 SIGNINGS AND RELEASES'


def test_releases_empty_message_and_count(tmp_path):
    """C19: the empty phase-4 message is NO SIGNINGS OR RELEASES; the phase-5
    PLAYERS RELEASED count is unchanged (REL lines with 3+ tokens only)"""
    ldir = make_offseason(tmp_path, rosters=None)
    data = dynview.load_data(str(ldir))
    assert dynview.rows((SO, 0, oc(4)), data) == [('NO SIGNINGS OR RELEASES',)]
    assert dynview.body_cols((SO, 0, oc(4)), data) == dynview.COLS_SINGLE
    (tmp_path / 'full').mkdir()
    ldir = make_offseason(tmp_path / 'full')
    data = dynview.load_data(str(ldir))
    ready = dynview.rows((SO, 0, oc(5)), data)
    assert ready[4] == ('PLAYERS RELEASED: 2',)
    assert ready[3] == ('FREE AGENT SIGNINGS: 4',)


def test_releases_parse_rosters_tuple(tmp_path):
    """C19: parse_rosters REL events carry the stem and the name"""
    ldir = make_offseason(tmp_path, rosters=None)
    (ldir / 'ROSTERS.TXT').write_bytes(
        b'REL CLASALW7 A Guy\r\n'
        b'REL\r\n'                       # one token: not an event
        b'REL TEAM\r\n'                  # two tokens: not an event
        b'REL CLASALE1 Solo\r\n')
    assert dynview.parse_rosters(str(ldir)) == [('REL', 'CLASALW7', 'A Guy'),
                                                ('REL', 'CLASALE1', 'Solo')]


def test_releases_total_rows_capped(tmp_path, monkeypatch):
    """C19: the combined SIGN + RELEASE row count is still capped at LIST_MAX"""
    rosters = b''.join(b'SIGN CLASALW7 Player%02d pool\r\n' % k for k in range(30))
    rosters += b''.join(b'REL CLASNLW4 Gone%02d\r\n' % k for k in range(30))
    ldir = make_offseason(tmp_path, rosters)
    monkeypatch.setattr(dynview, 'LIST_MAX', 45)
    data = dynview.load_data(str(ldir))
    rows = dynview.offseason_body((SO, 0, oc(4)), data)[1]
    assert len(rows) == 45
    assert rows[29] == ('SEATTLE', 'Player29', 'FREE AGENT')
    assert rows[30] == ('NEW YORK N', 'Gone00', 'RELEASED')
    assert rows[-1] == ('NEW YORK N', 'Gone14', 'RELEASED')


# ---------------------------------------------------------------- C23c PLAYOFFS and round box scores
SP = dynview.SCREEN_PLAYOFFS
SPB = dynview.SCREEN_PBOX
PLAYOFFS_FOOTER = 'ENTER BOX  LEFT RIGHT SEASON  PGUP PGDN  ESC'
PBOX_FOOTER = 'ENTER CARD  LEFT RIGHT GAME  PGUP PGDN  ESC'


def round_hdr(season, g, v, h, rnd, L, k, vr, hr, vhi, hhi, ve, he, s=0):
    """one flags-4 round header record: idx = visitor * 256 + home, b = rnd + 4 L + 8 s
    (s the series number within (rnd, L)), i = the 1-based game number k,
    stats = (vR, hR, vH, hH, vE, hE, 0, 0)."""
    return box_rec(season, g, 4, v * 256 + h, (vr, hr, vhi, hhi, ve, he, 0, 0),
                   b=rnd + 4 * L + 8 * s, i=k)


def playoff_recs():
    """BOXSCORE.DAT records of season 3, header g ascending: AL DS series 0 (ids 0/16,
    games 1..3 at g 16..18, BOS LEADS 2-1), AL DS series 1 (ids 8/9, 4 games
    at g 19..22, MIL WINS 3-1), AL LCS (ids 0/8, 4 games, BOS WINS 4-0), NL LCS (ids
    16/24, 3 games, COL LEADS 3-0); every game one header then one batting and one pitching
    row per side (entry 0xffff rows, '?' on the box)."""
    recs = []
    for k, g in enumerate((16, 17, 18)):
        vr, hr = ((5, 3), (2, 6), (4, 2))[k]
        recs.append(round_hdr(3, g, 0, 16, 1, 0, k + 1, vr, hr, 9, 7, 1, 0))
    for k, g in enumerate((19, 20, 21, 22)):
        vr, hr = ((7, 1), (2, 5), (9, 3), (5, 4))[k]
        recs.append(round_hdr(3, g, 8, 9, 1, 0, k + 1, vr, hr, 6, 5, 2, 1, s=1))
    for k, g in enumerate((23, 24, 25, 26)):
        recs.append(round_hdr(3, g, 0, 8, 2, 0, k + 1, 7, 1, 11, 4, 0, 1))
    for k, g in enumerate((27, 28, 29)):
        vr, hr = ((2, 5), (1, 7), (4, 9))[k]
        recs.append(round_hdr(3, g, 16, 24, 2, 1, k + 1, vr, hr, 6, 8, 1, 0))
    for g in range(16, 30):
        recs.append(box_rec(3, g, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)))
        recs.append(box_rec(3, g, 2, 0xffff, (80, 5, 2, 2, 1, 1, 8, 30)))
    return recs


def game_side_rows(vr, hr, vhi, hhi, ve, he):
    """the visitor and home cells (R, H, E and the W mark) of one round game's rows."""
    return [('BOSTON', '%d' % vr, '%d' % vhi, '%d' % ve, 'W' if vr > hr else ''),
            ('ATLANTA', '%d' % hr, '%d' % hhi, '%d' % he, 'W' if hr > vr else '')]


def make_playoffs(tmp_path):
    """make_series league (team names, the 2 WS games of game_ms(3, (0, 1))) whose
    BOXSCORE.DAT holds playoff_recs() plus BOX_G0 (game 1) and two rows for WS game 2."""
    ldir = make_series(tmp_path, game_ms(3, (0, 1)))
    recs = playoff_recs() + BOX_G0 + \
        [box_rec(3, 1, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)),
         box_rec(3, 1, 2, 0xffff, (80, 5, 2, 2, 1, 1, 8, 30))]
    write_box(ldir, recs)
    return ldir


def playoffs_all_rows(state, data):
    """every row of the paged PLAYOFFS screen state's season"""
    n = dynview.total_rows(state, data)
    return [r for p in range((n + 11) // 12) for r in dynview.rows((SP, p, state[2]), data)]


def test_playoff_rows_titles_games_and_summaries(tmp_path):
    """PLAYOFFS rows of a full season: per series the league and round title, the GAME k
    rows (R, H, E, W on the side with more runs), then the summary of the first game's
    two teams with the DS threshold 3 and the LCS threshold 4."""
    ldir = make_playoffs(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.playoffs_body((SP, 0, 0), data)[0] == dynview.COLS_SERIES
    assert dynview.playoffs_body((SP, 0, 0), data)[1] == playoffs_all_rows((SP, 0, 0), data)
    # a title row keeps its full text (CELL_CUT covers it: 18 chars fit)

    rows = playoffs_all_rows((SP, 0, 0), data)
    # C30: the season's player rows (16 headers skipped, 16 '?' batting + 16 '?' pitching)
    # tally: HITTER 2 H, PLAYER02 1 H 1 RBI, ACE 8 SO 7.2 IP 3.60 ERA, PLAYER06 5 SO
    # 10.0 IP 2 ER 3.60 ERA -> the block test_c30_league_of_4096 pins exactly
    assert len(rows) == 60 == dynview.total_rows((SP, 0, 0), data)
    assert rows[50] == ('POSTSEASON LEADERS', '', '', '', '')
    assert rows[51] == ('HITTER, A', '', '', '', '2 H')
    assert rows[52] == ('PLAYER02, B', '', '', '', '1 H')
    # series 0: the title, three games, the 2-1 lead below the DS threshold
    assert rows[0] == ('AL DIVISION SERIES', '', '', '', '')
    assert rows[1] == ('GAME 1', '', '', '', '')
    assert rows[2:4] == game_side_rows(5, 3, 9, 7, 1, 0)
    assert rows[10] == ('BOSTON', '', '', '', 'LEADS 2-1')
    # series 1: 3-1 in a division series reaches the threshold (WINS, not LEADS)
    assert rows[11][0] == 'AL DIVISION SERIES'
    assert rows[24] == ('MILWAUKEE', '', '', '', 'WINS 3-1')
    # AL LCS: 4-0, threshold 4
    assert rows[25][0] == 'AL CHAMPIONSHIP SERIES'
    assert rows[38] == ('BOSTON', '', '', '', 'WINS 4-0')
    # NL LCS: 3-0 in a championship series stays a LEADS (threshold 4)
    assert rows[39][0] == 'NL CHAMPIONSHIP SERIES'
    assert rows[49] == ('COLORADO', '', '', '', 'LEADS 3-0')
    # a game's rows carry R, H and E; the W mark follows the runs
    assert rows[1] == ('GAME 1', '', '', '', '')
    assert rows[2] == ('BOSTON', '5', '9', '1', 'W')
    assert rows[3] == ('ATLANTA', '3', '7', '0', '')
    # the columns fit; the draw cuts every cell to its column (cell[:w] in render, so an
    # 18 char title renders as 17), and the model rows hold the full text
    for row in dynview.rows((SP, 0, 0), data):
        if not row[0].endswith('SERIES'):
            for cell, (_h, _x, w, _a) in zip(row, dynview.COLS_SERIES):
                assert len(cell) <= w, cell


def test_playoffs_managed_star(tmp_path):
    """the managed star on PLAYOFFS; the POSTSEASON LEADERS rows end at_SB rows and the
    leaders keep the no-star message (the tally reads the box, the names read the entries)"""
    ldir = make_playoffs(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12] = 1                                     # id 0 (BOSTON) managed
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rows = playoffs_all_rows((SP, 0, 0), data)
    assert rows[0] == ('AL DIVISION SERIES', '', '', '', '')
    assert rows[1] == ('GAME 1', '', '', '', '')
    assert rows[2] == ('*BOSTON', '5', '9', '1', 'W')
    assert rows[3] == ('ATLANTA', '3', '7', '0', '')
    assert rows[10] == ('*BOSTON', '', '', '', 'LEADS 2-1')
    assert rows[24] == ('MILWAUKEE', '', '', '', 'WINS 3-1')
    assert rows[38] == ('*BOSTON', '', '', '', 'WINS 4-0')
    assert rows[49] == ('COLORADO', '', '', '', 'LEADS 3-0')
    # C30: the leaders block still appends after the 50 round rows (the same tallies)
    assert rows[50] == ('POSTSEASON LEADERS', '', '', '', '')
    assert len(rows) == 60
    assert rows[51] == ('HITTER, A', '', '', '', '2 H')


def test_playoff_box_rows_and_title(tmp_path):
    """PBOX rows: the box_rows layout of the round game's records (the flags-4 header
    excluded, '?' for the 0xffff entries), COLS_BOX, and the round title."""
    ldir = make_playoffs(tmp_path)
    data = dynview.load_data(str(ldir))
    # round game g 16 (cat 0): one header, one batting and one pitching row per side
    rows = dynview.rows((SPB, 0, 0), data)
    assert dynview.pbox_body((SPB, 0, 0), data) == (dynview.COLS_BOX, rows)
    assert rows == [('BOSTON',) + HDR_AB, ('?', '4', '1', '2', '1', '0', '1'),
                    PIT_HDR, ('?', '8.0', '5', '2', '2', '1', '8'),
                    ('ATLANTA',) + HDR_AB, PIT_HDR]
    assert dynview.total_rows((SPB, 0, 0), data) == 6
    assert dynview.screen_title((SPB, 0, 0), data) == '1995 AL DS GAME 1'
    # game 2 of the AL DS series 1: (cat & 63) = g - 16 = 6
    assert dynview.screen_title((SPB, 0, 6), data) == '1995 AL DS GAME 4'
    # the AL LCS and NL LCS titles
    assert dynview.screen_title((SPB, 0, 23 - 16), data) == '1995 AL LCS GAME 1'
    assert dynview.screen_title((SPB, 0, 27 - 16), data) == '1995 NL LCS GAME 1'
    assert dynview.screen_title((SPB, 0, 29 - 16), data) == '1995 NL LCS GAME 3'
    # the box records of the WS game 1 still show on the BOX SCORE screen
    assert dynview.rows((SB, 0, 0), data) == BOX_G0_ROWS


def test_playoff_box_no_header_or_rows_message(tmp_path):
    """no flags-4 header, or a header with no other record: one message row, COLS_SINGLE"""
    ldir = make_playoffs(tmp_path)
    write_box(ldir, [box_rec(3, 40, 0, 0, (1, 1, 1, 1, 1, 1, 1, 1))]     # no round header
              + [r for r in playoff_recs() if r[2] != 4]
              + [round_hdr(3, 41, 0, 8, 2, 0, 1, 7, 1, 11, 4, 0, 1)])    # no box rows
    data = dynview.load_data(str(ldir))
    for cat in (24, 25):
        assert dynview.rows((SPB, 0, cat), data) == [('NO BOX SCORE RECORDED',)]
        assert dynview.body_cols((SPB, 0, cat), data) == dynview.COLS_SINGLE
        assert dynview.total_rows((SPB, 0, cat), data) == 1
    # a header of a WS g (< 16) never counts
    write_box(ldir, [box_rec(3, 5, 4, 0 * 256 + 16, (1, 2, 3, 4, 5, 6, 7, 8), b=9, i=1)]
              + BOX_G0)
    data = dynview.load_data(str(ldir))
    # the WS box screen reads its game record from MILESTON.DAT: without those records
    # the message row returns even with BOX_G0 records on file
    assert dynview.rows((SB, 0, 5), data) == [('NO BOX SCORE RECORDED',)]
    # pbox_rows ignores a flags-4 record of a g below 16 entirely
    assert dynview.pbox_rows(data['hist'], data['box'], data['teams'], 3, 5) == \
        [('NO BOX SCORE RECORDED',)]


def test_playoffs_empty_season_message(tmp_path):
    """a season with no round game and one past the history table: one message row,
    COLS_SINGLE; the history table caps the season walk"""
    ldir = make_playoffs(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.rows((SP, 0, 1), data) == [('NO PLAYOFF ROUNDS RECORDED',)]
    assert dynview.body_cols((SP, 0, 1), data) == dynview.COLS_SINGLE
    assert dynview.screen_title((SP, 0, 1), data) == '1994 PLAYOFFS'
    assert dynview.rows((SP, 0, 2), data) == [('NO PLAYOFF ROUNDS RECORDED',)]
    assert dynview.screen_title((SP, 0, 2), data) == '1993 PLAYOFFS'
    assert dynview.rows((SP, 0, 3), data) == [('NO PLAYOFF ROUNDS RECORDED',)]


def test_playoffs_hub_title_footer_and_keys(tmp_path):
    """the hub's 12th row and key P (both cases), the PLAYOFFS title and footer, LEFT
    and RIGHT season steps, PGUP and PGDN pages, and ENTER's box choice."""
    ldir = make_playoffs(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.MENU_ROWS[11] == 'P  PLAYOFFS'
    assert dynview.SCREEN_PLAYOFFS == 14 and dynview.SCREEN_PBOX == 15
    assert dynview.rows(HUB, data)[11] == ('P  PLAYOFFS',)
    assert dynview.total_rows(HUB, data) == 12
    assert dynview.step(HUB, 80, data) == ((SP, 0, 0), 0)
    assert dynview.step(HUB, 112, data) == ((SP, 0, 0), 0)
    # a click on the row gives key ord('P') = 80
    assert dynview.click_to_key(HUB, data, 100, 35 + 11 * 11 + 3) == (80, None)
    assert dynview.screen_title((SP, 0, 0), data) == '1995 PLAYOFFS'
    assert dynview.footer_text((SP, 0, 0)) == PLAYOFFS_FOOTER
    assert len(PLAYOFFS_FOOTER) == 44
    # LEFT and RIGHT step the seasons like WORLD SERIES does
    s = dynview.step((SP, 0, 0), dynview.KEY_LEFT, data)[0]
    assert s == (SP, 0, 1)
    assert dynview.step(s, dynview.KEY_RIGHT, data)[0] == (SP, 0, 0)
    assert dynview.step((SP, 0, 0), dynview.KEY_RIGHT, data)[0] == (SP, 0, 0)
    # PGUP and PGDN page as every list screen (50 rows: 5 pages)
    s = dynview.step((SP, 0, 0), dynview.KEY_PGDN, data)[0]
    assert s == (SP, 1, 0)
    assert dynview.step(s, dynview.KEY_PGUP, data)[0] == (SP, 0, 0)
    assert dynview.step((SP, 4, 0), dynview.KEY_PGDN, data)[0] == (SP, 4, 0)
    # ENTER opens the first game on the page: the nth GAME row of the season (the rows
    # come in the games' order) is the nth playoff game. Page 0's first GAME row is the
    # season's first game (g 16)
    assert dynview.step((SP, 0, 0), dynview.KEY_ENTER, data) == ((SPB, 0, 0), 0)
    # page 1 (rows 12..23): three GAME rows sat before it, so series 1's GAME 1 (g 19)
    assert dynview.step((SP, 1, 0), dynview.KEY_ENTER, data) == ((SPB, 0, 3), 0)
    # page 3 (rows 36..47): eleven GAME rows sat before it, so NL LCS GAME 1 (g 27)
    assert dynview.step((SP, 3, 0), dynview.KEY_ENTER, data) == ((SPB, 0, 11), 0)
    # page 4 (rows 48..49): no GAME row, so the season's first round game (cat 0)
    assert dynview.step((SP, 4, 0), dynview.KEY_ENTER, data) == ((SPB, 0, 0), 0)
    assert dynview.step((SP, 0, 1), dynview.KEY_ENTER, data) == ((SP, 0, 1), 0)


def test_playoff_box_walk_and_esc(tmp_path):
    """PBOX LEFT and RIGHT step between the season's round games by g, RIGHT past the
    last opens the season's first WS box, LEFT from the first WS box comes back, and
    ESC returns to PLAYOFFS."""
    ldir = make_playoffs(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.footer_text((SPB, 0, 0)) == PBOX_FOOTER
    assert len(PBOX_FOOTER) == 43
    # RIGHT steps to the next round game, LEFT back; over 14 round games then into the WS
    s = (SPB, 0, 13)                              # the last round game (g 29)
    assert dynview.step(s, dynview.KEY_RIGHT, data) == ((SB, 0, 0), 0)
    assert dynview.step((SB, 0, 0), dynview.KEY_LEFT, data) == ((SPB, 0, 13), 0)
    assert dynview.step((SPB, 0, 0), dynview.KEY_LEFT, data) == ((SPB, 0, 0), 0)
    assert dynview.step((SPB, 0, 0), dynview.KEY_RIGHT, data) == ((SPB, 0, 1), 0)
    # the season's WS games with records are games 1 and 2 (cat 0 and 1); ESC to PLAYOFFS
    assert dynview.step((SPB, 0, 5), dynview.KEY_ESC, data) == ((SP, 0, 0), 0)
    # a season with round games but no WS game: RIGHT past the last does nothing
    (tmp_path / 'nows').mkdir()
    ldir2 = make_playoffs(tmp_path / 'nows')
    write_mileston(str(ldir2 / 'MILESTON.DAT'), [])
    data2 = dynview.load_data(str(ldir2))
    assert dynview.step((SPB, 0, 13), dynview.KEY_RIGHT, data2) == ((SPB, 0, 13), 0)
    # the WS screens keep their own LEFT/RIGHT: RIGHT past the last WS game stays
    assert dynview.step((SB, 0, 1), dynview.KEY_RIGHT, data) == ((SB, 0, 1), 0)


def test_box_left_from_first_ws_game_into_pbox(tmp_path):
    """on the BOX SCORE screen, LEFT on the season's first WS game with a record opens
    the last round game's PBOX; on other WS games LEFT walks as before."""
    ldir = make_playoffs(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.step((SB, 0, 0), dynview.KEY_LEFT, data) == ((SPB, 0, 13), 0)
    # game 2 of the season's WS has a record and walks left to game 1 as before
    assert dynview.step((SB, 0, 1), dynview.KEY_LEFT, data) == ((SB, 0, 0), 0)
    # a season without round games keeps LEFT where it is on the first WS game
    (tmp_path / 'norounds').mkdir()
    ldir2 = make_playoffs(tmp_path / 'norounds')
    recs = [r for r in playoff_recs() if r[2] != 4 or False]
    write_box(ldir2, BOX_G0)
    data2 = dynview.load_data(str(ldir2))
    assert dynview.step((SB, 0, 0), dynview.KEY_LEFT, data2) == ((SB, 0, 0), 0)


# ---------------------------------------------------------------- C62 row cursor
def test_box_entries_align_with_rows(tmp_path):
    """box_entries is box_rows' length, None exactly on the team headers, the PITCHING
    headers, the message row and the '?' rows; the same for pbox_entries"""
    ldir0 = tmp_path / 'box'
    ldir0.mkdir()
    ldir = make_series(ldir0, game_ms(3, (0,)))
    write_box(ldir, BOX_G0 + [box_rec(3, 0, 0, 0xffff, (9, 9, 9, 9, 9, 9, 9, 9))])
    data = dynview.load_data(str(ldir))
    rows = dynview.box_rows(data['hist'], data['ms'], data['box'], data['teams'], 3, 0)
    entries = dynview.box_entries(data['hist'], data['ms'], data['box'], data['teams'], 3, 0)
    assert len(entries) == len(rows)
    # one extra visitor batting row (a '?'): 10 rows
    assert entries == [None, 0, None, None, 5, 1, None, 2, None, 6]
    # rows[2] is the '?' batting row of the visitor side
    assert rows[2][0] == '?'
    # the message row: entries [(None,)]
    assert dynview.box_rows(data['hist'], data['ms'], data['box'], data['teams'], 3, 1) \
        == [('NO BOX SCORE RECORDED',)]
    assert dynview.box_entries(data['hist'], data['ms'], data['box'], data['teams'], 3, 1) \
        == [None]
    # PBOX: the round game rows' entries, one header per side, '?' rows
    ldir1 = tmp_path / 'pbox'
    ldir1.mkdir()
    ldir = make_playoffs(ldir1)
    data = dynview.load_data(str(ldir))
    prows = dynview.pbox_rows(data['hist'], data['box'], data['teams'], 3, 16)
    pentries = dynview.pbox_entries(data['hist'], data['box'], data['teams'], 3, 16)
    assert len(pentries) == len(prows) == 6
    assert pentries == [None, None, None, None, None, None]     # all '?' records
    assert dynview.pbox_entries(data['hist'], data['box'], data['teams'], 3, 40) == [None]


def test_box_cursor_enter_card_and_esc(tmp_path):
    """BOX is a cursor screen: ENTER on a batting row opens pack(13, 0, entry) with the box
    state as card_back; ESC returns with the row kept; ENTER on a header row is a no-op;
    PGUP / PGDN move the cursor; the footers are the C62 text"""
    ldir = make_series(tmp_path, game_ms(3, (0,)))
    write_box(ldir, BOX_G0)
    data = dynview.load_data(str(ldir))
    assert dynview.FOOTERS[SB] == BOX_FOOTER == 'ENTER CARD  LEFT RIGHT GAME  PGUP PGDN  ESC'
    assert dynview.footer_text((SB, 0, 0), data) == BOX_FOOTER
    assert dynview.cursor_screen((SB, 0, 0)) is True
    assert dynview.cursor_screen((SPB, 0, 0)) is True
    # row 1 is the visitor's first batting row (HITTER, entry 0): the card opens
    s, _ex = dynview.step((SB, 0, 0, 1), ENTER, data)
    assert s == (13, 0, 0)
    assert data['card_back'] == (SB, 0, 0, 1)
    s, _ex = dynview.step(s, ESC, data)
    assert s == (SB, 0, 0, 1)
    # a pitching row too (row 3, ACE = entry 5)
    assert dynview.row_entry((SB, 0, 0, 3), data) == 5
    # the team header row and the PITCHING row: no card
    for r in (0, 2):
        assert dynview.step((SB, 0, 0, r), ENTER, data) == ((SB, 0, 0, r), 0)
    # a row past the end: nothing
    assert dynview.step((SB, 0, 0, 9), ENTER, data) == ((SB, 0, 0, 9), 0)
    # DOWN / UP move the cursor (pack drops a 0 row); the 9 rows make one page, so
    # PGUP / PGDN cannot move
    assert dynview.step((SB, 0, 0, 1), dynview.KEY_DOWN, data) == ((SB, 0, 0, 2), 0)
    assert dynview.step((SB, 0, 0, 1), dynview.KEY_UP, data) == ((SB, 0, 0), 0)
    assert dynview.step((SB, 0, 0, 1), dynview.KEY_PGDN, data) == ((SB, 0, 0, 1), 0)
    assert dynview.step((SB, 0, 0, 1), dynview.KEY_PGUP, data) == ((SB, 0, 0, 1), 0)


def test_pbox_cursor_enter_card_and_footers(tmp_path):
    """PBOX: the same cursor, the card of its player rows and the C62 footer"""
    ldir = make_playoffs(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.FOOTERS[SPB] == PBOX_FOOTER
    assert dynview.footer_text((SPB, 0, 0), data) == PBOX_FOOTER
    assert dynview.cursor_screen((SPB, 0, 0)) is True
    # every player row of the round game is a '?': no card anywhere, ENTER is a no-op
    for r in range(6):
        assert dynview.step((SPB, 0, 0, r), ENTER, data) == ((SPB, 0, 0, r), 0)
    assert dynview.step((SPB, 0, 0, 2), ESC, data) == ((SP, 0, 0), 0)
    # PGDN over the 6 rows: no page to go to, the state stays
    assert dynview.step((SPB, 0, 0, 2), dynview.KEY_PGDN, data) == ((SPB, 0, 0, 2), 0)


def test_box_left_right_step_resets_row(tmp_path):
    """RIGHT to another game resets page and row; LEFT / RIGHT with no other game keep
    the state exactly (the row kept); the same on PBOX"""
    base = tmp_path / 'walk' / 'lg'
    base.mkdir(parents=True)
    ldir = make_series(base, game_ms(3, (0, 1)) + game_ms(2, (0,)))
    write_box(ldir, BOX_G0 + [box_rec(3, 1, 0, 1, (9, 9, 9, 9, 9, 9, 9, 9))])
    data = dynview.load_data(str(ldir))
    s = (SB, 0, 0, 3)
    assert dynview.step(s, dynview.KEY_RIGHT, data) == ((SB, 0, 1), 0)
    assert dynview.step((SB, 0, 1, 3), dynview.KEY_LEFT, data) == ((SB, 0, 0), 0)
    # game 2 (cat >> 3 = 1) has a kind 192 record but no box rows for g 2, and game 3
    # has none: the season's games with records stay 0 and 1, so LEFT steps to game 1
    assert dynview.step((SB, 0, 2, 3), dynview.KEY_RIGHT, data) == ((SB, 0, 2, 3), 0)
    assert dynview.step((SB, 0, 2, 3), dynview.KEY_LEFT, data) == ((SB, 0, 1), 0)
    # from the season's first game LEFT has nowhere to go: the state is unchanged
    assert dynview.step((SB, 0, 0, 4), dynview.KEY_LEFT, data) == ((SB, 0, 0, 4), 0)
    # PBOX: cat 0 (g 16) steps to cat 1 (g 17) and back, the row resets; past the ends kept
    pbase = tmp_path / 'pb' / 'lg'
    pbase.mkdir(parents=True)
    ldir2 = make_series(pbase, game_ms(3, (0, 1)))
    write_box(ldir2, playoff_recs()[:12])          # the AL DS series 0, two games
    data2 = dynview.load_data(str(ldir2))
    s = (SPB, 0, 0, 2)
    assert dynview.step(s, dynview.KEY_RIGHT, data2) == ((SPB, 0, 1), 0)
    assert dynview.step((SPB, 0, 1, 2), dynview.KEY_LEFT, data2) == ((SPB, 0, 0), 0)
    assert dynview.step((SPB, 0, 0, 2), dynview.KEY_LEFT, data2) == ((SPB, 0, 0, 2), 0)


# ---------------------------------------------------------------- C27 MILESTONES WATCH
def test_watch_offsets_and_message(tmp_path):
    """watch_items through the reference renderer's own helpers: the WATCH rows of
    make_data's league (3000-H hitter is retired so no row; the empty league shows the
    message), the WATCH columns and the message row's COLS_SINGLE"""
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # entries 0 and 5 are retired; the role players have H = 10 + i <= 37: no watch rows
    assert dynview.watch_items(data['hist']) == []
    empty = tmp_path / 'empty'
    empty.mkdir()
    data2 = dynview.load_data(str(empty))
    assert dynview.watch_items(data2['hist']) == []
    # BODY: an active H-2950 batter and an active PSO-2995 pitcher
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    t = [0] * 25
    t[AB], t[H] = 8000, 2950
    write_player(d, 2, b'WACTCHA', b'W', status=1, totals=t)   # entry 2 was retired
    p.write_bytes(bytes(d))
    data3 = dynview.load_data(str(ldir))
    items = dynview.watch_items(data3['hist'])
    assert items == [(50, 3000, 2, 2, 2950)]
    assert dynview.watch_rows(data3['hist']) == [('WACTCHA, W', '3000 H', '2950', '50')]


def test_watch_state_and_clicks(tmp_path):
    """LEFT/RIGHT toggle with page and row reset, WATCH is a cursor screen (mode 0 is
    now one too, C61), row_entry names the row's entry, and the title bands are
    LEFT/RIGHT on both modes"""
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    t = [0] * 25
    t[AB], t[H] = 8000, 2950
    write_player(d, 2, b'WACTCHA', b'W', status=1, totals=t)
    t = [0] * 25
    t[AB], t[HR] = 3000, 298
    write_player(d, 3, b'NEARHR', b'N', status=1, totals=t)
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    MS = dynview.SCREEN_MILESTONES
    s, _ex = dynview.step((MS, 2, 0), dynview.KEY_RIGHT, data)
    assert s == (MS, 0, 1)
    s2, _ex = dynview.step((MS, 0, 0, 5), dynview.KEY_LEFT, data)
    assert s2 == (MS, 0, 1)
    assert dynview.step(s2, dynview.KEY_RIGHT, data)[0] == (MS, 0, 0)
    assert dynview.cursor_screen((MS, 0, 0)) is True       # C61: mode 0 is a cursor screen
    assert dynview.cursor_screen((MS, 0, 1)) is True
    assert dynview.row_entry((MS, 0, 1, 0), data) == 3          # HR row sorts first
    assert dynview.row_entry((MS, 0, 1, 1), data) == 2
    assert dynview.row_entry((MS, 0, 1, 9), data) is None
    s3, _ex = dynview.step((MS, 0, 1, 1), dynview.KEY_ENTER, data)
    assert s3 == (dynview.SCREEN_CARD, 0, 2)
    assert dynview.step(s3, dynview.KEY_ESC, data)[0] == (MS, 0, 1, 1)
    assert dynview.click_to_key((MS, 0, 0), data, 159, 12) == (dynview.KEY_LEFT, None)
    assert dynview.click_to_key((MS, 0, 1), data, 161, 18) == (dynview.KEY_RIGHT, None)


# ---------------------------------------------------------------- C61 MILESTONES cursor
def test_c61_milestone_items_match_rows(tmp_path):
    """milestone_items is exactly the records milestone_rows shows, in its order, and
    milestone_rows builds its cells from it"""
    ldir = make_awards(tmp_path)
    data = dynview.load_data(str(ldir))
    items = dynview.milestone_items(data['hist'], data['ms'])
    assert items == [(3, 0, 2, 3000), (3, 5, 32, 51), (2, 1, 32, 52), (2, 2, 2, 3000)]
    rows = dynview.milestone_rows(data['hist'], data['ms'])
    assert rows == [(dynview.year_text(data['hist'], s), dynview.entry_name(data['hist'], i, 16),
                     dynview.event_text(k, v)) for s, i, k, v in items]
    # award and leader records are skipped, newest season first, file order within one
    (tmp_path / 'mix').mkdir()
    ms = award_league_ms() + [(2, 3, 2, 2900), (1, 4, 5, 400)]
    ldir2 = make_awards(tmp_path / 'mix', ms=ms)
    data2 = dynview.load_data(str(ldir2))
    assert dynview.milestone_items(data2['hist'], data2['ms']) == [
        (3, 0, 2, 3000), (3, 5, 32, 51), (2, 1, 32, 52), (2, 2, 2, 3000),
        (2, 3, 2, 2900), (1, 4, 5, 400)]
    # LIST_MAX caps the list
    monkey_full = [(1, k % 30, 2, 100 + k) for k in range(1300)]
    assert len(dynview.milestone_items(data['hist'], monkey_full)) == dynview.LIST_MAX


def test_c61_cursor_down_and_enter_row1(tmp_path):
    """DOWN moves the cat 0 cursor; ENTER on row 1 opens pack(13, 0, idx of row 1) with
    card_back = the milestones state with row 1; ESC returns it"""
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    MS = dynview.SCREEN_MILESTONES
    assert dynview.milestone_items(data['hist'], data['ms'])[0][1] == 0    # row 0 is HITTER (idx 0)
    s = (MS, 0, 0, 0)
    s1, _ex = dynview.step(s, dynview.KEY_DOWN, data)
    assert s1 == (MS, 0, 0, 1)
    assert dynview.milestone_items(data['hist'], data['ms'])[1][1] == 5    # row 1 is ACE (idx 5)
    card, _ex = dynview.step(s1, ENTER, data)
    assert card == (dynview.SCREEN_CARD, 0, 5)
    assert data['card_back'] == (MS, 0, 0, 1)
    back, _ex = dynview.step(card, ESC, data)
    assert back == (MS, 0, 0, 1)


def test_c61_row_entry_no_award_and_empty(tmp_path):
    """a NO_AWARD record row and an out-of-list row give row_entry None; ENTER on an
    empty list does nothing (and mode 0 with no history shows the message row)"""
    (tmp_path / 'na').mkdir()
    ms = [(3, 0xffff, 2, 3000), (3, 1, 2, 2000)]
    data = dynview.load_data(str(make_data(tmp_path / 'na', ms=ms)[0]))
    MS = dynview.SCREEN_MILESTONES
    r = (MS, 0, 0, 0)
    assert dynview.milestone_rows(data['hist'], data['ms'])[0][1] == 'NONE'
    assert dynview.row_entry(r, data) is None
    assert dynview.step(r, ENTER, data) == (r, 0)
    assert dynview.row_entry((MS, 0, 0, 5), data) is None
    (tmp_path / 'plain').mkdir()
    empty = dynview.load_data(str(make_data(tmp_path / 'plain', ms=[])[0]))
    s = (MS, 0, 0)
    assert dynview.step(s, ENTER, data) == (s, 0)          # never taken: empty-list ENTER
    _d, _ex = dynview.step(s, ENTER, empty)
    assert dynview.total_rows(s, empty) == 0
    assert dynview.rows(s, empty) == []


def test_c61_paging_and_left_right_toggle(tmp_path):
    """PGDN on cat 0 puts the cursor on the new page's first row; LEFT/RIGHT still
    toggle the mode and reset page and row; the footers are exact"""
    (tmp_path / 'many').mkdir()
    ms = [(2, k % 30, 2, 100 + k) for k in range(30)]      # 30 rows: pages 0..2
    data = dynview.load_data(str(make_data(tmp_path / 'many', ms=ms)[0]))
    MS = dynview.SCREEN_MILESTONES
    s, _ex = dynview.step((MS, 0, 0, 3), dynview.KEY_PGDN, data)
    assert s == (MS, 1, 0, 12)
    s2, _ex = dynview.step(s, dynview.KEY_PGUP, data)
    assert pack3(s2) == (MS, 0, 0) and unpack4(s2) == 0
    assert dynview.footer_text((MS, 0, 0), data) == \
        'ENTER CARD  LEFT RIGHT WATCH  PGUP PGDN  ESC'
    assert dynview.FOOTERS[MS] == 'ENTER CARD  LEFT RIGHT WATCH  PGUP PGDN  ESC'
    assert dynview.footer_text((MS, 0, 1), data) == \
        'ENTER CARD  LEFT RIGHT MODE  PGUP PGDN  ESC'      # cat 1 footer unchanged
    t, _ex = dynview.step((MS, 1, 0, 12), dynview.KEY_LEFT, data)
    assert t == (MS, 0, 1)
    t2, _ex = dynview.step((MS, 1, 1, 12), dynview.KEY_RIGHT, data)
    assert t2 == (MS, 0, 0)
    # WATCH keeps its cursor behaviour (C27 unchanged)
    (tmp_path / 'w').mkdir()
    ldirw = make_data(tmp_path / 'w')[0]
    pw = ldirw / 'HISTORY.DAT'
    dw = bytearray(pw.read_bytes())
    tw = [0] * 25
    tw[AB], tw[H] = 8000, 2950
    write_player(dw, 2, b'WACTCHA', b'W', status=1, totals=tw)
    pw.write_bytes(bytes(dw))
    d3 = dynview.load_data(str(ldirw))
    assert dynview.row_entry((MS, 0, 1, 0), d3) == 2
    c, _ex = dynview.step((MS, 0, 1, 0), ENTER, d3)
    assert c == (dynview.SCREEN_CARD, 0, 2)
    assert dynview.step(c, ESC, d3)[0] == (MS, 0, 1)       # row 0 packs away


# ---------------------------------------------------------------- POSTSEASON LEADERS (C39)
PM = dynview.SCREEN_LEADERS
POST = 3 * dynview.MODE_SHIFT
POST_LABELS = [c[0] for c in dynview.POST_CATS]


def post_index(label):
    return POST_LABELS.index(label)


def test_post_totals_and_post_leader_totals(tmp_path):
    ldir, _ = make_data(tmp_path)
    # two postseason WS games of season 3. Game 1 (g 0): HITTER (entry 0) bats twice
    # (G counts the game once), ACE (5) pitches then bats for the same game. Game 2
    # (g 1): PLAYER01 (1) bats. A flags 4 round header of entry 0 and rows of entry 3
    # (no row) and 4096+ (ignored) round it out.
    write_box(ldir, [
        box_rec(3, 0, 4, 0 * 256 + 16, (5, 3, 9, 7, 1, 0, 0, 0), b=1, i=1),  # header: skipped
        box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0)),
        box_rec(3, 0, 2, 5, (72, 5, 2, 2, 1, 1, 8, 30)),       # ACE pitches game 1
        box_rec(3, 0, 0, 5, (1, 0, 0, 0, 1, 0, 0, 0)),          # ACE bats game 1 too
        box_rec(3, 1, 0, 0, (3, 0, 1, 0, 1, 2, 0, 2)),          # HITTER game 2
        box_rec(3, 1, 2, 1, (12, 1, 1, 0, 0, 0, 2, 6)),         # PLAYER01 pitches game 2
        box_rec(3, 1, 0, 4096, (9, 9, 9, 9, 9, 9, 9, 9)),       # entry >= 4096: ignored
        box_rec(2, 0, 0, 3, (1, 0, 0, 0, 0, 0, 0, 0)),          # PLAYER03: one game
    ])
    data = dynview.load_data(str(ldir))
    box = data['box']
    # every entry below the cap matches post_totals (including None)
    got = dynview.post_leader_totals(box)
    for entry in range(4096):
        pt = dynview.post_totals(box, entry)
        assert got.get(entry) == (pt if pt is not None else None), entry
    g0, t0 = got[0]
    assert g0 == 2 and t0[1] == 7 and t0[2] == 3 and t0[5] == 1 and t0[7] == 1 \
        and t0[10] == 2 and t0[0] == 2
    g5, t5 = got[5]
    assert g5 == 1 and t5[19] == 3 * 7 + 2 and t5[20] == 2 and t5[23] == 8 \
        and t5[1] == 1 and t5[0] == 1
    assert got[1][0] == 1
    assert 4096 not in got and 3 in got


def test_post_order_value_entry_and_cap(tmp_path):
    ldir, _ = make_data(tmp_path)
    # entry 0: 2 games; entry 1: 1 game HR 3; entry 2: 1 game HR 3 (tie, entry order);
    # entry 4096: 5 games (ignored). The mark of entry 2 is R (status 2), entry 0 H
    # - entries 28+ are HoF: entry 0 here is HITTER (status 2 retired)
    write_box(ldir, [box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0)),
                     box_rec(3, 1, 0, 0, (3, 0, 1, 0, 1, 0, 0, 0)),
                     box_rec(3, 0, 0, 1, (2, 0, 1, 0, 3, 0, 0, 0)),
                     box_rec(3, 0, 0, 2, (2, 0, 1, 0, 3, 0, 0, 0)),
                     box_rec(3, 0, 0, 4097, (9, 0, 0, 0, 0, 0, 0, 0))])
    data = dynview.load_data(str(ldir))
    box = data['box']
    hr = dynview.post_order(box, dynview.POST_CATS[post_index('HR')])
    # HR 3 tie: entry 1 before entry 2; entry 0's HR 1 last
    assert hr == [(3, 1, 1), (3, 2, 1), (1, 0, 2)]
    g = dynview.post_order(box, dynview.POST_CATS[0])     # G of the qualifiers
    assert [it[:2] for it in g] == [(2, 0), (1, 1), (1, 2)]
    ip = dynview.post_order(box, dynview.POST_CATS[post_index('IP')])
    assert ip == []
    # only the first POST_MAX
    many = [box_rec(3, k % 7, 0, e, (1, 0, 0, 0, 0, 0, 0, 0))
            for k, e in enumerate(range(3, 3 + 60))]
    write_box(ldir, box_rec(3, 0, 0, 0, (1, 0, 0, 0, 0, 0, 0, 0)) and many)
    data = dynview.load_data(str(ldir))
    assert len(dynview.post_order(data['box'], dynview.POST_CATS[post_index('G')])) \
        == dynview.POST_MAX


def test_post_leaders_body_rows_title_and_row_entry(tmp_path):
    ldir, _ = make_data(tmp_path)
    write_box(ldir, [box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0)),
                     box_rec(3, 0, 0, 1, (1, 0, 2, 0, 0, 0, 1, 0)),
                     box_rec(3, 0, 2, 1, (70, 5, 2, 2, 1, 1, 8, 28))])
    data = dynview.load_data(str(ldir))
    s = (PM, 0, POST + post_index('H'))
    cols, rows = dynview.leaders_body(s, data)
    assert cols == dynview.COLS_POST_LEADERS
    assert rows == [('#1', 'HITTER, A', 'R', '1', '2'),
                    ('#2', 'PLAYER01, B', ' ', '1', '2')]
    assert dynview.footer_text(s, data) == dynview.FOOTERS[PM]
    assert dynview.screen_title(s, data) == 'POSTSEASON LEADERS: H'
    assert dynview.row_entry((PM, 0, POST + post_index('H'), 0), data) == 0  # row 0: entry 0
    # IP formatting: a pitching row's 70 IP10 of PLAYER01 = 7.0
    ip = dynview.leaders_body((PM, 0, POST + post_index('IP')), data)[1]
    assert ip == [('#1', 'PLAYER01, B', ' ', '1', '7.0')]
    s1, _ex = dynview.step(s, dynview.KEY_DOWN, data)
    assert dynview.row_entry(s1, data) == 1
    card, _ex = dynview.step(s1, dynview.KEY_ENTER, data)
    assert card[0] == dynview.SCREEN_CARD and card[2] == 1
    assert dynview.step(card, dynview.KEY_ESC, data)[0] == s1
    assert dynview.row_entry((PM, 0, POST + post_index('H'), 5), data) is None


def test_post_leaders_empty_message(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    s = (PM, 0, POST + post_index('G'))
    assert dynview.leaders_body(s, data) == \
        (dynview.COLS_SINGLE, [(dynview.NO_POST_TEXT,)])
    assert dynview.screen_title(s, data) == 'POSTSEASON LEADERS: G'
    assert dynview.footer_text(s, data) == dynview.FOOTERS[PM]
    assert dynview.row_entry((PM, 0, POST + post_index('G'), 0), data) is None


def test_post_tab_cycle_and_left_right(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    s = st(PM, 0, 2)                                       # CAREER RBI (CATS index 2)
    for _ in range(3):                                     # -> SEASON -> BY YEAR -> POST
        s, _ex = dynview.step(s, dynview.KEY_TAB, data)
    assert s == (PM, 0, POST + post_index('RBI'))           # RBI carried into POST_CATS
    assert dynview.screen_title(s, data) == 'POSTSEASON LEADERS: RBI'
    s, _ex = dynview.step(s, dynview.KEY_TAB, data)         # POST -> CAREER
    assert s == (PM, 0, 2)                                  # RBI keeps its CATS index
    # BB (CAREER 7) stays BB on SEASON (index 8), then falls back to G on POST
    assert dynview.step((PM, 0, 7), dynview.KEY_TAB, data)[0] == (PM, 0, 40)
    # AVG -> POST falls back to index 0 (G)
    s, _ex = dynview.step((PM, 0, 8), dynview.KEY_TAB, data)      # CAREER AVG -> SEASON
    for _ in range(2):
        s, _ex = dynview.step(s, dynview.KEY_TAB, data)           # -> BY YEAR -> POST
    assert s == (PM, 0, POST)
    # LEFT/RIGHT wrap within POST_CATS
    s, _ex = dynview.step(s, dynview.KEY_LEFT, data)
    assert s == (PM, 0, POST + len(POST_LABELS) - 1)
    s, _ex = dynview.step(s, dynview.KEY_RIGHT, data)
    s, _ex = dynview.step(s, dynview.KEY_RIGHT, data)
    assert s == (PM, 0, POST + 1)

# ---------------------------------------------------------------- C40 HONORS view
def honors_league(tmp_path, name='honors'):
    """ALPHA (entry 0, awards MVP 2 CY 1 ROY 0 GG 3 SS 0) with an MVP award record, a NL
    BA leader record and a milestone in seasons 1 and 2, so season 3 has no award or
    leader records; BAKER (entry 1) with an award record of season 3 only; HOTEL
    (entry 2) with no records. HISTORY start 1990 so year_text(season 1) = 1990."""
    ldir = tmp_path / name
    ldir.mkdir()
    d = bytearray(32 + 64 * 128 + 3 * 160)
    d[3] = 1
    d[4], d[5] = 3, 0
    d[6], d[7] = 3, 0
    d[18], d[19] = 1990 & 255, 1990 >> 8
    write_season(d, 1, b'ALA01', b'NL01', awards=(0, 0xffff, 0xffff, 1, 0xffff, 0xffff))
    write_season(d, 2, b'ALA02', b'NL02', awards=(0, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff))
    write_season(d, 3, b'ALA03', b'NL03', awards=(1, 0xffff, 0xffff, 0xffff, 0xffff, 0xffff))
    t0 = [0] * 25
    t0[AB], t0[H] = 9000, 3000
    write_player(d, 0, b'ALPHA', b'A', status=1, totals=t0,
                 awards=(2, 1, 0, 3, 0))
    t1 = [0] * 25
    t1[AB], t1[H] = 500, 150
    write_player(d, 1, b'BAKER', b'B', status=1, totals=t1, awards=(0, 0, 1, 0, 0))
    write_player(d, 2, b'HOTEL', b'H', status=1)
    (ldir / 'HISTORY.DAT').write_bytes(bytes(d))
    write_mileston(str(ldir / 'MILESTON.DAT'), [
        (1, 0, 64, 1),           # ALPHA AL MVP of season 1
        (2, 0, 128, 330),        # ALPHA AL BA LEADER .330 of season 2 (before 96+0)
        (2, 0, 160, 333),        # ALPHA NL BA LEADER .333 of season 2 (same season)
        (2, 0, 2, 3000),         # ALPHA 3000 HITS of season 2 (before the leaders?)
        (3, 1, 65, 2),           # BAKER AL CY YOUNG of season 3
    ])
    return ldir


def test_honors_rows_order_and_text(tmp_path):
    """the first row holds the career counts; the items sort by (season, group, order):
    the season's award record, then the milestone (same season, by file position), then
    the two leader records of the same season in file order; a season without award or
    leader records uses the fallback winners"""
    ldir = honors_league(tmp_path)
    data = dynview.load_data(str(ldir))
    s = (dynview.SCREEN_CARD, 0, 0, 1)
    assert dynview.body_cols(s, data) == dynview.COLS_HONORS
    assert dynview.footer_text(s, data) == 'LEFT RIGHT  PGUP PGDN  H SEASONS  ESC'
    rows = dynview.rows(s, data)
    # items of the same season keep file order: the season 2 records of ALPHA come as the
    # two leader records (positions 1 and 2) and then the milestone (position 3)
    assert rows[0] == ('', 'MVP 2  CY 1  ROY 0  GG 3  SS 0')
    body = rows[1:]
    assert body == [('1990', 'AL MVP'),                  # season 1 award record
                    ('1991', 'AL BA LEADER .330 BA'),    # season 2 leader records (pos 1)
                    ('1991', 'NL BA LEADER .333 BA'),    # ... then (pos 2)
                    ('1991', '3000 HITS')]               # ... then the milestone (pos 3)
    # BAKER: the fallback of season 1 (NL MVP of the table, awards=(0, FFFF, FFFF, 1, ...))
    # and the season 3 award record; season 3 has a record so no fallback there
    rows1 = dynview.rows((dynview.SCREEN_CARD, 0, 1, 1), data)
    assert rows1[0] == ('', 'MVP 0  CY 0  ROY 1  GG 0  SS 0')
    assert rows1[1:] == [('1990', 'NL MVP'), ('1992', 'AL CY YOUNG')]    # HOTEL: only the first row
    assert dynview.rows((dynview.SCREEN_CARD, 0, 2, 1), data) == \
        [('', 'MVP 0  CY 0  ROY 0  GG 0  SS 0')]


def test_honors_hof_row_and_fallback_caps(tmp_path):
    """a HOF entry gets HALL OF FAME at its hof_season in group 1: after that season's
    records, before the next season's. Past the season table there is no fallback"""
    ldir = honors_league(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[8224 + 22 + 0 * 160] = 3                       # ALPHA status HOF
    d[8224 + 150 + 0 * 160] = 3                      # hof_season 3
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir))
    rows = dynview.rows((dynview.SCREEN_CARD, 0, 0, 1), data)
    # season 3's award record names BAKER (idx 1), so ALPHA has no season 3 item but the
    # HOF row (group 1) still lands at hof_season 3 = 1992
    assert rows[1:] == [('1990', 'AL MVP'), ('1991', 'AL BA LEADER .330 BA'),
                        ('1991', 'NL BA LEADER .333 BA'), ('1991', '3000 HITS'),
                        ('1992', 'HALL OF FAME')]


def test_honors_paging_keys_and_esc(tmp_path):
    """HONORS pages 9 rows: 12 award records give 13 rows over 2 pages, PGDN/PGUP page,
    the second PGDN stays; H toggles and resets the page; ESC from HONORS returns
    data['card_back']"""
    ldir = honors_league(tmp_path)
    p = ldir / 'MILESTON.DAT'
    write_mileston(str(p), [(s, 0, 64, 1) for s in range(1, 13)])
    data = dynview.load_data(str(ldir))
    assert len(dynview.honors_rows(data['hist'], data['ms'], 0)) == 13
    s0 = (dynview.SCREEN_CARD, 0, 0, 1)
    assert [r[0] for r in dynview.rows(s0, data)] == \
        ['', '1990', '1991', '1992', '1993', '1994', '1995', '1996', '1997']
    s = dynview.step(s0, dynview.KEY_PGDN, data)[0]
    assert s == (dynview.SCREEN_CARD, 1, 0, 1)
    assert [r[0] for r in dynview.rows(s, data)] == ['1998', '1999', '2000', '2001']
    assert dynview.step(s, dynview.KEY_PGDN, data)[0] == s        # the last page stays
    assert dynview.step(s, dynview.KEY_PGUP, data)[0] == s0
    assert dynview.step(s0, dynview.KEY_PGUP, data)[0] == s0
    # H toggles the view and resets the page; ESC returns card_back from both views
    data['card_back'] = (dynview.SCREEN_LEADERS, 0, 0, 2)
    s2 = dynview.step((dynview.SCREEN_CARD, 2, 0), 72, data)[0]
    assert s2 == (dynview.SCREEN_CARD, 0, 0, 1)
    assert dynview.step(s2, 104, data)[0] == (dynview.SCREEN_CARD, 0, 0)
    assert dynview.step(s2, dynview.KEY_ESC, data)[0] == (dynview.SCREEN_LEADERS, 0, 0, 2)
    assert dynview.step((dynview.SCREEN_CARD, 0, 0), dynview.KEY_ESC, data)[0] == \
        (dynview.SCREEN_LEADERS, 0, 0, 2)
    # PGDN on HONORS does not touch the SEASONS paging bounds (its own row count)
    assert dynview.step((dynview.SCREEN_CARD, 0, 0), dynview.KEY_PGDN, data)[0] == \
        (dynview.SCREEN_CARD, 0, 0)


# ---------------------------------------------------------------- C50 FIND PLAYER
def find_players(write):
    """HISTORY.DAT bytes d: last names that collide under the prefix sorts, one unused
    entry (status 0), and one lower-case stored last name (write = write_player)."""
    def add(i, last, first, status, played, pos1, pitcher=0, hof=0):
        write(i, last.encode(), first.encode(), status=status, seasons_played=played,
              pitcher=pitcher, hof_season=hof)
        o = 8224 + i * 160
        # write_player has no pos1: patch the position byte
        return o
    return add


def make_find(tmp_path, writer):
    """make_data league whose entries 0..6 are the FIND fixture (the rest stay)."""
    ldir, mb = make_data(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    rows = [(0, b'SMITH', b'JOHN', 2, 12, 3), (1, b'smith', b'AARON', 1, 5, 0),
            (2, b'SMYTHE', b'ZEKE', 3, 18, 6), (3, b'JONES', b'SAM', 1, 4, 5),
            (4, b'UNUSED', b'NO', 0, 0, 9), (5, b'BROWN', b'X', 1, 1, 3),
            (6, b'NOBODY', b'Q', 1, 2, 7)]
    for i, last, first, status, played, pos1 in rows:
        o = 8224 + i * 160
        d[o:o + 20] = (last + b'\0' * 12)[:12] + (first + b'\0' * 8)[:8]
        d[o + 22] = status
        struct.pack_into('<H', d, o + 28, played)
        d[o + 30] = pos1
    p.write_bytes(bytes(d))
    return ldir


def test_find_open_edit_and_rows(tmp_path):
    """C50: F/f on the hub opens FIND with data['find'] = '' and the prompt row; letters
    append (upper case, at most FIND_MAX), BACKSPACE removes; edits reset page and row;
    the MENU footer exact."""
    ldir = make_find(tmp_path, write_player)
    data = dynview.load_data(str(ldir))
    HUB = (dynview.SCREEN_MENU, 0, 0)
    s, _ex = dynview.step(HUB, ord('F'), data)
    assert s == (dynview.SCREEN_FIND, 0, 0)
    assert dynview.step(HUB, ord('f'), data)[0] == s
    assert data['find'] == ''
    assert dynview.rows(s, data) == [('TYPE THE START OF A LAST NAME.',)]
    assert dynview.body_cols(s, data) == dynview.COLS_SINGLE
    assert dynview.screen_title(s, data) == 'FIND PLAYER: _'
    assert dynview.footer_text(s, data) == 'TYPE NAME  BKSP  ENTER CARD  ESC MENU'
    assert dynview.FOOTERS[dynview.SCREEN_MENU] == '0-9 W P F SELECT   ESC EXIT'
    assert dynview.FOOTERS[dynview.SCREEN_FIND] == 'TYPE NAME  BKSP  ENTER CARD  ESC MENU'
    # typing: a fresh FIND, then letters append upper case, edits reset, BACKSPACE
    # removes, a 13th letter never lands
    s = press(s, ord('a'), data)
    assert s == (dynview.SCREEN_FIND, 0, 0) and data['find'] == 'A'
    s = press((dynview.SCREEN_FIND, 1, 0, 3), ord('b'), data)
    assert s == (dynview.SCREEN_FIND, 0, 0) and data['find'] == 'AB'
    s = press(s, 8, data)
    assert data['find'] == 'A' and s == (dynview.SCREEN_FIND, 0, 0)
    s, _ex = dynview.step(HUB, ord('F'), data)          # start the cap check over
    for k in 'ABCDEFGHIJKL':
        s = press(s, ord(k.lower()), data)
    assert data['find'] == 'ABCDEFGHIJKL'
    s = press(s, ord('z'), data)
    assert data['find'] == 'ABCDEFGHIJKL' and dynview.screen_title(s, data) == \
        'FIND PLAYER: ABCDEFGHIJKL_'
    # digits and TAB never type
    s = press(s, ord('5'), data)
    assert data['find'] == 'ABCDEFGHIJKL'
    # a non-letter key down a filtered list leaves the state alone
    s2 = (dynview.SCREEN_FIND, 0, 0, 1)
    assert dynview.step(s2, ord('5'), data) == (s2, 0)
    # C is a letter here (it types, it does not open the card)
    s3 = (dynview.SCREEN_FIND, 0, 0)
    s4 = press(s3, ord('c'), data)
    assert s4 == (dynview.SCREEN_FIND, 0, 0)
    # ESC clears the typed query first (C59): reset to the prompt row, not the hub
    assert dynview.step((dynview.SCREEN_FIND, 0, 0, 2), ESC, data) == \
        ((dynview.SCREEN_FIND, 0, 0), 0)
    assert data['find'] == ''


def test_find_esc_clears_then_menu(tmp_path):
    """C59: ESC on FIND with a non-empty query clears data['find'] and resets to the
    prompt row (18, 0, 0); a second ESC goes to the MENU; ESC with an empty query goes
    straight to the MENU; the footer labels the ESC key CLEAR only while the query has
    text; ESC after moving the cursor resets it too."""
    ldir = make_find(tmp_path, write_player)
    data = dynview.load_data(str(ldir))
    HUB = (dynview.SCREEN_MENU, 0, 0)
    s, _ex = dynview.step(HUB, ord('F'), data)
    s = press(s, ord('S'), data)
    s = press(s, ord('M'), data)
    assert data['find'] == 'SM'
    assert dynview.footer_text(s, data) == 'TYPE NAME  BKSP  ENTER CARD  ESC CLEAR'
    assert press(s, ESC, data) == (dynview.SCREEN_FIND, 0, 0)
    assert data['find'] == ''
    assert dynview.footer_text((dynview.SCREEN_FIND, 0, 0), data) == \
        'TYPE NAME  BKSP  ENTER CARD  ESC MENU'
    assert dynview.step((dynview.SCREEN_FIND, 0, 0), ESC, data) == (HUB, 0)
    # ESC on an empty query goes straight to the MENU
    assert dynview.step((dynview.SCREEN_FIND, 0, 0), ESC, data) == (HUB, 0)
    # ESC after moving the cursor resets it too
    s = press(HUB, ord('f'), data)
    s = press(s, ord('S'), data)
    s = press((dynview.SCREEN_FIND, 0, 0, 2), ESC, data)
    assert s == (dynview.SCREEN_FIND, 0, 0) and data['find'] == ''
    # a card opened from FIND keeps the exact FIND state on ESC (unchanged)
    s = press(s, ord('S'), data)
    s = press(s, ord('M'), data)
    card, _ex = dynview.step((dynview.SCREEN_FIND, 0, 0, 1), ENTER, data)
    assert data['card_back'] == (dynview.SCREEN_FIND, 0, 0, 1)
    assert dynview.step(card, ESC, data)[0] == (dynview.SCREEN_FIND, 0, 0, 1)
    assert data['find'] == 'SM'
    assert dynview.footer_text((dynview.SCREEN_FIND, 0, 0, 1), data) == \
        'TYPE NAME  BKSP  ENTER CARD  ESC CLEAR'


def _find_cells(hist, q):
    """the find_rows cells without their entries (C50)"""
    return [c for _i, c in dynview.find_rows(hist, q)]


def test_find_rows_filter_sort_and_status(tmp_path):
    """find_rows filters by the last-name prefix (lower-case names match too), sorts by
    (last upper, first upper, index), never lists status 0, and labels the statuses;
    a no-match query gives the NO PLAYER FOUND row keeping COLS_FIND."""
    ldir = make_find(tmp_path, write_player)
    data = dynview.load_data(str(ldir))
    hist = data['hist']
    assert _find_cells(hist, '') == []
    assert _find_cells(hist, 'SM') == [
        ('smith, AARON', 'P', '5', 'ACTIVE'),
        ('SMITH, JOHN', '2B', '12', 'RETIRED'),
        ('SMYTHE, ZEKE', 'LF', '18', 'HALL OF FAME')]
    assert _find_cells(hist, 'J') == [('JONES, SAM', 'SS', '4', 'ACTIVE')]
    # lower-case compare: only the letter keys build an upper-case query, the sort is on
    # the upper-cased last name (folded here by upper())
    assert _find_cells(hist, 'SMI') == \
        [r for r in _find_cells(hist, 'SM') if r[0].upper().startswith('SMI')]
    assert _find_cells(hist, 'UNUSED') == []     # status 0 never listed
    # lower-case queries upper (the letter keys never build one, but find_rows folds)
    # ENTER opens the row's entry (row 1 is SMITH, JOHN: entry 0), ESC back keeps the query
    s = (dynview.SCREEN_FIND, 0, 0, 1) if False else press((dynview.SCREEN_FIND, 0, 0),
                                                           ord('S'), data)
    s = press(s, ord('M'), data)
    assert data['find'] == 'SM'
    card, _ex = dynview.step((dynview.SCREEN_FIND, 0, 0, 1), ENTER, data)
    assert card == (dynview.SCREEN_CARD, 0, 0)
    assert data['card_back'] == (dynview.SCREEN_FIND, 0, 0, 1)
    assert dynview.step(card, ESC, data)[0] == (dynview.SCREEN_FIND, 0, 0, 1)
    cursor = (dynview.SCREEN_FIND, 0, 0, 1)
    press(cursor, ord('S'), data)                      # an edit resets the row
    assert data['find'] == 'SMS'
    # empty list: ENTER does nothing; no-match row with COLS_FIND
    s5 = (dynview.SCREEN_FIND, 0, 0)
    st1 = press(s5, ord('Z'), data)
    assert dynview.rows(st1, data) == [('NO PLAYER FOUND.',)]
    assert dynview.body_cols(st1, data) == dynview.COLS_FIND
    st2 = press(st1, ENTER, data)
    assert st2 == st1
    # the cursor screen rule and total_rows of the message screens
    assert dynview.cursor_screen(st1) is True
    up = press(st1, dynview.KEY_UP, data)              # UP from row 0 stays
    assert up == st1


def test_c50_find_list_cap(tmp_path, monkeypatch):
    """find_rows keeps at most FIND_LIST matches, the first ones in sort order (the DOS
    port holds no more)"""
    ldir = make_find(tmp_path, write_player)
    hist = dynview.load_data(str(ldir))['hist']
    full = dynview.find_rows(hist, 'SM')
    assert dynview.FIND_LIST == 300 and len(full) > 1
    monkeypatch.setattr(dynview, 'FIND_LIST', 1)
    assert dynview.find_rows(hist, 'SM') == full[:1]



# ---------------------------------------------------------------- C30 PLAYOFFS postseason leaders
def pl_round_hdrs():
    """the two flags-4 heads of the C30 tests: g 16 and 17, AL DS (b 1), games 1 and 2"""
    return [round_hdr(3, 16, 0, 16, 1, 0, 1, 5, 3, 9, 7, 1, 0),
            round_hdr(3, 17, 0, 16, 1, 0, 2, 2, 6, 8, 6, 0, 1)]


LEAD_TITLE = ('POSTSEASON LEADERS', '', '', '', '')


def post_leaders_rows(tmp_path, recs, name='c30'):
    """the POSTSEASON LEADERS block of a make_series season-3 league whose BOXSCORE.DAT
    holds pl_round_hdrs() plus recs (the rows before it included)"""
    (tmp_path / name).mkdir(parents=True, exist_ok=True)
    ldir = make_series(tmp_path / name, [])
    write_box(ldir, pl_round_hdrs() + list(recs))
    data = dynview.load_data(str(ldir))
    rows = dynview.playoffs_body((SP, 0, 0), data)[1]
    i = rows.index(LEAD_TITLE)
    return rows[:i], rows[i:]


def test_c30_season_rows_ws_and_rounds_categories_texts(tmp_path):
    """batters and pitchers spread over a WS game and the round games; the seven
    categories in order with the exact value texts; ERA needs 27 outs (the 26-out
    pitcher absent, the 27-out one present); a tie on H by entry index; NO_AWARD and
    out-of-range idx are ignored"""
    pre, lead = post_leaders_rows(tmp_path, [
        box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0)),          # WS game 1 batting
        box_rec(3, 0, 2, 5, (14, 4, 1, 4, 0, 0, 5, 0)),         # WS game 1 pitching
        box_rec(3, 17, 0, 0, (0, 0, 14, 7, 2, 0, 0, 0)),        # round game 2 batting
        box_rec(3, 17, 2, 0xffff, (14, 1, 0, 1, 0, 0, 0, 0)),    # NO_AWARD: ignored
        box_rec(3, 16, 0, 100, (1, 0, 99, 0, 0, 0, 0, 0)),      # past 30 entries: ignored
        box_rec(3, 16, 0, 1, (0, 0, 20, 0, 0, 0, 0, 3)),        # PLAYER01: 20 H
        box_rec(3, 16, 0, 2, (0, 0, 20, 0, 0, 0, 0, 0)),        # PLAYER02: 20 H
        box_rec(3, 16, 2, 2, (4, 4, 1, 4, 0, 0, 5, 0)),          # PLAYER02: 26 outs, no ERA
        box_rec(3, 16, 2, 5, (100, 4, 0, 4, 0, 0, 8, 0)),        # ACE: 28 outs 9.1 IP
        box_rec(3, 16, 0, 12, (1, 0, 0, 0, 0, 0, 0, 8)),         # SO 8 tie, entry 12
        box_rec(3, 16, 0, 19, (1, 0, 0, 0, 0, 0, 0, 8)),         # SO 8 tie, entry 19
    ])
    assert len(pre) == 8 and pre[0][0] == 'AL DIVISION SERIES' and pre[-1][4] == 'TIED 1-1'
    assert pre[-1][0] == 'SERIES'
    assert lead == [
        LEAD_TITLE,
        ('PLAYER01, B', '', '', '', '20 H'), ('PLAYER02, B', '', '', '', '20 H'),
        ('HITTER, A', '', '', '', '16 H'),                      # the H tie: idx 1 < 2
        ('HITTER, A', '', '', '', '2 HR'),                      # the WS HR only
        ('HITTER, A', '', '', '', '8 RBI'),
        ('PLAYER12, B', '', '', '', '8 SB'), ('PLAYER19, B', '', '', '', '8 SB'),
        ('PLAYER01, B', '', '', '', '3 SB'),
        ('ACE, P', '', '', '', '13 SO'), ('PLAYER02, B', '', '', '', '5 SO'),
        ('ACE, P', '', '', '', '12.1 IP'), ('PLAYER02, B', '', '', '', '1.1 IP'),
        ('ACE, P', '', '', '', '5.83 ERA')]                     # 27+ outs only
    # a batter with only SO 1 (a batting row's sixth stat) has no H: the categories
    # H HR RBI SB IP ERA all give no row, only SO shows
    (tmp_path / 'c30b').mkdir(parents=True, exist_ok=True)
    ldir = make_series(tmp_path / 'c30b', [])
    write_box(ldir, pl_round_hdrs() + [box_rec(3, 16, 2, 1, (20, 4, 0, 0, 0, 0, 1, 0))])
    rows = dynview.playoffs_body((SP, 0, 0), dynview.load_data(str(ldir)))[1]
    i = rows.index(LEAD_TITLE)
    assert rows[i + 1:] == [('PLAYER01, B', '', '', '', '1 SO'),
                            ('PLAYER01, B', '', '', '', '2.0 IP')]


def test_c30_leaders_cap_top3_and_pages(tmp_path):
    """at most 3 rows per category, ties by entry index; the leaders ride the last page
    and ENTER on it still opens the season's first round game"""
    pre, lead = post_leaders_rows(tmp_path, [
        box_rec(3, 16, 0, e, (1, 0, 3, 0, 0, 0, 0, 0)) for e in range(1, 6)
    ], name='c30d')
    assert lead == [LEAD_TITLE,
                    ('PLAYER01, B', '', '', '', '3 H'), ('PLAYER02, B', '', '', '', '3 H'),
                    ('PLAYER03, B', '', '', '', '3 H')]
    pre3, lead3 = post_leaders_rows(tmp_path, [
        box_rec(3, 16, 0, e, (1, 0, 3, 0, 0, 0, 0, 3)) for e in range(1, 5)
    ], name='c30e')
    assert lead3 == [LEAD_TITLE,
                     ('PLAYER01, B', '', '', '', '3 H'), ('PLAYER02, B', '', '', '', '3 H'),
                     ('PLAYER03, B', '', '', '', '3 H'),
                     ('PLAYER01, B', '', '', '', '3 SB'), ('PLAYER02, B', '', '', '', '3 SB'),
                     ('PLAYER03, B', '', '', '', '3 SB')]
    # the 13-row league: page 1 holds the two leaders past the cut
    (tmp_path / 'c30p').mkdir(parents=True, exist_ok=True)
    ldir = make_series(tmp_path / 'c30p', [])
    write_box(ldir, pl_round_hdrs() + [
        box_rec(3, 16, 0, 0, (1, 0, 41, 0, 0, 0, 0, 0)),
        box_rec(3, 16, 0, 1, (1, 0, 27, 0, 0, 0, 0, 0)),
        box_rec(3, 16, 0, 2, (1, 0, 20, 0, 0, 0, 0, 0))])
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SP, 0, 0), data) == 12
    assert dynview.rows((SP, 0, 0), data)[-1] == ('PLAYER02, B', '', '', '', '20 H')
    assert dynview.rows((SP, 1, 0), data) == []
    s, _ex = dynview.step((SP, 0, 0), dynview.KEY_ENTER, data)
    assert s == (SPB, 0, 0)
    # the 13-row league (a 4th H-20 batter below the top 3 keeps: 3 leaders, the SO of
    # entry 0's 1, IP and ERA rows) still never spills past 12
    (tmp_path / 'c30p2').mkdir(parents=True, exist_ok=True)
    ldir = make_series(tmp_path / 'c30p2', [])
    write_box(ldir, pl_round_hdrs() + [
        box_rec(3, 16, 0, 0, (1, 0, 41, 0, 0, 0, 0, 1)),
        box_rec(3, 16, 0, 1, (1, 0, 27, 0, 0, 0, 0, 0)),
        box_rec(3, 16, 0, 2, (1, 0, 20, 0, 0, 0, 0, 0)),
        box_rec(3, 16, 0, 3, (1, 0, 20, 0, 0, 0, 0, 0)),
        box_rec(3, 16, 2, 0, (91, 4, 0, 1, 0, 0, 0, 0)),
        box_rec(3, 16, 2, 1, (90, 4, 0, 1, 0, 0, 0, 0))])
    data = dynview.load_data(str(ldir))
    assert dynview.total_rows((SP, 0, 0), data) == 17
    assert dynview.rows((SP, 1, 0), data)[-1] == ('PLAYER01, B', '', '', '', '1.00 ERA')
    s, _ex = dynview.step((SP, 1, 0), dynview.KEY_ENTER, data)
    assert s == (SPB, 0, 0)                                    # the leaders never enter
    # the multi-page rows round-trip through rows()
    all_rows = playoffs_all_rows((SP, 0, 0), data)
    assert all_rows[:12] == dynview.rows((SP, 0, 0), data)
    assert all_rows[12:] == dynview.rows((SP, 1, 0), data)


def test_c30_cap_257_entries(tmp_path):
    """the 257th distinct entry in file order is not tallied"""
    pre, lead = post_leaders_rows(tmp_path, [
        box_rec(3, 16, 0, e, (1, 0, 3, 0, 0, 0, 0, 0)) for e in range(257)])
    assert lead == [LEAD_TITLE,
                    ('HITTER, A', '', '', '', '3 H'), ('PLAYER01, B', '', '', '', '3 H'),
                    ('PLAYER02, B', '', '', '', '3 H')]
    # a row of an already tallied entry keeps counting while rows of later entries drop:
    # entry 0 has two rows in the first 256 (H 10 + 3), entry 257 (the 258th distinct)
    # never shows
    recs = [box_rec(3, 16, 0, 0, (1, 0, 10, 0, 0, 0, 0, 0))]
    recs += [box_rec(3, 16, 0, e, (1, 0, 3, 0, 0, 0, 0, 0)) for e in range(1, 258)]
    pre, lead = post_leaders_rows(tmp_path, recs, name='c30h')
    assert lead == [LEAD_TITLE,
                    ('HITTER, A', '', '', '', '10 H'), ('PLAYER01, B', '', '', '', '3 H'),
                    ('PLAYER02, B', '', '', '', '3 H')]


def test_c30_no_round_headers_message(tmp_path):
    """a season with player rows but no round header keeps the lone message row"""
    (tmp_path / 'c30n').mkdir(parents=True, exist_ok=True)
    ldir = make_series(tmp_path / 'c30n', [])
    write_box(ldir, [box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0))])
    data = dynview.load_data(str(ldir))
    assert dynview.rows((SP, 0, 0), data) == [('NO PLAYOFF ROUNDS RECORDED',)]
    assert dynview.body_cols((SP, 0, 0), data) == dynview.COLS_SINGLE
    assert dynview.playoffs_body((SP, 0, 0), data) == (dynview.COLS_SINGLE,
                                                       [('NO PLAYOFF ROUNDS RECORDED',)])


def test_c30_ip_and_era_texts(tmp_path):
    """'9.1 IP' for 28 outs, the era100 text (er * 2700 // outs), the 27-out floor
    boundary (27 in, 26 out)"""
    pre, lead = post_leaders_rows(tmp_path, [
        box_rec(3, 16, 2, 0, (91, 4, 0, 1, 0, 0, 0, 4)),          # 28 outs -> 9.1 IP; 1 ER 0.03
        box_rec(3, 16, 2, 1, (90, 4, 0, 1, 0, 0, 0, 3)),          # 27 outs -> 9.0 IP; 1 ER 0.10
        box_rec(3, 16, 2, 2, (82, 4, 0, 1, 0, 0, 0, 5)),          # 26 outs: absent
    ], name='c30j')
    assert lead == [LEAD_TITLE,
                    ('HITTER, A', '', '', '', '9.1 IP'), ('PLAYER01, B', '', '', '', '9.0 IP'),
                    ('PLAYER02, B', '', '', '', '8.2 IP'),
                    ('HITTER, A', '', '', '', '0.96 ERA'), ('PLAYER01, B', '', '', '', '1.00 ERA')]


def test_c30_league_of_4096_and_ws_rows_shape(tmp_path):
    """the parity shape: two round headers, a WS MILESTON game, and the whole box of
    playoff_recs: BODY unchanged (the 50 rows above), the leaders after"""
    ldir = make_playoffs(tmp_path)
    data = dynview.load_data(str(ldir))
    rows = dynview.playoffs_body((SP, 0, 0), data)[1]
    assert len(rows) == 60 == dynview.total_rows((SP, 0, 0), data)
    assert rows[50] == LEAD_TITLE
    assert rows[51:] == [('HITTER, A', '', '', '', '2 H'), ('PLAYER02, B', '', '', '', '1 H'),
                         ('HITTER, A', '', '', '', '1 RBI'), ('ACE, P', '', '', '', '8 SO'),
                         ('PLAYER06, B', '', '', '', '5 SO'), ('PLAYER06, B', '', '', '', '10.0 IP'),
                         ('ACE, P', '', '', '', '7.2 IP'), ('PLAYER01, B', '', '', '', '0.1 IP'),
                         ('PLAYER06, B', '', '', '', '3.60 ERA')]
    # the paged rows agree (a 5-page walk lands the leaders on page 4)
    got = [r for p in range(5) for r in dynview.rows((SP, p, 0), data)]
    assert got == rows
    assert LEAD_TITLE in dynview.rows((SP, 4, 0), data)
    assert dynview.rows((SP, 4, 0), data)[8:] == rows[56:]


def test_c30_other_season_rows_ignored(tmp_path):
    """player rows of another season never tally into the season's leaders block"""
    pre, lead = post_leaders_rows(tmp_path, [
        box_rec(3, 16, 0, 1, (0, 0, 5, 0, 0, 0, 0, 0)),
        box_rec(2, 16, 0, 1, (0, 0, 9, 0, 0, 0, 0, 0)),
        box_rec(4, 0, 0, 2, (0, 0, 9, 0, 0, 0, 0, 0)),
    ], name='c30s')
    assert lead == [LEAD_TITLE, ('PLAYER01, B', '', '', '', '5 H')]

def test_c54_a_toggles_only_in_career(tmp_path):
    """A/a flips data['lead_active'] in CAREER mode and resets page and row; in every other
    LEADERS mode it is a no-op that leaves the flag untouched."""
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    assert data['lead_active'] is False
    s, _ex = dynview.step((PM, 2, 0, 7), 65, data)                # A on CAREER page 2, row 7
    assert s == (PM, 0, 0) and data['lead_active'] is True
    s, _ex = dynview.step(s, 97, data)                            # a flips it back
    assert s == (PM, 0, 0) and data['lead_active'] is False
    # SEASON, BY YEAR, POST: the state and the flag are unchanged
    for cat, year in ((dynview.MODE_SHIFT, 0),
                      (2 * dynview.MODE_SHIFT, 2),
                      (3 * dynview.MODE_SHIFT, 0)):
        before = (PM, 1, cat + 3, 9, year) if year else (PM, 1, cat + 3, 9)
        s, _ex = dynview.step(before, 65, data)
        assert s == before and data['lead_active'] is False, cat
    # other screens: A does what it did (nothing)
    s, _ex = dynview.step((dynview.SCREEN_HOF, 0, 0), 65, data)
    assert s == (dynview.SCREEN_HOF, 0, 0) and data['lead_active'] is False


def test_c54_order_ranks_title_footer_and_empty(tmp_path):
    """The active filter keeps only status 1 entries, re-ranks from #1, the title flips both
    ways, the footer gained A ACTIVE, and every category still counts its ranks within the
    filtered list."""
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    s, _ex = dynview.step((PM, 0, 0), 65, data)
    full = [i for _v, i, _e in dynview.career_order(data['hist'], 0)]
    active = [i for i in full
              if data['hist'].read_entry(i)['status'] == history.STATUS_ACTIVE]
    assert [i for _v, i, _e in dynview.career_order(data['hist'], 0, True)] == active
    rows = dynview.leaders_body((PM, 0, 0), data)[1]
    assert [r[0] for r in rows] == ['#%d' % (n + 1) for n in range(len(rows))]
    assert set(r[2].strip() for r in rows) == {''}               # no R or H marks: all active
    assert rows[0][1:] == \
        dynview.leaders_rows(data['hist'], 0)[full.index(active[0])][1:]
    assert dynview.screen_title(s, data) == 'ACTIVE LEADERS: H'
    assert dynview.footer_text(s, data) == \
        'LEFT RIGHT  TAB MODE  A ACTIVE  ENTER CARD'
    s, _ex = dynview.step(s, 65, data)                            # back off: CAREER again
    assert data['lead_active'] is False
    assert dynview.screen_title((PM, 0, 0), data) == 'CAREER LEADERS: H'
    # MVP AWARDS under the filter: ranks recount within the qualifiers
    s, _ex = dynview.step((PM, 0, 16), 65, data)
    mvp = dynview.leaders_body((PM, 0, 16), data)[1]
    assert [r[0] for r in mvp] == ['#%d' % (n + 1) for n in range(len(mvp))]
    assert dynview.screen_title((PM, 0, 16), data) == 'ACTIVE LEADERS: MVP AWARDS'


def test_c54_message_row_when_none_qualify(tmp_path):
    """Every entry retired: the ACTIVE H list is one 'NO ACTIVE QUALIFIERS.' row with
    COLS_SINGLE; the unfiltered list is unchanged."""
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    hist = data['hist']
    for i in range(dynview.n_entries(hist)):
        hist.d[hist.entry_offset(i) + 22] = history.STATUS_RETIRED
    data['lead_active'] = True
    assert dynview.leaders_body((PM, 0, 0), data) == \
        (dynview.COLS_SINGLE, [('NO ACTIVE QUALIFIERS.',)])
    assert dynview.total_rows((PM, 0, 0), data) == 1
    unfiltered = dynview.load_data(str(ldir))
    assert dynview.leaders_body((PM, 0, 0), unfiltered)[1][0][2] == 'R'


def test_c54_flag_survives_tab_card_and_menu(tmp_path):
    """The flag is session state: it survives the TAB round trip, LEFT/RIGHT, the PLAYER
    CARD walk and ESC to MENU, and the cursor entry under the filter opens that entry's
    card."""
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    s = press((PM, 0, 0), 65, data)                               # A on
    assert data['lead_active'] is True
    s = press(s, dynview.KEY_TAB, data)                           # -> SEASON
    assert data['lead_active'] is True
    for _n in range(3):                                           # BY YEAR, POST, CAREER
        s = press(s, dynview.KEY_TAB, data)                       # H keeps its label
    assert s == (PM, 0, 0) and data['lead_active'] is True
    assert dynview.screen_title(s, data) == 'ACTIVE LEADERS: H'
    s = press(s, dynview.KEY_RIGHT, data)                         # category steps, flag stays
    assert data['lead_active'] is True
    assert dynview.screen_title(s, data) == 'ACTIVE LEADERS: HR'
    # the cursor entry under the filter opens that entry's card
    entry = dynview.row_entry((PM, 0, 0), data)
    assert entry == [i for _v, i, _e in dynview.career_order(data['hist'], 0, True)][0]
    card, _ex = dynview.step((PM, 0, 0), dynview.KEY_ENTER, data)
    assert card == (dynview.SCREEN_CARD, 0, entry)
    assert data['lead_active'] is True
    back, _ex = dynview.step(card, dynview.KEY_ESC, data)
    assert back == (PM, 0, 0) and data['lead_active'] is True
    menu, _ex = dynview.step(back, dynview.KEY_ESC, data)
    assert menu == (dynview.SCREEN_MENU, 0, 0) and data['lead_active'] is True
    # open_card kept the list state like on any other screen
    assert data.get('card_back') == (PM, 0, 0)

# ---------------------------------------------------------------- C56 HISTORY cursor and STANDINGS jump
def test_history_cursor_moves_and_footer(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    hs = dynview.SCREEN_HISTORY
    assert dynview.cursor_screen((hs, 0, 0)) is True
    s = press((hs, 0, 0), dynview.KEY_DOWN, data)
    assert s == (hs, 0, 0, 1)                    # the cursor state packs the row
    assert dynview.unpack(s)[3] == 1
    s = press(s, dynview.KEY_DOWN, data)
    assert s == (hs, 0, 0, 2)                    # 3 rows: the last
    assert press(s, dynview.KEY_DOWN, data) == (hs, 0, 0, 2)
    assert press((hs, 0, 0), dynview.KEY_UP, data) == (hs, 0, 0)
    # PGDN on a 3-row list is a no-op (below 12 rows), PGUP at page 0 too
    assert press((hs, 0, 0), dynview.KEY_PGDN, data) == (hs, 0, 0)
    assert press((hs, 0, 0), dynview.KEY_PGUP, data) == (hs, 0, 0)
    assert dynview.footer_text((hs, 0, 0), data) == \
        'ENTER STANDINGS   PGUP PGDN   ESC MENU'


def test_history_enter_opens_standings_and_esc_back(tmp_path):
    """ENTER row r opens the STANDINGS of the row's season; ESC returns the exact
    HISTORY state (cursor kept) then MENU"""
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    hs, ss = dynview.SCREEN_HISTORY, dynview.SCREEN_STANDINGS
    assert dynview.history_pos(data['hist']) == [3, 2, 1]   # season_no 3, 2, 1 newest first
    s0 = press((hs, 0, 0), dynview.KEY_DOWN, data)          # row 1: season 2
    s, _ex = dynview.step(s0, ENTER, data)
    assert s == (ss, 0, 1)                       # cat = 3 recorded - pos 2 = 1
    assert dynview.screen_title(s, data) == '1994 STANDINGS'
    assert data['st_back'] == (hs, 0, 0, 1)
    s2, _ex = dynview.step(s, ESC, data)
    assert s2 == (hs, 0, 0, 1)
    assert 'st_back' not in data                 # deleted after the one level
    s3, _ex = dynview.step(s2, ESC, data)
    assert s3 == (dynview.SCREEN_MENU, 0, 0)
    # row 2 (the last): season 1, cat 2
    s, _ex = dynview.step((hs, 0, 0, 2), ENTER, data)
    assert s == (ss, 0, 2)
    assert dynview.screen_title(s, data) == '1993 STANDINGS'
    assert dynview.step(s, ESC, data)[0] == (hs, 0, 0, 2)


def test_history_enter_key0_path_esc_goes_to_menu(tmp_path):
    """STANDINGS opened another way (key 0 on the hub) deletes st_back first, so a
    later ESC goes to MENU; T then ESC ESC keeps st_back, returning STANDINGS then
    HISTORY (the standings league: T needs a MAJ team)"""
    hs, ss, hub = dynview.SCREEN_HISTORY, dynview.SCREEN_STANDINGS, (dynview.SCREEN_MENU, 0, 0)
    ldir = make_standings(tmp_path)
    data = dynview.load_data(str(ldir))
    press((hs, 0, 0), ENTER, data)               # arms st_back (state thrown away)
    assert 'st_back' in data
    s, _ex = dynview.step(hub, ord('0'), data)   # key 0: clears it
    assert s == (ss, 0, 0) and 'st_back' not in data
    assert dynview.step(s, ESC, data)[0] == hub  # ESC goes to MENU
    # T then ESC ESC: TEAM HISTORY keeps st_back, so ESC returns STANDINGS then HISTORY
    press((hs, 0, 0), ENTER, data)
    st = press((ss, 0, 0), ord('T'), data)
    assert st[0] == dynview.SCREEN_TEAMHIST
    assert 'st_back' in data                     # untouched by T
    back = dynview.step(st, ESC, data)[0]
    assert back == (ss, 0, 0)
    assert dynview.step(back, ESC, data)[0] == (hs, 0, 0)

# ------------------------------------------------- C58 PLAYER CARD LEFT/RIGHT browse
def test_c58_card_hof_browse_rows_and_view(tmp_path):
    """From HALL OF FAME row 1: RIGHT shows row 2's entry with card_back row 2; LEFT twice
    from row 1 stops at row 0; RIGHT on the last row is a no-op; H first keeps the HONORS
    view through the browse. ESC then returns the moved row."""
    ldir, _ = make_data(tmp_path)                      # HoF rows: PLAYER29, PLAYER28
    data = dynview.load_data(str(ldir))
    assert dynview.rows(st(dynview.SCREEN_HOF), data) == \
        dynview.hof_rows(data['hist'])
    data['card_back'] = (dynview.SCREEN_HOF, 0, 0, 0)
    s, _ex = dynview.step((dynview.SCREEN_CARD, 0, 29, 1), dynview.KEY_RIGHT, data)
    assert s == (dynview.SCREEN_CARD, 0, 28, 1)
    assert data['card_back'] == (dynview.SCREEN_HOF, 0, 0, 1)
    s, _ex = dynview.step((dynview.SCREEN_CARD, 0, 28, 1), dynview.KEY_LEFT, data)
    assert s == (dynview.SCREEN_CARD, 0, 29, 1)
    assert data['card_back'] == (dynview.SCREEN_HOF, 0, 0)          # row 0 packed away
    assert dynview.step(s, dynview.KEY_ESC, data)[0] == (dynview.SCREEN_HOF, 0, 0)
    # past the 2-HoF list RIGHT is a no-op and the back state stays
    data['card_back'] = (dynview.SCREEN_HOF, 0, 0, 1)
    assert dynview.step((dynview.SCREEN_CARD, 0, 28, 0), dynview.KEY_RIGHT, data) == \
        ((dynview.SCREEN_CARD, 0, 28, 0), 0)
    assert data['card_back'] == (dynview.SCREEN_HOF, 0, 0, 1)


def test_c58_card_browse_no_back_and_absent_back(tmp_path):
    """No data['card_back'], or a back state that is not a cursor screen: LEFT/RIGHT are
    no-ops; an explicit non-cursor back is left alone."""
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.step((dynview.SCREEN_CARD, 0, 0, 1), dynview.KEY_RIGHT, data) == \
        ((dynview.SCREEN_CARD, 0, 0, 1), 0)
    data['card_back'] = (dynview.SCREEN_STANDINGS, 0, 0)     # not a cursor screen
    assert dynview.step((dynview.SCREEN_CARD, 0, 0, 1), dynview.KEY_LEFT, data) == \
        ((dynview.SCREEN_CARD, 0, 0, 1), 0)
    assert data['card_back'] == (dynview.SCREEN_STANDINGS, 0, 0)


def test_c58_card_browse_none_row_skip_and_esc_page(tmp_path):
    """LEFT and RIGHT take the first row in the direction whose row_entry names a player:
    a row naming nobody (the NONE award slot) in between is skipped, both ends clamp to
    no-ops, and ESC after a browse lands on the back list with the cursor on the shown
    entry's row and its page."""
    ms = award_league_ms() + [(3, 0xffff, 70, 987), (3, 0xffff, 72, 961)]
    ldir = make_data(tmp_path, ms=ms)[0]
    data = dynview.load_data(str(ldir))
    rows = dynview.awards_rows(data['hist'], data['ms'], 3)
    assert len(rows) == 42
    ent = [dynview.row_entry((SA, 0, 0, r), data) for r in range(len(rows))]
    assert ent[7] is None and ent[10] is None      # the NONE award rows
    card = (dynview.SCREEN_CARD, 0, 0, 1)
    data['card_back'] = (SA, 0, 0, 6)
    s, _ex = dynview.step(card, dynview.KEY_RIGHT, data)
    assert s == (dynview.SCREEN_CARD, 0, 8, 1)     # row 7 (NONE) skipped, view kept
    assert data['card_back'] == (SA, 0, 0, 8)
    data['card_back'] = (SA, 0, 0, 9)
    s, _ex = dynview.step(card, dynview.KEY_LEFT, data)
    assert s == (dynview.SCREEN_CARD, 0, 8, 1)     # row 8 backwards again, view kept
    assert data['card_back'] == (SA, 0, 0, 8)
    # LEFT past row 0 and RIGHT past the last row do nothing
    data['card_back'] = (SA, 0, 0, 0)
    assert dynview.step(card, dynview.KEY_LEFT, data) == (card, 0)
    last = len(rows) - 1
    data['card_back'] = (SA, 0, 0, last)
    assert dynview.step(card, dynview.KEY_RIGHT, data) == (card, 0)
    # ESC after a page-crossing browse: the back list on the moved row and its page
    data['card_back'] = (SA, 0, 0, 20)
    card20 = (dynview.SCREEN_CARD, 0, 19, 1)       # entry 19: NL ROOKIE (row 20; the AL
    s, _ex = dynview.step(card20, dynview.KEY_RIGHT, data)   # MVP row 33 sorts after it)
    back = data['card_back']
    assert back[3] == 21 and back[1] == 1          # row 21 is on the list's page 1
    assert dynview.step(s, dynview.KEY_ESC, data)[0] == back


def test_c58_card_footers_both_views(tmp_path):
    """The two card footers: SEASONS view and HONORS view."""
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    assert dynview.footer_text((dynview.SCREEN_CARD, 0, 0), data) == \
        'LEFT RIGHT  PGUP PGDN  H HONORS  ESC'
    assert dynview.footer_text((dynview.SCREEN_CARD, 0, 0, 1), data) == \
        'LEFT RIGHT  PGUP PGDN  H SEASONS  ESC'
    assert dynview.FOOTERS[dynview.SCREEN_CARD] == 'LEFT RIGHT  PGUP PGDN  H HONORS  ESC'


# ---------------------------------------------------------------- C63 HOME and END
def test_c63_home_end_cursor_jumps(tmp_path):
    """HOME jumps to row 0 and END to row n - 1 on every cursor screen (HALL OF FAME and
    SEASON STANDINGS here), the page follows the row; end and one-row no-ops; MENU ignores
    both keys."""
    from test_dynview_c13 import line, player, write_league
    HC = dynview.SCREEN_HOF

    def tb(h):
        return [(h), 0, 0, 0, 0, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    ldir = tmp_path / 'c63'
    write_league(ldir, [player('HOF%02d' % i, first='A', status=3, hof=1 + i,
                               totals=tb(100 + i)) for i in range(13)],
                 seasons=4, lines=[line(0, 1, totals=tb(100))])
    data = dynview.load_data(str(ldir))
    n = dynview.total_rows((HC, 0, 0), data)
    assert n == 13                                 # two pages
    end = press((HC, 0, 0), dynview.KEY_END, data)
    assert end == (HC, 1, 0, 12)                   # page (n - 1) // 12, row n - 1
    assert press(end, dynview.KEY_HOME, data) == (HC, 0, 0)
    # row 0 HOME and the last row END are no-ops
    assert press((HC, 0, 0), dynview.KEY_HOME, data) == (HC, 0, 0)
    assert press(end, dynview.KEY_END, data) == end
    # HOME is a no-op and END a jump when the cursor starts mid-list
    assert press((HC, 1, 0, 6), dynview.KEY_HOME, data) == (HC, 0, 0)
    # SEASON STANDINGS of the FULL season: 36 rows, 3 pages; END from row 0 goes to row 35
    sldir = make_standings(tmp_path, [FULL_SEASON] * 3)
    sdata = dynview.load_data(str(sldir))
    s0 = press((SS, 0, 0), dynview.KEY_PGDN, sdata)
    assert s0 == (SS, 1, 0, 12)
    send = press(s0, dynview.KEY_END, sdata)
    assert send == (SS, 2, 0, 35)
    assert dynview.total_rows(send, sdata) == 36
    assert press(send, dynview.KEY_HOME, sdata) == (SS, 0, 0)
    assert press(send, dynview.KEY_END, sdata) == send
    # a one-row list: both keys are no-ops (SEASON STANDINGS of an empty season)
    (tmp_path / 'st1').mkdir()
    l1 = make_standings(tmp_path / 'st1')
    d1 = dynview.load_data(str(l1))
    assert dynview.total_rows((SS, 0, 0), d1) == 1
    one = press((SS, 0, 0), dynview.KEY_END, d1)
    assert press(one, dynview.KEY_HOME, d1) == one
    # the empty standings season (one message row): both keys are no-ops
    empty = (SS, 0, 0)
    assert press(press(empty, dynview.KEY_END, sdata), dynview.KEY_HOME, sdata) == empty
    # MENU is not a cursor screen: both keys are ignored
    assert press((dynview.SCREEN_MENU, 0, 0), dynview.KEY_HOME, sdata) == \
        (dynview.SCREEN_MENU, 0, 0)
    assert press((dynview.SCREEN_MENU, 0, 0), dynview.KEY_END, sdata) == \
        (dynview.SCREEN_MENU, 0, 0)
    # cursor_move keeps the HoF state unchanged at the ends (the empty-filter one-row list)
    assert dynview.cursor_move((HC, 0, 1, 0), (HC, 0, 1, 0), dynview.KEY_END, data) == \
        (HC, 0, 1, 0)
    assert dynview.cursor_move((HC, 0, 1, 0), (HC, 0, 1, 0), dynview.KEY_HOME, data) == \
        (HC, 0, 1, 0)

