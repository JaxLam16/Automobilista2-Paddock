"""Driving-style metrics, car statistics (race and season), and the practice lap replay."""
import json
import threading
import urllib.request
from datetime import datetime

import pytest

from ams2season.app import App, _make_server, make_handler
from ams2season.awards import race_awards
from ams2season.metrics import car_stats
from ams2season.race import analyze_race
from ams2season.recorder import Recorder
from ams2season.season import SeasonConfig, connect, ingest, season_cars_and_style
from ams2season.simulate import RaceScript, practice_drive, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]


@pytest.fixture(scope="module")
def race(tmp_path_factory):
    d = tmp_path_factory.mktemp("m")
    dirs = run_race(d, HUMANS, RaceScript(laps=6, n_ai=10, local_collision_lap=None), seed=7)
    path = next(x for x in dirs if x.name.endswith("_race"))
    return path, analyze_race(path, humans=set(HUMANS))


def test_driving_metrics_for_every_car(race):
    _, ra = race
    st = ra.stats.set_index("name")
    for col in ("brake_consistency", "throttle_consistency", "track_usage", "apex_gap_m", "brake_point_sd"):
        assert col in st.columns and st[col].notna().sum() >= len(st) - 1, col
    assert st.brake_consistency.between(0, 100).all() and st.track_usage.between(0, 100).all()
    # the simulator's drivers use differing amounts of road: the tightest line clips the apex
    assert st.apex_gap_m.min() < 0.3 and st.apex_gap_m.max() > 1.0
    assert st.loc[st.apex_gap_m.idxmin(), "track_usage"] == st.track_usage.max()


def test_car_stats_and_awards(race):
    _, ra = race
    cars = car_stats(ra.stats, ra.entrants)
    assert len(cars) >= 3 and sum(c["drivers"] for c in cars) == len(ra.entrants)
    paces = [c["pace"] for c in cars if c["pace"]]
    assert paces == sorted(paces)
    ids = {a["id"] for a in race_awards(ra)}
    assert {"fastest_car", "brake_metronome", "track_usage"} <= ids


def test_season_cars_and_style(race, tmp_path):
    path, _ = race
    cfg = SeasonConfig(drivers=[{"key": h.lower(), "display": h, "aliases": []} for h in HUMANS])
    ingest(tmp_path / "s.db", cfg, path, 1)
    out = season_cars_and_style(connect(tmp_path / "s.db"), cfg)
    assert {s["driver"] for s in out["style"]} == set(HUMANS) and all(s["track_usage"] is not None for s in out["style"])
    assert len(out["cars"]) >= 3 and abs(sum(c["entries"] for c in out["cars"]) - 14) == 0


def test_practice_lap_replay(tmp_path):
    rec = Recorder(tmp_path / "recordings", hz=20, log=lambda *_: None, wallclock=lambda: datetime(2026, 10, 2, 19, 0))
    now = 0
    for snap, t in practice_drive(laps=5, seed=3, invalid_laps=(3,)):
        now = t
        rec.step(snap, now)
    rec.close(now + 1)
    app = App(tmp_path)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/api/practice-laps?recording={rec.completed[-1].name}"
        d = json.loads(urllib.request.urlopen(url).read())
        names = [x["name"] for x in d["drivers"]]
        assert d["practice"] and d["driver"] == "Jax" and len(names) >= 3 and all(n.startswith("Lap ") for n in names)
        assert "Lap 3" not in names  # the invalid lap isn't replayed
        assert d["drivers"][0]["best"] == min(x["best"] for x in d["drivers"])  # fastest lap is the reference
        assert all(x["has_inputs"] for x in d["drivers"]) and len(d["corners"]) == 6
    finally:
        srv.shutdown()


def test_car_strengths_and_field(race, tmp_path):
    from ams2season.metrics import corner_types, field_row
    path, ra = race
    types = corner_types(ra.corner_speeds, ra.corners)
    assert len(types) == len(ra.corners) and {t["type"] for t in types} <= {"slow", "medium", "fast"}
    assert all((t["type"] == "slow") == (t["field_kph"] < 100) for t in types)
    cars = car_stats(ra.stats, ra.entrants, ra.corner_speeds)
    assert all(set(c["corners"]) == {t["corner"] for t in types} for c in cars)
    assert all(c["s1_delta"] is not None and c["apex_delta_slow"] is not None for c in cars)
    f = field_row(ra.stats)
    assert f["drivers"] == len(ra.stats) and f["pace"] and f["best_lap"] <= min(c["best_lap"] for c in cars)
    cfg = SeasonConfig(drivers=[{"key": h.lower(), "display": h, "aliases": []} for h in HUMANS])
    ingest(tmp_path / "s.db", cfg, path, 1)
    out = season_cars_and_style(connect(tmp_path / "s.db"), cfg)
    assert out["field"]["entries"] == len(ra.stats) and len(out["field"]["pace_by_race"]) == 1
    assert all(c["apex_delta_slow"] is not None for c in out["cars"])


def test_replay_has_steering_for_the_recording_driver(race):
    from ams2season.replay import replay_data
    _, ra = race
    rp = replay_data(ra)
    assert rp["inputs"]["steer"] and len(rp["inputs"]["steer"]) == rp["n"]
    assert max(abs(v) for v in rp["inputs"]["steer"] if v is not None) > 5
