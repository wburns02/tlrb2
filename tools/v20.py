#!/usr/bin/env python3
"""TLRB2 team file (.V20) reader / writer / differ. Layout decoded 2026-10-06 (Lane B), see notes/FORMATS.md.
  11735 B = 295 B team header + 80 player records x 143 B.
  Records 0..39 = "stat line" half (0..15 pitchers, 16..39 position players); records 40..79 = the same 40 players
  as the "current season" half (year+1, exp+1, season stats zeroed). The Utilities editor writes ratings to both.
usage: v20.py dump FILE [N]       decoded players (all, or record N only)
       v20.py hdr FILE            decoded team header (staff, lineups, defense, bench, reserves, strategy)
       v20.py raw FILE N          hex of record N with offsets
       v20.py diff OLD NEW        every changed byte as (header|player N, field offset, old -> new)
       v20.py set FILE N FIELD=VAL [FIELD=VAL ...] [-o OUT]   edit fields of record N (writes both halves when the
                                  record has a twin and the field is a rating/bio field; stats go to record N only)
Library: from v20 import Team; t = Team.load(path); p = t.players[16]; p['age'] = 36; t.save(path)"""
import sys, struct

HDR, REC, N = 295, 143, 80
SIZE = HDR + REC * N

# -- field table: name -> (offset, kind). kinds: u8, u16 (LE), hi (high nibble), lo (low nibble), str(len)
# nibble fields are given as (offset, 'hi'|'lo'). Composite fields are handled in _bio below.
F = {
    'injury': (0x18, 'u8'),   # bit7 = rested (pitched recently), 1..0x7f = injured days
    'age': (0x14, 'u8'), 'year_off': (0x15, 'u8'), 'exp': (0x16, 'u8'), 'games': (0x17, 'u8'),
    'salary': (0x19, 'u16'), 'portrait': (0x1b, 'u16'),
    'speed': (0x1d, 'hi'),
    'consist': (0x1e, 'lo'), 'exper': (0x1e, 'hi'),
    'pos1': (0x1f, 'lo'), 'pos2': (0x1f, 'hi'),
    'runs': (0x20, 'u8'), 'rbi': (0x21, 'u8'), 'sh': (0x22, 'u8'), 'sb': (0x23, 'u8'), 'cs': (0x24, 'u8'),
    'ab_l': (0x25, 'u16'), 'ab_r': (0x27, 'u16'), 'h_l': (0x29, 'u16'), 'h_r': (0x2b, 'u16'),
    'd_l': (0x2d, 'u16'), 'd_r': (0x2f, 'u16'), 't_l': (0x31, 'u8'), 't_r': (0x32, 'u8'),
    'hr_l': (0x33, 'u8'), 'hr_r': (0x34, 'u8'), 'bb_l': (0x35, 'u16'), 'bb_r': (0x37, 'u16'),
    'so_l': (0x39, 'u16'), 'so_r': (0x3b, 'u16'),
    'gb_pct10': (0x3d, 'u16'), 'gb_pull10': (0x3f, 'u16'), 'gb_opp10': (0x41, 'u16'),
    'fb_pull10': (0x43, 'u16'), 'fb_opp10': (0x45, 'u16'),
    'pinch_ab': (0x47, 'u8'), 'pinch_h': (0x48, 'u8'), 'pinch_hr': (0x49, 'u8'),
    'power': (0x4a, 'lo'), 'bunt': (0x4a, 'hi'), 'hit_run': (0x4b, 'lo'), 'streak_v': (0x4b, 'hi'),
    'clutch': (0x4c, 'lo'), 'daynight': (0x4c, 'hi'),
    'po1': (0x4d, 'u16'), 'po2': (0x4f, 'u16'), 'a1': (0x51, 'u16'), 'a2': (0x53, 'u16'),
    'e1': (0x55, 'u8'), 'e2': (0x56, 'u8'), 'dp1': (0x57, 'u8'), 'dp2': (0x58, 'u8'), 'pb': (0x59, 'u8'),
    'rto_a': (0x5a, 'u16'), 'rto_b': (0x5c, 'u16'),
    'arm': (0x5e, 'lo'), 'range': (0x5e, 'hi'),
    'w': (0x5f, 'u8'), 'l': (0x60, 'u8'), 'cg': (0x61, 'u8'), 'gs': (0x62, 'u8'), 'sho': (0x63, 'u8'), 'sv': (0x64, 'u8'),
    'ip10': (0x65, 'u16'), 'er': (0x67, 'u16'), 'runs_allowed': (0x69, 'u16'),
    'bf_l': (0x6b, 'u16'), 'bf_r': (0x6d, 'u16'), 'ph_l': (0x6f, 'u16'), 'ph_r': (0x71, 'u16'),
    'pd_l': (0x73, 'u16'), 'pd_r': (0x75, 'u16'), 'pt_l': (0x77, 'u8'), 'pt_r': (0x78, 'u8'),
    'pbb_l': (0x79, 'u16'), 'pbb_r': (0x7b, 'u16'), 'pso_l': (0x7d, 'u16'), 'pso_r': (0x7f, 'u16'),
    'phr_l': (0x81, 'u8'), 'phr_r': (0x82, 'u8'), 'bk': (0x83, 'u8'), 'wp': (0x84, 'u8'),
    'control': (0x86, 'lo'), 'velocity': (0x86, 'hi'), 'pitch4': (0x87, 'lo'), 'endurance': (0x87, 'hi'),
    'p_streak_v': (0x88, 'lo'), 'p_clutch': (0x88, 'hi'), 'p_daynight': (0x89, 'lo'), 'pickoff': (0x89, 'hi'),
    'release': (0x8a, 'lo'), 'q1': (0x8a, 'hi'), 'q2': (0x8b, 'lo'), 'q3': (0x8b, 'hi'), 'q4': (0x8c, 'lo'),
}
# fields that are bio/ratings: written to both halves (record N and N+/-40). Everything else: that record only.
TWIN = {'age', 'salary', 'portrait', 'speed', 'consist', 'exper', 'pos1', 'pos2', 'power', 'bunt', 'hit_run',
        'streak_v', 'clutch', 'daynight', 'arm', 'range', 'control', 'velocity', 'pitch4', 'endurance',
        'p_streak_v', 'p_clutch', 'p_daynight', 'pickoff', 'release', 'q1', 'q2', 'q3', 'q4', 'bats', 'throws', 'flag3'}

# Header layout (295 B), decoded by Lane B 2026-10-07 from Manager-screen diffs + MANAGE code (see notes/FORMATS.md)
H_DAY, H_STAFF, H_LINEUP, H_DEF, H_BENCH, H_RESERVE, H_STRAT = 0x6c, 111, 122, 158, 194, 222, 245
STRAT = ['lineup_speed_power', 'lineup_def_hit', 'lineup_end_era', 'pitch_yank', 'pitch_pinch', 'pitch_around',
         'bat_sac', 'bat_squeeze', 'bat_hitrun', 'def_walk', 'def_infield', 'def_pitchout',
         'run_aggr', 'run_steal2', 'run_steal3']   # stored = RIGHT-hand number on screen x10 (50 = 5/5)

POS = ['P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH', 'OF', 'IF', 'O/I', 'C/O', 'C/I', 'C/3']
PITCH = ['FASTBALL', 'CURVE', 'CHANGEUP', 'DEFENSE', 'SLIDER', 'SCREWBALL', 'SINKER', 'SPLITFINGER', 'FORKBALL', 'KNUCKLEBALL']
# streak letter (A..G) <-> stored nibble (measured: A7 B5 C8 D6 E10 F4 G9); day/night letter A..G = 1..7
STREAK_LETTER = {7: 'A', 5: 'B', 8: 'C', 6: 'D', 10: 'E', 4: 'F', 9: 'G'}
BATS = {1: 'R', 2: 'S'}          # +0x1d bits2..1 (0 presumed L, unverified)
THROWS_R = 8                     # +0x1d bit3 set = throws right


def cstr(b): return b.split(b'\0')[0].decode('latin-1')


def _get(r, off, kind):
    if kind == 'u8': return r[off]
    if kind == 'u16': return r[off] | r[off + 1] << 8
    if kind == 'hi': return r[off] >> 4
    if kind == 'lo': return r[off] & 15
    raise ValueError(kind)


def _set(r, off, kind, v):
    if kind == 'u8': r[off] = v & 255
    elif kind == 'u16': r[off], r[off + 1] = v & 255, (v >> 8) & 255
    elif kind == 'hi': r[off] = (r[off] & 15) | ((v & 15) << 4)
    elif kind == 'lo': r[off] = (r[off] & 0xF0) | (v & 15)
    else: raise ValueError(kind)


class Player:
    def __init__(self, raw, idx): self.raw, self.idx = bytearray(raw), idx
    @property
    def active(self): return self.raw[0] != 0
    def __getitem__(self, k):
        if k == 'last': return cstr(self.raw[0:12])
        if k == 'first': return cstr(self.raw[12:20])
        if k == 'year': return self.raw[0x15] + 1870
        if k == 'bats': return (self.raw[0x1d] >> 1) & 3
        if k == 'throws': return (self.raw[0x1d] >> 3) & 1
        if k == 'flag3': return self.raw[0x1d] & 1
        off, kind = F[k]; return _get(self.raw, off, kind)
    def __setitem__(self, k, v):
        if k == 'last': self.raw[0:12] = v.encode('latin-1')[:11].ljust(12, b'\0')
        elif k == 'first': self.raw[12:20] = v.encode('latin-1')[:7].ljust(8, b'\0')
        elif k == 'year': self.raw[0x15] = v - 1870
        elif k == 'bats': self.raw[0x1d] = (self.raw[0x1d] & ~6) | ((v & 3) << 1)
        elif k == 'throws': self.raw[0x1d] = (self.raw[0x1d] & ~8) | ((v & 1) << 3)
        elif k == 'flag3': self.raw[0x1d] = (self.raw[0x1d] & ~1) | (v & 1)
        else: off, kind = F[k]; _set(self.raw, off, kind, v)
    def fields(self): return {k: self[k] for k in F}
    def avg(self, side='t'):
        ab = self['ab_l'] + self['ab_r']; h = self['h_l'] + self['h_r']
        return h / ab if ab else 0.0


class Team:
    def __init__(self, data):
        assert len(data) == SIZE, len(data)
        self.header = bytearray(data[:HDR])
        self.players = [Player(data[HDR + REC * i:HDR + REC * (i + 1)], i) for i in range(N)]
    @classmethod
    def load(cls, path): return cls(open(path, 'rb').read())
    def to_bytes(self): return bytes(self.header) + b''.join(bytes(p.raw) for p in self.players)
    def save(self, path): open(path, 'wb').write(self.to_bytes())
    @property
    def name(self): return cstr(self.header[0:14])
    @property
    def league_code(self): return self.header[14:16].decode('latin-1')
    @property
    def stadium(self): return cstr(self.header[16:24]) + ('.' + cstr(self.header[24:27]) if self.header[24] else '')
    # --- header lists (indices are player record numbers 0..39; 0xff = empty slot) ---
    def staff(self): return list(self.header[H_STAFF:H_STAFF + 10])          # 5 starters in rotation order, 5 relievers
    def lineup(self, dh, vs_rhp):
        o = H_LINEUP + dh * 18 + vs_rhp * 9; return list(self.header[o:o + 9])    # no-DH lists: 8 players then 0xff
    def defense(self, dh, vs_rhp):
        o = H_DEF + dh * 18 + vs_rhp * 9; return list(self.header[o:o + 9])       # position per lineup slot (0 P, 9 DH)
    def bench(self, dh, vs_rhp):
        o = H_BENCH + dh * 14 + vs_rhp * 7; return list(self.header[o:o + 7])     # remaining active batters, 0xff pad
    def reserves(self): return list(self.header[H_RESERVE:H_RESERVE + 15])        # 6 pitchers + 9 batters off the 25-man
    def strategy(self): return {k: self.header[H_STRAT + i] for i, k in enumerate(STRAT)}
    def set_list(self, kind, vals, dh=0, vs_rhp=0):
        """kind: staff|lineup|defense|bench|reserves ; vals padded with 0xff to the slot count. No consistency checks
        (the roster must stay a partition of the 40 players: 10 staff + lineup/bench batters + 15 reserves)."""
        o, n = {'staff': (H_STAFF, 10), 'lineup': (H_LINEUP + dh * 18 + vs_rhp * 9, 9),
                'defense': (H_DEF + dh * 18 + vs_rhp * 9, 9), 'bench': (H_BENCH + dh * 14 + vs_rhp * 7, 7),
                'reserves': (H_RESERVE, 15)}[kind]
        assert len(vals) <= n; self.header[o:o + n] = bytes(vals) + b'\xff' * (n - len(vals))
    def set_strategy(self, key, right_value):
        """key in STRAT; right_value 0..10 as shown in the right-hand box (left box shows 10 - this)"""
        self.header[H_STRAT + STRAT.index(key)] = right_value * 10
    # --- season state (written by BACK at Main > QUIT; zeroed by Start New Season) ---
    @property
    def wins(self): return self.header[0x26]
    @property
    def losses(self): return self.header[0x27]
    @property
    def last_game_day(self): return self.header[H_DAY]                              # day index of the team's last game
    @property
    def streak(self):                                                               # (+n win streak / -n loss streak)
        b = self.header[0x6d]; return -(b & 0x7f) if b & 0x80 else b
    @property
    def rotation_ptr(self): return self.header[0x6e]                                # next starter, 0..4
    def set_record(self, w, l): self.header[0x26], self.header[0x27] = w, l
    def twin(self, i): return i + 40 if i < 40 else i - 40
    def set(self, i, **kw):
        """set fields on record i; ratings/bio fields also go to the twin record (other half)"""
        for k, v in kw.items():
            self.players[i][k] = v
            if k in TWIN or k in ('last', 'first'):
                self.players[self.twin(i)][k] = v


def describe(p):
    sv = STREAK_LETTER.get(p['streak_v'], '?'); dn = 'ABCDEFG'[p['daynight'] - 1] if 1 <= p['daynight'] <= 7 else '?'
    b = {0: 'L', 1: 'R', 2: 'S'}.get(p['bats'], '?'); t = 'R' if p['throws'] else 'L'
    return (f"{p['last']}, {p['first']}  {p['year']} age {p['age']} exp {p['exp']} ${p['salary']} B{b} T{t} "
            f"{POS[p['pos1']]}/{POS[p['pos2']]} consist {p['consist']} exper {p['exper']} portrait {p['portrait']}\n"
            f"    bat: G{p['games']} AB {p['ab_l']}+{p['ab_r']} H {p['h_l']}+{p['h_r']} 2B {p['d_l']}+{p['d_r']} "
            f"3B {p['t_l']}+{p['t_r']} HR {p['hr_l']}+{p['hr_r']} BB {p['bb_l']}+{p['bb_r']} SO {p['so_l']}+{p['so_r']} "
            f"R {p['runs']} RBI {p['rbi']} SH {p['sh']} SB {p['sb']} CS {p['cs']}\n"
            f"    spray: gb {p['gb_pct10']/10:.1f} pull {p['gb_pull10']/10:.1f} opp {p['gb_opp10']/10:.1f} | fb pull "
            f"{p['fb_pull10']/10:.1f} opp {p['fb_opp10']/10:.1f} | pinch {p['pinch_h']}/{p['pinch_ab']} HR {p['pinch_hr']}\n"
            f"    rat: speed {p['speed']} power {p['power']} bunt {p['bunt']} h&r {p['hit_run']} clutch {p['clutch']} "
            f"streak {sv} d/n {dn} arm {p['arm']} range {p['range']}\n"
            f"    field: PO {p['po1']}/{p['po2']} A {p['a1']}/{p['a2']} E {p['e1']}/{p['e2']} DP {p['dp1']}/{p['dp2']} PB {p['pb']} rto {p['rto_a']},{p['rto_b']}\n"
            f"    pitch: W-L {p['w']}-{p['l']} G.. GS {p['gs']} CG {p['cg']} SHO {p['sho']} SV {p['sv']} IP {p['ip10']/10:.1f} ER {p['er']} "
            f"BF {p['bf_l']}+{p['bf_r']} H {p['ph_l']}+{p['ph_r']} 2B {p['pd_l']}+{p['pd_r']} 3B {p['pt_l']}+{p['pt_r']} "
            f"BB {p['pbb_l']}+{p['pbb_r']} SO {p['pso_l']}+{p['pso_r']} HR {p['phr_l']}+{p['phr_r']} BK {p['bk']} WP {p['wp']}\n"
            f"    pit rat: control {p['control']} velocity {p['velocity']} endur {p['endurance']} pickoff {p['pickoff']} "
            f"release {p['release']} Q1-4 {p['q1']},{p['q2']},{p['q3']},{p['q4']} pitch4 {PITCH[p['pitch4']] if p['pitch4'] < len(PITCH) else p['pitch4']}")


def where(o):
    return ('header', o) if o < HDR else (f'player {(o - HDR) // REC:2d}', (o - HDR) % REC)


def pname(d, i): r = d[HDR + REC * i:HDR + REC * i + 24]; return cstr(r[12:20]) + ' ' + cstr(r[0:12])


def diff(a, b):
    x, y = open(a, 'rb').read(), open(b, 'rb').read(); assert len(x) == len(y)
    for o in range(len(x)):
        if x[o] != y[o]:
            w, f = where(o); nm = pname(x, (o - HDR) // REC) if o >= HDR else ''
            print(f'{o:#06x} {w:<10} +{f:#05x}  {x[o]:#04x} -> {y[o]:#04x}  ({x[o]} -> {y[o]})  {nm}')


def main(argv):
    cmd = argv[1]
    if cmd == 'dump':
        t = Team.load(argv[2])
        print(f'team={t.name!r} league={t.league_code!r} stadium={t.stadium!r}')
        for i, p in enumerate(t.players):
            if p.active and (len(argv) < 4 or int(argv[3]) == i): print(f'[{i}] ' + describe(p))
    elif cmd == 'hdr':
        t = Team.load(argv[2]); nm = lambda i: t.players[i]['last'] if i < 40 else '--'
        print(f'team={t.name!r} league={t.league_code!r} stadium={t.stadium!r} day={t.header[H_DAY]}')
        print('staff    ', [nm(i) for i in t.staff()])
        for dh in (0, 1):
            for v in (0, 1):
                print(f"lineup dh={dh} vs {'RHP' if v else 'LHP'}", [nm(i) for i in t.lineup(dh, v)], t.defense(dh, v),
                      'bench', [nm(i) for i in t.bench(dh, v)])
        print('reserves ', [nm(i) for i in t.reserves()])
        print('strategy ', t.strategy())
    elif cmd == 'raw':
        d = open(argv[2], 'rb').read(); i = int(argv[3]); r = d[HDR + REC * i:HDR + REC * (i + 1)]
        for k in range(0, REC, 16): print(f'{k:3d}', ' '.join(f'{b:02x}' for b in r[k:k + 16]))
    elif cmd == 'diff': diff(argv[2], argv[3])
    elif cmd == 'set':
        out = None; args = argv[2:]
        if '-o' in args: k = args.index('-o'); out = args[k + 1]; del args[k:k + 2]
        path, i, kvs = args[0], int(args[1]), args[2:]
        t = Team.load(path); kw = {}
        for kv in kvs:
            k, v = kv.split('=', 1); kw[k] = v if k in ('last', 'first') else int(v)
        t.set(i, **kw); t.save(out or path)
    else: raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
