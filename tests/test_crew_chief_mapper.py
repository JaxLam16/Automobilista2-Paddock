"""Original shared mapper, ABI bridge and freshness. Never connects to AMS2/audio."""
import base64
import ctypes as C
import hashlib
import json
from pathlib import Path
import sys

import pytest

from ams2season import shm as S
from ams2season.coach.crew_mapper import ALIASES, DEFAULTS, Mapper, snapshot_payload
from ams2season.coach.crew_spotter import ASSETS

TICKS = 638963172000000000
NATIVE = pytest.mark.skipif(sys.platform != 'win32', reason='Original .NET Framework mapper')


def snapshot():
    raw = S.SharedMemory()
    raw.mVersion = 14
    raw.mGameState = S.GAME_INGAME_PLAYING
    raw.mSessionState = S.SESSION_RACE
    raw.mRaceState = S.RACESTATE_RACING
    raw.mViewedParticipantIndex = 0
    raw.mNumParticipants = 3
    raw.mTrackLocation = b'Watkins_Glen'
    raw.mTrackVariation = b'Watkins_Glen_GP'
    raw.mTrackLength = 5472
    raw.mCarName = b'Nissan GT-R'
    raw.mCarClassName = b'GT3 Gen 0'
    raw.mNumSectors = 3
    raw.mLapsInEvent = 10
    raw.mEventTimeRemaining = -1
    raw.mFuelLevel = .5
    raw.mFuelCapacity = 100
    raw.mSpeed = 35
    raw.mOilTempCelsius = 110
    raw.mWaterTempCelsius = 95
    raw.mRpm = 4500
    raw.mMaxRPM = 8000
    raw.mLastOpponentCollisionIndex = -1
    raw.mEnforcedPitStopLap = -1
    raw.mLastLapTime = raw.mBestLapTime = -1
    for i, name in enumerate((b'Jax_Lam', b'Test Ahead', b'Test Behind')):
        p = raw.mParticipantInfo[i]
        p.mIsActive = True
        p.mName = name
        p.mRacePosition = (2, 1, 3)[i]
        p.mCurrentLapDistance = (1000, 1050, 950)[i]
        p.mLapsCompleted = 2
        p.mCurrentLap = 3
        p.mCurrentSector = 0
        raw.mRaceStates[i] = S.RACESTATE_RACING
        raw.mSpeeds[i] = 35
        raw.mCarClassNames[i].value = b'GT3 Gen 0'
        raw.mCarNames[i].value = b'Nissan GT-R'
        raw.mLastLapTimes[i] = raw.mFastestLapTimes[i] = 110
    for i in range(4):
        raw.mTyreCompound[i].value = b'slick_soft'
        raw.mTyreTempLeft[i] = 80+i
        raw.mTyreTempCenter[i] = 85+i
        raw.mTyreTempRight[i] = 90+i
        raw.mBrakeTempCelsius[i] = 400+i*10
        raw.mTyreWear[i] = .1
        raw.mTyreFlags[i] = 1
    return raw


@pytest.fixture
def native(tmp_path):
    # Real installed class/track definitions, private default settings, no game.
    mapper = Mapper(root=tmp_path)
    mapper.settings = dict(DEFAULTS)
    mapper.start()
    assert mapper.ready.wait(10), mapper.error
    try:
        yield mapper
    finally:
        mapper.close()


def mapped(mapper, raw=None, step=0):
    result = mapper.map_snapshot(raw or snapshot(), ticks=TICKS+step*10000000, local_slot=0, sample_age=0)
    assert result is not None, mapper.error
    assert result['mapped']
    return result


def test_original_sources_and_compiled_receipt_match():
    receipt = json.loads((ASSETS/'mapper_core.build.json').read_text(encoding='utf-8-sig'))
    for name, digest in receipt['sources'].items():
        assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest() == digest
    assert hashlib.sha256((ASSETS/receipt.get('assembly_file','mapper_core.dll')).read_bytes()).hexdigest() == receipt['assembly_sha256']
    provenance=json.loads((ASSETS/'mapper_sources.json').read_text(encoding='utf-8'))
    for name, item in provenance['projection'].items():
        digest = item.get('projected_sha256', item['sha256'])
        assert hashlib.sha256((ASSETS/name).read_bytes()).hexdigest() == digest
    # Exact pinned original decision sources; only UTC clocks are projected.
    assert hashlib.sha256((ASSETS/'GameStateMapper.cs').read_bytes()).hexdigest() == 'bab6df81baef6311ada65a6e381f1cec21c5bf9719e23a64a64ca01f94f2e5a7'
    assert hashlib.sha256((ASSETS/'CarData.cs').read_bytes()).hexdigest() == 'dabb24be0a240abd6a432132fe95f413329460cc565636123d05658d6b09750d'
    for name, digest in {'GameStateData.cs': '36452712e733aaa47015f9fefd5b5df36c0199fdf10bcfdaaf56ebb58831d85b',
                         'AMS2GameStateMapper.cs': '41ea86a1383a095015607eaf5b6e1daf0af1a693580fd5972c3286b5acf0fd67'}.items():
        # Source hash is also recorded with its one mechanical clock substitution.
        text = (ASSETS/name).read_text(encoding='utf-8')
        assert 'DateTime.UtcNow' not in text
        assert 'MapperClock.UtcNow' in text
        assert hashlib.sha256(text.replace('MapperClock.UtcNow', 'DateTime.UtcNow').encode()).hexdigest() == digest


def test_bridge_keeps_all_fixed_arrays_and_actual_ams2_tail_values():
    raw = snapshot()
    raw.mCarClassNames[1].value = b'GT4'
    raw.mOrientations[2][1] = .25
    raw.mLapsInvalidated[2] = True
    raw.mAntiLockSetting = 3
    raw.mTractionControlSetting = 5
    raw.mErsDeploymentMode = 4
    raw.mErsAutoModeEnabled = True
    raw.mClutchTemp = 145
    raw.mClutchWear = .3
    raw.mClutchSlipping = True
    data = snapshot_payload(raw)
    assert len(base64.b64decode(data['mParticipantData'][0]['mName'])) == 64
    assert len(base64.b64decode(data['mCarClassNames'])) == 4096
    assert base64.b64decode(data['mCarClassNames'])[64:67] == b'GT4'
    assert len(data['mOrientations']) == 192 and data['mOrientations'][7] == .25
    assert base64.b64decode(data['mLapsInvalidated'])[2] == 1
    assert data['mAntiLockSetting'] == 3 and data['mTractionControlSetting'] == 5
    assert data['mClutchTemp'] == 145 and data['mClutchWear'] == pytest.approx(.3)
    assert len(base64.b64decode(data['mLFTyreCompoundName'])) == 40
    assert data['mmfOnly_mNumSectors'] == 3


def test_reduced_replays_are_not_accepted_as_complete_native_input():
    with pytest.raises(TypeError, match='complete'):
        snapshot_payload({'laps': 2, 'speed': 35})


def test_nan_in_raw_snapshot_is_withheld_instead_of_filled_with_zero():
    raw = snapshot()
    raw.mOilTempCelsius = float('nan')
    mapper = Mapper(host=lambda payload: pytest.fail('Invalid input reached native mapper'))
    assert mapper.map_snapshot(raw, ticks=TICKS, local_slot=0, sample_age=0) is None
    assert 'Non-finite' in mapper.data_error and mapper.error is None


@pytest.mark.parametrize('change', ['stale', 'not_fresh', 'odd_sequence', 'paused', 'replay', 'spectating', 'inactive', 'old_version', 'bad_slot', 'zero_track'])
def test_invalid_input_does_not_start_or_advance_native_history(change):
    raw = snapshot()
    kwargs = dict(ticks=TICKS, local_slot=0, sample_age=0, fresh=True)
    if change == 'stale': kwargs['sample_age'] = .251
    if change == 'not_fresh': kwargs['fresh'] = False
    if change == 'odd_sequence': raw.mSequenceNumber = 3
    if change == 'paused': raw.mGameState = S.GAME_INGAME_PAUSED
    if change == 'replay': raw.mGameState = S.GAME_INGAME_REPLAY
    if change == 'spectating': raw.mViewedParticipantIndex = 1
    if change == 'inactive': raw.mParticipantInfo[0].mIsActive = False
    if change == 'old_version': raw.mVersion = 9
    if change == 'bad_slot': kwargs['local_slot'] = None
    if change == 'zero_track': raw.mTrackLength = 0
    mapper = Mapper(host=lambda payload: pytest.fail('Invalid input reached native mapper'))
    assert mapper.map_snapshot(raw, **kwargs) is None
    assert mapper.state == 'withheld_invalid_or_stale_snapshot'


@NATIVE
def test_original_struct_layout_is_measured_but_never_overlaid_on_ams2(native):
    layout = native._request({'op': 'layout'})
    assert layout['participantSize'] == C.sizeof(S.ParticipantInfo)
    for name, offset in layout['participantFields'].items():
        assert offset == getattr(S.ParticipantInfo, name).offset
    assert layout['fields']['mDPad'] != S.SharedMemory.mDPad.offset
    assert layout['fields']['mClutchOverheated'] != S.SharedMemory.mClutchOverheated.offset
    # Tail booleans and masks must be copied by name, not using this native ABI.
    assert layout['fields']['mParticipantData'] == S.SharedMemory.mParticipantInfo.offset


@NATIVE
def test_complete_original_mapper_maps_engine_tyres_and_header_tail(native):
    raw = snapshot()
    raw.mAntiLockSetting = 3
    raw.mTractionControlSetting = 5
    raw.mErsDeploymentMode = 4
    raw.mErsAutoModeEnabled = True
    raw.mClutchTemp = 145
    raw.mClutchWear = .3
    raw.mClutchSlipping = True
    result = mapped(native, raw)
    assert result['class_name'] == 'GT3'
    assert (result['oil'], result['water'], result['fuel']) == (110, 95, 50)
    assert result['brake_temps'] == [400, 410, 420, 430]
    assert result['tyre_tread'] == [[80+i, 85+i, 90+i] for i in range(4)]
    assert result['tyre_type'] == 'Soft'
    assert result['transmission'] == 'NONE'
    tail = result['raw_tail']
    assert tail == {'abs': 3, 'tc': 5, 'ers': 4, 'ers_auto': True, 'clutch_temp': 145,
                    'clutch_wear': pytest.approx(.3), 'clutch_overheated': False, 'clutch_slipping': True, 'yellow': 0}
    raw.mClutchOverheated = True
    hot = mapped(native, raw, 1)
    assert hot['raw_tail']['clutch_overheated'] is True
    # Original mapper deliberately disables this unreliable AMS2 damage signal.
    assert hot['transmission'] == 'NONE'


@NATIVE
def test_original_leader_and_ahead_pit_entry_is_a_single_transition(native):
    raw = snapshot()
    mapped(native, raw)
    mapped(native, raw, 1)
    raw.mPitModes[1] = S.PIT_MODE_DRIVING_INTO_PITS
    result = mapped(native, raw, 2)
    assert result['leader_pitting'] and result['ahead_pitting']
    assert result['opponents']['Test Ahead']['entered_pits']
    result = mapped(native, raw, 3)
    assert not result['leader_pitting'] and not result['ahead_pitting']
    assert result['opponents']['Test Ahead']['in_pits']
    assert not result['opponents']['Test Ahead']['entered_pits']


@NATIVE
def test_original_multiclass_positions_settle_and_use_installed_class_groups(native):
    raw = snapshot()
    raw.mCarClassNames[1].value = b'GT4'
    # Original first tick counts classes, next tick sorts the class positions.
    first = mapped(native, raw)
    result = mapped(native, raw, 1)
    assert first['classes'] == result['classes'] == 2
    assert result['position'] == 2 and result['class_position'] == 1
    assert result['opponents']['Test Ahead']['class_position'] == 1
    assert result['opponents']['Test Behind']['class_position'] == 2


@NATIVE
def test_original_fixed_duration_stays_in_seconds(native):
    raw = snapshot()
    raw.mSessionState = S.SESSION_PRACTICE
    raw.mLapsInEvent = 0
    raw.mSessionDuration = 1200
    raw.mEventTimeRemaining = 1100
    first = mapped(native, raw)
    raw.mEventTimeRemaining = 1099
    result = mapped(native, raw, 1)
    assert first['session_type'] == 'Practice'
    assert first['remaining'] == 1100 and result['remaining'] == 1099
    # Preserve original late-join inference; no invented full scheduled duration.
    assert first['duration'] == result['duration'] == 1100


@NATIVE
def test_original_sector_and_lap_transitions_survive_mapping_history(native):
    raw = snapshot()
    mapped(native, raw)
    for p in raw.mParticipantInfo[:3]:
        p.mCurrentSector = 1
    sector2 = mapped(native, raw, 1)
    assert sector2['new_sector'] and sector2['sector'] == 2 and not sector2['new_lap']
    for p in raw.mParticipantInfo[:3]:
        p.mCurrentSector = 2
    mapped(native, raw, 2)
    for p in raw.mParticipantInfo[:3]:
        p.mLapsCompleted += 1
        p.mCurrentLap += 1
        p.mCurrentSector = 0
        p.mCurrentLapDistance = 20
    lap = mapped(native, raw, 3)
    assert lap['new_lap'] and lap['laps'] == 3 and lap['sector'] == 1
    assert all(p['new_lap'] for p in lap['opponents'].values())
    assert not mapped(native, raw, 4)['new_lap']


@NATIVE
def test_new_session_type_clears_the_previous_session(native):
    raw = snapshot()
    raw.mSessionState = S.SESSION_PRACTICE
    assert mapped(native, raw)['session_type'] == 'Practice'
    raw.mSessionState = S.SESSION_QUALIFY
    quali = mapped(native, raw, 1)
    assert quali['new_session'] and quali['session_type'] == 'Qualify'
    raw.mSessionState = S.SESSION_RACE
    race = mapped(native, raw, 2)
    assert race['new_session'] and race['session_type'] == 'Race'


@NATIVE
def test_original_frozen_order_uses_opponent_history_and_authoritative_yellow(native):
    raw = snapshot()
    mapped(native, raw)
    raw.mYellowFlagState = 1
    result = mapped(native, raw, 1)
    assert result['phase'] == 'FullCourseYellow'
    assert result['fcy'] == 'PENDING'
    assert result['frozen_phase'] == 'FullCourseYellow'
    assert result['frozen_action'] == 'Follow'
    raw.mYellowFlagState = 0
    result = mapped(native, raw, 2)
    assert result['phase'] == 'Green' and result['fcy'] == 'RACING'
    assert result['frozen_action'] == 'None'


@NATIVE
def test_monotonic_history_requires_explicit_reset_for_replay_seek(native):
    first = mapped(native)
    assert native.map_snapshot(snapshot(), ticks=TICKS, local_slot=0, sample_age=0) is None
    assert native.reset_mapping()
    assert mapped(native)['new_session']


@NATIVE
@pytest.mark.parametrize('name,expected', [('Jax_Lam', 'jax lam'), ('[TEAM]JohnSmith42', 'john smith'), ('Ayrton Senna', 'ayrton senna')])
def test_original_driver_name_cleaning_is_available_without_sound_or_preferences_writes(native, name, expected):
    assert native._request({'op': 'name', 'name': name})['name'] == expected
