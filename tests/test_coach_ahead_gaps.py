"""Ahead trends use the actual same rival and already-completed matched crossings."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ams2season.coach.engine import CoachEngine
from ams2season.coach.gaps import GapWatch
from ams2season.coach.model import Car, Tick
from ams2season.coach.radio import Scheduler
from ams2season.coach.replay import run_replay
from test_coach_gaps import run_frames
from test_coach_radio import context, message
from test_coach_replay import write_recording


def frame(t, ahead_speed=49, *, lead_m=150,length=1000):
    cars=[]
    for slot,(name,start,speed,position) in enumerate((('Player',50,50,2),('Ahead',50+lead_m,ahead_speed,1))):
        progress=start+t*speed
        cars.append(Car(slot,name,'GT3','GT3',position,int(progress//length),progress%length,speed,0,2,False,0))
    distance=cars[0].distance
    local={'speed':50,'throttle':1 if distance<.95*length else .2,'brake':0,
           'steering':.01 if distance<.95*length else .3,'local_lap_invalid':False,'crash_state':0,
           'rain_density':0,'yellow_flag_state':0}
    return Tick(t,'ahead-race','race','Track','Layout',length,2,0,tuple(cars),local)


@pytest.mark.parametrize('speed,trend',[(49,'closing'),(50,'steady'),(51,'opening')])
def test_ahead_gap_and_rate_match_analytic_crossings_without_future_samples(speed,trend):
    watch=GapWatch('car ahead');found=[]
    for i in range(800):
        tick=frame(i*.1,speed)
        result=watch.feed(tick,*tick.cars)
        if result:found.append(result)
        if tick.t<9:assert watch.diagnostics['matched_gap_samples']==0
    assert found and found[0]['trend']==trend
    first=found[0]
    assert first['rival_name']=='Ahead' and first['relation']=='car ahead'
    assert first['measured_t']==pytest.approx(49)
    for sample in first['samples']:
        lap=sample['lap']
        assert sample['player_crossing_t']==pytest.approx((lap*1000+500-50)/50)
        assert sample['rival_crossing_t']==pytest.approx((lap*1000+500-200)/speed)
        assert sample['gap_s']==pytest.approx(sample['player_crossing_t']-sample['rival_crossing_t'])
    assert first['change_per_lap_s']==pytest.approx(20-1000/speed)


def test_ahead_token_ages_from_the_later_player_crossing():
    watch=GapWatch('car ahead')
    for i in range(491):
        tick=frame(i*.1)
        watch.feed(tick,*tick.cars)
    assert watch.token(60) is not None
    assert watch.token(61) is None


def test_engine_reports_numeric_ahead_gap_and_past_change_without_catch_or_corner_claims():
    engine,calls=run_frames([frame(i*.1) for i in range(800)])
    assert len(calls)==1 and calls[0].message.spec.code=='G-01'
    assert 'two point one seconds ahead' in calls[0].text
    assert 'shrank zero point four seconds per lap' in calls[0].text
    assert calls[0].seconds<6
    assert calls[0].message.evidence.values['rival_name']=='Ahead'
    assert engine.diagnostics['confirmed_ahead_gap_trends']>0
    assert not engine.diagnostics['confirmed_gap_trends']


def test_larger_ahead_gaps_use_actual_old_crossings_instead_of_a_twenty_second_cutoff():
    engine,calls=run_frames([frame(i*.1,50,lead_m=1150,length=5000) for i in range(2600)])
    assert len(calls)==1 and calls[0].message.evidence.values['gap_s']==pytest.approx(23)
    assert 'twenty-three seconds ahead' in calls[0].text
    assert engine.diagnostics['confirmed_ahead_gap_trends']==1


@pytest.mark.parametrize('fault',['new_rival','new_player_slot','pit','gap','teleport','pause','wrong_class','duplicate_position','lapped'])
def test_a_changed_pair_or_invalid_evidence_cannot_inherit_an_ahead_baseline(fault):
    frames=[]
    for i in range(800):
        if fault=='gap' and 300<=i<=310:continue
        tick=frame(i*.1)
        if i==300 or (fault in ('new_rival','new_player_slot','wrong_class','duplicate_position','lapped') and i>=300):
            player,rival=tick.cars
            if fault=='new_rival':rival=replace(rival,name='Joined')
            elif fault=='new_player_slot':player=replace(player,slot=2);tick=replace(tick,viewed_slot=2)
            elif fault=='pit':rival=replace(rival,pit=1)
            elif fault=='teleport':rival=replace(rival,distance=rival.distance+200)
            elif fault=='pause':tick=replace(tick,game_state=3)
            elif fault=='wrong_class':rival=replace(rival,car_class='Other')
            elif fault=='duplicate_position':rival=replace(rival,position=player.position)
            elif fault=='lapped':rival=replace(rival,laps=rival.laps+1)
            tick=replace(tick,cars=(player,rival))
        frames.append(tick)
    engine,calls=run_frames(frames)
    assert not [c for c in calls if c.message.spec.code=='G-01']
    assert not engine.diagnostics['confirmed_ahead_gap_trends']


def test_pending_ahead_advice_drops_on_an_overtake_before_delivery():
    engine,_=run_frames([frame(i*.1) for i in range(501)],busy=True)
    assert any(m.spec.code=='G-01' for m in engine.radio.pending.values())
    tick=frame(50.1)
    tick=replace(tick,cars=(replace(tick.cars[0],position=1),replace(tick.cars[1],position=2)))
    assert engine.feed(tick,radio_busy=False) is None
    assert not engine.radio.pending
    assert any(e.get('code')=='G-01' and e.get('reason')=='condition_changed' for e in engine.radio.log.events)


def test_past_incident_or_invalid_lap_is_retained_as_context_for_factual_gap_change():
    frames=[]
    for i in range(800):
        tick=frame(i*.1)
        if i==350:tick=replace(tick,local={**tick.local,'crash_state':3},
            cars=(tick.cars[0],replace(tick.cars[1],invalid=True,flag_colour=6)))
        frames.append(tick)
    _,calls=run_frames(frames)
    assert len(calls)==1
    values=calls[0].message.evidence.values
    assert values['scope']=='observed_past_gap_change'
    assert any(s['affected_interval'] for s in values['samples'])
    assert 'shrank' in calls[0].text


def test_bounded_backward_motion_away_from_timing_point_preserves_observed_gap_history():
    frames=[]
    for i in range(800):
        tick=frame(i*.1)
        if i==300:tick=replace(tick,cars=(replace(tick.cars[0],distance=tick.cars[0].distance-6),tick.cars[1]))
        frames.append(tick)
    _,calls=run_frames(frames)
    assert len(calls)==1
    assert any(s['affected_interval'] for s in calls[0].message.evidence.values['samples'])


def test_backward_recrossing_of_timing_point_cancels_an_ambiguous_pending_gap():
    engine,_=run_frames([frame(i*.1) for i in range(491)],busy=True)
    assert engine.radio.pending
    tick=frame(49.1)
    tick=replace(tick,cars=(replace(tick.cars[0],distance=495),tick.cars[1]))
    assert engine.feed(tick,radio_busy=False) is None
    assert not engine.radio.pending and engine.context.facts['timing:gap_ahead'] is None


@pytest.mark.parametrize('fault',['yellow','incident','caution','unknown_flags'])
def test_factual_ahead_report_is_withheld_under_unsafe_current_conditions(fault):
    frames=[]
    for i in range(800):
        tick=frame(i*.1)
        if i>=480:
            if fault=='yellow':tick=replace(tick,cars=(tick.cars[0],replace(tick.cars[1],flag_colour=6)))
            elif fault=='incident':tick=replace(tick,local={**tick.local,'crash_state':3})
            elif fault=='caution':tick=replace(tick,local={**tick.local,'yellow_flag_state':1})
            else:tick=replace(tick,cars=(tick.cars[0],replace(tick.cars[1],flag_colour=-1)))
        frames.append(tick)
    engine,calls=run_frames(frames)
    assert not calls and engine.context.facts['timing:gap_ahead'] is None


def test_finished_driver_is_quiet_even_while_remaining_rivals_enter_pits():
    engine=CoachEngine('Player')
    for i in range(550):
        tick=frame(i*.1)
        if i>=480:tick=replace(tick,cars=(replace(tick.cars[0],race_state=3),replace(tick.cars[1],pit=1)))
        assert engine.feed(tick,radio_busy=True) is None
    assert not engine.radio.pending
    assert engine.context.reason=='finished'
    assert engine.diagnostics['observed_relevant_pit_entries']==0


def test_finished_winner_stays_class_leader_and_your_own_stop_is_not_a_rival_call():
    from ams2season.coach.engine import relations
    tick=frame(40)
    tick=replace(tick,cars=(tick.cars[0],replace(tick.cars[1],race_state=3)))
    assert relations(tick,tick.cars[0])['class leader']==tick.cars[1].identity
    engine=CoachEngine('Player')
    for i in range(470):
        tick=frame(i*.1)
        tick=replace(tick,cars=(replace(tick.cars[0],position=1,pit=1 if i>=450 else 0),replace(tick.cars[1],position=2)))
        assert engine.feed(tick,radio_busy=False) is None
    assert engine.diagnostics['observed_relevant_pit_entries']==0


def test_numeric_ahead_calls_need_exact_cached_speech():
    engine=CoachEngine('Player',Scheduler(voice_duration=lambda text:None))
    for i in range(800):assert engine.feed(frame(i*.1),radio_busy=False) is None
    assert engine.diagnostics['confirmed_ahead_gap_trends']>0
    assert any(e.get('code')=='G-01' and e.get('reason')=='voice_clip_missing' for e in engine.radio.log.events)


def test_all_ahead_phrasings_remain_deliverable_on_a_stable_long_run():
    _,calls=run_frames([frame(i*.1,50) for i in range(3500)])
    assert {c.variant for c in calls if c.message.spec.code=='G-01'}=={0,1,2}
    assert all(c.seconds<=6 for c in calls)


def test_whole_sentence_must_fit_remaining_fact_lifetime_at_selection_and_fetch():
    ctx=context();radio=Scheduler(voice_duration=lambda text:1.5)
    too_late=replace(message(ctx),expires=ctx.t+1)
    radio.offer(too_late,ctx)
    assert radio.select(ctx) is None
    assert radio.log.events[-1]['reason']=='insufficient_lifetime'
    radio=Scheduler(voice_duration=lambda text:1.5)
    radio.offer(replace(message(ctx),expires=ctx.t+2),ctx)
    delivery=radio.select(ctx)
    assert delivery is not None
    assert radio.delivery_reason(delivery,replace(ctx,t=ctx.t+.8))=='insufficient_lifetime'


def test_ahead_replay_is_causal_at_one_and_twenty_times_and_preserves_originals(tmp_path,monkeypatch):
    recording=tmp_path/'race';write_recording(recording,[frame(i*.1) for i in range(800)])
    clock=[0.]
    monkeypatch.setattr('ams2season.coach.replay.time.monotonic',lambda:clock[0])
    monkeypatch.setattr('ams2season.coach.replay.time.sleep',lambda delay:clock.__setitem__(0,clock[0]+delay))
    reports=[run_replay(recording,tmp_path,speed=speed) for speed in (1,20)]
    events=[(Path(r['directory'])/'radio.jsonl').read_text() for r in reports]
    assert events[0]==events[1] and all(r['inputs_unchanged'] for r in reports)
    assert all(r['counts']['would_say']==1 and r['engine']['diagnostics']['confirmed_ahead_gap_trends']>0 for r in reports)
    assert any(json.loads(line).get('code')=='G-01' for line in events[0].splitlines())
