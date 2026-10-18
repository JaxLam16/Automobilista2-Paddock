"""Related calls remain individually true; a bundle is one call, not free extra radio."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from ams2season.coach.audio import AudioTickets, SILENCE
from ams2season.coach.model import Evidence, Requirement
from ams2season.coach.radio import Scheduler, RadioLog
from ams2season.coach.engine import CoachEngine
from ams2season.coach.voice import VoiceCache
from test_coach_radio import context, message
from test_coach_voice import voice_batch
from test_coach_replay import tick, write_recording
from ams2season.coach.replay import run_replay
from test_coach_windows import learned


def pair(ctx):
    first=message(ctx,id='ahead',key='pit:a',bundle_key='pit_entries')
    second=message(ctx,id='behind',key='pit:b',bundle_key='pit_entries',
                   slots={'relation':'car behind','turn':'turn nine'},
                   requirements=(Requirement('pit:b',(1,2),'in'),),
                   evidence=Evidence('high',{'driver':'B','pit_mode':1}))
    return first,second


def ready_context(**changes):
    return context(facts={'pit:a':1,'pit:b':1},window_id='straight-1',**changes)


def test_related_facts_share_one_call_with_all_evidence_and_cooldowns(tmp_path):
    ctx=ready_context()
    radio=Scheduler(log=RadioLog(tmp_path/'radio.jsonl'))
    first,second=pair(ctx)
    radio.offer(first,ctx);radio.offer(second,ctx)
    selected=radio.select(ctx)
    assert len(selected.calls)==2 and selected.seconds<=6
    assert selected.text=='The car ahead is pitting. The car behind is pitting.'
    assert not radio.pending
    assert not radio.offer(replace(second,id='duplicate'),ctx)
    assert radio.log.events[-1]['reason']=='duplicate'
    assert radio.acknowledge(selected,ctx,accepted=True,simulated=True)
    assert radio.per_lap[(ctx.lap,2)]==1 and radio.log.counts['would_say']==1
    assert set(radio.last_by_key)=={'pit:a','pit:b'}
    event=radio.log.events[-1]
    assert event['bundle_ids']==['ahead','behind']
    assert event['evidence']['components'][1]['evidence']['values']['driver']=='B'
    assert len([e for e in map(json.loads,(tmp_path/'radio.jsonl').read_text().splitlines()) if e['state']=='would_say'])==1
    later=replace(ctx,t=ctx.t+5)
    assert not radio.offer(replace(second,id='again',created=later.t,expires=later.t+10),later)
    assert radio.log.events[-1]['reason']=='cooldown'


def test_unrelated_or_more_urgent_calls_are_not_added_to_a_bundle():
    ctx=ready_context();radio=Scheduler()
    first,second=pair(ctx)
    second=replace(second,bundle_key='different_rival_context')
    radio.offer(first,ctx);radio.offer(second,ctx)
    selected=radio.select(ctx)
    assert len(selected.calls)==1 and len(radio.pending)==1
    radio=Scheduler()
    urgent=replace(second,spec=replace(second.spec,urgency=1))
    radio.offer(first,ctx);radio.offer(urgent,ctx)
    selected=radio.select(ctx)
    assert selected.message.id=='behind' and len(selected.calls)==1


@pytest.mark.parametrize('counted_facts',[1,2])
def test_at_most_three_facts_including_facts_inside_a_component(counted_facts):
    ctx=ready_context();radio=Scheduler()
    base=message(ctx,bundle_key='group',requirements=())
    short=replace(base.spec,phrases=('{relation} pitting.','{relation} entering.','Pitting: {relation}.'))
    for i,relation in enumerate(('ahead','behind','leader','other')):
        spec=replace(short,fact_count=counted_facts if i==0 else 1)
        radio.offer(replace(base,id=str(i),key=str(i),spec=spec,slots={'relation':relation}),ctx)
    selected=radio.select(ctx)
    assert sum(p.message.spec.fact_count for p in selected.calls)==3
    assert len(selected.calls)==4-counted_facts
    assert len(radio.pending)==counted_facts


def test_bundle_does_not_outlive_its_shortest_fact_or_exceed_time_budget():
    ctx=ready_context();radio=Scheduler()
    first,second=pair(ctx)
    radio.offer(first,ctx);radio.offer(replace(second,expires=ctx.t+3),ctx)
    selected=radio.select(ctx)
    assert len(selected.calls)==1  # combined speech would finish after the other fact expires
    radio=Scheduler()
    for i,relation in enumerate(('car ahead','car behind','class leader')):
        radio.offer(replace(first,id=str(i),key=str(i),slots={'relation':relation}),ctx)
    selected=radio.select(ctx)
    assert len(selected.calls)==2 and selected.seconds<=6 and len(radio.pending)==1


def test_audio_bundling_uses_the_actual_duration_of_what_is_played(tmp_path):
    ctx=ready_context();first,second=pair(ctx)
    texts=[first.render(0),second.render(0)]
    directory,_=voice_batch(tmp_path,texts=texts)
    voice=VoiceCache(tmp_path)
    def prepare():
        radio=Scheduler(voice_duration=voice.duration)
        radio.offer(first,ctx);radio.offer(second,ctx)
        return radio,radio.select(ctx)
    _,joined=prepare()
    # Composed from the two cached sentences with a sentence pause: its real length, not an estimate.
    assert len(joined.calls)==2 and joined.seconds==pytest.approx(1.5+.32+1.5,abs=1e-4)
    assert voice.get(joined.text).seconds==joined.seconds
    manifest=json.loads((directory/'manifest.json').read_text())
    compound=texts[0]+' '+texts[1]
    manifest['clips'].append({**manifest['clips'][0],'id':'compound','text':compound})
    (directory/'manifest.json').write_text(json.dumps(manifest));voice.reload()
    radio,bundle=prepare()
    assert len(bundle.calls)==2 and bundle.seconds==1.5  # the full cached PCM, not summed estimates
    broker=AudioTickets(clock=lambda:0)
    ticket=broker.issue(bundle,voice.get(bundle.text),ctx)
    assert broker.claim(ticket.token,radio,ctx,age_s=0)==voice.get(compound).data
    assert radio.log.counts['audio_served']==1


def test_changed_secondary_fact_withholds_whole_audio_without_consuming_budget(tmp_path):
    ctx=ready_context();first,second=pair(ctx)
    compound=first.render(0)+' '+second.render(0)
    voice_batch(tmp_path,texts=[first.render(0),second.render(0),compound])
    voice=VoiceCache(tmp_path);radio=Scheduler(voice_duration=voice.duration)
    radio.offer(first,ctx);radio.offer(second,ctx)
    selected=radio.select(ctx);broker=AudioTickets(clock=lambda:0)
    ticket=broker.issue(selected,voice.get(selected.text),ctx)
    changed=replace(ctx,t=ctx.t+.1,facts={'pit:a':1,'pit:b':0})
    assert broker.claim(ticket.token,radio,changed,age_s=0)==SILENCE
    assert not radio.last_by_key and not radio.per_lap
    assert radio.log.events[-1]['bundle_ids']==['ahead','behind']
    assert radio.log.events[-1]['reason']=='condition_changed'


def test_observed_simultaneous_rival_stops_become_one_preview_call():
    engine=CoachEngine('Player');calls=[]
    for i in range(470):
        frame=tick(i*.1,pit=1 if i>=450 else 0)
        behind=replace(frame.cars[1],slot=2,name='Behind',position=3,
                       distance=(frame.cars[0].distance-250)%frame.length)
        frame=replace(frame,cars=frame.cars+(behind,))
        selected=engine.feed(frame,radio_busy=False)
        if selected:
            calls.append(selected)
            engine.radio.acknowledge(selected,engine.context,accepted=True,simulated=True)
    assert len(calls)==1 and len(calls[0].calls)==2
    assert calls[0].text=='The car ahead is pitting. The car behind is pitting.'
    assert engine.radio.log.counts['would_say']==1
    assert {p.message.evidence.values['driver'] for p in calls[0].calls}=={'Rival','Behind'}


def test_battle_allows_one_call_per_straight_even_if_battle_started_after_first_call():
    ctx=ready_context();radio=Scheduler()
    first,second=pair(ctx)
    radio.offer(replace(first,bundle_key=None),ctx)
    radio.offer(replace(second,bundle_key=None),ctx)
    selected=radio.select(ctx);radio.acknowledge(selected,ctx,accepted=True)
    later=replace(ctx,t=ctx.t+4,nearest_gap=.7)
    assert radio.select(later) is None
    assert radio.log.events[-1]['reason']=='battle_straight_budget'
    selected=radio.select(replace(later,t=later.t+.1,window_id='straight-2'))
    assert selected.message.id=='behind'
    radio.acknowledge(selected,replace(later,t=later.t+.1,window_id='straight-2'),accepted=True)
    assert radio.per_lap[(ctx.lap,2)]==2


def test_unknown_battle_window_cannot_authorize_a_second_call():
    ctx=ready_context(nearest_gap=.5);radio=Scheduler()
    radio.offer(message(ctx),ctx)
    assert radio.select(replace(ctx,window_id=None)) is None
    assert radio.log.events[-1]['reason']=='battle_window_unknown'


def test_window_identity_ignores_lap_counter_and_one_frame_shift_but_not_a_corner():
    windows=learned();ids=[]
    for i in range(401,565):
        frame=tick(i*.1)
        ids.append(windows.window_id(frame.cars[0].distance,frame.t))
        # Learned geometry, rather than this momentary lift, defines the span.
        if i==430:frame=replace(frame,local={**frame.local,'throttle':.6})
        windows.feed(frame,frame.cars[0])
    assert len(set(ids[:150]))==1 and ids[-1] is None
    # A straight that wraps the start line retains one ID through the crossing.
    windows=learned()
    for lap in windows.laps:
        for b in range(windows.n):lap[b]=(b<20 or b>=80,50)
    ids=[]
    for i in range(580,625):
        frame=tick(i*.1);car=frame.cars[0]
        ids.append(windows.window_id(car.distance,frame.t))
        windows.feed(frame,car)
    assert len(set(ids[:39]))==1


def test_learned_shift_dip_does_not_earn_a_second_call_on_the_same_straight():
    windows=learned()
    for lap in windows.laps:lap[40]=(False,50)
    ids=[]
    for i in range(401,550):
        frame=tick(i*.1)
        ids.append(windows.window_id(frame.cars[0].distance,frame.t))
        windows.feed(frame,frame.cars[0])
    assert None in ids  # the dip itself never authorizes a call
    assert len({x for x in ids if x is not None})==1


def test_bundled_recording_is_read_only_and_decisions_match_at_one_and_twenty_times(tmp_path,monkeypatch):
    frames=[]
    for i in range(470):
        frame=tick(i*.1,pit=1 if i>=450 else 0)
        behind=replace(frame.cars[1],slot=2,name='Behind',position=3,
                       distance=(frame.cars[0].distance-250)%frame.length)
        frames.append(replace(frame,cars=frame.cars+(behind,)))
    recording=tmp_path/'recording';write_recording(recording,frames)
    now=[0.]
    monkeypatch.setattr('ams2season.coach.replay.time.monotonic',lambda:now[0])
    monkeypatch.setattr('ams2season.coach.replay.time.sleep',lambda delay:now.__setitem__(0,now[0]+delay))
    reports=[run_replay(recording,tmp_path,speed=speed) for speed in (1,20)]
    events=[[json.loads(line) for line in (Path(r['directory'])/'radio.jsonl').read_text().splitlines()] for r in reports]
    assert events[0]==events[1]
    for report in reports:
        assert report['inputs_unchanged'] and report['counts']['would_say']==1
        assert report['explanation']['code']=='calls_generated'
    call=next(e for e in events[0] if e['state']=='would_say')
    assert len(call['bundle_ids'])==2 and len(call['evidence']['components'])==2
