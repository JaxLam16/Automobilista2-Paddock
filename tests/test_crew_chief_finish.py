"""Real native original finish selection, queue, actual AMS2 struct inputs."""
import sys,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'diagnostics/cc-session-end-20261017'
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import pytest
from types import SimpleNamespace
import threading,hashlib
from ams2season import shm as S
from ams2season.coach import crew_spotter
from ams2season.coach.crew_core import Core
from ams2season.coach.crew_mapper import DEFAULTS
from test_crew_chief_damage import raw_state
from test_crew_chief_fuel import mapped,acknowledge,fragments
from test_crew_chief_position import rank

@pytest.fixture
def core(tmp_path,monkeypatch,request):
    host=Core(root=tmp_path);numbers=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS,__paddock_number_config=numbers,__paddock_state_directory=str(tmp_path/'state'),enable_rants='False',use_sweary_messages='False')
    host.settings.update(getattr(request,'param',{}));host.position_available=True
    host.start();assert host.ready.wait(10),host.error
    try:yield host
    finally:host.close()

def step(core,raw,t):
    event=mapped(core,raw,t)['events'];acknowledge(core,event['calls']);return event

def finish(raw,status=S.RACESTATE_FINISHED):
    raw.mRaceState=status;raw.mRaceStates[raw.mViewedParticipantIndex]=status

@pytest.mark.parametrize('position,expected',[(1,'won_race'),(2,'podium_finish'),(3,'podium_finish')])
def test_winner_and_podium_original_queue(core,position,expected):
    raw=raw_state();rank(raw,position)
    step(core,raw,0);step(core,raw,2);finish(raw)
    result=step(core,raw,63)
    assert fragments(result['calls'])==['lap_counter/'+expected],result
    assert result['calls'][0]['source_event']=='SessionEndMessages_4.19.5.4'
    assert result['calls'][0]['priority']==10 and not result['calls'][0]['immediate']
    assert not step(core,raw,64)['calls']
    assert not step(core,raw,80)['calls']

def test_disqualified_is_never_a_win(core):
    raw=raw_state();rank(raw,1);step(core,raw,0);step(core,raw,2);finish(raw,S.RACESTATE_DISQUALIFIED)
    assert fragments(step(core,raw,65)['calls'])==['penalties/penalty_disqualified']

@pytest.mark.parametrize('status',[S.RACESTATE_DNF,S.RACESTATE_RETIRED,S.RACESTATE_INVALID])
def test_unmapped_dnf_retired_invalid_withheld_without_false_win(core,status):
    raw=raw_state();rank(raw,1);step(core,raw,0);step(core,raw,2);finish(raw,status)
    result=step(core,raw,65)
    assert not result['calls']
    assert result['session_end_state']=='withheld_unmapped_finish_status'

def test_joining_finished_session_does_not_celebrate_a_stale_result(core):
    raw=raw_state();rank(raw,1);finish(raw)
    for t in (0,2,65,80):
        result=step(core,raw,t);assert not result['calls'];assert result['session_end_state']=='withheld_unobserved_finish'

@pytest.mark.parametrize('core',[{'enable_session_end_messages':'False'}],indirect=True)
def test_original_disabled_switch(core):
    raw=raw_state();step(core,raw,0);step(core,raw,2);finish(raw)
    result=step(core,raw,65);assert not result['calls'];assert result['session_end_state']=='disabled_by_preference'

def test_checkered_leader_finish_is_not_player_finish(core):
    raw=raw_state();step(core,raw,0);step(core,raw,2)
    raw.mParticipantInfo[1].mLapsCompleted=raw.mLapsInEvent
    raw.mParticipantInfo[1].mCurrentLap=raw.mLapsInEvent+1
    result=step(core,raw,65)
    assert not any('won_race' in f or 'podium_finish' in f for f in fragments(result['calls']))
    assert result['session_end_state']=='monitoring'

def test_unavailable_position_cannot_be_a_win(core):
    raw=raw_state();step(core,raw,0);step(core,raw,2);finish(raw);core.position_available=False
    result=step(core,raw,65);assert not result['calls'];assert result['session_end_state']=='withheld_position_inputs'

def field(raw,size=6):
    raw.mNumParticipants=size
    for i in range(size):
        p=raw.mParticipantInfo[i];p.mIsActive=True;p.mName=('Driver '+str(i)).encode() if i else b'Jax_Lam'
        p.mRacePosition=i+1;p.mLapsCompleted=2;p.mCurrentLap=3;p.mCurrentSector=0;p.mCurrentLapDistance=1000+i*50
        raw.mCarNames[i].value=b'Nissan GT-R';raw.mCarClassNames[i].value=b'GT3 Gen 0'
        raw.mRaceStates[i]=S.RACESTATE_RACING;raw.mSpeeds[i]=35
    return raw

@pytest.mark.parametrize('position,folder',[(4,'finished_race_good_finish'),(6,'finished_race')])
@pytest.mark.parametrize('core',[{'max_complaints_per_session':'0'}],indirect=True)
def test_other_and_last_original_finish(core,position,folder):
    raw=field(raw_state());rank(raw,position);step(core,raw,0);step(core,raw,2);finish(raw)
    words=fragments(step(core,raw,65)['calls'])
    assert words==['position/p'+str(position),'lap_counter/'+folder],words

def test_multiclass_win_uses_class_rank_and_class_field_not_overall(core):
    raw=field(raw_state());raw.mCarClassNames[1].value=b'LMP2';raw.mCarNames[1].value=b'Oreca 07'
    rank(raw,2);step(core,raw,0);step(core,raw,2);finish(raw)
    result=step(core,raw,65)
    assert result['session_end']['class_position']==1,result['session_end']
    assert result['session_end']['class_cars_at_start']==5,result['session_end']
    assert fragments(result['calls'])==['lap_counter/won_race'],result

def test_original_runtime_guard_uses_previous_laps_not_just_current_clock(core):
    raw=raw_state();rank(raw,1)
    for i in range(raw.mNumParticipants):raw.mParticipantInfo[i].mLapsCompleted=0;raw.mParticipantInfo[i].mCurrentLap=1
    step(core,raw,0);step(core,raw,2);finish(raw)
    result=step(core,raw,3);assert not result['calls']
    assert result['session_end']['handled']

def test_next_session_clears_previous_finish_and_requires_new_observed_running(core):
    raw=raw_state();rank(raw,1);step(core,raw,0);step(core,raw,2);finish(raw)
    assert 'lap_counter/won_race' in fragments(step(core,raw,65)['calls'])
    assert core.reset_mapping()
    result=step(core,raw,70);assert not result['calls'];assert not result['session_end']['handled']

@pytest.mark.parametrize('session,position,expected',[(S.SESSION_QUALIFY,1,'end_of_session_pole'),
    (S.SESSION_QUALIFY,2,'end_of_session'),(S.SESSION_PRACTICE,1,'end_of_session')])
def test_original_qualifying_pole_and_practice_finish(core,session,position,expected):
    raw=raw_state();raw.mSessionState=session;raw.mLapsInEvent=0;raw.mEventTimeRemaining=90
    rank(raw,position);step(core,raw,0);raw.mEventTimeRemaining=25;step(core,raw,65)
    raw.mEventTimeRemaining=0;raw.mSpeed=0
    for i in range(raw.mNumParticipants):raw.mSpeeds[i]=0
    words=[]
    for t in (90,91,92):words+=fragments(step(core,raw,t)['calls'])
    assert 'lap_counter/'+expected in words,words
    assert sum(f=='lap_counter/'+expected for f in words)==1
    assert 'lap_counter/won_race' not in words

@pytest.mark.parametrize('core',[{'__paddock_queue_test':'True'}],indirect=True)
def test_finish_purges_old_regular_calls_but_retains_finish_until_receipt(core):
    raw=raw_state();rank(raw,1);step(core,raw,0);step(core,raw,2)
    result=core._request({'op':'queue_test','actions':[{'action':'enqueue','folder':'conditions/celsius','name':'old-weather'}]})
    old={c['id'] for c in result['calls']};assert old
    finish(raw);result=mapped(core,raw,65)['events']
    assert not old.intersection(result['valid'])
    win=result['calls'][0];assert 'lap_counter/won_race' in win['fragments']
    next_result=mapped(core,raw,66)['events']
    assert win['id'] in next_result['valid'] and not next_result['calls']
    acknowledge(core,[win]);assert win['id'] not in mapped(core,raw,67)['events']['valid']

def finish_service():
    from ams2season.coach.service import CoachService
    s=CoachService.__new__(CoachService);s.origin=time.perf_counter();s.output='paddock';s.audio_enabled=True
    s.stop_event=threading.Event()
    s.engine=SimpleNamespace(context=SimpleNamespace(t=0,session='race',session_id='finish',reason='finished',active=False,pit_radio=False,
        facts={'game_state':S.GAME_INGAME_PLAYING}))
    s.core=SimpleNamespace(latest={'at':time.perf_counter(),'session':'finish','state':{'phase':'Finished'},'game_state':S.GAME_INGAME_PLAYING},
        lap_counter_available=False,lap_counter_state='inactive_session_phase',lap_counter_data={},
        session_end_state='finish_observed',session_end_data={'handled':True,'observed_running':True,'phase':'Finished'},
        valid_call=lambda n:n=='core:q1')
    return s

def test_finish_gate_only_admits_original_native_finish_and_not_coaching_or_spotting():
    s=finish_service();call={'native_id':'core:q1','source_event':'SessionEndMessages_4.19.5.4'}
    assert s._baseline_local_valid('finish',call)
    assert not s._local_valid('finish') and not s._local_valid('finish',spotter=True)
    for changed in ({'native_id':'events:q1'},{'native_id':'core:invalid'},{'source_event':'LapCounter_4.19.5.4'}):
        assert not s._baseline_local_valid('finish',{**call,**changed})
    assert not s._baseline_local_valid('other-session',call)

def test_native_finished_phase_blocks_coach_and_spotter_when_participant_state_lags():
    s=finish_service();s.engine.context.active=True;s.engine.context.reason='active'
    assert not s._local_valid('finish') and not s._local_valid('finish',spotter=True)
    assert s._baseline_local_valid('finish',{'native_id':'core:q1','source_event':'SessionEndMessages_4.19.5.4'})
    assert not s._baseline_local_valid('finish',{'native_id':'core:q1','source_event':'Position_4.19.5.4'})

@pytest.mark.parametrize('game_state',[S.GAME_FRONT_END,S.GAME_INGAME_PAUSED,S.GAME_INGAME_REPLAY,S.GAME_FRONT_END_REPLAY])
def test_old_fresh_finish_receipt_cannot_admit_new_frontend_pause_or_replay_tick(game_state):
    s=finish_service();s.engine.context.reason='menus';s.engine.context.facts['game_state']=game_state
    assert not s._baseline_local_valid('finish',{'native_id':'core:q1','source_event':'SessionEndMessages_4.19.5.4'})

def test_confirmed_native_finished_time_ticking_menu_is_allowed():
    s=finish_service();s.engine.context.reason='menus'
    s.engine.context.facts['game_state']=s.core.latest['game_state']=S.GAME_INGAME_INMENU_TIME_TICKING
    assert s._baseline_local_valid('finish',{'native_id':'core:q1','source_event':'SessionEndMessages_4.19.5.4'})

@pytest.mark.parametrize('invalid',['paused','replay','spectating','driver_unknown','disconnected','stale_mapper',
    'stale_context','other_session','not_finished','unobserved','disabled','stopped'])
def test_finish_gate_cannot_open_stale_or_unrelated_playback(invalid):
    s=finish_service()
    if invalid in ('paused','replay','spectating','driver_unknown','disconnected'):s.engine.context.reason=invalid
    if invalid=='stale_mapper':s.core.latest['at']-=1
    if invalid=='stale_context':s.engine.context.t=-1
    if invalid=='other_session':s.core.latest['session']='other'
    if invalid=='not_finished':s.core.session_end_data['phase']='Checkered'
    if invalid=='unobserved':s.core.session_end_data['observed_running']=False
    if invalid=='disabled':s.core.session_end_state='disabled_by_preference'
    if invalid=='stopped':s.stop_event.set()
    assert not s._baseline_local_valid('finish',{'native_id':'core:q1','source_event':'SessionEndMessages_4.19.5.4'})

def test_original_finish_source_and_build_are_pinned():
    A=crew_spotter.ASSETS;original=ROOT/'diagnostics/cc-timing-legacy-prep-20261017/dependency-IL-source/CrewChiefV4.Events.SessionEndMessages.cs'
    assert (A/'SessionEndMessages.cs').read_bytes()==original.read_bytes()
    receipt=json.loads((A/'mapper_core.build.json').read_text(encoding='utf-8-sig'))
    for f,h in receipt['sources'].items():assert hashlib.sha256((A/f).read_bytes()).hexdigest()==h
    assert receipt['metadata']['session_end_folders.json']==hashlib.sha256((A/'session_end_folders.json').read_bytes()).hexdigest()

def test_finish_folders_are_prepared_for_selected_voice_without_live_synthesis():
    from ams2season.coach.crew_finish import FOLDERS
    from ams2season.coach.crew_voice import CrewChiefVoice
    voice=CrewChiefVoice()
    for folder in FOLDERS:
        assert voice.phrases(folder),folder
    with pytest.raises(ValueError):voice.phrases('lap_counter/../won_race')

def test_live_worker_finish_reaches_original_queue_selected_voice_and_silent_receipt(tmp_path,monkeypatch):
    from ams2season.app import App
    from ams2season.recorder import Recorder
    from ams2season.coach.speech import LocalRadio
    from ams2season.coach.packs import PackStore
    from test_coach_service import wait_until,snapshot_stream
    import ams2season.coach.service as module
    app=App(tmp_path);app.recorder.thread=SimpleNamespace(is_alive=lambda:True)
    app.recorder.rec=Recorder(tmp_path/'recordings',sessions=(),log=lambda _:None)
    raw=raw_state();rank(raw,1)
    service=app.coach;service.output='paddock';service.audio_enabled=True;service.tts_fallback=False
    selected=json.loads((ROOT/'private_coach/settings.json').read_text())['voice_pack']
    service.voice_selection=selected;service.voice=PackStore(ROOT).cache(selected)
    service.pack_store.installed=lambda:PackStore(ROOT).installed()
    played=[]
    monkeypatch.setattr(module,'LocalRadio',lambda voice,**kwargs:LocalRadio(voice,sink=(played.append,lambda:None),effect='off'))
    try:
        with snapshot_stream(app,raw):
            service.start();assert service.core.ready.wait(10),service.core.error
            wait_until(lambda:service.core.session_end_state=='monitoring',10)
            finish(raw)
            wait_until(lambda:service.core.session_end_state=='finish_observed',5)
            def events():return list(service.engine.radio.log.events)
            wait_until(lambda:any(e['state']=='radio_closed' and str(e.get('id','')).startswith('cc-events:core:') for e in events()),10)
            requested=[e for e in events() if e['state']=='crew_chief_requested' and e.get('source')=='SessionEndMessages_4.19.5.4']
            assert len(requested)==1 and requested[0]['fragments']==['lap_counter/won_race'],requested
            sources=[e.get('voice') for e in events() if e['state']=='radio_playing']
            assert sources and all(v in ('voice_pack','crew_chief_recording','voice_pack_and_crew_chief_recording') for v in sources),sources
            assert service.engine.context.reason=='finished'
            assert played and not service.core.error,service.core.error
        service.stop()
        assert not list((tmp_path/'recordings').iterdir())
    finally:service.close()
