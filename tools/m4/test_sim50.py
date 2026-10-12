#!/usr/bin/env python3
"""Tests for the offline multi-season harness (tools/m4/sim50.py).

Every test needs /mnt/nvme/tlrb2/fixtures/t4/s1_pre and skips when missing.
Run:  python3 -m pytest -q tools/m4/test_sim50.py
"""
import os
import random
import shutil
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_TOOLS)
for _p in (_ROOT, _TOOLS, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest                                    # noqa: E402

if not os.path.isdir('/mnt/nvme/tlrb2/fixtures/t4/s1_pre'):
    pytest.skip('/mnt/nvme/tlrb2/fixtures/t4/s1_pre missing',
                allow_module_level=True)

import maj                                       # noqa: E402
import sim50                                     # noqa: E402
import teamids                                   # noqa: E402
import v20                                       # noqa: E402
from v20 import HDR, REC, F                      # noqa: E402

POOL_FILES = ('POOL1.V20', 'POOL2.V20', 'POOL3.V20', 'POOL4.V20')


def run(tmp_path, seasons, seed=8230, era=0, managed=(), set_args=()):
    out = str(tmp_path / 'sim')
    mp = sim50.main(['--seasons', str(seasons), '--seed', str(seed),
                     '--era', str(era), *managed, *set_args, '--out', out])
    assert mp == 0
    return out


def league_dirs(out):
    """The season dirs still on disk, season number order."""
    ds = sorted(d for d in os.listdir(out)
                if os.path.isdir(os.path.join(out, d)) and d.isdigit())
    return [os.path.join(out, d) for d in ds]


def assert_partition(img):
    """After ROSTERS the 40 roster slots are a partition: 10 P + 15 B named
    (byte 0 != 0 in the roster half), 6 + 9 reserves vacant, every name
    bytes 0..19 unique."""
    pits = [s for s in range(16) if img[HDR + REC * s]]
    bats = [s for s in range(16, 40) if img[HDR + REC * s]]
    assert len(pits) == 10
    assert len(bats) == 15
    names = [bytes(img[HDR + REC * s:HDR + REC * s + 20]) for s in pits + bats]
    assert len(set(names)) == 40
    for s in range(40):
        if s not in pits and s not in bats:
            # a reserve: roster half named in the reserves list is 0xff, and the
            # roster-half record itself is vacant
            assert not img[HDR + REC * s]


def test_three_season_run(tmp_path):
    out = run(tmp_path, 3)
    lines = [l for l in open(os.path.join(out, 'metrics.jsonl')).read().splitlines() if l]
    assert len(lines) == 3
    for line in lines:
        j = sim50.json.loads(line)
        assert set(sim50.MKeys) <= set(j)
    ds = league_dirs(out)
    # current + previous seasons only
    assert len(ds) <= 2
    # every league dir ROSTERS wrote (seasons after the first roll) partitions
    for d in ds[1:]:
        for p in sorted(glob.glob(os.path.join(d, 'league', '*.V20'))):
            stem = os.path.basename(p)
            if stem.startswith('ALLSTAR') or stem in POOL_FILES:
                continue
            assert_partition(bytearray(open(p, 'rb').read()))


import hashlib


def dir_hash(path):
    h = {}
    for root, dirs, files in os.walk(path):
        for fn in sorted(files):
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, path)
            h[rel] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    return h


def test_determinism(tmp_path):
    a = tmp_path / 'a'
    b = tmp_path / 'b'
    ma = sim50.main(['--seasons', '2', '--seed', '4242', '--era', '0',
                     '--out', str(a)])
    assert ma == 0
    mb = sim50.main(['--seasons', '2', '--seed', '4242', '--era', '0',
                     '--out', str(b)])
    assert mb == 0
    assert dir_hash(a) == dir_hash(b)


def test_set_max_trades_zero(tmp_path):
    out = run(tmp_path, 2, set_args=['--set', 'MAX_TRADES=0'])
    ds = league_dirs(out)
    assert len(ds) <= 2
    for d in ds[1:]:
        p = os.path.join(d, 'league', 'ROSTERS.TXT')
        if os.path.isfile(p):
            body = open(p, 'rb').read().decode('latin-1')
            assert 'TRADE ' not in body


def test_season_stats_written(tmp_path):
    """The season model writes games into the season-half twin and keeps the twin's name."""
    if not os.path.isdir(sim50.S1_PRE):
        pytest.skip('s1_pre missing')
    lg = tmp_path / 'lg'
    shutil.copytree(sim50.S1_PRE, lg)
    sim50.season_model(str(lg), random.Random(1))
    p = os.path.join(str(lg), 'CLASALE1.V20')
    img = open(p, 'rb').read()
    games = []
    for s in range(40):
        if not img[HDR + REC * s]:
            continue
        twin = img[HDR + REC * (s + 40):HDR + REC * (s + 41)]
        assert twin[0:20] == img[HDR + REC * s:HDR + REC * s + 20]
        games.append(v20._get(twin, *F['games']))
    assert sum(1 for g in games if g >= 140) >= 9, games
    assert sum(1 for g in games if g in (32, 55)) == 10, games


# ---------------------------------------------------------------- W/L slots (C12.3)
def make_wl_league(d, teams, table):
    """Synthetic 2-division league in d: LEAGUE.MAJ (full size) with the stems
    teams = [(L, slot, stem)], an empty V20 per team (header lists vacant, records
    zero) and TEAMID.DAT from table = {k: stem}, or none when table is None."""
    os.makedirs(d)
    maj_img = bytearray(maj.SIZE)
    for L, slot, stem in teams:
        off = teamids.S[L] + teamids.O_STEM + 8 * slot
        maj_img[off:off + 8] = stem.ljust(8, b'\0')
        img = bytearray(295 + 80 * 143)                  # header + 80 records
        img[111:295] = b'\xff' * 184
        with open(os.path.join(d, stem.decode('latin-1') + '.V20'), 'wb') as fh:
            fh.write(bytes(img))
    with open(os.path.join(d, 'LEAGUE.MAJ'), 'wb') as fh:
        fh.write(bytes(maj_img))
    if table is not None:
        tab = bytearray(256)
        for k, stem in table.items():
            tab[8 * k:8 * k + len(stem)] = stem
        with open(os.path.join(d, 'TEAMID.DAT'), 'wb') as fh:
            fh.write(bytes(tab))
    return d


def wl_of(d):
    return maj.Maj(open(os.path.join(d, 'LEAGUE.MAJ'), 'rb').read())


def test_season_model_wl_at_stable_id_slot(tmp_path):
    """TEAMID.DAT ids differ from the engine ids: each team's W/L lands in the
    MAJ slot of its stable id (C12.3), nowhere else."""
    d = make_wl_league(str(tmp_path / 'L'),
                       [(0, 0, b'BOS'), (0, 2, b'DET'), (1, 0, b'CHI')],
                       {5: b'BOS', 2: b'DET', 17: b'CHI'})
    wl, _ = sim50.season_model(d, random.Random(3))
    m = wl_of(d)
    assert sorted(wl) == [2, 5, 17]
    assert m.wl('AL', 0) == (wl[5], 162 - wl[5])
    assert m.wl('AL', 2) == (wl[2], 162 - wl[2])
    assert m.wl('NL', 0) == (wl[17], 162 - wl[17])
    assert m.wl('AL', 5) == (0, 0) and m.wl('NL', 1) == (0, 0)


def test_season_model_wl_engine_ids_without_table(tmp_path):
    d = make_wl_league(str(tmp_path / 'L'),
                       [(0, 0, b'BOS'), (0, 2, b'DET'), (1, 0, b'CHI'), (1, 1, b'SLN')],
                       None)
    wl, _ = sim50.season_model(d, random.Random(4))
    m = wl_of(d)
    assert sorted(wl) == [0, 2, 16, 17]
    for lg, slot, key in (('AL', 0, 0), ('AL', 2, 2), ('NL', 0, 16), ('NL', 1, 17)):
        assert m.wl(lg, slot) == (wl[key], 162 - wl[key])
