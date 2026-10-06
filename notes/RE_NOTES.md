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
Sanity: all 51 MAIN overlays start with 55 8B EC. MAIN 945 functions exported, 4 decompile failures; BB 1522/9.
Known gaps / next:
- DS is not set, so string and global references are unresolved. Find the DGROUP segment (Borland c0 startup
  loads DS from a relocated immediate near entry 1000:0000) and set the DS register context program-wide.
- Library code (Borland RTL, PKWARE DCL implode/explode) should be identified and named first (FLIRT-like
  signatures are not available for 16-bit in Ghidra; name by hand from known RTL entry patterns).
- Functions only reached through far pointers (callbacks, jump tables) may be missing: add seeds as found.

## Debugger (DOSBox-X heavy debug build, /mnt/nvme/src/dosbox-x)
Useful commands: BP seg:off, BPINT 21 3D (break on file open), BPM seg:off (memory change), MEMDUMPBIN seg:off len,
LOG n (trace n instructions to LOGCPU.TXT), SR (set register). Running-program segment differs from Ghidra's 1000:
Ghidra seg = runtime seg - (PSP + 0x10) + 0x1000.

## File-trace facts
- Utilities > Edit Player Stats reads TEAMS/<league>/<league>ALW1.V20 etc. in full (11735 B) and pages in a UTIL
  overlay (file offset 368144). The current league is CLASSIC (from SYSTEM).
- The editor asks "automatically calculate a player's ratings based on his new stats?": UTIL contains the
  stats -> ratings formula. Decoding it is the key to correct historical imports.
