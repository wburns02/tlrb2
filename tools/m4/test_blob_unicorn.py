import sys
import os
import struct
import pytest
from unicorn import *
from unicorn.x86_const import *

# Add the tools directory to path for rollover module
sys.path.insert(0, '/home/will/tlrb2/tools')
sys.path.insert(0, '/home/will/tlrb2/tools/m4')

from v20 import Team, F, _get, _set
import rollover

BLOB = '/mnt/nvme/tlrb2/work/m4/blob/rollover.bin'

# this unicorn binding constructs UcIntel instances (subclassing Uc returns the
# parent type), so add the context-manager methods to the class itself
Uc.__enter__ = lambda self: self
Uc.__exit__ = lambda self, *args: False

PRISTINE = '/mnt/nvme/tlrb2/pristine/TONY2/TEAMS/CLASSIC/CLASALE1.V20'

# Constants
ENTRY_ROLL_PLAYER = 0x10
SEGMENT_ROSTER = 0x2000
SEGMENT_SEASON = 0x2000
SEGMENT_RNG = 0x3000
SEGMENT_STACK = 0x7000
OFFSET_ROSTER = 0x0000
OFFSET_SEASON = 0x100
OFFSET_RNG = 0x0000
OFFSET_STACK = 0x7FFC
PHYSICAL_BLOB = 0x10000
PHYSICAL_ROSTER = 0x20000
PHYSICAL_SEASON = 0x20100
PHYSICAL_RNG = 0x30000
PHYSICAL_STACK = 0x70000
PHYSICAL_SENTINEL = 0xF0000

# Field offsets and sizes (local spec dict; v20.F is the authoritative table)
OFFS = {
    'age': (20, 1),
    'year_off': (21, 1),
    'exp': (22, 1),
    'games': (23, 1),
    'pos1': (29, 1),
    'endurance': (135, 1),
    'arm': (94, 1),
    'ab_l': (37, 2)
}

def build_pair(spec):
    # Load pristine team
    team = Team.load(PRISTINE)
    roster = bytearray(team.players[0].raw)
    season = bytearray(143)
    
    # Copy roster to season with some modifications
    for i in range(143):
        season[i] = roster[i]
        
    # Set up season stats based on roster values
    for name in rollover.STAT_FIELDS:
        if name in ('age', 'year_off', 'exp'):
            continue  # These are handled specially
        field = F[name]      # v20.F (STAT_FIELDS names all exist there)
        if field[1] == 'u8':
            value = min(255, roster[field[0]] // 8)
        elif field[1] == 'u16':
            value = min(65535, (roster[field[0]] << 8) | roster[field[0]+1] // 8)
        else:
            continue
        if field[1] == 'u8':
            season[field[0]] = value
        else:
            season[field[0]] = value >> 8
            season[field[0]+1] = value & 0xFF
            
    # Special handling for player 0 and 16
    if spec.get('player') == 0:
        for i in range(24, 143):
            season[i] = 0
    elif spec.get('player') == 16:
        season[23] = 150
        
    # Apply specific modifications from spec
    for key, value in spec.items():
        if key == 'age':
            roster[20] = value
            season[20] = value
        elif key == 'games':
            season[23] = value
        elif key == 'pos1':
            season[29] = (season[29] & 0xF0) | (value & 0x0F)
        elif key == 'endurance':
            season[135] = (season[135] & 0x0F) | ((value & 0x0F) << 4)
        elif key == 'arm':
            season[94] = (season[94] & 0xF0) | (value & 0x0F)
        elif key == 'ab_l':
            season[37] = value >> 8
            season[38] = value & 0xFF
            
    return (roster, season)

def test_merge_and_aging_all_players():
    if not os.path.exists(BLOB):
        pytest.skip("Blob file not found")
        
    # Load pristine team
    team = Team.load(PRISTINE)
    
    for i in range(40):
        roster, season = build_pair({'player': i})
        
        # Run reference implementation
        rng = rollover.Rng(0x0001)
        cfg = {'progress': False, 'retire': False}
        roster_in = bytearray(roster)
        season_in = bytearray(season)
        retire_ref = rollover.rollover_player(roster, season, cfg, rng, None)
        exp_season = bytearray(season)
        for _f in ('age', 'year_off', 'exp'):
            exp_season[F[_f][0]] = roster[F[_f][0]]
        if retire_ref:
            exp_season[0] = 0
            roster[0] = 0   # blob (and rollover_team) zero both halves on retire
        
        # Run unicorn emulation
        try:
            with Uc(UC_ARCH_X86, UC_MODE_16) as uc:
                # Map 1MB of memory
                uc.mem_map(0x00000, 0x100000)
                
                # Write blob
                with open(BLOB, 'rb') as f:
                    blob_bytes = f.read()
                uc.mem_write(PHYSICAL_BLOB, blob_bytes)
                
                # Write records
                uc.mem_write(PHYSICAL_ROSTER, bytes(roster_in))
                uc.mem_write(PHYSICAL_SEASON, bytes(season_in))
                
                # Write RNG state
                uc.mem_write(PHYSICAL_RNG, struct.pack('<H', 0x0001))
                
                # Set up stack
                uc.mem_write(PHYSICAL_STACK + OFFSET_STACK, b'\x00\x00')  # IP
                uc.mem_write(PHYSICAL_STACK + OFFSET_STACK + 2, b'\x00\xF0')  # CS
                
                # Set registers
                uc.reg_write(UC_X86_REG_CS, 0x1000)
                uc.reg_write(UC_X86_REG_DS, SEGMENT_ROSTER)
                uc.reg_write(UC_X86_REG_ES, SEGMENT_SEASON)
                uc.reg_write(UC_X86_REG_FS, SEGMENT_RNG)
                uc.reg_write(UC_X86_REG_SS, SEGMENT_STACK)
                uc.reg_write(UC_X86_REG_SI, OFFSET_ROSTER)
                uc.reg_write(UC_X86_REG_DI, OFFSET_SEASON)
                uc.reg_write(UC_X86_REG_BX, OFFSET_RNG)
                uc.reg_write(UC_X86_REG_CX, 0x0000)  # No flags
                uc.reg_write(UC_X86_REG_SP, OFFSET_STACK)
                uc.reg_write(UC_X86_REG_EIP, ENTRY_ROLL_PLAYER)
                
                # Write sentinel
                uc.mem_write(PHYSICAL_SENTINEL, b'\xF4')
                
                # Start emulation
                try:
                    uc.emu_start(PHYSICAL_BLOB + ENTRY_ROLL_PLAYER, 0)
                except UcError as e:
                    if e.errno != UC_ERR_EXCEPTION:
                        raise
                        
                # Read results
                ax = uc.reg_read(UC_X86_REG_AX)
                
                # Read back records
                roster_result = uc.mem_read(PHYSICAL_ROSTER, 143)
                season_result = uc.mem_read(PHYSICAL_SEASON, 143)
                
                # Compare results
                assert ax == (1 if retire_ref else 0), f"Player {i}: AX mismatch"
                assert roster_result == roster, f"Player {i}: roster mismatch"
                assert season_result == exp_season, f"Player {i}: season mismatch"
                
        except Exception as e:
            pytest.fail(f"Player {i}: Exception during emulation: {e}")

def test_progression_all_players():
    if not os.path.exists(BLOB):
        pytest.skip("Blob file not found")
        
    team = Team.load(PRISTINE)
    
    for i in range(40):
        roster, season = build_pair({'player': i})
        
        # Run reference implementation
        rng = rollover.Rng(0xBEEF + i)
        cfg = {'progress': True, 'retire': False}
        roster_in = bytearray(roster)
        season_in = bytearray(season)
        retire_ref = rollover.rollover_player(roster, season, cfg, rng, None)
        exp_season = bytearray(season)
        for _f in ('age', 'year_off', 'exp'):
            exp_season[F[_f][0]] = roster[F[_f][0]]
        if retire_ref:
            exp_season[0] = 0
            roster[0] = 0   # blob (and rollover_team) zero both halves on retire
        
        # Run unicorn emulation
        try:
            with Uc(UC_ARCH_X86, UC_MODE_16) as uc:
                # Map 1MB of memory
                uc.mem_map(0x00000, 0x100000)
                
                # Write blob
                with open(BLOB, 'rb') as f:
                    blob_bytes = f.read()
                uc.mem_write(PHYSICAL_BLOB, blob_bytes)
                
                # Write records
                uc.mem_write(PHYSICAL_ROSTER, bytes(roster_in))
                uc.mem_write(PHYSICAL_SEASON, bytes(season_in))
                
                # Write RNG state
                uc.mem_write(PHYSICAL_RNG, struct.pack('<H', 0xBEEF + i))
                
                # Set up stack
                uc.mem_write(PHYSICAL_STACK + OFFSET_STACK, b'\x00\x00')  # IP
                uc.mem_write(PHYSICAL_STACK + OFFSET_STACK + 2, b'\x00\xF0')  # CS
                
                # Set registers
                uc.reg_write(UC_X86_REG_CS, 0x1000)
                uc.reg_write(UC_X86_REG_DS, SEGMENT_ROSTER)
                uc.reg_write(UC_X86_REG_ES, SEGMENT_SEASON)
                uc.reg_write(UC_X86_REG_FS, SEGMENT_RNG)
                uc.reg_write(UC_X86_REG_SS, SEGMENT_STACK)
                uc.reg_write(UC_X86_REG_SI, OFFSET_ROSTER)
                uc.reg_write(UC_X86_REG_DI, OFFSET_SEASON)
                uc.reg_write(UC_X86_REG_BX, OFFSET_RNG)
                uc.reg_write(UC_X86_REG_CX, 0x0001)  # Progression enabled
                uc.reg_write(UC_X86_REG_SP, OFFSET_STACK)
                uc.reg_write(UC_X86_REG_EIP, ENTRY_ROLL_PLAYER)
                
                # Write sentinel
                uc.mem_write(PHYSICAL_SENTINEL, b'\xF4')
                
                # Start emulation
                try:
                    uc.emu_start(PHYSICAL_BLOB + ENTRY_ROLL_PLAYER, 0)
                except UcError as e:
                    if e.errno != UC_ERR_EXCEPTION:
                        raise
                        
                # Read results
                ax = uc.reg_read(UC_X86_REG_AX)
                
                # Read back records
                roster_result = uc.mem_read(PHYSICAL_ROSTER, 143)
                season_result = uc.mem_read(PHYSICAL_SEASON, 143)
                
                # Compare results
                assert ax == (1 if retire_ref else 0), f"Player {i}: AX mismatch"
                assert roster_result == roster, f"Player {i}: roster mismatch"
                assert season_result == exp_season, f"Player {i}: season mismatch"
                
        except Exception as e:
            pytest.fail(f"Player {i}: Exception during emulation: {e}")

def test_retirement_vectors():
    if not os.path.exists(BLOB):
        pytest.skip("Blob file not found")
        
    # V1 saturation
    roster, season = build_pair({'ab_l': 65530, 'games': 100})
    rng = rollover.Rng(0x0001)
    cfg = {'progress': True, 'retire': True}
    roster_in = bytearray(roster)
    season_in = bytearray(season)
    retire_ref = rollover.rollover_player(roster, season, cfg, rng, None)
    exp_season = bytearray(season)
    for _f in ('age', 'year_off', 'exp'):
        exp_season[F[_f][0]] = roster[F[_f][0]]
    if retire_ref:
        exp_season[0] = 0
        roster[0] = 0   # blob (and rollover_team) zero both halves on retire
    
    try:
        with Uc(UC_ARCH_X86, UC_MODE_16) as uc:
            # Map 1MB of memory
            uc.mem_map(0x00000, 0x100000)
            
            # Write blob
            with open(BLOB, 'rb') as f:
                blob_bytes = f.read()
            uc.mem_write(PHYSICAL_BLOB, blob_bytes)
            
            # Write records
            uc.mem_write(PHYSICAL_ROSTER, bytes(roster_in))
            uc.mem_write(PHYSICAL_SEASON, bytes(season_in))
            
            # Write RNG state
            uc.mem_write(PHYSICAL_RNG, struct.pack('<H', 0x0001))
            
            # Set up stack
            uc.mem_write(PHYSICAL_STACK + OFFSET_STACK, b'\x00\x00')  # IP
            uc.mem_write(PHYSICAL_STACK + OFFSET_STACK + 2, b'\x00\xF0')  # CS
            
            # Set registers
            uc.reg_write(UC_X86_REG_CS, 0x1000)
            uc.reg_write(UC_X86_REG_DS, SEGMENT_ROSTER)
            uc.reg_write(UC_X86_REG_ES, SEGMENT_SEASON)
            uc.reg_write(UC_X86_REG_FS, SEGMENT_RNG)
            uc.reg_write(UC_X86_REG_SS, SEGMENT_STACK)
            uc.reg_write(UC_X86_REG_SI, OFFSET_ROSTER)
            uc.reg_write(UC_X86_REG_DI, OFFSET_SEASON)
            uc.reg_write(UC_X86_REG_BX, OFFSET_RNG)
            uc.reg_write(UC_X86_REG_CX, 0x0003)  # Progression and retirement enabled
            uc.reg_write(UC_X86_REG_SP, OFFSET_STACK)
            uc.reg_write(UC_X86_REG_EIP, ENTRY_ROLL_PLAYER)
            
            # Write sentinel
            uc.mem_write(PHYSICAL_SENTINEL, b'\xF4')
            
            # Start emulation
            try:
                uc.emu_start(PHYSICAL_BLOB + ENTRY_ROLL_PLAYER, 0)
            except UcError as e:
                if e.errno != UC_ERR_EXCEPTION:
                    raise
                    
            # Read results
            ax = uc.reg_read(UC_X86_REG_AX)
            
            # Read back records
            roster_result = uc.mem_read(PHYSICAL_ROSTER, 143)
            season_result = uc.mem_read(PHYSICAL_SEASON, 143)
            
            # Compare results
            assert ax == (1 if retire_ref else 0), "V1: AX mismatch"
            assert roster_result == roster, "V1: roster mismatch"
            assert season_result == exp_season, "V1: season mismatch"
            
    except Exception as e:
        pytest.fail(f"V1: Exception during emulation: {e}")

    # V2 ages
    for age in (20, 24, 25, 28, 29, 34, 35, 40, 41):
        roster, season = build_pair({'age': age, 'games': 150, 'pos1': 7})
        rng = rollover.Rng(0x0001)
        cfg = {'progress': True, 'retire': True}
        roster_in = bytearray(roster)
        season_in = bytearray(season)
        retire_ref = rollover.rollover_player(roster, season, cfg, rng, None)
        exp_season = bytearray(season)
        for _f in ('age', 'year_off', 'exp'):
            exp_season[F[_f][0]] = roster[F[_f][0]]
        if retire_ref:
            exp_season[0] = 0
            roster[0] = 0   # blob (and rollover_team) zero both halves on retire
        
        try:
            with Uc(UC_ARCH_X86, UC_MODE_16) as uc:
                # Map 1MB of memory
                uc.mem_map(0x00000, 0x100000)
                
                # Write blob
                with open(BLOB, 'rb') as f:
                    blob_bytes = f.read()
                uc.mem_write(PHYSICAL_BLOB, blob_bytes)
                
                # Write records
                uc.mem_write(PHYSICAL_ROSTER, bytes(roster_in))
                uc.mem_write(PHYSICAL_SEASON, bytes(season_in))
                
                # Write RNG state
                uc.mem_write(PHYSICAL_RNG, struct.pack('<H', 0x0001))
                
                # Set up stack
                uc.mem_write(PHYSICAL_STACK + OFFSET_STACK, b'\x00\x00')  # IP
                uc.mem_write(PHYSICAL_STACK + OFFSET_STACK + 2, b'\x00\xF0')  # CS
                
                # Set registers
                uc.reg_write(UC_X86_REG_CS, 0x1000)
                uc.reg_write(UC_X86_REG_DS, SEGMENT_ROSTER)
                uc.reg_write(UC_X86_REG_ES, SEGMENT_SEASON)
                uc.reg_write(UC_X86_REG_FS, SEGMENT_RNG)
                uc.reg_write(UC_X86_REG_SS, SEGMENT_STACK)
                uc.reg_write(UC_X86_REG_SI, OFFSET_ROSTER)
                uc.reg_write(UC_X86_REG_DI, OFFSET_SEASON)
                uc.reg_write(UC_X86_REG_BX, OFFSET_RNG)
                uc.reg_write(UC_X86_REG_CX, 0x0003)  # Progression and retirement enabled
                uc.reg_write(UC_X86_REG_SP, OFFSET_STACK)
                uc.reg_write(UC_X86_REG_EIP, ENTRY_ROLL_PLAYER)
                
                # Write sentinel
                uc.mem_write(PHYSICAL_SENTINEL, b'\xF4')
                
                # Start emulation
                try:
                    uc.emu_start(PHYSICAL_BLOB + ENTRY_ROLL_PLAYER, 0)
                except UcError as e:
                    if e.errno != UC_ERR_EXCEPTION:
                        raise
                        
                # Read results
                ax = uc.reg_read(UC_X86_REG_AX)
                
                # Read back records
                roster_result = uc.mem_read(PHYSICAL_ROSTER, 143)
                season_result = uc.mem_read(PHYSICAL_SEASON, 143)
                
                # Compare results
                assert ax == (1 if retire_ref else 0), f"V2 age {age}: AX mismatch"
                assert roster_result == roster, f"V2 age {age}: roster mismatch"
                assert season_result == exp_season, f"V2 age {age}: season mismatch"
                
        except Exception as e:
            pytest.fail(f"V2 age {age}: Exception during emulation: {e}")

    # V3 pitcher retire
    roster, season = build_pair({'age': 30, 'pos1': 0, 'endurance': 2, 'arm': 2})
    rng = rollover.Rng(0x0001)
    cfg = {'progress': True, 'retire': True}
    roster_in = bytearray(roster)
    season_in = bytearray(season)
    retire_ref = rollover.rollover_player(roster, season, cfg, rng, None)
    exp_season = bytearray(season)
    for _f in ('age', 'year_off', 'exp'):
        exp_season[F[_f][0]] = roster[F[_f][0]]
    if retire_ref:
        exp_season[0] = 0
        roster[0] = 0   # blob (and rollover_team) zero both halves on retire
    
    try:
        with Uc(UC_ARCH_X86, UC_MODE_16) as uc:
            # Map 1MB of memory
            uc.mem_map(0x00000, 0x100000)
            
            # Write blob
            with open(BLOB, 'rb') as f:
                blob_bytes = f.read()
            uc.mem_write(PHYSICAL_BLOB, blob_bytes)
            
            # Write records
            uc.mem_write(PHYSICAL_ROSTER, bytes(roster_in))
            uc.mem_write(PHYSICAL_SEASON, bytes(season_in))
            
            # Write RNG state
            uc.mem_write(PHYSICAL_RNG, struct.pack('<H', 0x0001))
            
            # Set up stack
            uc.mem_write(PHYSICAL_STACK + OFFSET_STACK, b'\x00\x00')  # IP
            uc.mem_write(PHYSICAL_STACK + OFFSET_STACK + 2, b'\x00\xF0')  # CS
            
            # Set registers
            uc.reg_write(UC_X86_REG_CS, 0x1000)
            uc.reg_write(UC_X86_REG_DS, SEGMENT_ROSTER)
            uc.reg_write(UC_X86_REG_ES, SEGMENT_SEASON)
            uc.reg_write(UC_X86_REG_FS, SEGMENT_RNG)
            uc.reg_write(UC_X86_REG_SS, SEGMENT_STACK)
            uc.reg_write(UC_X86_REG_SI, OFFSET_ROSTER)
            uc.reg_write(UC_X86_REG_DI, OFFSET_SEASON)
            uc.reg_write(UC_X86_REG_BX, OFFSET_RNG)
            uc.reg_write(UC_X86_REG_CX, 0x0003)  # Progression and retirement enabled
            uc.reg_write(UC_X86_REG_SP, OFFSET_STACK)
            uc.reg_write(UC_X86_REG_EIP, ENTRY_ROLL_PLAYER)
            
            # Write sentinel
            uc.mem_write(PHYSICAL_SENTINEL, b'\xF4')
            
            # Start emulation
            try:
                uc.emu_start(PHYSICAL_BLOB + ENTRY_ROLL_PLAYER, 0)
            except UcError as e:
                if e.errno != UC_ERR_EXCEPTION:
                    raise
                    
            # Read results
            ax = uc.reg_read(UC_X86_REG_AX)
            
            # Read back records
            roster_result = uc.mem_read(PHYSICAL_ROSTER, 143)
            season_result = uc.mem_read(PHYSICAL_SEASON, 143)
            
            # Compare results
            assert ax == (1 if retire_ref else 0), "V3: AX mismatch"
            assert roster_result == roster, "V3: roster mismatch"
            assert season_result == exp_season, "V3: season mismatch"
            
    except Exception as e:
        pytest.fail(f"V3: Exception during emulation: {e}")

    # V4 no progress
    roster, season = build_pair({'games': 0})
    rng = rollover.Rng(0x0001)
    cfg = {'progress': True, 'retire': True}
    roster_in = bytearray(roster)
    season_in = bytearray(season)
    retire_ref = rollover.rollover_player(roster, season, cfg, rng, None)
    exp_season = bytearray(season)
    for _f in ('age', 'year_off', 'exp'):
        exp_season[F[_f][0]] = roster[F[_f][0]]
    if retire_ref:
        exp_season[0] = 0
        roster[0] = 0   # blob (and rollover_team) zero both halves on retire
    
    try:
        with Uc(UC_ARCH_X86, UC_MODE_16) as uc:
            # Map 1MB of memory
            uc.mem_map(0x00000, 0x100000)
            
            # Write blob
            with open(BLOB, 'rb') as f:
                blob_bytes = f.read()
            uc.mem_write(PHYSICAL_BLOB, blob_bytes)
            
            # Write records
            uc.mem_write(PHYSICAL_ROSTER, bytes(roster_in))
            uc.mem_write(PHYSICAL_SEASON, bytes(season_in))
            
            # Write RNG state
            uc.mem_write(PHYSICAL_RNG, struct.pack('<H', 0x0001))
            
            # Set up stack
            uc.mem_write(PHYSICAL_STACK + OFFSET_STACK, b'\x00\x00')  # IP
            uc.mem_write(PHYSICAL_STACK + OFFSET_STACK + 2, b'\x00\xF0')  # CS
            
            # Set registers
            uc.reg_write(UC_X86_REG_CS, 0x1000)
            uc.reg_write(UC_X86_REG_DS, SEGMENT_ROSTER)
            uc.reg_write(UC_X86_REG_ES, SEGMENT_SEASON)
            uc.reg_write(UC_X86_REG_FS, SEGMENT_RNG)
            uc.reg_write(UC_X86_REG_SS, SEGMENT_STACK)
            uc.reg_write(UC_X86_REG_SI, OFFSET_ROSTER)
            uc.reg_write(UC_X86_REG_DI, OFFSET_SEASON)
            uc.reg_write(UC_X86_REG_BX, OFFSET_RNG)
            uc.reg_write(UC_X86_REG_CX, 0x0003)  # Progression and retirement enabled
            uc.reg_write(UC_X86_REG_SP, OFFSET_STACK)
            uc.reg_write(UC_X86_REG_EIP, ENTRY_ROLL_PLAYER)
            
            # Write sentinel
            uc.mem_write(PHYSICAL_SENTINEL, b'\xF4')
            
            # Start emulation
            try:
                uc.emu_start(PHYSICAL_BLOB + ENTRY_ROLL_PLAYER, 0)
            except UcError as e:
                if e.errno != UC_ERR_EXCEPTION:
                    raise
                    
            # Read results
            ax = uc.reg_read(UC_X86_REG_AX)
            
            # Read back records
            roster_result = uc.mem_read(PHYSICAL_ROSTER, 143)
            season_result = uc.mem_read(PHYSICAL_SEASON, 143)
            
            # Compare results
            assert ax == (1 if retire_ref else 0), "V4: AX mismatch"
            assert roster_result == roster, "V4: roster mismatch"
            assert season_result == exp_season, "V4: season mismatch"
            
    except Exception as e:
        pytest.fail(f"V4: Exception during emulation: {e}")

    # V5 zero-stat player
    roster, season = build_pair({'games': 0})
    rng = rollover.Rng(0x0001)
    cfg = {'progress': True, 'retire': True}
    roster_in = bytearray(roster)
    season_in = bytearray(season)
    retire_ref = rollover.rollover_player(roster, season, cfg, rng, None)
    exp_season = bytearray(season)
    for _f in ('age', 'year_off', 'exp'):
        exp_season[F[_f][0]] = roster[F[_f][0]]
    if retire_ref:
        exp_season[0] = 0
        roster[0] = 0   # blob (and rollover_team) zero both halves on retire
    
    try:
        with Uc(UC_ARCH_X86, UC_MODE_16) as uc:
            # Map 1MB of memory
            uc.mem_map(0x00000, 0x100000)
            
            # Write blob
            with open(BLOB, 'rb') as f:
                blob_bytes = f.read()
            uc.mem_write(PHYSICAL_BLOB, blob_bytes)
            
            # Write records
            uc.mem_write(PHYSICAL_ROSTER, bytes(roster_in))
            uc.mem_write(PHYSICAL_SEASON, bytes(season_in))
            
            # Write RNG state
            uc.mem_write(PHYSICAL_RNG, struct.pack('<H', 0x0001))
            
            # Set up stack
            uc.mem_write(PHYSICAL_STACK + OFFSET_STACK, b'\x00\x00')  # IP
            uc.mem_write(PHYSICAL_STACK + OFFSET_STACK + 2, b'\x00\xF0')  # CS
            
            # Set registers
            uc.reg_write(UC_X86_REG_CS, 0x1000)
            uc.reg_write(UC_X86_REG_DS, SEGMENT_ROSTER)
            uc.reg_write(UC_X86_REG_ES, SEGMENT_SEASON)
            uc.reg_write(UC_X86_REG_FS, SEGMENT_RNG)
            uc.reg_write(UC_X86_REG_SS, SEGMENT_STACK)
            uc.reg_write(UC_X86_REG_SI, OFFSET_ROSTER)
            uc.reg_write(UC_X86_REG_DI, OFFSET_SEASON)
            uc.reg_write(UC_X86_REG_BX, OFFSET_RNG)
            uc.reg_write(UC_X86_REG_CX, 0x0003)  # Progression and retirement enabled
            uc.reg_write(UC_X86_REG_SP, OFFSET_STACK)
            uc.reg_write(UC_X86_REG_EIP, ENTRY_ROLL_PLAYER)
            
            # Write sentinel
            uc.mem_write(PHYSICAL_SENTINEL, b'\xF4')
            
            # Start emulation
            try:
                uc.emu_start(PHYSICAL_BLOB + ENTRY_ROLL_PLAYER, 0)
            except UcError as e:
                if e.errno != UC_ERR_EXCEPTION:
                    raise
                    
            # Read results
            ax = uc.reg_read(UC_X86_REG_AX)
            
            # Read back records
            roster_result = uc.mem_read(PHYSICAL_ROSTER, 143)
            season_result = uc.mem_read(PHYSICAL_SEASON, 143)
            
            # Compare results
            assert ax == (1 if retire_ref else 0), "V5: AX mismatch"
            assert roster_result == roster, "V5: roster mismatch"
            assert season_result == exp_season, "V5: season mismatch"
            
    except Exception as e:
        pytest.fail(f"V5: Exception during emulation: {e}")

def test_rng_agreement():
    if not os.path.exists(BLOB):
        pytest.skip("Blob file not found")
        
    for s in range(200):
        # V2 age-38 vector
        roster, season = build_pair({'age': 38, 'games': 150, 'pos1': 7})
        
        # Run reference implementation
        rng = rollover.Rng(s)
        cfg = {'progress': True, 'retire': True}
        roster_in = bytearray(roster)
        season_in = bytearray(season)
        retire_ref = rollover.rollover_player(roster, season, cfg, rng, None)
        exp_season = bytearray(season)
        for _f in ('age', 'year_off', 'exp'):
            exp_season[F[_f][0]] = roster[F[_f][0]]
        if retire_ref:
            exp_season[0] = 0
            roster[0] = 0   # blob (and rollover_team) zero both halves on retire
        
        # Run unicorn emulation
        try:
            with Uc(UC_ARCH_X86, UC_MODE_16) as uc:
                # Map 1MB of memory
                uc.mem_map(0x00000, 0x100000)
                
                # Write blob
                with open(BLOB, 'rb') as f:
                    blob_bytes = f.read()
                uc.mem_write(PHYSICAL_BLOB, blob_bytes)
                
                # Write records
                uc.mem_write(PHYSICAL_ROSTER, bytes(roster_in))
                uc.mem_write(PHYSICAL_SEASON, bytes(season_in))
                
                # Write RNG state
                uc.mem_write(PHYSICAL_RNG, struct.pack('<H', s))
                
                # Set up stack
                uc.mem_write(PHYSICAL_STACK + OFFSET_STACK, b'\x00\x00')  # IP
                uc.mem_write(PHYSICAL_STACK + OFFSET_STACK + 2, b'\x00\xF0')  # CS
                
                # Set registers
                uc.reg_write(UC_X86_REG_CS, 0x1000)
                uc.reg_write(UC_X86_REG_DS, SEGMENT_ROSTER)
                uc.reg_write(UC_X86_REG_ES, SEGMENT_SEASON)
                uc.reg_write(UC_X86_REG_FS, SEGMENT_RNG)
                uc.reg_write(UC_X86_REG_SS, SEGMENT_STACK)
                uc.reg_write(UC_X86_REG_SI, OFFSET_ROSTER)
                uc.reg_write(UC_X86_REG_DI, OFFSET_SEASON)
                uc.reg_write(UC_X86_REG_BX, OFFSET_RNG)
                uc.reg_write(UC_X86_REG_CX, 0x0003)  # Progression and retirement enabled
                uc.reg_write(UC_X86_REG_SP, OFFSET_STACK)
                uc.reg_write(UC_X86_REG_EIP, ENTRY_ROLL_PLAYER)
                
                # Write sentinel
                uc.mem_write(PHYSICAL_SENTINEL, b'\xF4')
                
                # Start emulation
                try:
                    uc.emu_start(PHYSICAL_BLOB + ENTRY_ROLL_PLAYER, 0)
                except UcError as e:
                    if e.errno != UC_ERR_EXCEPTION:
                        raise
                        
                # Read results
                ax = uc.reg_read(UC_X86_REG_AX)
                
                # Compare results
                assert ax == (1 if retire_ref else 0), f"Seed {s}: AX mismatch"
                
        except Exception as e:
            pytest.fail(f"Seed {s}: Exception during emulation: {e}")

if __name__ == '__main__':
    if not os.path.exists(BLOB):
        print("Blob file not found, skipping tests")
        exit(0)
        
    # Run tests manually
    try:
        test_merge_and_aging_all_players()
        print("test_merge_and_aging_all_players passed")
    except Exception as e:
        print(f"test_merge_and_aging_all_players failed: {e}")
        
    try:
        test_progression_all_players()
        print("test_progression_all_players passed")
    except Exception as e:
        print(f"test_progression_all_players failed: {e}")
        
    try:
        test_retirement_vectors()
        print("test_retirement_vectors passed")
    except Exception as e:
        print(f"test_retirement_vectors failed: {e}")
        
    try:
        test_rng_agreement()
        print("test_rng_agreement passed")
    except Exception as e:
        print(f"test_rng_agreement failed: {e}")
