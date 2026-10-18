"""Pinned downloads and immutable installs never prune private authoring/personal data."""
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import stat
import threading
import zipfile

import pytest

from ams2season.coach.packs import Pack, PackStore, asset_url
from test_coach_voice import audio,voice_batch


def archive(tmp_path,voice='original-test',fault=None,*,approved=False):
    pcm=audio(.8)
    data={'format':'paddock-voice-pack','schema':1,'voice_id':voice,'voice_name':voice,'version':'1.0.0',
          'rights':{'status':'cleared' if approved else 'private_experiment'},
          'clips':[{'id':'pit','text':'The car ahead is pitting.','radio':'clips/pit.wav',
                    'seconds':.8,'radio_sha256':hashlib.sha256(pcm).hexdigest()}]}
    if fault=='identity':data['voice_id']='someone-else'
    if fault=='checksum':data['clips'][0]['radio_sha256']='0'*64
    if fault=='duration':data['clips'][0]['seconds']=2
    if fault=='path':data['clips'][0]['radio']='../escape.wav'
    path=tmp_path/(voice+'.zip')
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as package:
        package.writestr('pack.json',json.dumps(data))
        package.writestr(data['clips'][0]['radio'],pcm)
        if fault=='extra':package.writestr('reference.raw.wav',pcm)
        if fault=='symlink':
            member=zipfile.ZipInfo('link.wav');member.create_system=3;member.external_attr=(stat.S_IFLNK|0o777)<<16
            package.writestr(member,b'../outside.wav')
    spec=Pack(voice,voice,'1.0.0',hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_size,
              distribution_approved=approved)
    return path,spec


def test_verified_install_is_immutable_and_previous_pack_is_kept_until_explicit_cleanup(tmp_path):
    store=PackStore(tmp_path)
    old,spec=archive(tmp_path);key=store.install(old,spec)
    assert store.cache(key).get('The car ahead is pitting.').seconds==.8
    assert store.install(old,spec)==key
    other,other_spec=archive(tmp_path,'other-test');other_key=store.install(other,other_spec)
    assert store.cache(key).index and store.cache(other_key).index
    protected=[]
    for folder in ('recordings','championships','backups','private_coach/references','private_coach/samples','private_coach/voice-bank'):
        path=tmp_path/folder/'preserve.txt';path.parent.mkdir(parents=True,exist_ok=True);path.write_text('keep');protected.append(path)
    assert store.cleanup_except(other_key)==[]
    assert not (store.base/key).exists() and (store.base/other_key).exists()
    assert all(p.read_text()=='keep' for p in protected)
    assert store.installed()[0]['key']==other_key


@pytest.mark.parametrize('fault',['identity','checksum','duration','path','extra','symlink'])
def test_bad_archive_cannot_replace_a_working_pack_or_escape_staging(tmp_path,fault):
    store=PackStore(tmp_path);old,spec=archive(tmp_path);working=store.install(old,spec)
    bad,bad_spec=archive(tmp_path,'other-test',fault)
    with pytest.raises((ValueError,KeyError)):store.install(bad,bad_spec)
    assert store.cache(working).index
    assert not (store.base/bad_spec.key).exists() and not (tmp_path/'escape.wav').exists()
    assert not list(store.base.glob('.stage-*'))


def test_modified_or_unmanaged_folders_are_never_deleted(tmp_path):
    store=PackStore(tmp_path);a,sa=archive(tmp_path);ka=store.install(a,sa)
    b,sb=archive(tmp_path,'other-test');kb=store.install(b,sb)
    user_file=store.base/ka/'user-note.txt';user_file.write_text('keep')
    unmanaged=store.base/'my-backup';unmanaged.mkdir();(unmanaged/'backup.txt').write_text('keep')
    warnings=store.cleanup_except(kb)
    assert warnings and user_file.read_text()=='keep' and unmanaged.exists()


def test_status_never_opens_a_staging_receipt_during_install(tmp_path,monkeypatch):
    store=PackStore(tmp_path);path,spec=archive(tmp_path);key=store.install(path,spec)
    stage=store.base/'.stage-in-progress';stage.mkdir()
    receipt=stage/'managed.json';receipt.write_text('{}')
    original=Path.read_text
    def guarded(path,*args,**kwargs):
        assert path!=receipt, 'Status must not open the install worker staging file'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',guarded)
    assert [p['key'] for p in store.installed()]==[key]


def test_transient_windows_sharing_failure_retries_same_verified_install(tmp_path,monkeypatch):
    store=PackStore(tmp_path);path,spec=archive(tmp_path);original=Path.rename;attempts=[]
    def sharing(path,target):
        if path.name.startswith('.stage-'):
            attempts.append(path)
            if len(attempts)<3:
                error=PermissionError('Synthetic Windows sharing violation');error.winerror=32
                raise error
        return original(path,target)
    monkeypatch.setattr(Path,'rename',sharing)
    monkeypatch.setattr('ams2season.coach.packs.time.sleep',lambda _:None)
    assert store.install(path,spec)==spec.key
    assert len(attempts)==3 and len(set(attempts))==1
    assert store.cache(spec.key).index and not list(store.base.glob('.stage-*'))


def test_sharing_retry_honours_cancellation_without_install_or_pruning(tmp_path,monkeypatch):
    store=PackStore(tmp_path);old,spec=archive(tmp_path);key=store.install(old,spec)
    path,new=archive(tmp_path,'new-original');cancel=threading.Event()
    def sharing(path,target):
        cancel.set()
        error=PermissionError('Synthetic Windows sharing violation');error.winerror=5
        raise error
    monkeypatch.setattr(Path,'rename',sharing)
    with pytest.raises(InterruptedError):store.install(path,new,cancel=cancel)
    assert store.cache(key).index and not (store.base/new.key).exists()
    assert not list(store.base.glob('.stage-*'))


def test_persistent_windows_permission_failure_is_bounded(tmp_path,monkeypatch):
    store=PackStore(tmp_path);path,spec=archive(tmp_path);attempts=[]
    def denied(path,target):
        attempts.append(path)
        error=PermissionError('Persistent synthetic access denied');error.winerror=5
        raise error
    monkeypatch.setattr(Path,'rename',denied)
    monkeypatch.setattr('ams2season.coach.packs.time.sleep',lambda _:None)
    with pytest.raises(PermissionError):store.install(path,spec)
    assert len(attempts)==5 and not store.installed()
    assert not list(store.base.glob('.stage-*'))


def test_sharing_retry_never_overwrites_a_new_destination(tmp_path,monkeypatch):
    store=PackStore(tmp_path);path,spec=archive(tmp_path)
    destination=store.base/spec.key
    def sharing(path,target):
        target.mkdir();(target/'user-note.txt').write_text('preserve')
        error=PermissionError('Synthetic concurrent destination');error.winerror=5
        raise error
    monkeypatch.setattr(Path,'rename',sharing)
    monkeypatch.setattr('ams2season.coach.packs.time.sleep',lambda _:None)
    with pytest.raises(ValueError,match='destination changed'):store.install(path,spec)
    assert (destination/'user-note.txt').read_text()=='preserve'
    assert not list(store.base.glob('.stage-*'))


def test_unknown_selected_pack_cannot_trigger_cleanup(tmp_path):
    store=PackStore(tmp_path);a,sa=archive(tmp_path);ka=store.install(a,sa)
    with pytest.raises((ValueError,OSError)):store.cleanup_except('jim-private')
    assert (store.base/ka).exists()
    voice_batch(tmp_path)
    assert store.cleanup_except('jim-private')==[]


@pytest.mark.parametrize('url',[
    'http://github.com/JaxLam16/Automobilista2-Paddock/releases/download/v1/voice.zip',
    'https://example.com/voice.zip',
    'https://github.com/other/repo/releases/download/v1/voice.zip',
    'https://github.com/JaxLam16/Automobilista2-Paddock/raw/main/voice.zip',
    'https://github.com/JaxLam16/Automobilista2-Paddock/releases/download/v1/voice.zip?token=secret',
])
def test_download_urls_are_pinned_release_assets_only(url):
    with pytest.raises(ValueError):asset_url(url)


class Response(io.BytesIO):
    def __init__(self,body):super().__init__(body);self.headers={'Content-Length':str(len(body))}


class Opener:
    def __init__(self,body):self.body=body;self.requests=[]
    def open(self,request,timeout):self.requests.append(request.full_url);return Response(self.body)


def test_on_demand_streamed_download_validates_bytes_then_installs(tmp_path):
    path,spec=archive(tmp_path,approved=True)
    url='https://github.com/JaxLam16/Automobilista2-Paddock/releases/download/voices-v1/original-test.zip'
    spec=replace(spec,url=url);opener=Opener(path.read_bytes());store=PackStore(tmp_path,opener=opener)
    assert opener.requests==[] and store.catalogue()==[]  # startup/status are offline
    progress=[];key=store.download(spec,progress=lambda done,total:progress.append((done,total)))
    assert opener.requests==[url] and progress[-1]==(spec.archive_bytes,spec.archive_bytes)
    assert store.cache(key).index and not list(store.base.glob('.download-*'))


def test_unapproved_bad_checksum_or_cancelled_download_preserves_existing_selection(tmp_path):
    path,spec=archive(tmp_path,approved=True)
    spec=replace(spec,url='https://github.com/JaxLam16/Automobilista2-Paddock/releases/download/v1/test.zip')
    store=PackStore(tmp_path,opener=Opener(path.read_bytes()))
    with pytest.raises(ValueError,match='approved'):store.download(replace(spec,distribution_approved=False))
    with pytest.raises(ValueError,match='checksum'):store.download(replace(spec,archive_sha256='0'*64))
    cancelled=threading.Event();cancelled.set()
    with pytest.raises(InterruptedError):store.download(spec,cancel=cancelled)
    assert not store.installed() and not list(store.base.glob('.download-*'))


def test_cancellation_after_clip_validation_removes_its_staging_files(tmp_path, monkeypatch):
    from ams2season.coach import packs
    path, spec = archive(tmp_path)
    store = PackStore(tmp_path)
    cancel = threading.Event()
    original = packs.VoiceCache
    def cancelled_validation(*args, **kwargs):
        cache = original(*args, **kwargs)
        cancel.set()
        return cache
    monkeypatch.setattr(packs, 'VoiceCache', cancelled_validation)
    with pytest.raises(InterruptedError):
        store.install(path, spec, cancel=cancel)
    assert not list(store.base.glob('.stage-*')) and not store.installed()


def test_malformed_unowned_receipts_do_not_break_status_or_trigger_deletion(tmp_path):
    store = PackStore(tmp_path)
    path, spec = archive(tmp_path)
    key = store.install(path, spec)
    (store.base/key/'managed.json').write_text('[]')
    assert store.installed() == []
    with pytest.raises(ValueError):
        store.cache(key)
    voice_batch(tmp_path)
    assert store.cleanup_except('jim-private') == []
    assert (store.base/key/'clips/pit.wav').is_file()
