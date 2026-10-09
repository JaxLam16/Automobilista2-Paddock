"""Turn a recorded session folder into laps, classification, pit stops and corners.

Everything here is a pure function of the raw frames, so new stats can be backfilled over
every race already recorded.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import shm as S

RACING, FINISHED = S.RACESTATE_RACING, S.RACESTATE_FINISHED
PIT_LANE = [S.PIT_MODE_DRIVING_INTO_PITS, S.PIT_MODE_IN_PIT, S.PIT_MODE_DRIVING_OUT_OF_PITS]
OFF_TRACK_PIT = PIT_LANE + [S.PIT_MODE_IN_GARAGE, S.PIT_MODE_DRIVING_OUT_OF_GARAGE]  # -1 (unknown) counts as on track
DNF_STATES = {S.RACESTATE_RETIRED, S.RACESTATE_DNF}


# --------------------------------------------------------------------------- loading
@dataclass
class Session:
    path: Path
    meta: dict
    frames: pd.DataFrame
    local: pd.DataFrame
    events: list[dict] = field(default_factory=list)

    @property
    def L(self) -> float:
        return float(self.meta["track_length"])

    @property
    def type(self) -> str:
        return self.meta.get("session_type", "unknown")

    @property
    def green_t(self) -> float | None:
        if self.meta.get("green_t") is not None:
            return float(self.meta["green_t"])
        for ev in self.events:
            if ev.get("type") == "green":
                return float(ev["t"])
        racing = self.frames.loc[self.frames.race_state == RACING, "t"]
        return float(racing.min()) if len(racing) else None

    @property
    def end_t(self) -> float:
        return float(self.frames.t.max())

    def event_grid(self) -> dict | None:
        for ev in self.events:
            if ev.get("type") == "green" and not ev.get("late"):
                return ev.get("grid")
        return None


def _read(path: Path, kind: str) -> pd.DataFrame:
    f = path / f"{kind}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    dfs = []  # recorder crashed mid-session: read the chunks (and any raw-JSON fallbacks)
    for p in sorted((path / f"{kind}_parts").glob("part-*.*")):
        try:
            if p.suffix == ".parquet":
                dfs.append(pd.read_parquet(p))
            elif p.suffix == ".json":
                dfs.append(pd.DataFrame(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def load_session(path: str | Path) -> Session:
    path = Path(path)
    meta = json.loads((path / "session.json").read_text(encoding="utf-8"))
    frames = _read(path, "frames")
    if len(frames):
        frames["name"] = frames["name"].astype(object)
        frames = frames.sort_values(["name", "t"], kind="stable").reset_index(drop=True)
    local = _read(path, "local")
    events = []
    ev_path = path / "events.jsonl"
    if ev_path.exists():
        events = [json.loads(line) for line in ev_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return Session(path=path, meta=meta, frames=frames, local=local, events=events)


# --------------------------------------------------------------------------- distance
def _mode(values: np.ndarray, default: int) -> int:
    if len(values) == 0:
        return default
    vals, counts = np.unique(values, return_counts=True)
    return int(vals[np.argmax(counts)])


def effective_track_length(frames: pd.DataFrame, reported: float) -> tuple[float, str | None]:
    """The lap length the data actually uses. If the game's reported track length disagrees with the
    lap distances seen on track by more than 3%, trust the data (a wrong length breaks every lap)."""
    ld = frames.loc[(frames.race_state == RACING) & (frames.lap_dist > 0), "lap_dist"].to_numpy(float)
    if len(ld) < 200:
        return reported, None
    observed = float(np.percentile(ld, 99.8))
    if reported > 0 and abs(observed / reported - 1) <= 0.03:
        return reported, None
    if observed < 300:
        return reported, None
    return observed, (f"track length reported as {reported:.0f} m but lap distances reach {observed:.0f} m; "
                      f"using {observed:.0f} m")


def _despike(t: np.ndarray, d: np.ndarray, tol: float = 80.0) -> np.ndarray:
    """Remove one-off jumps (lap distance flickering to 0 for a frame, network hiccups) by comparing
    each sample with a rolling median and interpolating over the outliers."""
    if len(d) < 7:
        return d
    med = pd.Series(d).rolling(7, center=True, min_periods=3).median().to_numpy()
    bad = np.abs(d - med) > tol
    if not bad.any() or bad.all():
        return d
    good = ~bad
    return np.interp(t, t[good], d[good])


def _fix_lap_dist(ld: np.ndarray, L: float, tol: float = 60.0) -> np.ndarray:
    """Repair 1-2 frame flickers in raw lap distance (e.g. a remote car reporting 0 for a frame).
    A run of samples that disagrees with both neighbours, while the neighbours agree with each other,
    is replaced by interpolation, done circularly so it also works right at the start/finish line."""
    ld = ld.astype(float).copy()
    n = len(ld)

    # Exactly 0.000 m is the "unknown" value a remote car reports during a hiccup; a moving car never
    # sits on exactly zero. Fill every such run (bursts included) from the samples either side.
    zero = ld == 0.0
    if zero.any() and not zero.all():
        edges = np.flatnonzero(np.diff(np.r_[0, zero.astype(int), 0]))
        for s0, s1 in zip(edges[::2], edges[1::2]):  # zero run is ld[s0:s1]
            if s0 == 0 or s1 == n:
                ld[s0:s1] = ld[s1] if s0 == 0 else ld[s0 - 1]
                continue
            a, b = ld[s0 - 1], ld[s1]
            if b - a < -L / 2:
                b += L
            elif b - a > L / 2:
                b -= L
            k = np.arange(1, s1 - s0 + 1) / (s1 - s0 + 1)
            ld[s0:s1] = (a + (b - a) * k) % L

    def cd(a, b):
        x = np.abs(a - b) % L
        return np.minimum(x, L - x)

    for span in (1, 2):
        if n < span + 2:
            break
        prev, nxt = ld[:n - span - 1], ld[span + 1:]
        bad = cd(prev, nxt) < tol * (span + 1)
        mids = [ld[1 + k:n - span + k] for k in range(span)]
        for m in mids:
            bad &= (cd(m, prev) > tol) & (cd(m, nxt) > tol)
        for i in np.flatnonzero(bad):
            a, b = ld[i], ld[i + span + 1]
            if b - a < -L / 2:
                b += L
            elif b - a > L / 2:
                b -= L
            for k in range(span):
                ld[i + 1 + k] = (a + (b - a) * (k + 1) / (span + 1)) % L
    return ld


def add_distance(frames: pd.DataFrame, L: float, green_t: float | None = None, gap_s: float = 2.0) -> pd.DataFrame:
    """Add `dist`: continuous race distance in metres (negative = behind the S/F line at the start).

    Lap distance is unwrapped into a running total. Each car is anchored at the green flag (everyone is
    within half a lap of the line on the grid), so behind-the-line grid slots are negative regardless
    of how the game counts that first crossing. Cars first seen mid-race are anchored with
    laps_completed; later segments (after a data gap) continue from where the car left off.
    Single-frame spikes are filtered out so they can't fake a line crossing.
    """
    dist = np.empty(len(frames))
    T_all, LD_all = frames.t.to_numpy(), frames.lap_dist.to_numpy(float)
    LC_all, V_all = frames.laps_completed.to_numpy(float), frames.speed.to_numpy(float)
    for _, idx in frames.groupby("name", sort=False).indices.items():
        t, ld, lc, v = T_all[idx], LD_all[idx], LC_all[idx], V_all[idx]
        out = np.empty(len(t))
        breaks = np.flatnonzero(np.diff(t) > gap_s) + 1
        prev_end = None
        for n_seg, (a, b) in enumerate(zip(np.r_[0, breaks], np.r_[breaks, len(t)])):
            seg = _fix_lap_dist(ld[a:b], L)
            # A line crossing goes from the end of the lap to the start (or back, reversing). Requiring
            # both ends of the jump to be near the line stops a mid-lap flicker to 0 being read as one.
            fwd = (seg[:-1] > 0.75 * L) & (seg[1:] < 0.25 * L)
            rev = (seg[:-1] < 0.25 * L) & (seg[1:] > 0.75 * L)
            wraps = np.r_[0, np.cumsum(fwd.astype(int) - rev.astype(int))]
            raw = wraps * L + seg  # continuous within the segment, unknown whole-lap offset
            if n_seg == 0 and green_t is not None and t[a] <= green_t + 5:
                ia = int(np.argmin(np.abs(t[a:b] - green_t)))
                base = -raw[ia] + (seg[ia] if seg[ia] <= L / 2 else seg[ia] - L)
                base = round(base / L) * L
            elif prev_end is not None:
                t_prev, d_prev, v_prev = prev_end
                predicted = d_prev + max(v_prev, 0.0) * (t[a] - t_prev)
                base = round((predicted - raw[0]) / L) * L
            else:
                ok = (lc[a:b] >= 0) & (seg > 0.1 * L) & (seg < 0.9 * L)
                k = _mode((lc[a:b] - wraps)[ok].astype(int), default=int(max(lc[a], 0)))
                base = k * L
            d = _despike(t[a:b], raw + base)
            if n_seg == 0 and green_t is not None and t[a] <= green_t + 5 and ld[a] == 0:
                # AMS2 reports exactly zero for grid cars until they reach the line. Filling
                # that prefix with their first positive reading put every grid slot *ahead*
                # of the line, in an arbitrary order. Work backwards from the first real
                # reading using travelled distance, retaining the negative grid distances.
                known = np.flatnonzero(ld[a:b] != 0)
                if len(known) and t[a + known[0]] <= green_t + 30:
                    first = int(known[0])
                    travel = np.r_[0.0, np.cumsum(np.maximum(0.0, (v[a:a + first] + v[a + 1:a + first + 1]) / 2)
                                                 * np.diff(t[a:a + first + 1]))]
                    d[:first] = d[first] - (travel[-1] - travel[:first])
            out[a:b] = d
            prev_end = (t[b - 1], d[-1], v[b - 1])
        dist[idx] = out
    res = frames.copy()
    res["dist"] = dist
    return res


# --------------------------------------------------------------------------- laps
def _last_valid(t: np.ndarray, v: np.ndarray, lo: float, hi: float) -> float:
    m = (t > lo) & (t <= hi) & (v > 0)
    return float(v[m][-1]) if m.any() else np.nan


def completed_lap_time(t: np.ndarray, last_lap: np.ndarray, t1: float, own: float) -> tuple[float, bool]:
    """Read the completed lap *after* its crossing, when the game's timing has updated.

    The previous lap is often close enough to pass the tolerance check. Taking the first
    value in a window starting before the crossing silently assigned it to the new lap.
    Keep the latest plausible updated value; interpolated crossing time is the fallback.
    """
    win = (t >= t1) & (t <= t1 + 5.0) & np.isfinite(last_lap) & (last_lap > 0) \
        & (np.abs(last_lap - own) < max(0.5, 0.02 * own))
    return (float(last_lap[win][-1]), True) if win.any() else (float(own), False)


def entrant_laps(g: pd.DataFrame, L: float, green_t: float) -> pd.DataFrame:
    """Laps for one entrant (g sorted by t, with `dist`). Stops at the chequered flag / retirement."""
    g = g[g.t >= green_t - 1.0]
    if len(g) < 2:
        return pd.DataFrame()
    t, d = g.t.to_numpy(), g.dist.to_numpy()
    rs = g.race_state.to_numpy()

    if (rs == FINISHED).any():
        stop_i = int(np.argmax(rs == FINISHED))
    elif np.isin(rs, list(DNF_STATES | {S.RACESTATE_DISQUALIFIED})).any():
        stop_i = int(np.argmax(np.isin(rs, list(DNF_STATES | {S.RACESTATE_DISQUALIFIED}))))
    else:
        stop_i = len(t) - 1
    k_last = int(np.floor(d[stop_i] / L + 1e-6))
    if k_last < 1:
        return pd.DataFrame()

    dm = np.maximum.accumulate(d)
    keep = np.r_[True, np.diff(dm) > 0]
    tx, dx = t[keep], dm[keep]
    k = np.arange(1, k_last + 1)
    k = k[k * L <= dx[-1]]
    if len(k) == 0:
        return pd.DataFrame()
    T = np.r_[green_t, np.interp(k * L, dx, tx)]
    # A "lap" far shorter than normal is a glitch (or the grid-to-line run): merge it into the next lap.
    for _ in range(3):
        own = np.diff(T)
        if len(own) < 2:
            break
        ref = np.median(own[1:]) if len(own) > 2 else np.max(own)
        short = np.flatnonzero(own < 0.4 * ref)
        if not len(short):
            break
        T = np.delete(T, short[0] + 1 if short[0] + 1 < len(T) - 1 or len(T) <= 2 else short[0])
    k = np.arange(1, len(T))

    last_lap, s1v, s2v = g.last_lap.to_numpy(float), g.cur_s1.to_numpy(float), g.cur_s2.to_numpy(float)
    inv, pit, sec, pos = g.lap_invalid.to_numpy(bool), g.pit_mode.to_numpy(), g.sector.to_numpy(), g.race_pos.to_numpy()
    rows = []
    for n in k:
        t0, t1 = T[n - 1], T[n]
        own = t1 - t0
        lap_time, game_time = completed_lap_time(t, last_lap, t1, own)
        s1 = _last_valid(t, s1v, t0 + 0.5, t1 - 0.02)
        s2 = _last_valid(t, s2v, t0 + 0.5, t1 - 0.02)
        if not (s1 > 0 and s2 > 0 and s1 + s2 < lap_time - 0.5):
            m = (t > t0) & (t < t1)
            ch = np.flatnonzero(np.diff(sec[m])) if m.sum() > 2 else np.array([])
            if len(ch) == 2:
                tt = t[m]
                b1, b2 = (tt[ch[0]] + tt[ch[0] + 1]) / 2, (tt[ch[1]] + tt[ch[1] + 1]) / 2
                s1, s2 = b1 - t0, b2 - b1
            else:
                s1 = s2 = np.nan
        s3 = lap_time - s1 - s2 if (s1 > 0 and s2 > 0) else np.nan
        in_lap = (t > t0 + 0.5) & (t <= t1)
        j = min(int(np.searchsorted(t, t1 + 1.0)), len(t) - 1)
        rows.append({
            "lap": int(n), "t_end": float(t1), "time": lap_time, "time_own": own,
            "game_time": game_time, "s1": s1, "s2": s2, "s3": s3,
            "valid": not bool(inv[in_lap].any()),
            "pit": bool(np.isin(pit[(t >= t0) & (t <= t1)], PIT_LANE).any()),
            "position": int(pos[j]) if pos[j] > 0 else np.nan,
        })
    laps = pd.DataFrame(rows)
    cand = laps[(laps.lap > 1) & laps.valid & ~laps.pit]
    cutoff = cand.time.median() * 1.07 if len(cand) else np.inf
    laps["clean"] = (laps.lap > 1) & laps.valid & ~laps.pit & (laps.time <= cutoff)
    return laps


def all_laps(frames: pd.DataFrame, L: float, green_t: float) -> pd.DataFrame:
    parts = []
    for name, g in frames.groupby("name", sort=False):
        laps = entrant_laps(g, L, green_t)
        if len(laps):
            laps.insert(0, "name", name)
            parts.append(laps)
    if not parts:
        return pd.DataFrame(columns=["name", "lap", "t_end", "time", "valid", "pit", "clean", "position"])
    laps = pd.concat(parts, ignore_index=True)
    first = laps.groupby("lap").t_end.transform("min")
    laps["gap_to_leader"] = laps.t_end - first
    return laps


# --------------------------------------------------------------------------- classification
def classify(sess: Session, frames: pd.DataFrame, laps: pd.DataFrame) -> pd.DataFrame:
    green_t, end_t = sess.green_t, sess.end_t
    rows = []
    for name, g in frames.groupby("name", sort=False):
        rs = g.race_state.to_numpy()
        finished = bool((rs == FINISHED).any())
        last = g.iloc[-1]
        present = last.t >= end_t - 2.0
        if finished:
            status = "finished"
        elif last.race_state == S.RACESTATE_DISQUALIFIED:
            status = "dsq"
        elif last.race_state in DNF_STATES:
            status = "dnf"
        elif not present:
            status = "disconnected"
        else:
            status = "running"
        el = laps[laps.name == name]
        n_laps = int(el.lap.max()) if len(el) else 0
        total = float(el.t_end.max() - green_t) if (finished and len(el)) else np.nan
        rows.append({"name": name, "car": g.car.mode().iat[0], "car_class": g.car_class.mode().iat[0],
                     "status": status, "laps": n_laps, "total_time": total,
                     "dist_last": float(g.dist.iat[-1]), "present": present,
                     "game_pos": int(last.race_pos) if present else 0})
    c = pd.DataFrame(rows, columns=["name", "car", "car_class", "status", "laps", "total_time", "dist_last", "present", "game_pos"])
    top = c[c.status.isin(["finished", "running"])].copy()
    gp = top.game_pos
    if len(top) and (gp > 0).all() and gp.is_unique:
        top = top.sort_values("game_pos")
    else:
        top = top.assign(_k=np.where(top.status == "finished", top.total_time, -top.dist_last)) \
                 .sort_values(["laps", "_k"], ascending=[False, True]).drop(columns="_k")
    out = c[c.status.isin(["dnf", "disconnected"])].sort_values(["laps", "dist_last"], ascending=False)
    dsq = c[c.status == "dsq"]
    c = pd.concat([top, out, dsq], ignore_index=True)
    c.insert(0, "pos", np.arange(1, len(c) + 1))
    winner = c.iloc[0] if len(c) else None
    c["gap"] = np.where((c.status == "finished") & (c.laps == (winner.laps if winner is not None else 0)),
                        c.total_time - (winner.total_time if winner is not None else 0), np.nan)
    c["laps_down"] = (winner.laps - c.laps) if winner is not None else 0

    grid = _grid(sess, frames)
    c["grid"] = c.name.map(grid)
    return c.drop(columns=["dist_last", "present"])


def _grid(sess: Session, frames: pd.DataFrame) -> dict:
    green_t = sess.green_t
    ev = sess.event_grid()
    if ev:
        g = {n: p for n, p in ev.items() if p and p > 0}
    else:
        pre = frames[(frames.t <= green_t) & (frames.race_pos > 0)]
        if len(pre):
            g = pre.groupby("name").race_pos.last().to_dict()
        else:  # recording started after green: best effort from distance order
            first = frames[frames.t <= green_t + 5].groupby("name").dist.first()
            g = {n: i + 1 for i, n in enumerate(first.sort_values(ascending=False).index)}
    order = sorted(g, key=lambda n: g[n])
    return {n: i + 1 for i, n in enumerate(order)}


# --------------------------------------------------------------------------- pit stops
def pit_stops(frames: pd.DataFrame, L: float, green_t: float) -> pd.DataFrame:
    rows = []
    for name, g in frames[frames.t >= green_t].groupby("name", sort=False):
        pm = g.pit_mode.to_numpy()
        inlane = np.isin(pm, [S.PIT_MODE_DRIVING_INTO_PITS, S.PIT_MODE_IN_PIT, S.PIT_MODE_DRIVING_OUT_OF_PITS])
        if not inlane.any():
            continue
        t, d, sched = g.t.to_numpy(), g.dist.to_numpy(), g.pit_schedule.to_numpy()
        edges = np.flatnonzero(np.diff(np.r_[0, inlane.astype(int), 0]))
        dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.05
        for a, b in zip(edges[::2], edges[1::2]):
            seg = slice(a, b)
            stationary = float(((pm[seg] == S.PIT_MODE_IN_PIT)).sum() * dt)
            kind = "stop"
            if np.isin(sched[seg], [S.PIT_SCHEDULE_DRIVE_THROUGH]).any():
                kind = "drive_through"
            elif np.isin(sched[seg], [S.PIT_SCHEDULE_STOP_GO]).any():
                kind = "stop_go"
            elif stationary < 0.5:
                kind = "drive_through"
            rows.append({"name": name, "lap": int(np.floor(max(d[a], 0) / L)) + 1, "entry_t": float(t[a]),
                         "lane_time": float(t[b - 1] - t[a]), "stationary_time": stationary, "kind": kind})
    return pd.DataFrame(rows, columns=["name", "lap", "entry_t", "lane_time", "stationary_time", "kind"])


# --------------------------------------------------------------------------- corners
def speed_profile(frames: pd.DataFrame, L: float, bin_m: float = 10.0) -> np.ndarray:
    """Median field speed (m/s) per lap-distance bin, from green-flag racing samples."""
    nb = max(int(np.ceil(L / bin_m)), 1)
    r = frames[(frames.race_state == RACING) & ~frames.pit_mode.isin(OFF_TRACK_PIT) & (frames.dist > 0)
               & (frames.speed > 1)]
    if len(r) == 0:
        return np.full(nb, np.nan)
    b = np.clip((r.lap_dist.to_numpy() / bin_m).astype(int), 0, nb - 1)
    prof = pd.Series(r.speed.to_numpy()).groupby(b).median().reindex(range(nb)).to_numpy()
    if np.isnan(prof).any():
        idx = np.arange(nb)
        ok = ~np.isnan(prof)
        prof = np.interp(idx, idx[ok], prof[ok], period=nb)
    return prof


def curvature_profile(ld, x, z, L: float, bin_m: float = 10.0) -> np.ndarray | None:
    """Path curvature (1/m, positive = turning left) per lap-distance bin, from one lap's positions."""
    ld, x, z = (np.asarray(a, float) for a in (ld, x, z))
    ok = np.isfinite(ld) & np.isfinite(x) & np.isfinite(z)
    if ok.sum() < 50:
        return None
    ld, x, z = ld[ok], x[ok], z[ok]
    o = np.argsort(ld)
    ld, x, z = ld[o], x[o], z[o]
    keep = np.r_[True, np.diff(ld) > 0.05]
    ld, x, z = ld[keep], x[keep], z[keep]
    nb = max(int(np.ceil(L / bin_m)), 10)
    c = (np.arange(nb) + 0.5) * bin_m
    if ld.max() - ld.min() < 0.8 * L:
        return None
    X, Z = np.interp(c, ld, x, period=L), np.interp(c, ld, z, period=L)
    k = 3
    pad = lambda a: np.r_[a[-k:], a, a[:k]]
    X = np.convolve(pad(X), np.ones(k) / k, "same")[k:-k]
    Z = np.convolve(pad(Z), np.ones(k) / k, "same")[k:-k]
    dX = np.r_[X[1:], X[:1]] - np.r_[X[-1:], X[:-1]]
    dZ = np.r_[Z[1:], Z[:1]] - np.r_[Z[-1:], Z[:-1]]
    th = np.unwrap(np.arctan2(dZ, dX))
    dth = np.r_[th[1:], th[:1] + (th[-1] - th[0]) + (th[1] - th[0])] - th  # forward difference, wrapping
    dth = (dth + np.pi) % (2 * np.pi) - np.pi
    kap = dth / bin_m
    return np.convolve(pad(kap), np.ones(k) / k, "same")[k:-k]


def _corners_from_curvature(kap: np.ndarray, profile: np.ndarray | None, bin_m: float) -> list[dict]:
    """Every turn is a curvature peak: tight hairpins, fast kinks, and both halves of a chicane
    (opposite-sign peaks). The apex is the slowest point near the peak when speed is known."""
    nb = len(kap)
    a = np.abs(kap)
    w = max(1, int(30 / bin_m))
    cands = []
    for i in range(nb):
        if a[i] < 1 / 400:  # radius over 400 m: a straight, not a turn
            continue
        if a[i] < np.take(a, range(i - w, i + w + 1), mode="wrap").max() - 1e-12:
            continue
        cands.append(i)
    def same_turn(i, j):  # same direction, and the curvature never relaxes much in between (long arcs)
        if np.sign(kap[i]) != np.sign(kap[j]):
            return False
        span = [(i + d) % nb for d in range(((j - i) % nb) + 1)]
        between = np.min(a[span]) if span else 0
        return (j - i) % nb * bin_m < 70 or between >= 0.5 * min(a[i], a[j])
    merged = []
    for i in cands:
        if merged and same_turn(merged[-1], i):
            if a[i] > a[merged[-1]]:
                merged[-1] = i
            continue
        merged.append(i)
    if len(merged) > 1 and same_turn(merged[-1], merged[0]):
        if a[merged[-1]] > a[merged[0]]:
            merged[0] = merged[-1]
        merged.pop()
    merged.sort()
    out = []
    for n, i in enumerate(merged):
        apex = i
        if profile is not None and np.isfinite(profile).any():
            gap_prev = ((i - merged[n - 1]) % nb) if len(merged) > 1 else nb
            gap_next = ((merged[(n + 1) % len(merged)] - i) % nb) if len(merged) > 1 else nb
            back, fwd = min(int(100 / bin_m), gap_prev // 2), min(int(100 / bin_m), gap_next // 2)
            win = [(i + d) % nb for d in range(-back, fwd + 1)]  # stay within this turn's half of the gap
            vals = [profile[j] if np.isfinite(profile[j]) else np.inf for j in win]
            apex = win[int(np.argmin(vals))]
        out.append((apex, i))
    out.sort()
    return [{"name": f"T{n + 1}", "apex": round(ap * bin_m + bin_m / 2, 1),
             "apex_kph": round(float(profile[ap]) * 3.6, 1) if profile is not None and np.isfinite(profile[ap]) else None,
             "dir": "left" if kap[pk] > 0 else "right", "radius": round(1 / max(abs(kap[pk]), 1e-6))}
            for n, (ap, pk) in enumerate(out)]


def detect_corners(profile: np.ndarray, bin_m: float = 10.0, min_drop: float = 5.0,
                   window_m: float = 150.0, curvature: np.ndarray | None = None) -> list[dict]:
    """Corners from the track's shape when positions are available (curvature peaks, so kinks and
    chicanes count), otherwise prominent local minima of the speed-vs-distance profile."""
    if curvature is not None and len(curvature) == len(profile) and np.isfinite(curvature).all():
        found = _corners_from_curvature(curvature, profile, bin_m)
        if len(found) >= 2:
            return found
    if np.isnan(profile).all():
        return []
    nb = len(profile)
    k = 5
    padded = np.r_[profile[-k:], profile, profile[:k]]
    smooth = np.convolve(padded, np.ones(k) / k, mode="same")[k:-k]
    w = max(int(window_m / bin_m), 1)
    wide = max(int(400 / bin_m), w)
    apexes = []
    for i in range(nb):
        near = np.take(smooth, range(i - w, i + w + 1), mode="wrap")
        if smooth[i] > near.min() + 1e-9:
            continue
        far = np.take(smooth, range(i - wide, i + wide + 1), mode="wrap")
        if far.max() - smooth[i] >= min_drop:
            if apexes and (i - apexes[-1]) * bin_m < window_m:
                continue
            apexes.append(i)
    if len(apexes) > 1 and (apexes[0] + nb - apexes[-1]) * bin_m < window_m:
        apexes.pop()
    return [{"name": f"T{n + 1}", "apex": round(a * bin_m + bin_m / 2, 1),
             "apex_kph": round(float(smooth[a]) * 3.6, 1)} for n, a in enumerate(apexes)]


def corner_for(lap_dist: float, corners: list[dict], exit_m: float = 60.0) -> str | None:
    """A pass belongs to the corner whose braking zone/apex it happened in: zone k runs from
    (apex[k-1] + exit_m) to (apex[k] + exit_m]."""
    if not corners:
        return None
    ends = [c["apex"] + exit_m for c in corners]
    for c, end in zip(corners, ends):
        if lap_dist <= end:
            return c["name"]
    return corners[0]["name"]  # past the last corner's exit: braking zone of T1 (wraps)


def reference_lap_xy(fr: pd.DataFrame, laps: pd.DataFrame, green_t: float | None = None):
    """(lap_dist, x, z) of one clean lap, for track shape: the driver with the most clean laps."""
    if laps is None or not len(laps) or "clean" not in laps.columns:
        return None
    clean = laps[laps.clean]
    if not len(clean):
        return None
    name = clean.groupby("name").size().idxmax()
    mine = clean[clean.name == name].sort_values("lap")
    lp = mine.iloc[min(1, len(mine) - 1)]
    prev = laps[(laps.name == name) & (laps.lap == lp.lap - 1)]
    t0 = float(prev.t_end.iat[0]) if len(prev) else (green_t or float(fr.t.min()))
    seg = fr[(fr.name == name) & (fr.t > t0) & (fr.t <= float(lp.t_end))]
    return (seg.lap_dist.to_numpy(float), seg.x.to_numpy(float), seg.z.to_numpy(float)) if len(seg) > 50 else None


def custom_corners(custom: list, profile: np.ndarray, curvature: np.ndarray | None = None, bin_m: float = 10.0) -> list[dict]:
    """Turns you placed yourself (name + lap distance), completed with apex speed and direction so they
    work everywhere detected ones do."""
    nb = len(profile)
    out = []
    for n, c in enumerate(sorted(custom, key=lambda c: float(c["apex"]))):
        i = int(float(c["apex"]) / bin_m) % nb
        k = float(np.mean(np.take(curvature, range(i - 3, i + 4), mode="wrap"))) if curvature is not None else 0.0
        v = profile[i] if nb else np.nan
        out.append({"name": (c.get("name") or f"T{n + 1}").strip()[:12], "apex": round(float(c["apex"]), 1),
                    "apex_kph": round(float(v) * 3.6, 1) if v == v else None,
                    "dir": ("left" if k > 0 else "right") if abs(k) > 1e-5 else None,
                    "radius": round(1 / abs(k)) if abs(k) > 1e-5 else None, "custom": True,
                    "exit_policy": 'compromise' if c.get('exit_policy') == 'compromise' else 'auto'})
    return out
