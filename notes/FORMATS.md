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
  - +0x35b: 1 in the AL block, 0 in NL, never changes (unknown).
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
- SYSTEM (76 B): "CLASSIC\0", then league parameters (0x0a..0x4b), unchanged by sims and by new season. Not decoded further.
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
- Still TBD: GAME.TMP internals, SCREENS/*.SCR, *.ANM, *.PAG, *.PAL, *.FNT, saved seasons.

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
- Persistence: MAIN stores the Ground Rules in SYSTEM bytes 8..0x19 (+8..+0xb pipes, errors, injuries, stats; +0xc DH; +0xd.. the general rows; +0x14.. control/input/auto)
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

Accumulators (visitor team only, 40 slots by player id):
- Pair arrays at 440+80k, index 2*id+split: k0 AB, k1 H, k2 2B, k3 3B, k4 HR, k5 BB, k6 SO, k13 E. k7, k8, k11, k12 unknown (SB/CS candidates). Single bytes: 0xf0 R, 0x118 RBI.
- Game 2 sums over all 40 slots match the CAL box totals: AB30 H4 2B1 HR2 BB3 SO4 E1.

Ground rules bits: 7444 low 3 bits = visitor AUTO (bit0 fielding, bit1 throwing, bit2 running, 1 = yes), 7445 low 3 bits = home AUTO. Upper bits constant (0x68, 0xc0). Proven with 0x6f and 0x6a runs. 7436 music = SYSTEM+0x1a. MAIN 4000:e968 maps SYSTEM to buffer, 4000:eae4 maps buffer to SYSTEM. SYSTEM persists the last rules.

Salary: no missing term; era100 (UTIL 1000:9e5f) verified, outliers are twin records.
Portrait index (static only): UTIL 5000:ea5e assigns it, BB 7000:da0a loads by record idx 0x1b. RTO pair u16@90/92 is summed by BB 6000:3407 from arrays 0x690/0x6b8. Exhibition games do not merge into player records, so no in-game confirmation yet. +0x85 counter unresolved.
