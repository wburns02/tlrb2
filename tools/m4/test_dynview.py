#!/usr/bin/env python3
"""Tests for the DYNVIEW reference renderer (tools/m4/dynview.py).
Run:  python3 -m pytest -q tools/m4/test_dynview.py
Synthetic HISTORY.DAT/MILESTON.DAT are built in tmp_path from raw bytes; rendering
tests need the game fonts under /mnt/nvme/tlrb2/files and skip when it is missing.
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dynview
import history

FILES = '/mnt/nvme/tlrb2/files'

SEASON_NO, CHAMP_ID, RUNNER_ID = 0, 2, 3
CHAMP_STEM, RUNNER_STEM, AW_OFF = 4, 12, 88
# TOTALS indexes
G, AB, H, D2, T3, HR, R, RBI, BB, SO, SB, CS, E, W, L, SV, GS, CG, SHO, OUTS, ER, \
    PH, PBB, PSO, PHR = range(25)


def mk_history(tmp_path, seasons, entries, awards=None):
    """Raw HISTORY.DAT bytes: 32 B header, seasons x 128 B, entries x 160 B."""
    d = bytearray(32)
    d[3] = 1
    d[4], d[5] = seasons & 255, (seasons >> 8) & 255
    d[6], d[7] = len(entries) & 255, (len(entries) >> 8) & 255
    for n, se in enumerate(seasons if isinstance(seasons, list) else [], 1):
        pass
    return bytes(d)


def write_season(d, season_no, champ_stem, runner_stem, awards=(0xffff,) * 6):
    o = 32 + (season_no - 1) * 128
    struct.pack_into('<H', d, o, season_no)
    d[o + 4:o + 12] = champ_stem.ljust(8, b'\0')[:8]
    d[o + 12:o + 20] = runner_stem.ljust(8, b'\0')[:8]
    for k, v in enumerate(awards):
        struct.pack_into('<H', d, o + AW_OFF + 2 * k, v)


def write_player(d, i, last, first, status=1, first_season=1, last_season=10,
                 seasons_played=10, pitcher=0, hof_season=0, war10=0,
                 totals=None, awards=(0, 0, 0, 0, 0)):
    o = 8224 + i * 160
    name = last.ljust(12, b'\0')[:12] + first.ljust(8, b'\0')[:8]
    d[o:o + 20] = name
    d[o + 22] = status
    struct.pack_into('<H', d, o + 24, first_season)
    struct.pack_into('<H', d, o + 26, last_season)
    struct.pack_into('<H', d, o + 28, seasons_played)
    d[o + 31] = pitcher
    t = totals or [0] * 25
    for k, v in enumerate(t):
        struct.pack_into('<I', d, o + 32 + 4 * k, v)
    struct.pack_into('<h', d, o + 132, war10)
    struct.pack_into('<H', d, o + 150, hof_season)
    d[o + 152:o + 157] = bytes(awards)


def write_mileston(path, records):
    """records = [(season, idx, kind, value)] in file order."""
    d = bytearray()
    for season, idx, kind, value in records:
        d += struct.pack('<HHBBH', season, idx, kind, 0, value)
    open(path, 'wb').write(bytes(d))


def make_data(tmp_path, seasons=3, ms=None):
    """Synthetic league dir with HISTORY.DAT (3 seasons, 30 entries incl. 2 HoF,
    awards set) and MILESTON.DAT (5 records). Returns (dir, hist bytes)."""
    ldir = tmp_path / 'league'
    ldir.mkdir()
    d = bytearray(32 + 64 * 128 + 30 * 160)
    d[3] = 1
    d[4], d[5] = seasons & 255, (seasons >> 8) & 255
    d[6], d[7] = 30 & 255, 0
    # seasons 1..3, newest data has champion stems ALA02/ALA03, runners NL01
    write_season(d, 1, b'ALA01', b'NL01', awards=(0, 1, 2, 3, 4, 5))
    write_season(d, 2, b'ALA02', b'NL02', awards=(6, 7, 8, 9, 10, 11))
    write_season(d, 3, b'ALA03', b'NL03', awards=(12, 13, 14, 15, 16, 17))
    # 30 entries: 0..27 role players, 28/29 HoF (hof seasons 2 and 3)
    for i in range(30):
        last = b'PLAYER%02d' % i
        status = 3 if i >= 28 else (2 if i % 3 == 0 else 1)
        write_player(d, i, last, b'B', status=status,
                     first_season=1, last_season=10, seasons_played=10,
                     pitcher=1 if i == 5 else 0,
                     hof_season=(2 if i == 28 else (3 if i == 29 else 0)),
                     war10=100 + i,
                     totals=[10 + i] * 11 + [0, 0, 0] + [20 + i] * 3
                     + [100 + i, 0, 0, 0, 5000 + i, 150 + i],
                     awards=(1, 0, 0, 2, 0))
    # make entry 0 a 3000-H batter with .318 AVG over 9423 AB, entry 5 an ERA pitcher
    t0 = [0] * 25
    t0[G], t0[AB], t0[H], t0[HR], t0[OUTS], t0[ER] = 3000 // 3, 9423, 3000, 400, 5400, 150
    write_player(d, 0, b'HITTER', b'A', status=2, totals=t0, war10=650)
    t5 = [0] * 25
    t5[G], t5[W], t5[SV], t5[OUTS], t5[ER], t5[PSO] = 400, 250, 0, 5400, 99, 3000
    write_player(d, 5, b'ACE', b'P', status=2, pitcher=1, totals=t5, war10=500)
    # awards point at real entries: season 3 AL MVP 0, NL MVP 1
    for n, aw in ((1, (0, 1, 2, 3, 4, 5)), (2, (6, 7, 8, 9, 10, 11)),
                  (3, (0, 1, 2, 3, 4, 5))):
        write_season(d, n, b'ALA0%d' % n, b'NL0%d' % n, awards=aw)
    (ldir / 'HISTORY.DAT').write_bytes(bytes(d))
    if ms is None:
        ms = [(3, 0, 2, 3000), (3, 5, 13, 3000), (2, 1, 32, 52),
              (2, 2, 35, 412), (1, 0, 5, 500)]
    write_mileston(str(ldir / 'MILESTON.DAT'), ms)
    return ldir, bytes(d)


def st(screen, page=0, cat=0):
    return (screen, page, cat)


# ---------------------------------------------------------------- model rows
def test_history_rows_newest_first(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_HISTORY), data)
    assert rows[0][0] == '3' and rows[1][0] == '2' and rows[2][0] == '1'
    assert rows[0][1] == 'ALA03' and rows[0][2] == 'NL03'
    # award names (PLAYER00.., cut to 12 chars)
    assert rows[0][3] == 'HITTER, A'[:12]


def test_hof_rows_order(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_HOF), data)
    # HoF entries 28 (season 2) and 29 (season 3): newer HoF season first
    assert rows[0][1] == '3' and rows[1][1] == '2'
    assert rows[0][0].startswith('PLAYER29')
    # pitcher columns for entry 5 are not in the HOF table (status 2)


def test_leaders_count_order_and_ties(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # H: only entries with H > 0 (entry 0 has H 3000, the rest H = 10+i)
    rows = dynview.rows(st(dynview.SCREEN_LEADERS, 0, 0), data)
    assert rows[0] == ('#1', 'HITTER, A', 'R', '10', '3000')
    assert rows[1][1].startswith('PLAYER')        # rest by totals
    # WAR descending: WAR10 600 (entry 0) > 500 (entry 5) > 100+i
    rows = dynview.rows(st(dynview.SCREEN_LEADERS, 0, 5), data)
    assert rows[0][1] == 'HITTER, A' and rows[0][4] == '65.0'
    assert rows[1][1] == 'ACE, P' and rows[1][4] == '50.0'
    assert rows[2][1].startswith('PLAYER29') and rows[2][4] == '12.9'


def test_leaders_avg_threshold_and_format(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # AVG: only AB >= 3000 qualifies (entry 0: 3000/9423 = .318)
    rows = dynview.rows(st(dynview.SCREEN_LEADERS, 0, 4), data)
    assert rows[0] == ('#1', 'HITTER, A', 'R', '10', '.318')
    assert len(rows) == 1
    # ERA: only OUTS >= 4500 (entries 0 and 5). entry 5: 99*2700/5400 = 49 -> 0.49,
    # entry 0: 150*2700/5400 = 75 -> 0.75, ascending
    rows = dynview.rows(st(dynview.SCREEN_LEADERS, 0, 9), data)
    assert rows[0] == ('#1', 'ACE, P', 'R', '10', '0.49')
    assert rows[1] == ('#2', 'HITTER, A', 'R', '10', '0.75')
    assert len(rows) == 2


def test_leaders_award_categories_wrap(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # MVP awards: entries 0..29 have awards[0] = 1, so all 30 qualify, top 12
    rows = dynview.rows(st(dynview.SCREEN_LEADERS, 0, 10), data)
    assert len(rows) == 12
    # LEFT from cat 0 wraps to cat 11; RIGHT from 11 wraps to 0
    s1, _ex = dynview.step(st(dynview.SCREEN_LEADERS, 0, 0),
                           dynview.KEY_LEFT, data)
    assert s1[2] == 11 and s1[1] == 0
    s2, _ex = dynview.step(s1, dynview.KEY_RIGHT, data)
    assert s2[2] == 0
    rows = dynview.rows(s1, data)
    assert len(rows) == 12


def test_milestone_rows_order_and_events(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_MILESTONES), data)
    # newest season first (3 before 2 before 1), file order within a season
    assert rows[0][0] == '3' and rows[1][0] == '3'
    assert rows[0][2] == '3000 HITS' and rows[0][1].startswith('HITTER')
    assert rows[1][2] == '2000 STRIKEOUTS'
    assert rows[2][0] == '2' and rows[2][2] == '52 HR SEASON'
    assert rows[3][2] == '.412 SEASON'
    assert rows[4][0] == '1' and rows[4][2] == '500 HOME RUNS'


def test_review_rows(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    rows = dynview.rows(st(dynview.SCREEN_REVIEW, 0, 3), data)
    text = [r[0] for r in rows]
    assert text[0] == 'CHAMPION ALA03' and text[1] == 'RUNNER-UP NL03'
    assert text[2].startswith('AL MVP HITTER')
    assert any(t.startswith('NEW HALL OF FAME: PLAYER29') for t in text)
    # season-3 milestones appended as "<name> <event>"
    assert any(t == 'HITTER, A 3000 HITS' for t in text)
    assert any(t == 'ACE, P 2000 STRIKEOUTS' for t in text)


def test_paging_bounds(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # HISTORY has 3 rows: PGDN from page 0 is a no-op (3 < 12 rows shown means
    # page*12+12 > 3), PGUP stays at 0
    s, _ex = dynview.step(st(dynview.SCREEN_HISTORY), dynview.KEY_PGDN, data)
    assert s[1] == 0
    s, _ex = dynview.step(s, dynview.KEY_PGUP, data)
    assert s[1] == 0
    # LEADERS MVP awards: 28 entries qualify (awards[0] = 1), PGDN -> page 1
    # (rank restarts per page rank #13 here), PGUP back, PGDN at the last page
    # (24 < 28) stays, a PGDN from page 2 is a no-op
    s, _ex = dynview.step(st(dynview.SCREEN_LEADERS, 0, 10), dynview.KEY_PGDN, data)
    assert s[1] == 1
    rows = dynview.rows(s, data)
    assert rows[0][0] == '#13'
    s, _ex = dynview.step(s, dynview.KEY_PGUP, data)
    assert s[1] == 0
    s, _ex = dynview.step(st(dynview.SCREEN_LEADERS, 0, 10), dynview.KEY_PGDN, data)
    s, _ex = dynview.step(s, dynview.KEY_PGDN, data)
    assert s[1] == 2
    s, _ex = dynview.step(s, dynview.KEY_PGDN, data)
    assert s[1] == 2


def test_esc_and_enter_navigation(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    # ESC from MENU exits
    s, ex = dynview.step(st(dynview.SCREEN_MENU), dynview.KEY_ESC, data)
    assert ex == 1
    # ESC from HISTORY goes to MENU
    s, ex = dynview.step(st(dynview.SCREEN_HISTORY), dynview.KEY_ESC, data)
    assert ex == 0 and s[0] == dynview.SCREEN_MENU
    # 1..5 open the screens; ENTER on REVIEW returns to MENU
    s, ex = dynview.step(st(dynview.SCREEN_MENU), ord('5'), data)
    assert s[0] == dynview.SCREEN_REVIEW and ex == 0
    s, ex = dynview.step(s, dynview.KEY_ENTER, data)
    assert ex == 0 and s[0] == dynview.SCREEN_MENU


# ---------------------------------------------------------------- formatting
def test_format_avg():
    assert dynview.fmt_avg(300) == '.300'
    assert dynview.fmt_avg(1000) == '1.000'
    assert dynview.fmt_avg(0) == '.000'
    assert dynview.fmt_avg(41) == '.041'


def test_format_era_war():
    assert dynview.fmt_era100(185) == '1.85'
    assert dynview.fmt_era100(49) == '0.49'
    assert dynview.fmt_war10(-5) == '-0.5'
    assert dynview.fmt_war10(123) == '12.3'
    assert dynview.fmt_war10(0) == '0.0'


def test_name_cut_rules():
    n20 = b'SMITH'.ljust(12, b'\0') + b'JOHN'.ljust(8, b'\0')
    assert dynview.name_display(n20) == 'SMITH, JOHN'
    # long names cut to 18
    n = b'MCCORMACKSTE'.ljust(12, b'\0') + b'ALEXANDER'.ljust(8, b'\0')
    out = dynview.name_display(n)
    assert out == 'MCCORMACKSTE, ALEX' and len(out) == 18
    # empty first part: just the last name
    n2 = b'JONES'.ljust(12, b'\0') + bytes(8)
    assert dynview.name_display(n2) == 'JONES'
    # trailing spaces in the field are stripped
    n3 = b'MAY  '.ljust(12, b'\0') + b'E  '.ljust(8, b'\0')
    assert dynview.name_display(n3) == 'MAY, E'


def test_stem_display():
    assert dynview.stem_display(b'phila') == 'PHILA'
    assert dynview.stem_display(b'\0' * 8) == '?'


def test_event_text():
    assert dynview.event_text(2, 3260) == '3000 HITS'
    assert dynview.event_text(5, 501) == '500 HOME RUNS'
    assert dynview.event_text(32, 52) == '52 HR SEASON'
    assert dynview.event_text(35, 412) == '.412 SEASON'
    assert dynview.event_text(38, 185) == '1.85 ERA SEASON'
    assert dynview.event_text(39, 51) == '51 SAVE SEASON'


# ---------------------------------------------------------------- rendering
def test_render_framebuffer_and_title_colors(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir), FILES)
    fb = dynview.render(st(dynview.SCREEN_MENU), data)
    assert len(fb) == 64000
    # title bar rows 8..20 contain only title red, white and black pixels
    bad = set()
    for y in range(8, 21):
        for x in range(8, 312):
            v = fb[y * 320 + x]
            if v not in (dynview.C_TITLE_RED, dynview.C_WHITE, dynview.C_BLACK):
                bad.add(v)
    assert not bad, sorted(bad)
    # rows 21..23 are inside the frame panel (193), rows 2..3 outside it (215)
    for y in range(21, 24):
        for x in range(8, 312):
            assert fb[y * 320 + x] == dynview.C_FRAME_TAN
    for y in range(2, 4):
        for x in range(8, 312):
            assert fb[y * 320 + x] == dynview.C_BG_BROWN


def test_render_determinism_and_steps(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir), FILES)
    seq = [dynview.KEY_PGDN, ord('3'), dynview.KEY_RIGHT, dynview.KEY_PGDN,
           dynview.KEY_PGUP, dynview.KEY_LEFT, dynview.KEY_ESC, ord('4'),
           dynview.KEY_PGDN, ord('5'), dynview.KEY_ENTER, ord('2')]
    s = st(dynview.SCREEN_MENU)
    for k in seq:
        s, _ex = dynview.step(s, k, data)
        fb1 = dynview.render(s, data)
        fb2 = dynview.render(s, data)
        assert fb1 == fb2
        assert len(fb1) == 64000


def test_render_clipping(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    # fill first so as to tell in-bounds writes from stray default state: a fill of
    # index 0 is the state itself, so use a nonzero fill before the off-screen cases
    fill = bytearray(b'\x01' * 64000)
    main_ft = dynview.load_fonts(FILES)[0]
    # off-screen right and bottom: nothing written, no exception
    dynview.draw_text(fill, main_ft, 320, 100, 'A', 15)
    dynview.draw_text(fill, main_ft, 10, 200, 'A', 15)
    dynview.draw_text(fill, main_ft, 10, -5, 'A', 15)
    # in-bounds writes land only on rows/columns inside the screen
    dynview.draw_text(fill, main_ft, 10, 193, 'A', 15)
    got = [(i % 320, i // 320) for i, v in enumerate(fill) if v == 15]
    assert 0 < len(got) <= 7 * 4
    for x, y in got:
        assert 0 <= x < 320 and 0 <= y < 200
    # fully off right (x 320, every pixel past 319): nothing written
    fb = bytearray(b'\x01' * 64000)
    dynview.draw_text(fb, main_ft, 320, 10, 'A', 15)
    assert all(v == 1 for v in fb)
    # partially clipped glyph draws only its in-bounds pixels (x 313 is within 320
    # but the glyph spills past: only columns 0..319 land)
    fb = bytearray(b'\x01' * 64000)
    dynview.draw_text(fb, main_ft, 313, 10, 'I', 15)
    got = [(i % 320, i // 320) for i, v in enumerate(fb) if v == 15]
    assert 0 < len(got) and all(x < 320 for x, y in got)
    # last in-bounds start column where nothing is written depends on the glyph
    # width: x 320 at least guarantees every pixel is past 319
    fb = bytearray(b'\x01' * 64000)
    dynview.draw_text(fb, main_ft, 320, 10, 'I', 15)
    assert all(v == 1 for v in fb)
    # partially clipped glyph draws only its in-bounds pixels (x 313 + the 5 px
    # A spills past 319: only columns 0..319 land)
    fb = bytearray(b'\x01' * 64000)
    dynview.draw_text(fb, main_ft, 313, 10, 'A', 15)
    got = [(i % 320, i // 320) for i, v in enumerate(fb) if v == 15]
    assert 0 < len(got) and all(x < 320 for x, y in got)


# ---------------------------------------------------------------- empty / missing
def test_no_history_every_screen(tmp_path):
    ldir = tmp_path / 'empty'
    ldir.mkdir()
    data = dynview.load_data(str(ldir))
    for screen in (dynview.SCREEN_HISTORY, dynview.SCREEN_HOF,
                   dynview.SCREEN_LEADERS, dynview.SCREEN_MILESTONES,
                   dynview.SCREEN_REVIEW):
        s = st(screen, 0, 1 if screen == dynview.SCREEN_REVIEW else 0)
        assert dynview.rows(s, data) == [('NO DYNASTY HISTORY YET',)]
    # zero-seasons file behaves the same
    p = ldir / 'HISTORY.DAT'
    p.write_bytes(bytes(32))
    data = dynview.load_data(str(ldir))
    assert dynview.rows(st(dynview.SCREEN_HISTORY), data) == \
        [('NO DYNASTY HISTORY YET',)]


# ---------------------------------------------------------------- previews
PREVIEWS = [st(dynview.SCREEN_MENU, 0, 0),
            st(dynview.SCREEN_HISTORY, 0, 0),
            st(dynview.SCREEN_HOF, 0, 0),
            st(dynview.SCREEN_LEADERS, 0, 0),
            st(dynview.SCREEN_LEADERS, 0, 4),
            st(dynview.SCREEN_LEADERS, 0, 9),
            st(dynview.SCREEN_MILESTONES, 0, 0),
            st(dynview.SCREEN_REVIEW, 0, 3)]


def test_preview_pngs(tmp_path):
    if not os.path.exists(os.path.join(FILES, 'MAIN.FNT')):
        import pytest
        pytest.skip('/mnt/nvme/tlrb2/files missing')
    out = '/mnt/nvme/tlrb2/t5'
    os.makedirs(out, exist_ok=True)
    real = os.path.join(out, 'real', 'HISTORY.DAT')
    pal = dynview.load_palette(os.path.join(FILES, 'DEFAULT.PAL'))
    # synthetic previews
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir), FILES)
    for n, s in enumerate(PREVIEWS):
        fb = dynview.render(s, data)
        dynview.write_png(os.path.join(out, 'syn_%02d.png' % n), fb, pal)
    # real previews when a recorded HISTORY.DAT exists
    if not (os.path.exists(real)
            and history.History.load(real).seasons_recorded > 0):
        print('real preview skipped: no recorded HISTORY.DAT under', out)
        return
    data = dynview.load_data(os.path.join(out, 'real'), FILES)
    for n, s in enumerate(PREVIEWS):
        fb = dynview.render(s, data)
        dynview.write_png(os.path.join(out, 'real_%02d.png' % n), fb, pal)


def test_column_layout_fits_and_never_overlaps():
    """Every MAIN.FNT glyph advances CHAR_W: columns stay inside x 10..304 and
    never share a pixel column, and every row builder's cells fit their width."""
    assert dynview.CHAR_W == 7
    for cols in (dynview.COLS_SINGLE, dynview.COLS_HISTORY, dynview.COLS_HOF,
                 dynview.COLS_LEADERS, dynview.COLS_MILESTONES):
        prev_end = 0
        for header, x, w, _a in cols:
            assert len(header) <= w
            assert x >= 10 and x >= prev_end
            prev_end = x + w * dynview.CHAR_W
        assert prev_end <= 10 + 42 * dynview.CHAR_W


def test_cells_fit_columns(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    screens = {dynview.SCREEN_HISTORY: dynview.COLS_HISTORY,
               dynview.SCREEN_HOF: dynview.COLS_HOF,
               dynview.SCREEN_MILESTONES: dynview.COLS_MILESTONES,
               dynview.SCREEN_REVIEW: dynview.COLS_SINGLE}
    for scr, cols in screens.items():
        for row in dynview.rows(st(scr), data):
            for cell, (_h, _x, w, _a) in zip(row, cols):
                assert len(cell) <= w, (scr, cell)
    for cat in range(dynview.N_CATS):
        for row in dynview.rows(st(dynview.SCREEN_LEADERS, 0, cat), data):
            for cell, (_h, _x, w, _a) in zip(row, dynview.COLS_LEADERS):
                assert len(cell) <= w, (cat, cell)


def test_review_title_from_menu_uses_last_season(tmp_path):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    s, _ex = dynview.step(st(dynview.SCREEN_MENU), ord('5'), data)
    assert dynview.screen_title(s, data) == 'SEASON 3 IN REVIEW'
    assert dynview.rows(s, data)[0] == ('CHAMPION ALA03',)


def test_name_cut_never_leaves_dangling_comma():
    n = b'PLAYER03'.ljust(12, b'\0') + b'B'.ljust(8, b'\0')
    assert dynview.name_display(n, 9) == 'PLAYER03'
    assert dynview.name_display(n, 10) == 'PLAYER03'
    assert dynview.name_display(n, 11) == 'PLAYER03, B'
    long = b'MCCORMACKSTE'.ljust(12, b'\0') + b'AL'.ljust(8, b'\0')
    assert dynview.name_display(long, 9) == 'MCCORMACK'


def test_list_max_caps_rows_and_paging(tmp_path, monkeypatch):
    ldir, _ = make_data(tmp_path)
    data = dynview.load_data(str(ldir))
    monkeypatch.setattr(dynview, 'LIST_MAX', 14)
    # MVP leaders: 28 qualify, capped to 14 -> pages 0 and 1 only, page 1 has 2 rows
    assert dynview.leaders_count(data['hist'], 10) == 14
    s, _ex = dynview.step(st(dynview.SCREEN_LEADERS, 0, 10), dynview.KEY_PGDN, data)
    assert s[1] == 1 and len(dynview.rows(s, data)) == 2
    s, _ex = dynview.step(s, dynview.KEY_PGDN, data)
    assert s[1] == 1
    monkeypatch.setattr(dynview, 'LIST_MAX', 3)
    assert len(dynview.milestone_rows(data['hist'], data['ms'])) == 3
    assert dynview.milestone_rows(data['hist'], data['ms'])[0][0] == '3'


def test_no_history_row_uses_single_column(tmp_path):
    ldir = tmp_path / 'empty'
    ldir.mkdir()
    data = dynview.load_data(str(ldir))
    for screen in range(6):
        cols = dynview.body_cols(st(screen), data)
        assert cols == dynview.COLS_SINGLE
        assert len(dynview.rows(st(screen), data)[0][0]) <= cols[0][2]


def test_unknown_chars_draw_question_mark():
    font = [(1, 1, 7, bytes([0x80]), 1)] * 95
    font = list(font)
    font[31] = (1, 1, 7, bytes([0x80]), 1)
    marker = (2, 1, 7, bytes([0x80, 0x80]), 1)
    font[31] = marker
    assert dynview.glyph_of(font, '\x01') is marker
    assert dynview.glyph_of(font, '\xe9') is marker
    assert dynview.glyph_of(font, '?') is marker
    assert dynview.glyph_of(font, '/') is not marker
