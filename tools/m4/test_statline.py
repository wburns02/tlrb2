#!/usr/bin/env python3
"""Ratings-implied stat line (tools/m4/statline.py, M4 Q8) and its C port
tools/m4/statline.h.

Python grids check that fill() reproduces the ratings it is built from. C parity runs
the host harness statline_c/sl_host (built at import by build_sl.py) against the Python
reference, byte for byte. The 16-bit SLHOST.EXE runs headless under DOSBox-X when both
it and the dosbox-x binary exist; otherwise that test skips. The shipped-team check
skips when /mnt/nvme/tlrb2/pristine is missing.
Run:  python3 -m pytest -q tools/m4/test_statline.py
"""
import glob
import os
import random
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
for _p in (_TOOLS, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest                                     # noqa: E402

import ratings as rt                              # noqa: E402
import rookies                                    # noqa: E402
import statline as sl                             # noqa: E402
from m4.rollover import Rng                       # noqa: E402

SL_C = os.path.join(_HERE, 'statline_c')
HOST = os.path.join(SL_C, 'sl_host')
EXE = os.path.join(SL_C, 'SLHOST.EXE')
DOSBOX = '/mnt/nvme/src/dosbox-x/src/dosbox-x'
PRISTINE = '/mnt/nvme/tlrb2/pristine/TONY2/TEAMS'
REC = sl.RECORD_LEN
IMAGE_LEN = sl.HEADER_LEN + 80 * REC              # 11735
SEASON = frozenset(sl.SEASON_STAT_BYTES)
SEASON_YEAR = 123


def _build():
    r = subprocess.run([sys.executable, os.path.join(SL_C, 'build_sl.py')],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed:\n' + r.stdout + r.stderr)
    if not os.path.exists(HOST):
        raise RuntimeError('host binary missing after build')


_build()


# ---------------------------------------------------------------- record builders

def batter_rec(P, K, S, bats, pos, rg, am):
    """A named batter with power, hit and run and speed in the rating nibbles (bunt,
    unused here, stays 0), bats code in byte 29 bits 1..2, range and arm in byte 94."""
    r = bytearray(REC)
    r[0] = 0x41
    r[74] = P
    r[75] = K
    r[29] = (S << 4) | (bats << 1)
    r[31] = pos
    r[94] = (rg << 4) | am
    return r


def pitcher_rec(C, V, E, rhp):
    """A named pitcher: control and velocity in byte 134, endurance in byte 135 hi;
    byte 29 bit 3 is the throws bit (1 = right, the split table's RHP row)."""
    r = bytearray(REC)
    r[0] = 0x41
    r[134] = C | (V << 4)
    r[135] = E << 4
    r[29] = 8 if rhp else 0
    r[31] = 0
    return r


def batter_grid():
    """(pos, bats, P, K, S, rg, am) for pos 1, 5, 8, 9; range and arm walk all 12 x 12
    pairs over the grid (rg and am 1..12)."""
    n = 0
    for pos in (1, 5, 8, 9):
        for bats in range(3):
            for P in range(1, 13):
                for K in range(1, 13):
                    for S in range(1, 13):
                        n += 1
                        yield pos, bats, P, K, S, 1 + n % 12, 1 + (n // 12) % 12


def pitcher_grid():
    for C in range(1, 13):
        for V in range(1, 13):
            for E in range(1, 11):
                for rhp in (False, True):
                    yield C, V, E, rhp


def _rand_recs(seed, n):
    rnd = random.Random(seed)
    return [bytes(rnd.getrandbits(8) for _ in range(REC)) for _ in range(n)]


# ---------------------------------------------------------------- Python grids

def test_batter_grid_ratings():
    """hit and run exact; power between the BA ladder step and the 4 x BA step, equal to
    the power rating whenever the hits allow it; speed never above the rating and at
    most 375 misses per 5184 records of one pos code (all three bats); fielding arm
    exact and range the rating unless PO 0 already reaches higher."""
    misses = {}
    for pos, bats, P, K, S, rg, am in batter_grid():
        r = batter_rec(P, K, S, bats, pos, rg, am)
        sl.fill(r)
        ab, h = rt.s2(r, 37), rt.s2(r, 41)
        assert ab == sl.AB
        assert rt.hit_and_run(r) == K, (pos, bats, P, K, S, rg, am)
        lo = rt.ladder(rt.per_mille(h, ab), sl.SLG_T)
        hi = rt.ladder(rt.per_mille(4 * h, ab), sl.SLG_T)
        assert rt.power(r) == min(max(P, lo), hi), (pos, bats, P, K, S, rg, am)
        sp = rt.speed(r)
        assert sp <= S, (pos, bats, P, K, S)
        misses[pos] = misses.get(pos, 0) + (sp != S)
        if pos <= 8:
            assert rt.arm(r) == am, (pos, bats, P, K, S, rg, am)
            no_po = bytearray(r)
            no_po[77] = no_po[78] = 0
            assert rt.rng(r) == max(rg, rt.rng(no_po)), (pos, bats, P, K, S, rg, am)
    for pos, n in misses.items():
        assert n <= 375, (pos, n)


def test_pitcher_grid_ratings():
    """control, velocity and endurance exact on every triple, for both throws."""
    for C, V, E, rhp in pitcher_grid():
        r = pitcher_rec(C, V, E, rhp)
        sl.fill(r)
        got = (rt.control(r), rt.velocity(r), rt.endurance(r))
        assert got == (C, V, E), (C, V, E, rhp, got)


def test_fill_changes_only_season_bytes():
    for raw in _rand_recs(0x5171, 2000):
        r = bytearray(raw)
        sl.fill(r)
        for o in range(REC):
            if o not in SEASON:
                assert r[o] == raw[o], o


def test_is_placeholder_rookies_every_position():
    """A generated rookie carries the placeholder line at every position code."""
    for pos in range(16):
        for seed in (1, 0x2222, 0x7e57):
            rec = rookies.RookieGen(Rng(seed)).make(pos, SEASON_YEAR)
            assert sl.is_placeholder(rec), (pos, seed)


def test_is_placeholder_false_cases():
    for pos in (0, 1, 5, 9, 15):
        rec = rookies.RookieGen(Rng(0x99)).make(pos, SEASON_YEAR)
        assert sl.is_placeholder(rec)
        sl.fill(rec)
        assert not sl.is_placeholder(rec), 'filled record'
        rec = rookies.RookieGen(Rng(0x99)).make(pos, SEASON_YEAR)
        rec[0] = 0
        assert not sl.is_placeholder(rec), 'unnamed'
        rec = rookies.RookieGen(Rng(0x99)).make(pos, SEASON_YEAR)
        rec[23] = 1
        assert not sl.is_placeholder(rec), 'G != 0'
        for off in ((41, 53, 57) if pos else (111, 121, 125)):
            rec = rookies.RookieGen(Rng(0x99)).make(pos, SEASON_YEAR)
            rec[off] = 1
            assert not sl.is_placeholder(rec), (pos, off)


def test_no_false_positives_on_shipped_teams():
    if not os.path.isdir(PRISTINE):
        pytest.skip('shipped TONY2 TEAMS missing')
    paths = sorted(glob.glob(os.path.join(PRISTINE, '*', '*.V20')))
    assert paths, 'TEAMS exists but has no V20 files'
    for p in paths:
        img = bytearray(open(p, 'rb').read())
        assert sl.repair_image(img) == [], p


# ---------------------------------------------------------------- C parity (host)

def _assert_same(got, exp, rec_len, what):
    """Byte equality; on a mismatch name the first differing record and its offsets."""
    if got == exp:
        return
    assert len(got) == len(exp), '%s: length %d, python %d' % (what, len(got), len(exp))
    for k in range(len(exp) // rec_len):
        a = got[k * rec_len:(k + 1) * rec_len]
        b = exp[k * rec_len:(k + 1) * rec_len]
        if a != b:
            offs = [i for i in range(rec_len) if a[i] != b[i]]
            raise AssertionError('%s: record %d differs at offsets %s (C %s, python %s)'
                                 % (what, k, offs[:16], a[offs[0]], b[offs[0]]))
    raise AssertionError('%s: differs' % what)


def _run_host(mode, data, tmp):
    inp = os.path.join(tmp, 'in.bin')
    out = os.path.join(tmp, 'out.bin')
    with open(inp, 'wb') as f:
        f.write(data)
    r = subprocess.run([HOST, mode, inp, out])
    assert r.returncode == 0, 'sl_host %s rc %d' % (mode, r.returncode)
    with open(out, 'rb') as f:
        return f.read()


def _fill_py(recs):
    out = []
    for raw in recs:
        r = bytearray(raw)
        sl.fill(r)
        out.append(bytes(r))
    return b''.join(out)


def _grid_recs():
    """The batter grid over bats 0..2 and pos codes 0..15, then the full pitcher grid
    over E, C and V nibbles 0..15 with both throws and the other byte 29 bits."""
    recs = []
    n = 0
    for pos in range(16):
        for bats in range(3):
            for P in range(1, 13):
                for K in range(1, 13):
                    for S in range(1, 13):
                        n += 1
                        recs.append(bytes(batter_rec(P, K, S, bats, pos,
                                                     1 + n % 12, 1 + (n // 12) % 12)))
    n = 0
    for E in range(16):
        for C in range(16):
            for V in range(16):
                n += 1
                r = bytearray(REC)
                r[0] = 0x41
                r[134] = C | (V << 4)
                r[135] = E << 4
                r[29] = ((n & 1) << 3) | (((n // 2) % 3) << 1) | ((n % 16) << 4)
                recs.append(bytes(r))
    return recs


def _synth_image(rnd):
    """A V20 image of random bytes whose roster records are a mix of random records and
    placeholder rookies (every other record a rookie, the rest random)."""
    img = bytearray(rnd.getrandbits(8) for _ in range(IMAGE_LEN))
    for i in range(sl.ROSTER_RECORDS):
        o = sl.HEADER_LEN + REC * i
        if rnd.random() < 0.5:
            pos = rnd.randrange(16)
            img[o:o + REC] = rookies.RookieGen(Rng(rnd.randrange(1, 0xffff))).make(
                pos, SEASON_YEAR)
    return img


def test_host_fill_parity_grid_and_random(tmp_path):
    recs = _grid_recs()
    recs += _rand_recs(0xc0de, 3000)
    data = b''.join(recs)
    got = _run_host('fill', data, str(tmp_path))
    _assert_same(got, _fill_py(recs), REC, 'fill grid')


def test_host_repair_parity_synthetic_and_shipped(tmp_path):
    rnd = random.Random(0x4e11)
    imgs = [bytes(_synth_image(rnd)) for _ in range(20)]
    if os.path.isdir(PRISTINE):
        for p in sorted(glob.glob(os.path.join(PRISTINE, '*', '*.V20'))):
            imgs.append(open(p, 'rb').read())
    data = b''.join(imgs)
    got = _run_host('repair', data, str(tmp_path))
    exp = bytearray(data)
    for k in range(len(imgs)):
        img = bytearray(exp[k * IMAGE_LEN:(k + 1) * IMAGE_LEN])
        sl.repair_image(img)
        exp[k * IMAGE_LEN:(k + 1) * IMAGE_LEN] = img
    _assert_same(got, bytes(exp), IMAGE_LEN, 'repair images')


def test_host_usage_exit2(tmp_path):
    r = subprocess.run([HOST, 'bogus', str(tmp_path / 'x'), str(tmp_path / 'y')])
    assert r.returncode == 2
    r = subprocess.run([HOST, 'fill', str(tmp_path / 'missing'), str(tmp_path / 'y')])
    assert r.returncode == 2


# ---------------------------------------------------------------- DOS parity (16-bit)

BAT_LADDER = [
    'if errorlevel 2 goto e2',
    'if errorlevel 1 goto e1',
    'echo 0 > RC.TXT',
    'goto end',
    ':e2',
    'echo 2 > RC.TXT',
    'goto end',
    ':e1',
    'echo 1 > RC.TXT',
    ':end',
]


def _run_dos(cdir, bat_line):
    """Write cdir/RUN.BAT (CRLF), run it under headless dosbox-x, return RC.TXT."""
    shutil.copy2(EXE, os.path.join(cdir, 'SLHOST.EXE'))
    with open(os.path.join(cdir, 'RUN.BAT'), 'wb') as f:
        for line in [bat_line] + BAT_LADDER:
            f.write(line.encode('latin-1') + b'\r\n')
    rc_txt = os.path.join(cdir, 'RC.TXT')
    if os.path.exists(rc_txt):
        os.remove(rc_txt)
    env = dict(os.environ)
    env['SDL_VIDEODRIVER'] = 'dummy'
    env['SDL_AUDIODRIVER'] = 'dummy'
    cmds = ['-c', 'mount c ' + cdir, '-c', 'c:', '-c', 'RUN.BAT', '-c', 'exit']
    proc = subprocess.run([DOSBOX, '-silent', '-set', 'mixer nosound=true', '-set',
                           'cpu cycles=max'] + cmds,
                          capture_output=True, text=True, timeout=300, env=env)
    if not os.path.exists(rc_txt):
        raise AssertionError('RC.TXT missing rc=%d out=%s err=%s'
                             % (proc.returncode, proc.stdout[-400:], proc.stderr[-400:]))
    return int(open(rc_txt).read().strip() or 0)


def _dos_ready():
    return (os.path.exists(EXE) and os.path.isfile(DOSBOX)
            and os.access(DOSBOX, os.X_OK))


def test_dos_parity(tmp_path):
    """SLHOST.EXE (16-bit) against the Python reference: batters P,K,S for bats 1 pos 6,
    pitchers C,V,E with throws R, 300 random records and 3 synthetic images."""
    if not _dos_ready():
        pytest.skip('SLHOST.EXE or dosbox-x missing')
    rnd = random.Random(0xd05)
    recs = []
    for P in range(1, 13):
        for K in range(1, 13):
            for S in range(1, 13):
                recs.append(bytes(batter_rec(P, K, S, 1, 6, 1 + (P + K) % 12, 1 + S % 12)))
    for C in range(1, 13):
        for V in range(1, 13):
            for E in range(1, 11):
                recs.append(bytes(pitcher_rec(C, V, E, True)))
    recs += _rand_recs(0xd05a, 300)
    fill_in = b''.join(recs)
    imgs = [bytes(_synth_image(rnd)) for _ in range(3)]
    rep_in = b''.join(imgs)
    d = str(tmp_path / 'dos')
    os.makedirs(d)
    with open(os.path.join(d, 'FILLIN.BIN'), 'wb') as f:
        f.write(fill_in)
    rc = _run_dos(d, 'SLHOST.EXE fill FILLIN.BIN FILLOUT.BIN')
    assert rc == 0, 'dos fill rc %d' % rc
    got = open(os.path.join(d, 'FILLOUT.BIN'), 'rb').read()
    _assert_same(got, _fill_py(recs), REC, 'dos fill')
    with open(os.path.join(d, 'REPIN.BIN'), 'wb') as f:
        f.write(rep_in)
    rc = _run_dos(d, 'SLHOST.EXE repair REPIN.BIN REPOUT.BIN')
    assert rc == 0, 'dos repair rc %d' % rc
    got = open(os.path.join(d, 'REPOUT.BIN'), 'rb').read()
    exp = bytearray(rep_in)
    for k in range(len(imgs)):
        img = bytearray(exp[k * IMAGE_LEN:(k + 1) * IMAGE_LEN])
        sl.repair_image(img)
        exp[k * IMAGE_LEN:(k + 1) * IMAGE_LEN] = img
    _assert_same(got, bytes(exp), IMAGE_LEN, 'dos repair images')
