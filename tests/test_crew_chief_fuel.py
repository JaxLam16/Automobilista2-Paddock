"""Original fuel and race-time events through actual isolated native hosts."""
import hashlib
import json
from pathlib import Path
import sys
import time

import pytest

from ams2season import shm as S
from ams2season.coach.crew_core import Core
from ams2season.coach.crew_fuel import COMMANDS,TIME_COMMANDS,PHRASES,command_for,request_text,listener_phrases
from ams2season.coach.crew_mapper import DEFAULTS,snapshot_payload
from ams2season.coach.crew_spotter import ASSETS
from ams2season.coach.telemetry import from_snapshot
from test_crew_chief_damage import raw_state
from test_crew_chief_mapper import TICKS

NATIVE=pytest.mark.skipif(sys.platform!='win32',reason='Original Framework fuel events')

@pytest.fixture
def core(tmp_path,request):
    host=Core(root=tmp_path)
    numbers=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS,__paddock_number_config=numbers,
        __paddock_state_directory=str(tmp_path/'state'),__paddock_fuel_multiplier='1')
    host.settings.update(getattr(request,'param',{}))
    host.fuel_available=True;host.race_time_available=True
    host.start();assert host.ready.wait(10),host.error
    try:yield host
    finally:host.close()

def mapped(core,raw,t=0):
    result=core._request({'op':'map','raw':snapshot_payload(raw),'ticks':TICKS+round(t*10000000)})
    assert result and result.get('mapped') and not result.get('error'),result or core.error
    core.latest={'at':time.perf_counter()}
    core._events(result['events'])
    return result

def fragments(calls):return [f for c in calls for f in c['fragments']]
def acknowledge(core,calls):
    for c in calls:core.acknowledge(c.get('native_id','core:'+c['id']))

def warm(core,raw=None):
    raw=raw or raw_state()
    for t in (0,1,2,3):
        result=mapped(core,raw,t);acknowledge(core,result['events']['calls'])
    return raw,result

def lap(core,raw,t,litres,invalid=False):
    for i in range(raw.mNumParticipants):
        raw.mParticipantInfo[i].mCurrentSector=1;raw.mParticipantInfo[i].mCurrentLapDistance=2000+i*50
        raw.mCurrentSector1Times[i]=35
        raw.mCurrentSector2Times[i]=40
        raw.mCurrentSector3Times[i]=35
    raw.mLapInvalidated=invalid
    mapped(core,raw,t-2)
    for i in range(raw.mNumParticipants):
        raw.mParticipantInfo[i].mCurrentSector=2;raw.mParticipantInfo[i].mCurrentLapDistance=4000+i*50
    mapped(core,raw,t-1)
    for i in range(raw.mNumParticipants):
        p=raw.mParticipantInfo[i];p.mLapsCompleted+=1;p.mCurrentLap+=1
        p.mCurrentSector=0;p.mCurrentLapDistance=20+i*50
        raw.mLastLapTimes[i]=raw.mFastestLapTimes[i]=110
    raw.mLastLapTime=raw.mBestLapTime=110
    raw.mFuelLevel=litres/100
    result=mapped(core,raw,t)
    acknowledge(core,result['events']['calls'])
    return result

def test_original_event_and_dependency_bodies_are_pinned():
    root=ASSETS.parents[2]
    receipts=json.loads((ASSETS/'fuel_sources.json').read_text())
    def block(text,marker):
        start=text.index(marker);end=text.index('{',start)+1;depth=1
        while depth:
            depth+=(text[end]=='{')-(text[end]=='}');end+=1
        return text[start:end]
    build=json.loads((ASSETS/'mapper_core.build.json').read_text(encoding='utf-8-sig'))
    for name,item in receipts.items():
        source=(ASSETS/name).read_bytes()
        assert hashlib.sha256(source).hexdigest()==item['sha256']==build['sources'][name]
        if 'original' in item:
            original=(root/item['original']).read_bytes()
            assert hashlib.sha256(original).hexdigest()==item['original_sha256']
            assert source==original.replace(b'DateTime.UtcNow',b'MapperClock.UtcNow')
        for dependency in item.get('dependencies',()):
            original=(root/dependency['original']).read_bytes()
            assert hashlib.sha256(original).hexdigest()==dependency['original_sha256']
            for marker in dependency['methods']:assert block(source.decode().replace('\r\n','\n'),marker)==block(original.decode('utf-8-sig').replace('\r\n','\n'),marker)
    for name,sha in build['metadata'].items():assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()==sha

def test_original_installed_fuel_phrases_and_bounded_numeric_requests():
    for key,phrases in {**COMMANDS,**TIME_COMMANDS}.items():
        if key=='CALCULATE_FUEL_FOR':continue
        for phrase in phrases:assert command_for(phrase+'?')==key
    for phrase in ('calculate fuel for five laps','how much fuel do i need for 199 minutes','how much fuel for two hours'):
        assert command_for(phrase)=='CALCULATE_FUEL_FOR'
    for phrase in ('calculate fuel for 200 laps','calculate fuel for 0 laps','calculate fuel for unknown laps','set fuel to 50'):
        assert command_for(phrase) is None
    assert request_text('Calculate fuel for 5 laps?')=='calculate fuel for five laps'
    assert 'calculate fuel for five laps' in listener_phrases()

@NATIVE
def test_startup_zero_is_not_spoken_as_an_empty_tank(core):
    raw=raw_state();mapped(core,raw)
    assert core.fuel_state=='warming_up'
    assert fragments(core.respond('WHATS_MY_FUEL_LEVEL'))==['acknowledge/no_data']

@NATIVE
@pytest.mark.parametrize('gallons,unit',[ (False,'litres_remaining'),(True,'gallons_remaining')])
def test_original_level_question_uses_explicit_units_and_measured_tank(core,gallons,unit):
    core._fuel_gallons=gallons
    raw,state=warm(core)
    assert core.fuel_state=='monitoring'
    calls=core.respond('WHATS_MY_FUEL_LEVEL')
    assert calls[0]['fragments'][-1]=='fuel/'+unit
    assert calls[0]['source_event']=='Fuel_4.19.5.4'
    if not gallons:assert calls[0]['fragments']==['numbers/50','fuel/litres_remaining']
    else:assert calls[0]['fragments']==['numbers/13point2','fuel/gallons_remaining']

@NATIVE
def test_original_consumption_waits_for_actual_complete_laps(core):
    raw,state=warm(core)
    calls=core.respond('WHATS_MY_FUEL_USAGE');assert fragments(calls)==['acknowledge/no_data'];acknowledge(core,calls)
    lap(core,raw,113,48)
    assert core.fuel_data['data']['measuredSamples']==0
    lap(core,raw,223,46)
    assert core.fuel_data['data']['measuredSamples']==1
    assert core.fuel_data['data']['consumptionPerLap']==pytest.approx(2,abs=.001)
    calls=core.respond('WHATS_MY_FUEL_USAGE')
    assert calls[0]['fragments']==['numbers/2point0','fuel/litres_per_lap']

@NATIVE
def test_original_numeric_lap_and_time_calculations_use_measured_history(core):
    raw,_=warm(core);lap(core,raw,113,48);lap(core,raw,223,46)
    calls=core.respond('CALCULATE_FUEL_FOR',text='calculate fuel for five laps')
    assert 'numbers/10' in fragments(calls) and 'fuel/litres' in fragments(calls)
    acknowledge(core,calls);mapped(core,raw,230)
    calls=core.respond('CALCULATE_FUEL_FOR',text='calculate fuel for five minutes')
    assert 'fuel/litres' in fragments(calls)

@NATIVE
def test_original_strategy_percentile_changes_and_reset(core):
    raw,_=warm(core)
    for i,level in enumerate((48,46,43,39)):
        lap(core,raw,113+i*110,level)
    measured=core.fuel_data['data']
    assert measured['measuredSamples']==3
    assert measured['consumptionPerLap']==pytest.approx(4,abs=.001)
    for t,command,reserve,usage in [(445,'SET_FUEL_STRATEGY_RISKY',.5,3),(446,'SET_FUEL_STRATEGY_CAUTIOUS',2,4),(447,'SET_FUEL_STRATEGY_RESET',1,4)]:
        mapped(core,raw,t);calls=core.respond(command);acknowledge(core,calls)
        mapped(core,raw,t+.1)
        assert core.fuel_data['data']['reserveMultiplier']==reserve
        assert core.fuel_data['data']['consumptionPerLap']==pytest.approx(usage,abs=.001)

@NATIVE
def test_original_absolute_low_fuel_warning_only_once(core):
    raw,_=warm(core);raw.mFuelLevel=.008
    calls=[]
    for t in range(4,30):
        result=mapped(core,raw,t);calls+=result['events']['calls'];acknowledge(core,result['events']['calls'])
    assert fragments(calls).count('fuel/one_litre_remaining')==1

@NATIVE
@pytest.mark.parametrize('core',[{'__paddock_fuel_multiplier':'0'}],indirect=True)
def test_explicit_zero_multiplier_disables_fuel_without_disabling_time_calls(core):
    raw,_=warm(core)
    assert core.fuel_state=='disabled_fuel_multiplier'
    assert fragments(core.respond('WHATS_MY_FUEL_LEVEL'))==['acknowledge/no_data']
    assert 'race_time/laps_remaining' in fragments(core.respond('HOW_LONGS_LEFT'))

@NATIVE
def test_bad_fuel_availability_withdraws_pending_questions_but_retains_race_time(core):
    raw,_=warm(core);calls=core.respond('WHATS_MY_FUEL_LEVEL');assert calls
    core.fuel_available=False
    result=mapped(core,raw,4)
    assert not result['events']['valid'] and core.fuel_state=='fuel_telemetry_unavailable'
    assert not core.respond('WHATS_MY_FUEL_LEVEL')
    assert core.respond('WHAT_LAP_AM_I_ON')

@NATIVE
def test_original_race_time_lap_count_and_remaining_questions(core):
    raw,_=warm(core)
    assert fragments(core.respond('WHAT_LAP_AM_I_ON'))==['numbers/3']
    calls=core.respond('HOW_LONGS_LEFT')
    assert fragments(calls)==['numbers/8','race_time/laps_remaining']

@NATIVE
def test_original_timed_practice_minutes_and_two_minute_warning(core):
    raw=raw_state();raw.mSessionState=S.SESSION_PRACTICE;raw.mLapsInEvent=0;raw.mEventTimeRemaining=600
    raw.mNumParticipants=1;raw.mParticipantInfo[0].mRacePosition=1
    for i in (1,2):raw.mParticipantInfo[i].mIsActive=False
    raw,_=warm(core,raw)
    calls=core.respond('HOW_LONGS_LEFT')
    assert 'race_time/remaining' in fragments(calls)
    acknowledge(core,calls)
    # This solo practice verifies time/personal fuel only, not any opponent gap.
    raw.mEventTimeRemaining=119
    result=mapped(core,raw,481)
    assert 'race_time/two_minutes_left' in fragments(result['events']['calls'])

@NATIVE
@pytest.mark.parametrize('core',[{'legacy_fuel':'True'}],indirect=True)
def test_original_installed_legacy_mode_is_respected(core):
    raw,_=warm(core)
    for t in (15,16,17):mapped(core,raw,t)
    assert core.fuel_data['mode']=='legacy'
    assert core.fuel_state=='monitoring_legacy'
    assert 'fuel/litres_remaining' in fragments(core.respond('WHATS_MY_FUEL_LEVEL'))

@NATIVE
@pytest.mark.parametrize('invalid',[-1,2,float('nan')])
def test_full_snapshot_fuel_gate_rejects_invalid_values(core,invalid):
    raw=raw_state();raw.mFuelLevel=invalid
    tick=from_snapshot(raw,0,'fuel-test')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter())
    assert not core.fuel_available
    assert not core.respond('WHATS_MY_FUEL_LEVEL')

def test_private_multiplier_validation_and_persistence(tmp_path):
    from ams2season.app import App
    app=App(tmp_path)
    try:
        assert app.coach.fuel_multiplier==1
        app.coach.configure({'fuel_multiplier':3})
        assert app.coach.fuel_multiplier==3 and app.coach.core.settings['__paddock_fuel_multiplier']=='3'
        saved=json.loads((tmp_path/'private_coach/settings.json').read_text())
        assert saved['fuel_multiplier']==3
        for value in (True,-1,11,1.5,'2'):
            with pytest.raises(ValueError,match='Fuel multiplier'):app.coach.configure({'fuel_multiplier':value})
    finally:app.coach.close()


def test_starting_coach_keeps_selected_fuel_multiplier(tmp_path):
    from test_coach_service import app_with_current
    app=app_with_current(tmp_path)
    try:
        app.coach.configure({'fuel_multiplier':3})
        previous=app.coach.core
        app.coach.start('Player')
        assert app.coach.core is not previous
        assert app.coach.core.settings['__paddock_fuel_multiplier']=='3'
    finally:app.coach.close()

@NATIVE
@pytest.mark.parametrize('core',[{'__paddock_fuel_multiplier':'3'}],indirect=True)
def test_original_private_saved_combo_filter_junk_filter_and_multiplier(core):
    raw=raw_state();state=mapped(core,raw)
    path=Path(core.settings['__paddock_state_directory'])/'fuel_usage.json'
    data=[{'game':'AMS2','carName':state['car_name'],'trackName':state['track'],
           'fuel':[{'litres':2,'lap_time':110,'conditions':0},{'litres':.1,'lap_time':110,'conditions':0}]},
          {'game':'AMS2','carName':'Wrong car','trackName':state['track'],
           'fuel':[{'litres':99,'lap_time':110,'conditions':0}]}]
    path.write_text(json.dumps(data));before=path.read_bytes()
    mapped(core,raw,1);mapped(core,raw,2)
    lap(core,raw,113,44)
    assert core.fuel_data['data']['savedSamples']==1
    assert core.fuel_data['data']['consumptionPerLap']==pytest.approx(6,abs=.001)
    assert path.read_bytes()==before

@NATIVE
@pytest.mark.parametrize('core',[{'save_all_fuel_data':'True'}],indirect=True)
@pytest.mark.parametrize('invalid',[False,True])
def test_original_fuel_history_saves_valid_green_laps_only_to_private_path(core,invalid):
    raw,_=warm(core)
    for i in range(4):lap(core,raw,113+110*i,48-2*i,invalid=invalid)
    assert core.fuel_data['data']['measuredSamples']==3
    raw.mPitMode=raw.mPitModes[0]=S.PIT_MODE_IN_PIT
    mapped(core,raw,445)
    path=Path(core.settings['__paddock_state_directory'])/'fuel_usage.json'
    if invalid:assert not path.exists()
    else:
        saved=json.loads(path.read_text())
        assert len(saved[0]['fuel'])==3
        assert all(sample['litres']==pytest.approx(2,abs=.001) for sample in saved[0]['fuel'])
        assert path.resolve().is_relative_to(core.root.resolve())

@NATIVE
def test_original_pit_entry_refuel_and_exit_track_actual_fuel_added(core):
    raw,_=warm(core);lap(core,raw,113,48);lap(core,raw,223,46)
    raw.mPitMode=raw.mPitModes[0]=S.PIT_MODE_IN_PIT;mapped(core,raw,225)
    raw.mFuelLevel=.66;mapped(core,raw,226);mapped(core,raw,227)
    raw.mPitMode=raw.mPitModes[0]=S.PIT_MODE_NONE;mapped(core,raw,228)
    assert core.fuel_data['data']['FuelAddedInLastStop']==pytest.approx(20,abs=.001)

@NATIVE
@pytest.mark.parametrize('lapped',[False,True])
def test_timed_race_remaining_laps_share_original_fuel_state_with_real_opponent_slots(core,lapped):
    raw=raw_state();raw.mLapsInEvent=0;raw.mEventTimeRemaining=600
    if lapped:
        raw.mParticipantInfo[0].mLapsCompleted=1;raw.mParticipantInfo[0].mCurrentLap=2
    raw,_=warm(core,raw)
    for t,litres in ((113,48),(223,46),(333,44)):
        raw.mEventTimeRemaining=600-t
        lap(core,raw,t,litres)
    remaining=core.fuel_data['data']['LapsRemaining']
    assert 2<remaining<7
    calls=core.respond('HOW_LONGS_LEFT')
    assert 'numbers/'+str(remaining) in fragments(calls)
    assert 'race_time/laps_remaining' in fragments(calls)

def test_unknown_session_clock_does_not_become_a_last_lap_call():
    requests=[]
    core=Core(host=lambda p:requests.append(p) or {'mapped':True,'events':{'calls':[],'valid':[]}})
    raw=raw_state();raw.mLapsInEvent=0;raw.mEventTimeRemaining=-1
    tick=from_snapshot(raw,0,'unknown-clock')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter())
    assert not requests[-1]['race_time_available']

def test_original_baseline_suppresses_duplicate_advanced_low_fuel_and_damage_warnings():
    from types import SimpleNamespace
    from ams2season.coach.engine import CoachEngine
    engine=CoachEngine.__new__(CoachEngine)
    engine.original_fuel_monitor=engine.original_damage_reporting=True
    calls=[];engine._say=lambda *args,**kwargs:calls.append(args)
    low={'kind':'fuel_low','whole':1}
    engine._car_status(low,None,None,None)
    engine._car_status({'kind':'damage','changes':[]},None,None,None)
    assert calls==[]
    engine.original_fuel_monitor=False
    engine._car_status(low,SimpleNamespace(t=1),None,None)
    assert calls[0][0]=='M-17'
