"""Automatic-call choices must not reset sessions, silence replies or edit CC."""
from copy import deepcopy
from dataclasses import replace
import json
import sys

import pytest

from ams2season.coach.call_controls import CallControls, NATIVE, empty
from ams2season.coach.crew_core import Core
from ams2season.coach.crew_events import Events
from ams2season.coach.radio import Scheduler
from ams2season.coach.catalogue import CATALOGUE
from test_coach_radio import context, message, play
from test_coach_service import app_with_current, snapshot, snapshot_stream, wait_until


def controls(root):
    value = CallControls(root)
    core, events = Core(root=root), Events(root=root)
    value.activate(core, events)
    return value, core, events


@pytest.mark.parametrize('overrides', [
    {'native': {'enable_fuel_messages': 'true'}},
    {'native': {'frequency_of_gap_ahead_reports': True}},
    {'native': {'frequency_of_gap_ahead_reports': 11}},
    {'native': {'ambient_temp_check_interval_seconds': 0}},
    {'native': {'enable_running_dos_commands_from_command_macros': True}},
    {'families': {'fuel': {'enabled': 1}}},
    {'families': {'fuel': {'min_interval_s': float('nan')}}},
    {'families': {'fuel': {'min_interval_s': 3601}}},
    {'paddock': {'fake': {'enabled': False}}},
    {'paddock': {'V-25': {'enabled': False}}},
    {'other': {}},
])
def test_invalid_options_never_write_or_change_active_choices(tmp_path, overrides):
    value, core, _ = controls(tmp_path)
    before = dict(core.settings)
    with pytest.raises(ValueError):
        value.save({'revision': 0, 'overrides': overrides})
    assert core.settings == before and value.active == empty()
    assert not value.path.exists()


def test_persistence_revision_restore_and_imported_values_are_separate(tmp_path):
    value, core, events = controls(tmp_path)
    original = {k: core.settings[k] for k in NATIVE}
    value.save({'revision': 0, 'overrides': {'native': {'enable_fuel_messages': True},
                'families': {'fuel': {'enabled': False}}, 'paddock': {'C-10': {'min_interval_s': 240}}}})
    assert value.active == empty()  # saving never changes a constructed host
    assert {k: core.settings[k] for k in NATIVE} == original
    assert value.status(True, core, events, [])['pending']
    loaded = CallControls(tmp_path)
    assert loaded.saved == value.saved and loaded.revision == 1
    with pytest.raises(ValueError, match='Refresh'):
        loaded.save({'revision': 0, 'preset': 'inherit'})
    loaded.activate(core, events)
    assert core.settings['enable_fuel_messages'] == 'True'
    assert loaded.status(True, core, events, [])['pending'] is False
    loaded.save({'revision': 1, 'preset': 'inherit'})
    fresh = Core(root=tmp_path)
    loaded.activate(fresh, Events(root=tmp_path))
    assert {k: fresh.settings[k] for k in NATIVE} == original
    assert not (tmp_path/'crew_chief').exists()


def test_native_family_controls_keep_manual_and_critical_calls_distinct(tmp_path):
    value, core, events = controls(tmp_path)
    value.save({'revision': 0, 'overrides': {'families': {'fuel': {'enabled': False}}}})
    value.activate(core, events)
    auto = {'source_event': 'Fuel_4.19.5.4', 'sound_type': 'CRITICAL_MESSAGE', 'immediate': True}
    assert value.native_reason(auto, 'race', 100) == 'automatic_call_disabled'
    assert value.native_reason({**auto, 'sound_type': 'VOICE_COMMAND_RESPONSE'}, 'race', 100) is None
    assert value.native_reason({'source_event': 'AudioPlayer_4.19.5.4'}, 'race', 100) is None


def test_native_interval_begins_at_accepted_submission_and_resets_for_session(tmp_path):
    value, core, events = controls(tmp_path)
    value.save({'revision': 0, 'overrides': {'families': {'gaps': {'min_interval_s': 60}}}})
    value.activate(core, events)
    call = {'source_event': 'Timings_4.19.5.4', 'sound_type': 'REGULAR_MESSAGE'}
    assert value.native_reason(call, 'race', 100) is None
    assert value.native_reason(call, 'race', 101) is None
    value.native_submitted(call, 'race', 101)
    assert value.native_reason(call, 'race', 160) == 'automatic_call_interval'
    assert value.native_reason(call, 'race', 161) is None
    assert value.native_reason(call, 'race2', 102) is None


def test_muted_paddock_automatic_reports_keep_explicit_requested_answers():
    radio, ctx = Scheduler(), context(session='practice', pit=2, pit_radio=True)
    radio.call_controls = {'B-01': {'enabled': False}}
    m = replace(message(ctx), spec=CATALOGUE['B-01'], slots={'a': 'Copy.', 'b': 'Understood.', 'c': 'Okay.'})
    assert radio.offer(m, ctx) is False
    assert radio.log.events[-1]['reason'] == 'automatic_call_disabled'
    with radio.requested():
        assert radio.offer(m, ctx)
    assert play(radio, ctx).message.requested


def test_interval_applies_across_different_paddock_keys_and_preserves_requested_reply():
    radio, ctx = Scheduler(), context()
    radio.call_controls = {'X-15': {'min_interval_s': 60}}
    radio.offer(message(ctx), ctx)
    played = play(radio, ctx)
    # Submitting cannot invalidate the call while its audio is still rendering.
    assert radio.invalid_delivery(played, ctx) is None
    newer = replace(ctx, t=110)
    other = message(newer, id='two', key='pitting:other')
    assert not radio.offer(other, newer)
    assert radio.log.events[-1]['reason'] == 'automatic_call_interval'
    with radio.requested():
        assert radio.offer(other, newer)
    assert play(radio, newer).message.requested


def test_api_stages_changes_without_restarting_or_altering_program_and_recorder(tmp_path):
    app = app_with_current(tmp_path)
    raw = snapshot()
    try:
        with snapshot_stream(app, raw):
            app.coach.start()
            wait_until(lambda: app.coach.engine.context is not None)
            service = app.coach
            run, worker, program, core, recorder = (service.live_id, service.thread, service.engine.program,
                                                    service.core, app.recorder.rec)
            settings = dict(core.settings)
            result = app.route('POST', '/api/coach/calls', {}, {'revision': 0, 'overrides': {
                'native': {'enable_fuel_messages': True}, 'paddock': {'C-10': {'enabled': False}}}})
            assert result['call_controls']['pending']
            assert service.core is core and service.core.settings == settings
            assert service.live_id == run and service.thread is worker and service.engine.program is program
            assert app.recorder.rec is recorder and app.recorder.rec.hooks['coach'] == service.feed
            service.start()
            assert service.live_id == run and service.status()['call_controls']['pending']
            service.stop()
            service.start()
            assert service.core.settings['enable_fuel_messages'] == 'True'
            assert not service.status()['call_controls']['pending']
            assert service.engine.radio.call_controls['C-10']['enabled'] is False
    finally:
        app.coach.close()
    assert not list((tmp_path/'recordings').iterdir())
    assert app._crew_chief is None and not (tmp_path/'crew_chief').exists()


def test_corrupt_file_is_visible_without_replacing_it(tmp_path):
    path = tmp_path/'private_coach/call_preferences.json'
    path.parent.mkdir()
    path.write_text('{bad')
    value, core, events = controls(tmp_path)
    assert value.status(False, core, events, [])['error']
    assert path.read_text() == '{bad' and value.saved == empty()


def test_less_chatter_is_opt_in_and_does_not_disable_warning_families(tmp_path):
    value, core, events = controls(tmp_path)
    value.save({'revision': 0, 'preset': 'less_chatter'})
    assert value.saved['native'] == {}
    assert set(value.saved['families']) == {'gaps', 'position', 'weather'}
    assert all(s['enabled'] for s in value.saved['paddock'].values())
    assert 'V-25' not in value.saved['paddock']


@pytest.mark.skipif(sys.platform != 'win32', reason='Original Framework event host')
def test_original_fuel_and_weather_replies_survive_real_native_preference_overrides(tmp_path):
    from ams2season.coach.crew_mapper import DEFAULTS
    from test_crew_chief_fuel import warm, acknowledge
    value, core, events = controls(tmp_path)
    numbers = core.settings['__paddock_number_config']
    core.settings = dict(DEFAULTS, __paddock_number_config=numbers,
        __paddock_state_directory=str(tmp_path/'state'), __paddock_fuel_multiplier='1')
    value.save({'revision': 0, 'overrides': {'families': {'fuel': {'enabled': False},
        'weather': {'enabled': False}}, 'native': {'enable_fuel_messages': False,
        'enable_track_and_air_temp_reports': False}}})
    value.activate(core, events)
    core.fuel_available = core.weather_available = True
    core.start()
    try:
        assert core.ready.wait(10), core.error
        raw, _ = warm(core)
        for command, source in [('WHATS_MY_FUEL_LEVEL', 'Fuel_4.19.5.4'),
                                ('WHATS_THE_AIR_TEMP', 'ConditionsMonitor_4.19.5.4')]:
            from test_crew_chief_fuel import mapped
            mapped(core, raw, 4)
            calls = core.respond(command)
            assert calls and all(c['source_event'] == source for c in calls)
            assert all(c['sound_type'] == 'VOICE_COMMAND_RESPONSE' for c in calls)
            assert all(value.native_reason(c, 'race', 4) is None for c in calls)
            acknowledge(core, calls)
    finally:
        core.close()


def test_muted_native_request_is_acknowledged_dropped_and_not_left_in_original_queue(tmp_path):
    app = app_with_current(tmp_path)
    try:
        with snapshot_stream(app, snapshot()):
            app.coach.start()
            wait_until(lambda: app.coach.engine.context is not None)
            service = app.coach
            with service.lock:
                service.call_controls.active['families']['fuel'] = {'enabled': False}
                call = {'native_id': 'core:test-muted', 'id': 'core:test-muted', 'folder': 'fuel/one_lap_left',
                    'fragments': ['fuel/one_lap_left'], 'source_event': 'Fuel_4.19.5.4',
                    'sound_type': 'REGULAR_MESSAGE', 'expires_s': 10}
                service._queue_baseline([call])
                assert not service.baseline_pending
                assert {'id': 'test-muted', 'outcome': 'dropped'} in service.core.acknowledged
                assert service.engine.radio.log.events[-1]['reason'] == 'automatic_call_disabled'
    finally:
        app.coach.close()


def test_cached_caption_percentage_cannot_hide_extra_uncaptioned_wavs(tmp_path):
    from types import SimpleNamespace
    from test_crew_chief_voice_engine import folder
    from ams2season.coach.crew_voice import CrewChiefVoice
    from ams2season.coach.crew_spotter import CrewChiefSounds
    from ams2season.coach.voice import pcm_wav
    folder(tmp_path, 'lap_counter/won_race', ['You won.'])
    (tmp_path/'voice/lap_counter/won_race/extra.wav').write_bytes(pcm_wav(b'\0\0'*8820))
    cc = CrewChiefVoice(CrewChiefSounds(tmp_path))
    cc.prepare(SimpleNamespace(get=lambda text: SimpleNamespace(data=b'known')), ['lap_counter/won_race'])
    status = cc.status(iter(['lap_counter/won_race', 'lap_counter/won_race']))
    assert status['covered'] == status['variants'] == 1
    assert status['uncaptioned_files'] == 1
    assert status['uncaptioned_examples'] == ['lap_counter/won_race/extra.wav']


@pytest.mark.skipif(sys.platform != 'win32', reason='Original Framework penalty host')
def test_real_penalty_reply_is_requested_even_without_original_voice_response_enum(tmp_path):
    import time
    from types import SimpleNamespace
    from ams2season.app import App
    from test_crew_chief_penalties import tick
    app = App(tmp_path)
    service = app.coach
    ctx = context()
    service.audio_enabled, service.output = True, 'paddock'
    service.engine = SimpleNamespace(context=ctx, radio=Scheduler())
    service._local_valid = lambda sid: True  # Test request/mute boundary after telemetry validation.
    service.core.queue_status = {'keep_quiet': True}
    service.call_controls.active['families']['penalties'] = {'enabled': False, 'min_interval_s': 120}
    service.events.start()
    try:
        assert service.events.ready.wait(10), service.events.error
        raw = tick(0)
        service.events.feed(raw, raw.cars[0])
        result = service._engine_reply('do I have a penalty', 'typed')
        assert result['understood'] == 'DO_I_HAVE_A_PENALTY'
        assert service.baseline_pending
        reply = service.baseline_pending[0]
        assert reply['sound_type'] == 'REGULAR_MESSAGE' and reply['requested'] is True
        assert service._baseline_quiet_allowed(reply)
        assert service.call_controls.native_reason(reply, ctx.session_id, ctx.t) is None
        service.call_controls.native_submitted(reply, ctx.session_id, ctx.t)
        assert not service.call_controls.last_native
    finally:
        service.engine = None
        service.close()
