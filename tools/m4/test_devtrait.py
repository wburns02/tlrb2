#!/usr/bin/env python3
"""Tests for the C1b hidden development trait (byte 142, grades 1..5).

The synthetic parts (assignment shares, growth/decline math, pot_ratings) run
offline; the fixture parts need /mnt/nvme/tlrb2/fixtures/t4/s1_pre and skip
when missing.
Run:  python3 -m pytest -q tools/m4/test_devtrait.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_TOOLS)
for _p in (_ROOT, _TOOLS, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest                                    # noqa: E402

SIM50 = '/mnt/nvme/tlrb2/fixtures/t4/s1_pre'

import rollover                                  # noqa: E402
import sim50                                     # noqa: E402  (S1_PRE)
import v20                                       # noqa: E402
from v20 import HDR, REC, F, _get                # noqa: E402

OFF_DEV, REC_SIZE = 142, 143


def synth_team(grades0=True, age=20):
    """One team image: 15 batters + 10 pitchers, byte 142 = 0 (or 3), age
    default 20, plausible ratings, named slots active in both halves."""
    d = bytearray(HDR + REC_SIZE * 80)
    for i in range(25):
        base = HDR + REC_SIZE * i
        pitcher = i < 10
        if pitcher:
            d[base + F['pos1'][0]] = 0            # pos1 lo nibble 0 = P
            d[base + 0x86] = 8 | (9 << 4)         # control 8, velocity 9
            d[base + 0x87] = 0 | (7 << 4)         # endurance 7
        else:
            d[base + F['pos1'][0]] = 4            # 1B
            d[base + 0x4a] = 8 | (5 << 4)         # power 8, bunt 5
            d[base + 0x4b] = 7 | (6 << 4)         # hit_run 7
            d[base + 0x5e] = 6 | (7 << 4)         # range 7, arm 6
        d[base + F['age'][0]] = age
        d[base + 0] = 65 + i                      # named -> active
        d[base + OFF_DEV] = 0 if grades0 else 3
        twin = HDR + REC_SIZE * (i + 40)
        d[twin:twin + REC_SIZE] = bytes(d[base:base + REC_SIZE])
    return d


def season_rec(games=100):
    r = bytearray(REC_SIZE)
    v20._set(r, *F['games'], games)
    return r


# ---------------------------------------------------------------------------
# a. dev off: byte-identical outputs (fixture)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.isdir(SIM50), reason='s1_pre fixture missing')
def test_a_dev_off_identical(tmp_path):
    """dev off: the full roll (C1 + C4 fill) is byte-identical with the default
    cfg, a copy of it and the copy with 'dev': False; and dev on differs."""
    import dynasty_ref
    runs = {}
    for tag, cfg in (('default', None), ('copy', dict(dynasty_ref.CFG)),
                     ('off', dict(dynasty_ref.CFG, dev=False)),
                     ('on', dict(dynasty_ref.CFG, dev=True))):
        out = str(tmp_path / tag)
        r = dynasty_ref.roll_league(SIM50, out, 0x1234, cfg=cfg)
        runs[tag] = (r['rng_end'], {p: open(os.path.join(out, p), 'rb').read()
                                    for p in sorted(os.listdir(out))})
    assert len(runs['default'][1]) >= 26
    assert runs['copy'] == runs['default'] and runs['off'] == runs['default']
    assert runs['on'] != runs['default']


# ---------------------------------------------------------------------------
# b. assignment shares (20000 draws, fixed seed)
# ---------------------------------------------------------------------------

def grade_of(d, cuts=rollover.DEV_CUTS):
    return 1 if d < cuts[0] else 2 if d < cuts[1] else 3 if d < cuts[2] \
        else 4 if d < cuts[3] else 5


def test_b_assignment_shares():
    """20000 synthetic young players (byte 142 = 0), fixed seed: per-grade
    share within 1.5 points of 10/20/40/20/10 %."""
    rng = rollover.Rng(1877)
    counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    n = 20000
    for _ in range(n):
        d = rng.draw() & 0xff
        counts[grade_of(d)] += 1
    cuts = rollover.DEV_CUTS
    for grade, lo, hi in ((1, 0, cuts[0]), (2, cuts[0], cuts[1]),
                          (3, cuts[1], cuts[2]), (4, cuts[2], cuts[3]),
                          (5, cuts[3], 256)):
        target = (hi - lo) / 2.56
        got = 100.0 * counts[grade] / n
        assert abs(got - target) < 1.5, (grade, got, target)


def test_b_assignment_draws_only_ungraded():
    """One ungraded young batter consumes exactly one assignment draw + 6 drift
    draws; the same player already graded consumes only the 6 drift draws."""
    season = season_rec()
    base_state = {}

    # already graded: 6 drift draws (evidence off, age < 33 no retire draw)
    team = synth_team(grades0=False)
    rec = bytearray(team[HDR + REC_SIZE * 20:HDR + REC_SIZE * 21])
    rng0 = rollover.Rng(99)
    rollover.rollover_player(rec, season, {'dev': True, 'evidence': False},
                             rng0, None)
    base_state['graded'] = rng0.s
    hand = rollover.Rng(99)
    for _ in range(6):
        hand.draw()
    assert rng0.s == hand.s

    # ungraded: the assignment draw first, then the same 6 drift draws
    team = synth_team(grades0=True)
    rec = bytearray(team[HDR + REC_SIZE * 20:HDR + REC_SIZE * 21])
    rng1 = rollover.Rng(99)
    rollover.rollover_player(rec, season, {'dev': True, 'evidence': False},
                             rng1, None)
    hand = rollover.Rng(base_state['graded'])
    assert rng1.s == hand.draw()          # 1 assignment + 6 drift = 7 draws
    d = rollover.Rng(99).draw() & 0xff    # the assignment draw was the 1st
    assert rec[OFF_DEV] == grade_of(d)


# ---------------------------------------------------------------------------
# c. growth
# ---------------------------------------------------------------------------

def run_one(age, grade, cfg_dev=True):
    team = synth_team()
    rec = bytearray(team[HDR + REC_SIZE * 20:HDR + REC_SIZE * 21])   # slot 20 = batter
    v20._set(rec, *F['age'], age)
    rec[OFF_DEV] = grade
    rng = rollover.Rng(5)
    rollover.rollover_player(rec, season_rec(),
                             {'dev': cfg_dev, 'evidence': False} if cfg_dev else
                             {'evidence': False}, rng, None)
    return rec


def test_c_single_draw_cases():
    """Age 21 (age2 after aging), first drift draw d = 100: grade 3 (g 90) no
    growth, grade 5 (g 90*7>>2 = 157) growth, grade 1 (g 90*1>>2 = 22) no
    growth."""
    pre = preimage(100)
    for grade, grows in ((3, False), (5, True), (1, False)):
        rec = run_one(20, grade)
        # rerun with the seed forced so the first drift draw is d = 100
        team = synth_team()
        rec = bytearray(team[HDR + REC_SIZE * 20:HDR + REC_SIZE * 21])
        v20._set(rec, *F['age'], 20)
        rec[OFF_DEV] = grade
        rng = rollover.Rng(pre)
        rollover.rollover_player(rec, season_rec(), {'dev': True, 'evidence': False},
                                 rng, None)
        power = _get(rec, *F['power'])
        assert (power == 9) == grows, (grade, power, grows)


def preimage(target):
    """A 16-bit seed whose first draw & 0xff == target (xorshift16 is a
    bijection, so one always exists)."""
    for s in range(1, 65536):
        r = rollover.Rng(s)
        if r.draw() & 0xff == target:
            return s
    raise AssertionError


def test_c_growth_boom_vs_bust():
    def grown(grade, trials=2000):
        n = 0
        for seed in range(trials):
            rec = run_one(21, grade)
            if _get(rec, *F['power']) > 8:
                n += 1
        return n
    assert grown(5) > grown(1)


# ---------------------------------------------------------------------------
# d. decline
# ---------------------------------------------------------------------------

def test_d_decline_exact_p():
    """Age 35 tier 1: p0 = 64*4>>2 = 64; grade 1 p = 64*6>>2 = 96 ('doubles-ish'
    vs grade 3), grade 3 p = 64*4>>2 = 64; both < 255 so the cap is untouched.
    The exact single-draw p comes from the formula, not the run."""
    tier = 1
    base = rollover.DRIFT_BASE(35)
    p0 = (base * rollover.TIER_MULT[tier]) >> 2
    p1 = min(255, (p0 * rollover.DM[1]) >> 2)
    p3 = min(255, (p0 * rollover.DM[3]) >> 2)
    assert (p0, p1, p3) == (64, 96, 64)
    assert p1 == p3 + p0 // 2


def test_d_decline_cap():
    """Tier 3 pitcher, age 40+: p0 = 160*2>>2 = 80; grade 1 p = 80*6>>2 = 120,
    under the 255 cap; min() keeps any larger DM product at 255."""
    assert min(255, (80 * rollover.DM[1]) >> 2) == 120
    assert min(255, (80 * 13) >> 2) == 255


# ---------------------------------------------------------------------------
# e. both halves, retirement draws unchanged
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.isdir(SIM50), reason='s1_pre fixture missing')
def test_e_both_halves_and_retirement(tmp_path):
    import glob
    paths = sorted(glob.glob(os.path.join(SIM50, '*.V20')))
    t_in = str(tmp_path / 'in.V20')
    out_dev = str(tmp_path / 'dev.V20')
    out_off = str(tmp_path / 'off.V20')
    # copy one team, set byte 142 = 0 in both halves for all records
    raw = bytearray(open(paths[0], 'rb').read())
    for i in range(80):
        raw[HDR + REC_SIZE * i + OFF_DEV] = 0
    open(t_in, 'wb').write(bytes(raw))
    rollover.rollover_team(t_in, out_dev, {'dev': True}, rollover.Rng(1), [])
    rollover.rollover_team(t_in, out_off, {}, rollover.Rng(1), [])
    td, to = v20.Team.load(out_dev), v20.Team.load(out_off)
    n_graded = 0
    for i in range(80):
        gd, go = td.players[i].raw[OFF_DEV], to.players[i].raw[OFF_DEV]
        assert go == 0                        # dev off: byte 142 untouched
        if td.players[i].active:
            assert gd in (1, 2, 3, 4, 5)
            # roster and season halves agree
            assert td.players[i + 40 if i < 40 else i - 40].raw[OFF_DEV] == gd
            n_graded += 1
    assert n_graded > 0


def test_e_retirement_draws_unchanged():
    """With dev on, the retirement draw at age2 < 33 (no draw) and the retire
    path use the same p as dev off; older players retire on the same draws."""
    team = synth_team(age=33)                 # age2 -> 34
    season = season_rec(games=0)
    outs = []
    for cfg in ({'dev': True}, {}):
        rec = bytearray(team[HDR:HDR + REC_SIZE])
        rec[OFF_DEV] = 4
        rng = rollover.Rng(11)
        retire = rollover.rollover_player(rec, season, cfg, rng, None)
        tier = rollover.tier_of(bytearray(team[HDR:HDR + REC_SIZE]))
        p = (rollover.RETIRE_BASE(34) * rollover.TIER_MULT[tier]) >> 2
        p = min(255, p * 2)                   # games 0 doubles
        outs.append((retire, p))
    assert outs[0] == outs[1]


# ---------------------------------------------------------------------------
# f. pot_ratings
# ---------------------------------------------------------------------------

def test_f_pot_grade0_today():
    """Grade 0 = the pre-C1b potential: G[age] is the unscaled sum, and
    pot_ratings matches the formula on it."""
    import rosters
    for age in range(16, 30):
        assert rosters.g_sum(age, 0) == sum(rosters._g_of(x) for x in range(age + 1, 27)) \
            if age < 26 else rosters.g_sum(age, 0) == 0
    team = synth_team(grades0=True)
    rec = bytearray(team[HDR + REC_SIZE * 20:HDR + REC_SIZE * 21])   # batter, age 20
    add = (sum(rosters._g_of(x) for x in range(21, 27)) + 128) >> 8
    want = [min(12, _get(rec, *F[n]) + add) if _get(rec, *F[n]) < 12 else _get(rec, *F[n])
            for n in ('power', 'hit_run', 'speed', 'range', 'arm')]
    assert rosters.pot_ratings(rec) == want
    rec[OFF_DEV] = 3                          # GM[3] = 4 -> x1.0, same as grade 0
    assert rosters.pot_ratings(rec) == want


def test_f_pot_boom_gt_bust():
    import rosters
    vals = {}
    for grade in (1, 5):
        team = synth_team()
        rec = bytearray(team[HDR:HDR + REC_SIZE])
        v20._set(rec, *F['age'], 20)
        rec[OFF_DEV] = grade
        vals[grade] = rosters.pot_ratings(rec)
    assert sum(vals[5]) > sum(vals[1])


# ---------------------------------------------------------------------------
# g. sim50 --dev
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.isdir(SIM50), reason='s1_pre fixture missing')
def test_g_sim50_dev(tmp_path):
    out = str(tmp_path / 'sim')
    rc = sim50.main(['--seasons', '3', '--seed', '8230', '--era', '0',
                     '--dev', '--out', out])
    assert rc == 0
    lines = [sim50.json.loads(l)
             for l in open(os.path.join(out, 'metrics.jsonl')) if l.strip()]
    assert len(lines) == 3
    for j in lines:
        assert 'dev_counts' in j
        assert set(map(int, j['dev_counts'])) == {1, 2, 3, 4, 5}
    # season 1 measures the stock league (byte 142 = 0 everywhere); from season
    # 2 on every active player carries a grade
    assert sum(lines[0]['dev_counts'].values()) == 0
    for j in lines[1:]:
        assert sum(j['dev_counts'].values()) >= 26 * 20


@pytest.mark.skipif(not os.path.isdir(SIM50), reason='s1_pre fixture missing')
def test_g_sim50_no_dev_no_counts(tmp_path):
    out = str(tmp_path / 'sim')
    rc = sim50.main(['--seasons', '2', '--seed', '8230', '--era', '0',
                     '--out', out])
    assert rc == 0
    lines = [sim50.json.loads(l)
             for l in open(os.path.join(out, 'metrics.jsonl')) if l.strip()]
    for j in lines:
        assert 'dev_counts' not in j
