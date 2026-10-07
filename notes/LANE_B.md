# Lane B (dynamic) status

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
