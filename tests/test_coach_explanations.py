"""Zero calls distinguishes missing features, absent triggers and actual holds."""
from dataclasses import replace
from pathlib import Path
import json

import pytest

from ams2season.coach.replay import run_replay
from test_coach_replay import tick, write_recording


def test_race_without_stops_reports_no_trigger_not_a_voice_or_window_failure(tmp_path):
    recording=tmp_path/'race';write_recording(recording,[tick(i*.1) for i in range(470)])
    report=run_replay(recording,tmp_path)
    assert report['counts'].get('would_say',0)==0
    assert report['engine']['diagnostics']['usable_radio_window_ticks']>0
    assert report['engine']['learned_laps']==2
    assert report['explanation']['code']=='no_pit_entry_samples'
    assert 'no call candidates' in report['explanation']['text']
    content=Path(report['review']).read_text(encoding='utf-8')
    assert 'Still being built' in content and 'Braking and throttle advice' in content
    assert report['inputs_unchanged']


def test_practice_replay_explains_missing_fuel_evidence_without_applying_race_rules(tmp_path):
    recording=tmp_path/'practice';meta=write_recording(recording)
    meta['session_type']='practice'
    (recording/'session.json').write_text(json.dumps(meta))
    report=run_replay(recording,tmp_path)
    assert report['explanation']['code']=='insufficient_fuel_evidence'
    assert report['engine']['diagnostics']['active_ticks']>0
    assert report['explanation']['capabilities']['implemented_rules'][0]['sessions']==['race']


def test_wrong_driver_reports_unusable_telemetry_instead_of_no_incidents(tmp_path):
    recording=tmp_path/'race';write_recording(recording)
    report=run_replay(recording,tmp_path,driver='Wrong driver')
    assert report['explanation']['code']=='no_active_telemetry'
    assert report['engine']['inactive_reasons']['driver_unknown']==470


@pytest.mark.parametrize('fault,reason',[('silent','verbosity'),('invalid','no radio window')])
def test_observed_candidates_withheld_by_a_filter_explain_that_filter(tmp_path,fault,reason):
    recording=tmp_path/'race'
    frames=[tick(i*.1,pit=1 if i>=450 else 0,invalid=(fault=='invalid' and i==100)) for i in range(470)]
    write_recording(recording,frames)
    report=run_replay(recording,tmp_path,mode='silent' if fault=='silent' else 'full')
    assert report['explanation']['code']=='calls_withheld'
    assert reason in report['explanation']['text']
    assert report['engine']['diagnostics']['observed_relevant_pit_entries']==1


def test_garage_spawn_or_existing_pit_state_is_not_called_a_new_stop(tmp_path):
    recording=tmp_path/'race';write_recording(recording,[tick(i*.1,pit=1) for i in range(470)])
    report=run_replay(recording,tmp_path)
    assert report['explanation']['code']=='no_relevant_pit_entry'
    assert report['engine']['diagnostics']['racing_pit_entry_samples']>0
    assert not report['counts'].get('queued')
