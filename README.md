# Tony La Russa Baseball II: full reverse engineering

Goal: decode the game completely and mod it from inside the game (no companion apps). Set up 2026-10-06.

## Layout

| Path | What |
|---|---|
| `~/tlrb2/` (git) | scripts, tools, Ghidra scripts, notes. Small files only. |
| `/mnt/nvme/tlrb2/iso/TONY2V13.iso` | CD image (v1.3 CD), mounted as D: |
| `/mnt/nvme/tlrb2/c/TONY2` | live install (for playing). Treat as Will's. |
| `/mnt/nvme/tlrb2/work/c/TONY2` | work install. All experiments and patches go here. |
| `/mnt/nvme/tlrb2/pristine/TONY2` | read-only pristine copy of the installed files (DATA1.ARJ from the CD) |
| `/mnt/nvme/tlrb2/files/` | raw CD contents (ANMS, SCREENS, SOUNDS, STADIUMS, REPLAY, manual PDF) |
| `/mnt/nvme/tlrb2/flat/` | flattened EXEs (overlays merged), `.map.json`, `.seeds.txt` |
| `/mnt/nvme/tlrb2/ghidra_proj/TLRB2` | Ghidra project, all 8 programs |
| `/mnt/nvme/tlrb2/index/<EXE>/` | grep dump: `_all.c`, `_functions.tsv` (regenerate after renames) |
| `/mnt/nvme/tlrb2/shots/`, `logs/`, `snaps/` | screenshots, traces, data snapshots |
| `/mnt/nvme/src/dosbox-x` | DOSBox-X source, built with the heavy debugger |

Install = DATA1.ARJ extracted to C:\TONY2 (what INSTALL does). The game reads art/sound/stadiums from D: at runtime.

## Run

- Play (real desktop, sound): `~/tlrb2/scripts/launch.sh live`
- Test rig (hidden Xvfb :98, silent): `~/tlrb2/scripts/launch.sh work headless`
- Debugger / instrumentation: `~/tlrb2/scripts/launch_trace.sh work [headless]` (DOSBox-X heavy-debug build; DOS-level
  file log of every open/read/seek on C: and D: in `/mnt/nvme/tlrb2/logs/dosbox-x.log`; debugger via Alt+Pause or the
  Debug menu; see notes/RE_NOTES.md). Its window has a menu bar, so the game area sits at a different offset
  (640x400 at 192,200 on :98) than under dosbox-staging (758x569 at 133,99): screenshot before clicking.
- Drive the rig: `~/tlrb2/scripts/xc.sh shot NAME | click X Y | menu X Y IX IY | key K | type TEXT`
  - Menus are press, drag, release: `xc.sh menu 487 111 530 299` = Utilities > Edit Player Stats.
  - The window needs focus for mouse input (xc.sh does it). Escape skips the intro.
- File trace: `~/tlrb2/scripts/ftrace.sh OUT` (strace on the running DOSBox: every open/read/seek with offsets).
  Overlay loads show up as reads of the EXE at an offset: offset - (FBOV header pos + 16) = overlay `fileoff` in the map.
- Snapshot data before an edit: `~/tlrb2/scripts/snap.sh NAME`; compare team files: `tools/v20.py diff OLD NEW`.

## Gotchas
- DOSBox-X ignores SIGTERM: `kill <pid>` leaves it running on :98, so repeated relaunches stacked up to 7 instances on the
  work install (2026-10-06 ~22:00, Lane B3 gt_run.sh batches; GAME.TMP captures from that window may be contaminated).
  tools/lane_b/relaunch.sh now escalates to SIGKILL and reaps strays on work/c.
- `pgrep -f`/`pkill -f` also match other sessions' `bash -c` wrappers whose command text merely mentions a script
  (e.g. a watcher that greps for gh.py). Anchor the pattern to the real invocation (`^bash [^ ]*scripts/regen[.]sh`,
  `^[^ ]*python3 [^ ]*gh[.]py`) or gate on /mnt/nvme/tlrb2/ghidra_proj/TLRB2.lock, which exists only while Ghidra has the project open.
- Two DOSBox rigs can run at once (2026-10-06): Lane B on Xvfb :98 (dosbox-x, work install) and the M3 rig on :97
  (dosbox, work2 install, scripts/m3_launch.sh). `pkill -x dosbox` / `pkill -x dosbox-x` hits both; kill your own rig by
  pid (e.g. `pgrep -f "work2/c"` or `pgrep -f "work/c\""`) instead.

- Never `pkill -f <pattern>` where the pattern appears in your own command line (it kills your shell). Use `pkill -x dosbox` or a bracket trick like `'com.dosbox_[x]'`.
- SDL picks Wayland if `WAYLAND_DISPLAY` is set: headless runs must set `SDL_VIDEODRIVER=x11` and unset it (launch scripts do), or the window opens on Will's desktop.
- dosbox-staging under Xvfb needs `output=surface` for screenshots (OpenGL gives black frames).
- Flathub DOSBox-X has no debugger and its LOG categories are compiled out; use the source build.
- DOSBox-X file logging needs both `fileio = true` and the category `files = debug` in `[log]` (conf/tlrb2-x.conf).
- Run only one DOSBox at a time on :98; xc.sh targets the first window whose title contains `cycles/ms`.

## Rules (carried over from the BBPro98 work)

1. Experiments only in `work/`. Every patch script asserts original bytes, is idempotent, has a revert, and refuses to touch `/mnt/nvme/tlrb2/c` or `pristine`.
2. Nothing is "done" until a screenshot Claude reads itself shows it. Every patch has a positive control.
3. Ghidra is the source of truth: every function/struct identified gets renamed/typed in the project in the same step.
4. Find code by tracing (debugger breakpoints, memory watches, file traces), not by guess-and-patch.
5. Commit to git after each verified milestone. Never push without asking.
