# Lane B (dynamic) status

## Status 2026-10-06 (M2 and M3 done to the extent below)
Done
- M2 player record fully mapped except u16@27 and u16@90/92. V20 header fully decoded (staff, lineups, defense, bench, reserves, strategy,
  W/L +38/39, streak +109, rotation pointer +110). tools/v20.py has accessors; parse+serialize byte exact. Round trips proven on screen
  (rt1.png record fields, rt2.png header lists).
- M3: ran a full 162 game season plus playoffs and WS on the work install with ftrace/snap diffs (snaps m3_base, m3_d1, m3_d2, m3_end).
  MAJ layout decoded: date constants, standings, schedule, runs/hits/errors tables, playoff data (FORMATS.md). Verified against the
  Game Scores screen for April 9. Season sums check: all W+L = 4212 = 26 x 162, per-team V20 W/L equal MAJ arrays.
- tools/maj.py reader/writer. Round trip proven: W/L edited outside the game show on Season > Standings (shots/rt_maj2.png).
  Order and GB are recomputed by the game on load.
- Season flow: CONTROL byte meanings, V20s written only at Main > QUIT, PLAYOFFS.AL/.NL layout (8 x GAME.TMP records), .SCH template
  layout (AL rows at +0x50+16d, byte identical to MAJ rows), Start New Season effects (zeroes W/L, streak, byte 24, stats in records
  40..79; deletes PLAYOFFS.*; rewrites schedule and date constants). Season stats never touch records 0..39.
- BACK code read: 1000:95da/95fb (streak), 1000:9d84 (starter chooser, rest bit).
Open
- DH flag: S+0x297 did not change when I set A=NO DH, N=USE DH in the new-season dialog (maybe the clicks missed, maybe stored in memory only).
  The injuries on/off choice is in no data file either. Needs a re-run with a screenshot after each click.
- MAJ: bitmaps at S+0x132b..0x1607, exact hits/errors table semantics, 0x20c/0x20d use, team names/colors/stadium storage (Setup Leagues,
  Edit Team Names, Assign Stadiums experiments not run), V20 header +44..91 and +237..244, record u16@27/90/92, +0x85 counter semantics,
  stats-to-ratings formula, GAME.TMP internals.
- Cause of the ordering of NL schedule rows in the SCH (+0x6fd4) not verified beyond one row match.
Next
- Edit Team Names / Assign Stadiums / team colors experiments with snap diffs. DH and injuries flag re-run.
- Decode GAME.TMP via a BB game (M4 is not started).
Code addresses for Lane A (BACK DGROUP 2c71 unless noted): streak setters 1000:95da (win) and 1000:95fb (loss), starter chooser 1000:9d84
(staff tables DS:0x180a + team*5 + i + 0x1abb, bullpen +0x1ac5, record base 0x127 + idx*0x8f), CONTROL.EXE FUN_1228_0007 (reads CONTROL).
UTIL (DGROUP 3954): position string table DS:0x0b6c, pitch type strings near DS:0x0a0f, MAJ upgrade UTIL 4000:74ad, MANAGE 1000:ce08 (aging loop).
Editor screens SCREENS/EDITBATA.SCR, EDITBATB.SCR, EDITFLD.SCR, CHOOSEP.SCR. V20 record struct 143 B, see FORMATS.md.
State: work install restored to snaps/m3_base (clean classic, CONTROL 00 01 ...). A DOSBox-X window is left at the DOS prompt on :98.
