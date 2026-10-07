#!/usr/bin/env python3
"""Tests for the M4 rollover reference (tools/m4/rollover.py).
Run:  cd ~/tlrb2 && python3 -m pytest tools/m4/test_rollover.py -q
      python3 tools/m4/test_rollover.py
Fixture: pristine CLASALE1.V20 (read-only); roster 0..39 copied into season slots 40..79,
season stats synthesized on the 40..79 records (career // 8, capped; player 0 zeroed;
player 16 games=150). Ages asserted as DELTAS (pristine ages are 30..46).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rollover
from v20 import Team, _get, _set, F

PRISTINE = '/mnt/nvme/tlrb2/pristine/TONY2/TEAMS/CLASSIC/CLASALE1.V20'


class ForcedRng(rollover.Rng):
    """Overrides draw() so the retirement branch sees a constant value."""
    def __init__(self, value):
        super().__init__(1)
        self.value = value

    def draw(self):
        return self.value


def fixture_team():
    t = Team.load(PRISTINE)
    for i in range(40):
        t.players[i + 40].raw[:] = t.players[i].raw[:]      # season half = copy of roster
    for i in range(40):
        season = t.players[i + 40].raw
        for f in rollover.STAT_FIELDS:
            off, kind = F[f]
            if kind in ('u8', 'u16'):
                if i == 0:
                    _set(season, off, kind, 0)               # player 0: zero season
                else:
                    cap = 255 if kind == 'u8' else 65535
                    _set(season, off, kind, min(cap, _get(t.players[i].raw, off, kind) // 8))
        _set(season, *F['games'], 150 if i == 16 else 0)
    return t


def test_merge_saturation(tmp_path):
    t = fixture_team()
    # player 16: career merge of career//8 season stats
    before = {f: _get(t.players[16].raw, *F[f]) for f in rollover.STAT_FIELDS
              if F[f][1] in ('u8', 'u16')}
    season = {f: _get(t.players[56].raw, *F[f]) for f in before}
    rollover.rollover_player(t.players[16].raw, t.players[56].raw,
                             {'progress': False, 'retire': False}, rollover.Rng(1), [])
    for f, b in before.items():
        cap = 255 if F[f][1] == 'u8' else 65535
        assert _get(t.players[16].raw, *F[f]) == min(cap, b + season[f]), f
    # player 0: zero season stats leave career bytes untouched
    before0 = {f: _get(t.players[0].raw, *F[f]) for f in rollover.STAT_FIELDS
               if F[f][1] in ('u8', 'u16')}
    rollover.rollover_player(t.players[0].raw, t.players[40].raw,
                             {'progress': False, 'retire': False}, rollover.Rng(1), [])
    for f, b in before0.items():
        assert _get(t.players[0].raw, *F[f]) == b, f
    # u16 saturation via sat_add (never raw _set an out-of-range value)
    assert rollover.sat_add(65530, 100, 'u16') == 65535
    assert rollover.sat_add(250, 10, 'u8') == 255


def test_aging_and_twin_mirror(tmp_path):
    t = fixture_team()
    age0 = _get(t.players[16].raw, *F['age'])
    year0 = _get(t.players[16].raw, *F['year_off'])
    exp0 = _get(t.players[16].raw, *F['exp'])
    rollover.rollover_player(t.players[16].raw, t.players[56].raw,
                             {'progress': False, 'retire': False}, rollover.Rng(1), [])
    assert _get(t.players[16].raw, *F['age']) == age0 + 1
    # year_off becomes season year_off + 1 (season half was a roster copy here, so the
    # reference reads the season record's year_off; assert the +1 delta against it)
    assert _get(t.players[16].raw, *F['year_off']) == year0 + 1
    assert _get(t.players[16].raw, *F['exp']) == exp0 + 1          # games 150 > 0
    # player 0: season games 0 -> exp unchanged
    exp_p0 = _get(t.players[0].raw, *F['exp'])
    rollover.rollover_player(t.players[0].raw, t.players[40].raw,
                             {'progress': False, 'retire': False}, rollover.Rng(1), [])
    assert _get(t.players[0].raw, *F['exp']) == exp_p0
    # team-level run mirrors the three fields onto the season-half twin
    f = tmp_path / 'TEAM.V20'
    t.save(f)
    rollover.rollover_team(str(f), str(f), {'progress': False, 'retire': False},
                           rollover.Rng(1), [])
    t2 = Team.load(str(f))
    for i in (0, 16, 39):
        for fld in ('age', 'year_off', 'exp'):
            assert _get(t2.players[i].raw, *F[fld]) == _get(t2.players[i + 40].raw, *F[fld]), \
                (i, fld)


def test_progression_vectors():
    assert rollover.k_delta(5, 8, 128) == 7      # (128*3+128)>>8 = 2
    assert rollover.k_delta(5, 8, 64) == 6       # (64*3+128)>>8 = 1
    assert rollover.k_delta(10, 6, 224) == 11    # k 224 = signed -32
    assert rollover.k_delta(7, 7, 128) == 7
    assert rollover.k_delta(12, 5, 0) == 12      # k = 0 identity (legal rating)
    assert rollover.k_delta(14, 20, 128) == 15   # clamp high
    assert rollover.k_delta(2, 0, 128) == 1      # clamp low


def test_progression_skipped_when_no_games(tmp_path):
    t = fixture_team()
    ratings_bytes = {}
    for f in ('power', 'bunt', 'hit_run', 'speed', 'range', 'arm'):
        ratings_bytes[f] = _get(t.players[0].raw, *F[f])
    rollover.rollover_player(t.players[0].raw, t.players[40].raw,
                             {'progress': True, 'retire': False}, rollover.Rng(1), [])
    for f, v in ratings_bytes.items():
        assert _get(t.players[0].raw, *F[f]) == v, f


def test_retirement_rules(tmp_path):
    t = fixture_team()
    p = t.players[0].raw
    _set(p, *F['age'], 39)                       # age2 40 -> False (no other branch fires)
    assert not rollover.rollover_player(p, t.players[40].raw,
                                        {'progress': False, 'retire': True}, rollover.Rng(1), [])
    _set(p, *F['age'], 40)                       # age2 41 -> True
    assert rollover.rollover_player(p, t.players[40].raw,
                                    {'progress': False, 'retire': True}, rollover.Rng(1), [])
    _set(p, *F['age'], 35)                       # age2 36: rng decides
    assert rollover.rollover_player(p, t.players[40].raw,
                                    {'progress': False, 'retire': True}, ForcedRng(0), [])
    assert not rollover.rollover_player(p, t.players[40].raw,
                                        {'progress': False, 'retire': True}, ForcedRng(0xff), [])
    # pitcher (pos1 == 0) with endurance < 3 and arm < 3 -> True regardless of age
    _set(p, *F['age'], 30)
    old_pos = _get(p, *F['pos1'])
    _set(p, *F['pos1'], 0)
    _set(p, *F['endurance'], 2)
    _set(p, *F['arm'], 2)
    assert rollover.rollover_player(p, t.players[40].raw,
                                    {'progress': False, 'retire': True}, rollover.Rng(1), [])
    # batter with the same weak endurance+arm -> False
    _set(p, *F['pos1'], 7)
    assert not rollover.rollover_player(p, t.players[40].raw,
                                        {'progress': False, 'retire': True}, rollover.Rng(1), [])
    _set(p, *F['pos1'], old_pos)


def test_determinism(tmp_path):
    ind = tmp_path / 'in'
    ind.mkdir()
    fixture_team().save(str(ind / 'TEAM.V20'))
    out1, out2 = tmp_path / 'o1', tmp_path / 'o2'
    rollover.rollover(str(ind), str(out1), {'progress': True, 'retire': True}, seed=7)
    rollover.rollover(str(ind), str(out2), {'progress': True, 'retire': True}, seed=7)
    for name in sorted(os.listdir(out1)):
        if name == 'HISTORY.DAT.json':
            continue
        assert name.endswith('.V20')
        assert open(f'{out1}/{name}', 'rb').read() == open(f'{out2}/{name}', 'rb').read(), name
    assert open(f'{out1}/HISTORY.DAT.json', 'rb').read() == \
        open(f'{out2}/HISTORY.DAT.json', 'rb').read()


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
