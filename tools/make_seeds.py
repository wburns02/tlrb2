#!/usr/bin/env python3
"""Function seed list for a flattened EXE (see vroomm_flatten.py). usage: make_seeds.py FLATDIR NAME EXE
Segments = MZ reloc targets + overlay segments + entry CS. Seeds = entry, every overlay thunk target,
and every `push bp; mov bp,sp` prologue, each expressed in its containing segment (so near calls resolve).
Writes NAME.seeds.txt and adds 'segments' to NAME.map.json."""
import json, re, struct, bisect, sys
fd, n, exe = sys.argv[1:4]
m = json.load(open(f'{fd}/{n}.map.json')); f = open(f'{fd}/{n}.flat.bin', 'rb').read(); d = open(exe, 'rb').read()
base = int(m['base'], 16)
crlc, = struct.unpack('<H', d[6:8]); rlo, = struct.unpack('<H', d[0x18:0x1a])
segs = {base, int(m['entry'].split(':')[0], 16)} | {int(o['ovl_seg'], 16) for o in m['overlays']}
for i in range(crlc):
    off, seg = struct.unpack('<2H', d[rlo + 4 * i:rlo + 4 * i + 4]); v = struct.unpack('<H', f[seg * 16 + off:seg * 16 + off + 2])[0]
    if base <= v < base + len(f) // 16: segs.add(v)
S = sorted(segs); seeds = {m['entry']} | {e['target'] for o in m['overlays'] for e in o['entries']}
for x in re.finditer(rb'\x55\x8b\xec', f):
    lin = base * 16 + x.start(); s = S[bisect.bisect_right(S, lin // 16) - 1]
    if lin - s * 16 < 0x10000: seeds.add(f'{s:04x}:{lin - s * 16:04x}')
open(f'{fd}/{n}.seeds.txt', 'w').write('\n'.join(sorted(seeds)))
m['segments'] = [f'{s:04x}' for s in S]; json.dump(m, open(f'{fd}/{n}.map.json', 'w'), indent=1)
print(n, 'segments', len(S), 'seeds', len(seeds))
