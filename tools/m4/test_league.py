#!/usr/bin/env python3
"""C16.1 tests: the current league and its paths, tools/m4/league.py against its C port tools/m4/league.h.

The host harness tools/m4/league_c/lg_host is built at import (build_lg.py). The parity test writes 300 random
SYSTEM files (lengths 0..76, NULs, letters, lowercase, apostrophes, forbidden bytes, high bytes), each with and
without its TEAMS/<L>/<L>.MAJ (empty or not), and checks the C output against league.py for both separators.
Run:  python3 -m pytest -q tools/m4/test_league.py
"""
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pytest                                   # noqa: E402

import league                                   # noqa: E402

LG_C = os.path.join(HERE, 'league_c')
LG_HOST = os.path.join(LG_C, 'lg_host')
FORBID = b'"*+,./:;<=>?[\\]|'


def _build():
    r = subprocess.run([sys.executable, os.path.join(LG_C, 'build_lg.py')], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('build failed:\n' + r.stdout + r.stderr)
    if not os.path.exists(LG_HOST):
        raise RuntimeError('host binary missing after build')


_build()


def c_out(game_dir, sep, cwd=None):
    """lg_host's lines as a dict (name, fromsys, dir, hist, snap, seasons, ret, maj)."""
    r = subprocess.run([LG_HOST, game_dir, sep], capture_output=True, text=True, cwd=cwd)
    assert r.returncode == 0, r.stderr
    out = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition('=')
        out[k] = v
    return out


def py_out(game_dir, sep):
    name, fromsys = league.current_info(game_dir)
    out = {'name': name, 'fromsys': str(fromsys)}
    out.update(league.paths(name, sep))
    return out


def write_system(gdir, data):
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / 'SYSTEM').write_bytes(data)


def write_maj(gdir, name, data=b''):
    d = gdir / 'TEAMS' / name
    d.mkdir(parents=True, exist_ok=True)
    (d / (name + '.MAJ')).write_bytes(data)


# ---------------------------------------------------------------- name rules

@pytest.mark.parametrize('data, want', [
    (b'CLASSIC\0\0', 'CLASSIC'),
    (b'classic', 'CLASSIC'),                     # 7 bytes, no NUL: the whole read is the name
    (b"negro'lg", "NEGRO'LG"),                   # apostrophes are valid; lowercase becomes upper
    (b'ABCDEFGHIJ', 'ABCDEFGH'),                 # no NUL: the first 8 bytes, the rest ignored
    (b'ABCDEFG\0', 'ABCDEFG'),
    (b'AB\0CD', 'AB'),                           # the first NUL ends the name
    (b'AB!#$%&()-@', 'AB!#$%&('),                # the first 8 bytes only
    (b'AB!', 'AB!'),                             # 0x21 is the lowest valid byte
    (b'AB~', 'AB~'),                             # 0x7e the highest
    (b'', None),                                 # empty
    (b'\0ABC', None),                            # NUL first: empty name
    (b'AB CD', None),                            # space is not a name byte
    (b'AB\x7f', None),
    (b'A\x80', None),
    (b'A\x1f', None),
])
def test_parse_name(data, want):
    assert league.parse_name(data) == want


@pytest.mark.parametrize('c', list(FORBID))
def test_parse_name_forbidden_bytes(c):
    assert league.parse_name(b'AB' + bytes([c])) is None
    assert league.parse_name(bytes([c])) is None


def test_forbidden_set_matches_c16_1():
    assert ''.join(sorted(chr(c) for c in league.FORBIDDEN)) == ''.join(sorted('"*+,./:;<=>?[\\]|'))


# ---------------------------------------------------------------- current()

def test_no_system_file_is_classic(tmp_path):
    assert league.current_info(str(tmp_path)) == ('CLASSIC', 0)


def test_empty_system_is_classic(tmp_path):
    write_system(tmp_path, b'')
    write_maj(tmp_path, 'CLASSIC')
    assert league.current_info(str(tmp_path)) == ('CLASSIC', 0)


def test_valid_name_needs_its_maj(tmp_path):
    write_system(tmp_path, b"NEGRO'LG\0")
    assert league.current_info(str(tmp_path)) == ('CLASSIC', 0)
    write_maj(tmp_path, "NEGRO'LG")
    assert league.current_info(str(tmp_path)) == ("NEGRO'LG", 1)
    assert league.current(str(tmp_path)) == "NEGRO'LG"


def test_empty_maj_still_opens(tmp_path):
    write_system(tmp_path, b'ALT\0')
    write_maj(tmp_path, 'ALT', b'')
    assert league.current_info(str(tmp_path)) == ('ALT', 1)


def test_maj_directory_does_not_open(tmp_path):
    write_system(tmp_path, b'ALT\0')
    (tmp_path / 'TEAMS' / 'ALT' / 'ALT.MAJ').mkdir(parents=True)
    assert league.current_info(str(tmp_path)) == ('CLASSIC', 0)


def test_invalid_name_is_classic_even_with_a_maj(tmp_path):
    write_system(tmp_path, b'BAD NAME')
    write_maj(tmp_path, 'BAD NAME')
    assert league.current_info(str(tmp_path)) == ('CLASSIC', 0)


def test_explicit_classic_counts_as_from_system(tmp_path):
    write_system(tmp_path, b'classic\0')
    write_maj(tmp_path, 'CLASSIC')
    assert league.current_info(str(tmp_path)) == ('CLASSIC', 1)


def test_dot_is_the_cwd(tmp_path, monkeypatch):
    write_system(tmp_path, b'ALT\0')
    write_maj(tmp_path, 'ALT')
    monkeypatch.chdir(tmp_path)
    assert league.current() == 'ALT'
    assert league.current('.') == 'ALT'
    assert league.current_info('') == ('ALT', 1)


# ---------------------------------------------------------------- paths()

def test_paths_classic_dos():
    assert league.paths('CLASSIC', '\\') == {
        'dir': 'TEAMS\\CLASSIC',
        'hist': 'TEAMS\\CLASSIC\\HISTORY.DAT',
        'snap': 'C:\\DYNSNAP',
        'seasons': 'C:\\SEASONS',
        'ret': 'C:\\DYNSNAP\\RETIRED.DAT',
        'maj': 'TEAMS\\CLASSIC\\CLASSIC.MAJ',
    }


def test_paths_league_dos():
    assert league.paths("NEGRO'LG", '\\') == {
        'dir': "TEAMS\\NEGRO'LG",
        'hist': "TEAMS\\NEGRO'LG\\HISTORY.DAT",
        'snap': "C:\\DYNLG\\NEGRO'LG\\SNAP",
        'seasons': "C:\\DYNLG\\NEGRO'LG",
        'ret': "C:\\DYNLG\\NEGRO'LG\\SNAP\\RETIRED.DAT",
        'maj': "TEAMS\\NEGRO'LG\\NEGRO'LG.MAJ",
    }


def test_paths_host_sep_and_default():
    assert league.paths('ALT', '/')['snap'] == 'C:/DYNLG/ALT/SNAP'
    assert league.paths('CLASSIC')['maj'] == 'TEAMS\\CLASSIC\\CLASSIC.MAJ'


# ---------------------------------------------------------------- C port parity

UPPER = b'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
NAME_POOL = UPPER + UPPER.lower() + b'0123456789' + b"'!#$%&()-@^_`{}~"


def _random_system(rng):
    """SYSTEM bytes of 0..76: half name-like (1..9 name bytes, now and then a forbidden one, usually a NUL),
    half noise; both padded with random bytes to the length."""
    length = rng.randint(0, 76)
    data = bytearray()
    if rng.random() < 0.5:
        for _ in range(rng.randint(1, 9)):
            data.append(rng.choice(FORBID) if rng.random() < 0.08 else rng.choice(NAME_POOL))
        if rng.random() < 0.7:
            data.append(0)
    while len(data) < length:
        data.append(rng.randrange(256))
    return bytes(data[:length])


def test_c_matches_python_on_300_random_systems(tmp_path):
    rng = random.Random(0x16C1)
    stats = {'valid': 0, 'maj': 0, 'lower': 0, 'apos': 0, 'maj_empty': 0, 'classic': 0}
    for i in range(300):
        gdir = tmp_path / f'g{i:03d}'
        data = _random_system(rng)
        write_system(gdir, data)
        name = league.parse_name(data[:league.NAME_MAX])
        if name is not None:
            stats['valid'] += 1
            stats['lower'] += any(0x61 <= c <= 0x7a for c in data[:len(name)])
            stats['apos'] += b"'" in data[:len(name)]
            if rng.random() < 0.5:
                empty = rng.random() < 0.5
                write_maj(gdir, name, b'' if empty else b'\x01\x02')
                stats['maj'] += 1
                stats['maj_empty'] += int(empty)
        want = py_out(str(gdir), '/')
        stats['classic'] += want['fromsys'] == '0'
        for sep in ('/', '\\'):
            assert c_out(str(gdir), sep) == py_out(str(gdir), sep), (i, data, sep)
    # the sample must reach every branch, or the parity count proves little
    assert stats['valid'] >= 60 and stats['maj'] >= 30 and stats['lower'] >= 5, stats
    assert stats['apos'] >= 1 and stats['maj_empty'] >= 5 and stats['classic'] >= 100, stats


def test_dot_game_dir_matches_python(tmp_path, monkeypatch):
    write_system(tmp_path, b"NEGRO'LG\0")
    write_maj(tmp_path, "NEGRO'LG")
    monkeypatch.chdir(tmp_path)
    for sep in ('/', '\\'):
        assert c_out('.', sep) == py_out('.', sep)
        assert c_out('', sep, cwd=str(tmp_path)) == py_out('', sep)
    assert c_out('.', '/')['name'] == "NEGRO'LG"


def test_c_rejects_bad_sep(tmp_path):
    r = subprocess.run([LG_HOST, str(tmp_path), 'x'], capture_output=True, text=True)
    assert r.returncode == 2
