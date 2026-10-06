Start this session from ~/tlrb2 (`cd ~/tlrb2 && claude`) and paste everything below the line.

---

Project: full reverse engineering of Tony La Russa Baseball II (1993 DOS, v1.3 CD) so I can mod it from inside the game. No companion apps or sidecars: every feature lands in the game itself. Read ~/tlrb2/README.md, notes/RE_NOTES.md, notes/FORMATS.md and IDEAS.md first. They describe the layout, the rig, the rules and what is already known.

The environment is already set up and verified: the live and work installs, the headless test rig on Xvfb :98, the strace file tracer, the flattened EXEs with overlays merged, a Ghidra project with all 8 programs, the grep index, and a DOSBox-X heavy-debug build. Do not redo any of it.

Model split: Fable for the hard RE judgment calls (struct layouts, hook design, register liveness, gate decisions), in short turns. Sonnet runs the session, Ghidra queries, debugger and trace runs, and the click-and-screenshot loops. GLM-Flash only for self-contained tools written from a complete spec (readers/writers once a format is decoded). No Opus unless I allow it.

Milestones, in order. Each is accepted only by evidence you read yourself (screenshot, trace or diff), with a positive control.

M1 Ghidra foundation
- Find DGROUP (Borland c0 startup sets DS from a relocated immediate near entry 1000:0000) and set the DS context so strings and globals resolve. Re-export and confirm a known string (e.g. "EDIT PLAYER STATS") is referenced from code.
- Give yourself live Ghidra access: a headless-capable Ghidra MCP server if one works with Ghidra 12.1.4 (verify first), else headless scripts in ~/tlrb2/ghidra_scripts wrapped as bash commands (xrefs, decomp, rename, settype, struct-apply).
- Identify and name the Borland RTL (fopen/fread/fseek/malloc/far heap, int 21h wrappers) and the PKWARE DCL implode/explode routines in every program.

M2 Team file (.V20) fully decoded
- Work install only. For each field the Utilities editors expose (ratings, positions, handedness, stats), change one value, save, snapshot and diff with tools/v20.py. Cross-check against the UTIL code that reads the record (debugger breakpoint on the V20 read, then a memory watch on the buffer).
- Define the V20 header and player record as Ghidra structs and apply them.
- Decode the stats -> ratings formula UTIL offers ("automatically calculate a player's ratings based on his new stats").
- Deliverable: notes/FORMATS.md complete for V20 and .MAJ, plus a round-trip reader/writer (GLM-Flash from the spec) proven by editing a file outside the game and seeing the change in the game.

M3 Season state
- Play or sim a short season on the work install. Trace which files hold season stats, standings, schedule progress and leaders. Decode them the same way.
- Map the end-of-season flow across programs (CONTROL errorlevels, SYSTEM, CONTROL, GAME.TMP).

M4 Dynasty feasibility (the headline mod, see IDEAS.md)
- Measure free conventional memory per program (CHECKMEM threshold, the DOSBox-X debugger's MCB chain) and where new code could live (code caves, a new overlay segment, a TSR, or a new program in the TONY2.BAT loop).
- Write a design for multi-season play (rollover, aging and progression, retirements, rookies, career stats, Hall of Fame, career leaders, history screens), built in the game's own UI style. Do not build yet; I want to review the design.

Parallel option (two sessions at once, same repo; paste this whole prompt into both and tell each which lane it is)
- Lane A (static, no display): M1, then types and renames in Ghidra whatever Lane B finds. Lane A is the only session that writes to the Ghidra project, because the project lock blocks a second writer.
- Lane B (dynamic, Xvfb :98, work install): M2 field diffs and debugger/file traces, then M3. It reads code through the grep index and the DOSBox-X debugger, and it records findings with addresses in notes/FORMATS.md for Lane A to apply.
- Each lane commits only its own files. M4 starts after both lanes finish.

Rules
- Experiments only in /mnt/nvme/tlrb2/work. Patch scripts assert original bytes, are idempotent, have a revert, and refuse to touch /mnt/nvme/tlrb2/c or /mnt/nvme/tlrb2/pristine.
- Ghidra is the source of truth: rename or type everything you identify in the same step, then regenerate the index.
- Find code by tracing (breakpoints, memory watches, file traces), not by guessing and patching.
- Commit to the local git repo after each verified milestone. Never push without asking.
- Interrupt me only for money, external sends, destructive actions on the live install, or the M4 design review.
