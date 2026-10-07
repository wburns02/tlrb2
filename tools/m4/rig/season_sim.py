#!/usr/bin/env python3
"""Drive one full season from new season to rollover via timed action sequence.

Follows the spec from season_driver_spec.md: coordinates and timing are verified working.
State: menu -> new season -> regular season -> all-star -> playoffs -> WS -> rollover -> done.

Usage: season_sim.py INSTALL_ROOT SEASON_NUM
"""
import sys
import os
import subprocess
import time
import logging
from pathlib import Path

# Import from the rig tools
sys.path.insert(0, os.path.dirname(__file__))

INSTALL_ROOT = sys.argv[1] if len(sys.argv) > 1 else '/mnt/nvme/tlrb2/work/dyn/c'
SEASON_NUM = int(sys.argv[2]) if len(sys.argv) > 2 else 1

LOGS_DIR = Path('/mnt/nvme/tlrb2/logs/t6')
LOG_PATH = LOGS_DIR / f'season_{SEASON_NUM}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

DISPLAY = ':98'
D_ENV = {'DISPLAY': DISPLAY}

def long_press(x, y, hold=0.5, wait=2):
    """Long press at (x,y): mousemove, 0.2s delay, mousedown, hold, mouseup, wait."""
    subprocess.run(['xdotool', 'mousemove', str(x), str(y)], env=D_ENV, check=True)
    time.sleep(0.2)
    subprocess.run(['xdotool', 'mousedown', '1'], env=D_ENV, check=True)
    time.sleep(hold)
    subprocess.run(['xdotool', 'mouseup', '1'], env=D_ENV, check=True)
    time.sleep(wait)
    log.info(f'long_press({x}, {y}, hold={hold:.1f}, wait={wait:.1f})')

def key_press(key_name, wait=1):
    """Send key to active window."""
    try:
        wid = subprocess.run(['xdotool', 'search', '--class', '.'],
                             env=D_ENV, capture_output=True, text=True, check=True)
        wid = wid.stdout.strip().split()[0] if wid.stdout.strip() else ''
        if wid:
            subprocess.run(['xdotool', 'key', '--window', wid, key_name],
                           env=D_ENV, check=True)
        else:
            subprocess.run(['xdotool', 'key', key_name], env=D_ENV, check=True)
    except:
        subprocess.run(['xdotool', 'key', key_name], env=D_ENV, check=False)
    time.sleep(wait)
    log.info(f'key_press({key_name}, wait={wait:.1f})')

def day_byte():
    """Read MAJ day byte at offset 0x20a."""
    maj = os.path.join(INSTALL_ROOT, 'TEAMS', 'CLASSIC', 'CLASSIC.MAJ')
    try:
        with open(maj, 'rb') as f:
            f.seek(0x20a)
            return f.read(1)[0]
    except OSError:
        return None

def history_byte0():
    """Read HISTORY.DAT byte 0 (rolled flag)."""
    hist = os.path.join(INSTALL_ROOT, 'HISTORY.DAT')
    try:
        with open(hist, 'rb') as f:
            return f.read(1)[0]
    except OSError:
        return None

def run_season():
    """Execute the season sequence."""
    log.info(f'Starting season {SEASON_NUM}')

    # Initial state check
    day = day_byte()
    hist0 = history_byte0()
    log.info(f'Initial: day=0x{day:02x}, hist0={hist0}')

    # Step 1: Navigate to SEASON menu (from main menu)
    log.info('Step 1: Open SEASON menu')
    long_press(304, 209, 0.5, 2)  # SEASON pulldown

    # Step 2: Select "PLAY LEAGUE GAMES" for a running season, or "START NEW SEASON"
    # For the first run or when day=0xf3, we start new season
    if day == 0xf3 or day is None:
        log.info('Step 2: Starting new season')
        long_press(352, 321, 0.5, 2)  # START NEW SEASON

        # Step 3: Confirm NEW SEASON
        log.info('Step 3: Confirm new season')
        long_press(430, 592, 0.5, 3)  # NEW SEASON button

        # Step 4: Confirm YES
        log.info('Step 4: Confirm YES')
        long_press(514, 456, 0.5, 2)  # YES

        # Step 5: Confirm DH
        log.info('Step 5: Confirm DH DONE')
        long_press(458, 468, 0.5, 2)  # DH DONE

        # Step 6: Injuries YES
        log.info('Step 6: Confirm injuries')
        long_press(514, 456, 0.5, 3)  # injuries YES

    # Step 7: Play through regular season
    log.info('Step 7: Play THRU REGULAR SEASON')
    long_press(732, 528, 0.5, 2)  # THRU REGULAR SEASON
    long_press(510, 592, 0.5, 5)  # PLAY

    # Regular season runs
    log.info('Step 8: Waiting for regular season to complete (~10 min)')
    time.sleep(600)  # Wait 10 minutes for regular season

    # Step 9: All-Star break handling (auto-skip or manual)
    day = day_byte()
    log.info(f'After regular season: day=0x{day:02x}')
    if day and 0x6a <= day <= 0x80:
        log.info('Step 9: All-Star break detected, continuing')
        key_press('Return', 1)
        time.sleep(5)

    # Step 10: Play through World Series
    log.info('Step 10: Play THRU WORLD SERIES')
    long_press(732, 546, 0.5, 2)  # THRU WORLD SERIES
    long_press(510, 592, 0.5, 3)  # PLAY

    # WS runs
    log.info('Step 11: Waiting for World Series (~5 min)')
    time.sleep(300)  # Wait 5 minutes for WS

    # Step 12: Exit and save
    log.info('Step 12: Returning to menu (QUIT)')
    key_press('Return', 2)
    key_press('Escape', 2)
    long_press(234, 341, 0.5, 5)  # QUIT

    # Step 13: Verify rollover
    log.info('Step 13: Verifying rollover')
    time.sleep(10)  # Let dynasty run and flush
    day = day_byte()
    hist0 = history_byte0()
    log.info(f'Final: day=0x{day:02x}, hist0={hist0}')

    if day == 0xf3 and hist0 == 1:
        log.info(f'Season {SEASON_NUM} PASSED')
        return True
    else:
        log.warning(f'Season {SEASON_NUM} end state mismatch: day=0x{day:02x}, hist0={hist0}')
        return False

if __name__ == '__main__':
    try:
        success = run_season()
        sys.exit(0 if success else 1)
    except Exception as e:
        log.exception(f'Fatal error: {e}')
        sys.exit(1)
