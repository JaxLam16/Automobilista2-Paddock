"""Original spotter integration and audio interruption; no real audio devices."""
from dataclasses import replace
import hashlib
import json
import sys
import threading
import time

import pytest

from ams2season.coach.crew_spotter import ASSETS, DEFAULTS, CrewChiefSounds, Spotter
from ams2season.coach.model import Car, Tick
from ams2season.coach.speech import LocalRadio
from ams2season.coach.voice import pcm_wav


def scene(t, *, right=True, left=False):
    z = 1000 - t * 50
    def car(slot, x, dz):
        return Car(slot, 'Driver' + str(slot), 'GT3', 'GT3', slot + 1, 2, 100, 50, 0, 2, False,
                   x=x, z=z + dz)
    p = car(0, 100, 0)
    return Tick(t, 's', 'race', 'Track', 'Layout', 2000, 2, 0,
                (p, car(1, 97 if right else 150, 1), car(2, 103 if left else 160, -1)),
                {'speed': 50, 'orientation_yaw': 0, 'world_velocity': (0, -50), 'local_sample_age_s': 0})


def test_pinned_original_source_and_default_parameters():
    manifest = json.loads((ASSETS / 'provenance.json').read_text())
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((ASSETS / name).read_bytes()).hexdigest() == digest
    assert DEFAULTS['spotter_overlap_delay'] == 50
    assert DEFAULTS['spotter_clear_delay'] == 150
    assert DEFAULTS['spotter_hold_repeat_frequency'] == 3
    assert DEFAULTS['max_closing_speed_for_spotter'] == 12
    assert DEFAULTS['time_after_race_start_for_spotter'] == 5


@pytest.mark.parametrize('change', [dict(fresh=False), dict(game_state=3), dict(game_state=5), dict(viewed_slot=1)])
def test_no_spotting_stale_paused_replay_or_spectator(change):
    requests = []
    spotter = Spotter(host=lambda p: requests.append(p) or {'calls': []})
    tick = replace(scene(1), **change)
    assert spotter.feed(tick, tick.cars[0]) == [] and requests == []


def test_source_input_transform_and_full_reset_after_roster_change():
    requests = []
    spotter = Spotter(host=lambda p: requests.append(p) or {'calls': []})
    for t in (1, 1.1):
        tick = scene(t)
        spotter.feed(tick, tick.cars[0])
    assert requests[0]['rotation'] == 0 and requests[0]['velocity'] == [50, 0, -50]
    assert [p['reset'] for p in requests] == [True, False]
    tick = scene(1.2)
    tick = replace(tick, cars=(*tick.cars[:2], replace(tick.cars[2], name='New entrant')))
    spotter.feed(tick, tick.cars[0])
    assert requests[-1]['reset']


def test_race_start_delay_matches_original_ams2_adapter():
    requests = []
    spotter = Spotter(host=lambda p: requests.append(p) or {'calls': []})
    tick = scene(0)
    waiting = replace(tick.cars[0], race_state=0)
    spotter.feed(replace(tick, cars=(waiting, *tick.cars[1:])), waiting)
    for i in range(1, 53):
        tick = scene(i / 10)
        spotter.feed(tick, tick.cars[0])
    assert requests and requests[0]['t'] >= 5.1


@pytest.mark.skipif(sys.platform != 'win32', reason='Runs original C# with Windows .NET Framework')
def test_original_state_machine_right_middle_partial_clear_all_clear_and_repeat():
    spotter = Spotter()
    spotter.start()
    try:
        assert spotter.ready.wait(10), spotter.error
        calls = []
        for i in range(145):
            tick = scene(i / 10, right=10 <= i < 95, left=20 <= i < 110)
            calls.extend((tick.t, c['folder']) for c in spotter.feed(tick, tick.cars[0]))
        folders = [f for _, f in calls]
        assert folders[0] == 'spotter/car_right'
        assert 'spotter/in_the_middle' in folders
        assert 'spotter/still_there' in folders
        assert 'spotter/clear_right' in folders
        assert folders[-1] == 'spotter/clear_all_round'
        holds = [t for t, f in calls if f == 'spotter/still_there']
        assert holds[1] - holds[0] >= 3
    finally:
        spotter.close()


class SlowVoice:
    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()
    def duration(self, text): return .1
    def get(self, text):
        from types import SimpleNamespace
        self.entered.set()
        assert self.release.wait(3)
        return SimpleNamespace(data=pcm_wav(b'\0\0' * 2205))


@pytest.mark.parametrize('action', ['cancel', 'close', 'context', 'expire'])
def test_rendered_audio_cannot_survive_interruption_or_context_change(action):
    voice, played = SlowVoice(), []
    valid, clock = [True], [1.0]
    radio = LocalRadio(voice, sink=(played.append, lambda: None), effect='off', clock=lambda: clock[0])
    assert radio.say('old', 'Old call.', valid=lambda: valid[0], deadline=2)
    assert voice.entered.wait(2)
    if action == 'cancel': radio.cancel_all()
    elif action == 'close': radio.close()
    elif action == 'context': valid[0] = False
    else: clock[0] = 3
    voice.release.set()
    deadline = time.monotonic() + 2
    while radio.current and time.monotonic() < deadline:
        time.sleep(.01)
    radio.close()
    assert played == []
    assert any(e['event'] == 'dropped' for e in radio.drain())


def test_custom_car_dimensions_and_exact_match_before_wildcard(tmp_path):
    sounds = CrewChiefSounds(tmp_path)
    sounds.classes = [{'ams2ClassNames': ['GT*'], 'spotterVehicleLength': 5},
                      {'ams2ClassNames': ['GT3'], 'spotterVehicleLength': 4.3, 'spotterVehicleWidth': 1.9}]
    assert sounds.dimensions('GT3') == (4.3, 1.9)
    assert sounds.dimensions('GT4') == (5, 1.8)
    assert sounds.dimensions('Unknown') == (4.5, 1.8)


@pytest.mark.skipif(sys.platform != 'win32', reason='Runs original C# with Windows .NET Framework')
def test_new_recording_replays_original_spotter_inputs_and_preserves_raw_files(tmp_path):
    from ams2season import shm as S
    from ams2season.recorder import Recorder
    from ams2season.coach.replay import run_replay
    recorder = Recorder(tmp_path / 'recordings', log=lambda _: None)
    for i in range(140):
        tick = scene(i / 20, right=20 <= i < 70, left=40 <= i < 100)
        snap = S.SharedMemory()
        snap.mVersion, snap.mGameState, snap.mSessionState, snap.mRaceState = S.SHARED_MEMORY_VERSION, 2, 5, 2
        snap.mTrackLocation, snap.mTrackVariation, snap.mTrackLength = b'Track', b'Layout', 2000
        snap.mCarName, snap.mCarClassName = b'GT3', b'GT3'
        snap.mSpeed, snap.mNumParticipants, snap.mViewedParticipantIndex = 50, 3, 0
        snap.mWorldVelocity[2] = -50
        snap.mThrottle = 1
        for c in tick.cars:
            p = snap.mParticipantInfo[c.slot]
            p.mName, p.mIsActive, p.mRacePosition = c.name.encode(), True, c.position
            p.mLapsCompleted, p.mCurrentLapDistance = c.laps, c.distance
            p.mWorldPosition[0], p.mWorldPosition[2] = c.x, c.z
            snap.mCarNames[c.slot].value, snap.mCarClassNames[c.slot].value = b'GT3', b'GT3'
            snap.mSpeeds[c.slot], snap.mRaceStates[c.slot] = 50, 2
        recorder.step(snap, tick.t)
    path = recorder.active.path
    recorder.close(7)
    report = run_replay(path, tmp_path, spotter_enabled=True)
    assert report['inputs_unchanged'] and not report['audio_played']
    assert report['spotter']['status'] == 'simulated' and report['spotter']['calls'] >= 4
    assert report['spotter']['input_samples'] == 140


def test_older_recording_reports_missing_original_spotter_channels(tmp_path):
    from ams2season.coach.replay import run_replay
    from test_coach_replay import write_recording
    path = tmp_path / 'recordings/old'
    write_recording(path)
    report = run_replay(path, tmp_path, spotter_enabled=True)
    assert report['spotter']['status'] == 'missing_heading_or_world_velocity'
    assert 'lacks the exact local heading or world velocity' in report['explanation']['text']
