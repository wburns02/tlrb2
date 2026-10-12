#!/usr/bin/env python3
"""Build the league harness: the host binary tools/m4/league_c/lg_host with gcc (always rebuilt). It
includes ../league.h, the C port of tools/m4/league.py (contract C16.1). The DOS users of league.h
(HISTWR, ROSTERS, CREATE) are built by their own build scripts."""
import os
import subprocess


HERE = os.path.dirname(os.path.abspath(__file__))

CMD = ['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror',
       '-o', 'lg_host', 'lg_host.c']


def build_host():
    subprocess.run(CMD, check=True, cwd=HERE)


if __name__ == '__main__':
    build_host()
