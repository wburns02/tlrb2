#!/bin/bash
# regen.sh [PROG ...]  -- re-export decompilation + grep index from the Ghidra project (no reimport).
# Run after any rename/typing session in the project. setds+fixrefs are in gh.py (see README).
set -e
GHIDRA=/mnt/nvme/ghidra/ghidra_12.1.4_PUBLIC
PROJ=/mnt/nvme/tlrb2/ghidra_proj
IDX=/mnt/nvme/tlrb2/index
SCRIPTS=/home/will/tlrb2/ghidra_scripts
PROGS=("$@")
[ ${#PROGS[@]} -eq 0 ] && PROGS=(MAIN BB UTIL DRAFT BACK MANAGE PLAY CONTROL)
for P in "${PROGS[@]}"; do
  echo "=== regen $P ==="
  $GHIDRA/support/analyzeHeadless $PROJ TLRB2 -process $P.flat.bin -noanalysis \
    -scriptPath $SCRIPTS -postScript ExportDecomp.java $IDX/$P 2>&1 | tail -2
done
echo done
