"""Original tyre event on complete synthetic AMS2 structs; no devices or game."""
import sys,json,hashlib
import time
from types import SimpleNamespace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'diagnostics/cc-tyres-live-20261017';A=ROOT/'ams2season/assets/crew_chief'
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import pytest
from ams2season.coach import crew_spotter
from ams2season.coach.crew_core import Core
from ams2season.coach.crew_mapper import DEFAULTS,snapshot_payload
from test_crew_chief_damage import raw_state
from test_crew_chief_mapper import TICKS

@pytest.fixture
def core(tmp_path,monkeypatch,request):
    host=Core(root=tmp_path);number_config=json.loads(host.settings['__paddock_number_config'])
    number_config['allow_short_hundreds']='false'
    number=json.dumps(number_config)
    host.settings=dict(DEFAULTS,__paddock_number_config=number,__paddock_state_directory=str(tmp_path/'state'),
        allow_rants='False',enable_driver_names='False',enable_delayed_responses='False')
    host.settings.update(getattr(request,'param',{}))
    host.tyres_available=True
    host.start()
    try:
        assert host.ready.wait(10),host.error
        yield host
    finally:host.close()

def step(core,raw,t=0,available=True):
    core.tyres_available=available
    result=core._request({'op':'map','raw':snapshot_payload(raw),'ticks':TICKS+round(t*10000000),'tyres_available':available})
    assert result and not result.get('error') and result.get('mapped'),result or core.error
    core._events(result['events'])
    import time
    core.latest={'at':time.perf_counter()}
    for c in result['events']['calls']:core.acknowledge(c['id'])
    return result['events']

def raw_tyres():
    raw=raw_state()
    for i in range(4):raw.mTyreRPS[i]=100
    return raw

def warm(core,raw=None):
    raw=raw or raw_tyres()
    step(core,raw);assert step(core,raw,1)['tyre_state']=='monitoring'
    return raw

def command(core,name):
    result=core._request({'op':'command','command':name,'ack':core.acknowledged[:]})
    assert result and not result.get('error'),result or core.error
    for c in result['calls']:core.acknowledge(c['id'])
    return result,[f for c in result['calls'] for f in c['fragments']]

def test_original_source_and_exact_helper_unchanged():
    c=A
    assert (c/'TyreMonitor.cs').read_bytes()==(ROOT/'diagnostics/cc-tyres-prep-20261017/installed-IL-source/CrewChiefV4.Events.TyreMonitor.cs').read_bytes()
    for name,digest in json.loads((c/'mapper_core.build.json').read_text(encoding='utf-8-sig'))['sources'].items():
        assert hashlib.sha256((c/name).read_bytes()).hexdigest()==digest

def test_actual_numeric_temperature_pressure_and_brake_fragments(core):
    warm(core)
    checks={}
    for name in ('WHAT_ARE_MY_TYRE_TEMPS','WHAT_ARE_MY_TYRE_PRESSURES','WHAT_ARE_MY_BRAKE_TEMPS'):
        result,words=command(core,name);checks[name]=words
        assert words and words!=['acknowledge/no_data'],result
        assert all(c['source_event']=='TyreMonitor_4.19.5.4' and c['folders_resolved'] for c in result['calls']),result
    assert checks['WHAT_ARE_MY_TYRE_TEMPS']==['tyre_monitor/left_front','numbers/85','tyre_monitor/right_front','numbers/86',
        'tyre_monitor/left_rear','numbers/87','tyre_monitor/right_rear','numbers/88','conditions/celsius']
    (HERE/'numeric-replies.json').write_text(json.dumps(checks,indent=2)+'\n')
    assert checks['WHAT_ARE_MY_BRAKE_TEMPS']==['tyre_monitor/left_front','numbers/4','numbers/hundred','tyre_monitor/right_front','numbers/4','numbers/hundred_and','numbers/10',
        'tyre_monitor/left_rear','numbers/4','numbers/hundred_and','numbers/20','tyre_monitor/right_rear','numbers/4','numbers/hundred_and','numbers/30','conditions/celsius']

@pytest.mark.parametrize('name',['HOW_ARE_MY_TYRE_TEMPS','HOW_ARE_MY_BRAKE_TEMPS','HOWS_MY_TYRE_WEAR'])
def test_original_condition_reports(core,name):
    warm(core)
    result,words=command(core,name)
    assert words and words!=['acknowledge/no_data'],result
    assert all(c['source_event']=='TyreMonitor_4.19.5.4' and c['folders_resolved'] for c in result['calls']),result

@pytest.mark.parametrize('name',['HOW_MANY_LAPS_ON_TYRE_SET','HOW_OLD_ARE_THESE_TYRES','WHAT_ARE_THE_RELATIVE_TYRE_PERFORMANCES'])
def test_unmapped_history_returns_no_data(core,name):
    warm(core);result,words=command(core,name)
    assert words==['acknowledge/no_data'] and result['withheld'],result

@pytest.mark.parametrize('field,value',[('mTyreTempCenter',0),('mTyreTempLeft',201),('mBrakeTempCelsius',0),('mTyreWear',-1)])
def test_unavailable_samples_reset_instead_of_repeating_previous_values(core,field,value):
    raw=warm(core);getattr(raw,field)[0]=value
    assert step(core,raw,2)['tyre_state']=='tyre_telemetry_unavailable'
    assert command(core,'WHAT_ARE_MY_TYRE_TEMPS')[1]==['acknowledge/no_data']

def test_requires_observed_pair_and_recovers(core):
    raw=raw_tyres();assert step(core,raw)['tyre_state']=='warming_up'
    assert command(core,'HOWS_MY_TYRE_WEAR')[1]==['acknowledge/no_data']
    assert step(core,raw,1)['tyre_state']=='monitoring'
    assert step(core,raw,2,False)['tyre_state']=='tyre_telemetry_unavailable'
    assert step(core,raw,3)['tyre_state']=='warming_up'
    assert step(core,raw,4)['tyre_state']=='monitoring'

@pytest.mark.parametrize('fahrenheit,imperial,unit,pressure_unit',[
    (False,False,'conditions/celsius','tyre_monitor/bar'),
    (True,True,'conditions/fahrenheit','tyre_monitor/psi')])
def test_original_unit_conversions(core,fahrenheit,imperial,unit,pressure_unit):
    core._fahrenheit=fahrenheit;core._fuel_gallons=imperial
    warm(core)
    assert command(core,'WHAT_ARE_MY_TYRE_TEMPS')[1][-1]==unit
    _,pressure=command(core,'WHAT_ARE_MY_TYRE_PRESSURES')
    assert pressure[-1]==pressure_unit
    if not imperial:
        expected=[]
        for w in ('left_front','right_front','left_rear','right_rear'):
            expected+=['tyre_monitor/'+w,'numbers/2','numbers/point','numbers/0','numbers/0']
        assert pressure==expected+[pressure_unit]
    else:
        # 200 kPa / original 6.894 = 29.0 psi, not 200 psi.
        assert pressure.count('numbers/29')==4,pressure

def test_original_live_surface_reading_not_average(core):
    warm(core)
    _,words=command(core,'WHAT_ARE_MY_LEFT_FRONT_SURFACE_TEMPS')
    assert words==['numbers/80','numbers/85','numbers/90','conditions/celsius']
    # Average data is not available before an observed lap completion.
    assert command(core,'HOWS_MY_LEFT_FRONT_CAMBER')[1]==['acknowledge/no_data']

@pytest.mark.parametrize('core',[{}, {'enable_brake_lock_warnings':'False'}],indirect=True,ids=['enabled','disabled'])
def test_original_cumulative_front_lock_warning_and_switch(core):
    raw=warm(core);raw.mTyreRPS[0]=raw.mTyreRPS[1]=0
    calls=[]
    for i in range(11,151):
        event=step(core,raw,i/10);calls+=event['calls']
    locking=[c for c in calls if any('locking' in f for f in c['fragments'])]
    if core.settings['enable_brake_lock_warnings']=='False':assert not locking,calls
    else:
        assert locking,calls
        assert all(c['source_event']=='TyreMonitor_4.19.5.4' and c['queue_managed'] for c in locking),locking
    (HERE/('lock-warning-'+core.settings['enable_brake_lock_warnings']+'.json')).write_text(json.dumps(calls,indent=2)+'\n')

def test_original_missing_wheel_excludes_lock_diagnosis(core):
    raw=warm(core);raw.mTyreRPS[0]=raw.mTyreRPS[1]=0;raw.mTyreFlags[0]=0;raw.mAirPressure[0]=0
    calls=[]
    for i in range(11,151):calls+=step(core,raw,i/10)['calls']
    assert not any('locking' in f for c in calls for f in c['fragments']),calls

def test_original_summary_contains_tyre_and_brake_status(core):
    warm(core);result,words=command(core,'CAR_STATUS')
    assert words and words!=['acknowledge/no_data'],result
    assert all(c['source_event']=='TyreMonitor_4.19.5.4' for c in result['calls']),result

def test_paddock_tyre_alias_uses_original_summary_only(core):
    warm(core);result,words=command(core,'PADDOCK_TYRE_STATUS')
    assert words and words!=['acknowledge/no_data'],result
    assert all(c['source_event']=='TyreMonitor_4.19.5.4' for c in result['calls']),result
    assert command(core,'WHAT_TYRES_AM_I_ON')[1]==['acknowledge/no_data']

def test_original_new_tyre_life_reply_is_not_replaced_by_a_fake_estimate(core):
    raw=raw_tyres()
    for w in range(4):raw.mTyreWear[w]=0
    warm(core,raw)
    result,words=command(core,'HOW_LONG_WILL_THESE_TYRES_LAST')
    assert words==['tyre_monitor/good_wear'],result

def test_all_installed_grammar_and_real_tyre_set_suffixes_match():
    from ams2season.coach import crew_tyres
    for name,phrases in crew_tyres.COMMANDS.items():
        for phrase in phrases:
            assert crew_tyres.command_for(phrase.upper()+'?')==name
            assert crew_tyres.command_for(phrase.replace('tire','tyre'))==name
    assert crew_tyres.command_for('how many laps on tyre set two')=='HOW_MANY_LAPS_ON_TYRE_SET'
    assert crew_tyres.command_for('how many laps on tire set 2')=='HOW_MANY_LAPS_ON_TYRE_SET'
    assert 'how many laps on tyre set two' in crew_tyres.listener_phrases()

def test_actual_service_routes_original_summary_with_requested_origin(core):
    from ams2season.coach.service import CoachService
    warm(core)
    service=CoachService.__new__(CoachService)
    service.output='paddock';service.audio_enabled=True;service.core=core
    service.talk={'state':'idle'};service._local_valid=lambda _:True
    log=[];queued=[]
    service.engine=SimpleNamespace(context=SimpleNamespace(session_id='tyre-test'),
        radio=SimpleNamespace(log=SimpleNamespace(record=lambda *a,**k:log.append(k))))
    def queue(calls,*,requested=False):
        assert requested
        queued.extend(calls)
    service._queue_baseline=queue
    reply=service._engine_reply('tyre status','typed')
    assert reply['understood']=='PADDOCK_TYRE_STATUS' and queued and log
    assert all(c['source_event']=='TyreMonitor_4.19.5.4' and c['native_id'].startswith('core:') for c in queued),queued
    assert not any(f.startswith('fuel/') for c in queued for f in c['fragments'])

def test_complete_live_snapshot_and_stale_reply_guards(core):
    from ams2season.coach.telemetry import from_snapshot
    raw=raw_tyres();tick=from_snapshot(raw,0,'tyres-live');player=tick.player('Jax_Lam')
    core.feed_snapshot(raw,tick,player,time.perf_counter())
    assert core.tyres_available and core.tyres_state=='warming_up'
    core.feed_snapshot(raw,tick,player,time.perf_counter())
    assert core.tyres_state=='monitoring'
    assert core.respond('WHAT_ARE_MY_TYRE_TEMPS')
    core.latest['at']-=1
    assert core.respond('WHAT_ARE_MY_TYRE_TEMPS')==[]

@pytest.mark.parametrize('cached',[True,False])
def test_native_tyre_soundset_keeps_selected_cached_voice_or_reported_original(tmp_path,cached):
    from test_crew_chief_voice_engine import folder
    from ams2season.coach.crew_spotter import CrewChiefSounds
    from ams2season.coach.crew_voice import CrewChiefVoice
    from ams2season.coach.voice import pcm_wav
    sounds=tmp_path/'sounds';folder(sounds,'tyre_monitor/good_wear',['wear looks good'])
    voice=SimpleNamespace(get=lambda _:SimpleNamespace(data=pcm_wav(b'\3\0'*8820)) if cached else None)
    cc=CrewChiefVoice(CrewChiefSounds(sounds))
    assert cc.open_native(tmp_path,folders=['tyre_monitor/good_wear'],voice=voice),cc.native_error
    try:
        text,data,source=cc.choose('tyre_monitor/good_wear',t=100)
        assert source==('voice_pack' if cached else 'crew_chief_recording') and data and text=='wear looks good'
        assert cc.native is not None and not cc.native_error
    finally:cc.close()

def test_tyre_call_controls_apply_switches_and_protect_requested_replies(tmp_path):
    from ams2season.coach.call_controls import CallControls
    control=CallControls(tmp_path)
    control.save({'revision':0,'overrides':{'families':{'tyres':{'enabled':False}},
        'native':{'enable_tyre_temp_warnings':False}}})
    core=SimpleNamespace(settings=dict(DEFAULTS));events=SimpleNamespace(settings={})
    control.activate(core,events)
    assert core.settings['enable_tyre_temp_warnings']=='False'
    call={'source_event':'TyreMonitor_4.19.5.4','sound_type':'REGULAR_MESSAGE'}
    assert control.native_reason(call,'tyres-test',1)=='automatic_call_disabled'
    assert control.native_reason({**call,'requested':True},'tyres-test',2) is None

def sector(core,raw,index,wear):
    for i in range(raw.mNumParticipants):
        raw.mParticipantInfo[i].mCurrentSector=index%3
        raw.mParticipantInfo[i].mLapsCompleted=2+index//3
        raw.mParticipantInfo[i].mCurrentLap=3+index//3
        raw.mParticipantInfo[i].mCurrentLapDistance=100+(index%3)*1800
    for i in range(4):raw.mTyreWear[i]=wear
    return step(core,raw,2+index*10)

@pytest.mark.parametrize('wear',[.1,.2])
def test_life_estimate_needs_observed_nonconstant_trajectory(core,wear):
    raw=raw_tyres()
    for w in range(4):raw.mTyreWear[w]=wear
    warm(core,raw)
    for i in range(9):sector(core,raw,i,wear)
    result,words=command(core,'HOW_LONG_WILL_THESE_TYRES_LAST')
    assert words==['acknowledge/no_data'] and any('trajectory' in r for r in result['withheld']),result

def test_original_polynomial_estimate_runs_after_real_sector_wear_history(core):
    raw=warm(core)
    for i in range(9):sector(core,raw,i,.03+.005*i)
    result,words=command(core,'HOW_LONG_WILL_THESE_TYRES_LAST')
    assert words and words!=['acknowledge/no_data'],result
    assert any('laps_on_current_tyres' in f for f in words),result
    (HERE/'polynomial-life-reply.json').write_text(json.dumps(result,indent=2)+'\n')

@pytest.mark.parametrize('core',[{}, {'enable_tyre_temp_warnings':'False','enable_brake_temp_warnings':'False'}],indirect=True,ids=['enabled','disabled'])
def test_original_automatic_temperature_warnings_and_switches(core):
    raw=warm(core)
    for w in range(4):
        raw.mTyreTempLeft[w]=raw.mTyreTempCenter[w]=raw.mTyreTempRight[w]=150
        raw.mBrakeTempCelsius[w]=1200
    calls=[]
    for i in range(1,16):calls+=sector(core,raw,i,.1)['calls']
    hot=[c for c in calls if any(f in ('tyre_monitor/cooking_tyres_all_round','tyre_monitor/cooking_brakes_all_round') for f in c['fragments'])]
    if core.settings['enable_tyre_temp_warnings']=='False':assert not hot,calls
    else:
        assert hot,calls
        assert all(c['source_event']=='TyreMonitor_4.19.5.4' and c['queue_managed'] for c in hot),hot
    (HERE/('temperature-warning-'+core.settings['enable_tyre_temp_warnings']+'.json')).write_text(json.dumps(calls,indent=2)+'\n')
