"""Race length is a causal leader estimate, never a personal fuel guarantee."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ams2season.coach.engine import CoachEngine
from ams2season.coach.race_length import RaceLengthWatch
from ams2season.coach.replay import run_replay
from ams2season.coach.telemetry import from_snapshot, from_recorded
from test_coach_gaps import frame as race_frame
from test_coach_replay import write_recording
from test_coach_service import snapshot


def frame(t, *, end=100, extra=1, laps=0, duration=100):
    tick = race_frame(t,back_speed=50)
    remaining = end-t if t<=end else -1
    return replace(tick,local={**tick.local,'race_laps':laps,'session_duration_s':duration,
        'session_additional_laps':extra,'event_time_remaining_s':remaining,
        'event_time_remaining_ms':remaining})


def feed(end=80, **kwargs):
    watch = RaceLengthWatch();updates=[]
    for i in range(int(end*10)+1):
        tick=frame(i*.1,**kwargs)
        value=watch.feed(tick,tick.cars[0])
        if value:updates.append(value)
    return watch,updates


def test_three_complete_leader_laps_establish_timed_finish_with_extra_lap():
    watch,updates=feed()
    assert updates and updates[0]['updated_t']==pytest.approx(76)
    value=updates[0]
    assert value['finish_lap_low']==value['finish_lap_high']==7
    assert value['source']=='observed_leader_finish_line_laps'
    assert value['scope']=='overall_leader'
    assert [(s['start_t'],s['end_t']) for s in value['samples']]==[(16,36),(36,56),(56,76)]
    assert value['minimum_lap_s']==value['maximum_lap_s']==20
    assert watch.status(80.6)['current'] is None
    assert watch.status(80.6)['last_estimate']['updated_t']==80


def test_timer_line_boundary_produces_a_range_not_false_precision():
    watch=RaceLengthWatch()
    for i in range(801):
        tick=frame(i*.1,end=96,extra=0,duration=96)
        watch.feed(tick,tick.cars[0])
    value=watch.status(80)['current']
    assert (value['finish_lap_low'],value['finish_lap_high'])==(5,6)


def test_actual_timer_finish_line_tie_waits_for_flag_instead_of_guessing_extra_lap():
    watch=RaceLengthWatch()
    for i in range(1201):
        tick=frame(i*.1,end=96,extra=1,duration=96)
        watch.feed(tick,tick.cars[0])
    assert watch.reason=='timer_finish_line_boundary_ambiguous'
    assert watch.status(120)['current'] is None


def test_seen_timer_expiry_latches_first_crossing_and_counts_extra_only_once():
    watch=RaceLengthWatch()
    values={}
    for i in range(1411):
        tick=frame(i*.1,extra=2)
        value=watch.feed(tick,tick.cars[0])
        if i in (1100,1161,1361):values[i]=value
    assert values[1100]['timer_expired']
    assert values[1161]['finish_lap_low']==values[1361]['finish_lap_low']==8
    assert watch.first_after_expiry==6


def test_delayed_finish_flag_does_not_invent_another_racing_lap():
    watch=RaceLengthWatch()
    for i in range(1171):
        tick=frame(i*.1,extra=0)
        watch.feed(tick,tick.cars[0])
    assert watch.reason=='awaiting_finish_state'
    assert watch.status(117)['current'] is None
    tick=frame(117.1,extra=0)
    leader=replace(tick.cars[0],race_state=3)
    result=watch.feed(replace(tick,cars=(leader,*tick.cars[1:])),tick.cars[1])
    assert result['state']=='observed_finish' and result['finish_lap_low']==6


def test_lap_limit_does_not_apply_timed_extra_laps_or_promise_personal_distance():
    tick=frame(20,laps=10,duration=0,extra=1)
    # Overall leader can be from a faster class; never substitute the class leader.
    player=replace(tick.cars[0],position=3,car_class='GT4')
    leader=replace(tick.cars[1],position=1,car_class='GT3')
    watch=RaceLengthWatch()
    value=watch.feed(replace(tick,cars=(player,leader)),player)
    assert value['state']=='scheduled' and value['finish_lap_low']==10
    assert value['leader']==leader.identity and value['scope']=='overall_leader'
    assert 'player_finish_lap' not in value and 'fuel_to_finish' not in value


@pytest.mark.parametrize('fault', ['unknown_extra','unknown_duration','conflicting_limit','missing_timer',
    'timer_already_negative','wrong_millisecond_scale','frozen_timer','missing_leader','duplicate_leader'])
def test_unknown_ambiguous_or_noncounting_inputs_withhold_timed_forecast(fault):
    watch=RaceLengthWatch()
    for i in range(801):
        tick=frame(i*.1);local=dict(tick.local);cars=tick.cars
        if fault=='unknown_extra':local.pop('session_additional_laps')
        elif fault=='unknown_duration':local.pop('session_duration_s')
        elif fault=='conflicting_limit':local['race_laps']=10
        elif fault=='missing_timer':local.pop('event_time_remaining_s')
        elif fault=='timer_already_negative':local['event_time_remaining_s']=-1
        elif fault=='wrong_millisecond_scale':local['event_time_remaining_s']*=1000
        elif fault=='frozen_timer':local['event_time_remaining_s']=100
        elif fault=='missing_leader':cars=tuple(replace(c,position=c.position+1) for c in cars)
        elif fault=='duplicate_leader':cars=tuple(replace(c,position=1) for c in cars)
        tick=replace(tick,local=local,cars=cars)
        assert watch.feed(tick,tick.cars[0]) is None


@pytest.mark.parametrize('fault',['pit','invalid','yellow','unknown_flag','gap','teleport','counter','pause','identity','timer_restart'])
def test_ready_forecast_cannot_survive_current_or_continuity_fault(fault):
    watch,_=feed();tick=frame(80.1);leader=tick.cars[0]
    if fault=='pit':leader=replace(leader,pit=1)
    elif fault=='invalid':leader=replace(leader,invalid=True)
    elif fault=='yellow':tick=replace(tick,local={**tick.local,'yellow_flag_state':1})
    elif fault=='unknown_flag':leader=replace(leader,flag_colour=-1)
    elif fault=='gap':tick=frame(82)
    elif fault=='teleport':leader=replace(leader,distance=600)
    elif fault=='counter':leader=replace(leader,laps=leader.laps+3)
    elif fault=='identity':leader=replace(leader,name='New leader')
    elif fault=='timer_restart':tick=replace(tick,local={**tick.local,'event_time_remaining_s':100})
    tick=replace(tick,cars=(leader,*tick.cars[1:]))
    assert watch.feed(tick,leader,active=fault!='pause',reason='paused') is None
    assert watch.status(tick.t)['current'] is None


def test_lagging_counter_at_finish_line_requires_confirmation_before_learning():
    watch=RaceLengthWatch()
    for i in range(801):
        tick=frame(i*.1)
        if i in (160,360,560,760):
            leader=replace(tick.cars[0],laps=tick.cars[0].laps-1)
            tick=replace(tick,cars=(leader,*tick.cars[1:]))
        value=watch.feed(tick,tick.cars[0])
        if i==760:assert value is None
    assert watch.status(80)['current']['finish_lap_low']==7


def test_rounded_track_endpoint_and_small_pre_wrap_overshoot_do_not_erase_laps():
    watch=RaceLengthWatch()
    for i in range(801):
        tick=frame(i*.1)
        if i in (159,359,559,759):
            leader=replace(tick.cars[0],distance=1000.18)
            tick=replace(tick,cars=(leader,*tick.cars[1:]))
        watch.feed(tick,tick.cars[0])
    assert watch.status(80)['current']['finish_lap_low']==7
    assert all(19.8<s['seconds']<20.2 for s in watch.samples)


def test_inconsistent_full_lap_pace_withholds_forecast():
    watch=RaceLengthWatch()
    for i in range(901):
        t=i*.1;tick=frame(t,end=200,duration=200)
        if t>=56:
            progress=3000+(t-56)*1000/30
            leader=replace(tick.cars[0],laps=int(progress//1000),distance=progress%1000)
            tick=replace(tick,cars=(leader,*tick.cars[1:]))
        assert watch.feed(tick,tick.cars[0]) is None
    assert watch.reason=='leader_pace_variable_or_stale'


def test_late_capture_after_expiry_never_invents_the_first_post_timer_crossing():
    watch=RaceLengthWatch()
    for i in range(1020,1901):
        tick=frame(i*.1,end=100,extra=2)
        assert watch.feed(tick,tick.cars[0]) is None
    assert watch.status(190)['current'] is None


def test_finished_overall_leader_is_observed_without_a_timer_or_pace_guess():
    tick=frame(80);leader=replace(tick.cars[0],race_state=3,laps=4)
    tick=replace(tick,cars=(leader,*tick.cars[1:]),local={**tick.local,'event_time_remaining_s':-1})
    watch=RaceLengthWatch();value=watch.feed(tick,tick.cars[1])
    assert value['state']=='observed_finish' and value['finish_lap_low']==4
    assert value['source']=='observed_leader_finished'


def test_pause_retains_only_labelled_historical_estimate_and_identity_clears_it():
    watch,_=feed();tick=frame(80.1)
    watch.feed(tick,tick.cars[0],active=False,reason='paused')
    assert watch.status(80.1)['current'] is None
    assert watch.status(80.1)['last_estimate']['updated_t']==80
    leader=replace(tick.cars[0],name='Joined')
    watch.feed(replace(tick,cars=(leader,*tick.cars[1:])),leader)
    assert watch.status(80.1)['last_estimate'] is None


def test_adapter_uses_real_seconds_despite_legacy_names_and_rejects_unknown_versions():
    snap=snapshot();snap.mVersion=14;snap.mLapsInEvent=0
    snap.mSessionDuration=1200;snap.mSessionAdditionalLaps=1;snap.mEventTimeRemaining=600
    live=from_snapshot(snap,1,'test')
    assert live.local['session_duration_s']==1200
    assert live.local['event_time_remaining_s']==600
    meta={'track_length':1000,'session_type':'race','shm_version':14,'laps_in_event':0,
          'session_duration_min':1200,'session_additional_laps':1}
    old=from_recorded(meta,[],{'t':1,'event_time_remaining_ms':600},'test',1)
    assert old.local['event_time_remaining_s']==600 and old.local['session_duration_s']==1200
    old=from_recorded({**meta,'shm_version':None},[],{'t':1,'event_time_remaining_ms':600},'test',1)
    assert old.local['event_time_remaining_s'] is None and old.local['session_duration_s'] is None


def write_timed(directory):
    meta=write_recording(directory,[frame(i*.1) for i in range(801)])
    meta.update(shm_version=14,laps_in_event=0,session_duration_min=100,session_additional_laps=1)
    (directory/'session.json').write_text(json.dumps(meta),encoding='utf-8')


def test_engine_and_replay_log_measurement_without_duplicate_cc_laps_calls(tmp_path,monkeypatch):
    engine=CoachEngine('Player')
    for i in range(801):
        tick=frame(i*.1);call=engine.feed(tick,radio_busy=False)
        if call:engine.radio.acknowledge(call,engine.context,accepted=True,simulated=True)
    events=[e for e in engine.radio.log.events if e['state']=='race_length_updated']
    assert len(events)==1 and events[0]['code']=='P-02'
    assert engine.status()['race_length']['current']['finish_lap_low']==7
    assert not any(e.get('code')=='P-02' and e['state'] in ('queued','would_say') for e in engine.radio.log.events)
    recording=tmp_path/'timed';write_timed(recording)
    now=[0.]
    monkeypatch.setattr('ams2season.coach.replay.time.monotonic',lambda:now[0])
    monkeypatch.setattr('ams2season.coach.replay.time.sleep',lambda seconds:now.__setitem__(0,now[0]+seconds))
    reports=[run_replay(recording,tmp_path,speed=speed) for speed in (1,20)]
    actual=[[json.loads(s) for s in (Path(r['directory'])/'radio.jsonl').read_text().splitlines()] for r in reports]
    assert actual[0]==actual[1] and all(r['inputs_unchanged'] for r in reports)
    assert all(r['engine']['race_length']['current']['finish_lap_low']==7 for r in reports)
    assert 'Overall leader finish:' in Path(reports[0]['review']).read_text()
