from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from ams2season.coach.names import RadioNames
from ams2season.identities import entrant_id
from test_crew_chief_baseline import scene


def setup(tmp_path):
    path = tmp_path / 'qualifying';path.mkdir()
    meta = {'session_type': 'qualify', 'status': 'complete', 'track_location': 'Track',
            'track_variation': 'Layout', 'track_length': 2000,
            'started_at': datetime.now(timezone.utc).isoformat(), 'local': {'name': 'Driver0'},
            'final': [{'name': 'Driver0', 'car': 'GT3', 'fastest_lap': 41, 'race_pos': 1},
                      {'name': 'Driver1', 'car': 'GT3', 'fastest_lap': 42, 'race_pos': 2},
                      {'name': 'Driver2', 'car': 'GT3', 'fastest_lap': 43, 'race_pos': 3}]}
    (path / 'session.json').write_text(json.dumps(meta))
    cfg = SimpleNamespace(name='GT3 Championship', drivers=[
        {'key': 'j', 'display': 'Jacks', 'role': 'human'},
        {'key': 'c', 'display': 'Chris Lulham', 'role': 'ai'}])
    lib = SimpleNamespace(recording_path=lambda recording: path, champ_config=lambda champ: cfg)
    (tmp_path / 'sounds/personalisations/Jacks').mkdir(parents=True)
    return RadioNames(tmp_path, sounds=tmp_path / 'sounds'), lib, path


def test_personal_catalogue_and_persistence_do_not_touch_recordings(tmp_path):
    store, lib, path = setup(tmp_path)
    before = (path / 'session.json').read_bytes()
    assert store.catalogue()['personal_names'] == ['Jacks']
    store.set_personal('Jacks', '')
    assert RadioNames(tmp_path).data['personal'] == 'Jacks'
    with pytest.raises(ValueError): store.set_personal('../Driver', store.data['revision'])
    assert (path / 'session.json').read_bytes() == before


def test_qualifying_assignments_include_humans_and_use_exact_identity_across_slot_changes(tmp_path):
    store, lib, path = setup(tmp_path)
    original = (path / 'session.json').read_bytes()
    store.assign(lib, 'q', 'champ', {entrant_id('Driver0', 'GT3'): 'j', entrant_id('Driver1', 'GT3'): 'c'}, '')
    tick = scene(1)
    tick = replace(tick, cars=tuple(replace(c, slot=c.slot + 10) for c in tick.cars))
    assert store.live_mapping(tick, 'Driver0') == {'Driver0': 'Jacks', 'Driver1': 'Chris Lulham'}
    assert (path / 'session.json').read_bytes() == original
    assert not store.live_mapping(replace(tick, session_id='next-race'), 'Driver0')


@pytest.mark.parametrize('change', ['track', 'layout', 'car', 'name', 'age', 'driver', 'duplicate'])
def test_withholds_unverified_names_and_falls_back_to_raw_ams2(tmp_path, change):
    store, lib, _ = setup(tmp_path)
    store.assign(lib, 'q', 'champ', {entrant_id('Driver1', 'GT3'): 'c'}, '')
    tick, driver, now = scene(1), 'Driver0', None
    if change == 'track':tick = replace(tick, track='Other')
    elif change == 'layout':tick = replace(tick, layout='Other')
    elif change == 'car':tick = replace(tick, cars=(tick.cars[0], replace(tick.cars[1], car='Other'), tick.cars[2]))
    elif change == 'name':tick = replace(tick, cars=(tick.cars[0], replace(tick.cars[1], name='Other'), tick.cars[2]))
    elif change == 'driver':driver = 'Someone else'
    elif change == 'duplicate':tick = replace(tick, cars=(*tick.cars, replace(tick.cars[1], slot=9)))
    else:now = datetime.now(timezone.utc) + timedelta(hours=5)
    assert store.live_mapping(tick, driver, now=now) == {}


def test_conflicting_and_stale_assignments_preserve_last_saved_state(tmp_path):
    store, lib, _ = setup(tmp_path)
    assignments = {entrant_id('Driver0', 'GT3'): 'j', entrant_id('Driver1', 'GT3'): 'j'}
    with pytest.raises(ValueError, match='at most once'): store.assign(lib, 'q', 'champ', assignments, '')
    second_window = RadioNames(tmp_path, sounds=tmp_path / 'sounds')
    store.set_personal('Jacks', '')
    saved = store.path.read_bytes()
    with pytest.raises(ValueError, match='another window'): second_window.set_personal('Jacks', '')
    assert store.path.read_bytes() == saved


@pytest.mark.parametrize('assigned', [True, False])
def test_live_pit_calls_use_assigned_name_or_original_ams2_name_without_changing_evidence(assigned):
    from ams2season.coach.engine import CoachEngine
    from test_coach_replay import tick
    engine = CoachEngine('Player', name_for=lambda car: 'Chris Lulham' if assigned else car.name)
    calls = []
    for i in range(470):
        frame = tick(i / 10, pit=1 if i >= 450 else 0)
        selected = engine.feed(frame, radio_busy=False)
        if selected:
            calls.append(selected)
            engine.radio.acknowledge(selected, engine.context, accepted=True, simulated=True)
    assert len(calls) == 1
    assert calls[0].text == ('Chris Lulham' if assigned else 'Rival') + ' is pitting.'
    assert calls[0].message.evidence.values['driver'] == 'Rival'
    assert calls[0].message.requirements[0].key.startswith('pit:1:Rival:')


def test_race_binding_survives_personal_name_and_coach_changes_and_app_restart(tmp_path):
    store, lib, _ = setup(tmp_path)
    store.assign(lib, 'q', 'champ', {entrant_id('Driver1', 'GT3'): 'c'}, '')
    assert store.live_mapping(scene(1), 'Driver0', race_id='recorded-race')['Driver1'] == 'Chris Lulham'
    store.set_personal('Jacks', store.data['revision'])
    tick = replace(scene(2), session_id='new-coach-run')
    assert store.live_mapping(tick, 'Driver0', race_id='recorded-race')['Driver1'] == 'Chris Lulham'
    reloaded = RadioNames(tmp_path)
    assert reloaded.live_mapping(tick, 'Driver0', race_id='recorded-race')['Driver1'] == 'Chris Lulham'
    assert not reloaded.live_mapping(tick, 'Driver0', race_id='different-race')
