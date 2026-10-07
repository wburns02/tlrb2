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
- Be terse in reports: what changed, test output tail, anything you could not do.
