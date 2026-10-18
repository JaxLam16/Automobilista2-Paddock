"""Final garage submission acknowledges the exact saved setup without applying it twice."""
import copy
import threading
import time

import pytest

from ams2season.engineer.store import EngineerStore, recommendation_token, setup_review, summary_for_ui
from ams2season.practice_overlay import garage_sample
from test_overlay_decisions import session
from test_practice_overlay import live_app, snapshot


def reviewed(root):
    store, s = session(root)
    s['runs'][-1]['measure'] = {}
    store.save(s)
    for rec, decision in zip(s['runs'][-1]['recommendations'], ('applied', 'maxed')):
        store.decide_recommendation(s['key'], 2, rec['id'], recommendation_token(s, s['runs'][-1], rec), decision)
    return store, store.get(s['key'])


def test_submission_retains_exact_decisions_and_never_reapplies_ticks(tmp_path):
    store,s=reviewed(tmp_path);before=copy.deepcopy(s);review=setup_review(s)
    result=store.submit_changes(s['key'],2,review['token'])
    assert result['saved'] and result['review']['submitted']
    after=store.get(s['key'])
    for field in ('ticks','pending_changes','maxed','unavailable'):
        assert after[field]==before[field]
    receipt=after['runs'][-1]['setup_submission']
    assert receipt['items']==review['items'] and receipt['pending_changes']==review['pending_changes']
    assert summary_for_ui(after)['runs'][-1]['setup_submission']==receipt
    saved=store.path(s['key']).read_bytes()
    duplicate=store.submit_changes(s['key'],2,review['token'])
    assert duplicate['duplicate'] and not duplicate['saved']
    assert store.path(s['key']).read_bytes()==saved


def test_unreviewed_instructions_cannot_be_submitted(tmp_path):
    store,s=session(tmp_path);review=setup_review(s);before=store.path(s['key']).read_bytes()
    with pytest.raises(ValueError,match='Review each'):
        store.submit_changes(s['key'],2,review['token'])
    assert store.path(s['key']).read_bytes()==before


@pytest.mark.parametrize('change',['new_run','recommendation','decision','manual','plan','car','deleted'])
def test_outdated_review_cannot_submit_a_different_setup(tmp_path,change):
    store,s=reviewed(tmp_path);review=setup_review(s)
    if change=='new_run':s['runs'].append({**copy.deepcopy(s['runs'][-1]),'id':3})
    elif change=='recommendation':s['runs'][-1]['recommendations'][0]['ticks']=-3
    elif change=='decision':s['runs'][-1]['decisions']['pressure_fl']='skipped'
    elif change=='manual':s['pending_changes'].append({'setting':'arb_rear','ticks':1,'manual':True})
    elif change=='plan':s['next_run']={'objective':'New plan'}
    elif change=='car':s['car']='Other car'
    store.save(s)
    if change=='deleted':store.delete(s['key'])
    before=store.path(s['key']).read_bytes() if store.path(s['key']).exists() else None
    with pytest.raises((ValueError,LookupError)):
        store.submit_changes(s['key'],2,review['token'])
    assert (store.path(s['key']).read_bytes() if store.path(s['key']).exists() else None)==before


def test_submission_rechecks_garage_guard_under_store_lock(tmp_path):
    store,s=reviewed(tmp_path);review=setup_review(s);before=store.path(s['key']).read_bytes()
    checks=iter((True,False))
    with pytest.raises(ValueError,match='telemetry changed'):
        store.submit_changes(s['key'],2,review['token'],guard=lambda:next(checks))
    assert store.path(s['key']).read_bytes()==before


def test_concurrent_submission_is_idempotent(tmp_path):
    store,s=reviewed(tmp_path);review=setup_review(s);barrier=threading.Barrier(3);results=[]
    def submit():
        barrier.wait();results.append(EngineerStore(tmp_path).submit_changes(s['key'],2,review['token']))
    threads=[threading.Thread(target=submit) for _ in range(2)]
    for t in threads:t.start()
    barrier.wait()
    for t in threads:t.join()
    assert sorted(r['saved'] for r in results)==[False,True]
    assert store.get(s['key'])['ticks']==s['ticks']


def test_final_overlay_card_submits_via_five_existing_controls(tmp_path):
    app=live_app(tmp_path);store,s=reviewed(tmp_path);o=app.practice_overlay;o.enabled=True
    app.recorder.engineer_key=s['key'];o.feed(snapshot(mPitMode=4,mSpeed=0),time.perf_counter())
    state=o.update(o.sample,s)
    assert state['total']==1 and state['card']['kind']=='review'
    assert state['menu'][0]['action']=='submit'
    before=store.path(s['key']).read_bytes()
    o.command('confirm');assert o.pending and store.path(s['key']).read_bytes()==before
    o.command('confirm');o._save_decision(store);o.update(o.sample,store.get(s['key']))
    assert o.status()['card']['submitted'] and 'Submitted to engineer' in o.status()['note']
    assert all(c['action']!='submit' for c in o.status()['menu'])
    assert store.get(s['key'])['ticks']==s['ticks']


@pytest.mark.parametrize('change',['leave','stale','driver','disabled','key'])
def test_overlay_submission_is_withdrawn_if_context_changes(tmp_path,change):
    app=live_app(tmp_path);store,s=reviewed(tmp_path);o=app.practice_overlay;o.enabled=True
    app.recorder.engineer_key=s['key'];o.feed(snapshot(mPitMode=4,mSpeed=0),time.perf_counter());o.update(o.sample,s)
    o.command('confirm');before=store.path(s['key']).read_bytes()
    if change=='leave':o.sample={**o.sample,'garage':False}
    elif change=='stale':o.sample={**o.sample,'at':time.perf_counter()-2}
    elif change=='driver':o.sample={**o.sample,'driver':'Other driver'}
    elif change=='disabled':o.enabled=False
    elif change=='key':app.recorder.engineer_key='other'
    o._save_decision(store)
    assert not o.pending and 'not submitted' in o.note
    assert store.path(s['key']).read_bytes()==before


def test_submit_api_and_repeated_engineer_start_preserve_audio_and_current_run(tmp_path):
    app=live_app(tmp_path);raw=snapshot(mPitMode=4,mSpeed=0)
    app.recorder.rec.step(raw,time.perf_counter());key=app.start_live_engineer()
    store,s=reviewed(tmp_path);assert key==s['key'];tracker=app.recorder.engineer
    coach=app.coach
    try:
        coach.audio_enabled=True;coach.output='paddock';coach.mode='full'
        coach_state=(coach.running,coach.audio_enabled,coach.output,coach.mode)
        # Reattaching a saved enabled overlay restores hooks and keeps the tracker.
        app.recorder.rec.hooks.pop('practice_overlay',None)
        app.recorder.rec.hooks.pop('engineer',None)
        app.recorder.rec.step(raw,time.perf_counter())
        assert app.start_live_engineer()==key and app.recorder.engineer is tracker
        assert app.recorder.rec.hooks['engineer']==tracker.feed
        assert app.recorder.rec.hooks['practice_overlay']==app.practice_overlay.feed
        result=app.route('POST','/api/engineer/submit',{},
                         {'key':key,'run_id':2,'token':setup_review(s)['token']})
        assert result['review']['submitted']
        assert (coach.running,coach.audio_enabled,coach.output,coach.mode)==coach_state
    finally:
        app.practice_overlay.close();coach.close()
