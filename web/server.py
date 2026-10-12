#!/usr/bin/env python3
"""Static site + save store for the TLRB2 browser build. Binds localhost only; put `tailscale serve` in front
for HTTPS on the tailnet (js-dos needs a secure context), or a reverse proxy that authenticates first (see
web/nginx-auth.conf.example). Never expose it without auth: the site holds the game.

usage: server.py SITE_DIR SAVES_DIR [PORT]
env:   TLRB2_ALLOW_LOGIN  only requests whose Tailscale-User-Login header equals it are served
       TLRB2_NO_AUTH=1    serve without it (local tests only); with neither set every request gets 403
       TLRB2_STUDIO_DIR   portrait studio files (default: studio next to SAVES_DIR)
       TLRB2_STUDIO_TOKEN_FILE  first line is the worker token (read on every worker request)
Writes (PUT, POST, DELETE) also need the header X-TLRB2: 1 and a same-origin Origin if one is sent.

GET/PUT/DELETE /saves/<name>: the js-dos filesystem-changes blob. PUT keeps the previous KEEP versions in
SAVES_DIR/old/, DELETE moves the save there, so a bad push never destroys a season.
GET /saves/: JSON listing of live slots and archived versions (also of deleted names).
POST /saves/<name>?copy=<src>: copy live slot <src> to <name> (the old <name>, if any, is archived).
POST /saves/<name>?restore=<id>: copy SAVES_DIR/old/<id> to <name> (the old <name>, if any, is archived).

Portrait studio (/studio/...): POST /studio/jobs queues a job; GET /studio/jobs/<id> is its state; DELETE removes it.
GET /studio/jobs/<id>/v<k>.png is a preview; POST /studio/jobs/<id>/accept?pick=<k> adds variant k to the customs.
GET /studio/customs is {"count"}; GET /studio/PORTRAIT.ANM is the bundle's portrait file with the customs appended.
POST /studio/worker/claim and POST /studio/worker/deliver/<id> are the GPU worker's (header X-Studio-Token).
"""
import base64
import http.server
import hmac
import json
import os
import re
import secrets
import struct
import sys
import threading
import time
import urllib.parse
import zipfile

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


STUDIO_JSON = 6 << 20           # POST /studio/jobs body
STUDIO_DELIVER = 2 << 20        # POST /studio/worker/deliver body
IMAGE_MAX = 4 << 20             # an uploaded picture, decoded
PREVIEW_MAX = 256 << 10         # a preview PNG, decoded
PROMPT_MAX = 300
ACTIVE_MAX = 3                  # at most this many queued or running jobs; one more: 429
CUSTOMS_MAX = 581
FRAME = 2688                    # one face: 56 x 48 pixels, a byte each
FRAME_HDR = struct.pack('<6H', 0x1001, 56, 48, 0, 0, 0)
ANM_FRAME = 12 + FRAME          # FRAME_HDR + FRAME, a frame as the portrait file stores it
ANM_FRAMES = 400                # the portrait file has 400 frame slots; customs come after them
ANM_ENTRY = 'TONY2/ANMS/PORTRAIT.ANM'
BUNDLE = 'tlrb2.jsdos'
DAY = 24 * 3600
STALE = 600                     # a running job claimed longer ago goes back to queued
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
JPEG_MAGIC = b'\xff\xd8\xff'
PROMPT_OK = re.compile(r'[ -~]*')                 # printable ASCII
JOB_ID = re.compile(r'[0-9a-f]{16}')
PICK = re.compile(r'[0-3]')
JOB = r'([0-9a-f]{16})'

# method, path regex, auth (read | write | worker), body limit or None, handler name
STUDIO_ROUTES = [
    ('GET', re.compile(r'/studio/PORTRAIT\.ANM'), 'read', None, '_studio_portrait'),
    ('GET', re.compile(r'/studio/customs'), 'read', None, '_studio_customs'),
    ('GET', re.compile(r'/studio/jobs/' + JOB), 'read', None, '_studio_job'),
    ('GET', re.compile(r'/studio/jobs/' + JOB + r'/v([0-3])\.png'), 'read', None, '_studio_preview'),
    ('POST', re.compile(r'/studio/jobs'), 'write', STUDIO_JSON, '_studio_create'),
    ('POST', re.compile(r'/studio/jobs/' + JOB + r'/accept'), 'write', None, '_studio_accept'),
    ('DELETE', re.compile(r'/studio/jobs/' + JOB), 'write', None, '_studio_delete'),
    ('POST', re.compile(r'/studio/worker/claim'), 'worker', None, '_studio_claim'),
    ('POST', re.compile(r'/studio/worker/deliver/' + JOB), 'worker', STUDIO_DELIVER, '_studio_deliver'),
]


def _decode_image(s):
    """The bytes of a base64 upload, or None unless they are a PNG or JPEG of at most IMAGE_MAX bytes."""
    try:
        img = base64.b64decode(s, validate=True)
    except ValueError:
        return None
    return img if len(img) <= IMAGE_MAX and img.startswith((PNG_MAGIC, JPEG_MAGIC)) else None


def _unb64(s):
    if not isinstance(s, str):
        raise ValueError('not base64')
    return base64.b64decode(s, validate=True)


def _parse_delivery(body):
    """('error', text) or ('done', [(frame, png), ...]) from a worker delivery. Raises ValueError."""
    if ('error' in body) == ('variants' in body):
        raise ValueError('need exactly one of error or variants')
    if 'error' in body:
        if not isinstance(body['error'], str) or len(body['error']) > 200:
            raise ValueError('bad error')
        return 'error', body['error']
    variants = body['variants']
    if not isinstance(variants, list) or not 1 <= len(variants) <= 4:
        raise ValueError('bad variants')
    out = []
    for v in variants:
        if not isinstance(v, dict):
            raise ValueError('bad variant')
        frame, png = _unb64(v.get('frame')), _unb64(v.get('png'))
        if len(frame) != FRAME or not 0 < len(png) <= PREVIEW_MAX or not png.startswith(PNG_MAGIC):
            raise ValueError('bad variant')
        out.append((frame, png))
    return 'done', out


def _queue(jobs):
    """Queued jobs, oldest first."""
    return sorted((j for j in jobs.values() if j['state'] == 'queued'), key=lambda j: (j['created'], j['id']))


def _job_view(job, jobs):
    """The GET /studio/jobs/<id> body. position is 1-based among queued jobs, 0 when the job is not queued."""
    ids = [j['id'] for j in _queue(jobs)]
    return {'id': job['id'], 'state': job['state'], 'error': job['error'], 'variants': job['variants'],
            'accepted': job['accepted'], 'position': ids.index(job['id']) + 1 if job['id'] in ids else 0}


def _write_file(path, data):
    """Write data to path through path.tmp and os.replace, creating the directory if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_file(path):
    """The bytes of path, or None if it does not exist."""
    try:
        with open(path, 'rb') as f:
            return f.read()
    except FileNotFoundError:
        return None


def _remove_file(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


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
        if self._studio_path():
            return self._studio('GET')
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
        if self._studio_path():
            return self._studio('HEAD')
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
        if self._studio_path():
            return self._studio('DELETE')
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
        if self._studio_path():
            return self._studio('POST')
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

    # ---- portrait studio. Every handler runs under the server lock with the job table after housekeeping.

    def _send_bytes(self, data, ctype):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _studio_path(self):
        return urllib.parse.urlsplit(self.path).path.startswith('/studio/')

    def _studio(self, method):
        """Any /studio/... request: route, auth, then the body (read before the lock), then the handler. A path with
        no route is 404 once the caller is allowed in."""
        path = urllib.parse.urlsplit(self.path).path
        for m, pat, auth, limit, fn in STUDIO_ROUTES:
            mt = pat.fullmatch(path)
            if m == method and mt:
                break
        else:
            if self._allowed(write=method not in ('GET', 'HEAD')):
                self.send_error(404)
            return
        if auth == 'worker':
            ok = self._allowed() and self._worker_ok()
        else:
            ok = self._allowed(write=auth == 'write')
        if not ok:
            return
        body = None
        if limit is not None:
            body = self._read_json(limit)
            if body is None:
                return
        with self.server.lock:
            getattr(self, fn)(self._scan_jobs(), body, *mt.groups())

    def _worker_ok(self):
        """X-Studio-Token must equal the first line of the file named by TLRB2_STUDIO_TOKEN_FILE. The file is read on
        every request, so a rotated token needs no restart. Anything else is 403; the token is never echoed or logged."""
        want = b''
        path = os.environ.get('TLRB2_STUDIO_TOKEN_FILE')
        if path:
            try:
                with open(path, 'rb') as f:
                    want = f.readline(4096).strip()
            except OSError:
                want = b''
        got = (self.headers.get('X-Studio-Token') or '').encode()
        if want and hmac.compare_digest(got, want):
            return True
        self.send_error(403)
        return False

    def _read_json(self, limit):
        """The request body as a JSON object, or None after 411, 413 or 400 is sent. Content-Length is checked before
        the body is read."""
        cl = self.headers.get('Content-Length') or ''
        if not re.fullmatch(r'[0-9]{1,12}', cl):
            self.send_error(411)
            return None
        n = int(cl)
        if n > limit:
            self.send_error(413)
            return None
        raw = self.rfile.read(n)
        try:
            obj = json.loads(raw) if len(raw) == n else None
        except (ValueError, RecursionError):
            obj = None
        if not isinstance(obj, dict):
            self.send_error(400, 'expected a JSON object')
            return None
        return obj

    def _jobs_dir(self):
        return os.path.join(self.server.studio, 'jobs')

    def _job_file(self, name):
        """A file in the jobs dir. name is always a validated id plus a fixed suffix, never client text."""
        return os.path.join(self._jobs_dir(), name)

    def _customs_path(self):
        return os.path.join(self.server.studio, 'customs.bin')

    def _save_job(self, job):
        _write_file(self._job_file(job['id'] + '.json'), json.dumps(job).encode())

    def _remove_job(self, jid):
        """Remove every file of a job. jid is a validated id, and the prefix includes the dot, so no other job matches."""
        d = self._jobs_dir()
        for name in os.listdir(d):
            if name.startswith(jid + '.'):
                _remove_file(os.path.join(d, name))

    def _scan_jobs(self):
        """{id: job} for every job after housekeeping: a job created over a day ago is removed with its files, and a
        running job claimed over 10 minutes ago goes back to queued."""
        jobs = {}
        d = self._jobs_dir()
        if not os.path.isdir(d):
            return jobs
        now = time.time()
        for name in os.listdir(d):
            if not name.endswith('.json') or not JOB_ID.fullmatch(name[:-len('.json')]):
                continue
            jid = name[:-len('.json')]
            try:
                with open(os.path.join(d, name), 'rb') as f:
                    job = json.loads(f.read())
            except (OSError, ValueError):
                continue
            if now - job['created'] > DAY:
                self._remove_job(jid)
                continue
            if job['state'] == 'running' and now - job['claimed'] > STALE:
                job.update(state='queued', claimed=None)
                self._save_job(job)
            jobs[jid] = job
        return jobs

    def _base_anm(self):
        """The bundle's PORTRAIT.ANM (u16 c0, then c0 frames), or None if it is missing, has c0 outside 1..400 or is
        not exactly 2 + 2700 * c0 bytes. The zip is read again only when its (mtime, size) changes."""
        path = os.path.join(self.server.site, BUNDLE)
        try:
            st = os.stat(path)
            key = (st.st_mtime_ns, st.st_size)
            if self.server.anm[0] != key:
                with zipfile.ZipFile(path) as z:
                    self.server.anm = (key, z.read(ANM_ENTRY))
        except (OSError, KeyError, zipfile.BadZipFile):
            return None
        base = self.server.anm[1]
        c0 = int.from_bytes(base[:2], 'little')
        if not 1 <= c0 <= ANM_FRAMES or len(base) != 2 + ANM_FRAME * c0:
            return None
        return base

    def _studio_create(self, jobs, body):
        prompt, image = body.get('prompt', ''), body.get('image', '')
        if not all(isinstance(f, (str, type(None))) for f in (prompt, image)):
            return self.send_error(400, 'prompt and image must be strings')
        prompt, image = (prompt or '').strip(), image or ''
        if len(prompt) > PROMPT_MAX or not PROMPT_OK.fullmatch(prompt):
            return self.send_error(400, 'prompt must be printable ASCII, 300 characters at most')
        img = None
        if image:
            img = _decode_image(image)
            if img is None:
                return self.send_error(400, 'image must be a PNG or JPEG of 4 MiB at most')
        if not prompt and img is None:
            return self.send_error(400, 'need a prompt or an image')
        if sum(j['state'] in ('queued', 'running') for j in jobs.values()) >= ACTIVE_MAX:
            return self.send_error(429)
        jid = secrets.token_hex(8)
        if img is not None:
            _write_file(self._job_file(jid + '.img'), img)
        self._save_job({'id': jid, 'state': 'queued', 'prompt': prompt, 'has_image': img is not None,
                        'created': time.time(), 'claimed': None, 'error': None, 'variants': 0,
                        'accepted': [], 'faces': {}})
        self._send_json({'id': jid})

    def _studio_job(self, jobs, body, jid):
        job = jobs.get(jid)
        if job is None:
            return self.send_error(404)
        self._send_json(_job_view(job, jobs))

    def _studio_preview(self, jobs, body, jid, k):
        data = _read_file(self._job_file(f'{jid}.v{k}.png'))
        if data is None:
            return self.send_error(404)
        self._send_bytes(data, 'image/png')

    def _studio_accept(self, jobs, body, jid):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query, keep_blank_values=True)
        if list(query) != ['pick'] or len(query['pick']) != 1 or not PICK.fullmatch(query['pick'][0]):
            return self.send_error(400, 'pick must be 0 to 3')
        k = query['pick'][0]
        job = jobs.get(jid)
        if job is None:
            return self.send_error(404)
        if job['state'] != 'done':
            return self.send_error(409, 'job is not done')
        if k not in job['faces']:
            frame = _read_file(self._job_file(f'{jid}.v{k}.bin'))
            if frame is None:
                return self.send_error(404)
            customs = _read_file(self._customs_path()) or b''
            n = len(customs) // FRAME
            if n >= CUSTOMS_MAX:
                return self.send_error(409, 'customs are full')
            _write_file(self._customs_path(), customs + frame)
            job['accepted'].append(int(k))
            job['faces'][k] = n
            self._save_job(job)
        n = job['faces'][k]
        self._send_json({'face': ANM_FRAMES + n, 'custom': n + 1})

    def _studio_delete(self, jobs, body, jid):
        if jid not in jobs:
            return self.send_error(404)
        self._remove_job(jid)
        self.send_response(204)
        self.end_headers()

    def _studio_customs(self, jobs, body):
        customs = _read_file(self._customs_path()) or b''
        self._send_json({'count': len(customs) // FRAME})

    def _studio_portrait(self, jobs, body):
        customs = _read_file(self._customs_path()) or b''
        n = len(customs) // FRAME
        if not n:
            return self.send_error(404)
        base = self._base_anm()
        if base is None:
            return self.send_error(500, 'bad bundle PORTRAIT.ANM')
        c0 = int.from_bytes(base[:2], 'little')
        frames = base[2:]
        out = [struct.pack('<H', ANM_FRAMES + n), frames, frames[:ANM_FRAME] * (ANM_FRAMES - c0)]
        out += [FRAME_HDR + customs[i * FRAME:(i + 1) * FRAME] for i in range(n)]
        self._send_bytes(b''.join(out), 'application/octet-stream')

    def _studio_claim(self, jobs, body):
        queued = _queue(jobs)
        if not queued:
            self.send_response(204)
            self.end_headers()
            return
        job = queued[0]
        job.update(state='running', claimed=time.time())
        self._save_job(job)
        data = _read_file(self._job_file(job['id'] + '.img')) if job['has_image'] else None
        image = base64.b64encode(data).decode('ascii') if data is not None else None
        self._send_json({'id': job['id'], 'prompt': job['prompt'], 'image': image})

    def _studio_deliver(self, jobs, body, jid):
        try:
            kind, payload = _parse_delivery(body)
        except ValueError:
            return self.send_error(400, 'bad delivery')
        job = jobs.get(jid)
        if job is None:
            return self.send_error(404)
        if job['state'] != 'running':
            return self.send_error(409, 'job is not running')
        if kind == 'error':
            job.update(state='failed', error=payload)
        else:
            for k, (frame, png) in enumerate(payload):
                _write_file(self._job_file(f'{jid}.v{k}.bin'), frame)
                _write_file(self._job_file(f'{jid}.v{k}.png'), png)
            job.update(state='done', variants=len(payload))
        _remove_file(self._job_file(jid + '.img'))
        self._save_job(job)
        self.send_response(204)
        self.end_headers()


def serve(site, saves, port):
    os.makedirs(saves, exist_ok=True)

    class H(Handler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=site, **k)

    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), H)
    srv.saves = saves
    srv.site = site
    srv.studio = os.environ.get('TLRB2_STUDIO_DIR') or os.path.join(os.path.dirname(os.path.abspath(saves)), 'studio')
    srv.anm = (None, b'')
    srv.lock = threading.Lock()
    return srv


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    s = serve(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) == 4 else 8121)
    print('serving on 127.0.0.1:%d' % s.server_address[1], flush=True)
    s.serve_forever()
