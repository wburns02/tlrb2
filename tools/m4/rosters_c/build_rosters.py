#!/usr/bin/env python3
"""Build ROSTERS: the host binary tools/m4/rosters_c/rosters_host with gcc
(always rebuilt), and the DOS program tools/m4/rosters_c/ROSTERS.EXE with
OpenWatcom when /mnt/nvme/tools/openwatcom exists: a 32-bit program with the
DOS/32A extender bound in as its stub (wcl386 -l=dos32a). A 16-bit large-model
build ran out of conventional memory on a mature league (28 team images plus
570 market moves is over 640 KB), so the DOS build is 32-bit."""
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
    # binw holds dos32a.exe, the stub wlink binds in
    env['PATH'] = (os.path.join(WATCOM, 'binl64') + os.pathsep
                   + os.path.join(WATCOM, 'binw') + os.pathsep + env.get('PATH', ''))
    env['INCLUDE'] = os.path.join(WATCOM, 'h')
    r = subprocess.run(['wcl386', '-q', '-bt=dos', '-l=dos32a', '-os', '-wx', '-we',
                        '-k65536', 'rosters.c', '-fe=ROSTERS.EXE'],
                       cwd=HERE, env=env)
    for leftover in ('rosters.o', 'rosters.obj', 'rosters.err'):
        p = os.path.join(HERE, leftover)
        if os.path.exists(p):
            os.remove(p)
    if r.returncode != 0:
        raise SystemExit('wcl386 failed')
    return EXE


if __name__ == '__main__':
    build_host()
    build_dos()
