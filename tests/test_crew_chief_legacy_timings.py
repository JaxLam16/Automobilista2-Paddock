"""Both original timing implementations on the same actual AMS2 mapper/queue."""
from pathlib import Path
import hashlib,json,sys
import pytest
from ams2season.coach.crew_core import Core
from ams2season.coach.crew_mapper import DEFAULTS
import test_crew_chief_timings as current

pytestmark=pytest.mark.skipif(sys.platform!='win32',reason='Original .NET Framework timing host')

@pytest.fixture(params=['False','True'],ids=['current','legacy'])
def core(tmp_path,request):
    host=Core(root=tmp_path);number=host.settings['__paddock_number_config']
    host.settings=dict(DEFAULTS,__paddock_number_config=number,__paddock_state_directory=str(tmp_path/'state'),
        enable_rants='False',enable_driver_names='False',revert_to_legacy_version_of_refactored_code=request.param,
        frequency_of_gap_ahead_reports='10',frequency_of_gap_behind_reports='0',gap_message_randomness='1')
    host.timings_available=True;host.start()
    try:
        assert host.ready.wait(10),host.error
        yield host
    finally:host.close()

test_actual_splits=current.test_actual_game_splits_and_original_gap_questions
test_no_pair=current.test_no_pair_yet_and_zero_gap_return_original_no_data
test_no_race_gap_in_practice=current.test_racing_gap_question_does_not_invent_a_practice_or_qualifying_gap
test_extreme_positions=current.test_leader_and_last_place_use_original_position_words_after_observed_start
test_unknown_corners=current.test_unsupported_corner_comparison_and_unlearned_track_delta_are_no_data
test_recovery=current.test_disabled_timing_sample_clears_state_and_requires_recovery_pair
test_negative_split=current.test_unavailable_negative_game_split_cannot_become_a_one_second_gap
test_real_crossings=current.test_track_and_leader_gaps_use_actual_original_delta_history
def test_original_automatic_queue(core):
    current.test_original_automatic_gap_message_uses_shared_queue_and_reputation_is_empty_in_ams2(core)

def test_original_preference_selects_actual_event_type(core):
    raw=current.warm(core);result=current.step(core,raw,3)
    expected='legacy' if core.settings['revert_to_legacy_version_of_refactored_code']=='True' else 'current'
    assert result['timings_state']=='monitoring' and result['timings']['mode']==expected

def test_status_uses_original_phrase_and_numbers(core):
    current.warm(core);words=current.command(core,'SESSION_STATUS')
    assert 'timings/gap_in_front_is_now' in words
    assert any(x in ('numbers/5point0','numbers/5point0seconds') for x in words)

def test_legacy_event_source_and_exact_installed_missing_property_fallback_are_pinned():
    root=Path(__file__).resolve().parents[1];a=root/'ams2season/assets/crew_chief'
    original=root/'diagnostics/cc-timing-legacy-prep-20261017/installed-IL-source/Timings_legacy.cs'
    assert (a/'Timings_legacy.cs').read_bytes()==original.read_bytes()
    pin=json.loads((a/'core_sources.json').read_text())['Timings_legacy.cs']
    assert hashlib.sha256(original.read_bytes()).hexdigest()==pin['sha256']
    assert DEFAULTS['iracing_reputations_rating']=='0'
    installed=(root/'diagnostics/cc-timing-legacy-prep-20261017/dependency-IL-source/CrewChiefV4.UserSettings.cs').read_text()
    assert 'int getInt(string name)' in installed and 'return 0;' in installed
