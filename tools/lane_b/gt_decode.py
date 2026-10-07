#!/usr/bin/env python3
"""Decode the lineup / defense / pitching block of GAME.TMP (7446 B, MAIN->BB hand-off, also 1..10.SAV and PLAYOFFS.* records).
Layout decoded by Lane B session 4 (2026-10-06), checked against both V20 headers on every captured run (see --check).
Side 0 = VISITOR, side 1 = HOME (stems at 7169 are written home first). Player ids are V20 record numbers 0..39.
usage: gt_decode.py GAME.TMP [TEAMDIR]     dump;  with TEAMDIR (TEAMS/CLASSIC) also verifies against the V20 headers"""
import sys
sys.path.insert(0, __file__.rsplit('/tools/', 1)[0] + '/tools')
LU, DEF, REST, STARTERS, PEN, INGAME, SLOT, POSV, CURP = 6763, 6781, 6799, 6843, 6853, 6895, 6975, 7055, 7139
NIGHT, DHF, STEM, RULES = 7143, 7193, 7169, 7428   # RULES: pipes, errors, injuries, use stats (1 = yes)

def decode(d):
    r = {}
    r['home_stem'] = d[STEM:STEM + 8].decode('latin-1'); r['vis_stem'] = d[STEM + 8:STEM + 16].decode('latin-1')
    r['dh'] = d[DHF]; r['night'] = d[NIGHT]
    r['pipes'], r['errors'], r['injuries'], r['use_stats'] = d[RULES:RULES + 4]
    S = []
    for s in (0, 1):
        pen = d[PEN + 21 * s:PEN + 21 * s + 11]
        S.append(dict(lineup=list(d[LU + 9 * s:LU + 9 * s + 9]), defense=list(d[DEF + 9 * s:DEF + 9 * s + 9]),
                      rest=[x for x in d[REST + 22 * s:REST + 22 * s + 22] if x != 0xff],
                      starters=list(d[STARTERS + 5 * s:STARTERS + 5 * s + 5]), relievers=list(pen[:5]), reserve_p=list(pen[5:]),
                      in_game=[i for i in range(40) if d[INGAME + 40 * s + i]],
                      slot=[d[SLOT + 40 * s + i] for i in range(40)], pos=[d[POSV + 40 * s + i] for i in range(40)],
                      cur_pitcher=d[CURP + s]))
    r['vis'], r['home'] = S
    return r

def check(d, teamdir):
    from v20 import Team
    r = decode(d); bad = []
    for side, stem in (('vis', r['vis_stem']), ('home', r['home_stem'])):
        t = Team.load(f'{teamdir}/{stem.upper()}.V20'); o = r['home' if side == 'vis' else 'vis']; s = r[side]
        opp_stem = r['home_stem'] if side == 'vis' else r['vis_stem']
        ot = Team.load(f'{teamdir}/{opp_stem.upper()}.V20'); opp_p = ot.players[ot.staff()[ot.rotation_ptr]]
        rhp = opp_p['throws']
        dh = r['dh']; lu, de = t.lineup(dh, rhp), t.defense(dh, rhp)
        exp_lu = lu if dh else lu[:8] + [t.staff()[t.rotation_ptr]]
        if s['lineup'] != exp_lu: bad.append((side, 'lineup', s['lineup'], exp_lu))
        if s['defense'][:8 + dh] != de[:8 + dh]: bad.append((side, 'defense', s['defense'], de))
        if s['starters'] != t.staff()[:5]: bad.append((side, 'starters', s['starters'], t.staff()[:5]))
    return r, bad

if __name__ == '__main__':
    d = open(sys.argv[1], 'rb').read()
    r = decode(d) if len(sys.argv) < 3 else check(d, sys.argv[2])[0]
    for k, v in r.items():
        print(k, v if not isinstance(v, dict) else '')
        if isinstance(v, dict):
            for kk, vv in v.items():
                if kk not in ('slot', 'pos'): print('   ', kk, vv)
    if len(sys.argv) > 2:
        print('MISMATCH' if check(d, sys.argv[2])[1] else 'OK', check(d, sys.argv[2])[1])
