"""Tests for realign.py (contract C12.4 setting, C12.5 realignment, C12.6 apply).
Run:  python3 -m pytest -q tools/m4/test_realign.py
Fixtures are synthetic (test_teamids.build_maj) and built in tmp_path or in memory.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import maj  # noqa: E402
import realign as ra  # noqa: E402
import teamids as ti  # noqa: E402
from test_teamids import build_maj, abbr_at, CLASSIC, S  # noqa: E402

RA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'realign.py')
MAJ_NAME = 'CLASSIC.MAJ'
WRITTEN = {0x20a, 0x20d} | set(range(0x20e, 0x214))
for _s in S:
    WRITTEN |= set(range(_s + 0x0f, _s + 0x297)) | set(range(_s + 0x298, _s + 0x29b)) | set(range(_s + 0x2b3, _s + 0x32b))


def slots(d, L):
    return {abbr_at(d, L, slot): slot for L2, slot, _st in ti.maj_teams(d) if L2 == L}


def entry(d, L, slot):
    s = S[L]
    return (bytes(d[s + ti.O_NAMES + 16 * slot:s + ti.O_NAMES + 16 * slot + 16]),
            bytes(d[s + ti.O_ABBR + 3 * slot:s + ti.O_ABBR + 3 * slot + 3]),
            bytes(d[s + ti.O_STEM + 8 * slot:s + ti.O_STEM + 8 * slot + 8]))


def generic_slots(n, divs):
    """Slots a generic league of n teams occupies with divs divisions (East, West, Central order)."""
    if divs == 3:
        q, r = divmod(n, 3)
        sizes = [q + (r > 0), q + (r > 1), q]
    else:
        sizes = [(n + 1) // 2, n // 2]
    out = []
    for dv, sz in enumerate(sizes):
        out += [dv * 8 + i for i in range(sz)]
    return out


def generic(L, n, divs):
    tag = 'A' if L == 0 else 'N'
    return [(slot, f'{tag}{i:02d}') for i, slot in enumerate(generic_slots(n, divs))]


def mk(path, d, hist=None):
    path.mkdir(parents=True, exist_ok=True)
    (path / MAJ_NAME).write_bytes(d)
    if hist is not None:
        h = bytearray(32)
        h[11] = hist
        (path / 'HISTORY.DAT').write_bytes(bytes(h))
    return str(path)


def test_now_and_wanted_rules():
    assert ra.now_divs(build_maj({}, divs=1)) == 2
    assert ra.now_divs(build_maj({}, divs=3)) == 3
    assert ra.now_divs(b'') == 2
    d = build_maj({}, divs=2)
    assert ra.wanted(b'', d) == 2
    assert ra.wanted(bytes(11), d) == 2 and ra.wanted(bytes(11) + b'\3', build_maj({}, divs=2)) == 3
    assert ra.wanted(bytes(11) + b'\1', build_maj({}, divs=3)) == 3       # 1 is not a setting: follow the MAJ
    assert ra.wanted(bytes(11) + b'\5', build_maj({}, divs=3)) == 3
    assert ra.wanted(bytes(11) + b'\0', build_maj({}, divs=2)) == 2


def test_wanted_for_dir(tmp_path):
    assert ra.wanted_for_dir(str(tmp_path)) == (2, 2)                    # no HISTORY, no MAJ
    lg = mk(tmp_path / 'lg', build_maj(CLASSIC), hist=3)
    assert ra.wanted_for_dir(lg) == (3, 2)


@pytest.mark.parametrize('case', ['short', 'leagues', 'divs0', 'divs4', 'already', 'already1', 'al_odd',
                                  'nl_odd', 'al_many', 'nl_many', 'nl_many2'])
def test_every_refusal_reason(case):
    d = bytearray(build_maj(CLASSIC))
    target, reason = 3, None
    if case == 'short':
        d, reason = bytes(100), 'SHORT MAJ'
    elif case == 'leagues':
        d[0x20c] = 1
        reason = 'NOT 2 LEAGUES'
    elif case == 'divs0':
        d[0x20d] = 0
        reason = 'BAD DIVISIONS'
    elif case == 'divs4':
        d[0x20d] = 4
        reason = 'BAD DIVISIONS'
    elif case == 'already':
        target, reason = 2, 'ALREADY'
    elif case == 'already1':
        d[0x20d] = 1
        target, reason = 2, 'ALREADY'
    elif case == 'al_odd':
        d = build_maj({0: CLASSIC[0][:13], 1: CLASSIC[1]})
        reason = 'AL ODD COUNT'
    elif case == 'nl_odd':
        d = build_maj({0: CLASSIC[0], 1: CLASSIC[1] + [(14, 'XXX')]})
        reason = 'NL ODD COUNT'
    elif case == 'al_many':
        d = build_maj({0: CLASSIC[0] + [(15, 'XXX'), (7, 'YYY')], 1: CLASSIC[1]})
        reason = 'AL TOO MANY TEAMS'
    elif case == 'nl_many':
        d = build_maj({0: CLASSIC[0], 1: CLASSIC[1] + [(6, 'Q1'), (7, 'Q2'), (14, 'Q3'), (15, 'Q4')]})
        reason = 'NL TOO MANY TEAMS'
    elif case == 'nl_many2':
        d = build_maj({0: CLASSIC[0], 1: [(s, 'N%d' % s) for s in (0, 1, 2, 3, 4, 8, 9, 10, 11, 12, 16, 17, 18, 19, 20)]},
                      divs=3)
        target, reason = 2, 'NL TOO MANY TEAMS'
    if isinstance(d, bytearray):
        d = bytes(d)
    assert ra.realign(d, target) == (None, reason)


def test_1994_known_table_on_the_1993_alignment():
    d = build_maj(CLASSIC)
    new, why = ra.realign(d, 3)
    assert why is None and len(new) == len(d)
    assert slots(new, 0) == {'BAL': 0, 'BOS': 1, 'DET': 2, 'NYA': 3, 'TOR': 4,
                             'CAL': 8, 'OAK': 9, 'SEA': 10, 'TEX': 11,
                             'CHA': 16, 'CLE': 17, 'KC': 18, 'MIL': 19, 'MIN': 20}
    assert slots(new, 1) == {'ATL': 0, 'MON': 1, 'NYN': 2, 'PHI': 3,
                             'LA': 8, 'SD': 9, 'SF': 10,
                             'CHN': 16, 'CIN': 17, 'HOU': 18, 'PIT': 19, 'SL': 20}
    assert [new[S[0] + 0x298 + dv] for dv in range(3)] == [5, 4, 5]
    assert [new[S[1] + 0x298 + dv] for dv in range(3)] == [4, 3, 5]
    assert list(new[0x20e:0x214]) == [5, 4, 5, 4, 3, 5]
    assert new[0x20d] == 3 and new[0x20a] == 0xf3
    for L in (0, 1):
        s = S[L]
        assert new[s + 0x2b3:s + 0x2cb] == b'\xff' * 24
        assert new[s + 0x2cb:s + 0x32b] == bytes(96)


def test_header_stem_table_is_left_unchanged():
    # C12.1: the shipped header holds ALLSTAR1 / ALLSTAR2 at k = 30 / 31, a team's engine id with 3 divisions
    d = bytearray(build_maj(CLASSIC))
    d[10 + 8 * 30:10 + 8 * 32] = b'ALLSTAR1ALLSTAR2'
    d[10:18] = b'clasale1'
    new, _ = ra.realign(bytes(d), 3)
    assert new[0:282] == bytes(d[0:282])
    back, _ = ra.realign(new, 2)
    assert back[0:282] == bytes(d[0:282])


def test_all_star_slot_15_is_kept_and_only_listed_bytes_change():
    d = build_maj(CLASSIC)
    new, _ = ra.realign(d, 3)
    for L in (0, 1):
        assert entry(new, L, 15) == entry(d, L, 15)
        assert entry(new, L, 15)[0].startswith(b'ALL STARS')
    diff = {i for i in range(len(d)) if d[i] != new[i]}
    assert diff <= WRITTEN


def test_every_team_keeps_its_name_abbreviation_and_stem():
    d = build_maj(CLASSIC)
    new, _ = ra.realign(d, 3)
    before = {abbr_at(d, L, slot): entry(d, L, slot) for L, slot, _st in ti.maj_teams(d)}
    after = {abbr_at(new, L, slot): entry(new, L, slot) for L, slot, _st in ti.maj_teams(new)}
    assert before == after


def test_round_trip_3_to_2_gives_back_the_classic_slots():
    d = build_maj(CLASSIC)
    three, _ = ra.realign(d, 3)
    two, why = ra.realign(three, 2)
    assert why is None
    assert two[0x20d] == 2
    assert [two[0x20e + i] for i in range(6)] == [7, 7, 0, 6, 6, 0]
    for L in (0, 1):
        assert slots(two, L) == slots(d, L)
        assert [two[S[L] + 0x298 + dv] for dv in range(3)] == ([7, 7, 0] if L == 0 else [6, 6, 0])
        for LL, slot, _st in ti.maj_teams(d):
            if LL == L:
                assert entry(two, L, slot) == entry(d, L, slot)
        assert entry(two, L, 15) == entry(d, L, 15)


@pytest.mark.parametrize('n', [10, 14])
def test_generic_rule_three_divisions(n):
    d = build_maj({0: generic(0, n, 2), 1: generic(1, n, 2)}, divs=2)
    new, why = ra.realign(d, 3)
    assert why is None
    sizes = {10: [4, 3, 3], 14: [5, 5, 4]}[n]
    for L, tag in ((0, 'A'), (1, 'N')):
        want, start = {}, 0
        for dv, sz in enumerate(sizes):
            for i in range(sz):
                want[f'{tag}{start + i:02d}'] = dv * 8 + i
            start += sz
        assert slots(new, L) == want
    for L in (0, 1):
        assert [new[S[L] + 0x298 + dv] for dv in range(3)] == sizes


@pytest.mark.parametrize('n', [10, 11, 13, 14])
def test_generic_rule_two_divisions(n):
    d = build_maj({0: generic(0, n, 3), 1: generic(1, n, 3)}, divs=3)
    new, why = ra.realign(d, 2)
    assert why is None
    east = (n + 1) // 2
    for L, tag in ((0, 'A'), (1, 'N')):
        want = {f'{tag}{i:02d}': i for i in range(east)}
        want.update({f'{tag}{east + i:02d}': 8 + i for i in range(n - east)})
        assert slots(new, L) == want
    assert [new[0x20e + i] for i in range(6)] == [east, n - east, 0] * 2


def test_known_table_needs_the_same_abbreviation_set():
    alt = dict(CLASSIC[0])
    alt[0] = 'BAX'                                    # BAL renamed: the AL set no longer matches the known table
    d = build_maj({0: list(alt.items()), 1: CLASSIC[1]})
    new, _ = ra.realign(d, 3)
    # generic rule over the AL list in slot order, 14 teams: East 5, West 5, Central 4
    assert slots(new, 0) == {'BAX': 0, 'BOS': 1, 'CLE': 2, 'DET': 3, 'MIL': 4,
                             'NYA': 8, 'TOR': 9, 'CAL': 10, 'CHA': 11, 'KC': 12,
                             'MIN': 16, 'OAK': 17, 'SEA': 18, 'TEX': 19}
    assert slots(new, 1)['PIT'] == 19 and slots(new, 1)['ATL'] == 0      # NL still matches its known table
    assert [new[S[0] + 0x298 + dv] for dv in range(3)] == [5, 5, 4]


def test_refused_realign_leaves_the_input_alone():
    d = build_maj({0: CLASSIC[0][:13], 1: CLASSIC[1]})
    before = bytes(d)
    assert ra.realign(d, 3) == (None, 'AL ODD COUNT')
    assert bytes(d) == before


def test_apply_paths_and_teamid_written_once(tmp_path):
    assert ra.apply(str(tmp_path / 'missing')) == 1
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert ra.apply(str(empty)) == 1 and not os.listdir(empty)           # no MAJ: nothing, no TEAMID.DAT

    d = build_maj(CLASSIC)
    lg = mk(tmp_path / 'lg', d)
    assert ra.apply(lg) == 1                                              # no HISTORY: wanted == now
    lg2 = mk(tmp_path / 'lg2', d, hist=2)
    assert ra.apply(lg2) == 1
    assert ti.load_table(lg2) is None

    too_many = build_maj({0: CLASSIC[0], 1: CLASSIC[1] + [(6, 'Q1'), (7, 'Q2'), (14, 'Q3'), (15, 'Q4')]})
    refused = mk(tmp_path / 'refused', too_many, hist=3)
    out = []
    assert ra.apply(refused, out) == 2 and out == ['NL TOO MANY TEAMS']
    assert open(os.path.join(refused, MAJ_NAME), 'rb').read() == too_many
    assert ti.load_table(refused) is None

    lg3 = mk(tmp_path / 'lg3', d, hist=3)
    pre_ids = [(k, st) for k, _L, _s, st in ti.teams(d, None)]
    assert ra.apply(lg3) == 0
    post = open(os.path.join(lg3, MAJ_NAME), 'rb').read()
    assert post[0x20d] == 3
    table = ti.load_table(lg3)
    assert table == [ti.make_table(d)[8 * k:8 * k + 8] for k in range(32)]
    assert [(k, st) for k, _L, _s, st in ti.teams(post, table)] == pre_ids
    assert ra.apply(lg3) == 1                                             # now 3 = wanted

    sentinel = bytes(range(256))
    open(os.path.join(lg3, ti.TABLE_NAME), 'wb').write(sentinel)
    h = bytearray(32)
    h[11] = 2
    open(os.path.join(lg3, 'HISTORY.DAT'), 'wb').write(bytes(h))
    assert ra.apply(lg3) == 0                                             # back to 2 divisions
    back = open(os.path.join(lg3, MAJ_NAME), 'rb').read()
    assert back[0x20d] == 2 and slots(back, 0) == slots(d, 0) and slots(back, 1) == slots(d, 1)
    assert open(os.path.join(lg3, ti.TABLE_NAME), 'rb').read() == sentinel   # never rewritten


def test_cli_prints_the_format_or_the_refusal(tmp_path):
    ok = mk(tmp_path / 'ok', build_maj(CLASSIC), hist=3)
    run = subprocess.run([sys.executable, RA, ok], capture_output=True, text=True)
    assert run.returncode == 0 and run.stdout == 'FORMAT 3\n'
    bad = mk(tmp_path / 'bad', build_maj({0: CLASSIC[0], 1: CLASSIC[1] + [(6, 'Q1'), (7, 'Q2'), (14, 'Q3'), (15, 'Q4')]}),
             hist=3)
    run = subprocess.run([sys.executable, RA, bad], capture_output=True, text=True)
    assert run.stdout == 'FORMAT REFUSED NL TOO MANY TEAMS\n'
    quiet = mk(tmp_path / 'quiet', build_maj(CLASSIC))
    run = subprocess.run([sys.executable, RA, quiet], capture_output=True, text=True)
    assert run.returncode == 0 and run.stdout == ''
