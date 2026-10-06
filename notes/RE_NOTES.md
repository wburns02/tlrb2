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

## Debugger (DOSBox-X heavy debug build, /mnt/nvme/src/dosbox-x)
Useful commands: BP seg:off, BPINT 21 3D (break on file open), BPM seg:off (memory change), MEMDUMPBIN seg:off len,
LOG n (trace n instructions to LOGCPU.TXT), SR (set register). Running-program segment differs from Ghidra's 1000:
Ghidra seg = runtime seg - (PSP + 0x10) + 0x1000.

## File-trace facts
- Utilities > Edit Player Stats reads TEAMS/<league>/<league>ALW1.V20 etc. in full (11735 B) and pages in a UTIL
  overlay (file offset 368144). The current league is CLASSIC (from SYSTEM).
- The editor asks "automatically calculate a player's ratings based on his new stats?": UTIL contains the
  stats -> ratings formula. Decoding it is the key to correct historical imports.
