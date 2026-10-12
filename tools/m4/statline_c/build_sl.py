#!/usr/bin/env python3
"""Build the statline parity harness: the host binary sl_host with gcc (always
rebuilt), and the DOS program SLHOST.EXE with OpenWatcom when
/mnt/nvme/tools/openwatcom exists (env WATCOM, wcl -bt=dos -ml). Both include
../statline.h, the C port of tools/m4/statline.py."""
import os
import subprocess


HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, 'SLHOST.EXE')
WATCOM = '/mnt/nvme/tools/openwatcom'

CMD = ['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror',
       '-o', 'sl_host', 'sl_host.c']


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
                        '-k32768', 'sl_host.c', '-fe=SLHOST.EXE'],
                       cwd=HERE, env=env)
    for leftover in ('sl_host.o', 'sl_host.obj', 'sl_host.err'):
        p = os.path.join(HERE, leftover)
        if os.path.exists(p):
            os.remove(p)
    if r.returncode != 0:
        raise SystemExit('wcl failed')
    return EXE


if __name__ == '__main__':
    build_host()
    build_dos()
