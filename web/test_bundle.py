"""build_bundle: same inputs give a byte-identical bundle, so deploy.sh can skip an unchanged one by sha."""
import hashlib
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_bundle  # noqa: E402


def _tree(tmp_path):
    root = tmp_path / 'c'
    (root / 'TONY2').mkdir(parents=True)
    (root / 'TONY2' / 'TONY2.BAT').write_bytes(b'@echo off\r\n')
    (root / 'TONY2' / 'X.EXE').write_bytes(b'MZ' + bytes(64))
    (root / 'DYNSNAP').mkdir()
    iso = tmp_path / 'cd.iso'
    iso.write_bytes(bytes(2048))
    return root, iso


def test_same_inputs_same_bundle(tmp_path, monkeypatch):
    root, iso = _tree(tmp_path)
    a, b = tmp_path / 'a.jsdos', tmp_path / 'b.jsdos'
    build_bundle.build(str(root), str(iso), str(a))
    real = time.time
    monkeypatch.setattr(time, 'time', lambda: real() + 3600)   # an hour later: nothing we generate may change
    build_bundle.build(str(root), str(iso), str(b))
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()


def test_bundle_layout(tmp_path):
    root, iso = _tree(tmp_path)
    out = tmp_path / 'o.jsdos'
    assert build_bundle.build(str(root), str(iso), str(out)) == 2
    names = zipfile.ZipFile(out).namelist()
    assert {'.jsdos/', 'TONY2/', 'DYNSNAP/', '.jsdos/dosbox.conf', 'TONY2/TONY2.BAT', 'TONY2/X.EXE', 'CD.ISO'} <= set(names)
    assert b'call TONY2.BAT' in zipfile.ZipFile(out).read('.jsdos/dosbox.conf')
