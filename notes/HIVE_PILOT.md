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
