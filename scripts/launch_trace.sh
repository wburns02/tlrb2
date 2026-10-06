#!/bin/bash
# usage: launch_trace.sh [live|work] [headless]  -- TLRB2 under the DOSBox-X heavy-debug build
# (/mnt/nvme/src/dosbox-x) with file I/O + INT 21h logging to /mnt/nvme/tlrb2/logs/dosbox-x.log (overwritten).
# Debugger: Alt+Pause in the window (curses UI on the launching terminal; run from a real terminal for that).
T=/mnt/nvme/tlrb2; BIN=/mnt/nvme/src/dosbox-x/src/dosbox-x
case "${1:-work}" in live) C=$T/c;; work) C=$T/work/c;; *) echo "target must be live or work"; exit 2;; esac
[ -d "$C/TONY2" ] || { echo "no install at $C/TONY2"; exit 2; }
mkdir -p $T/logs; : > $T/logs/dosbox-x.log
EXTRA=()
if [ "$2" = headless ]; then
  export DISPLAY=:98 SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11; unset WAYLAND_DISPLAY
  pgrep -f 'Xvfb :98' >/dev/null || { (setsid Xvfb :98 -screen 0 1024x768x24 >/dev/null 2>&1 &); sleep 1; }
  EXTRA=(-set "mixer nosound=true")
fi
cd $T/logs && exec $BIN -conf "$HOME/tlrb2/conf/tlrb2-x.conf" "${EXTRA[@]}" \
  -c "mount c \"$C\"" -c "imgmount d \"$T/iso/TONY2V13.iso\" -t iso" -c "c:" -c "cd \\TONY2" -c "TONY2.BAT"
