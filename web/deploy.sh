#!/bin/bash
# deploy.sh [--force]: push the current repo state to the browser build in one step.
#  1. copy our built EXEs (DYNASTY, DYNVIEW, HISTWR, ROSTERS, CREATE) into the web stage install
#  2. apply the BAT patch and the C10 menu patch to the stage (both idempotent)
#  3. build the js-dos bundle (stage + faces overlay + stadium CD) next to the served one
#  4. stop if nothing changed (bundle and index.html), unless --force
#  5. back up the served bundle and the saves on the host (keeps the last 4 of each), rsync, restart the unit
#  6. fetch the bundle back over HTTPS with auth and check its sha256 matches what was built
# Config (not in the repo): ~/.config/tlrb2/deploy.env sets TLRB2_WEB_HOST (ssh target) and optionally TLRB2_DATA;
# ~/.config/tlrb2/web_login holds url=, user=, password= for the site's basic auth. The password is never printed.
# Saves are never written, only copied to the backup dir; game files stay in the bundle, never in the repo.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
CFG=$HOME/.config/tlrb2
# shellcheck disable=SC1091
[ -f "$CFG/deploy.env" ] && . "$CFG/deploy.env"
: "${TLRB2_WEB_HOST:?set TLRB2_WEB_HOST in $CFG/deploy.env}"
DATA=${TLRB2_DATA:-/mnt/nvme/tlrb2}
W=$DATA/web; STAGE=$W/stage_dyn; SITE=$W/site
FORCE=${1:-}

say() { printf '[deploy] %s\n' "$*"; }

[ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ] || say "warning: repo has uncommitted changes"
say "repo $(git -C "$REPO" rev-parse --short HEAD)"

for e in blob/DYNASTY.EXE dynview_c/DYNVIEW.EXE histwr/HISTWR.EXE rosters_c/ROSTERS.EXE create_c/CREATE.EXE; do
  cmp -s "$REPO/tools/m4/$e" "$STAGE/TONY2/${e#*/}" || cp "$REPO/tools/m4/$e" "$STAGE/TONY2/"   # same bytes: keep the mtime
done
python3 "$REPO/tools/m4/rig/bat_patch.py" "$STAGE/TONY2"
python3 "$REPO/tools/m4/menu_patch.py" "$STAGE/TONY2" | sed 's/^/[deploy] /'

NEW=$SITE/tlrb2.jsdos.new
python3 "$REPO/web/build_bundle.py" "$STAGE" "$DATA/stadiums/tlub_parks.iso" "$NEW" "$DATA/faces/install" | tail -1
newsha=$(sha256sum "$NEW" | cut -c1-16)
oldsha=$(ssh "$TLRB2_WEB_HOST" 'sha256sum tlrb2-web/site/tlrb2.jsdos 2>/dev/null' | cut -c1-16)
idx_same=0; ssh "$TLRB2_WEB_HOST" 'cat tlrb2-web/site/index.html' | cmp -s - "$REPO/web/index.html" && idx_same=1
if [ "$newsha" = "$oldsha" ] && [ $idx_same = 1 ] && [ "$FORCE" != --force ]; then
  rm -f "$NEW"; say "served bundle $oldsha already current, nothing to deploy"; exit 0
fi
say "bundle $oldsha -> $newsha (index.html changed: $((1 - idx_same)))"
mv "$NEW" "$SITE/tlrb2.jsdos"; cp "$REPO/web/index.html" "$SITE/index.html"

TS=$(date +%Y%m%dT%H%M%S)
ssh "$TLRB2_WEB_HOST" "cd tlrb2-web && mkdir -p backup && cp -a saves backup/saves.$TS && cp site/tlrb2.jsdos backup/tlrb2.jsdos.$TS \
  && ([ -d studio ] && cp -a studio backup/studio.$TS || true) \
  && (ls -d backup/saves.* | sort | head -n -4 | xargs -r rm -r --) && (ls backup/tlrb2.jsdos.* | sort | head -n -4 | xargs -r rm --) \
  && (ls -d backup/studio.* 2>/dev/null | sort | head -n -4 | xargs -r rm -r --)"
rsync -a "$SITE/tlrb2.jsdos" "$SITE/index.html" "$TLRB2_WEB_HOST:tlrb2-web/site/"
ssh "$TLRB2_WEB_HOST" 'systemctl --user restart tlrb2-web && sleep 2 && systemctl --user is-active tlrb2-web' | sed 's/^/[deploy] unit /'

URL=$(sed -n 's/^url=//p' "$CFG/web_login"); URL=${URL%/}
K=$(mktemp); trap 'rm -f "$K"' EXIT; chmod 600 "$K"
printf 'user = "%s:%s"\n' "$(sed -n 's/^user=//p' "$CFG/web_login")" "$(sed -n 's/^password=//p' "$CFG/web_login")" > "$K"
code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/tlrb2.jsdos")
gotsha=$(curl -sf -K "$K" "$URL/tlrb2.jsdos" | sha256sum | cut -c1-16)
[ "$code" = 401 ] || { say "FAIL: site answered $code without credentials (expected 401)"; exit 1; }
[ "$gotsha" = "$newsha" ] || { say "FAIL: served $gotsha, built $newsha"; exit 1; }
say "live: $URL serves $gotsha, 401 without auth, backups at $TLRB2_WEB_HOST:tlrb2-web/backup/*.$TS"
