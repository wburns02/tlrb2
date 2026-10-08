"""Tests for the CFG header decoder in stadium.py against the stock parks (values as shown on Assign Stadiums)."""

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


def _info(stem):
    return stadium.info(open(os.path.join(SRC, 'STADIUMS', stem + '.CFG'), 'rb').read())


@need
def test_info_matches_assign_stadiums_screen():
    g = _info('GRASS')                                  # the rig's Assign Stadiums screen for GRASS
    assert g['name'] == 'TLUB GENERIC GRASS'
    assert g['fences'] == (330, 370, 410, 370, 330)
    assert (g['wind_mph'], g['temp_f'], g['humidity'], g['altitude_ft']) == (10, 72, 60, 0)
    assert _info('MILEHIGH')['altitude_ft'] == 5280
    assert _info('FENWAY')['altitude_ft'] == 21


@need
def test_surface_and_notes_ids():
    infos = {os.path.basename(f)[:-4]: stadium.info(open(f, 'rb').read()) for f in CFGS}
    assert {k for k, v in infos.items() if v['surface'] == 'classic'} == {
        'BAKER', 'CONNIE', 'CROSLEY', 'EBBETS', 'LACOL', 'POLO', 'YANKEE'}
    assert infos['ASTRO']['surface'] == 'turf' and infos['WRIGLEY']['surface'] == 'grass'
    assert sorted(v['notes'] for v in infos.values()) == list(range(41))


@need
def test_edge_tables_are_column_indexed():
    for f in CFGS:
        d = open(f, 'rb').read()
        for base in (stadium.FENCE_EDGE, stadium.WALL_EDGE):
            cols = [struct.unpack_from('<H', d, base + 4 * k + 2)[0] for k in range(stadium.EDGE_N)]
            if os.path.basename(f) == 'RIVER.CFG' and base == stadium.FENCE_EDGE:
                assert cols[:69] == list(range(69)) and struct.unpack_from('<2H', d, base + 4 * 69) == (0, 0)
            else:
                assert cols == list(range(stadium.EDGE_N)), f
        i = stadium.info(d)
        inner = zip(i['fence_y'][6:64], i['wall_y'][6:64])  # the edges meet (and may cross by a few px) at the poles
        assert all(w > y for y, w in inner), f              # fence above the stands wall
