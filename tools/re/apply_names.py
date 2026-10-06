#!/usr/bin/env python3
"""Apply bulk-naming results (/mnt/nvme/tlrb2/re/merged.json) to the Ghidra project.

usage: /mnt/nvme/bbpro98/ghidra_venv/bin/python3 apply_names.py [EXE ...]   (default: all 8), then scripts/regen.sh

Every named unit gets a plate comment: "[auto <status> <conf>] name: purpose" (+ the other model's answer).
Accepted units (seed, or confidence >= 0.6 and not contradicted by a confident second opinion; see name_all.py merge)
are also renamed, with SourceType.ANALYSIS so they stay distinguishable from hand-verified USER_DEFINED names.
A function already renamed by hand (USER_DEFINED) is never renamed. Re-running is idempotent. Call targets Ghidra
never made into functions (kb.py pseudo functions) are created first.
"""
import sys, os, re, json
os.environ.setdefault('GHIDRA_INSTALL_DIR', '/mnt/nvme/ghidra/ghidra_12.1.4_PUBLIC')
import pyghidra
pyghidra.start()
from ghidra.base.project import GhidraProject
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit

PROJ, NAME = '/mnt/nvme/tlrb2/ghidra_proj', 'TLRB2'
R = '/mnt/nvme/tlrb2/re'
PROGS = ['MAIN', 'BB', 'UTIL', 'DRAFT', 'BACK', 'MANAGE', 'PLAY', 'CONTROL']

def clean(n):
    n = re.sub(r'[^A-Za-z0-9_]', '_', str(n or '')).strip('_')[:60]
    return ('f_' + n) if n[:1].isdigit() else n

def set_plate(p, ad, text):
    try:
        from ghidra.program.model.listing import CommentType
        p.getListing().setComment(ad, CommentType.PLATE, text)
    except ImportError:
        p.getListing().setComment(ad, CodeUnit.PLATE_COMMENT, text)

def main():
    progs = sys.argv[1:] or PROGS
    merged = json.load(open(f'{R}/merged.json'))
    per = {}
    for k, m in merged.items():
        for p, a in m['members']:
            per.setdefault(p, []).append((a, m))
    proj = GhidraProject.openProject(PROJ, NAME, True)
    try:
        for prog in progs:
            p = proj.openProgram('/', f'{prog}.flat.bin', False)
            fm = p.getFunctionManager()
            af = p.getAddressFactory()
            ren = com = miss = made = 0
            tx = p.startTransaction('apply auto names')
            ok = False
            try:
                for a, m in per.get(prog, []):
                    ad = af.getAddress(a)
                    f = fm.getFunctionAt(ad) if ad else None
                    if f is None and ad is not None:  # call target Ghidra never made a function (kb pseudo function)
                        from ghidra.app.cmd.disassemble import DisassembleCommand
                        from ghidra.app.cmd.function import CreateFunctionCmd
                        from ghidra.util.task import TaskMonitor
                        DisassembleCommand(ad, None, True).applyTo(p, TaskMonitor.DUMMY)
                        CreateFunctionCmd(ad).applyTo(p, TaskMonitor.DUMMY)
                        f = fm.getFunctionAt(ad)
                        made += f is not None
                    if f is None:
                        miss += 1
                        continue
                    tag = 'seed' if m['status'] == 'seed' else f"auto {m['status']} {m['confidence']:.2f}"
                    text = f"[{tag}] {m['name']}: {m['purpose']}"
                    if m.get('alt'):
                        text += f"\nother model: {m['alt']}"
                    set_plate(p, ad, text); com += 1
                    accept = m['status'] == 'seed' or m.get('accept')
                    if accept and f.getSymbol().getSource() != SourceType.USER_DEFINED:
                        nm = clean(m['name'])
                        if nm and f.getName() != nm:
                            src = SourceType.USER_DEFINED if m['status'] == 'seed' else SourceType.ANALYSIS
                            try:
                                f.setName(nm, src)
                            except Exception:
                                f.setName(f"{nm}_{a.replace(':', '_')}", src)
                            ren += 1
                ok = True
            finally:
                p.endTransaction(tx, ok)
            proj.save(p)
            print(f'{prog}: renamed {ren}, comments {com}, functions created {made}, failed {miss}', flush=True)
    finally:
        proj.close()

if __name__ == '__main__':
    main()
