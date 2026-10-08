#!/usr/bin/env python3
"""Build DYNVIEW: the host binary tools/m4/dynview_c/dynview_host with gcc
(always rebuilt), and the DOS program tools/m4/dynview_c/DYNVIEW.EXE with
OpenWatcom when /mnt/nvme/tools/openwatcom exists (env WATCOM, wcl -bt=dos -ml)."""
import os
import subprocess


HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, 'DYNVIEW.EXE')
WATCOM = '/mnt/nvme/tools/openwatcom'

CMD = ['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror',
       '-o', 'dynview_host', 'dynview.c']


def build_host():
    subprocess.run(CMD, check=True, cwd=HERE)


def build_dos():
    if not os.path.isdir(WATCOM):
        return None
    env = dict(os.environ)
    env['WATCOM'] = WATCOM
    env['PATH'] = os.path.join(WATCOM, 'binl64') + os.pathsep + env.get('PATH', '')
    env['INCLUDE'] = os.path.join(WATCOM, 'h')
    r = subprocess.run(['wcl', '-q', '-bt=dos', '-ml', '-0', '-os', '-wx', '-we',
                        '-k32768', 'dynview.c', '-fe=DYNVIEW.EXE'],
                       cwd=HERE, env=env)
    for leftover in ('dynview.o', 'dynview.obj', 'dynview.err'):
        p = os.path.join(HERE, leftover)
        if os.path.exists(p):
            os.remove(p)
    if r.returncode != 0:
        raise SystemExit('wcl failed')
    return EXE


if __name__ == '__main__':
    build_host()
    build_dos()
