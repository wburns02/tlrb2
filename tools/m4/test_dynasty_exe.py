#!/usr/bin/env python3
"""T4a gate: DYNASTY.EXE end to end on the real m3_end / s1_pre fixtures, via
the mini DOS (dosemu.py), against the Python reference roll_league.

Run: cd ~/tlrb2 && python3 -m pytest tools/m4/test_dynasty_exe.py -q
"""
import os
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
for _p in (_TOOLS, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

from m4.dosemu import run_exe
from m4.dynasty_ref import roll_league

FIX = '/mnt/nvme/tlrb2/fixtures/t4'
LEAGUES = [os.path.join(FIX, d) for d in ('m3_end', 's1_pre')]
EXE = os.path.join(_HERE, 'blob', 'DYNASTY.EXE')
BUILD = os.path.join(_HERE, 'blob', 'build_dynasty.py')

subprocess.run([sys.executable, BUILD], check=True, cwd=os.path.join(_HERE, 'blob'))


def leagues():
    return [d for d in LEAGUES if os.path.isdir(d)]


def league_files(lg):
    return sorted(f for f in os.listdir(lg) if f.endswith('.V20'))


def make_root(tmp_root, src_league, hist=None, dynsnap=True):
    """tmp root/TONY2/TEAMS/CLASSIC <- a copy of src_league; optional HISTORY.DAT."""
    lg = tmp_root / 'TONY2' / 'TEAMS' / 'CLASSIC'
    lg.mkdir(parents=True)
    for f in league_files(src_league):
        shutil.copy2(os.path.join(src_league, f), lg / f)
    shutil.copy2(os.path.join(src_league, 'CLASSIC.MAJ'), lg / 'CLASSIC.MAJ')
    if hist is not None:
        (lg / 'HISTORY.DAT').write_bytes(hist)
    if dynsnap:
        (tmp_root / 'DYNSNAP').mkdir()
    return lg


def expected(src_league, tmp_root, seed, fill=True):
    out = tmp_root / 'ref'
    return roll_league(src_league, str(out), seed, fill=fill)


def check_v20s(got_lg, ref_out):
    for f in sorted(x for x in os.listdir(ref_out) if x.endswith('.V20')):
        a = (got_lg / f).read_bytes() if (got_lg / f).exists() else None
        b = (os.path.join(ref_out, f))
        with open(b, 'rb') as fh:
            assert a == fh.read(), f'{f} mismatch'


def hist_bytes(r):
    lo, hi = r['rng_end'] & 0xFF, (r['rng_end'] >> 8) & 0xFF
    slo, shi = r['seed'] & 0xFF, (r['seed'] >> 8) & 0xFF
    b = bytearray(32)
    b[0] = 1
    b[1], b[2] = lo, hi
    b[8], b[9] = slo, shi
    return bytes(b)


def parse_retired(path):
    d = path.read_bytes()
    nteam = d[0]
    names, flags = [], []
    off = 1
    for _ in range(nteam):
        names.append(d[off:off + 13].split(b'\0')[0].decode())
        off += 13
        flags.append(list(d[off:off + 40]))
        off += 40
    assert off == len(d), f'RETIRED.DAT trailing bytes: {len(d) - off}'
    return names, flags


def run(root_str, ticks):
    return run_exe(EXE, root_str, cwd='TONY2', ticks=ticks)


FIXTURES = [p for p in LEAGUES if os.path.isdir(p)]


def one_league():
    if not FIXTURES:
        pytest.skip('t4 league fixture missing')
    return FIXTURES[0]


def src_league():
    for d in LEAGUES:
        if os.path.isdir(d):
            return d
    pytest.skip('t4 league fixture missing')


# --- a: fresh roll ---------------------------------------------------------
def test_a_fresh_roll(tmp_path):
    src = one_league()
    lg = make_root(tmp_path / 'root', src)
    r = expected(src, tmp_path / 'root', 0x1234)
    root_str = str(tmp_path / 'root')
    ec = run(root_str, 0x1234)
    assert ec == 1
    check_v20s(lg, os.path.join(tmp_path / 'root', 'ref'))
    h = (lg / 'HISTORY.DAT').read_bytes()
    assert h == bytes([1, r['rng_end'] & 0xFF, (r['rng_end'] >> 8) & 0xFF,
                       0, 0, 0, 0, 0, 0x34, 0x12]) + bytes(22)
    names, flags = parse_retired(tmp_path / 'root' / 'DYNSNAP' / 'RETIRED.DAT')
    teams = league_files(src)
    assert len(names) == len(teams)
    assert [n.upper() for n in names] == sorted(teams)
    assert any(any(f) for f in flags), 'no retirees: flags check is vacuous'
    for fn, ret in r['retirees'].items():
        i = sorted(teams).index(fn)
        assert flags[i] == [1 if k in ret else 0 for k in range(40)], fn


# --- b/c: seed 1 cases ------------------------------------------------------
def test_b_ticks_zero(tmp_path):
    src = one_league()
    lg = make_root(tmp_path / 'root', src)
    r = expected(src, tmp_path / 'root', 1)
    root_str = str(tmp_path / 'root')
    assert run(root_str, 0x00000000) == 1
    check_v20s(lg, os.path.join(tmp_path / 'root', 'ref'))
    h = (lg / 'HISTORY.DAT').read_bytes()
    assert h[0] == 1
    assert ((h[9] << 8) | h[8]) == 1
    assert ((h[2] << 8) | h[1]) == r['rng_end']


def test_c_ticks_high_only(tmp_path):
    src = one_league()
    lg = make_root(tmp_path / 'root', src)
    r = expected(src, tmp_path / 'root', 1)
    assert run(str(tmp_path / 'root'), 0x00050000) == 1
    check_v20s(lg, os.path.join(tmp_path / 'root', 'ref'))
    h = (lg / 'HISTORY.DAT').read_bytes()
    assert ((h[9] << 8) | h[8]) == 1


# --- d: legacy 4 B file -----------------------------------------------------
def test_d_legacy_4b_file(tmp_path):
    src = one_league()
    lg = make_root(tmp_path / 'root', src, hist=bytes([0, 0x39, 0x05, 0]))
    r = expected(src, tmp_path / 'root', 0x0539)
    assert run(str(tmp_path / 'root'), 0x1234) == 1  # ticks ignored
    check_v20s(lg, os.path.join(tmp_path / 'root', 'ref'))
    h = (lg / 'HISTORY.DAT').read_bytes()
    assert len(h) == 32
    assert ((h[2] << 8) | h[1]) == r['rng_end']
    for k in list(range(3, 8)) + list(range(10, 32)):
        assert h[k] == 0, f'byte {k} = {h[k]:#x}'


# --- e: 9000 B file, done flag 0 --------------------------------------------
def test_e_grow_9000b_file(tmp_path):
    src = one_league()
    h = bytearray(9000)
    h[0] = 0
    h[1], h[2] = 0x77, 0x07
    for i in range(3, 9000):
        h[i] = (i * 7 + 3) & 0xff | 1
    before = bytes(h)
    lg = make_root(tmp_path / 'root', src, hist=before)
    r = expected(src, tmp_path / 'root', 0x0777)
    assert run(str(tmp_path / 'root'), 0x1234) == 1
    check_v20s(lg, os.path.join(tmp_path / 'root', 'ref'))
    after = (lg / 'HISTORY.DAT').read_bytes()
    assert len(after) == 9000
    assert after[0] == 1
    assert after[3:8] == before[3:8]
    assert after[10:] == before[10:]  # every other byte unchanged
    assert ((after[2] << 8) | after[1]) == r['rng_end']
    assert ((after[9] << 8) | after[8]) == 0x0777


# --- f: rng word 0 in the file -> ticks seed ---------------------------------
def test_f_rng_word_zero(tmp_path):
    src = one_league()
    h = bytearray(64)
    h[0] = 0
    # rng word stays 0
    lg = make_root(tmp_path / 'root', src, hist=bytes(h))
    r = expected(src, tmp_path / 'root', 0x4242)
    assert run(str(tmp_path / 'root'), 0x4242) == 1
    check_v20s(lg, os.path.join(tmp_path / 'root', 'ref'))
    after = (lg / 'HISTORY.DAT').read_bytes()
    assert ((after[9] << 8) | after[8]) == 0x4242
    assert ((after[2] << 8) | after[1]) == r['rng_end']


# --- g: done flag 1 at day 0xf3 ----------------------------------------------
def test_g_done_flag_noop(tmp_path):
    src = one_league()
    lg = make_root(tmp_path / 'root', src, hist=bytes([1, 0x34, 0x12] + [0] * 29))
    before = {}
    for f in sorted(os.listdir(lg)):
        before[f] = (lg / f).read_bytes()
    assert run(str(tmp_path / 'root'), 0x1234) == 0
    for f in sorted(os.listdir(lg)):
        assert (lg / f).read_bytes() == before[f], f
    assert not os.path.exists(tmp_path / 'root' / 'DYNSNAP' / 'RETIRED.DAT')


# --- h: day != 0xf3 clears byte 0 in place -----------------------------------
def test_h_day_byte_clears_flag(tmp_path):
    src = one_league()
    h = bytearray(9000)
    h[0] = 1
    for i in range(3, 9000):
        h[i] = (i * 7 + 3) & 0xff | 1
    before = bytes(h)
    lg = make_root(tmp_path / 'root', src, hist=before)
    maj = bytearray((lg / 'CLASSIC.MAJ').read_bytes())
    maj[0x20a] = 0x07
    (lg / 'CLASSIC.MAJ').write_bytes(bytes(maj))
    v20s = {f: (lg / f).read_bytes() for f in league_files(src)}
    assert run(str(tmp_path / 'root'), 0x1234) == 0
    after = (lg / 'HISTORY.DAT').read_bytes()
    assert len(after) == 9000
    assert after[0] == 0
    assert after[1:] == before[1:]
    for f in league_files(src):
        assert (lg / f).read_bytes() == v20s[f], f


# --- i: no CLASSIC.MAJ --------------------------------------------------------
def test_i_no_maj(tmp_path):
    src = one_league()
    lg = make_root(tmp_path / 'root', src)
    os.remove(lg / 'CLASSIC.MAJ')
    before = {f: (lg / f).read_bytes() for f in os.listdir(lg)}
    assert run(str(tmp_path / 'root'), 0x1234) == 0
    for f in os.listdir(lg):
        assert (lg / f).read_bytes() == before[f], f
    assert not os.path.exists(tmp_path / 'root' / 'DYNSNAP' / 'RETIRED.DAT')


# --- j: no DYNSNAP dir ---------------------------------------------------------
def test_j_no_dynsnap(tmp_path):
    src = one_league()
    lg = make_root(tmp_path / 'root', src, dynsnap=False)
    r = expected(src, tmp_path / 'root', 0x1234)
    assert run(str(tmp_path / 'root'), 0x1234) == 1
    check_v20s(lg, os.path.join(tmp_path / 'root', 'ref'))
    after = (lg / 'HISTORY.DAT').read_bytes()
    assert after == hist_bytes(r)
    for dirpath, dirnames, filenames in os.walk(tmp_path / 'root'):
        assert 'RETIRED.DAT' not in filenames, dirpath


# --- k: two rolls in a row ------------------------------------------------------
def test_k_two_rolls(tmp_path):
    src = one_league()
    lg = make_root(tmp_path / 'root', src)
    assert run(str(tmp_path / 'root'), 0x1234) == 1
    h = bytearray((lg / 'HISTORY.DAT').read_bytes())
    first_end = (h[2] << 8) | h[1]
    # the first roll's output league is the second roll's input
    snap = tmp_path / 'snap'
    shutil.copytree(lg, snap)
    h[0] = 0
    (lg / 'HISTORY.DAT').write_bytes(bytes(h))
    assert run(str(tmp_path / 'root'), 0x9999) == 1
    after = (lg / 'HISTORY.DAT').read_bytes()
    assert ((after[9] << 8) | after[8]) == first_end
    r = roll_league(str(snap), str(tmp_path / 'ref2'), first_end)
    check_v20s(lg, str(tmp_path / 'ref2'))
    assert after[1] | (after[2] << 8) == r['rng_end']


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
