"""Parity gate for rookie_fill.bin (M4 P2 fill + C4 rookie variety).

Builds rookie_fill.bin from rookie_fill.asm with nasm at import, then runs
each case under unicorn (16-bit x86) and compares the full team image, the
persisted rng word and AX against the Python reference
team_fill.fill_image + rookies.RookieGen.make on the same input and seed.

Blob ABI (rookie_fill.asm header): DS:SI = team image (295 B header + 80
records x 143 B), FS:BX = pointer to the rng word, AX = season year byte
(year - 1870). Far-call blob_base:0x10.

No game data: every fixture is synthesized.
"""

import os
import struct
import subprocess
import sys

from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_ERR_EXCEPTION, UcError
from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CS, UC_X86_REG_DS,
    UC_X86_REG_ES, UC_X86_REG_FS, UC_X86_REG_SP, UC_X86_REG_SS,
    UC_X86_REG_SI,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
_BLOB_DIR = os.path.join(_HERE, "blob")
for _p in (_TOOLS, _BLOB_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from m4 import team_fill  # noqa: E402
from m4.rollover import Rng  # noqa: E402
from m4.rookies import (  # noqa: E402
    RookieGen, STOCK_FACE_GROUP, default_faces, load_faces,
)

ASM = os.path.join(_BLOB_DIR, "rookie_fill.asm")
BIN = os.path.join(_BLOB_DIR, "rookie_fill.bin")
ENTRY_FILL = 0x10

RECORD = 143
HDR = 295
TEAM_BYTES = HDR + 80 * RECORD

# physical layout (one 1 MiB flat map, segments = physical >> 4)
PBLOB = 0x10000
PTeamA = 0x20000
PTeamB = 0x30000
PRNG = 0x40000
PSTACK = 0x70000
SEG_BLOB = PBLOB >> 4
SEG_STACK = PSTACK >> 4
SP_TOP = 0xFFC            # retf frame at SS:SP -> CS 0x7000 IP 0 (sentinel)


def _build_blob():
    """nasm the blob; better Week1 than a silent stale binary."""
    subprocess.run(
        ["nasm", "-f", "bin", "-o", BIN, ASM],
        check=True, cwd=_BLOB_DIR,
    )
    return open(BIN, "rb").read()


BLOB = _build_blob()


# ---------------------------------------------------------------------------
# Synthetic team images.
# ---------------------------------------------------------------------------

def _blank_image():
    return bytearray(TEAM_BYTES)


def _activate(img, slot, pos, age=28, year=50):
    base = HDR + slot * RECORD
    img[base] = 1                        # active (byte 0)
    img[base + 20] = age
    img[base + 21] = year                # year - 1870
    img[base + 31] = pos & 0x0F          # pos1
    # a small stat line so the season check has live bytes
    img[base + 23] = 150                 # games


def _vacate(img, slots):
    for s in slots:
        base = HDR + s * RECORD
        img[base] = 0
        img[base + 40 * RECORD] = 0      # season half too (post-rollover)


def _team(spec):
    """spec: {slot: pos} for actives; everything else vacant in both halves."""
    img = _blank_image()
    for slot, pos in spec.items():
        _activate(img, slot, pos)
    return img


def _all_active(spec_pos):
    return _team({i: spec_pos(i) for i in range(40)})


# ---------------------------------------------------------------------------
# Emulation.
# ---------------------------------------------------------------------------

def _run_blob(image, seed, year, image_phys, pre_draws=0, blob=None):
    """Run entry 0x10 on `image` (bytes) with the given rng seed. Returns
    (ax, image_after, rng_word). blob: alternate blob bytes (default BLOB)."""
    uc = Uc(UC_ARCH_X86, UC_MODE_16)
    uc.mem_map(0x00000, 0x100000)
    uc.mem_write(PBLOB, BLOB if blob is None else blob)
    uc.mem_write(image_phys, bytes(image))
    rng_word = seed & 0xFFFF
    if pre_draws:
        rng = Rng(seed)
        for _ in range(pre_draws):
            rng.draw()
        rng_word = rng.s
    uc.mem_write(PRNG, struct.pack("<H", rng_word))
    uc.mem_write(PSTACK + SP_TOP, struct.pack("<HH", 0, SEG_STACK))
    uc.mem_write(PSTACK, b"\xF4")        # sentinel halt at the retf target

    uc.reg_write(UC_X86_REG_CS, SEG_BLOB)
    uc.reg_write(UC_X86_REG_DS, image_phys >> 4)
    uc.reg_write(UC_X86_REG_ES, image_phys >> 4)
    uc.reg_write(UC_X86_REG_FS, PRNG >> 4)
    uc.reg_write(UC_X86_REG_SS, SEG_STACK)
    uc.reg_write(UC_X86_REG_SI, 0)
    uc.reg_write(UC_X86_REG_BX, 0)
    uc.reg_write(UC_X86_REG_AX, year & 0xFF)
    uc.reg_write(UC_X86_REG_SP, SP_TOP)
    try:
        uc.emu_start(PBLOB + ENTRY_FILL, 0)
    except UcError as e:
        if e.errno != UC_ERR_EXCEPTION:
            raise
    ax = uc.reg_read(UC_X86_REG_AX)
    after = bytes(uc.mem_read(image_phys, TEAM_BYTES))
    rng_word = struct.unpack("<H", uc.mem_read(PRNG, 2))[0]
    return ax, after, rng_word


def _reference(image, seed, year, pre_draws=0, faces=None):
    """The Python reference fill on a copy of `image`. Returns
    (nvac, image_after, rng_end_word). faces: (n, grp) or None (default)."""
    ref = bytearray(image)
    rng = Rng(seed)
    for _ in range(pre_draws):
        rng.draw()
    gen = RookieGen(rng, faces=faces)
    nvac, vac, pos = team_fill.fill_image(ref, year & 0xFF, rng, gen)
    return nvac, ref, rng.s


def _assert_parity(image, seed, year, image_phys=PTeamA, pre_draws=0,
                   blob=None, faces=None):
    ax, got, rng_word = _run_blob(image, seed, year, image_phys, pre_draws, blob)
    nvac, ref, ref_rng = _reference(image, seed, year, pre_draws, faces)
    diffs = [i for i in range(TEAM_BYTES) if got[i] != ref[i]]
    assert ax == nvac, "AX %d != nvac %d" % (ax, nvac)
    assert rng_word == ref_rng, "rng word %04x != %04x" % (rng_word, ref_rng)
    assert not diffs, "%d byte diffs, first at %d (record %d byte %d)" % (
        len(diffs), diffs[0], (diffs[0] - HDR) // RECORD,
        (diffs[0] - HDR) % RECORD,
    )


# ---------------------------------------------------------------------------
# Case groups. Never skipped: the blob is built at import, no skips.
# ---------------------------------------------------------------------------

def test_zero_vacancies_noop():
    image = _all_active(lambda i: i % 10)
    _assert_parity(image, 11, 50)


def test_one_vacancy():
    image = _all_active(lambda i: [0, 0, 0, 1, 1, 2, 2, 3, 4, 5, 6, 6][i % 12])
    _vacate(image, [5])
    _assert_parity(image, 9, 50)


def test_many_mixed_vacancies():
    vac = [3, 7, 11, 15, 19, 23, 27, 31, 35, 2, 5, 9]
    image = _all_active(lambda i: i % 10)
    _vacate(image, vac)
    _assert_parity(image, 12, 50)


def test_all_pitcher_vacancies():
    image = _all_active(lambda i: 0 if i < 10 else 1 + (i % 8))
    _vacate(image, list(range(10)))
    _assert_parity(image, 13, 50)


def test_all_batter_vacancies():
    image = _all_active(lambda i: 1 + (i % 8))
    _vacate(image, list(range(12)))
    _assert_parity(image, 14, 50)


def test_empty_roster_fills_all_40():
    image = _team({})                       # entirely empty team: 40 vacancies
    _assert_parity(image, 15, 50)


def test_full_roster_no_op_on_40():
    """All 40 roster + 40 season records active: the blob and reference both
    return 0 vacancies and leave the image byte-identical."""
    image = _all_active(lambda i: i % 10)
    for i in range(40):                     # season half active too
        base = HDR + (40 + i) * RECORD
        image[base] = 1                     # season byte 0
        image[base + 20] = 28
        image[base + 21] = 50
    ax, got, rng_word = _run_blob(image, 15, 50, PTeamB)
    nvac, ref, ref_rng = _reference(image, 15, 50)
    assert ax == 0 and nvac == 0
    assert got == bytes(image)
    assert ref == bytearray(image)
    assert rng_word == ref_rng


def test_rng_continues_across_teams():
    """Two far-calls in sequence sharing one rng word: team B's fill starts
    from team A's ending rng state."""
    img_a = _all_active(lambda i: 0)        # 3 pitcher vacancies
    _vacate(img_a, [0, 1, 2])
    img_b = _all_active(lambda i: 1 + (i % 8))
    _vacate(img_b, [5, 9])

    # reference: one shared Rng across both fills
    rng = Rng(21)
    ref_a = bytearray(img_a)
    ref_b = bytearray(img_b)
    gen = RookieGen(rng)
    n_a, _, _ = team_fill.fill_image(ref_a, 50, rng, gen)
    n_b, _, _ = team_fill.fill_image(ref_b, 50, rng, gen)
    assert n_a == 3 and n_b == 2

    uc = Uc(UC_ARCH_X86, UC_MODE_16)
    uc.mem_map(0x00000, 0x100000)
    uc.mem_write(PBLOB, BLOB)
    uc.mem_write(PTeamA, bytes(img_a))
    uc.mem_write(PTeamB, bytes(img_b))
    uc.mem_write(PRNG, struct.pack("<H", 21))
    uc.mem_write(PSTACK + SP_TOP, struct.pack("<HH", 0, SEG_STACK))
    uc.mem_write(PSTACK, b"\xF4")
    for phys in (PTeamA, PTeamB):
        uc.reg_write(UC_X86_REG_CS, SEG_BLOB)
        uc.reg_write(UC_X86_REG_DS, phys >> 4)
        uc.reg_write(UC_X86_REG_ES, phys >> 4)
        uc.reg_write(UC_X86_REG_FS, PRNG >> 4)
        uc.reg_write(UC_X86_REG_SS, SEG_STACK)
        uc.reg_write(UC_X86_REG_SI, 0)
        uc.reg_write(UC_X86_REG_BX, 0)
        uc.reg_write(UC_X86_REG_AX, 50)
        uc.reg_write(UC_X86_REG_SP, SP_TOP)
        uc.emu_start(PBLOB + ENTRY_FILL, 0)
    got_a = bytes(uc.mem_read(PTeamA, TEAM_BYTES))
    got_b = bytes(uc.mem_read(PTeamB, TEAM_BYTES))
    assert got_a == ref_a
    assert got_b == ref_b
    rng_word = struct.unpack("<H", uc.mem_read(PRNG, 2))[0]
    assert rng_word == rng.s


def test_random_images_seeded_matrix():
    """50 random images x 2 seeds: the catch-all across vacancy mixes."""
    import random
    rnd = random.Random(2026)
    case = 0
    for _ in range(50):
        for seed in (7, 4000):
            spec = {}
            for i in range(40):
                if rnd.random() < 0.55:
                    spec[i] = rnd.choice([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
            image = _team(spec)
            _assert_parity(image, seed, 50, pre_draws=rnd.randrange(0, 17))
            case += 1
    assert case == 100


def test_year_byte_written_verbatim():
    """The season year byte lands at record offset 21 exactly as passed
    (it is already year - 1870)."""
    image = _all_active(lambda i: i % 10)
    _vacate(image, [4])
    year = 1994 - 1870                       # 124
    _assert_parity(image, 5, year)
    nvac, ref, _ = _reference(image, 5, year)
    assert nvac == 1
    base = HDR + 4 * RECORD
    assert ref[base + 21] == year


def test_image_at_nonzero_offset_like_dynasty_exe():
    """DYNASTY.EXE passes DS = ES = its own segment and SI = team_buf (not 0),
    with code and data below the image. Every write must land relative to
    DS:SI, never at absolute HDR offsets, and nothing outside the image may
    change. ES is set to an unrelated segment to prove the blob does not
    rely on the caller's ES."""
    import random
    rnd = random.Random(77)
    seg = 0x5000
    for si_off in (0x0333, 0x1000 + 0x0255):
        spec = {i: rnd.choice(range(10)) for i in range(40) if rnd.random() < 0.5}
        image = _team(spec)
        uc = Uc(UC_ARCH_X86, UC_MODE_16)
        uc.mem_map(0x00000, 0x100000)
        uc.mem_write(PBLOB, BLOB)
        guard = bytes((i * 13 + 5) & 0xFF for i in range(0x10000))
        uc.mem_write(seg << 4, guard)
        uc.mem_write((seg << 4) + si_off, bytes(image))
        uc.mem_write(PRNG, struct.pack("<H", 4321))
        uc.mem_write(PSTACK + SP_TOP, struct.pack("<HH", 0, SEG_STACK))
        uc.mem_write(PSTACK, b"\xF4")
        uc.reg_write(UC_X86_REG_CS, SEG_BLOB)
        uc.reg_write(UC_X86_REG_DS, seg)
        uc.reg_write(UC_X86_REG_ES, 0x6000)
        uc.reg_write(UC_X86_REG_FS, PRNG >> 4)
        uc.reg_write(UC_X86_REG_SS, SEG_STACK)
        uc.reg_write(UC_X86_REG_SI, si_off)
        uc.reg_write(UC_X86_REG_BX, 0)
        uc.reg_write(UC_X86_REG_AX, 50)
        uc.reg_write(UC_X86_REG_SP, SP_TOP)
        try:
            uc.emu_start(PBLOB + ENTRY_FILL, 0, 0, 50_000_000)
        except UcError as e:
            if e.errno != UC_ERR_EXCEPTION:
                raise
        mem = bytes(uc.mem_read(seg << 4, 0x10000))
        got = mem[si_off:si_off + TEAM_BYTES]
        nvac, ref, ref_rng = _reference(image, 4321, 50)
        assert nvac > 0
        assert uc.reg_read(UC_X86_REG_AX) == nvac
        assert uc.reg_read(UC_X86_REG_SI) == si_off
        assert uc.reg_read(UC_X86_REG_ES) == 0x6000
        assert got == bytes(ref)
        assert mem[:si_off] == guard[:si_off]
        assert mem[si_off + TEAM_BYTES:] == guard[si_off + TEAM_BYTES:]
        assert bytes(uc.mem_read(0x60000, 0x10000)) == bytes(0x10000)
        assert struct.unpack("<H", uc.mem_read(PRNG, 2))[0] == ref_rng


# ---------------------------------------------------------------------------
# Face table (ANMS rule): patched header, default flags, load_faces.
# ---------------------------------------------------------------------------

def _patched_blob(n, table):
    """BLOB with header word 2 = n and the first n table bytes = table."""
    b = bytearray(BLOB)
    struct.pack_into("<H", b, 2, n)
    off = struct.unpack_from("<H", BLOB, 4)[0]
    b[off:off + n] = bytes(table)
    return bytes(b)


def _new_rookies(before, after):
    """(face, flag) of every roster slot filled between before and after."""
    out = []
    for i in range(40):
        base = HDR + i * RECORD
        if before[base] == 0 and after[base] != 0:
            face = after[base + 27] | (after[base + 28] << 8)
            out.append((face, after[base + 29] & 1))
    return out


def test_default_header_is_stock():
    assert struct.unpack_from("<H", BLOB, 2)[0] == 30
    off = struct.unpack_from("<H", BLOB, 4)[0]
    assert bytes(BLOB[off:off + 30]) == bytes(
        1 if i in STOCK_FACE_GROUP else 0 for i in range(30))
    assert bytes(BLOB[off + 30:off + 981]) == bytes(951)


def test_default_header_stock_flag_rule():
    """Default header == Python default. The stock flag rule (faces 3, 4, 16,
    18, 20, 21, 22, 25, 27 carry bit0) is checked on the rookies produced."""
    seen_set_flag1 = seen_mid_flag0 = 0
    for seed in (15, 16, 17, 18):
        image = _team({})                  # 40 vacancies: 40 rookies per case
        ax, got, _ = _run_blob(image, seed, 50, PTeamA)
        nvac, ref, _ = _reference(image, seed, 50)
        assert got == bytes(ref) and ax == nvac == 40
        for face, flag in _new_rookies(image, got):
            assert 0 <= face < 30
            assert flag == (1 if face in STOCK_FACE_GROUP else 0), face
            if face in STOCK_FACE_GROUP:
                seen_set_flag1 += flag
            elif 15 <= face <= 29:
                seen_mid_flag0 += 1 - flag
    assert seen_set_flag1 > 0
    assert seen_mid_flag0 > 0


def test_patched_face_table_matches_python():
    """Header n = 40 with flags at 30..39 mixed: blob == Python faces=(40, table)."""
    table = list(default_faces()[1]) + [1, 0, 1, 1, 0, 0, 1, 0, 1, 1]
    assert len(table) == 40
    blob = _patched_blob(40, table)
    faces = (40, bytes(table))
    import random
    rnd = random.Random(40)
    hi_faces = set()
    for seed in (7, 4000, 9, 77):
        spec = {i: rnd.choice(range(10)) for i in range(40) if rnd.random() < 0.5}
        image = _team(spec)
        _vacate(image, [i for i in range(40) if i not in spec])
        _assert_parity(image, seed, 50, blob=blob, faces=faces)
        nvac, ref, _ = _reference(image, seed, 50, faces=faces)
        for face, flag in _new_rookies(image, ref):
            assert flag == table[face]
            if face >= 30:
                hi_faces.add((face, flag))
    assert any(f == 1 for _, f in hi_faces)
    assert any(f == 0 for _, f in hi_faces)
    # empty roster: 40 rookies through the patched blob
    image = _team({})
    _assert_parity(image, 4321, 50, blob=blob, faces=faces)


def test_patched_face_table_large_n_u16_portrait():
    """n = 981 (the BB ceiling): faces above 255 need both bytes of u16@27."""
    import random
    rnd = random.Random(981)
    table = list(default_faces()[1]) + [rnd.randrange(2) for _ in range(951)]
    blob = _patched_blob(981, table)
    faces = (981, bytes(table))
    image = _team({})
    _assert_parity(image, 2024, 50, blob=blob, faces=faces)
    _, ref, _ = _reference(image, 2024, 50, faces=faces)
    assert any(face > 255 for face, _ in _new_rookies(image, ref))


def test_patched_face_table_small_n():
    """n = 30 through the patched path equals the default table (a header
    rewrite with the stock contents is a no-op)."""
    blob = _patched_blob(30, default_faces()[1])
    image = _team({i: i % 10 for i in range(0, 40, 2)})
    _assert_parity(image, 88, 50, blob=blob, faces=default_faces())


def _anms(tmp_path, portrait=None, grp=None):
    d = tmp_path / "ANMS"
    d.mkdir(parents=True, exist_ok=True)
    if portrait is not None:
        (d / "PORTRAIT.ANM").write_bytes(portrait)
    if grp is not None:
        (d / "FACEGRP.DAT").write_bytes(grp)
    return str(d)


def _u16(n):
    return bytes([n & 0xFF, (n >> 8) & 0xFF])


def test_load_faces_none_is_default():
    assert load_faces(None) == default_faces()
    n, grp = default_faces()
    assert n == 30 and len(grp) == 30
    assert {i for i in range(30) if grp[i]} == set(STOCK_FACE_GROUP)


def test_load_faces_missing_files(tmp_path):
    assert load_faces(_anms(tmp_path / "a")) == default_faces()
    assert load_faces(_anms(tmp_path / "b", portrait=_u16(45))) == default_faces()
    assert load_faces(_anms(tmp_path / "c", grp=bytes(50))) == default_faces()
    assert load_faces(str(tmp_path / "nowhere")) == default_faces()


def test_load_faces_length_bounds(tmp_path):
    p = _u16(45)
    assert load_faces(_anms(tmp_path / "l29", portrait=p, grp=bytes(29))) == default_faces()
    assert load_faces(_anms(tmp_path / "l982", portrait=p, grp=bytes(982))) == default_faces()
    n, grp = load_faces(_anms(tmp_path / "l981", portrait=p, grp=bytes(981)))
    assert n == 45 and len(grp) == 45
    n, grp = load_faces(_anms(tmp_path / "l30", portrait=_u16(45), grp=bytes(30)))
    assert n == 30 and len(grp) == 30


def test_load_faces_min_rules(tmp_path):
    grp = bytes(range(60))                      # low bits alternate by value
    # c < L: n = c
    n, got = load_faces(_anms(tmp_path / "cl", portrait=_u16(45), grp=grp[:50]))
    assert n == 45 and got == bytes(b & 1 for b in grp[:45])
    # L < c: n = L
    n, got = load_faces(_anms(tmp_path / "lc", portrait=_u16(55), grp=grp[:50]))
    assert n == 50 and got == bytes(b & 1 for b in grp[:50])
    # min < 30: default
    assert load_faces(_anms(tmp_path / "c29", portrait=_u16(29), grp=grp[:50])) == default_faces()
    assert load_faces(_anms(tmp_path / "c0", portrait=_u16(0), grp=grp[:50])) == default_faces()
    # short PORTRAIT.ANM (fewer than 2 bytes): default
    assert load_faces(_anms(tmp_path / "p1", portrait=b"\x2d", grp=grp[:50])) == default_faces()


def test_load_faces_masks_to_bit0(tmp_path):
    grp = bytes([2, 3, 0xFF, 0x80, 1, 0, 0x7E] + [0] * 23)
    n, got = load_faces(_anms(tmp_path / "m", portrait=_u16(30), grp=grp))
    assert n == 30
    assert got == bytes([0, 1, 1, 0, 1, 0, 0] + [0] * 23)
