#!/usr/bin/env python3
"""DYNVIEW C13 host parity: dynview_c/dynview_host (/RAW) and the Python reference render the
same 64000 B framebuffer for the same start state and keys, and leave byte-identical HISTORY.DAT
files after the START YEAR steps. Font tests skip unless DYNVIEW_FILES (default
/mnt/nvme/tlrb2/files) holds MAIN.FNT; the DOS test also needs dynview_c/DYNVIEW.EXE and dosbox-x.
Run:  python3 -m pytest -q tools/m4/test_dynview_c13_c.py
"""
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

import dynview
import pytest
from test_dynview_c13 import (line, player, player_set, portrait_frame,
                              season_lines_fixture, tot, write_league)
from m4.test_dynview import box_rec, write_box
from test_teamids import build_maj

FILES = os.environ.get('DYNVIEW_FILES', '/mnt/nvme/tlrb2/files')
HERE_C = os.path.join(HERE, 'dynview_c')
HOST = os.path.join(HERE_C, 'dynview_host')
EXE = os.path.join(HERE_C, 'DYNVIEW.EXE')
DOSBOX = (os.environ.get('DOSBOX') or shutil.which('dosbox-x')
          or '/mnt/nvme/src/dosbox-x/src/dosbox-x')
DOS_FONTS = ('MAIN.FNT', 'BOLD.FNT', 'DEFAULT.PAL')

FB_SIZE = 64000
ESC, ENTER, TAB = dynview.KEY_ESC, dynview.KEY_ENTER, dynview.KEY_TAB
UP, DOWN = dynview.KEY_UP, dynview.KEY_DOWN
LEFT, RIGHT = dynview.KEY_LEFT, dynview.KEY_RIGHT
PGUP, PGDN = dynview.KEY_PGUP, dynview.KEY_PGDN
MINUS, PLUS, EQUALS = dynview.KEY_MINUS, dynview.KEY_PLUS, dynview.KEY_EQUALS
ARROWS = (LEFT, RIGHT, UP, DOWN, PGUP, PGDN)
K1, K2, K3, K4, K7, K9 = (ord(c) for c in '123479')     # hub rows: history, HoF, leaders, ...
MENU, LEAD, SET, CARD = (dynview.SCREEN_MENU, dynview.SCREEN_LEADERS,
                         dynview.SCREEN_SETTINGS, dynview.SCREEN_CARD)
SEASON, BY_YEAR = dynview.MODE_SHIFT, 2 * dynview.MODE_SHIFT
SEASON_LABELS = [c[0] for c in dynview.SEASON_CATS]     # 17 categories
CAREER_LABELS = [c[0] for c in dynview.CATS]            # 18 categories
START = {'hub': (MENU, 0, 0), 'review': (dynview.SCREEN_REVIEW, 0, 0),
         'title': (MENU, 0, dynview.TITLE_FLAG)}
FLAG = {'hub': None, 'review': '/REVIEW', 'title': '/TITLE'}
TEAMS = {0: [(0, 'BOS'), (2, 'DET')], 1: [(0, 'NYA')]}
MS = [(3, 0, 2, 3000), (2, 1, 5, 500)]
BIG_ENTRIES = 400
# (tag, keys, mode): the frames of the MENU, the hub screens and the title and review starts
FRAMES = [('hub', (), 'hub'), ('history', (K1,), 'hub'), ('hof', (K2,), 'hub'),
          ('leaders_by_year', (K3, TAB, TAB), 'hub'), ('milestones', (K4,), 'hub'),
          ('awards', (K9,), 'hub'), ('settings', (K7,), 'hub'),
          ('settings_start', (K7, DOWN, DOWN), 'hub'), ('title', (), 'title'),
          ('title_leaders', (K3,), 'title'), ('review', (), 'review')]


def fonts_ready():
    return os.path.exists(os.path.join(FILES, 'MAIN.FNT'))


def dos_ready():
    return os.path.isfile(EXE) and os.path.isfile(DOSBOX) and os.access(DOSBOX, os.X_OK)


needs_fonts = pytest.mark.skipif(not fonts_ready(), reason='fonts missing (DYNVIEW_FILES)')
needs_dos = pytest.mark.skipif(not (dos_ready() and fonts_ready()),
                               reason='DYNVIEW.EXE, dosbox-x or fonts missing')


# ---------------------------------------------------------------- fixtures
def league(tmp_path, players=None, name='lg', seasons=3, start=None, lines=None, ms=None,
           teams=None):
    """one league dir: HISTORY.DAT (player_set by default), SEASLINE.DAT, MILESTON.DAT and
    LEAGUE.MAJ (the teams {lg: [(slot, abbr)]}) when given"""
    ldir = tmp_path / name
    write_league(ldir, player_set() if players is None else players, seasons=seasons,
                 start=start, lines=lines, ms=ms)
    if teams is not None:
        (ldir / 'LEAGUE.MAJ').write_bytes(build_maj(teams))
    return ldir


def thirty_players():
    """30 career batters with H 10..39: LEADERS CAREER H has 30 rows (three pages)"""
    return [player('P%02d' % e, first='A', totals=tot(H=10 + e)) for e in range(30)]


def nine_season_league(tmp_path):
    """ALPHA with 9 seasons of lines (entry 0): the card has 7 rows a page"""
    recs = [line(0, n, face=0, totals=tot(G=n, AB=400 + n, H=100 + n, HR=n, RBI=n, SB=n, BB=n),
                 war10=10 * n) for n in range(1, 10)]
    return league(tmp_path, [player('ALPHA', first='B', totals=tot(G=45, AB=3645, H=945, HR=45),
                                    war10=90)], seasons=9, lines=recs, name='card9')


def rand_totals(rng, pitcher):
    if pitcher:
        return tot(G=rng.randrange(1, 70), W=rng.randrange(0, 25), L=rng.randrange(0, 20),
                   SV=rng.randrange(0, 40), OUTS=rng.randrange(0, 900),
                   ER=rng.randrange(0, 300), PSO=rng.randrange(0, 300),
                   SHO=rng.randrange(0, 4), CG=rng.randrange(0, 8))
    ab = rng.randrange(0, 650)
    return tot(G=rng.randrange(1, 160), AB=ab, H=rng.randrange(0, ab + 1),
               HR=rng.randrange(0, 50), RBI=rng.randrange(0, 150), R=rng.randrange(0, 150),
               SB=rng.randrange(0, 60), BB=rng.randrange(0, 120), D2=rng.randrange(0, 45),
               T3=rng.randrange(0, 12))


def big_lines_league(tmp_path, name='big'):
    """400 players and 4000 SEASLINE lines over 12 seasons (about 320 KB): each season has
    distinct entries (334 in seasons 1..4, 333 after), so no two lines share an entry and season"""
    rng = random.Random(0xB16)
    players = []
    for e in range(BIG_ENTRIES):
        pit = int(e % 5 == 0)
        players.append(player('P%03d' % e, first='A', pitcher=pit, pos1=0 if pit else 3,
                              totals=rand_totals(rng, pit), war10=rng.randrange(-100, 600)))
    lines = []
    for s in range(12):
        for e in rng.sample(range(BIG_ENTRIES), 334 if s < 4 else 333):
            pit = int(e % 5 == 0)
            lines.append(line(e, s + 1, team=rng.randrange(0, 20), pitcher=pit,
                              pos1=0 if pit else 3, totals=rand_totals(rng, pit),
                              war10=rng.randrange(-100, 600)))
    ldir = tmp_path / name
    write_league(ldir, players, seasons=12, lines=lines)
    return ldir


def sidx(label):
    return SEASON_LABELS.index(label)


def season_keys(label):
    """keys from CAREER H to the SEASON category label (TAB keeps H, RIGHT steps the list)"""
    return [K3, TAB] + [RIGHT] * ((sidx(label) - sidx('H')) % len(SEASON_LABELS))


def ports(tmp_path):
    """the ANMS and GAME dirs of a test (both exist; a test may put PORTRAIT.ANM in ANMS)"""
    anms, game = tmp_path / 'anms', tmp_path / 'game'
    anms.mkdir(exist_ok=True)
    game.mkdir(exist_ok=True)
    return str(anms), str(game)


def hist_bytes(d):
    path = os.path.join(str(d), 'HISTORY.DAT')
    return open(path, 'rb').read() if os.path.exists(path) else None


def hist_year(h):
    """the start year as HISTORY.DAT bytes 18..19 hold it (raw, not start_year())"""
    return int.from_bytes(h[18:20], 'little')


# ---------------------------------------------------------------- host and Python runs
def toks(keys):
    """key list -> /KEYS: tokens: arrows and pages as 0x codes, clicks as Lx.y, right click R"""
    out = []
    for k in keys:
        if isinstance(k, tuple):
            out.append('L%d.%d' % (k[1], k[2]))
        elif k == 'R':
            out.append('R')
        elif k in ARROWS:
            out.append('0x%04x' % k)
        else:
            out.append(str(k))
    return ','.join(out)


def run_host(ldir, raw, keys, mode, anms, game):
    assert os.path.exists(HOST), 'dynview_host missing: build dynview_c first'
    argv = [HOST, '/RAW:' + raw]
    if FLAG[mode]:
        argv.append(FLAG[mode])
    if keys:
        argv.append('/KEYS:' + toks(keys))
    argv += ['/ANMS:' + anms, '/GAME:' + game, str(ldir), FILES]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, 'host rc %d: %s' % (r.returncode, r.stderr[:400])
    return open(raw, 'rb').read()


def py_run(ldir, tmp_path, keys=(), mode='hub'):
    """the Python side of main(): the start state, then each key; a click goes through
    click_to_key and cursor_to first, and 'R' is ESC. Returns (state, data)."""
    anms, game = ports(tmp_path)
    data = dynview.load_data(str(ldir), FILES, game, anms)
    state = START[mode]
    for k in keys:
        if isinstance(k, tuple):
            key, row = dynview.click_to_key(state, data, k[1], k[2])
            if key is None:
                continue
            if row is not None:
                state = dynview.cursor_to(state, row)
            state, _ex = dynview.step(state, key, data)
        else:
            state, _ex = dynview.step(state, ESC if k == 'R' else k, data)
    return state, data


def py_fb(ldir, tmp_path, keys=(), mode='hub'):
    state, data = py_run(ldir, tmp_path, keys, mode)
    return bytes(dynview.render(state, data))


def assert_frames(a, b, tag):
    """equal 64000 B frames; on a mismatch the first differing pixel as (x, y)"""
    assert len(a) == FB_SIZE and len(b) == FB_SIZE, tag + ': frame is not 64000 B'
    if a == b:
        return
    i = next(k for k in range(FB_SIZE) if a[k] != b[k])
    pytest.fail('%s: first diff at pixel (%d, %d): host %d, python %d'
                % (tag, i % 320, i // 320, a[i], b[i]))


def run_pair(ldir, tmp_path, tag, keys=(), mode='hub'):
    """host and Python each on their own copy of the league (a settings step writes
    HISTORY.DAT): the frames and the HISTORY.DAT bytes must match. Returns (frame, HISTORY.DAT)."""
    base = tempfile.mkdtemp(prefix=tag + '_', dir=str(tmp_path))
    h, p = os.path.join(base, 'h'), os.path.join(base, 'p')
    shutil.copytree(str(ldir), h)
    shutil.copytree(str(ldir), p)
    anms, game = ports(tmp_path)
    a = run_host(h, os.path.join(base, 'out.RAW'), keys, mode, anms, game)
    b = py_fb(p, tmp_path, keys, mode)
    assert_frames(a, b, tag)
    ha, hb = hist_bytes(h), hist_bytes(p)
    assert ha == hb, tag + ': HISTORY.DAT differs from Python'
    return a, ha


def check(ldir, tmp_path, tag, keys=(), mode='hub'):
    """the host frame, checked against Python"""
    return run_pair(ldir, tmp_path, tag, keys, mode)[0]


# ---------------------------------------------------------------- C13.1 start year
@needs_fonts
def test_start_year_step_creates_a_missing_history(tmp_path):
    """no HISTORY.DAT: a START YEAR step creates it, 32 B with bytes 18..19 set, on both sides"""
    ldir = league(tmp_path, name='nohist')
    os.remove(str(ldir / 'HISTORY.DAT'))
    _, hist = run_pair(ldir, tmp_path, 'nohist_start', [K7, DOWN, DOWN, RIGHT])
    assert len(hist) == 32
    assert hist_year(hist) == 1994


@needs_fonts
@pytest.mark.parametrize('raw', [0, 1950, 2101])
def test_menu_settings_and_titles_with_start_year(tmp_path, raw):
    """raw 0 and 2101 read as 1993; 1950 shows in every year label of the hub screens"""
    players = player_set() + [player('HALL', first='H', status=3, hof=2, totals=tot(H=1))]
    ldir = league(tmp_path, players, start=raw, lines=season_lines_fixture(), ms=MS)
    _, data = py_run(ldir, tmp_path, [K7])
    shown = {0: '1993', 1950: '1950', 2101: '1993'}[raw]
    assert dynview.settings_rows(data)[2] == ('START YEAR', shown)
    for tag, keys, mode in FRAMES:
        check(ldir, tmp_path, '%d_%s' % (raw, tag), keys, mode)


@needs_fonts
@pytest.mark.parametrize('raw, year', [(0, 1991), (1950, 1948), (2101, 1991)])
def test_start_year_steps_write_identical_history(tmp_path, raw, year):
    """RIGHT +1, '+' +10, '-' -10, LEFT x3 on START YEAR, then ENTER (no change). Only bytes
    18..19 of HISTORY.DAT change, and the host writes the bytes Python writes"""
    ldir = league(tmp_path, start=raw)
    orig = hist_bytes(ldir)
    keys = [K7, DOWN, DOWN, RIGHT, PLUS, MINUS, LEFT, LEFT, LEFT, ENTER]
    _, hist = run_pair(ldir, tmp_path, 'steps%d' % raw, keys)
    assert hist_year(hist) == year
    assert len(hist) == len(orig)
    assert {i for i in range(len(orig)) if orig[i] != hist[i]} <= {18, 19}


@needs_fonts
def test_start_year_clamps_at_2100_and_1871(tmp_path):
    cases = [('hi', 2095, [K7, DOWN, DOWN, PLUS, RIGHT, RIGHT], 2100),
             ('lo', 1875, [K7, DOWN, DOWN, MINUS, LEFT, LEFT], 1871),
             ('eq', 1990, [K7, DOWN, DOWN, EQUALS, MINUS], 1990)]
    for name, start, keys, year in cases:
        ldir = league(tmp_path, start=start, name=name)
        _, hist = run_pair(ldir, tmp_path, name, keys)
        assert hist_year(hist) == year, name


# ---------------------------------------------------------------- C13.3 LEADERS modes
@needs_fonts
def test_leaders_career_and_season_categories(tmp_path):
    """CAREER HR, TAB to SEASON HR, RIGHT through every SEASON category (the 17th wraps back to
    H), LEFT wrap from category 0, then the BY YEAR frames and their '-', '+' and '=' ends"""
    lines = season_lines_fixture() + [line(1, 3, totals=tot(G=10, AB=40, H=12, HR=1, RBI=3))]
    ldir = league(tmp_path, start=1990, lines=lines, teams=TEAMS)
    check(ldir, tmp_path, 'career_hr', [K3, RIGHT])
    check(ldir, tmp_path, 'season_hr', [K3, RIGHT, TAB])
    check(ldir, tmp_path, 'career_left_wrap', [K3, LEFT])
    assert py_run(ldir, tmp_path, [K3, LEFT])[0] == (LEAD, 0, len(CAREER_LABELS) - 1)
    first = check(ldir, tmp_path, 'season_h', [K3, TAB])
    steps = [check(ldir, tmp_path, 'season_r%d' % i, [K3, TAB] + [RIGHT] * i)
             for i in range(1, len(SEASON_LABELS) + 1)]
    assert steps[-1] == first
    assert len(set(steps)) == len(SEASON_LABELS)
    check(ldir, tmp_path, 'season_left_wrap', [K3, TAB] + [LEFT] * 4)
    assert py_run(ldir, tmp_path, [K3, TAB] + [LEFT] * 4)[0] == \
        (LEAD, 0, SEASON + len(SEASON_LABELS) - 1)
    by = [K3, TAB, TAB]
    init = check(ldir, tmp_path, 'by_year_init', by)
    s, data = py_run(ldir, tmp_path, by)
    assert s == (LEAD, 0, BY_YEAR + sidx('H'), 0, 3)                  # seasons 1..3 have lines
    assert dynview.screen_title(s, data) == '1992 LEADERS: H'
    one = check(ldir, tmp_path, 'by_year_minus', by + [MINUS])
    two = check(ldir, tmp_path, 'by_year_minus2', by + [MINUS, MINUS])
    assert one != two != init
    assert py_run(ldir, tmp_path, by + [MINUS, MINUS])[0] == \
        (LEAD, 0, BY_YEAR + sidx('H'), 0, 1)
    assert check(ldir, tmp_path, 'by_year_minus3', by + [MINUS] * 3) == two   # oldest: stays
    assert check(ldir, tmp_path, 'by_year_plus', by + [MINUS, PLUS]) == init
    assert check(ldir, tmp_path, 'by_year_equals_newest', by + [EQUALS]) == init


# ---------------------------------------------------------------- C13.2 SEASLINE.DAT edge files
@needs_fonts
def test_season_without_seaslines_bad_header_and_short_tail(tmp_path):
    """no SEASLINE.DAT; byte 3 = 1 (no lines); a partial 80 B record at the end (dropped).
    The bad header reads as no file, the tail as the file without it"""
    nolines = league(tmp_path, name='nolines')
    base = league(tmp_path, lines=season_lines_fixture(), name='base')
    bad = league(tmp_path, lines=season_lines_fixture(), name='bad')
    raw = bytearray((bad / 'SEASLINE.DAT').read_bytes())
    raw[3] = 1
    (bad / 'SEASLINE.DAT').write_bytes(bytes(raw))
    tail = league(tmp_path, lines=season_lines_fixture(), name='tail')
    with open(str(tail / 'SEASLINE.DAT'), 'ab') as f:
        f.write(line(5, 2, totals=tot(G=9, H=9))[:40])
    no_season = check(nolines, tmp_path, 'nolines_season', [K3, TAB])
    check(nolines, tmp_path, 'nolines_by_year', [K3, TAB, TAB])
    assert check(bad, tmp_path, 'badhdr_season', [K3, TAB]) == no_season
    check(bad, tmp_path, 'badhdr_by_year', [K3, TAB, TAB])
    check(tail, tmp_path, 'tail_season_hr', season_keys('HR'))
    assert check(tail, tmp_path, 'tail_by_year', [K3, TAB, TAB]) == \
        check(base, tmp_path, 'base_by_year', [K3, TAB, TAB])


# ---------------------------------------------------------------- C13.4 cursor
@needs_fonts
def test_leaders_cursor_rows_and_pages(tmp_path):
    """DOWN x3, UP at the top, DOWN x12 (the page follows), PGDN to page 2 of 3 and back, PGDN
    at the last page"""
    ldir = league(tmp_path, thirty_players(), name='cursor')
    base = check(ldir, tmp_path, 'cur_top', [K3])
    assert check(ldir, tmp_path, 'cur_down3', [K3, DOWN, DOWN, DOWN]) != base
    assert check(ldir, tmp_path, 'cur_up_at_top', [K3, UP]) == base
    check(ldir, tmp_path, 'cur_down12', [K3] + [DOWN] * 12)
    assert py_run(ldir, tmp_path, [K3] + [DOWN] * 12)[0] == (LEAD, 1, 0, 12)
    page1 = check(ldir, tmp_path, 'cur_pgdn1', [K3, PGDN])
    assert py_run(ldir, tmp_path, [K3, PGDN])[0] == (LEAD, 1, 0, 12)
    check(ldir, tmp_path, 'cur_pgdn2', [K3, PGDN, PGDN])
    assert py_run(ldir, tmp_path, [K3, PGDN, PGDN])[0] == (LEAD, 2, 0, 24)
    assert check(ldir, tmp_path, 'cur_pgdn_last_stays', [K3, PGDN, PGDN, PGDN]) == \
        check(ldir, tmp_path, 'cur_pgdn2_again', [K3, PGDN, PGDN])
    assert check(ldir, tmp_path, 'cur_pgup', [K3, PGDN, PGDN, PGUP]) == page1
    check(ldir, tmp_path, 'cur_down12_enter', [K3] + [DOWN] * 12 + [ENTER])


# ---------------------------------------------------------------- C13.5 ENTER and the card
@needs_fonts
def test_enter_opens_batter_and_pitcher_cards(tmp_path):
    """ENTER on a batter row, a pitcher row and a SEASON row opens the card; ESC returns to the
    identical list frame"""
    ldir = league(tmp_path, start=1990, lines=season_lines_fixture(), teams=TEAMS)
    w_keys = [RIGHT] * CAREER_LABELS.index('W')
    check(ldir, tmp_path, 'card_bat', [K3, DOWN, ENTER])
    assert py_run(ldir, tmp_path, [K3, DOWN, ENTER])[0] == (CARD, 0, 1)
    assert check(ldir, tmp_path, 'card_bat_esc', [K3, DOWN, ENTER, ESC]) == \
        check(ldir, tmp_path, 'list_bat', [K3, DOWN])
    check(ldir, tmp_path, 'card_pit', [K3] + w_keys + [ENTER])
    check(ldir, tmp_path, 'card_pit_row1', [K3] + w_keys + [DOWN, ENTER])
    assert check(ldir, tmp_path, 'card_pit_esc', [K3] + w_keys + [DOWN, ENTER, ESC]) == \
        check(ldir, tmp_path, 'list_pit', [K3] + w_keys + [DOWN])
    check(ldir, tmp_path, 'card_season', [K3, TAB, ENTER])
    assert py_run(ldir, tmp_path, [K3, TAB, ENTER])[0] == (CARD, 0, 3)
    assert check(ldir, tmp_path, 'card_season_esc', [K3, TAB, ENTER, ESC]) == \
        check(ldir, tmp_path, 'list_season', [K3, TAB])


@needs_fonts
def test_card_season_rows_paging_over_seven(tmp_path):
    """nine seasons of lines: PGDN to the second page, PGDN again stays, PGUP back"""
    ldir = nine_season_league(tmp_path)
    page0 = check(ldir, tmp_path, 'c9_p0', [K3, ENTER])
    page1 = check(ldir, tmp_path, 'c9_p1', [K3, ENTER, PGDN])
    assert py_run(ldir, tmp_path, [K3, ENTER, PGDN])[0] == (CARD, 1, 0)
    assert check(ldir, tmp_path, 'c9_p1_stays', [K3, ENTER, PGDN, PGDN]) == page1
    assert check(ldir, tmp_path, 'c9_back_p0', [K3, ENTER, PGDN, PGUP]) == page0


@needs_fonts
def test_card_portrait_from_anms_missing_frame_and_no_file(tmp_path):
    """PORTRAIT.ANM with 2 stored 48x56 frames: face 1 shows; face 5 is past the file and draws
    the gray box; with the file gone the card is the gray box too"""
    anms, _ = ports(tmp_path)
    port = os.path.join(anms, 'PORTRAIT.ANM')
    with open(port, 'wb') as f:
        f.write(struct.pack('<H', 2) + portrait_frame(40) + portrait_frame(41))
    alpha = [player('ALPHA', first='B', totals=tot(G=1, AB=1, H=5))]
    ldir = league(tmp_path, alpha, seasons=2, name='port1',
                  lines=[line(0, 1, face=0), line(0, 2, face=1)])
    shown = check(ldir, tmp_path, 'portrait_face1', [K3, ENTER])
    assert py_run(ldir, tmp_path, [K3, ENTER])[0] == (CARD, 0, 0)
    ldir5 = league(tmp_path, alpha, seasons=2, name='port5', lines=[line(0, 2, face=5)])
    check(ldir5, tmp_path, 'portrait_face5_past_file', [K3, ENTER])
    os.remove(port)
    none = check(ldir, tmp_path, 'portrait_no_file', [K3, ENTER])
    assert shown != none


@needs_fonts
def test_card_portrait_from_oldport_range(tmp_path):
    """OLDPORT.ANM in the GAME dir: face 981 is frame 0, 982 frame 1; a face at OLD_FACE_END (1509)
    and up is out of range and draws the gray box"""
    _, game = ports(tmp_path)
    with open(os.path.join(game, 'OLDPORT.ANM'), 'wb') as f:
        f.write(portrait_frame(100) + portrait_frame(101))
    alpha = [player('ALPHA', first='B', totals=tot(G=1, AB=1, H=5))]
    ldir = league(tmp_path, alpha, seasons=2, name='old1',
                  lines=[line(0, 1, face=981), line(0, 2, face=982)])
    check(ldir, tmp_path, 'oldport_face982', [K3, ENTER])
    ldir2 = league(tmp_path, alpha, seasons=2, name='old2', lines=[line(0, 2, face=1509)])
    check(ldir2, tmp_path, 'oldport_face_out_of_range', [K3, ENTER])


@needs_fonts
def test_card_without_lines_and_esc_back_to_the_list(tmp_path):
    """DELTA (entry 3) has no lines: the card says so; ESC returns to the list row"""
    ldir = league(tmp_path, lines=season_lines_fixture()[:3], name='nolines_card')
    card = check(ldir, tmp_path, 'card_no_lines', [K3, DOWN, DOWN, DOWN, ENTER])
    assert py_run(ldir, tmp_path, [K3, DOWN, DOWN, DOWN, ENTER])[0] == (CARD, 0, 3)
    list_row = check(ldir, tmp_path, 'list_row3', [K3, DOWN, DOWN, DOWN])
    assert check(ldir, tmp_path, 'card_no_lines_esc', [K3, DOWN, DOWN, DOWN, ENTER, ESC]) == \
        list_row
    assert card != list_row


@needs_fonts
def test_big_card_thirty_seasons_pgdn_four_times(tmp_path):
    """one entry with 30 seasons of lines: PGDN x4 reaches the last page (rows 28..29), a fifth
    PGDN stays"""
    lines = [line(0, n, totals=tot(G=n, AB=100 + n, H=10 + n, HR=n % 7, RBI=n, SB=n % 3,
                                   BB=n % 4), war10=3 * n) for n in range(1, 31)]
    ldir = league(tmp_path, [player('BIG', first='A', totals=tot(G=400, AB=1500, H=500, HR=40))],
                  seasons=30, lines=lines, name='card30')
    base = [K3, ENTER]
    for p in range(1, 5):
        check(ldir, tmp_path, 'card30_p%d' % p, base + [PGDN] * p)
    assert py_run(ldir, tmp_path, base + [PGDN] * 4)[0] == (CARD, 4, 0)
    assert check(ldir, tmp_path, 'card30_p4_stays', base + [PGDN] * 5) == \
        check(ldir, tmp_path, 'card30_p4', base + [PGDN] * 4)


# ---------------------------------------------------------------- C13.6 clicks and --keys
@needs_fonts
def test_clicks_on_hub_rows_gap_and_right_click(tmp_path):
    ldir = league(tmp_path, lines=season_lines_fixture(), start=1990)
    hub = check(ldir, tmp_path, 'hub', [])
    assert check(ldir, tmp_path, 'click_row0', [('L', 100, 40)]) == \
        check(ldir, tmp_path, 'key1', [K1])
    assert check(ldir, tmp_path, 'click_row2', [('L', 100, 60)]) == \
        check(ldir, tmp_path, 'key3', [K3])
    check(ldir, tmp_path, 'click_row10_world_series', [('L', 100, 148)])
    assert check(ldir, tmp_path, 'click_gap', [('L', 100, 67)]) == hub
    assert check(ldir, tmp_path, 'leaders_right_click', [K3, 'R']) == hub


@needs_fonts
def test_clicks_on_leaders_rows_title_and_footer(tmp_path):
    ldir = league(tmp_path, thirty_players(), name='clicks')
    lead = check(ldir, tmp_path, 'lead_top', [K3])
    assert check(ldir, tmp_path, 'click_row1_card', [K3, ('L', 100, 50)]) == \
        check(ldir, tmp_path, 'enter_row1_card', [K3, DOWN, ENTER])
    assert check(ldir, tmp_path, 'click_title_left', [K3, ('L', 100, 14)]) == \
        check(ldir, tmp_path, 'key_left', [K3, LEFT])
    assert check(ldir, tmp_path, 'click_title_right', [K3, ('L', 250, 14)]) == \
        check(ldir, tmp_path, 'key_right', [K3, RIGHT])
    assert check(ldir, tmp_path, 'click_footer_right', [K3, ('L', 250, 190)]) == \
        check(ldir, tmp_path, 'key_pgdn', [K3, PGDN])
    assert check(ldir, tmp_path, 'click_footer_left_on_page0', [K3, ('L', 100, 190)]) == lead
    small = league(tmp_path, name='small')          # four CAREER H rows: row 6 is empty
    assert check(small, tmp_path, 'click_empty_band', [K3, ('L', 100, 35 + 66 + 2)]) == \
        check(small, tmp_path, 'small_top', [K3])


@needs_fonts
def test_clicks_on_start_year_left_and_right_halves(tmp_path):
    ldir = league(tmp_path, start=1990, name='sethalves')
    y = 35 + 22 + 3                                 # the START YEAR band
    frame_l, hist_l = run_pair(ldir, tmp_path, 'set_click_left', [K7, ('L', 159, y)])
    assert hist_year(hist_l) == 1989
    frame_r, hist_r = run_pair(ldir, tmp_path, 'set_click_right', [K7, ('L', 160, y)])
    assert hist_year(hist_r) == 1991
    assert frame_l == check(ldir, tmp_path, 'set_key_left', [K7, DOWN, DOWN, LEFT])
    assert frame_r == check(ldir, tmp_path, 'set_key_right', [K7, DOWN, DOWN, RIGHT])


def test_click_bands_python_rules(tmp_path):
    """click_to_key bands of C13.6 with no fonts: hub rows, title and footer halves at x 160,
    the START YEAR halves, and an empty row band"""
    ldir = league(tmp_path, name='bands')
    data = dynview.load_data(str(ldir))
    hub, lead, st = (MENU, 0, 0), (LEAD, 0, 0), (SET, 0, 0)
    assert dynview.click_to_key(hub, data, 100, 35) == (ord('1'), None)
    assert dynview.click_to_key(hub, data, 100, 44) == (ord('1'), None)
    assert dynview.click_to_key(hub, data, 100, 45) == (None, None)
    assert dynview.click_to_key(hub, data, 100, 154) == (ord('W'), None)
    assert dynview.click_to_key(hub, data, 100, 155) == (None, None)
    assert dynview.click_to_key(lead, data, 159, 8) == (LEFT, None)
    assert dynview.click_to_key(lead, data, 160, 20) == (RIGHT, None)
    assert dynview.click_to_key(lead, data, 100, 7) == (None, None)
    assert dynview.click_to_key(lead, data, 100, 21) == (None, None)
    assert dynview.click_to_key(lead, data, 159, 183) == (PGUP, None)
    assert dynview.click_to_key(lead, data, 160, 183) == (PGDN, None)
    assert dynview.click_to_key(lead, data, 100, 182) == (None, None)
    assert dynview.click_to_key(lead, data, 100, 50) == (ENTER, 1)
    assert dynview.click_to_key(lead, data, 100, 35 + 66 + 2) == (None, None)  # 4 rows only
    assert dynview.click_to_key(st, data, 159, 60) == (LEFT, 2)
    assert dynview.click_to_key(st, data, 160, 60) == (RIGHT, 2)
    assert dynview.click_to_key(st, data, 100, 49) == (ENTER, 1)
    assert dynview.click_to_key((SET, 0, 2), data, 100, 14) == (LEFT, None)
    assert dynview.click_to_key(st, data, 100, 14) == (None, None)


# ---------------------------------------------------------------- big files
@needs_fonts
def test_big_seaslines_season_era_hr_and_by_year(tmp_path):
    """4000 SEASLINE lines over 12 seasons (more than 300 KB)"""
    ldir = big_lines_league(tmp_path)
    assert os.path.getsize(os.path.join(str(ldir), 'SEASLINE.DAT')) > 300000
    check(ldir, tmp_path, 'big_season_hr', [K3, TAB, LEFT, LEFT])
    assert py_run(ldir, tmp_path, [K3, TAB, LEFT, LEFT])[0] == (LEAD, 0, SEASON + sidx('HR'))
    check(ldir, tmp_path, 'big_season_era', season_keys('ERA'))
    by = [K3, TAB, TAB]
    check(ldir, tmp_path, 'big_by_year', by)
    assert py_run(ldir, tmp_path, by + [MINUS] * 3)[0] == (LEAD, 0, BY_YEAR + sidx('H'), 0, 9)
    check(ldir, tmp_path, 'big_by_year_minus3', by + [MINUS] * 3)


# ---------------------------------------------------------------- DOS (headless DOSBox-X)
BAT_LADDER = ['if errorlevel 3 goto e3', 'if errorlevel 2 goto e2',
              'if errorlevel 1 goto e1', 'echo 0 > RC.TXT', 'goto end',
              ':e3', 'echo 3 > RC.TXT', 'goto end',
              ':e2', 'echo 2 > RC.TXT', 'goto end',
              ':e1', 'echo 1 > RC.TXT', ':end']


def run_dos(cdir, bat_lines):
    """RUN.BAT (CRLF) in cdir under headless dosbox-x; returns the RC.TXT code"""
    shutil.copy2(EXE, os.path.join(cdir, 'DYNVIEW.EXE'))
    with open(os.path.join(cdir, 'RUN.BAT'), 'wb') as f:
        for text in list(bat_lines) + BAT_LADDER:
            f.write(text.encode('latin-1') + b'\r\n')
    rc_txt = os.path.join(cdir, 'RC.TXT')
    if os.path.exists(rc_txt):
        os.remove(rc_txt)
    env = dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
    proc = subprocess.run([DOSBOX, '-silent', '-set', 'mixer nosound=true', '-set',
                           'cpu cycles=max', '-c', 'mount c ' + cdir, '-c', 'c:',
                           '-c', 'RUN.BAT', '-c', 'exit'],
                          capture_output=True, text=True, timeout=600, env=env)
    if not os.path.exists(rc_txt):
        raise AssertionError('RC.TXT missing rc=%d out=%s err=%s'
                             % (proc.returncode, proc.stdout[-400:], proc.stderr[-400:]))
    return int(open(rc_txt).read().strip() or 0)


@needs_dos
def test_dos_big_season_hr_matches_python(tmp_path):
    """DYNVIEW.EXE /RAW on the 4000-line league, SEASON HR (CAREER H, TAB, LEFT x2)"""
    ldir = big_lines_league(tmp_path, name='dosbig')
    keys = [K3, TAB, LEFT, LEFT]
    d = tmp_path / 'dos'
    (d / 'LEAGUE').mkdir(parents=True)
    (d / 'FONTS').mkdir()
    for f in os.listdir(str(ldir)):
        shutil.copy2(os.path.join(str(ldir), f), str(d / 'LEAGUE' / f))
    for f in DOS_FONTS:
        shutil.copy2(os.path.join(FILES, f), str(d / 'FONTS' / f))
    rc = run_dos(str(d), ['DYNVIEW.EXE /RAW:OUT.RAW /KEYS:%s LEAGUE FONTS' % toks(keys)])
    assert rc == 0, 'dos rc %d' % rc
    dos = open(str(d / 'OUT.RAW'), 'rb').read()
    assert_frames(dos, py_fb(ldir, tmp_path, keys), 'dos big SEASON HR')


# ---------------------------------------------------------------- C23c PLAYOFFS parity
KP = ord('P')
Kp = ord('p')

def playoff_league(tmp_path):
    """the season-lines league with round box records (AL DS two games), the WS game-1
    MILESTON record, and the box rows of that WS game for the BOX LEFT fallback"""
    ldir = league(tmp_path, lines=season_lines_fixture(), start=1990,
                  ms=[(3, 0, 192, 5 * 256 + 3)])
    write_box(ldir, [
        box_rec(3, 16, 4, 0 * 256 + 16, (5, 3, 9, 7, 1, 0, 0, 0), b=1, i=1),
        box_rec(3, 16, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)),
        box_rec(3, 16, 2, 0xffff, (80, 5, 2, 2, 1, 1, 8, 30)),
        box_rec(3, 17, 4, 0 * 256 + 16, (2, 6, 8, 6, 0, 1, 0, 0), b=1, i=2),
        box_rec(3, 17, 0, 0xffff, (4, 1, 2, 1, 0, 0, 1, 0)),
        box_rec(3, 17, 2, 0xffff, (80, 5, 2, 2, 1, 1, 8, 30)),
    ])
    return ldir


@needs_fonts
def test_playoffs_hub_screen_parity(tmp_path):
    """the hub's 12th row, key P and p, the PLAYOFFS pages and seasons, ENTER on pages 0
    and 1, the empty season's message, ESC back out of the PBOX, and a click on the
    hub's PLAYOFFS row"""
    ldir = playoff_league(tmp_path)
    hub = check(ldir, tmp_path, 'c23c_hub', [])
    assert check(ldir, tmp_path, 'c23c_open_P', [KP]) == \
        check(ldir, tmp_path, 'c23c_open_p', [Kp])
    check(ldir, tmp_path, 'c23c_click_hub_row11', [('L', 100, 35 + 11 * 11 + 3)])
    check(ldir, tmp_path, 'c23c_playoffs_p0', [KP])
    check(ldir, tmp_path, 'c23c_playoffs_p0_pgdn', [KP, PGDN])
    check(ldir, tmp_path, 'c23c_playoffs_left', [KP, LEFT])
    check(ldir, tmp_path, 'c23c_playoffs_right_stays', [KP, RIGHT])
    check(ldir, tmp_path, 'c23c_playoffs_left_left', [KP, LEFT, LEFT])
    check(ldir, tmp_path, 'c23c_empty_enter', [KP, LEFT, ENTER])
    check(ldir, tmp_path, 'c23c_enter_first_game', [KP, ENTER])
    check(ldir, tmp_path, 'c23c_pbox_esc', [KP, ENTER, ESC])
    check(ldir, tmp_path, 'c23c_pbox_right', [KP, ENTER, RIGHT])
    check(ldir, tmp_path, 'c23c_pbox_ws_left', [87, 49, LEFT])
    assert check(ldir, tmp_path, 'c23c_click_equals_P',
                 [('L', 100, 35 + 11 * 11 + 3)]) == \
        check(ldir, tmp_path, 'c23c_open_P_again', [KP])
    assert check(ldir, tmp_path, 'c23c_hub_again', []) == hub
