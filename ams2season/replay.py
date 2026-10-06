"""Replay payload: every car on one shared timeline, compact enough to stream to the app.

Positions are in decimetres, race distance in metres, speed in km/h, all as integers (null when a
car isn't present). The UI interpolates between samples, so 5 Hz looks smooth.
"""
from __future__ import annotations

import numpy as np

from . import shm as S
from .race import COUNTED, RaceAnalysis
from .report import HUMAN_COLORS, _clean, _track


def _ints(values: np.ndarray, mask: np.ndarray, scale: float) -> list:
    q = np.round(np.where(mask, values, 0.0) * scale).astype(np.int64).tolist()
    for i in np.flatnonzero(~mask):
        q[i] = None
    return q


BODY_TYPES = {  # top-down silhouette family and real-world footprint (length, width in metres)
    "formula": (5.0, 1.9), "proto": (4.8, 1.95), "gt": (4.6, 2.0), "touring": (4.8, 1.9),
    "truck": (6.4, 2.5), "kart": (1.85, 1.35),
}


def body_type(car: str, car_class: str = "") -> str:
    s = f"{car} {car_class}".lower()
    if "kart" in s:
        return "kart"
    if "truck" in s:
        return "truck"
    if any(k in s for k in ("formula", "f-ultimate", "f-reiza", "f-v10", "f-v12", "f-v8", "f-classic", "f-trainer",
                             "f-usa", "f-retro", "f-vintage", "f-inter", "f-hitech", "f-3", "f3 ", "fvee", "indy",
                             "vee", "f-dallara", "open wheel")):
        return "formula"
    if any(k in s for k in ("lmp", "dpi", "prototype", "gtp", "group c", "hypercar", "p1 ", "p2 ", "p3 ", "p4 ",
                             "962", "sauber c9", "r89c", "mcr", "sigma", "metalmoro", "ligier js", "oreca", "riley")):
        return "proto"
    if any(k in s for k in ("stock car", "touring", "tcr", "sedan", "super v8", "supercars", "opala", "chevette",
                             "marcas", "turismo", "copa classic", "dtm 9")):
        return "touring"
    return "gt"


def heading_calibration(groups) -> tuple | None:
    """Which recorded Euler component is yaw, plus its sign and offset, found by matching direction of
    travel at speed. None if orientation isn't recorded (older recordings) or doesn't match well."""
    travel, comps = [], {c: [] for c in ("ox", "oy", "oz")}
    for _, g in groups:
        if len(g) < 10 or not {"ox", "oy", "oz"} <= set(g.columns):
            continue
        x, z, v = g.x.to_numpy(float), g.z.to_numpy(float), g.speed.to_numpy(float)
        dx, dz = x[2:] - x[:-2], z[2:] - z[:-2]
        m = (v[1:-1] > 15) & (np.hypot(dx, dz) > 0.5)
        travel.append(np.arctan2(dz, dx)[m])
        for c in comps:
            comps[c].append(g[c].to_numpy(float)[1:-1][m])
    if not travel:
        return None
    tr = np.concatenate(travel)
    best = None
    for c in comps:
        o = np.concatenate(comps[c]) if comps[c] else np.array([])
        if len(o) < 50 or not np.isfinite(o).all() or np.ptp(o) < 0.5:
            continue
        for sign in (1.0, -1.0):
            r = np.exp(1j * (tr - sign * o)).mean()
            if best is None or abs(r) > best[0]:
                best = (abs(r), c, sign, float(np.angle(r)))
    return best[1:] if best and best[0] > 0.95 else None


def row_heading(g, calib) -> np.ndarray:
    """Unwrapped heading (radians, world x-z plane) for each row of one car's frames."""
    if calib:
        c, sign, off = calib
        return np.unwrap(sign * g[c].to_numpy(float) + off)
    x, z, v = g.x.to_numpy(float), g.z.to_numpy(float), g.speed.to_numpy(float)
    if len(x) < 3:
        return np.zeros(len(x))
    dx, dz = np.gradient(x), np.gradient(z)
    h = np.arctan2(dz, dx)
    moving = (v > 2) & (np.hypot(dx, dz) > 1e-3)
    if moving.any():
        idx = np.where(moving, np.arange(len(h)), 0)
        np.maximum.accumulate(idx, out=idx)
        idx[:np.argmax(moving)] = np.argmax(moving)
        h = h[idx]
    return np.unwrap(h)


def _headings(fr, T: np.ndarray, groups) -> tuple[dict, str]:
    calib = heading_calibration(groups)
    out = {}
    for name, g in groups:
        if len(g) >= 2:
            out[name] = np.interp(T, g.t.to_numpy(), row_heading(g, calib))
    return out, ("orientation" if calib else "travel")


def replay_data(ra: RaceAnalysis, dt: float | None = None, colors: dict | None = None, awards: list | None = None,
                icons: dict | None = None, track_samples=None, track_width=None) -> dict:
    fr = ra.frames
    sess = ra.session
    green, end = sess.green_t, sess.end_t
    t0 = max(float(fr.t.min()), green - 6.0)
    if dt is None:  # finer timeline for normal-length races so deep zoom stays smooth; lighter for long ones
        dt = 0.1 if end - t0 <= 40 * 60 else 0.2
    T = np.arange(t0, end, dt)
    st = ra.stats.set_index("name")
    cls = ra.classification

    humans = [n for n in cls.name if not st.loc[n, "is_ai"]]
    color = {n: HUMAN_COLORS[i % len(HUMAN_COLORS)] for i, n in enumerate(humans)}
    if colors:
        color.update({n: c for n, c in colors.items() if n in color})

    cars, drivers = {}, []
    groups = fr.groupby("name")
    headings, heading_source = _headings(fr, T, groups)
    for r in cls.itertuples():
        g = groups.get_group(r.name)
        t = g.t.to_numpy()
        if len(t) < 2:
            continue
        j = np.clip(np.searchsorted(t, T), 1, len(t) - 1)
        nearest = np.where(np.abs(t[j - 1] - T) < np.abs(t[j] - T), j - 1, j)
        present = np.abs(t[nearest] - T) <= 0.6
        cars[r.name] = {
            "x": _ints(np.interp(T, t, g.x.to_numpy(float)), present, 10),
            "z": _ints(np.interp(T, t, g.z.to_numpy(float)), present, 10),
            "d": _ints(np.interp(T, t, g.dist.to_numpy(float)), present, 1),
            "v": _ints(np.interp(T, t, g.speed.to_numpy(float)) * 3.6, present, 1),
            "h": _ints(np.degrees(np.mod(headings.get(r.name, np.zeros(len(T))), 2 * np.pi)), present, 1),
        }
        rs = g.race_state.to_numpy()
        fin = t[rs == S.RACESTATE_FINISHED]
        out = t[np.isin(rs, [S.RACESTATE_RETIRED, S.RACESTATE_DNF, S.RACESTATE_DISQUALIFIED])]
        btype = body_type(r.car, r.car_class)
        drivers.append({
            "name": r.name, "car": r.car, "car_class": r.car_class, "body": btype,
            "length": ((icons or {}).get(r.car) or {}).get("length") or BODY_TYPES[btype][0], "width": BODY_TYPES[btype][1],
            "icon": ((icons or {}).get(r.car) or {}).get("url"),
            "is_ai": bool(st.loc[r.name, "is_ai"]), "color": color.get(r.name),
            "pos": r.pos, "grid": r.grid, "status": r.status,
            "finish_t": float(fin[0]) if len(fin) else None,
            "out_t": float(out[0]) if len(out) else (float(t[-1]) if r.status == "disconnected" else None),
        })

    pits = {}
    for p in ra.pits.itertuples():
        pits.setdefault(p.name, []).append([p.entry_t, p.entry_t + p.lane_time])

    lap_marks = []
    if len(ra.laps):
        first = ra.laps.groupby("lap").t_end.min()
        lap_marks = [{"lap": int(k) + 1, "t": float(v)} for k, v in first.items()]  # leader starts lap k+1

    passes = [{"t": p.t, "lap": p.lap, "corner": p.corner, "passer": p.passer, "passed": p.passed, "kind": p.kind}
              for p in ra.passes[ra.passes.kind.isin(COUNTED)].itertuples()]
    # real inputs for the car whose PC recorded the race (shared memory only exposes those locally)
    inputs = None
    local_name = (sess.meta.get("local") or {}).get("name")
    lo = sess.local
    if local_name in cars and lo is not None and len(lo) > 10 and {"throttle", "brake", "gear"} <= set(lo.columns):
        lt = lo.t.to_numpy()
        present = (T >= lt[0]) & (T <= lt[-1])
        gi = np.clip(np.searchsorted(lt, T), 0, len(lt) - 1)
        inputs = {"name": local_name,
                  "thr": _ints(np.interp(T, lt, lo.throttle.to_numpy(float)) * 100, present, 1),
                  "brk": _ints(np.interp(T, lt, lo.brake.to_numpy(float)) * 100, present, 1),
                  "gear": _ints(lo.gear.to_numpy(float)[gi], present, 1),
                  "steer": _ints(np.interp(T, lt, lo.steering.to_numpy(float)) * 100, present, 1) if "steering" in lo.columns else None}
    track = _track(ra, track_samples, track_width)
    corners = [{**c, "apex": float(rc["apex"])} for c, rc in zip(track["corners"], ra.corners)]

    m = sess.meta
    return _clean({
        "meta": {"track": m.get("track_location_translated") or m.get("track_location"),
                 "layout": m.get("track_variation_translated") or m.get("track_variation"),
                 "started_at": m.get("started_at"), "folder": sess.path.name},
        "t0": t0, "dt": dt, "n": len(T), "green_t": green, "end_t": float(T[-1]) if len(T) else end,
        "laps": int(cls.laps.max()) if len(cls) else 0, "track_length": sess.L,
        "lap_times": {n: [[int(r.lap), round(float(r.t_end), 2), None if r.time != r.time else round(float(r.time), 3), bool(r.clean)]
                          for r in g.itertuples()] for n, g in ra.laps.sort_values("lap").groupby("name")},
        "drivers": drivers, "cars": cars, "pits": pits, "lap_marks": lap_marks, "passes": passes,
        "battles": ra.battles[["a", "b", "start_t", "end_t", "laps", "winner"]].to_dict("records") if len(ra.battles) else [],
        "awards": [a for a in (awards or []) if a.get("t") is not None],
        "track": {**track, "corners": corners},
        "heading_source": heading_source, "inputs": inputs,
    })
