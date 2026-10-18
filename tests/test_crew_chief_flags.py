"""Native Crew Chief flag timing, telemetry provenance and silent voice delivery."""
from dataclasses import replace
import hashlib
import json
import sys
import time
from types import SimpleNamespace

import pytest

from ams2season.coach.crew_events import Events, DEFAULTS, FLAG_FOLDERS
from ams2season.coach.crew_spotter import ASSETS, CrewChiefSounds
from ams2season.coach.crew_voice import CrewChiefVoice
from ams2season.coach.model import Context
from ams2season.coach.speech import LocalRadio
from ams2season.coach.voice import pcm_wav
from test_crew_chief_penalties import tick, native
from test_crew_chief_voice_engine import folder


def flagged(t, colour=6, **kwargs):
    s=tick(t,**kwargs)
    return replace(s,local={**s.local,'flag_colour':colour})


def advance(event,start,end,colour=6,**kwargs):
    calls=[]
    for i in range(round(start*4),round(end*4)+1):
        s=flagged(i/4,colour,**kwargs)
        calls.extend((i/4,c) for c in event.feed(s,s.cars[0]))
    return calls


def test_exact_flag_source_and_compiled_receipt_are_current():
    assert hashlib.sha256((ASSETS/'FlagsMonitor.cs').read_bytes()).hexdigest()=='fd4731867a31059268ab08408076c7ce522be21cf98e9cc2e3942d6ce227c923'
    receipt=json.loads((ASSETS/'events_core.build.json').read_text(encoding='utf-8-sig'))
    for name,digest in receipt['sources'].items():
        assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()==digest
    assert hashlib.sha256((ASSETS/'events_core.dll').read_bytes()).hexdigest()==receipt['assembly_sha256']


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
@pytest.mark.parametrize('colour,name,expires,priority',[(2,'blue_flag',6,0),(3,'white_flag',2,0),
    (6,'yellow_flag',3,10),(7,'double_yellow_flag',3,10),(10,'black_flag',0,10)])
def test_original_ams2_flag_values_warmup_and_parameters(tmp_path,colour,name,expires,priority):
    event=native(tmp_path)
    try:
        calls=advance(event,0,10,colour)
        assert len(calls)==1
        when,c=calls[0]
        assert when==10 and c['folder']=='flags/'+name
        assert c['expires_s']==expires and c['priority']==priority
        assert c['immediate']==(name!='black_flag')
        assert c['source_event']=='FlagsMonitor_4.19.5.4' and c['id'].startswith('flags:')
        assert event.valid_call(c['native_id'])
        # In-pit messages are withdrawn by original FlagsMonitor validation.
        s=flagged(10.25,colour,pit=1);assert not event.feed(s,s.cars[0])
        assert not event.valid_call(c['native_id']) and not event.error
    finally: event.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
@pytest.mark.parametrize('colour',[-1,0,1,4,5,8,9,11])
def test_unmapped_red_final_lap_mechanical_and_chequered_are_not_fake_local_warnings(tmp_path,colour):
    event=native(tmp_path)
    try: assert advance(event,0,11,colour)==[] and not event.error
    finally: event.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
@pytest.mark.parametrize('colour,lo,hi',[(6,25,35),(7,25,35),(2,15,22),(3,15,25),(10,15,22)])
def test_original_randomized_cooldowns_not_a_tick_spam_loop(tmp_path,colour,lo,hi):
    event=native(tmp_path)
    try:
        calls=advance(event,0,81,colour)
        assert len(calls)>=2
        gaps=[b[0]-a[0] for a,b in zip(calls,calls[1:])]
        assert all(lo<=d<=hi+.25 for d in gaps),gaps
    finally: event.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
def test_original_blue_flag_start_suppression_and_same_opponent_repeat_cap(tmp_path):
    event=native(tmp_path)
    try:
        calls=[]
        for i in range(440):
            s=flagged(i/4,2)
            p=replace(s.cars[0],position=3,race_state=1 if i<44 else 2)
            # Source method identifies this car by distance/class position.
            rival=replace(s.cars[1],position=1,distance=90)
            s=replace(s,cars=(p,rival,s.cars[2]),local={**s.local,'race_state':p.race_state})
            calls.extend((i/4,c) for c in event.feed(s,p))
        assert len(calls)==3
        assert calls[0][0]>=26  # green at11, at least15 seconds original delay
        assert event.last_payload['opponents'][0]['key']==rival.identity
        assert not event.error
    finally: event.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
def test_original_yellow_suppressed_after_leader_finishes(tmp_path):
    event=native(tmp_path)
    try:
        for i in range(50):
            s=flagged(i/4,6)
            p=replace(s.cars[0],position=2)
            leader=replace(s.cars[1],position=1,race_state=3)
            s=replace(s,cars=(p,leader,s.cars[2]))
            assert not event.feed(s,p)
        assert event.last_payload['phase']=='Checkered' and not event.error
    finally: event.close()


@pytest.mark.parametrize('change',[dict(fresh=False),dict(game_state=3),dict(game_state=6),dict(viewed_slot=1)])
def test_flag_event_rejects_pause_spectator_replay_stale(change):
    requests=[]
    event=Events(host=lambda p:requests.append(p) or {'calls':[],'valid':[]})
    s=replace(flagged(12),**change)
    assert not event.feed(s,s.cars[0]) and not requests


def test_authoritative_flag_channel_and_recorder_round_trip(tmp_path):
    from ams2season import shm as S
    from ams2season.recorder import Recorder
    from ams2season.coach.telemetry import from_snapshot
    from ams2season.coach.replay import ticks
    snap=S.SharedMemory()
    snap.mVersion=S.SHARED_MEMORY_VERSION;snap.mGameState=2;snap.mSessionState=5;snap.mRaceState=2
    snap.mTrackLocation=b'Track';snap.mTrackVariation=b'Layout';snap.mTrackLength=2000
    snap.mCarName=b'GT3';snap.mCarClassName=b'GT3';snap.mNumParticipants=1
    p=snap.mParticipantInfo[0];p.mName=b'Player';p.mIsActive=True;p.mLapsCompleted=2;p.mCurrentSector=1
    snap.mRaceStates[0]=2;snap.mCarNames[0].value=b'GT3';snap.mCarClassNames[0].value=b'GT3'
    snap.mHighestFlagColour=6;snap.mHighestFlagColours[0]=2
    s=from_snapshot(snap,1,'s')
    assert s.local['flag_colour']==6 and s.cars[0].flag_colour==2
    rec=Recorder(tmp_path/'recordings',log=lambda _:None)
    rec.step(snap,0);path=rec.active.path;rec.close(.1)
    result=list(ticks(path,json.loads((path/'session.json').read_text())))[0]
    assert result.local['flag_colour']==6 and result.cars[0].flag_colour==2
    requests=[];event=Events(host=lambda p:requests.append(p) or {'calls':[],'valid':[]})
    event.feed(result,result.cars[0]);assert requests[0]['flag_colour']==6


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
def test_flag_warnings_do_not_depend_on_unrelated_penalty_channels(tmp_path):
    event=native(tmp_path)
    try:
        calls=[]
        for i in range(45):
            s=flagged(i/4,schedule=-1,sector=-1)
            calls.extend(event.feed(s,s.cars[0]))
        assert [c['folder'] for c in calls]==['flags/yellow_flag']
        assert event.state=='missing_penalty_telemetry' and event.flag_state=='monitoring'
        assert not event.respond('DO_I_HAVE_A_PENALTY') and not event.error
    finally: event.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
def test_disabled_yellow_profile_keeps_other_flags_working(tmp_path):
    event=Events(root=tmp_path);event.settings.update(DEFAULTS)
    event.settings['enable_yellow_flag_messages']=False
    event.start();assert event.ready.wait(10),event.error
    try:
        assert not advance(event,0,11,6)
        assert advance(event,11.25,12,10)[0][1]['folder']=='flags/black_flag'
    finally: event.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
def test_missing_channel_withdraws_only_affected_native_calls(tmp_path):
    event=native(tmp_path)
    try:
        calls=advance(event,0,10,6);call=calls[0][1]
        assert event.valid_call(call['native_id'])
        s=flagged(10.25,-1);event.feed(s,s.cars[0])
        assert not event.valid_call(call['native_id'])
        answer=event.respond('DO_I_HAVE_A_PENALTY')[0]
        assert event.valid_call(answer['native_id'])
        s=flagged(10.5,-1,schedule=-1);event.feed(s,s.cars[0])
        assert not event.valid_call(answer['native_id'])
    finally: event.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
def test_flag_native_to_selected_voice_through_real_service_silent_sink(tmp_path):
    from ams2season.app import App
    app=App(tmp_path);service=app.coach;original_voice=service.voice
    service.audio_enabled=True;service.output='paddock'
    played=[];logged=[];wav=pcm_wav(b'\1\0'*8820)
    service.voice=SimpleNamespace(get=lambda text:SimpleNamespace(data=wav))
    sounds=tmp_path/'sounds';folder(sounds,'flags/yellow_flag',['yellow flag, watch out'])
    service.cc_voice=CrewChiefVoice(CrewChiefSounds(sounds))
    service.cc_voice.prepare(service.voice,FLAG_FOLDERS)
    service.local_radio=LocalRadio(service.voice,sink=(played.append,lambda:None),effect='off')
    service.engine=SimpleNamespace(context=Context(0,'s',active=True,radio_busy=False),
        radio=SimpleNamespace(log=SimpleNamespace(record=lambda *a,**kw:logged.append((a,kw)))))
    service.events.start();assert service.events.ready.wait(10),service.events.error
    try:
        for i in range(41):
            s=flagged(i/4)
            service.origin=time.perf_counter()-s.t
            service.engine.context=replace(service.engine.context,t=s.t)
            service._queue_baseline(service.events.feed(s,s.cars[0]))
        assert service._deliver_baseline()
        until=time.monotonic()+1
        while service.local_radio.busy and time.monotonic()<until: time.sleep(.005)
        service._local_events()
        assert len(played)==1
        assert any(kw.get('source')=='FlagsMonitor_4.19.5.4' for _,kw in logged)
        assert any(kw.get('voice')=='voice_pack' for _,kw in logged)
        assert not service.events.valid_ids  # played-call acknowledgement
    finally:
        service.local_radio.close();service.local_radio=None;service.engine=None
        service.events.close();service.voice=original_voice;service.close()
