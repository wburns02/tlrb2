"""C4 rookie variety check (Python reference).

300 rookies from one seed must show real variety (contract C4):
- at least 8 distinct values of power (74 lo, batters),
- every rating within 1..cap (12, endurance 10),
- grade frequencies within 50..70 / 20..40 / 4..16 percent.

Names (contract C4 amendment): mixed case like the shipped V20 data
("Adams", "McCall"), NUL padded, never space padded, never all caps.

The grade is not stored, so it is reconstructed by replaying the same draw
stream: grades are the 9th..(8+n)th byte draws of each make() call.
"""

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from m4.rookies import (  # noqa: E402
    RookieGen, Rng, LAST_NAMES, FIRST_NAMES, LAST_TABLE, FIRST_TABLE,
)
from m4.rollover import Rng as BaseRng  # noqa: E402

SEASON_YEAR = 50          # the stored byte (year - 1870)
N_ROOKIES = 300

# Position codes cycled like the fill ladder emits them (a realistic mix).
CODES = [0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]

# The assembled table in the bin must equal the Python tables; find them by
# searching the bin for LAST_TABLE.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BIN = os.path.join(_HERE, "blob", "rookie_fill.bin")

_NAME_PAT = re.compile(r"^[A-Z][a-z]*([A-Z][a-z]+)?$")


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


def test_name_charset_and_case():
    """Names: mixed case, ASCII, within the field limits (contract C4)."""
    assert len(LAST_NAMES) == 128 and len(FIRST_NAMES) == 64
    assert len(set(LAST_NAMES)) == 128 and len(set(FIRST_NAMES)) == 64
    for n in LAST_NAMES:
        assert _NAME_PAT.match(n), "last name %r not mixed case" % n
        assert len(n) <= 11, "last name %r over 11 chars" % n
    for n in FIRST_NAMES:
        assert _NAME_PAT.match(n), "first name %r not mixed case" % n
        assert len(n) <= 7, "first name %r over 7 chars" % n


def test_record_name_bytes_nul_padded():
    """A generated record's bytes 0..20: NUL padding, no 0x20 (the shipped
    V20 convention, never space padded)."""
    gen = RookieGen(Rng(3))
    for pos in (0, 1, 5, 9):
        rec = gen.make(pos, SEASON_YEAR)
        name = bytes(rec[0:20])
        for ch in name:
            assert ch != 0x20, "0x20 in name bytes for pos %d" % pos
        last = name[0:12].rstrip(b"\x00")
        first = name[12:20].rstrip(b"\x00")
        assert last and last.decode("ascii") in LAST_NAMES
        assert first and first.decode("ascii") in FIRST_NAMES
        # bytes 20 (age) is not part of the name; the fields are NUL padded
        assert len(last) == len(name[0:12].rstrip(b"\x00"))
        assert name[0:12][len(last):] == b"\x00" * (12 - len(last))
        assert name[12:20][len(first):] == b"\x00" * (8 - len(first))


def test_bin_table_bytes_match_python():
    """The assembled name table in rookie_fill.bin equals LAST_TABLE +
    FIRST_TABLE (found by searching the bin for LAST_TABLE)."""
    bin_ = open(_BIN, "rb").read()
    needle = b"".join(LAST_TABLE)
    data = needle + b"".join(FIRST_TABLE)
    idx = bin_.find(needle)
    assert idx >= 0, "LAST_TABLE not found in the bin"
    assert bin_[idx:idx + len(data)] == data, "table bytes differ from python"


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
