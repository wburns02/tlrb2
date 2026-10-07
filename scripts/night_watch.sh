#!/bin/bash
# night_watch.sh  -- overnight monitor for the TLRB2 parallel session. Exits nonzero on a stall signal.
LOG=/mnt/nvme/tlrb2/logs2/night_watch.log
echo "watch start $(date +%H:%M)" >> $LOG
while true; do
  sleep 120
  {
    commits=$(git -C /home/will/tlrb2 log --oneline -1 2>/dev/null)
    other=$(pgrep -fc 'name_all|bakeoff' 2>/dev/null)
    lock=$(ls /mnt/nvme/tlrb2/ghidra_proj/TLRB2.lock 2>/dev/null | wc -l)
    rig98=$(pgrep -c -x dosbox-x 2>/dev/null); rig97=$(pgrep -c -x dosbox 2>/dev/null)
    echo "$(date +%H:%M) commit=[$commits] namers=$other lock=$lock rig98=$rig98 rig97=$rig97"
  } >> $LOG
  # stall signals: naming processes gone AND no new commit in 40 min; or stale lock with no ghidra proc
  last=$(find /mnt/nvme/tlrb2/re /home/will/tlrb2/tools/re /home/will/tlrb2/notes -newermt '-40 min' -type f 2>/dev/null | head -1)
  if [ -z "$last" ] && [ "$(pgrep -fc 'name_all|bakeoff')" = "0" ]; then
    echo "STALL: no naming procs, no recent output" >> $LOG; exit 1
  fi
  if [ "$lock" = "1" ] && [ "$(pgrep -fc analyzeHeadless)" = "0" ] && [ "$(pgrep -fc 'gh.py')" = "0" ]; then
    echo "STALL: stale ghidra lock, no ghidra process" >> $LOG; exit 2
  fi
done
