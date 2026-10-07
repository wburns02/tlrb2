#!/usr/bin/env python3
"""Fold hand/dynamically verified names (notes/lane_names.tsv: prog, addr, name, evidence) into the Ghidra project.

usage: /mnt/nvme/bbpro98/ghidra_venv/bin/python3 fold_names.py   (then scripts/regen.sh)
A function starting at addr is renamed USER_DEFINED (overrides auto_ names) and gets "[verified] evidence" prepended to
its plate comment. If addr is inside a function, a USER_DEFINED label is added instead. Idempotent.
"""
import os, sys
os.environ.setdefault('GHIDRA_INSTALL_DIR', '/mnt/nvme/ghidra/ghidra_12.1.4_PUBLIC')
import pyghidra
pyghidra.start()
from ghidra.base.project import GhidraProject
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit

PROJ, NAME = '/mnt/nvme/tlrb2/ghidra_proj', 'TLRB2'

def set_plate(p, ad, text):
    p.getListing().setComment(ad, CodeUnit.PLATE_COMMENT, text)

TSV = os.path.join(os.path.dirname(__file__), '..', '..', 'notes', 'lane_names.tsv')

def main():
    rows = [l.rstrip('\n').split('\t') for l in open(TSV) if l.strip() and not l.startswith('#')]
    proj = GhidraProject.openProject(PROJ, NAME, True)
    try:
        for prog in sorted({r[0] for r in rows}):
            p = proj.openProgram('/', f'{prog}.flat.bin', False)
            fm, af, lst = p.getFunctionManager(), p.getAddressFactory(), p.getListing()
            tx = p.startTransaction('fold verified names'); ok = False
            try:
                for _, a, nm, ev in (r for r in rows if r[0] == prog):
                    ad = af.getAddress(a)
                    f = fm.getFunctionAt(ad)
                    tag = f'[verified] {nm}: {ev}'
                    if f is not None:
                        f.setName(nm, SourceType.USER_DEFINED)
                        old = lst.getComment(CodeUnit.PLATE_COMMENT, ad) or ''
                        if not old.startswith('[verified]'):
                            set_plate(p, ad, tag + ('\n' + old if old else ''))
                        print(prog, a, 'renamed', nm)
                    else:
                        p.getSymbolTable().createLabel(ad, nm, SourceType.USER_DEFINED)
                        set_plate(p, ad, tag)
                        print(prog, a, 'label', nm)
                ok = True
            finally:
                p.endTransaction(tx, ok)
            proj.save(p)
    finally:
        proj.close()

if __name__ == '__main__':
    main()
