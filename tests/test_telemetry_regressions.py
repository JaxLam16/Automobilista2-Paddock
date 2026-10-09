"""Reported telemetry failures: main pedal events, grid order, timing, achievable scores and backfill."""
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ams2season import shm as S
from ams2season.derive import Session, add_distance, completed_lap_time, curvature_profile, detect_corners
from ams2season.legends import scores_from_raw
from ams2season.metrics import _corner_usage, _usage_score, race_pace
from ams2season.overtakes import overtaking
from ams2season.passes import Grid, PassParams, detect_passes
from ams2season.race import COUNTED
from ams2season.season import ANALYSIS_VERSION, SeasonConfig, add_correction, connect, ingest, refresh_analysis
from ams2season.simulate import TRACK, RaceScript, _build_centreline, run_race, v_ref
from ams2season.technique import _brake_event, _lap_metrics, corner_shapes, recording_laps


def test_lap_time_uses_updated_value_after_line():
    t = np.array([109.9, 110.0, 110.1, 110.2, 111.0])
    value, game = completed_lap_time(t, np.array([108.0, 108.0, 108.0, 107.35, 107.35]), 110.05, 107.36)
    assert value == 107.35 and game
    assert completed_lap_time(t, np.zeros(5), 110.05, 107.36) == (107.36, False)


def test_zero_distance_grid_prefix_keeps_real_order():
    t = np.arange(21, dtype=float)
    parts = []
    for name, first, reading in (("Rear", 5, 2.0), ("Front", 3, 1.0)):
        parts.append(pd.DataFrame({"name": name, "t": t, "lap_dist": np.where(t < first, 0, reading + 15 * (t - first)),
                                   "laps_completed": 0, "speed": 15.0}))
    fr = add_distance(pd.concat(parts, ignore_index=True), 1000, 0)
    initial = fr[fr.t == 0].set_index("name").dist
    assert initial.Rear == pytest.approx(-73) and initial.Front == pytest.approx(-44)
    for _, g in fr.groupby("name"):
        assert np.allclose(np.diff(g.dist), 15)


def test_non_round_track_length_keeps_corner_direction():
    ld, x, z, _, _ = _build_centreline()
    L = TRACK["length"] + 3.7
    kap = curvature_profile(ld * L / TRACK["length"], x, z, L)
    prof = np.array([v_ref((i * 10 + 5) * TRACK["length"] / L) for i in range(int(np.ceil(L / 10)))])
    assert len(kap) == len(prof)
    cs = detect_corners(prof, curvature=kap)
    assert len(cs) >= 6 and all(c.get("dir") in ("left", "right") for c in cs)


def _pedals():
    xb, xt, xs = np.arange(-320, 62, 2.0), np.arange(-60, 322, 2.0), np.arange(-150, 102, 2.0)
    B = np.where((xb >= -140) & (xb <= -30), 80.0, 0.0)
    T = np.where(xt >= 40, 100.0, 0.0)
    return xb, B, xt, T, xs, 80 + abs(xs) / 2


def test_braking_marker_ignores_touches_and_previous_corner_tail():
    xb, B, xt, T, xs, V = _pedals()
    clean = _lap_metrics(xb, B, xt, T, xs, V)
    B[(xb <= -260)] = 90             # previous corner is already braking at the window boundary
    B[(xb >= -220) & (xb <= -212)] = 10
    B[(xb >= -190) & (xb <= -188)] = 100  # isolated hard spike
    filtered = _lap_metrics(xb, B, xt, T, xs, V)
    assert filtered["onset"] == clean["onset"] == -140
    assert filtered["peak"] == 80


def test_small_brake_touch_does_not_become_a_braking_corner():
    xb, B, xt, T, xs, V = _pedals()
    B[:] = 0
    B[(xb >= -250) & (xb <= -190)] = 8
    assert _lap_metrics(xb, B, xt, T, xs, V)["onset"] is None


def test_main_braking_can_start_before_neighbour_midpoint():
    xb, B, *_ = _pedals()
    B = np.maximum(0, 80 * (1 - abs(xb + 50) / 100))
    event = _brake_event(xb, B, (-80, 20))
    assert event is not None
    assert -150 < xb[event[1]] < -80 and abs(xb[event[2]] + 50) <= 2


def test_throttle_blip_does_not_set_pickup():
    xb, B, xt, T, xs, V = _pedals()
    T[(xt >= -8) & (xt <= -4)] = 80
    assert _lap_metrics(xb, B, xt, T, xs, V)["pickup"] == 40


def test_exit_power_can_begin_before_minimum_speed():
    xb, B, xt, T, xs, V = _pedals()
    T = np.where(xt >= -20, 100.0, 0.0)
    V = 80 + abs(xs - 20) / 2
    m = _lap_metrics(xb, B, xt, T, xs, V)
    assert m["min_speed_at"] == 20 and m["pickup"] == -20


def test_neighbouring_corner_is_visible_but_not_in_scatter():
    ld = np.arange(0, 1000, 2.0)
    laps = []
    for n, start in enumerate((310, 320, 330, 340), 2):
        brake = np.where((ld >= 500) & (ld <= 540), 80.0, 0.0)
        brake[(ld >= start) & (ld <= start + 20)] = 70
        laps.append({"n": n, "valid": True, "time": 60.0, "ld": ld, "brake": brake,
                     "throttle": np.where(ld >= 620, 100.0, 0.0), "speed": 80 + abs(ld - 600) / 3})
    c = next(c for c in corner_shapes(laps, [{"name": "Previous", "apex": 300}, {"name": "Current", "apex": 600}], 1000) if c["corner"] == "Current")
    assert c["scatter"]["onset_sd"] == 0
    assert {r["onset"] for r in c["laps"]} == {-100}
    assert max(c["brake"]["mean"][:50]) > 0  # keep the original raw traces reviewable


def test_race_technique_excludes_start_and_cooldown_and_keeps_lap_numbers(tmp_path):
    t = np.arange(0, 200.2, 0.1)
    dist = 20 * t
    fr = pd.DataFrame({"name": "Jax", "t": t, "lap_dist": dist % 1000, "laps_completed": (dist // 1000).astype(int),
                       "speed": 20.0, "race_state": np.where(t >= 150.1, S.RACESTATE_FINISHED, S.RACESTATE_RACING),
                       "last_lap": 50.0, "lap_invalid": False, "pit_mode": 0, "cur_s1": 15.0, "cur_s2": 15.0})
    lo = pd.DataFrame({"t": t, "speed": 20.0, "throttle": 0.5, "brake": 0.0})
    sess = Session(tmp_path, {"track_length": 1000, "green_t": 0, "session_type": "race", "local": {"name": "Jax"}}, fr, lo)
    _, laps, _ = recording_laps(sess)
    assert [l["n"] for l in laps] == [2, 3]
    assert all(l["time"] == 50 for l in laps)


def test_track_usage_high_nineties_are_achievable_without_one_spike():
    L, ld = 500.0, np.arange(0, 500, 2.0)
    left, right = np.full(100, 6.0), np.full(100, -6.0)
    c = {"apex": 250.0, "dir": "left", "radius": 80}
    # A smooth outside-inside-outside line, rather than discontinuous edge jumps.
    ideal = -5.15 + 10.3 * np.exp(-((ld - 250) / 48) ** 4)
    assert _corner_usage(ld, ideal, c, L, left, right, L, L)[0] >= 99
    middle = np.zeros(len(ld))
    assert _corner_usage(ld, middle, c, L, left, right, L, L)[0] == 0
    middle[np.argmin(abs(ld - 250))] = 5.15
    assert _corner_usage(ld, middle, c, L, left, right, L, L)[0] < 5
    assert _usage_score(0.3, 12) == 100
    assert _usage_score(1, 12) > _usage_score(2, 12) > _usage_score(4, 12)


def test_profile_scales_keep_moderate_scores_and_missing_data():
    s = scores_from_raw({"lap_cv_pct": 3.0, "clean_share": 65})
    assert 30 < s["consistency"] < 31 and s["clean"] == 65
    assert scores_from_raw({})["consistency"] is None and scores_from_raw({})["clean"] is None


def _crossing_grid(lapped=False, full_lap=False):
    t = np.arange(0, 30, 0.1)
    d = np.vstack([40 * t + (1000 if full_lap else 0), 39 * t + 10])
    pos = np.vstack([np.where((t < 10) & (not lapped), 2, 1), np.where((t < 10) & (not lapped), 1, 2)])
    return Grid(t, ["A", "B"], d, pos, np.ones_like(d, bool), np.zeros_like(d, int),
                np.full_like(d, 40), np.zeros_like(d, bool))


def test_lapping_requires_a_race_position_exchange():
    p = PassParams()
    ordinary = detect_passes(_crossing_grid(), 1000, [], np.full(100, 40), p=p)
    assert len(ordinary) == 1 and ordinary.kind.iat[0] in COUNTED
    already_ahead = detect_passes(_crossing_grid(lapped=True), 1000, [], np.full(100, 40), p=p)
    assert len(already_ahead) == 1 and already_ahead.kind.iat[0] == "unconfirmed"
    assert detect_passes(_crossing_grid(lapped=True, full_lap=True), 1000, [], np.full(100, 40), p=p).empty


def test_unconfirmed_and_pit_cycles_do_not_count_as_being_passed():
    laps = pd.DataFrame([{"name": n, "lap": lap, "t_end": 60 * lap + i * 0.5, "time": 60.0, "clean": True, "pit": False}
                         for lap in range(1, 7) for i, n in enumerate(("A", "B"))])
    passes = pd.DataFrame([{"t": 100 + i, "lap": 2, "corner": "T1", "passer": "B", "passed": "A", "kind": k}
                           for i, k in enumerate(("clean", "pit_cycle", "unconfirmed"))])
    ra = SimpleNamespace(laps=laps, passes=passes, entrants=pd.DataFrame({"name": ["A", "B"], "is_ai": [False, False]}),
                         classification=pd.DataFrame({"name": ["A", "B"], "pos": [1, 2], "grid": [1, 2]}))
    o = {d["name"]: d for d in overtaking(ra)["drivers"]}
    assert o["B"]["made"] == 1 and o["A"]["lost"] == 1


def test_pace_average_remains_available_for_a_short_race():
    laps = pd.DataFrame([{"name": "Jax", "lap": lap, "t_end": lap * 100.0, "time": lap_time, "clean": True, "pit": False}
                         for lap, lap_time in enumerate((105, 100, 100, 106), 1)])
    d = race_pace(laps, {"Jax": False})["drivers"][0]
    assert d["average"] == 102 and d["median"] == 100 and d["representative_laps"] == 3
    assert d["thirds"] is None and d["trend"] is None
    assert sum(d[k]["laps"] for k in ("clean_air", "traffic", "mixed")) == 3


def test_season_refresh_preserves_penalties_notes_and_missing_recordings(tmp_path, monkeypatch):
    path = next(p for p in run_race(tmp_path / "recordings", ["Jax", "Mason"], RaceScript(laps=3, n_ai=2, local_collision_lap=None), seed=6) if p.name.endswith("_race"))
    db = tmp_path / "champ.db"
    cfg = SeasonConfig(drivers=[{"key": "jax", "display": "Jax"}, {"key": "mason", "display": "Mason"}])
    ingest(db, cfg, path, 1, note="Keep this event note")
    add_correction(db, 1, "jax", "points", -3, note="Keep this penalty")
    con = connect(db)
    with con:
        for row in con.execute("SELECT entrant_id,stats FROM result").fetchall():
            s = json.loads(row["stats"]); s.pop("_analysis_v", None); s["track_usage"] = 1
            con.execute("UPDATE result SET stats=? WHERE entrant_id=?", (json.dumps(s), row["entrant_id"]))
    con.close()
    assert refresh_analysis(db, cfg) == []
    con = connect(db)
    assert all(json.loads(r[0])["_analysis_v"] == ANALYSIS_VERSION for r in con.execute("SELECT stats FROM result"))
    assert con.execute("SELECT note FROM event").fetchone()[0] == "Keep this event note"
    assert tuple(con.execute("SELECT value,note FROM correction").fetchone()) == (-3, "Keep this penalty")
    con.close()
    monkeypatch.setattr("ams2season.season.ingest", lambda *a, **k: pytest.fail("Current analysis should not be repeated"))
    assert refresh_analysis(db, cfg) == []
    con = connect(db)
    with con:
        con.execute("UPDATE result SET stats='{}'")
    con.close()
    (path / "frames.parquet").rename(path / "frames.saved")
    assert "recording missing" in refresh_analysis(db, cfg)[0]
    con = connect(db)
    assert con.execute("SELECT COUNT(*) FROM result").fetchone()[0] == 4
    con.close()


@pytest.mark.skipif(not shutil.which("node"), reason="Node is needed for the browser timing module")
def test_replay_time_gaps():
    script = Path(__file__).with_name("replay_timing_cases.cjs")
    subprocess.run([shutil.which("node"), str(script)], check=True, capture_output=True, text=True)
