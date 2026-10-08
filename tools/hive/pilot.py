#!/usr/bin/env python3
"""GLM-Flash function-naming pilot. usage: pilot.py build | run | score
build: items.jsonl (50 functions: A 18 DOS wrappers, B 18 RTL/known, C 14 game, no truth); run: Hive calls -> proposals.jsonl; score: report."""
import json, os, sys, random, re, importlib.machinery, importlib.util, time
from concurrent.futures import ThreadPoolExecutor
from fninfo import Program

D = '/mnt/nvme/tlrb2/hive/pilot'
PROGS = {}
def prog(n):
    if n not in PROGS: PROGS[n] = Program(n)
    return PROGS[n]

DOS = {'07': ['getch', 'keyboard', 'console input', 'read key', 'read a key', 'character input', 'without echo', 'wait for key', 'keypress'],
       '0b': ['kbhit', 'keyboard', 'input status', 'key available', 'key pressed', 'keystroke'],
       '0e': ['setdisk', 'select drive', 'set drive', 'set current drive', 'select disk', 'change drive'],
       '19': ['getdisk', 'current drive', 'get drive', 'default drive'],
       '25': ['setvect', 'set interrupt vector', 'set vector', 'install handler', 'install interrupt'],
       '2a': ['getdate', 'get date', 'system date', 'current date'],
       '2c': ['gettime', 'get time', 'system time', 'current time'],
       '30': ['version'],
       '35': ['getvect', 'get interrupt vector', 'get vector'],
       '36': ['disk free', 'free disk', 'getdfree', 'free space', 'disk space'],
       '39': ['mkdir', 'make directory', 'create directory', 'create a directory'],
       '3b': ['chdir', 'change directory', 'change the current directory', 'set current directory'],
       '3c': ['creat', 'create'],
       '3d': ['open'],
       '3e': ['close'],
       '3f': ['read'],
       '40': ['write'],
       '41': ['unlink', 'delete', 'remove'],
       '42': ['seek'],
       '43': ['chmod', 'attribute', 'access'],
       '4a': ['setblock', 'resize', 'brk', 'realloc', 'shrink', 'modify memory'],
       '56': ['rename'],
       '1c': ['allocation', 'drive info', 'disk info', 'drive data', 'cluster', 'fat'],
       '2b': ['setdate', 'set date', 'set system date', 'set the system date'],
       '2d': ['settime', 'set time', 'set system time', 'set the system time'],
       '44': ['isatty', 'ioctl', 'device info', 'character device', 'is a device', 'tty', 'device'],
       '4c': ['exit', 'terminate']}

RTL = {'1000:46cb': ('strcpy', ['strcpy', 'string copy', 'copy string', 'copies a null-terminated', 'copy a null-terminated', 'copies a string']),
       '1000:468c': ('strcat', ['strcat', 'concatenat', 'append']),
       '1000:4735': ('strlen', ['strlen', 'string length', 'length of']),
       '1000:3e4c': ('memcpy', ['memcpy', 'memory copy', 'copy memory', 'copies n bytes', 'copy bytes', 'block copy', 'movmem']),
       '1000:3e70': ('setmem (memset)', ['setmem', 'memset', 'fill memory', 'fills memory', 'fill a block', 'fill bytes', 'fills a block', 'fill buffer']),
       '1000:24d8': ('farmalloc', ['malloc', 'allocate', 'alloc']),
       '1000:23c4': ('farfree', ['free', 'release', 'dealloc']),
       '1000:370d': ('fopen', ['fopen', 'open a file', 'open file', 'opens a file', 'open a stream', 'open stream']),
       '1000:36c3': ('__getfp (find unused FILE slot)', ['getfp', 'free file', 'unused file', 'free stream', 'unused stream', 'available stream', 'available file', 'free slot', 'empty slot', 'unused slot', 'unused entry', 'free entry']),
       '1000:3852': ('fread', ['fread']),
       '1000:3b89': ('fwrite', ['fwrite']),
       '1000:3742': ('fprintf', ['fprintf']),
       '1000:409e': ('printf (stdout)', ['printf']),
       '1000:1565': ('__IOerror (DOS error -> errno, return -1)', ['ioerror', 'errno', 'error code', 'dos error']),
       '1000:427e': ('__fputn (write n bytes to stream)', ['fputn', 'write', 'output']),
       '1000:375e': ('__fgetn (read n bytes from stream)', ['fgetn', 'read']),
       '1000:0897': ('clear a Mode X planar VGA page (all planes, 16000 B at A000)', ['clear', 'fill', 'erase', 'blank']),
       '1000:7f22': ('round(a*1000/b), 0 if b==0 (per-mille ratio, e.g. batting average)', ['1000', 'per mille', 'permille', 'average', 'percentage', 'ratio', 'thousand'])}

def build():
    random.seed(7)
    items = []
    # thin wrappers only (<= 60 B, no callees), smallest per service; each was checked by eye 2026-10-06
    cands = json.load(open(f'{D}/dos_thin.json'))
    for ah in sorted({x['ah'] for x in cands}):
        x = min((x for x in cands if x['ah'] == ah), key=lambda x: x['size'])
        items.append(dict(set='A', program=x['program'], addr=x['addr'], truth=f'DOS int 21h AH={ah}', ah=ah))
    for a, (t, _) in RTL.items():
        items.append(dict(set='B', program='MAIN', addr=a, truth=t))
    pool = []
    for n in ['UTIL', 'BB']:
        P = prog(n)
        for f in P.fn.values():
            if int(f['addr'][:4], 16) >= 0x2000 and 80 <= f['size'] <= 400 and P.bytes(f)[:3] == b'\x55\x8b\xec':
                pool.append((n, f['addr']))
    for n, a in random.sample(pool, 14):
        items.append(dict(set='C', program=n, addr=a, truth=None))
    random.shuffle(items)
    with open(f'{D}/items.jsonl', 'w') as fh:
        for it in items: fh.write(json.dumps(it) + '\n')
    print(len(items), 'items')

SYSTEM = """You are a reverse engineer naming functions in a 1993 DOS game, Tony La Russa Baseball II, built with
Borland C++ 3.x in the large memory model (far calls, retf, stack args start at [bp+6]). It links the Borland C runtime
and the PKWARE Data Compression Library. Code comes from a Ghidra export: the data segment register is not set yet, so
global data shows as raw offsets, strings are not resolved, and function boundaries can be wrong (some entries start
mid-function). Callee names are not known yet (FUN_seg_off).

For each function you get its address, size, caller count, callees, disassembly and decompiled C. Return ONLY a JSON
array, one object per function, in input order:
{"addr": "seg:off", "name": "snake_case or the exact Borland RTL name if you recognize it",
 "purpose": "one sentence", "kind": "rtl|dos|graphics|io|game|unknown",
 "confidence": 0.0-1.0, "evidence": ["concrete facts from the code that support the name"]}

A wrong confident name is far worse than "unknown". Only claim game meaning (batting, pitching, players, teams) when
the code itself shows it; otherwise describe what the code mechanically does and keep confidence low."""

def fn_block(it):
    P = prog(it['program']); f = P.fn[it['addr']]
    callees = ', '.join(f"{c} ({P.fn[c]['size']} B)" if c in P.fn else c for c in f['callees']) or 'none'
    c = P.decomp(f)
    if len(c) > 6000: c = c[:6000] + '\n/* ...rest omitted */'
    return (f"### {it['addr']}  (program {it['program']}.EXE, {f['size']} bytes, {len(f['callers'])} callers)\n"
            f"callees: {callees}\n\nDisassembly:\n{P.disasm_text(f)}\n\nDecompiled:\n{c}\n")

def load_hive():
    l = importlib.machinery.SourceFileLoader('cloud_code', os.path.expanduser('~/bin/cloud-code'))
    s = importlib.util.spec_from_loader('cloud_code', l); m = importlib.util.module_from_spec(s); l.exec_module(m)
    return m

def run():
    """Resumable: only items without a proposal are sent. BATCH and MAXTOK via argv[2], argv[3]."""
    cc = load_hive(); key = cc.load_hive_key()
    bs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    maxtok = int(sys.argv[3]) if len(sys.argv) > 3 else 48000
    items = [json.loads(l) for l in open(f'{D}/items.jsonl')]
    done = set()
    try:
        for r in map(json.loads, open(f'{D}/proposals.jsonl')):
            done |= {o.get('addr') for o in r.get('out', [])}
    except FileNotFoundError:
        pass
    todo = [it for it in items if it['addr'] not in done]
    batches = [todo[i:i + bs] for i in range(0, len(todo), bs)]
    def go(b):
        user = '\n'.join(fn_block(it) for it in b)
        t = time.time(); txt, usage, err = '', {}, None
        try:
            txt, usage = cc.call_hive(key, 'z-ai/glm-5.3-flash', SYSTEM, user,
                                      temperature=0.2, max_tokens=maxtok, timeout_s=900)
            m = re.search(r'\[.*\]', txt, re.S)
            if m:
                return dict(addrs=[it['addr'] for it in b], out=json.loads(m.group(0)), usage=usage,
                            secs=round(time.time() - t, 1), raw=txt, bs=bs)
            err = 'no JSON array in content'
        except Exception as e:
            err = repr(e)
        return dict(addrs=[it['addr'] for it in b], error=err, usage=usage, raw=txt,
                    secs=round(time.time() - t, 1), bs=bs)
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(go, batches))
    with open(f'{D}/proposals.jsonl', 'a') as fh:
        for r in res: fh.write(json.dumps(r) + '\n')
    print('todo', len(todo), 'batches', len(res), 'errors', sum('error' in r for r in res))

def score():
    items = [json.loads(l) for l in open(f'{D}/items.jsonl')]
    byaddr, tin, tout = {}, 0, 0
    for r in map(json.loads, open(f'{D}/proposals.jsonl')):
        for o in r.get('out', []): byaddr[o.get('addr')] = o
        u = r.get('usage') or {}; tin += u.get('prompt_tokens', 0); tout += u.get('completion_tokens', 0)
    rows = []
    for it in items:
        o = byaddr.get(it['addr'], {})
        text = (str(o.get('name', '')) + ' ' + str(o.get('purpose', ''))).lower()
        kws = DOS[it['ah']] if it['set'] == 'A' else RTL[it['addr']][1] if it['set'] == 'B' else None
        hit = None if kws is None else any(k in text for k in kws)
        rows.append((it['set'], it['program'], it['addr'], it['truth'], o.get('name'), o.get('confidence'), hit, o.get('purpose')))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    for r in rows: print(json.dumps(r))
    for s in 'AB':
        rs = [r for r in rows if r[0] == s]
        print(f'set {s}: auto-match {sum(bool(r[6]) for r in rs)}/{len(rs)}')
    print(f'tokens in {tin} out {tout}')

if __name__ == '__main__':
    {'build': build, 'run': run, 'score': score}[sys.argv[1]]()
