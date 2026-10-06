#!/bin/bash
# usage: snap.sh NAME [live|work]  -- copy the install's data files to /mnt/nvme/tlrb2/snaps/NAME for later diffing
T=/mnt/nvme/tlrb2; case "${2:-work}" in live) C=$T/c;; work) C=$T/work/c;; *) exit 2;; esac
D=$T/snaps/$1; [ -e "$D" ] && { echo "$D exists"; exit 1; }
mkdir -p "$D" && cp -a "$C/TONY2/." "$D/" && echo "$D"
