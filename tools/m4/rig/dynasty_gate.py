#!/usr/bin/env python3
"""Unattended multi-season dynasty gate on the :98 rig.

Per season: season_sim drives the game through the World Series and QUIT (the BAT loop copies the league to
C:\\DYNSNAP and DYNASTY rolls it), then this script snapshots DYNSNAP to logs/t6/sN_pre and TEAMS/CLASSIC to
logs/t6/sN_post BEFORE relaunching (the relaunch overwrites DYNSNAP), checks the roll byte for byte against the
Python reference (check_roll), runs roster sanity checks, and relaunches for the next season.

usage: dynasty_gate.py --seasons N [--first K] [--fresh] [--full-rosters]
  --first K        number of the first season run here (default: one past the highest logs/t6/sN_post)
  --fresh          rebuild the dedicated install from work/c (never touches work/c itself), patch the BAT,
                   install the repo DYNASTY.EXE, reset HISTORY.DAT to 4 zero bytes
  --full-rosters   require 40 named roster records per team after the roll (DYNASTY builds with the rookie fill)
Exit 0 only if every roll passes. Summary: logs/t6/gate_summary.json.
"""
import argparse
import glob
import json
import os
import shutil
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, TOOLS)
import rig                      # noqa: E402  (before check_roll: m4.team_fill puts tools/m4 on sys.path,
import season_sim               # noqa: E402   where the rig/ package would shadow rig.py)
import bat_patch                # noqa: E402
import check_roll               # noqa: E402
import v20                      # noqa: E402
from m4 import rollover         # noqa: E402

INSTALL = season_sim.INSTALL
SOURCE = '/mnt/nvme/tlrb2/work/c/TONY2'
LOGS = season_sim.LOGS
SUMMARY = os.path.join(LOGS, 'gate_summary.json')
RATINGS = [n for n, _ in rollover.BATTER_RATINGS + rollover.PITCHER_RATINGS]


def setup_fresh(install):
    if os.path.realpath(install) != os.path.realpath(INSTALL):
        sys.exit(f'--fresh only rebuilds the dedicated install {INSTALL}')
    if os.path.exists(install):
        shutil.rmtree(install)
    shutil.copytree(SOURCE, install)
    if not bat_patch.patch(install):
        sys.exit('BAT patch failed')
    shutil.copy2(os.path.join(TOOLS, 'm4', 'blob', 'DYNASTY.EXE'), os.path.join(install, 'DYNASTY.EXE'))
    with open(os.path.join(season_sim.league(install), 'HISTORY.DAT'), 'wb') as f:
        f.write(bytes(4))


def launch(install):
    subprocess.run(['bash', os.path.join(HERE, 'dyn_launch.sh'), install], check=True)
    time.sleep(15)
    dr = season_sim.Driver(0, install)
    dr.wait_for('ball_menu', 120, every=3, nudge=lambda st: rig.key('Escape'))


def snapshot(src, dst):
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for f in os.listdir(src):
        p = os.path.join(src, f)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(dst, f))


def roll_seed(pre, post):
    """The xorshift16 word DYNASTY started this roll from: C2 v1 files keep it at bytes 8..9; the 4-byte P1 file
    only has the word at bytes 1..2 of the pre-roll copy."""
    hp = open(os.path.join(post, 'HISTORY.DAT'), 'rb').read()
    if len(hp) >= 32:
        return struct.unpack_from('<H', hp, 8)[0]
    return struct.unpack_from('<H', open(os.path.join(pre, 'HISTORY.DAT'), 'rb').read(), 1)[0]


def roster_checks(pre, post, full):
    """Survivors aged exactly +1, ratings 1..15 on every named record, and (full) 40 named records per team."""
    errs, named = [], {}
    for pp in sorted(glob.glob(os.path.join(post, '*.V20'))):
        name = os.path.basename(pp)
        a, b = v20.Team.load(os.path.join(pre, name)), v20.Team.load(pp)
        named[name] = sum(1 for i in range(40) if b.players[i].active)
        if full and named[name] != 40:
            errs.append(f'{name}: {named[name]} named roster records, want 40')
        for i in range(40):
            x, y = a.players[i], b.players[i]
            if y.active:
                bad = [r for r in RATINGS if not 1 <= y[r] <= 15]
                if bad:
                    errs.append(f'{name} rec {i}: rating out of 1..15: {bad}')
            if x.active and y.active and bytes(x.raw[0:20]) == bytes(y.raw[0:20]):
                if y['age'] != min(255, x['age'] + 1):
                    errs.append(f'{name} rec {i}: age {x["age"]} -> {y["age"]}')
    return errs, named


def gate_one(n, install, full, fill=True):
    rec = {'season': n, 'ok': False}
    t0 = time.time()
    dr = season_sim.Driver(n, install)
    try:
        rec['sim_min'] = round(dr.season(), 1)
    except season_sim.SimError as e:
        dr.log(f'FAIL {e}')
        rec['error'] = str(e)
        return rec, dr
    pre, post = os.path.join(LOGS, f's{n}_pre'), os.path.join(LOGS, f's{n}_post')
    snapshot(os.path.join(os.path.dirname(install), 'DYNSNAP'), pre)
    snapshot(season_sim.league(install), post)
    rec['wall_min'] = round((time.time() - t0) / 60, 1)
    # the pre-roll copy must be the league DYNASTY saw: season over, not yet rolled
    with open(os.path.join(pre, 'CLASSIC.MAJ'), 'rb') as f:
        f.seek(0x20a)
        pre_day = f.read(1)[0]
    pre_h0 = open(os.path.join(pre, 'HISTORY.DAT'), 'rb').read(1)[0]
    if pre_day != 0xf3 or pre_h0 != 0:
        rec['error'] = f'DYNSNAP is not the pre-roll league (day 0x{pre_day:02x}, done flag {pre_h0})'
        dr.log(rec['error'])
        return rec, dr
    seed = rec['seed'] = roll_seed(pre, post)
    mm = check_roll.compare_dirs(pre, post, seed, fill=fill)
    rec['check_roll'] = 'PASS' if not any(mm.values()) else {k: [str(x) for x in v] for k, v in mm.items() if v}
    errs, named = roster_checks(pre, post, full)
    rec['roster_errors'] = errs[:50]
    rec['named_total'] = sum(named.values())
    rec['ok'] = rec['check_roll'] == 'PASS' and not errs
    dr.log(f'roll seed {seed}: check_roll {"PASS" if rec["check_roll"] == "PASS" else "FAIL"}, '
           f'{len(errs)} roster errors, {rec["named_total"]} named records')
    return rec, dr


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', type=int, required=True)
    ap.add_argument('--first', type=int)
    ap.add_argument('--fresh', action='store_true')
    ap.add_argument('--full-rosters', action='store_true')
    ap.add_argument('--install', default=INSTALL)
    ap.add_argument("--no-fill", action="store_true", help="installed DYNASTY.EXE predates the C4 fill")
    a = ap.parse_args(argv)
    if a.fresh:
        setup_fresh(a.install)
    if a.fresh or rig.window() is None:
        launch(a.install)
    first = a.first
    if first is None:
        done = [int(os.path.basename(p)[1:-5]) for p in glob.glob(os.path.join(LOGS, 's*_post'))]
        first = max(done, default=0) + 1
    summary = {'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'install': a.install, 'seasons': []}
    ok = True
    for n in range(first, first + a.seasons):
        rec, dr = gate_one(n, a.install, a.full_rosters, fill=not a.no_fill)
        summary['seasons'].append(rec)
        json.dump(summary, open(SUMMARY, 'w'), indent=1)
        if not rec['ok']:
            ok = False
            break
        try:
            dr.relaunch()
        except season_sim.SimError as e:
            dr.log(f'FAIL relaunch: {e}')
            summary['seasons'][-1]['relaunch_error'] = str(e)
            ok = False
            break
    summary['ok'] = ok
    json.dump(summary, open(SUMMARY, 'w'), indent=1)
    print(json.dumps({'ok': ok, 'seasons': [(r['season'], r['ok']) for r in summary['seasons']]}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
