#!/usr/bin/env python3
"""Z.AI self-audit of accepted bulk names: the rename gate, since single-model names failed the Sonnet spot-check
(2026-10-06: ~20% of accepted names wrong at the name level).

usage: audit.py calib [--thinking]   re-judge the Sonnet-judged units in verify.jsonl with Z.AI, print agreement
       audit.py run [--thinking]     judge every accepted non-seed unit not yet audited -> /mnt/nvme/tlrb2/re/audit.jsonl
Same prompt and verdicts as verify.py (correct | plausible | wrong | cannot_tell). name_all.py merge renames only
units whose audit verdict is correct (see merge()).
"""
import sys, os, json, time, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
import name_all, bakeoff
from verify import SYS

OUT = f'{name_all.R}/audit.jsonl'
lock = threading.Lock()

def zai(user, thinking):
    cfg = __import__('tomllib').load(open(os.path.expanduser('~/.kimi-code/config.toml'), 'rb'))['providers']['zai-coding-plan']
    for i in range(4):
        try:
            r = bakeoff.openai_post(cfg['base_url'] + '/chat/completions', cfg['api_key'],
                                    {'model': 'glm-5.3-flash', 'temperature': 0.1, 'max_tokens': 8000 if thinking else 1500,
                                     'thinking': {'type': 'enabled' if thinking else 'disabled'},
                                     'messages': [{'role': 'system', 'content': SYS}, {'role': 'user', 'content': user}]},
                                    timeout=300)
            return bakeoff.parse(r['choices'][0]['message'].get('content') or '')
        except Exception as e:
            err = e
            time.sleep(5 * (i + 1))
    return dict(verdict='error', reason=repr(err)[:200])

def judge(S, k, m, thinking):
    user = name_all.prompt(S, k) + f"\n\nProposed name: {m['name']}\nProposed purpose: {m['purpose']}\n"
    v = zai(user, thinking)
    return dict(key=k, rep=S.units[k]['rep'], name=m['name'], conf=m['confidence'], thinking=thinking, **v)

def calib(thinking):
    S = name_all.State()
    merged = json.load(open(f'{name_all.R}/merged.json'))
    son = {}
    for l in open(f'{name_all.R}/verify.jsonl'):
        r = json.loads(l)
        if r.get('verdict') in ('correct', 'plausible', 'wrong') and r['key'] in merged and r['key'] in S.units:
            son[r['key']] = r
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda k: judge(S, k, merged[k], thinking), son))
    tp = fp = fn = tn = 0
    for r in res:
        s_bad = son[r['key']]['verdict'] == 'wrong'
        z_ok = r.get('verdict') == 'correct'
        print(f"{son[r['key']]['verdict']:9} zai={r.get('verdict'):11} {r['name']}")
        if z_ok and not s_bad: tp += 1
        elif z_ok and s_bad: fp += 1
        elif s_bad: tn += 1
        else: fn += 1
    print(f'thinking={thinking}: zai-correct kept {tp + fp} (sonnet-wrong among them {fp}); '
          f'rejected {tn + fn} (sonnet-wrong among them {tn})')

def run(thinking):
    S = name_all.State()
    merged = json.load(open(f'{name_all.R}/merged.json'))
    done = set()
    if os.path.exists(OUT):
        done = {json.loads(l)['key'] for l in open(OUT)}
    todo = [(k, m) for k, m in merged.items()
            if m.get('accept') and m['status'] != 'seed' and k not in done and k in S.units]
    print('to audit', len(todo), flush=True)
    fh = open(OUT, 'a')
    n = [0]
    def one(km):
        r = judge(S, km[0], km[1], thinking)
        with lock:
            fh.write(json.dumps(r) + '\n'); fh.flush()
            n[0] += 1
            if n[0] % 100 == 0:
                print('audited', n[0], flush=True)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, todo))
    print('finished', n[0], flush=True)

if __name__ == '__main__':
    th = '--thinking' in sys.argv
    {'calib': calib, 'run': run}[sys.argv[1]](th)
