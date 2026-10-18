"""Gearbox throttle cuts on a straight do not split radio windows; real lifts still do.

AMS2 reports the filtered throttle, so a paddle upshift reads as one or two samples of
zero throttle while the gear shows neutral. Recorded at Brands Hatch Indy 2026-10-14
(BMW Z4 GT3): every upshift on Brabham Straight did this, which cut a 5-6 s straight
into pieces under 3 s and left no window for any call.
"""
from dataclasses import replace

import pytest

from ams2season.coach.engine import CoachEngine
from ams2season.coach.model import Car, Tick
from ams2season.coach.radio import Scheduler
from ams2season.coach.telemetry import from_recorded, gear_value
from ams2season.coach.windows import SHIFT_S, WindowLearner
from test_coach_replay import tick


def shifting(t, *, at=300, samples=2, before=3, after=4, during=0, brake=0., steering=.01,
             throttle=0., gears=True):
    """The synthetic 1000 m lap from test_coach_replay with one gear change at `at` metres."""
    frame = tick(t)
    d = frame.cars[0].distance
    local = dict(frame.local)
    cut = at <= d < at+5*samples  # 50 m/s at 10 Hz: 5 m per sample
    if gears:
        local['gear'] = during if cut else (after if at+5*samples <= d < 800 else before)
    if cut:
        local.update(throttle=throttle, brake=brake, steering=steering)
    return replace(frame, local=local)


def learn(**kw):
    learner = WindowLearner(1000)
    for i in range(401):
        frame = shifting(i*.1, **kw)
        learner.feed(frame, frame.cars[0])
    assert len(learner.laps) == 2
    return learner


def test_an_upshift_cut_on_a_straight_keeps_the_straight_whole():
    learner = learn()
    # 50 m to the 800 m corner at the learned 57.5 m/s, minus the 1 s guard.
    assert learner.seconds(50, 50) == pytest.approx(750/57.5-1, abs=.2)
    assert learner.shifts_bridged >= 2
    assert all(learner._safe_bin(i) for i in range(0, 80))


@pytest.mark.parametrize('change', [
    dict(after=3, during=3),          # a lift with no gear change: the driver lifted
    dict(after=2, during=0),          # downshift
    dict(samples=5),                  # 0.5 s interruption: longer than a shift cut
    dict(gears=False),                # no gear channel (older recordings): cannot attribute it
    dict(brake=.2),                   # brakes during the interruption
    dict(steering=.2),                # wheel turned during the interruption
])
def test_anything_that_is_not_a_short_upshift_still_splits_the_window(change):
    learner = learn(**change)
    assert learner.shifts_bridged == 0
    assert learner.seconds(50, 50) < 4  # stops before the 300 m interruption
    assert not all(learner._safe_bin(i) for i in range(0, 80))


def test_a_partial_lift_that_recovers_without_a_gear_change_is_not_a_shift():
    learner = learn(after=3, during=3, throttle=.6, samples=1)
    assert learner.shifts_bridged == 0 and learner.seconds(50, 50) < 4


def test_an_interruption_still_open_at_the_line_is_not_bridged():
    learner = WindowLearner(1000)
    for i in range(401):
        frame = tick(i*.1)
        d = frame.cars[0].distance
        local = {**frame.local, 'throttle': 1., 'steering': .01, 'gear': 3}
        if d >= 990:
            local.update(throttle=0., gear=0)
        frame = replace(frame, local=local)
        learner.feed(frame, frame.cars[0])
    assert learner.shifts_bridged == 0
    assert not learner._safe_bin(99)


def test_shift_bound_matches_the_technique_filter():
    assert .3 <= SHIFT_S <= .4


def test_gear_is_read_from_live_and_recorded_telemetry():
    assert [gear_value(v) for v in (3, 3., 0, -1, 21, 2.5, None, float('nan'), 'x')] == [3, 3, 0, -1, None, None, None, None, None]
    recorded = from_recorded({'session_type': 'practice', 'track_length': 1000}, [], {'t': 1., 'gear': 4.}, 'rec', 1.)
    assert recorded.local['gear'] == 4
    assert from_recorded({'session_type': 'practice', 'track_length': 1000}, [], {'t': 1.}, 'rec', 1.).local['gear'] is None


# --- Practice summaries can wait for the main straight on a short lap ---------------

LENGTH = 2000.


def short_lap(t):
    """2000 m at 50 m/s. Only 1800 m -> 150 m is a straight, about 16 s after the halfway line."""
    distance = t*50 % LENGTH
    straight = distance >= 1800 or distance < 150
    car = Car(0, 'Player', 'GT3', 'GT3', 1, int(t*50 // LENGTH), distance, 50, 0, 2, False, 0)
    local = {'speed': 50., 'throttle': 1. if straight else .4, 'brake': 0., 'steering': .01 if straight else .3,
             'gear': 5, 'local_lap_invalid': False, 'crash_state': 0, 'rain_density': 0.,
             'yellow_flag_state': 0, 'fuel_capacity': 100., 'fuel_level': (60-t*.05)/100}
    return Tick(t, 'test', 'practice', 'Track', 'Layout', LENGTH, 2, 0, (car,), local)


def test_fuel_use_measured_at_halfway_is_said_on_the_straight_more_than_20_s_later():
    engine, calls = CoachEngine('Player', Scheduler()), []
    for i in range(2400):
        frame = short_lap(i*.1)
        call = engine.feed(frame, radio_busy=False)
        if call:
            calls.append((frame.t, frame.cars[0].distance, call))
            engine.radio.acknowledge(call, engine.context, accepted=True, simulated=True)
    calibrated = [e for e in engine.radio.log.events if e['state'] == 'fuel_calibrated']
    assert calibrated and calibrated[0]['distance'] == pytest.approx(1000, abs=10)
    assert calls, [(e['state'], e.get('reason')) for e in engine.radio.log.events if e.get('code') == 'S-16']
    t, distance, call = calls[0]
    assert call.message.spec.code == 'S-16' and distance >= 1800
    assert 15 < t-calibrated[0]['t'] < 20 and t+call.seconds > calibrated[0]['t']+20
    assert 'two point zero zero litres per lap' in call.text  # 0.05 L/s over 40 s laps
