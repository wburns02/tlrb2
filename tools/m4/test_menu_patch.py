"""menu_patch (C10 menu bar, C12.2 DIV3): the DYNASTY menu-bar patch for MAIN, BACK, MANAGE, UTIL and CONTROL.EXE,
and the DIV3 byte edits in MAIN and UTIL.

Layout tests and the synthetic-file DIV3 tests run anywhere; the byte tests copy the five EXEs from the pristine
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
MENU_EXES = sorted(mp.EXES)
ALL_EXES = MENU_EXES + ['CONTROL.EXE']
DIV3_JOBS = [f'{name} div3' for name in mp.DIV3_SITES]
MOUSE_JOBS = [f'{name} mouse' for name in mp.MOUSE_SITES]
PLAYOFF_JOBS = [f'{name} playoffs' for name in mp.PLAYOFF_SITES]
MOUSE_ONLY = ['BB.EXE', 'DRAFT.EXE']             # carry a MOUSE job and nothing else


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


@pytest.mark.parametrize('exe,site,stock,patched', [
    ('MAIN.EXE', 0, '26 80 bf 0d 02 03 74 03 e9 e5 00 26 c6 87 0d 02 02',
     '26 80 bf 0d 02 03 90 90 e9 e5 00 26 c6 87 0d 02 02'),
    ('UTIL.EXE', 0, '80 3e 02 a1 03 75 12 c4 1e 26 b5 26 c6 87 0d 02 02',
     '80 3e 02 a1 03 eb 12 c4 1e 26 b5 26 c6 87 0d 02 02'),
    ('UTIL.EXE', 1, '80 3e 02 a1 03 74 03 e9 9b 00 c4 1e 26 b5 26 c6 87 0d 02 02',
     '80 3e 02 a1 03 90 90 e9 9b 00 c4 1e 26 b5 26 c6 87 0d 02 02'),
])
def test_div3_site_patterns_and_bytes(exe, site, stock, patched):
    pat, off, new = mp.DIV3_SITES[exe][site]
    assert pat.hex(' ') == stock
    assert mp._patched_pattern(pat, off, new).hex(' ') == patched


def test_div3_sites_change_exactly_their_bytes():
    assert mp.DIV3_SITES['MAIN.EXE'][0][1] == 6                  # the 74 03 at +6..+7
    assert [off for pat, off, new in mp.DIV3_SITES['UTIL.EXE']] == [5, 5]
    for sites in mp.DIV3_SITES.values():
        for pat, off, new in sites:
            p2 = mp._patched_pattern(pat, off, new)
            assert len(p2) == len(pat)
            assert {i for i in range(len(pat)) if pat[i] != p2[i]} == set(range(off, off + len(new)))


def _body(*pats):
    """A fake EXE: each stock pattern between filler, no other copy of it."""
    return b''.join(b'\x11' * 32 + p for p in pats) + b'\x11' * 32


def _util_pats():
    return [pat for pat, _off, _new in mp.DIV3_SITES['UTIL.EXE']]


def test_div3_roundtrip_on_a_fake_file(tmp_path):
    p = tmp_path / 'UTIL.EXE'
    p.write_bytes(_body(*_util_pats()))
    before = p.read_bytes()
    assert mp.div3_patch(str(p), 'UTIL.EXE') == 'patched'
    after = p.read_bytes()
    assert len(after) == len(before) and after != before
    assert mp.div3_patch(str(p), 'UTIL.EXE') == 'already'
    assert mp.div3_patch(str(p), 'UTIL.EXE', revert=True) == 'reverted'
    assert p.read_bytes() == before
    assert mp.div3_patch(str(p), 'UTIL.EXE', revert=True) == 'stock'


def test_div3_check_only_writes_nothing(tmp_path):
    p = tmp_path / 'UTIL.EXE'
    p.write_bytes(_body(*_util_pats()))
    before = p.read_bytes()
    assert mp.div3_patch(str(p), 'UTIL.EXE', check_only=True) == 'stock'
    assert p.read_bytes() == before


def test_div3_corrupt_site_refuses_and_writes_nothing(tmp_path):
    pats = _util_pats()
    body = bytearray(_body(*pats))
    body[body.find(pats[1]) + 5] ^= 0xff                        # the second site's 74 is not stock or patched
    p = tmp_path / 'UTIL.EXE'
    p.write_bytes(bytes(body))
    with pytest.raises(SystemExit, match='UTIL.EXE'):
        mp.div3_patch(str(p), 'UTIL.EXE')
    assert p.read_bytes() == bytes(body)


def test_div3_mixed_sites_refused_and_nothing_written(tmp_path):
    pats = _util_pats()
    body = bytearray(_body(*pats))
    body[body.find(pats[0]) + 5] = 0xeb                         # site 1 patched by hand, site 2 stock
    p = tmp_path / 'UTIL.EXE'
    p.write_bytes(bytes(body))
    with pytest.raises(SystemExit):
        mp.div3_patch(str(p), 'UTIL.EXE')
    assert p.read_bytes() == bytes(body)


def test_div3_pattern_must_occur_exactly_once(tmp_path):
    pat = mp.DIV3_SITES['MAIN.EXE'][0][0]
    p = tmp_path / 'MAIN.EXE'
    p.write_bytes(_body(pat, pat))
    with pytest.raises(SystemExit, match='MAIN.EXE.*occurs 2 times'):
        mp.div3_patch(str(p), 'MAIN.EXE', check_only=True)
    p.write_bytes(_body())
    with pytest.raises(SystemExit, match='MAIN.EXE'):
        mp.div3_patch(str(p), 'MAIN.EXE', check_only=True)


def _copy(tmp_path):
    d = tmp_path / 'TONY2'
    d.mkdir()
    for n in ALL_EXES + MOUSE_ONLY:
        shutil.copyfile(os.path.join(PRISTINE, n), d / n)   # pristine files are read-only
    return d


@needs_game
def test_patch_already_revert_roundtrip(tmp_path):
    d = _copy(tmp_path)
    stock = {n: (d / n).read_bytes() for n in ALL_EXES}
    assert mp.patch(str(d)) == dict.fromkeys(ALL_EXES + DIV3_JOBS + MOUSE_JOBS + PLAYOFF_JOBS, 'patched')
    patched = {n: (d / n).read_bytes() for n in stock}
    assert all(patched[n] != stock[n] and len(patched[n]) == len(stock[n]) for n in stock)
    assert mp.patch(str(d)) == dict.fromkeys(ALL_EXES + DIV3_JOBS + MOUSE_JOBS + PLAYOFF_JOBS, 'already')
    assert {n: (d / n).read_bytes() for n in stock} == patched
    assert mp.patch(str(d), revert=True) == dict.fromkeys(ALL_EXES + DIV3_JOBS + MOUSE_JOBS + PLAYOFF_JOBS, 'reverted')
    assert {n: (d / n).read_bytes() for n in stock} == stock
    assert not [f for f in os.listdir(d) if f.endswith('.bak')]


@needs_game
def test_c10_only_install_upgrades_in_place(tmp_path):
    d = _copy(tmp_path)
    stock = {n: (d / n).read_bytes() for n in ALL_EXES}
    mp.patch(str(d))
    full = {n: (d / n).read_bytes() for n in ALL_EXES}
    for table in (mp.DIV3_SITES, mp.MOUSE_SITES, mp.PLAYOFF_SITES):   # back to a C10-only install: stock bytes at the job sites
        for name in table:
            p = d / name
            b = bytearray(p.read_bytes())
            for fo, old, new in mp.div3_sites(str(p), name, table):
                b[fo:fo + len(old)] = old
            p.write_bytes(bytes(b))
    assert mp.patch(str(d)) == {**dict.fromkeys(ALL_EXES, 'already'), **dict.fromkeys(DIV3_JOBS + MOUSE_JOBS + PLAYOFF_JOBS, 'patched')}
    assert {n: (d / n).read_bytes() for n in ALL_EXES} == full
    assert mp.patch(str(d), revert=True) == dict.fromkeys(ALL_EXES + DIV3_JOBS + MOUSE_JOBS + PLAYOFF_JOBS, 'reverted')
    assert {n: (d / n).read_bytes() for n in ALL_EXES} == stock


@needs_game
def test_corrupt_div3_site_refuses_and_writes_nothing(tmp_path):
    d = _copy(tmp_path)
    p = d / 'UTIL.EXE'
    fo, _old, _new = mp.div3_sites(str(p), 'UTIL.EXE')[1]
    b = bytearray(p.read_bytes())
    b[fo] ^= 0xff
    p.write_bytes(bytes(b))
    before = {n: (d / n).read_bytes() for n in ALL_EXES}
    with pytest.raises(SystemExit):
        mp.patch(str(d))
    assert {n: (d / n).read_bytes() for n in ALL_EXES} == before


@needs_game
def test_mixed_div3_sites_refused_and_nothing_written(tmp_path):
    d = _copy(tmp_path)
    p = d / 'UTIL.EXE'
    fo, _old, new = mp.div3_sites(str(p), 'UTIL.EXE')[0]
    b = bytearray(p.read_bytes())
    b[fo:fo + len(new)] = new
    p.write_bytes(bytes(b))
    before = {n: (d / n).read_bytes() for n in ALL_EXES}
    with pytest.raises(SystemExit):
        mp.patch(str(d))
    assert {n: (d / n).read_bytes() for n in ALL_EXES} == before


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
    if exe in mp.DIV3_SITES:
        for fo, old, new in mp.div3_sites(str(d / exe), exe):
            named.update(range(fo, fo + len(old)))
    if exe in mp.MOUSE_SITES:
        for fo, old, new in mp.div3_sites(str(d / exe), exe, mp.MOUSE_SITES):
            named.update(range(fo, fo + len(old)))
    if exe in mp.PLAYOFF_SITES:
        for fo, old, new in mp.div3_sites(str(d / exe), exe, mp.PLAYOFF_SITES):
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


def test_mouse_sites_change_exactly_the_range_maxima():
    assert sorted(mp.MOUSE_SITES) == ['BACK.EXE', 'BB.EXE', 'DRAFT.EXE', 'MAIN.EXE', 'MANAGE.EXE', 'UTIL.EXE']
    for sites in mp.MOUSE_SITES.values():
        (pat, off, new), = sites
        assert pat.hex(' ') == '66 68 30 01 c3 00 66 6a 00 9a'
        assert mp._patched_pattern(pat, off, new).hex(' ') == '66 68 3f 01 c7 00 66 6a 00 9a'   # 319, 199


def test_mouse_roundtrip_on_a_fake_file(tmp_path):
    p = tmp_path / 'BB.EXE'
    p.write_bytes(_body(mp.MOUSE_PAT))
    before = p.read_bytes()
    assert mp.mouse_patch(str(p), 'BB.EXE') == 'patched'
    assert p.read_bytes() == before.replace(bytes.fromhex('30 01 c3 00'), bytes.fromhex('3f 01 c7 00'))
    assert mp.mouse_patch(str(p), 'BB.EXE') == 'already'
    assert mp.mouse_patch(str(p), 'BB.EXE', revert=True) == 'reverted'
    assert p.read_bytes() == before


def test_mouse_twice_refuses(tmp_path):
    p = tmp_path / 'BB.EXE'
    p.write_bytes(_body(mp.MOUSE_PAT, mp.MOUSE_PAT))
    with pytest.raises(SystemExit):
        mp.mouse_patch(str(p), 'BB.EXE', check_only=True)


@needs_game
@pytest.mark.parametrize('exe', sorted(mp.MOUSE_SITES))
def test_mouse_site_once_in_each_pristine_exe(exe):
    data = open(os.path.join(PRISTINE, exe), 'rb').read()
    assert data.count(mp.MOUSE_PAT) == 1


# ---------------------------------------------------------------- PLAYOFFS (C23)
def test_playoff_patch_keeps_every_fixup_word():
    old, new = mp.PLAYOFF_OLD, mp.PLAYOFF_NEW
    assert len(old) == len(new) == 0x3bf - mp.PLAYOFF_BASE
    for f in mp.PLAYOFF_FIXUPS:
        o = f - mp.PLAYOFF_BASE
        assert new[o:o + 2] == old[o:o + 2]


@needs_game
def test_playoff_function_once_in_pristine_back_at_the_overlay():
    data = open(os.path.join(PRISTINE, 'BACK.EXE'), 'rb').read()
    assert data.count(mp.PLAYOFF_OLD) == 1 and data.count(mp.PLAYOFF_NEW) == 0
    assert data.find(mp.PLAYOFF_OLD) == 176598


def test_playoff_roundtrip_on_a_fake_file(tmp_path):
    p = tmp_path / 'BACK.EXE'
    p.write_bytes(_body(mp.PLAYOFF_OLD))
    before = p.read_bytes()
    assert mp.playoff_patch(str(p), 'BACK.EXE') == 'patched'
    assert p.read_bytes() == before.replace(mp.PLAYOFF_OLD, mp.PLAYOFF_NEW)
    assert mp.playoff_patch(str(p), 'BACK.EXE') == 'already'
    assert mp.playoff_patch(str(p), 'BACK.EXE', revert=True) == 'reverted'
    assert p.read_bytes() == before


# Emulation of the whole function (unicorn): code at CS:0x2b6, DS strings at their offsets, the far calls
# (seg word 0 in the file: strcpy 45f5, strcat 45b6, fopen 3637, fclose 31fd, remove 1782; 170:25 the
# existence check) stubbed in Python, INT 21h 56h / 41h over a dict of file names.
CS, DS, SS, STUB = 0x2000, 0x3000, 0x4000, 0x0000
DIR = b'CLASSIC'


def _run_fn(code, files, name=DIR):
    uc_mod = pytest.importorskip('unicorn')
    from unicorn import x86_const as X
    uc = uc_mod.Uc(uc_mod.UC_ARCH_X86, uc_mod.UC_MODE_16)
    uc.mem_map(0, 0x100000)
    uc.mem_write(CS * 16 + 0x2b6, code)
    for off, sv in ((0x21f3, b'teams\\\0'), (0x21fa, b'\\playoffs.al\0'), (0x2207, b'rb\0'),
                    (0x220a, b'teams\\\0'), (0x2211, b'\\playoffs.nl\0'), (0x221e, b'rb\0')):
        uc.mem_write(DS * 16 + off, sv)
    uc.mem_write(DS * 16 + 0x6000, name.ljust(8, b'\0')[:8] + b'XYZ')   # 8-char dir, then junk
    uc.mem_write(DS * 16 + 0x50ea, struct.pack('<HH', 0x6000, DS))
    stubs = {0x45f5: 'strcpy', 0x45b6: 'strcat', 0x3637: 'fopen', 0x31fd: 'fclose', 0x1782: 'remove'}
    log = []

    def cstr(seg, off):
        b = bytes(uc.mem_read(seg * 16 + off, 64))
        return b[:b.index(0)]

    def retf():
        sp = uc.reg_read(X.UC_X86_REG_SP)
        ip, cs = struct.unpack('<HH', uc.mem_read(SS * 16 + sp, 4))
        uc.reg_write(X.UC_X86_REG_SP, sp + 4)
        uc.reg_write(X.UC_X86_REG_CS, cs)
        uc.reg_write(X.UC_X86_REG_IP, ip)

    def hook_code(uc, addr, size, _):
        if addr // 16 < 0x1000 and addr < 0x10000:
            sp = uc.reg_read(X.UC_X86_REG_SP)
            a = struct.unpack('<4H', uc.mem_read(SS * 16 + sp + 4, 8))
            what = stubs.get(addr - STUB * 16, 'check' if addr == 0x170 * 16 + 0x25 else None)
            if what in ('strcpy', 'strcat'):
                dst = (a[1], a[0])
                src = cstr(a[3], a[2])
                cur = b'' if what == 'strcpy' else cstr(*dst)
                uc.mem_write(dst[0] * 16 + dst[1], cur + src + b'\0')
            elif what == 'fopen':
                path = cstr(a[1], a[0]).lower()
                uc.reg_write(X.UC_X86_REG_AX, 0x99 if path in files else 0)
                uc.reg_write(X.UC_X86_REG_DX, 0x1 if path in files else 0)
            elif what in ('fclose', 'check'):
                pass
            elif what == 'remove':
                raise AssertionError('remove reached')
            log.append(what)
            retf()

    def hook_int(uc, intno, _):
        assert intno == 0x21
        ah = uc.reg_read(X.UC_X86_REG_AH)
        src = cstr(uc.reg_read(X.UC_X86_REG_DS), uc.reg_read(X.UC_X86_REG_DX)).lower()
        fl = uc.reg_read(X.UC_X86_REG_EFLAGS) & ~1
        if ah == 0x56:
            dst = cstr(uc.reg_read(X.UC_X86_REG_ES), uc.reg_read(X.UC_X86_REG_DI)).lower()
            ok = src in files and dst not in files
            if ok:
                files[dst] = files.pop(src)
            log.append(('ren', src, dst, ok))
        else:
            assert ah == 0x41
            ok = src in files
            files.pop(src, None)
            log.append(('del', src, ok))
        # the INT pushed FLAGS: set CF in the copy IRET restores
        uc.reg_write(X.UC_X86_REG_EFLAGS, fl | (0 if ok else 1))
    uc.hook_add(uc_mod.UC_HOOK_CODE, hook_code, begin=0, end=0xffff)
    uc.hook_add(uc_mod.UC_HOOK_INTR, hook_int)
    # caller: far call into the function, then hlt
    caller = CS * 16 + 0x100
    uc.mem_write(caller, bytes.fromhex('9a b6 02 00 20 f4'))     # call far 2000:02b6; hlt
    uc.mem_write(0x170 * 16 + 0x25, b'\xcb')
    for r, v in ((X.UC_X86_REG_CS, CS), (X.UC_X86_REG_DS, DS), (X.UC_X86_REG_SS, SS), (X.UC_X86_REG_ES, 0),
                 (X.UC_X86_REG_SP, 0xfff0), (X.UC_X86_REG_BP, 0x1234), (X.UC_X86_REG_SI, 0x5151),
                 (X.UC_X86_REG_DI, 0x7171)):
        uc.reg_write(r, v)
    uc.emu_start(caller, caller + 5, count=20000)
    regs = {k: uc.reg_read(getattr(X, 'UC_X86_REG_' + k)) for k in ('SP', 'BP', 'SI', 'DI', 'DS', 'SS')}
    return log, regs


def _pre(*exts):
    return {b'teams\\classic\\playoffs.' + e: e for e in exts}


def test_playoff_emulated_archives_both_files_and_keeps_registers():
    files = _pre(b'al', b'nl')
    log, regs = _run_fn(mp.PLAYOFF_NEW, files)
    assert files == {b'teams\\classic\\playoffs.a1': b'al', b'teams\\classic\\playoffs.n1': b'nl'}
    assert regs == {'SP': 0xfff0, 'BP': 0x1234, 'SI': 0x5151, 'DI': 0x7171, 'DS': DS, 'SS': SS}
    assert log[-1] == 'check' and log.count('fopen') == 2 and 'remove' not in log


def test_playoff_emulated_takes_the_first_free_suffix_and_deletes_when_full():
    files = _pre(b'al', b'a1', b'a3', b'nl', b'n1', b'n2', b'n3', b'n4')
    _run_fn(mp.PLAYOFF_NEW, files)
    assert sorted(files) == sorted(_pre(b'a1', b'a2', b'a3', b'n1', b'n2', b'n3', b'n4'))
    assert files[b'teams\\classic\\playoffs.a2'] == b'al'


def test_playoff_emulated_missing_files_and_short_dir_name():
    files = {}
    log, _ = _run_fn(mp.PLAYOFF_NEW, files, name=b'AB')
    assert files == {} and not [e for e in log if isinstance(e, tuple)]
    files = {b'teams\\ab\\playoffs.nl': 1}
    _run_fn(mp.PLAYOFF_NEW, files, name=b'AB')
    assert files == {b'teams\\ab\\playoffs.n1': 1}


def test_playoff_emulated_stock_function_removes():
    with pytest.raises(AssertionError, match='remove reached'):
        _run_fn(mp.PLAYOFF_OLD, _pre(b'al'))
