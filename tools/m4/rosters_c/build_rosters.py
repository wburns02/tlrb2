#!/usr/bin/env python3
"""Build ROSTERS: the host binary tools/m4/rosters_c/rosters_host with gcc
(always rebuilt), and the DOS program tools/m4/rosters_c/ROSTERS.EXE with
OpenWatcom when /mnt/nvme/tools/openwatcom exists (env WATCOM, wcl -bt=dos
-ml -0 -os)."""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, 'ROSTERS.EXE')
WATCOM = '/mnt/nvme/tools/openwatcom'

CMD = ['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror',
       '-o', 'rosters_host', 'rosters.c']


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
                        '-k32768', 'rosters.c', '-fe=ROSTERS.EXE'],
                       cwd=HERE, env=env)
    for leftover in ('rosters.o', 'rosters.obj', 'rosters.err'):
        p = os.path.join(HERE, leftover)
        if os.path.exists(p):
            os.remove(p)
    if r.returncode != 0:
        raise SystemExit('wcl failed')
    return EXE


if __name__ == '__main__':
    build_host()
    build_dos()
