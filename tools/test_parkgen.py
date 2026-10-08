"""Tests for tools/parkgen.py: keep mask, CFG name/palette writer, quantizer, palette chooser, build on real data.

Never calls parkgen.gen (needs the ComfyUI GPU server).
"""

import os
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parkgen  # noqa: E402
import stadium  # noqa: E402
from assets import read_frames  # noqa: E402

GRASS_SDM = os.path.join(parkgen.SRC, 'STADIUMS', 'GRASS.SDM')
HAVE_GAME_DATA = os.path.exists(GRASS_SDM)


def _synthetic_cfg():
    cfg = bytearray((bytes(range(256)) * 6)[:1289])
    head = b'TLUB GENERIC GRASS\0STADIUM'.ljust(31, b'\0')
    cfg[0:31] = head
    cfg[31] = 1
    return bytes(cfg)


def _synthetic_pal():
    pal = []
    for i in range(256):
        pal += [(i * 3) % 256, (i * 5) % 256, (i * 7) % 256]
    return pal


def test_keep_mask_shape_dtype_symmetry_and_fraction():
    m = parkgen.keep_mask()
    assert m.shape == (444, 1120)
    assert m.dtype == bool
    mirrored = m[:, ::-1]
    assert (m != mirrored).mean() <= 0.02
    assert m[330, 560]
    assert not m[0, 0]
    assert not m[0, 1119]
    frac = m.mean()
    assert 0.35 <= frac <= 0.55


def test_cfg_with_name_lines_and_bytes_outside_untouched():
    cfg = _synthetic_cfg()
    out = parkgen.cfg_with(cfg, 'Tlub Modern Ballpark', _synthetic_pal())
    assert out[0:31] == b'TLUB MODERN BALLPARK'.ljust(31, b'\0')     # stale tail after the old NUL is cleared too
    assert out[31] == cfg[31]
    assert out[339:] == cfg[339:]
    assert len(out) == len(cfg)


def test_cfg_with_palette_round_trip():
    cfg = _synthetic_cfg()
    pal = []
    for v in range(256):
        c = v % 64
        pal += [c * 255 // 63, ((c * 3) % 64) * 255 // 63, ((c * 7) % 64) * 255 // 63]
    out = parkgen.cfg_with(cfg, 'X', pal)
    assert stadium.palette(out)[240:528] == pal[240:528]


@pytest.mark.parametrize('name', ['', 'A' * 31, 'A\0B', 'CAFÉ'])
def test_cfg_with_rejects_bad_names(name):
    with pytest.raises(ValueError):
        parkgen.cfg_with(_synthetic_cfg(), name, _synthetic_pal())


def test_quantize_shape_dtype_allowed_and_exact_solid():
    pal = _synthetic_pal()
    allowed = [0, 5, 80, 81, 100, 175]
    rng = np.random.default_rng(1)
    img = Image.fromarray(rng.integers(0, 256, (10, 20, 3), dtype=np.uint8))
    q = parkgen.quantize(img, pal, allowed)
    assert q.shape == (10, 20)
    assert q.dtype == np.uint8
    assert set(np.unique(q).tolist()) <= set(allowed)

    solid = Image.new('RGB', (20, 10), tuple(pal[100 * 3:100 * 3 + 3]))
    qs = parkgen.quantize(solid, pal, allowed, dither=False)
    assert (qs == 100).all()


def test_choose_palette_contract_and_deterministic():
    field_px = np.arange(80, 151, dtype=np.uint8)
    rng = np.random.default_rng(2)
    new_rgb = rng.integers(0, 256, (5000, 3), dtype=np.uint8)
    pal = _synthetic_pal()
    pal2, allowed = parkgen.choose_palette(field_px, new_rgb, pal)

    expected_allowed = sorted(set(range(17)) | set(range(80, 151)) | set(range(151, 176)))
    assert allowed == expected_allowed
    assert allowed == sorted(allowed)
    assert pal2[0:17 * 3] == pal[0:17 * 3]
    assert pal2[80 * 3:151 * 3] == pal[80 * 3:151 * 3]
    for k in range(151 * 3, 176 * 3):
        assert any(pal2[k] == v * 255 // 63 for v in range(64))
    pal3, allowed3 = parkgen.choose_palette(field_px, new_rgb, pal)
    assert pal3 == pal2
    assert allowed3 == allowed


@pytest.mark.skipif(not HAVE_GAME_DATA, reason='game data missing')
def test_build_on_real_grass(tmp_path):
    base_sdm = stadium.unpack(GRASS_SDM)
    base_cfg = open(os.path.join(parkgen.SRC, 'STADIUMS', 'GRASS.CFG'), 'rb').read()
    base_px = np.frombuffer(base_sdm, 'u1').reshape(444, 1120)
    rgb = stadium.render(base_sdm, stadium.palette(base_cfg))
    gen_png = str(tmp_path / 'gen.png')
    rgb.resize((1680, 664), Image.LANCZOS).save(gen_png)

    out, pal2 = parkgen.build('GRASS', gen_png, 'ZTEST', 'TEST PARK', str(tmp_path))

    for fn in ('ZTEST.SDM', 'ZTEST.CFG', 'ZTEST.OVL', 'ZTEST.png'):
        assert (tmp_path / fn).exists()

    assert stadium.unpack(str(tmp_path / 'ZTEST.SDM')) == out.tobytes()
    keep = parkgen.keep_mask()
    assert np.array_equal(out[keep], base_px[keep])
    assert set(np.unique(out).tolist()) <= (set(range(17)) | set(range(80, 176)))

    base_frames = read_frames(open(os.path.join(parkgen.SRC, 'ANMS', 'GRASS.OVL'), 'rb').read())
    new_frames = read_frames(open(str(tmp_path / 'ZTEST.OVL'), 'rb').read())
    assert len(new_frames) == len(base_frames)
    for nf, bf in zip(new_frames, base_frames):
        assert (nf['h'], nf['w'], nf['flags']) == (bf['h'], bf['w'], bf['flags'])
    raw0 = set(bytes(new_frames[0]['raw']))
    assert raw0 <= (set(range(17)) | set(range(80, 176)))

    cfg2 = open(str(tmp_path / 'ZTEST.CFG'), 'rb').read()
    assert len(cfg2) == 1289
    assert cfg2[0:31] == b'TEST PARK'.ljust(31, b'\0')
    assert cfg2[31:51] == base_cfg[31:51]
    assert cfg2[339:] == base_cfg[339:]
    used = [int(i) for i in np.unique(base_px[keep]) if 80 <= i < 176]        # the kept field's colours are untouched
    for i in used:
        o = stadium.PAL_OFF + (i - stadium.PAL_LO) * 3
        assert cfg2[o:o + 3] == base_cfg[o:o + 3], i


@pytest.mark.parametrize('stem', ['TOOLONGNAME', 'A.B'])
def test_build_rejects_bad_stem_before_touching_files(tmp_path, stem):
    with pytest.raises(ValueError):
        parkgen.build('GRASS', str(tmp_path / 'nonexistent.png'), stem, 'X', str(tmp_path / 'out'))
    assert not (tmp_path / 'out').exists()
