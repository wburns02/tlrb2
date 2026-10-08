#!/usr/bin/env python3
"""Stadium panoramas (STADIUMS/<stem>.SDM, one DCL stream of a 1120 x 444 8-bit image, see notes/FORMATS.md).

usage:
  stadium.py unpack SDM OUT.raw            explode to raw palette indices
  stadium.py pack IN.raw OUT.SDM           implode raw indices back to an SDM
  stadium.py marker SDM OUT.SDM            re-encode with a solid test block in centre field (rig proof)
  stadium.py iso IN.iso OUT.iso FILE...    copy the CD image with STADIUMS/<name> (SDM, CFG) or
                                           ANMS/<name> (OVL) replaced or added
  stadium.py render SDM CFG OUT.png        panorama in its real colours

BB reads stadiums from the CD drive (SYSTEM byte 0x4b, auto_prepend_drive_to_path), never from C:, so new or
changed parks ship as a rebuilt CD image. Never writes under the live install or pristine.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dcl import explode, implode  # noqa: E402

W = 1120
PAL_OFF, PAL_LO, PAL_N = 51, 80, 96            # CFG bytes 51..338 = VGA DAC entries 80..175 (6-bit), proved on the rig
GUARD = ('/mnt/nvme/tlrb2/c/', '/mnt/nvme/tlrb2/pristine/', '/mnt/nvme/tlrb2/iso/')


def _out(path):
    a = os.path.abspath(path)
    for g in GUARD:
        if a.startswith(g):
            sys.exit('refusing to write under ' + g)
    return a


def unpack(sdm):
    d = open(sdm, 'rb').read()
    px, end = explode(d)
    if end != len(d):
        sys.exit('%s: stream ends at %d of %d' % (sdm, end, len(d)))
    return px


def marker(px, x0=500, y0=190, w=120, h=50, colour=0):
    px = bytearray(px)                          # default: a solid block on the centre-field grass
    for y in range(y0, y0 + h):
        px[y * W + x0:y * W + x0 + w] = bytes([colour]) * w
    return bytes(px)


def palette(cfg_bytes, base_pal=None):
    """768-entry 8-bit RGB list: DEFAULT.PAL for 0..79 and 176..255 (the panorama uses only 0..16 there),
    the stadium's own 96 colours from its CFG for 80..175."""
    from assets import SRC, load_pal
    pal = list(base_pal or load_pal(os.path.join(SRC, 'DEFAULT.PAL')))
    for k in range(PAL_N * 3):
        pal[PAL_LO * 3 + k] = min(255, (cfg_bytes[PAL_OFF + k] & 63) * 255 // 63)
    return pal


def render(px, pal):
    from PIL import Image
    im = Image.frombytes('P', (W, len(px) // W), bytes(px[:len(px) // W * W]))
    im.putpalette(pal)
    return im.convert('RGB')


def iso(src, dst, sdms):
    cmd = ['xorriso', '-indev', src, '-outdev', _out(dst), '-boot_image', 'any', 'keep']
    for s in sdms:                              # thumbnails (.OVL) live in ANMS, everything else in STADIUMS
        n = os.path.basename(s).upper()
        cmd += ['-map', os.path.abspath(s), ('/ANMS/' if n.endswith('.OVL') else '/STADIUMS/') + n]
    cmd += ['-commit']
    if os.path.exists(dst):
        os.remove(dst)
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['unpack'] and len(a) == 3:
        open(_out(a[2]), 'wb').write(unpack(a[1]))
    elif a[:1] == ['pack'] and len(a) == 3:
        open(_out(a[2]), 'wb').write(implode(open(a[1], 'rb').read()))
    elif a[:1] == ['marker'] and len(a) == 3:
        open(_out(a[2]), 'wb').write(implode(marker(unpack(a[1]))))
    elif a[:1] == ['render'] and len(a) == 4:
        render(unpack(a[1]), palette(open(a[2], 'rb').read())).save(_out(a[3]))
    elif a[:1] == ['iso'] and len(a) >= 4:
        iso(a[1], a[2], a[3:])
    else:
        sys.exit(__doc__)
