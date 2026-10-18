"""Original LapCounter on the live source build, synthetic telemetry; no speakers."""
import hashlib,json,sys
import time
import threading
from types import SimpleNamespace
from pathlib import Path
import pytest
from ams2season import shm as S
from ams2season.coach.crew_core import Core,lap_counter_inputs_available
from ams2season.coach.crew_mapper import DEFAULTS
from ams2season.coach import crew_spotter
from ams2season.coach.telemetry import from_snapshot
from ams2season.coach.crew_lapcounter import FOLDERS
from test_crew_chief_damage import raw_state
from test_crew_chief_fuel import mapped,acknowledge,fragments,lap
from test_crew_chief_position import rank

HERE=Path(__file__).resolve().parents[1]/'diagnostics/cc-lapcounter-20261016'
A=crew_spotter.ASSETS
NATIVE=pytest.mark.skipif(sys.platform!='win32',reason='Original Framework LapCounter')

@pytest.fixture
def core(tmp_path,request):
    host=Core(root=tmp_path);numbers=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS,__paddock_number_config=numbers,__paddock_state_directory=str(tmp_path/'state'),allow_rants='False')
    host.settings.update(getattr(request,'param',{}));host.lap_counter_available=True
    host.start();assert host.ready.wait(10),host.error
    try:yield host
    finally:host.close()

def feed(core,raw,t):
    event=mapped(core,raw,t)['events'];acknowledge(core,event['calls']);return event

def grid():
    raw=raw_state();raw.mRaceState=S.RACESTATE_NOT_STARTED
    for i in range(raw.mNumParticipants):
        raw.mParticipantInfo[i].mLapsCompleted=0;raw.mParticipantInfo[i].mCurrentLap=1
        raw.mRaceStates[i]=S.RACESTATE_NOT_STARTED
    return raw

def green(raw):
    raw.mRaceState=S.RACESTATE_RACING
    for i in range(raw.mNumParticipants):raw.mRaceStates[i]=S.RACESTATE_RACING

def test_original_source_and_live_assembly_are_pinned():
    data=(A/'LapCounter.cs').read_bytes()
    assert data==(HERE.parent/'cc-baseline-next-20261016/LapCounter.cs').read_bytes()
    assert hashlib.sha256(data).hexdigest()=='8d714327666f36eecabefab261f8b4564f9576b4c5af54c07b58d1298fa6b2fa'
    receipt=json.loads((A/'mapper_core.build.json').read_text(encoding='utf-8-sig'))
    for n,digest in receipt['sources'].items():assert hashlib.sha256((A/n).read_bytes()).hexdigest()==digest
    assert receipt['metadata']['lapcounter_folders.json']==hashlib.sha256((A/'lapcounter_folders.json').read_bytes()).hexdigest()

@NATIVE
def test_mid_race_join_does_not_invent_green_flag(core):
    raw=raw_state()
    first=feed(core,raw,0);second=feed(core,raw,1)
    assert first['lap_counter_state']=='warming_up'
    assert second['lap_counter_state']=='monitoring'
    assert not fragments(first['calls']+second['calls'])

@NATIVE
def test_observed_countdown_to_green_preserves_critical_priority_and_once_only(core):
    raw=grid();feed(core,raw,0);before=feed(core,raw,1)
    assert before['lap_counter']['mapped']['phase']=='Countdown'
    green(raw);event=feed(core,raw,2)
    calls=[c for c in event['calls'] if 'lap_counter/green_green_green' in c['fragments']]
    assert len(calls)==1,event
    assert calls[0]['source_event']=='LapCounter_4.19.5.4'
    assert calls[0]['immediate'] and calls[0]['priority']==15 and calls[0]['sound_type']=='CRITICAL_MESSAGE'
    assert 0<calls[0]['expires_s']<=2
    assert not fragments(feed(core,raw,3)['calls'])

@NATIVE
@pytest.mark.parametrize('core',[{'enable_green_light_messages':'False'}],indirect=True)
def test_green_light_preference_is_preserved(core):
    raw=grid();feed(core,raw,0);feed(core,raw,1);green(raw)
    assert 'lap_counter/green_green_green' not in fragments(feed(core,raw,2)['calls'])

@NATIVE
def test_pit_lane_start_does_not_call_green(core):
    raw=grid();raw.mPitMode=raw.mPitModes[0]=2
    feed(core,raw,0);feed(core,raw,1);green(raw)
    assert 'lap_counter/green_green_green' not in fragments(feed(core,raw,2)['calls'])

@NATIVE
@pytest.mark.parametrize('position,remaining,expected',[(1,2,'two_to_go_leading'),(2,2,'two_to_go_top_three'),(1,1,'last_lap_leading'),(2,1,'last_lap_top_three')])
def test_original_new_lap_remaining_calls(core,position,remaining,expected):
    raw=raw_state();rank(raw,position);raw.mLapsInEvent=3+remaining
    feed(core,raw,0);feed(core,raw,1)
    event=lap(core,raw,110,45)['events']
    assert event['lap_counter']['mapped']['IsNewLap']
    assert event['lap_counter']['mapped']['SessionLapsRemaining']==remaining
    assert 'lap_counter/'+expected in fragments(event['calls']),event
    assert not fragments(feed(core,raw,111)['calls'])

@NATIVE
def test_withdrawing_inputs_cancels_pending_lap_calls(core):
    raw=raw_state();feed(core,raw,0);feed(core,raw,1)
    core.lap_counter_available=False
    event=feed(core,raw,2)
    assert event['lap_counter_state']=='lap_counter_telemetry_unavailable'
    core.lap_counter_available=True
    assert feed(core,raw,3)['lap_counter_state']=='warming_up'

def bigger_grid(raw,position):
    raw.mNumParticipants=8
    for i in range(3,8):
        p=raw.mParticipantInfo[i];p.mIsActive=True;p.mName=('Car '+str(i)).encode()
        p.mLapsCompleted=2;p.mCurrentLap=3;p.mCurrentSector=0;p.mCurrentLapDistance=1000+i*40
        raw.mRaceStates[i]=S.RACESTATE_RACING;raw.mSpeeds[i]=35
        raw.mCarNames[i].value=b'Nissan GT-R';raw.mCarClassNames[i].value=b'GT3 Gen 0'
    rank(raw,position)

@NATIVE
@pytest.mark.parametrize('core,american,folder',[({'use_american_terms':'False'},False,'last_lap'),({'use_american_terms':'True'},True,'white_flag_last_lap')],indirect=['core'])
def test_original_last_lap_wording_uses_american_terms_preference(core,american,folder):
    raw=raw_state();bigger_grid(raw,5);raw.mLapsInEvent=4
    # Actual original preference, combined with the original car-class override.
    feed(core,raw,0);feed(core,raw,1)
    event=lap(core,raw,110,45)['events']
    assert 'lap_counter/'+folder in fragments(event['calls']),event
    assert event['lap_counter']['whiteFlagLastLapAnnounced']==american

@NATIVE
@pytest.mark.parametrize('session',[S.SESSION_PRACTICE,S.SESSION_QUALIFY])
def test_practice_and_qualifying_do_not_say_race_laps_or_green(core,session):
    raw=raw_state();raw.mSessionState=session;raw.mLapsInEvent=4
    raw.mEventTimeRemaining=600
    feed(core,raw,0);feed(core,raw,1)
    event=lap(core,raw,110,45)['events']
    assert not any(f.startswith('lap_counter/') for f in fragments(event['calls']))

@NATIVE
def test_fixed_time_race_does_not_get_lap_limited_end_calls(core):
    raw=raw_state();raw.mLapsInEvent=0;raw.mEventTimeRemaining=600
    feed(core,raw,0);feed(core,raw,1);raw.mEventTimeRemaining=490
    event=lap(core,raw,110,45)['events']
    assert event['lap_counter']['mapped']['SessionHasFixedTime']
    assert not any('lap_counter/' in f for f in fragments(event['calls']))

@NATIVE
def test_original_leader_finish_uses_known_installed_name_once(core,tmp_path):
    from ams2season.coach.crew_audio import AudioMetadata
    raw=raw_state();raw.mParticipantInfo[1].mName=b'Ayrton Senna'
    feed(core,raw,0);feed(core,raw,1)
    raw.mParticipantInfo[1].mLapsCompleted=10;raw.mParticipantInfo[1].mCurrentLap=11
    event=feed(core,raw,2)
    assert event['lap_counter']['mapped']['LeaderHasFinishedRace']
    assert fragments(event['calls'])==['senna','lap_counter/has_taken_the_win'],event
    assert not fragments(feed(core,raw,3)['calls'])
    audio=AudioMetadata(root=tmp_path/'audio');audio.start();assert audio.ready.wait(10),audio.error
    try:
        rendered=audio.request('render',fragments=['senna','lap_counter/has_taken_the_win'])
        files=[Path(p['file']) for p in rendered['parts'] if 'file' in p]
        assert len(files)==2 and files[0].parent==audio.sounds.root/'driver_names' and files[0].stem.lower()=='senna'
        assert all(p.is_file() for p in files)
        with pytest.raises(ValueError):audio.request('render',fragments=['../senna'])
        with pytest.raises(ValueError):audio.request('render',fragments=['unregistered-name'])
    finally:audio.close()

@NATIVE
def test_prestart_weather_and_lap_distance_are_real_original_fragments(core):
    raw=grid();raw.mGameState=S.GAME_INGAME_INMENU_TIME_TICKING
    feed(core,raw,0);calls=[]
    for i in range(1,8):calls+=feed(core,raw,i)['calls']
    words=fragments(calls)
    assert 'conditions/track_temp_is' in words and 'conditions/air_temp_is' in words,words
    assert 'numbers/35' in words and 'numbers/25' in words
    assert 'numbers/10' in words and 'battery/laps' in words
    assert all(c['source_event']=='LapCounter_4.19.5.4' for c in calls)

@NATIVE
def test_countdown_purges_pre_grid_messages_on_phase_change(core):
    raw=grid();raw.mGameState=S.GAME_INGAME_INMENU_TIME_TICKING
    feed(core,raw,0)
    event=mapped(core,raw,1)['events'];issued={c['id'] for c in event['calls']};assert issued
    raw.mGameState=S.GAME_INGAME_PLAYING
    countdown=mapped(core,raw,2)['events']
    assert not issued.intersection(countdown['valid'])
    assert 'lap_counter/get_ready' in fragments(countdown['calls'])

@NATIVE
@pytest.mark.parametrize('core',[{'play_pre_lights_messages_until_cancelled':'True'}],indirect=True)
def test_original_until_cancelled_requires_two_throttle_samples_over_point_two(core):
    raw=grid();raw.mGameState=S.GAME_INGAME_INMENU_TIME_TICKING
    feed(core,raw,0);feed(core,raw,1)
    raw.mThrottle=.2;assert 'lap_counter/get_ready' not in fragments(feed(core,raw,2)['calls'])
    raw.mThrottle=.21;assert 'lap_counter/get_ready' not in fragments(feed(core,raw,3)['calls'])
    assert 'lap_counter/get_ready' in fragments(feed(core,raw,4)['calls'])
    assert 'lap_counter/get_ready' not in fragments(feed(core,raw,5)['calls'])

@pytest.mark.parametrize('field,value',[
    ('mThrottle',-.1),('mThrottle',1.1),('mThrottle',float('nan')),
    ('mRaceState',99),('mPitMode',6),('mLapsInEvent',10000),
    ('mSessionAdditionalLaps',101),('mTrackTemperature',151),
    ('mAmbientTemperature',81),('mRainDensity',1.1),('mCloudBrightness',3)])
def test_unknown_or_invalid_actual_lapcounter_channels_are_withheld(field,value):
    raw=raw_state();assert lap_counter_inputs_available(raw)
    setattr(raw,field,value);assert not lap_counter_inputs_available(raw)

@pytest.mark.parametrize('field,value',[('mCurrentSector',3),('mLapsCompleted',10000),('mCurrentLapDistance',float('nan')),('mCurrentLapDistance',6000)])
def test_invalid_opponent_lap_records_are_not_used_for_finish_calls(field,value):
    raw=raw_state();setattr(raw.mParticipantInfo[1],field,value)
    assert not lap_counter_inputs_available(raw)

def test_live_lapcounter_input_loss_bypasses_cadence_and_stale_feed_resets():
    requests=[]
    core=Core(host=lambda p:requests.append(p) or {'mapped':True,'events':{'valid':[],'calls':[]}})
    raw=raw_state();sampled=time.perf_counter()-.03;tick=from_snapshot(raw,0,'lap')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled,respect_update_interval=True)
    assert requests[-1]['lap_counter_available']
    raw.mThrottle=1.1;tick=from_snapshot(raw,.01,'lap')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled+.01,respect_update_interval=True)
    assert len(requests)==2 and not requests[-1]['lap_counter_available']
    assert requests[-1]['position_available'] and requests[-1]['engine_available']
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter()-1)
    assert not core.latest and not core.lap_counter_available and not core.lap_counter_data

def test_pregrid_requires_a_previously_confirmed_same_local_identity():
    requests=[];core=Core(host=lambda p:requests.append(p) or ({'reset':True} if p.get('op')=='reset' else {'mapped':True,'events':{'valid':[],'calls':[]}}))
    raw=grid();raw.mGameState=S.GAME_INGAME_INMENU_TIME_TICKING
    tick=from_snapshot(raw,0,'lap');sampled=time.perf_counter()-.02
    assert not core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled)
    assert not requests and core.state=='withheld_unconfirmed_pregrid_player'
    raw.mGameState=S.GAME_INGAME_PLAYING;tick=from_snapshot(raw,.1,'lap')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter()-.02)
    assert requests[-1]['lap_counter_available']
    raw.mGameState=S.GAME_INGAME_INMENU_TIME_TICKING;tick=from_snapshot(raw,.2,'lap')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter()-.01)
    assert requests[-1]['lap_counter_available']
    assert len([p for p in requests if p.get('op')=='map'])==2

def test_unknown_timed_session_length_withholds_lapcounter_without_inventing_a_duration():
    requests=[];core=Core(host=lambda p:requests.append(p) or {'mapped':True,'events':{'valid':[],'calls':[]}})
    raw=raw_state();raw.mLapsInEvent=0;raw.mEventTimeRemaining=-1
    tick=from_snapshot(raw,0,'lap')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter()-.01)
    assert not requests[-1]['lap_counter_available'] and not requests[-1]['race_time_available']
    assert requests[-1]['position_available']

def test_every_installed_lapcounter_caption_variant_is_preparable_without_live_tts():
    from ams2season.coach.crew_voice import CrewChiefVoice
    voice=CrewChiefVoice()
    phrases=[p for f in FOLDERS for p in voice.phrases(f)]
    assert phrases and any('green, green, green' in p.text.casefold() for p in phrases)
    for f in ('lap_counter/../bad','lap_counter/../../a','strategy/unknown','opponents/unknown'):
        with pytest.raises(ValueError):voice.phrases(f)

def prestart_service():
    from ams2season.coach.service import CoachService
    service=CoachService.__new__(CoachService);service.origin=time.perf_counter();service.output='paddock'
    service.audio_enabled=True
    service.stop_event=threading.Event()
    service.engine=SimpleNamespace(context=SimpleNamespace(t=0,session='race',session_id='grid',reason='menus',active=False,pit_radio=False))
    service.core=SimpleNamespace(latest={'at':time.perf_counter(),'session':'grid'},lap_counter_available=True,
        lap_counter_state='monitoring',lap_counter_data={'mapped':{'phase':'Gridwalk'}},valid_call=lambda n:n=='core:q1')
    return service

def test_only_valid_original_core_calls_can_play_on_the_confirmed_prestart_grid():
    service=prestart_service()
    assert service._baseline_local_valid('grid',{'native_id':'core:q1'})
    assert not service._baseline_local_valid('grid',{'native_id':'core:invalid'})
    assert not service._baseline_local_valid('grid',{'native_id':'penalty:q1'})
    assert not service._baseline_local_valid('grid',{})
    assert not service._local_valid('grid') and not service._local_valid('grid',spotter=True)
    assert not service._baseline_local_valid('other-session',{'native_id':'core:q1'})

@pytest.mark.parametrize('reason',['paused','replay','spectating','driver_unknown','driver_retired','disconnected'])
def test_prestart_exception_never_opens_generic_menus_paused_replay_or_unknown_driver(reason):
    service=prestart_service();service.engine.context.reason=reason
    assert not service._baseline_local_valid('grid',{'native_id':'core:q1'})

@pytest.mark.parametrize('invalid',['stale_mapper','stale_context','other_session','unavailable','warmup','green','stopped'])
def test_prestart_exception_requires_fresh_matching_live_native_state(invalid):
    service=prestart_service()
    if invalid=='stale_mapper':service.core.latest['at']-=1
    if invalid=='stale_context':service.engine.context.t=-1
    if invalid=='other_session':service.core.latest['session']='previous'
    if invalid=='unavailable':service.core.lap_counter_available=False
    if invalid=='warmup':service.core.lap_counter_state='warming_up'
    if invalid=='green':service.core.lap_counter_data['mapped']['phase']='Green'
    if invalid=='stopped':service.stop_event.set()
    assert not service._baseline_local_valid('grid',{'native_id':'core:q1'})
