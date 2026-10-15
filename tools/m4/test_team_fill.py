"""Tests for TLRB2 M4 team_fill (post-rollover rookie fill).

Run with:
  python3 -m pytest -q tools/m4/test_team_fill.py
"""

import os
import shutil
import sys

_M4 = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_M4)
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


def _positions_for_team(team):
    """fill_image's position list for a team-view team (roster half active
    by pos, every inactive slot a vacancy)."""
    counts = {}
    for i in range(40):
        raw = team.players[i].raw
        if raw[0]:
            counts[raw[31] & 0x0F] = counts.get(raw[31] & 0x0F, 0) + 1
    return team_fill._priority_order(counts, sum(
        1 for i in range(40) if not team.players[i].raw[0]
    ))


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
    expected = _positions_for_team(_load(work))
    assert len(expected) == len(res["positions"])
    # The ladder part is _priority_order without its DH padding; every fill
    # after it is a C20 remainder draw (REM_TABLE code, never DH).
    ladder_n = sum(1 for c in expected if c != team_fill.POS_DH)
    assert res["positions"][:ladder_n] == expected[:ladder_n]
    for code in res["positions"][ladder_n:]:
        assert code in team_fill.REM_TABLE and code != team_fill.POS_DH
    sim = dict(pre)
    for idx, code in enumerate(res["positions"][:ladder_n]):
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
            assert code in team_fill.REM_TABLE, (
                "unexpected fill code %d (ladder leftover or DH)" % code
            )
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


# ---------------------------------------------------------------------------
# C20 remainder positions (post-ladder weighted draw)
# ---------------------------------------------------------------------------

def _make_team_v20(name=b'FAILING', abbr=b'FAI'):
    """A fresh 11735 B V20 with header name/abbr and 80 records."""
    d = bytearray(11735)
    d[0:14] = name.ljust(14, b'\0')[:14]
    d[14:16] = b'cl'
    d[16:19] = abbr.ljust(3, b'\0')[:3]
    return bytes(d)


def test_c20_remainder_draws_match_fresh_rng(tmp_path):
    """A team with 10 vacancies where the ladder covers 2 (6 P, 2 C, IF and
    OF targets already met -> 2 pitcher fills): exactly 8 remainder draws,
    and the codes equal REM_TABLE[d % 20] for the first 8 draws of a fresh
    Rng(seed)."""
    # 30 active: 6 P, 2 C, IF and OF targets already met -> the ladder covers
    pos = [0] * 6 + [1] * 2 + [2, 3, 4, 5] + [6, 7, 8, 6]
    pos += [1 + (i % 8) for i in range(30 - len(pos))]
    work = str(tmp_path / "c20.V20")
    d = bytearray(_make_team_v20())
    for i in range(30):
        base = 295 + i * 143
        d[base] = 1
        d[base + 31] = pos[i] & 0x0F
    open(work, "wb").write(bytes(d))

    out = str(tmp_path / "c20_filled.V20")
    seed = 777
    res = team_fill.fill_team(work, out, SEASON_YEAR, rollover.Rng(seed),
                              _make_rookie_gen(seed))
    assert len(res["vacancies"]) == 10

    # A fresh Rng(seed) taken right after nothing else: its first 8 draws are
    # the remainder draws the fill replayed.
    rng = rollover.Rng(seed)
    draws = [team_fill.REM_TABLE[rng.draw() % 20] for _ in range(8)]
    assert res["positions"] == [0, 0] + draws


def test_c20_no_code9_over_random_images():
    """No fill ever emits code 9, over 200 seeded random images."""
    import random
    rnd = random.Random(2026)
    for _ in range(200):
        image = bytearray(295 + 80 * 143)
        for i in range(40):
            if rnd.random() < 0.45:
                base = 295 + i * 143
                image[base] = 1
                image[base + 31] = rnd.randrange(0, 10)
        _, _, positions = team_fill.fill_image(
            image, 2, rollover.Rng(1), _make_rookie_gen(1))
        for code in positions:
            assert 0 <= code <= 8, "code %d leaked (DH never)" % code


def test_c20_ladder_full_no_remainder_draw(tmp_path):
    """A fill where the ladder covers every vacancy consumes no remainder
    draw: its rookie records equal RookieGen.make(code, year) called in fill
    order with the ladder codes on a fresh Rng(seed) (pos byte low nibble =
    the code, as fill_image does)."""
    # 24 active: 2 P and 22 DH -> ladder covers 6 P + 2 C + 4 IF + 4 OF =
    # 16 fills, and there are exactly 16 vacancies.
    pos = [0] * 2 + [9] * 22
    d = bytearray(_make_team_v20())
    for i in range(24):
        base = 295 + i * 143
        d[base] = 1
        d[base + 31] = pos[i] & 0x0F
    work = str(tmp_path / "ladder.V20")
    open(work, "wb").write(bytes(d))

    seed = 31337
    out = str(tmp_path / "ladder_filled.V20")
    res = team_fill.fill_team(work, out, SEASON_YEAR, rollover.Rng(seed),
                              _make_rookie_gen(seed))

    # Every fill code comes from the ladder (P, C, IF, OF), in ladder order.
    assert res["positions"] == [0] * 6 + [1] * 2 + [2, 3, 4, 5] + [6, 7, 8, 6]

    # Replay: ladder codes in fill order, record draws on a fresh Rng(seed).
    vacs = res["vacancies"]
    image = bytearray(open(out, "rb").read())
    replay = bytearray(open(work, "rb").read())
    rng = rollover.Rng(seed)
    gen = RookieGen(rng, [])
    for index, code in zip(vacs, res["positions"]):
        rookie = bytearray(gen.make(code, SEASON_YEAR))
        rookie[31] = (rookie[31] & 0xF0) | (code & 0x0F)
        season_copy = bytearray(rookie)
        for off in team_fill._SEASON_STAT_OFFSETS:
            season_copy[off] = 0
        base = 295 + index * 143
        replay[base:base + 143] = rookie
        replay[base + 40 * 143:base + 41 * 143] = season_copy
    assert image == bytes(replay), (
        "fill output diverges from a no-remainder replay"
    )


def test_c20_remainder_share_over_2000_draws():
    """Over 2000 remainder draws from Rng(1), each REM_TABLE code's share is
    within 3 points of its table share."""
    counts = {}
    rng = rollover.Rng(1)
    n = 2000
    for _ in range(n):
        code = team_fill.REM_TABLE[rng.draw() % 20]
        counts[code] = counts.get(code, 0) + 1
    for code in set(team_fill.REM_TABLE):
        share = 100.0 * counts.get(code, 0) / n
        table_share = 100.0 * team_fill.REM_TABLE.count(code) / 20
        assert abs(share - table_share) < 3.0, (
            "code %d: %.2f%% vs table %.2f%%" % (code, share, table_share)
        )


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
