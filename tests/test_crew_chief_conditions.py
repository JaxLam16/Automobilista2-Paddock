"""Original weather calls via complete shared state; all audio sinks are silent."""
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import wave

import pytest

from ams2season.coach.crew_core import Core,COMMANDS,FOLDERS,command_for
from ams2season.coach.crew_mapper import DEFAULTS,snapshot_payload
from ams2season.coach.crew_spotter import ASSETS,CrewChiefSounds
from ams2season.coach.crew_voice import CrewChiefVoice
from ams2season.coach.telemetry import from_snapshot
from ams2season.coach.voice import pcm_wav
from test_crew_chief_mapper import snapshot,TICKS

NATIVE=pytest.mark.skipif(sys.platform!='win32',reason='Original Framework event host')


def weather_snapshot():
    raw=snapshot()
    raw.mAmbientTemperature=25
    raw.mTrackTemperature=35
    raw.mCloudBrightness=2
    raw.mBrakeBias=.45
    return raw


@pytest.fixture
def core(tmp_path):
    host=Core(root=tmp_path)
    numbers=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS, __paddock_number_config=numbers)
    host.settings.update(ambient_temp_check_interval_seconds='5',track_temp_check_interval_seconds='5')
    host.start();assert host.ready.wait(10),host.error
    host.weather_available=True
    try:yield host
    finally:host.close()


def native_map(core,raw,seconds=0):
    result=core._request({'op':'map','ticks':TICKS+round(seconds*10000000),'raw':snapshot_payload(raw)})
    assert result is not None,core.error
    assert not result.get('error'),result
    assert result['mapped']
    return result['events']


def test_original_sources_and_message_types_are_pinned():
    receipt=json.loads((ASSETS/'core_sources.json').read_text())
    for name,item in receipt.items():assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()==item['sha256']
    assert receipt['ConditionsMonitor.cs']['sha256']=='2cba7685acfe26bbf79ef297400af24ea1573440382cb68372cf19c839e55187'
    assert receipt['AbstractEvent.cs']['sha256']=='828b619dad40f8476c26199843260314279b579f94e5d716a82b069e58612c90'


@pytest.mark.parametrize('phrase,command',[(phrase,command) for command,phrases in COMMANDS.items() for phrase in phrases])
def test_original_default_weather_questions_are_recognised(phrase,command):
    assert command_for(phrase.upper()+'?')==command


@NATIVE
def test_original_air_and_track_change_has_exact_resolved_fragment_order(core):
    raw=weather_snapshot()
    assert native_map(core,raw)['calls']==[]
    raw.mAmbientTemperature=35;raw.mTrackTemperature=45
    calls=native_map(core,raw,11)['calls']
    assert len(calls)==1
    assert calls[0]['fragments']==['conditions/air_and_track_temp_increasing','conditions/air_temp_is_now',
        'numbers/35','conditions/track_temp_is_now','numbers/45','conditions/celsius']
    assert calls[0]['expires_s']==10 and not calls[0]['immediate']
    assert calls[0]['source_event']=='ConditionsMonitor_4.19.5.4' and calls[0]['folders_resolved']
    assert native_map(core,raw,22)['calls']==[]


@NATIVE
def test_original_rain_levels_and_repeat_suppression(core):
    raw=weather_snapshot()
    native_map(core,raw)
    raw.mRainDensity=.2
    calls=native_map(core,raw,11)['calls']
    assert [c['fragments'] for c in calls]==[['conditions/light_rain_increasing']]
    assert calls[0]['immediate'] and calls[0]['sound_type']=='IMPORTANT_MESSAGE'
    for call in calls:core.acknowledge('core:'+call['id'])
    raw.mRainDensity=.25
    assert native_map(core,raw,22)['calls']==[]
    raw.mRainDensity=.65
    calls=native_map(core,raw,33)['calls']
    assert calls[0]['fragments']==['conditions/heavy_rain_increasing']
    for call in calls:core.acknowledge('core:'+call['id'])
    raw.mRainDensity=0
    assert native_map(core,raw,44)['calls'][0]['fragments']==['conditions/stopped_raining']


@NATIVE
@pytest.mark.parametrize('fahrenheit,unit,air,track',[(False,'celsius',25,35),(True,'fahrenheit',77,95)])
def test_original_temperature_questions_use_paddock_units(core,fahrenheit,unit,air,track):
    core._fahrenheit=fahrenheit
    native_map(core,weather_snapshot())
    for command,number,folder in [('WHATS_THE_AIR_TEMP',air,'air_temp_is_now'),('WHATS_THE_TRACK_TEMP',track,'track_temp_is_now')]:
        result=core._request({'op':'command','command':command,'ack':[]})
        assert result['calls'][0]['fragments']==['conditions/'+folder,'numbers/'+str(number),'conditions/'+unit]
        assert result['calls'][0]['immediate']


@NATIVE
def test_original_unmapped_brake_bias_returns_no_data_not_a_guessed_front_rear_value(core):
    native_map(core,weather_snapshot())
    result=core._request({'op':'command','command':'WHATS_MY_BRAKE_BIAS','ack':[]})
    assert result['calls'][0]['fragments']==['acknowledge/no_data']


@NATIVE
def test_missing_weather_withdraws_pending_and_new_session_reseeds_history(core):
    raw=weather_snapshot();native_map(core,raw)
    raw.mAmbientTemperature=35
    result=native_map(core,raw,11)
    assert result['calls'] and result['valid']
    core.weather_available=False
    assert native_map(core,raw,12)['valid']==[]
    core.weather_available=True
    raw.mSessionState=3
    assert native_map(core,raw,13)['calls']==[]


@NATIVE
def test_native_unicode_opponents_survive_utf8_ipc(core):
    raw=weather_snapshot();raw.mParticipantInfo[1].mName='Sébastien Pérez'.encode()
    result=core._request({'op':'map','ticks':TICKS,'raw':snapshot_payload(raw)})
    assert not result.get('error'),result
    assert result['opponents']['Sébastien Pérez']['name']=='Sébastien Pérez'


def test_stale_raw_snapshot_never_reaches_host_and_withdraws_pending():
    host=Core(host=lambda p:pytest.fail('stale snapshot reached native host'))
    raw=weather_snapshot();tick=from_snapshot(raw,0,'race')
    host.valid_ids={'1'}
    assert host.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter()-1)==[]
    assert not host.valid_ids and host.latest is None


def test_pregrid_requires_a_successfully_mapped_driving_identity():
    requests=[]
    def native(payload):
        requests.append(payload)
        if payload['op']=='reset':return {'reset':True}
        return {'mapped':True,'events':{'calls':[],'valid':[]}}
    host=Core(host=native)
    raw=weather_snapshot();raw.mGameState=4
    tick=from_snapshot(raw,0,'race')
    assert host.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter())==[]
    assert requests==[]
    raw.mGameState=2;tick=from_snapshot(raw,1,'race')
    host.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter())
    assert host._confirmed
    raw.mGameState=4;tick=from_snapshot(raw,2,'race')
    host.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter())
    assert requests[-1]['op']=='map'
    raw.mCarName=b'Other car';tick=from_snapshot(raw,3,'race')
    count=len(requests)
    host.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter())
    assert len(requests)==count


def test_failed_driving_snapshot_does_not_confirm_pregrid_identity():
    host=Core(host=lambda p:pytest.fail('invalid snapshot reached host'))
    raw=weather_snapshot();raw.mVersion=9
    tick=from_snapshot(raw,0,'race')
    host.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter())
    assert host._confirmed is None


@NATIVE
def test_transient_invalid_raw_field_withholds_and_recovers_without_killing_host(core):
    raw=weather_snapshot();tick=from_snapshot(raw,0,'race')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter())
    assert core.latest and not core.error
    process=core.process
    raw.mOilTempCelsius=float('nan');tick=from_snapshot(raw,.1,'race')
    assert core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter())==[]
    assert core.latest is None and core.data_error and not core.error
    assert process.poll() is None
    raw.mOilTempCelsius=110;tick=from_snapshot(raw,.2,'race')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter())
    assert core.latest and core.data_error is None and core.process is process


def test_resolved_folder_legacy_fallback_keeps_exact_pause_without_extra_silence(tmp_path):
    cc=CrewChiefVoice(CrewChiefSounds(tmp_path))
    voice=SimpleNamespace(get=lambda text:None)
    data=pcm_wav(b'\1\0'*2205)
    cc.choose=lambda folder,selected=True: (folder,data,'crew_chief_recording')
    text,audio,source=cc.render({'fragments':['conditions/air_temp_is_now','insert_pause:100','numbers/25'],
        'folders_resolved':True},voice)
    with wave.open(io.BytesIO(audio)) as wav:assert wav.getnframes()==2205*2+2205
    assert source=='crew_chief_recording'


@NATIVE
def test_live_worker_maps_complete_snapshot_and_routes_question_to_silent_radio(tmp_path,monkeypatch):
    from ams2season.app import App
    from ams2season.recorder import Recorder
    from ams2season.coach.speech import LocalRadio
    from test_coach_service import wait_until,snapshot_stream
    import ams2season.coach.service as module
    app=App(tmp_path)
    app.recorder.thread=SimpleNamespace(is_alive=lambda:True)
    app.recorder.rec=Recorder(tmp_path/'recordings',sessions=(),log=lambda _:None)
    raw=weather_snapshot();app.recorder.rec.step(raw,time.perf_counter())
    service=app.coach;service.output='paddock';service.audio_enabled=True;service.tts_fallback=False
    played=[]
    monkeypatch.setattr(module,'LocalRadio',lambda voice,**kwargs:LocalRadio(voice,sink=(played.append,lambda:None),effect='off'))
    try:
        with snapshot_stream(app,raw):
            service.start()
            assert service.core.ready.wait(10),service.core.error
            wait_until(lambda:service.core.latest is not None and time.perf_counter()-service.core.latest['at']<.15)
            with service.lock:
                reply=service._engine_reply("what's the air temperature",'typed')
                assert reply['understood']=='WHATS_THE_AIR_TEMP' and 'queued' in reply['response']
                assert service.baseline_pending[-1]['fragments']==['conditions/air_temp_is_now','numbers/25','conditions/celsius']
                assert service._deliver_baseline()
            wait_until(lambda:bool(played))
        process=service.core.process
        service.stop()
        assert process.poll() is not None and not service.core.valid_ids
        assert not list((tmp_path/'recordings').iterdir())
    finally:service.close()
