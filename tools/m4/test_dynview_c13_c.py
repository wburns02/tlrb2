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
K1, K2, K3, K4, K7, K9 = (ord(c) for c in '123479')     # hub rows: history, HoF, leaders,
                                                        # milestones, settings, awards
MENU, LEAD, SET, CARD = (dynview.SCREEN_MENU, dynview.SCREEN_LEADERS,
                         dynview.SCREEN_SETTINGS, dynview.SCREEN_CARD)
SA, AH = dynview.SCREEN_AWARDS, dynview.SCREEN_AWHIST
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


# ---------------------------------------------------------------- C62 BOX / PBOX row cursor
def box_cursor_league(tmp_path, name):
    """3 seasons, entries 0 ALPHA (batting rows) and 4 ECHO (pitching rows) of two WS
    games (kind 192 / 193 MILESTON records), one round game with a flags 4 header and
    its rows for the PBOX; team names through the MAJ"""
    ldir = league(tmp_path, player_set(), seasons=3, name=name,
                  ms=[(3, 0, 192, 5 * 256 + 3), (3, 0, 193, 3 * 256 + 16)],
                  teams=TEAMS)
    write_box(ldir, [
        box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0)),
        box_rec(3, 0, 0, 1, (3, 0, 1, 0, 0, 2, 0, 0)),
        box_rec(3, 0, 2, 4, (72, 5, 2, 2, 1, 1, 8, 30)),
        box_rec(3, 0, 2, 0xffff, (10, 1, 0, 0, 0, 1, 0, 3)),
        box_rec(3, 16, 4, 5 * 256 + 3, (5, 3, 9, 7, 1, 0, 0, 0), b=1, i=1),
        box_rec(3, 16, 0, 2, (2, 0, 1, 0, 0, 0, 1, 1)),
        box_rec(3, 16, 2, 6, (80, 5, 2, 2, 1, 1, 8, 30)),
    ])
    return ldir


@needs_fonts
def test_box_pbox_row_cursor_parity(tmp_path):
    """C62 frame parity: the BOX footer, the cursor on a batting row and on a pitching
    row, the card of a batting row and ESC back with the row kept, ENTER on a header row
    (the unchanged frame), PGDN; the PBOX cursor and its card rows ('?' records: the
    frame is the every-row-lit cursor on the headers too)"""
    ldir = box_cursor_league(tmp_path, 'boxcur')
    _, data = py_run(ldir, tmp_path, [87, 49])
    assert dynview.FOOTERS[dynview.SCREEN_BOX] == \
        'ENTER CARD  LEFT RIGHT GAME  PGUP PGDN  ESC'
    assert py_run(ldir, tmp_path, [87, 49, RIGHT])[0] == (dynview.SCREEN_BOX, 0, 1)
    assert dynview.row_entry((dynview.SCREEN_BOX, 0, 0, 1), data) == 0
    assert dynview.row_entry((dynview.SCREEN_BOX, 0, 0, 4), data) == 4   # ECHO pitching
    assert dynview.row_entry((dynview.SCREEN_BOX, 0, 0, 0), data) is None
    # the box: 2 team headers + 2 batting rows + 2 PITCHING headers + 2 pitching rows
    n = dynview.total_rows((dynview.SCREEN_BOX, 0, 0), data)
    assert n == 8 == len(dynview.box_entries(data['hist'], data['ms'], data['box'],
                                             data['teams'], 3, 0))
    check(ldir, tmp_path, 'c62_box', [87, 49])
    check(ldir, tmp_path, 'c62_box_cursor_bat', [87, 49, DOWN])
    check(ldir, tmp_path, 'c62_box_cursor_pit', [87, 49, DOWN, DOWN, DOWN, DOWN])
    check(ldir, tmp_path, 'c62_box_enter_card', [87, 49, DOWN, ENTER])
    assert py_run(ldir, tmp_path, [87, 49, DOWN, ENTER])[0] == (CARD, 0, 0)
    check(ldir, tmp_path, 'c62_box_card_esc', [87, 49, DOWN, ENTER, ESC])
    assert py_run(ldir, tmp_path, [87, 49, DOWN, ENTER, ESC])[0] == \
        (dynview.SCREEN_BOX, 0, 0, 1)
    check(ldir, tmp_path, 'c62_box_enter_header', [87, 49, ENTER])
    check(ldir, tmp_path, 'c62_box_pgdn', [87, 49, PGDN])
    check(ldir, tmp_path, 'c62_box_right_reset', [87, 49, DOWN, RIGHT])
    assert py_run(ldir, tmp_path, [87, 49, DOWN, RIGHT])[0] == (dynview.SCREEN_BOX, 0, 1)
    check(ldir, tmp_path, 'c62_box_left_back', [87, 49, RIGHT, LEFT])
    # the round game's player rows open their cards: CHARLIE (entry 2), GOLF (entry 6)
    check(ldir, tmp_path, 'c62_pbox', [KP, ENTER])
    check(ldir, tmp_path, 'c62_pbox_cursor', [KP, ENTER, DOWN])
    check(ldir, tmp_path, 'c62_pbox_card', [KP, ENTER, DOWN, ENTER])
    assert py_run(ldir, tmp_path, [KP, ENTER, DOWN, ENTER])[0] == (CARD, 0, 2)
    check(ldir, tmp_path, 'c62_pbox_card_pit', [KP, ENTER, DOWN, DOWN, DOWN, ENTER])
    assert py_run(ldir, tmp_path, [KP, ENTER, DOWN, DOWN, DOWN, ENTER])[0] == (CARD, 0, 6)
    check(ldir, tmp_path, 'c62_pbox_esc', [KP, ENTER, DOWN, ENTER, ESC])
    # a header row names no card
    assert dynview.row_entry((dynview.SCREEN_PBOX, 0, 0, 0),
                             py_run(ldir, tmp_path, [KP, ENTER])[1]) is None


# ---------------------------------------------------------------- C26 PLAYER CARD POST row
def post_league(tmp_path, name, entry0_lines=8, pitcher=False):
    """ALPHA (a batter, or a pitcher with pitcher) with entry0_lines seasons of lines, whose
    entry 0 has box rows: 3 WS games and 2 round games (each round game with its flags 4
    header); entry 1 HOTEL has no box rows"""
    totals = (tot(G=20, W=5, L=3, SV=2, OUTS=300, ER=50, PSO=30) if pitcher else
              tot(G=100, AB=400, H=120, HR=10, RBI=50, SB=10))
    players = [player('ALPHA', first='B', pitcher=int(pitcher), pos1=0 if pitcher else 3,
                      totals=totals, war10=50), player_set()[7]]
    recs = [line(0, n, pitcher=int(pitcher), pos1=0 if pitcher else 3,
                 totals=rand_totals(random.Random(n), pitcher),
                 war10=10 * n) for n in range(1, entry0_lines + 1)]
    ldir = league(tmp_path, players, seasons=entry0_lines, lines=recs, name=name)
    bat = (0, 0, 2, 1, 0, 0, 1, 0)
    write_box(ldir, [
        box_rec(3, 0, 0, 0, bat),
        box_rec(3, 1, 0, 0, (3, 0, 1, 2, 1, 0, 0, 2)),
        box_rec(3, 2, 0, 0, (3, 1, 1, 0, 1, 0, 0, 1)),
        box_rec(3, 16, 4, 0 * 256 + 16, (5, 3, 9, 7, 1, 0, 0, 0), b=1, i=1),
        box_rec(3, 16, 0, 0, (2, 0, 1, 0, 0, 0, 1, 1)),
        box_rec(3, 17, 4, 0 * 256 + 16, (2, 6, 8, 6, 0, 1, 0, 0), b=1, i=2),
        box_rec(3, 17, 0, 0, (1, 0, 0, 1, 0, 0, 0, 0)),
        box_rec(3, 0, 2, 0, (72, 5, 2, 2, 1, 1, 8, 30)),
        box_rec(3, 3, 2, 0, (12, 1, 1, 0, 0, 0, 2, 6)),   # entry 0 also pitched (harmless)
        box_rec(3, 0, 0, 1, (9, 9, 9, 9, 9, 9, 9, 9)),    # another entry: ignored
    ])
    return ldir


@needs_fonts
def test_card_post_batter_parity(tmp_path):
    """a batter card with a POST row: page 0 (6 season rows, CAREER at 161, POSTSEASON at
    172) and the nolines card of an entry with box rows but no lines"""
    ldir = post_league(tmp_path, 'postbat')
    check(ldir, tmp_path, 'c26_bat_p0', [K3, ENTER])
    check(ldir, tmp_path, 'c26_bat_p1', [K3, ENTER, PGDN])
    assert py_run(ldir, tmp_path, [K3, ENTER])[0] == (CARD, 0, 0)
    check(ldir, tmp_path, 'c26_bat_pgdn', [K3, ENTER, PGDN, PGDN])


@needs_fonts
def test_card_post_pitcher_parity(tmp_path):
    """a pitcher card with a POST row: W L SV and WAR cells '-', IP and ERA from the sums"""
    ldir = post_league(tmp_path, 'postpit', entry0_lines=3, pitcher=True)
    w_keys = [RIGHT] * CAREER_LABELS.index('W')
    check(ldir, tmp_path, 'c26_pit', [K3] + w_keys + [ENTER])
    check(ldir, tmp_path, 'c26_pit_pgdn', [K3] + w_keys + [ENTER, PGDN])


@needs_fonts
def test_card_post_paging_and_no_post(tmp_path):
    """an 8-line entry with a POST row: page 1 (2 rows), PGDN past the last page and back;
    HOTEL (no box rows): the frame is the unchanged 7-rows-per-page card"""
    ldir = post_league(tmp_path, 'postpage')
    page1 = check(ldir, tmp_path, 'c26_page1', [K3, ENTER, PGDN])
    assert check(ldir, tmp_path, 'c26_page1_stays', [K3, ENTER, PGDN, PGDN]) == page1
    assert check(ldir, tmp_path, 'c26_back_p0', [K3, ENTER, PGDN, PGUP]) == \
        check(ldir, tmp_path, 'c26_page0', [K3, ENTER])
    # HOTEL, entry 1: no box rows (only entry 0's), no net: an unchanged card
    check(ldir, tmp_path, 'c26_not_post', [K3, DOWN, DOWN, DOWN, DOWN, DOWN, DOWN, DOWN,
                                           DOWN, ENTER])
    check(ldir, tmp_path, 'c26_not_post_pgdn', [K3, DOWN, DOWN, DOWN, DOWN, DOWN, DOWN,
                                                DOWN, DOWN, ENTER, PGDN, PGDN, PGDN])


# ---------------------------------------------------------------- C27 MILESTONES WATCH
def watch_players():
    """the C27 watch fixture's players (9 entries, 6 watch rows)"""
    return [
        player('HIT2950', first='A', totals=tot(H=2950, AB=8000)),
        player('HIT1700', first='B', totals=tot(H=1700, AB=5000)),
        player('HIT3100', first='C', totals=tot(H=3100, AB=9000)),
        player('HR298', first='D', totals=tot(HR=298, AB=3000, H=800)),
        player('HR395', first='E', totals=tot(HR=395, AB=3000, H=800)),
        player('RETIRED', first='F', status=2, totals=tot(H=2990, AB=8000)),
        player('KMAN', first='G', pitcher=1, pos1=0, totals=tot(PSO=2995, G=400,
                                                               OUTS=8000)),
        player('SBTIE1', first='H', totals=tot(SB=490)),
        player('SBTIE2', first='I', totals=tot(SB=490)),
    ]


@needs_fonts
def test_watch_parity_frames(tmp_path):
    """MILESTONES mode 0 (the new footer), WATCH page 0 with the cursor on row 1, WATCH
    empty (the message row), WATCH after ENTER (the card), and a title click that toggles
    the mode; every frame matches Python's bytes"""
    ldir = league(tmp_path, watch_players(), seasons=3, name='watch')
    empty = league(tmp_path, [player('NONE', totals=tot(H=10))], seasons=1, name='watch0')
    check(ldir, tmp_path, 'c27_ms0', [K4])
    check(ldir, tmp_path, 'c27_watch', [K4, RIGHT])
    check(ldir, tmp_path, 'c27_watch_row1', [K4, RIGHT, DOWN])
    assert py_run(ldir, tmp_path, [K4, RIGHT, DOWN])[0] == (4, 0, 1, 1)
    check(ldir, tmp_path, 'c27_watch_enter_card', [K4, RIGHT, DOWN, ENTER])
    assert py_run(ldir, tmp_path, [K4, RIGHT, DOWN, ENTER])[0] == (CARD, 0, 3)
    check(ldir, tmp_path, 'c27_watch_esc_back', [K4, RIGHT, DOWN, ENTER, ESC])
    assert check(ldir, tmp_path, 'c27_watch_title_click', [K4, ('L', 100, 14)]) == \
        check(ldir, tmp_path, 'c27_watch_key_right', [K4, RIGHT])
    check(empty, tmp_path, 'c27_watch_empty', [K4, RIGHT])
    check(empty, tmp_path, 'c27_ms0_empty', [K4])
    check(ldir, tmp_path, 'c27_watch_pgdn', [K4, RIGHT, PGDN])


# ---------------------------------------------------------------- C61 MILESTONES row cursor
def ms_row_league(tmp_path, name):
    """15 entries, MILESTON records with kind 2 and 32 (the 3000 HITS and 51 HR rows in
    file order; a NO_AWARD record sorts in as a NONE row)"""
    players = [player('P%02d' % e, totals=tot(H=10 + e)) for e in range(15)]
    ms = [(3, 0, 2, 3000), (3, 1, 32, 51), (3, 0xffff, 2, 2000), (2, 2, 5, 500)]
    for s in range(12, 28):                      # rows past one page (24 + 4 = 28)
        ms.append((2, s, 2, 100 + s))
    return league(tmp_path, players, seasons=3, name=name, ms=ms)


@needs_fonts
def test_milestones_cursor_parity_frames(tmp_path):
    """cat 0 with the new footer and the cursor on row 1, PGDN to page 1 (cursor row 12),
    the card opened from row 1 and ESC back with the row kept, cat 1 unchanged; every
    frame matches Python's bytes"""
    ldir = ms_row_league(tmp_path, 'ms61')
    empty = league(tmp_path, [player('NONE', totals=tot(H=10))], seasons=1, name='ms61e')
    st, data = py_run(ldir, tmp_path, [K4, DOWN])
    assert st == (4, 0, 0, 1)
    assert dynview.milestone_items(data['hist'], data['ms'])[1][1] == 1   # row 1 is entry 1
    check(ldir, tmp_path, 'c61_ms0_row1', [K4, DOWN])
    check(ldir, tmp_path, 'c61_ms0_pgdn', [K4, PGDN])
    st, _data = py_run(ldir, tmp_path, [K4, PGDN])
    assert st == (4, 1, 0, 12)
    check(ldir, tmp_path, 'c61_ms0_enter_card', [K4, DOWN, ENTER])
    st, _data = py_run(ldir, tmp_path, [K4, DOWN, ENTER])
    assert st == (CARD, 0, 1)
    check(ldir, tmp_path, 'c61_ms0_esc_back', [K4, DOWN, ENTER, ESC])
    st, _data = py_run(ldir, tmp_path, [K4, DOWN, ENTER, ESC])
    assert st == (4, 0, 0, 1)
    # row 2 is the NO_AWARD record: no card, the state stays
    st, data = py_run(ldir, tmp_path, [K4, DOWN, DOWN])
    assert st == (4, 0, 0, 2)
    assert dynview.row_entry(st, data) is None
    check(ldir, tmp_path, 'c61_ms0_no_award', [K4, DOWN, DOWN, ENTER])
    # an empty list: ENTER does nothing; no message row either (mode 0 has none)
    check(empty, tmp_path, 'c61_ms0_empty', [K4, ENTER])
    # the WATCH behaviour is unchanged (C27): cursor row 1, the card, ESC back
    wl = league(tmp_path, watch_players(), seasons=3, name='ms61w')
    check(wl, tmp_path, 'c61_watch_row1', [K4, RIGHT, DOWN])
    check(wl, tmp_path, 'c61_watch_card_esc', [K4, RIGHT, DOWN, ENTER, ESC])


# ---------------------------------------------------------------- C28 AWARD HISTORY
def awhist_players():
    """the C28 fixture players (8 entries; the names match test_dynview_c13.awhist_league)"""
    return [player(n, totals=tot(H=100 + e), war10=50 + e) for e, n in
            enumerate(['WIN1X', 'WIN2X', 'WIN3X', 'WIN4X', 'GLOVE', 'LEADR', 'FILLA',
                       'FILLB'])]


def awhist_league_c(tmp_path):
    """4 seasons with AL MVP records in seasons 2, 3, 4 (season 1 only the fallback
    winners of its season entry, no award record at all), an NL GLOVE C record in
    season 3, leader records the H key ignores, and a WS record"""
    ldir = league(tmp_path, awhist_players(), seasons=4, start=1990, name='awh',
                  ms=[(2, 1, 64, 30), (2, 6, 128, 312),
                      (3, 2, 64, (-25) & 0xffff), (3, 4, 99, 987),
                      (3, 5, 160, 205), (4, 3, 64, 0), (4, 0, 192, 5 * 256 + 3)])
    hp = ldir / 'HISTORY.DAT'
    d = bytearray(hp.read_bytes())
    d[32 + 88:32 + 100] = bytes((0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0))
    hp.write_bytes(bytes(d))
    return ldir


# ---------------------------------------------------------------- C39 POSTSEASON LEADERS
def post_leader_league(tmp_path, name):
    """The post_league box plus player rows for entries 1 and 5 and a flags 4 header:
    entry 0 (HITTER, retired) H 2 over 2 games, entry 1 (HOTEL, active) H 2 over 1 game
    and IP 2.0 over another, entry 5 (ACE) nothing but a header (no rows)."""
    ldir = post_league(tmp_path, name)
    write_box(ldir, [
        box_rec(3, 0, 4, 0 * 256 + 16, (5, 3, 9, 7, 1, 0, 0, 0), b=1, i=1),
        box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0)),
        box_rec(3, 1, 0, 0, (3, 0, 1, 0, 1, 0, 0, 0)),
        box_rec(3, 0, 0, 1, (1, 0, 2, 0, 0, 0, 1, 0)),
        box_rec(3, 0, 2, 1, (20, 5, 2, 2, 1, 1, 3, 12)),
    ])
    return ldir


@needs_fonts
def test_awhist_parity_frames(tmp_path):
    """C28: AWARD HISTORY for AL MVP with the cursor on row 1, the NL GLOVE C code after
    the steps, the message row of an award never given, SEASON AWARDS with the new
    footer, H from the awards (both the award and the leader row), the card opened from
    the history and the identical state ESC returns twice, and a title click (LEFT)"""
    ldir = awhist_league_c(tmp_path)
    # H (72) from the SEASON AWARDS' AL MVP row opens AL MVP (code 0), the cursor DOWN
    # to row 1: the history frame and the ESC back through the card
    check(ldir, tmp_path, 'c28_awards_footer', [K9])
    assert py_run(ldir, tmp_path, [K9])[0] == (SA, 0, 0)
    check(ldir, tmp_path, 'c28_open_h', [K9, 72])
    assert py_run(ldir, tmp_path, [K9, 72])[0] == (16, 0, 0)
    check(ldir, tmp_path, 'c28_row1', [K9, 72, DOWN])
    assert py_run(ldir, tmp_path, [K9, 72, DOWN])[0] == (16, 0, 0, 1)
    # H from the leader record row: code 0 as well
    assert py_run(ldir, tmp_path, [K9, DOWN, 72])[0] == (16, 0, 0)
    check(ldir, tmp_path, 'c28_h_on_leader', [K9, DOWN, 72])
    # LEFT from code 0 to 39 (the message row), then RIGHT to 38, then to the NL GLOVE C
    # code after LEFT wrap walk 0 -> 39 -> 38 ... to 23
    check(ldir, tmp_path, 'c28_left_wrap_msg', [K9, 72, LEFT])
    assert py_run(ldir, tmp_path, [K9, 72, LEFT])[0] == (16, 0, 39)
    # RIGHT from 39 wraps to 0
    check(ldir, tmp_path, 'c28_right_back_zero', [K9, 72, LEFT, RIGHT])
    assert py_run(ldir, tmp_path, [K9, 72, LEFT, RIGHT])[0] == (16, 0, 0)
    # 17 LEFTs: 0 -> 39 -> ... -> 23 (the NL GLOVE C code)
    wrap = [K9, 72] + [LEFT] * 17
    assert py_run(ldir, tmp_path, wrap)[0] == (16, 0, 23)
    check(ldir, tmp_path, 'c28_walk_to_nlglove', wrap)
    # the title click on AWARD HISTORY is LEFT (the code steps back)
    assert check(ldir, tmp_path, 'c28_title_click', [K9, 72, ('L', 100, 14)]) == \
        check(ldir, tmp_path, 'c28_key_left', [K9, 72, LEFT])
    # ENTER on the history row opens the card; ESC back twice (card -> history ->
    # awards), each state identical
    hist_keys = [K9, 72, ENTER]
    assert py_run(ldir, tmp_path, hist_keys)[0] == (CARD, 0, 3)
    check(ldir, tmp_path, 'c28_card_from_hist', hist_keys)
    check(ldir, tmp_path, 'c28_card_esc_weak', hist_keys + [ESC])
    assert py_run(ldir, tmp_path, hist_keys + [ESC])[0] == (16, 0, 0)
    check(ldir, tmp_path, 'c28_esc_to_awards', hist_keys + [ESC, ESC])
    assert py_run(ldir, tmp_path, hist_keys + [ESC, ESC])[0] == (9, 0, 0)
    # AWARD HISTORY H-less state (a Right/Left walk) ESC: back to the SEASON AWARDS
    # state kept by its H (identical), and a no-history league (the default back)
    check(ldir, tmp_path, 'c28_pgdn_stays', [K9, 72, PGDN])
    empty = league(tmp_path, name='awhempty')
    check(empty, tmp_path, 'c28_empty', [K9, 72, LEFT])


@needs_fonts
def test_awhist_parity_flat_league_frames(tmp_path):
    """the season-3 league without the fallback patch (every season has award records):
    the fallback rule never applies, and the history rows come from the records alone"""
    ldir = league(tmp_path, awhist_players(), seasons=4, start=1990, name='awhflat',
                  ms=[(2, 1, 64, 30), (3, 2, 64, (-25) & 0xffff), (4, 3, 64, 0),
                      (3, 4, 99, 987)])
    check(ldir, tmp_path, 'c28_flat_mvp', [K9, 72])
    check(ldir, tmp_path, 'c28_flat_noglove', [K9, 72, LEFT])


@needs_fonts
def test_awhist_parity_nl_fallback_frames(tmp_path):
    """C28: the NL codes 20 and 22 (k <= 2) take season 1's fallback winners aw[3 + k]
    in both ports (the C port once tested the code a, not k, so NL never fell back)"""
    ldir = awhist_league_c(tmp_path)
    nl = [K9, 72] + [RIGHT] * 20
    assert py_run(ldir, tmp_path, nl)[0] == (16, 0, 20)
    check(ldir, tmp_path, 'c28_nl_mvp_fallback', nl)
    check(ldir, tmp_path, 'c28_nl_k2_fallback', nl + [RIGHT, RIGHT])


@needs_fonts
def test_post_leaders_parity(tmp_path):
    """POSTSEASON H page 0 (mark, G, value), the empty message, POST IP (7.0), the frame
    after TAB from BY YEAR, the card opened from POST row 1, and ESC back to the list"""
    ldir = post_leader_league(tmp_path, 'postlead')
    by = [K3, TAB, TAB]
    post_h = check(ldir, tmp_path, 'c39_post_h', [K3, TAB, TAB, TAB])
    assert py_run(ldir, tmp_path, [K3, TAB, TAB, TAB])[0] == \
        (LEAD, 0, 3 * dynview.MODE_SHIFT + dynview.POST_CATS.index(
            ('H', 'count', 2)))
    # the empty H table of a league with no box: one message row
    empty = league(tmp_path, name='postnone')
    check(empty, tmp_path, 'c39_post_empty', [K3, TAB, TAB, TAB])
    check(ldir, tmp_path, 'c39_post_ip', [K3, TAB, TAB, TAB, RIGHT, RIGHT, RIGHT, RIGHT,
                                          RIGHT])
    assert check(ldir, tmp_path, 'c39_tab_from_by_year', by + [TAB]) == post_h
    card = check(ldir, tmp_path, 'c39_post_card', [K3, TAB, TAB, TAB, DOWN, ENTER])
    assert py_run(ldir, tmp_path, [K3, TAB, TAB, TAB, DOWN, ENTER])[0] == (CARD, 0, 1)
    assert check(ldir, tmp_path, 'c39_post_esc', [K3, TAB, TAB, TAB, DOWN, ENTER, ESC]) == \
        check(ldir, tmp_path, 'c39_post_h_row1', [K3, TAB, TAB, TAB, DOWN])
    assert card != post_h
    s, data = py_run(ldir, tmp_path, [K3, TAB, TAB, TAB])
    assert dynview.screen_title(s, data) == 'POSTSEASON LEADERS: H'
    assert dynview.footer_text(s, data) == dynview.FOOTERS[LEAD]
    assert dynview.leaders_body(s, data)[0] == dynview.COLS_POST_LEADERS


@needs_fonts
def test_post_leaders_entry_past_history_parity(tmp_path):
    """a BOXSCORE.DAT index past HISTORY.DAT's entries (below POST_ENTRY_MAX) lists as '?'
    with no mark in both ports, and never crashes the Python reference"""
    ldir = post_league(tmp_path, 'postpast')
    write_box(ldir, [box_rec(3, 0, 0, 4000, (4, 1, 3, 1, 0, 0, 1, 0)),
                     box_rec(3, 0, 0, 0, (4, 1, 2, 1, 0, 0, 1, 0))])
    check(ldir, tmp_path, 'c39_post_past', [K3, TAB, TAB, TAB])
    s, data = py_run(ldir, tmp_path, [K3, TAB, TAB, TAB])
    rows = dynview.leaders_body(s, data)[1]
    assert rows[0][1:3] == ('?', ' ')

# ---------------------------------------------------------------- C40 PLAYER CARD HONORS
def honors_players():
    """ALPHA with award records and HALL (HOF), then HOTEL with nothing"""
    return [player('ALPHA', first='B', totals=tot(H=3000, AB=9000, HR=400, RBI=1500), war10=600),
            player('HOTEL', first='H', totals=tot(), war10=0),
            player('HALL', first='H', status=3, hof=4, totals=tot(H=1), war10=1)]


@needs_fonts
def test_card_honors_parity(tmp_path):
    """HONORS page 0 (a batter: counts row, award/leader/milestone records in (season,
    group, order) order, the fallback winners of seasons without records), page 1 after
    PGDN and back, the no-item entry's single row, the HOF entry, and the SEASONS card
    with the new footer; every frame matches Python's bytes"""
    ms = [(1, 0, 64, 1), (1, 0, 2, 3000), (2, 0, 128, 330), (2, 0, 65, 2),
          (3, 1, 64, 3), (4, 0, 64, 1)]
    ldir = league(tmp_path, honors_players(), start=1990, seasons=5, ms=ms, name='hon')
    open_alpha = [K3, ENTER]
    p0 = check(ldir, tmp_path, 'c40_p0', open_alpha + [ord('H')])
    p1 = check(ldir, tmp_path, 'c40_p1', open_alpha + [ord('H'), PGDN])
    assert p0 != p1
    assert check(ldir, tmp_path, 'c40_back_p0', open_alpha + [ord('H'), PGDN, PGUP]) == p0
    assert py_run(ldir, tmp_path, open_alpha + [ord('H'), PGDN])[0] == (CARD, 1, 0, 1)
    # PGDN stays on the last page and PGUP returns
    assert check(ldir, tmp_path, 'c40_stays', open_alpha + [ord('H'), PGDN, PGDN]) == p1
    # HOTEL (entry 1): no ms records name its entry and no fallback (its awards are 0):
    # the counts row only
    check(ldir, tmp_path, 'c40_none', [K3, DOWN, ENTER, ord('H')])
    # HALL (entry 2): the season 4 AL MVP record names entry 2, so no season 4 fallback;
    # HALL OF FAME (group 1) lands at hof_season 4 = 1993, after that record
    check(ldir, tmp_path, 'c40_hof', [K3, DOWN, DOWN, ENTER, ord('H')])
    # the SEASONS view with the new footer, and the two footers themselves
    check(ldir, tmp_path, 'c40_seasons_footer', open_alpha)
    s6, data6 = py_run(ldir, tmp_path, open_alpha)
    assert dynview.footer_text(s6, data6) == 'LEFT RIGHT  PGUP PGDN  H HONORS  ESC'
    assert dynview.footer_text((CARD, 0, 0, 1), data6) == \
        'LEFT RIGHT  PGUP PGDN  H SEASONS  ESC'


# ---------------------------------------------------------------- C58 card LEFT/RIGHT
@needs_fonts
def test_c58_browse_parity_frames(tmp_path):
    """C58: the card browses the list it was opened from. LEADERS CAREER H card then
    RIGHT (to row 1's card, card_back row 1), ESC back to the moved row, the AWARDS
    NONE-row skip, the HONORS view kept through a browse, and the LAST-row no-op."""
    # the plain player_set league: CAREER H rows ALPHA(0), BRAVO, CHARLIE, DELTA...
    ldir = league(tmp_path, player_set(), seasons=3, start=1990,
                  lines=season_lines_fixture(), name='c58lead')
    keys0 = [K3, ENTER]
    run_pair(ldir, tmp_path, 'c58_card', keys0)
    run_pair(ldir, tmp_path, 'c58_right', keys0 + [RIGHT])
    assert py_run(ldir, tmp_path, keys0 + [RIGHT])[0] == (CARD, 0, 1)
    assert py_run(ldir, tmp_path, keys0 + [RIGHT])[1]['card_back'] == (LEAD, 0, 0, 1)
    run_pair(ldir, tmp_path, 'c58_right_esc', keys0 + [RIGHT, ESC])
    assert py_run(ldir, tmp_path, keys0 + [RIGHT, ESC])[0] == (LEAD, 0, 0, 1)
    # LEFT twice from the row-1 card stops at row 0
    run_pair(ldir, tmp_path, 'c58_left_left', keys0 + [LEFT, LEFT])
    assert py_run(ldir, tmp_path, keys0 + [LEFT, LEFT])[0] == (CARD, 0, 0)
    # a NONE award row is skipped: the awards list rows 2 GLOVE C (NONE), then row 3
    ms = [(3, 0, 64, 0), (3, 3, 65, 1000), (3, 0xffff, 66, 30), (3, 4, 67, 987),
          (3, 6, 68, 999), (2, 0, 64, 1)]
    ald = league(tmp_path, player_set(), seasons=3, start=1990, ms=ms, name='c58aw')
    akeys = [K9, DOWN, ENTER]
    run_pair(ald, tmp_path, 'c58_aw_card', akeys)
    run_pair(ald, tmp_path, 'c58_aw_right_skip', akeys + [RIGHT])
    run_pair(ald, tmp_path, 'c58_aw_right_esc', akeys + [RIGHT, ESC])
    assert py_run(ald, tmp_path, akeys + [RIGHT])[0] == (CARD, 0, 4)
    # the HONORS view is kept and the page reset through a browse
    run_pair(ald, tmp_path, 'c58_aw_honors_right', akeys + [ord('H'), RIGHT, RIGHT])
    assert py_run(ald, tmp_path, akeys + [ord('H'), RIGHT, RIGHT])[0] == (CARD, 0, 6, 1)



@needs_fonts
def test_card_honors_paging_nine(tmp_path):
    """12 award records over 12 seasons: 13 HONORS rows over 2 pages, PGDN to page 1 and
    back; every frame matches Python's bytes"""
    ms = [(s, 0, 64, 1) for s in range(1, 13)]
    ldir = league(tmp_path, [player('MANY', first='A', totals=tot(H=100))], start=1990,
                  seasons=12, ms=ms, name='honpg')
    open_m = [K3, ENTER]
    p0 = check(ldir, tmp_path, 'c40_nine_p0', open_m + [ord('H')])
    p1 = check(ldir, tmp_path, 'c40_nine_p1', open_m + [ord('H'), PGDN])
    assert p0 != p1
    assert check(ldir, tmp_path, 'c40_nine_stays', open_m + [ord('H'), PGDN, PGDN]) == p1
    assert check(ldir, tmp_path, 'c40_nine_back', open_m + [ord('H'), PGDN, PGUP]) == p0
    s, data = py_run(ldir, tmp_path, open_m + [ord('H'), PGDN])
    assert [r[0] for r in dynview.rows(s, data)] == ['1998', '1999', '2000', '2001']


# ---------------------------------------------------------------- C50 FIND PLAYER host parity
# The FIND PLAYER frames (fb bytes): the empty-query prompt, a filtered frame with the
# cursor on row 1, the no-match frame, the MENU frame with the new footer, and a card
# opened from FIND then ESC back.
KF, Kf = ord('F'), ord('f')


# ---------------------------------------------------------------- the fixture league
def find_players():
    """Entries with last names that collide under the prefix sorts, plus one unused
    entry (status 0) and one lower-case stored last name."""
    return [
        player('SMITH', first='JOHN', status=2, played=12, pos1=3),
        player('smith', first='AARON', status=1, played=5, pos1=0),    # lower case file
        player('SMYTHE', first='ZEKE', status=3, hof=2, played=18, pos1=6),
        player('JONES', first='SAM', status=1, played=4, pos1=5),
        player('UNUSED', first='NO', status=0, played=0, pos1=9),      # never listed
        player('BROWN', first='X', status=1, played=1, pos1=3),
        player('NOBODY', first='Q', status=1, played=2, pos1=7),
    ]


# ---------------------------------------------------------------- C50 FIND PLAYER frames
@needs_fonts
def test_c50_menu_footer_and_open(tmp_path):
    """F and f on the hub open the empty FIND (prompt row, COLS_SINGLE); the hub footer
    carries the F key; ESC goes back to the prompt row (C59), empty query kept cleared."""
    ldir = league(tmp_path, players=player_set(), seasons=3, name='mf')
    hub = run_pair(ldir, tmp_path, 'c50_hub', [])[0]
    assert dynview.FOOTERS[dynview.SCREEN_MENU] == '0-9 W P F SELECT   ESC EXIT'
    oF = run_pair(ldir, tmp_path, 'c50_open_F', [KF])[0]
    of = run_pair(ldir, tmp_path, 'c50_open_f', [Kf])[0]
    assert oF == of
    s, data = py_run(ldir, tmp_path, [KF])
    assert s == (dynview.SCREEN_FIND, 0, 0)
    assert data['find'] == ''
    assert dynview.rows(s, data) == [('TYPE THE START OF A LAST NAME.',)]
    assert dynview.body_cols(s, data) == dynview.COLS_SINGLE
    assert dynview.screen_title(s, data) == 'FIND PLAYER: _'
    assert dynview.footer_text(s, data) == 'TYPE NAME  BKSP  ENTER CARD  ESC MENU'
    # ESC with an empty query goes straight to the hub, then typing letters does nothing there
    assert run_pair(ldir, tmp_path, 'c50_find_esc', [KF, ESC])[0] == hub


@needs_fonts
def test_c59_find_esc_clears_frames(tmp_path):
    """C59 framebuffer parity: ESC on a typed query clears it back to the prompt frame
    (with the ESC MENU footer again), the second ESC reaches the hub; the typed frame
    carries the ESC CLEAR footer, ESC after DOWN resets the cursor with the query."""
    ldir = league(tmp_path, players=find_players(), seasons=3, name='esc9')
    hub = run_pair(ldir, tmp_path, 'c59_hub', [])[0]
    prompt = run_pair(ldir, tmp_path, 'c59_prompt', [KF])[0]
    s, data = py_run(ldir, tmp_path, [KF, ord('S'), ord('M')])
    assert data['find'] == 'SM'
    assert dynview.footer_text(s, data) == 'TYPE NAME  BKSP  ENTER CARD  ESC CLEAR'
    typed = run_pair(ldir, tmp_path, 'c59_typed', [KF, ord('S'), ord('M')])[0]
    assert typed != prompt
    one = run_pair(ldir, tmp_path, 'c59_esc_once', [KF, ord('S'), ord('M'), ESC])[0]
    assert one == prompt
    two = run_pair(ldir, tmp_path, 'c59_esc_twice', [KF, ord('S'), ord('M'), ESC, ESC])[0]
    assert two == hub
    s2, data2 = py_run(ldir, tmp_path, [KF, ord('S'), ord('M'), ESC, ESC])
    assert s2 == (dynview.SCREEN_MENU, 0, 0) and data2['find'] == ''
    # ESC after the cursor moved resets the row and keeps the cleared query
    down = [KF, ord('S'), ord('M'), DOWN]
    run_pair(ldir, tmp_path, 'c59_down', down)
    assert py_run(ldir, tmp_path, down)[0] == (dynview.SCREEN_FIND, 0, 0, 1)
    esc3 = down + [ESC]
    assert run_pair(ldir, tmp_path, 'c59_esc_down', esc3)[0] == prompt
    s3, data3 = py_run(ldir, tmp_path, esc3)
    assert s3 == (dynview.SCREEN_FIND, 0, 0) and data3['find'] == ''


@needs_fonts
def test_c50_empty_prompt_and_no_match_frames(tmp_path):
    """the same league, F then a letter that matches nothing: the NO PLAYER FOUND row
    with COLS_SINGLE; the title carries the query and the cursor."""
    ldir = league(tmp_path, **{
        'players': find_players(), 'seasons': 3, 'name': 'nm'})
    empty = run_pair(ldir, tmp_path, 'c50_prompt', [KF])[0]
    nomatch = run_pair(ldir, tmp_path, 'c50_nomatch', [KF, ord('Z')])[0]
    assert empty != nomatch
    s, data = py_run(ldir, tmp_path, [KF, ord('Z')])
    assert s == (dynview.SCREEN_FIND, 0, 0)
    assert data['find'] == 'Z'
    assert dynview.rows(s, data) == [('NO PLAYER FOUND.',)]
    # the FIND headers stay on the no-match frame (a lone message row of a screen
    # with its own columns); the cursor row is highlighted
    assert dynview.body_cols(s, data) == dynview.COLS_FIND
    assert dynview.screen_title(s, data) == 'FIND PLAYER: Z_'


def _find_cells(hist, q):
    """the find_rows cells without their entries (C50)"""
    return [c for _i, c in dynview.find_rows(hist, q)]


@needs_fonts
def test_c50_filtered_frame_cursor_and_sort(tmp_path):
    """'SM' lists the SM* entries sorted (last upper, first upper, index), lower-case
    last names match, the unused entry (status 0) never shows; DOWN moves the cursor to
    row 1 and the frame matches Python."""
    ldir = league(tmp_path, **{'players': find_players(), 'seasons': 3, 'name': 'filt'})
    keys = [KF, ord('S'), ord('M')]
    frame = run_pair(ldir, tmp_path, 'c50_filter_sm', keys)[0]
    s, data = py_run(ldir, tmp_path, keys)
    assert s == (dynview.SCREEN_FIND, 0, 0)
    assert data['find'] == 'SM'
    assert _find_cells(data['hist'], 'SM') == [
        ('smith, AARON', 'P', '5', 'ACTIVE'),
        ('SMITH, JOHN', '2B', '12', 'RETIRED'),
        ('SMYTHE, ZEKE', 'LF', '18', 'HALL OF FAME')]
    assert dynview.rows(s, data) == _find_cells(data['hist'], 'SM')
    assert dynview.body_cols(s, data) == dynview.COLS_FIND
    assert dynview.screen_title(s, data) == 'FIND PLAYER: SM_'
    # index tiebreak: entry 1 (AARON, lower case in the file) sorts before entry 0
    assert dynview.row_entry(s, data) == 1
    down1 = run_pair(ldir, tmp_path, 'c50_filter_sm_down', keys + [DOWN])[0]
    assert py_run(ldir, tmp_path, keys + [DOWN])[0] == (dynview.SCREEN_FIND, 0, 0, 1)
    assert down1 != frame


@needs_fonts
def test_c50_edit_rules_frame_parity(tmp_path):
    """BACKSPACE removes the last letter, an edit resets the page and the row, the
    FIND_MAX 12 cap holds (the 13th letter does not land), and a letter typed after
    BACKSPACE rebuilds the frame of typing the letters in one go."""
    ldir = league(tmp_path, **{'players': find_players(), 'seasons': 3, 'name': 'edit'})
    keys = [KF, ord('S'), ord('M'), DOWN]
    run_pair(ldir, tmp_path, 'c50_edit_down', keys)
    assert py_run(ldir, tmp_path, keys)[0] == (dynview.SCREEN_FIND, 0, 0, 1)
    back = [KF, ord('S'), ord('M'), DOWN, 8]
    run_pair(ldir, tmp_path, 'c50_edit_bksp_resets', back)
    assert py_run(ldir, tmp_path, back)[0] == (dynview.SCREEN_FIND, 0, 0)
    cap = [KF] + [ord(c) for c in 'ABCDEFGHIJKL'] + [ord('M'), ord('X')]
    run_pair(ldir, tmp_path, 'c50_edit_cap', cap)
    s, data = py_run(ldir, tmp_path, cap)
    assert data['find'] == 'ABCDEFGHIJKL'
    assert dynview.screen_title(s, data) == 'FIND PLAYER: ABCDEFGHIJKL_'
    # a 13th letter never lands: editing to the cap then more keeps 12 chars; BACKSPACE
    # then a letter rebuilds the same frame as typing the two letters in one go
    again = [KF] + [ord(c) for c in 'ABCDEFGHIJKL'] + [ord('M'), 8, ord('L')]
    cap12 = [KF] + [ord(c) for c in 'ABCDEFGHIJKL']
    assert run_pair(ldir, tmp_path, 'c50_edit13', again)[0] == \
        run_pair(ldir, tmp_path, 'c50_edit11', cap12)[0]


@needs_fonts
def test_c50_enter_card_and_esc_back(tmp_path):
    """ENTER on row 1 opens that entry's card (open_card stores the FIND state); ESC
    returns to the exact FIND state with the query kept; C types a letter."""
    ldir = league(tmp_path, **{'players': find_players(), 'seasons': 3, 'name': 'card',
                               'lines': None})
    keys = [KF, ord('S'), ord('M'), DOWN, ENTER]
    card = run_pair(ldir, tmp_path, 'c50_card', keys)[0]
    s, data = py_run(ldir, tmp_path, keys)
    assert s == (dynview.SCREEN_CARD, 0, 0)      # row 1 (SMITH, JOHN ahead of AARON), entry 0
    assert data['card_back'] == (dynview.SCREEN_FIND, 0, 0, 1)
    assert card != run_pair(ldir, tmp_path, 'c50_card_list', [KF, ord('S'), ord('M')])[0]
    back = keys + [ESC]
    assert run_pair(ldir, tmp_path, 'c50_card_esc', back)[0] == \
        run_pair(ldir, tmp_path, 'c50_card_list_again', [KF, ord('S'), ord('M'), DOWN])[0]
    s2, data2 = py_run(ldir, tmp_path, back)
    assert s2 == (dynview.SCREEN_FIND, 0, 0, 1)
    assert data2['find'] == 'SM'
    # C on FIND types a letter (no card), unlike the season RETIREMENTS walk
    c = run_pair(ldir, tmp_path, 'c50_c_types',
                 [KF, ord('C'), ord('H'), ord('A'), ord('R'), ord('L')])[0]
    s3, data3 = py_run(ldir, tmp_path, [KF, ord('C'), ord('H'), ord('A'), ord('R'),
                                        ord('L')])
    assert s3 == (dynview.SCREEN_FIND, 0, 0)
    assert data3['find'] == 'CHARL'
    assert dynview.screen_title(s3, data3) == 'FIND PLAYER: CHARL_'
    assert c != run_pair(ldir, tmp_path, 'c50_c_types_open', [KF])[0]


@needs_fonts
def test_c50_paging_other_keys_do_nothing(tmp_path):
    """PGUP at the top stays (frame equals the plain list), PGDN past the end stays,
    a digit and TAB never type, ENTER on the empty prompt does nothing."""
    ldir = league(tmp_path, **{'players': find_players(), 'seasons': 3, 'name': 'keys'})
    base = run_pair(ldir, tmp_path, 'c50_keys_base', [KF, ord('J')])[0]
    assert run_pair(ldir, tmp_path, 'c50_keys_pgup', [KF, ord('J'), PGUP])[0] == base
    assert run_pair(ldir, tmp_path, 'c50_keys_pgdn', [KF, ord('J'), PGDN])[0] == base
    assert run_pair(ldir, tmp_path, 'c50_keys_digit', [KF, ord('J'), ord('5')])[0] == base
    s, data = py_run(ldir, tmp_path, [KF, ord('J'), ord('5')])
    assert data['find'] == 'J'                 # a digit is never typed
    # the query is non-empty, so the ESC label is CLEAR (C59)
    assert dynview.footer_text(s, data) == 'TYPE NAME  BKSP  ENTER CARD  ESC CLEAR'
    assert py_run(ldir, tmp_path, [KF, ord('J'), PGUP])[0] == (dynview.SCREEN_FIND, 0, 0)

# ---------------------------------------------------------------- C53 HALL OF FAME filters
def hof_players_c53():
    """Five HoF entries (P C SS LF RF), one active DH battery mate and two actives:
    no DH HoF member, so the DH filter shows the message row."""
    return [
        player('PITCHA', first='A', status=3, hof=2, pitcher=1, pos1=0,
               totals=tot(W=300, OUTS=3704, ER=900, PSO=2995), war10=500),
        player('CATCHR', first='C', status=3, hof=3, pitcher=0, pos1=1,
               totals=tot(H=2000, AB=6000, HR=150), war10=400),
        player('SSMAN', first='S', status=3, hof=3, pitcher=0, pos1=5,
               totals=tot(H=2500, AB=8000, HR=80), war10=450),
        player('LFMAN', first='L', status=3, hof=3, pitcher=0, pos1=6,
               totals=tot(H=2300, AB=7800, HR=300), war10=430),
        player('RFMAN', first='R', status=3, hof=2, pitcher=0, pos1=8,
               totals=tot(H=2200, AB=7500, HR=350), war10=420),
        player('DHMAN', first='D', status=1, hof=0, pitcher=0, pos1=9,
               totals=tot(H=1900, AB=7000, HR=280), war10=380),
        player('ACTIVE1', first='X', totals=tot(H=100, AB=2000)),
        player('ACTIVE2', first='Y', pitcher=1, pos1=0, totals=tot(W=10, OUTS=500)),
    ]


@needs_fonts
def test_hof_pitcher_pos1_not_in_position_filter(tmp_path):
    """C53: a HoF pitcher whose pos1 is a batting position (SS 5) shows under ALL and P
    only, never under the SS filter, in Python and in the C port"""
    pl = hof_players_c53()
    pl[0] = player('PITCHA', first='A', status=3, hof=2, pitcher=1, pos1=5,
                   totals=tot(W=300, OUTS=3704, ER=900, PSO=2995), war10=500)
    ldir = league(tmp_path, pl, seasons=4, start=1990, name='hof53p')
    s, data = py_run(ldir, tmp_path, [K2] + [TAB] * 6)
    assert dynview.screen_title(s, data) == 'HALL OF FAME: SS'
    assert [r[0] for r in dynview.rows(s, data)] == ['SSMAN, S']
    check(ldir, tmp_path, 'c53p_ss', [K2] + [TAB] * 6)
    check(ldir, tmp_path, 'c53p_p', [K2, TAB])


@needs_fonts
def test_hof_filter_frames(tmp_path):
    """C53: the ALL page with the new footer, P (the pitcher's row), OF with the cursor
    on row 1, the DH message row of a league with none, TAB wrap back to ALL, and the
    other position pages; every frame matches Python's bytes"""
    ldir = league(tmp_path, hof_players_c53(), seasons=4, start=1990, name='hof53')
    all0 = check(ldir, tmp_path, 'c53_all', [K2])
    assert py_run(ldir, tmp_path, [K2])[0] == (dynview.SCREEN_HOF, 0, 0)
    s, data = py_run(ldir, tmp_path, [K2])
    assert dynview.footer_text(s, data) == 'TAB POSITION   PGUP PGDN   ESC MENU'
    for f in range(1, 9):
        check(ldir, tmp_path, 'c53_f%d' % f, [K2] + [TAB] * f)
    assert py_run(ldir, tmp_path, [K2] + [TAB] * 9)[0] == (dynview.SCREEN_HOF, 0, 0)
    assert check(ldir, tmp_path, 'c53_wrap', [K2] + [TAB] * 9) == all0
    # P shows the one HoF pitcher, OF three outfielders; DH has none
    s, data = py_run(ldir, tmp_path, [K2, TAB])
    assert [r[0] for r in dynview.rows(s, data)] == ['PITCHA, A']
    assert dynview.screen_title(s, data) == 'HALL OF FAME: P'
    s, data = py_run(ldir, tmp_path, [K2] + [TAB] * 7)
    assert [r[0] for r in dynview.rows(s, data)] == ['LFMAN, L', 'RFMAN, R']
    s, data = py_run(ldir, tmp_path, [K2] + [TAB] * 8)
    assert dynview.rows(s, data) == [('NO HALL OF FAMERS AT DH',)]
    assert dynview.body_cols(s, data) == dynview.COLS_SINGLE


@needs_fonts
def test_hof_filter_cursor_card_and_esc_frames(tmp_path):
    """C53: the OF frame with the cursor on row 1, the card opened from a filtered row
    (the cursor entry of hof_order(hist, cat)) and ESC back to the identical filter state"""
    ldir = league(tmp_path, hof_players_c53(), seasons=4, start=1990, name='hof53c')
    of = [K2] + [TAB] * 7
    row1 = check(ldir, tmp_path, 'c53_of_row1', of + [DOWN])
    assert py_run(ldir, tmp_path, of + [DOWN])[0] == (dynview.SCREEN_HOF, 0, 7, 1)
    card = check(ldir, tmp_path, 'c53_card', of + [DOWN, ENTER])
    assert py_run(ldir, tmp_path, of + [DOWN, ENTER])[0] == (dynview.SCREEN_CARD, 0, 4)
    assert check(ldir, tmp_path, 'c53_esc_back', of + [DOWN, ENTER, ESC]) == row1
    # a card from another filter's row 0 (SS) and back
    ss = [K2] + [TAB] * 6
    check(ldir, tmp_path, 'c53_card_ss', ss + [ENTER])
    assert py_run(ldir, tmp_path, ss + [ENTER])[0] == (dynview.SCREEN_CARD, 0, 2)
    assert check(ldir, tmp_path, 'c53_esc_ss', ss + [ENTER, ESC]) == \
        check(ldir, tmp_path, 'c53_ss_plain', ss)


@needs_fonts
def test_hof_filter_empty_leagues_frames(tmp_path):
    """C53: the DH message row of a one-catching league, PGDN on it (stays), and cat 0
    of a league with no HoF members at all (today's empty table, COLS_HOF)"""
    one = league(tmp_path, [player('ONLYC', first='C', status=3, hof=1, pos1=1,
                                   totals=tot(H=100, AB=400))],
                 seasons=2, start=1990, name='hofone')
    msg = check(one, tmp_path, 'c53_empty_dh', [K2] + [TAB] * 8)
    assert py_run(one, tmp_path, [K2] + [TAB] * 8)[0] == (dynview.SCREEN_HOF, 0, 8)
    assert check(one, tmp_path, 'c53_empty_dh_pgdn', [K2] + [TAB] * 8 + [PGDN]) == msg
    assert check(one, tmp_path, 'c53_empty_msg_esc', [K2] + [TAB] * 8 + [ESC]) == \
        check(one, tmp_path, 'c53_plain_esc', [K2, ESC])
    check(one, tmp_path, 'c53_empty_c', [K2, TAB, TAB])
    none = league(tmp_path, [player('ACT', first='A', totals=tot(H=10, AB=40))],
                  seasons=2, name='hofnone')
    check(none, tmp_path, 'c53_nohof_all', [K2])
    assert py_run(none, tmp_path, [K2])[0] == (dynview.SCREEN_HOF, 0, 0)

# ---------------------------------------------------------------- C54 LEADERS active-only
def active_league(tmp_path, name='c54'):
    """Six career batters: three active (H 3000 / 2000 / 2000), two retired and one HoF
    (the retired ones lead the unfiltered list), with season lines for the TAB walk"""
    players = [player('ALPHA', totals=tot(H=3000, AB=9000)),
               player('BRAVO', totals=tot(H=2000, AB=3000)),
               player('CHARLIE', totals=tot(H=2000, AB=3000)),
               player('DELTA', status=2, totals=tot(H=2500, AB=3000)),
               player('ECHO', status=3, totals=tot(H=2400, AB=3000)),
               player('FOXTROT', status=2, totals=tot(H=100))]
    return league(tmp_path, players, name=name)


@needs_fonts
def test_c54_career_active_parity(tmp_path):
    """The CAREER LEADERS frame with the new footer, the ACTIVE frame after A, the ACTIVE
    frame with the cursor on row 1, the empty ACTIVE message frame, and A in SEASON mode
    (the frame is unchanged) all match Python's bytes"""
    ldir = active_league(tmp_path)
    check(ldir, tmp_path, 'c54_career_new_footer', [K3])
    act = check(ldir, tmp_path, 'c54_active', [K3, ord('A')])
    assert check(ldir, tmp_path, 'c54_active_a_lower', [K3, ord('a')]) == act
    check(ldir, tmp_path, 'c54_active_row1', [K3, ord('A'), DOWN])
    empty = league(tmp_path, [player('ALPHA', status=2, totals=tot(H=3000, AB=9000))],
                   name='c54empty')
    check(empty, tmp_path, 'c54_active_empty', [K3, ord('A')])
    season = check(ldir, tmp_path, 'c54_season_base', [K3, TAB])
    assert check(ldir, tmp_path, 'c54_season_a_stays', [K3, TAB, ord('A')]) == season
    # the unfiltered career frame ranks the retired players first again after 'a'
    career = check(ldir, tmp_path, 'c54_career_again', [K3, ord('A'), ord('A')])
    assert career == check(ldir, tmp_path, 'c54_career_plain', [K3])


@needs_fonts
def test_c54_active_flag_survives_and_card_parity(tmp_path):
    """The flag survives the TAB round trip to SEASON and back, the PLAYER CARD opened from
    the ACTIVE list and ESC back to it, LEFT/RIGHT, and ESC to MENU"""
    ldir = active_league(tmp_path)
    act = check(ldir, tmp_path, 'c54_h_after_tabs', [K3, ord('A'), TAB, TAB, TAB, TAB])
    assert check(ldir, tmp_path, 'c54_active_plain', [K3, ord('A')]) == act
    card = check(ldir, tmp_path, 'c54_card_from_active', [K3, ord('A'), ENTER])
    assert py_run(ldir, tmp_path, [K3, ord('A'), ENTER])[0] == (CARD, 0, 0)
    assert check(ldir, tmp_path, 'c54_card_esc_back', [K3, ord('A'), ENTER, ESC]) == \
        check(ldir, tmp_path, 'c54_active_plain2', [K3, ord('A')])
    assert card != act
    check(ldir, tmp_path, 'c54_menu_after_card_esc', [K3, ord('A'), ENTER, ESC, ESC])
    s, data = py_run(ldir, tmp_path, [K3, ord('A')])
    order = [i for _v, i, _e in dynview.career_order(data['hist'], 0, True)]
    assert order == [0, 1, 2]                # the retired entries lead the unfiltered list
    assert dynview.row_entry(s, data) == 0
    assert dynview.screen_title(s, data) == 'ACTIVE LEADERS: H'
    # the filter re-ranks behind the cursor: row 1 is entry 1 (BRAVO)
    down, data2 = py_run(ldir, tmp_path, [K3, ord('A'), DOWN])
    assert dynview.row_entry(down, data2) == 1


# ---------------------------------------------------------------- C56 HISTORY cursor and STANDINGS jump
@needs_fonts
def test_c56_history_cursor_standings_parity(tmp_path):
    """HISTORY with the cursor on row 1, the STANDINGS opened from it (ESC back to the
    identical frame), and the no-history HISTORY frame; every frame matches Python."""
    ldir = league(tmp_path, players=player_set(), seasons=3, start=1990, name='c56')
    nohist = league(tmp_path, name='c56nohist')
    os.remove(str(nohist / 'HISTORY.DAT'))
    check(ldir, tmp_path, 'c56_hist_footer', [K1])
    check(ldir, tmp_path, 'c56_hist_row1', [K1, DOWN])
    assert py_run(ldir, tmp_path, [K1, DOWN])[0] == (dynview.SCREEN_HISTORY, 0, 0, 1)
    check(ldir, tmp_path, 'c56_standings', [K1, DOWN, ENTER])
    assert py_run(ldir, tmp_path, [K1, DOWN, ENTER])[0] == (dynview.SCREEN_STANDINGS, 0, 1)
    check(ldir, tmp_path, 'c56_standings_esc', [K1, DOWN, ENTER, ESC])
    assert py_run(ldir, tmp_path, [K1, DOWN, ENTER, ESC])[0] == \
        (dynview.SCREEN_HISTORY, 0, 0, 1)
    check(ldir, tmp_path, 'c56_esc_menu', [K1, DOWN, ENTER, ESC, ESC])
    check(nohist, tmp_path, 'c56_nohistory', [K1])


@needs_dos
def test_c58_dos_browse_frames(tmp_path):
    """C58 under headless DOSBox-X: HOF card, RIGHT, RIGHT then ESC, LEADERS card RIGHT and
    LEFT, AWARDS card RIGHT, HONORS LEFT, RIGHT on the last award row; DOS bytes == Python"""
    players = player_set()
    for i, hof in ((0, 2), (1, 3), (2, 3)):             # three Hall of Famers
        players[i].update(status=3, hof=hof)
    ms = [(3, 0, 64, 0), (3, 3, 65, 1000), (3, 0xffff, 66, 30), (3, 4, 67, 987),
          (3, 6, 68, 999), (2, 0, 64, 1)]
    ldir = league(tmp_path, players, seasons=3, start=1990, lines=season_lines_fixture(),
                  ms=ms, name='c58dos')
    d = tmp_path / 'dos'
    (d / 'LEAGUE').mkdir(parents=True)
    (d / 'FONTS').mkdir()
    for f in os.listdir(str(ldir)):
        shutil.copy2(os.path.join(str(ldir), f), str(d / 'LEAGUE' / f))
    for f in DOS_FONTS:
        shutil.copy2(os.path.join(FILES, f), str(d / 'FONTS' / f))
    cases = ([K2, DOWN, ENTER], [K2, DOWN, ENTER, RIGHT], [K2, DOWN, ENTER, RIGHT, ESC],
             [K3, DOWN, ENTER, RIGHT], [K3, DOWN, ENTER, LEFT], [K9, ENTER, RIGHT],
             [K9, ENTER, ord('H'), LEFT], [K9, ENTER, PGDN, PGDN, DOWN, DOWN, DOWN, RIGHT])
    for n, keys in enumerate(cases):
        out = 'C58_%d.RAW' % n                          # DOS 8.3 name
        rc = run_dos(str(d), ['DYNVIEW.EXE /RAW:%s /KEYS:%s LEAGUE FONTS' % (out, toks(keys))])
        assert rc == 0, 'case %d: dos rc %d' % (n, rc)
        dos = open(str(d / out), 'rb').read()
        assert_frames(dos, py_fb(ldir, tmp_path, keys), 'c58 dos case %d' % n)

# ---------------------------------------------------------------- C57 STANDINGS row cursor
def standings_league(tmp_path, name='c57'):
    """A three-season league with a four-team MAJ (stems BOS CLE DET ATL, each with a
    V20, so data['teams'] lists them by stable id) and season 1's w_l games."""
    ldir = league(tmp_path, seasons=3, start=1990, name=name,
                  teams={0: [(0, 'BOS'), (2, 'CLE'), (3, 'DET')],
                         1: [(0, 'ATL')]})
    for stem, nm in (('ABOS', 'BOSTON'), ('ACLE', 'CLEVELAND'), ('ADET', 'DETROIT'),
                     ('NATL', 'ATLANTA')):
        (ldir / (stem + '.V20')).write_bytes(nm.encode().ljust(14, b'\0') + bytes(66))
    wl = {0: (10, 5), 2: (8, 2), 3: (6, 4), 16: (7, 9)}
    d = bytearray((ldir / 'HISTORY.DAT').read_bytes())
    d[4], d[5] = 1, 0
    o = 32
    d[o : o + 2] = (1).to_bytes(2, 'little')     # the season number of entry 1
    d[o + 2] = 0xff                              # champion unknown
    for t in range(32):
        w, l = wl.get(t, (0, 0))
        d[o + 24 + 2 * t] = w
        d[o + 25 + 2 * t] = l
    (ldir / 'HISTORY.DAT').write_bytes(bytes(d))
    return ldir


@needs_fonts
def test_c57_standings_cursor_teamhist_parity(tmp_path):
    """The STANDINGS frames with the new footer and the cursor on a team row, TEAM
    HISTORY opened by ENTER and ESC back to the identical frame (the cursor still on
    the row), the no-op ENTER on a header row, and T from the cursor state; every
    frame matches Python."""
    ldir = standings_league(tmp_path)
    hist = [K1, DOWN, ENTER, ord('0')]     # HISTORY row 1 (season 1), ENTER, hub key 0
    # the plain standings page 0 (one season recorded: cat 0 is its newest) and the
    # cursor on the team row 1 (the header is 0)
    check(ldir, tmp_path, 'c57_standings_footer', hist)
    check(ldir, tmp_path, 'c57_standings_cursor', hist + [DOWN])
    # ENTER on the team row opens the TEAM HISTORY of that team (row 1: CLEVELAND, id 2)
    assert py_run(ldir, tmp_path, hist + [DOWN, ENTER])[0] == \
        (dynview.SCREEN_TEAMHIST, 0, 2)
    check(ldir, tmp_path, 'c57_enter_teamhist', hist + [DOWN, ENTER])
    # ESC returns to the standings frame with the cursor still on the row
    assert py_run(ldir, tmp_path, hist + [DOWN, ENTER, ESC])[0] == \
        (dynview.SCREEN_STANDINGS, 0, 0, 1)
    check(ldir, tmp_path, 'c57_teamhist_esc', hist + [DOWN, ENTER, ESC])
    # ENTER on the header row (0) leaves the frame unchanged
    check(ldir, tmp_path, 'c57_enter_header', hist + [ENTER])
    # T from the cursor state keeps the row: ESC comes back to the same cursor frame
    assert py_run(ldir, tmp_path, hist + [DOWN, ord('T'), ESC])[0] == \
        (dynview.SCREEN_STANDINGS, 0, 0, 1)
    check(ldir, tmp_path, 'c57_t_esc', hist + [DOWN, ord('T'), ESC])
    # team id 0 (BOSTON, row 2) opens too: 0 is a real id, not a sentinel
    assert py_run(ldir, tmp_path, hist + [DOWN, DOWN, ENTER])[0] == \
        (dynview.SCREEN_TEAMHIST, 0, 0)
    check(ldir, tmp_path, 'c57_enter_tid0', hist + [DOWN, DOWN, ENTER])

# ---------------------------------------------------------------- C60 TEAM HISTORY row cursor
def teamhist_league(tmp_path, name='c60'):
    """standings_league with three played seasons: CLEVELAND (id 2) has a row for
    each (3, 2, 1), DETROIT (id 3) none in any season (the message row), and each
    season has a standings page."""
    ldir = standings_league(tmp_path, name=name)
    wl = {2: (8, 2), 16: (7, 9)}
    d = bytearray((ldir / 'HISTORY.DAT').read_bytes())
    d[4] = 3
    d[32 + 24 + 2 * 3] = 0                       # DETROIT out of season 1 too
    d[32 + 24 + 2 * 3 + 1] = 0
    for s in (2, 3):
        o = 32 + (s - 1) * 128
        d[o:o + 2] = s.to_bytes(2, 'little')
        d[o + 2] = 0xff
        for t in range(32):
            w, l = wl.get(t, (0, 0))
            d[o + 24 + 2 * t] = w
            d[o + 25 + 2 * t] = l
    (ldir / 'HISTORY.DAT').write_bytes(bytes(d))
    return ldir


@needs_fonts
def test_c60_teamhist_cursor_standings_parity(tmp_path):
    """TEAM HISTORY with the new footer, the cursor on row 1, the STANDINGS opened
    by ENTER and the ESC back with the row kept; the message-row TEAM HISTORY with
    ENTER is the unchanged frame. Every frame matches Python."""
    ldir = teamhist_league(tmp_path)
    # HISTORY row 1 (season 1) ENTER, standings row 1 (CLEVELAND) ENTER:
    # the TEAM HISTORY of CLEVELAND (id 2)
    hist = [K1, DOWN, ENTER, DOWN, ENTER]
    s0, data0 = py_run(ldir, tmp_path, hist, 'hub')
    assert s0 == (dynview.SCREEN_TEAMHIST, 0, 2)
    assert dynview.footer_text(s0, data0) == 'ENTER SEASON  LEFT RIGHT TEAM  PGUP PGDN ESC'
    check(ldir, tmp_path, 'c60_teamhist_footer', hist)
    # the cursor down to row 1 (the 1994 season)
    check(ldir, tmp_path, 'c60_teamhist_row1', hist + [DOWN])
    # ENTER on row 1 opens that season's STANDINGS (cat 1 of 3 seasons)
    st, _data = py_run(ldir, tmp_path, hist + [DOWN, ENTER])
    assert st == (dynview.SCREEN_STANDINGS, 0, 1)
    check(ldir, tmp_path, 'c60_teamhist_enter_standings', hist + [DOWN, ENTER])
    # ESC returns to the TEAM HISTORY frame, the cursor still on row 1
    st, _data = py_run(ldir, tmp_path, hist + [DOWN, ENTER, ESC])
    assert st == (dynview.SCREEN_TEAMHIST, 0, 2, 1)
    check(ldir, tmp_path, 'c60_teamhist_esc', hist + [DOWN, ENTER, ESC])
    # RIGHT from CLEVELAND is DETROIT (no played season): the message row; ENTER
    # on it changes nothing
    msg = hist + [RIGHT]
    st, _data = py_run(ldir, tmp_path, msg)
    assert st == (dynview.SCREEN_TEAMHIST, 0, 3)
    assert dynview.team_history_rows(_data['hist'], _data['box'], 3) == \
        [('NO SEASONS RECORDED',)]
    check(ldir, tmp_path, 'c60_teamhist_message', msg + [ENTER])
