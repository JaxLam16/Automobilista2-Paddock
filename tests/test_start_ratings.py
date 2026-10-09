"""Opportunity-balanced race starts and evidence/season regressions."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ams2season import profiles
from ams2season.derive import Session
from ams2season.legends import scores_from_raw, start_score
from ams2season.race import _observed_start_grid, _start_lap1_position
from ams2season.season import SeasonConfig, connect


@pytest.mark.parametrize('size', [2, 5, 32])
def test_every_gain_and_loss_are_on_the_correct_side_of_neutral(size):
    for grid in range(1, size + 1):
        for position in range(1, size + 1):
            value = start_score(grid, position, size)
            assert 0 <= value <= 100
            if position < grid:
                assert value > 50
            elif position > grid:
                assert value < 50
            else:
                assert value == (100 if grid == 1 else 50)


def test_opportunity_normalization_does_not_reward_starting_at_the_back():
    assert start_score(2, 1, 20) > start_score(10, 9, 20) > start_score(20, 19, 20) > 50
    assert start_score(10, 10, 20) == start_score(20, 20, 20) == 50
    # Starting grid/field alone cannot influence identical passing opportunity.
    assert start_score(10, 8, 20) == start_score(10, 8, 40)
    # Each extra gain improves the same driver's score, each loss lowers it.
    assert start_score(10, 5, 20) > start_score(10, 8, 20)
    assert start_score(10, 15, 20) < start_score(10, 12, 20)


@pytest.mark.parametrize('values', [
    (None, 1, 20), (True, 1, 20), ('1', 1, 20), (np.nan, 1, 20),
    (1, np.inf, 20), (1, 1, -1), (1, 1, 1), (0, 1, 20),
    (21, 1, 20), (1, 0, 20), (1, 21, 20), (1.5, 1, 20), (2, 1, 20.5),
])
def test_invalid_or_uncompetitive_start_is_unrated(values):
    assert start_score(*values) is None


def test_explicit_missing_start_score_never_uses_old_gain_fallback():
    assert scores_from_raw({'start_score': None, 'lap1_gain': 6})['starts'] is None
    assert scores_from_raw({'start_score': np.nan, 'lap1_gain': 6})['starts'] is None
    assert scores_from_raw({'start_score': True, 'lap1_gain': 6})['starts'] is None
    assert scores_from_raw({'start_score': 0, 'lap1_gain': 6})['starts'] == 0
    assert scores_from_raw({'start_score': 75, 'lap1_gain': -6})['starts'] == 75
    assert scores_from_raw({'lap1_gain': 0})['starts'] == 50  # gain-only legacy caller


def real_cases():
    return json.loads((Path(__file__).parent / 'data/starts/real_start_cases.json').read_text())['cases']


def as_session(case):
    frames = pd.DataFrame(case['frames'])
    session = Session(Path(case['source']), {'green_t': case['green_t'], 'track_length': case['track_length']},
                      frames, pd.DataFrame(), [case['green_event']])
    return session, frames


@pytest.mark.parametrize('case', real_cases(), ids=lambda c: c['source'])
def test_real_recorded_starts_use_game_grid_and_first_lap(case):
    session, frames = as_session(case)
    observed = _observed_start_grid(session, frames)
    position = _start_lap1_position(pd.DataFrame([case['lap']]), frames[frames.name == case['local']],
                                   case['green_t'], len(observed))
    expected = case['expected']
    assert observed[case['local']] == expected['grid']
    assert len(observed) == expected['field_size']
    assert position == expected['lap1_pos']
    value = start_score(observed[case['local']], position, len(observed))
    if expected['grid'] == 1 and position == 1:
        assert value == 100
    elif position == expected['grid']:
        assert value == 50
    else:
        # The former zero was the actual recorded 1 -> 26 first lap, not missing
        # data. Field normalization keeps the severity without tanh rounding to 0.
        assert expected['grid'] == 1 and position == 26 and 5 < value < 6


def test_a_genuinely_late_or_incomplete_capture_is_not_a_bad_start():
    case = copy.deepcopy(real_cases()[-1])
    session, frames = as_session(case)
    frames.loc[:, 'speed'] = 45.
    assert _observed_start_grid(session, frames) == {}
    frames.loc[:, 'speed'] = .1
    frames.loc[:, 'laps_completed'] = 3
    assert _observed_start_grid(session, frames) == {}
    session.events = []  # no observed event or pre-green grid
    assert _observed_start_grid(session, frames) == {}
    session, frames = as_session(case)
    local = frames[frames.name == case['local']]
    laps = pd.DataFrame([case['lap']])
    assert np.isnan(_start_lap1_position(laps[laps.lap != 1], local, 0, 32))
    assert np.isnan(_start_lap1_position(laps, local[local.t > 10], 0, 32))
    missing = local[~local.t.between(20, 25)]
    assert np.isnan(_start_lap1_position(laps, missing, 0, 32))
    no_completion = local.copy(); no_completion.loc[:, 'laps_completed'] = 0
    assert np.isnan(_start_lap1_position(laps, no_completion, 0, 32))


def test_grid_opportunities_ignore_late_joiners_and_reject_unknown_slots():
    case = copy.deepcopy(real_cases()[-1]); session, frames = as_session(case)
    extra = frames[frames.name == case['local']].copy(); extra['name'] = 'Late joiner'; extra['t'] += 50
    both = pd.concat([frames, extra], ignore_index=True)
    grid = _observed_start_grid(session, both)
    assert len(grid) == 32 and 'Late joiner' not in grid
    session.events[0]['grid'][case['local']] = 1
    assert _observed_start_grid(session, frames) == {}
    session.events[0]['grid'].pop(case['local'])
    session.events[0]['grid'].pop(next(n for n, p in session.events[0]['grid'].items() if p == 10))
    assert _observed_start_grid(session, frames) == {}


def test_profiles_average_per_race_scores_and_missing_evidence_stays_missing(tmp_path, monkeypatch):
    db = tmp_path / 'starts.db'
    con = connect(db)
    for i in range(1, 4):
        con.execute('INSERT INTO event(id,round) VALUES(?,?)', (i, i))
        con.execute("INSERT INTO session(id,event_id,type,path) VALUES(?,?,'race',?)", (i, i, str(i)))
    con.commit(); con.close()
    config = SeasonConfig(drivers=[{'key': 'jax', 'display': 'Jax'}])
    rounds = [{'round': i, 'race_no': 1, 'track': 'Test', 'started_at': '2026-10-08',
               'recording': str(i), 'recording_exists': True} for i in range(1, 4)]
    samples = [start_score(2, 1, 20), start_score(20, 19, 20), None]

    def measurement(recording):
        value = samples[int(recording) - 1]
        return {'Jax': {'raw': {'start_score': value, 'lap1_gain': 1 if value is not None else None},
                        'totals': dict(errors=0, spins=0, passes=0),
                        'opportunities': dict(attack_laps=0, pass_laps=0, defend_laps=0, lost_laps=0)}}

    lib = SimpleNamespace(root=tmp_path, _refresh_champ_analysis=lambda _: None, _db=lambda _: db,
                          _cfg=lambda _: config, _analysis=lambda recording, _: (recording, None),
                          tyre_care=lambda *args: [])
    monkeypatch.setattr(profiles, 'rounds_summary', lambda *args: rounds)
    monkeypatch.setattr(profiles, 'measurements', measurement)
    result = profiles.build(lib, 'test')['profiles'][0]
    expected = round(np.mean(samples[:2]))
    assert result['scores']['starts'] == expected
    assert result['samples']['starts'] == 2 and result['races'] == 3
    assert [x['cumulative_scores']['starts'] for x in result['history']] == [100, expected, expected]
    assert result['history'][2]['scores']['starts'] is None
    # Current snapshots remain useful with missing recordings; old scoring
    # snapshots must not silently become current opportunity-balanced scores.
    for race in rounds: race['recording_exists'] = False
    assert profiles.build(lib, 'test')['profiles'][0]['scores']['starts'] == expected
    con = connect(db); con.execute('UPDATE profile_sample SET version=?', (profiles.VERSION - 1,)); con.commit(); con.close()
    stale = profiles.build(lib, 'test')
    assert stale['profiles'] == [] and len(stale['problems']) == 3
