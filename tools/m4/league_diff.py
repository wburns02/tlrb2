#!/usr/bin/env python3
"""League-set differ for M4 P1 gates: OLD_DIR vs NEW_DIR (each a league dir holding
CLASSIC.MAJ + 26 .V20, i.e. a season). Reports, per team file:
  roster half (records 0..39) field changes  - what rollover/aging/progression touched
  season half (records 40..79) field changes - stats accumulated in-season (expected busy)
plus MAJ header day/games/W-L. Byte-level ground truth lives in `v20.py diff` (full byte
list); this tool summarizes by FIELD, which is what the P1 gate is judged on.

usage: league_diff.py OLD_DIR NEW_DIR [--full] [--fields F1,F2,...] [--team CODE]
  --full    also print every changed byte as v20.py does
  --fields  restrict the roster-half report to these field names
  --team    restrict to one team code (e.g. BAL)
Exit 0 always; prints a one-line verdict per file.
"""
import sys, os, glob, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from v20 import Team, F, REC  # noqa: E402
from maj import Maj          # noqa: E402

BIO = ('age', 'year_off', 'exp', 'games', 'injury', 'salary', 'portrait', 'speed', 'consist',
       'exper', 'pos1', 'pos2', 'power', 'bunt', 'hit_run', 'streak_v', 'clutch', 'daynight',
       'arm', 'range', 'control', 'velocity', 'pitch4', 'endurance', 'p_streak_v', 'p_clutch',
       'p_daynight', 'pickoff', 'release', 'q1', 'q2', 'q3', 'q4', 'bats', 'throws', 'flag3')


def field_map():
    """name -> [(off, kind)] (kind without the lo/hi split loses side; keep raw)."""
    m = collections.defaultdict(list)
    for name, (off, kind) in F.items():
        m[name].append((off, kind))
    return m


FM = field_map()


def field_diffs(old_rec, new_rec, fields=None):
    """[(field, off, kind, old, new)] using the field table; falls back to raw byte for
    bytes no field covers."""
    out = []
    covered = set()
    for name, spots in FM.items():
        if fields and name not in fields:
            continue
        for off, kind in spots:
            a = Team._get(old_rec, off, kind) if hasattr(Team, '_get') else None
            from v20 import _get, _set
            va, vb = _get(old_rec, off, kind), _get(new_rec, off, kind)
            covered.add(off)
            if kind in ('lo', 'hi'):
                covered.add(off)
            if va != vb:
                out.append((name, off, kind, va, vb))
    for i, (a, b) in enumerate(zip(old_rec, new_rec)):
        if a != b and i not in covered:
            out.append(('RAW', i, 'u8', a, b))
    return out


def diff_team(p_old, p_new, fields=None, full=False):
    t_old, t_new = Team.load(p_old), Team.load(p_new)
    code = t_old.abbr or os.path.basename(p_old)
    rolf = seaf = collections.Counter()
    rol_changes, sea_changes = [], []
    for idx in range(80):
        d = field_diffs(t_old.players[idx].raw, t_new.players[idx].raw, fields)
        if idx < 40:
            rol_changes += [(idx, *x) for x in d]
            rolf.update(x[0] for x in d)
        else:
            sea_changes += [(idx, *x) for x in d]
            seaf.update(x[0] for x in d)
    print(f'{code}: roster-half fields {dict(rolf) or "{}"}  season-half fields changed={len(seaf)}')
    if full:
        for idx, name, off, kind, va, vb in rol_changes:
            print(f'  r{idx:02d} {name:12s} {off:#04x} {kind:3s} {va} -> {vb}')
    return rol_changes, sea_changes


def main(a):
    old_d, new_d = a[0], a[1]
    full = '--full' in a
    fields = None
    if '--fields' in a:
        fields = set(a[a.index('--fields') + 1].split(','))
    team = a[a.index('--team') + 1].upper() if '--team' in a else None
    mo = os.path.join(old_d, 'CLASSIC.MAJ')
    mn = os.path.join(new_d, 'CLASSIC.MAJ')
    if os.path.exists(mo) and os.path.exists(mn):
        ho, hn = Maj.load(mo).hdr(), Maj.load(mn).hdr()
        print('MAJ hdr: ' + '  '.join(f'{k} {ho[k]}->{hn[k]}' for k in ho if ho[k] != hn[k]))
    for p_old in sorted(glob.glob(os.path.join(old_d, '*.V20'))):
        p_new = os.path.join(new_d, os.path.basename(p_old))
        if not os.path.exists(p_new):
            print(f'{os.path.basename(p_old)}: missing in NEW')
            continue
        if team:
            from v20 import Team as T
            if T.load(p_old).abbr != team:
                continue
        diff_team(p_old, p_new, fields, full)


if __name__ == '__main__':
    main(sys.argv[1:])
