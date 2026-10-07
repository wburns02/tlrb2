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
- +237..+244: 14 14 05 05 0f 0f 14 00 in every CLASSIC team (0 in older 0168 files). Constant roster limits? Not edited. Open.
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
