#!/usr/bin/env python3
"""Unicorn-based mini DOS: run a 16-bit MZ EXE against a host directory tree.

The host directory `root` stands for drive C:. DOS paths resolve under root:
`C:\\...` at the drive root, anything else under root/cwd. Lookup is
case-insensitive against the host names (the host files are upper case).
Supports the int 21h calls our DOS programs use plus the int 1Ah tick call.
"""
import os
import re
import struct

from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR, UC_HOOK_CODE, UcError
from unicorn.x86_const import *

LOAD_SEG = 0x1000
PSP_SEG = 0x0FF0
MEM_SIZE = 0x100000
DTA_SIZE = 43
NAME_SLOT = 13  # DTA name field: 8.3 name + NUL
CF = 0x001


class DosError(Exception):
    def __init__(self, code=None, msg=''):
        if isinstance(code, int):
            super().__init__(msg or f'DOS error {code:#04x}')
            self.code = code
        else:
            super().__init__(code)
            self.code = None


def dos_find(root, dos_path):
    """Case-insensitive host path for a DOS path ('X:\\...' or 'X:...'), or
    None. 'X:\\A\\B' resolves under root; other paths resolve from root too
    (cwd is prepended by the caller when the path is relative to TONY2)."""
    cur = root
    drive_root = False  # a drive-letter prefix resets to the root
    for part in [p for p in dos_path.replace('/', '\\').split('\\') if p]:
        if part.endswith(':') and len(part) == 2:
            cur = root
            drive_root = True
            continue
        if drive_root:
            drive_root = False
            cur = os.path.join(root, part.upper())
            continue
        try:
            entries = os.listdir(cur)
        except OSError:
            return None
        match = next((e for e in entries if e.upper() == part.upper()), None)
        if match is None:
            return None
        cur = os.path.join(cur, match)
    return cur


def split_parent(dos_path):
    """(parent DOS dir path, final component); '' means the root."""
    parts = [p for p in dos_path.replace('/', '\\').split('\\') if p]
    if part := parts and parts[-1]:
        return '\\'.join(parts[:-1]), part
    return '\\'.join(parts), ''


def wildcard_rx(pattern):
    """8.3 wildcard (* and ?) against upper-case names."""
    rx = ''
    for ch in pattern.upper():
        if ch == '*':
            rx += '.*'
        elif ch == '?':
            rx += '.'
        else:
            rx += re.escape(ch)
    return re.compile('^' + rx + '$')


class MiniDos:
    def __init__(self, root, cwd='TONY2', ticks=0x1234):
        self.root = os.path.abspath(root)
        self.cwd = cwd
        self.ticks = ticks
        self.dta = 0
        self.handles = {}
        self.next_handle = 5
        self.find_ctx = None  # (host_dir, [names], index)
        self.exit_code = None

    # ---- flags -----------------------------------------------------------
    def ok(self, uc):
        uc.reg_write(UC_X86_REG_EFLAGS, uc.reg_read(UC_X86_REG_EFLAGS) & ~CF)

    def fail(self, uc, code):
        uc.reg_write(UC_X86_REG_AX, code)
        uc.reg_write(UC_X86_REG_EFLAGS, uc.reg_read(UC_X86_REG_EFLAGS) | CF)

    # ---- paths -----------------------------------------------------------
    def dos_path(self, uc):
        ds = uc.reg_read(UC_X86_REG_DS)
        dx = uc.reg_read(UC_X86_REG_DX)
        raw = uc.mem_read((ds << 4) + dx, 260)
        return raw.split(b'\0')[0].decode('cp437', 'replace')

    def resolve(self, dos_path):
        if len(dos_path) > 2 and dos_path[1] == ':':
            return dos_find(self.root, dos_path)
        return dos_find(self.root, self.cwd + '\\' + dos_path)

    def parent_dir(self, uc):
        """Host dir of the parent of the DOS path in DS:DX, or None."""
        dpath, _ = split_parent(self.dos_path(uc))
        ddir = self.resolve(dpath)
        if ddir is None or not os.path.isdir(ddir):
            return None
        return ddir

    # ---- int 21h ---------------------------------------------------------
    def int21(self, uc):
        ah = uc.reg_read(UC_X86_REG_AH)
        if ah == 0x1a:
            self.set_dta(uc)
        elif ah == 0x3c:
            self.create(uc)
        elif ah == 0x3d:
            self.open(uc)
        elif ah == 0x3e:
            self.close(uc)
        elif ah == 0x3f:
            self.read(uc)
        elif ah == 0x40:
            self.write(uc)
        elif ah == 0x42:
            self.seek(uc)
        elif ah == 0x4e:
            self.find_first(uc)
        elif ah == 0x4f:
            self.find_next(uc)
        elif ah == 0x4c:
            self.exit_code = uc.reg_read(UC_X86_REG_AL)
            uc.emu_stop()
        else:
            raise DosError(msg=f'unimplemented int 21h AH={ah:#04x}')

    def set_dta(self, uc):
        ds = uc.reg_read(UC_X86_REG_DS)
        dx = uc.reg_read(UC_X86_REG_DX)
        self.dta = (ds << 4) + dx
        self.ok(uc)

    def new_handle(self, uc, f):
        h = self.next_handle
        self.next_handle += 1
        self.handles[h] = f
        uc.reg_write(UC_X86_REG_AX, h)
        self.ok(uc)

    def create(self, uc):
        ddir = self.parent_dir(uc)
        if ddir is None:
            return self.fail(uc, 3)
        _, name = split_parent(self.dos_path(uc))
        try:
            f = open(os.path.join(ddir, name.upper()), 'wb+')
        except OSError:
            return self.fail(uc, 5)
        self.new_handle(uc, f)

    def open(self, uc):
        host = self.resolve(self.dos_path(uc))
        mode = uc.reg_read(UC_X86_REG_AL)
        if host is None or not os.path.isfile(host):
            return self.fail(uc, 2)
        try:
            if mode == 0:
                f = open(host, 'rb')
            elif mode == 1:
                f = open(host, 'r+b')  # DOS never truncates on open
            elif mode == 2:
                f = open(host, 'r+b')
            else:
                return self.fail(uc, 0x0c)
        except OSError:
            return self.fail(uc, 5)
        self.new_handle(uc, f)

    def close(self, uc):
        f = self.handles.pop(uc.reg_read(UC_X86_REG_BX), None)
        if f is None:
            return self.fail(uc, 6)
        f.close()
        self.ok(uc)

    def read(self, uc):
        f = self.handles.get(uc.reg_read(UC_X86_REG_BX))
        if f is None:
            return self.fail(uc, 6)
        count = uc.reg_read(UC_X86_REG_CX)
        buf = (uc.reg_read(UC_X86_REG_DS) << 4) + uc.reg_read(UC_X86_REG_DX)
        data = f.read(count)
        if data:
            uc.mem_write(buf, data)
        uc.reg_write(UC_X86_REG_AX, len(data))
        self.ok(uc)

    def write(self, uc):
        f = self.handles.get(uc.reg_read(UC_X86_REG_BX))
        if f is None:
            return self.fail(uc, 6)
        count = uc.reg_read(UC_X86_REG_CX)
        if count == 0:
            raise DosError(msg='int 21h AH=40h with CX=0 (DOS truncates): asm must not do that')
        buf = (uc.reg_read(UC_X86_REG_DS) << 4) + uc.reg_read(UC_X86_REG_DX)
        f.write(bytes(uc.mem_read(buf, count)))
        uc.reg_write(UC_X86_REG_AX, count)
        self.ok(uc)

    def seek(self, uc):
        f = self.handles.get(uc.reg_read(UC_X86_REG_BX))
        if f is None:
            return self.fail(uc, 6)
        whence = uc.reg_read(UC_X86_REG_AL)
        off = (uc.reg_read(UC_X86_REG_CX) << 16) | uc.reg_read(UC_X86_REG_DX)
        if whence > 2:
            return self.fail(uc, 0x0c)
        f.seek(off, whence)
        new = f.tell()
        uc.reg_write(UC_X86_REG_DX, (new >> 16) & 0xFFFF)
        uc.reg_write(UC_X86_REG_AX, new & 0xFFFF)
        self.ok(uc)

    def find_first(self, uc):
        if self.dta == 0:
            return self.fail(uc, 6)
        ddir = self.parent_dir(uc)
        if ddir is None:
            return self.fail(uc, 3)
        _, pattern = split_parent(self.dos_path(uc))
        rx = wildcard_rx(pattern)
        names = [n for n in os.listdir(ddir)
                 if not os.path.isdir(os.path.join(ddir, n)) and rx.match(n.upper())]
        # reverse sorted order so the asm insertion sort is exercised
        names.sort(reverse=True)
        self.find_ctx = [ddir, names, 0]
        self.find_emit(uc)

    def find_next(self, uc):
        if self.find_ctx is None:
            return self.fail(uc, 0x12)
        self.find_emit(uc)

    def find_emit(self, uc):
        ddir, names, idx = self.find_ctx
        if idx >= len(names):
            self.find_ctx = None
            return self.fail(uc, 0x12)
        name = names[idx]
        host = os.path.join(ddir, name)
        st = os.stat(host)
        self.find_ctx[2] = idx + 1
        d = self.dta
        uc.mem_write(d + 0x15, b'\x20')                       # archive attr
        uc.mem_write(d + 0x16, b'\x00' * 4)                   # time + date
        uc.mem_write(d + 0x1a, st.st_size.to_bytes(4, 'little'))
        nm = name.upper().encode('ascii')[:NAME_SLOT - 1]
        uc.mem_write(d + 0x1e, nm.ljust(NAME_SLOT, b'\0')[:NAME_SLOT])
        self.ok(uc)

    # ---- int 1Ah ---------------------------------------------------------
    def int1a(self, uc):
        if uc.reg_read(UC_X86_REG_AH) != 0:
            raise DosError(msg='unimplemented int 1Ah',
                           code=uc.reg_read(UC_X86_REG_AH))
        uc.reg_write(UC_X86_REG_CX, (self.ticks >> 16) & 0xFFFF)
        uc.reg_write(UC_X86_REG_DX, self.ticks & 0xFFFF)
        uc.reg_write(UC_X86_REG_AL, 0)


def run_exe(exe_path, root, cwd='TONY2', ticks=0x1234, max_insns=200_000_000):
    """Run a 16-bit MZ EXE under the mini DOS; returns the AL exit code of
    int 21h AH=4Ch."""
    blob = open(exe_path, 'rb').read()
    if blob[:2] != b'MZ':
        raise ValueError(f'{exe_path}: not an MZ EXE')
    (e_magic, e_cblp, e_cp, e_crlc, e_cparhdr, e_minalloc, e_maxalloc,
     e_ss, e_sp, e_csum, e_ip, e_cs, e_lfarlc, e_ovno) = struct.unpack_from('<14H', blob, 0)
    if e_crlc != 0:
        raise ValueError('relocations not supported (e_crlc != 0)')
    img = blob[e_cparhdr * 16:]

    uc = Uc(UC_ARCH_X86, UC_MODE_16)
    uc.mem_map(0, MEM_SIZE)
    uc.mem_write(LOAD_SEG * 16, img)
    dos = MiniDos(root, cwd=cwd, ticks=ticks)

    def hook_intr(uc, intno, user_data):
        if intno == 0x21:
            dos.int21(uc)
        elif intno == 0x1a:
            dos.int1a(uc)
        else:
            raise DosError(msg=f'unhandled interrupt {intno:#x}')

    uc.hook_add(UC_HOOK_INTR, hook_intr)
    uc.reg_write(UC_X86_REG_CS, LOAD_SEG + e_cs)
    uc.reg_write(UC_X86_REG_EIP, e_ip)
    uc.reg_write(UC_X86_REG_SS, LOAD_SEG + e_ss)
    uc.reg_write(UC_X86_REG_SP, e_sp)
    uc.reg_write(UC_X86_REG_DS, PSP_SEG)
    uc.reg_write(UC_X86_REG_ES, PSP_SEG)
    try:
        uc.emu_start((LOAD_SEG + e_cs) * 16 + e_ip, 0, count=max_insns)
    except UcError as e:
        raise DosError(f'unicorn fault: {e}')
    if dos.exit_code is None:
        raise DosError('exited without int 21h AH=4Ch')
    return dos.exit_code
