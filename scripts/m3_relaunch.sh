#!/bin/bash
# m3_relaunch.sh  -- restart dosbox-x on :97 with the work2 install (Lane B's relaunch.sh, :97/work2 variant).
T=/mnt/nvme/tlrb2
for p in $(pgrep -f "^/mnt/nvme/src/dosbox-x/src/dosbox-x .*$T/work2/c"); do
  kill "$p" 2>/dev/null; sleep 1; kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null
done
pkill -x dosbox 2>/dev/null; sleep 1
export DISPLAY=:97 SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11; unset WAYLAND_DISPLAY
cd $T/logs2
setsid /mnt/nvme/src/dosbox-x/src/dosbox-x -conf $HOME/tlrb2/conf/tlrb2-x.conf -set mixer nosound=true \
  -c "mount c \"$T/work2/c\"" -c "imgmount d \"$T/iso/TONY2V13.iso\" -t iso" -c "c:" -c 'cd \TONY2' -c TONY2.BAT >/dev/null 2>&1 &
echo $! > $T/logs2/dosboxx.pid
echo "new pid $(cat $T/logs2/dosboxx.pid)"
