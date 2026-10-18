"""Original pit-stop event on synthetic AMS2 data; no game inputs or sound devices."""
import hashlib
import json
import sys
import time
from types import SimpleNamespace

import pytest

from ams2season import shm as S
from ams2season.coach.crew_core import Core
from ams2season.coach.crew_mapper import DEFAULTS,snapshot_payload
from ams2season.coach.crew_pits import COMMANDS,FOLDERS,command_for
from ams2season.coach.crew_spotter import ASSETS
from ams2season.coach.telemetry import from_snapshot
from test_crew_chief_damage import raw_state
from test_crew_chief_fuel import mapped,acknowledge,fragments,lap

NATIVE=pytest.mark.skipif(sys.platform!='win32',reason='Original Framework PitStops')


@pytest.fixture
def core(tmp_path,request):
    host=Core(root=tmp_path)
    numbers=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS,__paddock_number_config=numbers,
        __paddock_state_directory=str(tmp_path/'state'))
    host.settings.update(getattr(request,'param',{}))
    host.pit_available=True
    host.start();assert host.ready.wait(10),host.error
    try:yield host
    finally:host.close()


def warm(core,raw=None):
    raw=raw or raw_state()
    mapped(core,raw,0);mapped(core,raw,1)
    assert core.pit_state=='monitoring'
    return raw


def test_original_complete_pit_source_and_build_are_pinned():
    receipt=json.loads((ASSETS/'pit_sources.json').read_text())
    build=json.loads((ASSETS/'mapper_core.build.json').read_text(encoding='utf-8-sig'))
    for name,item in receipt.items():
        assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()==item['sha256']==build['sources'][name]
        assert hashlib.sha256((ASSETS.parents[2]/item['original']).read_bytes()).hexdigest()==item['original_sha256']
    assert (ASSETS/'PitStops.cs').read_bytes()==(ASSETS.parents[2]/receipt['PitStops.cs']['original']).read_bytes()
    assert build['metadata']['pit_speech.json']==hashlib.sha256((ASSETS/'pit_speech.json').read_bytes()).hexdigest()


@pytest.mark.parametrize('command,phrase',[(key,p) for key,phrases in COMMANDS.items() for p in phrases])
def test_original_installed_english_pit_commands(command,phrase):
    assert command_for(phrase.upper()+'?')==command


def test_pit_commands_do_not_invent_pit_menu_control():
    assert all(command_for(p) is None for p in ('set pit speed to 80','add fuel','change tyres','request pitstop'))


@NATIVE
def test_startup_history_is_not_an_occupied_or_mandatory_answer(core):
    mapped(core,raw_state(),0)
    assert core.pit_state=='warming_up'
    assert fragments(core.respond('IS_MY_PIT_BOX_OCCUPIED'))==['acknowledge/no_data']
    assert 'warming up' in core.withheld[0]


@NATIVE
def test_pit_request_exact_original_delay_and_no_cancel_ack_in_ams2(core):
    raw=warm(core)
    raw.mPitSchedule=1
    result=mapped(core,raw,6)
    assert fragments(result['events']['calls'])==['mandatory_pit_stops/pit_stop_requested']
    call=result['events']['calls'][0]
    assert call['immediate'] and call['source_event']=='PitStops_4.19.5.4'
    acknowledge(core,result['events']['calls'])
    assert not mapped(core,raw,7)['events']['calls']
    raw.mPitSchedule=0
    assert not mapped(core,raw,15)['events']['calls']
    raw.mPitSchedule=1
    assert not mapped(core,raw,25)['events']['calls']  # original once-per-lap flag


@NATIVE
def test_starting_with_request_does_not_manufacture_a_new_request(core):
    raw=raw_state();raw.mPitSchedule=1
    for t in (0,1,10):assert not mapped(core,raw,t)['events']['calls']


@NATIVE
def test_original_five_second_request_cooldown_is_strict_even_across_new_lap(core):
    raw=warm(core);raw.mPitSchedule=1
    calls=mapped(core,raw,6)['events']['calls'];acknowledge(core,calls)
    raw.mPitSchedule=0;mapped(core,raw,6.1)
    lap(core,raw,9,50)
    raw.mPitSchedule=1
    assert not mapped(core,raw,11)['events']['calls']  # exactly five seconds
    raw.mPitSchedule=0;mapped(core,raw,11.05)
    raw.mPitSchedule=1
    assert fragments(mapped(core,raw,11.1)['events']['calls'])==['mandatory_pit_stops/pit_stop_requested']


@NATIVE
@pytest.mark.parametrize('schedule,expected',[(0,'acknowledge/no_data'),(1,'acknowledge/no'),(7,'mandatory_pit_stops/pit_stall_occupied')])
def test_occupancy_answer_requires_actual_schedule_evidence(core,schedule,expected):
    raw=raw_state();raw.mPitSchedule=schedule;warm(core,raw)
    assert fragments(core.respond('IS_MY_PIT_BOX_OCCUPIED'))==[expected]
    assert core.pit_data['occupancy_known']==(schedule in (1,7))


@NATIVE
@pytest.mark.parametrize('command,reason',[
    ('WHATS_PITLANE_SPEED_LIMIT',None),('WHAT_ARE_THE_PIT_ACTIONS',None),
    ('HOW_MANY_LAPS_SINCE_PITTING','timestamp'),('DO_I_HAVE_A_MANDATORY_PIT_STOP','mandatory')])
def test_unknown_pit_data_does_not_become_an_invented_answer(core,command,reason):
    raw=raw_state();raw.mEnforcedPitStopLap=-1;warm(core,raw)
    assert core.pit_data['mapped']['PitSpeedLimit']==-1
    assert core.pit_data['mapped']['PitBoxPositionEstimate']==-1
    assert core.pit_data['mapped']['limiter']=='NOT_AVAILABLE'
    assert fragments(core.respond(command))==['acknowledge/no_data']
    if reason:assert any(reason in item for item in core.withheld)


@NATIVE
def test_original_mandatory_stop_question_uses_enforced_lap(core):
    raw=raw_state();raw.mEnforcedPitStopLap=5;warm(core,raw)
    assert core.pit_data['data']['hasMandatoryPitStop']
    assert core.pit_data['data']['pitWindowOpenLap']==5
    calls=core.respond('DO_I_HAVE_A_MANDATORY_PIT_STOP')
    assert fragments(calls)==['mandatory_pit_stops/yes_stop_on_lap','numbers/5']


@NATIVE
def test_confirmed_no_mandatory_stop_uses_original_no(core):
    raw=raw_state();raw.mEnforcedPitStopLap=0;warm(core,raw)
    assert fragments(core.respond('DO_I_HAVE_A_MANDATORY_PIT_STOP'))==['acknowledge/no']


@NATIVE
def test_pit_withdrawal_clears_queued_calls_and_recovery_does_not_make_request(core):
    raw=warm(core);calls=core.respond('WHATS_PITLANE_SPEED_LIMIT');assert calls
    core.pit_available=False
    result=mapped(core,raw,2)
    assert not result['events']['valid'] and core.pit_state=='pit_telemetry_unavailable'
    assert not core.respond('IS_MY_PIT_BOX_OCCUPIED')
    core.pit_available=True;raw.mPitSchedule=1
    assert not mapped(core,raw,10)['events']['calls']
    assert core.pit_state=='warming_up'


@NATIVE
@pytest.mark.parametrize('mode',[S.PIT_MODE_DRIVING_INTO_PITS,S.PIT_MODE_IN_PIT,S.PIT_MODE_DRIVING_OUT_OF_PITS,S.PIT_MODE_IN_GARAGE])
def test_original_mapper_pit_modes_are_preserved(core,mode):
    raw=warm(core);raw.mPitMode=raw.mPitModes[0]=mode
    mapped(core,raw,2)
    assert core.pit_data['mapped']['InPitlane']


@pytest.mark.parametrize('field,value',[
    ('mPitMode',6),('mPitSchedule',8),('mEnforcedPitStopLap',-2),
    ('mSpeed',float('nan')),('mTrackLength',0),('distance',-1),('distance',float('nan'))])
def test_invalid_pit_telemetry_withdraws_without_waiting_for_event_cadence(field,value):
    requests=[]
    core=Core(host=lambda p:requests.append(p) or {'mapped':True,'events':{'calls':[],'valid':[]}})
    raw=raw_state();tick=from_snapshot(raw,0,'pit-gate');sampled=time.perf_counter()-.02
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled,respect_update_interval=True)
    assert requests[-1]['pit_available']
    if field=='distance':raw.mParticipantInfo[0].mCurrentLapDistance=value
    else:setattr(raw,field,value)
    tick=from_snapshot(raw,.01,'pit-gate')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled+.01,respect_update_interval=True)
    assert not core.pit_available
    if field=='mTrackLength' or isinstance(value,float) and value!=value:
        # Complete-snapshot validation rejects these before entering C#.
        assert core.latest is None and not core.valid_ids
    else:assert len(requests)==2 and not requests[-1]['pit_available']


@NATIVE
def test_background_is_reported_as_unmixed_and_resets_with_session(core):
    warm(core)
    assert core.background=={'selected':None,'mixed':False}
    core.reset()
    assert not core.pit_available and not core.pit_data and not core.background


def collect(core,raw,start,end):
    calls=[]
    for i in range(round(start*10),round(end*10)+1):
        result=mapped(core,raw,i/10)
        calls+=result['events']['calls'];acknowledge(core,result['events']['calls'])
    return calls


@NATIVE
def test_approaching_pitlane_gives_generic_speed_warning_without_inventing_limit(core):
    raw=warm(core);raw.mPitMode=raw.mPitModes[0]=S.PIT_MODE_DRIVING_INTO_PITS
    calls=mapped(core,raw,2)['events']['calls']
    assert fragments(calls)==['mandatory_pit_stops/watch_your_pit_speed']
    assert calls[0]['priority']==15 and calls[0]['sound_type']=='CRITICAL_MESSAGE'
    acknowledge(core,calls)
    assert not collect(core,raw,2.1,3)


@NATIVE
@pytest.mark.parametrize('session,stopped,expected',[
    (S.SESSION_RACE,True,True),(S.SESSION_RACE,False,False),(S.SESSION_PRACTICE,True,False)])
def test_stop_complete_requires_race_and_observed_stationary_to_exit_transition(core,session,stopped,expected):
    raw=raw_state();raw.mSessionState=session
    raw.mPitMode=raw.mPitModes[0]=S.PIT_MODE_IN_PIT
    raw.mSpeed=0 if stopped else 20
    warm(core,raw)
    raw.mPitMode=raw.mPitModes[0]=S.PIT_MODE_DRIVING_OUT_OF_PITS
    raw.mSpeed=5
    calls=mapped(core,raw,2)['events']['calls']
    assert ('mandatory_pit_stops/stop_complete_go' in fragments(calls)) is expected
    if expected:
        assert calls[0]['immediate'] and calls[0]['priority']==15


@NATIVE
def test_original_immediate_request_ack_is_retained_until_playback_receipt(core):
    raw=warm(core);raw.mPitSchedule=1
    calls=mapped(core,raw,6)['events']['calls'];assert calls
    assert core.valid_call('core:'+calls[0]['id'])
    raw.mPitSchedule=0;mapped(core,raw,6.1)
    # This original race-branch immediate acknowledgement has no abstractEvent
    # validation; don't change its semantics to those of the deferred branch.
    assert core.valid_call('core:'+calls[0]['id'])
    acknowledge(core,calls);mapped(core,raw,6.2)
    assert not core.valid_call('core:'+calls[0]['id'])


@NATIVE
def test_original_occupied_stall_warning_uses_one_to_two_second_queue_delay(core):
    raw=warm(core);raw.mPitSchedule=7
    assert not mapped(core,raw,2)['events']['calls']
    calls=collect(core,raw,2.1,5)
    assert fragments(calls)==['mandatory_pit_stops/pit_stall_occupied']
    assert not calls[0]['immediate'] and calls[0]['priority']==10
    assert not collect(core,raw,5.1,6)


@NATIVE
def test_original_crew_ready_announces_on_sector_two_to_three(core):
    raw=raw_state();raw.mPitSchedule=1
    raw.mParticipantInfo[0].mCurrentSector=1
    warm(core,raw)
    raw.mParticipantInfo[0].mCurrentSector=2
    assert not mapped(core,raw,2)['events']['calls']
    calls=collect(core,raw,2.1,5)
    assert fragments(calls)==['mandatory_pit_stops/pit_crew_ready']


@NATIVE
def test_mandatory_countdown_question_waits_for_original_race_window_initialisation(core):
    raw=raw_state();raw.mEnforcedPitStopLap=5;raw.mRaceState=S.RACESTATE_NOT_STARTED
    warm(core,raw)
    assert not core.pit_data['data']['pitDataInitialised']
    assert fragments(core.respond('DO_I_HAVE_A_MANDATORY_PIT_STOP'))==['acknowledge/no_data']
    assert any('window is not confirmed' in s for s in core.withheld)


@NATIVE
def test_original_mandatory_window_opening_and_open_are_lap_driven(core):
    raw=raw_state();raw.mEnforcedPitStopLap=5;warm(core,raw)
    lap(core,raw,110,50)  # completed 3
    result=lap(core,raw,220,50)  # completed 4: opens at the end of this lap
    calls=result['events']['calls']+collect(core,raw,220.1,241)
    assert 'mandatory_pit_stops/pit_window_opening' in fragments(calls)
    result=lap(core,raw,330,50)  # completed 5
    calls=result['events']['calls']+collect(core,raw,330.1,351)
    assert 'mandatory_pit_stops/pit_window_open' in fragments(calls)
    assert core.pit_data['data']['inPitWindow']
    assert core.background=={'selected':'dtm_pit_window_open.wav','mixed':False}
    for completed,t in ((6,440),(7,550),(8,660),(9,770)):
        result=lap(core,raw,t,50)
        calls=result['events']['calls']+collect(core,raw,t+.1,t+21)
    assert 'mandatory_pit_stops/pit_window_closed' in fragments(calls)
    assert core.pit_data['data']['mandatoryStopMissed'] and not core.pit_data['data']['inPitWindow']
    assert core.background=={'selected':'dtm_pit_window_closed.wav','mixed':False}
    assert fragments(core.respond('DO_I_HAVE_A_MANDATORY_PIT_STOP'))==['mandatory_pit_stops/missed_stop']


def test_voice_recognition_routes_pit_phrase_using_original_confidence_threshold():
    from ams2season.coach.service import CoachService
    service=CoachService.__new__(CoachService)
    service.buttons=None;service.output='crew_chief';service.audio_enabled=False
    service.talk={'state':'thinking'}
    service.core=SimpleNamespace(waiting_for_driver_ok=False,settings={'minimum_voice_recognition_confidence_system_sre':'.7'})
    outcomes=[{'text':'is my pit box occupied','confidence':v,'detected_speech':True,'problem':None} for v in (.69,.9)]
    service.listener=SimpleNamespace(heard_details=lambda:outcomes)
    replies=[];service._button_reply=lambda *args:replies.append(args)
    service._service_buttons()
    assert replies==[('is my pit box occupied','voice')]


@NATIVE
@pytest.mark.parametrize('fuel,gallons',[('litres',False),('us_gallons',True)])
def test_live_worker_uses_original_pit_reply_and_actual_fuel_unit_preference(tmp_path,monkeypatch,fuel,gallons):
    from ams2season.app import App
    from ams2season.recorder import Recorder
    from ams2season.coach.speech import LocalRadio
    from test_coach_service import wait_until,snapshot_stream
    import ams2season.coach.service as module
    app=App(tmp_path)
    app.recorder.thread=SimpleNamespace(is_alive=lambda:True)
    app.recorder.rec=Recorder(tmp_path/'recordings',sessions=(),log=lambda _:None)
    raw=raw_state();raw.mPitSchedule=7
    app.recorder.rec.step(raw,time.perf_counter())
    played=[]
    monkeypatch.setattr(module,'LocalRadio',lambda voice,**kwargs:LocalRadio(voice,sink=(played.append,lambda:None),effect='off'))
    with snapshot_stream(app,raw):
        service=app.coach
        service.configure({'units':{'fuel':fuel}})
        service.output='paddock';service.audio_enabled=True;service.tts_fallback=False
        try:
            service.start();assert service.core.ready.wait(10),service.core.error
            wait_until(lambda:service.core.pit_state=='monitoring')
            wait_until(lambda:service.core.latest and time.perf_counter()-service.core.latest['at']<.15)
            with service.lock:
                assert service.core._fuel_gallons is gallons
                reply=service._engine_reply('is my pit box occupied','typed')
                assert reply['understood']=='IS_MY_PIT_BOX_OCCUPIED' and 'queued' in reply['response']
                assert service.baseline_pending[-1]['fragments']==['mandatory_pit_stops/pit_stall_occupied']
                assert service.baseline_pending[-1]['source_event']=='PitStops_4.19.5.4'
                assert service._deliver_baseline()
            wait_until(lambda:bool(played))
            status=service.status()
            assert 'PitStops' in status['original_core']['events']
            assert not status['original_core']['full_parity_complete']
            assert not list((tmp_path/'recordings').iterdir())
        finally:service.close()
