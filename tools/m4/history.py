#!/usr/bin/env python3
"""M4 HISTORY.DAT v1 reference (notes/M4_CONTRACT.md C2). Dataclass-free plain code.

Layout, little endian (TEAMS/<LEAGUE>/HISTORY.DAT):
  header 32 B: 0 u8 done flag, 1 u16 rng word, 3 u8 version, 4 u16 seasons recorded,
               6 u16 player entries, 8..31 zero
  season table at 32: 64 x 128 B. Entry for season n (1-based) at 32 + (n-1)*128:
    0 u16 season_no, 2 u8 champion id, 3 u8 runner-up id (0xff unknown),
    4 8 B champion stem, 12 8 B runner-up stem, 20 u8 al_pennant, 21 u8 nl_pennant,
    24 32x(u8 W, u8 L) by league-global id 0..31 (NL = slot+16), 88..127 zero
  player table at 8224: 160 B entries:
    0 20 B name (raw V20 bytes 0..19), 20 u16 birth, 22 u8 status (1 active 2 retired
    3 Hall of Fame), 23 u8 age at last season, 24 u16 first season, 26 u16 last season,
    28 u16 seasons played, 30 u8 pos1, 31 u8 pitcher flag, 32 25xu32 career totals
    (G, AB, H, 2B, 3B, HR, R, RBI, BB, SO, SB, CS, E, W, L, SV, GS, CG, SHO, OUTS, ER,
    PH, PBB, PSO, PHR), 132 s16 career WAR10, 134 7xs16 top-7 sorted desc (-32768
    unused), 148 s16 JAWS10, 150 u16 HoF season, 152..156 career award counts
    (MVP, CY, ROY, GG, SS), 157..159 zero
    (C7: season entry 88..99 = the 6 award winners as u16 player entry indices)

Identity: same entry iff name bytes 0..19 AND birth match.
Careers count dynasty seasons only (the shipped half-0 lines are NOT imported).
usage: python3 tools/m4/history.py dump HISTORY.DAT
"""
import os, sys, struct, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import war
import maj
from v20 import Team, F, _get           # noqa: E402

HDR_SIZE = 32
SEASON_TABLE = 32
SEASON_ENTRY = 128
SEASON_COUNT = 64
PLAYER_TABLE = 32 + 64 * SEASON_ENTRY   # 8224
PLAYER_ENTRY = 160
TOTALS = ['G', 'AB', 'H', '2B', '3B', 'HR', 'R', 'RBI', 'BB', 'SO', 'SB', 'CS', 'E',
          'W', 'L', 'SV', 'GS', 'CG', 'SHO', 'OUTS', 'ER', 'PH', 'PBB', 'PSO', 'PHR']
STATUS_ACTIVE, STATUS_RETIRED, STATUS_HOF = 1, 2, 3
EMPTY_TOP = -32768
NO_AWARD = 0xffff
# C7 milestone tables (kind -> mark), ascending kinds
MILESTONE_CAREER = [(1, 'H', 2000), (2, 'H', 3000), (3, 'HR', 300), (4, 'HR', 400),
                    (5, 'HR', 500), (6, 'HR', 600), (7, 'HR', 700), (8, 'RBI', 1500),
                    (9, 'RBI', 2000), (10, 'SB', 500), (11, 'W', 200), (12, 'W', 300),
                    (13, 'PSO', 2000), (14, 'PSO', 3000), (15, 'PSO', 4000),
                    (16, 'SV', 300), (17, 'SV', 400)]
# season kinds: (kind, stat key, gate kind, gate value); value = the season stat
MILESTONE_SEASON = [(32, 'HR', None, None), (33, 'H', None, None), (34, 'SB', None, None),
                    (35, 'BA', 'pa', 502), (36, 'W', None, None), (37, 'PSO', None, None),
                    (38, 'ERA100', 'outs486', None), (39, 'SV', None, None)]
MILESTONE_RECORD = 8        # 8 B records in MILESTON.DAT
# career-total keys used by the milestone tables, as TOTALS indexes
MILESTONE_IDX = {'H': 2, 'HR': 5, 'RBI': 7, 'SB': 10, 'W': 13, 'SV': 15, 'PSO': 23}
# season-half milestone stats, as collected keys (H/HR/SB = L+R; W/SV/PSO as in C2;
# the collection step flattens the C2 inputs to these names)
MS_H, MS_HR, MS_SB, MS_W, MS_SV, MS_PSO = 'ms_H', 'ms_HR', 'ms_SB', 'ms_W', 'ms_SV', 'ms_PSO'


def idiv(a, b):
    return war.idiv(a, b)


class History:
    def __init__(self, data):
        if data is None or len(data) == 0:
            # brand-new file: 32 B header, all zero except version
            data = bytes(HDR_SIZE)
        if len(data) < HDR_SIZE:
            # legacy: shorter than the v1 header; pad
            data = data + bytes(HDR_SIZE - len(data))
        self.d = bytearray(data)
        if len(self.d) < PLAYER_TABLE:
            self.d += bytes(PLAYER_TABLE - len(self.d))
        self._entries = self._parse_players()

    # -- load / save / upgrade --
    @classmethod
    def load(cls, path):
        p = os.path.exists(path)
        if not p:
            return cls(None)
        return cls(open(path, 'rb').read())

    def save(self, path):
        self.flush()
        open(path, 'wb').write(bytes(self.d))

    @property
    def done(self):
        return self.d[0]

    @done.setter
    def done(self, v):
        self.d[0] = v & 255

    @property
    def rng_word(self):
        return self.d[1] | self.d[2] << 8

    @rng_word.setter
    def rng_word(self, v):
        self.d[1], self.d[2] = v & 255, (v >> 8) & 255

    @property
    def version(self):
        return self.d[3]

    @version.setter
    def version(self, v):
        self.d[3] = v

    @property
    def seasons_recorded(self):
        return self.d[4] | self.d[5] << 8

    @seasons_recorded.setter
    def seasons_recorded(self, v):
        self.d[4], self.d[5] = v & 255, (v >> 8) & 255

    def _parse_players(self):
        out = []
        n = len(self.d)
        off = PLAYER_TABLE
        while off + PLAYER_ENTRY <= n:
            out.append(off)
            off += PLAYER_ENTRY
        return out

    def entries(self):
        return list(range(len(self._entries)))

    def entry_offset(self, i):
        return PLAYER_TABLE + i * PLAYER_ENTRY

    def read_entry(self, i):
        o = self.entry_offset(i)
        e = {}
        e['name'] = bytes(self.d[o:o + 20])
        e['birth'] = self.d[o + 20] | self.d[o + 21] << 8
        e['status'] = self.d[o + 22]
        e['age'] = self.d[o + 23]
        e['first_season'] = self.d[o + 24] | self.d[o + 25] << 8
        e['last_season'] = self.d[o + 26] | self.d[o + 27] << 8
        e['seasons_played'] = self.d[o + 28] | self.d[o + 29] << 8
        e['pos1'] = self.d[o + 30]
        e['pitcher'] = self.d[o + 31]
        raw = self.d[o + 32:o + 132]
        e['totals'] = [raw[4 * k] | raw[4 * k + 1] << 8 | raw[4 * k + 2] << 16
                       | raw[4 * k + 3] << 24 for k in range(25)]
        e['WAR10'] = struct.unpack_from('<h', self.d, o + 132)[0]
        e['top7'] = list(struct.unpack_from('<7h', self.d, o + 134))
        e['JAWS10'] = struct.unpack_from('<h', self.d, o + 148)[0]
        e['hof_season'] = self.d[o + 150] | self.d[o + 151] << 8
        e['awards'] = list(self.d[o + 152:o + 157])     # MVP, CY, ROY, GG, SS counts
        return e

    def write_entry(self, i, e):
        o = self.entry_offset(i)
        self.d[o:o + 20] = e['name'][:20].ljust(20, b'\0')
        self.d[o + 20], self.d[o + 21] = e['birth'] & 255, (e['birth'] >> 8) & 255
        self.d[o + 22] = e['status'] & 255
        self.d[o + 23] = e['age'] & 255
        self.d[o + 24], self.d[o + 25] = e['first_season'] & 255, (e['first_season'] >> 8) & 255
        self.d[o + 26], self.d[o + 27] = e['last_season'] & 255, (e['last_season'] >> 8) & 255
        self.d[o + 28], self.d[o + 29] = e['seasons_played'] & 255, (e['seasons_played'] >> 8) & 255
        self.d[o + 30] = e['pos1'] & 255
        self.d[o + 31] = e['pitcher'] & 255
        for k, v in enumerate(e['totals']):
            struct.pack_into('<I', self.d, o + 32 + 4 * k, v & 0xffffffff)
        struct.pack_into('<h', self.d, o + 132, e['WAR10'])
        struct.pack_into('<7h', self.d, o + 134, *e['top7'])
        struct.pack_into('<h', self.d, o + 148, e['JAWS10'])
        self.d[o + 150], self.d[o + 151] = e['hof_season'] & 255, (e['hof_season'] >> 8) & 255
        aw = e.get('awards', None)
        if aw is None:
            aw = [0] * 5
        self.d[o + 152:o + 157] = bytes(v & 255 for v in aw[:5])
        self.d[o + 157:o + 160] = bytes(3)

    def append_entry(self, e):
        i = len(self._entries)
        off = self.entry_offset(i)
        if len(self.d) < off + PLAYER_ENTRY:
            self.d += bytes(off + PLAYER_ENTRY - len(self.d))
        self._entries.append(off)
        self.d[6], self.d[7] = i + 1 & 255, (i + 1) >> 8 & 255
        self.write_entry(i, e)
        return i

    def flush(self):
        self.d[6], self.d[7] = len(self._entries) & 255, (len(self._entries) >> 8) & 255

    # -- season table --
    def season_offset(self, season_no):
        return SEASON_TABLE + (season_no - 1) * SEASON_ENTRY

    def write_season_entry(self, season_no, e):
        o = self.season_offset(season_no)
        struct.pack_into('<H', self.d, o, e['season_no'])
        self.d[o + 2] = e['champion'] & 255
        self.d[o + 3] = e['runner_up'] & 255
        self.d[o + 4:o + 12] = e['champion_stem'].ljust(8, b'\0')[:8]
        self.d[o + 12:o + 20] = e['runner_up_stem'].ljust(8, b'\0')[:8]
        self.d[o + 20] = e['al_pennant'] & 255
        self.d[o + 21] = e['nl_pennant'] & 255
        self.d[o + 22:o + 24] = bytes(2)
        wl = e.get('w_l', [(0, 0)] * 32)
        for t in range(32):
            self.d[o + 24 + 2 * t] = wl[t][0] & 255
            self.d[o + 25 + 2 * t] = wl[t][1] & 255
        hist_awards = e.get('awards', None)
        if hist_awards is None:
            hist_awards = [0] * 6           # absent key: zeros, like files written
        for k, v in enumerate(hist_awards[:6]):    # before the awards field existed
            struct.pack_into('<H', self.d, o + 88 + 2 * k, v & 0xffff)
        self.d[o + 100:o + 128] = bytes(28)

    def read_season_entry(self, season_no):
        o = self.season_offset(season_no)
        e = {}
        e['season_no'] = struct.unpack_from('<H', self.d, o)[0]
        e['champion'] = self.d[o + 2]
        e['runner_up'] = self.d[o + 3]
        e['champion_stem'] = bytes(self.d[o + 4:o + 12]).split(b'\0')[0]
        e['runner_up_stem'] = bytes(self.d[o + 12:o + 20]).split(b'\0')[0]
        e['al_pennant'] = self.d[o + 20]
        e['nl_pennant'] = self.d[o + 21]
        e['w_l'] = [(self.d[o + 24 + 2 * t], self.d[o + 25 + 2 * t]) for t in range(32)]
        e['awards'] = [struct.unpack_from('<H', self.d, o + 88 + 2 * k)[0] for k in range(6)]
        return e


def upgrade_legacy(path):
    """A legacy 4-byte P1 file (done flag + rng word, no byte 3): upgrade in place
    keeping bytes 0..2, writing version 1 and the full 32 B header."""
    raw = open(path, 'rb').read()
    h = History(raw)
    h.version = 1
    if len(raw) < HDR_SIZE:
        h.seasons_recorded = 0
    h.save(path)
    return h


def find_entry(hist, name20, birth):
    """Linear scan; same entry iff name bytes 0..19 and birth match. Returns index
    or -1 (caller appends)."""
    for i in range(len(hist._entries)):
        e = hist.read_entry(i)
        if e['name'] == name20 and e['birth'] == birth:
            return i
    return -1


def maj_or_none(league_dir):
    cands = sorted(glob.glob(os.path.join(league_dir, '*.MAJ')))
    return cands[0] if cands else None


def decode_champion(m):
    """C2 champion decode from the AL/NL playoff blocks (amended 2026-10-08, two samples):
    the AL block holds both series as (team0, team1) with each side's wins:
    LCS teams S+0x3d7/0x3d8, wins S+0x3df/0x3e0; WS teams S+0x3d9 (AL pennant) and
    S+0x3da (NL pennant), wins S+0x3e1/0x3e2. WS winner = the side with more wins
    (tie: 0xff). al_pennant = AL S+0x3d9; nl_pennant = NL S+0x3d9; runner-up = the
    pennant winner that is not the WS winner. 0xff anywhere unknown."""
    s_al, s_nl = 0x21d, 0x758c
    t0 = m.d[s_al + 0x3d9]
    t1 = m.d[s_al + 0x3da]
    w0 = m.d[s_al + 0x3e1]
    w1 = m.d[s_al + 0x3e2]
    al_p = m.d[s_al + 0x3d9]
    nl_p = m.d[s_nl + 0x3d9]
    # ids past the 32 league-global ids are unknown, like 0xff (C2 amendment)
    t0, t1, al_p, nl_p = (v if v < 32 else 0xff for v in (t0, t1, al_p, nl_p))
    ws = t0 if w0 > w1 else t1 if w1 > w0 else 0xff
    runner = 0xff
    if ws != 0xff:
        if al_p == ws:
            runner = nl_p
        elif nl_p == ws:
            runner = al_p
    return ws, runner, al_p, nl_p


def team_stem(m, lg_id):
    """8 B file stem of the team's V20, from the MAJ (NL = slot+16)."""
    if lg_id == 0xff:
        return b''
    lg = 'AL' if lg_id < 16 else 'NL'
    slot = lg_id if lg_id < 16 else lg_id - 16
    return m.stem(lg, slot).encode('latin-1')[:8]


def mapped_teams(league_dir, m):
    """[(v20 path, league-global id)] in sorted file order; files whose stem matches no MAJ slot
    (ALLSTAR1/2.V20) are left out of every history step."""
    teams = []
    for p in sorted(glob.glob(os.path.join(league_dir, '*.V20'))):
        stem = os.path.basename(p)[:-4].lower()
        lg_id = None
        for lg in ('AL', 'NL'):
            base = 0 if lg == 'AL' else 16
            for s in range(16):
                if m.stem(lg, s).lower() == stem:
                    lg_id = base + s
        if lg_id is not None:
            teams.append((p, lg_id))
    return teams


def record_season(league_dir, hist_path, season_no, retirees=None):
    """C2 update order, run BEFORE the P1 rollover mutates anything:
    1. read MAJ standings, champion; write the season entry.
    2. league pass over active records 0..39 (sorted *.V20) using the SEASON half
       (i+40) stats and roster-half bio/ratings: league totals for C3.
    3. per player: find or append, add season stats, status 1, ages, seasons, pos;
       season WAR10, career WAR10 += season, top-7 and JAWS10.
    C7 (after step 3): season awards (6 winners in season bytes 88..99, career award
    counts in player bytes 152..156) and MILESTON.DAT next to HISTORY.DAT
    (read, drop season_no >= current, append this season in entry index order).
    retirees = {v20 basename: [record indexes]} from rollover(); applied later
    by mark_retired() (step 4 runs after the P1 rollover)."""
    hist = History.load(hist_path)
    mp = maj_or_none(league_dir)
    m = maj.Maj.load(mp)
    hist.version = 1
    # 1. season entry
    ws, runner, al_p, nl_p = decode_champion(m)
    entry = {'season_no': season_no, 'champion': ws, 'runner_up': runner,
             'champion_stem': team_stem(m, ws), 'runner_up_stem': team_stem(m, runner),
             'al_pennant': al_p, 'nl_pennant': nl_p, 'w_l': [(0, 0)] * 32}
    for lg in ('AL', 'NL'):
        base = 0 if lg == 'AL' else 16
        for t in range(16):
            w, l = m.wl(lg, t)
            if w or l:
                entry['w_l'][base + t] = (w, l)
    if season_no <= SEASON_COUNT:      # the table holds 64 seasons; later ones keep careers only
        hist.write_season_entry(season_no, entry)
    if season_no > hist.seasons_recorded:
        hist.seasons_recorded = season_no
    # 2. league pass (unmatched stems, e.g. ALLSTAR1/2: skipped entirely)
    teams = mapped_teams(league_dir, m)
    per, lg_totals = war.season_league(teams)
    pf = war.park_factors(mp) if mp else {}
    # 3. per player; collect the C7 inputs per named record
    collected = []
    table_season = season_no <= SEASON_COUNT
    for p, lg_id in teams:
        t = Team.load(p)
        for i in range(40):
            if not t.players[i].active:
                continue
            rec = t.players[i + 40].raw
            roster = t.players[i].raw
            season_games = _get(rec, *F['games'])
            age_before = _get(roster, *F['age'])
            birth = 1000 + season_no - age_before
            name20 = bytes(roster[0:20])
            idx = find_entry(hist, name20, birth)
            pos1 = _get(roster, *F['pos1']) & 15
            totals = war.season_stats_inputs(rec)
            if idx < 0:
                e = {'name': name20, 'birth': birth, 'status': STATUS_ACTIVE,
                     'age': age_before, 'first_season': season_no, 'last_season': season_no,
                     'seasons_played': 0,
                     'pos1': pos1, 'pitcher': 1 if pos1 == 0 else 0,
                     'totals': [0] * 25, 'WAR10': 0, 'top7': [EMPTY_TOP] * 7,
                     'JAWS10': 0, 'hof_season': 0, 'awards': [0] * 5}
                idx = hist.append_entry(e)
            e = hist.read_entry(idx)
            # C7 career totals BEFORE this record's stats are added ('before' is
            # always the entry as it stands, never rewound: milestone idempotence
            # comes only from the drop rule on MILESTON.DAT).
            before = {k: e['totals'][MILESTONE_IDX[k]] for k in MILESTONE_IDX}
            for k, name in enumerate(TOTALS):
                e['totals'][k] = (e['totals'][k] + totals[name]) & 0xffffffff
            e['status'] = STATUS_ACTIVE
            e['age'] = age_before
            e['last_season'] = season_no
            if season_games > 0:
                e['seasons_played'] += 1
            e['pos1'] = pos1
            e['pitcher'] = 1 if pos1 == 0 else 0
            team_pf = pf.get(lg_id, 1000)
            w10 = season_war10(rec, roster, season_games, lg_totals, team_pf, pos1)
            e['WAR10'] += w10
            e['top7'] = sorted(e['top7'] + [w10], reverse=True)[:7]
            e['JAWS10'] = war.jaws10(e['WAR10'], e['top7'])
            hist.write_entry(idx, e)
            exp = _get(roster, *F['exp'])
            c = {'index': idx, 'league': 'AL' if lg_id < 16 else 'NL', 'pos1': pos1,
                 'exp': exp, 'games': season_games, 'w10': w10,
                 'pa': totals['AB'] + totals['BB'],
                 'outs': totals['OUTS'], 'ab': totals['AB'], 'h': totals['H'],
                 'er': totals['ER'],
                 MS_H: totals['H'], MS_HR: totals['HR'],
                 MS_SB: totals['SB'], MS_W: totals['W'], MS_SV: totals['SV'],
                 MS_PSO: totals['PSO'],
                 'range': _get(roster, *F['range']), 'arm': _get(roster, *F['arm']),
                 'po1': _get(rec, *F['po1']), 'a1': _get(rec, *F['a1']),
                 'e1': _get(rec, *F['e1'])}
            bat100 = 0
            if pos1 != 0:
                bat100 = war.batter_bat100(rec, dict(lg_totals, pf1000=team_pf))
            c['bat100'] = bat100
            collected.append((idx, c, before, {k: e['totals'][MILESTONE_IDX[k]]
                                               for k in MILESTONE_IDX}))
    # C7 awards (season table entries 1..64 only) and career award counts (every season)
    # candidates sorted by player entry index (stable; file/slot order is not
    # entry index order for returning players), so ties go to the lower index
    ordered = sorted(collected, key=lambda x: x[0])
    al = [c for _, c, _, _ in ordered if c['league'] == 'AL']
    nl = [c for _, c, _, _ in ordered if c['league'] == 'NL']
    alo = pick_awards(al, lambda x: x['bat100'])
    nlo = pick_awards(nl, lambda x: x['bat100'])
    # winner lists in award-count order: MVP, CY, ROY, GG q=1..8, SS q=1..9
    counts = {}
    for sel in (alo, nlo):
        winners = [sel['mvp'], sel['cy'], sel['roy'],
                   *[sel['gg'].get(q) for q in range(1, 9)],
                   *[sel['ss'].get(q) for q in range(1, 10)]]
        for k, w in enumerate(winners):
            if w is None:
                continue
            ckind = k if k < 3 else (3 if k < 11 else 4)    # MVP/CY/ROY | GG | SS
            counts.setdefault(w['index'], [0] * 5)[ckind] += 1
    for idx in counts:
        e = hist.read_entry(idx)
        aw = e.get('awards')
        if not isinstance(aw, list):
            aw = [0] * 5
        for k in range(5):
            aw[k] = min(255, aw[k] + counts[idx][k])
        e['awards'] = aw
        hist.write_entry(idx, e)
    if table_season:
        se = hist.read_season_entry(season_no)
        se['awards'] = [
            alo['mvp']['index'] if alo['mvp'] else NO_AWARD,
            alo['cy']['index'] if alo['cy'] else NO_AWARD,
            alo['roy']['index'] if alo['roy'] else NO_AWARD,
            nlo['mvp']['index'] if nlo['mvp'] else NO_AWARD,
            nlo['cy']['index'] if nlo['cy'] else NO_AWARD,
            nlo['roy']['index'] if nlo['roy'] else NO_AWARD]
        hist.write_season_entry(season_no, se)
    # C7 milestones: drop season_no >= current (idempotent rerun), append this season
    ms_old = [r for r in milestone_entries(hist_path) if r[0] < season_no]
    exps = {}
    for idx, c, before, after in ordered:
        exps[idx] = {'season': season_no, 'before': before, 'after': after}
    ms_new = season_milestones([c for _, c, _, _ in ordered], exps)
    write_milestones(hist_path, ms_old + ms_new)
    hist.done = 1
    hist.flush()
    hist.save(hist_path)
    return hist


def mark_retired(hist_path, league_dir, retirees, season_no):
    """C2 step 4 (after the P1 rollover): retirees get status 2, then the HoF test.
    status 3 + HoF season = season_no (the season just completed) if it passes.
    league_dir is the PRE-rollover dir (the same V20s record_season read): the rollover
    zeroes a retiree's name byte 0, so the retiree identity (name bytes 0..19,
    birth = 1000 + season_no - age) must come from the pre-roll file."""
    hist = History.load(hist_path)
    mp = maj_or_none(league_dir)
    mapped = {os.path.basename(p) for p, _ in mapped_teams(league_dir, maj.Maj.load(mp))} if mp else set()
    for basename, recs in (retirees or {}).items():
        p = os.path.join(league_dir, basename)
        if basename not in mapped or not os.path.exists(p):
            continue                    # ALLSTAR copies of real players must not retire the real entry
        t = Team.load(p)
        for i in recs:
            roster = t.players[i].raw
            birth = 1000 + season_no - _get(roster, *F['age'])
            idx = find_entry(hist, bytes(roster[0:20]), birth)
            if idx < 0:
                continue
            e = hist.read_entry(idx)
            e['status'] = STATUS_RETIRED
            if hof_passes(e):
                e['status'] = STATUS_HOF
                e['hof_season'] = season_no
            hist.write_entry(idx, e)
    hist.save(hist_path)
    return hist


def hof_passes(e):
    return war.hof_passes({'seasons_played': e['seasons_played'],
                           'H': e['totals'][2], 'HR': e['totals'][5],
                           'AB': e['totals'][1], 'W': e['totals'][13],
                           'PSO': e['totals'][23], 'SV': e['totals'][15],
                           'WAR10': e['WAR10'], 'JAWS10': e['JAWS10']})


def season_bat100(rec, lg_totals, team_pf):
    """C3 bat100 (after the park term) exactly as record_season feeds batter_war10."""
    return war.batter_bat100(rec, dict(lg_totals, pf1000=team_pf))


def season_war10(rec, roster, season_games, lg_totals, team_pf, pos1):
    if pos1 == 0:
        return war.pitcher_war10(rec, season_games, lg_totals)
    return war.batter_war10(rec, roster, season_games, dict(lg_totals, pf1000=team_pf))


def max_by_key(cands, key):
    """max by key(c); ties go to the candidate with the lower entry index
    (cands are (entry_index, value-ish) tuples in ascending player entry order)."""
    best = None
    for c in cands:
        if best is None or key(c) > key(best):
            best = c
    return best


def gold_glove_fp1000(po1, a1, e1):
    """fp1000 = ((po1 + a1) * 1000) / (po1 + a1 + e1), 1000 if the denominator is 0."""
    den = po1 + a1 + e1
    if den == 0:
        return 1000
    return idiv((po1 + a1) * 1000, den)


def pick_awards(recs, bat100_of):
    """C7 award selection over one league's candidate records. recs = the per-record
    collect() dicts of one league in player entry index order (ascending). Returns a
    dict with keys mvp, cy, roy (entry index or None) and gg, ss (entry index per
    position 1..9, or None). bat100_of(c) = the record's bat100 (only for batters)."""
    out = {}
    # MVP: batters with pa >= 502, max season WAR10
    out['mvp'] = max_by_key([c for c in recs if c['pos1'] != 0 and c['pa'] >= 502],
                            lambda c: c['w10'])
    # Cy Young: pitchers with outs >= 486; fallback: any pitcher with outs > 0
    cy = max_by_key([c for c in recs if c['pos1'] == 0 and c['outs'] >= 486],
                    lambda c: c['w10'])
    if cy is None:
        cy = max_by_key([c for c in recs if c['pos1'] == 0 and c['outs'] > 0],
                        lambda c: c['w10'])
    out['cy'] = cy
    # Rookie of the Year: exp 0 and (pa >= 130 or outs >= 150), max season WAR10
    out['roy'] = max_by_key([c for c in recs if c['exp'] == 0
                             and (c['pa'] >= 130 or c['outs'] >= 150)],
                            lambda c: c['w10'])
    # Gold Glove, positions 1..8 by roster pos1
    gg = {}
    for q in range(1, 9):
        need = 90 if q == 1 else 100
        cands = [c for c in recs if c['pos1'] == q and c['games'] >= need]
        best = max_by_key(cands, lambda c: 2 * c['range'] + c['arm'])
        if best is None:
            gg[q] = None
            continue
        top = [c for c in cands if 2 * c['range'] + c['arm'] == 2 * best['range'] + best['arm']]
        best = max_by_key(top, lambda c: gold_glove_fp1000(c['po1'], c['a1'], c['e1']))
        gg[q] = best
    out['gg'] = gg
    # Silver Slugger, positions 1..9 (DH = 9)
    ss = {}
    for q in range(1, 10):
        ss[q] = max_by_key([c for c in recs if c['pos1'] == q and c['pa'] >= 300],
                           bat100_of)
    out['ss'] = ss
    return out


def milestone_entries(hist_path):
    """Read MILESTON.DAT next to a HISTORY.DAT: list of (season, idx, kind, value)
    records; an empty list when the file is missing."""
    p = os.path.join(os.path.dirname(hist_path), 'MILESTON.DAT')
    if not os.path.exists(p):
        return []
    raw = open(p, 'rb').read()
    out = []
    for o in range(0, len(raw) - MILESTONE_RECORD + 1, MILESTONE_RECORD):
        season, idx = raw[o] | raw[o + 1] << 8, raw[o + 2] | raw[o + 3] << 8
        kind, zero = raw[o + 4], raw[o + 5]
        value = raw[o + 6] | raw[o + 7] << 8
        out.append((season, idx, kind, value))
    return out


def write_milestones(hist_path, ms):
    p = os.path.join(os.path.dirname(hist_path), 'MILESTON.DAT')
    d = bytearray()
    for season, idx, kind, value in ms:
        d += struct.pack('<HHBBH', season, idx, kind, 0, min(value, 0xffff))
    open(p, 'wb').write(bytes(d))


def season_milestones(collected, exps_after):
    """Milestone records for one season. collected = the per-record collect() dicts
    (entry_index ordered); exps_after = {entry_index: expiry dict} keyed by entry
    index, each with 'season' and 'before'/'after' career-total dicts. Returns a
    list of (season, idx, kind, value) appended in player entry index order, kinds
    ascending per player."""
    out = []
    for c in collected:
        idx = c['index']
        x = exps_after[idx]
        s = x['season']
        for kind, key, mark in MILESTONE_CAREER:
            before, after = x['before'][key], x['after'][key]
            if before < mark <= after:
                out.append((s, idx, kind, min(after, 0xffff)))
        # season kinds (value = the season stat)
        if c[MS_HR] >= 50:
            out.append((s, idx, 32, c[MS_HR]))
        if c[MS_H] >= 200:
            out.append((s, idx, 33, c[MS_H]))
        if c[MS_SB] >= 100:
            out.append((s, idx, 34, c[MS_SB]))
        if c['pa'] >= 502 and c['ab'] > 0 and idiv(c['h'] * 1000, c['ab']) >= 400:
            out.append((s, idx, 35, idiv(c['h'] * 1000, c['ab'])))
        if c[MS_W] >= 20:
            out.append((s, idx, 36, c[MS_W]))
        if c[MS_PSO] >= 300:
            out.append((s, idx, 37, c[MS_PSO]))
        if c['outs'] >= 486 and idiv(c['er'] * 2700, c['outs']) < 200:
            out.append((s, idx, 38, idiv(c['er'] * 2700, c['outs'])))
        if c[MS_SV] >= 50:
            out.append((s, idx, 39, c[MS_SV]))
    return out


def dump(hist_path):
    h = History.load(hist_path)
    print(f'seasons recorded {h.seasons_recorded}  version {h.version}  done {h.done}')
    for n in range(1, h.seasons_recorded + 1):
        s = h.read_season_entry(n)
        champ = s['champion_stem'].decode('latin-1').rstrip('\0') or '?'
        run = s['runner_up_stem'].decode('latin-1').rstrip('\0') or '?'
        print(f"season {s['season_no']}: {champ} ({s['champion']:#04x}) over {run} "
              f"({s['runner_up']:#04x})  pennants AL {s['al_pennant']:#04x} NL {s['nl_pennant']:#04x}")
    for i in range(len(h._entries)):
        e = h.read_entry(i)
        name = e['name'].decode('latin-1')
        last = name[0:12].split('\0')[0]
        first = name[12:20].split('\0')[0]
        pos = 'P' if e['pitcher'] else '?%d?' % e['pos1']
        used = [v for v in e['top7'] if v != EMPTY_TOP]
        print(f"[{i}] {first} {last}  b{e['birth']} {pos}  s{e['status']} "
              f"seasons {e['first_season']}..{e['last_season']} ({e['seasons_played']})  "
              f"WAR10 {e['WAR10']}  top {used}  JAWS10 {e['JAWS10']}"
              + (f"  HoF {e['hof_season']}" if e['status'] == STATUS_HOF else ''))


def main(argv):
    if len(argv) >= 3 and argv[1] == 'dump':
        dump(argv[2])
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
