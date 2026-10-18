"""C-26: running wide on laps the game still counts gives a track-limits warning."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ams2season.coach.engine import CoachEngine
from ams2season.coach.offtrack import OffTrackWatch
from ams2season.coach.radio import Scheduler
from ams2season.coach.replay import run_replay
from test_coach_sections import LENGTH, NORMAL, frame as lap_frame
from test_coach_replay import write_recording

END = 3*NORMAL+5   # wide on laps 1 and 2, then the straight after the timing line
QUEUED = 2*NORMAL+16  # shortly after the lap-2 episode is confirmed


def frame(t, *, laps=(1, 2), spot=(600, 640), invalid=False, state=1, session='practice', second_spot=None):
    tick = lap_frame(t, slower=False)
    car, local = tick.cars[0], dict(tick.local)
    lo, hi = spot
    if second_spot and car.laps == laps[-1]:
        lo, hi = second_spot
    if car.laps in laps and lo <= car.distance < hi:
        local['crash_state'] = state
        if invalid:
            local['local_lap_invalid'] = True
    if invalid and car.laps in laps and car.distance >= lo:
        local['local_lap_invalid'] = True  # the game deletes the lap and keeps it deleted
    return replace(tick, local=local, session=session)


def run(*, end=END, cached=False, **kwargs):
    engine = CoachEngine('Player', Scheduler(voice_duration=(lambda _: None) if cached else None))
    calls = []
    for i in range(int(end*10)+1):
        call = engine.feed(frame(i*.1, **kwargs), radio_busy=False)
        if call:
            calls.append(call)
            engine.radio.acknowledge(call, engine.context, accepted=True, simulated=True)
    return engine, [c for c in calls if c.message.spec.code == 'C-26']


@pytest.mark.parametrize('session', ['practice', 'race'])
def test_running_wide_twice_at_the_same_spot_warns_about_track_limits(session):
    engine, calls = run(session=session)
    assert len(calls) == 1
    call, value = calls[0], calls[0].message.evidence.values
    assert 'near six hundred metres' in call.text and 'track limits' in call.text
    assert value['laps'] == [1, 2] and value['lap_still_valid'] is True
    assert value['track_limit_margin_known'] is False and value['cause_attributed'] is False
    assert engine.status()['offtrack']['spots'] == [600]


def test_qualifying_waits_until_the_push_lap_is_over():
    engine, calls = run(session='qualify')
    assert not calls and any(e.get('code') == 'C-26' and e.get('reason') == 'qualifying_push'
                             for e in engine.radio.log.events)


@pytest.mark.parametrize('kwargs', [{'laps': (2,)}, {'invalid': True}, {'state': 3}, {'state': None},
                                    {'second_spot': (1200, 1240)}, {'laps': (0, 3), 'end': 4*NORMAL}])
def test_one_off_deleted_lap_incident_unknown_or_different_spot_is_not_a_warning(kwargs):
    engine, calls = run(**kwargs)
    assert not calls and not engine.diagnostics.get('confirmed_offtrack_warnings')


def test_a_lap_deleted_after_the_warning_was_queued_cancels_it():
    engine = CoachEngine('Player')
    for i in range(int(QUEUED*10)+1):
        engine.feed(frame(i*.1), radio_busy=True)
    assert any(m.spec.code == 'C-26' for m in engine.radio.pending.values())
    tick = frame(QUEUED+.1)
    engine.feed(replace(tick, local={**tick.local, 'local_lap_invalid': True}), radio_busy=False)
    assert not any(m.spec.code == 'C-26' for m in engine.radio.pending.values())
    assert any(e.get('code') == 'C-26' and e.get('reason') == 'condition_changed' for e in engine.radio.log.events)


def test_watch_needs_a_second_back_on_track_with_the_lap_still_valid():
    watch = OffTrackWatch()
    events = []
    for i in range(int(END*10)+1):
        tick = frame(i*.1)
        events += watch.feed(tick, tick.cars[0])
    assert len(events) == 1
    first, second = events[0]['episodes']
    assert second['start_m'] >= 600 and second['seconds'] == pytest.approx(.8, abs=.11)
    assert events[0]['measured_t'] - second['end_t'] >= 1.0


def test_missing_clip_and_replay_parity(tmp_path, monkeypatch):
    engine, calls = run(cached=True)
    assert not calls and engine.diagnostics['confirmed_offtrack_warnings'] == 1
    recording = Path(tmp_path)/'recordings'/'synthetic-wide'
    meta = write_recording(recording, [frame(i*.1) for i in range(int(END*10)+1)])
    meta.update(session_type='practice', track_length=LENGTH)
    (recording/'session.json').write_text(json.dumps(meta))
    now = [0.]
    monkeypatch.setattr('ams2season.coach.replay.time.monotonic', lambda: now[0])
    monkeypatch.setattr('ams2season.coach.replay.time.sleep', lambda s: now.__setitem__(0, now[0]+s))
    reports = [run_replay(recording, tmp_path, speed=speed) for speed in (1, 20)]
    events = [[json.loads(s) for s in (Path(r['directory'])/'radio.jsonl').read_text().splitlines()] for r in reports]
    assert events[0] == events[1] and all(r['inputs_unchanged'] for r in reports)
    assert any(e.get('code') == 'C-26' and e['state'] == 'would_say' for e in events[0])
    silent = run_replay(recording, tmp_path, voice_durations={})
    assert 'Running-wide' in silent['explanation']['text']
