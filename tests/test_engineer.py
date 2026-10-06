"""The race engineer: settings catalogue, rules, category colours, learning per tick, the run workflow on real
AMS2 telemetry, and the live tracker's run detection."""
import json
import threading
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ams2season.engineer import engine
from ams2season.engineer.catalog import CATEGORIES, SETTINGS, action_text
from ams2season.engineer.store import EngineerStore

DATA = Path(__file__).parent / "data" / "engineer"


def test_catalogue_covers_every_category():
    keys = [s["key"] for s in SETTINGS]
    assert len(keys) == len(set(keys)) and len(keys) > 70
    for c, _ in CATEGORIES:   # every category has settings that serve it
        assert any(s["category"] == c or c in s["also"] for s in SETTINGS), c
    assert action_text("arb_rear", -2) == "Soften by 2 ticks"
    assert action_text("camber_fl", 1) == "More negative camber by 1 tick"
    from ams2season.engineer.catalog import garage_hint
    assert "further below zero" in garage_hint("camber_fl", 1) and "towards zero" in garage_hint("camber_fl", -1)
    assert "goes up" in garage_hint("final_drive", 1) and "shorter" in garage_hint("final_drive", 1)
    assert "check the description" in garage_hint("traction_control", 1)
    assert action_text("final_drive", 3) == "Shorten by 3 ticks"


def _m(**kw):
    base = {"n_flying": 4, "laps": [], "corners": [], "corner_balance": {}, "countersteer": {"entry": 0, "mid": 0, "exit": 0, "lift": 0, "fast": 0},
            "fast_gradient": 0.3, "full_throttle_share": 0.5, "steer_max": 0.5}
    base.update(kw)
    return base


def test_rules_follow_the_evidence():
    st = {"press_window": (1.80, 1.95)}
    m = _m(tyres={"fl": {"press_hot_bar": 2.02, "inner_minus_outer": 0.5}, "fr": {"press_hot_bar": 1.87, "inner_minus_outer": 5.0}},
           gearing={"num_gears": 6, "max_rpm": 7500, "top_gear_rpm_frac": 0.85, "limiter_top_s_lap": 0.0},
           thermals={"water_c": 104.0, "oil_c": 110.0}, countersteer={"entry": 0.5, "mid": 0.0, "exit": 0.0, "lift": 0.0, "fast": 0.0})
    recs = {r["setting"]: r for r in engine.recommend(m, st)}
    assert recs["pressure_fl"]["ticks"] < 0 and "pressure_fr" not in recs          # too high; the other is fine
    assert recs["camber_fl"]["ticks"] > 0 and "camber_fr" not in recs              # outside hotter: more negative camber
    assert recs["final_drive"]["ticks"] > 0                                         # shorten: top gear never near the limiter
    assert recs["radiator"]["ticks"] > 0 and recs["brake_bias"]["ticks"] > 0        # engine hot; rear unsettled on entry
    assert all(r["why"] and r["confidence"] in ("high", "medium", "low") for r in recs.values())
    st2 = dict(st, unavailable=["radiator"], maxed={"final_drive": "up"})
    recs2 = {r["setting"] for r in engine.recommend(m, st2)}
    assert "radiator" not in recs2 and "final_drive" not in recs2                   # not on this car / used up


def test_category_colours():
    m = _m(fuel={"per_lap_l": 2.8}, gearing={"num_gears": 6}, platform={"fl": {}}, tyres={"fl": {}}, braking={"x": 1}, thermals={"water_c": 90})
    recs = [{"category": "gearing", "ticks": 3, "setting": "final_drive"}, {"category": "tyre_contact", "ticks": 1, "setting": "pressure_fl"}]
    c = engine.categories(m, recs, {"runs_analysed": 2, "clean_streak": {"pit_strategy": 2, "thermals": 1}})
    assert c["gearing"]["color"] == "orange" and c["tyre_contact"]["color"] == "yellow"
    assert c["pit_strategy"]["color"] == "blue" and c["thermals"]["color"] == "green"
    assert engine.categories(None, [], {})["gearing"]["color"] == "red"
    lower = [{"category": "ground_clearance", "ticks": -4, "setting": f"ride_height_{w}"} for w in ("fl", "fr", "rl", "rr")]
    gc = engine.categories(m, lower, {})["ground_clearance"]
    assert gc["color"] == "orange" and gc["text"] == "2 changes needed"      # two axles, not sixteen ticks


def test_downforce_level_is_tested_with_both_wings():
    recs = engine.recommend(_m(full_throttle_share=0.7), {})
    dl = [r for r in recs if r["category"] == "downforce"]
    assert {r["setting"] for r in dl} == {"downforce_front", "downforce_rear"} and all(r["ticks"] == -1 and r["test"] for r in dl)
    assert not [r for r in engine.recommend(_m(full_throttle_share=0.7), {"tested": {"downforce_level": True}}) if r["category"] == "downforce"]


@pytest.fixture(scope="module")
def runs():
    if not DATA.exists():
        pytest.skip("real engineer test data not present")
    return {k: pd.read_parquet(DATA / f"{k}.parquet") for k in ("ra_ferrari_baseline", "ra_ferrari_wing2_frontarb2")}


def test_workflow_on_real_runs(runs, tmp_path):
    st = EngineerStore(tmp_path)
    s = st.create("Ferrari 488 GT3", "Road_America", "Road_America_RC", {"mode": "time", "minutes": 60})
    s = st.add_run(s["key"], runs["ra_ferrari_baseline"], 6440.41, "session 1")
    r1 = s["runs"][-1]
    assert r1["measure"]["n_flying"] >= 1 and len(r1["measure"]["corners"]) >= 8
    assert any(r["setting"] == "final_drive" and r["ticks"] > 0 for r in r1["recommendations"])   # 6th gear never near the limiter
    assert s["next_run"]["fuel_l"] >= 100 and s["race_fuel"]["litres"] > 60                        # 25 L was a low-fuel run: full tank next; race fuel for 60 min
    assert s["flags"]["low_fuel_done"] and not s["flags"].get("high_fuel_done")
    s = st.decide(s["key"], {}, manual=[{"setting": "downforce_rear", "ticks": 2}, {"setting": "arb_front", "ticks": 2}])
    assert s["ticks"] == {"downforce_rear": 2, "arb_front": 2}
    s = st.add_run(s["key"], runs["ra_ferrari_wing2_frontarb2"], 6440.41, "session 2")
    r2 = s["runs"][-1]
    assert r2["compare"]["balance_change"] > 0.1 and r2["compare"]["corners_more_understeer"] >= 7   # it sees the extra understeer
    assert s["learned"]["fast_gradient"]["per_tick"] > 0                                             # and learns from the wing change
    assert any(r["setting"] == "downforce_rear" and r["ticks"] < 0 for r in r2["recommendations"])   # fast corners now push: take wing off
    s = st.decide(s["key"], {r2["recommendations"][0]["id"]: "unavailable"})
    assert r2["recommendations"][0]["setting"] in s["unavailable"]


def test_learning_rejects_implausible_tick_sizes(tmp_path):
    st = EngineerStore(tmp_path)
    s = st.create("Car", "Track", "Layout")
    out = st._learn(s, {"gearing": {"top_gear_rpm_frac": 0.848}}, {"gearing": {"top_gear_rpm_frac": 0.853}}, [{"setting": "final_drive", "ticks": 3}])
    assert out[0]["per_tick"] is None and "Check the change went in" in out[0]["note"] and "final_drive" not in s["learned"]


def _snap(speed, pit, lap, dist):
    w = [0.0] * 4
    p = SimpleNamespace(mCurrentLapDistance=dist, mLapsCompleted=lap, mWorldPosition=[dist, 0, 0])
    return SimpleNamespace(mViewedParticipantIndex=0, mParticipantInfo=[p], mPitMode=pit, mSpeed=speed, mSessionState=4, mFuelLevel=0.5,
                           mFuelCapacity=120.0, mEventTimeRemaining=600.0, mTrackLength=1000.0, mCarName=b"Car", mTrackLocation=b"T", mTrackVariation=b"V",
                           mSteering=0.0, mThrottle=1.0, mBrake=0.0, mAngularVelocity=[0, 0, 0], mLocalAcceleration=[0, 0, 0], mLapInvalidated=False,
                           mGear=4, mRpm=6000, mMaxRPM=7500, mNumGears=6, mBrakeBias=0.45, mAntiLockSetting=8, mTractionControlSetting=6,
                           mAntiLockActive=False, mWaterTempCelsius=85, mOilTempCelsius=95, mTyreCompound=[SimpleNamespace(value=b"Slick")] * 4,
                           mTyreRPS=w, mTyreTempLeft=w, mTyreTempCenter=w, mTyreTempRight=w, mAirPressure=w, mRideHeight=w, mSuspensionTravel=w,
                           mSuspensionVelocity=w, mTyreHeightAboveGround=w, mBrakeTempCelsius=w, mTyreWear=w)


def test_live_tracker_splits_runs_at_the_pits():
    from ams2season.engineer.live import EngineerTracker
    done = []
    tr = EngineerTracker(lambda df, info: done.append((df.local_lap.nunique(), info["track_length"])) or {"ok": True})
    t = 0.0
    for _ in range(20):                      # sitting in the garage
        tr.feed(_snap(0.0, 4, 0, 0), t); t += 0.05
    for lap in range(3):                     # three laps on track
        for i in range(200):
            tr.feed(_snap(50.0, 0, lap, i * 5), t); t += 0.05
    assert tr.status()["state"] == "running" and tr.status()["laps"] >= 2
    tr.feed(_snap(0.0, 2, 3, 0), t)          # back in the pit box
    assert done and done[0] == (4, 1000.0) and tr.status()["state"] == "garage"


def test_engineer_api(tmp_path):
    from ams2season.app import App, _make_server, make_handler
    app = App(tmp_path)
    srv = _make_server(0, make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"

    def call(m, p, body=None):
        req = urllib.request.Request(base + p.lstrip("/"), method=m, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    try:
        E = call("GET", "/api/engineer")
        assert len(E["categories"]) == 9 and len(E["settings"]) > 70
        s = call("POST", "/api/engineer/session", {"car": "Ferrari 488 GT3", "track": "Road_America", "layout": "Road_America_RC",
                                                   "symmetrical_off": True, "baseline_default": True, "race_target": {"mode": "laps", "laps": 25}})
        assert s["race_target"]["laps"] == 25 and s["symmetrical_off"]
        g = call("GET", f"/api/engineer/session?key={s['key']}")
        assert g["key"] == s["key"] and g["latest"] is None
        assert call("GET", "/api/engineer")["sessions"][0]["key"] == s["key"]
    finally:
        srv.shutdown()



def test_fuel_effect_from_high_and_low_fuel_runs(runs, tmp_path):
    st = EngineerStore(tmp_path)
    s = st.create("Ferrari 488 GT3", "Road_America", "Road_America_RC")
    heavy = runs["ra_ferrari_baseline"].copy()
    heavy["fuel_level"] = heavy.fuel_level + 0.6            # the same laps as if started on ~97 L
    heavy["t"] = heavy.t * 1.0
    s = st.add_run(s["key"], heavy, 6440.41, "full tank")
    assert s["flags"].get("high_fuel_done") and s["next_run"]["fuel_l"] < 40      # now the low-fuel comparison
    s = st.add_run(s["key"], runs["ra_ferrari_wing2_frontarb2"], 6440.41, "low fuel")
    assert s["flags"]["low_fuel_done"] and "fuel_effect_s_per_10l" in s


def _plat(fl=3.0, fr=3.2, rl=3.4, rr=3.6, bottom=None):
    p = {w: {"ride_min_cm": v, "ride_near_zero_s": 0.0, "at_travel_limit_s": 0.0} for w, v in (("fl", fl), ("fr", fr), ("rl", rl), ("rr", rr))}
    if bottom:
        p[bottom]["ride_near_zero_s"] = 0.5
    return p


def test_ride_height_lowering():
    rh = lambda recs: {r["setting"]: r["ticks"] for r in recs if r["setting"].startswith("ride_height")}
    # plenty of room, balanced: both axles come down, about half the room each, never more than 4 ticks
    r = rh(engine.recommend(_m(platform=_plat()), {}))
    assert set(r) == {"ride_height_fl", "ride_height_fr", "ride_height_rl", "ride_height_rr"} and all(-4 <= v < 0 for v in r.values())
    assert r["ride_height_fl"] == r["ride_height_fr"]                                   # an axle moves together
    # understeer in fast corners: the front first (more rake = more front grip)
    r = rh(engine.recommend(_m(platform=_plat(), fast_gradient=0.6), {"unavailable": ["downforce_rear", "downforce_front"]}))
    assert set(r) == {"ride_height_fl", "ride_height_fr"}
    # the wings are already fixing the balance: both axles by the same amount, keeping the rake
    r = rh(engine.recommend(_m(platform=_plat(), fast_gradient=0.6), {}))
    assert set(r) == {"ride_height_fl", "ride_height_fr", "ride_height_rl", "ride_height_rr"} and len(set(r.values())) == 1
    # bottoming at one corner: that axle is raised, never lowered
    r = rh(engine.recommend(_m(platform=_plat(bottom="rl")), {}))
    assert r.get("ride_height_rl", 0) > 0 and r.get("ride_height_rr", 0) >= 0
    # not enough laps, or already near the floor learned for this car: leave it
    assert not rh(engine.recommend(_m(platform=_plat(), n_flying=1), {}))
    assert not rh(engine.recommend(_m(platform=_plat(fl=2.0, fr=2.0, rl=2.0, rr=2.0)), {"learned": {"ride_floor_front": {"cm": 1.5}, "ride_floor_rear": {"cm": 1.5}}}))


def test_ride_floor_learned_when_lowering_causes_bottoming(tmp_path):
    st = EngineerStore(tmp_path)
    s = st.create("Car", "Track", "Layout")
    prev = {"platform": _plat()}
    now = {"platform": _plat(fl=0.6, fr=0.9, bottom="fl")}
    out = st._learn(s, prev, now, [{"setting": "ride_height_fl", "ticks": -4}, {"setting": "ride_height_fr", "ticks": -4}])
    assert s["learned"]["ride_floor_front"]["cm"] == 0.6 and any("started bottoming" in (x.get("note") or "") for x in out)
    assert s["learned"]["ride_height"]["per_tick"] > 0                                  # and what one tick did


def test_preferences_move_the_targets():
    m = _m(countersteer={"entry": 0, "mid": 0, "exit": 0.4, "lift": 0, "fast": 0}, braking={"tc_setting": 6, "spin_rl_s": 0.5, "spin_rr_s": 0.5})
    tc = lambda prefs: [r for r in engine.recommend(m, {"prefs": prefs}) if r["setting"] == "traction_control"]
    assert tc({}) and tc({"balance": -0.8, "aggression": -0.8})            # neutral and safe: calm the exits
    assert not tc({"balance": 0.8, "aggression": 0.6})                      # likes oversteer: this much is fine
    fg = lambda prefs: [r for r in engine.recommend(_m(fast_gradient=0.36), {"prefs": prefs}) if r["setting"] == "downforce_rear"]
    assert not fg({}) and fg({"balance": 0.8})                              # likes oversteer: less understeer at speed wanted
    lo = lambda prefs: {r["setting"] for r in engine.recommend(_m(platform=_plat(1.9, 1.9, 1.9, 1.9)), {"prefs": prefs}) if r["setting"].startswith("ride_height")}
    assert not lo({"aggression": -1}) and lo({"aggression": 1})             # aggressive runs closer to the ground


def test_qualifying_variant_and_category_breakdown(runs, tmp_path):
    st = EngineerStore(tmp_path)
    s = st.create("Ferrari 488 GT3", "Road_America", "Road_America_RC")
    for k in ("ra_ferrari_baseline", "ra_ferrari_wing2_frontarb2"):
        s = st.add_run(s["key"], runs[k], 6440.41, k)
    r = s["runs"][-1]
    q = {x["setting"]: x for x in r["quali"]}
    assert q["fuel"]["action"].startswith("Set to") and int(q["fuel"]["action"].split()[2]) < 20
    d = r["categories"]["aero_balance"]["detail"]
    assert d["confidence"] in ("low", "medium", "high") and d["confidence_reasons"] and d["evidence"][0]["target"]
    assert [h["run"] for h in d["history"]] == [1, "now"]                    # the key figure across runs
    s = st.create("Ferrari 488 GT3", "Road_America", "Road_America_RC", prefs={"balance": 0.5})
    assert s["prefs"] == {"balance": 0.5} and len(s["runs"]) == 2           # re-evaluated, not a new run


def test_driver_feedback_merges_with_the_data():
    base = _m(fast_gradient=0.55, countersteer={"entry": 0, "mid": 0, "exit": 0.8, "lift": 0, "fast": 0}, braking={"tc_setting": 6, "spin_rl_s": 0.5, "spin_rr_s": 0.5})
    recs = engine.recommend(base, {})
    fb = {"mid": {"fast": -1, "slow": -2}, "exit": {"slow": 1}, "brakes": {"medium": 1}}
    out = {r["setting"]: r for r in engine.merge_feedback(recs, fb, base, {})}
    assert out["downforce_rear"]["feedback"] == "agrees" and "matches what you felt" in out["downforce_rear"]["why"]
    assert out["traction_control"]["feedback"] == "agrees"
    assert out["arb_front"]["source"] == "feedback" and out["arb_front"]["ticks"] == -2 and out["arb_front"]["confidence"] == "low"
    assert out["brake_bias"]["source"] == "feedback" and "engine_braking" not in out          # one feel-only remedy per symptom
    # the data says the opposite: the data wins, your feel is noted
    opp = {r["setting"]: r for r in engine.merge_feedback(recs, {"mid": {"fast": 2}}, base, {})}
    assert opp["downforce_rear"]["ticks"] < 0 and opp["downforce_rear"]["feedback"] == "disagrees"
    # mixed answers on one setting cancel out, and it says so
    mixed = engine.merge_feedback([], {"mid": {"slow": -1}, "turn_in": {"slow": 1}}, _m(), {})
    assert not any(r["setting"] in ("arb_front", "arb_rear") for r in mixed) and "Mixed feel" in mixed[0]["why"]
    net = {r["setting"]: r["ticks"] for r in engine.merge_feedback([], {"mid": {"slow": -2, "medium": -1}, "turn_in": {"slow": 1}}, _m(), {})}
    assert net == {"arb_front": -2}                                                   # 3 understeer votes against 1 oversteer: soften the front, 2 ticks
    # kerbs: harsh -> softer fast bump all round; unavailable settings are respected
    kb = engine.merge_feedback([], {"kerbs": -1}, _m(), {"unavailable": ["fast_bump_rl"]})
    assert {r["setting"] for r in kb} == {"fast_bump_fl", "fast_bump_fr", "fast_bump_rr"} and all(r["ticks"] == -1 for r in kb)


def test_feedback_is_saved_with_the_run(runs, tmp_path):
    st = EngineerStore(tmp_path)
    s = st.create("Ferrari 488 GT3", "Road_America", "Road_America_RC")
    s = st.add_run(s["key"], runs["ra_ferrari_wing2_frontarb2"], 6440.41, "run")
    s = st.feedback(s["key"], {"turn_in": {"slow": -2, "fast": 9}, "kerbs": -1, "notes": "pushes into the hairpin"})
    fb = s["runs"][-1]["feedback"]
    assert fb == {"turn_in": {"slow": -2}, "kerbs": -1, "notes": "pushes into the hairpin"}     # out-of-range values dropped
    assert any(r.get("source") == "feedback" and r["setting"] == "arb_front" for r in s["runs"][-1]["recommendations"])
    assert len(s["runs"]) == 1



def test_old_sessions_are_brought_up_to_date(runs, tmp_path):
    st = EngineerStore(tmp_path)
    s = st.create("Ferrari 488 GT3", "Road_America", "Road_America_RC")
    s = st.add_run(s["key"], runs["ra_ferrari_wing2_frontarb2"], 6440.41, "run")
    raw = json.loads(st.path(s["key"]).read_text())
    for c in raw["runs"][-1]["categories"].values():                 # as saved by an engineer from before breakdowns
        c.pop("detail", None)
    raw.pop("engine_version")
    st.path(s["key"]).write_text(json.dumps(raw))
    s2 = st.get(s["key"])
    assert all("detail" in c and c["detail"]["confidence"] for c in s2["runs"][-1]["categories"].values())
    assert s2["engine_version"] == engine.ENGINE_VERSION and all("garage" in r for r in s2["runs"][-1]["recommendations"] if not r.get("info"))


def test_race_plan():
    m = {"fuel": {"per_lap_l": 2.8, "capacity_l": 120}, "avg_lap": 128.0, "wear_per_lap_pct": {"fl": 1.4, "fr": 1.9, "rl": 1.1, "rr": 1.2}}
    plan = lambda **t: engine.race_fuel({"race_target": {"mode": "time", "minutes": 60, **t}}, m)
    p = plan()
    assert p["laps"] == 30 and p["stops"] == 0 and p["litres"] == 87 and p["stints"][0]["tyres"] == "new"
    p = plan(pit_stops=1)
    assert p["stops"] == 1 and p["stops_reason"] == ["mandatory stops"] and [s["laps"] for s in p["stints"]] == [15, 15]
    assert p["stints"][1]["tyres"] == "keep"                                            # 30 laps is within the tyres' life
    p = plan(minutes=120)                                                               # 58 laps of fuel doesn't fit in 120 L
    assert p["stops"] >= 1 and "fuel tank size" in p["stops_reason"] and all(s["fuel_l"] <= 120 for s in p["stints"])
    p = plan(tyre_mult=3, practice_tyre_mult=1, practice_differs=True)                  # tyres last 12 laps at x3 wear
    assert p["tyre_life_laps"] == 12 and "tyre wear" in p["stops_reason"] and p["stints"][1]["tyres"] == "change"
    p = plan(fuel_mult=2, practice_fuel_mult=1, practice_differs=True)
    assert p["per_lap_l"] == 5.6 and any("scaled ×2" in n for n in p["notes"])
    p = plan(fuel_mult=2)                                                               # practice ran at the race's settings: no scaling
    assert p["per_lap_l"] == 2.8
    assert plan(fuel_mult=0)["per_lap_l"] == 0 and any("off" in n for n in plan(fuel_mult=0)["notes"])
    assert any("in-game time" in n for n in plan(minutes=60, time_accel=4)["notes"]) and not plan(time_accel=1)["notes"]



def test_race_plan_tracks_each_set_of_tyres():
    # three mandatory stops, tyres good for 46 laps: two stints on the first set, then a change
    m = {"fuel": {"per_lap_l": 2.0, "capacity_l": 120}, "avg_lap": 100.0, "wear_per_lap_pct": {"fl": 1.5}}
    p = engine.race_fuel({"race_target": {"mode": "laps", "laps": 80, "pit_stops": 3}}, m)
    assert [s["tyres"] for s in p["stints"]] == ["new", "keep", "change", "keep"]
    assert p["stints"][1]["tyre_wear_end_pct"] == 60.0 and p["stints"][2]["tyre_wear_end_pct"] == 30.0   # wear on the set, not the stint
    assert all(s["tyre_wear_end_pct"] <= 70 for s in p["stints"])
