"""Standalone engineer basics and Paddock's own radio (no Crew Chief)."""
import io
import json
import time
import wave

from ams2season.coach.car_status import FuelLeftWatch, LapWatch, TempWatch
from ams2season.coach.model import Car, Tick
from ams2season.coach.speech import LocalRadio, radio_call
from ams2season.coach.voice import pcm_wav

L = 2000.0


def car(laps, distance, pit=0, last_lap=None, car_class='GT3'):
    return Car(slot=0, name='Player', car='GT3', car_class=car_class, position=1, laps=laps, distance=distance,
               speed=50, pit=pit, race_state=2, invalid=False, last_lap=last_lap)


def tick(t, player, session='practice', **local):
    base = {'speed': 50, 'local_lap_invalid': False, 'compound': 'Slick'}
    base.update(local)
    return Tick(t=t, session_id='s', session=session, track='T', layout='L', length=L, game_state=2,
                viewed_slot=0, cars=(player,), local=base)


def drive(watch, laps, lap_s=40.0, *, times=None, invalid_lap=None, start_lap=0):
    """Feed laps at 10 Hz; the game's last-lap time updates 0.4 s after the line."""
    events, t, last = [], 0.0, None
    for lap in range(start_lap, start_lap + laps):
        n = int(lap_s * 10)
        for i in range(n):
            distance = L * i / n
            if i == 4 and lap > start_lap:
                last = (times or {}).get(lap - 1, lap_s)
            invalid = invalid_lap == lap and i > n // 2
            event = watch.feed(tick(t, car(lap, distance, last_lap=last), local_lap_invalid=invalid), car(lap, distance, last_lap=last))
            if event:
                events.append(event)
            t += .1
    return events


def test_lap_times_at_the_line_compare_with_the_best_and_skip_out_laps():
    watch = LapWatch()
    events = drive(watch, 5, times={1: 41.2, 2: 40.5, 3: 40.9})
    laps = [e for e in events if e['kind'] == 'lap']
    # lap 0 was joined mid-way (an out lap): no call; then every timed lap
    assert [round(e['time'], 1) for e in laps] == [41.2, 40.5, 40.9]
    assert laps[1]['best_before'] == 41.2 and laps[2]['best_before'] == 40.5 and watch.best == 40.5


def test_identical_lap_times_are_confirmed_by_the_line_to_line_time():
    watch = LapWatch()
    events = drive(watch, 4, times={1: 40.0, 2: 40.0})
    assert [e['time'] for e in events if e['kind'] == 'lap'] == [40.0, 40.0]


def test_a_lap_the_game_deletes_is_called_once_and_never_a_best():
    watch = LapWatch()
    events = drive(watch, 4, times={1: 41.0, 2: 39.0, 3: 42.0}, invalid_lap=2)
    deleted = [e for e in events if e['kind'] == 'deleted']
    laps = [e for e in events if e['kind'] == 'lap']
    assert len(deleted) == 1 and deleted[0]['lap'] == 3
    assert laps[1]['valid'] is False and laps[1]['deleted_said'] and watch.best == 41.0


def test_cold_tyres_and_brakes_leaving_the_pits_then_up_to_temperature():
    watch = TempWatch()
    events, t = [], 0.0
    for i in range(30):   # rolling out of the box
        p = car(0, 100 + i, pit=3)
        events += watch.feed(tick(t, p, speed=15, tyre_c=(30, 30, 30, 30), brake_c=(80, 80, 60, 60)), p)
        t += .1
    assert [e['kind'] for e in events] == ['pit_exit_cold'] and events[0]['tyres'] and events[0]['brakes']
    for i in range(400):
        p = car(0, 200 + i)
        temp = min(90, 30 + i)
        events += watch.feed(tick(t, p, speed=50, tyre_c=(temp,) * 4, brake_c=(400,) * 4), p)
        t += .1
    assert [e['kind'] for e in events] == ['pit_exit_cold', 'tyres_ready']


def test_hot_fronts_need_to_stay_hot_and_wet_tyres_are_left_alone():
    for compound, expected in (('Slick', ['tyres_hot']), ('Wet', [])):
        watch, events, t = TempWatch(), [], 0.0
        for i in range(300):
            p = car(1, 500 + i)
            events += watch.feed(tick(t, p, speed=50, compound=compound, tyre_c=(112, 112, 95, 95), brake_c=(500,) * 4), p)
            t += .1
        assert [e['kind'] for e in events] == expected
        if expected:
            assert events[0]['axle'] == 'front' and events[0]['tyre_c'] > 105


def test_hot_brakes_only_for_iron_brake_classes_on_two_laps():
    for car_class, expected in (('GT3', ['brakes_hot']), ('F-Ultimate', [])):
        watch, events, t = TempWatch(), [], 0.0
        for lap in range(4):
            for i in range(50):
                p = car(lap, 40 * i, car_class=car_class)
                events += watch.feed(tick(t, p, speed=50, tyre_c=(90,) * 4, brake_c=(900, 900, 500, 500)), p)
                t += .1
        assert [e['kind'] for e in events] == expected


def test_low_fuel_calls_count_down_once_each():
    watch = FuelLeftWatch()
    out = []
    for lap, litres in enumerate([20, 9.5, 7, 4.6, 2.2, 0.5]):
        out.append(watch.feed(None, car(lap, 10), {'fuel_litres': litres, 'litres_per_lap': 2.4}))
    assert [e and e['whole'] for e in out] == [None, None, 3, 2, 1, 0]


def clip(seconds=.5):
    return pcm_wav(b'\x10\x00' * int(22050 * seconds))


class Voice:
    def __init__(self, texts):
        self.texts = texts

    def duration(self, text):
        return .5 if text in self.texts else None

    def get(self, text):
        class C:
            data = clip()
        return C() if text in self.texts else None


def test_local_radio_plays_one_call_at_a_time_with_radio_clicks():
    played = []
    radio = LocalRadio(Voice({'Box this lap.'}), sink=(played.append, lambda: None))
    assert radio.can_say('Box this lap.') and not radio.can_say('Unknown line.')
    radio.say('a', 'Box this lap.')
    radio.say('b', 'Unknown line.')
    deadline = time.time() + 3
    while time.time() < deadline and len([e for e in radio.events if e['event'] in ('finished', 'failed')]) < 2:
        time.sleep(.02)
    events = radio.drain()
    assert [e['event'] for e in events] == ['playing', 'finished', 'failed']
    with wave.open(io.BytesIO(played[0])) as wav:
        assert wav.getnframes() / 22050 > .5      # the clicks and gaps around the clip
    assert not radio.busy
    radio.close()


def test_radio_call_respects_volume():
    loud, quiet = radio_call(clip(), 1.0), radio_call(clip(), .25)
    assert len(loud) == len(quiet) and loud != quiet


def test_standalone_speech_needs_no_crew_chief_setup_and_plays_through_paddock(tmp_path, monkeypatch):
    from test_coach_service import app_with_current, snapshot, wait_until
    from ams2season.coach import service as coach_service
    played = []

    class Radio(LocalRadio):
        def __init__(self, voice, **kwargs):
            kwargs['sink'] = (played.append, lambda: None)
            super().__init__(Voice({'Box this lap.'}), **kwargs)
    monkeypatch.setattr(coach_service, 'LocalRadio', Radio)
    app = app_with_current(tmp_path)
    status = app.route('POST', '/api/coach/settings', {}, {'output': 'paddock', 'audio_enabled': True, 'volume': .5})
    assert status['output'] == 'paddock' and status['audio_enabled'] and status['volume'] == .5
    assert not (tmp_path / 'crew_chief').exists()       # Crew Chief untouched
    app.route('POST', '/api/coach/start', {}, {})
    service = app.coach
    wait_until(lambda: service.local_radio is not None)
    assert service.standalone and service.local_radio.volume == .5
    app.route('POST', '/api/coach/stop', {}, {})
    assert service.local_radio is None
    service.close()


def make_pack(directory, clips, voice_id='paddock-test', name='Test voice'):
    import hashlib
    import json
    import zipfile
    entries, files = [], {}
    for i, (text, seconds) in enumerate(clips.items()):
        data = pcm_wav(b'\x20\x00' * int(22050 * seconds))
        path = f'clips/c{i}.wav'
        files[path] = data
        entries.append({'id': str(i), 'text': text, 'radio': path, 'radio_sha256': hashlib.sha256(data).hexdigest(),
                        'seconds': len(data[44:]) / 2 / 22050, 'fragment': True})
    pack = {'format': 'paddock-voice-pack', 'schema': 1, 'voice_id': voice_id, 'voice_name': name, 'version': '1.0.0',
            'rights': {'status': 'cleared', 'license': 'Apache-2.0', 'synthetic': True}, 'clips': entries}
    archive = directory / 'whole.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('pack.json', json.dumps(pack))
        for path, data in files.items():
            z.writestr(path, data)
    return archive.read_bytes()


def test_a_pack_placed_on_the_pc_in_parts_installs_and_builds_lines_from_pieces(tmp_path):
    from ams2season.coach.packs import PackStore
    from ams2season.coach.voice import VoiceCache
    clips = {'box this lap': .6, 'forty-six': .4, 'two': .2, 'fuel for about': .5, 'three laps': .45}
    data = make_pack(tmp_path, clips)
    store = PackStore(tmp_path)
    store.imports.mkdir(parents=True)
    third = len(data) // 3
    for n, chunk in enumerate((data[:third], data[third:2 * third], data[2 * third:]), 1):
        (store.imports / f'paddock-test.zip.{n:03d}').write_bytes(chunk)
    (store.imports / 'broken.zip.002').write_bytes(b'x')      # part 1 missing: not offered
    assert [e['name'] for e in store.importable()] == ['paddock-test']
    key, spec = store.import_local('paddock-test')
    voice = store.cache(key)
    assert isinstance(voice, VoiceCache) and voice.voice_id == 'paddock-test'
    line = voice.get('Forty-six two.')
    assert line is not None and abs(line.seconds - voice.duration('Forty-six two.')) < 1e-9
    assert voice.duration('Fuel for about three laps.') is not None
    assert voice.duration('Box this lap, fuel for about three laps.') is not None
    assert voice.duration('Fuel for about four laps.') is None     # a missing word: not this voice


class AnyVoice(Voice):
    def __init__(self):
        super().__init__(set())

    def duration(self, text):
        return .5

    def get(self, text):
        class C:
            data = clip()
        return C()


def test_a_spoken_call_is_played_and_logged_and_the_coach_keeps_running(tmp_path, monkeypatch):
    from test_coach_program import candidate
    from test_coach_program_service import practice
    from test_coach_service import app_with_current, wait_until
    from ams2season.coach import service as coach_service
    played = []

    class Radio(LocalRadio):
        def __init__(self, voice, **kwargs):
            kwargs['sink'] = (played.append, lambda: None)
            super().__init__(AnyVoice(), **kwargs)
    monkeypatch.setattr(coach_service, 'LocalRadio', Radio)
    monkeypatch.setattr(coach_service.CoachService, '_plan_lookup', lambda self, *args: [candidate()])
    monkeypatch.setattr(coach_service.CoachService, '_speech_duration', lambda self, text: .5)
    app = app_with_current(tmp_path)
    app.recorder.rec.step(practice(), time.perf_counter())
    app.route('POST', '/api/coach/settings', {}, {'output': 'paddock', 'audio_enabled': True})
    app.route('POST', '/api/coach/start', {}, {})
    end = time.perf_counter() + 4
    while time.perf_counter() < end and not any(e['state'] == 'radio_closed' for e in app.coach.status()['events']):
        app.recorder.rec.step(practice(), time.perf_counter())
        time.sleep(.03)
    status = app.coach.status()
    states = [e['state'] for e in status['events']]
    assert 'radio_playing' in states and 'radio_closed' in states and played
    assert status['running'] and not status['error'] and status['last_error'] is None
    app.coach.close()


class FakeReader:
    def __init__(self):
        self.buttons = 0

    def read(self):
        return {0: (0x0EB7, 0x0006, 'Wheel', self.buttons)}


def test_button_capture_then_presses_and_releases_reach_their_role():
    from ams2season.coach.buttons import ButtonWatch
    reader = FakeReader()
    watch = ButtonWatch(reader=reader)
    watch.start_capture('ptt')
    watch._step(reader.read())
    reader.buttons = 1 << 4                    # button 5 pressed
    watch._step(reader.read())
    captured = watch.drain()
    assert captured[0]['event'] == 'captured' and captured[0]['binding']['button'] == 5
    watch.bind({'ptt': captured[0]['binding'], 'debrief': {'mid': 0x0EB7, 'pid': 6, 'button': 7}})
    reader.buttons = 0
    watch._step(reader.read())
    reader.buttons = 1 << 4
    watch._step(reader.read())
    reader.buttons = (1 << 4) | (1 << 6)
    watch._step(reader.read())
    reader.buttons = 1 << 6
    watch._step(reader.read())
    assert [(e['event'], e['role']) for e in watch.drain()] == [('up', 'ptt'), ('down', 'ptt'), ('down', 'debrief'), ('up', 'ptt')]


def test_buttons_are_saved_and_a_heard_phrase_answers_the_engineer(tmp_path, monkeypatch):
    from test_coach_program import candidate
    from test_coach_program_service import practice, drive, events
    from test_coach_service import app_with_current, wait_until
    from ams2season.coach import service as coach_service
    reader = FakeReader()

    class Watch(coach_service.ButtonWatch):
        def __init__(self, bindings=None, **kwargs):
            super().__init__(bindings, reader=reader)

    class Listener:
        def __init__(self, phrases):
            self.phrases, self.error, self.queue = phrases, None, []
            self.ready=True

        def press(self):
            pass

        def release(self):
            self.queue.append(('this is practice two', .9))

        def heard(self):
            out, self.queue = self.queue, []
            return out

        def heard_details(self):
            return [{'text':text,'confidence':confidence,'detected_speech':bool(text),'problem':None}
                    for text,confidence in self.heard()]

        def close(self):
            pass
    monkeypatch.setattr(coach_service, 'ButtonWatch', Watch)
    monkeypatch.setattr(coach_service, 'WindowsListener', Listener)
    monkeypatch.setattr(coach_service.CoachService, '_plan_lookup', lambda self, *args: [candidate()])
    app = app_with_current(tmp_path)
    app.recorder.rec.step(practice(), time.perf_counter())
    app.route('POST', '/api/coach/buttons/capture', {}, {'role': 'ptt'})
    time.sleep(.1)
    reader.buttons = 1
    wait_until(lambda: app.coach.status()['talk']['bindings'].get('ptt'))
    reader.buttons = 0
    saved = json.loads((tmp_path / 'private_coach' / 'settings.json').read_text())
    assert saved['buttons']['ptt']['button'] == 1
    app.route('POST', '/api/coach/start', {}, {})
    drive(app, .3)
    reader.buttons = 1
    drive(app, .2)
    reader.buttons = 0
    wait_until(lambda: (app.coach.status()['live']['program'] or {}).get('goal') == 'practice2')
    assert app.coach.status()['talk']['last_heard']['understood']
    assert [e for e in events(app, 'driver_reply') if e['source'] == 'voice']
    app.route('POST', '/api/coach/buttons/clear', {}, {'role': 'ptt'})
    assert 'ptt' not in app.coach.status()['talk']['bindings']
    app.coach.close()


def test_recon_calls_each_corner_ahead_once_and_joins_close_ones():
    from ams2season.coach.car_status import ReconGuide
    from ams2season.coach.intents import parse
    assert parse('Can you do a recon lap?').kind == 'recon' and parse('recon').kind == 'recon'
    assert parse('talk me through the corners').kind == 'recon'
    guide = ReconGuide()
    assert not guide.start([])
    assert guide.start([(300, 'turn one'), (900, 'turn two'), (980, 'turn three'), (1600, 'turn four')])
    calls, t = [], 0.0
    for lap in range(2):
        for i in range(400):
            p = car(lap, 1500 + i * 5 if lap == 0 else i * 5)
            p = car(lap, (p.distance) % L)
            event = guide.feed(tick(t, p, speed=40), p)
            t += .1
            if event:
                calls.append((event['labels'], event['last']))
    assert calls == [(['turn four'], False), (['turn one'], False), (['turn two', 'turn three'], False)] or \
        calls[-1][1] is True
    assert [l for c in calls for l in c[0]] == ['turn four', 'turn one', 'turn two', 'turn three'] and calls[-1][1]
    assert not guide.active


def test_recon_from_the_engineer_corner_list_is_spoken_through_the_radio():
    from ams2season.coach.engine import CoachEngine
    from ams2season.coach.radio import Scheduler
    engine = CoachEngine('Player', Scheduler(), corner_list=lambda: [{'apex': 300.0}, {'apex': 1200.0}])
    t = 0.0
    for i in range(20):
        p = car(1, 100 + i)
        engine.feed(tick(t, p, speed=40, throttle=1, brake=0, steering=0, rain_density=0, crash_state=0, gear=3), radio_busy=False)
        t += .1
    assert engine.start_recon().startswith('Recon lap: 2 corners')
    texts = []
    for i in range(300):
        p = car(1, 120 + i * 4)
        delivery = engine.feed(tick(t, p, speed=40, throttle=1, brake=0, steering=0, rain_density=0, crash_state=0, gear=3), radio_busy=False)
        if delivery:
            texts.append(delivery.text)
            engine.radio.acknowledge(delivery, engine.context, accepted=True, simulated=True)
        t += .1
    assert texts[0].startswith(('Recon lap', 'Copy, recon')) and 'Turn one.' in texts and any(x.startswith('Turn two.') for x in texts)


def test_exit_and_restart_requests_and_the_update_notice(tmp_path):
    from ams2season.app import App
    app = App(tmp_path)
    version = app.route('GET', '/api/app/version', {}, {})
    assert version['update_waiting'] is False and version['running'] == version['installed']
    app.started_stamp -= 1                      # as if files changed after start
    assert app.route('GET', '/api/app/version', {}, {})['update_waiting'] is True
    assert app.route('POST', '/api/app/quit', {}, {'restart': True})['action'] == 'restart' and app.quit_requested == 'restart'
    assert app.route('POST', '/api/app/quit', {}, {})['action'] == 'exit'


def test_spotter_requires_actual_heading_instead_of_guessing_from_motion():
    from ams2season.coach.spotter import Spotter
    requested = []
    spotter = Spotter(host=lambda request: requested.append(request) or {'calls': []})
    p = car(1, 500)
    # Old recordings have world positions but no local orientation/velocity. They
    # cannot validate the original CC algorithm's AMS2 input transform.
    assert spotter.feed(tick(0, p), p) == []
    assert requested == []


def test_damage_is_reported_once_it_settles_and_engine_heat_needs_to_last():
    from ams2season.coach.car_status import HealthWatch
    watch, events, t = HealthWatch(), [], 0.0
    def dmg(aero=0., susp=0.):
        return {'aero': aero, 'engine': 0., 'suspension': [susp, 0., 0., 0.], 'brakes': [0.] * 4}
    for i in range(80):
        aero = 0. if i < 20 else .1 if i < 22 else .22
        p = car(1, 500 + i)
        events += watch.feed(tick(t, p, speed=40, damage=dmg(aero, .3 if i >= 21 else 0.), water_c=90, oil_c=100), p)
        t += .1
    assert len(events) == 1 and events[0]['kind'] == 'damage'
    parts = {(c['part'], c.get('wheel'), c['level']) for c in events[0]['changes']}
    assert parts == {('aero', None, 'significant'), ('suspension', 'front left', 'significant')}
    hot = []
    for i in range(200):          # 5 s hot, a dip, then 13.9 s hot: only the long stretch counts
        p = car(1, 600 + i)
        hot += watch.feed(tick(t, p, speed=40, damage=dmg(.22, .3), water_c=111 if i < 50 or i > 60 else 100, oil_c=100), p)
        t += .1
    assert [e['kind'] for e in hot] == ['engine_hot'] and hot[0]['what'] == 'water'
