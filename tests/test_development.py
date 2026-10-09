"""Real telemetry extraction, season isolation and reversible actual physics writes."""
import copy
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from ams2season.app import App
from ams2season.development import Development, eligible_fields, evaluate, measure, objectives
from ams2season.legends import scores_from_raw
from ams2season.recorder import Recorder
from ams2season.season import connect
from ams2season.simulate import practice_drive
from ams2season.weekends import assign, weekends
from tests.test_bop import setup_game, hashes


@pytest.fixture(scope='module')
def practices(tmp_path_factory):
    root = tmp_path_factory.mktemp('development-telemetry')
    rec = Recorder(root, hz=20, log=lambda *_: None, wallclock=lambda: datetime(2026, 10, 1, 19))
    t = 0
    for snap, t in practice_drive(laps=7, seed=22, consistency=0, invalid_laps=(), lockup_rate=0, spin_rate=0):
        rec.step(snap, t)
    rec.close(t + 1)
    p1 = rec.completed[-1]
    meta = json.loads((p1 / 'session.json').read_text()); meta['local']['car'] = 'CAR_A'
    (p1 / 'session.json').write_text(json.dumps(meta))
    local = pd.read_parquet(p1 / 'local.parquet')
    local['fuel_capacity'] = 100.
    local['fuel_level'] = .7 - local.t * .00005
    local.to_parquet(p1 / 'local.parquet', index=False)
    p2 = root / '20261002_development_practice'; shutil.copytree(p1, p2)
    for name in ('frames.parquet', 'local.parquet'):
        df = pd.read_parquet(p2 / name)
        for col in ('t', 'last_lap', 'best_lap', 's1', 's2', 's3', 'current_lap'):
            if col in df: df[col] = df[col] * .99
        df['speed'] /= .99
        df.to_parquet(p2 / name, index=False)
    meta['started_at'] = '2026-10-02T19:00:00'; meta['duration_s'] *= .99
    (p2 / 'session.json').write_text(json.dumps(meta))
    return p1, p2


@pytest.fixture
def campaign(tmp_path, practices):
    root = tmp_path / 'app'; root.mkdir()
    for path in practices: shutil.copytree(path, root / 'recordings' / path.name)
    app = App(root)
    cid = app.lib.create_champ({'name': 'Development Cup'})
    app.lib.update_champ(cid, {'drivers': [{'display': 'Jax'}]})
    dev = Development(app); app._development = dev
    game = setup_game(tmp_path)
    dev.editor.scan(str(game)); dev.config(cid, {'car': 'car_a', 'automatic': True})
    assign(app.lib, cid, {'round': 1, 'practice1': practices[0].name})
    yield app, cid, dev, game
    dev.stop.set()


def plan_and_assign(campaign, categories=('power', 'weight')):
    app, cid, dev, _ = campaign
    plan = dev.create(cid, {'round': 1, 'categories': list(categories)})
    p2 = next(p.name for p in app.lib.recordings_dir.iterdir() if p.name.startswith('20261002'))
    assign(app.lib, cid, {'round': 1, 'practice2': p2})
    return plan


def test_missing_profile_values_stay_unrated_and_starts_are_gradual():
    for bad in (None, float('nan'), float('inf'), float('-inf'), '0', True):
        s = scores_from_raw({'clean_share': bad, 'lap1_gain': bad, 'lap_cv_pct': bad})
        assert all(s[k] is None for k in ('clean', 'starts', 'consistency'))
    assert scores_from_raw({'lap1_gain': 0})['starts'] == 50
    assert 0 < scores_from_raw({'lap1_gain': -6})['starts'] < 20
    assert 80 < scores_from_raw({'lap1_gain': 6})['starts'] < 100
    assert scores_from_raw({'clean_share': 90})['clean'] == 90
    assert scores_from_raw({'lap_cv_pct': 1})['consistency'] == 80


def test_measure_selects_three_actual_reference_laps_and_consistent_corner_grid(practices):
    ref = measure(practices[0]); run = measure(practices[1], ref)
    assert len(ref['reference_laps']) == 3 and ref['clean_laps'] >= 5
    assert ref['car'] == 'CAR_A' and ref['fuel_used'] > 0
    assert run['median'] < ref['median'] - .3
    assert run['corners'] == ref['corners']
    assert ref['hash'] != run['hash']


def test_practice_one_and_two_never_enter_race_metrics_or_points(campaign):
    app, cid, dev, _ = campaign
    plan_and_assign(campaign)
    con = connect(app.lib._db(cid))
    assert con.execute('SELECT COUNT(*) FROM session').fetchone()[0] == 0
    assert con.execute('SELECT COUNT(*) FROM practice_award').fetchone()[0] == 0
    con.close()
    assert app.lib.driver_profiles(cid)['profiles'] == []
    assert len(weekends(app.lib, cid)) == 1


def test_legacy_practice_awards_are_excluded_when_session_becomes_p1(campaign):
    from ams2season.season import file_practice, refile_practice
    app, cid, _, _ = campaign
    p1 = app.lib.recording_path(weekends(app.lib, cid)[0]['practice1'])
    # Even legacy filing and a settings-driven reanalysis must respect the new P1 role.
    result = file_practice(app.lib._db(cid), app.lib.champ_config(cid), p1, 1)
    assert result['awards'] == []
    refile_practice(app.lib._db(cid), app.lib.champ_config(cid))
    con = connect(app.lib._db(cid))
    assert con.execute('SELECT COUNT(*) FROM practice_award').fetchone()[0] == 0
    con.close()


def test_partial_credit_carries_forward_to_a_small_upgrade(campaign):
    app, cid, dev, game = campaign
    p1 = app.lib.recording_path(weekends(app.lib, cid)[0]['practice1'])
    before = hashes(game)
    for rnd, scale in ((1, 1.005), (2, 1.006)):
        if rnd == 2: assign(app.lib, cid, {'round': rnd, 'practice1': p1.name})
        p = dev.create(cid, {'round': rnd, 'categories': ['power']})
        p2 = app.lib.recordings_dir / ('partial_' + str(rnd)); shutil.copytree(p1, p2)
        meta = json.loads((p2 / 'session.json').read_text()); meta['started_at'] = '2026-10-0' + str(rnd + 2) + 'T19:00:00'
        (p2 / 'session.json').write_text(json.dumps(meta))
        for name in ('frames.parquet', 'local.parquet'):
            df = pd.read_parquet(p2 / name)
            for col in ('t', 'last_lap', 'best_lap', 's1', 's2', 's3', 'current_lap'):
                if col in df: df[col] *= scale
            df['speed'] /= scale; df.to_parquet(p2 / name, index=False)
        assign(app.lib, cid, {'round': rnd, 'practice2': p2.name})
        p = dev.submit(cid, {'plan': p['id']})
        assert p['evaluation']['projects'][0]['points'] == 1
        if rnd == 1: assert p['state'] == 'assessed' and hashes(game) == before
        else: assert p['state'] == 'applied' and p['upgrades'] == {'power': 1}


def test_queue_recovers_after_app_restart(campaign, monkeypatch):
    app, cid, dev, game = campaign
    plan = plan_and_assign(campaign)
    monkeypatch.setattr('ams2season.liveries._game_running', lambda: True)
    assert dev.submit(cid, {'plan': plan['id']})['state'] == 'queued'
    before = hashes(game); dev.stop.set()
    restarted = App(app.lib.root)
    try:
        assert restarted._development is not None
        monkeypatch.setattr('ams2season.liveries._game_running', lambda: False)
        assert restarted._development.apply(cid, plan['id'])['state'] == 'applied'
        assert hashes(game) != before
    finally:
        restarted._development.stop.set()


def test_full_pipeline_applies_small_real_changes_to_every_copy_once_and_undo(campaign):
    app, cid, dev, game = campaign
    plan = plan_and_assign(campaign)
    before = hashes(game)
    original = dev.editor.detail('car_a')['metrics']
    assessed = dev.submit(cid, {'plan': plan['id']})
    assert assessed['state'] == 'applied', assessed.get('error')
    assert assessed['upgrades'] == {'power': 1, 'weight': 1}
    after = hashes(game); assert before != after
    metrics = dev.editor.detail('car_a')['metrics']
    assert metrics['power_kw'] > original['power_kw'] and metrics['mass'] < original['mass']
    assert metrics['power_kw'] / original['power_kw'] < 1.003
    assert original['mass'] - metrics['mass'] <= 4
    assert dev.submit(cid, {'plan': plan['id']})['transaction'] == assessed['transaction']
    assert hashes(game) == after
    dev.undo(cid, {'plan': plan['id']})
    assert hashes(game) == before
    assert dev.plans(cid)[0]['state'] == 'reverted'


def test_queue_waits_for_game_then_applies_without_reassessing(campaign, monkeypatch):
    _, cid, dev, game = campaign
    plan = plan_and_assign(campaign)
    before = hashes(game)
    monkeypatch.setattr('ams2season.liveries._game_running', lambda: True)
    p = dev.submit(cid, {'plan': plan['id']})
    assert p['state'] == 'queued' and hashes(game) == before
    monkeypatch.setattr('ams2season.liveries._game_running', lambda: False)
    p = dev.apply(cid, plan['id'])
    assert p['state'] == 'applied' and hashes(game) != before


def test_bop_undo_updates_development_ledger_without_losing_research(campaign):
    _, cid, dev, game = campaign
    before = hashes(game)
    plan = plan_and_assign(campaign)
    assert dev.submit(cid, {'plan': plan['id']})['state'] == 'applied'
    dev.editor.undo()
    assert hashes(game) == before
    status = dev.overview(cid)
    assert status['plans'][0]['state'] == 'reverted'
    for category in ('power', 'weight'):
        area = next(x for x in status['catalog'] if x['id'] == category)
        assert area['points'] == 2 and area['unlocked'] == 1 and area['applied'] == 0


def test_unrelated_physics_edit_blocks_until_explicitly_adopted(campaign):
    _, cid, dev, game = campaign
    plan = plan_and_assign(campaign)
    car = dev.editor.cars['car_a']
    draft = dev.editor.preview([{'car': car.id, 'fingerprint': car.fingerprint, 'parameters': {'cdf.mass.0.0': 1400}}])
    dev.editor.apply(draft['token']); before = hashes(game)
    p = dev.submit(cid, {'plan': plan['id']})
    assert p['state'] == 'blocked' and hashes(game) == before
    p = dev.retry(cid, {'plan': plan['id'], 'adopt_current': True})
    assert p['state'] == 'applied'
    assert dev.editor.detail('car_a')['metrics']['mass'] == 1397


def test_completed_file_transaction_recovers_if_database_completion_was_lost(campaign):
    _, cid, dev, game = campaign
    plan = plan_and_assign(campaign)
    p = dev.submit(cid, {'plan': plan['id']}); assert p['state'] == 'applied'
    before = hashes(game)
    p['state'] = 'applying'; p.pop('transaction'); dev.save(cid, p)
    recovered = dev.apply(cid, p['id'])
    assert recovered['state'] == 'applied' and hashes(game) == before


def test_same_recording_cannot_farm_research_in_another_championship(campaign):
    app, cid, dev, game = campaign
    plan = plan_and_assign(campaign)
    assert dev.submit(cid, {'plan': plan['id']})['state'] == 'applied'
    other = app.lib.create_champ({'name': 'Other Cup'})
    dev.config(other, {'car': 'car_a'})
    w = weekends(app.lib, cid)[0]
    assign(app.lib, other, {'round': 1, 'practice1': w['practice1']})
    p = dev.create(other, {'round': 1, 'categories': ['power']})
    assign(app.lib, other, {'round': 1, 'practice2': w['practice2']})
    before = hashes(game)
    with pytest.raises(ValueError, match='already earned'): dev.submit(other, {'plan': p['id']})
    assert hashes(game) == before


def test_reference_is_locked_and_cannot_be_used_as_practice_two(campaign):
    app, cid, dev, _ = campaign
    p1 = weekends(app.lib, cid)[0]['practice1']
    with pytest.raises(ValueError, match='separate'): assign(app.lib, cid, {'round': 1, 'practice2': p1})
    plan = dev.create(cid, {'round': 1, 'categories': ['power']})
    p2 = next(p.name for p in app.lib.recordings_dir.iterdir() if p.name.startswith('20261002'))
    with pytest.raises(ValueError, match='locked'): assign(app.lib, cid, {'round': 1, 'practice1': p2})
    path = app.lib.recording_path(p1) / 'session.json'
    meta = json.loads(path.read_text()); meta['label'] = 'changed'; path.write_text(json.dumps(meta))
    assign(app.lib, cid, {'round': 1, 'practice2': p2})
    with pytest.raises(ValueError, match='changed'): dev.submit(cid, {'plan': plan['id']})


def test_goals_fail_when_laps_are_not_consecutive_or_not_comparable():
    ref = {'driver': 'Jax', 'car': 'Car', 'track': 'Track', 'layout': 'GP', 'length': 5000, 'hash': 'p1', 'median': 100,
           'started_at': '2026-10-01', 'corner_speeds': {'T1': 170}, 'kinds': {'fast': ['T1'], 'corner': [], 'exit': []}}
    project = [{'category': 'front_aero', 'objectives': objectives('front_aero', ref)}]
    run = ref | {'hash': 'p2', 'started_at': '2026-10-02', 'clean_laps': 3,
                 'laps': [{'n': n, 'time': 100, 'speeds': {'T1': 173}} for n in (1, 3, 5)]}
    result = evaluate(project, ref, run)
    assert result['projects'][0]['points'] == 0
    run['laps'] = [{'n': n, 'time': 100, 'speeds': {'T1': 173}} for n in (1, 2, 3)]
    result = evaluate(project, ref, run)
    assert result['projects'][0]['points'] == 1
    run['laps'][1]['speeds']['T1'] = 177
    result = evaluate(project, ref, run)
    assert result['projects'][0]['points'] == 2
    run['car'] = 'Different'
    with pytest.raises(ValueError, match='same driver'): evaluate(project, ref, run)


def test_catalog_marks_unsupported_physics_instead_of_faking_an_upgrade(campaign):
    _, cid, dev, _ = campaign
    cats = {c['id']: c for c in dev.overview(cid)['catalog']}
    assert len(cats) >= 20 and cats['power']['available'] and cats['brakes']['available']
    assert not cats['tyres']['available'] and not cats['underbody']['available']
    with pytest.raises(ValueError, match='Tyres'): dev.create(cid, {'round': 1, 'categories': ['tyres']})


def test_manual_mode_keeps_earned_levels_queued(campaign):
    _, cid, dev, game = campaign
    dev.config(cid, {'car': 'car_a', 'automatic': False})
    plan = plan_and_assign(campaign)
    before = hashes(game)
    p = dev.submit(cid, {'plan': plan['id']})
    assert p['state'] == 'queued' and hashes(game) == before
    assert dev.retry(cid, {'plan': plan['id']})['state'] == 'applied'


def test_undo_never_removes_a_later_bop_change(campaign):
    _, cid, dev, game = campaign
    plan = plan_and_assign(campaign)
    assert dev.submit(cid, {'plan': plan['id']})['state'] == 'applied'
    car = dev.editor.cars['car_a']
    preview = dev.editor.preview([{'car': car.id, 'fingerprint': car.fingerprint, 'parameters': {'cdf.mass.0.0': 1300}}])
    dev.editor.apply(preview['token']); before = hashes(game)
    with pytest.raises(ValueError, match='latest physics'): dev.undo(cid, {'plan': plan['id']})
    assert hashes(game) == before
