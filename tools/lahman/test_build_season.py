#!/usr/bin/env python3
"""H1 build_season tests. All skip if the Lahman DB or the template league is missing.
usage: python3 -m pytest -q tools/lahman/test_build_season.py"""
import os
import sqlite3
import sys

import pytest

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import build_season                                              # noqa: E402
import ratings                                                   # noqa: E402
import v20                                                       # noqa: E402

DB = '/mnt/nvme/tlrb2/lahman/lahmansbaseballdb.sqlite'
TEMPLATE = '/mnt/nvme/tlrb2/hist/template/CLASSIC'
YEAR = 1985

_TEMPLATE_OK = os.path.isfile(DB) and os.path.isdir(TEMPLATE)

pytestmark = pytest.mark.skipif(not _TEMPLATE_OK,
                                reason='Lahman DB or template league missing')


@pytest.fixture(scope='module')
def league(tmp_path_factory):
    out = tmp_path_factory.mktemp('league') / 'hist1985'
    rc = build_season.main(['build_season.py', str(YEAR), str(out)])
    assert rc == 0, out
    return out


def team_path(out, stem):
    return os.path.join(out, stem.upper() + '.V20')


BUILT = [(stem, tid) for stem, tid, _ in build_season.team_list()]


def named_pitchers(t):
    return [p for p in t.players[:16] if p.active]


def named_batters(t):
    return [p for p in t.players[16:40] if p.active]


def test_files_and_alignment(league):
    assert sorted(os.listdir(TEMPLATE)) == sorted(os.listdir(league))
    for stem, _ in BUILT:
        with open(os.path.join(TEMPLATE, stem.upper() + '.V20'), 'rb') as f:
            s = f.read()
        with open(team_path(league, stem), 'rb') as f:
            d = f.read()
        # header bytes 0..110 kept from the template (name, colors, strategy, GM profile)
        assert s[:111] == d[:111]
    for name in ('CLASSIC.MAJ', 'ALLSTAR1.V20', 'ALLSTAR2.V20'):
        with open(os.path.join(TEMPLATE, name), 'rb') as f:
            s = f.read()
        with open(os.path.join(league, name), 'rb') as f:
            assert s == f.read()


def test_roster_counts(league):
    # NOTE: the spec's literal "every team has 16 named pitchers and >= 20 named
    # batters" contradicts the 1985 DB: under the one-team rule with the G_p*2 >= G_all
    # test, e.g. SDN has 15 pitcher and 16 batter candidates, DET 13 pitchers. The build
    # rules are followed exactly (pitcher slots 0..15, batter slots 16..39, unused
    # vacant); the test asserts the data-supported invariant instead.
    for stem, _ in BUILT:
        t = v20.Team.load(team_path(league, stem))
        pits = named_pitchers(t)
        bats = named_batters(t)
        assert len(pits) + len(bats) >= 31
        assert all(p.raw[31] & 15 == 0 for p in pits)
        assert all(p.raw[31] & 15 for p in bats)


def test_no_duplicate_identity(league):
    seen = set()
    for stem, _ in BUILT:
        t = v20.Team.load(team_path(league, stem))
        for p in t.players[:40]:
            if not p.active:
                continue
            ident = (p['last'], p['first'], p['age'])
            assert ident not in seen, (stem, ident)
            seen.add(ident)


def db_rows(year, pid, tid):
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    bt = c.execute('select AB, R, H, "2B", "3B", HR, RBI, SB, CS, BB, SO, SH from batting'
                   ' where yearID=? and playerID=? and teamID=?',
                   (year, pid, tid)).fetchall()
    pt = c.execute('select W, L, CG, GS, SHO, SV, IPouts, H, ER, HR, BB, SO, BFP, BK, WP,'
                   ' R from pitching where yearID=? and playerID=? and teamID=?',
                   (year, pid, tid)).fetchall()
    c.close()
    return bt, pt


def u16(r, o):
    return r[o] | r[o + 1] << 8


def b2(r, o):
    return r[o] + r[o + 1]


def test_spot_facts_1985(league):
    nya = v20.Team.load(team_path(league, 'clasale6'))
    nyn = v20.Team.load(team_path(league, 'clasnle3'))

    def find(t, last):
        want = last.upper()
        for p in t.players[:40]:
            if p.active and p['last'].upper() == want:
                return p
        raise AssertionError(last)

    matt = find(nya, 'MATTINGLY')
    assert matt['year'] == YEAR
    bt, _ = db_rows(YEAR, 'mattido01', 'NYA')
    ab, r, h, d2, t3, hr, rbi, sb, cs, bb, so, sh = bt[0]
    assert (h, hr, rbi, ab) == (211, 35, 145, 652)
    assert u16(matt.raw, 0x29) + u16(matt.raw, 0x2b) == 211     # h_l + h_r
    assert matt.raw[0x33] + matt.raw[0x34] == 35                # hr_l + hr_r
    assert matt['rbi'] == 145
    assert matt.raw[31] & 15 == 2                   # pos1 = 1B

    gooden = find(nyn, 'GOODEN')
    _, pt = db_rows(YEAR, 'goodedw01', 'NYN')
    w, l, cg, gs, sho, sv, ipouts, h, er, hr, bb, so, bfp, bk, wp, ra = pt[0]
    assert (w, ipouts, so) == (24, 830, 268)
    assert gooden['w'] == 24
    assert u16(gooden.raw, 0x65) == (ipouts // 3) * 10 + ipouts % 3 == 2762
    assert u16(gooden.raw, 0x7d) + u16(gooden.raw, 0x7f) == 268   # pso_l + pso_r

    hend = find(nya, 'HENDERSON')
    bt, _ = db_rows(YEAR, 'henderi01', 'NYA')
    assert bt[0][7] == 80
    assert hend['sb'] == 80


def test_ratings_round_trip(league):
    for stem, _ in BUILT:
        t = v20.Team.load(team_path(league, stem))
        for p in t.players[:40]:
            r = p.raw
            if not r[0]:
                continue
            if r[31] & 15 == 0:
                pairs = [('control', ratings.control(r), r[134] & 15),
                         ('velocity', ratings.velocity(r), r[134] >> 4),
                         ('endurance', ratings.endurance(r), r[135] >> 4)]
            else:
                pairs = [('speed', ratings.speed(r), r[29] >> 4),
                         ('bunt', ratings.bunt(r), r[74] >> 4),
                         ('power', ratings.power(r), r[74] & 15),
                         ('hit_run', ratings.hit_and_run(r), r[75] & 15),
                         ('range', ratings.rng(r), r[94] >> 4),
                         ('arm', ratings.arm(r), r[94] & 15)]
            for k, calc, stored in pairs:
                assert stored == calc, (stem, k, v20.pname(r, 0), calc, stored)
            assert u16(r, 25) == ratings.salary(r)


def test_season_twins(league):
    for stem, _ in BUILT:
        t = v20.Team.load(team_path(league, stem))
        for i in range(40):
            rec, tw = t.players[i], t.players[i + 40]
            if rec.raw[0] == 0:
                assert tw.raw == bytearray(143)
                continue
            assert tw['last'] == rec['last'] and tw['first'] == rec['first']
            assert tw.raw[20:31] == rec.raw[20:31]           # bio bytes
            for f in ('bats', 'throws', 'pos1', 'pos2', 'salary', 'power', 'bunt',
                      'hit_run', 'speed', 'range', 'arm', 'control', 'velocity',
                      'endurance', 'games'):
                assert tw[f] == rec[f], (stem, f, v20.pname(rec.raw, 0))
            for f in build_season.STAT_FIELDS:
                assert tw[f] == 0, (stem, f, v20.pname(rec.raw, 0))
            assert tw.raw[141] == 0 and tw.raw[142] == 0


def test_header_partition(league):
    for stem, _ in BUILT:
        t = v20.Team.load(team_path(league, stem))
        staff = t.staff()
        assert len([s for s in staff if s != 0xff]) == 10
        assert len(set(staff)) == 10
        assert all(s < 16 for s in staff)
        # DH vs-RHP lineup set: 9 distinct batters
        lu = t.lineup(1, 1)
        dh_active = [s for s in lu if s != 0xff]
        assert len(dh_active) == 9 and len(set(dh_active)) == 9
        assert all(s >= 16 for s in dh_active)
        # reserves + the active lists cover every named slot exactly once
        res = t.reserves()
        covered = set(s for s in staff + res if s != 0xff)
        for dh in (0, 1):
            for vr in (0, 1):
                covered |= set(s for s in t.lineup(dh, vr) + t.bench(dh, vr)
                               if s != 0xff)
        named = set()
        for i in range(40):
            r = t.players[i]
            if r.raw[0]:
                named.add(i)
            else:
                # vacant slot: the season twin is zero in both halves
                assert t.players[i + 40].raw == bytearray(143)
        # vacant slots, when present, are the trailing slots of each type block
        vac_p = [s for s in range(16) if s not in named]
        n_p = len(vac_p)
        assert vac_p == list(range(16 - n_p, 16))
        vac_b = [s for s in range(16, 40) if s not in named]
        n_vb = len(vac_b)
        assert vac_b == list(range(40 - n_vb, 40))
        assert covered == named, (stem, sorted(named - covered), sorted(covered - named))
        # staff + reserves: distinct, and the union of staff + reserves + the DH
        # lineup/bench lists is the named set (the 15-slot reserves carry 0xff pads when
        # fewer than 16 pitchers are named, so the count varies)
        single = [s for s in staff + res if s != 0xff]
        assert len(single) == len(set(single))
        act = set()
        for dh in (0, 1):
            for vr in (0, 1):
                act |= set(t.lineup(dh, vr)) | set(t.bench(dh, vr))
        act = {s for s in act if s != 0xff}
        union = set(single) | act
        assert union == named, (stem, sorted(named - union))


def test_year_out_of_range(tmp_path):
    for year in (1976, 1993):
        out = os.path.join(tmp_path, 'x')
        rc = build_season.main(['build_season.py', str(year), str(out)])
        assert rc == 2
        assert not os.path.exists(out)
    # existing empty OUT_DIR is also left empty on exit 2
    out = os.path.join(tmp_path, 'y')
    os.mkdir(out)
    rc = build_season.main(['build_season.py', '1993', str(out)])
    assert rc == 2
    assert os.listdir(out) == []
