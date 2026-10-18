"""Original number/SoundSet selection through metadata IPC; no physical audio."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import sys
import time

import pytest

from ams2season.coach.crew_audio import AudioMetadata,DEFAULTS,number_caption
from ams2season.coach.crew_spotter import ASSETS,CrewChiefSounds
from ams2season.coach.crew_voice import CrewChiefVoice
from ams2season.coach.speech import LocalRadio
from ams2season.coach.voice import pcm_wav
from test_crew_chief_voice_engine import folder

NATIVE=pytest.mark.skipif(sys.platform!='win32',reason='Original Framework metadata host')


def sound(path,name,byte=1):
    path.mkdir(parents=True,exist_ok=True)
    (path/name).write_bytes(pcm_wav(bytes([byte,0])*8820))


def metadata(tmp_path,**changes):
    host=AudioMetadata(root=tmp_path,sounds=tmp_path/'sounds')
    host.settings=json.loads(json.dumps(DEFAULTS));host.settings.update(changes)
    host.start();assert host.ready.wait(5),host.error
    return host


def test_original_number_sources_and_build_receipt():
    hashes={'NumberReaderEn.cs':'c1e8191cbfdf4a96757cc79a3ab6c3253e3a4bef1d322a9f4b3b43a0a543e106',
        'NumberReader.cs':'d1bfa457d9b166bc8bb07abcd3190f4d80f489371934afc1342ccc6a135d7119',
        'TimeSpanWrapper.cs':'51dfc264d1711b964f0c90102606f38c5b4d19689db14f0710aeb2495fffe3f1',
        'CarNumber.cs':'71bbfb04bf77b79e95030e58a3a67c2151a341333bc2914c96eebc90d4b84691'}
    receipt=json.loads((ASSETS/'audio_core.build.json').read_text(encoding='utf-8-sig'))
    for name,digest in {**receipt['sources'],**hashes}.items():
        assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()==digest
    assert hashlib.sha256((ASSETS/receipt.get('assembly_file','audio_core.dll')).read_bytes()).hexdigest()==receipt['assembly_sha256']


@NATIVE
@pytest.mark.parametrize('number,expected',[(0,['numbers/0']),(42,['numbers/42']),
    (-12,['numbers/minus','numbers/12']),(104,['numbers/1','numbers/hundred_and','numbers/4']),
    (1100,['numbers/11','numbers/hundred']),
    (10001,['numbers/10','numbers/thousand_and','numbers/1'])])
def test_original_integer_rules_and_long_form(tmp_path,number,expected):
    host=metadata(tmp_path)
    try:
        assert host.request('expand',fragments=[{'type':'integer','value':number,'short':False}])['folders']==expected
    finally:host.close()


@NATIVE
def test_original_short_hundreds_varies_between_two_valid_forms(tmp_path):
    host=metadata(tmp_path)
    try:
        forms={tuple(host.request('expand',fragments=[104])['folders']) for _ in range(50)}
        assert forms=={('numbers/1','numbers/04'),('numbers/1','numbers/hundred_and','numbers/4')}
    finally:host.close()


@NATIVE
def test_number_configuration_overrides_are_applied(tmp_path):
    options={**DEFAULTS['number_config'],'always_use_thousands':'true','say_and_between_hundred_and_units':'false'}
    host=metadata(tmp_path,number_config=options)
    try:
        assert host.request('expand',fragments=[{'type':'integer','value':1104,'short':False}])['folders']==[
            'numbers/1','numbers/thousand','numbers/1','numbers/hundred','numbers/4']
    finally:host.close()


@NATIVE
@pytest.mark.parametrize('value,expected',[('0',['numbers/0']),('00',['numbers/zerozero']),
    ('000',['numbers/double_oh','numbers/0']),('007',['numbers/double_oh','numbers/7']),
    ('601',['numbers/6','numbers/0','numbers/1']),('551',['numbers/5','numbers/5','numbers/1']),
    ('226',['numbers/2','numbers/2','numbers/6']),('126',['numbers/1','numbers/26'])])
def test_original_car_numbers_preserve_leading_zeros_and_grouping(tmp_path,value,expected):
    for name in ('zerozero','double_oh'):sound(tmp_path/'sounds/voice/numbers'/name,'1.wav')
    host=metadata(tmp_path)
    try:assert host.request('expand',fragments=[{'type':'car_number','value':value}])['folders']==expected
    finally:host.close()


@NATIVE
def test_original_time_rounding_precision_and_pause_metadata(tmp_path):
    host=metadata(tmp_path)
    try:
        assert host.request('expand',fragments=[{'type':'time','seconds':90.25,'precision':'HUNDREDTHS'}])['folders']==[
            'insert_pause:50','numbers/1_30','numbers/point25']
        # Original boundary rounding carries .999 into the next whole second.
        assert host.request('expand',fragments=[{'type':'time','seconds':59.999,'precision':'HUNDREDTHS'}])['folders']==[
            'numbers/1','numbers/minute']
    finally:host.close()


@NATIVE
def test_soundset_uses_a_shuffled_bag_instead_of_repeated_random_choice(tmp_path):
    base=tmp_path/'sounds/voice/spotter/car_left'
    for i in range(4):sound(base,str(i)+'.wav',i+1)
    host=metadata(tmp_path)
    try:
        names=[Path(host.request('render',fragments=['spotter/car_left'],t=100+i)['parts'][0]['file']).name for i in range(12)]
        for start in (0,4,8):assert set(names[start:start+4])=={'0.wav','1.wav','2.wav','3.wav'}
    finally:host.close()


@NATIVE
def test_required_prefix_without_selected_name_is_excluded(tmp_path):
    base=tmp_path/'sounds/voice/penalties/lap_deleted'
    sound(base,'1_rq_prefix_ok.wav');sound(base,'plain.wav')
    host=metadata(tmp_path)
    try:
        for i in range(8):
            parts=host.request('render',fragments=['penalties/lap_deleted'],t=100+i)['parts']
            assert [Path(p['file']).name for p in parts]==['plain.wav']
    finally:host.close()


@NATIVE
def test_personalisation_due_optional_prefix_and_next_call_uses_plain_version(tmp_path):
    sound(tmp_path/'sounds/personalisations/Jacks/prefixes_and_suffixes/ok','name.wav')
    base=tmp_path/'sounds/voice/penalties/lap_deleted'
    sound(base,'1_op_prefix_ok.wav')
    host=metadata(tmp_path,personalisation='Jacks')
    try:
        first=host.request('render',fragments=['penalties/lap_deleted'],t=100)['parts']
        assert [Path(p['file']).name for p in first]==['name.wav','1_op_prefix_ok.wav']
        second=host.request('render',fragments=['penalties/lap_deleted'],t=101)['parts']
        assert [Path(p['file']).name for p in second]==['1_op_prefix_ok.wav']
    finally:host.close()


@NATIVE
def test_zero_personalisation_interval_disables_name_and_original_pause_setting(tmp_path):
    sound(tmp_path/'sounds/personalisations/Jacks/prefixes_and_suffixes/ok','name.wav')
    sound(tmp_path/'sounds/voice/penalties/lap_deleted','1_op_prefix_ok.wav')
    host=metadata(tmp_path,personalisation='Jacks',min_time_between_personalised_messages=0,pause_between_message_fragments=70)
    try:
        result=host.request('render',fragments=['penalties/lap_deleted','insert_pause:25','penalties/lap_deleted','insert_pause:999'],t=100)
        assert [p.get('pause_ms') for p in result['parts']]==[None,70,25,70,None]
        assert len([p for p in result['parts'] if p.get('file')])==2
    finally:host.close()


@NATIVE
def test_original_filename_gender_and_swear_filters(tmp_path):
    base=tmp_path/'sounds/voice/spotter/car_left'
    for name in ('plain.wav','sweary_1.wav','male_2.wav'):sound(base,name)
    host=metadata(tmp_path,block_male_sounds=True,use_sweary_messages=False)
    try:
        for i in range(8):assert Path(host.request('render',fragments=['spotter/car_left'],t=i)['parts'][0]['file']).name=='plain.wav'
    finally:host.close()


@NATIVE
@pytest.mark.parametrize('fragment',['../../private.wav','TTS_IDENTIFIERanything',{'type':'car_number','value':'../2'},
    {'type':'time','seconds':-1,'precision':'TENTHS'},100000,1.2])
def test_unsupported_paths_speech_downloads_and_numbers_are_withheld(tmp_path,fragment):
    host=metadata(tmp_path)
    try:
        with pytest.raises(ValueError):host.request('render',fragments=[fragment])
    finally:host.close()


@NATIVE
def test_cached_selected_audio_and_uncaptioned_name_fallback_are_reported(tmp_path):
    sounds=tmp_path/'sounds';folder(sounds,'penalties/lap_deleted',['lap deleted'])
    base=sounds/'voice/penalties/lap_deleted';(base/'0.wav').rename(base/'1_op_prefix_ok.wav')
    (base/'subtitles.csv').write_text('1_op_prefix_ok.wav,"lap deleted"\n')
    sound(sounds/'personalisations/Jacks/prefixes_and_suffixes/ok','name.wav',2)
    voice=SimpleNamespace(get=lambda text:SimpleNamespace(data=pcm_wav(b'\3\0'*8820)))
    cc=CrewChiefVoice(CrewChiefSounds(sounds));assert cc.open_native(tmp_path,personalisation='Jacks',folders=['penalties/lap_deleted'],voice=voice),cc.native_error
    try:
        text,data,source=cc.choose('penalties/lap_deleted',t=100)
        assert source=='voice_pack_and_crew_chief_recording'
        assert 'lap deleted' in text and cc.status(['penalties/lap_deleted'])['uncaptioned_personalisation_files']==1
        played=[];radio=LocalRadio(voice,sink=(played.append,lambda:None),effect='off')
        try:
            assert radio.say('test',text,data=data,source=source)
            until=time.monotonic()+1
            while radio.busy and time.monotonic()<until:time.sleep(.005)
            assert len(played)==1
        finally:radio.close()
    finally:cc.close()


def test_unknown_decimal_caption_is_not_invented():
    assert number_caption('04')=='oh four'
    assert number_caption('hundred_and')=='hundred and'
    assert number_caption('point25') is None
    assert number_caption('1_30') is None


def test_metadata_transport_failure_keeps_exact_original_spotter_fallback(tmp_path):
    folder(tmp_path,'spotter/car_left',['on your left'])
    cc=CrewChiefVoice(CrewChiefSounds(tmp_path))
    def failed(*args,**kwargs):raise OSError('metadata transport unavailable')
    cc.native=SimpleNamespace(request=failed,close=lambda:None)
    text,data,source=cc.choose('spotter/car_left')
    assert text=='on your left' and source=='crew_chief_recording'
    assert cc.native is None and cc.native_error=='metadata transport unavailable'
    assert data==(tmp_path/'voice/spotter/car_left/0.wav').read_bytes()


@NATIVE
def test_real_service_starts_and_stops_metadata_with_a_disposable_silent_radio(tmp_path,monkeypatch):
    from test_coach_service import app_with_current,snapshot,snapshot_stream
    import ams2season.coach.service as module
    app=app_with_current(tmp_path)
    # The first audio catalogue scan can outlast a single sample's freshness.
    # A real active recorder continues feeding during service construction.
    with snapshot_stream(app,snapshot()):
        service=app.coach
        service.output='paddock';service.audio_enabled=True;service.tts_fallback=False
        # Keep the actual LocalRadio lifecycle, replacing only its physical sink.
        monkeypatch.setattr(module,'LocalRadio',lambda voice,**kwargs:LocalRadio(voice,sink=(lambda data:None,lambda:None),effect='off'))
        try:
            result=service.start()
            assert result['running'] and service.cc_voice.native is not None,service.cc_voice.native_error
            process=service.cc_voice.native.process
            service.stop()
            assert service.cc_voice.native is None and process.poll() is not None
        finally:service.close()
