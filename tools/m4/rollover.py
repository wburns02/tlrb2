#!/usr/bin/env python3
"""M4 rollover REFERENCE implementation (Python), contract C1 (notes/M4_CONTRACT.md).
The 16-bit asm patch must reproduce these byte outputs exactly; the gate diffs rig
output against this prediction.

Semantics (C1):
  A season IS the league dir (CLASSIC.MAJ + 26 .V20). At season end records 40..79 hold
  the completed season's stats (BACK-accumulated); records 0..39 hold bio+ratings plus
  the CAREER stat line.

  Quality tier, computed ONCE per player from the ROSTER half ratings BEFORE any change:
    pitcher (pos1 & 15 == 0): qs = control + velocity + endurance
                              tier = 0 if qs < 23, 1 if qs < 26, 2 if qs < 28, else 3
    batter: qs = power + hit_run + speed + range
            tier = 0 if qs < 32, 1 if qs < 36, 2 if qs < 39, else 3
    (thresholds = p50/p75/p90 of the shipped CLASSIC league)

  rollover(league_dir, out_dir, cfg):
    1. career merge:  career = sat_add(career, season) per STAT field (u8 fields cap 255,
       u16 cap 65535; L+R merged independently)
    2. aging:         age+1 (both halves), year_off+1, exp+1 if season games > 0
    3a. evidence      (progression flag AND season games > 0): per rating in the rating
                      order, new = old + ((96 * (target - old) + 128) >> 8), clamp 1..15;
                      target = ratings formula on the season record (tools/ratings.py)
    3b. drift         (progression flag, regardless of games): per rating in the rating
                      order, ONE draw ALWAYS: d = draw() & 0xff; v = current value;
                      cap = 10 for endurance, else 12.
                        age2 <= 26: g = 90 if age2 <= 22, 64 if age2 <= 24, else 32;
                                    if d < g and v < cap: v += 1
                        27 <= age2 <= 31: no change (draw still consumed)
                        age2 >= 32: base = 40 (32..33), 64 (34..35), 96 (36..37),
                                    128 (38..39), 160 (40+); mult = [4, 4, 3, 2][tier];
                                    p = (base * mult) >> 2; if d < p and v > 1: v -= 1
    4. retirement     (retirement flag): NEVER forced.
                        age2 < 33: not retired, NO draw
                        age2 >= 33: base = 10 (33..34), 20 (35..36), 36 (37..38),
                                    56 (39..40), 80 (41..42), 110 (43+);
                                    mult = [4, 4, 3, 2][tier]; p = (base * mult) >> 2;
                                    if season games == 0: p = min(255, p * 2)
                                    d = draw() & 0xff; retired iff d < p
    5. history:       HISTORY.DAT (league dir): per season: year, champion, W-L table,
                      retirees; players archived with career line
  The stock Start New Season (zeroing 40..79, new schedule) still runs afterwards; we
  only pre-process the set before handing it to the stock path.

  Rating order (evidence, drift and RNG draw order):
    batters: power, bunt, hit_run, speed, range, arm
    pitchers: control, velocity, endurance
  Draw order per player: the drift draws (6 or 3) then the retirement draw. The RNG
  stream continues across players and teams (sorted *.V20 order, records 0..39).

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
BATTER_RATINGS = [('power', ratings.power), ('bunt', ratings.bunt), ('hit_run', ratings.hit_and_run),
                  ('speed', ratings.speed), ('range', ratings.rng), ('arm', ratings.arm)]
PITCHER_RATINGS = [('control', ratings.control), ('velocity', ratings.velocity),
                   ('endurance', ratings.endurance)]
SAT = {'u8': 255, 'u16': 65535}
# C1 drift base by age2 bucket (>= 32), and retirement base by age2 bucket (>= 33)
DRIFT_BASE = lambda age2: 40 if age2 <= 33 else 64 if age2 <= 35 else 96 \
    if age2 <= 37 else 128 if age2 <= 39 else 160
RETIRE_BASE = lambda age2: 10 if age2 <= 34 else 20 if age2 <= 36 else 36 \
    if age2 <= 38 else 56 if age2 <= 40 else 80 if age2 <= 42 else 110
TIER_MULT = (4, 4, 3, 2)
DRAFT_CAP = {'endurance': 10, 'control': 12, 'velocity': 12, 'power': 12, 'bunt': 12,
             'hit_run': 12, 'speed': 12, 'range': 12, 'arm': 12}
ENDURANCE_CAP = 10


def k_delta(old, target, k):
    """new = old + (k*(target-old) + 128) >> 8 with k positive (evidence uses 96),
    arithmetic shift (Python >> on negatives floors, same as x86 sar), clamp 1..15."""
    v = (k * (target - old) + 128) >> 8
    return max(1, min(15, old + v))


def tier_of(rec):
    """C1 quality tier from the ROSTER half ratings, before any change.
    pitcher (pos1 & 15 == 0) -> [control, velocity, endurance], else the batting four."""
    pitcher = rec[F['pos1'][0]] & 15 == 0
    if pitcher:
        qs = _get(rec, *F['control']) + _get(rec, *F['velocity']) + _get(rec, *F['endurance'])
        return 0 if qs < 23 else 1 if qs < 26 else 2 if qs < 28 else 3
    qs = _get(rec, *F['power']) + _get(rec, *F['hit_run']) + _get(rec, *F['speed']) \
        + _get(rec, *F['range'])
    return 0 if qs < 32 else 1 if qs < 36 else 2 if qs < 39 else 3


def sat_add(a, b, kind):
    return min(SAT[kind], a + b)


class Rng:
    """xorshift16, the asm port's exact generator; draw order is the C1 order:
    one drift draw per rating (6 batter / 3 pitcher), then the retirement draw."""
    def __init__(self, seed=1):
        self.s = seed & 0xffff          # blob parity: xorshift(0) stays 0

    def draw(self):
        s = self.s
        s ^= (s << 7) & 0xFFFF
        s ^= s >> 9
        s ^= (s << 8) & 0xFFFF
        self.s = s
        return s


def rollover_player(rec_roster, rec_season, cfg, rng, log):
    """Mutate rec_roster (career half) in place from rec_season. Returns retire bool."""
    s_bio = lambda r: {k: _get(r, *F[k]) if F[k][1] in ('u8', 'u16') else None
                       for k in ('age', 'year_off', 'exp', 'games')}
    s_b = s_bio(rec_season)
    # tier from the ROSTER half BEFORE any change
    tier = tier_of(rec_roster)
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
    _set(rec_roster, *F['year_off'], (s_b['year_off'] + 1) & 0xff)
    if s_b['games'] > 0:
        _set(rec_roster, *F['exp'], min(255, _get(rec_roster, *F['exp']) + 1))
    # 3a. evidence: only with the progression flag AND season games > 0
    if cfg.get('progress', True) and s_b['games'] > 0:
        pitcher = _get(rec_roster, *F['pos1']) & 15 == 0   # pos code 0 = P
        table = PITCHER_RATINGS if pitcher else BATTER_RATINGS
        for name, fn in table:
            off, kind = F[name]
            old = _get(rec_roster, off, kind)
            target = fn(rec_season)
            new = k_delta(old, target, 96)
            if new != old and log is not None:
                log.append({'rating': name, 'old': old, 'target': target, 'new': new})
            _set(rec_roster, off, kind, new)
    # 3b. drift: only with the progression flag, regardless of games, one draw always
    if cfg.get('progress', True):
        pitcher = _get(rec_roster, *F['pos1']) & 15 == 0   # pos code 0 = P
        table = PITCHER_RATINGS if pitcher else BATTER_RATINGS
        age2 = _get(rec_roster, *F['age'])
        for name, _fn in table:
            d = rng.draw() & 0xff
            off, kind = F[name]
            v = _get(rec_roster, off, kind)
            if age2 <= 26:
                g = 90 if age2 <= 22 else 64 if age2 <= 24 else 32
                if d < g and v < DRAFT_CAP[name]:
                    v += 1
            elif age2 <= 31:
                pass                       # no change, the draw is still consumed
            else:
                base = DRIFT_BASE(age2)
                p = (base * TIER_MULT[tier]) >> 2
                if d < p and v > 1:
                    v -= 1
            _set(rec_roster, off, kind, v)
    # 4. retirement: never forced; draw only at age2 >= 33
    age2 = _get(rec_roster, *F['age'])
    retire = False
    if cfg.get('retire', True) and age2 >= 33:
        base = RETIRE_BASE(age2)
        p = (base * TIER_MULT[tier]) >> 2
        if s_b['games'] == 0:
            p = min(255, p * 2)
        retire = (rng.draw() & 0xff) < p
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
