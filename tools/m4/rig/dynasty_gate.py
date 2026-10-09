#!/usr/bin/env python3
"""Unattended multi-season dynasty gate on the :98 rig.

Per season: season_sim drives the game through the World Series and QUIT (the BAT loop copies the league to
C:\\DYNSNAP and DYNASTY rolls it), then this script snapshots DYNSNAP to logs/t6/sN_pre and TEAMS/CLASSIC to
logs/t6/sN_post BEFORE relaunching (the relaunch overwrites DYNSNAP), checks the roll byte for byte against the
Python reference (check_roll; with ROSTERS.EXE installed, the whole DYNASTY + HISTWR + ROSTERS chain, rosters_check),
runs roster sanity checks, and relaunches for the next season.

usage: dynasty_gate.py --seasons N [--first K] [--fresh] [--full-rosters]
  --first K        number of the first season run here (default: one past the highest logs/t6/sN_post)
  --fresh          rebuild the dedicated install from work/c (never touches work/c itself), patch the BAT,
                   install the repo DYNASTY.EXE, HISTWR.EXE, ROSTERS.EXE and DYNVIEW.EXE, remove HISTORY.DAT and MILESTON.DAT
  --full-rosters   require 40 named roster records per team after the roll (DYNASTY builds with the rookie fill)
  --league DIR     with --fresh: copy a built league (e.g. /mnt/nvme/tlrb2/hist/1985) over TEAMS/CLASSIC; every
                   file in DIR must already exist there under the same name
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
import tempfile
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
from m4 import history          # noqa: E402

INSTALL = season_sim.INSTALL
SOURCE = '/mnt/nvme/tlrb2/work/c/TONY2'
LOGS = season_sim.LOGS
SUMMARY = os.path.join(LOGS, 'gate_summary.json')
RATINGS = [n for n, _ in rollover.BATTER_RATINGS + rollover.PITCHER_RATINGS]
PITCH_RATINGS = ('control', 'velocity', 'endurance')


def install_league(lg, src):
    """Copy every file of the built league src over the same-named files of the league dir lg.
    Refuses (SystemExit) an empty src or a file name lg does not already have."""
    names = sorted(n for n in os.listdir(src) if os.path.isfile(os.path.join(src, n)))
    have = set(os.listdir(lg))
    missing = [n for n in names if n not in have]
    if not names or missing:
        sys.exit(f'--league {src}: not a league dir for {lg} (unknown files {missing[:5]})')
    for n in names:
        shutil.copy2(os.path.join(src, n), os.path.join(lg, n))
    return names


def setup_fresh(install, league_src=None):
    if os.path.realpath(install) != os.path.realpath(INSTALL):
        sys.exit(f'--fresh only rebuilds the dedicated install {INSTALL}')
    if os.path.exists(install):
        shutil.rmtree(install)
    shutil.copytree(SOURCE, install)
    if not bat_patch.patch(install):
        sys.exit('BAT patch failed')
    shutil.copy2(os.path.join(TOOLS, 'm4', 'blob', 'DYNASTY.EXE'), os.path.join(install, 'DYNASTY.EXE'))
    shutil.copy2(os.path.join(TOOLS, 'm4', 'histwr', 'HISTWR.EXE'), os.path.join(install, 'HISTWR.EXE'))
    shutil.copy2(os.path.join(TOOLS, 'm4', 'rosters_c', 'ROSTERS.EXE'), os.path.join(install, 'ROSTERS.EXE'))
    shutil.copy2(os.path.join(TOOLS, 'm4', 'dynview_c', 'DYNVIEW.EXE'), os.path.join(install, 'DYNVIEW.EXE'))
    # a stale DYNSNAP (an earlier run's HISTORY/MILESTON/RETIRED) would feed the
    # next roll and the history check; the BAT copy only overwrites, so clear it
    snap = os.path.join(os.path.dirname(install), 'DYNSNAP')
    if os.path.isdir(snap):
        for name in os.listdir(snap):
            p = os.path.join(snap, name)
            if os.path.isfile(p):
                os.remove(p)
    lg = season_sim.league(install)
    for name in ('HISTORY.DAT', 'MILESTON.DAT'):
        p = os.path.join(lg, name)
        if os.path.exists(p):
            os.remove(p)
    if league_src:
        install_league(lg, league_src)


def launch(install, tries=2):
    """Start DOSBox-X and wait for the ball menu. An Escape during the PLAY intro has hung the boot on a black
    screen, so wait quietly first, nudge only after that, and relaunch once if the menu never comes. The boot
    DYNASTY MODE screen (dynview /title, before the intro) is passed with Return."""
    for attempt in range(tries):
        subprocess.run(['bash', os.path.join(HERE, 'dyn_launch.sh'), install], check=True)
        time.sleep(15)
        dr = season_sim.Driver(0, install)
        try:
            dr.wait_for('ball_menu', 60, every=3, nudge=lambda st: st == 'dynview' and rig.key('Return'))
            return
        except season_sim.SimError:
            pass
        try:
            dr.wait_for('ball_menu', 60, every=3, nudge=lambda st: rig.key('Escape'))
            return
        except season_sim.SimError:
            if attempt == tries - 1:
                raise
            dr.log('no ball menu after 135s: relaunching')


def snapshot(src, dst):
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for f in os.listdir(src):
        p = os.path.join(src, f)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(dst, f))


def done_flag(league):
    """HISTORY byte 0; a league that never rolled has no HISTORY.DAT (C2: missing = 0)."""
    hp = os.path.join(league, 'HISTORY.DAT')
    if not os.path.exists(hp):
        return 0
    b = open(hp, 'rb').read(1)
    return b[0] if b else 0


def roll_seed(pre, post):
    """The xorshift16 word DYNASTY started this roll from: C2 v1 files keep it at bytes 8..9; the 4-byte P1 file
    only has the word at bytes 1..2 of the pre-roll copy."""
    hp = open(os.path.join(post, 'HISTORY.DAT'), 'rb').read()
    if len(hp) >= 32:
        return struct.unpack_from('<H', hp, 8)[0]
    return struct.unpack_from('<H', open(os.path.join(pre, 'HISTORY.DAT'), 'rb').read(), 1)[0]


def roster_checks(pre, post, full):
    """Survivors aged exactly +1, ratings 1..15 on every named record (pitching ratings may be 0 on non-pitchers, C4), and (full) 40 named records per team."""
    errs, named = [], {}
    for pp in sorted(glob.glob(os.path.join(post, '*.V20'))):
        name = os.path.basename(pp)
        if name.upper().startswith('POOL'):
            continue                    # free-agent pools (C6): checked byte for byte by rosters_check
        a, b = v20.Team.load(os.path.join(pre, name)), v20.Team.load(pp)
        named[name] = sum(1 for i in range(40) if b.players[i].active)
        if full and named[name] != 40:
            errs.append(f'{name}: {named[name]} named roster records, want 40')
        for i in range(40):
            x, y = a.players[i], b.players[i]
            if y.active:
                # C4 batter rookies carry no pitching ratings (nibbles 0); only pitchers need 1..15 there
                lo = {r: (0 if r in PITCH_RATINGS and (y.raw[31] & 15) != 0 else 1) for r in RATINGS}
                bad = [r for r in RATINGS if not lo[r] <= y[r] <= 15]
                if bad:
                    errs.append(f'{name} rec {i}: rating out of 1..15: {bad}')
            if x.active and y.active and bytes(x.raw[0:20]) == bytes(y.raw[0:20]):
                if y['age'] != min(255, x['age'] + 1):
                    errs.append(f'{name} rec {i}: age {x["age"]} -> {y["age"]}')
    return errs, named


def expect_histwr(pre, post, dst, rosters_ran=False):
    """Write what HISTWR wrote after the roll (C5) into dst: HISTORY.DAT and MILESTON.DAT, from the DYNSNAP snapshot
    (pre). The rng word HISTWR kept at bytes 1..2 is DYNASTY's end word: post bytes 1..2, or post bytes 16..17 when
    ROSTERS ran after it (C6 moves it there and writes its own end word to 1..2). Returns [] or ['RETIRED.DAT missing']."""
    hp = os.path.join(dst, 'HISTORY.DAT')
    pp = os.path.join(pre, 'HISTORY.DAT')
    base = bytearray(open(pp, 'rb').read()) if os.path.exists(pp) else bytearray()
    if len(base) < 32:
        base += bytes(32 - len(base))
    ppost = open(os.path.join(post, 'HISTORY.DAT'), 'rb').read()
    base[0] = 1
    base[1:3] = ppost[16:18] if rosters_ran else ppost[1:3]
    base[8:10] = ppost[8:10]
    open(hp, 'wb').write(bytes(base))
    pm = os.path.join(pre, 'MILESTON.DAT')
    if os.path.exists(pm):
        shutil.copyfile(pm, os.path.join(dst, 'MILESTON.DAT'))
    rp = os.path.join(pre, 'RETIRED.DAT')
    if not os.path.exists(rp):
        return ['RETIRED.DAT missing']
    raw = open(rp, 'rb').read()
    nteam = raw[0]
    retirees = {}
    off = 1
    for _ in range(nteam):
        name = bytes(raw[off:off + 13]).split(b'\0')[0].decode('latin-1')
        flags = raw[off + 13:off + 53]
        idxs = [i for i in range(40) if flags[i]]
        if idxs:
            retirees[name] = idxs
        off += 53
    season = history.History.load(hp).seasons_recorded + 1
    history.record_season(pre, hp, season)
    history.mark_retired(hp, pre, retirees, season)
    return []


ROSTERS_HDR = (1, 2, 16, 17)      # HISTORY header bytes ROSTERS owns (C6); rosters_check verifies them


def _first_diff(want, got):
    return next((i for i in range(min(len(want), len(got))) if want[i] != got[i]), min(len(want), len(got)))


def history_check(pre, post, rosters_ran=False):
    """Byte-for-byte expectation for what HISTWR wrote after the roll (C5), from the DYNSNAP snapshot (pre). With
    ROSTERS after it, the bytes ROSTERS owns are left to rosters_check. Returns a list of error strings (empty = PASS)."""
    errs = []
    with tempfile.TemporaryDirectory() as tmp:
        e = expect_histwr(pre, post, tmp, rosters_ran)
        if e:
            return e
        want = bytearray(open(os.path.join(tmp, 'HISTORY.DAT'), 'rb').read())
        got = bytearray(open(os.path.join(post, 'HISTORY.DAT'), 'rb').read())
        if rosters_ran:
            for i in ROSTERS_HDR:
                if i < len(want) and i < len(got):
                    want[i] = got[i]
        if want != got:
            errs.append(f'HISTORY.DAT differs at offset {_first_diff(want, got)} '
                        f'(want {len(want)} B, got {len(got)} B)')
        ms_tmp = os.path.join(tmp, 'MILESTON.DAT')     # written by record_season
        ms_post = os.path.join(post, 'MILESTON.DAT')
        if os.path.exists(ms_tmp) != os.path.exists(ms_post):
            errs.append('MILESTON.DAT exists on only one side')
        elif os.path.exists(ms_tmp) and open(ms_tmp, 'rb').read() != open(ms_post, 'rb').read():
            errs.append('MILESTON.DAT differs')
    return errs


def rosters_check(pre, post, seed, fill=True):
    """The whole rolled branch of the C8 BAT replayed in Python on the DYNSNAP snapshot: DYNASTY (dynasty_ref), HISTWR
    (expect_histwr), ROSTERS (rosters.run on DYNSNAP + DYNSNAP/RETIRED.DAT). Every V20 (teams and pools), HISTORY.DAT
    and ROSTERS.TXT must equal the post league byte for byte. Returns a list of error strings (empty = PASS)."""
    from m4 import dynasty_ref
    from m4 import rosters
    errs = []
    with tempfile.TemporaryDirectory() as ref:
        dynasty_ref.roll_league(pre, ref, seed, fill=fill)
        e = expect_histwr(pre, post, ref, rosters_ran=True)
        if e:
            return e
        rc = rosters.run(ref, pre, os.path.join(ref, 'HISTORY.DAT'), os.path.join(pre, 'RETIRED.DAT'))
        if rc != 0:
            return [f'rosters reference exit {rc}']
        names = lambda d: {n for n in os.listdir(d) if n.upper().endswith('.V20')}
        rn, pn = names(ref), names(post)
        for n in sorted(rn ^ pn):
            errs.append(f'{n} only in {"reference" if n in rn else "post"}')
        for n in sorted(rn & pn) + ['HISTORY.DAT', 'ROSTERS.TXT']:
            wp, gp = os.path.join(ref, n), os.path.join(post, n)
            if not os.path.exists(wp) or not os.path.exists(gp):
                errs.append(f'{n} missing ({"reference" if not os.path.exists(wp) else "post"})')
                continue
            want, got = open(wp, 'rb').read(), open(gp, 'rb').read()
            if want != got:
                errs.append(f'{n} differs at offset {_first_diff(want, got)}')
    return errs


def gate_one(n, install, full, fill=True, do_history=True):
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
    pre_h0 = done_flag(pre)
    if pre_day != 0xf3 or pre_h0 != 0:
        rec['error'] = f'DYNSNAP is not the pre-roll league (day 0x{pre_day:02x}, done flag {pre_h0})'
        dr.log(rec['error'])
        return rec, dr
    seed = rec['seed'] = roll_seed(pre, post)
    rosters_ran = rec['rosters'] = os.path.exists(os.path.join(install, 'ROSTERS.EXE'))
    if rosters_ran:
        # ROSTERS rewrote the rolled V20s: the reference is the whole DYNASTY + HISTWR + ROSTERS chain
        rerrs = rosters_check(pre, post, seed, fill=fill)
        rec['check_roll'] = 'PASS' if not rerrs else rerrs[:50]
    else:
        mm = check_roll.compare_dirs(pre, post, seed, fill=fill)
        rec['check_roll'] = 'PASS' if not any(mm.values()) else {k: [str(x) for x in v] for k, v in mm.items() if v}
    errs, named = roster_checks(pre, post, full)
    rec['roster_errors'] = errs[:50]
    rec['named_total'] = sum(named.values())
    if do_history:
        herrs = history_check(pre, post, rosters_ran)
        rec['history_check'] = 'PASS' if not herrs else herrs
    else:
        rec['history_check'] = 'SKIPPED'
    rec['ok'] = (rec['check_roll'] == 'PASS' and not errs
                 and rec['history_check'] in ('PASS', 'SKIPPED'))
    dr.log(f'roll seed {seed}: check_roll {"PASS" if rec["check_roll"] == "PASS" else "FAIL"}, '
           f'{len(errs)} roster errors, {rec["named_total"]} named records, '
           f'history {rec["history_check"] if isinstance(rec["history_check"], str) else "FAIL"}')
    # a failure names its first few mismatches in the log (the record alone went unread once)
    for key in ('check_roll', 'roster_errors', 'history_check'):
        v = rec.get(key)
        if v and v not in ('PASS', 'SKIPPED'):
            items = v if isinstance(v, list) else [f'{k}: {x}' for k, x in v.items()] if isinstance(v, dict) else [v]
            for x in items[:5]:
                dr.log(f'  {key}: {x}')
    return rec, dr


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', type=int, required=True)
    ap.add_argument('--first', type=int)
    ap.add_argument('--fresh', action='store_true')
    ap.add_argument('--full-rosters', action='store_true')
    ap.add_argument('--install', default=INSTALL)
    ap.add_argument("--no-fill", action="store_true", help="installed DYNASTY.EXE predates the C4 fill")
    ap.add_argument('--league', default=None)
    ap.add_argument("--no-history", action="store_true",
                    help="skip the history_check (install has no HISTWR.EXE)")
    a = ap.parse_args(argv)
    if a.league and not a.fresh:
        sys.exit('--league needs --fresh')
    if a.fresh:
        setup_fresh(a.install, a.league)
    first = a.first
    if first is None:
        done = [int(os.path.basename(p)[1:-5]) for p in glob.glob(os.path.join(LOGS, 's*_post'))]
        first = max(done, default=0) + 1
    if a.fresh or rig.window() is None:
        launch(a.install)
    else:
        # resuming: a run that stopped after a roll leaves the game at the DOS prompt
        dr = season_sim.Driver(first, a.install)
        if dr.state()[0] == 'dos_prompt':
            dr.relaunch()
    summary = {'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'install': a.install, 'seasons': []}
    ok = True
    for n in range(first, first + a.seasons):
        rec, dr = gate_one(n, a.install, a.full_rosters, fill=not a.no_fill,
                           do_history=not a.no_history)
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
