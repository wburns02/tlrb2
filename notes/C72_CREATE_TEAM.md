# C72. Create a team: design and locked contract (2026-10-15)

Status: design only. Nothing here is built. Section "Contract" is locked: the build tasks
(C72a to C72d) paste their slice of it verbatim and may not change it without a new
dated revision of this file.

## Goal

From inside the game (DYNASTY > CREATE A PLAYER's CREATE.EXE, a new first screen), the
user adds one new franchise to the current league: name, abbreviation, colours, a park, a
full 40-man roster. The next season (or the current one, if no game has been played yet)
schedules and plays it like any other team. No outside tool run is needed, per Will's
"avoid building outside the game" rule.

## What we already own

- MAJ team slots: per league block (S = 0x21d AL, 0x758c NL) slot = division*8 + i. Stock
  uses i = 0..6, so slot 7 (East) is free in each league; slot 15 is the hidden ALL STARS
  entry in the 2-division layout and is NOT free (FORMATS.md, C46 notes).
- Expansion writers: tools/lahman/build_season.py add_expansion (1993, NL slots 6 and 14)
  and add_expansion_1998 (NL slots 7 and 15). Both copy a neighbouring V20, rename the
  header (+0 name, +16 abbr), write the MAJ entry (name, abbr, stem: the UTIL NEW TEAM
  fields) and bump the division count at S + 0x298 + d and 0x20e + 3 + d.
- Rosters: m4/team_fill.py fill_image(image, season_year, rng, rookie_gen) fills every
  vacant slot from the RookieGen at the league's grade; rosters.repair keeps the header
  lists (staff, lineup, defence, bench, reserve) valid. Both have C ports (rosters_c,
  create_c).
- Faces 30..96, ratings.py (9 formulas + salary), parkgen and the stadium reference.
- C71 (2026-10-15, rig): the engine packs a league's teams into 16 indexes
  (teamids.slot_to_engine). 3 divisions: division d slot i maps to index 5*d + i, so a division
  holds at most 5 teams and index 15 is the hidden ALL STARS entry. 2 divisions: index = slot,
  slot 15 is ALL STARS, so division 0 can hold 8 (slots 0..7) and division 1 at most 7. A league
  holds at most 15 teams in either layout. The Lahman 1998 build (NL 5/5/6) put HOU at index 15
  and hung at APRIL 1; the 1997 control (5/4/5) played a full season.

## Contract (locked)

1. Slot. (revised 2026-10-15 after C71) The division capacity is 5 in a 3-division league
   (0x20d = 3) and 8 for division 0, 7 for division 1 in a 2-division league. The new team takes
   slot d*8 + count(d) for the first division d, AL before NL and lower d first, whose count is
   under its capacity. None: the screen shows LEAGUE FULL and writes nothing. Slot 15 is never
   used.
2. Stem. The first of clasXlYN (X = a or n by league, Y = e for division 0, w otherwise,
   N = 1..9) whose <league dir>/<STEM upper>.V20 does not exist and which no MAJ entry uses.
   None: LEAGUE FULL.
3. Header. The V20 is a copy of the division's slot 0 team file with: +0 name (16 B, upper
   case A-Z, space, '.', NUL padded, 1..15 chars), +16 abbr (2..3 chars A-Z), the stadium
   byte (+19) and the colour bytes set from the form (the colour offsets are not decoded
   yet: C72a starts with a rig diff of UTIL Team Colors and pins them here in a dated
   revision before any code), every roster record (slots 0..79)
   zeroed, then the header lists rebuilt by rosters.repair on the filled roster.
4. Roster. fill_image(image, season_year, Rng(seed), RookieGen) over the empty image fills
   all 40 roster slots (16 pitchers, 24 batters by team_fill's priority order). seed is the
   CREATE session seed (the same LCG as C37), so a run is reproducible.
5. MAJ. Name (16 B), abbr and stem written to the slot's entry exactly as add_expansion
   does; the division count for that division +1. Every other MAJ byte stays as it was.
6. TEAMID.DAT. When the league has one, the new team gets the next unused stable id
   (0..31; ids are never reused, team id 0 is valid, never a sentinel) appended per the
   teamids format. HISTORY.DAT is not touched: the team enters history from its first
   recorded season.
7. Timing. Allowed only when the current season has no game played (MAJ day = 0) or from
   the offseason before launch. Otherwise the screen shows SEASON UNDER WAY and writes nothing.
8. Write order. V20 first, then TEAMID.DAT, then the MAJ last (the MAJ is what makes the
   team visible), so a crash leaves at most an unreferenced V20.
9. Both ports. create.py is the reference; create_c matches it byte for byte (file parity
   tests over the V20, MAJ and TEAMID.DAT bytes). C89, no new array over 2 KB.

## Build plan (each a normal tiered-build-loop task with its own holdout)

v1 is REPLACE A TEAM (open question 1): the user picks the team to replace, the slot and stem
stay, TEAMID.DAT gives the slot a new stable id (the old franchise's history stays under its old
id), and the replaced team's players go to the free-agent pool (C69's release path) before the
new roster is filled.

- C72a: create_team(league_dir, form, seed) in Python (rules 1 to 8), no UI, plus tests.
- C72b: the C port of C72a with file parity.
- C72c: the CREATE.EXE NEW TEAM screen: name and abbr typing (C10's name entry), colour
  pair picker over the palette, stadium cycle, CREATE, then the existing player screens on
  the new team.
- C72d: rig proof. A fresh league plus one created team plays a full season and its
  playoffs on the dedicated rig install, roll check clean.

## Open questions (for Will)

1. Answered by C71 (rig, 2026-10-15): GENERATED needs an even team count per league and the
   engine caps a division (5 with 3 divisions; 8 and 7 with 2) and a league (15). A stock league
   (14 a league) has one free place a league at most, so ADDING one team always leaves a league
   odd and unschedulable, and adding a pair to one league does not fit. Adding is blocked until
   the GENERATED even-count check is reverse engineered (C71 follow-up). Recommendation, adopted
   for v1 below: REPLACE A TEAM. The created franchise takes over an existing slot (its V20 is
   rewritten per rules 3 and 4, the MAJ entry renamed per rule 5, the stem kept), so counts never
   change and it schedules today. Rules 1, 2 and 7 then apply only to the later ADD mode.
2. Logo and uniform drawing are not decoded. A created team shows the default logo. Fine
   for v1?
3. Expansion draft from the other 27 teams' unprotected players, instead of an all-rookie
   roster? It is a separate later task either way (needs a protect-list UI).
