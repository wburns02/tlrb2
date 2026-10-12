"""menu_patch (C10): the DYNASTY menu-bar patch for MAIN, BACK, MANAGE, UTIL and CONTROL.EXE.

Layout tests run anywhere; the byte tests copy the five EXEs from the pristine install and skip
when /mnt/nvme/tlrb2/pristine/TONY2 is missing.
"""
import os
import shutil
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import menu_patch as mp  # noqa: E402
from patchlib import Ctx  # noqa: E402

PRISTINE = '/mnt/nvme/tlrb2/pristine/TONY2'
needs_game = pytest.mark.skipif(not os.path.isfile(os.path.join(PRISTINE, 'MAIN.EXE')),
                                reason='pristine install missing')
MENU_EXES = sorted(mp.EXES)
ALL_EXES = MENU_EXES + ['CONTROL.EXE']


def test_hook_replaces_stock_decode_exactly():
    assert len(mp.hook()) == len(mp.STOCK_HOOK) == 14
    # push cs; push 0x01e2 (back into the loop after the 14 bytes); ax = ds - (DGROUP - 1eba); push ax;
    # push CODE_OFF; retf
    h = mp.hook()
    assert h[:4] == b'\x0e\x68\xe2\x01' and h[-1:] == b'\xcb'
    assert struct.unpack_from('<H', h, 7)[0] == mp.DGROUP - mp.MENU_SEG
    assert struct.unpack_from('<H', h, 11)[0] == mp.CODE_OFF


@pytest.mark.parametrize('exe', MENU_EXES)
def test_hook_per_exe(exe):
    c = mp.EXES[exe]
    h = mp.hook(exe)
    assert len(h) == 14 and h[:2] == b'\x0e\x68' and h[-1:] == b'\xcb'
    assert struct.unpack_from('<H', h, 2)[0] == c['loop'][1] + 14
    assert struct.unpack_from('<H', h, 7)[0] == c['dgroup'] - c['menu_seg']
    assert struct.unpack_from('<H', h, 11)[0] == mp.CODE_OFF


@pytest.mark.parametrize('exe', MENU_EXES)
def test_trampoline_uses_this_exes_control_pointer(exe):
    t = mp.trampoline(exe)
    assert t.count(b'\xc4\x1e' + struct.pack('<H', mp.EXES[exe]['control'])) == 1
    assert mp.CODE_OFF + len(t) <= mp.CAVE_END


def test_main_table_matches_main_constants():
    c = mp.EXES['MAIN.EXE']
    assert (c['dgroup'], c['menu_seg'], c['loop'][0], c['str_table']) == (
        mp.DGROUP, mp.MENU_SEG, mp.LOOP_SEG, mp.STR_TABLE)
    assert (c['crlc'], c['reloc_end']) == (mp.MZ_CRLC, mp.MZ_RELOC_END)


@pytest.mark.parametrize('exe', MENU_EXES)
def test_cave_layout_fits(exe):
    pats = mp.main_patches(exe)
    ms = mp.EXES[exe]['menu_seg']
    cave = [p for p in pats if p[0] == ms and p[1] == mp.ENTRY_OFF][0]
    assert mp.ENTRY_OFF + len(cave[3]) <= mp.CAVE_END
    assert cave[2] == bytes(len(cave[3]))      # the cave was zero
    sub = cave[3][mp.SUB_OFF - mp.ENTRY_OFF:mp.CODE_OFF - mp.ENTRY_OFF]
    assert struct.unpack_from('<HH', sub, 0) == (4, 0xffff)
    assert struct.unpack_from('<4H', sub, 4) == mp.ITEM_IDS
    assert sub[0x24:] == bytes(8)              # runtime words


@pytest.mark.parametrize('exe', MENU_EXES)
def test_strings_fit_their_holes(exe):
    for seg, off, old, new in mp.main_patches(exe):
        assert len(old) == len(new), (hex(seg), hex(off))
    texts = b''.join(n for _s, _o, _old, n in mp.main_patches(exe))
    for item in mp.ITEMS + ('DYNASTY', 'PLAY BALL!'):
        assert item.encode('ascii') + b'\0' in texts


def test_control_patch_bounds_and_exit():
    (seg, off, old, new), = mp.control_patches()
    assert new[:3] == bytes.fromhex('83fb0a')  # cmp bx,10: states 1..11 after the dec
    assert len(old) == len(new)


def _copy(tmp_path):
    d = tmp_path / 'TONY2'
    d.mkdir()
    for n in ALL_EXES:
        shutil.copyfile(os.path.join(PRISTINE, n), d / n)   # pristine files are read-only
    return d


@needs_game
def test_patch_already_revert_roundtrip(tmp_path):
    d = _copy(tmp_path)
    stock = {n: (d / n).read_bytes() for n in ALL_EXES}
    assert mp.patch(str(d)) == dict.fromkeys(ALL_EXES, 'patched')
    patched = {n: (d / n).read_bytes() for n in stock}
    assert all(patched[n] != stock[n] and len(patched[n]) == len(stock[n]) for n in stock)
    assert mp.patch(str(d)) == dict.fromkeys(ALL_EXES, 'already')
    assert {n: (d / n).read_bytes() for n in stock} == patched
    assert mp.patch(str(d), revert=True) == dict.fromkeys(ALL_EXES, 'reverted')
    assert {n: (d / n).read_bytes() for n in stock} == stock
    assert not [f for f in os.listdir(d) if f.endswith('.bak')]


@needs_game
@pytest.mark.parametrize('exe', MENU_EXES)
def test_patched_header_and_bytes(tmp_path, exe):
    d = _copy(tmp_path)
    mp.patch(str(d))
    c = mp.EXES[exe]
    b = (d / exe).read_bytes()
    assert struct.unpack_from('<H', b, 6)[0] == c['crlc'] + 2
    lfarlc = struct.unpack_from('<H', b, 0x18)[0]
    assert lfarlc + 4 * c['crlc'] == c['reloc_end']
    assert lfarlc + 4 * (c['crlc'] + 2) <= struct.unpack_from('<H', b, 8)[0] * 16
    tail = b[c['reloc_end']:c['reloc_end'] + 8]
    assert tail == struct.pack('<4H', c['str_table'] + 4 * 0x2e + 2, c['dgroup'] - 0x1000,
                               c['str_table'] + 4 * 0x2f + 2, c['dgroup'] - 0x1000)
    ctx = Ctx(str(d / exe))
    fo = ctx.flat_to_file(*c['loop'])
    assert b[fo:fo + 14] == mp.hook(exe)
    # every changed byte is one the patch list names
    s = open(os.path.join(PRISTINE, exe), 'rb').read()
    assert len(s) == len(b)
    named = set()
    for fo, old, new in mp._resolve(str(d / exe), mp.main_patches(exe), mp.main_header_patches(exe)):
        named.update(range(fo, fo + len(old)))
    assert {i for i in range(len(s)) if s[i] != b[i]} <= named


@needs_game
def test_one_bad_file_writes_nothing(tmp_path):
    d = _copy(tmp_path)
    p = d / 'UTIL.EXE'
    (fo, old, new) = mp._resolve(str(p), mp.main_patches('UTIL.EXE'))[0]
    b = bytearray(p.read_bytes())
    b[fo] ^= 0xff
    p.write_bytes(bytes(b))
    before = {n: (d / n).read_bytes() for n in ALL_EXES}
    with pytest.raises(SystemExit):
        mp.patch(str(d))
    assert {n: (d / n).read_bytes() for n in ALL_EXES} == before


@needs_game
def test_unexpected_bytes_refused(tmp_path):
    d = _copy(tmp_path)
    p = d / 'CONTROL.EXE'
    (fo, old, new), = mp._resolve(str(p), mp.control_patches())
    b = bytearray(p.read_bytes())
    b[fo] ^= 0xff
    p.write_bytes(bytes(b))
    with pytest.raises(SystemExit):
        mp.patch(str(d))


def test_refuses_pristine_path(tmp_path):
    d = tmp_path / 'pristine' / 'TONY2'
    d.mkdir(parents=True)
    with pytest.raises(SystemExit):
        mp.patch(str(d))
