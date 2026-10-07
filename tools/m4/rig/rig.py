#!/usr/bin/env python3
"""Low-level rig access for the dynasty driver: screenshots, OCR, long presses, keys on Xvfb :98.

Coordinates are root-window coords on :98. The DOSBox-X game area is 640x400 at GAME_X, GAME_Y.
OCR reads the game font with stable confusions (P->F, N->H, D->O, S->5), so word lookups go through norm().
"""
import os
import subprocess
import time

from PIL import Image, ImageOps
import pytesseract

DISPLAY = ':98'
GAME_X, GAME_Y, GAME_W, GAME_H = 192, 201, 640, 400
SHOTS = '/mnt/nvme/tlrb2/logs/t6/shots'
ENV = dict(os.environ, DISPLAY=DISPLAY)
ENV.pop('WAYLAND_DISPLAY', None)

_CONFUSE = str.maketrans({'F': 'P', 'H': 'N', 'O': 'D', '0': 'D', '5': 'S', '1': 'I', 'L': 'I', '|': 'I',
                          '8': 'B', 'Q': 'D', 'U': 'V'})


def norm(s):
    """Uppercase, keep letters/digits, fold the font's OCR confusions onto one letter each."""
    return ''.join(c for c in s.upper() if c.isalnum()).translate(_CONFUSE)


def _x(*args):
    return subprocess.run(['xdotool', *args], env=ENV, capture_output=True, text=True).stdout.strip()


def window():
    w = _x('search', '--name', 'cycles/ms')
    return w.splitlines()[0] if w else None


def focus():
    w = window()
    if w:
        _x('windowfocus', '--sync', w)
    return w


def shot(name=None):
    """Full root screenshot as a PIL image; saved under SHOTS when name is given."""
    raw = subprocess.run(['import', '-window', 'root', 'png:-'], env=ENV, capture_output=True).stdout
    from io import BytesIO
    img = Image.open(BytesIO(raw)).convert('RGB')
    if name:
        os.makedirs(SHOTS, exist_ok=True)
        img.save(os.path.join(SHOTS, name + '.png'))
    return img


def game(img):
    return img.crop((GAME_X, GAME_Y, GAME_X + GAME_W, GAME_Y + GAME_H))


def words(img=None, scale=3):
    """OCR the game area. Returns [(raw_text, normed, cx, cy)] in root coords, one per word, plus one per
    line (joined words) so multi-word labels can be matched as a unit."""
    img = img or shot()
    g = game(img)
    out = []
    for invert in (False, True):
        gi = ImageOps.grayscale(g)
        if invert:
            gi = ImageOps.invert(gi)
        gi = gi.resize((GAME_W * scale, GAME_H * scale), Image.NEAREST)
        d = pytesseract.image_to_data(gi, config='--psm 11', output_type=pytesseract.Output.DICT)
        for i, t in enumerate(d['text']):
            if not t.strip() or int(float(d['conf'][i])) < 30:
                continue
            cx = GAME_X + (d['left'][i] + d['width'][i] / 2) / scale
            cy = GAME_Y + (d['top'][i] + d['height'][i] / 2) / scale
            out.append((t, norm(t), int(cx), int(cy)))
    return out


def text(img=None):
    """All normed OCR words joined, for screen identification."""
    return ' '.join(w[1] for w in words(img))


def find(label, img=None, ws=None, cutoff=0.6):
    """Center (x, y) of the OCR word (or run of adjacent words on one line) that best matches label, fuzzy,
    else None. Matching is on normed text with difflib ratio >= cutoff."""
    import difflib
    key = norm(label)
    ws = ws if ws is not None else words(img)
    best, at = 0.0, None
    nwords = len(label.split())
    for i in range(len(ws)):
        run = [ws[i]]
        for j in range(i + 1, min(len(ws), i + nwords)):
            if abs(ws[j][3] - ws[i][3]) > 4:
                break
            run.append(ws[j])
        cand = ''.join(w[1] for w in run)
        if not key or abs(len(cand) - len(key)) > max(1, len(key) // 3):
            continue
        r = difflib.SequenceMatcher(None, key, cand).ratio()
        if r > best:
            best = r
            at = (sum(w[2] for w in run) // len(run), run[0][3])
    return at if best >= cutoff else None


def press(x, y, hold=0.5):
    """Long press: the game polls button state per frame, short clicks get lost."""
    focus()
    _x('mousemove', str(x), str(y))
    time.sleep(0.2)
    _x('mousedown', '1')
    time.sleep(hold)
    _x('mouseup', '1')


def menu(x, y, ix, iy):
    """Menu bar: press on the title, drag to the item, release."""
    focus()
    _x('mousemove', str(x), str(y))
    time.sleep(0.3)
    _x('mousedown', '1')
    time.sleep(0.8)
    _x('mousemove', str(ix), str(iy))
    time.sleep(0.5)
    _x('mouseup', '1')


def key(k):
    w = focus()
    if w:
        _x('key', '--window', w, k)
    else:
        _x('key', k)


def same(a, b, box=None, tol=2.0):
    """Mean abs pixel difference of two shots (optionally a root-coords box) below tol."""
    if box:
        a, b = a.crop(box), b.crop(box)
    import numpy as np
    return float(np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).mean()) < tol


def type_text(s, delay=120):
    """Type at the DOS prompt (per-key delay: DOSBox drops fast keystrokes). Focus plus plain typing:
    events sent with --window are synthetic and DOSBox-X ignores them."""
    focus()
    _x('type', '--delay', str(delay), s)


def park():
    """Move the pointer off the game area so it cannot overlap a reference crop."""
    _x('mousemove', '1010', '750')
