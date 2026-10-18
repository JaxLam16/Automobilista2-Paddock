"""Early brake inputs require past clean references plus speed and section evidence."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ams2season.coach.braking import BrakingWatch
from ams2season.coach.engine import CoachEngine
from ams2season.coach.radio import Scheduler
from ams2season.coach.replay import run_replay
from test_coach_corner_speed import frame as speed_frame
from test_coach_replay import write_recording


def frame(t,*,early=True,lower=True,slower=True):
    tick=speed_frame(t,lower=lower,slower=slower);car=tick.cars[0]
    onset=160 if early and car.laps>=3 else 185
    brake=.7 if onset<=car.distance<225 else 0.
    return replace(tick,local={**tick.local,'brake':brake,'local_sample_age_s':0.})


def run(*,end=116,cached=False,transform=lambda f:f,**kwargs):
    engine=CoachEngine('Player',Scheduler(voice_duration=(lambda _:None) if cached else None));calls=[]
    for i in range(int(end*10)+1):
        call=engine.feed(transform(frame(i*.1,**kwargs)),radio_busy=False)
        if call:calls.append(call);engine.radio.acknowledge(call,engine.context,accepted=True,simulated=True)
    return engine,calls


def test_repeated_earlier_brake_input_is_factual_with_earlier_references_only():
    engine,calls=run();brake=[c for c in calls if c.message.spec.code=='C-05']
    assert len(brake)==1
    call=brake[0];value=call.message.evidence.values
    assert 'earlier at the bend near' in call.text
    assert value['earlier_by_m']>=20 and value['earlier_at_least_m']>=8 and value['entry_down_kph']>=4
    assert value['cause_attributed'] is value['later_braking_recommended'] is value['thermal_compensation'] is False
    assert all(r['end_t']<value['recent'][0]['start_t'] for r in value['reference_sections'])
    assert call.message.evidence.pattern_laps==(3,4,5)
    assert not any(c.message.spec.code=='C-09' for c in calls)
    assert engine.status()['braking']['comparison_reason']=='confirmed_pattern'


@pytest.mark.parametrize('kwargs',[{'end':110},{'early':False},{'lower':False},{'slower':False}])
def test_no_premature_or_single_channel_early_brake_diagnosis(kwargs):
    engine,calls=run(**kwargs)
    assert not any(c.message.spec.code=='C-05' for c in calls)
    assert not engine.diagnostics.get('confirmed_early_brake_patterns')


@pytest.mark.parametrize('fault',['brake','negative','range','tiny','brief','double','drag','invalid','traffic','weather','pause','race','gap','unaligned','alignment_unknown'])
def test_bad_ambiguous_or_unsafe_inputs_do_not_become_braking_advice(fault):
    def change(tick):
        car=tick.cars[0];local=dict(tick.local)
        if fault=='brake':local.pop('brake')
        elif fault=='negative':local['brake']=-1
        elif fault=='range':local['brake']=2
        elif fault=='tiny':local['brake']*=.1
        elif fault=='brief':local['brake']=.7 if 180<car.distance<183 else 0.
        elif fault=='double' and 90<car.distance<115:local['brake']=.7
        elif fault=='drag':local['brake']=max(.03,local['brake'])
        elif fault=='invalid':car=replace(car,invalid=True)
        elif fault=='weather':local.pop('rain_density')
        elif fault=='unaligned':local['local_sample_age_s']=.02
        elif fault=='alignment_unknown':local.pop('local_sample_age_s')
        elif fault=='gap' and tick.t%1<.5:return None
        cars=(car,replace(car,slot=1,name='Other',distance=(car.distance+30)%1000)) if fault=='traffic' else (car,)
        return replace(tick,cars=cars,local=local,game_state=3 if fault=='pause' else 2,
                       session='race' if fault=='race' else 'practice')
    engine=CoachEngine('Player');calls=[]
    for i in range(1161):
        tick=change(frame(i*.1))
        if tick is None:continue
        call=engine.feed(tick,radio_busy=False)
        if call:calls.append(call);engine.radio.acknowledge(call,engine.context,accepted=True,simulated=True)
    assert not any(c.message.spec.code=='C-05' for c in calls)
    assert not engine.diagnostics.get('confirmed_early_brake_patterns')


def test_missing_clip_withholds_early_brake_wording_and_reports_it():
    engine,calls=run(cached=True)
    assert not calls and engine.diagnostics['confirmed_early_brake_patterns']==1
    assert any(e.get('code')=='C-05' and e.get('reason')=='voice_clip_missing' for e in engine.radio.log.events)


def test_pending_brake_evidence_cancelled_when_brake_channel_disappears():
    engine=CoachEngine('Player')
    for i in range(1141):engine.feed(frame(i*.1),radio_busy=True)
    assert any(m.spec.code=='C-05' for m in engine.radio.pending.values())
    tick=frame(114.1);local=dict(tick.local);local.pop('brake')
    engine.feed(replace(tick,local=local),radio_busy=False)
    assert not any(m.spec.code=='C-05' for m in engine.radio.pending.values())


def test_early_brake_reference_disagreement_and_different_approach_are_withheld():
    for fault in ('reference','approach','latest'):
        def change(tick):
            car=tick.cars[0];local=dict(tick.local)
            if fault=='reference' and car.laps==2:local['brake']=.7 if 165<car.distance<225 else 0.
            if fault=='approach' and car.laps>=3 and car.distance<100:local['speed']=40.
            if fault=='latest' and car.laps==5:local['brake']=.7 if 185<car.distance<225 else 0.
            return replace(tick,local=local)
        engine,calls=run(transform=change)
        assert not any(c.message.spec.code=='C-05' for c in calls),fault


def test_two_of_three_with_latest_counts_but_sample_uncertainty_and_late_second_application_do_not():
    def skip_middle(tick):
        car=tick.cars[0]
        if car.laps==4:return replace(tick,local={**tick.local,'brake':.7 if 185<=car.distance<225 else 0.})
        return tick
    engine,calls=run(transform=skip_middle)
    brake=[c for c in calls if c.message.spec.code=='C-05']
    assert len(brake)==1 and brake[0].message.evidence.pattern_laps==(3,5)
    for fault in ('uncertain','late_second'):
        def change(tick):
            car=tick.cars[0];local=dict(tick.local)
            if fault=='uncertain' and car.laps>=3:local['brake']=.7 if 176<=car.distance<225 else 0.
            if fault=='late_second' and 280<=car.distance<305:local['brake']=.7
            return replace(tick,local=local)
        engine,calls=run(transform=change)
        assert not any(c.message.spec.code=='C-05' for c in calls),fault


def write_braking(root):
    recording=Path(root)/'recordings'/'synthetic-braking'
    meta=write_recording(recording,[frame(i*.1) for i in range(1161)])
    meta['session_type']='practice';(recording/'session.json').write_text(json.dumps(meta))
    return recording


def test_brake_replay_has_past_only_event_parity_and_keeps_originals(tmp_path,monkeypatch):
    recording=write_braking(tmp_path);now=[0.]
    monkeypatch.setattr('ams2season.coach.replay.time.monotonic',lambda:now[0])
    monkeypatch.setattr('ams2season.coach.replay.time.sleep',lambda s:now.__setitem__(0,now[0]+s))
    reports=[run_replay(recording,tmp_path,speed=speed) for speed in (1,20)]
    events=[[json.loads(s) for s in (Path(r['directory'])/'radio.jsonl').read_text().splitlines()] for r in reports]
    assert events[0]==events[1] and all(r['inputs_unchanged'] for r in reports)
    assert all(r['counts']['would_say']==1 for r in reports)
    assert any(e.get('code')=='C-05' and e['state']=='would_say' for e in events[0])
    cached=run_replay(recording,tmp_path,voice_durations={})
    assert cached['explanation']['code']=='calls_withheld' and 'Earlier-brake-input' in cached['explanation']['text']


def test_replay_asof_pedals_are_fresh_but_cannot_be_used_for_precision_brake_markers(tmp_path):
    import pyarrow.parquet as pq
    import pyarrow as pa
    recording=write_braking(tmp_path);path=recording/'local.parquet'
    raw=pq.read_table(path).to_pylist()
    for row in raw:row['t']-=.01
    pq.write_table(pa.Table.from_pylist(raw),path)  # Generated fixture only.
    report=run_replay(recording,tmp_path)
    assert report['engine']['braking']['diagnostics']['unaligned_pedal_samples']>1000
    assert not report['engine']['diagnostics'].get('confirmed_early_brake_patterns')
    assert report['inputs_unchanged']
