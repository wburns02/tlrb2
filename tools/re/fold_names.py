#!/usr/bin/env python3
"""Fold hand/dynamically verified names (notes/lane_names.tsv: prog, addr, name, evidence) into the Ghidra project,
and apply data types listed in notes/lane_types.tsv (prog, addr, type, name, evidence). type is a /TLRB2 type
(V20Team, V20Header, V20Player, see structs.py) or a built-in (byte, word, dword), optionally with [N] for an array
or a trailing * for a far pointer (4 bytes seg:off) to it; char and FILE (as void) are accepted too. Existing data at the address is cleared first.

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
TYPES = os.path.join(os.path.dirname(__file__), '..', '..', 'notes', 'lane_types.tsv')

DGROUP = dict(MAIN='40fa', BB='5120', UTIL='3954', DRAFT='1f31', BACK='2c71', MANAGE='28bf', PLAY='170a', CONTROL='123e')

def where(prog, a):
    """'seg:off' or 'DS:off' -> Ghidra address text; None for buffer-relative rows (DS:xxxx+0x..), which have no
    static address and are documentation only."""
    a = a.strip()
    if '+' in a:
        return None
    if a.upper().startswith('DS:'):
        return f"{DGROUP[prog]}:{a[3:]}"
    return a

def resolve(p, t):
    from ghidra.program.model.data import (CategoryPath, ByteDataType, WordDataType, DWordDataType, ArrayDataType,
                                           PointerDataType, CharDataType, VoidDataType)
    import re
    m = re.match(r'^(\w+)(?:\[(\d+|0x[0-9a-fA-F]+)\])?(\*)?$', t.strip())
    if not m:
        raise ValueError(t)
    base, n, ptr = m.groups()
    # FILE: the RTL stream struct is not modelled, so FILE* is a far pointer to void
    dt = {'byte': ByteDataType.dataType, 'word': WordDataType.dataType, 'dword': DWordDataType.dataType,
          'char': CharDataType.dataType, 'FILE': VoidDataType.dataType}.get(base)
    if dt is None:
        dt = p.getDataTypeManager().getDataType(CategoryPath('/TLRB2'), base)
        if dt is None:
            raise ValueError('unknown type ' + base)
    if n:
        dt = ArrayDataType(dt, int(n, 0), dt.getLength())
    if ptr:
        dt = PointerDataType(dt, 4)
    return dt

def apply_types(proj, opened):
    if not os.path.exists(TYPES):
        return
    rows = [l.rstrip('\n').split('\t') for l in open(TYPES) if l.strip() and not l.startswith('#')]
    for prog in sorted({r[0] for r in rows}):
        if prog not in opened:  # GhidraProject tracks each open; opening twice ends its transaction twice on close
            opened[prog] = proj.openProgram('/', f'{prog}.flat.bin', False)
        p = opened[prog]
        af, lst = p.getAddressFactory(), p.getListing()
        tx = p.startTransaction('apply verified types'); ok = False
        try:
            for _, a, t, nm, ev in (r for r in rows if r[0] == prog):
                w = where(prog, a)
                if w is None:
                    print(prog, a, 'skipped (buffer-relative, no static address)'); continue
                ad = af.getAddress(w)
                try:
                    dt = resolve(p, t)
                    lst.clearCodeUnits(ad, ad.add(dt.getLength() - 1), False)
                    lst.createData(ad, dt)
                    if nm:
                        p.getSymbolTable().createLabel(ad, nm, SourceType.USER_DEFINED)
                    lst.setComment(ad, CodeUnit.PLATE_COMMENT, f'[verified] {nm} ({t}): {ev}')
                    print(prog, a, 'typed', t, nm)
                except Exception as e:
                    print(prog, a, 'type FAILED', t, repr(e)[:200])
            ok = True
        finally:
            p.endTransaction(tx, ok)
        proj.save(p)

def main():
    rows = [l.rstrip('\n').split('\t') for l in open(TSV) if l.strip() and not l.startswith('#')]
    proj = GhidraProject.openProject(PROJ, NAME, True)
    opened = {}
    try:
        for prog in sorted({r[0] for r in rows}):
            p = opened[prog] = proj.openProgram('/', f'{prog}.flat.bin', False)
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
        apply_types(proj, opened)
    finally:
        proj.close()

if __name__ == '__main__':
    main()
