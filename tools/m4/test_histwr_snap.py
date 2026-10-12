#!/usr/bin/env python3
"""C16.2 tests: HISTWR /SNAP and /ARCHIVE (tools/m4/histwr/histwr.c) on the host build.

Explicit paths: byte-exact copies (block boundaries of the 2048 B copy buffer), overwrite with extra files kept,
subdirectories not copied, missing parents made, the slot choice (S01..S03 holding or lacking a *.MAJ), all 99
full, exit codes. No-argument defaults: run with cwd = a game dir whose SYSTEM names a league (and one invalid
name, which falls back to CLASSIC); the files must land at the C16.1 host paths (C:/DYNLG/<L>/SNAP, ...).
Run:  python3 -m pytest -q tools/m4/test_histwr_snap.py
The host binary tools/m4/histwr/histwr_host is built at import (build_histwr.py).
"""
import os
import random

import pytest
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

HW = os.path.join(HERE, 'histwr')
HOST = os.path.join(HW, 'histwr_host')


def _build():
    r = subprocess.run([sys.executable, os.path.join(HW, 'build_histwr.py')], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed:\n' + r.stdout + r.stderr)
    if not os.path.exists(HOST):
        raise RuntimeError('host binary missing after build')


_build()


def run(*args, cwd=None):
    return subprocess.run([HOST, *args], capture_output=True, text=True, cwd=cwd)


def blob(n, seed):
    return random.Random(seed).randbytes(n)


def files(d):
    """{name: bytes} of the regular files directly in d."""
    return {p.name: p.read_bytes() for p in sorted(Path(d).iterdir()) if p.is_file()}


def fill(d, spec):
    """Write {name: bytes} into d (made)."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    for name, data in spec.items():
        (d / name).write_bytes(data)
    return d


def league(root, name='LG'):
    """A league dir with exact-copy fixtures: block sizes around 2048, an empty file, all byte values."""
    spec = {
        'CLASSIC.MAJ': blob(59771, 1),
        'HISTORY.DAT': blob(2048, 2),
        'TEAMID.DAT': blob(2047, 3),
        'ZERO.DAT': b'',
        'BIG.V20': blob(5000, 4),
        'ALL.BIN': bytes(range(256)) * 3,
        'lower.v20': blob(2049, 5),
    }
    return fill(Path(root) / name, spec)


# ---------------------------------------------------------------- /SNAP, explicit paths

def test_snap_copies_every_regular_file_byte_exact(tmp_path):
    ldir = league(tmp_path)
    sdir = tmp_path / 'snap'
    r = run('/SNAP', str(ldir), str(sdir))
    assert r.returncode == 0, r.stderr
    assert r.stdout == '' and r.stderr == ''
    want = files(ldir)
    assert files(sdir) == want
    assert len(want) == 7 and want['BIG.V20'] == blob(5000, 4)


def test_snap_overwrites_same_names_and_keeps_extra_files(tmp_path):
    ldir = league(tmp_path)
    sdir = fill(tmp_path / 'snap', {'CLASSIC.MAJ': b'old', 'OLD.V20': b'keep me', 'ZERO.DAT': b'x'})
    assert run('/SNAP', str(ldir), str(sdir)).returncode == 0
    got = files(sdir)
    assert got['CLASSIC.MAJ'] == files(ldir)['CLASSIC.MAJ']
    assert got['ZERO.DAT'] == b''
    assert got['OLD.V20'] == b'keep me'


def test_snap_copies_no_subdirectories(tmp_path):
    ldir = league(tmp_path)
    fill(ldir / 'SUB', {'INNER.DAT': b'deep'})
    sdir = tmp_path / 'snap'
    assert run('/SNAP', str(ldir), str(sdir)).returncode == 0
    assert not (sdir / 'SUB').exists()
    assert 'INNER.DAT' not in files(sdir)
    assert sorted(p.name for p in sdir.iterdir()) == sorted(files(ldir))


def test_snap_makes_missing_parents(tmp_path):
    ldir = league(tmp_path)
    sdir = tmp_path / 'C' / 'DYNLG' / 'LG' / 'SNAP'
    assert run('/SNAP', str(ldir), str(sdir)).returncode == 0
    assert files(sdir) == files(ldir)


def test_snap_same_dir_copies_nothing_and_keeps_bytes(tmp_path):
    ldir = league(tmp_path)
    before = files(ldir)
    assert run('/SNAP', str(ldir), str(ldir)).returncode == 0
    assert files(ldir) == before


@pytest.mark.parametrize('alias', ['{d}/', '{d}//', '{d}/../{n}', '{d}/./', 'link'])
def test_snap_same_dir_under_another_spelling_keeps_bytes(tmp_path, alias):
    """the same directory spelled differently (trailing separators, . and .., a symlink) keeps every byte:
    each file already is its destination"""
    ldir = league(tmp_path)
    before = files(ldir)
    if alias == 'link':
        other = tmp_path / 'link'
        other.symlink_to(ldir, target_is_directory=True)
        other = str(other)
    else:
        other = alias.format(d=str(ldir), n=ldir.name)
    assert run('/SNAP', str(ldir), other).returncode == 0
    assert files(ldir) == before
    assert run('/SNAP', other, str(ldir)).returncode == 0
    assert files(ldir) == before


def test_archive_into_its_own_snap_keeps_bytes(tmp_path):
    """SEASONS_DIR/S01 that is SNAP_DIR itself (via ..): every byte stays"""
    seasons = tmp_path / 'SEAS'
    snap = fill(seasons / 'S01', {'X.DAT': blob(3000, 9)})
    before = files(snap)
    assert run('/ARCHIVE', str(seasons / 'S01' / '..' / 'S01'), str(seasons)).returncode == 0
    assert files(snap) == before


def test_snap_exit_1_when_league_dir_missing(tmp_path):
    r = run('/SNAP', str(tmp_path / 'nope'), str(tmp_path / 'snap'))
    assert r.returncode == 1


def test_snap_exit_1_when_a_copy_fails(tmp_path):
    ldir = league(tmp_path)
    sdir = tmp_path / 'snap'
    (sdir / 'CLASSIC.MAJ').mkdir(parents=True)     # a directory where the copy must write a file
    assert run('/SNAP', str(ldir), str(sdir)).returncode == 1


def test_snap_wrong_arg_count_is_usage(tmp_path):
    assert run('/SNAP', str(tmp_path)).returncode == 2
    assert run('/SNAP', 'a', 'b', 'c').returncode == 2


def test_switch_is_case_insensitive(tmp_path):
    ldir = league(tmp_path)
    assert run('/snap', str(ldir), str(tmp_path / 'a')).returncode == 0
    assert run('/Snap', str(ldir), str(tmp_path / 'b')).returncode == 0
    assert files(tmp_path / 'b') == files(ldir)


# ---------------------------------------------------------------- /ARCHIVE, explicit paths

MAJ = b'\x7fMAJ'


def snap_with_maj(root):
    return fill(Path(root) / 'snap', {'CLASSIC.MAJ': blob(3000, 9), 'HISTORY.DAT': blob(2100, 8),
                                      'RETIRED.DAT': b'\x01\x02'})


def test_archive_picks_first_slot_without_a_maj(tmp_path):
    snap = snap_with_maj(tmp_path)
    seasons = tmp_path / 'SEASONS'
    fill(seasons / 'S01', {'CLASSIC.MAJ': MAJ})
    fill(seasons / 'S02', {'NOTES.TXT': b'no maj here'})
    fill(seasons / 'S03', {'OLD.MAJ': MAJ})
    r = run('/ARCHIVE', str(snap), str(seasons))
    assert r.returncode == 0, r.stderr
    assert r.stdout == ''
    assert files(seasons / 'S01') == {'CLASSIC.MAJ': MAJ}                  # untouched
    assert files(seasons / 'S03') == {'OLD.MAJ': MAJ}                      # untouched
    got = files(seasons / 'S02')
    assert got == {**files(snap), 'NOTES.TXT': b'no maj here'}             # extras kept
    assert not (seasons / 'S04').exists()


def test_archive_twice_moves_to_the_next_free_slot(tmp_path):
    snap = snap_with_maj(tmp_path)
    seasons = tmp_path / 'SEASONS'
    assert run('/ARCHIVE', str(snap), str(seasons)).returncode == 0      # S01
    assert run('/ARCHIVE', str(snap), str(seasons)).returncode == 0      # S01 holds a MAJ: S02
    assert files(seasons / 'S01') == files(snap)
    assert files(seasons / 'S02') == files(snap)
    assert not (seasons / 'S03').exists()


def test_archive_creates_missing_seasons_and_parents(tmp_path):
    snap = snap_with_maj(tmp_path)
    seasons = tmp_path / 'C' / 'SEASONS'
    assert run('/ARCHIVE', str(snap), str(seasons)).returncode == 0
    assert files(seasons / 'S01') == files(snap)


def test_archive_all_99_full_copies_nothing(tmp_path):
    snap = snap_with_maj(tmp_path)
    seasons = tmp_path / 'SEASONS'
    for nn in range(1, 100):
        fill(seasons / f'S{nn:02d}', {'CLASSIC.MAJ': bytes([nn])})
    before = {nn: files(seasons / f'S{nn:02d}') for nn in range(1, 100)}
    r = run('/ARCHIVE', str(snap), str(seasons))
    assert r.returncode == 0
    assert sorted(p.name for p in seasons.iterdir()) == sorted(f'S{nn:02d}' for nn in range(1, 100))
    assert {nn: files(seasons / f'S{nn:02d}') for nn in range(1, 100)} == before


def test_archive_99_is_the_last_slot(tmp_path):
    snap = snap_with_maj(tmp_path)
    seasons = tmp_path / 'SEASONS'
    for nn in range(1, 99):
        fill(seasons / f'S{nn:02d}', {'CLASSIC.MAJ': MAJ})
    assert run('/ARCHIVE', str(snap), str(seasons)).returncode == 0
    assert files(seasons / 'S99') == files(snap)


def test_archive_ignores_subdirs_of_snap(tmp_path):
    snap = snap_with_maj(tmp_path)
    fill(snap / 'SUB', {'INNER.MAJ': MAJ})
    seasons = tmp_path / 'SEASONS'
    assert run('/ARCHIVE', str(snap), str(seasons)).returncode == 0
    assert not (seasons / 'S01' / 'SUB').exists()
    assert files(seasons / 'S01') == files(snap)


def test_archive_exit_1_when_snap_missing(tmp_path):
    assert run('/ARCHIVE', str(tmp_path / 'nope'), str(tmp_path / 'SEASONS')).returncode == 1


def test_archive_exit_1_when_the_slot_cannot_be_made(tmp_path):
    snap = snap_with_maj(tmp_path)
    seasons = tmp_path / 'SEASONS'
    seasons.mkdir()
    (seasons / 'S01').write_bytes(b'a file, not a slot')
    assert run('/ARCHIVE', str(snap), str(seasons)).returncode == 1


def test_archive_wrong_arg_count_is_usage(tmp_path):
    assert run('/ARCHIVE', str(tmp_path)).returncode == 2
    assert run('/ARCHIVE', 'a', 'b', 'c').returncode == 2


# ---------------------------------------------------------------- no-argument defaults (C16.1)

def game_dir(root, system):
    """A game dir (the cwd) with SYSTEM as given, or none when system is None."""
    g = Path(root) / 'game'
    g.mkdir()
    if system is not None:
        (g / 'SYSTEM').write_bytes(system)
    return g


def test_snap_default_follows_system_league(tmp_path):
    g = game_dir(tmp_path, b'ALT\0\0\0\0\0')
    ldir = league(g / 'TEAMS', 'ALT')
    (g / 'TEAMS' / 'ALT' / 'ALT.MAJ').write_bytes(MAJ)
    r = run('/SNAP', cwd=str(g))
    assert r.returncode == 0, r.stderr
    assert files(g / 'C:' / 'DYNLG' / 'ALT' / 'SNAP') == files(ldir)
    assert not (g / 'C:' / 'DYNSNAP').exists()


def test_snap_default_invalid_name_is_classic(tmp_path):
    g = game_dir(tmp_path, b'BAD NAME')
    ldir = league(g / 'TEAMS', 'CLASSIC')
    r = run('/SNAP', cwd=str(g))
    assert r.returncode == 0, r.stderr
    assert files(g / 'C:' / 'DYNSNAP') == files(ldir)
    assert not (g / 'C:' / 'DYNLG').exists()


def test_snap_default_without_maj_is_classic(tmp_path):
    g = game_dir(tmp_path, b'ALT\0')            # ALT names a league, but its MAJ is missing
    ldir = league(g / 'TEAMS', 'CLASSIC')
    assert run('/SNAP', cwd=str(g)).returncode == 0
    assert files(g / 'C:' / 'DYNSNAP') == files(ldir)


def test_snap_default_without_system_is_classic(tmp_path):
    g = game_dir(tmp_path, None)
    ldir = league(g / 'TEAMS', 'CLASSIC')
    assert run('/SNAP', cwd=str(g)).returncode == 0
    assert files(g / 'C:' / 'DYNSNAP') == files(ldir)


def test_archive_default_follows_system_league(tmp_path):
    g = game_dir(tmp_path, b"NEGRO'LG")
    fill(g / 'TEAMS' / "NEGRO'LG", {"NEGRO'LG.MAJ": MAJ})
    snap = fill(g / 'C:' / 'DYNLG' / "NEGRO'LG" / 'SNAP', {"NEGRO'LG.MAJ": blob(100, 3), 'HISTORY.DAT': b'h'})
    r = run('/ARCHIVE', cwd=str(g))
    assert r.returncode == 0, r.stderr
    assert files(g / 'C:' / 'DYNLG' / "NEGRO'LG" / 'S01') == files(snap)
    assert not (g / 'C:' / 'SEASONS').exists()


def test_archive_default_invalid_name_is_classic(tmp_path):
    g = game_dir(tmp_path, b'x/y')
    snap = fill(g / 'C:' / 'DYNSNAP', {'CLASSIC.MAJ': blob(50, 4)})
    assert run('/ARCHIVE', cwd=str(g)).returncode == 0
    assert files(g / 'C:' / 'SEASONS' / 'S01') == files(snap)
