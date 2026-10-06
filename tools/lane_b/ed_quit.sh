#!/bin/bash
# ed_quit.sh -- DONE in player screen, then Main > QUIT (the editor writes the team file on exit). Leaves the DOS prompt.
export DISPLAY=:98; X=~/tlrb2/scripts/xc.sh
$X click 300 592; sleep 2   # DONE (position differs per screen; extra click is harmless)
$X key Escape; sleep 1; $X click 235 342; sleep 5
