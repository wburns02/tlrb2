#!/usr/bin/env python3
r"""Build a js-dos bundle (.jsdos, a zip) of an installed TLRB2 for the browser build.

usage: build_bundle.py ROOT CD.ISO OUT.jsdos [OVERLAY_DIR ...]

ROOT is the C: drive: it holds TONY2/ (with TONY2.BAT) and anything else the install needs at C:\, e.g. the
empty DYNSNAP/ of a dynasty install. Each overlay has the same layout and is copied over ROOT (e.g. the faces
install, TONY2/ANMS/...). Empty directories are kept. CD.ISO is mounted as D: because the game loads stadiums
only from the CD drive. The autoexec relaunches TONY2.BAT whenever it ends, so QUIT goes back through the BAT loop
(where a dynasty install rolls a finished season) instead of leaving a DOS prompt in the browser. Game files go into
the bundle only, never into the repo.
"""
import os
import sys
import zipfile

CONF = """[sdl]
autolock=false
[dosbox]
machine=svga_s3
memsize=16
[cpu]
core=normal
cycles=20000
[sblaster]
sbtype=sb16
[dos]
xms=true
ems=true
umb=true
[autoexec]
mount c .
imgmount d CD.ISO -t iso
c:
:loop
cd \\TONY2
call TONY2.BAT
goto loop
"""


def files_under(root):
    for d, _, fs in os.walk(root):
        for f in sorted(fs):
            p = os.path.join(d, f)
            yield p, os.path.relpath(p, root)


def dirs_under(root):
    for d, ds, _ in os.walk(root):
        for x in ds:
            yield os.path.relpath(os.path.join(d, x), root).replace(os.sep, '/') + '/'


def build(root, iso, out, overlays=()):
    if not os.path.isfile(os.path.join(root, 'TONY2', 'TONY2.BAT')):
        sys.exit('no TONY2/TONY2.BAT in ' + root)
    entries = {}
    dirs = {'.jsdos/'}
    for top in (root,) + tuple(overlays):
        for p, rel in files_under(top):
            entries[rel.replace(os.sep, '/')] = p
        dirs.update(dirs_under(top))
    with zipfile.ZipFile(out + '.tmp', 'w', zipfile.ZIP_DEFLATED) as z:
        # js-dos extracts with libzip and creates only directories that have their own entry
        for name in entries:
            parts = name.split('/')[:-1]
            dirs.update('/'.join(parts[:i]) + '/' for i in range(1, len(parts) + 1))
        for d in sorted(dirs, key=lambda d: (d.count('/'), d)):
            z.writestr(zipfile.ZipInfo(d), b'')
        z.writestr('.jsdos/dosbox.conf', CONF)
        for name in sorted(entries):
            z.write(entries[name], name)
        z.write(iso, 'CD.ISO')
    os.replace(out + '.tmp', out)
    return len(entries)


if __name__ == '__main__':
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    n = build(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
    print(f'{sys.argv[3]}: {n} game files + CD.ISO, {os.path.getsize(sys.argv[3])} bytes')
