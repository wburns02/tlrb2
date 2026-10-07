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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
