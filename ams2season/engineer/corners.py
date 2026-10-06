"""Corner-by-corner balance, so two runs can be compared like for like.

Corners are found from the car's own yaw: stretches of lap where the path curvature (yaw rate / speed) is
clearly non-zero. At each corner's apex (the 30 m round its tightest point) the balance figure is the steering
needed per unit of curvature actually achieved. Compared at the SAME corner across runs, the corner's radius,
speed and the driver's line largely cancel, leaving the car's balance: more steering for the same curvature is
more understeer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def find_corners(lap: pd.DataFrame, L: float, min_gap_m: float = 80.0) -> list[dict]:
    d = lap.lap_dist.to_numpy(float)
    v = lap.speed.to_numpy(float)
    kap = np.abs(lap.yaw_rate.to_numpy(float)) / np.maximum(v, 5)
    kap = pd.Series(kap).rolling(9, center=True, min_periods=1).mean().to_numpy()
    on = kap > 0.006
    corners = []
    i = 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and on[j]:
                j += 1
            if d[min(j, len(d) - 1)] - d[i] > 25:
                k = i + int(np.argmax(kap[i:j]))
                if not corners or d[k] - corners[-1]["apex"] > min_gap_m:
                    corners.append({"apex": float(d[k]), "kap": float(kap[k]), "speed_kph": float(v[k] * 3.6),
                                    "dir": "right" if lap.yaw_rate.iat[k] < 0 else "left"})
            i = j
        else:
            i += 1
    for n, c in enumerate(corners):
        c["name"] = f"C{n + 1}"
    return corners


def corner_balance(lap: pd.DataFrame, corners: list[dict], half: float = 15.0) -> dict:
    """name -> {steer_per_curv, steer, curvature, speed_kph, acc_lat} at each corner's apex for one lap."""
    d = lap.lap_dist.to_numpy(float)
    out = {}
    for c in corners:
        m = np.abs(d - c["apex"]) < half
        if m.sum() < 4:
            continue
        g = lap[m]
        v = g.speed.to_numpy(float)
        kap = np.abs(g.yaw_rate.to_numpy(float)) / np.maximum(v, 5)
        st = np.abs(g.steering.to_numpy(float))
        out[c["name"]] = {"steer_per_curv": float(np.median(st) / max(np.median(kap), 1e-4)), "steer": float(np.median(st)),
                          "curvature": float(np.median(kap)), "speed_kph": float(np.median(v) * 3.6),
                          "acc_lat": float(np.median(np.abs(g.acc_lat)))}
    return out


def laps_of(lo: pd.DataFrame, valid_only: bool = True) -> list[pd.DataFrame]:
    out = []
    for n, g in lo.groupby("local_lap"):
        if n == 0 or len(g) < 200:
            continue
        if valid_only and g.local_lap_invalid.any():
            continue
        out.append(g.sort_values("t"))
    return out
