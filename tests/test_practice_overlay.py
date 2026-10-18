import copy
import json
import time
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from ams2season import shm as S
from ams2season.app import App
from ams2season.practice_overlay import PracticeOverlay, checklist, garage_sample
from test_engineer_live_start import live_app, snapshot as engineer_snapshot


def snapshot(**changes):
    raw = engineer_snapshot(**changes)
    raw.mParticipantInfo[0].mName = b'Player'
    return raw


def advice():
    return {'car':'Mustang GT','track':'Watkins_Glen','layout':'GP_Inner_Loop','runs':[{
        'id':2,'decisions':{},'recommendations':[
            {'id':'pressure_fl','setting':'pressure_fl','ticks':-2,'category':'tyre_contact','priority':1,
             'why':'Hot pressure above target.','confidence':'high'},
            {'id':'camber_fl','setting':'camber_fl','ticks':1,'category':'tyre_contact','priority':2,
             'why':'Outer shoulder hotter.','confidence':'medium'}]}]}


def programme(goal='practice2'):
    return {'active':True,'goal':goal,'source':'screen','detected':'practice2','objectives':[
        {'id':'tyres:clean','project':'Tyre contact','text':'Set one clean flying lap.','laps':0,'actual':None,'met':False}]}


def model(tmp_path):
    overlay=PracticeOverlay(App(tmp_path));overlay.enabled=True
    return overlay


@pytest.mark.parametrize('changes',[
    {'mPitMode':0},{'mPitMode':1},{'mPitMode':2},{'mPitMode':3},{'mPitMode':5},
    {'mSpeed':1},{'mSpeed':float('nan')},{'mSessionState':S.SESSION_RACE},
    {'mSessionState':S.SESSION_QUALIFY},{'mGameState':S.GAME_INGAME_REPLAY},
    {'mGameState':S.GAME_FRONT_END},{'mViewedParticipantIndex':-1},
    {'mCarName':b''},{'mTrackLength':0},
])
def test_only_stationary_practice_garage_opens(tmp_path,changes):
    o=model(tmp_path)
    raw=snapshot(mPitMode=4,mSpeed=0)
    for k,v in changes.items():setattr(raw,k,v)
    s=garage_sample(raw,time.perf_counter())
    assert not o.update(s,advice(),programme())['visible']


@pytest.mark.parametrize('game',[S.GAME_INGAME_PLAYING,S.GAME_INGAME_PAUSED,S.GAME_INGAME_INMENU_TIME_TICKING])
def test_garage_menus_and_pause_show_current_setup(tmp_path,game):
    o=model(tmp_path);s=garage_sample(snapshot(mPitMode=4,mSpeed=0,mGameState=game),time.perf_counter())
    state=o.update(s,advice(),programme('practice1'))
    assert state['visible'] and state['total']==3
    assert state['card']['location']=='Tyres / Brakes / Chassis'
    assert state['card']['action']=='Decrease by 2 ticks'


def test_stale_stopped_or_disconnected_telemetry_withdraws_cards(tmp_path):
    o=model(tmp_path);now=time.perf_counter();s=garage_sample(snapshot(mPitMode=4,mSpeed=0),now)
    assert o.update(s,advice(),now=now)['visible']
    assert not o.update(s,advice(),now=now+1)['visible']
    assert o.status()['total']==0
    assert not o.update(s,advice(),now=now,recorder_running=False)['visible']
    assert not o.update(None,advice(),now=now)['visible']


def test_rnd_only_in_confirmed_practice_two_and_follows_setup():
    for goal in ('practice1','free',None):
        assert len(checklist(advice(),programme(goal)))==3
    cards=checklist(advice(),programme())
    assert [c['kind'] for c in cards]==['setup','setup','review','rd']
    assert 'one clean flying lap' in cards[-1]['action']
    assert len(checklist(None,programme()))==1
    guessed=programme();guessed['source']='assumed'
    assert len(checklist(advice(),guessed))==3


def test_navigation_wrap_dismiss_return_and_new_advice(tmp_path):
    o=model(tmp_path);s=garage_sample(snapshot(mPitMode=4,mSpeed=0),time.perf_counter())
    session=advice();before=copy.deepcopy(session)
    o.update(s,session,programme())
    assert o.command('next')['index']==1
    assert o.command('previous')['index']==0
    assert o.command('previous')['index']==3
    assert not o.command('toggle')['visible']
    assert not o.update(s,session,programme())['visible']
    assert o.command('toggle')['visible']
    o.command('toggle')
    driving={**s,'garage':False}
    o.update(driving,session,programme())
    assert o.update(s,session,programme())['visible']
    assert o.status()['index']==0
    assert session==before
    session['runs'][-1]['decisions']['pressure_fl']='applied'
    assert o.update(s,session)['total']==2
    assert o.status()['card']['heading']=='Front left camber'


def test_mismatched_car_track_or_layout_never_reuses_setup(tmp_path):
    o=model(tmp_path);s=garage_sample(snapshot(mPitMode=4,mSpeed=0),time.perf_counter())
    for k in ('car','track','layout'):
        other=advice();other[k]='Other'
        assert not o.update(s,other)['visible']


def test_stale_button_press_cannot_reopen_old_garage(tmp_path):
    o=model(tmp_path);s=garage_sample(snapshot(mPitMode=4,mSpeed=0),time.perf_counter())
    o.update(s,advice());o.display_at=time.perf_counter()-2
    assert not o.command('toggle')['visible']


class FakeNative:
    def __init__(self,root):self.running=True;self.states=[]
    def publish(self,state):self.states.append(state)
    def close(self):self.running=False


def wait_for(fn):
    end=time.monotonic()+4
    while time.monotonic()<end:
        if fn():return
        time.sleep(.02)
    assert fn()


def test_http_configuration_worker_and_wheel_navigation(tmp_path):
    app=live_app(tmp_path)
    o=app.practice_overlay;o.native_factory=FakeNative
    raw=snapshot(mPitMode=4,mSpeed=0)
    app.recorder.rec.step(raw,time.perf_counter())
    app.start_live_engineer()
    from ams2season.engineer.store import EngineerStore
    from ams2season.engineer.engine import ENGINE_VERSION
    store=EngineerStore(tmp_path);s=store.get(app.recorder.engineer_key)
    s.update(runs=advice()['runs'],engine_version=ENGINE_VERSION);store.save(s)
    before=store.path(s['key']).read_bytes()
    coach=app.coach
    halt=threading.Event()
    def feed():
        while not halt.wait(.02):app.recorder.rec.step(raw,time.perf_counter())
    feeder=threading.Thread(target=feed,daemon=True);feeder.start()
    try:
        app.route('POST','/api/coach/overlay',{}, {'enabled':True,'position':'left'})
        app.recorder.rec.step(raw,time.perf_counter())
        wait_for(lambda:o.status()['visible'])
        wait_for(lambda:o.status()['reason']=='ready')
        with coach.lock:
            coach.buttons=SimpleNamespace(drain=lambda:[{'event':'down','role':'overlay_next'}])
            coach._service_buttons();coach.buttons=None
        assert app.route('GET','/api/coach/overlay',{}, {})['index']==1
        with coach.lock:
            coach.buttons=SimpleNamespace(drain=lambda:[{'event':'up','role':'overlay_previous'}])
            coach._service_buttons();coach.buttons=None
        assert o.status()['index']==1
        assert o.native.states and o.native.running
        assert store.path(s['key']).read_bytes()==before
        assert json.loads((tmp_path/'private_coach/overlay/settings.json').read_text())=={'enabled':True,'position':'left'}
        app.route('POST','/api/coach/overlay',{}, {'enabled':False})
        wait_for(lambda:o.native is None)
        assert not o.status()['visible']
    finally:
        halt.set();feeder.join(timeout=1)
        o.close()
        app.coach.buttons=None;app.coach.close()


def test_invalid_settings_actions_and_conflicting_radio_buttons(tmp_path):
    app=App(tmp_path);o=app.practice_overlay
    for body in ({'enabled':'yes'},{'position':'centre'}):
        with pytest.raises(ValueError):o.configure(body)
    with pytest.raises(ValueError):o.command('apply')
    try:
        b={'mid':1,'pid':2,'button':3,'label':'Wheel 3'}
        with pytest.raises(ValueError,match='separate wheel button'):
            app.coach.configure({'buttons':{'ptt':b,'overlay_next':b}})
    finally:app.coach.close()


def test_conflicting_capture_keeps_old_binding_without_stopping_worker(tmp_path):
    app=App(tmp_path);coach=app.coach
    b={'mid':1,'pid':2,'button':3,'label':'Wheel 3'}
    try:
        coach.configure({'buttons':{'ptt':b}})
        coach.buttons=SimpleNamespace(drain=lambda:[{'event':'captured','role':'overlay_next','binding':b}])
        coach._service_buttons()
        assert coach.button_bindings=={'ptt':b}
        assert 'separate wheel button' in coach.talk['note'] and coach.talk['capturing'] is None
    finally:
        coach.buttons=None;coach.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Windows native overlay')
def test_real_helper_hidden_state_publication_and_cleanup(tmp_path):
    from ams2season.practice_overlay import NativeOverlay
    native=NativeOverlay(tmp_path)
    try:
        native.publish({'visible':False,'enabled':True,'card':None})
        state=json.loads(native.path.read_text())
        assert state['expires_utc']>time.time() and not state['visible']
        time.sleep(.3)
        assert native.running
    finally:native.close()
    assert not native.running and not native.path.exists()


@pytest.mark.skipif(sys.platform!='win32',reason='Windows native overlay')
def test_hidden_helper_exits_if_parent_goes_away(tmp_path):
    state=tmp_path/'state.json';state.write_text('{}')
    parent=subprocess.Popen([sys.executable,'-c','import time; time.sleep(.8)'],creationflags=subprocess.CREATE_NO_WINDOW)
    executable=Path(__file__).resolve().parents[1]/'ams2season/assets/practice_overlay.exe'
    helper=subprocess.Popen([str(executable),str(state),str(parent.pid)],creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        parent.wait(timeout=3)
        assert helper.wait(timeout=4)==0
    finally:
        if helper.poll() is None:helper.kill()
        if parent.poll() is None:parent.kill()
