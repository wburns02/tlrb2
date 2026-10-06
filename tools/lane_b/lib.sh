# source me. Helpers for the headless editor rig (:98, DOSBox-X heavy, game at 192,200).
X=~/tlrb2/scripts/xc.sh
P() { $X click $1 $2; sleep 2.5; }        # open player (team list coords)
D() { $X click 255 592; sleep 2; }        # DONE (batting screens)
DF() { $X click 300 592; sleep 2; }       # DONE (fielding/pitching screens)
F() { ~/tlrb2/scripts/setf.sh "$@"; }     # F X Y VALUE
boot() { $X type "tony2"; $X key Return; sleep 14; }  # from DOS prompt to MAIN (intro skipped later)
