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
  2 * range + arm, then max fp1000 = ((po1 + a1) * 1000) / (po1 + a1 + e1) (1000 if the denominator is 0).
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
Known v1 gaps: per-season Gold Glove and Silver Slugger winners are only kept as career counts.

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
records are not listed (about 200 seasons at the observed 20 to 35 records a season). HISTORY.DAT has no cap (entries are read one
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
| DYNASTY MODE | 8 | 8 | `:dynmenu` | `dynview /menu`: the hub (history, HOF, leaders, milestones, review, offseason, settings, about) |
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
has eight rows (7 DYNASTY SETTINGS, 8 ABOUT THE MODS) with or without a recorded season.

DYNASTY SETTINGS edits the C2 header fields that had no UI: byte 10 era mode (ENTER cycles REAL CALENDAR (0) ->
RESERVE CLAUSE (1) -> FREE AGENCY (2) -> REAL CALENDAR; any other value shows RESERVE CLAUSE and goes to FREE AGENCY)
and the u32 managed-team mask at 12..15 (one row per team of the league's MAJ, YOU MANAGE / AI MANAGES). Each ENTER
writes only those bytes; a missing HISTORY.DAT is created as 32 zero bytes first, a shorter one zero-extended to 32.
The next roll reads them (C6). ABOUT THE MODS is three fixed pages describing every mod.

CREATE A PLAYER (CREATE.EXE, Python reference tools/m4/create.py): TEAM list (MAJ order, AL then NL), SLOT list (the
team's 40 roster slots, P1..P16 pitchers, B1..B24 batters), EDIT form (names, position, hands, age, ratings, face with
the portrait drawn; typed letters are stored upper case like every stock name, since the LARGE font has no lower
case glyphs), CONFIRM when the slot is named, DONE. The save writes two 143-byte records into the team V20 in
place: roster record s and season record s + 40, built like a C4 rookie (stat constants, salary, exper 0 consist 2)
with the chosen fields and ratings and no random draw; the season half is the record with the season stat offsets
zeroed. No point budget, salary not shown. The new player takes the replaced player's lineup and staff spots
unchanged (no repair pass), and the replaced player leaves the league (not added to any pool or history).

