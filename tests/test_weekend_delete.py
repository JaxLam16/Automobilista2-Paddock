"""Reviewed weekend removal preserves recordings, earned research and a full backup."""
import json,sqlite3
from pathlib import Path

import pytest

from ams2season.weekends import assign,weekends,deletion_review,remove,next_round,connection
from test_development import campaign,practices,plan_and_assign
from tests.test_bop import hashes

pytestmark=pytest.mark.usefixtures('closed_synthetic_game')


def test_delete_unassessed_weekend_keeps_recordings_and_cancels_only_unearned_plan(campaign):
    app,cid,dev,game=campaign
    plan=dev.create(cid,{'round':1,'categories':['power']})
    before=hashes(game);paths=list(app.lib.recordings_dir.glob('*/session.json'))
    content={p:p.read_bytes() for p in paths}
    review=app.route('GET',f'/api/championships/{cid}/weekends/1',{}, {})
    result=app.route('DELETE',f'/api/championships/{cid}/weekends/1',{}, {'token':review['token']})
    assert result['ok'] and not weekends(app.lib,cid)
    retained=dev.plans(cid)[0]
    assert retained['weekend_deleted'] and retained['state']=='cancelled' and not retained['evaluation']
    assert all(p.read_bytes()==value for p,value in content.items()) and hashes(game)==before
    with sqlite3.connect(result['backup']) as backup:
        assert backup.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert backup.execute('SELECT COUNT(*) FROM weekend').fetchone()[0]==1
        assert json.loads(backup.execute('SELECT data FROM development').fetchone()[0])['state']=='planned'
    assert next_round(app.lib,cid)==2
    with pytest.raises(ValueError,match='history only'):dev.submit(cid,{'plan':plan['id']})


def test_delete_assessed_weekend_keeps_earned_and_applied_levels(campaign):
    app,cid,dev,game=campaign
    plan=plan_and_assign(campaign,('power',));dev.submit(cid,{'plan':plan['id']})
    before=hashes(game);catalog={r['id']:r for r in dev.overview(cid)['catalog']}
    review=deletion_review(app.lib,cid,1)
    assert review['can_delete'] and review['development_history']==1
    remove(app.lib,cid,1,review['token'])
    assert dev.plans(cid)[0]['state']=='applied' and dev.plans(cid)[0]['weekend_deleted']
    after={r['id']:r for r in dev.overview(cid)['catalog']}
    assert after['power']['points']==catalog['power']['points']==2
    assert after['power']['applied']==catalog['power']['applied']==1 and hashes(game)==before


def test_pending_human_or_ai_upgrades_and_changed_review_are_not_deleted(campaign):
    app,cid,dev,game=campaign
    review=deletion_review(app.lib,cid,1)
    assign(app.lib,cid,{'round':1,'name':'Changed after review'})
    with pytest.raises(ValueError,match='changed'):remove(app.lib,cid,1,review['token'])
    plan=dev.create(cid,{'round':1,'categories':['power']});plan['state']='queued';dev.save(cid,plan)
    review=deletion_review(app.lib,cid,1)
    assert not review['can_delete']
    with pytest.raises(ValueError,match='pending'):remove(app.lib,cid,1,review['token'])
    plan['state']='planned';dev.save(cid,plan)
    value=dev.ai.read(cid);value['jobs']=[{'id':'test','round':1,'state':'queued'}];dev.ai.write(cid,value)
    assert not deletion_review(app.lib,cid,1)['can_delete']
    assert len(weekends(app.lib,cid))==1


def test_delete_filed_weekend_removes_results_points_and_corrections_but_other_round_stays(tmp_path):
    from ams2season.app import App
    from ams2season.season import connect
    app=App(tmp_path);cid=app.lib.create_champ({'name':'Removal'})
    db=app.lib._db(cid);con=connection(db)
    recording=app.lib.recordings_dir/'kept-race';recording.mkdir(parents=True)
    (recording/'session.json').write_text('{}')
    with con:
        for rnd in (1,2):
            con.execute('INSERT INTO event(id,round) VALUES(?,?)',(rnd,rnd))
            con.execute("INSERT INTO session(id,event_id,type,path) VALUES(?,?,'race',?)",(rnd,rnd,str(recording)))
            con.execute('INSERT INTO entrant(id,session_id,name,is_ai) VALUES(?,?,?,0)',(rnd,rnd,'Player'))
            con.execute('INSERT INTO result(entrant_id,finish) VALUES(?,1)',(rnd,))
            con.execute("INSERT INTO correction(round,driver,kind,value) VALUES(?,'Player','points',10)",(rnd,))
            con.execute('INSERT INTO practice(round,path) VALUES(?,?)',(rnd,str(recording)+str(rnd)))
    con.close()
    # Minimal session metadata is sufficient for a deletion review; no analysis/game writes.
    app.lib.recording_summary=lambda p:{'id':p.name,'type':'race'}
    review=deletion_review(app.lib,cid,1);assert review['filed_sessions']==1
    result=remove(app.lib,cid,1,review['token'])
    con=connect(db)
    try:
        assert [r[0] for r in con.execute('SELECT round FROM event')]==[2]
        assert [r[0] for r in con.execute('SELECT round FROM correction')]==[2]
        assert [r[0] for r in con.execute('SELECT round FROM practice')]==[2]
        assert [r[0] for r in con.execute('SELECT entrant_id FROM result')]==[2]
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
    finally:con.close()
    assert (recording/'session.json').is_file() and Path(result['backup']).is_file()


def test_backup_failure_leaves_weekend_and_plans_unchanged(campaign,monkeypatch):
    app,cid,dev,game=campaign;review=deletion_review(app.lib,cid,1)
    original=Path.mkdir
    def fail(path,*args,**kwargs):
        if path.name=='backups':raise OSError('Backup unavailable')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'mkdir',fail)
    with pytest.raises(OSError,match='Backup'):remove(app.lib,cid,1,review['token'])
    assert len(weekends(app.lib,cid))==1


def test_http_delete_reads_the_review_token_body(campaign):
    import threading,http.client
    from ams2season.app import _make_server,make_handler
    app,cid,dev,game=campaign;server=_make_server(0,make_handler(app))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    path=f'/api/championships/{cid}/weekends/1'
    try:
        client=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=10)
        client.request('GET',path);response=client.getresponse();assert response.status==200
        review=json.loads(response.read());client.close()
        client=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=10)
        client.request('DELETE',path,body=json.dumps({'token':review['token']}),headers={'Content-Type':'application/json'})
        response=client.getresponse();assert response.status==200,response.read()
        result=json.loads(response.read());client.close()
        assert result['ok'] and not weekends(app.lib,cid) and Path(result['backup']).is_file()
    finally:server.shutdown();server.server_close()
