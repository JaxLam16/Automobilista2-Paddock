"""The Errors and Overtaking pages: mistakes found and classified, positions lost to them, pass and hold
rates, and the Pace page colouring drivers outside a championship."""
import json
import threading
import urllib.request

import pandas as pd
import pytest

from ams2season.app import App, _make_server, make_handler
from ams2season.errors import race_errors
from ams2season.overtakes import overtaking
from ams2season.race import analyze_race
from ams2season.simulate import RaceScript, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]


@pytest.fixture(scope="module")
def spun(tmp_path_factory):
    root = tmp_path_factory.mktemp("eo")
    dirs = run_race(root / "recordings", HUMANS, RaceScript(laps=6, n_ai=10, spin=("Theo", 3, 1320.0), local_collision_lap=None), seed=7)
    path = next(d for d in dirs if d.name.endswith("_race"))
    return root, path, analyze_race(path, humans=set(HUMANS))


def test_spin_found_with_its_cost(spun):
    _, _, ra = spun
    e = race_errors(ra)
    theo = [x for x in e["errors"] if x["name"] == "Theo"]
    assert len(theo) == 1 and theo[0]["kind"] == "spin" and theo[0]["lap"] == 3 and theo[0]["corner"] == "T3"
    assert theo[0]["loss"] > 2 and theo[0]["positions"] >= 1
    d = {x["name"]: x for x in e["drivers"]}
    assert d["Theo"]["spin"] == 1 and d["Theo"]["positions_lost"] >= 1 and d["Theo"]["clean_lap_share"] < 100
    assert all(d[h]["errors"] == 0 for h in ("Jax", "Mason", "Eli"))       # no false mistakes


def test_overtaking_rates(spun):
    _, _, ra = spun
    o = {x["name"]: x for x in overtaking(ra)["drivers"]}
    for d in o.values():
        assert d["pass_rate"] is None or 0 <= d["pass_rate"] <= 100
        assert d["hold_rate"] is None or 0 <= d["hold_rate"] <= 100
        assert d["attack_laps"] >= len({l for l in ra.passes[(ra.passes.passer == d["name"]) & (ra.passes.kind != "gifted") & (ra.passes.lap > 1)].lap})
    assert o["Theo"]["gifted_lost"] >= 1                                     # his spin handed places away, outside the ratings
    made = sum(d["made"] + d["gifted_gained"] for d in o.values())
    assert made == len(ra.passes)


def test_hold_rate_counts_defending_laps():
    """A hand-built case: B sits 0.5 s behind A for laps 2-6 and passes on lap 6."""
    from types import SimpleNamespace
    rows = []
    for lap in range(1, 7):
        rows.append({"name": "A", "lap": lap, "t_end": 60.0 * lap, "time": 60.0, "clean": True, "pit": False})
        rows.append({"name": "B", "lap": lap, "t_end": 60.0 * lap + (0.5 if lap < 6 else -0.3), "time": 60.0, "clean": True, "pit": False})
    ra = SimpleNamespace(laps=pd.DataFrame(rows),
                         passes=pd.DataFrame([{"t": 355.0, "lap": 6, "corner": "T1", "passer": "B", "passed": "A", "kind": "clean"}]),
                         entrants=pd.DataFrame({"name": ["A", "B"], "is_ai": [False, False]}),
                         classification=pd.DataFrame({"name": ["B", "A"], "pos": [1, 2], "grid": [2, 1]}))
    o = {x["name"]: x for x in overtaking(ra)["drivers"]}
    assert o["B"]["attack_laps"] == 5 and o["B"]["pass_rate"] == 20               # 1 pass in 5 laps attacking
    assert o["A"]["defend_laps"] == 5 and o["A"]["hold_rate"] == 80               # held 4 of 5
    assert o["B"]["net"] == 1 and o["A"]["net"] == -1


def test_pages_and_pace_colours(spun):
    root, path, _ = spun
    app = App(root)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    get = lambda p: json.loads(urllib.request.urlopen(base + p.lstrip("/")).read())
    try:
        e = get(f"/api/errors?recording={path.name}")
        assert e["track"]["points"] and any(x["name"] == "Theo" and x["kind"] == "spin" for x in e["errors"])
        o = get(f"/api/overtakes?recording={path.name}")
        assert o["passes"] and all(p.get("x") is not None for p in o["passes"]) and o["track"]["corners"]
        pace = get(f"/api/pace?recording={path.name}")                           # no championship: colours still assigned
        assert all(d["color"] for d in pace["drivers"] if not d["is_ai"])
        html = urllib.request.urlopen(base + f"report?recording={path.name}").read().decode()
        assert 'id="passlog"' not in html and 'id="map"' not in html             # moved to the Overtaking page
    finally:
        srv.shutdown()
