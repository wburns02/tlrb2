#!/usr/bin/env python3
"""Parity tests: the C15 /EXPAND port (rosters_c/rosters.c do_expand) against
the Python reference (rosters.expand). Every check runs the reference on one
copy of a fixture and the host on a second identical copy, then compares the
exit codes and every file of the league dir (case-sensitive names, exact
bytes) and the untouched snapshot dir. No .TMP is ever left.

Run:  python3 -m pytest -q tools/m4/test_rosters_expand_c.py
The host binary tools/m4/rosters_c/rosters_host must exist (build_rosters.py
builds it); every test skips when it is missing. The real-data test skips
when /mnt/nvme/tlrb2/fixtures/expansion is missing.
"""
import os
import random
import shutil
import struct
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
for _p in (_TOOLS, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from m4 import rosters as rosters_py                     # noqa: E402
import test_rosters_expand as te                         # noqa: E402
from test_rosters import full_image, put_player          # noqa: E402
from test_history import make_team_v20                   # noqa: E402

HOST = os.path.join(_HERE, 'rosters_c', 'rosters_host')
REAL = '/mnt/nvme/tlrb2/fixtures/expansion'

RATINGS_P = ('control', 'velocity', 'endurance')
RATINGS_B = ('power', 'hit_run', 'speed', 'range', 'arm')


def need_host():
    if not os.path.exists(HOST):
        pytest.skip('rosters_host missing')


# ---------------------------------------------------------------------------
# Parity runner
# ---------------------------------------------------------------------------

def compare_dirs(da_dir, db_dir):
    """Every file of the two dirs, case-sensitive names, exact bytes."""
    da = {p.name: p.read_bytes()
          for p in sorted(da_dir.iterdir()) if p.is_file()}
    db = {p.name: p.read_bytes()
          for p in sorted(db_dir.iterdir()) if p.is_file()}
    assert sorted(da) == sorted(db), (sorted(da), sorted(db))
    for n in sorted(da):
        assert da[n] == db[n], n
    assert not [n for n in da if n.upper().endswith('.TMP')], sorted(da)


def compare(base_a, base_b):
    """The league and snap dirs of both copies."""
    compare_dirs(base_a / 'league', base_b / 'league')
    compare_dirs(base_a / 'snap', base_b / 'snap')


def run_pair(fx, base, switch='/EXPAND'):
    """Copy the fixture twice; rosters.expand on copy a, the host on copy b.
    Returns (rc_python, rc_host)."""
    la, lb = base / 'a', base / 'b'
    shutil.copytree(fx, la)
    shutil.copytree(fx, lb)
    rc_p = rosters_py.expand(str(la / 'league'), str(la / 'snap'),
                             str(la / 'league' / 'HISTORY.DAT'))
    rc_c = subprocess.run(
        [HOST, switch, str(lb / 'league'), str(lb / 'snap'),
         str(lb / 'league' / 'HISTORY.DAT')], capture_output=True).returncode
    return rc_p, rc_c


def parity(tmp_path, builder, switch='/EXPAND', expect=None):
    need_host()
    fx = tmp_path / 'fx'
    fx.mkdir()
    builder(fx)
    rc_p, rc_c = run_pair(fx, tmp_path, switch)
    assert rc_p == rc_c, (rc_p, rc_c)
    if expect is not None:
        assert rc_p == expect, rc_p
    compare(tmp_path / 'a', tmp_path / 'b')
    return rc_p


# ---------------------------------------------------------------------------
# Fixture builders (every one lays out league/ and snap/ under its base)
# ---------------------------------------------------------------------------

def b_no_event(base):
    """No expansion, no contraction, no moved stem: exit 1, nothing written."""
    lg, snap, _m = te.expand_league(base, 'league')
    (base / 'snap').mkdir()


def b_one_expansion(base):
    """One expansion team, no snapshot MAJ (C15.3 ids from the current MAJ)."""
    lg, snap, _m = te.expand_league(base, 'league')
    (base / 'snap').mkdir()
    (lg / 'ALA13.V20').write_bytes(bytes(te.expansion_image('ALA13')))
    (lg / 'HISTORY.DAT').write_bytes(bytes(16))


def b_one_expansion_full(base):
    """One expansion team with a snapshot: the draft, SIGN lines, floor."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    (lg / 'ALA13.V20').write_bytes(bytes(te.expansion_image('ALA13')))
    (lg / 'HISTORY.DAT').write_bytes(bytes(16))
    os.rename(snap, base / 'snap')


def b_two_expansion_leagues(base):
    """Two expansion teams in different leagues (ALA13 + NL00)."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    (lg / 'ALA13.V20').write_bytes(bytes(te.expansion_image('ALA13')))
    (lg / 'NL00.V20').write_bytes(bytes(te.expansion_image('NL00')))
    (lg / 'HISTORY.DAT').write_bytes(bytes(16))
    os.rename(snap, base / 'snap')


def b_max_v_two_teams(base):
    """Two expansion teams, one standout star (V order and round alternation)."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    img = bytearray((lg / 'CLASALE1.V20').read_bytes())
    put_player(img, 20, 'STAR', 'SI', 22, 7, {'power': 12, 'hit_run': 12,
                                              'speed': 12, 'range': 12,
                                              'arm': 12})
    (lg / 'CLASALE1.V20').write_bytes(bytes(img))
    (lg / 'ALA13.V20').write_bytes(bytes(te.expansion_image('ALA13')))
    (lg / 'NLEXP.V20').write_bytes(bytes(te.expansion_image('NLEXP')))
    for maj_dir in (lg, snap):
        d = bytearray((maj_dir / te.MAJ_PATH).read_bytes())
        a = 0x758c + 0x1d7 + 8 * 14
        d[a:a + 8] = b'NLEXP___'
        (maj_dir / te.MAJ_PATH).write_bytes(bytes(d))
    os.rename(lg / 'NLEXP.V20', lg / 'NLEXP___.V20')
    (lg / 'HISTORY.DAT').write_bytes(bytes(16))
    os.rename(snap, base / 'snap')


def b_mask_managed(base):
    """Mask bit 0: CLASALE1 (id 0) managed, loses nobody."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    (lg / 'ALA13.V20').write_bytes(bytes(te.expansion_image('ALA13')))
    hh = bytearray(16)
    struct.pack_into('<I', hh, 12, 1)
    (lg / 'HISTORY.DAT').write_bytes(bytes(hh))
    os.rename(snap, base / 'snap')


def b_pool_all_managed(base):
    """All sources managed: the draft takes nobody, the pool signs."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    (lg / 'ALA13.V20').write_bytes(bytes(te.expansion_image('ALA13')))
    hh = bytearray(16)
    struct.pack_into('<I', hh, 12, 0xffffffff)
    (lg / 'HISTORY.DAT').write_bytes(bytes(hh))
    for pi in range(4):
        pimg = bytearray(rosters_py.pool_blank(bytearray(make_team_v20())))
        if pi >= 2:
            continue                       # POOL3 / POOL4 missing
        for slot in range(6):
            put_player(pimg, slot, 'PP%d%d' % (pi, slot), 'P', 24 + pi, 0,
                       {'control': 3 + slot, 'velocity': 4,
                        'endurance': 2 + (slot % 5)})
        for slot in range(20, 30):
            put_player(pimg, slot, 'PB%d%d' % (pi, slot), 'B', 22 + (slot % 9),
                       1 + (slot % 8),
                       {'power': 2 + (slot % 10), 'hit_run': 6,
                        'speed': 3, 'range': 4, 'arm': 5})
        (lg / ('POOL%d.V20' % (pi + 1))).write_bytes(bytes(pimg))
    os.rename(snap, base / 'snap')


def _contract(lg, snap, stem, slot, drop_file):
    """Contracted stem: gone from the current MAJ, kept in the snapshot."""
    d = bytearray((lg / te.MAJ_PATH).read_bytes())
    a = 0x21d + 0x1d7 + 8 * slot
    d[a:a + 8] = bytes(8)
    (lg / te.MAJ_PATH).write_bytes(bytes(d))
    (lg / (stem.upper() + '.V20')).write_bytes(bytes(full_image(stem.upper())))
    (snap / (stem.upper() + '.V20')).write_bytes(bytes(full_image(stem.upper())))
    if drop_file:
        os.remove(lg / (stem.upper() + '.V20'))


def b_contract_file(base):
    """Contraction, the team file present."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    _contract(lg, snap, 'ALA13', 13, False)
    (lg / 'HISTORY.DAT').write_bytes(bytes(16))
    os.rename(snap, base / 'snap')


def b_contract_snap_only(base):
    """Contraction, only the snap V20 (no current team file)."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    _contract(lg, snap, 'ALA13', 13, True)
    (lg / 'HISTORY.DAT').write_bytes(bytes(16))
    os.rename(snap, base / 'snap')


def b_contract_pool_full(base):
    """Contraction into full pools: every real player POOLRET."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    for pi in range(4):
        pimg = bytearray(rosters_py.pool_blank(bytearray(make_team_v20())))
        for slot in range(16):
            put_player(pimg, slot, 'PP%d%d' % (pi, slot), 'P', 30, 0,
                       {'control': 5, 'velocity': 5, 'endurance': 5})
        for slot in range(16, 40):
            put_player(pimg, slot, 'PB%d%d' % (pi, slot), 'B', 30, 2,
                       {'power': 5, 'hit_run': 5, 'speed': 5, 'range': 5,
                        'arm': 5})
        (lg / ('POOL%d.V20' % (pi + 1))).write_bytes(bytes(pimg))
    _contract(lg, snap, 'ALA13', 13, False)
    (lg / 'HISTORY.DAT').write_bytes(bytes(16))
    os.rename(snap, base / 'snap')


def b_moved_only(base):
    """Moved stems only (UTIL compaction), no TEAMID.DAT: the table is made."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    d = bytearray((lg / te.MAJ_PATH).read_bytes())
    s = 0x21d + 0x1d7
    a, b2 = s + 8 * 3, s + 8 * 4
    d[a:a + 8], d[b2:b2 + 8] = bytes(d[b2:b2 + 8]), bytes(d[a:a + 8])
    (lg / te.MAJ_PATH).write_bytes(bytes(d))
    (lg / 'HISTORY.DAT').write_bytes(bytes(16))
    os.rename(snap, base / 'snap')


def b_existing_table(base):
    """An existing 256 B TEAMID.DAT: entries never cleared, lowest free k."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    import teamids
    tab = bytearray(teamids.make_table(m.d))
    tab[8 * 19:8 * 19 + 8] = bytes(8)      # NL slot 3's entry cleared
    (lg / 'TEAMID.DAT').write_bytes(bytes(tab))
    (snap / 'TEAMID.DAT').write_bytes(bytes(tab))
    (lg / 'NL03.V20').write_bytes(bytes(te.expansion_image('NL03')))
    (lg / 'HISTORY.DAT').write_bytes(bytes(16))
    os.rename(snap, base / 'snap')


def b_existing_txt(base):
    """An existing ROSTERS.TXT: the new lines are appended."""
    lg, snap, m = te.expand_league(base, 'league')
    te.add_snapshot(lg, snap, m)
    (lg / 'ALA13.V20').write_bytes(bytes(te.expansion_image('ALA13')))
    (lg / 'HISTORY.DAT').write_bytes(bytes(16))
    (lg / 'ROSTERS.TXT').write_bytes(b'OLD LINE\r\n')
    os.rename(snap, base / 'snap')


def b_short_maj(base):
    """The current MAJ cut to 59770 B: exit 2, nothing changed."""
    lg, snap, _m = te.expand_league(base, 'league')
    (base / 'snap').mkdir()
    (lg / te.MAJ_PATH).write_bytes(bytes(te.MIN_MAJ - 1))


# ---------------------------------------------------------------------------
# 1. One parity test per scenario
# ---------------------------------------------------------------------------

def test_no_event(tmp_path):
    parity(tmp_path, b_no_event, expect=1)


def test_one_expansion(tmp_path):
    parity(tmp_path, b_one_expansion, expect=0)


def test_one_expansion_full(tmp_path):
    parity(tmp_path, b_one_expansion_full, expect=0)


def test_two_expansion_leagues(tmp_path):
    parity(tmp_path, b_two_expansion_leagues, expect=0)


def test_max_v_two_teams(tmp_path):
    parity(tmp_path, b_max_v_two_teams, expect=0)


def test_mask_managed(tmp_path):
    parity(tmp_path, b_mask_managed, expect=0)


def test_pool_all_managed(tmp_path):
    parity(tmp_path, b_pool_all_managed, expect=0)


def test_contract_file(tmp_path):
    parity(tmp_path, b_contract_file, expect=0)


def test_contract_snap_only(tmp_path):
    parity(tmp_path, b_contract_snap_only, expect=0)


def test_contract_pool_full(tmp_path):
    parity(tmp_path, b_contract_pool_full, expect=0)


def test_moved_only(tmp_path):
    parity(tmp_path, b_moved_only, expect=0)


def test_existing_table(tmp_path):
    parity(tmp_path, b_existing_table, expect=0)


def test_existing_txt(tmp_path):
    parity(tmp_path, b_existing_txt, expect=0)


def test_short_maj(tmp_path):
    parity(tmp_path, b_short_maj, expect=2)


# ---------------------------------------------------------------------------
# 2. A second run on the result: exit 1 for both, dirs still equal
# ---------------------------------------------------------------------------

def test_second_run(tmp_path):
    need_host()
    fx = tmp_path / 'fx'
    fx.mkdir()
    b_one_expansion_full(fx)
    rc_p, rc_c = run_pair(fx, tmp_path)
    assert rc_p == rc_c == 0
    compare(tmp_path / 'a', tmp_path / 'b')
    # second round on the results
    rc_p2 = rosters_py.expand(str(tmp_path / 'a' / 'league'),
                              str(tmp_path / 'a' / 'snap'),
                              str(tmp_path / 'a' / 'league' / 'HISTORY.DAT'))
    rc_c2 = subprocess.run(
        [HOST, '/EXPAND', str(tmp_path / 'b' / 'league'),
         str(tmp_path / 'b' / 'snap'),
         str(tmp_path / 'b' / 'league' / 'HISTORY.DAT')],
        capture_output=True).returncode
    assert rc_p2 == rc_c2 == 1, (rc_p2, rc_c2)
    compare(tmp_path / 'a', tmp_path / 'b')


# ---------------------------------------------------------------------------
# 3. Switch case: /expand and /EXPAND
# ---------------------------------------------------------------------------

def test_switch_case(tmp_path):
    """'/expand' and '/EXPAND' on two copies: same rc, same bytes, and both
    equal to the reference."""
    need_host()
    for builder in (b_one_expansion_full, b_two_expansion_leagues):
        base = tmp_path / ('r%d' % len(list(tmp_path.iterdir())))
        base.mkdir()
        fx = base / 'fx'
        fx.mkdir()
        builder(fx)
        rc_p, rc_lo = run_pair(fx, base, switch='/expand')
        assert rc_p == rc_lo == 0, (rc_p, rc_lo)
        compare(base / 'a', base / 'b')
        lu = base / 'u'
        shutil.copytree(fx, lu)
        rc_up = subprocess.run(
            [HOST, '/EXPAND', str(lu / 'league'), str(lu / 'snap'),
             str(lu / 'league' / 'HISTORY.DAT')],
            capture_output=True).returncode
        assert rc_up == rc_lo, (rc_up, rc_lo)
        compare(base / 'b', lu)


# ---------------------------------------------------------------------------
# 4. No-path form (cwd install, C16.1 layout)
# ---------------------------------------------------------------------------

def no_path_run(tmp_path, builder):
    """The C16.1 install: TEAMS/CLASSIC = the league dir, C:/DYNSNAP = the
    snapshot dir. The host runs with only /EXPAND from the install cwd; the
    reference runs on the equivalent explicit paths."""
    need_host()
    fx = tmp_path / 'fx'
    fx.mkdir()
    builder(fx)
    ref = tmp_path / 'ref'
    inst = tmp_path / 'inst'
    shutil.copytree(fx, ref)
    shutil.copytree(fx, inst)
    (inst / 'TEAMS').mkdir()
    (inst / 'C').mkdir()
    shutil.move(str(inst / 'league'), str(inst / 'TEAMS' / 'CLASSIC'))
    shutil.move(str(inst / 'snap'), str(inst / 'C' / 'DYNSNAP'))
    rc_c = subprocess.run([HOST, '/EXPAND'], cwd=str(inst),
                          capture_output=True).returncode
    rc_p = rosters_py.expand(str(ref / 'league'), str(ref / 'snap'),
                             str(ref / 'league' / 'HISTORY.DAT'))
    assert rc_p == rc_c, (rc_p, rc_c)
    compare_dirs(ref / 'league', inst / 'TEAMS' / 'CLASSIC')
    compare_dirs(ref / 'snap', inst / 'C' / 'DYNSNAP')


def test_no_path_form(tmp_path):
    no_path_run(tmp_path, b_pool_all_managed)


def test_no_path_classic_full(tmp_path):
    no_path_run(tmp_path, b_one_expansion_full)


# ---------------------------------------------------------------------------
# 5. Real data (skips when the fixture is missing)
# ---------------------------------------------------------------------------

def test_real_data(tmp_path):
    if not os.path.isdir(os.path.join(REAL, 'cur')):
        pytest.skip('real fixture data missing')
    need_host()
    fx = tmp_path / 'fx'
    fx.mkdir()
    shutil.copytree(os.path.join(REAL, 'cur'), fx / 'league')
    shutil.copytree(os.path.join(REAL, 'snap'), fx / 'snap')
    la, lb = tmp_path / 'a', tmp_path / 'b'
    shutil.copytree(fx, la)
    shutil.copytree(fx, lb)
    rc_p = rosters_py.expand(str(la / 'league'), str(la / 'snap'),
                             str(la / 'league' / 'HISTORY.DAT'))
    rc_c = subprocess.run(
        [HOST, '/EXPAND', str(lb / 'league'), str(lb / 'snap'),
         str(lb / 'league' / 'HISTORY.DAT')], capture_output=True).returncode
    assert rc_p == rc_c == 0, (rc_p, rc_c)
    compare(la, lb)


# ---------------------------------------------------------------------------
# 6. Seeded random stress: 20 seeds
# ---------------------------------------------------------------------------

def b_stress(seed):
    def build(base):
        rnd = random.Random(seed)
        lg, snap, m = te.expand_league(base, 'league')
        # expansion teams: ALA13 always (k 13), NLEXP___ (k 30) sometimes
        (lg / 'ALA13.V20').write_bytes(bytes(te.expansion_image('ALA13')))
        e_ids = {13}
        second = rnd.random() < 0.5
        if second:
            (lg / 'NLEXP___.V20').write_bytes(
                bytes(te.expansion_image('NLEXP___')))
            e_ids.add(30)
        te.add_snapshot(lg, snap, m)
        if second:
            for maj_dir in (lg, snap):
                d = bytearray((maj_dir / te.MAJ_PATH).read_bytes())
                a = 0x758c + 0x1d7 + 8 * 14
                d[a:a + 8] = b'NLEXP___'
                (maj_dir / te.MAJ_PATH).write_bytes(bytes(d))
            (snap / 'NLEXP___.V20').write_bytes(
                bytes(te.expansion_image('NLEXP___')))
        # the mask: every idmanaged except a random 2-4 AI sources
        others = [k for k in range(32) if k not in e_ids]
        ai = set(rnd.sample(others, rnd.randint(2, 4)))
        mask = 0
        for k in range(32):
            if k not in ai:
                mask |= 1 << k
        hh = bytearray(rnd.getrandbits(8) for _ in range(16))
        struct.pack_into('<I', hh, 12, mask)
        (lg / 'HISTORY.DAT').write_bytes(bytes(hh))
        # pools: random occupancy, some files missing
        for pi in range(4):
            if rnd.random() < 0.25:
                continue
            pimg = bytearray(rosters_py.pool_blank(bytearray(make_team_v20())))
            for _ in range(rnd.randint(0, 28)):
                slot = rnd.randrange(40)
                if slot < 16:
                    put_player(pimg, slot, 'P%d%d' % (pi, slot), 'P',
                               rnd.randrange(19, 39), 0,
                               dict((n, rnd.randrange(1, 13))
                                    for n in RATINGS_P))
                else:
                    put_player(pimg, slot, 'B%d%d' % (pi, slot), 'B',
                               rnd.randrange(19, 39), rnd.randrange(1, 9),
                               dict((n, rnd.randrange(1, 13))
                                    for n in RATINGS_B))
            (lg / ('POOL%d.V20' % (pi + 1))).write_bytes(bytes(pimg))
        # sometimes one contracted stem (from the AI set only, never an E team)
        if rnd.random() < 0.5:
            cands = [k for k in ai if k not in (13, 30)]
            if cands:
                k = rnd.choice(cands)
                slot = (k - 16) if k >= 16 else k
                stem = ('NL%02d' % slot) if k >= 16 else ('ALA%02d' % slot)
                drop = rnd.random() < 0.5
                _contract(lg, snap, stem, slot, drop)
        os.rename(snap, base / 'snap')
    return build


def test_stress(tmp_path):
    for seed in range(20):
        base = tmp_path / ('s%d' % seed)
        base.mkdir()
        parity(base, b_stress(seed))
