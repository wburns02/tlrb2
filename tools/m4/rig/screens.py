#!/usr/bin/env python3
"""Screen identification from screenshots via pixel diff against reference crops.

Capture refs manually on the rig; store under /mnt/nvme/tlrb2/logs/t6/refs/
Matches by mean absolute pixel difference with threshold; returns best match name.
"""
import os
import subprocess
from pathlib import Path
from PIL import Image
import numpy as np


REFS_DIR = Path('/mnt/nvme/tlrb2/logs/t6/refs')
THRESHOLD = 15.0


def screenshot(display=':98', path=None):
    """Capture root window. Return PIL Image or path."""
    if path is None:
        path = '/tmp/screen.png'
    subprocess.run(
        ['import', '-window', 'root', path],
        env={'DISPLAY': display},
        check=True
    )
    return Image.open(path)


def crop_image(img, box):
    """Crop image to (x1, y1, x2, y2)."""
    return img.crop(box)


def pixel_diff(img_a, img_b):
    """Mean absolute difference between two images (converted to grayscale)."""
    a = np.array(img_a.convert('L')).astype(float)
    b = np.array(img_b.convert('L')).astype(float)
    if a.shape != b.shape:
        return 1000.0
    return np.mean(np.abs(a - b))


def identify_screen(screenshot_path, display=':98', verbose=False):
    """Match screenshot against refs. Return (state_name, confidence)."""
    if not REFS_DIR.exists():
        return 'unknown', 0.0

    img = Image.open(screenshot_path)
    best_name = 'unknown'
    best_score = 1000.0

    for ref_file in sorted(REFS_DIR.glob('*.png')):
        state_name = ref_file.stem
        ref = Image.open(ref_file)

        # Exact size match only
        if ref.size != img.size:
            if verbose:
                print(f"  {state_name}: size mismatch {ref.size} vs {img.size}", flush=True)
            continue

        diff = pixel_diff(img, ref)
        if verbose:
            print(f"  {state_name}: diff={diff:.1f}", flush=True)

        if diff < best_score:
            best_score = diff
            best_name = state_name

    confidence = 100.0 - min(100.0, best_score)
    return best_name if best_score < THRESHOLD else 'unknown', confidence


def capture_ref(name, display=':98'):
    """Manually capture a reference crop. Stores as refs/NAME.png."""
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    path = REFS_DIR / f'{name}.png'
    screenshot(display, str(path))
    print(f"Captured {path}")
