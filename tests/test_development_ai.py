"""AI research advances by rate and weekend, never by fictional practice goals."""
import pytest
from tests.test_development import campaign,practices
from ams2season.season import save_config
from ams2season.weekends import assign
from tests.test_bop import hashes

def roster(app,cid,*,shared=False,unknown=False):
    cfg=app.lib.champ_config(cid)
    cfg.drivers=[{'key':'jax','display':'Jax','role':'human',**({} if unknown else {'car':'CAR_A'})},
                 {'key':'robot','display':'Robot','role':'ai','car':'CAR_A' if shared else 'CAR_B'}]
    save_config(app.lib._db(cid),cfg)

@pytest.fixture(autouse=True)
def synthetic_game_closed(monkeypatch):
    monkeypatch.setattr('ams2season.liveries._game_running',lambda:False)
    monkeypatch.setattr('ams2season.bop_files._game_running',lambda:False)

def test_rate_zero_half_rate_and_exactly_once_full_upgrade(campaign):
    app,cid,dev,game=campaign;roster(app,cid)
    p2=practices_name=next(p.name for p in app.lib.recordings_dir.iterdir() if p.name.startswith('20261002'))
    assign(app.lib,cid,{'round':1,'practice2':p2})
    original=dev.editor._car('car_b').fingerprint
    human=dev.editor._car('car_a').fingerprint
    dev.ai.configure(cid,{'enabled':True,'rate_pct':0});dev.ai.advance(cid)
    assert dev.ai.read(cid)['processed']==[]
    dev.ai.configure(cid,{'enabled':True,'rate_pct':50});dev.ai.advance(cid)
    assert dev.ai.read(cid)['ledger']['car_b']['credit']==.5
    assert dev.editor._car('car_b').fingerprint==original
    assign(app.lib,cid,{'round':2,'practice2':p2});dev.ai.advance(cid)
    value=dev.ai.read(cid)
    assert len(value['jobs'])==1 and value['jobs'][0]['state']=='applied'
    assert dev.editor._car('car_b').fingerprint!=original
    assert dev.editor._car('car_a').fingerprint==human
    after=hashes(game);dev.ai.advance(cid)
    assert hashes(game)==after and len(dev.ai.read(cid)['jobs'])==1

@pytest.mark.parametrize('case',['shared','unknown'])
def test_human_shared_or_unassigned_cars_never_receive_ai_physics(campaign,case):
    app,cid,dev,game=campaign;roster(app,cid,shared=case=='shared',unknown=case=='unknown')
    p2=next(p.name for p in app.lib.recordings_dir.iterdir() if p.name.startswith('20261002'))
    assign(app.lib,cid,{'round':1,'practice2':p2})
    dev.ai.configure(cid,{'enabled':True,'rate_pct':200});before=hashes(game);dev.ai.advance(cid)
    assert hashes(game)==before and not dev.ai.read(cid)['jobs']
    assert dev.ai.status(cid)['held_cars']

def test_ai_queue_waits_for_game_and_rechecks_human_model_assignment(campaign,monkeypatch):
    app,cid,dev,game=campaign;roster(app,cid)
    p2=next(p.name for p in app.lib.recordings_dir.iterdir() if p.name.startswith('20261002'))
    assign(app.lib,cid,{'round':1,'practice2':p2})
    dev.ai.configure(cid,{'enabled':True,'rate_pct':100})
    before=hashes(game);monkeypatch.setattr('ams2season.liveries._game_running',lambda:True)
    dev.ai.advance(cid)
    assert hashes(game)==before and dev.ai.read(cid)['jobs'][0]['state']=='queued'
    cfg=app.lib.champ_config(cid);cfg.drivers[0]['car']='CAR_B';save_config(app.lib._db(cid),cfg)
    monkeypatch.setattr('ams2season.liveries._game_running',lambda:False);dev.ai.advance(cid)
    assert hashes(game)==before


def test_distinct_ai_model_sharing_human_physics_is_excluded(campaign):
    app,cid,dev,game=campaign;roster(app,cid)
    dev.editor._car('car_b').sources['edf']=dev.editor._car('car_a').sources['edf']
    eligible,held,_=dev.ai.eligibility(cid)
    assert 'car_b' not in eligible and any('shares editable physics' in c['reason'] for c in held)
