#!/bin/bash
# setds_all.sh  -- set DGROUP as the DS register over every program + fixrefs string pass.
# DGROUP values from the c0 startup immediate (see notes/RE_NOTES.md). ~5 min per program.
PY=/mnt/nvme/bbpro98/ghidra_venv/bin/python3
GH=/home/will/tlrb2/ghidra_scripts/gh.py
for spec in "MAIN 40fa" "BB 5120" "UTIL 3954" "DRAFT 1f31" "BACK 2c71" "MANAGE 28bf" "PLAY 170a" "CONTROL 123e"; do
  set -- $spec
  echo "=== $1 DS=$2 $(date +%H:%M) ==="
  $PY $GH setds $1.flat.bin $2 2>&1 | tail -2
  $PY $GH fixrefs $1.flat.bin $2 2>&1 | tail -1
done
echo ALL_DONE $(date +%H:%M)
