"""Desktop app: a localhost server + a chromeless Edge/Chrome window.

    python -m ams2season app            (or the desktop shortcut it can create for you)

Everything lives in the app folder (the working directory when launched):
    ams2season.json        app settings
    recordings/            one folder per recorded session (unchanged format)
    championships/*.db     one SQLite file per championship (config stored inside)
"""
from __future__ import annotations

import collections
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

import numpy as np
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .report import _clean

PRESET_POINTS = {
    "f1": [25, 18, 15, 12, 10, 8, 6, 4, 2, 1],
    "motogp": [25, 20, 16, 13, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
    "indycar": [50, 40, 35, 32, 30, 28, 26, 24, 22, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10],
    "top8": [10, 8, 6, 5, 4, 3, 2, 1],
}
DEFAULT_PORT = 8642
ASSETS = Path(__file__).parent / "assets"


# --------------------------------------------------------------------------- settings
@dataclass
class Settings:
    recordings_dir: str = "recordings"
    championships_dir: str = "championships"
    driver_label: str = ""
    autostart_recorder: bool = True
    talking_points: int = 6
    pinned_awards: list = field(default_factory=list)
    car_icon_overrides: dict = field(default_factory=dict)  # in-game car name -> icon file ("" = no icon)
    car_lengths: dict = field(default_factory=dict)         # icon key -> length in metres
    tyre_windows: dict = field(default_factory=dict)        # car name -> {temp_lo, temp_hi, press_lo, press_hi}
    racing_corners: str = "reduced"                         # braking/throttle consistency: equal / reduced / excluded

    @classmethod
    def load(cls, root: Path) -> "Settings":
        f = root / "ams2season.json"
        if f.exists():
            raw = json.loads(f.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
        s = cls(driver_label=os.environ.get("USERNAME") or os.environ.get("USER") or "")
        s.save(root)
        return s

    def save(self, root: Path) -> None:
        (root / "ams2season.json").write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- recorder service
class RecorderService:
    """Runs the Recorder on a background thread; the UI polls status()."""

    def __init__(self, lib: "Library", reader_factory=None):
        self.lib = lib
        self.available = sys.platform == "win32" or reader_factory is not None
        self.reader_factory = reader_factory
        self.thread: threading.Thread | None = None
        self.stop_event: threading.Event | None = None
        self.rec = None
        self.log = collections.deque(maxlen=200)
        self.error: str | None = None

    def _log(self, line: str) -> None:
        self.log.append(f"{datetime.now():%H:%M:%S} {line}")

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self) -> None:
        if self.running or not self.available:
            return
        from .recorder import Recorder
        s = self.lib.settings
        self.rec = Recorder(self.lib.recordings_dir, label=s.driver_label or None, log=self._log)
        if self.mapper:
            self.rec.hooks["mapper"] = self.mapper.feed
        if self.practice:
            self.rec.hooks["practice"] = self.practice.feed
        if getattr(self, "engineer", None):
            self.rec.hooks["engineer"] = self.engineer.feed
        self.stop_event = threading.Event()
        self.error = None

        def target():
            try:
                if self.reader_factory:
                    reader = self.reader_factory()
                else:
                    from .shm import SharedMemoryReader
                    reader = SharedMemoryReader()
                self.rec.run(reader, self.stop_event)
            except Exception as exc:
                self.error = f"{exc}"
                self._log("[error] recorder stopped: " + traceback.format_exc())

        self.thread = threading.Thread(target=target, name="recorder", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.stop_event:
            self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    # ------------------------------------------------------------- track-edge mapping
    mapper = None
    practice = None

    def start_mapping(self) -> None:
        from .trackmap import LiveMapper
        if not self.running:
            self.start()
        self.mapper = LiveMapper()
        if self.rec:
            self.rec.hooks["mapper"] = self.mapper.feed

    def start_engineer(self, on_run_end) -> None:
        from .engineer.live import EngineerTracker
        if not self.running:
            self.start()
        self.engineer = EngineerTracker(on_run_end)
        if self.rec:
            self.rec.hooks["engineer"] = self.engineer.feed

    def stop_engineer(self) -> None:
        if self.rec:
            self.rec.hooks.pop("engineer", None)
        self.engineer = None

    def start_practice(self, objectives: list, pb_lookup) -> None:
        from .practice import PracticeTracker
        if not self.running:
            self.start()
        self.practice = PracticeTracker(objectives, pb_lookup)
        if self.rec:
            self.rec.hooks["practice"] = self.practice.feed

    def stop_practice(self) -> dict | None:
        st = self.practice.status() if self.practice else None
        if self.rec:
            self.rec.hooks.pop("practice", None)
        self.practice = None
        return st

    def stop_mapping(self) -> None:
        if self.rec:
            self.rec.hooks.pop("mapper", None)
        self.mapper = None

    def status(self) -> dict:
        st = {"available": self.available, "running": self.running, "error": self.error,
              "log": list(self.log)[-40:], "connected": False, "session": None, "completed": []}
        if self.rec:
            st.update(self.rec.status())
        if not self.available:
            st["state"] = "unavailable"
        elif not self.running:
            st["state"] = "off"
        elif st["session"]:
            st["state"] = "recording"
        elif st["connected"]:
            st["state"] = "connected"
        else:
            st["state"] = "waiting"
        return st


# --------------------------------------------------------------------------- library
def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "championship"


class Library:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.settings = Settings.load(self.root)
        self.lock = threading.RLock()
        self._report_cache: dict = {}

    @property
    def recordings_dir(self) -> Path:
        p = Path(self.settings.recordings_dir)
        p = p if p.is_absolute() else self.root / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def champs_dir(self) -> Path:
        p = Path(self.settings.championships_dir)
        p = p if p.is_absolute() else self.root / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ----------------------------------------------------------- recordings
    def recording_path(self, name: str) -> Path:
        """Resolve a recording by folder name, refusing anything outside the recordings folder."""
        p = (self.recordings_dir / unquote(name)).resolve()
        if p.parent != self.recordings_dir.resolve() or not (p / "session.json").exists():
            raise LookupError(f"no recording named {name!r}")
        return p

    def recording_summary(self, path: Path) -> dict | None:
        try:
            m = json.loads((path / "session.json").read_text(encoding="utf-8"))
        except Exception:
            return None
        final = [p for p in m.get("final") or [] if p.get("race_pos", 0) > 0]
        final.sort(key=lambda p: p["race_pos"])
        if m.get("session_type") == "qualify":
            timed = sorted((p for p in m.get("final") or [] if (p.get("fastest_lap") or 0) > 0),
                           key=lambda p: p["fastest_lap"])
            leader = timed[0]["name"] if timed else None
        else:
            leader = final[0]["name"] if final else None
        return {"id": path.name, "type": m.get("session_type"),
                "track_raw": m.get("track_location"), "layout_raw": m.get("track_variation"),
                "track": m.get("track_location_translated") or m.get("track_location"),
                "layout": m.get("track_variation_translated") or m.get("track_variation"),
                "started_at": m.get("started_at"), "duration_s": m.get("duration_s"),
                "cars": len(m.get("final") or []), "leader": leader, "status": m.get("status"),
                "label": m.get("label"), "laps": m.get("laps_in_event"),
                # a race that actually happened: someone completed a lap (a session left before the start has none)
                "raced": m.get("session_type") != "race" or (any((p.get("laps_completed") or 0) > 0 for p in m.get("final") or [])
                                                              and not (path / "analysis" / "no_race.flag").exists()),
                "out_of_range": sorted((m.get("out_of_range") or {}).keys()),
                "names": [p["name"] for p in m.get("final") or []],
                "driver": (m.get("local") or {}).get("name"), "car": (m.get("local") or {}).get("car"),
                "imported_from": (json.loads((path / "import.json").read_text(encoding="utf-8")).get("from") if (path / "import.json").exists() else None)}

    def recordings(self) -> list[dict]:
        from datetime import datetime as _dt
        assigned = self.assignments()
        out = []
        for p in sorted(self.recordings_dir.iterdir(), reverse=True):
            if p.is_dir() and (p / "session.json").exists():
                s = self.recording_summary(p)
                if s:
                    s["assigned"] = assigned.get(str(p.resolve()), [])
                    out.append(s)
        qualis = [r for r in out if r["type"] == "qualify" and r.get("started_at") and r["status"] == "complete"]
        for r in out:  # the qualifying session that came before this race (same track, within 4 hours)
            if r["type"] == "race" and r.get("started_at"):
                t_r = _dt.fromisoformat(r["started_at"])
                cands = [q for q in qualis if q["track"] == r["track"] and q["layout"] == r["layout"]
                         and 0 <= (t_r - _dt.fromisoformat(q["started_at"])).total_seconds() <= 4 * 3600]
                r["quali"] = max(cands, key=lambda q: q["started_at"])["id"] if cands else None
                pair = next((a for a in r['assigned'] if a.get('slot') == 'race'), None)
                if pair is not None:
                    r['quali'] = pair.get('qualify')
        return out

    def assignments(self) -> dict[str, list]:
        from .season import connect
        m = collections.defaultdict(list)
        for db in self._champ_files():
            con = connect(db)
            try:
                cfg = self._cfg(con)
                for r in con.execute("""SELECT s.path, ev.round, s.race_no FROM session s
                                        JOIN event ev ON ev.id=s.event_id"""):
                    m[str(Path(r["path"]).resolve())].append(
                        {"champ": db.stem, "name": cfg.name if cfg else db.stem, "round": r["round"],
                         "race_no": r["race_no"]})
                if con.execute("SELECT 1 FROM sqlite_master WHERE name='weekend'").fetchone():
                    for w in con.execute('SELECT * FROM weekend'):
                        for slot in ('practice1', 'practice2', 'qualify', 'race'):
                            if w[slot]:
                                key = str((self.recordings_dir / w[slot]).resolve())
                                same = next((a for a in m[key] if a['champ'] == db.stem and a['round'] == w['round']), None)
                                if same is not None:
                                    same.update(slot=slot, qualify=w['qualify'])
                                else:
                                    m[key].append({'champ': db.stem, 'name': cfg.name if cfg else db.stem,
                                                   'round': w['round'], 'race_no': 1, 'slot': slot, 'qualify': w['qualify']})
            finally:
                con.close()
        return m

    def name_suggestions(self, champ_id: str | None = None) -> list[dict]:
        """AI names are re-rolled every race, so a name seen in 2+ races is almost certainly a person."""
        counts = collections.Counter()
        labels = set()
        for r in self.recordings():
            if r["type"] == "race":
                counts.update(set(r["names"]))
                if r.get("label"):
                    labels.add(r["label"])
        known = set()
        if champ_id:
            cfg = self.champ_config(champ_id)
            known = cfg.human_names()
        from .race import _norm
        n_races = sum(1 for r in self.recordings() if r["type"] == "race")
        need = max(2, -(-6 * n_races // 10))  # in 60%+ of races: AI names rarely repeat that often
        out = [{"name": n, "races": c} for n, c in counts.most_common() if c >= need and _norm(n) not in known]
        for lab in labels:
            if _norm(lab) not in known and lab not in {o["name"] for o in out}:
                out.append({"name": lab, "races": counts.get(lab, 0), "recorder": True})
        return out

    # ----------------------------------------------------------- championships
    def _champ_files(self) -> list[Path]:
        return sorted(p for p in self.champs_dir.glob("*.db") if not p.name.startswith("."))

    def _db(self, champ_id: str) -> Path:
        p = (self.champs_dir / f"{champ_id}.db").resolve()
        if p.parent != self.champs_dir.resolve() or not p.exists():
            raise LookupError(f"no championship {champ_id!r}")
        return p

    @staticmethod
    def _cfg(con):
        from .season import stored_config
        return stored_config(con)

    def champ_config(self, champ_id: str):
        from .season import connect
        con = connect(self._db(champ_id))
        try:
            return self._cfg(con)
        finally:
            con.close()

    def champ_list(self) -> list[dict]:
        from .season import connect, standings
        out = []
        for db in self._champ_files():
            con = connect(db)
            try:
                cfg = self._cfg(con)
                if cfg is None:
                    continue
                n = con.execute("SELECT COUNT(*) FROM session WHERE type='race'").fetchone()[0]
                leader, top = None, []
                if n:
                    st = standings(con, cfg)
                    if len(st):
                        leader = {"driver": st.driver.iat[0], "points": float(st.points.iat[0])}
                        top = [{"driver": r.driver, "points": float(r.points)} for r in st.head(3).itertuples()]
                nxt = (con.execute("SELECT COALESCE(MAX(round), 0) FROM event").fetchone()[0] or 0) + 1
                out.append({"id": db.stem, "name": cfg.name, "races": n, "drivers": len(cfg.drivers),
                            "leader": leader, "top": top, "next_round": nxt, "updated": db.stat().st_mtime})
            finally:
                con.close()
        out.sort(key=lambda c: -c["updated"])
        return out

    def create_champ(self, body: dict) -> str:
        from .season import SeasonConfig, save_config
        name = (body.get("name") or "").strip() or "New championship"
        cid = _slug(name)
        n = 1
        while (self.champs_dir / f"{cid}.db").exists():
            n += 1
            cid = f"{_slug(name)}-{n}"
        drivers = []
        if body.get("copy_roster_from"):
            drivers = self.champ_config(body["copy_roster_from"]).drivers
        cfg = SeasonConfig(name=name, drivers=drivers, points=dict(PRESET_POINTS), default_points="f1",
                           ai_policy="humans_only", fastest_lap_bonus=1, drop_rounds=0, points_for_dnf=False)
        save_config(self.champs_dir / f"{cid}.db", cfg)
        return cid

    def update_champ(self, champ_id: str, body: dict) -> dict:
        from .season import SeasonConfig, reingest_all, save_config
        db = self._db(champ_id)
        old = self.champ_config(champ_id)
        raw = json.loads(old.to_json())
        for k in ("name", "drivers", "points", "default_points", "ai_policy", "fastest_lap_bonus",
                  "drop_rounds", "points_for_dnf", "corners", "pass_detection", "teams", "team_count", "team_colors_for_drivers",
                  "practice_points", "practice_awards", "livery_ai", "car_class"):
            if k in body:
                raw[k] = body[k]
        raw["drivers"] = _clean_drivers(raw.get("drivers") or [])
        if not isinstance(raw.get('car_class', ''), str):
            raise ValueError('Championship car class must be a class name.')
        raw['car_class'] = raw.get('car_class', '').strip()
        from .identities import validate_roster
        validate_roster(raw['drivers'])
        raw["teams"] = _clean_teams(raw.get("teams") or [], {d["key"] for d in raw["drivers"]})
        raw["team_count"] = max(0, int(raw.get("team_count") or 0))
        cfg = SeasonConfig(**raw)
        needs_reanalysis = (json.dumps(cfg.drivers, sort_keys=True) != json.dumps(old.drivers, sort_keys=True)
                            or cfg.corners != old.corners or cfg.pass_detection != old.pass_detection
                            or cfg.livery_ai != old.livery_ai)
        practice_changed = (cfg.practice_points != old.practice_points or sorted(cfg.practice_awards) != sorted(old.practice_awards))
        with self.lock:
            problems = reingest_all(db, cfg) if needs_reanalysis else (save_config(db, cfg) or [])
            if needs_reanalysis or practice_changed:
                from .season import refile_practice
                refile_practice(db, cfg)
        self._report_cache.clear()
        return {"reanalysed": needs_reanalysis, "problems": problems}

    def delete_champ(self, champ_id: str) -> None:
        db = self._db(champ_id)
        db.rename(db.with_name(f".deleted-{datetime.now():%Y%m%d-%H%M%S}-{db.name}"))

    def _refresh_champ_analysis(self, champ_id: str) -> list[str]:
        from .season import refresh_analysis
        db = self._db(champ_id)
        with self.lock:
            key = ("analysis-refresh", str(db), db.stat().st_mtime_ns)
            if key in self._report_cache:
                return self._report_cache[key]
            before = db.stat().st_mtime_ns
            problems = refresh_analysis(db, self.champ_config(champ_id))
            if db.stat().st_mtime_ns != before:
                self._report_cache.clear()
            self._report_cache[("analysis-refresh", str(db), db.stat().st_mtime_ns)] = problems
            return problems

    def champ_detail(self, champ_id: str) -> dict:
        from .awards import season_awards
        from .season import (connect, driver_colors, driver_stats, head_to_head, progression, rounds_summary,
                             season_cars_and_style, standings, team_standings, teammate_battles)
        analysis_problems = self._refresh_champ_analysis(champ_id)
        db = self._db(champ_id)
        con = connect(db)
        try:
            cfg = self._cfg(con)
            rounds = rounds_summary(con, cfg)
            from .practice_points import AWARDS as _PA
            from .season import practice_sessions
            data = {"id": champ_id, "config": json.loads(cfg.to_json()), "rounds": rounds, "analysis_problems": analysis_problems,
                    "practice": practice_sessions(con), "practice_catalog": [{"key": k, "label": l, "about": a} for k, l, a in _PA],
                    "standings": {}, "progression": {}, "drivers": [], "h2h": None, "awards": [],
                    "talking_points": int(self.settings.talking_points or 6),
                    "corrections": [dict(r) for r in con.execute("SELECT * FROM correction ORDER BY round, id")],
                    "next_round": (max((r["round"] for r in rounds), default=0) + 1)}
            if rounds or data["practice"]:
                for pol in ("humans_only", "full_field"):
                    st = standings(con, cfg, policy=pol)
                    data["standings"][pol] = {"columns": list(st.columns), "rows": st.where(st.notna(), None).to_dict("records")}
                    data["progression"][pol] = progression(con, cfg, policy=pol) if rounds else {}
                ds = driver_stats(con, cfg, include_ai=True)
                data["drivers"] = ds.to_dict("records")
                ahead, passes = head_to_head(con, cfg)
                data["h2h"] = {"names": list(ahead.index), "ahead": ahead.values.tolist(),
                               "passes": passes.values.tolist()}
                data["awards"] = season_awards(con, cfg, self.settings.pinned_awards or [])
                if cfg.teams:
                    data["team_standings"] = {pol: team_standings(con, cfg, policy=pol).to_dict("records") for pol in ("humans_only", "full_field")}
                    data["teammates"] = teammate_battles(con, cfg)
                data["tyre_care"] = self.tyre_care(con, cfg)
                data.update({"season_" + k: v for k, v in season_cars_and_style(con, cfg).items()})
            dc = driver_colors(cfg)
            data["colors"] = {d.get("display", d["key"]): dc[d["key"]] for d in cfg.drivers}
            tm = {k: t for t in cfg.teams for k in t.get("members", [])}
            data["driver_team"] = {d.get("display", d["key"]): tm[d["key"]]["key"] for d in cfg.drivers if d["key"] in tm}
            from .weekends import weekends
            data["weekends"] = weekends(self, champ_id)
            return _clean(data)
        finally:
            con.close()

    def add_round(self, champ_id: str, body: dict) -> dict:
        from .season import connect, file_practice, ingest
        db = self._db(champ_id)
        path = self.recording_path(body["recording"])
        cfg = self.champ_config(champ_id)
        rnd = int(body["round"]) if body.get("round") else None
        if (self.recording_summary(path) or {}).get("type") == "practice":   # practice: awards, not a race result
            if rnd is None:
                con = connect(db)
                try:
                    last = con.execute("SELECT MAX(round) FROM event").fetchone()[0] or 0
                finally:
                    con.close()
                rnd = last + 1
            with self.lock:
                info = file_practice(db, cfg, path, rnd)
            self._report_cache.clear()
            return {"practice": True, **info}
        with self.lock:
            info = ingest(db, cfg, path, round_no=rnd, race_no=int(body.get("race_no") or 1))
        info.pop("analysis", None)
        return info

    def remove_round(self, champ_id: str, round_no: int, race_no: int) -> None:
        from .season import remove_round
        with self.lock:
            remove_round(self._db(champ_id), round_no, race_no)
        self._report_cache.clear()

    def add_correction(self, champ_id: str, body: dict) -> None:
        from .season import add_correction
        v = body.get("value")
        add_correction(self._db(champ_id), int(body["round"]), body["driver"], body["kind"],
                       float(v) if v not in (None, "") else None, body.get("note") or None,
                       race_no=int(body.get("race_no") or 1))

    def delete_correction(self, champ_id: str, cid: int) -> None:
        from .season import connect
        con = connect(self._db(champ_id))
        try:
            with con:
                con.execute("DELETE FROM correction WHERE id=?", (cid,))
        finally:
            con.close()

    # ----------------------------------------------------------- race analysis / report / replay
    def _analysis(self, recording: str, champ_id: str | None):
        """Analyse once per (recording, championship config); shared by the report and the replay."""
        from .derive import load_session
        from .race import _norm, analyze_race
        path = self.recording_path(recording)
        frames = path / "frames.parquet"
        stamp = frames.stat().st_mtime if frames.exists() else 0
        cfg = self.champ_config(champ_id) if champ_id else self._fallback_config()
        from .identities import project_session, revision
        key = (str(path), champ_id, stamp, cfg.to_json() if cfg else None, self.settings.racing_corners,
               revision(path, cfg if champ_id else None))
        hit = self._report_cache.get(("analysis",) + key)
        if hit:
            return hit
        humans = corners = params = None
        meta = load_session(path).meta
        if cfg:
            humans = cfg.human_names()
            corners = cfg.corners_for(meta["track_location"], meta["track_variation"])
            params = cfg.pass_params()
        corners = self.track_corners(meta["track_location"], meta["track_variation"]) or corners  # your own turns win
        try:
            # Standalone reports borrow human aliases only; fictional identity is championship-scoped.
            session = project_session(path, cfg if champ_id else None)
            ra = analyze_race(session, humans=humans, corners_override=corners, params=params, racing_mode=self.settings.racing_corners)
            original = session.meta.get('_recorded_names', {})
            ra.entrants['recorded_name'] = ra.entrants.name.map(lambda name: original.get(name, name))
            ra.classification['recorded_name'] = ra.classification.name.map(lambda name: original.get(name, name))
        except ValueError as exc:
            from .race import NO_RACE
            if str(exc) == NO_RACE:   # remember it, so the home page stops offering this recording
                try:
                    (path / "analysis").mkdir(exist_ok=True)
                    (path / "analysis" / "no_race.flag").write_text("1", encoding="utf-8")
                except Exception:
                    pass
            raise
        colors = None
        if cfg:
            from .season import driver_colors
            dc, amap = driver_colors(cfg), cfg.alias_map()
            colors = {n: dc[amap[_norm(n)]] for n in ra.entrants.name if _norm(n) in amap and amap[_norm(n)] in dc}
        if len(self._report_cache) > 24:
            self._report_cache.clear()
        self._report_cache[("analysis",) + key] = (ra, colors)
        return ra, colors

    def race_report(self, recording: str, champ_id: str | None) -> str:
        from .race import NO_RACE
        from .report import race_report_html
        try:
            ra, colors = self._analysis(recording, champ_id)
        except ValueError as exc:
            if str(exc) != NO_RACE:
                raise
            import html as _h   # shown inside the race page, so a readable note rather than a raw error
            return ("<!doctype html><meta charset='utf-8'><body style='font:15px/1.5 system-ui,sans-serif;padding:40px;color:#8A93A3;"
                    "background:transparent'><h2 style='margin:0 0 8px;color:inherit'>No race to show</h2><p>" + _h.escape(NO_RACE) + "</p></body>")
        s = self.settings
        t_samples, t_width, _ = self.track_file(ra.session.meta["track_location"], ra.session.meta["track_variation"])
        return race_report_html(ra, colors, top_n=int(s.talking_points or 6), pinned=s.pinned_awards or [],
                                embedded=True, track_samples=t_samples, track_width=t_width)

    @property
    def icons_dir(self) -> Path:
        p = self.root / "car_icons"
        p.mkdir(exist_ok=True)
        return p

    def icons_for(self, cars) -> dict:
        """In-game car name -> {"url", "length", "length_source"} for every car that has an icon."""
        from .caricons import available, length_for, match
        icons, st = available(self.icons_dir), self.settings
        out = {}
        for car in set(cars):
            key = match(car, icons, st.car_icon_overrides)
            if key in icons:
                length, src = length_for(key, st.car_lengths)
                out[car] = {"url": icons[key]["url"], "length": length, "length_source": src, "key": key}
        return out

    def icon_file(self, name: str) -> Path:
        from .caricons import BUILTIN_DIR
        for folder in (self.icons_dir, BUILTIN_DIR):  # your own icons first, then the built-in set
            f = (folder / name).resolve()
            if f.parent == folder.resolve() and f.is_file():
                return f
        raise LookupError("no such icon")

    def car_icon_page(self) -> dict:
        from .caricons import CAR_SPECS, available, length_for, match, seen_cars
        icons, st = available(self.icons_dir), self.settings
        cars = seen_cars(self.recordings_dir)
        for c in cars:
            key = match(c["car"], icons, st.car_icon_overrides)
            c["icon"] = icons[key]["file"] if key in icons else None
            c["how"] = "chosen" if c["car"] in st.car_icon_overrides else ("auto" if c["icon"] else "none")
            c["length"] = length_for(key, st.car_lengths)[0] if key in icons else None
        listing = []
        for key, info in icons.items():
            length, src = length_for(key, st.car_lengths)
            listing.append({**info, "key": key, "length": length, "length_source": src or "unknown",
                            "default_length": CAR_SPECS.get(key, (None,))[0],
                            "cars": [c["car"] for c in cars if c["icon"] == info["file"]]})
        return {"icons": sorted(listing, key=lambda x: x["file"].lower()), "cars": cars}

    IMPORT_FILES = ("session.json", "frames.parquet", "local.parquet", "events.jsonl", "livery_assignments.json")

    def import_recording(self, body: dict) -> dict:
        """A friend's recording, sent as a zip or as a folder's files: copied into your recordings so their car's
        telemetry shows up beside yours (Brake & throttle compares everyone who recorded the same session).
        Only the recording files are written, by their plain names, so nothing outside the recordings folder can
        be touched."""
        import base64
        import io
        import re as _re
        import zipfile
        files = {}
        if body.get("zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(base64.b64decode(body["zip"])))
            except Exception:
                raise ValueError("That file isn't a zip that can be opened.")
            for info in z.infolist():
                if not info.is_dir() and info.filename.replace("\\", "/").rsplit("/", 1)[-1] in self.IMPORT_FILES:
                    files[info.filename.replace("\\", "/")] = z.read(info)
        for f in body.get("files") or []:
            pth = str(f.get("path") or "").replace("\\", "/")
            if pth.rsplit("/", 1)[-1] in self.IMPORT_FILES:
                files[pth] = base64.b64decode(f["data"])
        roots = sorted({p.rsplit("/", 1)[0] if "/" in p else "" for p in files if p.endswith("session.json")})
        if not roots:
            raise ValueError("No recording found: a recording is a folder with a session.json inside.")
        out = []
        for root in roots:
            pref = root + "/" if root else ""
            mine = {p[len(pref):]: b for p, b in files.items() if p.startswith(pref) and "/" not in p[len(pref):]}
            try:
                meta = json.loads(mine["session.json"].decode("utf-8"))
            except Exception:
                raise ValueError("That recording's session.json can't be read.")
            if not meta.get("session_type") or not meta.get("track_location") or "frames.parquet" not in mine:
                raise ValueError("That doesn't look like a complete recording (session details or positions are missing).")
            if 'livery_assignments.json' in mine:
                from .identities import validate_facts
                validate_facts(json.loads(mine['livery_assignments.json'].decode('utf-8')))
            who = (meta.get("local") or {}).get("name") or meta.get("label") or "friend"
            base = root.rsplit("/", 1)[-1] if root else ""
            if not _re.fullmatch(r"[\w.-]+", base or "-"):
                base = ""
            if not base:
                stamp = str(meta.get("started_at") or "").replace("-", "").replace(":", "").replace("T", "-")[:15]
                base = f"{stamp}_{meta.get('track_location')}_{meta['session_type']}"
            base = _re.sub(r"[^\w.-]+", "_", base)
            dest = self.recordings_dir / base
            if dest.exists():
                try:
                    old = json.loads((dest / "session.json").read_text(encoding="utf-8"))
                except Exception:
                    old = {}
                if old.get("started_at") == meta.get("started_at") and (old.get("local") or {}).get("name") == who:
                    out.append({"id": dest.name, "driver": who, "already": True})
                    continue
                dest = self.recordings_dir / f"{base}_{_re.sub(r'[^\w-]+', '_', who)}"
                n = 2
                while dest.exists():
                    dest = self.recordings_dir / f"{base}_{_re.sub(r'[^\w-]+', '_', who)}_{n}"
                    n += 1
            dest.mkdir(parents=True)
            for name, data in mine.items():
                if name in self.IMPORT_FILES:
                    (dest / name).write_bytes(data)
            (dest / "import.json").write_text(json.dumps({"from": who, "imported_at": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")
            out.append({"id": dest.name, "driver": who, "type": meta["session_type"],
                        "track": meta.get("track_location_translated") or meta.get("track_location"), "already": False})
        self._report_cache.clear()
        return {"imported": out}

    def _siblings(self, path: Path, kind: str, window_s: float) -> list[Path]:
        """Other recordings of the same session (friends' PCs): same track and session type, started within the
        window. Friends in other time zones are hours apart on the clock, so a whole-hour difference also counts
        when the same drivers appear in both."""
        me = self.recording_summary(path)
        if not me or not me.get("started_at"):
            return []
        from datetime import datetime as _dt
        t_me = _dt.fromisoformat(me["started_at"])
        out = []
        for p in self.recordings_dir.iterdir():
            if p == path or not (p / "session.json").exists():
                continue
            o = self.recording_summary(p)
            if not o or o["type"] != kind or o["track"] != me["track"] or o["layout"] != me["layout"] or not o.get("started_at"):
                continue
            dt = abs((_dt.fromisoformat(o["started_at"]) - t_me).total_seconds())
            off_hour = min(dt % 3600, 3600 - dt % 3600)
            shared = len(set(me.get("names") or []) & set(o.get("names") or []))
            if dt <= window_s or (dt <= 14 * 3600 and off_hour <= window_s and shared >= 2):
                out.append(p)
        return out

    def personal_best(self, track, layout, car, driver):
        """Fastest lap the game recorded for this driver, car and layout in any earlier session."""
        best = None
        for p in self.recordings_dir.iterdir():
            f = p / "session.json"
            if not f.exists():
                continue
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if m.get("track_location") != track or m.get("track_variation") != layout:
                continue
            for x in m.get("final") or []:
                if x.get("name") == driver and (not car or x.get("car") == car) and (x.get("fastest_lap") or 0) > 0:
                    best = x["fastest_lap"] if best is None else min(best, x["fastest_lap"])
        return best

    TECHNIQUE_VERSION = 8  # shift-aware throttle shapes and modulated/flat-out corners

    def technique_cached(self, path: Path) -> dict:
        from .report import _clean
        from .technique import technique_report
        meta = self.recording_summary(path)
        stamp = max(((path / f).stat().st_mtime for f in ("frames.parquet", "local.parquet") if (path / f).exists()), default=0)
        stamp = f"{stamp}|{json.dumps(self.track_corners(meta['track_raw'], meta['layout_raw']))}|{self.settings.racing_corners}"
        cache = path / "analysis" / "technique.json"
        if cache.exists():
            try:
                c = json.loads(cache.read_text(encoding="utf-8"))
                if c.get("_stamp") == stamp and c.get("_v") == self.TECHNIQUE_VERSION:
                    return c
            except Exception:
                pass
        rep = _clean(technique_report(path, self.track_corners(meta["track_raw"], meta["layout_raw"]), mode=self.settings.racing_corners))
        rep.update({"_stamp": stamp, "_v": self.TECHNIQUE_VERSION})
        try:
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps(rep), encoding="utf-8")
        except Exception:
            pass
        return rep

    def technique(self, recording: str, champ_id: str | None, pace_reference: str = 'fastest') -> dict:
        from .derive import load_session
        from .pace_compare import VERSION as PACE_VERSION, lap_catalog, pace_comparison
        from .report import _clean
        if pace_reference not in ('fastest', 'same_car', 'leader', 'pole'):
            raise ValueError('Unknown pace reference.')
        path = self.recording_path(recording)
        meta = self.recording_summary(path)
        reports = [self.technique_cached(path)]
        for sib in self._siblings(path, meta["type"], 20 * 60):  # friends' recordings of the same session
            r = self.technique_cached(sib)
            if r.get("available") and r.get("driver") not in {x.get("driver") for x in reports}:
                reports.append(r)
        cfg = self.champ_config(champ_id) if champ_id else self._fallback_config()
        colors = {}
        if cfg:
            from .race import _norm
            from .season import driver_colors
            dc, amap = driver_colors(cfg), cfg.alias_map()
            colors = {r["driver"]: dc.get(amap.get(_norm(r.get("driver") or ""))) for r in reports if r.get("driver")}
        race = None
        if meta["type"] == "race":
            race = {"id": recording, "champ": champ_id}
        elif meta["type"] == "qualify":
            race = self.race_for_quali(recording)
        t_samples, t_width, t_stamp = self.track_file(meta['track_raw'], meta['layout_raw'])
        references = [{'key': 'fastest', 'label': 'Fastest recorded lap'},
                      {'key': 'same_car', 'label': 'Fastest in the same car'}]
        paired_quali = None
        if meta['type'] == 'race':
            references.append({'key': 'leader', 'label': "Race winner's best lap"})
            rec = next((r for r in self.recordings() if r['id'] == recording), {})
            paired_quali = rec.get('quali')
            if paired_quali:
                references.append({'key': 'pole', 'label': 'Recorded qualifying pole'})
        enriched = []
        for rep in reports:
            report = dict(rep)
            if rep.get('available'):
                src = self.recording_path(rep.get('folder') or recording)
                stamp = tuple((src / f).stat().st_mtime_ns if (src / f).exists() else 0 for f in ('frames.parquet', 'local.parquet', 'session.json'))
                qpath = self.recording_path(paired_quali) if paired_quali else None
                qstamp = tuple((qpath / f).stat().st_mtime_ns if (qpath / f).exists() else 0
                               for f in ('frames.parquet', 'local.parquet', 'session.json')) if qpath else None
                from .identities import revision
                key = ('pace-comparison', PACE_VERSION, str(src), stamp, t_stamp, paired_quali, qstamp, pace_reference,
                       revision(path, cfg if champ_id else None),
                       json.dumps(self.track_corners(meta['track_raw'], meta['layout_raw'])), self.TECHNIQUE_VERSION,
                       cfg.to_json() if cfg else None)
                comparison = self._report_cache.get(key)
                if comparison is None:
                    session = load_session(src)
                    L, catalog = lap_catalog(session)
                    corners = [{'name': c['corner'], 'apex': c['apex']} for c in rep.get('corners', [])]
                    # Direction/radius come from the same measured track shape.
                    from .technique import corners_from_laps, recording_laps
                    _, driving_laps, _ = recording_laps(session)
                    mine = catalog.get(rep.get('driver'))
                    if mine:
                        corners = corners_from_laps(driving_laps, L, (mine['grid'], mine['x'], mine['z']),
                                                    self.track_corners(meta['track_raw'], meta['layout_raw']))
                    reference_session, reference_name = None, None
                    if pace_reference == 'pole':
                        if paired_quali:
                            try:
                                reference_session = load_session(qpath)
                            except (OSError, ValueError, KeyError) as exc:
                                comparison = {'available': False, 'reason': f'Paired qualifying telemetry is unavailable: {exc}'}
                        else:
                            comparison = {'available': False, 'reason': 'No qualifying recording is paired with this race.'}
                    elif pace_reference == 'leader':
                        if meta['type'] == 'race':
                            leader = self._analysis(recording, champ_id)[0]
                            winner = str(leader.classification.iloc[0]['name'])
                            reference_name = leader.session.meta.get('_recorded_names', {}).get(winner, winner)
                        else:
                            comparison = {'available': False, 'reason': 'A race-winner reference requires a race recording.'}
                    if comparison is None:
                        try:
                            comparison = _clean(pace_comparison(session, rep.get('driver'), corners, reference_session, reference_name,
                                                               pace_reference, t_samples, t_width, catalogs=(L, catalog)), digits=None)
                        except (OSError, ValueError, KeyError, IndexError) as exc:
                            comparison = {'available': False, 'reason': f'Pace comparison unavailable: {exc}'}
                    self._report_cache[key] = comparison
                report['pace_comparison'] = comparison
            enriched.append(report)
        return {"recording": recording, "type": meta["type"], "track": meta["track"], "layout": meta["layout"],
                "started_at": meta["started_at"], "drivers": enriched, "colors": colors, "race": race,
                'pace_reference': pace_reference, 'pace_references': references}

    def tyre_care(self, con, cfg, only_round=None, only_race=None) -> list[dict]:
        """Season tyre care for every human who recorded their own races (wear relative to the others
        in the same race, plus lock-ups and wheelspin per lap)."""
        from .race import _norm
        amap, disp = cfg.alias_map(), {d["key"]: d.get("display", d["key"]) for d in cfg.drivers}
        rows = []
        for r in con.execute("SELECT s.path, ev.round, s.race_no FROM session s JOIN event ev ON ev.id=s.event_id WHERE s.type='race'"):
            if only_round is not None and (r['round'], r['race_no']) != (only_round, only_race):
                continue
            p = Path(r["path"])
            if not p.exists():
                continue
            per = []
            for rec in [p] + self._siblings(p, "race", 20 * 60):
                t = self.technique_cached(rec)
                ty = t.get("tyres") if t.get("available") else None
                key = amap.get(_norm(t.get("driver") or ""))
                if ty and key and key not in {x["key"] for x in per}:
                    per.append({"key": key, "wear": ty["wear_per_lap_avg"] if ty["wear_enabled"] else None,
                                "lock": ty["lockups_per_lap"], "spin": ty["wheelspin_per_lap"]})
            wears = [x["wear"] for x in per if x["wear"]]
            med = float(np.median(wears)) if wears else None
            for x in per:
                rows.append({**x, "round": r["round"], "wear_index": (x["wear"] / med) if (med and x["wear"]) else None})
        out = []
        for key in {x["key"] for x in rows}:
            mine = [x for x in rows if x["key"] == key]
            wi = [x["wear_index"] for x in mine if x["wear_index"]]
            lock = float(np.mean([x["lock"] for x in mine])); spin = float(np.mean([x["spin"] for x in mine]))
            wix = float(np.mean(wi)) if wi else None
            score = 100 - (60 * (wix - 1) if wix else 0) - 15 * lock - 10 * spin
            out.append({"driver": disp.get(key, key), "races": len(mine), "wear_vs_field": round((wix - 1) * 100, 1) if wix else None,
                        "lockups_per_lap": round(lock, 2), "wheelspin_per_lap": round(spin, 2),
                        "score": int(max(0, min(100, round(score))))})
        return sorted(out, key=lambda x: -x["score"])

    def track_file(self, track: str, layout: str):
        """(edge points, road width, file timestamp) from this track's saved map, if any."""
        from .trackmap import load_track_file, load_track_samples, track_file_path
        p = track_file_path(self.root, track, layout)
        if not p.exists():
            return None, None, 0
        return load_track_samples(self.root, track, layout), load_track_file(self.root, track, layout).get("width"), p.stat().st_mtime

    def practice_laps(self, recording: str) -> dict:
        """Your own clean laps from a session, shaped like qualifying so the same view can replay them."""
        from .quali import analyze_practice, quali_data
        path = self.recording_path(recording)
        meta = self.recording_summary(path)
        t_samples, t_width, t_stamp = self.track_file(meta["track_raw"], meta["layout_raw"])
        stamp = (path / "frames.parquet").stat().st_mtime if (path / "frames.parquet").exists() else 0
        key = ("practice", str(path), stamp, t_stamp)
        if key in self._report_cache:
            return self._report_cache[key]
        qa = analyze_practice(path, track_samples=t_samples, track_width=t_width,
                              corners_override=self.track_corners(meta["track_raw"], meta["layout_raw"]))
        icons = self.icons_for(qa.classification.car if len(qa.classification) else [])
        data = quali_data(qa, icons=icons)
        data.update({"practice": True, "driver": qa.practice_driver, "merged_recordings": [], "session_type": meta["type"],
                     "track_key": {"track": meta["track_raw"], "layout": meta["layout_raw"]}, "race": None})
        self._report_cache[key] = data
        return data

    TYRES_VERSION = 5  # corrected lap timing and race cooldown exclusion

    def tyres(self, recording: str) -> dict:
        """Full tyre analysis for the recording car, cached beside the recording."""
        from .report import _clean
        from .tyres import DEFAULT_WINDOW, tyre_analysis
        path = self.recording_path(recording)
        meta = self.recording_summary(path)
        car = (meta.get("local") or {}).get("car") if isinstance(meta.get("local"), dict) else None
        if car is None:
            from .derive import load_session
            car = (load_session(path).meta.get("local") or {}).get("car")
        window = {**DEFAULT_WINDOW, **self.settings.tyre_windows.get(car or "", {})}
        corners = self.track_corners(meta["track_raw"], meta["layout_raw"])
        stamp = max(((path / f).stat().st_mtime for f in ("frames.parquet", "local.parquet") if (path / f).exists()), default=0)
        stamp = f"{stamp}|{json.dumps(window, sort_keys=True)}|{json.dumps(corners)}|{self.TYRES_VERSION}"
        cache = path / "analysis" / "tyres.json"
        if cache.exists():
            try:
                c = json.loads(cache.read_text(encoding="utf-8"))
                if c.get("_stamp") == stamp:
                    return c
            except Exception:
                pass
        rep = _clean(tyre_analysis(path, window, corners))
        rep.update({"_stamp": stamp, "car": car, "recording": recording, "type": meta["type"], "track": meta["track"],
                    "layout": meta["layout"], "started_at": meta["started_at"], "default_window": DEFAULT_WINDOW,
                    "race": {"id": recording, "champ": None} if meta["type"] == "race" else self.race_for_quali(recording) if meta["type"] == "qualify" else None})
        try:
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps(rep), encoding="utf-8")
        except Exception:
            pass
        return rep

    def track_corners(self, track: str, layout: str) -> list | None:
        """Turns you placed yourself on the Track maps page, if any."""
        from .trackmap import load_track_file
        return (load_track_file(self.root, track, layout) or {}).get("corners") or None

    def race_pace_page(self, recording: str, champ_id: str | None) -> dict:
        from .metrics import race_pace
        ra, colors = self._analysis(recording, champ_id)[:2]
        is_ai = dict(zip(ra.entrants.name, ra.entrants.is_ai.astype(bool)))
        data = race_pace(ra.laps, is_ai)
        rec = next((r for r in self.recordings() if r["id"] == recording), {})
        quali = {}
        if rec.get("quali"):
            try:
                q = self.quali(rec["quali"], champ_id)
                quali = {d["name"]: d["best"] for d in q["drivers"] if d.get("best")}
            except Exception:
                quali = {}
        colors = self._colors_for(ra, colors)
        for d in data["drivers"]:
            d["quali_best"] = quali.get(d["name"])
            d["color"] = colors.get(d["name"])
        meta = ra.session.meta
        data.update({"meta": {"track": meta.get("track_location_translated") or meta.get("track_location"),
                              "started_at": meta.get("started_at")}, "quali_recording": rec.get("quali"),
                     "classification": [r.name for r in ra.classification.itertuples()]})
        data["awards"] = self._race_awards(ra, "pace")
        return data

    @staticmethod
    def _colors_for(ra, colors: dict | None) -> dict:
        """Driver colours: the championship's when there is one, otherwise the report's (humans in finishing order)."""
        from .report import HUMAN_COLORS
        st = ra.stats.set_index("name")
        humans = [n for n in ra.classification.name if n in st.index and not st.loc[n, "is_ai"]]
        out = {n: HUMAN_COLORS[i % len(HUMAN_COLORS)] for i, n in enumerate(humans)}
        out.update({k: v for k, v in (colors or {}).items() if v})
        return out

    def _race_meta(self, ra) -> dict:
        m = ra.session.meta
        return {"track": m.get("track_location_translated") or m.get("track_location"), "started_at": m.get("started_at")}

    def _race_awards(self, ra, page: str | None = None) -> list:
        """The race's awards, worked out once per analysis; with a page, only the ones that belong there."""
        if getattr(ra, "_awards_cache", None) is None:
            from .awards import race_awards
            ra._awards_cache = race_awards(ra, self.settings.pinned_awards or [])
        return [a for a in ra._awards_cache if page is None or a.get("page") == page]

    def style_page(self, recording: str, champ_id: str | None) -> dict:
        """Driving style for every car: braking and throttle consistency (three ways of counting racing corners),
        track usage, distance from the apex, and the share of corners spent racing."""
        ra, colors = self._analysis(recording, champ_id)
        cols = self._colors_for(ra, colors)
        st = ra.stats
        keep = ["name", "is_ai", "brake_consistency", "brake_point_sd", "throttle_consistency", "throttle_point_sd", "throttle_rating_source", "track_usage", "apex_gap_m", "exit_gap_m", "track_edge_source", "racing_share",
                *[f"{k}_consistency_{m}" for k in ("brake", "throttle") for m in ("equal", "reduced", "excluded")]]
        order = {r.name: i + 1 for i, r in enumerate(ra.classification.itertuples())}
        rows = []
        for r in st[[c for c in keep if c in st.columns]].to_dict("records"):
            r = {k: (None if isinstance(v, float) and v != v else v) for k, v in r.items()}
            r.update({"pos": order.get(r["name"]), "color": cols.get(r["name"]), "is_ai": bool(r.get("is_ai"))})
            rows.append(r)
        rows.sort(key=lambda r: r["pos"] or 99)
        return {"meta": self._race_meta(ra), "drivers": rows, "racing_mode": getattr(ra, "racing_mode", "reduced"),
                "awards": self._race_awards(ra, "style")}

    def errors_page(self, recording: str, champ_id: str | None) -> dict:
        from .errors import race_errors
        from .report import _track
        ra, colors = self._analysis(recording, champ_id)
        meta = self.recording_summary(self.recording_path(recording))
        t_samples, t_width, _ = self.track_file(meta["track_raw"], meta["layout_raw"])
        data = race_errors(ra)
        cols = self._colors_for(ra, colors)
        for d in data["drivers"]:
            d["color"] = cols.get(d["name"])
        data.update({"meta": self._race_meta(ra), "track": _track(ra, t_samples, t_width), "colors": cols, "awards": self._race_awards(ra, "errors")})
        return data

    def overtakes_page(self, recording: str, champ_id: str | None) -> dict:
        from .overtakes import overtaking
        from .report import report_data
        ra, colors = self._analysis(recording, champ_id)
        meta = self.recording_summary(self.recording_path(recording))
        t_samples, t_width, _ = self.track_file(meta["track_raw"], meta["layout_raw"])
        cols = self._colors_for(ra, colors)
        rd = report_data(ra, colors=cols, track_samples=t_samples, track_width=t_width)
        data = overtaking(ra)
        for d in data["drivers"]:
            d["color"] = cols.get(d["name"])
        data.update({"meta": self._race_meta(ra), "passes": rd["passes"], "track": rd["track"], "colors": cols, "awards": self._race_awards(ra, "overtakes"),
                     "battles": rd.get("battles", [])})
        return data

    def driver_profiles(self, cid: str) -> dict:
        from .profiles import build, VERSION
        db = self._db(cid)
        self._refresh_champ_analysis(cid)
        key = ("profiles", VERSION, str(db), db.stat().st_mtime_ns)
        if key in self._report_cache:
            return self._report_cache[key]
        with self.lock:
            out = build(self, cid)
        self._report_cache[("profiles", VERSION, str(db), db.stat().st_mtime_ns)] = out
        return out

    def race_cars_page(self, recording: str, champ_id: str | None) -> dict:
        from .report import _car_extra, _car_rows
        ra = self._analysis(recording, champ_id)[0]
        meta = ra.session.meta
        return {"awards": self._race_awards(ra, "cars"), "cars": _car_rows(ra), "car_extra": _car_extra(ra),
                "meta": {"track": meta.get("track_location_translated") or meta.get("track_location"), "started_at": meta.get("started_at")}}

    def track_turns(self, key: str) -> dict:
        from .derive import curvature_profile, detect_corners
        from .trackmap import track_outline
        p = (self.root / "tracks" / f"{key}.json").resolve()
        if p.parent != (self.root / "tracks").resolve() or not p.exists():
            raise LookupError("no such track map")
        data = json.loads(p.read_text(encoding="utf-8"))
        rows = [(ld, x, z, side) for side in ("left", "right") for ld, x, z in data.get("samples", {}).get(side, [])]
        import pandas as pd
        samples = pd.DataFrame(rows, columns=["lap_dist", "x", "z", "side"])
        L = float(data.get("length") or (samples.lap_dist.max() if len(samples) else 0))
        if not len(samples) or L <= 0:
            raise ValueError("This track map has no mapped edges yet.")
        out = track_outline(samples, L)
        detected = self._turns_from_recordings(data.get("track"), data.get("layout"))
        cen = np.array(out["centre"])
        if not detected and len(cen) > 50:  # fallback: a well-smoothed centre line (raw mapping points wiggle)
            k = 15
            sm = lambda a: np.convolve(np.r_[a[-k:], a, a[:k]], np.ones(k) / k, "same")[k:-k]
            cx, cz = cen[:, 1], cen[:, 2]
            for _ in range(4):
                cx, cz = sm(cx), sm(cz)
            kap = curvature_profile(cen[:, 0], cx, cz, L)
            if kap is not None:
                detected = [{"name": c["name"], "apex": c["apex"]} for c in detect_corners(np.full(len(kap), 30.0), curvature=kap)]
        out.update({"key": key, "track": data.get("track"), "layout": data.get("layout"), "length": L,
                    "corners": data.get("corners") or detected, "custom": bool(data.get("corners")), "detected": detected})
        return out

    def _turns_from_recordings(self, track: str | None, layout: str | None) -> list:
        """The turns your own analyses found at this track (newest race, else qualifying, else practice)."""
        recs = [r for r in self.recordings() if r.get("track_raw") == track and r.get("layout_raw") == layout and r.get("status") == "complete"]
        for kind in ("race", "qualify", "practice"):
            for r in sorted((x for x in recs if x["type"] == kind), key=lambda x: x.get("started_at") or "", reverse=True)[:1]:
                try:
                    if kind == "race":
                        cs = self._analysis(r["id"], None)[0].corners
                    elif kind == "qualify":
                        cs = self.quali(r["id"], None)["corners"]
                    else:
                        tq = self.technique_cached(self.recording_path(r["id"]))
                        cs = next((d.get("corners_detected") or [{"name": c["corner"], "apex": c["apex"]} for c in d["corners"]]
                                   for d in tq["drivers"] if d.get("available")), [])
                    cs = [{"name": c["name"], "apex": float(c["apex"])} for c in cs if c.get("apex") is not None]
                    if cs:
                        return cs
                except Exception:
                    continue
        return []

    def race_for_quali(self, quali_id: str) -> dict | None:
        """The race a qualifying session led into (the race whose qualifying link points here)."""
        races = [r for r in self.recordings() if r["type"] == "race" and r.get("quali") == quali_id]
        if not races:
            return None
        r = min(races, key=lambda r: r["started_at"] or "")
        return {"id": r["id"], "champ": r["assigned"][0]["champ"] if r["assigned"] else None}

    def quali(self, recording: str, champ_id: str | None) -> dict:
        from .quali import analyze_qualifying, quali_data
        from .race import _norm
        path = self.recording_path(recording)
        cfg = self.champ_config(champ_id) if champ_id else self._fallback_config()
        siblings = self._siblings(path, "qualify", 20 * 60)
        stamp = tuple(sorted((str(p), (p / "frames.parquet").stat().st_mtime if (p / "frames.parquet").exists() else 0)
                             for p in [path] + siblings))
        meta = self.recording_summary(path)
        t_samples, t_width, t_stamp = self.track_file(meta["track_raw"], meta["layout_raw"])
        key = ("quali", stamp, cfg.to_json() if cfg else None, t_stamp)
        if key in self._report_cache:
            return self._report_cache[key]
        qa = analyze_qualifying(path, humans=cfg.human_names() if cfg else None, extra_recordings=siblings,
                                track_samples=t_samples, track_width=t_width,
                                corners_override=self.track_corners(meta["track_raw"], meta["layout_raw"]))
        colors = None
        if cfg:
            from .season import driver_colors
            dc, amap = driver_colors(cfg), cfg.alias_map()
            colors = {n: dc[amap[_norm(n)]] for n in qa.classification.name if _norm(n) in amap and amap[_norm(n)] in dc}
        data = quali_data(qa, colors=colors, icons=self.icons_for(qa.classification.car if len(qa.classification) else []))
        data["merged_recordings"] = [p.name for p in siblings]
        data["track_key"] = {"track": meta["track_raw"], "layout": meta["layout_raw"]}
        data["race"] = self.race_for_quali(recording)
        from .quali import quali_breakdown
        data["breakdown"] = quali_breakdown(qa, self.settings.pinned_awards or [])
        data["talking_points"] = int(self.settings.talking_points or 6)
        self._report_cache[key] = data
        return data

    def replay(self, recording: str, champ_id: str | None) -> dict:
        from .awards import race_awards
        from .replay import replay_data
        ra, colors = self._analysis(recording, champ_id)
        icons = self.icons_for(ra.entrants.car)
        t_samples, t_width, _ = self.track_file(ra.session.meta["track_location"], ra.session.meta["track_variation"])
        data = replay_data(ra, colors=colors, awards=race_awards(ra, self.settings.pinned_awards or []), icons=icons,
                           track_samples=t_samples, track_width=t_width)
        data["track_key"] = {"track": ra.session.meta["track_location"], "layout": ra.session.meta["track_variation"]}
        return data

    def _fallback_config(self):
        """Not in a championship: borrow the most recent championship's roster to know who's human."""
        champs = self.champ_list()
        return self.champ_config(champs[0]["id"]) if champs else None

    def import_legacy(self) -> str | None:
        """First launch: turn an existing season.json (+ season.db) into a championship."""
        if self._champ_files():
            return None
        legacy = self.root / "season.json"
        if not legacy.exists():
            return None
        from .season import SeasonConfig, save_config
        cfg = SeasonConfig.load(legacy)
        cid = _slug(cfg.name)
        target = self.champs_dir / f"{cid}.db"
        if (self.root / "season.db").exists():
            shutil.copy2(self.root / "season.db", target)
        for k, v in PRESET_POINTS.items():
            cfg.points.setdefault(k, v)
        save_config(target, cfg)
        return cid


TEAM_ICONS = ("shield", "star", "bolt", "flame", "crown", "wing", "wheel", "flag", "diamond", "hex", "chevron", "peak")


def _clean_teams(teams: list[dict], driver_keys: set) -> list[dict]:
    """Valid teams: a name, a colour, an icon from the set, and each driver in at most one team."""
    out, keys, taken = [], set(), set()
    for t in teams:
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        key = _slug(t.get("key") or name)
        base, n = key, 1
        while key in keys:
            n += 1
            key = f"{base}-{n}"
        keys.add(key)
        color = str(t.get("color") or "#2E86DE")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = "#2E86DE"
        icon = t.get("icon") if t.get("icon") in TEAM_ICONS else "shield"
        members = [m for m in t.get("members", []) if m in driver_keys and m not in taken]
        taken.update(members)
        out.append({"key": key, "name": name, "color": color.upper(), "icon": icon, "members": members})
    return out


def _clean_drivers(drivers: list[dict]) -> list[dict]:
    out, keys = [], set()
    for d in drivers:
        display = str(d.get("display") or "").strip()
        if not display:
            continue
        key = _slug(d.get("key") or display) or "driver"
        base, n = key, 1
        while key in keys:
            n += 1
            key = f"{base}-{n}"
        keys.add(key)
        aliases = d.get("aliases") or []
        if isinstance(aliases, str):
            aliases = aliases.split(",")
        aliases = [a.strip() for a in aliases if a and a.strip()]
        role = d.get('role', 'human')
        if role not in ('human', 'ai'):
            raise ValueError('Driver role must be human or AI.')
        entry = {"key": key, "display": display, "aliases": aliases, 'role': role}
        if role == 'ai':
            entry['aliases'] = []
        if d.get('livery'):
            entry['livery'] = dict(d['livery'])
        out.append(entry)
    return out


# --------------------------------------------------------------------------- HTTP
class App:
    def __init__(self, root: Path, reader_factory=None):
        self.lib = Library(root)
        self.recorder = RecorderService(self.lib, reader_factory)
        self.last_heartbeat: float | None = None
        self.closing_at: float | None = None
        self.port = None
        self._livery_editor = None
        self._livery_designer = None
        self._bop_editor = None
        self._development = None
        if (self.lib.root / 'balance_of_performance' / 'development_receipts.db').exists():
            from .development import Development
            self._development = Development(self)
            self._development.start_worker()

    CLOSE_GRACE_S = 15          # a reload sends "closing" then heartbeats again straight away
    SILENT_LIMIT_S = 3 * 3600   # fallback if the close signal never arrives (crash, killed browser)

    def should_quit(self) -> bool:
        """Quit when the window has closed, but never because a background window was throttled or
        put to sleep by the browser, and never in the middle of recording a session."""
        if self.recorder.status().get("state") == "recording":
            return False
        now = time.monotonic()
        if self.closing_at is not None and now - self.closing_at > self.CLOSE_GRACE_S:
            # Windows' clock can give successive requests the same timestamp.
            # A heartbeat after closing already clears closing_at in route().
            return self.last_heartbeat is None or self.last_heartbeat <= self.closing_at
        return self.last_heartbeat is not None and now - self.last_heartbeat > self.SILENT_LIMIT_S

    def log_error(self, method: str, path: str, exc: Exception) -> None:
        """Append a traceback to ams2season.log next to the app (kept to the last ~1 MB)."""
        try:
            log = self.lib.root / "ams2season.log"
            if log.exists() and log.stat().st_size > 1_000_000:
                log.write_text(log.read_text(encoding="utf-8", errors="replace")[-500_000:], encoding="utf-8")
            with log.open("a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {method} {path}\n")
                f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        except Exception:
            pass

    # ------------------------------------------------------------------------------------ race engineer
    def engineer_route(self, method: str, path: str, query: dict, body: dict):
        from .derive import load_session
        from .engineer.catalog import CATEGORIES, SETTINGS
        from .engineer.store import EngineerStore, summary_for_ui
        lib = self.lib
        store = EngineerStore(lib.root)
        eng = getattr(self.recorder, "engineer", None)
        live = eng.status() if eng else None
        live_key = getattr(self.recorder, "engineer_key", None)
        if method == "GET" and path == "/api/engineer":
            prac = [{"id": r["id"], "car": r.get("car"), "track": r["track"], "track_raw": r.get("track_raw"), "layout_raw": r.get("layout_raw"),
                     "started_at": r["started_at"]} for r in lib.recordings() if r["type"] == "practice" and r["status"] == "complete"]
            for p in prac:
                if not p["car"]:
                    try:
                        p["car"] = (load_session(lib.recording_path(p["id"])).meta.get("local") or {}).get("car")
                    except Exception:
                        pass
            return {"sessions": store.list(), "live": live, "live_key": live_key, "practice": prac,
                    "settings": SETTINGS, "categories": CATEGORIES}
        if method == "POST" and path == "/api/engineer/session":
            s = store.create(body["car"], body["track"], body.get("layout") or body["track"], body.get("race_target"),
                             symmetrical_off=body.get("symmetrical_off"), baseline_default=body.get("baseline_default"),
                             unavailable=body.get("unavailable"), press_window=body.get("press_window"), prefs=body.get("prefs"))
            return summary_for_ui(s)
        if method == "GET" and path == "/api/engineer/session":
            out = summary_for_ui(store.get(query["key"]))
            out.update({"live": live if live_key == query["key"] else None, "settings": SETTINGS, "categories": CATEGORIES})
            return out
        if method == "DELETE" and path == "/api/engineer/session":
            p = store.path(query["key"])
            if p.exists():
                p.unlink()
            return {"ok": True}
        if method == "POST" and path == "/api/engineer/analyse":
            s = store.get(body["key"])
            rp = lib.recording_path(body["recording"])
            sess = load_session(rp)
            car = (sess.meta.get("local") or {}).get("car")
            if car and car != s["car"]:
                raise ValueError(f"That recording is in the {car}, not the {s['car']}.")
            if sess.local is None or not len(sess.local):
                raise ValueError("That recording has no telemetry from your car.")
            return summary_for_ui(store.add_run(body["key"], sess.local, sess.L, body["recording"]))
        if method == "POST" and path == "/api/engineer/feedback":
            return summary_for_ui(store.feedback(body["key"], body.get("feedback") or {}))
        if method == "POST" and path == "/api/engineer/decide":
            return summary_for_ui(store.decide(body["key"], body.get("decisions") or {}, body.get("manual") or []))
        if method == "POST" and path == "/api/engineer/live/start":
            key = body["key"]
            store.get(key)

            def on_run_end(df, info):
                L = info.get("track_length") or float(df.lap_dist.max())
                s = store.add_run(key, df, L, "live run")
                return {"run": len(s["runs"])}
            self.recorder.start_engineer(on_run_end)
            self.recorder.engineer_key = key
            return {"ok": True}
        if method == "POST" and path == "/api/engineer/live/stop":
            self.recorder.stop_engineer()
            self.recorder.engineer_key = None
            return {"ok": True}
        raise LookupError("unknown engineer request")

    @property
    def livery_designer(self):
        if self._livery_designer is None:
            from .livery_designer import LiveryDesigner
            self._livery_designer = LiveryDesigner(self)
        return self._livery_designer

    @property
    def liveries(self):
        if self._livery_editor is None:
            from .liveries import LiveryEditor
            self._livery_editor = LiveryEditor(self.lib.root)
        return self._livery_editor

    def identity_catalog(self):
        editor = self.liveries
        problem = None
        if not editor.cars and editor.config.get('game_path'):
            try:
                editor.scan()
            except (ValueError, OSError) as exc:
                problem = str(exc)  # historical snapshots remain usable without this installation
        models = set()
        for path in self.lib.recordings_dir.iterdir():
            if not (path / 'session.json').is_file():
                continue
            try:
                meta = json.loads((path / 'session.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            models.update(p['car'] for p in meta.get('final', []) if p.get('car'))
        return {'cars': [c.public() for c in editor.cars.values()], 'recorded_models': sorted(models), 'problem': problem}

    def identity_review(self, recording, champ=None, detail=False):
        from .identities import entrant_id, read
        path = self.lib.recording_path(recording)
        choices = []
        if not champ:
            assigned = {a['champ'] for a in self.lib.assignments().get(str(path.resolve()), [])}
            if len(assigned) == 1:
                champ = next(iter(assigned))
            else:
                for db in self.lib._champ_files():
                    cfg = self.lib.champ_config(db.stem)
                    if cfg and cfg.livery_ai and any(d.get('livery') for d in cfg.drivers) and (not assigned or db.stem in assigned):
                        choices.append({'id': db.stem, 'name': cfg.name})
                if len(choices) == 1:
                    champ = choices[0]['id']
        cfg = self.lib.champ_config(champ) if champ else None
        facts = read(path)
        enabled = bool(cfg and cfg.livery_ai and any(d.get('livery') for d in cfg.drivers))
        result = {'enabled': enabled, 'champ': champ, **facts}
        if cfg and not enabled:
            result['setup_required'] = True
        if not champ and len(choices) > 1:
            result['choices'] = choices
        summary = self.lib.recording_summary(path)
        if summary['type'] != 'race' or summary['status'] != 'complete':
            result['enabled'] = False
            result.pop('setup_required', None)
            result['unavailable_reason'] = 'Livery assignments are available after a race recording is complete.'
            result.pop('choices', None)
            return result
        if not enabled or (facts['reviewed'] and not detail):
            return result
        from .race import analyze_race
        # Classification is deliberately read under raw identities, including DNFs.
        frames = path / 'frames.parquet'
        stamp = frames.stat().st_mtime_ns if frames.exists() else 0
        key = ('identity-entrants', str(path), stamp, tuple(sorted(cfg.human_names())))
        entrants = self.lib._report_cache.get(key)
        if entrants is None:
            ra = analyze_race(path, humans=cfg.human_names())
            roles = dict(zip(ra.entrants.name, ra.entrants.is_ai))
            entrants = [{'id': entrant_id(r.name, r.car), 'name': r.name, 'car': r.car,
                         'finish': int(r.pos), 'status': r.status, 'is_ai': bool(roles[r.name])}
                        for r in ra.classification.itertuples()]
            self.lib._report_cache[key] = entrants
        result.update({'entrants': entrants, 'drivers': cfg.drivers, 'champ_name': cfg.name, 'car_class': cfg.car_class})
        return result

    def save_identity_review(self, body):
        from .identities import save
        from .season import connect, ingest
        recording, champ = body['recording'], body['champ']
        with self.lib.lock:
            review = self.identity_review(recording, champ, detail=True)
            if not review['enabled']:
                raise ValueError('Enable livery AI identities in this championship first.')
            self.identity_catalog()
            path = self.lib.recording_path(recording)
            data = save(path, body.get('assignments', {}), review['entrants'], self.liveries,
                        self.lib.champ_config(champ), body.get('revision'))
            self.lib._report_cache.clear()
            problems = []
            # Facts belong to the recording. Refresh every championship using it.
            for db in self.lib._champ_files():
                con = connect(db)
                try:
                    cfg = self.lib._cfg(con)
                    rows = con.execute('SELECT ev.round,s.race_no,s.path FROM session s JOIN event ev ON ev.id=s.event_id WHERE s.type=\'race\'').fetchall()
                finally:
                    con.close()
                for row in rows:
                    if Path(row['path']).resolve() != path.resolve():
                        continue
                    try:
                        ingest(db, cfg, path, round_no=row['round'], race_no=row['race_no'])
                    except Exception as exc:
                        problems.append(f'{cfg.name}, round {row["round"]}: {exc}')
            return {'ok': True, 'revision': data['revision'], 'problems': problems}

    def route(self, method: str, path: str, query: dict, body: dict):
        lib = self.lib
        if path == '/api/identities/catalog' and method == 'GET':
            return self.identity_catalog()
        if path == '/api/identities' and method == 'GET':
            return self.identity_review(query['recording'], query.get('champ'), query.get('detail') == '1')
        if path == '/api/identities' and method == 'POST':
            return self.save_identity_review(body)
        if method == 'PUT' and re.fullmatch(r'/api/championships/[\w-]+', path) and 'drivers' in body:
            from .identities import snapshot, color_override
            if any(d.get('livery') for d in body['drivers']):
                self.identity_catalog()
                old = lib.champ_config(path.rsplit('/', 1)[1])
                previous = {d['key']: d.get('livery') for d in old.drivers}
                for driver in body['drivers']:
                    if not driver.get('livery'):
                        continue
                    binding = driver.get('livery') or {}
                    snap = snapshot(self.liveries, binding.get('car_id'), binding.get('livery_id'), previous.get(driver.get('key')))
                    snap['recorded_car'] = str(binding.get('recorded_car') or '').strip()
                    snap.pop('color_override', None)
                    override = color_override(binding.get('color_override'))
                    if override:
                        snap['color_override'] = override
                    driver['livery'] = snap
        weekend_route = re.fullmatch(r"/api/championships/([\w-]+)/weekends", path)
        if weekend_route:
            from .weekends import weekends, assign
            cid = weekend_route.group(1)
            if method == "GET": return {"weekends": weekends(lib, cid)}
            if method == "POST":
                with lib.lock: return assign(lib, cid, body)
        dev_route = re.fullmatch(r"/api/championships/([\w-]+)/development(?:/([\w-]+))?", path)
        if dev_route:
            if self._development is None:
                from .development import Development
                self._development = Development(self)
            return self._development.route(dev_route.group(1), method, dev_route.group(2) or "", body)
        if path.startswith("/api/bop"):
            if self._bop_editor is None:
                from .bop import BopEditor
                self._bop_editor = BopEditor(self.lib.root, self.lib)
            return self._bop_editor.route(method, path, query, body)
        if path.startswith("/api/liveries"):
            return self.liveries.route(method, path, query, body)
        if method == "GET" and path == "/api/ping":
            return {"app": "ams2season", "version": __version__}
        if method == "POST" and path == "/api/closing":  # the window is closing (or reloading)
            self.closing_at = time.monotonic()
            return {"ok": True}
        if method == "POST" and path == "/api/heartbeat":
            self.last_heartbeat = time.monotonic()
            self.closing_at = None
            return {"ok": True}
        if method == "GET" and path == "/api/recorder":
            return self.recorder.status()
        if method == "POST" and path == "/api/recorder/start":
            self.recorder.start()
            return self.recorder.status()
        if method == "POST" and path == "/api/recorder/stop":
            self.recorder.stop()
            return self.recorder.status()
        if method == "GET" and path == "/api/home":
            recs = lib.recordings()
            return {"settings": asdict(lib.settings), "version": __version__,
                    "championships": lib.champ_list(),
                    "inbox": [r for r in recs if r["type"] == "race" and not r["assigned"] and r["status"] == "complete" and r.get("raced", True)][:8],
                    "latest": next((r for r in recs if r["type"] == "race" and r["status"] == "complete" and r.get("raced", True)), None),
                    "total_recordings": len(recs)}
        if method == "GET" and path == "/api/recordings":
            return {"recordings": lib.recordings()}
        if method == "GET" and path == "/api/settings":
            from .profiles import VERSION as PROFILE_VERSION
            return {"build": "telemetry-technique-20261008", "profile_version": PROFILE_VERSION, "settings": asdict(lib.settings), "root": str(lib.root),
                    "recordings_dir": str(lib.recordings_dir), "champs_dir": str(lib.champs_dir),
                    "windows": sys.platform == "win32", "version": __version__}
        if method == "GET" and path == "/api/car-icons":
            return lib.car_icon_page()
        if method == "POST" and path == "/api/car-icons/assign":  # pick an icon for an in-game car ("" = none)
            ov = dict(lib.settings.car_icon_overrides)
            if body.get("file") is None:
                ov.pop(body["car"], None)        # back to automatic matching
            else:
                ov[body["car"]] = body["file"]
            lib.settings.car_icon_overrides = ov
            lib.settings.save(lib.root)
            lib._report_cache.clear()
            return {"ok": True}
        if method == "POST" and path == "/api/car-icons/length":
            from .caricons import compact
            key = compact(Path(body["file"]).stem)
            lengths = dict(lib.settings.car_lengths)
            if body.get("length"):
                lengths[key] = max(3.0, min(7.0, float(body["length"])))
            else:
                lengths.pop(key, None)           # back to the default
            lib.settings.car_lengths = lengths
            lib.settings.save(lib.root)
            lib._report_cache.clear()
            return {"ok": True}
        if method == "POST" and path == "/api/car-icons/upload":
            from .caricons import import_upload
            res = import_upload(lib.icons_dir, body["name"], body["data"])
            lib._report_cache.clear()
            return res
        if method == "POST" and path == "/api/car-icons/flip":
            from .caricons import BUILTIN_DIR, flip_icon
            f = lib.icon_file(body["file"])
            if f.parent == BUILTIN_DIR.resolve():  # never edit the bundled set: flip a copy in your folder
                target = lib.icons_dir / f.name
                target.write_bytes(f.read_bytes())
                f = target
            flip_icon(f)
            lib._report_cache.clear()
            return {"ok": True}
        if method == "DELETE" and path == "/api/car-icons":
            f = lib.icon_file(query["file"])
            if f.parent != lib.icons_dir.resolve():
                raise ValueError("Built-in icons can't be deleted; choose \"no icon\" for a car instead.")
            f.unlink()
            lib._report_cache.clear()
            return {"ok": True}
        if method == "GET" and path == "/api/practice/templates":
            from .practice import DEFAULT_SELECTION, TEMPLATES
            return {"templates": TEMPLATES, "default": DEFAULT_SELECTION}
        if method == "GET" and path == "/api/practice/suggest":
            from .practice import suggest_objectives
            from .practice_points import AWARDS
            out = suggest_objectives(lib.recordings_dir)
            out["awards"] = [{"key": k, "label": l, "about": a} for k, l, a in AWARDS]
            return out
        if method == "POST" and path == "/api/practice/start":
            objs = [o for o in body.get("objectives", []) if isinstance(o, dict) and o.get("id")]
            self.recorder.start_practice(objs, lib.personal_best)
            return {"ok": True}
        if method == "GET" and path == "/api/practice/status":
            p = self.recorder.practice
            st = p.status() if p else {"active": False}
            st.update({"recorder": self.recorder.status()["state"], "available": self.recorder.available})
            if not p:
                recs = [r for r in lib.recordings() if r["type"] == "practice" and r["status"] == "complete"]
                st["last_recording"] = recs[0]["id"] if recs else None
            return st
        if method == "POST" and path == "/api/practice/stop":
            st = self.recorder.stop_practice() or {}
            recs = [r for r in lib.recordings() if r["type"] == "practice"]
            st["last_recording"] = recs[0]["id"] if recs else None
            return st
        if method == "GET" and path == "/api/technique":
            return lib.technique(query["recording"], query.get("champ") or None, query.get('pace_reference', 'fastest'))
        if method == "POST" and path == "/api/trackmap/start":
            self.recorder.start_mapping()
            return {"ok": True, "available": self.recorder.available}
        if method == "POST" and path == "/api/trackmap/stop":
            self.recorder.stop_mapping()
            return {"ok": True}
        if method == "POST" and path == "/api/trackmap/discard":
            if self.recorder.mapper:
                self.recorder.start_mapping()
            return {"ok": True}
        if method == "GET" and path == "/api/trackmap/status":
            from .trackmap import load_track_file
            m = self.recorder.mapper
            st = {"mapping": m is not None, "recorder": self.recorder.status()["state"], "available": self.recorder.available}
            if m:
                st.update(m.status())
                if st.get("track"):
                    st["saved"] = (load_track_file(lib.root, st["track"], st["layout"]) or {}).get("coverage")
            return st
        if method == "POST" and path == "/api/trackmap/save":
            from .trackmap import save_track_samples
            m = self.recorder.mapper
            if not m or not m.track:
                raise ValueError("nothing mapped yet")
            samples, _ = m.samples()
            if samples is None or not len(samples):
                raise ValueError("no edge crossings recorded yet: keep your wheels on the white line")
            res = save_track_samples(lib.root, m.track, m.layout, m.L, samples)
            lib._report_cache.clear()
            self.recorder.start_mapping()  # fresh buffer for the next pass; the file keeps what was saved
            return res
        if method == "GET" and path == "/api/tracks":
            from .trackmap import list_track_files
            return {"tracks": list_track_files(lib.root)}
        if method == "POST" and path == "/api/tracks/width":
            from .trackmap import save_track_width
            save_track_width(lib.root, body["track"], body["layout"], body.get("width"))
            lib._report_cache.clear()
            return {"ok": True}
        if method == "DELETE" and path == "/api/tracks":
            p = (lib.root / "tracks" / f"{query['key']}.json").resolve()
            if p.parent != (lib.root / "tracks").resolve() or not p.exists():
                raise LookupError("no such track map")
            p.unlink()
            lib._report_cache.clear()
            return {"ok": True}
        m_ = re.match(r"^/api/championships/([^/]+)/profiles$", path)
        if method == "GET" and m_:
            return lib.driver_profiles(m_.group(1))
        if method == "POST" and path == "/api/recordings/import":
            return lib.import_recording(body)
        if path.startswith("/api/engineer"):
            return self.engineer_route(method, path, query, body)
        if method == "GET" and path == "/api/style":
            return lib.style_page(query["recording"], query.get("champ"))
        if method == "GET" and path == "/api/errors":
            return lib.errors_page(query["recording"], query.get("champ"))
        if method == "GET" and path == "/api/overtakes":
            return lib.overtakes_page(query["recording"], query.get("champ"))
        if method == "GET" and path == "/api/tyres":
            return lib.tyres(query["recording"])
        if method == "POST" and path == "/api/tyres/window":  # the operating window for one car
            from .tyres import DEFAULT_WINDOW
            win = dict(lib.settings.tyre_windows)
            if body.get("window"):
                w = {k: float(body["window"][k]) for k in DEFAULT_WINDOW if body["window"].get(k) not in (None, "")}
                if w.get("temp_lo", 0) >= w.get("temp_hi", 1e9) or w.get("press_lo", 0) >= w.get("press_hi", 1e9):
                    raise ValueError("The low end of a window has to be below the high end.")
                win[body["car"]] = w
            else:
                win.pop(body["car"], None)
            lib.settings.tyre_windows = win
            lib.settings.save(lib.root)
            return {"ok": True}
        if method == "GET" and path == "/api/pace":
            return lib.race_pace_page(query["recording"], query.get("champ"))
        if method == "GET" and path == "/api/race-cars":
            return lib.race_cars_page(query["recording"], query.get("champ"))
        if method == "GET" and path == "/api/tracks/turns":
            return lib.track_turns(query["key"])
        if method == "POST" and path == "/api/tracks/turns":
            from .trackmap import save_track_corners
            t = lib.track_turns(body["key"])
            save_track_corners(lib.root, t["track"], t["layout"], body.get("corners"))
            lib._report_cache.clear()
            return {"ok": True}
        if method == "GET" and path == "/api/practice-laps":
            return lib.practice_laps(query["recording"])
        if method == "GET" and path == "/api/quali":
            return lib.quali(query["recording"], query.get("champ") or None)
        if method == "GET" and path == "/api/replay":
            return lib.replay(query["recording"], query.get("champ") or None)
        if method == "GET" and path == "/api/awards-catalog":
            from .awards import GROUP_ORDER, RACE_CATALOG, SEASON_CATALOG
            cat = lambda c: [{"id": k, "group": v[0], "title": v[1], "about": v[2]} for k, v in c.items()]
            return {"race": cat(RACE_CATALOG), "season": cat(SEASON_CATALOG), "groups": GROUP_ORDER}
        if method == "POST" and path == "/api/settings":
            if "talking_points" in body:
                body["talking_points"] = max(1, min(40, int(body["talking_points"])))
            if "pinned_awards" in body:
                body["pinned_awards"] = [str(x) for x in body["pinned_awards"]][:60]
            if "racing_corners" in body and body["racing_corners"] not in ("equal", "reduced", "excluded"):
                raise ValueError("racing_corners must be equal, reduced or excluded")
            for k in ("recordings_dir", "driver_label", "autostart_recorder", "talking_points", "pinned_awards", "racing_corners"):
                if k in body:
                    setattr(lib.settings, k, body[k])
            lib._report_cache.clear()
            lib.settings.save(lib.root)
            return {"settings": asdict(lib.settings)}
        if method == "POST" and path == "/api/open-folder":
            target = lib.recording_path(body["recording"]) if body.get("recording") else lib.root
            if sys.platform == "win32":
                os.startfile(target)  # noqa: S606 - local desktop app
            return {"ok": True, "path": str(target)}
        if method == "POST" and path == "/api/shortcut":
            return {"path": create_shortcut(lib.root)}
        if method == "GET" and path == "/api/suggestions":
            return {"names": lib.name_suggestions(query.get("champ"))}
        if method == "GET" and path == "/api/championships":
            return {"championships": lib.champ_list()}
        if method == "POST" and path == "/api/championships":
            return {"id": lib.create_champ(body)}
        m = re.fullmatch(r"/api/championships/([\w-]+)", path)
        if m:
            cid = m.group(1)
            if method == "GET":
                return lib.champ_detail(cid)
            if method == "PUT":
                return lib.update_champ(cid, body)
            if method == "DELETE":
                lib.delete_champ(cid)
                return {"ok": True}
        m = re.fullmatch(r"/api/championships/([\w-]+)/rounds", path)
        if m and method == "POST":
            return lib.add_round(m.group(1), body)
        if m and method == "DELETE":
            lib.remove_round(m.group(1), int(query["round"]), int(query.get("race_no", 1)))
            return {"ok": True}
        m = re.fullmatch(r"/api/championships/([\w-]+)/practice/(\d+)", path)
        if m and method == "DELETE":
            from .season import remove_practice
            with lib.lock:
                remove_practice(lib._db(m.group(1)), int(m.group(2)))
            lib._report_cache.clear()
            return {"ok": True}
        m = re.fullmatch(r"/api/championships/([\w-]+)/corrections(?:/(\d+))?", path)
        if m and method == "POST":
            lib.add_correction(m.group(1), body)
            return {"ok": True}
        if m and method == "DELETE" and m.group(2):
            lib.delete_correction(m.group(1), int(m.group(2)))
            return {"ok": True}
        raise LookupError(f"no route {method} {path}")


def make_handler(app: App):
    ui_file = Path(__file__).parent / "app_ui.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = "ams2season"

        def log_message(self, *args):  # quiet
            pass

        def _host_ok(self) -> bool:
            # localhost only, and refuse other Host headers (DNS-rebinding protection)
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def _send(self, code: int, body: bytes, ctype: str):
            gz = len(body) > 32_000 and "gzip" in (self.headers.get("Accept-Encoding") or "")
            if gz:
                import gzip
                body = gzip.compress(body, compresslevel=5)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if ctype.startswith('image/svg+xml'):
                # Imported SVG logos must remain images even when opened directly.
                self.send_header('Content-Security-Policy', "sandbox; default-src 'none'; style-src 'unsafe-inline'")
            if not ctype.startswith("image/"):
                # never reuse an old copy: after an update the app window must load the new page, scripts and data
                self.send_header("Cache-Control", "no-store")
            if gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            # Editable physics and percentage baselines must round-trip exactly:
            # four-place report rounding can erase small aero-coefficient edits.
            path = urlparse(self.path).path
            digits = None if path in ('/api/bop', '/api/technique') or path.startswith('/api/bop/') else 4
            self._send(code, json.dumps(_clean(obj, digits), allow_nan=False).encode("utf-8"), "application/json")

        def _dispatch(self, method: str):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path.startswith('/livery-designer/') or url.path == '/api/livery-designer':
                    if method not in ('GET', 'POST'):
                        raise LookupError('Unknown designer request.')
                    if method == 'POST':
                        def reject_designer(code, message):
                            # Drain small rejected bodies before closing: unread uploads
                            # can reset the connection on Windows and hide the error.
                            length = int(self.headers.get('Content-Length') or 0)
                            if 0 < length <= 1 << 20:
                                self.rfile.read(length)
                            self.close_connection = True
                            return self._json(code, {'error': message})
                        origin = self.headers.get('Origin')
                        if (origin and origin != 'http://' + self.headers.get('Host', '')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                            return reject_designer(403, 'Designer changes must come from this app window.')
                        ctype = self.headers.get('Content-Type', '').split(';')[0].strip()
                        if ctype not in ('application/json', 'application/octet-stream', 'image/png', 'application/zip'):
                            return reject_designer(415, 'Designer uploads require JSON or binary image data.')
                        n = int(self.headers.get('Content-Length') or 0)
                        if not 0 <= n <= 512 << 20:
                            return self._json(413, {'error': 'Designer uploads must be at most 512 MB.'})
                        data = self.rfile.read(n)
                        if len(data) != n:
                            raise ValueError('Designer upload was cut short.')
                    else:
                        data = b''
                    if url.path == '/api/livery-designer':
                        result = app.livery_designer.status() if method == 'GET' else app.livery_designer.configure(json.loads(data))
                        return self._json(200, result)
                    relative = '/' + url.path[len('/livery-designer/'):]
                    if url.query:
                        relative += '?' + url.query
                    code, data, ctype = app.livery_designer.handle(method, relative, self.headers, data)
                    return self._send(code, data, ctype)
                if method == "GET" and url.path in ("/", "/index.html"):
                    return self._send(200, ui_file.read_bytes(), "text/html; charset=utf-8")
                if method == "GET" and url.path == "/replay-timing.js":
                    return self._send(200, ui_file.with_name("replay_timing.js").read_bytes(), "text/javascript; charset=utf-8")
                if method == 'GET' and url.path == '/identity-ui.js':
                    return self._send(200, ui_file.with_name('identity_ui.js').read_bytes(), 'text/javascript; charset=utf-8')
                if method == 'POST' and url.path == '/api/identities':
                    origin = self.headers.get('Origin')
                    if origin and origin != 'http://' + self.headers.get('Host', ''):
                        return self._json(403, {'error': 'Assignments must come from this app window.'})
                    if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                        return self._json(415, {'error': 'Assignments require JSON.'})
                campaign_assets = {"/development-ui.js": ("development_ui.js", "text/javascript; charset=utf-8"),
                                   "/development-ui.css": ("development_ui.css", "text/css; charset=utf-8")}
                if method == "GET" and url.path in campaign_assets:
                    filename, ctype = campaign_assets[url.path]
                    return self._send(200, ui_file.with_name(filename).read_bytes(), ctype)
                bop_assets = {"/bop-editor.js": ("bop_editor.js", "text/javascript; charset=utf-8"),
                              "/bop-editor.css": ("bop_editor.css", "text/css; charset=utf-8")}
                if method == "GET" and url.path in bop_assets:
                    filename, ctype = bop_assets[url.path]
                    return self._send(200, ui_file.with_name(filename).read_bytes(), ctype)
                if method in ("POST", "PUT", "DELETE") and (url.path.startswith("/api/bop") or re.fullmatch(r"/api/championships/[\w-]+/development(?:/[\w-]+)?", url.path)):
                    origin = self.headers.get("Origin")
                    if origin and origin != "http://" + self.headers.get("Host", ""):
                        return self._json(403, {"error": "BOP changes must come from this app window."})
                    if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                        return self._json(415, {"error": "BOP requests require JSON."})
                livery_assets = {"/livery-editor.js": ("livery_editor.js", "text/javascript; charset=utf-8"),
                                 "/livery-editor.css": ("livery_editor.css", "text/css; charset=utf-8")}
                if method == "GET" and url.path in livery_assets:
                    filename, ctype = livery_assets[url.path]
                    return self._send(200, ui_file.with_name(filename).read_bytes(), ctype)
                if method == "GET" and url.path == "/api/liveries/image":
                    image = app.liveries.preview_image(query.get("car", ""), query.get("livery", ""))
                    try:
                        return self._send(200, image, "image/png")
                    except (BrokenPipeError, ConnectionResetError):
                        return  # the editor was left before this preview finished
                if method in ("POST", "PUT", "DELETE") and url.path.startswith("/api/liveries"):
                    origin = self.headers.get("Origin")
                    if origin and origin != "http://" + self.headers.get("Host", ""):
                        return self._json(403, {"error": "Livery changes must come from this app window."})
                    if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                        return self._json(415, {"error": "Livery requests require JSON."})
                if method == "GET" and url.path == "/favicon.ico" and (ASSETS / "icon.ico").exists():
                    return self._send(200, (ASSETS / "icon.ico").read_bytes(), "image/x-icon")
                if method == "GET" and url.path.startswith("/car-icons/"):
                    f = app.lib.icon_file(unquote(url.path[len("/car-icons/"):]))
                    ctype = {".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp"}.get(f.suffix.lower(), "")
                    if not ctype:
                        raise LookupError("not an image")
                    return self._send(200, f.read_bytes(), ctype)
                if method == "GET" and url.path == "/report":
                    page = app.lib.race_report(query["recording"], query.get("champ") or None)
                    return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                body = {}
                if method in ("POST", "PUT"):
                    n = int(self.headers.get("Content-Length") or 0)
                    if n:
                        body = json.loads(self.rfile.read(n).decode("utf-8"))
                return self._json(200, app.route(method, url.path, query, body))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return   # the browser left before the answer arrived (moved to another page): nothing to send
            except (KeyError, IndexError) as exc:  # a bug, not "not found": say what broke and log it
                app.log_error(method, url.path, exc)
                return self._json(500, {"error": f"Something went wrong ({type(exc).__name__}: {exc}). "
                                                 f"Details were saved to ams2season.log."})
            except LookupError as exc:
                return self._json(404, {"error": str(exc)})
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            except Exception as exc:
                app.log_error(method, url.path, exc)
                return self._json(500, {"error": f"Something went wrong ({type(exc).__name__}: {exc}). "
                                                 f"Details were saved to ams2season.log."})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return Handler


# --------------------------------------------------------------------------- window / launch
class _Server(ThreadingHTTPServer):
    # SO_REUSEADDR lets a restart rebind a port still in TIME_WAIT on Linux/macOS. On Windows it would
    # let two processes share the port, so it stays off there (a running app is detected via /api/ping).
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


def _make_server(port: int, handler) -> _Server:
    for p in (port, 0):
        try:
            return _Server(("127.0.0.1", p), handler)
        except OSError:
            continue
    raise RuntimeError("could not open a local port")


def _existing_instance(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=0.5) as r:
            return json.loads(r.read()).get("app") == "ams2season"
    except Exception:
        return False


def _ui_stamp() -> str:
    """Changes whenever the app's page does, so the window opens a fresh address after every update and can
    never show an old cached copy."""
    try:
        st = (Path(__file__).with_name("app_ui.html")).stat()
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return str(int(time.time()))


def open_window(url: str, root: Path) -> bool:
    """Open a chromeless app window (Edge, else Chrome); fall back to the default browser."""
    candidates = []
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidates += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                               Path(base) / "Google/Chrome/Application/chrome.exe"]
    else:
        for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    for exe in candidates:
        if exe.exists():
            profile = root / ".appwindow"
            subprocess.Popen([str(exe), f"--app={url}", f"--user-data-dir={profile}", "--window-size=1440,920",
                              "--no-first-run", "--no-default-browser-check"])
            return True
    webbrowser.open(url)
    return False


def create_shortcut(root: Path) -> str:
    """Desktop shortcut that starts the app with no console window (Windows)."""
    if sys.platform != "win32":
        raise ValueError("desktop shortcuts are only created on Windows")
    from .desktop import shortcut_command
    target, arguments = shortcut_command(root)
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    lnk = desktop / "AMS2 Season.lnk"
    icon = ASSETS / "icon.ico"
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          "$s.TargetPath='{target}';$s.Arguments='{arguments}';$s.WorkingDirectory='{root}';"
          "$s.IconLocation='{icon}';$s.Description='AMS2 Season';$s.Save()").format(
        lnk=str(lnk).replace("'", "''"), target=str(target).replace("'", "''"), arguments=arguments.replace("'", "''"),
        root=str(root).replace("'", "''"), icon=str(icon).replace("'", "''"))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return str(lnk)


def run_app(root: str | Path = ".", port: int = DEFAULT_PORT, open_ui: bool = True, keep_alive: bool = False,
            reader_factory=None) -> None:
    root = Path(root).resolve()
    if _existing_instance(port):  # already running: just bring up another window
        if open_ui:
            open_window(f"http://127.0.0.1:{port}/?v={_ui_stamp()}", root)
        return
    app = App(root, reader_factory=reader_factory)
    imported = app.lib.import_legacy()
    if imported:
        app.recorder._log(f"imported season.json as championship '{imported}'")
    server = _make_server(port, make_handler(app))
    app.port = server.server_address[1]
    url = f"http://127.0.0.1:{app.port}/?v={_ui_stamp()}"
    if app.lib.settings.autostart_recorder:
        app.recorder.start()
    print(f"AMS2 Season running at {url}  (close the app window to quit)")
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    if open_ui:
        open_window(url, root)

    try:
        while True:
            time.sleep(1)
            if keep_alive or app.last_heartbeat is None or not app.should_quit():
                continue
            break
    except KeyboardInterrupt:
        pass
    finally:
        app.recorder.stop()
        server.shutdown()
