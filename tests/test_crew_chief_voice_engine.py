"""Original source temperature decisions and selected voice, without real sound output."""
from dataclasses import replace
import csv
import hashlib
import io
import json
import sys
import time
from types import SimpleNamespace
import wave

import pytest

from ams2season.coach.crew_engine import EngineMonitor, command_for
from ams2season.coach.crew_spotter import CrewChiefSounds
from ams2season.coach.crew_voice import CrewChiefVoice
from ams2season.coach.speech import LocalRadio
from ams2season.coach.voice import VoiceCache, pcm_wav, text_key
from test_crew_chief_baseline import scene


def folder(root, name, texts):
    base = root/'voice'/name
    base.mkdir(parents=True)
    with (base/'subtitles.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f)
        for i,text in enumerate(texts):
            filename=str(i)+'.wav'
            (base/filename).write_bytes(pcm_wav(b'\0\0'*8820))
            w.writerow((filename,text))


def test_selected_voice_uses_actual_subtitle_variant_and_never_live_tts(tmp_path):
    folder(tmp_path,'spotter/still_there',["he's still there",'hold your line'])
    selected=pcm_wav(b'\1\0'*8820)
    class Voice:
        def get(self,text): return SimpleNamespace(data=selected)
    voice=Voice()
    cc=CrewChiefVoice(CrewChiefSounds(tmp_path))
    cc.prepare(voice,['spotter/still_there'])
    played=[]
    radio=LocalRadio(voice,sink=(played.append,lambda:None),effect='off')
    try:
        text,data,source=cc.choose('spotter/still_there')
        assert text in ("he's still there",'hold your line') and data==selected and source=='voice_pack'
        assert radio.spot(text,data=data,source=source,deadline=time.monotonic()+2)
        deadline=time.monotonic()+2
        while not played and time.monotonic()<deadline: time.sleep(.01)
        assert played
        assert any(e.get('source')=='voice_pack' and e['text']==text for e in radio.drain())
    finally: radio.close()
    assert cc.status(['spotter/still_there'])['missing']==[]


def test_missing_ai_variant_falls_back_to_exact_original_audio_and_reports_it(tmp_path):
    folder(tmp_path,'spotter/car_left',['on your left'])
    cc=CrewChiefVoice(CrewChiefSounds(tmp_path))
    cc.prepare(SimpleNamespace(get=lambda text:None),['spotter/car_left'])
    text,data,source=cc.choose('spotter/car_left')
    assert text=='on your left' and source=='crew_chief_recording'
    assert data==(tmp_path/'voice/spotter/car_left/0.wav').read_bytes()
    assert cc.status(['spotter/car_left'])['missing']==['on your left']
    with pytest.raises(ValueError): cc.choose('spotter/../../private')


def test_supplement_is_identity_checked_and_reload_picks_it_up(tmp_path):
    out=tmp_path/'private_coach/voice-supplements/paddock-daniel'
    out.mkdir(parents=True)
    wav=pcm_wav(b'\1\0'*8820)
    (out/'hold.wav').write_bytes(wav)
    manifest={'private':True,'publish_allowed':False,'voice_id':'paddock-daniel',
              'clips':[{'id':'hold','text':'hold your line','radio':'hold.wav',
                        'radio_sha256':hashlib.sha256(wav).hexdigest(),'seconds':.4}]}
    v=VoiceCache(tmp_path,voice_id='paddock-daniel')
    assert v.get('hold your line') is None
    (out/'manifest.json').write_text(json.dumps(manifest))
    v.reload()
    assert v.get('hold your line').data==wav
    broken=VoiceCache(tmp_path,voice_id='paddock-daniel',
                      pack_directory=tmp_path/'private_coach/voice-packs/missing')
    assert broken.errors  # a supplement cannot disguise a missing managed pack
    assert VoiceCache(tmp_path,voice_id='another-engineer').get('hold your line') is None
    manifest['voice_id']='another-engineer'
    (out/'manifest.json').write_text(json.dumps(manifest))
    v.reload()
    assert v.get('hold your line') is None and v.errors


@pytest.mark.parametrize('change',[dict(fresh=False),dict(game_state=3),dict(game_state=5),dict(viewed_slot=1)])
def test_engine_cannot_use_spectator_paused_stale_or_replay_inputs(change):
    requests=[]
    monitor=EngineMonitor(host=lambda p:requests.append(p) or {'calls':[]})
    tick=replace(scene(1),local={'oil_c':150,'water_c':140,'speed':50,'local_sample_age_s':0},**change)
    assert monitor.feed(tick,tick.cars[0])==[] and requests==[]
    assert not monitor.respond('WHAT_IS_MY_OIL_TEMP')


def test_engine_uses_class_limits_and_never_invents_pressure_flags_or_stalled_health():
    requests=[]
    monitor=EngineMonitor(host=lambda p:requests.append(p) or {'calls':[]})
    monitor.sounds.classes=[{'ams2ClassNames':['GT3'],'maxSafeOilTemp':145,'maxSafeWaterTemp':120}]
    tick=replace(scene(1),local={'oil_c':100,'water_c':90,'speed':50,'local_sample_age_s':0})
    monitor.feed(tick,tick.cars[0],fahrenheit=True)
    assert requests[-1]['oil_limit']==145 and requests[-1]['water_limit']==120
    assert requests[-1]['fahrenheit'] and 'stalled' not in requests[-1]
    monitor.respond('WHAT_IS_MY_OIL_TEMP')
    assert requests[-1]['command']=='WHAT_IS_MY_OIL_TEMP' and not requests[-1]['reset']
    bad=replace(tick,t=1.1,local={**tick.local,'oil_c':None})
    assert not monitor.feed(bad,bad.cars[0]) and monitor.last_payload is None
    assert command_for("what's my oil temp?")=='WHAT_IS_MY_OIL_TEMP'
    assert command_for('what is the car ahead doing') is None


@pytest.mark.skipif(sys.platform!='win32',reason='Original C# .NET Framework host')
def test_original_engine_minute_average_transition_recovery_and_numeric_response(tmp_path):
    sounds=tmp_path/'sounds'
    folder(sounds,'engine_monitor/oil_temp_intro',['your oil temperature is'])
    folder(sounds,'engine_monitor/water_temp_intro',['your water temperature is'])
    monitor=EngineMonitor(root=tmp_path,sounds=sounds)
    monitor.start()
    try:
        assert monitor.ready.wait(10),monitor.error
        events=[]
        for i in range(990):
            t=i/4
            tick=replace(scene(t),local={'oil_c':170 if t<190 else 90,'water_c':150 if t<190 else 80,
                                        'speed':50,'local_sample_age_s':0})
            events += [(t,c) for c in monitor.feed(tick,tick.cars[0])]
        assert not monitor.error
        assert [c['folder'] for _,c in events]==[
            'engine_monitor/hot_oil_and_water','engine_monitor/all_clear']
        assert 180 < events[0][0] < 181 and 240 < events[1][0] < 242
        reply=monitor.respond('WHAT_ARE_MY_ENGINE_TEMPS')
        assert reply[0]['immediate'] and reply[0]['fragments']==[
            'engine_monitor/oil_temp_intro',90,'engine_monitor/water_temp_intro',80,'conditions/celsius']
        tick=replace(tick,t=t+.25)
        monitor.feed(tick,tick.cars[0],fahrenheit=True)
        assert monitor.respond('WHAT_IS_MY_OIL_TEMP')[0]['fragments']==[
            'engine_monitor/oil_temp_intro',194,'conditions/fahrenheit']
        monitor.reset()
        assert not monitor.feed(replace(tick,t=t+1,game_state=3),tick.cars[0])
    finally: monitor.close()


def test_composed_engine_reply_preserves_fragment_order_and_selected_identity(tmp_path):
    folder(tmp_path,'engine_monitor/oil_temp_intro',['your oil temperature is'])
    folder(tmp_path,'conditions/celsius',['celsius'])
    wav=pcm_wav(b'\1\0'*8820)
    voice=SimpleNamespace(get=lambda text:SimpleNamespace(data=wav))
    cc=CrewChiefVoice(CrewChiefSounds(tmp_path))
    cc.prepare(voice,['engine_monitor/oil_temp_intro','conditions/celsius'])
    text,data,source=cc.render({'fragments':['engine_monitor/oil_temp_intro',90,'conditions/celsius']},voice)
    assert text=='your oil temperature is ninety celsius' and source=='voice_pack'
    with wave.open(io.BytesIO(data)) as w: assert w.getnframes()/22050==pytest.approx(1.3,abs=2/22050)
