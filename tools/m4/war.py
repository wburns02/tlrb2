#!/usr/bin/env python3
"""M4 WAR / Hall of Fame reference (notes/M4_CONTRACT.md C3). Integer math only:
every signed division goes through idiv() which truncates toward zero (x86 idiv).

war.py operates on the SEASON half (records 40..79 of a .V20) plus the roster half
for range/arm ratings. Two entry points:
  war10_players(teams)    per-player season WAR10, teams = [(v20_path, team_lg_id)]
  season_league(teams)    same plus the league aggregates (L_lw, L_pa, L_runs,
                          L_er, L_outs, pf1000 per team id)
jaws10 and hof_passes are here; history.record_season() calls these.
usage: python3 tools/m4/war.py LEAGUE_DIR   (per-player season WAR10)
"""
import os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from v20 import Team, F, _get           # noqa: E402
import maj                              # noqa: E402

PF_MIN, PF_MAX = 900, 1100


def idiv(a, b):
    """Signed division truncating toward zero (x86 idiv). Python // floors."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


# pos100 per 162 G by pos1 code (v20 POS order), DH = 9; anything else 0
POS100 = {1: 1250, 2: -1250, 3: 300, 4: 250, 5: 750, 6: -750, 7: 250, 8: -750, 9: -1750}


def player_bat_inputs(rec):
    """(ab, h, d, t, hr, bb, sb, cs, runs) summed L+R from a season-half record."""
    ab = _get(rec, *F['ab_l']) + _get(rec, *F['ab_r'])
    h = _get(rec, *F['h_l']) + _get(rec, *F['h_r'])
    d = _get(rec, *F['d_l']) + _get(rec, *F['d_r'])
    t = _get(rec, *F['t_l']) + _get(rec, *F['t_r'])
    hr = _get(rec, *F['hr_l']) + _get(rec, *F['hr_r'])
    bb = _get(rec, *F['bb_l']) + _get(rec, *F['bb_r'])
    sb, cs = _get(rec, *F['sb']), _get(rec, *F['cs'])
    runs = _get(rec, *F['runs'])
    return ab, h, d, t, hr, bb, sb, cs, runs


def batter_bat100(season, lg):
    """C3 bat100 (batting runs x100 after the park term). lg = dict with keys L_lw,
    L_pa, L_runs, pf1000. pa == 0 batters: bat100 = lw100 (park100 = 0, the C3
    amendment: batters with pa == 0 still get lw100). If L_pa == 0 the subtraction
    terms are 0 (no division)."""
    ab, h, d, t, hr, bb, sb, cs, runs = player_bat_inputs(season)
    s1 = h - d - t - hr
    pa = ab + bb
    lw100 = 47 * s1 + 78 * d + 109 * t + 140 * hr + 33 * bb + 20 * sb - 41 * cs - 27 * (ab - h)
    if pa > 0 and lg['L_pa'] > 0:
        bat100 = lw100 - idiv(lg['L_lw'] * pa, lg['L_pa'])
        pf1000 = lg.get('pf1000', 1000)
        park100 = idiv(idiv((pf1000 - 1000) * lg['L_runs'], 20) * pa, lg['L_pa'])
        bat100 -= park100
    else:
        bat100 = lw100
    return bat100


def batter_war10(season, roster, games, lg):
    """C3 batter WAR10 from batter_bat100 plus replacement, position and fielding."""
    bat100 = batter_bat100(season, lg)
    ab, h, d, t, hr, bb, sb, cs, runs = player_bat_inputs(season)
    pa = ab + bb
    repl100 = idiv(2000 * pa, 600) if pa > 0 and lg['L_pa'] > 0 else 0
    pos1 = _get(roster, *F['pos1']) & 15
    posadj100 = idiv(POS100.get(pos1, 0) * games, 162)
    fld100 = iddiv_fld(roster, games)
    return idiv(bat100 + repl100 + posadj100 + fld100, 100)


def iddiv_fld(roster, games):
    """fld100 = (((range - 6) * 150 + (arm - 6) * 50) * g) / 162 (rounds toward zero)."""
    rng = _get(roster, *F['range'])
    arm = _get(roster, *F['arm'])
    raw = (rng - 6) * 150 + (arm - 6) * 50
    return idiv(raw * games, 162)


def pitcher_war10(season, games, lg):
    """C3 pitcher WAR10 from season-half ip10/er. lg needs L_er, L_outs."""
    ip10 = _get(season, *F['ip10'])
    outs = ipiv_outs(ip10)
    er = _get(season, *F['er'])
    if lg['L_outs'] == 0 or outs == 0:
        return 0
    pit100 = idiv(lg['L_er'] * 120 * outs, lg['L_outs']) - er * 100
    return idiv(pit100, 100)


def ipiv_outs(ip10):
    """C2 outs = (ip10 // 10) * 3 + ip10 % 10 (ip10 // 10 toward zero; ip10 >= 0 here)."""
    return idiv(ip10, 10) * 3 + ip10 % 10


def season_stats_inputs(season):
    """Career-total inputs from a season-half record (C2 order, 25 values)."""
    g = lambda k: _get(season, *F[k])
    return {
        'G': g('games'),
        'AB': g('ab_l') + g('ab_r'), 'H': g('h_l') + g('h_r'),
        '2B': g('d_l') + g('d_r'), '3B': g('t_l') + g('t_r'), 'HR': g('hr_l') + g('hr_r'),
        'R': g('runs'), 'RBI': g('rbi'), 'BB': g('bb_l') + g('bb_r'), 'SO': g('so_l') + g('so_r'),
        'SB': g('sb'), 'CS': g('cs'), 'E': g('e1') + g('e2'),
        'W': g('w'), 'L': g('l'), 'SV': g('sv'), 'GS': g('gs'), 'CG': g('cg'), 'SHO': g('sho'),
        'OUTS': ipiv_outs(g('ip10')), 'ER': g('er'),
        'PH': g('ph_l') + g('ph_r'), 'PBB': g('pbb_l') + g('pbb_r'),
        'PSO': g('pso_l') + g('pso_r'), 'PHR': g('phr_l') + g('phr_r'),
    }


def season_league(teams):
    """teams = [(v20_path, team_lg_id)] with unmatched stems already skipped.
    Returns (per_player war10 dict keyed by (team_lg_id, rec_index), league dict with
    L_* and pf1000 table)."""
    maj_path = None
    ldir = os.path.dirname(teams[0][0]) if teams else None
    cands = sorted(glob.glob(os.path.join(ldir, '*.MAJ'))) if ldir else []
    if cands:
        maj_path = cands[0]
    pf = park_factors(maj_path) if maj_path else {}
    bats, pits, aggregate = [], [], {}
    for path, lg_id in teams:
        t = Team.load(path)
        for i in range(40):
            if not t.players[i].active:
                continue
            rec = t.players[i + 40].raw
            roster = t.players[i].raw
            games = _get(rec, *F['games'])
            pos1 = _get(roster, *F['pos1']) & 15
            if pos1 == 0:
                ip10 = _get(rec, *F['ip10'])
                outs = ipiv_outs(ip10)
                er = _get(rec, *F['er'])
                if outs > 0:
                    pits.append((outs, er))
            else:
                ab, h, d, tt, hr, bb, sb, cs, runs = player_bat_inputs(rec)
                s1 = h - d - tt - hr
                pa = ab + bb
                if pa > 0:
                    lw100 = 47 * s1 + 78 * d + 109 * tt + 140 * hr + 33 * bb + 20 * sb \
                        - 41 * cs - 27 * (ab - h)
                    bats.append((lw100, pa, runs))
    aggregate['L_lw'] = sum(b[0] for b in bats)
    aggregate['L_pa'] = sum(b[1] for b in bats)
    aggregate['L_runs'] = sum(b[2] for b in bats)
    aggregate['L_er'] = sum(p[1] for p in pits)
    aggregate['L_outs'] = sum(p[0] for p in pits)
    per = {}
    for path, lg_id in teams:
        t = Team.load(path)
        for i in range(40):
            if not t.players[i].active:
                continue
            rec = t.players[i + 40].raw
            roster = t.players[i].raw
            games = _get(rec, *F['games'])
            pos1 = _get(roster, *F['pos1']) & 15
            if pos1 == 0:
                w10 = pitcher_war10(rec, games, aggregate)
            else:
                w10 = batter_war10(rec, roster, games, aggregate
                                   | {'pf1000': pf.get(lg_id, 1000)})
            per[(lg_id, i)] = w10
    aggregate['pf1000'] = pf
    return per, aggregate


def park_factor1000(home_rs, home_ra, away_g, away_rs, away_ra, home_g):
    """pf1000 = 1000 * ((home_rs + home_ra) * away_g) / ((away_rs + away_ra) * home_g),
    clamped 900..1100; 1000 if any term is 0."""
    den_h = home_rs + home_ra
    den_a = away_rs + away_ra
    if den_h == 0 or den_a == 0 or away_g == 0 or home_g == 0:
        return 1000
    pf = idiv(1000 * den_h * away_g, den_a * home_g)
    return max(PF_MIN, min(PF_MAX, pf))


def park_factors(maj_path):
    """pf1000 per league-global team id from the MAJ (both halves of doubleheaders)."""
    m = maj.Maj.load(maj_path)
    out = {}
    for lg in ('AL', 'NL'):
        base = 0 if lg == 'AL' else 16
        for slot in range(16):
            lg_id = base + slot
            home_rs = home_ra = away_rs = away_ra = home_g = away_g = 0
            for day in range(maj.DAYS):
                mask, mask2 = m.played(lg, day)
                row = m.results(lg, day)
                row2 = m.results2(lg, day)
                sched = m.schedule(lg, day)
                dhmask = m.dh(lg)
                for si, (away, home) in enumerate(sched):
                    bit = 0x80 >> si
                    if not (mask & bit):
                        continue
                    ra, rh = row[2 * si], row[2 * si + 1]
                    if home == lg_id:
                        home_rs += rh; home_ra += ra; home_g += 1
                    elif away == lg_id:
                        away_rs += ra; away_ra += rh; away_g += 1
                    if (dhmask & bit) and (mask2 & bit):
                        ra2, rh2 = row2[2 * si], row2[2 * si + 1]
                        if home == lg_id:
                            home_rs += rh2; home_ra += ra2; home_g += 1
                        elif away == lg_id:
                            away_rs += ra2; away_ra += rh2; away_g += 1
            if home_g or away_g:
                out[lg_id] = park_factor1000(home_rs, home_ra, away_g, away_rs, away_ra, home_g)
    return out


def jaws10(career_war10, top7):
    """C2 JAWS10 = (career + sum of the used top-7 entries) / 2 toward zero."""
    used = [v for v in top7 if v != -32768]
    return idiv(career_war10 + sum(used), 2)


def hof_passes(entry):
    """C3: seasons >= 10 AND any of the eight criteria. entry dict with the career
    totals, career WAR10 and JAWS10 (keys as in the C2 table plus 'WAR10'/'JAWS10')."""
    if entry.get('seasons_played', 0) < 10:
        return False
    if entry.get('H', 0) >= 3000: return True
    if entry.get('HR', 0) >= 500: return True
    ab = entry.get('AB', 0)
    if ab >= 5000 and idiv(entry.get('H', 0) * 1000, ab) >= 300: return True
    if entry.get('W', 0) >= 300: return True
    if entry.get('PSO', 0) >= 3000: return True
    if entry.get('SV', 0) >= 400: return True
    if entry.get('WAR10', 0) >= 600: return True
    if entry.get('JAWS10', 0) >= 500: return True
    return False


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    mp = maj_path(argv[1])
    teams = []
    for p in sorted(glob.glob(os.path.join(argv[1], '*.V20'))):
        lg_id = slot_from_stem(mp, os.path.basename(p)[:-4])
        if lg_id is None:
            continue                # unmatched stems (ALLSTAR files) are skipped
        teams.append((p, lg_id))
    if not teams:
        raise SystemExit('no V20 matches a MAJ stem in ' + argv[1])
    per, lg = season_league(teams)
    for (lg_id, i), w in sorted(per.items()):
        print(f'{lg_id:2d} rec {i:2d}  WAR10 {w}')


def maj_path(ldir):
    c = sorted(glob.glob(os.path.join(ldir, '*.MAJ')))
    return c[0] if c else None


def slot_from_stem(mp, stem):
    """league-global id from the MAJ stem match, case-insensitive; None = no match
    (ALLSTAR files: their MAJ stems start with NUL)."""
    if mp is None:
        return None
    m = maj.Maj.load(mp)
    for lg in ('AL', 'NL'):
        base = 0 if lg == 'AL' else 16
        for s in range(16):
            if m.stem(lg, s).lower() == stem.lower():
                return base + s
    return None


if __name__ == '__main__':
    main(sys.argv)
