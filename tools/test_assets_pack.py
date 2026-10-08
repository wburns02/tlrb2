"""Tests for the SCR and ANM/OVL packers in assets.py (round trip through the readers)."""

import glob
import os
import random
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assets import (  # noqa: E402
    parse_scr,
    read_frames,
    read_scr,
    write_frames,
    write_scr,
)

FILES = "/mnt/nvme/tlrb2/files"
HAVE_DATA = os.path.isdir(FILES)
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="game files not at %s" % FILES)

FRAME_KEYS = ("flags", "h", "w", "yo", "xo", "raw", "stored")


def _anm_paths():
    paths = []
    for pat in ("ANMS/*.ANM", "ANMS/*.OVL", "*.ANM", "*.OVL"):
        paths += glob.glob(os.path.join(FILES, pat))
    return sorted(paths)


def _same_frames(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        for k in FRAME_KEYS:
            assert x[k] == y[k], k


def _walk_clen(d):
    """Skip every frame by its header alone (clen, or h*w when stored); must land exactly on the end."""
    p = 2
    for _ in range(struct.unpack_from("<H", d)[0]):
        _, h, w, _, _, cl = struct.unpack_from("<6H", d, p)
        p += 12 + (cl if cl else h * w)
    assert p == len(d)


@needs_data
def test_scr_real_files():
    paths = sorted(glob.glob(os.path.join(FILES, "SCREENS", "*.SCR")))
    assert paths, "no SCR files found"
    for path in paths:
        with open(path, "rb") as f:
            d = f.read()
        s = read_scr(d)
        t, h, w, raw = parse_scr(d)
        assert (s["flags"] >> 8, s["h"], s["w"], s["raw"]) == (t, h, w, raw), path
        clen = struct.unpack_from("<7H", d)[6]
        assert clen == len(d) - 14, path

        packed = write_scr(s)
        r = read_scr(packed)
        for k in ("flags", "h", "w", "yo", "xo", "raw"):
            assert r[k] == s[k], (path, k)
        assert struct.unpack_from("<7H", packed)[6] == len(packed) - 14, path


@needs_data
def test_anm_ovl_real_files():
    accepted, skipped = 0, 0
    for path in _anm_paths():
        with open(path, "rb") as f:
            d = f.read()
        try:
            frames = read_frames(d)
        except Exception:
            skipped += 1
            continue
        accepted += 1
        _walk_clen(d)
        packed = write_frames(frames)
        _walk_clen(packed)
        _same_frames(read_frames(packed), frames)
    print("\nANM/OVL accepted %d skipped %d" % (accepted, skipped))
    # 216 files: 194 normal, 21 big replay ANMs, OLDPORT.ANM
    assert accepted >= 194, (accepted, skipped)


def test_frames_mixed_stored_and_compressed():
    rnd = random.Random(7)
    frames = [
        dict(flags=0x0500, h=2, w=3, yo=1, xo=2, raw=bytes([1, 2, 3, 4, 5, 6]), stored=True),
        dict(flags=0x0200, h=8, w=8, yo=0, xo=0, raw=bytes(rnd.choice(b"abc") for _ in range(64)), stored=False),
    ]
    packed = write_frames(frames)
    assert struct.unpack_from("<H", packed)[0] == 2
    assert struct.unpack_from("<6H", packed, 2)[5] == 0  # stored frame: clen 0
    back = read_frames(packed)
    _same_frames(back, frames)
    assert back[0]["stored"] is True and back[1]["stored"] is False


def test_scr_synthetic_round_trip():
    raw = bytes((i * 7) & 0xFF for i in range(20 * 30))
    s = dict(flags=0x3C00, h=20, w=30, yo=5, xo=9, raw=raw)
    packed = write_scr(s)
    assert struct.unpack_from("<7H", packed)[6] == len(packed) - 14
    r = read_scr(packed)
    assert r == s


def test_write_scr_rejects_wrong_size():
    with pytest.raises(ValueError):
        write_scr(dict(flags=0, h=2, w=2, yo=0, xo=0, raw=b"abc"))


def test_write_frames_rejects_wrong_size():
    f = dict(flags=0, h=2, w=2, yo=0, xo=0, raw=b"abc", stored=True)
    with pytest.raises(ValueError):
        write_frames([f])
    f["stored"] = False
    with pytest.raises(ValueError):
        write_frames([f])


def test_write_frames_rejects_clen_overflow():
    rnd = random.Random(3)
    raw = bytes(rnd.getrandbits(8) for _ in range(64000))  # incompressible: ~72 KB stream
    f = dict(flags=0, h=250, w=256, yo=0, xo=0, raw=raw, stored=False)
    with pytest.raises(ValueError):
        write_frames([f])
    f["stored"] = True
    packed = write_frames([f])  # stored form has no clen limit
    assert struct.unpack_from("<6H", packed, 2)[5] == 0


def test_read_frames_rejects_trailing_bytes():
    f = dict(flags=0, h=2, w=2, yo=0, xo=0, raw=b"wxyz", stored=True)
    packed = write_frames([f]) + b"\x00"
    with pytest.raises(ValueError):
        read_frames(packed)


def test_read_frames_rejects_overrun():
    f = dict(flags=0, h=2, w=2, yo=0, xo=0, raw=b"wxyz", stored=True)
    packed = write_frames([f])
    with pytest.raises(ValueError):
        read_frames(packed[:-1])


def test_read_frames_rejects_truncated_stream():
    raw = bytes(range(64)) * 4
    f = dict(flags=0, h=16, w=16, yo=0, xo=0, raw=raw, stored=False)
    packed = write_frames([f])
    with pytest.raises(ValueError):
        read_frames(packed[:-3])
