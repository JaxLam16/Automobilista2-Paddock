"""What the car is doing, measured from one practice run of the recording car.

AMS2 conventions, verified on real telemetry (Ferrari 488 GT3, Road America):
  * turning right: steering > 0, yaw rate < 0, lateral acceleration > 0, left-side wheels loaded
  * longitudinal acceleration > 0 under braking, < 0 under power; forward speed = -vel_long
  * body slip: lateral velocity has the opposite sign to the yaw rate in a normal corner
  * ride height in cm, suspension travel and tyre height above ground in m, damper velocity in m/s
The car's own yaw rate gives the path curvature (curvature = yaw rate / speed); positions are too coarse
at 20 Hz to differentiate twice.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WHEELS = ("fl", "fr", "rl", "rr")
SLOW_KPH, FAST_KPH = 120.0, 170.0
DAMPER_SLOW = 0.05          # m/s: below this is the "slow" damper range (body motion), above is "fast" (kerbs, bumps)


def _r(v, dp=2):
    return None if v is None or v != v or not np.isfinite(v) else round(float(v), dp)


def balance(lo: pd.DataFrame) -> dict:
    """Understeer / oversteer by corner phase and speed.

    For every cornering sample, steering-per-curvature (how much steering the car needs for the yaw it
    actually achieves) is compared with the car's own low-g baseline. Above 1 the car needs more steering
    than geometry says (understeer); below 1 it needs less (oversteer). Countersteer (steering against the
    direction of rotation) is counted separately: that's the rear stepping out."""
    v = lo.speed.to_numpy(float)
    yaw = lo.yaw_rate.to_numpy(float)
    st = lo.steering.to_numpy(float)
    ay = lo.acc_lat.to_numpy(float)
    ax = lo.acc_long.to_numpy(float)
    thr, brk = lo.throttle.to_numpy(float), lo.brake.to_numpy(float)
    kap = np.where(v > 12, -yaw / np.maximum(v, 1), np.nan)      # + = turning right, matching steering's sign
    turning = np.abs(kap) > 0.004
    ratio = np.where(turning & (np.sign(st) == np.sign(kap)), np.abs(st) / np.abs(kap), np.nan)
    base_m = turning & (np.abs(ay) < 5) & (np.abs(ax) < 2)
    base = np.nanmedian(ratio[base_m]) if np.isfinite(ratio[base_m]).sum() > 30 else np.nanpercentile(ratio[turning], 25)
    idx = ratio / base
    kph = v * 3.6
    phases = {"entry": turning & (brk > 0.1) & (ax > 2), "mid": turning & (brk < 0.05) & (thr < 0.6) & (np.abs(ay) > 7),
              "exit": turning & (thr > 0.5) & (ax < -0.5)}
    out = {"baseline_steer_per_curvature": _r(base, 1)}
    for ph, m in phases.items():
        for sp, sm in (("slow", kph < SLOW_KPH), ("fast", kph > FAST_KPH)):
            sel = m & sm & np.isfinite(idx) & (np.abs(ay) > 6)
            out[f"{ph}_{sp}"] = {"index": _r(np.nanmedian(idx[sel]), 3) if sel.sum() > 15 else None, "samples": int(sel.sum())}
    counter = turning & (np.sign(st) == -np.sign(kap)) & (np.abs(st) > 0.02) & (np.abs(ay) > 5)
    out["countersteer_s"] = _r(counter.sum() / 20.0, 1)
    out["countersteer_on_power_s"] = _r((counter & (thr > 0.5)).sum() / 20.0, 1)
    out["countersteer_on_entry_s"] = _r((counter & (brk > 0.1)).sum() / 20.0, 1)
    return out


def tyres(lo: pd.DataFrame) -> dict:
    from ..tyres import _zones
    out = {}
    for w in WHEELS:
        z = _zones(lo, w)
        p = lo.get(f"press_{w}")
        from ..tyres import to_bar
        rec = {"press_hot_bar": _r(np.nanmedian(to_bar(p.to_numpy(float))), 3) if p is not None else None}
        if z is not None:
            inner, mid, outer = (np.nanmean(a) for a in z)
            rec.update({"inner": _r(inner, 1), "middle": _r(mid, 1), "outer": _r(outer, 1),
                        "inner_minus_outer": _r(inner - outer, 1), "centre_minus_edges": _r(mid - (inner + outer) / 2, 1)})
        out[w] = rec
    return out


def platform(lo: pd.DataFrame) -> dict:
    """Ride height, travel, bump-stop / bottoming contact, damper velocity balance and wheel lift per corner."""
    out = {}
    for w in WHEELS:
        ride, trav, sv, hag = (lo.get(f"{k}_{w}") for k in ("ride", "susp", "svel", "hag"))
        rec = {}
        if ride is not None:
            r = ride.to_numpy(float)
            rec.update({"ride_min_cm": _r(np.nanpercentile(r, 0.5), 2), "ride_median_cm": _r(np.nanmedian(r), 2),
                        "ride_near_zero_s": _r(np.sum(r < 0.8) / 20.0, 1)})
        if trav is not None:
            tr = trav.to_numpy(float)
            top = np.nanmax(tr)
            # A hard limit (bump stop, end of travel) shows as samples piling up against a ceiling. Without one the
            # distribution simply thins out near its maximum, so the highest value seen is not a limit by itself.
            top_band = np.sum(tr > top - 0.0007)
            below = np.sum((tr > top - 0.0021) & (tr <= top - 0.0007))
            clipped = top_band >= 10 and top_band > 1.5 * max(below, 1) / 2      # per-mm density at the top beats the band below
            rec.update({"travel_max_mm": _r(top * 1000, 1), "travel_p99_mm": _r(np.nanpercentile(tr, 99) * 1000, 1),
                        "at_travel_limit_s": _r(top_band / 20.0, 1) if clipped else 0.0, "travel_clipped": bool(clipped)})
        if sv is not None:
            s = sv.to_numpy(float)
            bump, reb = s[s > 0], -s[s < 0]
            rec.update({"slow_share": _r(np.mean(np.abs(s) < DAMPER_SLOW), 3),
                        "bump_p95": _r(np.percentile(bump, 95), 3) if len(bump) > 50 else None,
                        "rebound_p95": _r(np.percentile(reb, 95), 3) if len(reb) > 50 else None,
                        "fast_bump_share": _r(np.mean(s > DAMPER_SLOW), 3), "fast_rebound_share": _r(np.mean(s < -DAMPER_SLOW), 3)})
        if hag is not None:
            h = hag.to_numpy(float)
            rec["wheel_lift_s"] = _r(np.sum(h > 0.004) / 20.0, 1)
        out[w] = rec
    return out


def gearing(lo: pd.DataFrame) -> dict:
    rpm, mx, gear = lo.rpm.to_numpy(float), float(np.nanmax(lo.max_rpm)) if "max_rpm" in lo else np.nan, lo.gear.to_numpy()
    up = np.flatnonzero(np.diff(gear) > 0)
    limiter = rpm >= 0.985 * mx if mx == mx else np.zeros(len(rpm), bool)
    top = int(np.nanmax(lo.num_gears)) if "num_gears" in lo else int(np.nanmax(gear))
    after = [rpm[i + 3] / rpm[i] for i in up if i + 3 < len(rpm) and rpm[i] > 0]
    return {"max_rpm": _r(mx, 0), "num_gears": top, "upshift_rpm": _r(np.median(rpm[up]), 0) if len(up) else None,
            "rpm_drop_on_upshift": _r(1 - np.median(after), 3) if after else None,
            "limiter_s": _r(limiter.sum() / 20.0, 1), "limiter_in_top_gear_s": _r((limiter & (gear == top)).sum() / 20.0, 1),
            "top_speed_kph": _r(np.nanmax(lo.speed) * 3.6, 1), "top_gear_share": _r(np.mean(gear == top), 3)}


def braking_traction(lo: pd.DataFrame) -> dict:
    """Lock-ups (a wheel turning much slower than the car under braking) and wheelspin (faster on power)."""
    v = lo.speed.to_numpy(float)
    # AMS2 reports the REAR share of brake bias (0.45 for a 55/45 garage setting): the front share is 1 - that
    bb = float(np.nanmedian(lo.brake_bias)) if "brake_bias" in lo else np.nan
    out = {"brake_bias_front": _r(1 - bb, 3) if bb == bb and 0 < bb < 1 else None,
           "abs_setting": int(np.nanmedian(lo.abs_setting)) if "abs_setting" in lo else None,
           "tc_setting": int(np.nanmedian(lo.tc_setting)) if "tc_setting" in lo else None,
           "abs_active_share_braking": _r(lo.abs_active[lo.brake > 0.3].mean(), 3) if "abs_active" in lo else None}
    steady = (lo.brake < 0.02) & (lo.throttle < 0.05) & (v > 20)   # coasting: no drive or brake slip in the reference
    for w in WHEELS:
        rps = lo.get(f"rps_{w}")
        if rps is None:
            continue
        r = np.abs(rps.to_numpy(float))
        # mTyreRPS is radians per second in practice (radius comes out ~0.33 m), whatever the header says
        radius = np.nanmedian(v[steady] / np.maximum(r[steady], 1e-3)) if steady.sum() > 50 else np.nan
        slip = (r * radius - v) / np.maximum(v, 1)
        # normal braking slip is ~4% (ABS holds ~10-12%) and traction slip 5-10%: a lock-up is beyond 20%, wheelspin beyond 15%
        out[f"lock_{w}_s"] = _r(np.sum((slip < -0.20) & (lo.brake > 0.2) & (v > 15)) / 20.0, 2)
        out[f"spin_{w}_s"] = _r(np.sum((slip > 0.15) & (lo.throttle > 0.5) & (v > 8)) / 20.0, 2)
        out[f"radius_{w}_m"] = _r(radius, 3)
    return out


def thermals(lo: pd.DataFrame) -> dict:
    mv = lo[lo.speed > 15]
    out = {"water_c": _r(np.nanpercentile(mv.water_temp, 95), 1) if "water_temp" in lo else None,
           "oil_c": _r(np.nanpercentile(mv.oil_temp, 95), 1) if "oil_temp" in lo else None}
    for w in WHEELS:
        b = mv.get(f"btemp_{w}")
        if b is not None:
            out[f"brake_{w}_peak_c"] = _r(np.nanpercentile(b, 99), 0)
            out[f"brake_{w}_median_c"] = _r(np.nanmedian(b[mv.brake > 0.3]), 0) if (mv.brake > 0.3).any() else None
    return out


def fuel(lo: pd.DataFrame) -> dict:
    if "fuel_level" not in lo or "fuel_capacity" not in lo:
        return {}
    cap = float(np.nanmedian(lo.fuel_capacity))
    litres = lo.fuel_level.to_numpy(float) * cap
    laps = []
    if "local_lap" in lo:
        for n, g in lo.groupby("local_lap"):
            if len(g) > 100:
                laps.append({"lap": int(n), "start_l": _r(g.fuel_level.iloc[0] * cap, 2), "used_l": _r((g.fuel_level.iloc[0] - g.fuel_level.iloc[-1]) * cap, 2)})
    used = [x["used_l"] for x in laps[1:-1] if x["used_l"] and x["used_l"] > 0.3]   # flying laps (not out or in lap)
    return {"capacity_l": _r(cap, 0), "start_l": _r(litres[0], 1), "end_l": _r(litres[-1], 1), "per_lap_l": _r(np.median(used), 2) if used else None,
            "laps": laps}


def run_evidence(path_or_session) -> dict:
    from ..derive import Session, load_session
    sess = path_or_session if isinstance(path_or_session, Session) else load_session(path_or_session)
    lo = sess.local.sort_values("t").reset_index(drop=True)
    moving = lo[lo.speed > 12]
    return {"car": (sess.meta.get("local") or {}).get("car"), "track": sess.meta.get("track_location"),
            "laps": int(lo.local_lap.max()) if "local_lap" in lo else None,
            "balance": balance(moving), "tyres": tyres(moving), "platform": platform(moving), "gearing": gearing(moving),
            "braking": braking_traction(lo), "thermals": thermals(lo), "fuel": fuel(lo)}
