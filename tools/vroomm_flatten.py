#!/usr/bin/env python3
"""Flatten a Borland C++ 3.x VROOMM overlaid DOS EXE into one real-mode image for Ghidra.

usage: vroomm_flatten.py EXE OUTDIR [--base 0x1000]

Output (OUTDIR/<name>.flat.bin + <name>.map.json):
  load image at BASE:0000 with MZ relocations applied, then every overlay segment appended
  at a new paragraph with its own fixups applied. Each 5-byte stub thunk `CD 3F off16 00`
  is rewritten to `EA off16 seg16` (far jmp to the overlay's new home), so calls through
  stubs resolve statically. Load in Ghidra as Raw Binary, language x86:LE:16:Real Mode,
  base address BASE:0000. The map gives stub seg -> overlay seg, sizes, and the entry point.

Format notes (verified on MAIN.EXE / BB.EXE, 2026-10-06):
  after the MZ load image: 'FBOV' u32 ovl_size u32 segtbl_off i32 nseg, overlay data follows.
  stub segment header (0x20 B, paragraph aligned): CD 3F, u16 0, u32 fileoff (from ovl data
  start), u16 codesize, u16 relocsize, u16 nentries, ...; then nentries x (CD 3F off16 00).
  overlay fixups: relocsize/2 u16 offsets right after the code. Each fixed-up word is a SELECTOR, not a segment:
  index*8 into the FBOV segment table (nseg x 8 B at file offset segtbl: u16 load-relative seg, u16 maxoff,
  u16 flags, u16 minoff). The overlay manager replaces it with that entry's segment (+ load segment); calls to
  another overlay land on its stub segment. Fixed 2026-10-06: the first version added BASE to the selector, which
  only happened to be right for selector 0 (seg 0, the main RTL code segment).
"""
import sys, struct, json, os

def main():
    exe, out = sys.argv[1], sys.argv[2]
    base = int(sys.argv[sys.argv.index('--base') + 1], 0) if '--base' in sys.argv else 0x1000
    d = open(exe, 'rb').read()
    assert d[:2] == b'MZ', 'not an MZ exe'
    cblp, cp, crlc, hdrpar = struct.unpack('<4H', d[2:10])
    ip, cs = struct.unpack('<2H', d[0x14:0x18])
    rlo = struct.unpack('<H', d[0x18:0x1a])[0]
    img_end = (cp - 1) * 512 + (cblp or 512)
    hdr = hdrpar * 16
    img = bytearray(d[hdr:img_end])
    for i in range(crlc):
        off, seg = struct.unpack('<2H', d[rlo + 4 * i:rlo + 4 * i + 4])
        p = seg * 16 + off
        struct.pack_into('<H', img, p, (struct.unpack('<H', img[p:p + 2])[0] + base) & 0xffff)
    ovl = {'overlays': []}
    if d[img_end:img_end + 4] == b'FBOV':
        ovl_size, segtbl, nseg = struct.unpack('<IIi', d[img_end + 4:img_end + 16])
        ovl_data = d[img_end + 16:img_end + 16 + ovl_size]
        segtab = [struct.unpack('<H', d[segtbl + 8 * i:segtbl + 8 * i + 2])[0] for i in range(nseg)]
        nfix = nsel = 0
        flat = bytearray(img)
        flat += b'\0' * (-len(flat) % 16)
        for p in range(0, len(img) - 0x20, 16):
            if img[p:p + 2] != b'\xcd\x3f' or img[p + 2:p + 4] != b'\0\0':
                continue
            fileoff, codesize, relocsize, nent = struct.unpack('<IHHH', img[p + 4:p + 14])
            ents = img[p + 0x20:p + 0x20 + 5 * nent]
            if not nent or fileoff + codesize + relocsize > len(ovl_data) or relocsize % 2 \
               or any(ents[5 * k:5 * k + 2] != b'\xcd\x3f' for k in range(nent)):
                continue
            code = bytearray(ovl_data[fileoff:fileoff + codesize])
            newseg = base + len(flat) // 16
            for k in range(relocsize // 2):
                r = struct.unpack('<H', ovl_data[fileoff + codesize + 2 * k:fileoff + codesize + 2 * k + 2])[0]
                assert r + 2 <= codesize, (hex(p), hex(r))
                sel = struct.unpack('<H', code[r:r + 2])[0]
                assert sel % 8 == 0 and sel // 8 < nseg, ('fixup is not a selector', hex(p), hex(r), hex(sel))
                struct.pack_into('<H', code, r, (segtab[sel // 8] + base) & 0xffff)
                nfix += 1; nsel += sel != 0
            entries = []
            for k in range(nent):
                e = p + 0x20 + 5 * k
                eoff = struct.unpack('<H', img[e + 2:e + 4])[0]
                flat[e:e + 5] = b'\xea' + struct.pack('<HH', eoff, newseg)
                entries.append({'stub': f'{base + p // 16:04x}:{0x20 + 5 * k:04x}', 'target': f'{newseg:04x}:{eoff:04x}'})
            ovl['overlays'].append({'stub_seg': f'{base + p // 16:04x}', 'ovl_seg': f'{newseg:04x}',
                                    'fileoff': fileoff, 'codesize': codesize, 'fixups': relocsize // 2,
                                    'entries': entries})
            flat += code + b'\0' * (-len(code) % 16)
        ovl.update(fbov_nseg=nseg, fbov_size=ovl_size, fbov_segtbl=segtbl, overlay_fixups=nfix, nonzero_selectors=nsel)
    else:
        flat = img
    os.makedirs(out, exist_ok=True)
    name = os.path.splitext(os.path.basename(exe))[0]
    open(f'{out}/{name}.flat.bin', 'wb').write(flat)
    ovl.update(exe=exe, base=f'{base:04x}', entry=f'{cs + base:04x}:{ip:04x}', image_bytes=len(img),
               flat_bytes=len(flat), mz_relocs=crlc)
    json.dump(ovl, open(f'{out}/{name}.map.json', 'w'), indent=1)
    n = len(ovl['overlays'])
    pro = sum(1 for o in ovl['overlays'] if o['entries'])
    print(f"{name}: image {len(img)} B, {n} overlays, {sum(len(o['entries']) for o in ovl['overlays'])} thunks, "
          f"flat {len(flat)} B, entry {ovl['entry']}")

if __name__ == '__main__':
    main()
