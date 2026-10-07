# Unattended RE run (started 2026-10-06 ~17:00, Opus coordinating)

Will asked for a plan put into effect and run without check-ins. Three workers:

| Lane | Who | What | Ghidra |
|---|---|---|---|
| A0 | Opus (this plan) | foundation fixes, bulk naming pipeline, apply, verify | sole writer during rebuild/apply |
| A1 | Will's GLM-Flash Claude Code session (Warp) | M1 by hand: setds/fixrefs (gh.py), RTL naming | writer between Opus steps (GHIDRA_FREE flag) |
| B | Sonnet headless (`claude -p`, log /mnt/nvme/tlrb2/lanes/laneB.jsonl) | M2 V20/.MAJ decoding on Xvfb :98, then M3 | never; reads index/flat, logs addresses in notes/LANE_B.md |

## Steps (A0)
1. Foundation fixes, found while building the pipeline:
   - Overlay fixups are FBOV segment-table selectors, not segments (tools/vroomm_flatten.py fixed). Before the fix
     ~7,500 overlay far calls pointed into the wrong code.
   - DS = DGROUP set at import (SeedFunctions.java arg 2, from the c0 `mov dx,DGROUP`).
   - Rebuild all 8 programs (scripts/ghidra_build.sh), then gh.py fixrefs per program, then scripts/regen.sh.
2. Knowledge base (tools/re/kb.py): relocation masks, DGROUP strings, call graph from disassembly (overlay stubs
   followed), call targets Ghidra missed as pseudo functions, cross-program dedupe (5997 functions -> ~3800 unique
   bodies), seeds (53 hand-verified RTL/DOS names propagated to every program).
3. Bulk naming (tools/re/name_all.py): every unique body, callees first, Z.AI GLM-5.3-Flash (thinking off, conc 4)
   as the primary namer. DeepSeek V4.1 Flash on Hive is backup only (Will, 2026-10-06: it ran ~7/min vs Z.AI ~23/min
   because of long reasoning output): `run --backends deepseek --weak` after Z.AI finishes, on units still below 0.6. Prompts carry callee names
   (with confidence), DS strings and annotated disassembly. Chosen by the 2026-10-06 bake-off (notes/HIVE_PILOT.md):
   both 100% precise at confidence >= 0.6 on the known set.
4. Merge: accept = confidence >= 0.6 and not contradicted by a confident second opinion. Everything else becomes a
   plate comment only.
5. RESULT 2026-10-06 (30-unit early sample): ~20% of accepted names wrong at the name level (free that is brk,
   hex-to-ASCII called BCD, overclaimed game meanings). Confidence does not separate them; Z.AI self-audit does not
   either (tools/re/audit.py calib: 25-38% of its passes were Sonnet-wrong). Decision: rename with prefix auto_
   (SourceType.ANALYSIS) so every bulk name reads as a hint; plate comments carry purpose and the other opinion.
   Original rule kept for reference:
   Sonnet spot-check (tools/re/verify.py) on a stratified sample of accepted names. Renames are applied only if the
   sample is >= 90% correct-or-plausible; otherwise comments only and the accept rule is tightened.
6. Apply (tools/re/apply_names.py): create missing functions, rename accepted (SourceType.ANALYSIS), plate comments
   for all; regen the index.
7. Second pass on units still below 0.6, now with named callers and callees in context.
8. Fold Lane B's addresses (notes/LANE_B.md) into Ghidra.

Not in scope while unattended: M4 design (needs Will), any patch to the live install, any push.

## Status 2026-10-07 (03:40)
- Steps 1-8 done. KB: 5666 functions -> 3269 units, 37 seeds. Z.AI named all 3046 non-seed units; DeepSeek backup
  (--weak) answered 1332 weak units; Z.AI round 2 (--retry, backend zai2, callees now named) re-asked the 1282 units
  the first merge did not accept. Final merge: 2614 accepted (was 1987), 1810 single, 754 differ, 660 agree, 8 conflict.
- Ghidra: auto_ (ANALYSIS) names on 4392 functions, FUN_ left on 917, about 320 verified/seed/RTL names. 54 apply
  failures are BB/PLAY call targets Ghidra will not turn into functions.
- M2 types: /TLRB2 V20Player, V20Header, V20Team in all 8 programs (tools/re/structs.py). Lane globals typed from
  notes/lane_types.tsv by fold_names.py (DS:off rows map to DGROUP; buffer-relative rows stay documentation).
- Lane B6: season-game merge BB 6000:3407 confirmed field by field, RTO pair (90 caught, 92 attempts), +0x85 appearance
  counter, accumulator layout for both teams, result-code formulas, ALLTIME.BOX writer BB 6000:c6c1.
- Lane B7: SAVE confirmed dynamically (append, 2 B header + 7194 B), u16@27 is the portrait index (0..29 generic,
  981..1507 photos), MAJ +0x35b is the injuries flag. Open: a few result codes, byte 29 bit0 (static only).
- Lane B8: SYSTEM fully mapped (byte 8 DH, 9..0xc pipes/errors/injuries/stats, 14 box-score flags from 0x37), PKWARE
  DCL streams (tools/dcl.py), SCR/PAL/FNT/small ANM/OVL/OLDPORT rendered by tools/assets.py to
  /mnt/nvme/tlrb2/assets_png (263 PNGs; BACKGRD.SCR matches the rig pixel for pixel), STADIUMS CFG fence distances,
  SDM = 1120x444 park panorama. No season save file: SAVE SEASON builds a new league set.
- M1-M3 done. M4 not started: needs Will's design review.
- Left (all minor): big replay ANM payloads (HOMERUN, INTRO), SDM palette source, CFG tables past the fences, DH byte
  dynamic check, result codes 0x4a/0x4b/0x4d/0x51 and class 6/7, byte 29 bit0 (skin tone, static only), 917 FUN_
  functions with no confident name.
