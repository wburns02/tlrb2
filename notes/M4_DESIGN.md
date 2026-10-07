# M4 design: dynasty / multi-season mode (for Will's review, not built)

Status: DRAFT 2026-10-07; Lane B9 prerequisites closed 2026-10-07 (commit bef14b9/6bc59e7) and folded in below.
Everything is grounded in the completed M1-M3 RE (FORMATS.md is the source for every offset cited here). The 16-bit
rollover core (tools/m4/blob/) is written and byte-exact against tools/m4/rollover.py under the unicorn harness
(tools/m4/test_blob_unicorn.py: merge+aging, progression, retirement vectors, rng agreement, all 40 players).

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
  (DRAFT 1000:5589 record copy). There is NO procedural rookie generator in the shipped code: the draft pool is the
  league's own V20 players re-categorised (DRAFT 2000:e964). A rookie class must be assembled from the decoded
  pieces (blank-record init, portrait picker, ratings/salary formulas).
- Program loop: TONY2.BAT loops PLAY + CONTROL; CONTROL.EXE FUN_1228_0007 reads the 9 B CONTROL file and dispatches
  the next program (ids 1..7, bounds cmp bx,5 at 0x1228:0xCF, jump table 0x1228:0x127; id-8 patch recipe in LANE_B.md).
- Screens are data: SCREENS/*.SCR + per-screen .PAL + text page files via load_page_file_by_id, all decoded and
  renderable (tools/assets.py, 263 PNGs). New screens can be composed in the game's own style.
- Headroom (Lane B9, MCB walks of 640 KB dumps in snaps/m4_dumps/): free conventional memory is always one
  contiguous block: PLAY 443.7 KiB, MAIN 321.7 idle / 233.7 menus, MANAGE 388.7, UTIL 277.7/254.7, DRAFT 188.7,
  BACK 106.7 mid-sim, BB 94.7 mid-game, CONTROL 592.7. Code caves: MAIN up to 9.9 KB, PLAY 4.5 KB, CONTROL 300 B,
  UTIL/DRAFT ~2.1 KB, BB 64+133 B, BACK/MANAGE none.

## Design

### 1. Season rollover (the core)

Insert one new step between "season over" (MAJ+0x20a == 0xf3) and the Start New Season zeroing, so the league set
itself remains the dynasty state.

RESOLVED (2026-10-07, evidence over the draft's TBD): the rollover lives in a STANDALONE DYNASTY.EXE (16-bit asm,
int 21h file IO only), run from TONY2.BAT before `control` hands off to MAIN. The BAT loop (`if errorlevel 1..7`)
already dispatches by exit code; DYNASTY is invoked at the top of the loop, checks CLASSIC.MAJ day == 0xf3 and its
own done-marker in HISTORY.DAT, performs the rollover if due, and exits 0 so the stock loop proceeds untouched.
Zero bytes of game code change for P1/P2; no CONTROL dispatch knowledge needed; no conventional-memory fight with
the game (DYNASTY runs between programs, where DOS has maximal free memory). The in-MAIN patch from the draft is
demoted to fallback (only if int 21h path/CF handling proves unable to see the league dir, which the rig will
disprove or confirm in P0). Rollover ordering is safe: the stock Start New Season zeroing of 40..79 runs later,
whenever the user confirms it, and is exactly what we want AFTER the merge/archive. Rollover is idempotent via the
HISTORY.DAT season marker, so "user does not start a new season immediately" is harmless.

Rollover does, in order:
1. Career merge: add each 40..79 season stat into the player's career totals (see storage below), with saturation.
2. Aging: age+1 (byte 20), year+1 (byte 21), exp+1 if games > 0 (byte 22).
3. Progression: target = ratings_from_stats(last season) using the existing formulas (tools/ratings.py ports back
   unchanged); new = old + k(age) x (target - old), k ~ 0.5 at 21-24 declining to 0 at 28, negative to -0.3 by 35+.
   Pitchers from ER/BF/SO rates. Clamp with ratings.py's rules.
4. Retirement: retire if age >= 41, or age >= 36 and random < (age-35)*8%, or endurance+arm both < 3. Retired
   players are removed from the V20 and archived to history.
5. Rookies: generate the new class (assembled from decoded DRAFT/UTIL pieces, see section 3; no stock generator
   exists), fill rosters back to 40, run the existing draft for assignment.
6. History: append the season record (champion from MAJ+0x3d3 playoff field, standings, award winners computed from
   the season half) to the history file; then the stock zeroing runs as today.

### 2. Career stats storage

Primary: the 0..39 stat fields become the career half (they exist in the record today and are shown by the existing
screens, so career stats appear in-game for free). Rollover changes Start New Season from "zero 40..79" to
"saturating-add 40..79 into 0..39, then zero 40..79". Widths: season fields are u8/u16 sized; career AB/H/IP stay
under u16 for any realistic career, HR/RBI u8 overflow, so anything that can overflow also lives in the history file
and the in-record byte saturates.

One nuance from Lane B9: the STATISTICAL LEADERS screen reads records 0..39 row-for-row, and in the shipped leagues
half 0 holds single best-season lines, not career sums. Pointing half 0 at career totals therefore turns the leaders
screen into a CAREER leaders screen automatically, which is what a dynasty wants; the loss is per-season best lines,
which HISTORY.DAT keeps instead.

Overflow + history: one new league-level file, HISTORY.DAT (name ours to avoid any stock collision), containing per
season: champion, standings snapshot, award winners; and per player id (import_id u16 + name): career totals in u32,
retirement age, HoF flag. The game's own patched code reads and writes it; no sidecar process, file stays inside the
install. This is the same pattern as the game's own ALLTIME.BOX.

### 3. Rookies and the draft

Reuse DRAFT as-is for assignment (it already writes picks into team files; the on-disk team files stay authoritative,
and Lane B9 confirmed the twin-copy helper (names/age verbatim, year+1, exp+1) fires only at league/team build and
post-draft, never mid-season). Rollover must BUILD the rookie class itself: there is no procedural generator in the
shipped code, so assemble one from the decoded pieces (blank-record init, portrait picker, ratings formulas, salary
formula), write the rookies into the vacated records 0..39 of each V20, and let stock DRAFT assign them. No new
draft UI.

### 4. Hall of Fame, career leaders, history screens

One new DYNASTY menu entry, reached the same low-risk way: DYNASTY.EXE doubles as the screen program (invoked from
the BAT with an argument, e.g. `dynasty HOF`), so NO MAIN menu patch either. It renders in VGA mode 13h using the
game's own decoded font/palette assets (tools/assets.py already renders all 263 screens; the same data drives the
asm renderer). Screens:
- SEASON HISTORY: list of past seasons (year, champion, awards); enter for standings.
- HALL OF FAME: retired players meeting thresholds (formula-voted, no narrative), career line + seasons.
- CAREER LEADERS: top-10 tables per category from HISTORY.DAT, in the STATISTICAL LEADERS screen style.
Falls back to a MAIN menu patch only if key-wait/UX in the standalone renderer proves worse than the patch risk
(decided in P3, rig-tested).

### 5. What we deliberately do not do

- No external companion program, no sidecar files outside the install, no changes to /mnt/nvme/tlrb2/c or pristine
  (work/ only until shipped).
- No new schedule logic: the stock .SCH templates and 162-game season are kept.
- No in-season progression (stock behavior kept; progression happens at rollover only).
- No stat field width changes inside .V20 (the 11735 B layout is fixed); saturation + HISTORY.DAT absorb overflow.

## Status (2026-10-07)

- P1 DONE and rig-verified: DYNASTY.EXE (tools/m4/blob/, built by build_dynasty.py) rolls the real m3_end season
  byte-exact against tools/m4/rollover.py (all 28 V20 files + rng word 17254), second run is a no-op, and the stock
  Start New Season then runs cleanly on the rolled league (day 0xf3 -> 7, season half zeroed, career half kept except
  the 10 injured DU byte-24 resets). Gate pinned by tools/m4/test_blob_realdata.py (1120 player pairs in unicorn).
- Season-2 playability CLOSED (2026-10-07): the rolled league played a full season in the rig with All-Star and
  injuries on. All-Star game ran (AL 3, NL 1, July 16, correct rosters), regular season completed (OCT 6,
  Chicago A 120-42), playoffs and World Series completed (PHILADELPHIA over CLE 4-2), QUIT flushed the MAJ day
  byte to 0xf3. No crashes at any break point. Snapshot: snaps/season2_end/.
- Season-3 rollover gate GREEN (2026-10-07): the real played season-2 league rolled by DYNASTY.EXE is byte-exact
  against tools/m4/rollover.py on all 28 V20s (work/season3_gate/, ref roll = 16 real retirements; retirement is
  rng-driven, so byte agreement through every draw proves the 16-bit xorshift matched the Python Rng the whole
  way). Second DYNASTY run is a no-op (flag 1, zero writes).
- P2 Python reference layer DONE and gated (16/16 tests): tools/m4/rookies.py (rookie-class generator: name pool
  harvested from real records, portrait 0..29, age 18..23, salary = ratings.salary clamped 109..9999, all rating
  nibbles 1..15) and tools/m4/team_fill.py (post-rollover fill: priority ladder P>=8, C>=2, IF>=1 each, OF>=4,
  rest DH; refuses half-vacant slots; zeroing limited to PROVEN season-stat offsets, bytes 59..70 are live
  per-half nibbles and are NOT zeroed).

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

1. Code home: RESOLVED by the B9 numbers: the standalone DYNASTY.EXE path needs no game-code patch at all for
   P1/P2, and CONTROL has 592.7 KiB free if a chained-program dispatch (id 8) is ever preferred. MAIN caves
   (9.9 KB) remain the fallback only.
2. Career half in 0..39 changes what existing screens show (leaders screen becomes career leaders, see section 2).
   Acceptable? The alternative (history file only) keeps stock screens untouched but loses free in-game visibility.
3. Retirement/progression constants (the curves above are first-pass; you may want era-appropriate values for a
   19th-century league).
4. HoF thresholds and whether awards matter to you or champion + leaders are enough.
5. Roster turnover (found 2026-10-07, measured on the real CLASSIC league with the C1 reference): a normal seed
   retires 6 to 19 players per season out of ~1100 on the 28 real rosters, about 1%. Real MLB turns over far more,
   mostly through washouts (young players released), not old-age retirement. Under C1 a weak 26-year-old keeps his
   roster spot until 36, so rookies enter only as veterans age out. Option: a release rule (for example age 29+ and
   every key rating below a floor, or N straight seasons under a games threshold) that frees the slot without
   counting as a retirement for the Hall of Fame. Not built; needs your call. (Seasons 1 to 3 of the test dynasty
   looked like heavy turnover only because they rolled at seed 0, a degenerate rng that retired 192 a season;
   the T4a seed rule removes that.)

## Answers (Will, 2026-10-07)

- Q2: season leaders and career leaders are two separate screens. P1 stays as built (Will, 2026-10-07: do not
  redo it). Career totals are already recorded by the P1 merge into half 0; the second screen is a P3 display task
  in DYNASTY, which also reads HISTORY.DAT u32 totals where half 0 saturates (u8 HR/RBI).
- Q3: realistic, but older players get a better chance to keep playing well. No 42-year-old Babe Ruth hitting like
  he is 27, but a star at 35-37 should still be a useful regular. Direction: push the progression plateau later
  (k ~ 0 through ~31 instead of 28), make the decline gentler (reach -0.3 around 38+, not 35+), scale decline and
  retirement odds by quality (elite players decline slower and retire later), and lower the age 36+ retirement
  probability. Validate the curves against real aging data (Lahman) before locking constants.
- Q4: Hall of Fame uses general classic thresholds (3000 H, 500 HR, 300 W, 3000 K, .300 over a long career, etc.)
  plus modern value stats: a WAR-style number (and a JAWS-style peak + career blend). Will specifically wants the
  case of a player whose WAR was huge but whose counting stats only looked very good (Lou Whitaker / Bobby Grich
  type) to get in. No new recording is needed for a first version: fielding uses
  what the V20 already holds (games, errors from the season accumulators, range/arm ratings; note real PO/A do not
  exist, import overwrites them with position averages), and a team park factor comes from the per-game home/away
  runs already stored in the MAJ results cells, computed at rollover. True per-player PO/A recording is in IDEAS.md.
  Awards: TBD.

- Q5 roster turnover (Will, 2026-10-07; research and pipeline in notes/M4_ROSTER.md):
  1. Your own team is left to the manager: the AI never releases, signs, or trades for a managed team.
  2. Era rules: both, as an option. Real calendar (reserve clause before 1976, free agency for 6+ years of service
     from 1976) or one rule set throughout.
  3. Trades: yes, in v1 (AI to AI).
  4. Money: ignored for now (no payroll, salary byte untouched).
  5. Turnover target: real life for now (1970-90 MLB rates, Lahman table in M4_ROSTER.md).

## Engineering decisions (brain, 2026-10-07)

- HISTORY.DAT writer runs as a second DOS program, HISTWR.EXE, written in C (OpenWatcom v2, large model, toolchain
  at /mnt/nvme/tools/openwatcom). Why: the player table passes 64 KB in the first season (1100+ x 160 B) and the
  C3 math needs signed 32/64-bit products and divisions. In 16-bit asm that is far segments plus hand-rolled long
  division; in C it is plain code, and the same source builds on the host with gcc so the Python reference can pin
  it byte for byte. DYNASTY.EXE (asm) keeps the roll and only adds the seed rule, an in-place header write, and a
  RETIRED.DAT list for HISTWR. Contract C5.
- Crash window: the BAT runs `dynasty` then `if errorlevel 1 histwr`. If DOSBox is killed between the two, that
  season's history is lost (the roll itself is kept). Accepted: the window is one program start, and a pending
  flag would need the pre-roll snapshot kept across launches, which the BAT's DYNSNAP copy overwrites.
- Reference fixes found while porting: mark_retired now skips ALLSTAR files (their records are copies of real
  players, so an All-Star copy retiring would have retired the real player), and seasons past 64 skip the
  season-table write instead of overwriting the first player entries.
