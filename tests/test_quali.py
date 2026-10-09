"""Qualifying analysis, ghost entries, and merging a friend's recording of the same session."""
import json

import numpy as np
import pandas as pd
import pytest

from ams2season import shm as S
from ams2season.derive import Session
from ams2season.quali import analyze_qualifying, quali_data
from ams2season.race import analyze_race
from ams2season.simulate import RaceScript, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]


def _close_laps(tmp_path, local_name):
    # Two valid flying laps differ by only 15 ms, as in the Testing recording.
    t = np.arange(0.05, 306, 0.05)
    crossings = [0, 100, 200.015, 300.015, 400.015]
    dist = np.interp(t, crossings, np.arange(5) * 1000)
    angle = dist / 1000 * 2 * np.pi
    fr = pd.DataFrame({"t": t, "name": "AI", "car": "GT3", "car_class": "Testing",
                       "lap_dist": dist % 1000, "laps_completed": (dist // 1000).astype(int),
                       "speed": 10.0, "x": 160 * np.cos(angle), "z": 160 * np.sin(angle),
                       "race_state": S.RACESTATE_RACING, "pit_mode": 0, "lap_invalid": False,
                       "last_lap": np.where(t < 100, 0, np.where(t < 200.015, 100.5,
                                              np.where(t < 300.015, 100.015, 100.0))),
                       "fastest_lap": np.where(t < 200.015, 0, np.where(t < 300.015, 100.015, 100.0)),
                       "cur_s1": 30.0, "cur_s2": 30.0})
    lo = pd.DataFrame({"t": t, "throttle": np.where(t < 200.015, 0.3, 0.9),
                       "brake": 0.0, "steering": 0.0, "gear": 3})
    return Session(tmp_path, {"track_length": 1000, "local": {"name": local_name}}, fr, lo)


def test_best_lap_prefers_exact_time_over_earlier_near_match(tmp_path):
    qa = analyze_qualifying(_close_laps(tmp_path, "Observer"), humans={"Observer"})
    assert qa.classification.best.iat[0] == pytest.approx(100.0)
    assert qa.classification.lap_no.iat[0] == 2


def test_friend_inputs_use_closest_lap_time(tmp_path, monkeypatch):
    own = _close_laps(tmp_path, "Observer")
    friend = _close_laps(tmp_path, "AI")
    monkeypatch.setattr("ams2season.quali.load_session", lambda _: friend)
    qa = analyze_qualifying(own, humans={"Observer"}, extra_recordings=["friend"])
    assert np.median(qa.best["AI"]["thr"]) == pytest.approx(90.0)


def test_long_recording_pause_does_not_invent_empty_qualifying_laps(tmp_path):
    sess = _close_laps(tmp_path, "Observer")
    # Simulation continues from the same position after a 20-minute pause.
    sess.frames.loc[sess.frames.t >= 150, 't'] += 1200
    sess.local.loc[sess.local.t >= 150, 't'] += 1200
    qa = analyze_qualifying(sess, humans={"Observer"})
    assert len(qa.laps) == 1 and qa.laps.valid.all()
    assert qa.classification.best.iat[0] == pytest.approx(100.0)
    assert qa.classification.valid_laps.iat[0] == 1
    assert qa.laps.t0.iat[0] > 1400
    assert np.isfinite(qa.best['AI']['v']).all()
    assert any('gaps' in w for w in qa.warnings)


def test_gap_during_fastest_lap_uses_an_observed_lap_instead(tmp_path):
    sess = _close_laps(tmp_path, "Observer")
    sess.frames = sess.frames[~sess.frames.t.between(230, 245)].copy()
    sess.local = sess.local[~sess.local.t.between(230, 245)].copy()
    qa = analyze_qualifying(sess, humans={"Observer"})
    assert len(qa.laps) == 1
    assert qa.classification.best.iat[0] == pytest.approx(100.015)
    assert qa.laps.t1.iat[0] < 201
    assert any('gaps' in w for w in qa.warnings)


@pytest.fixture(scope="module")
def weekend(tmp_path_factory):
    out = tmp_path_factory.mktemp("q")
    s = RaceScript(laps=3, n_ai=6, with_qualifying=True)
    a = run_race(out, HUMANS, s, seed=12)
    b = run_race(out, HUMANS, s, seed=12, local_human="Mason")  # Mason's PC recorded the same weekend
    pick = lambda dirs, kind: next(d for d in dirs if f"_{kind}" in d.name)
    return {"q_jax": pick(a, "qualify"), "q_mason": pick(b, "qualify"), "out": out}


def test_best_laps_and_deltas(weekend):
    qa = analyze_qualifying(weekend["q_jax"], humans=set(HUMANS))
    cls = qa.classification
    assert len(cls) == 10 and (cls.laps >= 3).all()
    assert cls.best.is_monotonic_increasing and (cls.best > 55).all()
    pole = cls.name.iat[0]
    for r in cls.itertuples():  # the delta trace ends exactly on the official gap
        d = qa.best[r.name]["t"] - qa.best[pole]["t"]
        assert abs(d[-1] - r.gap) < 0.01
    assert len(qa.corners) == 6
    jax = qa.best["Jax"]
    assert "thr" in jax and "steer" in jax and np.ptp(jax["steer"]) > 10  # the recording PC's own inputs
    assert len(jax["brake_pts"]) >= 5 and len(jax["throttle_pts"]) >= 5
    assert "thr" not in qa.best["Mason"]  # not without his recording


def test_friends_recording_adds_their_inputs(weekend):
    qa = analyze_qualifying(weekend["q_jax"], humans=set(HUMANS), extra_recordings=[weekend["q_mason"]])
    assert "thr" in qa.best["Mason"] and qa.best["Mason"]["inputs_from"] == "Mason"
    assert "thr" in qa.best["Jax"]
    d = quali_data(qa)
    flags = {x["name"]: x["has_inputs"] for x in d["drivers"]}
    assert flags["Jax"] and flags["Mason"] and not flags["Eli"]
    json.dumps(d, allow_nan=False)


def test_ghost_duplicate_is_ignored(tmp_path):
    dirs = run_race(tmp_path, HUMANS, RaceScript(laps=3, n_ai=6, ghost_duplicate=True, local_collision_lap=None), seed=8)
    race = next(d for d in dirs if d.name.endswith("_race"))
    truth = json.loads((race / "truth.json").read_text())
    ra = analyze_race(race, humans=set(HUMANS))
    assert any("ignored" in w for w in ra.warnings)
    assert list(ra.classification.name) == truth["classification"]
    assert ra.laps[ra.laps.valid].time.min() > 50


def test_breakdown(weekend):
    from ams2season.quali import quali_breakdown
    qa = analyze_qualifying(weekend["q_jax"], humans=set(HUMANS))
    bd = quali_breakdown(qa)
    assert bd["summary"].startswith(qa.classification.name.iat[0])
    assert len(bd["drivers"]) == len(qa.classification) and len(bd["corner_kings"]) == 6
    ids = {a["id"] for a in bd["awards"]}
    assert {"q_pole", "q_closest", "q_corner_king", "q_top_speed"} <= ids
    d0 = bd["drivers"][0]
    assert set(d0["apex"]) == {c["name"] for c in qa.corners} and d0["interval"] is None
    assert all(len(bd["laps"][d["name"]]) == d["laps"] for d in bd["drivers"])
    json.dumps(bd, default=float)
