"""Backed-up local Crew Chief configuration and the installed MQTTnet transport."""
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import socket
import struct
import sys
import threading
import time

import pytest

from ams2season.crew_chief import CrewChief, TEST_MESSAGE


@pytest.fixture
def radio(tmp_path, monkeypatch):
    install = tmp_path / 'install'
    install.mkdir()
    (install / 'CrewChiefV4.exe').write_bytes(b'fixture-not-executable')
    (install / 'MQTTnet.dll').write_bytes(b'fixture')
    (install / 'mqtt_telemetry.json').write_text(json.dumps({'Server':'original.example','Port':1883,'Channels':[]}))
    documents = tmp_path / 'documents/CrewChiefV4'
    (documents / 'Profiles').mkdir(parents=True)
    (documents / 'Profiles/defaultSettings.json').write_text(json.dumps({'userSettings':{
        'enable_mqtt_telemetry':False,'mqtt_topic_drivername':'Original','messages_volume':0.75}}))
    service = CrewChief(tmp_path, documents=documents)
    monkeypatch.setattr(service, '_is_running', lambda **kwargs:False)
    service.fixture_exe = str(install / 'CrewChiefV4.exe')
    return service


def configure(radio, **kwargs):
    return radio.configure({'exe':radio.fixture_exe,**kwargs})


def test_viewing_status_is_read_only(radio):
    status = radio.status()
    assert not status['configured'] and not status['listening']
    assert not radio.dir.exists() and not radio.mqtt_path.exists()
    assert radio.profiles() == ['defaultSettings.json']


def test_setup_copies_profile_and_restores_original_bytes(radio):
    original_profile = (radio.documents / 'Profiles/defaultSettings.json').read_bytes()
    original_mqtt = b'{ "Server": "previous", "Channels": [] }\n'
    radio.mqtt_path.write_bytes(original_mqtt)
    result = configure(radio)
    assert result['configured'] and not result['listening']
    config = json.loads(radio.mqtt_path.read_text())
    assert config['Server'] == '127.0.0.1' and config['Login'] == 'paddock'
    assert config['SubscribeTopic'] == '/paddock/coach' and config['Channels'] == []
    assert config['DebugResponse'] and not config['AllowSoundDownload']
    assert 'token' not in result and config['Password'] not in json.dumps(result)
    profile = json.loads(radio.profile_path.read_text())['userSettings']
    assert profile['enable_mqtt_telemetry'] and profile['mqtt_topic_drivername'] == 'Paddock'
    assert profile['messages_volume'] == 0.75
    assert (radio.documents / 'Profiles/defaultSettings.json').read_bytes() == original_profile
    # Crew Chief may rewrite whitespace/order without changing the configuration.
    radio.profile_path.write_text(json.dumps({'userSettings':profile},separators=(',',':')))
    restored = radio.restore()
    assert not restored['configured'] and radio.mqtt_path.read_bytes() == original_mqtt
    assert not radio.profile_path.exists()
    assert list((radio.dir / 'backups').glob('*/receipt.json'))


def test_originally_missing_mqtt_file_removed_on_restore(radio):
    configure(radio)
    radio.restore()
    assert not radio.mqtt_path.exists()


def test_backup_restore_survives_moving_paddock_folder(radio,tmp_path,monkeypatch):
    configure(radio)
    relocated=tmp_path/'new-version'
    shutil.copytree(radio.dir,relocated/'crew_chief')
    moved=CrewChief(relocated,documents=radio.documents)
    monkeypatch.setattr(moved,'_is_running',lambda **kwargs:False)
    assert not moved.restore()['configured']
    assert not radio.mqtt_path.exists() and not radio.profile_path.exists()


def test_setup_refuses_running_app_and_unreadable_existing_profile(radio, monkeypatch):
    monkeypatch.setattr(radio,'_is_running',lambda **kwargs:True)
    with pytest.raises(ValueError,match='Close Crew Chief'):
        configure(radio)
    monkeypatch.setattr(radio,'_is_running',lambda **kwargs:False)
    radio.profile_path.write_text('user-owned profile')
    with pytest.raises(ValueError,match='existing Paddock.json profile is not readable'):
        configure(radio)
    assert radio.profile_path.read_text() == 'user-owned profile'
    assert not radio.mqtt_path.exists() and not radio.dir.exists()


def test_setup_reuses_existing_profile_and_restores_original_bytes(radio):
    default = radio.documents / 'Profiles/defaultSettings.json'
    original_default = default.read_bytes()
    original_profile = b'{ "userSettings": {"messages_volume": 0.42, "tts_setting_listprop": "ANY_TIME", "enable_mqtt_telemetry": false, "mqtt_topic_drivername": "Previous"}, "custom": {"keep": true} }\n'
    original_mqtt = b'{ "Server": "previous", "Channels": [] }\n'
    radio.profile_path.write_bytes(original_profile)
    radio.mqtt_path.write_bytes(original_mqtt)
    assert radio.status()['profile_exists'] and not radio.status()['configured']
    # An existing Paddock profile is authoritative, even with no base selection.
    result = configure(radio,base_profile='missing-base.json')
    profile = json.loads(radio.profile_path.read_text())
    assert result['configured']
    assert profile['userSettings']['messages_volume'] == 0.42
    assert profile['userSettings']['tts_setting_listprop'] == 'ANY_TIME'
    assert profile['userSettings']['enable_mqtt_telemetry']
    assert profile['userSettings']['mqtt_topic_drivername'] == 'Paddock'
    assert profile['custom'] == {'keep':True}
    assert default.read_bytes() == original_default
    radio.restore()
    assert radio.profile_path.read_bytes() == original_profile
    assert radio.mqtt_path.read_bytes() == original_mqtt


def test_existing_profile_does_not_require_another_profile(radio):
    (radio.documents / 'Profiles/defaultSettings.json').unlink()
    radio.profile_path.write_text(json.dumps({'userSettings':{'messages_volume':0.42}}))
    assert configure(radio)['configured'] and radio.profiles() == []


@pytest.mark.parametrize('content',['{}','{"userSettings": []}','[]','not JSON'])
def test_invalid_existing_profile_cannot_be_overwritten(radio,content):
    radio.profile_path.write_text(content)
    with pytest.raises(ValueError,match='existing Paddock.json profile is not readable'):
        configure(radio)
    assert radio.profile_path.read_text() == content
    assert not radio.mqtt_path.exists() and not radio.dir.exists()


def test_failed_reuse_restores_existing_profile_and_mqtt(radio,monkeypatch):
    original_profile = b'{ "userSettings": {"messages_volume": 0.42} }\n'
    original_mqtt = b'{ "Server": "original" }\n'
    radio.profile_path.write_bytes(original_profile)
    radio.mqtt_path.write_bytes(original_mqtt)
    monkeypatch.setattr(radio,'_save',lambda: (_ for _ in ()).throw(OSError('fixture save failure')))
    with pytest.raises(OSError):
        configure(radio)
    assert radio.profile_path.read_bytes() == original_profile
    assert radio.mqtt_path.read_bytes() == original_mqtt


@pytest.mark.parametrize('body',[{'port':0},{'port':65536},{'port':'oops'},{'base_profile':'../private.json'},{'exe':'missing.exe'}])
def test_invalid_setup_cannot_modify_documents(radio,body):
    with pytest.raises(ValueError):
        configure(radio,**body)
    assert not radio.mqtt_path.exists() and not radio.profile_path.exists()


def test_failed_setup_rolls_back_all_external_changes(radio,monkeypatch):
    monkeypatch.setattr(radio,'_save',lambda: (_ for _ in ()).throw(OSError('fixture save failure')))
    with pytest.raises(OSError):
        configure(radio)
    assert not radio.profile_path.exists() and not radio.mqtt_path.exists()


def test_restore_preserves_newer_edits(radio):
    configure(radio)
    saved = radio.mqtt_path.read_bytes()
    profile = json.loads(radio.profile_path.read_text())
    profile['userSettings']['messages_volume'] = 0.6
    radio.profile_path.write_text(json.dumps(profile))
    with pytest.raises(ValueError,match='changed after'):
        radio.restore()
    assert radio.mqtt_path.read_bytes() == saved
    assert json.loads(radio.profile_path.read_text())['userSettings']['messages_volume'] == 0.6


def test_readiness_is_not_claimed_as_audible_confirmation(radio):
    with pytest.raises(ValueError,match='Wait for Crew Chief'):
        radio.test()
    radio.last_test = {'id':'123','message':TEST_MESSAGE,'sent':True,'received':False,'heard':False}
    radio._host_event({'type':'ack','payload':json.dumps({'response':json.dumps({'message':TEST_MESSAGE})})})
    assert radio.last_test['received'] and not radio.last_test['heard']
    with pytest.raises(ValueError):
        radio.heard('stale')
    assert radio.heard('123')['heard']


def test_cached_audio_setup_adds_immutable_backups_and_full_restore_is_exact(radio):
    initial = (radio.documents/'Profiles/defaultSettings.json').read_bytes()
    configure(radio)
    base_receipt = dict(radio.settings['receipt'])
    base_folder = radio.dir/base_receipt['directory']
    base_files = {p.name: p.read_bytes() for p in base_folder.iterdir()}
    profile = json.loads(radio.profile_path.read_text())
    assert radio.prepare_audio()['cached_audio_configured']
    updated = json.loads(radio.profile_path.read_text())
    assert updated['userSettings']['enable_shared_memory'] is True
    assert updated['userSettings']['messages_volume'] == profile['userSettings']['messages_volume']
    assert json.loads(radio.mqtt_path.read_text())['AllowSoundDownload'] is True
    assert {p.name:p.read_bytes() for p in base_folder.iterdir()} == base_files
    radio.restore()
    assert (radio.documents/'Profiles/defaultSettings.json').read_bytes() == initial
    assert not radio.profile_path.exists() and not radio.mqtt_path.exists()
    assert len(list((radio.dir/'backups').glob('*/receipt.json'))) == 2


def test_cached_audio_setup_reuses_existing_profile_and_restores_it_byte_for_byte(radio):
    original = b'{"userSettings":{"messages_volume":0.33,"custom_pref":7},"custom":true}\n'
    radio.profile_path.write_bytes(original)
    configure(radio)
    radio.prepare_audio()
    assert json.loads(radio.profile_path.read_text())['custom'] is True
    radio.restore()
    assert radio.profile_path.read_bytes() == original


def test_cached_audio_preserves_newer_preferences_and_running_app(radio,monkeypatch):
    configure(radio)
    before = radio.profile_path.read_bytes()
    monkeypatch.setattr(radio,'_is_running',lambda **kw:True)
    with pytest.raises(ValueError,match='Close Crew Chief'):
        radio.prepare_audio()
    assert radio.profile_path.read_bytes() == before
    monkeypatch.setattr(radio,'_is_running',lambda **kw:False)
    profile=json.loads(before); profile['userSettings']['messages_volume']=.2
    radio.profile_path.write_text(json.dumps(profile))
    radio.prepare_audio()
    saved=radio.profile_path.read_bytes()
    with pytest.raises(ValueError,match='Newer Crew Chief preferences'):
        radio.restore()
    assert radio.profile_path.read_bytes() == saved


def test_failed_cached_audio_setup_rolls_back_without_changing_prior_backup(radio,monkeypatch):
    configure(radio)
    before={p:p.read_bytes() for p in (radio.profile_path,radio.mqtt_path)}
    monkeypatch.setattr(radio,'_save',lambda: (_ for _ in ()).throw(OSError('fixture write failed')))
    with pytest.raises(OSError): radio.prepare_audio()
    assert all(p.read_bytes()==data for p,data in before.items())
    assert not radio.settings.get('audio_receipt')


@pytest.mark.parametrize('file,key,value', [
    ('mqtt','Server','other.example'), ('mqtt','Port',1883),
    ('mqtt','Password','changed'), ('mqtt','SubscribeTopic','/other'),
    ('mqtt','UseTLS',True), ('profile','enable_mqtt_telemetry',False),
    ('profile','mqtt_topic_drivername','Other'),
])
def test_cached_audio_setup_preserves_altered_connection(radio,file,key,value):
    configure(radio)
    path = radio.mqtt_path if file == 'mqtt' else radio.profile_path
    data = json.loads(path.read_text())
    (data if file == 'mqtt' else data['userSettings'])[key] = value
    path.write_text(json.dumps(data))
    before = {p:p.read_bytes() for p in (radio.mqtt_path,radio.profile_path)}
    backups = list((radio.dir/'backups').glob('*/receipt.json'))
    with pytest.raises(ValueError,match='connection settings changed'):
        radio.prepare_audio()
    assert all(p.read_bytes() == content for p,content in before.items())
    assert list((radio.dir/'backups').glob('*/receipt.json')) == backups
    assert not radio.settings.get('audio_receipt')


@pytest.mark.parametrize('url',[
    'http://example.com:8777/api/coach/audio/'+'a'*48+'.wav',
    'http://localhost:8777/api/coach/audio/'+'a'*48+'.wav',
    'http://127.0.0.1:8777/private_coach/references/jim-reference.wav',
    'http://127.0.0.1:8777/api/coach/audio/'+'a'*48+'.wav?anything=1',
    'https://127.0.0.1:8777/api/coach/audio/'+'a'*48+'.wav',
])
def test_cached_audio_transport_refuses_arbitrary_urls_even_before_connecting(radio,url):
    with pytest.raises(ValueError,match='one-use local'):
        radio.submit_audio(url)


def _wait(test, timeout=10):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if test(): return
        time.sleep(0.03)
    raise AssertionError('Timed out waiting for local radio state')


def _string(text):
    data = text.encode()
    return struct.pack('!H',len(data)) + data


def _packet(header,data):
    length = len(data)
    prefix = bytearray([header])
    while True:
        digit = length % 128
        length //= 128
        prefix.append(digit | (128 if length else 0))
        if not length: break
    return bytes(prefix)+data


def _recv_exact(sock,n):
    chunks = b''
    while len(chunks) < n:
        more = sock.recv(n-len(chunks))
        if not more: raise EOFError('MQTT connection closed')
        chunks += more
    return chunks


def _recv(sock):
    header = _recv_exact(sock,1)[0]
    length, shift = 0, 0
    while True:
        digit = _recv_exact(sock,1)[0]
        length += (digit & 127) << shift
        if not digit & 128: break
        shift += 7
    return header,_recv_exact(sock,length)


@pytest.mark.skipif(sys.platform!='win32',reason='Installed Windows MQTTnet transport')
def test_real_mqttnet_transport_auth_subscription_ack_and_no_replay(radio):
    library = Path(r'C:\Program Files (x86)\Britton IT Ltd\CrewChiefV4\MQTTnet.dll')
    if not library.exists(): pytest.skip('Crew Chief is not installed on this test machine')
    shutil.copy2(library,Path(radio.fixture_exe).parent/'MQTTnet.dll')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0))
        port = probe.getsockname()[1]
    configure(radio,port=port)
    radio.start()
    try:
        def connect(password):
            sock = socket.create_connection(('127.0.0.1',port),timeout=10)
            sock.settimeout(5)
            sock.sendall(_packet(0x10,_string('MQTT')+bytes([4,0xc2,0,60])+_string('paddock-qa')+_string('paddock')+_string(password)))
            ack = _recv(sock)
            return sock,ack
        bad,ack = connect('wrong')
        assert ack == (0x20,b'\0\x04')
        bad.close()
        sock,ack = connect(radio.settings['token'])
        assert ack == (0x20,b'\0\0')
        sock.sendall(_packet(0x82,b'\0\x01'+_string('/unrelated')+b'\0'))
        assert _recv(sock) == (0x90,b'\0\x01\x80')
        sock.sendall(_packet(0x82,b'\0\x02'+_string('/paddock/coach/Paddock')+b'\0'))
        assert _recv(sock) == (0x90,b'\0\x02\0')
        _wait(lambda: radio.status()['connected'])
        sent = radio.test()
        header,data = _recv(sock)
        assert header == 0x30
        n = struct.unpack('!H',data[:2])[0]
        assert data[2:2+n].decode() == '/paddock/coach/Paddock'
        message = json.loads(data[2+n:])
        # A radio check must wake Crew Chief's immediate audio queue; its
        # ordinary queue depends on game ticks even after an MQTT receipt ACK.
        assert message == {'message':TEST_MESSAGE,'distance':0,'priority':0,'immediate':True}
        debug = json.dumps({'response':json.dumps(message)}).encode()
        sock.sendall(_packet(0x30,_string('/paddock/coach/_debug/Paddock')+debug))
        _wait(lambda:radio.last_test['received'])
        assert sent['sent'] and not radio.last_test['heard']
        sock.sendall(b'\xc0\0')
        assert _recv(sock) == (0xd0,b'')
        sock.close()
        _wait(lambda:not radio.status()['connected'])
        # A new subscriber cannot get an old radio check.
        sock,ack = connect(radio.settings['token'])
        sock.sendall(_packet(0x82,b'\0\x03'+_string('/paddock/coach/Paddock')+b'\0'))
        assert _recv(sock)[0] == 0x90
        sock.settimeout(0.2)
        with pytest.raises(socket.timeout): sock.recv(1)
        sock.close()
    finally:
        radio.stop(persist=False)
    assert not radio.status()['listening']
    # Stop/start reuses the configured port and does not replay the old check.
    radio.start()
    try:
        assert radio.status()['listening'] and not radio.status()['connected']
    finally:
        radio.stop(persist=False)


@pytest.mark.skipif(sys.platform!='win32',reason='Installed Windows MQTTnet transport')
def test_cached_audio_regular_queue_and_just_in_time_http_revalidation(radio,tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace
    from ams2season.app import App, make_handler, _make_server
    from ams2season.coach.engine import CoachEngine
    from ams2season.coach.radio import Scheduler, RadioLog
    from ams2season.coach.audio import SILENCE
    from test_coach_voice import voice_batch
    from test_coach_radio import context, message
    library=Path(r'C:\Program Files (x86)\Britton IT Ltd\CrewChiefV4\MQTTnet.dll')
    if not library.exists():pytest.skip('Crew Chief is not installed')
    shutil.copy2(library,Path(radio.fixture_exe).parent/'MQTTnet.dll')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    configure(radio,port=port)
    radio.prepare_audio()
    radio.start()
    from ams2season.coach.catalogue import CATALOGUE
    root=tmp_path/'app';root.mkdir()
    texts=[text.format(relation=relation) for relation in ('car ahead','car behind') for text in CATALOGUE['X-15'].phrases]
    texts.append(texts[1]+' '+texts[4])
    voice_batch(root,texts=texts)
    app=App(root);app._crew_chief=radio
    server=_make_server(0,make_handler(app));app.port=server.server_address[1]
    threading.Thread(target=server.serve_forever,daemon=True).start()
    service=app.coach;service.audio_enabled=True
    service.thread=SimpleNamespace(is_alive=lambda:True)
    service.engine=CoachEngine('Player',Scheduler(log=RadioLog(root/'private_coach/radio.jsonl',deferred=True),voice_duration=service.voice.duration))
    sock=None
    def fetch(url):
        from urllib.parse import urlparse
        parsed=urlparse(url)
        connection=http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=5)
        connection.request('GET',parsed.path)
        response=connection.getresponse();data=response.read();connection.close()
        assert response.status==200
        return data
    try:
        sock=socket.create_connection(('127.0.0.1',port),timeout=5);sock.settimeout(5)
        sock.sendall(_packet(0x10,_string('MQTT')+bytes([4,0xc2,0,60])+_string('cached-audio-qa')+_string('paddock')+_string(radio.settings['token'])))
        assert _recv(sock)==(0x20,b'\0\0')
        sock.sendall(_packet(0x82,b'\0\x01'+_string('/paddock/coach/Paddock')+b'\0'))
        assert _recv(sock)==(0x90,b'\0\x01\0')
        _wait(lambda:radio.audio_transport_status()['connected'])
        for index,invalid in enumerate((False,True)):
            ctx=context(t=100+index*5,window_s=4)
            service.engine.context=ctx
            m=message(ctx,id=str(index),key='pit:'+str(index))
            assert service.engine.radio.offer(m,ctx)
            selected=service.engine.radio.select(ctx)
            assert selected is not None
            service._submit_audio(selected)
            header,data=_recv(sock)
            assert header==0x30
            n=struct.unpack('!H',data[:2])[0]
            payload=json.loads(data[2+n:])
            assert payload['immediate'] is False and payload['priority']==0 and payload['distance']==0
            assert payload['message'].startswith(f'http://127.0.0.1:{app.port}/api/coach/audio/')
            service.engine.context=replace(ctx,brake=.8) if invalid else ctx
            service.origin=time.perf_counter()-ctx.t
            body=fetch(payload['message'])
            assert (body==SILENCE) is invalid
            assert fetch(payload['message'])==SILENCE
        assert service.engine.radio.log.counts['audio_served']==1
        assert service.engine.radio.log.counts['audio_withheld']==1
        # A later full cached bundle goes through the same real transport. A
        # changed secondary fact must silence the entire clip at the HTTP fetch.
        from test_coach_bundles import pair, ready_context
        ctx=ready_context(t=112,window_s=4)
        service.engine.context=ctx
        for part in pair(ctx):assert service.engine.radio.offer(part,ctx)
        selected=service.engine.radio.select(ctx)
        assert len(selected.calls)==2
        service._submit_audio(selected)
        _,data=_recv(sock);n=struct.unpack('!H',data[:2])[0]
        payload=json.loads(data[2+n:])
        service.engine.context=replace(ctx,facts={'pit:a':1,'pit:b':0})
        service.origin=time.perf_counter()-ctx.t
        assert fetch(payload['message'])==SILENCE
        assert service.engine.radio.log.counts['audio_withheld']==2
        assert service.engine.radio.log.events[-1]['bundle_ids']==['ahead','behind']
        # Check the C# boundary independently of Python URL validation.
        radio.process.stdin.write(json.dumps({'type':'audio','id':'bad','url':'http://external.example/api/coach/audio/'+'a'*48+'.wav'})+'\n')
        radio.process.stdin.flush();sock.settimeout(.2)
        with pytest.raises(socket.timeout):sock.recv(1)
    finally:
        if sock:sock.close()
        service.thread=None;service.close()
        server.shutdown();server.server_close()
        radio.stop(persist=False)


def test_api_assets_and_cross_site_guard(tmp_path,radio):
    from ams2season.app import App,make_handler,_make_server
    app = App(tmp_path)
    app._crew_chief = radio
    server = _make_server(0,make_handler(app))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    port = server.server_address[1]
    def request(method,path,body=None,headers=None):
        connection = http.client.HTTPConnection('127.0.0.1',port,timeout=30)
        connection.request(method,path,body=json.dumps(body) if body is not None else None,
                           headers=headers or {'Content-Type':'application/json'})
        response=connection.getresponse()
        return response.status,response.read()
    try:
        assert request('GET','/crew-chief.js')[0] == 200
        status,data = request('GET','/api/crew-chief')
        assert status == 200 and not json.loads(data)['configured']
        assert request('POST','/api/crew-chief/configure',{}, {'Content-Type':'application/json','Origin':'http://other.example'})[0] == 403
        assert request('POST','/api/crew-chief/configure',{}, {'Content-Type':'text/plain'})[0] == 415
        assert not radio.mqtt_path.exists()
    finally:
        server.shutdown()
