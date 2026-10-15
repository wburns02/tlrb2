#!/usr/bin/env python3
"""Lahman season -> playable TLRB2 league (H1).
usage: build_season.py YEAR OUT_DIR [--db PATH] [--template DIR]
YEAR 1977..2012. Copies the template league dir to OUT_DIR (must not exist or be empty), then (1993:
the two NL expansion teams; 1998: TB replaces the AL's Milwaukee, which moves to the NL with Arizona;
renames: 1997 CAL to ANAHEIM/ANA, 2005 LA ANGELS/LAA and WASHINGTON/WAS, 2012 MIAMI/MIA), rewrites the
28 or 30 CLAS*.V20 files, seeds HISTORY.DAT with the players' Lahman careers before YEAR (C36,
seed_history), then rebuilds ALLSTAR1/2 from them (C9, rosters.refresh_allstars). 1994+ adds TEAMID.DAT
(from the pre-realignment MAJ) and realigns the MAJ to 3 divisions with the Lahman alignment (C38,
realign_lahman). MAJ and every V20 header bytes 0..110 are kept from the template (1993/1998: the
MAJ expansion slot entries and division counts are patched, C15's UTIL NEW TEAM fields). The last step
writes REAL.DAT, the real standings and player lines of YEAR (C74, write_real). Exit 0 ok, 2
on any error."""
import os
import shutil
import sqlite3
import struct
import sys
import unicodedata

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import ratings                                                    # noqa: E402
import v20                                                        # noqa: E402
from m4 import realign, rosters, teamids                          # noqa: E402 (depth_rebuild)

DB = '/mnt/nvme/tlrb2/lahman/lahmansbaseballdb.sqlite'
TEMPLATE = '/mnt/nvme/tlrb2/hist/template/CLASSIC'
YEAR_MIN, YEAR_MAX = 1977, 2012

# 1977-1992 alignment, slot = division*8 + i (all-star team is slot 15): AL East 0..6, AL West
# 8..14, NL East 0..5, NL West 8..14. Files clasale1..7, clasalw1..7, clasnle1..6, clasnlw1..6.
# Milwaukee used the Lahman teamID ML4 through 1997 (the Brewers leave the AL in 1998; from then
# on MIL is the NL teamID and clasale5 holds TBA).
AL_TEAMS = ['BAL', 'BOS', 'CLE', 'DET', 'ML4', 'NYA', 'TOR',
            'CAL', 'CHA', 'KCA', 'MIN', 'OAK', 'SEA', 'TEX']
NL_TEAMS = ['CHN', 'MON', 'NYN', 'PHI', 'PIT', 'SLN',
            'ATL', 'CIN', 'HOU', 'LAN', 'SDN', 'SFN']


def team_list(year=1992):
    """[(stem, Lahman teamID, MAJ slot)] for the season: the 26 pre-1993 teams; 1993 the
    two NL expansion teams (East 7th FLO slot 6, West 7th COL slot 14); 1997 the AL slot 8
    team's Lahman teamID becomes ANA; 1998 TB takes the AL slot 4 stem clasale5, Milwaukee
    moves to the NL East as clasnle8 slot 7 and ARI joins the NL West as clasnlw8 slot 15
    (28 -> 30 teams). 2005 MON becomes WAS and the AL slot 8 teamID becomes LAA; 2012 FLO
    becomes MIA."""
    out = []
    for i, tid in enumerate(AL_TEAMS):
        et = i < 7
        if i == 7 and year >= 1997:
            tid = 'ANA'
        if i == 7 and year >= 2005:
            tid = 'LAA'
        if i == 4 and year >= 1998:
            tid = 'TBA'
        out.append(('clasale%d' % (i + 1) if et else 'clasalw%d' % (i - 6),
                    tid, i if et else i + 1))
    nl = list(NL_TEAMS)
    if year >= 1993:
        nl.insert(6, 'FLO')
        nl.append('COL')
    if year >= 1998:
        nl.insert(7, 'MIL')
        nl.append('ARI')
    ne = 8 if year >= 1998 else (7 if year >= 1993 else 6)   # NL East size
    for i, tid in enumerate(nl):
        if tid == 'MON' and year >= 2005:
            tid = 'WAS'
        elif tid == 'FLO' and year >= 2012:
            tid = 'MIA'
        out.append(('clasnle%d' % (i + 1) if i < ne else 'clasnlw%d' % (i - ne + 1),
                    tid, i if i < ne else i - ne + 8))
    return out


# 1993 NL expansion (stem, Lahman teamID, NL slot, display name, abbr, template stem to copy)
EXPANSION_1993 = [('clasnle7', 'FLO', 6, 'FLORIDA', 'FLA', 'clasnle6'),
                  ('clasnlw7', 'COL', 14, 'COLORADO', 'COL', 'clasnlw6')]


def _maj_path(out_dir):
    majs = [f for f in os.listdir(out_dir) if f.lower().endswith('.maj')]
    if len(majs) != 1:
        raise ValueError('expected exactly one MAJ file in %s, got %r' % (out_dir, majs))
    return os.path.join(out_dir, majs[0])


def add_expansion(out_dir):
    """1993: add the two NL expansion teams. Copies the neighbouring template V20 to
    CLASNLE7.V20 / CLASNLW7.V20, renames them, then patches the MAJ: each NL team entry's
    name, abbr, stem (the C15 UTIL NEW TEAM fields) and the NL division counts 6 -> 7.
    Everything else in the MAJ must stay the template's (and the target slots empty)."""
    maj = _maj_path(out_dir)
    img = bytearray(open(maj, 'rb').read())
    if len(img) < 0x758c + 0x298 + 2:
        raise ValueError('MAJ too short: %d B' % len(img))
    for stem, tid, slot, name, abbr, tmpl in EXPANSION_1993:
        if img[0x758c + 0x1d7 + 8 * slot] != 0:
            raise ValueError('MAJ slot %d is not empty' % slot)
    for stem, tid, slot, name, abbr, tmpl in EXPANSION_1993:
        shutil.copy2(os.path.join(out_dir, tmpl.upper() + '.V20'),
                     os.path.join(out_dir, stem.upper() + '.V20'))
        t = v20.Team.load(os.path.join(out_dir, stem.upper() + '.V20'))
        t.set_name(name)
        t.set_abbr(abbr)
        t.set_stadium('grass')
        t.save(os.path.join(out_dir, stem.upper() + '.V20'))
        b = 0x758c + 0x0f + 16 * slot
        img[b:b + 16] = name.encode('latin-1').ljust(16, b'\0')
        b = 0x758c + 0x18f + 3 * slot
        img[b:b + 3] = abbr.encode('latin-1').ljust(3, b'\0')
        b = 0x758c + 0x1d7 + 8 * slot
        img[b:b + 8] = stem.encode('latin-1').ljust(8, b'\0')
    for d in (0, 1):
        img[0x758c + 0x298 + d] = 7
        img[0x20e + 3 + d] = 7
    open(maj, 'wb').write(bytes(img))


# 1998: TB replaces the AL's Milwaukee, which moves to the NL with Arizona. Slot 7 files and
# entries must be empty first (same ValueError as add_expansion).
EXPANSION_1998 = [('clasnle8', 'MIL', 7, 'MILWAUKEE', 'MIL', 'clasnle5'),
                  ('clasnlw8', 'ARI', 15, 'ARIZONA', 'ARI', 'clasnlw7')]


def add_expansion_1998(out_dir):
    """1998: copy the (still template-Milwaukee) CLASALE5.V20 to CLASNLE8.V20 as MILWAUKEE/MIL
    (stadium kept) and CLASNLW7.V20 to CLASNLW8.V20 as ARIZONA/ARI (stadium grass); then the
    CLASALE5.V20 file becomes TAMPA BAY/TB. NL slots 7 and 15 get name, abbr and stem, and the
    NL division counts go 7 -> 8."""
    maj = _maj_path(out_dir)
    img = bytearray(open(maj, 'rb').read())
    if len(img) < 0x758c + 0x298 + 2:
        raise ValueError('MAJ too short: %d B' % len(img))
    for stem, tid, slot, name, abbr, tmpl in EXPANSION_1998:
        if img[0x758c + 0x1d7 + 8 * slot] != 0:
            raise ValueError('MAJ slot %d is not empty' % slot)
    le5 = os.path.join(out_dir, 'CLASALE5.V20')
    shutil.copy2(le5, os.path.join(out_dir, 'CLASNLE8.V20'))
    t = v20.Team.load(os.path.join(out_dir, 'CLASNLE8.V20'))
    t.set_name('MILWAUKEE')
    t.set_abbr('MIL')
    t.save(os.path.join(out_dir, 'CLASNLE8.V20'))
    shutil.copy2(os.path.join(out_dir, 'CLASNLW7.V20'), os.path.join(out_dir, 'CLASNLW8.V20'))
    t = v20.Team.load(os.path.join(out_dir, 'CLASNLW8.V20'))
    t.set_name('ARIZONA')
    t.set_abbr('ARI')
    t.set_stadium('grass')
    t.save(os.path.join(out_dir, 'CLASNLW8.V20'))
    t = v20.Team.load(le5)
    t.set_name('TAMPA BAY')
    t.set_abbr('TB')
    t.set_stadium('grass')
    t.save(le5)
    b = 0x21d + 0x0f + 16 * 4
    img[b:b + 16] = 'TAMPA BAY'.encode('latin-1').ljust(16, b'\0')
    b = 0x21d + 0x18f + 3 * 4
    img[b:b + 3] = b'TB\0'
    for stem, tid, slot, name, abbr, tmpl in EXPANSION_1998:
        b = 0x758c + 0x0f + 16 * slot
        img[b:b + 16] = name.encode('latin-1').ljust(16, b'\0')
        b = 0x758c + 0x18f + 3 * slot
        img[b:b + 3] = abbr.encode('latin-1').ljust(3, b'\0')
        b = 0x758c + 0x1d7 + 8 * slot
        img[b:b + 8] = stem.encode('latin-1').ljust(8, b'\0')
    for d in (0, 1):
        img[0x758c + 0x298 + d] = 8
        img[0x20e + 3 + d] = 8
    open(maj, 'wb').write(bytes(img))


# (first, last, stem, L, slot, name, abbr): franchise moves and rebrands. Each row with
# first <= year <= last sets the V20 header name/abbr and the MAJ league L slot entry.
RENAMES = [
    (1997, 2004, 'clasalw1', 0, 8, 'ANAHEIM', 'ANA'),
    (2005, 9999, 'clasalw1', 0, 8, 'LA ANGELS', 'LAA'),
    (2005, 9999, 'clasnle2', 1, 1, 'WASHINGTON', 'WAS'),
    (2012, 9999, 'clasnle7', 1, 6, 'MIAMI', 'MIA'),
]


def rename_teams(out_dir, year):
    """The RENAMES rows active for year: the stem's V20 header name/abbr and the MAJ league L
    slot entry's name (16 B NUL padded) and abbr follow."""
    maj = _maj_path(out_dir)
    img = bytearray(open(maj, 'rb').read())
    if len(img) < 0x758c + 0x298 + 2:
        raise ValueError('MAJ too short: %d B' % len(img))
    for first, last, stem, L, slot, name, abbr in RENAMES:
        if not first <= year <= last:
            continue
        path = os.path.join(out_dir, stem.upper() + '.V20')
        t = v20.Team.load(path)
        t.set_name(name)
        t.set_abbr(abbr)
        t.save(path)
        s = teamids.S[L]
        b = s + 0x0f + 16 * slot
        img[b:b + 16] = name.encode('latin-1').ljust(16, b'\0')
        b = s + 0x18f + 3 * slot
        img[b:b + 3] = abbr.encode('latin-1').ljust(3, b'\0')
    open(maj, 'wb').write(bytes(img))


BAT_COLS = ['AB', 'R', 'H', '2B', '3B', 'HR', 'RBI', 'SB', 'CS', 'BB', 'SO', 'SH']
PIT_COLS = ['W', 'L', 'CG', 'GS', 'SHO', 'SV', 'IPouts', 'H', 'ER', 'HR',
            'BB', 'SO', 'BFP', 'BK', 'WP', 'R']
ZERO_B = (0,) * len(BAT_COLS)
ZERO_P = (0,) * len(PIT_COLS)
POS_RATE_FN = {'power': 'power', 'bunt': 'bunt', 'hit_run': 'hit_and_run', 'speed': 'speed',
               'range': 'rng', 'arm': 'arm', 'control': 'control', 'velocity': 'velocity',
               'endurance': 'endurance'}
# every stat field (roster half computed, season twin all zero)
STAT_FIELDS = ['runs', 'rbi', 'sh', 'sb', 'cs', 'ab_l', 'ab_r', 'h_l', 'h_r', 'd_l', 'd_r',
               't_l', 't_r', 'hr_l', 'hr_r', 'bb_l', 'bb_r', 'so_l', 'so_r',
               'po1', 'po2', 'a1', 'a2', 'e1', 'e2', 'dp1', 'dp2', 'pb',
               'w', 'l', 'cg', 'gs', 'sho', 'sv', 'ip10', 'er', 'runs_allowed',
               'bf_l', 'bf_r', 'ph_l', 'ph_r', 'pd_l', 'pd_r', 'pt_l', 'pt_r',
               'pbb_l', 'pbb_r', 'pso_l', 'pso_r', 'phr_l', 'phr_r', 'bk', 'wp']


def clamp255(x):
    return max(0, min(255, x))


def clamp16(x):
    return max(0, min(65535, x))


def fold(s):
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(ch for ch in s if ord(ch) < 128)


def agg_team(c, year, tid, table, cols):
    sel = ', '.join('"%s"' % x for x in cols)
    out = {}
    for r in c.execute('select playerID, %s from %s where yearID=? and teamID=?'
                       % (sel, table), (year, tid)):
        acc = out.setdefault(r[0], [0] * len(cols))
        for i, v in enumerate(r[1:]):
            acc[i] += v or 0
    return {k: tuple(v) for k, v in out.items()}


def agg_fielding(c, year, tid):
    out = {}
    for pid, pos, g, po, a, e, dp, pb in c.execute(
            'select playerID, POS, G, PO, A, E, DP, PB from fielding'
            ' where yearID=? and teamID=?', (year, tid)):
        acc = out.setdefault(pid, {}).setdefault(pos, [0] * 6)
        for i, v in enumerate((g, po, a, e, dp, pb)):
            acc[i] += v or 0
    return {k: {p: tuple(v) for p, v in x.items()} for k, x in out.items()}


def exp_map(c, year):
    """playerID -> set of earlier years with any batting or pitching row."""
    out = {}
    for tab in ('batting', 'pitching'):
        for pid, y in c.execute('select distinct playerID, yearID from %s where yearID<?'
                                % tab, (year,)):
            out.setdefault(pid, set()).add(y)
    return out


def select(c, year):
    """{teamID: [(playerID, (tid, G_all, G_p, [G_c, G_1b, G_2b, G_3b, G_ss, G_lf, G_cf,
    G_rf, G_dh]))]}: each player belongs to the one team with the largest G_all that year
    (ties: lowest teamID); only that team's stint rows are used for his stats."""
    app = c.execute('select playerID, teamID, G_all, G_p,'
                    ' G_c, G_1b, G_2b, G_3b, G_ss, G_lf, G_cf, G_rf, G_dh'
                    ' from appearances where yearID=?', (year,)).fetchall()
    best = {}
    for pid, tid, g_all, g_p, *pgames in app:
        cur = best.get(pid)
        if cur is None or g_all > cur[1] or (g_all == cur[1] and tid < cur[0]):
            best[pid] = (tid, g_all, g_p, pgames)
    tm = {}
    for pid, cur in best.items():
        tm.setdefault(cur[0], []).append((pid, cur))
    return tm


# Lahman fielding.POS string by TLRB pos code (C, 1B, 2B, 3B, SS, OF, P); OF codes
# 6..8 use the Lahman 'OF' totals rows.
FLD_CHAR = {1: 'C', 2: '1B', 3: '2B', 4: '3B', 5: 'SS', 6: 'OF', 7: 'OF', 8: 'OF'}


def split_u16(p, name, total, share):
    l = (total * share + 50) // 100
    p[name + '_l'] = clamp16(l)
    p[name + '_r'] = clamp16(total - l)


def split_u8(p, name, total, share):
    l = (total * share + 50) // 100
    p[name + '_l'] = clamp255(l)
    p[name + '_r'] = clamp255(total - l)


def write_batter_stats(p, bt):
    p['runs'] = clamp255(bt[1])
    p['rbi'] = clamp255(bt[6])
    p['sh'] = clamp255(bt[11])
    p['sb'] = clamp255(bt[7])
    p['cs'] = clamp255(bt[8])
    split_u16(p, 'ab', bt[0], 30)
    split_u16(p, 'h', bt[2], 30)
    split_u16(p, 'd', bt[3], 30)
    split_u8(p, 't', bt[4], 30)
    split_u8(p, 'hr', bt[5], 30)
    split_u16(p, 'bb', bt[9], 30)
    split_u16(p, 'so', bt[10], 30)


def write_pitcher_stats(p, pt):
    w, l, cg, gs, sho, sv, ipouts, h, er, hr, bb, so, bfp, bk, wp, r = pt
    p['w'] = clamp255(w)
    p['l'] = clamp255(l)
    p['cg'] = clamp255(cg)
    p['gs'] = clamp255(gs)
    p['sho'] = clamp255(sho)
    p['sv'] = clamp255(sv)
    p['ip10'] = clamp16((ipouts // 3) * 10 + ipouts % 3)
    p['er'] = clamp16(er)
    p['runs_allowed'] = clamp16(r)
    split_u8(p, 'pt', (h * 18 + 500) // 1000, 25)
    split_u16(p, 'pd', (h * 204 + 500) // 1000, 25)
    split_u16(p, 'bf', bfp, 25)
    split_u16(p, 'ph', h, 25)
    split_u16(p, 'pbb', bb, 25)
    split_u16(p, 'pso', so, 25)
    split_u8(p, 'phr', hr, 25)
    p['bk'] = clamp255(bk)
    p['wp'] = clamp255(wp)


def fld_totals(fld, char):
    x = fld.get(char)
    return x if x is not None else (0,) * 6


def write_fielding(p, pos1, pos2, fld):
    x = fld_totals(fld, FLD_CHAR[pos1]) if pos1 in FLD_CHAR else (0,) * 6
    p['po1'] = clamp16(x[1])
    p['a1'] = clamp16(x[2])
    p['e1'] = clamp255(x[3])
    p['dp1'] = clamp255(x[4])
    if pos2 in FLD_CHAR:
        x = fld_totals(fld, FLD_CHAR[pos2])
        p['po2'] = clamp16(x[1])
        p['a2'] = clamp16(x[2])
        p['e2'] = clamp255(x[3])
        p['dp2'] = clamp255(x[4])
    else:
        p['po2'] = p['a2'] = p['e2'] = p['dp2'] = 0
    p['pb'] = clamp255(fld_totals(fld, 'C')[5]) if pos1 == 1 else 0


def pos2_code(pos1, games):
    """pos2 (hi nibble 0x1f) from `others` = positions 1..8 other than pos1 with >= 10
    appearance games (games = G array by pos code 1..9)."""
    others = [q for q in range(1, 9) if q != pos1 and games[q - 1] >= 10]
    if not others:
        return pos1 if pos1 in range(1, 6) else (10 if pos1 in range(6, 9) else 9)
    if pos1 in (6, 7, 8):
        if all(q in (6, 7, 8) for q in others):
            return 10
        if any(q in (2, 3, 4, 5) for q in others):
            return 12
        if all(q == 1 for q in others):
            return 13
        return 12
    if pos1 in (2, 3, 4, 5):
        if len(others) == 1:
            return others[0]
        if all(q in (2, 3, 4, 5) for q in others):
            return 11
        if any(q in (6, 7, 8) for q in others):
            return 12
        return 14
    if pos1 == 1:
        if any(q in (6, 7, 8) for q in others):
            return 13
        return 15 if others == [4] else 14
    return others[0]


def build_player(c, year, pid, cur, rec, tw, agg, exps, people):
    row = people[pid]
    if row[2] is None:
        raise ValueError('no birthYear for %s' % pid)
    nameFirst, nameLast, byear, bmonth, bats, throws = row
    rec['last'] = fold(nameLast)[:11]
    rec['first'] = fold(nameFirst)[:7]
    age = year - byear - (1 if (bmonth or 0) >= 7 else 0)
    rec['age'] = clamp255(max(16, min(50, age)))
    rec['year'] = year
    rec['exp'] = clamp255(max(0, min(25, len(exps.get(pid, ())))))
    rec['games'] = clamp255(cur[1])
    rec['bats'] = {'L': 0, 'R': 1, 'B': 2}.get(bats, 1)
    rec['throws'] = 0 if throws == 'L' else 1
    fld = agg['fld'].get(pid, {})
    if cur[2] * 2 >= cur[1]:                                   # pitcher
        rec['pos1'] = rec['pos2'] = 0
        write_pitcher_stats(rec, agg['pit'].get(pid, ZERO_P))
        write_batter_stats(rec, agg['bat'].get(pid, ZERO_B))   # his batting rows
        write_fielding(rec, 0, 0, fld)
        names = ['control', 'velocity', 'endurance']
    else:
        games = cur[3]
        pos1 = max(range(1, 10), key=lambda q: (games[q - 1], -q))
        rec['pos1'] = pos1
        rec['pos2'] = pos2_code(pos1, games)
        write_batter_stats(rec, agg['bat'].get(pid, ZERO_B))
        write_fielding(rec, pos1, rec['pos2'], fld)
        names = ['power', 'bunt', 'hit_run', 'speed', 'range', 'arm']
    # ratings in the order the game computes them, each written before the next is computed
    for nm in names:
        rec[nm] = getattr(ratings, POS_RATE_FN[nm])(bytes(rec.raw))
    rec['salary'] = ratings.salary(bytes(rec.raw))
    # bio/ratings to the season twin (slot i + 40); its stats all zero
    for f in ['last', 'first', 'age', 'year', 'exp', 'games', 'bats', 'throws',
              'pos1', 'pos2', 'salary'] + names:
        tw[f] = rec[f]
    for f in STAT_FIELDS:
        tw[f] = 0
    rec.raw[141] = rec.raw[142] = 0
    tw.raw[141] = tw.raw[142] = 0


def tmpl_pair(orig, slot):
    """Template records (roster half, season twin) at slot from the pristine template
    bytes; if that slot is vacant there, the nearest lower named slot of the same type
    (pitcher 0..15, batter 16..39)."""
    named = [s for s in range(40) if orig[v20.HDR + v20.REC * s]]
    same = [s for s in named if (s < 16) == (slot < 16)]
    if not same:
        raise ValueError('template has no named %s slot'
                         % ('pitcher' if slot < 16 else 'batter'))
    lo = ([s for s in same if s <= slot] or same)[-1]
    return (bytearray(orig[v20.HDR + v20.REC * lo:v20.HDR + v20.REC * (lo + 1)]),
            bytearray(orig[v20.HDR + v20.REC * (lo + 40):v20.HDR + v20.REC * (lo + 41)]))


def picks(c, year, tid, sel, bat, pit):
    """40 rows: top pitchers by IPouts (ties playerID) in slots 0..15, top batters by
    AB + BB (ties playerID) in slots 16..39. Unused slots are vacant (None)."""
    cur = dict(sel)
    pits = [(pid, app) for pid, app in cur.items() if app[2] * 2 >= app[1]]
    bats = [(pid, app) for pid, app in cur.items() if app[2] * 2 < app[1]]
    pits.sort(key=lambda pc: (-pit.get(pc[0], ZERO_P)[6], pc[0]))
    bats.sort(key=lambda pc: (-(bat.get(pc[0], ZERO_B)[0] + bat.get(pc[0], ZERO_B)[9]),
                              pc[0]))
    out = [None] * 40
    for i, pc in enumerate(pits[:16]):
        out[i] = pc
    for i, pc in enumerate(bats[:24]):
        out[16 + i] = pc
    return out


def build_team(c, year, tid, path, people, exps, sel, placed=None):
    t = v20.Team.load(path)
    img = bytearray(t.to_bytes())
    orig = bytes(img)
    bat = agg_team(c, year, tid, 'batting', BAT_COLS)
    pit = agg_team(c, year, tid, 'pitching', PIT_COLS)
    agg = {'fld': agg_fielding(c, year, tid), 'bat': bat, 'pit': pit}
    rows = picks(c, year, tid, sel, bat, pit)
    for s, row in enumerate(rows):
        ro = v20.HDR + v20.REC * s
        so = v20.HDR + v20.REC * (s + 40)
        if row is None:
            img[ro:ro + v20.REC] = bytes(v20.REC)
            img[so:so + v20.REC] = bytes(v20.REC)
            continue
        pid, cur = row
        pair = tmpl_pair(orig, s)
        img[ro:ro + v20.REC] = pair[0]
        img[so:so + v20.REC] = pair[1]
        rec = v20.Player(img[ro:ro + v20.REC], s)
        tw = v20.Player(img[so:so + v20.REC], s + 40)
        build_player(c, year, pid, cur, rec, tw, agg, exps, people)
        img[ro:ro + v20.REC] = rec.raw
        img[so:so + v20.REC] = tw.raw
        if placed is not None:
            age = rec['age']
            placed.append((bytes(rec.raw[0:20]), 1001 - age, pid, rec['pos1'], age))
    rosters.depth_rebuild(img)
    v20.Team(img).save(path)


def build_league(db, year, out_dir, template):
    c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
    exps = exp_map(c, year)
    people = {r[0]: r[1:] for r in c.execute(
        'select playerID, nameFirst, nameLast, birthYear, birthMonth, bats, throws'
        ' from people')}
    sel = select(c, year)
    placed = []
    for stem, tid, slot in team_list(year):
        path = os.path.join(out_dir, stem.upper() + '.V20')
        build_team(c, year, tid, path, people, exps, sel.get(tid, []), placed)
    return placed


# (table, columns, first history.TOTALS index): batting G AB H 2B 3B HR R RBI BB SO SB CS = 0..11,
# fielding E = 12, pitching W L SV GS CG SHO OUTS ER PH PBB PSO PHR = 13..24
TOTAL_TABLES = (
    ('batting', ('G', 'AB', 'H', '2B', '3B', 'HR', 'R', 'RBI', 'BB', 'SO', 'SB', 'CS'), 0),
    ('fielding', ('E',), 12),
    ('pitching', ('W', 'L', 'SV', 'GS', 'CG', 'SHO', 'IPouts', 'ER', 'H', 'BB', 'SO', 'HR'), 13))


def _career_rows(c, year):
    """(pid -> year set, pid -> [25] totals sums) with yearID < year (NULL counts as 0), in
    history.TOTALS order (TOTAL_TABLES). The year set holds the years of batting and pitching
    rows only."""
    years, sums = {}, {}
    for tab, cols, base in TOTAL_TABLES:
        sel = ', '.join('"%s"' % x for x in cols)
        for r in c.execute('select playerID, yearID, %s from %s where yearID<?' % (sel, tab),
                           (year,)):
            pid = r[0]
            if tab != 'fielding':
                years.setdefault(pid, set()).add(r[1])
            acc = sums.setdefault(pid, [0] * 25)
            for j, v in enumerate(r[2:]):
                acc[base + j] += v or 0
    return years, sums


AWARD_NAMES = ['Most Valuable Player', 'Cy Young Award', 'Rookie of the Year',
               'Gold Glove', 'Silver Slugger']


def _award_counts(c, year):
    """playerID -> [MVP, CY, ROY, GG, SS] award counts with yearID < year, each capped at 255."""
    out = {}
    for pid, aid, n in c.execute(
            'select playerID, awardID, count(*) from awardsplayers'
            ' where yearID<? group by playerID, awardID', (year,)):
        k = AWARD_NAMES.index(aid) if aid in AWARD_NAMES else -1
        if k < 0:
            continue
        acc = out.setdefault(pid, [0] * 5)
        acc[k] = min(255, acc[k] + n)
    return out


def seed_history(db, year, out_dir, placed):
    """C36: write OUT_DIR/HISTORY.DAT with one prior-career entry per placed player who
    has a pre-YEAR Lahman row. Identity = the V20 record's name bytes 0..19 and birth
    = 1001 - age; a second player with the same (name, birth) identity is skipped."""
    from m4 import history
    c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
    years, sums = _career_rows(c, year)
    awards = _award_counts(c, year)
    hist = history.History(None)
    hist.version = 1
    hist.seasons_recorded = 0
    hist.start_year = year
    seen = set()
    for rec in placed:
        pid = rec[2]
        if pid not in years:
            continue
        name20, birth = rec[0], rec[1]
        if (name20, birth) in seen:
            continue
        seen.add((name20, birth))
        total = sums[pid]
        pos1 = rec[3] & 15
        hist.append_entry({'name': name20, 'birth': birth, 'status': history.STATUS_ACTIVE,
                           'age': rec[4], 'first_season': 1, 'last_season': 0,
                           'seasons_played': len(years[pid]), 'pos1': pos1,
                           'pitcher': 1 if pos1 == 0 else 0, 'totals': total,
                           'WAR10': 0, 'top7': [history.EMPTY_TOP] * 7, 'JAWS10': 0,
                           'hof_season': 0, 'awards': awards.get(pid, [0] * 5)})
    hist.save(os.path.join(out_dir, 'HISTORY.DAT'))
    c.close()


def realign_lahman(db, year, out_dir, template=None):
    """C38: 1994+ leagues are written already realigned to 3 divisions with the Lahman
    alignment. Writes TEAMID.DAT from the pre-realignment MAJ (stable ids = the 2-division
    engine ids), realigns the MAJ, then sets HISTORY.DAT byte 0 = 1 (the season is rolled,
    START NEW SEASON > GENERATED starts it)."""
    from m4 import realign
    from m4 import teamids
    maj = _maj_path(out_dir)
    d = open(maj, 'rb').read()
    c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
    div = dict(c.execute('select teamID, divID from teams where yearID=?', (year,)))
    c.close()
    known = {}
    for L, prefix in ((0, 'clasal'), (1, 'clasnl')):
        s = teamids.S[L]
        names = [[] for _ in range(3)]
        for stem, tid, slot in team_list(year):
            if not stem.startswith(prefix):
                continue
            if tid not in div:
                raise ValueError('Lahman teams table has no divID for %s (year %d)'
                                 % (tid, year))
            a = s + teamids.O_ABBR + 3 * slot
            names['EWC'.index(div[tid])].append(
                bytes(d[a:a + 3]).rstrip(b'\0').decode('latin-1'))
        known[L] = names
    table = teamids.make_table(d)
    open(os.path.join(out_dir, teamids.TABLE_NAME), 'wb').write(table)
    # 1998+: the NL holds 16 teams (realign's default cap is 15)
    new, reason = realign.realign(d, 3, known=known, cap=16 if year >= 1998 else None)
    if reason is not None:
        raise ValueError(reason)
    if year >= 1998 and template is not None:
        # ARI took the NL slot 15 all-star entry (ALL STARS 2, NUL-led stem) in the 2-division
        # layout; slot 15 is free again after the 3-division realign, so the template's entry
        # comes back there, as in every other league
        new = bytearray(new)
        t = open(_maj_path(template), 'rb').read()
        s = teamids.S[1]
        for o, n in ((teamids.O_NAMES, 16), (teamids.O_ABBR, 3), (teamids.O_STEM, 8)):
            a = s + o + n * 15
            if any(new[a:a + n]):
                raise ValueError('NL slot 15 is not free after the realign')
            new[a:a + n] = t[a:a + n]
        new = bytes(new)
    open(maj, 'wb').write(new)
    hp = os.path.join(out_dir, 'HISTORY.DAT')
    img = bytearray(open(hp, 'rb').read())
    img[0] = 1
    open(hp, 'wb').write(bytes(img))


REAL_NAME = 'REAL.DAT'
REAL_HDR, REAL_TEAM, REAL_PLAYER = 16, 8, 80


def _season_totals(c, year):
    """(pid -> [25] sums, pid -> pitching G) over every stint of yearID == year, in history.TOTALS
    order (TOTAL_TABLES); a missing row or a NULL cell counts 0. Slot 0 (G) is the batting G."""
    sums, pit_g = {}, {}
    for tab, cols, base in TOTAL_TABLES:
        sel = ', '.join('"%s"' % x for x in cols)
        for r in c.execute('select playerID, %s from %s where yearID=?' % (sel, tab), (year,)):
            acc = sums.setdefault(r[0], [0] * 25)
            for j, v in enumerate(r[1:]):
                acc[base + j] += v or 0
    for pid, g in c.execute('select playerID, G from pitching where yearID=?', (year,)):
        pit_g[pid] = pit_g.get(pid, 0) + (g or 0)
    return sums, pit_g


def write_real(db, year, out_dir, placed):
    """C74: write OUT_DIR/REAL.DAT, what really happened in YEAR (16 B header 'RL', version 1, year,
    team record count T, player record count P; T 8 B team records (stable id, real W, real L) in
    id order; P 80 B player records, one per placed player in placed order: name20, birth key, the
    stable id of the team he was placed on, flags (bit0 pitcher: pos1 0), 25 u16 real season
    totals in history.TOTALS order summed over all his stints, capped at 0xffff; a pitcher's G is
    his pitching G). The stable ids are the league's own (MAJ and TEAMID.DAT), so this runs after
    realign_lahman. A team with no Lahman teams row gets no team record; a player whose team has
    no stable id gets 0xff."""
    c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
    try:
        sums, pit_g = _season_totals(c, year)
        team_of = {pid: tid for tid, rows in select(c, year).items() for pid, _cur in rows}
        wl = {tid: (w or 0, l or 0) for tid, w, l in
              c.execute('select teamID, W, L from teams where yearID=?', (year,))}
    finally:
        c.close()
    d = open(_maj_path(out_dir), 'rb').read()
    ids = {st.rstrip(b'\0').decode('latin-1').lower(): k
           for k, _L, _slot, st in teamids.teams(d, teamids.load_table(out_dir))}
    sid = {tid: ids[stem.lower()] for stem, tid, _slot in team_list(year) if stem.lower() in ids}
    teams = sorted((sid[tid], wl[tid]) for tid in sid if tid in wl)
    out = bytearray(REAL_HDR + REAL_TEAM * len(teams) + REAL_PLAYER * len(placed))
    struct.pack_into('<2sBBHBBH', out, 0, b'RL', 1, 0, year, len(teams), 0, len(placed))
    off = REAL_HDR
    for k, (w, l) in teams:
        struct.pack_into('<BBHHH', out, off, k, 0, min(w, 0xffff), min(l, 0xffff), 0)
        off += REAL_TEAM
    for name20, birth, pid, pos1, _age in (r[:5] for r in placed):
        pitcher = (pos1 & 15) == 0
        tot = list(sums.get(pid, [0] * 25))
        if pitcher:
            tot[0] = pit_g.get(pid, 0)
        out[off:off + 20] = bytes(name20)[:20].ljust(20, b'\0')
        struct.pack_into('<HBB', out, off + 20, birth, sid.get(team_of.get(pid), 0xff),
                         1 if pitcher else 0)
        struct.pack_into('<25H', out, off + 24, *(min(v, 0xffff) for v in tot))
        off += REAL_PLAYER
    with open(os.path.join(out_dir, REAL_NAME), 'wb') as f:
        f.write(bytes(out))


def main(argv):
    usage = 'usage: build_season.py YEAR OUT_DIR [--db PATH] [--template DIR]'
    year, out, db, template = None, None, DB, TEMPLATE
    args = list(argv[1:])
    i = 0
    try:
        while i < len(args):
            a = args[i]
            if a == '--db':
                db = args[i + 1]
                i += 2
            elif a == '--template':
                template = args[i + 1]
                i += 2
            elif year is None:
                year = a
                i += 1
            elif out is None:
                out = a
                i += 1
            else:
                print(usage)
                return 2
    except IndexError:
        print(usage)
        return 2
    if year is None or out is None:
        print(usage)
        return 2
    try:
        year = int(year)
    except ValueError:
        print('YEAR must be an integer, got %r' % year)
        return 2
    if not YEAR_MIN <= year <= YEAR_MAX:
        print('YEAR must be %d..%d, got %d' % (YEAR_MIN, YEAR_MAX, year))
        return 2
    if not os.path.isfile(db):
        print('DB missing: %s' % db)
        return 2
    if not os.path.isdir(template):
        print('template missing: %s' % template)
        return 2
    if os.path.exists(out) and (not os.path.isdir(out) or os.listdir(out)):
        print('OUT_DIR must not exist or be empty: %s' % out)
        return 2
    try:
        os.makedirs(out, exist_ok=True)
        for f in os.listdir(template):
            shutil.copy2(os.path.join(template, f), os.path.join(out, f))
            os.chmod(os.path.join(out, f), 0o644)
        if year >= 1993:
            add_expansion(out)
        if year >= 1998:
            add_expansion_1998(out)
        if year >= 1997:
            rename_teams(out, year)
        placed = build_league(db, year, out, template)
        seed_history(db, year, out, placed)
        rosters.refresh_allstars(out)               # else the template's classic stars play the first All-Star game
        if year >= 1994:
            realign_lahman(db, year, out, template)
        write_real(db, year, out, placed)           # C74: last, the stable ids are final now
        if year >= 1998:
            # C71 (rig, 2026-10-15): 16 teams overflow the engine's 15 team indexes a league, and
            # GENERATED refuses an odd (15/15) split, so a 30-team league does not play in-game yet
            print('warning: %d builds 30 teams (NL 16), which the game cannot schedule (C71)' % year)
    except Exception as e:
        print('build failed: %s' % e)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
