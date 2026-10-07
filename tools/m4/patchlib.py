#!/usr/bin/env python3
"""DOS EXE patch library for TLRB2 M4 (dynasty mod).

Inverse of tools/vroomm_flatten.py: maps a flat-image address (the Ghidra view,
BASE:0000, default BASE 0x1000) back to a byte offset in the real VROOMM EXE file,
so patches found in Ghidra can be applied to the shipped binaries.

Real-file layout (verified 2026-10-06, see vroomm_flatten.py docstring):
  [MZ header: hdrpar*16 B][load image][FBOV u32 ovl_size u32 segtbl_off i32 nseg]
  [overlay data: ovl_size B][segment table]
Overlay code stored in the file is byte-identical to what the overlay manager
loads (fixups are applied in memory only), so any byte that is NOT an overlay
fixup word can be patched directly in the file. Stub thunks live in the load
image; same rule.

API:
  Ctx(exe)                    parse once
    .flat_to_file(seg, off)   Ghidra flat addr -> file offset, or None
    .fixup_at(seg, off)       True if the addr is an overlay relocation word
    .find_caves(min_len)      [(seg, off, len)] filler runs inside overlay code
  apply(exe, patches, tag)    patches = [(file_off, old, new)]; asserts old bytes,
                              writes .<TAG>.bak once, refuses to double-patch
  revert(exe, tag)            restore from .<TAG>.bak

CLI self-test: patchlib.py EXE FLATBIN  -> round-trips sample addresses through
flat_to_file and diffs the bytes against the flattener output.
"""
import struct, sys, os, shutil

BASE = 0x1000  # flattener default


class Ctx:
    def __init__(self, exe):
        self.exe = exe
        d = open(exe, 'rb').read()
        self.d = d
        assert d[:2] == b'MZ', 'not an MZ exe'
        cblp, cp, crlc, hdrpar = struct.unpack('<4H', d[2:10])
        self.hdr = hdrpar * 16
        img_end = (cp - 1) * 512 + (cblp or 512)
        self.img = d[self.hdr:img_end]
        self.img_end = img_end
        rlo = struct.unpack('<H', d[0x18:0x1a])[0]
        self.mz_relocs = {seg * 16 + off for off, seg in
                          (struct.unpack('<2H', d[rlo + 4 * i:rlo + 4 * i + 4]) for i in range(crlc))}
        self.img_pad = (len(self.img) + 15) // 16 * 16
        self.overlays = []      # dicts: ovl_seg (flat, BASE-relative), fileoff, codesize, fixups, stub_off
        if d[img_end:img_end + 4] == b'FBOV':
            ovl_size, segtbl, nseg = struct.unpack('<IIi', d[img_end + 4:img_end + 16])
            ovl_data = d[img_end + 16:img_end + 16 + ovl_size]
            self.ovl_data_start = img_end + 16
            self.ovl_size = ovl_size
            for p in range(0, len(self.img) - 0x20, 16):
                if self.img[p:p + 2] != b'\xcd\x3f' or self.img[p + 2:p + 4] != b'\0\0':
                    continue
                fileoff, codesize, relocsize, nent = struct.unpack('<IHHH', self.img[p + 4:p + 14])
                ents = self.img[p + 0x20:p + 0x20 + 5 * nent]
                if not nent or fileoff + codesize + relocsize > len(ovl_data) or relocsize % 2 \
                   or any(ents[5 * k:5 * k + 2] != b'\xcd\x3f' for k in range(nent)):
                    continue
                fixes = [struct.unpack('<H', ovl_data[fileoff + codesize + 2 * k:
                                                 fileoff + codesize + 2 * k + 2])[0]
                         for k in range(relocsize // 2)]
                self.overlays.append({'ovl_seg': None, 'fileoff': fileoff, 'codesize': codesize,
                                      'stub_off': p, 'nent': nent, 'fixups': fixes})
            seg = self.img_pad // 16
            for o in self.overlays:
                o['ovl_seg'] = BASE + seg
                seg += (o['codesize'] + 15) // 16

    def overlay_by_seg(self, seg):
        for o in self.overlays:
            if o['ovl_seg'] == seg:
                return o
        return None

    def in_load_image(self, seg, off):
        return 0 <= (seg - BASE) * 16 + off < len(self.img)

    def fixup_at(self, seg, off):
        """True if the flat address is a relocation word (MZ reloc in the load image or an
        overlay fixup): its file bytes are a selector, not the runtime value; never patch
        or byte-compare those."""
        if self.in_load_image(seg, off):
            return (seg - BASE) * 16 + off in self.mz_relocs
        o = self.overlay_by_seg(seg)
        return bool(o) and off in o['fixups']

    def flat_to_file(self, seg, off):
        """Ghidra flat paragraph:offset -> byte offset in the EXE file, or None."""
        if self.in_load_image(seg, off):
            return self.hdr + (seg - BASE) * 16 + off
        o = self.overlay_by_seg(seg)
        if o and 0 <= off < o['codesize']:
            return self.ovl_data_start + o['fileoff'] + off
        return None

    def find_caves(self, min_len=64):
        """Runs of 00 inside overlay code regions, clear of fixup words.
        Returns [(seg, off, len)] sorted by len desc."""
        out = []
        for o in self.overlays:
            fo = self.ovl_data_start + o['fileoff']
            code = self.d[fo:fo + o['codesize']]
            i = 0
            while i < len(code):
                if code[i] == 0:
                    j = i
                    while j < len(code) and code[j] == 0:
                        j += 1
                    if j - i >= min_len and not any(i <= fx < j for fx in o['fixups']):
                        out.append((o['ovl_seg'], i, j - i))
                    i = j
                else:
                    i += 1
        out.sort(key=lambda t: -t[2])
        return out


def apply(exe, patches, tag='m4'):
    """patches: [(file_off, old_bytes, new_bytes)]. Asserts current==old for every entry
    before writing anything; refuses if a .<tag>.bak already exists (double patch)."""
    bak = f'{exe}.{tag}.bak'
    assert not os.path.exists(bak), f'{bak} already exists; revert before re-patching'
    d = open(exe, 'rb').read()
    for fo, old, new in patches:
        assert len(old) == len(new), (hex(fo), 'len mismatch')
        assert d[fo:fo + len(old)] == old, f'at {hex(fo)}: expected {old.hex()} got {d[fo:fo+len(old)].hex()}'
    shutil.copy2(exe, bak)
    d = bytearray(d)
    for fo, old, new in patches:
        d[fo:fo + len(new)] = new
    open(exe, 'wb').write(bytes(d))
    return bak


def revert(exe, tag='m4'):
    bak = f'{exe}.{tag}.bak'
    assert os.path.exists(bak), f'no {bak}'
    shutil.copy2(bak, exe)


def selftest(exe, flatbin):
    c = Ctx(exe)
    flat = open(flatbin, 'rb').read()
    name = os.path.splitext(os.path.basename(exe))[0]
    n_ok = n_bad = 0
    checks = [(BASE, 0, 64), (BASE, len(c.img) - 32, 32)]
    for o in c.overlays[::4]:
        checks.append((o['ovl_seg'], 0, min(32, o['codesize'])))
        if o['codesize'] > 64:
            checks.append((o['ovl_seg'], o['codesize'] - 32, 32))
    first_ovl_flat = BASE + c.img_pad // 16
    for seg, off, n in checks:
        fo = c.flat_to_file(seg, off)
        got = c.d[fo:fo + n] if fo is not None else None
        if seg == BASE:
            want = flat[off:off + n]
        else:
            want = flat[c.img_pad + (seg - first_ovl_flat) * 16 + off:][:n]
        # mask relocation words: file holds selectors/segment-relative values there
        diffs = [i for i in range(n) if got[i] != want[i]
                 and not c.fixup_at(seg, off + i) and not c.fixup_at(seg, off + i - 1)]
        if not diffs:
            n_ok += 1
        else:
            n_bad += 1
            print(f'MISMATCH seg={seg:04x} off={off:04x} at {diffs[:8]} file={got.hex()[:32]} '
                  f'flat={want.hex()[:32]}')
    caves = c.find_caves(64)
    print(f'{name}: {len(c.overlays)} overlays, map-ok {n_ok}/{n_ok + n_bad}, '
          f'caves>=64B: {len(caves)} top {[(hex(s), hex(o), l) for s, o, l in caves[:3]]}')
    return n_bad == 0


if __name__ == '__main__':
    ok = selftest(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
