#!/bin/bash
# mgr_open.sh ITEMY [TEAMX TEAMY] -- from the DOS prompt: boot the game, open Manager menu item at ITEMY
# (231 roster, 253 staff, 275 rotation, 297 defense, 319 batting order, 341 profile), pick team (default Baltimore 588,294).
export DISPLAY=:98; X=~/tlrb2/scripts/xc.sh
source ~/tlrb2/tools/lane_b/lib.sh
boot; $X key Escape; sleep 3
$X menu 395 210 420 "$1"; sleep 6
$X click "${2:-588}" "${3:-294}"; sleep 5
