#!/bin/bash
# Lane B: restart my own DOSBox-X on :98 (work install). Kills only the pid in logs/dosboxx.pid (or $1). Game boots straight into TONY2.BAT.
# TLRB2_ISO overrides the CD image (default: the stock TONY2V13.iso), e.g. one rebuilt by tools/stadium.py.
T=/mnt/nvme/tlrb2
PIDF=$T/logs/dosboxx.pid
OLD=${1:-$(cat $PIDF 2>/dev/null)}
# DOSBox-X ignores SIGTERM (it lingers on :98 and takes clicks), so escalate to SIGKILL. Also reap any stray DOSBox-X
# on the work install left by earlier relaunches. Never touches the :97 rig (plain dosbox on work2).
for p in $OLD $(pgrep -f "^/mnt/nvme/src/dosbox-x/src/dosbox-x .*$T/work/c"); do
  kill "$p" 2>/dev/null; sleep 1; kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null
done; sleep 1
export DISPLAY=:98 SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11; unset WAYLAND_DISPLAY
# The click coordinates assume a 1024x768 screen: start :98 at that size if it is missing (a 1280x1024 :98 centres the
# window elsewhere and every click misses).
pgrep -f '^Xvfb :98' >/dev/null || { (setsid Xvfb :98 -screen 0 1024x768x24 >/dev/null 2>&1 &); sleep 1; }
cd $T/logs
setsid /mnt/nvme/src/dosbox-x/src/dosbox-x -conf $HOME/tlrb2/conf/tlrb2-x.conf -set mixer nosound=true \
  -c "mount c \"$T/work/c\"" -c "imgmount d \"${TLRB2_ISO:-$T/iso/TONY2V13.iso}\" -t iso" -c "c:" -c 'cd \TONY2' -c TONY2.BAT >/dev/null 2>&1 &
echo $! > $PIDF
echo "new pid $(cat $PIDF)"
