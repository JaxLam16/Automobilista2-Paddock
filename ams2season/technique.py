"""Driving technique from the recording car's real pedal inputs, plus tyre care.

For every corner, each lap's brake and throttle traces are lined up by distance to the apex, so laps
can be averaged into one "shape" and compared:

  brake:    where braking starts, how hard the initial hit is, how quickly it builds (attack), how long it
            trails off towards the apex
  throttle: where it's picked up after the apex, how long until it's flat, and any hesitation (lifting
            again on the way out)

Consistency per corner combines how much the shape varies lap to lap with the scatter of the key
points (braking point, pickup point). 100 = identical every lap.

Tyres: wear per lap per wheel, temperatures and pressures, and lock-ups / wheelspin found by comparing
each wheel's rotation speed with the car's speed (each wheel's radius is learned from steady driving,
because the game's slip value is obsolete).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .derive import Session, add_distance, detect_corners, effective_track_length, load_session

BRAKE_WIN = (-320.0, 60.0)    # metres relative to the apex
THROTTLE_WIN = (-60.0, 320.0)
STEP = 2.0
WHEELS = ("fl", "fr", "rl", "rr")


# --------------------------------------------------------------------------- laps of the recording car
def recording_laps(sess: Session) -> tuple[str | None, list, float]:
    """The recording car's complete laps, each with its inputs and tyre data against lap distance."""
    from .quali import session_laps
    lo = sess.local
    name = (sess.meta.get("local") or {}).get("name")
    if not name or lo is None or not len(lo) or not {"throttle", "brake"} <= set(lo.columns):
        return None, [], sess.L
    fr = sess.frames[sess.frames.name == name]
    if len(fr) < 50:
        return name, [], sess.L
    L, _ = effective_track_length(sess.frames, sess.L)
    g = add_distance(fr, L, sess.green_t if sess.type == "race" else None)
    laps = session_laps(g, L)
    if not len(laps):
        return name, [], L
    gt, gd = g.t.to_numpy(), g.dist.to_numpy()
    lt = lo.t.to_numpy()
    has_tyres = "wear_fl" in lo.columns
    out = []
    for n, lap in enumerate(laps.itertuples(), start=1):
        m = (lt >= lap.t0) & (lt <= lap.t1)
        if m.sum() < 40:
            continue
        seg = lo[m]
        ld = np.interp(seg.t.to_numpy(), gt, gd) - lap.k * L
        rec = {"n": n, "time": float(lap.time), "valid": bool(lap.valid), "t0": float(lap.t0),
               "ld": ld, "t": seg.t.to_numpy(float), "speed": seg.speed.to_numpy(float) * 3.6,
               "throttle": seg.throttle.to_numpy(float) * 100, "brake": seg.brake.to_numpy(float) * 100,
               "steer": seg.steering.to_numpy(float) * 100 if "steering" in seg.columns else None,
               "s1": lap.s1, "s2": lap.s2, "s3": lap.s3}
        if has_tyres:
            for k in ("wear", "ttemp", "press", "btemp", "rps"):
                for w in WHEELS:
                    rec[f"{k}_{w}"] = seg[f"{k}_{w}"].to_numpy(float)
        out.append(rec)
    return name, out, L


def corners_from_laps(laps: list, L: float, xy=None, custom=None) -> list[dict]:
    good = [lp for lp in laps if lp["valid"]] or laps
    if not good:
        return []
    nb = max(int(L / 10), 1)
    prof = []
    for lp in good:
        b = np.clip((lp["ld"] / 10).astype(int), 0, nb - 1)
        prof.append(pd.Series(lp["speed"] / 3.6).groupby(b).median().reindex(range(nb)).to_numpy())
    med = np.nanmedian(np.vstack(prof), axis=0)
    ok = ~np.isnan(med)
    if ok.sum() < nb * 0.5:
        return []
    med = np.interp(np.arange(nb), np.arange(nb)[ok], med[ok], period=nb)
    from .derive import curvature_profile, custom_corners
    kap = curvature_profile(*xy, L) if xy else None
    return custom_corners(custom, med, kap) if custom else detect_corners(med, curvature=kap)


# --------------------------------------------------------------------------- shapes per corner
def _rel(ld: np.ndarray, apex: float, L: float) -> np.ndarray:
    r = (ld - apex) % L
    return np.where(r > L / 2, r - L, r)


def _trace(lap: dict, key: str, apex: float, L: float, xs: np.ndarray) -> np.ndarray:
    rel = _rel(lap["ld"], apex, L)
    o = np.argsort(rel)
    r, v = rel[o], lap[key][o]
    keep = np.r_[True, np.diff(r) > 1e-3]
    r, v = r[keep], v[keep]
    out = np.interp(xs, r, v, left=np.nan, right=np.nan)
    out[(xs < r.min()) | (xs > r.max())] = np.nan
    return out


def _first(xs, arr, cond_from=None, test=lambda v: v > 5):
    for i in range(len(xs)):
        if cond_from is not None and xs[i] < cond_from:
            continue
        if not np.isnan(arr[i]) and test(arr[i]):
            return float(xs[i])
    return None


def _lap_metrics(xb, B, xt, T, speed_x, speed):
    onset = _first(xb, B)
    m = {"onset": onset}
    if onset is not None:
        after = np.where(xb >= onset, B, np.nan)
        pk = int(np.nanargmax(after))
        m["peak"] = float(B[pk])
        m["attack"] = float(xb[pk] - onset)
        rel_i = [i for i in range(len(xb)) if xb[i] >= xb[pk] and not np.isnan(B[i]) and B[i] > 5]
        m["release"] = float(xb[rel_i[-1]]) if rel_i else float(xb[pk])
        m["trail"] = m["release"] - float(xb[pk])
    vmin_i = int(np.nanargmin(np.where((speed_x > -150) & (speed_x < 100), speed, np.nan))) if np.isfinite(speed).any() else None
    m["min_speed"] = float(speed[vmin_i]) if vmin_i is not None else None
    m["min_speed_at"] = float(speed_x[vmin_i]) if vmin_i is not None else None
    start = m["min_speed_at"] if m["min_speed_at"] is not None else -20.0
    pickup = _first(xt, T, cond_from=start - 20, test=lambda v: v > 30)  # committing to the exit, not a maintenance touch
    m["pickup"] = pickup
    if pickup is not None:
        full = _first(xt, T, cond_from=pickup, test=lambda v: v > 95)
        m["full"] = full
        seg = T[(xt >= pickup) & (xt <= (full if full is not None else xt[-1]))]
        seg = seg[~np.isnan(seg)]
        drops, peak = 0, 0.0
        for v in seg:  # lifting again after picking the throttle up
            peak = max(peak, v)
            if peak - v > 15:
                drops, peak = drops + 1, v
        m["hesitations"] = drops
    return m


def _describe(m: dict) -> str:
    if m.get("onset") is None:
        return "Taken without braking: the throttle tells the story."
    parts = []
    if m.get("peak", 0) >= 85 and m.get("attack", 99) <= 12:
        parts.append("a hard initial hit")
    elif m.get("attack", 0) >= 22:
        parts.append("a progressive build-up of pressure")
    else:
        parts.append("a firm, quick build-up")
    zone = (m.get("release", 0) - m["onset"]) or 1
    if m.get("trail", 0) / zone >= 0.55:
        parts.append("a long trail into the apex")
    elif m.get("trail", 0) / zone <= 0.25:
        parts.append("an early release before the apex")
    else:
        parts.append("a moderate trail")
    if m.get("hesitations", 0) >= 1:
        parts.append("some hesitation on the throttle")
    return "Typically " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + "."


def _scores(B, T, rows, w):
    """Brake / throttle consistency for one corner, each lap weighted by w (racing corners count less)."""
    from .traffic import wstd
    W = np.asarray(w, float)[:, None]
    wavg = lambda M: np.nansum(M * W, axis=0) / np.maximum(np.nansum(W * ~np.isnan(M), axis=0), 1e-9)
    mb, mt = wavg(B), wavg(T)
    zone_b, zone_t = mb > 2, (mt > 2) & (mt < 98)
    def dev(M, m, zone):
        if not zone.any():
            return 0.0
        per = np.array([np.nanmean(np.abs(M[i, zone] - m[zone])) for i in range(len(M))])
        ok = np.isfinite(per) & (np.asarray(w) > 0)
        return float(np.average(per[ok], weights=np.asarray(w)[ok])) if ok.any() else 0.0
    brake_dev, thr_dev = dev(B, mb, zone_b), dev(T, mt, zone_t)
    on = [(r["onset"], wi) for r, wi in zip(rows, w) if r["onset"] is not None]
    pk = [(r["pickup"], wi) for r, wi in zip(rows, w) if r.get("pickup") is not None]
    onset_sd = (wstd([a for a, _ in on], [b for _, b in on]) or 0.0) if len(on) >= 2 else 0.0
    pickup_sd = (wstd([a for a, _ in pk], [b for _, b in pk]) or 0.0) if len(pk) >= 2 else 0.0
    braking = sum(r["onset"] is not None for r in rows) >= len(rows) / 2
    brake_score = float(np.clip(100 - 2.5 * brake_dev - 3.0 * onset_sd, 0, 100)) if braking else None
    thr_score = float(np.clip(100 - 2.0 * thr_dev - 1.5 * pickup_sd, 0, 100))
    overall = float(np.mean([s for s in (brake_score, thr_score) if s is not None]))
    return ({"overall": round(overall), "brake": None if brake_score is None else round(brake_score), "throttle": round(thr_score)},
            {"onset_sd": round(onset_sd, 1), "pickup_sd": round(pickup_sd, 1), "brake_dev": round(brake_dev, 1), "throttle_dev": round(thr_dev, 1)})


def corner_shapes(laps: list, corners: list, L: float, max_traces: int = 12, racing: dict | None = None,
                  mode: str = "reduced") -> list[dict]:
    """`racing` maps (lap number, corner name) -> True when that pass was made fighting another car."""
    from .traffic import MODES, weights
    xb = np.arange(BRAKE_WIN[0], BRAKE_WIN[1] + STEP, STEP)
    xt = np.arange(THROTTLE_WIN[0], THROTTLE_WIN[1] + STEP, STEP)
    xs = np.arange(-150, 100 + STEP, STEP)
    good = [lp for lp in laps if lp["valid"]] or laps
    best = min(good, key=lambda lp: lp["time"]) if good else None
    out = []
    for c in corners:
        apex = float(c["apex"])
        rows, Bs, Ts = [], [], []
        for lp in good:
            B, T = _trace(lp, "brake", apex, L, xb), _trace(lp, "throttle", apex, L, xt)
            V = _trace(lp, "speed", apex, L, xs)
            if np.isnan(B).mean() > 0.3 or np.isnan(T).mean() > 0.3:
                continue
            met = _lap_metrics(xb, B, xt, T, xs, V)
            met.update({"lap": lp["n"], "time": lp["time"], "best": lp is best, "racing": bool((racing or {}).get((lp["n"], c["name"])))})
            rows.append(met)
            Bs.append(B)
            Ts.append(T)
        if len(rows) < 2:
            continue
        B, T = np.vstack(Bs), np.vstack(Ts)
        mb, mt = np.nanmean(B, axis=0), np.nanmean(T, axis=0)
        braking = sum(r["onset"] is not None for r in rows) >= len(rows) / 2
        flags = [r["racing"] for r in rows]
        by_mode = {m: _scores(B, T, rows, weights(flags, m)) for m in MODES}
        typical = {k: float(np.median([r[k] for r in rows if r.get(k) is not None])) if any(r.get(k) is not None for r in rows) else None
                   for k in ("onset", "peak", "attack", "trail", "release", "pickup", "full", "min_speed", "hesitations")}
        bi = next((i for i, r in enumerate(rows) if r["best"]), None)
        pick = list(range(len(rows)))[-max_traces:]
        r1 = lambda a: [None if not np.isfinite(v) else round(float(v), 1) for v in a]
        out.append({
            "corner": c["name"], "apex": apex, "braking": braking,
            "scores": by_mode[mode][0], "scatter": by_mode[mode][1], "racing_laps": int(sum(flags)),
            "excluded_fallback": bool(any(flags) and (len(flags) - sum(flags)) < 3),
            "scores_by_mode": {m: v[0] for m, v in by_mode.items()}, "scatter_by_mode": {m: v[1] for m, v in by_mode.items()},
            "typical": typical, "describe": _describe(typical),
            "brake": {"x": r1(xb), "mean": r1(mb), "p25": r1(np.nanpercentile(B, 25, axis=0)), "p75": r1(np.nanpercentile(B, 75, axis=0)),
                      "laps": [r1(B[i]) for i in pick], "best": r1(B[bi]) if bi is not None else None},
            "throttle": {"x": r1(xt), "mean": r1(mt), "p25": r1(np.nanpercentile(T, 25, axis=0)), "p75": r1(np.nanpercentile(T, 75, axis=0)),
                         "laps": [r1(T[i]) for i in pick], "best": r1(T[bi]) if bi is not None else None},
            "laps": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
        })
    return out


# --------------------------------------------------------------------------- tyres
def tyre_report(laps: list) -> dict | None:
    if not laps or "wear_fl" not in laps[0]:
        return None
    allv = np.concatenate([lp["speed"] for lp in laps]) / 3.6
    radius = {}
    for w in WHEELS:  # steady driving: wheel surface speed matches the car's speed
        rps = np.concatenate([lp[f"rps_{w}"] for lp in laps])
        br = np.concatenate([lp["brake"] for lp in laps])
        th = np.concatenate([lp["throttle"] for lp in laps])
        # coasting (no pedals): a driven wheel spins a few % faster than the road under power, so calibrating
        # on throttle makes the rears look like they lock under braking
        ok = (allv > 20) & (br < 2) & (th < 5) & (rps > 1)
        if ok.sum() < 20:
            ok = (allv > 20) & (br < 2) & (th < 60) & (rps > 1)
        radius[w] = float(np.median(allv[ok] / (2 * math.pi * rps[ok]))) if ok.sum() >= 20 else None
    rows = []
    for lp in laps:
        v = lp["speed"] / 3.6
        slip = {w: (2 * math.pi * lp[f"rps_{w}"] * radius[w] - v) / np.maximum(v, 1.0) if radius[w] else np.zeros(len(v)) for w in WHEELS}

        def events(mask, need):
            n, run = 0, 0
            for x in mask:
                run = run + 1 if x else 0
                if run == need:
                    n += 1
            return n
        lock = (lp["brake"] > 30) & (np.minimum(slip["fl"], slip["fr"]) < -0.2) & (v > 8)
        spin = (lp["throttle"] > 40) & (np.maximum(slip["rl"], slip["rr"]) > 0.15) & (v > 5)
        wear = {w: float(max(0.0, lp[f"wear_{w}"][-1] - lp[f"wear_{w}"][0]) * 100) for w in WHEELS}
        rows.append({"lap": lp["n"], "valid": lp["valid"], "time": lp["time"], "wear": wear, "wear_avg": float(np.mean(list(wear.values()))),
                     "temp": {w: float(np.nanmean(lp[f"ttemp_{w}"])) for w in WHEELS},
                     "temp_max": {w: float(np.nanmax(lp[f"ttemp_{w}"])) for w in WHEELS},
                     "press": {w: float(np.nanmean(lp[f"press_{w}"])) for w in WHEELS},
                     "brake_temp_max": float(max(np.nanmax(lp[f"btemp_{w}"]) for w in ("fl", "fr"))),
                     "lockups": events(lock, 3), "wheelspin": events(spin, 4),
                     "tread_left": {w: float((1 - lp[f"wear_{w}"][-1]) * 100) for w in WHEELS}})
    df = pd.DataFrame([{**{f"wear_{w}": r["wear"][w] for w in WHEELS}, "lockups": r["lockups"], "wheelspin": r["wheelspin"],
                        "wear_avg": r["wear_avg"]} for r in rows])
    wear_on = df.wear_avg.mean() > 0.005
    temps = {w: float(np.mean([r["temp"][w] for r in rows])) for w in WHEELS}
    return {
        "laps": rows, "wear_enabled": bool(wear_on),
        "wear_per_lap": {w: round(float(df[f"wear_{w}"].mean()), 3) for w in WHEELS},
        "wear_per_lap_avg": round(float(df.wear_avg.mean()), 3),
        "temps": {w: round(v, 1) for w, v in temps.items()},
        "front_rear_temp": round(float((temps["fl"] + temps["fr"]) / 2 - (temps["rl"] + temps["rr"]) / 2), 1),
        "lockups_per_lap": round(float(df.lockups.mean()), 2), "wheelspin_per_lap": round(float(df.wheelspin.mean()), 2),
        "lockups": int(df.lockups.sum()), "wheelspin": int(df.wheelspin.sum()),
        "hardest_worked": max(WHEELS, key=lambda w: df[f"wear_{w}"].mean()) if wear_on else None,
        "radius": radius,
    }


# --------------------------------------------------------------------------- report
def corner_field(sess, corners: list, L: float, me: str) -> dict:
    """Time through each turn (60 m either side of the apex) for every car in the session, so you can see
    where you ranked: corner name -> {"time": yours, "median": the field's, "pct": % of the field you beat}."""
    from .derive import add_distance
    from .quali import session_laps
    fr = add_distance(sess.frames, L, None)
    times = {}
    for name, g in fr.groupby("name"):
        g = g.sort_values("t")
        laps = session_laps(g, L)
        if not len(laps):
            continue
        good = laps[laps.valid] if laps.valid.any() else laps
        d, t = g.dist.to_numpy(float), g.t.to_numpy(float)
        for c in corners:
            zs = []
            for lp in good.itertuples():
                a, b = lp.k * L + c["apex"] - 60, lp.k * L + c["apex"] + 60
                if a < d.min() or b > d.max():
                    continue
                zs.append(float(np.interp(b, d, t) - np.interp(a, d, t)))
            zs = [z for z in zs if 0 < z < 30]
            if zs:
                times.setdefault(c["name"], {})[name] = float(np.median(zs))
    out = {}
    for cn, per in times.items():
        if me not in per or len(per) < 3:
            continue
        mine, others = per[me], [v for k, v in per.items() if k != me]
        out[cn] = {"time": round(mine, 3), "median": round(float(np.median(list(per.values()))), 3),
                   "pct": round(100 * sum(v > mine for v in others) / len(others)), "cars": len(per)}
    return out


def _summary(shapes: list, key: str = "scores") -> dict:
    if not shapes:
        return {}
    sc = lambda c: c[key]["overall"]
    best, worst = max(shapes, key=sc), min(shapes, key=sc)
    return {"overall": round(float(np.mean([sc(c) for c in shapes]))), "most_consistent": best["corner"], "most_consistent_score": sc(best),
            "least_consistent": worst["corner"], "least_consistent_score": sc(worst)}


def technique_report(path_or_session, corners_override=None, mode: str = "reduced") -> dict:
    sess = path_or_session if isinstance(path_or_session, Session) else load_session(path_or_session)
    name, laps, L = recording_laps(sess)
    if not name or not laps:
        return {"driver": name, "available": False, "reason": "This recording has no pedal inputs for its driver."}
    good = [lp for lp in laps if lp["valid"]] or laps
    ref = min(good, key=lambda lp: lp["time"])
    fr = sess.frames[(sess.frames.name == name) & (sess.frames.t >= ref["t0"]) & (sess.frames.t <= ref["t0"] + ref["time"])]
    xy = (fr.lap_dist.to_numpy(float), fr.x.to_numpy(float), fr.z.to_numpy(float)) if len(fr) > 50 else None
    corners = corners_from_laps(laps, L, xy, corners_override)
    racing = {}
    try:  # which corner passes were made fighting another car
        from .derive import add_distance
        from .traffic import racing_flags
        fr = add_distance(sess.frames, L, None)
        keys, times = [], []
        for lp in laps:
            if lp.get("t") is None or len(lp["ld"]) < 5:
                continue
            for c in corners:
                for d in (c["apex"] - 80, c["apex"]):
                    keys.append((lp["n"], c["name"]))
                    times.append(float(np.interp(d, lp["ld"], lp["t"])))
        flags = racing_flags(fr, name, times, L)
        for k, f in zip(keys, flags):
            racing[k] = racing.get(k, False) or bool(f)
    except Exception:
        racing = {}
    shapes = corner_shapes(laps, corners, L, racing=racing, mode=mode)
    try:  # where you ranked in each turn against everyone in the session
        field = corner_field(sess, corners, L, name)
        for sh in shapes:
            sh["field"] = field.get(sh.get("corner"))
    except Exception:
        pass
    track = None
    if xy is not None:  # outline and turn positions for the turn map
        ld, x, z = xy
        o = np.argsort(ld)
        ld, x, z = ld[o], x[o], z[o]
        step = max(1, len(ld) // 600)
        track = {"points": [[round(float(a), 1), round(float(b), 1)] for a, b in zip(x[::step], z[::step])],
                 "corners": [{"name": c["name"], "x": round(float(np.interp(c["apex"], ld, x)), 1),
                              "z": round(float(np.interp(c["apex"], ld, z)), 1)} for c in corners]}
    tyres = tyre_report(laps)
    good = [lp for lp in laps if lp["valid"]]
    summary = {}
    from .traffic import MODES
    summary_by_mode = {m: _summary([{**c, "s": c["scores_by_mode"][m]} for c in shapes], "s") for m in MODES} if shapes else {}
    if shapes:
        worst = min(shapes, key=lambda c: c["scores"]["overall"])
        summary = _summary(shapes)
        tips = []
        if worst["braking"] and worst["scatter"]["onset_sd"] >= 4:
            tips.append(f"{worst['corner']}: your braking point moves around by about ±{worst['scatter']['onset_sd']:.0f} m. Pick a fixed marker.")
        if worst["scatter"]["pickup_sd"] >= 6:
            tips.append(f"{worst['corner']}: throttle pickup varies by ±{worst['scatter']['pickup_sd']:.0f} m. Commit to the exit earlier and more consistently.")
        hes = [c for c in shapes if (c["typical"].get("hesitations") or 0) >= 1]
        if hes:
            tips.append("Hesitation on the throttle out of " + ", ".join(c["corner"] for c in hes[:3]) + ": try one smooth application instead of lifting again.")
        if tyres and tyres["lockups_per_lap"] >= 0.3:
            tips.append(f"About {tyres['lockups_per_lap']:.1f} front lock-ups per lap: ease the initial brake hit slightly.")
        summary["tips"] = tips
    m = sess.meta
    return {"available": True, "driver": name, "session_type": sess.type, "folder": sess.path.name,
            "track": m.get("track_location_translated") or m.get("track_location"),
            "layout": m.get("track_variation_translated") or m.get("track_variation"), "started_at": m.get("started_at"),
            "car": (m.get("local") or {}).get("car"),
            "laps": [{"n": lp["n"], "time": lp["time"], "valid": lp["valid"], "s1": lp["s1"], "s2": lp["s2"], "s3": lp["s3"]} for lp in laps],
            "best": min((lp["time"] for lp in good), default=None), "corners": shapes, "summary": summary, "tyres": tyres,
            "summary_by_mode": summary_by_mode, "racing_mode": mode,
            "racing_passes": sum(c["racing_laps"] for c in shapes), "passes": sum(len(c["laps"]) for c in shapes),
            "map": track}
