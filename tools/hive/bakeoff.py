#!/usr/bin/env python3
"""Run the 50-function pilot (items.jsonl) through one backend, one function per call.
usage: bakeoff.py run BACKEND | score BACKEND...   (BACKEND: zai haiku deepseek local kimi)
Writes /mnt/nvme/tlrb2/hive/pilot/proposals_<BACKEND>.jsonl. Resumable (skips answered items)."""
import json, sys, time, os, re, subprocess, tempfile, tomllib, urllib.request, urllib.error
import importlib.machinery, importlib.util
from concurrent.futures import ThreadPoolExecutor
import pilot

D = pilot.D
CONC = {'zai': 4, 'haiku': 8, 'deepseek': 3, 'local': 2, 'kimi': 4}

def parse(txt):
    i = min((j for j in (txt.find('['), txt.find('{')) if j >= 0), default=-1)  # first JSON opener, not any '['
    v, _ = json.JSONDecoder().raw_decode(txt[i:])
    v = v if isinstance(v, list) else [v]
    if not v or not isinstance(v[0], dict):
        raise ValueError('not a list of objects')
    return v[0]

def openai_post(url, key, body, timeout=900):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def b_zai(user):
    cfg = tomllib.load(open(os.path.expanduser('~/.kimi-code/config.toml'), 'rb'))['providers']['zai-coding-plan']
    r = openai_post(cfg['base_url'] + '/chat/completions', cfg['api_key'],
                    {'model': 'glm-5.3-flash', 'temperature': 0.2, 'max_tokens': 4000, 'thinking': {'type': 'disabled'},
                     'messages': [{'role': 'system', 'content': pilot.SYSTEM}, {'role': 'user', 'content': user}]})
    return r['choices'][0]['message'].get('content') or '', r.get('usage', {}).get('completion_tokens')

_cc = None
def b_deepseek(user):
    global _cc
    if _cc is None:
        _cc = pilot.load_hive(); _cc._HIVE_MODEL_MAP['deepseek-v4.1-flash'] = 'deepseek-ai/deepseek-v4.1-flash'
    txt, u = _cc.call_hive(_cc.load_hive_key(), 'deepseek-v4.1-flash', pilot.SYSTEM, user,
                           temperature=0.2, max_tokens=32000, timeout_s=900)
    return txt, u.get('completion_tokens')

def b_haiku(user):
    with tempfile.TemporaryDirectory() as d:
        p = subprocess.run(['claude', '-p', '--model', 'claude-haiku-4-5-20251001', '--tools', '', '--strict-mcp-config',
                            '--setting-sources', '', '--system-prompt', pilot.SYSTEM, '--output-format', 'json'],
                           input=user, capture_output=True, text=True, cwd=d, timeout=900)
    o = json.loads(p.stdout)
    if o.get('is_error'):
        raise RuntimeError(str(o.get('result'))[:200])
    return o.get('result', ''), o.get('usage', {}).get('output_tokens')

_lc = None
def b_local(user):
    global _lc
    if _lc is None:
        l = importlib.machinery.SourceFileLoader('local_code', os.path.expanduser('~/bin/local-code'))
        s = importlib.util.spec_from_loader('local_code', l); _lc = importlib.util.module_from_spec(s); l.exec_module(_lc)
    hit = _lc.owner_activity_recent(180)
    if hit:
        raise RuntimeError('GPU courtesy: owner active: ' + hit[:120])
    return _lc.call_ollama('qwen3-coder:30b', pilot.SYSTEM, user, ctx=16384, temperature=0.2,
                           keep_alive='10m', timeout_s=900), None

def b_kimi(user):
    """kimi is an agentic CLI: run it in bubblewrap with $HOME hidden except its own config, in an empty dir."""
    h = os.path.expanduser('~')
    with tempfile.TemporaryDirectory(dir='/tmp') as d:
        cmd = ['bwrap', '--ro-bind', '/', '/', '--tmpfs', h, '--bind', f'{h}/.kimi-code', f'{h}/.kimi-code',
               '--bind', f'{h}/.cache/kimi-code', f'{h}/.cache/kimi-code', '--bind', d, d, '--dev', '/dev',
               '--proc', '/proc', '--unshare-pid', '--die-with-parent', '--chdir', d,
               f'{h}/.kimi-code/bin/kimi', '-m', 'kimi-code/kimi-for-coding-highspeed', '-p',
               pilot.SYSTEM + '\n\nDo not use any tools. Answer directly.\n\n' + user]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if p.returncode:
        raise RuntimeError(f'kimi rc={p.returncode}: {p.stderr[-200:]}')
    return p.stdout, None

B = {'zai': b_zai, 'haiku': b_haiku, 'deepseek': b_deepseek, 'local': b_local, 'kimi': b_kimi}

def run(backend):
    out = f'{D}/proposals_{backend}.jsonl'
    items = [json.loads(l) for l in open(f'{D}/items.jsonl')]
    done = set()
    if os.path.exists(out):
        done = {r['addr'] for r in map(json.loads, open(out)) if 'out' in r}
    todo = [it for it in items if it['addr'] not in done]
    def go(it):
        user = pilot.fn_block(it)
        err = 'retries exhausted (429)'
        for attempt in range(4):
            t = time.time()
            try:
                txt, ntok = B[backend](user)
                return dict(addr=it['addr'], out=parse(txt), secs=round(time.time() - t, 1), out_tokens=ntok)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(5 * (attempt + 1)); continue
                err = repr(e)
            except Exception as e:
                err = repr(e)[:300]
            if 'courtesy' in err:
                break
        return dict(addr=it['addr'], error=err, secs=round(time.time() - t, 1))
    t0 = time.time()
    with ThreadPoolExecutor(CONC[backend]) as ex:
        res = list(ex.map(go, todo))
    with open(out, 'a') as fh:
        for r in res:
            fh.write(json.dumps(r) + '\n')
    print(backend, 'todo', len(todo), 'ok', sum('out' in r for r in res), 'wall', round(time.time() - t0, 1))

if __name__ == '__main__':
    if sys.argv[1] == 'run':
        run(sys.argv[2])

EXTRA = {'0e': ['setdrive'], '25': ['int_vector', 'interrupt vector'], '19': ['getdrive'], '1c': ['getfat'], '1000:36c3': ['free_slot', 'first_free', 'unused'],
         '1000:3742': ['fprintf']}

def load(backend):
    m = {}
    if backend == 'glm-hive':
        for r in map(json.loads, open(f'{D}/proposals.jsonl')):
            for o in r.get('out', []):
                m[o.get('addr')] = dict(o=o)
        return m, None
    rows = [json.loads(l) for l in open(f'{D}/proposals_{backend}.jsonl')]
    for r in rows:
        if 'out' in r:
            m[r['addr']] = dict(o=r['out'], secs=r['secs'], tok=r.get('out_tokens'))
    return m, rows

def score(backends, show):
    items = [json.loads(l) for l in open(f'{D}/items.jsonl')]
    print('backend    answered  A_ok  B_ok  hi_conf(>=.6) right/total  C_max_conf  C_hi  median_s')
    for b in backends:
        m, _ = load(b)
        a = bk = hi = hiok = chi = 0; cmax = 0; secs = []; misses = []
        for it in items:
            p = m.get(it['addr'])
            if not p: continue
            o = p['o']; secs.append(p.get('secs') or 0)
            try: conf = float(o.get('confidence') or 0)
            except (TypeError, ValueError): conf = 0
            text = (str(o.get('name', '')) + ' ' + str(o.get('purpose', ''))).lower()
            if it['set'] == 'C':
                cmax = max(cmax, conf); chi += conf >= 0.6
                if show and conf >= 0.6: misses.append(('C', it['program'], it['addr'], o.get('name'), conf, o.get('purpose')))
                continue
            kws = (pilot.DOS[it['ah']] + EXTRA.get(it['ah'], [])) if it['set'] == 'A' else \
                  (pilot.RTL[it['addr']][1] + EXTRA.get(it['addr'], []))
            ok = any(k in text for k in kws)
            if it['set'] == 'A': a += ok
            else: bk += ok
            if conf >= 0.6: hi += 1; hiok += ok
            if show and not ok: misses.append((it['set'], it['addr'], it['truth'], o.get('name'), conf, o.get('purpose')))
        secs.sort()
        print(f"{b:<10} {len(m):>5}    {a:>4}  {bk:>4}   {hiok:>3}/{hi:<3}                  {cmax:<5}      {chi:>3}   {secs[len(secs)//2] if secs else '-'}")
        for x in misses: print('   ', json.dumps(x)[:260])

if __name__ == '__main__' and sys.argv[1] == 'score':
    score([b for b in sys.argv[2:] if b != '--show'], '--show' in sys.argv)
