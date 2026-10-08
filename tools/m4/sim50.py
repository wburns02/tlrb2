#!/usr/bin/env python3
"""Offline multi-season harness for the C6 roster pipeline (contract C6,
tools/m4/rosters.py). Replaces the game's BACK + league play with a season
model: every season rolls the league (C1), runs the C6 offseason on the
rolled league, and feeds the next season from the rewritten rosters.

usage: sim50.py --seasons N --seed S --era E [--managed LGID ...]
                [--set KEY=VAL ...] --out DIR
  --set overrides rosters.T entries; REL rows as REL=16,69,33,5,48,...; ints
  only. Season dirs DIR/<k> (k = 1..seasons, the current and previous season
  kept on disk), metrics one JSON line per season in DIR/metrics.jsonl, the
  summary in DIR/summary.txt and stdout.
"""
import argparse
import glob
import json
import os
import random
import shutil
import struct
import sys

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(_TOOLS)
for _p in (_ROOT, _TOOLS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import maj                                       # noqa: E402
import v20                                       # noqa: E402
from m4 import rosters, history as history_mod  # noqa: E402
from m4 import dynasty_ref                       # noqa: E402
from m4 import rollover                          # noqa: E402
from v20 import HDR, REC, F                      # noqa: E402

S1_PRE = '/mnt/nvme/tlrb2/fixtures/t4/s1_pre'
POOL_FILES = rosters.POOL_FILES
ROLL_CFG = {'progress': True, 'retire': True, 'evidence': False}

# metric keys, one JSON line per season
MKeys = ('season', 'retired', 'released', 'market', 'signed', 'traded',
         'unsigned_retirements', 'draft_class', 'pool_size', 'turnover',
         'team_change', 'avg_age', 'spread', 'best_w', 'worst_w')

# season-model stat lines. Batters: (games, ab_l, bb_l); pitchers:
# (games, ip10). Field starters = the 8 field positions of the DH vs-RHP
# lineup set, DH = the DH slot, bench = the other active batters,
# rotation = +111..+115, relief = +116..+120.
BATTER_STATS = {'field': (150, 540, 60), 'dh': (140, 495, 55),
                'bench': (60, 135, 15), 'none': (0, 0, 0)}
PITCHER_STATS = {'rotation': (32, 2000), 'relief': (55, 700), 'none': (0, 0)}
SEASON_STATS_OFF = 40


def stdev(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    return (sum((v - mean) ** 2 for v in vals) / n) ** 0.5


def hist_word(raw):
    if len(raw) < 3:
        return 1
    w = raw[1] | raw[2] << 8
    return w if w else 1


# ---------------------------------------------------------------------------
# Season model: depth read, team strength, W/L, season stats
# ---------------------------------------------------------------------------

def deep_lists(img):
    """The DH vs-RHP lineup set of one team image (bytearray) plus the staff
    and reserves: (lineup slots, defense positions, bench slots, staff slots,
    reserve slots), 0xff entries dropped. Header offsets per C6."""
    o = 27                                  # dh 1 * 18 + vs 1 * 9
    lineup = [s for s in img[v20.H_LINEUP + o:v20.H_LINEUP + o + 9] if s != 0xff]
    defense = list(img[v20.H_DEF + o:v20.H_DEF + o + 9])
    b0 = v20.H_BENCH + 14 + 7               # the DH vs-RHP set: block 3, +215..+221
    bench = [s for s in img[b0:b0 + 7] if s != 0xff]
    staff = [s for s in img[v20.H_STAFF:v20.H_STAFF + 10] if s != 0xff]
    reserves = [s for s in img[v20.H_RESERVE:v20.H_RESERVE + 15] if s != 0xff]
    return lineup, defense, bench, staff, reserves


def rec_of(img, slot):
    return img[HDR + REC * slot:HDR + REC * (slot + 1)]


def team_strength(img):
    """Strength = sum S of the 9 DH-set starters + 2 * sum S of the 5 rotation
    pitchers + sum S of the 5 relievers; S = rosters.score on the roster
    half."""
    lineup, defense, bench, staff, reserves = deep_lists(img)
    total = 0
    for s in lineup:
        total += rosters.score(rec_of(img, s))
    for s in staff[:5]:                     # rotation
        total += 2 * rosters.score(rec_of(img, s))
    for s in staff[5:10]:                   # relievers
        total += rosters.score(rec_of(img, s))
    return total


def write_season_stats(img, book):
    """Season-half records (roster slot i + 40) from book = {slot: kind}:
    batters (games, ab_l, bb_l), pitchers (games, ip10); zero for every other
    named player; pool files and vacant slots untouched."""
    for slot in range(40):
        ro = HDR + REC * slot
        if not img[ro]:
            continue
        so = HDR + REC * (slot + SEASON_STATS_OFF)
        rec = bytearray(img[so:so + REC])
        # zero the season stat fields only; the twin's name/bio/ratings stay
        for f in rollover.STAT_FIELDS + ['games']:
            v20._set(rec, *F[f], 0)
        kind = book.get(slot, 'none')
        pitcher = img[ro + F['pos1'][0]] & 15 == 0
        if pitcher:
            games, ip10 = PITCHER_STATS[kind]
            v20._set(rec, *F['games'], games)
            v20._set(rec, *F['ip10'], ip10)
        else:
            games, ab_l, bb_l = BATTER_STATS[kind]
            v20._set(rec, *F['games'], games)
            v20._set(rec, *F['ab_l'], ab_l)
            v20._set(rec, *F['bb_l'], bb_l)
        img[so:so + REC] = rec


def form_noise(league_dir, rng, p):
    """Stand-in for the real game's evidence step (off here: the season stats are
    synthetic): each rating of each named team player moves +-1 (equal odds, clamp
    1..15) with probability p / 256. 0 = off."""
    if not p:
        return
    for path in sorted(glob.glob(os.path.join(league_dir, '*.V20'))):
        name = os.path.basename(path)
        if name.startswith('ALLSTAR') or name in POOL_FILES:
            continue
        img = bytearray(open(path, 'rb').read())
        for slot in range(40):
            ro = HDR + REC * slot
            if not img[ro]:
                continue
            rec = bytearray(img[ro:ro + REC])
            pitcher = rec[F['pos1'][0]] & 15 == 0
            table = rollover.PITCHER_RATINGS if pitcher else rollover.BATTER_RATINGS
            for rname, _fn in table:
                if rng.random() * 256 < p:
                    v = v20._get(rec, *F[rname]) + rng.choice((-1, 1))
                    v20._set(rec, *F[rname], max(1, min(15, v)))
            img[ro:ro + REC] = rec
        with open(path, 'wb') as f:
            f.write(bytes(img))


def season_model(league_dir, rng):
    """One season on the snapshot dir: team strength from the current rosters,
    W/L into the MAJ (snapshot MAJ, set_wl per (lg, slot)), then the
    season-half stat lines. Returns (wl, strengths) with wl = {lg_id: W}."""
    mp = history_mod.maj_or_none(league_dir)
    m = maj.Maj(open(mp, 'rb').read())
    teams = history_mod.mapped_teams(league_dir, m)
    strengths = {}
    imgs = {}
    for p, lg_id in teams:
        img = bytearray(open(p, 'rb').read())
        imgs[p] = img
        strengths[lg_id] = team_strength(img)
    vals = list(strengths.values())
    mean = sum(vals) / len(vals)
    sd = stdev(vals)
    wl = {}
    for p, lg_id in teams:
        z = (strengths[lg_id] - mean) / sd if sd > 0 else 0.0
        pct = max(0.30, min(0.70, 0.5 + 0.06 * z + rng.gauss(0, 0.03)))
        w = round(162 * pct)
        wl[lg_id] = w
        m.set_wl('AL' if lg_id < 16 else 'NL',
                 lg_id if lg_id < 16 else lg_id - 16, w, 162 - w)
    m.save(mp)
    for p, lg_id in teams:
        img = imgs[p]
        lineup, defense, bench, staff, reserves = deep_lists(img)
        book = {}
        for s, pos in zip(lineup, defense):
            book[s] = 'dh' if pos == 9 else 'field'
        for s in bench:
            book.setdefault(s, 'bench')
        for s in staff[:5]:
            book[s] = 'rotation'
        for s in staff[5:10]:
            book[s] = 'relief'
        write_season_stats(img, book)
        with open(p, 'wb') as f:
            f.write(bytes(img))
    return wl, strengths


# ---------------------------------------------------------------------------
# One season: the roll + the C6 offseason
# ---------------------------------------------------------------------------

def write_retired(path, retire_map):
    """C5 RETIRED.DAT: u8 nteam, then nteam x (13 B DTA name NUL padded,
    40 B flags), teams in the roll's sorted order. retire_map = {file: [rec]}."""
    names = sorted(retire_map)
    d = bytearray()
    d.append(len(names) & 0xff)
    for name in names:
        d += name.upper().encode('latin-1')[:12].ljust(13, b'\0')
        flags = bytearray(40)
        for i in (retire_map[name] or []):
            if 0 <= i < 40:
                flags[i] = 1
        d += flags
    with open(path, 'wb') as f:
        f.write(bytes(d))


def event_counts(rolled_dir):
    """Event counts from the ROSTERS.TXT the C6 run wrote."""
    counts = {'RET': 0, 'REL': 0, 'MKT': 0, 'SIGN': 0, 'TRADE': 0,
              'DRAFT': 0, 'POOLRET': 0}
    p = os.path.join(rolled_dir, 'ROSTERS.TXT')
    if not os.path.isfile(p):
        return counts
    for line in open(p, 'rb').read().decode('latin-1').splitlines():
        parts = line.split(' ', 1)
        if parts and parts[0] in counts:
            counts[parts[0]] += 1
    return counts


def pool_size(league_dir):
    n = 0
    for name in POOL_FILES:
        p = os.path.join(league_dir, name)
        if not os.path.isfile(p):
            continue
        img = open(p, 'rb').read()
        n += sum(1 for s in range(40) if img[HDR + REC * s])
    return n


def one_season(snap, rolled, word):
    """3. The C1 roll of SNAP with the carried stream word, the C5
    RETIRED.DAT from the retirees, then the C6 offseason reading SNAP as the
    pre-roll snapshot; HISTORY bytes 1..2 = the ROSTERS end word, 8..9 = the
    roll start word. Returns the roll result and the event counts."""
    hist_path = os.path.join(snap, 'HISTORY.DAT')
    result = dynasty_ref.roll_league(snap, rolled, word, cfg=ROLL_CFG)
    retired_path = os.path.join(rolled, 'RETIRED.DAT')
    write_retired(retired_path, result['retirees'])
    rc = rosters.run(rolled, snap, hist_path, retired_path)
    if rc != 0:
        raise RuntimeError('rosters.run failed')
    counts = event_counts(rolled)
    counts['retired'] = sum(len(v) for v in result['retirees'].values())
    counts['unsigned_retirements'] = counts['RET'] + counts['POOLRET']
    # the carried header: HISTORY bytes 1..2 = rng_end, 8..9 = the roll start
    raw = open(hist_path, 'rb').read()
    carry = bytearray(raw[:32].ljust(32, b'\0'))
    carry[1], carry[2] = raw[1], raw[2]     # rosters wrote its end word to 1..2
    carry[8], carry[9] = word & 0xff, (word >> 8) & 0xff
    with open(os.path.join(rolled, 'HISTORY.DAT'), 'wb') as f:
        f.write(bytes(carry))
    return result, counts


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def birth_of(age, season):
    return season + 1000 - age


def active_sets(league_dir, season):
    """Active players per team after the offseason, from the header lists:
    10 P (+111..+120) + 15 B (every DH set's lineup + bench). Returns
    (per_team, ages) with per_team = [{identity: team_index}] and
    ages = {identity: age} (age = record byte 20), identity = (name bytes
    0..19, birth = season + 1000 - age)."""
    out = []
    ages = {}
    files = [p for p in sorted(glob.glob(os.path.join(league_dir, '*.V20')))
             if not os.path.basename(p).startswith('ALLSTAR')
             and os.path.basename(p) not in POOL_FILES]
    for ti, p in enumerate(files):
        img = open(p, 'rb').read()
        active = set()
        for s in img[v20.H_STAFF:v20.H_STAFF + 10]:
            if s != 0xff:
                active.add(s)
        for dh in (0, 1):
            for vs in (0, 1):
                o = v20.H_LINEUP + dh * 18 + vs * 9
                for s in img[o:o + 9]:
                    if s != 0xff:
                        active.add(s)
                o = v20.H_BENCH + dh * 14 + vs * 7
                for s in img[o:o + 7]:
                    if s != 0xff:
                        active.add(s)
        players = {}
        for s in active:
            r = img[HDR + REC * s:HDR + REC * (s + 1)]
            age = r[F['age'][0]]
            ident = (bytes(r[0:20]), birth_of(age, season))
            players[ident] = ti
            ages[ident] = age
        out.append(players)
    return out, ages


def season_metrics(season, league_dir, counts, strengths, wl, prev_active,
                   prev_team_of):
    """One metrics line. prev_active = last season's active identity -> team
    index (None in season 1)."""
    actives, active_ages = active_sets(league_dir, season)
    now = {}
    now_team_of = {}
    for players in actives:
        for ident, ti in players.items():
            now[ident] = ti
            now_team_of[ident] = ti
    turnover = None
    if prev_active is not None:
        gone = sum(1 for ident in prev_active if ident not in now)
        turnover = gone / len(prev_active) if prev_active else 0.0
    team_change = None
    if prev_active is not None:
        both = [ident for ident in prev_active if ident in now]
        if both:
            moved = sum(1 for ident in both
                        if now_team_of[ident] != prev_team_of[ident])
            team_change = moved / len(both)
    ages = [active_ages[idt] for idt in now]
    wvals = list(wl.values())
    line = {
        'season': season,
        'retired': counts['retired'],
        'released': counts['REL'],
        'market': counts['MKT'],
        'signed': counts['SIGN'],
        'traded': counts['TRADE'],
        'unsigned_retirements': counts['unsigned_retirements'],
        'draft_class': counts['DRAFT'],
        'pool_size': pool_size(league_dir),
        'turnover': turnover,
        'team_change': team_change,
        'avg_age': sum(ages) / len(ages) if ages else 0.0,
        'spread': stdev(list(strengths.values())),
        'best_w': max(wvals) if wvals else 0,
        'worst_w': min(wvals) if wvals else 0,
    }
    return line


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize(lines, out_dir, hist, seasons):
    """summary.txt and stdout: per-metric means over seasons 6..N (burn-in 5)
    next to the targets, career stats, the dynasty/doormat check and the
    max/min team W over the run. hist = {'seasons_by_ident': {ident: [seasons]},
    'ages': {ident: [ages]}, 'wl_by_team': {season: {lg_id: W}}}."""
    burn = [ln for ln in lines if ln['season'] > 5] or lines
    out = []

    def mean(k):
        vals = [ln[k] for ln in burn if ln.get(k) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    seasons_by_ident = hist['seasons_by_ident']
    ages = hist['ages']
    out.append('sim50 summary (%d seasons, means over seasons %d..%d)'
               % (seasons, burn[0]['season'] if burn else 0,
                  lines[-1]['season'] if lines else 0))
    out.append('turnover             %.3f  (target 0.216)' % mean('turnover'))
    out.append('team_change          %.3f  (target 0.210)' % mean('team_change'))
    out.append('avg_age              %.2f' % mean('avg_age'))
    out.append('spread               %.2f' % mean('spread'))

    # careers: players first active in seasons 6..N-10, counted at the end
    cohort = [i for i, ss in seasons_by_ident.items()
              if ss and 6 <= min(ss) <= seasons - 10]
    lens = [(max(seasons_by_ident[i]) - min(seasons_by_ident[i]) + 1)
            for i in cohort]
    if lens:
        ls = sorted(lens)
        med_len = ls[(len(ls) - 1) // 2]
        one = sum(1 for n in lens if n == 1) / len(lens)
        out.append('career length (n=%d) mean %.2f median %d seasons  (target 7.01 / 6)'
               % (len(lens), sum(ls) / len(ls), med_len))
        out.append('one-season careers   %.3f  (target 0.181)' % one)
        first = sorted(ages[i][0] for i in cohort)
        last = sorted(ages[i][-1] for i in cohort)
        out.append('cohort age first/last active  median %d / %d  (target 24 / 30)'
                   % (first[(len(first) - 1) // 2], last[(len(last) - 1) // 2]))
    # final active age: medians over the players active in the last season
    final_ages = sorted(ages[i][-1] for i, ss in seasons_by_ident.items()
                        if ss and ss[-1] == seasons)
    if final_ages:
        out.append('final active age     median %d  (target 28)'
                   % final_ages[(len(final_ages) - 1) // 2])
    # dynasty / doormat: any team above .600 (W >= 98) or below .400 (W <= 65)
    # for 10+ straight seasons
    dyn = doormat = 0
    all_ids = set()
    for wl in hist['wl_by_team'].values():
        all_ids.update(wl)
    for lg_id in sorted(all_ids):
        ws = [hist['wl_by_team'].get(s, {}).get(lg_id) for s in range(1, seasons + 1)]
        run_up = run_down = 0
        for w in ws:
            if w is not None and w >= 98:
                run_up += 1
                dyn = max(dyn, run_up)
            else:
                run_up = 0
            if w is not None and w <= 65:
                run_down += 1
                doormat = max(doormat, run_down)
            else:
                run_down = 0
    all_w = [w for wl in hist['wl_by_team'].values() for w in wl.values()]
    out.append('dynasty streaks 10+  %d   doormat streaks 10+  %d' % (dyn, doormat))
    if all_w:
        out.append('team W over the run  max %d  min %d' % (max(all_w), min(all_w)))
    text = '\n'.join(out) + '\n'
    with open(os.path.join(out_dir, 'summary.txt'), 'w') as f:
        f.write(text)
    sys.stdout.write(text)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_set(args):
    t = {}
    for kv in args:
        k, v = kv.split('=', 1)
        if k == 'REL':
            row = [int(x) for x in v.split(',')]
            t['REL'] = [row[i:i + 4] for i in range(0, len(row), 4)]
        else:
            t[k] = int(v)
    return t


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', type=int, required=True)
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--era', type=int, required=True)
    ap.add_argument('--managed', type=int, nargs='*', default=[])
    ap.add_argument('--set', nargs='*', default=[])
    ap.add_argument('--out', required=True)
    ap.add_argument('--noise', type=int, default=0,
                    help='form noise p/256 per rating per season (evidence stand-in), 0 = off')
    a = ap.parse_args(argv)
    for k, v in parse_set(a.set).items():
        rosters.T[k] = v
    mask = 0
    for lg in (a.managed or []):
        mask |= 1 << lg
    season_model_rng = random.Random(a.seed)
    start_word = a.seed & 0xffff or 1

    if os.path.isdir(a.out):
        shutil.rmtree(a.out)
    os.makedirs(a.out)

    hist = {'seasons_by_ident': {}, 'ages': {}, 'wl_by_team': {}}
    prev_active = None
    prev_team_of = None
    prev_rolled = None
    season_dirs = []
    metrics_path = os.path.join(a.out, 'metrics.jsonl')
    with open(metrics_path, 'w') as mf:
        for k in range(1, a.seasons + 1):
            cur = os.path.join(a.out, str(k))
            os.makedirs(cur)
            # season 1 league = the stock fixture; later = last season's ROLLED
            # (that dir moves here)
            league = os.path.join(cur, 'league')
            if k == 1:
                shutil.copytree(S1_PRE, league)
                with open(os.path.join(league, 'HISTORY.DAT'), 'wb') as f:
                    f.write(bytes(new_history(start_word, a.era, mask)))
            else:
                shutil.move(prev_rolled, league)
            # 1-2. the season model on a snapshot SNAP of the league dir
            snap = os.path.join(cur, 'snap')
            rolled = os.path.join(snap, 'rolled')
            shutil.copytree(league, snap)
            hist_path = os.path.join(snap, 'HISTORY.DAT')
            word = hist_word(open(hist_path, 'rb').read())
            form_noise(snap, season_model_rng, a.noise)
            wl, strengths = season_model(snap, season_model_rng)
            # 3. the roll with the carried word, then the C6 offseason; ROSTERS
            # reads the season stats from SNAP (the pre-roll snapshot)
            result, counts = one_season(snap, rolled, word)
            # 4. ROLLED becomes the league for season k + 1; only the current
            # and previous season dirs stay on disk and RETIRED.DAT is not
            # carried
            os.remove(os.path.join(rolled, 'RETIRED.DAT'))
            prev_rolled = rolled
            if k > 1:
                shutil.rmtree(season_dirs.pop(0))
            season_dirs.append(cur)
            # metrics: the active sets come from the league after ROSTERS
            line = season_metrics(k, league, counts, strengths, wl,
                                  prev_active, prev_team_of)
            mf.write(json.dumps(line) + '\n')
            mf.flush()
            # identity seasons and ages (for the career stats and summary), the
            # next season's comparison sets, and the W/L history
            actives, active_ages = active_sets(league, k)
            pooled = {}
            for ti, players in enumerate(actives):
                for ident in players:
                    hist['seasons_by_ident'].setdefault(ident, []).append(k)
                    hist['ages'].setdefault(ident, []).append(active_ages[ident])
                    pooled[ident] = ti
            prev_team_of = pooled
            prev_active = pooled
            hist['wl_by_team'][k] = wl
    lines = [json.loads(l) for l in open(metrics_path) if l.strip()]
    summarize(lines, a.out, hist, a.seasons)
    return 0


def new_history(word, era, mask):
    """The 32 B HISTORY header: bytes 1..2 = the rng word (S & 0xffff or 1 if
    0), byte 10 = era, bytes 12..15 = the managed mask."""
    d = bytearray(32)
    d[1], d[2] = word & 0xff, (word >> 8) & 0xff
    d[10] = era & 0xff
    struct.pack_into('<I', d, 12, mask & 0xffffffff)
    return d


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
