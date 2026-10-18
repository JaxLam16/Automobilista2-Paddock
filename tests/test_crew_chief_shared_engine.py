"""Original EngineMonitor on complete AMS2 state. No game, speakers or microphone."""
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from ams2season import shm as S
from ams2season.coach.crew_core import Core
from ams2season.coach.crew_mapper import DEFAULTS, snapshot_payload
from ams2season.coach.crew_spotter import ASSETS
from ams2season.coach.telemetry import from_snapshot
from test_crew_chief_conditions import weather_snapshot
from test_crew_chief_mapper import TICKS

NATIVE = pytest.mark.skipif(sys.platform != 'win32', reason='Original Framework event host')


@pytest.fixture
def core(tmp_path, request):
    host = Core(root=tmp_path)
    numbers = json.loads(host.settings['__paddock_number_config'])
    numbers['allow_short_hundreds'] = 'false'
    host.settings = dict(DEFAULTS, __paddock_number_config=json.dumps(numbers))
    host.settings.update(getattr(request, 'param', {}))
    host.engine_available = True
    host.weather_available = True
    host.start()
    assert host.ready.wait(10), host.error
    try:
        yield host
    finally:
        host.close()


def native_map(core, raw, seconds=0):
    result = core._request({'op': 'map', 'ticks': TICKS+round(seconds*10000000), 'raw': snapshot_payload(raw)})
    assert result and not result.get('error'), result or core.error
    assert result['mapped']
    return result


def stop_engine(core, raw):
    raw.mSpeed = 0
    if raw.mSessionState == S.SESSION_QUALIFY:
        raw.mLapsInEvent = 0
        raw.mEventTimeRemaining = 600
    native_map(core, raw)
    if raw.mSessionState == S.SESSION_QUALIFY: raw.mEventTimeRemaining = 535
    native_map(core, raw, 65)
    raw.mRpm = 0
    assert not native_map(core, raw, 66)['stalled']
    assert not native_map(core, raw, 67)['stalled']
    return native_map(core, raw, 67.1)


def test_shared_engine_uses_byte_identical_original_and_build_receipt():
    receipt = json.loads((ASSETS/'core_sources.json').read_text())['EngineMonitor.cs']
    assert receipt['sha256'] == '336a728eb21d26702a373309b1ab110a026e0750030ad79a2411eb804497675a'
    assert hashlib.sha256((ASSETS/'EngineMonitor.cs').read_bytes()).hexdigest() == receipt['sha256']
    assert json.loads((ASSETS/'mapper_core.build.json').read_text(encoding='utf-8-sig'))['sources']['EngineMonitor.cs'] == receipt['sha256']


@NATIVE
def test_original_mapper_stall_after_two_seconds_and_event_two_minute_cooldown(core):
    raw = weather_snapshot()
    result = stop_engine(core, raw)
    assert result['stalled'] and result['running'] == pytest.approx(67.1)
    call, = result['events']['calls']
    assert call['fragments'] == ['engine_monitor/stalled']
    assert call['immediate'] and call['expires_s'] == 3 and call['source_event'] == 'EngineMonitor_4.19.5.4'
    core._events(result['events'])
    core.acknowledge('core:'+call['id'])
    raw.mRpm = 1000
    assert native_map(core, raw, 68)['events']['valid'] == []
    raw.mRpm = 0
    assert native_map(core, raw, 71)['events']['calls'] == []
    raw.mRpm = 1000
    native_map(core, raw, 188)
    raw.mRpm = 0
    assert native_map(core, raw, 191)['events']['calls'][0]['fragments'] == ['engine_monitor/stalled']


@NATIVE
@pytest.mark.parametrize('reason', ['destroyed_engine', 'destroyed_suspension', 'pits', 'moving', 'practice'])
def test_original_stall_exclusions(core, reason):
    raw = weather_snapshot()
    raw.mSpeed = 0
    if reason == 'destroyed_engine': raw.mEngineDamage = 1
    if reason == 'destroyed_suspension': raw.mSuspensionDamage[0] = 1
    if reason == 'pits': raw.mPitModes[0] = raw.mPitMode = S.PIT_MODE_IN_PIT
    if reason == 'moving': raw.mSpeed = 6
    if reason == 'practice': raw.mSessionState = S.SESSION_PRACTICE
    native_map(core, raw)
    native_map(core, raw, 65)
    raw.mRpm = 0
    native_map(core, raw, 66)
    result = native_map(core, raw, 68)
    assert not result['events']['calls']
    if reason == 'destroyed_engine': assert result['engine_damage'] == 'DESTROYED'
    if reason == 'destroyed_suspension': assert result['suspension_destroyed']
    if reason == 'pits': assert result['in_pits'] and not result['stalled']
    else: assert result['stalled']


@NATIVE
@pytest.mark.parametrize('core', [{'just_the_facts': 'True'}], indirect=True)
def test_original_just_the_facts_setting_suppresses_stalled_message(core):
    result = stop_engine(core, weather_snapshot())
    assert result['stalled'] and result['events']['calls'] == []


@NATIVE
@pytest.mark.parametrize('session', [S.SESSION_RACE, S.SESSION_QUALIFY])
def test_original_stall_supported_race_and_qualifying(core, session):
    raw = weather_snapshot()
    raw.mSessionState = session
    assert stop_engine(core, raw)['events']['calls'][0]['fragments'] == ['engine_monitor/stalled']


@NATIVE
def test_original_heat_window_recovery_and_shared_class_limits(core):
    raw = weather_snapshot()
    calls = []
    states = {}
    for i in range(990):
        t = i/4
        raw.mOilTempCelsius = 170 if t < 190 else 90
        raw.mWaterTempCelsius = 150 if t < 190 else 80
        result = native_map(core, raw, t)
        states[t] = result['events']['engine_state']
        calls.extend((t, c) for c in result['events']['calls'])
    assert result['oil_limit'] == 135 and result['water_limit'] == 115
    assert states[120] == 'warming_up' and states[120.25] == 'monitoring'
    assert [c['fragments'] for _, c in calls] == [['engine_monitor/hot_oil_and_water'], ['engine_monitor/all_clear']]
    assert 180 < calls[0][0] < 181 and 240 < calls[1][0] < 242
    assert calls[0][1]['priority'] == 10 and not calls[0][1]['immediate']


@NATIVE
def test_original_mapped_gt3_oil_limit_is_not_old_default_threshold(core):
    raw = weather_snapshot()
    raw.mOilTempCelsius = 132
    for i in range(191):
        result = native_map(core, raw, i)
        assert result['events']['calls'] == []
    assert result['oil_limit'] == 135
    # The shared mapper actually identifies the installed class instead of using
    # the old helper's 130C fallback for an unrecognised class spelling.
    answer = core._request({'op': 'command', 'command': 'HOW_ARE_MY_ENGINE_TEMPS'})
    assert answer['calls'][0]['fragments'] == ['engine_monitor/all_clear']


@NATIVE
@pytest.mark.parametrize('fahrenheit,unit,oil,water', [(False, 'celsius', 110, 95), (True, 'fahrenheit', 230, 203)])
def test_four_original_engine_commands_resolve_original_numbers_and_units(core, fahrenheit, unit, oil, water):
    raw = weather_snapshot()
    core._fahrenheit = fahrenheit
    native_map(core, raw)
    native_map(core, raw, 121)
    # Retain samples after the first original averaging-window reset.
    native_map(core, raw, 122)
    # Original EngineMonitor stores rounded temperatures as float, so unchanged
    # AbstractEvent resolves them through the fractional reader (including .00).
    def number(value):
        return (['numbers/'+str(value)] if value < 100 else
                ['numbers/'+str(value//100), 'numbers/hundred_and', 'numbers/'+str(value%100)]) + ['numbers/point', 'numbers/0', 'numbers/0']
    expected = {
        'WHAT_IS_MY_OIL_TEMP': ['engine_monitor/oil_temp_intro', *number(oil), 'conditions/'+unit],
        'WHAT_IS_MY_WATER_TEMP': ['engine_monitor/water_temp_intro', *number(water), 'conditions/'+unit],
        'WHAT_ARE_MY_ENGINE_TEMPS': ['engine_monitor/oil_temp_intro', *number(oil), 'engine_monitor/water_temp_intro', *number(water), 'conditions/'+unit],
        'HOW_ARE_MY_ENGINE_TEMPS': ['engine_monitor/all_clear'],
    }
    for command, fragments in expected.items():
        result = core._request({'op': 'command', 'command': command})
        assert result['calls'][0]['fragments'] == fragments
        assert result['calls'][0]['folders_resolved'] and result['calls'][0]['immediate']


@NATIVE
def test_missing_weather_cannot_withdraw_engine_and_missing_engine_cannot_withdraw_weather(core):
    raw = weather_snapshot()
    native_map(core, raw)
    answer = core._request({'op': 'command', 'command': 'WHAT_IS_MY_OIL_TEMP'})
    engine_id = answer['calls'][0]['id']
    core.weather_available = False
    result = native_map(core, raw, 1)['events']
    assert engine_id in result['valid']
    core.weather_available = True
    native_map(core, raw, 2)
    answer = core._request({'op': 'command', 'command': 'WHATS_THE_AIR_TEMP'})
    weather_id = answer['calls'][0]['id']
    core.engine_available = False
    result = native_map(core, raw, 3)['events']
    assert weather_id in result['valid'] and engine_id not in result['valid']
    assert result['engine_state'] == 'engine_telemetry_unavailable'
    assert core._request({'op': 'command', 'command': 'WHAT_IS_MY_OIL_TEMP'})['calls'] == []


@NATIVE
def test_native_new_session_resets_engine_warmup_and_withdraws_previous_calls(core):
    raw = weather_snapshot()
    native_map(core, raw)
    native_map(core, raw, 130)
    reply = core._request({'op': 'command', 'command': 'WHAT_IS_MY_OIL_TEMP'})
    assert reply['valid']
    raw.mSessionState = S.SESSION_QUALIFY
    result = native_map(core, raw, 131)
    assert result['new_session'] and result['running'] == 0
    assert result['events']['engine_state'] == 'warming_up' and result['events']['valid'] == []


@NATIVE
def test_ams2_pressure_values_do_not_invent_unmapped_warning_flags(core):
    raw = weather_snapshot()
    raw.mOilPressureKPa = raw.mFuelPressureKPa = 0
    native_map(core, raw)
    result = native_map(core, raw, 130)
    assert result['events']['calls'] == []


@pytest.mark.parametrize('invalid', ['oil', 'engine_health', 'suspension_health'])
def test_live_engine_input_gate_withholds_invalid_channels_independently(invalid):
    requests = []
    def native(payload):
        requests.append(payload)
        return {'mapped': True, 'events': {'calls': [], 'valid': []}}
    host = Core(host=native)
    raw = weather_snapshot()
    if invalid == 'oil': raw.mOilTempCelsius = 0
    if invalid == 'engine_health': raw.mEngineDamage = -1
    if invalid == 'suspension_health': raw.mSuspensionDamage[3] = -1
    tick = from_snapshot(raw, 0, 'race')
    host.feed_snapshot(raw, tick, tick.player('Jax_Lam'), time.perf_counter())
    assert requests[-1]['weather_available'] and not requests[-1]['engine_available']
    assert host.latest is not None


@NATIVE
def test_live_worker_engine_question_runs_shared_host_only_and_silent_radio(tmp_path, monkeypatch):
    from ams2season.app import App
    from ams2season.recorder import Recorder
    from ams2season.coach.speech import LocalRadio
    from test_coach_service import wait_until,snapshot_stream
    import ams2season.coach.service as module
    app = App(tmp_path)
    app.recorder.thread = SimpleNamespace(is_alive=lambda: True)
    app.recorder.rec = Recorder(tmp_path/'recordings', sessions=(), log=lambda _: None)
    raw = weather_snapshot()
    app.recorder.rec.step(raw, time.perf_counter())
    service = app.coach
    service.output = 'paddock'; service.audio_enabled = True; service.tts_fallback = False
    played = []
    monkeypatch.setattr(module, 'LocalRadio', lambda voice, **kwargs: LocalRadio(voice, sink=(played.append, lambda: None), effect='off'))
    try:
        with snapshot_stream(app,raw):
            service.start()
            assert service.core.ready.wait(10), service.core.error
            wait_until(lambda: service.core.latest is not None and time.perf_counter()-service.core.latest['at']<.15)
            with service.lock:
                reply = service._engine_reply('what are my engine temperatures', 'typed')
                assert reply['understood'] == 'WHAT_ARE_MY_ENGINE_TEMPS' and 'queued' in reply['response']
                call = service.baseline_pending[-1]
                assert call['source_event'] == 'EngineMonitor_4.19.5.4' and call['native_id'].startswith('core:')
                fragments = call['fragments']
                assert fragments[0] == 'engine_monitor/oil_temp_intro'
                assert fragments[-6:] == ['engine_monitor/water_temp_intro', 'numbers/95', 'numbers/point', 'numbers/0', 'numbers/0', 'conditions/celsius']
                assert fragments[1:-6] in (['numbers/1', 'numbers/10', 'numbers/point', 'numbers/0', 'numbers/0'],
                    ['numbers/1', 'numbers/hundred_and', 'numbers/10', 'numbers/point', 'numbers/0', 'numbers/0'])
                status = service.status()
                assert status['engine_monitor']['source'] == 'original_shared_mapper'
                assert status['original_core']['events'] == ['Position', 'LapCounter', 'Timings', 'LapTimes', 'PitStops', 'Fuel', 'RaceTime', 'TyreMonitor', 'EngineMonitor', 'DamageReporting', 'ConditionsMonitor', 'SessionEndMessages']
                assert not status['crew_chief_baseline']['complete']
                assert 'warm-up' in service._engine_reply('how are my engine temps', 'typed')['response']
                assert service._deliver_baseline()
            wait_until(lambda: bool(played))
        assert not hasattr(service, 'engine_monitor')  # no duplicate legacy event process
        process = service.core.process
        service.stop()
        assert process.poll() is not None and not service.core.valid_ids
        assert not list((tmp_path/'recordings').iterdir())
    finally:
        service.close()


@NATIVE
def test_shared_core_reopens_after_output_route_change_with_new_history(core):
    raw = weather_snapshot()
    tick = from_snapshot(raw, 0, 'race')
    core.feed_snapshot(raw, tick, tick.player('Jax_Lam'), time.perf_counter())
    assert core.latest and core._confirmed
    process = core.process
    core.close()
    assert process.poll() is not None and core.latest is None and core._confirmed is None
    core.start()
    assert core.ready.wait(10), core.error
    tick = from_snapshot(raw, 1, 'race')
    core.feed_snapshot(raw, tick, tick.player('Jax_Lam'), time.perf_counter())
    assert core.latest and core.engine_state == 'warming_up' and core.process is not process
