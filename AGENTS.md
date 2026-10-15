# tlrb2 builder card

Full project rules: CLAUDE.md (read it too; this card does not repeat it). Current state: STATUS.md.

## 1. What this is
Full reverse engineering of Tony La Russa Baseball II (1993 DOS) plus in-game mods ("Dynasty" mode: season history,
offseason, create-a-player, league tools). PUBLIC GitHub repo, so no game files, no game data, no secrets.
Python is the reference implementation; the 16-bit C/asm ports that run inside the game must match it byte-exact.
The mods are served in the browser (js-dos) at https://tlrb2.ecbtx.com (basic auth, returns 401 without credentials).
Deploy target: a private host reached by ssh, driven only by `web/deploy.sh`. There is no Railway, no DB.

## 2. Install
- Python 3.14 with `pytest` and `unicorn` (both present on this machine). No requirements file, no venv.
- Tools used by some tests: `nasm`, `gcc` (host harness builds go to tmp dirs), Open Watcom at
  `/mnt/nvme/tools/openwatcom`, `dosbox-x` at `/mnt/nvme/src/dosbox-x`.
- Game data (never copied into the repo) lives under `/mnt/nvme/tlrb2/`. See section 9.

## 3. Run locally
- The mods are libraries and DOS programs, there is no server to start for the game logic.
- Play the real install: `scripts/launch.sh live`. Headless test rig: `scripts/launch.sh work headless` (Xvfb :98).
- Browser build: `web/server.py` serves the bundle; `web/build_bundle.py` builds it. Do not bind ports 8765, 8766,
  8794, 8795, 8799 (live services); pick a free high port.
- Rebuild the asm blob: `python3 tools/m4/blob/build_dynasty.py` (nasm, BITS 16, CPU 386).
- Rebuild a C port (Open Watcom 16-bit): `python3 tools/m4/create_c/build_create.py`, `tools/m4/dynview_c/build_dynview.py`,
  `tools/m4/histwr/build_histwr.py`, `tools/m4/rosters_c/build_rosters.py`. Host harnesses (gcc) are built by the tests.

## 4. Test (commands run on 2026-10-15)
- Whole M4 suite (what CLAUDE.md says): `python3 -m pytest -q -p no:cacheprovider tools/m4`
  Full-run wall time was not measured today (see the notes file); the unicorn and DOSBox parity tests are the slow part,
  so run the whole thing once at the end, not per edit.
  Tests needing `/mnt/nvme` data or dosbox-x skip when it is absent; that is expected and not a failure.
- One file (all verified): `python3 -m pytest -q -p no:cacheprovider tools/m4/test_history.py` (22 passed, 3.4 s);
  `test_rollover.py` (18 passed, 1.1 s); `test_realign.py` (28 passed, 1.4 s); `test_league.py` (46 passed, 2.1 s).
- One test: append `::test_name`, or use `-k name`.
- Holdout suite (synthetic, offline, no game data, 14 tests, about 1 s):
  `cd tools/m4 && python3 -m pytest -q -p no:cacheprovider holdout`
  (also works from the repo root as `python3 -m pytest -q -p no:cacheprovider tools/m4/holdout`).
- Run serially. Do not pass `-n`: under pytest-xdist the workers race to build the same C object (`dynview.o`)
  at collection and the run dies before any test. Never weaken, skip or delete a parity test.
- Other test roots: `tools/*.py` (assets, dcl, stadium, replay) and `web/test_*.py`; `python3 -m pytest -q tools web`.

## 5. Lint / typecheck
There is no lint or typecheck config in the repo. `ruff` ad hoc reports about 356 errors in tools/m4 on main
(mostly F405 star imports, E402, E702, F401, E741), so the code is not lint clean. Do not add new ones: keep your
new files `ruff check` clean. mypy is not used. `menu_patch.py:56` emits a pre-existing SyntaxWarning; ignore it.

## 6. Deploy and verify
- `web/deploy.sh [--force]` only. It copies the built EXEs into the web stage, patches, builds the js-dos bundle,
  backs up bundle and saves, rsyncs, restarts the unit and fetches the bundle back over HTTPS to compare sha256.
- It needs `~/.config/tlrb2/deploy.env` and `~/.config/tlrb2/web_login` (never read, print or copy them).
  Builders do NOT deploy. The orchestrator runs it after merge.
- Verify: the script's last line reports the served sha matching the built sha. Then a Playwright walk of the menus.
  `curl -s -o /dev/null -w '%{http_code}' https://tlrb2.ecbtx.com/` must be 401 (auth on), not 5xx.
- Cloudflare returns 403 to the default Python-urllib User-Agent: scripts that call the site set their own.

## 7. Migrations
No database. The "migration" equivalent is the V20 / MAJ / HISTORY.DAT byte layout (see section 8 and
`notes/FORMATS.md`): offsets are fixed, writers must be isolated (touch only their own bytes) and size-gated.

## 8. Layout map
- `tools/v20.py`: V20 team file reader/writer (11735 B: 295 B header + 80 x 143 B records; 0..39 roster, 40..79 season).
- `tools/maj.py`: MAJ league file (59771 B).
- `tools/m4/` : all Dynasty code. Python reference modules sit next to their C ports.
- `tools/m4/rollover.py` + `rookies.py`: aging, retirement, draft (xorshift16 `Rng`, contracts C1..).
- `tools/m4/history.py`: HISTORY.DAT (32 B header, 64 x 128 B season table, 160 B player entries from 8224).
- `tools/m4/create.py` + `create_c/`: CREATE A PLAYER (Python reference + C port + `build_create.py`).
- `tools/m4/dynview.py` + `dynview_c/`: DYNASTY MODE screens (framebuffer parity tests `test_dynview_c13_c.py`).
- `tools/m4/league.py`/`league.h`, `realign.py`/`realign.h`, `teamids.py`/`teamids.h`: league files, 3-division
  realign, team ids (never compute L*16+slot yourself, go through teamids).
- `tools/m4/menu_patch.py`, `patchlib.py`, `rig/bat_patch.py`: patch a COPY of the game install (idempotent, refuse live paths).
- `tools/m4/blob/`: asm blob (`dynasty.asm`, `build_dynasty.py`, built `DYNASTY.EXE`); unicorn parity in `test_blob_unicorn.py`.
- `tools/m4/rig/`: DOSBox rig (Xvfb :98) and its helpers; launch only through these scripts.
- `tools/m4/holdout/`: synthetic regression tests for the riskiest writers (section 4).
- `notes/M4_CONTRACT.md`: locked integer-math contracts (law). `notes/M4_DESIGN.md`, `FORMATS.md`, `RE_NOTES.md`: background.
- `web/`: js-dos bundle builder, server, `deploy.sh`. `scripts/`: launch, snapshot and rig shell scripts.
- `ghidra_scripts/`, `conf/`: RE helpers and dosbox configs. Do not run Ghidra from a builder task.

## 9. Landmines
- Public repo: never commit game EXEs, .V20, .MAJ, .ANM, .SCR, images, or paths to private data. Our own builds
  (`tools/m4/blob/DYNASTY.EXE`, the C-port EXEs, `*.bin`) are the only binaries allowed. Fixtures are `tmp_path` only.
- Game data for skipped tests: ISO `/mnt/nvme/tlrb2/iso`, work install `/mnt/nvme/tlrb2/work/c/TONY2`, pristine copy
  `/mnt/nvme/tlrb2/pristine/TONY2`, snapshots `/mnt/nvme/tlrb2/snaps`. In the sandbox these are absent and skip.
- C12 team ids: a 3-division league compacts engine ids and uses slots 16..23. Use `teamids.py`/`teamids.h`.
- A new season on the generated schedule (every 3-division league) starts at day byte 0x00, not 0x07.
- C15: a team file with only `EMPTY` placeholders or vacant slots is an expansion team; `ROSTERS /EXPAND` drafts for it
  at the next BAT start. Fixtures wanting an untouched league must not leave a placeholder-only team in the MAJ.
- Rig BAT flow: every program switch (MAIN to UTIL, MANAGE, BACK, frontend PLAY) passes through `:start`, so
  `ROSTERS /EXPAND` runs on each one. Stock UTIL started by hand from the DOS prompt shows a black screen (needs the
  frontend handoff); reach it via MAIN > UTILITIES. To capture a pre-/EXPAND state on a throwaway install, set a flag
  file in the `:util` route and copy the league dir at `:start` when it exists.
- DOSBox: launch only through the rig scripts (Xvfb :98 by default; TLRB2_RIG_DISPLAY and TLRB2_RIG_LOGS select a
  second rig display and log dir so two rigs never share a pidfile or screen; SDL_VIDEODRIVER=x11, WAYLAND_DISPLAY unset); an agent shell
  inherits DISPLAY=:0 and would open on Will's desktop. Kill your session when done. Rig typing: `rig.key` is ignored
  by DOSBox-X, use `rig.type_text` or `xdotool key`. A stock text field drops the first key right after the focus click.
- `HISTORY.DAT` season writes are guarded by `season_no <= SEASON_COUNT` (64); a season past 64 must never land on the
  player table at offset 8224. Keep that guard.
- js-dos 8.5.3 writes bundle entries after plain initFs files, so an initFs file under a path the bundle also has is
  silently overwritten. Overlay with a one-entry stored zip (index.html storedZip).
- Browser walks need a 6G capped limit; at 3G the wasm build traps with "RuntimeError: unreachable" (looks like a black screen).
- Asm: nasm, BITS 16, CPU 386. Signed division truncates toward zero, signed `>>` is arithmetic.
- No em or en dashes anywhere (code, comments, notes, commit messages).

## 10. Never touch
- Will's live install `/mnt/nvme/tlrb2/c` and the pristine copy; experiments go to `/mnt/nvme/tlrb2/work/c/TONY2` or tmp dirs.
- `~/.config/tlrb2/*` (deploy and web login) and anything credential-like.
- Parity tests: never skip, weaken or delete one to get green. Fix the port, not the test.
- Integer contracts in `notes/M4_CONTRACT.md`. If a contract looks wrong, stop and report; do not silently deviate.
- Other worktrees under `.claude/worktrees/` (other builders run there) and git history (no reset, rebase, clean, push).
- `web/deploy.sh` runs, `launch.sh live`, Ghidra projects, and any large file under /home (use /mnt/nvme).

## Appending to notes/M4_CONTRACT.md
New behaviour that Python and C must share gets its own section at the END of the file, never edited into an old one:
`## Cnn. TITLE (added YYYY-MM-DD)`, where nn is the next unused number (`grep -n '^## C' notes/M4_CONTRACT.md`;
sections are not in numeric order). State exact integer math, table order, draw order, footer text, and which tests
pin it. Reference it from the Python docstring and the C port. Change an old contract only as its own reviewed step.
