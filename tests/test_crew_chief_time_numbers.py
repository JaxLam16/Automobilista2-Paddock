"""Numeric value substitution; never invent original recording transcripts."""
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,sys

import pytest

from ams2season.coach.crew_audio import time_number_phrase,number_caption
from ams2season.coach.crew_voice import CrewChiefVoice
from ams2season.coach.crew_spotter import CrewChiefSounds,ASSETS
from ams2season.coach.voice import pcm_wav
from test_crew_chief_audio_core import sound


@pytest.mark.parametrize('name,text',[
    ('1_01','one oh one'),('1_09','one oh nine'),('1_10','one ten'),
    ('1_38','one thirty-eight'),('2_59','two fifty-nine'),
    ('point00','point zero zero'),('point01','point zero one'),
    ('point10','point one zero'),('point76','point seven six'),('point99','point nine nine'),
    ('point1seconds','point one seconds'),('point9seconds','point nine seconds')])
def test_native_time_value_and_decimal_precision_have_canonical_rendering(name,text):
    assert time_number_phrase(name)==text
    assert number_caption(name) is None  # rendering is not a claimed WAV transcript


@pytest.mark.parametrize('name',['1_00','2_60','3_38','1_1','1_-1','point100','point-1','../point00','unknown','38','1point8seconds'])
def test_no_unbounded_or_unrelated_folder_inference(name):
    assert time_number_phrase(name) is None


@pytest.mark.parametrize('cached,selected,expected',[(True,True,'voice_pack'),(False,True,'crew_chief_recording'),(True,False,'crew_chief_recording')])
def test_cached_value_substitutes_whole_clip_or_reports_original_fallback(tmp_path,cached,selected,expected):
    base=tmp_path/'sounds/voice/numbers/1_38';sound(base,'1_38.wav',1)
    ai=pcm_wav(b'\3\0'*8820);cc=CrewChiefVoice(CrewChiefSounds(tmp_path/'sounds'))
    voice=SimpleNamespace(get=lambda text:SimpleNamespace(data=ai) if cached else None)
    cc.number_folders=('numbers/1_38',);cc.prepare(voice,cc.number_folders)
    text,data,source=cc.choose('numbers/1_38',selected=selected)
    assert source==expected
    assert data==(ai if expected=='voice_pack' else (base/'1_38.wav').read_bytes())
    status=cc.status([])['numeric']
    assert status['uncaptioned_folders']==1 and status['time_values']==1
    assert status['time_values_cached']==int(cached)
    assert status['uncaptioned_fallback_folders']==int(not cached)
    if expected=='voice_pack':assert text=='one thirty-eight'


@pytest.mark.skipif(sys.platform!='win32',reason='Original .NET Framework audio metadata')
def test_native_original_file_selection_and_precision_are_unchanged(tmp_path):
    sounds=tmp_path/'sounds';names=('1_38','point76','31','point00')
    for name in names:sound(sounds/'voice/numbers'/name,name+'.wav',1)
    ai=pcm_wav(b'\4\0'*8820);voice=SimpleNamespace(get=lambda _:SimpleNamespace(data=ai))
    cc=CrewChiefVoice(CrewChiefSounds(sounds))
    folders=['numbers/'+n for n in names]
    assert cc.open_native(tmp_path,folders=folders,voice=voice),cc.native_error
    try:
        native=cc.native.request('render',fragments=['numbers/1_38','numbers/point76'],t=1)
        assert [Path(p['file']).parent.name for p in native['parts']]==['1_38','point76']
        text,data,source=cc.render({'fragments':['numbers/1_38','insert_pause:50','numbers/point76']},voice,t=2)
        assert source=='voice_pack' and text=='one thirty-eight point seven six'
        assert len(data)>len(ai)*2-44
        assert cc.render({'fragments':['numbers/31','numbers/point00']},voice,t=3)[0]=='thirty-one point zero zero'
        assert cc.render({'fragments':['numbers/1_38']},voice,selected=False,t=4)[2]=='crew_chief_recording'
    finally:cc.close()


def test_original_numeric_decision_sources_are_still_pinned():
    for build in ('mapper_core','audio_core'):
        receipt=json.loads((ASSETS/(build+'.build.json')).read_text(encoding='utf-8-sig'))
        assert hashlib.sha256((ASSETS/receipt['assembly_file']).read_bytes()).hexdigest()==receipt['assembly_sha256']
        for name in ('NumberReaderEn.cs','NumberReader.cs','TimeSpanWrapper.cs'):
            assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()==receipt['sources'][name]


def test_new_voice_cache_clears_a_previous_missing_time_value(tmp_path):
    sound(tmp_path/'voice/numbers/point76','point76.wav',1)
    cc=CrewChiefVoice(CrewChiefSounds(tmp_path));cc.number_folders=('numbers/point76',)
    cc.prepare(SimpleNamespace(get=lambda _:None),cc.number_folders)
    assert cc.status([])['numeric']['time_values_cached']==0
    cc.prepare(SimpleNamespace(get=lambda _:SimpleNamespace(data=pcm_wav(b'\5\0'*8820))),cc.number_folders)
    assert cc.status([])['numeric']['time_values_cached']==1
