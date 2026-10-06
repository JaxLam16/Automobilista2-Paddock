"""Racing corners: passes through a corner while fighting another car, and how much they should count.

Braking and throttle points move for good reasons in traffic (following someone in, braking on a defensive line,
lapping a backmarker), so consistency scores can count those corners at full weight, at a quarter weight, or
not at all. A corner counts as racing if, at the braking point or the apex, another car was within 1.0 s ahead
or 0.7 s behind on track (on any lap, so lapping and being lapped count too). Cars in the pits don't.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MODES = ("equal", "reduced", "excluded")
WEIGHT = {"equal": 1.0, "reduced": 0.25, "excluded": 0.0}
LABEL = {"equal": "Equal weight", "reduced": "Less weight", "excluded": "Excluded"}
AHEAD_S, BEHIND_S = 1.0, 0.7


def racing_flags(fr: pd.DataFrame, name: str, times, L: float) -> np.ndarray:
    """For each time, was `name` racing another car? `fr` needs t, name, dist (continuous), speed, pit_mode."""
    times = np.asarray(times, float)
    out = np.zeros(len(times), bool)
    if not len(times):
        return out
    by = {n: g.sort_values("t") for n, g in fr.groupby("name")}
    me = by.get(name)
    if me is None or len(me) < 2:
        return out
    tm = me.t.to_numpy(float)
    my_d = np.interp(times, tm, me.dist.to_numpy(float))
    my_v = np.maximum(np.interp(times, tm, me.speed.to_numpy(float)), 10.0)
    for n, g in by.items():
        if n == name or len(g) < 2:
            continue
        to = g.t.to_numpy(float)
        ok = (times >= to[0]) & (times <= to[-1])
        if not ok.any():
            continue
        od = np.interp(times, to, g.dist.to_numpy(float))
        pit = np.interp(times, to, (g.pit_mode.to_numpy(float) > 0).astype(float)) > 0.5 if "pit_mode" in g else np.zeros(len(times), bool)
        gap_m = ((od - my_d) + L / 2) % L - L / 2
        tg = gap_m / my_v
        out |= ok & ~pit & (((tg > 0) & (tg < AHEAD_S)) | ((tg < 0) & (tg > -BEHIND_S)))
    return out


def weights(flags, mode: str, min_n: int = 3) -> np.ndarray:
    """Per-pass weights. Excluding never leaves fewer than `min_n` passes: if it would, everything counts."""
    f = np.asarray(flags, bool)
    w = np.where(f, WEIGHT[mode], 1.0)
    if mode == "excluded" and (w > 0).sum() < min_n:
        w = np.ones(len(f))
    return w


def wstd(values, w) -> float | None:
    v, w = np.asarray(values, float), np.asarray(w, float)
    ok = np.isfinite(v) & (w > 0)
    if ok.sum() < 2:
        return None
    v, w = v[ok], w[ok]
    m = np.average(v, weights=w)
    return float(np.sqrt(np.average((v - m) ** 2, weights=w)))
