"""Independent review checks for complete timing and optional reference inputs."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ams2season.derive import Session
from ams2season.pace_compare import compare_laps, lap_catalog, pace_comparison
from ams2season.shm import RACESTATE_RACING


def session(offset=0.0, local_gap=False, invalid_middle=False):
    elapsed = np.arange(0, 151, .05)
    progress = 20 * elapsed
    phase = 2 * np.pi * progress / 1000
    frames = pd.DataFrame({'name': 'Driver', 't': elapsed + offset,
                           'lap_dist': progress % 1000, 'laps_completed': np.floor(progress / 1000).astype(int),
                           'speed': 20., 'race_state': RACESTATE_RACING, 'car': 'Test car',
                           'lap_invalid': (elapsed > 55) & (elapsed < 95) if invalid_middle else False,
                           'pit_mode': 0, 'last_lap': np.where(elapsed >= 50, 50., 0.),
                           'cur_s1': 15., 'cur_s2': 15.,
                           'x': 1000 / (2 * np.pi) * np.cos(phase), 'z': 1000 / (2 * np.pi) * np.sin(phase)})
    local = pd.DataFrame({'t': elapsed + offset, 'speed': 20., 'throttle': .8,
                          'brake': np.where((elapsed % 50 > 35) & (elapsed % 50 < 40), .7, 0.),
                          'gear': 4})
    if local_gap:
        local = local[~local.t.between(offset + 65, offset + 75)]
    return Session(Path('synthetic-review'), {'session_type': 'practice', 'track_length': 1000,
                                               'local': {'name': 'Driver'},
                                               'track_location': 'Test', 'track_variation': 'Circle'},
                   frames, local)


def test_catalog_clock_origin_does_not_change_elapsed_lap_or_geometry():
    a, b = session(), session(offset=12500.25)
    La, ca = lap_catalog(a); Lb, cb = lap_catalog(b)
    assert La == Lb == 1000
    left, right = ca['Driver'], cb['Driver']
    assert left['time'] == right['time'] == 50
    assert left['t'][0] == right['t'][0] == 0
    assert left['t'][-1] == right['t'][-1] == 50
    assert np.allclose(left['t'], right['t'])
    assert np.allclose(left['x'], right['x'])
    assert np.allclose(left['brake'], right['brake'])


def test_invalid_fastest_lap_is_not_selected_and_final_partial_lap_is_not_counted():
    L, catalog = lap_catalog(session(invalid_middle=True))
    ours = catalog['Driver']
    assert ours['valid_laps'] == 1 and ours['lap'] == 3 and ours['time'] == 50
    assert ours['t'][0] == 0 and ours['t'][-1] == 50


def test_local_only_recording_gap_is_not_interpolated_into_real_pedal_evidence():
    L, catalog = lap_catalog(session(local_gap=True))
    ours = catalog['Driver']
    assert ours['time'] == 50 and ours['valid_laps'] == 2
    assert 'brake' not in ours and 'throttle' not in ours and 'gear' not in ours


def test_corner_partitions_cover_observed_gap_with_wraparound_corners():
    L, catalog = lap_catalog(session())
    reference = catalog['Driver']
    mine = dict(reference, name='Slower', time=53., t=reference['t'] * 53 / 50)
    corners = [{'name': 'Near start', 'apex': 15}, {'name': 'Middle', 'apex': 450},
               {'name': 'Near finish', 'apex': 965}]
    result = compare_laps(mine, reference, corners, L)
    assert result['gap_s'] == pytest.approx(3.)
    assert sum(c['gap_s'] for c in result['corners']) == pytest.approx(result['gap_s'])
    for corner in result['corners']:
        assert sum(corner['phase_gap_s'].values()) == pytest.approx(corner['gap_s'])
    assert result['extra_path_estimate_s'] == pytest.approx(0.)  # identical path, slower traversal


def test_reference_from_other_layout_is_unavailable_before_geometry_comparison():
    ours, other = session(), session()
    other.meta['track_variation'] = 'Other layout'
    result = pace_comparison(ours, 'Driver', [{'name': 'Turn', 'apex': 450}], reference_session=other)
    assert not result['available'] and 'layout' in result['reason']


def braking_lap(name, pedal_start=None):
    """Identical traversal with independently recorded pedal-onset evidence."""
    grid = np.arange(0, 1001, 5.)
    metres_per_second = np.interp(grid, [0, 300, 430, 560, 1000], [60, 60, 20, 60, 60])
    elapsed = np.r_[0., np.cumsum(np.diff(grid) / ((metres_per_second[:-1] + metres_per_second[1:]) / 2))]
    phase = 2 * np.pi * grid / 1000
    lap = {'name': name, 'car': 'Same GT3', 'grid': grid, 't': elapsed,
           'time': float(elapsed[-1]), 'lap': 2, 'valid_laps': 3,
           'x': 1000 / (2 * np.pi) * np.cos(phase), 'z': 1000 / (2 * np.pi) * np.sin(phase),
           'v': metres_per_second * 3.6}
    if pedal_start is not None:
        lap['brake'] = np.where((grid >= pedal_start) & (grid <= 440), 80., 0.)
    return lap


def test_player_pedal_onset_is_not_compared_directly_to_ai_deceleration_onset():
    mine = braking_lap('Player', pedal_start=220)
    reference = braking_lap('AI')
    result = compare_laps(mine, reference, [{'name': 'Turn', 'apex': 450}], 1000)
    corner = result['corners'][0]
    assert corner['mine']['brake_source'] == 'pedals'
    assert corner['reference']['brake_source'] == 'deceleration'
    assert abs(corner['mine']['brake_at_m'] - corner['reference']['brake_at_m']) >= 20
    assert corner['mine']['deceleration_at_m'] == corner['reference']['deceleration_at_m']
    assert corner['brake_comparison_source'] == 'deceleration'
    assert corner['brake_marker_delta_m'] == pytest.approx(0.)
    assert result['gap_s'] == pytest.approx(0.)
    assert not any(s.startswith(('Braking begins', 'Deceleration begins')) for s in corner['observations'])


def test_two_real_pedal_traces_still_compare_actual_braking_onsets():
    mine = braking_lap('Player', pedal_start=220)
    reference = braking_lap('Friend', pedal_start=300)
    corner = compare_laps(mine, reference, [{'name': 'Turn', 'apex': 450}], 1000)['corners'][0]
    assert corner['brake_comparison_source'] == 'pedals'
    assert corner['brake_marker_delta_m'] == pytest.approx(-80.)
    assert any(s.startswith('Braking begins 80 m earlier') for s in corner['observations'])


@pytest.mark.parametrize('corners', [
    [{'name': 'First', 'apex': 450, 'dir': 'left'}, {'name': 'Second', 'apex': 530, 'dir': 'right'}],
    [{'name': 'Configured', 'apex': 450, 'dir': 'left', 'exit_policy': 'compromise'}],
], ids=['linked-opposing-turns', 'configured-narrow-exit'])
def test_compromised_exits_suppress_line_cost_and_preserve_observed_time_gaps(corners):
    sess = session()
    L, catalog = lap_catalog(sess)
    reference = dict(catalog['Driver'], name='Reference')
    original = catalog['Driver']
    # A wider measured path supplies a positive distance-only cost before policy
    # suppression; slowing the traversal also leaves an independently measured gap.
    radius = 1000 / (2 * np.pi)
    mine = dict(original, name='Driver', time=53., t=original['t'] * 53 / 50,
                x=original['x'] * (radius + 5) / radius,
                z=original['z'] * (radius + 5) / radius)
    basic = compare_laps(mine, reference, corners, L)
    assert basic['extra_path_estimate_s'] > 0
    assert all(c['extra_path_estimate_s'] > 0 for c in basic['corners'])
    result = pace_comparison(sess, 'Driver', corners, reference_name='Reference',
                             catalogs=(L, {'Driver': mine, 'Reference': reference}))
    assert result['available'] and result['gap_s'] == pytest.approx(3.)
    assert result['extra_path_estimate_s'] is None
    assert sum(c['gap_s'] for c in result['corners']) == pytest.approx(3.)
    for corner in result['corners']:
        baseline = next(c for c in basic['corners'] if c['corner'] == corner['corner'])
        assert corner['extra_path_estimate_s'] is None and corner['extra_path_sensitivity_s'] is None
        assert corner['gap_s'] == baseline['gap_s']
        assert corner['phase_gap_s'] == baseline['phase_gap_s']
