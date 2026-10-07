#!/usr/bin/env python3
"""Rookie-class generator for the TLRB2 M4 dynasty mod.

Builds 143-byte V20 player records for rookie-class callups, calibrated
against the weakest third of the real m3_end league (season-half records
40..79 of the shipped CLASSIC V20 files).

Pipeline per rookie (see RookieGen.make):
  1. blank record (all zeros, matches UTIL 5000:e89d init_blank_player_record)
  2. name from pools harvested from the real league's own player names
  3. age / year_off / exp / games
  4. position code (caller supplied)
  5. plausible season stat line per position
  6. ratings computed by tools/ratings.py, nibbles written back exactly as
     shipped records store them
  7. salary via ratings.salary, clamped
  8. portrait + group flag
  9. throws/bats nibble

Determinism: all randomness flows through the Rng class from
tools/m4/rollover.py (xorshift16). Same seed + same ordered inputs gives
byte-identical output.
"""

import os
import sys

# Make the existing tools importable regardless of cwd.
_TOOLS = "/home/will/tlrb2/tools"
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import ratings  # noqa: E402  (proven stats->ratings + salary calculators)
from m4.rollover import Rng  # noqa: E402  (xorshift16 rng)
import v20  # noqa: E402  (Team.load / Player / F field offsets)

# ---------------------------------------------------------------------------
# Constants block: every magic threshold lives here, calibrated against the
# real m3_end CLASSIC V20 data (28 teams x 80 records x 143 bytes).
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

# Age distribution: 18..23 weighted toward 20-22 (weights sum arbitrary).
AGE_CHOICES = [18, 19, 20, 21, 22, 23]
AGE_WEIGHTS = [4, 10, 24, 26, 22, 14]

# Throws/bats distribution (per 100 draws): mostly R hitters, some L, few S.
# throws: 72 R / 28 L ; bats among R-throwers: 84 R / 16 S ;
# bats among L-throwers: 88 L / 12 S.
THROWS_R_PER_100 = 72
BATS_S_PER_100 = 16

# Portrait: generic face index 0..29; group flag byte29 bit0 per FORMATS.md
# line 264 (776e table): flag 0 for faces 0..14, flag 1 for faces 15..29.
PORTRAIT_MAX = 29
PORTRAIT_FLAG_SPLIT = 15  # faces >= this carry group flag bit set

# Salary clamp (task spec).
SALARY_MIN = 109
SALARY_MAX = 9999

# Calibration band: rookies are drawn from the weakest third of the real
# league by position (season-half stat lines, records 40..79). Stat draws
# are scaled around that band with this loose multiplier bound; the test
# suite asserts no generated stat exceeds band_max * STAT_SANITY_MULT.
STAT_SANITY_MULT = 3.0

# Position mix per team for gen_class (task spec): 3 P, 1 C, 1 each of
# 1B/2B/3B/SS, 1 OF (code 10), rest DH.
PER_TEAM_POSITIONS = [
    POS_P, POS_P, POS_P,
    POS_C,
    POS_1B, POS_2B, POS_3B, POS_SS,
    POS_OF,
]
PER_TEAM_DEFAULT_POS = POS_DH

# Name pools: harvested from real records at import of gen_class; these
# fallbacks are only used if no real data can be loaded (should not happen
# on this box, but keeps the module importable for offline unit tests).
FALLBACK_LAST = [
    "SMITH", "JOHNSON", "BROWN", "DAVIS", "MILLER", "WILSON", "MOORE",
    "TAYLOR", "ANDERSON", "THOMAS", "JACKSON", "WHITE", "HARRIS", "MARTIN",
    "THOMPSON", "YOUNG", "WALKER", "HALL", "ALLEN", "KING", "WRIGHT",
    "SCOTT", "GREEN", "BAKER", "ADAMS", "NELSON", "HILL", "CAMPBELL",
]
FALLBACK_FIRST = [
    "JAMES", "JOHN", "ROBERT", "MICHAEL", "WILLIAM", "DAVID", "RICHARD",
    "JOSEPH", "THOMAS", "CHARLES", "GEORGE", "FRANK", "HENRY", "EDWARD",
    "HARRY", "RALPH", "FRED", "WALTER", "ARTHUR", "CARL", "SAM", "JOE",
]

# Real-data source for calibration (m3_end snapshot).
DEFAULT_SNAP_GLOB = "/mnt/nvme/tlrb2/snaps/m3_end/TEAMS/CLASSIC/*.V20"


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
OFF_HAND = 29       # hi nibble speed; lo nibble: bit3 throws R(0=L),
                    # bits2-1 bats (1=R, 2=S, 0=L), bit0 group flag
OFF_EXP_CONSIST = 30  # hi exper / lo consist
OFF_POS = 31        # hi pos2 / lo pos1
# Batter stats
OFF_R, OFF_RBI, OFF_SH, OFF_SB, OFF_CS = 32, 33, 34, 35, 36
OFF_AB_L, OFF_AB_R = 37, 39   # u16 each
OFF_H_L, OFF_H_R = 41, 43     # u16 each
OFF_D_L, OFF_D_R = 45, 47     # u16 each
OFF_T_L, OFF_T_R = 49, 50     # u8 each
OFF_HR_L, OFF_HR_R = 51, 52   # u8 each
OFF_BB_L, OFF_BB_R = 53, 54   # u8 each
OFF_SO_L, OFF_SO_R = 57, 58   # u8 each
# Pitcher stats
OFF_IP = 101        # u16, innings x 10
OFF_P_H = 111       # u16
OFF_P_BB = 121      # u16
OFF_P_SO = 125      # u16


def _put_u16(rec, off, val):
    rec[off] = val & 0xFF
    rec[off + 1] = (val >> 8) & 0xFF


def _get_u16(rec, off):
    return rec[off] | (rec[off + 1] << 8)


def _set_nibble_hi(rec, off, val):
    rec[off] = (rec[off] & 0x0F) | ((val & 0x0F) << 4)


def _set_nibble_lo(rec, off, val):
    rec[off] = (rec[off] & 0xF0) | (val & 0x0F)


# ---------------------------------------------------------------------------
# Name pool harvesting from the real league.
# ---------------------------------------------------------------------------

def _clean_name(raw):
    """Decode a name field, strip padding, keep A-Z and space only."""
    try:
        s = raw.decode("latin-1")
    except AttributeError:
        s = str(raw)
    except Exception:
        return ""
    out = []
    for ch in s:
        if ch == "\x00":
            break
        if ch.isalpha():
            out.append(ch.upper())
        elif ch == " ":
            out.append(" ")
    return "".join(out).strip()


def harvest_name_pool(team_paths):
    """Return (last_names, first_names) lists from real records.

    v20.Player exposes the decoded fields directly: p['last'] (12-char
    field), p['first'] (8-char field).
    """
    lasts, firsts = [], []
    seen_last, seen_first = set(), set()
    for path in team_paths:
        try:
            team = v20.Team.load(path)
        except Exception:
            continue
        for p in team.players:
            ln = _clean_name(p['last'])
            fn = _clean_name(p['first'])
            if ln and ln not in seen_last:
                seen_last.add(ln)
                lasts.append(ln)
            if fn and fn not in seen_first:
                seen_first.add(fn)
                firsts.append(fn)
    if not lasts:
        lasts = list(FALLBACK_LAST)
    if not firsts:
        firsts = list(FALLBACK_FIRST)
    return lasts, firsts


def _find_name_offsets():
    """Locate the last/first name field keys in v20.F defensively."""
    last_key = first_key = None
    for k in ("last", "lastname", "name_last", "lname"):
        if k in v20.F:
            last_key = k
            break
    for k in ("first", "firstname", "name_first", "fname"):
        if k in v20.F:
            first_key = k
            break
    if last_key is None or first_key is None:
        # Fall back to the FORMATS.md fixed offsets.
        return ("raw", 0, 12), ("raw", 12, 8)
    off_l, off_f = v20.F[last_key], v20.F[first_key]
    return ("raw", off_l, 12), ("raw", off_f, 8)


# ---------------------------------------------------------------------------
# Calibration data: weakest-third stat bands from the real league.
# ---------------------------------------------------------------------------

def _record_bytes(player):
    raw = getattr(player, "raw", None)
    if raw is None:
        raw = getattr(player, "data", None)
    if raw is None:
        raise ValueError("player object has no raw record bytes")
    return bytes(raw)


def _batter_stats_from(rec):
    """Pull a batter's combined L+R season stat line from a record."""
    ab = _get_u16(rec, OFF_AB_L) + _get_u16(rec, OFF_AB_R)
    h = _get_u16(rec, OFF_H_L) + _get_u16(rec, OFF_H_R)
    d = _get_u16(rec, OFF_D_L) + _get_u16(rec, OFF_D_R)
    t = rec[OFF_T_L] + rec[OFF_T_R]
    hr = rec[OFF_HR_L] + rec[OFF_HR_R]
    bb = rec[OFF_BB_L] + rec[OFF_BB_R]
    so = rec[OFF_SO_L] + rec[OFF_SO_R]
    return {
        "ab": ab, "h": h, "2b": d, "3b": t, "hr": hr,
        "bb": bb, "so": so, "r": rec[OFF_R], "rbi": rec[OFF_RBI],
        "sb": rec[OFF_SB], "cs": rec[OFF_CS], "sh": rec[OFF_SH],
    }


def _pitcher_stats_from(rec):
    return {
        "ip": _get_u16(rec, OFF_IP),        # x10
        "h": _get_u16(rec, OFF_P_H),
        "bb": _get_u16(rec, OFF_P_BB),
        "so": _get_u16(rec, OFF_P_SO),
    }


def _pos_code(rec):
    return rec[31] & 0x0F  # pos1 in lo nibble per FORMATS.md


def calibrate(team_paths):
    """Compute weakest-third stat bands per position group.

    Returns dict with keys "batter" and "pitcher"; each maps stat name to
    (low, high) observed across the weakest third of players (by a simple
    overall production proxy) at that group, using season-half records.
    """
    batter_lines = []
    pitcher_lines = []
    for path in team_paths:
        try:
            team = v20.Team.load(path)
        except Exception:
            continue
        players = team.players
        for idx in range(SEASON_HALF_START,
                         min(SEASON_HALF_START + SEASON_HALF_COUNT,
                             len(players))):
            try:
                rec = _record_bytes(players[idx])
            except Exception:
                continue
            if len(rec) < RECORD_LEN:
                continue
            pos = _pos_code(rec)
            if pos == POS_P:
                pitcher_lines.append(_pitcher_stats_from(rec))
            else:
                batter_lines.append((pos, _batter_stats_from(rec)))

    bands = {}

    # Batter band: rank by AB (playing-time proxy), take weakest third,
    # then report min/max of each stat within that third.
    if batter_lines:
        batter_lines.sort(key=lambda t: t[1]["ab"])
        cut = max(1, len(batter_lines) // 3)
        weak = [s for _, s in batter_lines[:cut]]
        keys = weak[0].keys()
        bands["batter"] = {
            k: (min(w[k] for w in weak), max(w[k] for w in weak))
            for k in keys
        }
    else:
        bands["batter"] = None

    if pitcher_lines:
        pitcher_lines.sort(key=lambda s: s["ip"])
        cut = max(1, len(pitcher_lines) // 3)
        weak = pitcher_lines[:cut]
        keys = weak[0].keys()
        bands["pitcher"] = {
            k: (min(w[k] for w in weak), max(w[k] for w in weak))
            for k in keys
        }
    else:
        bands["pitcher"] = None

    # Salary band: bottom half of all salaries in the league (rookies should
    # land inside the league's cheap band).
    salaries = []
    for path in team_paths:
        try:
            team = v20.Team.load(path)
        except Exception:
            continue
        for p in team.players[:ROSTER_RECORDS]:
            try:
                rec = _record_bytes(p)
            except Exception:
                continue
            if len(rec) >= RECORD_LEN:
                salaries.append(_get_u16(rec, OFF_SALARY))
    if salaries:
        salaries.sort()
        half = salaries[:len(salaries) // 2]
        bands["salary_bottom_half"] = (min(half), max(half))
    else:
        bands["salary_bottom_half"] = (SALARY_MIN, 3000)

    return bands


# ---------------------------------------------------------------------------
# The generator.
# ---------------------------------------------------------------------------

class RookieGen:
    """Generates one 143-byte rookie record per make() call."""

    def __init__(self, rng, team_paths=None):
        self.rng = rng
        paths = team_paths
        if paths is None:
            import glob
            paths = sorted(glob.glob(DEFAULT_SNAP_GLOB))
        self.last_pool, self.first_pool = harvest_name_pool(paths)
        self.bands = calibrate(paths)

    # -- small rng helpers --------------------------------------------------

    def _below(self, n):
        """Uniform integer in [0, n) from the xorshift16 draw (rollover.Rng
        exposes draw() only)."""
        return self.rng.draw() % n

    def _rand(self, lo, hi):
        """Inclusive uniform integer in [lo, hi]."""
        return lo + self._below(hi - lo + 1)

    def _weighted(self, choices, weights):
        total = sum(weights)
        pick = self._below(total)
        acc = 0
        for c, w in zip(choices, weights):
            acc += w
            if pick < acc:
                return c
        return choices[-1]

    def _band_draw(self, group, key, lo_floor=0):
        """Draw a stat value around the calibrated weakest-third band.

        The draw is uniform within [max(lo_floor, lo), hi] of the band; if
        the band is missing we fall back to a small token value.
        """
        band = self.bands.get(group)
        if band and key in band:
            lo, hi = band[key]
            lo = max(lo_floor, lo)
            if hi < lo:
                hi = lo
            return self._rand(lo, hi)
        return lo_floor

    # -- record pieces ------------------------------------------------------

    def _write_name(self, rec):
        last = self.last_pool[self._below(len(self.last_pool))]
        first = self.first_pool[self._below(len(self.first_pool))]
        # Keep within field sizes; shipped names are uppercase A-Z and space.
        last = "".join(ch for ch in last.upper() if ch.isalpha())[:12]
        first = "".join(ch for ch in first.upper() if ch.isalpha())[:8]
        if not last:
            last = "ROOKIE"
        if not first:
            first = "ROOK"
        # Padding: shipped records pad with spaces up to the field width and
        # the remainder of the field stays zero (verified against real
        # records: name chars, then 0x20 filler to field end, then 0x00).
        field_l = last.ljust(12, " ")
        field_f = first.ljust(8, " ")
        rec[OFF_LAST:OFF_LAST + 12] = field_l.encode("latin-1")
        rec[OFF_FIRST:OFF_FIRST + 8] = field_f.encode("latin-1")

    def _write_identity(self, rec, season_year):
        age = self._weighted(AGE_CHOICES, AGE_WEIGHTS)
        rec[OFF_AGE] = age
        rec[OFF_YEAR] = (season_year - 1870) & 0xFF
        rec[OFF_EXP] = 0
        rec[OFF_GAMES] = 0

    def _write_position(self, rec, position):
        # pos1 = actual position, pos2 = 0 (none) for rookies.
        _set_nibble_lo(rec, OFF_POS, position & 0x0F)
        _set_nibble_hi(rec, OFF_POS, 0)

    def _write_hand(self, rec):
        # lo nibble of byte 29: bit3 throws (1=R, 0=L),
        # bits2-1 bats (1=R, 2=S, 0=L), bit0 group flag (portrait pools).
        throws_r = self._below(100) < THROWS_R_PER_100
        switch = self._below(100) < BATS_S_PER_100
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

    def _write_portrait(self, rec):
        face = self._below(PORTRAIT_MAX + 1)
        _put_u16(rec, OFF_PORTRAIT, face)
        flag = 1 if face >= PORTRAIT_FLAG_SPLIT else 0
        if flag:
            rec[OFF_HAND] |= 0x01
        else:
            rec[OFF_HAND] &= 0xFE

    def _write_exper_consist(self, rec):
        # Rookies: exper and consist nibbles low (task spec).
        exper = self._rand(0, 3)
        consist = self._rand(0, 3)
        _set_nibble_hi(rec, OFF_EXP_CONSIST, exper)
        _set_nibble_lo(rec, OFF_EXP_CONSIST, consist)

    # -- stat lines ----------------------------------------------------------

    def _batter_line(self, rec, position):
        """Fill batter stat fields from the calibrated weak band."""
        ab = self._band_draw("batter", "ab", lo_floor=40)
        # Split AB between L and R sides. Switch hitters split; single-sided
        # hitters put nearly everything on their primary side.
        hand_nib = rec[OFF_HAND] & 0x0F
        bats = (hand_nib >> 1) & 0x3
        if bats == 2:  # switch
            left_ab = ab // 2
        elif bats == 0:  # left
            left_ab = int(ab * 0.85)
        else:  # right
            left_ab = ab // 10
        right_ab = ab - left_ab

        # Rate stats drawn as counts scaled off the band's per-AB feel.
        # We draw counts directly from the band (which is already per-season
        # counts for weak players) but keep them consistent with AB.
        def _count(key, cap_per_ab):
            v = self._band_draw("batter", key)
            cap = int(ab * cap_per_ab) + 1
            return min(v, cap)

        h = _count("h", 0.40)
        d = _count("2b", 0.10)
        t = _count("3b", 0.03)
        hr = _count("hr", 0.09)
        bb = _count("bb", 0.20)
        so = _count("so", 0.35)
        r = _count("r", 0.15)
        rbi = _count("rbi", 0.15)
        sb = _count("sb", 0.05)
        cs = _count("cs", 0.03)
        sh = _count("sh", 0.03)

        # Ensure hits <= AB and doubles+triples+HR <= hits.
        h = min(h, ab)
        d = min(d, h)
        t = min(t, h - d)
        hr = min(hr, h - d - t)

        # Distribute across L/R sides proportionally to AB split.
        def _split(total):
            l = total * left_ab // ab if ab else 0
            return l, total - l

        hl, hr_ = _split(h)
        dl, dr = _split(d)
        tl, tr = _split(t)
        hrl, hrr = _split(hr)
        bbl, bbr = _split(bb)
        sol, sor = _split(so)

        _put_u16(rec, OFF_AB_L, left_ab)
        _put_u16(rec, OFF_AB_R, right_ab)
        _put_u16(rec, OFF_H_L, hl)
        _put_u16(rec, OFF_H_R, hr_)
        _put_u16(rec, OFF_D_L, dl)
        _put_u16(rec, OFF_D_R, dr)
        rec[OFF_T_L] = tl
        rec[OFF_T_R] = tr
        rec[OFF_HR_L] = hrl
        rec[OFF_HR_R] = hrr
        rec[OFF_BB_L] = bbl
        rec[OFF_BB_R] = bbr
        rec[OFF_SO_L] = sol
        rec[OFF_SO_R] = sor
        rec[OFF_R] = r
        rec[OFF_RBI] = rbi
        rec[OFF_SB] = sb
        rec[OFF_CS] = cs
        rec[OFF_SH] = sh

    def _pitcher_line(self, rec):
        """Fill pitcher stat fields from the calibrated weak band."""
        ip = self._band_draw("pitcher", "ip", lo_floor=200)  # stored x10
        h = self._band_draw("pitcher", "h")
        bb = self._band_draw("pitcher", "bb")
        so = self._band_draw("pitcher", "so")
        # Keep counts plausible vs innings pitched (ip is x10, so real IP
        # is ip/10; hits allowed per 9 IP under ~2.5x IP is generous enough).
        real_ip = max(1, ip // 10)
        h = min(h, real_ip * 25 // 10)
        bb = min(bb, real_ip * 10 // 10)
        so = min(so, real_ip * 15 // 10)
        _put_u16(rec, OFF_IP, ip)
        _put_u16(rec, OFF_P_H, h)
        _put_u16(rec, OFF_P_BB, bb)
        _put_u16(rec, OFF_P_SO, so)

    # -- ratings + salary -----------------------------------------------------

    def _write_ratings(self, rec, position):
        """Compute ratings with ratings.py and store them where the game
        reads them (FORMATS.md record layout, verified against shipped
        records): batters 74 hi bunt / lo power, 75 hi streak / lo H&R,
        76 hi day-night / lo clutch, 94 hi range / lo arm; pitchers 134 hi
        velocity / lo control, 135 hi endurance / lo pitch4 type, 136..140
        the personality block. Non-derived nibbles get the shipped modal
        defaults (streak 7 = letter A, day/night 7 = letter G, clutch 8,
        pitcher personality 7s, pitch4 = 4 slider). Bytes 59..61 are the
        per-half live-nibble area, NOT ratings; they stay 0 here."""
        if position == POS_P:
            vel = ratings.velocity(rec)
            ctl = ratings.control(rec)
            endu = ratings.endurance(rec)
            _set_nibble_hi(rec, 134, vel)
            _set_nibble_lo(rec, 134, ctl)
            _set_nibble_hi(rec, 135, endu)
            rec[135] = (rec[135] & 0xF0) | 4      # pitch4: slider (modal)
            # Pitcher class is computed by the game from stored endurance
            # + usage (ratings.pitcher_class reads 135 hi); nothing to store.
            rec[136] = 0x77
            rec[137] = 0x77
            rec[138] = 0x77
            rec[139] = 0x77
            rec[140] = 7
        else:
            pw = ratings.power(rec)
            hr_ = ratings.hit_and_run(rec)
            bt = ratings.bunt(rec)
            rg = ratings.rng(rec)
            am = ratings.arm(rec)
            _set_nibble_hi(rec, 74, bt)
            _set_nibble_lo(rec, 74, pw)
            _set_nibble_hi(rec, 75, 7)             # streak: letter A (modal)
            _set_nibble_lo(rec, 75, hr_)
            _set_nibble_hi(rec, 76, 7)             # day/night: letter G
            _set_nibble_lo(rec, 76, 8)             # clutch: 8 (modal)
            _set_nibble_hi(rec, 94, rg)
            _set_nibble_lo(rec, 94, am)

    def _write_salary(self, rec):
        sal = ratings.salary(rec)
        sal = max(SALARY_MIN, min(SALARY_MAX, int(sal)))
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
        if position == POS_P:
            self._pitcher_line(rec)
        else:
            self._batter_line(rec, position)
        self._write_ratings(rec, position)
        self._write_salary(rec)
        return rec


# ---------------------------------------------------------------------------
# Class generation across teams.
# ---------------------------------------------------------------------------

def gen_class(team_paths, season_year, seed, per_team=5):
    """Deterministically generate a rookie class.

    Returns dict mapping team path -> list of per_team rookie records
    (bytes). Position mix per team: 3 P, 1 C, 1 each 1B/2B/3B/SS, 1 OF
    (code 10), rest DH.
    """
    positions = list(PER_TEAM_POSITIONS)
    while len(positions) < per_team:
        positions.append(PER_TEAM_DEFAULT_POS)
    positions = positions[:per_team]

    rng = Rng(seed)
    gen = RookieGen(rng, team_paths=team_paths)
    out = {}
    for path in team_paths:
        rookies = []
        for pos in positions:
            rec = gen.make(pos, season_year)
            rookies.append(bytes(rec))
        out[path] = rookies
    return out


# ---------------------------------------------------------------------------
# Summary main.
# ---------------------------------------------------------------------------

def _rating_summary(rec, position):
    if position == POS_P:
        return {
            "vel": ratings.velocity(rec),
            "ctl": ratings.control(rec),
            "end": ratings.endurance(rec),
            "cls": ratings.pitcher_class(rec),
        }
    return {
        "pow": ratings.power(rec),
        "spd": ratings.speed(rec),
        "hr": ratings.hit_and_run(rec),
        "bnt": ratings.bunt(rec),
        "rng": ratings.rng(rec),
        "arm": ratings.arm(rec),
    }


def main():
    import glob
    paths = sorted(glob.glob(DEFAULT_SNAP_GLOB))
    season_year = 1920
    seed = 7
    per_team = 5
    classes = gen_class(paths, season_year, seed, per_team=per_team)
    total = 0
    salaries = []
    for path in sorted(classes):
        team = os.path.basename(path)
        for i, rec in enumerate(classes[path]):
            pos = rec[31] & 0x0F
            last = rec[0:12].decode("latin-1").rstrip(" \x00")
            first = rec[12:20].decode("latin-1").rstrip(" \x00")
            age = rec[OFF_AGE]
            sal = _get_u16(rec, OFF_SALARY)
            ratings_s = _rating_summary(rec, pos)
            rstr = " ".join("%s=%d" % (k, v) for k, v in ratings_s.items())
            print("%-12s #%-2d %-12s %-8s age=%d pos=%-2d sal=%4d %s"
                  % (team, i, last, first, age, pos, sal, rstr))
            total += 1
            salaries.append(sal)
    if salaries:
        print("total=%d mean_salary=%.1f min=%d max=%d"
              % (total, sum(salaries) / len(salaries),
                 min(salaries), max(salaries)))


if __name__ == "__main__":
    main()
