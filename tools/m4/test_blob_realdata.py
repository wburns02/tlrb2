#!/usr/bin/env python3
"""P1 gate as a test: the 16-bit blob vs tools/m4/rollover.py on the REAL
completed m3_end season (all 28 league files, all 40 players each).

The synthetic fixtures in test_blob_unicorn.py masked the t_hitrun register
clobber class; real season stats catch it. Run:
    cd ~/tlrb2 && python3 -m pytest tools/m4/test_blob_realdata.py -q
"""
import os
import struct
import sys

sys.path.insert(0, '/home/will/tlrb2/tools')
sys.path.insert(0, '/home/will/tlrb2/tools/m4')

import pytest
from unicorn import *
from unicorn.x86_const import *

import rollover
from v20 import Team, F

BLOB = '/mnt/nvme/tlrb2/work/m4/blob/rollover.bin'
M3_DIR = '/mnt/nvme/tlrb2/snaps/m3_end/TEAMS/CLASSIC'

Uc.__enter__ = lambda self: self
Uc.__exit__ = lambda self, *args: False

ENTRY = 0x10
SEG_ROSTER = 0x2000
SEG_SEASON = 0x2000
SEG_RNG = 0x3000
SEG_STACK = 0x7000
PHYS_BLOB = 0x10000
PHYS_ROSTER = 0x20000
PHYS_SEASON = 0x20100
PHYS_RNG = 0x30000
PHYS_STACK = 0x70000
PHYS_SENTINEL = 0xF0000


def emu_pair(uc, roster_in, season_in, rng_state, flags=1):
    """Roll one player pair in the live Uc; returns (ax, roster, season)."""
    uc.mem_write(PHYS_ROSTER, bytes(roster_in))
    uc.mem_write(PHYS_SEASON, bytes(season_in))
    uc.mem_write(PHYS_RNG, struct.pack('<H', rng_state))
    uc.reg_write(UC_X86_REG_CX, flags)
    uc.reg_write(UC_X86_REG_CS, 0x1000)     # the previous retf left CS = 0xF000
    uc.reg_write(UC_X86_REG_EIP, PHYS_BLOB + ENTRY)
    try:
        uc.emu_start(PHYS_BLOB + ENTRY, 0)
    except UcError as e:
        if e.errno != UC_ERR_EXCEPTION:
            raise
    ax = uc.reg_read(UC_X86_REG_AX)
    return ax, bytes(uc.mem_read(PHYS_ROSTER, 143)), bytes(uc.mem_read(PHYS_SEASON, 143))


@pytest.mark.skipif(not os.path.exists(BLOB), reason='blob not built')
@pytest.mark.skipif(not os.path.isdir(M3_DIR), reason='m3_end snapshot missing')
def test_real_season_blob_matches_reference():
    blob = open(BLOB, 'rb').read()
    teams = sorted(f for f in os.listdir(M3_DIR) if f.endswith('.V20'))
    assert len(teams) == 28
    mismatches = []
    checked = 0
    with Uc(UC_ARCH_X86, UC_MODE_16) as uc:
        uc.mem_map(0x00000, 0x100000)
        uc.mem_write(PHYS_BLOB, blob)
        uc.mem_write(PHYS_STACK + 0x7FFC, b'\x00\x00')
        uc.mem_write(PHYS_STACK + 0x7FFE, b'\x00\xF0')
        uc.mem_write(PHYS_SENTINEL, b'\xF4')
        uc.reg_write(UC_X86_REG_CS, 0x1000)
        uc.reg_write(UC_X86_REG_DS, SEG_ROSTER)
        uc.reg_write(UC_X86_REG_ES, SEG_SEASON)
        uc.reg_write(UC_X86_REG_FS, SEG_RNG)
        uc.reg_write(UC_X86_REG_SS, SEG_STACK)
        uc.reg_write(UC_X86_REG_SI, 0)
        uc.reg_write(UC_X86_REG_DI, 0x100)
        uc.reg_write(UC_X86_REG_BX, 0)
        uc.reg_write(UC_X86_REG_SP, 0x7FFC)
        for ti, name in enumerate(teams):
            t = Team.load(os.path.join(M3_DIR, name))
            for i in range(40):
                roster = bytearray(t.players[i].raw)
                season = bytearray(t.players[i + 40].raw)
                if roster[0] == 0 and season[0] == 0:
                    continue
                rng = rollover.Rng((ti * 40 + i) * 2654435761 & 0xFFFF or 1)
                r_in, s_in = bytearray(roster), bytearray(season)
                rng_state0 = rng.s          # pre-reference state for the blob
                ref_ret = rollover.rollover_player(roster, season,
                                                   {'progress': True, 'retire': True},
                                                   rng, None)
                # mirror the team-level twin semantics the same way the harness does
                for f in ('age', 'year_off', 'exp'):
                    season[F[f][0]] = roster[F[f][0]]
                if ref_ret:
                    roster[0] = 0
                    season[0] = 0
                try:
                    ax, r_got, s_got = emu_pair(uc, r_in, s_in, rng_state0, 3)
                except UcError as e:
                    mismatches.append(f'{name}#{i}: EMU FAIL {e}')
                    continue
                checked += 1
                if ax != (1 if ref_ret else 0):
                    mismatches.append(f'{name}#{i}: AX {ax} != {ref_ret}')
                if r_got != bytes(roster):
                    d = [k for k in range(143) if r_got[k] != roster[k]]
                    mismatches.append(f'{name}#{i}: roster bytes {d[:6]}')
                if s_got != bytes(season):
                    d = [k for k in range(143) if s_got[k] != season[k]]
                    mismatches.append(f'{name}#{i}: season bytes {d[:6]}')
    assert not mismatches, f'{len(mismatches)} mismatches over {checked} players: ' \
        + '; '.join(mismatches[:10])


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
