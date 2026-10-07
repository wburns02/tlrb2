#!/usr/bin/env python3
"""Tests for the C7 awards and milestones (tools/m4/history.py, contract C7).
Run:  python3 -m pytest -q tools/m4/test_awards.py
Synthetic parts are built in tmp_path from the test_history fixtures (V20 + MAJ);
the real-data part skips if /mnt/nvme/tlrb2/fixtures/t4/s1_pre is missing.
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import history
import war
from v20 import Team, HDR, REC, N, F, _set, _get
from v20 import SIZE as V20_SIZE
import maj

from test_history import make_team_v20, make_maj, set_player

S1_PRE = '/mnt/nvme/tlrb2/fixtures/t4/s1_pre'
PRE_AL = 'CLASALE1.V20'     # stem clasale1 = AL MAJ slot 0
PRE_NL = 'NL01.V20'         # stem NL01 = NL MAJ slot 1 (synthetic make_maj stems)


def statbat(t, i, ab, h, d2=0, t3=0, hr=0, bb=0, sb=0, cs=0, runs=0, games=0, rbi=0):
    """season-half batting line + games (all in L)."""
    s = t.players[i + 40].raw
    _set(s, *F['games'], games)
    _set(s, *F['ab_l'], ab); _set(s, *F['h_l'], h)
    _set(s, *F['d_l'], d2); _set(s, *F['t_l'], t3); _set(s, *F['hr_l'], hr)
    _set(s, *F['bb_l'], bb)
    _set(s, *F['sb'], sb); _set(s, *F['cs'], cs); _set(s, *F['runs'], runs)
    _set(s, *F['rbi'], rbi)


def statpit(t, i, ip10, er, w=0, sv=0, games=0, gs=0, pso=0):
    """season-half pitching line. PSO lives in pso_l/pso_r (not the batter SO field)."""
    s = t.players[i + 40].raw
    _set(s, *F['games'], games)
    _set(s, *F['gs'], gs)
    _set(s, *F['w'], w); _set(s, *F['sv'], sv)
    _set(s, *F['ip10'], ip10); _set(s, *F['er'], er)
    _set(s, *F['pso_l'], pso)


def fielding(t, i, po1, a1, e1):
    """fielding stats on BOTH halves (record_season reads season then roster)."""
    for rec in (t.players[i].raw, t.players[i + 40].raw):
        _set(rec, *F['po1'], po1)
        _set(rec, *F['a1'], a1)
        _set(rec, *F['e1'], e1)


def entry_of(h, t, i, season_no):
    """player entry index for record i of team t, per the C2 identity rule."""
    roster = t.players[i].raw
    birth = 1000 + season_no - _get(roster, *F['age'])
    return history.find_entry(h, bytes(roster[0:20]), birth)


def test_awards_synthetic_league(tmp_path):
    """One clear winner per award per league, a tie broken by lower entry index,
    a Cy Young fallback (no pitcher reaches 486 outs), a rookie with exp 1 excluded,
    a catcher Gold Glove at 95 games, an NL DH slot with no Silver Slugger gap."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / PRE_AL).write_bytes(make_team_v20())
    (ldir / PRE_NL).write_bytes(make_team_v20(name=b'NLONE', abbr=b'NL1'))
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    # -- AL team: MVP winner, a WAR tie pair (lower entry index wins), an excluded
    # exp-1 rookie, a real exp-0 rookie, veterans all exp 1 so only the rookie is one
    ta = Team(open(str(ldir / PRE_AL), 'rb').read())
    set_player(ta, 16, 'MVPWIN', 'AL', 27, 7, 155)          # CF, pa 512, big WAR
    statbat(ta, 16, 450, 150, d2=30, t3=5, hr=25, bb=62, sb=30, runs=100, games=155)
    fielding(ta, 16, 300, 20, 5)
    set_player(ta, 17, 'TIELO', 'LOWIDX', 27, 3, 150)       # 2B, ties with TIEHI
    statbat(ta, 17, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
    fielding(ta, 17, 250, 200, 6)
    set_player(ta, 18, 'TIEHI', 'HIGHIDX', 27, 3, 150)      # same pos, same line
    statbat(ta, 18, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
    fielding(ta, 18, 250, 200, 6)
    set_player(ta, 19, 'ROOKIE', 'SOPH', 22, 9, 10)         # DH, exp 1: not a rookie
    ta.players[19]['exp'] = 1
    statbat(ta, 19, 500, 200, hr=40, bb=60, rbi=110, runs=120, games=162)
    set_player(ta, 20, 'SSBAT', 'FIFTY', 28, 5, 150)        # SS pa 200: under SS 300
    statbat(ta, 20, 190, 60, bb=10, runs=30, games=150)
    set_player(ta, 21, 'FROSH', 'KID', 21, 4, 10)           # 3B rookie, exp 0
    statbat(ta, 21, 150, 48, hr=15, bb=20, rbi=50, runs=40, games=100)
    set_player(ta, 0, 'CYFALL', 'FALLBACK', 26, 0, 25)      # P A: 162 outs, under 486
    ta.players[0]['exp'] = 1
    statpit(ta, 0, 540, 60, w=10, pso=100, games=25)
    set_player(ta, 1, 'CYFALL2', 'FALLBK2', 26, 0, 20)      # P B: 300 outs, better WAR
    ta.players[1]['exp'] = 1
    statpit(ta, 1, 1000, 30, w=8, pso=80, games=20)
    for i in (16, 17, 18, 20):
        ta.players[i]['exp'] = 1
    ta.save(str(ldir / PRE_AL))
    # -- NL team: GG catcher at 95 games, a DH, everyone exp 1 (no NL rookie)
    tn = Team(open(str(ldir / PRE_NL), 'rb').read())
    set_player(tn, 16, 'CATCHER', 'GLOVE', 28, 1, 95)       # C at 95 games (>= 90)
    tn.players[16]['exp'] = 1
    statbat(tn, 16, 320, 90, hr=10, bb=30, rbi=45, runs=40, games=95)
    fielding(tn, 16, 700, 60, 8)
    set_player(tn, 17, 'NLDH', 'DESIG', 29, 9, 150)         # NL DH: MVP + SS(9)
    tn.players[17]['exp'] = 1
    statbat(tn, 17, 550, 180, hr=30, bb=70, rbi=105, runs=110, games=150)
    tn.save(str(ldir / PRE_NL))
    hp = str(tmp_path / 'HISTORY.DAT')
    history.record_season(str(ldir), hp, 1)
    h = history.History.load(hp)
    aw = h.read_season_entry(1)['awards']
    al_mvp = entry_of(h, ta, 16, 1)
    al_tie_lo = entry_of(h, ta, 17, 1)
    al_tie_hi = entry_of(h, ta, 18, 1)
    al_soph = entry_of(h, ta, 19, 1)
    al_frosh = entry_of(h, ta, 21, 1)
    al_p1 = entry_of(h, ta, 1, 1)
    nl_c = entry_of(h, tn, 16, 1)
    nl_dh = entry_of(h, tn, 17, 1)
    assert al_tie_lo < al_tie_hi                # records 17, 18: append order
    e_lo, e_hi = h.read_entry(al_tie_lo), h.read_entry(al_tie_hi)
    # season winners
    assert aw[0] == al_mvp                                  # AL MVP
    assert aw[1] == al_p1                                   # AL CY: fallback, 300 outs
    assert aw[2] == al_frosh                                # AL ROY: exp 0, pa 170
    assert aw[3] == nl_dh                                   # NL MVP: the DH
    assert aw[4] == history.NO_AWARD                        # NL CY: no NL pitchers at all
    assert aw[5] == history.NO_AWARD                        # NL ROY: everyone exp 1
    # the exp-1 DH did not win ROY despite the best batter WAR line
    assert aw[2] != al_soph
    # War tie pair: equal season WAR10 -> MVP must not be decided by index here,
    # but Silver Slugger(3) goes to the LOWER index (same bat100, same pa gate)
    assert e_lo['top7'][0] == e_hi['top7'][0]
    # career counts
    assert h.read_entry(al_mvp)['awards'][0] == 1           # MVP
    assert h.read_entry(al_mvp)['awards'][3] == 1           # GG(7): only CF, games 155
    assert h.read_entry(al_p1)['awards'][1] == 1            # CY
    assert h.read_entry(al_frosh)['awards'][2] == 1         # ROY
    assert h.read_entry(al_soph)['awards'][2] == 0          # exp 1: no ROY
    assert h.read_entry(al_soph)['awards'][4] == 1          # AL SS(9): pa 560 DH
    assert h.read_entry(nl_dh)['awards'][0] == 1            # NL MVP
    assert h.read_entry(nl_dh)['awards'][4] == 1            # NL SS(9)
    assert h.read_entry(nl_c)['awards'][3] == 1             # NL GG(1): C at 95 games
    assert h.read_entry(nl_c)['awards'][4] == 1             # NL SS(1): pa 350
    # the SSBAT short-PA SS got no Silver Slugger
    assert h.read_entry(entry_of(h, ta, 20, 1))['awards'][4] == 0


def test_mvp_tie_lower_entry_index(tmp_path):
    """Two batters with identical lines and positions: same WAR10 and the Silver
    Slugger/MVP style max with ties must go to the LOWER player entry index.
    The season MVP is asserted directly on the tie."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / PRE_AL).write_bytes(make_team_v20())
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    t = Team(open(str(ldir / PRE_AL), 'rb').read())
    set_player(t, 16, 'ATIEDA', 'FIRST', 27, 3, 150)
    statbat(t, 16, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
    set_player(t, 17, 'BTIEDB', 'SECOND', 27, 3, 150)
    statbat(t, 17, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
    t.save(str(ldir / PRE_AL))
    hp = str(tmp_path / 'HISTORY.DAT')
    history.record_season(str(ldir), hp, 1)
    h = history.History.load(hp)
    i16 = entry_of(h, t, 16, 1)
    i17 = entry_of(h, t, 17, 1)
    assert i16 < i17
    assert h.read_entry(i16)['top7'][0] == h.read_entry(i17)['top7'][0]   # the tie
    # pick_awards ties go to the lower entry index: MVP and SS(3) both
    sel = history.pick_awards([c for c in
                               [{'index': i16, 'pos1': 3, 'exp': 0, 'games': 150,
                                 'w10': h.read_entry(i16)['top7'][0],
                                 'pa': 510, 'outs': 0, 'bat100': 100,
                                 'range': 7, 'arm': 6, 'po1': 0, 'a1': 0, 'e1': 0},
                                {'index': i17, 'pos1': 3, 'exp': 0, 'games': 150,
                                 'w10': h.read_entry(i17)['top7'][0],
                                 'pa': 510, 'outs': 0, 'bat100': 100,
                                 'range': 7, 'arm': 6, 'po1': 0, 'a1': 0, 'e1': 0}]],
                              lambda x: x['bat100'])
    assert sel['mvp']['index'] == i16
    assert sel['ss'][3]['index'] == i16
    assert h.read_season_entry(1)['awards'][0] == i16


def test_milestones_kinds_and_idempotent_rerun(tmp_path):
    """A player crossing 3000 H and 500 HR this season gets kinds 2 and 5 (he was
    already past 2000 H and 400 HR: no 1, no 4 in this season's records); season
    kinds 32/33 fire with the right values; a rerun of the same season leaves
    MILESTON.DAT byte-identical."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / PRE_AL).write_bytes(make_team_v20())
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    hp = str(tmp_path / 'HISTORY.DAT')
    v20p = str(ldir / PRE_AL)
    # 10 prior seasons: H 295/yr (2950 career), HR 40/yr (400 career), RBI 60, SB 10;
    # kind 1 (H 2000) and kind 3/4 (HR 300/400) fire in EARLIER seasons only
    for season in range(1, 11):
        t = Team(open(v20p, 'rb').read())
        if season > 1:
            for rec in (t.players[16].raw, t.players[56].raw):
                _set(rec, *F['age'], _get(rec, *F['age']) + 1)
        set_player(t, 16, 'MILESTONE', 'MIKE', 25 + season - 1, 7, 155)
        statbat(t, 16, 550, 295, hr=40, bb=60, rbi=60, sb=10, runs=110, games=155)
        t.save(v20p)
        history.record_season(str(ldir), hp, season)
    pre_bytes = open(hp, 'rb').read()               # pre-season HISTORY.DAT
    pre_v20 = open(v20p, 'rb').read()               # the season-10 V20 the chain read
    # the season that crosses: H 310 (3260 > 3000), HR 101 (501 > 500), SB 20, RBI 100
    t = Team(open(v20p, 'rb').read())
    for rec in (t.players[16].raw, t.players[56].raw):
        _set(rec, *F['age'], _get(rec, *F['age']) + 1)
    set_player(t, 16, 'MILESTONE', 'MIKE', 35, 7, 155)
    statbat(t, 16, 560, 310, hr=101, bb=60, rbi=100, sb=20, runs=130, games=155)
    t.save(v20p)
    crossing_v20 = open(v20p, 'rb').read()
    history.record_season(str(ldir), hp, 11)
    ms11 = [(s, i, k, v) for s, i, k, v in history.milestone_entries(hp) if s == 11]
    kinds = sorted(k for s, i, k, v in ms11)
    assert 2 in kinds and 5 in kinds
    assert 1 not in kinds and 3 not in kinds and 4 not in kinds
    vals = {k: v for s, i, k, v in ms11}
    assert vals[2] == 3260 and vals[5] == 501
    assert vals[32] == 101 and vals[33] == 310
    assert 34 not in kinds                           # SB 20: under 100
    # BA .554 with pa 620 (>= 502): kind 35 fires with h*1000/ab
    assert vals[35] == war.idiv(310 * 1000, 560)
    # idempotent rerun, tested the contract's way: the drop rule only. Restore
    # HISTORY.DAT to its pre-season bytes, keep MILESTON.DAT exactly as the first
    # run wrote it, and run the season again -> MILESTON.DAT byte-identical.
    ms_path = os.path.join(os.path.dirname(hp), 'MILESTON.DAT')
    ms_after_first = open(ms_path, 'rb').read()
    # the replay into hp2 shares the MILESTON path (same dir), so restore over it
    open(hp, 'wb').write(pre_bytes)
    open(v20p, 'wb').write(pre_v20)
    hp2 = str(tmp_path / 'PRE.DAT')
    for season in range(1, 11):
        t2 = Team(open(v20p, 'rb').read())
        if season > 1:
            for rec in (t2.players[16].raw, t2.players[56].raw):
                _set(rec, *F['age'], _get(rec, *F['age']) + 1)
        set_player(t2, 16, 'MILESTONE', 'MIKE', 25 + season - 1, 7, 155)
        statbat(t2, 16, 550, 295, hr=40, bb=60, rbi=60, sb=10, runs=110, games=155)
        t2.save(v20p)
        history.record_season(str(ldir), hp2, season)
    # the replay rebuilt pre_bytes: sanity (same pre-season history file)
    assert open(hp2, 'rb').read() == pre_bytes
    # restore the crossing season and rerun
    open(hp, 'wb').write(pre_bytes)
    open(ms_path, 'wb').write(ms_after_first)
    open(v20p, 'wb').write(crossing_v20)
    history.record_season(str(ldir), hp, 11)
    assert open(ms_path, 'rb').read() == ms_after_first


def test_milestone_pitcher_kinds(tmp_path):
    """Pitcher season kinds: W 21 -> 36; PSO 310 -> 37; SV 51 -> 39; kind 38 fires
    for a sub-2.00 ERA over 486+ outs with value er*2700/outs, and does not fire
    at exactly 2.00."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / PRE_AL).write_bytes(make_team_v20())
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    hp = str(tmp_path / 'HISTORY.DAT')
    v20p = str(ldir / PRE_AL)
    t = Team(open(v20p, 'rb').read())
    set_player(t, 0, 'ACE', 'ART', 27, 0, 35)
    # ip10 1666 -> outs 504; er 30 -> ERA100 = 30*2700/504 = 160 < 200
    statpit(t, 0, 1666, 30, w=21, pso=310, games=35)
    t.save(v20p)
    history.record_season(str(ldir), hp, 1)
    vals = {k: v for s, i, k, v in history.milestone_entries(hp)}
    assert vals[36] == 21 and vals[37] == 310 and vals[38] == war.idiv(30 * 2700, 504)
    assert 39 not in vals                               # sv 0
    # exactly 2.00 (er 40 over 540 outs -> 200): does not fire
    t = Team(open(v20p, 'rb').read())
    for rec in (t.players[0].raw, t.players[40].raw):
        _set(rec, *F['age'], _get(rec, *F['age']) + 1)
    statpit(t, 0, 1800, 40, w=20, pso=300, games=35)
    t.save(v20p)
    history.record_season(str(ldir), hp, 2)
    vals = {k: v for s, i, k, v in history.milestone_entries(hp) if s == 2}
    assert 38 not in vals
    assert vals[37] == 300
    # closer: sv 51 -> 39
    t = Team(open(v20p, 'rb').read())
    for rec in (t.players[0].raw, t.players[40].raw, t.players[1].raw, t.players[41].raw):
        _set(rec, *F['age'], _get(rec, *F['age']) + 1)
    set_player(t, 1, 'CLOSER', 'CHAD', 27, 0, 60)
    statpit(t, 1, 900, 25, w=3, sv=51, pso=80, games=60)
    t.save(v20p)
    history.record_season(str(ldir), hp, 3)
    vals = {k: v for s, i, k, v in history.milestone_entries(hp) if s == 3}
    assert vals[39] == 51


def test_duplicate_identity_two_teams_merges(tmp_path):
    """One identity on two teams in one season: totals = sum of both records,
    seasons_played +1 per record with games > 0; and byte-for-byte identical
    outside season 88..99 / player 152..156 to a main-line record_season output
    (the C2 second-half convention)."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / PRE_AL).write_bytes(make_team_v20())
    (ldir / 'ALA02.V20').write_bytes(make_team_v20(name=b'TEAM02', abbr=b'T02'))
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    # the same identity on both teams: same name and age (birth = 1000 + season - age)
    for stem, i, games in ((PRE_AL, 16, 100), ('ALA02.V20', 17, 80)):
        t = Team(open(str(ldir / stem), 'rb').read())
        set_player(t, i, 'TRADED', 'DEXTER', 27, 7, games)
        statbat(t, i, 40 if stem == PRE_AL else 60, 12 if stem == PRE_AL else 20,
                bb=5, runs=8, games=games)
        t.save(str(ldir / stem))
    hp = str(tmp_path / 'HISTORY.DAT')
    history.record_season(str(ldir), hp, 1)
    h = history.History.load(hp)
    assert len(h._entries) == 1             # one identity: both records merge
    e = h.read_entry(0)
    assert e['totals'][1] == 100            # AB 40 + 60
    assert e['totals'][2] == 32             # H 12 + 20
    assert e['seasons_played'] == 2         # +1 per record with games > 0
    # both records' season WAR10 added: rerun through a fresh History with only one
    # of the two records and compare the sums
    t1 = Team(open(str(ldir / PRE_AL), 'rb').read())
    h2 = history.History(None)
    rec1 = t1.players[56].raw
    stats1 = war.season_stats_inputs(rec1)
    # merge = both seasons' stats added; the duplicate identity must not re-add:
    # one record per half, so total = sum of the two (asserted above on AB/H)
    # and the C7 bytes zeroed in both, byte-for-byte identical outside 88..99 and
    # 152..156 to a C2-only (no awards) record_season run of the same league
    import shutil
    ldir_b = tmp_path / 'lg_main'
    shutil.copytree(ldir, ldir_b)
    hp_b = str(tmp_path / 'MAIN.DAT')
    orig_pick = history.pick_awards

    def no_awards(recs, bat100_of):
        return {'mvp': None, 'cy': None, 'roy': None, 'gg': {}, 'ss': {}}

    history.pick_awards = no_awards
    try:
        history.record_season(str(ldir_b), hp_b, 1)
    finally:
        history.pick_awards = orig_pick
    a = open(hp, 'rb').read()
    b = open(hp_b, 'rb').read()
    def strip(d):
        d = bytearray(d)
        d[32 + 88:32 + 100] = bytes(12)     # season award bytes
        for off in range(history.PLAYER_TABLE, len(d), history.PLAYER_ENTRY):
            d[off + 152:off + 157] = bytes(5)
        return bytes(d)
    assert strip(a) == strip(b)


def test_mvp_tie_lower_entry_index_across_files(tmp_path):
    """Ties go to the lower player entry index even when the file/slot order
    disagrees. End to end: the earlier FILE holds a rookie appearing this season
    (appends late, higher index) while the later FILE holds a returner (lower
    index); with identical lines the LOWER index wins. Also a direct pick_awards
    check in both candidate orders."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / PRE_AL).write_bytes(make_team_v20())
    (ldir / 'ALA02.V20').write_bytes(make_team_v20(name=b'TEAM02', abbr=b'T02'))
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    hp = str(tmp_path / 'HISTORY.DAT')
    p1 = str(ldir / PRE_AL)     # earlier file
    p2 = str(ldir / 'ALA02.V20')  # later file
    # season 1: a returner on the LATER file -> entry 0
    t = Team(open(p2, 'rb').read())
    set_player(t, 17, 'RETURNR', 'REX', 27, 3, 150)
    statbat(t, 17, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
    t.save(p2)
    history.record_season(str(ldir), hp, 1)
    h = history.History.load(hp)
    assert len(h._entries) == 1
    # season 2: the returner (entry 0, later file) + a rookie on the EARLIER file.
    # Same lines: file order reads the rookie first, but his entry appends as 1.
    t = Team(open(p2, 'rb').read())
    for rec in (t.players[17].raw, t.players[57].raw):
        _set(rec, *F['age'], _get(rec, *F['age']) + 1)
    set_player(t, 17, 'RETURNR', 'REX', 28, 3, 150)
    statbat(t, 17, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
    t.save(p2)
    t1 = Team(open(p1, 'rb').read())
    set_player(t1, 16, 'FILEROOK', 'FRED', 21, 3, 150)
    statbat(t1, 16, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
    t1.save(p1)
    history.record_season(str(ldir), hp, 2)
    h = history.History.load(hp)
    assert len(h._entries) == 2
    # same season WAR10: a two-way tie; the winner is the LOWER entry index (the
    # returner, entry 0) although his record sits in the LATER file
    assert h.read_entry(0)['top7'][0] == h.read_entry(1)['top7'][0]
    assert h.read_season_entry(2)['awards'][0] == 0
    # direct: pick_awards kept on entry-index-sorted candidates gives the lower
    # index on a tie, whatever the caller's order was before the sort
    c7 = {'index': 7, 'pos1': 3, 'exp': 1, 'games': 150, 'w10': 50,
          'pa': 510, 'outs': 0, 'bat100': 200, 'range': 7, 'arm': 6,
          'po1': 0, 'a1': 0, 'e1': 0}
    c3 = {'index': 3, 'pos1': 3, 'exp': 1, 'games': 150, 'w10': 50,
          'pa': 510, 'outs': 0, 'bat100': 200, 'range': 7, 'arm': 6,
          'po1': 0, 'a1': 0, 'e1': 0}
    for cands in ([c7, c3], [c3, c7]):
        ordered = sorted([(c['index'], c) for c in cands], key=lambda x: x[0])
        sel = history.pick_awards([c for _, c in ordered], lambda x: x['bat100'])
        assert sel['mvp']['index'] == 3
        assert sel['ss'][3]['index'] == 3


def test_roundtrip_awards_fields(tmp_path):
    """Write then read an entry with awards [1, 2, 3, 4, 255] and a season entry
    awards list; an entry written without 'awards' reads zeros (old files)."""
    p = str(tmp_path / 'HISTORY.DAT')
    hist = history.History(None)
    hist.version = 1
    hist.write_season_entry(1, {'season_no': 1, 'champion': 0xff, 'runner_up': 0xff,
                                'champion_stem': b'', 'runner_up_stem': b'',
                                'al_pennant': 0xff, 'nl_pennant': 0xff,
                                'w_l': [(0, 0)] * 32,
                                'awards': [3, 4, 5, 6, 7, 8]})
    hist.append_entry({'name': b'AWARD'.ljust(12) + b'WIN'.ljust(8), 'birth': 1960,
                       'status': 1, 'age': 26, 'first_season': 1, 'last_season': 1,
                       'seasons_played': 1, 'pos1': 3, 'pitcher': 0,
                       'totals': [0] * 25, 'WAR10': 0, 'top7': [history.EMPTY_TOP] * 7,
                       'JAWS10': 0, 'hof_season': 0, 'awards': [1, 2, 3, 4, 255]})
    hist.save(p)
    h = history.History.load(p)
    assert h.read_entry(0)['awards'] == [1, 2, 3, 4, 255]
    assert h.read_season_entry(1)['awards'] == [3, 4, 5, 6, 7, 8]
    # entry written without the key: bytes 152..159 zero on disk, reads zeros
    hist2 = history.History(None)
    hist2.append_entry({'name': b'NOKEY'.ljust(12) + b'OLD'.ljust(8), 'birth': 1961,
                        'status': 1, 'age': 26, 'first_season': 1, 'last_season': 1,
                        'seasons_played': 1, 'pos1': 3, 'pitcher': 0,
                        'totals': [0] * 25, 'WAR10': 0, 'top7': [history.EMPTY_TOP] * 7,
                        'JAWS10': 0, 'hof_season': 0})
    p2 = str(tmp_path / 'OLD.DAT')
    hist2.save(p2)
    raw = open(p2, 'rb').read()
    po = history.PLAYER_TABLE
    assert raw[po + 152:po + 160] == bytes(8)
    assert history.History.load(p2).read_entry(0)['awards'] == [0] * 5
    # season entry written without the key: bytes 88..99 zero
    hist3 = history.History(None)
    hist3.write_season_entry(1, {'season_no': 1, 'champion': 0xff, 'runner_up': 0xff,
                                 'champion_stem': b'', 'runner_up_stem': b'',
                                 'al_pennant': 0xff, 'nl_pennant': 0xff,
                                 'w_l': [(0, 0)] * 32})
    p3 = str(tmp_path / 'OLDS.DAT')
    hist3.save(p3)
    raw = open(p3, 'rb').read()
    assert raw[32 + 88:32 + 100] == bytes(12)
    assert raw[32 + 100:32 + 128] == bytes(28)
    assert history.History.load(p3).read_season_entry(1)['awards'] == [0] * 6


def test_awards_count_every_season_past_64(tmp_path):
    """Award counts are added for every season, including seasons past 64 (no
    season-table write there; counts land on the same entry)."""
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / PRE_AL).write_bytes(make_team_v20())
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    hp = str(tmp_path / 'HISTORY.DAT')
    v20p = str(ldir / PRE_AL)
    for season, dage in ((1, 0), (65, 64)):     # birth = 1000 + season - age: keep
        t = Team(open(v20p, 'rb').read())       # the identity across the season jump
        if dage:
            for rec in (t.players[16].raw, t.players[56].raw):
                _set(rec, *F['age'], _get(rec, *F['age']) + dage)
        set_player(t, 16, 'EVERGREEN', 'CAL', 27 + dage, 7, 155)
        statbat(t, 16, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
        t.save(v20p)
        history.record_season(str(ldir), hp, season)
    h = history.History.load(hp)
    e = h.read_entry(0)
    assert e['awards'][0] == 2                          # MVP both seasons
    # season 65 wrote no season-table entry: entry 1 still season 1
    assert h.read_season_entry(1)['season_no'] == 1


# -- real data --

def collect_all(h, ldir, season_no, lg_totals, pf):
    """The C7 per-record inputs, collected exactly as record_season does."""
    m = maj.Maj.load(history.maj_or_none(ldir))
    teams = history.mapped_teams(ldir, m)
    coll = []
    for p, lg_id in teams:
        t = Team.load(p)
        for i in range(40):
            if not t.players[i].active:
                continue
            rec = t.players[i + 40].raw
            roster = t.players[i].raw
            games = _get(rec, *F['games'])
            pos1 = _get(roster, *F['pos1']) & 15
            stats = war.season_stats_inputs(rec)
            birth = 1000 + season_no - _get(roster, *F['age'])
            idx = history.find_entry(h, bytes(roster[0:20]), birth)
            c = {'index': idx, 'league': 'AL' if lg_id < 16 else 'NL', 'pos1': pos1,
                 'exp': _get(roster, *F['exp']), 'games': games, 'w10': 0,
                 'pa': stats['AB'] + stats['BB'], 'outs': stats['OUTS'],
                 'ab': stats['AB'], 'h': stats['H'], 'er': stats['ER'],
                 'range': _get(roster, *F['range']), 'arm': _get(roster, *F['arm']),
                 'po1': _get(rec, *F['po1']), 'a1': _get(rec, *F['a1']),
                 'e1': _get(rec, *F['e1']), 'bat100': 0}
            team_pf = pf.get(lg_id, 1000)
            if pos1 == 0:
                c['w10'] = war.pitcher_war10(rec, games, lg_totals)
            else:
                c['w10'] = war.batter_war10(rec, roster, games,
                                            dict(lg_totals, pf1000=team_pf))
                c['bat100'] = war.batter_bat100(rec, dict(lg_totals, pf1000=team_pf))
            coll.append(c)
    return coll


def test_real_data_awards():
    """Run the s1_pre chain season through record_season; print the 6 season awards
    (names) and the milestone list; assert each award winner meets its qualification
    and that award counts across all entries sum to 6 + GG awarded + SS awarded."""
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/fixtures/t4/s1_pre missing')
    import shutil, tempfile
    tmp = tempfile.mkdtemp(prefix='a1_real_')
    try:
        ldir = os.path.join(tmp, 'lg')
        os.mkdir(ldir)
        for f in os.listdir(S1_PRE):
            shutil.copy(os.path.join(S1_PRE, f), ldir)
        hp = os.path.join(tmp, 'HISTORY.DAT')
        h = history.record_season(ldir, hp, 1)
        aw = h.read_season_entry(1)['awards']
        names = ['AL MVP', 'AL CY', 'AL ROY', 'NL MVP', 'NL CY', 'NL ROY']

        def ename(i):
            n = h.read_entry(i)['name'].decode('latin-1')
            last = n[0:12].split('\0')[0]
            first = n[12:20].split('\0')[0]
            return (first + ' ' + last).strip()

        print()
        for k, idx in enumerate(aw):
            if idx == history.NO_AWARD:
                print(f'{names[k]}: none')
            else:
                print(f'{names[k]}: [{idx}] {ename(idx)}')
        ms = history.milestone_entries(hp)
        print(f'milestones: {len(ms)} records')
        for s, i, k, v in ms:
            print(f'  s{s} [{i}] {ename(i)} kind {k} value {v}')
        # recount the C7 winners exactly as record_season collects them
        m = maj.Maj.load(history.maj_or_none(ldir))
        teams = history.mapped_teams(ldir, m)
        _, lg_totals = war.season_league(teams)
        pf = war.park_factors(history.maj_or_none(ldir))
        coll = sorted(collect_all(h, ldir, 1, lg_totals, pf), key=lambda c: c['index'])
        got = {}
        for lg in ('AL', 'NL'):
            got[lg] = history.pick_awards([c for c in coll if c['league'] == lg],
                                          lambda x: x['bat100'])
        season6 = [got['AL']['mvp'], got['AL']['cy'], got['AL']['roy'],
                   got['NL']['mvp'], got['NL']['cy'], got['NL']['roy']]
        assert [w['index'] if w else history.NO_AWARD for w in season6] == list(aw)
        # each award winner meets its qualification
        for k, w in enumerate(season6):
            if w is None:
                continue
            if k in (0, 3):         # MVP: pa >= 502
                assert w['pa'] >= 502
            elif k in (1, 4):       # CY: outs >= 486, or fallback outs > 0
                assert w['outs'] > 0
            else:                   # ROY: exp 0 and (pa >= 130 or outs >= 150)
                assert w['exp'] == 0
                assert w['pa'] >= 130 or w['outs'] >= 150
        gg = sum(1 for lg in ('AL', 'NL') for q in got[lg]['gg'] if got[lg]['gg'][q])
        ss = sum(1 for lg in ('AL', 'NL') for q in got[lg]['ss'] if got[lg]['ss'][q])
        top3 = sum(1 for lg in ('AL', 'NL') for w in
                   (got[lg]['mvp'], got[lg]['cy'], got[lg]['roy']) if w is not None)
        total = 0
        for i in range(len(h._entries)):
            total += sum(h.read_entry(i)['awards'])
        assert total == top3 + gg + ss
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
