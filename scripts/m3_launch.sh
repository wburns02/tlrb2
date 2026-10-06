#!/bin/bash
# m3_launch.sh  -- M3 season-state rig: isolated dosbox-staging on Xvfb :97 with the work2 install.
# Own display + own install = zero interference with the :98 rig. Drive with m3_xc.sh, trace with:
#   strace -f -tt -y -e openat,read,write,lseek,close -p $(pgrep -x dosbox | head -1)
T=/mnt/nvme/tlrb2; C=$T/work2/c
export DISPLAY=:97 SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11; unset WAYLAND_DISPLAY
pgrep -f 'Xvfb :97' >/dev/null || { (setsid Xvfb :97 -screen 0 1024x768x24 >/dev/null 2>&1 &); sleep 1; }
exec dosbox --noprimaryconf --conf "$HOME/tlrb2/conf/tlrb2.conf" \
  --set nosound=true --set output=surface \
  -c "mount c \"$C\"" -c "imgmount d \"$T/iso/TONY2V13.iso\" -t iso" \
  -c "c:" -c "cd \\TONY2" -c "TONY2.BAT"
