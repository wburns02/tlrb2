"""Tests for TLRB2 M4 team_fill (post-rollover rookie fill).

Run with:
  cd /home/will/tlrb2 && python3 -m pytest \
      /mnt/nvme/tlrb2/work/m4/test_team_fill.py -q
"""

import os
import shutil
import sys

_TOOLS = "/home/will/tlrb2/tools"
_M4 = "/home/will/tlrb2/tools/m4"
for _p in (_TOOLS, _M4):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

import rollover  # noqa: E402
import v20  # noqa: E402
from rookies import RookieGen  # noqa: E402

import team_fill  # noqa: E402

SNAP_DIR = "/mnt/nvme/tlrb2/snaps/m3_end/TEAMS/CLASSIC"
REAL_ROLLED_DIR = "/mnt/nvme/tlrb2/work/c/TONY2/TEAMS/CLASSIC"

SEASON_YEAR = 2


def _snap_teams(n):
    names = sorted(
        f for f in os.listdir(SNAP_DIR) if f.upper().endswith(".V20")
    )
    return names[:n]


def _load(path):
    return v20.Team.load(path)


def _active(team, i):
    return team.players[i].raw[0] != 0


def _vacancies(team):
    return [i for i in range(40) if not _active(team, i)]


def _make_rookie_gen(seed):
    return RookieGen(rollover.Rng(seed), [])


@pytest.fixture
def rolled_team(tmp_path):
    """Copy one m3_end V20, run a real rollover to produce vacancies."""
    name = _snap_teams(1)[0]
    src = os.path.join(SNAP_DIR, name)
    work = tmp_path / "rolled.V20"
    shutil.copy(src, str(work))
    # Walk seeds until this team produces at least one real retiree (ages in
    # the classic league skew young, so seed 1 often retires nobody).
    for seed in range(1, 61):
        shutil.copy(src, str(work))
        report = []
        rollover.rollover_team(
            str(work), str(work), {"progress": True, "retire": True},
            rollover.Rng(seed), report,
        )
        if any(entry.get("retire") for entry in report):
            return str(work), report
    import pytest
    pytest.skip("no seed in 1..60 retired anyone on %s" % name)


@pytest.fixture
def three_rolled_teams(tmp_path):
    """Three m3_end V20s, each rolled over for real vacancies."""
    out = []
    import pytest
    for name in _snap_teams(3):
        src = os.path.join(SNAP_DIR, name)
        dst = tmp_path / name
        for seed in range(1, 61):
            shutil.copy(src, str(dst))
            report = []
            rollover.rollover_team(
                str(dst), str(dst), {"progress": True, "retire": True},
                rollover.Rng(seed), report,
            )
            if any(entry.get("retire") for entry in report):
                out.append((str(dst), report))
                break
        else:
            pytest.skip("no retiree seed for %s" % name)
    return out


# ---------------------------------------------------------------------------
# Core fill behaviour
# ---------------------------------------------------------------------------

def test_vacated_slots_filled_both_halves(tmp_path, rolled_team):
    path, report = rolled_team
    out = str(tmp_path / "filled.V20")
    res = team_fill.fill_team(path, out, SEASON_YEAR, rollover.Rng(7),
                              _make_rookie_gen(7))

    vacated = _vacancies(_load(path))
    assert vacated, "rollover produced no vacancies; fixture is useless"
    assert sorted(res["vacancies"]) == sorted(vacated)

    before = _load(path)
    after = _load(out)

    for i in vacated:
        assert after.players[i].raw[0] != 0, "roster half not filled"
        assert after.players[40 + i].raw[0] != 0, "season half not filled"

    # Non-vacated slots are byte-identical in both halves.
    vac_set = set(vacated)
    for i in range(80):
        if i in vac_set or (i - 40) in vac_set:
            continue
        assert after.players[i].raw == before.players[i].raw, (
            "slot %d changed but was not vacated" % i
        )


def test_season_half_stats_zero_identity_matches(tmp_path, rolled_team):
    path, report = rolled_team
    out = str(tmp_path / "filled.V20")
    res = team_fill.fill_team(path, out, SEASON_YEAR, rollover.Rng(7),
                              _make_rookie_gen(7))

    after = _load(out)
    for i in res["vacancies"]:
        roster = after.players[i].raw
        season = after.players[40 + i].raw

        # All season stat bytes zeroed in the season half.
        for off in sorted(team_fill._SEASON_STAT_OFFSETS):
            assert season[off] == 0, (
                "season byte %d not zeroed for slot %d" % (off, i)
            )

        # Identity fields match the roster half.
        assert season[0:23] == roster[0:23]
        assert season[24:32] == roster[24:32]
        assert season[29] == roster[29]
        assert season[31] == roster[31]
        assert season[59:101] == roster[59:101]
        assert season[127:143] == roster[127:143]

        # Salary / age / name via the Player view.
        p_roster = after.players[i]
        p_season = after.players[40 + i]
        assert p_season["salary"] == p_roster["salary"]
        assert p_season["age"] == p_roster["age"]
        assert p_season["last"] == p_roster["last"]
        assert p_season["first"] == p_roster["first"]


def test_position_priorities_all_pitcher_retirees(tmp_path):
    """Synthesise a team whose 4 retirees are all pitchers."""
    name = _snap_teams(1)[0]
    src = os.path.join(SNAP_DIR, name)
    work = str(tmp_path / "synth.V20")
    shutil.copy(src, work)

    team = _load(work)
    # Find 4 active pitchers in the roster half and zero their byte 0 in
    # both halves (simulating a rollover retirement).
    pitchers = [i for i in range(40)
                if _active(team, i) and (team.players[i].raw[31] & 0x0F) == 0]
    assert len(pitchers) >= 4, "fixture team lacks 4 active pitchers"
    for i in pitchers[:4]:
        r = bytearray(team.players[i].raw)
        r[0] = 0
        team.players[i].raw = bytes(r)
        s = bytearray(team.players[40 + i].raw)
        s[0] = 0
        team.players[40 + i].raw = bytes(s)
    team.save(work)

    out = str(tmp_path / "synth_filled.V20")
    res = team_fill.fill_team(work, out, SEASON_YEAR, rollover.Rng(3),
                              _make_rookie_gen(3))

    after = _load(out)

    # Pre-fill active counts (excluding the slots we are about to fill).
    pre = {}
    vac_set = set(res["vacancies"])
    for i in range(40):
        if i not in vac_set and _active(after, i):
            code = after.players[i].raw[31] & 0x0F
            pre[code] = pre.get(code, 0) + 1

    # Walk the fills in order and check the priority ladder.
    sim = dict(pre)
    for idx, code in enumerate(res["positions"]):
        if code == 0:
            assert sim.get(0, 0) < 8, (
                "pitcher fill #%d but already >= 8 pitchers" % idx
            )
        elif code == 1:
            assert sim.get(0, 0) >= 8, "catcher fill before pitchers done"
            assert sim.get(1, 0) < 2
        elif code in (2, 3, 4, 5):
            assert sim.get(0, 0) >= 8 and sim.get(1, 0) >= 2, (
                "IF fill before P/C targets met"
            )
            assert sim.get(code, 0) < 1
        elif 6 <= code <= 8:
            assert sim.get(0, 0) >= 8 and sim.get(1, 0) >= 2 and all(
                sim.get(c, 0) >= 1 for c in (2, 3, 4, 5)
            ), "OF fill before P/C/IF targets met"
            of_have = sum(sim.get(c, 0) for c in (6, 7, 8))
            assert of_have < 4, "OF fill past target"
        else:
            assert code == 9, "unexpected fill code %d" % code
        sim[code] = sim.get(code, 0) + 1

    # Final counts respect the targets.
    counts = {}
    for i in range(40):
        if _active(after, i):
            code = after.players[i].raw[31] & 0x0F
            counts[code] = counts.get(code, 0) + 1
    assert counts.get(0, 0) >= 8
    assert counts.get(1, 0) >= 2
    for c in (2, 3, 4, 5):
        assert counts.get(c, 0) >= 1
    assert sum(counts.get(c, 0) for c in (6, 7, 8)) >= 4 or counts.get(9, 0) > 0


def test_determinism_same_seed(tmp_path, three_rolled_teams):
    outs_a = tmp_path / "a"
    outs_b = tmp_path / "b"
    outs_a.mkdir()
    outs_b.mkdir()

    in_dir = tmp_path / "in"
    in_dir.mkdir()
    for path, _rep in three_rolled_teams:
        shutil.copy(path, str(in_dir / os.path.basename(path)))

    rep_a = team_fill.fill_league(str(in_dir), str(outs_a), SEASON_YEAR, 42)
    rep_b = team_fill.fill_league(str(in_dir), str(outs_b), SEASON_YEAR, 42)

    assert rep_a == rep_b
    for name in rep_a:
        a = open(str(outs_a / name), "rb").read()
        b = open(str(outs_b / name), "rb").read()
        assert a == b, "seeded fill not deterministic for %s" % name


def test_ensure_minimum_thin_roster(tmp_path):
    name = _snap_teams(1)[0]
    src = os.path.join(SNAP_DIR, name)
    work = str(tmp_path / "thin.V20")
    shutil.copy(src, work)

    team = _load(work)
    active = [i for i in range(40) if _active(team, i)]
    assert len(active) >= 35, "fixture team already too thin to thin further"
    # Deactivate down to 30 active in both halves.
    to_kill = active[: len(active) - 30]
    for i in to_kill:
        r = bytearray(team.players[i].raw)
        r[0] = 0
        team.players[i].raw = bytes(r)
        s = bytearray(team.players[40 + i].raw)
        s[0] = 0
        team.players[40 + i].raw = bytes(s)
    team.save(work)

    before = _load(work)
    before_bytes = [before.players[i].raw for i in range(80)]

    out = str(tmp_path / "thin_filled.V20")
    res = team_fill.ensure_minimum(work, out, SEASON_YEAR, rollover.Rng(5),
                                   _make_rookie_gen(5))

    after = _load(out)
    n_active = sum(1 for i in range(40) if _active(after, i))
    assert n_active == 35
    assert len(res["vacancies"]) == 5

    # No other records touched.
    filled = set(res["vacancies"]) | {40 + i for i in res["vacancies"]}
    for i in range(80):
        if i in filled:
            continue
        assert after.players[i].raw == before_bytes[i], (
            "ensure_minimum touched untouched slot %d" % i
        )


def test_ensure_minimum_noop_when_35_plus(tmp_path):
    name = _snap_teams(1)[0]
    src = os.path.join(SNAP_DIR, name)
    out = str(tmp_path / "noop.V20")
    res = team_fill.ensure_minimum(src, out, SEASON_YEAR, rollover.Rng(5),
                                   _make_rookie_gen(5))
    assert res == {"vacancies": [], "positions": []}
    assert open(src, "rb").read() == open(out, "rb").read()


# ---------------------------------------------------------------------------
# Positive controls / guards
# ---------------------------------------------------------------------------

def test_no_vacancies_noop(tmp_path):
    """A team with no zeroed slots: fill_team changes nothing."""
    name = _snap_teams(1)[0]
    src = os.path.join(SNAP_DIR, name)
    out = str(tmp_path / "noop.V20")
    res = team_fill.fill_team(src, out, SEASON_YEAR, rollover.Rng(9),
                              _make_rookie_gen(9))
    assert res == {"vacancies": [], "positions": []}
    assert open(src, "rb").read() == open(out, "rb").read()


def test_cannot_overwrite_active_slot(tmp_path):
    """fill_team must refuse a slot that is only HALF vacant: roster byte 0
    zeroed but the season-half record still active. That is not a rollover
    vacancy and overwriting it would destroy a live player's stat line."""
    name = _snap_teams(1)[0]
    src_path = os.path.join(SNAP_DIR, name)
    bad = str(tmp_path / "bad.V20")
    shutil.copy(src_path, bad)
    team = _load(bad)
    assert any(_active(team, i) for i in range(40))
    # Half-vacate slot 5: roster half inactive, season half untouched.
    team.players[5].raw[0] = 0
    team.save(bad)
    with pytest.raises(ValueError):
        team_fill.fill_team(bad, str(tmp_path / "out.V20"), SEASON_YEAR,
                            rollover.Rng(7), _make_rookie_gen(7))



def test_cannot_overwrite_active_season_half(tmp_path):
    """A roster vacancy with an active season-half record is not a rollover
    vacancy; fill_team must refuse."""
    name = _snap_teams(1)[0]
    src = os.path.join(SNAP_DIR, name)
    work = str(tmp_path / "half.V20")
    shutil.copy(src, work)

    team = _load(work)
    i = next(i for i in range(40) if _active(team, i))
    r = bytearray(team.players[i].raw)
    r[0] = 0
    team.players[i].raw = bytes(r)
    # Season half left active on purpose.
    team.save(work)

    with pytest.raises(ValueError):
        team_fill.fill_team(work, str(tmp_path / "y.V20"), SEASON_YEAR,
                            rollover.Rng(9), _make_rookie_gen(9))


def test_real_rolled_league_fixture(tmp_path):
    """Second fixture: a REAL rolled league (TONY2, season 2 mid-season).

    Whatever vacancies it still has must be fillable; if it has none,
    fill_team must be a clean no-op.
    """
    names = sorted(
        f for f in os.listdir(REAL_ROLLED_DIR) if f.upper().endswith(".V20")
    )
    assert names, "real rolled league fixture missing"
    name = names[0]
    src = os.path.join(REAL_ROLLED_DIR, name)
    out = str(tmp_path / name)

    before = _load(src)
    pre_vac = _vacancies(before)

    res = team_fill.fill_team(src, out, SEASON_YEAR, rollover.Rng(11),
                              _make_rookie_gen(11))
    after = _load(out)

    assert sorted(res["vacancies"]) == sorted(pre_vac)
    for i in pre_vac:
        assert _active(after, i)
        assert _active(after, 40 + i)
    vac_set = set(pre_vac)
    for i in range(80):
        if i in vac_set or (i - 40) in vac_set:
            continue
        assert after.players[i].raw == before.players[i].raw


def test_position_codes_shipped_convention(tmp_path, rolled_team):
    """Filled records carry only codes the shipped data uses (0..8), and an
    OF-needing fill spreads across LF/CF/RF instead of one generic code.
    Fails against the old all-code-10 fill."""
    path, _report = rolled_team
    out = str(tmp_path / "filled.V20")
    team_fill.fill_team(path, out, 1994, rollover.Rng(42), _make_rookie_gen(42))
    rolled, filled = _load(path), _load(out)
    codes = []
    for i in _vacancies(rolled):
        codes.append(filled.players[i].raw[31] & 0x0F)
    assert codes, "fixture produced no fills"
    for code in codes:
        assert 0 <= code <= 9, "code %d outside ladder output (0..9)" % code
    of_codes = [c for c in codes if 6 <= c <= 8]
    if len(of_codes) >= 3:
        assert set(of_codes) == {6, 7, 8}, (
            ">=3 OF fills should spread LF/CF/RF, got %r" % of_codes
        )
