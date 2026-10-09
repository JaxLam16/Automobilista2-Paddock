"""Driving-style and car metrics for every car in a race, worked out from speed and position.

Braking point consistency: for each corner and clean lap, where hard deceleration starts before the apex;
the scatter of that point across laps, corner by corner, gives a score (100 = the same point every lap).
Throttle pickup consistency: the same for where the car starts accelerating again after the apex.
Track usage: sustained wheel-to-edge proximity at entry, apex and exit (mapped where available,
otherwise estimated). A linked corner's setup line can excuse a narrow exit when the next entry
provides evidence for it; the measured exit gap remains visible.
Car statistics: pace, best lap, top speed and results per car model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HALF_TRACK = 0.85   # wheel centre to car centre, sideways


def _lap_slices(fr: pd.DataFrame, laps: pd.DataFrame, L: float):
    """(name, lap, lap_dist, t, speed m/s, x, z) for every clean lap."""
    clean = laps[laps.clean]
    by_car = dict(tuple(fr.groupby("name")))
    for r in clean.itertuples():
        g = by_car.get(r.name)
        if g is None:
            continue
        m = (g.dist >= (r.lap - 1) * L) & (g.dist < r.lap * L)
        seg = g[m]
        if len(seg) < 40:
            continue
        yield r.name, int(r.lap), seg.dist.to_numpy() - (r.lap - 1) * L, seg.t.to_numpy(), seg.speed.to_numpy(float), \
            seg.x.to_numpy(float), seg.z.to_numpy(float)


def _sustained(mask: np.ndarray, need: int) -> int | None:
    run = 0
    for i, x in enumerate(mask):
        run = run + 1 if x else 0
        if run >= need:
            return i - need + 1
    return None


def _usage_score(gap: float, width: float) -> float:
    """Wheel-to-edge proximity on an achievable, road-width-aware scale.

    Within 40 cm of the edge earns full credit; the middle of the usable road
    earns zero for that phase. This measures the line, not the field's ranking.
    """
    room = max((width - 2 * HALF_TRACK) / 2 - 0.4, 1.0)
    return float(100 * np.clip(1 - max(0.0, gap - 0.4) / room, 0, 1))


def _edge_source(source) -> str:
    return source if source in ("mapped", "mixed") else "estimated"


def _phase_approach(rel, gap, width, mask):
    """Closest approach supported over at least 6 m and three consecutive samples.

    A low percentile over a whole phase can still reward an isolated position spike in a short
    phase. Taking the upper quartile in a short distance window requires several samples to
    support the approach. Large recording gaps cannot join otherwise separate touches.
    """
    rel, gap, width = (np.asarray(a, float) for a in (rel, gap, width))
    idx = np.flatnonzero(mask & np.isfinite(gap) & np.isfinite(width))
    if len(idx) < 3:
        return None
    idx = idx[np.argsort(rel[idx])]
    r, g, w = rel[idx], gap[idx], width[idx]
    starts = np.arange(len(r) - 2)
    ends = np.maximum(starts + 2, np.searchsorted(r, r[starts] + 6.0))
    have = ends < len(r)
    starts, ends = starts[have], ends[have]
    # Count interruptions once, then evaluate all small windows in vectorised groups.
    bad = np.r_[0, np.cumsum((np.diff(r) > 15.0) | (np.diff(r) <= 0) | (np.abs(np.diff(idx)) != 1))]
    valid = ((r[ends] - r[starts] >= 6.0) & (r[ends] - r[starts] <= 30.0)
             & (bad[ends] == bad[starts]))
    starts, ends = starts[valid], ends[valid]
    best = None
    counts = ends - starts + 1
    for count in np.unique(counts):
        si = starts[counts == count]
        win = si[:, None] + np.arange(count)
        close = np.quantile(g[win], 0.75, axis=1)
        k = int(np.argmin(close))
        if best is None or close[k] < best[0]:
            best = (float(close[k]), float(np.median(w[win[k]])))
    return best


def _linked_exit(c, next_corner, L, curvature):
    """Whether normal outside exit and the next corner's outside entry conflict.

    Opposite-direction turns need incompatible outside edges. Same-direction turns usually
    share their outside edge, so short spacing alone must not excuse a missed exit. A long
    straight between opposing turns leaves time to use the ordinary outside exit as well.
    This only identifies a candidate; the driven next-entry line must also support relief.
    """
    if next_corner is None or c.get("dir") not in ("left", "right") or next_corner.get("dir") not in ("left", "right"):
        return False
    span = (float(next_corner["apex"]) - float(c["apex"])) % L
    if c["dir"] == next_corner["dir"] or not 20.0 <= span <= 180.0:
        return False
    if curvature is not None:
        kap = np.asarray(curvature, float)
        if not len(kap):
            return False
        step = L / len(kap)
        loc = (float(c["apex"]) + np.arange(0, span + step / 2, step)) % L
        k = kap[np.minimum((loc / step).astype(int), len(kap) - 1)]
        if not np.isfinite(k).all():
            return False
        if _sustained(np.abs(k) < 1 / 800, max(2, int(np.ceil(45.0 / step)))) is not None:
            return False
    return True


def corner_track_usage(ld, off, c, L, left, right, before, after, *, next_corner=None,
                       curvature=None, edge_source="estimated") -> dict:
    """One lap's sustained entry/apex/exit wheel gaps, and a conservative exit policy.

    Distances are measured regardless of scoring policy. A narrow exit is excused only for a
    nearby opposing turn when the observed line reaches that next turn's outside entry, or
    when the track's configured ``exit_policy='compromise'`` excludes wide-exit scoring.
    ``exit_policy='wide'`` explicitly keeps ordinary scoring even in a linked sequence.
    This is line-position evidence, not proof of the optimal line or a lap-time penalty.
    ``edge_source`` describes the supplied geometry, not per-corner mapping coverage.
    """
    from .trackmap import BIN_M
    blank = {"track_usage": None, "apex_gap_m": None, "entry_gap_m": None, "exit_gap_m": None,
             "entry_usage_score": None, "apex_usage_score": None, "exit_usage_score": None,
             "exit_treatment": "unavailable", "exit_reason": None, "next_corner": None,
             "edge_source": _edge_source(edge_source)}
    if L <= 0 or c.get("dir") not in ("left", "right") or off is None or left is None or right is None:
        return blank
    ld, off, left, right = (np.asarray(a, float) for a in (ld, off, left, right))
    if not len(left) or not len(right) or len(ld) != len(off):
        return blank
    rel = (ld - c['apex'] + L / 2) % L - L / 2
    bins = np.minimum((np.nan_to_num(ld % L) / BIN_M).astype(int), min(len(left), len(right)) - 1)
    le, ri = left[bins], right[bins]
    inside = le if c['dir'] == 'left' else ri
    outside = ri if c['dir'] == 'left' else le
    width = le - ri
    legal = (np.isfinite(ld) & np.isfinite(off) & np.isfinite(le) & np.isfinite(ri)
             & (width > 2 * HALF_TRACK) & (off >= ri - HALF_TRACK) & (off <= le + HALF_TRACK))
    band = float(np.clip((c.get('radius') or 100) * 0.2, 12, 35))
    band = min(band, before / 4, after / 4)
    phases = [('apex', -band, band, inside),
              ('entry', -min(300, before / 2), -band, outside),
              ('exit', band, min(300, after / 2), outside)]
    out = dict(blank)
    for label, start, end, edge in phases:
        near = legal & (rel >= start) & (rel <= end)
        gap = np.maximum(0.0, np.abs(edge - off) - HALF_TRACK)
        approach = _phase_approach(rel, gap, width, near)
        if approach is not None:
            close, road_width = approach
            out[f'{label}_gap_m'] = close
            out[f'{label}_usage_score'] = _usage_score(close, road_width)
    if out['exit_gap_m'] is not None:
        out['exit_treatment'] = 'normal'
    policy = c.get('exit_policy', 'auto')
    if policy == 'compromise':
        out['exit_treatment'] = 'configured_compromise'
        out['exit_reason'] = "Exit scoring disabled for this corner's intended line."
    elif policy != 'wide' and _linked_exit(c, next_corner, L, curvature):
        next_rel = (ld - next_corner['apex'] + L / 2) % L - L / 2
        next_band = float(np.clip((next_corner.get('radius') or 100) * 0.2, 12, 35))
        next_band = min(next_band, after / 4)
        next_outside = ri if next_corner['dir'] == 'left' else le
        near = legal & (next_rel >= -min(300, after / 2)) & (next_rel <= -next_band)
        next_gap = np.maximum(0.0, np.abs(next_outside - off) - HALF_TRACK)
        approach = _phase_approach(next_rel, next_gap, width, near)
        if out['exit_gap_m'] is not None and approach is not None and approach[0] <= min(1.5, 0.15 * approach[1]):
            out['exit_treatment'] = 'linked_corner'
            out['next_corner'] = next_corner.get('name')
            out['exit_reason'] = f"Narrow exit can prepare the outside entry of {next_corner.get('name', 'the next turn')}."
    # Never turn a missing scored phase into full credit. A justified/configured compromise
    # drops the exit's weight, while entry and apex carry their usual relative importance.
    exempt = out['exit_treatment'] in ('linked_corner', 'configured_compromise')
    required = ('entry', 'apex') if exempt else ('entry', 'apex', 'exit')
    if all(out[f'{p}_usage_score'] is not None for p in required):
        exit_weight = 0.0 if exempt else 0.25
        out['track_usage'] = (0.25 * out['entry_usage_score'] + 0.5 * out['apex_usage_score']
                              + exit_weight * (out['exit_usage_score'] or 0.0)) / (0.75 + exit_weight)
    return out


def _corner_usage(ld, off, c, L, left, right, before, after):
    """Compatibility wrapper for the original score/apex-gap pair."""
    d = corner_track_usage(ld, off, c, L, left, right, before, after)
    return (d['track_usage'], d['apex_gap_m']) if d['track_usage'] is not None else None


def _line_summary(details: list[dict]) -> dict:
    keys = ('track_usage', 'apex_gap_m', 'entry_gap_m', 'exit_gap_m',
            'entry_usage_score', 'apex_usage_score', 'exit_usage_score')
    out = {}
    for key in keys:
        v = [d[key] for d in details if d.get(key) is not None]
        out[key] = round(float(np.median(v)), 2 if key.endswith('_m') else 1) if v else None
    measured = [d for d in details if d.get('exit_gap_m') is not None]
    exempt = [d for d in measured if d['exit_treatment'] in ('linked_corner', 'configured_compromise')]
    treatments = {d['exit_treatment'] for d in measured}
    treatment = next(iter(treatments)) if len(treatments) == 1 else 'mixed' if measured else 'unavailable'
    out.update({'exit_treatment': treatment,
                'exit_reason': exempt[0]['exit_reason'] if exempt else None,
                'next_corner': exempt[0]['next_corner'] if exempt else None,
                'exit_compromise_share': round(100 * len(exempt) / len(measured), 1) if measured else None,
                'laps_measured': len(measured),
                'edge_source': details[0]['edge_source'] if details else 'unavailable'})
    return out


def driving_metrics(fr, laps, corners, L, ref_xy=None, edges=None, mode: str = "reduced") -> pd.DataFrame:
    rows = []
    left = right = ref = None
    curvature = None
    source = 'unavailable'
    if edges and ref_xy is not None:
        from .trackmap import BIN_M, Ref
        from .derive import curvature_profile
        ref = Ref(*ref_xy, L)
        left, right = np.asarray(edges["left"]), np.asarray(edges["right"])
        source = _edge_source(edges.get('source'))
        curvature = curvature_profile(*ref_xy, L)
    per = {}
    for name, lap, ld, t, v, x, z in _lap_slices(fr, laps, L):
        vs = pd.Series(v).rolling(5, center=True, min_periods=1).mean().to_numpy()
        dtt = np.gradient(t)
        acc = pd.Series(np.gradient(vs) / np.where(dtt > 1e-4, dtt, np.nan)).rolling(5, center=True, min_periods=1).mean().to_numpy()
        off = ref.offset(ld % L, x, z) if ref is not None else None
        for ci, c in enumerate(corners):
            a = c["apex"]
            rel = (ld - a + L / 2) % L - L / 2
            o = np.argsort(rel)
            r_, acc_ = rel[o], acc[o]
            w = (r_ >= -400) & (r_ <= 0)
            i0 = _sustained(acc_[w] < -4.0, 5)
            brake = float(-r_[w][i0]) if i0 is not None else None
            w2 = (r_ >= -30) & (r_ <= 320)
            i1 = _sustained(acc_[w2] > 0.8, 6)
            pick = float(r_[w2][i1]) if i1 is not None else None
            e = per.setdefault((name, c["name"]), {"brake": [], "pick": [], "usage": [], "apex_gap": [], "vmin": [],
                                                    "bt": [], "pt": [], "line": []})
            wv = (r_ >= -80) & (r_ <= 50)
            if wv.any():
                e["vmin"].append(float(np.nanmin(pd.Series(v[o]).rolling(3, center=True, min_periods=1).mean().to_numpy()[wv])) * 3.6)
            t_apex = float(np.interp(0.0, r_, t[o])) if len(r_) else np.nan
            t_brk = float(np.interp(-80.0, r_, t[o])) if len(r_) else np.nan
            if brake is not None:
                e["brake"].append(brake)
                e["bt"].append((t_brk, t_apex))
            if pick is not None:
                e["pick"].append(pick)
                e["pt"].append((t_brk, t_apex))
            if off is not None and c.get("dir"):
                before = (a - corners[ci - 1]['apex']) % L if len(corners) > 1 else L
                after = (corners[(ci + 1) % len(corners)]['apex'] - a) % L if len(corners) > 1 else L
                usage = corner_track_usage(ld, off, c, L, left, right, before, after,
                                           next_corner=corners[(ci + 1) % len(corners)] if len(corners) > 1 else None,
                                           curvature=curvature, edge_source=source)
                e['line'].append(usage)
                if usage['track_usage'] is not None:
                    e['usage'].append(usage['track_usage'])
                if usage['apex_gap_m'] is not None:
                    e['apex_gap'].append(usage['apex_gap_m'])
    from .traffic import MODES, racing_flags, weights, wstd
    names = sorted({k[0] for k in per})
    for n in names:
        mine = {k[1]: v for k, v in per.items() if k[0] == n}
        # was each braking / pickup made fighting another car? (checked at the braking point and the apex)
        q = [tt for v in mine.values() for pair in v["bt"] + v["pt"] for tt in pair]
        fl = iter(racing_flags(fr, n, q, L)) if q else iter(())
        for v in mine.values():
            v["bflag"] = [bool(next(fl)) | bool(next(fl)) for _ in v["bt"]]
            v["pflag"] = [bool(next(fl)) | bool(next(fl)) for _ in v["pt"]]
        sd_mode = {}
        for m in MODES:
            bs = [wstd(v["brake"], weights(v["bflag"], m)) for v in mine.values() if len(v["brake"]) >= 3]
            ts = [wstd(v["pick"], weights(v["pflag"], m)) for v in mine.values() if len(v["pick"]) >= 3]
            sd_mode[m] = ([x for x in bs if x is not None], [x for x in ts if x is not None])
        bsd, tsd = sd_mode[mode]
        flags_all = [f for v in mine.values() for f in v["bflag"] + v["pflag"]]
        per_mode = {}
        for m, (b_, t_) in sd_mode.items():
            per_mode[f"brake_consistency_{m}"] = round(float(np.clip(100 - 5 * np.median(b_), 0, 100))) if b_ else np.nan
            per_mode[f"throttle_consistency_{m}"] = round(float(np.clip(100 - 3 * np.median(t_), 0, 100))) if t_ else np.nan
        use = [u for v in mine.values() for u in v["usage"]]
        apx = [g for v in mine.values() for g in v["apex_gap"]]
        exits = [d['exit_gap_m'] for v in mine.values() for d in v['line'] if d['exit_gap_m'] is not None]
        rows.append({"name": n,
                     "brake_point_sd": round(float(np.median(bsd)), 1) if bsd else np.nan,
                     "brake_consistency": round(float(np.clip(100 - 5 * np.median(bsd), 0, 100))) if bsd else np.nan,
                     "throttle_point_sd": round(float(np.median(tsd)), 1) if tsd else np.nan,
                     "throttle_consistency": round(float(np.clip(100 - 3 * np.median(tsd), 0, 100))) if tsd else np.nan,
                     "track_usage": round(float(np.median(use))) if use else np.nan,
                     "apex_gap_m": round(float(np.median(apx)), 2) if apx else np.nan,
                     "exit_gap_m": round(float(np.median(exits)), 2) if exits else np.nan,
                     "track_edge_source": source,
                     "racing_share": round(100 * float(np.mean(flags_all))) if flags_all else np.nan, **per_mode})
    extra = ["racing_share"] + [f"{k}_consistency_{m}" for k in ("brake", "throttle") for m in MODES]
    out = pd.DataFrame(rows, columns=["name", "brake_point_sd", "brake_consistency", "throttle_point_sd",
                                      "throttle_consistency", "track_usage", "apex_gap_m", "exit_gap_m", "track_edge_source"] + extra)
    line_cols = list(_line_summary([]))
    speeds = pd.DataFrame([{"name": k[0], "corner": k[1], "vmin": float(np.median(v["vmin"])), **_line_summary(v['line'])}
                           for k, v in per.items() if v["vmin"]], columns=["name", "corner", "vmin"] + line_cols)
    return out, speeds


SLOW_KPH, FAST_KPH = 100.0, 160.0


def corner_types(speeds: pd.DataFrame, corners: list) -> list[dict]:
    """Each turn with the field's typical apex speed and whether that makes it slow, medium or fast."""
    field = speeds.groupby("corner").vmin.median() if len(speeds) else pd.Series(dtype=float)
    out = []
    for c in corners:
        v = field.get(c["name"])
        if v is None or v != v:
            continue
        kind = "slow" if v < SLOW_KPH else "fast" if v > FAST_KPH else "medium"
        out.append({"corner": c["name"], "field_kph": round(float(v), 1), "type": kind})
    return out


def strength_columns(stats: pd.DataFrame, laps: pd.DataFrame, speeds: pd.DataFrame, corners: list) -> pd.DataFrame:
    """Per driver: apex speed vs the field in slow / medium / fast corners (km/h, + = quicker) and each
    sector's median time vs the field (s, - = quicker). Stored with the race so cars can be compared."""
    types = {c["corner"]: c for c in corner_types(speeds, corners)}
    rows = []
    clean = laps[laps.clean] if len(laps) else laps
    sec = clean.groupby("name")[["s1", "s2", "s3"]].median() if len(clean) else pd.DataFrame(columns=["s1", "s2", "s3"])
    field_sec = sec.median() if len(sec) else pd.Series({"s1": np.nan, "s2": np.nan, "s3": np.nan})
    for name in stats.name:
        r = {"name": name}
        mine = speeds[speeds.name == name]
        for kind in ("slow", "medium", "fast"):
            d = [row.vmin - types[row.corner]["field_kph"] for row in mine.itertuples() if row.corner in types and types[row.corner]["type"] == kind]
            r[f"apex_delta_{kind}"] = round(float(np.mean(d)), 2) if d else np.nan
        for k in ("s1", "s2", "s3"):
            v = sec[k].get(name) if k in sec else np.nan
            r[f"{k}_delta"] = round(float(v - field_sec[k]), 3) if v == v and field_sec[k] == field_sec[k] else np.nan
        rows.append(r)
    return pd.DataFrame(rows)


def field_row(stats: pd.DataFrame) -> dict:
    """The whole field as a reference row for the car tables."""
    return {"drivers": int(len(stats)),
            "pace": float(stats.median_clean.median()) if stats.median_clean.notna().any() else None,
            "best_lap": float(stats.best_lap.min()) if stats.best_lap.notna().any() else None,
            "top_speed": float(stats.top_speed_kph.max()) if stats.top_speed_kph.notna().any() else None}


def car_stats(stats: pd.DataFrame, entrants: pd.DataFrame, speeds: pd.DataFrame | None = None) -> list[dict]:
    """Pace, results and strengths per car model in one race."""
    df = stats.merge(entrants[["name", "car", "car_class"]], on="name", how="left")
    field = df.median_clean.median()
    out = []
    for car, g in df.groupby("car"):
        pace = g.median_clean.median()
        out.append({"car": car, "car_class": g.car_class.iat[0], "drivers": int(len(g)),
                    "humans": int((~g.is_ai.astype(bool)).sum()),
                    "pace": float(pace) if pace == pace else None,
                    "pace_vs_field": float((pace / field - 1) * 100) if pace == pace and field == field else None,
                    "best_lap": float(g.best_lap.min()) if g.best_lap.notna().any() else None,
                    "top_speed": float(g.top_speed_kph.max()) if g.top_speed_kph.notna().any() else None,
                    "best_finish": int(g.finish.min()) if g.finish.notna().any() else None,
                    "avg_finish": float(g.finish.mean()) if g.finish.notna().any() else None,
                    "wins": int((g.finish == 1).sum()),
                    "brake_consistency": float(g.brake_consistency.mean()) if "brake_consistency" in g and g.brake_consistency.notna().any() else None,
                    **{k: (round(float(g[k].mean()), 3) if k in g and g[k].notna().any() else None)
                       for k in ("apex_delta_slow", "apex_delta_medium", "apex_delta_fast", "s1_delta", "s2_delta", "s3_delta")},
                    "corners": ({row.corner: round(float(row.vmin), 1) for row in
                                 speeds[speeds.name.isin(g.name)].groupby("corner", as_index=False).vmin.mean().itertuples()}
                                if speeds is not None and len(speeds) else {})})
    return sorted(out, key=lambda r: (r["pace"] is None, r["pace"] or 0))



CLEAN_AIR_S, TRAFFIC_S = 2.0, 1.5


def race_pace(laps: pd.DataFrame, is_ai: dict) -> dict:
    """How each driver's pace developed, and what traffic cost them.

    Every lap is classed by the gap to the car directly ahead at the line, at both ends of the lap: clean air
    (over 2 s both times), traffic (under 1.5 s both times) or mixed. Representative laps leave out lap 1,
    pit laps, invalid laps and anything over 107% of the driver's best."""
    L_ = laps.sort_values(["lap", "t_end"]).copy()
    L_["gap_ahead"] = L_.groupby("lap").t_end.diff()            # time behind whoever crossed this lap just before
    gaps = {(r.name, int(r.lap)): (r.gap_ahead if r.gap_ahead == r.gap_ahead else np.inf) for r in L_.itertuples()}
    drivers, rep_all = [], []
    for name, g in laps.sort_values("lap").groupby("name"):
        good = g[(g.lap > 1) & g.clean & ~g.pit.astype(bool) & g.time.notna()]
        if len(good):
            good = good[good.time <= good.time.min() * 1.07]
        rows = []
        for r in g.itertuples():
            a, b = gaps.get((name, int(r.lap) - 1), np.inf), gaps.get((name, int(r.lap)), np.inf)
            air = "clean" if a > CLEAN_AIR_S and b > CLEAN_AIR_S else "traffic" if a < TRAFFIC_S and b < TRAFFIC_S else "mixed"
            rows.append({"lap": int(r.lap), "time": None if r.time != r.time else round(float(r.time), 3),
                         "rep": bool(r.Index in good.index), "gap_ahead": None if not np.isfinite(b) else round(float(b), 2),
                         "air": air if r.lap > 1 else "start"})
        rep = good.time.to_numpy(float)
        rep_laps = good.lap.to_numpy(float)
        trend = float(np.polyfit(rep_laps, rep, 1)[0]) if len(rep) >= 4 else None
        thirds = None
        if len(rep) >= 6:
            parts = np.array_split(np.arange(len(rep)), 3)
            thirds = [round(float(np.median(rep[p])), 3) for p in parts]
        by_air = {k: [x["time"] for x in rows if x["rep"] and x["air"] == k] for k in ("clean", "traffic")}
        med = lambda v: round(float(np.median(v)), 3) if v else None
        cost = (med(by_air["traffic"]) - med(by_air["clean"])) if len(by_air["traffic"]) >= 2 and len(by_air["clean"]) >= 2 else None
        drivers.append({"name": name, "is_ai": bool(is_ai.get(name, True)), "laps": rows,
                        "best": round(float(rep.min()), 3) if len(rep) else None, "median": med(list(rep)),
                        "average": round(float(np.mean(rep)), 3) if len(rep) else None, "representative_laps": int(len(rep)),
                        "trend": None if trend is None else round(trend, 3), "thirds": thirds,
                        "clean_air": {"median": med(by_air["clean"]), "laps": len(by_air["clean"])},
                        "traffic": {"median": med(by_air["traffic"]), "laps": len(by_air["traffic"])},
                        "mixed": {"median": med([x['time'] for x in rows if x['rep'] and x['air'] == 'mixed']),
                                  "laps": sum(x['rep'] and x['air'] == 'mixed' for x in rows)},
                        "traffic_cost": None if cost is None else round(cost, 3)})
        rep_all += [(int(l), t) for l, t in zip(rep_laps, rep)]
    field = pd.DataFrame(rep_all, columns=["lap", "time"]).groupby("lap").time.median() if rep_all else pd.Series(dtype=float)
    return {"drivers": drivers, "field_by_lap": [[int(k), round(float(v), 3)] for k, v in field.items()]}
