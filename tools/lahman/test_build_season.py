#!/usr/bin/env python3
"""H1 build_season tests. All skip if the Lahman DB or the template league is missing.
usage: python3 -m pytest -q tools/lahman/test_build_season.py"""
import os
import shutil
import sqlite3
import sys

import pytest

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import build_season                                              # noqa: E402
import ratings                                                   # noqa: E402
import v20                                                       # noqa: E402
from m4 import history                                           # noqa: E402
from m4 import realign                                           # noqa: E402
from m4 import teamids                                           # noqa: E402

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
    assert sorted(os.listdir(TEMPLATE) + ['HISTORY.DAT', 'REAL.DAT']) == sorted(os.listdir(league))
    for stem, _ in BUILT:
        with open(os.path.join(TEMPLATE, stem.upper() + '.V20'), 'rb') as f:
            s = f.read()
        with open(team_path(league, stem), 'rb') as f:
            d = f.read()
        # header bytes 0..110 kept from the template (name, colors, strategy, GM profile)
        assert s[:111] == d[:111]
    with open(os.path.join(TEMPLATE, 'CLASSIC.MAJ'), 'rb') as f:
        s = f.read()
    with open(os.path.join(league, 'CLASSIC.MAJ'), 'rb') as f:
        assert s == f.read()
    # ALLSTAR files are rebuilt from the built rosters (C9); their header bytes 0..110 stay the template's
    for name in ('ALLSTAR1.V20', 'ALLSTAR2.V20'):
        with open(os.path.join(TEMPLATE, name), 'rb') as f:
            s = f.read()
        with open(os.path.join(league, name), 'rb') as f:
            d = f.read()
        assert len(s) == len(d) and s[:111] == d[:111]


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
    for year in (1976, 2013):
        out = os.path.join(tmp_path, 'x')
        rc = build_season.main(['build_season.py', str(year), str(out)])
        assert rc == 2
        assert not os.path.exists(out)
    # existing empty OUT_DIR is also left empty on exit 2
    out = os.path.join(tmp_path, 'y')
    os.mkdir(out)
    rc = build_season.main(['build_season.py', '2013', str(out)])
    assert rc == 2
    assert os.listdir(out) == []


def test_fielding_by_position_1985(league):
    """Fielding comes from Lahman fielding.POS strings ('C', '1B', ..., 'OF'): Mattingly's 1B line and
    Carlton Fisk's catcher line (with PB) land in po1/a1/e1/dp1; every named infielder and catcher has po1 > 0."""
    import sqlite3
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)

    def fld(pid, tid, pos):
        return c.execute('select sum(PO), sum(A), sum(E), sum(DP), sum(PB) from fielding'
                         ' where playerID=? and yearID=? and teamID=? and POS=?',
                         (pid, YEAR, tid, pos)).fetchone()

    nya = v20.Team.load(team_path(league, 'clasale6'))
    cha = v20.Team.load(team_path(league, 'clasalw2'))
    matt = next(p for p in nya.players[:40] if p.active and p['last'].upper() == 'MATTINGLY')
    po, a, e, dp, _ = fld('mattido01', 'NYA', '1B')
    assert po > 1000
    assert (matt['po1'], matt['a1'], matt['e1'], matt['dp1']) == (po, a, e, min(dp, 255))
    fisk = next(p for p in cha.players[:40] if p.active and p['last'].upper() == 'FISK')
    assert fisk.raw[31] & 15 == 1
    po, a, e, dp, pb = fld('fiskca01', 'CHA', 'C')
    assert (fisk['po1'], fisk['a1'], fisk['pb']) == (po, a, pb)
    for stem, _ in BUILT:
        t = v20.Team.load(team_path(league, stem))
        for p in t.players[16:40]:
            if p.active and 1 <= (p.raw[31] & 15) <= 5 and p['games'] >= 40:
                assert p['po1'] > 0, (stem, v20.pname(p.raw, 0))


def test_allstars_from_built_rosters(league):
    """C9 at build time: every ALLSTAR record is a copy of a record on a built team of its own league (AL file from
    AL teams, NL from NL), not a template classic star."""
    for name, al in (('ALLSTAR1.V20', True), ('ALLSTAR2.V20', False)):
        star = open(os.path.join(league, name), 'rb').read()
        pool = set()
        for stem, _ in BUILT:
            if stem.startswith('clasal') != al:
                continue
            img = open(team_path(league, stem), 'rb').read()
            for s in range(40):
                r = img[295 + 143 * s:295 + 143 * (s + 1)]
                if r[0]:
                    pool.add(r)
        named = [star[295 + 143 * s:295 + 143 * (s + 1)] for s in range(40) if star[295 + 143 * s]]
        assert len(named) >= 30, (name, len(named))
        stale = [r[:14] for r in named if r not in pool]
        assert not stale, (name, stale[:3])


def _hist_and_found(league):
    """HISTORY.DAT and {(identity): (record bytes, pos1)} of the placed records,
    identity = (name bytes 0..19, birth = 1001 - age)."""
    with open(os.path.join(str(league), 'HISTORY.DAT'), 'rb') as f:
        h = history.History(f.read())
    found = {}
    for stem, _ in BUILT:
        t = v20.Team.load(team_path(league, stem))
        for i in range(40):
            r = t.players[i].raw
            if not r[0]:
                continue
            found.setdefault((bytes(r[0:20]), 1001 - r[0x14]),
                             (bytes(r), r[31] & 15))
    return h, found


def _match_pid(c, name20):
    """The Lahman playerID with a YEAR row whose folded nameLast[:11]/nameFirst[:7]
    match the V20 record's name bytes 0..19, or None when not decisive."""
    last = build_season.fold(bytes(name20[0:12]).split(b'\x00')[0].decode('latin-1')).upper()
    first = build_season.fold(bytes(name20[12:20]).split(b'\x00')[0].decode('latin-1')).upper()
    if not last:
        return None
    cands = c.execute('select playerID, nameLast, nameFirst from people'
                      ' where playerID in (select playerID from batting where yearID=?'
                      ' union select playerID from pitching where yearID=?)',
                      (YEAR, YEAR)).fetchall()
    pids = {r[0] for r in cands
            if build_season.fold(r[1] or '')[:11].upper() == last
            and build_season.fold(r[2] or '')[:7].upper() == first}
    return pids.pop() if len(pids) == 1 else None


def _career_years(c, pid):
    """Distinct pre-1985 yearIDs over the player's batting and pitching rows."""
    return {y for (y,) in c.execute(
        'select yearID from batting where playerID=? and yearID<?'
        ' union select yearID from pitching where playerID=? and yearID<?',
        (pid, YEAR, pid, YEAR))}


def _db_totals(c, pid):
    """The pre-1985 totals in history.TOTALS order, NULL as 0 (C36 rule 3)."""
    t = [0] * 25
    for tab, cols, base in (
            ('batting', ('G', 'AB', 'H', '2B', '3B', 'HR', 'R', 'RBI', 'BB', 'SO',
                         'SB', 'CS'), 0),
            ('fielding', ('E',), 12),
            ('pitching', ('W', 'L', 'SV', 'GS', 'CG', 'SHO', 'IPouts', 'ER',
                          'H', 'BB', 'SO', 'HR'), 13)):
        sel = ', '.join('coalesce("%s", 0)' % x for x in cols)
        for row in c.execute('select %s from %s where playerID=? and yearID<?' % (sel, tab),
                             (pid, YEAR)):
            for j, v in enumerate(row):
                t[base + j] += v
    return t


def _db_awards(c, pid):
    """Pre-1985 award counts (MVP, CY, ROY, GG, SS), each capped at 255."""
    out = [0] * 5
    for aid, n in c.execute('select awardID, count(*) from awardsplayers'
                            ' where playerID=? and yearID<? group by awardID',
                            (pid, YEAR)):
        if aid in AWARD_NAMES:
            out[AWARD_NAMES.index(aid)] += n
    return [min(255, v) for v in out]


AWARD_NAMES = ['Most Valuable Player', 'Cy Young Award', 'Rookie of the Year',
               'Gold Glove', 'Silver Slugger']


def test_history_header_and_identities(league):
    with open(os.path.join(str(league), 'HISTORY.DAT'), 'rb') as f:
        h = history.History(f.read())
    assert h.version == 1
    assert h.start_year == YEAR
    assert h.seasons_recorded == 0
    entries = [h.read_entry(i) for i in h.entries()]
    idents = [(e['name'], e['birth']) for e in entries]
    assert len(idents) == len(set(idents))              # a duplicated identity is skipped
    placed = set(_hist_and_found(league)[1])
    assert set(idents) <= placed                        # every entry is a placed record
    for e in entries:
        assert e['age'] == 1001 - e['birth']            # birth = 1001 - record age
        assert e['status'] == history.STATUS_ACTIVE
        assert e['first_season'] == 1 and e['last_season'] == 0
        if e['pitcher'] == 1:
            assert e['pos1'] == 0
        assert e['WAR10'] == 0 and e['JAWS10'] == 0 and e['hof_season'] == 0
        assert e['top7'] == [history.EMPTY_TOP] * 7


def test_history_count_totals_awards(league):
    """Exactly the placed players with a pre-1985 row have entries; every entry matched
    to the DB has seasons_played, totals and award counts equal to the DB sums."""
    h, found = _hist_and_found(league)
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    want = set()
    for ident in found:
        pid = _match_pid(c, ident[0])
        if pid and _career_years(c, pid):
            want.add(ident)
    got = [(h.read_entry(i)['name'], h.read_entry(i)['birth']) for i in h.entries()]
    assert len(got) == len(set(got))
    assert set(got) <= set(found)
    # a name shared by two YEAR players (two Mike Browns) is not decisive: compare the rest
    decisive = {i for i in got if _match_pid(c, i[0]) is not None}
    assert len(decisive) > 0.9 * len(got)
    assert decisive == want, (len(want), sorted(want - decisive)[:3],
                              sorted(decisive - want)[:3])
    for i in h.entries():
        e = h.read_entry(i)
        pid = _match_pid(c, e['name'])
        if pid is None:
            continue
        assert e['seasons_played'] == len(_career_years(c, pid)), (pid, e['name'])
        assert e['totals'] == _db_totals(c, pid), (pid, e['name'])
        assert e['awards'] == _db_awards(c, pid), (pid, e['name'])
    c.close()


def test_history_pete_rose(league):
    """Spot check from the DB at test time: the placed 1985 CIN Pete Rose entry."""
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    h_sum, _n = c.execute('select sum(H), count(*) from batting'
                          ' where playerID=? and yearID<?', ('rosepe01', YEAR)).fetchone()
    years = {y for (y,) in c.execute(
        'select yearID from batting where playerID=? and yearID<?'
        ' union select yearID from pitching where playerID=? and yearID<?',
        ('rosepe01', YEAR, 'rosepe01', YEAR))}
    c.close()
    # rosepe01 must be placed (1985 CIN, a real pre-1985 career)
    conn = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    hist, found = _hist_and_found(league)
    ident = next(i for i in found if _match_pid(conn, i[0]) == 'rosepe01')
    conn.close()
    e = next(hist.read_entry(i) for i in hist.entries()
             if (hist.read_entry(i)['name'], hist.read_entry(i)['birth']) == ident)
    assert e['pitcher'] == 0
    assert e['totals'][2] == h_sum                     # H = DB sum of batting H
    assert e['seasons_played'] == len(years)           # distinct pre-1985 years


def test_history_pitcher(league):
    """Spot check from the DB at test time: the placed pitcher with the most pre-1985 W."""
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    rows = c.execute('select playerID, sum(W), sum(IPouts), sum(SO) from pitching'
                     ' where yearID<? group by playerID order by sum(W) desc',
                     (YEAR,)).fetchall()
    c.close()
    hist, _found = _hist_and_found(league)
    cc = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    by_pid = {}
    for i in hist.entries():
        e = hist.read_entry(i)
        pid = _match_pid(cc, e['name'])
        if pid is not None:
            by_pid[pid] = i
    c.close()
    for pid, w, outs, so in rows:
        if pid in by_pid:
            e = hist.read_entry(by_pid[pid])
            assert e['pitcher'] == 1
            assert e['totals'][13] == w                # W
            assert e['totals'][19] == outs             # OUTS = IPouts
            assert e['totals'][23] == so               # PSO = SO
            return
    pytest.fail('no pre-1985 pitching leader placed in 1985')


def test_history_mvp_award(league):
    """Spot check from the DB at test time: a placed player with a pre-1985 MVP, his MVP
    count equals the DB count."""
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    rows = c.execute('select playerID, count(*) from awardsplayers where yearID<?'
                     ' and awardID=? group by playerID', (YEAR, 'Most Valuable Player')
                     ).fetchall()
    hist, _found = _hist_and_found(league)
    cc = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    by_pid = {}
    for i in hist.entries():
        pid = _match_pid(cc, hist.read_entry(i)['name'])
        if pid is not None:
            by_pid[pid] = i
    c.close()
    for pid, n in rows:
        if pid in by_pid:
            e = hist.read_entry(by_pid[pid])
            assert e['awards'][0] == n
            return
    pytest.fail('no pre-1985 MVP winner placed in 1985')


def test_history_rookie_no_entry(league):
    """A placed rookie with no pre-YEAR row has no entry."""
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    hist, found = _hist_and_found(league)
    got = {(hist.read_entry(i)['name'], hist.read_entry(i)['birth'])
           for i in hist.entries()}
    checked = 0
    for ident in found:
        pid = _match_pid(c, ident[0])
        if pid and not _career_years(c, pid):
            checked += 1
            assert ident not in got, ident
    c.close()
    assert checked, 'no placed rookie found'


@pytest.fixture(scope='module')
def league_nohist(tmp_path_factory):
    """A 1985 build with seed_history replaced by a no-op."""
    out = tmp_path_factory.mktemp('league') / 'hist1985_nohist'
    orig = build_season.seed_history
    build_season.seed_history = lambda *a, **k: None
    try:
        rc = build_season.main(['build_season.py', str(YEAR), str(out)])
        assert rc == 0, out
        return out
    finally:
        build_season.seed_history = orig


def test_v20_maj_unchanged_without_seed(league, league_nohist):
    """Every non-HISTORY file of a normal build equals the seeded-out build: V20, MAJ,
    the template files kept as-is, byte for byte."""
    assert sorted(os.listdir(league)) == sorted(os.listdir(league_nohist) + ['HISTORY.DAT'])
    for f in sorted(os.listdir(league)):
        if f.upper() == 'HISTORY.DAT':
            continue
        with open(os.path.join(str(league), f), 'rb') as fa:
            a = fa.read()
        with open(os.path.join(str(league_nohist), f), 'rb') as fb:
            b = fb.read()
        assert a == b, f


def test_team_lists():
    old = build_season.team_list(1985)
    assert len(old) == 26
    assert [(s, tid, k) for s, tid, k in old if s.startswith('clasnle')] == [
        ('clasnle1', 'CHN', 0), ('clasnle2', 'MON', 1), ('clasnle3', 'NYN', 2),
        ('clasnle4', 'PHI', 3), ('clasnle5', 'PIT', 4), ('clasnle6', 'SLN', 5)]
    assert [(s, tid, k) for s, tid, k in old if s.startswith('clasnlw')] == [
        ('clasnlw1', 'ATL', 8), ('clasnlw2', 'CIN', 9), ('clasnlw3', 'HOU', 10),
        ('clasnlw4', 'LAN', 11), ('clasnlw5', 'SDN', 12), ('clasnlw6', 'SFN', 13)]
    assert build_season.team_list(1992) == old
    new = build_season.team_list(1993)
    assert len(new) == 28
    fle = new.index(('clasnle7', 'FLO', 6))
    col = new.index(('clasnlw7', 'COL', 14))
    assert fle < col
    assert new[:len(old) - 6] == old[:len(old) - 6]          # AL unchanged
    # the six old NL East teams sit before FLO, the six old NL West teams before COL
    assert [tid for _, tid, _ in new[fle - 6:fle]] == ['CHN', 'MON', 'NYN', 'PHI', 'PIT', 'SLN']
    assert [tid for _, tid, _ in new[col - 6:col]] == ['ATL', 'CIN', 'HOU', 'LAN', 'SDN', 'SFN']


def test_maj_patch_minimal(tmp_path):
    # add_expansion patches only the two NL slot entries and the four count bytes
    src = os.path.join(TEMPLATE, 'CLASSIC.MAJ')
    img = bytearray(open(src, 'rb').read())
    for stem, tid, slot, name, abbr, tmpl in build_season.EXPANSION_1993:
        shutil.copyfile(os.path.join(TEMPLATE, tmpl.upper() + '.V20'),
                     os.path.join(str(tmp_path), tmpl.upper() + '.V20'))
    shutil.copyfile(src, str(tmp_path / 'classic.maj'))
    build_season.add_expansion(str(tmp_path))
    with open(str(tmp_path / 'classic.maj'), 'rb') as f:
        out = f.read()
    diff = [i for i in range(len(img)) if img[i] != out[i]]
    allowed = set()
    for stem, tid, slot, name, abbr, tmpl in build_season.EXPANSION_1993:
        allowed |= set(range(0x758c + 0x0f + 16 * slot, 0x758c + 0x0f + 16 * slot + 16))
        allowed |= set(range(0x758c + 0x18f + 3 * slot, 0x758c + 0x18f + 3 * slot + 3))
        allowed |= set(range(0x758c + 0x1d7 + 8 * slot, 0x758c + 0x1d7 + 8 * slot + 8))
    allowed |= {0x758c + 0x298, 0x758c + 0x299, 0x20e + 3, 0x20e + 4}
    assert set(diff) <= allowed, sorted(set(diff) - allowed)
    assert out[0x758c + 0x298] == 7 and out[0x758c + 0x299] == 7
    assert out[0x20e + 3] == 7 and out[0x20e + 4] == 7
    assert out[0x758c + 0x1d7 + 8 * 6:0x758c + 0x1d7 + 8 * 6 + 8] == b'clasnle7'
    assert out[0x758c + 0x1d7 + 8 * 14:0x758c + 0x1d7 + 8 * 14 + 8] == b'clasnlw7'
    assert out[0x758c + 0x0f + 16 * 6:0x758c + 0x0f + 16 * 6 + 7] == b'FLORIDA'
    assert out[0x758c + 0x0f + 16 * 14:0x758c + 0x0f + 16 * 14 + 8] == b'COLORADO'


def test_maj_patch_errors(tmp_path):
    src = os.path.join(TEMPLATE, 'CLASSIC.MAJ')
    for stem, tid, slot, name, abbr, tmpl in build_season.EXPANSION_1993:
        shutil.copyfile(os.path.join(TEMPLATE, tmpl.upper() + '.V20'),
                     os.path.join(str(tmp_path), tmpl.upper() + '.V20'))
    # no MAJ
    with pytest.raises(ValueError):
        build_season.add_expansion(str(tmp_path))
    # two MAJs
    shutil.copyfile(src, str(tmp_path / 'a.maj'))
    shutil.copyfile(src, str(tmp_path / 'b.MAJ'))
    with pytest.raises(ValueError):
        build_season.add_expansion(str(tmp_path))
    os.remove(str(tmp_path / 'b.MAJ'))
    # slot occupied: pre-seed the FLO stem
    img = bytearray(open(src, 'rb').read())
    img[0x758c + 0x1d7 + 8 * 6:0x758c + 0x1d7 + 8 * 6 + 8] = b'clasnle6'
    open(str(tmp_path / 'a.maj'), 'wb').write(bytes(img))
    with pytest.raises(ValueError):
        build_season.add_expansion(str(tmp_path))
    # truncated MAJ
    open(str(tmp_path / 'a.maj'), 'wb').write(bytes(img[:0x758c + 0x298]))
    with pytest.raises(ValueError):
        build_season.add_expansion(str(tmp_path))


@pytest.fixture(scope='module')
def league94(tmp_path_factory):
    out = tmp_path_factory.mktemp('league') / 'hist1994'
    rc = build_season.main(['build_season.py', '1994', str(out)])
    assert rc == 0, out
    return out


def _maj_bytes(league):
    with open(os.path.join(str(league), 'CLASSIC.MAJ'), 'rb') as f:
        return f.read()


DIV94_AL = {0: ['BAL', 'BOS', 'DET', 'NYA', 'TOR'], 8: ['CAL', 'OAK', 'SEA', 'TEX'],
            16: ['CLE', 'MIL', 'CHA', 'KC', 'MIN']}
DIV94_NL = {0: ['MON', 'NYN', 'PHI', 'FLA', 'ATL'], 8: ['LA', 'SD', 'SF', 'COL'],
            16: ['CHN', 'PIT', 'SL', 'CIN', 'HOU']}


def test_1994_three_divisions(league94):
    names = sorted(os.listdir(league94))
    assert 'TEAMID.DAT' in names and 'HISTORY.DAT' in names
    maj = _maj_bytes(league94)
    assert maj[0x20d] == 3 and maj[0x20a] == 0xf3
    for L in (0, 1):
        s = teamids.S[L]
        assert [maj[s + 0x298 + dv] for dv in range(3)] == [5, 4, 5]
        assert [maj[0x20e + 3 * L + dv] for dv in range(3)] == [5, 4, 5]
    for L, want in ((0, DIV94_AL), (1, DIV94_NL)):
        s = teamids.S[L]
        for start, abbrs in want.items():
            for i, abbr in enumerate(abbrs):
                a = s + teamids.O_ABBR + 3 * (start + i)
                got = bytes(maj[a:a + 3]).rstrip(b'\0').decode('latin-1')
                assert got == abbr, (L, start + i, abbr, got)


def test_1994_teamid_dat(league94):
    """TEAMID.DAT was written from the pre-realignment MAJ: every team's stable id is its
    2-division engine id (AL slot, NL slot + 16), and the ids survive the realignment."""
    with open(os.path.join(str(league94), 'TEAMID.DAT'), 'rb') as f:
        table = f.read()
    assert len(table) == 256
    d = _maj_bytes(league94)
    tl = build_season.team_list(1994)
    for stem, tid, slot in tl:
        L = 0 if stem.startswith('clasal') else 1
        k = slot if L == 0 else slot + 16
        assert table[8 * k:8 * k + 8].rstrip(b'\0').decode('latin-1') == stem, stem
    teams = teamids.teams(d, table)
    assert len(teams) == 28
    for _k, L, slot, st in teams:
        stem = st.rstrip(b'\0').decode('latin-1')
        slot2 = {s2: sl for s2, _t, sl in tl if s2 == stem}[stem]
        assert _k == (slot2 if L == 0 else slot2 + 16), (_k, L, slot2, stem)
    # every stem of the realigned MAJ appears exactly once in the table
    for _L, _slot, st in teamids.maj_teams(d):
        assert sum(1 for k in range(32) if table[8 * k:8 * k + 8] == st) == 1


def test_1994_history(league94):
    with open(os.path.join(str(league94), 'HISTORY.DAT'), 'rb') as f:
        assert f.read()[0] == 1


@pytest.fixture(scope='module')
def league93(tmp_path_factory):
    out = tmp_path_factory.mktemp('league') / 'hist1993'
    rc = build_season.main(['build_season.py', '1993', str(out)])
    assert rc == 0, out
    return out


def test_expansion_headers(league93):
    for stem, name, abbr in (('clasnle7', 'FLORIDA', 'FLA'), ('clasnlw7', 'COLORADO', 'COL')):
        t = v20.Team.load(team_path(league93, stem))
        assert (t.name, t.abbr, t.stadium) == (name, abbr, 'grass')
        # header bytes 0..110 in the untouched part are still the copied template's
        with open(os.path.join(TEMPLATE, 'CLASNLE6.V20' if stem == 'clasnle7'
                               else 'CLASNLW6.V20'), 'rb') as f:
            s = f.read()
        with open(team_path(league93, stem), 'rb') as f:
            d = f.read()
        assert len(s) == len(d)
        assert s[27:111] == d[27:111]


def test_1993_maj(league93):
    with open(os.path.join(TEMPLATE, 'CLASSIC.MAJ'), 'rb') as f:
        img = f.read()
    majs = [f for f in os.listdir(league93) if f.upper().endswith('.MAJ')]
    assert majs == ['CLASSIC.MAJ']
    with open(os.path.join(league93, majs[0]), 'rb') as f:
        out = f.read()
    assert len(out) == len(img)
    diff = [i for i in range(len(img)) if img[i] != out[i]]
    allowed = set()
    for stem, tid, slot, name, abbr, tmpl in build_season.EXPANSION_1993:
        allowed |= set(range(0x758c + 0x0f + 16 * slot, 0x758c + 0x0f + 16 * slot + 16))
        allowed |= set(range(0x758c + 0x18f + 3 * slot, 0x758c + 0x18f + 3 * slot + 3))
        allowed |= set(range(0x758c + 0x1d7 + 8 * slot, 0x758c + 0x1d7 + 8 * slot + 8))
    allowed |= {0x758c + 0x298, 0x758c + 0x299, 0x20e + 3, 0x20e + 4}
    assert set(diff) <= allowed, sorted(set(diff) - allowed)


def test_1993_files_and_teamids(league93):
    names = sorted(os.listdir(league93))
    for stem, tid, slot in build_season.team_list(1993):
        assert (stem.upper() + '.V20') in names, stem
    assert names.count('ALLSTAR1.V20') == 1 and names.count('ALLSTAR2.V20') == 1
    assert names.count('CLASSIC.MAJ') == 1
    assert len(names) == len(os.listdir(TEMPLATE)) + 4          # 28 V20 + ALLSTAR1/2 + MAJ + HISTORY.DAT + REAL.DAT (C74)
    assert names.count('REAL.DAT') == 1
    assert len(build_season.team_list(1993)) == 28
    import m4.teamids as teamids
    teams = teamids.maj_teams(open(os.path.join(str(league93), 'CLASSIC.MAJ'), 'rb').read())
    assert len(teams) == 28
    stems = [t[2].split(b'\0', 1)[0].decode('latin-1') for t in teams]
    assert stems == [s for s, _, _ in build_season.team_list(1993)]
    for t in teams:
        assert t[0] == (0 if t[2].startswith(b'clasal') else 1)


def test_1993_rosters(league93):
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    for stem, tid in (('clasnle7', 'FLO'), ('clasnlw7', 'COL')):
        t = v20.Team.load(team_path(league93, stem))
        named = [p for p in t.players[:40] if p.raw[0]]
        assert len(named) >= 20, (stem, len(named))
        db_names = {row[0].upper() for row in c.execute(
            'select nameLast from people p join appearances a on p.playerID=a.playerID'
            ' where a.yearID=1993 and a.teamID=? and a.G_all > 0', (tid,))}
        for p in named:
            assert p['last'].upper() in db_names, (stem, p['last'])
    # spot: each team's 1993 AB leader is on the roster by name
    for stem, tid, want_last in (('clasnle7', 'FLO', None), ('clasnlw7', 'COL', None)):
        pid, last, first = c.execute(
            'select b.playerID, p.nameLast, p.nameFirst from batting b join people p'
            ' on b.playerID=p.playerID where b.yearID=1993 and b.teamID=?'
            ' order by b.AB desc limit 1', (tid,)).fetchone()
        t = v20.Team.load(team_path(league93, stem))
        assert any(p.active and p['last'].upper() == last.upper()
                   for p in t.players[:40]), (stem, last, pid)


@pytest.fixture(scope='module')
def league97(tmp_path_factory):
    out = tmp_path_factory.mktemp('league') / 'hist1997'
    rc = build_season.main(['build_season.py', '1997', str(out)])
    assert rc == 0, out
    return out


def test_1997_ana_rename(league97):
    t = v20.Team.load(team_path(league97, 'clasalw1'))
    assert (t.name, t.abbr) == ('ANAHEIM', 'ANA')
    with open(os.path.join(str(league97), 'CLASSIC.MAJ'), 'rb') as f:
        d = f.read()
    s = teamids.S[0]
    # ANA is in the West block (DIV94_AL's CAL spot) in team_list order
    a = s + teamids.O_ABBR + 3 * 8
    assert bytes(d[a:a + 3]).rstrip(b'\0') == b'ANA'
    n = s + teamids.O_NAMES + 16 * 8
    assert bytes(d[n:n + 16]).rstrip(b'\0') == b'ANAHEIM'
    assert bytes(d[s + teamids.O_ABBR:s + teamids.O_ABBR + 3]).rstrip(b'\0') == b'BAL'
    assert d[0x20d] == 3


def test_1997_ana_players_from_lahman(league97):
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    t = v20.Team.load(team_path(league97, 'clasalw1'))
    db_names = {row[0].upper() for row in c.execute(
        'select nameLast from people p join appearances a on p.playerID=a.playerID'
        ' where a.yearID=1997 and a.teamID="ANA" and a.G_all > 0')}
    named = [p for p in t.players[:40] if p.raw[0]]
    assert len(named) >= 20
    for p in named:
        assert p['last'].upper() in db_names, p['last']
    c.close()


def test_1993_no_teamid(league93):
    with open(os.path.join(str(league93), 'CLASSIC.MAJ'), 'rb') as f:
        d = f.read()
    assert d[0x20d] == 2 and d[0x20a] != 0xf3
    assert not [f for f in os.listdir(league93) if f.upper() == 'TEAMID.DAT']
    with open(os.path.join(str(league93), 'HISTORY.DAT'), 'rb') as f:
        assert f.read()[0] == 0


def test_1994_1997_history_rolled(league94, league97):
    for lg in (league94, league97):
        with open(os.path.join(str(lg), 'HISTORY.DAT'), 'rb') as f:
            assert f.read()[0] == 1


def _classic_maj_bytes():
    with open(os.path.join(TEMPLATE, 'CLASSIC.MAJ'), 'rb') as f:
        return f.read()


def test_realign_known_table_overrides_default():
    """realign(known=...) with the default KNOWN table is byte-identical to known=None; a known
    table with the same AL abbr set in another order changes the AL and leaves the NL alone."""
    d = _classic_maj_bytes()
    new, why = realign.realign(d, 3)
    assert why is None
    same, why1 = realign.realign(d, 3, known=realign.KNOWN[3])
    assert why1 is None and same == new
    al = [['BAL', 'BOS', 'CLE', 'NYA', 'TOR'], ['CAL', 'OAK', 'SEA', 'TEX'],
          ['CHA', 'DET', 'KC', 'MIL', 'MIN']]
    moved, why2 = realign.realign(d, 3, known={0: al, 1: realign.KNOWN[3][1]})
    assert why2 is None
    s0, s1 = teamids.S[0], teamids.S[1]
    assert moved[s0 + 0x0f:s0 + 0x2b3] != new[s0 + 0x0f:s0 + 0x2b3]
    assert moved[s1 + 0x0f:s1 + 0x2b3] == new[s1 + 0x0f:s1 + 0x2b3]


def test_2013_out_of_range(tmp_path):
    out = os.path.join(tmp_path, 'x')
    assert build_season.YEAR_MAX == 2012
    rc = build_season.main(['build_season.py', '2013', str(out)])
    assert rc == 2
    assert not os.path.exists(out)


@pytest.mark.parametrize('year', [1998, 2005, 2012])
def test_team_list_lahman_ids(year):
    """Every 1998+ teamID is a real Lahman `teams` row of that year; 30 entries."""
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    ids = {r[0] for r in c.execute('select teamID from teams where yearID=?', (year,))}
    c.close()
    tl = build_season.team_list(year)
    assert len(tl) == 30
    wrong = [(s, t) for s, t, _k in tl if t not in ids]
    assert not wrong, (year, wrong)


def test_team_list_30_stems_slots():
    for year in (1998, 2005, 2012):
        tl = build_season.team_list(year)
        assert [(s, t) for s, t, _k in tl if s.startswith('clasal')] == [
            ('clasale1', 'BAL'), ('clasale2', 'BOS'), ('clasale3', 'CLE'),
            ('clasale4', 'DET'), ('clasale5', 'TBA'), ('clasale6', 'NYA'),
            ('clasale7', 'TOR'), ('clasalw1', 'ANA' if year <= 2004 else 'LAA'),
            ('clasalw2', 'CHA'), ('clasalw3', 'KCA'), ('clasalw4', 'MIN'),
            ('clasalw5', 'OAK'), ('clasalw6', 'SEA'), ('clasalw7', 'TEX')]
        mon = 'MON' if year <= 2004 else 'WAS'
        fla = 'FLO' if year <= 2011 else 'MIA'
        assert [(s, t) for s, t, _k in tl if s.startswith('clasnle')] == [
            ('clasnle1', 'CHN'), ('clasnle2', mon), ('clasnle3', 'NYN'),
            ('clasnle4', 'PHI'), ('clasnle5', 'PIT'), ('clasnle6', 'SLN'),
            ('clasnle7', fla), ('clasnle8', 'MIL')]
        assert [(s, t) for s, t, _k in tl if s.startswith('clasnlw')] == [
            ('clasnlw1', 'ATL'), ('clasnlw2', 'CIN'), ('clasnlw3', 'HOU'), ('clasnlw4', 'LAN'),
            ('clasnlw5', 'SDN'), ('clasnlw6', 'SFN'), ('clasnlw7', 'COL'), ('clasnlw8', 'ARI')]
        assert [k for _s, _t, k in tl if _s.startswith('clasal')] == \
            list(range(7)) + list(range(8, 15))
        assert sorted(k for _s, _t, k in tl if _s.startswith('clasnl')) == \
            sorted(list(range(8)) + list(range(8, 16)))


def _stem_at(d, L, slot):
    a = teamids.S[L] + 0x1d7 + 8 * slot
    return bytes(d[a:a + 8]).rstrip(b'\0').decode('latin-1').lower()


def _maj_entry(d, L, stem):
    """(name, abbr) of the realigned MAJ slot holding stem in league L."""
    s = teamids.S[L]
    for slot in range(24):
        if _stem_at(d, L, slot) == stem:
            n = bytes(d[s + teamids.O_NAMES + 16 * slot:s + teamids.O_NAMES + 16 * slot + 16])
            a = bytes(d[s + teamids.O_ABBR + 3 * slot:s + teamids.O_ABBR + 3 * slot + 3])
            return n.split(b'\0')[0], a.rstrip(b'\0')
    raise AssertionError('stem %s not in league %d' % (stem, L))


def _league_divisions(year, out_dir):
    """({L: [stem sets of realigned division 0, 1, 2]}, {L: [stem sets per Lahman divID
    E, W, C]}, {L: (division count bytes 0, 1, 2)}) for the year's teams."""
    with open(os.path.join(str(out_dir), 'CLASSIC.MAJ'), 'rb') as f:
        d = f.read()
    c = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    div = dict(c.execute('select teamID, divID from teams where yearID=?', (year,)))
    c.close()
    tl = build_season.team_list(year)
    got, want, counts = {}, {}, {}
    for L, prefix in ((0, 'clasal'), (1, 'clasnl')):
        s = teamids.S[L]
        counts[L] = tuple(d[s + 0x298 + dv] for dv in range(3))
        got[L] = [{_stem_at(d, L, dv * 8 + i) for i in range(counts[L][dv])} for dv in range(3)]
        want[L] = [set(), set(), set()]
        for stem, tid, _slot in tl:
            if stem.startswith(prefix):
                want[L]['EWC'.index(div[tid])].add(stem)
    return got, want, counts


DIV_INTEREST = [1998, 2005, 2012]


@pytest.fixture(scope='module', params=DIV_INTEREST)
def league30(tmp_path_factory, request):
    year = request.param
    out = tmp_path_factory.mktemp('league') / ('hist%d' % year)
    rc = build_season.main(['build_season.py', str(year), str(out)])
    assert rc == 0, out
    return year, out


def test_30_team_maj(league30):
    year, lg = league30
    names = sorted(os.listdir(lg))
    assert 'TEAMID.DAT' in names
    for f in ('CLASALE5.V20', 'CLASNLE8.V20', 'CLASNLW8.V20'):
        assert f in names
    maj = _maj_bytes(lg)
    assert maj[0x20d] == 3 and maj[0x20a] == 0xf3
    got, want, counts = _league_divisions(year, lg)
    for L in (0, 1):
        s = teamids.S[L]
        assert [maj[s + 0x298 + dv] for dv in range(3)] == list(counts[L])
        assert [maj[0x20e + 3 * L + dv] for dv in range(3)] == list(counts[L])
        assert sum(counts[L]) == (14 if L == 0 else 16)
        assert max(counts[L]) <= 8 and min(counts[L]) >= 4


def test_30_team_divisions_match_lahman(league30):
    """Per league, the set of MAJ abbrs in each realigned division equals the Lahman
    divID grouping of that year's teamIDs (the known table drove the packing)."""
    year, lg = league30
    got, want, _counts = _league_divisions(year, lg)
    assert got == want, (year, got, want)


@pytest.fixture(scope='module')
def league98(tmp_path_factory):
    out = tmp_path_factory.mktemp('league') / 'hist1998b'
    rc = build_season.main(['build_season.py', '1998', str(out)])
    assert rc == 0, out
    return out


def test_1998_files(league98):
    t = v20.Team.load(team_path(league98, 'clasale5'))
    assert (t.name, t.abbr) == ('TAMPA BAY', 'TB')
    t = v20.Team.load(team_path(league98, 'clasnle8'))
    assert (t.name, t.abbr) == ('MILWAUKEE', 'MIL')
    t = v20.Team.load(team_path(league98, 'clasnlw8'))
    assert (t.name, t.abbr, t.stadium) == ('ARIZONA', 'ARI', 'grass')
    with open(os.path.join(str(league98), 'TEAMID.DAT'), 'rb') as f:
        assert len(f.read()) == 256
    with open(os.path.join(str(league98), 'HISTORY.DAT'), 'rb') as f:
        assert f.read()[0] == 1


@pytest.fixture(scope='module')
def league2005(tmp_path_factory):
    out = tmp_path_factory.mktemp('league') / 'hist2005'
    rc = build_season.main(['build_season.py', '2005', str(out)])
    assert rc == 0, out
    return out


def test_2005_renames(league2005):
    t = v20.Team.load(team_path(league2005, 'clasalw1'))
    assert (t.name, t.abbr) == ('LA ANGELS', 'LAA')
    t = v20.Team.load(team_path(league2005, 'clasnle2'))
    assert (t.name, t.abbr) == ('WASHINGTON', 'WAS')
    t = v20.Team.load(team_path(league2005, 'clasnle7'))
    assert (t.name, t.abbr) == ('FLORIDA', 'FLA')
    with open(os.path.join(str(league2005), 'CLASSIC.MAJ'), 'rb') as f:
        d = f.read()
    assert _maj_entry(d, 0, 'clasalw1') == (b'LA ANGELS', b'LAA')
    assert _maj_entry(d, 1, 'clasnle2') == (b'WASHINGTON', b'WAS')
    assert _maj_entry(d, 1, 'clasnle7') == (b'FLORIDA', b'FLA')


@pytest.fixture(scope='module')
def league2012(tmp_path_factory):
    out = tmp_path_factory.mktemp('league') / 'hist2012'
    rc = build_season.main(['build_season.py', '2012', str(out)])
    assert rc == 0, out
    return out


def test_2012_miami(league2012):
    t = v20.Team.load(team_path(league2012, 'clasnle7'))
    assert (t.name, t.abbr) == ('MIAMI', 'MIA')
    with open(os.path.join(str(league2012), 'CLASSIC.MAJ'), 'rb') as f:
        d = f.read()
    assert _maj_entry(d, 1, 'clasnle7') == (b'MIAMI', b'MIA')


def test_1998_nl_allstar_entry_restored(league30):
    """C46: ARI fills the NL slot 15 all-star entry before the realign; after it, slot 15 is free
    and holds the template's ALL STARS 2 entry again (name, abbr, NUL-led stem), as in the AL."""
    lg = league30[1]
    d = _maj_bytes(lg)
    t = _classic_maj_bytes()
    for L in (0, 1):
        s = teamids.S[L]
        for o, n in ((teamids.O_NAMES, 16), (teamids.O_ABBR, 3), (teamids.O_STEM, 8)):
            a = s + o + n * 15
            assert d[a:a + n] == t[a:a + n], (L, o)
    assert d[teamids.S[1] + teamids.O_STEM + 8 * 15] == 0


# ---------------------------------------------------------------- C74 REAL.DAT
@pytest.fixture(scope='module')
def real93(tmp_path_factory):
    """a 1993 build and the `placed` list build_league returned for it"""
    out = tmp_path_factory.mktemp('league') / 'real1993'
    orig, box = build_season.build_league, []

    def spy(*a, **k):
        box.append(orig(*a, **k))
        return box[-1]
    build_season.build_league = spy
    try:
        rc = build_season.main(['build_season.py', '1993', str(out)])
    finally:
        build_season.build_league = orig
    assert rc == 0, out
    return out, box[0]


def check_real_dat(raw, year, placed, db):
    """REAL.DAT bytes of a real build against the Lahman db: header, one team record per team of
    team_list(year) with the db's W and L, one player record per placed player in order, and the
    totals of every 40th player against the db's sums over all his stints"""
    import struct
    tl = build_season.team_list(year)
    assert raw[0:4] == b'RL\x01\x00' and struct.unpack_from('<H', raw, 4)[0] == year
    t, p = raw[6], struct.unpack_from('<H', raw, 8)[0]
    assert raw[7] == 0 and raw[10:16] == bytes(6)
    assert (t, p) == (len(tl), len(placed))
    assert len(raw) == 16 + 8 * t + 80 * p
    c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
    want = {}
    for stem, tid, slot in tl:
        k = slot + (0 if stem.startswith('clasal') else 16)
        w, l = c.execute('select W, L from teams where yearID=? and teamID=?', (year, tid)).fetchone()
        want[k] = (w, l)
    got = {}
    for i in range(t):
        k, z, w, l, z2 = struct.unpack_from('<BBHHH', raw, 16 + 8 * i)
        assert (z, z2) == (0, 0)
        got[k] = (w, l)
    assert got == want
    assert list(got) == sorted(got)
    base = 16 + 8 * t
    for i, (name20, birth, pid, pos1, age) in enumerate(placed):
        r = raw[base + 80 * i:base + 80 * (i + 1)]
        assert r[0:20] == name20 and struct.unpack_from('<H', r, 20)[0] == birth
        assert r[22] in want and r[23] == (1 if pos1 == 0 else 0) and r[74:80] == bytes(6)
        if i % 40:
            continue
        tot = struct.unpack_from('<25H', r, 24)
        ab, h, hr = c.execute('select sum(AB), sum(H), sum(HR) from batting where playerID=?'
                              ' and yearID=?', (pid, year)).fetchone()
        assert (tot[1], tot[2], tot[5]) == (min(ab or 0, 0xffff), min(h or 0, 0xffff),
                                            min(hr or 0, 0xffff)), pid
        w, outs, er, g = c.execute('select sum(W), sum(IPouts), sum(ER), sum(G) from pitching where'
                                   ' playerID=? and yearID=?', (pid, year)).fetchone()
        assert (tot[13], tot[19], tot[20]) == (w or 0, outs or 0, er or 0), pid
        if pos1 == 0:
            assert tot[0] == (g or 0), pid
    c.close()


def test_1993_real_dat(real93):
    """C74: a 1993 build writes REAL.DAT last: 28 team records (the db's W and L), one player
    record per placed player, the header year 1993"""
    out, placed = real93
    raw = open(os.path.join(str(out), 'REAL.DAT'), 'rb').read()
    assert raw[6] == 28
    assert len(placed) > 700
    check_real_dat(raw, 1993, placed, build_season.DB)
