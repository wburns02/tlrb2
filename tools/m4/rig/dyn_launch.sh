#!/bin/bash
# Launch DOSBox-X for dynasty gate on :98. Kills only strays from the install root.
# usage: dyn_launch.sh INSTALL_ROOT [PIDFILE]

INSTALL_ROOT="${1:-/mnt/nvme/tlrb2/work/dyn/c/TONY2}"
PIDF="${2:-/mnt/nvme/tlrb2/logs/t6/dosboxx.pid}"
MOUNT_ROOT="${INSTALL_ROOT%/*}"  # Parent dir (c not c/TONY2)

OLD=$(cat "$PIDF" 2>/dev/null)

# Kill the old process (by pid if known, else by install path pattern). DOSBox-X ignores SIGTERM.
if [ -n "$OLD" ]; then
  kill "$OLD" 2>/dev/null
  sleep 1
  kill -0 "$OLD" 2>/dev/null && kill -9 "$OLD" 2>/dev/null
fi

# Reap any strays on THIS install path (not touching other rigs). Match the exact binary name, then check
# the mount path in its argv, so no shell whose command text mentions the path can match.
for p in $(pgrep -x dosbox-x 2>/dev/null); do
  if tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | grep -qF "mount c \"$MOUNT_ROOT\""; then
    kill -9 "$p" 2>/dev/null
  fi
done
sleep 1

# Launch
export DISPLAY=:98 SDL_AUDIODRIVER=dummy SDL_VIDEODRIVER=x11
unset WAYLAND_DISPLAY
mkdir -p /mnt/nvme/tlrb2/logs/t6
cd /mnt/nvme/tlrb2/logs/t6
setsid /mnt/nvme/src/dosbox-x/src/dosbox-x -conf "$HOME/tlrb2/conf/tlrb2-x.conf" \
  -set mixer nosound=true \
  -c "mount c \"$MOUNT_ROOT\"" \
  -c "imgmount d \"/mnt/nvme/tlrb2/iso/TONY2V13.iso\" -t iso" \
  -c "c:" -c "cd \TONY2" -c "TONY2.BAT" >/dev/null 2>&1 &
echo $! > "$PIDF"
echo "launched pid $!"
