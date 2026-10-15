#!/usr/bin/env python3
"""Playoff format realignment (contract C12.4 setting and C12.5 realignment), Python reference.

HISTORY.DAT byte 11 picks the format: 2 divisions (stock) or 3 divisions and a wild card. realign() moves a
league's team entries (names, abbreviations, stems) to the slots of the wanted layout and rewrites the MAJ
counts and day to match (the file header stem table is left as it is, C12.1). apply() also writes TEAMID.DAT (teamids.py, C12.3) from the
pre-realignment MAJ the first time, so every team keeps its stable id.

usage: realign.py LEAGUE_DIR   (runs apply; prints FORMAT n, FORMAT REFUSED reason, or nothing)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import history  # noqa: E402
import maj      # noqa: E402
import teamids  # noqa: E402

HISTORY_NAME = 'HISTORY.DAT'
MAJ_SIZE = maj.SIZE
S = teamids.S
O_NAMES, O_ABBR, O_STEM = teamids.O_NAMES, teamids.O_ABBR, teamids.O_STEM
LG_NAMES = ('AL', 'NL')
# known alignments by abbreviation, [target divisions][league] -> division lists (East, West, Central)
KNOWN = {
    3: {0: [['BAL', 'BOS', 'DET', 'NYA', 'TOR'], ['CAL', 'OAK', 'SEA', 'TEX'], ['CHA', 'CLE', 'KC', 'MIL', 'MIN']],
        1: [['ATL', 'MON', 'NYN', 'PHI'], ['LA', 'SD', 'SF'], ['CHN', 'CIN', 'HOU', 'PIT', 'SL']]},
    2: {0: [['BAL', 'BOS', 'CLE', 'DET', 'MIL', 'NYA', 'TOR'], ['CAL', 'CHA', 'KC', 'MIN', 'OAK', 'SEA', 'TEX']],
        1: [['CHN', 'MON', 'NYN', 'PHI', 'PIT', 'SL'], ['ATL', 'CIN', 'HOU', 'LA', 'SD', 'SF']]},
}


def now_divs(d):
    d = teamids.raw(d)
    if len(d) <= 0x20d:
        return 2
    return 2 if d[0x20d] == 1 else d[0x20d]


def wanted(hist, d):
    b = hist[11] if len(hist) > 11 else 0
    return b if b in (2, 3) else now_divs(d)


def wanted_for_dir(league_dir):
    """-> (wanted, now) for a league dir. A missing HISTORY.DAT reads as empty; no MAJ reads as now 2."""
    hp = os.path.join(league_dir, HISTORY_NAME)
    hist = open(hp, 'rb').read() if os.path.exists(hp) else b''
    mp = history.maj_or_none(league_dir)
    d = open(mp, 'rb').read() if mp else b''
    return wanted(hist, d), now_divs(d)


def _abbr(abbr):
    return abbr.replace(b'\0', b'').decode('latin-1')


def _league_teams(d, L):
    """[(slot, name16, abbr3, stem8)] of league L in slot order (the C12.3 teams)."""
    s = S[L]
    out = []
    for lg, slot, stem in teamids.maj_teams(d):
        if lg != L:
            continue
        name = bytes(d[s + O_NAMES + 16 * slot:s + O_NAMES + 16 * slot + 16])
        abbr = bytes(d[s + O_ABBR + 3 * slot:s + O_ABBR + 3 * slot + 3])
        out.append((slot, name, abbr, stem))
    return out


def _divisions(teams_L, target, L, known=None):
    """Three division lists (East, West, Central; Central empty with 2 divisions) of league L's team tuples.
    known, when given, replaces KNOWN[target] (known[L] per league, same set-equality check: a set that does
    not match the league's abbreviations falls back to the generic rule)."""
    table = KNOWN[target][L] if known is None else known[L]
    if {_abbr(t[2]) for t in teams_L} == {a for div in table for a in div}:
        by = {_abbr(t[2]): t for t in teams_L}
        out = [[by[a] for a in div] for div in table]
    else:
        n = len(teams_L)
        if target == 3:
            q, r = divmod(n, 3)
            sizes = [q + (r > 0), q + (r > 1), q]
        else:
            sizes = [(n + 1) // 2, n // 2]
        out, i = [], 0
        for sz in sizes:
            out.append(teams_L[i:i + sz])
            i += sz
    return out + [[]] * (3 - len(out))


def realign(d, target, known=None):
    """-> (new_bytes, None), or (None, reason) when refused; d itself is never changed. known, when given,
    is a {league: division lists} table replacing KNOWN[target] (Python only; the C port takes none)."""
    assert target in (2, 3), target
    d = teamids.raw(d)
    if len(d) < MAJ_SIZE:
        return None, 'SHORT MAJ'
    if d[0x20c] != 2:
        return None, 'NOT 2 LEAGUES'
    if d[0x20d] not in (1, 2, 3):
        return None, 'BAD DIVISIONS'
    if target == now_divs(d):
        return None, 'ALREADY'
    cap = 15 if target == 3 else 14
    leagues = [_league_teams(d, L) for L in (0, 1)]
    for L, lst in enumerate(leagues):
        if len(lst) > cap:
            return None, f'{LG_NAMES[L]} TOO MANY TEAMS'
        if target == 3 and len(lst) % 2:
            return None, f'{LG_NAMES[L]} ODD COUNT'

    new = bytearray(d)
    for L in (0, 1):
        s = S[L]
        for slot in range(teamids.SLOTS):
            if slot == 15 and d[s + O_STEM + 8 * 15] == 0:
                continue                       # the all-star entry stays
            new[s + O_NAMES + 16 * slot:s + O_NAMES + 16 * slot + 16] = bytes(16)
            new[s + O_ABBR + 3 * slot:s + O_ABBR + 3 * slot + 3] = bytes(3)
            new[s + O_STEM + 8 * slot:s + O_STEM + 8 * slot + 8] = bytes(8)
        for dv, lst in enumerate(_divisions(leagues[L], target, L, known)):
            for i, (_slot, name, abbr, stem) in enumerate(lst):
                slot = dv * 8 + i
                new[s + O_NAMES + 16 * slot:s + O_NAMES + 16 * slot + 16] = name
                new[s + O_ABBR + 3 * slot:s + O_ABBR + 3 * slot + 3] = abbr
                new[s + O_STEM + 8 * slot:s + O_STEM + 8 * slot + 8] = stem
            new[s + 0x298 + dv] = len(lst)
            new[0x20e + 3 * L + dv] = len(lst)
        new[s + 0x2b3:s + 0x2cb] = b'\xff' * 24
        new[s + 0x2cb:s + 0x32b] = bytes(96)
    new[0x20a] = 0xf3
    new[0x20d] = target
    return bytes(new), None


def plan(maj_bytes, hist_bytes, table_bytes):
    """-> (code, new_maj, new_table, reason). Code 1: wanted == now (nothing). Code 2: refused (reason set).
    Code 0: new_maj is the realigned MAJ; new_table = make_table(maj_bytes) when table_bytes is None or not
    256 B (an existing table is never rewritten), else None."""
    d = teamids.raw(maj_bytes)
    want = wanted(hist_bytes or b'', d)
    if want == now_divs(d):
        return 1, None, None, None
    new, reason = realign(d, want)
    if new is None:
        return 2, None, None, reason
    if table_bytes is None or len(table_bytes) != teamids.TABLE_SIZE:
        return 0, new, teamids.make_table(d), None
    return 0, new, None, None


def apply(league_dir, out=None):
    """-> 0 (MAJ rewritten), 1 (nothing to do or no MAJ) or 2 (refused; the reason is appended to out)."""
    mp = history.maj_or_none(league_dir)
    if mp is None:
        return 1
    hp = os.path.join(league_dir, HISTORY_NAME)
    hist = open(hp, 'rb').read() if os.path.exists(hp) else None
    tp = teamids.table_path(league_dir)
    table = open(tp, 'rb').read() if tp else None
    code, new, new_table, reason = plan(open(mp, 'rb').read(), hist, table)
    if code == 2:
        if out is not None:
            out.append(reason)
        return 2
    if code == 1:
        return 1
    if new_table is not None:
        path = tp or os.path.join(league_dir, teamids.TABLE_NAME)
        open(path, 'wb').write(new_table)
    open(mp, 'wb').write(new)
    return 0


def main(argv):
    if len(argv) != 2:
        raise SystemExit(__doc__)
    target, _now = wanted_for_dir(argv[1])
    out = []
    rc = apply(argv[1], out)
    if rc == 0:
        print(f'FORMAT {target}')
    elif rc == 2:
        print(f'FORMAT REFUSED {out[-1]}')


if __name__ == '__main__':
    main(sys.argv)
