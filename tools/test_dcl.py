"""Tests for the DCL implode encoder in dcl.py (round trip through explode)."""

import glob
import os
import random
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dcl import (  # noqa: E402
    _BASE,
    _DIST_CODES,
    _DISTLEN,
    _EXTRA,
    _LEN_CODES,
    _LENLEN,
    _St,
    _dist,
    _len,
    explode,
    implode,
)

STADIUMS = "/mnt/nvme/tlrb2/files/STADIUMS"
SCREENS = "/mnt/nvme/tlrb2/files/SCREENS"


def _pack_lsb(pairs):
    """Pack (value, nbits) pairs into bytes, LSB first, zero-padded."""
    acc = 0
    nacc = 0
    out = bytearray()
    for v, nb in pairs:
        acc |= v << nacc
        nacc += nb
        while nacc >= 8:
            out.append(acc & 255)
            acc >>= 8
            nacc -= 8
    if nacc:
        out.append(acc & 255)
    return bytes(out)


def _mix(seed, size):
    rnd = random.Random(seed)
    out = bytearray()
    while len(out) < size:
        if rnd.random() < 0.5:
            out += bytes([rnd.randrange(256)]) * rnd.randrange(1, 900)
        else:
            out += bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 400)))
    return bytes(out[:size])


def _roundtrip(x, dict_bits=6):
    s = implode(x, dict_bits)
    y, consumed = explode(s)
    assert y == x
    assert consumed == len(s)
    return s


# 1. Round trips

def test_roundtrip_empty():
    _roundtrip(b"")


def test_roundtrip_one_byte():
    _roundtrip(b"\x7f")


def test_roundtrip_600_zeros():
    _roundtrip(b"\x00" * 600)


@pytest.mark.parametrize("dict_bits", [4, 5, 6])
def test_roundtrip_random_20k(dict_bits):
    rnd = random.Random(1234 + dict_bits)
    x = bytes(rnd.randrange(256) for _ in range(20 * 1024))
    _roundtrip(x, dict_bits)


@pytest.mark.parametrize("dict_bits", [4, 5, 6])
def test_roundtrip_mix_300k(dict_bits):
    _roundtrip(_mix(99 + dict_bits, 300 * 1024), dict_bits)


@pytest.mark.parametrize("dict_bits", [4, 5, 6])
def test_roundtrip_small_text(dict_bits):
    _roundtrip(b"abcabcabcabcabxabcabcabc" * 40, dict_bits)


def test_bad_dict_bits_rejected():
    with pytest.raises(ValueError):
        implode(b"abc", 7)


# 2. explode consumes the whole stream

@pytest.mark.parametrize("x", [b"", b"q", b"\x00" * 600, b"hello hello hello world"])
def test_explode_consumes_whole_stream(x):
    s = implode(x)
    assert explode(s)[1] == len(s)


def test_explode_consumes_whole_stream_with_trailing_check():
    s = implode(_mix(7, 5000))
    assert explode(s)[1] == len(s)


# 3. Real data

def _sdm_files():
    if not os.path.isdir(STADIUMS):
        return []
    return sorted(glob.glob(os.path.join(STADIUMS, "*.SDM")))


_REAL = _sdm_files()


@pytest.mark.skipif(not _REAL, reason="real data missing: %s" % STADIUMS)
def test_real_data_roundtrip_and_ratio():
    ratios = []
    worst = None
    for path in _REAL:
        with open(path, "rb") as f:
            raw = f.read()
        x, consumed = explode(raw)
        t0 = time.time()
        s = implode(x)
        dt = time.time() - t0
        assert explode(s)[0] == x, path
        ratio = len(s) / consumed
        ratios.append(ratio)
        name = os.path.basename(path)
        print("%s stream=%d implode_out=%d ratio=%.4f implode_s=%.2f"
              % (name, consumed, len(s), ratio, dt))
        assert ratio <= 1.25, "%s ratio %.4f" % (name, ratio)
        if worst is None or dt > worst[1]:
            worst = (name, dt)
    print("ratio min=%.4f max=%.4f" % (min(ratios), max(ratios)))
    print("slowest implode: %s %.2fs" % worst)


# 4. Codec helper bit-level checks

@pytest.mark.parametrize("sym", range(16))
def test_len_codes_decode_via_stream(sym):
    v, nb = _LEN_CODES[sym]
    assert nb >= 1
    s = _St(_pack_lsb([(v, nb)]))
    assert s.decode(_len) == sym


def test_every_dist_symbol_decodes_via_stream():
    for sym in range(64):
        v, nb = _DIST_CODES[sym]
        s = _St(_pack_lsb([(v, nb)]))
        assert s.decode(_dist) == sym


def test_len_code_table_is_prefix_free_and_complete():
    codes = {}
    for sym in range(16):
        v, nb = _LEN_CODES[sym]
        codes[sym] = (v, nb)
    # Kraft sum over the 16 length symbols is exactly 1 for this table.
    kraft = sum(1.0 / (1 << nb) for _, nb in codes.values())
    assert abs(kraft - 1.0) < 1e-9
    expanded = []
    for b in _LENLEN:
        expanded += [b & 15] * ((b >> 4) + 1)
    assert sorted(nb for _, nb in codes.values()) == sorted(expanded)


def test_length_symbol_ranges_cover_2_to_519():
    for L in range(2, 520):
        hits = [s for s in range(16) if _BASE[s] <= L < _BASE[s] + (1 << _EXTRA[s])]
        assert len(hits) == 1, L
