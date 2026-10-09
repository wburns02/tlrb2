"""menu_patch (C10): the DYNASTY menu-bar patch for MAIN.EXE and CONTROL.EXE.

Layout tests run anywhere; the byte tests copy MAIN.EXE and CONTROL.EXE from the pristine
install and skip when /mnt/nvme/tlrb2/pristine/TONY2 is missing.
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


def test_hook_replaces_stock_decode_exactly():
    assert len(mp.hook()) == len(mp.STOCK_HOOK) == 14
    # push cs; push 0x01e2 (back into the loop after the 14 bytes); ax = ds - (DGROUP - 1eba); push ax;
    # push CODE_OFF; retf
    h = mp.hook()
    assert h[:4] == b'\x0e\x68\xe2\x01' and h[-1:] == b'\xcb'
    assert struct.unpack_from('<H', h, 7)[0] == mp.DGROUP - mp.MENU_SEG
    assert struct.unpack_from('<H', h, 11)[0] == mp.CODE_OFF


def test_cave_layout_fits():
    pats = mp.main_patches()
    cave = [p for p in pats if p[0] == mp.MENU_SEG and p[1] == mp.ENTRY_OFF][0]
    assert mp.ENTRY_OFF + len(cave[3]) <= mp.CAVE_END
    assert cave[2] == bytes(len(cave[3]))      # the cave was zero
    sub = cave[3][mp.SUB_OFF - mp.ENTRY_OFF:mp.CODE_OFF - mp.ENTRY_OFF]
    assert struct.unpack_from('<HH', sub, 0) == (4, 0xffff)
    assert struct.unpack_from('<4H', sub, 4) == mp.ITEM_IDS
    assert sub[0x24:] == bytes(8)              # runtime words


def test_strings_fit_their_holes():
    for seg, off, old, new in mp.main_patches():
        assert len(old) == len(new), (hex(seg), hex(off))
    texts = b''.join(n for _s, _o, _old, n in mp.main_patches())
    for item in mp.ITEMS + ('DYNASTY', 'PLAY BALL!'):
        assert item.encode('ascii') + b'\0' in texts


def test_control_patch_bounds_and_exit():
    (seg, off, old, new), = mp.control_patches()
    assert new[:3] == bytes.fromhex('83fb0a')  # cmp bx,10: states 1..11 after the dec
    assert len(old) == len(new)


def _copy(tmp_path):
    d = tmp_path / 'TONY2'
    d.mkdir()
    for n in ('MAIN.EXE', 'CONTROL.EXE'):
        shutil.copyfile(os.path.join(PRISTINE, n), d / n)   # pristine files are read-only
    return d


@needs_game
def test_patch_already_revert_roundtrip(tmp_path):
    d = _copy(tmp_path)
    stock = {n: (d / n).read_bytes() for n in ('MAIN.EXE', 'CONTROL.EXE')}
    assert mp.patch(str(d)) == {'MAIN.EXE': 'patched', 'CONTROL.EXE': 'patched'}
    patched = {n: (d / n).read_bytes() for n in stock}
    assert all(patched[n] != stock[n] and len(patched[n]) == len(stock[n]) for n in stock)
    assert mp.patch(str(d)) == {'MAIN.EXE': 'already', 'CONTROL.EXE': 'already'}
    assert {n: (d / n).read_bytes() for n in stock} == patched
    assert mp.patch(str(d), revert=True) == {'MAIN.EXE': 'reverted', 'CONTROL.EXE': 'reverted'}
    assert {n: (d / n).read_bytes() for n in stock} == stock
    assert not [f for f in os.listdir(d) if f.endswith('.bak')]


@needs_game
def test_patched_main_header_and_bytes(tmp_path):
    d = _copy(tmp_path)
    mp.patch(str(d))
    b = (d / 'MAIN.EXE').read_bytes()
    assert struct.unpack_from('<H', b, 6)[0] == mp.MZ_CRLC + 2
    lfarlc = struct.unpack_from('<H', b, 0x18)[0]
    assert lfarlc + 4 * (mp.MZ_CRLC + 2) <= struct.unpack_from('<H', b, 8)[0] * 16
    tail = b[mp.MZ_RELOC_END:mp.MZ_RELOC_END + 8]
    assert tail == struct.pack('<4H', mp.STR_TABLE + 4 * 0x2e + 2, mp.DGROUP - 0x1000,
                               mp.STR_TABLE + 4 * 0x2f + 2, mp.DGROUP - 0x1000)
    ctx = Ctx(str(d / 'MAIN.EXE'))
    fo = ctx.flat_to_file(mp.LOOP_SEG, 0x1d4)
    assert b[fo:fo + 14] == mp.hook()
    # every changed byte is one the patch list names
    s = open(os.path.join(PRISTINE, 'MAIN.EXE'), 'rb').read()
    named = set()
    for fo, old, new in mp._resolve(str(d / 'MAIN.EXE'), mp.main_patches(), mp.main_header_patches()):
        named.update(range(fo, fo + len(old)))
    assert {i for i in range(len(s)) if s[i] != b[i]} <= named


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
