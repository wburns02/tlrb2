#!/usr/bin/env python3
"""M4 rollover REFERENCE implementation (Python). The 16-bit asm patch must reproduce
these byte outputs exactly; the P1 gate diffs rig output against this prediction.

Semantics (see notes/M4_DESIGN.md):
  A season IS the league dir (CLASSIC.MAJ + 26 .V20). At season end records 40..79 hold
  the completed season's stats (BACK-accumulated); records 0..39 hold bio+ratings plus
  the CAREER stat line (stock shipped leagues already carry career numbers there, so
  existing screens show them for free).

  rollover(league_dir, out_dir, cfg):
    1. career merge:  career = sat_add(career, season) per STAT field (u8 fields cap 255,
       u16 cap 65535; L+R merged independently)
    2. aging:         age+1, year_off+1, exp+1 if season games > 0 (both halves)
    3. progression:   target = ratings_from_stats(season record) via tools/ratings.py;
                      new = old + k(age)*(target-old) with k as num/256 integer math
                      (matching the asm port exactly: delta = (k*(t-o) + 128) >> 8 signed)
       progressed ratings: batters power/bunt/hit_run/speed/range/arm,
                           pitchers control/velocity/endurance
    4. retirement:    age >= 41, or age >= 36 and rand < (age-35)*8%, or (pitcher)
                      endurance+arm both < 3 -> record marked inactive (byte 0 = 0),
                      player archived in the season history
    5. history:       HISTORY.DAT (league dir): per season: year, champion, W-L table,
                      retirees; players archived with career line
  The stock Start New Season (zeroing 40..79, new schedule) still runs afterwards; we
  only pre-process the set before handing it to the stock path.

  Integer-math contract for the asm port:
    k(age): age<=20:192, 21-24:128, 25-27:64, 28:0, 29-34:224 (i.e. -32/256), >=35:192
            (-64/256); sign carried by whether target < old.
    delta = (k * (target - old) + 128) >> 8 computed in 16-bit signed, then added,
    clamped 1..15.
    retirement RNG: xorshift16 state seeded with --seed, one draw per player only in the
    age>=36 branch, threshold (age-35)*20 out of 255 (8%/year over 35); identical to the
    asm port (rollover.asm) so byte-exact comparison holds.

usage:
  rollover.py IN_DIR OUT_DIR [--seed 1] [--no-progress] [--no-retire] [--dry]
  rollover.py predict IN_DIR            # print what WOULD change, no writes
"""
import sys, os, glob, json, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from v20 import Team, _get, _set, F          # noqa: E402
import ratings                               # noqa: E402

# every field BACK accumulates into 40..79 and that we carry as career totals in 0..39
STAT_FIELDS = [
    # batters + fielders
    'runs', 'rbi', 'sh', 'sb', 'cs', 'ab_l', 'ab_r', 'h_l', 'h_r', 'd_l', 'd_r', 't_l', 't_r',
    'hr_l', 'hr_r', 'bb_l', 'bb_r', 'so_l', 'so_r', 'gb_pct10', 'gb_pull10', 'gb_opp10',
    'fb_pull10', 'fb_opp10', 'pinch_ab', 'pinch_h', 'pinch_hr',
    'po1', 'po2', 'a1', 'a2', 'e1', 'e2', 'dp1', 'dp2', 'pb', 'rto_a', 'rto_b',
    # pitchers
    'w', 'l', 'cg', 'gs', 'sho', 'sv', 'ip10', 'er', 'runs_allowed', 'bf_l', 'bf_r',
    'ph_l', 'ph_r', 'pd_l', 'pd_r', 'pt_l', 'pt_r', 'pbb_l', 'pbb_r', 'pso_l', 'pso_r',
    'phr_l', 'phr_r', 'bk', 'wp',
]
K_BY_AGE = lambda age: 192 if age <= 20 else 128 if age <= 24 else 64 if age <= 27 else 0 \
    if age == 28 else 224 if age <= 34 else 192
BATTER_RATINGS = [('power', ratings.power), ('bunt', ratings.bunt), ('hit_run', ratings.hit_and_run),
                  ('speed', ratings.speed), ('range', ratings.rng), ('arm', ratings.arm)]
PITCHER_RATINGS = [('control', ratings.control), ('velocity', ratings.velocity),
                   ('endurance', ratings.endurance)]
SAT = {'u8': 255, 'u16': 65535}


def k_delta(old, target, k):
    """new = old + (k*(target-old) + 128) >> 8 with k a SIGNED byte (224 means -32),
    arithmetic shift (Python >> on negatives floors, same as x86 sar), clamp 1..15."""
    ks = k - 256 if k > 128 else k
    v = (ks * (target - old) + 128) >> 8
    return max(1, min(15, old + v))


def sat_add(a, b, kind):
    return min(SAT[kind], a + b)


class Rng:
    """xorshift16, the asm port's exact generator; draw() only called in the age>=36
    retirement branch so draw order matches."""
    def __init__(self, seed=1):
        self.s = seed & 0xffff or 1

    def draw(self):
        s = self.s
        s ^= (s << 7) & 0xFFFF
        s ^= s >> 9
        s ^= (s << 8) & 0xFFFF
        self.s = s
        return s


def rollover_player(rec_roster, rec_season, cfg, rng, log):
    """Mutate rec_roster (career half) in place from rec_season. Returns retire bool."""
    bio = lambda r: {k: _get(r, *F[k]) if F[k][1] in ('u8', 'u16') else None
                     for k in ('age', 'year_off', 'exp', 'games')}
    s_bio = bio(rec_season)
    # 1. career merge with saturation
    for f in STAT_FIELDS:
        off, kind = F[f]
        if kind not in SAT:
            continue
        a, b = _get(rec_roster, off, kind), _get(rec_season, off, kind)
        if b:
            _set(rec_roster, off, kind, sat_add(a, b, kind))
    # 2. aging (both halves; caller applies the same to the twin)
    age = _get(rec_roster, *F['age'])
    _set(rec_roster, *F['age'], min(255, age + 1))
    _set(rec_roster, *F['year_off'], (s_bio['year_off'] + 1) & 0xff)
    if s_bio['games'] > 0:
        _set(rec_roster, *F['exp'], min(255, _get(rec_roster, *F['exp']) + 1))
    # 3. progression
    if cfg.get('progress', True) and s_bio['games'] > 0:
        k = K_BY_AGE(age + 1)
        if k:
            pitcher = _get(rec_roster, *F['pos1']) == 0   # pos code 0 = P
            table = PITCHER_RATINGS if pitcher else BATTER_RATINGS
            for name, fn in table:
                off, kind = F[name]
                old = _get(rec_roster, off, kind)
                target = fn(rec_season)
                new = k_delta(old, target, k)
                if new != old:
                    log.append({'rec': rec_roster is not None, 'rating': name, 'old': old,
                                'target': target, 'new': new})
                _set(rec_roster, off, kind, new)
    # 4. retirement
    age2 = age + 1
    retire = False
    if cfg.get('retire', True):
        if age2 >= 41:
            retire = True
        elif age2 >= 36:
            if (rng.draw() & 0xff) < (age2 - 35) * 20:
                retire = True
        elif _get(rec_roster, *F['endurance']) < 3 and _get(rec_roster, *F['arm']) < 3 \
                and _get(rec_roster, *F['pos1']) == 0:   # pos code 0 = P
            retire = True
    return retire


def rollover_team(path_in, path_out, cfg, rng, report):
    t = Team.load(path_in)
    retirees = []
    for i in range(40):
        r_roster, r_season = t.players[i].raw, t.players[i + 40].raw
        if not t.players[i].active and not t.players[i + 40].active:
            continue
        log = []
        retire = rollover_player(r_roster, r_season, cfg, rng, log)
        # mirror bio+ratings edits to the season-half twin so both halves agree
        for f in ('age', 'year_off', 'exp'):
            off, kind = F[f]
            _set(r_season, off, kind, _get(r_roster, off, kind))
        if retire:
            retirees.append(i)
            r_roster[0] = 0
            r_season[0] = 0
        if log or retire:
            report.append({'team': t.abbr, 'rec': i, 'retire': retire, 'changes': log[:8]})
    t.save(path_out)
    return retirees


def rollover(in_dir, out_dir, cfg=None, seed=1, dry=False):
    cfg = cfg or {}
    os.makedirs(out_dir, exist_ok=True)
    rng = Rng(seed)
    report = []
    all_ret = {}
    for p in sorted(glob.glob(os.path.join(in_dir, '*.V20'))):
        all_ret[os.path.basename(p)] = rollover_team(
            p, os.path.join(out_dir, os.path.basename(p)), cfg, rng, report)
    # MAJ: bump nothing in the reference (stock path rewrites day/schedule); copy through
    maj = os.path.join(in_dir, 'CLASSIC.MAJ')
    if os.path.exists(maj):
        shutil.copy2(maj, os.path.join(out_dir, 'CLASSIC.MAJ'))
    hist = {'seed': seed, 'retirees': all_ret, 'players': report}
    if not dry:
        json.dump(hist, open(os.path.join(out_dir, 'HISTORY.DAT.json'), 'w'), indent=1)
    return hist


def main(a):
    dry = '--dry' in a or a[0] == 'predict'
    in_dir = a[0] if a[0] != 'predict' else a[1]
    out_dir = a[1] if a[0] != 'predict' else '/tmp/m4_predict'
    seed = int(a[a.index('--seed') + 1]) if '--seed' in a else 1
    hist = rollover(in_dir, out_dir, seed=seed,
                    cfg={'progress': '--no-progress' not in a, 'retire': '--no-retire' not in a},
                    dry=dry)
    n_ch = sum(len(r['changes']) for r in hist['players'])
    n_ret = sum(len(v) for v in hist['retirees'].values())
    print(f'players changed: {len(hist["players"])}  rating edits: {n_ch}  retirees: {n_ret}')
    for r in hist['players'][:12]:
        ch = ', '.join(f"{c['rating']} {c['old']}->{c['new']} (t{c['target']})" for c in r['changes'][:4])
        print(f"  {r['team']} rec{r['rec']:02d}{' RETIRE' if r['retire'] else ''} {ch}")


if __name__ == '__main__':
    main(sys.argv[1:])
