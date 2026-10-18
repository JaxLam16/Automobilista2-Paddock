"""App routing, evidence gates and duplicate-baseline ownership."""
import time
from types import SimpleNamespace as NS

import pytest

from ams2season.coach.crew_core import lap_time_inputs_available
from ams2season.coach.crew_laptimes import COMMANDS,command_for
from ams2season.coach.engine import CoachEngine
from ams2season.coach.service import CoachService
from test_crew_chief_laptimes import core,raw_laps,step,warm,lap
from test_coach_call_controls import controls


def test_every_installed_phrase_and_punctuation_routes_to_original_owner():
    assert len(COMMANDS)==7
    for command,phrases in COMMANDS.items():
        for phrase in phrases:
            assert command_for(phrase.upper()+'?!')==command
    assert command_for('invent a target lap for me') is None


@pytest.mark.parametrize('field,index,value',[
    ('mLastLapTime',None,float('nan')),('mBestLapTime',None,float('inf')),
    ('mCurrentSector1Times',0,float('nan')),('mCurrentSector2Times',1,-2),
    ('mCurrentSector3Times',2,90000),('mLastLapTimes',1,-10),('mFastestLapTimes',2,float('inf'))])
def test_bad_timing_input_is_unavailable_instead_of_a_fabricated_history(field,index,value):
    raw=raw_laps();assert lap_time_inputs_available(raw)
    if index is None:setattr(raw,field,value)
    else:getattr(raw,field)[index]=value
    assert not lap_time_inputs_available(raw)


def test_live_bridge_sets_receives_and_resets_lap_state(core):
    from ams2season.coach.telemetry import from_snapshot
    raw=raw_laps();tick=from_snapshot(raw,0,'lap-bridge');player=tick.player('Jax_Lam')
    core.feed_snapshot(raw,tick,player,time.perf_counter())
    assert core.lap_times_available and core.lap_times_state=='warming_up'
    core.feed_snapshot(raw,tick,player,time.perf_counter())
    assert core.lap_times_state=='monitoring'
    assert core.respond('WHAT_WAS_MY_LAST_LAP_TIME')[0]['fragments']==['acknowledge/no_data']
    core.latest['at']-=1
    assert core.respond('WHAT_WAS_MY_LAST_LAP_TIME')==[]
    core.reset()
    assert not core.lap_times_available and core.lap_times_data=={}


def test_actual_service_routes_lap_question_with_requested_origin(core):
    raw=warm(core);lap(core,raw,1,2);lap(core,raw,2,102)
    core.latest={'at':time.perf_counter()}
    service=CoachService.__new__(CoachService)
    service.output='paddock';service.audio_enabled=True;service.core=core
    service.talk={'state':'idle'};service._local_valid=lambda _:True
    queued=[]
    service.engine=NS(context=NS(session_id='lap-test'),radio=NS(log=NS(record=lambda *a,**k:None)))
    def queue(calls,*,requested=False):
        assert requested
        queued.extend(calls)
    service._queue_baseline=queue
    reply=service._engine_reply("what's my last lap time",'typed')
    assert reply['understood']=='WHAT_WAS_MY_LAST_LAP_TIME' and queued
    assert all(c['source_event']=='LapTimes_4.19.5.4' and c['native_id'].startswith('core:') for c in queued)
    assert any('lap_times/time_intro' in c['fragments'] for c in queued)


@pytest.mark.parametrize('kind',['lap','pit_exit_cold','tyres_ready','tyres_hot','tyres_cooled','brakes_hot'])
def test_original_module_owns_baseline_emission_without_touching_watcher_history(kind):
    def unexpected(*a,**k):pytest.fail('Duplicate Paddock baseline call')
    engine=NS(original_lap_times=True,original_tyre_monitor=True,_say=unexpected,_consistency=unexpected)
    CoachEngine._car_status(engine,{'kind':kind},None,None,None)


def test_legacy_preview_fallback_and_requested_recon_are_retained():
    calls=[];engine=NS(_say=lambda *a,**k:calls.append(a))
    CoachEngine._car_status(engine,{'kind':'tyres_ready'},None,None,None)
    assert calls[-1][0]=='W-05'
    engine.original_lap_times=engine.original_tyre_monitor=True
    CoachEngine._car_status(engine,{'kind':'recon_corner','labels':['turn one'],'last':False,'apex':300},None,None,None)
    assert calls[-1][0]=='V-25'


def test_original_controls_replace_duplicate_rows_and_preserve_saved_preview_choices(tmp_path):
    controls_,core_,events=controls(tmp_path)
    controls_.save({'revision':0,'overrides':{'paddock':{'C-35':{'enabled':False}},
        'native':{'frequency_of_player_race_lap_time_reports':7},'families':{'lap_times':{'enabled':False}}}})
    controls_.activate(core_,events)
    rules=CoachEngine.capabilities()['implemented_rules']
    live=controls_.status(True,core_,events,rules,standalone=True)
    assert live['managed_by_original']['C-35']=='lap_times'
    assert live['managed_by_original']['M-10']=='tyres'
    assert not set(live['managed_by_original'])&{r['id'] for r in live['paddock']}
    assert live['saved']['paddock']['C-35']=={'enabled':False,'min_interval_s':0}
    preview=controls_.status(False,core_,events,rules)
    assert 'C-35' in {r['id'] for r in preview['paddock']}
    auto={'source_event':'LapTimes_4.19.5.4','sound_type':'REGULAR_MESSAGE'}
    assert controls_.native_reason(auto,'race',100)=='automatic_call_disabled'
    assert controls_.native_reason({**auto,'requested':True},'race',100) is None
    assert core_.settings['frequency_of_player_race_lap_time_reports']=='7'
