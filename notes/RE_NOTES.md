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
