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
import re
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
import rookies
from m4.test_create import (make_league, make_anms, make_v20, named_rec, typed, need_fonts,
                            frame_px, FILES, HAVE_FONTS, ENTER, ESC, UP, DOWN, LEFT, RIGHT,
                            PGUP, PGDN, BACK)

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


def parity(tmp_path, keys, base=None, anms=True, control=None, anms_path=None, fonts=FILES):
    """Run both sides on the same keys in a fresh work dir under tmp_path. fonts is the font dir
    of both sides. Returns (python state, work cwd): the cwd is where the host ran (CONTROL lives
    there)."""
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
    ctx = cr.load_ctx(pl, fonts, anms_dir)
    st = cr.start_state()
    for k in keys:
        st, _ = cr.step(st, k, ctx)
    fb_py = bytes(cr.render(st, ctx))
    if control is not None:
        with open(os.path.join(cwd, 'CONTROL'), 'wb') as fh:
            fh.write(control)
    raw = os.path.join(work, 'out.raw')
    r = run_host(cwd, cl, raw, keys, anms_dir, font_dir=fonts)
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
SAVE_NAMED_BATTER = typed('Lowe') + [DOWN] * 13
# every rating at its cap: batter power, bunt, hit and run, speed, range, arm; pitcher
# control, velocity, endurance (the cap, 10)
SAVE_ALL12_BATTER = typed('Lowe') + [DOWN] * 6 + ([RIGHT] * 6 + [DOWN]) * 6 \
    + [DOWN, ENTER]
SAVE_ALL_MAX_PITCHER = (typed('Ruiz') + [DOWN] + typed('Tom') + [DOWN] * 4
                        + ([RIGHT] * 6 + [DOWN]) * 2 + [RIGHT] * 6 + [DOWN] * 2 + [ENTER])


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


@need_fonts
def test_parity_salary_and_second_pos_c21(tmp_path):
    """C21: the SALARY text under the portrait and the SECOND POS row match the Python
    render: a batter edit screen with the cursor on SECOND POS, a pitcher edit screen
    (salary text only), a save after changing ratings (the salary text differs from the
    default) and the empty-name message screen on both edit forms."""
    # named batter B1: cursor on SECOND POS (row 3), and the save after rating changes
    batter = ([ENTER] + [DOWN] * 16 + [ENTER] + typed('Lowe') + [DOWN] * 3)
    parity(tmp_path, batter)
    ratings = typed('Lowe') + [DOWN] * 6 + ([RIGHT] * 6 + [DOWN]) * 3
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [ENTER] + ratings)
    # empty pitcher P2: the pitcher screen shows SALARY (no SECOND POS row)
    parity(tmp_path, [ENTER, DOWN, ENTER] + typed('Ruiz') + [DOWN] + typed('Tom')
           + [DOWN] * 4 + [RIGHT] * 6)
    # empty-name message screen, batter and pitcher (MSG_NAME moved to y 175)
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [ENTER] + [DOWN] * 13 + [ENTER])
    parity(tmp_path, [ENTER, ENTER] + [DOWN] * 9 + [ENTER])


# ---------------------------------------------------------------- parity: saves
@need_fonts
def test_parity_save_pos2_v20_bytes_c20b(tmp_path):
    """C20b: a saved SS has byte 31 = 0xB5, a saved LF 0xA6, a saved pitcher
    0x00; the host's V20 bytes equal Python's on the same keys (parity())."""
    # named batter B1 (slot 16, occupant pos SS): default form keeps pos 5
    ss_keys = [ENTER] + [DOWN] * 16 + [ENTER] + SAVE_NAMED_BATTER + [ENTER, ENTER]
    st, _ = parity(tmp_path, ss_keys)
    assert st['screen'] == cr.S_DONE
    assert cr.record(st['image'], 16)[31] == 0xB5
    # same slot, POSITION one RIGHT: 5 -> 6 (LF, pos2 resets to OF)
    lf_keys = ([ENTER] + [DOWN] * 16 + [ENTER] + typed('Lefty') + [DOWN] * 2
               + [RIGHT] + [DOWN] * 11 + [ENTER, ENTER])
    st, _ = parity(tmp_path, lf_keys)
    assert st['screen'] == cr.S_DONE
    assert cr.record(st['image'], 16)[31] == 0xA6
    # empty pitcher P2: byte 31 = 0
    st, _ = parity(tmp_path, [ENTER, DOWN, ENTER] + SAVE_EMPTY_PITCHER)
    assert st['screen'] == cr.S_DONE
    assert cr.record(st['image'], 1)[31] == 0


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


@need_fonts
def test_parity_save_all12_batter_and_all_max_pitcher_v20(tmp_path):
    st, _ = parity(tmp_path, [ENTER] + [DOWN] * 16 + [ENTER] + SAVE_ALL12_BATTER
                   + [ENTER])
    assert st['screen'] == cr.S_DONE
    st, _ = parity(tmp_path, [ENTER, DOWN, ENTER] + SAVE_ALL_MAX_PITCHER)
    assert st['screen'] == cr.S_DONE


@need_fonts
def test_parity_role_column_slot_screen(tmp_path):
    """The slot list with ROLE text on named slots (BOS: P1 Adams in ROT, B1 Baker in
    START) and the other lists set on empty slots."""
    base = make_league(str(tmp_path / 'roles'))
    with open(os.path.join(base, 'BOS.V20'), 'r+b') as fh:
        for off, slot in ((111, 0), (116, 2), (122, 16), (194, 17), (222, 18)):
            fh.seek(off)
            fh.write(bytes([slot]))
    st, _ = parity(tmp_path, [ENTER], base=base)
    assert st['screen'] == cr.S_SLOT


@need_fonts
def test_parity_save_reserve_slot_confirm_v20(tmp_path):
    base = make_league(str(tmp_path / 'res'))
    with open(os.path.join(base, 'BOS.V20'), 'r+b') as fh:
        fh.seek(222)                                 # RES list: slot 16 (B1)
        fh.write(bytes([16]))
    st, _ = parity(tmp_path, [ENTER] + [DOWN] * 16 + [ENTER] + SAVE_NAMED_BATTER
                   + [ENTER], base=base)
    assert st['screen'] == cr.S_CONFIRM
    st, _ = parity(tmp_path, [ENTER] + [DOWN] * 16 + [ENTER] + SAVE_NAMED_BATTER
                   + [ENTER, ENTER], base=base)
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


@need_fonts
def test_parity_budget_c31(tmp_path):
    """C31: the BUDGET block and the refusal message on both sides. OFF default, the
    three modes, the red over-budget text, an over-budget SAVE refusal frame, a save
    under STAR and B typed into the last name."""
    # OFF default form (batter and pitcher), and each of the 3 modes
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [ENTER])
    parity(tmp_path, [ENTER, DOWN, ENTER])
    parity(tmp_path, [ENTER] + [DOWN] * 17 + [ENTER] + [DOWN] * 6 + [66])
    parity(tmp_path, [ENTER] + [DOWN] * 17 + [ENTER] + [DOWN] * 6 + [98, 98])
    parity(tmp_path, [ENTER] + [DOWN] * 17 + [ENTER] + [DOWN] * 6 + [66, 66, 66])
    # over-budget refusal: ROOKIE, POWER raised to 12, SAVE ENTER (msg 2 frame)
    over = ([ENTER] + [DOWN] * 17 + [ENTER] + typed('Oak') + [DOWN] * 6 + [98]
            + [RIGHT] * 6 + [DOWN] * 7 + [ENTER])
    st, _ = parity(tmp_path, over)
    assert (st['screen'], st['msg'], st['budget']) == (cr.S_EDIT, 2, 1)
    # then the next key clears msg 2 like msg 1
    parity(tmp_path, over + [LEFT])
    # a save under STAR goes to DONE on both sides with identical V20 bytes
    st, _ = parity(tmp_path, [ENTER] + [DOWN] * 17 + [ENTER] + typed('Oak')
                   + [DOWN] * 6 + [98, 98, 98] + [RIGHT] * 6 + [DOWN] * 7 + [ENTER])
    assert st['screen'] == cr.S_DONE
    # B typed into the last name letters, mode untouched
    parity(tmp_path, [ENTER] + [DOWN] * 17 + [ENTER] + typed('bBb') + [DOWN, 98, 98, UP])
    # survive CREATE ANOTHER: cycle a mode, save, re-enter the edit screen
    again = ([ENTER] + [DOWN] * 17 + [ENTER] + typed('Oak') + [DOWN] * 6 + [98]
             + [RIGHT] * 6 + [DOWN] * 7 + [ENTER, 98, ENTER, ENTER, DOWN, ENTER, ENTER])
    st, _ = parity(tmp_path, again)
    assert (st['screen'], st['budget']) == (cr.S_EDIT, 2)


# ---------------------------------------------------------------- parity: C34 A auto-fill
# Synthetic fonts, so the parity runs without the game fonts (glyph shapes do not
# matter, both sides draw the same ones).
def test_parity_autofill_c34(tmp_path):
    """C34: key A on the edit screen auto-fills from the session seed; the framebuffer
    and the saved V20 bytes match on a batter (each mode, once and twice) and a
    pitcher under STAR, and A typed into the first name stays a letter."""
    fonts = synth_fonts(os.path.join(str(tmp_path), 'c34fonts'))
    batter = [ENTER] + [DOWN] * 16 + [ENTER] + [DOWN] * 6
    parity(tmp_path, batter + [97], fonts=fonts)                     # OFF: REGULAR target
    parity(tmp_path, batter + [66] + [65], fonts=fonts)              # ROOKIE
    parity(tmp_path, batter + [66, 66] + [97], fonts=fonts)          # REGULAR
    parity(tmp_path, batter + [66] * 3 + [65], fonts=fonts)          # STAR
    parity(tmp_path, batter + [66, 66, 66] + [65, 65], fonts=fonts)  # twice under STAR
    parity(tmp_path, [ENTER, ENTER] + [DOWN] * 5 + [66] * 3 + [65],
           fonts=fonts)                                              # P1, STAR
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [ENTER] + [65] + [DOWN, 97, UP],
           fonts=fonts)                                              # A types on names
    parity(tmp_path, batter + [65, ESC, DOWN, ENTER, 65],
           fonts=fonts)                                              # seed across screens


# ---------------------------------------------------------------- parity: C37 N random name
# Synthetic fonts, so the parity runs without the game fonts (glyph shapes do not
# matter, both sides draw the same ones).
createForm = [ENTER] + [DOWN] * 16 + [ENTER]          # named batter B1 (slot 16)

def test_parity_random_name_c37(tmp_path):
    """C37: key N on the edit screen picks a name from the rookie pools with the session
    seed; the framebuffer and the saved V20 bytes match. Five N presses so different
    pool entries are drawn, then a save; N on the last name types 'N'; N then A then a
    save; and the new FOOT_FIELD frame."""
    fonts = synth_fonts(os.path.join(str(tmp_path), 'c37fonts'))
    parity(tmp_path, [ENTER, ENTER] + [78, 78, 78, 78, 78], fonts=fonts)     # P1, five N
    parity(tmp_path, createForm + [DOWN] * 6 + [110] * 5, fonts=fonts)       # B1, five N
    # N (78) typed into the last name, N (110) into the first: letters, not a pick
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [ENTER] + [78, 78] + [DOWN, 110], fonts=fonts)
    # N once, then A, then save (the picked name with the autofilled ratings)
    st, _ = parity(tmp_path, createForm + [DOWN] * 6 + [78, 65] + [DOWN] * 7
                   + [ENTER, ENTER], fonts=fonts)
    assert st['screen'] == cr.S_DONE
    assert st['form']['last'] in rookies.LAST_NAMES
    assert st['form']['first'] in rookies.FIRST_NAMES
    # a save of the five-N name (empty batter B2, no confirm)
    parity(tmp_path, [ENTER] + [DOWN] * 17 + [ENTER] + [78] * 5 + [DOWN] * 7 + [ENTER],
           fonts=fonts)
    # the FOOT_FIELD frame itself (cursor on a rating row, footer text differs from C34)
    parity(tmp_path, createForm + [DOWN] * 6, fonts=fonts)


def test_parity_foot_field_text_c37():
    """C37: the two FOOT_FIELD texts match, and the C source text matches the Python."""
    assert cr.FOOT_FIELD == 'UP DOWN LEFT RIGHT  A AUTO  N NAME  ESC'
    src = open(os.path.join(HERE_C, 'create.c')).read()
    assert ('static const char *FOOT_FIELD = "%s";' % cr.FOOT_FIELD) in src


def test_name_tables_match_python_lists():
    """C37: the C name tables are the rookies.py lists in identical order: read both
    pools from rookies.py, extract the C table initializers from the create.c text and
    compare entry by entry."""
    src = open(os.path.join(HERE_C, 'create.c')).read()

    def c_table(name):
        i = src.index('C37_%s[' % name)
        a = src.index('{', i)
        depth = 0
        for j in range(a, len(src)):
            if src[j] == '{':
                depth += 1
            elif src[j] == '}':
                depth -= 1
                if depth == 0:
                    break
        assert depth == 0, name
        body = src[a + 1:j]
        return re.findall(r'"((?:[^"\\]|\\.)*)"', body)

    lasts = c_table('LAST_NAMES')
    firsts = c_table('FIRST_NAMES')
    assert lasts == rookies.LAST_NAMES, 'C37_LAST_NAMES differs from rookies.LAST_NAMES'
    assert firsts == rookies.FIRST_NAMES, 'C37_FIRST_NAMES differs from rookies.FIRST_NAMES'


# ---------------------------------------------------------------- parity: C68 unique name
def _c68_picks(n):
    """The first n C37 (last, first) picks from seed 1 and the seed after them:
    pick 1 is ('Russell', 'Marvin'), the seed it leaves is 377401575."""
    out = []
    seed = 1
    for _ in range(n):
        seed = (seed * 1103515245 + 12345) % 2 ** 31
        last = rookies.LAST_NAMES[(seed >> 16) % len(rookies.LAST_NAMES)]
        seed = (seed * 1103515245 + 12345) % 2 ** 31
        first = rookies.FIRST_NAMES[(seed >> 16) % len(rookies.FIRST_NAMES)]
        out.append((last, first))
    return out, seed


def test_parity_random_name_unique_c68(tmp_path):
    """C68: the N pick skips names already in the league on both sides - a plant in
    another team's V20 (DET slot 20), one in the selected team's own image, and all
    eight picks planted (the 8th kept) - while a clean league stays byte-identical
    to C37, and a save after the skip writes the same V20 bytes."""
    picks, _ = _c68_picks(8)
    assert picks[0] == ('Russell', 'Marvin')
    fonts = synth_fonts(os.path.join(str(tmp_path), 'c68fonts'))
    pit = [ENTER, ENTER] + [DOWN] * 2 + [ord('N')]     # P1, POSITION row, one N
    other = make_league(str(tmp_path / 'other'),
                        recs={2: {20: named_rec('Russell', 'Marvin', 25, 4)}})
    parity(tmp_path, pit, base=other, fonts=fonts)
    own = make_league(str(tmp_path / 'own'),
                      recs={0: {1: named_rec('Russell', 'Marvin', 25, 0)}})
    parity(tmp_path, [ENTER, DOWN, ENTER] + [DOWN] * 2 + [ord('N')], base=own,
           fonts=fonts)
    all8 = make_league(str(tmp_path / 'all8'),
                       recs={2: {20 + i: named_rec(p[0], p[1], 25, 4)
                                 for i, p in enumerate(picks)}})
    parity(tmp_path, pit, base=all8, fonts=fonts)      # all 8 collide: the 8th kept
    parity(tmp_path, pit, fonts=fonts)                 # clean league: the C37 pick
    st, _ = parity(tmp_path, [ENTER, DOWN, ENTER] + [DOWN] * 2 + [ord('N')]
                   + [DOWN] * 7 + [ENTER], base=other, fonts=fonts)
    assert st['screen'] == cr.S_DONE                   # a save after the skip
    assert (st['form']['last'], st['form']['first']) == picks[1]


# ---------------------------------------------------------------- 3 divisions: team list (C12.3)
# These run without the game fonts: synthetic MAIN.FNT / BOLD.FNT of the same layout (glyph
# shapes do not matter, both sides draw the same ones), so the host team list is always checked.
MAJ_SIZE = 59771
# (league, MAJ slot, stem, V20 name, record index of one named batter or None); 3 divisions use
# slots 0..4, 8..12, 16..20. The NL slot 20 team (PIT) is the last team listed.
TEAM3_SPEC = [(0, 0, b'BOS', b'BOSTON', None), (0, 2, b'DET', b'DETROIT', None),
              (0, 8, b'OAK', b'OAKLAND', None), (1, 16, b'CHI', b'CUBS', None),
              (1, 17, b'SLN', b'', None), (1, 20, b'PIT', b'PITTSBURGH', 0)]
# TEAMID.DAT ids (C12.3): AL teams 0..15, NL teams 16..31. PIT (NL slot 20) is engine id 30 without
# the table; with it the NL order differs (PIT 16, SLN 17, CHI 21), so the team list shows it.
TEAMID3 = {b'BOS': 0, b'DET': 1, b'OAK': 2, b'PIT': 16, b'SLN': 17, b'CHI': 21}
TEAMS3_NO_TABLE = [(0, 'BOS', 'BOSTON'), (2, 'DET', 'DETROIT'), (5, 'OAK', 'OAKLAND'),
                   (26, 'CHI', 'CUBS'), (27, 'SLN', 'SLN'), (30, 'PIT', 'PITTSBURGH')]
TEAMS3_TABLE = [(0, 'BOS', 'BOSTON'), (1, 'DET', 'DETROIT'), (2, 'OAK', 'OAKLAND'),
                (16, 'PIT', 'PITTSBURGH'), (17, 'SLN', 'SLN'), (21, 'CHI', 'CUBS')]


def synth_fonts(d):
    """MAIN.FNT (7 rows) and BOLD.FNT (8 rows), 95 glyphs each in the assets.parse_fnt layout."""
    os.makedirs(d, exist_ok=True)
    for leaf, rows in (('MAIN.FNT', 7), ('BOLD.FNT', 8)):
        buf = bytearray(struct.pack('<H', 95))
        for g in range(95):
            buf += bytes((rows, 7, 7))
            buf += bytes(((g * 29 + r * 13) % 127) << 1 for r in range(rows))
        with open(os.path.join(d, leaf), 'wb') as fh:
            fh.write(buf)
    return d


def make_league3(d, table=None):
    """A 3-division league: the MAJ with 0x20d = 3 and the TEAM3_SPEC stems, a V20 per team, and
    TEAMID.DAT = table (bytes) when given."""
    os.makedirs(d, exist_ok=True)
    maj = bytearray(MAJ_SIZE)
    maj[0x20c], maj[0x20d] = 2, 3
    for lg, slot, stem, name, batter in TEAM3_SPEC:
        base = cr.AL_BASE if lg == 0 else cr.NL_BASE
        off = base + cr.MAJ_STEM_OFF + 8 * slot
        maj[off:off + 8] = stem.ljust(8, b'\0')
        recs = {} if batter is None else {batter: named_rec('Ruiz', 'Tom', 25, 0, 100)}
        with open(os.path.join(d, stem.decode('latin-1') + '.V20'), 'wb') as fh:
            fh.write(make_v20(name, recs))
    with open(os.path.join(d, 'LEAGUE.MAJ'), 'wb') as fh:
        fh.write(bytes(maj))
    if table is not None:
        with open(os.path.join(d, 'TEAMID.DAT'), 'wb') as fh:
            fh.write(table)
    return d


def table3():
    t = bytearray(256)
    for stem, k in TEAMID3.items():
        t[8 * k:8 * k + len(stem)] = stem
    return bytes(t)


def test_3div_team_list_no_table_parity(tmp_path):
    """3 divisions without TEAMID.DAT: cr.teams lists the NL slot 20 team as id 30 (its engine id),
    and the host team screen and slot screen match the Python render."""
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = make_league3(os.path.join(work, 'base'))
    assert cr.teams(base) == TEAMS3_NO_TABLE
    fonts = synth_fonts(os.path.join(work, 'fonts'))
    parity(tmp_path, [], base=base, fonts=fonts)
    parity(tmp_path, [DOWN] * 5 + [ENTER], base=base, fonts=fonts)


def test_3div_team_list_table_parity(tmp_path):
    """3 divisions with TEAMID.DAT: the stable ids come from the table (PIT 16, SLN 17, CHI 21), so
    the NL order differs from the engine ids, and the host team and slot screens match the Python
    render."""
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = make_league3(os.path.join(work, 'base'), table=table3())
    assert cr.teams(base) == TEAMS3_TABLE
    fonts = synth_fonts(os.path.join(work, 'fonts'))
    parity(tmp_path, [], base=base, fonts=fonts)
    parity(tmp_path, [DOWN] * 5 + [ENTER], base=base, fonts=fonts)


# ---------------------------------------------------------------- parity: face list (C14.1)
# Synthetic fonts again, so these run without the game fonts. Generic faces 0..G-1 and customs
# 400..c-1 (C14.1): G = FACEGRP.DAT length, c = PORTRAIT.ANM count.
FLAG5 = bytes(1 if k == 5 else 0 for k in range(97))
FACE_P2 = [ENTER, DOWN, ENTER]                     # P2, empty pitcher: FACE is row 8, SAVE row 9
SAVE_FACE_P2 = FACE_P2 + typed('Ruiz') + [DOWN] + typed('Tom') + [DOWN] * 7


def _face_setup(tmp_path, n_frames, faces, count=None):
    """(anms dir, synthetic fonts): PORTRAIT.ANM with n_frames frames, FACEGRP.DAT = faces, and
    the header count patched to count when given (a count past the frames)."""
    work = tempfile.mkdtemp(dir=str(tmp_path))
    anms = make_anms(os.path.join(work, 'anms'), n=n_frames, faces=faces)
    if count is not None:
        path = os.path.join(anms, 'PORTRAIT.ANM')
        data = open(path, 'rb').read()
        open(path, 'wb').write(struct.pack('<H', count) + data[2:])
    return anms, synth_fonts(os.path.join(work, 'fonts'))


def test_parity_face_list_generic_only(tmp_path):
    """G = c = 97: the list is 0..96, wraps both ways, and a save writes the generic flag."""
    anms, fonts = _face_setup(tmp_path, 97, None)
    keys = FACE_P2 + [DOWN] * 8 + [RIGHT] * 65 + [PGDN, PGUP, RIGHT, RIGHT, LEFT, LEFT, PGUP]
    parity(tmp_path, keys, anms_path=anms, fonts=fonts)
    st, _ = parity(tmp_path, SAVE_FACE_P2 + [PGDN, PGDN, DOWN, ENTER], anms_path=anms, fonts=fonts)
    assert st['screen'] == cr.S_DONE and st['form']['face'] == 50


def test_parity_face_list_with_customs(tmp_path):
    """G = 97, c = 403: the list is 0..96 then 400..402; wraps and PGUP / PGDN cross into customs,
    and saves of custom 401 (group 0) and generic 5 (group 1) match the V20 bytes."""
    anms, fonts = _face_setup(tmp_path, 403, FLAG5)
    keys = FACE_P2 + [DOWN] * 8 + [RIGHT] * 70 + [PGUP] + [RIGHT] * 7 + [PGDN] + [LEFT] * 8
    keys += [PGDN, PGUP]
    st, _ = parity(tmp_path, keys, anms_path=anms, fonts=fonts)
    assert st['form']['face'] == 402
    st, _ = parity(tmp_path, SAVE_FACE_P2 + [RIGHT] * 68 + [DOWN, ENTER], anms_path=anms, fonts=fonts)
    assert st['screen'] == cr.S_DONE and st['form']['face'] == 401
    st, _ = parity(tmp_path, SAVE_FACE_P2 + [LEFT] * 25 + [DOWN, ENTER], anms_path=anms, fonts=fonts)
    assert st['screen'] == cr.S_DONE and st['form']['face'] == 5


def test_parity_face_list_exactly_400(tmp_path):
    """c = 400: no customs, the list is the 97 generic faces only."""
    anms, fonts = _face_setup(tmp_path, 400, bytes(97))
    keys = FACE_P2 + [DOWN] * 8 + [RIGHT] * 67 + [PGDN] + [LEFT] * 11 + [PGUP, PGDN]
    parity(tmp_path, keys, anms_path=anms, fonts=fonts)


def test_parity_face_list_count_capped_981(tmp_path):
    """Header count 1000 (past the 981 cap, and past the 403 frames in the file): the list is
    97 + 981 - 400 = 678 entries, so PGUP from 30 lands on custom 971 (position 668)."""
    anms, fonts = _face_setup(tmp_path, 403, bytes(97), count=1000)
    keys = FACE_P2 + [DOWN] * 8 + [PGUP] * 4
    st, _ = parity(tmp_path, keys, anms_path=anms, fonts=fonts)
    assert st['form']['face'] == 971
    parity(tmp_path, keys + [PGUP], anms_path=anms, fonts=fonts)


# ---------------------------------------------------------------- parity: C44 C copy
def test_parity_copy_c44(tmp_path):
    """C44: key C on the slot list opens the prefilled edit form like Python. The slot
    list footer with the new C COPY text, C on a pitcher, C on a lowercase c on a
    batter, C on an empty slot (frame unchanged below the footer), C then edit then a
    save of the copied record, and C typed on the team screen (no copy there)."""
    fonts = synth_fonts(os.path.join(str(tmp_path), 'c44fonts'))
    # the new FOOT_SLOT text on the slot screen itself
    parity(tmp_path, [ENTER], fonts=fonts)
    # C on a pitcher (slot 0: Adams) shows the copied form
    parity(tmp_path, [ENTER] + [67], fonts=fonts)
    # lowercase c on a batter (slot 16: Baker)
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [99], fonts=fonts)
    # C on an empty slot: the frame is the plain slot list (footer only differs)
    parity(tmp_path, [ENTER] + [DOWN, 67], fonts=fonts)
    # copy, then a save: the record bytes equal Python's on the same keys
    st, _ = parity(tmp_path, [ENTER] + [DOWN] * 16 + [99] + [DOWN] * 13 + [ENTER, ENTER],
                   fonts=fonts)
    assert st['screen'] == cr.S_DONE
    assert st['form']['last'] == 'Baker' and st['form']['pos'] == 5
    # ENTER on the slot list is unchanged: the default form, not the copy
    parity(tmp_path, [ENTER] + [ENTER], fonts=fonts)
    # C on the team screen does nothing
    parity(tmp_path, [67, 99, ENTER], fonts=fonts)


def test_parity_copy_foot_slot_text_c44():
    """C44: the FOOT_SLOT texts match, and the C source text matches the Python."""
    assert cr.FOOT_SLOT == 'UP DOWN  ENTER NEW  C COPY  ESC TEAMS'
    src = open(os.path.join(HERE_C, 'create.c')).read()
    assert ('static const char *FOOT_SLOT = "%s";' % cr.FOOT_SLOT) in src
