"""Ground truth set A: small functions whose only DOS call is int 21h with a constant AH.
Truth = the DOS service, read from the instruction bytes (independent of any model)."""
import re, json, sys, hashlib
from fninfo import Program

def ah_before(rows, i):
    """Constant AH in effect at rows[i] (an int 0x21), scanning back to the last AH write; None if unknown."""
    for a, hx, ins in reversed(rows[:i]):
        m = re.match(r'mov ah,0x([0-9a-f]+)$', ins)
        if m: return int(m.group(1), 16)
        m = re.match(r'mov ax,0x([0-9a-f]+)$', ins)
        if m: return int(m.group(1), 16) >> 8
        if re.match(r'(mov|xchg|xor|or|and|add|sub|inc|dec|pop|lodsw|cbw|mul|div|imul|idiv|cwd|lahf|in) (ah|ax)\b', ins) \
           or re.search(r',(ah|ax)$', ins) and ins.startswith('xchg') or ins.startswith(('call', 'lodsw', 'lahf', 'cbw')):
            return None
        if ins.startswith(('jmp', 'ret', 'j')) and not ins.startswith('jmp short') and False:
            return None
    return None

out, seen = [], set()
for name in ['MAIN', 'BB', 'UTIL', 'DRAFT', 'BACK', 'MANAGE', 'PLAY', 'CONTROL']:
    P = Program(name)
    for f in P.fn.values():
        if not (4 <= f['size'] <= 160): continue
        rows = P.disasm(f)
        ints = [i for i, r in enumerate(rows) if r[2] == 'int 0x21']
        if len(rows) and any(r[2].startswith('int ') and r[2] != 'int 0x21' for r in rows): continue
        if not ints: continue
        ahs = {ah_before(rows, i) for i in ints}
        if len(ahs) != 1 or None in ahs: continue
        key = hashlib.sha1(bytes(P.bytes(f))).hexdigest()
        if key in seen: continue
        seen.add(key)
        out.append(dict(program=name, addr=f['addr'], size=f['size'], ah=f'{ahs.pop():02x}',
                        n_int=len(ints), callees=len(f['callees'])))
for o in out: print(json.dumps(o))
