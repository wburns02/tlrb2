#!/usr/bin/env python3
"""Define the decoded file formats as Ghidra data types (category /TLRB2) in every program.

usage: /mnt/nvme/bbpro98/ghidra_venv/bin/python3 structs.py   (then scripts/regen.sh)
Source of truth for every offset: notes/FORMATS.md (Lane B, proven by round trips; tools/v20.py parses byte exact).
Nibble-packed bytes are u8 fields whose comment says which nibble holds what. Re-running replaces the types.
Types: V20Player (143 B), V20Header (295 B), V20Team (11735 B = header + 80 players).
"""
import os
os.environ.setdefault('GHIDRA_INSTALL_DIR', '/mnt/nvme/ghidra/ghidra_12.1.4_PUBLIC')
import pyghidra
pyghidra.start()
from ghidra.base.project import GhidraProject
from ghidra.program.model.data import (StructureDataType, ArrayDataType, CharDataType, ByteDataType, WordDataType,
                                       CategoryPath, DataTypeConflictHandler)

PROJ, NAME = '/mnt/nvme/tlrb2/ghidra_proj', 'TLRB2'
PROGS = ['MAIN', 'BB', 'UTIL', 'DRAFT', 'BACK', 'MANAGE', 'PLAY', 'CONTROL']
CAT = CategoryPath('/TLRB2')
B, W, C = ByteDataType.dataType, WordDataType.dataType, CharDataType.dataType

# (offset, name, type, count, comment); type 'c' char array, 'b' u8, 'w' u16 LE. Gaps become undefined bytes.
PLAYER = [
    (0, 'last_name', 'c', 12, ''), (12, 'first_name', 'c', 8, ''), (20, 'age', 'b', 1, ''),
    (21, 'year_m1870', 'b', 1, 'year - 1870'), (22, 'exp', 'b', 1, ''), (23, 'games', 'b', 1, 'G, used by range/arm/endurance'),
    (24, 'days_unavail', 'b', 1, 'DU: low 7 bits days, bit7 REST; injuries are values without bit7. Records 0..39 only'),
    (25, 'salary', 'w', 1, 'clamped 109..9999, UTIL salary formulas'), (27, 'unk_id', 'w', 1, 'not the portrait; per-player id?'),
    (29, 'speed_hands', 'b', 1, 'hi speed; lo bit3 throws R, bits2-1 bats (1 R, 2 S), bit0 unknown box'),
    (30, 'exper_consist', 'b', 1, 'hi exper, lo consistency'), (31, 'pos2_pos1', 'b', 1, 'hi pos2, lo pos1 (0 P,1 C,2 1B..9 DH,10 OF..15 C/3)'),
    (32, 'r', 'b', 1, ''), (33, 'rbi', 'b', 1, ''), (34, 'sh', 'b', 1, ''), (35, 'sb', 'b', 1, ''), (36, 'cs', 'b', 1, ''),
    (37, 'ab_l', 'w', 1, ''), (39, 'ab_r', 'w', 1, ''), (41, 'h_l', 'w', 1, ''), (43, 'h_r', 'w', 1, ''),
    (45, 'd2b_l', 'w', 1, ''), (47, 'd2b_r', 'w', 1, ''), (49, 't3b_l', 'b', 1, ''), (50, 't3b_r', 'b', 1, ''),
    (51, 'hr_l', 'b', 1, ''), (52, 'hr_r', 'b', 1, ''), (53, 'bb_l', 'w', 1, ''), (55, 'bb_r', 'w', 1, ''),
    (57, 'so_l', 'w', 1, ''), (59, 'so_r', 'w', 1, ''),
    (61, 'grounder_pct10', 'w', 1, 'x10; fly% = 100 - this'), (63, 'gb_pull10', 'w', 1, ''), (65, 'gb_opp10', 'w', 1, ''),
    (67, 'fb_pull10', 'w', 1, ''), (69, 'fb_opp10', 'w', 1, ''),
    (71, 'pinch_ab', 'b', 1, ''), (72, 'pinch_h', 'b', 1, ''), (73, 'pinch_hr', 'b', 1, ''),
    (74, 'bunt_power', 'b', 1, 'hi bunt, lo power (1..12)'), (75, 'streak_hnr', 'b', 1, 'hi streak, lo hit and run'),
    (76, 'daynight_clutch', 'b', 1, 'hi day/night, lo clutch'),
    (77, 'po1', 'w', 1, ''), (79, 'po2', 'w', 1, ''), (81, 'a1', 'w', 1, ''), (83, 'a2', 'w', 1, ''),
    (85, 'e1', 'b', 1, ''), (86, 'e2', 'b', 1, ''), (87, 'dp1', 'b', 1, ''), (88, 'dp2', 'b', 1, ''), (89, 'pb', 'b', 1, ''),
    (90, 'rto_num', 'w', 1, 'RTO% = rto_num/rto_den x100 (probable)'), (92, 'rto_den', 'w', 1, ''),
    (94, 'range_arm', 'b', 1, 'hi range, lo arm'),
    (95, 'p_w', 'b', 1, ''), (96, 'p_l', 'b', 1, ''), (97, 'p_cg', 'b', 1, ''), (98, 'p_gs', 'b', 1, ''), (99, 'p_sho', 'b', 1, ''),
    (100, 'p_sv', 'b', 1, ''), (101, 'p_ip10', 'w', 1, 'innings x10 (.1 .2 thirds)'), (103, 'p_er', 'w', 1, ''),
    (105, 'p_r', 'w', 1, 'likely runs'), (107, 'p_bfp_l', 'w', 1, 'batters faced'), (109, 'p_bfp_r', 'w', 1, ''),
    (111, 'p_h_l', 'w', 1, ''), (113, 'p_h_r', 'w', 1, ''), (115, 'p_2b_l', 'w', 1, ''), (117, 'p_2b_r', 'w', 1, ''),
    (119, 'p_3b_l', 'b', 1, ''), (120, 'p_3b_r', 'b', 1, ''), (121, 'p_bb_l', 'w', 1, ''), (123, 'p_bb_r', 'w', 1, ''),
    (125, 'p_so_l', 'w', 1, ''), (127, 'p_so_r', 'w', 1, ''), (129, 'p_hr_l', 'b', 1, ''), (130, 'p_hr_r', 'b', 1, ''),
    (131, 'p_bk', 'b', 1, ''), (132, 'p_wp', 'b', 1, ''), (133, 'unk_85', 'b', 1, 'mostly tracks games; semantics unknown'),
    (134, 'velo_control', 'b', 1, 'hi velocity, lo control'), (135, 'endur_pitch4', 'b', 1, 'hi endurance, lo pitch4 type'),
    (136, 'p_clutch_streak', 'b', 1, 'hi clutch, lo streak'), (137, 'pickoff_daynight', 'b', 1, 'hi pickoff, lo day/night'),
    (138, 'q1_release', 'b', 1, 'hi Q1, lo release'), (139, 'q3_q2', 'b', 1, 'hi Q3, lo Q2'),
    (140, 'q4_userset', 'b', 1, 'lo Q4; hi nibble = ratings user-set flag'), (141, 'import_id', 'w', 1, 'UTIL import match id'),
]
HEADER = [
    (0, 'team_name', 'c', 14, ''), (14, 'league', 'c', 2, '"cl"'), (16, 'abbr', 'c', 3, ''),
    (19, 'stadium_stem', 'c', 8, 'STADIUMS/<stem>.CFG/.SDM'), (38, 'wins', 'b', 1, ''), (39, 'losses', 'b', 1, ''),
    (44, 'color_main', 'b', 24, '8 shades x (r,g,b), VGA DAC 0..63, light to dark'), (68, 'color_accent', 'b', 24, ''),
    (108, 'last_day_aged', 'b', 1, 'MANAGE age_players_loop; BACK writes last game day'),
    (109, 'streak', 'b', 1, 'bit7 loss streak, low 7 bits length'), (110, 'rotation_ptr', 'b', 1, '0..4'),
    (111, 'starters', 'b', 5, 'player indices, rotation order'), (116, 'relievers', 'b', 5, ''),
    (122, 'batting_order', 'b', 36, '4 sets x 9, set = dh*2 + vs (vs 0 LHP 1 RHP); 0xff pad'),
    (158, 'defense', 'b', 36, '4 x 9 position codes per slot'), (194, 'bench', 'b', 28, '4 x 7, 0xff pad'),
    (222, 'reserves', 'b', 15, '6 pitchers + 9 batters'), (237, 'gm_profile', 'b', 7, 'draft GM weights, sum 100'),
    (244, 'gm_preset', 'b', 1, '0..4 preset, 5 custom'), (245, 'strategy', 'b', 15, '5 tabs x 3 sliders, right value x10'),
]

def build(name, fields, size):
    s = StructureDataType(CAT, name, size)
    for off, fn, t, n, cm in fields:
        base = {'c': C, 'b': B, 'w': W}[t]
        dt = base if n == 1 else ArrayDataType(base, n, base.getLength())
        s.replaceAtOffset(off, dt, dt.getLength(), fn, cm or None)
    return s

def main():
    player = build('V20Player', PLAYER, 143)
    header = build('V20Header', HEADER, 295)
    proj = GhidraProject.openProject(PROJ, NAME, True)
    try:
        for prog in PROGS:
            p = proj.openProgram('/', f'{prog}.flat.bin', False)
            dtm = p.getDataTypeManager()
            tx = p.startTransaction('TLRB2 structs'); ok = False
            try:
                hp = dtm.addDataType(header, DataTypeConflictHandler.REPLACE_HANDLER)
                pp = dtm.addDataType(player, DataTypeConflictHandler.REPLACE_HANDLER)
                team = StructureDataType(CAT, 'V20Team', 0)
                team.add(hp, 'hdr', None)
                team.add(ArrayDataType(pp, 80, 143), 'players', 'records 0..39 ratings/career half, 40..79 current season')
                t = dtm.addDataType(team, DataTypeConflictHandler.REPLACE_HANDLER)
                assert t.getLength() == 11735, t.getLength()
                ok = True
            finally:
                p.endTransaction(tx, ok)
            proj.save(p)
            print(prog, 'V20Header/V20Player/V20Team defined', flush=True)
    finally:
        proj.close()

if __name__ == '__main__':
    main()
