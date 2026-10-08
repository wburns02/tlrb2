#!/usr/bin/env python3
"""Stadium panoramas (STADIUMS/<stem>.SDM, one DCL stream of a 1120 x 444 8-bit image, see notes/FORMATS.md).

usage:
  stadium.py unpack SDM OUT.raw            explode to raw palette indices
  stadium.py pack IN.raw OUT.SDM           implode raw indices back to an SDM
  stadium.py marker SDM OUT.SDM            re-encode with a solid test block in centre field (rig proof)
  stadium.py iso IN.iso OUT.iso FILE...    copy the CD image with STADIUMS/<name> (SDM, CFG) or
                                           ANMS/<name> (OVL) replaced or added
  stadium.py render SDM CFG OUT.png        panorama in its real colours
  stadium.py info CFG...                   decoded header (name, surface, fences, conditions, notes id, zones, heights)
  stadium.py fences CFG                    zone distances (feet), fence height range, obstacle list
  stadium.py refence CFG OUT.CFG LF LCF CF RCF RF [H | H1 H2 H3 H4 H5]
                                           new fence rows for the zone distances (feet), fence heights (default 8)

BB reads stadiums from the CD drive (SYSTEM byte 0x4b, auto_prepend_drive_to_path), never from C:, so new or
changed parks ship as a rebuilt CD image. Never writes under the live install or pristine.
"""
import math
import os
import struct
import subprocess
import sys
from functools import lru_cache

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


SURFACE = {0: 'turf', 1: 'grass', 2: 'classic'}   # 0 = every 1992 turf park incl. domes, 2 = the historic parks
EDGE_N, FENCE_EDGE, WALL_EDGE = 70, 0x153, 0x26b   # 70 x (u16 y, u16 column) per edge, column k = panorama x 16k..16k+15
OBST_EDGE, OBST_END = FENCE_EDGE + 4 * 140, FENCE_EDGE + 4 * 200   # entries 140..199: obstacle pairs
FENCE_TOP, DUGOUT = 0x475, 0x501               # u16 fence top row per column; 4 x int16 dugout points
ZONE_ANGLES = (-45.0, -22.5, 0.0, 22.5, 45.0)  # LF, LCF, CF, RCF, RF in degrees (negative is left field)


def tdiv(a, b):
    """C integer division: truncates toward zero."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _row(depth):
    if depth < 1:
        return 299 - depth
    if depth < 0x3d:
        return tdiv((0x13b - depth) * 0x13, 0x14)
    if depth < 0x80:
        return tdiv((0x1a4 - depth) * 0x2d, 0x43)
    if depth < 0xea:
        return tdiv((0x19d - depth) * 0x18, 0x23)
    if depth < 0x19b:
        return tdiv((0x254 - depth) * 0x14, 0x3b)
    return tdiv(0x41a - depth, 10)


def field_row(depth):
    """panorama row of a point depth feet from home plate (game function 2000:4823)."""
    return _row(depth) + 100


def field_x(lateral):
    """panorama x of a point lateral feet from the centre line."""
    if lateral < -0x7f:
        return tdiv(lateral * 0x43, 0x23) + 0x1c9
    if lateral < -0x3c:
        return tdiv(lateral * 0x96, 0x43) + 0x1f0
    if lateral < 0x3d:
        return tdiv(lateral * 199, 0x3c) + 0x230
    if lateral < 0x80:
        return tdiv(lateral * 0x96, 0x43) + 0x270
    return tdiv(lateral * 0x43, 0x23) + 0x297


def _edge(cfg, base, i):
    return struct.unpack_from('<2H', cfg, base + 4 * i)          # (row, column)


def fence_row(cfg, k):
    return _edge(cfg, FENCE_EDGE, k)[0]


def wall_row(cfg, k):
    return _edge(cfg, WALL_EDGE, k)[0]


def classify(cfg, c106, k, neg=False):
    """0 in play, 1 obstacle or stands wall (or foul past the wall), 2 beyond the fence, 3 foul.
    c106 is the row before the +100 panorama offset (game function 3000:0614)."""
    cx = c106 + 100
    if k > 69:
        ref = fence_row(cfg, 0) if neg else fence_row(cfg, 69)
        return 1 if cx > ref else 3
    if cx <= fence_row(cfg, k):
        return 2
    if cx >= wall_row(cfg, k):
        return 1
    for kk, y1, y2 in obstacles(cfg):
        if kk == k and y1 <= cx <= y2:
            return 1
    return 0


def fence_tops(cfg):
    return list(struct.unpack_from('<%dH' % EDGE_N, cfg, FENCE_TOP))


def fence_height(cfg, k):
    """fence height in feet over the column's fence base (game function 1000:f6f6)."""
    if k > 69:
        return 10
    d = fence_row(cfg, k) - struct.unpack_from('<H', cfg, FENCE_TOP + 2 * k)[0]
    return 0 if d <= 0 else tdiv(d * 2, 7)


def fence_heights(cfg):
    return [fence_height(cfg, k) for k in range(EDGE_N)]


def obstacles(cfg):
    """(column, y1, y2) per valid obstacle pair, in table order."""
    out = []
    for i in range(140, 200, 2):
        (r0, c0), (r1, c1) = _edge(cfg, FENCE_EDGE, i), _edge(cfg, FENCE_EDGE, i + 1)
        if c0 == c1 and r0 and r1:
            out.append((c0, r0, r1))
    return out


def dugouts(cfg):
    x0, y0, x1, y1 = struct.unpack_from('<4h', cfg, DUGOUT)
    return ((x0, y0), (x1, y1))


@lru_cache(maxsize=None)
def depth_for_row(y):
    """smallest depth whose panorama row is at or above y, None if none."""
    for p in range(-50, 1101):
        if field_row(p) <= y:
            return p
    return None


@lru_cache(maxsize=None)
def lateral_for_x(x):
    """lateral whose panorama x is nearest x, smallest lateral on ties."""
    return min(range(-500, 501), key=lambda p: (abs(field_x(p) - x), p))


def _points(cfg):
    """per column k: (lateral, depth, feet) for the fence base; depth None and feet 0 when the row is 0."""
    out = []
    for k in range(EDGE_N):
        row = fence_row(cfg, k)
        lat = lateral_for_x(16 * k + 8)
        dep = depth_for_row(row) if row else None
        out.append((lat, dep, round(math.hypot(dep, lat)) if dep is not None else 0))
    return out


def fence_feet(cfg):
    return [feet for _, _, feet in _points(cfg)]


def zone_distances(cfg):
    """fence feet at LF, LCF, CF, RCF, RF: the column nearest each zone angle. 0 if no column has a fence."""
    pts = [(k, lat, dep, feet) for k, (lat, dep, feet) in enumerate(_points(cfg)) if feet > 0]
    out = []
    for za in ZONE_ANGLES:
        best = min(pts, key=lambda p: (abs(math.degrees(math.atan2(p[1], p[2])) - za), p[0]), default=None)
        out.append(best[3] if best else 0)
    return tuple(out)


def _interp(angle, values):
    """piecewise linear over ZONE_ANGLES, clamped to the end values."""
    if angle <= ZONE_ANGLES[0]:
        return float(values[0])
    if angle >= ZONE_ANGLES[-1]:
        return float(values[-1])
    for i in range(len(ZONE_ANGLES) - 1):
        a0, a1 = ZONE_ANGLES[i], ZONE_ANGLES[i + 1]
        if angle <= a1:
            return values[i] + (angle - a0) / (a1 - a0) * (values[i + 1] - values[i])


def _pick(dists):
    """per column k: (depth, lateral) of the fence base that matches the zone distances."""
    out = []
    for k in range(EDGE_N):
        lat = lateral_for_x(16 * k + 8)
        best = None
        for p in range(0, 1001):
            e = abs(math.hypot(p, lat) - _interp(math.degrees(math.atan2(lat, p)), dists))
            if best is None or e < best[0]:
                best = (e, p)
        out.append((best[1], lat))
    return out


def fence_rows(dists):
    """70 panorama fence base rows for LF, LCF, CF, RCF, RF distances in feet."""
    return [field_row(p) for p, _ in _pick(dists)]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def with_fences(cfg, dists, heights):
    """new CFG bytes with fence rows, tops and zone distances set. heights: a number or 5 values (LF..RF)."""
    dists = tuple(dists)
    if len(dists) != 5 or not all(_is_int(d) and 150 <= d <= 650 for d in dists):
        raise ValueError('zone distances must be 5 ints in 150..650: %r' % (dists,))
    if isinstance(heights, (list, tuple)):
        heights = tuple(heights)
    else:
        heights = (heights,) * 5
    if len(heights) != 5 or not all(_is_num(h) and 0 <= h <= 60 for h in heights):
        raise ValueError('fence heights must be a number or 5 numbers in 0..60: %r' % (heights,))
    picks = _pick(dists)
    rows = [field_row(p) for p, _ in picks]
    for k in range(6, 64):
        if wall_row(cfg, k) <= rows[k]:
            raise ValueError('column %d: fence row %d not above wall row %d' % (k, rows[k], wall_row(cfg, k)))
    out = bytearray(cfg)
    struct.pack_into('<5H', out, 0x20, *dists)
    for k, (p, lat) in enumerate(picks):
        h = round(_interp(math.degrees(math.atan2(lat, p)), heights))
        struct.pack_into('<2H', out, FENCE_EDGE + 4 * k, rows[k], k)
        struct.pack_into('<H', out, FENCE_TOP + 2 * k, max(0, rows[k] - (h * 7 + 1) // 2))
    out[OBST_EDGE:OBST_END] = bytes(OBST_END - OBST_EDGE)
    return bytes(out)


def info(cfg):
    """decoded CFG header. Conditions as shown on Assign Stadiums; notes is a per-park id 0..40 (37 GRASS, 38 TURF)."""
    lf, lcf, cf, rcf, rf = struct.unpack_from('<5H', cfg, 0x20)
    hs = fence_heights(cfg)
    return dict(name=cfg[:31].split(b'\0')[0].decode('latin-1'), surface=SURFACE.get(cfg[0x1f], cfg[0x1f]),
                fences=(lf, lcf, cf, rcf, rf), wind_mph=cfg[0x2a], wind_dir=cfg[0x2b], temp_f=cfg[0x2c],
                humidity=cfg[0x2d], altitude_ft=struct.unpack_from('<H', cfg, 0x2f)[0], notes=cfg[0x31],
                fence_y=[struct.unpack_from('<H', cfg, FENCE_EDGE + 4 * k)[0] for k in range(EDGE_N)],
                wall_y=[struct.unpack_from('<H', cfg, WALL_EDGE + 4 * k)[0] for k in range(EDGE_N)],
                zones=zone_distances(cfg), heights=(min(hs), max(hs)), obstacles=len(obstacles(cfg)),
                dugouts=dugouts(cfg))


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
    elif a[:1] == ['info'] and len(a) >= 2:
        for f in a[1:]:
            i = info(open(f, 'rb').read())
            print('%s: %s' % (os.path.basename(f), ', '.join('%s=%s' % kv for kv in i.items() if not kv[0].endswith('_y'))))
    elif a[:1] == ['fences'] and len(a) == 2:
        cfg = open(a[1], 'rb').read()
        hs, obs = fence_heights(cfg), obstacles(cfg)
        print('LF=%d LCF=%d CF=%d RCF=%d RF=%d  height %d..%d  obstacles=%d' % (
            *zone_distances(cfg), min(hs), max(hs), len(obs)))
        for k, y1, y2 in obs:
            print('col %d rows %d..%d' % (k, y1, y2))
    elif a[:1] == ['refence'] and len(a) in (8, 9, 13):
        hs = [float(x) for x in a[8:]] or [8]
        try:
            new = with_fences(open(a[1], 'rb').read(), [int(x) for x in a[3:8]], hs * 5 if len(hs) == 1 else hs)
        except ValueError as e:
            sys.exit(str(e))
        open(_out(a[2]), 'wb').write(new)
    elif a[:1] == ['iso'] and len(a) >= 4:
        iso(a[1], a[2], a[3:])
    else:
        sys.exit(__doc__)
