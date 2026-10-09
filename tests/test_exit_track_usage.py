"""Exit-edge distance and linked-corner scoring from supported position geometry."""
import numpy as np
import pandas as pd

from ams2season.metrics import corner_track_usage, driving_metrics


def geometry(length=1000.0):
    ld = np.arange(0, length, 2.0)
    return ld, np.full(int(length / 5), 6.0), np.full(int(length / 5), -6.0)


def usage(ld, off, left, right, **kwargs):
    return corner_track_usage(ld, off, {'name': 'T1', 'apex': 250.0, 'dir': 'left', 'radius': 80},
                              1000.0, left, right, 1000.0, 1000.0, **kwargs)


def test_exit_gap_uses_outside_wheel_and_supported_approach():
    ld, left, right = geometry()
    off = -4.15 + 9.3 * np.exp(-((ld - 250) / 48) ** 4)
    d = usage(ld, off, left, right, edge_source='mapped')
    assert d['apex_gap_m'] < 0.02
    assert abs(d['exit_gap_m'] - 1.0) < 0.001
    assert d['exit_treatment'] == 'normal'
    assert d['edge_source'] == 'mapped'
    assert d['exit_usage_score'] < d['apex_usage_score']


def test_single_exit_position_spike_cannot_hide_narrow_exit():
    ld, left, right = geometry()
    off = np.zeros(len(ld))
    baseline = usage(ld, off, left, right)
    off[np.argmin(abs(ld - 350))] = -5.15
    d = usage(ld, off, left, right)
    assert d['exit_gap_m'] == baseline['exit_gap_m'] == 5.15
    assert d['track_usage'] == baseline['track_usage'] == 0


def test_exit_distance_survives_a_justified_chicane_setup():
    ld, left, right = geometry()
    next_corner = {'name': 'T2', 'apex': 370.0, 'dir': 'right', 'radius': 80}
    # Stay left after T1 to enter the following right-hander from its outside.
    off = np.interp(ld, [0, 150, 230, 350, 370, 430, 1000], [-5.15, -5.15, 5.15, 5.15, -5.15, 5.15, 5.15])
    d = corner_track_usage(ld, off, {'name': 'T1', 'apex': 250.0, 'dir': 'left', 'radius': 80},
                           1000.0, left, right, 880.0, 120.0, next_corner=next_corner)
    ordinary = corner_track_usage(ld, off, {'name': 'T1', 'apex': 250.0, 'dir': 'left', 'radius': 80},
                                  1000.0, left, right, 880.0, 120.0)
    assert d['exit_treatment'] == 'linked_corner'
    assert d['next_corner'] == 'T2' and 'T2' in d['exit_reason']
    assert abs(d['exit_gap_m'] - 10.3) < 1e-9  # measured, not rewritten to zero
    assert d['exit_usage_score'] == 0
    assert d['track_usage'] > 99 and ordinary['track_usage'] == 75


def test_nearby_turns_do_not_blanket_excuse_a_missed_exit():
    ld, left, right = geometry()
    off = np.interp(ld, [0, 150, 230, 266, 280, 1000], [-5.15, -5.15, 5.15, 5.15, 0, 0])
    c = {'name': 'T1', 'apex': 250.0, 'dir': 'left', 'radius': 80}
    for direction in ('left', 'right'):
        following = {'name': 'T2', 'apex': 370.0, 'dir': direction, 'radius': 80}
        d = corner_track_usage(ld, off, c, 1000.0, left, right, 880.0, 120.0, next_corner=following)
        assert d['exit_treatment'] == 'normal'
        assert d['track_usage'] < 100


def test_configured_interior_exit_keeps_distance_without_exit_penalty():
    ld, left, right = geometry()
    off = np.interp(ld, [0, 150, 230, 1000], [-5.15, -5.15, 5.15, 5.15])
    c = {'name': 'T1', 'apex': 250.0, 'dir': 'left', 'radius': 80, 'exit_policy': 'compromise'}
    d = corner_track_usage(ld, off, c, 1000, left, right, 1000, 1000)
    assert d['exit_treatment'] == 'configured_compromise'
    assert 'intended line' in d['exit_reason'] and d['next_corner'] is None
    assert abs(d['exit_gap_m'] - 10.3) < 1e-9
    assert d['exit_usage_score'] == 0 and d['track_usage'] == 100


def test_explicit_wide_policy_keeps_exit_scoring_in_a_linked_sequence():
    ld, left, right = geometry()
    off = np.interp(ld, [0, 150, 230, 350, 370, 430, 1000], [-5.15, -5.15, 5.15, 5.15, -5.15, 5.15, 5.15])
    c = {'name': 'T1', 'apex': 250.0, 'dir': 'left', 'radius': 80, 'exit_policy': 'wide'}
    d = corner_track_usage(ld, off, c, 1000, left, right, 880, 120,
                           next_corner={'name': 'T2', 'apex': 370, 'dir': 'right', 'radius': 80})
    assert d['exit_treatment'] == 'normal' and d['track_usage'] == 75


def test_one_next_entry_spike_does_not_claim_combo_compromise():
    ld, left, right = geometry()
    off = np.interp(ld, [0, 150, 230, 266, 280, 1000], [-5.15, -5.15, 5.15, 5.15, 0, 0])
    off[np.argmin(abs(ld - 330))] = 5.15
    d = corner_track_usage(ld, off, {'name': 'T1', 'apex': 250.0, 'dir': 'left', 'radius': 80},
                           1000.0, left, right, 880.0, 120.0,
                           next_corner={'name': 'T2', 'apex': 370.0, 'dir': 'right', 'radius': 80})
    assert d['exit_treatment'] == 'normal'


def test_a_straight_between_opposing_turns_keeps_normal_exit_scoring():
    ld, left, right = geometry()
    off = np.interp(ld, [0, 150, 230, 400, 410, 1000], [-5.15, -5.15, 5.15, 5.15, -5.15, -5.15])
    curvature = np.zeros(100)
    curvature[23:27], curvature[39:43] = 0.0125, -0.0125
    d = corner_track_usage(ld, off, {'name': 'T1', 'apex': 250.0, 'dir': 'left', 'radius': 80},
                           1000.0, left, right, 840.0, 160.0,
                           next_corner={'name': 'T2', 'apex': 410.0, 'dir': 'right', 'radius': 80},
                           curvature=curvature)
    assert d['exit_treatment'] == 'normal'
    assert d['track_usage'] == 75


def test_missing_exit_edge_stays_unavailable_without_losing_apex_distance():
    ld, left, right = geometry()
    right[(np.arange(len(right)) * 5 >= 266) & (np.arange(len(right)) * 5 <= 750)] = np.nan
    off = -5.15 + 10.3 * np.exp(-((ld - 250) / 48) ** 4)
    d = usage(ld, off, left, right)
    assert d['apex_gap_m'] is not None
    assert d['exit_gap_m'] is None and d['track_usage'] is None
    assert d['exit_treatment'] == 'unavailable' and d['edge_source'] == 'estimated'
    empty = corner_track_usage(ld, off, {'apex': 250, 'dir': 'left'}, 1000, [], [], 1000, 1000)
    assert empty['exit_gap_m'] is None


def test_corner_at_lap_wrap_reports_both_sides_without_a_false_gap():
    ld, left, right = geometry()
    rel = (ld - 20 + 500) % 1000 - 500
    off = -5.15 + 10.3 * np.exp(-(rel / 48) ** 4)
    d = corner_track_usage(ld, off, {'name': 'T1', 'apex': 20.0, 'dir': 'left', 'radius': 80},
                           1000.0, left, right, 1000.0, 1000.0)
    assert d['track_usage'] > 99
    assert d['exit_gap_m'] == 0 and d['entry_gap_m'] == 0


def test_driver_and_corner_outputs_include_distance_and_geometry_provenance():
    ld, left, right = geometry()
    radius = 1000 / (2 * np.pi)
    angle = ld / radius
    ref = (ld, radius * np.cos(angle), radius * np.sin(angle))
    off = -5.15 + 10.3 * np.exp(-((ld - 250) / 48) ** 4)
    fr = pd.DataFrame({'name': 'Jax', 'dist': ld, 't': ld / 20, 'speed': 20,
                       'x': (radius - off) * np.cos(angle), 'z': (radius - off) * np.sin(angle)})
    laps = pd.DataFrame([{'name': 'Jax', 'lap': 1, 'clean': True}])
    corners = [{'name': 'T1', 'apex': 250.0, 'dir': 'left', 'radius': 80}]
    drivers, detail = driving_metrics(fr, laps, corners, 1000, ref, {'left': left, 'right': right, 'source': 'mixed'})
    assert drivers.exit_gap_m.iat[0] == 0
    assert drivers.track_edge_source.iat[0] == detail.edge_source.iat[0] == 'mixed'
    assert detail.laps_measured.iat[0] == 1 and detail.exit_compromise_share.iat[0] == 0
    assert detail.exit_gap_m.iat[0] == 0 and detail.exit_treatment.iat[0] == 'normal'
    missing_drivers, missing_detail = driving_metrics(fr, laps, corners, 1000)
    assert missing_drivers.exit_gap_m.isna().all()
    assert missing_detail.exit_gap_m.isna().all()
    assert missing_detail.exit_treatment.iat[0] == 'unavailable'
