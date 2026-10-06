#!/usr/bin/env python3
"""Bulk function naming over every unit in /mnt/nvme/tlrb2/re/units.json, callees first.

usage: name_all.py run [--limit N] [--backends zai,deepseek]   (resumable; appends to answers.jsonl)
       name_all.py status
       name_all.py merge      -> /mnt/nvme/tlrb2/re/names/<EXE>.tsv and merged.json

Two backends (Z.AI GLM-5.3-Flash with thinking off, DeepSeek V4.1 Flash on Hive) each answer every unit. A unit counts
as named for its callers as soon as one answer exists, so the frontier moves at the combined rate and the second
opinion follows. Callee names shown to the model are the current merged view, marked as unverified guesses.
"""
import sys, os, json, time, threading, random, re, traceback
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'hive'))
import kb
import bakeoff

R = kb.R
ANS = f'{R}/answers.jsonl'
CONC = {'zai': 4, 'deepseek': 3}

SYSTEM = """You are a reverse engineer naming functions in a 1993 DOS game, Tony La Russa Baseball II, built with
Borland C++ 3.x in the large memory model (far calls, retf, stack args start at [bp+6]; some 386 instructions). It links
the Borland C runtime, the PKWARE Data Compression Library, and the game's own VGA (Mode X), sound, file and UI code.
The code comes from a Ghidra export. Function boundaries can be wrong (some entries start mid-function or are data).

You get, for one function: address, size, caller count, callees (with names other models proposed; those are
UNVERIFIED guesses with a confidence, trust them only as far as their confidence), DS string literals the code loads
(resolved through DGROUP; occasionally a coincidental constant), the disassembly (DS strings and globals annotated) and
Ghidra's decompiled C (DS not set there, so globals are raw offsets).

Return ONLY a JSON array with one object:
[{"addr": "seg:off", "name": "snake_case, or the exact Borland RTL name if you recognize it",
  "purpose": "one sentence", "kind": "rtl|dos|pkware|graphics|sound|input|io|ui|game|math|data|unknown",
  "confidence": 0.0-1.0, "evidence": ["concrete facts from the code that support the name"]}]

A wrong confident name is far worse than "unknown". Only claim game meaning (batting, pitching, players, teams,
stats, schedule) when the code itself shows it (strings, record strides, callees whose names show it); otherwise
describe what the code mechanically does and keep confidence low. Confidence >= 0.6 means you would bet on it."""

lock = threading.Lock()

class State:
    def __init__(self):
        d = json.load(open(f'{R}/units.json'))
        self.units = {u['key']: u for u in d['units']}
        self.seeds = d['seeds']
        self.Ps = kb.load_programs()
        self.m2u = {(m[0], m[1]): k for k, u in self.units.items() for m in u['members']}
        # callee units of a unit = union over members
        self.deps = defaultdict(set)
        for k, u in self.units.items():
            for p, a in u['members']:
                for c in self.Ps[p].fn[a]['callees']:
                    ck = self.m2u.get((p, c))
                    if ck and ck != k:
                        self.deps[k].add(ck)
        self.callers = defaultdict(int)
        for k, u in self.units.items():
            for p, a in u['members']:
                self.callers[k] += len(self.Ps[p].fn[a]['callers'])
        self.ans = defaultdict(dict)  # key -> backend -> answer
        if os.path.exists(ANS):
            for line in open(ANS):
                r = json.loads(line)
                if 'out' in r:
                    self.ans[r['key']][r['backend']] = r['out']

    def named(self, k):
        return k in self.seeds or bool(self.ans.get(k))

    def view(self, k):
        """Merged name for display to callers: (name, purpose, conf, note)."""
        if k in self.seeds:
            s = self.seeds[k]
            return s['name'], s['purpose'], 1.0, 'verified'
        a = self.ans.get(k) or {}
        if not a:
            return None
        best = max(a.values(), key=lambda o: conf(o))
        others = [o for o in a.values() if o is not best]
        note = ''
        if others:
            note = 'two models agree' if agree(best, others[0]) else f"other model said {others[0].get('name')}"
        return best.get('name'), best.get('purpose'), conf(best), note

def conf(o):
    try:
        return float(o.get('confidence') or 0)
    except (TypeError, ValueError):
        return 0.0

STOP = {'get', 'set', 'fn', 'func', 'function', 'the', 'a', 'of', 'and', 'to', 'dos', 'int21', 'wrapper', 'far',
        'helper', 'do', 'proc', 'routine', 'handler'}
def toks(name):
    s = re.sub(r'([a-z])([A-Z])', r'\1_\2', str(name or '')).lower()
    return {t for t in re.split(r'[^a-z0-9]+', s) if t and t not in STOP}

def agree(a, b):
    ta, tb = toks(a.get('name')), toks(b.get('name'))
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.5 or ta <= tb or tb <= ta

def prompt(S, k):
    u = S.units[k]
    p, a = u['rep']
    P = S.Ps[p]
    f = P.fn[a]
    cl = []
    for c in f['callees']:
        ck = S.m2u.get((p, c))
        size = P.fn[c]['size'] if c in P.fn else '?'
        v = S.view(ck) if ck else None
        if v:
            nm, pu, cf, note = v
            cl.append(f'  {c} ({size} B): {nm} [conf {cf:.2f}{", " + note if note else ""}] {pu}')
        else:
            cl.append(f'  {c} ({size} B): not named yet')
    strs = kb.strings_used(P, f)
    also = [f'{m[0]} {m[1]}' for m in u['members'][1:]]
    c = P.decomp(f)
    if len(c) > 6000:
        c = c[:6000] + '\n/* ...rest omitted */'
    return (f"### {a}  (program {p}.EXE, {f['size']} bytes, {S.callers[k]} callers"
            + (f"; identical code also in {', '.join(also[:6])}" if also else '') + ")\n"
            f"callees:\n" + ('\n'.join(cl) if cl else '  none') + "\n"
            f"DS strings loaded: " + (json.dumps(strs[:20]) if strs else 'none') + "\n\n"
            f"Disassembly:\n{kb.annotate(P, f)}\n\nDecompiled:\n{c}\n")

def call_backend(b, user):
    if b == 'zai':
        cfg = __import__('tomllib').load(open(os.path.expanduser('~/.kimi-code/config.toml'), 'rb'))['providers']['zai-coding-plan']
        r = bakeoff.openai_post(cfg['base_url'] + '/chat/completions', cfg['api_key'],
                                {'model': 'glm-5.3-flash', 'temperature': 0.2, 'max_tokens': 4000,
                                 'thinking': {'type': 'disabled'},
                                 'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]},
                                timeout=300)
        return r['choices'][0]['message'].get('content') or '', r.get('usage', {})
    if b == 'deepseek':
        if bakeoff._cc is None:
            with lock:
                if bakeoff._cc is None:
                    cc = bakeoff.pilot.load_hive()
                    cc._HIVE_MODEL_MAP['deepseek-v4.1-flash'] = 'deepseek-ai/deepseek-v4.1-flash'
                    bakeoff._cc = cc
        txt, u = bakeoff._cc.call_hive(bakeoff._cc.load_hive_key(), 'deepseek-v4.1-flash', SYSTEM, user,
                                       temperature=0.2, max_tokens=16000, timeout_s=300)
        return txt, u or {}
    raise ValueError(b)

def run(limit=None, backends=('zai', 'deepseek')):
    S = State()
    todo = {b: {k for k in S.units if k not in S.seeds and b not in S.ans.get(k, {})} for b in backends}
    attempts = defaultdict(int)
    inflight = set()
    paused = {b: 0.0 for b in backends}
    fails = {b: 0 for b in backends}
    done_n = {b: 0 for b in backends}
    stop = threading.Event()
    t0 = time.time()
    fh = open(ANS, 'a')

    def pick(b):
        with lock:
            cand = [k for k in todo[b] if (k, b) not in inflight]
            if not cand:
                return None
            ready = [k for k in cand if all(S.named(d) for d in S.deps[k])]
            if not ready:
                # cycle or frontier waiting on in-flight work: release the least-blocked unit
                ready = sorted(cand, key=lambda k: (sum(not S.named(d) for d in S.deps[k]), S.units[k]['size']))[:1]
            # prefer units the other backend already answered (second opinion while context is fresh), then most callers
            k = max(ready, key=lambda k: (bool(S.ans.get(k)), S.callers[k], -S.units[k]['size']))
            inflight.add((k, b))
            return k

    def worker(b):
        while not stop.is_set():
            if limit and sum(done_n.values()) >= limit:
                return
            if time.time() < paused[b]:
                time.sleep(5); continue
            k = pick(b)
            if k is None:
                return
            t = time.time(); rec = None
            try:
                txt, usage = call_backend(b, prompt(S, k))
                out = bakeoff.parse(txt)
                rec = dict(key=k, backend=b, out=out, secs=round(time.time() - t, 1),
                           tin=usage.get('prompt_tokens'), tout=usage.get('completion_tokens'), ts=int(time.time()))
                fails[b] = 0
            except Exception as e:
                err = repr(e)[:300]
                code = getattr(e, 'code', None)
                attempts[(k, b)] += 1
                if code == 429 or '429' in err:
                    fails[b] += 1
                    time.sleep(min(60, 5 * fails[b]) + random.random() * 3)
                else:
                    fails[b] += 1
                if fails[b] >= 12:
                    paused[b] = time.time() + 600
                    print(f'[{b}] {fails[b]} consecutive failures, pausing 10 min. last: {err}', flush=True)
                    fails[b] = 0
                if attempts[(k, b)] >= 3:
                    rec = dict(key=k, backend=b, error=err, secs=round(time.time() - t, 1), ts=int(time.time()))
            with lock:
                inflight.discard((k, b))
                if rec:
                    todo[b].discard(k)
                    fh.write(json.dumps(rec) + '\n'); fh.flush()
                    if 'out' in rec:
                        S.ans[k][b] = rec['out']; done_n[b] += 1

    def reporter():
        while not stop.wait(60):
            el = time.time() - t0
            left = {b: len(todo[b]) for b in backends}
            rate = sum(done_n.values()) / el * 60
            msg = dict(elapsed_min=round(el / 60, 1), done=done_n, left=left, per_min=round(rate, 1),
                       named_units=sum(1 for k in S.units if S.named(k)), total_units=len(S.units),
                       paused=[b for b in backends if time.time() < paused[b]])
            json.dump(msg, open(f'{R}/status.json', 'w'))
            print(json.dumps(msg), flush=True)

    threads = [threading.Thread(target=worker, args=(b,)) for b in backends for _ in range(CONC[b])]
    rt = threading.Thread(target=reporter, daemon=True); rt.start()
    for th in threads: th.start()
    for th in threads: th.join()
    stop.set()
    print('finished', json.dumps(dict(done=done_n, left={b: len(todo[b]) for b in backends})), flush=True)

def merge():
    S = State()
    os.makedirs(f'{R}/names', exist_ok=True)
    merged = {}
    for k, u in S.units.items():
        if k in S.seeds:
            s = S.seeds[k]
            m = dict(name=s['name'], purpose=s['purpose'], kind=s['kind'], confidence=1.0, status='seed', alt=None)
        else:
            a = S.ans.get(k) or {}
            if not a:
                continue
            os_ = sorted(a.items(), key=lambda kv: -conf(kv[1]))
            (b1, o1) = os_[0]
            o2 = os_[1][1] if len(os_) > 1 else None
            c1 = conf(o1)
            if o2 is None:
                status = 'single'
            elif agree(o1, o2):
                status = 'agree'
            elif conf(o2) >= 0.6:
                status = 'conflict'
            else:
                status = 'differ'
            # accept for rename: high confidence and not contradicted by a confident second opinion
            accept = c1 >= 0.6 and status in ('agree', 'single', 'differ') and o1.get('name') not in (None, '', 'unknown')
            m = dict(name=o1.get('name'), purpose=o1.get('purpose'), kind=o1.get('kind'), confidence=c1,
                     status=status, accept=accept, by=b1,
                     alt=(f"{o2.get('name')} ({conf(o2):.2f}): {o2.get('purpose')}" if o2 else None),
                     evidence=o1.get('evidence'))
        m['members'] = u['members']
        merged[k] = m
    json.dump(merged, open(f'{R}/merged.json', 'w'), indent=0)
    per = defaultdict(list)
    for k, m in merged.items():
        for p, a in m['members']:
            per[p].append((a, m))
    for p, rows in per.items():
        with open(f'{R}/names/{p}.tsv', 'w') as fh:
            fh.write('addr\tname\tconfidence\tstatus\tkind\tpurpose\talt\n')
            for a, m in sorted(rows, key=lambda r: r[0]):
                fh.write('\t'.join(str(x).replace('\t', ' ').replace('\n', ' ') for x in
                                   (a, m['name'], f"{m['confidence']:.2f}", m['status'], m['kind'], m['purpose'], m.get('alt') or '')) + '\n')
    st = defaultdict(int)
    for m in merged.values():
        st[m['status']] += 1
        st['accept'] += bool(m.get('accept') or m['status'] == 'seed')
    print(dict(st), 'of', len(S.units), 'units')

def status():
    S = State()
    n = defaultdict(int)
    for k, a in S.ans.items():
        for b in a: n[b] += 1
    print(dict(n), 'units', len(S.units), 'seeds', len(S.seeds))
    if os.path.exists(f'{R}/status.json'):
        print(open(f'{R}/status.json').read())

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'run':
        lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
        bs = tuple(sys.argv[sys.argv.index('--backends') + 1].split(',')) if '--backends' in sys.argv else ('zai', 'deepseek')
        run(lim, bs)
    elif cmd == 'merge':
        merge()
    elif cmd == 'status':
        status()
    elif cmd == 'prompt':
        S = State(); print(prompt(S, S.m2u[(sys.argv[2], sys.argv[3])]))
