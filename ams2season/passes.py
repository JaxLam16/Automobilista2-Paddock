"""On-track passes and battles.

All entrants are resampled onto one time grid. For each pair, the sign of their race-distance
difference gives the running order. A pass is a change between two *stable* orders (each held
for `hold_s`), so side-by-side flicker collapses into at most one pass. Order changes across a
stretch where either car was in the pit lane / not racing are recorded as `pit_cycle`, not passes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import shm as S
from .derive import OFF_TRACK_PIT, corner_for

PASS_COLUMNS = ["t", "lap", "lap_dist", "corner", "passer", "passed", "kind", "lap1"]


@dataclass
class PassParams:
    hold_s: float = 3.0          # new order must hold this long to count
    max_gap_s: float = 1.0       # tolerated invalid time between stable orders
    grid_dt: float = 0.1         # resample resolution
    gift_speed_ratio: float = 0.5  # passed car below this fraction of field speed => gifted
    gift_window: tuple = (-4.0, 1.0)
    contact_window_s: float = 3.0
    battle_gap_s: float = 1.0
    battle_min_laps: float = 2.0
    battle_merge_s: float = 3.0


@dataclass
class Grid:
    T: np.ndarray
    names: list
    D: np.ndarray       # race distance
    POS: np.ndarray
    OK: np.ndarray      # racing, not in pit lane, data present
    PIT: np.ndarray
    SPD: np.ndarray
    INV: np.ndarray


def build_grid(frames: pd.DataFrame, green_t: float, dt: float) -> Grid:
    end = float(frames.t.max())
    T = np.arange(green_t, end, dt)
    names = sorted(frames.name.unique())
    n, m = len(names), len(T)
    D = np.full((n, m), np.nan)
    POS = np.zeros((n, m), dtype=np.int16)
    PIT = np.zeros((n, m), dtype=np.int8)
    RS = np.zeros((n, m), dtype=np.int8)
    SPD = np.full((n, m), np.nan)
    INV = np.zeros((n, m), dtype=bool)
    groups = frames.groupby("name").indices
    for i, name in enumerate(names):
        g = frames.iloc[groups[name]]
        t = g.t.to_numpy()
        j = np.clip(np.searchsorted(t, T), 1, len(t) - 1) if len(t) > 1 else np.zeros(m, int)
        nearest = np.where(np.abs(t[j - 1] - T) < np.abs(t[j] - T), j - 1, j) if len(t) > 1 else j
        present = np.abs(t[nearest] - T) <= 0.5
        D[i] = np.where(present, np.interp(T, t, g.dist.to_numpy()), np.nan)
        POS[i] = g.race_pos.to_numpy()[nearest]
        PIT[i] = g.pit_mode.to_numpy()[nearest]
        RS[i] = g.race_state.to_numpy()[nearest]
        SPD[i] = np.where(present, g.speed.to_numpy()[nearest], np.nan)
        INV[i] = g.lap_invalid.to_numpy()[nearest]
    OK = (RS == S.RACESTATE_RACING) & ~np.isin(PIT, OFF_TRACK_PIT) & ~np.isnan(D)
    return Grid(T, names, D, POS, OK, PIT, SPD, INV)


def _runs(x: np.ndarray):
    if len(x) == 0:
        return np.array([]), np.array([], int), np.array([], int)
    ch = np.flatnonzero(np.diff(x)) + 1
    starts = np.r_[0, ch]
    ends = np.r_[ch, len(x)]
    return x[starts], starts, ends


def detect_passes(grid: Grid, L: float, corners: list[dict], profile: np.ndarray,
                  bin_m: float = 10.0, contacts: list[tuple] | None = None,
                  p: PassParams | None = None) -> pd.DataFrame:
    p = p or PassParams()
    T, D, OK = grid.T, grid.D, grid.OK
    n = len(grid.names)
    hold = int(round(p.hold_s / p.grid_dt))
    mass = _mass_invalidations(grid, p)
    rows = []
    for i in range(n):
        for j in range(i + 1, n):
            diff = D[i] - D[j]
            with np.errstate(invalid="ignore"):
                valid = OK[i] & OK[j] & (np.abs(diff) < 0.5 * L)
            state = np.where(valid, np.sign(np.nan_to_num(diff)), 0).astype(np.int8)
            vals, starts, ends = _runs(state)
            stable = [(v, s, e) for v, s, e in zip(vals, starts, ends) if v != 0 and e - s >= hold]
            for (v1, s1, e1), (v2, s2, e2) in zip(stable, stable[1:]):
                if v1 == v2:
                    continue
                between = state[e1:s2]
                passer, passed = (i, j) if v2 > 0 else (j, i)
                k = s2
                if (between == 0).sum() * p.grid_dt > p.max_gap_s:
                    kind = "pit_cycle"
                else:
                    kc = min(k + hold, len(T) - 1)
                    pa, pb = grid.POS[passer, kc], grid.POS[passed, kc]
                    if pa > 0 and pb > 0 and pa > pb:
                        kind = "unconfirmed"  # distance says pass, game order disagrees
                    else:
                        kind = _classify(grid, passer, passed, k, L, profile, bin_m, contacts, p, mass)
                dpass = D[passer, k] if not np.isnan(D[passer, k]) else D[passer, max(k - 1, 0)]
                lap_dist = float(dpass % L)
                rows.append({
                    "t": float(T[k]), "lap": int(np.floor(dpass / L)) + 1, "lap_dist": round(lap_dist, 1),
                    "corner": corner_for(lap_dist, corners), "passer": grid.names[passer],
                    "passed": grid.names[passed], "kind": kind, "lap1": bool(dpass < L),
                })
    df = pd.DataFrame(rows, columns=PASS_COLUMNS)
    return df.sort_values("t", kind="stable").reset_index(drop=True)


def _mass_invalidations(grid: Grid, p: PassParams) -> np.ndarray:
    """Moments when a big part of the field has its lap invalidated together (a game rule at the start,
    a restart...): those aren't anyone going off, so they mustn't make a pass "gifted"."""
    inv = np.nan_to_num(grid.INV.astype(float))
    flips = np.zeros_like(inv)
    flips[:, 1:] = np.diff(inv, axis=1) > 0
    w = max(1, int(2.0 / p.grid_dt))
    counts = np.convolve(flips.sum(axis=0), np.ones(2 * w + 1), "same")
    active = np.maximum(grid.OK.sum(axis=0), 1)
    return counts >= np.maximum(3, 0.4 * active)


def _classify(grid: Grid, passer: int, passed: int, k: int, L: float, profile: np.ndarray,
              bin_m: float, contacts, p: PassParams, mass: np.ndarray | None = None) -> str:
    t = grid.T[k]
    a, b = grid.names[passer], grid.names[passed]
    if contacts:
        for ct, x, y in contacts:
            if abs(ct - t) <= p.contact_window_s and {x, y} == {a, b}:
                return "contact"
    lo = max(int(k + p.gift_window[0] / p.grid_dt), 0)
    hi = min(int(k + p.gift_window[1] / p.grid_dt), len(grid.T) - 1)
    # Gifted = the passed car was far slower than the cars around it (the passer included): a spin, an
    # off, a car crawling. Comparing with neighbours, not with the usual speed at that spot, means a whole
    # pack slowing for turn 1 on lap 1 doesn't make every pass look gifted.
    for kk in range(lo, hi + 1):
        v = grid.SPD[passed, kk]
        d0 = grid.D[passed, kk]
        if np.isnan(v) or np.isnan(d0):
            continue
        near = grid.OK[:, kk] & (np.abs(grid.D[:, kk] - d0) < 150)
        near[passed] = False
        sp = grid.SPD[near, kk]
        sp = sp[~np.isnan(sp)]
        ref = float(np.median(sp)) if len(sp) else np.nan
        if not len(sp) and not np.isnan(profile).all():  # nobody around: fall back to the usual speed here
            ref = float(profile[min(int((d0 % L) / bin_m), len(profile) - 1)])
        if ref == ref and ref > 8 and v < p.gift_speed_ratio * ref:
            return "gifted"
    inv = grid.INV[passed, lo:hi + 1]
    if len(inv) > 1:
        flip = np.flatnonzero(np.diff(inv.astype(int)) > 0) + lo + 1
        if any(mass is None or not mass[f] for f in flip):
            return "gifted"  # passed car's lap got invalidated right there (off / cut), on its own
    return "clean"


def detect_battles(grid: Grid, L: float, p: PassParams | None = None) -> pd.DataFrame:
    """Pairs running within `battle_gap_s` of each other for at least `battle_min_laps`."""
    p = p or PassParams()
    D, OK, SPD, T = grid.D, grid.OK, grid.SPD, grid.T
    n = len(grid.names)
    merge = int(p.battle_merge_s / p.grid_dt)
    # running-order rank at each instant (only racing cars); a battle needs adjacent cars,
    # otherwise every pair inside a nose-to-tail train would count
    keyed = np.where(OK, D, -np.inf)
    rank = np.empty_like(keyed, dtype=np.int32)
    rank[np.argsort(-keyed, axis=0, kind="stable"), np.arange(keyed.shape[1])] = np.arange(n)[:, None]
    rows = []
    for i in range(n):
        for j in range(i + 1, n):
            diff = D[i] - D[j]
            with np.errstate(invalid="ignore"):
                follower_spd = np.where(diff >= 0, SPD[j], SPD[i])
                interval = np.abs(diff) / np.maximum(np.nan_to_num(follower_spd, nan=5.0), 5.0)
                close = (OK[i] & OK[j] & (np.abs(diff) < 0.5 * L) & (interval <= p.battle_gap_s)
                         & (np.abs(rank[i] - rank[j]) == 1))
            vals, starts, ends = _runs(close.astype(np.int8))
            segs = [[s, e] for v, s, e in zip(vals, starts, ends) if v == 1]
            merged = []
            for s, e in segs:
                if merged and s - merged[-1][1] <= merge:
                    merged[-1][1] = e
                else:
                    merged.append([s, e])
            for s, e in merged:
                e1 = e - 1
                covered = np.nanmax(D[[i, j], e1]) - np.nanmin(D[[i, j], s])
                if covered < p.battle_min_laps * L:
                    continue
                ahead_start = i if D[i, s] >= D[j, s] else j
                ahead_end = i if D[i, e1] >= D[j, e1] else j
                st = np.sign(np.nan_to_num(diff[s:e])).astype(np.int8)
                sv, ss, se = _runs(st[st != 0])
                held = [v for v, a, b in zip(sv, ss, se) if b - a >= int(p.hold_s / p.grid_dt)]
                swaps = sum(1 for (a, b) in zip(held, held[1:]) if a != b)
                rows.append({
                    "a": grid.names[ahead_start], "b": grid.names[i if ahead_start == j else j],
                    "start_t": float(T[s]), "end_t": float(T[e1]),
                    "start_lap": max(int(np.floor(np.nanmax(D[[i, j], s]) / L)) + 1, 1),
                    "end_lap": int(np.floor(np.nanmax(D[[i, j], e1]) / L)) + 1,
                    "laps": round(covered / L, 1), "duration_s": round(float(T[e1] - T[s]), 1),
                    "min_gap_s": round(float(np.nanmin(interval[s:e])), 2),
                    "avg_gap_s": round(float(np.nanmean(np.abs(interval[s:e]))), 2), "swaps": swaps,
                    "winner": grid.names[ahead_end],
                })
    cols = ["a", "b", "start_t", "end_t", "start_lap", "end_lap", "laps", "duration_s", "min_gap_s", "avg_gap_s", "swaps", "winner"]
    return pd.DataFrame(rows, columns=cols)
