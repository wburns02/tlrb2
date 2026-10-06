#!/usr/bin/env python3
"""Concurrency/latency probe: N simultaneous requests of one pilot function to a backend.
usage: probe.py hive|zai|zai-think|haiku N"""
import json, sys, time, re, os, subprocess, tempfile, tomllib, urllib.request
from concurrent.futures import ThreadPoolExecutor
import pilot

ITEM = {'set': 'B', 'program': 'MAIN', 'addr': '1000:3742'}

def zai(user, think):
    cfg = tomllib.load(open(os.path.expanduser('~/.kimi-code/config.toml'), 'rb'))['providers']['zai-coding-plan']
    body = {'model': 'glm-5.3-flash', 'messages': [{'role': 'system', 'content': pilot.SYSTEM}, {'role': 'user', 'content': user}],
            'temperature': 0.2, 'max_tokens': 16000, 'thinking': {'type': 'enabled' if think else 'disabled'}}
    req = urllib.request.Request(cfg['base_url'] + '/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + cfg['api_key']})
    r = json.load(urllib.request.urlopen(req, timeout=900))
    return r['choices'][0]['message'].get('content') or '', r.get('usage', {})

def hive(user):
    cc = pilot.load_hive()
    return cc.call_hive(cc.load_hive_key(), 'z-ai/glm-5.3-flash', pilot.SYSTEM, user,
                        temperature=0.2, max_tokens=16000, timeout_s=900)

def haiku(user):
    with tempfile.TemporaryDirectory() as d:
        p = subprocess.run(['claude', '-p', '--model', 'claude-haiku-4-5-20251001', '--tools', '', '--strict-mcp-config',
                            '--setting-sources', '', '--system-prompt', pilot.SYSTEM, '--output-format', 'json'],
                           input=user, capture_output=True, text=True, cwd=d, timeout=900)
    o = json.loads(p.stdout)
    if o.get('is_error'): raise RuntimeError(o.get('result', '')[:200])
    return o.get('result', ''), o.get('usage', {})

def one(backend, user):
    t = time.time()
    try:
        txt, usage = {'hive': hive, 'zai': lambda u: zai(u, False), 'zai-think': lambda u: zai(u, True), 'haiku': haiku}[backend](user)
        m = re.search(r'\[.*\]', txt, re.S)
        name = json.loads(m.group(0))[0].get('name') if m else None
        return dict(ok=bool(m), secs=round(time.time() - t, 1), name=name,
                    out=usage.get('completion_tokens', usage.get('output_tokens')))
    except Exception as e:
        return dict(ok=False, secs=round(time.time() - t, 1), err=repr(e)[:160])

if __name__ == '__main__':
    backend, n = sys.argv[1], int(sys.argv[2])
    user = pilot.fn_block(ITEM)
    t = time.time()
    with ThreadPoolExecutor(n) as ex:
        res = list(ex.map(lambda _: one(backend, user), range(n)))
    ok = [r for r in res if r['ok']]
    print(json.dumps(dict(backend=backend, n=n, ok=len(ok), wall=round(time.time() - t, 1),
                          secs=sorted(r['secs'] for r in ok), names=sorted({str(r['name']) for r in ok}),
                          out_tokens=[r.get('out') for r in ok][:3],
                          errors=[r['err'] for r in res if 'err' in r][:3])))
