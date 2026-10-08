#!/usr/bin/env python3
"""Static site + save store for the TLRB2 browser build. Binds localhost only; put `tailscale serve` in front
for HTTPS on the tailnet (js-dos needs a secure context). Never expose it publicly: the site holds the game.

usage: server.py SITE_DIR SAVES_DIR [PORT]
env:   TLRB2_ALLOW_LOGIN  only requests whose Tailscale-User-Login header equals it are served
       TLRB2_NO_AUTH=1    serve without it (local tests only); with neither set every request gets 403
Writes (PUT, POST, DELETE) also need the header X-TLRB2: 1 and a same-origin Origin if one is sent.

GET/PUT/DELETE /saves/<name>: the js-dos filesystem-changes blob. PUT keeps the previous KEEP versions in
SAVES_DIR/old/, DELETE moves the save there, so a bad push never destroys a season.
GET /saves/: JSON listing of live slots and archived versions (also of deleted names).
POST /saves/<name>?copy=<src>: copy live slot <src> to <name> (the old <name>, if any, is archived).
POST /saves/<name>?restore=<id>: copy SAVES_DIR/old/<id> to <name> (the old <name>, if any, is archived).
"""
import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.parse

MAX_SAVE = 64 << 20
KEEP = 20
NAME = re.compile(r'^[A-Za-z0-9_-]{1,64}$')   # no dots: version ids are <name>.<stamp>.<tag>
RESERVED = ('old',)                              # SAVES_DIR/old holds the archive
TAGS = ('prev', 'deleted')


def _valid_name(name):
    return bool(NAME.match(name)) and name.lower() not in RESERVED


def _parse_version(fname):
    """'<name>.<stamp>.<tag>' -> (name, stamp, tag), or None if fname is not an archive file name."""
    parts = fname.rsplit('.', 2)
    if len(parts) != 3 or parts[2] not in TAGS or not parts[1]:
        return None
    return parts[0], parts[1], parts[2]


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      '.wasm': 'application/wasm', '.jsdos': 'application/zip', '.js': 'text/javascript',
                      '.mjs': 'text/javascript'}

    def _allowed(self, write=False):
        """Tailscale identity check (fail closed: no TLRB2_ALLOW_LOGIN means 403 unless TLRB2_NO_AUTH=1, for local
        tests only). Writes also need the X-TLRB2 header and, if the browser sends Origin, a same-origin one: a
        custom header forces a CORS preflight this server never answers, so another site cannot write saves."""
        want = os.environ.get('TLRB2_ALLOW_LOGIN')
        if want:
            ok = self.headers.get('Tailscale-User-Login') == want
        else:
            ok = os.environ.get('TLRB2_NO_AUTH') == '1'
        if ok and write:
            origin = self.headers.get('Origin')
            hosts = {self.headers.get('Host'), self.headers.get('X-Forwarded-Host')} - {None}
            ok = (self.headers.get('X-TLRB2') == '1'
                  and self.headers.get('Sec-Fetch-Site', 'same-origin') == 'same-origin'
                  and (origin is None or urllib.parse.urlsplit(origin).netloc in hosts))
        if not ok:
            self.send_error(403)
        return ok

    def _save_path(self):
        """None if the path is not /saves/..., False if the name is invalid (400 already sent), else the file path."""
        url_path = urllib.parse.urlsplit(self.path).path
        if not url_path.startswith('/saves/'):
            return None
        name = url_path[len('/saves/'):]
        if not _valid_name(name):
            self.send_error(400, 'bad save name')
            return False
        return os.path.join(self.server.saves, name)

    def _send_json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)

    def _listing(self):
        """Caller holds the server lock."""
        root = self.server.saves
        slots = []
        with os.scandir(root) as it:
            for e in it:
                n = e.name
                if not _valid_name(n) or n.endswith('.tmp') or not e.is_file():
                    continue
                st = e.stat()
                slots.append({'name': n, 'size': st.st_size, 'mtime': st.st_mtime})
        slots.sort(key=lambda s: s['mtime'], reverse=True)

        found = {}
        old = os.path.join(root, 'old')
        if os.path.isdir(old):
            with os.scandir(old) as it:
                for e in it:
                    parsed = _parse_version(e.name)
                    if not parsed or not _valid_name(parsed[0]) or not e.is_file():
                        continue
                    name, stamp, tag = parsed
                    st = e.stat()
                    found.setdefault(name, []).append((stamp, {
                        'id': e.name, 'size': st.st_size, 'mtime': st.st_mtime, 'tag': tag}))
        versions = {}
        for name, items in found.items():
            items.sort(key=lambda t: t[0], reverse=True)
            versions[name] = [v for _, v in items]
        return {'slots': slots, 'versions': versions}

    def do_GET(self):
        if not self._allowed():
            return
        if urllib.parse.urlsplit(self.path).path == '/saves/':
            with self.server.lock:
                listing = self._listing()
            return self._send_json(listing)
        p = self._save_path()
        if p is False:
            return
        if p is None:
            return super().do_GET()
        try:
            with open(p, 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            return self.send_error(404)
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self):
        if self._allowed():
            super().do_HEAD()

    def _archive(self, p, tag):
        """Caller holds the server lock."""
        if not os.path.exists(p):
            return
        old = os.path.join(self.server.saves, 'old')
        os.makedirs(old, exist_ok=True)
        base = os.path.basename(p)
        t = time.time()
        stamp = time.strftime('%Y%m%dT%H%M%S', time.localtime(t)) + '%06d' % int(t % 1 * 1e6)
        os.replace(p, os.path.join(old, f'{base}.{stamp}.{tag}'))
        mine = sorted(f for f in os.listdir(old)
                      if (_parse_version(f) or ('',))[0] == base)
        for f in mine[:-KEEP]:
            os.remove(os.path.join(old, f))

    def _store(self, p, data):
        """Write data as the live copy at p, archiving the previous one. Caller holds the server lock."""
        tmp = p + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        self._archive(p, 'prev')
        os.replace(tmp, p)

    def do_PUT(self):
        if not self._allowed(write=True):
            return
        p = self._save_path()
        if not p:
            return p is None and self.send_error(404)
        try:
            n = int(self.headers.get('Content-Length', ''))
        except ValueError:
            return self.send_error(411)
        if n <= 0 or n > MAX_SAVE:
            return self.send_error(413)
        data = self.rfile.read(n)
        if len(data) != n:
            return self.send_error(400, 'short body')
        with self.server.lock:
            self._store(p, data)
        self.send_response(204)
        self.end_headers()

    def do_DELETE(self):
        if not self._allowed(write=True):
            return
        p = self._save_path()
        if not p:
            return p is None and self.send_error(404)
        with self.server.lock:
            self._archive(p, 'deleted')
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        if not self._allowed(write=True):
            return
        url = urllib.parse.urlsplit(self.path)
        if not url.path.startswith('/saves/') or not url.query:
            return self.send_error(405)
        p = self._save_path()
        if p is None:
            return self.send_error(405)
        if p is False:
            return
        qs = urllib.parse.parse_qs(url.query, keep_blank_values=True)
        ops = [k for k in ('copy', 'restore') if k in qs]
        if len(ops) != 1 or set(qs) != set(ops) or len(qs[ops[0]]) != 1:
            return self.send_error(400, 'expected exactly one of copy or restore')
        op, arg = ops[0], qs[ops[0]][0]

        if op == 'copy':
            if not _valid_name(arg):
                return self.send_error(400, 'bad source name')
            src = os.path.join(self.server.saves, arg)
            with self.server.lock:
                if not os.path.isfile(src):
                    return self.send_error(404)
                with open(src, 'rb') as f:
                    data = f.read()
                self._store(p, data)
        else:
            ver = _parse_version(arg)
            if (not ver or not _valid_name(ver[0]) or '/' in arg or '\\' in arg or '..' in arg
                    or os.path.basename(arg) != arg):
                return self.send_error(400, 'bad version id')
            src = os.path.join(self.server.saves, 'old', arg)
            with self.server.lock:
                if not os.path.isfile(src):
                    return self.send_error(404)
                with open(src, 'rb') as f:
                    data = f.read()
                self._store(p, data)
        self.send_response(204)
        self.end_headers()


def serve(site, saves, port):
    os.makedirs(saves, exist_ok=True)

    class H(Handler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=site, **k)

    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), H)
    srv.saves = saves
    srv.lock = threading.Lock()
    return srv


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    s = serve(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) == 4 else 8121)
    print('serving on 127.0.0.1:%d' % s.server_address[1], flush=True)
    s.serve_forever()
