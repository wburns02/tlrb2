#!/usr/bin/env python3
"""CREATE C port parity (tools/m4/create_c/create.c) against tools/m4/create.py. Run:
  python3 -m pytest -q tools/m4/test_create.py tools/m4/test_create_c.py
The host binary tools/m4/create_c/create_host is built at import via build_create.py.
Every parity check runs create.py (step + render) and the host binary with /KEYS and
/RAW on a copy of the same league, then compares the 64000 B framebuffers and every
team V20 byte for byte. DOS tests skip when CREATE.EXE or dosbox-x is missing; font
tests skip when /mnt/nvme/tlrb2/files/MAIN.FNT is missing."""
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import pytest

import create as cr
import dynview
from m4.test_create import (make_league, make_anms, typed, need_fonts, frame_px, FILES,
                            HAVE_FONTS, ENTER, ESC, UP, DOWN, LEFT, RIGHT, PGUP, PGDN,
                            BACK)

HERE_C = os.path.join(HERE, 'create_c')
HOST = os.path.join(HERE_C, 'create_host')
EXE = os.path.join(HERE_C, 'CREATE.EXE')
WATCOM = '/mnt/nvme/tools/openwatcom'
DOSBOX = '/mnt/nvme/src/dosbox-x/src/dosbox-x'
FB_SIZE = 64000


def _build():
    r = subprocess.run([sys.executable, os.path.join(HERE_C, 'build_create.py')],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed:\n' + r.stdout + r.stderr)
    if not os.path.exists(HOST):
        raise RuntimeError('host binary missing after build')


_build()


def toks(seq):
    """key sequence -> /KEYS: token string (decimal, arrows and PGUP/PGDN as 0x hex)."""
    out = []
    for k in seq:
        if k in (dynview.KEY_LEFT, dynview.KEY_RIGHT, dynview.KEY_UP, dynview.KEY_DOWN,
                 dynview.KEY_PGUP, dynview.KEY_PGDN):
            out.append('0x%04x' % k)
        else:
            out.append(str(k))
    return ','.join(out)


def run_host(cwd, league, raw, keys, anms, font_dir=FILES):
    argv = [HOST]
    if keys:
        argv.append('/KEYS:' + toks(keys))
    argv.append('/RAW:' + raw)
    argv += [league, font_dir, anms]
    return subprocess.run(argv, capture_output=True, text=True, timeout=300, cwd=cwd)


def v20_bytes(d):
    out = {}
    for name in sorted(os.listdir(d)):
        if name.upper().endswith('.V20'):
            out[name] = open(os.path.join(d, name), 'rb').read()
    return out


def first_diff(a, b):
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i
    return min(len(a), len(b))


def parity(tmp_path, keys, base=None, anms=True, control=None, anms_path=None):
    """Run both sides on the same keys in a fresh work dir under tmp_path. Returns
    (python state, work cwd): the cwd is where the host ran (CONTROL lives there)."""
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = base or make_league(os.path.join(work, 'base'))
    pl = os.path.join(work, 'py_league')
    cl = os.path.join(work, 'c_league')
    cwd = os.path.join(work, 'cwd')
    shutil.copytree(base, pl)
    shutil.copytree(base, cl)
    os.makedirs(cwd)
    if anms_path is not None:
        anms_dir = anms_path
    elif anms:
        anms_dir = make_anms(os.path.join(work, 'anms'))
    else:
        anms_dir = os.path.join(work, 'no_anms')
    ctx = cr.load_ctx(pl, FILES, anms_dir)
    st = cr.start_state()
    for k in keys:
        st, _ = cr.step(st, k, ctx)
    fb_py = bytes(cr.render(st, ctx))
    if control is not None:
        with open(os.path.join(cwd, 'CONTROL'), 'wb') as fh:
            fh.write(control)
    raw = os.path.join(work, 'out.raw')
    r = run_host(cwd, cl, raw, keys, anms_dir)
    assert r.returncode == 0, 'host rc %d: %s' % (r.returncode, r.stderr[:400])
    fb_c = open(raw, 'rb').read()
    assert len(fb_c) == FB_SIZE
    if fb_c != fb_py:
        i = first_diff(fb_c, fb_py)
        raise AssertionError('framebuffer differs at %d (x %d y %d): c %d py %d'
                             % (i, i % 320, i // 320, fb_c[i], fb_py[i]))
    assert v20_bytes(cl) == v20_bytes(pl), 'V20 bytes differ'
    return st, cwd


SAVE_EMPTY_PITCHER = typed('Ruiz') + [DOWN] + typed('Tom') + [DOWN] * 8 + [ENTER]
SAVE_NAMED_BATTER = typed('Lowe') + [DOWN] * 12


# ---------------------------------------------------------------- host basics
def test_host_usage_without_raw(tmp_path):
    r = subprocess.run([HOST], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
    assert 'usage' in (r.stderr + r.stdout).lower()


def test_fonts_missing_exit2(tmp_path):
    empty = str(tmp_path / 'fonts')
    os.makedirs(empty)
    r = run_host(str(tmp_path), str(tmp_path), str(tmp_path / 'o.raw'), [],
                 str(tmp_path / 'anms'), font_dir=empty)
    assert r.returncode == 2
    assert 'CREATE: FONTS NOT FOUND' in r.stderr
    assert not os.path.exists(str(tmp_path / 'o.raw'))


# ---------------------------------------------------------------- parity: screens
@need_fonts
def test_parity_team_screen(tmp_path):
    parity(tmp_path, [])
    parity(tmp_path, [DOWN, DOWN, PGDN, PGUP, UP, ord('x')])


@need_fonts
def test_parity_no_teams(tmp_path):
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = make_league(os.path.join(work, 'base'), majs=())
    parity(tmp_path, [ENTER, DOWN], base=base)


@need_fonts
def test_parity_slot_screen(tmp_path):
    parity(tmp_path, [ENTER])
    parity(tmp_path, [ENTER, PGDN, DOWN, DOWN])
    parity(tmp_path, [DOWN, ENTER, PGDN, PGDN, PGUP, ESC])


@need_fonts
def test_parity_edit_defaults_and_fields(tmp_path):
    parity(tmp_path, [ENTER, ENTER])                                # pitcher P1
    parity(tmp_path, [ENTER, DOWN, ENTER])                          # empty pitcher P2
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [ENTER])               # named batter B1
    parity(tmp_path, [ENTER] + [DOWN] * 17 + [ENTER])               # empty batter B2


@need_fonts
def test_parity_typing_and_fields(tmp_path):
    keys = [ENTER, ENTER] + typed("aB1 .'-x") + [BACK, BACK] + typed('zzzzzzzzzzzz')
    keys += [DOWN] + typed('Jo') + [32] + typed('abcdefgh') + [UP]
    keys += [DOWN, DOWN, RIGHT, LEFT, LEFT]                         # POSITION row: no change
    keys += [DOWN, LEFT, RIGHT, RIGHT]                              # hands wrap
    keys += [DOWN, RIGHT] + [DOWN] + [RIGHT] * 14 + [LEFT] * 3      # ratings / face
    parity(tmp_path, keys)
    batter = [ENTER] + [DOWN] * 17 + [ENTER] + [DOWN] * 2 + [RIGHT] * 5 + [LEFT]
    batter += [DOWN] * 3 + [RIGHT] * 40 + [LEFT] * 40 + [DOWN, LEFT] * 3
    batter += [DOWN] * 6 + [RIGHT] * 15 + [UP] * 30
    parity(tmp_path, batter)


@need_fonts
def test_parity_portrait_and_gray_box(tmp_path):
    keys = [ENTER, ENTER] + [DOWN] * 8 + [RIGHT] * 3
    parity(tmp_path, keys, anms=True)
    parity(tmp_path, keys, anms=False)


@need_fonts
def test_parity_message_and_save_row(tmp_path):
    parity(tmp_path, [ENTER, ENTER] + [DOWN] * 9 + [ENTER])          # msg 1 on SAVE
    parity(tmp_path, [ENTER, ENTER, DOWN, ENTER, ESC])


@need_fonts
def test_parity_confirm_and_done(tmp_path):
    parity(tmp_path, [ENTER, ENTER] + SAVE_EMPTY_PITCHER)              # named P1: CONFIRM
    parity(tmp_path, [ENTER, DOWN, ENTER] + SAVE_EMPTY_PITCHER)        # empty P2: DONE
    parity(tmp_path, [ENTER, ENTER] + typed('Q') + [DOWN] * 9 + [ENTER, ESC])
    parity(tmp_path, [ENTER, ENTER] + typed('Q') + [DOWN] * 9 + [ENTER, ENTER, DOWN])
    parity(tmp_path, [ENTER] + [DOWN] * 17 + [ENTER] + SAVE_NAMED_BATTER + [ENTER])


@need_fonts
def test_parity_portrait_edge_cases(tmp_path):
    work = tempfile.mkdtemp(dir=str(tmp_path))
    buf = bytearray(struct.pack('<H', 40))
    for k in range(40):
        if k == 30:                                  # the default face is compressed
            buf += struct.pack('<6H', 0, 56, 48, 0, 0, 10) + bytes(10)
        else:
            buf += struct.pack('<6H', 0, 56, 48, 0, 0, 0) + frame_px(k)
    compressed = make_anms(os.path.join(work, 'comp'), n=40, frames=bytes(buf),
                           faces=bytes(40))
    parity(tmp_path, [ENTER, ENTER], anms_path=compressed)
    short_grp = make_anms(os.path.join(work, 'grp'), n=40, faces=bytes(20))
    parity(tmp_path, [ENTER, ENTER] + [DOWN] * 8 + [RIGHT], anms_path=short_grp)
    short = make_anms(os.path.join(work, 'short'), n=40)
    path = os.path.join(short, 'PORTRAIT.ANM')
    data = open(path, 'rb').read()
    open(path, 'wb').write(data[:2 + 2700 * 30 + 100])
    parity(tmp_path, [ENTER, ENTER], anms_path=short)


# ---------------------------------------------------------------- parity: saves
@need_fonts
def test_parity_save_empty_slot_v20(tmp_path):
    st, _ = parity(tmp_path, [ENTER, DOWN, ENTER] + SAVE_EMPTY_PITCHER)
    assert st['screen'] == cr.S_DONE


@need_fonts
def test_parity_save_named_slot_confirm_v20(tmp_path):
    st, _ = parity(tmp_path, [ENTER, ENTER] + typed('Smith') + [DOWN] + typed('Al')
                   + [DOWN] * 8 + [ENTER, ENTER])
    assert st['screen'] == cr.S_DONE


@need_fonts
def test_parity_save_batter_confirm_v20(tmp_path):
    st, _ = parity(tmp_path, [ENTER] + [DOWN] * 16 + [ENTER] + SAVE_NAMED_BATTER
                   + [ENTER, ENTER])
    assert st['screen'] == cr.S_DONE


# ---------------------------------------------------------------- parity: random keys
RANDOM_POOL = [ENTER] * 4 + [ESC] + [UP, DOWN] * 3 + [PGUP, PGDN, LEFT, RIGHT] * 2 \
    + [BACK] + [32, 46, 39, 45, ord('x'), ord('Q'), ord('a'), ord('1'), 0, 0x1234] \
    + [ord(c) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz']


NAME_POOL = "AaBbZz .'-1@xyzqwertyuiop"


def session(rng, n_actions):
    """Random walk through the screens built from macros: navigation, enter, escape,
    typing, field changes and a SAVE attempt (DOWN to the last row, then ENTER)."""
    keys = []
    for _ in range(n_actions):
        a = rng.random()
        if a < 0.18:
            keys += [rng.choice([UP, DOWN, PGUP, PGDN]) for _ in range(rng.randint(1, 15))]
        elif a < 0.30:
            keys += [ENTER]
        elif a < 0.36:
            keys += [ESC]
        elif a < 0.50:
            keys += typed(''.join(rng.choice(NAME_POOL) for _ in range(rng.randint(1, 13))))
        elif a < 0.66:
            keys += [rng.choice([LEFT, RIGHT]) for _ in range(rng.randint(1, 14))]
        elif a < 0.72:
            keys += [BACK] * rng.randint(1, 4)
        elif a < 0.86:
            keys += [DOWN] * rng.randint(0, 12) + [ENTER]
        else:
            keys += [DOWN] * 13 + [ENTER]
    return keys


@need_fonts
@pytest.mark.parametrize('seed', [1, 2, 3, 4, 5, 6])
def test_parity_random_sessions(tmp_path, seed):
    keys = session(random.Random(seed), 160)
    parity(tmp_path, keys)


@need_fonts
@pytest.mark.parametrize('seed', [1, 2, 3])
def test_parity_random_keys(tmp_path, seed):
    rng = random.Random(seed)
    keys = [rng.choice(RANDOM_POOL) for _ in range(400)]
    parity(tmp_path, keys)


@need_fonts
def test_parity_random_keys_no_anms(tmp_path):
    rng = random.Random(9)
    keys = [rng.choice(RANDOM_POOL) for _ in range(300)]
    parity(tmp_path, keys, anms=False)


# ---------------------------------------------------------------- CONTROL and exit
@need_fonts
def test_control_after_raw_run(tmp_path):
    ctl = bytes([0x01, 0x09, 0, 0, 0, 0, 0, 0xff, 0xff])
    _st, cwd = parity(tmp_path, [ENTER], control=ctl)
    assert open(os.path.join(cwd, 'CONTROL'), 'rb').read() == \
        bytes([0x01, 0x01, 0, 0, 0, 0, 0, 0xff, 0xff])


@need_fonts
def test_control_absent_is_fine(tmp_path):
    base = make_league(str(tmp_path / 'base'))
    cl = str(tmp_path / 'c_league')
    shutil.copytree(base, cl)
    cwd = str(tmp_path / 'cwd')
    os.makedirs(cwd)
    r = run_host(cwd, cl, str(tmp_path / 'o.raw'), [], str(tmp_path / 'anms'))
    assert r.returncode == 0
    assert not os.path.exists(os.path.join(cwd, 'CONTROL'))


# ---------------------------------------------------------------- DOS build and parity
def _dos_ready():
    return (os.path.exists(EXE) and os.path.isfile(DOSBOX)
            and os.access(DOSBOX, os.X_OK))


def test_dos_build():
    exe2 = os.path.join(HERE_C, 'CREATE2.EXE')
    if not os.path.isdir(WATCOM):
        if os.path.exists(exe2):
            os.remove(exe2)
        pytest.skip('OpenWatcom missing')
    assert os.path.exists(EXE), 'CREATE.EXE not built'
    with open(EXE, 'rb') as f:
        assert f.read(2) == b'MZ'
    r = subprocess.run([sys.executable, os.path.join(HERE_C, 'build_create.py')],
                       cwd=HERE_C, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    shutil.copy2(EXE, exe2)
    r2 = subprocess.run([sys.executable, os.path.join(HERE_C, 'build_create.py')],
                        cwd=HERE_C, capture_output=True, text=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert open(EXE, 'rb').read() == open(exe2, 'rb').read(), 'second build differs'
    os.remove(exe2)


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


def run_dos(cdir, bat_lines):
    """Write cdir/RUN.BAT (CRLF), run it under dosbox-x, return int(RC.TXT)."""
    shutil.copy2(EXE, os.path.join(cdir, 'CREATE.EXE'))
    bat = os.path.join(cdir, 'RUN.BAT')
    with open(bat, 'wb') as f:
        for line in bat_lines + BAT_LADDER:
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
                          capture_output=True, text=True, timeout=180, env=env)
    if not os.path.exists(rc_txt):
        raise AssertionError('RC.TXT missing rc=%d out=%s err=%s'
                             % (proc.returncode, proc.stdout[-400:], proc.stderr[-400:]))
    return int(open(rc_txt).read().strip() or 0)


def test_dos_parity(tmp_path):
    """Headless DOSBox-X: CREATE.EXE /RAW:OUT.RAW /KEYS:13,13 LEAGUE FONTS ANMS against
    the Python reference on the same league."""
    if not _dos_ready():
        pytest.skip('CREATE.EXE or dosbox-x missing')
    if not HAVE_FONTS:
        pytest.skip('fonts missing')
    base = make_league(str(tmp_path / 'base'))
    d = str(tmp_path / 'dos')
    os.makedirs(os.path.join(d, 'LEAGUE'))
    os.makedirs(os.path.join(d, 'FONTS'))
    os.makedirs(os.path.join(d, 'ANMS'))
    for name in os.listdir(base):
        shutil.copy2(os.path.join(base, name), os.path.join(d, 'LEAGUE', name))
    for name in ('MAIN.FNT', 'BOLD.FNT', 'DEFAULT.PAL'):
        shutil.copy2(os.path.join(FILES, name), os.path.join(d, 'FONTS', name))
    anms = make_anms(str(tmp_path / 'anms'))
    for name in os.listdir(anms):
        shutil.copy2(os.path.join(anms, name), os.path.join(d, 'ANMS', name))
    rc = run_dos(d, ['CREATE.EXE /RAW:OUT.RAW /KEYS:13,13 LEAGUE FONTS ANMS'])
    assert rc == 0, 'dos rc %d' % rc
    py_league = str(tmp_path / 'py_league')
    shutil.copytree(base, py_league)
    ctx = cr.load_ctx(py_league, FILES, anms)
    st = cr.start_state()
    for k in [ENTER, ENTER]:
        st, _ = cr.step(st, k, ctx)
    fb_py = bytes(cr.render(st, ctx))
    fb_dos = open(os.path.join(d, 'OUT.RAW'), 'rb').read()
    assert fb_dos == fb_py, 'DOS framebuffer differs at %d' % first_diff(fb_dos, fb_py)
