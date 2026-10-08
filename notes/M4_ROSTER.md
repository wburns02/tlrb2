# M4 roster management: research and proposed design (2026-10-07)

Status: RESEARCH + PROPOSAL, questions answered 2026-10-07 (section 5). Not built or contracted yet (C6 next).

Why: TLRB2 was a single-season game, so it never needed roster turnover. M4 adds aging and retirement, but under
C1 only 6 to 19 of ~1100 players leave per season (about 1%), all by age. Real baseball loses ~20% a year, mostly
young washouts. Without a roster system the league fossilizes: a weak 26-year-old holds his slot for ten years.

## 1. Calibration data (computed from Lahman, Chadwick baseballdatabank mirror, MLB 1970-1990)

Computed by us (script: scratchpad attr.py, method: player is "gone" if he has no MLB appearance in year N+1;
baseball age = year - birth year, minus 1 if born July or later; PA = AB+BB+HBP+SH+SF; a player is a pitcher in a
season if he pitched and his IP outs >= his PA).

- 19,053 player-seasons. 19.6% do not appear in MLB the next year. Of those who return, 18.9% are on a different
  team. About 907 players a season (about 35 per team) and 140 debuts a season.
- Career length (debut cohort 1970-1980): mean 6.6 seasons, median 5, 17% one-season careers.
  Final-season age: median 28, quartiles 26 / 28 / 32. Most careers end young.
- P(gone next year) by age: 22-24 about 16%, 25-30 18-21%, 31-34 21-22%, 35 28%, 36 29%, 37 35%, 39+ ~38%.
  Age matters much less than playing time:

| age band | low playing time | mid | regular |
|---|---|---|---|
| <= 24 | 27% | 13% | 2% |
| 25-29 | 47% | 16% | 2% |
| 30-33 | 61% | 20% | 3% |
| 34+ | 75% | 30% | 7% |

  (batters: low < 100 PA, mid 100-399, regular 400+; pitchers: low < 30 IP, mid 30-99, regular 100+)

  Reading: regulars almost never vanish, even old ones. Fringe players vanish fast, faster as they age. That one
  table is the core of a realistic release rule. Note "gone" includes demotions to the minors, which is what our
  15 reserve slots stand for.

Quoted, not verified by us: the 1976 Seitz decision ended the reserve clause (players free after one renewal year),
salary arbitration from 1974, amateur draft since 1965 in reverse standings order, Rule 5 draft (a pick must stay
on the big-league roster all season or be offered back). Sources: en.wikipedia.org/wiki/Seitz_decision,
en.wikipedia.org/wiki/Major_League_Baseball_draft, mlb.com Rule 5 history.

## 2. What other games do

ZenGM (open source, github.com/zengm-games/zengm, baseball variant; brain checked the starred items in source):
- *Value = blend of current and potential by age: 70% potential at 19, 55% at 23, 30% at 25, ~0 from 28, then a
  small age discount (0.95 current at 28 down to 0.90 past 38). player/valueCombineOvrPot.ts.
- *Cuts: when over the roster max, release the lowest-value players, but never below the minimum count at a
  position. team/checkRosterSizes.ts dropPlayers.
- *Free agency: teams in random order, each skips the round with p = 0.5 (baseball), else signs the best free
  agent it can afford; user team skipped. freeAgents/autoSign.ts.
- Retirement: old age, or a free agent nobody signed for a year retires. Depth chart: greedy best player per
  position with a primary-position bonus, then pairwise swap passes. Draft: pick by team-rating gain plus a small
  value term. Contracts: linear in value between min and max. (Reported by the research agent, not re-checked.)

ClaudeBall (~/ClaudeBall, our own TypeScript sim; found by the code audit):
- Retirement table: 0% before 37, 10% at 37, 25% at 38, 40% at 39, 60% at 40, +15%/yr after, cap 90%, work ethic
  cuts it up to 30%. src/engine/player/DevelopmentEngine.ts.
- Trade value = rating average x position weight (C 1.15, SS 1.12, CF 1.10, P 1.08, 2B/3B 1.05, RF 1.00, LF 0.98,
  1B 0.95, DH 0.88) x age factor (1.00 at 22-29, 0.92 at 30-31, 0.80 at 32-33, 0.65 at 34-35, 0.48 at 36-37) +
  control bonus for young players. AI accepts within 5 points; stars (70+) only for a player within 15.
  src/engine/gm/TradeEngine.ts, src/engine/season/AITradeManager.ts.
- Contract length by age: 35+ 1 yr, 32-34 up to 2, 28-31 up to 4, younger up to 7. Salary ~ value^2.5.
  src/engine/gm/ContractEngine.ts. Waivers: AI releases sub-40 players, claims 45+. src/engine/gm/WaiverWire.ts.
- Built: draft, free agency, waivers, trades, contracts, AAA. Stubbed: GM personalities, auto depth chart, A/AA.

Commercial sims (research agent, sourced):
- OOTP: biggest documented AI failures are free agency (AI spends its budget on 1 to 3 stars, then fills with
  junk; good free agents left unsigned) and trades (lopsided or incoherent deals, waiving players it just traded
  for). OOTP 27 rebuilt trade AI around "what do we shop, what do we need". operationsports.com, OOTP forums.
- Baseball Mogul: trade value = projected wins above replacement over the contract, adjusted by team need,
  contender vs rebuilder, star scarcity, salary. files.sportsmogul.com/help/TradeSettings.html
- Super Mega Baseball 3: deliberately small franchise mode: one-year contracts, everyone re-signs or retires each
  offseason, procedural free agents, a salary cap that forces keep/release choices. news.xbox.com 2020-05-21.
- Action PC Baseball "Legacy" mode: roll to the next season with aging, retirement, and a new rookie class: the
  closest classic-DOS analog to what M4 does.
- Football Manager: AI squad building fails when it stops pursuing replacements, so AI teams decay over decades.

Lessons that matter here:
1. Release by playing time and value, not age (Lahman table). This is the missing piece.
2. Keep each AI step dumb and bounded. The famous failures (OOTP free agency, trades) come from open-ended
   optimizers. Deterministic orders (reverse standings) beat random orders for us anyway (byte parity).
3. Free agency without an economy works (SMB3). Money is optional.
4. Trades are the riskiest piece. Ship last, small, and capped per team.
5. Measure long-run balance (talent spread across teams over 30+ simulated seasons) before locking constants.

## 3. What TLRB2 already gives us (from FORMATS.md / RE_NOTES.md)

- Roster = 40 records: active 25 (10 P + 15 B) and 15 reserves (6 P + 9 B), team header +222..+236. The reserves
  are our minor league. Lineups (4 sets), bench, rotation live in the header (+122..+221).
- Record byte 22 = experience (years with games > 0): service time for free. Byte 25 = salary (game formula,
  109..9999). Bytes 141-142 are zero in every record: candidate storage for contract years (verify the game never
  reads them).
- DRAFT.EXE has per-team GM profiles: 7 weights (+237..+243) and 5 presets. Every CLASSIC team uses preset 0.
  Category labels not decoded yet (profile2.scr). These are built-in AI GM personalities we can reuse.
- Season half (records 40..79) still holds last season's games, PA, IP at rollover time: the playing-time input.

Gap found while researching: the C4 rookie fill drops a rookie into the vacated slot, so he inherits the
retiree's lineup, bench, rotation, and active/reserve place even at a different position. Any roster step must
end with a full depth rebuild.

## 4. Proposed offseason pipeline (all inside DYNASTY's roll, deterministic, one rng stream)

Order: 1 age/progress/retire (C1, exists), 2 value, 3 release, 4 free agency, 5 draft, 6 trades (later),
7 depth rebuild. Steps 3 to 7 are new.

2. Value (integer). V = position-weighted rating composite (the game's own ratings; ClaudeBall position weights),
   blended toward a potential estimate for young players with ZenGM's age table (fixed point, x/256). Plus
   playing time from the season half as the "is he used" signal.
3. Release. Per team, rank by V within position group. Protected: the best N at each position (2 C, 1 per IF
   spot, 4 OF, 5 SP, 4 RP), and first-two-year players in the reserves (an "options" analog). Everyone else rolls
   against the Lahman table (age band x playing time), scaled by how far below the team's replacement line he is.
   Target: 15-20% of the league moving per season, matching 1970-90. Released players go to the free-agent pool
   (stats and history kept; HISTORY marks "released", not retired; HoF still possible).
4. Free agency. Pool = released players (+ veterans who "test the market", see era rules). Teams pick in reverse
   standings order, one player per turn, by need (empty position slot first, then biggest V gain), until 40.
   Unsigned pool players retire after one offseason (ZenGM rule). The pool lives in a sidecar file (not *.V20,
   DYNASTY rolls every V20), for example FREEAGT.DAT in V20 record format.
5. Draft. Today's C4 rookie class goes into the pool's draft section instead of straight into vacant slots.
   Teams pick in reverse standings order using their DRAFT GM profile weights, rookies go to the reserves.
   This replaces the direct fill, gives worse teams better rookies, and reuses the stock personalities.
6. Trades (phase 2). AI-to-AI only, a few per offseason: a team with a surplus at one position and a hole at
   another swaps with a team in the opposite state, values within ClaudeBall's 5-point band, stars protected.
   Real data says 18.9% of returners change teams a year, but free agency alone gets most of that movement.
7. Depth rebuild. ZenGM genDepth style: best player at each position (primary position bonus), DH, bench by V;
   rotation = top 5 SP by V, closer = best RP; 25 active = 10 P + 15 B by V, rest reserves; all 4 lineup sets
   (vs L/R, DH/no DH) using the platoon splits the V20 already stores.

Era rules (Will?): the CLASSIC league starts in the 1970s. Option: follow the real calendar. Before 1976 the
reserve clause holds (no veteran free agency, only releases feed the pool); from 1976 players with 6+ years of
service (byte 22) whose contract ends enter the pool. Contracts: length by age (ClaudeBall table) stored in bytes
141-142 if they prove unused, else no contracts and a per-year "tests the market" roll for 6+ year veterans.

Money (Will?): the game already computes salary. Simplest: no payroll limit (SMB3 style). Next step: soft budget
by market size, which needs a team revenue number we do not have.

## 5. Questions for Will (answered 2026-10-07, answers and resulting decisions at the end of this section)

1. Your own team: (a) left alone (you manage it, the AI only acts on others), (b) AI-managed like everyone else,
   or (c) AI suggestions you accept or refuse on a new screen. Recommendation: (a) for v1, with your released or
   unsigned players visible in a report. Note the free-agent pool and draft need some way for you to pick; stock
   DRAFT.EXE already has a human draft UI.
2. Era rules: follow the real calendar (reserve clause, then 1976 free agency) or one rule set throughout?
3. Trades: in v1, later, or never for AI-to-AI?
4. Money: ignore payroll, or add budgets?
5. Turnover target: match 1970-90 (about 20% of players gone per year) or something gentler?

Answers: 1 left to the manager, 2 both as an option, 3 trades in v1, 4 ignore money, 5 real life.

Decisions that follow (brain):
- The game has no "human team" flag: league games are all simulated by BACK and the user picks which to play. So
  DYNASTY keeps its own managed-team mask in the HISTORY.DAT header (bytes 10..31 are zero today): bytes 12..15 =
  u32, bit k = MAJ team slot k. 0 = no managed team (all AI). Set by a DYNASTY settings screen (T5 scope); until then
  by a tool. A managed team: never releases, never signs from the pool, never trades. Its vacancies still get its
  draft picks in standings order, chosen by its own DRAFT GM profile (the stock Draft screen already lets the
  manager set it), and the new players go to its reserves. Its depth chart is only repaired (a lineup, bench or
  rotation slot that lost its player gets the best eligible replacement), never rebuilt.
- Era byte: header byte 10. 0 = real calendar (default), 1 = reserve clause throughout, 2 = free agency throughout.
  Calendar year = record byte 21 + 1870 (the season year the rollover already maintains).
- Turnover is measured on the active 25: the Lahman "gone" rate (out of MLB next year) maps to "not on any active
  25 next season", which in our world means released to the pool, demoted to reserves, or retired. The 40-man
  organization turns over less.
- Trades v1 are AI to AI only. Offering trades to the manager is later (needs a screen).

## 6. How to validate before building

- Offline 50-season run in Python: the reference pipeline plus a crude season model (team strength from ratings to
  wins, playing time from the depth chart). Track talent spread across teams, average age, roster churn, and how
  long stars stay. Tune constants until it looks like 1970-90 MLB, then lock the contract (new section C6).
- Then the usual: Python reference, asm port with byte parity, real-game 5-season gate.

## 7. R2 validation result (2026-10-07, tools/m4/sim50.py, 50 seasons, seed 8230, era 0)

Targets recomputed from Lahman 1971-90 with the same definition sim50 uses: active set = the top 15 batters and
10 pitchers by playing time per team-season (the 25-man roster). All-appearing numbers in brackets.

| metric | locked C6 | target | stock T (pre-R2) |
|---|---|---|---|
| turnover (active last season, not this) | .218 | .216 [.194] | .106 |
| team_change (active both, other team) | .170 | .210 [.243] | .066 |
| career length mean / median | 12.3 / 13 | 7.0 / 6 [7.2 / 6] | 13.1 / 14 |
| one-season careers | .051 | .181 [.162] | .037 |
| cohort age first / last active | 22 / 34 | 24 / 30 | 22 / 33 |
| final active age median | 28 | 28 | 29 |

What moved what (grid under /mnt/nvme/tlrb2/sim50/tune):
- MKT drives team_change: 24 -> .07, 64 with REL x2 -> .17-.18. BAND and NEED barely matter.
- Turnover was stuck at .11-.13 under every T setting and under rating noise up to 96/256 (the permanent
  `--noise` random walk), because depth used S alone and S is stable year to year, so the same 25 kept their
  jobs. A per-season form draw on the depth comparison (FORM_A, a hot spring, a slump, a manager's hunch) is the
  missing piece: A 8 -> .170, 16 -> .221, 30 -> .261. Locked at 16. Form also feeds playing time, so marginal
  players drop to the low PT class and the existing release table finishes the job.
- Aging variants (decline from 30, retire from 31, decline x1.5 with form on) cut careers only to ~10.5.
- A youth seasoning penalty on depth moved entry age 22 -> 24 but did not shorten careers.

Accepted gap: careers run ~12 seasons against a real 7, and one-season careers are rare. That is structural: a
team file holds 40 players and there are no minor leagues, so the only replacement pool is the team's own
reserves plus 4 pool files, all long-tenured. Real MLB pulled from thousands of minor leaguers, most of whom got
one or two seasons. Closing it needs a feeder system (a later idea), not a constant. Aging (C1) is left as is so
DYNASTY's asm does not change for R2; the B1 dev trait (C1b) is the next lever on the age curve.
