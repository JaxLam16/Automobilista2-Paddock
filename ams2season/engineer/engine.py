"""The engineer's brain: measure a run, compare it with the last, recommend ticks, colour the nine categories,
and plan the next run.

Every rule only fires on evidence it can stand on, and says what that evidence was. Targets and thresholds
live in TARGETS so they can be tuned in one place. Where the engineer has measured what one tick does on this
car (from changes you made and the runs either side), it uses that instead of the starting estimate.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .catalog import BY_KEY, CATEGORIES, CORNER, action_text, garage_hint

ENGINE_VERSION = 3   # bump when recommendations or breakdowns change shape: older sessions are re-evaluated when opened
from .corners import corner_balance, find_corners
from .evidence import braking_traction, gearing, platform, thermals, tyres

WHEELS = ("fl", "fr", "rl", "rr")
TARGETS = {
    "press_bar": (1.80, 1.95),            # hot tyre pressure window (overridden by the car's tyre window)
    "camber_delta_c": (3.0, 8.0),         # inside minus outside surface temperature
    "water_c": (82.0, 100.0), "oil_c": (90.0, 118.0),
    "brake_front_c": (350.0, 750.0), "brake_rear_c": (300.0, 650.0),   # median under braking, peaks beyond 850 are too hot
    "top_gear_rpm": (0.94, 0.995),        # share of the rev limit reached in top gear on the longest straight
    "fast_gradient": (0.15, 0.40),        # extra steering per curvature from light to heavy cornering in fast corners
    "countersteer_s_lap": 0.30,           # countersteer per lap at one phase that counts as oversteer
    "abs_share": (0.03, 0.25),
    "ride_min_cm": 1.5,                   # lowest ride height to approach at an axle until the car's real floor is learned
    "ride_floor_margin_cm": 0.4,          # once a floor is learned (where it bottomed), stay this far above it
}


def targets(prefs: dict | None) -> dict:
    """The targets, moved by how you like the car. balance: -1 (likes understeer) .. +1 (likes oversteer);
    aggression: -1 (safe) .. +1 (aggressive). Preferences move what the engineer aims for, never the evidence."""
    p = prefs or {}
    bal = float(np.clip(p.get("balance", 0.0), -1, 1))
    agg = float(np.clip(p.get("aggression", 0.0), -1, 1))
    t = dict(TARGETS)
    lo, hi = TARGETS["fast_gradient"]
    shift = -0.12 * bal                                  # likes oversteer: aim for less understeer at speed
    t["fast_gradient"] = (max(0.0, lo + shift), hi + shift)
    t["countersteer_s_lap"] = float(np.clip(TARGETS["countersteer_s_lap"] * (1 + 0.6 * max(bal, 0) + 0.5 * max(agg, 0)
                                                                             - 0.3 * max(-bal, 0) - 0.4 * max(-agg, 0)), 0.12, 0.8))
    t["ride_min_cm"] = TARGETS["ride_min_cm"] - 0.4 * agg     # aggressive runs closer to the ground
    t["ride_floor_margin_cm"] = TARGETS["ride_floor_margin_cm"] - 0.15 * agg
    t["abs_share"] = (TARGETS["abs_share"][0], TARGETS["abs_share"][1] + 0.1 * agg)
    return t


# what one tick does, until the engineer has measured it on this car
TICK_GUESS = {"pressure": 0.012, "camber": 1.8, "final_drive": 0.025, "fast_gradient": 0.06, "ride_height": 0.1}   # ride height: cm per tick


def _r(v, dp=2):
    return None if v is None or (isinstance(v, float) and (v != v or not math.isfinite(v))) else round(float(v), dp)


# ----------------------------------------------------------------------------------------------- measuring
def flying_laps(lo: pd.DataFrame) -> list[pd.DataFrame]:
    """Laps after the out lap that are complete and valid (the in lap and any lap with a pit visit excluded)."""
    out = []
    groups = list(lo.groupby("local_lap"))
    for i, (n, g) in enumerate(groups):
        if n == groups[0][0] or i == len(groups) - 1 or len(g) < 200:
            continue
        if "local_lap_invalid" in g and g.local_lap_invalid.any():
            continue
        out.append(g.sort_values("t"))
    if not out:  # a run ending mid-lap: the last lap counts if complete enough
        for n, g in groups[1:]:
            if len(g) >= 200 and not ("local_lap_invalid" in g and g.local_lap_invalid.any()):
                out.append(g.sort_values("t"))
    return out


def _fast_gradient(lo: pd.DataFrame):
    v = lo.speed.to_numpy(float)
    kap = np.abs(lo.yaw_rate.to_numpy(float)) / np.maximum(v, 5)
    st, ay = np.abs(lo.steering.to_numpy(float)), np.abs(lo.acc_lat.to_numpy(float))
    m = (kap > 0.003) & (np.sign(lo.steering.to_numpy(float)) == np.sign(-lo.yaw_rate.to_numpy(float))) & (lo.brake.to_numpy(float) < 0.05) \
        & (np.abs(lo.acc_long.to_numpy(float)) < 3) & (v * 3.6 > 150)
    spc, a = st[m] / kap[m], ay[m]
    lo_g, hi_g = spc[(a > 4) & (a < 9)], spc[a > 13]
    if len(lo_g) < 15 or len(hi_g) < 60:
        return None, int(len(lo_g))
    return float(np.median(hi_g) / np.median(lo_g) - 1), int(len(lo_g))


def _countersteer(lo: pd.DataFrame, n_laps: int) -> dict:
    v = lo.speed.to_numpy(float)
    kap = -lo.yaw_rate.to_numpy(float) / np.maximum(v, 5)
    st = lo.steering.to_numpy(float)
    turning = (np.abs(kap) > 0.004) & (v > 12)
    c = turning & (np.sign(st) == -np.sign(kap)) & (np.abs(st) > 0.02) & (np.abs(lo.acc_lat.to_numpy(float)) > 5)
    thr, brk = lo.throttle.to_numpy(float), lo.brake.to_numpy(float)
    fast = v * 3.6 > 150
    per = lambda m: _r(m.sum() / 20.0 / max(n_laps, 1), 2)
    return {"entry": per(c & (brk > 0.1)), "mid": per(c & (brk < 0.05) & (thr < 0.5)), "exit": per(c & (thr >= 0.5)),
            "lift": per(c & (brk < 0.05) & (thr < 0.05)), "fast": per(c & fast)}


def measure_run(lo: pd.DataFrame, L: float, corners_ref: list | None = None) -> dict:
    """Everything the rules need from one run (the recording car's telemetry for that stint)."""
    lo = lo.sort_values("t").reset_index(drop=True)
    flying = flying_laps(lo)
    fl = pd.concat(flying) if flying else lo[lo.speed > 12]
    n = max(len(flying), 1)
    has = lambda c: c in lo.columns and lo[c].notna().any()
    laps = []
    for g in flying:
        laps.append({"lap": int(g.local_lap.iat[0]), "time": _r(g.t.iat[-1] - g.t.iat[0], 3),
                     "fuel_l": _r(g.fuel_level.iat[0] * g.fuel_capacity.iat[0], 1) if has("fuel_capacity") else None})
    ref = flying[0] if flying else lo
    corners = corners_ref or (find_corners(ref, L) if has("yaw_rate") else [])
    cb = {}
    for g in flying:
        for name, b in corner_balance(g, corners).items():
            cb.setdefault(name, []).append(b["steer_per_curv"])
    m = {"laps": laps, "n_flying": len(flying), "corners": corners,
         "corner_balance": {k: _r(float(np.median(v)), 3) for k, v in cb.items()}}
    if has("yaw_rate"):
        m["fast_gradient"], m["fast_gradient_n"] = _fast_gradient(fl)
        m["countersteer"] = _countersteer(fl, n)
    m["full_throttle_share"] = _r(float((fl.throttle > 0.95).mean()), 3)
    m["steer_max"] = _r(float(np.nanpercentile(np.abs(fl.steering), 99.5)), 3)
    if has("rpm") and has("gear"):
        g_ = gearing(fl)
        top = g_["num_gears"]
        in_top = fl[fl.gear == top]
        m["gearing"] = {**g_, "top_gear_rpm_frac": _r(float(in_top.rpm.max() / g_["max_rpm"]), 3) if len(in_top) > 20 and g_["max_rpm"] else None,
                        "limiter_top_s_lap": _r(g_["limiter_in_top_gear_s"] / n, 2)}
    if has("rps_fl"):
        b = braking_traction(fl)
        m["braking"] = {**b, **{k: _r(v / n, 2) for k, v in b.items() if k.startswith(("lock_", "spin_")) and v is not None},
                        "peak_decel": _r(float(np.nanpercentile(fl.acc_long, 99.5)), 1) if has("acc_long") else None}
    if has("tc_fl") or has("ttemp_fl"):
        m["tyres"] = tyres(fl)
    if has("press_fl"):
        from ..tyres import to_bar
        mv = lo[lo.speed > 12]
        bu = {}
        for w in WHEELS:
            p = to_bar(mv[f"press_{w}"].to_numpy(float))
            first = to_bar(flying[0][f"press_{w}"].to_numpy(float)) if flying else p
            last = to_bar(flying[-1][f"press_{w}"].to_numpy(float)) if len(flying) >= 2 else None
            bu[w] = {"cold": _r(float(np.nanmedian(p[:100])), 3), "first_flying": _r(float(np.nanmedian(first)), 3),
                     "last_flying": _r(float(np.nanmedian(last)), 3) if last is not None else None}
        m["press_buildup"] = bu
    if has("ride_fl"):
        p = platform(fl)
        m["platform"] = {w: {**v, **{k: _r(v[k] / n, 2) for k in ("ride_near_zero_s", "at_travel_limit_s", "wheel_lift_s") if v.get(k) is not None}}
                         for w, v in p.items()}
    if has("water_temp"):
        m["thermals"] = thermals(lo)
    if has("fuel_capacity"):
        cap = float(np.nanmedian(lo.fuel_capacity))
        used = []
        for g in flying:
            u = (g.fuel_level.iat[0] - g.fuel_level.iat[-1]) * cap
            if u > 0.2:
                used.append(u)
        m["fuel"] = {"capacity_l": _r(cap, 0), "start_l": _r(float(lo.fuel_level.iat[0]) * cap, 1),
                     "per_lap_l": _r(float(np.median(used)), 2) if used else None, "laps_measured": len(used)}
    if has("wear_fl") and flying:
        per = {}
        for w in WHEELS:
            d = [float(g[f"wear_{w}"].iat[-1] - g[f"wear_{w}"].iat[0]) * 100 for g in flying if f"wear_{w}" in g]
            d = [x for x in d if x >= 0]
            per[w] = _r(float(np.median(d)), 3) if d else None
        m["wear_per_lap_pct"] = per
    m["compound"] = str(lo.compound.dropna().iloc[0]) if has("compound") else None
    m["best_lap"] = min((x["time"] for x in laps if x["time"]), default=None)
    m["avg_lap"] = _r(float(np.mean([x["time"] for x in laps if x["time"]])), 3) if laps else None
    return m


# ----------------------------------------------------------------------------------------------- recommending
def _rec(key, ticks, why, evidence, confidence, priority=2, test=False, category=None):
    ticks = int(ticks)
    s = BY_KEY[key]
    assert category is None or category == s["category"] or category in s["also"], (key, category)
    return {"id": key, "setting": key, "label": s["label"], "category": category or s["category"], "ticks": ticks,
            "action": action_text(key, ticks), "garage": garage_hint(key, ticks), "why": why, "evidence": evidence, "confidence": confidence,
            "priority": priority, "test": test}


def recommend(m: dict, state: dict, prev: dict | None = None) -> list[dict]:
    """Recommendations for the next run. `state` carries unavailable settings, maxed-out directions, learned
    per-tick effects, the tyre window and the race target."""
    TG = targets(state.get("prefs"))
    learned = state.get("learned", {})
    unavailable = set(state.get("unavailable", []))
    maxed = state.get("maxed", {})            # key -> "up" / "down": that direction is used up
    out = []
    win = state.get("press_window") or TG["press_bar"]

    def add(key, ticks, *a, **k):
        if key in unavailable or ticks == 0 or not BY_KEY[key]["analysed"]:
            return
        if maxed.get(key) == ("up" if ticks > 0 else "down"):
            return
        out.append(_rec(key, ticks, *a, **k))

    # ---- tyre contact: hot pressures and camber, per wheel
    ty = m.get("tyres") or {}
    per_tick_p = learned.get("pressure", {}).get("per_tick") or TICK_GUESS["pressure"]
    for w in WHEELS:
        t = ty.get(w) or {}
        hot = t.get("press_hot_bar")
        if hot and m["n_flying"] >= 2:
            target = sum(win) / 2
            err = target - hot
            if not (win[0] <= hot <= win[1]) or abs(err) > 0.05:      # inside the window and near its middle: leave it
                n = int(np.clip(round(err / per_tick_p), -8, 8))
                add(f"pressure_{w}", n, f"Hot pressure {hot:.2f} bar against a {win[0]:.2f}-{win[1]:.2f} bar window: aim for {target:.2f}.",
                    {"hot_bar": hot, "target_bar": round(target, 3), "per_tick_bar": round(per_tick_p, 4)}, "high" if m["n_flying"] >= 3 else "medium", 1)
        d = t.get("inner_minus_outer")
        lo_, hi_ = TG["camber_delta_c"]
        if d is not None and m["n_flying"] >= 2 and not (lo_ <= d <= hi_):
            per_tick_c = learned.get("camber", {}).get("per_tick") or TICK_GUESS["camber"]
            goal = (lo_ + hi_) / 2
            n = int(np.clip(round((goal - d) / per_tick_c), -3, 3)) or (1 if d < lo_ else -1)
            add(f"camber_{w}", n, f"Inside of the tyre is {d:+.1f} °C against the outside; {lo_:.0f}-{hi_:.0f} °C means the camber has the tyre working evenly.",
                {"inside_minus_outside_c": d, "target_c": goal}, "medium", 2)

    # ---- braking & traction
    b = m.get("braking") or {}
    abs_share = b.get("abs_active_share_braking")
    if abs_share is not None and m["n_flying"] >= 2:
        if abs_share > TG["abs_share"][1]:
            add("brake_pressure", -1 if abs_share < 0.4 else -2, f"ABS is working in {abs_share:.0%} of braking: the pedal is overpowering the tyres.",
                {"abs_share": abs_share}, "medium")
        elif abs_share < TG["abs_share"][0] and (b.get("peak_decel") or 99) < 14:
            add("brake_pressure", 1, f"ABS barely works ({abs_share:.0%}) and peak braking is only {b['peak_decel']:.1f} m/s²: there's grip unused.",
                {"abs_share": abs_share, "peak_decel": b.get("peak_decel")}, "medium")
    fl_lock = (b.get("lock_fl_s") or 0) + (b.get("lock_fr_s") or 0)
    rr_lock = (b.get("lock_rl_s") or 0) + (b.get("lock_rr_s") or 0)
    cs = m.get("countersteer") or {}
    if fl_lock - rr_lock > 0.3:
        add("brake_bias", -1, f"Fronts lock {fl_lock:.1f} s a lap against {rr_lock:.1f} s at the rear: move bias rearward.", {"front_lock_s_lap": fl_lock, "rear_lock_s_lap": rr_lock}, "medium")
    elif rr_lock - fl_lock > 0.3 or (cs.get("entry") or 0) > TG["countersteer_s_lap"]:
        add("brake_bias", 1, f"The rear is unsettled under braking (rear locking {rr_lock:.1f} s a lap, countersteer on entry {cs.get('entry') or 0:.1f} s a lap): move bias forward.",
            {"rear_lock_s_lap": rr_lock, "entry_countersteer_s_lap": cs.get("entry")}, "medium")
    if max(fl_lock, rr_lock) > 0.5 and b.get("abs_setting") is not None:
        add("abs", 1, f"Wheels still lock ({max(fl_lock, rr_lock):.1f} s a lap) with ABS at {b['abs_setting']}.", {"lock_s_lap": max(fl_lock, rr_lock)}, "medium")
    if (cs.get("lift") or 0) > TG["countersteer_s_lap"]:
        add("engine_braking", -1, f"The rear steps out when you lift ({cs['lift']:.1f} s of countersteer a lap off both pedals): less engine braking calms it.",
            {"lift_countersteer_s_lap": cs["lift"]}, "medium")
    spin_l, spin_r = b.get("spin_rl_s"), b.get("spin_rr_s")
    if spin_l is not None and spin_r is not None:
        if (cs.get("exit") or 0) > TG["countersteer_s_lap"] and b.get("tc_setting") is not None:
            add("traction_control", 1, f"The rear steps out on power ({cs['exit']:.1f} s of countersteer a lap at exits).",
                {"exit_countersteer_s_lap": cs["exit"], "tc": b["tc_setting"]}, "medium")
        if abs(spin_l - spin_r) > 1.0:
            add("rear_diff_clutches", 1, f"One rear wheel spins far more than the other ({spin_l:.1f} s vs {spin_r:.1f} s a lap over 15% slip): the inside wheel is spinning away drive.",
                {"spin_rl_s_lap": spin_l, "spin_rr_s_lap": spin_r}, "low")

    # ---- chassis balance (mid-corner and exit oversteer: countersteer is proof)
    if (cs.get("mid") or 0) > TG["countersteer_s_lap"]:
        add("arb_rear", -1, f"The rear slides mid-corner ({cs['mid']:.1f} s of countersteer a lap): soften the rear bar.", {"mid_countersteer_s_lap": cs["mid"]}, "medium")
    tc_offered = any(r["setting"] == "traction_control" for r in out)
    if (cs.get("exit") or 0) > 1.5 * TG["countersteer_s_lap"] and not tc_offered:   # one remedy at a time
        add("toe_rear", 1, f"Persistent oversteer on exit ({cs['exit']:.1f} s a lap): a little more rear toe-in adds stability.", {"exit_countersteer_s_lap": cs["exit"]}, "low", 3)
    if m.get("steer_max") and m["steer_max"] > 0.95:
        add("steering_lock", 1, f"You're using {m['steer_max']:.0%} of the steering in the tightest corners.", {"steer_max": m["steer_max"]}, "high")

    # ---- aero balance: fast-corner understeer gradient, fast-corner oversteer
    fg = m.get("fast_gradient")
    lo_g, hi_g = TG["fast_gradient"]
    if (cs.get("fast") or 0) > TG["countersteer_s_lap"]:
        add("downforce_rear", 1, f"The rear slides in fast corners ({cs['fast']:.1f} s of countersteer a lap): more rear downforce.", {"fast_countersteer_s_lap": cs["fast"]}, "medium", 1)
    elif fg is not None and fg > hi_g:
        per = learned.get("fast_gradient", {}).get("per_tick") or TICK_GUESS["fast_gradient"]
        n = -int(np.clip(round((fg - (lo_g + hi_g) / 2) / per), 1, 3))
        add("downforce_rear", n, f"In fast corners you need {fg:.0%} more steering for the same curvature once the car is loaded: the front runs out of grip first. Less rear downforce shifts the aero balance forward.",
            {"fast_gradient": fg, "target": [lo_g, hi_g], "samples": m.get("fast_gradient_n")}, "medium", 1)
    elif fg is not None and fg < lo_g:
        add("downforce_front", -1, f"Fast corners are close to neutral ({fg:.0%}): the car may be nervous at speed. A touch less front downforce adds stability.",
            {"fast_gradient": fg, "target": [lo_g, hi_g]}, "low", 2)

    # ---- downforce level: a test, not a fix
    # (a paired change: both wings together keep the aero balance where it is, so only the total moves)
    fts = m.get("full_throttle_share")
    aero_recs = any(r["setting"] in ("downforce_front", "downforce_rear") for r in out)
    if fts is not None and fts > 0.62 and not state.get("tested", {}).get("downforce_level") and not aero_recs:
        why = f"{fts:.0%} of the lap is flat out: worth testing less drag. Take 1 tick off both wings together (keeping the balance) and compare lap time."
        for k in ("downforce_front", "downforce_rear"):
            add(k, -1, why, {"full_throttle_share": fts}, "low", 3, test=True, category="downforce")

    # ---- gearing: how close top gear gets to the limiter
    g = m.get("gearing") or {}
    frac = g.get("top_gear_rpm_frac")
    if g:
        if (g.get("limiter_top_s_lap") or 0) > 0.4:
            add("final_drive", -1, f"You're on the limiter in top gear for {g['limiter_top_s_lap']:.1f} s a lap.", {"limiter_top_s_lap": g["limiter_top_s_lap"]}, "high", 1)
        elif frac is not None and frac < TG["top_gear_rpm"][0]:
            per = learned.get("final_drive", {}).get("per_tick") or TICK_GUESS["final_drive"]
            n = int(np.clip(round((0.97 - frac) / per), 1, 3))
            add("final_drive", n, f"Top gear only reaches {frac:.0%} of the rev limit on the longest straight: shorter gearing gives more acceleration everywhere.",
                {"top_gear_rpm_frac": frac, "top_speed_kph": g.get("top_speed_kph")}, "high" if m["n_flying"] >= 2 else "medium", 1)

    # ---- ground clearance: bottoming and the travel limit, per corner
    pf = m.get("platform") or {}
    for w in WHEELS:
        p = pf.get(w) or {}
        if (p.get("ride_near_zero_s") or 0) > 0.2 or (p.get("at_travel_limit_s") or 0) > 0.5:
            add(f"ride_height_{w}", 1, f"{CORNER[w]} bottoms out or sits on the travel limit ({p.get('ride_near_zero_s') or 0:.1f} s near zero ride height, {p.get('at_travel_limit_s') or 0:.1f} s on the limit, per lap).",
                {k: p.get(k) for k in ("ride_min_cm", "ride_near_zero_s", "at_travel_limit_s")}, "medium", 1)
        if (p.get("wheel_lift_s") or 0) > 1.5:
            add(f"fast_bump_{w}", -1, f"{CORNER[w]} wheel leaves the ground {p['wheel_lift_s']:.1f} s a lap (kerbs): softer fast bump lets it follow the surface.",
                {"wheel_lift_s_lap": p["wheel_lift_s"]}, "low", 3)

    # ---- ride height: lower where there's measured room. Lower is usually faster (more floor downforce, less
    # drag) but it's also how a car starts bottoming, so: only after 2+ flying laps with no bottoming or hard
    # travel limit on that axle, both wheels of an axle together (judged by the lower one), half the remaining
    # room per run (at most 4 ticks), and never below the floor learned from a run where it did bottom.
    if m["n_flying"] >= 2:
        fg_now = m.get("fast_gradient")
        fast_os = (cs.get("fast") or 0) > TG["countersteer_s_lap"]
        axles = (("front", ("fl", "fr")), ("rear", ("rl", "rr")))
        # Rake: lowering the front moves aero balance forward, lowering the rear moves it back. If the wings are
        # already being changed for the balance, lower both axles by the same amount instead (one remedy per symptom).
        wing_recs = any(r["setting"] in ("downforce_front", "downforce_rear") for r in out)
        if not wing_recs and fg_now is not None and fg_now > TG["fast_gradient"][1]:
            axles = axles[:1]
        elif not wing_recs and fast_os:
            axles = axles[1:]
        per_tick = learned.get("ride_height", {}).get("per_tick") or TICK_GUESS["ride_height"]
        plans = []
        for axle, ws in axles:
            ps = [pf.get(w) or {} for w in ws]
            if any((p.get("ride_near_zero_s") or 0) > 0 or (p.get("at_travel_limit_s") or 0) > 0 for p in ps):
                continue
            mins = [p.get("ride_min_cm") for p in ps if p.get("ride_min_cm") is not None]
            if len(mins) < 2:
                continue
            floor = (learned.get(f"ride_floor_{axle}") or {}).get("cm")
            target = floor + TG["ride_floor_margin_cm"] if floor is not None else TG["ride_min_cm"]
            room = min(mins) - target
            if room > 0.3:
                plans.append((axle, ws, min(mins), target, room, floor))
        if wing_recs and len(plans) == 2:   # keep the rake: both axles by the smaller step
            n_both = min(int(np.clip(round(pl[4] / per_tick / 2), 1, 4)) for pl in plans)
        elif wing_recs:
            plans = []                       # only one axle has room: that would change the balance too; wait
        for axle, ws, low, target, room, floor in plans:
            if room:
                n = n_both if wing_recs else int(np.clip(round(room / per_tick / 2), 1, 4))
                why = (f"The {axle} never got closer than {low:.1f} cm to the ground over {m['n_flying']} flying laps, with no bottoming: "
                       f"{room:.1f} cm of room above the {target:.1f} cm {'floor learned for this car' if floor is not None else 'safety margin'}. "
                       "Lower is faster (more downforce from the floor, less drag); this closes about half the gap, and the next run checks it's still clear. "
                       + ("Both axles go down together so the rake, and the balance, stay where the wing change puts them." if wing_recs
                          else "Lowering the front adds rake: more front grip in fast corners." if axle == "front" else "Lowering the rear reduces rake: a little more stable at speed."))
                for w in ws:
                    add(f"ride_height_{w}", -n, why, {"ride_min_cm": low, "target_cm": round(target, 2), "room_cm": round(room, 2),
                                                      "cm_per_tick": round(per_tick, 3), "floor_learned": floor is not None}, "medium", 2)

    # ---- thermals & reliability
    th = m.get("thermals") or {}
    wt, ot = th.get("water_c"), th.get("oil_c")
    if wt is not None and ot is not None:
        if wt > TG["water_c"][1] or ot > TG["oil_c"][1]:
            add("radiator", 2, f"Engine running hot (water {wt:.0f} °C, oil {ot:.0f} °C): open the radiator before it costs power or reliability.", {"water_c": wt, "oil_c": ot}, "high", 1)
        elif wt < TG["water_c"][0] - 2 and ot < TG["oil_c"][0]:
            add("radiator", -1, f"Engine running cool (water {wt:.0f} °C, oil {ot:.0f} °C): a smaller radiator opening cuts drag.", {"water_c": wt, "oil_c": ot}, "medium", 3)
    for axle, ws, key in (("front", ("fl", "fr"), "duct_front"), ("rear", ("rl", "rr"), "duct_rear")):
        med = [th.get(f"brake_{w}_median_c") for w in ws if th.get(f"brake_{w}_median_c")]
        pk = [th.get(f"brake_{w}_peak_c") for w in ws if th.get(f"brake_{w}_peak_c")]
        lo_b, hi_b = TG[f"brake_{axle}_c"]
        if med and pk:
            if max(pk) > 850 or np.mean(med) > hi_b:
                add(key, 1, f"{axle.capitalize()} brakes too hot (median {np.mean(med):.0f} °C under braking, peak {max(pk):.0f} °C).", {"median_c": round(float(np.mean(med))), "peak_c": max(pk)}, "high", 1)
            elif np.mean(med) < lo_b:
                add(key, -1, f"{axle.capitalize()} brakes running cool ({np.mean(med):.0f} °C under braking): close the duct for less drag and quicker warm-up.", {"median_c": round(float(np.mean(med)))}, "medium", 3)

    out.sort(key=lambda r: (r["priority"], {"high": 0, "medium": 1, "low": 2}[r["confidence"]]))
    return out


# ----------------------------------------------------------------------------------------------- statuses & plans
COLORS = ("red", "orange", "yellow", "green", "blue")


def categories(m: dict | None, recs: list[dict], state: dict) -> dict:
    """Colour per category. Red: no evidence, or well off. Orange/yellow: getting there. Green: dialled in.
    Blue: dialled in and confirmed by a second run with nothing left to change."""
    out = {}
    for key, label in CATEGORIES:
        mine = [r for r in recs if r["category"] == key and not r.get("test")]
        evidence = m is not None and _has_evidence(key, m)
        if not evidence:
            out[key] = {"label": label, "color": "red", "text": "No evidence yet"}
            continue
        # how far off: the biggest single change, plus a little for each further one. Both wheels of an axle
        # (front left + front right ride height, say) are one decision, not two.
        groups = {}
        for r in mine:
            k = r["setting"]
            if k[-3:] in ("_fl", "_fr"):
                k = k[:-3] + "_front"
            elif k[-3:] in ("_rl", "_rr"):
                k = k[:-3] + "_rear"
            groups[k] = max(groups.get(k, 0), abs(r["ticks"]))
        big = (max(groups.values()) + 0.5 * (len(groups) - 1)) if groups else 0
        mine = list(groups)
        if big == 0:
            confirmed = state.get("clean_streak", {}).get(key, 0) >= 2     # two runs with evidence, nothing to change
            out[key] = {"label": label, "color": "blue" if confirmed else "green", "text": "Confirmed by two runs" if confirmed else "Dialled in"}
        elif big <= 2:
            out[key] = {"label": label, "color": "yellow", "text": f"{len(mine)} small change{'s' if len(mine) > 1 else ''}"}
        elif big <= 4.5:
            out[key] = {"label": label, "color": "orange", "text": f"{len(mine)} change{'s' if len(mine) > 1 else ''} needed"}
        else:
            out[key] = {"label": label, "color": "red", "text": "Well off target"}
    return out


def _has_evidence(cat: str, m: dict) -> bool:
    n = m.get("n_flying", 0)
    return {"pit_strategy": (m.get("fuel") or {}).get("per_lap_l") is not None,
            "gearing": bool(m.get("gearing")) and n >= 1,
            "ground_clearance": bool(m.get("platform")) and n >= 1,
            "tyre_contact": bool(m.get("tyres")) and n >= 2,
            "chassis_balance": "countersteer" in m and n >= 2,
            "aero_balance": m.get("fast_gradient") is not None or (m.get("countersteer") or {}).get("fast") is not None and n >= 2,
            "downforce": m.get("full_throttle_share") is not None and n >= 2,
            "braking_traction": bool(m.get("braking")) and n >= 2,
            "thermals": bool(m.get("thermals")) and n >= 1}[cat]


TYRE_CHANGE_AT_PCT = 70.0   # plan a tyre change before the worst tyre is this worn


def race_fuel(state: dict, m: dict | None) -> dict | None:
    """The race plan: fuel, stops and tyres for your race target. Practice measurements are scaled by the race's
    fuel and tyre wear multipliers (against practice's, if different). Stops are the most of: mandatory stops,
    what the tank needs, and what the tyres need."""
    tgt = state.get("race_target") or {}
    per_meas = ((m or {}).get("fuel") or {}).get("per_lap_l") if m else None
    per_meas = per_meas or state.get("fuel_per_lap")
    lap = (m or {}).get("avg_lap") or state.get("avg_lap")
    if not per_meas:
        return None
    def scale(k):   # race multiplier over practice's (0 = off in AMS2: nothing used)
        race = float(tgt.get(k + "_mult", 1) if tgt.get(k + "_mult") is not None else 1)
        prac = float(tgt.get("practice_" + k + "_mult") or 1) if tgt.get("practice_differs") else race
        return 0.0 if race == 0 else race / prac if prac > 0 else 1.0
    f_scale, t_scale = scale("fuel"), scale("tyre")
    per = per_meas * f_scale
    if tgt.get("mode") == "laps":
        laps = int(tgt.get("laps") or 0)
    elif lap:
        laps = math.ceil((tgt.get("minutes") or 60) * 60 / lap) + 1    # the lap in progress when time runs out
    else:
        return None
    cap = ((m or {}).get("fuel") or {}).get("capacity_l") if m else None
    cap = cap or 120.0
    total = laps * per + per                                           # one lap in reserve
    notes = ["Fuel usage is off for the race: no fuel is used, so carry the minimum."] if f_scale == 0 else []
    stops_fuel = max(0, math.ceil(total / cap) - 1)
    wear = (m or {}).get("wear_per_lap_pct") or {}
    worst = max((v for v in wear.values() if v is not None), default=None)
    worst_race = worst * t_scale if worst is not None else None
    life = int(TYRE_CHANGE_AT_PCT // worst_race) if worst_race and worst_race > 0 else None
    stops_tyre = max(0, math.ceil(laps / life) - 1) if life else 0
    mandatory = int(tgt.get("pit_stops") or 0)
    stops = max(mandatory, stops_fuel, stops_tyre)
    why = [r for r, n in (("mandatory stops", mandatory), ("fuel tank size", stops_fuel), ("tyre wear", stops_tyre)) if n == stops and n > 0]
    stints, left = [], laps
    for k in range(stops + 1):
        n = math.ceil(left / (stops + 1 - k))
        left -= n
        stints.append(n)
    plan, on_set = [], 0          # laps the current set of tyres has done since it was fitted
    for k, n in enumerate(stints):
        fuel = n * per + (per if k == len(stints) - 1 else 0.5 * per)  # a lap's reserve at the end, half a lap into each stop
        if k == 0:
            tyres, on_set = "new", n
        elif life is not None and on_set + n > life:
            tyres, on_set = "change", n
        else:
            tyres, on_set = "keep", on_set + n
        plan.append({"stint": k + 1, "laps": n, "fuel_l": int(math.ceil(min(fuel, cap))), "tyres": tyres,
                     "tyre_wear_end_pct": round(worst_race * on_set, 1) if worst_race else None})   # wear on that set by the end of the stint
    if f_scale != 1:
        notes.append(f"Fuel measured in practice ({per_meas:.2f} L a lap) is scaled ×{f_scale:g} for the race's fuel usage setting.")
    if t_scale != 1 and worst is not None:
        notes.append(f"Tyre wear measured in practice ({worst:.2f}% a lap, worst tyre) is scaled ×{t_scale:g} for the race's tyre wear setting.")
    if worst is None:
        notes.append("No tyre wear measured yet: stops are planned from fuel and the mandatory stops only.")
    acc = float(tgt.get("time_accel") or 1)
    if tgt.get("mode") != "laps" and acc > 1:
        span_h = (tgt.get("minutes") or 60) * acc / 60
        if span_h >= 2:
            notes.append(f"With ×{acc:g} time acceleration, {span_h:.1f} hours of in-game time pass during the race: light and track temperature "
                         "will change, so hot tyre pressures and grip will drift from what practice showed. It doesn't change fuel or tyre wear "
                         "(the race length is real time).")
    return {"laps": laps, "per_lap_l": round(per, 2), "per_lap_measured_l": round(per_meas, 2), "litres": int(math.ceil(total)),
            "capacity_l": cap, "stops": stops, "stops_reason": why, "stints": plan, "start_fuel_l": plan[0]["fuel_l"],
            "wear_per_lap_pct": round(worst_race, 3) if worst_race else None, "tyre_life_laps": life, "notes": notes}


def next_run(state: dict, m: dict | None, recs: list[dict]) -> dict:
    runs = state.get("runs_analysed", 0)
    rf = race_fuel(state, m)
    cap = ((m or {}).get("fuel") or {}).get("capacity_l") or 120
    if runs == 0 or not state.get("high_fuel_done"):
        return {"fuel_l": int(cap), "tyres": "Slick", "laps": 6, "objective": "Full tank: measure fuel use and tyre behaviour, and see the car's pace on maximum fuel."
                + (" (No full-tank run yet: the runs so far were on low fuel.)" if runs else "")}
    if not state.get("low_fuel_done"):
        low = int(math.ceil((rf["per_lap_l"] if rf else 3.0) * 5 + 3))
        return {"fuel_l": low, "tyres": "Slick", "laps": 4, "objective": "Low fuel: compare your pace with the full-tank run to learn what the fuel load costs."}
    if recs:
        return {"fuel_l": min(rf["start_fuel_l"], int(cap)) if rf else int(cap * 0.5), "tyres": "Slick", "laps": 5,
                "objective": f"Try the {len(recs)} change{'s' if len(recs) != 1 else ''} below and confirm they help."}
    return {"fuel_l": min(rf["start_fuel_l"], int(cap)) if rf else int(cap * 0.5), "tyres": "Slick", "laps": 5,
            "objective": "Setup is settled: a race-fuel confirmation run, or you're ready to go racing."}


def compare(prev: dict | None, m: dict) -> dict | None:
    """How this run differs from the last one, corner by corner and overall."""
    if not prev:
        return None
    a, b = prev.get("corner_balance") or {}, m.get("corner_balance") or {}
    common = [k for k in a if k in b and a[k] and b[k]]
    out = {"best_lap_delta": _r((m.get("best_lap") or 0) - (prev.get("best_lap") or 0), 3) if m.get("best_lap") and prev.get("best_lap") else None}
    if len(common) >= 4:
        ch = np.array([b[k] / a[k] - 1 for k in common])
        out.update({"balance_change": _r(float(np.median(ch)), 3), "corners": len(common), "corners_more_understeer": int((ch > 0.05).sum()),
                    "corners_less_understeer": int((ch < -0.05).sum())})
    if prev.get("fast_gradient") is not None and m.get("fast_gradient") is not None:
        out["fast_gradient_change"] = _r(m["fast_gradient"] - prev["fast_gradient"], 3)
    return out


# ----------------------------------------------------------------------------------------------- qualifying setup
def quali_variant(m: dict, state: dict) -> list[dict]:
    """Changes on top of the race setup for qualifying: little fuel, tyres that reach their window by the
    timed lap, less cooling for a short run, and a step less TC if the rear isn't stepping out. Each one
    comes from this run's measurements; anything the data can't support is left out."""
    TG = targets(state.get("prefs"))
    unavailable = set(state.get("unavailable", []))
    out = []

    def add(key, ticks, why, evidence, conf="medium"):
        if key in unavailable or ticks == 0:
            return
        out.append(_rec(key, ticks, why, evidence, conf, 2))
    f = m.get("fuel") or {}
    tgt = state.get("race_target") or {}
    f_scale = float(tgt.get("fuel_mult") or 1) / float(tgt.get("practice_fuel_mult") or tgt.get("fuel_mult") or 1) if tgt.get("practice_differs") else 1.0
    if f.get("per_lap_l"):
        litres = int(math.ceil(f["per_lap_l"] * f_scale * 3.5 + 1))
        out.append({"id": "q_fuel", "setting": "fuel", "label": "Fuel", "category": "pit_strategy", "ticks": 0, "action": f"Set to {litres} L",
                    "why": f"Out lap, two timed laps and a reserve at {f['per_lap_l']:.2f} L a lap: every litre you don't carry is lap time.",
                    "evidence": {"per_lap_l": f["per_lap_l"]}, "confidence": "high", "priority": 1, "test": False})
    per_tick = (state.get("learned", {}).get("pressure", {}) or {}).get("per_tick") or TICK_GUESS["pressure"]
    for w, b in (m.get("press_buildup") or {}).items():
        settled = b.get("last_flying")         # the latest lap of the run: as close to settled as the run gets
        if not settled or not b.get("first_flying"):
            continue
        short = settled - b["first_flying"]    # how far below that the tyre still was on the first timed lap
        if short > 0.02:
            n = int(np.clip(round(short / per_tick), 1, 8))
            add(f"pressure_{w}", n, f"On your first flying lap this tyre was still {short:.2f} bar below where it got to by the end of the run "
                f"({b['first_flying']:.2f} against {settled:.2f}): start it higher so it's up to pressure for the timed lap.",
                {"first_flying_bar": b["first_flying"], "end_of_run_bar": settled}, "medium" if m.get("n_flying", 0) >= 3 else "low")
    th = m.get("thermals") or {}
    if th.get("water_c") is not None and th.get("oil_c") is not None:
        room = min(TG["water_c"][1] - th["water_c"], TG["oil_c"][1] - th["oil_c"])
        if room > 8:
            add("radiator", -2 if room > 15 else -1, f"Water peaks at {th['water_c']:.0f} °C and oil at {th['oil_c']:.0f} °C: {room:.0f} °C of headroom, plenty for a few laps with less cooling (less drag).",
                {"headroom_c": round(room, 1)})
    for axle, ws, key in (("front", ("fl", "fr"), "duct_front"), ("rear", ("rl", "rr"), "duct_rear")):
        pk = [th.get(f"brake_{w}_peak_c") for w in ws if th.get(f"brake_{w}_peak_c")]
        if pk and max(pk) < 700:
            add(key, -1, f"{axle.capitalize()} brakes peak at {max(pk):.0f} °C over a long run: a few laps with less cooling is safe, and warmer brakes bite from the first corner.",
                {"peak_c": max(pk)}, "medium")
    cs = m.get("countersteer") or {}
    b = m.get("braking") or {}
    if b.get("tc_setting") and (cs.get("exit") or 0) < 0.5 * TG["countersteer_s_lap"]:
        add("traction_control", -1, f"The rear barely steps out on exits ({cs.get('exit') or 0:.2f} s a lap): for one lap you can trade a step of TC for drive.",
            {"exit_countersteer_s_lap": cs.get("exit") or 0, "tc": b["tc_setting"]}, "low")
    return out


# ----------------------------------------------------------------------------------------------- category breakdown
def category_detail(cat: str, m: dict, recs: list[dict], state: dict, history: list[dict]) -> dict:
    """Why a category has its colour: the measurements behind it against their targets, how much data they
    rest on, whether earlier runs agree, and the recommendations it's driving."""
    TG = targets(state.get("prefs"))
    n = m.get("n_flying", 0)
    ev, key_metric = [], None

    def row(label, value, target=None, ok=None, unit="", note=None):
        ev.append({"label": label, "value": value, "target": target, "ok": ok, "unit": unit, "note": note})
    g = lambda *ks: _dig(m, ks)
    if cat == "pit_strategy":
        f = m.get("fuel") or {}
        row("Fuel per lap", f.get("per_lap_l"), None, None, "L", f"from {f.get('laps_measured', 0)} flying laps")
        row("Fuel at the start of the run", f.get("start_l"), None, None, "L")
        key_metric = ("fuel", "per_lap_l")
    elif cat == "gearing":
        gr = m.get("gearing") or {}
        lo, hi = TG["top_gear_rpm"]
        fr = gr.get("top_gear_rpm_frac")
        row("Top gear reaches (share of the rev limit)", fr, f"{lo:.0%}-{hi:.0%}", None if fr is None else lo <= fr <= hi)
        row("On the limiter in top gear", gr.get("limiter_top_s_lap"), "under 0.4 s a lap", None if gr.get("limiter_top_s_lap") is None else gr["limiter_top_s_lap"] < 0.4, "s/lap")
        row("Top speed", gr.get("top_speed_kph"), None, None, "km/h")
        row("Time in top gear", gr.get("top_gear_share"), None, None, "share")
        key_metric = ("gearing", "top_gear_rpm_frac")
    elif cat == "ground_clearance":
        for w in WHEELS:
            p = (m.get("platform") or {}).get(w) or {}
            room = None if p.get("ride_min_cm") is None else p["ride_min_cm"] - TG["ride_min_cm"]
            row(f"{CORNER[w]}: lowest ride height", p.get("ride_min_cm"), f"safe above {TG['ride_min_cm']:.1f} cm", None if room is None else room >= 0, "cm",
                (f"room to go lower: {room:.1f} cm · " if room is not None and room > 0.3 else "") +
                f"bottoming {p.get('ride_near_zero_s') or 0} s/lap, hard travel limit {p.get('at_travel_limit_s') or 0} s/lap, wheel lift {p.get('wheel_lift_s') or 0} s/lap")
        for axle in ("front", "rear"):
            fl_ = (state.get("learned", {}).get(f"ride_floor_{axle}") or {}).get("cm")
            if fl_ is not None:
                row(f"{axle.capitalize()} floor learned (bottomed here)", fl_, None, None, "cm")
        key_metric = ("platform", "fl", "ride_min_cm")
    elif cat == "tyre_contact":
        win = state.get("press_window") or TG["press_bar"]
        lo, hi = TG["camber_delta_c"]
        for w in WHEELS:
            t = (m.get("tyres") or {}).get(w) or {}
            hp, d = t.get("press_hot_bar"), t.get("inner_minus_outer")
            row(f"{CORNER[w]}: hot pressure", hp, f"{win[0]:.2f}-{win[1]:.2f} bar", None if hp is None else win[0] <= hp <= win[1], "bar")
            row(f"{CORNER[w]}: inside minus outside", d, f"{lo:.0f} to {hi:.0f} °C", None if d is None else lo <= d <= hi, "°C",
                None if t.get("centre_minus_edges") is None else f"centre vs shoulders {t['centre_minus_edges']:+.1f} °C")
        key_metric = ("tyres", "fl", "press_hot_bar")
    elif cat in ("chassis_balance", "braking_traction"):
        cs = m.get("countersteer") or {}
        lim = TG["countersteer_s_lap"]
        phases = (("entry", "Rear stepping out under braking"), ("lift", "Rear stepping out on lift")) if cat == "braking_traction" else (("mid", "Rear sliding mid-corner"), ("exit", "Rear sliding on power"))
        for k, label in phases:
            row(label + " (countersteer)", cs.get(k), f"under {lim:.2f} s a lap", None if cs.get(k) is None else cs[k] <= lim, "s/lap")
        if cat == "braking_traction":
            b = m.get("braking") or {}
            lo, hi = TG["abs_share"]
            row("ABS working while braking", b.get("abs_active_share_braking"), f"{lo:.0%}-{hi:.0%}", None if b.get("abs_active_share_braking") is None else lo <= b["abs_active_share_braking"] <= hi, "share")
            for w in WHEELS:
                row(f"{CORNER[w]}: lock-ups (over 20% slip)", b.get(f"lock_{w}_s"), "under 0.3 s a lap", None if b.get(f"lock_{w}_s") is None else b[f"lock_{w}_s"] < 0.3, "s/lap")
            row("Brake bias (front)", b.get("brake_bias_front"), None, None, "share")
            row("TC / ABS settings", f"{b.get('tc_setting')} / {b.get('abs_setting')}")
            key_metric = ("braking", "abs_active_share_braking")
        else:
            cb = m.get("corner_balance") or {}
            row("Corners measured for balance", len(cb), None, None, "", "steering needed per curvature at each apex, compared with your last run")
            key_metric = ("countersteer", "exit")
    elif cat == "aero_balance":
        lo, hi = TG["fast_gradient"]
        fg = m.get("fast_gradient")
        row("Fast-corner understeer gradient", fg, f"{lo:.0%}-{hi:.0%}", None if fg is None else lo <= fg <= hi, "share",
            f"extra steering needed per curvature from light to heavy cornering above 150 km/h ({m.get('fast_gradient_n') or 0} light-load samples)")
        row("Rear sliding in fast corners", (m.get("countersteer") or {}).get("fast"), f"under {TG['countersteer_s_lap']:.2f} s a lap",
            None if (m.get("countersteer") or {}).get("fast") is None else m["countersteer"]["fast"] <= TG["countersteer_s_lap"], "s/lap")
        key_metric = ("fast_gradient",)
    elif cat == "downforce":
        row("Flat out", m.get("full_throttle_share"), None, None, "share", "over 62% flat out suggests testing less drag")
        row("Top speed", g("gearing", "top_speed_kph"), None, None, "km/h")
        row("Less-downforce test done", bool((state.get("tested") or {}).get("downforce_level")))
        key_metric = ("full_throttle_share",)
    elif cat == "thermals":
        th = m.get("thermals") or {}
        row("Water (peak)", th.get("water_c"), f"{TG['water_c'][0]:.0f}-{TG['water_c'][1]:.0f} °C", None if th.get("water_c") is None else TG["water_c"][0] <= th["water_c"] <= TG["water_c"][1], "°C")
        row("Oil (peak)", th.get("oil_c"), f"{TG['oil_c'][0]:.0f}-{TG['oil_c'][1]:.0f} °C", None if th.get("oil_c") is None else TG["oil_c"][0] <= th["oil_c"] <= TG["oil_c"][1], "°C")
        for w in WHEELS:
            axle = "front" if w[0] == "f" else "rear"
            lo, hi = TG[f"brake_{axle}_c"]
            md = th.get(f"brake_{w}_median_c")
            row(f"{CORNER[w]} brake under braking", md, f"{lo:.0f}-{hi:.0f} °C", None if md is None else lo <= md <= hi, "°C", f"peak {th.get(f'brake_{w}_peak_c')} °C")
        key_metric = ("thermals", "water_c")
    # confidence: laps, samples, and whether earlier runs agree
    reasons, level = [], "low"
    reasons.append(f"{n} flying lap{'s' if n != 1 else ''} in this run" + (" (3 or more is solid)" if n >= 3 else " (3 or more would be more solid)"))
    vals = [h.get("value") for h in history if h.get("value") is not None]
    if key_metric:
        cur = _dig(m, key_metric)
        if cur is not None:
            vals = vals + [cur]
    runs_ev = len(vals)
    if runs_ev >= 2:
        a, b = vals[-2], vals[-1]
        spread = abs(b - a) / (abs(a) + 1e-9) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        if spread is not None:
            reasons.append(f"the key figure moved {spread:.0%} from the last run" + (" (consistent)" if spread < 0.1 else " (still settling, or a change took effect)"))
    reasons.append(f"evidence from {runs_ev} run{'s' if runs_ev != 1 else ''}")
    if n >= 3 and runs_ev >= 2:
        level = "high"
    elif n >= 2 or runs_ev >= 2:
        level = "medium"
    if not ev or all(r["value"] is None for r in ev):
        level, reasons = "none", ["No measurements for this category in this run."]
    return {"evidence": ev, "confidence": level, "confidence_reasons": reasons,
            "history": [{"run": h["run"], "value": h.get("value")} for h in history] + ([{"run": "now", "value": _dig(m, key_metric)}] if key_metric else []),
            "key_metric": KEY_LABEL.get(cat),
            "recommendations": [r["id"] for r in recs if r["category"] == cat]}


KEY_LABEL = {"pit_strategy": "fuel per lap", "gearing": "share of the rev limit reached in top gear", "ground_clearance": "front-left lowest ride height",
             "tyre_contact": "front-left hot pressure", "chassis_balance": "rear sliding on exits", "aero_balance": "fast-corner understeer gradient",
             "downforce": "share of the lap flat out", "braking_traction": "ABS working while braking", "thermals": "peak water temperature"}


def _dig(d, ks):
    for k in ks:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def key_metric_value(cat: str, m: dict):
    km = {"pit_strategy": ("fuel", "per_lap_l"), "gearing": ("gearing", "top_gear_rpm_frac"), "ground_clearance": ("platform", "fl", "ride_min_cm"),
          "tyre_contact": ("tyres", "fl", "press_hot_bar"), "chassis_balance": ("countersteer", "exit"), "aero_balance": ("fast_gradient",),
          "downforce": ("full_throttle_share",), "braking_traction": ("braking", "abs_active_share_braking"), "thermals": ("thermals", "water_c")}[cat]
    return _dig(m, km)


# ----------------------------------------------------------------------------------------------- driver feedback
# How the car felt, per corner phase and speed: -2 big understeer .. 0 good .. +2 big oversteer
# (on throttle: -2 pushes on power .. +2 lots of wheelspin; kerbs: -1 harsh, 0 fine, +1 soft / bottoming).
FEEDBACK_PHASES = [("brakes", "On the brakes"), ("turn_in", "Turn-in"), ("mid", "Mid-corner"), ("exit", "Exit")]
FEEDBACK_SPEEDS = [("slow", "Slow corners"), ("medium", "Medium corners"), ("fast", "Fast corners")]


def _fb_rules(phase: str, speed: str, sign: int) -> list[tuple]:
    """(setting, ticks per step, what it does) for one feel. Slow and medium corners: mechanical grip (bars,
    diff, TC). Fast corners: aero. Braking: bias and engine braking."""
    fast = speed == "fast"
    if phase == "brakes":
        return [("brake_bias", -1, "moves braking towards the rear so the fronts stop locking and pushing")] if sign < 0 else \
               [("brake_bias", 1, "moves braking forward so the rear stays planted")] + ([("engine_braking", -1, "less engine braking calms the rear on entry")] if not fast else [])
    if phase in ("turn_in", "mid"):
        if fast:
            return [("downforce_rear", -1, "shifts the aero balance forward for more front grip at speed")] if sign < 0 else \
                   [("downforce_rear", 1, "more rear downforce keeps the rear planted at speed")]
        # one axis: understeer and oversteer votes in slow/medium corners net out before choosing a bar
        return [("_mech_balance", -1, "")] if sign < 0 else [("_mech_balance", 1, "")]
    if phase == "exit":
        if fast:
            return [("downforce_rear", -1, "shifts the aero balance forward for more front grip at speed")] if sign < 0 else \
                   [("downforce_rear", 1, "more rear downforce keeps the rear planted on power at speed")]
        return [("rear_diff_clutches", -1, "less diff lock lets the car rotate on power")] if sign < 0 else [("traction_control", 1, "more TC stops the rear stepping out on power")]
    if phase == "throttle":
        return [("rear_diff_clutches", -1, "less diff lock lets the car rotate on power")] if sign < 0 else [("traction_control", 1, "more TC keeps the wheelspin in check")]
    return []


def _fb_supported(setting: str, ticks: int, m: dict, TG: dict) -> str | None:
    """Telemetry that backs up a feedback change, if any (a sentence), else None."""
    cs, b, fg = m.get("countersteer") or {}, m.get("braking") or {}, m.get("fast_gradient")
    lim = TG["countersteer_s_lap"]
    if setting == "brake_bias":
        fl = (b.get("lock_fl_s") or 0) + (b.get("lock_fr_s") or 0)
        if ticks < 0 and fl > 0.1:
            return f"the fronts lock {fl:.1f} s a lap"
        if ticks > 0 and (cs.get("entry") or 0) > 0.5 * lim:
            return f"{cs['entry']:.1f} s of countersteer a lap under braking"
    if setting == "engine_braking" and (cs.get("lift") or 0) > 0.5 * lim:
        return f"{cs['lift']:.1f} s of countersteer a lap when you lift"
    if setting == "downforce_rear" and fg is not None:
        if ticks < 0 and fg > TG["fast_gradient"][1] - 0.05:
            return f"fast-corner understeer gradient {fg:.0%}"
        if ticks > 0 and (cs.get("fast") or 0) > 0.5 * lim:
            return f"{cs['fast']:.1f} s of countersteer a lap in fast corners"
    if setting in ("arb_rear", "traction_control") and ticks != 0 and (cs.get("mid" if setting == "arb_rear" else "exit") or 0) > 0.5 * lim:
        k = "mid" if setting == "arb_rear" else "exit"
        return f"{cs[k]:.1f} s of countersteer a lap {'mid-corner' if k == 'mid' else 'on exits'}"
    if setting.startswith("fast_bump") and any(((m.get("platform") or {}).get(w) or {}).get("wheel_lift_s") or 0 for w in WHEELS):
        return "wheels leaving the ground over kerbs"
    if setting.startswith("ride_height") and any((((m.get("platform") or {}).get(w) or {}).get("ride_near_zero_s") or 0) > 0 for w in WHEELS):
        return "the car bottoming out"
    return None


def merge_feedback(recs: list[dict], fb: dict | None, m: dict, state: dict) -> list[dict]:
    """Fold how the car felt into the recommendations. Agreement raises confidence; where the data says the
    opposite the data wins (with your feel noted); things only you felt become their own recommendations."""
    if not fb:
        return recs
    TG = targets(state.get("prefs"))
    unavailable, maxed = set(state.get("unavailable", [])), state.get("maxed", {})
    votes = {}   # setting -> [(ticks, reason)]
    for ph, _ in FEEDBACK_PHASES:
        for sp, sl in FEEDBACK_SPEEDS:
            v = (fb.get(ph) or {}).get(sp)
            if not v:
                continue
            feel = {-2: "big understeer", -1: "understeer", 1: "oversteer", 2: "big oversteer"}[int(v)]
            for setting, step, does in _fb_rules(ph, sp, int(np.sign(v))):
                votes.setdefault(setting, []).append((step * abs(int(v)), f"{feel} {dict(FEEDBACK_PHASES)[ph].lower()} in {sl.lower()}", does))
    th = fb.get("throttle")
    if th:
        for setting, step, does in _fb_rules("throttle", "", int(np.sign(th))):
            votes.setdefault(setting, []).append((step * abs(int(th)), {-2: "pushing hard on power", -1: "pushing on power", 1: "some wheelspin", 2: "lots of wheelspin"}[int(th)], does))
    kb = fb.get("kerbs")
    if kb:
        if kb < 0:
            for w in WHEELS:
                votes.setdefault(f"fast_bump_{w}", []).append((-1, "harsh over kerbs", "softer fast bump lets the wheel ride the kerb"))
        else:
            bottoming = any((((m.get("platform") or {}).get(w) or {}).get("ride_near_zero_s") or 0) > 0 for w in WHEELS)
            for w in WHEELS:
                if bottoming:
                    votes.setdefault(f"ride_height_{w}", []).append((1, "soft or bottoming over kerbs", "a little more ride height stops the floor hitting"))
                else:
                    votes.setdefault(f"fast_bump_{w}", []).append((1, "soft and wallowy over kerbs", "firmer fast bump controls the car over kerbs"))
    mb = votes.pop("_mech_balance", None)
    if mb:
        net = sum(t for t, _, _ in mb)
        felt = "; ".join(sorted({f for _, f, _ in mb}))
        if net < 0:
            votes.setdefault("arb_front", []).extend((net if i == 0 else 0, f, "a softer front bar lets the front tyres bite") for i, (t, f, _) in enumerate(mb))
        elif net > 0:
            votes.setdefault("arb_rear", []).extend((-net if i == 0 else 0, f, "a softer rear bar gives the rear more grip") for i, (t, f, _) in enumerate(mb))
        else:
            votes["_mixed_balance"] = [(0, felt, "")]
    out = [dict(r) for r in recs]
    by_setting = {r["setting"]: r for r in out}
    notes = []
    feel_only_used = {}         # feel -> remedy used for it: one remedy per feel unless the data supports another
    base_of = lambda k: k[:-3] if k[-3:] in ("_fl", "_fr", "_rl", "_rr") else k   # all four corners of one setting are one remedy
    for setting, vs in votes.items():
        total = sum(t for t, _, _ in vs)
        felt = "; ".join(sorted({f for _, f, _ in vs}))
        if total == 0:
            what = "the balance in slower corners" if setting == "_mixed_balance" else BY_KEY[setting]["label"].lower()
            notes.append(f"Mixed feel for {what} ({felt}): it balances out, so no change from feel alone.")
            continue
        ticks = int(np.clip(total, -2, 2))
        existing = by_setting.get(setting)
        if existing:
            if np.sign(existing["ticks"]) == np.sign(ticks):
                existing["why"] += f" This matches what you felt ({felt})."
                existing["confidence"] = {"low": "medium", "medium": "high", "high": "high"}[existing["confidence"]]
                existing["feedback"] = "agrees"
            else:
                existing["why"] += f" You felt the opposite ({felt}): the data wins this run; if it still feels that way after this change, say so again."
                existing["feedback"] = "disagrees"
            continue
        if setting in unavailable or not BY_KEY[setting]["analysed"] and not setting.startswith(("fast_bump", "ride_height")):
            continue
        if maxed.get(setting) == ("up" if ticks > 0 else "down"):
            continue
        support = _fb_supported(setting, ticks, m, TG)
        feels = {f for _, f, _ in vs}
        if not support and any(feel_only_used.get(f, base_of(setting)) != base_of(setting) for f in feels):
            continue
        if not support:
            for f in feels:
                feel_only_used.setdefault(f, base_of(setting))
        does = vs[0][2]
        why = f"You felt {felt}: {does}." + (f" The data backs it up: {support}." if support else " The data doesn't show it clearly, so this is your feel's call; the next run will tell.")
        rec = _rec(setting, ticks, why, {"felt": felt, "telemetry": support or "not seen"}, "medium" if support else "low", 2)
        rec["source"] = "feedback"
        out.append(rec)
        by_setting[setting] = rec
    if notes and out:
        out[0] = dict(out[0], feedback_notes=notes)
    elif notes:
        out.append({"id": "feedback_note", "setting": None, "label": "Your feedback", "category": "chassis_balance", "ticks": 0, "action": "No change",
                    "why": " ".join(notes), "evidence": {}, "confidence": "low", "priority": 9, "test": False, "info": True})
    out.sort(key=lambda r: (r["priority"], {"high": 0, "medium": 1, "low": 2}[r["confidence"]]))
    return out
