"""Original damage event, real complete mapper and muted audio boundaries."""
import hashlib
import json
import queue
import re
import sys
import time
from types import SimpleNamespace

import pytest

from ams2season import shm as S
from ams2season.coach.crew_core import Core
from ams2season.coach.crew_damage import COMMANDS,FOLDERS,I_AM_OK,clearly_ok,command_for
from ams2season.coach.crew_mapper import DEFAULTS,snapshot_payload
from ams2season.coach.crew_spotter import ASSETS
from ams2season.coach.speech import WindowsListener
from ams2season.coach.telemetry import from_snapshot
from test_crew_chief_conditions import weather_snapshot
from test_crew_chief_mapper import TICKS

NATIVE=pytest.mark.skipif(sys.platform!='win32',reason='Original Framework damage event')

def raw_state():
    raw=weather_snapshot()
    for i in range(4):raw.mAirPressure[i]=200
    return raw

@pytest.fixture
def core(tmp_path,request):
    host=Core(root=tmp_path)
    numbers=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS,__paddock_number_config=numbers)
    host.settings.update(enable_delayed_responses='False',allow_rants='False')
    host.settings.update(getattr(request,'param',{}))
    host.damage_available=True
    host.start()
    assert host.ready.wait(10),host.error
    try:yield host
    finally:host.close()

def mapped(core,raw,t=0):
    result=core._request({'op':'map','raw':snapshot_payload(raw),'ticks':TICKS+round(t*10000000)})
    assert result and result.get('mapped') and not result.get('error'),result or core.error
    core.latest={'at':time.perf_counter()}
    core._events(result['events'])
    return result['events']

def acknowledge(core,calls):
    for c in calls:core.acknowledge(c.get('native_id','core:'+c['id']))

def through(core,raw,start,end):
    calls=[]
    for i in range(round(start*10),round(end*10)+1):
        result=mapped(core,raw,i/10)
        calls+=result['calls']
        acknowledge(core,result['calls'])
    return calls

def fragments(calls):return [f for c in calls for f in c['fragments']]

def test_source_only_has_the_recorded_clock_substitution_and_build_matches():
    receipt=json.loads((ASSETS/'core_sources.json').read_text())['DamageReporting.cs']
    original=(ASSETS.parents[2]/receipt['original']).read_bytes()
    source=(ASSETS/'DamageReporting.cs').read_bytes()
    assert hashlib.sha256(original).hexdigest()==receipt['original_sha256']=='f7f2968b821db02448546220ef6382265a7cdff6b9470eb478de2cca50e2c88c'
    assert source==original.replace(b'DateTime.UtcNow',b'MapperClock.UtcNow')
    assert json.loads((ASSETS/'mapper_core.build.json').read_text(encoding='utf-8-sig'))['sources']['DamageReporting.cs']==hashlib.sha256(source).hexdigest()
    assert set(FOLDERS)==set(re.findall(r'"(damage_reporting/[^"\r\n]+)"',source.decode()))

def test_installed_english_commands_and_original_substring_response_matching():
    for key,phrases in COMMANDS.items():
        for phrase in phrases:assert command_for(phrase)==key
    assert command_for('fuel usage') is None
    assert all(clearly_ok(s) for s in I_AM_OK)
    assert clearly_ok("yes I'm fine, thanks")
    assert not clearly_ok('what was that')

@NATIVE
@pytest.mark.parametrize('field,value,expected',[
    ('mAeroDamage',.11,'trivial_aero_damage'),
    ('mAeroDamage',.3,'minor_aero_damage'),
    ('mAeroDamage',.65,'severe_aero_damage'),
    ('mEngineDamage',.22,'minor_engine_damage'),
    ('mEngineDamage',.5,'severe_engine_damage'),
    ('mEngineDamage',.95,'busted_engine'),
    ('mSuspensionDamage',.08,'minor_suspension_damage'),
    ('mSuspensionDamage',.2,'severe_suspension_damage'),
    ('mSuspensionDamage',.7,'busted_suspension'),
    ('mBrakeDamage',.35,None),
    ('mBrakeDamage',.7,None),
    ('mBrakeDamage',.95,None),
])
def test_original_component_thresholds_settle_delays_and_duplicate_suppression(core,field,value,expected):
    raw=raw_state();mapped(core,raw)
    if field in ('mSuspensionDamage','mBrakeDamage'):getattr(raw,field)[0]=value
    else:setattr(raw,field,value)
    assert not mapped(core,raw,1)['calls']
    assert not mapped(core,raw,4)['calls']  # strictly more than three seconds
    calls=through(core,raw,4.1,15)
    # Original defaults disable automatic brake damage; explicit reports remain.
    assert fragments(calls)==(['damage_reporting/'+expected] if expected else [])
    assert all(c['source_event']=='DamageReporting_4.19.5.4' and c['priority'] in (3,15) for c in calls)
    assert not through(core,raw,16,20)

@NATIVE
@pytest.mark.parametrize('core',[{'enable_brake_damage_messages':'True'}],indirect=True)
@pytest.mark.parametrize('value,expected',[(.35,'minor_brake_damage'),(.7,'severe_brake_damage'),(.95,'busted_brakes')])
def test_original_enabled_brake_damage_setting_restores_automatic_calls(core,value,expected):
    raw=raw_state();mapped(core,raw)
    raw.mBrakeDamage[0]=value
    assert fragments(through(core,raw,1,15))==['damage_reporting/'+expected]

@NATIVE
@pytest.mark.parametrize('corner',range(4))
def test_original_puncture_30kpa_threshold_and_corner_words(core,corner):
    raw=raw_state();mapped(core,raw)
    raw.mAirPressure[corner]=29
    calls=through(core,raw,11,19)
    assert fragments(calls)==['damage_reporting/'+('left_front','right_front','left_rear','right_rear')[corner]+'_puncture']
    assert not through(core,raw,20,25)

@NATIVE
def test_original_equal_pressure_sanity_filter(core):
    raw=raw_state()
    for i in range(4):raw.mAirPressure[i]=0
    mapped(core,raw)
    assert through(core,raw,11,20)==[]

@NATIVE
def test_original_repairs_withdraw_pending_damage_and_allow_later_damage(core):
    raw=raw_state();mapped(core,raw)
    raw.mAeroDamage=.3;mapped(core,raw,1)
    result=mapped(core,raw,4.1)
    assert result['queue']['regular']>=1
    raw.mAeroDamage=0
    assert not through(core,raw,4.2,15)
    raw.mAeroDamage=.3
    assert fragments(through(core,raw,16,30))==['damage_reporting/minor_aero_damage']

@NATIVE
@pytest.mark.parametrize('core',[{'enable_damage_messages':'False'}],indirect=True)
def test_original_disabled_automatic_damage_keeps_explicit_report(core):
    raw=raw_state();mapped(core,raw)
    raw.mAeroDamage=.3
    assert through(core,raw,1,15)==[]
    assert fragments(core.respond('HOWS_MY_AERO'))==['damage_reporting/minor_aero_damage']

@NATIVE
def test_original_full_report_and_individual_questions_no_invented_gearbox_health(core):
    raw=raw_state();mapped(core,raw)
    assert fragments(core.respond('DAMAGE_REPORT'))==['damage_reporting/no_damage']
    acknowledge(core,core.respond('HOWS_MY_AERO'))
    for t,cmd,expected in [(1,'HOWS_MY_BRAKES','no_brake_damage'),(2,'HOWS_MY_ENGINE','no_engine_damage'),
                           (3,'HOWS_MY_SUSPENSION','no_suspension_damage')]:
        mapped(core,raw,t)
        calls=core.respond(cmd)
        assert fragments(calls)==['damage_reporting/'+expected]
        acknowledge(core,calls)
    mapped(core,raw,4)
    assert fragments(core.respond('HOWS_MY_TRANSMISSION'))==['acknowledge/no_data']

def crash(core,*,voice=True,prior_voice=True):
    raw=raw_state();raw.mSpeed=40
    core.voice_enabled=voice
    mapped(core,raw)
    if prior_voice:core.speech_result("what's the air temperature",.9,detected_speech=True)
    mapped(core,raw,10)
    raw.mSpeed=1;raw.mEngineDamage=1
    mapped(core,raw,10.05)
    return raw,mapped(core,raw,13.06)

@NATIVE
@pytest.mark.parametrize('text,confidence,detected,expected',[
    ("I'm OK",.9,True,'acknowledge_driver_is_ok'),
    ('what was that',.9,True,'acknowledge_driver_is_ok_not_understood'),
    ("I'm OK",.4,True,'acknowledge_driver_is_ok_not_understood'),
    (None,0,True,'acknowledge_driver_is_ok_not_understood'),
    (None,0,False,'acknowledge_driver_is_ok_no_speech'),
])
def test_original_crash_conversation_actual_recognition_rejection_and_silence(core,text,confidence,detected,expected):
    raw,event=crash(core)
    assert fragments(event['calls'])==['damage_reporting/are_you_ok_first_try']
    assert event['waiting_for_driver_ok']
    acknowledge(core,event['calls'])
    calls=core.speech_result(text,confidence,detected_speech=detected)
    assert fragments(calls)==['damage_reporting/'+expected]
    assert not core.waiting_for_driver_ok

@NATIVE
def test_original_crash_retries_and_no_prompt_without_actual_voice_history(core):
    raw,event=crash(core,prior_voice=False)
    assert not event['waiting_for_driver_ok'] and not event['calls']
    assert fragments(through(core,raw,14,20))==['damage_reporting/busted_engine']
    core.reset_mapping()
    raw,event=crash(core)
    acknowledge(core,event['calls'])
    second=mapped(core,raw,21.07)
    assert fragments(second['calls'])==['damage_reporting/are_you_ok_second_try']
    acknowledge(core,second['calls'])
    third=mapped(core,raw,29.08)
    assert fragments(third['calls'])==['damage_reporting/are_you_ok_third_try']
    assert not third['waiting_for_driver_ok']

@NATIVE
def test_live_service_forwards_crash_response_before_ordinary_command_and_clears_speech_hold(core):
    from ams2season.coach.service import CoachService
    raw,event=crash(core);acknowledge(core,event['calls'])
    core.waiting_for_speech=True
    mapped(core,raw,13.1)
    service=CoachService.__new__(CoachService)
    service.core=core;service.buttons=None;service.output='paddock';service.audio_enabled=True
    service.thread=SimpleNamespace(is_alive=lambda:True)
    service.engine=SimpleNamespace(context=SimpleNamespace(session_id='damage-test'))
    service.talk={'state':'thinking'}
    service._local_valid=lambda _:True
    calls=[];origins=[]
    def queue_requested(items,*,requested=False):
        origins.append(requested)
        calls.extend(items)
    service._queue_baseline=queue_requested
    service.listener=SimpleNamespace(ready=True,error=None,heard_details=lambda:[{
        'text':"I'm OK",'confidence':.9,'detected_speech':True,'problem':None}])
    service._button_reply=lambda *args:pytest.fail('Crash response leaked into ordinary/advanced command routing')
    service._service_buttons()
    assert fragments(calls)==['damage_reporting/acknowledge_driver_is_ok']
    assert origins==[True]
    assert service.talk['last_heard']['understood'] and not core.waiting_for_driver_ok

@NATIVE
def test_typed_speech_does_not_invent_microphone_history_and_stale_replies_are_withheld(core):
    raw=raw_state();mapped(core,raw)
    assert core.speech_result("I'm OK",1,voice=False)==[]
    result=mapped(core,raw,.1)
    assert not result['has_made_voice_command']
    core.latest['at']-=1
    assert core.speech_result("I'm OK",1)==[]
    assert not mapped(core,raw,.2)['has_made_voice_command']

@NATIVE
def test_original_roll_and_upside_down_orientation_window(core):
    raw=raw_state();raw.mSpeed=1
    raw.mOrientation[0]=2
    mapped(core,raw)
    assert fragments(through(core,raw,.1,7))==['damage_reporting/stopped_upside_down']

@NATIVE
def test_unavailable_damage_withdraws_pending_calls_without_disabling_weather(core):
    raw=raw_state();mapped(core,raw)
    raw.mAeroDamage=.3;mapped(core,raw,1);mapped(core,raw,4.1)
    core.damage_available=False;core.weather_available=True
    result=mapped(core,raw,5)
    assert not result['valid'] and result['damage_state']=='damage_telemetry_unavailable'
    assert core.respond('HOWS_MY_AERO')==[]
    assert fragments(core.respond('WHATS_THE_AIR_TEMP'))[0]=='conditions/air_temp_is_now'

@NATIVE
@pytest.mark.parametrize('field,value',[('mAeroDamage',2),('mAirPressure',-1),('mOrientation',100)])
def test_live_full_snapshot_availability_rejects_invalid_damage_without_fake_zeroes(core,field,value):
    raw=raw_state()
    if field=='mAeroDamage':raw.mAeroDamage=value
    else:getattr(raw,field)[0]=value
    tick=from_snapshot(raw,1,'damage-test');player=tick.cars[0]
    core.feed_snapshot(raw,tick,player,time.perf_counter())
    assert not core.damage_available and core.damage_state=='damage_telemetry_unavailable'
    assert core.respond('HOWS_MY_AERO')==[]

def test_listener_detail_api_keeps_device_error_silence_and_rejected_speech_distinct():
    listener=WindowsListener.__new__(WindowsListener);listener.results=queue.Queue()
    inputs=[{'text':None,'confidence':0,'detected_speech':False,'problem':None},
            {'text':None,'confidence':0,'detected_speech':True,'problem':None},
            {'text':None,'confidence':0,'detected_speech':False,'problem':'device failed'}]
    for item in inputs:listener.results.put(item)
    assert listener.heard_details()==inputs
    listener.results.put(inputs[-1])
    assert listener.heard()==[(None,'device failed')]

def test_live_original_update_interval_preserves_sample_count_windows_and_immediate_invalid_data(monkeypatch):
    requests=[]
    core=Core(host=lambda p:requests.append(p) or {'mapped':True,'events':{'calls':[],'valid':[]}})
    raw=raw_state();tick=from_snapshot(raw,0,'cadence')
    core.settings['update_interval']='100'
    sampled=1000.
    monkeypatch.setattr('ams2season.coach.crew_core.time.perf_counter',lambda:sampled)
    for offset in (0,.05,.1,.15,.2):
        sampled=1000+offset
        core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled,respect_update_interval=True)
    assert len(requests)==3
    sampled=1000.25;raw.mAeroDamage=2
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled,respect_update_interval=True)
    assert len(requests)==4 and requests[-1]['damage_available'] is False
    sampled=1000.26
    raw.mSessionState=S.SESSION_QUALIFY
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled,respect_update_interval=True)
    assert len(requests)==5
    core.reset()
    core._needs_reset=False
    requests.clear()
    for offset in (0,.049,.099,.149,.199,.249,.299,.349):
        sampled=1001+offset
        core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled,respect_update_interval=True)
    assert len(requests)==4  # No 150ms drift from slightly early recorder samples.
