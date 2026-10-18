"""Calls without a recorded clip go to Crew Chief's text-to-speech, only when still valid."""
from dataclasses import replace
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ams2season.app import App
from ams2season.coach.engine import CoachEngine
from ams2season.coach.radio import RadioLog, Scheduler
from ams2season.coach.replay import run_replay
from ams2season.coach.voice import tts_estimate
from ams2season.crew_chief import CrewChief
from test_coach_radio import context, message
from test_coach_sections import END, LENGTH, frame as section_frame
from test_coach_replay import write_recording
from test_crew_chief import radio, configure  # noqa: F401  (fixture)


class FakeBridge:
    """Stands in for the Crew Chief connection: records what would be sent."""
    def __init__(self, *, connected=True, fail=None):
        self.sent, self.audio, self.connected, self.fail = [], [], connected, fail
        self.settings = {'audio_receipt': {'files': []}}

    def audio_transport_status(self):
        return {'configured': True, 'connected': self.connected}

    def submit_speech(self, text):
        if self.fail:
            raise ValueError(self.fail)
        self.sent.append(text)
        return 'speech-'+str(len(self.sent))

    def submit_audio(self, url):
        self.audio.append(url)
        return 'audio-'+str(len(self.audio))


def live_service(tmp_path, *, tts=True, bridge=None):
    app = App(tmp_path)
    app._crew_chief = bridge or FakeBridge()
    app.port = 8642
    service = app.coach
    service.audio_enabled, service.tts_fallback = True, tts
    service.thread = SimpleNamespace(is_alive=lambda: True)
    service.engine = CoachEngine('Player', Scheduler(log=RadioLog(tmp_path/'private_coach/radio.jsonl', deferred=True),
                                                     voice_duration=service._speech_duration))
    return app, service


def select(service, ctx):
    service.engine.context = ctx
    assert service.engine.radio.offer(message(ctx), ctx)
    selected = service.engine.radio.select(ctx)
    assert selected is not None
    return selected


def test_clipless_call_is_read_by_crew_chief_and_followed_in_its_sdk(tmp_path):
    app, service = live_service(tmp_path)
    ctx = context(window_s=8)
    selected = select(service, ctx)
    assert selected.seconds == pytest.approx(tts_estimate(selected.text))
    service._submit_audio(selected)
    assert app._crew_chief.sent == [selected.text] and not app._crew_chief.audio
    counts = service.engine.radio.log.counts
    assert counts['speech_queued'] == 1 and counts['submitted'] == 1 and service.engine.radio.delivering is None
    event = [e for e in service.engine.radio.log.events if e['state'] == 'speech_queued'][0]
    assert event['route'] == 'crew_chief_tts' and event['text'] == selected.text
    # Crew Chief's own subtitle shows our text while it plays, then the channel closes.
    service.audio.observe({'available': True, 'busy': True, 'phrase': selected.text}, service.engine.radio, ctx)
    service.audio.observe({'available': True, 'busy': False, 'phrase': selected.text}, service.engine.radio, ctx)
    states = [e['state'] for e in service.engine.radio.log.events]
    assert states[-2:] == ['radio_observed', 'radio_closed']
    assert all(e.get('heard') is False for e in service.engine.radio.log.events if e['state'].startswith('radio_'))
    service.thread = None
    service.close()


def test_text_to_speech_off_keeps_the_previous_silent_behaviour(tmp_path):
    app, service = live_service(tmp_path, tts=False)
    ctx = context(window_s=8)
    service.engine.context = ctx
    assert service.engine.radio.offer(message(ctx), ctx)
    assert service.engine.radio.select(ctx) is None  # no clip, so nothing is selectable
    assert any(e.get('reason') == 'voice_clip_missing' for e in service.engine.radio.log.events)
    assert not app._crew_chief.sent
    service.thread = None
    service.close()


@pytest.mark.parametrize('change,reason', [
    (lambda ctx: replace(ctx, radio_busy=None), 'not observed idle'),
    (lambda ctx: replace(ctx, facts={'ahead': 'a', 'pit:a': 0}), 'condition changed'),
    (lambda ctx: replace(ctx, brake=.8), 'driving workload'),
])
def test_text_is_rechecked_immediately_before_sending(tmp_path, change, reason):
    app, service = live_service(tmp_path)
    ctx = context(window_s=8)
    selected = select(service, ctx)
    service.engine.context = change(ctx)
    service._submit_audio(selected)
    assert not app._crew_chief.sent
    withheld = [e for e in service.engine.radio.log.events if e['state'] == 'speech_withheld']
    assert len(withheld) == 1 and reason in withheld[0]['reason']
    assert service.engine.radio.delivering is None
    service.thread = None
    service.close()


def test_a_bridge_failure_is_logged_and_releases_the_radio(tmp_path):
    app, service = live_service(tmp_path, bridge=FakeBridge(fail='Crew Chief is disconnected.'))
    ctx = context(window_s=8)
    selected = select(service, ctx)
    service._submit_audio(selected)
    assert service.engine.radio.delivering is None
    assert [e['reason'] for e in service.engine.radio.log.events if e['state'] == 'speech_withheld'] == ['Crew Chief is disconnected.']
    service.thread = None
    service.close()


def test_setting_persists_and_allows_speech_without_recordings(tmp_path):
    app = App(tmp_path)
    app._crew_chief = FakeBridge()
    status = app.coach.configure({'audio_enabled': True})
    assert status['audio_enabled'] and status['tts_fallback'] and status['readiness']['tts_fallback']
    saved = json.loads((tmp_path/'private_coach/settings.json').read_text())
    assert saved['tts_fallback'] is True and saved['audio_enabled'] is True
    with pytest.raises(ValueError, match='text-to-speech'):
        app.coach.configure({'tts_fallback': False})  # no recordings: speech would be silent
    assert json.loads((tmp_path/'private_coach/settings.json').read_text()) == saved
    status = app.coach.configure({'audio_enabled': False, 'tts_fallback': False})
    assert not status['tts_fallback']
    with pytest.raises(ValueError):
        app.coach.configure({'tts_fallback': 'yes'})
    reloaded = App(tmp_path)
    assert reloaded.coach.tts_fallback is False
    app.coach.close()
    reloaded.coach.close()


def test_duration_prefers_a_recording_and_estimates_text_to_speech_otherwise(tmp_path):
    app, service = live_service(tmp_path)
    service.voice.index['recorded phrase'] = {'seconds': 1.25}
    assert service._speech_duration('Recorded phrase.') == 1.25
    assert service._speech_duration('Five words are spoken here.') == pytest.approx(5/2.6+.4)
    service.tts_fallback = False
    assert service._speech_duration('Five words are spoken here.') is None
    service.thread = None
    service.close()


def test_bridge_sends_plain_text_to_the_regular_queue_only(radio):  # noqa: F811
    configure(radio)
    with pytest.raises(ValueError, match='cached audio'):
        radio.submit_speech('Biggest loss: the bend near five hundred metres, two tenths.')
    radio.settings['audio_receipt'] = {'files': []}
    radio.clients.add('client')
    lines = io.StringIO()
    radio.process = SimpleNamespace(poll=lambda: None, stdin=SimpleNamespace(write=lines.write, flush=lambda: None))
    request = radio.submit_speech('Biggest loss: the bend near five hundred metres, two tenths.')
    command = json.loads(lines.getvalue())
    assert command == {'type': 'speak', 'id': request, 'text': 'Biggest loss: the bend near five hundred metres, two tenths.'}
    for bad in ('', 'x'*257, 'http://example.com/a.wav', 'line\nbreak', 7):
        with pytest.raises(ValueError):
            radio.submit_speech(bad)
    radio.clients.clear()
    with pytest.raises(ValueError, match='disconnected'):
        radio.submit_speech('Gap behind two seconds.')
    radio.process = None


def test_host_keeps_coaching_text_in_the_regular_queue_behind_the_spotter():
    source = (Path(__file__).parents[1]/'ams2season/assets/crew_chief_host.cs').read_text()
    assert 'bool isSpeech = kind == "speak";' in source
    assert 'if (isSpeech && !allowAudio) continue;' in source
    assert 'immediate = kind == "say"' in source  # only the radio check is immediate


def test_replay_can_simulate_text_to_speech_for_phrases_without_recordings(tmp_path):
    recording = Path(tmp_path)/'recordings'/'synthetic-sections'
    meta = write_recording(recording, [section_frame(i*.1) for i in range(int(END*10)+1)])
    meta.update(session_type='practice', track_length=LENGTH)
    (recording/'session.json').write_text(json.dumps(meta))
    silent = run_replay(recording, tmp_path, voice_durations={})
    spoken = run_replay(recording, tmp_path, voice_durations={}, tts_fallback=True)
    assert silent['counts'].get('would_say', 0) == 0 and silent['speech_simulation'] == 'cached_voice'
    assert spoken['counts']['would_say'] == 1 and spoken['speech_simulation'] == 'cached_voice_with_tts'
    assert spoken['inputs_unchanged']
