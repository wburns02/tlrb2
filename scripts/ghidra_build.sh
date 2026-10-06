#!/bin/bash
# Rebuild flattened images, seed lists, the Ghidra project and the grep index from the pristine EXEs.
# usage: ghidra_build.sh [NAME ...]   (default: all 8 programs). Ghidra project: /mnt/nvme/tlrb2/ghidra_proj/TLRB2
set -e
T=/mnt/nvme/tlrb2; G=/mnt/nvme/ghidra/ghidra_12.1.4_PUBLIC/support/analyzeHeadless; R=$HOME/tlrb2
NAMES=("$@"); [ ${#NAMES[@]} -eq 0 ] && NAMES=(MAIN BB UTIL DRAFT BACK MANAGE PLAY CONTROL)
mkdir -p $T/flat $T/index $T/ghidra_proj
for n in "${NAMES[@]}"; do
  python3 -I $R/tools/vroomm_flatten.py $T/pristine/TONY2/$n.EXE $T/flat
  python3 -I $R/tools/make_seeds.py $T/flat $n $T/pristine/TONY2/$n.EXE
  # extra seeds: call targets inside known functions (tools/re/extra_seeds.py, run after a build)
  [ -f $T/flat/$n.seeds.extra.txt ] && cat $T/flat/$n.seeds.extra.txt >> $T/flat/$n.seeds.txt
  # DGROUP: Borland c0 starts with `mov dx,DGROUP` (BA lo hi); already relocated in the flat image
  DS=$(python3 -c "import sys;b=open(sys.argv[1],'rb').read(3);assert b[0]==0xba;print('%04x'%(b[1]|b[2]<<8))" $T/flat/$n.flat.bin)
  $G $T/ghidra_proj TLRB2 -import $T/flat/$n.flat.bin -overwrite -loader BinaryLoader -loader-baseAddr 1000:0000 \
     -processor "x86:LE:16:Real Mode" -cspec default -scriptPath $R/ghidra_scripts \
     -preScript SeedFunctions.java $T/flat/$n.seeds.txt $DS -postScript ExportDecomp.java $T/index/$n > $T/ghidra_$n.log 2>&1
  echo "$n: DS=$DS $(grep -o 'seeded.*failed' $T/ghidra_$n.log) | $(grep -o 'exported [0-9]*' $T/ghidra_$n.log) | decompile failures: $(grep -c 'decompile failed' $T/index/$n/_all.c)"
done
