"""Practice awards: a small number of championship points for what practice rewards that races don't.

Every award goes to the best human in the session (all tied drivers share it). Thresholds keep them honest:
a streak, a consistency or an improvement figure needs enough laps behind it to mean something.
"""
from __future__ import annotations

import numpy as np

AWARDS = [
    ("iron_man", "Iron man", "Most valid laps in a row"),
    ("mileage", "Mileage", "Most laps driven"),
    ("metronome", "Metronome", "Most consistent laps (at least 5 within 3% of their best)"),
    ("every_inch", "Every inch", "Best track usage"),
    ("most_improved", "Most improved", "Biggest gain from first flying lap to best lap"),
    ("clean_sheet", "Clean sheet", "Fewest invalid laps for the distance (at least 5 laps)"),
    ("fastest", "Fastest lap", "Fastest valid lap"),
]
DEFAULT_ENABLED = [k for k, _, _ in AWARDS if k != "fastest"]   # practice points are for everyone, not just the quick
LABEL = {k: l for k, l, _ in AWARDS}


def practice_stats(path) -> dict:
    """name -> {laps, valid, streak, consistency_s, improvement_pct, invalid_share, best, track_usage} for every car."""
    from .derive import add_distance, effective_track_length, load_session
    from .quali import session_laps
    sess = load_session(path)
    L, _ = effective_track_length(sess.frames, sess.L)
    fr = add_distance(sess.frames, L, None)
    out = {}
    for name, g in fr.groupby("name"):
        laps = session_laps(g.sort_values("t"), L)
        if not len(laps):
            continue
        times = [(float(lp.time), bool(lp.valid)) for lp in laps.itertuples() if lp.time == lp.time and lp.time > 0]
        if not times:
            continue
        valid = [t for t, v in times if v]
        streak = best_streak = 0
        for _, v in times:
            streak = streak + 1 if v else 0
            best_streak = max(best_streak, streak)
        best = min(valid) if valid else None
        near = [t for t in valid if best and t <= best * 1.03]
        flying = [t for t in valid if best and t <= best * 1.10]     # leaves out out-laps and slow-downs
        out[name] = {"laps": len(times), "valid": len(valid), "streak": best_streak, "best": best,
                     "consistency_s": round(float(np.std(near)), 3) if len(near) >= 5 else None,
                     "improvement_pct": round(100 * (flying[0] - best) / flying[0], 2) if len(flying) >= 3 else None,
                     "invalid_share": round(1 - len(valid) / len(times), 3) if len(times) >= 5 else None, "track_usage": None}
    try:   # track usage, measured the same way as in race reports
        from .derive import all_laps, curvature_profile, detect_corners, reference_lap_xy, speed_profile
        from .metrics import driving_metrics
        from .trackmap import recording_edge_samples, track_geometry
        t0 = float(fr.t.min())                 # practice has no green flag: count laps from when the recording starts
        laps_df = all_laps(fr, L, t0)
        ref_xy = reference_lap_xy(fr, laps_df, t0)
        profile = speed_profile(fr, L)
        corners = detect_corners(profile, curvature=curvature_profile(*ref_xy, L) if ref_xy else None)
        edges = None
        if ref_xy is not None:
            normal = {(r.name, int(r.lap) - 1) for r in laps_df[laps_df.clean].itertuples()}
            edges = track_geometry(fr, *ref_xy, L, normal=normal, samples=recording_edge_samples(sess), cloud_points=0).get("offsets")
        dm, _ = driving_metrics(fr, laps_df, corners, L, ref_xy, edges)
        for r in dm.itertuples():
            if r.name in out and r.track_usage == r.track_usage:
                out[r.name]["track_usage"] = float(r.track_usage)
    except Exception:
        pass
    return out


def awards(stats: dict, humans: dict, enabled: list | None = None, points: float = 1.0) -> list[dict]:
    """humans: in-game name -> championship driver key. Returns one entry per (award, winner)."""
    enabled = DEFAULT_ENABLED if enabled is None else enabled
    pool = {n: s for n, s in stats.items() if n in humans}
    rules = {  # award -> (value from stats, higher is better, how to show it)
        "iron_man": (lambda s: s["streak"] if s["streak"] >= 3 else None, True, lambda v: f"{int(v)} valid laps in a row"),
        "mileage": (lambda s: s["laps"] if s["laps"] >= 3 else None, True, lambda v: f"{int(v)} laps"),
        "metronome": (lambda s: s["consistency_s"], False, lambda v: f"laps within ±{v:.2f} s"),
        "every_inch": (lambda s: s["track_usage"], True, lambda v: f"track usage {v:.0f}/100"),
        "most_improved": (lambda s: s["improvement_pct"] if (s["improvement_pct"] or 0) > 0 else None, True, lambda v: f"{v:.1f}% quicker than their first flying lap"),
        "clean_sheet": (lambda s: s["invalid_share"], False, lambda v: f"{v:.0%} of laps invalid"),
        "fastest": (lambda s: s["best"], False, lambda v: f"{int(v // 60)}:{v % 60:06.3f}"),
    }
    out = []
    for key in enabled:
        if key not in rules:
            continue
        get, higher, show = rules[key]
        vals = {n: get(s) for n, s in pool.items()}
        vals = {n: v for n, v in vals.items() if v is not None}
        if not vals:
            continue
        best = max(vals.values()) if higher else min(vals.values())
        winners = [n for n, v in vals.items() if v == best]
        if key == "clean_sheet" and len(winners) > 1:            # equally clean: the one who drove more laps
            most = max(pool[n]["laps"] for n in winners)
            winners = [n for n in winners if pool[n]["laps"] == most]
        for n in winners:
            out.append({"award": key, "label": LABEL[key], "name": n, "driver": humans[n], "value": best, "detail": show(best),
                        "points": float(points), "shared": len(winners) > 1})
    return out
