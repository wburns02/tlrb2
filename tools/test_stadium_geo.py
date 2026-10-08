"""Tests for the park geometry in stadium.py: the world to panorama mapping, the classifier, fence heights and
with_fences. The synthetic tests need no game data; the rest use the stock CFGs when they are present."""

import glob
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stadium  # noqa: E402
from assets import SRC  # noqa: E402

CFGS = sorted(glob.glob(os.path.join(SRC, 'STADIUMS', '*.CFG')))
need = pytest.mark.skipif(len(CFGS) < 41, reason='game data missing')
CHANGED = [(0x20, 0x2a), (0x153, 0x26b), (0x383, 0x473), (0x475, 0x501)]   # what with_fences may write
DIST = (330, 375, 405, 375, 330)


def _cfg(stem):
    return open(os.path.join(SRC, 'STADIUMS', stem + '.CFG'), 'rb').read()


def _blank():
    return bytearray(0x509)


def _set_edge(buf, base, i, row, col):
    struct.pack_into('<2H', buf, base + 4 * i, row, col)


def _walled():
    """blank CFG with the stands wall at row 600 in every column, so with_fences has room to work."""
    buf = _blank()
    for k in range(stadium.EDGE_N):
        _set_edge(buf, stadium.WALL_EDGE, k, 600, k)
    return buf


def _outside(a, b):
    return [i for i in range(0x509) if not any(lo <= i < hi for lo, hi in CHANGED) and a[i] != b[i]]


# synthetic: no game data needed

def test_tdiv_truncates_toward_zero():
    assert stadium.tdiv(-7, 2) == -3
    assert stadium.tdiv(7, -2) == -3
    assert stadium.tdiv(-7, -2) == 3
    assert stadium.tdiv(7, 2) == 3


def test_field_mapping_known_points():
    assert stadium.field_row(0) == 399
    assert stadium.field_row(-5) == 404
    assert stadium.field_x(0) == 560


def test_classify_fence_wall_obstacle():
    buf = _blank()
    _set_edge(buf, stadium.FENCE_EDGE, 5, 300, 5)
    _set_edge(buf, stadium.WALL_EDGE, 5, 400, 5)
    _set_edge(buf, stadium.FENCE_EDGE, 140, 340, 5)
    _set_edge(buf, stadium.FENCE_EDGE, 141, 360, 5)
    assert stadium.classify(buf, 200, 5) == 2          # cx 300 is at the fence base
    assert stadium.classify(buf, 201, 5) == 0          # cx 301, in play
    assert stadium.classify(buf, 240, 5) == 1          # cx 340, obstacle bottom is inclusive
    assert stadium.classify(buf, 245, 5) == 1          # cx 345, inside the obstacle
    assert stadium.classify(buf, 300, 5) == 1          # cx 400 reaches the wall


def test_classify_outfield_foul_lines():
    buf = _blank()
    _set_edge(buf, stadium.FENCE_EDGE, 0, 250, 0)
    _set_edge(buf, stadium.FENCE_EDGE, 69, 500, 69)
    assert stadium.classify(buf, 450, 70) == 1         # cx 550 past the right foul line
    assert stadium.classify(buf, 350, 70) == 3         # cx 450, fair side of the line
    assert stadium.classify(buf, 200, 70, neg=True) == 1   # cx 300 past the left foul line at row 250
    assert stadium.classify(buf, 100, 70, neg=True) == 3   # cx 200


def test_obstacle_pair_rules():
    buf = _blank()
    _set_edge(buf, stadium.FENCE_EDGE, 140, 340, 5)
    _set_edge(buf, stadium.FENCE_EDGE, 141, 360, 5)
    _set_edge(buf, stadium.FENCE_EDGE, 142, 340, 7)    # columns differ: not an obstacle
    _set_edge(buf, stadium.FENCE_EDGE, 143, 360, 8)
    _set_edge(buf, stadium.FENCE_EDGE, 144, 0, 9)      # zero row: not an obstacle
    _set_edge(buf, stadium.FENCE_EDGE, 145, 30, 9)
    _set_edge(buf, stadium.FENCE_EDGE, 146, 10, 9)
    _set_edge(buf, stadium.FENCE_EDGE, 147, 20, 9)
    assert stadium.obstacles(buf) == [(5, 340, 360), (9, 10, 20)]


def test_fence_height_from_row_and_top():
    buf = _blank()
    _set_edge(buf, stadium.FENCE_EDGE, 3, 200, 3)
    for top, want in ((190, 2), (180, 5), (200, 0), (300, 0)):
        struct.pack_into('<H', buf, stadium.FENCE_TOP + 6, top)
        assert stadium.fence_height(buf, 3) == want, top
    assert stadium.fence_height(buf, 70) == 10


def test_tops_dugouts_and_info_keys():
    buf = _blank()
    struct.pack_into('<H', buf, stadium.FENCE_TOP, 192)
    struct.pack_into('<4h', buf, stadium.DUGOUT, 29, 69, 32, -62)
    assert stadium.fence_tops(buf)[0] == 192
    assert stadium.dugouts(buf) == ((29, 69), (32, -62))
    i = stadium.info(bytes(buf))
    assert i['obstacles'] == 0 and i['dugouts'] == ((29, 69), (32, -62)) and len(i['zones']) == 5


def test_with_fences_rejects_bad_values():
    buf = _walled()
    with pytest.raises(ValueError):
        stadium.with_fences(buf, (100, 375, 405, 375, 330), 8)
    with pytest.raises(ValueError):
        stadium.with_fences(buf, DIST, 99)
    with pytest.raises(ValueError):
        stadium.with_fences(buf, (330, 375, 405, 375), 8)


def test_with_fences_round_trip_synthetic():
    buf = _walled()
    _set_edge(buf, stadium.FENCE_EDGE, 140, 340, 5)    # an obstacle the write must clear
    _set_edge(buf, stadium.FENCE_EDGE, 141, 360, 5)
    out = stadium.with_fences(bytes(buf), DIST, 8)
    assert len(out) == len(buf)
    assert all(abs(a - b) <= 6 for a, b in zip(stadium.zone_distances(out), DIST))
    assert all(stadium.fence_height(out, k) == 8 for k in range(stadium.EDGE_N))
    assert stadium.obstacles(out) == []
    assert _outside(buf, out) == []


# game data: the stock parks

@need
def test_grass_fence_rows_tops_dugouts():
    g = _cfg('GRASS')
    assert stadium.info(g)['fence_y'][:4] == [228, 222, 216, 210]
    assert stadium.fence_tops(g)[:3] == [192, 187, 182]
    assert stadium.dugouts(g) == ((29, 69), (32, -62))
    assert stadium.obstacles(g) == []
    assert all(7 <= h <= 10 for h in stadium.fence_heights(g)[:70])


@need
def test_fenway_height_and_obstacle():
    f = _cfg('FENWAY')
    assert max(stadium.fence_heights(f)) == 34
    obs = stadium.obstacles(f)
    assert len(obs) == 1 and obs[0][0] == 65


@need
def test_grass_zone_distances():
    z = stadium.zone_distances(_cfg('GRASS'))
    assert 315 <= z[0] <= 340 and 315 <= z[4] <= 340
    assert 395 <= z[2] <= 415


@need
def test_grass_classify_on_fence_and_wall():
    g = _cfg('GRASS')
    fy = stadium.info(g)['fence_y']
    assert stadium.classify(g, fy[35] - 100, 35) == 2
    assert stadium.classify(g, fy[35] - 99, 35) == 0
    assert stadium.info(g)['wall_y'][35] == 439
    assert stadium.classify(g, fy[69] - 100, 70) == 3


@need
def test_grass_round_trip():
    g = _cfg('GRASS')
    out = stadium.with_fences(g, DIST, 8)
    assert all(abs(a - b) <= 6 for a, b in zip(stadium.zone_distances(out), DIST))
    assert all(7 <= stadium.fence_height(out, k) <= 9 for k in range(70))
    assert stadium.obstacles(out) == []
    assert _outside(g, out) == []


@need
def test_grass_with_fences_rejects_bad_values():
    g = _cfg('GRASS')
    with pytest.raises(ValueError):
        stadium.with_fences(g, (100, 375, 405, 375, 330), 8)
    with pytest.raises(ValueError):
        stadium.with_fences(g, DIST, 99)
