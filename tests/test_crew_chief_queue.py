"""Original queue decisions plus asynchronous silent playback receipts."""
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from ams2season.coach.crew_core import Core, RADIO_COMMANDS, command_for
from ams2season.coach.crew_mapper import DEFAULTS
from ams2season.coach.crew_spotter import ASSETS
from test_crew_chief_conditions import weather_snapshot
from test_crew_chief_shared_engine import native_map

NATIVE=pytest.mark.skipif(sys.platform!='win32',reason='Original .NET queue host')


@pytest.fixture
def core(tmp_path,request):
    host=Core(root=tmp_path)
    host.settings=dict(DEFAULTS,__paddock_number_config=host.settings['__paddock_number_config'],__paddock_queue_test='True')
    host.settings.update(getattr(request,'param',{}))
    host.start();assert host.ready.wait(10),host.error
    native_map(host,weather_snapshot())
    try:yield host
    finally:host.close()


def probe(core,*actions,ack=()):
    result=core._request({'op':'queue_test','actions':actions,'ack':list(ack)})
    assert result and not result.get('error'),result or core.error
    return result


def enqueue(name,**kw):
    return dict(action='enqueue',name=name,folder='engine_monitor/all_clear',**kw)


def test_original_queue_methods_and_pearls_are_pinned_verbatim():
    root=Path(__file__).resolve().parents[1]
    receipt=json.loads((ASSETS/'queue_sources.json').read_text())
    # Source-body comparisons, not a second implementation of the decisions.
    def block(text,marker):
        start=text.index(marker);end=text.index('{',start)+1;depth=1
        while depth:
            depth+=(text[end]=='{')-(text[end]=='}');end+=1
        return text[start:end]
    count=0
    for name,item in receipt.items():
        target=(ASSETS/name).read_text(encoding='utf-8-sig')
        assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()==item['sha256']
        original=(root/item['original']).read_text(encoding='utf-8-sig')
        for marker in item.get('methods',()):
            assert block(original,marker)==block(target,marker)
            count+=1
        if item['transformation']=='none':assert original==target
    assert count==29


@pytest.mark.parametrize('command,phrases',list(RADIO_COMMANDS.items()))
def test_original_installed_radio_phrases_are_recognised(command,phrases):
    for phrase in phrases:assert command_for(phrase.upper()+'?')==command


@NATIVE
def test_native_queue_test_facade_is_disabled_in_production_settings(tmp_path):
    host=Core(root=tmp_path)
    try:
        host.start();assert host.ready.wait(10),host.error
        native_map(host,weather_snapshot())
        result=host._request({'op':'queue_test','actions':[]})
        assert 'disabled' in result['error']
    finally:host.close()


@NATIVE
def test_original_priorities_fifo_first_duplicate_wins_until_playback_receipt(core):
    result=probe(core,enqueue('low',priority=1),enqueue('first',priority=7),enqueue('second',priority=7),enqueue('first',priority=20))
    assert [c['folder'] for c in result['calls']]==['COMPOUND_first','COMPOUND_second','COMPOUND_low']
    assert result['queue']['regular']==3 and result['queue']['awaiting_receipt']==3
    assert result['calls'][0]['priority']==7 and result['calls'][0]['sound_type']=='REGULAR_MESSAGE'
    assert probe(core,enqueue('first',priority=20))['calls']==[]
    assert probe(core)['calls']==[]  # exported once, still waiting for actual sink receipt
    ids=[c['id'] for c in result['calls']]
    result=probe(core,ack=[{'id':id,'outcome':'finished'} for id in ids])
    assert result['valid']==[] and result['queue']['regular']==0
    # The original enqueue gate opens again only after the old item left the queue.
    result=probe(core,enqueue('first',priority=20))
    native_map(core,weather_snapshot(),.25)
    result=probe(core)
    # Depending on the original 200ms wakeup, export occurred in map or probe.
    assert result['queue']['regular']==1


@NATIVE
def test_original_delayed_high_priority_blocks_lower_when_hard_parts_mode_disabled(core):
    result=probe(core,enqueue('delayed',priority=10,delay=2),enqueue('low',priority=1))
    assert result['calls']==[] and result['queue']['regular_names']==['COMPOUND_delayed']
    result=native_map(core,weather_snapshot(),2.25)['events']
    assert [c['folder'] for c in result['calls']]==['COMPOUND_delayed']
    assert result['calls'][0]['delay_s']==0 and 27<result['calls'][0]['expires_s']<28


@NATIVE
@pytest.mark.parametrize('core',[{'enable_delayed_messages_on_hardparts':'True'}],indirect=True)
def test_original_hard_parts_mode_does_not_apply_delayed_priority_block(core):
    result=probe(core,enqueue('delayed',priority=10,delay=2),enqueue('low',priority=1))
    assert [c['folder'] for c in result['calls']]==['COMPOUND_low']
    assert result['queue']['regular']==2


@NATIVE
def test_original_trigger_stays_queued_until_true_and_max_queue_length_discards(core):
    result=probe(core,{'action':'trigger','value':False},enqueue('conditional',trigger=True),enqueue('small_queue',max_queue=1,priority=10))
    assert result['calls']==[] and result['queue']['regular_names']==['COMPOUND_conditional']
    probe(core,{'action':'trigger','value':True})
    result=native_map(core,weather_snapshot(),.25)['events']
    assert [c['folder'] for c in result['calls']]==['COMPOUND_conditional']


@NATIVE
def test_original_immediate_queue_normalises_auto_and_blocks_regular(core):
    result=probe(core,enqueue('regular'),enqueue('reply',immediate=True))
    assert len(result['calls'])==1 and result['calls'][0]['folder']=='COMPOUND_reply'
    assert result['calls'][0]['sound_type']=='VOICE_COMMAND_RESPONSE'
    native_map(core,weather_snapshot(),.25)
    assert probe(core)['queue']['regular']==1
    result=probe(core,ack=[result['calls'][0]['id']])
    # Await the source wake interval, rather than letting metadata export simulate completion.
    result=native_map(core,weather_snapshot(),.5)['events']
    assert result['calls'][0]['folder']=='COMPOUND_regular'


@NATIVE
def test_original_five_second_immediate_repeat_suppression(core):
    result=probe(core,enqueue('same',immediate=True))
    result=probe(core,enqueue('same'),ack=[result['calls'][0]['id']])
    native_map(core,weather_snapshot(),.25)
    assert probe(core)['queue']['regular']==0


@NATIVE
@pytest.mark.parametrize('core',[{'speak_only_when_spoken_to':'True'}],indirect=True)
def test_original_speak_only_when_spoken_to_allows_only_replies_and_spotter(core):
    result=probe(core,enqueue('auto'),enqueue('important',immediate=True,type='IMPORTANT_MESSAGE'),enqueue('reply',immediate=True))
    assert [c['folder'] for c in result['calls']]==['COMPOUND_reply']
    assert result['queue']['regular']==0 and result['queue']['immediate']==1


@NATIVE
@pytest.mark.parametrize('core',[{'priortise_messages_depending_on_situation':'True'}],indirect=True)
def test_original_auto_verbosity_uses_mapped_traffic_and_priority_threshold(core):
    result=probe(core,{'action':'advance','seconds':2},{'action':'gaps','front':.6,'behind':.8},enqueue('low',priority=5),enqueue('safety',priority=10))
    assert result['queue']['verbosity']=='LOW'
    assert [c['folder'] for c in result['calls']]==['COMPOUND_safety']


@NATIVE
@pytest.mark.parametrize('core',[{'allow_important_messages_even_when_silenced':'False'}],indirect=True)
def test_original_keep_quiet_discards_regular_and_important_but_keeps_reply(core):
    result=probe(core,{'action':'quiet'},enqueue('regular'),enqueue('important',immediate=True,type='IMPORTANT_MESSAGE'),enqueue('reply',immediate=True))
    assert result['queue']['keep_quiet']
    assert [c['folder'] for c in result['calls']]==['acknowledge/keepQuietEnabled','COMPOUND_reply']
    result=probe(core,ack=[c['id'] for c in result['calls']])
    native_map(core,weather_snapshot(),.25)
    assert probe(core)['queue']['regular']==0


@NATIVE
@pytest.mark.parametrize('core',[{'allow_important_messages_even_when_silenced':'True'}],indirect=True)
def test_original_keep_quiet_can_allow_important_immediate_messages(core):
    result=probe(core,{'action':'quiet'},enqueue('important',immediate=True,type='IMPORTANT_MESSAGE'))
    assert len(result['calls'])==2 and result['queue']['keep_quiet']


@NATIVE
@pytest.mark.parametrize('core',[{'enable_delayed_messages_on_hardparts':'True'}],indirect=True)
def test_original_mapped_hard_part_holds_regular_until_next_clear_location(core):
    result=probe(core,{'action':'hard_part','start':900,'end':1200},enqueue('wait'))
    assert result['calls']==[] and result['queue']['regular']==1
    raw=weather_snapshot();raw.mParticipantInfo[0].mCurrentLapDistance=1400
    result=native_map(core,raw,.3)['events']
    assert result['calls'][0]['folder']=='COMPOUND_wait'


@NATIVE
def test_original_expiry_withdraws_exported_unplayed_item_and_purge_retains_markers(core):
    result=probe(core,enqueue('expires',expiry=1))
    assert result['valid']
    result=native_map(core,weather_snapshot(),2)['events']
    assert not result['valid'] and result['queue']['regular']==0
    probe(core,enqueue('SESSION_END'),enqueue('retain_on_session_end'),enqueue('normal'))
    result=probe(core,{'action':'purge'})
    assert set(result['queue']['regular_names'])=={'COMPOUND_SESSION_END','COMPOUND_retain_on_session_end'}


@NATIVE
def test_delayed_immediate_and_standby_use_sample_clock_without_sleeping(core):
    result=probe(core,{'action':'stand_by','folder':'engine_monitor/all_clear','min':5,'max':6})
    assert [c['folder'] for c in result['calls']]==['acknowledge/stand_by']
    assert result['queue']['paused'] and result['queue']['delayed']==1
    probe(core,ack=[result['calls'][0]['id']])
    result=native_map(core,weather_snapshot(),4.99)['events']
    assert not result['calls'] and result['queue']['delayed']==1
    result=native_map(core,weather_snapshot(),5)['events']
    assert result['calls'][0]['fragments']==['engine_monitor/all_clear']
    assert result['calls'][0]['sound_type']=='VOICE_COMMAND_RESPONSE' and not result['queue']['paused']


@NATIVE
def test_repeat_requires_actual_playback_receipt_not_just_an_export(core):
    result=probe(core,enqueue('heard',immediate=True))
    first=result['calls'][0]
    assert probe(core,{'action':'repeat'})['calls']==[]
    result=probe(core,{'action':'repeat'},ack=[{'id':first['id'],'outcome':'dropped'}])
    assert result['calls']==[]
    result=probe(core,enqueue('heard_again',immediate=True))
    result=probe(core,{'action':'repeat'},ack=[{'id':result['calls'][0]['id'],'outcome':'finished'}])
    repeated=result['calls'][0]
    assert repeated['folder']=='REPEAT_COMPOUND_heard_again' and repeated['fragments']==first['fragments']
    assert repeated['sound_type']=='VOICE_COMMAND_RESPONSE'


@NATIVE
def test_original_repeat_keeps_call_that_started_then_was_interrupted(core):
    result=probe(core,enqueue('interrupted',immediate=True))
    first=result['calls'][0]
    result=probe(core,{'action':'repeat'},ack=[{'id':first['id'],'outcome':'playing'}])
    assert first['id'] in result['valid']
    repeated=result['calls'][0]
    assert repeated['id']!=first['id'] and repeated['folder']=='REPEAT_COMPOUND_interrupted'
    assert repeated['fragments']==first['fragments']
    # A final drop releases only the interrupted original, not its new repeat.
    result=probe(core,ack=[{'id':first['id'],'outcome':'dropped'}])
    assert result['valid']==[repeated['id']]


@NATIVE
@pytest.mark.parametrize('setting,expected', [('NEVER',False),('SPOTTER_MESSAGES',False),('CRITICAL_MESSAGES',False),('IMPORTANT_MESSAGES',True)])
def test_original_interrupt_setting_threshold_for_important_message(tmp_path,setting,expected):
    host=Core(root=tmp_path)
    host.settings.update(DEFAULTS,__paddock_queue_test='True',interrupt_setting_listprop=setting)
    try:
        host.start();assert host.ready.wait(10),host.error
        native_map(host,weather_snapshot())
        result=probe(host,enqueue('important',immediate=True,type='IMPORTANT_MESSAGE'))
        assert result['calls'][0]['interrupts_regular'] is expected
    finally:host.close()


@NATIVE
def test_waiting_for_push_to_talk_keeps_original_reply_queued_until_release(core):
    core.waiting_for_speech=True
    native_map(core,weather_snapshot(),.25)
    result=probe(core,enqueue('reply',immediate=True))
    assert result['calls']==[] and result['queue']['immediate']==1
    core.waiting_for_speech=False
    result=native_map(core,weather_snapshot(),.5)['events']
    assert result['calls'][0]['folder']=='COMPOUND_reply'


@NATIVE
@pytest.mark.parametrize('core',[{'__paddock_personalised_folders':'["COMPOUND_personal"]'}],indirect=True)
def test_original_first_personalised_message_moves_to_front_before_higher_priority(core):
    result=probe(core,enqueue('high',priority=10),enqueue('personal',priority=1))
    assert [c['folder'] for c in result['calls']]==['COMPOUND_personal','COMPOUND_high']
    assert result['queue']['play_order']==[c['id'] for c in result['calls']]


def service_fixture(tmp_path):
    from ams2season.app import App
    app=App(tmp_path)
    service=app.coach
    ctx=SimpleNamespace(t=10,session_id='one',active=True,pit_radio=False,lap=1,distance=20)
    service.engine=SimpleNamespace(context=ctx,radio=SimpleNamespace(log=SimpleNamespace(record=lambda *a,**k:None)))
    service._local_valid=lambda *a,**k:True
    service.cc_voice.render=lambda call,*a,**k:(call['folder'],b'wav','voice_pack')
    played=[]
    service.local_radio=SimpleNamespace(busy=False,current=None,
        say=lambda key,*a,**kw:played.append(('say',key)) or True,
        urgent=lambda key,*a,**kw:played.append(('urgent',key)) or True,close=lambda:None)
    return service,played


def service_call(id,priority=5,**kw):
    return dict(folder='test/'+id,fragments=[],id=id,native_id='core:'+id,queue_managed=True,
        expires_s=10,delay_s=0,priority=priority,immediate=False,sound_type='REGULAR_MESSAGE',**kw)


def test_service_keeps_native_personalisation_order_and_logs_receipts(tmp_path):
    service,played=service_fixture(tmp_path)
    try:
        service.core.play_order=['q1','q2'];service.core.valid_ids={'q1','q2'}
        service._queue_baseline([service_call('q1',priority=1),service_call('q2',priority=10)])
        assert service._deliver_baseline() and played==[('say','cc-events:core:q1')]
        service._ack_baseline('core:q1','dropped')
        assert service.core.acknowledged==[{'id':'q1','outcome':'dropped'}]
    finally:
        service.engine=None;service.close()


@pytest.mark.parametrize('kind,setting,expected',[
    ('REGULAR_MESSAGE',False,False),('REGULAR_MESSAGE',True,True),
    ('VOICE_COMMAND_RESPONSE',True,False),('CRITICAL_MESSAGE',True,False),('SPOTTER',True,False)])
def test_service_only_interrupts_regular_speech_when_native_policy_allows(tmp_path,kind,setting,expected):
    service,played=service_fixture(tmp_path)
    try:
        service.core.play_order=['q1'];service.core.valid_ids={'q1'}
        service.local_radio.busy=True;service.local_radio.current='spot' if kind=='SPOTTER' else 'ordinary'
        service.baseline_inflight['ordinary']={'sound_type':kind}
        call=service_call('q1');call.update(immediate=True,sound_type='IMPORTANT_MESSAGE',interrupts_regular=setting)
        service._queue_baseline([call])
        assert service._deliver_baseline() is expected
        assert played==([('urgent','cc-events:core:q1')] if expected else [])
    finally:
        service.engine=None;service.close()


@pytest.mark.parametrize('allow,kind,immediate,expected',[
    (False,'REGULAR_MESSAGE',False,False),(False,'IMPORTANT_MESSAGE',True,False),
    (False,'VOICE_COMMAND_RESPONSE',True,True),(False,'SPOTTER',True,True),
    (True,'REGULAR_MESSAGE',False,False),(True,'IMPORTANT_MESSAGE',True,True)])
def test_keep_quiet_policy_also_applies_to_remaining_legacy_event_transport(tmp_path,allow,kind,immediate,expected):
    service,played=service_fixture(tmp_path)
    try:
        service.core.queue_status={'keep_quiet':True}
        service.core.settings['allow_important_messages_even_when_silenced']=str(allow)
        assert service._baseline_quiet_allowed({'sound_type':kind,'immediate':immediate}) is expected
    finally:
        service.engine=None;service.close()


def test_cancelled_audio_reports_drop_after_sink_returns_so_native_queue_can_release(tmp_path):
    import threading
    from ams2season.coach.speech import LocalRadio
    from ams2season.coach.voice import pcm_wav
    from test_coach_service import wait_until
    entered=threading.Event();release=threading.Event()
    def sink(data):entered.set();assert release.wait(5)
    voice=SimpleNamespace(get=lambda text:None)
    radio=LocalRadio(voice,sink=(sink,release.set),effect='off')
    try:
        radio.say('cc-events:core:q1','test',data=pcm_wav(b'\1\0'*2205))
        assert entered.wait(5)
        radio.cancel_all()
        wait_until(lambda:not radio.busy)
        events=radio.drain()
        assert any(e['event']=='dropped' and e['key']=='cc-events:core:q1' for e in events)
        assert not any(e['event']=='finished' for e in events)
    finally:release.set();radio.close()
