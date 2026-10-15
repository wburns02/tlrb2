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
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import dynview
import history
import pytest
import realign
import teamids
import m4.test_dynview as T
from m4.test_dynview import (make_data, write_player, write_season,
                             write_mileston, st, make_offseason, ROSTER_BODY,
                             big_league, make_awards, make_standings,
                             STAND_SEASONS, CLASSIC_SEASON, HALF_EAST, HALF_WEST,
                             FULL_SEASON, award_recs, award_league_ms,
                             lead_league_ms, LEAD_3, make_series, series_recs,
                             SERIES6, SERIES7, UNFINISHED5, TIED4, box_rec, write_box,
                             BOX_G0, write_team, write_standings,
                             write_team_v20_full, draft_managed_test_league,
                             DRAFT17, TRADE17, oc, write_maj)
from test_teamids import build_maj, CLASSIC

WATCOM = '/mnt/nvme/tools/openwatcom'
HERE_C = os.path.join(HERE, 'dynview_c')
HOST = os.path.join(HERE_C, 'dynview_host')
EXE = os.path.join(HERE_C, 'DYNVIEW.EXE')
FILES = os.environ.get('DYNVIEW_FILES', '/mnt/nvme/tlrb2/files')
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
    """key sequence -> /KEYS: token string (decimal, hex keys as 0x, Lx.y a click)."""
    out = []
    for k in seq:
        if isinstance(k, tuple):
            out.append('L%d.%d' % (k[1], k[2]))
        elif k in (dynview.KEY_LEFT, dynview.KEY_RIGHT, dynview.KEY_UP,
                   dynview.KEY_DOWN, dynview.KEY_PGUP, dynview.KEY_PGDN):
            out.append('0x%04x' % k)
        else:
            out.append(str(k))
    return ','.join(out)


def run_host(league_dir, raw_path, keys=None, review=False, font_dir=None,
             extra=None, offseason=False, title=False):
    """Host binary with /RAW; returns the 64000 B framebuffer."""
    argv = [HOST]
    if offseason:
        argv.append('/OFFSEASON')
    elif review:
        argv.append('/REVIEW')
    elif title:
        argv.append('/TITLE')
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


def fb_python(ldir, keys=None, review=False, font_dir=FILES, offseason=False,
              title=False):
    """Python reference with the same state after the same keys."""
    data = dynview.load_data(str(ldir), font_dir)
    if offseason:
        s = (dynview.SCREEN_OFFSEASON, 0, 16)
    elif review:
        s = (dynview.SCREEN_REVIEW, 0, 0)
    elif title:
        s = (dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG)
    else:
        s = (dynview.SCREEN_MENU, 0, 0)
    for k in (keys or []):
        if isinstance(k, tuple):              # ('L', x, y): a left click (C13.6)
            key, row = dynview.click_to_key(s, data, k[1], k[2])
            if key is None:
                continue
            if row is not None:
                s = dynview.cursor_to(s, row)
            s, _ex = dynview.step(s, key, data)
            continue
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


def twin_league(ldir, tmp_path, tag):
    """two copies of the league, one for the host binary and one for Python: a settings
    ENTER writes HISTORY.DAT, so the two runs must not share it"""
    base = tempfile.mkdtemp(prefix=tag + '_', dir=str(tmp_path))
    h, p = os.path.join(base, 'h'), os.path.join(base, 'p')
    shutil.copytree(str(ldir), h)
    shutil.copytree(str(ldir), p)
    return h, p


def history_bytes(d):
    path = os.path.join(d, 'HISTORY.DAT')
    return open(path, 'rb').read() if os.path.exists(path) else None


def check_parity(ldir, tmp_path, tag, keys=None, review=False, font_dir=FILES,
                 offseason=False, title=False):
    h, p = twin_league(ldir, tmp_path, tag)
    raw = str(tmp_path / (tag + '.RAW'))
    a = run_host(h, raw, keys=keys, review=review, font_dir=font_dir,
                 offseason=offseason, title=title)
    b = fb_python(p, keys=keys, review=review, font_dir=font_dir,
                  offseason=offseason, title=title)
    if a != b:
        i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]),
                 min(len(a), len(b)))
        x, y = i % 320, i // 320
        pytest.fail(f'{tag}: first diff at pixel ({x}, {y}): '
                    f'python {b[i] if i < len(b) else "?"} '
                    f'c {a[i] if i < len(a) else "?"}')
    if history_bytes(h) != history_bytes(p):
        pytest.fail(f'{tag}: HISTORY.DAT after the keys differs from Python')
    return a


# ---------------- test 1: synthetic data, every screen ----------------

def test_synthetic_every_screen(tmp_path):
    ldir, _ = make_data(tmp_path)
    # every screen, every leaders category, pages 0 and 1 where they exist
    check_parity(ldir, tmp_path, 'menu')
    check_parity(ldir, tmp_path, 'hist', keys=[48 + dynview.SCREEN_HISTORY])
    check_parity(ldir, tmp_path, 'hof', keys=[48 + dynview.SCREEN_HOF])
    check_parity(ldir, tmp_path, 'ms', keys=[48 + dynview.SCREEN_MILESTONES])
    check_parity(ldir, tmp_path, 'review', review=True)
    for cat in range(dynview.N_CATS):
        check_parity(ldir, tmp_path, 'lead%d' % cat,
                     keys=[ord('3')] + [dynview.KEY_RIGHT] * cat)
    # page 1 when it exists: MVP awards has 28+ qualifying
    if leaders_total(ldir, 10) > dynview.ROWS_PER_PAGE:
        check_parity(ldir, tmp_path, 'lead10p1',
                     keys=[ord('3')] + [dynview.KEY_RIGHT] * 10
                     + [dynview.KEY_PGDN])


def test_team_names_and_none_parity(tmp_path):
    """V20 team names (named, blank, short file, missing) and NO_AWARD = NONE."""
    ldir, _ = make_data(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    write_season(d, 3, b'ala03', b'nl03', awards=(0, 0xffff, 0xffff, 3, 0xffff, 5))
    write_season(d, 2, b'ALA02', b'NL02', awards=(0xffff, 7, 8, 0xffff, 10, 11))
    p.write_bytes(bytes(d))
    (ldir / 'ALA03.V20').write_bytes(b'PHILADELPHIA  \0clPHI' + bytes(60))
    (ldir / 'NL03.V20').write_bytes(bytes(80))
    (ldir / 'ALA02.V20').write_bytes(b'Chicago A')
    rev = [r[0] for r in dynview.rows((dynview.SCREEN_REVIEW, 0, 0), dynview.load_data(str(ldir)))]
    assert rev[0] == 'CHAMPION PHILADELPHIA' and 'AL CY YOUNG NONE' in rev
    check_parity(ldir, tmp_path, 'tn_hist', keys=[48 + dynview.SCREEN_HISTORY])
    check_parity(ldir, tmp_path, 'tn_review', review=True)


def test_title_parity(tmp_path):
    """/TITLE: welcome rows on a league with no season, the menu with history,
    ENTER (exit flag, state kept), a menu key, and ESC back to the plain menu."""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    empty = tmp_path / 'empty'
    empty.mkdir()
    check_parity(empty, tmp_path, 'title_new', title=True)
    check_parity(empty, tmp_path, 'title_new_enter', title=True, keys=[dynview.KEY_ENTER])
    check_parity(empty, tmp_path, 'title_new_hist', title=True, keys=[ord('1')])
    ldir, _ = make_data(tmp_path)
    check_parity(ldir, tmp_path, 'title_hist', title=True)
    check_parity(ldir, tmp_path, 'title_hist_enter', title=True, keys=[dynview.KEY_ENTER])
    check_parity(ldir, tmp_path, 'title_hist_lead', title=True, keys=[ord('3')])
    check_parity(ldir, tmp_path, 'title_hist_esc', title=True,
                 keys=[ord('2'), dynview.KEY_ESC])
    # /OFFSEASON and /REVIEW win over /TITLE
    raw = str(tmp_path / 'prec.RAW')
    a = run_host(str(ldir), raw, extra=['/TITLE'], offseason=True, font_dir=FILES)
    assert a == fb_python(ldir, offseason=True)
    a = run_host(str(ldir), raw, extra=['/TITLE'], review=True, font_dir=FILES)
    assert a == fb_python(ldir, review=True)


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

KEYS = [dynview.KEY_ESC, dynview.KEY_ENTER, ord('0'), ord('1'), ord('2'), ord('3'),
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


def test_random_keys_standings_league(tmp_path):
    """random navigation on the league with games: standings tables under the keys"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_standings(tmp_path)
    rng = random.Random(0x5a7d)
    for n in range(60):
        ln = rng.randrange(1, 12)
        seq = [rng.choice(KEYS) for _ in range(ln)]
        check_parity(ldir, tmp_path, 'srnd%03d' % n, keys=seq)


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
    check_parity(ldir, tmp_path, 'real_hist', keys=[48 + dynview.SCREEN_HISTORY])
    check_parity(ldir, tmp_path, 'real_hof', keys=[48 + dynview.SCREEN_HOF])
    check_parity(ldir, tmp_path, 'real_ms', keys=[48 + dynview.SCREEN_MILESTONES])
    check_parity(ldir, tmp_path, 'real_review', review=True)
    for cat in range(dynview.N_CATS):
        check_parity(ldir, tmp_path, 'real_lead%d' % cat,
                     keys=[ord('3')] + [dynview.KEY_RIGHT] * cat)
    # the offseason walk: every phase, page 0; retirees and free agents page 1
    for phase in range(6):
        check_offseason(ldir, tmp_path, 'real_off%d' % phase, phase)
    check_offseason(ldir, tmp_path, 'real_off_retire_p1', 1, page=1)
    check_offseason(ldir, tmp_path, 'real_off_fa_p1', 4, page=1)
    check_offseason(ldir, tmp_path, 'real_off_nl5', 5, launched=False)


# ---------------- test 5b: offseason ----------------

def off_keys(phase, page=0, launched=True):
    """keys that reach an offseason phase page: ENTER per phase (from /OFFSEASON, or
    from MENU with '6' when not launched), then PGDN per page"""
    keys = [13] * phase + [dynview.KEY_PGDN] * page
    return keys if launched else [ord('6')] + keys


def check_offseason(ldir, tmp_path, tag, phase, page=0, launched=True,
                    font_dir=FILES):
    return check_parity(ldir, tmp_path, tag, keys=off_keys(phase, page, launched),
                        offseason=launched, font_dir=font_dir)


def big_rosters():
    """ROSTERS.TXT past the bounds: 450 DRAFT lines (only the first DRAFT_KEEP
    count), 450 picks of which 50 find no kept DRAFT, 1500 free agent signings and
    700 resolving trades (1400 rows, past LIST_MAX)"""
    out = []
    for k in range(450):
        out.append(b'DRAFT CLASALW2 Draft%03d\r\n' % k)
    for k in range(450):
        out.append(b'SIGN CLASNLE4 Draft%03d CLASALW2\r\n' % k)
    for k in range(1500):
        out.append(b'SIGN CLASALE1 Free%04d pool\n' % k)
    for k in range(700):
        out.append(b'TRADE CLASALE1 Pl%03d CLASNLW4 Q%03d\r\n' % (k, k))
    return b''.join(out)


def test_offseason_every_phase(tmp_path):
    ldir = make_offseason(tmp_path)
    for launched in (True, False):
        for phase in range(6):
            for page in (0, 1):
                check_offseason(ldir, tmp_path,
                                'off_%d_%d_%d' % (launched, phase, page),
                                phase, page, launched)


def test_offseason_missing_rosters(tmp_path):
    ldir = make_offseason(tmp_path, rosters=None)
    for phase in range(6):
        check_offseason(ldir, tmp_path, 'off_norost%d' % phase, phase)


def test_offseason_no_history(tmp_path):
    ldir = tmp_path / 'oeh'
    ldir.mkdir()
    (ldir / 'ROSTERS.TXT').write_bytes(ROSTER_BODY)
    for phase in range(6):
        check_offseason(ldir, tmp_path, 'off_nohist%d' % phase, phase)
    check_offseason(ldir, tmp_path, 'off_nohist_nl', 0, launched=False)


ODD_ROSTERS = (
    b'DRAFT clasale1 Pat  Doe\r\n'                  # lower-case stem, spaces collapse
    b'DRAFT CLASNLE3 J\xe9ss\x00e Cl\r\n'               # high byte and NUL in a name
    b'SIGN  CLASALW7   Pat Doe   CLASALE1\r\n'       # pick: stems match in any case
    b'SIGN CLASNLE4 J\xe9ss\x00e Cl pool\r\n'          # free agent from the pool
    b'SIGN CLASNLE4 J\xe9ss\x00e Cl CLASNLE3\r\n'      # pick (same bytes, same name)
    b'SIGN Cl\xe9 Pat\rDoe pool\r\n'                  # odd team token and a CR inside
    b'TRADE clasnle3 x\xe9 clasalw2 y\x00z\r\n'        # lower-case team token
    b'TRADE CLASALE1 Pat Doe LONGSTEM9 Y Z\r\n'        # no team token: ignored
    b'\tSIGN CLASALW7 Tab Name pool\r\n'               # tab first: not an event
    b'SIGN CLASALW7 Pat Doe POOL\r\n')                 # POOL in capitals is the pool


def test_offseason_odd_bytes(tmp_path):
    ldir = make_offseason(tmp_path, rosters=ODD_ROSTERS)
    picks, fa = dynview.sign_split(dynview.load_data(str(ldir), FILES)['events'])
    assert len(picks) == 2 and len(fa) == 3
    check_offseason(ldir, tmp_path, 'odd_draft', 2)
    check_offseason(ldir, tmp_path, 'odd_fa', 4)
    check_offseason(ldir, tmp_path, 'odd_trades', 3)
    check_offseason(ldir, tmp_path, 'odd_ready', 5)


def test_offseason_big_rosters(tmp_path):
    ldir = make_offseason(tmp_path, rosters=big_rosters())
    data = dynview.load_data(str(ldir), FILES)
    # the caps are exercised: draft picks stop at 400, FA and trade rows at LIST_MAX
    assert len(dynview.offseason_body((dynview.SCREEN_OFFSEASON, 0, 20), data)[1]) \
        == dynview.LIST_MAX
    check_offseason(ldir, tmp_path, 'big_retire1', 1)
    check_offseason(ldir, tmp_path, 'big_draft0', 2)
    check_offseason(ldir, tmp_path, 'big_draft_last', 2, page=33)
    check_offseason(ldir, tmp_path, 'big_trades0', 3)
    check_offseason(ldir, tmp_path, 'big_trades_last', 3, page=99)
    check_offseason(ldir, tmp_path, 'big_fa_p1', 4, page=1)
    check_offseason(ldir, tmp_path, 'big_fa_last', 4, page=99)
    check_offseason(ldir, tmp_path, 'big_ready', 5)
    check_offseason(ldir, tmp_path, 'big_ready_nl', 5, launched=False)


# ---------------- test 5c: hub, DYNASTY SETTINGS, ABOUT, /MENU ----------------

SET_SCREEN = dynview.SCREEN_SETTINGS
ABOUT_SCREEN = dynview.SCREEN_ABOUT
HUB_STATE = (dynview.SCREEN_MENU, 0, 0)
DOWN, UP = dynview.KEY_DOWN, dynview.KEY_UP
PGDN, PGUP = dynview.KEY_PGDN, dynview.KEY_PGUP
ESC, ENTER = dynview.KEY_ESC, dynview.KEY_ENTER


def settings_league(d, n_teams=20):
    """league dir d (made) with HISTORY.DAT, MILESTON.DAT, a MAJ of n_teams teams and
    their V20 files (t00 .. t19: lg 0..15 AL, 16..19 NL)"""
    d.mkdir()
    ldir, _ = make_data(d)
    big_league(ldir, n_teams)
    return ldir


SETTINGS_SEQS = [
    ('open', [55]),
    ('era1', [55, ENTER]),
    ('era_cycle', [55, ENTER, ENTER, ENTER, ENTER]),
    ('team0', [55, DOWN, ENTER]),
    ('team_nl', [55] + [DOWN] * 16 + [ENTER]),        # lg 16, the first NL team
    ('last_clamped', [55] + [DOWN] * 25 + [ENTER]),   # cursor stops on the last row
    ('pages', [55, PGDN, ENTER, PGDN, ENTER, PGUP, ENTER, PGUP, PGUP, ENTER]),
    ('toggle_twice', [55, DOWN, ENTER, ENTER, DOWN, ENTER, UP, UP, ENTER]),
    ('esc_back_in', [55, DOWN, ENTER, ESC, 55, ENTER]),
    ('esc_hub', [55, ESC]),
    ('hub_then_settings', [ord('7'), DOWN, DOWN, ENTER]),
    ('bad_keys', [55, ord('9'), ord('x'), 0x4b00, 0x4d00, ENTER]),
]


def test_settings_key_sequences_parity(tmp_path):
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = settings_league(tmp_path / 'lg')
    for tag, keys in SETTINGS_SEQS:
        check_parity(ldir, tmp_path, 'set_' + tag, keys=keys)


def test_settings_and_about_no_history_file(tmp_path):
    """no HISTORY.DAT: the settings rows still show; ENTER creates the file (32 B)"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = tmp_path / 'nohist'
    ldir.mkdir()
    big_league(ldir, 20)
    check_parity(ldir, tmp_path, 'nh_open', keys=[55])
    check_parity(ldir, tmp_path, 'nh_toggle', keys=[55, ENTER, DOWN, ENTER, PGDN, ENTER])
    check_parity(ldir, tmp_path, 'nh_about', keys=[56, PGDN, PGDN])
    check_parity(ldir, tmp_path, 'nh_hub')
    # no MAJ at all: the ERA RULES row only
    bare = tmp_path / 'bare'
    bare.mkdir()
    check_parity(bare, tmp_path, 'bare_set', keys=[55, DOWN, ENTER, ENTER])


ABOUT_SEQS = [[56], [56, PGDN], [56, PGDN, PGDN], [56, PGDN, PGDN, PGDN],
              [56, PGDN, PGDN, PGDN, PGDN], [56, PGDN, PGDN, PGDN, PGDN, PGDN],
              [56, PGDN, PGUP, PGUP, PGUP, PGUP], [56, ENTER, DOWN, UP]]


def test_about_pages_parity(tmp_path):
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'hist').mkdir()
    ldir, _ = make_data(tmp_path / 'hist')
    empty = tmp_path / 'empty'
    empty.mkdir()
    for n, keys in enumerate(ABOUT_SEQS):
        check_parity(ldir, tmp_path, 'about_h%d' % n, keys=keys)
        check_parity(empty, tmp_path, 'about_e%d' % n, keys=keys)


def test_hub_and_title_new_rows_parity(tmp_path):
    if not _fonts_ready():
        pytest.skip('fonts missing')
    empty = tmp_path / 'empty'
    empty.mkdir()
    ldir = settings_league(tmp_path / 'lg')
    check_parity(empty, tmp_path, 'hub_e')
    check_parity(ldir, tmp_path, 'hub_h')
    check_parity(ldir, tmp_path, 'hub_h8', keys=[56])
    check_parity(empty, tmp_path, 'title_e_set', title=True, keys=[55])
    check_parity(empty, tmp_path, 'title_e_about', title=True, keys=[56])
    check_parity(ldir, tmp_path, 'title_h_set', title=True, keys=[55, DOWN, ENTER])
    check_parity(ldir, tmp_path, 'title_h_about', title=True, keys=[56, PGDN])


def test_random_settings_keys(tmp_path):
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = settings_league(tmp_path / 'lg')
    rng = random.Random(0x5e77)
    keys = [55, 56, ENTER, ENTER, UP, DOWN, PGUP, PGDN, ESC, ord('1'), ord('5'),
            ord('7'), ord('8'), ord('9')]
    for n in range(150):
        seq = [rng.choice(keys) for _ in range(rng.randrange(1, 30))]
        check_parity(ldir, tmp_path, 'rset%03d' % n, keys=seq)


def menu_host(ldir, raw, cwd, extra=()):
    """host /MENU run from cwd (the directory that holds CONTROL); returns the frame"""
    r = subprocess.run([HOST, *extra, '/MENU', '/RAW:' + raw, str(ldir), FILES],
                       capture_output=True, text=True, timeout=300, cwd=str(cwd))
    assert r.returncode == 0, f'host rc {r.returncode}: {r.stderr[:400]}'
    return open(raw, 'rb').read()


CONTROL_IN = {0: b'\x01\x08\x00\x00\x00\x00\x00\xff\xff',
              1: b'\x01\x09\x00\x00\x00\x00\x00\xff\xff',
              2: b'\x01\x0a\x00\x00\x00\x00\x00\xff\xff',
              3: b'\x01\x0b\x00\x00\x00\x00\x00\xff\xff'}
CONTROL_OUT = b'\x01\x01\x00\x00\x00\x00\x00\xff\xff'
MENU_STATE = {0: HUB_STATE, 1: HUB_STATE, 2: (SET_SCREEN, 0, 0), 3: (ABOUT_SCREEN, 0, 0)}


def test_menu_control_items(tmp_path):
    """/MENU: the frame equals Python --control for every CONTROL item; CONTROL[1] is
    CONTROL[0] afterwards"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = settings_league(tmp_path / 'lg')
    data = dynview.load_data(str(ldir), FILES)
    for item in (0, 1, 2, 3):
        tag = 'ctl%d' % item
        hcwd, pcwd = tmp_path / (tag + '_hc'), tmp_path / (tag + '_pc')
        hcwd.mkdir()
        pcwd.mkdir()
        (hcwd / 'CONTROL').write_bytes(CONTROL_IN[item])
        (pcwd / 'CONTROL').write_bytes(CONTROL_IN[item])
        h, p = twin_league(ldir, tmp_path, tag)
        a = menu_host(h, str(tmp_path / (tag + '_h.RAW')), hcwd)
        raw_p = str(tmp_path / (tag + '_p.RAW'))
        dynview.main(['--control', str(pcwd / 'CONTROL'), '--raw', raw_p, p, FILES])
        b = open(raw_p, 'rb').read()
        assert a == b, tag
        assert a == bytes(dynview.render(MENU_STATE[item], data)), tag
        assert (hcwd / 'CONTROL').read_bytes() == CONTROL_OUT, tag
        assert (pcwd / 'CONTROL').read_bytes() == CONTROL_OUT, tag


def test_menu_flag_precedence_and_no_control(tmp_path):
    """/MENU with no CONTROL file: the hub, and no CONTROL is created; /REVIEW and /TITLE
    win over the item, and CONTROL is still returned"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = settings_league(tmp_path / 'lg')
    data = dynview.load_data(str(ldir), FILES)
    nocwd = tmp_path / 'nocwd'
    nocwd.mkdir()
    h, _ = twin_league(ldir, tmp_path, 'noctl')
    a = menu_host(h, str(tmp_path / 'noctl.RAW'), nocwd)
    assert a == bytes(dynview.render(HUB_STATE, data))
    assert not (nocwd / 'CONTROL').exists()
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    (cwd / 'CONTROL').write_bytes(CONTROL_IN[2])
    h, _ = twin_league(ldir, tmp_path, 'prec_rev')
    a = menu_host(h, str(tmp_path / 'prec_rev.RAW'), cwd, extra=['/REVIEW'])
    assert a == bytes(dynview.render((dynview.SCREEN_REVIEW, 0, 0), data))
    assert (cwd / 'CONTROL').read_bytes() == CONTROL_OUT
    (cwd / 'CONTROL').write_bytes(CONTROL_IN[3])
    h, _ = twin_league(ldir, tmp_path, 'prec_title')
    a = menu_host(h, str(tmp_path / 'prec_title.RAW'), cwd, extra=['/TITLE'])
    assert a == bytes(dynview.render((dynview.SCREEN_MENU, 0, dynview.TITLE_FLAG), data))
    assert (cwd / 'CONTROL').read_bytes() == CONTROL_OUT


# ---------------- test 5d: SEASON AWARDS (hub key 9) ----------------

LEFT, RIGHT = dynview.KEY_LEFT, dynview.KEY_RIGHT
AWARD_SEQS = [
    ('hub', []),                                     # the nine hub rows
    ('open', [57]),
    ('left1', [57, LEFT]),
    ('left2', [57, LEFT, LEFT]),
    ('left_stays', [57, LEFT, LEFT, LEFT, LEFT]),    # season 1 stays
    ('back', [57, LEFT, LEFT, RIGHT, RIGHT, RIGHT]),  # RIGHT at the newest stays
    ('pages', [57, PGDN, PGDN, PGDN, PGDN, PGUP]),   # 4 pages, PGDN stops at the last
    ('page_then_left', [57, PGDN, LEFT, PGDN]),      # LEFT resets the page
    ('left_then_pages', [57, LEFT, PGDN, PGDN, PGDN]),  # season 2 has one page
    ('page_then_left_stays', [57, PGDN, LEFT, LEFT, LEFT, PGDN]),
    ('esc', [57, ESC]),
    ('enter', [57, ENTER]),
    ('esc_back_in', [57, ESC, 57, LEFT]),
    ('milestones', [52]),
    ('milestones_p1', [52, PGDN]),
    ('hub_then_awards', [57, ESC, 56, ESC, 57]),
]


def test_awards_key_sequences_parity(tmp_path):
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_awards(tmp_path)
    for tag, keys in AWARD_SEQS:
        check_parity(ldir, tmp_path, 'aw_' + tag, keys=keys)
    check_parity(ldir, tmp_path, 'aw_review', review=True)
    check_parity(ldir, tmp_path, 'aw_title', title=True)
    check_parity(ldir, tmp_path, 'aw_title_9', title=True, keys=[57])
    check_parity(ldir, tmp_path, 'aw_title_9_left', title=True, keys=[57, LEFT])
    check_parity(ldir, tmp_path, 'aw_about', keys=[56, PGDN, PGDN])


def test_awards_past_history_table_parity(tmp_path):
    """a header of 70 recorded seasons: cat 5 shows season 65, past the table, with no
    records: one message row"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_awards(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[4], d[5] = 70, 0
    p.write_bytes(bytes(d))
    check_parity(ldir, tmp_path, 'aw_p70_open', keys=[57])
    check_parity(ldir, tmp_path, 'aw_p70_s65', keys=[57] + [LEFT] * 5)
    check_parity(ldir, tmp_path, 'aw_p70_s65_pg', keys=[57] + [LEFT] * 5 + [PGDN])
    check_parity(ldir, tmp_path, 'aw_p70_s64', keys=[57] + [LEFT] * 6)


def test_awards_no_history_parity(tmp_path):
    if not _fonts_ready():
        pytest.skip('fonts missing')
    empty = tmp_path / 'empty'
    empty.mkdir()
    check_parity(empty, tmp_path, 'aw_nh_open', keys=[57])
    check_parity(empty, tmp_path, 'aw_nh_left', keys=[57, LEFT, RIGHT, PGDN])


def test_leaders_parity(tmp_path):
    """the 58-row season (40 award and 18 leader rows) on every page, then MILESTONES
    and REVIEW beside it"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'lead').mkdir()
    ldir = make_awards(tmp_path / 'lead', ms=lead_league_ms())
    for p in range(5):
        check_parity(ldir, tmp_path, 'ld_p%d' % p, keys=[57] + [PGDN] * p)
    check_parity(ldir, tmp_path, 'ld_last_stays', keys=[57] + [PGDN] * 6)
    check_parity(ldir, tmp_path, 'ld_left_pgdn', keys=[57, LEFT, PGDN])
    check_parity(ldir, tmp_path, 'ld_milestones', keys=[52])
    check_parity(ldir, tmp_path, 'ld_review', review=True)


def test_leaders_al_only_parity(tmp_path):
    """season 3 with the AL leaders only (49 rows): KEYS 57 then PGDN, and every page"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'al').mkdir()
    ldir = make_awards(tmp_path / 'al', ms=award_league_ms() + award_recs(3, LEAD_3[:9]))
    check_parity(ldir, tmp_path, 'al_57_pgdn', keys=[57, PGDN])
    check_parity(ldir, tmp_path, 'al_pages', keys=[57] + [PGDN] * 4)


def test_leaders_stray_kinds_parity(tmp_path):
    """kinds 127, 137, 159, 169 and 200 beside the leaders, and a season 1 with only a
    stray record (its six-winner fallback stays)"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'stray').mkdir()
    stray = award_recs(3, [(127, 2, 5), (137, 2, 5), (159, 2, 5), (169, 2, 5), (200, 2, 5)])
    stray += award_recs(1, [(169, 4, 9)])
    ldir = make_awards(tmp_path / 'stray', ms=lead_league_ms(extra=stray))
    check_parity(ldir, tmp_path, 'stray_57_pgdn', keys=[57, PGDN])
    check_parity(ldir, tmp_path, 'stray_p3', keys=[57] + [PGDN] * 3)
    check_parity(ldir, tmp_path, 'stray_s1', keys=[57, LEFT, LEFT])
    check_parity(ldir, tmp_path, 'stray_milestones', keys=[52, PGDN])
    check_parity(ldir, tmp_path, 'stray_review', review=True)


def test_leaders_cap_64_parity(tmp_path):
    """68 records for season 3: the first 64 rows, six pages with the last one 4 rows"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'cap').mkdir()
    extra = award_recs(3, [(128, i, 300) for i in (1, 2, 4, 6, 7, 8, 9, 10, 11, 21)])
    ldir = make_awards(tmp_path / 'cap', ms=lead_league_ms(extra=extra))
    check_parity(ldir, tmp_path, 'cap_p5', keys=[57] + [PGDN] * 5)
    check_parity(ldir, tmp_path, 'cap_p6', keys=[57] + [PGDN] * 6)


# ---------------- test 5e: SEASON STANDINGS (hub key 0) ----------------

STAND_SEQS = [
    ('hub', []),                                        # the ten hub rows
    ('open', [48]),
    ('left1', [48, LEFT]),
    ('left2', [48, LEFT, LEFT]),                        # season 1
    ('left_stays', [48, LEFT, LEFT, LEFT, LEFT]),       # season 1 stays
    ('back', [48, LEFT, LEFT, RIGHT, RIGHT, RIGHT]),    # RIGHT at the newest stays
    ('pages', [48, LEFT, LEFT, PGDN, PGDN, PGDN, PGUP]),   # 30 rows: 3 pages
    ('left_stays_page', [48, LEFT, LEFT, PGDN, LEFT, PGDN]),
    ('page_then_left', [48, LEFT, PGDN, LEFT, PGDN]),   # LEFT resets the page
    ('season2_pgdn', [48, LEFT, PGDN]),                 # season 2: one page
    ('season3_pgdn', [48, PGDN]),                       # the message row: one page
    ('esc', [48, ESC]),
    ('enter', [48, ENTER]),
    ('esc_back_in', [48, ESC, 48, LEFT]),
    ('hub_then_standings', [48, ESC, 57, ESC, 48]),
    ('awards_then_standings', [57, LEFT, ESC, 48, LEFT]),
]


def test_standings_key_sequences_parity(tmp_path):
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_standings(tmp_path)
    for tag, keys in STAND_SEQS:
        check_parity(ldir, tmp_path, 'st_' + tag, keys=keys)
    check_parity(ldir, tmp_path, 'st_review', review=True)
    check_parity(ldir, tmp_path, 'st_title', title=True)
    check_parity(ldir, tmp_path, 'st_title_0', title=True, keys=[48])
    check_parity(ldir, tmp_path, 'st_title_0_left', title=True, keys=[48, LEFT])
    check_parity(ldir, tmp_path, 'st_about', keys=[56, PGDN, PGDN])


def test_standings_past_history_table_parity(tmp_path):
    """a header of 70 recorded seasons: cat 0 shows season 70, past the table; cat 5
    season 65 and cat 6 season 64 (no games in its entry): one message row each"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_standings(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[4], d[5] = 70, 0
    p.write_bytes(bytes(d))
    check_parity(ldir, tmp_path, 'st_p70_open', keys=[48])
    check_parity(ldir, tmp_path, 'st_p70_s65', keys=[48] + [LEFT] * 5)
    check_parity(ldir, tmp_path, 'st_p70_s64_pg', keys=[48] + [LEFT] * 6 + [PGDN])


def test_standings_no_history_parity(tmp_path):
    if not _fonts_ready():
        pytest.skip('fonts missing')
    empty = tmp_path / 'empty'
    empty.mkdir()
    check_parity(empty, tmp_path, 'st_nh_open', keys=[48])
    check_parity(empty, tmp_path, 'st_nh_left', keys=[48, LEFT, RIGHT, PGDN])
    check_parity(empty, tmp_path, 'st_nh_title', title=True, keys=[48])
    # every season screen's title on a league with no recorded season (no SEASON 0)
    check_parity(empty, tmp_path, 'rv_nh_open', keys=[53])
    check_parity(empty, tmp_path, 'rv_nh_title', title=True, keys=[53])


def test_standings_classic_parity(tmp_path):
    """the CLASSIC shape as the newest season: four division blocks on 3 pages"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_standings(tmp_path, seasons=STAND_SEASONS[:2] + [CLASSIC_SEASON])
    check_parity(ldir, tmp_path, 'st_cl_p1', keys=[48])
    check_parity(ldir, tmp_path, 'st_cl_p2', keys=[48, PGDN])
    check_parity(ldir, tmp_path, 'st_cl_p3', keys=[48, PGDN, PGDN])
    check_parity(ldir, tmp_path, 'st_cl_p3_end', keys=[48, PGDN, PGDN, PGDN])
    check_parity(ldir, tmp_path, 'st_cl_pgup', keys=[48, PGDN, PGDN, PGUP])
    check_parity(ldir, tmp_path, 'st_cl_s2_pgdn', keys=[48, LEFT, PGDN])


def test_standings_one_division_parity(tmp_path):
    """a league with games in one division only (AL WEST as the newest season, AL EAST
    the one before) next to a split NL: one block under the league name"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_standings(tmp_path, seasons=[HALF_EAST, HALF_WEST])
    check_parity(ldir, tmp_path, 'st_half_west', keys=[48])
    check_parity(ldir, tmp_path, 'st_half_east', keys=[48, LEFT])


def test_standings_full_36_parity(tmp_path):
    """all 32 ids played: 4 headers and 32 teams, 36 rows on 3 full pages"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_standings(tmp_path, seasons=[FULL_SEASON])
    check_parity(ldir, tmp_path, 'st_full_p1', keys=[48])
    check_parity(ldir, tmp_path, 'st_full_p2', keys=[48, PGDN])
    check_parity(ldir, tmp_path, 'st_full_p3', keys=[48, PGDN, PGDN])
    check_parity(ldir, tmp_path, 'st_full_p3_end', keys=[48, PGDN, PGDN, PGDN])


# ---------------- test 5f: WORLD SERIES (hub key W or w) ----------------

# season 3 (the newest) is SERIES7 and season 2 SERIES6; season 1 has no game record
SERIES_SEQS = [
    ('hub', []),
    ('open', [87]),
    ('open_lower', [119]),
    ('pgdn', [87, PGDN]),                               # 7 games: page 2
    ('pgdn_stays', [87, PGDN, PGDN, PGDN]),
    ('pgdn_pgup', [87, PGDN, PGUP]),
    ('left', [87, LEFT]),                               # season 2: 6 games, page 1
    ('left_pgdn', [87, LEFT, PGDN]),                    # page 2: games 5..6 and the summary
    ('left_pgdn_stays', [87, LEFT, PGDN, PGDN]),
    ('left_left_msg', [87, LEFT, LEFT]),                # season 1: the message row
    ('msg_pgdn', [87, LEFT, LEFT, PGDN]),
    ('left_stays', [87, LEFT, LEFT, LEFT, LEFT]),
    ('right', [87, LEFT, LEFT, RIGHT, RIGHT, RIGHT]),
    ('esc', [87, ESC]),
    ('enter', [87, ENTER]),
    ('esc_back_in', [87, ESC, 119, RIGHT]),
    ('hub_then_w', [56, ESC, 119, PGDN]),
    ('w_then_standings', [119, ESC, 48, LEFT]),
    ('standings_then_w', [48, ESC, 119, LEFT]),
]


def test_series_key_sequences_parity(tmp_path):
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_series(tmp_path, series_recs(3, SERIES7) + series_recs(2, SERIES6))
    for tag, keys in SERIES_SEQS:
        check_parity(ldir, tmp_path, 'sr_' + tag, keys=keys)
    check_parity(ldir, tmp_path, 'sr_review', review=True)
    check_parity(ldir, tmp_path, 'sr_title', title=True)
    check_parity(ldir, tmp_path, 'sr_title_w', title=True, keys=[119])
    check_parity(ldir, tmp_path, 'sr_title_w_pgdn', title=True, keys=[119, PGDN])


def test_series_six_game_pages_parity(tmp_path):
    """6 games as the newest season: page 1 (games 1..4) and page 2 (games 5..6, WINS 4-2)"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'six').mkdir()
    ldir = make_series(tmp_path / 'six', series_recs(3, SERIES6))
    check_parity(ldir, tmp_path, 'sr6_p1', keys=[87])
    check_parity(ldir, tmp_path, 'sr6_p2', keys=[87, PGDN])
    check_parity(ldir, tmp_path, 'sr6_p2_end', keys=[87, PGDN, PGDN])


def test_series_variants_parity(tmp_path):
    """a tie (SERIES, TIED 2-2) with game 2 lacking its kind 201 record and a duplicate
    of game 1's records after them, and a 3-2 lead (LEADS) of the first game's home"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'var').mkdir()
    dup = [(3, 0 * 256 + 16, 192, 1 * 256 + 9), (3, 1 * 256 + 1, 200, 0)]
    ldir = make_series(tmp_path / 'var', series_recs(3, TIED4, no_he=(1,)) + dup
                       + series_recs(2, UNFINISHED5))
    check_parity(ldir, tmp_path, 'var_tie', keys=[87])
    check_parity(ldir, tmp_path, 'var_tie_p2', keys=[87, PGDN])
    check_parity(ldir, tmp_path, 'var_lead', keys=[87, LEFT])
    check_parity(ldir, tmp_path, 'var_msg', keys=[87, LEFT, LEFT])


def test_series_past_history_table_parity(tmp_path):
    """a header of 70 seasons: season 70 and season 65 are past the table (one message
    row), season 64 has its records"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'past').mkdir()
    ldir = make_series(tmp_path / 'past', series_recs(64, UNFINISHED5)
                       + series_recs(65, SERIES6) + series_recs(70, SERIES7))
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[4], d[5] = 70, 0
    p.write_bytes(bytes(d))
    check_parity(ldir, tmp_path, 'srp_70', keys=[87])
    check_parity(ldir, tmp_path, 'srp_65', keys=[87] + [LEFT] * 5)
    check_parity(ldir, tmp_path, 'srp_64', keys=[87] + [LEFT] * 6)
    check_parity(ldir, tmp_path, 'srp_64_pgdn', keys=[87] + [LEFT] * 6 + [PGDN])


def test_series_kinds_off_other_screens_parity(tmp_path):
    """kinds 192..207 beside the award and leader records: MILESTONES, LAST SEASON REVIEW
    and SEASON AWARDS (every season) show what they show without them"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'koff').mkdir()
    kinds = [(3, 9, kind, 7) for kind in range(192, 208)]
    ldir = make_awards(tmp_path / 'koff', ms=award_league_ms() + series_recs(3, SERIES6)
                       + kinds)
    check_parity(ldir, tmp_path, 'koff_ms', keys=[52])
    check_parity(ldir, tmp_path, 'koff_ms_p1', keys=[52, PGDN])
    check_parity(ldir, tmp_path, 'koff_review', review=True)
    check_parity(ldir, tmp_path, 'koff_aw', keys=[57])
    check_parity(ldir, tmp_path, 'koff_aw_s2', keys=[57, LEFT, PGDN])
    check_parity(ldir, tmp_path, 'koff_aw_s3', keys=[57, LEFT, LEFT])


# ---------------- test 5g: BOX SCORE (WORLD SERIES keys 1..7) ----------------

def box_ws_league(tmp_path):
    """season 3 with 7 games (SERIES7) and season 2 with 6 (SERIES6); the box records: game 1
    (BOX_G0, 9 rows), game 3 (36 batting records, 40 rows); game 2 has none"""
    (tmp_path / 'box').mkdir()
    ldir = make_series(tmp_path / 'box', series_recs(3, SERIES7) + series_recs(2, SERIES6))
    write_box(ldir, BOX_G0 + [box_rec(3, 2, 0, k % 30, (k + 1, 0, 0, 0, 0, 0, 0, 0))
                              for k in range(36)])
    return ldir


def test_box_pages_parity(tmp_path):
    """the 40 row box of game 3 on pages 0 and 2 (and PGDN past its last page), the 9 row
    box of game 1 on page 0"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = box_ws_league(tmp_path)
    check_parity(ldir, tmp_path, 'box_g3_p0', keys=[87, 51])
    check_parity(ldir, tmp_path, 'box_g3_p2', keys=[87, 51, PGDN, PGDN])
    check_parity(ldir, tmp_path, 'box_g3_p3', keys=[87, 51, PGDN, PGDN, PGDN, PGDN])
    check_parity(ldir, tmp_path, 'box_g1_p0', keys=[87, 49])
    check_parity(ldir, tmp_path, 'box_g1_pgdn', keys=[87, 49, PGDN])


def test_box_managed_mask_parity(tmp_path):
    """C18: the box score's team header carries no managed star, in C as in Python,
    with every mask bit set"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = box_ws_league(tmp_path)
    write_mask(ldir, 0xFFFFFFFF)
    check_parity(ldir, tmp_path, 'box_g1_mask', keys=[87, 49])
    check_parity(ldir, tmp_path, 'box_g3_mask', keys=[87, 51])


def test_box_ws_footer_and_message_parity(tmp_path):
    """WORLD SERIES with its new footer, the message row (game 2 has no box records, nor
    does a league whose BOXSCORE.DAT is missing), ESC back to the series of a box, and the
    keys that are not game keys"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = box_ws_league(tmp_path)
    check_parity(ldir, tmp_path, 'box_ws', keys=[87])
    check_parity(ldir, tmp_path, 'box_ws_left', keys=[87, LEFT])
    check_parity(ldir, tmp_path, 'box_msg', keys=[87, 50])
    check_parity(ldir, tmp_path, 'box_msg_esc', keys=[87, 50, ESC])
    check_parity(ldir, tmp_path, 'box_left_esc', keys=[87, LEFT, 49, ESC])
    check_parity(ldir, tmp_path, 'box_not_game', keys=[87, 56, 48])
    (tmp_path / 'nofile').mkdir()
    ldir = make_series(tmp_path / 'nofile', series_recs(3, SERIES7))
    check_parity(ldir, tmp_path, 'box_nofile', keys=[87, 49, PGDN])


def test_box_key_walk_parity(tmp_path):
    """W, 3, RIGHT, LEFT, PGDN, ESC: game 3's box, the next game (a message row), back to
    game 3, its page 1, then the series"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = box_ws_league(tmp_path)
    check_parity(ldir, tmp_path, 'box_walk', keys=[87, 51, RIGHT, LEFT, PGDN, ESC])
    check_parity(ldir, tmp_path, 'box_walk_back', keys=[87, 51, RIGHT, LEFT, PGDN, ESC, 119])


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


def _synth_fonts_ready():
    """a DYNVIEW_FILES override with its own MAIN.FNT also counts (no game files needed)"""
    return FILES != '/mnt/nvme/tlrb2/files' or _fonts_ready()


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
             '0x5100 LEAGUE FONTS'),
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


def test_dos_offseason_parity(tmp_path):
    """Headless DOSBox-X: /OFFSEASON draft and free agent pages, and menu key 6 to the
    ready phase (not launched), compared with Python on the same league files."""
    if not _dos_ready():
        pytest.skip('DYNVIEW.EXE or dosbox-x missing')
    if not _fonts_ready():
        pytest.skip('fonts missing')
    fa30 = b''.join(b'SIGN CLASALW7 Player%02d pool\r\n' % k for k in range(30))
    d = str(tmp_path / 'dosoff')
    os.makedirs(os.path.join(d, 'LEAGUE'))
    os.makedirs(os.path.join(d, 'FONTS'))
    for f in ('MAIN.FNT', 'BOLD.FNT', 'DEFAULT.PAL'):
        shutil.copy2(os.path.join(FILES, f), os.path.join(d, 'FONTS', f))
    cases = (('draft', 'DYNVIEW.EXE /RAW:D1.RAW /OFFSEASON /KEYS:13,13 LEAGUE FONTS',
              ROSTER_BODY, [13, 13]),
             ('fa_p1', 'DYNVIEW.EXE /RAW:D2.RAW /OFFSEASON /KEYS:13,13,13,13,20736 '
              'LEAGUE FONTS', fa30, [13, 13, 13, 13, dynview.KEY_PGDN]),
             ('ready', 'DYNVIEW.EXE /RAW:D3.RAW /KEYS:54,13,13,13,13,13 LEAGUE FONTS',
              ROSTER_BODY, [ord('6'), 13, 13, 13, 13, 13]))
    for tag, line, rosters, keys in cases:
        os.makedirs(str(tmp_path / ('py_' + tag)))
        ldir = make_offseason(tmp_path / ('py_' + tag), rosters=rosters)
        for f in os.listdir(str(ldir)):
            shutil.copy2(os.path.join(str(ldir), f), os.path.join(d, 'LEAGUE', f))
        rawname = line.split('/RAW:')[1].split(' ')[0]
        rc = run_dos(d, [line])
        assert rc == 0, f'{tag}: dos rc {rc}'
        dos_raw = open(os.path.join(d, rawname), 'rb').read()
        py = fb_python(ldir, keys=keys, offseason=(tag != 'ready'))
        if dos_raw != py:
            i = next(k for k in range(min(len(dos_raw), len(py)))
                     if dos_raw[k] != py[k])
            pytest.fail(f'dos offseason {tag}: first diff at pixel '
                        f'({i % 320}, {i // 320}): python {py[i]} c {dos_raw[i]}')


def test_dos_settings_parity(tmp_path):
    """Headless DOSBox-X: DYNVIEW.EXE /RAW:OUT.RAW /KEYS:55,0x5000,13 LEAGUE FONTS (open
    DYNASTY SETTINGS, move to the first team, toggle it); the frame and the HISTORY.DAT
    bytes are compared with Python on the same league"""
    if not _dos_ready():
        pytest.skip('DYNVIEW.EXE or dosbox-x missing')
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = settings_league(tmp_path / 'lg')
    d = str(tmp_path / 'dosset')
    os.makedirs(os.path.join(d, 'LEAGUE'))
    os.makedirs(os.path.join(d, 'FONTS'))
    for f in os.listdir(str(ldir)):
        shutil.copy2(os.path.join(str(ldir), f), os.path.join(d, 'LEAGUE', f))
    for f in ('MAIN.FNT', 'BOLD.FNT', 'DEFAULT.PAL'):
        shutil.copy2(os.path.join(FILES, f), os.path.join(d, 'FONTS', f))
    rc = run_dos(d, ['DYNVIEW.EXE /RAW:OUT.RAW /KEYS:55,0x5000,13 LEAGUE FONTS'])
    assert rc == 0, f'dos rc {rc}'
    dos_raw = open(os.path.join(d, 'OUT.RAW'), 'rb').read()
    h, p = twin_league(ldir, tmp_path, 'dosset_py')
    py = fb_python(p, keys=[55, dynview.KEY_DOWN, 13], font_dir=FILES)
    if dos_raw != py:
        i = next(k for k in range(min(len(dos_raw), len(py)))
                 if dos_raw[k] != py[k])
        pytest.fail(f'dos settings: first diff at pixel ({i % 320}, {i // 320}): '
                    f'python {py[i]} c {dos_raw[i]}')
    assert open(os.path.join(d, 'LEAGUE', 'HISTORY.DAT'), 'rb').read() == history_bytes(p), \
        'dos HISTORY.DAT differs from Python'


def test_dos_awards_parity(tmp_path):
    """Headless DOSBox-X: DYNVIEW.EXE /RAW:OUT.RAW /KEYS:57,0x4b00 LEAGUE FONTS (open
    SEASON AWARDS, step back to season 2) on the award league, compared with Python"""
    if not _dos_ready():
        pytest.skip('DYNVIEW.EXE or dosbox-x missing')
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_awards(tmp_path)
    d = str(tmp_path / 'dosaw')
    os.makedirs(os.path.join(d, 'LEAGUE'))
    os.makedirs(os.path.join(d, 'FONTS'))
    for f in os.listdir(str(ldir)):
        shutil.copy2(os.path.join(str(ldir), f), os.path.join(d, 'LEAGUE', f))
    for f in ('MAIN.FNT', 'BOLD.FNT', 'DEFAULT.PAL'):
        shutil.copy2(os.path.join(FILES, f), os.path.join(d, 'FONTS', f))
    rc = run_dos(d, ['DYNVIEW.EXE /RAW:OUT.RAW /KEYS:57,0x4b00 LEAGUE FONTS'])
    assert rc == 0, f'dos rc {rc}'
    dos_raw = open(os.path.join(d, 'OUT.RAW'), 'rb').read()
    py = fb_python(ldir, keys=[57, dynview.KEY_LEFT], font_dir=FILES)
    if dos_raw != py:
        i = next(k for k in range(min(len(dos_raw), len(py)))
                 if dos_raw[k] != py[k])
        pytest.fail(f'dos awards: first diff at pixel ({i % 320}, {i // 320}): '
                    f'python {py[i]} c {dos_raw[i]}')


def test_dos_standings_parity(tmp_path):
    """Headless DOSBox-X: DYNVIEW.EXE /RAW:OUT.RAW /KEYS:48,0x5100 LEAGUE FONTS (open
    SEASON STANDINGS, PGDN) compared with Python. The newest season is the CLASSIC shape
    (3 pages), so the PGDN lands on page 2 (the newest season of make_standings has no
    games, one message row)"""
    if not _dos_ready():
        pytest.skip('DYNVIEW.EXE or dosbox-x missing')
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_standings(tmp_path, seasons=STAND_SEASONS[:2] + [CLASSIC_SEASON])
    d = str(tmp_path / 'dosst')
    os.makedirs(os.path.join(d, 'LEAGUE'))
    os.makedirs(os.path.join(d, 'FONTS'))
    for f in os.listdir(str(ldir)):
        shutil.copy2(os.path.join(str(ldir), f), os.path.join(d, 'LEAGUE', f))
    for f in ('MAIN.FNT', 'BOLD.FNT', 'DEFAULT.PAL'):
        shutil.copy2(os.path.join(FILES, f), os.path.join(d, 'FONTS', f))
    rc = run_dos(d, ['DYNVIEW.EXE /RAW:OUT.RAW /KEYS:48,0x5100 LEAGUE FONTS'])
    assert rc == 0, f'dos rc {rc}'
    dos_raw = open(os.path.join(d, 'OUT.RAW'), 'rb').read()
    py = fb_python(ldir, keys=[48, dynview.KEY_PGDN], font_dir=FILES)
    if dos_raw != py:
        i = next(k for k in range(min(len(dos_raw), len(py)))
                 if dos_raw[k] != py[k])
        pytest.fail(f'dos standings: first diff at pixel ({i % 320}, {i // 320}): '
                    f'python {py[i]} c {dos_raw[i]}')


def test_dos_series_parity(tmp_path):
    """Headless DOSBox-X: DYNVIEW.EXE /RAW:OUT.RAW /KEYS:87,0x5100 LEAGUE FONTS (open
    WORLD SERIES, PGDN) on the 6 game series, compared with Python: page 2 with WINS 4-2"""
    if not _dos_ready():
        pytest.skip('DYNVIEW.EXE or dosbox-x missing')
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_series(tmp_path, series_recs(3, SERIES6))
    d = str(tmp_path / 'dossr')
    os.makedirs(os.path.join(d, 'LEAGUE'))
    os.makedirs(os.path.join(d, 'FONTS'))
    for f in os.listdir(str(ldir)):
        shutil.copy2(os.path.join(str(ldir), f), os.path.join(d, 'LEAGUE', f))
    for f in ('MAIN.FNT', 'BOLD.FNT', 'DEFAULT.PAL'):
        shutil.copy2(os.path.join(FILES, f), os.path.join(d, 'FONTS', f))
    rc = run_dos(d, ['DYNVIEW.EXE /RAW:OUT.RAW /KEYS:87,0x5100 LEAGUE FONTS'])
    assert rc == 0, f'dos rc {rc}'
    dos_raw = open(os.path.join(d, 'OUT.RAW'), 'rb').read()
    py = fb_python(ldir, keys=[87, dynview.KEY_PGDN], font_dir=FILES)
    if dos_raw != py:
        i = next(k for k in range(min(len(dos_raw), len(py)))
                 if dos_raw[k] != py[k])
        pytest.fail(f'dos series: first diff at pixel ({i % 320}, {i // 320}): '
                    f'python {py[i]} c {dos_raw[i]}')


# ---------------- C17: offseason draft POS and the managed-team marks ----------------

C17_ROSTERS = (DRAFT17 + TRADE17
               + b'SIGN CLASALW7 Lou Green pool\r\n'
                 b'SIGN CLASALW2 Bobby Holmes CLASNLW4\r\n'
                 b'SIGN CLASNLW4 Lou Green pool\r\n')


def c17_league(tmp_path, tag, records, mask, rosters=C17_ROSTERS):
    """make_offseason league with the SEATTLE team file full size (records), a MAJ of
    the three teams (BOSTON 0, SEATTLE 7, NEW YORK N 20) and HISTORY mask mask."""
    (tmp_path / tag).mkdir()
    ldir = draft_managed_test_league(tmp_path / tag, rosters, mask)
    write_team_v20_full(ldir, 'CLASALW7', records, name='SEATTLE')
    return ldir


def test_c17_draft_pos_parity(tmp_path):
    """Python vs host framebuffers on the draft screen: the full-file fixture (a found
    pick gets its POS name, one without a match ''), mask 0 and the mask set, and a pick
    whose team file is missing (POS '')."""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    # mask 0, one record found (slot 0) and one not on the file (the CLASALW2 pick)
    ldir = c17_league(tmp_path, 'c17 zero', {0: ('Lou Green', 5), 1: ('Bobby Holmes', 0)}, 0)
    check_offseason(ldir, tmp_path, 'c17_zero_draft', 2)
    # the same with SEATTLE's mask bit set
    ldir = c17_league(tmp_path, 'c17 set', {0: ('Lou Green', 5), 1: ('Bobby Holmes', 0)},
                      1 << 7)
    check_offseason(ldir, tmp_path, 'c17_set_draft', 2)
    # a pick whose team file is missing: POS ''
    tmp2 = tmp_path / 'c17 missing'
    tmp2.mkdir()
    ldir2 = draft_managed_test_league(tmp2, b'DRAFT CLASALE1 Bobby Green\r\n'
                                            b'SIGN CLASALW7 Bobby Green CLASALE1\r\n',
                                      1 << 7)
    check_offseason(ldir2, tmp_path, 'c17_nofile_draft', 2)


@pytest.mark.parametrize('phase', [3, 4])
def test_c17_managed_trades_fa_parity(tmp_path, phase):
    """Python vs host on the TRADES and FREE AGENTS screens: the mask 0 (no stars) and
    the SEATTLE mask bit set ('*' + the display cut to the 13 char TEAM column; only the
    first trade column is marked)."""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = c17_league(tmp_path, 'c17 f%d' % phase,
                      {0: ('Lou Green', 5), 1: ('Bobby Holmes', 0)}, 0)
    check_offseason(ldir, tmp_path, 'c17_zero_p%d' % phase, phase)
    ldir = c17_league(tmp_path, 'c17 s%d' % phase,
                      {0: ('Lou Green', 5), 1: ('Bobby Holmes', 0)}, 1 << 7)
    check_offseason(ldir, tmp_path, 'c17_set_p%d' % phase, phase)
    # every bit set: BOSTON and NEW YORK N are marked too
    tmp3 = tmp_path / ('c17 f%d s' % phase)
    tmp3.mkdir()
    ldir3 = draft_managed_test_league(tmp3, C17_ROSTERS, 0xffffffff)
    write_team_v20_full(ldir3, 'CLASALW7', {0: ('Lou Green', 5), 1: ('Bobby Holmes', 0)},
                        name='SEATTLE')
    check_offseason(ldir3, tmp_path, 'c17_all_p%d' % phase, phase)


def test_c17_managed_by_stem_parity(tmp_path):
    """Two teams whose V20 header names are equal (same display) with only one managed:
    only that team's rows get '*' in Python and on the host, and a trade row's third
    column never starts with '*'."""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    rosters = (b'DRAFT CLASALE1 Bobby Holmes\r\n'
               b'DRAFT CLASALE1 Bobby Holmes\r\n'
               b'SIGN CLASALW7 Bobby Holmes CLASALE1\r\n'
               b'SIGN CLASALW2 Bobby Holmes CLASALE1\r\n'
               b'TRADE CLASALW7 Duke Snider CLASALW2 TONY BERNAZARD\r\n')
    tmp2 = tmp_path / 'c17 twin'
    tmp2.mkdir()
    ldir = draft_managed_test_league(tmp2, rosters, 1 << 7)
    write_team_v20_full(ldir, 'CLASALW7', {0: ('Lou Green', 5)}, name='SEATTLE')
    write_team_v20_full(ldir, 'CLASALW2', {0: ('Lou Green', 5)}, name='SEATTLE')
    data = dynview.load_data(str(ldir), FILES)
    assert data['teams'] == [(0, 'SEATTLE'), (7, 'SEATTLE'), (20, 'NEW YORK N')]
    rows = dynview.offseason_body((dynview.SCREEN_OFFSEASON, 0, oc(2)), data)[1]
    assert rows == [('#1', '*SEATTLE', '', 'Bobby Holmes'),
                    ('#2', 'SEATTLE', '', 'Bobby Holmes')]
    trade = dynview.offseason_body((dynview.SCREEN_OFFSEASON, 0, oc(3)), data)[1]
    assert trade == [('*SEATTLE', 'Duke Snider', 'SEATTLE'),
                     ('SEATTLE', 'TONY BERNAZARD', 'SEATTLE')]
    check_offseason(ldir, tmp_path, 'c17_twin_draft', 2)
    check_offseason(ldir, tmp_path, 'c17_twin_trades', 3)


# ---------------- three divisions: DYNASTY SETTINGS, PLAYOFF FORMAT, SEASON STANDINGS ----------------
# D2 is the synthetic CLASSIC league (2 divisions, test_teamids.build_maj); D3 the same teams realigned
# to 3 divisions by realign.realign (C12.5); TABLE3 is the TEAMID.DAT the realignment writes (C12.3)

D2 = build_maj(CLASSIC, divs=2, day=0x07)
D3 = realign.realign(D2, 3)[0]
TABLE3 = teamids.make_table(D2)
STAND_3 = ['AL WEST', 'AL CENTRAL', 'AL EAST', 'NL WEST', 'NL CENTRAL', 'NL EAST']


def with_day(maj, day):
    d = bytearray(maj)
    d[0x20a] = day
    return bytes(d)


def league_files(d):
    """{name: bytes} of every file of the league dir d"""
    return {f: open(os.path.join(d, f), 'rb').read() for f in sorted(os.listdir(d))}


def three_div_league(tmp_path, tag, maj, table=None, byte0=0, byte11=0):
    """A league dir (make_data: 3 seasons, MILESTON.DAT) with the MAJ as CLASSIC.MAJ, a V20 per MAJ
    team named TEAM <STEM> (upper case stems, the form the C port opens), HISTORY bytes 0 and 11 set,
    and TEAMID.DAT when table is given"""
    (tmp_path / tag).mkdir()
    ldir = make_data(tmp_path / tag)[0]
    (ldir / 'CLASSIC.MAJ').write_bytes(maj)
    for _k, _L, _s, st_ in teamids.teams(maj, None):
        stem = st_.rstrip(b'\0').decode('latin-1').upper()
        write_team(ldir, stem, 'TEAM ' + stem)
    hp = ldir / 'HISTORY.DAT'
    d = bytearray(hp.read_bytes())
    d[0], d[11] = byte0, byte11
    hp.write_bytes(bytes(d))
    if table is not None:
        (ldir / 'TEAMID.DAT').write_bytes(table)
    return ldir


def run_pair(ldir, tmp_path, tag, keys):
    """host and Python on twin copies of the league after keys: (host dir, python dir, host frame,
    python frame)"""
    h, p = twin_league(ldir, tmp_path, tag)
    raw = str(tmp_path / (tag + '.RAW'))
    a = run_host(h, raw, keys=keys, font_dir=FILES)
    b = fb_python(p, keys=keys, font_dir=FILES)
    return h, p, a, b


def assert_same(h, p, a, b, tag):
    """the frames and every league file (MAJ, TEAMID.DAT, HISTORY.DAT) match Python"""
    if a != b:
        i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]),
                 min(len(a), len(b)))
        pytest.fail(f'{tag}: first diff at pixel ({i % 320}, {i // 320}): '
                    f'python {b[i] if i < len(b) else "?"} '
                    f'c {a[i] if i < len(a) else "?"}')
    assert league_files(h) == league_files(p), f'{tag}: league files after the keys differ'


def test_three_division_settings_rows_parity(tmp_path):
    """DYNASTY SETTINGS of a 3 division MAJ: PLAYOFF FORMAT reads 3 DIV + WILDCARD and the NL slot 20
    team (SL, the last Central team) is listed under its stable id: 21 with TEAMID.DAT, else 30 (its
    engine id); the pages match Python with and without the table"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    for tag, table, sid in (('set_nt', None, 30), ('set_wt', TABLE3, 21)):
        ldir = three_div_league(tmp_path, tag, D3, table)
        data = dynview.load_data(str(ldir))
        assert dynview.settings_rows(data)[1] == ('PLAYOFF FORMAT', '3 DIV + WILDCARD')
        assert (sid, 'TEAM NSL') in data['teams']
        for n, keys in enumerate(([55], [55, PGDN], [55, PGDN, PGDN])):
            check_parity(ldir, tmp_path, '%s_%d' % (tag, n), keys=keys)


def test_playoff_enter_applies_at_once_parity(tmp_path):
    """ENTER on PLAYOFF FORMAT of a 2 division league on day 0xf3 with HISTORY byte 0 = 1, and on day 7
    (which sets byte 0 = 1 after the apply): the MAJ becomes the 3 division MAJ, TEAMID.DAT is written
    from the 2 division MAJ, byte 11 = 3, and the files and the screen match Python"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    for tag, day, byte0 in (('pf_rolled', 0xf3, 1), ('pf_setup', 7, 0)):
        ldir = three_div_league(tmp_path, tag, with_day(D2, day), byte0=byte0)
        h, p, a, b = run_pair(ldir, tmp_path, tag, [55, DOWN, ENTER])
        assert_same(h, p, a, b, tag)
        got = league_files(h)
        assert got['CLASSIC.MAJ'] == D3
        assert got['TEAMID.DAT'] == TABLE3
        assert got['HISTORY.DAT'][0] == 1 and got['HISTORY.DAT'][11] == 3
        assert dynview.settings_rows(dynview.load_data(str(h)))[1] == \
            ('PLAYOFF FORMAT', '3 DIV + WILDCARD')


def test_playoff_enter_mid_season_writes_byte_11_only_parity(tmp_path):
    """Day 1 (mid season): ENTER writes HISTORY byte 11 only (row 3 DIV NEXT YEAR), the second ENTER
    writes 2 (5 - 3): the MAJ and TEAMID.DAT stay as they are"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    maj = with_day(D2, 1)
    ldir = three_div_league(tmp_path, 'pf_mid', maj)
    hist0 = (ldir / 'HISTORY.DAT').read_bytes()
    h, p, a, b = run_pair(ldir, tmp_path, 'pf_mid1', [55, DOWN, ENTER])
    assert_same(h, p, a, b, 'pf_mid1')
    got = league_files(h)
    assert got['HISTORY.DAT'] == hist0[:11] + b'\x03' + hist0[12:]
    assert got['CLASSIC.MAJ'] == maj and 'TEAMID.DAT' not in got
    assert dynview.settings_rows(dynview.load_data(str(h)))[1] == \
        ('PLAYOFF FORMAT', '3 DIV NEXT YEAR')
    h, p, a, b = run_pair(ldir, tmp_path, 'pf_mid2', [55, DOWN, ENTER, ENTER])
    assert_same(h, p, a, b, 'pf_mid2')
    got = league_files(h)
    assert got['HISTORY.DAT'] == hist0[:11] + b'\x02' + hist0[12:]
    assert got['CLASSIC.MAJ'] == maj and 'TEAMID.DAT' not in got


def test_standings_three_divisions_parity(tmp_path):
    """SEASON STANDINGS of a 3 division entry (ndiv 3 and the C12.7 map of the realigned league), with
    and without the table: six blocks in AL WEST, AL CENTRAL, AL EAST, NL WEST, NL CENTRAL, NL EAST
    order, a blank row ahead of the AL EAST header (the page padding), and every page matches Python"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    for tag, table in (('stand_wt', TABLE3), ('stand_nt', None)):
        ldir = three_div_league(tmp_path, tag, D3, table)
        ids = sorted(k for k, *_ in teamids.teams(D3, table))
        wl = {k: (50 + (5 * k) % 31, 70 + k % 9) for k in ids}
        hp = ldir / 'HISTORY.DAT'
        d = bytearray(hp.read_bytes())
        write_standings(d, 3, wl, champ=2, al_p=8, nl_p=16)
        o = 32 + 2 * 128
        d[o + 22] = 3
        d[o + 100:o + 116] = history.divmap_of(D3, table)
        hp.write_bytes(bytes(d))
        data = dynview.load_data(str(ldir))
        n = dynview.total_rows((dynview.SCREEN_STANDINGS, 0, 0), data)
        rows = [r for pg in range((n + 11) // 12)
                for r in dynview.rows((dynview.SCREEN_STANDINGS, pg, 0), data)]
        heads = [i for i, r in enumerate(rows) if r[0] and r[1:] == ('', '', '', '', '')]
        assert [rows[i][0] for i in heads] == STAND_3
        assert all(i % 12 != 11 for i in heads)
        assert ('', '', '', '', '', '') in rows
        assert sum(1 for r in rows if r[0] and r[1]) == len(ids)
        for k in range((n + 11) // 12):
            check_parity(ldir, tmp_path, '%s_p%d' % (tag, k), keys=[48] + [PGDN] * k)


def _game_dir(tmp_path, name, system):
    """a game dir (the cwd under the BAT) holding the fonts, TEAMS/<name> (settings_league, its MAJ renamed
    <name>.MAJ) and SYSTEM (None: no file)"""
    g = tmp_path / 'g'
    (g / 'TEAMS').mkdir(parents=True)
    src = settings_league(tmp_path / 'src')
    ldir = g / 'TEAMS' / name
    shutil.copytree(str(src), str(ldir))
    os.rename(str(ldir / 'TEST.MAJ'), str(ldir / (name + '.MAJ')))
    for f in os.listdir(FILES):
        if f.upper().endswith('.FNT') or f.upper() == 'DEFAULT.PAL':
            shutil.copy2(os.path.join(FILES, f), str(g / f))
    if system is not None:
        (g / 'SYSTEM').write_bytes(system)
    return g, ldir


@pytest.mark.parametrize('name,system', [('TESTLG', b'testlg\0\0\0\0\0'), ('CLASSIC', None),
                                         ('CLASSIC', b'NOSUCH\0\0')])
def test_default_league_dir_follows_system(tmp_path, name, system):
    """C16.3: with no LEAGUE_DIR the host binary opens TEAMS/<current league>; the frame equals the run that
    names that dir (TESTLG via SYSTEM, CLASSIC without SYSTEM or when SYSTEM names a league with no MAJ)."""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    g, ldir = _game_dir(tmp_path, name, system)
    raw = str(tmp_path / 'default.raw')
    r = subprocess.run([HOST, '/KEYS:' + toks([55]), '/RAW:' + raw], capture_output=True, text=True,
                       timeout=300, cwd=str(g))
    assert r.returncode == 0, f'host rc {r.returncode}: {r.stderr[:400]}'
    named = run_host(str(ldir), str(tmp_path / 'named.raw'), keys=[55], font_dir=str(g))
    assert open(raw, 'rb').read() == named


# ---------------- C18/C19 parity: starred teams and releases ----------------

def write_mask(ldir, mask):
    """HISTORY.DAT bytes 12..15 = mask (u32 LE)"""
    p = os.path.join(ldir, 'HISTORY.DAT')
    d = bytearray(open(p, 'rb').read())
    d[12:16] = mask.to_bytes(4, 'little')
    open(p, 'wb').write(bytes(d))
    return d


def test_c18_standings_series_history_star_parity(tmp_path):
    """C18: STANDINGS, WORLD SERIES and SEASON HISTORY with one managed team: the star's
    pixels match Python on every page; the same league with mask 0 matches too"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'stand').mkdir()
    sld = make_standings(tmp_path / 'stand')
    write_mask(sld, 1 << 1)                     # DETROIT, AL id 1
    data = dynview.load_data(str(sld))
    for pg in range(2):
        check_parity(sld, tmp_path, 'c18_stand%d' % pg, keys=[48] + [PGDN] * pg)
    # WORLD SERIES on the same league (BOSTON vs ATLANTA, a 6 game series)
    (tmp_path / 'series').mkdir()
    wld = make_series(tmp_path / 'series', series_recs(3, SERIES6))
    write_mask(wld, 1 << 0)                     # BOSTON, AL id 0
    for pg in range(2):
        check_parity(wld, tmp_path, 'c18_series%d' % pg,
                     keys=[87] + []
                     if False else [ord('W')] + [PGDN] * pg)
    # SEASON HISTORY with a managed champion stem (make_data champion ALA03)
    (tmp_path / 'hist').mkdir()
    hld = make_data(tmp_path / 'hist')[0]
    write_team(hld, 'ALA03', 'MILWAUKEE')
    write_maj(hld, {2: b'ALA03'})
    write_mask(hld, 1 << 2)
    check_parity(hld, tmp_path, 'c18_hist', keys=[49])
    # mask 0 regression on each screen
    write_mask(sld, 0)
    check_parity(sld, tmp_path, 'c18_stand_m0', keys=[48])
    write_mask(wld, 0)
    check_parity(wld, tmp_path, 'c18_series_m0', keys=[ord('W')])
    write_mask(hld, 0)
    check_parity(hld, tmp_path, 'c18_hist_m0', keys=[49])


def test_c18_standings_all_bits_parity(tmp_path):
    """C18 tid >= 32 rule on the framebuffer: all history mask bits set stars nothing an
    all-bits run would not; the frames match Python"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'full').mkdir()
    ldir = make_standings(tmp_path / 'full')
    write_mask(ldir, 0xffffffff)
    data = dynview.load_data(str(ldir))
    rows = [r for pg in range(3) for r in dynview.rows((dynview.SCREEN_STANDINGS, pg, 2),
                                                       data)]
    assert not any(r[0].startswith('*TEAM') and int(r[0][5:]) >= 32 for r in rows if r[1:])
    for pg in range(3):
        check_parity(ldir, tmp_path, 'c18_full%d' % pg, keys=[48] + [PGDN] * pg)


def test_c19_signings_releases_parity(tmp_path):
    """C19: offseason phase 4 with SIGN and REL lines: title, the SIGN rows then the
    RELEASED rows in file order with a starred managed release, the empty phase message
    and the mask 0 frames all match Python"""
    if not _fonts_ready():
        pytest.skip('fonts missing')
    ldir = draft_managed_test_league(
        tmp_path, b'SIGN CLASALW7 Sign One pool\r\n'
                  b'SIGN CLASNLW4 Sign Two pool\r\n'
                  b'REL CLASALW7 Cut One\r\n'
                  b'REL CLASNLE4 Cut Two Words\r\n'
                  b'REL BOSTON Cut Three\r\n', 1 << 7)
    data = dynview.load_data(str(ldir))
    rows = dynview.offseason_body((dynview.SCREEN_OFFSEASON, 0, oc(4)), data)[1]
    assert rows == [('*SEATTLE', 'Sign One', 'FREE AGENT'),
                    ('NEW YORK N', 'Sign Two', 'FREE AGENT'),
                    ('*SEATTLE', 'Cut One', 'RELEASED'),
                    ('CLASNLE4', 'Cut Two Words', 'RELEASED'),
                    ('BOSTON', 'Cut Three', 'RELEASED')]
    assert dynview.screen_title((dynview.SCREEN_OFFSEASON, 0, oc(4)), data) == \
        '5/6 SIGNINGS AND RELEASES'
    check_offseason(ldir, tmp_path, 'c19_fa', 4)
    # the empty phase message and no-history league
    (tmp_path / 'norost').mkdir()
    nld = make_offseason(tmp_path / 'norost', rosters=None)
    check_offseason(nld, tmp_path, 'c19_empty', 4)
    # mask 0 regression
    write_mask(ldir, 0)
    check_offseason(ldir, tmp_path, 'c19_fa_m0', 4)


# ---------------- test C23c: PLAYOFFS (hub key P) and round box scores ----------------

def make_playoffs_mask(tmp_path):
    """a make_playoffs league with BOSTON (id 0) managed (the mask byte 12 set)"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    ldir = T.make_playoffs(tmp_path)
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12] = 1
    p.write_bytes(bytes(d))
    return ldir


PLAYOFF_SEQS = [
    ('open_P', [80]),
    ('open_p_lower', [112]),
    ('click_hub_row11', None),                  # a click at the 12th hub row
    ('p0_pgdn', [80, PGDN]),
    ('p0_pgdn_pgdn', [80, PGDN, PGDN]),
    ('p4', [80] + [PGDN] * 4),
    ('p4_pgdn_stays', [80] + [PGDN] * 5),
    ('left_season', [80, LEFT]),
    ('right_stays', [80, RIGHT]),
    ('enter_first_game', [80, ENTER]),
    ('p1_enter', [80, PGDN, ENTER]),
    ('pbox_first', [80, ENTER]),
    ('pbox_right_walk', [80, ENTER, RIGHT]),
    ('pbox_right_to_ws', [80, ENTER] + [RIGHT] * 13),
    ('ws_left_to_pbox', [87, 49, LEFT]),
    ('pbox_esc', [80, ENTER, ESC]),
]


def test_playoffs_parity(tmp_path):
    """C23c: the hub frame with the 12th row, PLAYOFFS pages and seasons, ENTER's box
    choice, the PBOX walk into and back out of the WS box, and a click on the hub's
    PLAYOFFS row all match Python pixel for pixel."""
    if not _synth_fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'pl').mkdir(parents=True, exist_ok=True)
    ldir = T.make_playoffs(tmp_path / 'pl')
    for tag, keys in PLAYOFF_SEQS:
        if keys is None:
            check_parity(ldir, tmp_path, 'pl_click_hub_row11',
                         keys=[('L', 100, 35 + 11 * 11 + 3)])
        else:
            check_parity(ldir, tmp_path, 'pl_' + tag, keys=keys)


def test_playoffs_empty_parity(tmp_path):
    """a season with no round games: the message row, its pages, and ENTER doing
    nothing there"""
    if not _synth_fonts_ready():
        pytest.skip('fonts missing')
    (tmp_path / 'ple').mkdir(parents=True, exist_ok=True)
    ldir = make_series(tmp_path / 'ple', T.game_ms(3, (0, 1)))
    check_parity(ldir, tmp_path, 'ple_p0', keys=[80])
    check_parity(ldir, tmp_path, 'ple_p1', keys=[80, PGDN])
    check_parity(ldir, tmp_path, 'ple_left', keys=[80, LEFT])
    check_parity(ldir, tmp_path, 'ple_enter', keys=[80, ENTER])
    check_parity(ldir, tmp_path, 'ple_pgdn_enter', keys=[80, PGDN, ENTER])


def test_playoffs_managed_cap_and_order_parity(tmp_path):
    """the managed star on the round rows; the 48 header cap; headers written out of g
    order draw in g order; a season with WS games but no round records; 25 random key
    walks over a league with both WS and round records"""
    if not _synth_fonts_ready():
        pytest.skip('fonts missing')
    ldir = make_playoffs_mask(tmp_path / 'plm')
    check_parity(ldir, tmp_path, 'plm_p0', keys=[80])
    check_parity(ldir, tmp_path, 'plm_pbox', keys=[80, ENTER])

    tmp3 = tmp_path / 'cap48'
    tmp3.mkdir()
    ldir3 = make_series(tmp3, T.game_ms(3, (0,)))
    recs = []
    for gi in range(48):
        g = 16 + gi
        recs.append(T.round_hdr(3, g, 16, 24, 2, 1, 1, 1, 0, 2, 1, 0, 0))
        recs.append(T.box_rec(3, g, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)))
    recs += T.BOX_G0
    T.write_box(ldir3, recs)
    check_parity(ldir3, tmp_path, 'plcap_p0', keys=[80])
    check_parity(ldir3, tmp_path, 'plcap_end', keys=[80, ENTER] + [RIGHT] * 47)
    check_parity(ldir3, tmp_path, 'plcap_ws_left', keys=[87, 49, LEFT])
    check_parity(ldir3, tmp_path, 'plcap_ws_left_empty', keys=[87, 50, LEFT])

    tmp4 = tmp_path / 'gorder'
    tmp4.mkdir()
    ldir4 = make_series(tmp4, T.game_ms(3, (0,)))
    recs = [T.round_hdr(3, 18, 0, 16, 1, 0, 3, 4, 2, 8, 6, 1, 0),
            T.round_hdr(3, 16, 0, 16, 1, 0, 1, 5, 3, 9, 7, 1, 0),
            T.round_hdr(3, 17, 0, 16, 1, 0, 2, 2, 6, 8, 6, 0, 1)]
    recs += [T.box_rec(3, g, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)) for g in (16, 17, 18)]
    recs += [T.box_rec(3, g, 2, 0xffff, (80, 5, 2, 2, 1, 1, 8, 30)) for g in (16, 17, 18)]
    recs += T.BOX_G0
    T.write_box(ldir4, recs)
    check_parity(ldir4, tmp_path, 'plg_p0', keys=[80])
    check_parity(ldir4, tmp_path, 'plg_enter', keys=[80, PGDN, PGDN, ENTER])

    tmp5 = tmp_path / 'rand'
    tmp5.mkdir()
    ldir5 = make_series(tmp5, series_recs(3, SERIES7) + series_recs(2, SERIES6))
    recs = [rr for g in range(16, 21) for rr in
            (T.round_hdr(3, g, 0, 16, 1, 0, g - 15, 5, 3, 9, 7, 1, 0),
             T.box_rec(3, g, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)))]
    recs += T.BOX_G0
    T.write_box(ldir5, recs)
    rng = random.Random(7)
    keypool = [ESC, ENTER, ord('0'), ord('1'), ord('2'), ord('3'), ord('4'), ord('5'),
               ord('9'), ord('P'), ord('p'), 87, 119, LEFT, RIGHT,
               dynview.KEY_UP, dynview.KEY_DOWN, PGUP, PGDN]
    for n in range(25):
        seq = [rng.choice(keypool) for _ in range(rng.randrange(1, 25))]
        check_parity(ldir5, tmp_path, 'plr%02d' % n, keys=seq)


def test_playoffs_sparse_g_and_long_box_parity(tmp_path):
    """brain gate (C23c): round games at g 16, 20, 30, 40 (ENTER on page 1 opens the box
    of g 40, not g 16 + its list index), and a 44-record box score on g 20 drawn on every
    page (the C box rows follow the page and the record buffer holds BOX_MAX_RECS)."""
    if not _synth_fonts_ready():
        pytest.skip('fonts missing')
    tmp = tmp_path / 'sparse'
    tmp.mkdir()
    ldir = make_series(tmp, T.game_ms(3, (0,)))
    recs = [T.round_hdr(3, 16, 0, 1, 1, 0, 1, 3, 1, 7, 5, 0, 1),
            T.round_hdr(3, 20, 2, 3, 1, 0, 1, 2, 4, 6, 9, 1, 0, s=1),
            T.round_hdr(3, 30, 0, 2, 2, 0, 1, 5, 0, 10, 3, 0, 0),
            T.round_hdr(3, 40, 16, 17, 2, 1, 1, 1, 2, 4, 8, 2, 0)]
    for g in (16, 30, 40):
        recs.append(T.box_rec(3, g, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)))
    for n in range(44):
        side, pitch = n % 2, 1 if n % 11 == 0 else 0
        stats = ((30 + n, 3, 2, 1, 0, 1, 4, 9) if pitch
                 else (4, n % 3, n % 4, n % 2, 0, 1, n % 5, 0))
        recs.append(T.box_rec(3, 20, side | (pitch << 1), 0xffff, stats))
    recs += T.BOX_G0
    T.write_box(ldir, recs)
    check_parity(ldir, tmp_path, 'sp_p1_enter', keys=[80, PGDN, ENTER])
    check_parity(ldir, tmp_path, 'sp_long_p0', keys=[80, ENTER, RIGHT])
    for k in range(1, 5):
        check_parity(ldir, tmp_path, 'sp_long_p%d' % k, keys=[80, ENTER, RIGHT] + [PGDN] * k)
    check_parity(ldir, tmp_path, 'sp_long_back', keys=[80, ENTER, RIGHT, PGDN, PGDN, PGUP])
    data = dynview.load_data(str(ldir))
    s = (dynview.SCREEN_PLAYOFFS, 1, 0)
    assert dynview.step(s, dynview.KEY_ENTER, data)[0] == (dynview.SCREEN_PBOX, 0, 24)


# ---------------------------------------------------------------- C27 MILESTONES WATCH
from m4.test_dynview import G, AB, H, HR, R, RBI, BB, SO, SB, CS, E, W, L, \
    SV, GS, CG, SHO, OUTS, ER, PH, PBB, PSO, PHR     # TOTALS indexes


def watch_league_c(league_dir, empty=False):
    """HISTORY.DAT for the C27 watch parity league: active batters at H 2950 (row) and
    1700 (no row, 85%), HR 298 and HR 395 rows, a retired H 2990, a PSO 2995 pitcher,
    H 3100 (no higher H mark); empty: one far-from-any-mark active player"""
    d = bytearray(32 + 64 * 128 + (1 if empty else 7) * 160)
    d[3] = 1
    d[4], d[5] = 3, 0
    d[6] = 1 if empty else 7
    write_season(d, 1, b'ALA01', b'NL01')
    write_season(d, 2, b'ALA02', b'NL02')
    write_season(d, 3, b'ALA03', b'NL03')
    tt = lambda: [0] * 25
    if empty:
        tw = tt()
        tw[H], tw[AB] = 10, 50
        write_player(d, 0, b'NONE', b'A', status=1, totals=tw)
    else:
        sets = [(b'HITE2950', 2950, 8000, 0, 0, 0),
                (b'HITLOW', 1700, 5000, 0, 0, 0),
                (b'HITDONE', 3100, 9000, 0, 0, 0),
                (b'HRNEAR', 0, 3000, 298, 0, 0),
                (b'HRNEAR2', 0, 3000, 395, 0, 0)]
        for i, (last, h, ab, hr, pso, sb) in enumerate(sets):
            tw = tt()
            tw[H], tw[AB], tw[HR], tw[PSO], tw[SB] = h, ab, hr, pso, sb
            write_player(d, i, last, b'A', status=1, totals=tw)
        tw = tt()
        tw[H], tw[AB] = 2990, 8000
        write_player(d, 5, b'ORGUY', b'G', status=2, totals=tw)
        tw = tt()
        tw[PSO], tw[G], tw[OUTS] = 2995, 400, 8000
        write_player(d, 6, b'KMAN', b'K', status=1, pitcher=1, totals=tw)
    league_dir.mkdir(parents=True, exist_ok=True)
    (league_dir / 'HISTORY.DAT').write_bytes(bytes(d))
    return league_dir


@pytest.mark.parametrize('empty', [False, True])
def test_watch_screen_parity(tmp_path, empty):
    """C27 MILESTONES mode 0 (new footer), WATCH (RIGHT), the cursor row and its card,
    the empty message row, and the title click that toggles the mode"""
    if not _synth_fonts_ready():
        pytest.skip('fonts missing')
    ldir = watch_league_c(tmp_path / ('w1' if not empty else 'w0'), empty=empty)
    check_parity(ldir, tmp_path, 'c27c_ms0', keys=[52])
    check_parity(ldir, tmp_path, 'c27c_watch', keys=[52, dynview.KEY_RIGHT])
    if not empty:
        check_parity(ldir, tmp_path, 'c27c_watch_row1',
                     keys=[52, dynview.KEY_RIGHT, dynview.KEY_DOWN])
        check_parity(ldir, tmp_path, 'c27c_watch_enter',
                     keys=[52, dynview.KEY_RIGHT, dynview.KEY_DOWN, 13])
        check_parity(ldir, tmp_path, 'c27c_watch_esc',
                     keys=[52, dynview.KEY_RIGHT, dynview.KEY_DOWN, 13, 27])
        assert fb_python(ldir, keys=[52, dynview.KEY_RIGHT, dynview.KEY_DOWN, 13]) != \
            fb_python(ldir, keys=[52, dynview.KEY_RIGHT, dynview.KEY_DOWN])
    check_parity(ldir, tmp_path, 'c27c_title_click',
                 keys=[52, ('L', 100, 14)])
    assert fb_python(ldir, keys=[52, ('L', 100, 14)]) == \
        fb_python(ldir, keys=[52, dynview.KEY_RIGHT])


# ---------------------------------------------------------------- C29 TEAM HISTORY

def th_league_c(tmp_path, name):
    """The C29 parity league: the standings league's names and 3 seasons (BOSTON and
    CLEVELAND play every season, DETROIT and ATLANTA only 1993), BOSTON the 1993
    champion, CLEVELAND the 1994 AL pennant, and 1995 round headers that put BOSTON
    and DETROIT in an AL DS, CLEVELAND and ATLANTA in the AL LCS."""
    base = tmp_path / name
    base.mkdir(parents=True, exist_ok=True)
    ldir = make_standings(base, seasons=[
        ({0: (10, 4), 1: (8, 6), 2: (4, 10), 16: (8, 2)}, 0, 0xff, 0xff),
        ({0: (6, 4), 2: (6, 4), 16: (4, 6), 17: (8, 2)}, 0xff, 2, 0xff),
        ({0: (5, 5), 2: (9, 0), 16: (7, 3), 17: (1, 9)}, 0xff, 0xff, 0xff)])
    write_box(ldir, [
        box_rec(3, 16, 4, 0 * 256 + 2, (5, 3, 9, 7, 1, 0, 0, 0), b=1, i=1),  # AL DS 0/2
        box_rec(3, 17, 4, 1 * 256 + 16, (2, 4, 6, 9, 0, 1, 0, 0), b=1 + 4, i=1),  # AL DS 1/16
        box_rec(3, 23, 4, 2 * 256 + 16, (7, 1, 11, 4, 0, 1, 0, 0), b=2, i=1),  # AL LCS 2/16
        box_rec(3, 27, 4, 16 * 256 + 17, (2, 5, 6, 8, 1, 0, 0, 0), b=2 + 4, i=1),  # NL LCS
    ])
    return ldir


def test_teamhist_champion_frame_parity(tmp_path):
    """TEAM HISTORY of the champion BOSTON (mask 0 on standings), the standings frame
    with the new T footer, and a T press on a page-2 season-1 standings with the mask
    bit on CLEVELAND: every frame matches Python and ESC returns the exact state."""
    if not _synth_fonts_ready():
        pytest.skip('fonts missing')
    ldir = th_league_c(tmp_path, 'thc')
    check_parity(ldir, tmp_path, 'c29_stand_open', keys=[48])
    check_parity(ldir, tmp_path, 'c29_stand_open_t', keys=[48, 84])
    # the exact ESC round trip: identical standings state
    assert fb_python(ldir, keys=[48, 84, ESC]) == fb_python(ldir, keys=[48])
    check_parity(ldir, tmp_path, 'c29_esc_back', keys=[48, 84, ESC])
    check_parity(ldir, tmp_path, 'c29_lower_t', keys=[48, 116])
    # the champion's rows show; a long history page 1 (only 3 rows: PGDN stays)
    assert fb_python(ldir, keys=[48, 84, PGDN]) == fb_python(ldir, keys=[48, 84])
    check_parity(ldir, tmp_path, 'c29_pgdn_stays', keys=[48, 84, PGDN])


def test_teamhist_page1_and_right_parity(tmp_path):
    """Page 1 of a long history and RIGHT to the next team: a 12+ season league whose
    BOSTON plays every season, so the history spills onto page 2; RIGHT lands on
    DETROIT's history."""
    if not _synth_fonts_ready():
        pytest.skip('fonts missing')
    ldir = th_league_c(tmp_path, 'thlong')
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    for n in range(4, 15):
        # seasons 4..14 replay the season-1 table without champion or pennants
        write_standings(d, n, {0: (9, 5), 1: (7, 7), 2: (6, 8), 16: (8, 2)})
    d[4], d[5] = 14, 0
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir), FILES)
    s, _ex = dynview.step((dynview.SCREEN_STANDINGS, 0, 0), 84, data)
    assert s == (dynview.SCREEN_TEAMHIST, 0, 0)
    assert dynview.screen_title(s, data) == 'BOSTON  1 TITLES  1 PENNANTS'
    n = dynview.total_rows(s, data)
    assert n > dynview.ROWS_PER_PAGE
    assert dynview.rows((dynview.SCREEN_TEAMHIST, 1, 0), data)[0] == \
        dynview.team_history_rows(data['hist'], data['box'], data['teams'], 0)[12]
    check_parity(ldir, tmp_path, 'c29_long_p0', keys=[48, 84])
    check_parity(ldir, tmp_path, 'c29_long_p1', keys=[48, 84, PGDN])
    check_parity(ldir, tmp_path, 'c29_long_right', keys=[48, 84, RIGHT])
    check_parity(ldir, tmp_path, 'c29_long_right_pgdn', keys=[48, 84, RIGHT, PGDN])


def test_teamhist_masked_open_and_title_click_parity(tmp_path):
    """The T open picks the lowest managed id; the message row of a team without
    seasons; a title-band click steps the team."""
    if not _synth_fonts_ready():
        pytest.skip('fonts missing')
    ldir = th_league_c(tmp_path, 'thmask')
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12:16] = (1 << 2).to_bytes(4, 'little')            # CLEVELAND managed
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir), FILES)
    s, _ex = dynview.step((dynview.SCREEN_STANDINGS, 0, 0), 84, data)
    assert s == (dynview.SCREEN_TEAMHIST, 0, 2)
    # the message row: TEAM 10 has no games
    assert dynview.rows((dynview.SCREEN_TEAMHIST, 0, 10), data) == \
        [('NO SEASONS RECORDED',)]
    check_parity(ldir, tmp_path, 'c29_mask_open', keys=[48, 84])
    check_parity(ldir, tmp_path, 'c29_mask_msg', keys=[48, 84, LEFT, LEFT, LEFT])
    # LEFT from BOSTON wraps to the last listed team (SAN FRANCISCO, 27)
    msg_state = None
    s2, _ex = dynview.step(s, dynview.KEY_LEFT, data)
    assert s2[2] == 1
    # the title click: RIGHT on the title band of the mask league
    check_parity(ldir, tmp_path, 'c29_title_click', keys=[48, 84, ('L', 250, 14)])
    assert fb_python(ldir, keys=[48, 84, ('L', 250, 14)]) == \
        fb_python(ldir, keys=[48, 84, dynview.KEY_RIGHT])


def test_teamhist_walk_and_esc_parity(tmp_path):
    """LEFT and RIGHT wrap over the listed teams, PGDN/PGUP page, ESC gives the kept
    standings state (page included), and rows carry the LCS / DS results."""
    if not _synth_fonts_ready():
        pytest.skip('fonts missing')
    ldir = th_league_c(tmp_path, 'thwalk')
    p = ldir / 'HISTORY.DAT'
    d = bytearray(p.read_bytes())
    d[12:16] = (1 << 27).to_bytes(4, 'little')           # SAN FRANCISCO managed
    p.write_bytes(bytes(d))
    data = dynview.load_data(str(ldir), FILES)
    s, _ex = dynview.step((dynview.SCREEN_STANDINGS, 0, 0), 84, data)
    assert s == (dynview.SCREEN_TEAMHIST, 0, 27)
    # LEFT: SAN FRANCISCO -> LOS ANGELES (26); RIGHT wraps it back to SAN FRANCISCO
    s2 = dynview.step(s, dynview.KEY_LEFT, data)[0]
    assert s2 == (dynview.SCREEN_TEAMHIST, 0, 26)
    assert dynview.step(s2, dynview.KEY_RIGHT, data)[0] == s
    s3, _ex = dynview.step(s, dynview.KEY_RIGHT, data)
    assert s3 == (dynview.SCREEN_TEAMHIST, 0, 0)
    # the RESULT cells of CLEVELAND (2): 1995 LCS, 1994 PENNANT, 1993 ''
    rows = dynview.team_history_rows(data['hist'], data['box'], data['teams'], 2)
    assert [r[5] for r in rows] == ['LCS', 'PENNANT', '']
    # the py sequence 48 84 ESC ESC: back to standings then the hub
    check_parity(ldir, tmp_path, 'c29_walk_right', keys=[48, 84, RIGHT])
    check_parity(ldir, tmp_path, 'c29_walk_right_right', keys=[48, 84, RIGHT, RIGHT])
    check_parity(ldir, tmp_path, 'c29_walk_left', keys=[48, 84, LEFT])
    check_parity(ldir, tmp_path, 'c29_walk_t_esc_esc', keys=[48, 84, ESC])
    # a click on the standings title: LEFT/RIGHT still step the season there
    check_parity(ldir, tmp_path, 'c29_stand_title_click', keys=[48, ('L', 100, 14)])
