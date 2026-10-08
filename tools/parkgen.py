#!/usr/bin/env python3
"""New stadiums from a stock one: keep the playing field pixel for pixel, regenerate the stands, sky and scoreboard
with the local ComfyUI (SDXL inpaint), quantize back to the stadium's 96 own colours (CFG palette 80..175).

usage:
  parkgen.py gen BASE_STEM OUTDIR SEED [DENOISE] [PROMPT_KEY]   inpaint the stock panorama, writes OUTDIR/gen_SEED.png
  parkgen.py build BASE_STEM GEN.png NEWSTEM "DISPLAY NAME" OUTDIR
                                    writes OUTDIR/NEWSTEM.SDM, NEWSTEM.CFG (base CFG with the new name and palette)
                                    and NEWSTEM.OVL (174 x 73 thumbnail for the stadium select screen)

The field mask is a polygon measured on GRASS (generic grass park); every stock park shares the camera, but the
stands edge differs, so check OUTDIR/mask.png before trusting it on another base. GPU courtesy check first.
"""
import json
import os
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import faces  # noqa: E402
import stadium  # noqa: E402
from assets import SRC, read_frames, write_frames  # noqa: E402
from dcl import implode  # noqa: E402

W, H = 1120, 444
GW, GH = 1680, 664                                  # SDXL works near 1 MP; 1.5x the panorama, multiple of 8
LEFT = [(560, 139), (300, 141), (150, 152), (75, 170), (25, 215), (40, 230), (400, 425), (425, 444)]
PROMPTS = {
    'modern': ('wide panoramic view from behind home plate of a modern 2020s major league baseball ballpark, '
               'steel and glass architecture, sold-out crowd, every seat filled with thousands of fans in colorful clothes, '
               'glass-fronted luxury suites between the decks, a huge LED video scoreboard beyond center field, '
               'downtown city skyline beyond the outfield, clear blue afternoon sky, detailed retro video game '
               'background art, 1990s pixel art style'),
    'night': ('wide panoramic view from behind home plate of a modern major league baseball ballpark during a night game, '
              'dark night sky, bright stadium light towers, sold-out crowd filling two curved decks, glowing LED ribbon '
              'boards along the upper deck, a huge lit video scoreboard beyond center field, city lights beyond the '
              'outfield, detailed retro video game background art, 1990s pixel art style'),
    'brick': ('wide panoramic view from behind home plate of a retro-classic brick baseball ballpark, red brick facade '
              'and arches, dark green seats in two decks filled with a sold-out crowd, a long old brick warehouse beyond '
              'right field, a manual scoreboard and a video board beyond center field, sunny afternoon, blue sky, '
              'detailed retro video game background art, 1990s pixel art style'),
}
NEG = ('empty seats, empty stands, text, words, signage, watermark, logo, letters, blurry, distorted perspective, '
       'fisheye, people close to camera, players')


def keep_mask():
    poly = LEFT + [(W - x, y) for x, y in reversed(LEFT)]
    m = Image.new('L', (W, H), 0)
    ImageDraw.Draw(m).polygon(poly, fill=255)
    return np.asarray(m) > 0


def _upload(png_path, name):
    b = uuid.uuid4().hex
    body = (('--%s\r\nContent-Disposition: form-data; name="image"; filename="%s"\r\nContent-Type: image/png\r\n\r\n'
             % (b, name)).encode() + open(png_path, 'rb').read()
            + ('\r\n--%s\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--%s--\r\n' % (b, b)).encode())
    req = urllib.request.Request(faces.COMFY + '/upload/image', body,
                                 {'Content-Type': 'multipart/form-data; boundary=' + b})
    return json.load(urllib.request.urlopen(req, timeout=60))['name']


def _workflow(img_name, text, seed, denoise):
    return {
        '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': faces.CKPT}},
        '2': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': text}},
        '3': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': NEG}},
        '4': {'class_type': 'LoadImage', 'inputs': {'image': img_name}},   # MASK = transparent = regenerate
        '5': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['4', 0], 'vae': ['1', 2]}},
        '6': {'class_type': 'SetLatentNoiseMask', 'inputs': {'samples': ['5', 0], 'mask': ['4', 1]}},
        '7': {'class_type': 'KSampler', 'inputs': {
            'model': ['1', 0], 'positive': ['2', 0], 'negative': ['3', 0], 'latent_image': ['6', 0],
            'seed': seed, 'steps': 34, 'cfg': 6.0, 'sampler_name': 'dpmpp_2m', 'scheduler': 'karras',
            'denoise': denoise}},
        '8': {'class_type': 'VAEDecode', 'inputs': {'samples': ['7', 0], 'vae': ['1', 2]}},
        '9': {'class_type': 'PreviewImage', 'inputs': {'images': ['8', 0]}},
    }


def gen(base, outdir, seed, denoise=0.8, key='modern'):
    if faces.owner_busy():
        sys.exit('GPU courtesy: companion app active in the last 180 s, stopping')
    os.makedirs(outdir, exist_ok=True)
    d = os.path.join(SRC, 'STADIUMS', base)
    rgb = stadium.render(stadium.unpack(d + '.SDM'), stadium.palette(open(d + '.CFG', 'rb').read()))
    keep = keep_mask()
    rgba = rgb.resize((GW, GH), Image.LANCZOS).convert('RGBA')      # resize RGB first: an RGBA resize zeroes
    rgba.putalpha(Image.fromarray(np.where(keep, 255, 0).astype('uint8')).resize((GW, GH)))  # masked pixels
    src = os.path.join(outdir, 'src.png')
    rgba.save(src)
    shown = rgb.copy()
    shown.paste((20, 20, 20), mask=Image.fromarray(np.where(keep, 0, 160).astype('uint8')))
    shown.save(os.path.join(outdir, 'mask.png'))
    name = _upload(src, 'tlrb2_park_%s.png' % base.lower())
    pid = faces._post('/prompt', {'prompt': _workflow(name, PROMPTS[key], seed, denoise)})['prompt_id']
    for _ in range(900):
        time.sleep(1)
        h = json.load(urllib.request.urlopen(faces.COMFY + '/history/' + pid, timeout=30))
        if pid in h and h[pid].get('outputs'):
            img = h[pid]['outputs']['9']['images'][0]
            q = 'filename=%s&subfolder=%s&type=%s' % (img['filename'], img['subfolder'], img['type'])
            dst = os.path.join(outdir, 'gen_%d.png' % seed)
            open(dst, 'wb').write(urllib.request.urlopen(faces.COMFY + '/view?' + q, timeout=60).read())
            print(dst)
            return dst
    sys.exit('timeout')


def _lab(rgb):
    """float array (..., 3) of 0..255 sRGB to a cheap perceptual space (weighted RGB, good enough for 96 colours)."""
    return rgb.astype('f4') * np.array([0.30, 0.59, 0.11], 'f4') ** 0.5


def choose_palette(field_px, new_rgb, pal, free_iters=12, seed=0):
    """Pick colours for the free stadium slots (80..175 not used by the kept field) by k-means on the new pixels,
    holding the field's colours and the low greys fixed. Returns (palette list, allowed index list)."""
    used = set(int(i) for i in np.unique(field_px))
    free = [i for i in range(stadium.PAL_LO, stadium.PAL_LO + stadium.PAL_N) if i not in used]
    fixed = sorted(used | set(range(17)))
    cols = np.array(pal, 'f4').reshape(256, 3)
    pts = new_rgb.reshape(-1, 3).astype('f4')
    rng = np.random.default_rng(seed)
    pts = pts[rng.choice(len(pts), min(len(pts), 60000), replace=False)]
    fx = _lab(cols[fixed])
    pl = _lab(pts)
    d_fixed = ((pl[:, None, :] - fx[None]) ** 2).sum(-1).min(1)
    cent = []                                      # k-means++ seeded where the fixed colours fit worst
    d = d_fixed.copy()
    for _ in free:
        c = pl[rng.choice(len(pl), p=d / d.sum())] if d.sum() > 0 else pl[rng.integers(len(pl))]
        cent.append(c)
        d = np.minimum(d, ((pl - c) ** 2).sum(-1))
    cent = np.array(cent)
    for _ in range(free_iters):
        allc = np.concatenate([fx, cent])
        a = ((pl[:, None, :] - allc[None]) ** 2).sum(-1).argmin(1) - len(fx)
        for j in range(len(cent)):
            m = a == j
            if m.any():
                cent[j] = pl[m].mean(0)
    rgb = np.clip(cent / (np.array([0.30, 0.59, 0.11], 'f4') ** 0.5), 0, 255)
    out = list(pal)
    for i, c in zip(free, rgb):
        c6 = [int(round(v * 63 / 255)) for v in c]       # the DAC is 6-bit: store what the game will show
        out[i * 3:i * 3 + 3] = [v * 255 // 63 for v in c6]
    return out, sorted(fixed + free)


def quantize(rgb_img, pal, allowed, dither=True):
    """map an RGB image onto the allowed palette indices (Floyd-Steinberg by default), return index bytes."""
    lut = list(allowed)
    p = []
    for i in lut:
        p += pal[i * 3:i * 3 + 3]
    p += p[:3] * (256 - len(lut))
    pim = Image.new('P', (1, 1))
    pim.putpalette(p)
    q = rgb_img.convert('RGB').quantize(palette=pim, dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE)
    return np.array(lut, 'u1')[np.minimum(np.asarray(q), len(lut) - 1)]


def cfg_with(cfg, name, pal):
    """base CFG with a new display name (one NUL-terminated string in bytes 0..30; text after the NUL in stock files,
    e.g. GRASS's "STADIUM", is stale) and palette 80..175."""
    b = bytearray(cfg)
    nm = name.upper()
    if not (0 < len(nm) <= 30 and nm.isascii() and '\0' not in nm):
        raise ValueError('name must be 1..30 ASCII characters')
    b[0:31] = nm.encode().ljust(31, b'\0')
    for k in range(stadium.PAL_N * 3):
        b[stadium.PAL_OFF + k] = (pal[stadium.PAL_LO * 3 + k] * 63 + 127) // 255   # nearest 6-bit step
    return bytes(b)


def build(base, gen_png, stem, name, outdir, dither=True):
    if not (stem.isalnum() and 1 <= len(stem) <= 8):
        raise ValueError('stem must be 1..8 letters or digits (DOS 8.3)')
    os.makedirs(outdir, exist_ok=True)
    d = os.path.join(SRC, 'STADIUMS', base)
    cfg = open(d + '.CFG', 'rb').read()
    px = np.frombuffer(stadium.unpack(d + '.SDM'), 'u1').reshape(H, W)
    pal = stadium.palette(cfg)
    keep = keep_mask()
    new = np.asarray(Image.open(gen_png).convert('RGB').resize((W, H), Image.LANCZOS))
    pal2, allowed = choose_palette(px[keep], new[~keep], pal)
    q = quantize(Image.fromarray(new), pal2, allowed, dither)
    out = np.where(keep, px, q).astype('u1')
    stem = stem.upper()
    open(os.path.join(outdir, stem + '.SDM'), 'wb').write(implode(out.tobytes()))
    cfg2 = cfg_with(cfg, name, pal2)
    open(os.path.join(outdir, stem + '.CFG'), 'wb').write(cfg2)
    stadium.render(out.tobytes(), pal2).save(os.path.join(outdir, stem + '.png'))
    ovl = read_frames(open(os.path.join(SRC, 'ANMS', base + '.OVL'), 'rb').read())
    f = dict(ovl[0])
    cw = round(H * f['w'] / f['h'])                # thumbnail = centre crop of the panorama at its aspect, scaled
    x0 = (W - cw) // 2
    th = stadium.render(out.tobytes(), pal2).crop((x0, 0, x0 + cw, H)).resize((f['w'], f['h']), Image.LANCZOS)
    f['raw'] = quantize(th, pal2, allowed, dither).tobytes()
    open(os.path.join(outdir, stem + '.OVL'), 'wb').write(write_frames([f] + ovl[1:]))
    return out, pal2


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['gen'] and len(a) >= 4:
        gen(a[1], a[2], int(a[3]), float(a[4]) if len(a) > 4 else 0.8, a[5] if len(a) > 5 else 'modern')
    elif a[:1] == ['build'] and len(a) == 6:
        build(a[1].upper(), a[2], a[3], a[4], a[5])
    else:
        sys.exit(__doc__)
