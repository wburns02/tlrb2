#!/usr/bin/env python3
"""T5b tests: DYNVIEW C port of tools/m4/dynview.py. Run:
  python3 -m pytest -q tools/m4/test_dynview_c.py
Host binary tools/m4/dynview_c/dynview_host is built at import via
build_dynview.py; DOS tests skip when DYNVIEW.EXE or dosbox-x is missing;
font-using tests skip when /mnt/nvme/tlrb2/files/MAIN.FNT is missing.
Every parity check runs dynview.render (Python) and the host binary with
/RAW and compares the 64000 B framebuffers."""
import os
import random
import struct
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import dynview
import history
import pytest
from m4.test_dynview import (make_data, write_player, write_season,
                             write_mileston, st)

WATCOM = '/mnt/nvme/tools/openwatcom'
HERE_C = os.path.join(HERE, 'dynview_c')
HOST = os.path.join(HERE_C, 'dynview_host')
EXE = os.path.join(HERE_C, 'DYNVIEW.EXE')
FILES = '/mnt/nvme/tlrb2/files'
DOSBOX = '/mnt/nvme/src/dosbox-x/src/dosbox-x'

FB_SIZE = 64000
PLAYER_TABLE = history.PLAYER_TABLE


def _build():
    r = subprocess.run([sys.executable, os.path.join(HERE_C, 'build_dynview.py')],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed:\n' + r.stdout + r.stderr)
    if not os.path.exists(HOST):
        raise RuntimeError('host binary missing after build')


_build()


def toks(seq):
    """key sequence -> /KEYS: token string (decimal, hex keys as 0x)."""
    out = []
    for k in seq:
        if k in (dynview.KEY_LEFT, dynview.KEY_RIGHT, dynview.KEY_UP,
                 dynview.KEY_DOWN, dynview.KEY_PGUP, dynview.KEY_PGDN):
            out.append('0x%04x' % k)
        else:
            out.append(str(k))
    return ','.join(out)


def run_host(league_dir, raw_path, keys=None, review=False, font_dir=None,
             extra=None):
    """Host binary with /RAW; returns the 64000 B framebuffer."""
    argv = [HOST]
    if review:
        argv.append('/REVIEW')
    if keys:
        argv.append('/KEYS:' + toks(keys))
    argv.append('/RAW:' + raw_path)
    argv.append(league_dir)
    if font_dir:
        argv.append(font_dir)
    if extra:
        argv = extra + argv[1:] if False else argv + extra
    r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f'host rc {r.returncode}: {r.stderr[:400]}'
    return open(raw_path, 'rb').read()


def fb_python(ldir, keys=None, review=False, font_dir=FILES):
    """Python reference with the same state after the same keys."""
    data = dynview.load_data(str(ldir), font_dir)
    s = (dynview.SCREEN_REVIEW, 0, 0) if review else (dynview.SCREEN_MENU, 0, 0)
    for k in (keys or []):
        s, _ex = dynview.step(s, k, data)
    return bytes(dynview.render(s, data))


NAMES = ['SMITH', 'JONES', 'BROWN', 'MCCORMACKSTE', 'MAY', 'jones']
FIRSTS = ['A', 'JOHN', '', 'E', 'ALEXANDER']


def big_history(league, n_entries=1500, n_seasons=64, hdr_seasons=70,
                ms_count=1400):
    """Big synthetic HISTORY.DAT: varied totals, statuses incl. 150 HoF,
    negative WAR10, zero AB/OUTS, odd name bytes; header seasons beyond the
    table; 1400 milestone records."""
    d = bytearray(32 + 64 * 128 + n_entries * 160)
    d[3] = 1
    d[4], d[5] = hdr_seasons & 255, (hdr_seasons >> 8) & 255
    d[6], d[7] = n_entries & 255, (n_entries >> 8) & 255
    rng = random.Random(0x5eed)
    for n in range(1, n_seasons + 1):
        write_season(d, n, b'ALA%02d' % (n % 100), b'NL%02d' % (n % 100),
                     awards=tuple((i * 7 + n) % n_entries for i in range(6)))
    hof_seasons = {}
    for i in range(n_entries):
        status = 1
        if i < 150:
            status = 3
            hof_seasons[i] = rng.randrange(1, 65)
        elif i % 4 == 0:
            status = 2
        pitcher = 1 if i % 5 == 0 else 0
        t = [0] * 25
        t[0] = rng.randrange(0, 3000)
        t[1] = 0 if i % 97 == 0 else rng.randrange(0, 9000)
        t[2] = rng.randrange(0, 3000) if i % 3 else 0
        t[5] = rng.randrange(0, 800)
        t[7] = rng.randrange(0, 2200)
        t[10] = rng.randrange(0, 900)
        t[13] = 0 if pitcher and i % 2 else rng.randrange(0, 350)
        t[15] = rng.randrange(0, 500) if pitcher else 0
        t[19] = 0 if i % 11 == 0 else rng.randrange(0, 6000)
        t[20] = rng.randrange(0, 2500)
        t[23] = rng.randrange(0, 4200)
        ab = t[1]
        h = min(t[2], ab)
        t[2] = h
        ts = list(t)
        ts[1] = rng.randrange(0, 3000)      # G: keep AVG sane, vary
        ts[2] = h
        war10 = rng.randrange(-400, 900)
        last = 'L%04d' % i
        if i % 7 == 0:
            last = last.lower()
        first = FIRSTS[i % len(FIRSTS)]
        if i % 50 == 0:
            first = bytes([128 + i % 64, 200]).decode('latin-1')
        elif i % 53 == 0:
            first = '\x01\x1f'
        write_player(d, i, last.encode('latin-1'), first.encode('latin-1'),
                     status=status, first_season=1, last_season=30,
                     seasons_played=rng.randrange(0, 25), pitcher=pitcher,
                     hof_season=hof_seasons.get(i, 0), war10=war10,
                     totals=ts, awards=(rng.randrange(0, 8), 0, 0,
                                        rng.randrange(0, 8), 0))
    (league / 'HISTORY.DAT').write_bytes(bytes(d))
    ms = []
    for j in range(ms_count):
        ms.append((rng.randrange(1, 71), rng.randrange(0, n_entries),
                   rng.randrange(0, 41), rng.randrange(0, 4000)))
    ms.sort()
    write_mileston(str(league / 'MILESTON.DAT'), ms)


def hof_page_count(ldir):
    """number of HoF rows (paging check helper)"""
    data = dynview.load_data(str(ldir), FILES)
    return len(dynview.hof_rows(data['hist']))


def leaders_total(ldir, cat):
    data = dynview.load_data(str(ldir), FILES)
    return dynview.leaders_count(data['hist'], cat)


def milestones_total(ldir):
    data = dynview.load_data(str(ldir), FILES)
    return len(dynview.milestone_rows(data['hist'], data['ms']))


def check_parity(ldir, tmp_path, tag, keys=None, review=False, font_dir=FILES):
    raw = str(tmp_path / (tag + '.RAW'))
    a = run_host(str(ldir), raw, keys=keys, review=review, font_dir=font_dir)
    b = fb_python(ldir, keys=keys, review=review, font_dir=font_dir)
    if a != b:
        i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]),
                 min(len(a), len(b)))
        x, y = i % 320, i // 320
        pytest.fail(f'{tag}: first diff at pixel ({x}, {y}): '
                    f'python {b[i] if i < len(b) else "?"} '
                    f'c {a[i] if i < len(a) else "?"}')
    return a


# ---------------- test 1: synthetic data, every screen ----------------

def test_synthetic_every_screen(tmp_path):
    ldir, _ = make_data(tmp_path)
    # every screen, every leaders category, pages 0 and 1 where they exist
    check_parity(ldir, tmp_path, 'menu')
    check_parity(ldir, tmp_path, 'hist')
    check_parity(ldir, tmp_path, 'hof')
    check_parity(ldir, tmp_path, 'ms')
    check_parity(ldir, tmp_path, 'review', review=True)
    for cat in range(dynview.N_CATS):
        check_parity(ldir, tmp_path, 'lead%d' % cat,
                     keys=[ord('3')] + [dynview.KEY_RIGHT] * cat)
    # page 1 when it exists: MVP awards has 28+ qualifying
    if leaders_total(ldir, 10) > dynview.ROWS_PER_PAGE:
        check_parity(ldir, tmp_path, 'lead10p1',
                     keys=[ord('3')] + [dynview.KEY_RIGHT] * 10
                     + [dynview.KEY_PGDN])


def test_synthetic_review_start(tmp_path):
    ldir, _ = make_data(tmp_path)
    check_parity(ldir, tmp_path, 'rev_start', review=True)


def test_synthetic_nav_sequences(tmp_path):
    """the key sequences of test_dynview's navigation tests"""
    ldir, _ = make_data(tmp_path)
    # test_paging_bounds sequence
    check_parity(ldir, tmp_path, 'pg1',
                 keys=[dynview.KEY_PGDN, dynview.KEY_PGUP])
    check_parity(ldir, tmp_path, 'pg2',
                 keys=[ord('3')] + [dynview.KEY_RIGHT] * 10
                 + [dynview.KEY_PGDN, dynview.KEY_PGUP, dynview.KEY_PGDN,
                    dynview.KEY_PGDN])
    # test_esc_and_enter_navigation sequence
    check_parity(ldir, tmp_path, 'nav1',
                 keys=[dynview.KEY_ESC])
    check_parity(ldir, tmp_path, 'nav2',
                 keys=[dynview.SCREEN_HISTORY, dynview.KEY_ESC])
    check_parity(ldir, tmp_path, 'nav3',
                 keys=[ord('5'), dynview.KEY_ENTER])
    # test_render_determinism_and_steps sequence
    check_parity(ldir, tmp_path, 'det',
                 keys=[dynview.KEY_PGDN, ord('3'), dynview.KEY_RIGHT,
                       dynview.KEY_PGDN, dynview.KEY_PGUP, dynview.KEY_LEFT,
                       dynview.KEY_ESC, ord('4'), dynview.KEY_PGDN, ord('5'),
                       dynview.KEY_ENTER, ord('2')])


# ---------------- test 2: 300 random key sequences ----------------

KEYS = [dynview.KEY_ESC, dynview.KEY_ENTER, ord('1'), ord('2'), ord('3'),
        ord('4'), ord('5'), ord('9'), dynview.KEY_LEFT, dynview.KEY_RIGHT,
        dynview.KEY_UP, dynview.KEY_DOWN, dynview.KEY_PGUP, dynview.KEY_PGDN]


def test_random_keys(tmp_path):
    ldir, _ = make_data(tmp_path)
    rng = random.Random(0x7105)
    for n in range(300):
        ln = rng.randrange(1, 15)
        seq = [rng.choice(KEYS) for _ in range(ln)]
        review = n % 2 == 1
        check_parity(ldir, tmp_path, 'rnd%03d' % n, keys=seq, review=review)


# ---------------- test 3: big synthetic history ----------------

def test_big_history_pages(tmp_path):
    league = tmp_path / 'bigleague'
    league.mkdir()
    big_history(league)
    # LIST_MAX applies: the top-K buffers cap at 1200 rows
    ldir = league
    check_parity(ldir, tmp_path, 'big_menu')
    check_parity(ldir, tmp_path, 'big_hist')
    check_parity(ldir, tmp_path, 'big_hof_p0')
    check_parity(ldir, tmp_path, 'big_hof_p1')
    nhof = hof_page_count(ldir)
    if nhof > 0:
        last_p = (nhof - 1) // dynview.ROWS_PER_PAGE
        keys = [ord('2')] + [dynview.KEY_PGDN] * last_p
        check_parity(ldir, tmp_path, 'big_hof_last', keys=keys)
    for cat in (0, 4, 5, 9):
        ncand = leaders_total(ldir, cat)
        pages = [0, 1, 50, (ncand - 1) // dynview.ROWS_PER_PAGE]
        for p in sorted(set(pages)):
            if p * dynview.ROWS_PER_PAGE >= ncand:
                continue
            keys = [ord('3')] + [dynview.KEY_RIGHT] * cat \
                 + [dynview.KEY_PGDN] * p
            check_parity(ldir, tmp_path, 'big_lead%d_p%d' % (cat, p),
                         keys=keys)
    check_parity(ldir, tmp_path, 'big_ms_p0')
    nms = milestones_total(ldir)
    for p in (0, 1, 50, (nms - 1) // dynview.ROWS_PER_PAGE):
        if p * dynview.ROWS_PER_PAGE >= min(nms, dynview.LIST_MAX):
            continue
        keys = [ord('4')] + [dynview.KEY_PGDN] * p
        check_parity(ldir, tmp_path, 'big_ms_p%d' % p, keys=keys)
    check_parity(ldir, tmp_path, 'big_review', review=True)


# ---------------- test 4: edge files ----------------

def _history_only(ldir, raw):
    (ldir / 'HISTORY.DAT').write_bytes(raw)


def test_edge_missing_history(tmp_path):
    ldir = tmp_path / 'l1'
    ldir.mkdir()
    for scr in range(6):
        check_parity(ldir, tmp_path, 'edge_mh_s%d' % scr,
                     keys=[ord('1') + scr] if scr else None)


def test_edge_empty_history(tmp_path):
    ldir = tmp_path / 'l2'
    ldir.mkdir()
    _history_only(ldir, b'')
    for scr in range(6):
        check_parity(ldir, tmp_path, 'edge_eh_s%d' % scr,
                     keys=[ord('1') + scr] if scr else None)


def test_edge_4byte_legacy(tmp_path):
    ldir = tmp_path / 'l3'
    ldir.mkdir()
    _history_only(ldir, bytes([0, 0x39, 0x05, 0]))
    for scr in range(6):
        check_parity(ldir, tmp_path, 'edge_4b_s%d' % scr,
                     keys=[ord('1') + scr] if scr else None)


def test_edge_32byte_zero_header(tmp_path):
    ldir = tmp_path / 'l4'
    ldir.mkdir()
    _history_only(ldir, bytes(32))
    for scr in range(6):
        check_parity(ldir, tmp_path, 'edge_32_s%d' % scr,
                     keys=[ord('1') + scr] if scr else None)


def test_edge_short_player_table(tmp_path):
    """HISTORY.DAT shorter than its player table (152 B into entry 0)"""
    ldir = tmp_path / 'l5'
    ldir.mkdir()
    d = bytearray(32 + 64 * 128 + 30)
    d[3] = 1
    d[4], d[5] = 1, 0
    d[6], d[7] = 3, 0
    d[32:32 + 128] = bytes(128)
    _history_only(ldir, bytes(d))
    for scr in range(6):
        check_parity(ldir, tmp_path, 'edge_pts%d' % scr,
                     keys=[ord('1') + scr] if scr else None)


def test_edge_header_count_larger(tmp_path):
    """header entry count larger than the file holds"""
    ldir = tmp_path / 'l6'
    ldir.mkdir()
    d = bytearray(32 + 64 * 128 + 2 * 160)
    d[3] = 1
    d[4], d[5] = 1, 0
    d[6], d[7] = 99, 0            # header says 99, file has 2
    write_season(d, 1, b'ALA01', b'NL01')
    for i in range(2):
        write_player(d, i, b'P%02d' % i, b'B', status=1, seasons_played=3,
                     totals=[5] * 25, war10=10 + i)
    _history_only(ldir, bytes(d))
    for scr in range(6):
        check_parity(ldir, tmp_path, 'edge_hcl%d' % scr,
                     keys=[ord('1') + scr] if scr else None)


def test_edge_missing_mileston(tmp_path):
    league = tmp_path / 'l7'
    league.mkdir()
    big_history(league, n_entries=40, ms_count=0)
    for scr in range(6):
        check_parity(league, tmp_path, 'edge_mm%d' % scr,
                     keys=[ord('1') + scr] if scr else None)


def test_edge_mileston_short_tail(tmp_path):
    """MILESTON.DAT with a 5 B tail (dropped like Python)"""
    league = tmp_path / 'l8'
    league.mkdir()
    big_history(league, n_entries=40, ms_count=0)
    raw = bytearray(open(str(league / 'MILESTON.DAT'), 'rb').read()
                    if (league / 'MILESTON.DAT').exists() else b'')
    ms = [(3, 0, 2, 3000), (2, 1, 5, 500)]
    write_mileston(str(league / 'MILESTON.DAT'), ms)
    with open(str(league / 'MILESTON.DAT'), 'ab') as f:
        f.write(bytes(5))         # 5 B tail
    for scr in range(6):
        check_parity(league, tmp_path, 'edge_mst%d' % scr,
                     keys=[ord('1') + scr] if scr else None)


# ---------------- test 5: real data ----------------

def test_real_data(tmp_path):
    real = '/mnt/nvme/tlrb2/t5/real'
    if not os.path.exists(os.path.join(real, 'HISTORY.DAT')):
        pytest.skip('real HISTORY.DAT missing')
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        pytest.skip('fonts missing')
    ldir = tmp_path / 'real'
    ldir.mkdir()
    for f in os.listdir(real):
        shutil.copy2(os.path.join(real, f), str(ldir / f))
    check_parity(ldir, tmp_path, 'real_menu')
    check_parity(ldir, tmp_path, 'real_hist')
    check_parity(ldir, tmp_path, 'real_hof')
    check_parity(ldir, tmp_path, 'real_ms')
    check_parity(ldir, tmp_path, 'real_review', review=True)
    for cat in range(dynview.N_CATS):
        check_parity(ldir, tmp_path, 'real_lead%d' % cat,
                     keys=[ord('3')] + [dynview.KEY_RIGHT] * cat)


# ---------------- test 6: errors ----------------

def test_errors_no_fonts(tmp_path):
    if not os.path.exists(HOST):
        pytest.skip('host binary missing')
    ldir = tmp_path / 'lg'
    ldir.mkdir()
    raw = str(tmp_path / 'out.RAW')
    r = subprocess.run([HOST, '/RAW:' + raw, '/FONTS:' if False else str(ldir),
                        str(tmp_path / 'nofonts')], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 2, r.returncode
    assert not os.path.exists(raw), 'RAW written despite font failure'


def test_host_interactive_usage(tmp_path):
    """host interactive (no /RAW) prints usage and exits 2"""
    r = subprocess.run([HOST], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.returncode
    assert 'usage' in (r.stderr + r.stdout).lower()


# ---------------- test 7: DOS build + headless DOSBox-X parity ----------------

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


def _dos_ready():
    return (os.path.exists(EXE) and os.path.isfile(DOSBOX)
            and os.access(DOSBOX, os.X_OK))


def _fonts_ready():
    return os.path.exists(os.path.join(FILES, 'MAIN.FNT'))


def test_dos_build():
    exe2 = os.path.join(HERE_C, 'DYNVIEW2.EXE')
    if not os.path.isdir(WATCOM):
        if os.path.exists(exe2):
            os.remove(exe2)
        pytest.skip('OpenWatcom missing')
    assert os.path.exists(EXE), 'DYNVIEW.EXE not built'
    with open(EXE, 'rb') as f:
        assert f.read(2) == b'MZ'
    # second build is byte-identical
    r = subprocess.run([sys.executable, os.path.join(HERE_C, 'build_dynview.py')],
                       cwd=HERE_C, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    shutil.copy2(EXE, exe2)
    r2 = subprocess.run([sys.executable, os.path.join(HERE_C, 'build_dynview.py')],
                        cwd=HERE_C, capture_output=True, text=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert open(EXE, 'rb').read() == open(exe2, 'rb').read(), \
        'second DYNVIEW.EXE build differs'
    os.remove(exe2)


def run_dos(cdir, bat_lines):
    """Write cdir/RUN.BAT (CRLF), run it under dosbox-x, return int(RC.TXT)."""
    shutil.copy2(EXE, os.path.join(cdir, 'DYNVIEW.EXE'))
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
    mounts = cdir
    cmds = ['-c', 'mount c ' + mounts]
    cmds += ['-c', 'c:', '-c', 'RUN.BAT', '-c', 'exit']
    proc = subprocess.run(
        [DOSBOX, '-silent', '-set', 'mixer nosound=true', '-set',
         'cpu cycles=max'] + cmds,
        capture_output=True, text=True, timeout=180, env=env)
    if not os.path.exists(rc_txt):
        raise AssertionError(f'RC.TXT missing rc={proc.returncode} '
                             f'out={proc.stdout[-400:]} err={proc.stderr[-400:]}')
    return int(open(rc_txt).read().strip() or 0)


def test_dos_parity(tmp_path):
    """Headless DOSBox-X: DYNVIEW.EXE /RAW:OUT.RAW /KEYS:51 LEAGUE FONTS and
    two more states, compared with Python."""
    if not _dos_ready():
        pytest.skip('DYNVIEW.EXE or dosbox-x missing')
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir, _ = make_data(tmp_path)
    d = str(tmp_path / 'dos')
    os.makedirs(d)
    # league and the three font files into C:, as directories LEAGUE and FONTS
    os.makedirs(os.path.join(d, 'LEAGUE'))
    os.makedirs(os.path.join(d, 'FONTS'))
    for f in os.listdir(str(ldir)):
        shutil.copy2(os.path.join(str(ldir), f),
                     os.path.join(d, 'LEAGUE', f))
    for f in ('MAIN.FNT', 'BOLD.FNT', 'DEFAULT.PAL'):
        shutil.copy2(os.path.join(FILES, f), os.path.join(d, 'FONTS', f))
    # state 1: /KEYS:51 (decimal 51 = '3' ASCII: opens CAREER LEADERS),
    # plus leaders cat 4 page 1 (/REVIEW start checked in the third state)
    for tag, args in (
            ('k51', 'DYNVIEW.EXE /RAW:OUT.RAW /KEYS:51 LEAGUE FONTS'),
            ('lead4p1',
             'DYNVIEW.EXE /RAW:OUT2.RAW /KEYS:51,0x4d00,0x4d00,0x4d00,0x4d00,'
             '0x4d,51 LEAGUE FONTS'),
            ('review', 'DYNVIEW.EXE /RAW:OUT3.RAW /REVIEW LEAGUE FONTS')):
        rc = run_dos(d, [args])
        assert rc == 0, f'{tag}: dos rc {rc}'
        rawname = 'OUT.RAW' if tag == 'k51' else ('OUT2.RAW' if tag == 'lead4p1'
                                                  else 'OUT3.RAW')
        dos_raw = open(os.path.join(d, rawname), 'rb').read()
        py = fb_python(ldir, keys=[51] if tag == 'k51' else
                       ([ord('3')] + [dynview.KEY_RIGHT] * 4
                        + [dynview.KEY_PGDN] if tag == 'lead4p1' else []),
                       review=(tag == 'review'))
        if dos_raw != py:
            i = next(k for k in range(min(len(dos_raw), len(py)))
                     if dos_raw[k] != py[k])
            pytest.fail(f'dos {tag}: first diff at pixel '
                        f'({i % 320}, {i // 320}): python {py[i]} c {dos_raw[i]}')


def test_dos_font_probe_second_drive(tmp_path):
    """fonts only on a second mounted drive (mount e), no FONT_DIR argument,
    /RAW parity."""
    if not _dos_ready():
        pytest.skip('DYNVIEW.EXE or dosbox-x missing')
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir, _ = make_data(tmp_path)
    d = str(tmp_path / 'dosfp')
    os.makedirs(d)
    os.makedirs(os.path.join(d, 'LEAGUE'))
    edir = str(tmp_path / 'edrive')
    os.makedirs(edir)
    for f in os.listdir(str(ldir)):
        shutil.copy2(os.path.join(str(ldir), f),
                     os.path.join(d, 'LEAGUE', f))
    for f in ('MAIN.FNT', 'BOLD.FNT', 'DEFAULT.PAL'):
        shutil.copy2(os.path.join(FILES, f), os.path.join(edir, f))
    bat = os.path.join(d, 'RUN.BAT')
    shutil.copy2(EXE, os.path.join(d, 'DYNVIEW.EXE'))
    with open(bat, 'wb') as f:
        f.write(b'DYNVIEW.EXE /RAW:OUT.RAW LEAGUE\r\n')
        for line in BAT_LADDER:
            f.write(line.encode('latin-1') + b'\r\n')
    rc_txt = os.path.join(d, 'RC.TXT')
    if os.path.exists(rc_txt):
        os.remove(rc_txt)
    env = dict(os.environ)
    env['SDL_VIDEODRIVER'] = 'dummy'
    env['SDL_AUDIODRIVER'] = 'dummy'
    proc = subprocess.run(
        [DOSBOX, '-silent', '-set', 'mixer nosound=true', '-set',
         'cpu cycles=max', '-c', 'mount c ' + d, '-c', 'mount e ' + edir,
         '-c', 'c:', '-c', 'RUN.BAT', '-c', 'exit'],
        capture_output=True, text=True, timeout=180, env=env)
    assert os.path.exists(rc_txt), \
        f'RC.TXT missing rc={proc.returncode} out={proc.stdout[-300:]}'
    rc = int(open(rc_txt).read().strip() or 0)
    assert rc == 0, rc
    assert os.path.exists(os.path.join(d, 'OUT.RAW')), \
        'no OUT.RAW: fonts not found on drive E'
    dos_raw = open(os.path.join(d, 'OUT.RAW'), 'rb').read()
    py = fb_python(ldir, font_dir=FILES)
    if dos_raw != py:
        i = next(k for k in range(min(len(dos_raw), len(py)))
                 if dos_raw[k] != py[k])
        pytest.fail(f'font probe: first diff at pixel ({i % 320}, {i // 320}): '
                    f'python {py[i]} c {dos_raw[i]}')


def test_dos_no_fonts_exit2(tmp_path):
    """No fonts anywhere (BAT ladder): exit 2."""
    if not _dos_ready():
        pytest.skip('DYNVIEW.EXE or dosbox-x missing')
    d = str(tmp_path / 'dosnf')
    os.makedirs(d)
    os.makedirs(os.path.join(d, 'LEAGUE'))
    open(os.path.join(d, 'LEAGUE', 'HISTORY.DAT'), 'wb').write(bytes(32))
    rc = run_dos(d, ['DYNVIEW.EXE /RAW:OUT.RAW LEAGUE'])
    assert rc == 2, rc
    assert not os.path.exists(os.path.join(d, 'OUT.RAW'))
