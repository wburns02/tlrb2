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
