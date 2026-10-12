"""index.html's storedZip (the Portrait Studio overlay, C14.4 boot) builds a zip that zipfile reads back byte for byte.
Runs the page's own crc32 / storedZip source under node."""
import os
import shutil
import subprocess
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = 'TONY2/ANMS/PORTRAIT.ANM'


def page_zip_source():
    with open(os.path.join(HERE, 'index.html')) as f:
        s = f.read()
    return s[s.index('let crcTable = null;'):s.index('async function boot(name) {')]


def test_boot_passes_the_overlay_as_a_zip():
    with open(os.path.join(HERE, 'index.html')) as f:
        s = f.read()
    assert "opts.initFs = [storedZip('TONY2/ANMS/PORTRAIT.ANM', " in s


def test_stored_zip_round_trips(tmp_path):
    node = shutil.which('node')
    assert node, 'node is needed to run the page script'
    script = tmp_path / 'z.mjs'
    script.write_text(page_zip_source() + """
import { writeFileSync } from 'node:fs';
for (const n of [0, 1, 1082702]) {
  const d = new Uint8Array(n);
  for (let i = 0; i < n; i++) d[i] = (i * 7919 + (i >> 8)) & 255;
  writeFileSync(process.argv[2] + '/z' + n + '.zip', storedZip('%s', d));
}
""" % ENTRY)
    subprocess.run([node, str(script), str(tmp_path)], check=True, timeout=60)
    for n in (0, 1, 1082702):
        with zipfile.ZipFile(tmp_path / ('z%d.zip' % n)) as z:
            assert z.testzip() is None
            [info] = z.infolist()
            assert (info.filename, info.compress_type, info.file_size) == (ENTRY, zipfile.ZIP_STORED, n)
            assert z.read(ENTRY) == bytes((i * 7919 + (i >> 8)) & 255 for i in range(n))
