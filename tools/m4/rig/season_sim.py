#!/usr/bin/env python3
"""Drive one full season from new season to rollover (day 0xf3).

State machine over screens.py identification. Long presses on buttons, Escape/Return for keys.
Stall handling: if screen unchanged 120s and not sim_running, attempt dismissals, give up after 3 cycles.
Log every action with timestamp to logs/t6/season_N.log.

Usage: season_sim.py INSTALL_ROOT SEASON_NUM
"""
import sys
import os
import subprocess
import time
import logging
from pathlib import Path
from PIL import Image

# Import from the rig tools
sys.path.insert(0, os.path.dirname(__file__))
from screens import identify_screen, screenshot

INSTALL_ROOT = sys.argv[1] if len(sys.argv) > 1 else '/mnt/nvme/tlrb2/work/dyn/c'
SEASON_NUM = int(sys.argv[2]) if len(sys.argv) > 2 else 1

LOGS_DIR = Path('/mnt/nvme/tlrb2/logs/t6')
LOG_PATH = LOGS_DIR / f'season_{SEASON_NUM}.log'
SCREENSHOT_PATH = LOGS_DIR / f'season_{SEASON_NUM}.png'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

DISPLAY = ':98'
D_ENV = {'DISPLAY': DISPLAY}

# Button press: long hold
def long_press(x, y, hold=0.5, wait=2):
    """Long press at (x,y) on root window."""
    subprocess.run(['xdotool', 'mousemove', str(x), str(y)], env=D_ENV, check=True)
    time.sleep(0.2)
    subprocess.run(['xdotool', 'mousedown', '1'], env=D_ENV, check=True)
    time.sleep(hold)
    subprocess.run(['xdotool', 'mouseup', '1'], env=D_ENV, check=True)
    time.sleep(wait)
    log.info(f'long_press({x}, {y})')

# Key press
def key_press(key_name, wait=1):
    """Send key."""
    wid = subprocess.run(['xdotool', 'search', '--class', '.'],
                         env=D_ENV, capture_output=True, text=True, check=True)
    wid = wid.stdout.strip().split()[0] if wid.stdout.strip() else ''
    if wid:
        subprocess.run(['xdotool', 'key', '--window', wid, key_name],
                       env=D_ENV, check=True)
    else:
        subprocess.run(['xdotool', 'key', key_name], env=D_ENV, check=True)
    time.sleep(wait)
    log.info(f'key_press({key_name})')

# Capture and identify screen
def check_screen():
    """Screenshot and identify. Return (screen_name, confidence)."""
    shot_path = SCREENSHOT_PATH
    subprocess.run(['import', '-window', 'root', str(shot_path)], env=D_ENV, check=True)
    state, conf = identify_screen(str(shot_path), DISPLAY)
    log.info(f'screen: {state} (conf={conf:.0f}%)')
    return state, conf

# Check day byte
def day_byte():
    """Read MAJ day byte at offset 0x20a."""
    maj = os.path.join(INSTALL_ROOT, 'TEAMS', 'CLASSIC', 'CLASSIC.MAJ')
    try:
        with open(maj, 'rb') as f:
            f.seek(0x20a)
            return f.read(1)[0]
    except OSError:
        return None

# Check HISTORY.DAT byte 0
def history_byte0():
    """Read HISTORY.DAT byte 0 (rolled flag)."""
    hist = os.path.join(INSTALL_ROOT, 'HISTORY.DAT')
    try:
        with open(hist, 'rb') as f:
            return f.read(1)[0]
    except OSError:
        return None

def run_season():
    """Drive full season state machine."""
    log.info(f'Starting season {SEASON_NUM} simulation')
    state = 'menu_start'
    last_screen = None
    stall_count = 0
    stall_start = time.time()

    while True:
        # Screenshot and check state
        screen, conf = check_screen()
        day = day_byte()
        hist0 = history_byte0()
        log.info(f'  state={state} screen={screen} day=0x{day:02x} hist0={hist0}')

        # Stall detection
        if screen == last_screen and state != 'sim_running':
            elapsed = time.time() - stall_start
            if elapsed > 120:
                log.warning(f'Stalled for {elapsed:.0f}s on screen {screen}')
                stall_count += 1
                if stall_count >= 3:
                    log.error('Stall timeout after 3 cycles')
                    log.error(f'Last screenshot: {SCREENSHOT_PATH}')
                    return False
                log.info(f'Attempting dismissals (cycle {stall_count}/3)')
                # Try known dismissals
                key_press('Return', 2)
                key_press('Escape', 2)
                long_press(512, 384, 0.3, 2)
                stall_start = time.time()
        else:
            stall_count = 0
            stall_start = time.time()
        last_screen = screen

        # Unknown screen: log and attempt recovery
        if screen == 'unknown':
            log.warning(f'Unknown screen, attempting recovery')
            log.info(f'Saved to {SCREENSHOT_PATH}')
            key_press('Return', 1)
            key_press('Escape', 1)
            continue

        # State machine
        if state == 'menu_start':
            if screen == 'main_menu':
                log.info('Reached main menu, opening SEASON')
                long_press(304, 209, 0.5, 2)
                state = 'season_menu'
            elif screen == 'season_play':
                state = 'season_play'
            else:
                log.info('Navigating to menu')
                key_press('Escape', 2)

        elif state == 'season_menu':
            if screen == 'season_menu' or 'start_new' in screen:
                log.info('Starting new season')
                long_press(352, 321, 0.5, 2)
                state = 'new_season_dialog'
            else:
                key_press('Escape', 1)

        elif state == 'new_season_dialog':
            if 'new_season' in screen or 'confirm' in screen:
                log.info('Confirming new season')
                long_press(430, 592, 0.5, 3)
                state = 'dh_dialog'
            else:
                long_press(430, 592, 0.5, 2)

        elif state == 'dh_dialog':
            if 'dh' in screen or 'confirm' in screen:
                log.info('Confirming DH')
                long_press(458, 468, 0.5, 2)
                state = 'injuries_dialog'
            else:
                key_press('Return', 2)

        elif state == 'injuries_dialog':
            if 'injuries' in screen or 'confirm' in screen:
                log.info('Confirming injuries')
                long_press(514, 456, 0.5, 3)
                state = 'season_play_start'
            else:
                key_press('Return', 2)

        elif state == 'season_play_start':
            if screen == 'season_play':
                log.info('Selecting THRU REGULAR SEASON')
                long_press(732, 528, 0.5, 2)
                state = 'play_start'
            else:
                log.info('Navigating to season play screen')
                long_press(344, 253, 0.5, 2)

        elif state == 'play_start':
            if 'season_play' in screen or 'play' in screen:
                log.info('Clicking PLAY to start season')
                long_press(510, 592, 0.5, 5)
                state = 'sim_running'
                stall_start = time.time()
            else:
                long_press(510, 592, 0.5, 2)

        elif state == 'sim_running':
            # Poll for day progression
            if day and day >= 0xf3:
                log.info(f'Reached end of season (day=0x{day:02x})')
                state = 'post_ws'
            elif day and day >= 0x6a:
                log.info(f'All-Star break area (day=0x{day:02x})')
                if screen == 'allstar_play' or 'allstar' in screen:
                    state = 'allstar_dialog'
                else:
                    time.sleep(10)
            else:
                log.info(f'Season running (day=0x{day:02x})')
                time.sleep(15)

        elif state == 'allstar_dialog':
            if 'allstar_play' in screen:
                log.info('Clicking PLAY on All-Star screen')
                long_press(510, 563, 0.5, 5)
                state = 'allstar_game'
            elif 'ground_rules' in screen:
                log.info('Clicking PLAY BALL on ground rules')
                long_press(428, 592, 0.5, 3)
                state = 'allstar_lineup'
            else:
                key_press('Return', 2)

        elif state == 'allstar_lineup':
            if 'lineup' in screen:
                log.info('Clicking PLAY BALL on lineup')
                long_press(510, 592, 0.5, 3)
                state = 'allstar_game'
            else:
                key_press('Return', 2)

        elif state == 'allstar_game':
            if 'result' in screen:
                log.info('Clicking DONE on All-Star result')
                long_press(510, 563, 0.5, 3)
                state = 'allstar_boxscore'
            elif 'boxscore' in screen:
                state = 'allstar_boxscore'
            else:
                log.info('All-Star game in progress')
                time.sleep(30)

        elif state == 'allstar_boxscore':
            if 'boxscore' in screen:
                log.info('Dismissing box score')
                long_press(304, 592, 0.5, 3)
                state = 'resume_season'
            else:
                key_press('Return', 2)

        elif state == 'resume_season':
            log.info('Resuming season after All-Star break')
            key_press('Escape', 2)
            state = 'season_play_start'

        elif state == 'post_ws':
            log.info('World Series over, returning to menu')
            key_press('Return', 2)
            key_press('Escape', 2)
            long_press(234, 341, 0.5, 5)
            state = 'done'

        elif state == 'done':
            log.info(f'Season {SEASON_NUM} complete, day=0x{day:02x}, hist0={hist0}')
            if day == 0xf3 and hist0 == 1:
                log.info('DYNASTY rollover confirmed')
                return True
            else:
                log.warning(f'Unexpected end state: day=0x{day:02x}, hist0={hist0}')
                return True

        else:
            log.warning(f'Unknown state: {state}')
            key_press('Escape', 1)

        time.sleep(0.5)

if __name__ == '__main__':
    try:
        success = run_season()
        sys.exit(0 if success else 1)
    except Exception as e:
        log.exception(f'Fatal error: {e}')
        sys.exit(1)
