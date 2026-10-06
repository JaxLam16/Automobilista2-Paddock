"""Race pace (trend, thirds, clean air vs traffic, race vs qualifying), corner percentiles, replay lap times,
the Pace and Cars pages, and turns placed by hand."""
import json
import shutil
import threading
import urllib.request
from pathlib import Path

import pandas as pd
import pytest

from ams2season.app import App, _make_server, make_handler
from ams2season.metrics import race_pace
from ams2season.simulate import RaceScript, run_race

RBR = Path(__file__).parent / "data" / "rbr"


def test_clean_air_traffic_trend_and_thirds():
    """Two cars: B sits 0.8 s behind A for laps 2-5; then A pulls away (gap 3 s and growing) and B, in clean
    air, laps faster and faster."""
    rows, ta, tb = [], 0.0, 0.0
    for lap in range(1, 10):
        a_time = 60.0 if lap <= 5 else 57.5
        b_time = 60.0 if lap <= 5 else 59.0 - 0.1 * (lap - 6)
        ta += a_time
        tb = ta + 0.8 if lap <= 5 else tb + b_time
        if lap == 6:
            tb = ta + 3.0
        rows.append({"name": "A", "lap": lap, "t_end": ta, "time": a_time, "clean": True, "pit": False})
        rows.append({"name": "B", "lap": lap, "t_end": tb, "time": b_time, "clean": True, "pit": False})
    out = race_pace(pd.DataFrame(rows), {"A": False, "B": False})
    b = next(d for d in out["drivers"] if d["name"] == "B")
    air = {x["lap"]: x["air"] for x in b["laps"]}
    assert air[1] == "start" and all(air[k] == "traffic" for k in (2, 3, 4, 5))
    assert all(air[k] == "clean" for k in (7, 8, 9))
    assert b["traffic"]["laps"] >= 3 and b["clean_air"]["laps"] >= 3 and b["traffic_cost"] > 0.5
    assert b["trend"] < 0 and b["thirds"][2] < b["thirds"][0]
    a = next(d for d in out["drivers"] if d["name"] == "A")
    assert all(x["air"] in ("clean", "start") for x in a["laps"])   # the leader always has clean air
    assert len(out["field_by_lap"]) == 8


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("pace")
    run_race(root / "recordings", ["Jax", "Mason", "Eli", "Theo"], RaceScript(laps=8, n_ai=8, with_qualifying=True, local_collision_lap=None), seed=7)
    app = App(root)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"

    def call(m, path, body=None):
        req = urllib.request.Request(base + path.lstrip("/"), method=m, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    race = next(r["id"] for r in call("GET", "/api/recordings")["recordings"] if r["type"] == "race")
    yield app, call, race, root
    srv.shutdown()


def test_pace_and_cars_pages(server):
    app, call, race, _ = server
    p = call("GET", f"/api/pace?recording={race}")
    jax = next(d for d in p["drivers"] if d["name"] == "Jax")
    assert jax["quali_best"] and jax["median"] and jax["median"] > jax["quali_best"]   # race pace slower than qualifying
    assert jax["thirds"] and jax["trend"] is not None and p["field_by_lap"]
    c = call("GET", f"/api/race-cars?recording={race}")
    assert len(c["cars"]) >= 2 and c["car_extra"]["field"]["pace"] and c["car_extra"]["turns"]
    rp = call("GET", f"/api/replay?recording={race}")
    laps = rp["lap_times"]["Jax"]
    assert len(laps) == 8 and all(x[1] > 0 for x in laps) and laps[1][2] and laps[1][3] is True


def test_corner_percentiles(server):
    _, call, race, _ = server
    tq = call("GET", f"/api/technique?recording={race}")
    jax = next(d for d in tq["drivers"] if d.get("available"))
    fields = [c["field"] for c in jax["corners"] if c.get("field")]
    assert len(fields) == len(jax["corners"]) and all(0 <= f["pct"] <= 100 and f["cars"] >= 10 for f in fields)


@pytest.mark.skipif(not RBR.exists(), reason="real Red Bull Ring recording not present")
def test_turns_placed_by_hand(tmp_path):
    shutil.copytree(RBR, tmp_path, dirs_exist_ok=True)
    app = App(tmp_path)
    t = app.lib.track_turns("spielberg__spielberg-modern")
    assert not t["custom"] and [c["name"] for c in t["corners"]] == [f"T{i}" for i in range(1, 9)]  # from your recording
    assert abs(t["corners"][0]["apex"] - 475) < 30 and len(t["centre"]) > 800
    from ams2season.trackmap import save_track_corners
    save_track_corners(tmp_path, t["track"], t["layout"], [{"name": "Niki Lauda", "apex": 460}, {"name": "Remus", "apex": 1400},
                                                            {"name": "Rindt", "apex": 4000}])
    app.lib._report_cache.clear()
    assert app.lib.track_turns("spielberg__spielberg-modern")["custom"]
    rec = next(r["id"] for r in app.lib.recordings() if r["type"] == "qualify")
    q = app.lib.quali(rec, None)
    assert [c["name"] for c in q["corners"]] == ["Niki Lauda", "Remus", "Rindt"]
    assert [c["dir"] for c in q["corners"]] == ["right", "right", "right"]
    save_track_corners(tmp_path, t["track"], t["layout"], None)                              # back to automatic
    app.lib._report_cache.clear()
    assert not app.lib.track_turns("spielberg__spielberg-modern")["custom"]
