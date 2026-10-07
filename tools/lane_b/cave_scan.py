#!/usr/bin/env python3
# Lane B: code-cave scan over the flattened TLRB2 images.
# A cave is a run of >= MIN bytes of one filler byte (00/90/ff) inside the RESIDENT load image
# (the flat prefix before the first overlay segment). Overlay-segment padding is excluded: at
# runtime overlays load into a shared buffer segment-by-segment, so tail bytes there are not safe.
# Usage: cave_scan.py [MIN]   (default 64)   -> table to stdout
import json, sys

BASE = 0x1000
DGROUP = {'MAIN': 0x40fa, 'BB': 0x5120, 'UTIL': 0x3954, 'DRAFT': 0x1f31,
          'BACK': 0x2c71, 'MANAGE': 0x28bf, 'PLAY': 0x170a, 'CONTROL': 0x123e}
MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 64

for prog in ['MAIN', 'BB', 'UTIL', 'DRAFT', 'BACK', 'MANAGE', 'PLAY', 'CONTROL']:
    m = json.load(open(f'/mnt/nvme/tlrb2/flat/{prog}.map.json'))
    data = open(f'/mnt/nvme/tlrb2/flat/{prog}.flat.bin', 'rb').read()
    stubs = {int(o['stub_seg'], 16) for o in m['overlays']}
    first_ovl = min((int(o['ovl_seg'], 16) for o in m['overlays']), default=0)
    resident_end = (first_ovl - BASE) * 16 if first_ovl else len(data)
    dg = DGROUP[prog]
    runs = []
    i = 0
    while i < resident_end:
        b = data[i]
        if b in (0x00, 0x90):
            j = i
            while j < resident_end and data[j] == b:
                j += 1
            if j - i >= MIN:
                runs.append((i, j - i, b))
            i = j
        else:
            i += 1
    print(f"== {prog}: resident image {resident_end} B ({resident_end//16} para), "
          f"{len(m['overlays'])} overlays (first ovl seg {first_ovl:#x}), runs>={MIN}: {len(runs)}")
    for off, ln, b in runs:
        seg = BASE + off // 16
        o = off % 16
        kind = 'DGROUP' if seg == dg else ('stub' if seg in stubs else 'code')
        print(f"   {seg:04x}:{o:04x} len {ln:6d} ({ln:6d} B) fill {b:02x} [{kind}]")
