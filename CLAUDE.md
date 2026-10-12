# tlrb2 builder rules (GLM, Kimi, Claude). CLAUDE.md is a byte-identical copy.

Project: full reverse engineering of Tony La Russa Baseball II (1993 DOS) and in-game mods. Public repo.
- Never commit game files or game data (.EXE from the game, .V20, .MAJ, .ANM, .SCR, images). Our own builds
  (tools/m4/blob/DYNASTY.EXE, *.bin) are the only binaries allowed.
- No em dashes or en dashes anywhere. No secrets, no absolute paths to private machines in code.
- Python reference first, then the 16-bit asm port must match it BYTE-EXACT. The unicorn tests
  (tools/m4/test_blob_unicorn.py) are the parity gate; never weaken, skip or delete a parity test to get green.
- Integer math contracts in notes/M4_CONTRACT.md are law: truncation toward zero for signed division (x86 idiv),
  arithmetic right shift for signed >>, exact table order for RNG draws. If the contract is wrong, stop and say so;
  do not silently deviate.
- Asm: nasm, BITS 16, CPU 386 (32-bit registers allowed). Build DYNASTY.EXE with python3 tools/m4/blob/build_dynasty.py.
- Test command: python3 -m pytest -q tools/m4. Tests needing /mnt/nvme data skip in the sandbox; that is expected.
- Do not run git commands that change history (no reset, rebase, clean, push). Commit only when the task says so.
- DOSBox sessions: launch only through the rig scripts (Xvfb :98, SDL_VIDEODRIVER=x11, WAYLAND_DISPLAY unset). An agent
  shell inherits DISPLAY=:0, so an ad-hoc launch opens on Will's desktop. Kill your session when the probe ends; a
  machine-level reaper (dosbox-reaper.timer) also kills agent-launched DOSBox after its Claude session exits or after
  2 hours (export DOSBOX_KEEP=1 for a longer season sim).
- Team ids (C12): never map a MAJ slot or engine id to a team as L * 16 + slot. Go through tools/m4/teamids.py
  (C: tools/m4/teamids.h) with the league's TEAMID.DAT. A 3-division league compacts engine ids and uses slots 16..23.
- A new season on the GENERATED schedule (every 3-division league) starts at day byte 0x00, not 0x07.
- Web deploy: web/deploy.sh (copies our EXEs into the stage, patches, builds, backs up, rsyncs, verifies the served sha).
- Web: Cloudflare in front of the site returns 403 to the default Python-urllib User-Agent. Any script that calls
  the site sends its own User-Agent (tools/studio_worker.py does).
- js-dos 8.5.3 writes bundle (zip) entries after plain initFs files, so a {path, contents} file under a path the
  bundle also has is silently overwritten. Overlay a bundle file with a one-entry stored zip in initFs (index.html
  storedZip). The overlay then counts as a changed file and rides along in the slot's saved changes.
- Browser walks (Playwright + js-dos) need a 6G capped limit; at 3G the wasm build traps with
  "RuntimeError: unreachable" on some boots, which looks like a black screen, not a game bug.
- Be terse in reports: what changed, test output tail, anything you could not do.
