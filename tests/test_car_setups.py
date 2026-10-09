"""One-car snapshots survive tuning while preserving version and file guards."""
import copy
import json
import struct
import threading
from urllib.request import Request, urlopen

import pytest

from ams2season.bop import BopEditor
from ams2season.car_setups import capture, compatibility, get, import_setup, listing, prepare
from ams2season.bop_tuning import stage
from ams2season.conversion import propose
from test_bop import hashes, request
from test_conversion import rich_game, conversion_request
from test_conversion_calibration import bars_chassis, replace_component


@pytest.fixture
def editor(tmp_path, monkeypatch):
    game = rich_game(tmp_path)
    replace_component(game, 'car_a', 'cdf', bars_chassis(1470))
    folder = game / 'Vehicles/physics/tyres'
    folder.mkdir(exist_ok=True)
    for car in ('car_a', 'car_b', 'car_c'):
        (folder / f'tyre_{car}.hdtbin').write_bytes(f'{car} entire tyre physics'.encode())
    e = BopEditor(tmp_path / 'app'); e.scan(str(game))
    monkeypatch.setattr('ams2season.bop_files._game_running', lambda: False)
    return e


def saved(editor, draft=None, name='Road America'):
    return capture(editor, {'car': 'car_a', 'name': name, 'edit': draft})


def apply(editor, draft):
    return editor.apply(editor.preview([draft])['token'])


def test_installed_snapshot_needs_no_draft_and_saves_only_one_car(editor):
    before = hashes(editor.game)
    result = saved(editor); setup = get(editor, result['id'])
    assert setup['kind'] == 'settings' and setup['car'] == 'car_a'
    assert setup['settings']['parameters']['cdf.mass.0.0'] == 1470
    assert setup['settings']['tyres'] == 'tyre_car_a'
    assert setup['tyre_reference']['model'] == 'tyre_car_a'
    assert not any(k.startswith('edf.rpm') for k in setup['settings']['parameters'])
    assert not prepare(editor, 'car_a', setup)['edit']['parameters']
    assert listing(editor)[0]['car'] == 'car_a' and hashes(editor.game) == before


def test_draft_and_percentage_baseline_roundtrip_without_compounding(editor):
    draft = stage(editor, {'edit': request(editor), 'category': 'wings', 'percent': .25})['edit']
    draft['parameters']['cdf.mass.0.0'] = 1420
    setup = saved(editor, draft)['setup']
    loaded = prepare(editor, 'car_a', json.loads(json.dumps(setup)))['edit']
    assert loaded['parameters'] == draft['parameters']
    assert loaded['percentage_tuning'] == draft['percentage_tuning']
    reset = stage(editor, {'edit': loaded, 'category': 'wings', 'percent': 0})['edit']
    assert reset['parameters'] == {'cdf.mass.0.0': 1420}
    assert setup['settings']['parameters']['gdf.gear.0.0'] == next(p.value for p in editor.cars['car_a'].parameters if p.id == 'gdf.gear.0.0')


def test_restore_after_numeric_class_tyre_and_float_widening_apply(editor):
    baseline = saved(editor)['setup']; original = hashes(editor.game)
    signature = compatibility(editor, editor.cars['car_a'])
    draft = request(editor, parameters={'cdf.mass.0.0': 1390, 'cdf.fw_max_height.0.0': .25},
                    target_class='Testing', group='GT3', grid='10', tyres='tyre_car_b')
    apply(editor, draft)
    modified = hashes(editor.game)
    assert compatibility(editor, editor.cars['car_a']) == signature
    assert 'tyre_car_a' not in editor.listing()['tyre_models']  # Still installed but no car now uses it.
    restore = prepare(editor, 'car_a', baseline)['edit']
    assert restore['fingerprint'] == editor.cars['car_a'].fingerprint
    assert restore['tyres'] == 'tyre_car_a' and restore['target_class'] == baseline['settings']['target_class']
    apply(editor, restore)
    assert editor.detail('car_a')['metrics']['mass'] == 1470
    assert editor.cars['car_a'].references['tyres'] == 'tyre_car_a'
    assert compatibility(editor, editor.cars['car_a']) == signature
    assert next(p.value for p in editor.cars['car_a'].parameters if p.id == 'cdf.fw_max_height.0.0') == 1
    # Restoration uses the installed writer layout; Undo is byte-exact.
    editor.undo(); assert hashes(editor.game) == modified
    assert all(modified[k] == v for k, v in original.items() if 'car_a' not in k and 'PERSISTENT' not in k)


def test_saved_tuned_configuration_loads_again_after_another_apply(editor):
    tuned = stage(editor, {'edit': request(editor), 'category': 'power', 'percent': 1.25})['edit']
    preset = saved(editor, tuned)['setup']
    apply(editor, tuned)
    apply(editor, request(editor, parameters={'cdf.power_multiplier.0.0': 1.1}))
    loaded = prepare(editor, 'car_a', preset)['edit']
    assert loaded['percentage_tuning'] == tuned['percentage_tuning']
    apply(editor, loaded)
    assert editor.detail('car_a')['metrics']['power_multiplier'] == pytest.approx(preset['settings']['parameters']['cdf.power_multiplier.0.0'])


def test_conversion_snapshot_keeps_class_tyre_and_reference_context(editor):
    draft = propose(editor, conversion_request(strength=.6, performance_target='reference'))['edit']
    setup = saved(editor, draft)['setup']
    loaded = prepare(editor, 'car_a', setup)['edit']
    assert loaded['target_class'] == draft['target_class']
    assert loaded['tyres'] == draft['tyres']
    assert loaded['conversion_reference'] == draft['conversion_reference']
    assert loaded['reference_basis'] == draft['reference_basis']
    assert editor._evaluate(loaded)['after'] == editor._evaluate(draft)['after']


def test_import_is_local_and_wrong_car_never_saves_or_changes_game(editor):
    setup = saved(editor)['setup']; before = hashes(editor.game)
    count = len(listing(editor))
    with pytest.raises(ValueError, match='different car'):
        import_setup(editor, {'car': 'car_b', 'setup': setup})
    with pytest.raises(ValueError, match='selected car'):
        capture(editor, {'car': 'car_b', 'name': 'Wrong', 'edit': request(editor)})
    assert len(listing(editor)) == count
    result = import_setup(editor, {'car': 'car_a', 'setup': json.loads(json.dumps(setup))})
    assert get(editor, result['id']) == setup and hashes(editor.game) == before


@pytest.mark.parametrize('change', ['mass', 'unknown', 'rpm', 'vdf'])
def test_compatibility_accepts_tuning_but_blocks_physics_model_changes(editor, change):
    setup = saved(editor)['setup']
    if change == 'mass':
        apply(editor, request(editor, parameters={'cdf.mass.0.0': 1400}))
        assert prepare(editor, 'car_a', setup)['edit']['parameters']['cdf.mass.0.0'] == 1470
        return
    car = editor.cars['car_a']
    if change == 'unknown':
        raw = car.sources['cdf'][0].raw + b'new mod revision'
        replace_component(editor.game, 'car_a', 'cdf', raw)
    elif change == 'rpm':
        raw = bytearray(car.sources['edf'][0].raw)
        p = next(p for p in car.parameters if p.group == 'RPM')
        struct.pack_into('<' + p.fmt, raw, p.offset, p.value + 100)
        replace_component(editor.game, 'car_a', 'edf', bytes(raw))
    else:
        # An unknown VDF byte must remain pinned, even with an editable tyre link.
        source = car.sources['vdf'][0]
        raw = bytearray(source.raw); raw[-1] ^= 1
        source.file.write_bytes(bytes(raw))
    editor.scan(str(editor.game))
    with pytest.raises(ValueError, match='different physics|complete set'):
        prepare(editor, 'car_a', setup)


def test_tyre_dependency_change_blocks_restore_and_apply(editor):
    setup = saved(editor)['setup']
    apply(editor, request(editor, tyres='tyre_car_b'))
    loaded = prepare(editor, 'car_a', setup)['edit']
    plan = editor.preview([loaded])
    tyre = editor.game / 'Vehicles/physics/tyres/tyre_car_a.hdtbin'
    tyre.write_bytes(b'new tyre model version')
    with pytest.raises(ValueError, match='referenced game file changed'):
        editor.apply(plan['token'])
    editor.scan(str(editor.game))
    with pytest.raises(ValueError, match='tyre model is missing'):
        prepare(editor, 'car_a', setup)


@pytest.mark.parametrize('mutation', ['format', 'version', 'boolean_version', 'name', 'missing', 'extra', 'bool', 'nan', 'range', 'class', 'tyres', 'pin', 'context'])
def test_malformed_imports_never_save_or_change_game(editor, mutation):
    setup = saved(editor)['setup']; before = hashes(editor.game); count = len(listing(editor))
    setup = copy.deepcopy(setup)
    if mutation in ('format', 'version', 'name'): setup[mutation] = None
    elif mutation == 'boolean_version': setup['version'] = True
    elif mutation == 'missing': del setup['settings']['parameters']['cdf.mass.0.0']
    elif mutation == 'extra': setup['settings']['parameters']['cdf.nonexistent.0.0'] = 1
    elif mutation in ('bool', 'nan', 'range'): setup['settings']['parameters']['cdf.mass.0.0'] = {'bool': True, 'nan': float('nan'), 'range': -1}[mutation]
    elif mutation == 'class': setup['settings']['target_class'] = '../bad'
    elif mutation == 'tyres': setup['settings']['tyres'] = None
    elif mutation == 'pin': setup['tyre_reference']['hash'] = '0' * 64
    elif mutation == 'context': setup['context']['donor_baseline'] = {}
    with pytest.raises(ValueError): import_setup(editor, {'car': 'car_a', 'setup': setup})
    assert len(listing(editor)) == count and hashes(editor.game) == before


def test_shared_physics_is_excluded_instead_of_modified(editor):
    car = editor.cars['car_a']; car.blocked['edf'] = 'Shared engine'
    setup = saved(editor)['setup']
    assert not any(k.startswith('edf.') for k in setup['settings']['parameters'])
    assert not prepare(editor, 'car_a', setup)['edit']['parameters']


def test_single_car_legacy_profile_import_and_multi_car_rejection(editor):
    profile = {'format': 'ams2season-bop', 'version': 1, 'name': 'Legacy',
               'edits': [request(editor, parameters={'cdf.mass.0.0': 1400})]}
    result = import_setup(editor, {'car': 'car_a', 'setup': profile})
    assert result['edit']['parameters'] == {'cdf.mass.0.0': 1400}
    profile['edits'].append(request(editor, 'car_b', parameters={'cdf.mass.0.0': 1250}))
    with pytest.raises(ValueError, match='multiple cars'): import_setup(editor, {'car': 'car_a', 'setup': profile})
    with pytest.raises(ValueError, match='identifier'): get(editor, '../outside')


def test_complete_donor_draft_keeps_local_baseline_without_exporting_binaries(tmp_path, monkeypatch):
    from test_donor import ready, draft
    _, editor, baseline = ready(tmp_path)
    setup = saved(editor, draft(editor, baseline, power=.5))['setup']
    assert setup['kind'] == 'donor-draft'
    assert prepare(editor, 'car_a', setup)['edit']['donor_baseline']['id'] == baseline['id']
    assert len(json.dumps(setup)) < 5000
    (editor.install_dir / 'donor_baselines' / baseline['id'] / 'baseline.json').unlink()
    with pytest.raises(ValueError, match='baseline'):
        prepare(editor, 'car_a', setup)


def test_http_capture_load_export_import_preserve_tiny_coefficients_and_scope(editor):
    from ams2season.app import _make_server, make_handler
    class App:
        root = editor.app_root
        def route(self, method, path, query, body): return editor.route(method, path, query, body)
    server = _make_server(0, make_handler(App()))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    def api(path, body=None):
        req = Request(f'http://127.0.0.1:{server.server_address[1]}' + path,
                      None if body is None else json.dumps(body).encode(), {'Content-Type': 'application/json'})
        with urlopen(req, timeout=10) as response: return json.load(response)
    try:
        draft = stage(editor, {'edit': request(editor), 'category': 'wings', 'percent': .25})['edit']
        result = api('/api/bop/car-setups/capture', {'car': 'car_a', 'name': 'HTTP', 'edit': draft})
        setup = api('/api/bop/car-setups/file?id=' + result['id'])
        assert setup['settings']['parameters']['cdf.rw_lift.0.2'] == draft['parameters']['cdf.rw_lift.0.2']
        loaded = api('/api/bop/car-setups/load', {'car': 'car_a', 'id': result['id']})
        imported = api('/api/bop/car-setups/import', {'car': 'car_a', 'setup': setup})
        assert loaded['edit'] == imported['edit']
        assert len(api('/api/bop/car-setups')['setups']) == 2
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
