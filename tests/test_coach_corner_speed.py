"""Map-free speed comparisons learn only from earlier local clean telemetry."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ams2season.coach.engine import CoachEngine
from ams2season.coach.radio import Scheduler
from ams2season.coach.replay import run_replay
from ams2season.coach.model import Car,Tick
from test_coach_replay import write_recording


def frame(t,*,lower=True,slower=True,turning=True):
    normal=960/50+40/40;bad=960/50+40/30
    if t<3*normal or not slower:
        lap=int(t//normal);phase=t-lap*normal;minimum=40
    else:
        lap=3+int((t-3*normal)//bad);phase=t-3*normal-(lap-3)*bad;minimum=30
    if phase<230/50:d=phase*50;speed=50
    elif phase<230/50+40/minimum:d=230+(phase-230/50)*minimum;speed=minimum
    else:d=270+(phase-230/50-40/minimum)*50;speed=50
    reading=30 if lower and lap>=3 and 230<=d<=270 else 40 if 230<=d<=270 else 50
    if not lower:reading=40 if 230<=d<=270 else 50
    car=Car(0,'Player','GT3','GT3',1,lap,d,speed,0,2,False,0)
    local={'speed':reading,'steering':.2 if turning and 225<d<275 else .01,
           'throttle':.4 if 180<d<310 else 1.,'brake':0.,'rain_density':0.,
           'local_lap_invalid':False,'crash_state':0,'yellow_flag_state':0}
    return Tick(t,'test','practice','Track','Layout',1000,2,0,(car,),local)


def run(*,end=116,cached=False,transform=lambda f:f,**kwargs):
    engine=CoachEngine('Player',Scheduler(voice_duration=(lambda _:None) if cached else None));calls=[]
    for i in range(int(end*10)+1):
        tick=transform(frame(i*.1,**kwargs));call=engine.feed(tick,radio_busy=False)
        if call:calls.append(call);engine.radio.acknowledge(call,engine.context,accepted=True,simulated=True)
    return engine,calls


def test_map_free_repeated_lower_minimum_with_slower_section_generates_factual_call():
    engine,calls=run()
    assert len(calls)==1 and calls[0].message.spec.code=='C-09'
    assert 'the bend near' in calls[0].text and 'Minimum speed is down' in calls[0].text
    evidence=calls[0].message.evidence.values
    assert evidence['minimum_down_kph']>25 and evidence['cause_attributed'] is False
    assert all(r['end_t']<=evidence['recent'][0]['start_t'] for r in evidence['reference_sections'])
    assert calls[0].message.evidence.pattern_laps==(3,4,5)
    assert engine.status()['corner_speed']['learned_bends']


@pytest.mark.parametrize('kwargs',[{'end':110},{'lower':False},{'slower':False},{'turning':False}])
def test_no_premature_or_one_channel_only_diagnosis(kwargs):
    engine,calls=run(**kwargs)
    assert not calls and not engine.diagnostics.get('confirmed_corner_speed_patterns')


def test_bend_discovery_requires_steering_in_both_earlier_reference_intervals():
    def straight_second_reference(tick):
        if tick.cars[0].laps==2:tick=replace(tick,local={**tick.local,'steering':.01})
        return tick
    engine,calls=run(transform=straight_second_reference)
    assert not calls and not engine.diagnostics.get('confirmed_corner_speed_patterns')


@pytest.mark.parametrize('fault',['invalid','flag','incident','weather','steering','speed','traffic','pause','spectator','race'])
def test_invalid_unknown_busy_or_wrong_session_evidence_is_withheld(fault):
    def change(tick):
        car=tick.cars[0];local=dict(tick.local);cars=(car,)
        if fault=='invalid':car=replace(car,invalid=True)
        elif fault=='flag':car=replace(car,flag_colour=2)
        elif fault=='incident':local['crash_state']=3
        elif fault in ('weather','steering','speed'):local.pop({'weather':'rain_density'}.get(fault,fault))
        if fault=='traffic':cars=(car,replace(car,slot=1,name='Other',distance=(car.distance+30)%1000))
        else:cars=(car,)
        return replace(tick,cars=cars,local=local,game_state=3 if fault=='pause' else 2,
                       viewed_slot=1 if fault=='spectator' else 0,session='race' if fault=='race' else 'practice')
    engine,calls=run(transform=change)
    assert not calls and not engine.diagnostics.get('confirmed_corner_speed_patterns')


def test_missing_clip_stays_silent():
    engine,calls=run(cached=True)
    assert not calls and engine.diagnostics['confirmed_corner_speed_patterns']==1
    assert any(e.get('code')=='C-09' and e.get('reason')=='voice_clip_missing' for e in engine.radio.log.events)


def test_pending_speed_evidence_cancels_when_current_traffic_changes():
    engine=CoachEngine('Player')
    for i in range(1141):engine.feed(frame(i*.1),radio_busy=True)
    assert any(m.spec.code=='C-09' for m in engine.radio.pending.values())
    tick=frame(114.1);other=replace(tick.cars[0],slot=1,name='Other',distance=(tick.cars[0].distance+30)%1000)
    engine.feed(replace(tick,cars=(*tick.cars,other)),radio_busy=False)
    assert not engine.radio.pending


def write_speed(root):
    recording=Path(root)/'recordings'/'synthetic-corner-speed'
    meta=write_recording(recording,[frame(i*.1) for i in range(1161)])
    meta['session_type']='practice';(recording/'session.json').write_text(json.dumps(meta))
    return recording


def test_speed_replay_has_past_only_event_parity_and_preserves_sources(tmp_path,monkeypatch):
    recording=write_speed(tmp_path);now=[0.]
    monkeypatch.setattr('ams2season.coach.replay.time.monotonic',lambda:now[0])
    monkeypatch.setattr('ams2season.coach.replay.time.sleep',lambda seconds:now.__setitem__(0,now[0]+seconds))
    reports=[run_replay(recording,tmp_path,speed=speed) for speed in (1,20)]
    events=[[json.loads(s) for s in (Path(r['directory'])/'radio.jsonl').read_text().splitlines()] for r in reports]
    assert events[0]==events[1] and all(r['inputs_unchanged'] for r in reports)
    assert all(r['counts']['would_say']==1 for r in reports)
