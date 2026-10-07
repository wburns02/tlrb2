"""C4 rookie variety check (Python reference).

300 rookies from one seed must show real variety (contract C4):
- at least 8 distinct values of power (74 lo, batters),
- every rating within 1..cap (12, endurance 10),
- grade frequencies within 50..70 / 20..40 / 4..16 percent.

The grade is not stored, so it is reconstructed by replaying the same draw
stream: grades are the 9th..(8+n)th byte draws of each make() call.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from m4.rookies import RookieGen, Rng  # noqa: E402
from m4.rollover import Rng as BaseRng  # noqa: E402

SEASON_YEAR = 50          # the stored byte (year - 1870)
N_ROOKIES = 300

# Position codes cycled like the fill ladder emits them (a realistic mix).
CODES = [0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]


class _DrawRecorder(BaseRng):
    """Rng that records every byte draw, so grades can be replayed."""

    def __init__(self, seed):
        super().__init__(seed)
        self.dbytes = []

    def draw(self):
        v = super().draw()
        self.dbytes.append(v & 0xFF)
        return v


def _rating_nibbles(rec, pos):
    """The stored C4 ratings of one record, keyed by the C1 order names."""
    if pos == 0:
        return {
            "control": rec[134] & 0x0F,
            "velocity": rec[134] >> 4,
            "endurance": rec[135] >> 4,
        }
    return {
        "power": rec[74] & 0x0F,
        "bunt": rec[74] >> 4,
        "hit_run": rec[75] & 0x0F,
        "speed": rec[29] >> 4,
        "range": rec[94] >> 4,
        "arm": rec[94] & 0x0F,
    }


def _is_batter(rec):
    return rec[31] & 0x0F != 0


def test_c4_variety():
    rng = _DrawRecorder(5)
    gen = RookieGen(rng)
    positions = []
    recs = []
    for i in range(N_ROOKIES):
        pos = CODES[i % len(CODES)]
        positions.append(pos)
        recs.append(gen.make(pos, SEASON_YEAR))

    # -- powers (batters): at least 8 distinct values ----------------------
    powers = {recs[i][74] & 0x0F
              for i in range(N_ROOKIES) if positions[i] != 0}
    assert len(powers) >= 8, "only %d distinct power values: %r" % (
        len(powers), sorted(powers))

    # -- every rating within 1..cap ----------------------------------------
    for i, rec in enumerate(recs):
        for key, v in _rating_nibbles(rec, positions[i]).items():
            cap = 10 if key == "endurance" else 12
            assert 1 <= v <= cap, "rookie %d %s=%d outside 1..%d" % (
                i, key, v, cap)

    # -- grade frequencies (replay the byte-draw stream) --------------------
    # Per make(): 8 draws before the grade (last, first, age, throws, switch,
    # portrait, exper, consist), then the grade draw. The draw counts match
    # between python and the blob (test_fill_unicorn proves it), so replaying
    # the recorded stream in order recovers each grade.
    grades = [0, 0, 0]
    idx = 0
    for i in range(N_ROOKIES):
        # replay this rookie's draws from the recorded stream: walk the
        # generator again alongside the record sequence
        d = rng.dbytes[idx + 8]           # the grade draw
        grades[0 if d < 154 else (1 if d < 230 else 2)] += 1
        # advance by the draws this make consumed
        idx += _draws_for(positions[i])
    assert idx == len(rng.dbytes), "draw stream drifted: %d vs %d" % (
        idx, len(rng.dbytes))

    total = N_ROOKIES
    pct = [100.0 * g / total for g in grades]
    assert 50 <= pct[0] <= 70, "grade-0 share %.1f%% outside 50..70" % pct[0]
    assert 20 <= pct[1] <= 40, "grade-1 share %.1f%% outside 20..40" % pct[1]
    assert 4 <= pct[2] <= 16, "grade-2 share %.1f%% outside 4..16" % pct[2]


def _draws_for(pos):
    """Draws one make() consumes: 8 pre-rating + 1 grade + per-rating."""
    return 9 + (3 if pos == 0 else 6)


if __name__ == "__main__":
    test_c4_variety()
    print("C4 variety ok")
