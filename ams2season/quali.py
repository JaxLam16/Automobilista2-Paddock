"""Qualifying analysis: every driver's best lap on one shared lap-distance grid.

Putting all best laps on the same 2 m grid makes the interesting comparisons trivial:
  * time gap at any point on track = t_driver[i] - t_reference[i]  (the delta trace)
  * position mode: every car at the same lap distance, so racing lines can be compared directly
  * braking / throttle points per corner, minimum corner speeds, sector times

Real driver inputs (throttle, brake, steering, gear) exist only for the car on the PC that recorded.
Pass the other recordings of the same session as `extra_recordings` and each friend's own inputs are
attached to their best lap (matched by lap time, aligned by lap distance, so no clock sync is needed).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import shm as S
from .derive import (Session, _last_valid, add_distance, detect_corners, effective_track_length, load_session)
from .race import _norm, find_ghosts
from .replay import BODY_TYPES, body_type, heading_calibration, row_heading
from .report import HUMAN_COLORS, _clean

GRID_M = 2.0
PIT_LANE = [S.PIT_MODE_DRIVING_INTO_PITS, S.PIT_MODE_IN_PIT, S.PIT_MODE_DRIVING_OUT_OF_PITS,
            S.PIT_MODE_IN_GARAGE, S.PIT_MODE_DRIVING_OUT_OF_GARAGE]


@dataclass
class QualiAnalysis:
    session: Session
    L: float
    classification: pd.DataFrame
    laps: pd.DataFrame
    best: dict
    corners: list
    track: list
    warnings: list = field(default_factory=list)


def session_laps(g: pd.DataFrame, L: float) -> pd.DataFrame:
    """Every complete lap (line to line) for one car, with validity and the game's lap time."""
    t, d = g.t.to_numpy(), g.dist.to_numpy()
    if len(t) < 10:
        return pd.DataFrame()
    dm = np.maximum.accumulate(d)
    keep = np.r_[True, np.diff(dm) > 0]
    tx, dx = t[keep], dm[keep]
    k0, k1 = int(math.ceil(dx[0] / L + 1e-9)), int(math.floor(dx[-1] / L))
    if k1 - k0 < 1:
        return pd.DataFrame()
    ks = np.arange(k0, k1 + 1)
    T = np.interp(ks * L, dx, tx)
    last_lap, inv, pit = g.last_lap.to_numpy(float), g.lap_invalid.to_numpy(bool), g.pit_mode.to_numpy()
    s1v, s2v = g.cur_s1.to_numpy(float), g.cur_s2.to_numpy(float)
    rows = []
    for i in range(len(ks) - 1):
        t0, t1 = T[i], T[i + 1]
        own = t1 - t0
        win = (t > t1 - 0.5) & (t <= t1 + 5) & (last_lap > 0) & (np.abs(last_lap - own) < max(0.5, 0.02 * own))
        lap_time = float(last_lap[win][0]) if win.any() else own
        in_lap = (t > t0 + 0.5) & (t <= t1)
        s1 = _last_valid(t, s1v, t0 + 0.5, t1 - 0.02)
        s2 = _last_valid(t, s2v, t0 + 0.5, t1 - 0.02)
        ok_s = s1 > 0 and s2 > 0 and s1 + s2 < lap_time - 0.5
        rows.append({"k": int(ks[i]), "t0": float(t0), "t1": float(t1), "time": lap_time, "own": own,
                     "valid": not bool(inv[in_lap].any()) and not bool(np.isin(pit[(t >= t0) & (t <= t1)], PIT_LANE).any()),
                     "s1": s1 if ok_s else np.nan, "s2": s2 if ok_s else np.nan,
                     "s3": lap_time - s1 - s2 if ok_s else np.nan})
    return pd.DataFrame(rows)


def _phases(v_kph: np.ndarray, trel: np.ndarray, thr=None, brk=None):
    """0 coast, 1 braking, 2 throttle on the distance grid. Real pedals when they were used, else
    worked out from acceleration (from speed and time along the lap)."""
    vm = v_kph / 3.6
    dtt = np.gradient(trel)
    acc = np.gradient(vm) / np.where(dtt > 1e-4, dtt, np.nan)
    acc = pd.Series(acc).rolling(9, center=True, min_periods=1).mean().to_numpy()
    if thr is not None and brk is not None and np.nanmax(brk) > 20:
        ph = np.where(brk > 5, 1, np.where(thr > 20, 2, 0))
    else:
        ph = np.where(acc < -4, 1, np.where(acc > 0.6, 2, 0))
    ph = np.where(np.isfinite(vm), ph, -1)
    return ph.astype(int), acc


def _points(ph: np.ndarray, trel: np.ndarray, grid_m: float) -> tuple[list, list]:
    """Braking points (braking held for 0.3 s+) and throttle-on points (first throttle after braking)."""
    brakes, throttles = [], []
    i, n = 1, len(ph)
    last_brake = -1e9
    while i < n:
        if ph[i] == 1 and ph[i - 1] != 1:
            j = i
            while j < n and ph[j] == 1:
                j += 1
            if trel[min(j, n - 1)] - trel[i] >= 0.3:
                brakes.append(round(i * grid_m, 1))
                last_brake = i
            i = j
            continue
        if ph[i] == 2 and ph[i - 1] != 2 and (i - last_brake) * grid_m < 600 and last_brake > 0:
            throttles.append(round(i * grid_m, 1))
            last_brake = -1e9
        i += 1
    def dedupe(pts):  # a wobble on the pedal isn't a new braking point
        out = []
        for p in pts:
            if not out or p - out[-1] > 60:
                out.append(p)
        return out
    return dedupe(brakes), dedupe(throttles)


def _local_inputs(sess: Session):
    lo = sess.local
    name = (sess.meta.get("local") or {}).get("name")
    if not name or lo is None or len(lo) < 10 or not {"throttle", "brake", "steering", "gear"} <= set(lo.columns):
        return None, None
    return name, lo


def _lap_grid(sl: pd.DataFrame, lap: pd.Series, L: float, calib, grid: np.ndarray, lo=None) -> dict:
    t = sl.t.to_numpy()
    ld = sl.dist.to_numpy() - lap.k * L
    ldm = np.maximum.accumulate(ld)
    keep = np.r_[True, np.diff(ldm) > 1e-3]
    tk, lk = t[keep], ldm[keep]
    trel = np.interp(grid, lk, tk) - lap.t0
    if trel[-1] > 0 and lap.own > 0:
        trel = trel * (lap.time / lap.own)  # stretch to the official lap time so deltas match the timing screen
    out = {"t": trel, "x": np.interp(grid, lk, sl.x.to_numpy(float)[keep]), "z": np.interp(grid, lk, sl.z.to_numpy(float)[keep]),
           "h": np.interp(grid, lk, row_heading(sl, calib)[keep]), "v": np.interp(grid, lk, sl.speed.to_numpy(float)[keep]) * 3.6}
    if lo is not None:
        lt = lo.t.to_numpy()
        tabs = np.interp(grid, lk, tk)
        if tabs[0] >= lt[0] - 1 and tabs[-1] <= lt[-1] + 1:
            gi = np.clip(np.searchsorted(lt, tabs), 0, len(lt) - 1)
            out.update({"thr": np.interp(tabs, lt, lo.throttle.to_numpy(float)) * 100,
                        "brk": np.interp(tabs, lt, lo.brake.to_numpy(float)) * 100,
                        "steer": np.interp(tabs, lt, lo.steering.to_numpy(float)) * 100,
                        "gear": lo.gear.to_numpy(float)[gi]})
    return out


def analyze_qualifying(path_or_session, humans: set[str] | None = None, extra_recordings=(), grid_m: float = GRID_M, corners_override=None,
                       track_samples=None, track_width=None) -> QualiAnalysis:
    sess = path_or_session if isinstance(path_or_session, Session) else load_session(path_or_session)
    warnings = []
    hum = {_norm(h) for h in humans} if humans else set()
    L, why = effective_track_length(sess.frames, sess.L)
    if why:
        warnings.append(why)
    fr = add_distance(sess.frames, L, None)
    groups = dict(tuple(fr.groupby("name")))
    calib = heading_calibration(groups.items())

    all_laps = []
    for name, g in groups.items():
        lp = session_laps(g, L)
        if len(lp):
            lp.insert(0, "name", name)
            all_laps.append(lp)
    laps = pd.concat(all_laps, ignore_index=True) if all_laps else pd.DataFrame(columns=["name", "k", "time", "valid"])
    if len(laps):
        ghosts = find_ghosts(fr, laps.rename(columns={"k": "lap"}).assign(lap=lambda x: x.lap + 2), float(fr.t.min()), hum)
        if ghosts:
            laps = laps[~laps.name.isin(ghosts)]
            warnings.append("ignored " + "; ".join(f"{n} ({w})" for n, w in ghosts.items()))
        med = float(laps[laps.valid].time.median()) if laps.valid.any() else float(laps.time.median())
        laps.loc[(laps.time < 0.5 * med) | (laps.time > 3 * med), "valid"] = False

    grid = np.arange(0.0, L, grid_m)
    local_name, local_lo = _local_inputs(sess)
    best, rows = {}, []
    for name, lp in laps.groupby("name"):
        g = groups[name]
        game_best = g.loc[g.fastest_lap > 0, "fastest_lap"]
        choice = None
        if len(game_best):  # the game's own fastest lap is authoritative for validity
            match = lp[(lp.time - float(game_best.iat[-1])).abs() < 0.02]
            if len(match):
                choice = match.iloc[0]
        if choice is None and lp.valid.any():
            choice = lp[lp.valid].sort_values("time").iloc[0]
        if choice is None:
            continue
        sl = g[(g.t >= choice.t0 - 1.5) & (g.t <= choice.t1 + 1.5)]
        best[name] = _lap_grid(sl, choice, L, calib, grid, local_lo if name == local_name else None)
        best[name]["inputs_from"] = sess.meta.get("label") or "this recording" if name == local_name and "thr" in best[name] else None
        valid = lp[lp.valid]
        sectors = [valid[c].min() for c in ("s1", "s2", "s3")] if len(valid) else [np.nan] * 3
        rows.append({"name": name, "car": g.car.mode().iat[0], "car_class": g.car_class.mode().iat[0],
                     "is_ai": bool(hum) and _norm(name) not in hum, "best": float(choice.time),
                     "lap_no": int((lp.k < choice.k).sum() + 1), "laps": len(lp), "valid_laps": int(lp.valid.sum()),
                     "s1": choice.s1, "s2": choice.s2, "s3": choice.s3,
                     "theoretical": float(np.sum(sectors)) if not np.isnan(sectors).any() else np.nan})

    # friends' own recordings of the same session: attach their real inputs to their best lap
    for extra in extra_recordings:
        try:
            es = load_session(extra)
        except Exception:
            continue
        en, elo = _local_inputs(es)
        if not en or en not in best or "thr" in best[en]:
            continue
        eL, _ = effective_track_length(es.frames, es.L)
        ef = add_distance(es.frames[es.frames.name == en], eL, None)
        elp = session_laps(ef, eL)
        target = next(r for r in rows if r["name"] == en)["best"]
        match = elp[(elp.time - target).abs() < 0.02] if len(elp) else elp
        if not len(match):
            continue
        lap = match.iloc[0]
        sl = ef[(ef.t >= lap.t0 - 1.5) & (ef.t <= lap.t1 + 1.5)]
        ex = _lap_grid(sl, lap, eL, None, grid * (eL / L), elo)
        if "thr" in ex:
            for c in ("thr", "brk", "steer", "gear"):
                best[en][c] = ex[c]
            best[en]["inputs_from"] = es.meta.get("label") or Path(extra).name

    return _assemble(sess, fr, L, grid, grid_m, best, rows, laps, warnings, extra_recordings, track_samples, track_width, corners_override)


def _assemble(sess, fr, L, grid, grid_m, best, rows, laps, warnings, extra_recordings=(), track_samples=None, track_width=None,
              corners_override=None):
    """Shared final steps: phases and markers per lap, classification, turns, outline and track edges."""
    for name, b in best.items():
        b["ph"], _ = _phases(b["v"], b["t"], b.get("thr"), b.get("brk"))
        b["brake_pts"], b["throttle_pts"] = _points(b["ph"], b["t"], grid_m)

    cls = pd.DataFrame(rows).sort_values("best").reset_index(drop=True) if rows else pd.DataFrame(columns=["name", "best"])
    if len(cls):
        cls.insert(0, "pos", np.arange(1, len(cls) + 1))
        cls["gap"] = cls.best - cls.best.iat[0]
    # corners from the field's median best-lap speed, in 10 m bins
    corners, track = [], []
    if best:
        V = np.vstack([b["v"] for b in best.values()]) / 3.6
        med = np.nanmedian(V, axis=0)
        nb = max(int(L / 10), 1)
        prof = np.interp(np.arange(nb) * 10 + 5, grid, med)
        pole = best[cls.name.iat[0]]
        from .derive import curvature_profile
        kap = curvature_profile(grid, pole["x"], pole["z"], L)
        from .derive import custom_corners
        corners = custom_corners(corners_override, prof, kap) if corners_override else detect_corners(prof, curvature=kap)
        for c in corners:
            i = min(int(c["apex"] / grid_m), len(grid) - 1)
            c.update({"x": float(pole["x"][i]), "z": float(pole["z"][i])})
        step = max(1, len(grid) // 900)
        track = [[float(x), float(z)] for x, z in zip(pole["x"][::step], pole["z"][::step])]
        from .trackmap import recording_edge_samples, track_geometry
        normal = {(r.name, int(r.k)) for r in laps[laps.valid].itertuples()}
        parts = [recording_edge_samples(sess)]
        for extra in extra_recordings:  # friends' recordings know where their own wheels crossed the edges
            try:
                parts.append(recording_edge_samples(load_session(extra)))
            except Exception:
                pass
        parts = [p for p in parts if p is not None and len(p)]
        geo = track_geometry(fr, grid, pole["x"], pole["z"], L, normal=normal, samples=track_samples, width=track_width,
                             extra_samples=pd.concat(parts, ignore_index=True) if parts else None)
    else:
        geo = {}
    qa = QualiAnalysis(sess, L, cls, laps, best, corners, track, warnings)
    qa.geometry = geo
    return qa


def quali_data(qa: QualiAnalysis, colors: dict | None = None, icons: dict | None = None) -> dict:
    cls = qa.classification
    humans = [n for n, ai in zip(cls.name, cls.is_ai) if not ai]
    color = {n: HUMAN_COLORS[i % len(HUMAN_COLORS)] for i, n in enumerate(humans)}
    if colors:
        color.update({n: c for n, c in colors.items() if n in color})

    def q(a, scale):
        a = np.asarray(a, float)
        return [None if not np.isfinite(v) else int(round(v * scale)) for v in a]

    laps, drivers = {}, []
    for r in cls.itertuples():
        b = qa.best[r.name]
        has = "thr" in b
        laps[r.name] = {"t": q(b["t"], 1000), "x": q(b["x"], 10), "z": q(b["z"], 10), "h": q(np.degrees(np.mod(b["h"], 2 * np.pi)), 1),
                        "v": q(b["v"], 10), "ph": [int(v) for v in b["ph"]],
                        "thr": q(b["thr"], 1) if has else None, "brk": q(b["brk"], 1) if has else None,
                        "steer": q(b["steer"], 1) if has else None, "gear": q(b["gear"], 1) if has else None,
                        "brake_pts": b["brake_pts"], "throttle_pts": b["throttle_pts"]}
        bt = body_type(r.car, r.car_class)
        ic = (icons or {}).get(r.car) or {}
        drivers.append({"name": r.name, "car": r.car, "car_class": r.car_class, "body": bt, "length": ic.get("length") or BODY_TYPES[bt][0],
                        "width": BODY_TYPES[bt][1], "icon": ic.get("url"),
                        "is_ai": bool(r.is_ai), "color": color.get(r.name), "pos": r.pos, "best": r.best, "gap": r.gap,
                        "lap_no": r.lap_no, "laps": r.laps, "valid_laps": r.valid_laps, "s1": r.s1, "s2": r.s2, "s3": r.s3,
                        "theoretical": r.theoretical, "has_inputs": has, "inputs_from": b.get("inputs_from")})
    m = qa.session.meta
    return _clean({
        "meta": {"track": m.get("track_location_translated") or m.get("track_location"),
                 "layout": m.get("track_variation_translated") or m.get("track_variation"),
                 "started_at": m.get("started_at"), "folder": qa.session.path.name},
        "L": qa.L, "grid_m": GRID_M, "n": int(math.ceil(qa.L / GRID_M)), "drivers": drivers, "laps": laps,
        "corners": qa.corners, "track": {"points": qa.track, **getattr(qa, "geometry", {})}, "warnings": qa.warnings,
    })


# --------------------------------------------------------------------------- breakdown
def _brake_for(pts, apex):
    c = [p for p in pts if apex - 450 <= p <= apex]
    return c[0] if c else None


def quali_breakdown(qa: QualiAnalysis, pinned: list | None = None) -> dict:
    """Everything you'd want from a qualifying debrief, in one dict for the breakdown page."""
    from .awards import rank
    cls, laps, best, corners = qa.classification, qa.laps, qa.best, qa.corners
    if not len(cls):
        return {}
    human = {r.name: not r.is_ai for r in cls.itertuples()}
    t_start = float(qa.session.frames.t.min())
    fr = qa.session.frames
    on = fr[~fr.pit_mode.isin(PIT_LANE)]
    vmax_session = (on.groupby("name").speed.max() * 3.6).to_dict()

    valid = laps[laps.valid & laps.name.isin(cls.name)]
    sec_best = {s: (valid.loc[valid[s].idxmin(), "name"], float(valid[s].min())) if valid[s].notna().any() else (None, None)
                for s in ("s1", "s2", "s3")}
    ideal = sum(v for _, v in sec_best.values()) if all(v for _, v in sec_best.values()) else None

    drivers, lap_lists = [], {}
    for r in cls.itertuples():
        b = best[r.name]
        el = laps[laps.name == r.name].sort_values("k")
        vl = el[el.valid]
        first_valid = float(vl.time.iat[0]) if len(vl) else None
        within = vl[vl.time <= r.best * 1.07]
        apex, brakes = {}, {}
        for c in corners:
            lo, hi = max(0, int((c["apex"] - 150) / GRID_M)), min(len(b["v"]) - 1, int((c["apex"] + 60) / GRID_M))
            apex[c["name"]] = float(np.nanmin(b["v"][lo:hi + 1]))
            bp = _brake_for(b["brake_pts"], c["apex"])
            brakes[c["name"]] = round(c["apex"] - bp, 1) if bp is not None else None
        drivers.append({
            "name": r.name, "is_ai": bool(r.is_ai), "pos": int(r.pos), "best": r.best, "gap": r.gap,
            "s1": r.s1, "s2": r.s2, "s3": r.s3, "theoretical": r.theoretical,
            "potential": (r.best - r.theoretical) if r.theoretical == r.theoretical else None,
            "laps": int(r.laps), "valid_laps": int(r.valid_laps), "invalid_laps": int(r.laps - r.valid_laps),
            "top_speed": float(vmax_session.get(r.name, np.nanmax(b["v"]))),
            "improvement": (first_valid - r.best) if first_valid else None,
            "consistency": float(within.time.std()) if len(within) >= 3 else None,
            "apex": apex, "brake_before_apex": brakes,
        })
        lap_lists[r.name] = [{"n": i + 1, "time": float(x.time), "valid": bool(x.valid), "s1": x.s1, "s2": x.s2, "s3": x.s3,
                              "at_min": round((float(x.t1) - t_start) / 60, 2)} for i, x in enumerate(el.itertuples())]
    for i, x in enumerate(drivers):
        x["interval"] = x["best"] - drivers[i - 1]["best"] if i else None
    theo = sorted([x for x in drivers if x["theoretical"] == x["theoretical"] and x["theoretical"]], key=lambda x: x["theoretical"])
    for i, x in enumerate(theo):
        x["theo_pos"] = i + 1

    corner_kings = []
    for c in corners:
        sp = sorted(drivers, key=lambda x: -x["apex"][c["name"]])
        br = sorted([x for x in drivers if x["brake_before_apex"][c["name"]] is not None], key=lambda x: x["brake_before_apex"][c["name"]])
        corner_kings.append({"corner": c["name"], "fastest": sp[0]["name"], "fastest_kph": sp[0]["apex"][c["name"]],
                             "latest_braker": br[0]["name"] if br else None,
                             "latest_brake_m": br[0]["brake_before_apex"][c["name"]] if br else None})

    # ---- awards
    A = []

    def aw(aid, group, title, winner, value, detail, score, winners=None):
        A.append({"id": aid, "group": group, "title": title, "winner": winner, "winners": winners or ([winner] if winner else []),
                  "value": value, "detail": detail, "score": score, "human": any(human.get(w) for w in (winners or [winner]) if w), "t": None})

    def fmt(x):
        m, sec = divmod(x, 60)
        return f"{int(m)}:{sec:06.3f}" if m else f"{sec:.3f}"
    p1 = drivers[0]
    if len(drivers) > 1:
        aw("q_pole", "Results", "Pole position", p1["name"], fmt(p1["best"]),
           f"{p1['name']} took pole with {fmt(p1['best'])}, {drivers[1]['best'] - p1['best']:.3f} s clear of {drivers[1]['name']}.", 9)
        tight = min(drivers[1:], key=lambda x: x["interval"])
        ahead = drivers[tight["pos"] - 2]
        split = "set identical times" if tight["interval"] < 0.0005 else f"were split by {tight['interval']:.3f} s"
        aw("q_closest", "Results", "Closest gap", tight["name"], f"{tight['interval']:.3f} s",
           f"{ahead['name']} (P{ahead['pos']}) and {tight['name']} (P{tight['pos']}) {split}.", 7,
           winners=[ahead["name"], tight["name"]])
    hums = [x for x in drivers if not x["is_ai"]]
    if hums and hums[0]["pos"] > 1:
        aw("q_best_human", "Results", "Fastest of you", hums[0]["name"], f"P{hums[0]['pos']}",
           f"{hums[0]['name']} was the quickest human, P{hums[0]['pos']}, {hums[0]['gap']:.3f} s off pole.", 8)
    if len(hums) >= 2:
        pairs = [(abs(a["best"] - b["best"]), a, b) for i, a in enumerate(hums) for b in hums[i + 1:]]
        g, a, b = min(pairs, key=lambda x: x[0])
        aw("q_human_battle", "Rivalries", "Closest friends", None, f"{g:.3f} s",
           f"{a['name']} and {b['name']} " + ("set identical times." if g < 0.0005 else f"were only {g:.3f} s apart."), 8, winners=[a["name"], b["name"]])
    owners = [v[0] for v in sec_best.values() if v[0]]
    if len(owners) == 3:
        aw("q_sectors", "Pace", "Sector kings", owners[0] if len(set(owners)) == 1 else None, " / ".join(o.split()[0] for o in owners),
           "; ".join(f"S{i + 1} {o} ({v:.3f})" for i, (o, v) in enumerate(sec_best.values())) + ".", 6, winners=list(dict.fromkeys(owners)))
    if ideal:
        aw("q_ideal", "Pace", "Ideal lap", None, fmt(ideal),
           f"The best three sectors of the session add up to {fmt(ideal)}, {p1['best'] - ideal:.3f} s under pole.", 4)
    pot = [x for x in drivers if x["potential"] is not None and x["potential"] > 0.02]
    if pot:
        x = max(pot, key=lambda x: x["potential"])
        aw("q_left_on_table", "Pace", "Left on the table", x["name"], f"{x['potential']:.3f} s",
           f"{x['name']}'s best sectors would have been {x['potential']:.3f} s quicker than their best lap"
           + (f", good for P{x['theo_pos']}." if x.get("theo_pos") and x["theo_pos"] < x["pos"] else "."), 6)
    if theo and theo[0]["name"] != p1["name"]:
        aw("q_theoretical_pole", "Pace", "Theoretical pole", theo[0]["name"], fmt(theo[0]["theoretical"]),
           f"On best sectors, {theo[0]['name']} would have taken pole from {p1['name']}.", 7)
    if corner_kings:
        cnt = pd.Series([c["fastest"] for c in corner_kings]).value_counts()
        aw("q_corner_king", "Pace", "Corner king", cnt.index[0], f"{cnt.iat[0]} of {len(corner_kings)}",
           f"{cnt.index[0]} carried the most speed through {cnt.iat[0]} of {len(corner_kings)} corners.", 6)
        lb = pd.Series([c["latest_braker"] for c in corner_kings if c["latest_braker"]]).value_counts()
        if len(lb):
            aw("q_late_braker", "Pace", "Latest braker", lb.index[0], f"{lb.iat[0]} corners",
               f"{lb.index[0]} braked latest into {lb.iat[0]} corners.", 6)
    ts = max(drivers, key=lambda x: x["top_speed"])
    aw("q_top_speed", "Pace", "Top speed", ts["name"], f"{ts['top_speed']:.0f} km/h", f"{ts['name']} hit {ts['top_speed']:.0f} km/h.", 3)
    imp = [x for x in drivers if x["improvement"] and x["improvement"] > 0.05]
    if imp:
        x = max(imp, key=lambda x: x["improvement"])
        aw("q_improver", "Consistency", "Found the most time", x["name"], f"-{x['improvement']:.3f} s",
           f"{x['name']} went {x['improvement']:.3f} s quicker from their first clean lap to their best.", 5)
    cons = [x for x in drivers if x["consistency"] is not None]
    if cons:
        x = min(cons, key=lambda x: x["consistency"])
        aw("q_consistent", "Consistency", "Metronome", x["name"], f"{x['consistency']:.3f} s", f"{x['name']}'s laps varied by just {x['consistency']:.3f} s.", 4)
    busy = max(drivers, key=lambda x: x["laps"])
    aw("q_busiest", "Consistency", "Most laps", busy["name"], str(busy["laps"]), f"{busy['name']} ran {busy['laps']} laps.", 2)
    tl = max(drivers, key=lambda x: x["invalid_laps"])
    if tl["invalid_laps"] >= 1:
        aw("q_track_limits", "Hard luck", "Track limits", tl["name"], str(tl["invalid_laps"]), f"{tl['name']} had {tl['invalid_laps']} lap(s) deleted.", 4)

    summary = f"{p1['name']} took pole with {fmt(p1['best'])}."
    if len(drivers) > 1:
        summary += f" {drivers[1]['name']} was {drivers[1]['best'] - p1['best']:.3f} s back in P2."
    if hums and hums[0]["pos"] > 1:
        summary += f" {hums[0]['name']} led the humans in P{hums[0]['pos']}."
    return {"summary": summary, "drivers": drivers, "laps": lap_lists, "sector_best": {k: {"name": v[0], "time": v[1]} for k, v in sec_best.items()},
            "ideal": ideal, "corner_kings": corner_kings, "awards": rank(A, pinned)}


# --------------------------------------------------------------------------- practice: your own laps, side by side
def analyze_practice(path_or_session, grid_m: float = GRID_M, max_laps: int = 12, track_samples=None, track_width=None,
                     corners_override=None) -> QualiAnalysis:
    """The recording driver's clean laps as if each were a separate car, so the qualifying view can race
    them against each other, compare lines and debrief where one lap found time over another."""
    sess = path_or_session if isinstance(path_or_session, Session) else load_session(path_or_session)
    name, lo = _local_inputs(sess)
    name = name or (sess.meta.get("local") or {}).get("name")
    if not name:
        raise ValueError("This recording has no driver of its own to replay.")
    L, why = effective_track_length(sess.frames, sess.L)
    warnings = [why] if why else []
    fr = add_distance(sess.frames[sess.frames.name == name], L, None)
    laps = session_laps(fr, L)
    if not len(laps) or not laps.valid.any():
        raise ValueError("No clean laps in this session to replay.")
    laps.insert(0, "name", name)
    good = laps[laps.valid]
    good = good[good.time <= good.time.min() * 1.07].sort_values("time").head(max_laps)
    calib = heading_calibration([(name, fr)])
    grid = np.arange(0.0, L, grid_m)
    car = fr.car.mode().iat[0] if len(fr) else ""
    cls = fr.car_class.mode().iat[0] if len(fr) else ""
    best, rows = {}, []
    for lap in good.itertuples():
        n = int((laps.k < lap.k).sum() + 1)
        key = f"Lap {n}"
        sl = fr[(fr.t >= lap.t0 - 1.5) & (fr.t <= lap.t1 + 1.5)]
        best[key] = _lap_grid(sl, lap, L, calib, grid, lo)
        best[key]["inputs_from"] = name if "thr" in best[key] else None
        rows.append({"name": key, "car": car, "car_class": cls, "is_ai": False, "best": float(lap.time), "lap_no": n,
                     "laps": 1, "valid_laps": 1, "s1": lap.s1, "s2": lap.s2, "s3": lap.s3, "theoretical": np.nan})
    qa = _assemble(sess, fr, L, grid, grid_m, best, rows, laps, warnings, (), track_samples, track_width, corners_override)
    qa.practice_driver = name
    return qa
