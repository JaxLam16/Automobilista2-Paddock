import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

from ams2season.skill_overlay import SkillOverlay, sample
from ams2season import shm as S
from test_skills import lap, measured
from test_practice_overlay import snapshot


def model(tmp_path):
    o=SkillOverlay(SimpleNamespace(lib=SimpleNamespace(root=tmp_path),recorder=SimpleNamespace(running=True)))
    o.start=lambda:None
    o.settings={**o.settings,'enabled':True}
    return o


def samples():
    p=lap();rows=[]
    for i,t in enumerate(p['t']):
        s={k:float(v[i]) for k,v in p.items() if hasattr(v,'shape')}
        rows.append({**s,'at':float(t),'lap':0,'driver':'Player','slot':0,'car':'Mustang','track':'Track','layout':'GP','length':1000,'session':'practice','active':True,'valid':True})
    return rows


def prime(o):
    o.update(samples()[0],now=0);o.corners=[{'name':'T1','apex':300}]


def test_defaults_and_independent_settings_are_persisted(tmp_path):
    o=model(tmp_path);assert o.settings['timing']=='exit' and o.settings['corners']==[]
    assert o.settings['size']=='compact' and o.settings['position']=='center'
    o.configure({'selected':'trail_braking','duration_s':8})
    new=SkillOverlay(o.app);assert new.settings['selected']=='trail_braking'
    assert not (tmp_path/'private_coach/settings.json').exists()
    assert not (tmp_path/'private_coach/overlay/settings.json').exists()


@pytest.mark.parametrize('body',[{'duration_s':0},{'duration_s':float('nan')},{'selected':'bogus'},
    {'skills':[]},{'selected':'brake_point','skills':['steering']},{'opacity':2},{'corners':'T1'},
    {'sessions':['replay']},{'enabled':'true'},{'voice':True}])
def test_reject_bad_configuration(tmp_path,body):
    o=model(tmp_path)
    with pytest.raises(ValueError):o.configure(body)
    assert not o.path.exists()


def test_after_exit_default_and_stale_invalid_garage_hide_immediately(tmp_path):
    o=model(tmp_path);prime(o)
    for s in samples():
        state=o.update(s,now=s['at'])
        if s['ld']<480:assert not state['visible']
    assert state['visible'] and not state['provisional'] and state['metric']['value'] is not None
    assert not o.update(s,now=s['at']+1)['visible']
    for key,value in [('valid',False),('active',False),('session','race')]:
        fresh={**s,key:value,'at':20,'t':20}
        assert not o.update(fresh,now=20)['visible']


def test_identity_switch_does_not_show_previous_driver_result(tmp_path):
    o=model(tmp_path);prime(o)
    for s in samples():o.update(s,now=s['at'])
    s={**s,'driver':'Other','at':13,'t':13}
    state=o.update(s,now=13);assert not state['visible'] and state['metric'] is None


def test_choose_corners_and_cycle_skills_without_toggling_radio(tmp_path):
    o=model(tmp_path);prime(o);o.configure({'corners':['T2'],'skills':['steering','peak_brake'],'selected':'steering'})
    for s in samples():o.update(s,now=s['at'])
    assert not o.visible
    assert o.command('next')['selected']=='peak_brake'
    assert o.command('previous')['selected']=='steering'
    assert not o.command('toggle')['enabled']


def test_live_reference_is_guarded_by_layout_length_and_car_or_class(tmp_path):
    from ams2season.skills import report
    from test_skills import lap
    o=model(tmp_path);d=tmp_path/'recordings'/'reference';d.mkdir(parents=True)
    meta={'track_location':'Track','track_variation':'GP','track_length':1000,'status':'complete',
          'local':{'name':'Reference','car':'GT-R','car_class':'GT3'}}
    (d/'session.json').write_text(json.dumps(meta))
    o.app.lib.recordings_dir=d.parent;o.app.lib.technique_cached=lambda path:{'skills':report([lap()],[{'name':'T1','apex':300}],1000)}
    o.configure({'reference':'reference','selected':'minimum_speed'})
    s={**samples()[0],'car_class':'GT3'};o.update(s,now=0)
    assert o.reference_info['kind']=='same_class' and o.reference_passes
    s={**s,'layout':'Other','at':.05,'t':.05};o.update(s,now=.05)
    assert not o.reference_passes and 'does not match' in o.reference_info['error']


def test_scalar_snapshot_guards_pit_pause_replay_and_validity():
    raw=S.SharedMemory();raw.mNumParticipants=1;raw.mViewedParticipantIndex=0
    raw.mParticipantInfo[0].mIsActive=True;raw.mParticipantInfo[0].mName=b'Player'
    raw.mCarName=b'Mustang';raw.mTrackLocation=b'Track';raw.mTrackVariation=b'GP'
    raw.mTrackLength=1000;raw.mSessionState=S.SESSION_PRACTICE;raw.mGameState=S.GAME_INGAME_PLAYING
    s=sample(raw,1);assert s['active'] and 'yaw_rate' in s and 'vel_lat' in s
    for k,v in [('mPitMode',4),('mGameState',S.GAME_INGAME_PAUSED),('mGameState',S.GAME_INGAME_REPLAY)]:
        r=copy.deepcopy(raw);setattr(r,k,v);assert not sample(r,1)['active']
    raw.mViewedParticipantIndex=-1;assert sample(raw,1) is None


@pytest.mark.skipif(sys.platform!='win32',reason='Windows passive overlay renderer')
def test_actual_native_panel_renders_measurement_without_activation(tmp_path):
    o=model(tmp_path);o.card=measured();o.visible=True
    state=tmp_path/'state.json';state.write_text(json.dumps(o.status()),encoding='utf-8')
    image=tmp_path/'panel.png'
    helper=Path(__file__).parents[1]/'ams2season/assets/skill_overlay.exe'
    result=subprocess.run([str(helper),'--render',str(state),str(image)],timeout=15,capture_output=True)
    assert result.returncode==0 and image.stat().st_size>1000
    labels=json.loads(Path(str(image)+'.labels.json').read_text())
    assert labels['no_activation'] and labels['metric']['label']=='Trail braking'
    assert labels['height']<=110 and labels['width']<=480


def test_http_settings_require_own_origin_and_save_only_skill_settings(tmp_path):
    import http.client,threading
    from ams2season.app import App,make_handler,_make_server
    app=App(tmp_path);app.skill_overlay.start=lambda:None
    server=_make_server(0,make_handler(app));threading.Thread(target=server.serve_forever,daemon=True).start()
    port=server.server_address[1]
    def request(origin):
        c=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        c.request('POST','/api/skills/overlay',body=json.dumps({'enabled':True,'selected':'trail_braking'}),headers={'Content-Type':'application/json','Origin':origin})
        r=c.getresponse();body=r.read();c.close();return r.status,body
    try:
        assert request('http://untrusted.test')[0]==403
        code,body=request('http://127.0.0.1:'+str(port));assert code==200
        assert json.loads(body)['selected']=='trail_braking'
        assert not (tmp_path/'private_coach/settings.json').exists()
    finally:server.shutdown();server.server_close();app.skill_overlay.close()
