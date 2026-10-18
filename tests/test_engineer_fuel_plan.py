"""Practice fuel plan: measure first, then race fuel, never a full tank by default."""
from ams2season.engineer import engine


def state(**changes):
    value = {'runs_analysed': 0, 'race_target': {'mode': 'time', 'minutes': 20}, 'high_fuel_done': False,
             'low_fuel_done': False, 'fuel_per_lap': None, 'avg_lap': None}
    value.update(changes)
    return value


def measure(per=0.94, lap=46.0, cap=120, start=60.0):
    return {'fuel': {'capacity_l': cap, 'start_l': start, 'per_lap_l': per, 'laps_measured': 4}, 'avg_lap': lap}


def test_first_run_goes_out_on_whatever_fuel_is_in():
    plan = engine.next_run(state(), None, [])
    assert plan['fuel_l'] is None and plan['laps'] >= 3
    assert 'measure fuel use' in plan['objective'] and 'Full tank' not in plan['objective']


def test_a_sprint_asks_for_race_fuel_not_a_full_tank():
    # 20 minutes at 46 s a lap: 28 laps at 0.94 L plus a lap's reserve, 28 L
    plan = engine.next_run(state(runs_analysed=1), measure(), [])
    rf = engine.race_fuel(state(runs_analysed=1), measure())
    assert plan['fuel_l'] == rf['start_fuel_l'] == 28 and plan['objective'].startswith('Race fuel')
    # race fuel is light, so there is no separate low-fuel run: the setup changes come next
    done = state(runs_analysed=2, high_fuel_done=True)
    plan = engine.next_run(done, measure(), [{'id': 'x'}])
    assert plan['fuel_l'] == 28 and plan['objective'].startswith('Try the 1 change')


def test_a_race_longer_than_a_tank_runs_a_full_one():
    long = state(runs_analysed=1, race_target={'mode': 'time', 'minutes': 180})
    plan = engine.next_run(long, measure(per=3.0, lap=100.0, cap=110), [])
    assert plan['fuel_l'] == 110 and plan['objective'].startswith('Full tank')
    # heavy race fuel: a low-fuel comparison is worth a run
    plan = engine.next_run(dict(long, high_fuel_done=True), measure(per=3.0, lap=100.0, cap=110), [])
    assert plan['fuel_l'] == engine.low_fuel_l(3.0) and plan['objective'].startswith('Low fuel')


def test_fuel_not_measured_yet_says_so_instead_of_guessing():
    plan = engine.next_run(state(runs_analysed=1), measure(per=None), [{'id': 'x'}])
    assert plan['fuel_l'] is None and "isn't measured" in plan['objective'] and 'Try the 1 change' in plan['objective']


def test_fuel_off_for_the_race_runs_light():
    off = state(runs_analysed=1, race_target={'mode': 'laps', 'laps': 30, 'fuel_mult': 0})
    plan = engine.next_run(off, measure(), [])
    assert plan['fuel_l'] == engine.low_fuel_l(0.94) and 'off for the race' in plan['objective']


def test_sessions_planned_by_the_old_rules_are_replanned_when_opened(tmp_path):
    import json
    from ams2season.engineer.store import EngineerStore
    store = EngineerStore(tmp_path)
    session = store.create('BMW Z4 GT3', 'BrandsHatch', 'BrandsHatch_Indy', {'mode': 'time', 'minutes': 20})
    session['runs'] = [{'id': 1, 'measure': {**measure(start=30.0), 'n_flying': 4}, 'changes_before': [], 'decisions': {}}]
    session['flags'].update(low_fuel_done=True, low_fuel_run={'fuel_l': 30.0, 'avg_lap': 46.0})
    session['next_run'] = {'fuel_l': 120, 'tyres': 'Slick', 'laps': 6, 'objective': 'Full tank: ...'}
    session['engine_version'] = 3
    store.path(session['key']).write_text(json.dumps(session), encoding='utf-8')
    opened = store.get(session['key'])
    # 30 L covers a 20-minute race at 0.94 L a lap, so that run was already the race-fuel run
    assert opened['flags']['high_fuel_done'] and not opened['flags'].get('low_fuel_done')
    assert opened['next_run']['fuel_l'] == 28 and 'Full tank' not in opened['next_run']['objective']
