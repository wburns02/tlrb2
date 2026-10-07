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

## Status 2026-10-06 ~21:00
- Steps 1-4 done. KB: 5666 functions -> 3269 units, 37 seeds. Z.AI named all 3046 non-seed units (9 errors);
  merge accepted 1865.
- Step 6 applied once (Z.AI only): 3471 functions renamed (auto_ prefix, ANALYSIS), 5633 plate comments, 4 functions
  created, 53 failed (mostly BB/PLAY call targets Ghidra would not turn into functions). Index regenerated.
- Running: DeepSeek backup on the ~1350 units below 0.6 (run_backup.log). On finish a chain re-merges, re-applies
  (idempotent) and regenerates, gated on the Ghidra lock file.
- Still to do: step 8 (fold Lane B / M3 addresses into Ghidra), commit. Step 7 is the DeepSeek backup pass.
