#!/usr/bin/env python3
r"""Patch TONY2.BAT to run the dynasty programs before control (contract C7).

Replaces the stock `:start` / `control` with:
  :start
  copy TEAMS\CLASSIC\*.* C:\DYNSNAP > NUL
  dynasty
  if errorlevel 1 goto rolled
  goto ctl
  :rolled
  call archive
  histwr
  rosters
  dynview /offseason
  :ctl
  control

and, when the stock `:frontend` / `play` is present, runs the DYNASTY MODE screen at boot:
  :frontend
  dynview /title
  play

and routes the DYNASTY menu-bar picks (menu_patch.py, CONTROL errorlevels 8..11) ahead of the stock
`if errorlevel 7 goto end`:
  if errorlevel 10 goto dynmenu
  if errorlevel 9 goto create
  if errorlevel 8 goto dynmenu
with `:dynmenu` / `dynview /menu` / `goto start` and `:create` / `create` / `goto start` placed
after the stock `goto frontend`.

Every earlier patched form (C5 with and without the histwr line, C7 with
dynview /review, any form without the boot screen) upgrades in place. CRLF line endings, idempotent, asserts stock content, refuses
live/pristine paths. Also writes ARCHIVE.BAT next to TONY2.BAT: it copies the finished season (the
pre-roll snapshot in C:\DYNSNAP) to the first free C:\SEASONS\Snn, so a new season never destroys the old one.
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
    'call archive\r\n'
    'histwr\r\n'
    'rosters\r\n'
    'dynview /offseason\r\n'
    ':ctl\r\n'
    'control\r\n'
)

STOCK_FRONTEND = ':frontend\r\nplay\r\n'
PATCHED_FRONTEND = ':frontend\r\ndynview /title\r\nplay\r\n'

# the DYNASTY menu (menu_patch.py): CONTROL exits 8 + item; 8, 10 and 11 run DYNVIEW (it reads
# CONTROL[1] for the screen), 9 runs CREATE; both hand CONTROL[1] back to the caller
STOCK_ROUTES = 'if errorlevel 7 goto end\r\n'
PATCHED_ROUTES = ('if errorlevel 10 goto dynmenu\r\n'
                  'if errorlevel 9 goto create\r\n'
                  'if errorlevel 8 goto dynmenu\r\n'
                  'if errorlevel 7 goto end\r\n')
STOCK_LABELS = 'goto frontend\r\n\r\n:draft\r\n'
PATCHED_LABELS = ('goto frontend\r\n\r\n'
                  ':dynmenu\r\ndynview /menu\r\ngoto start\r\n\r\n'
                  ':create\r\ncreate\r\ngoto start\r\n\r\n'
                  ':draft\r\n')

# earlier patched forms, newest first: upgraded in place by patch()
EARLIER_FORMS = (
    (':start\r\n'
     'copy TEAMS\\CLASSIC\\*.* C:\\DYNSNAP > NUL\r\n'
     'dynasty\r\n'
     'if errorlevel 1 goto rolled\r\n'
     'goto ctl\r\n'
     ':rolled\r\n'
     'call archive\r\n'
     'histwr\r\n'
     'rosters\r\n'
     'dynview /review\r\n'
     ':ctl\r\n'
     'control\r\n'),
    (':start\r\n'
     'copy TEAMS\\CLASSIC\\*.* C:\\DYNSNAP > NUL\r\n'
     'dynasty\r\n'
     'if errorlevel 1 goto rolled\r\n'
     'goto ctl\r\n'
     ':rolled\r\n'
     'histwr\r\n'
     'rosters\r\n'
     'dynview /review\r\n'
     ':ctl\r\n'
     'control\r\n'),
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

ARCHIVE_SLOTS = 99


def archive_bat(slots=ARCHIVE_SLOTS):
    """ARCHIVE.BAT text (CRLF): copy C:\\DYNSNAP to the first C:\\SEASONS\\Snn without a CLASSIC.MAJ."""
    lines = ['@echo off', 'if not exist C:\\SEASONS\\NUL md C:\\SEASONS']
    names = ['S%02d' % i for i in range(1, slots + 1)]
    lines += [f'if not exist C:\\SEASONS\\{n}\\CLASSIC.MAJ goto {n}' for n in names]
    lines.append('goto done')
    for n in names:
        lines += [f':{n}', f'if not exist C:\\SEASONS\\{n}\\NUL md C:\\SEASONS\\{n}',
                  f'copy C:\\DYNSNAP\\*.* C:\\SEASONS\\{n} > NUL', 'goto done']
    lines.append(':done')
    return '\r\n'.join(lines) + '\r\n'


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
        if not any(f in content for f in forms + (PATCHED_FRONTEND, PATCHED_ROUTES, PATCHED_LABELS)):
            print("Already reverted or never patched", file=sys.stderr)
            return True
        for f in forms:
            content = content.replace(f, STOCK_START)
        content = content.replace(PATCHED_FRONTEND, STOCK_FRONTEND)
        content = content.replace(PATCHED_ROUTES, STOCK_ROUTES)
        content = content.replace(PATCHED_LABELS, STOCK_LABELS)
    else:
        # the menu routes and their labels go in together or not at all (a goto to a missing
        # label ends the batch); a BAT with neither (the synthetic test BATs) skips them
        has_routes = PATCHED_ROUTES in content or STOCK_ROUTES in content
        has_labels = PATCHED_LABELS in content or STOCK_LABELS in content
        if has_routes != has_labels:
            print(f"ERROR: menu routes and labels not both present in {bat_path}", file=sys.stderr)
            return False
        todo = [(st, new) for st, new in ((STOCK_ROUTES, PATCHED_ROUTES), (STOCK_LABELS, PATCHED_LABELS))
                if has_routes and new not in content]
        if PATCHED_START in content and STOCK_FRONTEND not in content and not todo:
            print("Already patched", file=sys.stderr)
            return True
        content = content.replace(STOCK_FRONTEND, PATCHED_FRONTEND)
        for stock, new in todo:
            if content.count(stock) != 1:
                print(f"ERROR: stock {stock!r} not found once in {bat_path}", file=sys.stderr)
                return False
            content = content.replace(stock, new)
        if PATCHED_START not in content:
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
    arch = os.path.join(install_root, 'ARCHIVE.BAT')
    if revert:
        if os.path.exists(arch):
            os.remove(arch)
    else:
        with open(arch, 'wb') as f:
            f.write(archive_bat().encode('cp437'))

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
