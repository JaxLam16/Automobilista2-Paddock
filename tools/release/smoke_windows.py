"""Verify the ZIP and run its EXE in isolation with no Python on PATH."""
import argparse
import base64
from datetime import datetime
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import time
import uuid
from urllib.parse import quote
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path)
    args = parser.parse_args()
    release = args.release.resolve()
    if not release.is_relative_to(ROOT / 'releases'):
        raise ValueError('Choose a release inside this workspace releases directory.')
    zipped = release.with_name(release.name + '.zip')
    expected = zipped.with_suffix('.zip.sha256').read_text().split()[0]
    assert digest(zipped) == expected, 'ZIP checksum mismatch'
    stage = ROOT / 'build' / ('smoke-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    stage.mkdir(parents=True)
    with zipfile.ZipFile(zipped) as archive:
        assert archive.testzip() is None, 'Corrupt ZIP entry'
        for name in archive.namelist():
            path = (stage / name).resolve()
            assert path.is_relative_to(stage), 'Unsafe ZIP path'
        archive.extractall(stage)
    portable = stage / release.name
    manifest = json.loads((portable / 'FILE_MANIFEST.json').read_text())
    actual = {p.relative_to(portable).as_posix() for p in portable.rglob('*') if p.is_file()}
    assert actual == set(manifest) | {'FILE_MANIFEST.json'}, 'Unexpected payload file'
    for name, sha in manifest.items():
        assert digest(portable / name) == sha, 'Payload checksum mismatch: ' + name
    assert set(p.name for p in portable.iterdir()) == {
        'AMS2 Paddock.exe', '_internal', 'docs', 'README.md', 'THIRD_PARTY_NOTICES',
        'BUILD_INFO.json', 'FILE_MANIFEST.json'}
    assert not any(p.suffix in ('.parquet', '.db', '.bff', '.vdf', '.hdt', '.hdv') for p in portable.rglob('*'))
    # Deliberately disable live recording so this smoke test cannot capture the user's game.
    (portable / 'ams2season.json').write_text(json.dumps({
        'autostart_recorder': False, 'driver_label': 'Alpha Test Driver'}), encoding='utf-8')
    env = dict(os.environ)
    windows = Path(env.get('SystemRoot', r'C:\Windows'))
    env['PATH'] = str(windows / 'System32') + os.pathsep + str(windows)
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    elsewhere = stage / 'different-working-directory'
    elsewhere.mkdir()
    executable = portable / 'AMS2 Paddock.exe'
    report = {'zip_sha256': expected, 'payload_files_verified': len(manifest),
              'python_on_path': False, 'personal_data_in_payload': False, 'checks': []}

    def launch():
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        process = subprocess.Popen([str(executable), '--no-window', '--port', str(port)],
                                   cwd=elsewhere, env=env)
        return process, port

    def call(port, method, path, body=None, expected_status=200):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=90)
        try:
            connection.request(method, path, body=json.dumps(body) if body is not None else None,
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            data = response.read()
            assert response.status == expected_status, (path, response.status, data[:1000])
            return json.loads(data) if 'application/json' in response.getheader('Content-Type', '') else data
        finally:
            connection.close()

    def ready(process, port):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            startup_log = portable / 'startup-error.log'
            if startup_log.exists():
                raise RuntimeError(startup_log.read_text(encoding='utf-8'))
            if process.poll() is not None:
                raise RuntimeError(f'Frozen app exited with {process.returncode}')
            try:
                return call(port, 'GET', '/api/ping')
            except (ConnectionError, OSError):
                time.sleep(.25)
        raise TimeoutError('Frozen app did not start; check extracted startup-error.log')

    def close(process, port):
        call(port, 'POST', '/api/heartbeat', {})
        call(port, 'POST', '/api/closing', {})
        assert process.wait(timeout=35) == 0, 'App shutdown failed'

    process = None
    try:
        print('ZIP integrity and payload isolation passed; starting portable EXE.', flush=True)
        process, port = launch()
        assert ready(process, port)['version'] == json.loads((portable / 'BUILD_INFO.json').read_text())['version']
        settings = call(port, 'GET', '/api/settings')
        assert Path(settings['root']) == portable
        assert call(port, 'GET', '/api/recordings')['recordings'] == []
        assert call(port, 'GET', '/api/home')['total_recordings'] == 0
        assert not call(port, 'GET', '/api/recorder')['running']
        for path in ('/', '/bop-editor.js', '/bop-editor.css', '/livery-editor.js',
                     '/livery-editor.css', '/development-ui.js', '/development-ui.css',
                     '/replay-timing.js', '/identity-ui.js', '/favicon.ico'):
            assert len(call(port, 'GET', path)) > 50
        for path in ('/api/car-icons', '/api/engineer', '/api/bop', '/api/bop/config',
                     '/api/bop/car-setups', '/api/liveries', '/api/identities/catalog', '/api/tracks'):
            call(port, 'GET', path)
        scan_guard = call(port, 'GET', '/api/bop/class-sets', expected_status=400)
        assert 'scan' in scan_guard['error'].lower()
        report['checks'].extend(['fresh start', 'default root beside EXE from another working directory',
                                 'all UI assets', 'lazy editor/engineer imports', 'empty personal data'])
        print('Fresh startup, UI assets and editor APIs passed.', flush=True)
        close(process, port)
        process = None
        print('Creating synthetic recording with the frozen EXE.', flush=True)
        synthetic = subprocess.Popen([str(executable), 'simulate', '--out', str(portable / 'recordings'),
                                      '--races', '1', '--humans', 'AlphaOne,AlphaTwo'], cwd=elsewhere, env=env)
        try:
            assert synthetic.wait(timeout=120) == 0, 'Frozen simulation failed'
        finally:
            if synthetic.poll() is None:
                synthetic.kill()
                synthetic.wait()
        process, port = launch()
        ready(process, port)
        recordings = call(port, 'GET', '/api/recordings')['recordings']
        race = next(record for record in recordings if record['type'] == 'race')
        recording = quote(race['id'])
        assert len(call(port, 'GET', '/report?recording=' + recording)) > 1000
        for path in ('/api/replay', '/api/technique', '/api/tyres', '/api/pace', '/api/style'):
            call(port, 'GET', path + '?recording=' + recording)
        cid = call(port, 'POST', '/api/championships', {'name': 'Alpha Smoke Championship'})['id']
        call(port, 'PUT', '/api/championships/' + cid,
             {'drivers': [{'display': name, 'aliases': ''} for name in ('AlphaOne', 'AlphaTwo')]})
        call(port, 'POST', '/api/championships/' + cid + '/rounds',
             {'recording': race['id'], 'round': 1})
        detail = call(port, 'GET', '/api/championships/' + cid)
        assert len(detail['rounds']) == 1
        report['checks'].extend(['frozen simulation / Parquet write and read',
                                 'relaunch and recording persistence', 'race report and replay',
                                 'technique / pace / tyres / style', 'championship create and ingest'])
        close(process, port)
        process = None
        # Historical identities must work without the game/catalog on a tester's PC.
        # Seed only synthetic roster metadata, then exercise the frozen API itself.
        db = portable / 'championships' / (cid + '.db')
        meta = json.loads((portable / 'recordings' / race['id'] / 'session.json').read_text())
        bot = next(e for e in meta['final'] if e['name'] not in ('AlphaOne', 'AlphaTwo'))
        human = next(e for e in meta['final'] if e['name'] == 'AlphaOne')
        from PIL import Image
        preview = io.BytesIO()
        Image.new('RGB', (20, 10), '#D33E38').save(preview, format='PNG')
        binding = {'car_id': 'smoke-car', 'livery_id': '1', 'recorded_car': bot['car'],
                   'car_name': bot['car'], 'livery_name': 'Historical smoke livery',
                   'preview': base64.b64encode(preview.getvalue()).decode('ascii'), 'color': '#D33E38'}
        human_binding = dict(binding, livery_id='2', recorded_car=human['car'],
                             livery_name='Human smoke livery', color_override='#0088FF')
        with sqlite3.connect(db) as con:
            cfg = json.loads(con.execute("SELECT value FROM meta WHERE key='config'").fetchone()[0])
            cfg['drivers'].append({'key': 'alpha-ai', 'display': 'Alpha Fictional AI', 'role': 'ai', 'aliases': [], 'livery': binding})
            next(d for d in cfg['drivers'] if d['display'] == 'AlphaOne')['livery'] = human_binding
            cfg.update(livery_ai=True, ai_policy='full_field', car_class='GT3 Gen 0')
            con.execute("UPDATE meta SET value=? WHERE key='config'", (json.dumps(cfg),))
        process, port = launch()
        ready(process, port)
        call(port, 'PUT', '/api/championships/' + cid, {'drivers': cfg['drivers'], 'car_class': cfg['car_class']})
        query = '?recording=' + recording + '&champ=' + cid
        review = call(port, 'GET', '/api/identities' + query)
        bot_id = next(e['id'] for e in review['entrants'] if e['name'] == bot['name'])
        human_id = next(e['id'] for e in review['entrants'] if e['name'] == 'AlphaOne')
        assert review['car_class'] == 'GT3 Gen 0'
        original = portable / 'recordings' / race['id']
        before = {name: digest(original / name) for name in ('session.json', 'frames.parquet', 'local.parquet', 'events.jsonl')}
        fact = dict(binding, name=bot['name'])
        human_fact = dict(human_binding, name='AlphaOne')
        revision = uuid.uuid4().hex
        (original / 'livery_assignments.json').write_text(json.dumps({'version': 1, 'reviewed': True,
            'revision': revision, 'assignments': {bot_id: fact, human_id: human_fact}}))
        assert call(port, 'GET', '/api/identities' + query)['reviewed']
        assert b'Alpha Fictional AI' in call(port, 'GET', '/report' + query)
        call(port, 'POST', '/api/identities', {'recording': race['id'], 'champ': cid, 'revision': revision,
             'assignments': {bot_id: fact, human_id: human_fact}})
        detail = call(port, 'GET', '/api/championships/' + cid)
        assert any(r['driver'] == 'Alpha Fictional AI' and r['is_ai'] for r in detail['standings']['full_field']['rows'])
        assert all(r['driver'] != 'Alpha Fictional AI' for r in detail['standings']['humans_only']['rows'])
        assert detail['config']['car_class'] == 'GT3 Gen 0'
        assert next(d for d in detail['config']['drivers'] if d['display'] == 'AlphaOne')['role'] == 'human'
        replay = call(port, 'GET', '/api/replay' + query)
        for name, color, ai in [('AlphaOne', '#0088FF', False), ('Alpha Fictional AI', '#D33E38', True)]:
            driver = next(d for d in replay['drivers'] if d['name'] == name)
            assert driver['color'] == color and driver['is_ai'] == ai
            assert driver['livery']['image'].startswith('data:image/png;base64,')
        assert before == {name: digest(original / name) for name in before}
        close(process, port)
        process = None
        report['checks'].extend(['persistent livery AI without an installed game', 'fictional AI full-field points / human-only separation',
                                 'human livery persistence / embedded pictures / replay color override', 'championship car-class persistence',
                                 'frozen assignment save and raw-recording hash preservation', 'graceful shutdown after all launches'])
        report['passed'] = True
    except Exception as exc:
        report['passed'] = False
        report['error'] = str(exc)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        report['test_data'] = str(stage)
        report_path = release.with_name(release.name + '.verification.json')
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
