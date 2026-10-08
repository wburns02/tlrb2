#!/usr/bin/env python3
"""Python reference for one DYNASTY.EXE roll of a league dir.

Per team, in sorted file name order (the asm insertion-sorts the 8.3 names the same way): the C1 rollover of all 80
records, then the C4 rookie fill of the vacated roster slots. Both blobs get the same rng word, so the whole league
is one xorshift16 stream: team A rollover, team A fill, team B rollover, ... The fill's season year byte is record
byte 21 of the first named record in 0..79 after the rollover (the asm's year scan); a file with no named record
(a blank pool) takes the year of the last earlier file that had one (C4 amendment 2026-10-07), and is not filled
only when no earlier file had one.

usage: dynasty_ref.py IN_DIR OUT_DIR --seed N [--no-fill]
"""
import glob
import os
import shutil
import sys

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from m4 import rollover, team_fill          # noqa: E402
from m4.rookies import RookieGen            # noqa: E402

CFG = {'progress': True, 'retire': True}    # the asm passes CX = 3 (progress + retire)
HDR, REC, OFF_YEAR = 295, 143, 21


def season_year(image):
    for i in range(80):
        o = HDR + i * REC
        if image[o]:
            return image[o + OFF_YEAR]
    return None


def roll_league(in_dir, out_dir, seed, fill=True, cfg=None):
    """Roll every *.V20 of in_dir into out_dir; CLASSIC.MAJ is copied through. Returns
    {'seed', 'rng_end', 'retirees': {file: [rec]}, 'filled': {file: [rec]}, 'players': rollover report}."""
    os.makedirs(out_dir, exist_ok=True)
    rng = rollover.Rng(seed)
    gen = RookieGen(rng)
    report, retirees, filled = [], {}, {}
    last_year = None
    for p in sorted(glob.glob(os.path.join(in_dir, '*.V20'))):
        name = os.path.basename(p)
        out = os.path.join(out_dir, name)
        retirees[name] = rollover.rollover_team(p, out, cfg or CFG, rng, report)
        if not fill:
            continue
        image = bytearray(open(out, 'rb').read())
        year = season_year(image)
        if year is None:
            year = last_year
        if year is None:
            filled[name] = []
            continue
        last_year = year
        _, vac, _ = team_fill.fill_image(image, year, rng, gen)
        filled[name] = list(vac)
        with open(out, 'wb') as f:
            f.write(image)
    maj = os.path.join(in_dir, 'CLASSIC.MAJ')
    if os.path.exists(maj):
        shutil.copy2(maj, os.path.join(out_dir, 'CLASSIC.MAJ'))
    return {'seed': seed, 'rng_end': rng.s, 'retirees': retirees, 'filled': filled, 'players': report}


def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('in_dir')
    ap.add_argument('out_dir')
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--no-fill', action='store_true')
    a = ap.parse_args(argv)
    r = roll_league(a.in_dir, a.out_dir, a.seed, fill=not a.no_fill)
    print(f"rng_end {r['rng_end']}  retired {sum(map(len, r['retirees'].values()))}  "
          f"filled {sum(map(len, r['filled'].values()))}")


if __name__ == '__main__':
    main(sys.argv[1:])
