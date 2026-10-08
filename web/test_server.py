import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

import server as srvmod


def call(port, method, path, body=None, headers=None):
    if body is None and method in ('POST', 'PUT'):
        body = b''
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=body, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def listing(port):
    status, body, headers = call(port, 'GET', '/saves/')
    assert status == 200
    assert headers.get('Content-Type') == 'application/json'
    return json.loads(body)


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.delenv('TLRB2_ALLOW_LOGIN', raising=False)
    site = tmp_path / 'site'
    site.mkdir()
    (site / 'index.html').write_text('<html></html>')
    saves = tmp_path / 'saves'
    s = srvmod.serve(str(site), str(saves), 0)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s
    s.shutdown()
    s.server_close()
    t.join(5)


def port_of(s):
    return s.server_address[1]


def test_put_then_get_roundtrip(srv):
    p = port_of(srv)
    assert call(p, 'PUT', '/saves/alpha', body=b'hello')[0] == 204
    status, body, _ = call(p, 'GET', '/saves/alpha')
    assert status == 200 and body == b'hello'


def test_put_twice_lists_one_prev_version(srv):
    p = port_of(srv)
    call(p, 'PUT', '/saves/alpha', body=b'v1')
    call(p, 'PUT', '/saves/alpha', body=b'v2')
    doc = listing(p)
    assert [s['name'] for s in doc['slots']] == ['alpha']
    assert doc['slots'][0]['size'] == 2
    vers = doc['versions']['alpha']
    assert len(vers) == 1
    assert vers[0]['tag'] == 'prev'
    assert vers[0]['size'] == 2
    assert call(p, 'GET', '/saves/alpha')[1] == b'v2'


def test_listing_accepts_query_string(srv):
    p = port_of(srv)
    call(p, 'PUT', '/saves/alpha', body=b'x')
    status, body, _ = call(p, 'GET', '/saves/?cachebust=1')
    assert status == 200
    assert [s['name'] for s in json.loads(body)['slots']] == ['alpha']


def test_listing_skips_tmp_and_dotfiles(srv):
    p = port_of(srv)
    call(p, 'PUT', '/saves/alpha', body=b'x')
    os.makedirs(srv.saves, exist_ok=True)
    open(os.path.join(srv.saves, 'beta.tmp'), 'wb').close()
    open(os.path.join(srv.saves, '.hidden'), 'wb').close()
    names = [s['name'] for s in listing(p)['slots']]
    assert names == ['alpha']


def test_copy_creates_slot_with_identical_bytes(srv):
    p = port_of(srv)
    data = bytes(range(256)) * 100
    call(p, 'PUT', '/saves/src', body=data)
    assert call(p, 'POST', '/saves/dst?copy=src')[0] == 204
    assert call(p, 'GET', '/saves/dst')[1] == data
    assert call(p, 'GET', '/saves/src')[1] == data
    assert {s['name'] for s in listing(p)['slots']} == {'src', 'dst'}


def test_copy_over_existing_archives_prev(srv):
    p = port_of(srv)
    call(p, 'PUT', '/saves/src', body=b'new')
    call(p, 'PUT', '/saves/dst', body=b'old')
    assert call(p, 'POST', '/saves/dst?copy=src')[0] == 204
    assert call(p, 'GET', '/saves/dst')[1] == b'new'
    assert [v['tag'] for v in listing(p)['versions']['dst']] == ['prev']


def test_copy_from_missing_source_is_404(srv):
    p = port_of(srv)
    assert call(p, 'POST', '/saves/dst?copy=nope')[0] == 404
    assert call(p, 'GET', '/saves/dst')[0] == 404


def test_restore_copies_old_version_and_archives_current(srv):
    p = port_of(srv)
    call(p, 'PUT', '/saves/alpha', body=b'v1')
    call(p, 'PUT', '/saves/alpha', body=b'v2')
    vid = listing(p)['versions']['alpha'][0]['id']
    assert call(p, 'POST', '/saves/alpha?restore=' + urllib.parse.quote(vid, safe=''))[0] == 204
    assert call(p, 'GET', '/saves/alpha')[1] == b'v1'
    tags = [v['tag'] for v in listing(p)['versions']['alpha']]
    assert len(tags) == 2
    assert sorted(v['size'] for v in listing(p)['versions']['alpha']) == [2, 2]
    # the archived v2 is now among the versions and still readable
    ids = [v['id'] for v in listing(p)['versions']['alpha']]
    assert vid in ids
    assert len(ids) == len(set(ids))


def test_restore_bad_ids_are_400(srv):
    p = port_of(srv)
    call(p, 'PUT', '/saves/alpha', body=b'v1')
    call(p, 'PUT', '/saves/alpha', body=b'v2')
    for bad in ('x/alpha.20250101T000000000001.prev', '../alpha.20250101T000000000001.prev', '..'):
        status = call(p, 'POST', '/saves/alpha?' + urllib.parse.urlencode({'restore': bad}))[0]
        assert status == 400, bad
    assert call(p, 'GET', '/saves/alpha')[1] == b'v2'


@pytest.mark.parametrize('name', ['.x', 'a/b', 'a b', 'a' * 65])
def test_bad_slot_names_are_400(srv, name):
    p = port_of(srv)
    path = '/saves/' + urllib.parse.quote(name, safe='')
    assert call(p, 'PUT', path, body=b'x')[0] == 400
    assert call(p, 'GET', path)[0] == 400
    assert call(p, 'POST', path + '?copy=alpha')[0] == 400
    assert call(p, 'DELETE', path)[0] == 400


def test_post_without_query_is_rejected_and_writes_nothing(srv):
    p = port_of(srv)
    status = call(p, 'POST', '/saves/alpha')[0]
    assert status in (400, 405)
    assert not os.path.exists(os.path.join(srv.saves, 'alpha'))
    assert listing(p)['slots'] == []


def test_post_unknown_query_is_400(srv):
    p = port_of(srv)
    call(p, 'PUT', '/saves/src', body=b'x')
    assert call(p, 'POST', '/saves/dst?copy=src&extra=1')[0] == 400
    assert call(p, 'GET', '/saves/dst')[0] == 404


def test_delete_moves_slot_to_deleted_versions(srv):
    p = port_of(srv)
    call(p, 'PUT', '/saves/alpha', body=b'x')
    assert call(p, 'DELETE', '/saves/alpha')[0] == 204
    doc = listing(p)
    assert 'alpha' not in [s['name'] for s in doc['slots']]
    assert [v['tag'] for v in doc['versions']['alpha']] == ['deleted']
    assert call(p, 'GET', '/saves/alpha')[0] == 404


def test_login_header_enforced_per_request(srv, monkeypatch):
    p = port_of(srv)
    monkeypatch.setenv('TLRB2_ALLOW_LOGIN', 'a@b')
    assert call(p, 'GET', '/saves/alpha')[0] == 403
    assert call(p, 'GET', '/saves/alpha', headers={'Tailscale-User-Login': 'a@b'})[0] == 404
    assert call(p, 'GET', '/saves/', headers={'Tailscale-User-Login': 'other'})[0] == 403
