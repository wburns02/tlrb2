#!/usr/bin/env python3
"""The current league for the dynasty tools (contract C16.1).

current(game_dir) names the league the game is on: SYSTEM in the game directory holds it in its first 8 bytes,
and it counts only when the league's stock MAJ TEAMS<sep><L><sep><L>.MAJ opens. Anything else is CLASSIC, which
keeps every path the dynasty tools had before C16. paths(name, sep) gives the dynasty files of a league
(C16.1 paths, used by HISTWR, ROSTERS, CREATE and DYNASTY).

league.h is the C port; test_league.py checks both sides byte for byte. The game directory is the cwd of every
tool under TONY2.BAT, and "" or "." name the cwd.
"""
import os

CLASSIC = 'CLASSIC'
SYSTEM_FILE = 'SYSTEM'
NAME_MAX = 8
# the bytes a league name may not hold (C16.1), beside the space and the controls outside 0x21..0x7e
FORBIDDEN = frozenset(b'"*+,./:;<=>?[\\]|')


def parse_name(data):
    """The league name SYSTEM bytes give (upper-cased), or None when the name is invalid.

    The name is bytes 0..7 up to the first NUL (8 bytes when there is none): valid when 1..8 bytes, each in
    0x21..0x7e and not in FORBIDDEN. a..z become A..Z."""
    head = bytes(data[:NAME_MAX])
    nul = head.find(b'\0')
    raw = head if nul < 0 else head[:nul]
    if not 1 <= len(raw) <= NAME_MAX:
        return None
    for c in raw:
        if not 0x21 <= c <= 0x7e or c in FORBIDDEN:
            return None
    return raw.upper().decode('ascii')


def _open_read(path):
    """True when path opens for reading (a directory does not: open() raises on it)."""
    try:
        with open(path, 'rb'):
            return True
    except OSError:
        return False


def current_info(game_dir='.'):
    """(name, fromsys): the current league and 1 when SYSTEM gave it, 0 for the CLASSIC fallback."""
    try:
        with open(os.path.join(game_dir, SYSTEM_FILE), 'rb') as f:
            data = f.read(NAME_MAX)
    except OSError:
        return CLASSIC, 0
    name = parse_name(data)
    if name is None:
        return CLASSIC, 0
    if not _open_read(os.path.join(game_dir, 'TEAMS', name, name + '.MAJ')):
        return CLASSIC, 0
    return name, 1


def current(game_dir='.'):
    """The current league's name (C16.1): SYSTEM's name when valid and its MAJ opens, else CLASSIC."""
    return current_info(game_dir)[0]


def paths(name, sep='\\'):
    """The dynasty paths of league name (C16.1). sep is '\\' for the DOS tools, '/' for host builds."""
    s = sep
    if name == CLASSIC:
        snap = f'C:{s}DYNSNAP'
        seasons = f'C:{s}SEASONS'
    else:
        snap = f'C:{s}DYNLG{s}{name}{s}SNAP'
        seasons = f'C:{s}DYNLG{s}{name}'
    return {
        'dir': f'TEAMS{s}{name}',
        'hist': f'TEAMS{s}{name}{s}HISTORY.DAT',
        'snap': snap,
        'seasons': seasons,
        'ret': snap + s + 'RETIRED.DAT',
        'maj': f'TEAMS{s}{name}{s}{name}.MAJ',
    }
