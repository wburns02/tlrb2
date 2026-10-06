#!/bin/bash
# ed_open.sh TEAMX TEAMY  -- from MAIN menu: Utilities > Edit Player Stats, click team at (X,Y), answer NO to auto-ratings.
# (DOSBox-X heavy build on :98, game area at 192,200.)  Baltimore = 589 294.
export DISPLAY=:98; X=~/tlrb2/scripts/xc.sh
$X key Escape; sleep 1
$X menu 490 210 520 342; sleep 6
$X click "${1:-589}" "${2:-294}"; sleep 3
$X click 540 440; sleep 4
