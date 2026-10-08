import os
import random
import struct

import pytest
from PIL import Image

import replay as R

FILES = '/mnt/nvme/tlrb2/files'
STOCK = FILES + '/ANMS'
REPLAY_NAMES = [
    '1BOUT', '2BOUT', '2BSAFE', '2BSTEAL', '3BDIVE', '3BDIVE2', '3BSAFE', 'DBLPLAY', 'DBLPLAY2',
    'DIVE', 'DIVE2', 'DIVE2L', 'HOMEOUT', 'HOMERUN', 'HOMESAFE', 'JUMP', 'JUMP2', 'LEAP', 'MOON',
]

skip_stock = pytest.mark.skipif(not os.path.exists(STOCK + '/HOMERUN.ANM'), reason='stock ANMS missing')


def _stock(name):
    return os.path.join(STOCK, name + '.ANM')


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


def _roundtrip_ok(data):
    info, frames = R.decode(data)
    out = R.encode(frames, info['palette'], info['width'], info['height'], info['flags'])
    info2, frames2 = R.decode(out)
    assert frames2 == frames
    for k in ('palette', 'flags', 'width', 'height'):
        assert info2[k] == info[k]


def _ops(stream):
    """Walk a frame stream; return a list of (kind, arg)."""
    ops = []
    i = 0
    while i < len(stream):
        op = stream[i]
        i += 1
        if op == 0x80:
            w = struct.unpack_from('<H', stream, i)[0]
            i += 2
            if w & 0x8000 and w & 0x4000:
                ops.append(('run', w ^ 0xc000))
                i += 1
            elif w & 0x8000:
                ops.append(('dump', w ^ 0x8000))
                i += w ^ 0x8000
            elif w == 0:
                ops.append(('end', 0))
                break
            else:
                ops.append(('skip', w))
        elif op == 0:
            ops.append(('run', stream[i]))
            i += 2
        elif op & 0x80:
            ops.append(('skip', op & 0x7f))
        else:
            ops.append(('dump', op))
            i += op
    return ops


def _rand_pal(seed):
    rng = random.Random(seed)
    return bytes(rng.randrange(64) for _ in range(768))


def _rand_frames(seed, w, h, n):
    rng = random.Random(seed)
    cur = bytearray(rng.randrange(256) for _ in range(w * h))
    frames = []
    for _ in range(n):
        m = rng.random()
        if m < 0.2:
            pass
        elif m < 0.6:
            for _ in range(rng.randrange(1, 40)):
                p = rng.randrange(w * h)
                L = rng.randrange(1, 300)
                k = min(L, w * h - p)
                cur[p:p + k] = bytes([rng.randrange(256)]) * k
        else:
            for _ in range(rng.randrange(1, 60)):
                cur[rng.randrange(w * h)] = rng.randrange(256)
        frames.append(bytes(cur))
    return frames


@skip_stock
def test_stock_parse_homerun():
    p = R.parse(_read(_stock('HOMERUN')))
    assert len(p['frames']) == 18
    assert (p['width'], p['height']) == (232, 138)
    assert p['flags'] == 0xff01
    assert p['sizes'][0] == 34320


@pytest.mark.skipif(not os.path.exists(FILES + '/INTRO.ANM'), reason='INTRO.ANM missing')
def test_stock_parse_intro():
    p = R.parse(_read(FILES + '/INTRO.ANM'))
    assert len(p['frames']) == 150
    assert (p['width'], p['height']) == (320, 200)


@pytest.mark.skipif(not os.path.exists(_stock('1BOUT')), reason='1BOUT missing')
def test_stock_parse_1bout():
    data = _read(_stock('1BOUT'))
    assert len(data) == 185838
    assert len(R.parse(data)['frames']) == 20


@pytest.mark.skipif(not os.path.exists(_stock('FLAG')), reason='FLAG missing')
def test_flag_is_not_replay():
    with pytest.raises(ValueError):
        R.parse(_read(_stock('FLAG')))


@skip_stock
@pytest.mark.parametrize('name', REPLAY_NAMES)
def test_stock_roundtrip(name):
    _roundtrip_ok(_read(_stock(name)))


@pytest.mark.skipif(not os.path.exists(FILES + '/INTRO.ANM'), reason='INTRO.ANM missing')
def test_stock_roundtrip_intro():
    _roundtrip_ok(_read(FILES + '/INTRO.ANM'))


@pytest.mark.skipif(not os.path.exists(FILES + '/BOLT13.ANM'), reason='BOLT13.ANM missing')
def test_stock_roundtrip_bolt13():
    _roundtrip_ok(_read(FILES + '/BOLT13.ANM'))


def test_decode_frame_clamps_run_and_dump():
    buf = bytearray(10)
    stream = b'\x00\x05\x07' + b'\x80' + struct.pack('<H', 0xc014) + b'\x09' + b'\x80\x00\x00'
    R.decode_frame(stream, buf, 5, 2)
    assert bytes(buf) == bytes([7] * 5 + [9] * 5)

    buf = bytearray(10)
    stream = b'\x86' + b'\x80' + struct.pack('<H', 0x8008) + bytes(range(1, 9)) + b'\x80\x00\x00'
    R.decode_frame(stream, buf, 5, 2)
    assert bytes(buf) == bytes([0] * 6 + [1, 2, 3, 4])


def test_random_roundtrip():
    frames = _rand_frames(2, 97, 61, 12)
    pal = _rand_pal(3)
    data = R.encode(frames, pal, 97, 61)
    info, out = R.decode(data)
    assert out == frames
    assert info['palette'] == pal
    assert (info['width'], info['height'], info['flags']) == (97, 61, 1)


def test_encode_frame_against_prev():
    frames = _rand_frames(4, 64, 40, 8)
    w, h = 64, 40
    prev = None
    for f in frames:
        s = R.encode_frame(f, prev)
        buf = bytearray(bytes(prev) if prev is not None else bytes(w * h))
        R.decode_frame(s, buf, w, h)
        assert bytes(buf) == f
        prev = f


def test_long_runs_over_0x3fff():
    w, h = 320, 200
    f0 = bytes(w * h)
    rng = random.Random(7)
    f1 = bytes([7]) * 50000 + bytes(rng.randrange(256) for _ in range(w * h - 50000))
    s1 = R.encode_frame(f1, f0)
    assert b'\x80\xff\xff' in s1
    _roundtrip_ok(R.encode([f0, f1], _rand_pal(1), w, h))


def test_identical_frames():
    rng = random.Random(9)
    f = bytes(rng.randrange(256) for _ in range(232 * 138))
    assert R.encode_frame(f, f) == b'\x80\x00\x00\x00'
    _roundtrip_ok(R.encode([f, f, f], _rand_pal(2), 232, 138))


def test_long_skips_over_0x7fff():
    w, h = 320, 200
    rng = random.Random(11)
    f0 = bytes(rng.randrange(256) for _ in range(w * h))
    f1 = bytearray(f0)
    f1[0] ^= 1
    f1[w * h - 1] ^= 1
    f1 = bytes(f1)
    s = R.encode_frame(f1, f0)
    assert b'\x80\xff\x7f' in s
    _roundtrip_ok(R.encode([f0, f1], _rand_pal(5), w, h))


def test_sizes_multiple_of_4_and_first_frame_no_skip():
    frames = _rand_frames(5, 320, 200, 6)
    data = R.encode(frames, _rand_pal(6), 320, 200)
    p = R.parse(data)
    assert all(s % 4 == 0 for s in p['sizes'])
    kinds = [k for k, _ in _ops(p['frames'][0])]
    assert 'skip' not in kinds
    assert kinds[-1] == 'end'


def test_encode_validation():
    frames = _rand_frames(8, 8, 4, 2)
    pal = _rand_pal(8)
    with pytest.raises(ValueError):
        R.encode(frames, bytes(767), 8, 4)
    bad = bytearray(pal)
    bad[5] = 64
    with pytest.raises(ValueError):
        R.encode(frames, bytes(bad), 8, 4)
    with pytest.raises(ValueError):
        R.encode([], pal, 8, 4)
    with pytest.raises(ValueError):
        R.encode([b'\x00' * 31], pal, 8, 4)
    rng = random.Random(12)
    big = bytes(rng.randrange(256) for _ in range(400 * 200))
    with pytest.raises(ValueError):
        R.encode([big], pal, 400, 200)
    with pytest.raises(ValueError):
        R.encode([b'\x00'] * 0x10000, pal, 1, 1)


def test_parse_validation():
    with pytest.raises(ValueError):
        R.parse(b'\x00' * 100)
    with pytest.raises(ValueError):
        R.parse(bytes(0x30e))
    data = R.encode(_rand_frames(10, 8, 4, 2), _rand_pal(10), 8, 4)
    with pytest.raises(ValueError):
        R.parse(data + b'\x00')
    with pytest.raises(ValueError):
        R.parse(data[:-1])


def test_pil_palette():
    assert R.pil_palette([0, 63, 32]) == [0, 255, 129]


def test_out_guard():
    for g in R.GUARD:
        with pytest.raises(SystemExit):
            R._out(g + 'x/y')


def test_cli_bad_args():
    with pytest.raises(SystemExit):
        R.main([])
    with pytest.raises(SystemExit):
        R.main(['bogus'])
    with pytest.raises(SystemExit):
        R.main(['roundtrip'])


def _write_syn(tmp_path, frames, pal, w, h, flags=1):
    p = tmp_path / 'SYN.ANM'
    p.write_bytes(R.encode(frames, pal, w, h, flags))
    return str(p)


def test_cli_info(tmp_path, capsys):
    frames = _rand_frames(13, 16, 8, 3)
    p = _write_syn(tmp_path, frames, _rand_pal(13), 16, 8, 0xff01)
    R.main(['info', p])
    size = os.path.getsize(p)
    assert capsys.readouterr().out == 'SYN.ANM: 3 frames 16x8 flags 0xFF01 bytes %d\n' % size


def test_cli_frames(tmp_path):
    frames = _rand_frames(14, 16, 8, 3)
    p = _write_syn(tmp_path, frames, _rand_pal(14), 16, 8)
    out = tmp_path / 'out'
    R.main(['frames', p, str(out)])
    for i, f in enumerate(frames):
        with Image.open(out / ('%02d.png' % i)) as im:
            assert im.mode == 'P'
            assert im.tobytes() == f


def test_cli_gif(tmp_path):
    frames = _rand_frames(15, 16, 8, 3)
    p = _write_syn(tmp_path, frames, _rand_pal(15), 16, 8)
    out = tmp_path / 'a.gif'
    R.main(['gif', p, str(out), '50'])
    with Image.open(out) as im:
        assert im.n_frames == 3


def test_cli_build_and_roundtrip(tmp_path, capsys):
    w, h = 16, 8
    pal6 = _rand_pal(16)
    frames = _rand_frames(16, w, h, 3)
    pngs = []
    for i, f in enumerate(frames):
        im = Image.frombytes('P', (w, h), f)
        im.putpalette(R.pil_palette(pal6))
        p = tmp_path / ('in%d.png' % i)
        im.save(p)
        pngs.append(str(p))
    out = tmp_path / 'built.ANM'
    R.main(['build', str(out)] + pngs + ['--flags', '0xff01'])
    info, got = R.decode(out.read_bytes())
    assert got == frames
    assert info['palette'] == pal6
    assert info['flags'] == 0xff01

    R.main(['roundtrip', str(out)])
    assert capsys.readouterr().out == 'built.ANM ok %d %d\n' % (out.stat().st_size, out.stat().st_size)
