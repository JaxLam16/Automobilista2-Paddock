"""Mapped geometry, past-only references and repeated local apex evidence."""
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path

import pytest

from ams2season.coach.apex import ApexMapStore,ApexWatch,map_path
from ams2season.coach.engine import CoachEngine
from ams2season.coach.model import Car,Tick
from ams2season.coach.radio import Scheduler
from ams2season.coach.replay import run_replay
from ams2season.coach.telemetry import from_recorded,from_snapshot
from test_coach_replay import write_recording
from test_coach_service import snapshot


def write_map(root,**changes):
    radius=1000/(2*math.pi)
    data={'track':'Track','layout':'Layout','length':1000,'corners':[{'name':'T9','apex':250}],
          'samples':{}}
    for side,r in [('left',radius-6),('right',radius+6)]:
        data['samples'][side]=[[i*2.5,r*math.cos(i*2.5/radius),r*math.sin(i*2.5/radius)] for i in range(401)]
    data.update(changes)
    path=map_path(root,'Track','Layout');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data),encoding='utf-8')
    return path


def frame(t,*,slow=True,wider=True,bad_after=3):
    start=bad_after*20
    if t<start or not slow:
        lap=int(t//20);phase=t-lap*20;d=phase*50;speed=50
    else:
        lap=bad_after+int((t-start)//20.5);phase=t-start-(lap-bad_after)*20.5
        if phase<4:d=phase*50;speed=50
        elif phase<6.5:d=200+(phase-4)*40;speed=40
        else:d=300+(phase-6.5)*50;speed=50
    gap=4.5 if wider and lap>=bad_after else 1.5
    radius=1000/(2*math.pi);r=radius-6+gap;angle=d/radius
    car=Car(0,'Player','GT3','GT3',1,lap,d,speed,0,2,False,0,r*math.cos(angle),r*math.sin(angle))
    local={'speed':speed,'throttle':1. if not 180<d<350 else .3,'brake':0.,
           'steering':.01 if not 180<d<350 else .2,'rain_density':0.,'crash_state':0,
           'yellow_flag_state':0,'local_lap_invalid':False}
    return Tick(t,'test','practice','Track','Layout',1000,2,0,(car,),local)


def run(root,*,end=114,cached=False,transform=lambda f:f,**kwargs):
    engine=CoachEngine('Player',Scheduler(voice_duration=(lambda _:None) if cached else None),apex_store=ApexMapStore(root))
    calls=[]
    for i in range(int(end*10)+1):
        tick=transform(frame(i*.1,**kwargs));call=engine.feed(tick,radio_busy=False)
        if call:
            calls.append(call);engine.radio.acknowledge(call,engine.context,accepted=True,simulated=True)
    return engine,calls


def test_two_earlier_reference_intervals_and_repeated_wider_slower_passes_create_apex_call(tmp_path):
    write_map(tmp_path);engine,calls=run(tmp_path)
    assert len(calls)==1 and calls[0].message.spec.code=='C-10'
    call=calls[0]
    assert call.text=="You're missing the apex at turn nine."
    evidence=call.message.evidence.values
    assert evidence['wider_by_m']>2.8 and evidence['causal_time_loss_attributed_to_line'] is False
    assert max(r['end_t'] for r in evidence['reference_intervals'])<=min(r['start_t'] for r in evidence['recent'])
    assert all(r['slower_by_s']>.3 for r in evidence['recent'])
    assert call.message.evidence.pattern_laps==(3,4,5)
    assert engine.status()['apex']['supported_corners']==['T9']


def test_no_call_before_five_completed_full_intervals_or_without_both_deficits(tmp_path):
    write_map(tmp_path)
    for end,slow,wider in [(110,True,True),(114,False,True),(114,True,False)]:
        engine,calls=run(tmp_path,end=end,slow=slow,wider=wider)
        assert not calls
        assert engine.status()['diagnostics'].get('confirmed_apex_patterns',0)==0


def test_two_of_three_recent_passes_are_enough_when_latest_pass_is_a_miss(tmp_path):
    write_map(tmp_path)
    def one_good(tick):
        car=tick.cars[0]
        if car.laps==3:
            ratio=(1000/(2*math.pi)-6+1.5)/(1000/(2*math.pi)-6+4.5)
            tick=replace(tick,cars=(replace(car,x=car.x*ratio,z=car.z*ratio),))
        return tick
    _,calls=run(tmp_path,transform=one_good)
    assert len(calls)==1 and calls[0].message.evidence.pattern_laps==(4,5)


def test_reference_uses_fastest_earlier_intervals_with_valid_corner_measurements(tmp_path):
    write_map(tmp_path)
    def missing_first_measurements(tick):
        car=tick.cars[0]
        if car.laps in (1,2) and abs(car.distance-250)<=15:
            tick=replace(tick,cars=(replace(car,x=0,z=0),))
        return tick
    _,calls=run(tmp_path,end=154,bad_after=5,transform=missing_first_measurements)
    assert len(calls)==1
    assert [r['lap'] for r in calls[0].message.evidence.values['reference_intervals']]==[3,4]


@pytest.mark.parametrize('fault',['map_missing','layout','length','modelled','one_side','malformed'])
def test_wrong_unknown_or_inferred_maps_never_substitute_for_mapped_edges(tmp_path,fault):
    path=write_map(tmp_path)
    if fault=='map_missing':path.unlink()
    elif fault=='layout':write_map(tmp_path,layout='Different layout')
    elif fault=='length':write_map(tmp_path,length=1020)
    elif fault=='modelled':write_map(tmp_path,samples={},width=12)
    elif fault=='one_side':
        data=json.loads(path.read_text());data['samples'].pop('right');path.write_text(json.dumps(data))
    elif fault=='malformed':path.write_text('[]')
    engine,calls=run(tmp_path)
    assert not calls and not engine.status()['apex']['supported_corners']
    assert engine.status()['apex']['map_reason']!='mapped'


@pytest.mark.parametrize('fault',['invalid','crash','yellow','flag','weather','position','traffic','unknown_traffic','spectator','paused','race'])
def test_ineligible_laps_or_driver_state_never_teach_an_apex_pattern(tmp_path,fault):
    write_map(tmp_path)
    def change(tick):
        car=tick.cars[0];local=dict(tick.local);cars=tick.cars
        if fault=='invalid':car=replace(car,invalid=True)
        elif fault=='crash':local['crash_state']=3
        elif fault=='yellow':local['yellow_flag_state']=1
        elif fault=='flag':car=replace(car,flag_colour=2)
        elif fault=='weather':local.pop('rain_density')
        elif fault=='position':car=replace(car,x=None)
        if fault in ('traffic','unknown_traffic'):
            other=replace(car,slot=1,name='Rival',distance=(car.distance+50)%1000 if fault=='traffic' else None)
            cars=(car,other)
        else:cars=(car,)
        return replace(tick,cars=cars,local=local,viewed_slot=1 if fault=='spectator' else 0,
                       game_state=3 if fault=='paused' else 2,session='race' if fault=='race' else 'practice')
    engine,calls=run(tmp_path,transform=change)
    assert not calls and engine.status()['diagnostics'].get('confirmed_apex_patterns',0)==0


def test_current_danger_or_map_change_cancels_a_waiting_pattern(tmp_path):
    path=write_map(tmp_path);engine=CoachEngine('Player',apex_store=ApexMapStore(tmp_path))
    for i in range(1121):engine.feed(frame(i*.1),radio_busy=True)
    assert any(m.spec.code=='C-10' for m in engine.radio.pending.values())
    tick=frame(112.1)
    engine.feed(replace(tick,local={**tick.local,'crash_state':3}),radio_busy=False)
    assert not engine.radio.pending
    assert any(e.get('code')=='C-10' and e.get('reason')=='condition_changed' for e in engine.radio.log.events)
    # The authoring map is a disposable fixture. Changed geometry resets references.
    write_map(tmp_path,corners=[{'name':'Other','apex':250}])
    engine.feed(frame(112.2),radio_busy=False)
    assert engine.status()['apex']['clean_intervals_completed']==0


def test_missing_exact_voice_clip_holds_instead_of_tts(tmp_path):
    write_map(tmp_path);engine,calls=run(tmp_path,cached=True)
    assert not calls and engine.status()['diagnostics']['confirmed_apex_patterns']==1
    assert any(e['state']=='held' and e.get('reason')=='voice_clip_missing' for e in engine.radio.log.events)


def test_selected_apex_call_is_revalidated_after_map_edit_before_audio_fetch(tmp_path):
    write_map(tmp_path);engine=CoachEngine('Player',apex_store=ApexMapStore(tmp_path));delivery=None
    for i in range(1141):
        delivery=engine.feed(frame(i*.1),radio_busy=False)
        if delivery:break
    assert delivery and delivery.message.spec.code=='C-10'
    write_map(tmp_path,corners=[{'name':'T9','apex':255}])
    engine.feed(frame(engine.context.t+.1),radio_busy=True)
    assert engine.radio.delivery_reason(delivery,engine.context) is not None


def test_map_snapshot_is_frozen_for_replay_and_live_detects_edits(tmp_path):
    live=ApexMapStore(tmp_path);frozen=ApexMapStore(tmp_path,frozen=True)
    assert live.load('Track','Layout',1000) is None and frozen.load('Track','Layout',1000) is None
    write_map(tmp_path)
    assert live.load('Track','Layout',1000) is not None
    assert frozen.load('Track','Layout',1000) is None


def test_world_coordinates_use_current_exact_driver_in_both_adapters():
    snap=snapshot();snap.mParticipantInfo[0].mWorldPosition[0]=123;snap.mParticipantInfo[0].mWorldPosition[2]=456
    assert from_snapshot(snap,1,'test').cars[0].x==123
    row={'slot':0,'name':'Player','x':123,'z':456}
    assert from_recorded({'track_length':1000},[row],{'t':1},'test',1).cars[0].z==456


def write_apex(root):
    write_map(root)
    recording=Path(root)/'recordings'/'synthetic-apex'
    write_recording(recording,[frame(i*.1) for i in range(1141)])
    meta=json.loads((recording/'session.json').read_text());meta['session_type']='practice'
    (recording/'session.json').write_text(json.dumps(meta))
    return recording


def test_replay_speed_parity_and_map_recording_hashes_are_preserved(tmp_path,monkeypatch):
    recording=write_apex(tmp_path);path=map_path(tmp_path,'Track','Layout');before=hashlib.sha256(path.read_bytes()).hexdigest()
    now=[0.]
    monkeypatch.setattr('ams2season.coach.replay.time.monotonic',lambda:now[0])
    monkeypatch.setattr('ams2season.coach.replay.time.sleep',lambda seconds:now.__setitem__(0,now[0]+seconds))
    reports=[run_replay(recording,tmp_path,speed=speed) for speed in (1,20)]
    events=[[json.loads(s) for s in (Path(r['directory'])/'radio.jsonl').read_text().splitlines()] for r in reports]
    assert events[0]==events[1] and all(r['inputs_unchanged'] for r in reports)
    assert all(r['counts']['would_say']==1 for r in reports)
    assert any(row['file']==str(path) for row in reports[0]['inputs'])
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before


def test_authoring_map_change_during_replay_invalidates_verification(tmp_path):
    recording=write_apex(tmp_path)
    def edited(_):write_map(tmp_path,corners=[{'name':'Different','apex':250}])
    with pytest.raises(ValueError,match='recording changed'):
        run_replay(recording,tmp_path,progress=edited)
