#!/bin/bash
# xc.sh actions on the :98 headless display (dosbox-staging window; focus is required for mouse input)
#   click X Y | menu X Y ITEMX ITEMY (press on menu bar, drag to item, release) | shot NAME | key K | type TEXT
export DISPLAY=:98
W=$(xdotool search --name 'cycles/ms' 2>/dev/null | head -1)
[ -n "$W" ] && xdotool windowfocus --sync "$W" 2>/dev/null
case "$1" in
  shot) mkdir -p /mnt/nvme/tlrb2/shots; import -window root "/mnt/nvme/tlrb2/shots/$2.png"; echo "/mnt/nvme/tlrb2/shots/$2.png";;
  key) xdotool key --window "$W" "$2";;
  type) xdotool type --delay 80 "$2";;
  click) xdotool mousemove "$2" "$3"; sleep 0.3; xdotool mousedown 1; sleep 0.2; xdotool mouseup 1;;
  menu) xdotool mousemove "$2" "$3"; sleep 0.3; xdotool mousedown 1; sleep 0.8
        xdotool mousemove "$4" "$5"; sleep 0.5; xdotool mouseup 1;;
  *) echo "usage: xc.sh click X Y | menu X Y IX IY | shot NAME | key K | type TEXT"; exit 2;;
esac
