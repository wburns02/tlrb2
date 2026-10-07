# Lane B (dynamic) status

## Status 2026-10-06 (third Lane B session)
Done (all committed; evidence in FORMATS.md, code names in lane_names.tsv)
- M2 record and header: V20 header fully decoded including colors (+44..91, tools/v20.py colors/set_colors), abbreviation, stadium stem and the draft GM
  profile (+237..244: 7 percentages summing to 100 plus preset index 0..5, code DRAFT 2000:ecfd and 2000:f6c9). Parse and serialize are byte exact on all shipped teams.
- M3 MAJ: layout, per-day arrays, doubleheader rows, name/abbr/stem tables, DH flag at S+0x132b, injuries flag at AL block +0x35b, cancel and night arrays.
  tools/maj.py has accessors and setters. DH and injuries flags proven on screen with positive controls (new-season dialog, shots n13, p1..p3).
- Team names, abbreviations, colors, stadium assignment are stored in the V20 headers plus the MAJ name tables (Edit Team Names changes both). Proven by snap diffs.
- Stats-to-ratings: all nine auto ratings decoded (power, hit and run, bunt, speed, range, arm, velocity, control, endurance) and implemented in tools/ratings.py.
  Checked against every shipped player with real stats: 99.7 to 100 percent exact. Code UTIL 1000:b02a..b82f, 5000:e298/e477.
- GAME.TMP: size, writer/reader, home-first team stems, night flag, stadium bytes, random weather-like bytes. Ground Rules DH/errors/injuries/stats are not in it.
- New rig tools: tools/lane_b/relaunch.sh (restart own DOSBox-X by pid file), gt_run.sh (scripted exhibition game that captures GAME.TMP).
Open
- Player record u16@27 (not the portrait, probably an id), u16@90/92 (probable RTO% ratio), +0x85 counter (not found in code; the UTIL hits at +0x85 are another struct).
- Header +237..244 category labels (screen file profile2.scr), meaning of the 7 percentages beyond "draft GM weights".
- GAME.TMP lineup/defense block and play log layout, where BB keeps the Ground Rules switches. UTIL 5000:a5aa/f382/f697 "overall rating" (109..9999) formula.
- Cause of the ordering of NL schedule rows in the SCH (+0x6fd4) not verified beyond one row match.
Next
- Decode the GAME.TMP lineup block by varying lineups with the Manager screen; read BB for the Ground Rules storage.
- Earlier-session facts that still hold: season flow (CONTROL byte meanings, V20s written only at Main > QUIT, PLAYOFFS.* layout, Start New Season effects).
Code addresses for Lane A (BACK DGROUP 2c71 unless noted): streak setters 1000:95da/95fb, starter chooser 1000:9d84, rain postpone 1000:57c0, day slot loop 1000:523d,
injury roll 1000:98f3, MAIN night flags 6000:0ba2, DRAFT GM profile 2000:ecfd/f6c9, MAIN GAME.TMP writer 4000:d07d, BB reader 6000:c4da,
UTIL (DGROUP 3954) rating formulas 1000:b02a b121 b1cd b29c b3d8 b541 b68e b74a b82f, per_mille 1000:a478, import 5000:e298/e477,
CONTROL.EXE FUN_1228_0007 (reads CONTROL). V20 record struct 143 B, see FORMATS.md.
State: work install restored to snaps/m3_base. My DOSBox-X (pid in /mnt/nvme/tlrb2/logs/dosboxx.pid) is on :98.
