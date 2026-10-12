#!/usr/bin/env python3
"""Playoff team ids and realignment: the C ports tools/m4/teamids.h and tools/m4/realign.h against the Python
reference tools/m4/teamids.py and tools/m4/realign.py (contract C12.3, C12.5).

Synthetic 59771 B MAJs (1, 2 and 3 divisions, the 1993 and 1994 abbreviation sets, repeated abbreviations and
refusal cases) run through the host harness teamids_c/ti_host (built at import by build_ti.py). Every mode's output
is compared with the Python result byte for byte. The 16-bit TIHOST.EXE runs a sample of the same cases under
headless DOSBox-X when both it and the dosbox-x binary exist; otherwise that test skips.
Run:  python3 -m pytest -q tools/m4/test_teamids_c.py
"""
import functools
import os
import random
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
for _p in (_TOOLS, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest                                   # noqa: E402

import realign as ra                            # noqa: E402
import teamids as ti                            # noqa: E402

TI_C = os.path.join(_HERE, 'teamids_c')
HOST = os.path.join(TI_C, 'ti_host')
EXE = os.path.join(TI_C, 'TIHOST.EXE')
DOSBOX = '/mnt/nvme/src/dosbox-x/src/dosbox-x'
MAJ_SIZE = ra.MAJ_SIZE
UP = b'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
ALPHA = UP + UP.lower() + b'0123456789'
TAB256 = random.Random(0x256).randbytes(256)    # a table handed to plan as present (its bytes do not matter)


def _build():
    r = subprocess.run([sys.executable, os.path.join(TI_C, 'build_ti.py')],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed:\n' + r.stdout + r.stderr)
    if not os.path.exists(HOST):
        raise RuntimeError('host binary missing after build')


_build()


# ---------------------------------------------------------------- fixtures

def _swap_case(b):
    """ASCII case flipped for letters; every other byte (NULs included) kept."""
    return bytes(c ^ 0x20 if (0x41 <= c <= 0x5a or 0x61 <= c <= 0x7a) else c for c in b)


def _team_slots(nd):
    """The slots a team can hold: 0..15 with 1 or 2 divisions, the 15 division slots with 3."""
    return [s for s in range(ti.SLOTS) if (s % 8 < 5 if nd == 3 else s < 16)]


def _pick_stem(rnd, pool):
    """A team stem (8 B): fresh letters (sometimes 1..7 long with NUL padding, rarely an embedded NUL), or a
    repeat or a case change of an earlier stem."""
    r = rnd.random()
    if pool and r < 0.12:
        st = rnd.choice(pool)
    elif pool and r < 0.24:
        st = _swap_case(rnd.choice(pool))
    else:
        raw = bytearray(8)
        for i in range(rnd.choice((8, 8, 8, rnd.randint(1, 7)))):
            raw[i] = rnd.choice(ALPHA)
        if raw[2] and rnd.random() < 0.05:
            raw[1] = 0
        st = bytes(raw)
    pool.append(st)
    return st


def _name(rnd):
    return bytes(rnd.choice(ALPHA + b'  ') for _ in range(rnd.randint(2, 14))).ljust(16, b'\0')


def _rand_abbr(rnd):
    if rnd.random() < 0.05:
        return bytes((rnd.choice(UP), 0, rnd.choice(UP)))
    return bytes(rnd.choice(UP) for _ in range(rnd.choice((2, 3, 3)))).ljust(3, b'\0')


def _known_abbr(a, embed):
    if embed and len(a) == 2:
        return bytes((ord(a[0]), 0, ord(a[1])))
    return a.encode().ljust(3, b'\0')


def _build_maj(rnd, nd, teams, pool, allstar=(False, False)):
    """A MAJ holding teams[L] = [(slot, abbr3), ...]; stems and names are drawn here. Every other slot the division
    count uses gets a NUL first stem byte (no team), the all-star entry sits in slot 15 when asked, and the rest of
    the 59771 B is random junk (unused slots included)."""
    d = bytearray(rnd.randbytes(MAJ_SIZE))
    d[0x20c] = 2
    d[0x20d] = nd
    for L in (0, 1):
        s = ti.S[L]
        taken = {slot for slot, _ in teams[L]}
        for slot in _team_slots(nd):
            if slot not in taken:
                d[s + ti.O_STEM + 8 * slot] = 0
        if allstar[L] and 15 not in taken:
            d[s + ti.O_STEM + 8 * 15:s + ti.O_STEM + 8 * 15 + 8] = b'\0LLSTAR1'
            d[s + ti.O_NAMES + 16 * 15:s + ti.O_NAMES + 16 * 15 + 16] = b'\0LL STARS 1'.ljust(16, b'\0')
        for slot, abbr in teams[L]:
            d[s + ti.O_NAMES + 16 * slot:s + ti.O_NAMES + 16 * slot + 16] = _name(rnd)
            d[s + ti.O_ABBR + 3 * slot:s + ti.O_ABBR + 3 * slot + 3] = abbr
            d[s + ti.O_STEM + 8 * slot:s + ti.O_STEM + 8 * slot + 8] = _pick_stem(rnd, pool)
    return bytes(d)


def _random_teams(rnd, nd):
    """Per league and division 0..8 (2 divisions) or 0..5 (3) teams at random slots of that division."""
    teams = ([], [])
    per = 5 if nd == 3 else 8
    for L in (0, 1):
        for v in range(3 if nd == 3 else 2):
            for slot in rnd.sample(range(v * 8, v * 8 + per), rnd.randint(0, per)):
                teams[L].append((slot, _rand_abbr(rnd)))
    return teams


def _known_teams(rnd, layout, nd, shuffled, dups=(0, 0)):
    """Teams carrying the realign.KNOWN abbreviations of one layout (2 or 3 divisions). Sorted: the k-th known
    abbreviation at the k-th slot. Shuffled: random slots, and some 2-letter abbreviations with an embedded NUL.
    dups[L] repeats an abbreviation that many times."""
    teams = ([], [])
    for L in (0, 1):
        abbrs = [a for div in ra.KNOWN[layout][L] for a in div]
        abbrs += abbrs[1:2] * dups[L]
        slots = rnd.sample(_team_slots(nd), len(abbrs))
        if not shuffled:
            slots.sort()
        for slot, a in zip(slots, abbrs):
            teams[L].append((slot, _known_abbr(a, shuffled and rnd.random() < 0.5)))
    return teams


def _tables(rnd, d):
    """The table variants: None, the MAJ's make_table, a shuffled make_table, a case-changed one, and one with a
    non-empty entry zeroed (teams whose stem it held lose their id)."""
    base = ti.make_table(d)
    entries = [base[8 * k:8 * k + 8] for k in range(32)]
    shuffled = entries[:]
    rnd.shuffle(shuffled)
    live = [k for k in range(32) if entries[k][0]]
    missing = bytearray(base)
    if live:
        k = rnd.choice(live)
        missing[8 * k:8 * k + 8] = bytes(8)
    return [None, base, b''.join(shuffled), _swap_case(base), bytes(missing)]


def _hists(rnd):
    """HISTORY.DAT stand-ins: none, empty, 11 B (no byte 11), and 12 B with byte 11 at 0, 2, 3 and 7."""
    return [None, b'', rnd.randbytes(11)] + [rnd.randbytes(11) + bytes((b,)) for b in (0, 2, 3, 7)]


@functools.lru_cache(maxsize=None)
def _fixtures():
    """[{label, d, tables}]: 200 random MAJs, the 1993 (layout 2) and 1994 (layout 3) sets on 1, 2 and 3 divisions,
    repeated abbreviations, and the refusal cases."""
    rnd = random.Random(0x7a1b)
    pool = []
    out = []

    def add(label, d):
        out.append({'label': label, 'd': d, 'tables': _tables(rnd, d)})

    for i in range(200):
        nd = (1, 2, 3)[i % 3]
        teams = _random_teams(rnd, nd)
        allstar = (rnd.random() < 0.3, rnd.random() < 0.3)
        add('rand%d/nd%d' % (i, nd), _build_maj(rnd, nd, teams, pool, allstar))
    for layout in (2, 3):
        for nd in (1, 2, 3):
            for shuffled in (False, True):
                teams = _known_teams(rnd, layout, nd, shuffled)
                add('known%d/nd%d/%s' % (layout, nd, 'shuffled' if shuffled else 'sorted'),
                    _build_maj(rnd, nd, teams, pool, (False, shuffled)))
    # NL 13 on 3 divisions (12 known plus one repeat: target 2 matches the set and leaves one team out), NL 14 on
    # 2 divisions (12 known plus two repeats: target 3 matches and leaves two out), AL 15 (14 known plus one
    # repeat: odd for 3 divisions, too many for 2)
    add('dupNL13/nd3', _build_maj(rnd, 3, _known_teams(rnd, 2, 3, False, (0, 1)), pool))
    add('dupNL14/nd2', _build_maj(rnd, 2, _known_teams(rnd, 3, 2, True, (0, 2)), pool))
    add('dupAL15/nd2', _build_maj(rnd, 2, _known_teams(rnd, 3, 2, True, (1, 0)), pool))
    base = _build_maj(rnd, 2, _random_teams(rnd, 2), pool)
    add('short1000', base[:1000])
    add('short40000', base[:40000])
    for v in (1, 3):
        x = bytearray(base)
        x[0x20c] = v
        add('leagues%d' % v, bytes(x))
    for v in (0, 4):
        x = bytearray(base)
        x[0x20d] = v
        add('divs%d' % v, bytes(x))
    add('al16/nd2', _build_maj(rnd, 2, ([(s, _rand_abbr(rnd)) for s in range(16)],
                                        [(s, _rand_abbr(rnd)) for s in range(3)]), pool))
    add('al15/nd2', _build_maj(rnd, 2, ([(s, _rand_abbr(rnd)) for s in range(15)], []), pool))
    add('al13/nd2', _build_maj(rnd, 2, ([(s, _rand_abbr(rnd)) for s in range(13)], []), pool))
    add('nl16/nd1', _build_maj(rnd, 1, ([], [(s, _rand_abbr(rnd)) for s in range(16)]), pool))
    return out


# ---------------------------------------------------------------- helpers

def _put(path, data):
    with open(path, 'wb') as f:
        f.write(data)
    return path


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


def _run(*args):
    r = subprocess.run([HOST] + [str(a) for a in args], capture_output=True, text=True)
    assert r.returncode == 0, 'ti_host %s rc %d: %s' % (args[0], r.returncode, r.stderr)
    return r.stdout


def _same(got, exp, what):
    """Byte equality; on a mismatch name the first differing offset."""
    if got == exp:
        return
    n = min(len(got), len(exp))
    first = next((i for i in range(n) if got[i] != exp[i]), n)
    raise AssertionError('%s: C %d B, python %d B, first difference at %d'
                         % (what, len(got), len(exp), first))


def _teams_bytes(d, table):
    return b''.join(bytes((k, L, slot)) + st for k, L, slot, st in ti.teams(d, table))


def _maps_bytes(d, table):
    """The 624 B of ti_host maps: id_of_engine 0..255, id_of_slot (L 0..1, slot 0..23), slot_of_id 0..31 (L, slot
    or ff ff), stem_of_id 0..31 (8 B)."""
    out = bytearray()
    for e in range(256):
        out.append(ti.id_of_engine(d, table, e))
    for L in (0, 1):
        for slot in range(ti.SLOTS):
            k = ti.id_of_slot(d, table, L, slot)
            out.append(0xff if k is None else k)
    for k in range(32):
        p = ti.slot_of_id(d, table, k)
        out += bytes(p) if p else b'\xff\xff'
    for k in range(32):
        out += ti.stem_of_id(d, table, k).ljust(8, b'\0')
    return bytes(out)


# ---------------------------------------------------------------- C parity (host)

def test_fixture_set():
    fx = _fixtures()
    assert sum(f['label'].startswith('rand') for f in fx) >= 200
    assert all(len(f['tables']) == 5 for f in fx)


def test_host_teams_parity(tmp_path):
    maj_f, tab_f, out_f = (str(tmp_path / n) for n in ('maj.bin', 'tab.bin', 'out.bin'))
    for fx in _fixtures():
        _put(maj_f, fx['d'])
        for table in fx['tables']:
            tab_arg = '-' if table is None else _put(tab_f, table)
            _run('teams', maj_f, tab_arg, out_f)
            _same(_read(out_f), _teams_bytes(fx['d'], table), fx['label'] + ' teams')


def test_host_maps_parity(tmp_path):
    maj_f, tab_f, out_f = (str(tmp_path / n) for n in ('maj.bin', 'tab.bin', 'out.bin'))
    for fx in _fixtures():
        _put(maj_f, fx['d'])
        for table in (None, fx['tables'][2], fx['tables'][4]):
            tab_arg = '-' if table is None else _put(tab_f, table)
            _run('maps', maj_f, tab_arg, out_f)
            _same(_read(out_f), _maps_bytes(fx['d'], table), fx['label'] + ' maps')


def test_host_table_parity(tmp_path):
    maj_f, out_f = str(tmp_path / 'maj.bin'), str(tmp_path / 'out.bin')
    for fx in _fixtures():
        _put(maj_f, fx['d'])
        _run('table', maj_f, out_f)
        _same(_read(out_f), ti.make_table(fx['d']), fx['label'] + ' table')


def test_host_plan_parity(tmp_path):
    maj_f, hist_f = str(tmp_path / 'maj.bin'), str(tmp_path / 'hist.bin')
    outmaj_f, outtab_f = str(tmp_path / 'outmaj.bin'), str(tmp_path / 'outtab.bin')
    hists = _hists(random.Random(0x91a))
    for fx in _fixtures():
        d = fx['d']
        _put(maj_f, d)
        for hist in hists:
            hist_arg = '-' if hist is None else _put(hist_f, hist)
            for have in (0, 1):
                what = '%s plan hist=%s have=%d' % (fx['label'], 'none' if hist is None else len(hist), have)
                got = _run('plan', maj_f, hist_arg, have, outmaj_f, outtab_f)
                code, new, new_table, reason = ra.plan(d, hist, TAB256 if have else None)
                if code == 2:
                    exp_out = 'code 2\nreason %s\n' % reason
                else:
                    exp_out = 'code %d\n' % code
                assert got == exp_out, '%s: stdout %r, python %r' % (what, got, exp_out)
                exp_maj = new if code == 0 else d
                exp_tab = new_table if code == 0 and new_table is not None else b''
                _same(_read(outmaj_f), exp_maj, what + ' maj')
                _same(_read(outtab_f), exp_tab, what + ' table')


def test_host_realign_parity(tmp_path):
    maj_f, out_f = str(tmp_path / 'maj.bin'), str(tmp_path / 'out.bin')
    for fx in _fixtures():
        d = fx['d']
        _put(maj_f, d)
        for target in (2, 3):
            got = _run('realign', maj_f, target, out_f)
            new, reason = ra.realign(d, target)
            if new is None:
                assert got == 'rc 1\nreason %s\n' % reason, '%s target %d: %r' % (fx['label'], target, got)
                exp = d
            else:
                assert got == 'rc 0\n', '%s target %d: %r' % (fx['label'], target, got)
                exp = new
            _same(_read(out_f), exp, '%s realign %d' % (fx['label'], target))


def test_host_bad_target(tmp_path):
    """Python asserts the target is 2 or 3; C refuses the others with BAD TARGET and leaves the MAJ alone."""
    maj_f, out_f = str(tmp_path / 'maj.bin'), str(tmp_path / 'out.bin')
    d = _fixtures()[0]['d']
    _put(maj_f, d)
    for target in (0, 1, 4):
        assert _run('realign', maj_f, target, out_f) == 'rc 1\nreason BAD TARGET\n', target
        _same(_read(out_f), d, 'bad target %d' % target)


def test_host_usage_exit2(tmp_path):
    maj_f = _put(str(tmp_path / 'maj.bin'), _fixtures()[0]['d'])
    bad_tab = _put(str(tmp_path / 'tab.bin'), bytes(100))
    out = str(tmp_path / 'out.bin')
    cases = [
        ['bogus', 'a', 'b'],
        ['table', str(tmp_path / 'missing'), out],
        ['teams', maj_f, bad_tab, out],
        ['realign', maj_f, 'x', out],
        ['plan', maj_f, '-', '2', out, out],
    ]
    for args in cases:
        r = subprocess.run([HOST] + args, capture_output=True)
        assert r.returncode == 2, args


# ---------------------------------------------------------------- DOS parity (16-bit)

def _dos_ready():
    return os.path.isfile(EXE) and os.path.isfile(DOSBOX) and os.access(DOSBOX, os.X_OK)


def _dos_run(cdir, lines):
    """Write cdir/RUN.BAT (CRLF) and run it under headless dosbox-x (as test_statline.py does)."""
    with open(os.path.join(cdir, 'RUN.BAT'), 'wb') as f:
        for line in lines:
            f.write(line.encode('latin-1') + b'\r\n')
    env = dict(os.environ)
    env['SDL_VIDEODRIVER'] = 'dummy'
    env['SDL_AUDIODRIVER'] = 'dummy'
    cmds = ['-c', 'mount c ' + cdir, '-c', 'c:', '-c', 'RUN.BAT', '-c', 'exit']
    subprocess.run([DOSBOX, '-silent', '-set', 'mixer nosound=true', '-set', 'cpu cycles=max'] + cmds,
                   capture_output=True, text=True, timeout=600, env=env)


def _dos_check(cdir, name, exp, what, text=False):
    """A file the DOS run wrote, byte for byte; text output has DOS CR LF line ends, folded to LF first."""
    p = os.path.join(cdir, name)
    assert os.path.exists(p), '%s: %s not written' % (what, name)
    got = _read(p)
    if text:
        got = got.replace(b'\r\n', b'\n')
        exp = exp.encode()
    _same(got, exp, what + ' ' + name)


def test_dos_parity(tmp_path):
    """TIHOST.EXE (16-bit) against the Python reference on every 37th fixture: teams, maps, table, realign to 2 and
    3, plan with no hist and with a 12 B hist (byte 11 = 3). One headless DOSBox-X batch."""
    if not _dos_ready():
        pytest.skip('TIHOST.EXE or dosbox-x missing')
    cdir = str(tmp_path / 'dos')
    os.makedirs(cdir)
    shutil.copy2(EXE, os.path.join(cdir, 'TIHOST.EXE'))
    h3 = random.Random(0xd05).randbytes(11) + b'\x03'
    _put(os.path.join(cdir, 'H3.BIN'), h3)
    picks = _fixtures()[::37]
    lines = []
    for j, fx in enumerate(picks):
        d = fx['d']
        m, t = 'M%d.BIN' % j, 'T%d.BIN' % j
        _put(os.path.join(cdir, m), d)
        _put(os.path.join(cdir, t), ti.make_table(d))
        lines += [
            'TIHOST.EXE teams %s - A%d.BIN' % (m, j),
            'TIHOST.EXE teams %s %s B%d.BIN' % (m, t, j),
            'TIHOST.EXE maps %s - C%d.BIN' % (m, j),
            'TIHOST.EXE table %s D%d.BIN' % (m, j),
            'TIHOST.EXE realign %s 2 E%d.BIN > G%d.TXT' % (m, j, j),
            'TIHOST.EXE realign %s 3 F%d.BIN > H%d.TXT' % (m, j, j),
            'TIHOST.EXE plan %s - 0 PM%d.BIN PT%d.BIN > Q%d.TXT' % (m, j, j, j),
            'TIHOST.EXE plan %s H3.BIN 1 PN%d.BIN PU%d.BIN > R%d.TXT' % (m, j, j, j),
        ]
    _dos_run(cdir, lines)
    for j, fx in enumerate(picks):
        d, what = fx['d'], fx['label'] + ' dos'
        _dos_check(cdir, 'A%d.BIN' % j, _teams_bytes(d, None), what)
        _dos_check(cdir, 'B%d.BIN' % j, _teams_bytes(d, ti.make_table(d)), what)
        _dos_check(cdir, 'C%d.BIN' % j, _maps_bytes(d, None), what)
        _dos_check(cdir, 'D%d.BIN' % j, ti.make_table(d), what)
        for name, target, out_name in (('G', 2, 'E'), ('H', 3, 'F')):
            new, reason = ra.realign(d, target)
            exp_out = 'rc 1\nreason %s\n' % reason if new is None else 'rc 0\n'
            _dos_check(cdir, '%s%d.TXT' % (name, j), exp_out, what, text=True)
            _dos_check(cdir, '%s%d.BIN' % (out_name, j), d if new is None else new, what)
        code, new, new_table, reason = ra.plan(d, None, None)
        exp_out = 'code 2\nreason %s\n' % reason if code == 2 else 'code %d\n' % code
        _dos_check(cdir, 'Q%d.TXT' % j, exp_out, what, text=True)
        _dos_check(cdir, 'PM%d.BIN' % j, new if code == 0 else d, what)
        _dos_check(cdir, 'PT%d.BIN' % j, new_table if code == 0 else b'', what)
        code, new, _none, reason = ra.plan(d, h3, ti.make_table(d))
        exp_out = 'code 2\nreason %s\n' % reason if code == 2 else 'code %d\n' % code
        _dos_check(cdir, 'R%d.TXT' % j, exp_out, what, text=True)
        _dos_check(cdir, 'PN%d.BIN' % j, new if code == 0 else d, what)
        _dos_check(cdir, 'PU%d.BIN' % j, b'', what)
