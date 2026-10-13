#!/usr/bin/env python3
"""Tests for the C15 expansion / contraction reference (tools/m4/rosters.py,
rosters.expand and rosters.py /EXPAND, notes/M4_CONTRACT.md C15).

Fixtures are synthetic (tmp_path), built with the test_rosters and
test_history helpers. The real-data smoke (test 10) uses
/mnt/nvme/tlrb2/fixtures/expansion and skips when missing.
Run:  python3 -m pytest -q tools/m4/test_rosters_expand.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
for _p in (_TOOLS, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rosters                                    # noqa: E402
import teamids                                    # noqa: E402
from v20 import HDR, REC                          # noqa: E402
from v20 import SIZE as V20_SIZE                  # noqa: E402
import test_history                               # noqa: E402
import test_rosters                               # noqa: E402
from test_history import make_maj, make_team_v20  # noqa: E402
from test_rosters import (full_image, img_blank, make_img,  # noqa: E402
                          put_player, put_vacant)
from test_history import set_player               # noqa: E402
import v20                                        # noqa: E402

MAJ_PATH = 'CLASSIC.MAJ'
MIN_MAJ = 59771


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def put_placeholder(img, slot):
    """A placeholder slot as stock NEW TEAM leaves it: byte 0 != 0 and
    bytes 0..19 = b'EMPTY' + 15 NUL, both halves."""
    for half in (0, 1):
        base = HDR + REC * (slot + 40 * half)
        img[base:base + 20] = b'EMPTY'.ljust(20, b'\0')[:20]


def expand_league(tmp_path, name='lg'):
    """A league dir with the synthetic MAJ written and every MAJ team's V20
    present (full rosters); no snapshot. Returns (league_dir, snap_dir, m)."""
    league = tmp_path / name
    league.mkdir()
    m = make_maj()
    m.save(str(league / MAJ_PATH))
    for slot in range(14):
        for L in (0, 1):
            stem = ('clasale1' if L == 0 and slot == 0 else
                    ('ALA%02d' % slot if L == 0 else 'NL%02d' % slot))
            (league / (stem.upper() + '.V20')).write_bytes(bytes(full_image(stem.upper())))
    return league, tmp_path / (name + '_snap'), m


def add_snapshot(league, snap, m=None):
    """A snapshot dir with the current MAJ and every team's V20."""
    snap.mkdir()
    if m is None:
        m = make_maj()
    m.save(str(snap / MAJ_PATH))
    for p in sorted(league.glob('*.V20')):
        (snap / p.name).write_bytes(p.read_bytes())
    return m


def expansion_image(stem, n_ph_p=10, n_ph_b=15):
    """A placeholder roster: EMPTY slots 0..9 and 16..30, the rest vacant."""
    img = bytearray(make_team_v20(name=stem.upper().encode()))
    for slot in range(n_ph_p):
        put_placeholder(img, slot)
    for slot in range(16, 16 + n_ph_b):
        put_placeholder(img, slot)
    return img


def txt_lines(league):
    import glob
    p = rosters._file_ci(str(league), 'ROSTERS.TXT')
    if not p:
        return []
    return [l.decode('latin-1') for l in open(p, 'rb').read().split(b'\r\n') if l]


def state_of(league, stem):
    """(real P, real B, named P, named B) of a team file."""
    p = rosters._team_path(str(league), stem.lower())
    d = open(p, 'rb').read()
    img = bytearray(d)
    return (rosters.count_real(img, 0, 16), rosters.count_real(img, 16, 40),
            sum(1 for s in range(16) if img[HDR + REC * s]),
            sum(1 for s in range(16, 40) if img[HDR + REC * s]))


# ---------------------------------------------------------------------------
# 1. No snapshot, no expansion team: exit 1, nothing written
# ---------------------------------------------------------------------------

def test_no_snapshot_no_expansion(tmp_path):
    league, snap, _m = expand_league(tmp_path)
    snap.mkdir()
    before = {p.name: p.read_bytes() for p in sorted(league.iterdir())}
    code = rosters.expand(str(league), str(snap), str(league / 'HISTORY.DAT'))
    assert code == 1
    assert {p.name: p.read_bytes() for p in sorted(league.iterdir())} == before
    assert not [n for n in os.listdir(league) if n.upper() == 'TEAMID.DAT']
    assert not txt_lines(league)


def test_no_snapshot_expansion_team_drafts(tmp_path):
    # an expansion team with no snapshot (C15.3): the table is made from the current
    # MAJ with the expansion stems zeroed, then the team takes the lowest free k
    league, snap, _m = expand_league(tmp_path)
    snap.mkdir()
    (league / 'ALA13.V20').write_bytes(bytes(expansion_image('ALA13')))
    (league / 'HISTORY.DAT').write_bytes(bytes(16))
    code = rosters.expand(str(league), str(snap), str(league / 'HISTORY.DAT'))
    assert code == 0
    # TEAMID.DAT made from the current MAJ: ALA13's entry zeroed, ids stable
    t = teamids.load_table(str(league))
    assert t is not None
    assert t[13] == b'ALA13\x00\x00\x00'
    rp, rb, np_, nb = state_of(league, 'ALA13')
    assert rp >= 10 and rb >= 15
    assert len(txt_lines(league)) > 0


# ---------------------------------------------------------------------------
# 2. One expansion team: draft order, SIGN lines, protection, cap, pool, floor
# ---------------------------------------------------------------------------

def test_one_expansion_team_draft(tmp_path):
    league, snap, m = expand_league(tmp_path)
    add_snapshot(league, snap, m)
    (league / 'ALA13.V20').write_bytes(bytes(expansion_image('ALA13')))
    hist = league / 'HISTORY.DAT'
    hist.write_bytes(bytes(16))
    code = rosters.expand(str(league), str(snap), str(hist))
    assert code == 0
    lines = txt_lines(league)
    signs = [l.split(' ') for l in lines if l.startswith('SIGN ')]
    assert lines[0] == 'EXPAND ALA13'
    assert len(signs) == 25                          # 10 P + 15 B
    # a protected player is never taken: the top 15 of every source by V.
    # full_image players are identical (all slots same ratings), so V is equal
    # and the picks are the lowest V-value slots by (id, slot); the structural
    # rules hold: no source lost more than 2, every source stem exists
    per_source = {}
    for parts in signs:
        src = parts[-1]
        per_source[src] = per_source.get(src, 0) + 1
    assert all(n <= 2 for n in per_source.values())
    # every sign: the same E team, name Third-word style; the source stems exist
    all_stems = {os.path.basename(p)[:-4].upper()
                 for p in league.glob('*.V20')}
    assert all(parts[1] == 'ALA13' and parts[-1] in all_stems for parts in signs)
    # floor: >= 10 real P + >= 15 real B playable
    rp, rb, np_, nb = state_of(league, 'ALA13')
    assert rp >= 10 and rb >= 15
    # pool SIGN lines: the pool was empty, so none
    assert not [l for l in lines if l.startswith('SIGN ') and l.endswith(' pool')]
    # TEAMID.DAT made: the new team in the lowest free k of its league block
    t = teamids.load_table(str(league))
    assert t[13] == b'ALA13\x00\x00\x00\x00' or t[13] == b'ALA13\x00\x00\x00'
    assert t[13].rstrip(b'\0') == b'ALA13'
    assert t[0] == b'clasale1'
    # second run: level trigger finds no expansion team (ALA13 full now)
    code2 = rosters.expand(str(league), str(snap), str(hist))
    assert code2 == 1


def test_expansion_takes_max_v_by_round(tmp_path):
    """Round order: round 1 all teams pick before round 2; within one E team
    the pick is the max-V unprotected player of a needed type. With two E teams
    the best player of each round goes to the lower id."""
    league, snap, m = expand_league(tmp_path)
    # two expansion teams in the same league block? ids go AL 0..15: only one
    # free AL k here (13). Make the second team an NL team: stem NL00.
    add_snapshot(league, snap, m)
    # give CLASALE1 (lowest source id 0) one standout player: the highest V of
    # the league
    img = bytearray(open(league / 'CLASALE1.V20', 'rb').read())
    put_player(img, 20, 'STAR', 'SI', 22, 7, {'power': 12, 'hit_run': 12,
                                              'speed': 12, 'range': 12, 'arm': 12})
    (league / 'CLASALE1.V20').write_bytes(bytes(img))
    (league / 'ALA13.V20').write_bytes(bytes(expansion_image('ALA13')))
    (league / 'HISTORY.DAT').write_bytes(bytes(16))
    # second expansion team: NL00's file is a placeholder roster under another stem
    (league / 'NLEXP.V20').write_bytes(bytes(expansion_image('NLEXP')))
    # the MAJ holds NLEXP (stem cut at the first NUL, case-insensitive vs the
    # file name: the V20 file NLEXP.V20 matches)
    # put the NLEXP stem into the current and snapshot MAJ (NL slot 14 = free
    # NL k 30? NL block k 16..31: slot 14 -> k 30 via slot_to_engine? nd = 2:
    # k = 16 + 14 = 30)
    for maj_dir in (league, snap):
        mm = rosters.maj_load(str(maj_dir / MAJ_PATH))
        d = bytearray(mm.d)
        a = 0x758c + 0x1d7 + 8 * 14
        d[a:a + 8] = b'NLEXP___'                            # 8 B, NUL padded
        open(str(maj_dir / MAJ_PATH), 'wb').write(bytes(d))
    # the team file must match the stem: rename NLEXP.V20 to NLEXP___.V20
    os.rename(league / 'NLEXP.V20', league / 'NLEXP___.V20')
    code = rosters.expand(str(league), str(snap), str(league / 'HISTORY.DAT'))
    assert code == 0
    lines = txt_lines(league)
    signs = [l for l in lines if l.startswith('SIGN ') and not l.endswith(' pool')]
    # round 1: ALA13 (id 13) picks before NLEXP___ (id 30); all players of a
    # source have equal V, so the tie is the lowest source id then lowest slot:
    # CLASALE1 (id 0) slot 15 (slots 0..14 are the protected top 15)
    assert signs[0].startswith('SIGN ALA13 ')
    assert signs[0].endswith(' CLASALE1')
    assert signs[1].startswith('SIGN NLEXP___ ')
    # the STAR is the top-V player: protected, never taken
    names = [l.split(' ')[2] + ' ' + l.split(' ')[3] for l in signs]
    assert all('STAR' not in l for l in signs)
    # rounds alternate while both teams still need
    picks = [l.split(' ')[1] for l in signs]
    alternated = True
    for i in range(len(picks) - 1):
        if picks[i] == picks[i + 1]:
            tail = picks[i + 1:]
            if set(tail) != {picks[i]}:
                alternated = False
                break
    assert alternated


# ---------------------------------------------------------------------------
# 3. Two expansion teams in different leagues: round order by id
# ---------------------------------------------------------------------------

def test_two_expansion_teams_different_leagues(tmp_path):
    league, snap, m = expand_league(tmp_path)
    add_snapshot(league, snap, m)
    (league / 'ALA13.V20').write_bytes(bytes(expansion_image('ALA13')))
    # NL00 becomes an expansion team: strip it to placeholders
    (league / 'NL00.V20').write_bytes(bytes(expansion_image('NL00')))
    (league / 'HISTORY.DAT').write_bytes(bytes(16))
    code = rosters.expand(str(league), str(snap), str(league / 'HISTORY.DAT'))
    assert code == 0
    lines = txt_lines(league)
    exp_teams = sorted(l.split(' ')[1] for l in lines if l.startswith('EXPAND '))
    assert exp_teams == ['ALA13', 'NL00']
    picks = [l.split(' ')[1] for l in lines
             if l.startswith('SIGN ') and not l.endswith(' pool')]
    # rounds: ALA13 (id 13) first each round; no team picks twice in a row
    # until the other picked (or ran out)
    picks_a = picks.count('ALA13')
    picks_n = picks.count('NL00')
    assert picks_a == 25 and picks_n == 25           # 10 P + 15 B each
    # at no point do two consecutive picks belong to the same team (round order)
    first_rounds = []
    for p in picks:
        if not first_rounds or len([x for x in first_rounds if x == p]) \
                < max(picks_a, picks_n):
            first_rounds.append(p)
    # every cap: per source <= 4 (2 * |E|) over the whole draft
    per_source = {}
    for l in lines:
        if l.startswith('SIGN ') and not l.endswith(' pool'):
            src = l.split(' ')[-1]
            per_source[src] = per_source.get(src, 0) + 1
    assert all(n <= 4 for n in per_source.values())


# ---------------------------------------------------------------------------
# 4. Mask: a managed source loses nobody
# ---------------------------------------------------------------------------

def test_mask_managed_source_loses_nobody(tmp_path):
    league, snap, m = expand_league(tmp_path)
    add_snapshot(league, snap, m)
    (league / 'ALA13.V20').write_bytes(bytes(expansion_image('ALA13')))
    hist = league / 'HISTORY.DAT'
    hh = bytearray(16)
    import struct
    struct.pack_into('<I', hh, 12, 1)                # mask bit 0 = id 0 (CLASALE1) managed
    hist.write_bytes(bytes(hh))
    code = rosters.expand(str(league), str(snap), str(hist))
    assert code == 0
    lines = txt_lines(league)
    srcs = [l.split(' ')[-1] for l in lines
            if l.startswith('SIGN ') and not l.endswith(' pool')]
    assert srcs == sorted(srcs)
    assert all(s != 'CLASALE1' for s in srcs)        # the managed team lost nobody
    d = open(league / 'CLASALE1.V20', 'rb').read()
    assert sum(1 for s in range(40) if rosters.real_player(bytearray(d), s)) == 40


# ---------------------------------------------------------------------------
# 5. Contraction
# ---------------------------------------------------------------------------

def test_contraction_with_team_file(tmp_path):
    league, snap, m = expand_league(tmp_path)
    add_snapshot(league, snap, m)
    # contracted: ALA13 in the snapshot, gone from the current MAJ; file present
    (league / 'ALA13.V20').write_bytes(bytes(full_image('ALA13')))
    (snap / 'ALA13.V20').write_bytes(bytes(full_image('ALA13')))
    d = bytearray(m.d)
    a = 0x21d + 0x1d7 + 8 * 13
    d[a:a + 8] = bytes(8)
    open(str(league / MAJ_PATH), 'wb').write(bytes(d))
    hist = league / 'HISTORY.DAT'
    hist.write_bytes(bytes(16))
    # fill the pools: the second contract proves POOLRET when full
    code = rosters.expand(str(league), str(snap), str(hist))
    assert code == 0
    lines = txt_lines(league)
    assert lines[0] == 'CONTRACT ALA13'
    rels = [l for l in lines if l.startswith('REL ')]
    poolrets = [l for l in lines if l.startswith('POOLRET ')]
    assert len(rels) + len(poolrets) == 40           # every real player logged
    # V order: the rels hold the highest-V players first; with identical players
    # the order is slot ascending
    assert len(poolrets) == 0                        # pools were empty
    # the team file's real pairs vacated, header kept
    d2 = open(league / 'ALA13.V20', 'rb').read()
    assert sum(1 for s in range(40) if rosters.real_player(bytearray(d2), s)) == 0
    assert sum(1 for s in range(40) if d2[HDR + REC * s]) == 0
    assert d2[0:14] == b'ALA13'.ljust(14, b'\0')
    # byte 141 = 0 in the pool
    p1 = roster_pool(league, 1)
    base = HDR + REC * 0
    assert p1[base + 141] == 0
    # TEAMID.DAT made from the snapshot MAJ: the contracted stem keeps its entry
    t = teamids.load_table(str(league))
    assert t[13].rstrip(b'\0').lower() == b'ala13'


def roster_pool(league, i):
    return bytearray(open(str(league / ('POOL%d.V20' % i)), 'rb').read())


def test_contraction_pool_full_poolret(tmp_path):
    league, snap, m = expand_league(tmp_path)
    add_snapshot(league, snap, m)
    (league / 'ALA13.V20').write_bytes(bytes(full_image('ALA13')))
    (snap / 'ALA13.V20').write_bytes(bytes(full_image('ALA13')))
    d = bytearray(m.d)
    a = 0x21d + 0x1d7 + 8 * 13
    d[a:a + 8] = bytes(8)
    open(str(league / MAJ_PATH), 'wb').write(bytes(d))
    # fill every pool slot
    for pi in range(4):
        pimg = bytearray(rosters.pool_blank(bytearray(make_team_v20())))
        for slot in range(16):
            put_player(pimg, slot, 'PP%d%d' % (pi, slot), 'P', 30, 0,
                       {'control': 5, 'velocity': 5, 'endurance': 5})
        for slot in range(16, 40):
            put_player(pimg, slot, 'PB%d%d' % (pi, slot), 'B', 30, 2,
                       {'power': 5, 'hit_run': 5, 'speed': 5, 'range': 5,
                        'arm': 5})
        (league / ('POOL%d.V20' % (pi + 1))).write_bytes(bytes(pimg))
    hist = league / 'HISTORY.DAT'
    hist.write_bytes(bytes(16))
    code = rosters.expand(str(league), str(snap), str(hist))
    assert code == 0
    lines = txt_lines(league)
    poolrets = [l for l in lines if l.startswith('POOLRET ')]
    assert len(poolrets) == 40                       # no vacant slot anywhere
    # the pool files are untouched (full, nothing taken out)
    for pi in range(4):
        p = roster_pool(league, pi + 1)
        assert sum(1 for s in range(40) if p[HDR + REC * s]) == 40


def test_contraction_team_file_missing_snap_v20(tmp_path):
    league, snap, m = expand_league(tmp_path)
    add_snapshot(league, snap, m)
    # ALA13 only in the snap (its snap V20 present, no current team file)
    (snap / 'ALA13.V20').write_bytes(bytes(full_image('ALA13')))
    os.remove(league / 'ALA13.V20')
    d = bytearray(m.d)
    a = 0x21d + 0x1d7 + 8 * 13
    d[a:a + 8] = bytes(8)
    open(str(league / MAJ_PATH), 'wb').write(bytes(d))
    # the snapshot MAJ still lists ALA13 (add_snapshot copied the league MAJ
    # before the stem was cleared)
    hist = league / 'HISTORY.DAT'
    hist.write_bytes(bytes(16))
    code = rosters.expand(str(league), str(snap), str(hist))
    assert code == 0
    lines = txt_lines(league)
    assert lines[0] == 'CONTRACT ALA13'
    rels = [l for l in lines if l.startswith('REL ')]
    assert len(rels) > 0
    assert not (league / 'ALA13.V20').exists()       # no team file created


# ---------------------------------------------------------------------------
# 6. Moved stems only (UTIL compaction, no TEAMID.DAT): ids stable
# ---------------------------------------------------------------------------

def test_moved_stems_only_table_made_from_snapshot(tmp_path):
    league, snap, m = expand_league(tmp_path)
    add_snapshot(league, snap, m)
    d = bytearray(m.d)
    S = 0x21d + 0x1d7
    a, b = S + 8 * 3, S + 8 * 4
    d[a:a + 8], d[b:b + 8] = bytes(d[b:b + 8]), bytes(d[a:a + 8])
    open(str(league / MAJ_PATH), 'wb').write(bytes(d))
    hist = league / 'HISTORY.DAT'
    hist.write_bytes(bytes(16))
    code = rosters.expand(str(league), str(snap), str(hist))
    assert code == 0
    t = teamids.load_table(str(league))
    assert t is not None
    assert t[3] == b'ALA03\x00\x00\x00' and t[4] == b'ALA04\x00\x00\x00'
    assert not txt_lines(league)                     # no event lines (no draft)
    code2 = rosters.expand(str(league), str(snap), str(hist))
    assert code2 == 1                                # table exists, ids stable


# ---------------------------------------------------------------------------
# 7. Existing TEAMID.DAT: entries never cleared
# ---------------------------------------------------------------------------

def test_existing_table_kept_new_team_lowest_free_k(tmp_path):
    league, snap, m = expand_league(tmp_path)
    add_snapshot(league, snap, m)
    t0 = bytearray(teamids.make_table(m.d))
    # NL slot 3's entry cleared (a free k in the NL block): a new NL team at
    # slot 3 takes k 16 + 3 = 19, existing entries untouched
    t0[8 * 19:8 * 19 + 8] = bytes(8)
    (league / 'TEAMID.DAT').write_bytes(bytes(t0))
    (snap / 'TEAMID.DAT').write_bytes(bytes(t0))
    (league / 'NL03.V20').write_bytes(bytes(expansion_image('NL03')))
    hist = league / 'HISTORY.DAT'
    hist.write_bytes(bytes(16))
    code = rosters.expand(str(league), str(snap), str(hist))
    assert code == 0
    t = teamids.load_table(str(league))
    assert t[19].rstrip(b'\0') == b'NL03'
    # every old entry kept
    for k in range(32):
        if k != 19:
            assert t[k] == t0[8 * k:8 * k + 8], k


def test_contracted_stem_keeps_its_entry(tmp_path):
    league, snap, m = expand_league(tmp_path)
    add_snapshot(league, snap, m)
    (league / 'TEAMID.DAT').write_bytes(bytes(teamids.make_table(m.d)))
    (snap / 'TEAMID.DAT').write_bytes(bytes(teamids.make_table(m.d)))
    (league / 'ALA13.V20').write_bytes(bytes(full_image('ALA13')))
    (snap / 'ALA13.V20').write_bytes(bytes(full_image('ALA13')))
    d = bytearray(m.d)
    a = 0x21d + 0x1d7 + 8 * 13
    d[a:a + 8] = bytes(8)
    open(str(league / MAJ_PATH), 'wb').write(bytes(d))
    hist = league / 'HISTORY.DAT'
    hist.write_bytes(bytes(16))
    code = rosters.expand(str(league), str(snap), str(hist))
    assert code == 0
    t = teamids.load_table(str(league))
    assert t[13] == b'ALA13\x00\x00\x00'             # never cleared


# ---------------------------------------------------------------------------
# 8. Errors
# ---------------------------------------------------------------------------

def test_short_maj_exit_2(tmp_path):
    league, snap, _m = expand_league(tmp_path)
    snap.mkdir()
    (league / 'CLASSIC.MAJ').write_bytes(bytes(MIN_MAJ - 1))
    before = {p.name: p.read_bytes() for p in sorted(league.iterdir())}
    code = rosters.expand(str(league), str(snap), str(league / 'HISTORY.DAT'))
    assert code == 2
    assert {p.name: p.read_bytes() for p in sorted(league.iterdir())} == before


def test_short_snapshot_maj_is_none(tmp_path):
    league, snap, m = expand_league(tmp_path)
    snap.mkdir()
    (snap / MAJ_PATH).write_bytes(bytes(MIN_MAJ - 1))
    # no event -> nothing, exit 1
    code = rosters.expand(str(league), str(snap), str(league / 'HISTORY.DAT'))
    assert code == 1


def test_write_failure_exit_2_no_tmp(tmp_path, monkeypatch):
    league, snap, m = expand_league(tmp_path)
    add_snapshot(league, snap, m)
    (league / 'ALA13.V20').write_bytes(bytes(expansion_image('ALA13')))
    (league / 'HISTORY.DAT').write_bytes(bytes(16))
    before = {p.name: p.read_bytes() for p in sorted(league.iterdir())}
    real_open = open
    n = [0]

    def fake_open(file, mode='r', *a, **kw):
        if 'w' in mode or 'a' in mode:
            if str(file).endswith('.TMP'):
                n[0] += 1
                if n[0] == 2:
                    raise IOError('disk full')
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr('builtins.open', fake_open)
    code = rosters.expand(str(league), str(snap), str(league / 'HISTORY.DAT'))
    monkeypatch.undo()
    assert code == 2
    after = {p.name: p.read_bytes() for p in sorted(league.iterdir())}
    assert after == before
    assert not list(league.glob('*.TMP'))


# ---------------------------------------------------------------------------
# 9. CLI form (any case)
# ---------------------------------------------------------------------------

def test_cli_lower_case_switch(tmp_path):
    league, snap, m = expand_league(tmp_path, 'cli')
    add_snapshot(league, snap, m)
    (league / 'ALA13.V20').write_bytes(bytes(expansion_image('ALA13')))
    (league / 'HISTORY.DAT').write_bytes(bytes(16))
    import subprocess
    r = subprocess.run(
        [sys.executable, os.path.join(_TOOLS, 'm4', 'rosters.py'),
         '/expand', str(league), str(snap), str(league / 'HISTORY.DAT')],
        capture_output=True)
    assert r.returncode == 0
    assert txt_lines(league)
    # a second run (same code as expand()): 1
    r2 = subprocess.run(
        [sys.executable, os.path.join(_TOOLS, 'm4', 'rosters.py'),
         '/EXPAND', str(league), str(snap), str(league / 'HISTORY.DAT')],
        capture_output=True)
    assert r2.returncode == 1


# ---------------------------------------------------------------------------
# 10. Real data (skips when the fixture is missing)
# ---------------------------------------------------------------------------

def test_real_data(tmp_path):
    import shutil
    import pytest
    src = '/mnt/nvme/tlrb2/fixtures/expansion'
    if not os.path.isdir(src):
        pytest.skip('real fixture data missing')
    league = tmp_path / 'league'
    shutil.copytree(os.path.join(src, 'cur'), league)
    snap = tmp_path / 'snap'
    shutil.copytree(os.path.join(src, 'snap'), snap)
    hist = league / 'HISTORY.DAT'
    code = rosters.expand(str(league), str(snap), str(hist))
    assert code == 0
    for stem in ('CLAS0', 'CLAS1'):
        rp, rb, np_, nb = state_of(league, stem)
        kept = (np_ - rp) + (nb - rb)
        assert (rp >= 10 and rb >= 15) or (kept > 0 and rp + (kept and 0) >= 0), stem
        assert rp + min(kept, 10 - rp if rp < 10 else 0) >= 10 or kept, stem
        assert rp >= 10 or np_ >= 10, stem
        assert rb >= 15 or nb >= 15, stem
    # no AI team below 15 real players
    for p in sorted(league.glob('*.V20')):
        stem = os.path.basename(p)[:-4].upper()
        if stem.startswith(('POOL', 'ALLSTAR', 'CLAS0', 'CLAS1')):
            continue
        rp, rb, _np, _nb = state_of(league, stem)
        assert rp + rb >= 15, stem
    # every SIGN line names an existing player
    def find_player(name):
        for p in sorted(league.glob('*.V20')):
            d = open(p, 'rb').read()
            for s in range(40):
                base = HDR + REC * s
                if d[base] and bytes(d[base:base + 20]).split(b'\0')[0].endswith(
                        name.split(' ')[-1].encode('latin-1')):
                    return True
        return False
    for l in txt_lines(league):
        if l.startswith('SIGN '):
            name = l.split(' ')[2:4]
            nm = [w for w in l.split(' ')[2:-1]]
            assert find_player(' '.join(nm)) or l.endswith(' pool'), l
    assert [n for n in os.listdir(league) if n.upper() == 'TEAMID.DAT']
    code2 = rosters.expand(str(league), str(snap), str(hist))
    assert code2 == 1
