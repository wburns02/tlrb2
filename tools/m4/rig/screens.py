#!/usr/bin/env python3
"""Screen identification for the dynasty driver.

Most screens are told apart by OCR keywords (normed, see rig.norm, so 'JULY' reads 'JVIY'). Two screens carry no
readable text and use a pixel reference instead: the World Series ring (full-screen art) and the DH dialog. The
reference shots live under logs/t6/refs (game-derived, never in the repo).
"""
import os

from PIL import Image

import rig

REFS = '/mnt/nvme/tlrb2/logs/t6/refs'

# name: (ref file, root-coords box, max mean abs diff)
PIX = {
    'ring': ('ring.png', (200, 215, 820, 330), 8.0),
    'dh_dialog': ('dh_dialog.png', (430, 342, 585, 440), 6.0),  # the injury dialog covers this part
}

# (name, alternatives): a screen matches when every word of one alternative is present. Checked in order, so the
# dialogs come before the screens they sit on.
WORDS = [
    ('allstar_dialog', [{'JVIY'}]),
    ('destroy_dialog', [{'DESTRDY'}]),
    ('injury_dialog', [{'DCCVR'}, {'DVRING', 'TNE'}]),
    ('dos_prompt', [{'VERSIDN', 'PATCN'}]),
    ('ball_menu', [{'DRAPT', 'CREDITS'}]),
    ('play_std', [{'STANDARD', 'GAMES'}]),
    ('new_season', [{'NVMEER', 'IEAGVES', 'SAVE'}]),
    ('standings', [{'SEATTIE'}, {'TDRDNTD'}, {'DETRDIT'}]),
]

_refs = {}


def pixel_diff(a, b):
    """Mean abs difference of two same-mode images; a size mismatch counts as a total miss."""
    import numpy as np
    if a.size != b.size:
        return 1e9
    return float(np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).mean())


def _ref(name):
    if name not in _refs:
        f, box, _ = PIX[name]
        p = os.path.join(REFS, f)
        _refs[name] = Image.open(p).convert('RGB').crop(box) if os.path.exists(p) else None
    return _refs[name]


def by_pixels(img):
    for name, (_, box, tol) in PIX.items():
        r = _ref(name)
        if r is not None and pixel_diff(img.crop(box), r) < tol:
            return name
    return None


def by_words(ws):
    present = {w[1] for w in ws}
    for name, alts in WORDS:
        if any(alt <= present for alt in alts):
            return name
    return None


def identify(img=None):
    """(state name or 'unknown', normed word set) for a root screenshot."""
    if img is None:
        rig.park()
        img = rig.shot()
    name = by_pixels(img)
    ws = rig.words(img)
    return (name or by_words(ws) or 'unknown'), {w[1] for w in ws}


SEASON_OVER = ('season_over.png', (393, 520, 538, 536), 6.0)


def season_over(img=None):
    """PLAY STANDARD GAMES with "PLAY ALL GAMES TO" set to SEASON OVER (gray highlight, OCR cannot read it)."""
    if img is None:
        rig.park()
        img = rig.shot()
    f, box, tol = SEASON_OVER
    if 'season_over' not in _refs:
        _refs['season_over'] = Image.open(os.path.join(REFS, f)).convert('RGB').crop(box)
    return pixel_diff(img.crop(box), _refs['season_over']) < tol
