"""Track edges for the replay maps.

The game never shares track edges, so they come from two places:

1. Mapped edges (best). For the car on the recording PC the game reports the surface under each
   wheel. Every time a wheel crosses between asphalt and anything else (kerb, grass, gravel, run-off),
   the edge is exactly under that wheel. A "mapping lap" along each edge, saved as a track file,
   gives precise edges; normal laps add more wherever a wheel touches a kerb.

2. Modelled edges (fallback). Average every lap that looks normal into one clean racing line. Then use
   what racing lines do: at the slowest point of a corner (the apex) the car is at the inside edge,
   and at turn-in and exit it is out at the outside edge. Smooth curves through those anchor points
   give a road that bends with the track, at a typical width, widened anywhere the normal laps need.

Mapped edges are used wherever they exist; the model fills the rest, blended smoothly.
"""
from __future__ import annotations

import json
import math
import warnings
import re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import shm as S

BIN_M = 5.0
HALF_CAR = 1.0       # positions are the centre of the car
HALF_TRACK = 0.85    # wheel centre to car centre, sideways
DEFAULT_WIDTH = 12.0
MIN_WIDTH = 7.0

# surfaces that count as "the track" (asphalt and the like); kerbs, grass, gravel, run-off do not,
# so a transition marks the edge of the racing surface (the white line / start of the kerb)
ON_TRACK = {0, 1, 2, 3, 4, 5, 11, 21, 29, 35, 36, 37, 50}  # road, low grip, bumpy 1-3, marbles, drains,
#                                                          pavement, cobbles, damaged, train track, bumpy cobbles, rally tarmac.
# Painted concrete is left out on purpose: it's mostly painted run-off and track-limit strips beyond the lines.
PIT = [S.PIT_MODE_DRIVING_INTO_PITS, S.PIT_MODE_IN_PIT, S.PIT_MODE_DRIVING_OUT_OF_PITS,
       S.PIT_MODE_IN_GARAGE, S.PIT_MODE_DRIVING_OUT_OF_GARAGE]


# --------------------------------------------------------------------------- reference line
def _reference(ref_ld, ref_x, ref_z, L: float):
    ref_ld, ref_x, ref_z = (np.asarray(a, float) for a in (ref_ld, ref_x, ref_z))
    o = np.argsort(ref_ld)
    ld, x, z = ref_ld[o], ref_x[o], ref_z[o]
    keep = np.r_[True, np.diff(ld) > 0.05]
    ld, x, z = ld[keep], x[keep], z[keep]
    dx, dz = np.gradient(x, ld), np.gradient(z, ld)
    n = np.hypot(dx, dz) + 1e-9
    return ld, x, z, -dz / n, dx / n  # unit normal to the left of travel (+offset side)


class Ref:
    def __init__(self, ref_ld, ref_x, ref_z, L: float):
        self.L = L
        self.ld, self.x, self.z, self.nx, self.nz = _reference(ref_ld, ref_x, ref_z, L)
        self.nb = max(int(L / BIN_M), 10)
        self.c = (np.arange(self.nb) + 0.5) * BIN_M

    def at(self, ld):
        L = self.L
        return (np.interp(ld, self.ld, self.x, period=L), np.interp(ld, self.ld, self.z, period=L),
                np.interp(ld, self.ld, self.nx, period=L), np.interp(ld, self.ld, self.nz, period=L))

    def offset(self, ld, x, z):
        rx, rz, nx, nz = self.at(ld)
        return (np.asarray(x, float) - rx) * nx + (np.asarray(z, float) - rz) * nz

    def point(self, off):
        rx, rz, nx, nz = self.at(self.c)
        return np.c_[rx + off * nx, rz + off * nz]

    def bins(self, ld):
        return np.clip((np.asarray(ld, float) / BIN_M).astype(int), 0, self.nb - 1)


def _circ_smooth(a: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return a
    pad = np.r_[a[-k:], a, a[:k]]
    return np.convolve(pad, np.ones(k) / k, "same")[k:-k]


def _circ_fill(a: np.ndarray, max_gap: int | None = None) -> np.ndarray:
    """Fill NaNs by circular interpolation; gaps longer than max_gap bins stay NaN."""
    a = a.copy()
    ok = ~np.isnan(a)
    if ok.sum() < 2:
        return a
    idx = np.arange(len(a))
    filled = np.interp(idx, idx[ok], a[ok], period=len(a))
    if max_gap is None:
        return filled
    # measure gap lengths (circular)
    gap = np.zeros(len(a), int)
    run = 0
    for i in list(range(len(a))) * 2:
        run = 0 if ok[i] else run + 1
        gap[i] = run
    for i in reversed(list(range(len(a))) * 2):
        if not ok[i]:
            gap[i] = max(gap[i], gap[(i + 1) % len(a)])
    out = np.where(ok | (gap <= max_gap), filled, np.nan)
    return out


# --------------------------------------------------------------------------- 1. edges from wheel surfaces
def edge_samples(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Edge points from the recording car's wheel surfaces.

    df needs: t, x, z, lap_dist, speed, steering, terrain_fl/fr/rl/rr. Heading comes from the direction
    of travel. Which side of the car is "left" in world coordinates is found from the data itself:
    steering left must turn the car towards its left."""
    need = {"t", "x", "z", "lap_dist", "speed", "steering", "terrain_fl", "terrain_fr", "terrain_rl", "terrain_rr"}
    empty = pd.DataFrame(columns=["lap_dist", "x", "z", "side"])
    if not need <= set(df.columns) or len(df) < 40:
        return empty, {"reason": "no wheel-surface data"}
    d = df[(df.speed > 4) & df.x.notna() & (df.terrain_fl >= 0)].sort_values("t")
    if len(d) < 40:
        return empty, {"reason": "not enough driving"}
    x = pd.Series(d.x.to_numpy(float)).rolling(5, center=True, min_periods=1).mean().to_numpy()
    z = pd.Series(d.z.to_numpy(float)).rolling(5, center=True, min_periods=1).mean().to_numpy()
    th = np.unwrap(np.arctan2(np.gradient(z), np.gradient(x)))
    step = np.hypot(np.gradient(x), np.gradient(z))
    kappa = np.gradient(th) / np.maximum(step, 1e-3)
    kappa = pd.Series(kappa).rolling(31, center=True, min_periods=5).mean().to_numpy()  # ignore small weaves
    steer = pd.Series(d.steering.to_numpy(float)).rolling(31, center=True, min_periods=5).mean().to_numpy()
    m = (np.abs(steer) > 0.05) & (np.abs(kappa) > 1 / 400) & (step > 0.2)
    if m.sum() < 20:
        return empty, {"reason": "not enough cornering to calibrate"}
    agree = float(np.mean(np.sign(kappa[m]) == np.sign(-steer[m])))  # steering left (negative) turns left
    left_sign = 1.0 if agree >= 0.5 else -1.0
    calib = {"left_sign": left_sign, "confidence": round(abs(agree - 0.5) * 2, 3)}
    nx, nz = -np.sin(th) * left_sign, np.cos(th) * left_sign  # unit vector to the car's left
    tx, tz = np.cos(th), np.sin(th)
    ld = d.lap_dist.to_numpy(float)
    rows = []
    for col, side, along in (("terrain_fl", "left", 1.3), ("terrain_fr", "right", 1.3),
                             ("terrain_rl", "left", -1.3), ("terrain_rr", "right", -1.3)):
        on = np.isin(d[col].to_numpy(), list(ON_TRACK))
        flips = np.flatnonzero(on[1:] != on[:-1])  # crossing between i and i+1
        lat = HALF_TRACK if side == "left" else -HALF_TRACK
        for i in flips:
            j = i + 1
            if abs(ld[j] - ld[i]) > 30:  # crossing the start/finish line: skip
                continue
            wx = (x[i] + x[j]) / 2 + lat * (nx[i] + nx[j]) / 2 + along * (tx[i] + tx[j]) / 2
            wz = (z[i] + z[j]) / 2 + lat * (nz[i] + nz[j]) / 2 + along * (tz[i] + tz[j]) / 2
            rows.append((float((ld[i] + ld[j]) / 2 + along), float(wx), float(wz), side))
    out = pd.DataFrame(rows, columns=["lap_dist", "x", "z", "side"])
    return out, calib


def _roll_nanmedian(a: np.ndarray, w: int) -> np.ndarray:
    """Circular rolling median that ignores NaN (w bins either side)."""
    n = len(a)
    idx = (np.arange(n)[:, None] + np.arange(-w, w + 1)[None, :]) % n
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN windows are expected (unmapped stretches)
        return np.nanmedian(a[idx], axis=1)


def _smooth_covered(a: np.ndarray, k: int = 5, passes: int = 3) -> np.ndarray:
    """Repeated circular moving average over the covered parts only (NaN stays NaN)."""
    have = ~np.isnan(a)
    out = np.where(have, a, 0.0)
    for _ in range(passes):
        num = _circ_smooth(np.where(have, out, 0.0), k)
        den = _circ_smooth(have.astype(float), k)
        out = np.where(have, num / np.maximum(den, 1e-9), 0.0)
    return np.where(have, out, np.nan)


def _circ_grad(a: np.ndarray) -> np.ndarray:
    return (np.r_[a[1:], a[:1]] - np.r_[a[-1:], a[:-1]]) / 2


def _edge_curve(s: pd.DataFrame, ref: Ref, outward: float, reach: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """One edge as its own curve in world coordinates, one point per 5 m of lap (NaN where unmapped).

    Built in the edge's own frame, not as offsets from the racing line: in a tight corner a point on the edge
    isn't square across from the racing line at its lap distance, and the racing line itself swings from one
    edge to the other, so measured from it the edges spike and smear at exactly the tightest corners.

    1. A first curve through the per-section median points (robust to scattered strays).
    2. Each point's distance from that curve, outward positive. False edges from a surface change inside the
       road (paint, patches) come as dense clusters on the inside; lone strays outside are scattered. So each
       section takes the outermost residual with real support around it (neighbours within 0.6 m over ~25 m).
    3. Sections that disagree with the surrounding ~45 m are dropped, short gaps (up to 70 m) bridged, and the
       residuals smoothed lightly, so apexes stay sharp."""
    nb = ref.nb
    X = np.full(nb, np.nan)
    Z = np.full(nb, np.nan)
    if not len(s):
        return X, Z
    ld = s.lap_dist.to_numpy(float) % ref.L
    b = ref.bins(ld)
    x, z = s.x.to_numpy(float), s.z.to_numpy(float)
    ro_all = ref.offset(ld, x, z)
    keep = np.abs(ro_all) < 25  # drop garage / pit-building strays far from the circuit
    if reach is not None:
        # An edge can't lie inside the road the cars actually drove: a left-edge point well right of the
        # leftmost line any normal lap took (or the reverse) is impossible. 1.5 m allows for kerb-riding.
        keep &= (outward * (ro_all - reach[b]) > -1.0)
    b, x, z = b[keep], x[keep], z[keep]
    if len(b) < 10:
        return X, Z
    # First curve: per section, the cluster with the most support across neighbouring sections (a median of
    # everything would land halfway between the real edge and a cluster of strays on the far side)
    ro = ref.offset(ref.c[b] if hasattr(ref, "c") else (b + 0.5) * BIN_M, x, z)
    by = {k: np.flatnonzero(b == k) for k in np.unique(b)}
    for i, idx in by.items():
        pool = np.concatenate([ro[by[(i + d) % nb]] for d in range(-2, 3) if (i + d) % nb in by])
        support = [np.count_nonzero(np.abs(pool - ro[j]) <= 1.0) for j in idx]
        r0 = ro[idx[int(np.argmax(support))]]
        mine = idx[np.abs(ro[idx] - r0) <= 1.0]
        X[i], Z[i] = float(np.median(x[mine])), float(np.median(z[mine]))
    X0, Z0 = _circ_fill(X.copy(), max_gap=3), _circ_fill(Z.copy(), max_gap=3)
    X0, Z0 = _smooth_covered(X0, 3, 1), _smooth_covered(Z0, 3, 1)  # light: a sharp apex must survive
    tx, tz = _circ_grad(np.nan_to_num(X0)), _circ_grad(np.nan_to_num(Z0))
    tl = np.maximum(np.hypot(tx, tz), 1e-6)
    nx, nz = -tz / tl * outward, tx / tl * outward          # outward normal of the first curve
    ok = ~np.isnan(X0[b])
    b, x, z = b[ok], x[ok], z[ok]
    res = (x - X0[b]) * nx[b] + (z - Z0[b]) * nz[b]        # outward distance from the first curve
    keep = np.abs(res) < 8
    b, res = b[keep], res[keep]
    first = np.full(nb, np.nan)
    by_bin = {k: np.sort(res[b == k])[::-1] for k in np.unique(b)}
    for i in by_bin:
        v = np.concatenate([by_bin.get((i + d) % nb, np.empty(0)) for d in range(-2, 3)])
        need = max(2, int(np.ceil(0.15 * len(v)))) if len(v) >= 3 else 1
        for r in by_bin[i]:
            if np.count_nonzero(np.abs(v - r) <= 0.6) >= need:      # support counted over ~25 m...
                own = by_bin[i][np.abs(by_bin[i] - r) <= 0.6]       # ...position from this section's own points
                first[i] = float(np.median(own))
                break
    local = _roll_nanmedian(first, 4)  # in the edge's own frame this only needs to catch gross outliers
    r_arr = np.where(np.abs(first - local) <= 2.5, first, np.nan)
    r_arr = _circ_fill(r_arr, max_gap=3)
    r_arr = _smooth_covered(r_arr, 3, 2)
    covered = ~np.isnan(r_arr) & ~np.isnan(X0)
    X = np.where(covered, X0 + r_arr * nx, np.nan)
    Z = np.where(covered, Z0 + r_arr * nz, np.nan)
    return X, Z


def _offsets_from_curve(X: np.ndarray, Z: np.ndarray, ref: Ref) -> np.ndarray:
    """Where each section's square-across line (from the racing line) meets the edge curve, as an offset.
    An exact intersection, so drawing the edge from these offsets reproduces the curve, tight corners too.
    The curve joins each mapped section to the next one up to 30 m away (sparse stretches still count);
    a section with no mapped neighbour that close is placed directly."""
    nb = ref.nb
    c = (np.arange(nb) + 0.5) * BIN_M
    rx, rz, nx, nz = ref.at(c)
    valid = np.flatnonzero(~np.isnan(X))
    out = np.full(nb, np.nan)
    if not len(valid):
        return out
    segs = []  # (start bin, end bin) between consecutive mapped sections, wrapping round the lap
    for a, b in zip(valid, np.r_[valid[1:], valid[:1]]):
        if 0 < (b - a) % nb <= 6:
            segs.append((a, b))
    joined = {a for a, _ in segs} | {b for _, b in segs}
    by_start = {}
    for a, b in segs:
        by_start.setdefault(a, []).append(b)
    for i in range(nb):
        best = None
        for k in range(-8, 8):
            a = (i + k) % nb
            for b in by_start.get(a, ()):
                qx, qz, dx, dz = X[a], Z[a], X[b] - X[a], Z[b] - Z[a]
                den = nx[i] * dz - nz[i] * dx                     # solve r + t*n = q + u*d
                if abs(den) < 1e-9:
                    continue
                t = ((qx - rx[i]) * dz - (qz - rz[i]) * dx) / den
                u = ((qx - rx[i]) * nz[i] - (qz - rz[i]) * nx[i]) / den
                if -1e-6 <= u <= 1 + 1e-6 and abs(t) < 30 and (best is None or abs(k) < best[0]):
                    best = (abs(k), t)
        if best is not None:
            out[i] = best[1]
    for i in valid:  # a lone mapped section: place it where it is
        if i not in joined and np.isnan(out[i]):
            out[i] = float((X[i] - rx[i]) * nx[i] + (Z[i] - rz[i]) * nz[i])
    return out


def edges_from_samples(samples: pd.DataFrame, ref: Ref, reach: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Per-bin left/right edge offsets from edge points (NaN where a side wasn't mapped). `reach` is where
    normal laps' outermost wheels went on each side, used to reject impossible edge points.

    Two passes: the second drops any point that would pinch the road below 70% of its typical width against
    the other edge from the first pass (strays near the racing line). Gaps are then bridged along the track's
    shape, never with a straight chord across a curve."""
    def build(sm):
        res = []
        for side, outward in (("left", 1.0), ("right", -1.0)):
            X, Z = _edge_curve(sm[sm.side == side], ref, outward, None if reach is None else reach[side])
            res.append(_offsets_from_curve(X, Z, ref))
        return res
    e_l, e_r = build(samples)
    both = ~np.isnan(e_l) & ~np.isnan(e_r)
    if both.sum() > 20:
        typical = float(np.median(e_l[both] - e_r[both]))
        ld = samples.lap_dist.to_numpy(float) % ref.L
        b = ref.bins(ld)
        ro = ref.offset(ld, samples.x, samples.z)
        is_left = (samples.side == "left").to_numpy()
        other = np.where(is_left, e_r[b], e_l[b])
        gap = np.where(is_left, ro - other, other - ro)
        pinch = ~np.isnan(other) & (gap < 0.7 * typical)
        if pinch.any():
            e_l, e_r = build(samples[~pinch])
    return _circ_fill(e_l, max_gap=14), _circ_fill(e_r, max_gap=14)


# --------------------------------------------------------------------------- 2. the racing-line model
def modeled_edges(frames: pd.DataFrame, normal: set | None, ref: Ref, width: float | None = None) -> tuple[np.ndarray, np.ndarray, dict]:
    """Edges inferred from normal laps (see the module docstring).

    1. Keep laps that look normal: valid, and never straying far from the typical line (spins, offs
       and odd lines are dropped). Their median is the average racing line; their 5th/95th percentile
       per 5 m section is the envelope of where normal laps go.
    2. Corners are the slow points of the average line that really bend. At each apex the inside edge
       sits under the inside wheels of the tightest normal laps; at turn-in and exit the outside edge
       sits under the outside wheels of the widest ones.
    3. The road's centre is eased smoothly (cosine curves) between those anchors, and the width comes
       from how much road the normal laps use in total. Edges never cut through a normal lap."""
    L, nb = ref.L, ref.nb
    f = frames[(frames.speed > 5) & ~frames.pit_mode.isin(PIT) & (frames.lap_dist > 0) & (frames.lap_dist < L)]
    if "dist" in f.columns:
        lapidx = np.floor(f.dist.to_numpy() / L).astype(int)
    else:
        lapidx = f.laps_completed.to_numpy().astype(int)
    key = pd.Series(list(zip(f.name, lapidx)), index=f.index)
    if normal:
        sel = key.isin(normal).to_numpy()
        f, key = f[sel], key[sel]
    W0 = width or DEFAULT_WIDTH
    if len(f) < 200:
        return np.zeros(nb) + W0 / 2, np.zeros(nb) - W0 / 2, {"laps": 0}
    off = ref.offset(f.lap_dist.to_numpy(float), f.x, f.z)
    b = ref.bins(f.lap_dist)
    prof = pd.DataFrame({"k": key.astype(str).to_numpy(), "b": b, "off": off}).groupby(["k", "b"]).off.median().unstack()
    P = prof.reindex(columns=range(nb)).to_numpy(float)
    P = P[(~np.isnan(P)).mean(axis=1) > 0.7]
    if not len(P):
        return np.zeros(nb) + W0 / 2, np.zeros(nb) - W0 / 2, {"laps": 0}
    med = np.nanmedian(P, axis=0)
    dev = np.nanmax(np.abs(P - med), axis=1)  # how far each lap strays from the typical line
    keep = dev < max(3.5, float(np.nanpercentile(dev, 60)) * 1.5)
    good = P[keep] if keep.sum() >= 2 else P
    line = _circ_smooth(_circ_fill(np.nanmedian(good, axis=0)), 5)
    lo = _circ_smooth(_circ_fill(np.nanpercentile(good, 5, axis=0)), 5)
    hi = _circ_smooth(_circ_fill(np.nanpercentile(good, 95, axis=0)), 5)
    W = float(width or DEFAULT_WIDTH)  # racing lines alone can't reveal the road's width: a typical value, adjustable per track
    inside_edge = lambda i, s_in: (hi[i] + HALF_TRACK) if s_in > 0 else (lo[i] - HALF_TRACK)

    spd = pd.Series(f.speed.to_numpy(float) * 3.6).groupby(b).median().reindex(range(nb)).to_numpy()
    spd = _circ_smooth(_circ_fill(spd), 3)
    pts = ref.point(line)
    th = np.unwrap(np.arctan2(np.gradient(pts[:, 1]), np.gradient(pts[:, 0])))
    kappa = _circ_smooth(np.gradient(th) / BIN_M, 7)
    w = max(1, int(80 / BIN_M))
    apexes = []
    for i in range(nb):
        win = np.take(spd, range(i - w, i + w + 1), mode="wrap")
        if spd[i] > win.min() + 1e-6:
            continue
        far = np.take(spd, range(i - 3 * w, i + 3 * w + 1), mode="wrap")
        k_here = np.take(kappa, range(i - 5, i + 6), mode="wrap").mean()
        if far.max() - spd[i] >= 8 and abs(k_here) > 1 / 600:
            if not apexes or (i - apexes[-1][0]) * BIN_M > 60:
                apexes.append((i, 1.0 if k_here > 0 else -1.0, abs(k_here)))
    cons = []  # (bin, road-centre offset, kind)
    anchors = []  # (bin, which edge, where normal laps reach it, kind): the out-in-out check uses these
    for i, s_in, kap in apexes:
        cons.append((i, inside_edge(i, s_in) - s_in * W / 2, "apex"))
        anchors.append((i, "left" if s_in > 0 else "right", inside_edge(i, s_in), "apex"))
        for direction in (-1, 1):
            j, steps = i, 0
            while steps < int(250 / BIN_M):
                j2 = (j + direction) % nb
                if abs(kappa[j2]) < 0.3 * kap and steps * BIN_M >= 40:
                    break
                j, steps = j2, steps + 1
            outside = inside_edge(j, -s_in)  # the outside edge, from the widest normal laps
            cons.append((j, outside + s_in * W / 2, "entry" if direction < 0 else "exit"))
            anchors.append((j, "right" if s_in > 0 else "left", outside, "entry" if direction < 0 else "exit"))
    cons.sort()
    pruned = []  # chicanes: keep the apexes, drop entry/exit anchors that crowd them
    for c in cons:
        if pruned and ((c[0] - pruned[-1][0]) % nb) * BIN_M < 30:
            if pruned[-1][2] == "apex" and c[2] != "apex":
                continue
            if c[2] == "apex" and pruned[-1][2] != "apex":
                pruned[-1] = c
                continue
            pruned[-1] = (pruned[-1][0], (pruned[-1][1] + c[1]) / 2, pruned[-1][2])
            continue
        pruned.append(c)
    if len(pruned) >= 2:
        centre = np.zeros(nb)
        for (ia, va, _), (ib, vb, _) in zip(pruned, pruned[1:] + [(pruned[0][0] + nb, pruned[0][1], "")]):
            span = ib - ia
            for t in range(span + 1):
                u = t / max(span, 1)
                centre[(ia + t) % nb] = va + (vb - va) * (1 - math.cos(math.pi * u)) / 2
    else:
        centre = _circ_smooth((lo + hi) / 2, 9)
    left, right = centre + W / 2, centre - W / 2
    left = np.maximum(left, _circ_smooth(hi + HALF_TRACK, 5))  # never cut through a normal lap
    right = np.minimum(right, _circ_smooth(lo - HALF_TRACK, 5))
    return left, right, {"laps": int(len(good)), "laps_dropped": int(len(P) - len(good)), "corners": len(apexes),
                         "width": round(W, 1), "anchors": anchors,
                         "reach": {"left": hi + HALF_TRACK, "right": lo - HALF_TRACK}}  # where normal laps' wheels go


# --------------------------------------------------------------------------- combine
def _fit_length(samples: pd.DataFrame | None, L: float) -> pd.DataFrame | None:
    """A track file mapped with a slightly different lap length (game build, or measured vs reported)
    would put edge points near the start/finish line at the wrong end of the lap: rescale to this lap."""
    if samples is None or not len(samples):
        return samples
    fl = samples.attrs.get("length")
    if fl and abs(fl / L - 1) > 0.002:
        samples = samples.assign(lap_dist=samples.lap_dist.to_numpy(float) * (L / fl))
    return samples


def track_geometry(frames: pd.DataFrame, ref_ld, ref_x, ref_z, L: float, normal: set | None = None,
                   samples: pd.DataFrame | None = None, cloud_points: int = 15000, width: float | None = None,
                   extra_samples: pd.DataFrame | None = None) -> dict:
    """`samples` are mapping-lap edge points (a track file); `extra_samples` come from ordinary laps (races,
    qualifying) and only fill stretches the mapping didn't cover, since racing laps cut corners and run wide."""
    if len(np.asarray(ref_ld)) < 20:
        return {}
    ref = Ref(ref_ld, ref_x, ref_z, L)
    samples, extra_samples = _fit_length(samples, L), _fit_length(extra_samples, L)
    e_left = e_right = None
    if (samples is None or not len(samples)) and extra_samples is not None and len(extra_samples):
        samples, extra_samples = extra_samples, None
    m_left, m_right, info = modeled_edges(frames, normal, ref, width)
    if samples is not None and len(samples):
        reach = info.get("reach")
        e_left, e_right = edges_from_samples(samples, ref, reach)
        if extra_samples is not None and len(extra_samples):
            x_left, x_right = edges_from_samples(extra_samples, ref, reach)
            e_left = np.where(np.isnan(e_left), x_left, e_left)
            e_right = np.where(np.isnan(e_right), x_right, e_right)
        both = ~np.isnan(e_left) & ~np.isnan(e_right)
        if width is None and both.mean() > 0.1:  # mapped sections tell us how wide this road really is
            width = float(np.clip(np.median(e_left[both] - e_right[both]), 7.0, 20.0))
            m_left, m_right, info = modeled_edges(frames, normal, ref, width)
    left, right = m_left.copy(), m_right.copy()
    cov = {"left": 0.0, "right": 0.0}
    if e_left is not None:
        for name, e, base in (("left", e_left, left), ("right", e_right, right)):
            have = ~np.isnan(e)
            cov[name] = round(float(have.mean()) * 100, 1)
            if have.all() or not have.any():
                if have.any():
                    base[:] = e
                continue
            # unmapped stretches: the model, shifted so it joins the mapped edge exactly at both ends
            fixed = e.copy()
            nb = len(e)
            edges = np.flatnonzero(np.diff(np.r_[have[-1], have].astype(int)) == -1)  # first missing bin of each run
            for st in edges:
                j = st
                while not have[j % nb]:
                    j += 1
                before, after = (st - 1) % nb, j % nb
                d0, d1 = e[before] - base[before], e[after] - base[after]
                span = j - st + 1
                for t in range(st, j):
                    u = (t - st + 1) / span
                    fixed[t % nb] = base[t % nb] + d0 + (d1 - d0) * u
            base[:] = _smooth_covered(fixed, 3, 2)
    if info.get("reach"):
        left, right = _widen_pinches(left, right, info["reach"])
    narrow = (left - right) < MIN_WIDTH
    mid = (left + right) / 2
    left[narrow], right[narrow] = mid[narrow] + MIN_WIDTH / 2, mid[narrow] - MIN_WIDTH / 2
    L_pts, R_pts = ref.point(left), ref.point(right)
    f = frames[(frames.speed > 5)]
    pick = np.random.default_rng(2).choice(len(f), size=min(cloud_points, len(f)), replace=False) if len(f) else []
    cloud = [[int(round(x * 10)), int(round(z * 10))] for x, z in zip(f.x.to_numpy(float)[pick], f.z.to_numpy(float)[pick])]
    mapped = max(cov.values())
    source = ("mapped" if min(cov.values()) >= 90 else "mixed" if mapped > 0 else "model")
    return {
        "left": [[round(float(x), 2), round(float(z), 2)] for x, z in L_pts],
        "right": [[round(float(x), 2), round(float(z), 2)] for x, z in R_pts],
        "cloud": cloud, "samples": int(len(f)),
        "width": {"median": round(float(np.median(left - right)), 1), "min": round(float(np.min(left - right)), 1),
                  "max": round(float(np.max(left - right)), 1)},
        "edges": {"source": source, "mapped_pct": cov, "model": {k: v for k, v in info.items() if k not in ("anchors", "reach")}},
        "offsets": {"left": [round(float(v), 3) for v in left], "right": [round(float(v), 3) for v in right]},
    }


def _widen_pinches(left: np.ndarray, right: np.ndarray, reach: dict, floor: float = 0.75, target: float = 0.9):
    """A backstop for a pinch (under 75% of the track's typical width) left by stray edge points.

    An edge the cars actually run along (within 2 m of their outermost wheels there) is pinned: it's
    confirmed by the cars and never moves. Only a free edge widens, and only that edge is smoothed. At an
    apex the inside edge is always pinned, so a real apex can't be undone."""
    width = left - right
    typical = float(np.median(width))
    narrow = width < floor * typical
    if not narrow.any():
        return left, right
    gap_l = left - reach["left"]     # left edge beyond the leftmost wheels
    gap_r = reach["right"] - right   # right edge beyond the rightmost wheels
    pin_l, pin_r = gap_l < 2.0, gap_r < 2.0
    need = np.where(narrow, target * typical - width, 0.0)
    move_l = narrow & ~pin_l & (pin_r | (gap_l >= gap_r))
    move_r = narrow & ~pin_r & ~move_l
    for arr, move, sign in ((left, move_l, 1.0), (right, move_r, -1.0)):
        if not move.any():
            continue
        target_arr = arr + sign * np.where(move, need, 0.0)
        zone = _circ_smooth(move.astype(float), 9) > 0           # blend just the moved edge into its surroundings
        blended = _smooth_covered(target_arr.copy(), 5, 2)
        arr[:] = np.where(zone, np.where(move, target_arr, blended), arr)
    return left, right


# --------------------------------------------------------------------------- track files
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "track"


def track_file_path(root: Path, track: str, layout: str) -> Path:
    d = Path(root) / "tracks"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_slug(track)}__{_slug(layout)}.json"


def load_track_file(root: Path, track: str, layout: str) -> dict:
    p = track_file_path(root, track, layout)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_track_width(root: Path, track: str, layout: str, width: float | None) -> dict:
    data = load_track_file(root, track, layout) or {"track": track, "layout": layout, "samples": {"left": [], "right": []}}
    if width:
        data["width"] = float(np.clip(width, 6.0, 25.0))
    else:
        data.pop("width", None)
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    track_file_path(root, track, layout).write_text(json.dumps(data), encoding="utf-8")
    return data


def load_track_samples(root: Path, track: str, layout: str) -> pd.DataFrame | None:
    data = load_track_file(root, track, layout)
    if not data:
        return None
    rows = [(ld, x, z, side) for side in ("left", "right") for ld, x, z in data.get("samples", {}).get(side, [])]
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["lap_dist", "x", "z", "side"])
    df.attrs["length"] = data.get("length")
    return df


def save_track_samples(root: Path, track: str, layout: str, L: float, new: pd.DataFrame, cap_per_bin: int = 24) -> dict:
    """Merge new edge points into the track file (keeping the most recent few per 5 m section)."""
    p = track_file_path(root, track, layout)
    old = load_track_samples(root, track, layout)
    allp = pd.concat([d for d in (old, new) if d is not None and len(d)], ignore_index=True) if (old is not None or len(new)) else new
    allp = allp.assign(b=(allp.lap_dist % L // BIN_M).astype(int)).groupby(["side", "b"]).tail(cap_per_bin)
    cov = coverage(allp, L)
    prev = load_track_file(root, track, layout)
    data = {"track": track, "layout": layout, "length": L, "updated": datetime.now().isoformat(timespec="seconds"),
            "coverage": cov, **({"width": prev["width"]} if prev.get("width") else {}),
            "samples": {side: [[round(r.lap_dist, 1), round(r.x, 2), round(r.z, 2)] for r in allp[allp.side == side].itertuples()]
                        for side in ("left", "right")}}
    p.write_text(json.dumps(data), encoding="utf-8")
    return {"path": str(p), "coverage": cov}


def coverage(samples: pd.DataFrame, L: float) -> dict:
    """Share of each edge that is mapped, counting short gaps (up to 30 m) between edge points as covered."""
    nb = max(int(L / BIN_M), 1)
    out = {}
    for side in ("left", "right"):
        a = np.full(nb, np.nan)
        s = samples[samples.side == side] if samples is not None and len(samples) else []
        if len(s):
            a[np.unique((s.lap_dist.to_numpy(float) % L // BIN_M).astype(int).clip(0, nb - 1))] = 1.0
            a = _circ_fill(a, max_gap=6)
        out[side] = round(float((~np.isnan(a)).mean()) * 100, 1)
    return out


def list_track_files(root: Path) -> list[dict]:
    d = Path(root) / "tracks"
    out = []
    if d.exists():
        for p in sorted(d.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                out.append({"key": p.stem, "track": data.get("track"), "layout": data.get("layout"),
                            "coverage": data.get("coverage") or {"left": 0, "right": 0}, "width": data.get("width"),
                            "updated": data.get("updated")})
            except Exception:
                continue
    return out


# --------------------------------------------------------------------------- live mapping
class LiveMapper:
    """Collects the recording car's position and wheel surfaces from live snapshots (any session type)
    while the driver does mapping laps, and reports coverage as it goes."""

    def __init__(self):
        self.rows, self.track, self.layout, self.L = [], None, None, None
        self.started = time.time()
        self._cache = (0, None, None)

    def feed(self, snap, now: float) -> None:
        if snap.mGameState not in (S.GAME_INGAME_PLAYING, S.GAME_INGAME_INMENU_TIME_TICKING) or snap.mTrackLength <= 0:
            return
        i = snap.mViewedParticipantIndex
        if not (0 <= i < S.STORED_PARTICIPANTS_MAX) or not snap.mParticipantInfo[i].mIsActive:
            return
        track, layout = S.cstr(snap.mTrackLocation), S.cstr(snap.mTrackVariation)
        if (track, layout) != (self.track, self.layout):  # a different track: start over
            self.rows, self.track, self.layout, self.L = [], track, layout, float(snap.mTrackLength)
        p = snap.mParticipantInfo[i]
        self.rows.append((now, p.mWorldPosition[0], p.mWorldPosition[2], p.mCurrentLapDistance, snap.mSpeed,
                          snap.mSteering, *(int(snap.mTerrain[w]) for w in range(4))))
        if len(self.rows) > 120_000:
            self.rows = self.rows[-120_000:]

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=["t", "x", "z", "lap_dist", "speed", "steering",
                                                "terrain_fl", "terrain_fr", "terrain_rl", "terrain_rr"])

    def samples(self):
        if self._cache[0] != len(self.rows):
            s, calib = edge_samples(self.frame())
            self._cache = (len(self.rows), s, calib)
        return self._cache[1], self._cache[2]

    def status(self) -> dict:
        if not self.rows:
            return {"track": None, "ticks": 0}
        df = self.frame()
        s, calib = self.samples()
        cov = coverage(s, self.L or 1)
        last = df.iloc[-1]
        on = lambda c: int(last[c]) in ON_TRACK
        touching = ("left" if not (on("terrain_fl") and on("terrain_rl")) else "") + (" right" if not (on("terrain_fr") and on("terrain_rr")) else "")
        step = max(1, len(df) // 1500)
        pstep = max(1, len(s) // 3000) if len(s) else 1
        dist = float(np.nansum(np.hypot(np.diff(df.x), np.diff(df.z))))
        return {"track": self.track, "layout": self.layout, "length": self.L, "ticks": len(df),
                "laps_driven": round(dist / self.L, 2) if self.L else 0, "coverage": cov, "calibration": calib,
                "touching": touching.strip(), "speed_kph": round(float(last.speed) * 3.6),
                "car": [float(last.x), float(last.z)],
                "path": [[round(float(x), 1), round(float(z), 1)] for x, z in zip(df.x[::step], df.z[::step])],
                "points": {side: [[round(r.x, 1), round(r.z, 1)] for r in s[s.side == side].iloc[::pstep].itertuples()]
                           for side in ("left", "right")} if len(s) else {"left": [], "right": []}}


def recording_edge_samples(sess) -> pd.DataFrame:
    """Edge points from a recording's own wheel-surface data (the recording car), if it has any."""
    lo = getattr(sess, "local", None)
    if lo is None or not len(lo) or "terrain_fl" not in lo.columns:
        return pd.DataFrame(columns=["lap_dist", "x", "z", "side"])
    s, _ = edge_samples(lo)
    return s



def save_track_corners(root: Path, track: str, layout: str, corners: list | None) -> dict:
    """Your own turn positions for a track ([{name, apex}] in metres of lap; None = back to automatic)."""
    data = load_track_file(root, track, layout) or {"track": track, "layout": layout, "samples": {"left": [], "right": []}}
    if corners:
        data["corners"] = [{"name": str(c.get("name") or f"T{i + 1}").strip()[:12], "apex": round(float(c["apex"]), 1)}
                           for i, c in enumerate(sorted(corners, key=lambda c: float(c["apex"])))]
    else:
        data.pop("corners", None)
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    track_file_path(root, track, layout).write_text(json.dumps(data), encoding="utf-8")
    return data


def track_outline(samples: pd.DataFrame, L: float) -> dict:
    """Centre line (with lap distance) and both edges from a track file's points alone, for the turn editor."""
    nb = max(int(L / BIN_M), 10)
    sides = {}
    for side in ("left", "right"):
        sp = samples[samples.side == side]
        b = ((sp.lap_dist.to_numpy(float) % L) / BIN_M).astype(int) % nb
        X, Z = np.full(nb, np.nan), np.full(nb, np.nan)
        if len(sp):
            mx, mz = pd.Series(sp.x.to_numpy()).groupby(b).median(), pd.Series(sp.z.to_numpy()).groupby(b).median()
            X[mx.index.to_numpy()], Z[mz.index.to_numpy()] = mx.to_numpy(), mz.to_numpy()
            # drop sections that jump far from their neighbours (garage / pit-building strays near the line)
            rx, rz = _roll_nanmedian(X, 4), _roll_nanmedian(Z, 4)
            bad = np.hypot(X - rx, Z - rz) > 12
            X[bad], Z[bad] = np.nan, np.nan
        X, Z = _circ_fill(X), _circ_fill(Z)
        sides[side] = (_smooth_covered(X, 5, 2), _smooth_covered(Z, 5, 2))
    cx = (sides["left"][0] + sides["right"][0]) / 2
    cz = (sides["left"][1] + sides["right"][1]) / 2
    ld = (np.arange(nb) + 0.5) * BIN_M
    ok = ~np.isnan(cx)
    r = lambda a: [round(float(v), 2) for v in a]
    return {"centre": [[round(float(d), 1), round(float(x), 2), round(float(z), 2)] for d, x, z in zip(ld[ok], cx[ok], cz[ok])],
            "left": [list(p) for p in zip(r(sides["left"][0][ok]), r(sides["left"][1][ok]))],
            "right": [list(p) for p in zip(r(sides["right"][0][ok]), r(sides["right"][1][ok]))]}
