#!/usr/bin/env python3
"""Tests for the C29 TEAM HISTORY screen (tools/m4/dynview.py and the C port).
Model rows, the state walk and the frame parity need the synthetic fonts and the
host binary; rendering tests skip without the fonts (DYNVIEW_FILES).
Run:  python3 -m pytest -q tools/m4/test_c29_teamhist.py
"""
import itertools
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import dynview
import history
import pytest
from test_dynview import (make_standings, STAND_SEASONS, write_standings, box_rec,
                          write_box, game_ms)
from test_dynview_c13 import load, make_fonts
from test_dynview_c13_c import needs_fonts

STH = dynview.SCREEN_TEAMHIST
SS = dynview.SCREEN_STANDINGS
T_FOOTER = 'ENTER SEASON  LEFT RIGHT TEAM  PGUP PGDN ESC'
ENTER, ESC = dynview.KEY_ENTER, dynview.KEY_ESC
LEFT, RIGHT = dynview.KEY_LEFT, dynview.KEY_RIGHT
PGUP, PGDN = dynview.KEY_PGUP, dynview.KEY_PGDN


def hist_league(tmp_path, seasons, box=None, mask=None, sub=None,
                stems={0: b'T00', 1: b'T01', 2: b'T02', 16: b'T16'}):
    """make_standings league (under tmp_path/sub when given) whose seasons are the
    (w_l, champ, al_p, nl_p) tuples given (the newest last, so seasons[0] is season 1),
    BOXSCORE.DAT holds box, the HISTORY mask is mask, and the MAJ lists the four stems
    (V20 names BOSTON, DETROIT, CLEVELAND, ATLANTA) unless stems is None (no MAJ)."""
    if sub is not None:
        tmp_path = tmp_path / sub
        tmp_path.mkdir(exist_ok=True)
    ldir = make_standings(tmp_path, seasons=seasons)
    if box is not None:
        write_box(ldir, box)
    p = ldir / 'HISTORY.DAT'
    if mask is not None:
        d = bytearray(p.read_bytes())
        d[12:16] = mask.to_bytes(4, 'little')
        p.write_bytes(bytes(d))
    if stems is None:
        (ldir / 'TEST.MAJ').unlink()
    return ldir


def div_map(ldir, season, divs, ndiv=3):
    """HISTORY.DAT season gets ndiv and the C12.7 map divs = {id: division}."""
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    o = 32 + (season - 1) * 128
    d[o + 22] = ndiv
    for k, div in divs.items():
        d[o + 100 + k // 2] |= div << (4 * (k & 1))
    p.write_bytes(bytes(d))


def press(s, key, data):
    return dynview.step(s, key, data)[0]


def test_ordinal_label():
    """The FINISH ordinal: 1ST..3RD, then %dTH, 11TH..13TH always TH."""
    assert [dynview.ordinal_label(k) for k in (1, 2, 3, 4, 11, 13, 14, 21, 22)] == \
        ['1ST', '2ND', '3RD', '4TH', '11TH', '13TH', '14TH', '21ST', '22ND']


def test_teamhist_columns_fit():
    assert dynview.COLS_TEAMHIST == \
        [('YEAR', dynview._cx(0), 4, 'L'), ('W', dynview._cx(5), 4, 'R'),
         ('L', dynview._cx(10), 4, 'R'), ('PCT', dynview._cx(15), 5, 'R'),
         ('FINISH', dynview._cx(22), 6, 'L'), ('RESULT', dynview._cx(30), 12, 'L')]
    assert all(x + w * dynview.CHAR_W <= 10 + 42 * dynview.CHAR_W
               for _h, x, w, _a in dynview.COLS_TEAMHIST)


# three seasons: BOSTON (0), CLEVELAND (2) and DETROIT (1) play 1993; only CLEVELAND
# plays 1994; only BOSTON and CLEVELAND play 1995. Season 1: BOSTON the champion;
# season 2: CLEVELAND the (WS-losing) AL pennant; season 3: BOSTON in the AL LCS
# (rnd 2 header 0/1) and CLEVELAND in the AL DS (rnd 1 header 0/2)
WL_TH_1 = {0: (10, 4), 1: (8, 6), 2: (4, 10)}
WL_TH_2 = {2: (6, 4), 16: (8, 2)}
WL_TH_3 = {0: (5, 5), 2: (9, 0)}
TH_HEADERS = [box_rec(3, 16, 4, 0 * 256 + 2, (5, 3, 9, 7, 1, 0, 0, 0), b=1, i=1),
              box_rec(3, 23, 4, 0 * 256 + 1, (7, 1, 11, 4, 0, 1, 0, 0), b=2, i=1)]


def th_league(tmp_path):
    return hist_league(tmp_path,
                       seasons=[(WL_TH_1, 0, 0xff, 0xff),
                                (WL_TH_2, 0xff, 2, 0xff),
                                (WL_TH_3, 0xff, 0xff, 0xff)],
                       box=TH_HEADERS)


def test_teamhist_rows_champion_pennant_lcs_ds_absent(tmp_path):
    """One row per season with games, newest first; RESULT champion once, pennant once,
    LCS via a rnd 2 header once, DS via a rnd 1 header once; a season without games
    for the team makes no row. Shared legacy East for ids 0..7 the rank walks."""
    data = load(th_league(tmp_path))
    hist, box = data['hist'], data['box']
    # BOSTON (0): 1995 LCS (the rnd 2 AL LCS header 0/1) but CLEVELAND's 1.000 is the
    # East's first; no 1994 games; 1993 champion (10-4 first of the East)
    assert dynview.team_history_rows(hist, box, 0) == \
        [('1995', '5', '5', '.500', '2ND', 'LCS'),
         ('1993', '10', '4', '.714', '1ST', 'CHAMPION')]
    # CLEVELAND (2): 1995 DS (the rnd 1 header 0/2), 1994 pennant (WS loss),
    # 1993 plain (4-10 under the .714)
    assert dynview.team_history_rows(hist, box, 2) == \
        [('1995', '9', '0', '1.000', '1ST', 'DS'),
         ('1994', '6', '4', '.600', '1ST', 'PENNANT'),
         ('1993', '4', '10', '.285', '3RD', '')]
    # DETROIT (1): no 1994 or 1995 games; 1995 sits in the LCS header 0/1 but DETROIT
    # played only 1993 (plain row)
    assert dynview.team_history_rows(hist, box, 1) == \
        [('1993', '8', '6', '.571', '2ND', '')]


def test_teamhist_rows_finish_rank_ties(tmp_path):
    """FINISH is the standings-order rank among the teams of the league (the same ids
    0..15 in the team's division of the entry) with games: PCT desc, then W desc, then
    id. A PCT tie breaks by W; a W tie by id. Teams of the other division or league
    never count."""
    wl = {0: (10, 6), 1: (20, 12), 2: (10, 6), 16: (30, 0), 8: (40, 0)}
    ldir = hist_league(tmp_path, seasons=[(wl, 0xff, 0xff, 0xff)])
    data = load(ldir)
    hist = data['hist']
    # East (0..7) .625 all three: W 20 puts DETROIT first, the id breaks BOSTON and
    # CLEVELAND; the WEST MILWAUKEE (8) and the NL CINCINNATI (30-0) never count
    assert dynview.team_history_rows(hist, [], 1)[0][4] == '1ST'
    assert dynview.team_history_rows(hist, [], 0)[0][4] == '2ND'
    assert dynview.team_history_rows(hist, [], 2)[0][4] == '3RD'
    # W desc beats PCT-inside-division: not reachable here (same PCT) but the 8 team is
    # above them all in the league and still does not join the rank
    wl2 = {0: (9, 7), 1: (10, 6), 2: (9, 7), 3: (8, 8), 4: (7, 9)}
    ldir = hist_league(tmp_path, seasons=[(wl2, 0xff, 0xff, 0xff)], sub='b')
    hist = load(ldir)['hist']
    # PCT desc first: DETROIT .625 1ST, the .562 pair by id, then .500 and .437
    assert dynview.team_history_rows(hist, [], 3)[0][4] == '4TH'


def test_teamhist_rows_no_rows_message(tmp_path):
    """A team with no games in any season: one message row; the body returns COLS_SINGLE"""
    ldir = make_standings(tmp_path)
    data = load(ldir)
    assert dynview.team_history_rows(data['hist'], [], 15) == \
        [('NO SEASONS RECORDED',)]
    cols, rows = dynview.teamhist_body((STH, 0, 15), data)
    assert cols == dynview.COLS_SINGLE and rows == [('NO SEASONS RECORDED',)]
    assert dynview.total_rows((STH, 0, 15), data) == 1
    assert dynview.body_cols((STH, 0, 15), data) == dynview.COLS_SINGLE
    assert dynview.rows((STH, 0, 15), data) == [('NO SEASONS RECORDED',)]


def test_teamhist_rows_three_divisions_rank(tmp_path):
    """A 3 division entry: the FINISH rank counts the team's own division only, ordered
    as standings_block orders them."""
    wl = {t: (10, 5) for t in range(8)}
    ldir = hist_league(tmp_path, seasons=[(wl, 0xff, 0xff, 0xff)])
    div_map(ldir, 1, {k: (1 if k % 8 < 4 else 2) for k in range(8)})
    hist = load(ldir)['hist']
    # all .667: the rank inside the division follows the id, 4 teams a division
    assert dynview.team_history_rows(hist, [], 4)[0][4] == '1ST'
    assert dynview.team_history_rows(hist, [], 7)[0][4] == '4TH'
    # a W tie with a lower id in the same division: the id wins ('2ND' for id 5)
    assert dynview.team_history_rows(hist, [], 5)[0][4] == '2ND'


def test_teamhist_title_counts(tmp_path):
    """The title '%s  %d TITLES  %d PENNANTS': titles = CHAMPION rows, pennants =
    CHAMPION or PENNANT rows; an unlisted team reads 'TEAM %d'."""
    wl_1 = {0: (10, 4), 2: (4, 10)}
    wl_2 = {0: (6, 4), 2: (8, 2)}
    seasons = [(wl_1, 0, 0xff, 0xff), (wl_2, 0xff, 2, 0xff),
               (WL_TH_3, 0xff, 0xff, 0xff)]
    ldir = hist_league(tmp_path, seasons=seasons)
    data = load(ldir)
    # BOSTON: champion 1993, nothing else -> 1 title, 1 pennant (= the title)
    assert dynview.screen_title((STH, 0, 0), data) == 'BOSTON  1 TITLES  1 PENNANTS'
    assert dynview.screen_title((STH, 0, 2), data) == 'CLEVELAND  0 TITLES  1 PENNANTS'
    # DETROIT (1) never played: the message row counts neither
    assert dynview.screen_title((STH, 0, 1), data) == 'DETROIT  0 TITLES  0 PENNANTS'
    # ST LOUIS (20) is a MAJ team with no games and no titles
    assert dynview.screen_title((STH, 0, 20), data) == 'ST LOUIS  0 TITLES  0 PENNANTS'
    # an id no MAJ team holds: the 'TEAM %d' fallback (id 15 sits in no stem)
    assert dynview.screen_title((STH, 0, 15), data) == 'TEAM 15  0 TITLES  0 PENNANTS'


def test_teamhist_open_esc_and_team_walk(tmp_path):
    """T opens the managed team (the lowest id with the mask bit set), else the first
    of data['teams']; ESC returns the exact standings state (page and cat too); LEFT
    and RIGHT wrap over the listed teams with page 0; PGUP/PGDN page as every list."""
    wl_1 = {0: (5, 5), 1: (10, 4), 2: (4, 10), 16: (8, 2)}
    wl_2 = {1: (6, 4)}
    ldir = hist_league(tmp_path, seasons=[(wl_1, 0, 0xff, 0xff), (wl_2, 0xff, 0xff, 0xff)],
                       mask=1 << 2)
    data = load(ldir)
    # the make_standings MAJ lists 25 teams in id order: 0, 1, 2, then 3 (the NL id 16
    # follows the whole AL)
    ids = [t for t, _ in data['teams']]
    assert ids[:3] == [0, 1, 2] and 16 in ids and len(ids) == 25
    assert data['teams'][0][:2] == (0, 'BOSTON')
    # T on a page-2 season-1 standings: the managed CLEVELAND (2)
    s, _ex = dynview.step((SS, 2, 2), 84, data)
    assert s == (STH, 0, 2)
    assert dynview.footer_text(s, data) == T_FOOTER
    # ESC returns the identical standings state
    assert dynview.step(s, ESC, data) == ((SS, 2, 2), 0)
    # lower case t too
    assert dynview.step((SS, 0, 0), 116, data)[0] == (STH, 0, 2)
    # mask 0: the first team
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12:16] = bytes(4)
    p.write_bytes(bytes(d))
    data = load(ldir)
    assert dynview.step((SS, 0, 0), 84, data)[0] == (STH, 0, 0)
    # a managed team past the first id wins: the mask bit on NEW YORK (3)
    d[12:16] = (1 << 3).to_bytes(4, 'little')
    p.write_bytes(bytes(d))
    data = load(ldir)
    assert dynview.step((SS, 0, 0), 84, data)[0] == (STH, 0, 3)
    # LEFT and RIGHT walk the listed teams in id order and wrap, page 0 (ids 0, 1, 2,
    # then 3 and on; the id before 16 in the MAJ is SEATTLE 13)
    assert press((STH, 3, 1), RIGHT, data) == (STH, 0, 2)
    assert press((STH, 0, 27), RIGHT, data) == (STH, 0, 0)
    assert press((STH, 3, 0), LEFT, data) == (STH, 0, 27)
    assert press((STH, 0, 16), LEFT, data) == (STH, 0, 13)
    # PGDN pages as every list screen (1 row: stays)
    assert press((STH, 2, 2), PGDN, data) == (STH, 2, 2)


TH_ENTER, TH_DOWN = dynview.KEY_ENTER, dynview.KEY_DOWN


_th_n = itertools.count()


def th_league(tmp_path, seasons=None, box=TH_HEADERS, mask=None, sub=None):
    """hist_league over a fresh subdir (each load() call needs its own league dir):
    the (w_l, champ, al_p, nl_p) tuples given (the newest last), BOXSCORE.DAT holds
    box (TH_HEADERS by default) and the HISTORY mask is mask."""
    sub = sub or 'th%d' % next(_th_n)
    return hist_league(tmp_path,
                       seasons=seasons or [(WL_TH_1, 0, 0xff, 0xff),
                                           (WL_TH_2, 0xff, 2, 0xff),
                                           (WL_TH_3, 0xff, 0xff, 0xff)],
                       box=box, mask=mask, sub=sub)


def test_team_history_seasons_align(tmp_path):
    """team_history_seasons is the season number of every team_history_rows row,
    newest first, None on the message row (C60); both run the shared walk."""
    data = load(th_league(tmp_path))
    hist, box = data['hist'], data['box']
    for t in range(4):
        rows = dynview.team_history_rows(hist, box, t)
        seasons = dynview.team_history_seasons(hist, box, t)
        assert len(seasons) == len(rows)
        assert seasons == sorted(seasons, reverse=True)   # newest first
        for season, row in zip(seasons, rows):
            if season is None:
                assert row == ('NO SEASONS RECORDED',)
            else:
                assert len(row) == 6 and row[0] == dynview.year_text(hist, season)
    # BOSTON (0): rows for 1995 then 1993; DETROIT (1): only 1993
    assert dynview.team_history_seasons(hist, box, 0) == [3, 1]
    assert dynview.team_history_seasons(hist, box, 1) == [1]
    # a team with no games: the message row, season None
    ldir = make_standings(tmp_path)
    data = load(ldir)
    assert dynview.team_history_seasons(data['hist'], [], 15) == [None]


def test_teamhist_enter_opens_season_standings(tmp_path):
    """ENTER on a TEAM HISTORY row opens that season's SEASON STANDINGS (cat =
    seasons_recorded - season) and sets st_back to the packed TEAM HISTORY state
    (cursor kept); ESC returns to it, ESC again returns th_back (untouched by ENTER);
    the message row and past-the-end rows are no-ops; DOWN moves the cursor and
    LEFT/RIGHT reset page and row (C60)."""
    wl_1 = {0: (5, 5), 1: (10, 4), 2: (4, 10), 16: (8, 2)}
    wl_2 = {2: (6, 4), 16: (8, 2)}
    ldir = hist_league(tmp_path, seasons=[(wl_1, 0, 0xff, 0xff), (wl_2, 0xff, 0xff, 0xff)],
                       mask=1 << 2)
    data = load(ldir)
    hist = data['hist']
    # CLEVELAND (2): rows 1994 then 1993; ENTER on row 1 opens the 1993 standings
    seasons = dynview.team_history_seasons(hist, data['box'], 2)
    assert seasons == [2, 1]
    s = (STH, 0, 2, 1)
    s2, _ex = dynview.step(s, TH_ENTER, data)
    assert s2 == (SS, 0, hist.seasons_recorded - 1)
    assert data['st_back'] == s
    # ESC back to the TEAM HISTORY row, ESC again to th_back
    s3, _ex = dynview.step(s2, ESC, data)
    assert s3 == s
    assert 'st_back' not in data
    # th_back is untouched by ENTER: it still holds the standings state of the T jump
    data2 = load(ldir)
    s4, _ex = dynview.step((SS, 0, 1), 84, data2)
    assert s4 == (STH, 0, 2)
    assert data2['th_back'] == (SS, 0, 1)
    s5, _ex = dynview.step(s4, TH_ENTER, data2)
    assert s5 == (SS, 0, 0)                          # the 1994 standings (the newest)
    assert data2['st_back'] == (STH, 0, 2)
    s6, _ex = dynview.step(s5, ESC, data2)
    assert s6 == (STH, 0, 2)
    s7, _ex = dynview.step(s6, ESC, data2)
    assert s7 == (SS, 0, 1)
    # an earlier st_back is replaced
    data3 = load(ldir)
    dynview.step((dynview.SCREEN_HISTORY, 0, 0, 0), TH_ENTER, data3)      # an st_back from HISTORY
    s8, _ex = dynview.step((STH, 0, 2, 0), TH_ENTER, data3)
    assert s8 == (SS, 0, 0)
    assert data3['st_back'] == (STH, 0, 2)
    # the message row (TEAM 15, no games in any season, real T fixture list): the
    # message ENTER is a no-op and keeps st_back
    data4 = load(ldir)
    data4['st_back'] = (9, 9, 9)
    r_msg = dynview.team_history_rows(hist, data4['box'], 15)
    assert r_msg == [('NO SEASONS RECORDED',)]
    assert dynview.step((STH, 0, 15, 0), TH_ENTER, data4) == ((STH, 0, 15, 0), 0)
    assert data4['st_back'] == (9, 9, 9)
    # a row past the end is a no-op
    assert dynview.step((STH, 0, 2, 99), TH_ENTER, data4) == ((STH, 0, 2, 99), 0)
    # DOWN moves the cursor; LEFT and RIGHT step the team with page and row reset
    data5 = load(ldir)
    assert press((STH, 0, 2, 0), TH_DOWN, data5) == (STH, 0, 2, 1)
    assert press((STH, 1, 2, 2), LEFT, data5) == (STH, 0, 1)
    assert press((STH, 1, 2, 2), RIGHT, data5) == (STH, 0, 3)
    # the footer and the cursor screen flag
    assert dynview.footer_text((STH, 0, 2, 1), data5) == \
        'ENTER SEASON  LEFT RIGHT TEAM  PGUP PGDN ESC'
    assert dynview.cursor_screen((STH, 0, 2, 1))
    assert dynview.row_entry((STH, 0, 2, 1), data5) is None


def test_teamhist_paging_cursor(tmp_path):
    """PGUP / PGDN move the cursor like on every cursor screen (C60): PGDN puts it on
    the next page's first row when the page changes, PGUP back."""
    wl = {t: (10 + t, 5) for t in range(4)}
    seasons = [({t: (10 + t + s, 5) for t in range(4)}, 0xff, 0xff, 0xff)
               for s in range(15)]
    ldir = hist_league(tmp_path, seasons=seasons)
    data = load(ldir)
    hist = data['hist']
    assert len(dynview.team_history_rows(hist, data['box'], 0)) == 15
    s = (STH, 0, 0, 0)
    assert press(s, PGDN, data) == (STH, 1, 0, 12)
    assert press((STH, 1, 0, 12), PGUP, data) == (STH, 0, 0)
    # PGDN with no next page stays
    assert press((STH, 1, 0, 12), PGDN, data) == (STH, 1, 0, 12)


def test_teamhist_enter_after_history_roundtrip(tmp_path):
    """The full C56 / C60 chain: HISTORY row ENTER to STANDINGS, STANDINGS row ENTER
    to TEAM HISTORY, TEAM HISTORY row ENTER to that season's STANDINGS, then ESC ESC
    ESC back to TEAM HISTORY and ESC to the first STANDINGS."""
    ldir = th_league(tmp_path, sub='rt')
    data = load(ldir)
    n = data['hist'].seasons_recorded
    s, _ex = dynview.step((dynview.SCREEN_HISTORY, 0, 0, 0), TH_ENTER, data)
    assert s == (SS, 0, n - 3)                       # the 1993 standings (season 1)
    s, _ex = dynview.step(s, dynview.KEY_DOWN, data)
    assert s == (SS, 0, n - 3, 1)
    s, _ex = dynview.step(s, TH_ENTER, data)
    assert s == (STH, 0, 2)                          # the row-1 team's history (CLE)
    s, _ex = dynview.step(s, TH_ENTER, data)
    assert s == (SS, 0, n - 3)                       # CLEVELAND 1995's standings (season 3)
    assert data['st_back'] == (STH, 0, 2)            # the earlier st_back is replaced
    s, _ex = dynview.step(s, ESC, data)
    assert s == (STH, 0, 2)                          # the TEAM HISTORY row is kept
    s, _ex = dynview.step(s, ESC, data)
    assert s == (SS, 0, n - 3, 1)                    # the held th_back row
    s, _ex = dynview.step(s, ESC, data)
    assert s == (dynview.SCREEN_MENU, 0, 0)          # st_back was replaced by the C60 ENTER


def test_teamhist_no_teams_t_nothing(tmp_path):
    """An empty data['teams'] (no MAJ): T does nothing on SEASON STANDINGS; the rows
    and the title still read the fallback names."""
    ldir = hist_league(tmp_path, seasons=list(STAND_SEASONS), stems=None)
    data = load(ldir)
    assert data['teams'] == []
    assert dynview.step((SS, 0, 0), 84, data) == ((SS, 0, 0), 0)
    assert dynview.step((SS, 0, 0), 116, data) == ((SS, 0, 0), 0)
    rows = dynview.team_history_rows(data['hist'], [], 15)   # TEAM 15 has no games
    assert rows == [('NO SEASONS RECORDED',)]


def test_teamhist_left_right_screens_and_title_click():
    """SCREEN_TEAMHIST sits in LEFT_RIGHT_SCREENS, so a title-band click is LEFT/RIGHT;
    its footer carries no MENU tail."""
    assert dynview.SCREEN_TEAMHIST in dynview.LEFT_RIGHT_SCREENS
    assert dynview.FOOTERS[SS] == 'ENTER TEAM  LEFT RIGHT SEASON  PGUP PGDN ESC'
    assert dynview.FOOTERS[dynview.SCREEN_TEAMHIST] == \
        'ENTER SEASON  LEFT RIGHT TEAM  PGUP PGDN ESC'


def test_teamhist_title_click_walk(tmp_path):
    """click_to_key on the TEAM HISTORY title band gives LEFT / RIGHT (the team steps
    over the listed teams)."""
    data = load(th_league(tmp_path))
    ids = [t for t, _ in data['teams']]
    assert dynview.click_to_key((STH, 0, 2), data, 100, 14) == (dynview.KEY_LEFT, None)
    assert dynview.click_to_key((STH, 0, 2), data, 200, 18) == (dynview.KEY_RIGHT, None)
    key, _row = dynview.click_to_key((STH, 0, 2), data, 200, 18)
    # RIGHT: the next listed team is NEW YORK (3) in the make_standings MAJ
    assert press((STH, 0, 2), key, data) == (STH, 0, ids[ids.index(2) + 1])
    key, _row = dynview.click_to_key((STH, 0, 2), data, 100, 14)
    assert press((STH, 0, 2), key, data) == (STH, 0, 1)
    # the wrap at the last team
    key, _row = dynview.click_to_key((STH, 0, ids[-1]), data, 200, 18)
    assert press((STH, 0, ids[-1]), key, data) == (STH, 0, ids[0])


@needs_fonts
def test_teamhist_render_frames(tmp_path):
    """The hosted render of a champion team's history (frames are 64000 B and the
    title carries the team's title line) and the standings' new footer."""
    fonts = make_fonts(tmp_path / 'fonts')
    ldir = th_league(tmp_path)
    data = load(ldir, fonts)
    s, _ex = dynview.step((SS, 0, 0), 84, data)
    fb = bytes(dynview.render(s, data))
    assert len(fb) == 64000
    assert dynview.footer_text(s, data) == T_FOOTER
    assert dynview.screen_title(s, data) == 'BOSTON  1 TITLES  1 PENNANTS'


# ---------------------------------------------------------------- C57 standings row cursor
def test_standings_teams_align(tmp_path):
    """standings_teams aligns with standings_rows on the message and standings seasons
    (None on the header and message rows, the ids in standings order otherwise)."""
    ldir = make_standings(tmp_path, seasons=STAND_SEASONS)
    data = dynview.load_data(str(ldir))
    rows = dynview.standings_rows(data['hist'], data['teams'], 1)
    tids = dynview.standings_teams(data['hist'], data['teams'], 1)
    assert len(rows) == len(tids)
    for r, tid in zip(rows, tids):
        if r[0] and r[1:] != ('', '', '', '', ''):
            assert isinstance(tid, int)
            assert r[0].lstrip('*') == dict(data['teams']).get(tid,
                                                               'TEAM %d' % tid)
        else:
            assert tid is None
    assert dynview.standings_rows(data['hist'], data['teams'], 3) == \
        [('NO STANDINGS RECORDED',)]
    assert dynview.standings_teams(data['hist'], data['teams'], 3) == [None]
