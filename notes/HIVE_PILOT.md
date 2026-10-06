# GLM-Flash naming pilot (2026-10-06)

50 functions: A 18 thin DOS wrappers (truth from the int 21h AH byte), B 18 RTL/known functions (labeled by hand from
disassembly), C 14 random game functions from UTIL/BB overlays (no truth; graded for overclaiming).
Tools: tools/hive/fninfo.py, find_dos_wrappers.py, pilot.py (build | run [batch] [max_tokens] | score).
Data: /mnt/nvme/tlrb2/hive/pilot/ (items.jsonl, proposals.jsonl with raw outputs).

Results (graded by hand, not only the keyword scorer):
- Answered 42/50. 8 lost to runaway reasoning: 4 of 18 calls burned the full 48k-token budget with no answer.
- Known answers: A 17/17, B 10/13 = 27/30. All 3 misses were at confidence <= 0.5 (__IOerror, farfree, fprintf
  called sprintf). Every answer at confidence >= 0.6 was correct (25/25).
- Game functions: max confidence 0.6, mechanical descriptions; concrete claims spot-checked true. One soft
  overclaim ("main" at 0.55, no callers to confirm).
- Lead for M2: UTIL 5000:b547 randomizes flag bits in records of stride 0x8f = 143 B (the V20 player record).
  UTIL 4000:74ad upgrades a file from 0xE625 to 0xE97B bytes.
- Cost: 59k in / 430k out tokens, about $0.08. ~10k reasoning tokens per function on average.
- Speed: 44 min wall for 50 functions at 3 concurrent calls. Full ~6000 functions at that rate: ~3-4 days.
Verdict: accuracy and calibration are good enough; throughput is not. Use confidence >= 0.6 as the auto-accept bar
(still subject to Sonnet verification before a rename lands in Ghidra).

## Bake-off (same 50 functions, one function per call; tools/hive/bakeoff.py, probe.py)
Graded by hand where the keyword scorer missed correct answers. "hi-conf" = answers at confidence >= 0.6.

| Backend | Answered | Known right (A+B /36) | hi-conf right | Game overclaims >= 0.6 | Median s/fn | Notes |
|---|---|---|---|---|---|---|
| Z.AI GLM-5.3-Flash, thinking off | 50 | 26 | 28/28 | 2 (both plausible) | 6.9 | conc 4 ok, 429s at 8 |
| DeepSeek V4.1 Flash (Hive) | 50 | 25 | 26/26 | 0 | 7.2 | best calibration on game code |
| GLM-5.3-Flash (Hive, reasoning on) | 42 | 27/30 | 25/25 | 1 | ~150 | runaway reasoning, too slow |
| Kimi for coding highspeed | 31 | 19 | 19/20 | 1 | 11.6 | 5-hour quota gone after 31 calls |
| Haiku 4.5 (claude -p) | 50 | 23 | 21/26 | 7 | 32.4 | confident wrongs on runtime, overclaims game meaning |
| qwen3-coder:30b (local) | 50 | 12 | 12/26 | 8 | 3.1 | many 0.9+ wrongs, disqualified |

The Z.AI claim "BB 3000:73b9 = long double compare" checked out by hand: it compares two 10-byte reals
(exponent +8, sign +0xa, mantissa words 0..6) and returns FPU-status-style C3/C0 bits (0x4000 equal, 0x100 less),
so it belongs to the FPU emulator. No model named fprintf/printf/fopen/fread without callee names, so the bulk run
goes callees first. Verdict: Z.AI no-think + DeepSeek, two opinions per function (notes/RUN_PLAN.md).
