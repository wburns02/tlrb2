#!/usr/bin/env python3
"""Unit tests for rig components (bat_patch, screens, check_roll)."""
import os
import sys
import tempfile
import shutil
import pytest
from pathlib import Path
from PIL import Image
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import bat_patch
import screens
import check_roll
import season_sim
import dynasty_gate


class TestBatPatch:
    """Test bat_patch idempotency and revert."""

    def test_patch_idempotent(self):
        """Patching twice should be idempotent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            install = Path(tmpdir) / 'TONY2'
            install.mkdir()

            # Create synthetic BAT with stock content
            bat = install / 'TONY2.BAT'
            bat.write_bytes(
                'REM START MAIN LOOP\r\n:start\r\ncontrol\r\n'.encode('cp437')
            )

            # First patch
            assert bat_patch.patch(str(install), revert=False)
            content1 = bat.read_text(encoding='cp437')
            assert 'dynasty' in content1

            # Second patch (idempotent)
            assert bat_patch.patch(str(install), revert=False)
            content2 = bat.read_text(encoding='cp437')
            assert content1 == content2

    def test_patch_revert(self):
        """Reverting should restore stock content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            install = Path(tmpdir) / 'TONY2'
            install.mkdir()

            bat = install / 'TONY2.BAT'
            stock = 'REM START MAIN LOOP\r\n:start\r\ncontrol\r\n'
            bat.write_bytes(stock.encode('cp437'))

            # Patch then revert
            assert bat_patch.patch(str(install), revert=False)
            assert bat_patch.patch(str(install), revert=True)
            assert bat.read_bytes().decode('cp437') == stock

    def test_patch_upgrades_old_form(self):
        """The previous patched form (no histwr line) upgrades in place."""
        with tempfile.TemporaryDirectory() as tmpdir:
            install = Path(tmpdir) / 'TONY2'
            install.mkdir()
            bat = install / 'TONY2.BAT'
            old = ('REM START MAIN LOOP\r\n' + bat_patch.PATCHED_START_OLD)
            bat.write_bytes(old.encode('cp437'))
            assert bat_patch.patch(str(install), revert=False)
            content = bat.read_bytes().decode('cp437')
            assert content == 'REM START MAIN LOOP\r\n' + bat_patch.PATCHED_START
            assert 'histwr' in content
            # idempotent after the upgrade
            assert bat_patch.patch(str(install), revert=False)
            assert bat.read_bytes().decode('cp437') == content

    def test_c7_form_upgrades_every_earlier_form(self):
        """C7: rolled seasons run histwr, rosters and dynview /review; every
        earlier patched form upgrades in place and reverts to stock."""
        body = bat_patch.PATCHED_START.replace('\r\n', '\n')
        assert body == (':start\ncopy TEAMS\\CLASSIC\\*.* C:\\DYNSNAP > NUL\ndynasty\n'
                        'if errorlevel 1 goto rolled\ngoto ctl\n:rolled\nhistwr\nrosters\n'
                        'dynview /review\n:ctl\ncontrol\n')
        for old in bat_patch.EARLIER_FORMS:
            with tempfile.TemporaryDirectory() as tmpdir:
                install = Path(tmpdir) / 'TONY2'
                install.mkdir()
                bat = install / 'TONY2.BAT'
                bat.write_bytes(('echo off\r\n' + old + 'goto x\r\n').encode('cp437'))
                assert bat_patch.patch(str(install), revert=False)
                assert bat.read_bytes().decode('cp437') == (
                    'echo off\r\n' + bat_patch.PATCHED_START + 'goto x\r\n')
                assert bat_patch.patch(str(install), revert=True)
                assert bat.read_bytes().decode('cp437') == (
                    'echo off\r\n' + bat_patch.STOCK_START + 'goto x\r\n')

    def test_c7_labels_free_in_stock_bat(self):
        """The new labels do not collide with the shipped TONY2.BAT (DOS
        matches labels on 8 chars, case-insensitive)."""
        stock = Path('/mnt/nvme/tlrb2/pristine/TONY2/TONY2.BAT')
        if not stock.exists():
            pytest.skip('no pristine install')
        labels = [l.strip()[1:9].lower() for l in stock.read_bytes().decode('cp437').splitlines()
                  if l.strip().startswith(':')]
        assert 'rolled' not in labels and 'ctl' not in labels
        with tempfile.TemporaryDirectory() as tmpdir:
            install = Path(tmpdir) / 'TONY2'
            install.mkdir()
            (install / 'TONY2.BAT').write_bytes(stock.read_bytes())
            assert bat_patch.patch(str(install), revert=False)
            out = (install / 'TONY2.BAT').read_bytes().decode('cp437')
            got = [l.strip()[1:9].lower() for l in out.splitlines() if l.strip().startswith(':')]
            assert len(got) == len(set(got))
            assert bat_patch.patch(str(install), revert=True)
            assert (install / 'TONY2.BAT').read_bytes() == stock.read_bytes()

    def test_revert_from_old_form(self):
        """Reverting from the previous patched form restores stock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            install = Path(tmpdir) / 'TONY2'
            install.mkdir()
            bat = install / 'TONY2.BAT'
            stock = 'REM START MAIN LOOP\r\n:start\r\ncontrol\r\n'
            bat.write_bytes(('REM START MAIN LOOP\r\n'
                             + bat_patch.PATCHED_START_OLD).encode('cp437'))
            assert bat_patch.patch(str(install), revert=True)
            assert bat.read_bytes().decode('cp437') == stock

    def test_revert_from_new_form(self):
        """Reverting from the current patched form restores stock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            install = Path(tmpdir) / 'TONY2'
            install.mkdir()
            bat = install / 'TONY2.BAT'
            stock = 'REM START MAIN LOOP\r\n:start\r\ncontrol\r\n'
            bat.write_bytes(('REM START MAIN LOOP\r\n'
                             + bat_patch.PATCHED_START).encode('cp437'))
            assert bat_patch.patch(str(install), revert=True)
            assert bat.read_bytes().decode('cp437') == stock

    def test_patch_refuses_live_path(self):
        """Should refuse /mnt/nvme/tlrb2/c."""
        with tempfile.TemporaryDirectory() as tmpdir:
            install = '/mnt/nvme/tlrb2/c/TONY2'
            assert not bat_patch.patch(install, revert=False)


class TestScreens:
    """Test screen identification (requires refs, mock if not present)."""

    def test_pixel_diff_identical(self):
        """Identical images should have diff ~0."""
        img = Image.new('L', (100, 100), color=128)
        diff = screens.pixel_diff(img, img)
        assert diff < 1.0

    def test_pixel_diff_different(self):
        """Different images should have nonzero diff."""
        img1 = Image.new('L', (100, 100), color=50)
        img2 = Image.new('L', (100, 100), color=200)
        diff = screens.pixel_diff(img1, img2)
        assert diff > 100

    def test_pixel_diff_size_mismatch(self):
        """Size mismatch should give large diff."""
        img1 = Image.new('L', (100, 100), color=128)
        img2 = Image.new('L', (50, 50), color=128)
        diff = screens.pixel_diff(img1, img2)
        assert diff > 500



class TestDynviewScreen:
    def _panel(self):
        img = Image.new('RGB', (1024, 768), (0, 0, 0))
        for box, rgb, _ in screens.DYNVIEW_BARS:
            img.paste(rgb, box)
        return img

    def test_bars_match(self):
        assert screens.by_dynview(self._panel())

    def test_blank_and_half_panel_miss(self):
        assert not screens.by_dynview(Image.new('RGB', (1024, 768), (0, 0, 0)))
        img = self._panel()
        img.paste((207, 178, 154), screens.DYNVIEW_BARS[1][0])
        assert not screens.by_dynview(img)

    def test_no_game_screen_matches(self):
        shots = '/mnt/nvme/tlrb2/logs/t6/shots'
        if not os.path.isdir(shots):
            pytest.skip('no rig screenshots')
        names = [f for f in sorted(os.listdir(shots)) if f.endswith('.png') and 'dynview' not in f]
        hits = [f for f in names if screens.by_dynview(Image.open(os.path.join(shots, f)))]
        assert names and hits == []


class TestBatPatchPaths:
    def test_dynsnap_at_drive_root(self, tmp_path):
        install = tmp_path / 'c' / 'TONY2'
        install.mkdir(parents=True)
        (install / 'TONY2.BAT').write_bytes(b':start\r\ncontrol\r\n')
        assert bat_patch.patch(str(install))
        assert (tmp_path / 'c' / 'DYNSNAP').is_dir()
        assert not (install / 'DYNSNAP').exists()

    def test_refuses_shared_work_install(self):
        assert not bat_patch.patch('/mnt/nvme/tlrb2/work/c/TONY2')
        assert not bat_patch.patch('/mnt/nvme/tlrb2/pristine/TONY2')


class TestScreenWords:
    def _ws(self, *words):
        return [(w, w, 0, 0) for w in words]

    def test_dialog_wins_over_screen_under_it(self):
        assert screens.by_words(self._ws('PIAY', 'STANDARD', 'GAMES', 'JVIY')) == 'allstar_dialog'
        assert screens.by_words(self._ws('PIAY', 'STANDARD', 'GAMES')) == 'play_std'

    def test_ball_menu_needs_both_words(self):
        assert screens.by_words(self._ws('DRAPT', 'CREDITS', 'MANAGER')) == 'ball_menu'
        assert screens.by_words(self._ws('DRAPT')) is None


class TestDiskState:
    def _league(self, tmp_path, day, hist):
        lg = tmp_path / 'TONY2' / 'TEAMS' / 'CLASSIC'
        lg.mkdir(parents=True)
        maj = bytearray(0x300)
        maj[0x20a] = day
        (lg / 'CLASSIC.MAJ').write_bytes(bytes(maj))
        (lg / 'HISTORY.DAT').write_bytes(hist)
        return str(tmp_path / 'TONY2'), str(lg)

    def test_day_and_flag(self, tmp_path):
        inst, _ = self._league(tmp_path, 0xf3, b'\x01\x34\x12\x00')
        assert season_sim.day(inst) == 0xf3
        assert season_sim.hist0(inst) == 1

    def test_roll_seed_p1_file_uses_pre_word(self, tmp_path):
        pre, post = tmp_path / 'pre', tmp_path / 'post'
        pre.mkdir()
        post.mkdir()
        (pre / 'HISTORY.DAT').write_bytes(b'\x00\x34\x12\x00')
        (post / 'HISTORY.DAT').write_bytes(b'\x01\x99\x99\x00')
        assert dynasty_gate.roll_seed(str(pre), str(post)) == 0x1234

    def test_roll_seed_v1_file_uses_start_word(self, tmp_path):
        pre, post = tmp_path / 'pre', tmp_path / 'post'
        pre.mkdir()
        post.mkdir()
        (pre / 'HISTORY.DAT').write_bytes(bytes(32))
        h = bytearray(32)
        h[0], h[3], h[8], h[9] = 1, 1, 0x78, 0x56
        (post / 'HISTORY.DAT').write_bytes(bytes(h))
        assert dynasty_gate.roll_seed(str(pre), str(post)) == 0x5678


class TestHistoryCheck:
    """G1: history_check against a synthetic pre/post pair built without DOS."""

    _PRE = '/mnt/nvme/tlrb2/fixtures/t4/s1_pre'

    def _pair(self, tmp_path, old_ms=None):
        """pre (no HISTORY.DAT) rolled with the reference; pre/RETIRED.DAT from the
        roll's retirees; post = rolled with the DYNASTY header + the HISTWR chain."""
        import history as hist_mod
        from m4 import dynasty_ref
        if not os.path.isdir(self._PRE):
            pytest.skip('fixtures missing')
        pre = str(tmp_path / 'pre')
        shutil.copytree(self._PRE, pre)
        hp = os.path.join(pre, 'HISTORY.DAT')
        if os.path.exists(hp):
            os.remove(hp)
        rolled = str(tmp_path / 'rolled')
        res = dynasty_ref.roll_league(pre, rolled, seed=0x1234)
        write_retired(os.path.join(pre, 'RETIRED.DAT'), res['retirees'])
        post = str(tmp_path / 'post')
        shutil.copytree(rolled, post)
        rng_end = res['rng_end']
        header = bytearray(32)
        header[0], header[1], header[2] = 1, rng_end & 255, (rng_end >> 8) & 255
        header[8], header[9] = 0x34, 0x12
        open(os.path.join(post, 'HISTORY.DAT'), 'wb').write(bytes(header))
        if old_ms is not None:
            # an earlier season's MILESTON.DAT: in the league dir (so in the snapshot too)
            open(os.path.join(pre, 'MILESTON.DAT'), 'wb').write(old_ms)
            open(os.path.join(post, 'MILESTON.DAT'), 'wb').write(old_ms)
        py_rets = {n: i for n, i in res['retirees'].items() if i}
        season = hist_mod.History.load(os.path.join(post, 'HISTORY.DAT')).seasons_recorded + 1
        hist_mod.record_season(pre, os.path.join(post, 'HISTORY.DAT'), season)
        hist_mod.mark_retired(os.path.join(post, 'HISTORY.DAT'), pre, py_rets, season)
        return pre, post

    def test_pass(self, tmp_path):
        pre, post = self._pair(tmp_path)
        assert dynasty_gate.history_check(pre, post) == []

    def test_pass_with_existing_mileston(self, tmp_path):
        """pre already holds MILESTON.DAT (every season after the first): the expectation
        must start from it, or the old records are reported as a difference."""
        import struct as st
        old = st.pack('<HHBBH', 0, 0, 33, 0, 210)
        pre, post = self._pair(tmp_path, old_ms=old)
        assert open(os.path.join(post, 'MILESTON.DAT'), 'rb').read()[:8] == old
        assert dynasty_gate.history_check(pre, post) == []

    def test_hist_byte_flip_reports_offset(self, tmp_path):
        pre, post = self._pair(tmp_path)
        hp = os.path.join(post, 'HISTORY.DAT')
        raw = bytearray(open(hp, 'rb').read())
        raw[40] ^= 0xff
        open(hp, 'wb').write(bytes(raw))
        errs = dynasty_gate.history_check(pre, post)
        assert len(errs) == 1
        assert 'offset 40' in errs[0]

    def test_missing_mileston(self, tmp_path):
        pre, post = self._pair(tmp_path)
        os.remove(os.path.join(post, 'MILESTON.DAT'))
        errs = dynasty_gate.history_check(pre, post)
        assert any('MILESTON' in e for e in errs)

    def _chain(self, tmp_path):
        """_pair plus ROSTERS on the post league, as the C8 BAT runs it (DYNSNAP = pre)."""
        from m4 import rosters
        pre, post = self._pair(tmp_path)
        assert rosters.run(post, pre, os.path.join(post, 'HISTORY.DAT'), os.path.join(pre, 'RETIRED.DAT')) == 0
        return pre, post

    def test_rosters_chain_pass(self, tmp_path):
        pre, post = self._chain(tmp_path)
        assert os.path.exists(os.path.join(post, 'POOL1.V20'))
        assert dynasty_gate.rosters_check(pre, post, 0x1234) == []
        assert dynasty_gate.history_check(pre, post, rosters_ran=True) == []

    def test_rosters_chain_without_flag_fails_history(self, tmp_path):
        """ROSTERS moved the rng word: the C5-only expectation no longer holds."""
        pre, post = self._chain(tmp_path)
        assert dynasty_gate.history_check(pre, post) != []

    def test_rosters_chain_catches_v20_flip(self, tmp_path):
        pre, post = self._chain(tmp_path)
        p = os.path.join(post, 'CLASALE1.V20')
        raw = bytearray(open(p, 'rb').read())
        raw[400] ^= 1
        open(p, 'wb').write(bytes(raw))
        assert dynasty_gate.rosters_check(pre, post, 0x1234) == ['CLASALE1.V20 differs at offset 400']

    def test_rosters_chain_catches_start_word_flip(self, tmp_path):
        """Bytes 16..17 (ROSTERS start word) seed the reference ROSTERS: a flip there fails rosters_check, while the
        HISTWR check leaves those bytes to it."""
        pre, post = self._chain(tmp_path)
        hp = os.path.join(post, 'HISTORY.DAT')
        h = bytearray(open(hp, 'rb').read())
        h[16] ^= 1
        open(hp, 'wb').write(bytes(h))
        assert dynasty_gate.rosters_check(pre, post, 0x1234) != []
        assert dynasty_gate.history_check(pre, post, rosters_ran=True) == []

    def test_rosters_chain_missing_pool(self, tmp_path):
        pre, post = self._chain(tmp_path)
        os.remove(os.path.join(post, 'POOL2.V20'))
        assert 'POOL2.V20 only in reference' in dynasty_gate.rosters_check(pre, post, 0x1234)

    def test_gate_one_ok_wiring(self):
        """history_check returns [] on a pass; gate_one must map that to 'PASS'
        and count it as ok (source check: gate_one drives a live display)."""
        src = open(os.path.join(os.path.dirname(dynasty_gate.__file__), 'dynasty_gate.py')).read()
        body = src[src.index('def gate_one'):src.index('def main')]
        assert "'PASS' if not herrs else herrs" in body
        assert "rec['history_check'] in ('PASS', 'SKIPPED')" in body

    def test_setup_fresh_source(self):
        src = open(os.path.join(os.path.dirname(dynasty_gate.__file__), 'dynasty_gate.py')).read()
        assert 'HISTWR.EXE' in src
        assert 'ROSTERS.EXE' in src and 'DYNVIEW.EXE' in src
        assert 'bytes(4)' not in src


def write_retired(path, retirees):
    """C5 RETIRED.DAT: u8 nteam, then nteam x (13 B name + 40 B flags)."""
    names = sorted(retirees)
    with open(path, 'wb') as f:
        f.write(bytes([len(names)]))
        for n in names:
            f.write(n.encode('latin-1').ljust(13, b'\0')[:13])
            fb = bytearray(40)
            for i in retirees[n]:
                fb[i] = 1
            f.write(bytes(fb))


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


def test_roster_checks_pitching_zero_only_for_non_pitchers(tmp_path):
    """C4 batter rookies (any pos1 != 0, e.g. DH 9) may carry 0 pitching ratings; a pitcher (pos1 0) may not."""
    pre_src = '/mnt/nvme/tlrb2/fixtures/t4/s1_pre'
    if not os.path.isdir(pre_src):
        pytest.skip('fixtures missing')
    import v20
    pre, post = str(tmp_path / 'pre'), str(tmp_path / 'post')
    shutil.copytree(pre_src, pre)
    shutil.copytree(pre_src, post)
    fn = sorted(f for f in os.listdir(post) if f.upper().endswith('.V20'))[0]
    t = v20.Team.load(os.path.join(post, fn))
    bat = next(i for i in range(40) if t.players[i].active and (t.players[i].raw[31] & 15) != 0)
    pit = next(i for i in range(40) if t.players[i].active and (t.players[i].raw[31] & 15) == 0)
    for i in (bat, pit):
        for r in ('control', 'velocity', 'endurance'):
            t.players[i][r] = 0
    t.save(os.path.join(post, fn))
    errs, _ = dynasty_gate.roster_checks(pre, post, False)
    rating = [e for e in errs if 'rating' in e]
    assert rating == [f'{fn} rec {pit}: rating out of 1..15: [\'control\', \'velocity\', \'endurance\']'], rating


class TestInstallLeague:
    def _dirs(self, tmp_path):
        lg, src = tmp_path / 'CLASSIC', tmp_path / '1985'
        lg.mkdir()
        src.mkdir()
        for n in ('CLASSIC.MAJ', 'CLASALE1.V20', 'HISTORY.DAT'):
            (lg / n).write_bytes(b'old')
        for n in ('CLASSIC.MAJ', 'CLASALE1.V20'):
            (src / n).write_bytes(b'new ' + n.encode())
        return lg, src

    def test_copies_same_named_files_only(self, tmp_path):
        lg, src = self._dirs(tmp_path)
        assert dynasty_gate.install_league(str(lg), str(src)) == ['CLASALE1.V20', 'CLASSIC.MAJ']
        assert (lg / 'CLASSIC.MAJ').read_bytes() == b'new CLASSIC.MAJ'
        assert (lg / 'HISTORY.DAT').read_bytes() == b'old'

    def test_refuses_unknown_file(self, tmp_path):
        import pytest
        lg, src = self._dirs(tmp_path)
        (src / 'BOGUS.V20').write_bytes(b'x')
        with pytest.raises(SystemExit):
            dynasty_gate.install_league(str(lg), str(src))
        assert (lg / 'CLASSIC.MAJ').read_bytes() == b'old'

    def test_refuses_empty_src(self, tmp_path):
        import pytest
        lg, src = self._dirs(tmp_path)
        for p in src.iterdir():
            p.unlink()
        with pytest.raises(SystemExit):
            dynasty_gate.install_league(str(lg), str(src))

    def test_done_flag_missing_or_empty_history(self):
        """A Lahman league's first roll has no HISTORY.DAT in DYNSNAP (gate crashed on s101)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            assert dynasty_gate.done_flag(tmpdir) == 0
            h = Path(tmpdir) / 'HISTORY.DAT'
            h.write_bytes(b'')
            assert dynasty_gate.done_flag(tmpdir) == 0
            h.write_bytes(b'\x01\x02')
            assert dynasty_gate.done_flag(tmpdir) == 1

    def test_league_needs_fresh(self):
        import pytest
        with pytest.raises(SystemExit):
            dynasty_gate.main(['--seasons', '1', '--league', '/nonexistent'])
