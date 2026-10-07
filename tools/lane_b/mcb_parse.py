#!/usr/bin/env python3
# Lane B: parse a DOSBox-X debugger MEMDUMPBIN dump of conventional memory (from seg 0x50, offset 0)
# and walk the MCB chain. Reports per-block table, total free, largest free block.
# Usage: mcb_parse.py DUMPFILE [--base 0x50] [--top 0xA000]
import struct, sys

def main():
    path = sys.argv[1]
    base = int(sys.argv[sys.argv.index("--base")+1], 0) if "--base" in sys.argv else 0x50
    top  = int(sys.argv[sys.argv.index("--top")+1], 0)  if "--top" in sys.argv else 0xA000
    data = open(path, "rb").read()
    def seg(i):  # segment -> offset in dump
        return (i - base) * 16
    # find the chain head: first 'M'/'Z' block whose links walk cleanly to an end
    head = None
    for s in range(base, 0x600):
        o = seg(s)
        if data[o] in (0x4D, 0x5A):
            owner, size = struct.unpack_from("<HH", data, o + 1)
            # try walking
            cur, ok = s, True
            for _ in range(400):
                co = seg(cur)
                t = data[co]
                if t not in (0x4D, 0x5A): ok = False; break
                _, sz = struct.unpack_from("<HH", data, co + 1)
                cur = cur + 1 + sz
                if t == 0x5A: break
                if cur >= top: ok = False; break
            else:
                ok = False
            if ok and t == 0x5A:
                head = s; break
    if head is None:
        print("no MCB chain head found"); return 1
    print(f"chain head at seg {head:#x}")
    total_free = 0; max_free = 0; rows = []
    cur = head
    while True:
        o = seg(cur)
        t = data[o]
        owner, size = struct.unpack_from("<HH", data, o + 1)
        name = data[o+8:o+16].split(b"\0")[0].decode("ascii", "replace").strip()
        rows.append((cur, t, owner, size, name))
        if owner == 0:
            total_free += size
            max_free = max(max_free, size)
        if t == 0x5A: break
        cur = cur + 1 + size
        if cur >= top: print("chain ran past top"); break
    for cur, t, owner, size, name in rows:
        kind = "DOS" if owner == 8 else ("free" if owner == 0 else f"psp {owner:#06x}")
        print(f"  {cur:#06x} {chr(t)} size={size:6d} para ({size*16:7d} B) owner={kind:9s} '{name}'")
    print(f"TOTAL conventional free: {total_free*16} B ({total_free*16/1024:.1f} KiB)")
    print(f"LARGEST free block:      {max_free*16} B ({max_free*16/1024:.1f} KiB) [{max_free:#x} para]")
    return 0

if __name__ == "__main__":
    sys.exit(main())
