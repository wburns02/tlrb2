#!/usr/bin/env python3
"""Drive full season with state machine, stall detect, day-byte polling.

State machine tracks: season start -> regular season -> WS -> rollover.
Stall detect: 120s unchanged at day byte, try dismissals 3 times.
Logs every action and screenshot paths.

Usage: season_sim.py INSTALL_ROOT SEASON_NUM
"""
import sys, os, subprocess, time, logging
from pathlib import Path

INSTALL_ROOT = sys.argv[1] if len(sys.argv) > 1 else '/mnt/nvme/tlrb2/work/dyn/c/TONY2'
SEASON_NUM = int(sys.argv[2]) if len(sys.argv) > 2 else 1

LOGS_DIR = Path('/mnt/nvme/tlrb2/logs/t6')
LOG_PATH = LOGS_DIR / f'season_{SEASON_NUM}.log'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
    handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

DISPLAY = ':98'
D_ENV = {'DISPLAY': DISPLAY}

def long_press(x, y, hold=0.5, wait=2):
    subprocess.run(['xdotool', 'mousemove', str(x), str(y)], env=D_ENV, check=True)
    time.sleep(0.2)
    subprocess.run(['xdotool', 'mousedown', '1'], env=D_ENV, check=True)
    time.sleep(hold)
    subprocess.run(['xdotool', 'mouseup', '1'], env=D_ENV, check=True)
    time.sleep(wait)
    log.info(f'long_press({x}, {y})')

def key_press(k, wait=1):
    subprocess.run(['xdotool', 'key', k], env=D_ENV, check=False)
    time.sleep(wait)
    log.info(f'key_press({k})')

def day_byte():
    maj = os.path.join(INSTALL_ROOT, 'TEAMS', 'CLASSIC', 'CLASSIC.MAJ')
    try:
        with open(maj, 'rb') as f:
            f.seek(0x20a)
            return f.read(1)[0]
    except: return None

def hist0():
    hist = os.path.join(INSTALL_ROOT, 'TEAMS', 'CLASSIC', 'HISTORY.DAT')
    try:
        with open(hist, 'rb') as f:
            return f.read(1)[0]
    except: return None

def shot(name):
    path = LOGS_DIR / f'{name}_{SEASON_NUM}.png'
    try:
        subprocess.run(['import', '-window', 'root', str(path)], env=D_ENV, timeout=5, check=True)
        return path
    except: return None

def run():
    log.info(f'Season {SEASON_NUM}: start')
    d = day_byte()
    h = hist0()
    log.info(f'Init: day=0x{d:02x} hist0={h}')
    
    st = 'start'
    stall_ct = 0
    last_d = None
    stall_t = time.time()
    
    while True:
        d = day_byte()
        h = hist0()
        ela = time.time() - stall_t
        log.info(f'[{st}] day=0x{d:02x} h={h} ela={ela:.0f}s')
        
        # Stall: 120s at same day, not sim_running
        if st != 'sim_running' and d == last_d and ela > 120:
            stall_ct += 1
            log.warning(f'Stall {stall_ct}/3')
            if stall_ct >= 3:
                s = shot(f'stall_{st}')
                log.error(f'Stall on {st}: {s}')
                return False
            key_press('Return', 1); key_press('Escape', 1); long_press(512, 384, 0.3, 1)
            stall_t = time.time()
            continue
        else:
            if d != last_d: stall_ct = 0; stall_t = time.time()
            last_d = d
        
        # States
        if st == 'start':
            log.info('SEASON menu')
            long_press(304, 209, 0.5, 2)
            st = 'season_menu'
        elif st == 'season_menu':
            if d == 0xf3:
                log.info('New season')
                long_press(352, 321, 0.5, 2)
                st = 'new_season'
            else:
                log.info('Play screen')
                long_press(344, 253, 0.5, 2)
                st = 'play_screen'
        elif st == 'new_season':
            log.info('NEW SEASON')
            long_press(430, 592, 0.5, 3)
            st = 'yes_confirm'
        elif st == 'yes_confirm':
            log.info('YES')
            long_press(514, 456, 0.5, 2)
            st = 'dh_done'
        elif st == 'dh_done':
            log.info('DH DONE')
            long_press(458, 468, 0.5, 2)
            st = 'inj_yes'
        elif st == 'inj_yes':
            log.info('Injuries YES')
            long_press(514, 456, 0.5, 3)
            st = 'play_screen'
        elif st == 'play_screen':
            if d < 0xf3:
                log.info('THRU REGULAR SEASON')
                long_press(732, 528, 0.5, 2)
                time.sleep(1)
                long_press(510, 592, 0.5, 5)
                st = 'sim_running'
                stall_t = time.time()
            else:
                log.info('WS')
                st = 'ws'
        elif st == 'sim_running':
            if d == 0xf3:
                log.info('Regular season done')
                st = 'ws'
                stall_t = time.time()
            else:
                time.sleep(30)
        elif st == 'ws':
            log.info('THRU WORLD SERIES')
            long_press(732, 546, 0.5, 2)
            time.sleep(1)
            long_press(510, 592, 0.5, 3)
            st = 'ws_run'
            stall_t = time.time()
        elif st == 'ws_run':
            if d == 0xf3 and h == 0:
                log.info('WS done, QUIT')
                st = 'quit'
                stall_t = time.time()
            else:
                time.sleep(30)
        elif st == 'quit':
            log.info('QUIT')
            key_press('Return', 2); key_press('Escape', 2)
            long_press(234, 341, 0.5, 5)
            st = 'done'
        elif st == 'done':
            time.sleep(10)
            d_f = day_byte()
            h_f = hist0()
            log.info(f'Final: day=0x{d_f:02x} hist0={h_f}')
            s = shot('season_done')
            if d_f == 0xf3 and h_f == 1:
                log.info(f'SUCCESS: {s}')
                return True
            else:
                log.warning(f'BAD END: {s}')
                return False
        else:
            log.warning(f'Unknown: {st}')
            key_press('Escape', 1)

if __name__ == '__main__':
    try:
        sys.exit(0 if run() else 1)
    except Exception as e:
        log.exception(f'Fatal: {e}')
        sys.exit(1)
