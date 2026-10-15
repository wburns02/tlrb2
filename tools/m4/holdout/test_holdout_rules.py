"""Holdout suite, part 2: the locked integer rules (rollover, realign, team ids, league names)
and the C ports' parity with the Python reference.

Offline and deterministic. No game data. The host binaries are compiled into tmp dirs with gcc
(skipped when gcc is missing) so the run leaves nothing behind in the repo.
Run:  cd tools/m4 && python3 -m pytest -q -p no:cacheprovider holdout
"""
import os
import random
import shutil
import subprocess

import pytest

import league
import realign as ra
import rollover as ro
import teamids as ti
from v20 import F, HDR, REC, SIZE
from holdout_util import MAJ_SIZE, S_AL, S_NL, blank_team, make_maj, put_player

M4 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAVE_GCC = shutil.which('gcc') is not None


class Script:
    """Scripted RNG: hands out the given draws in order and fails on a draw nobody planned."""

    def __init__(self, *vals):
        self.vals = list(vals)
        self.used = 0

    def draw(self):
        assert self.vals, 'unplanned RNG draw #%d' % (self.used + 1)
        self.used += 1
        return self.vals.pop(0)


def lo(rec, off, v):
    rec[off] = (rec[off] & 0xf0) | v


def hi(rec, off, v):
    rec[off] = (rec[off] & 0x0f) | (v << 4)


def batter(age, games=0, ratings=(0, 0, 0, 0, 0, 0)):
    """(roster, season) 143 B records of a batter. ratings = power, bunt, hit_run, speed, range, arm."""
    out = []
    for g in (0, games):
        r = bytearray(REC)
        r[0:4] = b'Test'
        r[0x14] = age
        r[0x15] = 100
        r[0x17] = g
        r[0x1f] = 4
        out.append(r)
    pw, bu, hr, sp, rg, ar = ratings
    for r in out:
        lo(r, 0x4a, pw)
        hi(r, 0x4a, bu)
        lo(r, 0x4b, hr)
        hi(r, 0x1d, sp)
        hi(r, 0x5e, rg)
        lo(r, 0x5e, ar)
    return out[0], out[1]


def bat_ratings(r):
    return (r[0x4a] & 15, r[0x4a] >> 4, r[0x4b] & 15, r[0x1d] >> 4, r[0x5e] >> 4, r[0x5e] & 15)


# ---------------------------------------------------------------- rollover (contract C1)

def test_rollover_career_merge_saturates_and_touches_nothing_else():
    """Step 1 and 2 of C1 on junk records: every stat field merges as min(cap, a + b) (u8 cap 255,
    u16 cap 65535, season value 0 leaves the career alone); age and exp move by one; year_off is the
    season's plus one; every other byte (name, ratings, salary, ids, games, injury) is unchanged."""
    rnd = random.Random(0xc1)
    roster = bytearray(rnd.randbytes(REC))
    season = bytearray(rnd.randbytes(REC))
    roster[0x14], roster[0x16] = 25, 3
    season[0x15], season[0x17] = 110, 10
    roster[0x20], season[0x20] = 200, 100                   # runs u8 saturates at 255
    roster[0x25:0x27], season[0x25:0x27] = (65000).to_bytes(2, 'little'), (1000).to_bytes(2, 'little')
    roster[0x23], season[0x23] = 3, 4                       # sb 3 + 4
    roster[0x21], season[0x21] = 77, 0                      # rbi: season 0 keeps 77
    roster[0x33], season[0x33] = 250, 5                     # hr_l 255 cap
    expect = bytearray(roster)
    for name in ro.STAT_FIELDS:
        off, kind = F[name]
        n = 2 if kind == 'u16' else 1
        a = int.from_bytes(roster[off:off + n], 'little')
        b = int.from_bytes(season[off:off + n], 'little')
        cap = 65535 if n == 2 else 255
        expect[off:off + n] = (min(cap, a + b) if b else a).to_bytes(n, 'little')
    expect[0x14], expect[0x15], expect[0x16] = 26, 111, 4

    log = []
    retire = ro.rollover_player(roster, season, {'progress': False, 'retire': False}, Script(), log)
    assert retire is False
    assert bytes(roster) == bytes(expect)
    assert roster[0x20] == 255 and roster[0x23] == 7 and roster[0x21] == 77 and roster[0x33] == 255
    assert int.from_bytes(roster[0x25:0x27], 'little') == 65535


def _retirement_rules():
    """Step 4 of C1: no draw below age 33; p = RETIRE_BASE * tier mult >> 2, doubled (cap 255) when the
    season has no games; retired iff (draw & 0xff) < p, so p-1 retires and p does not."""
    cases = [  # (age before, season games, ratings, p)
        (32, 5, (0,) * 6, 10),            # age2 33, tier 0
        (32, 0, (0,) * 6, 20),            # no games: doubled
        (36, 5, (0,) * 6, 36),            # age2 37 -> base 36
        (50, 0, (0,) * 6, 220),           # age2 51 -> base 110, doubled to 220
        (32, 5, (12, 0, 12, 12, 12, 0), 5),   # tier 3 (qs 48), mult 2: 10 * 2 >> 2
    ]
    for age, games, rat, p in cases:
        for draw, want in ((p - 1, True), (p, False), (0x100 | (p - 1), True), (0x100 | p, False)):
            roster, season = batter(age, games, rat)
            sc = Script(draw)
            got = ro.rollover_player(roster, season, {'progress': False}, sc, [])
            assert got is want, (age, games, rat, p, draw)
            assert sc.used == 1
    for age in (0, 31):                                     # age2 <= 32 never draws
        roster, season = batter(age, 5)
        assert ro.rollover_player(roster, season, {'progress': False}, Script(), []) is False
    roster, season = batter(40, 5)                          # the retire flag off: no draw, never retired
    assert ro.rollover_player(roster, season, {'progress': False, 'retire': False}, Script(), []) is False


def test_rollover_drift_retirement_boundaries_and_draw_order():
    """Steps 3b and 4 of C1 (retirement: see _retirement_rules). Drift: one draw per rating in the order power, bunt, hit_run, speed, range, arm, drawn
    even when nothing changes; growth below 27 (g 90, 64, 32 by age), none from 27 to 31, decline from
    32 with p = base * mult >> 2; caps 12 (endurance 10) and floor 1 hold; the xorshift16 stream is
    pinned."""
    _retirement_rules()
    r = ro.Rng(1)
    assert [r.draw() for _ in range(6)] == [33153, 24609, 59801, 11787, 46494, 55715]
    assert [ro.Rng(0).draw() for _ in range(3)] == [0, 0, 0]
    assert ro.Rng(0x10001).draw() == 33153                  # the seed is a 16 bit word

    cfg = {'retire': False}
    # (age before, start rating, draw that moves it, draw that does not, direction)
    table = [(21, 5, 89, 90, +1), (23, 5, 63, 64, +1), (25, 5, 31, 32, +1),
             (31, 5, 39, 40, -1), (33, 5, 63, 64, -1), (35, 5, 95, 96, -1)]
    for age, start, d_yes, d_no, step in table:
        for draw, moved in ((d_yes, True), (d_no, False)):
            roster, season = batter(age, 0, (start,) * 6)
            sc = Script(draw, d_no, d_no, d_no, d_no, d_no)
            ro.rollover_player(roster, season, cfg, sc, [])
            want = (start + step if moved else start,) + (start,) * 5
            assert bat_ratings(roster) == want, (age, draw)
            assert sc.used == 6, (age, 'all six draws are consumed')
    for age in (26, 27, 28, 30):                            # age2 27..31: draws consumed, nothing moves
        roster, season = batter(age, 0, (5,) * 6)
        sc = Script(0, 0, 0, 0, 0, 0)
        ro.rollover_player(roster, season, cfg, sc, [])
        assert bat_ratings(roster) == (5,) * 6 and sc.used == 6, age
    roster, season = batter(21, 0, (12, 12, 1, 12, 12, 12))     # caps hold
    ro.rollover_player(roster, season, cfg, Script(*[0] * 6), [])
    assert bat_ratings(roster) == (12, 12, 2, 12, 12, 12)
    roster, season = batter(40, 0, (1,) * 6)                    # the floor holds under a decline
    ro.rollover_player(roster, season, cfg, Script(*[0] * 6), [])
    assert bat_ratings(roster) == (1,) * 6

    pit = []
    for _ in range(2):
        rec = bytearray(REC)
        rec[0:4], rec[0x14], rec[0x15], rec[0x1f] = b'Pitc', 21, 100, 0
        lo(rec, 0x86, 11)                                   # control
        hi(rec, 0x86, 12)                                   # velocity at the cap
        hi(rec, 0x87, 10)                                   # endurance at ITS cap
        pit.append(rec)
    sc = Script(0, 0, 0)                                    # a pitcher draws 3 times, not 6
    ro.rollover_player(pit[0], pit[1], cfg, sc, [])
    assert (pit[0][0x86] & 15, pit[0][0x86] >> 4, pit[0][0x87] >> 4) == (12, 12, 10) and sc.used == 3


def test_rollover_team_writes_only_the_retired_and_aged_records(tmp_path):
    """rollover_team reads one V20 and writes another: the input file is untouched, size and header
    are kept, an inactive pair is left alone, a retiree loses only its first byte in both halves, and
    the season half mirrors age, year_off and exp."""
    img = blank_team()
    for slot in (5, 6):
        for r in (slot, slot + 40):
            put_player(img, r, 'Old', 'Man', 40, 4, games=100)
    for r in (8, 48):                                       # inactive pair carrying junk
        img[HDR + REC * r:HDR + REC * (r + 1)] = random.Random(r).randbytes(REC)
        img[HDR + REC * r] = 0
    src = tmp_path / 'IN.V20'
    dst = tmp_path / 'OUT.V20'
    src.write_bytes(bytes(img))

    sc = Script(0, 255)                                     # slot 5 retires (0 < 80), slot 6 stays
    retirees = ro.rollover_team(str(src), str(dst), {'progress': False}, sc, [])
    out = dst.read_bytes()
    assert src.read_bytes() == bytes(img)                   # the input is never modified
    assert retirees == [5] and sc.used == 2
    assert len(out) == SIZE and out[:HDR] == bytes(img[:HDR])

    def rec(b, r):
        return b[HDR + REC * r:HDR + REC * (r + 1)]

    for r in set(range(80)) - {5, 6, 45, 46}:
        assert rec(out, r) == rec(bytes(img), r), r         # nothing else moves, junk included
    assert rec(out, 5)[0] == 0 and rec(out, 45)[0] == 0
    assert rec(out, 5)[1:0x14] == rec(bytes(img), 5)[1:0x14]    # a retiree keeps the rest of its name
    assert rec(out, 6)[0] != 0 and rec(out, 46)[0] != 0
    for a, b in ((5, 45), (6, 46)):
        assert rec(out, a)[0x14] == rec(out, b)[0x14] == 41    # aged in both halves
        assert rec(out, a)[0x15:0x17] == rec(out, b)[0x15:0x17]


# ---------------------------------------------------------------- realign and team ids (C12)

AL = ['BAL', 'BOS', 'CLE', 'DET', 'MIL', 'NYA', 'TOR', 'CAL', 'CHA', 'KC', 'MIN', 'OAK', 'SEA', 'TEX']
NL = ['CHN', 'MON', 'NYN', 'PHI', 'PIT', 'SL', 'ATL', 'CIN', 'HOU', 'LA', 'SD', 'SF']


def two_div_maj(junk=0xa11):
    """The 1993 alignment: AL 7 + 7 and NL 6 + 6 on divisions at slots 0..7 and 8..15."""
    def side(abbrs, east):
        t = []
        for i, a in enumerate(abbrs):
            slot = i if i < east else 8 + i - east
            t.append((slot, a, a.lower() + '1'))
        return t
    return make_maj(side(AL, 7), side(NL, 6), ndiv=2, junk=junk)


def test_realign_refusals_stay_in_lane_and_plan_keeps_stable_ids():
    """realign refuses short, wrong-league-count, bad-division, already-aligned, odd and oversized
    leagues without producing bytes; a success keeps the length, keeps every team, and changes bytes
    only inside the league blocks and the six division bytes. plan() keeps every team's stable id
    and never rewrites an existing TEAMID.DAT."""
    d = two_div_maj()
    keep = bytes(d)
    new, why = ra.realign(d, 3)
    assert why is None and len(new) == MAJ_SIZE and new[0x20d] == 3
    assert d == keep
    for L, s in enumerate((S_AL, S_NL)):                    # same teams, same names, same stems
        before = sorted((d[s + 0x0f + 16 * k:s + 0x1f + 16 * k], d[s + 0x18f + 3 * k:s + 0x192 + 3 * k],
                         d[s + 0x1d7 + 8 * k:s + 0x1df + 8 * k]) for k in range(16) if d[s + 0x1d7 + 8 * k])
        after = sorted((new[s + 0x0f + 16 * k:s + 0x1f + 16 * k], new[s + 0x18f + 3 * k:s + 0x192 + 3 * k],
                        new[s + 0x1d7 + 8 * k:s + 0x1df + 8 * k]) for k in range(24) if new[s + 0x1d7 + 8 * k])
        assert before == after, L
    allowed = set(range(0x20a, 0x214))
    for s in (S_AL, S_NL):
        allowed |= set(range(s + 0x0f, s + 0x32b))
    assert [i for i in range(MAJ_SIZE) if new[i] != d[i] and i not in allowed] == []

    assert ra.realign(d[:MAJ_SIZE - 1], 3) == (None, 'SHORT MAJ')
    assert ra.realign(d, 2) == (None, 'ALREADY')
    one = bytearray(d)
    one[0x20c] = 1
    assert ra.realign(bytes(one), 3) == (None, 'NOT 2 LEAGUES')
    bad = bytearray(d)
    bad[0x20d] = 7
    assert ra.realign(bytes(bad), 3) == (None, 'BAD DIVISIONS')
    odd = make_maj([(i, a, a.lower() + '1') for i, a in enumerate(AL[:13])], [], junk=3)
    assert ra.realign(odd, 3) == (None, 'AL ODD COUNT')
    full = make_maj([(i, 'T%02d' % i, 'tm%d' % i) for i in range(5)] +
                    [(8 + i, 'U%02d' % i, 'um%d' % i) for i in range(5)] +
                    [(16 + i, 'V%02d' % i, 'vm%d' % i) for i in range(5)], [], ndiv=3, junk=4)
    assert ra.realign(full, 2) == (None, 'AL TOO MANY TEAMS')

    # plan(): code 1 when nothing to do, code 0 with the stable-id table taken from the OLD alignment
    # when none exists, never a new table when one is present; every team keeps its id
    assert ra.plan(d, b'', None)[0] == 1                    # history asks for 2, the MAJ has 2
    hist = bytes(11) + b'\x03'
    code, new, tab, why = ra.plan(d, hist, None)
    assert (code, why) == (0, None) and new[0x20d] == 3
    assert tab == ti.make_table(d) and len(tab) == ti.TABLE_SIZE
    code2, new2, tab2, _ = ra.plan(d, hist, bytes(256))     # a table is there: leave it
    assert code2 == 0 and tab2 is None and new2 == new
    old_ids = {(k, st) for k, _L, _s, st in ti.teams(d, tab)}
    new_ids = {(k, st) for k, _L, _s, st in ti.teams(new, tab)}
    assert old_ids == new_ids and len(old_ids) == len(AL) + len(NL)
    assert ra.plan(d[:100], hist, None)[0] == 2             # refused plans carry a reason
    assert ra.plan(d[:100], hist, None)[3] == 'SHORT MAJ'


@pytest.fixture(scope='module')
def ti_host(tmp_path_factory):
    if not HAVE_GCC:
        pytest.skip('gcc missing')
    out = tmp_path_factory.mktemp('ti') / 'ti_host'
    src = os.path.join(M4, 'teamids_c', 'ti_host.c')
    r = subprocess.run(['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror', '-o', str(out), src],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(out)


def test_c_port_matches_python_for_teams_table_and_realign(ti_host, tmp_path):
    """teamids.h / realign.h against teamids.py / realign.py, byte for byte, on fresh MAJs: a 2 and a
    3 division league, a shuffled stem table, refusal cases, and a bad target."""
    def run(*args):
        r = subprocess.run([ti_host] + [str(a) for a in args], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout

    maj_f, tab_f, out_f = (str(tmp_path / n) for n in ('maj', 'tab', 'out'))
    d2 = two_div_maj()
    d3, why = ra.realign(d2, 3)
    assert why is None
    odd = make_maj([(i, a, a.lower() + '1') for i, a in enumerate(AL[:13])], [], junk=3)
    mixed = make_maj([(i, 'AB' if i % 2 else 'ab', 'dup%d' % (i % 3)) for i in range(6)],
                     [(2, 'ZZ', 'only')], junk=9)           # repeated and case-changed stems
    for d in (d2, d3, odd, mixed, d2[:5000]):
        open(maj_f, 'wb').write(d)
        shuf = ti.make_table(d)
        ents = [shuf[8 * k:8 * k + 8] for k in range(32)]
        random.Random(5).shuffle(ents)
        for table in (None, ti.make_table(d), b''.join(ents)):
            arg = '-'
            if table is not None:
                open(tab_f, 'wb').write(table)
                arg = tab_f
            run('teams', maj_f, arg, out_f)
            want = b''.join(bytes((k, L, s)) + st for k, L, s, st in ti.teams(d, table))
            assert open(out_f, 'rb').read() == want
        run('table', maj_f, out_f)
        assert open(out_f, 'rb').read() == ti.make_table(d)
        for target in (2, 3):
            got = run('realign', maj_f, target, out_f)
            new, reason = ra.realign(d, target)
            if new is None:
                assert got == 'rc 1\nreason %s\n' % reason and open(out_f, 'rb').read() == d
            else:
                assert got == 'rc 0\n' and open(out_f, 'rb').read() == new
    open(maj_f, 'wb').write(d2)
    assert run('realign', maj_f, 4, out_f) == 'rc 1\nreason BAD TARGET\n'
    assert open(out_f, 'rb').read() == d2


# ---------------------------------------------------------------- league names (C16.1)

def test_league_name_rules_keep_writes_inside_the_league_dir(tmp_path, lg_host):
    """The SYSTEM name picks the directory the tools write to: only 1..8 bytes of 0x21..0x7e outside
    the forbidden set count, a name never contains a path character, and a valid name is used only if
    its MAJ opens. Lower case folds to upper; anything else is CLASSIC."""
    for data, want in ((b'CLASSIC\0', 'CLASSIC'), (b'negro\0', 'NEGRO'), (b"o'brien\0", "O'BRIEN"),
                       (b'ABCDEFGHIJ', 'ABCDEFGH'), (b'AB\0CD', 'AB')):
        assert league.parse_name(data) == want, data
    for data in (b'', b'\0', b'..\0', b'A/B', b'A\\B', b'C:X', b'A.B', b'A B', b'A\x7f', b'A\x80',
                 b'A\x1f', b'A*', b'A?', b'A|B'):
        assert league.parse_name(data) is None, data
    for c in b'"*+,./:;<=>?[\\]|':
        assert league.parse_name(b'A' + bytes([c])) is None

    g = tmp_path / 'game'
    (g / 'TEAMS' / 'ALT').mkdir(parents=True)
    (g / 'SYSTEM').write_bytes(b'alt\0')
    assert league.current_info(str(g)) == ('CLASSIC', 0)    # no MAJ yet
    (g / 'TEAMS' / 'ALT' / 'ALT.MAJ').write_bytes(b'')
    assert league.current_info(str(g)) == ('ALT', 1)
    (g / 'SYSTEM').write_bytes(b'../ALT\0')                 # a climbing name is rejected outright
    assert league.current_info(str(g)) == ('CLASSIC', 0)
    p = league.paths('ALT', '/')
    assert p['hist'] == 'TEAMS/ALT/HISTORY.DAT' and p['snap'] == 'C:/DYNLG/ALT/SNAP'
    assert league.paths('CLASSIC', '\\')['snap'] == 'C:\\DYNSNAP'
    _c_league_parity(lg_host, tmp_path / 'par')


@pytest.fixture(scope='module')
def lg_host(tmp_path_factory):
    if not HAVE_GCC:
        pytest.skip('gcc missing')
    out = tmp_path_factory.mktemp('lg') / 'lg_host'
    src = os.path.join(M4, 'league_c', 'lg_host.c')
    r = subprocess.run(['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror', '-o', str(out), src],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(out)


def _c_league_parity(lg_host, tmp_path):
    """league.h against league.py: the current league, whether SYSTEM gave it, and every dynasty path,
    for both separators, on SYSTEM files with valid, forbidden, climbing and over long names."""
    samples = [b'', b'CLASSIC\0', b'classic', b'negro\0junk', b"o'brien", b'ABCDEFGHIJKL', b'..\0',
               b'A/B', b'A\\B', b'A.B', b'A B', b'\0ABC', b'AB\x80', b'AB\x1f', b'A:B', b'A,B', b'A*B', b'A?B',
               b'X' * 9]
    for i, data in enumerate(samples):
        for with_maj in (False, True):
            g = tmp_path / ('g%d%d' % (i, with_maj))
            g.mkdir(parents=True)
            (g / 'SYSTEM').write_bytes(data)
            # a MAJ for whatever name the bytes spell, valid or not, so a name check that lets a bad
            # name through shows up as a different answer (the host falls back to CLASSIC otherwise)
            cand = data[:8].split(b'\0')[0].upper().decode('latin-1')
            if with_maj and cand and '/' not in cand and '\\' not in cand and cand not in ('.', '..'):
                (g / 'TEAMS' / cand).mkdir(parents=True)
                (g / 'TEAMS' / cand / (cand + '.MAJ')).write_bytes(b'x')
            for sep in ('/', '\\'):
                r = subprocess.run([lg_host, str(g), sep], capture_output=True, text=True)
                assert r.returncode == 0, r.stderr
                got = dict(line.partition('=')[::2] for line in r.stdout.splitlines())
                cur, fromsys = league.current_info(str(g))
                want = {'name': cur, 'fromsys': str(fromsys)}
                want.update(league.paths(cur, sep))
                assert got == want, (data, with_maj, sep)
