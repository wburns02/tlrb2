import base64
import http.client
import json
import os
import re
import struct
import threading
import urllib.error
import urllib.request
import zipfile

import pytest

import server as srvmod

TOKEN = 's3cret-token'
WORKER = {'X-Studio-Token': TOKEN}
JSON_HDR = {'X-TLRB2': '1', 'Content-Type': 'application/json'}
PNG = b'\x89PNG\r\n\x1a\n' + bytes(24)
JPG = b'\xff\xd8\xff' + bytes(20)
FRAME = 2688
FRAME_HDR = struct.pack('<6H', 0x1001, 56, 48, 0, 0, 0)


def call(port, method, path, body=None, headers=None):
    if body is None and method in ('POST', 'PUT'):
        body = b''
    if headers is None:
        headers = {'X-TLRB2': '1'} if method in ('POST', 'PUT', 'DELETE') else {}
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=body, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def port_of(s):
    return s.server_address[1]


def b64(data):
    return base64.b64encode(data).decode()


def dumps(obj):
    return json.dumps(obj).encode()


def base_anm(c0):
    """u16 c0, then c0 frames of 2700 bytes; frame i is filled with byte 1 + i."""
    return struct.pack('<H', c0) + b''.join(bytes([1 + i % 200]) * 2700 for i in range(c0))


def write_bundle(path, anm):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('TONY2/ANMS/PORTRAIT.ANM', anm)
        z.writestr('TONY2/TONY2.BAT', b'@echo off\r\n')


def variant(k, png=PNG):
    return {'frame': b64(bytes([k + 1]) * FRAME), 'png': b64(png)}


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.delenv('TLRB2_ALLOW_LOGIN', raising=False)
    monkeypatch.delenv('TLRB2_STUDIO_DIR', raising=False)
    monkeypatch.setenv('TLRB2_NO_AUTH', '1')
    site = tmp_path / 'site'
    site.mkdir()
    (site / 'index.html').write_text('<html></html>')
    write_bundle(site / 'tlrb2.jsdos', base_anm(3))
    token = tmp_path / 'token'
    token.write_text(TOKEN + '\n')
    monkeypatch.setenv('TLRB2_STUDIO_TOKEN_FILE', str(token))
    s = srvmod.serve(str(site), str(tmp_path / 'saves'), 0)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s
    s.shutdown()
    s.server_close()
    t.join(5)


@pytest.fixture
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(srvmod.time, 'time', lambda: now[0])
    return now


def new_job(p, prompt='a tall catcher', image=None):
    body = {'prompt': prompt}
    if image is not None:
        body['image'] = b64(image)
    st, b, _ = call(p, 'POST', '/studio/jobs', body=dumps(body), headers=JSON_HDR)
    assert st == 200, b
    return json.loads(b)['id']


def job_state(p, jid):
    st, b, _ = call(p, 'GET', f'/studio/jobs/{jid}')
    assert st == 200, b
    return json.loads(b)


def claim(p):
    return call(p, 'POST', '/studio/worker/claim', headers=WORKER)


def deliver(p, jid, obj):
    return call(p, 'POST', f'/studio/worker/deliver/{jid}', body=dumps(obj),
                headers={**WORKER, 'Content-Type': 'application/json'})


def run_job(p, jid, count=2):
    """Claim and deliver jid (which must be the oldest queued job) with count variants."""
    st, b, _ = claim(p)
    assert st == 200 and json.loads(b)['id'] == jid
    st, _, _ = deliver(p, jid, {'variants': [variant(k) for k in range(count)]})
    assert st == 204


def accept(p, jid, k):
    return call(p, 'POST', f'/studio/jobs/{jid}/accept?pick={k}')


def job_files(srv, jid):
    d = os.path.join(srv.studio, 'jobs')
    return sorted(f for f in os.listdir(d) if f.startswith(jid + '.')) if os.path.isdir(d) else []


def test_create_prompt_image_or_both(srv):
    p = port_of(srv)
    bodies = ({'prompt': 'a tall catcher'}, {'image': b64(PNG)}, {'prompt': 'x', 'image': b64(JPG)})
    for body in bodies:
        st, b, _ = call(p, 'POST', '/studio/jobs', body=dumps(body), headers=JSON_HDR)
        assert st == 200, b
        jid = json.loads(b)['id']
        assert re.fullmatch(r'[0-9a-f]{16}', jid)
        j = job_state(p, jid)
        assert j['state'] == 'queued' and j['error'] is None and j['variants'] == 0 and j['accepted'] == []
        assert (f'{jid}.img' in job_files(srv, jid)) == ('image' in body)


def test_create_400_cases(srv):
    p = port_of(srv)
    cases = {
        'empty object': {},
        'blank both': {'prompt': '   ', 'image': ''},
        'prompt 301': {'prompt': 'x' * 301},
        'non-ascii': {'prompt': 'café'},
        'control char': {'prompt': 'tab\there'},
        'prompt not a string': {'prompt': 5},
        'image not a string': {'image': 7},
        'bad base64': {'image': 'not base64 @@'},
        'bad magic': {'image': b64(b'GIF89a' + bytes(20))},
        'image over 4 MiB': {'image': b64(PNG + bytes((4 << 20) + 1 - len(PNG)))},
    }
    for name, body in cases.items():
        st, b, _ = call(p, 'POST', '/studio/jobs', body=dumps(body), headers=JSON_HDR)
        assert st == 400, name
    for raw in (b'{nope', b'[1, 2]', b''):
        assert call(p, 'POST', '/studio/jobs', body=raw, headers=JSON_HDR)[0] == 400, raw
    assert not os.path.exists(os.path.join(srv.studio, 'jobs'))


def test_prompt_length_boundary_after_strip(srv):
    p = port_of(srv)
    assert call(p, 'POST', '/studio/jobs', body=dumps({'prompt': ' ' + 'x' * 300 + ' '}), headers=JSON_HDR)[0] == 200
    assert call(p, 'POST', '/studio/jobs', body=dumps({'prompt': 'x' * 300}), headers=JSON_HDR)[0] == 200


def test_411_when_length_missing_or_bad(srv):
    p = port_of(srv)
    conn = http.client.HTTPConnection('127.0.0.1', p, timeout=10)
    conn.putrequest('POST', '/studio/jobs')
    conn.putheader('X-TLRB2', '1')
    conn.endheaders()
    assert conn.getresponse().status == 411
    conn.close()
    conn = http.client.HTTPConnection('127.0.0.1', p, timeout=10)
    conn.putrequest('POST', '/studio/jobs')
    conn.putheader('X-TLRB2', '1')
    conn.putheader('Content-Length', 'abc')
    conn.endheaders(b'{}')
    assert conn.getresponse().status == 411
    conn.close()


def test_413_over_the_limit(srv):
    p = port_of(srv)
    too_big = {'X-TLRB2': '1', 'Content-Type': 'application/json', 'Content-Length': str((6 << 20) + 1)}
    assert call(p, 'POST', '/studio/jobs', body=b'{}', headers=too_big)[0] == 413
    assert call(p, 'POST', f'/studio/worker/deliver/{"0" * 16}', body=b'{}',
                headers={**WORKER, 'Content-Length': str((2 << 20) + 1)})[0] == 413


def test_429_when_three_jobs_are_already_active(srv):
    p = port_of(srv)
    ids = [new_job(p) for _ in range(3)]
    st, _, _ = call(p, 'POST', '/studio/jobs', body=dumps({'prompt': 'fourth'}), headers=JSON_HDR)
    assert st == 429
    assert call(p, 'DELETE', f'/studio/jobs/{ids[0]}')[0] == 204
    assert call(p, 'POST', '/studio/jobs', body=dumps({'prompt': 'fourth'}), headers=JSON_HDR)[0] == 200


def test_status_and_queue_position(srv, clock):
    p = port_of(srv)
    ids = []
    for _ in range(3):
        ids.append(new_job(p))
        clock[0] += 1
    assert [job_state(p, i)['position'] for i in ids] == [1, 2, 3]
    run_job(p, ids[0], count=1)
    j = job_state(p, ids[0])
    assert j['state'] == 'done' and j['position'] == 0 and j['variants'] == 1
    assert [job_state(p, i)['position'] for i in ids[1:]] == [1, 2]
    assert call(p, 'GET', '/studio/jobs/' + '0' * 16)[0] == 404


def test_claim_oldest_first_then_204(srv, clock):
    p = port_of(srv)
    first = new_job(p, prompt='first', image=PNG)
    clock[0] += 1
    second = new_job(p, prompt='second')
    st, b, _ = claim(p)
    assert st == 200
    got = json.loads(b)
    assert got == {'id': first, 'prompt': 'first', 'image': b64(PNG)}
    assert job_state(p, first)['state'] == 'running'
    st, b, _ = claim(p)
    assert json.loads(b) == {'id': second, 'prompt': 'second', 'image': None}
    st, b, _ = claim(p)
    assert st == 204 and b == b''


def test_worker_needs_the_token(srv, tmp_path, monkeypatch):
    p = port_of(srv)
    new_job(p)
    for headers in ({}, {'X-Studio-Token': 'wrong'}, {'X-Studio-Token': TOKEN + 'x'}):
        st, b, _ = call(p, 'POST', '/studio/worker/claim', headers=headers)
        assert st == 403
        assert TOKEN.encode() not in b
    assert call(p, 'POST', f'/studio/worker/deliver/{"0" * 16}', body=b'{}', headers={})[0] == 403
    monkeypatch.delenv('TLRB2_STUDIO_TOKEN_FILE')
    assert call(p, 'POST', '/studio/worker/claim', headers=WORKER)[0] == 403
    token = tmp_path / 'empty'
    token.write_text('')
    monkeypatch.setenv('TLRB2_STUDIO_TOKEN_FILE', str(token))
    assert call(p, 'POST', '/studio/worker/claim', headers={'X-Studio-Token': ''})[0] == 403
    assert call(p, 'POST', '/studio/worker/claim', headers={'X-Studio-Token': TOKEN})[0] == 403


def test_worker_token_rotation_needs_no_restart(srv, tmp_path, monkeypatch):
    p = port_of(srv)
    new_job(p)
    token = tmp_path / 'token'
    token.write_text('rotated-token\n')
    assert call(p, 'POST', '/studio/worker/claim', headers=WORKER)[0] == 403
    assert call(p, 'POST', '/studio/worker/claim', headers={'X-Studio-Token': 'rotated-token'})[0] == 200


def test_deliver_variants_and_error(srv):
    p = port_of(srv)
    ok = new_job(p, image=PNG)
    run_job(p, ok, count=2)
    j = job_state(p, ok)
    assert j['state'] == 'done' and j['variants'] == 2 and j['error'] is None
    assert f'{ok}.img' not in job_files(srv, ok)
    assert f'{ok}.v0.bin' in job_files(srv, ok) and f'{ok}.v1.png' in job_files(srv, ok)
    assert os.path.getsize(os.path.join(srv.studio, 'jobs', f'{ok}.v0.bin')) == FRAME

    bad = new_job(p, image=JPG)
    claim(p)
    st, _, _ = deliver(p, bad, {'error': 'no face found'})
    assert st == 204
    j = job_state(p, bad)
    assert j['state'] == 'failed' and j['error'] == 'no face found' and j['variants'] == 0
    assert f'{bad}.img' not in job_files(srv, bad)


def test_deliver_needs_a_running_job(srv):
    p = port_of(srv)
    jid = new_job(p)
    assert deliver(p, jid, {'variants': [variant(0)]})[0] == 409
    run_job(p, jid, count=1)
    assert deliver(p, jid, {'variants': [variant(0)]})[0] == 409


@pytest.mark.parametrize('body', [
    {'variants': []},
    {'variants': [variant(k) for k in range(5)]},
    {'variants': [{'frame': b64(bytes(FRAME - 1)), 'png': b64(PNG)}]},
    {'variants': [{'frame': b64(bytes(FRAME + 1)), 'png': b64(PNG)}]},
    {'variants': [{'frame': b64(bytes(FRAME)), 'png': b64(b'GIF89a')}]},
    {'variants': [{'frame': b64(bytes(FRAME)), 'png': b64(PNG + bytes(256 << 10))}]},
    {'variants': [{'frame': 'not base64 @@', 'png': b64(PNG)}]},
    {'variants': [variant(0)], 'error': 'both'},
    {'error': 'x' * 201},
    {'error': 5},
    {},
])
def test_deliver_bad_bodies_are_400_and_leave_the_job_running(srv, body):
    p = port_of(srv)
    jid = new_job(p)
    claim(p)
    assert deliver(p, jid, body)[0] == 400
    assert job_state(p, jid)['state'] == 'running'


def test_preview_png_served_and_missing_is_404(srv):
    p = port_of(srv)
    jid = new_job(p)
    assert call(p, 'GET', f'/studio/jobs/{jid}/v0.png')[0] == 404
    run_job(p, jid, count=2)
    st, body, headers = call(p, 'GET', f'/studio/jobs/{jid}/v0.png')
    assert st == 200 and headers['Content-Type'] == 'image/png' and body == PNG
    assert call(p, 'GET', f'/studio/jobs/{jid}/v2.png')[0] == 404
    assert call(p, 'GET', f'/studio/jobs/{jid}/v4.png')[0] == 404
    assert call(p, 'GET', f'/studio/jobs/{jid}/v0.PNG')[0] == 404


def test_accept_flow(srv):
    p = port_of(srv)
    jid = new_job(p)
    assert accept(p, jid, 0)[0] == 409
    run_job(p, jid, count=2)
    st, b, _ = accept(p, jid, 0)
    assert st == 200 and json.loads(b) == {'face': 400, 'custom': 1}
    st, b, _ = accept(p, jid, 1)
    assert st == 200 and json.loads(b) == {'face': 401, 'custom': 2}
    st, b, _ = accept(p, jid, 0)
    assert st == 200 and json.loads(b) == {'face': 400, 'custom': 1}
    assert json.loads(call(p, 'GET', '/studio/customs')[1]) == {'count': 2}
    with open(os.path.join(srv.studio, 'customs.bin'), 'rb') as f:
        assert f.read() == bytes([1]) * FRAME + bytes([2]) * FRAME
    assert job_state(p, jid)['accepted'] == [0, 1]
    assert accept(p, jid, 3)[0] == 404
    assert call(p, 'POST', f'/studio/jobs/{jid}/accept?pick=4')[0] == 400
    assert call(p, 'POST', f'/studio/jobs/{jid}/accept')[0] == 400
    assert call(p, 'POST', f'/studio/jobs/{jid}/accept?pick=1&pick=2')[0] == 400
    assert call(p, 'POST', f'/studio/jobs/{"0" * 16}/accept?pick=0')[0] == 404


def test_accept_on_failed_job_is_409(srv):
    p = port_of(srv)
    jid = new_job(p)
    claim(p)
    deliver(p, jid, {'error': 'nope'})
    assert accept(p, jid, 0)[0] == 409


def test_accept_past_581_customs_is_409(srv):
    p = port_of(srv)
    os.makedirs(srv.studio, exist_ok=True)
    with open(os.path.join(srv.studio, 'customs.bin'), 'wb') as f:
        f.write(bytes(581 * FRAME))
    assert json.loads(call(p, 'GET', '/studio/customs')[1]) == {'count': 581}
    jid = new_job(p)
    run_job(p, jid, count=1)
    assert accept(p, jid, 0)[0] == 409
    assert json.loads(call(p, 'GET', '/studio/customs')[1]) == {'count': 581}


def test_delete_job_removes_every_file(srv):
    p = port_of(srv)
    jid = new_job(p, image=PNG)
    run_job(p, jid, count=2)
    accept(p, jid, 0)
    assert job_files(srv, jid)
    assert call(p, 'DELETE', f'/studio/jobs/{jid}')[0] == 204
    assert job_files(srv, jid) == []
    assert call(p, 'GET', f'/studio/jobs/{jid}')[0] == 404
    assert call(p, 'DELETE', f'/studio/jobs/{jid}')[0] == 404
    assert json.loads(call(p, 'GET', '/studio/customs')[1]) == {'count': 1}


def test_customs_count_starts_at_zero(srv):
    p = port_of(srv)
    assert json.loads(call(p, 'GET', '/studio/customs')[1]) == {'count': 0}


def test_portrait_404_without_customs(srv):
    p = port_of(srv)
    assert call(p, 'GET', '/studio/PORTRAIT.ANM')[0] == 404
    os.makedirs(srv.studio, exist_ok=True)
    open(os.path.join(srv.studio, 'customs.bin'), 'wb').close()
    assert call(p, 'GET', '/studio/PORTRAIT.ANM')[0] == 404


def test_portrait_exact_bytes_with_two_customs(srv):
    p = port_of(srv)
    jid = new_job(p)
    run_job(p, jid, count=2)
    accept(p, jid, 0)
    accept(p, jid, 1)
    st, body, headers = call(p, 'GET', '/studio/PORTRAIT.ANM')
    assert st == 200 and headers['Content-Type'] == 'application/octet-stream'
    base = base_anm(3)[2:]
    frame0 = base[:2700]
    expected = (struct.pack('<H', 402) + base + frame0 * 397
                + FRAME_HDR + bytes([1]) * FRAME + FRAME_HDR + bytes([2]) * FRAME)
    assert len(body) == 2 + 2700 * 402
    assert body == expected


def test_portrait_bad_base_is_500(srv):
    p = port_of(srv)
    jid = new_job(p)
    run_job(p, jid, count=1)
    accept(p, jid, 0)
    bundle = os.path.join(srv.site, 'tlrb2.jsdos')
    write_bundle(bundle, base_anm(401))
    assert call(p, 'GET', '/studio/PORTRAIT.ANM')[0] == 500
    write_bundle(bundle, base_anm(3) + b'\x00')
    assert call(p, 'GET', '/studio/PORTRAIT.ANM')[0] == 500


def test_portrait_picks_up_a_redeployed_bundle(srv):
    p = port_of(srv)
    jid = new_job(p)
    run_job(p, jid, count=1)
    accept(p, jid, 0)
    body = call(p, 'GET', '/studio/PORTRAIT.ANM')[1]
    assert body[2 + 2700 * 2:2 + 2700 * 3] == bytes([3]) * 2700
    write_bundle(os.path.join(srv.site, 'tlrb2.jsdos'), base_anm(2))
    body = call(p, 'GET', '/studio/PORTRAIT.ANM')[1]
    assert body[:2] == struct.pack('<H', 401) and len(body) == 2 + 2700 * 401
    assert body[2 + 2700 * 2:2 + 2700 * 3] == bytes([1]) * 2700


def test_stale_running_job_goes_back_to_queued(srv, clock):
    p = port_of(srv)
    jid = new_job(p)
    claim(p)
    clock[0] += 599
    assert job_state(p, jid)['state'] == 'running'
    clock[0] += 2
    j = job_state(p, jid)
    assert j['state'] == 'queued' and j['position'] == 1
    assert json.loads(claim(p)[1])['id'] == jid


def test_job_older_than_a_day_is_removed_with_its_files(srv, clock):
    p = port_of(srv)
    old = new_job(p, image=PNG)
    clock[0] += 3600
    young = new_job(p, image=JPG)
    clock[0] += 86400 - 3600 + 1
    assert call(p, 'GET', '/studio/customs')[0] == 200
    assert call(p, 'GET', f'/studio/jobs/{old}')[0] == 404
    assert job_files(srv, old) == []
    assert job_state(p, young)['state'] == 'queued'


def test_writes_without_guard_header_are_refused(srv):
    p = port_of(srv)
    jid = new_job(p)
    assert call(p, 'POST', '/studio/jobs', body=dumps({'prompt': 'x'}), headers={})[0] == 403
    assert call(p, 'POST', f'/studio/jobs/{jid}/accept?pick=0', headers={})[0] == 403
    assert call(p, 'DELETE', f'/studio/jobs/{jid}', headers={})[0] == 403
    cross = {'X-TLRB2': '1', 'Origin': 'https://evil.example', 'Content-Type': 'application/json'}
    assert call(p, 'POST', '/studio/jobs', body=dumps({'prompt': 'x'}), headers=cross)[0] == 403
    assert job_state(p, jid)['state'] == 'queued'


def test_reads_need_the_identity_check(srv, monkeypatch):
    p = port_of(srv)
    jid = new_job(p)
    monkeypatch.delenv('TLRB2_NO_AUTH')
    assert call(p, 'GET', f'/studio/jobs/{jid}')[0] == 403
    assert call(p, 'GET', '/studio/customs')[0] == 403
    assert call(p, 'POST', '/studio/worker/claim', headers=WORKER)[0] == 403


@pytest.mark.parametrize('bad', ['XYZ', '0' * 15, '0' * 17, '0123456789ABCDEF', '0123456789abcdef%0A'])
def test_ids_that_are_not_16_lowercase_hex_are_404(srv, bad):
    p = port_of(srv)
    assert call(p, 'GET', f'/studio/jobs/{bad}')[0] == 404
    assert call(p, 'GET', f'/studio/jobs/{bad}/v0.png')[0] == 404
    assert call(p, 'POST', f'/studio/jobs/{bad}/accept?pick=0')[0] == 404
    assert call(p, 'DELETE', f'/studio/jobs/{bad}')[0] == 404
    assert call(p, 'POST', f'/studio/worker/deliver/{bad}', body=dumps({'error': 'x'}),
                headers={**WORKER, 'X-TLRB2': '1', 'Content-Type': 'application/json'})[0] == 404


def test_unknown_studio_paths_are_404(srv):
    p = port_of(srv)
    assert call(p, 'GET', '/studio/nope')[0] == 404
    assert call(p, 'GET', '/studio/')[0] == 404
    assert call(p, 'GET', '/studio/jobs')[0] == 404
    assert call(p, 'POST', '/studio/nope', body=b'{}', headers=JSON_HDR)[0] == 404
    assert call(p, 'HEAD', '/studio/customs')[0] == 404


def test_studio_dir_is_a_sibling_of_saves(srv):
    p = port_of(srv)
    jid = new_job(p, image=PNG)
    assert srv.studio == os.path.join(os.path.dirname(srv.saves), 'studio')
    assert os.path.isfile(os.path.join(srv.studio, 'jobs', f'{jid}.json'))
    assert not os.path.exists(os.path.join(srv.saves, 'studio'))
    listing = json.loads(call(p, 'GET', '/saves/')[1])
    assert listing == {'slots': [], 'versions': {}}


def test_static_site_still_served(srv):
    p = port_of(srv)
    st, body, _ = call(p, 'GET', '/index.html')
    assert st == 200 and body == b'<html></html>'
