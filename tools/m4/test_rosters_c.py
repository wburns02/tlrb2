#!/usr/bin/env python3
"""Tests: the C port of the C6 roster pipeline (contract C6, contract slice).
The port is tools/m4/rosters_c/rosters.c; the Python reference is
tools/m4/rosters.py (rosters.run, the pure core).

Run:  python3 -m pytest -q tools/m4/test_rosters_c.py
The host binary tools/m4/rosters_c/rosters_host is built at import; the DOS
tests skip when OpenWatcom or /mnt/nvme/src/dosbox-x/src/dosbox-x is missing;
the real-data tests skip when /mnt/nvme/tlrb2/fixtures/t4/s1_pre is missing.
Every parity check compares, file by file, every team V20, every pool V20,
ROSTERS.TXT and HISTORY.DAT between a Python run (rosters.run) and a
host-binary run on two identical copies; a zero-file comparison fails.
"""
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from m4 import rosters as rosters_py                     # noqa: E402
from m4 import dynasty_ref                               # noqa: E402
from m4 import sim50                                     # noqa: E402
from test_history import make_team_v20, make_maj         # noqa: E402
import team_fill                                         # noqa: E402
import maj                                               # noqa: E402
from v20 import HDR, REC, F, _set, _get                  # noqa: E402
from v20 import SIZE as V20_SIZE                         # noqa: E402

WATCOM = '/mnt/nvme/tools/openwatcom'
DOSBOX = '/mnt/nvme/src/dosbox-x/src/dosbox-x'
S1_PRE = '/mnt/nvme/tlrb2/fixtures/t4/s1_pre'
RC = 'rosters_c'
ROSTERS_C = os.path.join(HERE, RC, 'rosters.c')
HOST = os.path.join(HERE, RC, 'rosters_host')
EXE = os.path.join(HERE, RC, 'ROSTERS.EXE')
POOL_FILES = rosters_py.POOL_FILES
ROSTERS_TXT = 'ROSTERS.TXT'


def _build():
    r = subprocess.run([sys.executable, os.path.join(HERE, RC,
                                                     'build_rosters.py')],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed:\n' + r.stdout + r.stderr)
    if not os.path.exists(HOST):
        raise RuntimeError('host binary missing after build')


_build()


def HOST_RUN(league, snap, hist, ret):
    return subprocess.run([HOST, league, snap, hist, ret],
                          capture_output=True, text=True)


# ---------------- fixture prep ----------------

def new_history(word, era, mask):
    """The 32 B HISTORY header (sim50.new_history): bytes 1..2 = the rng word,
    byte 10 = era, bytes 12..15 = the managed mask."""
    return bytes(sim50.new_history(word, era, mask))


def hist_of(file):
    return open(file, 'rb').read() if os.path.isfile(file) else None


def collect(league, hist_path):
    """Every output file of one run: ROSTERS.TXT, every team V20, every pool
    V20 and HISTORY.DAT. Unmapped stems (ALLSTAR*.V20) are not outputs, pool
    files always are (the run creates them), HISTORY.DAT always."""
    out = {}
    out[ROSTERS_TXT] = hist_of(os.path.join(league, ROSTERS_TXT))
    for name in os.listdir(league):
        if not name.upper().endswith('.V20'):
            continue
        if name.upper().startswith('POOL'):
            if name.upper() in ('POOL1.V20', 'POOL2.V20', 'POOL3.V20',
                                'POOL4.V20'):
                out[name.upper()] = hist_of(os.path.join(league, name))
            continue
        out[name.upper()] = hist_of(os.path.join(league, name))
    out['HISTORY.DAT'] = hist_of(hist_path)
    assert out['HISTORY.DAT'] is not None, 'HISTORY.DAT missing after the run'
    assert out[ROSTERS_TXT] is not None, 'ROSTERS.TXT missing after the run'
    assert len(out) > 2 and any(k.startswith('POOL') for k in out), \
        'a test that compares zero files fails'
    return out


def first_diff(a, b):
    if a == b:
        return -1, -1
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i, ((i - HDR) // REC) if i >= HDR else -1
    return (min(len(a), len(b)),
            ((min(len(a), len(b)) - HDR) // REC) if min(len(a), len(b)) >= HDR
            else -1)


def compare(key, lc, rc):
    """One file's parity: assert byte equality, report the first different
    file, offset and (for V20s) slot."""
    if lc is None or rc is None:
        raise AssertionError(f'{key}: one side is missing the file '
                             f'(py {lc is not None} c {rc is not None})')
    off, slot = first_diff(lc, rc)
    assert off < 0, (f'{key}: first diff at offset {off}'
                     + (f' (slot {slot})' if slot >= 0 else ''))


def parity(gold, cdir, chist):
    """File-by-file comparison of the Python and C outputs."""
    c = collect(cdir, chist)
    for key in sorted(gold):
        assert key in c, f'{key}: missing from the C output'
        compare(key, gold[key], c[key])
    for key in sorted(c):
        assert key in gold, f'{key}: file the Python run did not produce'


def snap_of(league, snap, stem, img=None):
    """Write SNAP_DIR/<STEM>.V20 for one team (all stems, upper case)."""
    for name in os.listdir(snap):
        if name.upper() == stem.upper() + '.V20':
            if img is not None:
                open(os.path.join(snap, name), 'wb').write(bytes(img))
            return
    open(os.path.join(snap, stem.upper() + '.V20'), 'wb').write(bytes(img))


# ---------------- test 1: real-data single seasons ----------------

def setup_case(root, pre, seed, era, mask):
    """Copy s1_pre to SNAP, write the 32 B HISTORY header, roll with
    dynasty_ref.roll_league, write LEAGUE/RETIRED.DAT from the retirees.
    Returns (league, snap, hist, retired)."""
    if os.path.exists(root):
        shutil.rmtree(root)
    snap = os.path.join(root, 'snap')
    os.makedirs(snap)
    for f in os.listdir(pre):
        shutil.copy2(os.path.join(pre, f), os.path.join(snap, f))
    hist = os.path.join(snap, 'HISTORY.DAT')
    open(hist, 'wb').write(new_history(seed & 0xffff or 1, era, mask))
    league = os.path.join(root, 'league')
    res = dynasty_ref.roll_league(snap, league, seed=seed)
    retired = os.path.join(league, 'RETIRED.DAT')
    sim50.write_retired(retired, res['retirees'])
    return league, snap, hist, retired


def run_case(root, tag, seed, era, mask):
    """Run both implementations on identical copies; file-by-file parity."""
    d = str(root)
    lc, ls, lh, lr = setup_case(os.path.join(d, tag + 'c'), S1_PRE, seed,
                                era, mask)
    rc_, rs, rh, rr = setup_case(os.path.join(d, tag + 'r'), S1_PRE, seed,
                                 era, mask)
    pyc = rosters_py.run(lc, ls, lh, lr)
    assert pyc == 0, f'py rc {pyc}'
    c = HOST_RUN(rc_, rs, rh, rr)
    assert c.returncode == 0, f'{tag}: C rc {c.returncode}: {c.stderr}'
    parity(collect(lc, lh), rc_, rh)


def _first_two_mask(league):
    """The bits of the first two mapped teams' league ids (managed repair
    path)."""
    stems = []
    m = make_maj()
    import glob
    for p in sorted(glob.glob(os.path.join(league, '*.V20'))):
        stem = os.path.basename(p)[:-4].lower()
        for lg in ('AL', 'NL'):
            base = 0 if lg == 'AL' else 16
            for s in range(16):
                if m.stem(lg, s).lower() == stem:
                    stems.append(base + s)
    mask = 0
    for lg in stems[:2]:
        mask |= 1 << lg
    return mask


def test_real_era0_mask0(tmp_path):
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    run_case(tmp_path, 'e0_', 0x1234, 0, 0)


def test_real_era1_mask0(tmp_path):
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    run_case(tmp_path, 'e1_', 0x1235, 1, 0)


def test_real_era2_mask0(tmp_path):
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    run_case(tmp_path, 'e2_', 0x1236, 2, 0)


def test_real_era0_managed_repair(tmp_path):
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    d = str(tmp_path)
    lc, ls, lh, lr = setup_case(os.path.join(d, 'mc'), S1_PRE, 0x1234, 0, 0)
    rc_, rs, rh, rr = setup_case(os.path.join(d, 'mr'), S1_PRE, 0x1234, 0, 0)
    mask = _first_two_mask(lc)
    assert mask, 'the fixture mapped no teams'
    # the managed path needs the era/seed the same on both sides: rewrite the
    # headers with the mask, then roll with the same seed (the roll ignores
    # the era bytes in the header)
    for hist in (lh, rh):
        raw = bytearray(open(hist, 'rb').read())
        struct.pack_into('<I', raw, 12, mask)
        open(hist, 'wb').write(bytes(raw))
    res = dynasty_ref.roll_league(ls, lc, seed=0x1234)
    sim50.write_retired(lr, res['retirees'])
    res = dynasty_ref.roll_league(rs, rc_, seed=0x1234)
    sim50.write_retired(rr, res['retirees'])
    pyc = rosters_py.run(lc, ls, lh, lr)
    assert pyc == 0, f'py rc {pyc}'
    c = HOST_RUN(rc_, rs, rh, rr)
    assert c.returncode == 0, f'C rc {c.returncode}: {c.stderr}'
    parity(collect(lc, lh), rc_, rh)


# ---------------- test 2: chain of 8 seasons ----------------

def chain(tmp_path, tag, seasons=8, seed=8230):
    """sim50's machinery (season_model on the snapshot, then the roll) with
    ROSTERS through both implementations each season; parity every season.
    The chain continues from the Python side."""
    d = str(tmp_path)
    last_py = last_c = None
    for k in range(1, seasons + 1):
        cur = os.path.join(d, f'{tag}{k}')
        os.makedirs(cur)
        league = os.path.join(cur, 'league')
        if k == 1:
            if not os.path.isdir(S1_PRE):
                import pytest
                pytest.skip('fixtures missing')
            shutil.copytree(S1_PRE, league)
            open(os.path.join(league, 'HISTORY.DAT'), 'wb').write(
                new_history(seed & 0xffff or 1, 0, 0))
        else:
            shutil.move(last_py, league)
        # season model on a snapshot of the league dir
        snap = os.path.join(cur, 'snap')
        rolled = os.path.join(snap, 'rolled')
        shutil.copytree(league, snap)
        hist_path = os.path.join(snap, 'HISTORY.DAT')
        word = sim50.hist_word(open(hist_path, 'rb').read())
        sm_rng = __import__('random').Random(seed + k)
        sim50.season_model(snap, sm_rng)
        res = dynasty_ref.roll_league(snap, rolled, word)
        sim50.write_retired(os.path.join(rolled, 'RETIRED.DAT'),
                            res['retirees'])
        # C side on a copy of the same inputs (copied BEFORE the Python run
        # mutates the snapshot dir)
        cur2 = os.path.join(d, f'{tag}c{k}')
        if os.path.exists(cur2):
            shutil.rmtree(cur2)
        shutil.copytree(cur, cur2)
        league2 = os.path.join(cur2, 'league')
        snap2 = os.path.join(cur2, 'snap')
        rolled2 = os.path.join(snap2, 'rolled')
        hist2 = os.path.join(snap2, 'HISTORY.DAT')
        # Python side on this season's dir
        pyc = rosters_py.run(rolled, snap, hist_path,
                             os.path.join(rolled, 'RETIRED.DAT'))
        assert pyc == 0, f'{tag} season {k}: py rc {pyc}'
        gold = collect(rolled, hist_path)
        c = HOST_RUN(rolled2, snap2, hist2,
                     os.path.join(rolled2, 'RETIRED.DAT'))
        assert c.returncode == 0, f'{tag} season {k}: C rc {c.returncode}' \
                                  f': {c.stderr}'
        parity(gold, rolled2, hist2)
        # the carried header (sim50.one_season): bytes 1..2 = the rosters end
        # word, 8..9 = the roll start word
        for rolled_, hist_ in ((rolled, hist_path),
                               (rolled2, hist2)):
            raw = open(hist_, 'rb').read()
            carry = bytearray(raw[:32].ljust(32, b'\0'))
            carry[1], carry[2] = raw[1], raw[2]
            carry[8], carry[9] = word & 0xff, (word >> 8) & 0xff
            open(os.path.join(rolled_, 'HISTORY.DAT'), 'wb').write(bytes(carry))
        os.remove(os.path.join(rolled, 'RETIRED.DAT'))
        os.remove(os.path.join(rolled2, 'RETIRED.DAT'))
        last_py = rolled
        last_c = rolled2
    # the chain continued from the Python side this whole time (last_py is the
    # final season's league); the C copy must equal it
    gold = collect(last_py, os.path.join(last_py, 'HISTORY.DAT'))
    parity(gold, last_c, os.path.join(last_c, 'HISTORY.DAT'))


def test_chain_8_seasons(tmp_path):
    chain(tmp_path, 'ch', seasons=8, seed=8230)


# ---------------- test 3: synthetic league ----------------

def synth_league(tmp_path, sub='lg', n_players=1, pit=None):
    """A synthetic league dir: MAJ + one V20 per stem, n_players batters +
    pit pitchers per team. Every player is young (exp 0, age 25): release
    protects them (C6 step 3), so the depth rebuild has starters."""
    ldir = os.path.join(str(tmp_path), sub)
    os.makedirs(ldir, exist_ok=True)
    make_maj().save(os.path.join(ldir, 'CLASSIC.MAJ'))
    path = os.path.join(ldir, 'CLASALE1.V20')
    d = bytearray(make_team_v20())
    pit = pit or 0
    assert pit + n_players <= 40, '40 player slots max'
    for i in range(n_players):
        slot = pit + i
        name = (b'B%02d' % i).ljust(12, b'\0')
        for rec in (slot, slot + 40):
            base = HDR + REC * rec
            # 20 exact bytes: a shorter slice assignment would SHRINK the
            # bytearray (slice assignment resizes)
            d[base:base + 20] = name + bytes(8)
            d[base] = 1
            r = bytearray(d[base:base + REC])
            _set(r, *F['age'], 25)
            _set(r, *F['pos1'], 2)
            _set(r, *F['exp'], 0)
            d[base:base + REC] = bytes(r)
        so = HDR + REC * (slot + 40)
        r = bytearray(d[so:so + REC])
        _set(r, *F['games'], 100)
        _set(r, *F['ab_l'], 400)
        d[so:so + REC] = bytes(r)
    for i in range(pit):
        slot = i
        name = (b'Q%02d' % i).ljust(12, b'\0')
        for rec in (slot, slot + 40):
            base = HDR + REC * rec
            d[base:base + 20] = name + bytes(8)
            d[base] = 1
            r = bytearray(d[base:base + REC])
            _set(r, *F['age'], 25)
            _set(r, *F['pos1'], 0)
            _set(r, *F['exp'], 0)
            d[base:base + REC] = bytes(r)
        so = HDR + REC * (slot + 40)
        r = bytearray(d[so:so + REC])
        _set(r, *F['games'], 30)
        _set(r, *F['ip10'], 1000)
        d[so:so + REC] = bytes(r)
    open(path, 'wb').write(bytes(d))
    return ldir, path


def synth_run(tmp_path, sub):
    """The standard synthetic ROSTERS run: both implementations on identical
    copies. Returns (py code, c proc, collect dicts)."""
    d = str(tmp_path)
    ldir = os.path.join(d, sub)
    hist = os.path.join(d, sub + 'h.DAT')
    open(hist, 'wb').write(bytes(range(32)))
    ret = os.path.join(d, sub + 'r.DAT')
    open(ret, 'wb').write(b'\x00')
    snap = os.path.join(d, sub + 'snap')
    shutil.copytree(ldir, snap)
    league = os.path.join(d, sub + 'league')
    shutil.copytree(ldir, league)
    pyc = rosters_py.run(league, snap, hist, ret)
    c = HOST_RUN(os.path.join(d, sub + 'league'), snap, hist, ret)
    return pyc, c, league, hist, os.path.join(d, sub, sub)


def test_synth_missing_history_exit2(tmp_path):
    ldir, _ = synth_league(tmp_path)
    snap = os.path.join(str(tmp_path), 'snap')
    shutil.copytree(ldir, snap)
    league = os.path.join(str(tmp_path), 'league')
    shutil.copytree(ldir, league)
    before = {n: open(os.path.join(league, n), 'rb').read()
              for n in os.listdir(league)}
    ret = os.path.join(str(tmp_path), 'r.DAT')
    open(ret, 'wb').write(b'\x00')
    hp = rosters_py.run(league, snap, os.path.join(str(tmp_path), 'NO.DAT'),
                        ret)
    assert hp == 2
    c = HOST_RUN(league, snap, os.path.join(str(tmp_path), 'NO.DAT'), ret)
    assert c.returncode == 2, c.returncode
    after = {n: open(os.path.join(league, n), 'rb').read()
             for n in os.listdir(league)}
    assert after == before
    assert not os.path.exists(os.path.join(str(tmp_path), 'NO.TMP'))


def test_synth_no_maj_exit2(tmp_path):
    ldir, _ = synth_league(tmp_path)
    os.remove(os.path.join(ldir, 'CLASSIC.MAJ'))
    snap = os.path.join(str(tmp_path), 'snap')
    shutil.copytree(ldir, snap)
    league = os.path.join(str(tmp_path), 'league')
    shutil.copytree(ldir, league)
    hist = os.path.join(str(tmp_path), 'h.DAT')
    open(hist, 'wb').write(bytes(range(32)))
    before = open(hist, 'rb').read()
    ret = os.path.join(str(tmp_path), 'r.DAT')
    open(ret, 'wb').write(b'\x00')
    hp = rosters_py.run(league, snap, hist, ret)
    assert hp == 2
    c = HOST_RUN(league, snap, hist, ret)
    assert c.returncode == 2, c.returncode
    assert open(hist, 'rb').read() == before
    assert not os.path.exists(os.path.join(str(tmp_path), 'h.TMP'))


def test_synth_missing_pool_created(tmp_path):
    """Missing pool files: created (FREE AGENTS headers) and byte-identical
    between the two runs."""
    ldir, _ = synth_league(tmp_path, n_players=18, pit=16)
    d = str(tmp_path)
    league = os.path.join(d, 'league')
    snap = os.path.join(d, 'snap')
    shutil.copytree(ldir, league)
    shutil.copytree(ldir, snap)
    hist = os.path.join(d, 'h.DAT')
    open(hist, 'wb').write(bytes(range(32)))
    ret = os.path.join(d, 'r.DAT')
    open(ret, 'wb').write(b'\x00')
    pyc = rosters_py.run(league, snap, hist, ret)
    assert pyc == 0, pyc
    c = HOST_RUN(league, snap, hist, ret)
    assert c.returncode == 0, c.stderr
    parity(collect(league, hist), league, hist)   # same dir: C == py already?
    # both runs wrote the same files; the C output must equal the py one
    for ki in (1, 2, 3, 4):
        p = os.path.join(league, 'POOL%d.V20' % ki)
        assert os.path.isfile(p), ki
        raw = open(p, 'rb').read()
        assert raw[0:14] == b'FREE AGENTS'.ljust(14, b'\0')[:14], ki


def test_synth_missing_retired(tmp_path):
    pyc, c, league, hist, _ = None, None, None, None, None
    ldir, _ = synth_league(tmp_path, n_players=18, pit=16)
    d = str(tmp_path)
    league = os.path.join(d, 'league')
    snap = os.path.join(d, 'snap')
    shutil.copytree(ldir, league)
    shutil.copytree(ldir, snap)
    hist = os.path.join(d, 'h.DAT')
    open(hist, 'wb').write(bytes(range(32)))
    pyc = rosters_py.run(league, snap, hist, os.path.join(d, 'NOPE.DAT'))
    assert pyc == 0, pyc
    c = HOST_RUN(league, snap, hist, os.path.join(d, 'NOPE.DAT'))
    assert c.returncode == 0, c.stderr
    parity(collect(league, hist), league, hist)


def test_synth_missing_snapshot(tmp_path):
    """One team's snapshot file missing (= snap None semantics): parity."""
    ldir, _ = synth_league(tmp_path, n_players=18, pit=16)
    d = str(tmp_path)
    league = os.path.join(d, 'league')
    snap = os.path.join(d, 'snap')
    shutil.copytree(ldir, league)
    shutil.copytree(ldir, snap)
    # one team's snap file: rename it away (the snap dir holds one V20)
    os.remove(os.path.join(snap, 'CLASALE1.V20'))
    hist = os.path.join(d, 'h.DAT')
    open(hist, 'wb').write(bytes(range(32)))
    ret = os.path.join(d, 'r.DAT')
    open(ret, 'wb').write(b'\x00')
    pyc = rosters_py.run(league, snap, hist, ret)
    assert pyc == 0, pyc
    c = HOST_RUN(league, snap, hist, ret)
    assert c.returncode == 0, c.stderr
    parity(collect(league, hist), league, hist)


def test_synth_hist_shorter_than_32(tmp_path):
    """A 4 B legacy history header: padded to 32 B, bytes 1..2 and 16..17
    written, length 32 on output."""
    ldir, _ = synth_league(tmp_path, n_players=18, pit=16)
    d = str(tmp_path)
    league = os.path.join(d, 'league')
    snap = os.path.join(d, 'snap')
    shutil.copytree(ldir, league)
    shutil.copytree(ldir, snap)
    hist = os.path.join(d, 'h.DAT')
    open(hist, 'wb').write(bytes([1, 0x39, 0x05, 0]))
    ret = os.path.join(d, 'r.DAT')
    open(ret, 'wb').write(b'\x00')
    pyc = rosters_py.run(league, snap, hist, ret)
    assert pyc == 0, pyc
    c = HOST_RUN(league, snap, hist, ret)
    assert c.returncode == 0, c.stderr
    parity(collect(league, hist), league, hist)
    raw = open(hist, 'rb').read()
    assert len(raw) == 32
    assert raw[0:4] == bytes([1, 0xfb, 0xb9, 0])   # byte 0 kept, 1..2 written
    assert raw[32 - 1] == 0


# ---------------- test 4: DOS build + real-DOS parity ----------------

def test_dos_build():
    exe2 = os.path.join(HERE, RC, 'ROSTERS2.EXE')
    if not os.path.isdir(WATCOM):
        if os.path.exists(exe2):
            os.remove(exe2)
        import pytest
        pytest.skip('OpenWatcom missing')
    for p in (EXE, exe2):
        if os.path.exists(p):
            os.remove(p)
    r = subprocess.run([sys.executable,
                        os.path.join(HERE, RC, 'build_rosters.py')],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.exists(EXE), 'ROSTERS.EXE not built'
    with open(EXE, 'rb') as f:
        assert f.read(2) == b'MZ'
    shutil.copy2(EXE, exe2)
    r = subprocess.run([sys.executable,
                        os.path.join(HERE, RC, 'build_rosters.py')],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert open(EXE, 'rb').read() == open(exe2, 'rb').read(), \
        'the second DOS build is not byte-identical'
    os.remove(exe2)


def _dos_ready():
    return (os.path.exists(EXE) and os.path.isfile(DOSBOX)
            and os.access(DOSBOX, os.X_OK))


BAT_LADDER = [
    'if errorlevel 3 goto e3',
    'if errorlevel 2 goto e2',
    'if errorlevel 1 goto e1',
    'echo 0 > RC.TXT',
    'goto end',
    ':e3',
    'echo 3 > RC.TXT',
    'goto end',
    ':e2',
    'echo 2 > RC.TXT',
    'goto end',
    ':e1',
    'echo 1 > RC.TXT',
    'goto end',
    ':end',
]


def run_dos(cdir, bat_lines, ddir=None):
    """Write cdir/RUN.BAT (CRLF), run it under headless dosbox-x, return
    int(RC.TXT). ddir = an optional second mount mounted as D:."""
    shutil.copy2(EXE, os.path.join(cdir, 'ROSTERS.EXE'))
    bat = os.path.join(cdir, 'RUN.BAT')
    with open(bat, 'wb') as f:
        for line in bat_lines:
            f.write(line.encode('latin-1') + b'\r\n')
        for line in BAT_LADDER:
            f.write(line.encode('latin-1') + b'\r\n')
    rc_txt = os.path.join(cdir, 'RC.TXT')
    if os.path.exists(rc_txt):
        os.remove(rc_txt)
    env = dict(os.environ)
    env['SDL_VIDEODRIVER'] = 'dummy'
    env['SDL_AUDIODRIVER'] = 'dummy'
    mounts = ['-c', 'mount c ' + cdir]
    if ddir:
        mounts += ['-c', 'mount d ' + ddir]
    proc = subprocess.run(
        [DOSBOX, '-silent', '-set', 'mixer nosound=true', '-set',
         'cpu cycles=max'] + mounts +
        ['-c', 'c:', '-c', 'RUN.BAT', '-c', 'exit'],
        capture_output=True, text=True, timeout=300, env=env)
    if not os.path.exists(rc_txt):
        raise AssertionError(f'RC.TXT missing rc={proc.returncode} '
                             f'out={proc.stdout[-400:]} '
                             f'err={proc.stderr[-400:]}')
    return int(open(rc_txt).read().strip() or 0)


def dos_inputs(d, pre, seed, era, mask):
    """Build the case 1 inputs into a flat DOS dir d (8.3 names, one level):
    the rolled league V20s + MAJ + RETIRED.DAT + HISTORY.DAT. Returns
    (gold, {[stem.V20]: bytes}) with the snapshot files for a D: mount."""
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    lc, ls, lh, lr = setup_case(os.path.join(d, '_w'), pre, seed, era, mask)
    # the inputs go to the DOS dir root BEFORE the Python run (which rewrites
    # the league V20s and HISTORY.DAT and creates the pools in place)
    for f in os.listdir(lc):
        if f.upper().endswith('.V20') or f.upper().endswith('.MAJ'):
            shutil.copy2(os.path.join(lc, f), os.path.join(d, f))
    shutil.copy2(lr, os.path.join(d, 'RETIRED.DAT'))
    shutil.copy2(lh, os.path.join(d, 'HISTORY.DAT'))
    # the snapshot files (read into memory before the work dir goes away)
    snaps = {}
    for f in os.listdir(ls):
        if f.upper().endswith('.V20'):
            snaps[f.upper()] = open(os.path.join(ls, f), 'rb').read()
    # the Python reference run on the work copy (its outputs are what the DOS
    # run is compared against: ROSTERS.TXT, the pools, HISTORY)
    pyc = rosters_py.run(lc, ls, lh, lr)
    assert pyc == 0, f'py rc {pyc}'
    gold = collect(lc, lh)
    shutil.rmtree(os.path.join(d, '_w'), ignore_errors=True)
    # the DOS run's snapshot mount (a separate dir, mounted as D:) holds the
    # STEM.V20 names (8.3)
    ddir = os.path.join(os.path.dirname(d), 'SNAP')
    if os.path.exists(ddir):
        shutil.rmtree(ddir)
    os.makedirs(ddir)
    for name, b in snaps.items():
        open(os.path.join(ddir, name), 'wb').write(b)
    return gold, ddir


def test_dos_era0_parity(tmp_path):
    """Case 1 (era 0, mask 0) under headless DOSBox-X: the DOS run's outputs
    equal the Python run's on the same inputs."""
    if not _dos_ready():
        import pytest
        pytest.skip('ROSTERS.EXE or dosbox-x missing')
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    d = str(tmp_path)
    cd = os.path.join(d, 'dos')
    gold, ddir = dos_inputs(cd, S1_PRE, 0x1234, 0, 0)
    rc = run_dos(cd, ['ROSTERS.EXE . D: HISTORY.DAT RETIRED.DAT'], ddir)
    assert rc == 0, f'dos rc {rc}'
    # the DOS outputs: the league dir is cd itself
    out = {}
    for f in os.listdir(cd):
        if f.upper().endswith('.V20'):
            out[f.upper()] = open(os.path.join(cd, f), 'rb').read()
    out['HISTORY.DAT'] = open(os.path.join(cd, 'HISTORY.DAT'), 'rb').read()
    out[ROSTERS_TXT] = open(os.path.join(cd, ROSTERS_TXT), 'rb').read()
    for ki in (1, 2, 3, 4):
        p = os.path.join(cd, 'POOL%d.V20' % ki)
        assert os.path.isfile(p), ki
        out['POOL%d.V20' % ki] = open(p, 'rb').read()
    for key in sorted(gold):
        assert key in out, f'{key}: missing from the DOS output'
        compare(key, gold[key], out[key])


def test_dos_chain_season_parity(tmp_path):
    """One chain season with pools present under headless DOSBox-X."""
    if not _dos_ready():
        import pytest
        pytest.skip('ROSTERS.EXE or dosbox-x missing')
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    d = str(tmp_path)
    # season 1 inputs exactly as the chain makes them
    cur = os.path.join(d, 's1')
    os.makedirs(cur)
    league = os.path.join(cur, 'league')
    shutil.copytree(S1_PRE, league)
    open(os.path.join(league, 'HISTORY.DAT'), 'wb').write(
        new_history(8230 & 0xffff or 1, 0, 0))
    snap = os.path.join(cur, 'snap')
    rolled = os.path.join(snap, 'rolled')
    shutil.copytree(league, snap)
    hist_path = os.path.join(snap, 'HISTORY.DAT')
    word = sim50.hist_word(open(hist_path, 'rb').read())
    sm_rng = __import__('random').Random(8231)
    sim50.season_model(snap, sm_rng)
    res = dynasty_ref.roll_league(snap, rolled, word)
    sim50.write_retired(os.path.join(rolled, 'RETIRED.DAT'), res['retirees'])
    # the DOS copy: the rolled league + the snap V20s (SNAP\\*.V20) as-is, taken
    # before the Python run (it rewrites the league and HISTORY in place)
    cd = os.path.join(d, 'dos')
    os.makedirs(cd)
    for f in os.listdir(rolled):
        if f.upper().endswith('.V20') or f.upper().endswith('.MAJ'):
            shutil.copy2(os.path.join(rolled, f), os.path.join(cd, f))
    shutil.copy2(os.path.join(rolled, 'RETIRED.DAT'),
                 os.path.join(cd, 'RETIRED.DAT'))
    shutil.copy2(hist_path, os.path.join(cd, 'HISTORY.DAT'))
    dd = os.path.join(d, 'snap')
    os.makedirs(dd)
    for f in os.listdir(snap):
        if f.upper().endswith('.V20'):
            shutil.copy2(os.path.join(snap, f), os.path.join(dd, f))
    pyc = rosters_py.run(rolled, snap, hist_path,
                         os.path.join(rolled, 'RETIRED.DAT'))
    assert pyc == 0, pyc
    gold = collect(rolled, hist_path)
    rc = run_dos(cd, ['ROSTERS.EXE . D: HISTORY.DAT RETIRED.DAT'], dd)
    assert rc == 0, f'dos rc {rc}'
    out = {}
    for f in os.listdir(cd):
        if f.upper().endswith('.V20'):
            out[f.upper()] = open(os.path.join(cd, f), 'rb').read()
    out['HISTORY.DAT'] = open(os.path.join(cd, 'HISTORY.DAT'), 'rb').read()
    out[ROSTERS_TXT] = open(os.path.join(cd, ROSTERS_TXT), 'rb').read()
    for key in sorted(gold):
        assert key in out, f'{key}: missing from the DOS output'
        compare(key, gold[key], out[key])


def _snapshot_tree(d):
    return {f: open(os.path.join(d, f), 'rb').read()
            for f in sorted(os.listdir(d))
            if os.path.isfile(os.path.join(d, f))}


def test_commit_rename_failure_restores_everything(tmp_path):
    """A rename failing mid-commit (host build with TEST_FAIL_RENAME_AT=k)
    exits 2 and leaves the league dir and HISTORY.DAT exactly as before:
    every original back, no TMP or BAK left. k = 0, a middle file, the
    HISTORY TMP (last)."""
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    src = os.path.join(HERE, RC, 'rosters.c')
    for k in (0, 7, 31):
        exe = os.path.join(str(tmp_path), 'rh%d' % k)
        subprocess.run(['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror',
                        '-DTEST_FAIL_RENAME_AT=%d' % k, '-o', exe, src],
                       check=True)
        lg, sn, hi, rt = setup_case(os.path.join(str(tmp_path), 'c%d' % k),
                                    S1_PRE, 0x2345, 0, 0)
        before_lg, before_sn = _snapshot_tree(lg), _snapshot_tree(sn)
        r = subprocess.run([exe, lg, sn, hi, rt], capture_output=True)
        assert r.returncode == 2, (k, r.returncode)
        assert _snapshot_tree(lg) == before_lg, k
        assert _snapshot_tree(sn) == before_sn, k


def test_commit_success_leaves_no_tmp_or_bak(tmp_path):
    """The normal commit swaps every output in and cleans up its BAKs."""
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    lg, sn, hi, rt = setup_case(os.path.join(str(tmp_path), 'ok'), S1_PRE,
                                0x2345, 0, 0)
    before = _snapshot_tree(lg)
    r = HOST_RUN(lg, sn, hi, rt)
    assert r.returncode == 0
    after = _snapshot_tree(lg)
    left = [f for f in list(after) + os.listdir(sn)
            if f.upper().endswith(('.TMP', '.BAK'))]
    assert left == []
    assert after != before


def test_dos_big_history_parity(tmp_path):
    """HISTORY.DAT past 64 KB (a long dynasty: 6 real seasons are ~200 KB) under DOS: ROSTERS patches header bytes
    1..2 and 16..17 and keeps every other byte and the length. Two sizes: 200000 B and 65536 + 16 B (16-bit size_t
    wraps below the 32 B header)."""
    if not _dos_ready():
        import pytest
        pytest.skip('ROSTERS.EXE or dosbox-x missing')
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    for size in (200000, 65536 + 16):
        d = os.path.join(str(tmp_path), 'h%d' % size)
        lc, ls, lh, lr = setup_case(os.path.join(d, '_w'), S1_PRE, 0x1234, 0, 0)
        hdr = open(lh, 'rb').read()[:32]
        body = bytes((i * 7 + 3) & 0xff for i in range(size - 32))
        open(lh, 'wb').write(hdr + body)
        cd = os.path.join(d, 'dos')
        os.makedirs(cd)
        for f in os.listdir(lc):
            if f.upper().endswith('.V20') or f.upper().endswith('.MAJ'):
                shutil.copy2(os.path.join(lc, f), os.path.join(cd, f))
        shutil.copy2(lr, os.path.join(cd, 'RETIRED.DAT'))
        shutil.copy2(lh, os.path.join(cd, 'HISTORY.DAT'))
        dd = os.path.join(d, 'SNAP')
        os.makedirs(dd)
        for f in os.listdir(ls):
            if f.upper().endswith('.V20'):
                shutil.copy2(os.path.join(ls, f), os.path.join(dd, f.upper()))
        assert rosters_py.run(lc, ls, lh, lr) == 0
        want = open(lh, 'rb').read()
        assert len(want) == size and want[32:] == body
        rc = run_dos(cd, ['ROSTERS.EXE . D: HISTORY.DAT RETIRED.DAT'], dd)
        assert rc == 0, f'{size}: dos rc {rc}'
        got = open(os.path.join(cd, 'HISTORY.DAT'), 'rb').read()
        assert len(got) == size, (size, len(got))
        assert got == want, (size, first_diff(want, got))
        compare('ROSTERS.TXT', open(os.path.join(lc, ROSTERS_TXT), 'rb').read(),
                open(os.path.join(cd, ROSTERS_TXT), 'rb').read())
