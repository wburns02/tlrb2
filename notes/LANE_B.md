# Lane B (dynamic) status

## Status 2026-10-07 (eighth Lane B session)
Done (details in FORMATS.md "Lane B8", addresses in lane_names.tsv / lane_types.tsv)
- SYSTEM (76 B) fully mapped: set dir, ground rules (corrected: +8 DH, +9 pipes, +0xa errors, +0xb injuries, +0xc stats), joystick A/B calibration, 14 Special Box Score flags at 0x37.. (rig CONFIRMED in on-screen order), CD drive index at 0x4b. Written at QUIT.
- tools/dcl.py (PKWARE DCL explode) and tools/assets.py (PNG renderer): PAL, SCR (63), FNT (5), ANM/OVL (all non-big), OLDPORT (528 portraits, 48x56 raw). BACKGRD.SCR matches a rig screenshot pixel for pixel.
- STADIUMS: CFG 1289 B (name, type, five fence distances, polylines), SDM = one DCL stream of a 1120 x 444 panorama. Loader BB 2000:1b40.
- Saved seasons: no such file. SAVE SEASON creates a new league set from the simulated stats (static only).
Open
- Big/replay ANM payload (HOMERUN etc.) and INTRO.ANM not decoded. SDM palette source unknown. CFG tables past the fence distances are structure only. DH byte SYSTEM+8 and SAVE SEASON menu path not run on the rig.
- PAL choice per screen is static (same name else DEFAULT.PAL); ANM palettes are DEFAULT.PAL guesses.
State: no dosbox-x on work/c; SYSTEM, CONTROL and CLASSIC.MAJ restored from snaps/m3_base after the QUIT rewrote them (diff -rq clean). Assets in /mnt/nvme/tlrb2/assets_png.

## Status 2026-10-07 (seventh Lane B session)
Done (details in FORMATS.md "Session 7", addresses in lane_names.tsv / lane_types.tsv)
- Box score SAVE dynamic: appends (fopen "ab") a 2 B header 0x000e + 7194 B of the game buffer to ALLTIME.BOX; byte-identical to the live buffer, second SAVE appends an identical record. BB 6000:c6c1 CONFIRMED.
- Portrait index PROVED: V20 player u16@27 (0..29 generic colour face, 981..1507 OLDPORT photo). Edited team files changed the play-screen portraits as predicted. Old FORMATS.md "not the portrait" claim removed.
- Result codes: 3 more games (~2170 events) sniffed live. Confirmed singles 0x0c..0x0f, doubles, HR, outs, walk 0x49, K 0x4c, 0x4d (class 4 with ab48=1), 0x4e DP, 0x4a/0x4b error, 0x4f, 0x52, 0x08. Class 6 = 7th weighted slot, never sets a code.
- MAJ +0x35b stale "unknown" line fixed (already proved as injuries ON/OFF).
Open
- Never observed: triples (0x17..0x1d), 0x03..0x07, 0x09, 0x0a, 0x0b, 0x50, 0x51. Static meaning only.
- Byte 29 bit0 as portrait group flag (UTIL 5000:ea5e) is static only. Whether 0x4d is HBP or intentional walk is not separated.
- UTIL 5000:b83f reads +0x1b (0xb8b4, 0xb926), not examined.
Next: force steals/WP/PB via lineup speed edits, edit byte 29 bit0 plus a generic-face run in UTIL to test the group flag.
State: no dosbox-x on work/c; work install restored from snaps/m3_base (SYSTEM, CONTROL, GAME.TMP, MAJ, V20s, ALLTIME.BOX removed), diff -rq clean. Saved s7_ALLTIME.BOX and s7_ALLTIME2.BOX in /mnt/nvme/tlrb2/snaps. MCP servers needing auth (Slack, Canva, context7, logfire, sentry, stripe) were unavailable and unused.

## Status 2026-10-07 (sixth Lane B session)
Done (details in FORMATS.md "Session 6", addresses in lane_names.tsv / lane_types.tsv)
- Season Featured game CLE 2 at BAL 1 played; V20/MAJ before and after diffed. BB 6000:3407 CONFIRMED as the merge (all per-field deltas equal the box score); RTO pair u16@90/92 CONFIRMED (90 caught, 92 attempts); +0x85 = appearance counter (= +0x17 in a fresh league); u16@27 not touched (portrait still unproven).
- Merge happens in BB memory at game end (buf+0x1bf5=1, needs buf+0x1bf4==0); files are written when BB exits after DONE.
- Accumulator arrays fully mapped for both teams (stride 0x8e8): k7/k8 are the GB/fly distribution counters, k11/k12 are PO/A, SB/CS are singles.
- Result codes: observed table plus static formulas (hit = base + zone). Meaning of ab4a, 0x4a/0x4b/0x4d/0x51 and class 6 unverified.
- ALLTIME.BOX writer located statically: BB 6000:c6c1, called from the box score dispatch 6000:d277.
Open
- Dynamic run of the SAVE button (ALLTIME.BOX from a season game), full code table for class 6/7 variants, portrait index.
State: no dosbox-x on work/c; work install fully restored from snaps/m3_base (SYSTEM, CONTROL, GAME.TMP, MAJ and V20s). Snapshots s6_before and s6_after in /mnt/nvme/tlrb2/snaps.

## Status 2026-10-07 (fifth Lane B session)
Done (evidence in FORMATS.md "GAME.TMP session 5", addresses in lane_names.tsv)
- Play log decoded: scoring-half-inning log, 18 rows x 108 B at 0x12d3, 6 B events (side, pitcher, batter+split, result, runners). Writer BB 6000:7e7b, row counter BB 6000:7e65. Verified on game 2 (CAL 3, BAL 5: 7 scoring rows) via ALLTIME.BOX record and a game 3 RAM time series. tools/lane_b/gt_log_decode.py self-test passes.
- Accumulator arrays (visitor team only) mapped for AB, H, 2B, 3B, HR, BB, SO, E, R, RBI. Sums match the CAL box score exactly.
- ALLTIME.BOX record format: 2 B header + buffer 0..7193 (7196 B).
- Salary: no missing term, outliers explained by twin records.
- Visitor auto bits: 7444 low 3 bits (home 7445), proven by runs. Music byte 7436 = SYSTEM+0x1a, mapped by MAIN 4000:e968 / 4000:eae4.
Open
- Result-code table (b2), arrays k7/k8/k11/k12 (SB/CS?), RTO numerator/denominator (u16@90/92), +0x85 counter.
- Portrait index and RTO merge are static only; exhibition games do not merge to player records, need a season game.
- Address of the box score SAVE (ALLTIME.BOX writer) not located.
Next
- Decode b2 with a game of known play-by-play, then play a season game to confirm 6000:3407 and the portrait index.
State: no dosbox-x running; work install SYSTEM, CONTROL, GAME.TMP restored from snaps/m3_base; ALLTIME.BOX moved to snaps/s5_work_ALLTIME.BOX.moved.
Confirmed code addresses: BB 6000:7e7b, 6000:7e65 (dynamic); BB 6000:3407, 6000:8100, 6000:3c2b, 7000:da0a, 7000:0346, UTIL 5000:ea5e (static); MAIN 4000:e968, 4000:eae4; UTIL 1000:9e5f.
