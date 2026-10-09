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
Pilot DONE 2026-10-08 (tools/faces.py, art and shots in /mnt/nvme/tlrb2/faces/pilot): juggernautXL on the local
ComfyUI, 10 fictional faces appended as ids 30..39 (count word 30 -> 40), every player of the work install pointed
at them, exhibition CAL @ BAL played on the rig: new faces render in the at-bat panels with team-coloured caps and
collars (BAL black/orange, CAL navy). Gotcha found on the way: the remap swaps all of 48..63 (56..63 = secondary
team ramp, browns in DEFAULT.PAL), so 56..63 must stay out of skin and beards. Open for a full set: the UTIL face
picker (DS:776e group table) only knows faces 0..29, so new faces reach players only through our own tools
(C4 rookies or a league builder); one pilot face (05) came out with a gray cap that does not take the team colour.
Full set DONE 2026-10-08: 67 new faces (9 pilot + 58 of 60 set1; 2 rejected for caps that will not take the team
colour), ids 30..96, built to /mnt/nvme/tlrb2/faces/install/TONY2/ANMS (PORTRAIT.ANM + FACEGRP.DAT). Every render
was checked by eye against its group flag (one prompt for a Black player rendered light skin and was reflagged 0).
The "picker" is UTIL's random generic-face assignment at league import, not a menu; it needs no patch, because
dynasty rookies come from our C4 generator, which now draws from every installed face and copies the group flag
from FACEGRP.DAT (amendment F1). To install: copy both files into the game's ANMS folder (keep a backup of the
stock PORTRAIT.ANM). Existing players keep their faces; new faces appear on rookies from the next dynasty roll.

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
Step 1 DONE 2026-10-08: DCL encoder (tools/dcl.py implode, all 41 stock SDMs round-trip at 1.02..1.05x size) and
tools/stadium.py (unpack, pack, marker, iso). A re-encoded GRASS.SDM with a test block plays in game from a rebuilt
CD image (stadiums load only from the CD drive).
Step 2 DONE 2026-10-08: the palette is in the CFG after all (0x33, DAC 80..175); the CFG header, conditions and the
two edge tables (fence base and stands wall, 70 columns of 16 px) are decoded (tools/stadium.py info). The stadium
list is built from the CFGs on the CD, so a new park needs no exe change. tools/parkgen.py made the first new park,
ZMODERN "TLUB MODERN BALLPARK": GRASS's field kept pixel for pixel, stands, skyline and video boards regenerated by
SDXL inpainting, 24 free palette slots by k-means. It shows in Assign Stadiums and plays in game
(/mnt/nvme/tlrb2/stadiums/zmodern.iso). Next: (1) photo-guided stands (a real park photo as the init or an
IP-Adapter reference for the masked region, photos kept out of the repo), (2) parks with other dimensions: real
fence distances are one CFG edit, but a differently shaped field needs a new field render plus new edge tables,
(3) more variety: a night prompt, a classic-park prompt, a dome base (TURF).
Step 3 2026-10-08: the CFG is fully mapped (notes/FORMATS.md). Correction: the 0x20 fence distances are display only;
play uses the edge tables, which are the real park in feet through BB's field to panorama map (GRASS inverts to
326/372/402). Fence height per column is at 0x475 (FENWAY's wall 34 ft). tools/stadium.py fences / refence read and
write it, so a new shape is: new fence rows plus a panorama redrawn to match.

## From ClaudeBall (~/ClaudeBall, surveyed 2026-10-07)
Taken: batting-order slot roles (src/engine/ai/LineupBuilder.ts) into C6 step 7. Earlier: trade value bands and
position weights (TradeEngine), retirement shape (DevelopmentEngine, since superseded by C1).
Queued:
- Awards (OffseasonEngine.generateAwards): the set MVP, Cy Young, Rookie of the Year, Gold Glove, Silver Slugger
  per league. Take the set, not the method: ClaudeBall picks from ratings; ours should pick from season stats and
  the C3 WAR10 HISTWR already computes. Storage: HISTORY season entry bytes 88..127 (reserved for P4 awards).
- Milestones (player/CareerEngine.ts MILESTONE_DEFS): career thresholds (500 HR, 3000 H, 300 W, 3000 K, ...) and
  season marks (40 HR, .300, 20 W, sub-2.00 ERA). HISTWR sees career totals before and after each season, so it
  can log "reached 3000 hits in season N" for a league-news / history screen.
- Hidden development trait (DevelopmentEngine work_ethic scales growth, decline and retirement): today every young
  player has the same expected growth, so every rookie class has the same shape. A per-player grade in record byte
  142 (zero in every stock record, game use unverified) feeding the C1 drift and retirement odds would give
  boom/bust prospects and late bloomers. C1 + asm change; decide after the 50-season validation.
- Historical leagues: ClaudeBall preprocessed Lahman 1900-2019 (public/data/lahman, from the SQLite at
  /mnt/win11/Fedora/lahman). A Lahman -> V20 + MAJ builder would let any real season be played. Ratings must come
  from the game's own decoded stat-to-rating formulas (the C1 evidence targets), not ClaudeBall's conversion.
Not worth taking: its HoF score (counting stats only, ours has WAR/JAWS), position assignment (takes the first
candidate, not the best), morale/hot-cold/injury/schedule/commentary (the TLRB2 engine has its own).

## Play in a web browser with saves (Will, 2026-10-08)
DONE. web/: build_bundle.py packs an installed C: drive (plus overlays such as the faces install) and the parks CD
image into a js-dos bundle; server.py serves it on localhost with a server-side save store; index.html runs it in
js-dos (DOSBox-X backend). Host it behind a private HTTPS proxy only (the bundle is the game, never public). Saves
are server-side named slots: Save now, Save as, Load, Delete (to history), New league from the clean bundle,
restore any of the last 20 versions per slot, autosave every 2/5/10 min plus on tab hide. Slot switches reload
the page (js-dos 8.5.3 props.stop() never resolves). The deployed bundle is a dynasty install: QUIT after the
World Series loops back through TONY2.BAT, which rolls the season (the full DYNASTY + HISTWR + ROSTERS + DYNVIEW
chain, byte-exact against the Python reference in the browser too; rookies draw from the new faces table).

## Old seasons are never destroyed (Will, 2026-10-08)
Stock Start New Season wipes the simulated season and box scores. Dynasty now archives first: ARCHIVE.BAT (written
by bat_patch) copies the finished pre-roll league (all V20s, MAJ, PLAYOFFS, HISTORY, MILESTON, RETIRED) to the first
free C:\SEASONS\Snn before the roll, verified byte-exact in the browser. Career stats, history, awards and the Hall
of Fame already carry forward. Open: browse an archived season in game (DYNVIEW "past seasons": standings, leaders,
playoff box scores from SEASONS\Snn). No pre-roll guard is needed (probe 2026-10-08): SEASON > START NEW SEASON
on BACK's post World Series menu saves the season and exits through the BAT, which archives and rolls it like QUIT.

## Next season sequence like BBPRO / ClaudeBall (Will, 2026-10-08)
DONE (contract C8a). The roll ends in `dynview /offseason`, six screens walked with ENTER: season in review,
retirements (with new Hall of Famers), rookie draft, trades, free agent signings, then SEASON N+1 IS READY with the
counts; ENTER hands on to MAIN's new season flow. Also on the DYNVIEW menu as `6  OFFSEASON`. DYNVIEW now restores
the caller's video mode, registers and palette (MAIN after BACK never sets the mode). Open: a draft order and
per-team needs shown during the draft (BBPRO style), the user's own team highlighted, and release reasons.

## Create a player, create a team (Will, 2026-10-08, deep research TODO)
Stock: only UTIL Edit Player Stats (age, salary, names; ratings recomputed from stats unless the user-set flag at
record byte 140 is on), Edit Team Names, Assign Stadiums, Team Colors. No generator, no face picker (faces are
random at import), no create-team flow. Building blocks we own: V20 record and team header decode, ratings.py
(all 9 formulas + salary), m4/rookies.py RookieGen, m4/team_fill.py, faces 30..96 + FACEGRP.DAT, parkgen +
stadium refence, DYNVIEW as the pattern for new in-game screens, MAJ slot 7 unused. Candidate path, cheapest
first: archetype player creator on RookieGen (position, grade, handedness, face), draft-style GM presets, create a
team in MAJ slot 7 (name, abbr, colours, generated park, roster via fill_team or an expansion draft from the
pools), then an in-game create screen (name entry, face browser over 30..96, rating sliders with live salary).
Gaps: uniform drawing, logo, typed-name entry UI, position eligibility rules. Needs a design pass with Will.
