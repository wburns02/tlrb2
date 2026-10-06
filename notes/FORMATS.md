# TLRB2 data formats

## Team file .V20 (11735 B, uncompressed). Decoded by Lane B 2026-10-06, code: tools/v20.py
295 B header + 80 player records x 143 B. Records 0-15 pitchers, 16-39 position players. Records 40-79 are the
same 40 players as the "current season" half (year+1, exp+1, season stats zeroed, ratings identical). The
Utilities editor writes ratings/bio to both halves. Edits proven by round trip: v20.py set (outside the game),
game editor shows the change (age, salary, first name, HR vs L verified on screen). Parse+serialize is byte exact.
Method: single-field edit in Utilities (work install), Main > QUIT is what writes the file, then v20.py diff.

Record offsets (dec, within the 143 B record). u16 is little endian. "hi/lo" = nibble of that byte.
- 0 last name (12), 12 first name (8), 20 age, 21 year-1870, 22 exp, 23 games, 25 u16 salary
- 27 u16 unknown. NOT the portrait (changing it left the picture unchanged). Looks like a per-player id.
- 29: hi speed. lo: bit3 throws R (0=L), bits2-1 bats (1=R, 2=S, L presumably 0), bit0 third header box (L/D, meaning unknown)
- 30: hi exper, lo consist. 31: hi pos2, lo pos1. Pos: 0 P,1 C,2 1B,3 2B,4 3B,5 SS,6 LF,7 CF,8 RF,9 DH,10 OF,11 IF,12 O/I,13 C/O,14 C/I,15 C/3
- 32 R, 33 RBI, 34 SH, 35 SB, 36 CS (u8)
- 37 AB_L, 39 AB_R, 41 H_L, 43 H_R, 45 2B_L, 47 2B_R (u16); 49 3B_L, 50 3B_R, 51 HR_L, 52 HR_R (u8);
  53 BB_L, 55 BB_R, 57 SO_L, 59 SO_R (u16). Totals shown by the editor are L+R.
- 61 grounder% x10, 63 gb pull x10, 65 gb opp x10, 67 fb pull x10, 69 fb opp x10 (u16). Fly% = 100 - grounder%.
- 71 pinch AB, 72 pinch H, 73 pinch HR (u8)
- 74 hi bunt lo power. 75 hi streak lo H&R. 76 hi day/night lo clutch. All 1..12 (editor clamps 13 to 12, ignores 0).
- 77 PO1, 79 PO2, 81 A1, 83 A2 (u16); 85 E1, 86 E2, 87 DP1, 88 DP2, 89 PB (u8)
- 90 u16 + 92 u16: RTO% shown = 90/92 x100 (probable, typed 33.3 stored 33 and 100). 94 hi range lo arm
- Pitchers: 95 W, 96 L, 97 CG, 98 GS, 99 SHO, 100 SV (u8); 101 IP x10, 103 ER, 105 u16 (equals ER in 301/416, likely R) (u16);
  107 BFP_L, 109 BFP_R, 111 H_L, 113 H_R, 115 2B_L, 117 2B_R (u16); 119 3B_L, 120 3B_R (u8);
  121 BB_L, 123 BB_R, 125 SO_L, 127 SO_R (u16); 129 HR_L, 130 HR_R, 131 BK, 132 WP (u8). Pitchers store batters faced, AB = BFP - BB.
- Pitcher ratings: 134 hi velocity lo control. 135 hi endurance lo pitch4 type. 136 hi clutch lo streak. 137 hi pickoff lo day/night.
  138 hi Q1 lo release. 139 hi Q3 lo Q2. 140 Q4. 141-142 zero. Batters carry default values here.
- Pitch4 codes: 0 FASTBALL 1 CURVE 2 CHANGEUP 3 ? 4 SLIDER 5 SCREWBALL 6 SINKER 7 SPLITFINGER 8 FORKBALL 9 KNUCKLEBALL
- Display letters: day/night A..G = 1..7. Streak letters: stored A7 B5 C8 D6 E10 F4 G9 (other values unmapped).
Header (295 B) decoded 2026-10-07 (Lane B), evidence = Manager-screen single-edit diffs + MANAGE code (team buffer ptr DAT_2000_c73c):
- +0 team name (14), +14 league code (2, "cl"), +16 stadium stem (8, "BALgrass"), +24 ext (3, "CFG"), +27.. zeros to +43.
- +44..+91 (48 B): two 24 B tables or 8 triples (a,a,b) / (x,y,z), differ per team, copied by MANAGE FUN_1000_f120 into DGROUP
  arrays 0x4f89/0x4fb9 (computer-manager/advice tables). Not edited by any screen. Meaning open.
- +108 u8 team "last day aged": equals MAJ+0x20a (league day counter) after any Manager save. MANAGE 1000:ce08 loops
  from this to the league day and ages injuries of players 0..39.
- +111..+120 pitching staff (10 player indices): 111..115 = 5 starters in rotation order, 116..120 = 5 relievers. +121 = 0xff.
  Pitching Staff swap active<->reserve changes one slot (proved); Rotation swap exchanges two slots (proved).
- Lineups, 4 sets, index = dh*18 + vs*9 where dh 0 = no-DH, 1 = DH; vs 0 = LHP, 1 = RHP (verified on screen for DH L/R and no-DH R):
  +122 batting order (9 slots; no-DH sets hold 8 players then 0xff; DH sets 9), 4 sets of 9 B -> +122..+157
  +158 defensive position per slot (4 x 9, position codes as in the V20 pos table: 0 P, 1 C..9 DH). No-DH sets end with 0 (pitcher).
  +194 bench = remaining active batters, 4 x 7 slots, 0xff padded (no-DH 7 players, DH 6 + 0xff) -> +194..+221
- +222..+236 reserves: 15 player indices (6 pitchers + 9 batters). Active 25-man = 10 pitchers + 15 batters; the whole file is a
  partition of the 40 players. Active<->reserve swap rewrites the player in every list that held him (lineups, bench, reserve slot).
- +237..+244: 14 14 05 05 0f 0f 14 00 in every CLASSIC team (0 in older 0168 files). Constant roster limits? Not edited. Open.
- +245..+259 manager strategy sliders (Manager > Manager Profile, 5 tabs x 3), stored = RIGHT-hand number x 10 (50 = 5/5):
  LINEUP: speed/power, defense/hitters, endurance/ERA; PITCHING: starters-in/yank'em, starters-in/pinch-hit, pitch-around/challenge;
  BATTING: sacrifice/hit-away, squeeze/hit-away, hit&run/play-safe; DEFENSE: walk/pitch-to, infield-in/normal, pitchout/throw-strikes;
  RUNNING: aggressive/safe, steal-2nd/safe, steal-3rd/safe. Proved: 15 values 30,80,40 40,90,20 10,60,30 80,20,60 90,10,70 for the
  screens' (7|3 2|8 6|4 / 6|4 1|9 8|2 / 9|1 4|6 7|3 / 2|8 8|2 4|6 / 1|9 9|1 3|7). +247 is used in MANAGE 1000:5e78 (advice score).
  +260..+264 stay 0x32 (unused), +265..+294 zero.
- Player record byte 24 (0x18) = DU column "days unavailable": low 7 bits = days, bit 7 shows "R" suffix (0x85 -> "5R", 0x03 -> "3",
  0x92 -> "18R"). Aged by 1 per league day, 0x81 -> 0. Proved in game (Roster/Staff/Rotation screens). Only records 0..39.
- tools/v20.py: `hdr FILE`, Team.staff/lineup/defense/bench/reserves/strategy, set_list, set_strategy, player 'injury'. In-game proof
  (shot rt2.png): header edited outside the game shows on Pitching Rotation (swapped starter), injury "8R", file parse+serialize byte exact.

## League file .MAJ (CLASSIC.MAJ 59771 B), partial
+0 league name (8). Then 10 B entries: 2-char league code + 8-char team stem ("clclasale1"), divisions of 8 slots, then ALLSTAR1/2.
From ~0x20a small control bytes, " LEAGUE", then 16 B team name+code entries from 0x22b, 3-letter abbreviations after 0x3a0.
A second similar region near 0x758c-0x8b5c, 128 B tail at 0xe8fb. Old-format MAJ = 58789 B; UTIL 4000:74ad upgrades 0xE625 to 0xE97B.
Not decoded.

## Other files (TBD)
SYSTEM (76 B: current league name + settings), CONTROL (9 B: next program/state), GAME.TMP, .SCH schedules
(57176 B, text header "162 "), PLAYOFFS.AL/.NL, SCREENS/*.SCR, *.ANM, *.PAG, *.PAL, *.FNT, saved seasons.
