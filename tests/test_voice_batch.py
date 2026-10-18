"""Generation guards run before any GPU/model import; cached resumes preserve clips."""
import hashlib
import json
import sys

import numpy as np
import pytest

from tools.voice.batch import Resources, inventory, preflight, reference_path


@pytest.mark.parametrize('resources,device,loaded,reason', [
    (Resources(True,12<<30,7000),'cuda',False,'Close AMS2'),
    (Resources(False,5<<30,7000),'cuda',False,'6GB'),
    (Resources(False,8<<30,None),'cuda',False,'4500MiB'),
    (Resources(False,8<<30,4000),'cuda',False,'4500MiB'),
    (Resources(False,1<<30,1000),'cuda',True,'1.5GB'),
    (Resources(True,8<<30,1000),'cuda',True,'Close AMS2'),
])
def test_preflight_refuses_game_or_resource_pressure(resources,device,loaded,reason):
    with pytest.raises(ValueError,match=reason):
        preflight(device,resources,loaded=loaded)


def test_loaded_model_does_not_require_its_own_allocated_memory_again():
    assert preflight('cuda',Resources(False,3<<30,1000),loaded=True)['free_gpu_mib'] == 1000
    assert preflight('cpu',Resources(False,8<<30))['free_gpu_mib'] is None


@pytest.mark.parametrize('phrases', [
    [{'id':'../escape','text':'Hello.'}],
    [{'id':'one','text':'Hello.'}]*2,
    [{'id':'one','text':'Bad\nline.'}],
    [{'id':'one','text':''}], [],
])
def test_inventory_rejects_unsafe_or_ambiguous_scripts(tmp_path,phrases):
    path=tmp_path/'inventory.json'
    path.write_text(json.dumps({'private':True,'publish_allowed':False,'phrases':phrases}))
    with pytest.raises(ValueError): inventory(path,tmp_path)


def test_inventory_stays_private(tmp_path):
    path=tmp_path/'inventory.json'
    data={'private':True,'publish_allowed':False,'phrases':[{'id':'one','text':'One.'}]}
    path.write_text(json.dumps(data))
    assert inventory(path,tmp_path)==data
    with pytest.raises(ValueError): inventory(path,tmp_path/'elsewhere')
    data['publish_allowed']=True
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError): inventory(path,tmp_path)


def test_new_voice_cannot_relabel_jims_default_reference(tmp_path):
    with pytest.raises(ValueError,match='own explicit private reference'):
        reference_path({},tmp_path,'different-voice')
    path=tmp_path/'reference.wav';path.write_bytes(b'fixture-reference')
    data={'reference':{'path':'reference.wav','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}
    assert reference_path(data,tmp_path,'different-voice')==path
    data['reference']['sha256']='0'*64
    with pytest.raises(ValueError,match='checksum'):reference_path(data,tmp_path,'different-voice')
    data['reference']['path']='../outside.wav'
    with pytest.raises(ValueError,match='inside private_coach'):reference_path(data,tmp_path,'different-voice')


def test_cached_generation_never_loads_model_and_keeps_limited_resume_manifest(tmp_path,monkeypatch):
    from tools.voice import generate_pilot as generate
    from ams2season import coach_audio
    monkeypatch.setattr(generate,'PRIVATE',tmp_path)
    (tmp_path/'references').mkdir()
    reference=tmp_path/'references/jim-reference.wav'
    reference.write_bytes(b'fixture-reference')
    refsha=hashlib.sha256(reference.read_bytes()).hexdigest()
    phrases=[{'id':'one','text':'One.'},{'id':'two','text':'Two.'}]
    path=tmp_path/'inventory.json'
    path.write_text(json.dumps({'private':True,'publish_allowed':False,'phrases':phrases}))
    output=tmp_path/'samples'; output.mkdir()
    for i,phrase in enumerate(phrases):
        raw=output/(phrase['id']+'.raw.wav')
        coach_audio.write_wav(raw,np.sin(np.arange(24000)*.1)*.1,24000)
        (output/(phrase['id']+'.raw.json')).write_text(json.dumps({
            'model_revision':generate.MODEL_REVISION,'reference_sha256':refsha,
            'text':phrase['text'],'temperature':.65,'seed':1701+i,
            'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest()}))
    def master(audio,sr,**kw):return audio,22050
    monkeypatch.setattr(coach_audio,'master_radio',master)
    # Importing torch or the speech library would fail this test rather than use a GPU.
    monkeypatch.setitem(sys.modules,'torch',None)
    monkeypatch.setitem(sys.modules,'chatterbox',None)
    monkeypatch.setattr(sys,'argv',['generate','--inventory',str(path),'--output',str(output)])
    generate.main()
    before=json.loads((output/'manifest.json').read_text())
    assert len(before['clips'])==2
    monkeypatch.setattr(sys,'argv',[*sys.argv,'--limit','1'])
    generate.main()
    after=json.loads((output/'manifest.json').read_text())
    assert len(after['clips'])==2 and after['clips'][1]==before['clips'][1]
    assert after['clips'][0]['radio_sha256']==before['clips'][0]['radio_sha256']
