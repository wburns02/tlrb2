#!/bin/bash
# dbg_dump.sh LABEL: Alt+Pause (enter debugger), MEMDUMPBIN conventional memory, F5 (resume CPU).
# Dump lands in /mnt/nvme/tlrb2/logs/M4/LABEL.BIN (debugger uppercases names, so use an uppercase dir).
D=~/tlrb2/tools/lane_b/dbg_pty.py; L=/mnt/nvme/tlrb2/logs
W=$(DISPLAY=:98 xdotool search --name 'cycles/ms' | head -1)
DISPLAY=:98 xdotool key --window $W alt+Pause
sleep 2
BEFORE=$(wc -c < $L/dbg_pty.log)
$D cmd "MEMDUMPBIN 50:0 A0000 M4/$1.BIN"
for i in $(seq 1 30); do
  sleep 1
  tail -c +$((BEFORE-200)) $L/dbg_pty.log 2>/dev/null | grep -aq "Memory dump binary success" && break
done
tail -c +$((BEFORE-200)) $L/dbg_pty.log 2>/dev/null | grep -aq "Memory dump binary success" || echo "WARN: no success marker for $1"
sleep 1
$D raw '\x1b[15~'
sleep 2
ls -la $L/M4/$1.BIN 2>/dev/null
