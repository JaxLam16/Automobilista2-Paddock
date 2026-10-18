"""Championship switching touches synthetic installed cars only, with reviewed targets."""
import pytest
from tests.test_development import campaign,practices,plan_and_assign
from tests.test_bop import hashes

@pytest.fixture(autouse=True)
def synthetic_game_closed(monkeypatch):
    monkeypatch.setattr('ams2season.liveries._game_running',lambda:False)
    monkeypatch.setattr('ams2season.bop_files._game_running',lambda:False)

def test_save_reset_load_preserves_earned_history_and_other_bop_parameters(campaign):
    app,cid,dev,game=campaign
    original=dev.editor.detail('car_a')['metrics']['mass']
    plan=plan_and_assign(campaign,('weight',));result=dev.submit(cid,{'plan':plan['id']})
    developed=dev.editor.detail('car_a')['metrics']['mass']
    assert developed<original
    saved=dev.states.save(cid,{'name':'Round one'})
    points=dev.plans(cid)[0]['evaluation']
    other=app.lib.create_champ({'name':'Fresh season'})
    preview=dev.states.preview(other,{'kind':'reset'})
    assert dev.editor.detail('car_a')['metrics']['mass']==developed
    dev.states.apply(other,{'token':preview['token']})
    assert dev.editor.detail('car_a')['metrics']['mass']==original
    assert not dev.states.status(cid)['is_active']
    assert dev.states.human_levels(other).get('weight',0)==0
    assert dev.plans(cid)[0]['evaluation']==points
    load=dev.states.preview(cid,{'kind':'load','state':saved['id']})
    dev.states.apply(cid,{'token':load['token']})
    assert dev.editor.detail('car_a')['metrics']['mass']==developed
    assert dev.states.status(cid)['is_active']
    assert dev.states.human_levels(cid)['weight']==1
    assert len(dev.states.status(cid)['snapshots'])>=2
    assert dev.plans(cid)[0]['transaction']==result['transaction']

def test_state_review_rejects_foreign_state_changed_files_and_game_open(campaign,monkeypatch):
    app,cid,dev,game=campaign
    plan=plan_and_assign(campaign,('weight',));dev.submit(cid,{'plan':plan['id']})
    saved=dev.states.save(cid,{'name':'Keep'})
    other=app.lib.create_champ({'name':'Other'})
    with pytest.raises(ValueError,match='belonging'):dev.states.preview(other,{'kind':'load','state':saved['id']})
    review=dev.states.preview(cid,{'kind':'reset'});before=hashes(game)
    monkeypatch.setattr('ams2season.liveries._game_running',lambda:True)
    with pytest.raises(ValueError,match='Close AMS2'):dev.states.apply(cid,{'token':review['token']})
    assert hashes(game)==before
    monkeypatch.setattr('ams2season.liveries._game_running',lambda:False)
    review=dev.states.preview(cid,{'kind':'reset'})
    car=dev.editor._car('car_a')
    intervening=dev.editor.preview([{'car':car.id,'fingerprint':car.fingerprint,'parameters':{'cdf.mass.0.0':1300}}])
    dev.editor.apply(intervening['token'])
    with pytest.raises(ValueError,match='review|Review'):dev.states.apply(cid,{'token':review['token']})

def test_zero_change_switch_has_explicit_active_champ_and_no_repeated_credits(campaign):
    app,cid,dev,game=campaign
    plan=plan_and_assign(campaign,('weight',));dev.submit(cid,{'plan':plan['id']})
    dev.states.save(cid,{'name':'Developed'})
    other=app.lib.create_champ({'name':'New'})
    review=dev.states.preview(other,{'kind':'reset'});dev.states.apply(other,{'token':review['token']})
    before=hashes(game)
    review=dev.states.preview(cid,{'kind':'reset'});assert review['count']==0
    dev.states.apply(cid,{'token':review['token']})
    assert dev.states.status(cid)['is_active'] and not dev.states.status(other)['is_active']
    assert hashes(game)==before
    assert dev.submit(cid,{'plan':plan['id']})['evaluation']['projects'][0]['points']==2


def test_state_journal_recovers_activation_after_index_write_failure(campaign,monkeypatch):
    app,cid,dev,game=campaign
    plan=plan_and_assign(campaign,('weight',));dev.submit(cid,{'plan':plan['id']})
    dev.states.save(cid,{'name':'Save'})
    other=app.lib.create_champ({'name':'New season'})
    review=dev.states.preview(other,{'kind':'reset'})
    original_write=dev.states.write;count=0
    def failing(value):
        nonlocal count
        count+=1
        if count==2:raise OSError('Simulated index write failure')
        original_write(value)
    monkeypatch.setattr(dev.states,'write',failing)
    with pytest.raises(OSError,match='Simulated'):dev.states.apply(other,{'token':review['token']})
    assert dev.states.active()==(True,other)
    assert dev.states.human_levels(other)=={}
