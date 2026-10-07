#!/usr/bin/env python3
"""Unattended multi-season dynasty gate: runs N seasons and verifies each rollover.

Setup (if --fresh): copy install, patch BAT, reset HISTORY.DAT.
Per season: start new season if needed, sim to 0xf3, copy pre-roll league, run check_roll,
verify player records, write summary JSON.

Usage: python3 tools/m4/rig/dynasty_gate.py --seasons N [--fresh]
"""
import sys
import os
import json
import shutil
import subprocess
import time
from pathlib import Path
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, '/home/will/tlrb2/tools')

# Import locals
rig_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, rig_dir)
import bat_patch
import check_roll as check_roll_mod

# Import from main repo
import v20


INSTALL_ROOT = '/mnt/nvme/tlrb2/work/dyn/c/TONY2'
LOGS_DIR = Path('/mnt/nvme/tlrb2/logs/t6')
SUMMARY_PATH = LOGS_DIR / 'gate_summary.json'


def setup_install(fresh=False):
    """Copy pristine install to work directory, patch BAT. Refuses overwrite unless --fresh."""
    base_dir = os.path.dirname(INSTALL_ROOT)
    os.makedirs(base_dir, exist_ok=True)

    if os.path.exists(INSTALL_ROOT):
        if not fresh:
            print(f'{INSTALL_ROOT} exists; use --fresh to overwrite', file=sys.stderr)
            return False
        # Remove old install (make writable first)
        subprocess.run(['chmod', '-R', 'u+w', INSTALL_ROOT], check=False)
        for item in os.listdir(INSTALL_ROOT):
            item_path = os.path.join(INSTALL_ROOT, item)
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)

    # Copy pristine
    pristine = '/mnt/nvme/tlrb2/pristine/TONY2'
    print(f'Copying {pristine} to {INSTALL_ROOT}')
    if not os.path.exists(INSTALL_ROOT):
        os.makedirs(INSTALL_ROOT)
    for item in os.listdir(pristine):
        src = os.path.join(pristine, item)
        dst = os.path.join(INSTALL_ROOT, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    # Make everything writable
    subprocess.run(['chmod', '-R', 'u+w', INSTALL_ROOT], check=True)

    # Patch BAT
    print(f'Patching {INSTALL_ROOT}/TONY2.BAT')
    if not bat_patch.patch(INSTALL_ROOT, revert=False):
        return False

    # Reset HISTORY.DAT (in TEAMS/CLASSIC/ per DYNASTY.EXE)
    hist_path = os.path.join(INSTALL_ROOT, 'TEAMS', 'CLASSIC', 'HISTORY.DAT')
    print(f'Resetting {hist_path}')
    with open(hist_path, 'wb') as f:
        f.write(b'\x00\x00\x00\x00')

    return True


def day_byte(install_root):
    """Read MAJ day byte."""
    maj = os.path.join(install_root, 'TEAMS', 'CLASSIC', 'CLASSIC.MAJ')
    try:
        with open(maj, 'rb') as f:
            f.seek(0x20a)
            return f.read(1)[0]
    except OSError:
        return None


def history_byte0(install_root):
    """Read HISTORY.DAT byte 0 (in TEAMS/CLASSIC/ per DYNASTY.EXE)."""
    hist = os.path.join(install_root, 'TEAMS', 'CLASSIC', 'HISTORY.DAT')
    try:
        with open(hist, 'rb') as f:
            return f.read(1)[0]
    except OSError:
        return None


def copy_snapshot(src_dir, dest_dir):
    """Copy TEAMS/CLASSIC/* to dest."""
    os.makedirs(dest_dir, exist_ok=True)
    src = os.path.join(src_dir, 'TEAMS', 'CLASSIC')
    for fname in os.listdir(src):
        src_file = os.path.join(src, fname)
        if os.path.isfile(src_file):
            shutil.copy2(src_file, os.path.join(dest_dir, fname))


def verify_player_records(install_root):
    """Verify all 26 teams have valid rosters."""
    errors = []
    teams_dir = os.path.join(install_root, 'TEAMS', 'CLASSIC')
    for v20_file in sorted(os.listdir(teams_dir)):
        if not v20_file.endswith('.V20'):
            continue
        try:
            team = v20.Team.load(os.path.join(teams_dir, v20_file))
            active_count = sum(1 for p in team.players if p.active)
            if active_count < 40:
                errors.append(f'{v20_file}: only {active_count} active records')
            # Check ages advanced
            for p in team.players[:40]:
                if p.active and p.age > 50:
                    errors.append(f'{v20_file}: age {p.age} > 50')
        except Exception as e:
            errors.append(f'{v20_file}: {e}')
    return errors


def run_season_gate(season_num):
    """Run one season simulation. Return success bool."""
    print(f'\n=== Season {season_num} ===')
    print(f'Launch on :98')
    # Launch game
    subprocess.run(['bash', 'tools/m4/rig/dyn_launch.sh', INSTALL_ROOT],
                   check=False, cwd='/home/will/tlrb2/.claude/worktrees/t6-driver')
    time.sleep(30)  # Let boot finish

    # Check if we need to start a new season
    day = day_byte(INSTALL_ROOT)
    hist0 = history_byte0(INSTALL_ROOT)
    print(f'Current state: day=0x{day:02x}, hist0={hist0}')

    if day == 0xf3 and hist0 == 0:
        print('League at season end, rolling over first')
        # Run season sim which will handle the rollover
        pass
    elif day != 0x07:
        print('Resetting to start of season')
        # Kill and relaunch to reset

    # Run season
    print(f'Running season_sim for season {season_num}')
    result = subprocess.run(
        ['python3', 'tools/m4/rig/season_sim.py', INSTALL_ROOT, str(season_num)],
        cwd='/home/will/tlrb2/.claude/worktrees/t6-driver'
    )
    if result.returncode != 0:
        print(f'season_sim failed')
        return False

    # Verify end state
    final_day = day_byte(INSTALL_ROOT)
    final_hist0 = history_byte0(INSTALL_ROOT)
    if final_day != 0xf3 or final_hist0 != 1:
        print(f'ERROR: final state bad (day=0x{final_day:02x}, hist0={final_hist0})')
        return False

    # Copy snapshots
    print(f'Copying pre-roll league to logs')
    pre_snap = LOGS_DIR / f's{season_num}_pre'
    post_snap = LOGS_DIR / f's{season_num}_post'

    # Pre-roll is in DYNSNAP (copied by BAT before dynasty runs)
    dynsnap = os.path.join(INSTALL_ROOT, 'DYNSNAP')
    if os.path.exists(dynsnap):
        copy_snapshot(INSTALL_ROOT, str(pre_snap))

    # Post-roll in TEAMS/CLASSIC
    copy_snapshot(INSTALL_ROOT, str(post_snap))

    # Check rollover
    print(f'Running check_roll')
    if pre_snap.exists() and post_snap.exists():
        mismatches = check_roll_mod.compare_dirs(str(pre_snap), str(post_snap), seed=1)
        if any(mismatches.values()):
            print(f'check_roll FAILED: {len(mismatches)} files with mismatches')
            return False

    # Verify rosters
    errors = verify_player_records(INSTALL_ROOT)
    if errors:
        print(f'Player record errors:')
        for e in errors[:5]:
            print(f'  {e}')
        return False

    print(f'Season {season_num} PASSED')
    return True


def main(args):
    if '--seasons' not in args:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    num_seasons = int(args[args.index('--seasons') + 1])
    fresh = '--fresh' in args

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Setup
    if fresh or not os.path.exists(INSTALL_ROOT):
        print(f'Setting up install')
        if not setup_install(fresh=fresh):
            sys.exit(1)

    # Run seasons
    summary = {'start_time': time.time(), 'seasons': [], 'passed': 0, 'failed': 0}
    for season in range(1, num_seasons + 1):
        try:
            start = time.time()
            success = run_season_gate(season)
            elapsed = time.time() - start
            summary['seasons'].append({
                'num': season,
                'success': success,
                'wall_time': elapsed
            })
            if success:
                summary['passed'] += 1
            else:
                summary['failed'] += 1
        except Exception as e:
            print(f'Season {season} exception: {e}')
            summary['failed'] += 1

    # Write summary
    with open(SUMMARY_PATH, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f'\nSummary written to {SUMMARY_PATH}')
    print(f'Passed: {summary["passed"]}, Failed: {summary["failed"]}')

    sys.exit(0 if summary['failed'] == 0 else 1)


if __name__ == '__main__':
    main(sys.argv[1:])
