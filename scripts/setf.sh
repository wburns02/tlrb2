#!/bin/bash
# setf.sh X Y VALUE  -- click a field in the editor, type VALUE, Enter (headless :98 rig)
~/tlrb2/scripts/xc.sh click "$1" "$2"; sleep 0.5; ~/tlrb2/scripts/xc.sh type "$3"; sleep 0.3; ~/tlrb2/scripts/xc.sh key Return; sleep 0.5
