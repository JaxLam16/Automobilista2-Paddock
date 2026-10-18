"""Original live Timings with complete synthetic AMS2 snapshots; no game or speakers."""
import hashlib,json,sys,time,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'diagnostics/cc-timing-prep-20261016';A=ROOT/'ams2season/assets/crew_chief'
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import pytest
from ams2season import shm as S
from ams2season.coach.crew_core import Core
from ams2season.coach.crew_mapper import DEFAULTS,snapshot_payload
from ams2season.coach import crew_spotter
from test_crew_chief_damage import raw_state
from test_crew_chief_mapper import TICKS


@pytest.fixture
def core(tmp_path,monkeypatch,request):
    host=Core(root=tmp_path);number=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS,__paddock_number_config=number,__paddock_state_directory=str(tmp_path/'state'),allow_rants='False',enable_driver_names='False')
    host.settings.update(getattr(request,'param',{}));host.timings_available=True;host.start()
    assert host.ready.wait(10),host.error
    try:yield host
    finally:host.close()


def step(core,raw,t=0,available=True):
    core.timings_available=available
    result=core._request({'op':'map','raw':snapshot_payload(raw),'ticks':TICKS+round(t*10000000),'timings_available':available})
    assert result and not result.get('error') and result.get('mapped'),result or core.error
    core._events(result['events']);return result['events']


def ack(core,result):
    for call in result['calls']:core.acknowledge(call['id'])


def warm(core,raw=None):
    raw=raw or raw_state();raw.mSplitTimeAhead=5;raw.mSplitTimeBehind=7
    for t in (0,1,2):ack(core,step(core,raw,t))
    return raw


def command(core,name):
    result=core._request({'op':'command','command':name,'ack':core.acknowledged[:]})
    assert result and not result.get('error'),result or core.error
    ack(core,result);return [f for c in result['calls'] for f in c['fragments']]


def test_original_sources_are_unchanged_and_all_candidate_sources_pinned():
    receipt=json.loads((A/'mapper_core.build.json').read_text(encoding='utf-8-sig'))
    for name in ('Timings.cs','OpponentMessages.cs'):
        assert (A/name).read_bytes()==(HERE/name).read_bytes()
    for name,digest in receipt['sources'].items():assert hashlib.sha256((A/name).read_bytes()).hexdigest()==digest


def test_actual_game_splits_and_original_gap_questions(core):
    raw=warm(core);state=step(core,raw,3)
    assert state['timings_state']=='monitoring'
    assert state['timings']['mapped']['TimeDeltaFront']==5
    assert state['timings']['mapped']['TimeDeltaBehind']==7
    assert command(core,'WHATS_MY_GAP_IN_FRONT') in (['insert_pause:50','numbers/5point0'],['insert_pause:50','numbers/5point0seconds'])
    assert command(core,'WHATS_MY_GAP_BEHIND') in (['insert_pause:50','numbers/7point0'],['insert_pause:50','numbers/7point0seconds'])


def test_no_pair_yet_and_zero_gap_return_original_no_data(core):
    raw=raw_state();step(core,raw)
    assert command(core,'WHATS_MY_GAP_IN_FRONT')==['acknowledge/no_data']
    step(core,raw,1)
    assert command(core,'WHATS_MY_GAP_IN_FRONT')==['acknowledge/no_data']


@pytest.mark.parametrize('phase',[S.SESSION_PRACTICE,S.SESSION_QUALIFY])
def test_racing_gap_question_does_not_invent_a_practice_or_qualifying_gap(core,phase):
    raw=raw_state();raw.mSessionState=phase;warm(core,raw)
    assert command(core,'WHATS_MY_GAP_IN_FRONT')==['acknowledge/no_data']


@pytest.mark.parametrize('position,positions,question,folder',[
    (1,(1,2,3),'WHATS_MY_GAP_IN_FRONT','position/leading'),
    (3,(3,1,2),'WHATS_MY_GAP_BEHIND','position/last')])
def test_leader_and_last_place_use_original_position_words_after_observed_start(core,position,positions,question,folder):
    raw=raw_state();raw.mRaceState=S.RACESTATE_NOT_STARTED
    for i in range(raw.mNumParticipants):
        raw.mParticipantInfo[i].mRacePosition=positions[i]
        raw.mParticipantInfo[i].mLapsCompleted=0;raw.mParticipantInfo[i].mCurrentLap=1
        raw.mRaceStates[i]=S.RACESTATE_NOT_STARTED
    for t in (0,1):ack(core,step(core,raw,t))
    raw.mRaceState=S.RACESTATE_RACING
    for i in range(raw.mNumParticipants):raw.mRaceStates[i]=S.RACESTATE_RACING
    for t in (2,3):ack(core,step(core,raw,t))
    assert command(core,question)==[folder]


def test_unsupported_corner_comparison_and_unlearned_track_delta_are_no_data(core):
    warm(core)
    assert command(core,'WHERE_AM_I_FASTER')==['acknowledge/no_data']
    assert command(core,'WHERE_AM_I_SLOWER')==['acknowledge/no_data']
    assert command(core,'WHATS_MY_GAP_IN_FRONT_ON_TRACK')==['acknowledge/no_data']


def test_disabled_timing_sample_clears_state_and_requires_recovery_pair(core):
    raw=warm(core);command(core,'WHATS_MY_GAP_IN_FRONT')
    assert step(core,raw,3,False)['timings_state']=='timing_telemetry_unavailable'
    assert step(core,raw,4)['timings_state']=='warming_up'
    assert command(core,'WHATS_MY_GAP_IN_FRONT')==['acknowledge/no_data']
    assert step(core,raw,5)['timings']['fields']['gapInFrontAtLastReport']==-1


@pytest.mark.parametrize('field,question',[('mSplitTimeAhead','WHATS_MY_GAP_IN_FRONT'),('mSplitTimeBehind','WHATS_MY_GAP_BEHIND')])
def test_unavailable_negative_game_split_cannot_become_a_one_second_gap(core,field,question):
    raw=warm(core);setattr(raw,field,-1)
    step(core,raw,3)
    assert command(core,question)==['acknowledge/no_data']


@pytest.mark.parametrize('core',[{'revert_to_legacy_version_of_refactored_code':'True'}],indirect=True)
def test_legacy_preference_selects_original_legacy_event_instead_of_modern_timings(core):
    raw=warm(core)
    state=step(core,raw,3)
    assert state['timings_state']=='monitoring' and state['timings']['mode']=='legacy'
    assert command(core,'WHATS_MY_GAP_IN_FRONT') in (['insert_pause:50','numbers/5point0'],['insert_pause:50','numbers/5point0seconds'])


def motion(core,seconds=25):
    raw=raw_state();raw.mSplitTimeAhead=3;raw.mSplitTimeBehind=8;raw.mTrackLength=1000
    raw.mTrackLocation=b'PaddockTimingFixture';raw.mTrackVariation=b'PaddockTimingFixture'
    raw.mSpeed=raw.mSpeeds[0]=40
    calls=[]
    for tick in range(seconds*5+1):
        t=tick/5
        raw.mSplitTimeAhead=3+.01*t
        for i,offset in enumerate((200,320,0)):
            dist=2000+offset+40*t;p=raw.mParticipantInfo[i]
            p.mCurrentLapDistance=dist%1000;p.mLapsCompleted=int(dist//1000);p.mCurrentLap=p.mLapsCompleted+1
            p.mCurrentSector=int(p.mCurrentLapDistance/1000*3);raw.mSpeeds[i]=40
        result=step(core,raw,t);calls+=result['calls'];ack(core,result)
    return raw,calls


@pytest.mark.parametrize('name,seconds',[('WHATS_MY_GAP_IN_FRONT_ON_TRACK',3),('WHATS_MY_GAP_BEHIND_ON_TRACK',5),('WHATS_MY_GAP_TO_LEADER',3)])
def test_track_and_leader_gaps_use_actual_original_delta_history(core,name,seconds):
    motion(core)
    words=command(core,name)
    assert words and words!=['acknowledge/no_data']
    values=[float(m.group(1)+'.'+(m.group(2) or '0')) for f in words
            if (m:=re.fullmatch(r'numbers/(\d+)(?:point(\d+))?(?:seconds)?',f))]
    assert any(abs(v-seconds)<.25 for v in values),words


@pytest.mark.parametrize('core',[{'frequency_of_gap_ahead_reports':'10','frequency_of_gap_behind_reports':'0','gap_message_randomness':'1'}],indirect=True)
def test_original_automatic_gap_message_uses_shared_queue_and_reputation_is_empty_in_ams2(core):
    raw,calls=motion(core,90)
    words=[f for c in calls for f in c['fragments']]
    assert any(f.startswith('timings/') for f in words),calls
    assert all(c['source_event']=='Timings_4.19.5.4' for c in calls)
    assert not any('reputation' in f for f in words)
