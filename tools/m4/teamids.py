#!/usr/bin/env python3
"""Team ids for the M4 league: engine ids (contract C12.1) and stable ids (C12.3, TEAMID.DAT).

Engine id e = L * 16 + c (L 0 AL, 1 NL). c is the slot with 1 or 2 divisions, and the compacted slot with 3
divisions (the team byte in schedule pairs and playoff bytes).
The stable id is the k whose TEAMID.DAT entry holds the team's stem. With no table the stable id is the engine
id, which is the C2 rule for every 2-division league.

Every function takes the raw MAJ bytes, or a maj.Maj (its .d is used).
"""
import os

S = (0x21d, 0x758c)            # AL and NL league blocks
O_NAMES, O_ABBR, O_STEM = 0x0f, 0x18f, 0x1d7
SLOTS = 24
TABLE_NAME = 'TEAMID.DAT'
TABLE_SIZE = 256


def raw(m):
    return getattr(m, 'd', m)


def ndiv(d):
    d = raw(d)
    if len(d) <= 0x20d or d[0x20d] not in (1, 2, 3):
        return 2
    return d[0x20d]


def slot_to_engine(L, slot, nd):
    if nd == 3:
        c = slot if slot < 8 else (slot - 3 if slot < 16 else slot - 6)
    else:
        c = slot
    return L * 16 + c


def engine_to_slot(e, nd):
    L, i = (e >> 4) & 1, e & 15
    if nd == 3:
        slot = i if i < 5 else (i + 3 if i < 10 else i + 6)
    else:
        slot = i
    return L, slot


def maj_teams(d):
    """[(L, slot, stem8)] for L 0 then 1, slot ascending, every slot the division count uses (slot < 16 with 1
    or 2 divisions, slot % 8 < 5 with 3) whose stem starts with a non-NUL byte."""
    d = raw(d)
    if len(d) < S[1] + O_STEM + 8 * SLOTS:
        return []
    nd = ndiv(d)
    out = []
    for L in (0, 1):
        for slot in range(SLOTS):
            if (slot % 8 >= 5) if nd == 3 else (slot >= 16):
                continue
            a = S[L] + O_STEM + 8 * slot
            st = bytes(d[a:a + 8])
            if st[0] != 0:
                out.append((L, slot, st))
    return out


def table_path(league_dir):
    """The TEAMID.DAT of league_dir in any case (the first match in sorted order), or None."""
    if not os.path.isdir(league_dir):
        return None
    names = sorted(f for f in os.listdir(league_dir) if f.upper() == TABLE_NAME)
    return os.path.join(league_dir, names[0]) if names else None


def load_table(league_dir):
    """The 32 stems (8 B each, NUL padded) of TEAMID.DAT, or None when it is missing or not 256 B."""
    p = table_path(league_dir)
    if p is None:
        return None
    b = open(p, 'rb').read()
    if len(b) != TABLE_SIZE:
        return None
    return [b[8 * k:8 * k + 8] for k in range(32)]


def make_table(d):
    """256 B table: entry k = the stem of the team whose engine id is k, zero elsewhere (the first team wins)."""
    d = raw(d)
    nd = ndiv(d)
    tab = bytearray(TABLE_SIZE)
    seen = set()
    for L, slot, st in maj_teams(d):
        k = slot_to_engine(L, slot, nd)
        if k in seen or k >= 32:
            continue
        seen.add(k)
        tab[8 * k:8 * k + 8] = st
    return bytes(tab)


def _entries(table):
    if table is None:
        return None
    if isinstance(table, (bytes, bytearray)):
        return [bytes(table[8 * k:8 * k + 8]) for k in range(32)]
    return list(table)


def _id_of_stem(entries, st):
    want = st.rstrip(b'\0').lower()
    for k, e in enumerate(entries):
        if e[:1] != b'\0' and e.rstrip(b'\0').lower() == want:
            return k
    return None


def teams(d, table):
    """[(id, L, slot, stem8)] sorted by id. table None: id = engine id. Otherwise id = the lowest k whose entry
    matches the stem (ASCII case-insensitive, trailing NULs ignored); a team with no such k is left out. A team
    whose id an earlier team already took is left out."""
    d = raw(d)
    nd = ndiv(d)
    entries = _entries(table)
    out, taken = [], set()
    for L, slot, st in maj_teams(d):
        if entries is None:
            k = slot_to_engine(L, slot, nd)
            if k >= 32:
                continue                # a slot the division count does not use
        else:
            k = _id_of_stem(entries, st)
            if k is None:
                continue
        if k in taken:
            continue
        taken.add(k)
        out.append((k, L, slot, st))
    return sorted(out)


def id_of_slot(d, table, L, slot):
    for k, tl, ts, _st in teams(d, table):
        if (tl, ts) == (L, slot):
            return k
    return None


def slot_of_id(d, table, k):
    for tk, tl, ts, _st in teams(d, table):
        if tk == k:
            return (tl, ts)
    return None


def id_of_engine(d, table, e):
    """Stable id of the team at engine id e; 0xff for 0xff, e >= 32 or a slot with no listed team."""
    d = raw(d)
    if e == 0xff or e >= 32:
        return 0xff
    L, slot = engine_to_slot(e, ndiv(d))
    k = id_of_slot(d, table, L, slot)
    return 0xff if k is None else k


def stem_of_id(d, table, k):
    """The stem of stable id k with trailing NULs stripped; b'' when no team has id k."""
    for tk, _tl, _ts, st in teams(d, table):
        if tk == k:
            return st.rstrip(b'\0')
    return b''
