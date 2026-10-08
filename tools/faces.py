#!/usr/bin/env python3
"""New generic player faces for ANMS/PORTRAIT.ANM (IDEAS.md, faces pilot).

PORTRAIT.ANM: u16 count, then per frame a 12 B header (0x1001, 56, 48, 0, 0, 0) and 48 x 56 raw 8-bit pixels.
BB load_portrait_by_rec_idx_1b (7000:da0a) seeks idx * 0xa8c + 0xe for idx < 981 and never reads the count, so
frames appended after the 30 stock faces are reachable through the player record portrait word (+0x1b).
BB 2000:b6df remaps 48..63 per team (0x10: 64..79 -> 48..63, 0x20: 48..63 -> 64..79): 48..55 is the primary
team ramp, 56..63 the secondary. Only cap and collar pixels may land on 48..55; 56..63 is never used.

usage:
  faces.py gen OUTDIR [N] [SET]     render N (default all) prompts of SET (pilot, set1) on the local ComfyUI
                                    (GPU courtesy check first); OUTDIR/groups.json gets each face's group flag
  faces.py build OUTDIR             crop + quantize OUTDIR/raw/*.png to OUTDIR/frames/*.bin, preview sheets;
                                    frames whose cap does not take the team colour go to OUTDIR/rejects
  faces.py append ANM_IN ANM_OUT BIN...   copy ANM_IN with the frames appended (count updated) and write
                                    FACEGRP.DAT (one group flag byte per face) next to ANM_OUT

Group flag: UTIL DS:776e flags the stock faces 3, 4, 16, 18, 20, 21, 22, 25, 27 (dark skin), and UTIL 5000:ea5e
assigns a generic face whose flag matches the player record's +0x1d bit0. FACEGRP.DAT carries the same flag for
every face, stock and new, so our rookie generator can keep face and record flag in agreement.
"""
import colorsys
import glob
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from assets import pal_for, parse_frames   # noqa: E402

W, H = 48, 56
FRAME_HDR = struct.pack('<6H', 0x1001, H, W, 0, 0, 0)
FRAME_SIZE = 12 + W * H                     # 0xa8c
SRC = '/mnt/nvme/tlrb2/files'
STOCK = '/mnt/nvme/tlrb2/pristine/TONY2/ANMS/PORTRAIT.ANM'
COMFY = 'http://127.0.0.1:8188'
CKPT = 'juggernautXL_v9.safetensors'
TEAM = range(48, 56)                        # primary team colour ramp (cap, collar)
TEAM2 = range(56, 64)                       # secondary team ramp: browns in DEFAULT.PAL, never used
SKIP = {0, 7, 8, 64}                        # rare in stock faces, kept out of new art
CAP_ROWS, COLLAR_ROW = 21, 38               # team colour only on the cap (rows 0..20) and collar/jersey (38..55)
CAP_MIN = 100                               # team-ramp pixels in the cap rows; stock faces have 199..726
STOCK_GROUP = bytes(1 if i in (3, 4, 16, 18, 20, 21, 22, 25, 27) else 0 for i in range(30))   # UTIL DS:776e

STYLE = ('head and shoulders portrait of a fictional professional baseball player from the 1980s, {who}, '
         'wearing a plain bright red baseball cap with no logo and a light gray baseball jersey with thin dark '
         'piping, plain dark olive green background, painted illustration, soft studio light, centered, '
         'chest up, looking toward the camera')
NEG = ('logo, letters, text, watermark, helmet, bat, glove, hands, sunglasses, two people, cropped head, '
       'blurry, photo frame, border')
PILOT = [
    'young white rookie with freckles, clean shaven, slight smile',
    'Black veteran in his thirties with a thick mustache, serious',
    'Latino shortstop in his twenties with a thin mustache, confident',
    'white pitcher in his late thirties with gray stubble, weathered face',
    'young Black outfielder, clean shaven, broad smile',
    'heavyset white catcher with a round face and a beard',
    'Latino pitcher with dark eyebrows, clean shaven, intense stare',
    'white infielder with a big 1980s mustache and long sideburns',
    'Black first baseman with a short goatee, calm expression',
    'Asian American utility player in his twenties, clean shaven, neutral expression',
]
PILOT_GROUP = [0, 1, 0, 0, 1, 0, 0, 0, 1, 0]


def _set1():
    """60 faces, roughly a 1980s major league mix: 36 white, 12 Black, 10 Latino, 2 Asian American."""
    kinds = [('white', 0)] * 36 + [('Black', 1)] * 12 + [('Latino', 0)] * 10 + [('Asian American', 0)] * 2
    ages = ['young rookie', 'player in his mid twenties', 'veteran in his early thirties',
            'veteran in his late thirties with a weathered face']
    hair = ['clean shaven', 'with a thick mustache', 'with light stubble', 'with a short beard',
            'with a thin mustache', 'clean shaven with sideburns']
    looks = ['slight smile', 'serious expression', 'broad smile', 'intense stare', 'calm expression']
    build = ['', 'heavyset ', 'lean ', '']
    who, grp = [], []
    for k, (kind, g) in enumerate(kinds):
        who.append('%s%s %s, %s, %s' % (build[k % 4], kind, ages[(k * 7) % 4], hair[(k * 5) % 6], looks[(k * 3) % 5]))
        grp.append(g)
    order = sorted(range(len(who)), key=lambda k: (k * 37) % len(who))   # interleave kinds
    return [who[k] for k in order], [grp[k] for k in order]


SETS = {'pilot': (PILOT, PILOT_GROUP, 7100), 'set1': _set1() + (7300,)}


def owner_busy(window_s=180):
    """GPU courtesy: the companion app logged a chat or image POST in the last window_s seconds."""
    try:
        log = subprocess.run(['journalctl', '--user', '-u', 'companion-api.service', '--since',
                              '-%ds' % window_s, '--no-pager', '-o', 'cat'],
                             capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    pat = re.compile(r'(?=.*\bPOST\b)(?=.*(?:chat|completion|comics|generate|images?|episodes|gallery|11435))',
                     re.I)
    return any(pat.search(l) for l in log.splitlines())


def _post(path, body):
    req = urllib.request.Request(COMFY + path, json.dumps(body).encode(), {'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=30))


def _workflow(text, seed):
    return {
        '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': CKPT}},
        '2': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': text}},
        '3': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': NEG}},
        '4': {'class_type': 'EmptyLatentImage', 'inputs': {'width': 832, 'height': 960, 'batch_size': 1}},
        '5': {'class_type': 'KSampler', 'inputs': {
            'model': ['1', 0], 'positive': ['2', 0], 'negative': ['3', 0], 'latent_image': ['4', 0],
            'seed': seed, 'steps': 30, 'cfg': 5.5, 'sampler_name': 'dpmpp_2m', 'scheduler': 'karras',
            'denoise': 1.0}},
        '6': {'class_type': 'VAEDecode', 'inputs': {'samples': ['5', 0], 'vae': ['1', 2]}},
        # PreviewImage writes to ComfyUI's temp dir, not the companion app's output gallery
        '7': {'class_type': 'PreviewImage', 'inputs': {'images': ['6', 0]}},
    }


def gen(outdir, n=None, name='pilot'):
    who_list, groups, seed0 = SETS[name]
    raw = os.path.join(outdir, 'raw')
    os.makedirs(raw, exist_ok=True)
    json.dump({'face%02d' % k: g for k, g in enumerate(groups)}, open(os.path.join(outdir, 'groups.json'), 'w'))
    for k, who in enumerate(who_list[:n]):
        dst = os.path.join(raw, 'face%02d.png' % k)
        if os.path.exists(dst):
            continue
        if owner_busy():
            sys.exit('GPU courtesy: companion app active in the last 180 s, stopping')
        pid = _post('/prompt', {'prompt': _workflow(STYLE.format(who=who), seed0 + k)})['prompt_id']
        for _ in range(600):
            time.sleep(1)
            h = json.load(urllib.request.urlopen(COMFY + '/history/' + pid, timeout=30))
            if pid in h and h[pid].get('outputs'):
                img = h[pid]['outputs']['7']['images'][0]
                q = 'filename=%s&subfolder=%s&type=%s' % (img['filename'], img['subfolder'], img['type'])
                open(dst, 'wb').write(urllib.request.urlopen(COMFY + '/view?' + q, timeout=60).read())
                print(dst)
                break
        else:
            sys.exit('timeout on ' + who)
    urllib.request.urlopen(urllib.request.Request(COMFY + '/free', b'{"unload_models": true, "free_memory": true}',
                                                  {'Content-Type': 'application/json'}), timeout=30)


def stock_indices():
    c = set()
    for f in parse_frames(open(STOCK, 'rb').read()):
        c.update(f[5])
    return sorted(c - SKIP)


def quantize(im, pal):
    """48 x 56 RGB image -> palette index bytes. Red-ramp (team colour) indices only for strongly
    saturated red pixels, so skin, lips and background never turn into the team colour."""
    allowed = stock_indices()
    team = [i for i in allowed if i in TEAM]
    other = [i for i in allowed if i not in TEAM and i not in TEAM2]

    def nearest(rgb, cands):
        r, g, b = rgb
        best, bd = None, None
        for i in cands:
            pr, pg, pb = pal[3 * i:3 * i + 3]
            rm = (r + pr) / 2                   # "redmean" weighted RGB distance
            d = (2 + rm / 256) * (r - pr) ** 2 + 4 * (g - pg) ** 2 + (2 + (255 - rm) / 256) * (b - pb) ** 2
            if bd is None or d < bd:
                best, bd = i, d
        return best

    out = bytearray()
    cache = {}
    for k, rgb in enumerate(im.getdata()):
        y = k // W
        band = y < CAP_ROWS or y >= COLLAR_ROW     # face rows never take the team colour
        key = (rgb, band)
        if key not in cache:
            h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
            red = band and (h < 0.03 or h > 0.95) and s > 0.6 and v > 0.25
            cache[key] = nearest(rgb, team if red else other)
        out.append(cache[key])
    return bytes(out)


def build(outdir):
    from PIL import Image, ImageEnhance
    pal = pal_for(SRC, 'DEFAULT')
    fdir = os.path.join(outdir, 'frames')
    os.makedirs(fdir, exist_ok=True)
    tiles = []
    for p in sorted(glob.glob(os.path.join(outdir, 'raw', '*.png'))):
        im = Image.open(p).convert('RGB')
        w, h = im.size                          # 832 x 960 is 6:6.9; crop to exactly 48:56
        cw = min(w, h * W // H)
        ch = cw * H // W
        im = im.crop(((w - cw) // 2, 0, (w - cw) // 2 + cw, ch))
        im = ImageEnhance.Contrast(im.resize((W, H), Image.LANCZOS)).enhance(1.1)
        px = quantize(im, pal)
        cap = sum(1 for k, b in enumerate(px) if k // W < CAP_ROWS and b in TEAM)
        if cap < CAP_MIN:                       # cap would stay gray or brown instead of the team colour
            os.makedirs(os.path.join(outdir, 'rejects'), exist_ok=True)
            open(os.path.join(outdir, 'rejects', os.path.basename(p)[:-4] + '.bin'), 'wb').write(px)
            print('reject %s: %d team pixels in the cap' % (os.path.basename(p), cap))
            stale = os.path.join(fdir, os.path.basename(p)[:-4] + '.bin')
            if os.path.exists(stale):
                os.remove(stale)
            continue
        open(os.path.join(fdir, os.path.basename(p)[:-4] + '.bin'), 'wb').write(px)
        tiles.append(px)
    # preview: row 1 under DEFAULT.PAL (red team), row 2 with the team ramp shown blue
    blue = list(pal)
    for k, i in enumerate(TEAM):
        blue[3 * i:3 * i + 3] = [max(0, 60 - 7 * k), max(0, 90 - 10 * k), max(0, 230 - 22 * k)]
    sheet = Image.new('RGB', (len(tiles) * (W + 4), 2 * (H + 4)), (20, 20, 24))
    for k, px in enumerate(tiles):
        for row, p in enumerate((pal, blue)):
            t = Image.frombytes('P', (W, H), px)
            t.putpalette(p)
            sheet.paste(t.convert('RGB'), (k * (W + 4) + 2, row * (H + 4) + 2))
    sheet.resize((sheet.width * 4, sheet.height * 4), Image.NEAREST).save(os.path.join(outdir, 'pilot_4x.png'))
    print(len(tiles), 'frames ->', fdir)


def append(anm_in, anm_out, bins):
    d = open(anm_in, 'rb').read()
    n = struct.unpack_from('<H', d)[0]
    if len(d) != 2 + n * FRAME_SIZE:
        sys.exit('%s: %d B is not %d raw frames' % (anm_in, len(d), n))
    for p in ('/mnt/nvme/tlrb2/c/', '/mnt/nvme/tlrb2/pristine/'):
        if os.path.abspath(anm_out).startswith(p):
            sys.exit('refusing to write under ' + p)
    grp_in = os.path.join(os.path.dirname(anm_in), 'FACEGRP.DAT')
    grp = bytearray(open(grp_in, 'rb').read() if os.path.exists(grp_in) else STOCK_GROUP)
    if len(grp) != n:
        sys.exit('%s has %d flags for %d faces' % (grp_in, len(grp), n))
    out = bytearray(struct.pack('<H', n + len(bins)) + d[2:])
    for b in bins:
        px = open(b, 'rb').read()
        assert len(px) == W * H, b
        out += FRAME_HDR + px
        gj = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(b))), 'groups.json')
        grp.append(json.load(open(gj))[os.path.basename(b)[:-4]] if os.path.exists(gj) else 0)
    if n + len(bins) > 981:
        sys.exit('BB reads PORTRAIT.ANM only below index 981')
    open(anm_out, 'wb').write(bytes(out))
    open(os.path.join(os.path.dirname(anm_out), 'FACEGRP.DAT'), 'wb').write(bytes(grp))
    print('%s: %d -> %d frames, new ids %d..%d' % (anm_out, n, n + len(bins), n, n + len(bins) - 1))


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['gen']:
        gen(a[1], int(a[2]) if len(a) > 2 else None, a[3] if len(a) > 3 else 'pilot')
    elif a[:1] == ['build']:
        build(a[1])
    elif a[:1] == ['append']:
        append(a[1], a[2], a[3:])
    else:
        sys.exit(__doc__)
