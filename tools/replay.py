"""Replay ANM decoder and encoder (HOMERUN.ANM, 1BOUT.ANM, INTRO.ANM, ...).

usage:
  replay.py info ANM...
  replay.py frames ANM OUTDIR
  replay.py gif ANM OUT.gif [MS]
  replay.py build OUT.ANM PNG... [--flags N]
  replay.py roundtrip ANM
"""
import os
import struct
import sys

from PIL import Image

GUARD = ('/mnt/nvme/tlrb2/c/', '/mnt/nvme/tlrb2/pristine/', '/mnt/nvme/tlrb2/iso/')

SIZES_AT = 0x30e


def _out(path):
    a = os.path.abspath(path)
    for g in GUARD:
        if a.startswith(g):
            sys.exit('refusing to write under ' + g)
    return a


def _need(stream, si, k):
    if si + k > len(stream):
        raise ValueError('truncated frame stream')


def _put(buf, di, n, data):
    k = min(len(data), n - di)
    if k > 0:
        buf[di:di + k] = data[:k]


def decode_frame(stream, buf, width, height):
    """Apply one frame stream in place onto buf (width*height bytes), clamped to the frame."""
    n = width * height
    if len(buf) != n:
        raise ValueError('buffer is not width*height')
    end = len(stream)
    si = di = 0
    while di < n and si < end:
        op = stream[si]
        si += 1
        if op == 0x80:
            _need(stream, si, 2)
            w = struct.unpack_from('<H', stream, si)[0]
            si += 2
            if w & 0x8000:
                if w & 0x4000:
                    c = w ^ 0xc000
                    _need(stream, si, 1)
                    v = stream[si]
                    si += 1
                    _put(buf, di, n, bytes((v,)) * c)
                else:
                    c = w ^ 0x8000
                    _need(stream, si, c)
                    _put(buf, di, n, stream[si:si + c])
                    si += c
                di += c
            elif w == 0:
                break
            else:
                di += w
        elif op == 0:
            _need(stream, si, 2)
            c, v = stream[si], stream[si + 1]
            si += 2
            _put(buf, di, n, bytes((v,)) * c)
            di += c
        elif op & 0x80:
            di += op & 0x7f
        else:
            _need(stream, si, op)
            _put(buf, di, n, stream[si:si + op])
            si += op
            di += op


def parse(data):
    data = bytes(data)
    if len(data) < SIZES_AT:
        raise ValueError('file shorter than header')
    palette = data[:768]
    n = struct.unpack_from('<H', data, 0x300)[0]
    if n == 0:
        raise ValueError('zero frames')
    flags, height, width = struct.unpack_from('<HHH', data, 0x302)
    if width == 0 or height == 0:
        raise ValueError('zero width or height')
    hdr_end = SIZES_AT + 2 * n
    if len(data) < hdr_end:
        raise ValueError('frame size table truncated')
    sizes = list(struct.unpack_from('<%dH' % n, data, SIZES_AT))
    if hdr_end + sum(sizes) != len(data):
        raise ValueError('frame sizes do not match file length')
    frames = []
    p = hdr_end
    for s in sizes:
        frames.append(data[p:p + s])
        p += s
    return dict(palette=palette, flags=flags, width=width, height=height, sizes=sizes, frames=frames)


def decode(data):
    p = parse(data)
    w, h = p['width'], p['height']
    buf = bytearray(w * h)
    out = []
    for s in p['frames']:
        decode_frame(s, buf, w, h)
        out.append(bytes(buf))
    info = {k: p[k] for k in ('palette', 'flags', 'width', 'height', 'sizes')}
    return info, out


def _runlen(cur, i):
    v = cur[i]
    n = len(cur)
    j = i + 1
    while j < n and cur[j] == v:
        j += 1
    return j - i


def _skip_ops(L, out):
    while L > 0:
        if L <= 127:
            out.append(0x80 | L)
            return
        c = min(L, 0x7fff)
        out += b'\x80' + struct.pack('<H', c)
        L -= c


def _run_ops(v, r, out):
    while r > 0:
        c = min(r, 0x3fff)
        if 0 < r - c < 3:
            c = r - 3
        if c <= 255:
            out += bytes((0, c, v))
        else:
            out += b'\x80' + struct.pack('<H', 0xc000 | c) + bytes((v,))
        r -= c


def _dump_ops(data, out):
    i = 0
    n = len(data)
    while i < n:
        rem = n - i
        if rem <= 127:
            out.append(rem)
            out += data[i:]
            return
        c = min(rem, 0x3fff)
        out += b'\x80' + struct.pack('<H', 0x8000 | c) + data[i:i + c]
        i += c


def encode_frame(cur, prev=None):
    cur = bytes(cur)
    n = len(cur)
    if prev is not None:
        prev = bytes(prev)
        if len(prev) != n:
            raise ValueError('prev frame has wrong length')
    out = bytearray()
    i = 0
    while i < n:
        if prev is not None and cur[i] == prev[i]:
            j = i + 1
            while j < n and cur[j] == prev[j]:
                j += 1
            if j == n:
                break
            _skip_ops(j - i, out)
            i = j
            continue
        r = _runlen(cur, i)
        if r >= 3:
            _run_ops(cur[i], r, out)
            i += r
            continue
        j = i + 1
        while j < n:
            if prev is not None and cur[j] == prev[j]:
                break
            if _runlen(cur, j) >= 3:
                break
            j += 1
        _dump_ops(cur[i:j], out)
        i = j
    out += b'\x80\x00\x00'
    out += b'\x00' * (-len(out) % 4)
    return bytes(out)


def encode(frames, palette, width, height, flags=1):
    if len(palette) != 768:
        raise ValueError('palette must be 768 bytes')
    if any(v > 63 for v in palette):
        raise ValueError('palette values must be 0..63')
    if not 0 < len(frames) <= 0xffff:
        raise ValueError('frame count must be 1..65535')
    for name, v in (('width', width), ('height', height), ('flags', flags)):
        if not 0 <= v <= 0xffff:
            raise ValueError(name + ' out of u16 range')
    streams = []
    prev = None
    for k, f in enumerate(frames):
        if len(f) != width * height:
            raise ValueError('frame %d has wrong length' % k)
        s = encode_frame(f, prev)
        if len(s) > 0xffff:
            raise ValueError('frame %d encodes to more than 0xffff bytes' % k)
        streams.append(s)
        prev = f
    head = (bytes(palette) + struct.pack('<H', len(frames))
            + struct.pack('<6H', flags, height, width, 0, 0, 0)
            + b''.join(struct.pack('<H', len(s)) for s in streams))
    return head + b''.join(streams)


def pil_palette(palette768):
    return [v * 255 // 63 for v in palette768]


def _load(path):
    with open(path, 'rb') as f:
        return f.read()


def _decode_file(path):
    try:
        return decode(_load(path))
    except ValueError as e:
        sys.exit('%s: %s' % (os.path.basename(path), e))


def _info(path):
    data = _load(path)
    try:
        p = parse(data)
    except ValueError as e:
        sys.exit('%s: %s' % (os.path.basename(path), e))
    print('%s: %d frames %dx%d flags 0x%04X bytes %d' % (
        os.path.basename(path), len(p['frames']), p['width'], p['height'], p['flags'], len(data)))


def _write_frames(info, frames, outdir):
    out = _out(outdir)
    os.makedirs(out, exist_ok=True)
    pal = pil_palette(info['palette'])
    digits = max(2, len(str(len(frames) - 1)))
    for i, f in enumerate(frames):
        im = Image.frombytes('P', (info['width'], info['height']), f)
        im.putpalette(pal)
        im.save(os.path.join(out, '%0*d.png' % (digits, i)))


def _gif(anm, outpath, ms):
    info, frames = _decode_file(anm)
    pal = pil_palette(info['palette'])
    ims = []
    for f in frames:
        im = Image.frombytes('P', (info['width'], info['height']), f)
        im.putpalette(pal)
        ims.append(im)
    out = _out(outpath)
    ims[0].save(out, save_all=True, append_images=ims[1:], duration=ms, loop=0)


def _build(out_path, pngs, flags):
    raws = []
    palette = None
    size = None
    for p in pngs:
        with Image.open(p) as im:
            if im.mode != 'P':
                sys.exit('%s: not P mode' % os.path.basename(p))
            if size is None:
                size = im.size
                palette = (im.getpalette() or [])[:768]
            elif im.size != size:
                sys.exit('%s: size differs from first PNG' % os.path.basename(p))
            raws.append(im.tobytes())
    palette = palette + [0] * (768 - len(palette))
    six = bytes((v * 63 + 127) // 255 for v in palette)
    w, h = size
    data = encode(raws, six, w, h, flags)
    with open(_out(out_path), 'wb') as f:
        f.write(data)


def _roundtrip(anm):
    data = _load(anm)
    try:
        info, frames = decode(data)
        out = encode(frames, info['palette'], info['width'], info['height'], info['flags'])
    except ValueError as e:
        sys.exit('%s: %s' % (os.path.basename(anm), e))
    info2, frames2 = decode(out)
    name = os.path.basename(anm)
    same = frames2 == frames and all(info2[k] == info[k] for k in ('palette', 'flags', 'width', 'height'))
    if not same:
        print('%s MISMATCH' % name)
        sys.exit(1)
    print('%s ok %d %d' % (name, len(data), len(out)))


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == 'info' and args:
        for p in args:
            _info(p)
    elif cmd == 'frames' and len(args) == 2:
        info, frames = _decode_file(args[0])
        _write_frames(info, frames, args[1])
    elif cmd == 'gif' and len(args) in (2, 3):
        ms = int(args[2]) if len(args) == 3 else 80
        _gif(args[0], args[1], ms)
    elif cmd == 'build' and len(args) >= 2:
        flags = 1
        if '--flags' in args:
            k = args.index('--flags')
            if k + 1 >= len(args):
                sys.exit(__doc__)
            flags = int(args[k + 1], 0)
            args = args[:k] + args[k + 2:]
        if len(args) < 2:
            sys.exit(__doc__)
        _build(args[0], args[1:], flags)
    elif cmd == 'roundtrip' and len(args) == 1:
        _roundtrip(args[0])
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
