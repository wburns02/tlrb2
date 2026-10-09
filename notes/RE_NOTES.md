# TLRB2 reverse-engineering notes

## Program architecture (verified 2026-10-06)
TONY2.BAT is a loop: PLAY.EXE (front end/intro) then CONTROL.EXE returns an errorlevel that picks the next program:
1 MAIN (menus), 2 BACK, 3 BB (on-field game + sim engine), 4 MANAGE, 5 UTIL (editors), 6 DRAFT, 7 quit.
State passes between programs through files (CONTROL, SYSTEM, GAME.TMP; TBD which carry what). CHECKMEM gates on free memory.

All EXEs: 16-bit real-mode MZ, Borland C++ 3.x (1991 runtime), PKWARE Data Compression Library linked in
(data files are imploded; see PATCH.TXT "data files kept in compressed format").
MAIN, BB, UTIL, DRAFT, BACK use Borland VROOMM overlays (FBOV): 51/42/37/41/24 overlay segments.
MANAGE, PLAY, CONTROL have no overlays. NOTE: ANMS/*.OVL and stadium *.OVL files are art, not code.

## Ghidra
Flattened images (tools/vroomm_flatten.py): load image at 1000:0000 with MZ relocs applied, overlays appended
with their fixups applied, every stub thunk `CD 3F off 00` rewritten to `EA off seg` (far jmp to the overlay).
Import: Raw Binary, x86:LE:16:Real Mode, base 1000:0000. Seeds (tools/make_seeds.py): entry + thunk targets +
every `push bp; mov bp,sp` in its containing segment (segments from MZ reloc values). Rebuild: scripts/ghidra_build.sh.
Sanity: all 51 MAIN overlays start with 55 8B EC. Functions exported / decompile failures: MAIN 945/4, BB 1522/9, UTIL 981/7, DRAFT 886/5, BACK 755/2, MANAGE 512/1,
PLAY 303/0, CONTROL 93/0 (6,000 total). Failures are pcode errors on bad flow targets, not import problems.
Known gaps / next:
- Library code (Borland RTL, PKWARE DCL implode/explode) should be identified and named first. The same RTL is
  linked into all 8 programs: name it by hand in one (MAIN), then propagate to the other 7 with a Function ID
  database built from that program (or a byte-pattern script if FID does not handle 16-bit real mode; verify).
- Functions only reached through far pointers (callbacks, jump tables) may be missing: add seeds as found.

### DGROUP + DS references (verified 2026-10-06)
The c0 startup is byte-identical in all 8 programs (only the immediate differs):
`mov dx,<DGROUP>; mov cs:[291],dx; mov ah,30h; int 21h; mov bp,[2]; mov bx,[2c]; mov ds,dx; ...`
DGROUP per program: MAIN 40fa, BB 5120, UTIL 3954, DRAFT 1f31, BACK 2c71, MANAGE 28bf, PLAY 170a, CONTROL 123e.
Flat layout: flat byte i maps to segment 0x1000 + i/16, so DS=S makes S*16 + off the exact Ghidra address.
Verified: "EDIT PLAYER STATS" and the whole string pool land inside each program's DGROUP.
Pipeline (ghidra_scripts/gh.py, live pyghidra access, BBPro98's venv):
- `setds PROG SEG`: ProgramContext DS over the whole range + full re-analysis. Memory operands (`mov [7d],ax`)
  then resolve to DAT_<dgroup>xxxx. Immediates (`mov dx,0xcdf`) do NOT auto-resolve.
- `fixrefs PROG SEG`: adds DATA refs from instruction scalars AND every DGROUP word whose value equals a
  defined-string DGROUP offset (menu strings live behind arrays of far pointers off,seg in DGROUP, e.g. UTIL
  DGROUP+242 'MAIN MENU', each entry followed by word 3954). Positive control: 'EDIT PLAYER STATS' (UTIL 3a21f,
  DGROUP cdf) referenced from the far-pointer table at DGROUP 29a. Refs are SourceType.ANALYSIS; short-string
  matches can be false positives. Run setds then fixrefs, then regen.
- Commands: setds / fixrefs / strings / xrefs / decomp / rename / label / structs.
- Status 2026-10-06 18:05: setds+fixrefs+regen applied to ALL 8 (second pass, after the DS-aware reimport batch
  from the parallel session, whose exports still lacked resolution). Indexes now carry DGROUP global refs
  (DAT_3000_xxxx = DGROUP seg rendering; DAT_4000_xxxx = overlay area) and 1395 s_ string labels in UTIL.
  String text appears in decomp only where code touches it directly; menu strings are behind DGROUP far-pointer
  tables (off,seg pairs), reachable via the table base, not the string itself.

## CONTROL.EXE transition logic (decoded 2026-10-06, static, no rig needed)
CONTROL's main = control_main_loop (1000:2287): rtl_fopen("control","rb") (rtl wrappers renamed in the project:
fopen 1000:1276, fread 1000:139f, fwrite 1000:160f, fclose 1000:0ed8). On missing file it creates it ("wb"),
writes the 9-byte default state (control_state_buf = DGROUP+0x2ec, renders as DAT_1000_26cc; display offset =
DGROUP + 0x23e0 in this program), else reads 9 bytes into it. State[1] = next program id: 1 MAIN, 2 BACK,
3 BB, 4 MANAGE, 5 UTIL, 6 DRAFT, 7 quit (exit(7) = errorlevel 7 ends TONY2.BAT). Pristine file bytes
`03 07 00 00 01 00 00 ff ff` map 1:1 onto the buffer. The 6 per-program switch branches are a jump table
Ghidra truncated (bad instruction data) - seed or trace them if the details matter.

## Debugger (DOSBox-X heavy debug build, /mnt/nvme/src/dosbox-x)
Useful commands: BP seg:off, BPINT 21 3D (break on file open), BPM seg:off (memory change), MEMDUMPBIN seg:off len,
LOG n (trace n instructions to LOGCPU.TXT), SR (set register). Running-program segment differs from Ghidra's 1000:
Ghidra seg = runtime seg - (PSP + 0x10) + 0x1000.

## Program transition protocol (live-proven 2026-10-06, :97 rig, strace)
Every program writes BOTH files on exit, then exits with errorlevel = next program id:
- `CONTROL` 9 B: [0]=program that just ran (1 MAIN, 2 BACK, 3 BB, 4 MANAGE, 5 UTIL, 6 DRAFT, 7 quit),
  [1]=next program id, then 00 00 01 00 00 ff ff. Observed MAIN->DRAFT `01 06 ...`, DRAFT->MAIN `06 01 ...`.
  Matches the control_main_loop decode above (state[1] drives the nextprogram choice).
- `SYSTEM` 76 B (league name "CLASSIC" + settings) rewritten verbatim each transition.
Save slots: the PLAY BALL > LOAD SAVED GAME list probes `1.SAV`..`10.SAV` (all ENOENT on a fresh install).
CLASSIC.MAJ is rewritten wholesale (59,771 B) when season screens open/close - league state is round-tripped
through .MAJ, team season stats live in the V20 second half (see FORMATS.md). SCREENS/*.SCR are not on C:;
they are read from the CD (D:). MAIN overlays page in by EXE file offset (e.g. 307424).
Rig for this: scripts/m3_launch.sh + m3_xc.sh (Xvfb :97, install /mnt/nvme/tlrb2/work2/c from pristine;
strace with `-p $(pgrep -x dosbox | head -1)`). Isolated from the :98 rig.
Open: the SEASON > PLAY LEAGUE GAMES date browser does not respond to keyboard or synthetic clicks
(game boxes not hot; the CLASSIC league ships pre-draft - games may require completing the draft first).
Sim/ GAME.TMP / end-of-season flow still need a completed-league trace.

## Night shift 2026-10-06/07 (:97 rig, scripts/m3_gt.sh + m3_gt_batch.sh)
Exhibition-game flow replicated on the :97/work2 rig (dosbox-x, Lane B's m3_base GAME.TMP): MAIN handoff
writes CONTROL `01 03 ...` when PLAY BALL is pressed, BB.EXE loads and plays on-field (computer/computer,
VERY FAST + one-pitch still shows full animations; a game takes >>7 min). Save cascade on handoff:
GAME.TMP 7446 + CLASSIC.MAJ 59771 + CONTROL + SYSTEM. Exhibition games write NO ALLTIME.BOX (confirms
Lane B's open item; the writer never fires outside season context). gt2_* snaps + per-run strace logs in
snaps/ and logs2/. Run-to-run state pollution: poll from a fresh baseline, wait for the SECOND CONTROL
rewrite (pattern 03*), not the handoff. Batch of 6 matchups ABORTED: guessed click coords missed the team dialogs (only the proven CAL(435,293)/BAL(600,293) pair works), and full-animation computer games do not finish in 40 min even at cycles=max - game pacing is wall-clock bound. Lane B session 6 superseded the goal by playing a real SEASON featured game (CLE 2 @ BAL 1) and confirming the merge + ALLTIME.BOX writer (see LANE_B.md).

## .SCH schedule files (observations 2026-10-06, static only; needs a trace to decode properly)
162_26.SCH 57,176 B: +0 ASCII "162 Games-26 Teams" (16 B + 2 NUL). +0x14 u32 (5e 5d ca 02, unknown; not a
DOS date). +0x18 a run of x86 code bytes (55 8b ec push bp / mov bp,sp...) for ~70 B then zeros to +0xc0 -
either an embedded stub or a dumped struct with far pointers; unexplained. From +0xc0: sequences of team ids
(01..0e) in game-order groups, e.g. `04 09 01 03 0a` - plausibly per-date (away,home) pairings. Do NOT decode
further by guessing: ftrace a season action (which program opens .SCH, offsets read) first.

## File-trace facts
- Utilities > Edit Player Stats reads TEAMS/<league>/<league>ALW1.V20 etc. in full (11735 B) and pages in a UTIL
  overlay (file offset 368144). The current league is CLASSIC (from SYSTEM).
- The editor asks "automatically calculate a player's ratings based on his new stats?": UTIL contains the
  stats -> ratings formula. Decoding it is the key to correct historical imports.

## Menu bar (MAIN, decoded 2026-10-08, static plus the :98 rig; patch tools/m4/menu_patch.py, contract C10)
- Menu data segment 1eba (file pre-relocation seg 0x0eba): dropdown structs of 22 words (count, enable mask, 16
  string ids, 4 runtime words) at 0x00 ball, 0x2c plate stats, 0x58 SEASON, 0x84 MANAGER, 0xb0 UTILITIES. The bar
  struct at 0xdc: count (5), mask, then 5-word entries (submenu index, flags 0x8000 top level | 0x2000 right
  aligned, string id, x, width); x and width are computed at runtime from the string, so a new entry stores 0.
- DGROUP 0x2208: far pointers to the dropdowns by submenu index; DGROUP 0x221c: far pointers to the menu strings by
  string id (0x2e entries, then the string pool from 0x22d4 with PLAY BALL! first). Index k of the first table is
  slot k - 5 of the second (the tables overlap), so submenu 13 is string slot 8.
- Only the four menu routines read the string table (`shl bx,2; push dword [bx+0x221c]`); no code addresses a pool
  string directly, so strings can move as long as the slot is repointed.
- String ids 8, 0xd and 0x20 are in no MAIN menu (8 is the old submenu-13 slot, 0xd PLAY TO RESERVED GAME, 0x20
  SIMULATED STATS); 0x2d is IMPORT ONLINE SERVICE STATS in UTILITIES (dead online-service import).
- The menu loop lives in overlay 4ec4 (flat 0x4ec40). A pick returns code = bar << 4 | item; the loop decodes
  `mov dx,si; shr dx,4; and si,0xf; mov bx,dx; dec bx; cmp bx,3` at 4ec4:01d4 and jumps through a 4-entry table
  for bars 1..4; anything else falls to the exit test. The loop exits when CONTROL[1] != 1 (CONTROL buffer far
  pointer at DS:0x9b64), and MAIN then saves and quits as for any program switch.
- 1eba:0112..017f is zero in the file and in RAM at menu idle (cave scan plus a :98 rig memory dump at the menu).
- Overlay code cannot far call into the resident image by a relocated pointer from the patch (the overlay has no
  relocation for new bytes), so the hook computes the 1eba segment as DS - 0x2240 (DGROUP 40fa minus 1eba) and
  enters by push / push / retf.
- CONTROL.EXE (seg 1228:00cd): `cmp bx,5; ja; shl bx,1; jmp cs:[bx+0x127]` over states 1..6, every handler
  `exit(state[1])`. The patch makes it `cmp bx,10; ja; inc ax; jmp exit`.
- Rig check 2026-10-08 (:98, rt1.py): the bar shows DYNASTY with four items; DYNASTY MODE leaves MAIN with CONTROL
  `01 08 ...`; MAIN restarts normally with CONTROL[1] = CONTROL[0].

