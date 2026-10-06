"""Driver errors in a race: where each driver lost time to a mistake, what kind it was, and what it cost.

Every corner on every lap is compared with that driver's own typical time through it (the median over their
clean laps). A loss of more than half a second is an error unless the car was stuck right behind another one.
It's classified as a spin (speed collapses), going off (the lap gets invalidated there), braking too late
(braking started well after their usual point and the corner was slower), or a slow corner (missed apex,
ran wide, a moment). Positions lost in the seconds after an error are charged to it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ZONE_BEFORE, ZONE_AFTER = 150.0, 100.0   # metres either side of the apex
MIN_LOSS = 0.5                           # seconds slower than usual
TRAFFIC_M = 30.0                         # a car this close ahead means "held up", not a mistake


def _braking_point(d: np.ndarray, t: np.ndarray, v: np.ndarray, apex: float) -> float | None:
    """Metres before the apex where hard braking (over 4 m/s2 for a few samples) started."""
    m = (d >= apex - ZONE_BEFORE) & (d <= apex)
    if m.sum() < 8:
        return None
    vv, tt, dd = v[m], t[m], d[m]
    dt = np.gradient(tt)
    acc = np.gradient(vv) / np.where(dt > 1e-4, dt, np.nan)
    run = 0
    for i, a in enumerate(acc):
        run = run + 1 if a < -4.0 else 0
        if run >= 4:
            return float(apex - dd[i - 3])
    return None


def race_errors(ra) -> dict:
    fr = ra.frames
    laps = ra.laps
    corners = ra.corners or []
    L = float(ra.session.L)
    passes = ra.passes if ra.passes is not None else pd.DataFrame(columns=["t", "passer", "passed"])
    by_car = {n: g.sort_values("t") for n, g in fr.groupby("name")}
    # every car's distance against time, to tell a mistake from being held up
    tracks = {n: (g.t.to_numpy(float), g.dist.to_numpy(float)) for n, g in by_car.items()}
    is_ai = dict(zip(ra.entrants.name, ra.entrants.is_ai.astype(bool)))
    errors, drivers = [], []
    for n, g in by_car.items():
        t, d, v = g.t.to_numpy(float), g.dist.to_numpy(float), g.speed.to_numpy(float)
        inv = g.lap_invalid.to_numpy(bool) if "lap_invalid" in g else np.zeros(len(g), bool)
        mine = laps[laps.name == n]
        clean = set(mine[mine.clean & (mine.lap > 1) & ~mine.pit.astype(bool)].lap.astype(int))
        pit = set(mine[mine.pit.astype(bool)].lap.astype(int))
        zones = {}
        for lap in mine.lap.astype(int):
            for c in corners:
                a, b = (lap - 1) * L + c["apex"] - ZONE_BEFORE, (lap - 1) * L + c["apex"] + ZONE_AFTER
                if a < d.min() or b > d.max():
                    continue
                ta, tb = float(np.interp(a, d, t)), float(np.interp(b, d, t))
                m = (d >= a) & (d <= b)
                if m.sum() < 5:
                    continue
                zones[(lap, c["name"])] = {"lap": lap, "corner": c["name"], "time": tb - ta, "ta": ta, "tb": tb,
                                           "vmin": float(np.min(v[m])), "brake": _braking_point(d, t, v, (lap - 1) * L + c["apex"]),
                                           "went_off": bool(np.any(np.diff(inv[m].astype(int)) > 0)), "at": float(np.median(t[m]))}
        base = {}
        for c in corners:
            ref = [zones[k] for k in zones if k[1] == c["name"] and k[0] in clean]
            if len(ref) >= 2:
                bp = [z["brake"] for z in ref if z["brake"] is not None]
                base[c["name"]] = {"time": float(np.median([z["time"] for z in ref])), "vmin": float(np.median([z["vmin"] for z in ref])),
                                   "brake": float(np.median(bp)) if bp else None}
        mine_err = []
        for z in zones.values():
            bz = base.get(z["corner"])
            if not bz or z["lap"] in pit:
                continue
            loss = z["time"] - bz["time"]
            if loss < MIN_LOSS:
                continue
            # held up? another car just ahead on track in the middle of the corner
            here = float(np.interp(z["at"], t, d))
            held = False
            for o, (to, do) in tracks.items():
                if o == n or z["at"] < to[0] or z["at"] > to[-1]:
                    continue
                gap = float(np.interp(z["at"], to, do)) - here
                if 0 < gap < TRAFFIC_M:
                    held = True
                    break
            if held and not z["went_off"] and z["vmin"] > 0.35 * bz["vmin"]:
                continue
            if z["vmin"] < max(8.0, 0.35 * bz["vmin"]):
                kind = "spin"
            elif z["went_off"]:
                kind = "off track"
            elif z["brake"] is not None and bz["brake"] is not None and z["brake"] < bz["brake"] - 12 and z["vmin"] < bz["vmin"] - 1.5:
                kind = "braked too late"
            else:
                kind = "slow corner"
            lost = passes[(passes.passed == n) & (passes.t >= z["ta"] - 1) & (passes.t <= z["tb"] + 6)]
            i = int(np.argmin(np.abs(t - z["at"])))
            mine_err.append({"name": n, "lap": z["lap"], "corner": z["corner"], "kind": kind, "loss": round(min(loss, 30.0), 2),
                             "positions": int(len(lost)), "t": round(z["ta"], 1), "x": round(float(g.x.iat[i]), 1), "z": round(float(g.z.iat[i]), 1),
                             "brake_later_m": None if z["brake"] is None or bz["brake"] is None else round(bz["brake"] - z["brake"], 0),
                             "speed_lost_kph": round((bz["vmin"] - z["vmin"]) * 3.6, 0)})
        mine_err.sort(key=lambda e: e["t"])
        laps_n = int(len(mine[mine.lap > 0]))
        err_laps = len({e["lap"] for e in mine_err})
        kinds = {k: sum(e["kind"] == k for e in mine_err) for k in ("spin", "off track", "braked too late", "slow corner")}
        worst = None
        if mine_err:
            by_corner = pd.Series([e["corner"] for e in mine_err]).value_counts()
            worst = {"corner": by_corner.index[0], "errors": int(by_corner.iloc[0])}
        contacts = int((ra.incidents.name == n).sum()) if ra.incidents is not None and len(ra.incidents) else 0
        drivers.append({"name": n, "is_ai": bool(is_ai.get(n, True)), "errors": len(mine_err), **{k.replace(" ", "_"): v for k, v in kinds.items()},
                        "time_lost": round(sum(e["loss"] for e in mine_err), 1), "positions_lost": sum(e["positions"] for e in mine_err),
                        "clean_lap_share": round(100 * (1 - err_laps / laps_n)) if laps_n else None, "laps": laps_n,
                        "worst_corner": worst, "contacts": contacts})
        errors += mine_err
    order = {r.name: i for i, r in enumerate(ra.classification.itertuples())}
    drivers.sort(key=lambda r: order.get(r["name"], 99))
    return {"drivers": drivers, "errors": sorted(errors, key=lambda e: e["t"]), "corners": [c["name"] for c in corners]}
