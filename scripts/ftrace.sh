#!/bin/bash
# usage: ftrace.sh [OUT]  -- attach strace to the running DOSBox (staging or X) and log every host file
# open/read/write/seek with offsets and sizes (-y prints the path on every fd). Works because C: is a host
# directory mount. Stop with Ctrl+C. Output default /mnt/nvme/tlrb2/logs/ftrace.log; filter with:
#   grep -E '/mnt/nvme/tlrb2/(work/)?c/' OUT
OUT=${1:-/mnt/nvme/tlrb2/logs/ftrace.log}; mkdir -p "$(dirname "$OUT")"
PID=$(pgrep -x dosbox || pgrep -x dosbox-x | head -1); [ -n "$PID" ] || { echo "no dosbox running"; exit 1; }
exec strace -f -tt -y -e trace=openat,read,write,lseek,close -e signal=none -p "$PID" -o "$OUT"
