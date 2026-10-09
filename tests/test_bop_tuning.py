"""Category scaling must remain bounded, auditable and reversible through normal BOP."""
import copy
import json

import pytest

from ams2season.bop import BopEditor
from ams2season.bop_physics import decode, edit
from ams2season.bop_tuning import information, stage
from test_bop import hashes, request
from test_conversion import rich_game
from test_conversion_calibration import bars_chassis, replace_component


@pytest.fixture
def editor(tmp_path, monkeypatch):
    game = rich_game(tmp_path)
    replace_component(game, 'car_a', 'cdf', bars_chassis(1470))
    e = BopEditor(tmp_path / 'app')
    e.scan(str(game))
    # Synthetic fixture only: the user's actual AMS2 may be running during tests.
    monkeypatch.setattr('ams2season.bop_files._game_running', lambda: False)
    return e


def tune(editor, category, percent, draft=None):
    return stage(editor, {'edit': draft or request(editor), 'category': category, 'percent': percent})


def test_all_categories_expose_complete_nonoverlapping_parameter_sets(editor):
    categories = editor.detail('car_a')['percentage_categories']
    assert len(categories) == 9 and all(c['available'] for c in categories)
    ids = [p for c in categories for p in c['parameters']]
    assert len(ids) == len(set(ids))
    assert all(c['step'] == .25 for c in categories)


@pytest.mark.parametrize('category', ['power', 'mass', 'wings', 'drag', 'brakes', 'springs', 'dampers', 'bars', 'cg'])
def test_quarter_percent_changes_only_the_category_and_reset_is_exact(editor, category):
    before = hashes(editor.game)
    selected = next(c for c in information(editor.cars['car_a']) if c['id'] == category)
    draft = tune(editor, category, .25)['edit']
    assert draft['parameters'] and set(draft['parameters']) <= set(selected['parameters'])
    assert hashes(editor.game) == before
    reset = tune(editor, category, 0, draft)['edit']
    assert reset == request(editor)
    assert hashes(editor.game) == before


def test_wings_preserve_balance_signs_drag_and_do_not_compound(editor):
    car = editor.cars['car_a']
    first = tune(editor, 'wings', 1)['edit']
    second = tune(editor, 'wings', 2, first)
    known = {p.id: p.value for p in car.parameters}
    for key, value in second['edit']['parameters'].items():
        assert value == pytest.approx(known[key] * 1.02)
    assert second['after']['fw_lift'] / second['before']['fw_lift'] == pytest.approx(1.02)
    assert second['after']['rw_lift'] / second['before']['rw_lift'] == pytest.approx(1.02)
    assert second['after']['body_drag'] == second['before']['body_drag']
    assert second['after']['power_multiplier'] == second['before']['power_multiplier']


def test_manual_draft_is_starting_point_and_resets_preserve_other_edits(editor):
    manual = request(editor, parameters={'cdf.fw_lift.0.0': -.3, 'cdf.cg_height.0.0': .25})
    first = tune(editor, 'wings', 1, manual)['edit']
    assert first['parameters']['cdf.fw_lift.0.0'] == pytest.approx(-.303)
    both = tune(editor, 'power', -.25, first)['edit']
    reset = tune(editor, 'wings', 0, both)['edit']
    assert reset['parameters']['cdf.fw_lift.0.0'] == -.3
    assert reset['parameters']['cdf.cg_height.0.0'] == .25
    assert set(reset['percentage_tuning']['categories']) == {'power'}
    assert tune(editor, 'power', 0, reset)['edit'] == manual


def test_mass_rounds_to_stored_whole_kg_without_scaling_inertia(editor):
    result = tune(editor, 'mass', -.25)
    assert result['after']['mass'] == 1466
    assert set(result['edit']['parameters']) == {'cdf.mass.0.0'}
    assert result['after']['yaw_inertia'] == result['before']['yaw_inertia']


def test_spring_and_damper_scaling_does_not_double_scale_ranges_or_settings(editor):
    draft = tune(editor, 'springs', 1)['edit']
    draft = tune(editor, 'dampers', -.25, draft)['edit']
    car = editor.cars['car_a']
    old = {p.id: p.value for p in car.parameters if p.id.startswith('cdf.')}
    new = {p.id: p.value for p in decode('cdf', edit('cdf', car.sources['cdf'][0].raw, draft['parameters']))}
    assert all(new[k] == v for k, v in old.items() if k not in draft['parameters'])
    assert all(new[k] == pytest.approx(v * 1.01) for k, v in old.items() if k.startswith('cdf.spring_multiplier.'))
    assert all(new[k] == pytest.approx(v * .9975) for k, v in old.items() if k.startswith('cdf.damper_multiplier.'))


@pytest.mark.parametrize('percent', [.1, .3, 50.25, -50.25, True, '1', float('nan'), float('inf'), None])
def test_invalid_percentages_never_change_files_or_input_draft(editor, percent):
    before = hashes(editor.game)
    draft = request(editor)
    snapshot = copy.deepcopy(draft)
    with pytest.raises(ValueError):
        tune(editor, 'wings', percent, draft)
    assert draft == snapshot and hashes(editor.game) == before


def test_unavailable_partial_or_shared_categories_are_blocked(editor):
    car = editor.cars['car_a']
    car.parameters = [p for p in car.parameters if p.id != 'cdf.rw_lift.0.2']
    assert not next(c for c in information(car) if c['id'] == 'wings')['available']
    with pytest.raises(ValueError, match='complete'):
        tune(editor, 'wings', 1)
    car.blocked['cdf'] = 'This physics file is shared with car_b.'
    with pytest.raises(ValueError, match='shared'):
        tune(editor, 'power', 1)


def test_bars_require_spring_model_and_preserve_counts_settings(editor):
    result = tune(editor, 'bars', .25)
    assert set(result['edit']['parameters']) == {f'cdf.{axle}_arb_range.0.{i}' for axle in ('front', 'rear') for i in range(2)}
    switched = request(editor, parameters={'cdf.spring_based_arb.0.0': 0})
    with pytest.raises(ValueError, match='spring-based'):
        tune(editor, 'bars', .25, switched)


@pytest.mark.parametrize('change', ['percent', 'base', 'parameters', 'category'])
def test_tampered_percentage_metadata_cannot_be_reviewed(editor, change):
    draft = tune(editor, 'wings', 1)['edit']
    state = draft['percentage_tuning']['categories']['wings']
    if change == 'percent': state['percent'] = 2
    elif change == 'base': state['base'].pop('cdf.rw_lift.0.2')
    elif change == 'parameters': draft['parameters']['cdf.fw_lift.0.0'] = -.5
    else: draft['percentage_tuning']['categories']['grip'] = state
    with pytest.raises(ValueError): editor.preview([draft])


def test_out_of_range_starting_values_and_stale_drafts_are_rejected(editor):
    manual = request(editor, parameters={'cdf.power_multiplier.0.0': 9.99})
    with pytest.raises(ValueError, match='range'):
        tune(editor, 'power', .25, manual)
    old = request(editor)
    old['fingerprint'] = 'stale'
    with pytest.raises(ValueError, match='differs'):
        tune(editor, 'power', 1, old)


def test_existing_zero_coefficients_stay_zero_and_nonwritable_defaults_do_not_resize(editor):
    car = editor.cars['car_a']
    p = next(p for p in car.parameters if p.id == 'cdf.fw_lift.0.2')
    p.value, p.offset, p.minimum, p.maximum = 0, -1, 0, 0
    result = tune(editor, 'wings', .25)
    assert 'cdf.fw_lift.0.2' not in result['edit']['parameters']


def test_percentage_profile_preview_apply_undo_and_api_route(editor):
    before = hashes(editor.game)
    first = editor.route('POST', '/api/bop/tune', {}, {'edit': request(editor), 'category': 'wings', 'percent': .25})
    result = tune(editor, 'power', 1, first['edit'])
    profile = {'format': 'ams2season-bop', 'version': 1, 'name': 'Quarter-step trial', 'edits': [result['edit']]}
    saved = editor.import_profile(profile)
    assert editor.profile(saved['id']) == profile and hashes(editor.game) == before
    plan = editor.preview(profile['edits'])
    assert plan['changes'][0]['percentage_tuning'] == result['edit']['percentage_tuning']
    editor.apply(plan['token'])
    assert editor.detail('car_a')['metrics']['wing_lift'] == pytest.approx(result['after']['wing_lift'])
    assert editor.detail('car_a')['metrics']['power_multiplier'] == pytest.approx(result['after']['power_multiplier'])
    record = json.loads(next((editor.install_dir / 'backups').glob('*/transaction.json')).read_text())
    assert record['changes'][0]['percentage_tuning'] == result['edit']['percentage_tuning']
    with pytest.raises(ValueError, match='differs'):
        editor.import_profile(profile)
    editor.undo()
    assert hashes(editor.game) == before and editor.import_profile(profile, save=False) == profile


def test_complete_donor_and_unknown_categories_are_not_mixed(editor):
    donor = request(editor, donor_baseline={'id': 'saved', 'offsets': {}})
    with pytest.raises(ValueError, match='complete donor'):
        tune(editor, 'wings', 1, donor)
    with pytest.raises(ValueError, match='supported'):
        tune(editor, 'grip', 1)


def test_http_preserves_tiny_percentage_values_through_edit_review_and_profile(editor):
    import http.client
    import threading
    import numpy as np
    from ams2season.app import App, _make_server, make_handler

    class FixtureApp(App):
        def route(self, method, path, query, body):
            if path == '/api/test-report-cleaning':
                return {'values': [np.float64(.0002005), np.float64(float('nan')),
                                   float('inf'), np.int64(2), np.bool_(True)]}
            return super().route(method, path, query, body)

    app = FixtureApp(editor.app_root)
    app._bop_editor = editor
    server = _make_server(0, make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=20)
        conn.request(method, path, json.dumps(body) if body is not None else None,
                     headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        result = json.loads(response.read())
        conn.close()
        assert response.status == 200, result
        return result

    before = hashes(editor.game)
    try:
        # Report/telemetry responses retain their existing four-place cleaning.
        assert call('GET', '/api/test-report-cleaning')['values'] == [.0002, None, None, 2, True]
        detail = call('GET', '/api/bop/car?car=car_a')
        expected = editor.detail('car_a')
        assert detail['parameters'] == expected['parameters']
        first = call('POST', '/api/bop/tune', {'edit': request(editor), 'category': 'wings', 'percent': .25})
        assert first['edit'] == tune(editor, 'wings', .25)['edit']
        small = first['edit']['parameters']['cdf.rw_lift.0.2']
        assert small != round(small, 4)
        # A second browser request must still validate the first response's baseline.
        second = call('POST', '/api/bop/tune', {'edit': first['edit'], 'category': 'wings', 'percent': 1})
        call('POST', '/api/bop/preview', {'edits': [second['edit']]})
        profile = {'format': 'ams2season-bop', 'version': 1, 'name': 'HTTP quarter-step trial', 'edits': [second['edit']]}
        saved = call('POST', '/api/bop/profiles', profile)
        downloaded = call('GET', '/api/bop/profile?id=' + saved['id'])
        assert downloaded == profile
        assert call('POST', '/api/bop/profile/validate', downloaded) == profile
        reset = call('POST', '/api/bop/tune', {'edit': downloaded['edits'][0], 'category': 'wings', 'percent': 0})
        assert reset['edit'] == request(editor)
        assert hashes(editor.game) == before
    finally:
        server.shutdown()
        server.server_close()
