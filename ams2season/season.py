"""Season database: ingest analysed races, apply stewarding corrections, compute standings and
season-long stats.

Human aliases and explicitly assigned fictional AI are persistent driver rows.
Unassigned AI remain race-scoped entrants; their raw names never register them.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .passes import PassParams
from .race import COUNTED, _norm, analyze_race

ANALYSIS_VERSION = 3  # opportunity-aware starts and linked-corner exit clearance

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS driver(id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, display TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event(id INTEGER PRIMARY KEY, round INTEGER UNIQUE NOT NULL, track TEXT, layout TEXT,
    car_class TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS session(id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES event(id),
    type TEXT NOT NULL, race_no INTEGER NOT NULL DEFAULT 1, path TEXT NOT NULL, recorded_by TEXT, started_at TEXT,
    track_length REAL, laps INTEGER, ai_count INTEGER, field_size INTEGER, corners TEXT, warnings TEXT,
    UNIQUE(event_id, type, race_no));
CREATE TABLE IF NOT EXISTS entrant(id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    driver_id INTEGER REFERENCES driver(id), name TEXT NOT NULL, car TEXT, car_class TEXT, is_ai INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS result(entrant_id INTEGER PRIMARY KEY REFERENCES entrant(id) ON DELETE CASCADE,
    grid INTEGER, finish INTEGER, status TEXT, laps INTEGER, total_time REAL, best_lap REAL, stats TEXT);
CREATE TABLE IF NOT EXISTS lap(entrant_id INTEGER NOT NULL REFERENCES entrant(id) ON DELETE CASCADE, lap INTEGER,
    time REAL, s1 REAL, s2 REAL, s3 REAL, valid INTEGER, pit INTEGER, clean INTEGER, position INTEGER,
    gap_to_leader REAL, PRIMARY KEY(entrant_id, lap));
CREATE TABLE IF NOT EXISTS pass(id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE, t REAL, lap INTEGER, lap_dist REAL,
    corner TEXT, passer_id INTEGER REFERENCES entrant(id), passed_id INTEGER REFERENCES entrant(id),
    kind TEXT, lap1 INTEGER);
CREATE TABLE IF NOT EXISTS pitstop(entrant_id INTEGER NOT NULL REFERENCES entrant(id) ON DELETE CASCADE,
    lap INTEGER, lane_time REAL, stationary_time REAL, kind TEXT);
CREATE TABLE IF NOT EXISTS battle(session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    a_id INTEGER, b_id INTEGER, start_lap INTEGER, end_lap INTEGER, laps REAL, duration_s REAL, min_gap_s REAL,
    swaps INTEGER, winner_id INTEGER);
CREATE TABLE IF NOT EXISTS incident(session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    t REAL, entrant_id INTEGER, other_id INTEGER, kind TEXT, magnitude REAL);
CREATE TABLE IF NOT EXISTS practice(id INTEGER PRIMARY KEY, round INTEGER NOT NULL, path TEXT NOT NULL UNIQUE,
    started_at TEXT, track TEXT, filed_at TEXT);
CREATE TABLE IF NOT EXISTS practice_award(practice_id INTEGER NOT NULL REFERENCES practice(id) ON DELETE CASCADE,
    award TEXT NOT NULL, driver_id INTEGER REFERENCES driver(id), name TEXT, value REAL, detail TEXT, points REAL, shared INTEGER);
CREATE TABLE IF NOT EXISTS correction(id INTEGER PRIMARY KEY, round INTEGER NOT NULL,
    race_no INTEGER NOT NULL DEFAULT 1, driver TEXT NOT NULL, kind TEXT NOT NULL, value REAL, note TEXT,
    created_at TEXT);
"""

CORRECTION_KINDS = ("time_penalty", "position_penalty", "dsq", "points")


# --------------------------------------------------------------------------- config
@dataclass
class SeasonConfig:
    name: str = "Season"
    drivers: list[dict] = field(default_factory=list)
    points: dict[str, list[float]] = field(default_factory=lambda: {"f1": [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]})
    default_points: str = "f1"
    ai_policy: str = "humans_only"           # or "full_field"
    fastest_lap_bonus: float = 0
    practice_points: float = 1.0                       # points per practice award (0 turns practice points off)
    practice_awards: list = field(default_factory=lambda: ["iron_man", "mileage", "metronome", "every_inch", "most_improved", "clean_sheet"])
    drop_rounds: int = 0
    points_for_dnf: bool = False
    pass_detection: dict = field(default_factory=dict)
    corners: dict = field(default_factory=dict)  # "Track|Layout": [{"name": "La Source", "apex": 350}, ...]
    teams: list = field(default_factory=list)      # [{"key", "name", "color", "icon", "members": [driver keys]}]
    team_count: int = 0                            # 0 = every member's points count; N = best N per race
    team_colors_for_drivers: bool = False
    livery_ai: bool = False
    car_class: str = ""                      # catalog filter for roster/livery pickers

    @classmethod
    def load(cls, path: str | Path) -> "SeasonConfig":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @classmethod
    def from_json(cls, text: str) -> "SeasonConfig":
        raw = json.loads(text)
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2)

    def alias_map(self) -> dict[str, str]:
        m = {}
        for d in self.drivers:
            for n in [d.get("display", d["key"]), d["key"], *d.get("aliases", [])]:
                m[_norm(n)] = d["key"]
        return m

    def human_names(self) -> set[str]:
        return {_norm(n) for d in self.drivers if d.get('role', 'human') != 'ai'
                for n in [d.get('display', d['key']), d['key'], *d.get('aliases', [])]}

    def corners_for(self, track: str, layout: str) -> list[dict] | None:
        c = self.corners.get(f"{track}|{layout}")
        if not c:
            return None
        return [{"name": x["name"], "apex": float(x["apex"])} for x in sorted(c, key=lambda x: x["apex"])]

    def pass_params(self) -> PassParams:
        return PassParams(**{k: v for k, v in self.pass_detection.items() if k in PassParams.__dataclass_fields__})


# --------------------------------------------------------------------------- db
def connect(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(battle)")}
    if "avg_gap_s" not in cols:  # databases made before battles had an average gap
        con.execute("ALTER TABLE battle ADD COLUMN avg_gap_s REAL")
    con.execute("PRAGMA foreign_keys = ON")
    return con


def stored_config(con: sqlite3.Connection) -> SeasonConfig | None:
    row = con.execute("SELECT value FROM meta WHERE key='config'").fetchone()
    return SeasonConfig.from_json(row["value"]) if row else None


def resolve_config(con, path: str | Path | None) -> SeasonConfig:
    if path:
        return SeasonConfig.load(path)
    cfg = stored_config(con)
    if cfg is None:
        raise SystemExit("no season config: pass --config (it is stored in the db on first ingest)")
    return cfg


def _sync_config(con: sqlite3.Connection, cfg: SeasonConfig) -> dict[str, int]:
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('config', ?)", (cfg.to_json(),))
    for d in cfg.drivers:
        con.execute("INSERT INTO driver(key, display) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET display=excluded.display",
                    (d["key"], d.get("display", d["key"])))
    return {r["key"]: r["id"] for r in con.execute("SELECT id, key FROM driver")}


def _py(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(float(v)) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def ingest(db_path: str | Path, cfg: SeasonConfig, session_dir: str | Path, round_no: int | None = None,
           race_no: int = 1, note: str | None = None) -> dict:
    """Analyse a race recording and store it as round `round_no` (replaces an earlier ingest)."""
    from .identities import project_session, revision
    sess = project_session(session_dir, cfg)
    ra = analyze_race(sess, humans=cfg.human_names(),
                      corners_override=cfg.corners_for(sess.meta["track_location"], sess.meta["track_variation"]),
                      params=cfg.pass_params())
    con = connect(db_path)
    try:
        with con:
            ids = _sync_config(con, cfg)
            if round_no is None:
                round_no = (con.execute("SELECT COALESCE(MAX(round), 0) FROM event").fetchone()[0] or 0) + 1
            car_class = ra.entrants.car_class.mode().iat[0] if len(ra.entrants) else None
            con.execute("""INSERT INTO event(round, track, layout, car_class, note) VALUES(?,?,?,?,?)
                           ON CONFLICT(round) DO UPDATE SET track=excluded.track, layout=excluded.layout,
                           car_class=excluded.car_class, note=COALESCE(excluded.note, event.note)""",
                        (round_no, sess.meta["track_location"], sess.meta["track_variation"], car_class, note))
            event_id = con.execute("SELECT id FROM event WHERE round=?", (round_no,)).fetchone()[0]
            con.execute("DELETE FROM session WHERE event_id=? AND type='race' AND race_no=?", (event_id, race_no))
            cur = con.execute(
                """INSERT INTO session(event_id, type, race_no, path, recorded_by, started_at, track_length, laps,
                   ai_count, field_size, corners, warnings) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, "race", race_no, str(Path(session_dir).resolve()), sess.meta.get("label"),
                 sess.meta.get("started_at"), sess.L, int(ra.classification.laps.max()),
                 int(ra.entrants.is_ai.sum()), len(ra.entrants), json.dumps(ra.corners), json.dumps(ra.warnings)))
            sid = cur.lastrowid
            amap = cfg.alias_map()
            eid = {}
            for e in ra.entrants.itertuples():
                key = sess.meta.get('_livery_drivers', {}).get(e.name) if e.is_ai else amap.get(_norm(e.name))
                recorded_name = sess.meta.get('_recorded_names', {}).get(e.name, e.name)
                c = con.execute("INSERT INTO entrant(session_id, driver_id, name, car, car_class, is_ai) VALUES(?,?,?,?,?,?)",
                                (sid, ids.get(key) if key else None, recorded_name, e.car, e.car_class, int(e.is_ai)))
                eid[e.name] = c.lastrowid
            stats = ra.stats.set_index("name")
            for r in ra.classification.itertuples():
                s = {k: _py(v) for k, v in stats.loc[r.name].to_dict().items()}
                s["_analysis_v"] = ANALYSIS_VERSION
                s['_identity_v'] = revision(session_dir, cfg)
                con.execute("INSERT INTO result VALUES(?,?,?,?,?,?,?,?)",
                            (eid[r.name], _py(r.grid), r.pos, r.status, r.laps, _py(r.total_time),
                             s.get("best_lap"), json.dumps(s)))
            con.executemany("INSERT INTO lap VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
                (eid[x.name], x.lap, _py(x.time), _py(x.s1), _py(x.s2), _py(x.s3), int(x.valid), int(x.pit),
                 int(x.clean), _py(x.position), _py(x.gap_to_leader)) for x in ra.laps.itertuples()])
            con.executemany("INSERT INTO pass(session_id, t, lap, lap_dist, corner, passer_id, passed_id, kind, lap1) "
                            "VALUES(?,?,?,?,?,?,?,?,?)", [
                (sid, x.t, x.lap, x.lap_dist, x.corner, eid[x.passer], eid[x.passed], x.kind, int(x.lap1))
                for x in ra.passes.itertuples()])
            con.executemany("INSERT INTO pitstop VALUES(?,?,?,?,?)", [
                (eid[x.name], x.lap, x.lane_time, x.stationary_time, x.kind) for x in ra.pits.itertuples()])
            con.executemany("INSERT INTO battle(session_id, a_id, b_id, start_lap, end_lap, laps, duration_s, min_gap_s, swaps, "
                            "winner_id, avg_gap_s) VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
                (sid, eid[x.a], eid[x.b], x.start_lap, x.end_lap, x.laps, x.duration_s, x.min_gap_s, x.swaps,
                 eid[x.winner], x.avg_gap_s) for x in ra.battles.itertuples()])
            con.executemany("INSERT INTO incident VALUES(?,?,?,?,?,?)", [
                (sid, x.t, eid.get(x.name), eid.get(x.other) if x.other else None, x.kind, _py(x.magnitude))
                for x in ra.incidents.itertuples()])
    finally:
        con.close()
    humans = ra.entrants[~ra.entrants.is_ai].name.tolist()
    return {"round": round_no, "race_no": race_no, "track": f"{sess.meta['track_location']} {sess.meta['track_variation']}",
            "winner": ra.classification.name.iat[0], "humans": humans,
            "ai": ra.entrants[ra.entrants.is_ai].name.tolist(), "warnings": ra.warnings, "analysis": ra}


# --------------------------------------------------------------------------- results & corrections
def race_table(con: sqlite3.Connection) -> pd.DataFrame:
    q = """SELECT ev.round, s.race_no, s.id AS session_id, ev.track, ev.layout, en.id AS entrant_id, en.name,
                  en.is_ai, d.key AS driver, d.display, r.grid, r.finish, r.status, r.laps, r.total_time,
                  r.best_lap, r.stats
           FROM result r JOIN entrant en ON en.id=r.entrant_id JOIN session s ON s.id=en.session_id
           JOIN event ev ON ev.id=s.event_id LEFT JOIN driver d ON d.id=en.driver_id
           WHERE s.type='race' ORDER BY ev.round, s.race_no, r.finish"""
    df = pd.read_sql_query(q, con)
    df["is_ai"] = df.is_ai.astype(bool)
    return df


def add_correction(db_path, round_no: int, driver: str, kind: str, value: float | None = None,
                   note: str | None = None, race_no: int = 1) -> int:
    if kind not in CORRECTION_KINDS:
        raise ValueError(f"kind must be one of {CORRECTION_KINDS}")
    con = connect(db_path)
    cfg = stored_config(con)
    if cfg:
        key = cfg.alias_map().get(_norm(driver))
        if key:
            row = con.execute('''SELECT en.name FROM entrant en JOIN driver d ON d.id=en.driver_id
                JOIN session s ON s.id=en.session_id JOIN event ev ON ev.id=s.event_id
                WHERE ev.round=? AND s.race_no=? AND s.type='race' AND d.key=? AND en.is_ai=1''',
                (round_no, race_no, key)).fetchone()
            if row:
                driver = row['name']  # stewarding follows the recorded car when its paint is corrected
    with con:
        cur = con.execute("INSERT INTO correction(round, race_no, driver, kind, value, note, created_at) VALUES(?,?,?,?,?,?,?)",
                          (round_no, race_no, driver, kind, value, note, datetime.now().isoformat(timespec="seconds")))
    con.close()
    return cur.lastrowid


def _corrected(race: pd.DataFrame, corrections: pd.DataFrame, amap: dict) -> pd.DataFrame:
    """Re-classify one race after penalties. Matches correction.driver against entrant name or roster alias."""
    r = race.copy().reset_index(drop=True)
    r["points_adj"] = 0.0
    if corrections.empty:
        return r

    def rows_for(name):
        key = amap.get(_norm(name))
        return r.index[(r.name.map(_norm) == _norm(name)) | ((r.driver == key) if key else False)]

    for c in corrections.itertuples():
        idx = rows_for(c.driver)
        if len(idx) == 0:
            continue
        i = idx[0]
        if c.kind == "time_penalty" and r.at[i, "status"] == "finished" and pd.notna(r.at[i, "total_time"]):
            r.at[i, "total_time"] += float(c.value or 0)
            fin = r[r.status == "finished"].sort_values(["laps", "total_time"], ascending=[False, True])
            rest = r[r.status != "finished"]
            r = pd.concat([fin, rest]).reset_index(drop=True)
        elif c.kind == "position_penalty":
            n = int(c.value or 0)
            row = r.loc[[i]]
            r = r.drop(index=i).reset_index(drop=True)
            last_classified = int((r.status.isin(["finished", "running"])).sum())
            r = pd.concat([r.iloc[:min(i + n, last_classified)], row, r.iloc[min(i + n, last_classified):]]).reset_index(drop=True)
        elif c.kind == "dsq":
            r.at[i, "status"] = "dsq"
            r = pd.concat([r.drop(index=i), r.loc[[i]]]).reset_index(drop=True)
        elif c.kind == "points":
            r.at[i, "points_adj"] += float(c.value or 0)
    r["finish"] = np.arange(1, len(r) + 1)
    return r


def classified_races(con: sqlite3.Connection, cfg: SeasonConfig) -> pd.DataFrame:
    """All races, corrections applied, with human_rank recomputed."""
    df = race_table(con)
    corr = pd.read_sql_query("SELECT * FROM correction ORDER BY id", con)
    amap = cfg.alias_map()
    parts = []
    for (rnd, rno), race in df.groupby(["round", "race_no"], sort=True):
        c = corr[(corr["round"] == rnd) & (corr.race_no == rno)]
        r = _corrected(race, c, amap)
        hum = r[~r.is_ai].index
        r["human_rank"] = np.nan
        r.loc[hum, "human_rank"] = np.arange(1, len(hum) + 1)
        parts.append(r)
    return pd.concat(parts, ignore_index=True) if parts else df


# --------------------------------------------------------------------------- standings
def practice_points(con: sqlite3.Connection) -> dict:
    """driver key -> {"display", "points", "awards"} from practice sessions filed in the championship."""
    out = {}
    try:
        rows = con.execute("SELECT d.key, d.display, pa.points FROM practice_award pa JOIN driver d ON d.id = pa.driver_id").fetchall()
    except sqlite3.OperationalError:
        return out
    for key, disp, pts in rows:
        o = out.setdefault(key, {"display": disp, "points": 0.0, "awards": 0})
        o["points"] += pts or 0
        o["awards"] += 1
    return out


def file_practice(db_path, cfg: "SeasonConfig", session_dir, round_no: int) -> dict:
    """File a practice session into a round: work out the practice awards and store them."""
    from datetime import datetime as _dt
    from .practice_points import awards, practice_stats
    session_dir = Path(session_dir)
    meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    if meta.get("session_type") != "practice":
        raise ValueError("That isn't a practice session.")
    con = connect(db_path)
    try:
        ids = _sync_config(con, cfg)
        amap = cfg.alias_map()
        stats = practice_stats(session_dir)
        humans = {n: amap[_norm(n)] for n in stats if _norm(n) in cfg.human_names()}
        won = awards(stats, humans, cfg.practice_awards, cfg.practice_points) if cfg.practice_points else []
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='weekend'").fetchone():
            p1 = {r[0] for r in con.execute('SELECT practice1 FROM weekend WHERE practice1 IS NOT NULL')}
            if session_dir.name in p1:
                won = []  # setup/learning sessions never add championship points
        ids = ids or dict(con.execute("SELECT key, id FROM driver").fetchall())
        con.execute("DELETE FROM practice WHERE path = ?", (str(session_dir),))
        cur = con.execute("INSERT INTO practice(round, path, started_at, track, filed_at) VALUES (?,?,?,?,?)",
                          (int(round_no), str(session_dir), meta.get("started_at"), meta.get("track_location_translated") or meta.get("track_location"),
                           _dt.now().isoformat(timespec="seconds")))
        pid = cur.lastrowid
        for a in won:
            con.execute("INSERT INTO practice_award VALUES (?,?,?,?,?,?,?,?)",
                        (pid, a["award"], ids.get(a["driver"]), a["name"], a["value"], a["detail"], a["points"], int(a["shared"])))
        con.commit()
        return {"round": int(round_no), "awards": won, "drivers": len(humans), "cars": len(stats)}
    finally:
        con.close()


def refile_practice(db_path, cfg: "SeasonConfig") -> None:
    """Work the practice awards out again (after the roster or the practice settings change)."""
    con = connect(db_path)
    try:
        rows = con.execute("SELECT path, round FROM practice").fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()
    for path, rnd in rows:
        if Path(path).exists():
            file_practice(db_path, cfg, path, rnd)


def remove_practice(db_path, practice_id: int) -> None:
    con = connect(db_path)
    try:
        con.execute("DELETE FROM practice_award WHERE practice_id = ?", (int(practice_id),))
        con.execute("DELETE FROM practice WHERE id = ?", (int(practice_id),))
        con.commit()
    finally:
        con.close()


def practice_sessions(con: sqlite3.Connection) -> list[dict]:
    try:
        ps = con.execute("SELECT id, round, path, started_at, track FROM practice ORDER BY round, started_at").fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for pid, rnd, path, started, track in ps:
        aw = con.execute("SELECT pa.award, COALESCE(d.display, pa.name), pa.detail, pa.points, pa.shared FROM practice_award pa "
                         "LEFT JOIN driver d ON d.id = pa.driver_id WHERE pa.practice_id = ?", (pid,)).fetchall()
        out.append({"id": pid, "round": rnd, "recording": Path(path).name, "started_at": started, "track": track,
                    "awards": [{"award": a, "driver": d, "detail": det, "points": p, "shared": bool(sh)} for a, d, det, p, sh in aw]})
    return out


def standings(con: sqlite3.Connection, cfg: SeasonConfig, policy: str | None = None,
              points_name: str | None = None) -> pd.DataFrame:
    policy = policy or cfg.ai_policy
    table = cfg.points[points_name or cfg.default_points]
    races = classified_races(con, cfg)
    prac = practice_points(con)
    if races.empty and not prac:
        return pd.DataFrame()
    if races.empty:   # only practice so far
        rows = [{"driver": v["display"], "points": v["points"], "practice": v["points"], "wins": 0, "podiums": 0, "best": np.nan, "races": 0}
                for v in prac.values()]
        st = pd.DataFrame(rows).sort_values("points", ascending=False)
        st.insert(0, "pos", np.arange(1, len(st) + 1))
        st.attrs["policy"], st.attrs["points"] = policy, points_name or cfg.default_points
        return st.reset_index(drop=True)
    eligible_status = {"finished", "running"} | ({"dnf", "disconnected"} if cfg.points_for_dnf else set())
    hum = races[races.driver.notna() & (~races.is_ai if policy == 'humans_only' else True)].copy()
    rank_col = "human_rank" if policy == "humans_only" else "finish"
    hum["rank"] = hum[rank_col].astype(int)
    hum["pts"] = [
        (table[rk - 1] if (rk <= len(table) and st in eligible_status) else 0.0)
        for rk, st in zip(hum["rank"], hum.status)]
    if cfg.fastest_lap_bonus:
        for _, race in hum.groupby(["round", "race_no"]):
            ok = race[race.status.isin(["finished", "running"]) & race.best_lap.notna()]
            if len(ok):
                hum.loc[ok.best_lap.idxmin(), "pts"] += cfg.fastest_lap_bonus
    hum["pts"] += hum.points_adj
    hum["race_label"] = ["R%d" % r if n == 1 else "R%d.%d" % (r, n) for r, n in zip(hum["round"], hum.race_no)]
    labels = list(dict.fromkeys(hum.race_label))

    rows = []
    for key, g in hum.groupby("driver"):
        per = dict(zip(g.race_label, g.pts))
        scores = sorted(per.values())
        dropped = scores[:cfg.drop_rounds] if cfg.drop_rounds and len(scores) > cfg.drop_rounds else []
        pp = prac.pop(key, {}).get("points", 0.0)
        rows.append({"driver": g.display.iat[0], "is_ai": bool(g.is_ai.iat[0]), "points": sum(scores) - sum(dropped) + pp,
                     **{lab: per.get(lab, np.nan) for lab in labels}, "practice": pp,
                     "wins": int((g["rank"] == 1).sum()), "podiums": int((g["rank"] <= 3).sum()),
                     "best": int(g["rank"].min()), "races": len(g)})
    for key, v in prac.items():   # drivers with practice points but no race yet
        rows.append({"driver": v["display"], "points": v["points"], "practice": v["points"], "wins": 0, "podiums": 0, "best": 99, "races": 0})
    if not rows:  # races filed, but none of their drivers match the roster yet
        return pd.DataFrame(columns=["pos", "driver", "points", "wins", "podiums", "best", "races"])
    st = pd.DataFrame(rows).sort_values(["points", "wins", "podiums", "best"], ascending=[False, False, False, True])
    st.insert(0, "pos", np.arange(1, len(st) + 1))
    st.attrs["policy"], st.attrs["points"] = policy, points_name or cfg.default_points
    return st.reset_index(drop=True)


# --------------------------------------------------------------------------- season stats
def _stats_frame(races: pd.DataFrame) -> pd.DataFrame:
    s = pd.json_normalize(races.stats.map(json.loads))
    s.index = races.index
    keep = [c for c in s.columns if c not in races.columns or c in ("name",)]
    return races.drop(columns=["stats"]).join(s[keep].drop(columns=["name"], errors="ignore"))


def driver_stats(con: sqlite3.Connection, cfg: SeasonConfig, include_ai: bool = False) -> pd.DataFrame:
    races = classified_races(con, cfg)
    if races.empty:
        return pd.DataFrame()
    df = _stats_frame(races)
    df["classified"] = df.status.isin(["finished", "running"])
    fastest = df[df.best_lap.notna()].groupby(["round", "race_no"]).best_lap.transform("min")
    df["fastest_lap"] = df.best_lap.eq(fastest.reindex(df.index))
    hum = df[df.driver.notna() & (~df.is_ai if not include_ai else True)]
    rows = []
    for key, g in hum.groupby("driver"):
        gc = g[g.classified]
        rows.append({
            "driver": g.display.iat[0], "is_ai": bool(g.is_ai.iat[0]), "races": len(g),
            "wins": int((g.finish == 1).sum()), "podiums": int((g.finish <= 3).sum()),
            "human_wins": int((g.human_rank == 1).sum()),
            "avg_grid": g.grid.mean(), "avg_finish": gc.finish.mean(), "avg_human_rank": g.human_rank.mean(),
            "pos_gained": g.positions_gained.sum(), "avg_lap1_gain": g.lap1_gain.mean(),
            "avg_field_pct": gc.field_pct.mean(),
            "passes": int(g.passes_made.sum()), "clean": int(g.passes_clean.sum()),
            "gifted": int(g.passes_gifted.sum()), "on_humans": int(g.passes_on_humans.sum()),
            "passed_by": int(g.passed_by.sum()), "net_passes": int(g.passes_made.sum() - g.passed_by.sum()),
            "lap1_passes": int(g.passes_lap1.sum()), "laps_led": int(g.laps_led.sum()),
            "fastest_laps": int(g.fastest_lap.sum()),
            "battles_won": f"{int(g.battles_won.sum())}/{int(g.battles.sum())}",
            "ai_rel_pace": g.ai_rel_pace.mean(), "consistency_s": g.consistency_s.mean(),
            "dnfs": int((~g.classified).sum()), "contacts": int(g.contacts.sum()),
        })
    if not rows:
        return pd.DataFrame(columns=["driver", "races", "avg_human_rank", "avg_finish"])
    return pd.DataFrame(rows).sort_values(["avg_human_rank", "avg_finish"]).reset_index(drop=True)


def head_to_head(con: sqlite3.Connection, cfg: SeasonConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(finished-ahead matrix, on-track passes matrix) between human drivers. Row beat column."""
    races = classified_races(con, cfg)
    hum = races[~races.is_ai & races.driver.notna()]
    names = sorted(hum.display.unique())
    ahead = pd.DataFrame(0, index=names, columns=names)
    for _, g in hum.groupby(["round", "race_no"]):
        order = list(g.sort_values("finish").display)
        for i, a in enumerate(order):
            for b in order[i + 1:]:
                ahead.loc[a, b] += 1
    q = """SELECT da.display AS passer, db.display AS passed, COUNT(*) AS n FROM pass p
           JOIN entrant ea ON ea.id=p.passer_id JOIN entrant eb ON eb.id=p.passed_id
           JOIN driver da ON da.id=ea.driver_id JOIN driver db ON db.id=eb.driver_id
           WHERE p.kind IN ({}) GROUP BY 1, 2""".format(",".join("?" * len(COUNTED)))
    passes = pd.DataFrame(0, index=names, columns=names)
    for r in con.execute(q, COUNTED):
        if r["passer"] in names and r["passed"] in names:
            passes.loc[r["passer"], r["passed"]] = r["n"]
    return ahead, passes


def season_highlights(con: sqlite3.Connection, cfg: SeasonConfig) -> list[str]:
    ds = driver_stats(con, cfg)
    if ds.empty:
        return []
    out = []

    def top(col, label, fmt="{:.0f}", asc=False):
        s = ds.dropna(subset=[col]).sort_values(col, ascending=asc)
        if len(s):
            out.append(f"{label}: {s.driver.iat[0]} ({fmt.format(s[col].iat[0])})")

    top("passes", "Most passes")
    top("net_passes", "Best net passing", "{:+.0f}")
    top("pos_gained", "Most places gained", "{:+.0f}")
    top("avg_lap1_gain", "Lap 1 specialist", "{:+.1f} places/race")
    top("consistency_s", "Metronome (lowest lap-time spread)", "{:.3f}s", asc=True)
    top("ai_rel_pace", "Fastest vs the AI", "{:.3f}x AI median pace", asc=True)
    top("laps_led", "Most laps led")
    _, pm = head_to_head(con, cfg)
    if pm.values.sum():
        tot = pm + pm.T
        a, b = np.unravel_index(np.argmax(np.triu(tot.values, 1)), tot.shape)
        if tot.values[a, b]:
            out.append(f"Biggest rivalry: {tot.index[a]} vs {tot.columns[b]} "
                       f"({pm.values[a, b]}-{pm.values[b, a]} in on-track passes)")
    return out


# --------------------------------------------------------------------------- app helpers
def save_config(db_path, cfg: SeasonConfig) -> None:
    con = connect(db_path)
    try:
        with con:
            _sync_config(con, cfg)
    finally:
        con.close()


def rounds_summary(con: sqlite3.Connection, cfg: SeasonConfig) -> list[dict]:
    """One row per race session: track, date, winner, first human, field mix (corrections applied)."""
    sessions = con.execute("""SELECT ev.round, s.race_no, ev.track, ev.layout, s.started_at, s.path, s.ai_count,
                                     s.field_size, s.laps, s.warnings FROM session s JOIN event ev ON ev.id=s.event_id
                              WHERE s.type='race' ORDER BY ev.round, s.race_no""").fetchall()
    races = classified_races(con, cfg)
    out = []
    for r in sessions:
        race = races[(races["round"] == r["round"]) & (races.race_no == r["race_no"])].sort_values("finish")
        hum = race[~race.is_ai]
        out.append({
            "round": r["round"], "race_no": r["race_no"], "track": r["track"], "layout": r["layout"],
            "started_at": r["started_at"], "recording": Path(r["path"]).name, "path": r["path"],
            "recording_exists": Path(r["path"]).exists(),
            "winner": (race.display.iat[0] if pd.notna(race.display.iat[0]) else race.name.iat[0]) if len(race) else None,
            "winner_is_ai": bool(race.is_ai.iat[0]) if len(race) else None,
            "first_human": hum.name.iat[0] if len(hum) else None,
            "first_human_pos": int(hum.finish.iat[0]) if len(hum) else None,
            "humans": int(len(hum)), "ai": r["ai_count"], "laps": r["laps"],
            "warnings": json.loads(r["warnings"] or "[]"),
        })
    return out


def progression(con: sqlite3.Connection, cfg: SeasonConfig, policy: str | None = None) -> dict:
    """Cumulative points per driver after each race (drop rounds ignored), for a chart."""
    st = standings(con, cfg, policy=policy)
    if st.empty:
        return {"labels": [], "series": {}}
    import re
    labels = [c for c in st.columns if re.fullmatch(r"R\d+(\.\d+)?", str(c))]
    series = {}
    for r in st.itertuples(index=False):
        row = r._asdict()
        vals = [0.0 if pd.isna(row[lab]) else float(row[lab]) for lab in labels]
        series[row["driver"]] = list(np.cumsum(vals))
    return {"labels": labels, "series": series}


def remove_round(db_path, round_no: int, race_no: int = 1) -> None:
    con = connect(db_path)
    try:
        with con:
            ev = con.execute("SELECT id FROM event WHERE round=?", (round_no,)).fetchone()
            if not ev:
                return
            con.execute("DELETE FROM session WHERE event_id=? AND type='race' AND race_no=?", (ev["id"], race_no))
            if race_no == 1 and con.execute("SELECT 1 FROM sqlite_master WHERE name='weekend'").fetchone():
                con.execute('UPDATE weekend SET race=NULL WHERE round=?', (round_no,))
            if not con.execute("SELECT 1 FROM session WHERE event_id=?", (ev["id"],)).fetchone():
                con.execute("DELETE FROM event WHERE id=?", (ev["id"],))
    finally:
        con.close()


def refresh_analysis(db_path, cfg: SeasonConfig) -> list[str]:
    """Refresh outdated stored race analyses, retaining event notes and steward corrections."""
    con = connect(db_path)
    try:
        rows = con.execute("""SELECT ev.round, s.race_no, s.path, r.stats FROM session s
            JOIN event ev ON ev.id=s.event_id JOIN entrant en ON en.session_id=s.id
            JOIN result r ON r.entrant_id=en.id WHERE s.type='race'""").fetchall()
    finally:
        con.close()
    stale = {}
    for r in rows:
        try:
            version = json.loads(r["stats"] or "{}").get("_analysis_v")
        except (ValueError, AttributeError):
            version = None
        from .identities import revision
        identity_version = json.loads(r['stats'] or '{}').get('_identity_v', '')
        if version != ANALYSIS_VERSION or identity_version != revision(r['path'], cfg):
            stale[(r["round"], r["race_no"])] = r["path"]
    problems = []
    for (round_no, race_no), path in stale.items():
        if not (Path(path) / "frames.parquet").is_file():
            problems.append(f"Round {round_no}, race {race_no}: recording missing; stored results retained.")
            continue
        try:
            ingest(db_path, cfg, path, round_no=round_no, race_no=race_no)
        except Exception as exc:
            problems.append(f"Round {round_no}, race {race_no}: analysis refresh failed ({exc}).")
    return problems


def reingest_all(db_path, cfg: SeasonConfig) -> list[str]:
    """Re-analyse every stored race (after roster / detection changes). Returns problems."""
    con = connect(db_path)
    try:
        rows = con.execute("""SELECT ev.round, s.race_no, s.path FROM session s JOIN event ev ON ev.id=s.event_id
                              WHERE s.type='race'""").fetchall()
    finally:
        con.close()
    problems = []
    for r in rows:
        if not Path(r["path"]).exists():
            problems.append(f"round {r['round']}: recording missing ({Path(r['path']).name})")
            continue
        try:
            ingest(db_path, cfg, r["path"], round_no=r["round"], race_no=r["race_no"])
        except Exception as exc:
            problems.append(f"round {r['round']}: {exc}")
    save_config(db_path, cfg)  # retain settings even when a recording is unavailable
    return problems


# --------------------------------------------------------------------------- teams
TEAM_PALETTE = ["#E4572E", "#2E86DE", "#E0A100", "#13A3A3", "#D6336C", "#7B2CBF", "#178A4C", "#A0522D", "#3F51B5", "#1C2230"]


def _shade(hex_color: str, f: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if f > 0:
        r, g, b = (int(c + (255 - c) * f) for c in (r, g, b))
    else:
        r, g, b = (int(c * (1 + f)) for c in (r, g, b))
    return f"#{r:02X}{g:02X}{b:02X}"


def driver_colors(cfg: SeasonConfig) -> dict:
    """Driver key -> colour. Roster order by default; with team colours on, teammates share their team's
    colour in light/dark variants so they stay distinguishable."""
    from .report import HUMAN_COLORS
    out = {d["key"]: HUMAN_COLORS[i % len(HUMAN_COLORS)] for i, d in enumerate(cfg.drivers)}
    if cfg.team_colors_for_drivers:
        for t in cfg.teams:
            for j, k in enumerate(t.get("members", [])):
                if k in out and t.get("color"):
                    out[k] = _shade(t["color"], [0.0, 0.35, -0.3, 0.6][j % 4])
    return out


def team_of(cfg: SeasonConfig) -> dict:
    return {k: t for t in cfg.teams for k in t.get("members", [])}


def race_points(con, cfg: SeasonConfig, policy: str | None = None, points_name: str | None = None) -> pd.DataFrame:
    """Points per human per race, after corrections (the building block of driver and team standings)."""
    policy = policy or cfg.ai_policy
    table = cfg.points[points_name or cfg.default_points]
    races = classified_races(con, cfg)
    if races.empty:
        return pd.DataFrame(columns=["round", "race_no", "driver", "display", "pts", "rank"])
    eligible = {"finished", "running"} | ({"dnf", "disconnected"} if cfg.points_for_dnf else set())
    hum = races[races.driver.notna() & (~races.is_ai if policy == 'humans_only' else True)].copy()
    hum["rank"] = hum["human_rank" if policy == "humans_only" else "finish"].astype(int)
    hum["pts"] = [(table[r - 1] if (r <= len(table) and st in eligible) else 0.0) for r, st in zip(hum["rank"], hum.status)]
    if cfg.fastest_lap_bonus:
        for _, race in hum.groupby(["round", "race_no"]):
            ok = race[race.status.isin(["finished", "running"]) & race.best_lap.notna()]
            if len(ok):
                hum.loc[ok.best_lap.idxmin(), "pts"] += cfg.fastest_lap_bonus
    hum["pts"] += hum.points_adj
    return hum[["round", "race_no", "driver", "display", "pts", "rank"]]


def team_standings(con, cfg: SeasonConfig, policy: str | None = None, points_name: str | None = None) -> pd.DataFrame:
    if not cfg.teams:
        return pd.DataFrame()
    rp = race_points(con, cfg, policy, points_name)
    owner = {k: t["key"] for t in cfg.teams for k in t.get("members", [])}
    rp = rp[rp.driver.isin(list(owner))].copy()
    rp["team"] = rp.driver.map(owner).astype(object)
    rp["label"] = ["R%d" % r if n == 1 else "R%d.%d" % (r, n) for r, n in zip(rp["round"], rp.race_no)]
    labels = list(dict.fromkeys(rp.sort_values(["round", "race_no"]).label))
    rows = []
    for t in cfg.teams:
        mine = rp[rp.team == t["key"]]
        per = {}
        for lab, g in mine.groupby("label"):
            pts = g.pts.sort_values(ascending=False)
            per[lab] = float(pts.head(cfg.team_count).sum() if cfg.team_count else pts.sum())
        rows.append({"team": t["key"], "name": t.get("name") or t["key"], "color": t.get("color"), "icon": t.get("icon"),
                     "points": sum(per.values()), **{lab: per.get(lab) for lab in labels},
                     "wins": int((mine["rank"] == 1).sum()), "podiums": int((mine["rank"] <= 3).sum()),
                     "members": [m for m in t.get("members", [])]})
    if not rows:
        return pd.DataFrame()
    st = pd.DataFrame(rows).sort_values(["points", "wins", "podiums"], ascending=False)
    st.insert(0, "pos", np.arange(1, len(st) + 1))
    st.attrs["labels"] = labels
    return st.reset_index(drop=True)


def teammate_battles(con, cfg: SeasonConfig) -> list[dict]:
    """Head-to-head inside each team: who finished ahead, and points."""
    if not cfg.teams:
        return []
    races = classified_races(con, cfg)
    rp = race_points(con, cfg)
    disp = {d["key"]: d.get("display", d["key"]) for d in cfg.drivers}
    out = []
    for t in cfg.teams:
        mem = [m for m in t.get("members", []) if m in disp]
        if len(mem) < 2:
            continue
        ahead = {m: 0 for m in mem}
        for _, g in races[races.driver.isin(mem)].groupby(["round", "race_no"]):
            if g.driver.nunique() >= 2:
                ahead[g.sort_values("finish").driver.iat[0]] += 1
        pts = rp[rp.driver.isin(mem)].groupby("driver").pts.sum().to_dict()
        out.append({"team": t["key"], "name": t.get("name"), "color": t.get("color"), "icon": t.get("icon"),
                    "drivers": [{"key": m, "display": disp[m], "ahead": ahead[m], "points": float(pts.get(m, 0))} for m in mem]})
    return out


# --------------------------------------------------------------------------- cars and driving style, season-long
def season_cars_and_style(con, cfg: SeasonConfig) -> dict:
    """Per car model: entries, results and pace relative to the field in each race, averaged. Per human:
    braking/throttle point consistency and track usage averaged over the season."""
    q = con.execute("""SELECT e.car, e.is_ai, d.display, r.finish, r.status, r.stats, s.id AS sid
                       FROM entrant e JOIN result r ON r.entrant_id = e.id JOIN session s ON s.id = e.session_id
                       LEFT JOIN driver d ON d.id = e.driver_id WHERE s.type = 'race'""").fetchall()
    if not q:
        return {"cars": [], "style": []}
    rows = []
    for x in q:
        st = json.loads(x["stats"] or "{}")
        rows.append({"car": x["car"], "is_ai": bool(x["is_ai"]), "display": x["display"], "finish": x["finish"], "sid": x["sid"],
                     **{k: st.get(k) for k in ("median_clean", "best_lap", "top_speed_kph", "brake_consistency",
                                               "throttle_consistency", "track_usage", "apex_gap_m", "exit_gap_m",
                                               "apex_delta_slow", "apex_delta_medium", "apex_delta_fast")}})
    df = pd.DataFrame(rows)
    for col in ("median_clean", "best_lap", "top_speed_kph", "brake_consistency", "throttle_consistency", "track_usage", "apex_gap_m", "exit_gap_m",
                "apex_delta_slow", "apex_delta_medium", "apex_delta_fast"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["rel"] = (df.median_clean / df.groupby("sid").median_clean.transform("median") - 1) * 100
    cars = []
    for car, g in df.groupby("car"):
        cars.append({"car": car, "entries": int(len(g)), "races": int(g.sid.nunique()), "wins": int((g.finish == 1).sum()),
                     "podiums": int((g.finish <= 3).sum()), "avg_finish": round(float(g.finish.mean()), 1),
                     "pace_vs_field": round(float(g.rel.mean()), 2) if g.rel.notna().any() else None,
                     "top_speed": round(float(g.top_speed_kph.max())) if g.top_speed_kph.notna().any() else None,
                     **{k: (round(float(g[k].mean()), 1) if g[k].notna().any() else None)
                        for k in ("apex_delta_slow", "apex_delta_medium", "apex_delta_fast")},
                     "humans": sorted({d for d in g.loc[~g.is_ai, 'display'].dropna()})})
    cars.sort(key=lambda c: (c["pace_vs_field"] is None, c["pace_vs_field"] if c["pace_vs_field"] is not None else 0))
    style = []
    for who, g in df[df.display.notna()].groupby("display"):
        style.append({"driver": who, "is_ai": bool(g.is_ai.iat[0]), "races": int(g.sid.nunique()),
                      **{k: (round(float(g[k].mean()), 2 if k in ("apex_gap_m", "exit_gap_m") else 0) if g[k].notna().any() else None)
                         for k in ("brake_consistency", "throttle_consistency", "track_usage", "apex_gap_m", "exit_gap_m")}})
    style.sort(key=lambda r: -(r["track_usage"] or 0))
    field = {"races": int(df.sid.nunique()), "entries": int(len(df)),
             "pace_by_race": [round(float(v), 3) for v in df.groupby("sid").median_clean.median().dropna()],
             "top_speed": round(float(df.top_speed_kph.max())) if df.top_speed_kph.notna().any() else None}
    return {"cars": cars, "style": style, "field": field}
