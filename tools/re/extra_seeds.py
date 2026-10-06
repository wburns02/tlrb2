#!/usr/bin/env python3
"""Add every call target found inside known functions to the seed list (Ghidra missed many far-call targets).

usage: extra_seeds.py NAME...   reads flat/NAME.seeds.txt + index/NAME/_functions.tsv, adds the new targets to
       flat/NAME.seeds.extra.txt (cumulative; scripts/ghidra_build.sh appends it to the make_seeds.py list). Targets: `call far seg:off` (linear, so segment aliasing
       does not matter), and near `call rel16`. A target is kept only if it lies in code (not DGROUP or past the
       image) and is not a stub thunk (those are already seeded through their overlay target).
Seeds are written as seg:off in the containing segment from map.json 'segments', like make_seeds.py does.
"""
import sys, os, re, json, bisect, shutil
sys.path.insert(0, os.path.dirname(__file__))
import kb

def main(n):
    T = kb.T
    m = json.load(open(f'{T}/flat/{n}.map.json'))
    P = kb.prog(n)
    ex_txt = f'{T}/flat/{n}.seeds.extra.txt'
    extra = set(open(ex_txt).read().split()) if os.path.exists(ex_txt) else set()
    seeds = set(open(f'{T}/flat/{n}.seeds.txt').read().split()) | extra
    S = sorted(int(s, 16) for s in m['segments'])
    stubs = set()
    for o in m['overlays']:
        for e in o['entries']:
            stubs.add(P.lin(e['stub']))
    starts = {P.lin(a) for a in P.fn}
    known = {P.lin(s) for s in seeds} | starts
    new = set()
    for a, f in P.fn.items():
        seg = int(a.split(':')[0], 16)
        for ad, hx, ins in P.disasm(f):
            mt = re.match(r'call (0x[0-9a-f]+):(0x[0-9a-f]+)$', ins)
            if mt:
                lin = (int(mt.group(1), 16) - 0x1000) * 16 + int(mt.group(2), 16)
            else:
                mt = re.match(r'call (0x[0-9a-f]+)$', ins)
                if not mt or not hx.upper().startswith('E8'):
                    continue
                lin = (seg - 0x1000) * 16 + int(mt.group(1), 16)
            if lin in known or lin in stubs or lin < 0 or lin >= len(P.flat):
                continue
            if P.dsbase <= lin < m['image_bytes']:
                continue
            new.add(lin)
    out = set(extra)
    for lin in new:
        a = 0x10000 + lin  # 0x1000 paragraphs = base
        s = S[bisect.bisect_right(S, a // 16) - 1]
        if a - s * 16 < 0x10000:
            out.add(f'{s:04x}:{a - s * 16:04x}')
    open(ex_txt, 'w').write('\n'.join(sorted(out)) + '\n')
    print(n, 'seeds', len(seeds), 'new call targets', len(new), 'extra total', len(out))

if __name__ == '__main__':
    for n in sys.argv[1:]:
        main(n)
