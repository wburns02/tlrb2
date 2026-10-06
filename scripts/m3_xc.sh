#!/bin/bash
# m3_xc.sh  -- drive the :97 rig (same verbs as xc.sh, but DISPLAY :97 and shots2/ logs2/).
export DISPLAY=:97
mkdir -p /mnt/nvme/tlrb2/shots2
W=$(xdotool search --name 'cycles/ms' 2>/dev/null | head -1)
[ -n "$W" ] && xdotool windowfocus --sync "$W" 2>/dev/null
case "$1" in
  shot) import -window root "/mnt/nvme/tlrb2/shots2/$2.png"; echo "/mnt/nvme/tlrb2/shots2/$2.png";;
  key) xdotool key --window "$W" "$2";;
  type) xdotool type --delay 80 "$2";;
  click) xdotool mousemove "$2" "$3"; sleep 0.3; xdotool mousedown 1; sleep 0.2; xdotool mouseup 1;;
  menu) xdotool mousemove "$2" "$3"; sleep 0.3; xdotool mousedown 1; sleep 0.8
        xdotool mousemove "$4" "$5"; sleep 0.5; xdotool mouseup 1;;
  win) echo "$W";;
  *) echo "usage: m3_xc.sh shot NAME | key K | type TEXT | click X Y | menu X Y IX IY | win"; exit 2;;
esac
