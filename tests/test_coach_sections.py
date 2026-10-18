"""C-01: biggest repeated section loss from earlier clean local laps, facts only."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ams2season.coach.catalogue import CATALOGUE
from ams2season.coach.engine import CoachEngine
from ams2season.coach.model import Car, Tick
from ams2season.coach.numbers import Numbers
from ams2season.coach.radio import Scheduler
from ams2season.coach.replay import run_replay
from ams2season.coach.sections import partition, spoken
from test_coach_corner_speed import frame as one_bend_frame
from test_coach_replay import write_recording

# 2000 m lap: bend A 480-520 m (slowed from lap 3), bend B 1480-1520 m (never changes).
# Long straights leave room for a radio window after each midpoint timing crossing.
LENGTH = 2000
NORMAL = 1920/50+40/40+40/40
SLOW = 1920/50+40/30+40/40


def frame(t, *, slower=True, lower=True, exit_lower=False, slow_laps=None, slow_reference=False):
    def slow(lap):
        if not slower:
            return False
        if slow_reference and lap == 1:
            return True
        return lap in slow_laps if slow_laps is not None else lap >= 3
    lap, start = 0, 0.
    while True:
        length = SLOW if slow(lap) else NORMAL
        if t < start+length:
            break
        start += length
        lap += 1
    phase, minimum = t-start, 30 if slow(lap) else 40
    segments = ((480, 50), (40, minimum), (960, 50), (40, 40), (480, 50))
    d, speed = 0., 50
    for metres, v in segments:
        if phase <= metres/v:
            d += phase*v
            speed = v
            break
        phase -= metres/v
        d += metres
    d = min(d, LENGTH-.1)
    in_a, in_b = 480 <= d <= 520, 1480 <= d <= 1520
    reading = (30 if lower else 40) if in_a and slow(lap) else 40 if in_a or in_b else 50
    if exit_lower and slow(lap) and 520 < d <= 590:
        reading = 40
    car = Car(0, 'Player', 'GT3', 'GT3', 1, lap, d, speed, 0, 2, False, 0)
    local = {'speed': reading, 'steering': .2 if 475 < d < 525 or 1475 < d < 1525 else .01,
             'throttle': .4 if 430 < d < 560 or 1430 < d < 1560 else 1., 'brake': 0., 'rain_density': 0.,
             'local_lap_invalid': False, 'crash_state': 0, 'yellow_flag_state': 0, 'local_sample_age_s': 0.}
    return Tick(t, 'test', 'practice', 'Track', 'Layout', LENGTH, 2, 0, (car,), local)


MIDPOINT_5 = 3*NORMAL+2*SLOW+480/50+40/30+480/50  # the fifth slow-lap interval completes here
END = MIDPOINT_5+8  # the straight after the timing line


def run(*, end=END, transform=lambda f: f, cached=False, **kwargs):
    engine = CoachEngine('Player', Scheduler(voice_duration=(lambda _: None) if cached else None))
    calls = []
    for i in range(int(end*10)+1):
        tick = transform(frame(i*.1, **kwargs))
        if tick is None:
            continue
        call = engine.feed(tick, radio_busy=False)
        if call:
            calls.append(call)
            engine.radio.acknowledge(call, engine.context, accepted=True, simulated=True)
    return engine, calls


def section_calls(calls):
    return [c for c in calls if c.message.spec.code == 'C-01']


def test_biggest_repeated_loss_names_the_section_size_and_one_measured_fact():
    engine, calls = run()
    found = section_calls(calls)
    assert len(found) == 1
    call, value = found[0], found[0].message.evidence.values
    assert call.text.split(':')[0] in ('Biggest loss', 'Main loss', 'Largest loss')
    assert 'the bend near five hundred' in call.text and 'three tenths, lower minimum speed.' in call.text
    assert 480 <= value['distance_m'] <= 520 and value['measured_sections'] == 2
    assert .3 <= value['loss_s'] <= .36 and value['facts'][0]['fact'] == 'lower_minimum_speed'
    assert value['cause_attributed'] is value['technique_recommended'] is value['thermal_compensation'] is False
    assert all(r['end_t'] < value['recent'][0]['start_t'] for r in value['reference_sections'])
    assert call.message.evidence.pattern_laps == (3, 4, 5)
    assert value['section_start_m'] >= 10 and value['section_end_m'] <= 990  # never across the midpoint line
    # The same bend is not called twice: C-01 already carries its minimum-speed fact.
    assert not any(c.message.spec.code == 'C-09' for c in calls)
    assert engine.diagnostics['confirmed_corner_speed_patterns'] == 1
    assert engine.status()['sections']['reason'] == 'confirmed_pattern'


def test_one_measured_section_is_never_called_the_biggest():
    engine = CoachEngine('Player')
    calls = []
    for i in range(1161):
        call = engine.feed(one_bend_frame(i*.1), radio_busy=False)
        if call:
            calls.append(call)
            engine.radio.acknowledge(call, engine.context, accepted=True, simulated=True)
    assert not section_calls(calls) and [c.message.spec.code for c in calls] == ['C-09']
    assert engine.status()['sections']['reason'] == 'need_two_measured_sections'


@pytest.mark.parametrize('kwargs', [{'end': MIDPOINT_5-.5}, {'slower': False}, {'slow_laps': (3, 4)},
                                    {'slow_reference': True}])
def test_no_premature_unrepeated_stale_or_reference_disagreeing_loss(kwargs):
    engine, calls = run(**kwargs)
    assert not section_calls(calls) and not engine.diagnostics.get('confirmed_section_losses')


def test_two_of_three_including_latest_counts():
    engine, calls = run(slow_laps=(3, 5))
    found = section_calls(calls)
    assert len(found) == 1 and found[0].message.evidence.pattern_laps == (3, 5)


def test_loss_without_a_measured_speed_change_is_reported_without_a_fact():
    engine, calls = run(lower=False)
    found = section_calls(calls)
    assert len(found) == 1 and found[0].text.endswith('three tenths.')
    assert found[0].message.evidence.values['facts'] == []
    assert found[0].message.evidence.values['spoken_fact'] is None


def test_exit_speed_is_recorded_and_the_first_fact_is_spoken():
    engine, calls = run(exit_lower=True)
    value = section_calls(calls)[0].message.evidence.values
    assert [f['fact'] for f in value['facts']] == ['lower_minimum_speed', 'lower_exit_speed']
    assert value['spoken_fact'] == 'lower minimum speed'


@pytest.mark.parametrize('fault', ['invalid', 'flag', 'incident', 'weather', 'traffic', 'pause', 'spectator', 'race'])
def test_unsafe_unknown_or_wrong_session_evidence_is_withheld(fault):
    def change(tick):
        car, local = tick.cars[0], dict(tick.local)
        if fault == 'invalid':
            car = replace(car, invalid=True)
        elif fault == 'flag':
            car = replace(car, flag_colour=2)
        elif fault == 'incident':
            local['crash_state'] = 3
        elif fault == 'weather':
            local.pop('rain_density')
        cars = (car, replace(car, slot=1, name='Other', distance=(car.distance+30) % LENGTH)) if fault == 'traffic' else (car,)
        return replace(tick, cars=cars, local=local, game_state=3 if fault == 'pause' else 2,
                       viewed_slot=1 if fault == 'spectator' else 0, session='race' if fault == 'race' else 'practice')
    engine, calls = run(transform=change)
    assert not section_calls(calls) and not engine.diagnostics.get('confirmed_section_losses')


def test_missing_clip_withholds_the_call_and_reports_it():
    engine, calls = run(cached=True)
    assert not calls and engine.diagnostics['confirmed_section_losses'] == 1
    assert any(e.get('code') == 'C-01' and e.get('reason') == 'voice_clip_missing' for e in engine.radio.log.events)


def test_pending_section_loss_is_dropped_when_traffic_appears():
    engine = CoachEngine('Player')
    for i in range(int(END*10)+1):
        engine.feed(frame(i*.1), radio_busy=True)
    assert any(m.spec.code == 'C-01' for m in engine.radio.pending.values())
    tick = frame(END+.1)
    other = replace(tick.cars[0], slot=1, name='Other', distance=(tick.cars[0].distance+30) % LENGTH)
    engine.feed(replace(tick, cars=(*tick.cars, other)), radio_busy=False)
    assert not any(m.spec.code == 'C-01' for m in engine.radio.pending.values())


def test_partition_splits_halfway_and_never_crosses_start_finish_or_the_midpoint():
    sections = partition([50, 150], 1000)  # bends at 250 m and 750 m
    assert sections == {50: (2, 98), 150: (102, 198)}
    close = partition([30, 60, 90], 1000)  # 150, 300, 450 m: halfway splits inside the first half
    assert close[30][1] == 45 and close[60] == (45, 75) and close[90][1] == 98
    assert partition([3], 1000) == {}  # too close to start/finish to have 20 m either side


def test_long_labels_keep_the_call_short_by_dropping_the_fact():
    phrases = CATALOGUE['C-01'].phrases
    fact = [{'fact': 'lower_minimum_speed', 'phrase': 'lower minimum speed'}]
    short = spoken(Numbers(), {'distance_m': 300, 'loss_s': .21, 'facts': fact}, phrases)
    assert short == {'turn': 'the bend near three hundred metres', 'loss': 'two tenths', 'detail': ', lower minimum speed'}
    assert all(len(p.format(**short).split()) <= 14 for p in phrases)
    long = spoken(Numbers(), {'distance_m': 5427, 'loss_s': 1.24, 'facts': fact}, phrases)
    assert long['detail'] == '' and long['loss'] == 'one point two seconds'


def test_section_replay_is_past_only_and_identical_at_both_speeds(tmp_path, monkeypatch):
    recording = Path(tmp_path)/'recordings'/'synthetic-sections'
    meta = write_recording(recording, [frame(i*.1) for i in range(int(END*10)+1)])
    meta.update(session_type='practice', track_length=LENGTH)
    (recording/'session.json').write_text(json.dumps(meta))
    now = [0.]
    monkeypatch.setattr('ams2season.coach.replay.time.monotonic', lambda: now[0])
    monkeypatch.setattr('ams2season.coach.replay.time.sleep', lambda s: now.__setitem__(0, now[0]+s))
    reports = [run_replay(recording, tmp_path, speed=speed) for speed in (1, 20)]
    events = [[json.loads(s) for s in (Path(r['directory'])/'radio.jsonl').read_text().splitlines()] for r in reports]
    assert events[0] == events[1] and all(r['inputs_unchanged'] for r in reports)
    assert any(e.get('code') == 'C-01' and e['state'] == 'would_say' for e in events[0])
    cached = run_replay(recording, tmp_path, voice_durations={})
    assert cached['explanation']['code'] == 'calls_withheld' and 'Section-loss' in cached['explanation']['text']


def offtrack_each_lap(tick, *, invalidate=False):
    car, local = tick.cars[0], dict(tick.local)
    if 960 < car.distance < 990:
        local['crash_state'] = 1  # AMS2's off-track state, e.g. an exit kerb used fully
    if invalidate and car.laps >= 3 and car.distance >= 960:
        local['local_lap_invalid'] = True  # the game itself deletes the lap
    return replace(tick, local=local)


def test_offtrack_state_on_a_lap_the_game_still_counts_is_not_an_incident():
    # Just before the timing line: an incident would also hold the call for 30 s.
    engine, calls = run(transform=offtrack_each_lap)
    assert len(section_calls(calls)) == 1
    assert engine.status()['learned_laps'] >= 2  # radio windows still learn from these laps


def test_only_the_games_own_invalid_flag_removes_a_lap():
    engine, calls = run(transform=lambda tick: offtrack_each_lap(tick, invalidate=True))
    assert not section_calls(calls) and not engine.diagnostics.get('confirmed_section_losses')


def test_impacts_spins_and_rolls_are_still_incidents():
    engine = CoachEngine('Player')
    for i in range(300):
        engine.feed(frame(i*.1), radio_busy=False)
    tick = frame(30.)
    engine.feed(replace(tick, local={**tick.local, 'crash_state': 1}), radio_busy=False)
    assert engine.context.since_incident > 25
    for state in (2, 3, 4, None):
        tick = frame(30.1)
        engine = CoachEngine('Player')
        engine.feed(frame(0.), radio_busy=False)
        engine.feed(replace(tick, local={**tick.local, 'crash_state': state}), radio_busy=False)
        assert engine.context.since_incident == 0
