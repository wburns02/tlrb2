"""Per-function views over the Ghidra export: bytes, ndisasm listing, decompiled C, call graph.

Usage as a library: P = Program('MAIN'); f = P.fn['1000:0157']; P.disasm(f); P.decomp(f)
"""
import subprocess, re

T = '/mnt/nvme/tlrb2'

class Program:
    def __init__(self, name):
        self.name = name
        self.flat = open(f'{T}/flat/{name}.flat.bin', 'rb').read()
        self.fn = {}
        for line in open(f'{T}/index/{name}/_functions.tsv').read().splitlines()[1:]:
            addr, nm, size, callers, callees = (line.split('\t') + [''] * 5)[:5]
            self.fn[addr] = dict(addr=addr, name=nm, size=int(size),
                                 callers=[c for c in callers.split(',') if c],
                                 callees=[c for c in callees.split(',') if c])
        self._c = {}
        cur, buf = None, []
        for line in open(f'{T}/index/{name}/_all.c', errors='replace'):
            m = re.match(r'// ==== (\S+) ', line)
            if m:
                if cur: self._c[cur] = ''.join(buf)
                cur, buf = m.group(1), []
            buf.append(line)
        if cur: self._c[cur] = ''.join(buf)

    @staticmethod
    def lin(addr):
        seg, off = (int(x, 16) for x in addr.split(':'))
        return (seg - 0x1000) * 16 + off

    def bytes(self, f):
        p = self.lin(f['addr'])
        return self.flat[p:p + f['size']]

    def disasm(self, f):
        """ndisasm listing with Ghidra seg:off addresses."""
        seg, off = (int(x, 16) for x in f['addr'].split(':'))
        out = subprocess.run(['ndisasm', '-b16', '-o', str(off), '-'], input=self.bytes(f),
                             capture_output=True).stdout.decode()
        rows = []
        for line in out.splitlines():
            a, hx, ins = line[:8], line[10:28].strip(), line[28:].strip()
            if a.strip():
                rows.append((int(a, 16), hx, ins))
        return rows

    def disasm_text(self, f):
        seg = f['addr'].split(':')[0]
        return '\n'.join(f'{seg}:{a:04x}  {hx:<14} {ins}' for a, hx, ins in self.disasm(f))

    def decomp(self, f):
        return self._c.get(f['addr'], '')
