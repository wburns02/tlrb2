#!/bin/bash
# usage: launch.sh [live|work] [headless]
#   live = /mnt/nvme/tlrb2/c (your real install), work = /mnt/nvme/tlrb2/work/c (experiments)
#   headless = run on Xvfb :98, silent (for automated tests); default = real desktop with sound
T=/mnt/nvme/tlrb2
case "${1:-live}" in live) C=$T/c;; work) C=$T/work/c;; *) echo "target must be live or work"; exit 2;; esac
[ -d "$C/TONY2" ] || { echo "no install at $C/TONY2"; exit 2; }
EXTRA=()
if [ "$2" = headless ]; then
  export DISPLAY=:98 SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11; unset WAYLAND_DISPLAY
  pgrep -f 'Xvfb :98' >/dev/null || { (setsid Xvfb :98 -screen 0 1024x768x24 >/dev/null 2>&1 &); sleep 1; }
  EXTRA=(--set nosound=true --set output=surface)
fi
exec dosbox --noprimaryconf --conf "$HOME/tlrb2/conf/tlrb2.conf" "${EXTRA[@]}" \
  -c "mount c \"$C\"" -c "imgmount d \"$T/iso/TONY2V13.iso\" -t iso" \
  -c "c:" -c "cd \\TONY2" -c "TONY2.BAT" 
