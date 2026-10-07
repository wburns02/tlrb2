#!/bin/bash
# m3_gt.sh LABEL VIS_X VIS_Y HOME_X HOME_Y [x,y ...]  -- Lane B gt_run.sh for the :97/work2 rig.
# Fresh GAME.TMP from m3_base, dosbox-x relaunch, exhibition setup clicks, play, capture GAME.TMP+CONTROL+SYSTEM.
X=~/tlrb2/scripts/m3_xc.sh
T=/mnt/nvme/tlrb2
L=$1; shift; vx=$1; vy=$2; hx=$3; hy=$4; shift 4
cp -a $T/snaps/m3_base/GAME.TMP $T/work2/c/TONY2/GAME.TMP
~/tlrb2/scripts/m3_relaunch.sh >/dev/null; sleep 18
setsid strace -f -tt -y -e trace=openat,read,write,lseek,close -e signal=none -p "$(cat $T/logs2/dosboxx.pid)" -o $T/logs2/ftrace_gt2_$L.log < /dev/null > /dev/null 2>&1 & sleep 2
ok=0
for i in $(seq 1 12); do
  $X key Escape; sleep 3; $X shot gt2_probe >/dev/null 2>&1
  python3 - <<'P' && { ok=1; break; }
from PIL import Image
import sys
im=Image.open('/mnt/nvme/tlrb2/shots2/gt2_probe.png').convert('RGB')
r,g,b=im.getpixel((300,232)); sys.exit(0 if (r>140 and g>80 and b<80 and r>g) else 1)
P
done
[ $ok = 1 ] || { echo "main menu not reached"; exit 1; }
$X click 250 232; sleep 5
$X click $vx $vy; sleep 3
$X click $hx $hy; sleep 5
for c in "$@"; do $X click ${c%,*} ${c#*,}; sleep 1; done
$X shot gt2_${L}_rules >/dev/null 2>&1
$X click 435 592; sleep 12
base_ctl=$(od -An -tx1 $T/work2/c/TONY2/CONTROL 2>/dev/null | tr -d ' \n')
$X click 512 592
# poll until CONTROL differs from the pre-play baseline (BB exit rewrite), up to 5 min
for i in $(seq 1 12); do
  sleep 5
  cur=$(od -An -tx1 $T/work2/c/TONY2/CONTROL 2>/dev/null | tr -d ' \n')
  [ -n "$cur" ] && [ "$cur" != "$base_ctl" ] && break
done
echo "handoff after $((i*5))s: $cur"
for i in $(seq 1 480); do
  sleep 5
  cur=$(od -An -tx1 $T/work2/c/TONY2/CONTROL 2>/dev/null | tr -d ' \n')
  case "$cur" in 030*) break;; esac
done
echo "poll_end after $((i*5))s: $cur"
cp $T/work2/c/TONY2/GAME.TMP $T/snaps/gt2_$L.tmp
for f in CONTROL SYSTEM; do cp $T/work2/c/TONY2/$f $T/snaps/gt2_$L.$f; done
ls -l --time-style=full-iso $T/snaps/gt2_$L.tmp
