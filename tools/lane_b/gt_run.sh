#!/bin/bash
# usage: gt_run.sh LABEL VIS_X VIS_Y HOME_X HOME_Y [x,y ...]
# Fresh rig (relaunch), exhibition game setup, extra clicks on the Ground Rules screen, play ball; copies GAME.TMP to snaps/gt_LABEL.tmp.
X=~/tlrb2/scripts/xc.sh; export DISPLAY=:98
L=$1; shift; vx=$1; vy=$2; hx=$3; hy=$4; shift 4
cp -a /mnt/nvme/tlrb2/snaps/m3_base/GAME.TMP /mnt/nvme/tlrb2/work/c/TONY2/GAME.TMP
~/tlrb2/tools/lane_b/relaunch.sh >/dev/null; sleep 15
ok=0
for i in $(seq 1 12); do
  $X key Escape; sleep 3; $X shot gt_probe >/dev/null 2>&1
  python3 - <<'P' && { ok=1; break; }
from PIL import Image
import sys
im=Image.open('/mnt/nvme/tlrb2/shots/gt_probe.png').convert('RGB')
r,g,b=im.getpixel((300,232)); sys.exit(0 if (r>140 and g>80 and b<80 and r>g) else 1)
P
done
[ $ok = 1 ] || { echo "main menu not reached"; exit 1; }
$X click 250 232; sleep 5
$X click $vx $vy; sleep 3
$X click $hx $hy; sleep 5
for c in "$@"; do $X click ${c%,*} ${c#*,}; sleep 1; done
$X shot gt_${L}_rules >/dev/null 2>&1
$X click 435 592; sleep 12
$X click 512 592; sleep 20
cp /mnt/nvme/tlrb2/work/c/TONY2/GAME.TMP /mnt/nvme/tlrb2/snaps/gt_$L.tmp
ls -l --time-style=full-iso /mnt/nvme/tlrb2/snaps/gt_$L.tmp
