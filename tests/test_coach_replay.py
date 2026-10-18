"""Live/replay parity on causal telemetry, pit entry evidence and learned windows."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ams2season import shm as S
from ams2season.coach.engine import CoachEngine, PitWatch
from ams2season.coach.model import Car, Tick
from ams2season.coach.replay import run_replay, ticks
from ams2season.coach.telemetry import from_snapshot, from_recorded
from ams2season.coach.windows import WindowLearner


def tick(t, *, pit=0, game=2, rival="Rival", viewed=0, position=2, invalid=False):
    lap = int(t // 20)
    distance = (t * 50) % 1000
    local = {"speed": 50, "throttle": 1. if distance < 800 else .2, "brake": 0.,
             "steering": .01 if distance < 800 else .3, "rain_density": 0., "crash_state": 0,
             "local_lap_invalid": invalid, "fuel_level": .5, "fuel_capacity": 100}
    player = Car(0, "Player", "GT3", "GT3", position, lap, distance, 50, 0, 2, invalid)
    other = Car(1, rival, "Other GT3", "GT3", 1 if position == 2 else 2, lap,
                (distance + 250) % 1000, 50, pit, 2, False)
    return Tick(t, "test-race", "race", "Track", "Layout", 1000, game, viewed, (player, other), local)


def test_windows_require_two_past_clean_complete_laps():
    windows = WindowLearner(1000)
    for i in range(400):
        frame = tick(i * .1)
        windows.feed(frame, frame.cars[0])
    assert windows.seconds(50, 50) is None
    frame = tick(40)
    windows.feed(frame, frame.cars[0])
    assert len(windows.laps) == 2
    assert windows.seconds(50, 50) > 10
    assert windows.seconds(790, 50) == 0
    assert windows.seconds(900, 50) == 0


def test_invalid_pit_or_incomplete_laps_cannot_teach_a_radio_window():
    for fault in ("invalid", "pit", "gap"):
        windows = WindowLearner(1000)
        for i in range(401):
            if fault == "gap" and 100 <= i <= 110:
                continue
            frame = tick(i * .1, invalid=(fault == "invalid" and i == 100))
            player = replace(frame.cars[0], pit=2) if fault == "pit" and i == 100 else frame.cars[0]
            windows.feed(frame, player)
        assert windows.seconds(100, 50) is None


def test_counter_lag_at_the_line_does_not_destroy_clean_window_learning():
    windows = WindowLearner(1000)
    for i in range(402):
        frame = tick(i * .1)
        car = frame.cars[0]
        if i in (200, 400):
            car = replace(car, laps=car.laps - 1)
        windows.feed(frame, car)
    assert len(windows.laps) == 2


def test_engine_calls_only_sustained_observed_entry_and_keeps_evidence():
    engine, calls = CoachEngine("Player"), []
    for i in range(470):
        frame = tick(i * .1, pit=1 if i >= 450 else 0)
        selected = engine.feed(frame, radio_busy=False)
        if selected:
            calls.append(selected)
            engine.radio.acknowledge(selected, engine.context, accepted=True, simulated=True)
    assert len(calls) == 1
    assert calls[0].text == "The car ahead is pitting."
    assert calls[0].message.evidence.values["source"] == "observed_transition"
    assert calls[0].message.created >= 45.5
    assert calls[0].message.evidence.values["driver"] == "Rival"


@pytest.mark.parametrize("fault", ["already_in_pits", "one_frame", "slot_reuse", "pause", "gap", "spectating"])
def test_no_false_pit_calls_for_spawn_flicker_slot_reuse_pause_or_gap(fault):
    engine = CoachEngine("Player")
    for i in range(470):
        if fault == "gap" and 445 <= i <= 455:
            continue
        pit = 1 if i >= 450 else 0
        if fault == "already_in_pits":
            pit = 1
        if fault == "one_frame":
            pit = 1 if i == 450 else 0
        frame = tick(i * .1, pit=pit,
                     rival="Joined" if fault == "slot_reuse" and i >= 450 else "Rival",
                     game=3 if fault == "pause" and 450 <= i <= 456 else 2,
                     viewed=1 if fault == "spectating" and i >= 450 else 0)
        selected = engine.feed(frame, radio_busy=False)
        assert selected is None
    assert engine.radio.log.counts["would_say"] == 0


def test_held_car_ahead_call_expires_when_player_passes_that_car():
    engine = CoachEngine("Player")
    for i in range(465):
        selected = engine.feed(tick(i*.1, pit=1 if i >= 450 else 0,
                                    position=1 if i >= 460 else 2), radio_busy=True)
        assert selected is None
    assert any(e.get("reason") == "condition_changed" for e in engine.radio.log.events)
    assert not engine.radio.pending


def write_recording(directory, frames=None):
    directory.mkdir(parents=True)
    frames = frames or [tick(i*.1, pit=1 if i >= 450 else 0) for i in range(470)]
    meta = {"session_type": "race", "track_location": "Track", "track_variation": "Layout",
            "track_length": 1000, "status": "complete", "local": {"name": "Player"}}
    (directory / "session.json").write_text(json.dumps(meta))
    cars, local = [], []
    for frame in frames:
        for car in frame.cars:
            cars.append({"t": frame.t, "slot": car.slot, "name": car.name, "car": car.car,
                         "car_class": car.car_class, "race_pos": car.position, "laps_completed": car.laps,
                         "lap_dist": car.distance, "speed": car.speed, "pit_mode": car.pit,
                         "race_state": car.race_state, "lap_invalid": car.invalid,'flag_colour':car.flag_colour,
                         'x':car.x,'z':car.z})
        local.append({**frame.local, "t": frame.t, "viewed_slot": frame.viewed_slot, "game_state": frame.game_state})
    pq.write_table(pa.Table.from_pylist(cars), directory / "frames.parquet")
    pq.write_table(pa.Table.from_pylist(local), directory / "local.parquet")
    return meta


def test_read_only_replay_preserves_sources_and_matches_direct_engine(tmp_path):
    recording = tmp_path / "recording"
    meta = write_recording(recording)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in recording.iterdir()}
    report = run_replay(recording, tmp_path)
    assert report["ticks"] == 470 and report["inputs_unchanged"] and not report["audio_played"]
    assert report["counts"]["would_say"] == 1
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in recording.iterdir()} == before
    events = [json.loads(line) for line in (Path(report["directory"]) / "radio.jsonl").read_text().splitlines()]
    actual = [e for e in events if e["state"] == "would_say"]
    direct = CoachEngine("Player")
    expected = []
    for frame in ticks(recording, meta):
        selected = direct.feed(frame, radio_busy=False)
        if selected:
            expected.append((frame.t, selected.text))
            direct.radio.acknowledge(selected, direct.context, accepted=True, simulated=True)
    assert [(e["t"], e["text"]) for e in actual] == expected
    assert "Simulated decisions only" in Path(report["review"]).read_text()


def test_replay_does_not_peek_at_future_local_rows():
    meta = {"track_length": 1000, "session_type": "race"}
    frame = tick(1)
    row = {"slot": 0, "name": "Player", "lap_dist": 50, "laps_completed": 0}
    assert not from_recorded(meta, [row], {"t": 1.1}, "race", 1).fresh
    assert not from_recorded(meta, [row], {"t": .5}, "race", 1).fresh


def test_replay_uses_json_crash_fallback_parts(tmp_path):
    recording = tmp_path / "recording"
    write_recording(recording)
    for kind in ("frames", "local"):
        path = recording / (kind + ".parquet")
        raw = pq.read_table(path).to_pydict()
        parts = recording / (kind + "_parts")
        parts.mkdir()
        (parts / "part-00000.json").write_text(json.dumps(raw))
        path.unlink()  # Disposable fixture only, not a user's recording.
    report = run_replay(recording, tmp_path)
    assert report["counts"]["would_say"] == 1


def test_replay_speed_changes_wall_time_but_never_decision_time(tmp_path, monkeypatch):
    recording = tmp_path / "recording"
    write_recording(recording)
    now = [0.]
    monkeypatch.setattr("ams2season.coach.replay.time.monotonic", lambda: now[0])
    monkeypatch.setattr("ams2season.coach.replay.time.sleep", lambda delay: now.__setitem__(0, now[0]+delay))
    results = [run_replay(recording, tmp_path, speed=speed) for speed in (1, 20)]
    events = [[json.loads(line) for line in (Path(r["directory"])/"radio.jsonl").read_text().splitlines()] for r in results]
    assert events[0] == events[1]
    assert results[0]["wall_seconds"] == pytest.approx(results[1]["wall_seconds"] * 20)


def test_bad_or_active_recording_fails_without_creating_private_output(tmp_path):
    recording = tmp_path / "recording"
    meta = write_recording(recording)
    meta["status"] = "recording"
    (recording / "session.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="finished"):
        run_replay(recording, tmp_path)
    assert not (tmp_path / "private_coach").exists()


def test_real_recorder_and_live_snapshot_adapter_reproduce_the_same_calls(tmp_path):
    from ams2season.recorder import Recorder
    engine, calls = CoachEngine("Player"), []
    def feed(snap, now):
        selected = engine.feed(from_snapshot(snap, now, "live"), radio_busy=False)
        if selected:
            calls.append((now, selected.text))
            engine.radio.acknowledge(selected, engine.context, accepted=True, simulated=True)
    rec = Recorder(tmp_path / "recordings", log=lambda _: None)
    rec.hooks["coach"] = feed
    for i in range(470):
        frame = tick(i*.1, pit=1 if i >= 450 else 0)
        snap = S.SharedMemory()
        snap.mVersion, snap.mGameState, snap.mSessionState, snap.mRaceState = S.SHARED_MEMORY_VERSION, 2, 5, 2
        snap.mCarName, snap.mCarClassName = b"GT3", b"GT3"
        snap.mTrackLocation, snap.mTrackVariation, snap.mTrackLength = b"Track", b"Layout", 1000
        snap.mNumParticipants, snap.mViewedParticipantIndex = 2, 0
        snap.mSpeed, snap.mThrottle = frame.local["speed"], frame.local["throttle"]
        snap.mSteering = frame.local["steering"]
        for car in frame.cars:
            p = snap.mParticipantInfo[car.slot]
            p.mIsActive, p.mName = True, car.name.encode()
            p.mRacePosition, p.mLapsCompleted, p.mCurrentLap = car.position, car.laps, car.laps+1
            p.mCurrentLapDistance = car.distance
            snap.mSpeeds[car.slot], snap.mPitModes[car.slot], snap.mRaceStates[car.slot] = car.speed, car.pit, car.race_state
            snap.mCarNames[car.slot].value, snap.mCarClassNames[car.slot].value = car.car.encode(), car.car_class.encode()
        rec.step(snap, frame.t)
    rec.close(47)
    report = run_replay(rec.completed[0], tmp_path)
    events = [json.loads(line) for line in (Path(report["directory"])/"radio.jsonl").read_text().splitlines()]
    replayed = [(e["t"], e["text"]) for e in events if e["state"] == "would_say"]
    assert len(calls) == len(replayed) == 1
    assert calls[0][1] == replayed[0][1]
    assert calls[0][0] == pytest.approx(replayed[0][0], abs=.11)
