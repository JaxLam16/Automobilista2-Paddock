"""Engineer sessions: one per car and track, saved as JSON beside the app. They hold the race target, the
settings your car doesn't have, the net ticks you've applied since the default setup, every run with its
measurements and recommendations, what you decided, and what one tick has been measured to do on this car."""
from __future__ import annotations

import json
import hashlib
import copy
import re
import threading
import time
from functools import wraps
from pathlib import Path

import pandas as pd

from . import engine
from .catalog import BY_KEY, CAT_LABEL, CATEGORIES

_STORE_LOCK = threading.RLock()


def _locked(method):
    @wraps(method)
    def run(*args, **kwargs):
        with _STORE_LOCK:
            return method(*args, **kwargs)
    return run


def recommendation_token(session, run, rec):
    """Bind a garage decision to the exact analysed recommendation, not its setting alone."""
    value = {'key': session.get('key'), 'car': session.get('car'), 'track': session.get('track'),
             'layout': session.get('layout'), 'run': run.get('id'), 'analysed_at': run.get('analysed_at'),
             'source': run.get('source'), 'recommendation': rec}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def setup_review(session):
    """Receipt for saved decisions; submitting acknowledges them without applying ticks again."""
    run = (session.get('runs') or [None])[-1]
    if not run:
        return None
    choices = {'applied', 'skipped', 'maxed', 'unavailable'}
    items = [{'id': r['id'], 'setting': r['setting'], 'label': BY_KEY[r['setting']]['label'],
              'ticks': r['ticks'], 'decision': (run.get('decisions') or {}).get(r['id']),
              'revision': recommendation_token(session, run, r)}
             for r in run.get('recommendations') or [] if r.get('setting') in BY_KEY
             and r.get('ticks') and not r.get('info')]
    remaining = sum(i['decision'] not in choices for i in items)
    value = {'key': session.get('key'), 'car': session.get('car'), 'track': session.get('track'),
             'layout': session.get('layout'), 'run_id': run['id'], 'items': items,
             'pending_changes': session.get('pending_changes') or [], 'ticks': session.get('ticks') or {},
             'maxed': session.get('maxed') or {}, 'unavailable': session.get('unavailable') or [],
             'next_run': session.get('next_run') or {}}
    token = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    submission = run.get('setup_submission') or {}
    return {**value, 'token': token, 'remaining': remaining,
            'counts': {c: sum(i['decision'] == c for i in items) for c in sorted(choices)},
            'can_submit': not remaining and bool(items or value['pending_changes']),
            'submitted': submission.get('token') == token,
            'submitted_at': submission.get('submitted_at') if submission.get('token') == token else None}

LEARNABLE = {  # setting prefix -> (learned key, measurement, sign: + if positive ticks raise the measurement)
    "pressure_": ("pressure", "press_hot_bar", 1), "camber_": ("camber", "inner_minus_outer", 1),
    "final_drive": ("final_drive", "top_gear_rpm_frac", 1), "downforce_rear": ("fast_gradient", "fast_gradient", 1),
    "ride_height_": ("ride_height", "ride_min_cm", 1),
    "downforce_front": ("fast_gradient", "fast_gradient", -1),
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


class EngineerStore:
    def __init__(self, root: Path):
        self.dir = Path(root) / "engineer"

    def key(self, car: str, track: str, layout: str) -> str:
        return f"{slug(car)}__{slug(track)}__{slug(layout)}"

    def path(self, key: str) -> Path:
        p = (self.dir / f"{slug(key) if '__' not in key else key}.json").resolve()
        if p.parent != self.dir.resolve():
            raise LookupError("no such engineer session")
        return p

    @_locked
    def delete(self, key):
        self.path(key).unlink(missing_ok=True)

    def list(self) -> list[dict]:
        out = []
        for f in sorted(self.dir.glob("*.json")) if self.dir.exists() else []:
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            last = s["runs"][-1] if s.get("runs") else None
            out.append({"key": s["key"], "car": s["car"], "track": s["track"], "layout": s.get("layout"), "runs": len(s.get("runs", [])),
                        "updated": s.get("updated"), "categories": last["categories"] if last else None})
        return sorted(out, key=lambda x: x.get("updated") or "", reverse=True)

    @_locked
    def get(self, key: str) -> dict:
        p = self.path(key)
        if not p.exists():
            raise LookupError("no such engineer session")
        s = json.loads(p.read_text(encoding="utf-8"))
        if s.get("runs") and s.get("engine_version") != engine.ENGINE_VERSION:
            # analysed by an older engineer: bring the latest run's advice, colours and breakdowns up to date
            s.setdefault("flags", {}).setdefault("clean_streak", {})
            s["flags"].setdefault("tested", {})
            if (s.get("fuel_plan") or 0) < 2:   # fuel runs are now judged against race fuel, not the tank
                for k in ("high_fuel_done", "low_fuel_done", "high_fuel_run", "low_fuel_run"):
                    s["flags"].pop(k, None)
                for run in s["runs"]:
                    self._mark_fuel(s, run["measure"])
                s["fuel_plan"] = 2
            self._evaluate(s)
            self.save(s)
        return s

    @_locked
    def save(self, s: dict) -> dict:
        s["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if s.get("runs"):
            s["engine_version"] = engine.ENGINE_VERSION
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.path(s['key'])
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(s), encoding='utf-8')
        temporary.replace(path)
        return s

    @_locked
    def create(self, car: str, track: str, layout: str, race_target: dict | None = None, **opts) -> dict:
        key = self.key(car, track, layout)
        try:
            s = self.get(key)
        except LookupError:
            s = {"key": key, "car": car, "track": track, "layout": layout, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "race_target": {"mode": "time", "minutes": 60}, "symmetrical_off": False, "baseline_default": False,
                 "unavailable": [], "maxed": {}, "ticks": {}, "runs": [], "learned": {}, "corners": None,
                 "pending_changes": [], "flags": {"low_fuel_done": False, "tested": {}, "clean_streak": {}}}
        if race_target:
            s["race_target"] = race_target
        for k in ("symmetrical_off", "baseline_default", "unavailable", "press_window", "prefs"):
            if k in opts and opts[k] is not None:
                s[k] = opts[k]
        if s.get("runs") and any(opts.get(k) is not None for k in ("unavailable", "press_window", "prefs")) or race_target and s.get("runs"):
            self._evaluate(s)            # what you like, or what the car has, changes the advice for the latest run
        return self.save(s)

    # ------------------------------------------------------------------------------------------ runs
    def _state(self, s: dict) -> dict:
        last = s["runs"][-1]["measure"] if s["runs"] else {}
        return {"unavailable": s.get("unavailable", []), "maxed": s.get("maxed", {}), "learned": s.get("learned", {}),
                "press_window": s.get("press_window"), "race_target": s.get("race_target"), "runs_analysed": len(s["runs"]),
                "prefs": s.get("prefs") or {},
                "low_fuel_done": s["flags"].get("low_fuel_done"), "high_fuel_done": s["flags"].get("high_fuel_done"),
                "tested": s["flags"].get("tested", {}),
                "clean_streak": s["flags"].get("clean_streak", {}), "fuel_per_lap": (last.get("fuel") or {}).get("per_lap_l"),
                "avg_lap": last.get("avg_lap")}

    @_locked
    def add_run(self, key: str, lo: pd.DataFrame, L: float, source: str) -> dict:
        s = self.get(key)
        m = engine.measure_run(lo, L, s.get("corners"))
        if not s.get("corners") and m.get("corners"):
            s["corners"] = m["corners"]          # the first run fixes the corner list, so later runs compare like for like
        prev = s["runs"][-1]["measure"] if s["runs"] else None
        changes = s.get("pending_changes", [])
        learned_now = self._learn(s, prev, m, changes) if prev else []
        checks = self._verify(s, prev, m, changes)
        self._mark_fuel(s, m)
        run = {"id": len(s["runs"]) + 1, "source": source, "analysed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "measure": m,
               "changes_before": changes, "compare": engine.compare(prev, m), "learned": learned_now, "checks": checks, "decisions": {}}
        s["runs"].append(run)
        s["pending_changes"] = []
        self._evaluate(s, new_run=True)
        return self.save(s)

    def _mark_fuel(self, s: dict, m: dict) -> None:
        """Race-fuel ("high") and low-fuel runs, judged on the tank itself, and once both exist, what the
        fuel load costs per lap. "High" is race fuel or more: the race's starting fuel (a full tank when it
        needs more than one), estimated from this run's own fuel use when it's the first measurement."""
        f = m.get("fuel") or {}
        if not (f.get("start_l") and f.get("capacity_l") and m.get("avg_lap")):
            return
        share = f["start_l"] / f["capacity_l"]
        race_l = engine.race_run_fuel(engine.race_fuel(self._state(s), m), f["capacity_l"])
        per = f.get("per_lap_l") or self._state(s).get("fuel_per_lap")
        if share >= 0.7 or race_l is not None and f["start_l"] >= race_l - max(2.0, 0.1 * race_l):
            s["flags"]["high_fuel_done"] = True
            s["flags"]["high_fuel_run"] = {"fuel_l": f["start_l"], "avg_lap": m["avg_lap"]}
        elif share <= 0.35 or per and f["start_l"] <= engine.low_fuel_l(per) + 3:
            s["flags"]["low_fuel_done"] = True
            s["flags"]["low_fuel_run"] = {"fuel_l": f["start_l"], "avg_lap": m["avg_lap"]}
        hi, lo_ = s["flags"].get("high_fuel_run"), s["flags"].get("low_fuel_run")
        if hi and lo_ and hi["fuel_l"] > lo_["fuel_l"] + 20:
            s["fuel_effect_s_per_10l"] = round((hi["avg_lap"] - lo_["avg_lap"]) / (hi["fuel_l"] - lo_["fuel_l"]) * 10, 3)

    def _evaluate(self, s: dict, new_run: bool = False) -> None:
        """Recommendations, category colours and breakdowns, the qualifying variant and the plan for the latest
        run. Re-run when your preferences or the car's available settings change."""
        run = s["runs"][-1]
        m = run["measure"]
        prev = s["runs"][-2]["measure"] if len(s["runs"]) > 1 else None
        state = self._state(s)
        recs = engine.merge_feedback(engine.recommend(m, state, prev), run.get("feedback"), m, state)
        if new_run:
            for c, _ in CATEGORIES:   # consecutive runs WITH evidence for the category and nothing to change
                has_recs = any(r["category"] == c and not r.get("test") for r in recs)
                ok = engine._has_evidence(c, m) and not has_recs
                s["flags"]["clean_streak"][c] = s["flags"]["clean_streak"].get(c, 0) + 1 if ok else 0
        state["clean_streak"] = s["flags"]["clean_streak"]
        cats = engine.categories(m, recs, state)
        for c, _ in CATEGORIES:
            hist = [{"run": r["id"], "value": engine.key_metric_value(c, r["measure"])} for r in s["runs"][:-1]]
            cats[c]["detail"] = engine.category_detail(c, m, recs, state, hist)
        run["recommendations"] = recs
        run["categories"] = cats
        run["quali"] = engine.quali_variant(m, state)
        run["decisions"] = {k: v for k, v in run.get("decisions", {}).items() if any(r["id"] == k for r in recs)}
        s["next_run"] = engine.next_run(state, m, recs)
        s["race_fuel"] = engine.race_fuel(state, m)

    def _learn(self, s: dict, prev: dict, m: dict, changes: list) -> list:
        """What did each change do? Measure the setting's own target before and after, per tick."""
        out = []
        for ch in changes:
            key, n = ch["setting"], ch["ticks"]
            spec = next((v for p, v in LEARNABLE.items() if key.startswith(p)), None)
            if not spec or not n:
                continue
            name, field, sign = spec
            w = key.rsplit("_", 1)[-1] if key.startswith(("pressure_", "camber_", "ride_height_")) else None
            src = "platform" if key.startswith("ride_height_") else "tyres"
            get = (lambda mm: ((mm.get(src) or {}).get(w) or {}).get(field)) if w else \
                  (lambda mm: (mm.get("gearing") or {}).get(field)) if field == "top_gear_rpm_frac" else (lambda mm: mm.get(field))
            a, b = get(prev), get(m)
            if a is None or b is None:
                continue
            per = sign * (b - a) / n
            guess = engine.TICK_GUESS.get(name)
            if per <= 0 or (guess and per < 0.25 * guess):
                # moved the wrong way, or far less than a tick plausibly could: the change may not have gone in,
                # or something else masked it. Note it, never learn a nonsense tick size from it.
                out.append({"setting": key, "label": BY_KEY[key]["label"], "measure": field, "before": a, "after": b, "ticks": n, "per_tick": None,
                            "note": f"{BY_KEY[key]['label']}: no clear effect from {n:+d} ticks ({field.replace('_', ' ')} {a} → {b}). "
                                    "Check the change went in; other changes or driving may also have masked it."})
                continue
            cur = s["learned"].get(name)
            new = per if not cur else (cur["per_tick"] * cur["n"] + per) / (cur["n"] + 1)
            s["learned"][name] = {"per_tick": round(new, 4), "n": (cur or {}).get("n", 0) + 1}
            out.append({"setting": key, "label": BY_KEY[key]["label"], "measure": field, "before": a, "after": b, "ticks": n, "per_tick": round(per, 4)})
        # bottoming after lowering: that axle's ride height when it started touching is its floor from now on
        lowered = {("front" if c["setting"][-2] == "f" else "rear") for c in changes if c["setting"].startswith("ride_height_") and c["ticks"] < 0}
        for axle in lowered:
            ws = ("fl", "fr") if axle == "front" else ("rl", "rr")
            ps = [((m.get("platform") or {}).get(w) or {}) for w in ws]
            if any((p.get("ride_near_zero_s") or 0) > 0 or (p.get("at_travel_limit_s") or 0) > 0 for p in ps):
                mins = [p.get("ride_min_cm") for p in ps if p.get("ride_min_cm") is not None]
                if mins:
                    s["learned"][f"ride_floor_{axle}"] = {"cm": round(min(mins), 2), "n": 1}
                    out.append({"setting": None, "label": f"{axle.capitalize()} ride height", "measure": "floor",
                                "note": f"The {axle} started bottoming at {min(mins):.1f} cm: the engineer will stay {engine.TARGETS['ride_floor_margin_cm']:.1f} cm above that from now on."})
        cmp_ = engine.compare(prev, m)
        if cmp_ and cmp_.get("balance_change") is not None and changes:
            out.append({"setting": None, "label": "Balance", "measure": "steering per curvature", "change": cmp_["balance_change"],
                        "note": f"Corner by corner the car needed {cmp_['balance_change']:+.0%} steering for the same curvature after: "
                                + ", ".join(f"{BY_KEY[c['setting']]['label'].lower()} {c['ticks']:+d}" for c in changes) + "."})
        return out

    def _verify(self, s: dict, prev: dict | None, m: dict, changes: list) -> list:
        """Settings the game does report: did the change actually go in?"""
        out = []
        b0, b1 = (prev or {}).get("braking") or {}, m.get("braking") or {}
        for ch in changes:
            if ch["setting"] == "brake_bias" and b0.get("brake_bias_front") is not None and b1.get("brake_bias_front") == b0.get("brake_bias_front"):
                out.append(f"Brake bias still reads {b1['brake_bias_front']:.0%} front: the change doesn't seem to have gone in.")
            if ch["setting"] == "traction_control" and b0.get("tc_setting") is not None and b1.get("tc_setting") == b0.get("tc_setting"):
                out.append(f"Traction control still reads {b1['tc_setting']}: the change doesn't seem to have gone in.")
            if ch["setting"] == "abs" and b0.get("abs_setting") is not None and b1.get("abs_setting") == b0.get("abs_setting"):
                out.append(f"ABS still reads {b1['abs_setting']}: the change doesn't seem to have gone in.")
        return out

    @_locked
    def feedback(self, key: str, fb: dict) -> dict:
        """How the latest run felt. Re-evaluates that run's recommendations with it."""
        s = self.get(key)
        if not s["runs"]:
            raise ValueError("Analyse a run first: feedback belongs to a run.")
        clean = {}
        for ph, _ in engine.FEEDBACK_PHASES:
            row = {sp: int(v) for sp, v in (fb.get(ph) or {}).items() if sp in dict(engine.FEEDBACK_SPEEDS) and v not in (None, "") and -2 <= int(v) <= 2}
            if row:
                clean[ph] = row
        for k, lim in (("throttle", 2), ("kerbs", 1)):
            v = fb.get(k)
            if v not in (None, "") and -lim <= int(v) <= lim:
                clean[k] = int(v)
        if fb.get("notes"):
            clean["notes"] = str(fb["notes"])[:1000]
        s["runs"][-1]["feedback"] = clean
        self._evaluate(s)
        return self.save(s)

    # ------------------------------------------------------------------------------------------ decisions
    @_locked
    def decide(self, key: str, decisions: dict, manual: list | None = None) -> dict:
        """decisions: recommendation id -> "applied" | "maxed" | "unavailable" | "skipped" (for the latest run).
        manual: [{setting, ticks}] for changes you made yourself."""
        s = self.get(key)
        if not s["runs"]:
            raise ValueError("Analyse a run first.")
        run = s["runs"][-1]
        changes = []
        for rec in run["recommendations"]:
            d = decisions.get(rec["id"])
            if not d or run.get('decisions', {}).get(rec['id']):
                continue
            run["decisions"][rec["id"]] = d
            if d == "applied":
                changes.append({"setting": rec["setting"], "ticks": rec["ticks"]})
                if rec.get("test"):
                    s["flags"]["tested"]["downforce_level"] = True
            elif d == "maxed":
                s["maxed"][rec["setting"]] = "up" if rec["ticks"] > 0 else "down"
            elif d == "unavailable" and rec["setting"] not in s["unavailable"]:
                s["unavailable"].append(rec["setting"])
        for ch in manual or []:
            if ch.get("setting") in BY_KEY and int(ch.get("ticks") or 0):
                changes.append({"setting": ch["setting"], "ticks": int(ch["ticks"]), "manual": True})
        for ch in changes:
            s["ticks"][ch["setting"]] = s["ticks"].get(ch["setting"], 0) + ch["ticks"]
            if s["maxed"].get(ch["setting"]) == ("down" if ch["ticks"] > 0 else "up"):
                s["maxed"].pop(ch["setting"])      # moved back off the limit
        s["pending_changes"] = s.get("pending_changes", []) + changes
        return self.save(s)

    @_locked
    def decide_recommendation(self, key, run_id, rec_id, token, decision, *, guard=None):
        """Overlay's idempotent single-card equivalent of the normal setup decisions."""
        if decision not in ('applied', 'skipped', 'maxed', 'unavailable'):
            raise ValueError('Choose Applied, Skipped, Maxed out or Unavailable.')
        if guard is not None and not guard():
            raise ValueError('Garage telemetry changed. No setup decision was saved.')
        session = self.get(key)
        run = (session.get('runs') or [None])[-1]
        rec = next((r for r in (run or {}).get('recommendations', []) if r['id'] == rec_id), None)
        if not run or run.get('id') != run_id or not rec or recommendation_token(session, run, rec) != token:
            raise ValueError('This recommendation changed. Review the current garage checklist.')
        previous = (run.get('decisions') or {}).get(rec_id)
        if previous:
            if previous == decision:
                return {'saved': False, 'decision': previous, 'duplicate': True}
            raise ValueError('This instruction was already reviewed. Review its decision on the Setup engineer page.')
        if guard is not None and not guard():
            raise ValueError('Garage telemetry changed. No setup decision was saved.')
        self.decide(key, {rec_id: decision})
        return {'saved': True, 'decision': decision, 'duplicate': False}

    @_locked
    def submit_changes(self, key, run_id, token, *, guard=None):
        """Seal the reviewed setup for the next run. Never reapply saved decisions."""
        def check_guard():
            if guard is not None and not guard():
                raise ValueError('Garage telemetry changed. Setup was not submitted.')
        check_guard()
        session = self.get(key)
        review = setup_review(session)
        if not review or review['run_id'] != run_id or review['token'] != token:
            raise ValueError('The setup review changed. Review the current checklist before submitting.')
        if not review['can_submit']:
            raise ValueError('Review each setup instruction first: Applied, Skip, Maxed out or Not available.')
        check_guard()
        if review['submitted']:
            return {'saved': False, 'duplicate': True, 'review': review}
        session['runs'][-1]['setup_submission'] = copy.deepcopy({
            'token': token, 'run_id': run_id, 'submitted_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'items': review['items'], 'pending_changes': review['pending_changes'], 'next_run': review['next_run']})
        self.save(session)
        return {'saved': True, 'duplicate': False, 'review': setup_review(session)}


def summary_for_ui(s: dict) -> dict:
    last = s["runs"][-1] if s.get("runs") else None
    return {**{k: v for k, v in s.items() if k != "runs"},
            "setup_review": setup_review(s),
            "runs": [{k: r.get(k) for k in ("id", "source", "analysed_at", "changes_before", "compare", "learned", "checks", "decisions", "feedback", "setup_submission")}
                     | {"best_lap": r["measure"].get("best_lap"), "avg_lap": r["measure"].get("avg_lap"), "laps": r["measure"].get("n_flying"),
                        "fuel_start": (r["measure"].get("fuel") or {}).get("start_l"), "compound": r["measure"].get("compound")} for r in s.get("runs", [])],
            "latest": last, "category_labels": CAT_LABEL}
