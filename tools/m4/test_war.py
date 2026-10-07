#!/usr/bin/env python3
"""Tests for the M4 WAR reference (tools/m4/war.py, contract C3).
Run:  python3 -m pytest -q tools/m4/test_war.py
All fixtures are synthetic (tmp_path), no game files are needed.
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import war
from v20 import Team, F, _set, _get
import maj

from test_history import make_team_v20, make_maj


def idiv_ref(a, b):
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


MAJ_SIZE = 59771


def test_idiv_truncates_toward_zero():
    assert war.idiv(7, 2) == 3
    assert war.idiv(-7, 2) == -3        # Python -7 // 2 = -4; idiv must give -3
    assert war.idiv(7, -2) == -3
    assert war.idiv(-7, -2) == 3
    assert war.idiv(0, 5) == 0
    assert war.idiv(100, 3) == 33
    assert war.idiv(-100, 3) == -33


def set_batter(t, i, AB, h, d, tt, hr, bb, sb, cs, runs, games, pos1, rng, arm):
    """set a season-half stat line (L+R halves summed by putting it all in _l)."""
    s = t.players[i + 40].raw
    t.players[i].raw[0] = 1
    t.players[i + 40].raw[0] = 1
    _set(t.players[i].raw, *F['pos1'], pos1)
    _set(t.players[i + 40].raw, *F['pos1'], pos1)
    _set(s, *F['games'], games)
    _set(s, *F['ab_l'], AB); _set(s, *F['h_l'], h); _set(s, *F['d_l'], d)
    _set(s, *F['t_l'], tt); _set(s, *F['hr_l'], hr); _set(s, *F['bb_l'], bb)
    _set(s, *F['sb'], sb); _set(s, *F['cs'], cs); _set(s, *F['runs'], runs)
    _set(t.players[i].raw, *F['range'], rng)
    _set(t.players[i].raw, *F['arm'], arm)
    _set(t.players[i + 40].raw, *F['range'], rng)
    _set(t.players[i + 40].raw, *F['arm'], arm)


def set_pitcher(t, i, ip10, er, games):
    s = t.players[i + 40].raw
    t.players[i].raw[0] = 1
    t.players[i + 40].raw[0] = 1
    _set(t.players[i].raw, *F['pos1'], 0)
    _set(t.players[i + 40].raw, *F['pos1'], 0)
    _set(s, *F['games'], games)
    _set(s, *F['ip10'], ip10)
    _set(s, *F['er'], er)


def test_batter_war_hand_case1(tmp_path):
    """Single batter, everything in the _l half. C3 by hand:
    AB 500 H 150 2B 30 3B 5 HR 20 BB 60 SB 10 CS 5 R 80, games 150, C (pos 1),
    range 8 arm 6. lw100 = 47*95 + 78*30 + 109*5 + 140*20 + 33*60 + 20*10 - 41*5
    - 27*350 = 2675. L_lw = 2675, L_pa = 560 -> bat100 = 0, park100 = 0.
    repl100 = 2000*560/600 = 1866; posadj = 1250*150/162 = 1157;
    fld = ((8-6)*150 + (6-6)*50)*150/162 = 32400*... = 277;
    war10 = (0 + 1866 + 1157 + 277)/100 = 33."""
    d = make_team_v20()
    t = Team(d)
    set_batter(t, 0, 500, 150, 30, 5, 20, 60, 10, 5, 80, 150, 1, 8, 6)
    f = tmp_path / 'TEAM.V20'
    t.save(str(f))
    per, lg = war.season_league([(str(f), 0)])
    s = t.players[40].raw
    roster = t.players[0].raw
    lgz = dict(lg, pf1000=1000)
    w = war.batter_war10(s, roster, 150, lgz)
    assert lg['L_lw'] == 2675 and lg['L_pa'] == 560 and lg['L_runs'] == 80
    assert per[(0, 0)] == 33
    assert w == 33


def test_batter_war_hand_case2_negative_with_park(tmp_path):
    """Weak DH with hitters' park (pf 1100). By hand: AB 450 H 95 2B 18 3B 1 HR 4
    BB 20 SB 2 CS 9 R 35, games 140, DH (pos 9), range 5 arm 5.
    s1 = 72, lw100 = -3797; L = self -> bat100 = -3797 pre-park;
    park100 = ((100*35)/20 * 470)/470 = 175; bat100 = -3972... recomputed below in-code.
    Expected war10 = -2 (hand-computed from C3 with idiv toward zero)."""
    t = Team(make_team_v20())
    set_batter(t, 0, 450, 95, 18, 1, 4, 20, 2, 9, 35, 140, 9, 5, 5)
    f = tmp_path / 'TEAM.V20'
    t.save(str(f))
    per, lg = war.season_league([(str(f), 0)])
    lgz = dict(lg, pf1000=1100)
    s, roster = t.players[40].raw, t.players[0].raw
    # park100 = idiv(idiv(100*35,20)*470,470) = idiv(175*470,470) = 175
    w = war.batter_war10(s, roster, 140, lgz)
    assert lg['L_lw'] == -3797      # 47*72 + 78*18 + 109*1 + 140*4 + 33*20 + 2*2 - 41*9 - 27*355
    # direct C3 chain:
    lw100 = -3797
    bat100 = lw100 - idiv_ref(lg['L_lw'] * 470, lg['L_pa'])
    park100 = idiv_ref(idiv_ref((1100 - 1000) * lg['L_runs'], 20) * 470, lg['L_pa'])
    bat100 -= park100
    repl100 = idiv_ref(2000 * 470, 600)
    posadj100 = idiv_ref(-1750 * 140, 162)
    fld100 = idiv_ref(((5 - 6) * 150 + (5 - 6) * 50) * 140, 162)
    expected = idiv_ref(bat100 + repl100 + posadj100 + fld100, 100)
    assert w == expected == -2      # bad DH with a hitters' park: negative WAR
    # season_league sees no MAJ here (pf fallback 1000): still negative, milder
    assert per[(0, 0)] == -1


def test_batter_war_league_subtraction(tmp_path):
    """Two batters: bat100 must be lw100 minus the league PA-weighted average.
    With two identical players bat100 = lw - L_lw*pa/L_pa = lw - lw = 0."""
    t = Team(make_team_v20())
    line = (400, 110, 22, 3, 12, 40, 8, 4, 55)
    set_batter(t, 0, *line, 140, 4, 7, 6)
    set_batter(t, 1, *line, 140, 3, 7, 6)
    f = tmp_path / 'TEAM.V20'
    t.save(str(f))
    per, lg = war.season_league([(str(f), 0)])
    ab, h = 400, 110
    s1 = h - 22 - 3 - 12
    lw = 47 * s1 + 78 * 22 + 109 * 3 + 140 * 12 + 33 * 40 + 20 * 8 - 41 * 4 - 27 * (ab - h)
    assert lg['L_lw'] == 2 * lw
    # identical lines: L_lw*pa == lw*pa*2, L_pa = 2*pa -> idiv = lw exactly
    assert per[(0, 0)] == per[(0, 1)]


def test_pitcher_war_single_league(tmp_path):
    """One pitcher: pit100 = L_er*120*outs/L_outs - er*100 = er*120 - er*100 = er*20.
    IP 180.0 (ip10 1800) ER 80 -> outs 540, pit100 = 1600, war10 = 16."""
    t = Team(make_team_v20())
    set_pitcher(t, 0, 1800, 80, 30)
    f = tmp_path / 'TEAM.V20'
    t.save(str(f))
    per, lg = war.season_league([(str(f), 0)])
    assert lg['L_outs'] == 540 and lg['L_er'] == 80
    assert per[(0, 0)] == 16


def test_pitcher_war_negative_two_pitchers(tmp_path):
    """Two pitchers, one good (180.0 IP, 60 ER), one bad (60.1 IP, 50 ER).
    Hand: outs_a = 540, outs_b = 3*60 + 1 = 181? ip10 601 -> 3*60 + 1 = 181.
    L_er = 110, L_outs = 721.
    A: pit100 = idiv(110*120*540, 721) - 6000 -> war10 per C3.
    B: negative (bad ER over few outs) -> hand-checked in-code, plus idiv sign."""
    t = Team(make_team_v20())
    set_pitcher(t, 0, 1800, 60, 30)
    set_pitcher(t, 1, 601, 50, 25)
    f = tmp_path / 'TEAM.V20'
    t.save(str(f))
    per, lg = war.season_league([(str(f), 0)])
    outs_a, outs_b = 540, 181
    L_er, L_outs = 110, outs_a + outs_b
    assert lg['L_er'] == L_er and lg['L_outs'] == L_outs
    pit_a = idiv_ref(L_er * 120 * outs_a, L_outs) - 60 * 100
    pit_b = idiv_ref(L_er * 120 * outs_b, L_outs) - 50 * 100
    assert per[(0, 0)] == idiv_ref(pit_a, 100)
    assert per[(0, 1)] == idiv_ref(pit_b, 100) < 0
    # idiv rounds toward zero: -1632/100 -> -16, never -17
    assert idiv_ref(-1632, 100) == -16


def test_pitcher_war_zero_outs_league(tmp_path):
    """No outs recorded anywhere: war10 = 0 when L_outs == 0. ip10 = 999 -> outs 3*99+9."""
    t = Team(make_team_v20())
    set_pitcher(t, 0, 0, 3, 5)
    s = t.players[40].raw
    lg = {'L_er': 0, 'L_outs': 0}
    assert war.pitcher_war10(s, 5, lg) == 0


def test_pitcher_outs_formula():
    """C2 outs = (ip10 // 10) * 3 + ip10 % 10, toward zero."""
    assert war.ipiv_outs(1800) == 540
    assert war.ipiv_outs(601) == 181
    assert war.ipiv_outs(90) == 27
    assert war.ipiv_outs(0) == 0


def test_park_factor_clamp_and_fallback():
    """pf1000 = 1000*(home_rs+home_ra)*away_g / ((away_rs+away_ra)*home_g),
    clamped 900..1100; 1000 if any term is 0."""
    # clamp high: home 3000 RS+RA vs away 800 over equal games -> 3750 -> 1100
    assert war.park_factor1000(2000, 1000, 81, 500, 300, 81) == 1100
    # clamp low: 500 vs 3800 -> 131 -> 900
    assert war.park_factor1000(300, 200, 81, 2000, 1800, 81) == 900
    # symmetric -> 1000 exactly
    assert war.park_factor1000(700, 700, 81, 700, 700, 81) == 1000
    # fallbacks: any zero term -> 1000
    assert war.park_factor1000(0, 0, 81, 700, 700, 81) == 1000
    assert war.park_factor1000(700, 700, 0, 700, 700, 81) == 1000
    assert war.park_factor1000(700, 700, 81, 0, 0, 0) == 1000


def test_park_factor_midrange():
    """A value inside the clamp band passes through; below 900 clamps up."""
    assert war.park_factor1000(1100, 0, 100, 1900, 0, 100) == 900   # 578 -> clamped
    assert war.park_factor1000(1900, 0, 100, 2000, 0, 100) == 950   # 950 in band
    assert war.park_factor1000(2090, 0, 100, 1900, 0, 100) == 1100  # 1100 in band


def test_park_from_maj(tmp_path):
    """A synthetic MAJ with played games: team 1 hosts a slugfest and plays a
    pitchers' duel on the road -> pf between, e.g. 933; a team with only road
    blowouts at both extremes clamps; unplayed team falls back to nothing."""
    p = tmp_path / 'CLASSIC.MAJ'
    m = maj.Maj(bytes(MAJ_SIZE))
    # day 8: team 0 at team 1, home 12-2 win
    m.d[maj.LG['AL'] + maj.O_SCHED + 16 * 8] = 0
    m.d[maj.LG['AL'] + maj.O_SCHED + 16 * 8 + 1] = 1
    rb = maj.LG['AL'] + maj.O_RUNS + 32 * 8
    m.d[rb], m.d[rb + 1] = 2, 12
    m.d[maj.LG['AL'] + maj.O_PLAYED + 2 * 8] = 0x80
    # day 9: team 1 at team 2, road 5-10 loss
    m.d[maj.LG['AL'] + maj.O_SCHED + 16 * 9] = 1
    m.d[maj.LG['AL'] + maj.O_SCHED + 16 * 9 + 1] = 2
    rb = maj.LG['AL'] + maj.O_RUNS + 32 * 9
    m.d[rb], m.d[rb + 1] = 5, 10
    m.d[maj.LG['AL'] + maj.O_PLAYED + 2 * 9] = 0x80
    p.write_bytes(bytes(m.d))
    pf = war.park_factors(str(p))
    # team 1: home 12+2 = 14 over 1 game, road 5+10 = 15 over 1 game
    # pf = 1000*14*1 idiv (15*1) = 933
    assert pf[1] == 933
    # team 0 played only on the road: no home games -> any-term-0 fallback 1000
    assert pf[0] == 1000
    # team 3 played nothing: not in the table
    assert 3 not in pf


def test_jaws():
    """C2 JAWS10 = (career + sum of used top-7) / 2 toward zero."""
    top = [60, 55, 50, 45, 40, 35, 30]
    assert war.jaws10(320, top) == 317            # (320 + 315)/2
    assert war.jaws10(321, top) == 318            # 636/2 exact
    # fewer than 7 used: -32768 sentinels are ignored
    assert war.jaws10(100, [40, 20, -32768, -32768, -32768, -32768, -32768]) == 80
    # negative career: toward zero
    assert war.jaws10(-3, [1, -32768, -32768, -32768, -32768, -32768, -32768]) == -1


def test_hof_criteria_alone():
    base = {'seasons_played': 12}
    for kw, val in [('H', 3000), ('HR', 500), ('W', 300), ('PSO', 3000), ('SV', 400),
                    ('WAR10', 600), ('JAWS10', 500)]:
        assert war.hof_passes(dict(base, **{kw: val})), kw
        assert not war.hof_passes(dict(base, **{kw: val - 1})), kw
    # batting average branch: AB >= 5000 and H*1000/AB >= 300
    assert war.hof_passes(dict(base, AB=5000, H=1500))
    assert war.hof_passes(dict(base, AB=6000, H=1800))
    assert not war.hof_passes(dict(base, AB=5000, H=1499))
    assert not war.hof_passes(dict(base, AB=4999, H=1500))     # AB short
    # seasons < 10 blocks everything
    for kw, val in [('H', 4000), ('HR', 700), ('WAR10', 900), ('JAWS10', 800)]:
        assert not war.hof_passes(dict(base, seasons_played=9, **{kw: val})), kw
    assert not war.hof_passes({'seasons_played': 9, 'H': 3000})


def test_hof_batting_avg_idiv():
    """H*1000/AB truncates toward zero: exactly-300 passes, 299 fails. The AB gate
    itself requires AB >= 5000 (4999 with an idiv-300 avg still fails)."""
    assert war.hof_passes({'seasons_played': 10, 'AB': 5000, 'H': 1500})   # 300
    assert not war.hof_passes({'seasons_played': 10, 'AB': 5001, 'H': 1500})  # 299
    assert not war.hof_passes({'seasons_played': 10, 'AB': 4999, 'H': 1500})  # AB gate


v20_SIZE = 11735
maj_SIZE = 59771
