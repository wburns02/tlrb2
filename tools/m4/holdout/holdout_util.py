"""Synthetic fixtures for the holdout suite. Nothing here reads or copies game data: every
file is built from bytes in tmp_path."""
import random

from v20 import HDR, REC, SIZE
import maj as maj_mod

MAJ_SIZE = maj_mod.SIZE
S_AL, S_NL = 0x21d, 0x758c
O_NAMES, O_ABBR, O_STEM = 0x0f, 0x18f, 0x1d7


def v20_bytes(seed=1):
    """A reproducible junk team image of exactly SIZE bytes."""
    return random.Random(seed).randbytes(SIZE)


def blank_team(name=b'TESTERS'):
    d = bytearray(SIZE)
    d[0:14] = name.ljust(14, b'\0')[:14]
    d[111:237] = b'\xff' * 126
    return d


def put_player(img, i, last, first, age, pos1, games=0, ratings=None):
    """Active player in record i of team image img (bytearray) with raw field pokes
    (offsets from notes/FORMATS.md, not through the v20 field table)."""
    o = HDR + REC * i
    rec = bytearray(REC)
    rec[0:len(last)] = last.encode('ascii')
    rec[12:12 + len(first)] = first.encode('ascii')
    rec[0x14] = age
    rec[0x15] = 120
    rec[0x17] = games
    rec[0x1f] = pos1
    for off, v in (ratings or {}).items():
        rec[off] = v
    img[o:o + REC] = rec


def make_maj(teams_al, teams_nl, ndiv=2, junk=None):
    """Synthetic 59771 B MAJ. teams_L = [(slot, abbr, stem)]; names are 'NAME-<abbr>'.
    junk=<seed> fills every other byte with reproducible random bytes (so a stray write shows up),
    with the first stem byte of every unused slot forced to NUL (no team there)."""
    if junk is None:
        d = bytearray(MAJ_SIZE)
    else:
        d = bytearray(random.Random(junk).randbytes(MAJ_SIZE))
        for s in (S_AL, S_NL):
            for slot in range(24):
                d[s + O_STEM + 8 * slot] = 0
    d[0x20c], d[0x20d] = 2, ndiv
    for s, teams in ((S_AL, teams_al), (S_NL, teams_nl)):
        for slot, abbr, stem in teams:
            nm = ('NAME-' + abbr).encode('ascii').ljust(16, b'\0')
            d[s + O_NAMES + 16 * slot:s + O_NAMES + 16 * slot + 16] = nm
            a = abbr.encode('ascii').ljust(3, b'\0')
            d[s + O_ABBR + 3 * slot:s + O_ABBR + 3 * slot + 3] = a
            d[s + O_STEM + 8 * slot:s + O_STEM + 8 * slot + 8] = stem.encode('ascii').ljust(8, b'\0')
    return bytes(d)
