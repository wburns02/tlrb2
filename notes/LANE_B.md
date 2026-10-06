# Lane B (dynamic) status

## Status 2026-10-06 (session ended before M3)
Done
- M2 player record fully mapped except u16@27 and u16@90/92 semantics. Layout in notes/FORMATS.md.
- tools/v20.py: Team/Player classes, dump, raw, diff, set. Parse+serialize is byte exact on CLASALE1.V20.
- In-game proof: v20.py set on work install CLASALE1.V20 (first name Zed, age 44, salary 4321, HR vs L 9),
  editor displays all of it. Screenshot /mnt/nvme/tlrb2/shots/rt1.png.
- Rig helpers: scripts/setf.sh, tools/lane_b/{lib.sh,ed_open.sh,ed_quit.sh}. Main > QUIT is what writes the .V20.
Open
- Header (295 B) lineup/rotation/bullpen lists, .MAJ layout, u16@27 (not a portrait), RTO field, streak values outside 4..10,
  third header box meaning, B=0 means L (unverified), stats-to-ratings formula (editor YES answer to auto ratings).
- M3 (season state trace with ftrace.sh/snap.sh) not started.
Next
- Decode header via Manager screens; MAJ via Setup Leagues / Edit Team Names / Assign Stadiums.
- Read UTIL 4000:74ad (MAJ upgrade) with tools/hive/fninfo.py.
Code addresses for Lane A (UTIL DGROUP 3954): position string table DS:0x0b6c (16 entries), pitch type strings near DS:0x0a0f,
editor screens SCREENS/EDITBATA.SCR, EDITBATB.SCR, EDITFLD.SCR, CHOOSEP.SCR. V20 record struct: 143 B, see FORMATS.md.
