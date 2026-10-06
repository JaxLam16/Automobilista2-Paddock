"""Qualifying analysis, ghost entries, and merging a friend's recording of the same session."""
import json

import numpy as np
import pytest

from ams2season.quali import analyze_qualifying, quali_data
from ams2season.race import analyze_race
from ams2season.simulate import RaceScript, run_race

HUMANS = ["Jax", "Mason", "Eli", "Theo"]


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
