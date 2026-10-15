#!/usr/bin/env python3
"""C74 write_real tests (tools/lahman/build_season.py): a synthetic Lahman sqlite and a synthetic league
dir in tmp_path, nothing from /mnt/nvme. test_build_season.py skips as a whole without the Lahman DB, so the
synthetic cases live here and run anywhere.
usage: python3 -m pytest -q tools/lahman/test_write_real.py"""
import os
import sqlite3
import struct
import sys

import pytest

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_TOOLS, os.path.join(_TOOLS, 'm4')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_season                                              # noqa: E402
from m4 import teamids                                           # noqa: E402
from test_teamids import build_maj                               # noqa: E402

YEAR = 1990
SCHEMA = [
    'create table teams (yearID int, teamID text, divID text, W int, L int)',
    'create table appearances (yearID int, teamID text, playerID text, G_all int, G_p int, G_c int,'
    ' G_1b int, G_2b int, G_3b int, G_ss int, G_lf int, G_cf int, G_rf int, G_dh int)',
    'create table batting (playerID text, yearID int, teamID text, G int, AB int, R int, H int,'
    ' "2B" int, "3B" int, HR int, RBI int, SB int, CS int, BB int, SO int, SH int)',
    'create table pitching (playerID text, yearID int, teamID text, W int, L int, G int, GS int,'
    ' CG int, SHO int, SV int, IPouts int, H int, ER int, HR int, BB int, SO int, BFP int, BK int,'
    ' WP int, R int)',
    'create table fielding (playerID text, yearID int, teamID text, POS text, G int, PO int, A int,'
    ' E int, DP int, PB int)']


def make_db(path):
    """BAL 76-85 and BOS 88-74 in 1990 (and BAL 1989, which must not leak in); aaa01 split BAL (60 G)
    then BOS (100 G) so he is placed on BOS, with a NULL CS and a NULL fielding E; ppp01 a BAL pitcher
    (batting G 29, pitching G 30, a NULL SHO); big01 a BOS batter whose AB sum passes 0xffff;
    ghost01 a batter with no batting row at all."""
    c = sqlite3.connect(str(path))
    for sql in SCHEMA:
        c.execute(sql)
    c.executemany('insert into teams values (?,?,?,?,?)',
                  [(1990, 'BAL', 'E', 76, 85), (1990, 'BOS', 'E', 88, 74), (1989, 'BAL', 'E', 87, 75)])
    app = lambda tid, pid, g, gp, g1b: (1990, tid, pid, g, gp, 0, g1b, 0, 0, 0, 0, 0, 0, 0)
    c.executemany('insert into appearances values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  [app('BAL', 'aaa01', 60, 0, 60), app('BOS', 'aaa01', 100, 0, 100),
                   app('BAL', 'ppp01', 30, 30, 0), app('BOS', 'big01', 150, 0, 150),
                   app('BOS', 'ghost01', 20, 0, 20)])
    c.executemany('insert into batting values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', [
        ('aaa01', 1990, 'BAL', 60, 200, 25, 50, 10, 1, 5, 20, 3, 1, 15, 40, 2),
        ('aaa01', 1990, 'BOS', 100, 400, 60, 120, 20, 2, 15, 70, 5, None, 40, 80, 1),
        ('aaa01', 1989, 'BAL', 99, 999, 99, 99, 99, 9, 99, 99, 9, 9, 99, 99, 9),
        ('ppp01', 1990, 'BAL', 29, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0),
        ('big01', 1990, 'BOS', 150, 70000, 5, 4, 3, 2, 1, 6, 7, 8, 9, 10, 11)])
    c.executemany('insert into pitching values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', [
        ('ppp01', 1990, 'BAL', 10, 8, 30, 28, 3, None, 0, 550, 190, 70, 20, 60, 150, 800, 1, 2, 90),
        ('ppp01', 1988, 'BAL', 1, 1, 9, 9, 9, 9, 9, 99, 99, 99, 9, 99, 99, 99, 9, 9, 99)])
    c.executemany('insert into fielding values (?,?,?,?,?,?,?,?,?,?)', [
        ('aaa01', 1990, 'BAL', '1B', 60, 400, 20, 3, 30, 0),
        ('aaa01', 1990, 'BOS', 'OF', 100, 200, 5, None, 0, 0),
        ('aaa01', 1990, 'BOS', '1B', 4, 20, 1, 2, 1, 0),
        ('ppp01', 1990, 'BAL', 'P', 30, 10, 40, 1, 2, 0)])
    c.commit()
    c.close()


def make_league(path, stems=(b'clasale1', b'clasale2')):
    """a league dir with a 2-division MAJ whose AL slots 0 and 1 carry the stems (the clas* stems the
    build writes) and no TEAMID.DAT, so the stable ids are the engine ids 0 and 1"""
    path.mkdir(parents=True, exist_ok=True)
    d = bytearray(build_maj({0: [(0, 'BAL'), (1, 'BOS')]}))
    for slot, st in enumerate(stems):
        a = teamids.S[0] + teamids.O_STEM + 8 * slot
        d[a:a + 8] = st.ljust(8, b'\0')
    (path / 'CLASSIC.MAJ').write_bytes(bytes(d))
    return str(path)


def name20(last, first):
    return last.encode().ljust(12, b'\0') + first.encode().ljust(8, b'\0')


# (name20, birth key, Lahman playerID, pos1, age) as build_team appends them
PLACED = [(name20('AAA', 'A'), 974, 'aaa01', 3, 27), (name20('PPP', 'P'), 976, 'ppp01', 0, 25),
          (name20('BIG', 'B'), 971, 'big01', 3, 30), (name20('GHOST', 'G'), 980, 'ghost01', 3, 21)]


def player(nm, birth, team, flags, tot):
    return nm + struct.pack('<HBB', birth, team, flags) + struct.pack('<25H', *tot) + bytes(6)


def expected():
    hdr = b'RL' + bytes([1, 0]) + struct.pack('<H', YEAR) + bytes([2, 0]) + struct.pack('<H', 4) + bytes(6)
    teams = struct.pack('<BBHHH', 0, 0, 76, 85, 0) + struct.pack('<BBHHH', 1, 0, 88, 74, 0)
    #        G    AB  H   2B 3B HR R   RBI BB  SO  SB CS E   W L SV GS CG SHO OUTS ER PH PBB PSO PHR
    aaa = [160, 600, 170, 30, 3, 20, 85, 90, 55, 120, 8, 1, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    ppp = [30, 2, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 10, 8, 0, 28, 3, 0, 550, 70, 190, 60, 150, 20]
    big = [150, 0xffff, 4, 3, 2, 1, 5, 6, 9, 10, 7, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    return (hdr + teams + player(PLACED[0][0], 974, 1, 0, aaa) + player(PLACED[1][0], 976, 0, 1, ppp)
            + player(PLACED[2][0], 971, 1, 0, big) + player(PLACED[3][0], 980, 1, 0, [0] * 25))


def test_exact_bytes(tmp_path):
    """header, two team records in id order, four player records in placed order: aaa01 (two stints
    summed, placed on BOS, a NULL cell and a NULL fielding E as 0, the 1989 row ignored), ppp01 (flags 1,
    pitching G 30 not batting G 29, NULL SHO as 0), big01 (AB capped at 0xffff), ghost01 (all zero)"""
    db = tmp_path / 'lahman.sqlite'
    make_db(db)
    lg = make_league(tmp_path / 'lg')
    build_season.write_real(str(db), YEAR, lg, PLACED)
    got = open(os.path.join(lg, 'REAL.DAT'), 'rb').read()
    want = expected()
    assert len(got) == 16 + 2 * 8 + 4 * 80
    assert got == want


def test_team_without_lahman_row_has_no_record(tmp_path):
    """a team of team_list(YEAR) that has no teams row gets no team record; a player placed on a
    team with no stable id (a stem the MAJ does not carry) gets team id 0xff"""
    db = tmp_path / 'lahman.sqlite'
    make_db(db)
    c = sqlite3.connect(str(db))
    c.execute("delete from teams where teamID='BAL'")
    c.commit()
    c.close()
    lg = make_league(tmp_path / 'lg', stems=(b'other1', b'clasale2'))
    build_season.write_real(str(db), YEAR, lg, PLACED)
    got = open(os.path.join(lg, 'REAL.DAT'), 'rb').read()
    assert got[6] == 1                                       # T: BOS only
    assert got[16:24] == struct.pack('<BBHHH', 1, 0, 88, 74, 0)
    assert got[8:10] == b'\x04\x00'
    players = [got[24 + 80 * k:24 + 80 * (k + 1)] for k in range(4)]
    assert [p[22] for p in players] == [1, 0xff, 1, 1]       # ppp01's BAL has no stable id here


def test_stable_ids_follow_teamid_dat(tmp_path):
    """with a TEAMID.DAT the stable id is the table's index of the stem, not the engine id"""
    db = tmp_path / 'lahman.sqlite'
    make_db(db)
    lg = make_league(tmp_path / 'lg')
    table = bytearray(256)
    table[8 * 5:8 * 5 + 8] = b'clasale1'
    table[8 * 9:8 * 9 + 8] = b'clasale2'
    open(os.path.join(lg, 'TEAMID.DAT'), 'wb').write(bytes(table))
    build_season.write_real(str(db), YEAR, lg, PLACED)
    got = open(os.path.join(lg, 'REAL.DAT'), 'rb').read()
    assert got[16:24] == struct.pack('<BBHHH', 5, 0, 76, 85, 0)
    assert got[24:32] == struct.pack('<BBHHH', 9, 0, 88, 74, 0)
    assert got[32 + 22] == 9 and got[32 + 80 + 22] == 5


def test_short_name_is_padded_not_shifted(tmp_path):
    db = tmp_path / 'lahman.sqlite'
    make_db(db)
    lg = make_league(tmp_path / 'lg')
    build_season.write_real(str(db), YEAR, lg, [(b'SHORT', 974, 'aaa01', 3, 27)])
    got = open(os.path.join(lg, 'REAL.DAT'), 'rb').read()
    assert len(got) == 16 + 2 * 8 + 80
    assert got[32:52] == b'SHORT'.ljust(20, b'\0')
    assert struct.unpack_from('<H', got, 32 + 20)[0] == 974


@pytest.fixture
def steps(monkeypatch, tmp_path):
    """build_season.main with every step but write_real replaced by a recorder; returns (calls, run)"""
    calls = []
    monkeypatch.setattr(build_season, 'add_expansion', lambda out: calls.append('add_expansion'))
    monkeypatch.setattr(build_season, 'add_expansion_1998', lambda out: calls.append('exp98'))
    monkeypatch.setattr(build_season, 'rename_teams', lambda out, y: calls.append('rename'))
    monkeypatch.setattr(build_season, 'build_league',
                        lambda db, y, out, t: calls.append('build_league') or ['placed'])
    monkeypatch.setattr(build_season, 'seed_history', lambda db, y, out, pl: calls.append('seed'))
    monkeypatch.setattr(build_season.rosters, 'refresh_allstars', lambda out: calls.append('allstars'))
    monkeypatch.setattr(build_season, 'realign_lahman',
                        lambda db, y, out, t=None: calls.append('realign'))
    (tmp_path / 'db.sqlite').write_bytes(b'')
    (tmp_path / 'tmpl').mkdir()

    def run(year, real):
        monkeypatch.setattr(build_season, 'write_real', real)
        return build_season.main(['build_season.py', str(year), str(tmp_path / ('out%d' % year)),
                                  '--db', str(tmp_path / 'db.sqlite'),
                                  '--template', str(tmp_path / 'tmpl')])
    return calls, run


def test_write_real_is_the_last_step(steps):
    calls, run = steps
    seen = {}
    rc = run(1996, lambda db, y, out, placed: (seen.update(year=y, placed=placed),
                                               calls.append('write_real')))
    assert rc == 0
    assert calls == ['add_expansion', 'build_league', 'seed', 'allstars', 'realign', 'write_real']
    assert seen == {'year': 1996, 'placed': ['placed']}


def test_write_real_runs_for_a_pre_1994_year(steps):
    calls, run = steps
    assert run(1985, lambda *a: calls.append('write_real')) == 0
    assert calls == ['build_league', 'seed', 'allstars', 'write_real']


def test_write_real_failure_fails_the_build(steps, capsys):
    calls, run = steps

    def boom(*a):
        raise ValueError('no teams table')
    assert run(1996, boom) == 2
    assert 'build failed: no teams table' in capsys.readouterr().out
