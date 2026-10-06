#!/usr/bin/env python3
"""Sonnet spot-check of accepted bulk names: precision estimate before renames land in Ghidra.

usage: verify.py [N] [SEED]    samples N accepted non-seed units (default 60), stratified: half game/ui/io-ish, half rest.
Runs headless `claude -p --model sonnet` (subscription, no tools) 4 at a time. Output: /mnt/nvme/tlrb2/re/verify.jsonl
and a summary line. Verdicts: correct | plausible | wrong | cannot_tell.
"""
import sys, os, json, random, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
import name_all, bakeoff

SYS = """You are a senior reverse engineer auditing function names that cheaper models proposed for a 1993 DOS game
(Tony La Russa Baseball II, Borland C++ 3.x large model). Judge ONLY from the code shown. Return ONLY JSON:
{"verdict": "correct|plausible|wrong|cannot_tell", "better_name": "snake_case or null", "reason": "one sentence"}
correct = the name and purpose match what the code does. plausible = consistent with the code but not provable from
it. wrong = the code contradicts the name or the purpose, or it claims meaning the code does not show."""

def one(S, k, m):
    user = name_all.prompt(S, k) + f"\n\nProposed name: {m['name']}\nProposed purpose: {m['purpose']}\n"
    with tempfile.TemporaryDirectory() as d:
        p = subprocess.run(['claude', '-p', '--model', 'sonnet', '--tools', '', '--strict-mcp-config',
                            '--setting-sources', '', '--system-prompt', SYS, '--output-format', 'json'],
                           input=user, capture_output=True, text=True, cwd=d, timeout=900)
    try:
        o = json.loads(p.stdout)
        v = bakeoff.parse(o.get('result', ''))
    except Exception as e:
        v = dict(verdict='error', reason=repr(e)[:200])
    return dict(key=k, rep=S.units[k]['rep'], name=m['name'], conf=m['confidence'], status=m['status'],
                kind=m.get('kind'), **v)

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 11)
    S = name_all.State()
    merged = json.load(open(f'{name_all.R}/merged.json'))
    acc = [(k, m) for k, m in merged.items() if m.get('accept') and m['status'] != 'seed']
    gameish = [x for x in acc if x[1].get('kind') in ('game', 'ui', 'io', 'data')]
    rest = [x for x in acc if x not in gameish]
    pick = random.sample(gameish, min(n // 2, len(gameish)))
    pick += random.sample(rest, min(n - len(pick), len(rest)))
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda km: one(S, *km), pick))
    with open(f'{name_all.R}/verify.jsonl', 'a') as fh:
        for r in res:
            fh.write(json.dumps(r) + '\n')
    from collections import Counter
    c = Counter(r.get('verdict') for r in res)
    cg = Counter(r.get('verdict') for r in res if r.get('kind') in ('game', 'ui', 'io', 'data'))
    print('all', dict(c), '| game/ui/io/data', dict(cg))
    for r in res:
        if r.get('verdict') == 'wrong':
            print('  WRONG', r['rep'], r['name'], r['conf'], '->', r.get('better_name'), '|', r.get('reason'))

if __name__ == '__main__':
    main()
