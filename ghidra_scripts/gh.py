#!/usr/bin/env python3
"""gh.py CMD ... -- live pyghidra access to the TLRB2 Ghidra project (/mnt/nvme/tlrb2/ghidra_proj).

Commands:
  setds PROG SEG        set DS=SEG (hex segment) over the whole program range, re-analyze, save
  strings PROG RE       list defined strings matching regex, with xref counts
  xrefs PROG ADDR       list references to a flat address (hex, e.g. 3a21f)
  decomp PROG TARGET    decompile a function by address or name
  rename PROG ADDR NAME rename function at flat address
  label PROG ADDR NAME  create a label at a flat address
  structs               list program names in the project

Addresses are flat Ghidra addresses (20-bit: segment*16+offset, e.g. 3a21f).
Runs read-write: every mutating command saves. Analysis runs after setds.
"""
import sys, os, re
os.environ.setdefault('GHIDRA_INSTALL_DIR', '/mnt/nvme/ghidra/ghidra_12.1.4_PUBLIC')
import pyghidra
pyghidra.start()
from ghidra.base.project import GhidraProject
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.address import AddressSet
from java.math import BigInteger

PROJ = '/mnt/nvme/tlrb2/ghidra_proj'
NAME = 'TLRB2'


def A(p, a):
    return p.getAddressFactory().getDefaultAddressSpace().getAddress(a)


def open_rw(proj, prog):
    return proj.openProgram('/', prog, False)


def main():
    cmd = sys.argv[1]
    proj = GhidraProject.openProject(PROJ, NAME, True)
    try:
        if cmd == 'structs':
            for n in proj.getRootFolder().getFiles():
                print(n.getName())
            return
        prog = sys.argv[2]
        p = open_rw(proj, prog)
        fm = p.getFunctionManager()
        if cmd == 'setds':
            seg = int(sys.argv[3], 16)
            ctx = p.getProgramContext()
            ds = ctx.getRegister('DS')
            lo, hi = p.getMinAddress(), p.getMaxAddress()
            tx = p.startTransaction('setds')
            try:
                ctx.setValue(ds, lo, hi, BigInteger.valueOf(seg))
                ok = True
            finally:
                p.endTransaction(tx, ok)
            proj.save(p)
            print(f'DS set to {seg:04x} over {lo}-{hi}; analyzing...')
            from ghidra.app.plugin.core.analysis import AutoAnalysisManager
            mgr = AutoAnalysisManager.getAnalysisManager(p)
            mgr.reAnalyzeAll(None)
            from ghidra.util.task import ConsoleTaskMonitor
            mgr.startAnalysis(ConsoleTaskMonitor())
            proj.save(p)
            print('analysis done; functions:', fm.getFunctionCount())
        elif cmd == 'fixrefs':
            # create DATA refs from immediates equal to DGROUP offsets of defined strings
            from ghidra.program.model.scalar import Scalar
            from ghidra.program.model.symbol import RefType
            seg = int(sys.argv[3], 16)
            base = seg * 16
            ref = p.getReferenceManager()
            str_off = {}
            for d in p.getListing().getDefinedData(True):
                if d.hasStringValue() and base <= d.getAddress().getOffset() < base + 0x10000:
                    str_off.setdefault(d.getAddress().getOffset() - base, d.getAddress())
            tx = p.startTransaction('fixrefs')
            n = made = 0
            ok = False
            try:
                for ins in p.getListing().getInstructions(True):
                    n += 1
                    for i in range(ins.getNumOperands()):
                        for obj in ins.getOpObjects(i):
                            if not isinstance(obj, Scalar):
                                continue
                            val = obj.getUnsignedValue()
                            if val in str_off:
                                ref.addMemoryReference(ins.getAddress(), str_off[val], RefType.DATA, SourceType.ANALYSIS, i)
                                made += 1
                # data words in DGROUP (pointer tables)
                mem = p.getMemory()
                import jpype
                dlen = min(0x10000, p.getMaxAddress().getOffset() - base + 1)
                buf = jpype.JArray(jpype.JByte)(dlen)
                got = mem.getBytes(A(p, base), buf)
                from ghidra.program.model.address import Address
                for k in range(0, len(buf) - 1):
                    val = (buf[k] & 0xff) | ((buf[k + 1] & 0xff) << 8)
                    if val in str_off:
                        frm = A(p, base + k)
                        ref.addMemoryReference(frm, str_off[val], RefType.DATA, SourceType.ANALYSIS, -1)
                        made += 1
                ok = True
            except Exception:
                import traceback; traceback.print_exc()
                raise
            finally:
                p.endTransaction(tx, ok)
            proj.save(p)
            print(f'scanned {n} instrs, strings={len(str_off)}, refs added={made}')
        elif cmd == 'strings':
            pat = re.compile(sys.argv[3])
            from ghidra.program.model.data import StringDataInstance
            for d in p.getListing().getDefinedData(True):
                v = d.getValue()
                if d.hasStringValue() and isinstance(v, str) and pat.search(v):
                    n = sum(1 for _ in p.getReferenceManager().getReferencesTo(d.getAddress()))
                    print(f"{d.getAddress()} nref={n} {v[:80]!r}")
        elif cmd == 'xrefs':
            ad = A(p, int(sys.argv[3], 16))
            ref = p.getReferenceManager()
            for r in ref.getReferencesTo(ad):
                print(f"{r.getFromAddress()} {r.getReferenceType()}")
            d = p.getListing().getDataAt(ad)
            print('data at:', repr(d.getValue())[:100] if d and d.hasStringValue() else (d or 'none'))
        elif cmd == 'decomp':
            t = sys.argv[3]
            f = fm.getFunctionAt(A(p, int(t, 16))) if re.fullmatch(r'[0-9a-f]+', t) else None
            if f is None:
                sym = p.getSymbolTable().getSymbols(t)
                for s in sym:
                    f = fm.getFunctionAt(s.getAddress())
                    if f:
                        break
            if f is None:
                print('NO FUNCTION', t); return
            from ghidra.app.decompiler import DecompInterface
            from ghidra.util.task import ConsoleTaskMonitor
            di = DecompInterface()
            di.openProgram(p)
            res = di.decompileFunction(f, 120, ConsoleTaskMonitor())
            print(res.getDecompiledFunction().getC() if res.decompileCompleted() else f'DECOMP FAILED: {res.getErrorMessage()}')
        elif cmd == 'rename':
            ad = A(p, int(sys.argv[3], 16))
            f = fm.getFunctionAt(ad)
            if f is None:
                print('NO FUNCTION at', sys.argv[3]); return
            tx = p.startTransaction('rename')
            try:
                print(f.getName(), '->', sys.argv[4]); f.setName(sys.argv[4], SourceType.USER_DEFINED)
                ok = True
            finally:
                p.endTransaction(tx, ok)
            proj.save(p)
        elif cmd == 'label':
            ad = A(p, int(sys.argv[3], 16))
            tx = p.startTransaction('label')
            try:
                p.getSymbolTable().createLabel(ad, sys.argv[4], SourceType.USER_DEFINED)
                ok = True
            finally:
                p.endTransaction(tx, ok)
            proj.save(p)
        else:
            print('unknown cmd', cmd)
    finally:
        proj.close()


if __name__ == '__main__':
    main()
