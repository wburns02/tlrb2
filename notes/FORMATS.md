# TLRB2 data formats

## Team file .V20 (11735 B, uncompressed). Decoded by Lane B 2026-10-06, code: tools/v20.py
295 B header + 80 player records x 143 B. Records 0-15 pitchers, 16-39 position players. Records 40-79 are the
same 40 players as the "current season" half (year+1, exp+1, season stats zeroed, ratings identical). The
Utilities editor writes ratings/bio to both halves. Edits proven by round trip: v20.py set (outside the game),
game editor shows the change (age, salary, first name, HR vs L verified on screen). Parse+serialize is byte exact.
Method: single-field edit in Utilities (work install), Main > QUIT is what writes the file, then v20.py diff.

Record offsets (dec, within the 143 B record). u16 is little endian. "hi/lo" = nibble of that byte.
- 0 last name (12), 12 first name (8), 20 age, 21 year-1870, 22 exp, 23 games, 25 u16 salary
- 27 u16 PORTRAIT INDEX (session 7, dynamic). 0..29 = generic colour face (ANMS\PORTRAIT.ANM; frames appended by tools/faces.py extend this up to 980), 981..1507 = real-player b/w photo (OLDPORT.ANM frame idx-981). Proved: all BAL batters set to 1000 showed one identical photo, CAL pitcher set to 3 showed a generic colour face. Twin halves hold the same value except 168 of 2200 pairs. (Session 6 saw no change only because a season game does not touch it.)
- 29: hi speed. lo: bit3 throws R (0=L), bits2-1 bats (1=R, 2=S, L presumably 0), bit0 portrait group flag (third header box; matched against UTIL DS:776e by the random face assignment, dark skin = 1, see session 7)
- 30: hi exper, lo consist. 31: hi pos2, lo pos1. Pos: 0 P,1 C,2 1B,3 2B,4 3B,5 SS,6 LF,7 CF,8 RF,9 DH,10 OF,11 IF,12 O/I,13 C/O,14 C/I,15 C/3
- 32 R, 33 RBI, 34 SH, 35 SB, 36 CS (u8)
- 37 AB_L, 39 AB_R, 41 H_L, 43 H_R, 45 2B_L, 47 2B_R (u16); 49 3B_L, 50 3B_R, 51 HR_L, 52 HR_R (u8);
  53 BB_L, 55 BB_R, 57 SO_L, 59 SO_R (u16). Totals shown by the editor are L+R.
- 61 grounder% x10, 63 gb pull x10, 65 gb opp x10, 67 fb pull x10, 69 fb opp x10 (u16). Fly% = 100 - grounder%.
- 71 pinch AB, 72 pinch H, 73 pinch HR (u8)
- 74 hi bunt lo power. 75 hi streak lo H&R. 76 hi day/night lo clutch. All 1..12 (editor clamps 13 to 12, ignores 0).
- 77 PO1, 79 PO2, 81 A1, 83 A2 (u16); 85 E1, 86 E2, 87 DP1, 88 DP2, 89 PB (u8)
- 90 u16 + 92 u16: RTO% shown = 90/92 x100. CONFIRMED session 6: a catcher faced 1 stolen base (no caught stealing) and u16@92 went 0->1, @90 stayed 0, so 90 = caught, 92 = attempts. 94 hi range lo arm
- Pitchers: 95 W, 96 L, 97 CG, 98 GS, 99 SHO, 100 SV (u8); 101 IP x10, 103 ER, 105 u16 (equals ER in 301/416, likely R) (u16);
  107 BFP_L, 109 BFP_R, 111 H_L, 113 H_R, 115 2B_L, 117 2B_R (u16); 119 3B_L, 120 3B_R (u8);
  121 BB_L, 123 BB_R, 125 SO_L, 127 SO_R (u16); 129 HR_L, 130 HR_R, 131 BK, 132 WP (u8). Pitchers store batters faced, AB = BFP - BB.
- Pitcher ratings: 134 hi velocity lo control. 135 hi endurance lo pitch4 type. 136 hi clutch lo streak. 137 hi pickoff lo day/night.
  138 hi Q1 lo release. 139 hi Q3 lo Q2. 140 Q4. 141-142 zero. Batters carry default values here.
- Pitch4 codes: 0 FASTBALL 1 CURVE 2 CHANGEUP 3 ? 4 SLIDER 5 SCREWBALL 6 SINKER 7 SPLITFINGER 8 FORKBALL 9 KNUCKLEBALL
- Display letters: day/night A..G = 1..7. Streak letters: stored A7 B5 C8 D6 E10 F4 G9 (other values unmapped).
- 140 hi nibble: "ratings are user-set" flag. 0 in all 3880 shipped players; the import path only recomputes ratings when it is 0. 141-142 u16:
  import id (matched by UTIL 5000:e298 against the id in an import line), 0 in all shipped players.
Stats-to-ratings (decoded 2026-10-06 Lane B s3 from UTIL 1000:b02a..b82f, implemented in tools/ratings.py, checked against every shipped player
with real stats: 99.7% to 100% exact per rating, 2 or fewer misses per ~670, zero-stat bench filler excluded). L+R means both split columns summed.
Stored in the ratings nibbles listed above. x = integer arithmetic exactly as in the code, see ratings.py for the 16 bit truncations.
- power (74 lo) = 1 + count of thresholds met by SLG x1000 = (H+2B+2*3B+3*HR)*1000/AB (rounded): 250 275 300 325 350 375 425 450 500 575 700.
- hit and run (75 lo): x = 10*(4H+2BB-3SO, floored at 0)/(AB+BB). 1 if 0, else 2 + count of (x>1,2,3,4,5,6,7,8,10,12).
- bunt (74 hi): s=10*(H-2B-3B-HR); x = 20*(s - min(s, 3SO+6HR))/(AB+BB). 1 + count of x>=4 8 12 16 19 21 23 27 31 35 40.
- speed (29 hi): x = 1000*max(SB-2CS,0)/(H+BB-2B-3B-HR) + 1000*3B/(30*2B) (each rounded), 1 + count of x>=1 2 4 6 9 15 20 25 90 150 240.
- range (94 hi) and arm (94 lo): per position row (pos1 -> row: C0 1B1 2B2 SS3 3B4 LF/CF/RF5; P, DH and the multi-position codes give 7).
  range = clamp(1..12, (PO1*a + A1*b + DP1*c - 100*E1, floored 0, + 50*G) / (100*G)); arm = same with (A1*d + DP1*e - 100*E1, + 25*G) / (50*G).
  Weights (a b c d e): C 140 200 0 500 2500, 1B 67 250 300 200 340, 2B 270 100 100 50 450, SS 320 130 100 133 100, 3B 600 200 200 200 300,
  OF 350 0 100 4000 3000 (table at UTIL ds:7490, 10 B per row). G is record +23.
- velocity (134 hi): o = outs = (IP10/10)*3 + IP10%10; x = (507*o + 540*SO - 1080*H if positive else 0, + 20*o) / (40*o), clamp 1..12.
- control (134 lo): x = max(2, (999*BB + 10*o)/(20*o)); rating = 14 - x if x < 14 else 1.
- endurance (135 hi): x = (min(CG,20)*G + IP10 + 2*(IP10%10))*10/G, rating = clamp(1..10, (x+50)/100) (about IP per game + CG/10).
- Not auto-derived: streak, clutch, day/night, pickoff, Q1..Q4, release, pitch4, consistency, experience.
- When a player is imported, PO1 and A1 are overwritten with PO130[pos]*G/130 and A130[pos]*G/130 (UTIL ds:7a14 and ds:7a28, per 130 games:
  PO P29 C657 1B982 2B233 3B82 SS189 LF193 CF300 RF206, A P60 C56 1B83 2B317 3B218 SS352 LF4 CF5 RF8), before range and arm are computed.
- UTIL 5000:a5aa/f382/f697 compute the player SALARY (record +25 u16, clamped 109..9999), decoded in session 4 and implemented as tools/ratings.salary(). Batter f382: obp+slg+30*HR+7.5*RBI plus bonuses, position arm/range adjustments via jump table at 5000:f687 (C f58c, 1B f62a, 2B f5b0, 3B f5cc, SS f605, LF f61d, CF f5a1, RF f61d), scaled by PA/575 under 525 PA. Pitcher f697/a5aa: class by a719 (starter vs reliever), x*115/100. Check vs 57 shipped V20s (salary 0 excluded): batters 1185/1188 exact, pitchers 772/792 (misses mostly 2 to 6 off, 3 batter and 4 pitcher outliers of hundreds, likely hand-edited values or a branch not modelled).
Header (295 B) decoded 2026-10-07 (Lane B), evidence = Manager-screen single-edit diffs + MANAGE code (team buffer ptr DAT_2000_c73c):
- +0 team name (14, 13 chars + NUL), +14 league code (2, "cl"), +16 team abbreviation (3, 'KC' NUL padded), +19 stadium stem (8 B,
  NUL terminated, the file STADIUMS/<STEM>.CFG/.SDM on the CD: 'grass', 'TURF', 'ASTRO', 'COMISKEY'; bytes after the NUL are stale,
  e.g. 'CFG'), +27.. zeros to +43. (Earlier note "+16 stadium stem BALgrass" was wrong: 'BAL' is the abbreviation.)
  Proved 2026-10-06 session 3: Edit Team Names changes +0 and +16 (MAJ too), Assign Stadiums changes +19 only ('grass' -> 'ASTRO'),
  outside edit with tools/v20.py shows on the Edit Team Names / Assign Stadiums (Oakland Coliseum) / Team Colors screens.
- +44..+91 (48 B) TEAM COLORS: main color 8 shades x (r,g,b) at +44, accent color 8 shades at +68; VGA DAC 6 bit values (0..63), light to
  dark. Edit Team Colors writes all 48 B when a swatch is clicked (main swatch #4 = (25,24,36)..(4,3,15), accent swatch #7 =
  (63,35,30)..(13,1,0); classic Baltimore main black (8,8,8)..(3,3,3), accent orange (63,23,0)..). tools/v20.py Team.colors()/set_colors().
  (The old guess "computer-manager tables copied by MANAGE FUN_1000_f120" is the colour block: f120 copies it into DGROUP 0x4f89/0x4fb9.)
- +38 u8 wins, +39 u8 losses (season record; BACK writes them at Main > QUIT, Start New Season zeroes them).
- +108 u8 team "last day aged" for MANAGE (1000:ce08 loops from this to MAJ+0x20a and ages byte 24 of players 0..39).
  BACK also writes the day index of the team's last game here (189 for a team that finished the regular season, 211 for WS finalists).
- +109 u8 streak: bit7 = loss streak, low 7 bits = length (BACK 1000:95da on a win, 1000:95fb on a loss). Zeroed by new season.
- +110 u8 starting-rotation pointer 0..4, advanced (idx+1)%5 by BACK's starter chooser 1000:9d84. Zeroed by new season (when nonzero).
- +111..+120 pitching staff (10 player indices): 111..115 = 5 starters in rotation order, 116..120 = 5 relievers. +121 = 0xff.
  Pitching Staff swap active<->reserve changes one slot (proved); Rotation swap exchanges two slots (proved).
- Lineups, 4 sets, index = dh*18 + vs*9 where dh 0 = no-DH, 1 = DH; vs 0 = LHP, 1 = RHP (verified on screen for DH L/R and no-DH R):
  +122 batting order (9 slots; no-DH sets hold 8 players then 0xff; DH sets 9), 4 sets of 9 B -> +122..+157
  +158 defensive position per slot (4 x 9, position codes as in the V20 pos table: 0 P, 1 C..9 DH). No-DH sets end with 0 (pitcher).
  +194 bench = remaining active batters, 4 x 7 slots, 0xff padded (no-DH 7 players, DH 6 + 0xff) -> +194..+221
- +222..+236 reserves: 15 player indices (6 pitchers + 9 batters). Active 25-man = 10 pitchers + 15 batters; the whole file is a
  partition of the 40 players. Active<->reserve swap rewrites the player in every list that held him (lineups, bench, reserve slot).
- +237..+243: Draft GM profile, 7 percentage bytes that must sum to 100 (DRAFT 2000:ecfd resets to the preset if not). +244: preset index 0..5, 5 = custom (no table copy). Presets (DRAFT ds:10e6, 7 B each): 0 = 20 20 5 5 15 15 20 (all CLASSIC teams), 1 = 20 15 5 5 25 15 15, 2 = 20 15 5 20 5 15 20, 3 = 25 20 10 5 10 10 20, 4 = 20 15 5 10 10 10 30. Category labels live in profile2.scr, not decoded. Used by the draft screen "GENERAL MANAGER PROFILE" (DRAFT 2000:f6c9 applies a preset, 2000:f0c1/e3e8 callers). tools/v20.py: gm_profile/set_gm_profile.
- +245..+259 manager strategy sliders (Manager > Manager Profile, 5 tabs x 3), stored = RIGHT-hand number x 10 (50 = 5/5):
  LINEUP: speed/power, defense/hitters, endurance/ERA; PITCHING: starters-in/yank'em, starters-in/pinch-hit, pitch-around/challenge;
  BATTING: sacrifice/hit-away, squeeze/hit-away, hit&run/play-safe; DEFENSE: walk/pitch-to, infield-in/normal, pitchout/throw-strikes;
  RUNNING: aggressive/safe, steal-2nd/safe, steal-3rd/safe. Proved: 15 values 30,80,40 40,90,20 10,60,30 80,20,60 90,10,70 for the
  screens' (7|3 2|8 6|4 / 6|4 1|9 8|2 / 9|1 4|6 7|3 / 2|8 8|2 4|6 / 1|9 9|1 3|7). +247 is used in MANAGE 1000:5e78 (advice score).
  +260..+264 stay 0x32 (unused), +265..+294 zero.
- Injury roll (BACK 1000:98f3, called from 1000:978f after a game, only if MAJ injuries flag set): for a pitcher a workload ratio
  a = (games-count byte per player at DS+0x17e1 * 100 / (days elapsed+5)) * (season length) / (pitcher durability byte at record+0x62), roll
  random(0..999) < (a-100)*10; for a batter a = byte(+0x1796)... threshold 115, chance (a-115)*5. Duration table from a second roll r=random/10+1:
  r<26 -> 1, <41 -> (r-0x18)/10+2.., slow growth, capped to 2..14, stored into DU byte (record+0x18) low bits (injury, no REST bit).
- Player record byte 24 (0x18) = DU column "days unavailable": low 7 bits = days, bit 7 = REST ("R" suffix: 0x85 -> "5R", 0x03 -> "3",
  0x92 -> "18R"). BACK sets bit7 on pitchers after they pitch (0x85 after 8.2 IP / 30 BF, 0x82 after 1 BF); a starter is eligible when
  the byte is 0 or 0x81. Aged by 1 per league day, 0x81 -> 0. Values 1..0x7f without bit7 are injuries. Proved in game
  (Roster/Staff/Rotation screens). Only records 0..39. Start New Season zeroes it.
- Season stats (M3, traced on a full 162 game season + playoffs): BACK accumulates into records 40..79 at the same field offsets
  as the stat half documented above (games +23, AB, H, ...; pitchers W +0x5f, GS +0x62, IP*10 +0x65, BF +0x6b/0x6d). Record
  byte +0x85 (133) mostly tracks games, semantics unknown. Start New Season zeroes every stat byte in 40..79 and keeps
  name/age/year/exp/ratings. Records 0..39 are untouched by a season (no in-season progression; byte 24 only).
- tools/v20.py: `hdr FILE`, Team.staff/lineup/defense/bench/reserves/strategy, set_list, set_strategy, player 'injury'. In-game proof
  (shot rt2.png): header edited outside the game shows on Pitching Rotation (swapped starter), injury "8R", file parse+serialize byte exact.

## League file .MAJ (CLASSIC.MAJ 59771 B). Decoded by Lane B (M3), code: tools/maj.py
Round trip proven: maj.py edit of W/L (outside the game) shows on Season > Standings (shot rt_maj2.png: Baltimore 99-63,
Chicago N 111-51). The game recomputes ordering and GB on load, so only W/L need editing. All offsets below are file offsets.
Old-format MAJ = 58789 B; UTIL 4000:74ad upgrades 0xE625 to 0xE97B.
- +0 league name (8). 10 B entries: 2-char league code + 8-char team stem ("clclasale1"), divisions of 8 slots, then ALLSTAR1/2.
  16 B team name+code entries from 0x22b, 3-letter abbreviations after 0x3a0 (names region partially decoded, see Setup Leagues).
- Global header bytes: +0x20a current day index (0 = April 1; 7 = new season start, 0xf3 = season over), +0x20b games (0xa2 = 162),
  +0x20c/0x20d leagues/divisions (2/2), +0x20e/0x20f AL East/West team counts (7/7), +0x211/0x212 NL (6/6),
  +0x214 first game day (8), +0x215 last regular-season day (0xbe = 190), +0x216/0x217 AL/NL LCS start (0xc0), +0x218 WS start (0xcb = 203),
  +0x21a/0x21b LCS and WS series length (7/7), +0x21c All-Star game day (0x6b = 107; 0 once passed or declined; 0x6a after new season).
  Day 203 = Oct 21, 107 = July 17. The Start New Season screen shows idx+1 as the date.
- Two league blocks, S = 0x21d (AL) and 0x758c (NL), size 0x736f. Team slot = division*8 + i (East 0..6, West 8..14; slot 7 unused).
  Offsets from S:
  - +0x297 DH flag (AL 1, NL 0 in classic). PROVED (session 3): the Start New Season "SET DH FOR LEAGUES" dialog writes it (A=NO DH, N=USE DH
    gave AL 0, NL 1 after the new season) and an outside edit with maj.py set_dh shows as the checkmarks in that dialog (shot n13). The earlier
    run failed because the radio rows only react to clicks on the checkmark column (x=445 in screen coords, rows y380/418), not on the text.
    BACK 1000:~9654 copies S+0x297 of the game's league into the game record (+0x1c19).
  - +0x35b of the AL block (file 0x578) = INJURIES ON/OFF (1 = on). PROVED: "Do you want injuries to occur during the season?" NO -> 0, YES -> 1
    (NL block's byte stays 0, only the AL block copy is read: BACK DAT_3000_1842+0x35b). Gate for the injury rolls in BACK 1000:98f3, c18b, c278,
    c750 and the season loop 4ed3/5cc8.
  - +0x298/0x299 East/West team counts.
  - +0x2b3 24 B standings order: East slots, 0xff, West slots, 0xff, then ff padding. All ff before play and after new season. Derived.
  - +0x2cb W[24] u8, +0x2e3 L[24] u8, +0x2fb GB*10 u16[24] (derived).
  - +0x3d3..0x3eb playoff data, cleared by new season: team ids of the playoff field (`ff ff ff ff 0c 03 0c 15` after the playoffs)
    and 8 B of series win tallies.
  - +0x3eb schedule: day d row at S+0x3eb+16*d, up to 8 games as (away, home) pairs, 0 0 = none. Ids are league-global (NL = slot+16).
    Rows 0..7 empty in classic (first game day 8). 244 rows.
  - Results, 244 days x 32 B (first 16 B = per-game values in schedule order): +0x1607 runs (away, home pairs), +0x3487 hits (likely),
    +0x5307 errors (likely). Checked against the in-game Game Scores screen for April 9 (Cle 4 Bal 0, Tor 4 Det 8, Min 2 Mil 6, KC 1 Oak 5, Tex 6 Sea 1).
  - +0x7187 u16 per day game-played bitmask (bit7 = game 0; 0xf8 = 5 games).
  - +0x132b / +0x141f / +0x1513: three 244 B arrays, one byte per day, bit 0x80>>g = game slot g of that day (decoded session 3 from
    BACK 1000:5bfe/5a65/rain code and MAIN 6000:0ba2, checked against m3_end data):
      +0x132b DOUBLEHEADER flag: slot g plays twice. Second game's runs/hits/errors are in the second 16 B half of the 32 B day row
        (offset 16 + 2g), its played bit in the second byte of the +0x7187 u16. Template has a few (3 bits in classic); BACK's rain
        code (1000:5c...) turns a game into a makeup doubleheader (random < table at DS:0x12a[month], not for teams flagged at +0x29b[team&15],
        which stay 0 in classic): it clears the game from the day row, flips the flag of the same pairing on day+1 and clears its night bit.
      +0x141f CANCELLED flag: a set bit makes the sim skip the game (all 0 in classic).
      +0x1513 NIGHT game flag, randomised when a season is set up (MAIN 6000:0ba2): day%7 in {0,1} never, 3 -> 80%, 4 -> 66.7%, else always,
        and never for doubleheader slots. All playoff days 0xff.
    Per-game result cells: runs (+0x1607), hits (+0x3487), errors (+0x5307) hold (away, home) byte pairs per slot, copied from BACK's game
    record 0x1beb/0x1bec runs, 0x1bed/0x1bee hits, 0x1bef/0x1bf0 errors by BACK 1000:5a65.
  - +0x7187 u16 per day: byte0 bit = game 1 of slot g played, byte1 bit = doubleheader game 2 played.
  - Names/IDs of the 16 team slots (slot = division*8+i, 15 = all-star team, 7 unused), decoded session 3 with Edit Team Names:
      +0x00 league name (15 B, NUL terminated; the stale " LEAGUE" text behind it is leftover), +0x0f team entries 16 B each (name 14 B
      + league code 2 B "cl") up to +0x10f, +0x18f 3 B abbreviations x16 ('KC' padded), +0x1d7 8 B file stems x16 ("clasale1" is the
      V20 name TEAMS/CLASSIC/CLASALE1.V20 without extension, "ALLSTAR1" in slot 15).
    Proof: names/abbr/league name edited in the game land in MAJ AND the team's V20 (+0, +16); a MAJ edit with tools/maj.py shows on
    the Edit Team Names screen. Edit Team Names changes nothing else.
  - +0x35b: 1 in the AL block, 0 in NL, never changes. = injuries ON/OFF flag (PROVED, see line above).
  - Global +0x20c/+0x20d = number of leagues / divisions per league. Setup Leagues "# OF DIVISIONS 2 -> 1 (clear the West)": 0x20d 2->1,
    AL west count (S+0x299) 7->0, NL west count 6->0, first byte of every west team name entry/abbr/stem zeroed, day idx 0x20a -> 0xf3.
- Tail 128 B at 0xe8fb: 8 entries x 8 u16, static park-factor-like data (1503, 468, 45, 177, 860, 1424, 177, 10000). Never changed by any sim.
- Start New Season diff (m3_end vs after, 2302 runs): +0x20a 0xf3 -> 7, 0x214..0x218 <- template, +0x21c <- 0x6a, standings, results
  and playoff data zeroed, schedule rows rewritten from the .SCH. No other MAJ bytes change. DH and injury choices are not in
  the MAJ, SYSTEM, or any other data file (diff -rq of the whole install shows only CONTROL, V20s, MAJ, PLAYOFFS.AL deleted).

## Other files
- CONTROL (9 B, read by CONTROL.EXE FUN_1228_0007 into DS 26cc..26d3): [0] calling program (1 MAIN, 2 BACK), [1] next program
  (1 MAIN, 2 BACK, 3 BB, 4 MANAGE, 5 UTIL, 6 DRAFT, 7 quit), [2] current day idx, [3] play-to day idx (0xf3 = season over),
  [4..6] flags (e.g. 01 00 00), [7..8] ff ff. Examples: `01 02 08 09 01 00 00 ff ff` (MAIN to BACK, day 8, play to 9),
  `02 07 ...` after quitting from BACK, `01 07 00 00 01 00 00 ff ff` after Start New Season.
  TONY2.BAT loops PLAY then CONTROL, which dispatches on the errorlevel.
- Season flow: Main "Play League Games" writes MAJ, CONTROL, SYSTEM then BACK simulates in memory. V20s are written at Main > QUIT,
  not during the sim. BB is only used to watch games.
- SYSTEM (76 B): see "SYSTEM file" below (Lane B8).
- .SCH templates (162_26.SCH, 162_28.SCH, 162_2_26.SCH, 162_2_28.SCH; 57176 B): text name ("162 Games-26 Teams"), then a settings
  block at 0x3e..0x50 (same shape as MAJ 0x20a..0x21c), then the AL schedule rows at +0x50+16*d (byte identical to the MAJ rows after
  new season, 0 mismatches over days 8..243), NL rows at +0x6fd4+16*d (day 0 start). Rest not decoded. Bytes 0x14..0x3d are stale
  buffer garbage (x86 code fragments), ignore.
- PLAYOFFS.AL / .NL (59569 B = 1 + 8 x 7446): byte 0 = games played in the series, then 8 game-state records of 7446 B = the GAME.TMP
  layout (per-batter 6 B entries `ff ff ff 00 00 00` empty at record+0x130d..0x14f3, team stems as ASCII near record+0x1c02).
  Created during the playoffs (O_RDWR|O_CREAT after each game); PLAYOFFS.NL deleted at the WS, which uses PLAYOFFS.AL; both gone
  after Start New Season. In-UI box scores come from here.
- Start New Season flow (Season menu y319): schedule list (162 Games-26 Teams, 162 Games-28 Teams, 162 Games(2)-26 Teams), games,
  start date, series lengths, required vs current league panels, NEW SEASON (430,592). YES/NO warning, Set DH dialog, injuries question,
  then Play Standard Games. Effects listed under MAJ and V20 above.
- Still TBD: GAME.TMP internals (rest), big replay ANM payload. SYSTEM, PAL, SCR, PAG, FNT, ANM/OVL, OLDPORT, STADIUMS and saved seasons are in the Lane B8 sections at the end.

## GAME.TMP and saved games (Lane B s3, 2026-10-06, rig runs gt_*.tmp in /mnt/nvme/tlrb2/snaps)
- GAME.TMP is the MAIN to BB hand-off, rewritten on every Play Ball (PLAY BALL on the lineup screen). Size 0x1d16 = 7446 B (the "0x11d16" in the decompile is
  a stray prefix). Writer MAIN 4000:d07d (called from the pre-game menu loop 4000:cf80), reader BB 6000:c4da. 1.SAV..10.SAV are the same 7446 B format
  (written by the in-game Escape menu > Save Game, plus the play log below); the save list caption ("EXHIBITION: BAL VS CAL (0 - 1) 2ND INNING, NO OUTS") is not in the file.
- 0..4821: all zero at game start. In a saved game bytes at 0,80,260,305,480.. etc. become 1 (per play log, not decoded).
- 4822..~6650: 3 byte records at stride 6, FF FF FF at start (log slots, not decoded).
- Lineup, defense and pitching block 6763..7142 and ground rules: fully decoded in session 4, see the "GAME.TMP session 4" block below (the earlier lines
  that said the Ground Rules switches are not in the file were wrong, they were read from runs whose switch states persisted from the previous run).
- 7143: night game flag (0 day, 1 night) = buffer +0x1be7. Proven by single-factor runs.
- 7169: three NUL-less names: HOME team file stem (8, e.g. "clasale1" = CLASALE1.V20), VISITOR stem (8), set directory ("classic", NUL ended). Proved with
  two team pairs (California visitor vs Baltimore home gives clasale1 first, so the first stem is the HOME team).
- 7402..7416: per-game random bytes (differ between identical setups): probably weather, wind and temperature (7413 values 0..20, 7415/7416 vary widely).
- 7419: stadium index byte (0x25 grass at Baltimore, 0x26 TURF at Texas), 7420..7427: stadium stem (8 B, stale bytes after the NUL, e.g. "TURF\0CFG").
- 7428..7445: Ground Rules, see below.


## GAME.TMP session 4 (Lane B, 2026-10-06): lineups, ground rules (decoder: tools/lane_b/gt_decode.py, verified on 14 captured runs)
Buffer = BB far pointer DS:aa2a (read by BB 6000:c4da), MAIN writes it from DS:9b7c (4000:d07d). All offsets are file offsets = buffer offsets.
Side 0 = VISITOR, side 1 = HOME everywhere in this block (the stems at 7169 are home first). Player ids are V20 record numbers 0..39 (0..15 pitchers).
- 6763 lineup 2 x 9 (visitor, home): batting order player ids. With the DH the 9 batters, without the DH 8 batters then the starting pitcher's id.
  The list is the V20 header lineup set for (DH on/off, opposing starter's hand: throws R -> "vs RHP" set), see Team.lineup(dh, vs_rhp). Proved for DH on and off.
- 6781 defense 2 x 9: position code per lineup slot (0 P, 1 C .. 8 RF, 9 DH), same lists as Team.defense(dh, vs_rhp).
- 6799 batters not in the lineup, 2 x 22 B (15 or 16 ids then 0xff pad): active bench first, then the reserve batters, as in the header bench + reserves.
- 6843 starters 2 x 5 (visitor then home, V20 staff[0..4]); 6853 pitchers 2 x 21: relievers 5 (staff[5..9]) then 6 reserve pitchers, 0xff pad to 21.
- 6895 in-game flag 2 x 40 (indexed by player id: 1 = in the lineup or the starting pitcher). 6975 batting slot 2 x 40: 16 + slot (0..8) for batters, 25 for the
  pitcher. 7055 defense position code 2 x 40 per player id (0 = not in the field list). 7139/7140: current pitcher id of visitor/home (starter at game start).
- 7143 night flag (buffer +0x1be7). 7193 DH flag (+0x1c19), same byte BACK keeps at game record +0x1c19.
- Ground Rules, GROUND RULES dialog in BB (control ids 2..0x37, query function BB 7000:24b0 reads these bytes): 7428 computer pipes ball (+0x1d04),
  7429 errors (+0x1d05), 7430 injuries (+0x1d06), 7431 use stats (+0x1d07), all 1 = YES. 7432 one pitch mode, 7433 auto replays, 7434 sound effects,
  7435 bit0 voice and bit1 crowd (03 = both), 7436 music, 7437 quick off the field, 7438 scrolling (any nonzero = yes; shipped values f9/f2).
  7439 animation speed (4 = very fast). 7440 control of the right-hand panel team (visitor), 7441 left-hand panel team (home): 0 PLAY, 1 MANAGE ONLY, 2 COMPUTER.
  7442 / 7443 input device of visitor / home (0 keyboard, 1 joystick 1, 2 joystick 2, 3 mouse). 7444 constant 0x68. 7445 low 3 bits: AUTO fielding, throwing, running
  of the HOME team (bit set = yes; the visitor auto bits are not separately proven). BB 7000:231f copies 7432..7445 and
  the DH/night/rules bytes into the environment struct at DS:aa1a (+8..+0x1a).
  Proof: single-factor runs from a known all-YES state flip exactly one byte each (errors 7429, injuries 7430, pipes 7428, stats 7431, DH 7193 plus the DH
  position 9 in the lineup, night 7143); general rows 7432..7438 all went to 0 together; control/input/auto bytes changed with the panel clicks.
- Persistence: MAIN stores the Ground Rules in SYSTEM bytes 8..0x19 (+9 pipes, +0xa errors, +0xb injuries, +0xc stats, +8 DH, +0xd.. the general rows, +0x13.. control/input/auto; corrected in Lane B8, see "SYSTEM file")
  and writes SYSTEM at game start, so the next game starts with the last used rules. Night is not persisted. That is why early single-switch runs looked like "no effect".
- The play log: bytes 0..4799 are 60 x 80 B? of small counters (the saved game has 01/02 at 0,1,80,81,260,305,...), 4800..4821 and 4822..6762 6-byte entries
  `ff ff ff 00 00 00` when empty; not decoded (needs a long saved game with a known box score).

## GAME.TMP session 5 (Lane B5): play log, accumulators, ALLTIME.BOX, rules bits
Buffer offset == file offset in GAME.TMP (7446 B). tools/lane_b/gt_log_decode.py decodes and self-checks against the game 2 box score (snaps/s5_g2.ALLTIME.BOX).

ALLTIME.BOX record (post-game box score SAVE button): 7196 B = 2 byte header (0e 00 seen) + buffer bytes 0..7193. Writer address not located.

Play log (scoring half-inning log):
- 18 rows x 108 B at 0x12d3, each 18 events x 6 B. Row counter at 0x12c0 (cap 0x12). Rows 0..cnt-1 are scoring half-innings, row cnt is the tail row holding the latest events. Empty event = 00 00 00 ff ff ff.
- Row advances when the batting side's run total (0x1beb visitor, 0x1bec home) changed after the play step. Verified: game 2 (CAL 3, BAL 5) gives cnt 7.
- Event: b0 bit0 = batting side (1 home), b0>>1 = fielding pitcher id. b1 = batter id<<2 | hand split. b2 = result code (table not decoded; 0x1f probably HR). b3..b5 = runners on 1B/2B/3B before the play, id | adv<<6, ff empty. Runner at base j (0 = first) scores if j+adv >= 3.
- Writer BB 6000:7e7b (row = buf + [0x12c0]*0x6c + slot*6), counter bump BB 6000:7e65, callers 6000:75fb and 6000:8100.

Accumulators (session 5 text, visitor only; superseded by session 6 section below, both teams exist at stride 0x8e8):
- Pair arrays at 440+80k, index 2*id+split: k0 AB, k1 H, k2 2B, k3 3B, k4 HR, k5 BB, k6 SO, k13 E. k7, k8, k11, k12 unknown (SB/CS candidates). Single bytes: 0xf0 R, 0x118 RBI.
- Game 2 sums over all 40 slots match the CAL box totals: AB30 H4 2B1 HR2 BB3 SO4 E1.

Ground rules bits: 7444 low 3 bits = visitor AUTO (bit0 fielding, bit1 throwing, bit2 running, 1 = yes), 7445 low 3 bits = home AUTO. Upper bits constant (0x68, 0xc0). Proven with 0x6f and 0x6a runs. 7436 music = SYSTEM+0x1a. MAIN 4000:e968 maps SYSTEM to buffer, 4000:eae4 maps buffer to SYSTEM. SYSTEM persists the last rules.

Salary: no missing term; era100 (UTIL 1000:9e5f) verified, outliers are twin records.
Portrait index: u16@27, dynamically proved in session 7 (see Session 7).

## Session 6 (Lane B6): season game merge, result codes, ALLTIME.BOX writer
Season Featured game CLEVELAND 2 at BALTIMORE 1, April 9 (CLASALE3 vs CLASALE1), both computer controlled, snapshots s6_before/s6_after. tools/lane_b/gt_merge_check.py prints per-team field sums of the V20 deltas.

Merge (BB 6000:3407, confirmed). Called from 6000:7190 when the game completes, only if buf[0x1bf4]==0; sets buf[0x1bf5]=1. It merges into the V20 records held in BB memory, the V20/MAJ/SYSTEM/CONTROL files are written when BB exits (after DONE on the box score), not at game end (no file touched between game end and DONE). GAME.TMP is not rewritten.
- Every record 40..79 delta matches the box score: CLE AB32 R2 H6 2B1 HR1 RBI1 BB4 SO4 SB1, BF34 pH10 pSO3 IP 9.0 (90) ER1 RA1 W1 CG1 GS1; BAL AB34 R1 H10 RBI1 SO3 E1, BF36 pH6 p2B2 pHR1 pBB4 pSO4 IP 9.0 (80+10) ER1 RA2 L1 GS1. Fielding PO 27 and A 19/17 per team, DP in +0x57.
- RTO pair: Severeid (BAL C) u16@92 0->1 for Jackson's one SB, u16@90 unchanged (SB 1, CS 0). RTO merge confirmed, arrays 0x690 (a, caught) / 0x6b8 (b, attempts).
- +0x85 and +0x17 both +1 for every player who appeared (15 per team, pinch hitters and defensive replacements included). +0x85 is a second games/appearance counter that equals +0x17 in a fresh league.
- Batted-ball distribution fields +0x3d..0x45 are SET (not added) from the game GB/fly counts: u16 values 1000, 666, 500, 154... = x10 shares; fly% = 100 - grounder%.
- Team header: +0x26 wins, +0x27 losses (CLE 0->1, BAL 0->1). +0x6d: CLE 0x01, BAL 0x81 (streak 1, bit7 = losing, probable). +0x6e both 0->1 (games count, probable). +0x6c 13->8 is the MANAGE "last day aged" pointer (day 9 minus one).
- Starter record 0..39 half: only byte 24 (+0x18) changes, 0->0x85 for both starters (rest bit + 5 days), as documented in the injury notes.
- CLASSIC.MAJ: +0x20a day 8->9, plus standings order, W/L, run/hit/error grids for the day (110 bytes in all, whole league day simulated).
- Portrait u16@27 not modified by the merge.

Game buffer accumulator layout (both teams, team t block base = 0xf0 + 0x8e8*t, 40 slots by id):
- singles (40 B): +0x00 R, +0x28 RBI, +0x50 SH, +0x78 SB, +0xa0 CS, +0x2f8 GB count, +0x320 gb pull, +0x348 gb opp, +0x370 fb pull, +0x398 fb opp, +0x3c0 pinch AB, +0x3e8 pinch H, +0x410 pinch HR, +0x578 PB, +0x5a0 RTO a, +0x5c8 RTO b, +0x5f0 outs (+7 correction when %10>2 gives 3 outs = 30 in IP x10), +0x618 ER, +0x640 R allowed, +0x898 BK, +0x8c0 WP. (Buffer offsets from base 0xf0: 0xf0 R, 0x118 RBI, 0x140 SH, 0x168 SB, 0x190 CS, 0x3e8 GBc, 0x410 gbpull, 0x438 gbopp, 0x460 fbpull, 0x488 fbopp, 0x4b0 pinchAB, 0x4d8 pinchH, 0x500 pinchHR, 0x668 PB, 0x690 RTOa, 0x6b8 RTOb, 0x6e0 outs, 0x708 ER, 0x730 RA, 0x988 BK, 0x9b0 WP.)
- pairs (2*id+split, 80 B): 0x1b8 AB, 0x208 H, 0x258 2B, 0x2a8 3B, 0x2f8 HR, 0x348 BB, 0x398 SO, 0x528 PO, 0x578 A, 0x5c8 E, 0x618 DP, 0x758 BF, 0x7a8 pH, 0x7f8 p2B, 0x848 p3B, 0x898 pHR, 0x8e8 pBB, 0x938 pSO.
- The session 5 unknowns k7/k8 (0x3e8..0x488 region) are the GB / fly distribution counters (GB count, gb pull, gb opp, fb pull, fb opp) feeding +0x3d..0x45; k11/k12 are PO (0x528) and A (0x578). SB/CS are the singles at 0x168/0x190, not pair arrays.
- Verified live: HR adds R, RBI, AB, H, HR to the batter and BF, pH, pHR to the pitcher; walk adds BB and BF/pBB; strikeout adds AB, SO, pitcher pSO, catcher PO; groundout/flyout adds AB, GB or fly counter, fielder PO and A, outs +1 (outs byte +8 when the third out is made: 3 outs stored as 30 after correction).

Result code b2 of the 6 B play-log event (assigned in BB 6000:8100 tail 0x8693..0x87f5, jump table at flat 0x58810 keyed by class ab3d):
- Observed in a full game: 0x0c/0x0d/0x0f singles (0x0c with RBI), 0x13 double, 0x21 HR, 0x27..0x2a ground outs (0x27,0x29 gb pull, 0x28,0x2a plain/opp), 0x30..0x33 and 0x3b, 0x47, 0x48 fly outs (0x30..0x32 fb pull, 0x3b/0x48 fb opp), 0x49 walk, 0x4c strikeout, 0x4e ground out variant (probably forced/other).
- Formulas (static): class0 = 0x0c..0x0f (singles), class1 = 0x10+zone (zone ab3a 0..6, doubles; 0x13 = zone 3), class2 = 0x17+zone (triples), class3 = 0x1e+zone (HR; 0x21 = zone 3, center), class4 = 0x49 (walk) or 0x4d (probably HBP), class5 = 0x4c (strikeout), class7 = batted-ball outs 0x25+ab4a (ground), 0x2e+ab4a, 0x37+ab4a, 0x40+ab4a (fly/other groups), 0x0b; overrides 0x4a, 0x4b, 0x51, 0x4e. ab4a 0..8 is probably the fielder position index. The four class7 groups and class6 are not fully separated by this single game; exact ab4a meaning and 0x4a/0x4b/0x4d/0x51 are unverified.

ALLTIME.BOX writer: BB 6000:c6c1 (stub 508c:0025): fopen(DS:3be2 name, DS:3bee mode), fwrite 2 B word 0x000e, fwrite DS:aa2a for 0x1c1a (7194) bytes. Called from 6000:d396 inside the box score menu dispatch 6000:d277 (SAVE; guard buf[0x1bf4]!=3 and buf[0x1bf5]!=0) and a twin at 6000:e476. Static only; the SAVE button was not pressed in session 6 (no new ALLTIME.BOX), the file layout matches the session 5 file. In the season game flags were buf[0x1bf4]=0 and buf[0x1bf5]=1 at end.

## Session 7 (Lane B7): box score SAVE, result codes, portrait index

ALLTIME.BOX SAVE, dynamic. Box score SAVE button (390,592) after a season Featured game: DOSBox log shows seek to end, "Writing 2 bytes", "Writing 7194 bytes". File opened with name DS:3be2 "alltime.box", mode DS:3bee "ab" (append). Record = u16 0x000e + 7194 B copied from the game buffer (far ptr at DS:aa2a, GAME.TMP layout); two live host copies of the buffer matched file bytes [2:7196] with 0 diffs. A second SAVE click appended an identical record (7196 -> 14392 B). DONE afterwards wrote the season files. Writer BB 6000:c6c1.

Portrait index = V20 player record u16@27 (+0x1b). BB 7000:da0a: idx < 0x3d5 (981): fseek(FILE DS:d6d0 portrait.anm, idx*0xa8c+0xe); idx >= 0x3d5: fseek(FILE DS:d6cc oldport.anm, (idx-0x3d5)*0xa8c+0xc); then fread 0xa80 B (56x48 bitmap), remap, blit. Files opened by BB 7000:d9a3. Callers 7000:be90 (stats modal), 7000:c8d0 (player report), 7000:d387 (scouting). Play screen shows the batter portrait bottom left and pitcher bottom right (those use it). Dynamic proof: see u16@27 line in the player record layout.
Portrait team colours (2026-10-08, static + rig-proved with appended faces): da0a calls BB 2000:b6df with 0x10 (one team) or 0x20 (the other). It remaps 48..63 and 64..79 as two 16-entry team blocks (0x10: 64..79 -> 48..63; 0x20: 48..63 -> 64..79). In a face, 48..55 is the primary team ramp and 56..63 the secondary.
Byte 29 (+0x1d) bit0 = portrait group flag (static only, not dynamically tested): UTIL 5000:ea5e picks a generic face whose flag in UTIL DS:776e equals rec+0x1d & 1, least used first (counts UTIL DS:bfb0). Probably light/dark skin tone. 776e = 00 00 00 01 01 00 00 00 00 00 00 00 00 00 00 00 01 00 01 00 01 01 01 00 00 01 00 01 00 00. Record copy to next-season twin copies +0x1b/+0x19 (UTIL 5000:9cd5, MAIN 5000:f1ce, DRAFT 1000:5589); blank record init sets +0x1b=0 (UTIL 5000:e89d).

Result codes (ab4b), observed in 3 more exhibition games (~2170 events, tools/lane_b/rc_sniff.py, rc_games.sh, rc_summarize.py) in addition to session 6:
- Class (ab3d) is drawn in BB 2000:3744 as the first of 7 cumulative per-mille ratings (built in 2000:3124) above a random 0..999, else 7. Class 6 (the 7th slot) never sets a code (seen only as a transient with ab4b=0xff).
- CONFIRMED singles class0: 0x0c (zone<2, fielder LF/CF/RF), 0x0d (zone 2..4), 0x0e (zone 5+), 0x0f (infield single, ab4a<6).
- CONFIRMED doubles 0x13..0x16 (class1 = 0x10+zone, zones 3..6 seen), HR/class3 0x1f..0x24 (0x1e+zone; 0x21 = zone 3, 0x22 = zone 4). Triples class2 0x17+zone: NOT observed (rare).
- CONFIRMED class7 outs: ground out 0x25+ab4a (0x25 P, 0x27..0x2a for 1B..SS), fly out ab49=0: 0x2e+ab4a for ab4a<6 (0x30..0x33), ab49=1 (ball x<0x10): 0x37+ab4a (0x37 P, 0x3c SS), ab4a>=6: 0x40+ab4a (0x46 LF, 0x47 CF, 0x48 RF).
- CONFIRMED 0x49 = walk (class 4, ab48=0), 0x4c = strikeout (class 5), 0x4d = class 4 with ab48=1 (the ab48=1 pitch result branch at BB 2000:724a; hit-by-pitch or intentional walk, which of the two not separated), 0x4e = ground-ball double play (class 7, ground, 2 outs on the play, DS:35eb == 2), 0x4a = class 7 batter-reaches-on-error (DS:3298 = 1, base index 1 -> 0x4a, zone 2/ab4a 5 seen), 0x4b = same with the second base index (zone 1, ab4a 6 seen; mapping base index to 0x4a/0x4b/0x51 is static, 0x51 NOT observed).
- 0x4f = runner thrown out advancing (class 7 fly, observed twice), 0x52 = lineup change event (class 255 reset state, observed once), 0x08 = sacrifice (class 7, fly, observed once).
- NOT observed: 0x03..0x07, 0x09, 0x0a (steals, CS, PB, WP, sac variants), 0x0b, 0x50, 0x51, triples. Static meaning only, see session 6 and the notes in BB 6000:8100.
- ab4a = fielder position in V20 numbering (0 P, 1 C, 2 1B, 3 2B, 4 3B, 5 SS, 6 LF, 7 CF, 8 RF); ab49 = ball x < 0x10 flag; ab3b = fly flag; DS:3298 = error on this play; DS:35eb = outs on this play.


## Lane B8: SYSTEM, assets, stadiums (2026-10-07)
Code: tools/dcl.py (PKWARE DCL explode, pure Python), tools/assets.py (PNG renderer, output /mnt/nvme/tlrb2/assets_png). Addresses in lane_names.tsv / lane_types.tsv.

### SYSTEM file (76 B, all programs keep a far pointer to a farmalloc'ed copy)
Pointers: MAIN DS:ab10 (loader 5000:40fb, saver 5000:4163), BB DS:bc1a (loader 6000:c28d, saver 6000:c2f5), UTIL DS:2b74, DRAFT DS:91ac. Written at game start and at MAIN QUIT (rig: toggling two Special Box Score flags changed SYSTEM only after QUIT; QUIT also rewrote CONTROL and the MAJ).
- 0..7 set directory name ("CLASSIC\0"), builds the TEAMS path. UTIL changes it in the league select screen.
- 0x08 DH, 0x09 pipes, 0x0a errors, 0x0b injuries, 0x0c use stats (+k = GAME.TMP byte 7420+k for k 0x09..0x0c; DH = GAME.TMP 7193, DH byte statically derived only). Copied back only when buf[0x1bf4] >= 2 (exhibition); the pristine bytes 8..0xc are stale. Snapshots gt_Ap/Ae/Ai/As confirm bytes 9, 0xa, 0xb, 0xc.
- 0x0d one pitch, 0x0e auto replays, 0x0f sound effects, 0x10 voice/crowd bits, 0x11 quick off the field, 0x12 scrolling, 0x1a music; 0x13 animation speed, 0x14 visitor control, 0x15 home control, 0x16 visitor input, 0x17 home input, 0x18 visitor auto bits, 0x19 home auto bits. Mapping: MAIN 4000:e968 (SYSTEM to buffer), 4000:eae4 (buffer to SYSTEM).
- 0x1b mouse present (1 after init), 0x1c / 0x1d joystick A / B present (MAIN 1000:6250).
- 0x1e..0x29 joystick A, u16 x 6: X, Y, X>>1, X+(X>>1), Y>>1, Y+(Y>>1) (calibration, BB 2000:16f3). 0x2a..0x35 joystick B, same layout.
- 0x36 team index for "ALL BOX SCORES (ONE TEAM)", 0xff = none (MAIN 6000:0d77 case 0x1d).
- 0x37..0x44 Special Box Score yes/no flags, one byte each, 1 = YES. Index order is the on-screen order: batter column (cycle, 5+ hits, 3+ HR, 4+ steals, 5+ runs, pinch grand slam), pitcher column (no hitter or perfect game, 1 hitter, 14+ strikeouts, extra-inning shutout), then 15+ inning game, either team 20+ runs, all boxscores of one team, all boxscores. CONFIRMED on the rig: YES on "3+ HOMERUNS" set byte 0x39, YES on "EXTRA-INNING SHUTOUT" set byte 0x40. BB 6000:3f4f checks them post game.
- 0x45..0x4a unused, 0x4b CD drive letter index (3 = D), used by auto_prepend_drive_path (MAIN 5000:4348, UTIL, DRAFT, BB).

### PAL (768 B)
256 x (R,G,B), 6-bit VGA DAC values (0..63). Writer UTIL 1000:0919 (out 3c8/3c9), loader UTIL 1000:9608 (fread 0x300). A screen uses the same-named .PAL when present, else DEFAULT.PAL (UTIL 1000:91a6 picks NEWLGU, EDITNAME, DEFAULT, DOWNLOAD for a few ids). OLDPORT portraits look right under DEFAULT.PAL (grayscale). Rendered BACKGRD.SCR with DEFAULT.PAL matches a rig screenshot of the main menu pixel for pixel (100% of the compared region).

### DCL (PKWARE Data Compression Library "implode")
Stream starts `00 06` (binary literals, 4096 dictionary). tools/dcl.py explode(data, start) returns (bytes, end offset). All 63 SCR, all small ANM/OVL and all 41 SDM decode and consume their stream exactly. The game's explode runs with a write callback that blits to VGA or fills an EMS area (BB 2000:df04 farmallocs a 0x311e work buffer).

### SCREENS/*.SCR
u16 count (1), then a 12 B header of 6 u16 (transparent colour in the high byte of the first word, height, width, y offset, x offset, compressed length = file size - 14), then the DCL stream. Explodes to height*width bytes (320 x 200 palette indices, 64000). Loader UTIL 1000:bdf1 (screens\<name>, drive-prefixed fallback). 63 files.

### *.PAG
Plain text, CRLF lines, TAB separated cells: the position and label layout pages for lineup, defense and the editors (DEFENSE, LINEUP, EDITFLD, EDITPIT, EDITPLAY, EDITPLYB). Read through load_page_file_by_id (MANAGE, MAIN, DRAFT, UTIL, BB).

### *.FNT (BOLD, LARGE, MAIN, SCBD, SCBDTHIN)
u16 glyph count (95 = chars 0x20..0x7e), then per glyph [rows][width bits][advance] followed by rows x ceil(width/8) bitmap bytes, MSB first. All five files parse to exactly their size. LARGE is upper case only (lower case glyphs are empty). In memory (UTIL 1000:87cd) entries are 7 B [rows][width bits][advance][far ptr] at DS:95a6 + font*0x299 + char*7; font names at DS:2f10. Glyph sheets: assets_png/fnt_*.png.

### ANMS/*.ANM, *.OVL (normal format)
u16 frame count, then per frame 12 B header (flags word with transparent colour in the high byte, height, width, y offset, x offset, compressed length) and a DCL stream of height*width bytes. OVL is the same format (stadium art, 320x145 overlays, 174x73 and others). All 262 non-big files render (assets_png/anm_*.png; palette DEFAULT.PAL is a guess for colours). Loaders UTIL 1000:c1ed (multi-frame), 1000:bfec (first frame), BB 2000:d922, 2000:d5db.
- Big/replay ANM (1BOUT, 2BOUT, 2BSAFE, 2BSTEAL, 3BDIVE, 3BDIVE2, 3BSAFE, DBLPLAY, DBLPLAY2, DIVE, DIVE2, DIVE2L, HOMEOUT, HOMERUN, HOMESAFE, JUMP, JUMP2, LEAP, MOON, FLAG, root INTRO.ANM and BOLT13.ANM): 768 B palette, u16 count, 14 B header (flags, h, w, 0, 0, 0, u16 size), then a u16 table and payload. HOMERUN: 18 frames, 232 x 138, first frame size 34320. The payload encoding is NOT decoded (DCL fails at every offset). Candidate decoder: BB 6000:962a auto_load_replay_file.
- ANMS.LST: 100 x (u32 offset, u32 size); ANMS.ALL is the concatenation of those small ANMs (181405 B, sum of sizes equal). Not otherwise verified.
- OLDPORT.ANM (1425600 B): no count word; 528 x (12 B header + raw 48 x 56 pixels), header clen 0 = uncompressed, transparent 0x18. Index = player portrait u16@27 minus 981. Renders under DEFAULT.PAL (assets_png/port_OLDPORT_first64.png). PORTRAIT.ANM (generic faces) renders as a normal ANM.

### STADIUMS/<stem>.CFG (1289 B, 41 files) and .SDM
BB loader 2000:1b40 (called from 6000:15a0): stadium stem is 8 chars at GAME.TMP+0x1cfc; opens stadiums\<stem>.cfg, fread 0x509 B x 1 into a fixed DS buffer (BB DS:4b73), then the .sdm.
- CFG: 0x00..0x1e stadium name (one NUL-terminated string, up to 30 chars: "THREE RIVERS STADIUM" crosses 0x13; text after the NUL, e.g. GRASS's "STADIUM", is stale and not shown), 0x1f type byte (0, 1 or 2), 0x20 u16[5] fence distances in feet LF, LCF, CF, RCF, RF (FENWAY 315, 379, 389, 383, 302; ASTRODOME 330, 380, 400, 380, 330), 0x2a wind mph, 0x2b wind direction (0..3; 1 = LEFT TO RIGHT, domes 2 with 0 mph), 0x2c average temperature F, 0x2d humidity %, 0x2f u16 altitude ft (MILEHIGH 5280, FENWAY 21), 0x31 notes id (0..40, unique per park, GRASS 37 shows NOTES NONE), 0x33..0x152 palette (below), then two edge tables of 70 x (u16 y, u16 column k): 0x153 the outfield fence base and 0x26b the stands wall along the foul lines, in panorama coordinates, column k covering x 16k..16k+15 (overlays on GRASS and FENWAY trace both exactly; RIVER's fence entry 69 is (0, 0)); 0x1f surface: 0 every 1992 turf park and dome, 1 grass, 2 the seven historic parks. tools/stadium.py info decodes all of this. Then a zero gap to 0x46f (POLO and FENWAY have a few nonzero bytes there), u16 tables at 0x470..0x500, and at 0x501 two (u16, u16) points indexed by buf[0x1cf3]*4 (BB reads them as screen positions); 0x508 = 0xff. Name, fences and the four conditions are confirmed against the rig's Assign Stadiums screen (GRASS); the surface meaning, the edge tables and the notes id are by inspection across all 41 files. Still unknown: 0x2e, 0x30, 0x32, the 0x470 tables and the 0x501 points. The edge tables presumably bound the ball in play (not proven on the rig), so a park whose field differs from its base would need new tables; parkgen keeps the base field, so the base tables stay valid.
- SDM: the whole file is one DCL stream. Explodes to 497280 B (1120 x 444, row stride 0x460 as used by the EMS writer BB 2000:dfba) or 501779 B (bigger stadiums). It is the pre-rendered 8-bit stadium panorama (FENWAY.SDM shows the park from behind home plate). Its palette IS in the CFG: bytes 0x33..0x152 are 96 VGA DAC triples (6-bit) for entries 80..175; the rest of the DAC is DEFAULT.PAL and the panorama uses only 0..16 there. Proved 2026-10-08 against all 45 confidently observed colours of a rig screenshot (panorama offset 448,215); the older "offset 0x2e failed" note was 5 bytes off. tools/stadium.py render draws a park in its real colours.
- Path: both files open as `<CD>:\stadiums\<stem>.*` through auto_prepend_drive_to_path (BB 6000:c620, drive = SYSTEM
  byte 0x4b), so stadiums always come from the CD drive, never C:. Modded parks ship as a rebuilt CD image
  (tools/stadium.py iso, xorriso). Proved 2026-10-08: tools/dcl.py implode re-encoded GRASS.SDM with a 120 x 50 block
  of index 0 at (500, 190); CAL @ BAL exhibition on the rig shows the block above the infield in the fielding view and
  the rest of the park unchanged, so the game's explode accepts our streams. The at-bat view is not the panorama.
- Stadium list: MAIN 5000:834e (auto_load_all_stadium_configs) scans `stadiums\*.cfg` on the CD with findfirst/findnext,
  so the stadium list is built from whatever CFGs the disc holds (UTIL 4000:fb46 is a second loader); 44 parks (3 added)
  list and play fine, so capacity is at least 44. A team picks its
  park by the 8 B stem in its V20 header (+19, tools/v20.py set_stadium).
- ANMS/<stem>.OVL: one 174 x 73 frame, a thumbnail of the park that renders correctly only under that park's CFG palette
  (indices 0..179). Where the game shows it is not seen yet: Assign Stadiums' VIEW STADIUM scrolls the SDM itself.
- New parks: tools/parkgen.py keeps GRASS's field pixels exactly, regenerates stands and sky with SDXL inpainting,
  fills the 24 CFG palette slots the field does not use by k-means, and writes SDM, CFG and OVL. Proved 2026-10-08:
  ZMODERN (stem `zmodern` on BAL in the work install, CD rebuilt with tools/stadium.py iso) runs a CAL @ BAL
  exhibition (50 s of play sampled, no crash) with the new skyline, video boards and stands in the outfield and fielding
  views. Assign Stadiums lists it last (after OLD YANKEE STADIUM, as the Z stem intends), shows its name, fences and
  conditions for BAL, and VIEW STADIUM shows the new panorama. Wind, humidity, temperature and altitude on that screen
  come from the base CFG (GRASS) unchanged.

### Saved seasons
There is no season save file. LOAD SAVED GAME is the in-game mid-game save (1.SAV..10.SAV, see GAME.TMP above). MAIN has "SAVE SEASON": it saves the simulated stats as a NEW LEAGUE (requires the regular season over and at least 81 games, and enough disk: 0xe97b (MAJ size 59771) + 0x2dd7 (V20 size 11735) per team, MAIN 6000:021b) i.e. a new TEAMS/<set> directory of V20s and a MAJ in the existing formats. Static only, the menu path was not run.

## M4 headroom (Lane B9, 2026-10-07)

### Free conventional memory (MCB chain walked in the DOSBox-X debugger)
Method: rig relaunched under a pty so the ncurses debugger is enabled (tools/lane_b/dbg_pty.py + relaunch_dbg.sh;
Alt+Pause opens it, MEMDUMPBIN 50:0 A0000 <file> dumps 640 KiB, tools/lane_b/mcb_parse.py walks the chain;
chain head at segment 0x450 in this DOSBox-X config). Programs were parked at their normal idle screens (menus
driven over Xvfb :98); each dump is one instant. DOSBox-X memsize=16 MB, XMS/EMS/UMB on; numbers are the
conventional chain only. Free memory is always ONE contiguous block (each program is the topmost load, no
fragmentation). "alloc" = the program's single DOS block (image + BSS + heap incl. the VROOMM overlay buffer,
which Borland allocates during CRT init, so overlay paging does not change free memory afterwards).

| program (state measured) | free conventional | largest block | program alloc |
|---|---|---|---|
| CONTROL.EXE (at its first file open, BPINT 21 3D) | 592.7 KiB | same | 15,360 B |
| PLAY.EXE (mid intro) | 443.7 KiB | same | 167,936 B |
| MAIN.EXE (main menu idle, after boot) | 321.7 KiB | same | 292,864 B |
| MAIN.EXE (after menus + pre-game screens) | 233.7 KiB | same | 292,864 B +heap growth |
| MANAGE.EXE (roster screen, Baltimore) | 388.7 KiB | same | 224,256 B |
| UTIL.EXE (Edit Player Stats team select) | 277.7 KiB | same | 337,920 B |
| UTIL.EXE (player editor open) | 254.7 KiB | same | grew ~23 KiB |
| DRAFT.EXE (started from the DOS prompt; black screen, it waits for a CONTROL state and never drew) | 188.7 KiB | same | 429,056 B |
| BACK.EXE (mid season sim, play-to Oct 3 via Play League Games) | 106.7 KiB | same | 513,024 B |
| BB.EXE (mid exhibition game, overlays + stadium + ANMs loaded) | 94.7 KiB | same | 525,312 B |

Bottom line for the design: even the two fattest states (BB in-game, BACK simulating) leave ~95-107 KiB of one
contiguous free block; a new 4-8 KiB code segment allocated at startup (farmalloc-style DOS block) fits in every
program with room to spare. MCB blocks: env block 73 para + image block; PSP always 0x814 in this rig, load image
at 0x824, flat seg S = runtime seg S-0x1000+0x824. TONY2.BAT runs CHECKMEM.EXE once (DOS version >= 3.30 check at
0x7d/0x7e, EMS-aware, sets errorlevel on failure; exact threshold constant not chased).

### Code caves (candidate padding inside the resident image)
tools/lane_b/cave_scan.py lists zero runs >= 64 B in each flat image's resident prefix; each candidate was then
checked against the real-memory dump of that program (same instant). Results (verified = all zero in RAM at idle):

- MAIN: 1eca:000d 115 B, 3fbe:000b 133 B, 4642:000c 68 B, 49ac:0001 2127 B, 4a4c:0003 129 B, 4a5b:0004 300 B, 4a8e:0004 9884 B all VERIFIED at idle. The huge 1edf:0000 133 KB flat run is BSS: 57 KB of it was already in use at idle.
- PLAY: every run VERIFIED (14bf:000b 433 B, 14db:0000 516 B, 159c:0002 180 B, 1733:000d 129 B, 1742:000e 300 B, 1771:000a 4470 B).
- CONTROL: 124f:000c 300 B VERIFIED.
- UTIL: 3846:000b 133 B, 3fd1:0004 64 B, 4068:0002 80 B, 41a2:0001 2127 B, 4242:0003 129 B VERIFIED (the 2291 88.9 KB flat run is live BSS).
- DRAFT: 1d94:000d 115 B, 1d9f:0005 2109 B, 1e24:000b 133 B VERIFIED (the rest live BSS).
- BB: only 4fe0:000b 133 B and 5394:0000 64 B VERIFIED (its big flat runs are live BSS).
- BACK / MANAGE: nothing verified (all candidate regions carry live tables/BSS by menu-idle time).

Caveat: "verified" means zero at one observed idle instant; any use of a cave must re-verify per address (watch
over gameplay) before shipping. The design should not NEED caves except for tiny hook trampolines: free
conventional memory (above) is the real code space, and per-program the far heap already hosts alloc'd buffers.

### Overlay (VROOMM) structure and where new code can live
FBOV format (tools/vroomm_flatten.py docstring, verified): after the MZ load image: 'FBOV' + u32 ovl_size +
u32 segtbl_off + i32 nseg; per stub segment a 0x20 B header (CD 3F, u16 0, u32 fileoff, u16 codesize,
u16 relocsize, u16 nentries) followed by nentries 5-byte thunks `CD 3F off16 00`; overlay fixup words are
selector indices (x8) into the nseg x 8 B segment table. Overlay counts: MAIN 51, BB 42, UTIL 37, DRAFT 41,
BACK 24; MANAGE/PLAY/CONTROL have none. Adding a new overlay to an existing EXE = append FBOV table entry +
stub + overlay data and bump nseg (file surgery); simpler paths: (a) allocate a DOS block at startup and patch
a far call to it, (b) add a new program to the TONY2.BAT loop (below), which gets a fresh full memory space.

### CONTROL.EXE dispatch (id 8 patch point) and the TONY2.BAT loop
TONY2.BAT: `play` then loop { `control`; if errorlevel 7 end; 6->draft, 5->util, 4->manage, 3->bb, 2->back,
1->main (bat labels run `<prog> %1` then goto start) }. Batch errorlevels are >=-ordered so a new id must be
inserted in the right place (e.g. `if errorlevel 8 goto dyn` before the 7 test).
CONTROL main loop (real seg 0x1228; flat offset = 0x2280+off): reads/creates the 9 B control file into DGROUP
0x2ec (DGROUP seg 0x123e), then:
  0xBE  cmp byte [0x2ed],7 / jz quit         (state[1] == 7 -> int10 mode 3, exit(7))
  0xC5  mov al,[0x2ed]; dec ax; mov bx,ax
  0xCF  cmp bx,5 / ja quit                   <-- bounds check: state[1] must be 1..6
  0xD4  shl bx,1; jmp [cs:bx+0x127]          jump table at 0x1228:0x127, six words:
        0xE5 0xEA 0xD9 0xEF 0xF4 0xF9  = handlers `mov ax,<same id>; push ax; call exit(0x1000:0x357)`.
So errorlevel == state[1] 1:1. Patch for id 8: change the `cmp bx,5` immediate (0x1228:0xD0, byte 05 -> 07)
to accept 1..8, repoint the `jmp [cs:bx+0x127]` displacement (0x1228:0xD6, word 0x127) to a copied 8-entry
table + two new `mov ax,N; jmp short <push/call exit tail at 0xDC>` handlers placed in a verified cave
(e.g. CONTROL 124f:000c, 300 B, see above). The new program itself writes the control file + exits with its
own errorlevel, exactly like the shipped programs.

### The 4 *.OVL stadium art files (C:\TONY2\GRASS1B/GRASS3B/TURF1B/TURF3B.OVL)
Not code: single-frame ANM art, u16 frame count (1) + 12 B header (flags 0x0200 -> transparent colour 2,
height 55, width 88, y 0, x 0, u16 clen) + one DCL stream of exactly 88x55 = 4840 B (GRASS1B: clen 1432,
file 1446 B, explodes to 4840 at end == file size). Filename pool is a string table at BB 5494
("grass1b.ovl", "grass3b.ovl", "turf1b.ovl", "turf3b.ovl"), i.e. BB selects by stadium surface for the
base/inline camera insets on the play screen; loader = BB's ANM loader family (2000:d922/2000:d5db).

### Next-season twin copy (season rollover hook), all three variants byte-identical in behaviour
UTIL 5000:9cd5, MAIN 5000:f1ce, DRAFT 1000:5589 copy ONE 143 B record from src to dst:
- +0x00..0x13 verbatim (last+first name), +0x14 age VERBATIM, +0x15 year-1870 +1, +0x16 exp +1,
  +0x19 u16 salary, +0x1b u16 portrait, nibble copies of +0x1d (throws/bats/flag3 + hi nibble),
  +0x1e (exper/consist), +0x1f (pos2/pos1), +0x4a (bunt/power), +0x4b (streak/H&R), +0x4c (day/night/clutch),
  +0x5e (range/arm), +0x86..0x8c (pitcher rating nibbles incl. +0x8c hi = user-set-ratings flag).
- Everything else (games +0x17 and all stat bytes) is NOT copied, so the destination keeps zero stats.
Callers (=> when it runs; it is a league/team-build helper, NOT a season-rollover pass):
- UTIL 5000:9cd5 <- 5000:91a1 build_team_from_source_data <- 5000:8c60 import_league_disk_to_team_files
  (Utilities > IMPORT VERSION 1 STATS: reads DH.LGU/NONDH.LGU + per-team .TMS, converts each player from a
  0x78-stride source record into V20 records 0..39, then twins into 40..79; salaries and portrait are zero at
  this stage, portrait assigned later by 5000:a208/5000:ea5e).
- MAIN 5000:f1ce <- 5000:ebc3 load_team_data_roster_for_all_slots <- 5000:da40 (MAIN league/team loading;
  reads both halves from the V20 file, so the on-disk twin is authoritative, not recomputed).
- DRAFT 1000:5589 <- 1000:504d reset_team_roster_after_draft (post-draft roster rebuild).
Corollary for the design: there is no in-season aging/progression in the shipped code; the twin's year+1/exp+1
fires only when a league is BUILT. A dynasty rollover must age +0x14 and regenerate +0x15/+0x16 itself.

### Fantasy draft pool (DRAFT) and player generation
- Pool: 2000:e7f7 draft_build_draft_pool iterates 32 draft slots grouped in fives per team (three category
  counts read from the league structures at +0x298/0x299/0x29a, mirroring the GM profile), and for each slot
  2000:e964 draft_load_team_file_and_add_players builds teams\<stem>.v20 (stem from the MAJ +0x1d7 table),
  farmallocs 0x2dd7 (one whole V20), copies the team header (14 B name) and up to 40 flagged 0x8f-stride
  player records into the pool. I.e. the draft pool = the league's own players re-categorised, NOT generated.
- There is NO procedural player generator anywhere: new players come from the v1 import (.TMS source records,
  ratings already packed in the source) or blank records. Reusable pieces for a rookie-class generator:
  UTIL 5000:e89d init_blank_player_record (zeroes 0x8f B, portrait 0), UTIL 5000:ea5e
  assign_random_generic_portrait (least-used face matching rec+0x1d&1 against UTIL DS:776e, counts DS:bfb0),
  and the stats->ratings calculators (UTIL 1000:b02a..b82f, tools/ratings.py) + salary (5000:f382/f697).
  Name tables seen (manager names in the league builder, UTIL DS:0x219c first / +0x1e0 last, 24 B entries)
  are fixed lists, not a name generator.

### STATISTICAL LEADERS reads records 0..39 (the historical half)
Rig: UTILITIES > STATISTICAL LEADERS (menu 490 210 -> item y=232). Table row 1 = WILLS, MAURY LA S
G165 AB695 H208 HR6, row 2 TAVERAS FRANK NYH G164 AB680 H178. File check: CLASNLW4.V20 record 29 WILLS
half0 G165 AB695 H208 HR6 (exact), twin half40 G0 AB0; CLASNLE3.V20 record 26 TAVERAS half0 matches row 2
exactly. So the default table = records 0..39 (shipped "historical" season stats, not career totals). The
HISTORICAL/SIMULATED button pair (bottom right) switches halves (SIMULATED = 40..79); the click coordinates
were not hit in this run, but the data above pins the default view. NOTE: half 0..39 of the classic league
holds each player's best/historical single season (Wills 1962: 165 G), not career sums.

### SYSTEM+8 DH byte (code-confirmed) and portrait bit0 (dynamic)
- MAIN 4000:eae4 game_buffer_to_settings: SYSTEM+8 <- GAME.TMP +0x1c19 (7193), executed only when
  buf[0x1bf4] >= 2 (completed exhibition game). Dynamic counterpart: toggling DESIGNATED HITTER to NO on the
  Ground Rules screen flipped GAME.TMP's DH (lineup screen showed 8 batters + pitcher batting 9th), but
  MAIN > QUIT wrote a byte-identical SYSTEM because no exhibition game completed in between. SYSTEM+8 = DH,
  persisted only through a finished exhibition game. (Season games take DH from MAJ S+0x297 at setup,
  MAIN 4000:e968's default branch.)
- V20 byte 29 (+0x1d) bit0: set it on Dave McNally (CLASALE1 record 0 and twin 40, 0x72 -> 0x73) and played
  an exhibition game: his generic portrait (index 6) rendered byte-identical on the play screen. Confirms the
  flag is used ONLY by the random assignment (UTIL 5000:ea5e matches it against the face-group table
  DS:776e when picking a face for a new/unassigned player), never by the renderer (BB 7000:da0a uses u16@27
  alone). Evidence shots pb3.png vs bb_esc3.png.
