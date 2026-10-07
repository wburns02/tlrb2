#!/usr/bin/env python3
"""Patch TONY2.BAT to call DYNASTY.EXE before control, with pre-roll backup.

Inserts after `:start`:
  copy TEAMS\CLASSIC\*.* C:\DYNSNAP > NUL
  dynasty

CRLF line endings, idempotent, asserts stock content, refuses live/pristine paths.
Usage:
  bat_patch.py INSTALL_ROOT [--revert]
"""
import sys
import os


STOCK_START = (
    ':start\r\n'
    'control\r\n'
)

PATCHED_START = (
    ':start\r\n'
    'copy TEAMS\\CLASSIC\\*.* C:\\DYNSNAP > NUL\r\n'
    'dynasty\r\n'
    'control\r\n'
)

PATCH_LINES = [
    'copy TEAMS\\CLASSIC\\*.* C:\\DYNSNAP > NUL\r\n',
    'dynasty\r\n',
]


def patch(install_root, revert=False):
    """Apply or revert patch. Refuses /mnt/nvme/tlrb2/c or pristine."""
    install_root = os.path.abspath(install_root)
    if 'tlrb2/c' in install_root or 'pristine' in install_root:
        print(f"ERROR: refusing to patch {install_root}", file=sys.stderr)
        return False

    bat_path = os.path.join(install_root, 'TONY2.BAT')
    dynsnap_path = os.path.join(install_root, 'DYNSNAP')

    if not os.path.isfile(bat_path):
        print(f"ERROR: {bat_path} not found", file=sys.stderr)
        return False

    with open(bat_path, 'rb') as f:
        content = f.read().decode('cp437')

    if revert:
        if PATCHED_START not in content:
            print("Already reverted or never patched", file=sys.stderr)
            return True
        content = content.replace(PATCHED_START, STOCK_START)
    else:
        if PATCHED_START in content:
            print("Already patched", file=sys.stderr)
            return True
        if STOCK_START not in content:
            print(f"ERROR: stock :start pattern not found in {bat_path}", file=sys.stderr)
            return False
        content = content.replace(STOCK_START, PATCHED_START)
        os.makedirs(dynsnap_path, exist_ok=True)

    with open(bat_path, 'wb') as f:
        f.write(content.encode('cp437'))

    return True


def main(args):
    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    install_root = args[0]
    revert = '--revert' in args
    if not patch(install_root, revert):
        sys.exit(1)


if __name__ == '__main__':
    main(sys.argv[1:])
