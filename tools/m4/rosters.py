#!/usr/bin/env python3
"""M4 roster management reference, contract C6 (notes/M4_CONTRACT.md C6).

Runs after DYNASTY rolled and HISTWR recorded (BAT: `if errorlevel 1 rosters`
after the histwr line). Inputs: the rolled league dir (TEAMS\\CLASSIC), the
pre-roll snapshot C:\\DYNSNAP (V20s + MAJ), C:\\DYNSNAP\\RETIRED.DAT and
HISTORY.DAT. Outputs: rewritten team V20s, the pool files, HISTORY header
bytes 1..2 and 16..17, and ROSTERS.TXT. C12.6 step 9 (realign.plan) may also
rewrite the MAJ and create TEAMID.DAT, and then ROSTERS.TXT ends with a FORMAT
line; all of them are committed together.

Pure core (importable, testable offline): the value/score/potential helpers,
the playing-time class, depth_rebuild(image) and repair(image, changed) on
in-memory bytearrays, and
  offseason(teams, snaps, retired, pool, standings, hist_hdr, rng)
with teams = [(stem, lg_id, image bytearray)], snaps = {stem: image bytes}
(pre-roll), retired = {stem: [40 flags]} (1 = the roll retired this slot),
pool = [4 pool file image bytearrays], standings = {lg_id: (W, L)} and
hist_hdr = the 32 B HISTORY header bytearray (era byte 10, managed mask
bytes 12..15). Mutates the images in place and returns the event log list.
T is one module-level dict so a harness can override any constant.

File wrapper run(league_dir, snap_dir, hist_path, retired_path) -> 0 ok,
2 error (files untouched on error). usage:
  rosters.py LEAGUE_DIR SNAP_DIR HIST_PATH RETIRED_PATH
  rosters.py /EXPAND LEAGUE_DIR SNAP_DIR HIST_PATH     (C15: expansion,
  contraction, stable ids; appended ROSTERS.TXT, TEAMID.DAT, pool writes)
"""
import glob
import os
import struct
import sys

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from m4.rollover import Rng, GM          # noqa: E402  (xorshift16, dev grade)
from m4 import history as history_mod    # noqa: E402  (mapped_teams)
from m4 import realign                   # noqa: E402  (plan, C12.5)
from m4 import teamids                   # noqa: E402  (stable ids, C12.3)
from v20 import HDR, REC, F, _get        # noqa: E402
import war                               # noqa: E402  (ipiv_outs)
import statline                          # noqa: E402  (placeholder stat lines)

# header list offsets (v20.py's constants, restated so the pure core stays
# self-contained)
H_STAFF, H_LINEUP, H_DEF, H_BENCH, H_RESERVE = 111, 122, 158, 194, 222

# ---------------------------------------------------------------------------
# T table (contract C6: tunable until the 50-season validation locks them)
# ---------------------------------------------------------------------------

T = {
    'SP_END': 6,
    'POOL_YEARS': 1,
    'KEEP_P': 7, 'KEEP_B': 10,
    'REL_CAP': 8,
    'MKT': 64,
    'NEED': 8,
    'BAND': 5,
    'MAX_TRADES': 6,
    'POOL_KEEP_P': 32, 'POOL_KEEP_B': 48,
    # step 7 form: each named player's depth S/Off carries d % (2A+1) - A (one
    # draw per named slot of an AI team, slot order); 0 = no draws
    'FORM_A': 16,
    # release p (/256), rows age <= 24, 25..29, 30..33, 34+;
    # columns none, low, mid, reg (2x the 1970-90 Lahman gone rates, R2)
    'REL': [[32, 138, 66, 10], [96, 240, 82, 10], [192, 255, 102, 16], [255, 255, 154, 36]],
}

POOL_FILES = ('POOL1.V20', 'POOL2.V20', 'POOL3.V20', 'POOL4.V20')

# ---------------------------------------------------------------------------
# Value / score / potential helpers (pure record views, no image state)
# ---------------------------------------------------------------------------

FIELD_W = {                              # (rw, aw) by primary position p
    0: (0, 0), 1: (1, 3), 2: (1, 0), 3: (3, 1), 4: (2, 2), 5: (3, 2),
    6: (1, 1), 7: (3, 1), 8: (1, 2), 9: (0, 0), 10: (2, 1), 11: (2, 2),
    12: (2, 1), 13: (1, 3), 14: (1, 3), 15: (1, 3),
}
GROUP_COVER = {                          # group code -> positions covered
    10: (6, 7, 8), 11: (2, 3, 4, 5), 12: (2, 3, 4, 5, 6, 7, 8),
    13: (1, 6, 7, 8), 14: (1, 2, 3, 4, 5), 15: (1, 4),
}
FIELD_ORDER = (1, 5, 3, 7, 4, 8, 6, 2)   # C, SS, 2B, CF, 3B, RF, LF, 1B
Q_ORDER = (1, 2, 3, 4, 5, 6, 7, 8, 'SP', 'RP')

W_AGE = ((20, 179), (22, 154), (23, 141), (24, 102), (25, 77), (26, 38), (27, 13))
DISCOUNT = ((29, 256), (31, 248), (33, 236), (35, 220), (37, 200))   # 38+ = 180
CAPS = {'endurance': 10}


def _g_of(x):
    return 90 if x <= 22 else 64 if x <= 24 else 32


def g_sum(age, grade=0):
    """G[age] = sum of g(x) for x = age+1..26; 0 for age >= 26. With a dev grade
    1..5 (C1b) each term is scaled: (g(x) * GM[grade]) >> 2, so scouts value
    boom prospects."""
    if age >= 26:
        return 0
    if grade:
        return sum((_g_of(x) * GM[grade]) >> 2 for x in range(age + 1, 27))
    return sum(_g_of(x) for x in range(age + 1, 27))


def pos1f(rec):
    return _get(rec, *F['pos1']) & 15


def pos2f(rec):
    return _get(rec, *F['pos2']) & 15


def is_pitcher(rec):
    return pos1f(rec) == 0


def can_play(rec, q):
    """Field positions q = 1..8: pos1 or pos2 is q, or a group code covers q
    (OF 6-8, IF 2-5, O/I 2-8, C/O 1 and 6-8, C/I 1-5, C/3 1 and 4)."""
    if not (1 <= q <= 8):
        return False
    for p in (pos1f(rec), pos2f(rec)):
        if p == q:
            return True
        if p in GROUP_COVER and q in GROUP_COVER[p]:
            return True
    return False


def fld(rec, q):
    """Fld(q) = rw[q]*range + aw[q]*arm (weights of position q, not of p)."""
    rw, aw = FIELD_W.get(q, (0, 0))
    return rw * _get(rec, *F['range']) + aw * _get(rec, *F['arm'])


def off(rec):
    """Off = 3*power + 3*hit_run + speed."""
    return (3 * _get(rec, *F['power']) + 3 * _get(rec, *F['hit_run'])
            + _get(rec, *F['speed']))


def score(rec):
    """Batter S = Off + Fld(p); pitcher S = 3*control + 3*velocity + 2*endurance."""
    if is_pitcher(rec):
        return (3 * _get(rec, *F['control']) + 3 * _get(rec, *F['velocity'])
                + 2 * _get(rec, *F['endurance']))
    return off(rec) + fld(rec, pos1f(rec))


def pitch_score4(rec):
    """Rotation key: 3*control + 3*velocity + 4*endurance."""
    return (3 * _get(rec, *F['control']) + 3 * _get(rec, *F['velocity'])
            + 4 * _get(rec, *F['endurance']))


def relief_score2(rec):
    """Relief key: 3*control + 3*velocity."""
    return 3 * _get(rec, *F['control']) + 3 * _get(rec, *F['velocity'])


def w_of(age):
    for cap, w in W_AGE:
        if age <= cap:
            return w
    return 0


def discount_of(age):
    for cap, f in DISCOUNT:
        if age <= cap:
            return f
    return 180


def pot_ratings(rec):
    """pot = min(cap, r + ((G[age] + 128) >> 8)) if r < cap else r; cap 10
    endurance, 12 otherwise. Order: control velocity endurance (pitcher) or
    power hit_run speed range arm (batter). G[age] reads the dev grade byte 142
    (C1b)."""
    age = _get(rec, *F['age'])
    add = (g_sum(age, rec[142]) + 128) >> 8
    names = ('control', 'velocity', 'endurance') if is_pitcher(rec) \
        else ('power', 'hit_run', 'speed', 'range', 'arm')
    out = []
    for name in names:
        o, kind = F[name]
        r = _get(rec, o, kind)
        cap = CAPS.get(name, 12)
        out.append(min(cap, r + add) if r < cap else r)
    return out


def spot(rec):
    """Spot = S computed on pot ratings."""
    p = pot_ratings(rec)
    if is_pitcher(rec):
        ctrl, vel, end = p
        return 3 * ctrl + 3 * vel + 2 * end
    power, hit_run, speed, rng_, arm = p
    rw, aw = FIELD_W.get(pos1f(rec), (0, 0))
    return 3 * power + 3 * hit_run + speed + rw * rng_ + aw * arm


def value(rec):
    """V = (S*(256 - w) + Spot*w) >> 8 by age, then the age discount
    (V * f) >> 8."""
    age = _get(rec, *F['age'])
    w = w_of(age)
    v = (score(rec) * (256 - w) + spot(rec) * w) >> 8
    return (v * discount_of(age)) >> 8


def sp_rp(rec):
    """SP = pitcher with endurance >= T.SP_END, else RP."""
    return 'SP' if _get(rec, *F['endurance']) >= T['SP_END'] else 'RP'


def pt_class(games, pa, outs, pitcher):
    """Class: none (0) if games = 0; batter low < 100 PA, mid 100..399,
    reg 400+; pitcher low < 90 outs, mid 90..299, reg 300+."""
    if games == 0:
        return 0
    if pitcher:
        return 1 if outs < 90 else 2 if outs <= 299 else 3
    return 1 if pa < 100 else 2 if pa <= 399 else 3


# ---------------------------------------------------------------------------
# Image helpers (bytearrays of 295 + 80*143 B)
# ---------------------------------------------------------------------------

def image_year(img):
    """Year = record byte 21 + 1870 of the first named record."""
    for i in range(80):
        base = HDR + REC * i
        if img[base]:
            return img[base + 21] + 1870
    return None


def named_slots(img):
    """Slot indices 0..39 with byte 0 != 0 in the roster half."""
    return [s for s in range(40) if img[HDR + REC * s]]


def vacate(img, slot):
    """Vacate a slot: both records (i and i + 40) zeroed."""
    ro = HDR + REC * slot
    so = HDR + REC * (slot + 40)
    img[ro:ro + REC] = bytes(REC)
    img[so:so + REC] = bytes(REC)


def copy_pair(img, slot):
    """The player's two records as independent bytearrays."""
    ro = HDR + REC * slot
    so = HDR + REC * (slot + 40)
    return [bytearray(img[ro:ro + REC]), bytearray(img[so:so + REC])]


def write_pair(img, slot, pair):
    ro = HDR + REC * slot
    so = HDR + REC * (slot + 40)
    img[ro:ro + REC] = bytes(pair[0])
    img[so:so + REC] = bytes(pair[1])


def write_pool_years(img, slot, v):
    """Record byte 141 = pool years, both halves."""
    for half in (0, 40):
        img[HDR + REC * (slot + half) + 141] = v & 0xff


def pname(rec):
    """Name as First Last from the record bytes."""
    last = bytes(rec[0:12]).split(b'\0')[0].decode('latin-1')
    first = bytes(rec[12:20]).split(b'\0')[0].decode('latin-1')
    return (first + ' ' + last).strip()


def is_on(img, slot):
    return img[HDR + REC * slot] != 0


def pool_blank(first_team_image):
    """A missing pool file: header all zero except name FREE AGENTS (+0) and
    the league code copied from the first team; 80 zero records."""
    d = bytearray(HDR + REC * 80)
    d[0:14] = b'FREE AGENTS'.ljust(14, b'\0')[:14]
    d[14:16] = bytes(first_team_image[14:16])
    return d


def lower_median(vals):
    m = sorted(vals)
    return m[(len(m) - 1) // 2]


def rev_order(teams, standings):
    """Team indices in reverse standings order: W/(W+L) ascending, compared
    as W1*(W2+L2) vs W2*(W1+L1) (0-0 counts as .500), ties by file order."""
    idx = list(range(len(teams)))
    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            ka, kb = idx[a], idx[b]
            w1, l1 = standings.get(teams[ka][1], (0, 0))
            w2, l2 = standings.get(teams[kb][1], (0, 0))
            s1 = w1 * (w2 + l2) if (w1 or l1) else (w2 + l2)
            s2 = w2 * (w1 + l1) if (w2 or l2) else (w1 + l1)
            if s1 > s2 or (s1 == s2 and ka > kb):
                idx[a], idx[b] = idx[b], idx[a]
    return idx


# ---------------------------------------------------------------------------
# Depth rebuild (the step 7 assignment + header writes) and managed repair
# ---------------------------------------------------------------------------

class _Scorer:
    """Score cache for one rebuild/trade pass, keyed by record bytes."""

    def __init__(self):
        self.cache = {}

    def S(self, rec):
        k = bytes(rec)
        v = self.cache.get(k)
        if v is None:
            v = self.cache[k] = score(rec)
        return v


def build_partition(img, scorer=None, form=None):
    """The step 7 assignment on the current rosters, no header writes.

    Returns {'active_p' (10 pitchers by S), 'roster' (the 5 rotation, 3c+3v+4e
    order), 'relief' (the other 5, 3c+3v desc), 'field' (8 (slot, q) greedy in
    C SS 2B CF 3B RF LF 1B order), 'dh', 'backup_c', 'active_b' (15),
    'order' (the batting order), 'bench7' (the other active batters by S)}. 
    Ties are lowest slot. form = {slot: offset} is added to every S and
    Off + Fld depth comparison (not the rotation, relief or batting order)."""
    sc = scorer or _Scorer()
    fm = form or {}

    def rec(s):
        return img[HDR + REC * s:HDR + REC * (s + 1)]

    def fS(s):
        return sc.S(rec(s)) + fm.get(s, 0)

    pits = [s for s in range(16) if is_on(img, s)]
    bats = [s for s in range(16, 40) if is_on(img, s)]
    active_p = sorted(pits, key=lambda s: (-fS(s), s))[:10]
    rot = sorted(set(active_p), key=lambda s: (-pitch_score4(rec(s)), s))[:5]
    rest = [s for s in active_p if s not in set(rot)]
    rest.sort(key=lambda s: (-relief_score2(rec(s)), s))
    assigned = set()
    field = []
    for q in FIELD_ORDER:
        cands = [s for s in bats if s not in assigned and can_play(rec(s), q)]
        pick = None
        if cands:
            pick = min(cands, key=lambda s: (-(off(rec(s)) + fld(rec(s), q) + fm.get(s, 0)), s))
        else:
            cands = [s for s in bats if s not in assigned]
            if cands:
                pick = min(cands, key=lambda s: (-(off(rec(s)) + fld(rec(s), q) - 20
                                                    + fm.get(s, 0)), s))
        if pick is not None:
            field.append((pick, q))
            assigned.add(pick)
    rest_b = [s for s in bats if s not in assigned]
    dh = min(rest_b, key=lambda s: (-(off(rec(s)) + fm.get(s, 0)), s)) if rest_b else None
    if dh is not None:
        assigned.add(dh)
    rest_b = [s for s in bats if s not in assigned]
    c_cands = [s for s in rest_b if can_play(rec(s), 1)]
    backup_c = min(c_cands, key=lambda s: (-fld(rec(s), 1), s)) if c_cands else None
    if backup_c is not None:
        assigned.add(backup_c)
    rest_b = [s for s in bats if s not in assigned]
    rest_b.sort(key=lambda s: (-fS(s), s))
    n_reserved = len(field) + (1 if dh is not None else 0) \
        + (1 if backup_c is not None else 0)
    take = rest_b[:max(0, 15 - n_reserved)]
    active_b = [s for s, _ in field] \
        + ([dh] if dh is not None else []) \
        + ([backup_c] if backup_c is not None else []) + take
    starters = [s for s, _ in field] + ([dh] if dh is not None else [])
    order = sorted(starters, key=lambda s: (-off(rec(s)), s))
    field_slots = {s for s, _ in field}
    bench7 = sorted((s for s in active_b if s not in field_slots),
                    key=lambda s: (-fS(s), s))
    return {'active_p': active_p, 'roster': rot, 'relief': rest, 'field': field,
            'dh': dh, 'backup_c': backup_c, 'active_b': active_b, 'order': order,
            'bench7': bench7}


def order_lineup(starters, rec, pos_of_assign):
    """The batting order r1..r9, picked in turn from the starters, each pick
    removed, ties lowest slot: #1 max 3*speed + 2*hit_run, #2 max 2*hit_run +
    speed, #3 max Off, #4 max power, #5 max 3*power + hit_run, #6.. the rest
    by Off descending."""
    left = list(starters)

    def pick(key):
        s = min(left, key=lambda s: (-key(rec(s)), s))
        left.remove(s)
        return s

    picks = [pick(lambda r: 3 * _get(r, *F['speed']) + 2 * _get(r, *F['hit_run'])),
             pick(lambda r: 2 * _get(r, *F['hit_run']) + _get(r, *F['speed'])),
             pick(off),
             pick(lambda r: _get(r, *F['power'])),
             pick(lambda r: 3 * _get(r, *F['power']) + _get(r, *F['hit_run']))]
    while left:
        s = min(left, key=lambda s: (-off(rec(s)), s))
        left.remove(s)
        picks.append(s)
    return [(s, pos_of_assign[s]) for s in picks]


def form_draws(image, rng):
    """T.FORM_A > 0: one draw per named slot (slot order), offset d % (2A+1) - A."""
    a = T['FORM_A']
    if a <= 0:
        return None
    return {s: (rng.draw() & 0xff) % (2 * a + 1) - a for s in range(40) if is_on(image, s)}


def depth_rebuild(image, form=None):
    """Step 7 rebuild for an AI team: partition + header list writes."""
    p = build_partition(image, form=form)

    def rec(s):
        return image[HDR + REC * s:HDR + REC * (s + 1)]

    # staff +111..+120 (rotation then relievers), +110 = 0, +121 = 0xff
    image[H_STAFF:H_STAFF + 5] = bytes(p['roster']) + b'\xff' * (5 - len(p['roster']))
    image[H_STAFF + 5:H_STAFF + 10] = bytes(p['relief']) + b'\xff' * (5 - len(p['relief']))
    image[H_STAFF - 1] = 0
    image[H_STAFF + 10] = 0xff
    # batting order: the role picks over the 9 starters (DH sets) and again
    # over the 8 field starters (no-DH sets, 0xff + position 0 in the 9th)
    pos_of = dict(p['field'])
    if p['dh'] is not None:
        pos_of[p['dh']] = 9
    field_slots = [s for s, _ in p['field']]
    dh_lineup = order_lineup(field_slots + ([p['dh']] if p['dh'] is not None
                                             else []), rec, pos_of)
    nodh_lineup = order_lineup(field_slots, rec, pos_of)
    for dh_flag in (0, 1):
        lineup = dh_lineup if dh_flag else nodh_lineup
        for vs in (0, 1):
            lo = H_LINEUP + dh_flag * 18 + vs * 9
            po = H_DEF + dh_flag * 18 + vs * 9
            slots = [s for s, _ in lineup]
            positions = [pos for _, pos in lineup]
            while len(slots) < 9:
                slots.append(0xff)
                positions.append(0)
            image[lo:lo + 9] = bytes(slots)
            image[po:po + 9] = bytes(positions)
            # bench +194: the other active batters by S descending
            # (no-DH: 7 entries incl. the DH; DH: 6 then 0xff)
            b = H_BENCH + dh_flag * 14 + vs * 7
            bench = [s for s in p['bench7'] if not (dh_flag and s == p['dh'])]
            n = 7 if not dh_flag else 6
            image[b:b + 7] = bytes(bench[:n]).ljust(7, b'\xff')   # short bench: pad (C pads)
    # reserves +222..+236: the 6 inactive pitchers, then the 9 inactive batters
    inactive_p = [s for s in range(16) if is_on(image, s)
                  and s not in set(p['active_p'])]
    inactive_b = [s for s in range(16, 40) if is_on(image, s)
                  and s not in set(p['active_b'])]
    image[H_RESERVE:H_RESERVE + 15] = (bytes(inactive_p[:6] + inactive_b[:9])
                                       .ljust(15, b'\xff'))
    return p


def changed_slots(stem, img, snap):
    """Slots whose occupant changed this offseason (name bytes or the active
    flag differ from the snapshot), plus any currently vacant slot."""
    out = set()
    for s in range(40):
        base = HDR + REC * s
        if img[base] == 0:
            out.add(s)
            continue
        if snap is not None:
            if bytes(snap[base:base + 20]) != bytes(img[base:base + 20]) \
                    or (snap[base] == 0) != (img[base] == 0):
                out.add(s)
    return out


def repair(image, changed):
    """Managed-team repair: every header list entry whose slot changed
    occupant this offseason (or is vacant) is replaced by the best S
    unchanged same-type reserve; the replacement is chosen ONCE per slot
    (first time it is met, lineup position filter by that first entry's
    position), memoized, and reused for every list entry holding that slot.
    A later lineup entry whose position the replacement cannot play gets the
    best reserve that can (one reserves swap per distinct replacement). The
    newcomer takes the reserve's place in +222..+236. Unchanged entries keep
    their bytes."""
    if not changed:
        return

    def rec(s):
        return image[HDR + REC * s:HDR + REC * (s + 1)]

    new_reserves = list(image[H_RESERVE:H_RESERVE + 15])
    entries = []
    for i in range(10):
        entries.append(('P', None, H_STAFF + i, image[H_STAFF + i]))
    for dh in (0, 1):
        for vs in (0, 1):
            for i in range(9):
                o = H_LINEUP + dh * 18 + vs * 9 + i
                pos = image[H_DEF + dh * 18 + vs * 9 + i]
                entries.append(('B', pos, o, image[o]))
            for i in range(7):
                o = H_BENCH + dh * 14 + vs * 7 + i
                entries.append(('B', None, o, image[o]))
    repl = {}                            # slot -> replacement slot (chosen once)

    def choose(slot, pitch, pos):
        if slot in repl:
            return repl[slot]
        cands = []
        for r in new_reserves:
            if r == 0xff or r == slot or not is_on(image, r) or r in changed:
                continue
            if is_pitcher(rec(r)) != pitch:
                continue
            if pos is not None and 1 <= pos <= 8 and not can_play(rec(r), pos):
                continue
            cands.append(r)
        if not cands:
            return None
        best = min(cands, key=lambda r: (-score(rec(r)), r))
        for i in range(15):
            if new_reserves[i] == best:
                new_reserves[i] = slot
                break
        repl[slot] = best
        return best

    for kind, pos, addr, slot in entries:
        if slot == 0xff:
            continue
        if slot not in changed and is_on(image, slot):
            continue
        pitch = kind == 'P'
        best = choose(slot, pitch, pos)
        if best is None:
            continue
        fits = (pos is None or not (1 <= pos <= 8) or can_play(rec(best), pos))
        if fits:
            image[addr] = best
            continue
        # a later lineup entry the replacement cannot play: pick the best
        # reserve that can, for this entry only
        cands = [r for r in new_reserves
                 if r != 0xff and r != slot and is_on(image, r) and r not in changed
                 and is_pitcher(rec(r)) == pitch
                 and (pos is None or not (1 <= pos <= 8) or can_play(rec(r), pos))]
        if cands:
            image[addr] = min(cands, key=lambda r: (-score(rec(r)), r))
        else:
            image[addr] = best
    image[H_RESERVE:H_RESERVE + 15] = bytes(new_reserves)


# ---------------------------------------------------------------------------
# The offseason pipeline (pure core)
# ---------------------------------------------------------------------------

class Move:
    """One pool-list capture: the player's record pair (copies), the source
    team stem (None = a pool file player) and the source slot, in move
    order. rookie = the slot was vacant in the snapshot (C4 rookie)."""
    __slots__ = ('stem', 'slot', 'pair', 'rookie')

    def __init__(self, stem, slot, pair, rookie=False):
        self.stem, self.slot, self.pair, self.rookie = stem, slot, pair, rookie

    def roster(self):
        return self.pair[0]

    def name(self):
        return pname(self.pair[0])

    def is_draft_class(self):
        """Draft class = pool players with exp = 0 and byte 141 = 0."""
        return self.pair[0][F['exp'][0]] == 0 and self.pair[0][141] == 0


def offseason(teams, snaps, retired, pool, standings, hist_hdr, rng):
    """The C6 offseason on in-memory state (see the module docstring for the
    argument shapes). Mutates the team and pool images, reads the rng seed
    from hist_hdr bytes 1..2 (0 -> 1) and writes the end word back, sets
    bytes 16..17 = the start word, and returns the event log (list of
    (code, parts) with code in RET DRAFT REL MKT SIGN TRADE POOLRET)."""
    ev = []
    era = hist_hdr[10]
    mask = struct.unpack_from('<I', hist_hdr, 12)[0]
    managed = {lg for _, lg, _ in teams if (mask >> lg) & 1}
    start_word = hist_hdr[1] | hist_hdr[2] << 8
    if start_word == 0:
        start_word = 1
    year = None
    start = hist_hdr[18] | hist_hdr[19] << 8
    if 1871 <= start <= 2100:
        # C13.1: a set start year runs the real calendar (bytes 4..5 = seasons recorded,
        # read after HISTWR, so this is the season being started)
        year = start + (hist_hdr[4] | hist_hdr[5] << 8)
    else:
        for _, _, img in teams:
            y = image_year(img)
            if y is not None:
                year = y
                break
    fa_on = era == 2 or (era == 0 and year is not None and year >= 1976)
    rev = rev_order(teams, standings)
    fwd = list(reversed(rev))

    snap_of = {stem: snaps.get(stem) for stem, _, _ in teams}
    ret_flags = {stem: (retired.get(stem) or [0] * 40) for stem, _, _ in teams}

    def rookie_flag(stem, slot):
        """C4 rookie = a slot named now that was vacant in the snapshot
        (both halves) or flagged in RETIRED.DAT."""
        snap = snap_of.get(stem)
        if snap is None:
            return False
        ro = HDR + REC * slot
        if snap[ro] or snap[HDR + REC * (slot + 40)]:
            return False
        return True

    def pt_of(stem, slot):
        """Playing-time class from the snapshot season record (slot i + 40).
        A slot vacant in the snapshot or a C4 rookie: class none."""
        snap = snap_of.get(stem)
        if snap is None or snap[HDR + REC * slot] == 0 or rookie_flag(stem, slot) \
                or ret_flags[stem][slot] == 1:
            return 0
        base = HDR + REC * slot
        r = snap[base:base + REC]
        s = snap[HDR + REC * (slot + 40):HDR + REC * (slot + 41)]
        pitcher = pos1f(r) == 0
        games = _get(s, *F['games'])
        if pitcher:
            return pt_class(games, 0, war.ipiv_outs(_get(s, *F['ip10'])), True)
        pa = (_get(s, *F['ab_l']) + _get(s, *F['ab_r'])
              + _get(s, *F['bb_l']) + _get(s, *F['bb_r']))
        return pt_class(games, pa, 0, False)

    # value cache keyed by record bytes (a moved player keeps his record)
    vcache = {}

    def V(rec):
        k = bytes(rec)
        v = vcache.get(k)
        if v is None:
            v = vcache[k] = value(rec)
        return v

    # ---- 1. pool cleanup ----------------------------------------------------
    for pimg in pool:
        for slot in range(40):
            base = HDR + REC * slot
            if pimg[base] and pimg[base + 141] >= T['POOL_YEARS']:
                ev.append(('POOLRET', (pname(pimg[base:base + REC]),)))
                vacate(pimg, slot)

    # ---- 2. draft class -------------------------------------------------------
    moved = []
    for stem, lg, img in teams:
        for slot in range(40):
            base = HDR + REC * slot
            if not img[base]:
                continue
            if rookie_flag(stem, slot) or ret_flags[stem][slot] == 1:
                moved.append(Move(stem, slot, copy_pair(img, slot), rookie=True))
                vacate(img, slot)
                ev.append(('DRAFT', (stem, pname(moved[-1].pair[0]))))

    # ---- 3. release (AI teams only) -------------------------------------------
    for stem, lg, img in teams:
        if lg in managed:
            continue
        pitchers = [s for s in range(16) if is_on(img, s)]
        batters = [s for s in range(16, 40) if is_on(img, s)]
        rec = lambda s: img[HDR + REC * s:HDR + REC * (s + 1)]
        prot = set()
        prot.update(sorted(pitchers, key=lambda s: (-V(rec(s)), s))[:T['KEEP_P']])
        prot.update(sorted(batters, key=lambda s: (-V(rec(s)), s))[:T['KEEP_B']])
        for p in (1, 5, 3, 7):
            c = [b for b in batters if pos1f(rec(b)) == p]
            if c:
                prot.add(min(c, key=lambda s: (-V(rec(s)), s)))
        for s in pitchers + batters:
            r = rec(s)
            if _get(r, *F['exp']) <= 1 and _get(r, *F['age']) <= 24:
                prot.add(s)
        med_p = lower_median([V(rec(s)) for s in pitchers]) if pitchers else None
        med_b = lower_median([V(rec(s)) for s in batters]) if batters else None
        count = 0
        for slot in pitchers + batters:
            if count >= T['REL_CAP']:
                break                          # no draw once the cap is reached
            if slot in prot:
                continue
            r = rec(slot)
            age = _get(r, *F['age'])
            band = 0 if age <= 24 else 1 if age <= 29 else 2 if age <= 33 else 3
            p = T['REL'][band][pt_of(stem, slot)]
            med = med_p if slot < 16 else med_b
            if med is not None and V(r) >= med:
                p >>= 1
            if (rng.draw() & 0xff) < p:
                moved.append(Move(stem, slot, copy_pair(img, slot)))
                vacate(img, slot)
                ev.append(('REL', (stem, pname(r))))
                count += 1

    # ---- 4. market (AI teams only, only when free agency is on) ----------------
    if fa_on:
        for stem, lg, img in teams:
            if lg in managed:
                continue
            for slot in range(40):
                base = HDR + REC * slot
                if not img[base]:
                    continue
                r = img[base:base + REC]
                if rookie_flag(stem, slot) or ret_flags[stem][slot] == 1:
                    continue
                if _get(r, *F['exp']) < 6:
                    continue
                if (rng.draw() & 0xff) < T['MKT']:
                    moved.append(Move(stem, slot, copy_pair(img, slot)))
                    vacate(img, slot)
                    ev.append(('MKT', (stem, pname(r))))

    # ---- 5. signing --------------------------------------------------------------
    # pool list = pool file players (files sorted, slots ascending), then the
    # moved players in the order they moved
    pool_list = []
    for pi, pimg in enumerate(pool):
        for slot in range(40):
            base = HDR + REC * slot
            if pimg[base]:
                pair = [pimg[base:base + REC],
                        pimg[base + 40 * REC:base + 41 * REC]]
                pool_list.append(Move(None, (pi, slot), [bytearray(pair[0]),
                                                         bytearray(pair[1])]))
    pool_list.extend(moved)
    signed = set()

    def img_of(stem):
        for s, lg, img in teams:
            if s == stem:
                return img
        return None

    def team_ranks(img):
        """AI need table: for each batter position the team's highest V among
        pos1 batters; for each pitcher role the 5th highest V (0 if fewer
        than 5)."""
        out = {}
        bypos = {}
        for s in range(16, 40):
            if is_on(img, s):
                r = img[HDR + REC * s:HDR + REC * (s + 1)]
                bypos.setdefault(pos1f(r), []).append(V(r))
        for p, vs in bypos.items():
            out[('B', p)] = max(vs)
        for role in ('SP', 'RP'):
            vs = sorted((V(img[HDR + REC * s:HDR + REC * (s + 1)])
                         for s in range(16) if is_on(img, s)
                         and sp_rp(img[HDR + REC * s:HDR + REC * (s + 1)]) == role),
                        reverse=True)
            out[('P', role)] = vs[4] if len(vs) >= 5 else 0
        return out

    def sign_place(img, stem, move, dst):
        write_pair(img, dst, move.pair)
        write_pool_years(img, dst, 0)
        signed.add(id(move))
        if move.stem is None:
            pi, pslot = move.slot
            vacate(pool[pi], pslot)
        ev.append(('SIGN', (stem, pname(move.pair[0]),
                            'pool' if move.stem is None else move.stem)))

    # rounds repeat until a full round signs nobody
    while True:
        acted = False
        taken = set()                       # a candidate signs at most once per round
        for k in rev:
            stem, lg, img = teams[k]
            vacs_p = [s for s in range(16) if not img[HDR + REC * s]]
            vacs_b = [s for s in range(16, 40) if not img[HDR + REC * s]]
            if not vacs_p and not vacs_b:
                continue
            ranks = team_ranks(img) if lg not in managed else None
            best = None
            for move in pool_list:
                if id(move) in signed or id(move) in taken:
                    continue
                pitch = is_pitcher(move.pair[0])
                vacs = vacs_p if pitch else vacs_b
                if not vacs:
                    continue
                if lg in managed:
                    # draft-class players of a vacant slot type; max V
                    if not move.is_draft_class():
                        continue
                    score_ = V(move.pair[0])
                else:
                    key = (('P', sp_rp(move.pair[0])) if pitch
                           else ('B', pos1f(move.pair[0])))
                    best_v = ranks.get(key, 0)
                    v = V(move.pair[0])
                    score_ = v + 2 * max(0, v - best_v)
                if best is None or score_ > best[0]:
                    best = (score_, move, vacs[0])
            if best is not None:
                taken.add(id(best[1]))
                sign_place(img, stem, best[1], best[2])
                acted = True
        if not acted:
            break

    # ---- 6. trades (AI teams only, no draws) -------------------------------------
    parts = {}
    for stem, lg, img in teams:
        if lg not in managed:
            parts[stem] = build_partition(img, _Scorer())

    def sc_rec(r):
        """Cached S for the trade pass (V cache stays keyed by bytes; S gets
        its own key)."""
        k = (1, bytes(r))
        v = vcache.get(k)
        if v is None:
            v = vcache[k] = score(r)
        return v

    med = {}
    for q in Q_ORDER:
        vals = []
        for stem, lg, img in teams:
            if lg in managed:
                continue
            p = parts[stem]

            def rec(s):
                return img[HDR + REC * s:HDR + REC * (s + 1)]

            if q in (1, 2, 3, 4, 5, 6, 7, 8):
                vals.extend(sc_rec(rec(s)) for s, qq in p['field'] if qq == q)
            else:
                vals.extend(sc_rec(rec(s))
                            for s in (p['roster'] if q == 'SP' else p['relief']))
        med[q] = lower_median(vals) if vals else None

    def team_need(stem, q):
        p = parts[stem]
        img = img_of(stem)

        def rec(s):
            return img[HDR + REC * s:HDR + REC * (s + 1)]

        if q in (1, 2, 3, 4, 5, 6, 7, 8):
            for s, qq in p['field']:
                if qq == q:
                    return med[q] - sc_rec(rec(s))
            return 0
        src = p['roster'] if q == 'SP' else p['relief']
        if not src:
            return 0
        worst = min(sc_rec(rec(s)) for s in src)
        return med[q] - worst

    def top3(stem, pitch):
        img = img_of(stem)
        slots = range(16) if pitch else range(16, 40)
        named = [s for s in slots if is_on(img, s)]
        return set(sorted(named, key=lambda s: (-V(img[HDR + REC * s:HDR + REC * (s + 1)]),
                                                s))[:3])

    def surplus(stem, q):
        """Surplus at q: non-starters whose can_play(q) (pitchers: role q) and
        whose S >= median(q), as [(slot, rec)] ascending."""
        img = img_of(stem)
        p = parts[stem]
        if med[q] is None:
            return []
        used = {s for s, _ in p['field']} | set(p['roster']) | set(p['relief']) \
            | ({p['dh']} if p['dh'] is not None else set())
        out = []
        for s in range(40):
            if s in used or not is_on(img, s):
                continue
            r = img[HDR + REC * s:HDR + REC * (s + 1)]
            if q in (1, 2, 3, 4, 5, 6, 7, 8):
                if is_pitcher(r) or not can_play(r, q):
                    continue
            else:
                if not is_pitcher(r) or sp_rp(r) != q:
                    continue
            if sc_rec(r) >= med[q]:
                out.append((s, r))
        return out

    trade_count = 0
    traded = set()
    for k in fwd:
        if trade_count >= T['MAX_TRADES']:
            break
        stemA, lgA, imgA = teams[k]
        if lgA in managed or stemA in traded:
            continue
        needs = [(Q_ORDER.index(q), q) for q in Q_ORDER
                 if team_need(stemA, q) > T['NEED']]
        if not needs:
            continue
        _, q = min(needs)
        qtype = 'P' if q in ('SP', 'RP') else 'B'
        done = False
        for stemB, lgB, imgB in teams:
            if stemB == stemA or lgB in managed or stemB in traded:
                continue
            for sX, rX in surplus(stemB, q):
                for q2 in Q_ORDER:
                    if qtype == 'P' and q2 not in ('SP', 'RP'):
                        continue
                    if qtype == 'B' and q2 in ('SP', 'RP'):
                        continue
                    if team_need(stemB, q2) <= T['NEED']:
                        continue
                    for sY, rY in surplus(stemA, q2):
                        sX3 = top3(stemB, qtype == 'P')
                        sY3 = top3(stemA, qtype == 'P')
                        if sX in sX3 or sY in sY3:
                            continue
                        vx, vy = V(rX), V(rY)
                        top = max(vx, vy)
                        if top and abs(vx - vy) * 100 > T['BAND'] * top:
                            continue
                        # swap x and y (each takes the other's slot): x (B slot
                        # sX) takes y's slot (A sY), y takes x's slot; the
                        # records AND their season twins move together
                        pX, pY = copy_pair(imgB, sX), copy_pair(imgA, sY)
                        vacate(imgB, sX)
                        vacate(imgA, sY)
                        write_pair(imgA, sY, pX)
                        write_pair(imgB, sX, pY)
                        ev.append(('TRADE', (stemA, pname(pX[0]), stemB, pname(pY[0]))))
                        traded.add(stemA)
                        traded.add(stemB)
                        trade_count += 1
                        done = True
                        break
                    if done:
                        break
                if done:
                    break
            if done:
                break

    # ---- 7. depth rebuild (AI) or repair (managed), pool write-back ---------------
    for stem, lg, img in teams:
        if lg in managed:
            snap = snap_of.get(stem)
            repair(img, changed_slots(stem, img, snap))
        else:
            depth_rebuild(img, form_draws(img, rng))

    unsigned = [e for e in pool_list if id(e) not in signed]
    list_pos = {id(e): i for i, e in enumerate(pool_list)}
    unsigned.sort(key=lambda e: (-V(e.pair[0]), list_pos[id(e)]))
    keep, drop = [], []
    cnt = {1: 0, 2: 0}
    for e in unsigned:
        typ = 1 if is_pitcher(e.pair[0]) else 2
        cap = T['POOL_KEEP_P'] if typ == 1 else T['POOL_KEEP_B']
        if cnt[typ] < cap:
            keep.append(e)
        else:
            drop.append(e)
        cnt[typ] += 1
    # unsigned pool-list players sorted by V descending, ties earliest. Every
    # unsigned entity first vacates its source (a pool-file player his file
    # slot, a moved player his team slot, already vacated), then the first
    # T.POOL_KEEP (pitchers and batters counted separately) are written to
    # POOL1..POOL4 lowest vacant slots of their type with byte 141 += 1 (both
    # halves); the rest retire unsigned. Vacant pool slots are the next draft
    # class.
    for e in unsigned:
        if e.stem is None:
            pi, pslot = e.slot
            vacate(pool[pi], pslot)
    for e in keep:
        pitch = is_pitcher(e.pair[0])
        slots = range(16) if pitch else range(16, 40)
        placed = False
        for pimg in pool:
            for slot in slots:
                if not pimg[HDR + REC * slot]:
                    write_pair(pimg, slot, e.pair)
                    for half in (0, 40):
                        o = HDR + REC * (slot + half) + 141
                        pimg[o] = (pimg[o] + 1) & 0xff
                    placed = True
                    break
            if placed:
                break
    for e in drop:
        ev.append(('POOLRET', (e.name(),)))

    # ---- 8. HISTORY bytes 16..17 = start word, 1..2 = end word --------------------
    struct.pack_into('<H', hist_hdr, 16, start_word)
    hist_hdr[1], hist_hdr[2] = rng.s & 0xff, (rng.s >> 8) & 0xff
    return ev


# ---------------------------------------------------------------------------
# C9 All-Star refresh
# ---------------------------------------------------------------------------

ALLSTAR_FILES = (('ALLSTAR1.V20', 0), ('ALLSTAR2.V20', 16))   # (file, league-global id base)


def allstar_refresh(star, teams, lg_base):
    """C9: rebuild one ALLSTAR image in place from the teams whose league-global
    id is in lg_base..lg_base+15. teams = [(stem, lg, img)] after C6 step 7."""
    cands = []                                    # (rec bytes, team img, slot), file then slot order
    for _, lg, img in teams:
        if lg_base <= lg < lg_base + 16:
            for s in range(40):
                if img[HDR + REC * s]:
                    cands.append((bytes(img[HDR + REC * s:HDR + REC * (s + 1)]), img, s))
    used = set()

    def season(img, s):
        return img[HDR + REC * (s + 40):HDR + REC * (s + 41)]

    # Q6 qualifier: G = max season games over the league's candidates
    g_max = max((_get(season(img, s), *F['games']) for _, img, s in cands), default=0)

    def qualifies(r, img, s):
        sr = season(img, s)
        if is_pitcher(r):
            return war.ipiv_outs(_get(sr, *F['ip10'])) >= g_max
        return 2 * _get(sr, *F['games']) >= g_max

    qual = [qualifies(*c) for c in cands]

    def best(ok, key, only_q):
        pick = None
        for k, (r, _, _) in enumerate(cands):
            if k in used or (only_q and not qual[k]) or not ok(r):
                continue
            if pick is None or key(r) > key(cands[pick][0]):
                pick = k
        return pick

    def chain(i, only_q):
        if i < 16:                                # C6 slot types, not the template record
            return best(is_pitcher, score, only_q)  # (a DYNASTY fill can leave a batter in 0..15)
        q = pos1f(star[HDR + REC * i:HDR + REC * (i + 1)])
        k = best(lambda r: not is_pitcher(r) and pos1f(r) == q, score, only_q)
        if k is None:
            k = best(lambda r: not is_pitcher(r) and can_play(r, q),
                     lambda r: off(r) + fld(r, q), only_q)
        if k is None:
            k = best(lambda r: not is_pitcher(r), score, only_q)
        return k

    for i in range(40):
        o = HDR + REC * i
        if not star[o]:
            continue
        k = chain(i, True)
        if k is None:
            k = chain(i, False)
        if k is None:
            vacate(star, i)
            continue
        used.add(k)
        _, img, s = cands[k]
        write_pair(star, i, copy_pair(img, s))
    depth_rebuild(star)


def refresh_allstars(league_dir):
    """C9 outside a roll: rebuild the league's ALLSTAR files in place from its current team files (a freshly built
    league, H1). Same selection as run(); a missing or wrong-size ALLSTAR file is skipped. Returns the files rewritten."""
    m = maj_load(history_mod.maj_or_none(league_dir))
    teams = [(os.path.basename(p)[:-4].lower(), lg, bytearray(open(p, 'rb').read()))
             for p, lg in history_mod.mapped_teams(league_dir, m)]
    done = []
    for name, base in ALLSTAR_FILES:
        sp = _file_ci(league_dir, name)
        if sp and os.path.getsize(sp) == HDR + REC * 80:
            img = bytearray(open(sp, 'rb').read())
            allstar_refresh(img, teams, base)
            open(sp, 'wb').write(bytes(img))
            done.append(sp)
    return done


# ---------------------------------------------------------------------------
# C15 expansion / contraction (ROSTERS /EXPAND)
# ---------------------------------------------------------------------------

EMPTY_NAME = b'EMPTY' + bytes(15)


def is_placeholder(img, slot):
    """Placeholder record (C15.1): byte 0 != 0 and bytes 0..19 = b'EMPTY' + 15
    NUL (the roster record i drives it)."""
    base = HDR + REC * slot
    return img[base] != 0 and bytes(img[base:base + 20]) == EMPTY_NAME


def real_player(img, slot):
    """Real player (C15.1): byte 0 != 0 and not a placeholder."""
    return img[HDR + REC * slot] != 0 and not is_placeholder(img, slot)


def team_file_of(league_dir, stem8):
    """Team file of a stem (C15.1): <stem>.V20 in the league dir, any case,
    exactly 11735 B; else None. stem8 = 8 B NUL padded."""
    stem = stem8.rstrip(b'\0').decode('latin-1').lower()
    tp = _team_path(league_dir, stem)
    if tp and os.path.getsize(tp) == HDR + REC * 80:
        return tp
    return None


def count_real(img, lo, hi):
    """Real players in roster slots lo..hi-1 (roster half only)."""
    return sum(1 for s in range(lo, hi) if real_player(img, s))


def expand(league_dir, snap_dir, hist_path):
    """C15.4: the /EXPAND step. Returns 0 anything written, 1 nothing (no
    event), 2 error (no file changed). No rng, no draws, no HISTORY writes."""
    try:
        mp = history_mod.maj_or_none(league_dir)
        if mp is None:
            return 2
        raw = open(mp, 'rb').read()
        if len(raw) < 59771:
            return 2
        m = maj_load(mp)
        cur = list(teamids.maj_teams(m.d))
        nd = teamids.ndiv(m.d)
        # snapshot MAJ: the file named like the current MAJ (any case), >= 59771 B
        snap_m = None
        if os.path.isdir(snap_dir):
            for f in sorted(os.listdir(snap_dir)):
                if f.upper() == os.path.basename(mp).upper() \
                        and os.path.isfile(os.path.join(snap_dir, f)):
                    sp = os.path.join(snap_dir, f)
                    sb = open(sp, 'rb').read()
                    if len(sb) >= 59771:
                        snap_m = maj_load(sp)
                    break
        # ---- C15.2 detection ----
        contracted = []
        if snap_m is not None:
            cur_stems = {st.rstrip(b'\0').lower() for _, _, st in cur}
            for L, slot, st in teamids.maj_teams(snap_m.d):
                if st.rstrip(b'\0').lower() not in cur_stems:
                    contracted.append((L, slot, st))
        expansion = []
        for L, slot, st in cur:
            tp = _team_path(league_dir, st.rstrip(b'\0').decode('latin-1').lower())
            if tp and os.path.getsize(tp) == HDR + REC * 80:
                img = open(tp, 'rb').read()
                if not any(real_player(bytearray(img), s) for s in range(40)):
                    expansion.append((L, slot, st))
        moved = []
        if snap_m is not None:
            cur_e = {st.rstrip(b'\0').lower(): teamids.slot_to_engine(L, slot, nd)
                     for L, slot, st in cur}
            for L, slot, st in teamids.maj_teams(snap_m.d):
                k = st.rstrip(b'\0').lower()
                if k in cur_e and cur_e[k] != teamids.slot_to_engine(
                        L, slot, teamids.ndiv(snap_m.d)):
                    moved.append((L, slot, st))
        # ---- C15.3 stable ids ----
        table = teamids.load_table(league_dir)
        table_existed = table is not None
        if table is None and (contracted or expansion or moved):
            if snap_m is not None:
                tab = teamids.make_table(snap_m.d)
            else:
                tab = bytearray(teamids.make_table(m.d))
                for L, slot, st in expansion:
                    k = teamids.slot_to_engine(L, slot, nd)
                    if k < 32:
                        tab[8 * k:8 * k + 8] = bytes(8)
            table = [bytes(tab[8 * k:8 * k + 8]) for k in range(32)]
        if table is not None:
            for L, slot, st in cur:
                if _id_of_stem8(table, st) is not None:
                    continue
                free = None
                for k in range(L * 16, L * 16 + 16):
                    if table[k][:1] == b'\0':
                        free = k
                        break
                if free is None:
                    continue                        # no free k: no id
                table[free] = bytes(st)
        table_changed = table is not None and (
            not table_existed
            or bytes(b''.join(table)) != open(teamids.table_path(league_dir),
                                              'rb').read())
        if not contracted and not expansion:
            # moved only: the ids above are the whole event (C15.4 step 1); the
            # made or extended table is written, nothing else
            tmps = []
            try:
                t_out = bytes(b''.join(table)) if table_changed else None
                if t_out is not None:
                    tp0 = teamids.table_path(league_dir)
                    p = tp0 or os.path.join(league_dir, teamids.TABLE_NAME)
                    tp = p + '.TMP'
                    with open(tp, 'wb') as f:
                        f.write(t_out)
                    tmps.append((tp, p))
            except Exception:
                for tp, _p in tmps:
                    if os.path.exists(tp):
                        os.remove(tp)
                raise
            for tp, p in tmps:
                os.replace(tp, p)
            return 0 if tmps else 1
        # ---- mask (HISTORY bytes 12..15, u32 LE) ----
        mask = 0
        try:
            hb = open(hist_path, 'rb').read()
            if len(hb) >= 16:
                mask = struct.unpack_from('<I', hb, 12)[0]
        except Exception:
            mask = 0

        def team_img(stem8):
            tp = team_file_of(league_dir, stem8)
            return bytearray(open(tp, 'rb').read()) if tp else None

        def snap_img(stem8):
            stem = stem8.rstrip(b'\0').decode('latin-1').lower()
            if not os.path.isdir(snap_dir):
                return None
            for f in sorted(os.listdir(snap_dir)):
                if f.upper().endswith('.V20') \
                        and os.path.basename(f)[:-4].lower() == stem \
                        and os.path.isfile(os.path.join(snap_dir, f)) \
                        and os.path.getsize(os.path.join(snap_dir, f)) == HDR + REC * 80:
                    return bytearray(open(os.path.join(snap_dir, f), 'rb').read())
            return None
        # ---- pool ----
        first_team = None
        for k, L, slot, st in sorted(teamids.teams(m.d, table)):
            img = team_img(st)
            if img is not None:
                first_team = img
                break
        pool_imgs = []
        for name in POOL_FILES:
            pp = os.path.join(league_dir, name)
            pool_imgs.append(bytearray(open(pp, 'rb').read())
                             if os.path.isfile(pp)
                             else (pool_blank(first_team) if first_team else None))
        changed_team = set()                    # lower stems
        changed_pool = set()                    # pool indices
        ev = []

        vcache = {}

        def V(rec):
            k = bytes(rec)
            v = vcache.get(k)
            if v is None:
                v = vcache[k] = value(rec)
            return v

        # ---- 2. dispersal ----
        team_img_by_stem = {}       # lower stem -> the image that gets written
        for L, slot, st in contracted:
            stem_u = st.rstrip(b'\0').decode('latin-1').upper()
            stem_l = stem_u.lower()
            img = team_img(st)
            if img is None:
                img = snap_img(st)
            ev.append(('CONTRACT', (stem_u,)))
            if img is None:
                continue
            players = [(s, img[HDR + REC * s:HDR + REC * (s + 1)])
                       for s in range(40) if real_player(img, s)]
            players.sort(key=lambda t: (-V(t[1]), t[0]))
            tp = _team_path(league_dir, stem_l)
            has_file = tp and os.path.getsize(tp) == HDR + REC * 80
            for s, rec in players:
                pitch = is_pitcher(rec)
                placed = False
                for pi, pimg in enumerate(pool_imgs):
                    if pimg is None:
                        continue
                    for pslot in (range(16) if pitch else range(16, 40)):
                        if pimg[HDR + REC * pslot] == 0:
                            write_pair(pimg, pslot, copy_pair(img, s))
                            write_pool_years(pimg, pslot, 0)
                            changed_pool.add(pi)
                            placed = True
                            break
                    if placed:
                        break
                name = pname(rec)
                ev.append(('REL', (stem_u, name)) if placed
                          else ('POOLRET', (name,)))
            if has_file:
                for s in range(40):
                    if real_player(img, s):
                        vacate(img, s)
                changed_team.add(stem_l)
                team_img_by_stem[stem_l] = img
        # ---- 3. draft ----
        def id_of(L, slot, st):
            if table is None:
                return teamids.slot_to_engine(L, slot, nd)
            return _id_of_stem8(table, st)

        E = sorted((k, L, slot, st) for L, slot, st in expansion
                   if (k := id_of(L, slot, st)) is not None)
        E_ids = {k for k, _, _, _ in E}

        def stem_u_of(stem8):
            return stem8.rstrip(b'\0').decode('latin-1').upper()

        sources = []
        for L, slot, st in cur:
            k = id_of(L, slot, st)
            if k is None or k in E_ids:
                continue
            if (mask >> k) & 1:
                continue                        # a managed team loses nobody
            if team_img(st) is None:
                continue
            sources.append((k, L, slot, st))
        sources.sort()
        src_img = {k: team_img(st) for k, _L, _s, st in sources}
        e_img = {k: team_img(st) for k, _L, _s, st in E}
        for _k, _L, _s, st in E:
            team_img_by_stem[stem_u_of(st).lower()] = e_img[_k]
        for k, _L, _s, st in sources:
            team_img_by_stem[stem_u_of(st).lower()] = src_img[k]
        e_name = {k: stem_u_of(st) for k, _L, _s, st in E}
        src_name = {k: stem_u_of(st) for k, _L, _s, st in sources}
        prot = {}
        for k, _L, _s, _st in sources:
            img = src_img[k]
            named = [s for s in range(40) if real_player(img, s)]
            prot[k] = set(sorted(named, key=lambda s: (
                -V(img[HDR + REC * s:HDR + REC * (s + 1)]), s))[:15])
        cap = {k: 2 * len(E) for k, _L, _s, _st in sources}
        got = {k: 0 for k, _L, _s, _st in E}

        def e_needs(k):
            need = []
            if count_real(e_img[k], 0, 16) < 10:
                need.append(True)
            if count_real(e_img[k], 16, 40) < 15:
                need.append(False)
            return need

        while True:
            acted = False
            for k, _L, _s, _st in E:
                img = e_img[k]
                need = e_needs(k)
                if not need:
                    continue
                best = None
                for sk, _sL, _ss, _sst in sources:
                    if cap[sk] <= 0:
                        continue
                    simg = src_img[sk]
                    for s in range(40):
                        if not real_player(simg, s) or s in prot[sk]:
                            continue
                        rec = simg[HDR + REC * s:HDR + REC * (s + 1)]
                        pit = is_pitcher(rec)
                        if not (pit and True in need or not pit and False in need):
                            continue
                        key = (-V(rec), sk, s)
                        if best is None or key < best[0]:
                            best = (key, sk, s)
                if best is None:
                    continue
                _key, sk, s = best
                rec = src_img[sk][HDR + REC * s:HDR + REC * (s + 1)]
                dst = next((d for d in (range(16) if is_pitcher(rec)
                                        else range(16, 40))
                            if not real_player(img, d)), None)
                if dst is None:
                    continue
                write_pair(img, dst, copy_pair(src_img[sk], s))
                write_pool_years(img, dst, 0)
                vacate(src_img[sk], s)
                cap[sk] -= 1
                got[k] += 1
                ev.append(('SIGN', (e_name[k], pname(rec), src_name[sk])))
                changed_team.add(e_name[k].lower())
                changed_team.add(src_name[sk].lower())
                acted = True
            if not acted:
                break
        # ---- 4. pool signing ----
        while True:
            acted = False
            for k, _L, _s, _st in E:
                img = e_img[k]
                need = []
                if any(not real_player(img, d) for d in range(16)):
                    need.append(True)
                if any(not real_player(img, d) for d in range(16, 40)):
                    need.append(False)
                if not need:
                    continue
                best = None
                for pi, pimg in enumerate(pool_imgs):
                    if pimg is None:
                        continue
                    for pslot in range(40):
                        if pimg[HDR + REC * pslot] == 0:
                            continue
                        rec = pimg[HDR + REC * pslot:HDR + REC * (pslot + 1)]
                        if is_pitcher(rec) not in need:
                            continue
                        key = (-V(rec), pi, pslot)
                        if best is None or key < best[0]:
                            best = (key, pi, pslot, rec)
                if best is None:
                    continue
                _key, pi, pslot, rec = best
                dst = next(d for d in (range(16) if is_pitcher(rec)
                                       else range(16, 40))
                           if not real_player(img, d))
                write_pair(img, dst, copy_pair(pool_imgs[pi], pslot))
                write_pool_years(img, dst, 0)
                vacate(pool_imgs[pi], pslot)
                changed_pool.add(pi)
                changed_team.add(e_name[k].lower())
                got[k] += 1
                ev.append(('SIGN', (e_name[k], pname(rec), 'pool')))
                acted = True
            if not acted:
                break
        # ---- 5. floor ----
        for k, _L, _s, _st in E:
            img = e_img[k]
            for lo, hi, floor in ((0, 16, 10), (16, 40, 15)):
                keep_n = max(0, floor - count_real(img, lo, hi))
                seen = 0
                for s in range(lo, hi):
                    if is_placeholder(img, s):
                        if seen < keep_n:
                            seen += 1
                        else:
                            vacate(img, s)
                    elif not real_player(img, s):
                        vacate(img, s)
        # ---- 6. depth rebuild ----
        for k, _L, _s, _st in E:
            if got[k]:
                depth_rebuild(e_img[k], None)
        lost = {k for k in cap if cap[k] < 2 * len(E)}
        for k in sorted(lost):
            if k in src_img:
                depth_rebuild(src_img[k], None)
        # ---- 8. writes ----
        tp0 = teamids.table_path(league_dir)
        table_out = bytes(b''.join(table)) if table_changed else None
        tmps = []
        try:
            def put(path, data):
                tp = path + '.TMP'
                with open(tp, 'wb') as f:
                    f.write(bytes(data))
                tmps.append((tp, path))
            for stem_l in sorted(changed_team):
                p = _team_path(league_dir, stem_l)
                if p:
                    data = team_img_by_stem.get(stem_l)
                    if data is None:
                        data = bytearray(open(p, 'rb').read())
                    put(p, data)
            for pi in sorted(changed_pool):
                if pool_imgs[pi] is not None:
                    put(os.path.join(league_dir, POOL_FILES[pi]), pool_imgs[pi])
            if table_out is not None:
                p = tp0 or os.path.join(league_dir, teamids.TABLE_NAME)
                put(p, table_out)
            txt_p = _file_ci(league_dir, 'ROSTERS.TXT') \
                or os.path.join(league_dir, 'ROSTERS.TXT')
            existing = open(txt_p, 'rb').read() if os.path.isfile(txt_p) else b''
            # ROSTERS.TXT is appended (C6 run() overwrites it; /EXPAND appends), CRLF,
            # in order: per contracted stem CONTRACT then its REL / POOLRET lines; per
            # E team that got a player EXPAND; the draft SIGN lines in pick order;
            # the pool SIGN lines
            out_lines = []
            seg = []
            for code, parts in ev:
                if code == 'CONTRACT':
                    if seg:
                        out_lines.extend(seg)
                        seg = []
                    out_lines.append('CONTRACT %s' % parts[0])
                elif code == 'REL':
                    seg.append('REL %s %s' % (parts[0].upper(), parts[1]))
                elif code == 'POOLRET':
                    seg.append('POOLRET %s' % parts[0])
            if seg:
                out_lines.extend(seg)
            for k, _L, _s, st in E:
                if got[k]:
                    out_lines.append('EXPAND %s' % e_name[k])
            for code, parts in ev:
                if code == 'SIGN' and parts[2] != 'pool':
                    out_lines.append('SIGN %s %s %s'
                                     % (parts[0].upper(), parts[1], parts[2]))
            for code, parts in ev:
                if code == 'SIGN' and parts[2] == 'pool':
                    out_lines.append('SIGN %s %s %s'
                                     % (parts[0].upper(), parts[1], parts[2]))
            if out_lines:
                body = b'\r\n'.join(l.encode('latin-1') for l in out_lines) + b'\r\n'
                put(txt_p, existing + body)
        except Exception:
            for tp, _p in tmps:
                if os.path.exists(tp):
                    os.remove(tp)
            raise
        for tp, p in tmps:
            os.replace(tp, p)
        return 0 if tmps else 1
    except Exception:
        return 2


def _id_of_stem8(table, stem8):
    """The lowest k whose table entry matches the stem (ASCII case-insensitive,
    trailing NULs ignored), or None."""
    want = stem8.rstrip(b'\0').lower()
    for k, e in enumerate(table):
        if e[:1] != b'\0' and e.rstrip(b'\0').lower() == want:
            return k
    return None


# ---------------------------------------------------------------------------
# File wrapper. 0 ok, 2 error (files untouched on error).
# ---------------------------------------------------------------------------

HIST_HDR_SIZE = 32


def parse_retired(path):
    """C5 RETIRED.DAT: u8 nteam, then nteam x (13 B DTA name, 40 B flags,
    flag i = 1 = the roll retired roster record i). {stem: [40 flags]}."""
    if not path or not os.path.isfile(path):
        return {}
    b = open(path, 'rb').read()
    out = {}
    if len(b) < 1:
        return out
    off = 1
    for _ in range(b[0]):
        if off + 53 > len(b):
            break
        name13 = bytes(b[off:off + 13]).split(b'\0')[0].decode('latin-1')
        stem = name13.split('.')[0].lower()
        out[stem] = [1 if x else 0 for x in b[off + 13:off + 53]]
        off += 53
    return out


def league_standings(m, table=None):
    """{stable team id: (W, L)} for every team of teamids.teams (C12.3): the W/L of its MAJ slot.
    table = the TEAMID.DAT stems (teamids.load_table) or None for the engine ids."""
    out = {}
    for k, L, slot, _st in teamids.teams(m, table):
        out[k] = m.wl('AL' if L == 0 else 'NL', slot)
    return out


def run(league_dir, snap_dir, hist_path, retired_path):
    """Exit code 0 ok, 2 error; files untouched on error."""
    if not os.path.isfile(hist_path):
        return 2
    mp = history_mod.maj_or_none(league_dir)
    if mp is None:
        return 2
    try:
        m = maj_load(mp)
        teams = []
        for p, lg in history_mod.mapped_teams(league_dir, m):
            stem = os.path.basename(p)[:-4].lower()
            teams.append((stem, lg, bytearray(open(p, 'rb').read())))
        if not teams:
            return 2
        pool = []
        for name in POOL_FILES:
            pp = os.path.join(league_dir, name)
            pool.append(bytearray(open(pp, 'rb').read())
                        if os.path.isfile(pp)
                        else pool_blank(teams[0][2]))
        snaps = {}
        for stem, _, _ in teams:
            sp = os.path.join(snap_dir, stem.upper() + '.V20')
            snaps[stem] = open(sp, 'rb').read() if os.path.isfile(sp) else None
        hist_raw = open(hist_path, 'rb').read()
        hist_hdr = bytearray(hist_raw[:HIST_HDR_SIZE].ljust(HIST_HDR_SIZE, b'\0'))
        retired = parse_retired(retired_path)
        seed = hist_hdr[1] | hist_hdr[2] << 8
        rng = Rng(seed if seed else 1)
        table = teamids.load_table(league_dir)
        ev = offseason(teams, snaps, retired, pool, league_standings(m, table),
                       hist_hdr, rng)
        stars = []                                # C9: [(path, image)]
        for name, base in ALLSTAR_FILES:
            sp = _file_ci(league_dir, name)
            if sp and os.path.getsize(sp) == HDR + REC * 80:
                img = bytearray(open(sp, 'rb').read())
                allstar_refresh(img, teams, base)
                stars.append((sp, img))
        # a placeholder line (created or dynasty rookie) becomes the line its ratings imply
        for _, _, img in teams:
            statline.repair_image(img)
        for pimg in pool:
            statline.repair_image(pimg)
        for _, img in stars:
            statline.repair_image(img)
        # C12.5 / C12.6 step 9: the playoff format (HISTORY byte 11) against the same MAJ
        # bytes run() read above; a plan that does nothing adds no line
        tfile = teamids.table_path(league_dir)
        table_bytes = open(tfile, 'rb').read() if tfile else None
        fcode, new_maj, new_table, reason = realign.plan(bytes(m.d), hist_raw, table_bytes)
        if fcode == 2:
            ev.append(('FORMAT', ['REFUSED', reason]))
        elif fcode == 0:
            ev.append(('FORMAT', [str(new_maj[0x20d])]))
        # write every output to <path>.TMP first, then os.replace them all only
        # after every TMP write succeeded (the except removes the TMPs), so an
        # IO error leaves every file untouched
        tmps = []
        try:
            pp = os.path.join(league_dir, 'ROSTERS.TXT')
            tp = pp + '.TMP'
            with open(tp, 'wb') as f:
                f.write(rosters_txt(ev))
            tmps.append((tp, pp))
            for stem, _, img in teams:
                p = _team_path(league_dir, stem)
                if p:
                    tp = p + '.TMP'
                    with open(tp, 'wb') as f:
                        f.write(bytes(img))
                    tmps.append((tp, p))
            for name, pimg in zip(POOL_FILES, pool):
                p = os.path.join(league_dir, name)
                tp = p + '.TMP'
                with open(tp, 'wb') as f:
                    f.write(bytes(pimg))
                tmps.append((tp, p))
            # HISTORY header bytes 1..2 and 16..17 only; length kept
            out = bytearray(hist_raw)
            if len(out) < HIST_HDR_SIZE:
                out += bytes(HIST_HDR_SIZE - len(out))
            out[1], out[2] = hist_hdr[1], hist_hdr[2]
            out[16], out[17] = hist_hdr[16], hist_hdr[17]
            p = hist_path
            tp = p + '.TMP'
            with open(tp, 'wb') as f:
                f.write(bytes(out))
            tmps.append((tp, p))
            for p, img in stars:
                tp = p + '.TMP'
                with open(tp, 'wb') as f:
                    f.write(bytes(img))
                tmps.append((tp, p))
            if fcode == 0:
                # the realigned MAJ, and TEAMID.DAT when the plan made one (C12.3), commit with the rest
                tp = mp + '.TMP'
                with open(tp, 'wb') as f:
                    f.write(bytes(new_maj))
                tmps.append((tp, mp))
                if new_table is not None:
                    p = tfile or os.path.join(league_dir, teamids.TABLE_NAME)
                    tp = p + '.TMP'
                    with open(tp, 'wb') as f:
                        f.write(new_table)
                    tmps.append((tp, p))
        except Exception:
            for tp, _ in tmps:
                if os.path.exists(tp):
                    os.remove(tp)
            raise
        for tp, p in tmps:
            os.replace(tp, p)
        return 0
    except Exception:
        return 2


def _file_ci(league_dir, name):
    """The league-dir file named name, any case, or None."""
    for f in sorted(os.listdir(league_dir)):
        if f.upper() == name and os.path.isfile(os.path.join(league_dir, f)):
            return os.path.join(league_dir, f)
    return None


def _team_path(league_dir, stem):
    for p in glob.glob(os.path.join(league_dir, '*.V20')):
        if os.path.basename(p)[:-4].lower() == stem:
            return p
    return None


def maj_load(path):
    import maj
    return maj.Maj(open(path, 'rb').read())


def rosters_txt(ev):
    """ROSTERS.TXT body: CRLF, one line per event in order, names on every
    line. FORMAT events (C12.6) are 'FORMAT n' or 'FORMAT REFUSED reason'.
    CONTRACT events (C15) are 'CONTRACT <STEM>'; EXPAND events 'EXPAND <STEM>'."""
    lines = []
    for code, parts in ev:
        if code == 'FORMAT':
            lines.append('FORMAT ' + ' '.join(parts))
        elif code in ('RET', 'REL', 'MKT', 'DRAFT'):
            lines.append('%s %s %s' % (code, parts[0].upper(), parts[1]))
        elif code == 'SIGN':
            lines.append('SIGN %s %s %s' % (parts[0].upper(), parts[1], parts[2]))
        elif code == 'TRADE':
            lines.append('TRADE %s %s %s %s' % (parts[0].upper(), parts[1],
                                                parts[2].upper(), parts[3]))
        elif code == 'POOLRET':
            lines.append('POOLRET %s' % parts[0])
        elif code == 'CONTRACT':
            lines.append('CONTRACT %s' % parts[0])
        elif code == 'EXPAND':
            lines.append('EXPAND %s' % parts[0])
    return b'\r\n'.join(l.encode('latin-1') for l in lines) + (b'\r\n' if lines else b'')


def main(argv):
    usage = 'usage: rosters.py LEAGUE_DIR SNAP_DIR HIST_PATH RETIRED_PATH\n' \
            '       rosters.py /EXPAND LEAGUE_DIR SNAP_DIR HIST_PATH'
    if len(argv) == 5 and argv[1].upper() == '/EXPAND':
        return expand(argv[2], argv[3], argv[4])
    if len(argv) != 5:
        print(usage)
        return 2
    return run(argv[1], argv[2], argv[3], argv[4])


if __name__ == '__main__':
    sys.exit(main(sys.argv))
