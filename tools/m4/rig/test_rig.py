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




if __name__ == '__main__':
    pytest.main([__file__, '-v'])
