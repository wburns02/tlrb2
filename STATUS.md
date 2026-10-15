# tlrb2 STATUS (2026-10-14, corrected 2026-10-15 01:50 CT)

Builder card: AGENTS.md. Project rules: CLAUDE.md. Contracts: notes/M4_CONTRACT.md.
Unverifiable claims are marked "(unverified)".

## Corrects an old claim
"M4 awaiting Will review" is stale. M4 (Dynasty mode) is built, merged to main, deployed to the browser build
and is in a numbered improvement loop (items C23..C59, one worktree and branch each). Nothing is blocked on a review.

## What is live
- Site: https://tlrb2.ecbtx.com answers HTTP 401 without credentials (curl, 2026-10-15). Auth is on, the host is up.
- Default branch: origin/main at `d0e6d0d` (2026-10-15 01:34, "C30: ERA text from the 32-bit key ..."). It was
  `f9e861f` when this lane started and `e039f26` when the worktree was branched.
- Last deploy: `/mnt/nvme/tlrb2/work/improve5/deploy_c23.log` shows the 2026-10-14 22:30 CT deploy ending with
  "live ... serves b6d46c314030554c, 401 without auth"; the improve5 progress log records a later deploy at 00:30
  "through C46" (commit `f7016388` in that log). The local bundle `/mnt/nvme/tlrb2/web/site/tlrb2.jsdos` is dated
  2026-10-15 00:29. Which commit the host serves right now was not checked with credentials (unverified).
- Features on main (per `git log` and notes/M4_CONTRACT.md): DYNASTY menu on MAIN/BACK/MANAGE/UTIL, season history,
  Hall of Fame, leaders, milestones, awards, standings by division, playoffs and box scores (C23c), CREATE A PLAYER
  with point budget, auto-fill and random name (C31, C34, C37), player card postseason line (C26), 3-division realign,
  team ids (C12), Lahman 1998-2012 data (C46), rollover/offseason, 67 new faces, modern stadiums.
- Not shipped to the host yet: everything merged after the last deploy, including C30 (just merged), C29, C40 and C50
  if they landed after 00:30 (the progress log says "redeploy after this batch"). Treat main as ahead of live (unverified).

## In flight (2026-10-15 01:50)
Builders (GLM-Flash via Hive) and the brain/orchestrator work in per-item worktrees under `.claude/worktrees/`:
- Not yet merged to main: c53 (HoF position filter, tip `94de0e2`, gate round 2 running, 3 dirty files), c54
  (LEADERS active-only toggle, tip `07a954f`, merged with main, awaiting gate).
- Just merged: c30 (post-season leaders, `d0e6d0d`).
- Worktrees at the main tip with a task still open or just closed: c56 (DYNVIEW HISTORY row cursor, spec C56.md), c58,
  c59 (specs C58.md, C59.md). Older merged worktrees (c23b, c23c, c26..c29, c31, c34..c40, c44, c46, c50) remain on disk.
- Plans and per-round logs: `/mnt/nvme/tlrb2/work/improve5/` (`progress.md`, `plan*.md`, `tasks/`, `holdC*`).
- Do not touch these worktrees. This scaffolding lane (branch burn/scaffolding) only adds AGENTS.md, STATUS.md and
  `tools/m4/holdout/`.

## Known broken or rough
- No lint or typecheck config; ruff reports about 356 errors in tools/m4 and about 755 across tools and web (mostly
  F405, E402, E702, F401, E741). Not enforced anywhere.
- `tools/m4/menu_patch.py:56` emits a SyntaxWarning (invalid escape) on import. Harmless, pre-existing.
- DOS far-data budget: a 59 KB array broke DOS parity while the host build passed (240-entry cap passes). Specs now cap
  new C arrays at about 2 KB.
- The merge helper `keepboth.py` is unsafe on dict, tuple and if-chain conflicts (duplicate keys, older value wins).
  Read code hunks by hand.
- Full-suite wall time and pass counts for `python3 -m pytest -q tools/m4` are not recorded here; see the notes file.
- Tests that need `/mnt/nvme/tlrb2` data, fonts, dosbox-x or Open Watcom skip when those are missing.

## Awaiting Will
- Redeploy: run `web/deploy.sh` after the current batch (needs `~/.config/tlrb2/deploy.env`; only the orchestrator or
  Will runs it). Then a browser walk of the new screens.
- Decide whether items C48 and C49 (release breaks header lists without depth_rebuild in C) and C51 (V20 reads in the
  C port) are worth building; the progress log defers them.
- Nothing else is known to be waiting on Will for this repo (unverified).
