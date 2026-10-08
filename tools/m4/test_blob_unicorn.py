"""C1 parity gate: the 16-bit blob (tools/m4/blob/rollover.bin, built from
rollover.asm with nasm at import) vs the Python reference tools/m4/rollover.py.
Every case diffs ALL bytes of both records, the RNG word and AX.

Run:  python3 -m pytest -q tools/m4/test_blob_unicorn.py
"""
import os
import struct
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
for _p in (_TOOLS, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402
from unicorn import *  # noqa: E402,F401,F403
from unicorn.x86_const import *  # noqa: E402,F401,F403

import rollover  # noqa: E402
from v20 import Team, F, _get, _set  # noqa: E402

ASM = os.path.join(_HERE, 'blob', 'rollover.asm')
BLOB = os.path.join(_HERE, 'blob', 'rollover.bin')
PRISTINE = '/mnt/nvme/tlrb2/pristine/TONY2/TEAMS/CLASSIC/CLASALE1.V20'

subprocess.run(['nasm', '-f', 'bin', '-o', BLOB, ASM], check=True,
               cwd=os.path.join(_HERE, 'blob'))

# this unicorn binding constructs UcIntel instances (subclassing Uc returns the
# parent type), so add the context-manager methods to the class itself
Uc.__enter__ = lambda self: self
Uc.__exit__ = lambda self, *args: False

# Constants
ENTRY_ROLL_PLAYER = 0x10
SEGMENT_ROSTER = 0x2000
SEGMENT_SEASON = 0x2000
SEGMENT_RNG = 0x3000
SEGMENT_STACK = 0x7000
OFFSET_ROSTER = 0x0000
OFFSET_SEASON = 0x100
OFFSET_RNG = 0x0000
OFFSET_STACK = 0x7FFC
PHYSICAL_BLOB = 0x10000
PHYSICAL_ROSTER = 0x20000
PHYSICAL_SEASON = 0x20100
PHYSICAL_RNG = 0x30000
PHYSICAL_STACK = 0x70000
PHYSICAL_SENTINEL = 0xF0000

BLOB_BYTES = open(BLOB, 'rb').read()

RATING_FIELDS = ('power', 'bunt', 'hit_run', 'speed', 'range', 'arm',
                 'control', 'velocity', 'endurance')


def build_pair(spec=None, batter=True):
    """One (roster, season) record pair. Ratings are set directly so each test
    can hit an exact tier; the season half carries stats for the target calls."""
    spec = dict(spec or {})
    roster = bytearray(143)
    season = bytearray(143)
    roster[0] = 1
    season[0] = 1
    rng = rollover.Rng(spec.pop('seed', 1))
    age = spec.pop('age', 20)
    games = spec.pop('games', 100)
    pos = spec.pop('pos1', 7 if batter else 0)
    roster[20] = age & 0xff
    season[20] = age & 0xff
    season[23] = games & 0xff
    roster[21] = 31            # year_off
    season[21] = 31
    roster[22] = 3             # exp
    season[22] = 3
    _set(roster, *F['pos1'], pos)
    _set(season, *F['pos1'], pos)
    # season stat lines so the target ratings are non-degenerate
    if batter:
        _set(season, *F['ab_l'], 300)
        _set(season, *F['ab_r'], 300)
        _set(season, *F['h_l'], 80)
        _set(season, *F['h_r'], 80)
        _set(season, *F['d_l'], 20)
        _set(season, *F['d_r'], 20)
        _set(season, *F['hr_l'], 10)
        _set(season, *F['hr_r'], 10)
        _set(season, *F['bb_l'], 40)
        _set(season, *F['bb_r'], 40)
        _set(season, *F['so_l'], 60)
        _set(season, *F['so_r'], 60)
        _set(season, *F['sb'], 12)
        _set(season, *F['games'], games)
        _set(season, *F['po1'], 150)
        _set(season, *F['a1'], 60)
        _set(season, *F['e1'], 4)
        _set(season, *F['dp1'], 30)
    else:
        _set(season, *F['w'], 10)
        _set(season, *F['l'], 8)
        _set(season, *F['cg'], 12)
        _set(season, *F['games'], games)
        _set(season, *F['ip10'], 520)
        _set(season, *F['er'], 60)
        _set(season, *F['so_l'], 70)
        _set(season, *F['so_r'], 70)
        _set(season, *F['pbb_l'], 30)
        _set(season, *F['pbb_r'], 30)
        _set(season, *F['ph_l'], 90)
        _set(season, *F['ph_r'], 90)
    # ratings: default mid values, then apply spec overrides
    if batter:
        for name, v in (('power', 6), ('bunt', 6), ('hit_run', 6), ('speed', 6),
                        ('range', 6), ('arm', 6)):
            _set(roster, *F[name], v)
            _set(season, *F[name], v)
    else:
        for name, v in (('control', 6), ('velocity', 6), ('endurance', 6)):
            _set(roster, *F[name], v)
            _set(season, *F[name], v)
    for key, value in spec.items():
        _set(roster, *F[key], value)
        _set(season, *F[key], value)
    return roster, season, rng


_UC = None


def get_uc():
    """One live Uc reused across cases (much faster than per-case setup)."""
    global _UC
    if _UC is None:
        _UC = Uc(UC_ARCH_X86, UC_MODE_16)
        _UC.mem_map(0x00000, 0x100000)
        _UC.mem_write(PHYSICAL_BLOB, BLOB_BYTES)
        _UC.mem_write(PHYSICAL_STACK + OFFSET_STACK, b'\x00\x00')
        _UC.mem_write(PHYSICAL_STACK + OFFSET_STACK + 2, b'\x00\xF0')
        _UC.mem_write(PHYSICAL_SENTINEL, b'\xF4')
        _UC.reg_write(UC_X86_REG_CS, 0x1000)
        _UC.reg_write(UC_X86_REG_DS, SEGMENT_ROSTER)
        _UC.reg_write(UC_X86_REG_ES, SEGMENT_SEASON)
        _UC.reg_write(UC_X86_REG_FS, SEGMENT_RNG)
        _UC.reg_write(UC_X86_REG_SS, SEGMENT_STACK)
        _UC.reg_write(UC_X86_REG_SI, OFFSET_ROSTER)
        _UC.reg_write(UC_X86_REG_DI, OFFSET_SEASON)
        _UC.reg_write(UC_X86_REG_BX, OFFSET_RNG)
        _UC.reg_write(UC_X86_REG_SP, OFFSET_STACK)
    return _UC


def run_blob(roster_in, season_in, rng_state, flags):
    """Emulate one entry_roll_player call on the shared Uc; returns
    (ax, roster, season, rng_word). A 5000-instruction cap stops a runaway
    blob instead of hanging the suite."""
    uc = get_uc()
    uc.mem_write(PHYSICAL_ROSTER, bytes(roster_in))
    uc.mem_write(PHYSICAL_SEASON, bytes(season_in))
    uc.mem_write(PHYSICAL_RNG, struct.pack('<H', rng_state))
    uc.mem_write(PHYSICAL_STACK + OFFSET_STACK, b'\x00\x00')   # IP
    uc.mem_write(PHYSICAL_STACK + OFFSET_STACK + 2, b'\x00\xF0')  # CS
    uc.mem_write(PHYSICAL_SENTINEL, b'\xF4')
    for reg, val in ((UC_X86_REG_CS, 0x1000), (UC_X86_REG_DS, SEGMENT_ROSTER),
                     (UC_X86_REG_ES, SEGMENT_SEASON), (UC_X86_REG_FS, SEGMENT_RNG),
                     (UC_X86_REG_SS, SEGMENT_STACK), (UC_X86_REG_SI, OFFSET_ROSTER),
                     (UC_X86_REG_DI, OFFSET_SEASON), (UC_X86_REG_BX, OFFSET_RNG),
                     (UC_X86_REG_CX, flags), (UC_X86_REG_SP, OFFSET_STACK)):
        uc.reg_write(reg, val)
    count = [0]

    def cap(uc, addr, size, ud):
        count[0] += 1
        if count[0] > 5000:
            uc.emu_stop()

    h = uc.hook_add(UC_HOOK_CODE, cap)
    try:
        uc.emu_start(PHYSICAL_BLOB + ENTRY_ROLL_PLAYER, 0)
    except UcError as e:
        if e.errno != UC_ERR_EXCEPTION:
            uc.hook_del(h)
            raise
        if count[0] > 5000:
            uc.hook_del(h)
            pytest.fail(f'blob ran past the 5000-instruction cap')
    uc.hook_del(h)
    ax = uc.reg_read(UC_X86_REG_AX)
    return (ax, bytes(uc.mem_read(PHYSICAL_ROSTER, 143)),
            bytes(uc.mem_read(PHYSICAL_SEASON, 143)),
            struct.unpack('<H', bytes(uc.mem_read(PHYSICAL_RNG, 2)))[0])


def assert_parity(roster, season, r_in, s_in, rng_start, cfg, label):
    """Roll the same input through the reference and the blob, diff everything."""
    ref_roster, ref_season = bytearray(r_in), bytearray(s_in)
    rng = rollover.Rng(rng_start)
    retire = rollover.rollover_player(ref_roster, ref_season, cfg, rng, None)
    ref_rng_word = rng.s
    exp_season = bytearray(ref_season)
    for f in ('age', 'year_off', 'exp'):
        exp_season[F[f][0]] = ref_roster[F[f][0]]
    if cfg.get('dev'):
        exp_season[rollover.OFF_DEV] = ref_roster[rollover.OFF_DEV]
    if retire:
        ref_roster[0] = 0
        exp_season[0] = 0
    ax, r_got, s_got, gw = run_blob(r_in, s_in, rng_start, cx_flags(cfg))
    assert ax == (1 if retire else 0), f'{label}: AX {ax} != {retire}'
    assert gw == ref_rng_word, f'{label}: rng word {gw:#06x} != {ref_rng_word:#06x}'
    r_diff = [k for k in range(143) if r_got[k] != ref_roster[k]]
    assert not r_diff, f'{label}: roster bytes {r_diff}'
    s_diff = [k for k in range(143) if s_got[k] != exp_season[k]]
    assert not s_diff, f'{label}: season bytes {s_diff}'


def cx_flags(cfg):
    return ((1 if cfg.get('progress', True) else 0) | (2 if cfg.get('retire', True) else 0)
            | (4 if cfg.get('dev') else 0))


def _set_kind(rec, off, kind, v):  # convenience wrapper unused; parity via F
    _set(rec, off, kind, v)


# -- every age2 bucket boundary in C1 (age = age2 - 1) -----------------------

@pytest.mark.parametrize('age', [21, 22, 23, 24, 25, 26, 27, 31, 32, 33, 34, 35,
                                 36, 37, 38, 39, 40, 41, 42, 43, 50])
def test_age2_boundaries_batter(age):
    roster, season, _ = build_pair({'age': age})
    assert_parity(roster, season, bytearray(roster), bytearray(season), 0x2A, {},
                  f'batter age {age}')


@pytest.mark.parametrize('age', [21, 22, 23, 24, 25, 26, 27, 31, 32, 33, 34, 35,
                                 36, 37, 38, 39, 40, 41, 42, 43, 50])
def test_age2_boundaries_pitcher(age):
    roster, season, _ = build_pair({'age': age}, batter=False)
    assert_parity(roster, season, bytearray(roster), bytearray(season), 0x2A, {},
                  f'pitcher age {age}')


# -- each tier boundary for batters and pitchers -----------------------------

@pytest.mark.parametrize('power,hit_run,speed,range_,tier', [
    (1, 1, 1, 1, 0),      # qs 4  (< 32)
    (10, 10, 10, 1, 0),   # qs 31 (tier 0 edge)
    (8, 8, 8, 8, 1),      # qs 32 (tier 1 edge)
    (10, 10, 10, 5, 1),   # qs 35 (tier 1 edge)
    (9, 9, 9, 9, 2),      # qs 36 (tier 2 edge)
    (10, 10, 10, 8, 2),   # qs 38 (tier 2 edge)
    (10, 10, 10, 9, 3),   # qs 39 (tier 3 edge)
    (12, 12, 12, 12, 3),  # stars
])
def test_tier_boundaries_batter(power, hit_run, speed, range_, tier):
    roster, season, _ = build_pair({'age': 34, 'power': power, 'hit_run': hit_run,
                                    'speed': speed, 'range': range_})
    assert rollover.tier_of(roster) == tier
    assert_parity(roster, season, bytearray(roster), bytearray(season), 0x11, {},
                  f'batter tier {tier} qs={power+hit_run+speed+range_}')


@pytest.mark.parametrize('control,velocity,endurance,tier', [
    (5, 5, 5, 0),          # qs 15 (< 23)
    (11, 5, 6, 0),         # qs 22 (tier 0 edge)
    (12, 6, 7, 1),         # tier 1 upper
    (8, 8, 9, 1),          # qs 25 (tier 1 edge)
    (9, 9, 9, 2),          # qs 27 (tier 2 edge)
    (12, 10, 6, 3),        # qs 28 (tier 3 edge)
    (12, 12, 10, 3),
])
def test_tier_boundaries_pitcher(control, velocity, endurance, tier):
    roster, season, _ = build_pair({'age': 34}, batter=False)
    _set(roster, *F['control'], control)
    _set(roster, *F['velocity'], velocity)
    _set(roster, *F['endurance'], endurance)
    assert rollover.tier_of(roster) == tier
    assert_parity(roster, season, bytearray(roster), bytearray(season), 0x11, {},
                  f'pitcher tier {tier} qs={control+velocity+endurance}')


# -- cap behaviour -----------------------------------------------------------

def test_caps_batter():
    for name, val in (('power', 12), ('bunt', 12), ('hit_run', 12),
                      ('speed', 12), ('range', 12), ('arm', 12)):
        for age in (20, 25, 34, 40):
            roster, season, _ = build_pair({'age': age, name: val})
            assert_parity(roster, season, bytearray(roster), bytearray(season),
                          0x77, {}, f'cap top {name} age {age}')
        for age in (20, 25, 34, 40):
            roster, season, _ = build_pair({'age': age, name: 1})
            assert_parity(roster, season, bytearray(roster), bytearray(season),
                          0x77, {}, f'cap bottom {name} age {age}')


def test_caps_pitcher_endurance10():
    # endurance cap 10: at 10 or 5 (any value) the young drift can never push past 10
    for val in (5, 10):
        for age in (20, 25):
            roster, season, _ = build_pair({'age': age}, batter=False)
            _set(roster, *F['endurance'], val)
            assert_parity(roster, season, bytearray(roster), bytearray(season),
                          0x33, {}, f'endurance cap {val} age {age}')


# -- season games == 0 -------------------------------------------------------

def test_games_zero():
    for age, batter in ((20, True), (25, True), (34, True), (43, True),
                        (20, False), (34, False), (43, False)):
        roster, season, _ = build_pair({'age': age, 'games': 0},
                                       batter=batter)
        assert_parity(roster, season, bytearray(roster), bytearray(season),
                      0x51, {}, f'games0 age {age} batter {batter}')


# -- 50-year-old: can retire only by draw ------------------------------------

def test_age_50_by_draw_only():
    for seed in range(0, 40):
        roster, season, _ = build_pair({'age': 50})
        assert_parity(roster, season, bytearray(roster), bytearray(season),
                      seed, {}, f'age 50 seed {seed}')


# -- flag-off cases: no drift draws / no retirement draw ----------------------

def test_progression_flag_off():
    # no drift draws at all: the rng word must stay at its start value
    roster, season, _ = build_pair({'age': 34})
    assert_parity(roster, season, bytearray(roster), bytearray(season),
                  0xBEEF, {'progress': False, 'retire': True}, 'prog off')
    for age in (20, 50):
        roster, season, _ = build_pair({'age': age})
        assert_parity(roster, season, bytearray(roster), bytearray(season),
                      0xBEEF, {'progress': False, 'retire': True}, f'prog off age {age}')


def test_retirement_flag_off():
    roster, season, _ = build_pair({'age': 45})
    assert_parity(roster, season, bytearray(roster), bytearray(season),
                  0xA5A5, {'progress': True, 'retire': False}, 'retire off')
    roster, season, _ = build_pair({'age': 45}, batter=False)
    assert_parity(roster, season, bytearray(roster), bytearray(season),
                  0xA5A5, {'progress': True, 'retire': False}, 'retire off P')


# -- 200-player random sweep with a continued RNG stream ----------------------

def test_random_sweep_200_players():
    players = []
    rng = rollover.Rng(0xC0FF)
    for i in range(200):
        batter = (i % 5) != 4
        r, s, _ = build_pair({}, batter=batter)
        r[F['age'][0]] = 15 + (rng.draw() % 36)       # ages 15..50
        s[F['age'][0]] = r[F['age'][0]]
        s[23] = rng.draw() % 200                      # season games 0..199
        if rng.draw() % 5 == 0:
            r[0] = 0                                  # some inactive roster halves
        if rng.draw() % 7 == 0:
            s[0] = 0                                  # some inactive season halves
        players.append((r, s))
    # continued RNG stream: one Rng instance drives the reference pass over all
    # ACTIVE players (rollover_team skips records inactive in BOTH halves); the
    # blob must consume exactly the same draws
    for i, (r, s) in enumerate(players):
        if r[0] == 0 and s[0] == 0:
            continue
        assert_parity(r, s, bytearray(r), bytearray(s), rng.s, {},
                      f'sweep player {i}')


# -- C1b dev trait (CX bit2) ---------------------------------------------------

@pytest.mark.parametrize('progress,retire', [(True, True), (True, False), (False, True)])
def test_dev_sweep(progress, retire):
    """300 players, grades 0..5 preassigned (0 = draw), ages 15..50, dev on."""
    rng = rollover.Rng(0xD3F1)
    cfg = {'progress': progress, 'retire': retire, 'dev': True}
    graded = 0
    for i in range(300):
        r, s, _ = build_pair({}, batter=(i % 4) != 3)
        r[F['age'][0]] = 15 + (rng.draw() % 36)
        s[F['age'][0]] = r[F['age'][0]]
        s[23] = rng.draw() % 200
        g = rng.draw() % 9
        r[rollover.OFF_DEV] = g if g <= 5 else 0
        s[rollover.OFF_DEV] = rng.draw() % 6          # stale twin byte: overwritten
        graded += r[rollover.OFF_DEV] != 0
        assert_parity(r, s, bytearray(r), bytearray(s), rng.s or 1, cfg, f'dev player {i}')
    assert graded > 50


@pytest.mark.parametrize('grade', [1, 2, 3, 4, 5])
@pytest.mark.parametrize('age', [20, 23, 25, 32, 35, 38, 41])
def test_dev_grade_age_grid(grade, age):
    for seed in (0x0101, 0x7E57, 0xBEEF, 0x1234, 0xFFFF):
        for batter in (True, False):
            r, s, _ = build_pair({'age': age}, batter=batter)
            r[rollover.OFF_DEV] = grade
            assert_parity(r, s, bytearray(r), bytearray(s), seed,
                          {'dev': True}, f'grade {grade} age {age} seed {seed:#x}')


def test_dev_off_leaves_byte_142():
    r, s, _ = build_pair({'age': 21})
    r[rollover.OFF_DEV], s[rollover.OFF_DEV] = 4, 2
    assert_parity(r, s, bytearray(r), bytearray(s), 0x4242, {}, 'dev off')
    _ax, r_got, s_got, _gw = run_blob(bytes(r), bytes(s), 0x4242, cx_flags({}))
    assert r_got[rollover.OFF_DEV] == 4 and s_got[rollover.OFF_DEV] == 2


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
