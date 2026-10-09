"""Throttle scoring separates shift interruptions, sustained exit power and maintenance modulation."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ams2season import shm as S
from ams2season.derive import Session, load_session
from ams2season.technique import (
    _filter_throttle, _lap_metrics, _scores, _throttle_hesitation, corner_shapes, technique_report,
    throttle_consistency_summary,
    _local_lap_usable, recording_laps,
)


def _lap(throttle, n=2, gear=None):
    ld = np.arange(0, 1000, 2.0)
    return {"n": n, "valid": True, "time": 25.0, "t": ld / 40.0, "ld": ld,
            "throttle": np.asarray(throttle, float), "gear": gear, "brake": np.zeros(len(ld)),
            "speed": np.full(len(ld), 144.0)}


def _shape(laps):
    return corner_shapes(laps, [{"name": "Test", "apex": 400.0}], 1000)[0]


def _shift_trace(depth=100, duration=0.1, before=100, after=100):
    t = np.arange(0, 3, 0.05)
    throttle = np.where(t < 1.0, float(before), float(after))
    throttle[(t >= 1.0) & (t < 1.0 + duration)] = before - depth
    gear = np.where(t < 1.0, 3, np.where(t < 1.1, 0, 4))
    return {"throttle": throttle, "t": t, "gear": gear}


def test_short_shift_cut_is_filtered_and_original_is_untouched():
    lap = _shift_trace()
    original = lap["throttle"].copy()
    filtered, mask = _filter_throttle(lap)
    assert filtered.min() == 100 and mask.sum() == 2
    assert np.array_equal(lap["throttle"], original)


def test_downshift_blip_is_filtered_using_gear_evidence():
    lap = _shift_trace(depth=-70, before=0, after=0)
    lap["gear"] = np.where(lap["t"] < 1, 4, np.where(lap["t"] < 1.1, 0, 3))
    filtered, mask = _filter_throttle(lap)
    assert filtered.max() == 0 and mask.sum() == 2


@pytest.mark.parametrize("case", ["no_gear", "steady_gear", "sustained_lift", "changing_power", "gap"])
def test_a_real_lift_or_insufficient_shift_evidence_is_retained(case):
    lap = _shift_trace(duration=0.7 if case == "sustained_lift" else 0.1,
                       after=50 if case == "changing_power" else 100)
    if case == "no_gear":
        lap.pop("gear")
    elif case == "steady_gear":
        lap["gear"][:] = 4
    elif case == "gap":
        lap["t"][lap["t"] >= 1.1] += 1
    filtered, mask = _filter_throttle(lap)
    assert filtered.min() == 0 and not mask.any()


def test_shift_filtered_analysis_does_not_hide_raw_plot():
    ld = np.arange(0, 1000, 2.0)
    laps = []
    for n, cut in enumerate((500, 530, 560), 2):
        throttle = np.full(len(ld), 100.0)
        throttle[(ld >= cut) & (ld < cut + 4)] = 0
        gear = np.where(ld < cut, 3, np.where(ld < cut + 4, 0, 4))
        laps.append(_lap(throttle, n, gear))
    c = _shape(laps)
    assert c["scores"]["throttle"] == 100
    assert c["throttle"]["shift_transients"] == 3
    assert min(c["throttle"]["best"]) == 0
    assert min(c["throttle"]["analysis_mean"]) == 100
    assert {r["throttle_kind"] for r in c["laps"]} == {"flat_out"}
    assert all(r["pickup"] is None for r in c["laps"])


def test_small_jitter_and_modulation_are_distinct_from_large_lifts():
    ld = np.arange(0, 1000, 2.0)
    clean = _shape([_lap(np.full(len(ld), 100.0), n) for n in range(2, 5)])
    minor, major = [], []
    for n in range(2, 5):
        little, large = np.full(len(ld), 100.0), np.full(len(ld), 100.0)
        for start in (440, 520, 600):
            little[(ld >= start) & (ld < start + 12)] = 92
            large[(ld >= start) & (ld < start + 32)] = 10
        minor.append(_lap(little, n)); major.append(_lap(large, n))
    modest, deep = _shape(minor), _shape(major)
    assert clean["scores"]["throttle"] == 100
    assert 94 <= modest["scores"]["throttle"] < 100
    assert deep["scores"]["throttle"] <= modest["scores"]["throttle"] - 15
    assert deep["scatter"]["throttle_hesitation_penalty"] > modest["scatter"]["throttle_hesitation_penalty"]


def test_fast_modulated_corner_does_not_invent_arbitrary_pickups():
    ld = np.arange(0, 1000, 2.0)
    laps = [_lap(np.clip(68 + 26 * np.sin(ld / 22 + phase), 0, 100), n)
            for n, phase in enumerate((0, 0.5, 1.0, 1.5), 2)]
    c = _shape(laps)
    assert 65 <= c["scores"]["throttle"] < 100
    assert c["scatter"]["throttle_marker_laps"] == 0
    assert c["scatter"]["throttle_modulated_laps"] == 4
    assert all(r["pickup"] is None for r in c["laps"])


def test_ramp_shape_is_compared_separately_from_pickup_timing():
    x = np.arange(-60, 322, 2.0)
    T = np.vstack([np.clip((x - pickup) * 2.5, 0, 100) for pickup in (0, 20, 40)])
    rows = [{"onset": None, "pickup": p, "throttle_kind": "exit"} for p in (0, 20, 40)]
    score, scatter = _scores(np.zeros((3, 191)), T, rows, np.ones(3))
    assert scatter["throttle_dev"] < 0.01
    assert scatter["throttle_pickup_penalty"] > 10
    assert 80 <= score["throttle"] < 100


def test_marker_absence_and_excluded_laps_are_not_zero_metre_pickups():
    T = np.tile(np.linspace(30, 100, 191), (3, 1))
    rows = [{"onset": None, "pickup": p, "throttle_kind": kind}
            for p, kind in ((10, "exit"), (None, "modulated"), (200, "exit"))]
    _, scatter = _scores(np.zeros_like(T), T, rows, np.array([1, 1, 0]))
    assert scatter["pickup_sd"] == 0
    assert scatter["throttle_marker_laps"] == 1


def test_summary_provides_real_pedal_ratings_without_inventing_missing_data():
    assert throttle_consistency_summary({"available": False}) == {"equal": None, "reduced": None, "excluded": None}
    assert throttle_consistency_summary({"available": True, "summary_by_mode": {
        "equal": {"throttle": 63}, "reduced": {"throttle": 68}}}) == {"equal": 63, "reduced": 68, "excluded": None}


def _local_identity_session(tmp_path):
    t = np.arange(0, 200.2, 0.1)
    distance = 20 * t
    frames = pd.DataFrame({"name": "Jax", "slot": 0, "t": t, "lap_dist": distance % 1000,
        "laps_completed": (distance // 1000).astype(int), "speed": 20.0,
        "race_state": S.RACESTATE_RACING, "last_lap": 50.0, "lap_invalid": False,
        "pit_mode": 0, "cur_s1": 15.0, "cur_s2": 15.0})
    local = pd.DataFrame({"t": t, "viewed_slot": 0, "speed": 20.0, "throttle": 0.7, "brake": 0.0})
    return Session(tmp_path, {"track_length": 1000, "green_t": 0, "session_type": "race",
                             "local": {"name": "Jax"}}, frames, local)


@pytest.mark.parametrize("issue,expected", [("gap", [3, 4]), ("different_car", [2, 4]),
                                            ("missing_pedal", [2, 4]), ("truncated", [3, 4])])
def test_bad_local_coverage_rejects_only_affected_laps(tmp_path, issue, expected):
    sess = _local_identity_session(tmp_path)
    if issue == "gap":
        sess.local = sess.local[~sess.local.t.between(70, 75)].copy()
    elif issue == "different_car":
        sess.local.loc[sess.local.t.between(120, 120.2), "viewed_slot"] = 1
    elif issue == "missing_pedal":
        sess.local.loc[sess.local.t.between(120, 120.2), "throttle"] = np.nan
    else:
        sess.local = sess.local[sess.local.t >= 70].copy()
    _, laps, _ = recording_laps(sess)
    assert [lp["n"] for lp in laps] == expected


def test_local_identity_can_follow_a_discrete_slot_change(tmp_path):
    sess = _local_identity_session(tmp_path)
    sess.frames.loc[sess.frames.t >= 100, "slot"] = 2
    sess.local.loc[sess.local.t >= 100, "viewed_slot"] = 2
    _, laps, _ = recording_laps(sess)
    assert [lp["n"] for lp in laps] == [2, 3, 4]
    assert _local_lap_usable(sess.local, sess.frames, 100, 150)


def test_all_wrong_car_pedals_are_unavailable_instead_of_scored(tmp_path):
    sess = _local_identity_session(tmp_path)
    sess.local["viewed_slot"] = 1
    report = technique_report(sess)
    assert report["available"] is False
    assert report["driver"] == "Jax"
    assert throttle_consistency_summary(report)["reduced"] is None


def test_missing_input_channel_preserves_known_driver_without_throwing(tmp_path):
    sess = _local_identity_session(tmp_path)
    sess.local = sess.local.drop(columns="speed")
    report = technique_report(sess)
    assert report["available"] is False and report["driver"] == "Jax"


@pytest.mark.parametrize("unsafe_inputs", ["wrong_viewed_participant", "missing_coverage"])
def test_race_and_profile_do_not_fall_back_to_acceleration_for_unsafe_player_pedals(tmp_path, unsafe_inputs):
    from ams2season.legends import scores_from_raw
    from ams2season.profiles import measurements
    from ams2season.race import analyze_race
    from ams2season.simulate import RaceScript, run_race

    path = next(p for p in run_race(tmp_path / "recordings", ["Jax", "Mason"],
        RaceScript(laps=3, n_ai=2, local_collision_lap=None), seed=6) if p.name.endswith("_race"))
    sess = load_session(path)
    # Mutate only this disposable in-memory session. Participant timing remains intact, so the
    # acceleration proxy would otherwise continue looking available while player pedals are unsafe.
    if unsafe_inputs == "wrong_viewed_participant":
        sess.local = sess.local.assign(viewed_slot=-1)
    else:
        sess.local = sess.local.iloc[[0, -1]].copy()
    analysis = analyze_race(sess, humans={"jax", "mason"})
    player = analysis.stats.set_index("name").loc["Jax"]
    assert player.throttle_rating_source == "unavailable"
    assert pd.isna(player.throttle_consistency)
    assert all(pd.isna(player[f"throttle_consistency_{mode}"]) for mode in ("equal", "reduced", "excluded"))
    raw = measurements(analysis)["Jax"]["raw"]
    assert raw["throttle_consistency"] is None
    assert scores_from_raw(raw)["throttle"] is None
    assert set(analysis.stats.loc[analysis.stats.name != "Jax", "throttle_rating_source"]) == {"acceleration"}


def test_hesitation_cost_uses_depth_and_duration_not_sample_count():
    def cost(hz, depth):
        t = np.arange(0, 2, 1 / hz)
        T = np.where((t >= 0.5) & (t < 1), 100 - depth, 100.0)
        return _throttle_hesitation(T, t)
    assert cost(20, 60)[0] == cost(50, 60)[0] == 1
    assert cost(20, 60)[1] == pytest.approx(cost(50, 60)[1], abs=0.1)
    assert 0 < cost(20, 8)[1] < cost(20, 60)[1] / 10


def test_genuine_lift_after_first_full_power_is_still_assessed():
    xb, xt, xs = np.arange(-320, 62, 2.0), np.arange(-60, 322, 2.0), np.arange(-150, 102, 2.0)
    B = np.where((xb >= -100) & (xb < -20), 80.0, 0.0)
    T = np.where(xt >= 0, 100.0, 0.0)
    T[(xt >= 80) & (xt < 120)] = 20
    result = _lap_metrics(xb, B, xt, T, xs, 100 + abs(xs) / 2, throttle_times=xt / 40)
    assert result["full"] == 0 and result["hesitations"] == 1
    assert result["throttle_hesitation_penalty"] > 10


_WATKINS = Path(__file__).resolve().parents[1] / "recordings" / "20261008-214419_Watkins-Glen_Watkins-Glen-GPIL_race"


@pytest.mark.skipif(not (_WATKINS / "local.parquet").exists(), reason="Optional installed-app real recording")
def test_watkins_fast_corner_regression_read_only():
    report = technique_report(_WATKINS, [{"name": name, "apex": apex}
        for name, apex in (("T1", 355), ("T2", 2015), ("T3", 2262.5), ("T4", 2825),
                           ("T5", 3325), ("T6", 4017.5), ("T7", 4377.5), ("T8", 4775), ("T9", 5087.5))])
    cs = {c["corner"]: c for c in report["corners"]}
    assert cs["T3"]["scores"]["throttle"] >= 50  # previously 10
    assert cs["T9"]["scores"]["throttle"] >= 50  # previously 0
    assert cs["T3"]["scores"]["throttle"] < 95  # substantial variation remains visible
    assert sum(c["throttle"]["shift_transients"] for c in cs.values()) > 0
