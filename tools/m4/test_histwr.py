#!/usr/bin/env python3
"""T4 tests: HISTWR C port of history.record_season + mark_retired (contract C5).
Run:  python3 -m pytest -q tools/m4/test_histwr.py
Host binary tools/m4/histwr/histwr_host is built at import; the DOS build test
skips when /mnt/nvme/tools/openwatcom is missing. Fixtures under /mnt/nvme skip
when missing."""
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import history
import war                                   # noqa: F401
from v20 import Team, HDR, REC, N, F, _set, _get
from v20 import SIZE as V20_SIZE
import maj
from m4.test_history import (make_team_v20, make_maj, set_player)
from m4 import dynasty_ref
from m4.test_awards import (statbat, statpit, fielding, entry_of,
                            PRE_AL, PRE_NL, GAME_REC, arr80, game, playoffs_al)

WATCOM = '/mnt/nvme/tools/openwatcom'
HERE_H = os.path.join(HERE, 'histwr')
HOST = os.path.join(HERE_H, 'histwr_host')
MS_NAME = 'MILESTON.DAT'

MAJ_SIZE = 59771
S_AL, S_NL = 0x21d, 0x758c
PLAYER_TABLE = history.PLAYER_TABLE
PLAYER_ENTRY = history.PLAYER_ENTRY


def _build():
    r = subprocess.run([sys.executable, os.path.join(HERE_H, 'build_histwr.py')],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed:\n' + r.stdout + r.stderr)
    if not os.path.exists(HOST):
        raise RuntimeError('host binary missing after build')


_build()


def HISTWR(pre, hist, retired):
    return subprocess.run([HOST, pre, hist, retired],
                          capture_output=True, text=True)


# ---------------- C5 RETIRED.DAT writer ----------------

def write_retired(path, retirees):
    """retirees: {file: [rec]} -> C5 format (13 B name + 40 B flags each)."""
    names = sorted(retirees)
    with open(path, 'wb') as f:
        f.write(bytes([len(names)]))
        for k in names:
            f.write(k.encode('latin-1').ljust(13, b'\0')[:13])
            fb = bytearray(40)
            for i in retirees[k]:
                fb[i] = 1
            f.write(bytes(fb))


# ---------------- pre-dir prep / DYNASTY header write ----------------

def prep_dir(src, dst, header):
    """Copy PRE_DIR, then simulate DYNASTY's header write (pad to 32 B, byte 0 = 1,
    bytes 1..2 = rng_end, 8..9 = start seed) on the snapshot copy."""
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    hp = os.path.join(dst, 'HISTORY.DAT')
    raw = bytearray(open(hp, 'rb').read()) if os.path.exists(hp) else bytearray()
    if len(raw) < 32:
        raw += bytes(32 - len(raw))
    raw[0] = 1
    raw[1:3] = header[1:3]
    raw[8:10] = header[8:10]
    open(hp, 'wb').write(bytes(raw))
    return dst


def dynasty_header(seed, rng_end):
    h = bytearray(10)
    h[0] = 1
    h[1:3] = struct.pack('<H', rng_end)
    h[8:10] = struct.pack('<H', seed)
    return bytes(h)


def first_diff(a, b):
    if a == b:
        return -1, -1
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i, (i - PLAYER_TABLE) // PLAYER_ENTRY
    return min(len(a), len(b)), (min(len(a), len(b)) - PLAYER_TABLE) // PLAYER_ENTRY


# ---------------- test chain (real data) ----------------

def chain(tmp_path, tag, pre_dirs, start, retire_team_filter=None):
    """start: None (no file) | 'legacy4' | 'dynasty32'. Runs the seasons in order,
    seeding the first pre-dir copies with the start state; each later season continues
    the previous season's history (the rolled V20s + the carried HISTORY.DAT)."""
    last_c = last_r = None
    for k, pre in enumerate(pre_dirs):
        seed = 0x1234 + k
        pc = prep_dir(pre, os.path.join(str(tmp_path), f'{tag}c{k}'),
                      dynasty_header(seed, seed))
        pr = prep_dir(pre, os.path.join(str(tmp_path), f'{tag}r{k}'),
                      dynasty_header(seed, seed))
        hp_c, hp_r = os.path.join(pc, 'HISTORY.DAT'), os.path.join(pr, 'HISTORY.DAT')
        if k == 0:
            apply_start(hp_c, hp_r, start)
        else:
            # season k continues season k-1: carry each side's final HISTORY.DAT,
            # then simulate DYNASTY's header write on it (rng_end = the roll's end)
            rng_end = res['rng_end']
            for hp, prev in ((hp_c, last_c), (hp_r, last_r)):
                carried = bytearray(open(prev, 'rb').read())
                carried[0] = 1
                carried[1:3] = struct.pack('<H', rng_end)
                carried[8:10] = struct.pack('<H', seed)
                open(hp, 'wb').write(bytes(carried))
        res = dynasty_ref.roll_league(pc, os.path.join(str(tmp_path), f'{tag}o{k}'),
                                      seed=seed)
        # HISTWR/record_season read the PRE-rollover V20s (pc stays stock); the
        # roll's output at {tag}o{k} is only the retiree/rng source
        ret_path = os.path.join(str(tmp_path), f'{tag}ret{k}.DAT')
        write_retired(ret_path, res['retirees'])
        py_rets = {n: idxs for n, idxs in res['retirees'].items() if idxs}
        season = history.History.load(hp_c).seasons_recorded + 1
        history.record_season(pc, hp_c, season)
        history.mark_retired(hp_c, pc, py_rets, season)
        rc = HISTWR(pr, hp_r, ret_path)
        assert rc.returncode == 0, f'{tag} season {k} rc {rc.returncode}: {rc.stderr}'
        a, b = open(hp_c, 'rb').read(), open(hp_r, 'rb').read()
        off, ent = first_diff(a, b)
        assert off < 0, f'{tag} season {season}: first diff at offset {off} (entry {ent})'
        # C7: MILESTON.DAT byte-identical too
        ms_c = os.path.join(os.path.dirname(hp_c), MS_NAME)
        ms_r = os.path.join(os.path.dirname(hp_r), MS_NAME)
        assert open(ms_c, 'rb').read() == open(ms_r, 'rb').read(), \
            f'{tag} season {season}: MILESTON.DAT differs'
        last_c, last_r = hp_c, hp_r
    h = history.History.load(last_c)
    assert h.seasons_recorded == len(pre_dirs), \
        f'{tag}: seasons recorded {h.seasons_recorded} != {len(pre_dirs)}'
    if len(pre_dirs) >= 2:
        assert any(e['seasons_played'] >= 2 for e in
                   (h.read_entry(i) for i in range(len(h._entries)))), \
            f'{tag}: no entry with seasons_played >= 2'


def apply_start(hp_c, hp_r, start):
    for hp in (hp_c, hp_r):
        if start is None:
            if os.path.exists(hp):
                os.remove(hp)
        elif start == 'legacy4':
            open(hp, 'wb').write(bytes([0, 0x39, 0x05, 0]))
        elif start == 'dynasty32':
            open(hp, 'wb').write(bytes([1]) + bytes(31))


def _real_pres():
    pres = [f'/mnt/nvme/tlrb2/fixtures/t4/s{i}_pre' for i in (1, 2, 3)]
    return [p for p in pres if os.path.isdir(p)]


def test_start_states_missing_file(tmp_path):
    pres = _real_pres()
    if not pres:
        import pytest
        pytest.skip('fixtures missing')
    chain(tmp_path, 's0_', pres, None)


def test_start_states_legacy4(tmp_path):
    pres = _real_pres()
    if not pres:
        import pytest
        pytest.skip('fixtures missing')
    chain(tmp_path, 'sl_', pres, 'legacy4')


def test_start_states_dynasty32(tmp_path):
    pres = _real_pres()
    if not pres:
        import pytest
        pytest.skip('fixtures missing')
    chain(tmp_path, 'sd_', pres, 'dynasty32')


def test_m3_end_single_season(tmp_path):
    pre = '/mnt/nvme/tlrb2/fixtures/t4/m3_end'
    if not os.path.isdir(pre):
        import pytest
        pytest.skip('fixture missing')
    chain(tmp_path, 'm3_', [pre], 'dynasty32')


def test_awards_interleaved_leagues(tmp_path):
    """Real s106 snapshot: AL and NL candidates interleave by entry index (ROSTERS
    trades, appended entries). Every AL candidate must be considered, not just the
    first n_al of the index-sorted array (dropped three AL award winners before)."""
    pre = '/mnt/nvme/tlrb2/fixtures/h6_awards'
    if not os.path.isdir(pre):
        import pytest
        pytest.skip('fixture missing')
    seed = 0x1234
    pc = prep_dir(pre, os.path.join(str(tmp_path), 'c'), dynasty_header(seed, seed))
    pr = prep_dir(pre, os.path.join(str(tmp_path), 'r'), dynasty_header(seed, seed))
    hp_c, hp_r = os.path.join(pc, 'HISTORY.DAT'), os.path.join(pr, 'HISTORY.DAT')
    res = dynasty_ref.roll_league(pc, os.path.join(str(tmp_path), 'o'), seed=seed)
    ret_path = os.path.join(str(tmp_path), 'ret.DAT')
    write_retired(ret_path, res['retirees'])
    season = history.History.load(hp_c).seasons_recorded + 1
    assert season == 3
    history.record_season(pc, hp_c, season)
    history.mark_retired(hp_c, pc, {n: i for n, i in res['retirees'].items() if i}, season)
    rc = HISTWR(pr, hp_r, ret_path)
    assert rc.returncode == 0, rc.stderr
    off, ent = first_diff(open(hp_c, 'rb').read(), open(hp_r, 'rb').read())
    assert off < 0, f'first diff at offset {off} (entry {ent})'


# ---------------- synthetic tests (test_history.py helpers) ----------------

def synth_league(tmp_path, players):
    """players = [(stem, rec_idx, name_last, name_first, age, pos1, season_kw)].
    Returns (dir, [v20 paths])."""
    ldir = os.path.join(str(tmp_path), 'lg')
    os.makedirs(ldir, exist_ok=True)
    make_maj().save(os.path.join(ldir, 'CLASSIC.MAJ'))
    for stem, i, last, first, age, pos1, kw in players:
        path = os.path.join(ldir, stem.decode('latin-1').upper() + '.V20')
        if not os.path.exists(path):
            open(path, 'wb').write(make_team_v20())
        t = Team(open(path, 'rb').read())
        set_player(t, i, last, first, age, pos1, kw.get('games', 0))
        s = t.players[i + 40].raw
        for key, val in kw.items():
            if key != 'games':
                _set(s, *F[key], val)
        t.save(path)
    return ldir


def test_duplicate_identity_merges(tmp_path):
    """Two records with the same identity (same team file) merge into one entry."""
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 20, 'BONDS', 'BARRY', 27, 7, {'games': 150, 'ab_l': 500, 'h_l': 160}),
    ])
    # second record in the same team: identical name + birth
    path = os.path.join(ldir, 'CLASALE1.V20')
    t = Team(open(path, 'rb').read())
    set_player(t, 21, 'BONDS', 'BARRY', 27, 7, 120)
    s = t.players[61].raw
    _set(s, *F['ab_l'], 400)
    _set(s, *F['h_l'], 120)
    t.save(path)
    hp = os.path.join(str(tmp_path), 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))    # 0 teams = no retirees
    rc = HISTWR(ldir, hp, ret)
    assert rc.returncode == 0, rc.stderr
    h = history.History.load(hp)
    assert len(h._entries) == 1
    e = h.read_entry(0)
    assert e['totals'][1] == 500 + 400
    # and the same via python for byte parity
    hp2 = os.path.join(str(tmp_path), 'H2.DAT')
    history.record_season(ldir, hp2, 1, None)
    a = open(hp, 'rb').read()
    b = open(hp2, 'rb').read()
    off, ent = first_diff(a, b)
    assert off < 0, f'duplicate-identity off {off} (entry {ent})'


def test_pa_zero_batter(tmp_path):
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 20, 'GLOVE', 'GARY', 30, 4, {'games': 100}),
    ])
    hp = os.path.join(str(tmp_path), 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(ldir, hp, ret)
    assert rc.returncode == 0, rc.stderr
    hp2 = os.path.join(str(tmp_path), 'H2.DAT')
    history.record_season(ldir, hp2, 1, None)
    a = open(hp, 'rb').read()
    b = open(hp2, 'rb').read()
    off, _ = first_diff(a, b)
    assert off < 0, f'pa-0 off {off}'


def test_lpa_zero_league(tmp_path):
    """Every batter is 0-pa: L_pa == 0 (no division)."""
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 20, 'BENCHY', 'BEN', 28, 4, {'games': 10}),
    ])
    hp = os.path.join(str(tmp_path), 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(ldir, hp, ret)
    assert rc.returncode == 0, rc.stderr
    hp2 = os.path.join(str(tmp_path), 'H2.DAT')
    history.record_season(ldir, hp2, 1, None)
    a = open(hp, 'rb').read()
    b = open(hp2, 'rb').read()
    off, _ = first_diff(a, b)
    assert off < 0, f'L_pa 0 off {off}'


def test_pitcher_zero_outs(tmp_path):
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 5, 'THROW', 'TOM', 26, 0, {'games': 5}),
    ])
    hp = os.path.join(str(tmp_path), 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(ldir, hp, ret)
    assert rc.returncode == 0, rc.stderr
    hp2 = os.path.join(str(tmp_path), 'H2.DAT')
    history.record_season(ldir, hp2, 1, None)
    a = open(hp, 'rb').read()
    b = open(hp2, 'rb').read()
    off, _ = first_diff(a, b)
    assert off < 0, f'pitcher-0-outs off {off}'


def test_hof_passes_big_career(tmp_path):
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 24, 'HITTER', 'HOF', 35, 5, {'games': 150, 'ab_l': 500, 'h_l': 310}),
    ])
    hp = os.path.join(str(tmp_path), 'H.DAT')
    h = history.History(None)
    # prior entry: 9 seasons played with big totals (H over the 3000 bar)
    h.version = 1
    seed_tot = [0] * 25
    seed_tot[2] = 3100
    h.append_entry({'name': b'\x01' + b'HITTER'.ljust(12, b'\0')[1:] + b'HOF'.ljust(8, b'\0'),
                    'birth': 1000 + 1 - 35, 'status': 1, 'age': 35,
                    'first_season': 1, 'last_season': 9, 'seasons_played': 9,
                    'pos1': 5, 'pitcher': 0, 'totals': seed_tot,
                    'WAR10': 400, 'top7': [90] * 7, 'JAWS10': 300, 'hof_season': 0})
    h.save(hp)
    h.save(os.path.join(str(tmp_path), 'H2.DAT'))   # same seed on the python side
    ret = os.path.join(str(tmp_path), 'R.DAT')
    # retire him this roll: flagged record 24
    write_retired(ret, {'CLASALE1.V20': [24]})
    rc = HISTWR(ldir, hp, ret)
    assert rc.returncode == 0, rc.stderr
    hp2 = os.path.join(str(tmp_path), 'H2.DAT')
    history.record_season(ldir, hp2, 1, None)
    history.mark_retired(hp2, ldir, {'CLASALE1.V20': [24]}, 1)
    a = open(hp, 'rb').read()
    b = open(hp2, 'rb').read()
    off, ent = first_diff(a, b)
    assert off < 0, f'hof off {off} (entry {ent})'
    ee = history.History.load(hp).read_entry(0)
    assert ee['status'] == history.STATUS_HOF


def test_allstar_retiree_flag_ignored(tmp_path):
    ldir = os.path.join(str(tmp_path), 'lg')
    os.makedirs(ldir)
    make_maj().save(os.path.join(ldir, 'CLASSIC.MAJ'))
    open(os.path.join(ldir, 'CLASALE1.V20'), 'wb').write(make_team_v20())
    open(os.path.join(ldir, 'ALLSTAR1.V20'), 'wb').write(make_team_v20(name=b'ALLSTARS', abbr=b'ALS'))
    m = make_maj()
    sa = S_AL + maj.O_STEM + 8 * 15
    m.d[sa:sa + 8] = b'\0' * 8
    m.save(os.path.join(ldir, 'CLASSIC.MAJ'))
    for fn, slot in (('CLASALE1.V20', 7), ('ALLSTAR1.V20', 3)):
        t = Team(open(os.path.join(ldir, fn), 'rb').read())
        set_player(t, slot, 'ROSSI', 'ROB', 29, 4, 100)
        t.save(os.path.join(ldir, fn))
    # a season with both, then RETIRED.DAT flags the ALLSTAR copy's record 3
    hp = os.path.join(str(tmp_path), 'H.DAT')
    write_retired(os.path.join(str(tmp_path), 'R.DAT'), {'CLASALE1.V20': [], 'ALLSTAR1.V20': [3]})
    rc = HISTWR(ldir, hp, os.path.join(str(tmp_path), 'R.DAT'))
    assert rc.returncode == 0, rc.stderr
    h = history.History.load(hp)
    assert h.read_entry(0)['status'] == history.STATUS_ACTIVE


def test_retired_names_missing_file(tmp_path):
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 7, 'ROSSI', 'ROB', 29, 4, {'games': 100}),
    ])
    hp = os.path.join(str(tmp_path), 'H.DAT')
    write_retired(os.path.join(str(tmp_path), 'R.DAT'), {'NOSUCH1.V20': [7]})
    rc = HISTWR(ldir, hp, os.path.join(str(tmp_path), 'R.DAT'))
    assert rc.returncode == 0, rc.stderr
    h = history.History.load(hp)
    assert h.read_entry(0)['status'] == history.STATUS_ACTIVE


def test_season_65_no_season_table_write(tmp_path):
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 21, 'VETER', 'VIC', 30, 6, {'games': 120, 'ab_l': 300, 'h_l': 90}),
    ])
    hp = os.path.join(str(tmp_path), 'H.DAT')
    h = history.History(None)
    h.version = 1
    h.seasons_recorded = 64
    h.save(hp)
    before = open(hp, 'rb').read()
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(ldir, hp, ret)
    assert rc.returncode == 0, rc.stderr
    raw = open(hp, 'rb').read()
    assert raw[32:8224] == before[32:8224]
    hh = history.History.load(hp)
    assert hh.seasons_recorded == 65
    assert len(hh._entries) == 1
    assert hh.read_entry(0)['first_season'] == 65


def test_no_maj_exit2_unchanged(tmp_path):
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 7, 'ROSSI', 'ROB', 29, 4, {'games': 100}),
    ])
    os.remove(os.path.join(ldir, 'CLASSIC.MAJ'))
    hp = os.path.join(str(tmp_path), 'H.DAT')
    open(hp, 'wb').write(bytes(range(32)))
    before = open(hp, 'rb').read()
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(ldir, hp, ret)
    assert rc.returncode == 2, rc.returncode
    assert open(hp, 'rb').read() == before
    assert not os.path.exists(os.path.join(str(tmp_path), 'HISTWR.TMP'))


def test_missing_retired_record_only(tmp_path):
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 7, 'ROSSI', 'ROB', 29, 4, {'games': 100}),
    ])
    hp = os.path.join(str(tmp_path), 'H.DAT')
    rc = HISTWR(ldir, hp, os.path.join(str(tmp_path), 'nope.DAT'))
    assert rc.returncode == 0, rc.stderr
    hp2 = os.path.join(str(tmp_path), 'H2.DAT')
    history.record_season(ldir, hp2, 1, None)
    a = open(hp, 'rb').read()
    b = open(hp2, 'rb').read()
    off, _ = first_diff(a, b)
    assert off < 0, f'record-only off {off}'


# ---------------- DOS build ----------------

def test_dos_build():
    exe = os.path.join(HERE_H, 'HISTWR.EXE')
    exe2 = os.path.join(HERE_H, 'HISTWR2.EXE')
    if not os.path.isdir(WATCOM):
        if os.path.exists(exe2):
            os.remove(exe2)
        import pytest
        pytest.skip('OpenWatcom missing')
    for p in (exe, exe2):
        if os.path.exists(p):
            os.remove(p)
    r = subprocess.run(
        ['python3', os.path.join(HERE_H, 'build_histwr.py')],
        cwd=HERE_H, capture_output=True, text=True)
    if not os.path.isdir(WATCOM):
        assert not os.path.exists(exe), 'HISTWR.EXE built without OpenWatcom'
        import pytest
        pytest.skip('OpenWatcom missing')
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.exists(exe), 'HISTWR.EXE not built'
    with open(exe, 'rb') as f:
        assert f.read(2) == b'MZ'
    # second build is byte-identical
    r2 = subprocess.run(
        [sys.executable, os.path.join(HERE_H, 'build_histwr.py')],
        cwd=HERE_H, capture_output=True, text=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    shutil.copy2(exe, exe2)
    r3 = subprocess.run(
        [sys.executable, os.path.join(HERE_H, 'build_histwr.py')],
        cwd=HERE_H, capture_output=True, text=True)
    assert r3.returncode == 0, r3.stdout + r3.stderr
    assert open(exe, 'rb').read() == open(exe2, 'rb').read()
    os.remove(exe2)


# ---------------- real-DOS parity (dosbox-x) ----------------

DOSBOX = '/mnt/nvme/src/dosbox-x/src/dosbox-x'


def _dos_ready():
    return (os.path.exists(os.path.join(HERE_H, 'HISTWR.EXE'))
            and os.path.isfile(DOSBOX) and os.access(DOSBOX, os.X_OK))


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
    ':end',
]


def run_dos(cdir, bat_lines):
    """Write cdir/RUN.BAT (CRLF), run it under dosbox-x, return int(RC.TXT)."""
    shutil.copy2(os.path.join(HERE_H, 'HISTWR.EXE'), os.path.join(cdir, 'HISTWR.EXE'))
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
    proc = subprocess.run(
        [DOSBOX, '-silent', '-set', 'mixer nosound=true', '-set', 'cpu cycles=max',
         '-c', 'mount c ' + cdir, '-c', 'c:', '-c', 'RUN.BAT', '-c', 'exit'],
        capture_output=True, text=True, timeout=120, env=env)
    if not os.path.exists(rc_txt):
        raise AssertionError(f'RC.TXT missing rc={proc.returncode} '
                             f'out={proc.stdout[-400:]} err={proc.stderr[-400:]}')
    return int(open(rc_txt).read().strip() or 0)


def test_dos_no_maj(tmp_path):
    """No MAJ in C:\\PRE: exit 2 under DOS, HIST.DAT byte-identical to before."""
    if not _dos_ready():
        import pytest
        pytest.skip('HISTWR.EXE or dosbox-x missing')
    pre = os.path.join(str(tmp_path), 'pre')
    os.makedirs(pre)
    hist = os.path.join(pre, 'HIST.DAT')
    open(hist, 'wb').write(bytes(range(32)))
    before = open(hist, 'rb').read()
    open(os.path.join(pre, 'RET.DAT'), 'wb').write(bytes(1))
    rc = run_dos(pre, ['HISTWR.EXE . HIST.DAT RET.DAT'])
    assert rc == 2, rc
    assert open(hist, 'rb').read() == before


def test_dos_chain_parity(tmp_path):
    """First two real-data seasons: host on one copy, HISTWR.EXE under DOS on the
    other; byte equality after each season."""
    if not _dos_ready():
        import pytest
        pytest.skip('HISTWR.EXE or dosbox-x missing')
    pres = _real_pres()[:2]
    if len(pres) < 2:
        import pytest
        pytest.skip('fixtures missing')
    d = str(tmp_path)
    dc = os.path.join(d, 'dosc')       # pre dir mounted as C: in dosbox
    last_c = last_d = None
    for k, pre in enumerate(pres):
        seed = 0x1234 + k
        pc = prep_dir(pre, os.path.join(d, f'hc{k}'), dynasty_header(seed, seed))
        dc = prep_dir(pre, os.path.join(d, f'dc{k}'), dynasty_header(seed, seed))
        hp_c, hp_d = os.path.join(pc, 'HISTORY.DAT'), os.path.join(dc, 'HISTORY.DAT')
        if k == 0:
            apply_start(hp_c, hp_d, 'dynasty32')
        else:
            rng_end = res['rng_end']
            for hp, prev in ((hp_c, last_c), (hp_d, last_d)):
                carried = bytearray(open(prev, 'rb').read())
                carried[0] = 1
                carried[1:3] = struct.pack('<H', rng_end)
                carried[8:10] = struct.pack('<H', seed)
                open(hp, 'wb').write(bytes(carried))
        res = dynasty_ref.roll_league(pc, os.path.join(d, f'ho{k}'), seed=seed)
        ret_path = os.path.join(d, f'ret{k}.DAT')
        write_retired(ret_path, res['retirees'])
        ret_dos = os.path.join(dc, 'RET.DAT')
        shutil.copy2(ret_path, ret_dos)
        py_rets = {n: idxs for n, idxs in res['retirees'].items() if idxs}
        season = history.History.load(hp_c).seasons_recorded + 1
        history.record_season(pc, hp_c, season)
        history.mark_retired(hp_c, pc, py_rets, season)
        rc = run_dos(dc, ['HISTWR.EXE . HISTORY.DAT RET.DAT'])
        assert rc == 0, f'season {k} dos rc {rc}'
        a = open(hp_c, 'rb').read()
        b = open(hp_d, 'rb').read()
        off, ent = first_diff(a, b)
        assert off < 0, f'dos season {season}: first diff at offset {off} (entry {ent})'
        # C7: MILESTON.DAT byte-identical too
        ms_c = os.path.join(pc, MS_NAME)
        ms_d = os.path.join(dc, MS_NAME)
        assert open(ms_c, 'rb').read() == open(ms_d, 'rb').read(), \
            f'dos season {season}: MILESTON.DAT differs'
        last_c, last_d = hp_c, hp_d


def test_dos_defaults(tmp_path):
    """No args: C:\\DYNSNAP = copy of s1_pre plus RETIRED.DAT, no C:\\TEAMS\\CLASSIC
    HISTORY.DAT; HISTWR.EXE exits 0 and C:\\TEAMS\\CLASSIC\\HISTORY.DAT equals the
    host run on the same inputs."""
    if not _dos_ready():
        import pytest
        pytest.skip('HISTWR.EXE or dosbox-x missing')
    pre = '/mnt/nvme/tlrb2/fixtures/t4/s1_pre'
    if not os.path.isdir(pre):
        import pytest
        pytest.skip('fixture missing')
    d = str(tmp_path)
    cd = os.path.join(d, 'cd')     # this becomes C: in dosbox
    os.makedirs(cd)
    # C:\DYNSNAP = copy of s1_pre + RETIRED.DAT
    snap = os.path.join(cd, 'DYNSNAP')
    shutil.copytree(pre, snap)
    open(os.path.join(snap, 'HISTORY.DAT'), 'wb').write(bytes([1]) + bytes(31))
    seed = 0x1234
    res = dynasty_ref.roll_league(snap, os.path.join(d, 'o'), seed=seed)
    write_retired(os.path.join(snap, 'RETIRED.DAT'), res['retirees'])
    # C:\TEAMS\CLASSIC: HISTORY.DAT absent (the dir exists)
    os.makedirs(os.path.join(cd, 'TEAMS', 'CLASSIC'), exist_ok=True)
    py_rets = {n: idxs for n, idxs in res['retirees'].items() if idxs}
    # host reference on its own copy of the same inputs
    hc = os.path.join(d, 'host')
    shutil.copytree(snap, hc)
    shutil.rmtree(os.path.join(hc, 'TEAMS'), ignore_errors=True)
    hp_h = os.path.join(hc, 'TEAMS', 'CLASSIC', 'HISTORY.DAT')
    os.makedirs(os.path.dirname(hp_h), exist_ok=True)
    season = history.History.load(os.path.join(snap, 'HISTORY.DAT')).seasons_recorded + 1
    HISTWR(hc, hp_h, os.path.join(hc, 'RETIRED.DAT'))
    history.mark_retired(hp_h, hc, py_rets, season)
    rc = run_dos(cd, ['HISTWR.EXE'])
    assert rc == 0, rc
    hp_c = os.path.join(cd, 'TEAMS', 'CLASSIC', 'HISTORY.DAT')
    assert os.path.exists(hp_c), 'no HISTORY.DAT produced'
    a = open(hp_h, 'rb').read()
    b = open(hp_c, 'rb').read()
    off, ent = first_diff(a, b)
    assert off < 0, f'dos defaults: first diff at offset {off} (entry {ent})'


# ---------------- round 3: argv fit, champion >= 32, rename failure ----------------

HOST_2 = os.path.join(HERE_H, 'histwr_host_2')
HC = os.path.join(HERE_H, 'histwr_host_failrename')


def _build_special(out, flags):
    r = subprocess.run(['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror']
                       + flags + ['-o', out, 'histwr.c'],
                       cwd=HERE_H, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_long_retired_path_rc2(tmp_path):
    """A 700-char RETIRED path: rc 2, HIST_PATH byte-identical (host build)."""
    _build()
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 7, 'ROSSI', 'ROB', 29, 4, {'games': 100}),
    ])
    hp = os.path.join(str(tmp_path), 'H.DAT')
    open(hp, 'wb').write(bytes(range(32)))
    before = open(hp, 'rb').read()
    ret = os.path.join(str(tmp_path), 'R' + 'x' * 700 + '.DAT')
    rc = HISTWR(ldir, hp, ret)
    assert rc.returncode == 2, rc.returncode
    assert open(hp, 'rb').read() == before


def test_champion_over_31_unknown(tmp_path):
    """MAJ WS byte 40 (>= 32): champion 0xff, runner 0xff, empty stems; host and
    Python byte-identical."""
    _build()
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 21, 'VETER', 'VIC', 30, 6, {'games': 120, 'ab_l': 300, 'h_l': 90}),
    ])
    # patch the MAJ copy's WS byte to 40
    d = bytearray(open(os.path.join(ldir, 'CLASSIC.MAJ'), 'rb').read())
    d[S_AL + 0x3da] = 40
    open(os.path.join(ldir, 'CLASSIC.MAJ'), 'wb').write(bytes(d))
    hp = os.path.join(str(tmp_path), 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(ldir, hp, ret)
    assert rc.returncode == 0, rc.stderr
    h = history.History.load(hp)
    s = h.read_season_entry(1)
    assert s['champion'] == 0xff and s['runner_up'] == 0xff
    assert s['champion_stem'] == b'' and s['runner_up_stem'] == b''
    # parity with Python
    hp2 = os.path.join(str(tmp_path), 'H2.DAT')
    history.record_season(ldir, hp2, 1, None)
    a = open(hp, 'rb').read()
    b = open(hp2, 'rb').read()
    off, ent = first_diff(a, b)
    assert off < 0, f'champion>=32 off {off} (entry {ent})'


def test_champion_ws_wins_decide(tmp_path):
    """WS winner comes from the series wins (AL S+0x3e1 vs S+0x3e2), not from the
    S+0x3da slot: AL pennant team 0 wins 4-2 -> champion 0, runner-up the NL team;
    host and Python byte-identical."""
    _build()
    ldir = synth_league(str(tmp_path), [
        (b'CLASALE1', 21, 'VETER', 'VIC', 30, 6, {'games': 120, 'ab_l': 300, 'h_l': 90}),
    ])
    d = bytearray(open(os.path.join(ldir, 'CLASSIC.MAJ'), 'rb').read())
    d[S_AL + 0x3d9] = 0
    d[S_AL + 0x3da] = 16
    d[S_NL + 0x3d9] = 16
    d[S_AL + 0x3e1] = 4
    d[S_AL + 0x3e2] = 2
    open(os.path.join(ldir, 'CLASSIC.MAJ'), 'wb').write(bytes(d))
    hp = os.path.join(str(tmp_path), 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(ldir, hp, ret)
    assert rc.returncode == 0, rc.stderr
    s = history.History.load(hp).read_season_entry(1)
    assert s['champion'] == 0 and s['runner_up'] == 16
    hp2 = os.path.join(str(tmp_path), 'H2.DAT')
    history.record_season(ldir, hp2, 1, None)
    off, ent = first_diff(open(hp, 'rb').read(), open(hp2, 'rb').read())
    assert off < 0, f'ws wins off {off} (entry {ent})'


def test_fail_rename_keeps_hist(tmp_path):
    """Second-rename failure: rc 2, HIST byte-identical, no BAK/TMP left (a host
    build with -DTEST_FAIL_RENAME forces the swap's second rename to fail)."""
    _build()
    _build_special(HC, ['-DTEST_FAIL_RENAME'])
    try:
        ldir = synth_league(str(tmp_path), [
            (b'CLASALE1', 7, 'ROSSI', 'ROB', 29, 4, {'games': 100}),
        ])
        hp = os.path.join(str(tmp_path), 'H.DAT')
        open(hp, 'wb').write(bytes(range(32)))
        before = open(hp, 'rb').read()
        ret = os.path.join(str(tmp_path), 'R.DAT')
        open(ret, 'wb').write(bytes(1))
        rc = subprocess.run([HC, ldir, hp, ret], capture_output=True, text=True)
        assert rc.returncode == 2, rc.returncode
        assert open(hp, 'rb').read() == before, 'HIST not restored'
        assert not os.path.exists(os.path.join(str(tmp_path), 'HISTWR.BAK')), 'BAK left'
        assert not os.path.exists(os.path.join(str(tmp_path), 'HISTWR.TMP')), 'TMP left'
    finally:
        if os.path.exists(HC):
            os.remove(HC)


# ---------------- round 4: C7 awards and milestones ----------------

def ms_path_of(hp):
    return os.path.join(os.path.dirname(hp), MS_NAME)


def test_awards_synthetic_league_host(tmp_path):
    """The A1 synthetic award league through the host binary: same HISTORY.DAT
    and MILESTON.DAT as the Python reference (award winners, career counts,
    season entry 88..99)."""
    _build()
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    (ldir / PRE_AL).write_bytes(make_team_v20())
    (ldir / PRE_NL).write_bytes(make_team_v20(name=b'NLONE', abbr=b'NL1'))
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    ta = Team(open(str(ldir / PRE_AL), 'rb').read())
    set_player(ta, 16, 'MVPWIN', 'AL', 27, 7, 155)      # CF, pa 512, big WAR
    statbat(ta, 16, 450, 150, d2=30, t3=5, hr=25, bb=62, sb=30, runs=100,
            games=155)
    fielding(ta, 16, 300, 20, 5)
    set_player(ta, 17, 'TIELO', 'LOWIDX', 27, 3, 150)   # 2B, ties with TIEHI
    statbat(ta, 17, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
    fielding(ta, 17, 250, 200, 6)
    set_player(ta, 18, 'TIEHI', 'HIGHIDX', 27, 3, 150)  # same pos, same line
    statbat(ta, 18, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
    fielding(ta, 18, 250, 200, 6)
    set_player(ta, 19, 'SOPH', 'NOTROOK', 22, 9, 162)   # DH, exp 1: no ROY
    ta.players[19]['exp'] = 1
    statbat(ta, 19, 500, 200, hr=40, bb=60, rbi=110, runs=120, games=162)
    set_player(ta, 20, 'SSBAT', 'SHORTPA', 28, 5, 150)  # SS pa 200: under 300
    statbat(ta, 20, 190, 60, bb=10, runs=30, games=150)
    set_player(ta, 21, 'FROSH', 'KID', 21, 4, 100)      # 3B rookie, exp 0
    statbat(ta, 21, 150, 48, hr=15, bb=20, rbi=50, runs=40, games=100)
    set_player(ta, 0, 'CYFALL', 'FALLBACK', 26, 0, 25)  # P A: 162 outs < 486
    ta.players[0]['exp'] = 1
    statpit(ta, 0, 540, 60, w=10, pso=100, games=25)
    set_player(ta, 1, 'CYFALL2', 'FALLBK2', 26, 0, 20)  # P B: 300 outs, better
    ta.players[1]['exp'] = 1
    statpit(ta, 1, 1000, 30, w=8, pso=80, games=20)
    for i in (16, 17, 18, 20):
        ta.players[i]['exp'] = 1
    ta.save(str(ldir / PRE_AL))
    tn = Team(open(str(ldir / PRE_NL), 'rb').read())
    set_player(tn, 16, 'CATCHER', 'GLOVE', 28, 1, 95)   # C at 95 games (>= 90)
    tn.players[16]['exp'] = 1
    statbat(tn, 16, 320, 90, hr=10, bb=30, rbi=45, runs=40, games=95)
    fielding(tn, 16, 700, 60, 8)
    set_player(tn, 17, 'NLDH', 'DESIG', 29, 9, 150)     # NL DH: MVP + SS(9)
    tn.players[17]['exp'] = 1
    statbat(tn, 17, 550, 180, hr=30, bb=70, rbi=105, runs=110, games=150)
    tn.save(str(ldir / PRE_NL))
    hp = os.path.join(str(tmp_path), 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(str(ldir), hp, ret)
    assert rc.returncode == 0, rc.stderr
    hp2 = os.path.join(str(tmp_path), 'H2.DAT')
    history.record_season(str(ldir), hp2, 1, None)
    a = open(hp, 'rb').read()
    b = open(hp2, 'rb').read()
    off, ent = first_diff(a, b)
    assert off < 0, f'award league off {off} (entry {ent})'
    assert open(ms_path_of(hp), 'rb').read() == open(ms_path_of(hp2), 'rb').read()
    # sanity: the winners landed (season entry 88..99 not all none)
    h = history.History.load(hp2)
    aw = h.read_season_entry(1)['awards']
    assert aw[0] != history.NO_AWARD and aw[1] != history.NO_AWARD
    assert aw[2] != history.NO_AWARD and aw[3] != history.NO_AWARD
    assert aw[4] == history.NO_AWARD and aw[5] == history.NO_AWARD


def test_fail_rename_keeps_both(tmp_path):
    """Second-rename failure with an old MILESTON.DAT present: rc 2, HISTORY.DAT
    AND MILESTON.DAT both byte-identical, no TMP/BAK left."""
    _build()
    _build_special(HC, ['-DTEST_FAIL_RENAME'])
    try:
        ldir = synth_league(str(tmp_path), [
            (b'CLASALE1', 7, 'ROSSI', 'ROB', 29, 4, {'games': 100}),
        ])
        hp = os.path.join(str(tmp_path), 'H.DAT')
        open(hp, 'wb').write(bytes(range(32)))
        before = open(hp, 'rb').read()
        ms = ms_path_of(hp)
        open(ms, 'wb').write(bytes([1, 0, 0, 0, 40, 0, 5, 0]))
        ms_before = open(ms, 'rb').read()
        ret = os.path.join(str(tmp_path), 'R.DAT')
        open(ret, 'wb').write(bytes(1))
        rc = subprocess.run([HC, ldir, hp, ret], capture_output=True, text=True)
        assert rc.returncode == 2, rc.returncode
        assert open(hp, 'rb').read() == before, 'HIST not restored'
        assert open(ms, 'rb').read() == ms_before, 'MILESTON not restored'
        for leftover in ('HISTWR.BAK', 'HISTWR.TMP', 'MILESTON.BAK',
                         'MILESTON.TMP'):
            assert not os.path.exists(os.path.join(str(tmp_path), leftover)), \
                f'{leftover} left'
    finally:
        if os.path.exists(HC):
            os.remove(HC)


def test_milestone_rerun_idempotent(tmp_path):
    """Running the same season twice on copies gives identical MILESTON.DAT
    (drop-then-append)."""
    _build()
    ldir = synth_league(str(tmp_path / 'in'), [
        (b'CLASALE1', 16, 'MILER', 'RUN', 26, 7, {'games': 150, 'ab_l': 550,
         'h_l': 200, 'hr_l': 55, 'rbi': 120}),
    ])
    outs = []
    for tag in ('a', 'b'):
        d = str(tmp_path / tag)
        shutil.copytree(ldir, d)
        hp = os.path.join(d, 'H.DAT')
        ret = os.path.join(d, 'R.DAT')
        open(ret, 'wb').write(bytes(1))
        rc = HISTWR(d, hp, ret)
        assert rc.returncode == 0, rc.stderr
        outs.append(open(ms_path_of(hp), 'rb').read())
    assert outs[0] == outs[1]
    assert len(outs[0]) > 0, 'no milestone records written'


def full_award_league(ldir):
    """AL on CLASALE1, NL on NL01. Each league: a pitcher (slot 0, 540 outs, exp 1), a
    regular at every position 1..8 (slots 1..8: pa 550, games 150, exp 1) and, as the
    position 6 regular, an exp-0 rookie (slot 6). The AL rookie hits poorly (negative WAR10
    and bat100, so his ROY and SS(6) values are negative); the AL adds a DH (slot 9). Every
    award has a winner: AL 20 records, NL 19 (no DH Silver Slugger). The first name carries
    the league: byte 0 of the name is the active flag, so the last names alone would collide
    across the two files (one identity, merged entries)."""
    make_maj().save(os.path.join(ldir, 'CLASSIC.MAJ'))
    for stem, pre, dh in ((PRE_AL, 'AL', True), (PRE_NL, 'NL', False)):
        path = os.path.join(ldir, stem)
        open(path, 'wb').write(make_team_v20())
        t = Team(open(path, 'rb').read())
        set_player(t, 0, 'ACE', pre, 27, 0, 30)
        t.players[0]['exp'] = 1
        statpit(t, 0, 1800, 40, w=15, pso=200, games=30)
        for q in range(1, 9):
            set_player(t, q, 'REG%d' % q, pre, 27, q, 150)
            t.players[q]['exp'] = 1
            statbat(t, q, 500, 150, d2=30, hr=20, bb=50, runs=90, games=150)
            fielding(t, q, 200 + 7 * q, 120 + q, 2 + q)
        set_player(t, 6, 'ROOK', pre, 22, 6, 130)
        t.players[6]['exp'] = 0
        if pre == 'AL':
            statbat(t, 6, 300, 30, bb=5, games=130, runs=10)
            fielding(t, 6, 50, 2, 9)
        else:
            statbat(t, 6, 500, 150, d2=30, hr=20, bb=50, runs=90, games=150)
            fielding(t, 6, 200 + 42, 126, 8)
        if dh:
            set_player(t, 9, 'DESIG', pre, 29, 9, 150)
            t.players[9]['exp'] = 1
            statbat(t, 9, 500, 150, hr=30, bb=50, runs=100, games=150)
        t.save(path)


def test_award_records_host_full_league(tmp_path):
    """HISTWR on a league with a Gold Glove at every position 1..8 and an AL DH Silver
    Slugger (no NL DH): MILESTON.DAT equals the Python reference byte for byte; the AL
    block (kinds 64..83) has 20 records and the NL block (96..115) has 19. Each side runs in
    its own directory (the MILESTON.DAT path is beside HISTORY.DAT)."""
    _build()
    ldir = str(tmp_path / 'lg')
    os.makedirs(ldir)
    full_award_league(ldir)
    host_dir, py_dir = str(tmp_path / 'host'), str(tmp_path / 'py')
    for d in (host_dir, py_dir):
        shutil.copytree(ldir, d)
    hp = os.path.join(host_dir, 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(host_dir, hp, ret)
    assert rc.returncode == 0, rc.stderr
    hp2 = os.path.join(py_dir, 'H.DAT')
    history.record_season(py_dir, hp2, 1, None)
    off, ent = first_diff(open(hp, 'rb').read(), open(hp2, 'rb').read())
    assert off < 0, f'full league off {off} (entry {ent})'
    ms_host = open(ms_path_of(hp), 'rb').read()
    assert ms_host == open(ms_path_of(hp2), 'rb').read(), 'MILESTON.DAT differs'
    ms = history.milestone_entries(hp2)
    assert sum(1 for r in ms if 64 <= r[2] < 96) == 20
    assert sum(1 for r in ms if 96 <= r[2] < 128) == 19
    # the negative AL ROY value (WAR10 < 0) is stored as u16 by both writers
    assert any(r[2] == 66 and r[3] >= 0x8000 for r in ms)


def test_leader_records_host_hr_tie_no_era(tmp_path):
    """C7 leader records, season 2 on a season-1 HISTORY.DAT, host binary against the Python
    reference byte for byte. AL: RETURNR (entry 0, from season 1) sits on the LATER team file
    and ties FILEROOK (appended in season 2, first in file order) at 347 BA, 40 HR and 160 H;
    the lower entry index wins each tie. The AL pitcher has 30 outs and the NL has no pitcher,
    so no ERA leader; NLBAT has pa 440, so no NL BA leader."""
    _build()
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    make_maj().save(str(ldir / 'CLASSIC.MAJ'))
    p1, p2, pn = str(ldir / PRE_AL), str(ldir / 'ALA02.V20'), str(ldir / PRE_NL)
    open(p2, 'wb').write(make_team_v20())
    t = Team(open(p2, 'rb').read())
    set_player(t, 17, 'RETURNR', 'REX', 27, 3, 150)
    statbat(t, 17, 460, 160, d2=35, hr=20, bb=50, runs=95, games=150)
    t.save(p2)
    s1 = os.path.join(str(tmp_path), 's1')
    os.makedirs(s1)
    history.record_season(str(ldir), os.path.join(s1, 'HISTORY.DAT'), 1)
    # season 2
    t = Team(open(p2, 'rb').read())
    set_player(t, 17, 'RETURNR', 'REX', 28, 3, 150)
    statbat(t, 17, 460, 160, d2=35, hr=40, bb=50, runs=95, games=150)
    t.save(p2)
    open(p1, 'wb').write(make_team_v20())
    t1 = Team(open(p1, 'rb').read())
    set_player(t1, 0, 'SHORTP', 'ART', 26, 0, 10)
    statpit(t1, 0, 100, 0, games=10)                    # 30 outs: no ERA qualifier
    set_player(t1, 16, 'FILEROOK', 'FRED', 21, 3, 150)
    statbat(t1, 16, 460, 160, d2=35, hr=40, bb=50, runs=95, games=150)
    t1.save(p1)
    open(pn, 'wb').write(make_team_v20(name=b'NLONE', abbr=b'NL1'))
    tn = Team(open(pn, 'rb').read())
    set_player(tn, 16, 'NLBAT', 'NELL', 28, 3, 150)
    statbat(tn, 16, 400, 120, hr=10, bb=40, games=150)  # pa 440: no BA leader
    tn.save(pn)
    hs, py = os.path.join(str(tmp_path), 'host'), os.path.join(str(tmp_path), 'py')
    shutil.copytree(s1, hs)
    shutil.copytree(s1, py)
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(str(ldir), os.path.join(hs, 'HISTORY.DAT'), ret)
    assert rc.returncode == 0, rc.stderr
    history.record_season(str(ldir), os.path.join(py, 'HISTORY.DAT'), 2)
    off, ent = first_diff(open(os.path.join(hs, 'HISTORY.DAT'), 'rb').read(),
                          open(os.path.join(py, 'HISTORY.DAT'), 'rb').read())
    assert off < 0, f'leader league off {off} (entry {ent})'
    ms_py = open(os.path.join(py, MS_NAME), 'rb').read()
    assert open(os.path.join(hs, MS_NAME), 'rb').read() == ms_py, 'MILESTON.DAT differs'
    h = history.History.load(os.path.join(py, 'HISTORY.DAT'))
    ret_idx = entry_of(h, t, 17, 2)
    fileroo = entry_of(h, t1, 16, 2)
    nlbat = entry_of(h, tn, 16, 2)
    assert ret_idx < fileroo                            # the tie: lower index RETURNR
    got = [r for r in history.milestone_entries(os.path.join(py, MS_NAME))
           if r[0] == 2 and 128 <= r[2] < 176]
    assert got == [(2, ret_idx, 128, 347), (2, ret_idx, 129, 40), (2, ret_idx, 131, 160),
                   (2, nlbat, 161, 10), (2, nlbat, 163, 120)]


# ---------------- round 5: second season under DOS (MILESTON.DAT already present) ----------------

def test_dos_second_season_existing_milestones(tmp_path):
    """Season 2 under real DOS with TEAMS\\CLASSIC\\HISTORY.DAT and MILESTON.DAT already present (season 1
    written by the host build). DOS rename never overwrites, so the MILESTON BAK step must move the old file
    aside; regression for the 5-season gate failure (bak_of got sizeof a pointer). Output equals the host."""
    if not _dos_ready():
        import pytest
        pytest.skip('HISTWR.EXE or dosbox-x missing')
    pre = '/mnt/nvme/tlrb2/fixtures/t4/s1_pre'
    if not os.path.isdir(pre):
        import pytest
        pytest.skip('fixture missing')
    _build()
    d = str(tmp_path)
    cd = os.path.join(d, 'cd')
    snap = os.path.join(cd, 'DYNSNAP')
    shutil.copytree(pre, snap)
    open(os.path.join(snap, 'HISTORY.DAT'), 'wb').write(bytes([1]) + bytes(31))
    res = dynasty_ref.roll_league(snap, os.path.join(d, 'o'), seed=0x1234)
    write_retired(os.path.join(snap, 'RETIRED.DAT'), res['retirees'])
    lg = os.path.join(cd, 'TEAMS', 'CLASSIC')
    os.makedirs(lg)
    # season 1 by the host build into the league dir
    r = HISTWR(snap, os.path.join(lg, 'HISTORY.DAT'), os.path.join(snap, 'RETIRED.DAT'))
    assert r.returncode == 0, r.stderr
    ms = os.path.join(lg, 'MILESTON.DAT')
    if not os.path.exists(ms):
        open(ms, 'wb').close()
    # host reference for season 2 on its own copy
    hc = os.path.join(d, 'host')
    shutil.copytree(lg, hc)
    r = HISTWR(snap, os.path.join(hc, 'HISTORY.DAT'), os.path.join(snap, 'RETIRED.DAT'))
    assert r.returncode == 0, r.stderr
    rc = run_dos(cd, ['HISTWR.EXE'])
    assert rc == 0, rc
    for leaf in ('HISTORY.DAT', 'MILESTON.DAT'):
        a = open(os.path.join(hc, leaf), 'rb').read()
        b = open(os.path.join(lg, leaf), 'rb').read()
        off, ent = first_diff(a, b)
        assert off < 0, f'{leaf}: first diff at offset {off} (entry {ent})'
    assert history.History.load(os.path.join(lg, 'HISTORY.DAT')).seasons_recorded == 2
    left = [n for n in os.listdir(lg) if n.upper().endswith(('.BAK', '.TMP'))]
    assert not left, left


# ---------------- C7 World Series records (PLAYOFFS.AL) ----------------

def series_parity(tmp_path, po):
    """HISTWR and the Python reference on full_award_league with the PLAYOFFS.AL bytes po:
    HISTORY.DAT and MILESTON.DAT equal byte for byte. Returns the reference MILESTON.DAT."""
    _build()
    ldir = str(tmp_path / 'lg')
    os.makedirs(ldir)
    full_award_league(ldir)
    open(os.path.join(ldir, 'PLAYOFFS.AL'), 'wb').write(po)
    host_dir, py_dir = str(tmp_path / 'host'), str(tmp_path / 'py')
    for d in (host_dir, py_dir):
        shutil.copytree(ldir, d)
    hp = os.path.join(host_dir, 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    rc = HISTWR(host_dir, hp, ret)
    assert rc.returncode == 0, rc.stderr
    hp2 = os.path.join(py_dir, 'H.DAT')
    history.record_season(py_dir, hp2, 1, None)
    off, ent = first_diff(open(hp, 'rb').read(), open(hp2, 'rb').read())
    assert off < 0, f'HISTORY.DAT off {off} (entry {ent})'
    assert open(ms_path_of(hp), 'rb').read() == open(ms_path_of(hp2), 'rb').read(), \
        'MILESTON.DAT differs'
    return history.milestone_entries(hp2)


def test_series_host_parity_seven_games(tmp_path):
    """A 7 game PLAYOFFS.AL with one skipped game (an unmapped visitor stem): HISTWR matches
    the Python reference byte for byte, and the six kept games write kinds 192 + g and
    200 + g with their own g (no 193 or 201)."""
    po = playoffs_al([
        game(b'ALA01', b'NL00', 3, 5, hits=(arr80(4, 3), arr80(10)), errs=(arr80(1), arr80(0, 2))),
        game(b'XYZ', b'NL00', 1, 1),                      # skipped
        game(b'NL01', b'ALA01', 255, 1, hits=(arr80(200, 100), arr80(255)),
             errs=(arr80(2), arr80(3))),
        game(b'clasale1', b'NL01', 2, 6, hits=(arr80(5, 2), arr80(9)), errs=(arr80(1), arr80(0, 3))),
        game(b'NL00', b'ALA13', 9, 9, hits=(arr80(9), arr80(9)), errs=(arr80(4), arr80(4))),
        game(b'AlA02', b'nl05', 1, 0, hits=(arr80(5), arr80(5)), errs=(arr80(), arr80())),
        game(b'NL01', b'ALA03', 2, 4, hits=(arr80(60, 60, 60, 60, 60), arr80(100)),
             errs=(arr80(0), arr80(1))),
    ])
    ms = series_parity(tmp_path, po)
    series = [r for r in ms if 192 <= r[2] <= 207]
    assert [r[2] for r in series] == [192, 200, 194, 202, 195, 203, 196, 204, 197, 205,
                                      198, 206]
    assert len(series) == 12


def test_series_host_parity_short_file(tmp_path):
    """A PLAYOFFS.AL with n = 3 one byte under 1 + 7446 * 3: no World Series records, the
    leader and award records are still written, and HISTWR matches the reference."""
    po = playoffs_al([game(b'ALA01', b'NL00', 3, 5), game(b'NL01', b'ALA02', 1, 2),
                      game(b'ALA03', b'NL03', 4, 4)])
    ms = series_parity(tmp_path, po[:1 + GAME_REC * 3 - 1])
    assert not any(192 <= r[2] <= 207 for r in ms)
    assert any(128 <= r[2] < 176 for r in ms) and any(64 <= r[2] < 128 for r in ms)


# ---------------- C7 box scores (BOXSCORE.DAT, fourth amendment) ----------------

def box_seven_games():
    """A 7 game PLAYOFFS.AL on full_award_league (AL clasale1 = team 0, NL01 = team 17). Game 1 is
    skipped (unmapped visitor stem). The AL ace (record 0) is a slot 9 pitcher only (IP 3.0). Teams
    2, 3, 13, 16 and 21 are on the MAJ but have no V20 here, so their rows carry NO_ENTRY."""
    return playoffs_al([
        game(b'clasale1', b'NL01', 3, 5, box=[
            {'b': {0: 0x19, **{i: 0x10 + i for i in range(1, 9)}},
             'v': {'IP10': {0: 30}, 'BF': {0: 7}, 'AB': {i: 4 for i in range(1, 9)},
                   'H': {1: 1, 2: (100, 27)}, 'R': {1: 1}}},
            {'b': {1: 0x11, 2: 0x12, 6: 0x29},
             'v': {'AB': {1: (200, 100), 2: 3}, 'IP10': {6: 10}, 'SOA': {6: (2, 0)}}}]),
        game(b'XYZ', b'NL00', 1, 1, box=[{'b': {0: 0x19}, 'v': {'IP10': {0: 9}}},
                                         {'b': {0: 0x10}}]),
        game(b'NL01', b'ALA01', 255, 1, box=[{'b': {1: 0x18}, 'v': {'AB': {1: (255, 255)}}},
                                             {'b': {3: 0x13}}]),
        game(b'clasale1', b'NL01', 2, 6, box=[{'b': {2: 0x12}, 'v': {'AB': {2: 3}}},
                                              {'b': {5: 0x19}}]),
        game(b'NL00', b'ALA13', 9, 9, box=[{'b': {0: 0x10}, 'v': {'AB': {0: 2}}}, {}]),
        game(b'AlA02', b'nl05', 1, 0, box=[{'b': {4: 0x14}, 'v': {'AB': {4: 1}}}, {}]),
        game(b'NL01', b'ALA03', 2, 4, box=[{'b': {16: 0x10}, 'v': {'AB': {16: 3}}},
                                           {'b': {0: 0x18}}]),
    ])


def test_box_host_parity_seven_games(tmp_path):
    """HISTWR and the Python reference on the 7 game box league: HISTORY.DAT, MILESTON.DAT and
    BOXSCORE.DAT equal byte for byte; game 1 (skipped) has no rows; the slot 9 ace is a pitching
    row alone."""
    series_parity(tmp_path, box_seven_games())
    host, py = os.path.join(str(tmp_path), 'host'), os.path.join(str(tmp_path), 'py')
    bc = open(os.path.join(host, 'BOXSCORE.DAT'), 'rb').read()
    bp = open(os.path.join(py, 'BOXSCORE.DAT'), 'rb').read()
    assert bc == bp and len(bc) > 0 and len(bc) % 16 == 0
    rows = history.box_entries(os.path.join(py, 'H.DAT'))
    assert {r[1] for r in rows} == {0, 2, 3, 4, 5, 6}
    ace = [r for r in rows if r[1] == 0 and r[2] == 2 and r[5] == 0]
    assert len(ace) == 1 and ace[0][4] == 0x19 and ace[0][6][0] == 30
    assert not [r for r in rows if r[1] == 0 and r[5] == 0 and r[2] & 2 == 0]


def test_box_rerun_parity(tmp_path):
    """The same season run again on a fresh HISTORY.DAT, with the first run's BOXSCORE.DAT still
    beside it: the same bytes, equal to the Python reference."""
    _build()
    ldir = str(tmp_path / 'lg')
    os.makedirs(ldir)
    full_award_league(ldir)
    open(os.path.join(ldir, 'PLAYOFFS.AL'), 'wb').write(box_seven_games())
    d = str(tmp_path / 'c')
    shutil.copytree(ldir, d)
    hp = os.path.join(d, 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    r = HISTWR(d, hp, ret)
    assert r.returncode == 0, r.stderr
    first = open(os.path.join(d, 'BOXSCORE.DAT'), 'rb').read()
    os.remove(hp)
    r = HISTWR(d, hp, ret)
    assert r.returncode == 0, r.stderr
    assert open(os.path.join(d, 'BOXSCORE.DAT'), 'rb').read() == first
    assert len(first) > 0
    py = str(tmp_path / 'py')
    shutil.copytree(ldir, py)
    history.record_season(py, os.path.join(py, 'H.DAT'), 1, None)
    assert open(os.path.join(py, 'BOXSCORE.DAT'), 'rb').read() == first


def test_box_two_seasons_host_parity(tmp_path):
    """Season 1 then season 2 in one league directory: HISTORY.DAT, MILESTON.DAT and BOXSCORE.DAT
    match the Python reference run the same way, and BOXSCORE.DAT keeps season 1's rows first."""
    _build()
    ldir = str(tmp_path / 'lg')
    os.makedirs(ldir)
    full_award_league(ldir)
    open(os.path.join(ldir, 'PLAYOFFS.AL'), 'wb').write(box_seven_games())
    host, py = str(tmp_path / 'host'), str(tmp_path / 'py')
    shutil.copytree(ldir, host)
    shutil.copytree(ldir, py)
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    hp = os.path.join(host, 'H.DAT')
    for _ in range(2):
        r = HISTWR(host, hp, ret)
        assert r.returncode == 0, r.stderr
    hp2 = os.path.join(py, 'H.DAT')
    history.record_season(py, hp2, 1, None)
    history.record_season(py, hp2, 2, None)
    for leaf in ('H.DAT', 'MILESTON.DAT', 'BOXSCORE.DAT'):
        a = open(os.path.join(host, leaf), 'rb').read()
        b = open(os.path.join(py, leaf), 'rb').read()
        off, ent = first_diff(a, b)
        assert off < 0, f'{leaf}: first diff at offset {off} (entry {ent})'
    rows = history.box_entries(hp2)
    s1 = [r for r in rows if r[0] == 1]
    assert s1 and {r[0] for r in rows} == {1, 2}
    assert rows == s1 + [r for r in rows if r[0] == 2]


def test_box_fail_rename_keeps_three_files(tmp_path):
    """A failing last rename (host build with -DTEST_FAIL_RENAME, BOXSCORE last): HISTORY.DAT,
    MILESTON.DAT and BOXSCORE.DAT are restored byte for byte, rc 2, and no TMP or BAK is left.
    Without an earlier BOXSCORE.DAT the failure leaves none behind."""
    _build()
    _build_special(HC, ['-DTEST_FAIL_RENAME'])
    try:
        ldir = str(tmp_path / 'lg')
        os.makedirs(ldir)
        full_award_league(ldir)
        open(os.path.join(ldir, 'PLAYOFFS.AL'), 'wb').write(box_seven_games())
        ret = os.path.join(str(tmp_path), 'R.DAT')
        open(ret, 'wb').write(bytes(1))
        hp = os.path.join(str(tmp_path), 'H.DAT')
        open(hp, 'wb').write(bytes(range(32)))
        ms = ms_path_of(hp)
        open(ms, 'wb').write(bytes([1, 0, 0, 0, 40, 0, 5, 0]))
        bp = os.path.join(str(tmp_path), 'BOXSCORE.DAT')
        open(bp, 'wb').write(struct.pack('<HBBHBB8B', 1, 0, 0, 0, 0x19, 0, *range(8)))
        before = {p: open(p, 'rb').read() for p in (hp, ms, bp)}
        rc = subprocess.run([HC, ldir, hp, ret], capture_output=True, text=True)
        assert rc.returncode == 2, rc.returncode
        for p, data in before.items():
            assert open(p, 'rb').read() == data, f'{os.path.basename(p)} not restored'
        for leftover in ('HISTWR.BAK', 'HISTWR.TMP', 'MILESTON.BAK', 'MILESTON.TMP',
                         'BOXSCORE.BAK', 'BOXSCORE.TMP'):
            assert not os.path.exists(os.path.join(str(tmp_path), leftover)), \
                f'{leftover} left'
        d2 = str(tmp_path / 'fresh')
        os.makedirs(d2)
        shutil.copytree(ldir, os.path.join(d2, 'lg'))
        hp2 = os.path.join(d2, 'H.DAT')
        rc = subprocess.run([HC, os.path.join(d2, 'lg'), hp2, ret], capture_output=True, text=True)
        assert rc.returncode == 2, rc.returncode
        assert not os.path.exists(hp2) and not os.path.exists(os.path.join(d2, 'BOXSCORE.DAT'))
        assert not os.path.exists(os.path.join(d2, 'BOXSCORE.TMP'))
    finally:
        if os.path.exists(HC):
            os.remove(HC)


def test_box_no_playoffs_host_empty_file(tmp_path):
    """No PLAYOFFS.AL: HISTWR and the Python reference both leave a 0 byte BOXSCORE.DAT."""
    _build()
    ldir = str(tmp_path / 'lg')
    os.makedirs(ldir)
    full_award_league(ldir)
    host, py = str(tmp_path / 'host'), str(tmp_path / 'py')
    shutil.copytree(ldir, host)
    shutil.copytree(ldir, py)
    hp = os.path.join(host, 'H.DAT')
    ret = os.path.join(str(tmp_path), 'R.DAT')
    open(ret, 'wb').write(bytes(1))
    r = HISTWR(host, hp, ret)
    assert r.returncode == 0, r.stderr
    history.record_season(py, os.path.join(py, 'H.DAT'), 1, None)
    for d in (host, py):
        assert open(os.path.join(d, 'BOXSCORE.DAT'), 'rb').read() == b''
