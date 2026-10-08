#!/usr/bin/env python3
r"""Patch TONY2.BAT to run the dynasty programs before control (contract C7).

Replaces the stock `:start` / `control` with:
  :start
  copy TEAMS\CLASSIC\*.* C:\DYNSNAP > NUL
  dynasty
  if errorlevel 1 goto rolled
  goto ctl
  :rolled
  histwr
  rosters
  dynview /review
  :ctl
  control

Every earlier patched form (C5 with and without the histwr line) upgrades in
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
    'if errorlevel 1 goto rolled\r\n'
    'goto ctl\r\n'
    ':rolled\r\n'
    'histwr\r\n'
    'rosters\r\n'
    'dynview /review\r\n'
    ':ctl\r\n'
    'control\r\n'
)

# earlier patched forms, newest first: upgraded in place by patch()
EARLIER_FORMS = (
    (':start\r\n'
     'copy TEAMS\\CLASSIC\\*.* C:\\DYNSNAP > NUL\r\n'
     'dynasty\r\n'
     'if errorlevel 1 histwr\r\n'
     'control\r\n'),
    (':start\r\n'
     'copy TEAMS\\CLASSIC\\*.* C:\\DYNSNAP > NUL\r\n'
     'dynasty\r\n'
     'control\r\n'),
)
PATCHED_START_OLD = EARLIER_FORMS[-1]

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
        forms = (PATCHED_START,) + EARLIER_FORMS
        if not any(f in content for f in forms):
            print("Already reverted or never patched", file=sys.stderr)
            return True
        for f in forms:
            content = content.replace(f, STOCK_START)
    else:
        if PATCHED_START in content:
            print("Already patched", file=sys.stderr)
            return True
        for f in EARLIER_FORMS:
            if f in content:
                content = content.replace(f, PATCHED_START)
                break
        else:
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
