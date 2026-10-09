"""Driving technique from the recording car's real pedal inputs, plus tyre care.

For every corner, each lap's brake and throttle traces are lined up by distance to the apex, so laps
can be averaged into one "shape" and compared:

  brake:    where braking starts, how hard the initial hit is, how quickly it builds (attack), how long it
            trails off towards the apex
  throttle: where it's picked up after the apex, how long until it's flat, and any hesitation (lifting
            again on the way out)

Consistency per corner combines shape variation with key-point scatter. Throttle also includes a
modest commitment deduction for actual exit withdrawals, weighted by depth and duration. Brief
gear-change interruptions are filtered for analysis; continuously modulated corners have no invented
pickup point. A withdrawal is not itself proof of a driving mistake or lost time.

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
def _local_lap_usable(local: pd.DataFrame, driver_frames: pd.DataFrame, t0: float, t1: float) -> bool:
    """Pedals must cover this lap continuously and belong to its named driver.

    Participant timing can stay continuous while local telemetry stops or the viewed car changes.
    Neither situation supports interpolating a player-pedal shape. Reject only the affected lap;
    old recordings without slot identity fields remain supported without claiming verification.
    """
    if local is None or not {"t", "speed", "throttle", "brake"} <= set(local.columns):
        return False
    times = local.t.to_numpy(float)
    times = times[np.isfinite(times)]
    if len(times) < 2:
        return False
    segment = local[(local.t >= t0) & (local.t <= t1)]
    if len(segment) < 40 or segment.t.iloc[0] > t0 + 2 or segment.t.iloc[-1] < t1 - 2:
        return False
    if (np.diff(segment.t.to_numpy(float)) <= 0).any():
        return False
    gaps = np.flatnonzero(np.diff(times) > 2.0)
    if ((times[gaps] < t1) & (times[gaps + 1] > t0)).any():
        return False
    if not np.isfinite(segment[["speed", "throttle", "brake"]].to_numpy(float)).all():
        return False
    if "viewed_slot" in segment and "slot" in driver_frames:
        frames = driver_frames.sort_values("t")
        frame_times = frames.t.to_numpy(float)
        slots = frames.slot.to_numpy(float)
        if not len(frames) or not np.isfinite(frame_times).all():
            return False
        # Slots are discrete identities, never linearly interpolate them.
        indexes = np.clip(np.searchsorted(frame_times, segment.t.to_numpy(float), side="right") - 1, 0, len(frames) - 1)
        viewed = segment.viewed_slot.to_numpy(float)
        if not np.isfinite(viewed).all() or not np.isfinite(slots[indexes]).all() or not (viewed == slots[indexes]).all():
            return False
    return True


def recording_laps(sess: Session) -> tuple[str | None, list, float]:
    """The recording car's complete laps, each with its inputs and tyre data against lap distance."""
    from .quali import session_laps
    lo = sess.local
    name = (sess.meta.get("local") or {}).get("name")
    if not name:
        return None, [], sess.L
    if lo is None or not len(lo) or not {"t", "speed", "throttle", "brake"} <= set(lo.columns):
        return name, [], sess.L
    fr = sess.frames[sess.frames.name == name]
    if len(fr) < 50:
        return name, [], sess.L
    L, _ = effective_track_length(sess.frames, sess.L)
    g = add_distance(fr, L, sess.green_t if sess.type == "race" else None)
    if sess.type == "race":
        from .shm import RACESTATE_FINISHED
        finished = fr.loc[fr.race_state == RACESTATE_FINISHED, "t"]
        if len(finished):
            g = g[g.t <= float(finished.iloc[0])]
    laps = session_laps(g, L)
    if sess.type == "race" and len(laps):
        laps = laps[laps.k >= 1]  # standing-start lap is not a repeatable flying-lap reference
    if not len(laps):
        return name, [], L
    gt, gd = g.t.to_numpy(), g.dist.to_numpy()
    lt = lo.t.to_numpy()
    has_tyres = "wear_fl" in lo.columns
    out = []
    for n, lap in enumerate(laps.itertuples(), start=1):
        if not _local_lap_usable(lo, fr, float(lap.t0), float(lap.t1)):
            continue
        m = (lt >= lap.t0) & (lt <= lap.t1)
        if m.sum() < 40:
            continue
        seg = lo[m]
        ld = np.interp(seg.t.to_numpy(), gt, gd) - lap.k * L
        rec = {"n": int(lap.k) + 1 if sess.type == "race" else n, "time": float(lap.time), "valid": bool(lap.valid), "t0": float(lap.t0),
               "ld": ld, "t": seg.t.to_numpy(float), "speed": seg.speed.to_numpy(float) * 3.6,
               "throttle": seg.throttle.to_numpy(float) * 100, "brake": seg.brake.to_numpy(float) * 100,
               "gear": seg.gear.to_numpy(float) if "gear" in seg.columns else None,
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
    nb = max(int(np.ceil(L / 10)), 1)
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


def _runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(int)))
    return list(zip(edges[::2], edges[1::2]))


def _filter_throttle(lap: dict):
    """Return an analysis-only trace; raw pedals are never edited.

    AMS2 briefly reports neutral/intermediate gears and cuts or blips the throttle during a shift.
    Bridge only a short, bounded interruption with similar power on both sides of a recorded gear
    transition. A long lift, an ongoing pedal change or a telemetry gap is not a shift transient.
    Without gear/time data we cannot make that attribution, and retain the interruption.
    """
    raw = np.asarray(lap["throttle"], float)
    filtered = raw.copy()
    shifts = np.zeros(len(raw), bool)
    times, gear = lap.get("t"), lap.get("gear")
    if times is not None and gear is not None and len(times) == len(raw) == len(gear):
        times, gear = np.asarray(times, float), np.asarray(gear, float)
        if len(times) > 2 and np.isfinite(times).all() and (np.diff(times) > 0).all():
            changes = np.flatnonzero(np.isfinite(gear[1:]) & np.isfinite(gear[:-1]) & (gear[1:] != gear[:-1])) + 1
            groups = np.split(changes, np.flatnonzero(np.diff(times[changes]) > 0.18) + 1) if len(changes) else []
            for group in groups:
                first, last = int(group[0]), int(group[-1])
                if times[last] - times[first] > 0.32:
                    continue
                a = int(np.searchsorted(times, times[first] - 0.12, side="right") - 1)
                b = int(np.searchsorted(times, times[last] + 0.14))
                if a < 0 or b >= len(raw) or times[b] - times[a] > 0.62:
                    continue
                if not np.isfinite(raw[a:b + 1]).all() or np.max(np.diff(times[a:b + 1])) > 0.2:
                    continue
                if gear[a] <= 0 or gear[b] <= 0 or gear[a] == gear[b] or abs(raw[b] - raw[a]) > 20:
                    continue
                bridge = np.interp(times[a:b + 1], times[[a, b]], raw[[a, b]])
                departure = np.abs(raw[a:b + 1] - bridge)
                if np.max(departure) < 12:
                    continue
                change = departure > 3
                filtered[a:b + 1][change] = bridge[change]
                shifts[a:b + 1] |= change
    # Remove only small sample jitter; a substantial brief lift remains evidence unless shift-backed.
    median = pd.Series(filtered).rolling(3, center=True, min_periods=1).median().to_numpy()
    tiny = np.isfinite(filtered) & np.isfinite(median) & (np.abs(filtered - median) <= 3)
    filtered[tiny] = median[tiny]
    return filtered, shifts


def _throttle_hesitation(T, times=None):
    """Count separate withdrawals and weight their depth and time, rather than counting samples.

    A few percent of pedal movement carries a small cost. A deep or sustained withdrawal carries
    much more. This is a commitment indicator, not proof that a lift was unnecessary or lost time.
    """
    T = np.asarray(T, float)
    times = np.arange(len(T), dtype=float) * 0.05 if times is None else np.asarray(times, float)
    events, severity = 0, 0.0
    for a, b in _runs(np.isfinite(T) & np.isfinite(times)):
        peak, start, trough = float(T[a]), None, float(T[a])
        for i in range(a + 1, b + 1):
            v = float(T[i]) if i < b else peak
            if start is None:
                if peak - v > 4:
                    start, trough = i, v
                else:
                    peak = max(peak, v)
            elif v >= peak - 3 or i == b:
                depth = peak - trough
                duration = max(0.05, float(times[min(i, b - 1)] - times[start]))
                events += 1
                severity += (depth / 100.0) ** 1.5 * min(duration, 2.0) * 18.0
                peak, start, trough = v, None, v
            else:
                trough = min(trough, v)
    return events, min(28.0, severity)


def _brake_event(xb, B, peak_bounds=None):
    """The sustained main brake application, not a touch or the previous corner's tail."""
    smooth = pd.Series(B).rolling(3, center=True, min_periods=1).median().to_numpy()
    candidates = []
    for a, b in _runs(np.isfinite(B) & np.isfinite(smooth) & (smooth > 3)):
        eligible = np.arange(a, b)
        if peak_bounds is not None:
            eligible = eligible[(xb[eligible] >= peak_bounds[0]) & (xb[eligible] <= peak_bounds[1])]
        if not len(eligible):
            continue
        peak = int(eligible[np.nanargmax(smooth[eligible])])
        height = float(smooth[peak])
        if height < 15 or height < 0.8 * float(np.nanmax(smooth[a:b])) or b - a < 4 or xb[peak] > 20 or a == 0 or not np.isfinite(B[a - 1]):
            continue  # a run already active at the boundary belongs to the previous corner
        threshold = max(5.0, 0.10 * height)
        start = peak
        while start > a and smooth[start - 1] > threshold:
            start -= 1
        end = peak
        while end + 1 < b and smooth[end + 1] > 5:
            end += 1
        candidates.append((float(np.nansum(smooth[a:b])), start, peak, end, a, b))
    return max(candidates, default=None, key=lambda e: e[0])


def _throttle_event(xt, T, start):
    """An exit application that commits to power; isolated maintenance blips do not qualify."""
    smooth = pd.Series(T).rolling(3, center=True, min_periods=1).median().to_numpy()
    candidates = []
    for a, b in _runs(np.isfinite(T) & np.isfinite(smooth) & (smooth > 20)):
        if b - a < 6 or a == 0 or not np.isfinite(T[a - 1]) or xt[b - 1] < start:
            continue
        peak = float(np.nanmax(smooth[a:b]))
        full_runs = [(u + a, v + a) for u, v in _runs(smooth[a:b] > 95) if v - u >= 4]
        if not full_runs and (peak < 60 or (b - a) * STEP < 20):
            continue
        above = np.flatnonzero(smooth[a:b] > 30)
        if not len(above):
            continue
        pickup = a + int(above[0])
        candidates.append((bool(full_runs), pickup, full_runs[0][0] if full_runs else None, a, b))
    return min(candidates, default=None, key=lambda e: e[1])


def _lap_metrics(xb, B, xt, T, speed_x, speed, brake_peak_bounds=None, throttle_times=None):
    event = _brake_event(xb, B, brake_peak_bounds)
    onset = float(xb[event[1]]) if event else None
    m = {"onset": onset}
    if event:
        _, _, pk, release, _, _ = event
        m["peak"] = float(B[pk])
        m["attack"] = float(xb[pk] - onset)
        m["release"] = float(xb[release])
        m["trail"] = m["release"] - float(xb[pk])
    near = (speed_x > -150) & (speed_x < 100) & np.isfinite(speed)
    vmin_i = int(np.nanargmin(np.where(near, speed, np.nan))) if near.any() else None
    m["min_speed"] = float(speed[vmin_i]) if vmin_i is not None else None
    m["min_speed_at"] = float(speed_x[vmin_i]) if vmin_i is not None else None
    start = m["min_speed_at"] if m["min_speed_at"] is not None else -20.0
    throttle = _throttle_event(xt, T, start - 10)
    pickup = float(xt[throttle[1]]) if throttle else None
    m["pickup"] = pickup
    finite = np.isfinite(T)
    powered = T[finite]
    flat = len(powered) >= 6 and np.mean(powered >= 95) >= 0.98 and np.min(powered) >= 90
    low_runs = [r for r in _runs(finite & (T <= 20)) if r[1] - r[0] >= 4]
    maintenance = (len(powered) >= 6 and np.mean(powered > 20) >= 0.65 and
                   m.get("peak", 0) < 40 and (len(low_runs) >= 2 or powered[0] > 20))
    m["throttle_kind"] = "flat_out" if flat else "modulated" if maintenance else "exit" if pickup is not None else "modulated" if len(powered) >= 6 else "unavailable"
    if flat or maintenance:
        m["pickup"] = pickup = None  # an arbitrary modulation trough is not an exit onset
    if pickup is not None:
        full = float(xt[throttle[2]]) if throttle[2] is not None else None
        m["full"] = full
    # Keep assessing commitment beyond the first full-throttle sample, where genuine second lifts
    # used to disappear from the metrics. Modulated corners have no invented pickup marker.
    commitment_start = pickup if pickup is not None else max(0.0, start)
    segment = np.where(xt >= commitment_start, T, np.nan)
    drops, cost = _throttle_hesitation(segment, throttle_times)
    m["hesitations"] = drops
    exit_power = segment[np.isfinite(segment)]
    substantial_lift = len(exit_power) > 0 and np.max(exit_power) >= 85 and np.min(exit_power) <= 20
    weighted_cost = cost * (0.45 if m["throttle_kind"] == "modulated" and not substantial_lift else 1.0)
    m["throttle_hesitation_penalty"] = max(0.6, weighted_cost) if drops else 0.0
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
    if (m.get("hesitations") or 0) >= 1:
        parts.append("some hesitation on the throttle")
    return "Typically " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + "."


def _scores(B, T, rows, w):
    """Brake / throttle consistency for one corner, each lap weighted by w (racing corners count less)."""
    from .traffic import wstd
    W = np.asarray(w, float)[:, None]
    wavg = lambda M: np.nansum(M * W, axis=0) / np.maximum(np.nansum(W * ~np.isnan(M), axis=0), 1e-9)
    # Compare the shape of true exit applications after aligning their pickup. Pickup scatter is
    # assessed separately, so the same timing difference does not receive two full penalties.
    aligned = T.copy()
    marker = [(i, r["pickup"]) for i, r in enumerate(rows) if r.get("pickup") is not None and w[i] > 0]
    if len(marker) >= 2:
        centre = float(np.median([p for _, p in marker]))
        grid = np.arange(T.shape[1], dtype=float)
        for i, pickup in marker:
            offset = np.clip(pickup - centre, -50, 50) / STEP
            aligned[i] = np.interp(grid + offset, grid, T[i], left=np.nan, right=np.nan)
    mb, mt = wavg(B), wavg(aligned)
    zone_b, zone_t = mb > 2, (mt > 2) & (mt < 98)
    def dev(M, m, zone):
        if not zone.any():
            return 0.0
        per = np.array([np.nanmean(np.abs(M[i, zone] - m[zone])) for i in range(len(M))])
        ok = np.isfinite(per) & (np.asarray(w) > 0)
        return float(np.average(per[ok], weights=np.asarray(w)[ok])) if ok.any() else 0.0
    brake_dev, thr_dev = dev(B, mb, zone_b), dev(aligned, mt, zone_t)
    on = [(r["onset"], wi) for r, wi in zip(rows, w) if r["onset"] is not None]
    pk = [(r["pickup"], wi) for r, wi in zip(rows, w) if r.get("pickup") is not None]
    onset_sd = (wstd([a for a, _ in on], [b for _, b in on]) or 0.0) if len(on) >= 2 else 0.0
    pickup_sd = (wstd([a for a, _ in pk], [b for _, b in pk]) or 0.0) if len(pk) >= 2 else 0.0
    braking = sum(r["onset"] is not None for r in rows) >= len(rows) / 2
    brake_score = float(np.clip(100 - 2.5 * brake_dev - 3.0 * onset_sd, 0, 100)) if braking else None
    valid_w = np.asarray(w, float)
    active = valid_w > 0
    modulation = float(np.average([r.get("throttle_kind") in ("modulated", "flat_out") for r in rows], weights=valid_w)) if active.any() else 0.0
    # Bounded scales tolerate ordinary modulation while still separating erratic applications.
    # An isolated, unavailable pickup contributes no timing penalty; it is not a zero-metre onset.
    shape_penalty = 50.0 * thr_dev / (18.0 + thr_dev)
    pickup_penalty = 28.0 * pickup_sd / (18.0 + pickup_sd) * (1.0 - 0.75 * modulation)
    hesitation_penalty = float(np.average([r.get("throttle_hesitation_penalty", 0.0) for r in rows], weights=valid_w)) if active.any() else 0.0
    thr_score = float(np.clip(100 - shape_penalty - pickup_penalty - hesitation_penalty, 0, 100))
    overall = float(np.mean([s for s in (brake_score, thr_score) if s is not None]))
    return ({"overall": round(overall), "brake": None if brake_score is None else round(brake_score), "throttle": round(thr_score)},
            {"onset_sd": round(onset_sd, 1), "pickup_sd": round(pickup_sd, 1), "brake_dev": round(brake_dev, 1), "throttle_dev": round(thr_dev, 1),
             "throttle_shape_penalty": round(shape_penalty, 1), "throttle_pickup_penalty": round(pickup_penalty, 1),
             "throttle_hesitation_penalty": round(hesitation_penalty, 1), "throttle_marker_laps": len(marker),
             "throttle_modulated_laps": int(sum(r.get("throttle_kind") == "modulated" and wi > 0 for r, wi in zip(rows, w))),
             "throttle_flat_out_laps": int(sum(r.get("throttle_kind") == "flat_out" and wi > 0 for r, wi in zip(rows, w)))})


def corner_shapes(laps: list, corners: list, L: float, max_traces: int = 12, racing: dict | None = None,
                  mode: str = "reduced") -> list[dict]:
    """`racing` maps (lap number, corner name) -> True when that pass was made fighting another car."""
    from .traffic import MODES, weights
    xb = np.arange(BRAKE_WIN[0], BRAKE_WIN[1] + STEP, STEP)
    xt = np.arange(THROTTLE_WIN[0], THROTTLE_WIN[1] + STEP, STEP)
    xs = np.arange(-150, 100 + STEP, STEP)
    good = [lp for lp in laps if lp["valid"]] or laps
    best = min(good, key=lambda lp: lp["time"]) if good else None
    filtered = []
    for lp in good:
        trace, shift_mask = _filter_throttle(lp)
        filtered.append({**lp, "throttle_analysis": trace, "shift_transient": shift_mask.astype(float)})
    out = []
    for ci, c in enumerate(corners):
        apex = float(c["apex"])
        before = (apex - corners[ci - 1]["apex"]) % L if len(corners) > 1 else L
        after = (corners[(ci + 1) % len(corners)]["apex"] - apex) % L if len(corners) > 1 else L
        brake_bounds = (BRAKE_WIN[0], min(BRAKE_WIN[1], after / 2))
        brake_peak_bounds = (max(BRAKE_WIN[0], -before / 2), min(20.0, after / 2))
        throttle_bounds = (max(THROTTLE_WIN[0], -before / 2), min(THROTTLE_WIN[1], after / 2))
        rows, Bs, Ts, score_Bs, score_Ts = [], [], [], [], []
        for lp in filtered:
            B, T = _trace(lp, "brake", apex, L, xb), _trace(lp, "throttle", apex, L, xt)
            V = _trace(lp, "speed", apex, L, xs)
            if np.isnan(B).mean() > 0.3 or np.isnan(T).mean() > 0.3:
                continue
            Bb = np.where((xb >= brake_bounds[0]) & (xb <= brake_bounds[1]), B, np.nan)
            filtered_T = _trace(lp, "throttle_analysis", apex, L, xt)
            Tt = np.where((xt >= throttle_bounds[0]) & (xt <= throttle_bounds[1]), filtered_T, np.nan)
            throttle_times = _trace(lp, "t", apex, L, xt) if lp.get("t") is not None else None
            V = np.where((xs >= -before / 2) & (xs <= after / 2), V, np.nan)
            met = _lap_metrics(xb, Bb, xt, Tt, xs, V, brake_peak_bounds, throttle_times)
            shift_trace = _trace(lp, "shift_transient", apex, L, xt) > 0.1
            owned = (xt >= throttle_bounds[0]) & (xt <= throttle_bounds[1])
            met["shift_transients"] = len(_runs(shift_trace & owned))
            met["shift_samples"] = int(np.sum(shift_trace & owned))
            event = _brake_event(xb, Bb, brake_peak_bounds)
            if event:
                Bb = np.where(np.isfinite(Bb), np.where((np.arange(len(Bb)) >= event[4]) & (np.arange(len(Bb)) < event[5]), Bb, 0), np.nan)
            else:
                Bb = np.where(np.isfinite(Bb), 0, np.nan)
            met.update({"lap": lp["n"], "time": lp["time"], "best": lp["n"] == best["n"] if best is not None else False, "racing": bool((racing or {}).get((lp["n"], c["name"])))})
            rows.append(met)
            Bs.append(B)
            Ts.append(T)
            score_Bs.append(Bb)
            score_Ts.append(Tt)
        if len(rows) < 2:
            continue
        B, T = np.vstack(Bs), np.vstack(Ts)
        mb, mt = np.nanmean(B, axis=0), np.nanmean(T, axis=0)
        braking = sum(r["onset"] is not None for r in rows) >= len(rows) / 2
        flags = [r["racing"] for r in rows]
        by_mode = {m: _scores(np.vstack(score_Bs), np.vstack(score_Ts), rows, weights(flags, m)) for m in MODES}
        typical = {k: float(np.median([r[k] for r in rows if r.get(k) is not None])) if any(r.get(k) is not None for r in rows) else None
                   for k in ("onset", "peak", "attack", "trail", "release", "pickup", "full", "min_speed", "hesitations")}
        bi = next((i for i, r in enumerate(rows) if r["best"]), None)
        pick = list(range(len(rows)))[-max_traces:]
        r1 = lambda a: [None if not np.isfinite(v) else round(float(v), 1) for v in a]
        scored_throttle = np.vstack(score_Ts)
        analysis_mean = np.divide(np.nansum(scored_throttle, axis=0), np.isfinite(scored_throttle).sum(axis=0),
                                  out=np.full(len(xt), np.nan), where=np.isfinite(scored_throttle).sum(axis=0) > 0)
        out.append({
            "corner": c["name"], "apex": apex, "braking": braking,
            "analysis_window": {"brake": list(brake_bounds), "brake_peak": list(brake_peak_bounds), "throttle": list(throttle_bounds)},
            "scores": by_mode[mode][0], "scatter": by_mode[mode][1], "racing_laps": int(sum(flags)),
            "excluded_fallback": bool(any(flags) and (len(flags) - sum(flags)) < 3),
            "scores_by_mode": {m: v[0] for m, v in by_mode.items()}, "scatter_by_mode": {m: v[1] for m, v in by_mode.items()},
            "typical": typical, "describe": _describe(typical),
            "brake": {"x": r1(xb), "mean": r1(mb), "p25": r1(np.nanpercentile(B, 25, axis=0)), "p75": r1(np.nanpercentile(B, 75, axis=0)),
                      "laps": [r1(B[i]) for i in pick], "best": r1(B[bi]) if bi is not None else None},
            "throttle": {"x": r1(xt), "mean": r1(mt), "p25": r1(np.nanpercentile(T, 25, axis=0)), "p75": r1(np.nanpercentile(T, 75, axis=0)),
                         "laps": [r1(T[i]) for i in pick], "best": r1(T[bi]) if bi is not None else None,
                         "analysis_mean": r1(analysis_mean),
                         "shift_transients": sum(r["shift_transients"] for r in rows),
                         "shift_samples": sum(r["shift_samples"] for r in rows),
                         "analysis_note": "Short gear-change transients and small sample jitter are filtered for scoring. Maintenance modulation has no pickup marker; substantial exit lifts still count. These plots retain the raw pedal inputs."},
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
    def mean_score(channel):
        values = [c[key].get(channel) for c in shapes if c[key].get(channel) is not None]
        return round(float(np.mean(values))) if values else None
    return {"overall": round(float(np.mean([sc(c) for c in shapes]))), "brake": mean_score("brake"), "throttle": mean_score("throttle"),
            "most_consistent": best["corner"], "most_consistent_score": sc(best),
            "least_consistent": worst["corner"], "least_consistent_score": sc(worst)}


def throttle_consistency_summary(report: dict) -> dict:
    """Actual player-pedal rating by traffic mode, for race/profile consumers.

    Missing pedal analysis stays unavailable; callers should not invent a player rating from the
    speed-based marker proxy used for cars whose pedal inputs were not recorded.
    """
    from .traffic import MODES
    if not report.get("available"):
        return {mode: None for mode in MODES}
    return {mode: report.get("summary_by_mode", {}).get(mode, {}).get("throttle") for mode in MODES}


def technique_report(path_or_session, corners_override=None, mode: str = "reduced") -> dict:
    sess = path_or_session if isinstance(path_or_session, Session) else load_session(path_or_session)
    name, laps, L = recording_laps(sess)
    if not name or not laps:
        return {"driver": name, "available": False, "reason": "No complete supported lap has continuous pedal inputs safely attributable to this driver."}
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
            tips.append(f"{worst['corner']}: throttle pickup varies by ±{worst['scatter']['pickup_sd']:.0f} m. Aim for a repeatable exit application where grip permits.")
        hes = [c for c in shapes if (c["typical"].get("hesitations") or 0) >= 1 and
               c["scatter"].get("throttle_modulated_laps", 0) < len(c["laps"]) / 2]
        if hes:
            tips.append("Power withdrawals on the exit of " + ", ".join(c["corner"] for c in hes[:3]) + ": check line and traction before trying a smoother application.")
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
