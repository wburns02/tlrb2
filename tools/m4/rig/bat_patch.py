#!/usr/bin/env python3
r"""Patch TONY2.BAT to call DYNASTY.EXE before control, with pre-roll backup.

Inserts after `:start` (the current form, contract C5):
  copy TEAMS\CLASSIC\*.* C:\DYNSNAP > NUL
  dynasty
  if errorlevel 1 histwr

Upgrades the previous patched form (the same without the histwr line) in
place. CRLF line endings, idempotent, asserts stock content, refuses
live/pristine paths.
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
    'if errorlevel 1 histwr\r\n'
    'control\r\n'
)

# the previous patched form (no histwr line): upgraded in place by patch()
PATCHED_START_OLD = (
    ':start\r\n'
    'copy TEAMS\\CLASSIC\\*.* C:\\DYNSNAP > NUL\r\n'
    'dynasty\r\n'
    'control\r\n'
)

# Will's live install, the pristine copy, and the shared work install are never patched
REFUSE = ('/mnt/nvme/tlrb2/c/', '/mnt/nvme/tlrb2/pristine/', '/mnt/nvme/tlrb2/work/c/')


def patch(install_root, revert=False):
    """Apply, upgrade, or revert patch. Refuses /mnt/nvme/tlrb2/c or pristine."""
    install_root = os.path.realpath(install_root)
    if any((install_root + '/').startswith(p) for p in REFUSE):
        print(f"ERROR: refusing to patch {install_root}", file=sys.stderr)
        return False

    bat_path = os.path.join(install_root, 'TONY2.BAT')
    # C:\\DYNSNAP is at the drive root, the parent of the install dir
    dynsnap_path = os.path.join(os.path.dirname(install_root), 'DYNSNAP')

    if not os.path.isfile(bat_path):
        print(f"ERROR: {bat_path} not found", file=sys.stderr)
        return False

    with open(bat_path, 'rb') as f:
        content = f.read().decode('cp437')

    if revert:
        if PATCHED_START not in content and PATCHED_START_OLD not in content:
            print("Already reverted or never patched", file=sys.stderr)
            return True
        content = content.replace(PATCHED_START, STOCK_START)
        content = content.replace(PATCHED_START_OLD, STOCK_START)
    else:
        if PATCHED_START in content:
            print("Already patched", file=sys.stderr)
            return True
        if PATCHED_START_OLD in content:
            # upgrade the previous form: add the histwr line in place
            content = content.replace(PATCHED_START_OLD, PATCHED_START)
        elif STOCK_START in content:
            content = content.replace(STOCK_START, PATCHED_START)
        else:
            print(f"ERROR: stock :start pattern not found in {bat_path}", file=sys.stderr)
            return False
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
