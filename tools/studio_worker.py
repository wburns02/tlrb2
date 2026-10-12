#!/usr/bin/env python3
"""Portrait Studio worker (C14.3): renders the site's queued portrait jobs on the GPU box and delivers them.

Loop: GPU busy (faces.owner_busy) -> wait; else claim a job, render 4 variants on the local ComfyUI (txt2img, or
img2img from the job's image), deliver each as the 2688 B frame plus a 192 x 224 preview PNG. stdlib only; logs to
stdout (journald). Never logs the token, the password or image bytes.

config: env, else ~/.config/tlrb2/studio.env (KEY=VALUE lines):
  TLRB2_STUDIO_URL          site URL (default: the url= line of web_login)
  TLRB2_STUDIO_TOKEN_FILE   file whose first line is the worker token
  TLRB2_WEB_LOGIN           basic auth file: url= user= password= (default ~/.config/tlrb2/web_login)
  TLRB2_COMFY               ComfyUI base URL (default faces.COMFY)
"""
import base64
import http.client
import io
import json
import os
import random
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import faces  # noqa: E402

VARIANTS = 4
IMG2IMG_DENOISE = 0.55
POLL_S = 1.0                                # ComfyUI history poll interval
RENDER_TIMEOUT_S = 600                      # per variant, as faces.gen
BUSY_S, IDLE_S, ERR_S = 30, 10, 30


def log(msg):
    print(msg, flush=True)


def read_kv(path):
    """KEY=VALUE lines, # comments skipped; a missing file reads as empty."""
    out = {}
    try:
        text = open(path, encoding='utf-8').read()
    except FileNotFoundError:
        return out
    for line in text.splitlines():
        k, sep, v = line.partition('=')
        if sep and not k.lstrip().startswith('#'):
            out[k.strip()] = v.strip()
    return out


def load_cfg():
    cfg_dir = os.path.join(os.path.expanduser('~'), '.config', 'tlrb2')
    login = read_kv(os.environ.get('TLRB2_WEB_LOGIN') or os.path.join(cfg_dir, 'web_login'))
    envf = read_kv(os.path.join(cfg_dir, 'studio.env'))

    def setting(k):
        return os.environ.get(k) or envf.get(k) or ''

    url = setting('TLRB2_STUDIO_URL') or login.get('url', '')
    try:
        with open(os.path.expanduser(setting('TLRB2_STUDIO_TOKEN_FILE')), encoding='utf-8') as f:
            token = f.readline().strip()
    except OSError:
        token = ''
    if not (url and login.get('user') and login.get('password') and token):
        sys.exit('studio_worker: need a site URL, user= and password= in web_login, and a token file '
                 '(TLRB2_STUDIO_URL, TLRB2_STUDIO_TOKEN_FILE; env or studio.env)')
    cred = base64.b64encode(('%s:%s' % (login['user'], login['password'])).encode()).decode()
    return {'url': url.rstrip('/'), 'auth': 'Basic ' + cred, 'token': token,
            'comfy': os.environ.get('TLRB2_COMFY') or faces.COMFY}


def _site(cfg, path, body=None):
    """Worker call to the site: nginx basic auth in Authorization, the worker token in X-Studio-Token."""
    headers = {'Authorization': cfg['auth'], 'X-Studio-Token': cfg['token']}
    data = b''
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(cfg['url'] + path, data, headers, method='POST')
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()


def _comfy(cfg, path, body=None, ctype='application/json'):
    """Local ComfyUI call, no site credentials. body bytes -> POST, None -> GET. Returns the raw reply."""
    req = urllib.request.Request(cfg['comfy'] + path, body, {'Content-Type': ctype})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError('ComfyUI %s: %s' % (e.code, e.read()[:200].decode('utf-8', 'replace')))


def claim(cfg):
    status, body = _site(cfg, '/studio/worker/claim')
    if status == 204:
        return None
    job = json.loads(body)
    if not re.fullmatch(r'[0-9a-f]{16}', str(job.get('id', ''))):
        raise ValueError('bad job id from site')
    return job


def deliver(cfg, job_id, body):
    _site(cfg, '/studio/worker/deliver/' + job_id, body)


def _upload(cfg, filename, data):
    """ComfyUI /upload/image (multipart, overwrite); returns the name LoadImage must use."""
    b = secrets.token_hex(16)
    body = (('--%s\r\nContent-Disposition: form-data; name="image"; filename="%s"\r\n'
             'Content-Type: application/octet-stream\r\n\r\n' % (b, filename)).encode()
            + data
            + ('\r\n--%s\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--%s--\r\n'
               % (b, b)).encode())
    reply = json.loads(_comfy(cfg, '/upload/image', body, 'multipart/form-data; boundary=' + b))
    return reply.get('name', filename)


def img2img_graph(text, seed, image):
    """faces._workflow with the empty latent replaced by the job's image: LoadImage -> scale -> VAEEncode."""
    wf = faces._workflow(text, seed)
    del wf['4']                             # EmptyLatentImage
    wf['4'] = {'class_type': 'LoadImage', 'inputs': {'image': image}}
    wf['8'] = {'class_type': 'ImageScale', 'inputs': {'image': ['4', 0], 'upscale_method': 'lanczos',
                                                       'width': 832, 'height': 960, 'crop': 'center'}}
    wf['9'] = {'class_type': 'VAEEncode', 'inputs': {'pixels': ['8', 0], 'vae': ['1', 2]}}
    wf['5']['inputs'].update(latent_image=['9', 0], denoise=IMG2IMG_DENOISE)
    return wf


def _await(cfg, pid):
    """Poll /history until PreviewImage (node 7) has its image; a ComfyUI execution error fails at once."""
    end = time.monotonic() + RENDER_TIMEOUT_S
    while time.monotonic() < end:
        h = json.loads(_comfy(cfg, '/history/' + pid)).get(pid)
        if h:
            if h.get('status', {}).get('status_str') == 'error':
                raise RuntimeError('ComfyUI execution failed')
            imgs = h.get('outputs', {}).get('7', {}).get('images')
            if imgs:
                return imgs[0]
        time.sleep(POLL_S)
    raise TimeoutError('ComfyUI render timed out after %d s' % RENDER_TIMEOUT_S)


def render(job, cfg):
    """-> VARIANTS (frame, png) pairs for the job."""
    from PIL import Image
    text = faces.STYLE.format(who=job.get('prompt') or 'a veteran player')
    name = None
    if job.get('image'):
        name = _upload(cfg, 'studio_%s.png' % job['id'], base64.b64decode(job['image']))
    base = random.randrange(2 ** 31)
    out = []
    for k in range(VARIANTS):
        if name is None:
            wf = faces._workflow(text, base + k)
        else:
            wf = img2img_graph(text, base + k, name)
        pid = json.loads(_comfy(cfg, '/prompt', json.dumps({'prompt': wf}).encode()))['prompt_id']
        img = _await(cfg, pid)
        q = urllib.parse.urlencode({key: img.get(key, '') for key in ('filename', 'subfolder', 'type')})
        im = Image.open(io.BytesIO(_comfy(cfg, '/view?' + q))).convert('RGB')
        frame = faces.to_frame(im)
        out.append((frame, faces.preview_png(frame)))
    return out


def _b64(b):
    return base64.b64encode(b).decode()


def _free(cfg):
    try:
        _comfy(cfg, '/free', json.dumps({'unload_models': True, 'free_memory': True}).encode())
    except (OSError, RuntimeError) as e:
        log('free failed: %s' % e)


def run_once(cfg):
    """One pass: 'busy' (GPU in use, queue left alone), 'idle' (queue empty), 'done' or 'failed'."""
    if faces.owner_busy():
        return 'busy'
    job = claim(cfg)
    if job is None:
        return 'idle'
    log('job %s: %s' % (job['id'], 'img2img' if job.get('image') else 'txt2img'))
    state = 'done'
    try:
        body = {'variants': [{'frame': _b64(f), 'png': _b64(p)} for f, p in render(job, cfg)]}
    except Exception as e:                  # every render failure goes to the site as the job's error
        state = 'failed'
        body = {'error': ('%s: %s' % (type(e).__name__, e))[:200]}
        log('job %s failed: %s' % (job['id'], body['error']))
    try:
        deliver(cfg, job['id'], body)
    finally:
        _free(cfg)
    log('job %s %s' % (job['id'], state))
    return state


def main():
    cfg = load_cfg()
    log('studio worker up: site %s, comfy %s' % (cfg['url'], cfg['comfy']))
    while True:
        try:
            state = run_once(cfg)
        except (OSError, ValueError, http.client.HTTPException) as e:
            log('network error: %s' % e)
            time.sleep(ERR_S)
            continue
        if state == 'busy':
            time.sleep(BUSY_S)
        elif state == 'idle':
            time.sleep(IDLE_S)


if __name__ == '__main__':
    main()
