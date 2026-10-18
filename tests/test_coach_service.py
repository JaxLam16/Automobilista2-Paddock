"""Coach workers never block recording or edit original sessions/preferences."""
import http.client
import json
from pathlib import Path
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ams2season import shm as S
from ams2season.app import App, _make_server, make_handler
from ams2season.recorder import Recorder
from test_coach_replay import write_recording


def snapshot():
    snap = S.SharedMemory()
    snap.mVersion = S.SHARED_MEMORY_VERSION
    snap.mGameState, snap.mSessionState, snap.mRaceState = 2, 5, 2
    snap.mNumParticipants, snap.mViewedParticipantIndex = 1, 0
    snap.mTrackLength = 1000
    snap.mCarName, snap.mCarClassName = b"GT3", b"GT3"
    snap.mTrackLocation, snap.mTrackVariation = b"Track", b"Layout"
    snap.mSpeed, snap.mThrottle, snap.mSteering = 50, 1, .01
    player = snap.mParticipantInfo[0]
    player.mIsActive, player.mName = True, b"Player"
    player.mLapsCompleted, player.mRacePosition, player.mCurrentLapDistance = 2, 1, 300
    snap.mCarNames[0].value, snap.mCarClassNames[0].value = b"GT3", b"GT3"
    snap.mRaceStates[0], snap.mSpeeds[0] = 2, 50
    return snap


def app_with_current(root):
    app = App(root)
    app.recorder.thread = SimpleNamespace(is_alive=lambda: True)
    app.recorder.rec = Recorder(root / "recordings", sessions=(), log=lambda _: None)
    # Build/read cold service metadata before the fixture's first live sample.
    # The real recorder keeps feeding while the user opens the engineer page.
    app.coach.status()
    app.recorder.rec.step(snapshot(), time.perf_counter())
    return app


def wait_until(predicate, timeout=5):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Worker did not reach the expected state")


@contextmanager
def snapshot_stream(app, raw):
    """Keep native live tests supplied as a real recorder does during playback."""
    stop=threading.Event()
    app.recorder.rec.step(raw,time.perf_counter())
    def feed():
        while not stop.is_set():
            app.recorder.rec.step(raw,time.perf_counter())
            stop.wait(.05)
    worker=threading.Thread(target=feed,daemon=True)
    worker.start()
    try:yield
    finally:
        stop.set();worker.join(2)
        assert not worker.is_alive()


def test_preview_start_stop_and_disconnect_do_not_touch_recording_or_crew_chief(tmp_path):
    app = app_with_current(tmp_path)
    assert not (tmp_path / "private_coach").exists()
    assert app.route("GET", "/api/coach", {}, {})["audio_enabled"] is False
    result = app.route("POST", "/api/coach/start", {}, {})
    assert result["running"] and result["live"]["driver"] == "Player"
    assert "coach" in app.recorder.rec.hooks
    app.recorder.rec.step(snapshot(), time.perf_counter())
    wait_until(lambda: (app.coach.status()["live"]["context"] or {}).get("active"))
    wait_until(lambda: (app.coach.status()["live"]["context"] or {}).get("reason") == "disconnected", 3)
    app.route("POST", "/api/coach/stop", {}, {})
    assert not app.coach.running and "coach" not in app.recorder.rec.hooks
    assert list((tmp_path / "recordings").iterdir()) == []
    assert not (tmp_path / "crew_chief").exists() and app._crew_chief is None


def test_slow_analysis_never_blocks_the_snapshot_hook(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    from ams2season.coach.engine import CoachEngine
    original = CoachEngine.feed
    def slow(self, *args, **kwargs):
        entered.set()
        release.wait(5)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(CoachEngine, "feed", slow)
    app = app_with_current(tmp_path)
    app.coach.start()
    try:
        app.recorder.rec.step(snapshot(), time.perf_counter())
        assert entered.wait(2)
        started = time.perf_counter()
        for _ in range(30):
            app.recorder.rec.step(snapshot(), time.perf_counter())
        assert time.perf_counter()-started < .5
        assert app.coach.inbox.qsize() <= 4 and app.coach.dropped_snapshots > 0
    finally:
        release.set()
        app.coach.close()


def test_driver_lock_and_missing_game_guard(tmp_path):
    app = App(tmp_path)
    with pytest.raises(ValueError, match="load your car"):
        app.coach.start()
    app = app_with_current(tmp_path)
    with pytest.raises(ValueError, match="exact in-game name"):
        app.coach.start("Some other driver")
    assert not app.coach.running


def test_replay_job_outputs_stay_private_and_settings_are_explicit(tmp_path):
    write_recording(tmp_path / "recordings" / "test-race")
    app = App(tmp_path)
    initial = app.coach.status()
    assert not initial["running"] and initial["replay"]["state"] == "idle"
    app.route("POST", "/api/coach/settings", {}, {"mode": "coach"})
    assert json.loads((tmp_path / "private_coach/settings.json").read_text())["audio_enabled"] is False
    app.route("POST", "/api/coach/replay", {}, {"recording": "test-race"})
    wait_until(lambda: app.coach.status()["replay"]["state"] != "running", 10)
    report = app.coach.status()["replay"]["result"]
    assert report["counts"]["would_say"] == 1 and report["inputs_unchanged"]
    run = Path(report["directory"]).name
    assert app.coach.review_file(run).is_file()
    for bad in ("../settings.json", "x"*32, run+"/../../", None):
        with pytest.raises(LookupError):
            app.coach.review_file(bad)
    app.coach.close()


def test_coach_unit_preferences_persist_without_enabling_speech_or_changing_mode(tmp_path):
    app=App(tmp_path)
    initial=app.coach.configure({'mode':'quiet','units':{'pressure':'psi','fuel':'laps'}})
    assert initial['format_examples']['pressure']['text']=='26.8 psi'
    assert initial['format_examples']['fuel']['text']=='8.0 laps'
    assert initial['mode']=='quiet' and not initial['audio_enabled']
    reloaded=App(tmp_path)
    assert reloaded.coach.units.pressure=='psi' and reloaded.coach.units.distance=='m'
    before=(tmp_path/'private_coach/settings.json').read_bytes()
    with pytest.raises(ValueError):app.coach.configure({'units':{'fuel':'guessed_laps'}})
    assert (tmp_path/'private_coach/settings.json').read_bytes()==before
    assert app.coach.units.fuel=='laps' and app.coach.mode=='quiet'
    app.coach.close();reloaded.coach.close()


def test_coach_http_mutations_require_same_origin_json_and_bounded_bodies(tmp_path):
    app = App(tmp_path)
    server = _make_server(0, make_handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    def request(method, path, body=b"{}", **headers):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, body=body, headers={"Content-Type": "application/json", **headers})
        response = conn.getresponse()
        data, status = response.read(), response.status
        conn.close()
        return status, data
    try:
        for _ in range(5):
            assert request("POST", "/api/coach/settings", Origin="http://untrusted.test")[0] == 403
        for path in ('/api/coach/voice/select', '/api/coach/voice/cancel'):
            assert request('POST', path, Origin='http://untrusted.test')[0] == 403
        assert request("POST", "/api/coach/settings", **{"Content-Type": "text/plain"})[0] == 415
        assert request("POST", "/api/coach/settings", body=b" "*17000)[0] == 413
        assert not (tmp_path / "private_coach/settings.json").exists()
        assert request("POST", "/api/coach/settings", body=b'{"mode":"coach"}')[0] == 200
        assert request('POST', '/api/coach/voice/select', body=b'{"key":"https://example.com/voice.zip"}')[0] == 400
        assert request('POST', '/api/coach/voice/cancel')[0] == 200
        assert request("GET", "/coach.js", body=None)[0] == 200
        assert b"PaddockCoach" in request("GET", "/crew-chief.js", body=None)[1]
        assert request("GET", "/coach-review?run=../settings.json", body=None)[0] == 404
    finally:
        app.coach.close()
        server.shutdown()
        server.server_close()
