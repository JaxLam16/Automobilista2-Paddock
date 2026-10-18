"""Five-way garage menu, safe setup decisions and POV-hat controls."""
import copy
import ctypes
import json
import threading
import time
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ams2season.engineer.store import EngineerStore, recommendation_token
from ams2season.practice_overlay import PracticeOverlay, MENU, garage_sample
from ams2season.coach.buttons import ButtonWatch, WinmmControllers, binding, with_pov
from test_practice_overlay import advice, snapshot, live_app, FakeNative, wait_for, programme


def session(root):
    store=EngineerStore(root)
    s=store.create('Mustang GT','Watkins_Glen','GP_Inner_Loop')
    s['runs']=advice()['runs'];s['runs'][0]['analysed_at']='2026-10-16T13:30:00'
    store.save(s)
    return store,s


@pytest.mark.parametrize('decision',['applied','skipped','maxed','unavailable'])
def test_decisions_match_engineer_ui_and_duplicate_never_reapplies(tmp_path,decision):
    store,s=session(tmp_path);run=s['runs'][-1];rec=run['recommendations'][0]
    token=recommendation_token(s,run,rec)
    result=store.decide_recommendation(s['key'],run['id'],rec['id'],token,decision)
    assert result['saved']
    current=store.get(s['key'])
    assert current['runs'][-1]['decisions'][rec['id']]==decision
    if decision=='applied':
        assert current['ticks']['pressure_fl']==-2
        assert current['pending_changes']==[{'setting':'pressure_fl','ticks':-2}]
    else:assert current['ticks']=={} and current['pending_changes']==[]
    if decision=='maxed':assert current['maxed']['pressure_fl']=='down'
    if decision=='unavailable':assert 'pressure_fl' in current['unavailable']
    before=store.path(s['key']).read_bytes()
    assert store.decide_recommendation(s['key'],run['id'],rec['id'],token,decision)['duplicate']
    assert store.path(s['key']).read_bytes()==before


@pytest.mark.parametrize('change',['run','ticks','evidence','timestamp','already_decided','deleted'])
def test_old_card_cannot_change_latest_advice(tmp_path,change):
    store,s=session(tmp_path);run=s['runs'][-1];rec=run['recommendations'][0]
    token=recommendation_token(s,run,rec);run_id=run['id']
    if change=='run':s['runs'].append({**copy.deepcopy(run),'id':3})
    elif change=='ticks':rec['ticks']=-1
    elif change=='evidence':rec['why']='Different evidence'
    elif change=='timestamp':run['analysed_at']='later'
    elif change=='already_decided':run['decisions'][rec['id']]='skipped'
    store.save(s)
    if change=='deleted':store.delete(s['key'])
    before=store.path(s['key']).read_bytes() if store.path(s['key']).exists() else None
    with pytest.raises((ValueError,LookupError)):
        store.decide_recommendation(s['key'],run_id,rec['id'],token,'applied')
    assert (store.path(s['key']).read_bytes() if store.path(s['key']).exists() else None)==before


def test_two_concurrent_confirms_apply_once(tmp_path):
    store,s=session(tmp_path);run=s['runs'][-1];rec=run['recommendations'][0]
    token=recommendation_token(s,run,rec);barrier=threading.Barrier(3);results=[]
    def confirm():
        barrier.wait();results.append(EngineerStore(tmp_path).decide_recommendation(s['key'],run['id'],rec['id'],token,'applied'))
    threads=[threading.Thread(target=confirm) for _ in range(2)]
    for t in threads:t.start()
    barrier.wait()
    for t in threads:t.join()
    assert sorted(r['saved'] for r in results)==[False,True]
    assert store.get(s['key'])['ticks']['pressure_fl']==-2


def test_setup_page_saving_after_overlay_cannot_double_apply_previous_decision(tmp_path):
    store,s=session(tmp_path);run=s['runs'][-1];rec=run['recommendations'][0]
    store.decide_recommendation(s['key'],run['id'],rec['id'],recommendation_token(s,run,rec),'applied')
    saved=store.decide(s['key'],{'pressure_fl':'applied','camber_fl':'maxed'})
    assert saved['ticks']=={'pressure_fl':-2}
    assert saved['pending_changes']==[{'setting':'pressure_fl','ticks':-2}]
    assert saved['maxed']['camber_fl']=='up'


def test_guard_rechecked_inside_store_transaction(tmp_path):
    store,s=session(tmp_path);r=s['runs'][-1];rec=r['recommendations'][0];before=store.path(s['key']).read_bytes()
    checks=iter((True,False))
    with pytest.raises(ValueError,match='telemetry changed'):
        store.decide_recommendation(s['key'],r['id'],rec['id'],recommendation_token(s,r,rec),'applied',guard=lambda:next(checks))
    assert store.path(s['key']).read_bytes()==before


def test_menu_arrows_select_then_confirm_saves_and_advances(tmp_path):
    app=live_app(tmp_path);store,s=session(tmp_path);app.recorder.engineer_key=s['key']
    o=app.practice_overlay;o.enabled=True;o.native_factory=FakeNative
    sample=garage_sample(snapshot(mPitMode=4,mSpeed=0),time.perf_counter())
    o.feed(snapshot(mPitMode=4,mSpeed=0),time.perf_counter());o.update(sample,s)
    assert o.status()['menu_index']==0
    assert o.command('right')['index']==1 and o.command('left')['index']==0
    o.command('down');assert o.status()['menu'][o.status()['menu_index']]['action']=='applied'
    before=store.path(s['key']).read_bytes()
    o.command('confirm');assert o.status()['pending']
    assert store.path(s['key']).read_bytes()==before # button handler performs no IO
    o.command('confirm') # repeated press while pending is ignored
    o._save_decision(store);o.update(o.sample,store.get(s['key']))
    assert o.status()['total']==2 and o.status()['index']==0 and o.status()['menu_index']==0
    assert store.get(s['key'])['ticks']=={'pressure_fl':-2}
    assert 'Applied' in o.status()['note']


def test_confirm_reopens_hidden_checklist_without_applying_selected_action(tmp_path):
    app=live_app(tmp_path);store,s=session(tmp_path);app.recorder.engineer_key=s['key']
    o=app.practice_overlay;o.enabled=True
    raw=snapshot(mPitMode=4,mSpeed=0);o.feed(raw,time.perf_counter());o.update(o.sample,s)
    o.command('up');o.command('confirm')
    assert o.status()['reason']=='dismissed'
    before=store.path(s['key']).read_bytes()
    assert o.command('confirm')['visible']
    assert o.status()['menu_index']==0 and not o.pending
    assert store.path(s['key']).read_bytes()==before


def test_confirm_reenables_disabled_overlay_on_worker_and_return_auto_opens(tmp_path):
    app=live_app(tmp_path);store,s=session(tmp_path);app.recorder.engineer_key=s['key']
    o=app.practice_overlay;o.native_factory=FakeNative
    raw=snapshot(mPitMode=4,mSpeed=0);o.feed(raw,time.perf_counter())
    o.update(o.sample,s);assert not o.enabled
    before=store.path(s['key']).read_bytes()
    try:
        o.command('confirm')
        wait_for(lambda:o.status()['visible'])
        assert json.loads((tmp_path/'private_coach/overlay/settings.json').read_text())['enabled'] is True
        assert not o.pending and store.path(s['key']).read_bytes()==before
        o.command('up');o.command('confirm');assert o.dismissed
        o.feed(snapshot(mPitMode=0,mSpeed=20),time.perf_counter())
        wait_for(lambda:not o.was_garage)
        o.feed(raw,time.perf_counter());wait_for(lambda:o.status()['visible'])
        assert not o.pending and store.path(s['key']).read_bytes()==before
    finally:o.close()


@pytest.mark.parametrize('changes',[{'mPitMode':0},{'mSessionState':5},{'mGameState':6}])
def test_confirm_cannot_enable_disabled_checklist_outside_practice_garage(tmp_path,changes):
    app=live_app(tmp_path);o=app.practice_overlay
    raw=snapshot(mPitMode=4,mSpeed=0)
    for k,v in changes.items():setattr(raw,k,v)
    o.feed(raw,time.perf_counter());o.command('confirm')
    assert not o.enabled and not o.enable_requested and o.thread is None


@pytest.mark.parametrize('change',['leave_garage','stale','new_car','disabled','new_engineer'])
def test_queued_decision_withdrawn_when_live_context_changes(tmp_path,change):
    app=live_app(tmp_path);store,s=session(tmp_path);app.recorder.engineer_key=s['key']
    o=app.practice_overlay;o.enabled=True
    raw=snapshot(mPitMode=4,mSpeed=0);o.feed(raw,time.perf_counter());o.update(o.sample,s)
    o.command('down');o.command('confirm')
    before=store.path(s['key']).read_bytes()
    if change=='leave_garage':o.sample={**o.sample,'garage':False}
    elif change=='stale':o.sample={**o.sample,'at':time.perf_counter()-2}
    elif change=='new_car':o.sample={**o.sample,'car':'Other'}
    elif change=='disabled':o.enabled=False
    elif change=='new_engineer':app.recorder.engineer_key='other'
    o._save_decision(store)
    assert not o.pending and 'No setup decision' in o.note
    assert store.path(s['key']).read_bytes()==before


def test_rnd_menu_cannot_claim_completed_or_apply_car_changes(tmp_path):
    app=live_app(tmp_path);o=app.practice_overlay;o.enabled=True
    sample=garage_sample(snapshot(mPitMode=4,mSpeed=0),time.perf_counter());o.update(sample,None,programme())
    assert [c['action'] for c in o.status()['menu']]==['next','hide']
    o.command('up');o.command('confirm');assert o.status()['reason']=='dismissed'
    assert not o.pending and not (tmp_path/'engineer').exists()


@pytest.mark.parametrize('angle,direction',[(0,33),(4500,34),(9000,34),(18000,35),(27000,36),(35999,33)])
def test_hat_directions_capture_bind_and_release(angle,direction):
    watcher=ButtonWatch();watcher.start_capture('overlay_down')
    watcher._step({0:(1,2,'Wheel',with_pov(0,angle))})
    events=watcher.drain();assert len(events)==1 and events[0]['event']=='captured'
    captured=events[0]['binding'];assert captured['button']==direction and 'hat' in captured['label']
    assert binding(captured)==captured
    watcher.bind({'overlay_down':captured})
    watcher._step({0:(1,2,'Wheel',with_pov(0,65535))})
    assert watcher.drain()[0]['event']=='up'
    watcher._step({0:(1,2,'Wheel',with_pov(0,angle))})
    assert watcher.drain()[0]['event']=='down'


@pytest.mark.parametrize('angle',[65535,0xffffffff,-1])
def test_centred_or_missing_hat_never_creates_a_direction(angle):
    assert with_pov(1,angle)==1


@pytest.mark.parametrize('has_pov,expected',[(False,0),(True,1<<32)])
def test_reader_uses_hat_only_when_controller_declares_one(has_pov,expected):
    class Info(ctypes.Structure):
        _fields_=[(name,ctypes.c_uint32) for name in ('dwSize','dwFlags','dwButtons','dwPOV')]
    flags=[]
    def poll(index,pointer):
        obj=pointer._obj;flags.append(obj.dwFlags)
        assert obj.dwPOV==65535
        obj.dwButtons=0;obj.dwPOV=0
        return 0
    reader=WinmmControllers.__new__(WinmmControllers)
    reader.JOYINFOEX=Info;reader.winmm=SimpleNamespace(joyGetPosEx=poll)
    reader.caps={0:(1,2,'Wheel',has_pov)};reader.caps_at=time.monotonic()
    assert reader.read()[0][3]==expected
    assert flags==[0xC0 if has_pov else 0x80]


def test_five_wheel_controls_reach_menu_and_confirm_through_coach(tmp_path):
    app=live_app(tmp_path);coach=app.coach;store,s=session(tmp_path)
    app.recorder.engineer_key=s['key'];o=app.practice_overlay;o.enabled=True
    raw=snapshot(mPitMode=4,mSpeed=0);o.feed(raw,time.perf_counter());o.update(o.sample,s)
    roles={'overlay_previous':36,'overlay_next':34,'overlay_up':33,'overlay_down':35,'overlay_confirm':8}
    watcher=ButtonWatch({role:{'mid':1,'pid':2,'button':button,'label':role} for role,button in roles.items()})
    coach.buttons=watcher
    def press(button):
        watcher._step({0:(1,2,'Wheel',0)});coach._service_buttons()
        watcher._step({0:(1,2,'Wheel',1<<(button-1))});coach._service_buttons()
    try:
        press(34);assert o.status()['index']==1
        press(36);assert o.status()['index']==0
        press(35);assert o.status()['menu_index']==1
        before=store.path(s['key']).read_bytes();press(8)
        assert o.pending and store.path(s['key']).read_bytes()==before
        watcher._step({0:(1,2,'Wheel',1<<7)});coach._service_buttons() # held, not a second press
        o._save_decision(store)
        assert store.get(s['key'])['ticks']=={'pressure_fl':-2}
        assert len(store.get(s['key'])['pending_changes'])==1
    finally:coach.buttons=None;coach.close()


def test_default_button_setup_has_exactly_five_overlay_roles(tmp_path):
    app=live_app(tmp_path)
    try:
        roles=app.coach.status()['talk']['roles']
        assert [r for r in roles if r.startswith('overlay_')]==[
            'overlay_previous','overlay_next','overlay_up','overlay_down','overlay_confirm']
    finally:app.coach.close()


@pytest.mark.skipif(sys.platform!='win32',reason='Windows native rendering')
@pytest.mark.parametrize('rd,expected',[(False,6),(True,2)])
def test_native_menu_deserializes_actual_json_array_and_renders_without_activation(tmp_path,rd,expected):
    app=live_app(tmp_path);o=app.practice_overlay;o.enabled=True
    sample=garage_sample(snapshot(mPitMode=4,mSpeed=0),time.perf_counter())
    o.update(sample,None if rd else advice(),programme() if rd else None)
    o.command('down');state=o.status()
    source=tmp_path/'native.json';source.write_text(json.dumps(state),encoding='utf-8')
    target=tmp_path/'native.png'
    executable=Path(__file__).resolve().parents[1]/'ams2season/assets/practice_overlay.exe'
    subprocess.run([str(executable),'--render',str(source),str(target)],check=True,timeout=10)
    labels=json.loads(Path(str(target)+'.labels.json').read_text(encoding='utf-8'))
    assert labels['no_activation'] and 100<labels['height']<700 and target.stat().st_size>1000
    assert len(labels['menu'].strip().splitlines())==expected
    assert ('Applied' not in labels['menu']) if rd else ('▶  Applied' in labels['menu'])
