#!/usr/bin/env python3
"""Static knowledge base over all 8 programs: relocation masks, DGROUP strings, cross-program function dedupe, seeds.

usage: kb.py build      -> /mnt/nvme/tlrb2/re/units.json (one unit per distinct function body) + seeds
Library: load_programs(), annotate(prog, fn) gives the disassembly with DS strings resolved.

Dedupe keys (per function):
  strict = bytes with relocated words, near call/jmp rel16 and far call/jmp targets zeroed
  loose  = instruction text with every hex number >= 0x100 replaced by N (globals, call targets, big constants)
A unit is a loose group when every program has at most one member and the function is >= 16 bytes, else strict.
"""
import sys, os, re, json, struct, hashlib
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'hive'))
from fninfo import Program

T = '/mnt/nvme/tlrb2'
R = f'{T}/re'
PROGS = ['MAIN', 'BB', 'UTIL', 'DRAFT', 'BACK', 'MANAGE', 'PLAY', 'CONTROL']
DGROUP = {'MAIN': 0x40fa, 'BB': 0x5120, 'UTIL': 0x3954, 'DRAFT': 0x1f31, 'BACK': 0x2c71, 'MANAGE': 0x28bf,
          'PLAY': 0x170a, 'CONTROL': 0x123e}

# thin int 21h wrappers (<= 60 B, no callees), each checked by eye 2026-10-06 (tools/hive/find_dos_wrappers.py)
DOS_NAMES = {'07': 'dos_getch_noecho', '0b': 'dos_kbhit', '0e': 'dos_setdisk', '19': 'dos_getdisk',
             '1c': 'dos_getfatinfo', '25': 'dos_setvect', '2a': 'dos_getdate', '2b': 'dos_setdate',
             '2c': 'dos_gettime', '2d': 'dos_settime', '30': 'dos_version', '35': 'dos_getvect',
             '36': 'dos_getdfree', '39': 'dos_mkdir', '3b': 'dos_chdir', '3c': 'dos_creat', '3d': 'dos_open',
             '3e': 'dos_close', '3f': 'dos_read', '40': 'dos_write', '41': 'dos_unlink', '42': 'dos_lseek',
             '43': 'dos_chmod', '44': 'dos_ioctl', '4a': 'dos_setblock', '4c': 'dos_exit', '56': 'dos_rename'}
# MAIN runtime functions labeled by hand from disassembly (pilot set B)
RTL_NAMES = {'1000:46cb': ('strcpy', 'copy NUL-terminated far string'),
             '1000:468c': ('strcat', 'append far string'),
             '1000:4735': ('strlen', 'length of far string'),
             '1000:3e4c': ('memcpy', 'copy n bytes between far pointers'),
             '1000:3e70': ('setmem', 'fill n bytes with a value'),
             '1000:24d8': ('farmalloc', 'far heap allocate'),
             '1000:23c4': ('farfree', 'far heap free'),
             '1000:370d': ('fopen', 'open a FILE stream'),
             '1000:36c3': ('__getfp', 'find an unused FILE slot in _streams'),
             '1000:3852': ('fread', 'read items from a stream'),
             '1000:3b89': ('fwrite', 'write items to a stream'),
             '1000:3742': ('fprintf', 'formatted write to a stream'),
             '1000:409e': ('printf', 'formatted write to stdout'),
             '1000:1565': ('__IOerror', 'map DOS error to errno, return -1'),
             '1000:427e': ('__fputn', 'write n bytes to a stream'),
             '1000:375e': ('__fgetn', 'read n bytes from a stream'),
             '1000:0897': ('modex_clear_page', 'clear a Mode X planar VGA page (all planes, 16000 B at A000)'),
             '1000:7f22': ('per_mille_ratio', 'round(a*1000/b), 0 if b == 0 (batting-average style ratio)')}

_P = {}
def prog(n):
    if n not in _P:
        P = Program(n)
        P.relocs = relocs(n)
        P.dsbase = (DGROUP[n] - 0x1000) * 16
        P.strings = ds_strings(P)
        add_call_targets(P)
        _P[n] = P
    return _P[n]

def gaddr(lin):
    """Ghidra's display address for a flat offset (64 KB chunks: 1000:xxxx, 2000:xxxx, ...)."""
    return '%04x:%04x' % (0x1000 + (lin >> 16) * 0x1000, lin & 0xffff)

def add_call_targets(P):
    """Functions Ghidra never created (flat/<EXE>.seeds.extra.txt) become pseudo functions that end at the next
    known start; a Ghidra function that swallowed one is cut at that start. Then callees/callers are recomputed
    from the disassembly (far calls by linear address, overlay stub thunks followed, near calls)."""
    m = json.load(open(f'{T}/flat/{P.name}.map.json'))
    ex = f'{T}/flat/{P.name}.seeds.extra.txt'
    extra = [l.strip() for l in open(ex)] if os.path.exists(ex) else []
    starts = sorted(P.lin(a) for a in P.fn)
    import bisect
    for s in extra:
        if not s:
            continue
        lin = P.lin(s)
        a = gaddr(lin)
        if a in P.fn:
            continue
        i = bisect.bisect_right(starts, lin)
        if i > 0:  # cut the containing function
            c = gaddr(starts[i - 1])
            if starts[i - 1] + P.fn[c]['size'] > lin:
                P.fn[c]['size'] = lin - starts[i - 1]
        end = starts[i] if i < len(starts) else len(P.flat)
        P.fn[a] = dict(addr=a, name='FUN_' + a.replace(':', '_'), size=min(end - lin, 1500), callers=[], callees=[],
                       pseudo=True)
        bisect.insort(starts, lin)
    thunk = {}
    for o in m['overlays']:
        for e in o['entries']:
            thunk[P.lin(e['stub'])] = P.lin(e['target'])
    bylin = {P.lin(a): a for a in P.fn}
    for f in P.fn.values():
        f['callers'] = []
    for a, f in P.fn.items():
        seg = int(a.split(':')[0], 16)
        cs = []
        for ad, hx, ins in P.disasm(f):
            mt = re.match(r'call (0x[0-9a-f]+):(0x[0-9a-f]+)$', ins)
            if mt:
                lin = (int(mt.group(1), 16) - 0x1000) * 16 + int(mt.group(2), 16)
            elif hx.upper().startswith('E8') and re.match(r'call (0x[0-9a-f]+)$', ins):
                lin = (seg - 0x1000) * 16 + int(ins.split()[1], 16)
            else:
                continue
            lin = thunk.get(lin, lin)
            t = bylin.get(lin)
            if t and t not in cs:
                cs.append(t)
        f['callees'] = cs
    for a, f in P.fn.items():
        for c in f['callees']:
            P.fn[c]['callers'].append(a)

def load_programs():
    return {n: prog(n) for n in PROGS}

def relocs(n):
    """Linear offsets (in the flat image) of every word the loader or overlay manager patches."""
    m = json.load(open(f'{T}/flat/{n}.map.json'))
    d = open(os.path.join(T, m['exe']), 'rb').read()
    cblp, cp, crlc, hdrpar = struct.unpack('<4H', d[2:10])
    rlo = struct.unpack('<H', d[0x18:0x1a])[0]
    out = set()
    for i in range(crlc):
        off, seg = struct.unpack('<2H', d[rlo + 4 * i:rlo + 4 * i + 4])
        out.add(seg * 16 + off)
    img_end = (cp - 1) * 512 + (cblp or 512)
    ovl_data = img_end + 16
    for o in m['overlays']:
        base = (int(o['ovl_seg'], 16) - 0x1000) * 16
        fo = ovl_data + o['fileoff'] + o['codesize']
        for k in range(o['fixups']):
            out.add(base + struct.unpack('<H', d[fo + 2 * k:fo + 2 * k + 2])[0])
        for e in o['entries']:  # rewritten stub thunks EA off seg
            s, of = (int(x, 16) for x in e['stub'].split(':'))
            out.add((s - 0x1000) * 16 + of + 3)
    return out

def ds_strings(P):
    """DS offset -> string, for NUL-terminated printable runs (len >= 3) that start after a NUL."""
    m = json.load(open(f'{T}/flat/{P.name}.map.json'))
    d = P.flat[P.dsbase:m['image_bytes']]
    out = {}
    for mt in re.finditer(rb'[\x20-\x7e\r\n\t]{3,}\x00', d):
        s = mt.start()
        if s == 0 or d[s - 1] == 0:
            out[s] = mt.group()[:-1].decode('latin1')
    return out

def masked(P, f):
    b = bytearray(P.bytes(f))
    p0 = P.lin(f['addr'])
    for i in range(len(b) - 1):
        if p0 + i in P.relocs:
            b[i] = b[i + 1] = 0
    for a, hx, ins in P.disasm(f):
        i = a - int(f['addr'].split(':')[1], 16)
        op = hx[:2].upper()
        if op in ('E8', 'E9') and len(hx) == 6:
            b[i + 1:i + 3] = b'\0\0'
        elif op in ('9A', 'EA') and len(hx) == 10:
            b[i + 1:i + 5] = b'\0\0\0\0'
    return bytes(b)

NUM = re.compile(r'0x([0-9a-f]+)')
def loose_text(P, f):
    rows = []
    for a, hx, ins in P.disasm(f):
        rows.append(NUM.sub(lambda m: 'N' if int(m.group(1), 16) >= 0x100 else m.group(0), ins))
    return '\n'.join(rows)

IMM = re.compile(r'^(mov|push)\b')
def str_imms(ins):
    """Word immediates (not jump targets, not memory displacements, not byte operands) that could be DS pointers."""
    if not IMM.match(ins) or 'byte' in ins:
        return []
    ops = ins.split(None, 1)[1] if ' ' in ins else ''
    src = ops.split(',')[-1].strip()
    if '[' in src or src.startswith(('cs:', 'es:', 'ss:')):
        return []
    mt = re.fullmatch(r'(?:word )?0x([0-9a-f]+)', src)
    v = int(mt.group(1), 16) if mt else -1
    return [v] if v >= 0x100 else []

def annotate(P, f, max_lines=400):
    """Disassembly with DS string literals and globals marked."""
    seg = f['addr'].split(':')[0]
    out = []
    rows = P.disasm(f)
    for a, hx, ins in rows[:max_lines]:
        notes = []
        for v in str_imms(ins):
            if v in P.strings:
                notes.append('ds:%04x "%s"' % (v, P.strings[v][:60].replace('\n', '\\n').replace('\r', '\\r')))
        mm = re.search(r'\[(?:ds:)?0x([0-9a-f]+)\]', ins)
        if mm and not re.search(r'\[(?:cs|es|ss):', ins):
            notes.append('global ds:%04x' % int(mm.group(1), 16))
        out.append(f'{seg}:{a:04x}  {hx:<14} {ins}' + ('   ; ' + '; '.join(notes) if notes else ''))
    if len(rows) > max_lines:
        out.append(f'... ({len(rows) - max_lines} more instructions omitted)')
    return '\n'.join(out)

def strings_used(P, f):
    s = []
    for a, hx, ins in P.disasm(f):
        for v in str_imms(ins):
            if v in P.strings and P.strings[v] not in s:
                s.append(P.strings[v])
    return s

def build():
    os.makedirs(R, exist_ok=True)
    Ps = load_programs()
    fns = []  # (prog, addr, strict, loose, size)
    for n, P in Ps.items():
        for a, f in P.fn.items():
            st = hashlib.sha1(masked(P, f)).hexdigest()[:16]
            lo = hashlib.sha1(loose_text(P, f).encode()).hexdigest()[:16] if f['size'] >= 16 else None
            fns.append((n, a, st, lo, f['size']))
        print(n, len(P.fn), 'functions', len(P.relocs), 'relocs', len(P.strings), 'strings', flush=True)
    by_loose = defaultdict(list)
    for x in fns:
        if x[3]:
            by_loose[x[3]].append(x)
    key = {}
    for lo, xs in by_loose.items():
        progs = [x[0] for x in xs]
        if len(progs) == len(set(progs)):
            for x in xs:
                key[(x[0], x[1])] = 'L' + lo
    units = defaultdict(list)
    for x in fns:
        units[key.get((x[0], x[1]), 'S' + x[2] + (x[0] if False else ''))].append([x[0], x[1]])
    # strict groups may hold several members of one program (e.g. identical thunks); that is fine: same body.
    order = {n: i for i, n in enumerate(PROGS)}
    U = []
    for k, ms in units.items():
        ms.sort(key=lambda m: (order[m[0]], m[1]))
        U.append(dict(key=k, members=ms, rep=ms[0], size=Ps[ms[0][0]].fn[ms[0][1]]['size']))
    # seeds
    seeds = {}
    m2u = {(m[0], m[1]): u['key'] for u in U for m in u['members']}
    for x in json.load(open(f'{T}/hive/pilot/dos_thin.json')):
        k = m2u.get((x['program'], x['addr']))
        if k is None:
            print('seed not a function start (skipped):', x['program'], x['addr'], DOS_NAMES[x['ah']]); continue
        seeds[k] = dict(name=DOS_NAMES[x['ah']], purpose=f"DOS int 21h AH={x['ah']} wrapper", kind='dos',
                        confidence=1.0, source='seed')
    for a, (nm, purpose) in RTL_NAMES.items():
        if ('MAIN', a) not in m2u:
            print('seed not a function start (skipped): MAIN', a, nm); continue
        seeds[m2u[('MAIN', a)]] = dict(name=nm, purpose=purpose, kind='rtl', confidence=1.0, source='seed')
    json.dump(dict(units=U, seeds=seeds), open(f'{R}/units.json', 'w'))
    multi = sum(1 for u in U if len(u['members']) > 1)
    print(f'{len(fns)} functions -> {len(U)} units ({multi} shared by 2+ functions, '
          f'{sum(len(u["members"]) for u in U if len(u["members"]) > 1)} functions in them); {len(seeds)} seeds')

if __name__ == '__main__':
    if sys.argv[1] == 'build':
        build()
