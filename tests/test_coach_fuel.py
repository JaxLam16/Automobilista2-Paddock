"""Fuel range must come from complete measured laps, never assumed consumption."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ams2season.coach.engine import CoachEngine
from ams2season.coach.fuel import FuelWatch
from ams2season.coach.numbers import Numbers, Units
from ams2season.coach.radio import Scheduler
from ams2season.coach.replay import run_replay
from test_coach_gaps import frame as race_frame
from test_coach_replay import write_recording


def frame(t, *, litres=None, session='practice'):
    tick=race_frame(t)
    fuel=40-t*.1 if litres is None else litres
    return replace(tick,session=session,cars=(tick.cars[0],),
                   local={**tick.local,'fuel_capacity':100.,'fuel_level':fuel/100})


def feed_watch(frames):
    watch=FuelWatch();calibrations=[]
    for tick in frames:
        result=watch.feed(tick,tick.cars[0])
        if result:calibrations.append(result)
    return watch,calibrations


def test_three_full_laps_ignore_partial_start_and_measure_true_use_and_range():
    watch,calibrations=feed_watch([frame(i*.1) for i in range(701)])
    assert len(calibrations)==1
    measured=calibrations[0]
    assert measured['measured_t']==pytest.approx(66)
    assert measured['litres_per_lap']==pytest.approx(2)
    assert [(s['start_t'],s['end_t']) for s in measured['samples']]==[(6,26),(26,46),(46,66)]
    assert all(s['seconds']==pytest.approx(20) for s in measured['samples'])
    estimate=watch.estimate(70)
    assert estimate['fuel_litres']==pytest.approx(33)
    assert estimate['range_laps']==pytest.approx(16.5)
    assert estimate['range_low_laps']==pytest.approx(16.5)
    assert estimate['range_high_laps']==pytest.approx(16.5)
    assert watch.status(70,Numbers())['formatted']['use']['text']=='2.00 L/lap'


def fuel_over_intervals(t, amounts):
    # The first midpoint is t=6. Each following20s is a complete lap.
    used=min(t,6)*.1
    for i,amount in enumerate(amounts):
        elapsed=max(0,min(20,t-6-i*20))
        used+=amount*elapsed/20
    return 40-used


def test_observed_spread_produces_a_range_band_without_claiming_a_confidence_interval():
    amounts=(1.9,2,2.1,2)
    watch,_=feed_watch([frame(i*.1,litres=fuel_over_intervals(i*.1,amounts)) for i in range(671)])
    estimate=watch.estimate(67)
    assert estimate['litres_per_lap']==pytest.approx(2)
    assert estimate['spread_litres_per_lap']==pytest.approx(.2)
    assert estimate['range_low_laps']==pytest.approx(estimate['fuel_litres']/2.1)
    assert estimate['range_high_laps']==pytest.approx(estimate['fuel_litres']/1.9)


def test_variable_consumption_is_withheld_instead_of_silently_discarding_an_outlier():
    watch,results=feed_watch([frame(i*.1,litres=fuel_over_intervals(i*.1,(1,3,2,2))) for i in range(671)])
    assert results==[] and watch.estimate(67) is None
    assert watch.reason=='variable_consumption'
    assert len(watch.samples)==3


@pytest.mark.parametrize('fault',['missing_capacity','zero_capacity','missing_fuel','nan_fuel','missing_flags','missing_caution','missing_weather','invalid','incident','pit'])
def test_missing_or_unsafe_channels_never_produce_a_calibration(fault):
    frames=[]
    for i in range(701):
        tick=frame(i*.1);local=dict(tick.local);car=tick.cars[0]
        if fault=='missing_capacity':local.pop('fuel_capacity')
        elif fault=='zero_capacity':local['fuel_capacity']=0
        elif fault=='missing_fuel':local.pop('fuel_level')
        elif fault=='nan_fuel':local['fuel_level']=float('nan')
        elif fault=='missing_flags':car=replace(car,flag_colour=-1)
        elif fault=='missing_caution':local.pop('yellow_flag_state')
        elif fault=='missing_weather':local.pop('rain_density')
        elif fault=='invalid':car=replace(car,invalid=True)
        elif fault=='incident':local['crash_state']=3  # spinning; off-track alone is not an incident
        elif fault=='pit':car=replace(car,pit=2)
        frames.append(replace(tick,local=local,cars=(car,)))
    watch,results=feed_watch(frames)
    assert results==[] and watch.estimate(70) is None


def test_rejected_interval_does_not_teach_consumption_but_past_valid_laps_remain_traceable():
    frames=[]
    for i in range(871):
        tick=frame(i*.1)
        if i==380:tick=replace(tick,local={**tick.local,'local_lap_invalid':True})
        frames.append(tick)
    watch,results=feed_watch(frames)
    assert len(results)==1 and results[0]['measured_t']==pytest.approx(86)
    assert [(s['start_t'],s['end_t']) for s in watch.samples]==[(6,26),(46,66),(66,86)]
    assert watch.estimate(87)['litres_per_lap']==pytest.approx(2)


@pytest.mark.parametrize('fault',['refuel','capacity','gap','teleport','fuel_jump'])
def test_changed_or_discontinuous_fuel_state_invalidates_a_ready_model(fault):
    watch,_=feed_watch([frame(i*.1) for i in range(701)])
    assert watch.estimate(70)
    tick=frame(70.1)
    if fault=='refuel':tick=replace(tick,local={**tick.local,'fuel_level':.5})
    elif fault=='capacity':tick=replace(tick,local={**tick.local,'fuel_capacity':110})
    elif fault=='gap':tick=frame(72)
    elif fault=='teleport':tick=replace(tick,cars=(replace(tick.cars[0],distance=800),))
    elif fault=='fuel_jump':tick=replace(tick,local={**tick.local,'fuel_level':.1})
    watch.feed(tick,tick.cars[0])
    assert watch.estimate(tick.t) is None and not watch.samples


def test_constant_fuel_never_becomes_infinite_range_and_stale_calibration_is_withheld():
    watch,results=feed_watch([frame(i*.1,litres=40) for i in range(701)])
    assert results==[] and watch.estimate(70) is None
    watch,_=feed_watch([frame(i*.1) for i in range(701)])
    assert watch.estimate(70)
    assert watch.estimate(70.6) is None


def test_fuel_burn_uses_physical_units_even_when_range_preference_is_laps():
    assert Numbers(Units(fuel='laps')).fuel_burn(2.85).text=='2.85 L/lap'
    gallons=Numbers(Units(fuel='us_gallons')).fuel_burn(3.785411784)
    assert gallons.text=='1.00 US gal/lap' and 'gallons per lap' in gallons.speech


def run_engine(frames, *, cached=False):
    engine=CoachEngine('Player',Scheduler(voice_duration=(lambda text:None) if cached else None))
    calls=[]
    for tick in frames:
        call=engine.feed(tick,radio_busy=False)
        if call:
            calls.append(call)
            engine.radio.acknowledge(call,engine.context,accepted=True,simulated=True)
    return engine,calls


def test_practice_call_contains_measured_burn_but_no_finish_or_pit_claim():
    engine,calls=run_engine([frame(i*.1) for i in range(800)])
    assert len(calls)==1 and calls[0].message.spec.code=='S-16'
    assert 'two point zero zero litres per lap' in calls[0].text
    assert calls[0].message.evidence.values['source']=='measured_clean_midpoint_laps'
    assert engine.status()['fuel']['estimate'] is not None
    # Crew Chief owns the basic fuel-remaining call: no extra range radio rule.
    race,race_calls=run_engine([frame(i*.1,session='race') for i in range(800)])
    assert race_calls==[] and race.status()['fuel']['estimate']


def test_refuel_pause_or_spectating_invalidates_pending_practice_fuel_advice():
    for fault in ('refuel','pause','spectating'):
        engine=CoachEngine('Player')
        for i in range(671):engine.feed(frame(i*.1),radio_busy=True)
        assert any(m.spec.code=='S-16' for m in engine.radio.pending.values())
        tick=frame(67.1)
        if fault=='refuel':tick=replace(tick,local={**tick.local,'fuel_level':.5})
        elif fault=='pause':tick=replace(tick,game_state=3)
        elif fault=='spectating':tick=replace(tick,viewed_slot=1)
        assert engine.feed(tick,radio_busy=False) is None
        assert not engine.radio.pending and engine.status()['fuel']['estimate'] is None


def test_numeric_fuel_calls_remain_silent_without_exact_cached_phrases():
    engine,calls=run_engine([frame(i*.1) for i in range(800)],cached=True)
    assert calls==[] and engine.diagnostics['fuel_call_candidates']
    assert any(e.get('code')=='S-16' and e.get('reason')=='voice_clip_missing' for e in engine.radio.log.events)


def write_practice(directory, *, ended=False):
    frames=[frame(i*.1) for i in range(800)]
    if ended:frames.append(replace(frame(80),game_state=1))
    meta=write_recording(directory,frames)
    meta['session_type']='practice'
    (directory/'session.json').write_text(json.dumps(meta))


def test_fuel_replay_is_causal_at_one_and_twenty_times_speed_and_preserves_inputs(tmp_path,monkeypatch):
    recording=tmp_path/'practice';write_practice(recording)
    clock=[0.]
    monkeypatch.setattr('ams2season.coach.replay.time.monotonic',lambda:clock[0])
    monkeypatch.setattr('ams2season.coach.replay.time.sleep',lambda delay:clock.__setitem__(0,clock[0]+delay))
    reports=[run_replay(recording,tmp_path,speed=speed) for speed in (1,20)]
    events=[(Path(report['directory'])/'radio.jsonl').read_text() for report in reports]
    assert events[0]==events[1] and all(r['inputs_unchanged'] for r in reports)
    assert all(r['counts']['would_say']==1 and r['engine']['fuel']['estimate'] for r in reports)
    assert all(r['explanation']['code']=='calls_generated' for r in reports)


def test_historical_use_survives_menus_without_exposing_a_current_range():
    engine,_=run_engine([frame(i*.1) for i in range(800)])
    engine.feed(replace(frame(80),game_state=1),radio_busy=False)
    fuel=engine.status()['fuel']
    assert fuel['estimate'] is None and fuel['formatted'] is None
    assert fuel['last_calibration']['use']['text']=='2.00 L/lap'
    assert not {'fuel_litres','range_laps'} & fuel['last_calibration'].keys()
    engine.feed(replace(frame(80.1),track='Another track'),radio_busy=False)
    assert engine.status()['fuel']['last_calibration'] is None


def test_replay_uses_requested_units_and_records_them_as_provenance(tmp_path):
    recording=tmp_path/'practice';write_practice(recording)
    report=run_replay(recording,tmp_path,units=Units(fuel='us_gallons'))
    assert report['units']['fuel']=='us_gallons'
    assert report['engine']['fuel']['formatted']['use']['text']=='0.53 US gal/lap'
    assert any('U S gallons per lap' in json.loads(line).get('text','')
        for line in (Path(report['directory'])/'radio.jsonl').read_text().splitlines())


def test_offtrack_state_on_a_valid_lap_still_measures_fuel():
    frames=[frame(i*.1) for i in range(701)]
    frames=[replace(f,local={**f.local,'crash_state':1}) if 250<=i<=270 else f for i,f in enumerate(frames)]
    watch,calibrations=feed_watch(frames)
    assert len(calibrations)==1 and calibrations[0]['litres_per_lap']==pytest.approx(2)
