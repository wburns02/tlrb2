#!/usr/bin/env python3
"""Render TLRB2 art assets to PNG. See FORMATS.md (PAL, SCR, FNT, ANM/OVL).

usage: assets.py [--src DIR] [--out DIR] scr|fnt|anm|all [names...]
"""
import os, struct, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dcl import explode, implode
from PIL import Image

SRC = '/mnt/nvme/tlrb2/files'
OUT = '/mnt/nvme/tlrb2/assets_png'


def load_pal(path):
    d = open(path, 'rb').read()[:768]
    out = []
    for i in range(256):
        r, g, b = d[i * 3:i * 3 + 3]
        out += [min(255, (c & 63) * 255 // 63) for c in (r, g, b)]
    return out


def pal_for(src, stem):
    for n in (stem, 'DEFAULT'):
        p = os.path.join(src, n + '.PAL')
        if os.path.exists(p):
            return load_pal(p)
    return [i // 3 for i in range(768)]


def parse_frames(d):
    """Normal ANM/OVL: u16 count, then 12 B hdr + DCL stream per frame."""
    n = struct.unpack_from('<H', d)[0]
    p = 2
    frames = []
    for _ in range(n):
        fl, h, w, yo, xo, cl = struct.unpack_from('<6H', d, p)
        p += 12
        if cl == 0:
            raw = d[p:p + h * w]
            p += h * w
        else:
            raw, p = explode(d, p)
        frames.append((fl >> 8, h, w, yo, xo, raw))
    return frames


def parse_scr(d):
    cnt, fl, h, w, yo, xo, cl = struct.unpack_from('<7H', d)
    raw, _ = explode(d, 14)
    return fl >> 8, h, w, raw


def read_scr(d):
    """SCR: u16 count, 12 B header (flags, h, w, yo, xo, clen), one DCL stream."""
    cnt, fl, h, w, yo, xo, cl = struct.unpack_from('<7H', d)
    raw, end = explode(d, 14)
    if len(raw) != h * w or end != len(d):
        raise ValueError('SCR decodes to %d B ending at %d, want %d B ending at %d' % (len(raw), end, h * w, len(d)))
    return dict(flags=fl, h=h, w=w, yo=yo, xo=xo, raw=raw)


def write_scr(s, dict_bits=6):
    raw = bytes(s['raw'])
    if len(raw) != s['h'] * s['w']:
        raise ValueError('raw is %d B, h*w is %d' % (len(raw), s['h'] * s['w']))
    stream = implode(raw, dict_bits)
    if len(stream) > 65535:
        raise ValueError('SCR stream %d B exceeds clen field' % len(stream))
    hdr = struct.pack('<7H', 1, s['flags'], s['h'], s['w'], s['yo'], s['xo'], len(stream))
    return hdr + stream


def read_frames(d):
    """Normal ANM/OVL: u16 count, then per frame a 12 B header and clen == 0 (raw h*w) or one DCL stream."""
    n = struct.unpack_from('<H', d)[0]
    p = 2
    frames = []
    for _ in range(n):
        if p + 12 > len(d):
            raise ValueError('frame header at %d overruns data' % p)
        fl, h, w, yo, xo, cl = struct.unpack_from('<6H', d, p)
        p += 12
        if cl == 0:
            if p + h * w > len(d):
                raise ValueError('stored frame at %d overruns data' % p)
            raw = d[p:p + h * w]
            p += h * w
        else:
            raw, p = explode(d, p)
            if len(raw) != h * w:
                raise ValueError('frame decodes to %d B, h*w is %d' % (len(raw), h * w))
        frames.append(dict(flags=fl, h=h, w=w, yo=yo, xo=xo, raw=raw, stored=(cl == 0)))
    if p != len(d):
        raise ValueError('frames end at %d, data is %d B' % (p, len(d)))
    return frames


def write_frames(frames, dict_bits=6):
    out = bytearray(struct.pack('<H', len(frames)))
    for f in frames:
        raw = bytes(f['raw'])
        if len(raw) != f['h'] * f['w']:
            raise ValueError('raw is %d B, h*w is %d' % (len(raw), f['h'] * f['w']))
        if f['stored']:
            body, cl = raw, 0
        else:
            body = implode(raw, dict_bits)
            cl = len(body)
            if cl > 65535:
                raise ValueError('frame stream %d B exceeds clen field; store it' % cl)
        out += struct.pack('<6H', f['flags'], f['h'], f['w'], f['yo'], f['xo'], cl)
        out += body
    return bytes(out)


def to_img(raw, w, h, pal, trans=None):
    im = Image.frombytes('P', (w, h), bytes(raw[:w * h]))
    im.putpalette(pal)
    if trans is not None:
        im.info['transparency'] = trans
    return im


def parse_fnt(d):
    n = struct.unpack_from('<H', d)[0]
    p = 2
    gl = []
    for _ in range(n):
        rows, bits, adv = d[p:p + 3]
        bpr = (bits + 7) // 8
        data = d[p + 3:p + 3 + rows * bpr]
        p += 3 + rows * bpr
        gl.append((rows, bits, adv, data, bpr))
    assert p == len(d), (p, len(d))
    return gl


def render_fnt(d, scale=3):
    gl = parse_fnt(d)
    cell = max(g[0] for g in gl) + 4, max(max(g[1], g[2]) for g in gl) + 4
    cols = 16
    im = Image.new('L', (cols * cell[1], 6 * cell[0]), 0)
    for i, (rows, bits, adv, data, bpr) in enumerate(gl):
        ox, oy = (i % cols) * cell[1] + 2, (i // cols) * cell[0] + 2
        for r in range(rows):
            for c in range(bits):
                if data[r * bpr + c // 8] & (0x80 >> (c % 8)):
                    im.putpixel((ox + c, oy + r), 255)
    return im.resize((im.width * scale, im.height * scale), Image.NEAREST)


def sheet(frames, pal, cols=8):
    mw = max(f[2] for f in frames)
    mh = max(f[1] for f in frames)
    rows = (len(frames) + cols - 1) // cols
    im = Image.new('P', (cols * (mw + 2), rows * (mh + 2)), 0)
    im.putpalette(pal)
    for i, (t, h, w, yo, xo, raw) in enumerate(frames):
        fr = Image.frombytes('P', (w, h), bytes(raw[:w * h]))
        im.paste(fr, ((i % cols) * (mw + 2), (i // cols) * (mh + 2)))
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=SRC)
    ap.add_argument('--out', default=OUT)
    ap.add_argument('kind', choices=['scr', 'fnt', 'anm', 'port', 'all'])
    ap.add_argument('names', nargs='*')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    want = {n.upper() for n in a.names}

    def pick(names):
        return [n for n in names if not want or os.path.splitext(n)[0].upper() in want]

    if a.kind in ('scr', 'all'):
        dd = os.path.join(a.src, 'SCREENS')
        for n in pick(sorted(os.listdir(dd))):
            if not n.upper().endswith('.SCR'):
                continue
            stem = n[:-4]
            t, h, w, raw = parse_scr(open(os.path.join(dd, n), 'rb').read())
            to_img(raw, w, h, pal_for(a.src, stem)).save(os.path.join(a.out, 'scr_%s.png' % stem))
    if a.kind in ('fnt', 'all'):
        for n in pick(sorted(os.listdir(a.src))):
            if n.upper().endswith('.FNT'):
                render_fnt(open(os.path.join(a.src, n), 'rb').read()).save(
                    os.path.join(a.out, 'fnt_%s.png' % n[:-4]))
    if a.kind in ('port', 'all'):
        # OLDPORT.ANM: no count word; 528 x (12 B hdr + raw 48x56), hdr clen 0 = uncompressed
        d = open(os.path.join(a.src, 'OLDPORT.ANM'), 'rb').read()
        fr, p = [], 0
        while p + 12 <= len(d):
            fl, h, w, yo, xo, cl = struct.unpack_from('<6H', d, p)
            fr.append((fl >> 8, h, w, yo, xo, d[p + 12:p + 12 + h * w]))
            p += 12 + h * w
        print('OLDPORT frames', len(fr), 'end', p, 'size', len(d))
        sheet(fr[:64], pal_for(a.src, 'DEFAULT'), 16).save(os.path.join(a.out, 'port_OLDPORT_first64.png'))
    if a.kind in ('anm', 'all'):
        dd = os.path.join(a.src, 'ANMS')
        pal = pal_for(a.src, 'DEFAULT')
        for n in pick(sorted(os.listdir(dd))):
            if not n.upper().endswith(('.ANM', '.OVL')) or os.path.getsize(os.path.join(dd, n)) > 400000:
                continue
            try:
                fr = parse_frames(open(os.path.join(dd, n), 'rb').read())
            except Exception as e:
                print('skip', n, e)
                continue
            if fr and all(len(f[5]) >= f[1] * f[2] for f in fr):
                sheet(fr, pal).save(os.path.join(a.out, 'anm_%s.png' % n.rsplit('.', 1)[0]))


if __name__ == '__main__':
    main()
