#!/bin/bash
# Lane B: restart the :98 DOSBox-X rig under a pty so the ncurses debugger is enabled.
# Same kill semantics as relaunch.sh (SIGKILL escalation, work/c strays only). Game output
# that would go to the debugger console -> logs/dbg_pty.log; send debugger commands with
#   ~/tlrb2/tools/lane_b/dbg_pty.py cmd "MEMDUMPBIN 50:0 A0000 mb.bin"
T=/mnt/nvme/tlrb2
PIDF=$T/logs/dosboxx.pid
OLD=$(cat $PIDF 2>/dev/null)
for p in $OLD $(pgrep -f "^/mnt/nvme/src/dosbox-x/src/dosbox-x .*$T/work/c"); do
  kill "$p" 2>/dev/null; sleep 1; kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null
done; sleep 1
CMD="/mnt/nvme/src/dosbox-x/src/dosbox-x -conf $HOME/tlrb2/conf/tlrb2-x.conf -set mixer nosound=true -c 'mount c \"$T/work/c\"' -c 'imgmount d \"$T/iso/TONY2V13.iso\" -t iso' -c 'c:' -c 'cd \\\\TONY2' -c TONY2.BAT"
setsid python3 ~/tlrb2/tools/lane_b/dbg_pty.py start "$CMD" >/dev/null 2>&1 &
sleep 2
echo "new pid $(cat $PIDF 2>/dev/null)"
