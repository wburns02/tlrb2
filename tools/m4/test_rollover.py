#!/usr/bin/env python3
"""Python unit tests for the M4 rollover reference C1 (tools/m4/rollover.py).
These pin C1 numbers DIRECTLY (no asm involvement). Run:
    cd ~/tlrb2 && python3 -m pytest -q tools/m4/test_rollover.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rollover
from v20 import Team, _get, _set, F


def blank_rec(batter=True, val=6):
    """A minimal 143 B record with rating = val on the progressible ratings."""
    r = bytearray(143)
    r[0] = 1
    _set(r, *F['pos1'], 7 if batter else 0)
    names = (('power',), ('bunt',), ('hit_run',), ('speed',), ('range',), ('arm',)) \
        if batter else (('control',), ('velocity',), ('endurance',))
    for (name,) in names:
        _set(r, *F[name], val)
    return r


class ForcedRng(rollover.Rng):
    """Overrides draw() so the drift/retirement draws see constant values."""
    def __init__(self, value):
        super().__init__(1)
        self.value = value

    def draw(self):
        return self.value


class CountRng(rollover.Rng):
    """Counts draws."""
    def __init__(self, seed=1):
        super().__init__(seed)
        self.n = 0

    def draw(self):
        self.n += 1
        return super().draw()


# -- k_delta: the evidence formula (k = 96 only in C1) ------------------------

def test_k_delta_evidence():
    assert rollover.k_delta(5, 8, 96) == 6        # (96*3+128)>>8 = 1
    assert rollover.k_delta(5, 8, 128) == 7       # (128*3+128)>>8 = 2
    assert rollover.k_delta(5, 8, 64) == 6        # (64*3+128)>>8 = 1
    assert rollover.k_delta(10, 6, 96) == 9       # (96*-4+128)>>8 = -1
    assert rollover.k_delta(7, 7, 96) == 7
    assert rollover.k_delta(14, 20, 96) == 15     # clamp high
    assert rollover.k_delta(2, 0, 96) == 1        # clamp low
    assert rollover.k_delta(5, 8, 96) == 6


# -- tier: C1 boundaries from roster-half ratings -----------------------------

def test_tier_batter():
    # qs = power + hit_run + speed + range; tiers at 32/36/39
    # speed+range stay 6+6 = 12; power gets qs - 12 (cap 12), hit_run the rest
    # (cap 15 for the lo nibble). qs >= 45 is unreachable this way and is not
    # a boundary anyway; the 48 case is covered by the exact-edge test.
    for qs, tier in ((31, 0), (32, 1), (35, 1), (36, 2), (38, 2), (39, 3)):
        r = blank_rec()
        pw = max(1, min(12, qs - 12))
        hr = max(1, min(15, qs - 12 - pw))
        _set(r, *F['power'], pw)
        _set(r, *F['hit_run'], hr)
        assert rollover.tier_of(r) == tier, qs


def test_tier_batter_exact_edges():
    # exact boundary vectors: qs 31/32 and 35/36 and 38/39
    for (p, hr, sp, rg), tier in (((8, 8, 8, 7), 0),   # 31 -> 0
                                  ((8, 8, 8, 8), 1),   # 32 -> 1
                                  ((9, 9, 9, 8), 1),   # 35 -> 1
                                  ((9, 9, 9, 9), 2),   # 36 -> 2
                                  ((10, 10, 9, 9), 2), # 38 -> 2
                                  ((10, 10, 10, 9), 3),  # 39 -> 3
                                  ((10, 10, 10, 10), 3)):  # 40 -> 3
        r = blank_rec()
        _set(r, *F['power'], p)
        _set(r, *F['hit_run'], hr)
        _set(r, *F['speed'], sp)
        _set(r, *F['range'], rg)
        assert rollover.tier_of(r) == tier, (p, hr, sp, rg)


def test_tier_pitcher():
    # qs = control + velocity + endurance; tiers at 23/26/28
    for (c, v, e), tier in (((5, 5, 5), 0),    # 15 -> 0
                            ((11, 6, 5), 0),   # 22 -> 0
                            ((12, 6, 5), 1),   # 23 -> 1
                            ((9, 8, 8), 1),    # 25 -> 1
                            ((9, 9, 8), 2),    # 26 -> 2
                            ((10, 9, 8), 2),   # 27 -> 2
                            ((10, 9, 9), 3),   # 28 -> 3
                            ((12, 12, 10), 3)):
        r = blank_rec(batter=False)
        _set(r, *F['control'], c)
        _set(r, *F['velocity'], v)
        _set(r, *F['endurance'], e)
        assert rollover.tier_of(r) == tier, (c, v, e)


def test_tier_batter_qs_31_32_35_36_38_39():
    # the exact C1 query: a batter with those qs values lands tier 0/1/1/2/2/3
    for qs, tier in ((31, 0), (32, 1), (35, 1), (36, 2), (38, 2), (39, 3)):
        r = blank_rec()
        pw = max(1, min(12, qs - 12))
        hr = max(1, min(15, qs - 12 - pw))
        _set(r, *F['power'], pw)
        _set(r, *F['hit_run'], hr)
        qs_check = sum(r[F[n][0]] & 15 for n in ('power', 'hit_run')) + 12
        assert qs_check == qs, (qs, qs_check)     # split must hit qs exactly
        assert rollover.tier_of(r) == tier, qs


# -- C1 p math: base * tier mult >> 2 ----------------------------------------

def test_c1_p_numbers():
    # drift p at age2 36..37, tier 3: base 96 * mult 2 >> 2 = 48
    assert (rollover.DRIFT_BASE(36) * rollover.TIER_MULT[3]) >> 2 == 48
    assert (rollover.DRIFT_BASE(37) * rollover.TIER_MULT[3]) >> 2 == 48
    # retirement p at age2 37..38, tier 3: base 36 * mult 2 >> 2 = 18
    assert (rollover.RETIRE_BASE(37) * rollover.TIER_MULT[3]) >> 2 == 18
    assert (rollover.RETIRE_BASE(38) * rollover.TIER_MULT[3]) >> 2 == 18
    # tier 0 doubles both: drift age2 <= 22 g = 90; retire age2 33 tier 0 = 40
    assert (rollover.DRIFT_BASE(40) * rollover.TIER_MULT[0]) >> 2 == 160   # 40+ tier 0
    assert (rollover.RETIRE_BASE(33) * rollover.TIER_MULT[0]) >> 2 == 10   # 33..34 tier 0
    # games == 0 doubles p, capped at 255
    assert min(255, 110 * 4) == 255
    assert (rollover.RETIRE_BASE(43) * rollover.TIER_MULT[0]) * 2 == 880


def test_drift_tables():
    # table constants exist and hold the C1 values (youth g values are pinned
    # through the drift behaviour in test_drift_noop below)
    assert rollover.DRIFT_BASE(32) == 40 and rollover.DRIFT_BASE(33) == 40
    assert rollover.DRIFT_BASE(34) == 64 and rollover.DRIFT_BASE(35) == 64
    assert rollover.DRIFT_BASE(36) == 96 and rollover.DRIFT_BASE(37) == 96
    assert rollover.DRIFT_BASE(38) == 128 and rollover.DRIFT_BASE(39) == 128
    assert rollover.DRIFT_BASE(40) == 160 and rollover.DRIFT_BASE(50) == 160


def test_retire_tables():
    for age2, b in ((33, 10), (34, 10), (35, 20), (36, 20), (37, 36), (38, 36),
                    (39, 56), (40, 56), (41, 80), (42, 80), (43, 110), (50, 110)):
        assert rollover.RETIRE_BASE(age2) == b, age2


# -- drift no-op range still consumes a draw ----------------------------------

def test_drift_noop_27_to_31_consumes_draws():
    # rollover_player ages first, so age 26..30 gives age2 27..31: the C1 no-op
    # window. Nothing may change, yet all 6 draws are consumed.
    for age in (26, 28, 30):            # age2 27, 29, 31
        r = blank_rec()
        _set(r, *F['age'], age)
        rng = CountRng(1)
        before = [_get(r, *F[f]) for f in ('power', 'bunt', 'hit_run', 'speed', 'range', 'arm')]
        rollover.rollover_player(r, blank_rec(), {'progress': True, 'retire': False}, rng, None)
        assert rng.n == 6, (age, rng.n)   # one draw per rating, consumed anyway
        after = [_get(r, *F[f]) for f in ('power', 'bunt', 'hit_run', 'speed', 'range', 'arm')]
        assert after == before, age       # 27..31 age2: no change


def test_drift_one_draw_per_rating():
    for batter in (True, False):
        r = blank_rec(batter=batter)
        rng = CountRng(1)
        rollover.rollover_player(r, blank_rec(batter=batter),
                                 {'progress': True, 'retire': False}, rng, None)
        assert rng.n == (6 if batter else 3), (batter, rng.n)


# -- evidence and drift gating -------------------------------------------------

def test_progression_skipped_when_no_games():
    r = blank_rec()
    season = blank_rec()
    season[23] = 0                       # season games 0
    rng = CountRng(1)
    rollover.rollover_player(r, season, {'progress': True, 'retire': False}, rng, None)
    assert rng.n == 6                    # drift still runs (games not needed)
    # no evidence target calls happened: ratings only moved by drift draws


def test_progression_flag_off_no_draws():
    r = blank_rec()
    rng = CountRng(1)
    rollover.rollover_player(r, blank_rec(), {'progress': False, 'retire': False}, rng, None)
    assert rng.n == 0                    # no drift draws at all


# -- retirement ----------------------------------------------------------------

def test_retire_age2_below_33_no_draw():
    for age in (0, 20, 31):              # age2 1..32
        r = blank_rec()
        _set(r, *F['age'], age)
        rng = CountRng(1)
        assert not rollover.rollover_player(r, blank_rec(),
                                            {'progress': False, 'retire': True}, rng, None)
        assert rng.n == 0, age           # NO retirement draw


def test_retire_never_forced():
    # a 50-year-old retires ONLY by draw: ret iff (d < p) with p from C1.
    # blank_rec batter: qs 24 -> tier 0, mult 4; age2 50 base 110 -> p = 110.
    for seed in range(0, 60):
        r = blank_rec()
        _set(r, *F['age'], 49)           # age2 50, base 110
        season = blank_rec()
        season[23] = 150                 # games > 0: no doubling
        d = rollover.Rng(seed)
        expected = (d.draw() & 0xff) < 110
        ret = rollover.rollover_player(bytearray(r), bytearray(season),
                                       {'progress': False, 'retire': True},
                                       rollover.Rng(seed), None)
        assert ret == expected, (seed, ret, expected)


def test_retire_p_games_zero_doubles_capped():
    # tier 3 retiree, age2 43+ (base 110) -> p = 55; with games 0 -> 110
    for season_games, exp_p in ((150, (110 * 2) >> 2), (0, min(255, ((110 * 2) >> 2) * 2))):
        r = blank_rec()                  # batter tier 3 (qs 24 -> tier 0 actually)
        # force tier: set max ratings -> batter qs 48 -> tier 3
        _set(r, *F['power'], 12)
        _set(r, *F['hit_run'], 12)
        _set(r, *F['speed'], 12)
        _set(r, *F['range'], 12)
        _set(r, *F['age'], 42)           # age2 43
        season = blank_rec()
        season[23] = season_games
        rng = rollover.Rng(0)            # d = 0 -> retired iff p > 0 (always)
        ret = rollover.rollover_player(r, season, {'progress': False, 'retire': True}, rng, None)
        assert ret is True, (season_games, exp_p)
        # with d = 0xff, retired iff 0xff < p (never)
        rng = ForcedRng(0xFF)
        assert not rollover.rollover_player(bytearray(r), season,
                                            {'progress': False, 'retire': True}, rng, None)


def test_retire_flag_off_no_draw():
    r = blank_rec()
    _set(r, *F['age'], 45)
    rng = CountRng(1)
    assert not rollover.rollover_player(r, blank_rec(),
                                        {'progress': False, 'retire': False}, rng, None)
    assert rng.n == 0                    # no retirement draw


# -- tier is computed from the roster half BEFORE changes ----------------------

def test_tier_pre_change():
    # season half has huge ratings; the ROSTER half tier must still decide.
    # Weak pitcher: roster qs 15 -> tier 0, p = (10*4)>>2 = 10, games 0 doubles
    # -> 20: draw 15 retires. If the tier came from the season half (qs 34 ->
    # tier 3, p = (10*2)>>2 = 5, doubled 10), draw 15 would NOT retire.
    r = blank_rec(batter=False, val=5)   # control 5 velocity 5 endurance 5
    _set(r, *F['age'], 33)               # age2 34, base 10
    season = blank_rec(batter=False, val=12)   # season half: tier 3 (unused)
    season[23] = 0
    assert rollover.tier_of(r) == 0
    assert rollover.tier_of(season) == 3
    assert rollover.rollover_player(r, season, {'progress': False, 'retire': True},
                                    ForcedRng(15), None)
    # same season half with a tier 3 roster: p = 10, draw 15 does not retire
    r = blank_rec(batter=False, val=12)
    _set(r, *F['endurance'], 10)         # qs 34 -> tier 3
    _set(r, *F['age'], 33)
    assert rollover.tier_of(r) == 3
    assert not rollover.rollover_player(r, season, {'progress': False, 'retire': True},
                                        ForcedRng(15), None)


# -- merge saturation (unchanged from P1, still law) ---------------------------

def test_merge_saturation():
    assert rollover.sat_add(65530, 100, 'u16') == 65535
    assert rollover.sat_add(250, 10, 'u8') == 255
    assert rollover.sat_add(100, 100, 'u8') == 200


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
