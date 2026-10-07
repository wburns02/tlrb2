"""TLRB2 M4: post-rollover rookie fill at team level (Python reference).

After a rollover, retired players have byte 0 == 0 in BOTH halves (roster
records 0..39 and season records 40..79).  Each vacated slot gets a freshly
generated rookie written into both halves:

  roster half  (records 0..39)  = the new rookie record as generated
  season half  (records 40..79) = the same record with all season stat
                                  bytes zeroed (identity fields kept)

Position choice per vacancy follows a priority ladder so the team keeps a
sane structure: pitchers to >= 8, catchers to >= 2, each infield code
2..5 to >= 1, outfielders to >= 4, then DH (code 9) for any remainder.

Counts are taken from the roster half AFTER retirement (byte 0 != 0),
using the primary position in the low nibble of byte 31.
"""

import os
import sys

_TOOLS = "/home/will/tlrb2/tools"
_M4 = "/home/will/tlrb2/tools/m4"
for _p in (_TOOLS, _M4):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rollover  # noqa: E402
import v20  # noqa: E402

# ---------------------------------------------------------------------------
# Season stat byte offsets, taken from /home/will/tlrb2/notes/FORMATS.md
# ("player record" section).  Offsets within a 143-byte record.
# ---------------------------------------------------------------------------

# Batter season stats (FORMATS.md player record):
#   games u8 at 23; R,RBI,SH,SB,CS u8 at 32..36; AB/H u16 pairs at 37..40;
#   2B u16 pair at 41..42; 3B/HR/BB/SO u8 pairs at 49..58.
_BATTER_STAT_OFFSETS = (
    23,                          # G
    32, 33, 34, 35, 36,          # R, RBI, SH, SB, CS
    37, 38,                      # AB   (u16)
    39, 40,                      # H    (u16)
    41, 42,                      # 2B   (u16)
    49, 50,                      # 3B, 3B (u8 pair)
    51, 52,                      # HR, HR (u8 pair)
    53, 54,                      # BB, BB (u8 pair)
    55, 56,                      # SO, SO (u8 pair)
    57, 58,                      # tail of the 49..58 stat region
)

# Pitcher season stats (FORMATS.md): games u8 at 23; IPx10 u16 at 101..102;
# H u16 at 111..112; BB u16 at 121..122; SO u16 at 125..126.
_PITCHER_STAT_OFFSETS = (
    23,
    101, 102,                    # IP x10 (u16)
    111, 112,                    # H (u16)
    121, 122,                    # BB (u16)
    125, 126,                    # SO (u16)
)

# Pitcher W-L-streak season bytes near 60..70 (FORMATS.md pitcher block).
_PITCHER_WL_OFFSETS = (61, 62, 63)

# Union of every season stat byte zeroed in the season half.  Identity
# fields (name, age, year, exp, salary, portrait, ratings, throws/bats)
# live outside these offsets, so zeroing the union for every rookie is safe.
# Bytes 59..70 are NOT zeroed: real records carry live per-half nibbles
# there in BOTH halves (verified against m3_end batters and pitchers), so
# they are not proven season stats. Stock Start New Season applies its own
# zeroing on top when the user starts the next season; we only zero the
# offsets proven to be season stats.
_SEASON_STAT_OFFSETS = frozenset(
    _BATTER_STAT_OFFSETS + _PITCHER_STAT_OFFSETS
)

ROSTER_HALF_BASE = 0    # records 0..39
SEASON_HALF_BASE = 40   # records 40..79
RECORD_SIZE = 143

# Primary position codes (byte 31 low nibble).
POS_PITCHER = 0
POS_CATCHER = 1
POS_INFIELD_MIN = 2
POS_INFIELD_MAX = 5
POS_DH = 9
POS_OUTFIELD = 10

# Priority targets.
TARGET_PITCHERS = 8
TARGET_CATCHERS = 2
TARGET_INFIELD_EACH = 1
TARGET_OUTFIELD = 4


def _pos_code(raw):
    """Primary position: low nibble of byte 31."""
    return raw[31] & 0x0F


def _is_active(raw):
    return raw[0] != 0


def _count_active_by_position(team):
    """Count active roster-half players by primary position code."""
    counts = {}
    for i in range(40):
        raw = team.players[i].raw
        if _is_active(raw):
            code = _pos_code(raw)
            counts[code] = counts.get(code, 0) + 1
    return counts


def _priority_order(counts, num_vacancies):
    """Return the list of position codes to assign, in fill order."""
    order = []
    counts = dict(counts)

    def take(code, target):
        while counts.get(code, 0) < target and len(order) < num_vacancies:
            order.append(code)
            counts[code] = counts.get(code, 0) + 1

    take(POS_PITCHER, TARGET_PITCHERS)
    take(POS_CATCHER, TARGET_CATCHERS)
    for code in range(POS_INFIELD_MIN, POS_INFIELD_MAX + 1):
        take(code, TARGET_INFIELD_EACH)
    take(POS_OUTFIELD, TARGET_OUTFIELD)
    # Any remaining vacancies become DH.
    while len(order) < num_vacancies:
        order.append(POS_DH)
    return order


def _zero_season_stats(rec):
    """Zero all season stat bytes in a 143-byte record copy."""
    for off in _SEASON_STAT_OFFSETS:
        rec[off] = 0


def _check_vacant(team, index):
    """Raise ValueError if slot `index` is not a true vacancy."""
    raw = team.players[index].raw
    if _is_active(raw):
        raise ValueError(
            "slot %d is active (byte 0 != 0); refusing to overwrite" % index
        )


def fill_team(team_in_path, team_out_path, season_year, rng, rookie_gen):
    """Fill vacated roster slots with generated rookies.

    A slot is vacated when byte 0 == 0 in the roster half (records 0..39).
    Each vacancy gets a rookie in the roster half and a stat-zeroed copy in
    the season half (records 40..79).

    Returns {'vacancies': [indices], 'positions': [codes]}.
    """
    team = v20.Team.load(team_in_path)

    vacancies = [i for i in range(40) if not _is_active(team.players[i].raw)]
    if not vacancies:
        team.save(team_out_path)
        return {"vacancies": [], "positions": []}

    # Guard: a vacancy must also be empty in the season half (post-rollover
    # retirees are zeroed in both halves).  Refuse to touch anything else.
    for i in vacancies:
        _check_vacant(team, i)
        season_raw = team.players[SEASON_HALF_BASE + i].raw
        if _is_active(season_raw):
            raise ValueError(
                "slot %d has an active season-half record; not a rollover "
                "vacancy" % i
            )

    counts = _count_active_by_position(team)
    positions = _priority_order(counts, len(vacancies))

    for index, code in zip(vacancies, positions):
        rec = rookie_gen.make(code, season_year)
        rookie = bytearray(rec)
        # Force the requested primary position (low nibble of byte 31),
        # preserving any high-nibble flags the generator set.
        rookie[31] = (rookie[31] & 0xF0) | (code & 0x0F)

        season_copy = bytearray(rookie)
        _zero_season_stats(season_copy)

        team.players[index].raw = bytes(rookie)
        team.players[SEASON_HALF_BASE + index].raw = bytes(season_copy)

    team.save(team_out_path)
    return {"vacancies": vacancies, "positions": positions}


def fill_league(in_dir, out_dir, season_year, seed):
    """Fill every *.V20 team in in_dir, writing results to out_dir.

    One RookieGen and one rollover.Rng(seed) are created once and shared
    across the whole league.

    Returns {team_basename: {'vacancies': [...], 'positions': [...]}}.
    """
    from rookies import RookieGen

    rng = rollover.Rng(seed)
    rookie_gen = RookieGen(rng, [])

    names = sorted(
        n for n in os.listdir(in_dir) if n.upper().endswith(".V20")
    )
    report = {}
    for name in names:
        in_path = os.path.join(in_dir, name)
        out_path = os.path.join(out_dir, name)
        report[name] = fill_team(
            in_path, out_path, season_year, rng, rookie_gen
        )
    return report


def ensure_minimum(team_in_path, team_out_path, season_year, rng, rookie_gen):
    """Safety net: top a thin roster up to 35 active records.

    Usable even without a rollover.  Only slots that are inactive in BOTH
    halves are filled (so an active season-half record is never clobbered).
    Position priorities are the same as fill_team.

    Returns {'vacancies': [indices], 'positions': [codes]}.
    """
    team = v20.Team.load(team_in_path)

    active = sum(1 for i in range(40) if _is_active(team.players[i].raw))
    if active >= 35:
        team.save(team_out_path)
        return {"vacancies": [], "positions": []}

    need = 35 - active
    # Candidate slots: inactive in both halves, lowest index first.
    candidates = []
    for i in range(40):
        if not _is_active(team.players[i].raw) and not _is_active(
            team.players[SEASON_HALF_BASE + i].raw
        ):
            candidates.append(i)
        if len(candidates) == need:
            break
    if len(candidates) < need:
        raise ValueError(
            "team has only %d free slots; need %d to reach 35 active"
            % (len(candidates), need)
        )

    counts = _count_active_by_position(team)
    positions = _priority_order(counts, need)

    for index, code in zip(candidates, positions):
        rec = rookie_gen.make(code, season_year)
        rookie = bytearray(rec)
        rookie[31] = (rookie[31] & 0xF0) | (code & 0x0F)

        season_copy = bytearray(rookie)
        _zero_season_stats(season_copy)

        team.players[index].raw = bytes(rookie)
        team.players[SEASON_HALF_BASE + index].raw = bytes(season_copy)

    team.save(team_out_path)
    return {"vacancies": candidates, "positions": positions}
