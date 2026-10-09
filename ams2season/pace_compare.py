"""Observed lap gaps and cautious geometry estimates, never causal pedal attribution.

Timing partitions cover the entire lap exactly once. The extra-path estimate asks
what additional measured distance costs at the driver's current speed. It does
not model the speed benefit of a wider radius, grip, traffic or a different car.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .derive import Session, add_distance, completed_lap_time, effective_track_length
from .quali import session_laps

VERSION = 1
GRID_M = 5.0


def lap_catalog(sess: Session) -> tuple[float, dict]:
    """Best valid, supported full flying lap per driver, with exact timing endpoints."""
    L, _ = effective_track_length(sess.frames, sess.L)
    if not math.isfinite(L) or L <= 0:
        return L, {}
    fr = add_distance(sess.frames, L, sess.green_t if sess.type == 'race' else None)
    grid = np.r_[np.arange(0, L, GRID_M), L]
    out = {}
    for name, g in fr.groupby('name', sort=False):
        g = g.sort_values('t')
        if 'race_state' in g and sess.type == 'race':
            from .shm import RACESTATE_FINISHED
            finished = g.loc[g.race_state == RACESTATE_FINISHED, 't']
            if len(finished):
                g = g[g.t <= float(finished.iloc[0]) + 0.1]
        lp = session_laps(g, L)
        if not len(lp):
            continue
        lp = lp[lp.valid & (lp.time > 0)]
        if sess.type == 'race':
            lp = lp[lp.k >= 1]
        supported = []
        for row in lp.itertuples():
            _, official = completed_lap_time(g.t.to_numpy(), g.last_lap.to_numpy(), row.t1, row.own)
            window = g[(g.t >= row.t0) & (g.t <= row.t1 + 1)]
            progressed = 'laps_completed' in window and window.laps_completed.max() > window.laps_completed.min()
            if official or progressed:
                supported.append(row.Index)
        lp = lp.loc[supported]
        if not len(lp):
            continue
        row = lp.sort_values('time').iloc[0]
        sl = g[(g.t >= row.t0 - 1.5) & (g.t <= row.t1 + 1.5)]
        if len(sl) < 40 or not {'x', 'z', 'speed'} <= set(sl):
            continue
        d = np.maximum.accumulate(sl.dist.to_numpy(float)) - row.k * L
        keep = np.r_[True, np.diff(d) > 1e-3]
        d, ts = d[keep], sl.t.to_numpy(float)[keep]
        if d[0] > 5 or d[-1] < L - 5:
            continue
        tabs = np.interp(grid, np.r_[0, d[(d > 0) & (d < L)], L],
                         np.r_[row.t0, ts[(d > 0) & (d < L)], row.t1])
        elapsed = (tabs - row.t0) * float(row.time / row.own)
        elapsed[0], elapsed[-1] = 0.0, float(row.time)
        item = {'name': name, 'car': str(g.car.mode().iloc[0]), 'time': float(row.time),
                'lap': int(row.k) + 1, 'valid_laps': len(lp), 'grid': grid, 't': elapsed,
                'x': np.interp(grid, d, sl.x.to_numpy(float)[keep]),
                'z': np.interp(grid, d, sl.z.to_numpy(float)[keep]),
                'v': np.interp(grid, d, sl.speed.to_numpy(float)[keep]) * 3.6}
        local = sess.local
        if name == (sess.meta.get('local') or {}).get('name') and local is not None and len(local):
            from .technique import _local_lap_usable
            lo = local[(local.t >= row.t0 - 1) & (local.t <= row.t1 + 1)].sort_values('t')
            local_times = lo.t.to_numpy(float)
            gaps = np.flatnonzero(np.diff(local_times) > 2.0)
            gap_in_lap = ((local_times[gaps] < row.t1) & (local_times[gaps + 1] > row.t0)).any()
            usable = (len(lo) >= 40 and np.isfinite(local_times).all() and not gap_in_lap
                      and _local_lap_usable(local, g, float(row.t0), float(row.t1)))
            if usable and lo.t.min() <= row.t0 + 0.15 and lo.t.max() >= row.t1 - 0.15:
                for key, column in (('brake', 'brake'), ('throttle', 'throttle')):
                    if column in lo and np.isfinite(lo[column]).all():
                        item[key] = np.interp(tabs, lo.t, lo[column]) * 100
                if 'gear' in lo:
                    ix = np.clip(np.searchsorted(lo.t.to_numpy(), tabs, side='right') - 1, 0, len(lo) - 1)
                    item['gear'] = lo.gear.to_numpy()[ix]
        out[name] = item
    if out:
        from .race import _norm, find_ghosts
        timed = pd.DataFrame([{'name': name, 'lap': 2, 'time': lap['time']} for name, lap in out.items()])
        local_name = (sess.meta.get('local') or {}).get('name')
        ghosts = find_ghosts(fr, timed, sess.green_t or float(fr.t.min()), {_norm(local_name)} if local_name else set())
        out = {name: lap for name, lap in out.items() if name not in ghosts}
    return L, out


def _smooth_xy(lap, window):
    points = np.c_[lap['x'], lap['z']]
    unique = points[:-1]
    pad = window // 2
    padded = np.vstack([unique[-pad:], unique, unique[:pad]]) if pad else unique
    clean = pd.DataFrame(padded).rolling(window, center=True, min_periods=window).mean().to_numpy()
    clean = clean[pad:pad + len(unique)]
    return np.vstack([clean, clean[0]])


def _marker(lap, apex, before, after, L):
    """Real sustained brake marker when available; deceleration is explicitly a proxy."""
    from .technique import _brake_event
    xs = np.arange(-320, min(20, after / 2) + 0.1, 2.0)
    ld = (apex + xs) % L
    near = np.arange(-min(150, before / 2), min(100, after / 2) + 0.1, 2.0)
    speed = np.interp((apex + near) % L, lap['grid'], lap['v'])
    result = {'brake_at_m': None, 'brake_source': 'unavailable', 'deceleration_at_m': None,
              'min_speed_kph': float(np.min(speed)) if len(speed) else None,
              'pickup_at_m': None}
    if 'brake' in lap:
        B = np.interp(ld, lap['grid'], lap['brake'])
        event = _brake_event(xs, B, (-before / 2, min(20, after / 2)))
        if event:
            result.update(brake_at_m=float(xs[event[1]]), brake_source='pedals')
    dt = np.diff(lap['t'])
    accel = np.diff(lap['v'] / 3.6) / np.maximum(dt, 1e-5)
    acc = pd.Series(accel).rolling(5, center=True, min_periods=1).mean().to_numpy()
    proxy = np.interp(ld, lap['grid'][:-1], acc)
    from .technique import _runs
    candidates = []
    for a, b in _runs((proxy < -2.5) & (xs < 10)):
        if b - a >= 4 and a > 0:
            peak = a + int(np.argmin(proxy[a:b]))
            if xs[peak] >= -before / 2:
                candidates.append((float(np.sum(-proxy[a:b])), float(xs[a])))
    if candidates:
        result['deceleration_at_m'] = max(candidates)[1]
        if 'brake' not in lap:
            result.update(brake_at_m=result['deceleration_at_m'], brake_source='deceleration')
    if 'throttle' in lap:
        # Reuse the same shift filtering and onset ownership as technique scoring.
        from .technique import _filter_throttle, _lap_metrics
        xt = np.arange(max(-60, -before / 2), min(320, after / 2) + 0.1, 2.0)
        filtered, _ = _filter_throttle(lap)
        T = np.interp((apex + xt) % L, lap['grid'], filtered)
        B = np.interp(ld, lap['grid'], lap['brake']) if 'brake' in lap else np.zeros(len(xs))
        times = np.interp((apex + xt) % L, lap['grid'], lap['t']) + np.floor((apex + xt) / L) * lap['time']
        metrics = _lap_metrics(xs, B, xt, T, near, speed, (-before / 2, min(20, after / 2)), times)
        result['pickup_at_m'] = metrics.get('pickup')
    return result


def compare_laps(mine, reference, corners, L):
    """Pure comparison on a shared distance grid; useful for tests and every session type."""
    grid = np.asarray(mine['grid'], float)
    if len(grid) < 10 or not np.allclose(grid, reference['grid']):
        raise ValueError('Lap distance grids must match.')
    mt, rt = np.asarray(mine['t']), np.asarray(reference['t'])
    if not np.isfinite(mt).all() or not np.isfinite(rt).all() or np.any(np.diff(mt) <= 0) or np.any(np.diff(rt) <= 0):
        raise ValueError('Lap timing must be finite and increase.')
    midpoint = (grid[:-1] + grid[1:]) / 2
    delta = np.diff(mt) - np.diff(rt)
    corners = sorted([c for c in corners if c.get('apex') is not None], key=lambda c: c['apex'])
    if not corners:
        return {'available': False, 'reason': 'No corners could be identified for a pace breakdown.'}
    ap = np.array([c['apex'] for c in corners])
    rel = (midpoint[:, None] - ap[None, :] + L / 2) % L - L / 2
    owner = np.argmin(np.abs(rel), axis=1)
    # Geometric noise is smoothed over 15–35m. The spread is sensitivity to
    # smoothing, not a statistical confidence interval or a physics simulation.
    paths = []
    for window in (3, 5, 7):
        ours, theirs = _smooth_xy(mine, window), _smooth_xy(reference, window)
        paths.append((np.linalg.norm(np.diff(ours, axis=0), axis=1),
                      np.linalg.norm(np.diff(theirs, axis=0), axis=1)))
    distance = np.linalg.norm(_smooth_xy(mine, 5) - _smooth_xy(reference, 5), axis=1)
    geometry_ok = all(np.isfinite(p).all() and np.median(p) > 0.1 and np.max(p) < 4 * GRID_M + 15 for pair in paths for p in pair)
    same_car = mine.get('car') == reference.get('car')
    rows = []
    for ci, c in enumerate(corners):
        mask = owner == ci
        if not mask.any():
            continue
        before = (ap[ci] - ap[ci - 1]) % L if len(ap) > 1 else L
        after = (ap[(ci + 1) % len(ap)] - ap[ci]) % L if len(ap) > 1 else L
        r = rel[:, ci]
        band = min(20, before / 4, after / 4)
        phases = {'approach': float(delta[mask & (r < -band)].sum()),
                  'corner': float(delta[mask & (np.abs(r) <= band)].sum()),
                  'exit': float(delta[mask & (r > band)].sum())}
        gap = float(delta[mask].sum())
        shape_gap = float(np.median(distance[:-1][mask])) if geometry_ok else None
        mine_marker = _marker(mine, ap[ci], before, after, L)
        ref_marker = _marker(reference, ap[ci], before, after, L)
        notes = []
        brake_delta = None
        both_pedals = mine_marker['brake_source'] == ref_marker['brake_source'] == 'pedals'
        marker_key = 'brake_at_m' if both_pedals else 'deceleration_at_m'
        if mine_marker[marker_key] is not None and ref_marker[marker_key] is not None:
            brake_delta = mine_marker[marker_key] - ref_marker[marker_key]
            if abs(brake_delta) >= 6:
                verb = 'Braking' if both_pedals else 'Deceleration'
                notes.append(f"{verb} begins {abs(brake_delta):.0f} m {'later' if brake_delta > 0 else 'earlier'} than the reference.")
        speed_delta = mine_marker['min_speed_kph'] - ref_marker['min_speed_kph']
        if abs(speed_delta) >= 2:
            notes.append(f"Minimum speed is {abs(speed_delta):.1f} km/h {'lower' if speed_delta < 0 else 'higher'}.")
        pickup_delta = None
        if mine_marker['pickup_at_m'] is not None and ref_marker['pickup_at_m'] is not None:
            pickup_delta = mine_marker['pickup_at_m'] - ref_marker['pickup_at_m']
            if abs(pickup_delta) >= 6:
                notes.append(f"Sustained throttle pickup is {abs(pickup_delta):.0f} m {'later' if pickup_delta > 0 else 'earlier'}.")
        if shape_gap is not None and shape_gap >= 0.75:
            notes.append(f"Recorded paths differ by about {shape_gap:.1f} m through this section.")
        estimate, sensitivity = None, None
        if same_car and geometry_ok:
            estimates = []
            for ours, theirs in paths:
                extra = max(0.0, float((ours[mask] - theirs[mask]).sum()))
                # Constant current speed over the section is a counterfactual
                # assumption; bound the estimate by the observed positive gap.
                speed = float(np.average((mine['v'][:-1][mask] + mine['v'][1:][mask]) / 7.2,
                                         weights=np.diff(mt)[mask]))
                estimates.append(min(max(gap, 0), extra / max(speed, 5)))
            if shape_gap is not None and shape_gap < 0.5:
                estimates = [0.0] * len(estimates)
            estimate = float(np.median(estimates))
            sensitivity = [float(min(estimates)), float(max(estimates))]
        rows.append({'corner': c['name'], 'apex': float(c['apex']), 'gap_s': gap,
                     'phase_gap_s': phases, 'line_deviation_m': shape_gap,
                     'extra_path_estimate_s': estimate, 'extra_path_sensitivity_s': sensitivity,
                     'brake_marker_delta_m': brake_delta, 'minimum_speed_delta_kph': speed_delta,
                     'brake_comparison_source': 'pedals' if both_pedals else 'deceleration',
                     'pickup_delta_m': pickup_delta, 'mine': mine_marker, 'reference': ref_marker,
                     'observations': notes})
    available = [r for r in rows if r['extra_path_estimate_s'] is not None]
    total_gap = float(mt[-1] - rt[-1])
    return {'available': True, 'driver': mine['name'],
            'reference': {'driver': reference['name'], 'car': reference['car'], 'lap': reference['lap'],
                          'time_s': reference['time'], 'valid_laps': reference['valid_laps'],
                          'pedals_available': 'brake' in reference},
            'lap': mine['lap'], 'time_s': mine['time'], 'gap_s': total_gap, 'same_car': same_car,
            'extra_path_estimate_s': min(max(total_gap, 0), sum(r['extra_path_estimate_s'] for r in available)) if available else None,
            'line_estimate_reason': None if available else ('Different car models; geometry-only time estimate is unavailable.' if not same_car else 'Position telemetry is insufficient for a geometry estimate.'),
            'method': 'Extra recorded path distance at your current speed, bounded by measured time loss. A shorter path can reduce corner speed, so this is not an optimal-line prediction. Braking, grip and line effects overlap; do not add this estimate to the measured gap.',
            'confidence': 'low', 'corners': rows,
            'trace': {'distance_m': grid.tolist(), 'gap_s': (mt - rt).tolist()}}


def pace_comparison(sess, driver, corners, reference_session=None, reference_name=None, reference_kind='fastest',
                    track_samples=None, track_width=None, catalogs=None):
    L, mine_catalog = catalogs or lap_catalog(sess)
    mine = mine_catalog.get(driver)
    if mine is None:
        return {'available': False, 'reason': 'No valid, complete flying lap with supported timing is recorded for this driver.'}
    other_session = reference_session is not None and reference_session is not sess
    if other_session:
        for key in ('track_location', 'track_variation'):
            if sess.meta.get(key) != reference_session.meta.get(key):
                return {'available': False, 'reason': 'Reference and driver must use the same track layout.'}
        other_L, ref_catalog = lap_catalog(reference_session)
        if abs(other_L - L) > 1:
            return {'available': False, 'reason': 'Reference track distance differs from this recording.'}
    else:
        ref_catalog = mine_catalog
    if reference_kind == 'same_car':
        candidates = [v for v in ref_catalog.values() if v['car'] == mine['car']]
    else:
        candidates = list(ref_catalog.values())
    if reference_name:
        reference = ref_catalog.get(reference_name)
    else:
        reference = min(candidates, key=lambda x: x['time']) if candidates else None
    if reference is None:
        return {'available': False, 'reason': 'The selected reference has no valid complete recorded flying lap.'}
    if other_session and not np.array_equal(mine['grid'], reference['grid']):
        # Less than a metre of estimated track-length variation is normalized.
        ref_grid = reference['grid'] * (L / other_L)
        reference = dict(reference, grid=mine['grid'])
        for key in ('t', 'x', 'z', 'v', 'brake', 'throttle'):
            if key in reference:
                reference[key] = np.interp(mine['grid'], ref_grid, reference[key])
        if 'gear' in reference:
            indices = np.clip(np.searchsorted(ref_grid, mine['grid'], side='right') - 1, 0, len(ref_grid) - 1)
            reference['gear'] = np.asarray(reference['gear'])[indices]
    result = compare_laps(mine, reference, corners, L)
    if not result.get('available'):
        return result
    result.update(reference_kind=reference_kind, same_session=not other_session)
    if other_session:
        result['context'] = 'Qualifying and race conditions, fuel and tyres can differ; this is a pace comparison, not isolated driver time loss.'
    elif not result['same_car']:
        result['context'] = 'Different car models contribute to the pace gap; pedal and speed differences are observations, not proven causes.'
    else:
        result['context'] = 'Best recorded valid flying laps. Traffic, setup, tyres and conditions can still differ.'
    self_reference = not other_session and reference['name'] == mine['name']
    if self_reference:
        result['context'] += ' Your own fastest lap is the reference; no faster recorded lap is available in this selection.'
    from .derive import curvature_profile
    from .metrics import _linked_exit
    corners = sorted(corners, key=lambda c: c['apex'])
    curvature = curvature_profile(mine['grid'], mine['x'], mine['z'], L)
    exempt = {c['name'] for c in corners if c.get('exit_policy') == 'compromise'}
    for ci, c in enumerate(corners):
        following = corners[(ci + 1) % len(corners)]
        if _linked_exit(c, following, L, curvature):
            exempt.update((c['name'], following['name']))
    for row in result['corners']:
        if self_reference:
            row['extra_path_estimate_s'] = None
            row['extra_path_sensitivity_s'] = None
            row['line_estimate_reason'] = 'Your own lap is the reference; no independent line comparison is available.'
        elif row['corner'] in exempt:
            row['extra_path_estimate_s'] = None
            row['extra_path_sensitivity_s'] = None
            row['line_estimate_reason'] = 'Coupled or intentionally narrow line; no isolated path-cost estimate.'
    # The road geometry uses the driver's own session, including recorded edge
    # touches. It never presumes that a reference driver's widest line is optimal.
    try:
        from .metrics import corner_track_usage
        from .trackmap import Ref, recording_edge_samples, track_geometry
        fr = add_distance(sess.frames, L, sess.green_t if sess.type == 'race' else None)
        geo = track_geometry(fr, mine['grid'], mine['x'], mine['z'], L, samples=track_samples,
                             width=track_width, extra_samples=recording_edge_samples(sess), cloud_points=0)
        edges = geo['offsets']
        ref = Ref(mine['grid'], mine['x'], mine['z'], L)
        source = geo.get('edges', {}).get('source', 'estimated')
        corners = sorted(corners, key=lambda c: c['apex'])
        for ci, c in enumerate(corners):
            row = next((r for r in result['corners'] if r['corner'] == c['name']), None)
            if row is None:
                continue
            before = (c['apex'] - corners[ci - 1]['apex']) % L if len(corners) > 1 else L
            after = (corners[(ci + 1) % len(corners)]['apex'] - c['apex']) % L if len(corners) > 1 else L
            detail = corner_track_usage(mine['grid'][:-1], np.zeros(len(mine['grid']) - 1), c, L,
                                        np.asarray(edges['left']), np.asarray(edges['right']), before, after,
                                        next_corner=corners[(ci + 1) % len(corners)], curvature=curvature, edge_source=source)
            row['track_usage'] = detail
            if detail and detail.get('exit_treatment') in ('linked_corner', 'configured_compromise'):
                row['observations'].append(detail['exit_reason'])
                row['extra_path_estimate_s'] = None
                row['extra_path_sensitivity_s'] = None
    except (ImportError, KeyError, ValueError, IndexError) as exc:
        result['track_usage_reason'] = f'Exit-edge measurement unavailable: {exc}'
    valid = [r['extra_path_estimate_s'] for r in result['corners'] if r['extra_path_estimate_s'] is not None]
    result['extra_path_estimate_s'] = min(max(result['gap_s'], 0), sum(valid)) if valid else None
    if not valid and result['line_estimate_reason'] is None:
        result['line_estimate_reason'] = ('Your own lap is the reference; no independent line comparison is available.' if self_reference
                                        else 'All measured corners require a coupled or intentionally narrow line.')
    return result
