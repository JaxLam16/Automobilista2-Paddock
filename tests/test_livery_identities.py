"""Real recording -> manual livery facts -> two independent championships."""
import base64
import hashlib
import http.client
import json
import io
import shutil
import threading
from types import SimpleNamespace

import pytest

from ams2season.app import App, _clean_drivers
from ams2season.identities import FILE, entrant_id, project_session, read, validate_roster
from ams2season.race import analyze_race
from ams2season.season import (SeasonConfig, add_correction, classified_races, connect,
                             ingest, race_points, save_config, standings, team_standings)
from ams2season.simulate import RaceScript, run_race

HUMANS = ['Jax', 'Mason']


@pytest.fixture(scope='module')
def recording(tmp_path_factory):
    root = tmp_path_factory.mktemp('identity-source')
    dirs = run_race(root, HUMANS, RaceScript(laps=3, n_ai=4, retire=(3, 2, 1500.0),
                                           disconnect=('Mason', 2, 900.0)), seed=41)
    return next(p for p in dirs if p.name.endswith('_race'))


class Catalog:
    config = {}

    def __init__(self, model):
        self.cars = {'gt3': SimpleNamespace(name=model, liveries=[{'id': '1', 'name': 'Red'}, {'id': '2', 'name': 'Blue'}]),
                     'other': SimpleNamespace(name='Other car', liveries=[{'id': '1', 'name': 'Other paint'}])}
        for key, car in self.cars.items():
            car.public = lambda key=key, car=car: {'id': key, 'name': car.name, 'class': 'GT3', 'liveries': car.liveries}

    def preview_image(self, car, livery):
        raise LookupError('This mod has no preview')


@pytest.fixture
def scene(tmp_path, recording):
    path = tmp_path / 'recordings' / recording.name
    shutil.copytree(recording, path)
    app = App(tmp_path)
    raw = analyze_race(path, humans=set(HUMANS))
    ai = raw.entrants[raw.entrants.is_ai].iloc[0]
    app._livery_editor = Catalog(ai.car)
    cid = app.lib.create_champ({'name': 'Fictional GT3'})
    roster = [{'display': h, 'aliases': [h.lower()]} for h in HUMANS] + [
        {'key': 'chris', 'display': 'Chris Lulham', 'role': 'ai',
         'livery': {'car_id': 'gt3', 'livery_id': '1', 'recorded_car': ai.car}},
        {'key': 'fred', 'display': 'Fred Example', 'role': 'ai',
         'livery': {'car_id': 'gt3', 'livery_id': '2', 'recorded_car': ai.car}}]
    app.route('PUT', '/api/championships/' + cid, {}, {'drivers': roster, 'livery_ai': True, 'ai_policy': 'full_field', 'fastest_lap_bonus': 0})
    hashes = {f: hashlib.sha256((path / f).read_bytes()).hexdigest()
              for f in ('session.json', 'frames.parquet', 'local.parquet', 'events.jsonl')}
    yield app, path, cid, ai, hashes
    assert hashes == {f: hashlib.sha256((path / f).read_bytes()).hexdigest() for f in hashes}


def assign(scene, paint='1', name=None):
    app, path, cid, ai, _ = scene
    review = app.identity_review(path.name, cid, detail=True)
    entrant = next(e for e in review['entrants'] if e['name'] == (name or ai['name']))
    body = {'recording': path.name, 'champ': cid, 'revision': review['revision'],
            'assignments': {entrant['id']: {'car_id': 'gt3', 'livery_id': paint, 'recorded_car': entrant['car']}}}
    return body, app.save_identity_review(body)


def test_roster_roles_are_backward_compatible_and_aliases_unique():
    cfg = SeasonConfig(drivers=[{'key': 'jax', 'display': 'Jax', 'aliases': ['Jackson']},
                                {'key': 'ai', 'display': 'Chris', 'role': 'ai'}])
    assert cfg.human_names() == {'jax', 'jackson'}
    assert cfg.alias_map()['chris'] == 'ai'
    assert SeasonConfig.from_json(cfg.to_json()).human_names() == cfg.human_names()
    with pytest.raises(ValueError, match='name or alias'):
        validate_roster(_clean_drivers([{'display': 'Jax', 'aliases': ['other']}, {'display': 'Other'}]))


def test_assignment_reopen_reports_points_profiles_and_human_ranks(scene):
    app, path, cid, ai, _ = scene
    assert not app.identity_review(path.name, cid)['reviewed']
    app.lib.add_round(cid, {'recording': path.name, 'round': 1})
    assign(scene)
    restored = App(app.lib.root)
    assert restored.identity_review(path.name, cid)['reviewed']
    ra = restored.lib._analysis(path.name, cid)[0]
    assert 'Chris Lulham' in set(ra.entrants.name)
    assert ra.entrants.set_index('name').loc['Chris Lulham', 'is_ai']
    assert ra.entrants.set_index('name').loc['Chris Lulham', 'recorded_name'] == ai['name']
    assert 'Chris Lulham' in restored.lib.race_report(path.name, cid)
    assert ai['name'] in restored.lib._analysis(path.name, None)[0].entrants.name.tolist()
    con = connect(app.lib._db(cid))
    try:
        cfg = app.lib.champ_config(cid)
        humans = standings(con, cfg, policy='humans_only')
        full = standings(con, cfg, policy='full_field')
        assert set(humans.driver) == set(HUMANS)
        assert set(full.driver) == set(HUMANS) | {'Chris Lulham'}
        assert full.set_index('driver').loc['Chris Lulham', 'is_ai']
        races = classified_races(con, cfg)
        assert races[races.driver == 'chris'].name.iat[0] == ai['name']
        assert sorted(races[~races.is_ai].human_rank) == [1, 2]
        cfg.teams = [{'key': 'ai-team', 'name': 'AI Team', 'members': ['chris']}]
        assert team_standings(con, cfg, policy='full_field').points.iat[0] == full.set_index('driver').loc['Chris Lulham', 'points']
        assert race_points(con, cfg, policy='full_field').driver.tolist().count('chris') == 1
    finally:
        con.close()
    profiles = restored.lib.driver_profiles(cid)['profiles']
    assert next(p for p in profiles if p['key'] == 'chris')['is_ai']


def test_same_recording_different_championship_names_and_penalties(scene):
    app, path, cid, ai, _ = scene
    app.lib.add_round(cid, {'recording': path.name, 'round': 1})
    cid2 = app.lib.create_champ({'name': 'Alternative roster', 'copy_roster_from': cid})
    cfg2 = app.lib.champ_config(cid2)
    cfg2.livery_ai = True
    cfg2.ai_policy = 'full_field'
    cfg2.drivers[-2]['display'] = 'Alex Alternative'
    save_config(app.lib._db(cid2), cfg2)
    app.lib.add_round(cid2, {'recording': path.name, 'round': 3})
    assign(scene)
    add_correction(app.lib._db(cid), 1, ai['name'], 'position_penalty', 3)
    add_correction(app.lib._db(cid), 1, 'Chris Lulham', 'points', -2)
    add_correction(app.lib._db(cid), 1, 'Jax', 'points', -7)
    before = app.lib._analysis(path.name, cid)[0]
    assert 'Alex Alternative' in app.lib._analysis(path.name, cid2)[0].entrants.name.tolist()
    assign(scene, '2')
    after = app.lib._analysis(path.name, cid)[0]
    assert before is not after
    assert 'Fred Example' in after.entrants.name.tolist() and 'Chris Lulham' not in after.entrants.name.tolist()
    con = connect(app.lib._db(cid))
    try:
        assert con.execute('SELECT COUNT(*) FROM correction').fetchone()[0] == 3
        corrected = classified_races(con, app.lib.champ_config(cid))
        assert corrected[corrected.driver == 'fred'].name.iat[0] == ai['name']
        assert corrected[corrected.driver == 'fred'].points_adj.iat[0] == -2
        assert corrected[corrected.driver == 'jax'].points_adj.iat[0] == -7
    finally:
        con.close()


def test_duplicates_stale_windows_and_unknowns_preserve_prior_review(scene):
    app, path, cid, ai, _ = scene
    body, _ = assign(scene)
    old = (path / FILE).read_bytes()
    with pytest.raises(ValueError, match='another window'):
        app.save_identity_review(body)
    review = app.identity_review(path.name, cid, True)
    same_model = [e for e in review['entrants'] if e['car'] == ai.car]
    body['revision'] = review['revision']
    body['assignments'] = {e['id']: {'car_id': 'gt3', 'livery_id': '1', 'recorded_car': e['car']} for e in same_model[:2]}
    assert len(body['assignments']) == 2
    with pytest.raises(ValueError, match='Two entrants'):
        app.save_identity_review(body)
    assert (path / FILE).read_bytes() == old
    body['assignments'] = {}
    app.save_identity_review(body)
    assert read(path)['reviewed'] and not read(path)['assignments']
    assert ai['name'] in project_session(path, app.lib.champ_config(cid)).frames.name.tolist()


def test_dnfs_missing_previews_and_model_mismatch(scene):
    app, path, cid, ai, _ = scene
    review = app.identity_review(path.name, cid, True)
    retired = next(e for e in review['entrants'] if e['status'] == 'dnf')
    assert any(e['status'] == 'disconnected' for e in review['entrants'])
    assign(scene, name=retired['name'])
    fact = read(path)['assignments'][retired['id']]
    assert not fact.get('preview') and fact['livery_name'] == 'Red'
    cfg = app.lib.champ_config(cid)
    cfg.drivers[-2]['livery']['recorded_car'] = 'Wrong model'
    assert 'Chris Lulham' not in project_session(path, cfg).frames.name.tolist()


def test_unassigned_ai_does_not_register_by_name_and_empty_human_roster(scene):
    app, path, cid, ai, _ = scene
    cfg = app.lib.champ_config(cid)
    cfg.drivers[-2]['display'] = ai['name']
    cfg.drivers = [d for d in cfg.drivers if d.get('role') == 'ai']
    db = app.lib.root / 'unassigned.db'
    ingest(db, cfg, path, round_no=1)
    con = connect(db)
    try:
        assert con.execute('SELECT COUNT(*) FROM entrant WHERE is_ai=0').fetchone()[0] == 0
        assert con.execute('SELECT COUNT(*) FROM entrant WHERE driver_id IS NOT NULL').fetchone()[0] == 0
        assert standings(con, cfg, policy='full_field').empty
    finally:
        con.close()


def test_historical_catalog_and_preview_snapshot(scene):
    app, path, cid, ai, _ = scene
    png = b'\x89PNG\r\n\x1a\npreview-fixture'
    app._livery_editor.preview_image = lambda car, paint: png
    assign(scene)
    fact = read(path)['assignments'][entrant_id(ai['name'], ai.car)]
    assert base64.b64decode(fact['preview']) == png
    app._livery_editor.cars = {}
    app._livery_editor.config = {'game_path': 'Unavailable game'}
    def unavailable_scan():
        raise ValueError('Game installation moved')
    app._livery_editor.scan = unavailable_scan
    assert app.identity_catalog()['problem'] == 'Game installation moved'
    assign(scene)  # a saved selection survives removal from today's mod catalog
    assert read(path)['assignments'][entrant_id(ai['name'], ai.car)]['livery_name'] == 'Red'


def test_first_review_context_before_filing_and_live_recording_guard(scene):
    app, path, cid, ai, _ = scene
    assert app.identity_review(path.name)['champ'] == cid
    assert app.identity_review(path.name)['enabled']
    cid2 = app.lib.create_champ({'name': 'Another', 'copy_roster_from': cid})
    cfg2 = app.lib.champ_config(cid2)
    cfg2.livery_ai = True
    save_config(app.lib._db(cid2), cfg2)
    assert {c['id'] for c in app.identity_review(path.name)['choices']} == {cid, cid2}
    app.lib.add_round(cid, {'recording': path.name})
    assert app.identity_review(path.name)['champ'] == cid
    # A recording still being written must never open an assignment dialog.
    live = app.lib.recordings_dir / 'live-copy'
    shutil.copytree(path, live)
    meta = json.loads((live / 'session.json').read_text())
    meta['status'] = 'recording'
    (live / 'session.json').write_text(json.dumps(meta))
    assert not app.identity_review(live.name, cid)['enabled']
    assert 'complete' in app.identity_review(live.name, cid)['unavailable_reason']
    assert not app.identity_review(live.name, cid).get('setup_required')


def test_disabled_roster_explains_setup_without_changing_saved_config(scene):
    app, path, cid, ai, _ = scene
    cfg = app.lib.champ_config(cid)
    cfg.livery_ai = False
    save_config(app.lib._db(cid), cfg)
    review = app.identity_review(path.name, cid, detail=True)
    assert not review['enabled'] and review['setup_required']
    assert not app.lib.champ_config(cid).livery_ai
    cfg.livery_ai = True
    cfg.drivers = [d for d in cfg.drivers if d.get('role') != 'ai']
    save_config(app.lib._db(cid), cfg)
    assert app.identity_review(path.name, cid)['setup_required']


def paint_png(color):
    from PIL import Image
    picture = Image.new('RGBA', (80, 50), (0, 0, 0, 0))
    picture.paste(color, (10, 10, 70, 40))
    buffer = io.BytesIO()
    picture.save(buffer, format='PNG')
    return buffer.getvalue()


def test_human_livery_defaults_class_and_race_override_preserve_roles(scene):
    app, path, cid, ai, _ = scene
    raw = analyze_race(path, humans=set(HUMANS))
    human = raw.entrants[raw.entrants.name == 'Jax'].iloc[0]
    app._livery_editor.cars['gt3'].liveries.append({'id': '3', 'name': 'Human paint'})
    app._livery_editor.preview_image = lambda car, paint: paint_png('#FF0000')
    cfg = app.lib.champ_config(cid)
    cfg.drivers[0]['livery'] = {'car_id': 'gt3', 'livery_id': '3', 'recorded_car': human.car, 'color_override': '#00aaff'}
    app.route('PUT', '/api/championships/' + cid, {}, {'drivers': cfg.drivers, 'car_class': 'GT3 Gen 0'})
    restored = App(app.lib.root)
    cfg = restored.lib.champ_config(cid)
    assert cfg.car_class == 'GT3 Gen 0'
    assert cfg.drivers[0]['role'] == 'human' and cfg.drivers[0]['aliases'] == ['jax']
    binding = cfg.drivers[0]['livery']
    assert binding['color'] == '#FF0000' and binding['color_override'] == '#00AAFF'
    replay = restored.lib.replay(path.name, cid)
    jax = next(d for d in replay['drivers'] if d['name'] == 'Jax')
    assert not jax['is_ai'] and jax['color'] == '#00AAFF'
    assert jax['livery']['image'].startswith('data:image/png;base64,')
    assert 'Human paint' in restored.lib.race_report(path.name, cid)
    assert not next(d for d in restored.lib.replay(path.name, None)['drivers'] if d['name'] == 'Jax')['livery']

    # Race facts supersede the roster without renaming a human or registering an AI.
    review = app.identity_review(path.name, cid, True)
    assert review['car_class'] == 'GT3 Gen 0'
    hid = entrant_id('Jax', human.car)
    body = {'recording': path.name, 'champ': cid, 'revision': review['revision'],
            'assignments': {hid: {'car_id': 'gt3', 'livery_id': '2', 'recorded_car': human.car, 'color_override': '#123456'}}}
    app.save_identity_review(body)
    jax = next(d for d in app.lib.replay(path.name, cid)['drivers'] if d['name'] == 'Jax')
    assert not jax['is_ai'] and jax['color'] == '#123456' and jax['livery']['livery_id'] == '2'
    assert 'Fred Example' not in app.lib._analysis(path.name, cid)[0].entrants.name.tolist()
    body['revision'] = read(path)['revision']; body['assignments'] = {}
    app.save_identity_review(body)
    assert not next(d for d in app.lib.replay(path.name, cid)['drivers'] if d['name'] == 'Jax')['livery']


def test_human_only_roster_can_review_and_colors_survive_missing_catalog(scene):
    app, path, cid, ai, _ = scene
    raw = analyze_race(path, humans=set(HUMANS))
    human = raw.entrants[raw.entrants.name == 'Jax'].iloc[0]
    app._livery_editor.preview_image = lambda car, paint: paint_png('#20B060')
    cfg = app.lib.champ_config(cid)
    cfg.drivers = cfg.drivers[:2]
    cfg.drivers[0]['livery'] = {'car_id': 'gt3', 'livery_id': '1', 'recorded_car': human.car}
    app.route('PUT', '/api/championships/' + cid, {}, {'drivers': cfg.drivers})
    assert app.identity_review(path.name, cid)['enabled']
    assert app.identity_review(path.name)['champ'] == cid
    review = app.identity_review(path.name, cid, True)
    body = {'recording': path.name, 'champ': cid, 'revision': review['revision'], 'assignments': {
        entrant_id('Jax', human.car): {'car_id': 'gt3', 'livery_id': '1', 'recorded_car': human.car}}}
    app.save_identity_review(body)
    app._livery_editor.cars = {}
    body['revision'] = read(path)['revision']
    app.save_identity_review(body)
    jax = next(d for d in app.lib.replay(path.name, cid)['drivers'] if d['name'] == 'Jax')
    assert jax['color'] == '#20B060' and jax['livery']['image']


def test_paint_change_reestimates_color_and_invalid_override_is_atomic(scene):
    from ams2season.identities import snapshot, preview_color
    app, path, cid, ai, _ = scene
    app._livery_editor.preview_image = lambda car, paint: paint_png('#FF0000' if paint == '1' else '#0044FF')
    red = snapshot(app.liveries, 'gt3', '1')
    blue = snapshot(app.liveries, 'gt3', '2', red)
    assert red['color'] == '#FF0000' and blue['color'] == '#0044FF'
    assert red['preview'] != blue['preview']
    assert preview_color(b'no image') is None
    body, _ = assign(scene)
    chris = next(d for d in app.lib.replay(path.name, cid)['drivers'] if d['name'] == 'Chris Lulham')
    assert chris['is_ai'] and chris['color'] == '#FF0000' and chris['livery']['image']
    before = (path / FILE).read_bytes()
    body['revision'] = read(path)['revision']
    next(iter(body['assignments'].values()))['color_override'] = 'red'
    with pytest.raises(ValueError, match='hex color'):
        app.save_identity_review(body)
    assert (path / FILE).read_bytes() == before


def test_sidecar_revision_refreshes_stored_results_and_keeps_corrections(scene):
    from ams2season.identities import save
    app, path, cid, ai, _ = scene
    app.lib.add_round(cid, {'recording': path.name})
    assign(scene)
    add_correction(app.lib._db(cid), 1, 'Chris Lulham', 'points', -4)
    body, _ = assign(scene)
    review = app.identity_review(path.name, cid, True)
    choice = next(iter(body['assignments'].values()))
    choice['livery_id'] = '2'
    save(path, body['assignments'], review['entrants'], app.liveries, app.lib.champ_config(cid), review['revision'])
    detail = app.lib.champ_detail(cid)
    fred = next(r for r in detail['standings']['full_field']['rows'] if r['driver'] == 'Fred Example')
    assert fred['points'] == 21  # 25 for the win minus the original entrant's penalty
    assert len(detail['corrections']) == 1


def test_http_assets_origin_guard_and_persistent_assignment(scene):
    from ams2season.app import _make_server, make_handler
    app, path, cid, ai, _ = scene
    server = _make_server(0, make_handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    def call(method, url, body=None, origin=None):
        client = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        client.request(method, url, json.dumps(body) if body is not None else None, headers)
        res = client.getresponse(); code, data = res.status, res.read(); client.close()
        return code, data
    try:
        assert call('GET', '/identity-ui.js')[0] == 200
        _, raw = call('GET', f'/api/identities?recording={path.name}&champ={cid}')
        review = json.loads(raw)
        entrant = next(e for e in review['entrants'] if e['name'] == ai['name'])
        body = {'champ': cid, 'recording': path.name, 'revision': review['revision'],
                'assignments': {entrant['id']: {'car_id': 'gt3', 'livery_id': '1', 'recorded_car': ai.car}}}
        assert call('POST', '/api/identities', body, 'https://example.com')[0] == 403
        assert not (path / FILE).exists()
        assert call('POST', '/api/identities', body, f'http://127.0.0.1:{port}')[0] == 200
        _, raw = call('GET', f'/api/identities?recording={path.name}&champ={cid}')
        assert json.loads(raw)['reviewed']
        assert call('POST', '/api/identities', body)[0] == 400  # stale tab
    finally:
        server.shutdown(); server.server_close()


def test_recording_import_preserves_identity_sidecar_and_rejects_invalid_metadata(scene, tmp_path):
    app, path, cid, ai, _ = scene
    assign(scene)
    (tmp_path / 'friend-import').mkdir()
    imported = App(tmp_path / 'friend-import')
    files = [{'path': path.name + '/' + name, 'data': base64.b64encode((path / name).read_bytes()).decode('ascii')}
             for name in app.lib.IMPORT_FILES]
    result = imported.lib.import_recording({'files': files})
    dest = imported.lib.recording_path(result['imported'][0]['id'])
    assert read(dest) == read(path)
    assert (dest / 'frames.parquet').read_bytes() == (path / 'frames.parquet').read_bytes()
    (tmp_path / 'invalid-import').mkdir()
    other = App(tmp_path / 'invalid-import')
    files[-1]['data'] = base64.b64encode(b'{"version":999,"assignments":{}}').decode('ascii')
    with pytest.raises(ValueError, match='Unsupported recording'):
        other.lib.import_recording({'files': files})
    assert not list(other.lib.recordings_dir.iterdir())
