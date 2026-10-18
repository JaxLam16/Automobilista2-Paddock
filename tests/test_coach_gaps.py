"""Known crossing times verify gap direction, continuity and same-rival isolation."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ams2season.coach.engine import CoachEngine
from ams2season.coach.gaps import GapWatch
from ams2season.coach.model import Car, Tick
from ams2season.coach.replay import run_replay
from ams2season.coach.radio import Scheduler
from ams2season.coach.telemetry import from_snapshot
from test_coach_replay import write_recording
from test_coach_service import snapshot


def frame(t, back_speed=49):
    cars=[]
    for slot, (name, start, speed) in enumerate((('Player',200,50),('Behind',50,back_speed))):
        progress=start+t*speed
        cars.append(Car(slot,name,'GT3','GT3',slot+1,int(progress//1000),progress%1000,speed,0,2,False,0))
    distance=cars[0].distance
    local={'speed':50,'throttle':1 if distance<800 else .2,'brake':0,
           'steering':.01 if distance<800 else .3,'local_lap_invalid':False,'crash_state':0,
           'rain_density':0,'yellow_flag_state':0}
    return Tick(t,'test','race','Track','Layout',1000,2,0,tuple(cars),local)


def run_frames(frames, *, busy=False):
    engine=CoachEngine('Player');calls=[]
    for item in frames:
        selected=engine.feed(item,radio_busy=busy)
        if selected:
            calls.append(selected)
            engine.radio.acknowledge(selected,engine.context,accepted=True,simulated=True)
    return engine,calls


@pytest.mark.parametrize('speed,trend',[(49,'opening'),(50,'steady'),(50.5,'closing')])
def test_crossing_gaps_have_known_times_and_sign_without_speed_based_estimates(speed,trend):
    watch=GapWatch();found=[]
    for i in range(800):
        tick=frame(i*.1,speed)
        value=watch.feed(tick,*tick.cars)
        if value:found.append(value)
    assert found and found[0]['trend']==trend
    result=found[0]
    assert len(result['samples'])==3
    for sample in result['samples']:
        lap=sample['lap']
        assert sample['player_crossing_t']==pytest.approx((lap*1000+500-200)/50)
        assert sample['rival_crossing_t']==pytest.approx((lap*1000+500-50)/speed)
        assert sample['gap_s']==pytest.approx(sample['rival_crossing_t']-sample['player_crossing_t'])
    assert result['change_per_lap_s']==pytest.approx(1000/speed-20)


def test_real_engine_generates_measured_gap_after_three_crossings_and_two_learned_laps():
    engine,calls=run_frames([frame(i*.1) for i in range(800)])
    assert calls
    gap_calls=[call for call in calls if call.message.spec.code=='G-18']
    assert len(gap_calls)==1
    call=gap_calls[0]
    assert 'growing' in call.text and 'behind' in call.text
    assert call.message.evidence.values['source']=='matched_midpoint_crossings'
    assert call.message.evidence.values['trend']=='opening'
    assert call.message.created>49
    assert engine.radio.log.counts['would_say']==1


@pytest.mark.parametrize('fault',['pit','invalid','yellow','missing_flags','fcy','crash','pause','gap','teleport','new_rival','wrong_class'])
def test_disrupted_or_unknown_evidence_cannot_form_a_three_crossing_trend(fault):
    frames=[]
    for i in range(800):
        tick=frame(i*.1)
        if fault=='gap' and 300<=i<=310:continue
        if i==300 or (fault in ('new_rival','wrong_class','missing_flags') and i>=300):
            player,behind=tick.cars
            if fault=='pit':behind=replace(behind,pit=1)
            elif fault=='invalid':behind=replace(behind,invalid=True)
            elif fault=='yellow':behind=replace(behind,flag_colour=6)
            elif fault=='missing_flags':behind=replace(behind,flag_colour=-1)
            elif fault=='fcy':tick=replace(tick,local={**tick.local,'yellow_flag_state':1})
            elif fault=='crash':tick=replace(tick,local={**tick.local,'crash_state':3})
            elif fault=='pause':tick=replace(tick,game_state=3)
            elif fault=='teleport':behind=replace(behind,distance=behind.distance+200)
            elif fault=='new_rival':behind=replace(behind,name='Joined')
            elif fault=='wrong_class':behind=replace(behind,car_class='Other class')
            tick=replace(tick,cars=(player,behind))
        frames.append(tick)
    engine,calls=run_frames(frames)
    assert not [c for c in calls if c.message.spec.code=='G-18']
    assert not engine.diagnostics['confirmed_gap_trends']


def test_lap_counter_lag_near_start_line_does_not_change_midpoint_timing():
    ordinary=[];lagged=[]
    for i in range(800):
        tick=frame(i*.1)
        ordinary.append(tick)
        lagged.append(replace(tick,cars=tuple(replace(c,laps=c.laps-1) if c.laps and c.distance<6 else c for c in tick.cars)))
    a,ac=run_frames(ordinary);b,bc=run_frames(lagged)
    assert [(c.text,c.message.evidence.values['gap_s']) for c in ac]==[(c.text,c.message.evidence.values['gap_s']) for c in bc]
    assert a.diagnostics['confirmed_gap_trends']==b.diagnostics['confirmed_gap_trends']>0


def test_pending_gap_call_drops_if_rival_or_race_evidence_changes_before_delivery():
    engine,_=run_frames([frame(i*.1) for i in range(510)],busy=True)
    assert any(m.spec.code=='G-18' for m in engine.radio.pending.values())
    tick=frame(51)
    tick=replace(tick,cars=(tick.cars[0],replace(tick.cars[1],flag_colour=6)))
    assert engine.feed(tick,radio_busy=False) is None
    assert not engine.radio.pending
    assert any(e.get('code')=='G-18' and e.get('reason')=='condition_changed' for e in engine.radio.log.events)


def test_gap_rule_requires_known_flags_and_local_state_in_snapshot_adapter():
    snap=snapshot()
    snap.mHighestFlagColours[0]=6
    snap.mYellowFlagState=1
    tick=from_snapshot(snap,1,'test')
    assert tick.cars[0].flag_colour==6 and tick.local['yellow_flag_state']==1


def test_gap_replay_matches_live_causally_without_modifying_originals(tmp_path):
    frames=[frame(i*.1) for i in range(800)]
    _,live=run_frames(frames)
    recording=tmp_path/'race'
    write_recording(recording,frames)
    result=run_replay(recording,tmp_path)
    assert result['inputs_unchanged'] and result['counts']['would_say']==len(live)==1
    assert result['engine']['diagnostics']['confirmed_gap_trends']>0
    assert result['explanation']['code']=='calls_generated'


def test_missing_old_recording_flag_channels_withholds_gap_rule_without_breaking_pit_analysis(tmp_path):
    frames=[]
    for i in range(800):
        tick=frame(i*.1)
        local=dict(tick.local);local.pop('yellow_flag_state')
        frames.append(replace(tick,cars=tuple(replace(c,flag_colour=-1) for c in tick.cars),local=local))
    engine,calls=run_frames(frames)
    assert not calls and not engine.diagnostics['confirmed_gap_trends']


def test_cached_audio_does_not_fall_back_to_tts_for_new_numeric_gap_calls():
    engine=CoachEngine('Player',Scheduler(voice_duration=lambda text:None))
    for i in range(800):
        assert engine.feed(frame(i*.1),radio_busy=False) is None
    assert engine.diagnostics['confirmed_gap_trends']>0
    assert any(e.get('code')=='G-18' and e.get('reason')=='voice_clip_missing' for e in engine.radio.log.events)


def test_gap_crossing_events_are_identical_at_one_and_twenty_times_replay_speed(tmp_path, monkeypatch):
    recording=tmp_path/'race'
    write_recording(recording,[frame(i*.1) for i in range(800)])
    clock=[0.]
    monkeypatch.setattr('ams2season.coach.replay.time.monotonic',lambda:clock[0])
    monkeypatch.setattr('ams2season.coach.replay.time.sleep',lambda delay:clock.__setitem__(0,clock[0]+delay))
    reports=[run_replay(recording,tmp_path,speed=speed) for speed in (1,20)]
    events=[(Path(report['directory'])/'radio.jsonl').read_text() for report in reports]
    assert events[0]==events[1] and all(r['inputs_unchanged'] for r in reports)
    assert any(json.loads(line).get('code')=='G-18' for line in events[0].splitlines())


def test_offtrack_state_on_a_valid_lap_keeps_the_gap_trend():
    frames=[]
    for i in range(800):
        tick=frame(i*.1)
        if 300<=i<=320:tick=replace(tick,local={**tick.local,'crash_state':1})
        frames.append(tick)
    engine,calls=run_frames(frames)
    assert len([c for c in calls if c.message.spec.code=='G-18'])==1
