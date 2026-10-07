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

## C2. HISTORY.DAT v1 (league dir, TEAMS\CLASSIC\HISTORY.DAT), little endian

Header, 32 B:
- 0 u8 done flag (same meaning as P1), 1 u16 rng word (same as P1), 3 u8 version = 1
  (a legacy 4-byte P1 file has no byte 3 or 0 there: upgrade in place keeping bytes 0..2)
- 4 u16 seasons recorded, 6 u16 player entries, 8..31 zero
Season table at offset 32: 64 entries x 128 B (8192 B). Entry for season n (1-based) at 32 + (n-1)*128:
- 0 u16 season_no; 2 u8 champion id; 3 u8 runner-up id (league-global ids, 0xff = unknown)
- 4 8 B champion team stem, 12 8 B runner-up stem (latin-1, NUL padded)
- 20 u8 al_pennant id, 21 u8 nl_pennant id, 22..23 zero
- 24 28 x (u8 W, u8 L) indexed by league-global id 0..27 (NL = slot + 16); unused ids 0,0
- 80..127 zero (reserved for awards, P4)
Champion decode (one sample, season2_end: "PHILADELPHIA over CLE 4-2"): AL block S=0x21d, NL block S=0x758c;
WS winner = byte at AL S+0x3da; al_pennant = AL S+0x3d9; nl_pennant = NL S+0x3d9; runner-up = the pennant winner
that is not the WS winner. 0xff anywhere means unknown.
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

Update order at rollover (Python reference `history.record_season(league_dir, hist_path, season_no, retirees)`),
run BEFORE the P1 rollover mutates anything, then `history.mark_retired(...)` after it:
1. read MAJ standings, champion; write the season entry.
2. league pass over every active record i in 0..39 of every V20 (sorted order) using the SEASON half (i+40) stats
   and roster-half bio/ratings: accumulate league totals for C3.
3. per player: find or append the entry, add season stats, set status 1, ages, seasons, pos; season WAR10 per C3;
   career WAR10 += season; update top-7 and JAWS10.
4. after rollover: retirees get status 2, then the HoF test (C3). status 3 + HoF season if it passes.

## C3. WAR and Hall of Fame (integer, per season, the season half stats)

Batters (pos1 != 0). ab, h, d(2B), t(3B), hr, bb summed L+R; sb, cs, runs; g = season games; s1 = h - d - t - hr; pa = ab + bb.
- lw100 = 47*s1 + 78*d + 109*t + 140*hr + 33*bb + 20*sb - 41*cs - 27*(ab - h)
- league: L_lw = sum lw100, L_pa = sum pa, L_runs = sum runs, over batters with pa > 0
- bat100 = lw100 - (L_lw * pa) / L_pa
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
