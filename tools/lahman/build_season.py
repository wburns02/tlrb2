#!/usr/bin/env python3
"""Lahman season -> playable TLRB2 league (H1).
usage: build_season.py YEAR OUT_DIR [--db PATH] [--template DIR]
YEAR 1977..1992. Copies the template league dir to OUT_DIR (must not exist or be empty), then
rewrites the 26 CLAS*.V20 files. MAJ, the ALLSTAR files and every V20 header bytes 0..110 are
kept from the template. Exit 0 ok, 2 on any error."""
import os
import shutil
import sqlite3
import sys
import unicodedata

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import ratings                                                    # noqa: E402
import v20                                                        # noqa: E402
from m4 import rosters                                            # noqa: E402 (depth_rebuild)

DB = '/mnt/nvme/tlrb2/lahman/lahmansbaseballdb.sqlite'
TEMPLATE = '/mnt/nvme/tlrb2/hist/template/CLASSIC'
YEAR_MIN, YEAR_MAX = 1977, 1992

# 1977-1992 alignment, slot = division*8 + i (all-star team is slot 15): AL East 0..6, AL West
# 8..14, NL East 0..5, NL West 8..14. Files clasale1..7, clasalw1..7, clasnle1..6, clasnlw1..6.
# Milwaukee used the Lahman teamID ML4 (MIL is a franchID, never a teamID here).
AL_TEAMS = ['BAL', 'BOS', 'CLE', 'DET', 'ML4', 'NYA', 'TOR',
            'CAL', 'CHA', 'KCA', 'MIN', 'OAK', 'SEA', 'TEX']
NL_TEAMS = ['CHN', 'MON', 'NYN', 'PHI', 'PIT', 'SLN',
            'ATL', 'CIN', 'HOU', 'LAN', 'SDN', 'SFN']


def team_list():
    out = []
    for i, tid in enumerate(AL_TEAMS):
        et = i < 7
        out.append(('clasale%d' % (i + 1) if et else 'clasalw%d' % (i - 6),
                    tid, i if et else i + 1))
    for i, tid in enumerate(NL_TEAMS):
        et = i < 6
        out.append(('clasnle%d' % (i + 1) if et else 'clasnlw%d' % (i - 5),
                    tid, i if et else i + 2))
    return out


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


# Lahman fielding POS char by TLRB pos code (pos char for pos1/pos2 fielding); OF codes
# 6..8 use the Lahman 'OF' totals rows.
FLD_CHAR = {1: '2', 2: '3', 3: '4', 4: '5', 5: '6', 6: 'OF', 7: 'OF', 8: 'OF'}


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
    p['pb'] = clamp255(fld_totals(fld, '2')[5]) if pos1 == 1 else 0


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


def build_team(c, year, tid, path, people, exps, sel):
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
    rosters.depth_rebuild(img)
    v20.Team(img).save(path)


def build_league(db, year, out_dir, template):
    c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
    exps = exp_map(c, year)
    people = {r[0]: r[1:] for r in c.execute(
        'select playerID, nameFirst, nameLast, birthYear, birthMonth, bats, throws'
        ' from people')}
    sel = select(c, year)
    for stem, tid, slot in team_list():
        path = os.path.join(out_dir, stem.upper() + '.V20')
        build_team(c, year, tid, path, people, exps, sel.get(tid, []))


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
        build_league(db, year, out, template)
    except Exception as e:
        print('build failed: %s' % e)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
