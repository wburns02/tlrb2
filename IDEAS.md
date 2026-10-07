# TLRB2 mod ideas (in-game only; full RE is the goal)

## Dynasty / multi-season mode (Will, 2026-10-06)
Things Tony 2 lacked: carry a league across seasons, player aging/progression/retirement, rookies,
Hall of Fame, career stat leaders, season history (champions, award winners).
Note: Utilities already has STATISTICAL LEADERS (single season); career/history is new.
RE needed first: season save format, where season stats live, the stats -> ratings formula (UTIL),
end-of-season flow (BACK/MAIN), and free memory/screen space for new screens.

## Historical imports (Lahman)
Depends on the V20 decode and the stats -> ratings formula.

## True fielding stats (for better in-game WAR)
The sim keeps no real putouts/assists per player (import overwrites PO/A with position averages x games; season
accumulators hold errors only). Recording real PO/A/DP per fielder means patching the play engine (BB/PLAY) to
bump new counters on each out, with only ~64+133 B of code caves there. Heavy lift; the M4 WAR approximation
works without it.

## New player faces (Will, 2026-10-07)
Generic faces: ANMS/PORTRAIT.ANM, u16 count 30 then 30 x (12 B hdr + 48 wide x 56 tall raw 8-bit), 85 palette
indices used (0, 7, 8, 48..64, 183..254). BB reads index i < 981 at i*0xa8c+0xe with no bounds check seen, so
appending frames may open slots 30..980 without a code patch (untested: count word, team colour remap). Plan:
image model renders head-and-shoulders, Python crops/downscales to 48x56 and quantizes to the used indices, pilot
10 faces on the rig before a full set. Fictional faces only. Replay ANMs stay blocked on the payload decode.

## Modern stadiums (Will, 2026-10-07)
Real-life photos of modern parks, run through the GPU for the retro look, as new playable stadiums.
What the RE already says (notes/FORMATS.md, STADIUMS): a stadium is two files, both loaded by BB at game start.
- <STEM>.CFG, 1289 B: name, a type byte, five fence distances in feet (LF, LCF, CF, RCF, RF), then polylines and
  tables whose meaning is unproven (likely wall and foul-line geometry in panorama coordinates).
- <STEM>.SDM: one DCL stream that explodes to a 1120 x 444 8-bit panorama, the view from behind home plate.
- A team picks its park by the 8-byte stem in its V20 header (+19); Assign Stadiums already writes it.
Gameplay is likely the easy half: the fence distances are plain numbers, so real dimensions go straight in. The
open RE items are (1) what the polylines drive (fielders, ball landing, home-run line on the panorama; must line
up with the new picture), (2) the runtime palette the SDM is drawn with (not in the CFG; the art must be quantized
to it), (3) a DCL encoder (we only have explode; a literal-only encoder is small and the stock loader should
accept it). Pipeline: photo from behind home plate -> img2img retro pass at 1120 x 444 -> quantize to the game
palette -> DCL encode -> CFG cloned from a similar stock park with the real distances. First proof: re-encode a
stock SDM losslessly and play a game in it, then swap in one AI panorama. Photos stay out of the public repo.
