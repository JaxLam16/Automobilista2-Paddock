"""Unchanged original Position on synthetic multi-car telemetry; silent playback."""
import hashlib,json,sys,time
from types import SimpleNamespace
import pytest

from ams2season import shm as S
from ams2season.coach.crew_core import Core,position_inputs_available
from ams2season.coach.crew_mapper import DEFAULTS
from ams2season.coach.crew_position import COMMANDS,FOLDERS,command_for
from ams2season.coach.crew_spotter import ASSETS
from ams2season.coach.telemetry import from_snapshot
from test_crew_chief_damage import raw_state
from test_crew_chief_fuel import mapped,acknowledge,fragments,lap

NATIVE=pytest.mark.skipif(sys.platform!='win32',reason='Original Framework Position')

@pytest.fixture
def core(tmp_path,request):
    host=Core(root=tmp_path)
    numbers=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS,__paddock_number_config=numbers,
        __paddock_state_directory=str(tmp_path/'state'))
    host.settings.update(allow_rants='False',frequency_of_overtaking_messages='9',frequency_of_being_overtaken_messages='9')
    host.settings.update(getattr(request,'param',{}))
    host.position_available=True
    host.start();assert host.ready.wait(10),host.error
    try:yield host
    finally:host.close()

def warm(core,raw=None):
    raw=raw or raw_state()
    mapped(core,raw,0);mapped(core,raw,1)
    assert core.position_state=='monitoring'
    return raw

def rank(raw,position):
    raw.mParticipantInfo[0].mRacePosition=position
    for i,p in enumerate([p for p in range(1,raw.mNumParticipants+1) if p!=position],1):
        raw.mParticipantInfo[i].mRacePosition=p

def through(core,raw,start,end):
    calls=[]
    for i in range(round(start*10),round(end*10)+1):
        event=mapped(core,raw,i/10)['events'];calls+=event['calls'];acknowledge(core,event['calls'])
    return calls

def test_complete_source_and_installed_phrases_are_pinned():
    receipt=json.loads((ASSETS/'position_sources.json').read_text())['Position.cs']
    original=(ASSETS.parents[2]/receipt['original']).read_bytes();source=(ASSETS/'Position.cs').read_bytes()
    assert source==original and hashlib.sha256(source).hexdigest()==receipt['sha256']==receipt['original_sha256']
    build=json.loads((ASSETS/'mapper_core.build.json').read_text(encoding='utf-8-sig'))
    assert build['sources']['Position.cs']==receipt['sha256']
    for name in ('position_speech.json','position_folders.json'):assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()==build['metadata'][name]
    for key,phrases in COMMANDS.items():
        for p in phrases:assert command_for(p.upper()+'?')==key
    assert command_for("what's my gap") is None

@NATIVE
def test_first_valid_sample_does_not_invent_previous_position_history(core):
    mapped(core,raw_state())
    assert core.position_state=='warming_up'
    assert fragments(core.respond('WHATS_MY_POSITION'))==['acknowledge/no_data']

@NATIVE
@pytest.mark.parametrize('position,expected',[(1,'position/leading'),(2,'position/p2'),(3,'position/p3')])
def test_original_position_reply_uses_the_measured_class_rank(core,position,expected):
    raw=raw_state();rank(raw,position);warm(core,raw)
    calls=core.respond('WHATS_MY_POSITION')
    assert expected in fragments(calls)
    assert all(c['source_event']=='Position_4.19.5.4' for c in calls)

@NATIVE
@pytest.mark.parametrize('session',[S.SESSION_PRACTICE,S.SESSION_QUALIFY,S.SESSION_RACE])
def test_solo_position_uses_original_one_car_guard_and_is_not_gap_evidence(core,session):
    raw=raw_state();raw.mSessionState=session;raw.mNumParticipants=1;rank(raw,1)
    for i in (1,2):raw.mParticipantInfo[i].mIsActive=False
    warm(core,raw)
    assert core.position_data['mapped']['opponents']==0
    assert core.position_data['data']['currentPosition']==1
    assert not core.position_data['data']['opponentKeyForCarWeJustPassed']
    assert fragments(core.respond('WHATS_MY_POSITION'))==['position/leading']

@NATIVE
def test_expected_finish_is_not_fabricated_from_ams2_position(core):
    warm(core)
    assert core.position_data['mapped']['expected_finish']=={'Item1':-1,'Item2':-1}
    assert fragments(core.respond('WHATS_MY_EXPECTED_FINISH_POSITION'))==['acknowledge/no_data']

@NATIVE
def test_invalid_position_availability_withdraws_queued_call_and_recovery_warms(core):
    raw=warm(core);calls=core.respond('WHATS_MY_POSITION');assert calls
    core.position_available=False;mapped(core,raw,2)
    assert not core.valid_ids and core.position_state=='position_telemetry_unavailable'
    assert not core.respond('WHATS_MY_POSITION')
    core.position_available=True;mapped(core,raw,3)
    assert core.position_state=='warming_up'
    assert fragments(core.respond('WHATS_MY_POSITION'))==['acknowledge/no_data']
    acknowledge(core,core.respond('WHATS_MY_POSITION'));mapped(core,raw,4)
    assert core.position_state=='monitoring'

@NATIVE
def test_class_position_comes_from_original_multiclass_mapper(core):
    raw=raw_state();raw.mCarClassNames[1].value=b'LMP2'
    warm(core,raw)
    assert core.position_data['mapped']['OverallPosition']==2
    assert core.position_data['mapped']['ClassPosition']==1
    assert 'position/leading' in fragments(core.respond('WHATS_MY_POSITION'))

def grid_start(core,n=8,start=2):
    raw=raw_state();raw.mNumParticipants=n;raw.mRaceState=S.RACESTATE_NOT_STARTED
    for i in range(n):
        p=raw.mParticipantInfo[i];p.mIsActive=True
        if i>=3:p.mName=('Grid '+str(i)).encode()
        p.mLapsCompleted=0;p.mCurrentLap=1;p.mCurrentSector=0;p.mCurrentLapDistance=1000+i*25
        raw.mRaceStates[i]=S.RACESTATE_NOT_STARTED;raw.mSpeeds[i]=35
        raw.mCarNames[i].value=b'Nissan GT-R';raw.mCarClassNames[i].value=b'GT3 Gen 0'
    rank(raw,start);warm(core,raw)
    raw.mRaceState=S.RACESTATE_RACING
    for i in range(n):raw.mRaceStates[i]=S.RACESTATE_RACING
    mapped(core,raw,2)
    assert core.position_data['mapped']['JustGoneGreen']
    return raw

@NATIVE
@pytest.mark.parametrize('finish,expected',[(1,'good_start'),(6,'bad_start'),(8,'terrible_start')])
def test_original_start_feedback_preserves_random_30_to_49_second_threshold(core,finish,expected):
    raw=grid_start(core);rank(raw,finish)
    mapped(core,raw,3)
    wait=core.position_data['data']['startMessageTime'];assert 30<=wait<50
    assert not any('start' in f for f in fragments(mapped(core,raw,2+wait)['events']['calls']))
    calls=mapped(core,raw,2+wait+.1)['events']['calls']
    assert 'position/'+expected in fragments(calls)
    assert not through(core,raw,2+wait+.2,2+wait+.4)

@NATIVE
@pytest.mark.parametrize('core',[{'enable_race_start_messages':'False'}],indirect=True)
def test_original_race_start_preference_is_respected(core):
    raw=grid_start(core);rank(raw,1)
    assert not through(core,raw,3,55)

@NATIVE
def test_original_last_reply_requires_observed_starting_field_size(core):
    raw=grid_start(core);rank(raw,8);mapped(core,raw,3)
    assert fragments(core.respond('WHATS_MY_POSITION'))==['position/last']


def close_history(core,being_passed=False):
    raw=raw_state();raw.mSplitTimeAhead=raw.mSplitTimeBehind=.8
    if being_passed:rank(raw,1)
    warm(core,raw)
    for i in range(2,20):
        event=mapped(core,raw,i*1.1)['events'];acknowledge(core,event['calls'])
    assert core.position_data['gap_samples_behind' if being_passed else 'gap_samples_ahead']>=11
    return raw

def candidate(core,being_passed=False):
    raw=close_history(core,being_passed)
    rank(raw,2 if being_passed else 1)
    key='opponentKeyForCarThatJustPassedUs' if being_passed else 'opponentKeyForCarWeJustPassed'
    for i in range(220,241):
        t=i/10;event=mapped(core,raw,t)['events'];acknowledge(core,event['calls'])
        if core.position_data['data'][key]:return raw,t
    raise AssertionError('Original event did not recognise the settled pass candidate: '+str(core.position_data))

@NATIVE
@pytest.mark.parametrize('flag',[6,7])
def test_observed_ams2_yellow_reaches_original_three_second_clean_pass_gate(core,flag):
    raw=close_history(core);raw.mHighestFlagColour=flag
    mapped(core,raw,21.1)
    assert core.position_data['mapped']['position_yellow']
    raw.mHighestFlagColour=1;mapped(core,raw,21.2)
    rank(raw,1)
    calls=through(core,raw,22,28)
    assert 'position/overtaking' not in fragments(calls)
    assert not core.position_data['data']['lastOvertakeWasClean']


@NATIVE
@pytest.mark.parametrize('being_passed,expected',[(False,'overtaking'),(True,'being_overtaken')])
def test_original_completed_pass_calls_wait_four_seconds_and_report_before_seven(core,being_passed,expected):
    raw,t=candidate(core,being_passed)
    assert not through(core,raw,t+.1,t+3.8)
    calls=through(core,raw,t+3.9,t+4.5)
    assert fragments(calls)==['position/'+expected]
    assert calls[0]['priority']==10 and calls[0]['source_event']=='Position_4.19.5.4'
    assert not through(core,raw,t+4.6,t+5)


@NATIVE
@pytest.mark.parametrize('reason',['invalid_lap','pits','speed_difference'])
def test_original_pass_is_abandoned_when_completion_conditions_fail(core,reason):
    raw,t=candidate(core)
    if reason=='invalid_lap':raw.mLapInvalidated=True
    if reason=='pits':raw.mPitMode=raw.mPitModes[0]=S.PIT_MODE_DRIVING_INTO_PITS
    if reason=='speed_difference':raw.mSpeed=100
    calls=through(core,raw,t+.1,t+5)
    assert 'position/overtaking' not in fragments(calls)
    assert not core.position_data['data']['opponentKeyForCarWeJustPassed']


@NATIVE
def test_original_just_the_facts_preference_suppresses_pass_praise(tmp_path):
    # A separate actual host verifies the original global setting, no event edits.
    host=Core(root=tmp_path)
    numbers=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS,__paddock_number_config=numbers,__paddock_state_directory=str(tmp_path/'state'),
        just_the_facts='True',frequency_of_overtaking_messages='9',frequency_of_being_overtaken_messages='9')
    host.position_available=True;host.start();assert host.ready.wait(10),host.error
    try:
        raw=raw_state();raw.mSplitTimeAhead=raw.mSplitTimeBehind=.8;warm(host,raw)
        for i in range(2,20):mapped(host,raw,i*1.1)
        assert host.position_data['gap_samples_ahead']==0
        rank(raw,1)
        assert not through(host,raw,22,29)
    finally:host.close()

@NATIVE
def test_original_queued_start_validation_checks_current_position(core):
    raw=grid_start(core);rank(raw,6)
    mapped(core,raw,3);wait=core.position_data['data']['startMessageTime']
    calls=mapped(core,raw,2+wait+.1)['events']['calls'];assert 'position/bad_start' in fragments(calls)
    call=calls[0];assert core.valid_call('core:'+call['id'])
    rank(raw,2);mapped(core,raw,2+wait+.2)
    assert not core.valid_call('core:'+call['id'])

@pytest.mark.parametrize('invalid',['duplicate_rank','zero_rank','duplicate_name','missing_name','missing_car','bad_speed','bad_gap','bad_flag','too_many'])
def test_ambiguous_or_missing_actual_grid_data_is_withheld(invalid):
    raw=raw_state();assert position_inputs_available(raw)
    if invalid=='duplicate_rank':raw.mParticipantInfo[1].mRacePosition=2
    if invalid=='zero_rank':raw.mParticipantInfo[1].mRacePosition=0
    if invalid=='duplicate_name':raw.mParticipantInfo[1].mName=raw.mParticipantInfo[0].mName
    if invalid=='missing_name':raw.mParticipantInfo[1].mName=b''
    if invalid=='missing_car':raw.mCarNames[1].value=b'';raw.mCarClassNames[1].value=b''
    if invalid=='bad_speed':raw.mSpeeds[1]=-1
    if invalid=='bad_gap':raw.mSplitTimeAhead=float('nan')
    if invalid=='bad_flag':raw.mHighestFlagColour=12
    if invalid=='too_many':raw.mNumParticipants=S.STORED_PARTICIPANTS_MAX+1
    assert not position_inputs_available(raw)

def test_inactive_grid_slots_and_unknown_gap_sentinels_do_not_invent_opponents():
    raw=raw_state();raw.mParticipantInfo[2].mIsActive=False
    raw.mParticipantInfo[2].mName=b'';raw.mParticipantInfo[2].mRacePosition=0
    raw.mSplitTimeAhead=raw.mSplitTimeBehind=-1
    assert position_inputs_available(raw)

def test_live_invalid_rank_bypasses_event_cadence_and_stale_data_withdraws_history():
    requests=[];core=Core(host=lambda p:requests.append(p) or {'mapped':True,'events':{'valid':[],'calls':[]}})
    raw=raw_state();sampled=time.perf_counter()-.02;tick=from_snapshot(raw,0,'pos')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled,respect_update_interval=True)
    assert requests[-1]['position_available']
    raw.mParticipantInfo[1].mRacePosition=2
    tick=from_snapshot(raw,.01,'pos')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled+.01,respect_update_interval=True)
    assert len(requests)==2 and not requests[-1]['position_available']
    assert requests[-1]['weather_available'] and requests[-1]['fuel_available']
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter()-1)
    assert not core.latest and not core.position_available and not core.position_data

def test_voice_question_uses_the_original_recognition_confidence():
    from ams2season.coach.service import CoachService
    service=CoachService.__new__(CoachService)
    service.buttons=None;service.output='crew_chief';service.audio_enabled=False
    service.talk={'state':'thinking'};service.core=SimpleNamespace(waiting_for_driver_ok=False,settings={'minimum_voice_recognition_confidence_system_sre':'.7'})
    service.listener=SimpleNamespace(heard_details=lambda:[{'text':"what's my position",'confidence':p,'detected_speech':True,'problem':None} for p in (.69,.9)])
    replies=[];service._button_reply=lambda *args:replies.append(args)
    service._service_buttons();assert replies==[("what's my position",'voice')]
