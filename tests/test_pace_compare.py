"""Timing reconciliation, conservative path estimates and actual API integration."""
import json
from pathlib import Path

import numpy as np
import pytest

from ams2season.pace_compare import compare_laps, lap_catalog, pace_comparison
from ams2season.derive import custom_corners, load_session
from ams2season.simulate import RaceScript, run_race
from ams2season.app import App
from ams2season.trackmap import load_track_file, save_track_corners


def _lap(name='Me', extra_time=0, radius=160, car='GT3'):
    grid = np.arange(0, 1001, 5.0)
    angle = grid / 1000 * 2 * np.pi
    return {'name': name, 'car': car, 'lap': 2, 'valid_laps': 3, 'time': 50.0 + extra_time,
            'grid': grid, 't': grid / 1000 * (50 + extra_time),
            'v': np.full(len(grid), 72.0), 'x': radius * np.cos(angle), 'z': radius * np.sin(angle)}


CORNERS = [{'name': 'T1', 'apex': 50.0}, {'name': 'T2', 'apex': 430.0}, {'name': 'T3', 'apex': 850.0}]


def test_whole_lap_timing_is_partitioned_once_including_start_line_corner():
    ours, theirs = _lap(extra_time=2), _lap('Reference')
    # Vary the gap around the circuit rather than only uniform loss.
    ours['t'] += 0.5 * np.sin(ours['grid'] / 1000 * 2 * np.pi)
    result = compare_laps(ours, theirs, CORNERS, 1000)
    assert result['gap_s'] == pytest.approx(2)
    assert sum(c['gap_s'] for c in result['corners']) == pytest.approx(2)
    for c in result['corners']:
        assert sum(c['phase_gap_s'].values()) == pytest.approx(c['gap_s'])
    assert result['trace']['gap_s'][-1] == pytest.approx(result['gap_s'])


def test_same_path_has_zero_geometric_loss_even_when_driver_is_slower():
    result = compare_laps(_lap(extra_time=5), _lap('Reference'), CORNERS, 1000)
    assert result['extra_path_estimate_s'] == 0
    assert all(c['line_deviation_m'] == pytest.approx(0) for c in result['corners'])


def test_extra_path_estimate_is_positive_but_never_exceeds_observed_loss():
    result = compare_laps(_lap(extra_time=2, radius=165), _lap('Reference'), CORNERS, 1000)
    assert 0 < result['extra_path_estimate_s'] <= 2
    assert all(0 <= c['extra_path_estimate_s'] <= c['gap_s'] + 1e-8 for c in result['corners'])
    assert result['confidence'] == 'low'


def test_longer_but_faster_line_is_not_called_lost_time():
    result = compare_laps(_lap(extra_time=-1, radius=165), _lap('Reference'), CORNERS, 1000)
    assert result['gap_s'] < 0
    assert result['extra_path_estimate_s'] == 0


def test_different_models_keep_measured_pace_but_no_line_time_claim():
    result = compare_laps(_lap(extra_time=3, car='Mustang'), _lap('GT-R', car='Nissan'), CORNERS, 1000)
    assert result['gap_s'] == 3
    assert result['extra_path_estimate_s'] is None
    assert 'Different car' in result['line_estimate_reason']


def test_position_spike_disables_geometry_without_losing_timing():
    mine = _lap(extra_time=1)
    mine['x'][90] += 1000
    result = compare_laps(mine, _lap('Reference'), CORNERS, 1000)
    assert result['available'] and result['gap_s'] == 1
    assert result['extra_path_estimate_s'] is None


def test_missing_reference_inputs_do_not_invent_throttle_advice():
    result = compare_laps(_lap(extra_time=1), _lap('AI'), CORNERS, 1000)
    assert not result['reference']['pedals_available']
    assert all(c['pickup_delta_m'] is None for c in result['corners'])


def test_nonmonotone_timing_rejected():
    mine = _lap()
    mine['t'][4] = mine['t'][3]
    with pytest.raises(ValueError, match='increase'):
        compare_laps(mine, _lap('Reference'), CORNERS, 1000)


def test_own_fastest_lap_does_not_claim_an_independent_line_estimate(recorded):
    session = load_session(recorded[1])
    L, catalog = lap_catalog(session)
    mine = catalog[session.meta['local']['name']]
    result = pace_comparison(session, mine['name'], CORNERS, reference_kind='same_car', catalogs=(L, {mine['name']: mine}))
    assert result['available'] and result['gap_s'] == 0
    assert result['extra_path_estimate_s'] is None
    assert 'own fastest lap' in result['context']
    assert 'no independent' in result['line_estimate_reason']


def test_intended_narrow_exit_setting_survives_track_round_trip(tmp_path):
    corners = [{'name': 'T1', 'apex': 200, 'exit_policy': 'compromise'}]
    save_track_corners(tmp_path, 'Track', 'Layout', corners)
    restored = load_track_file(tmp_path, 'Track', 'Layout')['corners']
    decoded = custom_corners(restored, np.full(100, 30.0), np.full(100, 0.02))
    assert decoded[0]['exit_policy'] == 'compromise'


@pytest.fixture(scope='module')
def recorded(tmp_path_factory):
    root = tmp_path_factory.mktemp('pace-comparison')
    folders = run_race(root / 'recordings', ['Jax', 'Mason'],
                       RaceScript(laps=5, n_ai=3, with_qualifying=True, local_collision_lap=None), seed=7)
    race = next(p for p in folders if p.name.endswith('_race'))
    return root, race


def test_catalog_uses_supported_flying_laps_and_exact_endpoints(recorded):
    _, path = recorded
    L, catalog = lap_catalog(load_session(path))
    assert catalog
    for lap in catalog.values():
        assert lap['lap'] >= 2
        assert lap['t'][0] == 0 and lap['t'][-1] == pytest.approx(lap['time'])
        assert lap['grid'][-1] == L


def test_api_attaches_pace_exit_fields_and_reference_options(recorded):
    root, path = recorded
    app = App(root)
    data = app.lib.technique(path.name, None)
    assert {'fastest', 'same_car', 'leader', 'pole'} <= {r['key'] for r in data['pace_references']}
    driver = next(d for d in data['drivers'] if d['available'])
    pace = driver['pace_comparison']
    assert pace['available']
    assert sum(c['gap_s'] for c in pace['corners']) == pytest.approx(pace['gap_s'])
    assert any(c.get('track_usage', {}).get('exit_gap_m') is not None for c in pace['corners'])
    # No numpy values, NaNs or Infinity leak into this enriched API.
    json.dumps(data, allow_nan=False)
    pole = app.lib.technique(path.name, None, 'pole')['drivers'][0]['pace_comparison']
    assert pole['available'] and not pole['same_session']
    same = app.lib.technique(path.name, None, 'same_car')['drivers'][0]['pace_comparison']
    assert same['same_car']
    with pytest.raises(ValueError, match='Unknown pace reference'):
        app.lib.technique(path.name, None, 'unsupported')


def test_player_profile_throttle_uses_same_pedal_score_as_technique(recorded):
    root, path = recorded
    app = App(root)
    report = app.lib.technique_cached(path)
    analysis = app.lib._analysis(path.name, None)[0]
    from ams2season.technique import throttle_consistency_summary
    expected = throttle_consistency_summary(report)
    player = analysis.stats.set_index('name').loc[report['driver']]
    assert player.throttle_consistency == expected['reduced']
    assert player.throttle_rating_source == 'pedals'
