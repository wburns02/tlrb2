# M4 design: dynasty / multi-season mode (for Will's review, not built)

Status: DRAFT 2026-10-07. Three inputs come from Lane B9 and are marked TBD-B9: memory headroom numbers, the
next-season-twin copy semantics, and the draft pool generator. Everything else is grounded in the completed M1-M3 RE
(FORMATS.md is the source for every offset cited here).

## What the game already gives us (the RE facts the design stands on)

- A season IS the league file set: CLASSIC.MAJ + 26 .V20 + SYSTEM + CONTROL. There is no separate season save; SAVE
  SEASON just builds a new league set from the simulated stats (B8).
- V20 team file: 80 records x 143 B. Records 0..39 = roster half (ratings, DU byte aged daily by MANAGE), 40..79 =
  season stat half (BACK accumulates every stat there at the same field offsets).
- Start New Season today: zeroes stat bytes in 40..79 (keeps name/age/year/exp/ratings), zeroes DU/W-L/streak/
  rotation, rewrites the schedule from the .SCH template, day back to 7. Records 0..39 are untouched. Age never
  advances in stock. Nothing accumulates across seasons. That is the whole dynasty gap.
- Stats -> ratings: all 9 UTIL formulas replicated at 99.7-100% (tools/ratings.py), plus the salary formula. The game
  can already compute ratings from stats; progression can reuse it directly.
- DRAFT.EXE exists with a GM profile (7 weights, presets in DRAFT ds:10e6) and writes picks into team files
  (DRAFT 1000:5589 record copy). Rookie generation machinery: TBD-B9.
- Program loop: TONY2.BAT loops PLAY + CONTROL; CONTROL.EXE FUN_1228_0007 reads the 9 B CONTROL file and dispatches
  the next program (ids 1..7). Adding a program id is a small patch: TBD-B9 confirms the dispatch table.
- Screens are data: SCREENS/*.SCR + per-screen .PAL + text page files via load_page_file_by_id, all decoded and
  renderable (tools/assets.py, 263 PNGs). New screens can be composed in the game's own style.
- Headroom (free conventional memory per program, code caves, .OVL structure): TBD-B9.

## Design

### 1. Season rollover (the core)

Insert one new step between "season over" (MAJ+0x20a == 0xf3) and the Start New Season zeroing, so the league set
itself remains the dynasty state. Preferred shape: a patch inside MAIN's Start New Season path right after the YES/NO
warning, calling new rollover code; fallback: a new DYNASTY program chained via the CONTROL dispatch, triggered when
it sees 0xf3. Choose after TBD-B9 (memory numbers decide: rollover needs room for the ratings recompute + file IO;
a standalone program has the most room, an in-MAIN patch reuses all loaders for free).

Rollover does, in order:
1. Career merge: add each 40..79 season stat into the player's career totals (see storage below), with saturation.
2. Aging: age+1 (byte 20), year+1 (byte 21), exp+1 if games > 0 (byte 22).
3. Progression: target = ratings_from_stats(last season) using the existing formulas (tools/ratings.py ports back
   unchanged); new = old + k(age) x (target - old), k ~ 0.5 at 21-24 declining to 0 at 28, negative to -0.3 by 35+.
   Pitchers from ER/BF/SO rates. Clamp with ratings.py's rules.
4. Retirement: retire if age >= 41, or age >= 36 and random < (age-35)*8%, or endurance+arm both < 3. Retired
   players are removed from the V20 and archived to history.
5. Rookies: generate the new class with the DRAFT generator (TBD-B9), fill rosters back to 40, run the existing
   draft for assignment.
6. History: append the season record (champion from MAJ+0x3d3 playoff field, standings, award winners computed from
   the season half) to the history file; then the stock zeroing runs as today.

### 2. Career stats storage

Primary: the 0..39 stat fields become the career half (they exist in the record today and are shown by the existing
screens, so career stats appear in-game for free). Rollover changes Start New Season from "zero 40..79" to
"saturating-add 40..79 into 0..39, then zero 40..79". Widths: season fields are u8/u16 sized; career AB/H/IP stay
under u16 for any realistic career, HR/RBI u8 overflow, so anything that can overflow also lives in the history file
and the in-record byte saturates.

Overflow + history: one new league-level file, HISTORY.DAT (name ours to avoid any stock collision), containing per
season: champion, standings snapshot, award winners; and per player id (import_id u16 + name): career totals in u32,
retirement age, HoF flag. The game's own patched code reads and writes it; no sidecar process, file stays inside the
install. This is the same pattern as the game's own ALLTIME.BOX.

### 3. Rookies and the draft

Reuse DRAFT as-is for assignment (it already writes picks into team files). Rollover only refreshes the pool with
the game's own generator (TBD-B9: name tables, rating generation, age/year assignment) and sets the GM profile as
today. No new draft UI.

### 4. Hall of Fame, career leaders, history screens

One new "DYNASTY" menu on the MAIN menu (menu string table + dispatch patch), with:
- SEASON HISTORY: list of past seasons (year, champion, awards); enter for standings.
- HALL OF FAME: retired players meeting thresholds (formula-voted, no narrative), career line + seasons.
- CAREER LEADERS: top-10 tables per category from HISTORY.DAT, in the STATISTICAL LEADERS screen style.
Screens reuse the game's own primitives (font, box draw, page files), per the UI style rules. Where they live
(patched UTIL vs the DYNASTY program) is decided by TBD-B9 headroom.

### 5. What we deliberately do not do

- No external companion program, no sidecar files outside the install, no changes to /mnt/nvme/tlrb2/c or pristine
  (work/ only until shipped).
- No new schedule logic: the stock .SCH templates and 162-game season are kept.
- No in-season progression (stock behavior kept; progression happens at rollover only).
- No stat field width changes inside .V20 (the 11735 B layout is fixed); saturation + HISTORY.DAT absorb overflow.

## Phasing (each phase gated by rig verification before the next)

- P0: pick the code home from TBD-B9 numbers; write the patch skeleton with assert-original-bytes + revert.
- P1: rollover pipeline (merge, aging, progression, retirement). Gate: play two back-to-back seasons in the rig,
  diff every V20 against a tools/ratings.py prediction of the progression; byte-exact agreement on the merge.
- P2: rookies + draft. Gate: a dynasty league survives 5 seasons with full 40-man rosters, ages advancing, no
  crashes, salary formulas still sane.
- P3: HISTORY.DAT + the three screens. Gate: Playwright-equivalent rig screenshots compared against the page files;
  values match the file.
- P4: awards, All-Star continuity, polish.

## Open questions for the review

1. Code home: in-MAIN patch vs a chained DYNASTY program (decide on TBD-B9 numbers; my default is the chained
   program if it has more than ~64 KB headroom, else the MAIN patch).
2. Career half in 0..39 changes what existing screens show. Acceptable? The alternative (history file only) keeps
   stock screens untouched but loses free in-game visibility.
3. Retirement/progression constants (the curves above are first-pass; you may want era-appropriate values for a
   19th-century league).
4. HoF thresholds and whether awards matter to you or champion + leaders are enough.
