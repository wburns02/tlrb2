#!/usr/bin/env python3
"""Tests for C15.5, C15.6 and C15.8 (tools/m4/dynview.py, dynview.c, rig/bat_patch.py):
the ABOUT the mods rows (C15.6), the BAT :start line (C15.5) and no row highlight on a
cursor screen's single message row (C15.8).
Run:  python3 -m pytest -q tools/m4/test_c15_display.py
Host parity: dynview_host is built at import via build_dynview.py (as test_dynview_c.py
does) and the framebuffers are compared over synthetic fonts (MAIN.FNT and
BOLD.FNT in tmp_path), so nothing needs /mnt/nvme.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(HERE, 'rig'))

import dynview
import pytest
import bat_patch
from test_dynview_c import (_build, check_parity, fb_python, run_host, twin_league,
                            FILES, FB_SIZE)
from test_dynview_c13 import (make_fonts, player, line, tot)
from test_dynview_c import make_data
from test_dynview_c13_c import league as c13_league

ABOUT, HOF, LEAD, SA = (dynview.SCREEN_ABOUT, dynview.SCREEN_HOF,
                        dynview.SCREEN_LEADERS, dynview.SCREEN_AWARDS)
SEASON = dynview.MODE_SHIFT
C_TITLE_RED = dynview.C_TITLE_RED

NEW_ROWS = [
    'NUMBER OF TEAMS',
    'UTILITIES > SETUP LEAGUES: NEW TEAM, THEN',
    'CLICK IT AND AN EMPTY DIVISION ROW.',
    'CLICK A PLACED TEAM TO REMOVE IT. NEW',
    'TEAMS DRAFT FROM AI TEAMS, WHICH KEEP 15',
    'EACH, THEN SIGN FREE AGENTS. PLAYERS OF',
    'A REMOVED TEAM BECOME FREE AGENTS. START',
    'THE SEASON WITH A SCHEDULE THAT FITS,',
    'ELSE GENERATED.',
    '',
]

_build()


# ---------------------------------------------------------------- C15.6 ABOUT rows
def test_about_new_rows_python_order_and_overflow():
    rows = dynview.ABOUT_ROWS
    assert len(rows) == 57
    i = rows.index('START YEAR: DYNASTY SETTINGS, LEFT RIGHT.')
    assert rows[i + 1] == ''
    assert rows[i + 2:i + 12] == NEW_ROWS
    assert rows[i + 12] == 'NEW FACES'
    for t in rows:
        assert len(t) <= 42, t


def test_about_pages_host_python_parity(tmp_path):
    """Every ABOUT page: host == Python (a league with history, and an empty one)."""
    fonts = make_fonts(tmp_path / 'fonts')
    (tmp_path / 'hist').mkdir()
    ldir, _ = make_data(tmp_path / 'hist')
    empty = tmp_path / 'empty'
    empty.mkdir()
    pages = (len(dynview.ABOUT_ROWS) + dynview.ROWS_PER_PAGE - 1) // dynview.ROWS_PER_PAGE
    for n, keys in enumerate([[56] + [dynview.KEY_PGDN] * k for k in range(pages + 1)]):
        check_parity(ldir, tmp_path, 'c15_about_h%d' % n, keys=keys, font_dir=fonts)
        check_parity(empty, tmp_path, 'c15_about_e%d' % n, keys=keys, font_dir=fonts)


# ---------------------------------------------------------------- C15.8 message rows
def body_band(fb):
    return [fb[y * 320 + x] for y in range(35, 45) for x in range(8, 312)]


def synth_fb(ldir, tmp_path, tag, keys, fonts):
    """host and Python frames of the key sequence with synthetic fonts: equal, host's"""
    h, p = twin_league(ldir, tmp_path, tag + '_lg')
    raw = str(tmp_path / (tag + '.RAW'))
    a = run_host(h, raw, keys=keys, font_dir=fonts)
    b = fb_python(p, keys=keys, font_dir=fonts)
    assert len(a) == FB_SIZE and len(b) == FB_SIZE, tag + ': frame is not 64000 B'
    assert a == b, tag + ': host and Python frames differ'
    return a


def test_leaders_message_row_no_highlight(tmp_path):
    """LEADERS SEASON with no SEASLINE.DAT (the NO SEASON LINES message row): no
    C_TITLE_RED in the body band, host == Python."""
    fonts = make_fonts(tmp_path / 'fonts')
    ldir = c13_league(tmp_path, name='nl_seas')
    fb = synth_fb(ldir, tmp_path, 'c15_msg', [ord('3'), dynview.KEY_TAB], fonts)
    assert C_TITLE_RED not in body_band(fb)


def test_leaders_list_row0_highlights(tmp_path):
    """A season list with real rows still highlights row 0 (C_TITLE_RED), host == Python."""
    fonts = make_fonts(tmp_path / 'fonts')
    recs = [line(0, 1, totals=tot(G=1, AB=3, H=2, HR=1, RBI=1, R=1), war10=10)]
    ldir = c13_league(tmp_path, name='lead_seas', lines=recs)
    fb = synth_fb(ldir, tmp_path, 'c15_list', [ord('3'), dynview.KEY_TAB], fonts)
    assert fb[36 * 320 + 9] == C_TITLE_RED


def test_nohist_message_rows_no_highlight(tmp_path):
    """HALL OF FAME and SEASON AWARDS on a league with no history (NO DYNASTY HISTORY
    YET): no C_TITLE_RED in the body band, host == Python; a HOF list with real rows
    still highlights row 0."""
    fonts = make_fonts(tmp_path / 'fonts')
    nohist = tmp_path / 'nohist'
    nohist.mkdir()
    empty = tmp_path / 'empty'
    empty.mkdir()
    data = dynview.load_data(str(empty), fonts)
    for state, tag in (((HOF, 0, 0), 'c15_nohist_hof'), ((SA, 0, 0), 'c15_nohist_awards')):
        b = bytes(dynview.render(state, data))
        assert C_TITLE_RED not in body_band(b), tag
        h, p = twin_league(nohist, tmp_path, tag)
        keys = [[48 + state[0]]]
        a = run_host(h, str(tmp_path / (tag + '.RAW')), keys=keys[0], font_dir=fonts)
        c = fb_python(p, keys=keys[0], font_dir=fonts)
        assert a == c, tag
    # a HOF list with real rows: row 0 is highlighted, host == Python
    ldir = c13_league(tmp_path, name='hof2',
                      players=[player('HALL', status=3, hof=2)])
    fb = synth_fb(ldir, tmp_path, 'c15_hof_list', [ord('2')], fonts)
    assert fb[36 * 320 + 9] == C_TITLE_RED


# ---------------------------------------------------------------- C15.5 bat_patch
class TestBatPatchC15:
    def test_patched_start_text(self):
        """The patched :start block: rosters /expand first, then the C16.4 form."""
        body = bat_patch.PATCHED_START.replace('\r\n', '\n')
        assert body == (':start\nrosters /expand\nhistwr /snap\ndynasty\n'
                        'if errorlevel 1 goto rolled\ngoto ctl\n:rolled\nhistwr /archive\nhistwr\n'
                        'rosters\ndynview /offseason\n:ctl\ncontrol\n')

    def test_every_earlier_form_upgrades_and_reverts(self):
        """Each EARLIER_FORMS entry (and the previous PATCHED_START, the newest entry)
        upgrades to the new form in place; --revert of every form restores STOCK_START."""
        assert bat_patch.EARLIER_FORMS[0] == (
            ':start\r\nhistwr /snap\r\ndynasty\r\n'
            'if errorlevel 1 goto rolled\r\ngoto ctl\r\n:rolled\r\nhistwr /archive\r\nhistwr\r\n'
            'rosters\r\ndynview /offseason\r\n:ctl\r\ncontrol\r\n')
        for old in (bat_patch.PATCHED_START,) + bat_patch.EARLIER_FORMS:
            with tempfile.TemporaryDirectory() as tmpdir:
                install = os.path.join(tmpdir, 'TONY2')
                os.mkdir(install)
                bat = os.path.join(install, 'TONY2.BAT')
                src = 'REM START MAIN LOOP\r\n' + old + 'goto x\r\n'
                with open(bat, 'wb') as f:
                    f.write(src.encode('cp437'))
                assert bat_patch.patch(install, revert=False)
                assert open(bat, 'rb').read().decode('cp437') == (
                    'REM START MAIN LOOP\r\n' + bat_patch.PATCHED_START + 'goto x\r\n')
                assert bat_patch.patch(install, revert=False)     # idempotent
                assert open(bat, 'rb').read().decode('cp437') == (
                    'REM START MAIN LOOP\r\n' + bat_patch.PATCHED_START + 'goto x\r\n')
                assert bat_patch.patch(install, revert=True)
                assert open(bat, 'rb').read().decode('cp437') == (
                    'REM START MAIN LOOP\r\n' + bat_patch.STOCK_START + 'goto x\r\n')

    def test_patch_twice_noop_and_revert(self):
        """Patching twice is a no-op on a stock BAT; --revert from the new form gives
        the stock BAT."""
        with tempfile.TemporaryDirectory() as tmpdir:
            install = os.path.join(tmpdir, 'TONY2')
            os.mkdir(install)
            bat = os.path.join(install, 'TONY2.BAT')
            stock = 'REM START MAIN LOOP\r\n:start\r\ncontrol\r\n'
            with open(bat, 'wb') as f:
                f.write(stock.encode('cp437'))
            assert bat_patch.patch(install, revert=False)
            content = open(bat, 'rb').read()
            assert bat_patch.PATCHED_START.encode('cp437') in content
            assert bat_patch.patch(install, revert=False)
            assert open(bat, 'rb').read() == content
            assert bat_patch.patch(install, revert=True)
            assert open(bat, 'rb').read().decode('cp437') == stock
