"""Original lap/sector events with real mapped synthetic timing history."""
from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'diagnostics/cc-laptimes-live-20261017';A=ROOT/'ams2season/assets/crew_chief'
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import pytest
from ams2season import shm as S
from ams2season.coach import crew_spotter
from ams2season.coach.crew_core import Core
from ams2season.coach.crew_mapper import DEFAULTS,snapshot_payload
from test_crew_chief_damage import raw_state
from test_crew_chief_mapper import TICKS

COMMANDS=('WHAT_ARE_MY_SECTOR_TIMES','WHATS_MY_LAST_SECTOR_TIME','WHATS_MY_BEST_LAP_TIME',
    'WHATS_THE_FASTEST_LAP_TIME','WHAT_WAS_MY_LAST_LAP_TIME','HOWS_MY_PACE','HOWS_MY_SELF_PACE')

@pytest.fixture(params=['False','True'],ids=['current','legacy'])
def core(tmp_path,monkeypatch,request):
    host=Core(root=tmp_path);numbers=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS,__paddock_number_config=numbers,__paddock_state_directory=str(tmp_path/'state'),
        allow_rants='False',enable_driver_names='False',revert_to_legacy_version_of_refactored_code=request.param,
        frequency_of_player_race_lap_time_reports='10',frequency_of_player_prac_and_qual_lap_time_reports='10')
    host.start()
    try:
        assert host.ready.wait(10),host.error
        yield host
    finally:host.close()

def raw_laps():
    raw=raw_state()
    raw.mLastLapTime=raw.mBestLapTime=-1
    for i in range(raw.mNumParticipants):
        raw.mLastLapTimes[i]=raw.mFastestLapTimes[i]=-1
        raw.mParticipantInfo[i].mLapsCompleted=0;raw.mParticipantInfo[i].mCurrentLap=1
    return raw

def step(core,raw,t=0,available=True):
    core.lap_times_available=available
    if raw.mSessionState in (S.SESSION_PRACTICE,S.SESSION_QUALIFY):
        raw.mLapsInEvent=0
        raw.mEventTimeRemaining=1800-t
    result=core._request({'op':'map','raw':snapshot_payload(raw),'ticks':TICKS+round(t*10000000),'lap_times_available':available})
    assert result and not result.get('error') and result.get('mapped'),result or core.error
    core._events(result['events'])
    for c in result['events']['calls']:core.acknowledge(c['id'])
    return result['events']

def command(core,name):
    result=core._request({'op':'command','command':name,'ack':core.acknowledged[:]})
    assert result and not result.get('error'),result or core.error
    core._events(result)
    for c in result['calls']:core.acknowledge(c['id'])
    return result,[f for c in result['calls'] for f in c['fragments']]

def lap(core,raw,n,start,laptime=98.765,opponents=False):
    calls=[]
    for sector,t,dist in ((1,start+31,2000),(2,start+64,4000),(0,start+laptime,50)):
        p=raw.mParticipantInfo[0];p.mCurrentSector=sector;p.mCurrentLapDistance=dist
        raw.mCurrentSector1Times[0]=31
        raw.mCurrentSector2Times[0]=33
        raw.mCurrentSector3Times[0]=laptime-64
        if sector==0:
            p.mLapsCompleted=n;p.mCurrentLap=n+1;raw.mLastLapTime=laptime
            raw.mLastLapTimes[0]=raw.mFastestLapTimes[0]=raw.mBestLapTime=laptime
        if opponents:
            for i,total in ((1,97.5),(2,105.0)):
                raw.mParticipantInfo[i].mCurrentSector=sector
                raw.mParticipantInfo[i].mCurrentLapDistance=dist
                raw.mCurrentSector1Times[i]=raw.mCurrentSector2Times[i]=raw.mCurrentSector3Times[i]=total/3
                if sector==0:
                    raw.mParticipantInfo[i].mLapsCompleted=n;raw.mParticipantInfo[i].mCurrentLap=n+1
                    raw.mLastLapTimes[i]=raw.mFastestLapTimes[i]=total
        event=step(core,raw,t);calls+=event['calls']
    return event,calls

def warm(core,phase=S.SESSION_RACE):
    raw=raw_laps();raw.mSessionState=phase
    assert step(core,raw)['lap_times_state']=='warming_up'
    assert step(core,raw,1)['lap_times_state']=='monitoring'
    return raw

def test_unchanged_installed_event_views_and_build_sources():
    c=A
    for name in ('LapTimes','LapTimes_legacy'):
        assert (c/(name+'.cs')).read_bytes()==(ROOT/('diagnostics/cc-laptimes-prep-20261017/installed-IL-source/CrewChiefV4.Events.'+name+'.cs')).read_bytes()
    for name,digest in json.loads((c/'mapper_core.build.json').read_text(encoding='utf-8-sig'))['sources'].items():
        assert hashlib.sha256((c/name).read_bytes()).hexdigest()==digest

def test_original_preference_selects_actual_type_and_no_history_is_no_data(core):
    raw=warm(core)
    state=step(core,raw,2)
    expected='legacy' if core.settings['revert_to_legacy_version_of_refactored_code']=='True' else 'current'
    assert state['lap_times']['mode']==expected
    for i,name in enumerate(COMMANDS):
        step(core,raw,3+6*i)
        assert command(core,name)[1]==['acknowledge/no_data'],name

@pytest.mark.parametrize('phase',[S.SESSION_RACE,S.SESSION_PRACTICE,S.SESSION_QUALIFY])
def test_observed_lap_history_yields_original_last_best_and_sector_replies(core,phase):
    raw=warm(core,phase);lap(core,raw,1,2)
    state,calls=lap(core,raw,2,102)
    assert state['lap_times']['mapped']['LapTimePrevious']==pytest.approx(98.765,abs=.001),state
    replies={}
    for i,name in enumerate(COMMANDS[:5]):
        step(core,raw,202+6*i)
        result,words=command(core,name);replies[name]=words
        assert words and words!=['acknowledge/no_data'],result
        assert all(c['source_event']=='LapTimes_4.19.5.4' and c['folders_resolved'] for c in result['calls']),result
    assert 'lap_times/time_intro' in replies['WHAT_WAS_MY_LAST_LAP_TIME']
    (HERE/('lap-replies-'+str(phase)+'-'+core.settings['revert_to_legacy_version_of_refactored_code']+'.json')).write_text(json.dumps({'state':state,'replies':replies,'automatic':calls},indent=2)+'\n')

def test_input_loss_clears_event_and_requires_new_observed_pair(core):
    raw=warm(core)
    assert step(core,raw,2,False)['lap_times_state']=='lap_times_telemetry_unavailable'
    assert command(core,'WHAT_WAS_MY_LAST_LAP_TIME')[1]==['acknowledge/no_data']
    assert step(core,raw,3)['lap_times_state']=='warming_up'
    assert step(core,raw,4)['lap_times_state']=='monitoring'

def test_invalid_lap_does_not_replace_the_observed_personal_best(core):
    raw=warm(core);lap(core,raw,1,2);state,_=lap(core,raw,2,102)
    before=state['lap_times']['mapped']['PlayerLapTimeSessionBest']
    raw.mLapInvalidated=True;raw.mLapsInvalidated[0]=True
    state,calls=lap(core,raw,3,202,laptime=97.2)
    assert not state['lap_times']['mapped']['PreviousLapWasValid'],state
    assert state['lap_times']['mapped']['PlayerLapTimeSessionBest']==before,state
    assert not any('personal_best' in f for c in calls for f in c['fragments']),calls

def test_missing_provided_sector_uses_original_observed_clock_not_zero(core):
    raw=warm(core);lap(core,raw,1,2)
    raw.mParticipantInfo[0].mCurrentSector=1;raw.mCurrentSector1Times[0]=0
    state=step(core,raw,132)
    result,words=command(core,'WHATS_MY_LAST_SECTOR_TIME')
    assert state['lap_times']['mapped']['LastSector1Time']==pytest.approx(31.235,abs=.02),state
    assert words and words!=['acknowledge/no_data'] and 'numbers/31' in words,result

def test_original_automatic_lap_report_uses_shared_queue(core):
    raw=warm(core);lap(core,raw,1,2);_,calls=lap(core,raw,2,102)
    assert calls,calls
    assert any('lap_times/time_intro' in c['fragments'] for c in calls),calls
    assert all(c['source_event']=='LapTimes_4.19.5.4' and c['queue_managed'] and not c['immediate'] for c in calls),calls

def test_requested_self_pace_has_original_history_and_not_an_invented_reference(core):
    raw=warm(core);lap(core,raw,1,2);lap(core,raw,2,102);lap(core,raw,3,202)
    result,words=command(core,'HOWS_MY_SELF_PACE')
    assert words and words!=['acknowledge/no_data'],result
    assert 'lap_times/time_intro' in words,result
    assert command(core,'HOWS_MY_PACE')[1]==['acknowledge/no_data']

def test_race_pace_compares_observed_opponent_sector_histories(core):
    raw=warm(core)
    for n in range(1,6):lap(core,raw,n,2+(n-1)*100,opponents=True)
    result,words=command(core,'HOWS_MY_PACE')
    assert words and words!=['acknowledge/no_data'],result
    assert 'lap_times/need_to_find_a_second' in words,words
    assert all(c['source_event']=='LapTimes_4.19.5.4' and c['folders_resolved'] for c in result['calls']),result
    (HERE/('opponent-pace-'+core.settings['revert_to_legacy_version_of_refactored_code']+'.json')).write_text(json.dumps(result,indent=2)+'\n')
