#!/usr/bin/env python3
"""Tests: the C port of the C6 roster pipeline (contract C6, contract slice).
The port is tools/m4/rosters_c/rosters.c; the Python reference is
tools/m4/rosters.py (rosters.run, the pure core).

Run:  python3 -m pytest -q tools/m4/test_rosters_c.py
The host binary tools/m4/rosters_c/rosters_host is built at import; the DOS
tests skip when OpenWatcom or /mnt/nvme/src/dosbox-x/src/dosbox-x is missing;
the real-data tests skip when /mnt/nvme/tlrb2/fixtures/t4/s1_pre is missing.
Every parity check compares, file by file, every team V20, every pool V20,
ROSTERS.TXT, HISTORY.DAT, the MAJ and TEAMID.DAT (C12) between a Python run
(rosters.run) and a host-binary run on two identical copies; a zero-file
comparison fails.
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
from m4 import history as history_py                     # noqa: E402
from m4 import realign                                   # noqa: E402
from m4 import teamids                                   # noqa: E402
from test_history import make_team_v20, make_maj         # noqa: E402
import team_fill                                         # noqa: E402
import maj                                               # noqa: E402
from v20 import HDR, REC, F, _set, _get                  # noqa: E402
from v20 import SIZE as V20_SIZE                         # noqa: E402

WATCOM = '/mnt/nvme/tools/openwatcom'
DOSBOX = '/mnt/nvme/src/dosbox-x/src/dosbox-x'
S1_PRE = '/mnt/nvme/tlrb2/fixtures/t4/s1_pre'
MATURE = '/mnt/nvme/tlrb2/fixtures/r3_mature'   # league + snap of a real s104 roll
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
    files always are (the run creates them), HISTORY.DAT always. The MAJ and
    TEAMID.DAT (C12) are outputs too; a file that only one side has fails parity."""
    out = {}
    out[ROSTERS_TXT] = hist_of(os.path.join(league, ROSTERS_TXT))
    for name in os.listdir(league):
        if name.upper().endswith('.MAJ') or name.upper() == teamids.TABLE_NAME:
            out[name.upper()] = hist_of(os.path.join(league, name))
            continue
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


def run_case(root, tag, seed, era, mask, fmt=None):
    """Run both implementations on identical copies; file-by-file parity.
    fmt, when given, is HISTORY byte 11 (the playoff format, C12.4) on both
    copies. Returns the Python league dir."""
    d = str(root)
    lc, ls, lh, lr = setup_case(os.path.join(d, tag + 'c'), S1_PRE, seed,
                                era, mask)
    rc_, rs, rh, rr = setup_case(os.path.join(d, tag + 'r'), S1_PRE, seed,
                                 era, mask)
    if fmt is not None:
        for hist in (lh, rh):
            raw = bytearray(open(hist, 'rb').read())
            raw[11] = fmt
            open(hist, 'wb').write(bytes(raw))
    pyc = rosters_py.run(lc, ls, lh, lr)
    assert pyc == 0, f'py rc {pyc}'
    c = HOST_RUN(rc_, rs, rh, rr)
    assert c.returncode == 0, f'{tag}: C rc {c.returncode}: {c.stderr}'
    parity(collect(lc, lh), rc_, rh)
    return lc


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

def test_statline_repair_parity(tmp_path):
    """Placeholder roster lines (a batter and a pitcher rookie in the team, pool and
    ALLSTAR images, test_rosters.rookie_league) repaired the same way by both runs."""
    from test_rosters import rookie_league
    lp = rookie_league(str(tmp_path / 'py'))
    lc = rookie_league(str(tmp_path / 'c'))
    assert rosters_py.run(*lp) == 0
    c = HOST_RUN(*lc)
    assert c.returncode == 0, f'C rc {c.returncode}: {c.stderr}'
    parity(collect(lp[0], lp[2]), lc[0], lc[2])


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


def dos_inputs(d, pre, seed, era, mask, fmt=None):
    """Build the case 1 inputs into a flat DOS dir d (8.3 names, one level):
    the rolled league V20s + MAJ + RETIRED.DAT + HISTORY.DAT. Returns
    (gold, {[stem.V20]: bytes}) with the snapshot files for a D: mount.
    fmt, when given, is HISTORY byte 11 (the playoff format, C12.4)."""
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    lc, ls, lh, lr = setup_case(os.path.join(d, '_w'), pre, seed, era, mask)
    if fmt is not None:
        raw = bytearray(open(lh, 'rb').read())
        raw[11] = fmt
        open(lh, 'wb').write(bytes(raw))
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
        if f.upper().endswith(('.V20', '.MAJ')) or f.upper() == teamids.TABLE_NAME:
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


def test_dos_format3_parity(tmp_path):
    """C12.6 step 9 under headless DOSBox-X: HISTORY byte 11 = 3 on the real fixture. The DOS run
    realigns the MAJ, creates TEAMID.DAT and commits both through REALIGN.TMP / TEAMID.TMP with every
    other output; all of them equal the Python run's."""
    if not _dos_ready():
        import pytest
        pytest.skip('ROSTERS.EXE or dosbox-x missing')
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    d = str(tmp_path)
    cd = os.path.join(d, 'dos')
    gold, ddir = dos_inputs(cd, S1_PRE, 0x1234, 0, 0, fmt=3)
    assert gold[ROSTERS_TXT].endswith(b'FORMAT 3\r\n'), 'the Python run did not realign'
    assert teamids.TABLE_NAME in gold, 'the Python run made no TEAMID.DAT'
    rc = run_dos(cd, ['ROSTERS.EXE . D: HISTORY.DAT RETIRED.DAT'], ddir)
    assert rc == 0, f'dos rc {rc}'
    out = {}
    for f in os.listdir(cd):
        if f.upper().endswith(('.V20', '.MAJ')) or f.upper() == teamids.TABLE_NAME:
            out[f.upper()] = open(os.path.join(cd, f), 'rb').read()
        assert not f.upper().endswith(('.TMP', '.BAK')), f'{f}: left behind'
    out['HISTORY.DAT'] = open(os.path.join(cd, 'HISTORY.DAT'), 'rb').read()
    out[ROSTERS_TXT] = open(os.path.join(cd, ROSTERS_TXT), 'rb').read()
    for key in sorted(gold):
        assert key in out, f'{key}: missing from the DOS output'
        compare(key, gold[key], out[key])
    assert out['CLASSIC.MAJ'][0x20d] == 3


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
        if f.upper().endswith(('.V20', '.MAJ')) or f.upper() == teamids.TABLE_NAME:
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


def test_dos_mature_league_parity(tmp_path):
    """A mature real-game league (the s104 CLASSIC roll: 570 market moves) under DOS. The 16-bit large-model build ran
    out of conventional memory here (exit 2, every file untouched); the DOS/32A build must match Python byte for byte."""
    if not _dos_ready():
        import pytest
        pytest.skip('ROSTERS.EXE or dosbox-x missing')
    if not os.path.isdir(MATURE):
        import pytest
        pytest.skip('fixtures missing')
    d = str(tmp_path)
    lc, cd, dd = (os.path.join(d, n) for n in ('py', 'dos', 'SNAP'))
    shutil.copytree(os.path.join(MATURE, 'league'), lc)
    shutil.copytree(os.path.join(MATURE, 'league'), cd)
    shutil.copytree(os.path.join(MATURE, 'snap'), dd)
    assert rosters_py.run(lc, dd, os.path.join(lc, 'HISTORY.DAT'), os.path.join(dd, 'RETIRED.DAT')) == 0
    rc = run_dos(cd, ['ROSTERS.EXE . D: HISTORY.DAT D:RETIRED.DAT'], dd)
    assert rc == 0, f'dos rc {rc}'
    names = sorted(f for f in os.listdir(lc) if f.upper().endswith('.V20')) + ['HISTORY.DAT', ROSTERS_TXT]
    assert any(n.upper().startswith('ALLSTAR') for n in names)
    for n in names:
        compare(n, open(os.path.join(lc, n), 'rb').read(), open(os.path.join(cd, n), 'rb').read())


# ---------------- test 5: playoff format (C12.3, C12.5, C12.6 step 9) ----------------

MAJ_NAME = 'CLASSIC.MAJ'
MAJ_SIZE = 59771
O_W, O_L = 0x2cb, 0x2e3              # the per-league W and L, slot-indexed (C12.1)


def _sizes(n, divs):
    """Teams per division (East, West, Central) of a league of n teams: the C12.5 generic rule."""
    if divs == 3:
        q, r = divmod(n, 3)
        return [q + (r > 0), q + (r > 1), q]
    return [(n + 1) // 2, n // 2, 0]


def fmt_maj(n_al=14, n_nl=14, divs=2):
    """A synthetic MAJ (C12.1): n_al AL and n_nl NL teams in the slots their divisions use, stems and
    abbreviations A00.. / N00.., names, the division counts and standings order 0xff (as C12.5 leaves it)."""
    d = bytearray(MAJ_SIZE)
    d[0x20c], d[0x20d] = 2, divs
    for L, n, tag in ((0, n_al, 'A'), (1, n_nl, 'N')):
        s = teamids.S[L]
        i = 0
        for dv, sz in enumerate(_sizes(n, divs)):
            d[s + 0x298 + dv] = sz
            d[0x20e + 3 * L + dv] = sz
            for j in range(sz):
                slot = dv * 8 + j
                abbr = ('%s%02d' % (tag, i)).encode()
                i += 1
                a = s + teamids.O_NAMES + 16 * slot
                d[a:a + 16] = (b'TEAM ' + abbr).ljust(16, b'\0')
                a = s + teamids.O_ABBR + 3 * slot
                d[a:a + 3] = abbr
                a = s + teamids.O_STEM + 8 * slot
                d[a:a + 8] = abbr.ljust(8, b'\0')
        d[s + 0x2b3:s + 0x2cb] = b'\xff' * 24
    return bytes(d)


def _reversed_table(maj_bytes):
    """A TEAMID.DAT whose ids run backwards in each league: not the engine ids, and every id stays in its league."""
    base = teamids.make_table(maj_bytes)
    tab = bytearray(teamids.TABLE_SIZE)
    for e in range(32):
        k = 15 - e % 16 + 16 * (e // 16)
        tab[8 * k:8 * k + 8] = base[8 * e:8 * e + 8]
    return bytes(tab)


def fmt_setup(root, maj_bytes, byte11, table, img, mask=0):
    """One side of a format test league under root: the MAJ, a team V20 (img) per MAJ team in league and snap,
    HISTORY.DAT with byte 11 and the managed mask (bytes 12..15), TEAMID.DAT when table is given, RETIRED.DAT.
    Returns (league, snap, hist, retired)."""
    league = os.path.join(root, 'league')
    snap = os.path.join(root, 'snap')
    os.makedirs(league)
    os.makedirs(snap)
    open(os.path.join(league, MAJ_NAME), 'wb').write(bytes(maj_bytes))
    for _L, _slot, st in teamids.maj_teams(maj_bytes):
        name = st.rstrip(b'\0').decode('latin-1') + '.V20'
        for dest in (league, snap):
            open(os.path.join(dest, name), 'wb').write(img)
    hist = os.path.join(root, 'HISTORY.DAT')
    h = bytearray(32)
    h[11] = byte11
    struct.pack_into('<I', h, 12, mask)
    open(hist, 'wb').write(bytes(h))
    if table is not None:
        open(os.path.join(league, teamids.TABLE_NAME), 'wb').write(bytes(table))
    retired = os.path.join(root, 'RETIRED.DAT')
    open(retired, 'wb').write(b'\x00')
    return league, snap, hist, retired


def fmt_run(tmp_path, tag, maj_bytes, byte11, table=None, mask=0):
    """ROSTERS on two identical copies of a format test league: the Python run and the C run, parity of every
    output (the MAJ and TEAMID.DAT included). Returns the Python league dir."""
    img = open(synth_league(tmp_path, sub=tag + 'img', n_players=18, pit=16)[1], 'rb').read()
    py = fmt_setup(os.path.join(str(tmp_path), tag + 'py'), maj_bytes, byte11, table, img, mask)
    cc = fmt_setup(os.path.join(str(tmp_path), tag + 'c'), maj_bytes, byte11, table, img, mask)
    assert rosters_py.run(*py) == 0
    c = HOST_RUN(*cc)
    assert c.returncode == 0, f'{tag}: C rc {c.returncode}: {c.stderr}'
    parity(collect(py[0], py[2]), cc[0], cc[2])
    return py[0]


def _read(path):
    return open(path, 'rb').read()


def test_format_three_divisions_realigns_and_writes_the_table(tmp_path):
    """C12.6 (a): byte 11 = 3 on a 14 + 14 team, 2-division league: the MAJ is realigned (0x20d 3, day 0xf3),
    TEAMID.DAT (256 B) is written from the pre-realignment MAJ, ROSTERS.TXT ends with FORMAT 3, no TMP or BAK left."""
    maj_bytes = fmt_maj(14, 14, 2)
    lp = fmt_run(tmp_path, 'a', maj_bytes, 3)
    after = _read(os.path.join(lp, MAJ_NAME))
    assert after[0x20d] == 3 and after[0x20a] == 0xf3
    assert after == realign.realign(maj_bytes, 3)[0]
    table = _read(os.path.join(lp, teamids.TABLE_NAME))
    assert len(table) == 256 and table == teamids.make_table(maj_bytes)
    assert _read(os.path.join(lp, ROSTERS_TXT)).endswith(b'FORMAT 3\r\n')
    assert not [f for f in os.listdir(lp) if f.upper().endswith(('.TMP', '.BAK'))]


def test_format_three_divisions_keeps_an_existing_table(tmp_path):
    """C12.6 (b): byte 11 = 3 with a TEAMID.DAT already there: the realignment keeps it as it is."""
    maj_bytes = fmt_maj(14, 14, 2)
    table = _reversed_table(maj_bytes)
    lp = fmt_run(tmp_path, 'b', maj_bytes, 3, table=table)
    assert _read(os.path.join(lp, teamids.TABLE_NAME)) == table
    assert _read(os.path.join(lp, MAJ_NAME))[0x20d] == 3
    assert _read(os.path.join(lp, ROSTERS_TXT)).endswith(b'FORMAT 3\r\n')


def test_format_refused_writes_the_reason_and_changes_nothing(tmp_path):
    """C12.6 (c): byte 11 = 3 on a league with an odd count (13 AL teams): FORMAT REFUSED with the Python reason,
    the MAJ unchanged, no TEAMID.DAT."""
    maj_bytes = fmt_maj(13, 14, 2)
    reason = realign.realign(maj_bytes, 3)[1]
    assert reason == 'AL ODD COUNT'
    lp = fmt_run(tmp_path, 'c', maj_bytes, 3)
    assert _read(os.path.join(lp, MAJ_NAME)) == maj_bytes
    assert not os.path.exists(os.path.join(lp, teamids.TABLE_NAME))
    assert _read(os.path.join(lp, ROSTERS_TXT)).endswith(f'FORMAT REFUSED {reason}\r\n'.encode())


def test_format_two_divisions_is_nothing_to_do(tmp_path):
    """C12.6 (d): byte 11 = 2 on a 2-division league: no FORMAT line, the MAJ unchanged, no TEAMID.DAT."""
    maj_bytes = fmt_maj(14, 14, 2)
    lp = fmt_run(tmp_path, 'd', maj_bytes, 2)
    assert _read(os.path.join(lp, MAJ_NAME)) == maj_bytes
    assert not os.path.exists(os.path.join(lp, teamids.TABLE_NAME))
    assert b'FORMAT' not in _read(os.path.join(lp, ROSTERS_TXT))


def test_three_divisions_maps_every_team_by_its_stable_id(tmp_path):
    """C12.3 (e): a 3-division MAJ with the TEAMID.DAT of its pre-realignment MAJ and byte 11 = 0: every team V20
    is mapped by its stable id (the table, not the 3-division engine ids): the managed mask and the standings are
    keyed by it, two managed teams (A07 and A08) by their ids."""
    pre = fmt_maj(14, 14, 2)
    table = teamids.make_table(pre)
    post = bytearray(realign.realign(pre, 3)[0])
    for L, slot, _st in teamids.maj_teams(bytes(post)):
        s = teamids.S[L]
        post[s + O_W + slot] = 3 * slot + 1
        post[s + O_L + slot] = 2 * slot + 5
    post = bytes(post)
    teams = teamids.teams(post, table)
    ids = sorted(k for k, _L, _s, _st in teams)
    assert ids != sorted(k for k, _L, _s, _st in teamids.teams(post, None))
    by_stem = {st.rstrip(b'\0').decode('latin-1'): k for k, _L, _s, st in teams}
    mask = (1 << by_stem['A07']) | (1 << by_stem['A08'])     # two managed teams, by stable id (bytes 12..15)
    lp = fmt_run(tmp_path, 'e', post, 0, table=table, mask=mask)
    mapped = history_py.mapped_teams(lp, maj.Maj(post))
    assert sorted(k for _p, k in mapped) == ids
    want = {k: (3 * slot + 1, 2 * slot + 5) for k, _L, slot, _st in teams}
    assert rosters_py.league_standings(maj.Maj(post), table) == want
    assert b'FORMAT' not in _read(os.path.join(lp, ROSTERS_TXT))


def test_format_commit_failure_restores_everything(tmp_path):
    """C12.6: a rename failing at the realigned MAJ's TMP (index 34: ROSTERS, 28 teams, 4 pools, HISTORY) or at
    TEAMID.DAT's (35): exit 2, and the league and snap dirs exactly as they were, no TMP or BAK left (the host build
    with TEST_FAIL_RENAME_AT=k)."""
    maj_bytes = fmt_maj(14, 14, 2)
    src = os.path.join(HERE, RC, 'rosters.c')
    img = _read(synth_league(tmp_path, sub='fimg', n_players=18, pit=16)[1])
    for k in (34, 35):
        exe = os.path.join(str(tmp_path), 'rf%d' % k)
        subprocess.run(['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror',
                        '-DTEST_FAIL_RENAME_AT=%d' % k, '-o', exe, src], check=True)
        lg, sn, hi, rt = fmt_setup(os.path.join(str(tmp_path), 'f%d' % k), maj_bytes, 3, None, img)
        before_lg, before_sn = _snapshot_tree(lg), _snapshot_tree(sn)
        r = subprocess.run([exe, lg, sn, hi, rt], capture_output=True)
        assert r.returncode == 2, (k, r.returncode)
        assert _snapshot_tree(lg) == before_lg, k
        assert _snapshot_tree(sn) == before_sn, k


def test_format_refuses_a_team_named_like_a_format_tmp(tmp_path):
    """C12.6, a deliberate divergence from Python: a team V20 named REALIGN would share the realigned MAJ's TMP
    (and BAK) name, so C exits 2 with every file as it was. Python has no such clash and realigns. Pinned here so
    the refusal is not silent; no other league is refused."""
    maj_bytes = bytearray(fmt_maj(14, 14, 2))
    s = teamids.S[0]
    maj_bytes[s + teamids.O_STEM:s + teamids.O_STEM + 8] = b'REALIGN\0'
    img = _read(synth_league(tmp_path, sub='rimg', n_players=18, pit=16)[1])
    lg, sn, hi, rt = fmt_setup(os.path.join(str(tmp_path), 'rn'), bytes(maj_bytes), 3, None, img)
    before_lg, before_sn = _snapshot_tree(lg), _snapshot_tree(sn)
    r = HOST_RUN(lg, sn, hi, rt)
    assert r.returncode == 2, r.returncode
    assert _snapshot_tree(lg) == before_lg
    assert _snapshot_tree(sn) == before_sn


def test_real_era0_three_divisions(tmp_path):
    """C12.6 on the real 1993 league: byte 11 = 3 realigns it (the known 1994 table), TEAMID.DAT (256 B) is written,
    and the C run matches Python byte for byte (the MAJ and the table included)."""
    if not os.path.isdir(S1_PRE):
        import pytest
        pytest.skip('fixtures missing')
    lc = run_case(tmp_path, 'f3_', 0x1234, 0, 0, fmt=3)
    assert _read(os.path.join(lc, ROSTERS_TXT)).endswith(b'FORMAT 3\r\n')
    assert len(_read(os.path.join(lc, teamids.TABLE_NAME))) == 256
