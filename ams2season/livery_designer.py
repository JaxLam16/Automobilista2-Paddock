"""Paddock integration for the supplied 3D livery designer, on the app's HTTP server."""
from contextlib import nullcontext
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path
import threading
from urllib.parse import unquote, urlparse, parse_qs

from .liveries import _game_running, _json_write, rcf_liveries
from .bff import path_uid

PREFIX = '/livery-designer/'
WEB = Path(__file__).parent / 'designer' / 'web'
GAME_WRITES = {'/api/install', '/api/preview', '/api/restore'}


class _FailedSave(Exception):
    pass


class _Transport:
    """The imported endpoints return their response before Paddock sends it."""
    def __init__(self, headers, body):
        self.headers, self.rfile = headers, io.BytesIO(body)
        self.response = None

    def _send(self, code, body, ctype):
        self.response = code, body, ctype


class LiveryDesigner:
    def __init__(self, app):
        self.app = app
        self.root = app.lib.root / 'livery_designer'
        self.lock = threading.RLock()
        self._game = self._endpoints = None

    def game_path(self):
        config = self.root / 'settings.json'
        own = json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
        return own.get('game_path') or self.app.liveries.config.get('game_path') or ''

    def status(self):
        from .designer.game import Game, find_game
        path = self.game_path()
        cars, error = [], None
        if path:
            try:
                cars = Game(path).cars()
            except (OSError, ValueError) as exc:
                error = str(exc)
        return {'game_path': path, 'suggestion': find_game() or '', 'ready': bool(path) and error is None,
                'cars': len(cars), 'error': error, 'projects_dir': str(self.root / 'projects'),
                'decals_dir': str(self.root / 'decals')}

    def configure(self, body):
        from .designer.game import Game
        value = str(body.get('game_path') or '').strip().strip('"')
        if not value:
            raise ValueError('Choose your Automobilista 2 installation folder.')
        game = Game(str(Path(value).expanduser().resolve()))
        with self.lock:
            _json_write(self.root / 'settings.json', {'game_path': game.root})
            self._game = self._endpoints = None
        return self.status()

    def endpoints(self):
        from .designer.game import Game
        from .designer.endpoints import make_endpoints
        path = self.game_path()
        if not path:
            raise ValueError('Choose the game folder in Livery designer first.')
        if self._game is None or self._game.root != str(Path(path).resolve()):
            self._game = Game(path)
            self._endpoints = make_endpoints(self._game, self.root)
        self._game.refresh()
        return self._endpoints

    def _check_restrictions(self, relative):
        q = {k: v[0] for k, v in parse_qs(urlparse(relative).query).items()}
        cars = {c.id: c for c in self._game.cars()}
        selected = [cars[q['car']]] if q.get('car') in cars else list(cars.values())
        ident = hashlib.sha256(os.path.normcase(self._game.root).encode()).hexdigest()[:20]
        catalog = self.app.liveries.root / 'installs' / ident / 'catalog'
        for car in selected:
            for path in car.rcfs:
                canonical = Path(path).relative_to(self._game.root).as_posix().lower()
                baseline = catalog / (format(path_uid(canonical), '016x') + '.rcf')
                if baseline.exists():
                    old = {e['id'] for e in rcf_liveries(baseline.read_bytes())}
                    current = {e['id'] for e in rcf_liveries(Path(path).read_bytes())}
                    if old - current:
                        raise ValueError('Enable all liveries for ' + car.name + ' in Livery editor before saving a design to the game.')

    def handle(self, method, relative, headers=None, body=b''):
        """Return (status, bytes, content-type); never start a second server."""
        path = unquote(urlparse(relative).path)
        if path.startswith('/vendor/'):
            file = (WEB / path.lstrip('/')).resolve()
            if method != 'GET' or not file.is_relative_to(WEB.resolve()) or not file.is_file():
                raise LookupError('Designer asset not found.')
            return 200, file.read_bytes(), mimetypes.guess_type(file)[0] or 'application/octet-stream'
        if path in ('/', '/editor', '/viewer') or path.startswith('/editor/'):
            name = 'editor/index.html' if path in ('/', '/editor') else 'index.html' if path == '/viewer' else path.lstrip('/')
            file = (WEB / name).resolve()
            if method != 'GET' or not file.is_relative_to(WEB.resolve()) or not file.is_file():
                raise LookupError('Designer asset not found.')
            return 200, file.read_bytes(), mimetypes.guess_type(file)[0] or 'application/octet-stream'
        if method not in ('GET', 'POST'):
            raise LookupError('Unknown designer request.')
        with self.lock, self.app.liveries.lock:
            endpoints = self.endpoints()
            writes = method == 'POST' and path in GAME_WRITES
            if writes:
                if _game_running():
                    raise ValueError('Close Automobilista 2 before saving a livery to the game.')
                self._check_restrictions(relative)
            from .designer.transaction import Transaction
            transport = _Transport(headers or {}, body)
            transport.headers = dict(transport.headers, **{'Content-Length': str(len(body))})
            try:
                with Transaction(self._game, self.root / 'cache') if writes else nullcontext():
                    endpoint = endpoints(transport, relative)
                    (endpoint.do_GET if method == 'GET' else endpoint.do_POST)()
                    if transport.response is None:
                        raise RuntimeError('Designer did not return a response.')
                    if writes and transport.response[0] >= 400:
                        raise _FailedSave()
            except _FailedSave:
                pass
            if writes and transport.response[0] < 400:
                editor = self.app.liveries
                editor.prepared.clear()
                editor.preview_cache.clear()
                editor.preview_archives.clear()
                if editor.game and editor.game.resolve() == Path(self._game.root):
                    editor.game = None
                    editor.cars.clear()
            return transport.response
