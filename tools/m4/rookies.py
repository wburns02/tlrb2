#!/usr/bin/env python3
"""Rookie-class generator for the TLRB2 M4 dynasty mod.

Builds 143-byte V20 player records for rookie-class callups. The fill path
(the path the DYNASTY.EXE P2 blob ports byte-exactly) uses our own name
pools and the C4 graded rating draws: it needs no game data, so the module
stays importable and testable offline.

Pipeline per rookie (see RookieGen.make):
  1. blank record (all zeros, matches UTIL 5000:e89d init_blank_player_record)
  2. last then first name from our own pools (C4; never harvested from the
     game), index = d % 128 and d % 64 with d = draw() & 0xff
  3. age / year_off / exp / games (age weighted as the WIP blob)
  4. position code (caller supplied)
  5. plausible season stat line per position (constants as the WIP blob)
  6. C4 rating draws: one grade draw, then one draw per rating in the C1
     rating order (batters power, bunt, hit_run, speed, range, arm;
     pitchers control, velocity, endurance), value = 3 + d % 5 + bonus,
     clamped 1..cap (cap = 10 endurance, 12 else)
  7. salary: 255 pitchers / 109 batters (as the WIP blob)
  8. portrait (face = d % n from the face table) + group flag
  9. throws/bats nibble

Draw order per rookie (C4): last-name, first-name, age, throws, switch,
portrait, exper, consist, grade, then the per-rating draws.

Names are stored like the shipped V20 data (contract C4): mixed case
("Adams", "McCall"), NUL padded, never space padded, never all caps.

Determinism: all randomness flows through the Rng class from
tools/m4/rollover.py (xorshift16). Same seed + same ordered inputs gives
byte-identical output.
"""

import os
import sys

# Make the m4 package importable regardless of cwd, relative to this file.
_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from m4.rollover import Rng  # noqa: E402  (xorshift16 rng)

# ---------------------------------------------------------------------------
# Constants block: every magic threshold lives here.
# ---------------------------------------------------------------------------

RECORD_LEN = 143          # bytes per player record
ROSTER_RECORDS = 40       # records 0..39 = roster, 40..79 = season-half stats
SEASON_HALF_START = 40    # first season-half record index
SEASON_HALF_COUNT = 40    # season-half record count per team file

# Position codes (FORMATS.md player record section).
POS_P, POS_C, POS_1B, POS_2B, POS_3B, POS_SS = 0, 1, 2, 3, 4, 5
POS_LF, POS_CF, POS_RF, POS_DH, POS_OF = 6, 7, 8, 9, 10
POS_IF, POS_OI, POS_CO, POS_CI, POS_C3 = 11, 12, 13, 14, 15

BATTER_POSITIONS = set(range(1, 16))  # everything except pitcher is a batter

# Age distribution: 18..23 weighted toward 20-22 (as the WIP blob; weights
# sum to 100 so the draw is % 100 and the cumulative cuts match the asm's
# cmp chain: <4 -> 18, <14 -> 19, <38 -> 20, <64 -> 21, <86 -> 22, else 23).
AGE_CHOICES = [18, 19, 20, 21, 22, 23]
AGE_WEIGHTS = [4, 10, 24, 26, 22, 14]

# Throws/bats distribution (as the WIP blob): 72% R throwers, 16% switch.
THROWS_R_PER_100 = 72
BATS_S_PER_100 = 16

# Portrait face table (see load_faces): n faces, each with a group flag
# (record byte 29 bit0, UTIL DS:776e, dark skin = 1). Default = the stock
# PORTRAIT.ANM frames 0..29, flagged per STOCK_FACE_GROUP. A mod that appends
# faces (tools/faces.py writes ANMS/FACEGRP.DAT) widens the table up to 981.
DEFAULT_FACE_N = 30
STOCK_FACE_GROUP = frozenset({3, 4, 16, 18, 20, 21, 22, 25, 27})
FACE_TABLE_MAX = 981      # BB reads PORTRAIT.ANM only below index 981

# Salary (as the WIP blob): constant per position code.
SALARY_PITCHER = 255
SALARY_BATTER = 109

# Position mix per team for gen_class (task spec): 3 P, 1 C, 1 each of
# 1B/2B/3B/SS, 1 OF, rest DH.
PER_TEAM_POSITIONS = [
    POS_P, POS_P, POS_P,
    POS_C,
    POS_1B, POS_2B, POS_3B, POS_SS,
    POS_OF,
]
PER_TEAM_DEFAULT_POS = POS_DH

# Name pools (C4): our own, never harvested from game data. 128 lasts and
# 64 firsts, mixed case like the shipped V20 data (first letter upper, rest
# lower; "Mc" names keep the capital after Mc), last <= 11 chars, first <= 7
# chars, emitted by blob/gen_names.py into rookie_names.inc in identical order.
LAST_NAMES = [
    "Adams", "Allen", "Anderson", "Baker", "Barnes", "Bell", "Bennett",
    "Brooks", "Brown", "Butler", "Campbell", "Carter", "Clark", "Cole",
    "Cook", "Cooper", "Cox", "Crawford", "Cross", "Davis", "Diaz", "Edwards",
    "Evans", "Fisher", "Flores", "Foster", "Fox", "Gray", "Green", "Hall",
    "Harris", "Hart", "Hayes", "Hill", "Howard", "Hughes", "Jackson",
    "James", "Jenkins", "Johnson", "Jones", "Kelly", "King", "Lee", "Lewis",
    "Long", "Marsh", "Martin", "Mason", "May", "Miller", "Mitchell", "Moore",
    "Morris", "Myers", "Nelson", "Parker", "Patel", "Perry", "Peterson",
    "Phillips", "Powell", "Price", "Reed", "Richardson", "Riley", "Rivera",
    "Roberts", "Robinson", "Ross", "Russell", "Sanchez", "Scott", "Shaw",
    "Simmons", "Smith", "Spencer", "Stevens", "Stewart", "Stone", "Sullivan",
    "Taylor", "Thomas", "Thompson", "Torres", "Turner", "Ward", "Watson",
    "Webb", "Wells", "West", "White", "Wilcox", "Williams", "Wilson", "Wood",
    "Wright", "Young", "Arnold", "Beck", "Burke", "Chambers", "Chandler",
    "Curtis", "Dixon", "Duncan", "Ellis", "Erickson", "Freeman", "Garcia",
    "Gibson", "Gordon", "Grant", "Hansen", "Henry", "Hodges", "Holmes",
    "Hopkins", "Hunter", "Johnston", "Lambert", "Larson", "Lloyd", "Lynch",
    "Malone", "McCall", "McRee", "Osborn",
]
FIRST_NAMES = [
    "Aaron", "Adam", "Alan", "Albert", "Andrew", "Anthony", "Arthur",
    "Benny", "Billy", "Bob", "Bobby", "Bruce", "Calvin", "Carl", "Charles",
    "Chris", "Clyde", "Curtis", "Daniel", "Danny", "David", "Dennis", "Don",
    "Donald", "Earl", "Eddie", "Edward", "Edwin", "Elmer", "Ernie", "Eugene",
    "Floyd", "Frank", "Fred", "Gary", "George", "Glen", "Gordon", "Hank",
    "Harold", "Harry", "Herb", "Herman", "Dexter", "Hugh", "Irving",
    "Jack", "James", "Jerry", "Jesse", "Jim", "Jimmy", "Joe", "John",
    "Johnny", "Jose", "Leon", "Lester", "Lou", "Louis", "Luther", "Mark",
    "Marvin", "Norm",
]

# C4 grade cut points: d = draw() & 0xff, 154/230 = 60/30/10 percent.
GRADE_CUT_1 = 154
GRADE_CUT_2 = 230
GRADE_BONUS = [0, 2, 4]

# C4 rating draws: value = 3 + d % 5 + bonus, clamped 1..cap.
RATING_MOD = 5
RATING_BASE = 3
RATING_CAP = 12           # every rating except endurance
RATING_CAP_ENDURANCE = 10

# C1 rating order (notes/M4_CONTRACT.md), as (key, record byte, nibble
# offset: 0 = lo, 4 = hi). Storage per FORMATS.md: batters 74 hi bunt lo
# power, 75 lo H&R, 29 hi speed, 94 hi range lo arm; pitchers 134 hi
# velocity lo control, 135 hi endurance.
BATTER_RATING_ORDER = [
    ("power", 74, 0),
    ("bunt", 74, 4),
    ("hit_run", 75, 0),
    ("speed", 29, 4),
    ("range", 94, 4),
    ("arm", 94, 0),
]
PITCHER_RATING_ORDER = [
    ("control", 134, 0),
    ("velocity", 134, 4),
    ("endurance", 135, 4),
]
CAPS = {"power": 12, "bunt": 12, "hit_run": 12, "speed": 12, "range": 12,
        "arm": 12, "control": 12, "velocity": 12, "endurance": 10}


# ---------------------------------------------------------------------------
# Record field helpers (offsets per FORMATS.md "player record" section).
# ---------------------------------------------------------------------------

OFF_LAST = 0        # 12 bytes last name
OFF_FIRST = 12      # 8 bytes first name
OFF_AGE = 20
OFF_YEAR = 21       # year - 1870
OFF_EXP = 22
OFF_GAMES = 23
OFF_SALARY = 25     # u16
OFF_PORTRAIT = 27   # u16
OFF_HAND = 29       # hi nibble speed; lo nibble: bit3 throws R(1=R, 0=L),
                    # bits2-1 bats (1=R, 2=S, 0=L), bit0 group flag
OFF_EXP_CONSIST = 30  # hi exper / lo consist
OFF_POS = 31        # hi pos2 / lo pos1
OFF_AB_L, OFF_AB_R = 37, 39   # u16 each
OFF_IP = 101        # u16, innings x 10


def _put_u16(rec, off, val):
    rec[off] = val & 0xFF
    rec[off + 1] = (val >> 8) & 0xFF


def _set_nibble_hi(rec, off, val):
    rec[off] = (rec[off] & 0x0F) | ((val & 0x0F) << 4)


def _set_nibble_lo(rec, off, val):
    rec[off] = (rec[off] & 0xF0) | (val & 0x0F)


# ---------------------------------------------------------------------------
# Name pool tables (C4).
# ---------------------------------------------------------------------------

def _name_table(names, width):
    """Render a C4 name pool as the fixed-width NUL-padded byte strings the
    shipped V20 data stores: mixed case ASCII, NUL padding, never spaces."""
    out = []
    for n in names:
        assert len(n) <= width - 1, "name %r too long for a %d-byte field" % (n, width)
        out.append(n.encode("ascii").ljust(width, b"\x00"))
    return out


LAST_TABLE = _name_table(LAST_NAMES, 12)
FIRST_TABLE = _name_table(FIRST_NAMES, 8)


# ---------------------------------------------------------------------------
# The generator (the fill path; the rookie_fill.asm port matches this).
# ---------------------------------------------------------------------------

def default_faces():
    """(30, STOCK group bytes): the table used when no ANMS files apply."""
    grp = bytes(1 if i in STOCK_FACE_GROUP else 0 for i in range(DEFAULT_FACE_N))
    return (DEFAULT_FACE_N, grp)


def load_faces(anms_dir):
    """Face table (n, grp) for the rookie portrait draw.

    anms_dir None -> default_faces(). Otherwise PORTRAIT.ANM's first u16 is c
    and FACEGRP.DAT (one byte per face, stock 30 first) has length L. With
    30 <= L <= 981 and min(L, c) >= 30, n = min(L, c) and grp = the first n
    bytes of FACEGRP.DAT, each masked to bit0. Any other case (a missing or
    short file, L out of range, min < 30) gives the default table.
    """
    if anms_dir is None:
        return default_faces()
    try:
        with open(os.path.join(anms_dir, "PORTRAIT.ANM"), "rb") as f:
            head = f.read(2)
        with open(os.path.join(anms_dir, "FACEGRP.DAT"), "rb") as f:
            data = f.read(FACE_TABLE_MAX + 1)
    except OSError:
        return default_faces()
    if len(head) < 2:
        return default_faces()
    c = head[0] | (head[1] << 8)
    length = len(data)
    if not (DEFAULT_FACE_N <= length <= FACE_TABLE_MAX):
        return default_faces()
    n = min(length, c)
    if n < DEFAULT_FACE_N:
        return default_faces()
    return (n, bytes(b & 1 for b in data[:n]))


class RookieGen:
    """Generates one 143-byte rookie record per make() call."""

    def __init__(self, rng, team_paths=None, faces=None):
        self.rng = rng
        # C4: our own name pools, identical order to the rookie_fill.asm
        # tables (kept there by gen_names.py). No game data is loaded: the
        # fill path works offline. team_paths is accepted and ignored for
        # call-site compatibility. faces = (n, grp) from load_faces; None
        # means the default table.
        self.last_pool = list(LAST_TABLE)
        self.first_pool = list(FIRST_TABLE)
        self.face_n, self.face_grp = faces if faces is not None else default_faces()

    # -- small rng helpers --------------------------------------------------

    def _dbyte(self):
        """d = draw() & 0xff."""
        return self.rng.draw() & 0xFF

    def _rand(self, lo, hi):
        """Inclusive uniform integer in [lo, hi]."""
        return lo + self.rng.draw() % (hi - lo + 1)

    def _weighted(self, choices, weights):
        """Draw from choices by cumulative weight (weights sum to 100 for
        the age pool, so the draw chain matches the asm's % 100 + cmps)."""
        total = sum(weights)
        pick = self.rng.draw() % total
        acc = 0
        for c, w in zip(choices, weights):
            acc += w
            if pick < acc:
                return c
        return choices[-1]

    # -- record pieces ------------------------------------------------------

    def _write_name(self, rec):
        # C4: index = d % 128 (last), d % 64 (first); d = draw() & 0xff.
        last = self.last_pool[self._dbyte() % len(self.last_pool)]
        first = self.first_pool[self._dbyte() % len(self.first_pool)]
        rec[OFF_LAST:OFF_LAST + 12] = last
        rec[OFF_FIRST:OFF_FIRST + 8] = first

    def _write_identity(self, rec, season_year):
        rec[OFF_AGE] = self._weighted(AGE_CHOICES, AGE_WEIGHTS)
        # season_year is already the stored byte (year - 1870), exactly what
        # the dynasty.asm year_scan probe and the blob write.
        rec[OFF_YEAR] = season_year & 0xFF
        rec[OFF_EXP] = 0
        rec[OFF_GAMES] = 0

    def _write_hand(self, rec):
        # lo nibble of byte 29: bit3 throws (1=R, 0=L),
        # bits2-1 bats (1=R, 2=S, 0=L), bit0 group flag (portrait pools).
        throws_r = self.rng.draw() % 100 < THROWS_R_PER_100
        switch = self.rng.draw() % 100 < BATS_S_PER_100
        if throws_r:
            bats = 2 if switch else 1  # S or R
        else:
            bats = 2 if switch else 0  # S or L
        nib = 0
        if throws_r:
            nib |= 0x8
        nib |= (bats & 0x3) << 1
        # group flag bit0: set below with portrait; clear here first.
        rec[OFF_HAND] = (rec[OFF_HAND] & 0xF0) | nib

    def _write_position(self, rec, position):
        # pos1 = actual position, pos2 = 0 (none) for rookies.
        _set_nibble_lo(rec, OFF_POS, position & 0x0F)
        _set_nibble_hi(rec, OFF_POS, 0)

    def _write_portrait(self, rec):
        face = self.rng.draw() % self.face_n
        _put_u16(rec, OFF_PORTRAIT, face)
        flag = self.face_grp[face] & 1
        if flag:
            rec[OFF_HAND] |= 0x01
        else:
            rec[OFF_HAND] &= 0xFE

    def _write_exper_consist(self, rec):
        # exper and consist: d % 4 each (as the WIP blob).
        exper = self.rng.draw() % 4
        consist = self.rng.draw() % 4
        _set_nibble_hi(rec, OFF_EXP_CONSIST, exper)
        _set_nibble_lo(rec, OFF_EXP_CONSIST, consist)

    # -- stat lines (constants as the WIP blob) -------------------------------

    def _write_stat_constants(self, rec, position):
        """Stat-line bytes the C4 draw order does not cover keep the WIP
        blob's fixed values."""
        if position == POS_P:
            # IP 200; pitch4 type 4 (135 lo); personality block 77s; byte
            # 140 = 7. Ratings 134 hi/lo and 135 hi are drawn later.
            _put_u16(rec, OFF_IP, 200)
            rec[135] |= 0x04
            rec[136] = 0x77
            rec[137] = 0x77
            rec[138] = 0x77
            rec[139] = 0x77
            rec[140] = 7
            # off-role batting, the stock pitcher pattern: power, bunt and
            # hit_run 1; speed, range and arm 7.
            rec[74] = 0x11
            rec[75] |= 0x01
            rec[29] |= 0x70
            rec[94] = 0x77
        else:
            # 75 hi streak 7 (letter A); 76 hi day-night 7, lo clutch 8.
            rec[75] |= 0x70
            rec[76] = 0x78
            # off-role pitching, the stock non-pitcher pattern: control 1,
            # velocity 3, endurance 1.
            rec[134] = 0x31
            rec[135] |= 0x10
            # AB 40 split by bats code (hand nibble already drawn).
            bats = (rec[OFF_HAND] >> 1) & 0x3
            if bats == 2:    # switch
                left, right = 20, 20
            elif bats == 0:  # left
                left, right = 34, 6
            else:            # right
                left, right = 4, 36
            _put_u16(rec, OFF_AB_L, left)
            _put_u16(rec, OFF_AB_R, right)

    # -- C4 rating draws ----------------------------------------------------

    def _grade(self):
        d = self._dbyte()
        if d < GRADE_CUT_1:
            return 0
        if d < GRADE_CUT_2:
            return 1
        return 2

    def _c4_rating(self, bonus, cap):
        v = RATING_BASE + (self._dbyte() % RATING_MOD) + bonus
        return max(1, min(cap, v))

    def _write_ratings(self, rec, position):
        """C4 graded ratings: one grade draw, then one draw per rating in
        the C1 order, written into the FORMATS.md nibbles."""
        order = PITCHER_RATING_ORDER if position == POS_P else BATTER_RATING_ORDER
        bonus = GRADE_BONUS[self._grade()]
        for key, off, shift in order:
            v = self._c4_rating(bonus, CAPS[key])
            if shift == 4:
                _set_nibble_hi(rec, off, v)
            else:
                _set_nibble_lo(rec, off, v)

    def _write_salary(self, rec, position):
        sal = SALARY_PITCHER if position == POS_P else SALARY_BATTER
        _put_u16(rec, OFF_SALARY, sal)

    # -- main entry -----------------------------------------------------------

    def make(self, position, season_year):
        rec = bytearray(RECORD_LEN)
        self._write_name(rec)
        self._write_identity(rec, season_year)
        self._write_hand(rec)
        self._write_position(rec, position)
        self._write_portrait(rec)
        self._write_exper_consist(rec)
        self._write_stat_constants(rec, position)
        self._write_ratings(rec, position)
        self._write_salary(rec, position)
        return rec


# ---------------------------------------------------------------------------
# Summary main.
# ---------------------------------------------------------------------------

def main():
    seed = 7
    season_year = 1920
    positions = list(PER_TEAM_POSITIONS)
    rng = Rng(seed)
    gen = RookieGen(rng)
    for i, pos in enumerate(positions):
        rec = gen.make(pos, season_year)
        last = rec[0:12].rstrip(b"\x00").decode("ascii")
        first = rec[12:20].rstrip(b"\x00").decode("ascii")
        print("rookie #%-2d %-12s %-8s age=%d pos=%-2d sal=%d pow=%d"
              % (i, last, first, rec[OFF_AGE], pos,
                 rec[OFF_SALARY] | (rec[OFF_SALARY + 1] << 8),
                 rec[74] & 0x0F))


if __name__ == "__main__":
    main()
