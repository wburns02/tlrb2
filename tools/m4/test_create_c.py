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



def test_parity_random_name_short_file_and_list_index_c68(tmp_path):
    """C68 (brain): a DET file cut after its slot 20 (shorter than 40 roster records)
    is skipped whole, so its planted pick does not collide; with NYA selected (list
    index 2, id 15) DET (index 1, id 2) is read from its file and its plant collides."""
    fonts = synth_fonts(os.path.join(str(tmp_path), 'c68fonts2'))
    pit = [ENTER, ENTER] + [DOWN] * 2 + [ord('N')]
    short = make_league(str(tmp_path / 'short'),
                        recs={2: {20: named_rec('Russell', 'Marvin', 25, 4)}})
    det = os.path.join(short, 'DET.V20')
    data = open(det, 'rb').read()
    open(det, 'wb').write(data[:295 + 143 * 21])
    st, _ = parity(tmp_path, pit, base=short, fonts=fonts)
    assert (st['form']['last'], st['form']['first']) == ('Russell', 'Marvin')
    nya = make_league(str(tmp_path / 'nya'),
                      recs={2: {20: named_rec('Russell', 'Marvin', 25, 4)}})
    st, _ = parity(tmp_path, [DOWN, DOWN] + pit, base=nya, fonts=fonts)
    assert (st['form']['last'], st['form']['first']) != ('Russell', 'Marvin')

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


# ---------------------------------------------------------------- C69: release to the pool
def rel_league_c(w, pools=None, mut=None):
    """test_create.rel_league on a tmp_path work dir (the C tests pass real
    key lists to both sides; the records: Adams (P) 0, Bloh (P) 1)."""
    from m4.test_create import pool_img, add_b1, rel_league
    return rel_league(os.path.join(w, 'L'), pools=pools, mut=mut)


@need_fonts
def test_parity_release_bench_batter_pool1_c69(tmp_path):
    """Release of a bench batter: identical frames and identical POOL1.V20 +
    BOS.V20 bytes (POOL1 created, pair at slot 16, years 0, header repaired,
    leftovers 0xff)."""
    from m4.test_create import add_b1
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = rel_league_c(os.path.join(work, 'mk'), mut=add_b1)
    st, _ = parity(tmp_path, [ENTER] + [DOWN] * 16 + [ord('D'), ord('Y')],
                   base=base)
    assert st['msg'] == 'RELEASED TO POOL1'
    assert st['screen'] == cr.S_SLOT


@need_fonts
def test_parity_release_staff_pitcher_c69(tmp_path):
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = rel_league_c(os.path.join(work, 'mk'))
    st, _ = parity(tmp_path, [ENTER, ord('D'), ord('Y')], base=base)
    assert st['msg'] == 'RELEASED TO POOL1'
    assert st['screen'] == cr.S_SLOT


@need_fonts
def test_parity_release_screen_frame_c69(tmp_path):
    """The S_RELEASE list frame (slot rows, FOOT_RELEASE) matches."""
    from m4.test_create import add_b1
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = rel_league_c(os.path.join(work, 'mk'), mut=add_b1)
    st, _ = parity(tmp_path, [ENTER] + [DOWN] * 16 + [ord('D')], base=base)
    assert st['screen'] == cr.S_RELEASE


@need_fonts
def test_parity_pool1_full_uses_pool2_c69(tmp_path):
    from m4.test_create import add_b1, pool_img
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = rel_league_c(os.path.join(work, 'mk'),
                        pools={'POOL1.V20': pool_img(n_bat=24)}, mut=add_b1)
    st, _ = parity(tmp_path, [ENTER] + [DOWN] * 16 + [ord('D'), ord('Y')],
                   base=base)
    assert st['msg'] == 'RELEASED TO POOL2'


@need_fonts
def test_parity_pool_full_refusal_c69(tmp_path):
    """All four pools of 16 pitchers: POOL FULL, nothing written, the frame
    keeps FOOT_RELEASE's row (msg replaces the footer)."""
    from m4.test_create import pool_img
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = rel_league_c(os.path.join(work, 'mk'),
                        pools={'POOL%d.V20' % i: pool_img(n_pit=16)
                               for i in (1, 2, 3, 4)})
    st, _ = parity(tmp_path, [ENTER, ord('D'), ord('Y')], base=base)
    assert st['msg'] == 'POOL FULL' and st['screen'] == cr.S_RELEASE
    st, _ = parity(tmp_path, [ENTER, ord('D'), ord('Y'), ord('N')], base=base)
    assert st['screen'] == cr.S_SLOT


@need_fonts
def test_parity_no_reserve_refusal_c69(tmp_path):
    def mut(base):
        img = bytearray(open(os.path.join(base, 'BOS.V20'), 'rb').read())
        img[222] = 0xff
        open(os.path.join(base, 'BOS.V20'), 'wb').write(bytes(img))
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = rel_league_c(os.path.join(work, 'mk'), mut=mut)
    st, _ = parity(tmp_path, [ENTER, ord('D'), ord('Y')], base=base)
    assert st['msg'] == 'NO RESERVE' and st['screen'] == cr.S_RELEASE
    st, _ = parity(tmp_path, [ENTER, ord('D'), ord('Y'), 27], base=base)
    assert st['screen'] == cr.S_SLOT


@need_fonts
def test_parity_wrong_size_pool_skipped_c69(tmp_path):
    """A 100-byte POOL1 is skipped and left unchanged; the release uses POOL2."""
    from m4.test_create import add_b1
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = rel_league_c(os.path.join(work, 'mk'),
                        pools={'POOL1.V20': bytes(100)}, mut=add_b1)
    st, _ = parity(tmp_path, [ENTER] + [DOWN] * 16 + [ord('D'), ord('Y')],
                   base=base)
    assert st['msg'] == 'RELEASED TO POOL2'


@need_fonts
def test_parity_release_keys_c69(tmp_path):
    """D on an empty slot is a no-op; d opens; N and ESC back; lowercase y
    releases; the next key clears a shown message."""
    from m4.test_create import add_b1
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = rel_league_c(os.path.join(work, 'mk'), mut=add_b1)
    parity(tmp_path, [ENTER, DOWN, DOWN, ord('D')], base=base)
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [100, ord('N')], base=base)
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [100, 27], base=base)
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [100, 121], base=base)
    parity(tmp_path, [ENTER] + [DOWN] * 16 + [ord('D'), ord('Y'), ord('x')],
           base=base)
    parity(tmp_path, [ENTER, 0x1234, ord('D'), ord('Y'), 32], base=base)


def test_parity_foot_release_text_c69():
    """C69: the FOOT_RELEASE text matches, and the C source text matches."""
    assert cr.FOOT_RELEASE == 'Y RELEASE   N ESC BACK'
    src = open(os.path.join(HERE_C, 'create.c')).read()
    assert ('static const char *FOOT_RELEASE = "%s";' % cr.FOOT_RELEASE) in src


# ---------------------------------------------------------------- C76: TRADE parity
import glob  # noqa: E402

from m4.test_create import (trade_league, std_league, trade_keys, _bat, _pit, _pair,  # noqa: E402
                            _team, A_BATTERS, B_BATTERS, OTHER_TEAMS, slot_keys, T_KEY, Y_KEY,
                            N_KEY)
import rosters  # noqa: E402

TRADES_TXT = 'TRADES.TXT'


def _league_files(d):
    """{name: bytes} of the regular files of a league dir."""
    out = {}
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            out[name] = open(p, 'rb').read()
    return out


def trade_parity(tmp_path, keys, base):
    """parity() with synthetic fonts, plus every other file of the two leagues (TRADES.TXT
    included, present on both or neither) equal. Returns the Python state."""
    fonts = synth_fonts(tempfile.mkdtemp(dir=str(tmp_path)))
    st, cwd = parity(tmp_path, keys, base=base, fonts=fonts)
    work = os.path.dirname(cwd)
    py = _league_files(os.path.join(work, 'py_league'))
    cl = _league_files(os.path.join(work, 'c_league'))
    assert sorted(py) == sorted(cl)
    for name in py:
        assert py[name] == cl[name], name
    return st


def _std_base(tmp_path, **kw):
    work = tempfile.mkdtemp(dir=str(tmp_path))
    return std_league(os.path.join(work, 'mk'), **kw)


def test_parity_trade_screens_c76(tmp_path):
    """Frames of the three trade screens, the T on an empty slot and the ESC / N chain."""
    base = _std_base(tmp_path)
    for keys in ([ENTER, T_KEY],                                  # S_TRADE_TEAM
                 slot_keys(17) + [T_KEY], slot_keys(17) + [ord('t'), DOWN, DOWN],
                 slot_keys(17) + [T_KEY, ENTER],                  # S_TRADE_PICK
                 slot_keys(17) + [T_KEY, ENTER] + [DOWN] * 14 + [PGDN, PGUP, PGDN],
                 slot_keys(17) + [T_KEY, ENTER, DOWN, ENTER],     # ENTER on an empty slot
                 trade_keys(17, 19),                              # S_TRADE_OFFER
                 trade_keys(17, 19, tail=[ord('x')]),
                 trade_keys(17, 19, tail=[N_KEY]), trade_keys(17, 19, tail=[ord('n')]),
                 trade_keys(17, 19, tail=[ESC]), trade_keys(17, 19, tail=[ESC, ESC]),
                 trade_keys(17, 19, tail=[ESC, ESC, ESC]),
                 trade_keys(17, 19, tail=[ESC, ESC, ESC, ESC]),
                 [ENTER, DOWN, T_KEY],                            # T on an empty slot
                 [ENTER, DOWN, ord('t'), ENTER]):
        trade_parity(tmp_path, keys, base)


def test_parity_trade_team_rows_above_and_below_a_c76(tmp_path):
    """The team list without A for A = BOS, NYA, CHI and SLN, and the cursor restored on ESC."""
    base = _std_base(tmp_path)
    for a in (0, 2, 3, 4):
        for row in (0, 1, 2, 3):
            keys = [DOWN] * a + slot_keys(16) + [T_KEY] + [DOWN] * row
            trade_parity(tmp_path, keys, base)
            st = trade_parity(tmp_path, keys + [ENTER], base)
            assert st['screen'] == cr.S_TRADE_PICK
            st = trade_parity(tmp_path, keys + [ENTER, DOWN, DOWN, ESC], base)
            assert (st['screen'], st['cursor']) == (cr.S_TRADE_TEAM, row)
    trade_parity(tmp_path, [DOWN] * 3 + slot_keys(16) + [T_KEY, PGDN, PGUP, UP], base)


def test_parity_trade_accept_with_repair_c76(tmp_path):
    """The accepted trade: both V20 files byte for byte (headers repaired both sides) and the
    TRADES.TXT line, plus the S_SLOT frame with TRADE ACCEPTED."""
    base = _std_base(tmp_path, a_hdr={122: 17, 158: 2, 222: 18}, b_hdr={194: 19, 222: 21})
    st = trade_parity(tmp_path, trade_keys(17, 19, tail=[Y_KEY]), base)
    assert (st['screen'], st['msg']) == (cr.S_SLOT, 'TRADE ACCEPTED')
    st = trade_parity(tmp_path, trade_keys(17, 19, tail=[ord('y')]), base)
    assert st['msg'] == 'TRADE ACCEPTED'
    trade_parity(tmp_path, trade_keys(17, 19, tail=[Y_KEY, DOWN]), base)     # the message clears
    # no reserve to fill the places: repair leaves the bytes, both sides
    base2 = _std_base(tmp_path, a_hdr={122: 17, 158: 2, 194: 17}, b_hdr={194: 19})
    assert trade_parity(tmp_path, trade_keys(17, 19, tail=[Y_KEY]), base2)['msg'] \
        == 'TRADE ACCEPTED'


def test_parity_trade_pitchers_and_other_teams_c76(tmp_path):
    work = tempfile.mkdtemp(dir=str(tmp_path))
    a = _team(_pair(0, _pit('Dunn', 'Di', 40, 2)), _pair(1, _pit('Xan', 'Xi', 35, 7)))
    b = _team(_pair(0, _pit('Fry', 'Fo', 92, 10)), _pair(1, _pit('Gum', 'Gi', 86, 10)),
              _pair(2, _pit('Hob', 'Hu', 80, 10)), _pair(5, _pit('Ing', 'Io', 40, 2)))
    base = trade_league(os.path.join(work, 'mk'), a, b, others=OTHER_TEAMS)
    assert trade_parity(tmp_path, trade_keys(0, 5, tail=[Y_KEY]), base)['msg'] \
        == 'TRADE ACCEPTED'
    assert trade_parity(tmp_path, trade_keys(1, 5, tail=[Y_KEY]), base)['msg'] \
        == 'TRADE ACCEPTED'                                         # SP bonus: B has 3 SP
    for get in (0, 1, 2):
        assert trade_parity(tmp_path, trade_keys(0, get, tail=[Y_KEY]), base)['msg'] \
            == 'DECLINED: UNTOUCHABLE'
    # trade with CHI and SLN as B
    for row in (2, 3):
        trade_parity(tmp_path, trade_keys(0, 0, b=row, tail=[Y_KEY]), base)


def test_parity_trade_declines_c76(tmp_path):
    """Each decline message and frame; nothing written (files equal Python's, which equal the
    start)."""
    work = tempfile.mkdtemp(dir=str(tmp_path))
    a = _team(_pair(0, _pit('Dunn', 'Di', 40, 2)), _pair(16, _bat('Ok', 'A', 38)),
              _pair(17, _bat('Low', 'B', 37)), _pair(18, _bat('Axe', 'Al', 90)))
    b = dict(B_BATTERS)
    b.update(_pair(0, _pit('Fry', 'Fo', 92, 10)))
    base = trade_league(os.path.join(work, 'mk'), a, b, others=OTHER_TEAMS)
    start = _league_files(base)
    cases = ((0, 16, 'DECLINED: SAME TYPE ONLY'), (16, 0, 'DECLINED: SAME TYPE ONLY'),
             (18, 16, 'DECLINED: UNTOUCHABLE'), (18, 18, 'DECLINED: UNTOUCHABLE'),
             (17, 19, 'DECLINED: NOT ENOUGH VALUE'), (16, 19, 'TRADE ACCEPTED'))
    for give, get, msg in cases:
        st = trade_parity(tmp_path, trade_keys(give, get, tail=[Y_KEY]), base)
        assert st['msg'] == msg
    for give, get, msg in cases[:5]:
        st = trade_parity(tmp_path, trade_keys(give, get, tail=[Y_KEY, ord('y'), ord('x')]), base)
        assert st['msg'] == 0 and st['screen'] == cr.S_TRADE_OFFER
    assert _league_files(base) == start
    # a decline keeps the offer screen, N backs out of it
    st = trade_parity(tmp_path, trade_keys(17, 19, tail=[Y_KEY, ord('n')]), base)
    assert (st['screen'], st['cursor']) == (cr.S_TRADE_PICK, 19)


def test_parity_trade_need_bonus_c76(tmp_path):
    work = tempfile.mkdtemp(dir=str(tmp_path))
    a = _team(_pair(16, _bat('Need', 'A', 36, pos2=1)), _pair(17, _bat('Plain', 'B', 36)),
              _pair(18, _bat('Elbow', 'C', 36, pos2=3)), _pair(19, _bat('Inf', 'D', 36, pos2=11)))
    base = trade_league(os.path.join(work, 'mk'), a, B_BATTERS, others=OTHER_TEAMS)
    for give, msg in ((16, 'TRADE ACCEPTED'), (17, 'DECLINED: NOT ENOUGH VALUE'),
                      (18, 'DECLINED: NOT ENOUGH VALUE'), (19, 'DECLINED: NOT ENOUGH VALUE')):
        assert trade_parity(tmp_path, trade_keys(give, 19, tail=[Y_KEY]), base)['msg'] == msg
    # a B whose catcher covers C: the thinnest position is 3B (second position 3 and IF count)
    b = dict(B_BATTERS)
    b.update(_pair(22, _bat('Cat', 'Cy', 20, pos2=1)))
    base = trade_league(os.path.join(work, 'mk2'), a, b, others=OTHER_TEAMS)
    for give, msg in ((16, 'DECLINED: NOT ENOUGH VALUE'), (18, 'TRADE ACCEPTED'),
                      (19, 'TRADE ACCEPTED'), (17, 'DECLINED: NOT ENOUGH VALUE')):
        assert trade_parity(tmp_path, trade_keys(give, 19, tail=[Y_KEY]), base)['msg'] == msg


def _py_trades(base, keys, tmp_path):
    """TRADES.TXT bytes after the Python state machine runs keys on a copy of the league."""
    work = tempfile.mkdtemp(dir=str(tmp_path))
    lg = os.path.join(work, 'copy')
    shutil.copytree(base, lg)
    ctx = cr.load_ctx(lg, synth_fonts(os.path.join(work, 'fonts')), os.path.join(work, 'none'))
    st = cr.start_state()
    for k in keys:
        st, _ = cr.step(st, k, ctx)
    return open(os.path.join(lg, TRADES_TXT), 'rb').read()


def test_parity_trade_season_numbers_c76(tmp_path):
    """TRADES.TXT season = HISTORY.DAT seasons recorded + 1: 301 for a u16 of 300, 1 for a
    missing, a 3 byte, an empty and a directory HISTORY.DAT, 8 for a 6 byte one."""
    for hist, want in ((bytes([0, 0, 0, 0, 44, 1]) + bytes(26), b'301'), (None, b'1'),
                       (b'', b'1'), (bytes([1, 2, 3]), b'1'), (bytes([0, 0, 0, 0, 7, 0]), b'8'),
                       ('dir', b'1'), (bytes(32), b'1')):
        base = _std_base(tmp_path)
        h = os.path.join(base, 'HISTORY.DAT')
        if hist == 'dir':
            os.mkdir(h)
        elif hist is not None:
            open(h, 'wb').write(hist)
        trade_parity(tmp_path, trade_keys(17, 19, tail=[Y_KEY]), base)
        assert _py_trades(base, trade_keys(17, 19, tail=[Y_KEY]), tmp_path) \
            == b'TRADE %s BOS Bo Bell DET Hal Hart\r\n' % want


def test_parity_trades_txt_appended_c76(tmp_path):
    base = _std_base(tmp_path)
    old = b'TRADE 3 AAA Old One BBB Old Two\r\nTRADE 3 CCC x DDD y'
    open(os.path.join(base, TRADES_TXT), 'wb').write(old)
    keys = trade_keys(16, 19, tail=[Y_KEY, DOWN, DOWN, T_KEY, ENTER] + [DOWN] * 21
                      + [ENTER, Y_KEY])
    st = trade_parity(tmp_path, keys, base)
    assert st['msg'] == 'TRADE ACCEPTED'


def test_parity_trade_write_errors_c76(tmp_path):
    """TRADES.TXT a directory, and (not root) a read-only V20: TRADE FAILED, the other V20
    still written, no TRADES.TXT line; both sides alike."""
    base = _std_base(tmp_path)
    os.mkdir(os.path.join(base, TRADES_TXT))
    st = trade_parity(tmp_path, trade_keys(17, 19, tail=[Y_KEY]), base)
    assert st['msg'] == 'TRADE FAILED' and st['screen'] == cr.S_SLOT
    if os.geteuid() != 0:
        for locked in ('BOS.V20', 'DET.V20'):
            base = _std_base(tmp_path)
            os.chmod(os.path.join(base, locked), 0o444)
            try:
                st = trade_parity(tmp_path, trade_keys(17, 19, tail=[Y_KEY]), base)
            finally:
                os.chmod(os.path.join(base, locked), 0o644)
            assert st['msg'] == 'TRADE FAILED'


def test_parity_trade_no_other_team_c76(tmp_path):
    from m4.test_create import make_league
    work = tempfile.mkdtemp(dir=str(tmp_path))
    base = make_league(os.path.join(work, 'mk'), spec={0: (b'BOS', b'BOSTON')},
                       recs={0: A_BATTERS})
    for keys in ([ENTER] + [DOWN] * 16 + [T_KEY],
                 [ENTER] + [DOWN] * 16 + [T_KEY, ENTER, DOWN, PGDN],
                 [ENTER] + [DOWN] * 16 + [T_KEY, ESC]):
        trade_parity(tmp_path, keys, base)


def _wide_team(rng, n_pit, n_bat, base_v=30):
    recs = {}
    for s in range(n_pit):
        end = rng.choice([1, 2, 4, 6, 7, 10])
        v = 2 * end + 3 * rng.randint(4, 24)
        recs.update(_pair(s, _pit('P%d' % s, 'A', v, end)))
    for s in range(16, 16 + n_bat):
        recs.update(_pair(s, _bat('B%d' % s, 'A', base_v + rng.randint(0, 40),
                                  pos2=rng.choice([0, 0, 1, 3, 4, 10, 11]))))
    return recs


def trade_session(rng, n):
    """Random key walk over the trade screens: list keys, ENTER, ESC, T, Y, N."""
    vocab = [UP, DOWN, DOWN, DOWN, PGDN, PGUP, ENTER, ENTER, ENTER, ESC, T_KEY, T_KEY, ord('t'),
             Y_KEY, Y_KEY, ord('y'), N_KEY, ord('n'), ord('D'), ord('x')]
    return [DOWN] * rng.randint(0, 4) + [ENTER] + [rng.choice(vocab) for _ in range(n)]


@pytest.mark.parametrize('seed', [1, 2, 3, 4, 5, 6])
def test_parity_trade_random_sessions_c76(tmp_path, seed):
    import random
    rng = random.Random(seed)
    work = tempfile.mkdtemp(dir=str(tmp_path))
    others = {15: _wide_team(rng, 8, 14), 16: _wide_team(rng, 9, 12), 17: _wide_team(rng, 7, 15)}
    base = trade_league(os.path.join(work, 'mk'), _wide_team(rng, 9, 16),
                        _wide_team(rng, 10, 15), others=others,
                        a_hdr={111: 0, 122: 16, 158: 2, 194: 17, 222: 18, 223: 19},
                        b_hdr={111: 1, 122: 17, 158: 2, 194: 18, 222: 16})
    for _ in range(6):
        trade_parity(tmp_path, trade_session(rng, rng.randint(40, 160)), base)


def test_parity_trade_session_makes_trades_c76(tmp_path):
    """The random walk is not vacuous: over the seeds of the session test, accepted trades and
    every decline message occur."""
    import random
    seen = set()
    for seed in range(1, 7):
        rng = random.Random(seed)
        work = tempfile.mkdtemp(dir=str(tmp_path))
        others = {15: _wide_team(rng, 8, 14), 16: _wide_team(rng, 9, 12),
                  17: _wide_team(rng, 7, 15)}
        base = trade_league(os.path.join(work, 'mk'), _wide_team(rng, 9, 16),
                            _wide_team(rng, 10, 15), others=others)
        for _ in range(6):
            keys = trade_session(rng, rng.randint(40, 160))
            copy = os.path.join(work, 'run')
            shutil.rmtree(copy, ignore_errors=True)
            shutil.copytree(base, copy)
            ctx = cr.load_ctx(copy, synth_fonts(os.path.join(work, 'fonts')),
                              os.path.join(work, 'none'))
            st = cr.start_state()
            for k in keys:
                st, _ = cr.step(st, k, ctx)
                if st['msg'] in cr.MSG_TRADE:
                    seen.add(st['msg'])
    assert set(cr.MSG_TRADE[:4]) <= seen


def test_parity_trade_texts_c76():
    src = open(os.path.join(HERE_C, 'create.c')).read()
    for name in ('FOOT_TRADE_TEAM', 'FOOT_TRADE_PICK', 'FOOT_TRADE_OFFER'):
        assert ('static const char *%s = "%s";' % (name, getattr(cr, name))) in src
    for text in cr.MSG_TRADE:
        assert '"%s"' % text in src
    assert '"TRADE: PICK A TEAM"' in src and '"PROPOSE A TRADE"' in src
    assert cr.S_TRADE_TEAM == 6 and '#define S_TRADE_TEAM 6' in src
    assert '#define S_TRADE_PICK 7' in src and '#define S_TRADE_OFFER 8' in src


# ---------------------------------------------------------------- C76: trade.h against rosters.py
HARNESS_C = r'''
#include <stdio.h>
#include <stdlib.h>
#include "trade.h"

static uint8_t a[V20_SIZE], b[V20_SIZE];

int main(int argc, char **argv)
{
    FILE *f;
    unsigned long n, i;
    int s, give, get;
    if (argc != 3)
        return 2;
    f = fopen(argv[2], "rb");
    if (!f)
        return 2;
    if (fread(&n, sizeof n, 1, f) != 1)
        return 2;
    for (i = 0; i < n; i++) {
        if (argv[1][0] == 'v') {                 /* images: V, SP, need, top 3 per slot */
            if (fread(a, 1, V20_SIZE, f) != V20_SIZE)
                return 2;
            for (s = 0; s < 80; s++)
                printf("%ld %d\n", (long)value(RIMG(a, s)), sp_rp(RIMG(a, s)));
            printf("need %d\n", tr_need(a));
            for (s = 0; s < 40; s++)
                printf("top3 %d\n", IS_ON(a, s) ? tr_top3(a, s) : -1);
        } else {                                  /* verdict: give, get, image A, image B */
            give = fgetc(f);
            get = fgetc(f);
            if (fread(a, 1, V20_SIZE, f) != V20_SIZE || fread(b, 1, V20_SIZE, f) != V20_SIZE)
                return 2;
            printf("%d\n", tr_verdict(a, give, b, get));
        }
    }
    fclose(f);
    return 0;
}
'''


@pytest.fixture(scope='module')
def trade_harness(tmp_path_factory):
    d = tmp_path_factory.mktemp('trade_h')
    src = os.path.join(str(d), 'harness.c')
    open(src, 'w').write(HARNESS_C)
    exe = os.path.join(str(d), 'harness')
    r = subprocess.run(['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror',
                        '-I', HERE_C, '-o', exe, src], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def _run_harness(exe, mode, blob, count, tmp_path):
    path = os.path.join(str(tmp_path), 'cases.bin')
    open(path, 'wb').write(struct.pack('<Q', count) + blob)
    r = subprocess.run([exe, mode, path], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0
    return r.stdout.split('\n')[:-1]


def _rand_rec(rng, pitcher):
    rec = bytearray(143)
    rec[0:5] = b'ABCDE'
    rec[20] = rng.randint(17, 43)
    rec[21] = 100
    pos1 = 0 if pitcher else rng.randint(1, 9)
    if rng.random() < 0.08:
        pos1 = rng.randint(0, 15)                  # a stray group / pitcher code
    rec[31] = pos1 | (rng.choice([0, 0, 1, 2, 3, 5, 8, 10, 11, 12, 13, 14, 15]) << 4)
    for off in (0x1d, 0x4a, 0x4b, 0x5e, 0x86, 0x87):
        rec[off] = rng.randint(0, 255)
    rec[142] = rng.choice([0, 0, 0, 1, 2, 3, 4, 5, 5, 6, 77, 255])
    return bytes(rec)


def _rand_image(rng):
    img = bytearray(11735)
    for s in range(40):
        if rng.random() < 0.85:
            rec = _rand_rec(rng, s < 16 if rng.random() < 0.95 else s >= 16)
            img[295 + 143 * s:295 + 143 * (s + 1)] = rec
    return bytes(img)


def _guard_value(rec):
    try:
        return rosters.value(rec)
    except IndexError:
        return cr._value(rec)


def test_trade_h_value_sp_need_top3_match_python_c76(tmp_path, trade_harness):
    import random
    rng = random.Random(76)
    imgs = [_rand_image(rng) for _ in range(40)]
    imgs.append(bytes(11735))                                  # nobody named
    out = _run_harness(trade_harness, 'v', b''.join(imgs), len(imgs), tmp_path)
    k = 0
    for img in imgs:
        for s in range(80):
            rec = img[295 + 143 * s:295 + 143 * (s + 1)]
            v, sp = out[k].split()
            k += 1
            assert int(v) == _guard_value(rec), (s, rec.hex())
            assert int(sp) == (rosters.sp_rp(rec) == 'SP')
        assert out[k] == 'need %d' % cr.trade_need(img)
        k += 1
        for s in range(40):
            want = (s in cr.trade_top3(img, s < 16)) if img[295 + 143 * s] else -1
            assert int(out[k].split()[1]) == int(want)
            k += 1
    assert k == len(out)


def test_trade_h_value_equals_rosters_value_exactly_c76(tmp_path, trade_harness):
    """No guard: records whose grade byte is 0..5 (or whose age makes the grade moot) give
    rosters.value exactly, over the age range and the 16 position codes."""
    import random
    rng = random.Random(7)
    recs = []
    for _ in range(6000):
        rec = bytearray(_rand_rec(rng, rng.random() < 0.4))
        rec[142] = rng.randint(0, 5)
        rec[20] = rng.randint(0, 50)
        rec[31] = rng.randint(0, 255)
        recs.append(bytes(rec))
    blob = b''
    for i in range(0, len(recs), 80):
        chunk = recs[i:i + 80]
        im = bytearray(11735)
        for j, rec in enumerate(chunk):
            im[295 + 143 * j:295 + 143 * (j + 1)] = rec
        blob += bytes(im)
    n = (len(recs) + 79) // 80
    out = _run_harness(trade_harness, 'v', blob, n, tmp_path)
    k = 0
    for i in range(n):
        for j in range(80):
            idx = i * 80 + j
            v = int(out[k].split()[0])
            k += 1 + (0 if j < 79 else 41)
            if idx < len(recs):
                assert v == rosters.value(recs[idx]), recs[idx].hex()


def test_trade_h_verdict_matches_python_c76(tmp_path, trade_harness):
    import random
    rng = random.Random(1976)
    cases, blob = [], b''
    codes = {None: 0}
    codes.update({m: i + 1 for i, m in enumerate(cr.MSG_TRADE[:3])})
    for _ in range(700):
        a, b = _rand_image(rng), _rand_image(rng)
        give = rng.choice([s for s in range(40) if a[295 + 143 * s]] or [0])
        get = rng.choice([s for s in range(40) if b[295 + 143 * s]] or [0])
        if not a[295 + 143 * give] or not b[295 + 143 * get]:
            continue
        cases.append(codes[cr.trade_verdict({'image': a, 'bimage': b, 'give': give,
                                             'get': get})])
        blob += bytes([give, get]) + a + b
    out = _run_harness(trade_harness, 'x', blob, len(cases), tmp_path)
    assert [int(x) for x in out] == cases
    assert {0, 1, 2, 3} <= set(cases), sorted(set(cases))


def test_trade_h_synthetic_fixture_records_c76(tmp_path, trade_harness):
    """The fixtures of the Python tests: every record of the standard league's two team
    images (and the need / top 3 on them)."""
    work = tempfile.mkdtemp(dir=str(tmp_path))
    lg = std_league(os.path.join(work, 'L'))
    imgs = [cr.read_v20(lg, 'BOS'), cr.read_v20(lg, 'DET')]
    out = _run_harness(trade_harness, 'v', b''.join(imgs), 2, tmp_path)
    k = 0
    for img in imgs:
        for s in range(80):
            rec = img[295 + 143 * s:295 + 143 * (s + 1)]
            assert int(out[k].split()[0]) == rosters.value(rec)
            k += 1
        assert out[k] == 'need %d' % cr.trade_need(img)
        k += 41


def test_trade_h_real_stock_v20_c76(tmp_path, trade_harness):
    files = []
    for pat in ('/mnt/nvme/tlrb2/fixtures/t4/s1_pre/**/*.V20', '/mnt/nvme/tlrb2/files/*.V20',
                '/mnt/nvme/tlrb2/files/**/*.V20'):
        files += glob.glob(pat, recursive=True)
    imgs = []
    for p in sorted(set(files)):
        d = open(p, 'rb').read()
        if len(d) == 11735:
            imgs.append(d)
    if not imgs:
        pytest.skip('no real V20 under /mnt/nvme/tlrb2')
    imgs = imgs[:12]
    out = _run_harness(trade_harness, 'v', b''.join(imgs), len(imgs), tmp_path)
    k = 0
    for img in imgs:
        for s in range(80):
            rec = img[295 + 143 * s:295 + 143 * (s + 1)]
            assert int(out[k].split()[0]) == _guard_value(rec)
            k += 1
        assert out[k] == 'need %d' % cr.trade_need(img)
        k += 41


def test_trade_h_is_standalone_and_c89_clean_c76(tmp_path):
    """trade.h compiles alone (it includes repair.h) with -Werror and, as C89, with the
    declaration-after-statement warning on."""
    stub = os.path.join(str(tmp_path), 'stub.c')
    open(stub, 'w').write('#include <stdio.h>\n#include "trade.h"\n'
                          'int main(void){uint8_t r[143]={0};printf("%d\\n",(int)value(r));'
                          'return 0;}\n')
    for std in ('-std=c99', '-std=gnu89'):
        r = subprocess.run(['gcc', std, '-pedantic', '-Wall', '-Wextra', '-Werror',
                            '-Wdeclaration-after-statement', '-I', HERE_C, '-o',
                            os.path.join(str(tmp_path), 'stub'), stub],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_create_c_does_not_touch_rosters_sources_c76():
    """create.c includes trade.h and repair.h; the rosters / dynview sources stay out of it."""
    src = open(os.path.join(HERE_C, 'create.c')).read()
    assert '#include "trade.h"' in src and '#include "../repair.h"' in src
    assert 'rosters.c' not in src and 'dynview.c' not in src


def test_parity_trade_top3_ties_c76(tmp_path):
    """Four equal-V batters on B: ties go to the lower slot, so 16..18 are untouchable and 19
    is not (same files and frames both sides)."""
    work = tempfile.mkdtemp(dir=str(tmp_path))
    a = _team(_pair(16, _bat('Axe', 'Al', 90)), _pair(17, _bat('Bell', 'Bo', 50)))
    b = _team(*[_pair(16 + i, _bat('B%d' % i, 'X', 50)) for i in range(4)])
    base = trade_league(os.path.join(work, 'mk'), a, b, others=OTHER_TEAMS)
    for get, msg in ((16, 'DECLINED: UNTOUCHABLE'), (17, 'DECLINED: UNTOUCHABLE'),
                     (18, 'DECLINED: UNTOUCHABLE'), (19, 'TRADE ACCEPTED')):
        assert trade_parity(tmp_path, trade_keys(16, get, tail=[Y_KEY]), base)['msg'] == msg
    # pitchers tie the same way
    pa = _team(_pair(0, _pit('Hi', 'A', 92, 10)))
    pb = _team(*[_pair(i, _pit('P%d' % i, 'X', 40, 2)) for i in range(4)])
    base = trade_league(os.path.join(work, 'mk2'), pa, pb, others=OTHER_TEAMS)
    for get, msg in ((0, 'DECLINED: UNTOUCHABLE'), (2, 'DECLINED: UNTOUCHABLE'),
                     (3, 'TRADE ACCEPTED')):
        assert trade_parity(tmp_path, trade_keys(0, get, tail=[Y_KEY]), base)['msg'] == msg
