"""Tyre analysis: tread profile and setup hints, warm-up, pressures, balance, overheating spots, heat map,
the operating window setting, and recordings made before tyre data was recorded."""
import json
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from ams2season.app import App, _make_server, make_handler
from ams2season.recorder import Recorder
from ams2season.simulate import practice_drive
from ams2season.tyres import tyre_analysis

RBR = Path(__file__).parent / "data" / "rbr"


def _practice(root, setup, laps=8):
    rec = Recorder(root / "recordings", hz=20, log=lambda *_: None, wallclock=lambda: datetime(2026, 10, 4, 18, 0))
    now = 0
    for snap, t in practice_drive(laps=laps, seed=3, tyre_setup=setup):
        now = t
        rec.step(snap, now)
    rec.close(now + 1)
    return rec.completed[-1]


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    """Over-inflated by 2.5 psi with too little negative camber."""
    root = tmp_path_factory.mktemp("ty")
    return root, _practice(root, {"press": 2.5, "camber": 1.2})


def test_recorder_captures_the_whole_tyre(planted):
    import pyarrow.parquet as pq
    lo = pq.read_table(planted[1] / "local.parquet").to_pandas()
    for k in ("tl", "tc", "tr", "tread", "layer", "carc", "rim", "air", "ride", "susp"):
        assert np.isfinite(lo[f"{k}_fl"]).all(), k
    assert 20 < lo.carc_fl.max() < 150 and lo.carc_fl.min() < 50   # degrees C (converted from Kelvin), cold at the start


def test_planted_setup_problems_are_found(planted):
    a = tyre_analysis(planted[1])
    assert a["available"] and a["has_zones"] and a["has_core"] and a["has_pressure"]
    for w in ("fl", "fr", "rl", "rr"):
        assert a["wheels"][w]["centre_vs_edges"] > 3 and any("over-inflated" in h for h in a["wheels"][w]["hints"])
    assert all(a["wheels"][w]["inner_vs_outer"] < 2 for w in ("fr", "rr"))      # too little camber shows on the loaded side
    assert any("over-inflated" in t and t.startswith("All four") for t in a["tips"])
    p = a["pressures"]["fl"]
    assert p["hot"] > p["cold"] + 0.15 and p["change_cold_by"] < 0                # builds up (in bar), and ends up too high
    assert a["balance"]["front_minus_rear"] > 2


def test_warm_up_heat_map_corners_and_laps(planted):
    a = tyre_analysis(planted[1], window={"temp_lo": 70})
    wu = a["warmups"][0]
    assert wu["kind"] == "start" and wu["all_warm_laps"] is not None and 0.3 < wu["all_warm_laps"] < 4
    assert all(wu["wheels"][w]["start_temp"] < 50 for w in wu["wheels"])          # tyres start cold
    assert len(a["heat"]) > 200 and len(a["corners"]) == 6 and a["hot_spots"]
    assert all(c["hottest"] in ("fl", "fr", "rl", "rr") for c in a["corners"])
    warm_laps = [r for r in a["laps"] if r["warm"]]
    assert warm_laps and not a["laps"][0]["warm"]                                 # the out lap is a warm-up lap
    n = len(a["timeline"]["t"])
    assert all(len(a["timeline"][w]["middle"]) == n and len(a["timeline"][w]["press"]) == n for w in ("fl", "fr", "rl", "rr"))
    assert a["best_band"] and a["best_band"][0] <= a["best_band"][1]


def test_neutral_setup_gets_no_pressure_warning(tmp_path):
    a = tyre_analysis(_practice(tmp_path, {}, laps=6))
    assert all(a["wheels"][w]["centre_vs_edges"] < 3 for w in ("fl", "fr", "rl", "rr"))
    assert not any("over-inflated" in t for t in a["tips"])


def test_operating_window_setting(planted):
    root, rec = planted
    app = App(root)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"

    def call(m, path, body=None):
        req = urllib.request.Request(base + path.lstrip("/"), method=m, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        _, t = call("GET", f"/api/tyres?recording={rec.name}")
        assert t["available"] and t["window"]["temp_lo"] == 80
        car = t["car"]
        assert call("POST", "/api/tyres/window", {"car": car, "window": {"temp_lo": 70, "temp_hi": 95, "press_lo": 1.85, "press_hi": 1.95}})[0] == 200
        _, t2 = call("GET", f"/api/tyres?recording={rec.name}")
        assert t2["window"]["temp_lo"] == 70 and t2["wheels"]["fl"]["in_window"] != t["wheels"]["fl"]["in_window"]
        assert call("POST", "/api/tyres/window", {"car": car, "window": {"temp_lo": 100, "temp_hi": 90}})[0] == 400
        call("POST", "/api/tyres/window", {"car": car, "window": None})
        assert call("GET", f"/api/tyres?recording={rec.name}")[1]["window"]["temp_lo"] == 80
    finally:
        srv.shutdown()


@pytest.mark.skipif(not RBR.exists(), reason="real Red Bull Ring recording not present")
def test_recording_from_before_tyre_data():
    a = tyre_analysis(RBR / "recordings" / "20261003-152233_Spielberg_qualify")
    assert not a["available"] and "older recorder" in a["reason"]



def test_pressure_units():
    from ams2season.tyres import to_bar
    assert abs(float(np.median(to_bar(np.array([186.6, 184.7])))) - 1.857) < 0.01    # real AMS2: kilopascals
    assert abs(float(to_bar(np.array([27.0]))[0]) - 1.862) < 0.01                    # PSI
    assert abs(float(to_bar(np.array([1.86]))[0]) - 1.86) < 1e-9                      # already bar
