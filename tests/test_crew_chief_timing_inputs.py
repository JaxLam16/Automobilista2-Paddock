"""Timing input withdrawal, installed grammar and boundary validation."""
import hashlib,json,time
import pytest
from ams2season.coach.crew_core import Core,timing_inputs_available
from ams2season.coach.crew_spotter import ASSETS
from ams2season.coach.crew_timings import COMMANDS,FOLDERS,command_for
from ams2season.coach.telemetry import from_snapshot
from test_crew_chief_damage import raw_state


def test_installed_gap_grammar_and_build_metadata():
    receipt=json.loads((ASSETS/'mapper_core.build.json').read_text(encoding='utf-8-sig'))
    for name in ('timing_speech.json','timing_folders.json'):
        assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()==receipt['metadata'][name]
    for key,phrases in COMMANDS.items():
        for phrase in phrases:assert command_for(phrase.upper()+'?')==key
    assert command_for('what is the fuel level') is None
    assert 'opponents/one_lap_ahead' in FOLDERS


@pytest.mark.parametrize('field,value',[
    ('mTrackLength',float('nan')),('mTrackLength',0),('mNumSectors',0),
    ('mNumSectors',4),('mRaceState',99),('mPitMode',6),
    ('mSplitTimeAhead',float('nan')),('mSplitTimeBehind',-2)])
def test_invalid_gap_channels_are_withheld(field,value):
    raw=raw_state();assert timing_inputs_available(raw)
    setattr(raw,field,value);assert not timing_inputs_available(raw)


@pytest.mark.parametrize('field,value',[
    ('mCurrentSector',3),('mLapsCompleted',10000),
    ('mCurrentLapDistance',float('nan')),('mCurrentLapDistance',6000)])
def test_invalid_opponent_crossing_data_is_withheld(field,value):
    raw=raw_state();setattr(raw.mParticipantInfo[1],field,value)
    assert not timing_inputs_available(raw)


def test_negative_split_sentinel_reaches_native_availability_guard_without_fabrication():
    raw=raw_state();raw.mSplitTimeAhead=raw.mSplitTimeBehind=-1
    assert timing_inputs_available(raw)


def test_live_timing_input_withdrawal_bypasses_cadence_and_stale_input_resets():
    requests=[]
    core=Core(host=lambda p:requests.append(p) or {'mapped':True,'events':{'valid':[],'calls':[]}})
    raw=raw_state();sampled=time.perf_counter()-.03
    tick=from_snapshot(raw,0,'timing')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled,respect_update_interval=True)
    assert requests[-1]['timings_available']
    raw.mNumSectors=0;tick=from_snapshot(raw,.01,'timing')
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),sampled+.01,respect_update_interval=True)
    assert len(requests)==2 and not requests[-1]['timings_available']
    assert requests[-1]['position_available'] and requests[-1]['engine_available']
    core.feed_snapshot(raw,tick,tick.player('Jax_Lam'),time.perf_counter()-1)
    assert not core.latest and not core.timings_available and not core.timings_data
