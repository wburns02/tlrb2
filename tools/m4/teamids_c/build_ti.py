#!/usr/bin/env python3
"""Build the teamids and realign parity harness: the host binary ti_host with gcc (always
rebuilt), and the DOS program TIHOST.EXE with OpenWatcom when /mnt/nvme/tools/openwatcom
exists (env WATCOM, wcl -bt=dos -ml). Both include ../teamids.h and ../realign.h, the C
ports of tools/m4/teamids.py and tools/m4/realign.py."""
import os
import subprocess


HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, 'TIHOST.EXE')
WATCOM = '/mnt/nvme/tools/openwatcom'

CMD = ['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror',
       '-o', 'ti_host', 'ti_host.c']


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
                        '-k32768', 'ti_host.c', '-fe=TIHOST.EXE'],
                       cwd=HERE, env=env)
    for leftover in ('ti_host.o', 'ti_host.obj', 'ti_host.err'):
        p = os.path.join(HERE, leftover)
        if os.path.exists(p):
            os.remove(p)
    if r.returncode != 0:
        raise SystemExit('wcl failed')
    return EXE


if __name__ == '__main__':
    build_host()
    build_dos()
