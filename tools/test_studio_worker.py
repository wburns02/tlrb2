"""Tests for tools/studio_worker.py and faces.to_frame / preview_png / build. No GPU, no network: a fake ComfyUI and a
fake site run on localhost. The worker tests stub faces.stock_indices, so PORTRAIT.ANM is not needed for them."""
import base64
import http.server
import io
import json
import os
import re
import sys
import threading
import urllib.parse

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import faces  # noqa: E402
import studio_worker as sw  # noqa: E402

TOKEN = 'tok-SECRET-123'
PASSWORD = 'pw-SECRET-456'
JOB_ID = '0123456789abcdef'
AUTH = 'Basic ' + base64.b64encode(('wkr:%s' % PASSWORD).encode()).decode()
HAVE_STOCK = os.path.exists(faces.STOCK) and os.path.exists(os.path.join(faces.SRC, 'DEFAULT.PAL'))


def _face(shift=0):
    """832 x 960 synthetic render: red cap over the top, face, grey jersey."""
    im = Image.new('RGB', (832, 960), (70, 96, 60))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 831, 360], fill=(214, 24, 30))
    d.ellipse([262 + shift, 330, 570 + shift, 700], fill=(226, 176, 136))
    d.rectangle([140, 700, 692, 959], fill=(190, 190, 196))
    return im


def _png(im):
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


def _reply(h, code, body=b'', ctype='application/json'):
    h.send_response(code)
    h.send_header('Content-Type', ctype)
    h.send_header('Content-Length', str(len(body)))
    h.end_headers()
    h.wfile.write(body)


class _Comfy(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        rec = self.server.rec
        rec['auth'].append(self.headers.get('Authorization'))
        u = urllib.parse.urlsplit(self.path)
        if u.path.startswith('/history/'):
            pid = u.path.rsplit('/', 1)[1]
            _reply(self, 200, json.dumps({pid: rec['history'][pid]}).encode())
        elif u.path == '/view':
            _reply(self, 200, rec['files'][urllib.parse.parse_qs(u.query)['filename'][0]], 'image/png')
        else:
            _reply(self, 404)

    def do_POST(self):
        rec = self.server.rec
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        rec['auth'].append(self.headers.get('Authorization'))
        if self.path == '/prompt':
            rec['graphs'].append(json.loads(body)['prompt'])
            pid = 'p%d' % len(rec['graphs'])
            name = pid + '.png'
            rec['files'][name] = _png(_face(len(rec['graphs'])))
            if rec['fail']:
                rec['history'][pid] = {'outputs': {}, 'status': {'status_str': 'error', 'completed': True}}
            else:
                rec['history'][pid] = {'outputs': {'7': {'images': [{'filename': name, 'subfolder': '',
                                                                     'type': 'temp'}]}},
                                       'status': {'status_str': 'success', 'completed': True}}
            _reply(self, 200, json.dumps({'prompt_id': pid}).encode())
        elif self.path == '/upload/image':
            rec['uploads'].append(body)
            name = re.search(rb'filename="([^"]+)"', body).group(1).decode()
            _reply(self, 200, json.dumps({'name': name, 'subfolder': '', 'type': 'input'}).encode())
        elif self.path == '/free':
            rec['free'] += 1
            _reply(self, 200, b'{}')
        else:
            _reply(self, 404)


class _Site(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        rec = self.server.rec
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        rec['log'].append({'path': self.path, 'auth': self.headers.get('Authorization'),
                           'token': self.headers.get('X-Studio-Token'), 'body': body})
        if self.path == '/studio/worker/claim':
            if rec['queue']:
                _reply(self, 200, json.dumps(rec['queue'].pop(0)).encode())
            else:
                _reply(self, 204)
        elif self.path.startswith('/studio/worker/deliver/'):
            _reply(self, 204)
        else:
            _reply(self, 404)


def _start(handler, rec):
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    srv.rec = rec
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def rig(tmp_path, monkeypatch):
    comfy = _start(_Comfy, {'graphs': [], 'uploads': [], 'files': {}, 'history': {}, 'free': 0, 'auth': [],
                            'fail': False})
    site = _start(_Site, {'queue': [], 'log': []})
    site_url = 'http://127.0.0.1:%d' % site.server_address[1]
    login = tmp_path / 'web_login'
    login.write_text('url=%s/\nuser=wkr\npassword=%s\n' % (site_url, PASSWORD))
    tok = tmp_path / 'token'
    tok.write_text(TOKEN + '\nnot the token\n')
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('TLRB2_WEB_LOGIN', str(login))
    monkeypatch.setenv('TLRB2_STUDIO_TOKEN_FILE', str(tok))
    monkeypatch.setenv('TLRB2_COMFY', 'http://127.0.0.1:%d' % comfy.server_address[1])
    monkeypatch.delenv('TLRB2_STUDIO_URL', raising=False)
    monkeypatch.setattr(faces, 'owner_busy', lambda *a, **k: False)
    monkeypatch.setattr(faces, 'stock_indices', lambda: [i for i in range(256) if i not in faces.SKIP])
    monkeypatch.setattr(sw, 'POLL_S', 0)
    yield {'cfg': sw.load_cfg(), 'comfy': comfy.rec, 'site': site.rec}
    for srv in (comfy, site):
        srv.shutdown()
        srv.server_close()


def _job(prompt='', image=None):
    job = {'id': JOB_ID, 'prompt': prompt, 'image': None}
    if image is not None:
        job['image'] = base64.b64encode(image).decode()
    return job


def _delivered(rig):
    calls = [c for c in rig['site']['log'] if c['path'].startswith('/studio/worker/deliver/')]
    assert [c['path'] for c in calls] == ['/studio/worker/deliver/' + JOB_ID]
    return json.loads(calls[0]['body'])


def test_load_cfg_reads_studio_env(tmp_path, monkeypatch):
    cfg_dir = tmp_path / '.config' / 'tlrb2'
    cfg_dir.mkdir(parents=True)
    tok = tmp_path / 'token'
    tok.write_text(TOKEN + '\n')
    (cfg_dir / 'studio.env').write_text('# worker\nTLRB2_STUDIO_TOKEN_FILE=%s\nTLRB2_STUDIO_URL=https://site.example/\n'
                                        % tok)
    (cfg_dir / 'web_login').write_text('url=https://other.example\nuser=wkr\npassword=%s\n' % PASSWORD)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('TLRB2_WEB_LOGIN', raising=False)
    monkeypatch.delenv('TLRB2_STUDIO_URL', raising=False)
    monkeypatch.delenv('TLRB2_STUDIO_TOKEN_FILE', raising=False)
    cfg = sw.load_cfg()
    assert cfg['url'] == 'https://site.example'
    assert cfg['token'] == TOKEN
    assert cfg['auth'] == AUTH


def test_txt2img_delivers_four_variants(rig):
    rig['site']['queue'].append(_job('a red-haired catcher'))
    assert sw.run_once(rig['cfg']) == 'done'
    variants = _delivered(rig)['variants']
    assert len(variants) == 4
    for k, v in enumerate(variants):
        frame = base64.b64decode(v['frame'])
        assert len(frame) == 2688
        assert Image.open(io.BytesIO(base64.b64decode(v['png']))).size == (192, 224)
        served = Image.open(io.BytesIO(rig['comfy']['files']['p%d.png' % (k + 1)])).convert('RGB')
        assert frame == faces.to_frame(served)
    graphs = rig['comfy']['graphs']
    assert len(graphs) == 4
    seeds = [g['5']['inputs']['seed'] for g in graphs]
    assert seeds == [seeds[0] + k for k in range(4)]
    for g in graphs:
        assert g['2']['inputs']['text'] == faces.STYLE.format(who='a red-haired catcher')
        assert g['3']['inputs']['text'] == faces.NEG
        assert 'LoadImage' not in {n['class_type'] for n in g.values()}
    assert rig['comfy']['uploads'] == []
    assert rig['comfy']['free'] == 1


def test_empty_prompt_uses_veteran(rig):
    rig['site']['queue'].append(_job(''))
    sw.run_once(rig['cfg'])
    texts = [g['2']['inputs']['text'] for g in rig['comfy']['graphs']]
    assert texts == [faces.STYLE.format(who='a veteran player')] * 4


def test_img2img_uploads_once_and_sends_four_graphs(rig):
    raw = _png(_face(5))
    rig['site']['queue'].append(_job('a catcher', image=raw))
    assert sw.run_once(rig['cfg']) == 'done'
    ups = rig['comfy']['uploads']
    assert len(ups) == 1
    assert b'filename="studio_%s.png"' % JOB_ID.encode() in ups[0]
    assert b'name="overwrite"\r\n\r\ntrue' in ups[0]
    assert raw in ups[0]
    graphs = rig['comfy']['graphs']
    assert len(graphs) == 4
    for g in graphs:
        nodes = {n['class_type']: n['inputs'] for n in g.values()}
        assert nodes['LoadImage']['image'] == 'studio_%s.png' % JOB_ID
        assert (nodes['ImageScale']['width'], nodes['ImageScale']['height']) == (832, 960)
        assert nodes['KSampler']['denoise'] == 0.55
        assert 'EmptyLatentImage' not in nodes
        assert g['2']['inputs']['text'] == faces.STYLE.format(who='a catcher')
        assert g['3']['inputs']['text'] == faces.NEG
    assert len(_delivered(rig)['variants']) == 4


def test_auth_headers_sent_and_token_never_printed(rig, capsys):
    rig['site']['queue'].append(_job('a'))
    sw.run_once(rig['cfg'])
    calls = rig['site']['log']
    assert [c['path'] for c in calls] == ['/studio/worker/claim', '/studio/worker/deliver/' + JOB_ID]
    for c in calls:
        assert c['auth'] == AUTH
        assert c['token'] == TOKEN
    assert all(a is None for a in rig['comfy']['auth'])
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err
    assert PASSWORD not in out.out + out.err


def test_comfy_error_delivers_error(rig):
    rig['comfy']['fail'] = True
    rig['site']['queue'].append(_job('a'))
    assert sw.run_once(rig['cfg']) == 'failed'
    err = _delivered(rig)
    assert list(err) == ['error']
    assert 0 < len(err['error']) <= 200
    assert rig['comfy']['free'] == 1


def test_owner_busy_leaves_queue_alone(rig, monkeypatch):
    monkeypatch.setattr(faces, 'owner_busy', lambda *a, **k: True)
    rig['site']['queue'].append(_job('a'))
    assert sw.run_once(rig['cfg']) == 'busy'
    assert rig['site']['log'] == []
    assert len(rig['site']['queue']) == 1


def test_empty_queue_is_idle(rig):
    assert sw.run_once(rig['cfg']) == 'idle'
    assert [c['path'] for c in rig['site']['log']] == ['/studio/worker/claim']
    assert rig['comfy']['free'] == 0


@pytest.mark.skipif(not HAVE_STOCK, reason='needs PORTRAIT.ANM and DEFAULT.PAL for quantize')
def test_build_writes_to_frame_output(tmp_path):
    raw = tmp_path / 'raw'
    raw.mkdir()
    for k in range(2):
        _face(9 * k).save(raw / ('face%02d.png' % k))
    faces.build(str(tmp_path))
    for k in range(2):
        src = Image.open(raw / ('face%02d.png' % k)).convert('RGB')
        assert (tmp_path / 'frames' / ('face%02d.bin' % k)).read_bytes() == faces.to_frame(src)


def test_preview_png_is_192_by_224():
    assert Image.open(io.BytesIO(faces.preview_png(bytes(2688)))).size == (192, 224)
