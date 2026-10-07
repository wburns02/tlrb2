#!/bin/bash
# usage: rc_games.sh LABEL N [VIS_X VIS_Y HOME_X HOME_Y]
# Plays N auto exhibition games (fresh rig each) with tools/lane_b/rc_sniff.py logging the BB play-result record to
# /mnt/nvme/tlrb2/s7/LABEL_k.log. A game is over when the log has been idle for 75 s. Leaves the last game's DOSBox running.
X=~/tlrb2/scripts/xc.sh; export DISPLAY=:98
T=/mnt/nvme/tlrb2; mkdir -p $T/s7
L=$1; N=$2; vx=${3:-435}; vy=${4:-294}; hx=${5:-590}; hy=${6:-294}
for k in $(seq 1 $N); do
  cp -a $T/snaps/m3_base/GAME.TMP $T/work/c/TONY2/GAME.TMP
  ~/tlrb2/tools/lane_b/relaunch.sh >/dev/null; sleep 15
  ok=0
  for i in $(seq 1 12); do
    $X key Escape; sleep 3; $X shot rc_probe >/dev/null 2>&1
    python3 - <<'P' && { ok=1; break; }
from PIL import Image
import sys
im=Image.open('/mnt/nvme/tlrb2/shots/rc_probe.png').convert('RGB')
r,g,b=im.getpixel((300,232)); sys.exit(0 if (r>140 and g>80 and b<80 and r>g) else 1)
P
  done
  [ $ok = 1 ] || { echo "main menu not reached"; exit 1; }
  $X click 250 232; sleep 5; $X click $vx $vy; sleep 3; $X click $hx $hy; sleep 5
  $X click 435 592; sleep 12
  PID=$(cat $T/logs/dosboxx.pid)
  LOG=$T/s7/${L}_$k.log; rm -f $LOG
  $X click 512 592; sleep 25
  setsid nohup python3 ~/tlrb2/tools/lane_b/rc_sniff.py $PID $LOG 1500 > $T/s7/${L}_$k.out 2>&1 &
  SP=$!
  sleep 3
  t0=$(date +%s)
  while :; do
    sleep 10
    now=$(date +%s); m=$(stat -c %Y $LOG 2>/dev/null || echo $now)
    [ $((now-m)) -gt 75 ] && [ $((now-t0)) -gt 120 ] && break
    [ $((now-t0)) -gt 1400 ] && break
  done
  kill $SP 2>/dev/null; sleep 1; kill -9 $SP 2>/dev/null
  $X shot rc_${L}_$k >/dev/null
  echo "game $k done lines=$(wc -l < $LOG)"
done
