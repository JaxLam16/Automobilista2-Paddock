"""Tyre analysis for the recording car: temperatures across the tread and through the tyre, operating window,
warm-up, pressures, balance, overheating spots, wear, stints, brakes and ride height.

Inner / outer: the game reports each tyre's own left, centre and right surface temperature. On the left-hand
wheels the inside of the tyre is its right side; on the right-hand wheels it's the left side.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .derive import Session, load_session

WHEELS = ("fl", "fr", "rl", "rr")
NAMES = {"fl": "Front left", "fr": "Front right", "rl": "Rear left", "rr": "Rear right"}
DEFAULT_WINDOW = {"temp_lo": 80.0, "temp_hi": 100.0, "press_lo": 1.80, "press_hi": 1.95}   # surface degC, hot pressure in bar


def to_bar(p: np.ndarray) -> np.ndarray:
    """Tyre pressure in bar. AMS2's header says PSI, but real telemetry reports kilopascals (about 186 for a
    1.86 bar GT3 tyre); older or simulated data may be in PSI. Decide from the magnitude."""
    p = np.asarray(p, float)
    med = np.nanmedian(p[p > 0]) if np.any(p > 0) else np.nan
    if med != med:
        return p
    return p / 100.0 if med > 60 else p / 14.5038 if med > 8 else p
MOVING = 8.0          # m/s: slower than this is pit lane / stationary
WARM_HOLD_S = 15.0    # a tyre counts as warm once it stays in the window this long


def _r(v, dp=1):
    return None if v is None or v != v or not np.isfinite(v) else round(float(v), dp)


def _zones(lo: pd.DataFrame, w: str):
    """(inner, middle, outer) surface temperature series for one wheel, or None if not recorded."""
    if f"tl_{w}" not in lo or not np.isfinite(lo[f"tc_{w}"]).any() or lo[f"tc_{w}"].abs().max() < 1:
        return None
    left, mid, right = lo[f"tl_{w}"].to_numpy(float), lo[f"tc_{w}"].to_numpy(float), lo[f"tr_{w}"].to_numpy(float)
    return (right, mid, left) if w in ("fl", "rl") else (left, mid, right)


def _runs(mask: np.ndarray):
    """(start, end) index pairs of consecutive True runs."""
    if not mask.any():
        return []
    d = np.diff(np.r_[0, mask.astype(int), 0])
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def tyre_analysis(path_or_session, window: dict | None = None, corners_override=None) -> dict:
    from .technique import corners_from_laps, recording_laps
    sess = path_or_session if isinstance(path_or_session, Session) else load_session(path_or_session)
    W = {**DEFAULT_WINDOW, **(window or {})}
    lo = sess.local
    if lo is None or not len(lo) or not any(f"ttemp_{w}" in lo or f"tc_{w}" in lo for w in WHEELS):
        return {"available": False, "reason": "This recording has no tyre data. It was made by an older recorder: sessions "
                                              "recorded from now on include full tyre temperatures, pressures and wear."}
    lo = lo.sort_values("t").reset_index(drop=True)
    name, laps, L = recording_laps(sess)
    t = lo.t.to_numpy(float)
    spd = lo.speed.to_numpy(float)
    moving = spd > MOVING
    zones = {w: _zones(lo, w) for w in WHEELS}
    has_zones = all(z is not None for z in zones.values())
    surf = {w: (np.nanmean(np.vstack(zones[w]), axis=0) if zones[w] is not None else lo.get(f"ttemp_{w}", pd.Series(np.nan, index=lo.index)).to_numpy(float))
            for w in WHEELS}
    peak = {w: (np.nanmax(np.vstack(zones[w]), axis=0) if zones[w] is not None else surf[w]) for w in WHEELS}
    col = lambda k, w: lo[f"{k}_{w}"].to_numpy(float) if f"{k}_{w}" in lo else np.full(len(lo), np.nan)
    carc = {w: col("carc", w) for w in WHEELS}
    air = {w: col("air", w) for w in WHEELS}
    rim = {w: col("rim", w) for w in WHEELS}
    press = {w: to_bar(col("press", w)) for w in WHEELS}
    brake_t = {w: col("btemp", w) for w in WHEELS}
    wear = {w: col("wear", w) for w in WHEELS}
    ride = {w: col("ride", w) for w in WHEELS}
    has_core = all(np.isfinite(carc[w]).any() for w in WHEELS)
    has_press = all(np.isfinite(press[w]).any() and np.nanmax(press[w]) > 0.5 for w in WHEELS)
    ld = lo.lap_dist.to_numpy(float) if "lap_dist" in lo else np.zeros(len(lo))
    dist = np.r_[0, np.cumsum(np.abs(np.diff(np.unwrap(ld / L * 2 * np.pi) / (2 * np.pi) * L)))] if L else np.zeros(len(lo))

    # ---------- out events: session start and every pit exit (tyres start cold)
    outs = []
    first = np.flatnonzero(moving)
    if len(first):
        outs.append({"t": float(t[first[0]]), "kind": "start"})
    fr = sess.frames
    if name and fr is not None and "pit_mode" in fr:
        me = fr[fr.name == name].sort_values("t")
        pm = me.pit_mode.to_numpy()
        for i in np.flatnonzero((pm[:-1] > 0) & (pm[1:] == 0)):
            tt = float(me.t.iat[i + 1])
            if not outs or tt - outs[-1]["t"] > 30:
                outs.append({"t": tt, "kind": "pit exit"})
    hold = max(1, int(WARM_HOLD_S / max(np.median(np.diff(t)) if len(t) > 1 else 0.05, 1e-3)))

    def warm_time(w, i0, i1):
        """When the tyre's rolling 20 s average surface temperature first reached the window. The surface
        itself dips on every straight, so a sustained-above test would almost never pass."""
        seg = pd.Series(np.where(moving[i0:i1], surf[w][i0:i1], np.nan))
        roll = seg.rolling(max(2, int(hold * 20 / WARM_HOLD_S)), min_periods=max(2, int(hold * 10 / WARM_HOLD_S))).mean().to_numpy()
        hit = np.flatnonzero(roll >= W["temp_lo"])
        return i0 + int(hit[0]) if len(hit) else None

    warmups = []
    bounds = [np.searchsorted(t, o["t"]) for o in outs] + [len(t)]
    for k, o in enumerate(outs):
        i0, i1 = bounds[k], bounds[k + 1]
        per = {}
        for w in WHEELS:
            a = warm_time(w, i0, i1)
            per[w] = None if a is None else {"s": _r(t[a] - t[i0], 0), "laps": _r((dist[a] - dist[i0]) / L, 2) if L else None,
                                              "start_temp": _r(np.nanmean(surf[w][i0:i0 + 40]))}
        done = [v for v in per.values() if v]
        warmups.append({"kind": o["kind"], "t": _r(o["t"], 0), "wheels": per,
                        "all_warm_s": max(v["s"] for v in done) if len(done) == 4 else None,
                        "all_warm_laps": max(v["laps"] or 0 for v in done) if len(done) == 4 else None})
    warm_after = {}  # first moment each stint's tyres were all warm: laps before that are warm-up laps
    for k, wu in enumerate(warmups):
        warm_after[k] = (wu["t"] or 0) + (wu["all_warm_s"] if wu["all_warm_s"] is not None else 1e9)

    # ---------- laps
    lap_rows = []
    for n, lp in enumerate(laps):
        a, b = np.searchsorted(t, lp["t0"]), np.searchsorted(t, lp["t0"] + lp["time"])
        if b - a < 20:
            continue
        sl = slice(a, b)
        stint = max([k for k, o in enumerate(outs) if o["t"] <= lp["t0"] + 1] or [0])
        warm = lp["t0"] >= warm_after.get(stint, 0) - 1
        row = {"lap": n + 1, "time": _r(lp["time"], 3), "valid": bool(lp["valid"]), "stint": stint + 1, "warm": bool(warm), "wheels": {}}
        for w in WHEELS:
            s_ = surf[w][sl]
            inw = (s_ >= W["temp_lo"]) & (s_ <= W["temp_hi"])
            z = zones[w]
            row["wheels"][w] = {
                "surface": _r(np.nanmean(s_)), "inner": _r(np.nanmean(z[0][sl])) if z else None, "middle": _r(np.nanmean(z[1][sl])) if z else None,
                "outer": _r(np.nanmean(z[2][sl])) if z else None, "carcass": _r(np.nanmean(carc[w][sl])), "air": _r(np.nanmean(air[w][sl])),
                "press": _r(np.nanmean(press[w][sl]), 3), "press_max": _r(np.nanmax(press[w][sl]), 3) if np.isfinite(press[w][sl]).any() else None,
                "brake_max": _r(np.nanmax(brake_t[w][sl]), 0) if np.isfinite(brake_t[w][sl]).any() else None,
                "in_window": _r(100 * np.mean(inw), 0), "over": _r(100 * np.mean(s_ > W["temp_hi"]), 0), "under": _r(100 * np.mean(s_ < W["temp_lo"]), 0),
                "swing": _r(np.nanpercentile(s_, 95) - np.nanpercentile(s_, 5)) if np.isfinite(s_).any() else None,
                "wear_used": _r(100 * (np.nanmax(wear[w][sl]) - np.nanmin(wear[w][sl])), 2) if np.isfinite(wear[w][sl]).any() else None}
        lap_rows.append(row)
    rep = [r for r in lap_rows if r["valid"] and r["warm"]] or [r for r in lap_rows if r["warm"]] or lap_rows
    rep_mask = np.zeros(len(t), bool)
    for r in rep:
        lp = laps[r["lap"] - 1]
        rep_mask[np.searchsorted(t, lp["t0"]):np.searchsorted(t, lp["t0"] + lp["time"])] = True
    if not rep_mask.any():
        rep_mask = moving.copy()

    # ---------- per wheel summary (representative laps: valid, tyres already warm)
    wheels = {}
    for w in WHEELS:
        m = rep_mask
        s_ = surf[w][m]
        z = zones[w]
        inner, mid, outer = ((np.nanmean(z[0][m]), np.nanmean(z[1][m]), np.nanmean(z[2][m])) if z else (np.nan,) * 3)
        swing = np.nanmedian([r["wheels"][w]["swing"] for r in rep if r["wheels"][w]["swing"] is not None]) if rep else np.nan
        wheel = {"name": NAMES[w], "surface": _r(np.nanmean(s_)), "peak": _r(np.nanpercentile(peak[w][m], 99)) if np.isfinite(peak[w][m]).any() else None,
                 "inner": _r(inner), "middle": _r(mid), "outer": _r(outer),
                 "spread": _r(np.nanmax([inner, mid, outer]) - np.nanmin([inner, mid, outer])) if z else None,
                 "centre_vs_edges": _r(mid - (inner + outer) / 2) if z else None, "inner_vs_outer": _r(inner - outer) if z else None,
                 "carcass": _r(np.nanmean(carc[w][m])), "air": _r(np.nanmean(air[w][m])), "rim": _r(np.nanmean(rim[w][m])),
                 "surface_over_carcass": _r(np.nanmean(s_ - carc[w][m])) if has_core else None,
                 "in_window": _r(100 * np.mean((s_ >= W["temp_lo"]) & (s_ <= W["temp_hi"])), 0),
                 "over": _r(100 * np.mean(s_ > W["temp_hi"]), 0), "under": _r(100 * np.mean(s_ < W["temp_lo"]), 0),
                 "swing": _r(swing), "character": None if swing != swing else "stable" if swing < 15 else "lively" if swing < 30 else "peaky",
                 "hints": []}
        cve, ivo = wheel["centre_vs_edges"], wheel["inner_vs_outer"]
        if cve is not None and cve > 3:
            wheel["hints"].append(f"Centre {cve:.0f} °C hotter than the shoulders: over-inflated. Try about {min(0.14, 0.017 * cve):.2f} bar less.")
        elif cve is not None and cve < -3:
            wheel["hints"].append(f"Shoulders {-cve:.0f} °C hotter than the centre: under-inflated. Try about {min(0.14, -0.017 * cve):.2f} bar more.")
        if ivo is not None and ivo > 10:
            wheel["hints"].append(f"Inside {ivo:.0f} °C hotter than the outside: probably too much negative camber (or toe).")
        elif ivo is not None and ivo < 0:
            wheel["hints"].append(f"Outside {-ivo:.0f} °C hotter than the inside: not enough negative camber.")
        wheels[w] = wheel

    # ---------- pressures: cold (first moving seconds) vs hot (representative laps)
    pressures = None
    if has_press:
        i0 = first[0] if len(first) else 0
        pressures = {}
        for w in WHEELS:
            cold = np.nanmean(press[w][i0:i0 + 60])
            hot = np.nanmedian(press[w][rep_mask])
            target = (W["press_lo"] + W["press_hi"]) / 2
            pressures[w] = {"cold": _r(cold, 3), "hot": _r(hot, 3), "build_up": _r(hot - cold, 3),
                            "in_window": _r(100 * np.mean((press[w][rep_mask] >= W["press_lo"]) & (press[w][rep_mask] <= W["press_hi"])), 0),
                            "unit": "bar",
                            "change_cold_by": _r(target - hot, 2)}

    # ---------- balance
    avg = lambda ws: float(np.nanmean([wheels[w]["surface"] for w in ws if wheels[w]["surface"] is not None]))
    balance = {"front_minus_rear": _r(avg(("fl", "fr")) - avg(("rl", "rr"))), "left_minus_right": _r(avg(("fl", "rl")) - avg(("fr", "rr")))}

    # ---------- corners, overheating spots, heat map
    xy = None
    corners = []
    if laps:
        lp = min((x for x in laps if x["valid"]), key=lambda x: x["time"], default=laps[0])
        a, b = np.searchsorted(t, lp["t0"]), np.searchsorted(t, lp["t0"] + lp["time"])
        xy = (ld[a:b], lo.x.to_numpy(float)[a:b], lo.z.to_numpy(float)[a:b]) if b - a > 50 else None
        try:
            corners = corners_from_laps(laps, L, xy, corners_override)
        except Exception:
            corners = []
    near_corner = lambda d: min(corners, key=lambda c: abs(((d - c["apex"]) + L / 2) % L - L / 2))["name"] if corners else None
    hot_spots = []
    for w in WHEELS:
        over = (peak[w] > W["temp_hi"] + 8) & moving
        counts = {}
        for a, b in _runs(over):
            if (t[min(b, len(t) - 1)] - t[a]) >= 0.3:
                cn = near_corner(ld[a]) or f"{ld[a]:.0f} m"
                c_ = counts.setdefault(cn, {"corner": cn, "events": 0, "peak": 0.0})
                c_["events"] += 1
                c_["peak"] = max(c_["peak"], float(np.nanmax(peak[w][a:b])))
        for c_ in counts.values():
            hot_spots.append({"wheel": w, **c_, "peak": _r(c_["peak"])})
    hot_spots.sort(key=lambda x: (-x["events"], -(x["peak"] or 0)))
    heat = []
    if L:
        nb = int(L // 10)
        b_ = (ld[rep_mask] // 10).astype(int) % nb
        df = pd.DataFrame({"b": b_, "x": lo.x.to_numpy(float)[rep_mask], "z": lo.z.to_numpy(float)[rep_mask],
                           **{w: surf[w][rep_mask] for w in WHEELS}}).groupby("b").mean()
        heat = [[int(i) * 10 + 5, _r(r.x, 1), _r(r.z, 1), *[_r(getattr(r, w)) for w in WHEELS]] for i, r in df.iterrows()]
    per_corner = []
    for c in corners:
        zone = rep_mask & (np.abs(((ld - c["apex"]) + L / 2) % L - L / 2) < 60)
        if zone.sum() < 5:
            continue
        pk = {w: _r(np.nanpercentile(peak[w][zone], 95)) for w in WHEELS}
        bk = {w: _r(np.nanmax(brake_t[w][zone]), 0) if np.isfinite(brake_t[w][zone]).any() else None for w in WHEELS}
        per_corner.append({"corner": c["name"], "apex": c["apex"], "peak": pk, "brake": bk,
                           "hottest": max(pk, key=lambda k: pk[k] or 0)})

    # ---------- lap time against temperature
    scatter = [[r["time"], _r(np.nanmean([r["wheels"][w]["surface"] for w in WHEELS if r["wheels"][w]["surface"] is not None]))]
               for r in lap_rows if r["valid"] and r["time"]]
    best_band = None
    good = sorted([p for p in scatter if p[1] is not None])
    if len(good) >= 4:
        top = good[:max(2, len(good) // 3)]
        best_band = [min(p[1] for p in top), max(p[1] for p in top)]

    # ---------- wear and stints
    wear_out = {}
    for w in WHEELS:
        per_lap = [r["wheels"][w]["wear_used"] for r in rep if r["wheels"][w]["wear_used"] is not None]
        rate = float(np.median(per_lap)) if per_lap else None
        now = float(np.nanmax(wear[w])) * 100 if np.isfinite(wear[w]).any() else None
        wear_out[w] = {"per_lap": _r(rate, 2), "now": _r(now, 1),
                       "laps_to_50": _r((50 - now) / rate, 0) if rate and now is not None and rate > 0 and now < 50 else None}
    stints = []
    for k in range(len(outs)):
        rows = [r for r in lap_rows if r["stint"] == k + 1]
        if not rows:
            continue
        rp = [r for r in rows if r["valid"] and r["warm"] and r["time"]]
        times = [r["time"] for r in rp]
        stints.append({"stint": k + 1, "laps": len(rows), "start": outs[k]["kind"],
                       "compound": str(lo.compound.dropna().iloc[0]) if "compound" in lo and lo.compound.notna().any() else None,
                       "median": _r(np.median(times), 3) if times else None,
                       "trend": _r(np.polyfit(range(len(times)), times, 1)[0], 3) if len(times) >= 4 else None,
                       "surface": _r(np.nanmean([r["wheels"][w]["surface"] for r in rp for w in WHEELS if r["wheels"][w]["surface"] is not None])) if rp else None,
                       "wear_per_lap": _r(np.nanmean([r["wheels"][w]["wear_used"] for r in rp for w in WHEELS if r["wheels"][w]["wear_used"] is not None]), 2) if rp else None})

    # ---------- brakes and ride height
    brakes = {w: {"peak": _r(np.nanpercentile(brake_t[w][moving], 99.5), 0) if np.isfinite(brake_t[w][moving]).any() else None,
                  "over_800_s": _r(float(np.sum(brake_t[w][moving] > 800)) * np.median(np.diff(t)), 1) if len(t) > 1 else None} for w in WHEELS}
    ride_out = None
    if all(np.isfinite(ride[w]).any() and np.nanmax(ride[w]) > 0 for w in WHEELS):
        ride_out = {}
        for w in WHEELS:
            low = (ride[w] < 1.0) & moving
            spots = {}
            for a, b in _runs(low):
                cn = near_corner(ld[a]) or f"{ld[a]:.0f} m"
                spots[cn] = spots.get(cn, 0) + 1
            ride_out[w] = {"min": _r(np.nanpercentile(ride[w][moving], 1), 2), "typical": _r(np.nanmedian(ride[w][moving]), 2),
                           "bottoming": sorted(({"corner": k, "events": v} for k, v in spots.items()), key=lambda x: -x["events"])[:5]}

    # ---------- timeline (2 per second) for the charts
    step = max(1, int(round(0.5 / max(np.median(np.diff(t)) if len(t) > 1 else 0.5, 1e-3))))
    idx = np.arange(0, len(t), step)
    timeline = {"t": [_r(v, 1) for v in t[idx]], "lap": [None] * len(idx)}
    for r in lap_rows:
        lp = laps[r["lap"] - 1]
        a, b = np.searchsorted(t[idx], lp["t0"]), np.searchsorted(t[idx], lp["t0"] + lp["time"])
        for i in range(a, b):
            timeline["lap"][i] = r["lap"]
    for w in WHEELS:
        z = zones[w]
        timeline[w] = {"inner": [_r(v) for v in z[0][idx]] if z else None, "middle": [_r(v) for v in z[1][idx]] if z else None,
                       "outer": [_r(v) for v in z[2][idx]] if z else None, "surface": [_r(v) for v in surf[w][idx]],
                       "carcass": [_r(v) for v in carc[w][idx]] if has_core else None, "air": [_r(v) for v in air[w][idx]] if has_core else None,
                       "press": [_r(v, 3) for v in press[w][idx]] if has_press else None, "brake": [_r(v, 0) for v in brake_t[w][idx]]}

    # ---------- talking points
    tips = []
    worst = min(WHEELS, key=lambda w: wheels[w]["in_window"] if wheels[w]["in_window"] is not None else 101)
    avg_win = np.nanmean([wheels[w]["in_window"] for w in WHEELS if wheels[w]["in_window"] is not None])
    tips.append(f"Tyres spent {avg_win:.0f}% of your representative laps inside the {W['temp_lo']:.0f}-{W['temp_hi']:.0f} °C window; "
                f"the {NAMES[worst].lower()} least ({wheels[worst]['in_window']:.0f}%, {wheels[worst]['over']:.0f}% too hot, {wheels[worst]['under']:.0f}% too cold).")
    for wu in warmups:
        if wu["all_warm_laps"] is not None:
            slow = max(WHEELS, key=lambda w: (wu["wheels"][w] or {}).get("s") or 0)
            tips.append(f"After the {wu['kind']}, all four tyres were in the window after {wu['all_warm_s']:.0f} s "
                        f"({wu['all_warm_laps']:.1f} laps); the {NAMES[slow].lower()} was slowest.")
        else:
            tips.append(f"After the {wu['kind']}, not every tyre reached the window before the stint ended.")
    fb = balance["front_minus_rear"]
    if fb is not None and abs(fb) >= 4:
        tips.append(f"The {'fronts' if fb > 0 else 'rears'} ran {abs(fb):.0f} °C hotter than the {'rears' if fb > 0 else 'fronts'}: "
                    f"{'the front axle is doing more of the work (typically understeer)' if fb > 0 else 'the rear axle is working harder (traction or oversteer)'}.")
    # setup hints, said once for every tyre that shares them
    def group(test):
        return [w for w in WHEELS if wheels[w][test[0]] is not None and test[1](wheels[w][test[0]])]
    def who(ws):
        if len(ws) == 4:
            return "All four tyres"
        if set(ws) == {"fl", "fr"}:
            return "Both fronts"
        if set(ws) == {"rl", "rr"}:
            return "Both rears"
        return ", ".join(NAMES[w] for w in ws).capitalize()
    rng = lambda ws, k: (f"{min(abs(wheels[w][k]) for w in ws):.0f}-{max(abs(wheels[w][k]) for w in ws):.0f}"
                         if len(ws) > 1 else f"{abs(wheels[ws[0]][k]):.0f}")
    over = group(("centre_vs_edges", lambda v: v > 3))
    under = group(("centre_vs_edges", lambda v: v < -3))
    much_cam = group(("inner_vs_outer", lambda v: v > 10))
    little_cam = group(("inner_vs_outer", lambda v: v < 0))
    if over:
        tips.append(f"{who(over)} run {rng(over, 'centre_vs_edges')} °C hotter in the centre than at the shoulders: over-inflated. "
                    f"Lower the pressure (the tread table has a suggestion per tyre).")
    if under:
        tips.append(f"{who(under)} run {rng(under, 'centre_vs_edges')} °C hotter at the shoulders than in the centre: under-inflated. Raise the pressure.")
    if much_cam:
        tips.append(f"{who(much_cam)}: the inside runs {rng(much_cam, 'inner_vs_outer')} °C hotter than the outside, probably too much negative camber.")
    if little_cam:
        tips.append(f"{who(little_cam)}: the outside runs as hot as or hotter than the inside, so there's not enough negative camber.")
    if hot_spots:
        h = hot_spots[0]
        tips.append(f"Biggest overheating spot: the {NAMES[h['wheel']].lower()} at {h['corner']}, {h['events']} times over "
                    f"{W['temp_hi'] + 8:.0f} °C (peak {h['peak']:.0f} °C).")
    if best_band:
        tips.append(f"Your quickest laps came with the tyres averaging {best_band[0]:.0f}-{best_band[1]:.0f} °C.")
    peaky = [w for w in WHEELS if wheels[w]["character"] == "peaky"]
    if peaky:
        tips.append(f"Peaky temperatures (big swings within a lap) on the {', '.join(NAMES[w].lower() for w in peaky)}: "
                    f"the surface heats in bursts (braking, slides) rather than evenly.")

    slip = None
    try:  # lock-ups and wheelspin, from wheel speed against car speed
        from .technique import tyre_report
        tr = tyre_report(laps)
        if tr:
            slip = {"lockups_per_lap": tr.get("lockups_per_lap"), "wheelspin_per_lap": tr.get("wheelspin_per_lap"),
                    "hardest_worked": tr.get("hardest_worked")}
    except Exception:
        slip = None
    return {"available": True, "driver": name, "window": W, "slip": slip, "has_zones": has_zones, "has_core": has_core, "has_pressure": has_press,
            "compound": str(lo.compound.dropna().iloc[0]) if "compound" in lo and lo.compound.notna().any() else None,
            "conditions": {"track": _r(lo.track_temp.median()) if "track_temp" in lo else None,
                           "ambient": _r(lo.ambient_temp.median()) if "ambient_temp" in lo else None},
            "wheels": wheels, "laps": lap_rows, "warmups": warmups, "pressures": pressures, "balance": balance,
            "hot_spots": hot_spots[:12], "corners": per_corner, "heat": heat, "scatter": scatter, "best_band": best_band,
            "wear": wear_out, "stints": stints, "brakes": brakes, "ride": ride_out, "timeline": timeline, "tips": tips,
            "track_length": L}
