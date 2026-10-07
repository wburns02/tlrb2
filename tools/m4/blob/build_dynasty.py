#!/usr/bin/env python3
"""Wrap nasm's dynasty.img (the bare load image) in a 32-byte MZ header.

Layout (all one segment, org 0): code+data, blob (para aligned), 512 B stack.
CS=IP=0 at entry; SS=0, SP = top of the reserved stack.
"""
import struct
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, 'dynasty.img')
EXE = os.path.join(HERE, 'DYNASTY.EXE')
STACK = 512


def main():
    subprocess.run(['nasm', '-f', 'bin', '-o', IMG, os.path.join(HERE, 'dynasty.asm')],
                   check=True, cwd=HERE)
    image = open(IMG, 'rb').read()
    sp = len(image)                       # top of stack == image end
    size = len(image)
    hdr = struct.pack('<16H',
                      0x5A4D,             # e_magic 'MZ'
                      size % 512,         # e_cblp
                      (size + 511) // 512,  # e_cp
                      0,                  # e_crlc
                      2,                  # e_cparhdr (32-byte header)
                      0,                  # e_minalloc
                      0xFFFF,             # e_maxalloc
                      0,                  # e_ss (same segment)
                      sp,                 # e_sp
                      0,                  # e_csum
                      0,                  # e_ip
                      0,                  # e_cs
                      0x1E,               # e_lfarlc
                      0, 0, 0)            # e_ovno + reserved -> 32 bytes
    assert len(hdr) == 32, len(hdr)
    open(EXE, 'wb').write(hdr + image)
    print(f'{EXE}: {32 + size} bytes (image {size}, sp {sp:#x})')


if __name__ == '__main__':
    sys.exit(main())
