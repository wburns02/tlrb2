# M4 contract (locked 2026-10-07; change only as its own reviewed step)

Integer conventions for every section: signed division truncates toward zero (x86 idiv); signed `>>` is an
arithmetic shift; all intermediate math fits in signed 32 bits (CPU 386 regs in asm). "draw()" is the existing
xorshift16 `Rng.draw()` in tools/m4/rollover.py, and `d = draw() & 0xff`.

## C1. Aging, progression, retirement (replaces the P1 K table and retirement rule)

Will, 2026-10-07: never force retirement; realistic, but older players get a better chance to keep playing well.

Quality tier, computed once per player from the ROSTER half (record i) ratings BEFORE any change this rollover:
- pitcher (pos1 & 15 == 0): qs = control + velocity + endurance; tier = 0 if qs < 23, 1 if qs < 26, 2 if qs < 28, else 3
- batter: qs = power + hit_run + speed + range; tier = 0 if qs < 32, 1 if qs < 36, 2 if qs < 39, else 3
(thresholds = p50/p75/p90 of the shipped CLASSIC league.)

Per player, in this order (steps 1 and 2 are unchanged from P1):
1. career merge (unchanged). 2. aging (unchanged); age2 = the aged age.
3a. evidence (only if progression flag AND season games > 0): for each rating in the rating order below,
    new = old + ((96 * (target - old) + 128) >> 8), clamp 1..15. target = ratings formula on the season record (as P1).
3b. drift (only if progression flag; regardless of games): for each rating in the rating order below, ONE draw always:
    d = draw() & 0xff; v = current value; cap = 10 for endurance, else 12.
    - age2 <= 26: g = 90 if age2 <= 22, 64 if age2 <= 24, else 32. If d < g and v < cap: v += 1.
    - 27 <= age2 <= 31: no change (the draw is still consumed).
    - age2 >= 32: base = 40 (32..33), 64 (34..35), 96 (36..37), 128 (38..39), 160 (40+);
      mult = [4, 4, 3, 2][tier]; p = (base * mult) >> 2. If d < p and v > 1: v -= 1.
4. retirement (only if retirement flag). No forced retirement of any kind (the age >= 41 rule and the pitcher
   endurance/arm rule are removed).
    - age2 < 33: not retired, NO draw.
    - age2 >= 33: base = 10 (33..34), 20 (35..36), 36 (37..38), 56 (39..40), 80 (41..42), 110 (43+);
      mult = [4, 4, 3, 2][tier]; p = (base * mult) >> 2; if season games == 0: p = min(255, p * 2).
      d = draw() & 0xff; retired iff d < p.

Rating order (for evidence, drift and RNG draw order):
- batters: power, bunt, hit_run, speed, range, arm
- pitchers: control, velocity, endurance
Draw order per player: the drift draws (6 or 3) then the retirement draw. The RNG stream continues across players
and teams exactly as in P1 (sorted *.V20 order, records 0..39).

## C1b. Development trait (2026-10-07; Will approved the idea; in DYNASTY since the asm port: rollover blob CX bit2, DYNASTY passes CX = 7)

Record byte 142 (both halves) = dev grade 1..5 (1 bust, 2 slow, 3 normal, 4 good, 5 boom); 0 = not yet assigned
(every stock record). FORMATS: bytes 141-142 are the UTIL import id, read only by the Utilities import path when a
user imports stat lines, never by DYNASTY, PLAY or the season sim (C6 already uses 141 for pool years).
- Assignment, in C1 per player right after step 2 (aging), only if the progression flag is set and byte 142 == 0:
  d = draw() & 0xff; grade = 1 if d < 26, 2 if d < 77, 3 if d < 179, 4 if d < 230, else 5 (10/20/40/20/10 %).
  Written to both halves. Players with a grade draw nothing here.
- 3b growth (age2 <= 26): g = (g * GM[grade]) >> 2, GM = [-, 1, 3, 4, 5, 7] (x0.25 .. x1.75).
- 3b decline (age2 >= 32): p = (p * DM[grade]) >> 2 after the tier multiplier, DM = [-, 6, 5, 4, 3, 2], capped 255.
- Retirement (step 4) is unchanged: the tier already reflects what the trait produced.
The RNG stream gains one draw per ungraded player at its first roll (C1 references and parity fixtures update).
ROSTERS potential (C6 G table) reads the scaled g so scouts value boom prospects (hidden from the player, visible to
the AI the way a scouting report would be).

## C2. HISTORY.DAT v1 (league dir, TEAMS\CLASSIC\HISTORY.DAT), little endian

Header, 32 B:
- 0 u8 done flag (same meaning as P1), 1 u16 rng word (same as P1), 3 u8 version = 1
  (a legacy 4-byte P1 file has no byte 3 or 0 there: upgrade in place keeping bytes 0..2)
- 4 u16 seasons recorded, 6 u16 player entries, 8 u16 start seed of the last roll, 10..31 zero
  (amended 2026-10-07) Seed rule at roll time: rng word = bytes 1..2; if the file is missing OR the word is 0, the
  word = BIOS tick count low word (int 1Ah, DX), and 1 if that is 0 (xorshift16 seeded with 0 stays 0 forever: every
  draw 0, every young player +1 on every rating, every age >= 33 player retires). Bytes 8..9 = the word in effect
  at the START of the roll, so the gate replays the roll with that seed. Bytes 1..2 = the word after the roll.
Season table at offset 32: 64 entries x 128 B (8192 B). Entry for season n (1-based) at 32 + (n-1)*128:
- 0 u16 season_no; 2 u8 champion id; 3 u8 runner-up id (league-global ids, 0xff = unknown)
- 4 8 B champion team stem, 12 8 B runner-up stem (latin-1, NUL padded)
- 20 u8 al_pennant id, 21 u8 nl_pennant id, 22..23 zero
- 24 32 x (u8 W, u8 L) indexed by league-global id 0..31 (NL = slot + 16); unused ids 0,0
  (amended 2026-10-07: CLASSIC NL uses slots 8..13 = ids 24..29, so 28 entries were too few)
- 88..127 zero (reserved for awards, P4)
Champion decode (amended 2026-10-08, two samples: season2_end "PHILADELPHIA over CLE 4-2" and the offseason e2e
"BOSTON over LA 4-2", ring screen): AL block S=0x21d, NL block S=0x758c. The AL block holds both series as
(team0, team1) plus each side's wins: LCS teams S+0x3d7/0x3d8, wins S+0x3df/0x3e0; WS teams S+0x3d9 (AL pennant) and
S+0x3da (NL pennant), wins S+0x3e1/0x3e2. WS winner = the WS team with more wins, a tie is unknown. al_pennant = AL
S+0x3d9; nl_pennant = NL S+0x3d9; runner-up = the pennant winner that is not the WS winner. 0xff anywhere means
unknown; any id byte >= 32 is read as 0xff (amended 2026-10-07). The pre-2026-10-08 rule (WS winner = AL S+0x3da)
always named the NL pennant winner: entries written before the fix show the NL team as champion in seasons the AL won.
Player table at offset 8224: entries x 160 B. Entry:
- 0 20 B name = raw V20 record bytes 0..19 (last 12, first 8)
- 20 u16 birth = 1000 + season_no - age (age = roster age BEFORE aging, season_no of first sighting)
- 22 u8 status: 1 active, 2 retired, 3 Hall of Fame
- 23 u8 age at last season; 24 u16 first season; 26 u16 last season; 28 u16 seasons played (season games > 0)
- 30 u8 pos1 of last season (roster half pos1 & 15); 31 u8 pitcher flag (pos1 == 0)
- 32 25 x u32 career totals, in this order: G, AB, H, 2B, 3B, HR, R, RBI, BB, SO, SB, CS, E, W, L, SV, GS, CG, SHO,
  OUTS, ER, PH, PBB, PSO, PHR   (L+R columns summed; E = e1 + e2; OUTS = (ip10 // 10) * 3 + ip10 % 10)
- 132 s16 career WAR10; 134 7 x s16 top-7 season WAR10, sorted descending, unused = -32768;
  148 s16 JAWS10 = (career + sum of the used top-7 entries) / 2; 150 u16 HoF season (0 none); 152..159 zero
Identity: same entry iff name bytes AND birth match (birth recomputed per sighting as 1000 + season_no - age).
Careers count dynasty seasons only (entries start at zero; the shipped half-0 lines are NOT imported).

Team mapping (amended 2026-10-07): a V20 file's league-global id = the MAJ slot whose 8 B stem equals the file's
basename stem, compared case-insensitively (AL slot s -> id s, NL slot s -> id s + 16). Files with no match
(ALLSTAR1/2.V20, whose MAJ stems start with NUL) are skipped by every history step: no league totals, no player
entries. The P1 rollover still processes every *.V20 (RNG stream unchanged).

Update order at rollover (Python reference `history.record_season(league_dir, hist_path, season_no, retirees)`),
run BEFORE the P1 rollover mutates anything, then `history.mark_retired(...)` after it:
1. read MAJ standings, champion; write the season entry.
2. league pass over every active record i in 0..39 of every V20 (sorted order) using the SEASON half (i+40) stats
   and roster-half bio/ratings: accumulate league totals for C3.
3. per player: find or append the entry, add season stats, set status 1, ages, seasons, pos; season WAR10 per C3;
   career WAR10 += season; update top-7 and JAWS10.
4. after rollover: retirees get status 2, then the HoF test (C3). status 3 + HoF season if it passes.
   (amended 2026-10-07) The rollover zeroes a retiree's name byte 0, so the retiree identity (name bytes, birth)
   is read from the PRE-rollover league (the same records step 3 read), birth = 1000 + season_no - pre-roll age.
   HoF season = season_no, the season just completed. version byte 3 is written as 1 by every record_season.

## C3. WAR and Hall of Fame (integer, per season, the season half stats)

Batters (pos1 != 0). ab, h, d(2B), t(3B), hr, bb summed L+R; sb, cs, runs; g = season games; s1 = h - d - t - hr; pa = ab + bb.
- lw100 = 47*s1 + 78*d + 109*t + 140*hr + 33*bb + 20*sb - 41*cs - 27*(ab - h)
- league: L_lw = sum lw100, L_pa = sum pa, L_runs = sum runs, over batters with pa > 0
- bat100 = lw100 - (L_lw * pa) / L_pa   (amended 2026-10-07: batters with pa == 0 are NOT zeroed, they still get
  lw100 (sb/cs), posadj100 and fld100; if L_pa == 0 the L_lw term and park100 are 0)
- park: pf1000 per team = 1000 * ((home_rs + home_ra) * away_g) / ((away_rs + away_ra) * home_g) from the MAJ
  per-game runs cells of played games (both halves of doubleheaders), clamp 900..1100; 1000 if any term is 0 or the
  team cannot be mapped. park100 = ((((pf1000 - 1000) * L_runs) / 20) * pa) / L_pa  (each division rounds toward
  zero, evaluated left to right; this form keeps every product under 2^31); bat100 -= park100
- repl100 = (2000 * pa) / 600
- pos100 per 162 G by pos1 code (v20 POS order): C 1250, 1B -1250, 2B 300, 3B 250, SS 750, LF -750, CF 250,
  RF -750, DH -1750, anything else 0; posadj100 = (pos100 * g) / 162
- fld100 = (((range - 6) * 150 + (arm - 6) * 50) * g) / 162
- war10 = (bat100 + repl100 + posadj100 + fld100) / 100   (bat100 already has park100 subtracted)
Pitchers (pos1 == 0): outs as in C2, er.
- league: L_er, L_outs over pitchers with outs > 0
- pit100 = (L_er * 120 * outs) / L_outs - er * 100; war10 = pit100 / 100 (0 when L_outs == 0)
Hall of Fame (on retirement): seasons played >= 10 AND any of: H >= 3000, HR >= 500, (AB >= 5000 and
H * 1000 / AB >= 300), W >= 300, PSO >= 3000, SV >= 400, career WAR10 >= 600, JAWS10 >= 500.

## C4. Rookie variety (amends the P2 fill-path generator; added 2026-10-07)

The P2 WIP blob gave every rookie identical ratings. Rookies must vary and some must become stars through C1 growth.
- Names: our own pools (no names harvested from game data), 128 last names and 64 first names, ASCII, last <= 11 chars,
  first <= 7, stored as tables in rookie_fill.asm and in tools/m4/rookies.py (identical order). Index = d % 128 and
  d % 64 (d = draw() & 0xff for the first-name draw too).
  (amended 2026-10-07) Stored like the shipped data: mixed case ("Adams", "McCall", "Aaron"), NUL padded (last 12 B,
  first 8 B), never space padded or all caps. The asm table is generated from the Python list, never hand-kept.
- Per rookie draw order: last-name, first-name, age, throws, switch, portrait, exper, consist (as the WIP blob), then
  grade, then one draw per rating in the C1 rating order (batters 6, pitchers 3).
- grade: d = draw() & 0xff; grade = 0 if d < 154, 1 if d < 230, else 2 (60/30/10 %); bonus = [0, 2, 4][grade].
- rating value = 3 + (d % 5) + bonus with d = draw() & 0xff, then clamp 1..cap (cap = 10 for endurance, else 12).
  Ratings not in the C1 order keep the WIP blob's constants.
  (amended 2026-10-07) Off-role ratings are constants matching the shipped data's most common pattern, no draws:
  pitchers bat power 1, bunt 1, hit_run 1, speed 7, range 7, arm 7 (74 = 0x11, 75 lo 1, 29 hi 7, 94 = 0x77); every
  other rookie pitches control 1, velocity 3, endurance 1 (134 = 0x31, 135 hi 1). Written with the stat-line
  constants, before the rating draws, which touch other nibbles only.
- Everything else (stat lines, salary, portrait, season-twin copy) stays as the WIP blob defines it.
  (amended 2026-10-12, C11) The WIP stat-line constants stay in the blob, but ROSTERS replaces that placeholder
  line with the C11 ratings-implied line in the same roll, so no rookie starts a season with it.
  (amended 2026-10-08, F1) Portrait: face = d % n, u16@27 = face, byte 29 bit0 = grp[face]. (n, grp) default to
  30 and the stock UTIL DS:776e table (1 at 3, 4, 16, 18, 20, 21, 22, 25, 27: dark skin); the old `face >= 15` flag
  rule was wrong. When ANMS\PORTRAIT.ANM (count c) and ANMS\FACEGRP.DAT (length L, one flag byte per face, written
  by tools/faces.py append) both read and 30 <= L <= 981: n = min(L, c) if that is >= 30, grp = those bytes & 1;
  else the default. DYNASTY reads both files once at startup and patches the rookie blob header (word 2 = n,
  word 4 = table offset). Draw order and count are unchanged.

## C5. Runtime split for HISTORY.DAT (added 2026-10-07, T4)

Two DOS programs, run by the patched TONY2.BAT loop:
```
:start
copy TEAMS\CLASSIC\*.* C:\DYNSNAP > NUL
dynasty
if errorlevel 1 histwr
control
```
DYNASTY.EXE (asm, owns the roll and the HISTORY header bytes 0..2 and 8..9):
- Acts only when MAJ day = 0xf3 and HISTORY byte 0 != 1 (unchanged). Seed rule per C2: rng = bytes 1..2 when the file
  exists and is >= 3 B, else missing; missing or 0 -> int 1Ah AH=0, rng = DX, 1 if DX = 0. start = rng.
- After rolling every team: the HISTORY file keeps its length or grows, never shrinks. Missing -> created as 32 B of
  zero. Shorter than 32 B -> zero-extended to 32 B (existing bytes kept). Then byte 0 = 1, bytes 1..2 = rng after the
  roll, bytes 8..9 = start; no other byte is touched (version and counts belong to HISTWR).
- Day != 0xf3 with byte 0 != 0: byte 0 = 0 written in place, nothing else touched, length unchanged.
- C:\DYNSNAP\RETIRED.DAT, rewritten from scratch after every roll: u8 nteam, then nteam x (13 B DTA name, NUL padded,
  + 40 B flags, flag i = the rollover blob's AX for roster record i, 1 = retired this roll), teams in the roll's
  sorted order. A team that failed to open or read has all-zero flags.
- Exit code 1 when it rolled (including the no-V20 case that only writes the header), else 0.
HISTWR.EXE (C, OpenWatcom large model; the same source also builds on the host with gcc for parity tests):
- usage: HISTWR [PRE_DIR HIST_PATH RETIRED_PATH], defaults C:\DYNSNAP, TEAMS\CLASSIC\HISTORY.DAT,
  C:\DYNSNAP\RETIRED.DAT. season_no = HISTORY seasons recorded (bytes 4..5) + 1.
- Output: HIST_PATH byte-identical to Python `history.record_season(PRE_DIR, H, season_no)` followed by
  `history.mark_retired(H, PRE_DIR, retirees, season_no)`, retirees = {name: [i with flag 1]} from RETIRED.DAT.
- Never holds the whole player table in memory: streams old entries to a temp file beside HIST_PATH, then replaces it.
- Any error (missing PRE_DIR MAJ, unreadable file): HIST_PATH unchanged, exit 2. Success exit 0.
Reference fixes in the same amendment: mark_retired skips unmapped files (ALLSTAR copies of real players), and
seasons past 64 skip the season-table write (careers still update; the table would overlap the player table).

## C6. Roster management, ROSTERS (LOCKED 2026-10-07 by the R2 50-season validation, notes/M4_ROSTER.md section 7;
## design and research in notes/M4_ROSTER.md)

Runs after DYNASTY rolled and HISTWR recorded. HISTWR exits 0 and resets errorlevel, so the BAT block is
`dynasty` / `if errorlevel 1 goto rolled` / `goto ctl` / `:rolled` / `histwr` / `rosters` / `:ctl` / `control`
(amended 2026-10-07: the earlier `if errorlevel 1 rosters` after histwr could never fire). Inputs:
the rolled league dir (TEAMS\CLASSIC), the pre-roll snapshot C:\DYNSNAP (V20s, MAJ), C:\DYNSNAP\RETIRED.DAT,
HISTORY.DAT. It rewrites team V20s, the pool files, HISTORY header bytes 1..2 and 16..17, and ROSTERS.TXT.
Same integer conventions and xorshift16 as C1. All lists below are in ascending order unless stated.

Files and header bytes:
- Teams = mapped_teams (C2): V20s whose stem matches a MAJ slot, sorted file order. ALLSTAR files are not teams;
  C9 (amended 2026-10-07) rebuilds them after step 7.
- Pool = POOL1.V20..POOL4.V20 in the league dir (unmapped, so the game and HISTWR ignore them; DYNASTY rolls them
  like any V20: pool players age and can retire, and the C4 fill turns pool vacancies into the draft class).
  Missing pool files are created by ROSTERS: header all zero except name "FREE AGENTS" (+0) and league code
  copied from the first team, 80 zero records. 4 x 40 slots: pitcher slots 0..15, batter slots 16..39 (as teams).
- HISTORY header (C2 bytes 10..31 were zero): 10 u8 era mode (0 real calendar, 1 reserve clause always, 2 free
  agency always), 11 zero, 12..15 u32 managed-team mask (bit k = league-global id k; 0 = all AI), 16..17 u16 rng
  word at ROSTERS start. ROSTERS reads its rng from bytes 1..2 (DYNASTY's end word; 0 -> 1) and writes the end
  word back to 1..2, so the next roll continues the stream. Missing HISTORY -> ROSTERS does nothing, exit 2.
- Year = record byte 21 + 1870 of the first named record of the first team (the season being started).
- Record byte 141 = pool years (0 on every team record; ROSTERS zeroes it on signing, both halves).
- A "player" = the record pair (i, i + 40) of one file. Every move copies both records together and vacates the
  source (both records zeroed). Pitcher slots only ever take pitchers, batter slots only batters.

Definitions:
- Ratings come from the roster half (record i). Batter: power, hit_run, speed, range, arm. Pitcher: control,
  velocity, endurance.
- Primary position p = pos1 (0x1f lo). Field weights (rw, aw) by p: C(1) 1,3; 1B(2) 1,0; 2B(3) 3,1; 3B(4) 2,2;
  SS(5) 3,2; LF(6) 1,1; CF(7) 3,1; RF(8) 1,2; DH(9) 0,0; OF(10) 2,1; IF(11) 2,2; O/I(12) 2,1; C/O(13), C/I(14),
  C/3(15) 1,3; 0 (pitcher code in a batter slot) 0,0.
- can_play(player, q) for field positions q = 1..8: true if pos1 or pos2 is q, or a group code covers q:
  OF -> 6,7,8; IF -> 2,3,4,5; O/I -> 2..8; C/O -> 1,6,7,8; C/I -> 1..5; C/3 -> 1,4. Every batter can DH.
- Off = 3*power + 3*hit_run + speed. Fld(q) = rw[q]*range + aw[q]*arm (weights of position q, not of p).
- Score: batter S = Off + Fld(p); pitcher S = 3*control + 3*velocity + 2*endurance.
- Potential ratings: for each rating r, pot = min(cap, r + ((G[age] + 128) >> 8)) if r < cap else r; cap 10 for
  endurance, 12 otherwise; G[age] = sum of g(x) for x = age+1..26 with g = 90 (x <= 22), 64 (23..24), 32 (25..26);
  G = 0 for age >= 26. Age = record byte 20 (already aged by the roll). Spot = S computed on pot ratings.
- Value V = (S*(256 - w) + Spot*w) >> 8, w by age: <= 20 179, 21..22 154, 23 141, 24 102, 25 77, 26 38, 27 13,
  else 0. Then age discount V = (V * f) >> 8, f: <= 29 256, 30..31 248, 32..33 236, 34..35 220, 36..37 200,
  38+ 180. (Depth decisions use S, roster decisions use V.)
- Playing time from the snapshot season record (DYNSNAP record i + 40, same file and index): batter PA = ab_l+ab_r+
  bb_l+bb_r (war.py's pa), pitcher outs = war.ipiv_outs(ip10). Class: none if games = 0; batter low PA < 100, mid
  100..399, reg 400+; pitcher low outs < 90, mid 90..299, reg 300+. A slot that was vacant in the snapshot or is a
  C4 rookie: class none.
- C4 rookie = a slot that is named now and was vacant in the snapshot or flagged in RETIRED.DAT.
- SP = pitcher with endurance >= T.SP_END, else RP.
- Reverse standings order: teams by W/(W+L) ascending, compared as W1*(W2+L2) vs W2*(W1+L1) (0-0 counts as .500),
  ties by sorted file order. W, L from the snapshot MAJ (maj.wl).

Pipeline (each step over teams in sorted file order unless stated):
1. Pool cleanup: every pool player with byte 141 >= T.POOL_YEARS retires unsigned (vacated, logged).
2. Draft class: every C4 rookie on a team (AI or managed) moves to the pool list (vacates its team slot).
   Pool C4 rookies stay in the pool. Draft class = all pool players with exp = 0 and byte 141 = 0 after this step.
3. Release (AI teams only), per team, pitchers (slots 0..15) then batters (16..39), slots ascending:
   protected = top T.KEEP_P pitchers / T.KEEP_B batters by V (ties lowest slot), plus the best V batter whose
   pos1 is C, SS, 2B and CF (one each, if any), plus exp <= 1 and age <= 24. Each unprotected player, while the
   team's release count < T.REL_CAP: p = T.REL[band][class] (band: age <= 24, 25..29, 30..33, 34+); if V >= the
   median V of the team's group (lower median of the sorted V list) then p = p >> 1. d = draw() & 0xff; released
   iff d < p. Released players move to the pool list. No draw once the cap is reached.
4. Market (AI teams only, only when free agency is on: era 2, or era 0 and year >= 1976): same order, every
   remaining non-rookie player with exp >= 6 draws once: d = draw() & 0xff; enters the pool iff d < T.MKT.
5. Signing: pool list = pool file players (files sorted, slots ascending) then moved players in the order they
   moved. Rounds: in reverse standings order, each team with a vacancy that has an eligible candidate takes one:
   - AI team: candidates = pool players of a vacant slot type. Need for a batter candidate c with pos1 p:
     best = the team's highest V among its batters with pos1 = p (0 if none); for a pitcher: best = the team's
     5th highest V among its pitchers of c's role (SP/RP), 0 if fewer than 5. score = V(c) + 2 * max(0, V(c) -
     best). Take the max score, ties earliest in the pool list.
   - Managed team: candidates = draft-class players of a vacant slot type; take the max V, ties earliest.
   The player goes to the team's lowest vacant slot of its type, byte 141 = 0. Rounds repeat until a full round
   signs nobody.
6. Trades (AI teams only, no draws). Starters per team = the depth rebuild's assignment (step 7) computed on the
   current rosters. League median at position q = lower median of every AI team's starter S at q (SP: the 5
   rotation S values of every team pooled; RP: the 5 relievers pooled). Need(team, q) = median(q) - starter S at
   q (for SP/RP: median minus the team's worst rotation/relief S), a need exists if > T.NEED. Surplus(team, q) =
   a non-starter whose can_play(q) (pitchers: role q) and whose S >= median(q). For each team A in standings order
   best first, its largest need q (ties lowest q, C=1..RF=8, then SP, RP): search partners B in sorted order with a
   surplus x at q, such that A has a surplus y of the same type (batter for batter, pitcher for pitcher) at some
   q2 where B has a need; neither x nor y is in its team's top 3 V of its type; |V(x) - V(y)| * 100 <= T.BAND *
   max(V(x), V(y)). First valid (B, x, y) in order of B, then x by slot, then y by slot: swap x and y (each takes
   the other's slot). At most 1 trade per team, at most T.MAX_TRADES per offseason.
7. Depth rebuild (AI teams) or repair (managed teams), then pool write-back.
   Rebuild:
   - Pitchers: active 10 = top 10 named pitchers by S (ties lowest slot). Rotation (+111..+115) = the 5 active with
     the highest 3*control + 3*velocity + 4*endurance, in that order; relievers (+116..+120) = the other 5 by
     3*control + 3*velocity descending; +121 = 0xff; +110 = 0.
   - Batters: field starters greedy in order C, SS, 2B, CF, 3B, RF, LF, 1B: the unassigned named batter with
     can_play(q) and max Off + Fld(q); if none can play q, the unassigned batter with max Off + Fld(q) - 20. DH =
     unassigned max Off. Backup catcher = unassigned max Fld(1) among can_play(1) (if any). Active 15 = 8 field
     starters + DH + backup C + the rest by S descending up to 15. Ties lowest slot.
   - Form (amended 2026-10-07, R2): if T.FORM_A > 0, before each AI team's rebuild (teams in order) draw once per
     named slot 0..39 in slot order: f = (draw() & 0xff) % (2 * FORM_A + 1) - FORM_A. f is added to that player's
     S in the active 10 pitchers, the "rest by S" active batters and the bench order, and to Off + Fld(q) (and
     Off + Fld(q) - 20) in the field picks and Off in the DH pick. Rotation, relief order, backup C and batting
     order use no form. Managed teams draw nothing. Trades (step 6) compute starters with no form.
   - Batting order (slot roles after ClaudeBall's LineupBuilder), picked in turn from the starters, each pick
     removed, ties lowest slot: #1 max 3*speed + 2*hit_run, #2 max 2*hit_run + speed, #3 max Off, #4 max power,
     #5 max 3*power + hit_run, #6.. the rest by Off descending. DH sets pick over the 9 starters (8 + DH); no-DH
     sets pick over the 8 field starters, then 0xff with position 0 (pitcher). Each entry's position byte = the
     player's assigned position (DH = 9). vs-LHP and vs-RHP sets are identical. Bench +194: the other active batters by S
     descending (no-DH: 7 incl. the DH; DH: 6 then 0xff).
   - Reserves +222..+236: the 6 inactive pitchers by slot, then the 9 inactive batters by slot.
   Repair (managed): every header list entry whose slot changed occupant this offseason (or is vacant) is replaced
   by the best S unchanged same-type reserve (lineup slots: one that can_play the slot's position if any); the
   newcomer takes that reserve's place in +222..+236. Unchanged entries keep their bytes.
   Pool write-back: unsigned pool-list players sorted by V descending (ties earliest); the first T.POOL_KEEP
   (pitchers and batters counted separately: T.POOL_KEEP_P, T.POOL_KEEP_B) are written to POOL1..POOL4 lowest
   vacant slots of their type with byte 141 += 1 (both halves); the rest retire unsigned. Vacant pool slots are
   the next draft class.
7c. (amended 2026-10-12) After C9 and before step 8: the C11 repair of every team, pool and ALLSTAR image.
8. HISTORY bytes 16..17 = start word, 1..2 = end word. ROSTERS.TXT (CRLF, rewritten each run): one line per
   event in order: `RET <team stem> <name>` (unsigned retirement), `DRAFT <team> <name>` (team = the file whose
   C4 vacancy produced the rookie), `REL <team> <name>`, `MKT <team> <name>`, `SIGN <team> <name> <from>`,
   `TRADE <teamA> <nameX> <teamB> <nameY>`, `POOLRET <name>` (pool cleanup and write-back drops), team stems
   upper case, names as "First Last" from the record. (Amended 2026-10-07: every line carries its names, so a
   transactions screen can read the file.)

T table (LOCKED by R2; changes are contract amendments):
- SP_END 6. POOL_YEARS 1. KEEP_P 7, KEEP_B 10. REL_CAP 8. MKT 64. NEED 8. BAND 5. MAX_TRADES 6.
  POOL_KEEP_P 32, POOL_KEEP_B 48. FORM_A 16.
- REL (/256) rows age <= 24, 25..29, 30..33, 34+; columns none, low, mid, reg:
  32 138 66 10 / 96 240 82 10 / 192 255 102 16 / 255 255 154 36 (2x the 1970-90 Lahman gone rates, capped 255).

Known v1 gaps (accepted): pool retirements are not marked in HISTORY (status stays active); the Draft GM profiles
are not used (category labels undecoded); no platoon lineups; no trades with the managed team; DYNASTY skips the
C4 fill for a file with no named record only when no earlier file (sorted 8.3 order) had one: a blank pool file
takes the year byte of the last earlier file that had a named record (amended 2026-10-07, DYNASTY.EXE and
dynasty_ref); ROSTERS still keeps at least one player per pool file when the pool has any.

## C9. All-Star refresh (added 2026-10-07, P4 All-Star continuity; ROSTERS, after C6 step 7, before step 8)

Found 2026-10-07: ALLSTAR1/2.V20 (the MAJ slot-15 teams the All-Star game uses) are never rewritten by the game
(snaps/season2_end ALLSTAR1 is byte-identical to the rolled league it started from, after an All-Star game was
played), so a dynasty keeps fielding the original stars forever, retired or not. ROSTERS now rebuilds both.
- ALLSTAR1.V20 draws from the AL teams (league-global id 0..15), ALLSTAR2.V20 from the NL (16..31). The file is
  found case-insensitively in the league dir; a missing file, or one whose size is not a V20, is skipped (not
  created, not written).
- Candidates: every named roster slot s (0..39) of every team of that league (C6 teams, managed teams included,
  pools excluded) after C6 step 7, in team file order then slot order. Each player is chosen at most once.
- Template: the ALLSTAR file's own roster slots 0..39 in slot order. A vacant template slot stays vacant. Slot type
  is the C6 convention, not the template record (DYNASTY rolls ALLSTAR files like any V20, and its C4 fill can put
  a batter rookie in a slot below 16). A named slot 0..15 takes the remaining pitcher with max S (C6 S, the roster
  record). A named slot 16..39 with q = pos1 of the template record takes, in this order of preference: the
  remaining batter whose pos1 == q, max S; else the remaining batter that can_play(q) (C6), max Off + Fld(q); else
  the remaining batter with max S.
  Ties: earliest candidate. No candidate left: the slot is vacated (both records).
- Qualifier (Q6, amended 2026-10-08): read from each candidate's season record (s + 40), which still holds the
  season just played when ROSTERS runs. G = the max u8 games over every candidate of that league (0 when nobody
  played). A pitcher (is_pitcher on the roster record) qualifies when outs >= G (outs = ipiv_outs(ip10), about a
  third of an inning per team game); a batter qualifies when 2 * games >= G. Each slot first runs its whole
  preference chain above over qualified candidates only; if that finds nobody, it runs the same chain over every
  remaining candidate. G = 0 makes everyone qualify (the pre-Q6 rule).
- The chosen player's two records (s, s + 40) are copied byte for byte into the template slot (i, i + 40). The
  source team is not changed.
- Header: the C6 step 7 depth rebuild with no form draws (no rng use, so the C6 rng stream and every other output
  are unchanged). Every other header byte is kept.
- Written with the other outputs (same TMP and rollback rules); HISTORY and HISTWR ignore ALLSTAR files (C2).

## C7. Awards and milestones (DRAFT 2026-10-07; HISTWR + history.record_season, after the C2 step 3 player pass)

Inputs per season, all from the pre-roll league exactly as C2/C3 read it: every named record of every mapped team,
its season half stats, roster half bio/ratings, its C3 season WAR10, the C3 bat100 (batting runs x100 after the
park term), its player entry index (after step 3 appended new entries), and its league: AL if the team's
league-global id < 16, else NL. pa, outs, ab, h, hr, sb, w, sv, pso, er as in C2/C3. Ties always go to the lower
player entry index. "none" = 0xffff.

Awards, per league:
- MVP: batters (pos1 != 0) with pa >= 502: max season WAR10.
- Cy Young: pitchers with outs >= 486: max season WAR10; if none qualify, max WAR10 over pitchers with outs > 0.
- Rookie of the Year: roster exp (record byte 22) == 0 and (pa >= 130 or outs >= 150): max season WAR10.
- Gold Glove, positions 1..8 (C, 1B, 2B, 3B, SS, LF, CF, RF) by roster pos1: games >= 100 (C: >= 90): max
  score fp1000 + 10 * (2 * range + arm), then max fp1000, with fp1000 = ((po1 + a1) * 1000) / (po1 + a1 + e1)
  (1000 if the denominator is 0). Amendment 2026-10-11: the rank was 2 * range + arm alone, which on real seasons
  gave a right fielder with 38 errors (.714) the award; seasons recorded before keep their winners.
- Silver Slugger, positions 1..9 (DH = 9, NL usually none): pa >= 300: max bat100.
Storage:
- Season entry bytes 88..99 (season table entries 1..64 only): AL MVP, AL CY, AL ROY, NL MVP, NL CY, NL ROY as u16
  player entry indices (none 0xffff); 100..127 stay zero.
- Player entry bytes 152..156: career counts u8 (saturating at 255) MVP, CY, ROY, GG, SS; 157..159 zero. Counts are
  added for every season, including seasons past 64.

Milestones: HISTWR also writes MILESTON.DAT next to HISTORY.DAT (same dir), 8 B records, little endian:
0 u16 season_no, 2 u16 player entry index, 4 u8 kind, 5 u8 zero, 6 u16 value (saturating 65535).
Each run first drops every record with season_no >= the current season (so a rerun is idempotent), then appends this
season's records in player entry index order, kinds ascending per player. Career kinds fire when the career total
crosses the mark this season (before < mark <= after); season kinds when the season stat meets the mark.
- career (value = new career total): 1 H 2000, 2 H 3000, 3 HR 300, 4 HR 400, 5 HR 500, 6 HR 600, 7 HR 700,
  8 RBI 1500, 9 RBI 2000, 10 SB 500, 11 W 200, 12 W 300, 13 PSO 2000, 14 PSO 3000, 15 PSO 4000, 16 SV 300, 17 SV 400
- season (value = the season stat): 32 HR >= 50, 33 H >= 200, 34 SB >= 100, 35 BA >= .400 with pa >= 502
  (value = h * 1000 / ab), 36 W >= 20, 37 PSO >= 300, 38 ERA < 2.00 with outs >= 486 (value = er * 2700 / outs,
  i.e. ERA x100), 39 SV >= 50
Write order (HISTWR): MILESTON.DAT and HISTORY.DAT are each written to a temp file; both renames happen only after
both temp files are complete, using the C5 BAK scheme, so on any exit 2 both files are unchanged.
Award records (amendment 2026-10-11, closes the v1 gap "per-season Gold Glove and Silver Slugger winners are only
kept as career counts"): after this season's milestone records HISTWR appends one MILESTON.DAT record per award
winner, AL block then NL block, k ascending: kind = 64 + k (AL) or 96 + k (NL), k = 0 MVP, 1 CY, 2 ROY, 2 + q Gold
Glove position q (1..8), 10 + q Silver Slugger position q (1..9); idx = the winner's entry index; value = s16 stored as
u16 (value & 0xffff): the season WAR10 for MVP, CY and ROY, fp1000 for Gold Glove, bat100 for Silver Slugger. No record
for an award with no winner. Written every season (also past 64) and dropped with the season on a rerun like every
other record. Milestone readers (MILESTONES, REVIEW) skip kinds >= 64. DYNVIEW shows them on SEASON AWARDS (hub key
9; C8). A season recorded before this amendment has no award records; SEASON AWARDS then falls back to the six
winners in the season entry.
Leader records (second amendment 2026-10-11, closes IDEAS "leaders of an archived season"): after the award
records HISTWR appends, AL block then NL block, k ascending, one record per category that has a leader: kind = 128 + k
(AL) or 160 + k (NL), idx = the leader's entry index, value = the stat as u16 (saturating 65535). Candidates are the
same per-league list the awards use. k: 0 BA = h * 1000 / ab, max, over pa >= 502 and ab > 0; 1 HR; 2 RBI; 3 H;
4 SB; 5 W; 6 ERA = er * 2700 / outs (ERA x100), MIN, over outs >= 486; 7 SO (pso); 8 SV; 1..5, 7, 8 are max and need
a value > 0. Ties go to the lower entry index. Written every season, dropped on a rerun like the award records.
Milestone readers skip them (kind >= 64). SEASON AWARDS lists them after the award records in kind order: AWARD
`AL BA LEADER` .. `NL SV LEADER` (`<lg> <cat> LEADER`, cat BA HR RBI H SB W ERA SO SV), NAME, VALUE `.352 BA`,
`47 HR`, `131 RBI`, `210 H`, `62 SB`, `24 W`, `1.87 ERA`, `301 SO`, `45 SV`. Seasons recorded before have none.
World Series records (third amendment 2026-10-11, closes IDEAS "playoff box scores of an archived season" for the
World Series): after the leader records HISTWR appends the season's World Series games from the league's PLAYOFFS.AL
(FORMATS.md: 59569 B, byte 0 = games played n, record g of 7446 B at file offset 1 + 7446 * g, GAME.TMP layout; the
stock game reuses it for the World Series and it is still there at roll time). Read only when the file exists, is at
least 1 + 7446 * n bytes and 1 <= n <= 7. Per game g < n (record offsets r): home stem = the 8 B at r + 0x1c01,
visitor stem = r + 0x1c09 (NUL padded), each matched case-insensitively to the MAJ slot stems (id = slot for AL, slot +
16 for NL, as the V20 team mapping); visitor runs u8 at r + 0x1beb, home runs u8 at r + 0x1bec; team t (0 visitor, 1
home) hits = sum of the 80 bytes at r + 0x208 + 0x8e8 * t, errors = sum of the 80 bytes at r + 0x5c8 + 0x8e8 * t
(each sum capped at 255). A game whose stems do not both map, or whose two teams are in the same league, writes
nothing. Each kept game writes two records, in g order: kind 192 + g, idx = visitor id * 256 + home id, value =
visitor runs * 256 + home runs; then kind 200 + g, idx = visitor hits * 256 + home hits, value = visitor errors * 256 +
home errors. Verified on three real seasons: runs equal the accumulator R sums and the series winner is the season
entry's champion every time. Dropped on a rerun like every record of the season; milestone, award and leader readers
ignore kinds 192..207.
World Series box scores (fourth amendment 2026-10-11): HISTWR also writes BOXSCORE.DAT next to HISTORY.DAT, always
(possibly 0 bytes), with the MILESTON drop rule (old records with season < current kept, only when HISTORY.DAT
existed; a short tail dropped), then this season's records. Record = 16 B: u16 season, u8 game g, u8 flags (bit0
side: 0 visitor, 1 home; bit1 pitching row), u16 player entry index (0xffff when the record has no entry), u8 the
side's batting-slot byte b of the player, u8 player id i (V20 record number), 8 u8 stats. For each game g that the
third amendment keeps (same PLAYOFFS.AL checks, same stems and league rule), in g order, side t = 0 then 1 (team id =
the visitor id, then the home id): batting rows, then pitching rows. Team t block at r + 0x8e8 * t (FORMATS.md
GAME.TMP accumulators, verified on 25 real games: the sums equal the line score R, H, E): singles u8 by id at R 0xf0,
RBI 0x118, SB 0x168, IP10 0x6e0 (innings * 10 in baseball notation, 72 = 7.2), ER 0x708, R allowed 0x730; pairs
(2 * id and 2 * id + 1, summed, capped at 255) at AB 0x1b8, H 0x208, HR 0x2f8, BB 0x348, SO 0x398, BF 0x758, H
allowed 0x7a8, HR allowed 0x898, BB allowed 0x8e8, SO allowed 0x938. b = byte r + 6975 + 40 * t + i: 0 = did not
appear; else low nibble = batting slot (0..8, 9 = the pitcher with the DH) and high nibble = entry order within that
slot (1 = started), verified on 218 real sides. Batting rows: every i 0..39 with b != 0 and (b & 15) <= 8, sorted by
(b & 15, b >> 4, i); stats AB R H RBI HR BB SO SB. Pitching rows: every i 0..15 with b != 0 and ((b & 15) == 9 or IP10
> 0 or BF > 0), sorted by (b >> 4, i); stats IP10, H allowed, R allowed, ER, HR allowed, BB allowed, SO allowed, BF.
Entry index = the entry the C2 player pass used for record i of the team file mapped to that team id this season
(0xffff for an inactive record or an unmapped team). Stats of an id that did not appear are ignored (the stock game
sometimes credits a stray RBI to an absent pitcher id).

## C8. The patched TONY2.BAT and DYNVIEW (added 2026-10-07; supersedes the C5 BAT block)

tools/m4/rig/bat_patch.py replaces the stock `:start` / `control` pair with:
```
:start
copy TEAMS\CLASSIC\*.* C:\DYNSNAP > NUL
dynasty
if errorlevel 1 goto rolled
goto ctl
:rolled
call archive
histwr
rosters
dynview /offseason
:ctl
control
```
The labels `rolled` and `ctl` are free in the shipped BAT (DOS matches 8 chars, case-insensitive). Every earlier
patched form (C5 with and without the histwr line, C8 with `dynview /review` and without `call archive`) upgrades in
place; --revert restores the stock pair from any form. ARCHIVE.BAT copies the pre-roll C:\DYNSNAP to the first free
C:\SEASONS\Snn.
Boot screen (added 2026-10-08): when the stock `:frontend` / `play` pair is present the patch makes it
`:frontend` / `dynview /title` / `play`, so DYNASTY MODE shows before the intro on every launch (re-patching an install
from before this adds it; --revert removes it). /TITLE is the MENU with cat 16: title `DYNASTY MODE: SEASON N+1`,
ENTER or ESC goes on to the game, 1-6 open a screen whose ESC returns to the plain menu. With no recorded season it
shows the fixed TITLE_ROWS how-to text and the footer `ENTER PLAY BALL`. Precedence /OFFSEASON, /REVIEW, /TITLE.
DYNVIEW.EXE (C, OpenWatcom large model; the Python reference is tools/m4/dynview.py) writes no file in interactive
mode except the two C10 writes: DYNASTY SETTINGS (HISTORY.DAT bytes 10 and 12..15) and, with /MENU, CONTROL byte 1. `/review` opens the season review; ESC from REVIEW goes to the menu, ESC from the menu
exits 0 and the BAT falls through to control. A missing DYNVIEW or ROSTERS prints the DOS error and the BAT goes on.
The install copies DYNASTY.EXE, HISTWR.EXE, ROSTERS.EXE and DYNVIEW.EXE into the game dir.
DOS limit: DYNVIEW reads at most the first 7000 MILESTON.DAT records (one far allocation under 64 KB); later
records are not listed (about 100 seasons at the observed 20 to 35 milestone records plus up to 40 award records a season). HISTORY.DAT has no cap (entries are read one
at a time).

### C8a. The offseason sequence (added 2026-10-08)
The roll runs when BACK's post World Series menu takes SEASON > START NEW SEASON (BACK saves, exits with CONTROL
`02 01 07 f3 01 00 00 24 00`, and the BAT reaches `:rolled`) or when the player QUITs after the World Series. It ends in
`dynview /offseason`, a walk through six screens, ENTER for the next one:
1. `1/6 SEASON N IN REVIEW` (the /review rows)
2. `2/6 RETIREMENTS`: status 2 or 3 with last_season == N, WAR10 descending then index ascending; NAME, AGE, YRS,
   WAR, HOF (HOF when inducted this season)
3. `3/6 ROOKIE DRAFT`: ROSTERS.TXT SIGN lines that match an unconsumed DRAFT line (same stem, ASCII upper case, and
   same name; the first such DRAFT in file order is consumed; at most 400 DRAFT lines kept)
4. `4/6 TRADES`: two rows per TRADE line (A gets X from B, B gets Y from A; B is the first token from index 3 that
   names a team file)
5. `5/6 FREE AGENT SIGNINGS`: every other SIGN line, FROM `FREE AGENT` for the pool
6. `6/6 SEASON N+1 IS READY`: the counts, then `ENTER: ON TO SEASON N+1`; ENTER exits 0 and control hands on to the
   next program (MAIN's new season flow after BACK, the DOS prompt after QUIT)
ROSTERS.TXT lines over 127 bytes are ignored whole; an empty phase shows one message row. `6  OFFSEASON` on the
menu opens the same walk without the launched flag, so its last ENTER goes back to the menu. ESC still goes to the
menu and ESC there exits.

DYNVIEW saves the caller's video state (BIOS mode, the 768 DAC bytes and, in mode 13h, sequencer 2 and 4, CRTC 0Ch,
0Dh, 14h and 17h, GC 5 and 6) and restores it on exit with a cleared screen. MAIN after BACK never sets the video
mode itself; the old exit to text mode 3 left MAIN drawing into a text screen (black, stuck). Rig check 2026-10-08: a
mode 13h caller, then DYNVIEW, then MAIN matches the same run without DYNVIEW.

## C10. The DYNASTY menu on MAIN's menu bar (added 2026-10-08)
Amendment 2026-10-11: the same DYNASTY title and items are on BACK's, MANAGE's and UTIL's bars too (DRAFT has
none). menu_patch.py patches MAIN, BACK, MANAGE, UTIL and CONTROL together; it checks all five are stock or
patched before it writes any. Picking an item from BACK, MANAGE or UTIL leaves that program through its normal
switch path (BACK saves the day first) with CONTROL[1] = 8 + k, and DYNVIEW / CREATE return to it through
CONTROL[0], which the program wrote on exit. Per-EXE addresses: notes/RE_NOTES.md "Menu bar on every program".
Every mod is reachable from the game's own menu bar. tools/m4/menu_patch.py patches MAIN.EXE and CONTROL.EXE in an
install (idempotent, asserts stock bytes, `--revert` restores them byte for byte, refuses the pristine tree):
- MAIN's bar gains a sixth entry, DYNASTY (between UTILITIES and the home plate), with four items. Picking item k
  makes MAIN store CONTROL[1] = 8 + k and leave through its normal shutdown path (it saves as for any program switch).
- CONTROL.EXE accepts states 1..11 and exits with errorlevel = CONTROL[1] (stock: 1..6 through a table whose every
  handler did the same).
- UTILITIES loses IMPORT ONLINE SERVICE STATS (a dead 1993 online-service import; its string id 0x2d is reused).
- Bytes, caves and the string-table move: notes/RE_NOTES.md "Menu bar" and FORMATS.md "MAIN menu data".

| item | CONTROL[1] | errorlevel | BAT route | program |
|---|---|---|---|---|
| DYNASTY MODE | 8 | 8 | `:dynmenu` | `dynview /menu`: the hub (history, HOF, leaders, milestones, review, offseason, settings, about, awards, standings) |
| CREATE A PLAYER | 9 | 9 | `:create` | `create` (CREATE.EXE) |
| DYNASTY SETTINGS | 10 | 10 | `:dynmenu` | `dynview /menu`: SETTINGS |
| ABOUT THE MODS | 11 | 11 | `:dynmenu` | `dynview /menu`: ABOUT |

C8 amendment, the BAT (bat_patch.py): ahead of the stock `if errorlevel 7 goto end`:
```
if errorlevel 10 goto dynmenu
if errorlevel 9 goto create
if errorlevel 8 goto dynmenu
```
and after the stock `goto frontend`:
```
:dynmenu
dynview /menu
goto start

:create
create
goto start
```
Both programs set CONTROL[1] = CONTROL[0] before they exit (DYNVIEW only with /MENU), so `:start` runs `control`
with the caller's state and MAIN comes back where it was. The route passes `:start`, so DYNASTY runs first: on a day
other than 0xf3 it is a no-op; at 0xf3 (season over) the roll runs exactly as it would on any other return to MAIN.
The labels `dynmenu` and `create` are free in the shipped BAT. The routes and labels go in together or not at all.

DYNVIEW `/MENU` (Python `--menu N` / `--control PATH`): reads CONTROL in the cwd; d[1] in 8..11 gives item d[1] - 8,
else 0. Item 2 opens SETTINGS, 3 ABOUT, anything else the hub. Precedence /OFFSEASON, /REVIEW, /TITLE, /MENU. The hub
has eight rows (7 DYNASTY SETTINGS, 8 ABOUT THE MODS; ten with the amendments below) with or without a recorded season. Amendment 2026-10-11: a ninth row
`9  SEASON AWARDS` (screen 9, footers `1-9 SELECT ...`). SEASON AWARDS shows one season, newest first: LEFT goes one
season back, RIGHT one forward (page reset), PGUP/PGDN page by 12, ESC to the hub. Title `SEASON N AWARDS`. Rows are
that season's C7 award records in kind order (AWARD, NAME, VALUE: `7.4 WAR`, `.992 FLD`, `45.2 RUNS`); a season with no
award records shows the season entry's six winners and `GG SS  NOT RECORDED` (seasons past 64: `NO AWARDS RECORDED`).
Second amendment 2026-10-11: a tenth row `0  SEASON STANDINGS` (screen 10, key `0`, footers `0-9 SELECT ...`), same
season browsing as SEASON AWARDS, title `SEASON N STANDINGS`. Rows come from the C2 season entry's w_l pairs: per league
with any games, a header row (`AMERICAN LEAGUE`, `NATIONAL LEAGUE`) then its teams by PCT desc, W desc, id asc (TEAM, W,
L, PCT, GB as `-`, `4`, `4.5`, mark `WS` for the champion, `P` for the other pennant winner). A team with no MAJ stem
shows `TEAM n`. No games in either league, or a season past 64: `NO STANDINGS RECORDED`.
Third amendment 2026-10-11: SEASON STANDINGS follows the stock Season > Standings screen. A league splits into its two
MAJ divisions (FORMATS.md: slot = division * 8 + i, East slots 0..7, West 8..15; league-global id = slot, NL slot + 16)
when both halves have a team with games: blocks `AL WEST`, `AL EAST`, `NL WEST`, `NL EAST` in that order (the stock
screen's order), each sorted and GB-measured on its own. A league with games in only one half keeps the one
`AMERICAN LEAGUE` / `NATIONAL LEAGUE` block. GB is written the stock way: `-` for 0, else `N.0` or `N.5` (`9.0`, `1.5`,
`-2.0`). With no recorded season the season screens' titles carry no number: `SEASON AWARDS`, `SEASON STANDINGS`,
`LAST SEASON REVIEW` (a954686).
A header that would land on a page's last row (row 12 of 12) gets one blank row before it, so it opens the next
page with its teams (CLASSIC: NL EAST moves from page 2's foot to the top of page 3); at most four, 40 rows.
Fourth amendment 2026-10-11: an eleventh hub row `W  WORLD SERIES` (screen 11, keys `W` 87 and `w` 119; hub
footer `0-9 W SELECT   ESC EXIT`, /TITLE footer `0-9 W SELECT   ENTER PLAY BALL` when a season is recorded), same
season browsing as SEASON AWARDS, title `SEASON N WORLD SERIES` (`WORLD SERIES` with no recorded season). Columns
TEAM (17, left), R, H, E (5 each, right), and a 10 wide right column. Per game with a kind 192 + g record of the
season (g ascending, the first record of a kind wins): a header row `GAME g+1`, the visitor row and the home row (team
name as SEASON STANDINGS names it, R, H and E from the 200 + g record or empty without one, `W` in the last column of
the team with more runs). Then one summary row: the team with more wins and `WINS a-b` when it has 4, else
`LEADS a-b`; equal wins: `SERIES` and `TIED a-a`. A season with no such record, or past 64: `NO WORLD SERIES RECORDED`.
Fifth amendment 2026-10-11 (box scores): on WORLD SERIES keys `1`..`7` open screen 12, the box score of game g = key
- 49 when the season has a kind 192 + g record (else nothing); WORLD SERIES footer `1-7 BOX  LEFT RIGHT SEASON  PGUP
PGDN  ESC`. Box state (12, page, cat * 8 + g), title `SEASON N WS GAME g+1`, footer `LEFT RIGHT GAME   PGUP PGDN   ESC
SERIES`; LEFT and RIGHT step to the previous or next game that has a 192 record, ESC returns to that season's WORLD
SERIES page 0. Columns: name 18 left, six 4 wide right, blank headers. Rows from BOXSCORE.DAT records of (season,
g) in file order: visitor then home, each a header row (team name as WORLD SERIES names it, `AB R H RBI BB SO`), its
batting rows (name, AB, R, H, RBI, BB, SO), a `PITCHING` row (`IP H R ER BB SO`) and its pitching rows (IP as
`7.2`). Names as SEASON AWARDS (18 wide); entry 0xffff shows `?`. No records: `NO BOX SCORE RECORDED`.

DYNASTY SETTINGS edits the C2 header fields that had no UI: byte 10 era mode (ENTER cycles REAL CALENDAR (0) ->
RESERVE CLAUSE (1) -> FREE AGENCY (2) -> REAL CALENDAR; any other value shows RESERVE CLAUSE and goes to FREE AGENCY)
and the u32 managed-team mask at 12..15 (one row per team of the league's MAJ, YOU MANAGE / AI MANAGES). Each ENTER
writes only those bytes; a missing HISTORY.DAT is created as 32 zero bytes first, a shorter one zero-extended to 32.
The next roll reads them (C6). ABOUT THE MODS is fixed pages (12 rows each, four since C12) describing every mod.

CREATE A PLAYER (CREATE.EXE, Python reference tools/m4/create.py): TEAM list (MAJ order, AL then NL), SLOT list (the
team's 40 roster slots, P1..P16 pitchers, B1..B24 batters), EDIT form (names, position, hands, age, ratings, face with
the portrait drawn; typed letters are stored upper case like every stock name, since the LARGE font has no lower
case glyphs), CONFIRM when the slot is named, DONE. The save writes two 143-byte records into the team V20 in
place: roster record s and season record s + 40, built like a C4 rookie (stat constants, salary, exper 0 consist 2)
with the chosen fields and ratings and no random draw; the season half is the record with the season stat offsets
zeroed. No point budget, salary not shown. The new player takes the replaced player's lineup and staff spots
unchanged (no repair pass), and the replaced player leaves the league (not added to any pool or history).
Amendment 2026-10-12 (Q8, C11): the roster record carries the C11 line of its typed ratings (written after the
rating nibbles), and the season half zeroes every C11 SEASON_STAT_BYTES offset. The SLOT list has a 5th column
ROLE (CX(36), 5 wide, left): ROT if the slot is in header 111..115, PEN 116..120, START 122..157, BENCH 194..221,
RES 222..236, else blank (blank for an empty slot). CONFIRM on a RES slot shows a 4th row
`RESERVE SLOT: ACTIVATE HIM TO PLAY.` (a reserve never plays until moved to the active roster in the stock roster
screens).

## C11. Ratings-implied stat line (added 2026-10-12, Q8; Python tools/m4/statline.py, C tools/m4/statline.h)

Found 2026-10-12 on the rig: BACK drives a batter's hitting from the roster-half stat line (records 0..39, the
career line C1 merges into), not from the rating nibbles. The C4 placeholder line (batters G 0, AB 40, nothing
else; pitchers G 0, IP10 200, nothing else) made every rookie and every created player hit about .000 whatever his
ratings. fill(rec) replaces it with a line whose tools/ratings.py ratings equal the stored nibbles.
- Bytes: fill zeroes SEASON_STAT_BYTES = 23, 32..73, 77..93, 95..132 (exactly the bytes the shipped season halves
  hold at zero) and writes the line there; no other byte changes. Batted-ball words 61..69 = 532 450 200 450 200
  (every shipped batter). Pitcher iff pos1 (31 lo) == 0. Nibble 0 counts as 1, above 12 as 12, endurance cap 10.
- Batters: G 140, AB 500, BB and SO per 1000 AB by hit and run, H nudged until hit and run is exact, extra bases
  aimed inside the power step and nudged until power is exact, SB/CS and 2B-to-3B moves for speed. R and RBI from H,
  HR and BB. L/R split by bats (L 223, else 332 per mille to the left column). Fielding (pos1 1..8): E from range,
  A the least that makes arm exact, PO the least that makes range exact; catchers RTO u16@90 = 220 + 26 * arm.
- Pitchers: starter iff endurance >= 5 (G 33, GS 33, CG min(20, 2(E - 4)), SHO CG / 3), else reliever (G 50, SV
  10); IP10 rounded to whole innings; BB nudged for control, H for velocity, HR 7 % of H, ER = R from H, BB, HR; W-L
  from the ERA; the pitcher's own batting line AB 60, H 9 (power 1, hit and run 1, the stock pitcher nibbles).
- Exactness (whole rating grid): hit and run, arm, control, velocity, endurance always; power except where H makes
  it impossible (power is between the BA ladder step and the 4 x BA step); range except where A alone already
  exceeds it; speed never above the target, 1 to 2 below on 375 of 5184 power/hit-run/speed triples. Bunt is not
  targeted (the stored bunt nibble stays).
- Placeholder signature (is_placeholder): byte 0 != 0, G == 0, and pitcher IP10 == 200 with H, BB, SO 0, or batter
  AB == 40 with H, BB, SO 0. Zero matches in the 57 shipped V20s.
- Where: CREATE writes it on save (C10 amendment); ROSTERS repairs every placeholder roster record of every team,
  pool and ALLSTAR image after C9 (C6 step 7c), which also fixes players created before this amendment.
- Integer only; the C port matches the Python byte for byte (host grid, random records, shipped V20s; 16-bit DOS
  subset in DOSBox-X). The win-percent division rounds toward zero (C semantics).
- Accepted: the line is a one-season career prior. The game's own career display shows it, and the sim's rates
  blend it with real seasons as C1 merges them in. HISTORY totals, leaders, awards and WAR read season halves, so
  they never include it.


## C12. Playoff format: 3 divisions and a wild card (added 2026-10-12)

Found 2026-10-12 on the rig: the engine plays a 3-division league natively, a 4-team field per league (the 3 division
winners plus the best second place by W) through a division series, LCS and World Series, once MAIN's load-time
downgrade is patched out and the season is started with the GENERATED schedule. Proof season (1994 alignment): AL
field CLE NYA OAK DET (DET the wild card), NL SL SF PHI LA (LA); World Series SL over CLE 4-0, every team 162 G.

### C12.1 Engine facts (MAJ)
- Global 0x20c = leagues (2), 0x20d = divisions per league (1, 2 or 3), 0x20a = day (7 new season set up, 0xf3
  season over). Team counts: global 0x20e + 3 * L + d and per league S + 0x298 + d (L 0 AL, 1 NL; d 0 East, 1 West,
  2 Central). S = 0x21d (AL), 0x758c (NL).
- Slot = d * 8 + i. With 1 or 2 divisions i < 8 (CLASSIC East 0..6, West 8..14). With 3 divisions i < 5: BACK
  compacts a slot to 0..14 (slot < 8 same, 8..15 minus 3, 16..23 minus 6).
- Engine id: the team byte in schedule pairs, playoff bytes and the MAJ header stem table. L * 16 + c, c = the slot
  (1 or 2 divisions) or the compacted slot (3 divisions). Inverse: L = (e >> 4) & 1, i = e & 15; slot = i (divisions
  != 3), else i if i < 5, i + 3 if i < 10, else i + 6.
- Per league, slot-indexed (24 entries): names S + 0x0f (16 B), abbreviations S + 0x18f (3 B), stems S + 0x1d7 (8 B),
  standings order S + 0x2b3 (24 B), W S + 0x2cb, L S + 0x2e3, GB S + 0x2fb (u16).
- Playoff bytes per league block (engine ids): S + 0x3d3..0x3d6 division-series field (3 divisions only), S + 0x3d7/
  0x3d8 LCS pair, S + 0x3d9 the league's pennant winner (AL block 0x3da = NL pennant winner), S + 0x3db..0x3de DS wins,
  S + 0x3df/0x3e0 LCS wins, AL S + 0x3e1/0x3e2 WS wins. The C2 champion decode is unchanged once ids are converted.
- MAJ file header: 0..7 league name, 8..9 league code, then 8 B stems at 10 + 8 * k: the shipped CLASSIC holds each
  team at its 2-division engine id and ALLSTAR1 / ALLSTAR2 at k = 30 / 31. The 3-division gate season ran with this
  table left stale (old engine ids) and every team played its own schedule, so the engine does not load teams through
  it; k = 30 is a team's engine id in a 3-division NL of 15 compacted ids, so the table is never rewritten (C12.5).
- Series lengths 0x219 DS, 0x21a LCS, 0x21b WS come from Start New Season (PLAYOFF 1 LENGTH, PLAYOFF 2 LENGTH, SERIES
  LENGTH; defaults 5, 7, 7). Stock UI, not a mod setting.
- Start New Season with 3 divisions: only GENERATED (the last schedule row, after ROUND ROBIN) works; the four shipped
  .SCH templates are 2-division. GENERATED needs an even team count per league and at most 8 teams a division.

### C12.2 MAIN and UTIL patch (tools/m4/menu_patch.py)
MAIN 5000:473e (auto_convert_team_maj_file_v3_to_v2, run at every MAJ load) turns a 0x20d == 3 league into a
2-division one and wipes the slots 16..23 teams. UTIL holds the same downgrade twice. File-offset patches, each
pattern asserted to occur exactly once:
- MAIN.EXE: `26 80 bf 0d 02 03 74 03 e9 e5 00 26 c6 87 0d 02 02`, bytes +6..+7 `74 03` -> `90 90`.
- UTIL.EXE: `80 3e 02 a1 03 75 12 c4 1e 26 b5 26 c6 87 0d 02 02`, byte +5 `75` -> `eb`; and
  `80 3e 02 a1 03 74 03 e9 9b 00 c4 1e 26 b5 26 c6 87 0d 02 02`, bytes +5..+6 `74 03` -> `90 90`.
They are a separate job group ('MAIN.EXE div3', 'UTIL.EXE div3') with its own stock / patched state, so an install
that already carries the C10 menu patch upgrades in place; --revert restores them; all files of both groups are
checked before any is written. UTIL's Setup Leagues "# OF DIVISIONS 3" stays a dead widget; the mod setting below is
the only way in.

### C12.3 Stable team ids (TEAMID.DAT)
The league-global id of C2 (HISTORY w_l, champion, runner-up and pennant ids, the managed-team mask, MILESTON and
BOXSCORE team ids, park factors, ROSTERS and ALLSTAR team ids, DYNVIEW and CREATE team lists) is the team's stable id,
which a realignment never changes:
- TEAMID.DAT in the league dir: exactly 256 B, 32 x 8 B stems (NUL padded). Entry k = the stem of the team whose id is
  k; an entry whose first byte is NUL is unused. Any other size counts as missing.
- MAJ teams: every L in 0..1 and slot s the division count uses (s < 16 with 1 or 2 divisions, s % 8 < 5 with 3)
  whose stem's first byte is not NUL (unused slots and the all-star entry in slot 15 start with NUL; other slots can
  hold stale bytes and never count). A team's stem is its 8 B cut at the first NUL and NUL padded (amended
  2026-10-12: UTIL's NEW LEAGUE leaves the old name's tail after the NUL, `TEST0\0e1`, and the game reads a C string).
- With no TEAMID.DAT the id of a MAJ team is its engine id (C12.1), which is the C2 rule (AL slot s, NL s + 16) for
  every 2-division league: a dynasty that never changes format never gets the file and every output is unchanged.
- With TEAMID.DAT the id of a MAJ team is the k whose entry equals its stem, compared case-insensitively (ASCII);
  the lowest such k; a MAJ team whose stem is in no entry has no id and is skipped wherever ALLSTAR files are.
- Only the realignment (C12.5) creates TEAMID.DAT, from the pre-realignment MAJ by the no-file rule, and only when
  it is missing. Nothing rewrites an existing one.
  (Amended 2026-10-13: ROSTERS /EXPAND also creates it when teams are added, removed or moved, and adds an entry for
  every MAJ team without one; entries are never cleared or rewritten. C15.3.)
- An id < 16 is AL (a realignment never moves a team between leagues).
Helpers (Python tools/m4/teamids.py, C tools/m4/teamids.h; identical results):
- `teams(maj, table)` -> [(id, L, slot, stem)] sorted by id (ties impossible: the lowest k rule, duplicates skipped
  after the first in slot order L 0 then 1, slot ascending).
- `id_of_slot`, `slot_of_id` (-> (L, slot) or none), `id_of_engine(e)` (0xff and any engine id whose slot holds no
  team -> 0xff), `stem_of_id`.
- `load_table(league_dir)` -> the 32 stems or none.

### C12.4 The setting (HISTORY.DAT header byte 11)
Byte 11 = playoff format: 0 follow the MAJ (default, no change), 2 two divisions with an LCS (stock), 3 three
divisions and a wild card. Any other value counts as 0.
- now = the MAJ's 0x20d (1 counts as 2; no MAJ: 2). wanted = byte 11 when 2 or 3, else now.
- DYNASTY SETTINGS row 2 (after ERA RULES, before the team rows): `PLAYOFF FORMAT`, value `2 DIVISIONS` or
  `3 DIV + WILDCARD` for wanted; when wanted != now the value is `2 DIV NEXT YEAR` or `3 DIV NEXT YEAR`.
- ENTER on it writes byte 11 = 5 - wanted (only that byte; a missing or short HISTORY.DAT is created / zero-extended
  to 32 B as for the other settings), then runs C12.6's immediate apply.

### C12.5 Realignment (Python tools/m4/realign.py, C tools/m4/realign.h; byte-identical MAJ results)
`realign(maj, target)`, target 2 or 3:
- Refused (MAJ unchanged, a reason string) when: the MAJ is shorter than 59771 B; 0x20c != 2; 0x20d not in 1..3;
  target == 0x20d (1 counts as 2); a league has more than 15 teams or an odd count (target 3); more than 14 teams
  (target 2).
- Team list per league: the MAJ teams (C12.3) of L in slot order, each carrying its 16 B name entry, 3 B
  abbreviation and 8 B stem.
- Division assignment:
  - Known alignments, by abbreviation (NUL-stripped, compared exactly), used when the league's abbreviation set equals
    the table's set for that league; teams inside a division in the table's order:
    3 divisions (MLB 1994): AL East BAL BOS DET NYA TOR, West CAL OAK SEA TEX, Central CHA CLE KC MIL MIN;
    NL East ATL MON NYN PHI, West LA SD SF, Central CHN CIN HOU PIT SL.
    2 divisions (shipped CLASSIC, MLB 1993): AL East BAL BOS CLE DET MIL NYA TOR, West CAL CHA KC MIN OAK SEA TEX;
    NL East CHN MON NYN PHI PIT SL, West ATL CIN HOU LA SD SF.
  - Otherwise the generic rule over the team list: 3 divisions, n = 3q + r: East q + (1 if r > 0), West q + (1 if
    r > 1), Central q, filled in list order East, West, Central; 2 divisions: East ceil(n / 2), West the rest.
- Writes (nothing else changes):
  - per league, slots 0..23: name, abbreviation and stem entries zeroed, except slot 15 whose entries are kept when its
    stem starts with NUL; then team i of division d at slot d * 8 + i.
  - S + 0x298 + d and 0x20e + 3 * L + d = the division counts (0 for an unused division).
  - 0x20d = target; 0x20a = 0xf3.
  - S + 0x2b3..0x2ca = 0xff; S + 0x2cb..0x32a = 0 (W, L, GB).
  - the file header (bytes 0..281) is not changed (C12.1: ALLSTAR1 / ALLSTAR2 stay at k = 30 / 31).
- `apply(league_dir, out=None)`: wanted (C12.4) == now -> 1 (nothing). Else: TEAMID.DAT (C12.3) if missing, then
  realign; refused -> 2 (the reason in `out` when given), else write the MAJ in place -> 0. A missing MAJ -> 1.

### C12.6 When it applies
- ROSTERS, every roll: step 9, after C6 step 8: `apply`. ROSTERS.TXT gets `FORMAT n` (applied, n = target) or
  `FORMAT REFUSED reason`; nothing when there was nothing to do.
- DYNASTY SETTINGS ENTER on PLAYOFF FORMAT, after writing byte 11: `apply` at once when the MAJ day (0x20a) is 0xf3 and
  HISTORY byte 0 == 1 (rolled, next season not started), or the day is 7 (set up, no game played). After an apply on
  day 7, HISTORY byte 0 = 1 (the realigned MAJ is at 0xf3; byte 0 = 1 stops DYNASTY rolling the unplayed season, and
  DYNASTY's own rule clears it when the next season starts). Otherwise the change waits for the next roll.
- The player then takes SEASON > START NEW SEASON; with 3 divisions, GENERATED.

### C12.7 HISTORY season entry (C2 amendment)
- Byte 22 = the season's divisions per league (MAJ 0x20d at the roll; 0 in entries written before C12 = legacy).
  Written only when the MAJ has 3 divisions or TEAMID.DAT exists; otherwise byte 22 and the map stay 0 (legacy),
  which gives the same divisions there (id = slot), so a dynasty that never changes format stays byte-identical.
- Bytes 100..115 = division map: id k's division + 1 (1 East, 2 West, 3 Central, 0 not a team) in the nibble
  (byte[100 + k // 2] >> (4 * (k & 1))) & 15. Legacy entries (byte 22 == 0): an id with games is East when
  (k & 15) < 8, else West. Bytes 116..127 stay zero.
- Writing it (history.record_season and HISTWR): w_l[id] for every MAJ team from its slot's MAJ W/L; champion,
  runner-up and pennant ids via id_of_engine; stems via stem_of_id; byte 22 and the map from the MAJ at the roll.
- Every other C2/C7 id (league totals, player league, park factors from schedule pairs via id_of_engine, PLAYOFFS.AL
  stems, MILESTON 192+/200+ ids, BOXSCORE team ids, ALLSTAR league ranges) uses the stable id.

### C12.8 Displays
- SEASON STANDINGS (C7 amendments): divisions from the entry's map (or the legacy rule). A league whose teams with
  games fall in two or more divisions shows one block per division in the order WEST, CENTRAL, EAST (the stock
  screens' column order); one division keeps the league's long-name block. Headers `AL WEST`, `AL CENTRAL`, `AL EAST`,
  `NL WEST`, `NL CENTRAL`, `NL EAST`. Page padding unchanged (a header never on a page's last row), at most 48 rows.
- Team names everywhere: the stable id -> stem (TEAMID.DAT or default) -> the team's display name as today.
- ABOUT THE MODS: after the DYNASTY SETTINGS block's last line (`LINEUP IS REPAIRED, NOT REBUILT.`) six lines:
  `PLAYOFF FORMAT: 2 DIVISIONS AND AN LCS,`, `OR 3 DIVISIONS AND A WILD CARD WITH A`, `DIVISION SERIES. IT TAKES EFFECT AT ONCE`,
  `BEFORE A SEASON STARTS, ELSE AT THE ROLL.`, `THEN START THE NEW SEASON WITH THE`, `GENERATED SCHEDULE.`
- ROSTERS.TXT readers ignore the FORMAT lines (the OFFSEASON screen's parser already skips unknown kinds).


## C13. Season lines, leaders, player card, mouse, start year (added 2026-10-12)

Will, 2026-10-12: season and career leaders, the year each season stat was achieved, click a player in the leaders to
see his card, and choose the start year.

### C13.1 Start year (HISTORY.DAT header bytes 18..19)
- u16 start year at 18..19; 0 or any value outside 1871..2100 counts as 1993 (the shipped season of the game).
- year_of(n) = start + n - 1 for season n (1-based). One rule everywhere a season is shown to the player; changing the
  start year relabels every season, nothing else is rewritten.
- DYNASTY SETTINGS row 3 (after PLAYOFF FORMAT, before the team rows): `START YEAR`, value the 4-digit start year.
  On that row LEFT / RIGHT = -1 / +1, `-` (45) / `+` (43) or `=` (61) = -10 / +10, clamped to 1871..2100; each change
  writes bytes 18..19 only (a missing or short HISTORY.DAT is created / zero-extended to 32 B as for the other
  settings). ENTER on the row does nothing. The team rows move down one (cursor c >= 3 is team c - 3).
- C6 era rule (REAL CALENDAR): when bytes 18..19 hold a value in 1871..2100, ROSTERS' year = start + seasons recorded
  (bytes 4..5, read after HISTWR, so the season being started); otherwise the C6 record-byte-21 rule, unchanged.
- ABOUT THE MODS gains a block (C13.7).

### C13.2 SEASLINE.DAT (league dir, next to HISTORY.DAT), little endian
Header 16 B: 0 'S' 'L', 2 u8 version 1, 3 u8 0, 4 u16 line size 80, 6 u16 highest season written, 8..15 zero.
Lines, 80 B each, from offset 16, in write order:
- 0 u16 player entry index (C2), 2 u16 season_no, 4 u8 stable team id (C12.3), 5 u8 flags (bit0 pitcher: pos1 == 0),
  6 u8 age (roster half, pre-roll), 7 u8 pos1 (roster half pos1 & 15), 8 u16 face (roster half +27),
  10 u8 roster half byte 29 raw (speed, throws, bats, face group), 11 u8 dev grade (byte 142),
  12 9 x u8 ratings from the roster half, 1..15 raw nibbles in this order: power, bunt, hit_run, speed, range, arm,
  control, velocity, endurance; 21 u8 0,
  22 25 x u16 season stats in the C2 TOTALS order (G, AB, H, 2B, 3B, HR, R, RBI, BB, SO, SB, CS, E, W, L, SV, GS, CG,
  SHO, OUTS, ER, PH, PBB, PSO, PHR) of the season half, each min(value, 0xffff),
  72 s16 season WAR10 (C3, the value step 3 added to the career), 74..79 zero.
Writing (history.record_season step 3, Python reference; HISTWR in C): one line per named record that step 3 visits,
in step 3's visiting order (mapped teams in sorted V20 order, records 0..39). After step 3: read the file (missing or
a bad header: start empty), drop every line with season_no >= this season, append this season's lines, header 6..7 =
this season, rewrite. Every season is written (no 64 cap).
Backfill (Python `history.backfill_lines(hist_path, seasons_dir)`; HISTWR `/LINES [HIST_PATH SEASONS_DIR]`, defaults
`TEAMS\CLASSIC\HISTORY.DAT` and `C:\SEASONS`): only when SEASLINE.DAT does not exist next to HIST_PATH and HISTORY.DAT
exists with seasons recorded > 0; otherwise nothing (exit 0). Archives = subdirs `Snn` (nn = 01..99, two digits) of
SEASONS_DIR that hold a *.MAJ, in nn order. An archive is the pre-roll league of one season: it matches season s
(1 <= s <= min(seasons recorded, 64), not yet matched) when its w_l, built exactly as record_season step 1 builds it
from the archive's MAJ and TEAMID.DAT, equals season entry s's w_l for all 32 ids and has a nonzero game; the lowest
such s. Unmatched archives are skipped. For each match in ascending s: the lines record_season would write for that
archive as league dir and season_no s, with entry indexes from find_entry(name, 1000 + s - age) on the CURRENT
HISTORY (a record with no entry gets no line) and WAR10 recomputed with the archive's league totals and park factors.
Writes SEASLINE.DAT (header + lines in s order) even when nothing matched, so it never runs twice. Never touches
HISTORY.DAT, MILESTON.DAT or BOXSCORE.DAT.
BAT (bat_patch.py): `histwr /lines` on its own line directly before every `dynview /menu` and `dynview /title` line,
and nothing else changes; upgrade in place and --revert as for every earlier form.

### C13.3 LEADERS (DYNVIEW hub row 3 `3  LEADERS`, screen 3)
Three modes in the screen state, TAB (9) cycles CAREER -> SEASON -> BY YEAR -> CAREER (page and cursor reset,
category kept when it exists in the new mode, else 0). LEFT / RIGHT cycle the category (as today).
- CAREER: categories over HISTORY player entries, the C7 rules of cat_value / cat_qualifies, in this order:
  H, HR, RBI, R, 2B, 3B, SB, BB, AVG, WAR, W, SV, SO (PSO), ERA, IP, SHO, MVP AWARDS, GG AWARDS.
  New counts R (TOTALS 6), 2B (3), 3B (4), BB (8), SHO (18) qualify when > 0; IP is OUTS (19), qualifies when > 0,
  shown `IP` as whole innings and thirds `1234.2`. Columns and the top LIST_MAX as today. Title `CAREER LEADERS: <cat>`.
- SEASON: all-time single-season bests from SEASLINE.DAT lines, categories:
  AVG, HR, RBI, H, R, 2B, 3B, SB, BB, WAR, W, ERA, SO, SV, IP, CG, SHO.
  AVG: pa = AB + BB >= 502 and AB > 0, value H * 1000 / AB. ERA: OUTS >= 486, value ER * 2700 / OUTS, ascending.
  WAR: every line with G > 0, value WAR10. Counts (SO is PSO, IP is OUTS): value > 0.
  Sort value (descending, ERA ascending), then season ascending, then entry index ascending; top 50.
  Title `SEASON LEADERS: <cat>`. Columns: `#` (4, L), NAME (16, L), YEAR (5, R), TEAM (4, R: the 3-letter MAJ
  abbreviation of the line's team id in the current league, `?` when none), VALUE (12, R).
- BY YEAR: the same categories, qualifiers and order over one season's lines; `-` / `+` (or `=`) step the season
  (start at the newest season with lines; nothing past either end). Title `<year> LEADERS: <cat>`; top 50;
  columns as SEASON with the YEAR column blank.
- No SEASLINE.DAT or no lines: one row `NO SEASON LINES RECORDED YET.` (SEASON and BY YEAR).
Footers: CAREER and SEASON `LEFT RIGHT STAT  TAB MODE  ENTER CARD`, BY YEAR `LEFT RIGHT STAT  - + YEAR  TAB MODE`.

### C13.4 Row cursor
The screen state gains a cursor: the absolute index of the highlighted row. On HALL OF FAME, LEADERS (all modes),
SEASON AWARDS and the offseason RETIREMENTS phase: UP / DOWN move it by one within the list (page follows:
page = cursor // 12), PGUP / PGDN move the page and put the cursor on the page's first row; the highlighted row is
drawn as the SETTINGS cursor row is (C_TITLE_RED bar, white text). Every other screen keeps its current keys.
(Amended 2026-10-13, C15.8: a one-column message row is never highlighted.)
ENTER on a highlighted row whose row names a player entry opens PLAYER CARD for that entry (AWARDS rows whose entry
is 0xffff or a team, and empty lists, do nothing). On the offseason ENTER keeps its walk meaning; the card opens there
with `C` (67, 99).

### C13.5 PLAYER CARD (screen 13)
Opened from a list (C13.4); ESC returns to the exact list state it came from (one level). PGUP / PGDN page the
season table. Data: the HISTORY entry, and the entry's SEASLINE.DAT lines in season order (latest line = the
highest season).
- Title: the player's name, first then last (`name_display`), upper case.
- Portrait at x 12, y 24 (48 x 56): face = latest line's face. face < 981: ANMS\PORTRAIT.ANM frame face (CREATE's
  `portrait()` rules); 981 <= face < 1509: OLDPORT.ANM in the game dir, frame face - 981 at offset (face - 981) * 2700
  (no count word, 12 B header + 2688 B, header clen must be 0 and 48 x 56). Missing frame or no line: a C_GRID_GRAY
  48 x 56 rect with a `?` centred.
- Info lines right of the portrait (x 70; y 26, 37, 48, 59, 70), main font, white:
  1 `<POS>  BATS <B>  THROWS <T>` (POS from pos1 as the game names it: P C 1B 2B 3B SS LF CF RF DH OF IF; B L/R/S,
  T L/R from byte 29; no line: position from the entry, no hands)
  2 status: `ACTIVE, AGE <age + 1>` (status 1), `RETIRED <year_of(last_season)>` (2),
  `HALL OF FAME <year_of(hof_season)>` (3)
  3 `<first year>-<last year>  <seasons played> SEASONS` (year_of of the entry's first and last season)
  4 ratings of the latest line, batters `POW p  H&R h  SPD s` and line 5 `RNG r  ARM a  BUNT b`; pitchers
  `CTL c  VEL v  END e` and line 5 empty. No line: `NO RATINGS RECORDED`. The dev grade is never shown.
- Season table: header row at y 84 (C_HEADER_GOLD, as the list header), up to 7 season rows from y 95 (ROW_H 11),
  then a CAREER row with the HISTORY entry totals (always the entry, not the sum of lines). Batters: YEAR (4), TM
  (4, right-aligned so the abbreviation never touches the year; amended 2026-10-12, was TEAM left-aligned), G (4), AB (5), H (4), HR (4), RBI (4), SB (4), AVG (5), WAR (5). Pitchers: YEAR, TM, G, W (3), L (3), SV (4),
  IP (6), SO (4), ERA (5), WAR (5). AVG / ERA / IP / WAR formatted as the leader values. Rows newest season first.
  No lines: one row `NO SEASON LINES RECORDED` above CAREER.
- Footer `PGUP PGDN SEASONS   ESC BACK`.

### C13.6 Mouse
DYNVIEW (C) polls INT 16h AH=1 and INT 33h AX=3; INT 33h AX=0 at start decides whether a mouse exists (no mouse:
keyboard only, no other change). After the mode set DYNVIEW sets the range itself: AX=7 CX=0 DX=319, then AX=8
CX=0 DX=199, so x = CX and y = DX. The browser's DOSBox-X maps the host pointer as x_norm * the guest's max, so
the pointer only lands true when the guest range is the whole 320x200 screen; the stock EXEs set 0..304 x 0..195,
and menu_patch's MOUSE job widens MAIN, BACK, MANAGE, UTIL, BB and DRAFT to 0..319 x 0..199. The cursor is
shown (AX=1) while waiting and hidden (AX=2) while drawing. A click fires on the release of a button.
- Right click = ESC.
- Left click at (x, y), in this order:
  - hub (MENU): a menu row band (body row r, y in 35 + 11r .. 35 + 11r + 9) = that row's key.
  - SETTINGS: a team or setting row band = move the cursor there, then ENTER (START YEAR: x < 160 LEFT, else RIGHT).
  - a C13.4 list: a row band holding a row = cursor there, then ENTER (opens the card).
  - title band (y 8..20) on a screen where LEFT / RIGHT do something = LEFT when x < 160, else RIGHT.
  - footer band (y >= 183) = PGUP when x < 160, else PGDN.
  - else nothing.
`/KEYS` (and Python `--keys`) tokens: a number = a key (as today), `Lx.y` = a left click at (x, y), `R` = a right
click, so the host parity tests drive clicks.

### C13.7 Years on every DYNVIEW screen
Every place DYNVIEW shows a season number to the player shows year_of(n) instead: SEASON HISTORY's YEAR column,
MILESTONES' YEAR column, the titles (`1995 AWARDS`, `1995 STANDINGS`, `1995 WORLD SERIES`, `1995 WS GAME 3`,
`1995 IN REVIEW`, offseason `1/6 1995 IN REVIEW`, `6/6 1996 IS READY`, `ENTER: ON TO 1996`, /TITLE
`DYNASTY MODE: 1996`). Text with no season keeps its wording. ABOUT THE MODS gains, after the playoff format block:
`LEADERS: CAREER, SINGLE SEASON AND BY`, `YEAR. TAB SWITCHES. ENTER OR A CLICK ON A`, `PLAYER OPENS HIS CARD.`,
`START YEAR: DYNASTY SETTINGS, LEFT RIGHT.`

## C14. Faces: more generic faces, custom faces, Portrait Studio (added 2026-10-12)

### C14.1 Face id layout (ANMS\PORTRAIT.ANM, ANMS\FACEGRP.DAT)
- Generic faces: ids 0..G-1, G = FACEGRP.DAT length (30 <= G <= 400). Rookies draw only these (load_faces / the
  DYNASTY blob rule n = min(L, c) is unchanged: L = G).
- Custom faces (Portrait Studio): ids 400..c-1, c = PORTRAIT.ANM count (<= 981). Frames G..399 are padding (copies of
  frame 0) whenever c > 400, so a custom face's frame sits at its id.
- CREATE A PLAYER's FACE field walks the list [0..G-1] then [400..c-1] (the second part only when c > 400):
  LEFT / RIGHT -1 / +1, PGUP / PGDN -10 / +10, each wrapping around the list modulo its length. Value text
  `<id + 1> OF <G>` for a generic face, `CUSTOM <id - 399>` for a custom one. Group bit written to the record:
  FACEGRP byte & 1 for a generic face, 0 for a custom one. default_form's face rule is unchanged.
- tools/faces.py set2: about 300 prompts from a fixed grid (heritage x age band x facial hair x build x expression),
  each prompt's group flag from its heritage, fixed seeds; frames that fail the cap QC go to rejects as today. They are
  appended after the installed generic faces, FACEGRP.DAT grows with them, G stays <= 400.

### C14.2 Portrait Studio server (web/server.py), all under the existing identity check
Storage: STUDIO_DIR = env TLRB2_STUDIO_DIR, default the directory `studio` next to SAVES_DIR (sibling, never inside
it). Layout: `jobs/<id>.json` (job record), `jobs/<id>.img` (upload, deleted once the job is done or failed),
`jobs/<id>.v<k>.bin` (2688 B frame) and `jobs/<id>.v<k>.png` (preview), `customs.bin` (concatenated 2688 B frames,
custom k at offset 2688 * k). Job id = 16 lowercase hex (secrets.token_hex(8)), matched by `^[0-9a-f]{16}$`.
Browser endpoints (reads need _allowed(); every POST/DELETE needs _allowed(write=True), as saves do):
- POST /studio/jobs, JSON body (Content-Length <= 6 MiB): {"prompt": str, "image": base64 str}; either may be
  absent or empty but not both. prompt: <= 300 chars after strip, printable ASCII only (0x20..0x7e), else 400.
  image: base64 that decodes to <= 4 MiB starting with the PNG (89 50 4E 47 0D 0A 1A 0A) or JPEG (FF D8 FF)
  magic, else 400. With 3 jobs already queued or running: 429 (at most 3 active). Creates the job {id, state "queued", prompt,
  has_image, created, claimed: null, error: null, variants: 0, accepted: []}; 200 {"id": id}.
- GET /studio/jobs/<id>: 200 {"id", "state" (queued|running|done|failed), "error", "variants", "accepted",
  "position" (1-based place among queued jobs by created, or 0)}; 404 unknown.
- GET /studio/jobs/<id>/v<k>.png (k 0..3): the preview PNG, Content-Type image/png; 404 when absent.
- POST /studio/jobs/<id>/accept?pick=<k>: job must be done and v<k>.bin exist (else 409 / 404); appends the frame
  to customs.bin (count = size / 2688; at most 581 customs: 409 past that), records k in accepted (accepting the
  same k twice returns the first face again, no second append); 200 {"face": 400 + n, "custom": n + 1} where n is
  that custom's index.
- DELETE /studio/jobs/<id>: removes every file of the job; 204 (404 unknown).
- GET /studio/customs: 200 {"count": n}.
- GET /studio/PORTRAIT.ANM: 404 when customs.bin is missing or empty. Else 200 application/octet-stream:
  base = the zip entry `TONY2/ANMS/PORTRAIT.ANM` of SITE_DIR/tlrb2.jsdos (u16 count c0, c0 frames of 2700 B);
  output = u16 (400 + n), the c0 base frames byte for byte, (400 - c0) copies of base frame 0 (header and pixels),
  then each custom as FRAME_HDR (u16 0x1001, 56, 48, 0, 0, 0) + its 2688 pixels. A base that is not exactly
  2 + 2700 * c0 bytes or has c0 > 400: 500.
- Housekeeping on every studio request: a job older than 24 h (created) is removed with its files; a running job
  claimed more than 10 min ago goes back to queued.
Worker endpoints: _allowed() AND header `X-Studio-Token: <token>` (nginx basic auth owns `Authorization`) where
token is the first line of the file
named by env TLRB2_STUDIO_TOKEN_FILE, compared with hmac.compare_digest; no env, unreadable or empty file, or a
mismatch: 403. They do not need X-TLRB2 or Origin.
- POST /studio/worker/claim: oldest queued job -> running (claimed = now); 200 {"id", "prompt", "image": base64 or
  null}; 204 when nothing is queued.
- POST /studio/worker/deliver/<id>, JSON (<= 2 MiB): {"variants": [{"frame": base64 of exactly 2688 B, "png":
  base64 PNG <= 256 KiB}, ... 1 to 4]} -> done, variants = count, files written; or {"error": str <= 200 chars}
  -> failed. Either way the upload is deleted. The job must be running (409 otherwise); 204.
Every studio write takes the server lock; files are written via a .tmp then os.replace. No studio path is ever
built from client text except a validated id and k.

### C14.3 Portrait Studio worker (tools/studio_worker.py, the workstation with the GPU)
- Config: env or ~/.config/tlrb2/studio.env: TLRB2_STUDIO_URL (the site URL), TLRB2_STUDIO_TOKEN_FILE; basic auth
  user and password from ~/.config/tlrb2/web_login (url=, user=, password=). Never logs the token or password.
- Loop: when faces.owner_busy() leave the queue alone (sleep 30 s); else claim; 204 -> sleep 10 s.
- A job makes 4 variants, seeds random per job: no image -> txt2img with faces.STYLE.format(who=prompt or
  'a veteran player') and faces.NEG (the faces._workflow graph); image -> the upload goes to ComfyUI /upload/image
  and an img2img graph (LoadImage -> scale to 832 x 960 -> VAEEncode -> KSampler denoise 0.55 with the same text
  and NEG -> VAEDecode -> PreviewImage). Each render -> faces.to_frame(im) (the crop + resize + contrast +
  quantize step of faces.build, factored out unchanged) -> 2688 B; preview PNG = the frame under DEFAULT.PAL scaled
  4x nearest (192 x 224). No cap QC reject: the player picks. Then POST deliver; any exception -> deliver
  {"error": short text}. After each job POST ComfyUI /free (unload models) as faces.gen does.
- Runs as a systemd user unit (tools/studio_worker.service.example), Restart=always.

### C14.4 Portrait Studio page (web/index.html)
- A STUDIO button next to SAVES opens a panel (outside the canvas): a description box (maxlength 300), a file
  picker (PNG/JPEG, <= 4 MB, checked before upload), GENERATE (POST /studio/jobs), a status line polled every 3 s
  (queued with position / GPU busy / rendering / failed with the error), then the 4 previews; each preview has ADD
  TO GAME (accept) which shows `ADDED AS CUSTOM n: SAVE AND RELOAD, THEN PICK IT IN CREATE A PLAYER (FACE FIELD).`
  and a SAVE AND RELOAD button (the existing save-then-reload slot switch to the current slot).
- Boot: fetch studio/PORTRAIT.ANM (no-store); on 200 pass js-dos initFs [zip] where zip is a one-entry stored zip
  holding it as `TONY2/ANMS/PORTRAIT.ANM`, so the customs overlay the bundle and the save; 404 or an error boots as
  today. (Amended 2026-10-12, was a {path, contents} file entry: js-dos 8.5.3 writes file entries before it unpacks
  the bundles, so the stock file won; zip entries unpack in order after the bundle and the slot's changes. The
  overlay then counts as a changed file, so a slot saved after a boot with customs carries that PORTRAIT.ANM, about
  1 MB; the next boot's overlay still wins, and customs are append-only.)
- Writes send the existing WRITE headers.


## C15. Number of teams: expansion and contraction (added 2026-10-13)

Will, 2026-10-12: change the number of teams, with an expansion draft. Found 2026-10-13 on the rig: stock UTIL > SETUP
LEAGUES already adds and removes teams. NEW TEAM (left list, under CHOOSE FROM CLASSIC TEAMS) asks TEAM NAME and TEAM
ABBR and writes TEAMS\<L>\CLAS<n>.V20 at once (header name, abbr, stadium GRASS; a placeholder roster, below); click the
team in the left list, then an empty division row, to place it; the MAJ is written when UTIL is left (slot stem, name,
abbreviation, counts S + 0x298 + d and 0x20e + 3 * L + d; the day byte is not changed). Clicking a placed team removes it
from its division; UTIL then compacts the division (the teams below move up one slot, so their engine ids change; W, L and
GB are not moved). DELETE TEAM deletes the V20 at once, and only for a team no division holds (a placed team gets `SORRY,
BUT THIS TEAM IS CURRENTLY BEING USED IN THE LEAGUE`). Proof seasons: two new NL teams (14 + 14) played a full season on
`162 GAMES-28 TEAMS` (placeholder rosters, 5-157 and 7-155, 162 G each in HISTORY); a 14 + 12 league (NL 7 / 5) on
GENERATED. The dynasty side is ROSTERS /EXPAND, which runs at every BAT
start and turns what UTIL did into a dynasty event: an expansion draft for new teams, a dispersal for removed ones,
and stable ids for both. Draft rule (decided for Will, 2026-10-13): new teams draft unprotected players from AI teams,
then sign free agents from the pool; managed teams lose nobody.

### C15.1 Definitions
- Placeholder record: byte 0 != 0 and bytes 0..19 = `EMPTY` followed by 15 NUL (stock NEW TEAM writes these in pitcher
  slots 0..9 and batter slots 16..30, both halves; ratings 7). Real player: a slot whose roster record (i) has byte 0 != 0
  and is not a placeholder. Slots 0..15 pitchers, 16..39 batters (C6).
- MAJ teams and ids: C12.3 (`teamids.teams(maj, table)`; table = TEAMID.DAT or none).
- Current MAJ: the league's MAJ (C16.1 'maj'). Snapshot MAJ: the file in the snap dir whose name equals the current MAJ's
  base name (any case), when readable and at least 59771 B; else none.
- Team file of a stem: `<stem>.V20` in the league dir (any case), exactly 11735 B; else none.
- V, is_pitcher, write_pair, vacate, byte 141 (pool years), pool files and pool_blank: C6.

### C15.2 Detection
- Contracted stems: the snapshot MAJ's teams (C12.3 maj_teams, L 0 then 1, slot ascending) whose stem (cut at the first
  NUL, ASCII case-insensitive) is not the stem of any current MAJ team. No snapshot MAJ: none. Edge triggered (the BAT's
  HISTWR /SNAP right after ROSTERS /EXPAND makes the snapshot current).
- Expansion teams: current MAJ teams whose team file exists and whose slots 0..39 hold no real player. Level triggered.
- Moved (only matters with no TEAMID.DAT): a stem present in both MAJs whose engine id (C12.1) differs between them.

### C15.3 Stable ids (amends C12.3: ROSTERS /EXPAND also creates and extends TEAMID.DAT)
- table = load_table. When table is none and there is a contracted stem, an expansion team or a moved stem: table =
  make_table(snapshot MAJ), or when there is no snapshot MAJ, make_table(current MAJ) with every entry equal to an
  expansion team's stem zeroed.
- When table is not none (loaded or made): every current MAJ team (maj_teams order) whose stem matches no entry gets the
  lowest k in L * 16 .. L * 16 + 15 whose entry's first byte is NUL; entry k = its stem (8 B, NUL padded, case as in the
  MAJ). None free: the team stays without an id (skipped as C12.3 says, never drafted for).
- Entries are never cleared: a contracted team keeps its id, so its history keeps its name; ids are never reused.
- TEAMID.DAT is written only when its bytes change (or it was made).

### C15.4 ROSTERS /EXPAND
`ROSTERS /EXPAND [LEAGUE_DIR SNAP_DIR HIST_PATH]` (switch any case; no paths: C16.1 dir, snap, hist). Python
`rosters.expand(league_dir, snap_dir, hist_path) -> code`, CLI `rosters.py /EXPAND LEAGUE_DIR SNAP_DIR HIST_PATH`.
Exit 0 when anything was written, 1 when nothing (the common case: no event), 2 on error (the current MAJ unreadable or
shorter than 59771 B, a read or write failure); on 2 no file is changed. No rng, no draws, no HISTORY writes.
- mask = HISTORY bytes 12..15 (u32 LE) when HIST_PATH is readable and at least 16 B, else 0 (all AI).
- Pool: POOL1..POOL4.V20 as C6 (missing: pool_blank of the first existing team file of the current MAJ teams, sorted
  file order as C6 run()).
Steps, in order:
1. Ids (C15.3).
2. Dispersal, for each contracted stem in snapshot order: its image = the team file when it exists, else the snap dir's
   `<stem>.V20` (any case, 11735 B), else none (only the CONTRACT line). Its real players sorted by V descending, ties
   slot ascending: each goes to the lowest vacant (byte 0 == 0) pool slot of its type, POOL1 first, slots ascending,
   both halves, byte 141 = 0, line `REL <STEM> <name>`; no vacant slot: line `POOLRET <name>`. When the team file
   exists, every real player's pair in it is vacated (header unchanged) and the file is written; a missing team file is
   not recreated.
3. Draft. E = expansion teams with an id, ascending id. Sources = current MAJ teams with an id that are not in E, whose
   mask bit is clear and whose team file exists, ascending id. Each source protects its top 15 real players by V (both
   types together), ties slot ascending, fixed before the first pick. Cap per source = 2 * |E| picks in total.
   Need of an E team: pitchers while it has fewer than 10 real pitchers, batters while fewer than 15 real batters.
   Rounds: each E team in order makes at most one pick: among every source below its cap, the unprotected real player
   still on it of a type E needs, max V, ties lowest source id, then lowest slot. The pair goes to E's lowest slot of its
   type that holds no real player (write_pair; byte 141 = 0 both halves), the source slot is vacated, line
   `SIGN <E> <name> <SOURCE STEM>`. Rounds repeat until a full round picks nobody.
4. Pool signing. Rounds: each E team in order with a slot holding no real player takes the max V pool player of a type
   it has such a slot for (pool order: POOL1..POOL4, slots ascending; ties earliest), to its lowest such slot, byte 141
   = 0, pool slot vacated, line `SIGN <E> <name> pool`. Rounds repeat until a full round signs nobody.
5. Floor. In each E team: placeholders in pitcher slots ascending, keep the first max(0, 10 - real pitchers) and vacate
   the rest; batters the same with 15. Every other slot holding no real player and not a kept placeholder is vacated
   (both halves zero). The team keeps a playable 25 when the league and pool could not fill it (known gap: a kept
   placeholder then stays a player for the C6 offseason).
6. depth_rebuild(image, form none) (C6 step 7, no draws) for every E team that got at least one player and every source
   that lost one.
7. An E team that got no player is left untouched and gets no line. ROSTERS.TXT (league dir, any case; created when
   missing) gets the lines appended (CRLF), in order: per contracted stem `CONTRACT <STEM>` then its REL / POOLRET
   lines; per E team that got a player `EXPAND <STEM>`; the draft SIGN lines in pick order; the pool SIGN lines.
   Team stems upper case, names "First Last" (C6 pname).
8. Writes: every changed team file, pool file (a pool file made blank and never changed is not written), TEAMID.DAT and
   ROSTERS.TXT, each to `<path>.TMP` first, then all replaced (C6 run order and rule).

### C15.5 TONY2.BAT (amends C16.4)
`:start` becomes `:start` / `rosters /expand` / `histwr /snap` / `dynasty` / ... (the rest unchanged). ROSTERS /EXPAND's
exit code is not tested by the BAT (the next line, HISTWR /SNAP, does not depend on it). Every earlier patched form
upgrades in place; --revert restores stock.

### C15.6 Displays
- DYNVIEW team names: unchanged (stable id -> TEAMID stem -> the V20 header name, else the stem upper case). A contracted
  team whose file UTIL deleted shows its stem.
- OFFSEASON screen: the /EXPAND SIGN lines show with the free agent signings (the parser already takes SIGN lines);
  CONTRACT and EXPAND lines are skipped as unknown kinds.
- ABOUT THE MODS: after the row `START YEAR: DYNASTY SETTINGS, LEFT RIGHT.` and the empty row after it, ten rows
  (the last one empty):
  `NUMBER OF TEAMS`
  `UTILITIES > SETUP LEAGUES: NEW TEAM, THEN`
  `CLICK IT AND AN EMPTY DIVISION ROW.`
  `CLICK A PLACED TEAM TO REMOVE IT. NEW`
  `TEAMS DRAFT FROM AI TEAMS, WHICH KEEP 15`
  `EACH, THEN SIGN FREE AGENTS. PLAYERS OF`
  `A REMOVED TEAM BECOME FREE AGENTS. START`
  `THE SEASON WITH A SCHEDULE THAT FITS,`
  `ELSE GENERATED.`
  ``

### C15.7 Schedules (stock, for the record)
Start New Season lists the templates with their REQUIRED LEAGUE SETUP: 162 GAMES-26 TEAMS (7/6/7/6), 162 GAMES-28 TEAMS
(7/7/7/7), 162 GAMES(2)-26; ROUND ROBIN and GENERATED fit other counts (GENERATED: an even count per league, at most 8
a division). Not a mod setting.

### C15.8 Row cursor on a message row (amends C13.4)
On a cursor screen whose body uses the one-column message layout (COLS_SINGLE: `NO DYNASTY HISTORY YET`,
`NO SEASON LINES RECORDED YET.` and any other single message row), no row is highlighted: every row is drawn on
C_ROW_TAN. Keys are unchanged (UP / DOWN cannot move in a one-row list; ENTER finds no player entry).

## C16. Dynasty tools follow the current league (added 2026-10-12)

Will, 2026-10-12: add more leagues. Stock UTIL > SETUP LEAGUES already makes them (NEW SOURCE LEAGUE, NEW LEAGUE asks
a name and an abbreviation, COPY TEAM, # OF LEAGUES, # OF DIVISIONS; rig and browser checked 2026-10-12) and
UTIL > CHANGE LEAGUES picks the current one. The stock layout is TEAMS\<L>\<L>.MAJ plus the .V20s (shipped:
CLASSIC, NEGRO'LG). Every dynasty tool was hardwired to TEAMS\CLASSIC; from C16 on each tool works on the current
league, and CLASSIC keeps every path it had, so an existing CLASSIC dynasty is untouched.

### C16.1 The current league (Python tools/m4/league.py, C tools/m4/league.h; identical results)
- Read the file SYSTEM in the game directory (the TONY2 dir, the cwd of every tool under the BAT). Missing, or
  shorter than 1 B: CLASSIC.
- Name = SYSTEM bytes 0..7 up to the first NUL (8 bytes when there is none). Valid when its length is 1..8 and every
  byte is 0x21..0x7e and not one of `" * + , . / : ; < = > ? [ \ ] |`. a..z become A..Z. Invalid: CLASSIC.
- A valid name whose file TEAMS<sep><L><sep><L>.MAJ (relative to the game directory) cannot be opened for reading:
  CLASSIC.
- `league.current(game_dir)` -> the name (str). C: `int lg_current(const char *game_dir, char name[9])` (game_dir
  "" or "." = cwd; returns 1 when SYSTEM gave the name, 0 for the CLASSIC fallback).
- Paths, `league.paths(name, sep)` -> dict; C `lg_path(char *out, int cap, int which, const char *name, char sep)`
  returns 0 when the result (with its NUL) does not fit cap, else 1. which / key:
  - LG_DIR 'dir': `TEAMS<sep><L>`
  - LG_HIST 'hist': `TEAMS<sep><L><sep>HISTORY.DAT`
  - LG_SNAP 'snap': CLASSIC `C:<sep>DYNSNAP`, else `C:<sep>DYNLG<sep><L><sep>SNAP`
  - LG_SEASONS 'seasons': CLASSIC `C:<sep>SEASONS`, else `C:<sep>DYNLG<sep><L>`
  - LG_RET 'ret': snap + `<sep>RETIRED.DAT`
  - LG_MAJ 'maj': `TEAMS<sep><L><sep><L>.MAJ`
  The DOS tools use sep `\`; host builds use `/` (C: then is a plain relative name; host tests pass explicit paths).

### C16.2 HISTWR /SNAP and /ARCHIVE (replace the BAT's copy line and ARCHIVE.BAT)
- `HISTWR /SNAP [LEAGUE_DIR SNAP_DIR]`: defaults the current league's dir and snap. Creates SNAP_DIR and each missing
  parent directory along it (C:\DYNLG, C:\DYNLG\<L>); then copies every regular file directly in LEAGUE_DIR (no
  subdirectories, no recursion) into SNAP_DIR, overwriting same-named files, byte for byte. Files already in
  SNAP_DIR and not in LEAGUE_DIR stay. Exit 0; exit 1 when LEAGUE_DIR cannot be listed or a copy fails. Prints nothing.
- `HISTWR /ARCHIVE [SNAP_DIR SEASONS_DIR]`: defaults the current league's snap and seasons. Creates SEASONS_DIR (and
  missing parents). The slot is the first nn in 01..99 whose SEASONS_DIR<sep>Snn holds no *.MAJ (Snn missing counts as
  free); none free: nothing, exit 0. Creates Snn when missing and copies every regular file directly in SNAP_DIR into
  it (overwriting). Exit 0; 1 on a copy failure. Prints nothing. (Same result as ARCHIVE.BAT for CLASSIC, whose slots
  only ever hold CLASSIC.MAJ.)
- Defaults of the other modes come from C16.1 too: plain `HISTWR` (pre = snap, hist, ret), `HISTWR /LINES` (hist,
  seasons).

### C16.3 Other tools' defaults (used only when the command line gives no paths; explicit paths win as today)
- ROSTERS: league dir, snap, hist, ret from C16.1.
- DYNVIEW, CREATE: league dir from C16.1 (host builds with sep `/`).
- DYNASTY.EXE (blob/dynasty.asm): reads SYSTEM in the cwd and applies C16.1 (8.3 DOS names, sep `\`); the MAJ is
  TEAMS\<L>\<L>.MAJ, history TEAMS\<L>\HISTORY.DAT, the rolled files TEAMS\<L>\*.V20, RETIRED.DAT in the league's
  snap (no snap directory: skipped silently, as today). CLASSIC: byte-identical behaviour and output to before.

### C16.4 TONY2.BAT (tools/m4/rig/bat_patch.py)
`:start` becomes:
  :start / histwr /snap / dynasty / if errorlevel 1 goto rolled / goto ctl / :rolled / histwr /archive / histwr /
  rosters / dynview /offseason / :ctl / control
(only the copy line and `call archive` change). Every earlier patched form upgrades in place; --revert restores stock.
(Amended 2026-10-13, C15.5: `rosters /expand` runs first, before `histwr /snap`.)
ARCHIVE.BAT is still written (unused) so a revert to an older bundle keeps working.

## C17. Offseason draft: position and your teams (added 2026-10-13)

Will, 2026-10-13: show each ROOKIE DRAFT pick's position, and mark the teams you manage on the offseason list
phases. Python tools/m4/dynview.py is the reference; the C port dynview_c/dynview.c must render byte-identical
framebuffers.

### C17.1 The POS column (phase 2, 3/6 ROOKIE DRAFT)
- Columns become exactly COLS_DRAFT = [('#', _cx(0), 4, 'L'), ('TEAM', _cx(4), 13, 'L'), ('POS', _cx(18), 3, 'L'),
  ('PLAYER', _cx(22), 20, 'L')]; rows become 4-tuples ('#k', TEAM, POS, PLAYER) (TEAM and PLAYER as today,
  disp(team) the SIGN line's team token and the name, only narrower columns).
- POS: the drafting team's team file (the SIGN line's 2nd token, the team token; the same case-insensitive
  file lookup team_disp/team_name uses, <STEM>.V20 in the league dir). Scan record slots 0..39 in order; the
  first slot that is on (first byte of the record non-zero, like rosters.is_on) and whose
  rosters.pname(record) equals the pick name exactly (pname = First Last from the record bytes, last 12 B at
  0 then first 8 B at 12) gives POS = dynview.pos_name(rosters.pos1f(record)) (pos1 field of v20.F, byte 0x1f
  low nibble). Missing file, a file shorter than v20.HDR + v20.REC * 40, or no matching slot: POS = ''.
- Record offsets v20.HDR (295), v20.REC (143), v20.F['pos1'] (0x1f, lo) and v20._get (as rosters.py imports
  them). Each team file is read at most once per screen build.

### C17.2 Your teams marked
- Let mask be the HISTORY mask DYNASTY SETTINGS already uses (data['mask'] in Python; HISTORY.DAT bytes
  12..15 u32 LE in C, g_mask). A ROSTERS.TXT team token is managed when its ASCII upper case equals a mapped
  stem's ASCII upper case and bit tid of mask is set (tid < 32). The map from the team STEM to its stable id
  is built once per data load with the same MAJ walk settings_teams uses (teamids.teams with the league's
  TEAMID.DAT yields (tid, L, slot, stem); stem = st.split(b'\0')[0]; empty stems and stems with no V20
  file are skipped, exactly the teams settings_teams lists). Python: data['team_stems'] =
  {stem_upper_str: tid} built in load_data, draft_managed uses it. C: the g_tstem table stored next to
  g_tdisp/g_tlg by load_teams, the token compared upper-cased. Tokens with no stem match are not managed.
  Two teams may share a display name; the match is by stem, never by display.
- In the TEAM column (the first team column) of the phase 2 ROOKIE DRAFT, phase 3 TRADES and phase 4 FREE
  AGENTS rows, a managed team's cell is '*' + the display text; the cell is then cut to the column width by
  the existing cell drawing, exactly as any long cell is today. Only the first column of a trade row is
  marked: the third column stays exactly what it was before C17 (disp(b) / disp(a), no '*'). FROM columns
  are unchanged.

### C17.3 Nothing else changes
- Other screens, footers, titles, counts, ABOUT rows, key handling and the card opening are untouched.
## C18. Your teams on the season screens (added 2026-10-14)

Will, 2026-10-14: mark the teams you manage on SEASON STANDINGS, WORLD SERIES and SEASON HISTORY. Python
tools/m4/dynview.py is the reference; the C port dynview_c/dynview.c must render byte-identical framebuffers.

- A team with stable id tid is managed when tid < 32 and bit tid of the HISTORY mask (data['mask'] in Python,
  g_mask in C) is set. This is the same mask DYNASTY SETTINGS edits and C17.2 uses; a team id comes from the
  data where one exists (SEASON STANDINGS and WORLD SERIES rows carry team ids directly, so mask-bit status needs
  no stem match), and SEASON HISTORY walks the champion STEM through the C17.2 stem map (Python
  data['team_stems'], one optional argument to history_rows, existing callers keep working; C the g_tstem
  table, se's NUL-or-space cut champion stem ASCII upper cased).
- SEASON STANDINGS: a managed team's first row cell ('TEAM %d' or the MAJ display) gets '*' prepended. Division
  header rows and the blank spacer row are never starred.
- WORLD SERIES: every visitor and home row and the summary row's team cell are starred when that team id is
  managed. GAME n header rows and the SERIES TIED row are never starred.
- SEASON HISTORY: the CHAMPION cell is starred when the champion stem maps to a managed id. A champion stem
  with no mapped id is never starred even with bits set. Masks 0 render exactly as the pre-C18 screens (the
  existing parity tests do not change).
- The star lives in the cell text and is cut like every cell ('*DETROIT' may lose its tail in the narrow TEAM
  column); the tid >= 32 ids are never starred, in Python and C.

## C19. Releases on the offseason walk (added 2026-10-14)

Will, 2026-10-14: show the releases on the 5/6 phase next to the free agent signings.

- parse_rosters yields ('REL', stem, name) for `REL <stem> <name...>` lines (n >= 3 tokens, name =
  ' '.join(tok[2:])); a missing or unreadable file gives []. The phase-6 count 'PLAYERS RELEASED: %d' is
  unchanged (REL lines with 3 or more tokens).
- The phase-5 title becomes '5/6 SIGNINGS AND RELEASES' (Python OFF_TITLES and the C screen_title). Its rows,
  capped at LIST_MAX in total, are the existing free-agent SIGN rows first, then one row per REL event in file
  order: (managed_cell(data, stem, disp(stem)), name, 'RELEASED'). Columns stay COLS_MOVE. The empty phase
  message becomes 'NO SIGNINGS OR RELEASES'. C: the release row's name joins the tokens into a buffer and is
  written bounded by SLEN; no new heap allocation per row.
- The C port counts one RELEASE row per REL event with an ord of fa + rel (the free agent rows first, then the
  releases), so paging and the caps are the combined list. The rows of a token with no team file show the token
  upper cased, like every TEAM cell.

## C20. Rookie position mix (added 2026-10-14; amends the C4/P2 fill ladder)

Finding: the ladder's "remaining vacancies become DH" made nearly every fill rookie a DH (7 of 8 drafted rookies in
a 105-season league), and the C6 draft redrafts exactly these rookies. Shipped data has zero code-9 players.
- The ladder (P to 8, C to 2, each IF code 2..5 to 1, OF 6+7+8 to 4 round robin) is unchanged and cut at nvac.
- Each vacancy left after the ladder gets code REM_TABLE[draw() % 20], REM_TABLE = (0 x8, 1 x2, 2, 3, 4, 5 x2, 6,
  7 x2, 8 x2): P 40 %, C 10 %, 1B/2B/3B 5 % each, SS 10 %, LF 5 %, CF 10 %, RF 10 %, DH never. One draw per remainder
  vacancy in fill order, all before the C4 record draws of the same team; no draw when the ladder covers every
  vacancy. Python team_fill.REM_TABLE and rookie_fill.asm rem_table hold the same bytes.

## C20b. Second position (added 2026-10-14)

Will, 2026-10-14: record byte 31 carries pos1 in the low nibble and pos2 (second position) in the high nibble
(codes 0 P, 1 C, 2 1B, 3 2B, 4 3B, 5 SS, 6 LF, 7 CF, 8 RF, 9 DH, 10 OF, 11 IF, 12 O/I, 13 C/O, 14 C/I, 15 C/3).
Every generated rookie and every CREATE A PLAYER batter was written with pos2 = 0, which is P; stock data never
gives a batter pos2 = P. This amends the C4 rookie record and the CREATE record build; the blob ABI is unchanged.

- POS2_OF (the most common stock pos2 per pos1) = (0, 1, 2, 11, 12, 11, 10, 10, 10, 9), indexed by pos1 code
  0..9: P->P, C->C, 1B->1B, 2B->IF, 3B->O/I, SS->IF, LF/CF/RF->OF, DH->DH. Defined once in tools/m4/rookies.py
  (module level) and held as the 10-byte pos2_table in rookie_fill.asm and POS2_OF in create_c/create.c.
- Generated rookies: byte 31 = pos1 | POS2_OF[pos1] << 4 (the never-emitted codes 10..15 keep pos2 = 0). No rng
  draw is added or removed: the draw order and count are unchanged. In rookie_fill.asm make_rookie, the code is
  stored as cl | (pos2_table[cl] << 4); every following compare tests the position code only (the CX value), and
  the P check `byte [cs:scratch+OFF_POS] compared with 0` stays correct (P has pos2 0, so the whole byte is 0
  for P and non-zero otherwise). team_fill.fill_image keeps its `rookie[31] = (rookie[31] & 0xF0) | (code & 0x0F)`
  line: the high nibble now comes from make() and equals POS2_OF[code].
- CREATE A PLAYER: build_record (create.py and create.c) writes byte 31 = pos1 | POS2_OF[pos1] << 4 for batters;
  pitchers stay all zero. The form, screens and keys are unchanged.

## C21. CREATE A PLAYER salary and second position (added 2026-10-14)

Finding: CREATE A PLAYER stored constant salaries (109 batters, 255 pitchers) even though
build_record already fills the stat line the ratings imply, so the game's own salary
formula (ratings.salary, exact on 1185 of 1188 shipped batters) is computable at create
time. The edit screen also had no way to set the C20b pos2 nibble: every created batter
carried the default POS2_OF[pos] with no choice.
- Rule 1: build_record stores the real salary. After statline.fill(rec), salary =
  ratings.salary(rec) as u16 at record +25, batters and pitchers both (it replaces
  gen._write_salary; the wire form is ratings.salary of the finished record).
- Rule 2: the edit screen, batter and pitcher, draws 'SALARY' at (228, 110) and the value
  '%d' % salary at (228, 120), C_BLACK on the panel, below the portrait box. The value is
  derived, not stored: it is ratings.salary of the record build_record would save for the
  current form (same year byte the save uses) and updates on every key.
- Rule 3: the batter rows gain ('pos2', 'SECOND POS') right after ('pos', 'POSITION')
  (batter rows 13 -> 14, pitcher rows unchanged). form['pos2'] defaults to
  POS2_OF[form['pos']] in blank_form and default_form; LEFT/RIGHT cycles codes 1..15 as
  (pos2 - 1 + d) % 15 + 1 and shows POS_LABELS[pos2]; a POSITION change resets
  pos2 = POS2_OF[new pos]; ENTER moves to the next row like other fields. build_record
  now writes byte 31 = pos | pos2 << 4 from the form for batters (pitchers stay 0),
  which supersedes the C20b build_record line (the defaults agree with POS2_OF).
- Rule 4: the batter rows now end at y 173, so the MSG_NAME 'TYPE A LAST NAME FIRST'
  line moves from y 172 to y 175 on both screens (Python and C). Nothing else moves.
- C port: statline.h gains sl_salary with sl_salary_batter, sl_salary_pitcher, sl_era100
  and sl_pitcher_class, a line-by-line port of ratings.py's salary family in long
  arithmetic with the same & 0xffff masks; create.c gains rules 2 to 4 and uses
  sl_salary for rules 1 and 2. sl_host gains a 'salary' mode (N x 143 B records in, N x
  u16 LE salaries out).
- V20 layout unchanged: salary u16 at +25, byte 31 pos1 low / pos2 high nibble.
## C23c. DYNVIEW PLAYOFFS (added 2026-10-14)

Finding: the C23b BOXSCORE.DAT round records (flags 4, g 16..63) had no viewer. DYNVIEW gains
two screens read off those records; it writes nothing.

- Hub: MENU_ROWS gains a 12th row 'P  PLAYOFFS'; key P or p (80/112) opens (SCREEN_PLAYOFFS,
  0, 0); a click on the row gives ord('P'). Hub rows, footers (FOOTERS[SCREEN_MENU],
  TITLE_FOOTER) and every other hub key are unchanged.
- State (dynview.py, byte-exact in dynview.c): SCREEN_PLAYOFFS = 14 with cat = seasons back,
  SCREEN_PBOX = 15 with cat = seasons back * 64 + (g - 16).
- playoff_games(box, season) -> [(g, idx, b, i, stats)] of the season's flags-4 records with
  g >= 16, g ascending (sorted; the writer emits g order). 48 headers at most are kept in the
  C port's FARDATA table, streamed from BOXSCORE.DAT like the BOX screen (no whole-file
  buffer).
- playoff_rows: past the history table or with no game, one message row
  ('NO PLAYOFF ROUNDS RECORDED',) with COLS_SINGLE. Otherwise per series (consecutive games
  with the same b): a title row ('%s %s' % (('AL','NL')[L], ('DIVISION SERIES',
  'CHAMPIONSHIP SERIES')[rnd - 1]), '', '', '', ''), then per game the three rows
  series_rows makes for a WS game (GAME k with k = i; visitor and home rows with R, H, E
  from stats (vR, hR, vH, hH, vE, hE) and W on the side with more runs; the C18 managed star
  on TEAM cells of game rows and the summary, never on a header row), then the summary row
  over the series' first game's two teams with the WINS threshold 3 for rnd 1 and 4 for rnd 2
  (WINS/LEADS a-b, else SERIES TIED a-a). Columns COLS_SERIES.
- PLAYOFFS keys: LEFT/RIGHT step seasons exactly as WORLD SERIES (add to the same branch and
  to LEFT_RIGHT_SCREENS; a title click is LEFT/RIGHT), PGUP/PGDN page, title
  '%d PLAYOFFS' % year_of(hist, season) ('PLAYOFFS' with no season), footer
  'ENTER BOX  LEFT RIGHT SEASON  PGUP PGDN  ESC'. ENTER opens the box of the first game whose
  GAME row is on the current page (the nth GAME row is the nth playoff game; the season's
  first round game when no GAME row is on the page), when the season has one.
- PBOX: rows are box_rows' layout for the records of (season, g) excluding the flags-4 header,
  at most BOX_RECS_MAX, the two teams from the header's idx; message row 'NO BOX SCORE
  RECORDED' without a header or without any other record. Title '%d %s %s GAME %d' % (year,
  ('AL','NL')[L], ('DS','LCS')[rnd - 1], i), 'PLAYOFF BOX SCORE' without a season or header.
  Footer 'LEFT RIGHT GAME   PGUP PGDN   ESC PLAYOFFS'. LEFT/RIGHT step to the previous/next
  round game of the season by g over playoff_games; RIGHT past the last round game opens the
  first WORLD SERIES box of the season that has one ((SCREEN_BOX, 0, cat * 64 >> ... ) =
  (SCREEN_BOX, 0, (cat >> 6) * 8 + g0)); LEFT on the season's first WS game with a record, when
  the season has round games, opens the last round game's PBOX ((SCREEN_PBOX, 0,
  (cat >> 3) * 64 + lastg - 16)); ESC returns (SCREEN_PLAYOFFS, 0, cat >> 6).
- The existing WORLD SERIES and BOX SCORE screens are unchanged otherwise; their filters stay
  (season, g) with g < 7.
- C port parity (tools/m4/dynview_c/dynview.c, gcc host build with -Werror): the hub with the
  12th row, PLAYOFFS pages 0 and 1 and empty seasons, PBOX first game and after RIGHT, the WS
  box after RIGHT past the last round game (and back), the managed star, a 48-header season,
  headers out of g order, and 25 random key walks all match Python's framebuffer byte for byte.
