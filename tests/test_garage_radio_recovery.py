"""Garage publication and PTT regression: no microphone, speakers or game writes."""
import ctypes,json,queue,sys,threading,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from ams2season.practice_overlay import NativeOverlay
from ams2season.coach.speech import WindowsListener
from ams2season.coach import crew_tyres
from ams2season.coach.service import CoachService
from test_practice_overlay import wait_for


@pytest.mark.skipif(sys.platform!='win32',reason='Windows file sharing semantics')
def test_reader_lock_delays_publication_without_killing_helper_or_leaving_stale_state(tmp_path):
    overlay=NativeOverlay.__new__(NativeOverlay)
    overlay.path=tmp_path/'state.json';overlay.path.write_text('{}')
    overlay.process=SimpleNamespace(poll=lambda:None)
    overlay.publication_delayed=False
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    # Same share mode as File.ReadAllText in the native window.
    handle=kernel.CreateFileW(str(overlay.path),0x80000000,1,None,3,0,None)
    assert handle not in (None,ctypes.c_void_p(-1).value),ctypes.get_last_error()
    try:
        overlay.publish({'enabled':True,'visible':False,'card':None})
        assert overlay.publication_delayed and overlay.running
        assert json.loads(overlay.path.read_text())=={}
    finally:kernel.CloseHandle(handle)
    overlay.publish({'enabled':True,'visible':False,'card':{'heading':'Current advice'}})
    state=json.loads(overlay.path.read_text())
    assert state['card']['heading']=='Current advice' and state['expires_utc']>time.time()
    assert not overlay.publication_delayed and overlay.running


class SpeechHost:
    def __init__(self):self.calls=[];self.closed=False
    def request(self,payload,timeout):
        self.calls.append(payload['cmd'])
        if payload['cmd']=='listen_stop':return {'text':'recon lap','confidence':.9,'detected_speech':True}
        return {}
    def close(self):self.closed=True


def test_recognizer_prepares_before_first_press_and_signals_when_actually_listening():
    host=SpeechHost();listener=WindowsListener(['recon lap','tyre status'],host=host)
    try:
        wait_for(lambda:listener.ready)
        assert host.calls==['listen_setup'] and listener.state=='ready'
        assert listener.drain_events()==[]
        listener.press();wait_for(lambda:listener.state=='listening')
        assert listener.drain_events()==[{'event':'listening'}]
        listener.release();wait_for(lambda:not listener.results.empty())
        assert listener.heard()==[('recon lap',.9)]
        assert host.calls==['listen_setup','listen_start','listen_stop']
    finally:listener.close()
    assert host.closed and not listener.thread.is_alive()


def test_slow_prepare_can_be_closed_without_leaking_a_late_host():
    entered=threading.Event();release=threading.Event()
    class Host(SpeechHost):
        def request(self,payload,timeout):entered.set();release.wait(2);return {}
        def close(self):super().close();release.set()
    host=Host();listener=WindowsListener(['recon lap'],host=host)
    assert entered.wait(1)
    listener.close()
    assert host.closed and not listener.thread.is_alive()


def test_released_during_prepare_never_starts_microphone_after_button_is_up():
    entered=threading.Event();release=threading.Event()
    class Host(SpeechHost):
        def request(self,payload,timeout):
            if payload['cmd']=='listen_setup':entered.set();assert release.wait(2)
            return super().request(payload,timeout)
    host=Host();listener=WindowsListener(['recon lap'],host=host)
    try:
        assert entered.wait(1)
        listener.press();listener.release();release.set()
        wait_for(lambda:not listener.results.empty())
        result=listener.heard_details()
        assert result[0]['text'] is None and 'before the microphone was ready' in result[0]['problem']
        assert host.calls==['listen_setup'] and listener.state=='ready'
        assert listener.drain_events()==[]
    finally:release.set();listener.close()


def service_with_outcome(text,confidence=.9,problem=None):
    service=CoachService.__new__(CoachService)
    service.buttons=None;service.output='paddock';service.audio_enabled=True
    service.thread=SimpleNamespace(is_alive=lambda:True)
    service.core=SimpleNamespace(waiting_for_driver_ok=False,waiting_for_speech=True,
        settings={'minimum_voice_recognition_confidence_system_sre':'.7'},speech_result=lambda *a,**k:[])
    service.engine=SimpleNamespace(context=SimpleNamespace(session_id='test'))
    service.listener=SimpleNamespace(ready=True,error=None,heard_details=lambda:[{'text':text,
        'confidence':confidence,'detected_speech':bool(text),'problem':problem}])
    service._local_valid=lambda _:True
    service.talk={'state':'thinking'}
    def queue_requested(calls, *, requested=False):
        assert requested is True
    service._queue_baseline=queue_requested
    replies=[];service._button_reply=lambda *args:replies.append(args)
    return service,replies


@pytest.mark.parametrize('phrase',['recon lap','can you do a recon lap','start a recon lap','call out the corners','guide me around the track'])
def test_recognized_recon_variants_reach_practice_reply_route(phrase):
    service,replies=service_with_outcome(phrase)
    service._service_buttons()
    assert replies==[(phrase,'voice')] and service.talk['last_heard']['understood']
    assert service.talk['state']=='idle' and not service.core.waiting_for_speech


@pytest.mark.parametrize('text,confidence,problem',[(None,0,'Microphone unavailable'),(None,0,None),('recon lap',.2,None)])
def test_failed_or_uncertain_speech_is_visible_and_releases_speech_hold(text,confidence,problem):
    service,replies=service_with_outcome(text,confidence,problem)
    service._service_buttons()
    assert not replies and not service.core.waiting_for_speech
    assert service.talk['note'] and not service.talk['last_heard']['understood']
    if problem:assert service.talk['note']==problem


@pytest.mark.parametrize('phrase',['tyre status','tire status','how are my tyres','what are my tire temperatures','how are my brake temps'])
def test_tyre_grammar_is_recognized_instead_of_silent_or_practice_progress(phrase):
    assert crew_tyres.command_for(phrase)
    service,replies=service_with_outcome(phrase)
    service._service_buttons();assert replies==[(phrase,'voice')]


@pytest.mark.parametrize('fresh',[True,False])
def test_tyre_response_routes_native_reply_or_freshness_gate(fresh):
    service,replies=service_with_outcome('tyre status')
    service.engine.radio=SimpleNamespace(log=SimpleNamespace(record=lambda *a,**k:None))
    service._local_valid=lambda _:fresh
    calls=[]
    requests=[]
    def respond(command):
        requests.append(command)
        return [{'id':'AudioPlayer:q1','native_id':'core:q1','fragments':['acknowledge/no_data'],
            'source_event':'AudioPlayer_4.19.5.4'}]
    service.core.respond=respond
    service._queue_baseline=lambda values, *, requested=False: calls.extend(
        {**value, 'requested':requested} for value in values)
    result=service._engine_reply('tyre status','voice')
    if fresh:
        assert 'response queued' in result['response']
        assert requests==['PADDOCK_TYRE_STATUS']
        assert calls[0]['fragments']==['acknowledge/no_data']
        assert calls[0]['source_event']=='AudioPlayer_4.19.5.4'
        assert calls[0]['requested'] is True
        assert calls[0]['native_id']=='core:q1'
    else:assert not requests and not calls and 'fresh local telemetry' in result['response']


def test_listener_grammar_contains_user_recon_and_installed_tyre_queries(tmp_path,monkeypatch):
    from ams2season.app import App
    from ams2season.coach import service as module
    monkeypatch.setattr(module,'WindowsListener',lambda phrases:SimpleNamespace(phrases=set(phrases)))
    app=App(tmp_path);listener=app.coach._ensure_listener()
    assert {'can you do a recon lap','recon lap','tyre status','how are my tire temps','how are my tyres'}<=listener.phrases
    assert all(p in listener.phrases for p in crew_tyres.listener_phrases())
