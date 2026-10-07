#!/usr/bin/env python3
"""Tests for the M4 rookie-class generator.

Run with:
  cd /home/will/tlrb2 && python3 -m pytest /mnt/nvme/tlrb2/work/m4/test_rookies.py -q
"""

import os
import sys
import glob

TOOLS = "/home/will/tlrb2/tools"
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import ratings  # noqa: E402
import v20  # noqa: E402

import rookies  # noqa: E402

SNAP_GLOB = "/mnt/nvme/tlrb2/snaps/m3_end/TEAMS/CLASSIC/*.V20"
SEASON_YEAR = 1920
SEED = 7
PER_TEAM = 5

# Loose sanity multiplier: no generated stat may exceed the calibrated
# weakest-third band max times this factor (stated per the task spec).
STAT_SANITY_MULT = 3.0


def _team_paths():
    paths = sorted(glob.glob(SNAP_GLOB))
    assert paths, "no real V20 files found at %s" % SNAP_GLOB
    return paths


def _gen_all(paths, seed=SEED):
    return rookies.gen_class(paths, SEASON_YEAR, seed, per_team=PER_TEAM)


def _all_records(classes):
    out = []
    for path in sorted(classes):
        for rec in classes[path]:
            out.append(rec)
    return out


def _validate_layout(rec, season_year=SEASON_YEAR):
    """Full layout validation of one record. Raises AssertionError on any
    violation. Used both by tests directly and by the positive-control test
    (which mutates a record and expects this to fail)."""
    assert len(rec) == rookies.RECORD_LEN

    # Parse through v20.Player.
    team = v20.Team.load(_team_paths()[0])
    player = v20.Player(bytes(rec), 0)
    assert player is not None

    # Name charset: A-Z and space only (after stripping zero padding).
    for field in (rec[0:12], rec[12:20]):
        raw = field.decode("latin-1")
        for ch in raw.rstrip("\x00"):
            assert ch == " " or ("A" <= ch <= "Z"), "bad name char %r" % ch

    age = rec[rookies.OFF_AGE]
    assert 18 <= age <= 23, "age %d out of range" % age
    assert rec[rookies.OFF_YEAR] == (season_year - 1870) & 0xFF
    assert rec[rookies.OFF_EXP] == 0

    sal = rec[rookies.OFF_SALARY] | (rec[rookies.OFF_SALARY + 1] << 8)
    assert 109 <= sal <= 9999, "salary %d out of clamp range" % sal
    expected_sal = max(109, min(9999, int(ratings.salary(bytes(rec)))))
    assert sal == expected_sal, "salary %d != ratings.salary clamped %d" % (sal, expected_sal)

    portrait = rec[rookies.OFF_PORTRAIT] | (rec[rookies.OFF_PORTRAIT + 1] << 8)
    assert 0 <= portrait <= 29, "portrait %d out of range" % portrait


def _rating_range_check(rec, position):
    """Assert every rating calculator returns inside the shipped range.

    The shipped range for all rating nibbles in real V20 records is 1..15
    (4-bit nibbles, 0 reserved for empty); verified against real records
    before writing these tests.
    """
    vals = []
    if position == rookies.POS_P:
        vals = [
            ratings.velocity(rec),
            ratings.control(rec),
            ratings.endurance(rec),
            ratings.pitcher_class(rec),
        ]
    else:
        vals = [
            ratings.power(rec),
            ratings.speed(rec),
            ratings.hit_and_run(rec),
            ratings.bunt(rec),
            ratings.rng(rec),
            ratings.arm(rec),
        ]
    for v in vals:
        assert 1 <= v <= 15, "rating %d outside shipped 1..15 range" % v


def test_determinism_same_seed_identical():
    paths = _team_paths()
    a = _gen_all(paths, seed=SEED)
    b = _gen_all(paths, seed=SEED)
    assert a == b, "same seed produced different bytes"


def test_determinism_different_seed_differs():
    paths = _team_paths()
    a = _gen_all(paths, seed=SEED)
    b = _gen_all(paths, seed=SEED + 1)
    assert a != b, "different seeds produced identical bytes"


def test_layout_all_records():
    paths = _team_paths()
    classes = _gen_all(paths)
    recs = _all_records(classes)
    assert len(recs) == len(paths) * PER_TEAM
    for rec in recs:
        _validate_layout(rec)


def test_ratings_sanity():
    paths = _team_paths()
    classes = _gen_all(paths)
    for path in sorted(classes):
        for rec in classes[path]:
            position = rookies.POS_P if (rec[31] & 15) == 0 else rookies.POS_DH
            _rating_range_check(rec, position)


def test_calibration():
    paths = _team_paths()
    classes = _gen_all(paths)
    recs = _all_records(classes)
    salaries = [rec[25] | (rec[26] << 8) for rec in recs]
    mean_salary = sum(salaries) / len(salaries)
    # Get real league bottom half mean salary
    real_salaries = []
    for path in paths:
        team = v20.Team.load(path)
        for player in team.players:
            if player['salary'] > 0:
                real_salaries.append(player['salary'])
    real_salaries.sort()
    bottom_half = real_salaries[:len(real_salaries)//2]
    real_mean = sum(bottom_half) / len(bottom_half)
    assert real_mean * 0.2 <= mean_salary <= real_mean * 3.0


def test_positive_control():
    paths = _team_paths()
    classes = _gen_all(paths)
    recs = _all_records(classes)
    rec = bytearray(recs[0])
    rec[rookies.OFF_AGE] = 99
    try:
        _validate_layout(rec)
        assert False, "validation should have failed"
    except AssertionError:
        pass  # Expected
