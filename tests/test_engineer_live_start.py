"""Starting from fresh recorder snapshots without a prior engineer or saved practice."""
import time
from types import SimpleNamespace

import pytest

from ams2season import shm as S
from ams2season.app import App
from ams2season.engineer.store import EngineerStore
from ams2season.recorder import Recorder
from test_engineer import _snap


def snapshot(car="Mustang GT", track="Watkins_Glen", layout="GP_Inner_Loop", **changes):
    snap = _snap(0, 4, 0, 0)
    snap.mGameState = S.GAME_INGAME_PLAYING
    snap.mVersion = S.SHARED_MEMORY_VERSION
    snap.mSessionState = S.SESSION_PRACTICE
    snap.mNumParticipants = 1
    snap.mParticipantInfo[0].mIsActive = True
    snap.mCarName, snap.mTrackLocation, snap.mTrackVariation = car.encode(), track.encode(), layout.encode()
    for name, value in changes.items():
        setattr(snap, name, value)
    return snap


def live_app(root):
    app = App(root)
    # Use synthetic snapshots, with no shared memory reader or real game writes.
    app.recorder.thread = SimpleNamespace(is_alive=lambda: True)
    app.recorder.rec = Recorder(root / "recordings", sessions=(), log=lambda _: None)
    return app


def test_live_start_without_saved_practice_and_resume(tmp_path):
    app = live_app(tmp_path)
    app.recorder.rec.step(snapshot(), time.perf_counter())
    overview = app.route("GET", "/api/engineer", {}, {})
    assert overview["practice"] == [] and overview["live"] is None
    assert overview["current"]["car"] == "Mustang GT"
    started = app.route("POST", "/api/engineer/live/start", {}, {})
    store = EngineerStore(tmp_path)
    session = store.get(started["key"])
    assert (session["car"], session["track"], session["layout"]) == ("Mustang GT", "Watkins_Glen", "GP_Inner_Loop")
    assert "engineer" in app.recorder.rec.hooks
    assert app.recorder.engineer_key == started["key"]
    # Repeat click keeps an in-progress tracker; resuming later retains setup.
    tracker = app.recorder.engineer
    tracker.feed(snapshot(mSpeed=50, mPitMode=0), 0)
    assert app.route("POST", "/api/engineer/live/start", {}, {}) == started
    assert app.recorder.engineer is tracker and tracker.rows
    session["ticks"] = {"arb_front": 2}
    session["symmetrical_off"] = True
    store.save(session)
    app.route("POST", "/api/engineer/live/stop", {}, {})
    resumed = app.route("POST", "/api/engineer/live/start", {}, {})
    assert resumed["key"] == started["key"]
    assert store.get(resumed["key"])["ticks"] == {"arb_front": 2}
    assert store.get(resumed["key"])["symmetrical_off"]


def test_click_resolves_latest_car_and_track(tmp_path):
    app = live_app(tmp_path)
    app.recorder.rec.step(snapshot(), time.perf_counter())
    assert app.route("GET", "/api/engineer/current", {}, {})["current"]["car"] == "Mustang GT"
    app.recorder.rec.step(snapshot(car="Nissan GT-R", track="Road_America", layout="RC"), time.perf_counter())
    started = app.route("POST", "/api/engineer/live/start", {}, {})
    assert EngineerStore(tmp_path).get(started["key"])["car"] == "Nissan GT-R"
    assert "road-america" in started["key"]


@pytest.mark.parametrize("changes", [
    {"mGameState": S.GAME_FRONT_END}, {"mGameState": S.GAME_INGAME_REPLAY},
    {"mSessionState": S.SESSION_INVALID}, {"mTrackLength": 0},
    {"mViewedParticipantIndex": -1}, {"mViewedParticipantIndex": 2},
    {"mCarName": b""}, {"mTrackLocation": b""},
])
def test_invalid_live_selection_does_not_create_session(tmp_path, changes):
    app = live_app(tmp_path)
    app.recorder.rec.step(snapshot(**changes), time.perf_counter())
    assert app.route("GET", "/api/engineer/current", {}, {})["current"] is None
    with pytest.raises(ValueError, match="No live car"):
        app.route("POST", "/api/engineer/live/start", {}, {})
    assert not (tmp_path / "engineer").exists()


def test_missing_stale_or_stopped_recorder_does_not_reuse_old_identity(tmp_path):
    app = live_app(tmp_path)
    app.recorder.rec.step(snapshot(), time.perf_counter() - 4)
    assert app.recorder.status()["current"] is None
    app.recorder.rec.step(snapshot(), time.perf_counter())
    app.recorder.rec.step(None, time.perf_counter())
    assert app.recorder.status()["current"] is None
    app.recorder.rec.step(snapshot(), time.perf_counter())
    app.recorder.thread = None
    assert app.recorder.status()["current"] is None
    with pytest.raises(ValueError, match="No live car"):
        app.route("POST", "/api/engineer/live/start", {}, {})


def test_track_change_cannot_mix_engineer_run_rows(tmp_path):
    app = live_app(tmp_path)
    app.recorder.rec.step(snapshot(), time.perf_counter())
    started = app.route("POST", "/api/engineer/live/start", {}, {})
    tracker = app.recorder.engineer
    tracker.feed(snapshot(mSpeed=50, mPitMode=0), 0)
    assert tracker.rows
    tracker.feed(snapshot(layout="Other_Layout", mSpeed=50, mPitMode=0), 1)
    assert tracker.rows == [] and not tracker.status()["connected"]
    app.recorder.rec.step(snapshot(car="Other Car"), time.perf_counter())
    with pytest.raises(ValueError, match="different car or track"):
        app.route("POST", "/api/engineer/live/start", {}, {"key": started["key"]})


def test_live_run_is_still_analysed_on_pit_return(tmp_path):
    app = live_app(tmp_path)
    app.recorder.rec.step(snapshot(), time.perf_counter())
    started = app.route("POST", "/api/engineer/live/start", {}, {})
    tracker = app.recorder.engineer
    for lap in range(3):
        for tick in range(100):
            snap = snapshot(mSpeed=40, mPitMode=0)
            snap.mParticipantInfo[0].mLapsCompleted = lap
            snap.mParticipantInfo[0].mCurrentLapDistance = tick * 10
            tracker.feed(snap, lap * 100 + tick)
    snap = snapshot()
    snap.mParticipantInfo[0].mLapsCompleted = 3
    tracker.feed(snap, 300)
    assert tracker.last_result == {"run": 1}
    assert len(EngineerStore(tmp_path).get(started["key"])["runs"]) == 1
