#!/usr/bin/env python3
"""Drive one dynasty season in the real game on the :98 rig, with nobody watching.

Flow, verified by hand on 2026-10-07 (coords are root coords on :98):
  new season  (only when the league is at day 0xf3 and HISTORY byte 0 is 1, i.e. already rolled)
              SEASON menu drag to START NEW SEASON (304,209 -> 340,320), NEW SEASON (430,592), destroy dialog
              YES (514,456), DH dialog DONE (458,468), injuries YES (514,456). Lands on PLAY STANDARD GAMES, day 0x07.
  play        from the ball menu: SEASON menu drag to PLAY LEAGUE GAMES (304,209 -> 344,254). THRU WORLD SERIES
              (710,546), PLAY (512,592). The All-Star question (JULY 17) gets NO (540,440), which skips the game.
              The standings screen then sits still while the sim runs (Return would toggle game scores), so an
              unchanged screen is NOT a stall; only the ring screen ends the wait.
  finish      ring, Return (WS grid), Return (game 1 box score), DONE (304,592), Escape (ball menu), QUIT (234,341),
              after a roll Escape twice out of DYNVIEW /REVIEW.
              On the way out the BAT loop copies the league to C:\\DYNSNAP and runs DYNASTY: day 0xf3, HISTORY
              byte 0 = 1, then the game ends at the C:\\TONY2> prompt.
  relaunch    type TONY2 + Return, Escape past the intro until the ball menu is up. DYNASTY skips (done flag set).

The caller snapshots DYNSNAP between finish and relaunch: the relaunch copies the post-roll league over it.

usage: season_sim.py N [--install DIR]   (one season: new season if due, play, finish; no relaunch)
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rig
import screens

INSTALL = '/mnt/nvme/tlrb2/work/dyn/c/TONY2'
LOGS = '/mnt/nvme/tlrb2/logs/t6'
SEASON_TIMEOUT = 40 * 60      # one season sims in ~10 min on this rig; generous


class SimError(RuntimeError):
    pass


def league(install):
    return os.path.join(install, 'TEAMS', 'CLASSIC')


def day(install):
    with open(os.path.join(league(install), 'CLASSIC.MAJ'), 'rb') as f:
        f.seek(0x20a)
        return f.read(1)[0]


def hist0(install):
    p = os.path.join(league(install), 'HISTORY.DAT')
    if not os.path.exists(p):
        return None
    with open(p, 'rb') as f:
        b = f.read(1)
    return b[0] if b else None


class Driver:
    def __init__(self, n, install=INSTALL):
        self.n, self.install = n, install
        os.makedirs(os.path.join(LOGS, 'shots'), exist_ok=True)
        self.logf = open(os.path.join(LOGS, f'season_{n}.log'), 'a')

    def log(self, msg):
        line = f'{time.strftime("%H:%M:%S")} s{self.n} {msg}'
        print(line, flush=True)
        self.logf.write(line + '\n')
        self.logf.flush()

    def shot(self, tag):
        name = f's{self.n}_{tag}'
        rig.park()
        rig.shot(name)
        return os.path.join(rig.SHOTS, name + '.png')

    def state(self):
        return screens.identify()

    def wait_for(self, want, timeout, every=2.0, nudge=None):
        """Poll until the screen is one of want. nudge(state) is called on every miss (e.g. press Escape).
        Raises SimError with the last screenshot path on timeout."""
        want = (want,) if isinstance(want, str) else tuple(want)
        t0 = time.time()
        st = None
        while time.time() - t0 < timeout:
            st, _ = self.state()
            if st in want:
                self.log(f'at {st} after {time.time() - t0:.0f}s')
                return st
            if nudge:
                nudge(st)
            time.sleep(every)
        p = self.shot('timeout')
        raise SimError(f'waited {timeout}s for {want}, last screen {st}, shot {p}')

    def repress(self, screen, desc, x, y, after=8.0):
        """nudge for wait_for: press (x, y) again while the screen is still `screen`, at most every `after` s."""
        last = [time.time()]

        def nudge(st):
            if st == screen and time.time() - last[0] >= after:
                self.act(f'{desc} (again, still at {screen})', rig.press, x, y)
                last[0] = time.time()
        return nudge

    def act(self, desc, fn, *a):
        self.log(desc)
        fn(*a)

    # ---- phases -------------------------------------------------------------------------------------------------
    def new_season(self):
        self.act('SEASON > START NEW SEASON', rig.menu, 304, 209, 340, 320)
        self.wait_for('new_season', 30)
        self.act('NEW SEASON', rig.press, 430, 592)
        # a press can be lost (s109 gate, 2026-10-07: still on the setup screen 20 s later)
        self.wait_for('destroy_dialog', 30, nudge=self.repress('new_season', 'NEW SEASON', 430, 592))
        self.act('destroy dialog YES', rig.press, 514, 456)
        self.wait_for('dh_dialog', 20)
        self.act('DH DONE', rig.press, 458, 468)
        self.wait_for('injury_dialog', 20)
        self.act('injuries YES', rig.press, 514, 456)
        self.wait_for('play_std', 60)
        t0 = time.time()
        while day(self.install) != 0x07 and time.time() - t0 < 30:
            time.sleep(2)
        d = day(self.install)
        if d != 0x07:
            raise SimError(f'new season started but day byte is 0x{d:02x}, expected 0x07')
        self.log('new season on disk: day 0x07')

    def play(self):
        st, _ = self.state()
        if st != 'play_std':
            self.act('SEASON > PLAY LEAGUE GAMES', rig.menu, 304, 209, 344, 254)
            self.wait_for('play_std', 30)
        for _ in range(3):
            self.act('THRU WORLD SERIES', rig.press, 710, 546)
            time.sleep(1.5)
            if screens.season_over():          # "PLAY ALL GAMES TO" now reads SEASON OVER
                break
        else:
            raise SimError(f'THRU WORLD SERIES did not take, shot {self.shot("thru_ws")}')
        self.act('PLAY', rig.press, 512, 592)
        t0, last_note, last_shot = time.time(), 0, 0
        while True:
            el = time.time() - t0
            if el > SEASON_TIMEOUT:
                raise SimError(f'no World Series ring after {SEASON_TIMEOUT}s, shot {self.shot("sim_timeout")}')
            st, _ = self.state()
            if st == 'ring':
                self.log(f'World Series ring after {el / 60:.1f} min')
                self.shot('ring')
                return el
            if st == 'allstar_dialog':
                self.act('All-Star game? NO', rig.press, 540, 440)
            elif st in ('ball_menu', 'dos_prompt', 'new_season'):
                raise SimError(f'sim left the season screens ({st}), shot {self.shot("sim_left")}')
            if el - last_note >= 60:
                self.log(f'simming, {el / 60:.0f} min, screen {st}')
                last_note = el
            if el - last_shot >= 300:
                self.shot('sim_last')
                last_shot = el
            time.sleep(10)

    def finish(self):
        self.act('Return (WS grid)', rig.key, 'Return')
        time.sleep(3)
        self.act('Return (box score)', rig.key, 'Return')
        time.sleep(3)
        self.act('DONE', rig.press, 304, 592)
        time.sleep(3)
        self.act('Escape', rig.key, 'Escape')
        tries = [0]

        def nudge(st):
            # box score still up: DONE again; anything else: Escape to raise the ball menu
            tries[0] += 1
            if tries[0] % 3 == 0:
                self.act(f'nudge from {st}: DONE + Escape', rig.press, 304, 592)
                time.sleep(2)
                rig.key('Escape')
        self.wait_for('ball_menu', 60, every=3, nudge=nudge)
        self.act('QUIT', rig.press, 234, 341)
        # a roll runs HISTWR, ROSTERS, then DYNVIEW /REVIEW (C8): Escape to its menu, Escape to leave
        if self.wait_for(('dos_prompt', 'dynview'), 180, every=3) == 'dynview':
            self.shot('dynview_review')
            self.act('DYNVIEW Escape (menu)', rig.key, 'Escape')
            time.sleep(2)
            self.act('DYNVIEW Escape (exit)', rig.key, 'Escape')
            self.wait_for('dos_prompt', 120, every=3,
                          nudge=lambda st: st == 'dynview' and rig.key('Escape'))
        d, h = day(self.install), hist0(self.install)
        self.log(f'at DOS: day 0x{d:02x} HISTORY byte0 {h}')
        if d != 0xf3 or h != 1:
            raise SimError(f'season ended without a roll: day 0x{d:02x} HISTORY byte0 {h}')

    def relaunch(self):
        self.act('type TONY2', rig.type_text, 'TONY2')
        rig.key('Return')
        time.sleep(15)
        seen = [0]

        def nudge(st):
            seen[0] += 1
            if st != 'ball_menu' and seen[0] % 2 == 1:
                rig.key('Escape')
        self.wait_for('ball_menu', 90, every=3, nudge=nudge)

    def season(self):
        """new season if due, play, finish. Returns sim minutes."""
        d, h = day(self.install), hist0(self.install)
        self.log(f'start: day 0x{d:02x} HISTORY byte0 {h}')
        if d == 0xf3:
            if h != 1:
                raise SimError('league at 0xf3 but not rolled; relaunch so DYNASTY rolls it first')
            self.new_season()
        sim = self.play()
        self.finish()
        return sim / 60


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('n', type=int)
    ap.add_argument('--install', default=INSTALL)
    a = ap.parse_args(argv)
    dr = Driver(a.n, a.install)
    try:
        dr.season()
    except SimError as e:
        dr.log(f'FAIL {e}')
        return 1
    dr.log('season done')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
