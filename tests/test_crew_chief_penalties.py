"""Original 4.19.5.4 penalty state machine; all speech uses a silent sink."""
from dataclasses import replace
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from ams2season.coach.crew_events import Events, DEFAULTS, command_for
from ams2season.coach.crew_voice import CrewChiefVoice
from ams2season.coach.crew_spotter import CrewChiefSounds
from ams2season.coach.speech import LocalRadio
from ams2season.coach.voice import pcm_wav
from ams2season.coach.telemetry import from_snapshot
from test_crew_chief_baseline import scene
from test_crew_chief_voice_engine import folder


def tick(t, *, schedule=0, laps=2, sector=1, invalid=False, pit=0, session='race'):
    s=scene(t)
    p=replace(s.cars[0],pit_schedule=schedule,laps=laps,sector=sector,invalid=invalid,pit=pit)
    return replace(s,session=session,cars=(p,*s.cars[1:]),
        local={**s.local,'pit_schedule':schedule,'yellow_flag_state':0,'local_lap_invalid':invalid})


def native(tmp_path):
    event=Events(root=tmp_path)
    event.settings.update(DEFAULTS)
    event.start()
    assert event.ready.wait(10),event.error
    return event


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
@pytest.mark.parametrize('schedule,kind',[(5,'drivethrough'),(6,'stopgo')])
def test_original_new_penalty_delay_lap_change_withdrawal_and_voice_questions(tmp_path,schedule,kind):
    event=native(tmp_path)
    try:
        s=tick(0);event.feed(s,s.cars[0])
        s=tick(.1,schedule=schedule);calls=event.feed(s,s.cars[0])
        assert calls[0]['folder']=='penalties/new_penalty_'+kind
        reminder=next(c for c in calls if c['folder']=='penalties/penalty_three_laps_left')
        assert reminder['delay_s']==20 and reminder['expires_s']==0
        assert event.valid_call(reminder['native_id'])
        reply=event.respond('DO_I_HAVE_A_PENALTY')
        assert reply[0]['fragments']==['penalties/you_have_a_penalty']
        assert reply[0]['immediate']
        for i in range(2,103):
            s=tick(i/10,schedule=schedule,laps=3 if i>=100 else 2)
            calls=event.feed(s,s.cars[0])
        assert not event.valid_call(reminder['native_id'])
        assert event.respond('HAVE_I_SERVED_MY_PENALTY')[0]['fragments']==[
            'acknowledge/no','penalties/you_still_have_a_penalty']
        s=tick(10.3,schedule=0,laps=3);event.feed(s,s.cars[0])
        answer=event.respond('HAVE_I_SERVED_MY_PENALTY')[0]
        assert answer['fragments']==['acknowledge/yes','penalties/penalty_served']
        assert event.valid_call(answer['native_id'])
        event.acknowledge(answer['native_id'])
        s=tick(10.4,laps=3);event.feed(s,s.cars[0])
        assert not event.valid_call(answer['native_id']) and not event.error
    finally: event.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
def test_official_invalid_lap_cut_is_delayed_once_and_kerbs_are_not_cuts(tmp_path):
    event=native(tmp_path)
    try:
        for i in range(20):
            s=tick(i/10,session='practice')
            assert not event.feed(s,s.cars[0])  # no official invalidation => no cut
        s=tick(2,invalid=True,session='practice')
        calls=event.feed(s,s.cars[0])
        assert len(calls)==1 and calls[0]['folder'].startswith('penalties/cut_track_')
        assert calls[0]['delay_s'] in (2,3) and calls[0]['expires_s']==5
        old_id=calls[0]['native_id']
        for i in range(21,40):
            s=tick(i/10,invalid=True,session='practice')
            assert not event.feed(s,s.cars[0])
        assert event.cuts==1
        s=replace(tick(4,invalid=True,session='practice'),game_state=3)
        assert not event.feed(s,s.cars[0]) and not event.valid_call(old_id)
    finally: event.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
def test_late_join_and_unknown_schedule_cannot_claim_no_penalty(tmp_path):
    event=native(tmp_path)
    try:
        s=tick(0,schedule=5);event.feed(s,s.cars[0])
        assert event.joined_with_penalty and not event.respond('DO_I_HAVE_A_PENALTY')
        s=tick(.1,schedule=-1)
        assert not event.feed(s,s.cars[0]) and not event.respond('DO_I_HAVE_A_PENALTY')
    finally: event.close()


@pytest.mark.parametrize('change',[dict(fresh=False),dict(game_state=3),dict(game_state=6),dict(viewed_slot=1)])
def test_no_penalty_advice_from_stale_pause_replay_or_spectator(change):
    requests=[]
    event=Events(host=lambda p:requests.append(p) or {'calls':[],'valid':[]})
    s=replace(tick(1,schedule=5),**change)
    assert not event.feed(s,s.cars[0]) and not requests


def test_penalty_phase_uses_local_race_state_and_leader_finish():
    requests=[]
    event=Events(host=lambda p:requests.append(p) or {'calls':[],'valid':[]})
    s=tick(0);event.feed(s,s.cars[0])
    s=tick(.1)
    leader=replace(s.cars[1],position=1,race_state=3)
    player=replace(s.cars[0],position=2)
    s=replace(s,cars=(player,leader),local={**s.local,'race_state':2})
    event.feed(s,player)
    assert requests[-1]['phase']=='Checkered'
    s=replace(s,t=.2,local={**s.local,'race_state':4})
    event.feed(s,player)
    assert event.state=='missing_or_inactive_telemetry' and event.last_payload is None


def test_raw_snapshot_and_recorded_car_channels_do_not_guess_missing_schedule():
    from ams2season import shm as S
    snap=S.SharedMemory();snap.mNumParticipants=1;snap.mViewedParticipantIndex=0
    snap.mParticipantInfo[0].mIsActive=True;snap.mParticipantInfo[0].mName=b'Player'
    snap.mParticipantInfo[0].mCurrentSector=2;snap.mPitSchedules[0]=6;snap.mPitSchedule=5
    result=from_snapshot(snap,1,'s')
    assert result.cars[0].sector==2 and result.cars[0].pit_schedule==6
    assert result.local['pit_schedule']==5  # original mapper uses authoritative local channel
    from ams2season.coach.telemetry import car_from_row
    assert car_from_row({'slot':0,'name':'Player'}).pit_schedule==-1
    assert command_for('Do I have a penalty?')=='DO_I_HAVE_A_PENALTY'


def test_new_recording_preserves_authoritative_local_schedule_separately(tmp_path):
    from ams2season import shm as S
    from ams2season.recorder import Recorder
    from ams2season.coach.replay import ticks
    snap=S.SharedMemory()
    snap.mVersion=S.SHARED_MEMORY_VERSION;snap.mGameState=2;snap.mSessionState=5;snap.mRaceState=2
    snap.mTrackLocation=b'Track';snap.mTrackVariation=b'Layout';snap.mTrackLength=2000
    snap.mCarName=b'GT3';snap.mCarClassName=b'GT3';snap.mNumParticipants=1
    p=snap.mParticipantInfo[0];p.mName=b'Player';p.mIsActive=True;p.mLapsCompleted=2;p.mCurrentSector=1
    snap.mRaceStates[0]=2;snap.mCarNames[0].value=b'GT3';snap.mCarClassNames[0].value=b'GT3'
    snap.mPitSchedule=5;snap.mPitSchedules[0]=6
    rec=Recorder(tmp_path/'recordings',log=lambda _:None)
    rec.step(snap,0);path=rec.active.path;rec.close(.1)
    meta=json.loads((path/'session.json').read_text())
    result=list(ticks(path,meta))[0]
    assert result.local['pit_schedule']==5 and result.cars[0].pit_schedule==6


def test_sweary_and_gender_file_flags_follow_read_only_profile_settings(tmp_path):
    base=tmp_path/'voice/penalties/cut_track_race_4';base.mkdir(parents=True)
    wav=pcm_wav(b'\0\0'*8820)
    for name in ('1.wav','sweary_1.wav','male_1.wav'): (base/name).write_bytes(wav)
    (base/'subtitles.csv').write_text('1.wav,"track limits"\nsweary_1.wav,"swearing variant"\nmale_1.wav,"male variant"\n')
    normal=CrewChiefVoice(CrewChiefSounds(tmp_path),settings={'block_male_sounds':True})
    assert [p.filename for p in normal.phrases('penalties/cut_track_race_4')]==['1.wav']
    all_=CrewChiefVoice(CrewChiefSounds(tmp_path),settings={'use_sweary_messages':True})
    assert len(all_.phrases('penalties/cut_track_race_4'))==3


def test_immediate_penalty_response_cannot_interrupt_active_spotter():
    entered,release=threading.Event(),threading.Event()
    def sink(data): entered.set();release.wait(2)
    radio=LocalRadio(SimpleNamespace(get=lambda t:None),sink=(sink,lambda:None),effect='off')
    try:
        assert radio.spot('car left',data=pcm_wav(b'\0\0'*8820))
        assert entered.wait(1)
        assert not radio.urgent('cc-penalties:1','penalty',data=pcm_wav(b'\0\0'*8820))
        assert radio.current=='spot'
    finally: release.set();radio.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
def test_live_service_delivers_original_penalty_in_selected_voice_and_withdraws_reminder(tmp_path):
    from ams2season.app import App
    from ams2season.coach.model import Context
    from ams2season.coach.service import CoachService
    app=App(tmp_path)
    service=app.coach
    original_voice=service.voice
    service.audio_enabled=True;service.output='paddock'
    played=[];logged=[]
    wav=pcm_wav(b'\1\0'*8820)
    service.voice=SimpleNamespace(get=lambda text:SimpleNamespace(data=wav))
    sounds=tmp_path/'sounds'
    folder(sounds,'penalties/new_penalty_drivethrough',["you've got a drive through penalty"])
    service.cc_voice=CrewChiefVoice(CrewChiefSounds(sounds))
    service.cc_voice.prepare(service.voice,['penalties/new_penalty_drivethrough'])
    service.local_radio=LocalRadio(service.voice,sink=(played.append,lambda:None),effect='off')
    service.engine=SimpleNamespace(context=Context(0,'s',active=True,radio_busy=False),
        radio=SimpleNamespace(log=SimpleNamespace(record=lambda *a,**kw:logged.append((a,kw)))))
    service.events.start();assert service.events.ready.wait(10),service.events.error
    try:
        def step(s):
            service.origin=time.perf_counter()-s.t
            service.engine.context=replace(service.engine.context,t=s.t)
            calls=service.events.feed(s,s.cars[0]);service._queue_baseline(calls)
            return service._deliver_baseline()
        assert not step(tick(0))
        assert step(tick(.1,schedule=5))
        until=time.monotonic()+1
        while service.local_radio.busy and time.monotonic()<until: time.sleep(.005)
        assert len(played)==1
        service._local_events()
        assert any(kw.get('voice')=='voice_pack' for _,kw in logged)
        assert any(c['folder']=='penalties/penalty_three_laps_left' for c in service.baseline_pending)
        assert not step(tick(.2,schedule=0))
        assert not service.baseline_pending and len(played)==1
        assert service._engine_reply('do I have a penalty','typed')['understood']=='DO_I_HAVE_A_PENALTY'
    finally:
        service.local_radio.close();service.local_radio=None;service.engine=None
        service.events.close();service.voice=original_voice;service.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Runs original C# .NET Framework')
def test_replay_bench_withdraws_delayed_reminder_using_original_validation(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from ams2season.coach.replay import run_replay
    path=tmp_path/'recordings/race';path.mkdir(parents=True)
    meta={'session_type':'race','status':'complete','track_location':'Track','track_variation':'Layout',
          'track_length':2000,'local':{'name':'Driver0','car':'GT3'}}
    (path/'session.json').write_text(json.dumps(meta))
    frames=[];local=[]
    for i in range(120):
        t=i/4;s=tick(t,schedule=5 if 4<=i<24 else 0)
        for car in s.cars:
            frames.append({'t':t,'slot':car.slot,'name':car.name,'car':car.car,'car_class':car.car_class,
                'race_pos':car.position,'laps_completed':car.laps,'lap_dist':car.distance,'speed':car.speed,
                'pit_mode':car.pit,'race_state':car.race_state,'lap_invalid':False,'pit_schedule':car.pit_schedule,
                'sector':car.sector,'x':car.x,'z':car.z})
        local.append({'t':t,'game_state':2,'viewed_slot':0,'speed':50,'throttle':1.,'brake':0.,'steering':0.,
                      'crash_state':0,'local_lap_invalid':False,'rain_density':0.,'water_temp':80.,'oil_temp':90.})
    pq.write_table(pa.Table.from_pylist(frames),path/'frames.parquet')
    pq.write_table(pa.Table.from_pylist(local),path/'local.parquet')
    report=run_replay(path,tmp_path,crew_engine_enabled=True)
    assert report['inputs_unchanged'] and not report['audio_played']
    result=report['crew_chief_penalties']
    assert result['status']=='simulated' and result['requested']>=2 and result['withdrawn']>=1
    events=[json.loads(s) for s in (tmp_path/report['directory']/'radio.jsonl').read_text().splitlines()]
    spoken=[e['text'] for e in events if e['state']=='would_say']
    assert 'penalties/new_penalty_drivethrough' in spoken
    assert 'penalties/penalty_three_laps_left' not in spoken
