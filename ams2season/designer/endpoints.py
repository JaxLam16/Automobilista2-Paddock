"""Local web server for the livery editor and viewer (python livery_tool.py edit)."""
import hashlib
import json
import mimetypes
import os
import re
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
import shutil

from PIL import Image

from . import dds, decals, install, model
from .template import reference_size

PREVIEW_MAX = 2048
IMAGE_EXT = {'.png', '.svg', '.jpg', '.jpeg', '.webp'}
mimetypes.add_type('text/javascript', '.js')
mimetypes.add_type('image/svg+xml', '.svg')


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or '').strip(' .')
    return name[:80] or 'Untitled'


def inside(base, path):
    base, path = os.path.realpath(base), os.path.realpath(path)
    return path == base or path.startswith(base + os.sep)


def make_endpoints(game, data_root):
    WEB = str(Path(__file__).parent / 'web')
    DECALS = str(Path(data_root) / 'decals')
    PROJECTS = str(Path(data_root) / 'projects')
    CACHE = str(Path(data_root) / 'cache')
    for source in (Path(__file__).parent / 'decals').rglob('*'):
        target = Path(DECALS) / source.relative_to(Path(__file__).parent / 'decals')
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(os.path.join(DECALS, 'My decals'), exist_ok=True)
    os.makedirs(PROJECTS, exist_ok=True)
    lock, write_lock = threading.Lock(), threading.Lock()
    models, finish_cache = {}, {}

    def cars():
        return {c.id: c for c in game.cars()}

    def livery_png(car, lid, full=False):
        src = game.livery_file(car, lid)
        if not src:
            return None
        st = os.stat(src)
        key = hashlib.sha1(f'{src}|{st.st_mtime_ns}|{st.st_size}|{full}'.encode()).hexdigest()[:16]
        out = os.path.join(CACHE, key + '.png')
        if not os.path.exists(out):
            im = dds.load(src).convert('RGB')
            if not full and max(im.size) > PREVIEW_MAX:
                s = PREVIEW_MAX / max(im.size)
                im = im.resize((max(1, int(im.size[0] * s)), max(1, int(im.size[1] * s))), Image.LANCZOS)
            tmp = out + f'.{threading.get_ident()}.tmp.png'
            im.save(tmp, compress_level=1)
            os.replace(tmp, out)
        return out

    def finish_support(car):
        key = (car.id, os.stat(car.rcfs[0]).st_mtime_ns)
        if key not in finish_cache:
            finish_cache[key] = install.finish_support(game, car)
        return finish_cache[key]

    def car_info(car):
        (w, h), _ = reference_size(game, car)
        mine = install.ours(game)
        table = car.liveries()
        return dict(id=car.id, name=car.name, width=w, height=h, next=max(table) + 1 if table else 1,
                    liveries=[dict(id=lid, name=lv['name'], ok=bool(lv['texture'] and game.resolve(lv['texture'])), ours=(car.id, lid) in mine)
                              for lid, lv in table.items()],
                    finish=finish_support(car))

    def decal_list():
        out = []
        for root, dirs, files in os.walk(DECALS):
            dirs.sort(key=str.lower)
            for f in sorted(files, key=str.lower):
                if os.path.splitext(f)[1].lower() in IMAGE_EXT:
                    rel = os.path.relpath(os.path.join(root, f), DECALS).replace(os.sep, '/')
                    cat = os.path.dirname(rel) or 'Other'
                    out.append(dict(name=os.path.splitext(f)[0].replace('_', ' '), category=cat,
                                    url='decals/' + urllib.parse.quote(rel), thumb='thumb/' + urllib.parse.quote(rel)))
        order = {'My decals': 0}
        out.sort(key=lambda d: (order.get(d['category'], 1), d['category'].lower(), d['name'].lower()))
        return out

    def project_list(car_id=None):
        out, names = [], {}
        for cid in sorted(os.listdir(PROJECTS)) if os.path.isdir(PROJECTS) else []:
            d = os.path.join(PROJECTS, cid)
            if not os.path.isdir(d) or (car_id and cid != car_id):
                continue
            for f in os.listdir(d):
                if f.endswith('.json'):
                    if not names:
                        try:
                            names.update({c.id: c.name for c in game.cars()})
                        except OSError:
                            pass
                    out.append(dict(car=cid, carName=names.get(cid, cid), name=f[:-5], modified=os.path.getmtime(os.path.join(d, f))))
        return sorted(out, key=lambda p: -p['modified'])

    class Endpoints:
        def __init__(self, transport, path):
            self.transport, self.path = transport, path
            self.headers, self.rfile = transport.headers, transport.rfile

        def log_message(self, *a):
            pass

        def send(self, body, ctype='application/json', code=200, cache=False):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            self.transport._send(code, body, ctype)

        def send_file(self, path, cache=False):
            ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype.endswith('javascript'):
                ctype += '; charset=utf-8'
            with open(path, 'rb') as file:
                return self.send(file.read(), ctype, cache=cache)

        def body(self):
            n = int(self.headers.get('Content-Length') or 0)
            if n < 0 or n > 512 << 20:
                raise ValueError('Upload must be at most 512 MB.')
            chunks, left = [], n
            while left > 0:
                c = self.rfile.read(min(left, 8 << 20))
                if not c:
                    raise IOError('upload was cut short')
                chunks.append(c)
                left -= len(c)
            return b''.join(chunks)

        def route(self):
            u = urllib.parse.urlparse(self.path)
            parts = [urllib.parse.unquote(p) for p in u.path.strip('/').split('/') if p]
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            return parts, q

        def do_GET(self):
            parts, q = self.route()
            try:
                if not parts or parts == ['editor']:
                    return self.send_file(os.path.join(WEB, 'editor', 'index.html'))
                if parts == ['viewer']:
                    return self.send_file(os.path.join(WEB, 'index.html'))
                if parts[0] == 'editor' and len(parts) == 2:
                    path = os.path.join(WEB, 'editor', parts[1])
                    if inside(os.path.join(WEB, 'editor'), path) and os.path.isfile(path):
                        return self.send_file(path)
                if parts[0] == 'decals' and len(parts) > 1:
                    path = os.path.join(DECALS, *parts[1:])
                    if inside(DECALS, path) and os.path.isfile(path):
                        return self.send_file(path, cache=True)
                if parts[0] == 'thumb' and len(parts) > 1:              # small previews for the library grid
                    path = os.path.join(DECALS, *parts[1:])
                    if inside(DECALS, path) and os.path.isfile(path):
                        if path.lower().endswith('.svg'):
                            return self.send_file(path, cache=True)
                        try:
                            return self.send_file(decals.thumbnail(path, CACHE), cache=True)
                        except Exception:
                            return self.send_file(path, cache=True)
                if parts == ['api', 'cars']:
                    return self.send([dict(id=c.id, name=c.name, folder=c.folder_name, pack=c.pack) for c in cars().values()])
                if parts[:2] == ['api', 'car'] and len(parts) == 3:
                    car = cars()[parts[2]]
                    with lock:
                        key = (car.id, os.stat(car.vhf).st_mtime_ns)
                        if key not in models:
                            models[key] = json.dumps(model.viewer_json(game, car)).encode()
                    return self.send(models[key])
                if parts[:2] == ['api', 'info'] and len(parts) == 3:
                    return self.send(car_info(cars()[parts[2]]))
                if parts[:2] == ['api', 'liveries'] and len(parts) == 3:
                    car = cars()[parts[2]]
                    return self.send([dict(id=lid, name=lv['name'], ok=bool(lv['texture'] and game.resolve(lv['texture'])))
                                      for lid, lv in car.liveries().items()])
                if parts[:2] == ['api', 'livery'] and len(parts) == 4:
                    car = cars()[parts[2]]
                    png = livery_png(car, int(parts[3].split('.')[0]), full=q.get('full') == '1')
                    if not png:
                        return self.send({'error': 'texture not found'}, code=404)
                    return self.send_file(png)
                if parts == ['api', 'decals']:
                    return self.send(decal_list())
                if parts == ['api', 'missing']:
                    return self.send(install.missing(game))
                if parts == ['api', 'projects']:
                    return self.send(project_list(q.get('car')))
                if parts == ['api', 'project']:
                    path = os.path.join(PROJECTS, safe_name(q['car']), safe_name(q['name']) + '.json')
                    if not inside(PROJECTS, path):
                        raise ValueError('Invalid project path.')
                    if not os.path.isfile(path):
                        return self.send({'error': 'project not found'}, code=404)
                    return self.send_file(path)
                self.send({'error': 'not found'}, code=404)
            except KeyError as e:
                self.send({'error': f'unknown {e}'}, code=404)
            except Exception as e:                       # keep the server alive; show the problem in the page
                self.send({'error': f'{type(e).__name__}: {e}'}, code=500)

        def do_POST(self):
            parts, q = self.route()
            try:
                data = self.body()
                if parts == ['api', 'install']:
                    car = cars()[q['car']]
                    w, h = int(q['width']), int(q['height'])
                    if not (0 < w <= 8192 and 0 < h <= 8192):
                        raise ValueError('Image dimensions must be between 1 and 8192.')
                    n = w * h * 4
                    if len(data) not in (n, 2 * n):
                        return self.send({'error': f'expected {n} or {2 * n} bytes, got {len(data)}'}, code=400)
                    spec = data[n:] if len(data) == 2 * n and q.get('finish') == '1' else None
                    with write_lock:
                        res = install.install_pixels(game, car, data[:n], w, h, q.get('name') or 'My livery',
                                                     int(q['slot']) if q.get('slot') else None, spec)
                    print(f'{res["action"].capitalize()} livery {res["slot"]} "{res["name"]}" on {car.name}'
                          f'{" with finish map" if res["finish"] else ""}. Backup: {res["backup"]}')
                    res['size'] = list(res['size'])
                    return self.send(res)
                if parts == ['api', 'preview']:
                    car = cars()[q['car']]
                    w, h = int(q['width']), int(q['height'])
                    if not (0 < w <= 8192 and 0 < h <= 8192):
                        raise ValueError('Image dimensions must be between 1 and 8192.')
                    if len(data) != w * h * 4:
                        return self.send({'error': f'expected {w * h * 4} bytes, got {len(data)}'}, code=400)
                    with write_lock:
                        path = install.write_preview(game, car, int(q['slot']), data, w, h)
                    return self.send({'ok': True, 'path': path})
                if parts == ['api', 'restore']:
                    with write_lock:
                        entries = json.loads(data)
                        trusted = {(e['car'], e['slot']): e for e in install.missing(game)}
                        selected = []
                        for entry in entries:
                            key = (entry.get('car'), entry.get('slot'))
                            if key not in trusted:
                                raise ValueError('This livery is no longer available to restore. Refresh the list.')
                            selected.append(trusted[key])
                        res = install.restore(game, selected)
                    for r in res['restored']:
                        print(f'Put back "{r["name"]}" on {r["carName"]} as livery {r["slot"]} (was {r["old"]})')
                    return self.send(res)
                if parts == ['api', 'project']:
                    d = os.path.join(PROJECTS, safe_name(q['car']))
                    if not inside(PROJECTS, d):
                        raise ValueError('Invalid project path.')
                    os.makedirs(d, exist_ok=True)
                    document = json.loads(data)
                    if not isinstance(document, dict) or document.get('car') != q['car']:
                        raise ValueError('Project must match the selected car.')
                    json.loads(data)                     # refuse to store anything that isn't valid JSON
                    path = os.path.join(d, safe_name(q['name']) + '.json')
                    tmp = path + '.tmp'
                    open(tmp, 'wb').write(data)
                    os.replace(tmp, path)
                    return self.send({'ok': True, 'path': path})
                if parts == ['api', 'decals', 'import']:
                    res = decals.import_zip(data, q.get('name') or 'Imported', DECALS)
                    note = f' ({len(res["skipped"])} files skipped)' if res['skipped'] else ''
                    print(f'Imported {res["added"]} logos into decals\\{res["folder"]}{note}')
                    return self.send(res)
                if parts == ['api', 'decals', 'open']:
                    if not hasattr(os, 'startfile'):
                        return self.send({'error': 'only available on Windows'}, code=400)
                    os.startfile(DECALS)
                    return self.send({'ok': True})
                if parts == ['api', 'decals']:
                    name = safe_name(q.get('name'))
                    Image.open(__import__('io').BytesIO(data)).verify()
                    path = os.path.join(DECALS, 'My decals', name + '.png')
                    if os.path.exists(path):
                        path = os.path.join(DECALS, 'My decals', f'{name} {time.strftime("%H%M%S")}.png')
                    open(path, 'wb').write(data)
                    return self.send({'ok': True})
                self.send({'error': 'not found'}, code=404)
            except PermissionError as e:
                self.send({'error': f'{e}. A game file is locked: close Automobilista 2 and try again.'}, code=500)
            except ValueError as e:
                self.send({'error': str(e)}, code=400)
            except KeyError as e:
                self.send({'error': f'unknown {e}'}, code=404)
            except Exception as e:
                self.send({'error': f'{type(e).__name__}: {e}'}, code=500)

    return Endpoints
