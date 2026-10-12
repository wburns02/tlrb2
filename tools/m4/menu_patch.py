#!/usr/bin/env python3
"""DYNASTY menu-bar patch for MAIN, BACK, MANAGE, UTIL and CONTROL.EXE (contract C10, amended 2026-10-11).

Adds a sixth entry, DYNASTY, to the menu bar (ball, SEASON, MANAGER, UTILITIES, DYNASTY, home plate) of every
program that has one, so every mod is reachable from the game's own menu wherever the player is. Its dropdown
holds DYNASTY MODE, CREATE A PLAYER, DYNASTY SETTINGS and ABOUT THE MODS. Picking item k makes the running
program leave through its normal shutdown path (BACK saves the day's results first, as for any program switch)
with CONTROL[1] = 8 + k; patched CONTROL.EXE exits with that errorlevel and TONY2.BAT runs `dynview /menu`
(8, 10, 11; DYNVIEW reads CONTROL[1] for the screen) or `create` (9), which put CONTROL[1] back to the caller
(CONTROL[0], which each program writes with its own id on exit) before returning. DRAFT has no menu bar.

The menu module is linked into MAIN, BACK, MANAGE and UTIL with identical contents; only its segments move, so
the patch is one list parameterized by the EXES table below. The notes that follow use MAIN's addresses.

Menu data (MAIN, verified 2026-10-08, notes/RE_NOTES.md "Menu bar"):
- menu data segment 1eba: dropdown structs of 22 words (count, enable mask, 16 string ids,
  4 runtime words) at 0x00 ball, 0x2c plate stats, 0x58 SEASON, 0x84 MANAGER, 0xb0
  UTILITIES; the bar struct at 0xdc is count, mask, then 5-word entries
  (submenu index, flags 0x8000 top level | 0x2000 right aligned, string id, x, width).
- DGROUP 0x2208: far pointers to the dropdowns by submenu index; DGROUP 0x221c: far pointers
  to the menu strings by string id. Index k of the first table is slot k-5 of the second.
- string ids 8, 0xd and 0x20 are in no MAIN menu; 0x2d (IMPORT ONLINE SERVICE STATS, a dead
  1993 online-service import) is dropped from MAIN's UTILITIES dropdown (count 10 -> 9). The
  table grows by two slots (0x2e, 0x2f) over the first 8 bytes of the string pool; PLAY BALL!
  moves out of the way and the new slots' segment words get two appended MZ relocations
  (the reloc table ends at 0x1706, the header at 0x1a00). Only the four menu routines read the
  table (`shl bx,2; push dword [bx+0x221c]`), and no code addresses a moved string directly.
- 1eba:0112..017f is zero in the file and in RAM at menu idle (cave scan, FORMATS.md); the new
  bar entry, dropdown, strings and trampoline code live there. Every pointer we repoint keeps
  its MZ relocation (the segment words already carry one), so only the file values change.
- The menu loop (overlay 4ec4, flat 4ec40) decodes the pick as bar = code >> 4, item = code
  & 15 and jumps through a 4-entry table for bars 1..4; anything else is ignored. The patch
  replaces its 14-byte decode with a far return into 1eba:0148 (cs = ds - 0x2240, the fixed
  DGROUP to 1eba distance), which redoes the decode and, for the DYNASTY bar, stores 8 + item
  in CONTROL[1]. The loop exits on CONTROL[1] != 1, so MAIN saves and quits as for any other
  program switch. BACK, MANAGE and UTIL decode the same way (their loops then test `ja` instead of `jbe`, which
  the returned flags of cmp bx,3 with bx = 4 satisfy) and exit on CONTROL[1] != 2, 4 and 5.
CONTROL.EXE (seg 1228): the 1..6 bounds check becomes 1..11 and the 6-way table jump becomes
`inc ax; jmp exit(ax)`, which is what every table handler did (errorlevel == state[1]).

usage: menu_patch.py INSTALL_DIR [--revert]   (INSTALL_DIR holds MAIN, BACK, MANAGE, UTIL and CONTROL.EXE)
Idempotent; checks every file is stock or patched before writing any; refuses the pristine tree.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patchlib import Ctx  # noqa: E402

DGROUP = 0x40fa
MENU_SEG = 0x1eba
LOOP_SEG = 0x4ec4          # overlay holding MAIN's menu loop

DYN_SUBMENU = 13           # submenu index 13 = string slot 8 (0x2208 + 13 * 4 == 0x223c)
ID_DYNASTY = 0x0d          # bar label
# dropdown items in order; the pick stores CONTROL[1] = 8 + item
ITEM_IDS = (0x20, 0x2d, 0x2e, 0x2f)
ITEMS = ('DYNASTY MODE', 'CREATE A PLAYER', 'DYNASTY SETTINGS', 'ABOUT THE MODS')
STATE_BASE = 8             # CONTROL[1] for item 0; CONTROL.EXE exits with that errorlevel

# 1eba cave layout
ENTRY_OFF = 0x112          # bar entry 5
SUB_OFF = 0x11c            # dropdown struct (44 B, runtime words at +0x24 stay zero)
STR_DYNASTY_OFF = 0x128    # inside the dropdown's unused string-id area (ids 4..15)
STR_MODE_OFF = 0x130
CODE_OFF = 0x148
CAVE_END = 0x180

# DGROUP string table (far pointers by id at 0x221c) grows from 0x2e to 0x30 entries over the
# first 8 bytes of the string pool, where PLAY BALL! lived; dead strings make room:
#   0x2378 PLAY TO RESERVED GAME (id 0xd, in no MAIN menu)  -> DYNASTY SETTINGS (id 0x2e)
#   0x2484 SIMULATED STATS (id 0x20, in no MAIN menu)        -> ABOUT THE MODS (id 0x2f)
#   0x253e IMPORT ONLINE SERVICE STATS (id 0x2d, dropped)    -> CREATE A PLAYER (id 0x2d) + PLAY BALL! (id 0)
STR_TABLE = 0x221c
POOL0 = 0x22d4             # old PLAY BALL!
NEW_SLOTS = (0x2e, 0x2f)
STR_SETTINGS_OFF = 0x2378
STR_ABOUT_OFF = 0x2484
STR_CREATE_OFF = 0x253e
STR_PLAYBALL_OFF = 0x254e

# MZ relocation table: two entries appended for the new slots' segment words
MZ_CRLC = 1458
MZ_RELOC_END = 0x1706      # lfarlc 0x3e + 1458 * 4; the header runs to 0x1a00

# The menu module (bar, dropdowns, string table and pool) is linked into MAIN, BACK, MANAGE and UTIL with
# identical contents (verified 2026-10-11, notes/RE_NOTES.md "Menu bar on every program"); only its segments move.
# Per EXE: DGROUP, the menu data segment, the 14-byte pick decode (seg, off), the string table offset in DGROUP,
# the CONTROL buffer far pointer in DGROUP and the MZ relocation count / table end. DRAFT has no menu bar.
EXES = {
    'MAIN.EXE': dict(dgroup=0x40fa, menu_seg=0x1eba, loop=(0x4ec4, 0x1d4), str_table=0x221c, control=0x9b64,
                     crlc=1458, reloc_end=0x1706),
    'BACK.EXE': dict(dgroup=0x2c71, menu_seg=0x2b2a, loop=(0x14e6, 0x34c), str_table=0x0d56, control=0x50de,
                     crlc=1001, reloc_end=0x0fe2),
    'MANAGE.EXE': dict(dgroup=0x28bf, menu_seg=0x281b, loop=(0x174a, 0x14e), str_table=0x0cdc, control=0x3b20,
                       crlc=1612, reloc_end=0x196e),
    'UTIL.EXE': dict(dgroup=0x3954, menu_seg=0x21d8, loop=(0x1bad, 0x0ea), str_table=0x2b86, control=0x9628,
                     crlc=1651, reloc_end=0x1a0a),
}
# string pool offsets relative to the string table (the same in every EXE)
REL_POOL0 = POOL0 - STR_TABLE
REL_SLOT8 = 0x233d - STR_TABLE
REL_SETTINGS = STR_SETTINGS_OFF - STR_TABLE
REL_ABOUT = STR_ABOUT_OFF - STR_TABLE
REL_CREATE = STR_CREATE_OFF - STR_TABLE
REL_PLAYBALL = STR_PLAYBALL_OFF - STR_TABLE

LE = lambda v: bytes((v & 0xff, v >> 8))  # noqa: E731
FP = lambda off, seg: LE(off) + LE(seg - 0x1000)  # noqa: E731  far pointer, file (pre-relocation) value


def trampoline(exe='MAIN.EXE'):
    """menu seg:0148: redo the decode, flag the DYNASTY bar, return with flags of cmp bx,3. The caller's next
    instruction (MAIN jbe, the others ja) sends bx = 4 to the loop's exit test."""
    ctl = EXES[exe]['control']
    return bytes.fromhex(
        '8bd6'        # mov dx,si
        'c1ea04'      # shr dx,4
        '83e60f'      # and si,0xf
        '8bda'        # mov bx,dx
        '4b'          # dec bx
        '83fa05'      # cmp dx,5          bar position 5
        '7405'        # je .dyn
        '83fa0d'      # cmp dx,13         or the submenu index, whichever the menu returns
        '750e'        # jne .out
        'c41e' + LE(ctl).hex() +  # .dyn: les bx,[CONTROL]   CONTROL buffer far pointer
        '8d4408'      # lea ax,[si+8]
        '26884701'    # mov [es:bx+1],al
        'bb0400'      # mov bx,4          not a table bar: the loop skips to its exit test
        '83fb03'      # .out: cmp bx,3
        'cb')         # retf


def hook(exe='MAIN.EXE'):
    """At the decode (MAIN overlay 4ec4:01d4), 14 bytes: far call menu seg:0148 by pushing cs:<decode + 14>, then
    menu seg = ds - (DGROUP - menu seg), and retf."""
    c = EXES[exe]
    return (b'\x0e' + b'\x68' + LE(c['loop'][1] + 14) + b'\x8c\xd8' + b'\x2d' + LE(c['dgroup'] - c['menu_seg'])
            + b'\x50' + b'\x68' + LE(CODE_OFF) + b'\xcb')


STOCK_HOOK = bytes.fromhex('8bd6c1ea0483e60f8bda4b83fb03')


def cstr(s, size):
    b = s.encode('ascii') + b'\0'
    assert len(b) <= size, (s, size)
    return b.ljust(size, b'\0')


def main_patches(exe='MAIN.EXE'):
    """[(seg, off, old, new)] in Ghidra flat addressing for one menu EXE (MAIN, BACK, MANAGE or UTIL)."""
    c = EXES[exe]
    dg, ms, tbl = c['dgroup'], c['menu_seg'], c['str_table']
    assert len(ITEM_IDS) == len(ITEMS) <= 16 and 4 + 2 * len(ITEM_IDS) <= STR_DYNASTY_OFF - SUB_OFF
    sub = bytearray(0x2c)
    sub[0:4] = LE(len(ITEM_IDS)) + LE(0xffff)
    for k, sid in enumerate(ITEM_IDS):
        sub[4 + 2 * k:6 + 2 * k] = LE(sid)
    for o, s in ((STR_DYNASTY_OFF, 'DYNASTY'), (STR_MODE_OFF, ITEMS[0])):
        b = s.encode('ascii') + b'\0'
        sub[o - SUB_OFF:o - SUB_OFF + len(b)] = b
    assert all(b == 0 for b in sub[0x24:])     # runtime words stay clear
    entry = LE(DYN_SUBMENU) + LE(0x8000) + LE(ID_DYNASTY) + LE(0) + LE(0)
    code = trampoline(exe)
    assert ENTRY_OFF + len(entry) == SUB_OFF and SUB_OFF + len(sub) == CODE_OFF
    assert CODE_OFF + len(code) <= CAVE_END
    cave_new = bytes(entry) + bytes(sub) + code
    slot = lambda sid: tbl + 4 * sid  # noqa: E731
    pool0, settings, about = tbl + REL_POOL0, tbl + REL_SETTINGS, tbl + REL_ABOUT
    create, playball = tbl + REL_CREATE, tbl + REL_PLAYBALL
    new_slots = FP(settings, dg) + FP(about, dg)
    assert slot(NEW_SLOTS[0]) == pool0 and slot(NEW_SLOTS[-1]) + 4 <= pool0 + 11
    return [
        (ms, 0xdc, LE(5), LE(6)),                             # bar count
        (ms, 0xb0, LE(10), LE(9)),                            # UTILITIES drops id 0x2d
        (ms, ENTRY_OFF, bytes(len(cave_new)), cave_new),
        (dg, slot(0), FP(pool0, dg), FP(playball, dg)),
        (dg, slot(8), FP(tbl + REL_SLOT8, dg), FP(SUB_OFF, ms)),
        (dg, slot(ID_DYNASTY), FP(settings, dg), FP(STR_DYNASTY_OFF, ms)),
        (dg, slot(0x20), FP(about, dg), FP(STR_MODE_OFF, ms)),
        (dg, pool0, cstr('PLAY BALL!', 11), new_slots + bytes(3)),
        (dg, settings, cstr('PLAY TO RESERVED GAME', 22), cstr(ITEMS[2], 22)),
        (dg, about, cstr('SIMULATED STATS', 16), cstr(ITEMS[3], 16)),
        (dg, create, cstr('IMPORT ONLINE SERVICE STATS', 28),
         cstr(ITEMS[1], playball - create) + cstr('PLAY BALL!', 12)),
        (c['loop'][0], c['loop'][1], STOCK_HOOK, hook(exe)),
    ]


def main_header_patches(exe='MAIN.EXE'):
    """[(file_off, old, new)]: the MZ relocation count and the appended entries."""
    c = EXES[exe]
    relocs = b''.join(LE(c['str_table'] + 4 * sid + 2) + LE(c['dgroup'] - 0x1000) for sid in NEW_SLOTS)
    return [(6, LE(c['crlc']), LE(c['crlc'] + len(NEW_SLOTS))),
            (c['reloc_end'], bytes(len(relocs)), relocs)]


CONTROL_SEG = 0x1228


def control_patches():
    return [(CONTROL_SEG, 0xcd, bytes.fromhex('83fb05772cd1e32effa72701'),
             bytes.fromhex('83fb0a772c40eb0790909090'))]


def _resolve(exe, patches, header=()):
    """-> [(file_off, old, new)]; segment words of repointed far pointers are MZ-relocated,
    which is fine: the file holds the pre-relocation value we compare and write."""
    ctx = Ctx(exe)
    out = []
    for seg, off, old, new in patches:
        fo = ctx.flat_to_file(seg, off)
        assert fo is not None, (hex(seg), hex(off))
        if len(old) == len(STOCK_HOOK) and old == STOCK_HOOK:
            assert not any(ctx.fixup_at(seg, off + i) for i in range(len(old))), 'fixup in hook'
        out.append((fo, old, new))
    return out + list(header)


def patch_file(exe, patches, revert=False, header=(), check_only=False):
    """Returns 'patched', 'already' or 'reverted'/'stock'. check_only: validate the bytes, write nothing."""
    res = _resolve(exe, patches, header)
    d = bytearray(open(exe, 'rb').read())
    cur = [bytes(d[fo:fo + len(o)]) for fo, o, n in res]
    if all(c == n for c, (fo, o, n) in zip(cur, res)):
        state = 'patched'
    elif all(c == o for c, (fo, o, n) in zip(cur, res)):
        state = 'stock'
    else:
        bad = [hex(fo) for c, (fo, o, n) in zip(cur, res) if c not in (o, n)]
        raise SystemExit(f'{exe}: unexpected bytes at {bad}; not a stock or patched file')
    want = 'stock' if revert else 'patched'
    if check_only:
        return state
    if state == want:
        return 'already' if not revert else 'stock'
    for fo, o, n in res:
        d[fo:fo + len(o)] = o if revert else n
    open(exe, 'wb').write(bytes(d))
    return 'reverted' if revert else 'patched'


def find_exe(root, name):
    for f in os.listdir(root):
        if f.upper() == name:
            return os.path.join(root, f)
    raise SystemExit(f'{name} not found in {root}')


def patch(install, revert=False):
    """Patch (or revert) MAIN, BACK, MANAGE, UTIL and CONTROL in install; -> {name: state}."""
    root = os.path.abspath(install)
    if 'pristine' in root.split(os.sep):
        raise SystemExit('refusing to patch the pristine tree')
    jobs = [(name, main_patches(name), main_header_patches(name)) for name in EXES]
    jobs.append(('CONTROL.EXE', control_patches(), ()))
    for name, pats, hdr in jobs:            # every file is stock or patched before any is written
        patch_file(find_exe(root, name), pats, revert, hdr, check_only=True)
    return {name: patch_file(find_exe(root, name), pats, revert, hdr) for name, pats, hdr in jobs}


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('--')]
    if len(args) != 1:
        raise SystemExit(__doc__)
    for name, state in patch(args[0], '--revert' in argv).items():
        print(name, state)


if __name__ == '__main__':
    main(sys.argv)
