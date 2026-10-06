"""Practice objectives, pedal-shape technique analysis, tyre care and teams."""
from datetime import datetime

import pytest

from ams2season.practice import PracticeTracker, describe
from ams2season.recorder import Recorder
from ams2season.simulate import practice_drive
from ams2season.technique import technique_report


def _record(tmp_path, **kw):
    rec = Recorder(tmp_path, hz=20, log=lambda *_: None, wallclock=lambda: datetime(2026, 10, 1, 19, 0))
    now = 0
    for snap, t in practice_drive(**kw):
        now = t
        rec.step(snap, now)
    rec.close(now + 1)
    return rec.completed[-1]


@pytest.fixture(scope="module")
def sessions(tmp_path_factory):
    d = tmp_path_factory.mktemp("prac")
    return {"steady": _record(d, laps=7, seed=1, consistency=2.0, tyre_wear=0.8, lockup_rate=0.0, spin_rate=0.0),
            "scrappy": _record(d, laps=7, seed=2, consistency=8.0, tyre_wear=1.4, lockup_rate=0.25, spin_rate=0.25)}


def test_practice_sessions_are_recorded(sessions):
    assert sessions["steady"].name.endswith("_practice")


def test_shape_consistency_separates_drivers(sessions):
    a, b = technique_report(sessions["steady"]), technique_report(sessions["scrappy"])
    assert a["available"] and b["available"] and len(a["corners"]) == 6
    assert a["summary"]["overall"] >= b["summary"]["overall"] + 12
    assert b["summary"]["least_consistent"] == "T2"  # the simulator makes T2 the hardest corner to repeat
    c = a["corners"][0]
    assert c["braking"] and 80 <= -c["typical"]["onset"] <= 180 and c["typical"]["peak"] > 60
    assert len(c["brake"]["mean"]) == len(c["brake"]["x"]) and c["brake"]["best"] is not None
    assert b["corners"][1]["scatter"]["onset_sd"] > a["corners"][1]["scatter"]["onset_sd"] * 2


def test_tyre_report(sessions):
    a, b = technique_report(sessions["steady"])["tyres"], technique_report(sessions["scrappy"])["tyres"]
    assert abs(a["radius"]["fl"] - 0.335) < 0.002 and abs(a["radius"]["rr"] - 0.345) < 0.002  # learned from steady driving
    assert a["lockups"] == 0 and a["wheelspin"] == 0
    assert b["lockups"] > 0 and b["wheelspin"] > 0
    assert b["wear_per_lap_avg"] > a["wear_per_lap_avg"] * 1.4 and a["wear_enabled"]


def test_practice_objectives_live():
    objs = [{"id": "consistency", "laps": 3, "pct": 101.0}, {"id": "clean_streak", "laps": 3},
            {"id": "brake_points", "laps": 2, "tolerance": 8}, {"id": "target", "offset": 0.05},
            {"id": "smooth", "laps": 2}, {"id": "sector", "sector": 2, "gain": 5.0}]
    tr = PracticeTracker(objs, pb_lookup=lambda *a: 64.5)
    for snap, t in practice_drive(laps=7, seed=4, consistency=2.0, invalid_laps=(3,), lockup_rate=0.0, spin_rate=0.0):
        tr.feed(snap, t)
    st = tr.status()
    laps = st["laps"]
    assert laps[0]["out"] and not laps[2]["valid"] and all(l["s1"] and l["s3"] for l in laps[1:])
    assert st["pb"] == 64.5 and st["corners"] == ["T1", "T2", "T3", "T4", "T5", "T6"]
    by = {o["id"]: o for o in st["objectives"]}
    assert by["consistency"]["done"] and by["clean_streak"]["done"] and by["target"]["done"] and by["smooth"]["done"]
    assert by["brake_points"]["done"]
    assert not by["sector"]["done"]  # 5 s off a sector is impossible
    assert "3 clean laps in a row within 101.0%" in describe(by["consistency"])
