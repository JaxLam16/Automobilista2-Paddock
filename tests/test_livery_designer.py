"""Designer integration: portable assets, projects, game saves and rollback."""
import hashlib
import http.client
import io
import json
from pathlib import Path
import struct
import threading

import pytest
from PIL import Image

from ams2season.app import App, _make_server, make_handler
from ams2season.bff import path_uid
from ams2season.designer import dds, install, model, rcf
from ams2season.designer.game import Game


from tools.release.designer_fixture import synthetic_game


def test_close_request_with_same_clock_tick_as_heartbeat_exits(tmp_path, monkeypatch):
    app = App(tmp_path)
    monkeypatch.setattr('ams2season.app.time.monotonic', lambda: 100.0)
    app.route('POST', '/api/heartbeat', {}, {})
    app.route('POST', '/api/closing', {}, {})
    monkeypatch.setattr('ams2season.app.time.monotonic', lambda: 116.0)
    assert app.should_quit()
    app.route('POST', '/api/heartbeat', {}, {})
    assert not app.should_quit()  # reload cancels the close
    app.route('POST', '/api/closing', {}, {})
    monkeypatch.setattr('ams2season.app.time.monotonic', lambda: 132.0)
    monkeypatch.setattr(app.recorder, 'status', lambda: {'state': 'recording'})
    assert not app.should_quit()  # never end an active recording

@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.setattr('ams2season.livery_designer._game_running', lambda: False)
    game = synthetic_game(tmp_path / 'game')
    (tmp_path / 'paddock').mkdir()
    app = App(tmp_path / 'paddock')
    app.liveries.config['game_path'] = game.root
    return app, game


def call(scene, method, path, body=b''):
    code, data, ctype = scene[0].livery_designer.handle(method, path, {}, body)
    return code, json.loads(data) if ctype == 'application/json' else data


def save(scene, slot=None, name='Paint & Racing'):
    query = '/api/install?car=sample&width=64&height=64&name=' + __import__('urllib.parse', fromlist=['quote']).quote(name)
    if slot is not None:
        query += '&slot=' + str(slot)
    return call(scene, 'POST', query, bytes([200, 40, 30, 255]) * 64 * 64)


def test_shared_game_setting_and_synthetic_model(scene):
    app, game = scene
    assert app.livery_designer.status()['cars'] == 1
    assert not (app.livery_designer.root / 'settings.json').exists()
    assert call(scene, 'GET', '/api/cars')[1][0]['name'] == 'Synthetic car'
    data = model.viewer_json(game, game.cars()[0])
    assert len(data['parts']) == 1 and data['parts'][0]['groups'][0]['material'] == 'PAINT'
    assert call(scene, 'GET', '/api/info/sample')[1]['width'] == 64


def test_assets_are_offline_and_separate_from_game_configuration(tmp_path):
    app = App(tmp_path)
    code, html, _ = app.livery_designer.handle('GET', '/')
    assert code == 200 and b'cdn.jsdelivr.net' not in html
    assert b'/livery-designer/vendor/three/' in html
    for path in ('/editor/app.js', '/editor/engine.js', '/editor/stamps.js', '/vendor/three/build/three.module.js', '/vendor/three-mesh-bvh/build/index.module.js'):
        assert app.livery_designer.handle('GET', path)[0] == 200
    with pytest.raises(LookupError):
        app.livery_designer.handle('GET', '/vendor/../../../../../ams2season.json')
    assert not app.livery_designer.root.exists()


def test_projects_and_imported_decals_persist_without_changing_game(scene):
    app, game = scene
    before = {p: p.read_bytes() for p in Path(game.root).rglob('*') if p.is_file()}
    doc = {'version': 1, 'car': 'sample', 'name': 'My design', 'layers': []}
    assert call(scene, 'POST', '/api/project?car=sample&name=My%20design', json.dumps(doc).encode())[0] == 200
    assert call(scene, 'GET', '/api/project?car=sample&name=My%20design')[1] == doc
    image = io.BytesIO(); Image.new('RGB', (4, 4), 'red').save(image, 'PNG')
    assert call(scene, 'POST', '/api/decals?name=Custom', image.getvalue())[0] == 200
    assert any(d['name'] == 'Custom' for d in call(scene, 'GET', '/api/decals')[1])
    assert all(p.read_bytes() == raw for p, raw in before.items())
    fresh = App(app.lib.root); fresh.liveries.config['game_path'] = game.root
    assert call((fresh, game), 'GET', '/api/projects')[1][0]['name'] == 'My design'
    assert call(scene, 'POST', '/api/project?car=sample&name=Bad', b'[]')[0] == 400


def test_save_add_update_picture_and_unique_original_backups(scene):
    app, game = scene
    folder = Path(game.root) / 'Vehicles/sample'
    originals = {p: p.read_bytes() for p in folder.glob('*.rcf')}
    app.liveries.prepared['stale'] = {}
    code, added = save(scene)
    assert code == 200 and added['slot'] == 2
    assert not app.liveries.prepared
    for path, raw in originals.items():
        assert rcf.liveries(path.read_text())[2]['name'] == 'Paint & Racing'
        assert 'TIRE="1"' in path.read_text()
        assert (Path(added['backup']) / path.relative_to(game.root)).read_bytes() == raw
    code, updated = save(scene, 2, 'Updated')
    assert code == 200 and updated['backup'] != added['backup']
    assert dds.info(updated['texture'])['mips'] == 7
    rgba = bytes([50, 100, 150, 255]) * 4 * 4
    code, preview = call(scene, 'POST', '/api/preview?car=sample&slot=2&width=4&height=4', rgba)
    assert code == 200 and dds.info(preview['path'])['width'] == 2048
    assert install.ours(game) == {('sample', 2)}


@pytest.mark.parametrize('slot', [None, 1])
def test_manifest_failure_rolls_back_every_changed_game_file(scene, monkeypatch, slot):
    _, game = scene
    before = {p: p.read_bytes() for p in Path(game.root).rglob('*') if p.is_file()}
    def fail(*args, **kwargs):
        raise OSError('Injected manifest failure')
    if slot is None:
        monkeypatch.setattr(install, '_manifest', fail)
    else:
        monkeypatch.setattr(install, 'write_rcfs', fail)
    code, result = save(scene, slot)
    assert code == 500 and 'Injected' in result['error']
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert not (Path(game.root) / 'Vehicles/sample/paint_2.dds').exists()


def test_bad_hr_blocks_save_before_texture_write(scene):
    _, game = scene
    hr = Path(game.root) / 'Vehicles/sample/sample_hr.rcf'
    hr.write_bytes(b'<broken>')
    original = (hr.parent / 'sample.rcf').read_bytes()
    assert save(scene)[0] == 400
    assert (hr.parent / 'sample.rcf').read_bytes() == original
    assert not (hr.parent / 'paint_2.dds').exists()


def test_game_running_and_restricted_liveries_block_writes(scene, monkeypatch):
    app, game = scene
    monkeypatch.setattr('ams2season.livery_designer._game_running', lambda: True)
    with pytest.raises(ValueError, match='Close Automobilista'):
        save(scene)
    monkeypatch.setattr('ams2season.livery_designer._game_running', lambda: False)
    ident = hashlib.sha256(__import__('os').path.normcase(game.root).encode()).hexdigest()[:20]
    catalog = app.liveries.root / 'installs' / ident / 'catalog'
    catalog.mkdir(parents=True)
    original = (Path(game.root)/'Vehicles/sample/sample.rcf').read_text()
    baseline = rcf.add_slot(original, 2, 'Disabled', 'vehicles/sample/paint_2.dds', 1)
    (catalog / (format(path_uid('vehicles/sample/sample.rcf'), '016x')+'.rcf')).write_text(baseline)
    with pytest.raises(ValueError, match='Enable all liveries'):
        save(scene)


def test_path_escape_dimensions_and_forged_restore_rejected(scene):
    _, game = scene
    for path in ('../private.txt', '/private.txt', 'C:\\private.txt', 'vehicles/../../private.txt'):
        with pytest.raises(ValueError):
            game.resolve(path)
    code, result = call(scene, 'POST', '/api/install?car=sample&width=-4&height=-4', b'')
    assert code == 400 and 'dimensions' in result['error']
    assert call(scene, 'POST', '/api/restore', b'[{"car":"sample","slot":22,"texture":"../private.txt"}]')[0] == 400


def test_paddock_http_binary_upload_security_and_configuration(scene):
    app, game = scene
    server = _make_server(0, make_handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    def request(method, path, body=None, ctype='application/json', origin=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        headers = {'Content-Type': ctype}
        if origin:
            headers['Origin'] = origin
        connection.request(method, path, body, headers)
        response = connection.getresponse(); code, data = response.status, response.read()
        connection.close()
        return code, data
    try:
        assert request('GET', '/livery-designer/')[0] == 200
        assert request('GET', '/livery-designer/editor/app.js')[0] == 200
        assert request('GET', '/livery-designer/decals/Class%20badges/GT3.svg')[0] == 200
        assert request('GET', '/api/livery-designer')[0] == 200
        doc = json.dumps({'car': 'sample', 'layers': []}).encode()
        path = '/livery-designer/api/project?car=sample&name=HTTP'
        assert request('POST', path, doc, origin='https://elsewhere.example')[0] == 403
        assert request('POST', path, doc, ctype='text/plain')[0] == 415
        assert request('POST', path, doc, origin=f'http://127.0.0.1:{port}')[0] == 200
        assert request('POST', '/livery-designer/api/install?car=sample&width=64&height=64', bytes([10, 20, 30, 255])*64*64, ctype='application/octet-stream')[0] == 200
        assert request('POST', '/api/livery-designer', json.dumps({'game_path': game.root}))[0] == 200
        assert (app.livery_designer.root/'settings.json').exists()
    finally:
        server.shutdown(); server.server_close()
