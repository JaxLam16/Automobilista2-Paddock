"""Practice sessions with objectives, F1-game style.

Pick objectives before going out; the tracker watches the recording car live (any practice session)
and ticks them off lap by lap. Laps are judged with the game's own lap times and validity; braking
points come from your real brake pedal; lock-ups and wheelspin from wheel speed against car speed.
"""
from __future__ import annotations

import math
import time

import numpy as np

from . import shm as S

TEMPLATES = [
    {"id": "consistency", "title": "Consistency run", "describe": "{laps} clean laps in a row within {pct}% of your personal best",
     "params": {"laps": {"value": 3, "min": 1, "max": 10, "step": 1}, "pct": {"value": 101.0, "min": 100.1, "max": 105, "step": 0.1}}},
    {"id": "target", "title": "Beat the target", "describe": "A clean lap at least {offset} s quicker than your personal best",
     "params": {"offset": {"value": 0.1, "min": 0.0, "max": 2.0, "step": 0.05}}},
    {"id": "clean_streak", "title": "Clean streak", "describe": "{laps} clean laps in a row",
     "params": {"laps": {"value": 5, "min": 2, "max": 20, "step": 1}}},
    {"id": "brake_points", "title": "Braking markers", "describe": "{laps} laps in a row with every braking point within {tolerance} m of your average",
     "params": {"laps": {"value": 3, "min": 1, "max": 10, "step": 1}, "tolerance": {"value": 5, "min": 1, "max": 20, "step": 1}}},
    {"id": "smooth", "title": "Smooth operator", "describe": "{laps} laps in a row without a lock-up or wheelspin",
     "params": {"laps": {"value": 3, "min": 1, "max": 10, "step": 1}}},
    {"id": "sector", "title": "Sector focus", "describe": "Beat your best sector {sector} of the session by {gain} s",
     "params": {"sector": {"value": 2, "min": 1, "max": 3, "step": 1}, "gain": {"value": 0.1, "min": 0.01, "max": 1.0, "step": 0.01}}},
]
DEFAULT_SELECTION = ["consistency", "clean_streak", "brake_points"]


def describe(obj: dict) -> str:
    t = next(x for x in TEMPLATES if x["id"] == obj["id"])
    return t["describe"].format(**{k: obj.get(k, v["value"]) for k, v in t["params"].items()})


class PracticeTracker:
    def __init__(self, objectives: list[dict], pb_lookup=None):
        self.objectives = [dict(o) for o in objectives]
        self.pb_lookup = pb_lookup
        self.started = time.time()
        self.reset(None, None, None, None)

    def reset(self, track, layout, car, driver):
        self.track, self.layout, self.car, self.driver = track, layout, car, driver
        self.pb = self.pb_lookup(track, layout, car, driver) if (self.pb_lookup and track) else None
        self.laps, self.cur, self.counter = [], [], None
        self.pending = None
        self.lap_start = None
        self.s12 = (None, None)
        self.radius = None
        self.corners = None

    # -------------------------------------------------------------- live feed
    def feed(self, snap, now: float) -> None:
        if snap.mGameState not in (S.GAME_INGAME_PLAYING, S.GAME_INGAME_INMENU_TIME_TICKING) or snap.mTrackLength <= 0:
            return
        i = snap.mViewedParticipantIndex
        if not (0 <= i < S.STORED_PARTICIPANTS_MAX) or not snap.mParticipantInfo[i].mIsActive:
            return
        p = snap.mParticipantInfo[i]
        key = (S.cstr(snap.mTrackLocation), S.cstr(snap.mTrackVariation), S.cstr(snap.mCarName), S.cstr(p.mName))
        if key != (self.track, self.layout, self.car, self.driver):
            self.reset(*key)
            self.L = float(snap.mTrackLength)
        lc = p.mLapsCompleted & 0x7FFFFFFF
        if self.counter is None:
            self.counter, self.lap_start = lc, now
            self.cur_out = True  # the first lap of a run is an out lap
        if self.pending and (snap.mLastLapTimes[i] > 0 and abs(snap.mLastLapTimes[i] - self.pending["prev_last"]) > 1e-3
                             or now - self.pending["at"] > 2.0):
            lap = self.pending["lap"]
            if snap.mLastLapTimes[i] > 0 and abs(snap.mLastLapTimes[i] - self.pending["prev_last"]) > 1e-3:
                lap["time"] = float(snap.mLastLapTimes[i])
            self.pending = None
            self._finish(lap)
        if lc > self.counter:  # crossed the line
            s1, s2 = self.s12
            lap = {"n": len(self.laps) + 1, "time": now - self.lap_start, "valid": not any(x[6] for x in self.cur[10:]),
                   "out": self.cur_out or any(x[7] != 0 for x in self.cur), "samples": self.cur,
                   "s1": s1, "s2": s2}
            self.pending = {"lap": lap, "at": now, "prev_last": float(snap.mLastLapTimes[i])}
            self.cur, self.counter, self.lap_start, self.cur_out, self.s12 = [], lc, now, False, (None, None)
        s1 = snap.mCurrentSector1Time if snap.mCurrentSector1Time > 0 else snap.mCurrentSector1Times[i]
        s2 = snap.mCurrentSector2Time if snap.mCurrentSector2Time > 0 else snap.mCurrentSector2Times[i]
        if s1 > 0:
            self.s12 = (float(s1), self.s12[1])
        if s2 > 0:
            self.s12 = (self.s12[0], float(s2))
        self.cur.append((now, p.mCurrentLapDistance, snap.mSpeed, snap.mThrottle, snap.mBrake, snap.mSteering,
                         bool(snap.mLapInvalidated), int(snap.mPitMode), *[snap.mTyreRPS[w] for w in range(4)],
                         float(np.mean(list(snap.mTyreWear))), p.mWorldPosition[0], p.mWorldPosition[2]))
        if len(self.cur) > 40_000:
            self.cur = self.cur[-40_000:]

    # -------------------------------------------------------------- per-lap analysis
    def _finish(self, lap: dict) -> None:
        a = np.array(lap["samples"], dtype=float) if lap["samples"] else np.zeros((0, 15))
        lap["time"] = float(lap["time"])
        if lap["s1"] and lap["s2"] and lap["time"] > lap["s1"] + lap["s2"]:
            lap["s3"] = lap["time"] - lap["s1"] - lap["s2"]
        else:
            lap["s1"] = lap["s2"] = lap["s3"] = None
        if len(a) > 50:
            v = a[:, 2]
            if self.radius is None or len(self.laps) < 3:  # learn wheel radii from steady driving
                ok = (v > 20) & (a[:, 4] < 0.02) & (a[:, 8:12].min(axis=1) > 1)
                if ok.sum() > 30:
                    self.radius = [float(np.median(v[ok] / (2 * math.pi * a[ok, 8 + w]))) for w in range(4)]
            lock = spin = 0
            if self.radius:
                slip = (2 * math.pi * a[:, 8:12] * np.array(self.radius) - v[:, None]) / np.maximum(v[:, None], 1)
                lock = self._events((a[:, 4] > 0.3) & (slip[:, :2].min(axis=1) < -0.2) & (v > 8), 3)
                spin = self._events((a[:, 3] > 0.4) & (slip[:, 2:].max(axis=1) > 0.15) & (v > 5), 4)
            lap["lockups"], lap["wheelspin"] = lock, spin
            lap["wear"] = float(max(0.0, a[-1, 12] - a[0, 12]) * 100)
            lap["ld"], lap["brake"], lap["speed"], lap["x"], lap["z"] = a[:, 1], a[:, 4], a[:, 2], a[:, 13], a[:, 14]
        else:
            lap["lockups"] = lap["wheelspin"] = 0
        lap.pop("samples", None)
        self.laps.append(lap)
        counted = [x for x in self.laps if x["valid"] and not x["out"]]
        if counted and self.corners is None:
            self.corners = self._corners(counted[0])
        if self.corners:
            for x in self.laps:
                if "ld" in x and "brake_pts" not in x:
                    x["brake_pts"] = self._brake_points(x)
        self._evaluate()

    @staticmethod
    def _events(mask, need):
        n = run = 0
        for x in mask:
            run = run + 1 if x else 0
            if run == need:
                n += 1
        return n

    def _corners(self, lap):
        if "ld" not in lap:
            return None
        nb = max(int(self.L / 10), 1)
        b = np.clip((lap["ld"] / 10).astype(int), 0, nb - 1)
        prof = np.full(nb, np.nan)
        for k in np.unique(b):
            prof[k] = np.median(lap["speed"][b == k])
        ok = ~np.isnan(prof)
        if ok.sum() < nb * 0.6:
            return None
        prof = np.interp(np.arange(nb), np.arange(nb)[ok], prof[ok], period=nb)
        from .derive import curvature_profile, detect_corners
        kap = curvature_profile(lap["ld"], lap["x"], lap["z"], self.L) if "x" in lap else None
        return detect_corners(prof, curvature=kap)

    def _brake_points(self, lap):
        pts = {}
        for c in self.corners:
            rel = (lap["ld"] - c["apex"]) % self.L
            rel = np.where(rel > self.L / 2, rel - self.L, rel)
            m = (rel >= -350) & (rel <= 0) & (lap["brake"] > 0.1)
            pts[c["name"]] = float(rel[m].min()) if m.any() else None
        return pts

    # -------------------------------------------------------------- objectives
    def reference(self):
        best = min((x["time"] for x in self.laps if x["valid"] and not x["out"]), default=None)
        return min([v for v in (self.pb, best) if v], default=None)

    def _evaluate(self) -> None:
        counted = [x for x in self.laps if not x["out"]]
        ref = self.pb or min((x["time"] for x in counted if x["valid"]), default=None)

        def streak(test):
            best = cur = 0
            for x in counted:
                cur = cur + 1 if test(x) else 0
                best = max(best, cur)
            return best, cur
        for o in self.objectives:
            kind = o["id"]
            if kind == "consistency":
                lim = ref * o.get("pct", 101.0) / 100 if ref else None
                best, cur = streak(lambda x: x["valid"] and lim is not None and x["time"] <= lim)
                o.update(progress=min(best, o.get("laps", 3)), goal=o.get("laps", 3), current=cur,
                         note=f"Limit {_fmt(lim)}" if lim else "Set a clean lap to get a reference")
            elif kind == "target":
                target = (self.pb - o.get("offset", 0.1)) if self.pb else None
                best_now = min((x["time"] for x in counted if x["valid"]), default=None)
                if target is None and best_now:  # no previous best: aim to beat your first clean lap
                    first = next(x["time"] for x in counted if x["valid"])
                    target = first - o.get("offset", 0.1)
                hit = best_now is not None and target is not None and best_now <= target
                o.update(progress=1 if hit else 0, goal=1, note=(f"Target {_fmt(target)}" + (f", best {_fmt(best_now)}" if best_now else "")) if target else "Set a clean lap first")
            elif kind == "clean_streak":
                best, cur = streak(lambda x: x["valid"])
                o.update(progress=min(best, o.get("laps", 5)), goal=o.get("laps", 5), current=cur, note="")
            elif kind == "brake_points":
                laps = [x for x in counted if x["valid"] and x.get("brake_pts")]
                tol = o.get("tolerance", 5)
                if len(laps) >= 2:
                    names = [c["name"] for c in self.corners]
                    avg = {n: np.mean([x["brake_pts"][n] for x in laps if x["brake_pts"].get(n) is not None] or [0]) for n in names}

                    def ok(x):
                        if not (x["valid"] and x.get("brake_pts")):
                            return False
                        return all(x["brake_pts"].get(n) is None or abs(x["brake_pts"][n] - avg[n]) <= tol for n in names)
                    best, cur = streak(ok)
                    worst = max(names, key=lambda n: np.std([x["brake_pts"][n] for x in laps if x["brake_pts"].get(n) is not None] or [0]))
                    note = f"Hardest to repeat: {worst}"
                else:
                    best = cur = 0
                    note = "Needs two clean laps to learn your braking points"
                o.update(progress=min(best, o.get("laps", 3)), goal=o.get("laps", 3), current=cur, note=note)
            elif kind == "smooth":
                best, cur = streak(lambda x: x.get("lockups", 0) == 0 and x.get("wheelspin", 0) == 0)
                o.update(progress=min(best, o.get("laps", 3)), goal=o.get("laps", 3), current=cur, note="")
            elif kind == "sector":
                sk = f"s{int(o.get('sector', 2))}"
                vals = [x[sk] for x in counted if x["valid"] and x.get(sk)]
                if vals:
                    target = vals[0] - o.get("gain", 0.1)
                    hit = min(vals) <= target
                    o.update(progress=1 if hit else 0, goal=1, note=f"Target {target:.3f} (first {vals[0]:.3f}, best {min(vals):.3f})")
                else:
                    o.update(progress=0, goal=1, note="Set a clean lap first")
            o["done"] = o.get("progress", 0) >= o.get("goal", 1)

    def status(self) -> dict:
        now = time.time()
        counted_best = min((x["time"] for x in self.laps if x["valid"] and not x["out"]), default=None)
        for o in self.objectives:
            o.setdefault("progress", 0)
            o.setdefault("goal", o.get("laps", 1) if o["id"] not in ("target", "sector") else 1)
            o.setdefault("done", False)
            o.setdefault("note", "")
            o["text"] = describe(o)
        return {"active": True, "track": self.track, "layout": self.layout, "car": self.car, "driver": self.driver,
                "pb": self.pb, "session_best": counted_best,
                "laps": [{k: x.get(k) for k in ("n", "time", "valid", "out", "s1", "s2", "s3", "lockups", "wheelspin", "wear")}
                         | {"brake_pts": x.get("brake_pts")} for x in self.laps],
                "objectives": self.objectives, "done": sum(1 for o in self.objectives if o.get("done")),
                "corners": [c["name"] for c in (self.corners or [])], "elapsed": round(now - self.started)}


def _fmt(x):
    if x is None:
        return "-"
    m, s = divmod(float(x), 60)
    return f"{int(m)}:{s:06.3f}" if m else f"{s:.3f}"


def suggest_objectives(recordings_dir) -> dict:
    """Goals picked from your own history: the car and track of your latest practice, and every earlier practice
    there. Each goal sits just beyond your best so far, so it's within reach but a stretch."""
    import json
    from pathlib import Path
    from .derive import add_distance, effective_track_length, load_session
    from .quali import session_laps
    recs = []
    for p in Path(recordings_dir).iterdir() if Path(recordings_dir).exists() else []:
        try:
            m = json.loads((p / "session.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        if m.get("session_type") == "practice" and m.get("status") == "complete" and not (p / "import.json").exists():
            recs.append((m.get("started_at") or "", p, m))
    recs.sort(reverse=True)
    if not recs:
        return {"objectives": [_params("clean_streak", laps=5), _params("consistency", laps=3, pct=101.0), _params("target", offset=0.1)],
                "based_on": None, "reasons": {"clean_streak": "A first goal: five clean laps in a row.",
                                               "consistency": "Three laps within 1% of your best.", "target": "Beat your first clean lap."}}
    car, track = (recs[0][2].get("local") or {}).get("car"), recs[0][2].get("track_variation")
    same = [(t, p, m) for t, p, m in recs if (m.get("local") or {}).get("car") == car and m.get("track_variation") == track][:10]
    best_streak = best_cons = 0
    laps_total = 0
    for _, p, m in same:
        try:
            sess = load_session(p)
            name = (m.get("local") or {}).get("name")
            L, _ = effective_track_length(sess.frames, sess.L)
            g = add_distance(sess.frames[sess.frames.name == name].sort_values("t"), L, None)
            laps = session_laps(g, L)
        except Exception:
            continue
        seq = [(float(x.time), bool(x.valid)) for x in laps.itertuples() if x.time == x.time and x.time > 0]
        laps_total += len(seq)
        valid = [t for t, v in seq if v]
        if not valid:
            continue
        ref = min(valid)
        cur = cons = 0
        for t, v in seq:
            cur = cur + 1 if v else 0
            best_streak = max(best_streak, cur)
            cons = cons + 1 if v and t <= ref * 1.01 else 0
            best_cons = max(best_cons, cons)
    streak_goal = int(min(15, max(5, best_streak + 2)))
    cons_goal = int(min(10, max(3, best_cons + 1)))
    reasons = {"clean_streak": f"Your best so far here is {best_streak} clean laps in a row: aim for {streak_goal}." if best_streak else "Five clean laps in a row to start.",
               "consistency": f"Your best run within 1% of your best lap is {best_cons}: aim for {cons_goal}." if best_cons else "Three laps within 1% of your best.",
               "target": "Beat your personal best for this car and track by a tenth." if same else "Beat your first clean lap by a tenth."}
    return {"objectives": [_params("clean_streak", laps=streak_goal), _params("consistency", laps=cons_goal, pct=101.0), _params("target", offset=0.1)],
            "based_on": {"car": car, "track": recs[0][2].get("track_variation_translated") or track, "sessions": len(same), "laps": laps_total},
            "reasons": reasons}


def _params(kind: str, **kw) -> dict:
    return {"id": kind, **kw}
