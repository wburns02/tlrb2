"""Tests for teamids.py (contract C12.1 engine ids and C12.3 stable ids).
Run:  python3 -m pytest -q tools/m4/test_teamids.py
All fixtures are synthetic (build_maj), built in tmp_path or in memory.
"""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import maj  # noqa: E402
import teamids as ti  # noqa: E402

S = ti.S


def build_maj(teams, divs=2, day=0x07):
    """Synthetic 59771 B MAJ. teams: {L: [(slot, abbr)]}. Noise everywhere the game does not use, so writes
    outside the tables show up. Slot 15 holds an all-star entry (NUL stem, non-empty name) unless a team sits
    there. Header stems at 10 + 8 * engine id, as the game writes them."""
    d = bytearray(random.Random(7).randbytes(maj.SIZE))
    d[0x20a], d[0x20c], d[0x20d] = day, 2, divs
    d[10:266] = bytes(256)
    for L in (0, 1):
        s = S[L]
        d[s + ti.O_NAMES:s + ti.O_NAMES + 16 * 24] = bytes(16 * 24)
        d[s + ti.O_ABBR:s + ti.O_ABBR + 3 * 24] = bytes(3 * 24)
        d[s + ti.O_STEM:s + ti.O_STEM + 8 * 24] = bytes(8 * 24)
        rows = {slot: (abbr.encode(), ('A' if L == 0 else 'N').encode() + abbr.encode())
                for slot, abbr in teams.get(L, [])}
        rows.setdefault(15, (b'AS', b'\0ASTAR'))
        for slot, (abbr, stem) in rows.items():
            name = b'ALL STARS' if slot == 15 and stem[:1] == b'\0' else b'TEAM ' + abbr
            a = s + ti.O_NAMES + 16 * slot
            d[a:a + 16] = name.ljust(14, b'\0') + b'cl'
            a = s + ti.O_ABBR + 3 * slot
            d[a:a + 3] = abbr.ljust(3, b'\0')
            a = s + ti.O_STEM + 8 * slot
            d[a:a + 8] = stem.ljust(8, b'\0')
            if stem[:1] != b'\0':
                e = ti.slot_to_engine(L, slot, divs)
                d[10 + 8 * e:18 + 8 * e] = stem.ljust(8, b'\0')
    return bytes(d)


def abbr_at(d, L, slot):
    a = S[L] + ti.O_ABBR + 3 * slot
    return bytes(d[a:a + 3]).rstrip(b'\0').decode()


CLASSIC = {
    0: [(0, 'BAL'), (1, 'BOS'), (2, 'CLE'), (3, 'DET'), (4, 'MIL'), (5, 'NYA'), (6, 'TOR'),
        (8, 'CAL'), (9, 'CHA'), (10, 'KC'), (11, 'MIN'), (12, 'OAK'), (13, 'SEA'), (14, 'TEX')],
    1: [(0, 'CHN'), (1, 'MON'), (2, 'NYN'), (3, 'PHI'), (4, 'PIT'), (5, 'SL'),
        (8, 'ATL'), (9, 'CIN'), (10, 'HOU'), (11, 'LA'), (12, 'SD'), (13, 'SF')],
}
THREE_RAW = [*range(5), *range(8, 13), *range(16, 21)]


def test_ndiv_reads_0x20d_and_defaults_to_two():
    assert ti.ndiv(build_maj({}, divs=3)) == 3
    assert ti.ndiv(build_maj({}, divs=2)) == 2
    assert ti.ndiv(build_maj({}, divs=1)) == 1
    assert ti.ndiv(bytes(0x20d)) == 2                       # too short to hold 0x20d
    for v in (0, 4, 0xff):
        d = bytearray(build_maj({}))
        d[0x20d] = v
        assert ti.ndiv(bytes(d)) == 2


def test_raw_accepts_a_maj_object():
    d = build_maj(CLASSIC)
    assert ti.ndiv(maj.Maj(d)) == 2
    assert ti.teams(maj.Maj(d), None) == ti.teams(d, None)


def test_three_division_compaction_values():
    assert [ti.slot_to_engine(0, s, 3) for s in THREE_RAW] == [*range(5), *range(5, 10), *range(10, 15)]
    assert [ti.slot_to_engine(1, s, 3) for s in THREE_RAW] == [16 + c for c in range(15)]
    assert [ti.engine_to_slot(e, 3)[1] for e in range(15)] == THREE_RAW
    assert ti.engine_to_slot(21, 2) == (1, 5) and ti.slot_to_engine(1, 5, 2) == 21


@pytest.mark.parametrize('nd,slots', [(2, range(16)), (3, THREE_RAW)])
def test_engine_round_trip(nd, slots):
    for L in (0, 1):
        for slot in slots:
            e = ti.slot_to_engine(L, slot, nd)
            assert 0 <= e < 32
            assert ti.engine_to_slot(e, nd) == (L, slot)


def test_maj_teams_order_skips_nul_stems_and_short_maj():
    d = build_maj({0: [(3, 'BAL'), (0, 'BOS')], 1: [(5, 'ATL')]})
    assert [(L, slot) for L, slot, _st in ti.maj_teams(d)] == [(0, 0), (0, 3), (1, 5)]
    assert ti.maj_teams(d)[0][2] == b'ABOS\0\0\0\0'
    assert ti.maj_teams(bytes(S[1] + ti.O_STEM + 8 * 24 - 1)) == []
    assert ti.maj_teams(bytes(S[1] + ti.O_STEM + 8 * 24)) == []     # all NUL stems, no teams


def test_load_table_missing_wrong_size_and_any_case(tmp_path):
    assert ti.load_table(str(tmp_path)) is None
    (tmp_path / 'TEAMID.DAT').write_bytes(bytes(255))
    assert ti.load_table(str(tmp_path)) is None
    (tmp_path / 'TEAMID.DAT').write_bytes(bytes(256))
    tab = ti.load_table(str(tmp_path))
    assert len(tab) == 32 and all(len(e) == 8 for e in tab)
    (tmp_path / 'TEAMID.DAT').unlink()
    (tmp_path / 'teamid.dat').write_bytes(b'A' * 256)
    assert ti.load_table(str(tmp_path)) == [b'A' * 8] * 32
    assert ti.load_table(str(tmp_path / 'nope')) is None


def test_make_table_two_divisions_is_engine_ids():
    d = build_maj(CLASSIC)
    t = ti.make_table(d)
    assert len(t) == ti.TABLE_SIZE
    teams_here = ti.maj_teams(d)
    for L, slot, st in teams_here:
        k = L * 16 + slot
        assert t[8 * k:8 * k + 8] == st
    assert sum(1 for k in range(32) if t[8 * k] != 0) == len(teams_here)


def test_make_table_ignores_slots_the_division_count_does_not_use():
    d = build_maj({0: [(5, 'XXX'), (8, 'YYY')]}, divs=3)      # raw 5 is unused with 3 divisions; raw 8 is engine 5
    t = ti.make_table(d)
    assert t[40:48] == b'AYYY\0\0\0\0'
    assert [st for _k, _L, _s, st in ti.teams(d, None)] == [b'AYYY\0\0\0\0']
    d = build_maj({0: [(3, 'XXX'), (16, 'YYY')], 1: [(0, 'ZZZ')]})   # 2 divisions: AL slot 16 never steals NL id 16
    assert [(k, L, s) for k, L, s, _st in ti.teams(d, None)] == [(3, 0, 3), (16, 1, 0)]


def test_two_division_ids_without_a_table_are_the_c2_rule():
    d = build_maj(CLASSIC)
    got = ti.teams(d, None)
    assert len(got) == 26
    assert all(k == L * 16 + slot for k, L, slot, _st in got)


def _ids(d, table):
    return [(k, L, slot) for k, L, slot, _st in ti.teams(d, table)]


def test_table_ids_match_stems_case_insensitively_and_keep_the_lowest_k():
    d = build_maj(CLASSIC)
    t = bytearray(ti.make_table(d))
    before = _ids(d, None)
    assert _ids(d, bytes(t)) == before
    t[15 * 8:15 * 8 + 8] = t[3 * 8:3 * 8 + 8]                  # a second entry (15 is free) with DET's stem: id 3
    assert _ids(d, bytes(t)) == before
    lower = bytearray(d)
    a = S[0] + ti.O_STEM + 8 * 1
    lower[a:a + 8] = lower[a:a + 8].lower()                    # BOS in lower case still matches entry 1
    assert _ids(bytes(lower), bytes(t)) == before


def test_a_team_without_a_table_entry_is_left_out():
    d = build_maj(CLASSIC)
    t = bytearray(ti.make_table(d))
    t[1 * 8:1 * 8 + 8] = bytes(8)                              # BOS has no entry any more
    got = ti.teams(d, bytes(t))
    assert len(got) == 25 and 1 not in [k for k, *_ in got]


def test_a_duplicate_stem_is_left_out_after_the_first_team():
    d = build_maj({0: [(0, 'BAL'), (1, 'BAL')]})
    got = ti.teams(d, ti.make_table(d))
    assert [(k, L, slot) for k, L, slot, _st in got] == [(0, 0, 0)]


def test_lookups_on_a_three_division_maj_without_a_table():
    d = build_maj({0: [(0, 'BAL'), (8, 'CAL'), (16, 'CHA')]}, divs=3)
    assert ti.id_of_slot(d, None, 0, 8) == 5
    assert ti.slot_of_id(d, None, 10) == (0, 16)
    assert ti.slot_of_id(d, None, 3) is None
    assert ti.id_of_engine(d, None, 5) == 5
    assert ti.id_of_engine(d, None, 6) == 0xff                 # engine slot 9 holds no team
    assert ti.id_of_engine(d, None, 0xff) == 0xff
    assert ti.id_of_engine(d, None, 40) == 0xff
    assert ti.stem_of_id(d, None, 5) == b'ACAL'
    assert ti.stem_of_id(d, None, 3) == b''


def test_stable_ids_survive_a_layout_change():
    two = build_maj({0: [(0, 'BAL'), (9, 'CAL')]}, divs=2)
    table = ti.make_table(two)
    three = build_maj({0: [(0, 'BAL'), (8, 'CAL')]}, divs=3)
    assert ti.id_of_slot(three, table, 0, 8) == 9
    assert ti.id_of_engine(three, table, 5) == 9               # engine 5 is CAL in the 3-division layout
    assert ti.id_of_engine(three, table, 9) == 0xff            # engine 9 holds no team there
    assert ti.stem_of_id(three, table, 9) == b'ACAL'
    assert [(k, L, slot) for k, L, slot, _st in ti.teams(three, table)] == [(0, 0, 0), (9, 0, 8)]


def test_a_table_built_from_the_league_gives_the_engine_ids_back():
    two = build_maj(CLASSIC)
    table = ti.make_table(two)
    assert _ids(two, table) == _ids(two, None)
    assert [abbr_at(two, L, slot) for _k, L, slot, _st in ti.teams(two, table)][:3] == ['BAL', 'BOS', 'CLE']
