"""dynasty_ref: the interleaved rollover + fill reference DYNASTY.EXE is gated against."""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from m4 import dynasty_ref, rollover    # noqa: E402
from v20 import Team                   # noqa: E402

M3_DIR = '/mnt/nvme/tlrb2/snaps/m3_end/TEAMS/CLASSIC'
needs_m3 = pytest.mark.skipif(not os.path.isdir(M3_DIR), reason='m3_end snapshot missing')


def _v20s(d):
    return {f: open(os.path.join(d, f), 'rb').read() for f in sorted(os.listdir(d)) if f.endswith('.V20')}


@needs_m3
def test_no_fill_equals_plain_rollover(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    dynasty_ref.roll_league(M3_DIR, str(a), 4321, fill=False)
    rollover.rollover(M3_DIR, str(b), cfg=dynasty_ref.CFG, seed=4321)
    assert _v20s(str(a)) == _v20s(str(b))


@needs_m3
def test_fill_restores_every_retiree_slot(tmp_path):
    out = tmp_path / 'o'
    r = dynasty_ref.roll_league(M3_DIR, str(out), 4321)
    assert sum(map(len, r['retirees'].values())) > 0
    for name, recs in r['retirees'].items():
        assert set(recs) <= set(r['filled'][name])
        t = Team.load(str(out / name))
        for i in recs:
            assert t.players[i].active


@needs_m3
def test_deterministic(tmp_path):
    a = dynasty_ref.roll_league(M3_DIR, str(tmp_path / 'a'), 77)
    b = dynasty_ref.roll_league(M3_DIR, str(tmp_path / 'b'), 77)
    assert a['rng_end'] == b['rng_end']
    assert _v20s(str(tmp_path / 'a')) == _v20s(str(tmp_path / 'b'))
