"""Private coach lifecycle. The recorder hook copies a snapshot and returns.

Disk I/O, rules and replays run on separate workers. Preview mode makes no sound
and never connects to Crew Chief or changes its preferences.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import queue
import re
import threading
import time
import uuid

from .engine import CoachEngine
from .radio import Policy, RadioLog, Scheduler
from .call_controls import CallControls
from .replay import run_replay
from .telemetry import from_snapshot
from .audio import AudioTickets, SILENCE, TICKET_PATH
from .voice import VoiceCache, tts_estimate
from .packs import PackStore
from .crew_sdk import CrewChiefObserver
from .speech import EFFECTS as RADIO_EFFECTS, LocalRadio, WindowsListener, WindowsSpeech
from .buttons import ROLES as BUTTON_ROLES, ButtonWatch, binding as button_binding
from .crew_spotter import Spotter, WORDS
from .crew_voice import CrewChiefVoice
from .crew_engine import FOLDERS as ENGINE_FOLDERS, COMMANDS as ENGINE_COMMANDS, command_for
from .crew_events import Events, FOLDERS as PENALTY_FOLDERS, FLAG_FOLDERS, COMMANDS as PENALTY_COMMANDS, command_for as penalty_command
from .crew_core import Core, FOLDERS as CONDITIONS_FOLDERS, COMMANDS as CONDITIONS_COMMANDS, RADIO_COMMANDS, RADIO_FOLDERS, command_for as conditions_command
from .crew_damage import COMMANDS as DAMAGE_COMMANDS, FOLDERS as DAMAGE_FOLDERS, I_AM_OK, clearly_ok, command_for as damage_command
from .crew_fuel import COMMANDS as FUEL_COMMANDS,TIME_COMMANDS,FOLDERS as FUEL_FOLDERS,command_for as fuel_command,request_text as fuel_text,listener_phrases as fuel_listener_phrases
from .crew_pits import COMMANDS as PIT_COMMANDS,FOLDERS as PIT_FOLDERS,command_for as pit_command
from .crew_position import COMMANDS as POSITION_COMMANDS,FOLDERS as POSITION_FOLDERS,command_for as position_command
from .crew_lapcounter import FOLDERS as LAPCOUNTER_FOLDERS
from .crew_finish import FOLDERS as FINISH_FOLDERS
from .crew_timings import COMMANDS as TIMING_COMMANDS,FOLDERS as TIMING_FOLDERS,command_for as timing_command
from .crew_tyres import FOLDERS as TYRE_FOLDERS,command_for as tyre_command,listener_phrases as tyre_listener_phrases
from .crew_laptimes import COMMANDS as LAPTIME_COMMANDS,FOLDERS as LAPTIME_FOLDERS,command_for as laptime_command
from .windows import WindowStore
from .apex import ApexMapStore
from .numbers import Numbers, Units
from .program import PracticeProgram
from .intents import parse as parse_reply
from .names import RadioNames
from .. import shm as S

ENGINEER_OWNER = 'practice-coach'
# Where calls are spoken: Paddock's own radio (standalone) or Crew Chief's.
OUTPUTS = ('paddock', 'crew_chief')


class CoachService:
    def __init__(self, app):
        self.app = app
        self.root = app.lib.root
        self.lock = threading.RLock()
        self.thread = None
        self.stop_event = threading.Event()
        self.inbox = queue.Queue(maxsize=4)
        self.engine = None
        self.live_error = None
        self.live_id = None
        self.dropped_snapshots = 0
        self.origin = 0
        self.replay_thread = None
        self.replay_stop = threading.Event()
        self.replay_state = {"state": "idle"}
        self.mode = "full"
        self.audio_enabled = False
        # A call with no voice clip is read by text-to-speech (Windows' own when standalone,
        # Crew Chief's otherwise).
        self.tts_fallback = True
        self.output = 'crew_chief'
        self.volume = 1.0
        self.radio_effect = 'full'
        self.spotter_enabled = False
        self.fuel_multiplier=1
        self.spotter = Spotter(root=self.root)
        self.events = Events(root=self.root)
        self.core = Core(root=self.root)
        self.baseline_pending = []
        self.baseline_inflight = {}
        self.baseline_voice = 'paddock'
        self.names = RadioNames(self.root)
        self.spoken_names = {}
        self.windows_voice = None
        self.local_radio = None
        self.speech = None
        self.last_error = None
        self.error_since = None
        self.error_count = 0
        # Talking to the engineer: wheel buttons (push-to-talk and direct answers).
        self.button_bindings = {}
        self.buttons = None
        self.listener = None
        self.talk = {'state': 'idle', 'capturing': None, 'last_heard': None, 'note': None}
        self.units = Units()
        self.voice = VoiceCache(self.root)
        self.pack_store = PackStore(self.root)
        self.voice_selection = 'jim-private'
        self.voice_pack_warnings = []
        self.pack_thread = None
        self.pack_cancel = threading.Event()
        self.pack_state = {'state': 'idle'}
        self.closed = False
        self.pack_catalogue = ()
        self.pack_catalogue_error = None
        try:
            self.pack_catalogue = tuple(p for p in self.pack_store.catalogue()
                                        if p.distribution_approved and p.url)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.pack_catalogue_error = 'Voice download catalogue unavailable: ' + str(exc)
        self.observer = CrewChiefObserver()
        self.audio = AudioTickets()
        self.engineer_results = queue.Queue(maxsize=8)
        self._last_reply_poll = 0
        self._engineer_session = None   # the practice session the coach started the setup engineer for
        self.program_error = None
        path = self.root / "private_coach" / "settings.json"
        if path.is_file():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.mode = Policy(mode=saved.get("mode", "full")).mode
                self.audio_enabled = saved.get('audio_enabled') is True
                self.tts_fallback = saved.get('tts_fallback', True) is True
                self.output = saved.get('output') if saved.get('output') in OUTPUTS else 'crew_chief'
                volume = saved.get('volume', 1.0)
                self.volume = float(volume) if isinstance(volume, (int, float)) and 0 <= volume <= 1 else 1.0
                self.radio_effect = saved.get('radio_effect') if saved.get('radio_effect') in RADIO_EFFECTS else 'full'
                self.spotter_enabled = saved.get('spotter') is True
                self.baseline_voice = saved.get('baseline_voice') if saved.get('baseline_voice') in ('paddock','original') else 'paddock'
                multiplier=saved.get('fuel_multiplier',1)
                if type(multiplier) is int and 0<=multiplier<=10:self.fuel_multiplier=multiplier
                voice = saved.get('windows_voice')
                self.windows_voice = voice if isinstance(voice, str) and 0 < len(voice) <= 100 else None
                buttons = saved.get('buttons') if isinstance(saved.get('buttons'), dict) else {}
                self.button_bindings = {r: button_binding(b) for r, b in buttons.items()
                                        if r in BUTTON_ROLES and button_binding(b)}
                self.units = self.units.update(saved.get('units',{}))
                self.voice_selection = saved.get('voice_pack','jim-private')
            except (ValueError, TypeError):
                pass
        if self.voice_selection!='jim-private':
            try:
                self.voice = self.pack_store.cache(self.voice_selection)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                # Never substitute Jim when a selected identity is unavailable.
                self.voice = VoiceCache(self.root,voice_id='unavailable')
                self.voice.index.clear()
                self.voice.errors.append('Selected engineer voice is unavailable: '+str(exc))
        self.cc_voice = CrewChiefVoice(self.spotter.sounds,settings=self.events.settings)
        self.call_controls = CallControls(self.root)
        self.call_controls.activate(self.core, self.events)
        self.core.settings['__paddock_fuel_multiplier']=str(self.fuel_multiplier)
        self.cc_voice.prepare(self.voice, self._cc_folders())

    def _cc_folders(self):
        prefix = 'spotter'
        selected = self.spotter.settings.get('spotter_name','Jim (default)')
        if selected != 'Jim (default)' and (self.spotter.sounds.root/'voice'/('spotter_'+selected)).is_dir():
            prefix = 'spotter_'+selected
        return tuple(prefix+'/'+key for key in WORDS) + ENGINE_FOLDERS + CONDITIONS_FOLDERS + PENALTY_FOLDERS + FLAG_FOLDERS + RADIO_FOLDERS + DAMAGE_FOLDERS + FUEL_FOLDERS + PIT_FOLDERS + POSITION_FOLDERS + LAPCOUNTER_FOLDERS + TIMING_FOLDERS + TYRE_FOLDERS + LAPTIME_FOLDERS + FINISH_FOLDERS

    def _speech_duration(self, text):
        """A recorded or composed clip's measured length, else a text-to-speech estimate when
        allowed (standalone: only while Windows speech works)."""
        seconds = self.voice.duration(text)
        if seconds is None and self.tts_fallback:
            if self.output == 'paddock' and self.speech is not None and not self.speech.available:
                return None
            seconds = tts_estimate(text)
        return seconds

    @property
    def standalone(self):
        return self.audio_enabled and self.output == 'paddock'

    def _open_local_radio(self):
        if self.local_radio is None:
            if self.cc_voice.native is None and not self.cc_voice.native_error:
                self.cc_voice.open_native(self.root,personalisation=self.names.data['personal'],
                                          folders=self._cc_folders(),voice=self.voice)
            self.cc_voice.prepare(self.voice, self._cc_folders())
            self.speech = WindowsSpeech(self.windows_voice) if self.tts_fallback else None
            self.local_radio = LocalRadio(self.voice, speech=self.speech, volume=self.volume, effect=self.radio_effect)

    def _close_local_radio(self):
        radio, self.local_radio, self.speech = self.local_radio, None, None
        if radio is not None:
            radio.close()
        self.baseline_inflight.clear()

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    @property
    def pack_busy(self):
        return self.pack_state['state'] in ('downloading', 'verifying', 'activating', 'cancelling')

    def feed(self, snap, now):
        if self.stop_event.is_set():
            return
        copied = S.SharedMemory.from_buffer_copy(snap)
        try:
            self.inbox.put_nowait((copied, now))
        except queue.Full:
            try:
                self.inbox.get_nowait()
            except queue.Empty:
                pass
            self.dropped_snapshots += 1
            try:
                self.inbox.put_nowait((copied, now))
            except queue.Full:
                pass

    def _skip_stale_snapshots(self,snap,sampled_at):
        # A busy worker can leave older frames queued beside a fresh one. Use
        # available fresh evidence instead of resetting the original mapper on
        # an already superseded stale frame. Genuine gaps still invalidate it.
        while time.perf_counter()-sampled_at>.25:
            try:
                snap,sampled_at=self.inbox.get_nowait()
            except queue.Empty:
                break
            self.dropped_snapshots+=1
        return snap,sampled_at

    def start(self, driver=None):
        with self.lock:
            if self.closed:
                raise ValueError('The coach is shutting down.')
            if self.pack_busy:
                raise ValueError('Wait for the voice change to finish or cancel it before starting the coach.')
            if self.running:
                return self.status()
            current = self.app.recorder.status().get("current")
            if not current:
                raise ValueError("Start the recorder and load your car in AMS2 before starting the coach preview.")
            driver = str(driver or current.get("driver") or "").strip()
            if not driver or driver != current.get("driver"):
                raise ValueError("Choose the exact in-game name of the driver currently in your car.")
            self.live_id = uuid.uuid4().hex
            log = RadioLog(self.root / "private_coach" / "live" / self.live_id / "radio.jsonl", deferred=True)
            from ..engineer.catalog import BY_KEY
            program = PracticeProgram(Numbers(self.units), plan_lookup=self._plan_lookup,
                                      engineer_state=self._engineer_state, settings=BY_KEY)
            program.personal_name = self.names.data['personal']
            program.replies_enabled = self._replies_configured() or self._wheel_replies()
            self.engine = CoachEngine(driver, Scheduler(Policy(mode=self.mode), log,
                voice_duration=self._speech_duration if self.audio_enabled else None),
                window_store=WindowStore(self.root), numbers=Numbers(self.units),apex_store=ApexMapStore(self.root),
                program=program, tyre_window=self._tyre_window, corner_list=self._engineer_corners,
                name_for=lambda car: self.spoken_names.get(car.name, car.name))
            self.engine.personal_name = self.names.data['personal']
            self.engineer_results = queue.Queue(maxsize=8)
            self._engineer_session = None
            self.program_error = None
            self.audio = AudioTickets()
            self._close_local_radio()
            self.spotter.close()
            self.spotter = Spotter(root=self.root)
            self.events.close()
            self.events = Events(root=self.root)
            self.core.close()
            self.core = Core(root=self.root)
            self.call_controls.activate(self.core, self.events)
            self.engine.radio.call_controls = self.call_controls.active['paddock']
            self.core.settings['__paddock_fuel_multiplier'] = str(self.fuel_multiplier)
            if self.cc_voice.settings != self.events.settings:
                self.cc_voice.close()
                self.cc_voice=CrewChiefVoice(self.spotter.sounds,settings=self.events.settings)
            self.baseline_pending.clear()
            if self.standalone:
                self.cc_voice.open_native(self.root,personalisation=self.names.data['personal'],
                                          folders=self._cc_folders(),voice=self.voice)
                if self.cc_voice.native:
                    self.core.settings['__paddock_personalised_folders']=json.dumps(sorted(self.cc_voice.native.personalised_folders))
                self._open_local_radio()
                self.events.start()
                self.core.start()
                if self.spotter_enabled:
                    self.spotter.start()
            if self.button_bindings:
                self._ensure_buttons()
            if 'ptt' in self.button_bindings:
                self._ensure_listener()
            self.live_error = None
            self.origin = time.perf_counter()
            self.inbox = queue.Queue(maxsize=4)
            self.dropped_snapshots = 0
            self.stop_event = threading.Event()
            self.thread = threading.Thread(target=self._run, name="private-race-coach", daemon=True)
            self.thread.start()
            self.app.recorder.coach = self
            self.app.recorder.rec.hooks["coach"] = self.feed
            return self.status()

    def _run(self):
        previous_key = None
        session_serial = 0
        latest_at = None
        last_sdk_poll = 0
        while not self.stop_event.is_set():
            try:
                snap, sampled_at = self.inbox.get(timeout=.2)
            except queue.Empty:
                with self.lock:
                    engine = self.engine
                    if (engine and engine.context and engine.context.active and latest_at is not None
                            and time.perf_counter() - latest_at > .5):
                        ctx = replace(engine.context, t=time.perf_counter()-self.origin,
                                      active=False, reason="disconnected")
                        engine.context = ctx
                        engine.radio.advance(ctx)
                        if self.local_radio:
                            self.local_radio.cancel_all()
                        self.spotter.reset()
                        self.events.reset()
                        self.core.invalidate('disconnected')
                        self.baseline_pending.clear()
                        self.audio.cancel(engine.radio, ctx, "disconnected")
                        engine.pits.states.clear()
                        if engine.windows:
                            engine.windows.clear_current()
                self._flush_log()
                continue
            try:
                with self.lock:
                    snap,sampled_at=self._skip_stale_snapshots(snap,sampled_at)
                    key = (S.cstr(snap.mTrackLocation), S.cstr(snap.mTrackVariation), int(snap.mSessionState),
                           S.cstr(snap.mCarName))
                    new_session = key != previous_key or snap.mGameState == S.GAME_INGAME_RESTARTING
                    if new_session:
                        session_serial += 1
                        previous_key = key
                    tick = from_snapshot(snap, sampled_at-self.origin, f"{self.live_id}:{session_serial}")
                    if time.perf_counter()-sampled_at > .5:
                        tick = replace(tick, fresh=False)
                    if self.standalone and self.engine.context is not None:
                        self._local_events()
                    if self.audio_enabled or time.monotonic()-last_sdk_poll > .25:
                        sdk = self.observer.poll()
                        last_sdk_poll = time.monotonic()
                    else:
                        sdk = self.observer.value
                    # Text preview assumes idle. Actual audio requires a fresh SDK
                    # heartbeat and uses verified cached durations, never live TTS.
                    if self.standalone:
                        # Our own radio, and Crew Chief's (its spotter) when it is running.
                        connected = self.local_radio is not None
                        radio_busy = bool(self.local_radio and self.local_radio.busy) or (
                            sdk.get('available') is True and sdk.get('busy') is True)
                    else:
                        transport = self.app.crew_chief.audio_transport_status() if self.audio_enabled else {}
                        connected = bool(transport.get('connected') and transport.get('configured'))
                        radio_busy = sdk.get('busy') if connected else None
                    recording = getattr(self.app.recorder.rec, 'active', None)
                    self.spoken_names = self.names.live_mapping(tick, self.engine.driver,
                        race_id=recording.path.name if recording is not None else None)
                    self.engine.personal_name = self.names.data['personal']
                    self.engine.program.personal_name = self.names.data['personal']
                    self.engine.radio.policy.mode='silent' if self.standalone and self.core.queue_status.get('keep_quiet') else self.mode
                    self.engine.original_engine_monitor = self.standalone and self.core.ready.is_set()
                    self.engine.original_penalties = self.standalone and self.events.ready.is_set()
                    self.engine.original_fuel_monitor=self.standalone and self.core.ready.is_set()
                    self.engine.original_damage_reporting=self.standalone and self.core.ready.is_set()
                    self.engine.original_lap_times=self.standalone and self.core.ready.is_set()
                    self.engine.original_tyre_monitor=self.standalone and self.core.ready.is_set()
                    delivery = self.engine.feed(tick, radio_busy=radio_busy if self.audio_enabled else False)
                    ctx = self.engine.context
                    ctx.facts['game_state']=tick.game_state
                    if new_session or not (ctx.active or ctx.pit_radio or self._original_prestart_valid(ctx.session_id)
                                           or self._original_finish_valid(ctx.session_id)):
                        self.baseline_pending.clear()
                        if self.local_radio:
                            self.local_radio.cancel_all()
                    if self.standalone:
                        self.core.waiting_for_speech=self.talk.get('state') in ('listening','thinking')
                        self.core.voice_enabled=bool(self.listener and self.listener.ready and not self.listener.error)
                        self._queue_baseline(self.events.feed(tick,tick.player(self.engine.driver)))
                        self._queue_baseline(self.core.feed_snapshot(snap,tick,tick.player(self.engine.driver),sampled_at,
                            fahrenheit=self.units.temperature=='f',fuel_gallons=self.units.fuel=='us_gallons',respect_update_interval=True))
                    if self.standalone and self.spotter_enabled and self.local_radio is not None:
                        for call in self.spotter.feed(tick, tick.player(self.engine.driver), busy=radio_busy):
                            folder = call['folder']
                            try:
                                text, data, source = self.cc_voice.choose(folder, selected=self.baseline_voice=='paddock',t=ctx.t)
                                session_id = ctx.session_id
                                self.local_radio.spot(text, data=data, source=source,
                                    valid=lambda sid=session_id, sound=folder: self._local_valid(sid, spotter=True)
                                        and self.spotter.valid_call(sound),
                                    deadline=time.monotonic() + call['expires_ms'] / 1000 -
                                        max(0, time.perf_counter() - self.origin - tick.t))
                            except (OSError, ValueError) as exc:
                                self.spotter.error = str(exc)
                    if new_session:
                        self.engine.radio.log.record('coach_session_started',self.engine.context,
                            text='Following '+self.engine.driver+' in '+tick.session+'.',
                            audio_enabled=self.audio_enabled,mode=self.mode,
                            voice=self.voice.status(),track=tick.track,layout=tick.layout)
                    self._service_program()
                    self._service_buttons()
                    if self.standalone:
                        self._local_events()
                    else:
                        self.audio.sweep(self.engine.radio, self.engine.context)
                        self.audio.observe(sdk, self.engine.radio, self.engine.context)
                        if not connected and self.audio_enabled:
                            self.audio.cancel(self.engine.radio, self.engine.context, 'radio_disconnected')
                    baseline_spoke = self._deliver_baseline() if self.standalone else False
                    if delivery and baseline_spoke:
                        self.engine.radio.acknowledge(delivery, self.engine.context, accepted=False)
                    elif delivery:
                        if self.standalone:
                            self._submit_local(delivery)
                        elif self.audio_enabled:
                            self._submit_audio(delivery)
                        else:
                            self.engine.radio.acknowledge(delivery, self.engine.context, accepted=True, simulated=True)
                    latest_at = sampled_at
                self._flush_log()
            except Exception as exc:
                # A fault in one tick is logged and the coach carries on; only a fault that keeps
                # happening for several seconds stops it (and says why).
                now = time.perf_counter()
                with self.lock:
                    self.last_error = f'{type(exc).__name__}: {exc}'[:400]
                    self.error_since = self.error_since or now
                    self.error_count += 1
                    if self.engine and self.engine.context:
                        try:
                            radio = self.engine.radio
                            if radio.delivering is not None:      # a call selected but not handed over
                                radio.acknowledge(radio.delivering, self.engine.context, accepted=False)
                            if self.error_count <= 20:
                                radio.log.record('coach_error', self.engine.context, reason=self.last_error)
                        except Exception:
                            pass
                    if now - self.error_since > 5:
                        self.live_error = self.last_error
                        if self.engine and self.engine.context:
                            self.engine.context = replace(self.engine.context, active=False, reason="coach_error")
                            self.engine.radio.advance(self.engine.context)
                        self.stop_event.set()
                continue
            self.error_since = None

    # ------------------------------------------------------------------ practice programme
    def _queue_baseline(self, calls, *, requested=False):
        ctx = self.engine.context
        for call in calls:
            if requested:
                call = {**call, 'requested': True}
            reason = self.call_controls.native_reason(call, ctx.session_id, ctx.t)
            if reason:
                if 'native_id' in call:
                    self._ack_baseline(call['native_id'], 'dropped')
                self.engine.radio.log.record('crew_chief_withheld', ctx, reason=reason,
                                             text=call['folder'], source=call.get('source_event'))
                continue
            expiry = ctx.t+call['expires_s'] if call['expires_s'] else None
            for old in self.baseline_pending:
                if old['folder']==call['folder'] and 'native_id' in old:
                    self._ack_baseline(old['native_id'],'dropped')
            self.baseline_pending = [p for p in self.baseline_pending if p['folder'] != call['folder']]
            self.baseline_pending.append({**call,'expires':expiry,'available_at':ctx.t+call.get('delay_s',0),
                                          'session_id':ctx.session_id})
            self.engine.radio.log.record('crew_chief_requested', ctx, text=call['folder'],
                                        source=call.get('source_event','EngineMonitor_4.19.5.4'),fragments=call['fragments'])

    def _baseline_owner(self, native_id):
        return self.core if str(native_id).startswith('core:') else self.events

    def _ack_baseline(self,native_id,outcome):
        owner=self._baseline_owner(native_id)
        if owner is self.core:owner.acknowledge(native_id,outcome)
        elif outcome!='playing':owner.acknowledge(native_id)

    def _baseline_quiet_allowed(self,call):
        if call.get('requested') is True:
            return True
        if not self.core.queue_status.get('keep_quiet') or call.get('play_even_when_silenced'):
            return True
        if str(self.core.settings.get('allow_important_messages_even_when_silenced','False')).casefold()=='true':
            return bool(call['immediate'])
        kind=call.get('sound_type','AUTO')
        if kind=='AUTO':kind='VOICE_COMMAND_RESPONSE' if call['immediate'] else 'REGULAR_MESSAGE'
        return kind in ('SPOTTER','VOICE_COMMAND_RESPONSE')

    def _deliver_baseline(self):
        ctx = self.engine.context
        allowed = []
        for call in self.baseline_pending:
            reason = self.call_controls.native_reason(call, ctx.session_id, ctx.t)
            if reason:
                if 'native_id' in call:
                    self._ack_baseline(call['native_id'], 'dropped')
                self.engine.radio.log.record('crew_chief_withheld', ctx, reason=reason,
                                             text=call['folder'], source=call.get('source_event'))
            else:
                allowed.append(call)
        self.baseline_pending = allowed
        for call in self.baseline_pending:
            if not self._baseline_quiet_allowed(call) and 'native_id' in call:
                self._ack_baseline(call['native_id'],'dropped')
        self.baseline_pending = [c for c in self.baseline_pending
            if (c['expires'] is None or c['expires']>ctx.t) and c['session_id']==ctx.session_id
            and self._baseline_quiet_allowed(c)
            and ('native_id' not in c or self._baseline_owner(c['native_id']).valid_call(c['native_id']))]
        ready=[c for c in self.baseline_pending if c['available_at']<=ctx.t]
        managed=[c for c in ready if c.get('queue_managed') and self.core.order(c['native_id']) is not None]
        ready=[c for c in ready if not c.get('queue_managed')]
        if managed:ready.append(min(managed,key=lambda c:self.core.order(c['native_id'])))
        if not ready or not self.local_radio:
            return False
        external=self.observer.value
        if external.get('available') is True and external.get('busy') is True:
            return False
        call = max(ready, key=lambda c:(c['immediate'],c['priority']))
        preempt=bool(call['immediate'])
        if call.get('queue_managed'):
            current=self.baseline_inflight.get(self.local_radio.current,{})
            kind=current.get('sound_type','REGULAR_MESSAGE') if self.local_radio.current else 'OTHER'
            preempt=bool(call.get('interrupts_regular') and kind=='REGULAR_MESSAGE')
        if self.local_radio.busy and (not preempt or self.local_radio.current=='spot'):return False
        self.baseline_pending.remove(call)
        if not self._baseline_local_valid(ctx.session_id,call):
            if 'native_id' in call:self._ack_baseline(call['native_id'],'dropped')
            return False
        try:
            text, data, source = self.cc_voice.render(call, self.voice, selected=self.baseline_voice=='paddock',t=ctx.t)
            native_id=call.get('native_id')
            speak=self.local_radio.urgent if preempt else self.local_radio.say
            key='cc-events:'+native_id if native_id else 'cc-engine'
            accepted=speak(key,text,data=data,source=source,
                valid=lambda sid=ctx.session_id, nid=native_id, message=call: self._baseline_local_valid(sid,message)
                    and self._baseline_quiet_allowed(call) and (nid is None or self._baseline_owner(nid).valid_call(nid)),
                deadline=None if call['expires'] is None else self.origin+call['expires'])
            if accepted:
                self.baseline_inflight[key]=call
                self.call_controls.native_submitted(call, ctx.session_id, ctx.t)
            if not accepted: self.baseline_pending.append(call)
            return accepted
        except (OSError, ValueError) as exc:
            if 'native_id' in call: self._baseline_owner(call['native_id']).error=str(exc)
            else: self.core.error = str(exc)
            self.engine.radio.log.record('crew_chief_withheld',ctx,reason=str(exc),text=call['folder'])
            return False

    def _plan_lookup(self, driver, car, track, layout, length):
        from ..development import waiting_plans
        return waiting_plans(self.app.lib, driver=driver, car=car, track=track, layout=layout, length=length)

    def _engineer_state(self):
        key = getattr(self.app.recorder, 'engineer_key', None)
        if not key:
            return None
        from ..engineer import engine as setup_engine
        from ..engineer.store import EngineerStore
        store = EngineerStore(self.root)
        s = store.get(key)
        plan = s.get('next_run') if s.get('runs') else setup_engine.next_run(store._state(s), None, [])
        return {'key': key, 'runs': len(s.get('runs', [])), 'next_run': plan,
                'pending_changes': list(s.get('pending_changes') or [])}

    def engineer_run_done(self, key, session):
        """Called by the setup engineer (recorder thread) after it analyses a live run."""
        try:
            run = session['runs'][-1]
            measure = run.get('measure') or {}
            info = {'key': key, 'run': run.get('id'), 'best_lap': measure.get('best_lap'), 'laps': measure.get('n_flying'),
                    'recommendations': [{k: r.get(k) for k in ('setting', 'label', 'category', 'ticks', 'priority', 'test', 'confidence')}
                                        for r in run.get('recommendations') or []]}
            self.engineer_results.put_nowait((key, info))
        except (KeyError, IndexError, TypeError, queue.Full):
            pass

    def _service_program(self):
        """Coach thread, under the lock: voice replies, engineer results and Practice 1's engineer."""
        engine = self.engine
        program = engine.program if engine else None
        ctx = engine.context if engine else None
        if program is None or ctx is None:
            return
        now = time.monotonic()
        bridge = self.app._crew_chief
        if bridge is not None and now - self._last_reply_poll > .2:
            self._last_reply_poll = now
            program.replies_enabled = bool(bridge.settings.get('replies_receipt')) or self._wheel_replies()
            for token in bridge.poll_replies():
                self._apply_reply(parse_reply(token), 'voice')
        while True:
            try:
                key, info = self.engineer_results.get_nowait()
            except queue.Empty:
                break
            if key == getattr(self.app.recorder, 'engineer_key', None):
                program.engineer_result(info, engine.radio, ctx)
                engine.radio.log.record('engineer_run_analysed', ctx, text='Setup engineer analysed run '+str(info.get('run'))+'.',
                                        engineer=info)
        # The setup engineer follows every practice run while the coach runs (the user's choice:
        # both on together). The coach never switches it off; that is done on the engineer page.
        wanted = ctx.session == 'practice' and ctx.active
        if wanted and self._engineer_session != program.session_id and getattr(self.app.recorder, 'engineer', None) is None:
            self._engineer_session = program.session_id
            try:
                key = self.app.start_live_engineer(started_by=ENGINEER_OWNER)
                engine.radio.log.record('engineer_started', ctx, text='Setup engineer following Practice 1 runs.', key=key)
            except Exception as exc:
                self.program_error = 'Setup engineer could not start: ' + str(exc)[:300]
                engine.radio.log.record('engineer_unavailable', ctx, reason=self.program_error)
        elif wanted and self._engineer_session != program.session_id:
            self._engineer_session = program.session_id      # already running (started on the engineer page)

    def _tyre_window(self, car):
        try:
            return dict(self.app.lib.settings.tyre_windows.get(car or '', {}))
        except Exception:
            return {}

    def _engineer_corners(self):
        key = getattr(self.app.recorder, 'engineer_key', None)
        if not key:
            return []
        from ..engineer.store import EngineerStore
        return EngineerStore(self.root).get(key).get('corners') or []

    # ------------------------------------------------------------------ talking to the engineer
    def _ensure_buttons(self):
        if self.buttons is None or not self.buttons.is_alive():
            self.buttons = ButtonWatch(self.button_bindings)
            self.buttons.start()

    def _ensure_listener(self):
        if self.listener is None:
            from ..crew_chief import REPLY_MACROS
            self.listener = WindowsListener([p for _, phrases in REPLY_MACROS for p in phrases] +
                [p for commands in (ENGINE_COMMANDS,PENALTY_COMMANDS,CONDITIONS_COMMANDS,RADIO_COMMANDS,DAMAGE_COMMANDS,PIT_COMMANDS,POSITION_COMMANDS,TIMING_COMMANDS,LAPTIME_COMMANDS) for phrases in commands.values() for p in phrases]+list(I_AM_OK)+fuel_listener_phrases()+tyre_listener_phrases()+
                ['can you do a recon lap','start a recon lap','call out the corners','guide me around the track'])
        return self.listener

    def capture_button(self, role):
        if role not in BUTTON_ROLES:
            raise ValueError('Choose which button to set.')
        with self.lock:
            self._ensure_buttons()
            self.buttons.start_capture(role)
            self.talk.update(capturing=role, note='Press the button on your wheel now (10 seconds).')
        time.sleep(.3)        # let a just-started controller watch report a problem straight away
        with self.lock:
            if self.buttons.error:
                self.talk.update(capturing=None, note=self.buttons.error)
        return self.status()

    def clear_button(self, role):
        if role not in BUTTON_ROLES:
            raise ValueError('Choose which button to clear.')
        with self.lock:
            bindings = dict(self.button_bindings)
            bindings.pop(role, None)
            self._configure({'buttons': bindings})
        return self.status()

    def _service_buttons(self):
        """Under the lock (coach thread each tick, or a status request): button presses, captures
        and what push-to-talk heard."""
        from ..crew_chief import REPLY_MACROS
        if self.buttons is not None:
            for event in self.buttons.drain():
                kind, role = event['event'], event.get('role')
                if kind == 'captured':
                    bindings = dict(self.button_bindings)
                    bindings[role] = event['binding']
                    try:
                        self._configure({'buttons': bindings})
                        self.talk.update(capturing=None, note='Set: ' + event['binding']['label'] + '.')
                    except ValueError as exc:
                        self.talk.update(capturing=None, note=str(exc))
                elif kind == 'capture_timeout':
                    self.talk.update(capturing=None, note='No button press seen. Try again, or check Windows sees the wheel.')
                elif role and role.startswith('skill_'):
                    if kind == 'down':self.app.skill_overlay.command(role.removeprefix('skill_'))
                elif role and role.startswith('overlay_'):
                    if kind == 'down':
                        self.app.practice_overlay.command(role.removeprefix('overlay_'))
                elif role == 'ptt':
                    listener = self._ensure_listener()
                    if kind == 'down':
                        if self.local_radio is not None:
                            self.local_radio.cancel_all()     # the engineer stops when you key the radio
                        listener.press()
                        self.talk['state'] = 'starting'
                    else:
                        listener.release()
                        if self.local_radio is not None:
                            self.local_radio.cue(False)
                        self.talk['state'] = 'thinking'
                elif kind == 'down':
                    self._button_reply(role, 'button')
        if self.listener is not None:
            for event in getattr(self.listener,'drain_events',lambda:[])():
                if event['event']=='listening' and self.talk['state']=='starting':
                    self.talk['state']='listening'
                    if self.local_radio is not None:self.local_radio.cue(True)
            tokens = {p.lower(): token for token, phrases in REPLY_MACROS for p in phrases}
            for outcome in self.listener.heard_details():
                text,confidence=outcome['text'],outcome['confidence']
                self.talk['state'] = 'idle'
                self.core.waiting_for_speech=False
                pending_ok=self.core.waiting_for_driver_ok
                if self.standalone and self.running and self.engine and self.engine.context and self._local_valid(self.engine.context.session_id) and not outcome.get('problem'):
                    self.core.voice_enabled=bool(self.listener.ready and not self.listener.error)
                    self.core.waiting_for_speech=False
                    self._queue_baseline(self.core.speech_result(text,confidence,detected_speech=outcome['detected_speech']),requested=True)
                baseline=bool(text and (command_for(text) or penalty_command(text) or conditions_command(text) or damage_command(text) or fuel_command(text) or pit_command(text) or position_command(text) or timing_command(text) or tyre_command(text) or laptime_command(text)))
                intent=parse_reply(text) if text and not baseline else None
                token=(text if baseline or intent and intent.kind!='unknown' else tokens.get(text.lower())) if text else None
                threshold=float(self.core.settings['minimum_voice_recognition_confidence_system_sre']) if baseline or pending_ok else .45
                if not 0<=threshold<=1:threshold=.7
                understood = bool(token) and confidence >= threshold and not outcome.get('problem')
                if pending_ok:understood=bool(text) and clearly_ok(text) and confidence>=threshold
                self.talk['last_heard'] = {'text': text, 'confidence': round(confidence, 2) if text else None,
                                           'understood': understood, 'problem': outcome.get('problem')}
                if outcome.get('problem'):
                    self.talk['note']=outcome['problem']
                elif pending_ok:
                    self.talk['note']='Driver response passed to the original crash exchange.'
                elif understood:
                    self._button_reply(token, 'voice')
                else:
                    self.talk['note']=('Speech was not clear enough. Hold the radio button, wait for its click, then try again.'
                        if text or outcome['detected_speech'] else 'No speech heard. Check the default Windows microphone and hold the radio button while speaking.')

    def _button_reply(self, token, source):
        engine = self.engine
        if not self.running or engine is None or engine.program is None or engine.context is None:
            self.talk['note'] = 'Heard "' + token + '", but the live coach is not running in a practice session.'
            return
        if not self._engine_reply(token, source):
            self._apply_reply(parse_reply(token), source)

    def _engine_reply(self, text, source):
        if self.core.waiting_for_driver_ok and source=='typed' and self.standalone and self._local_valid(self.engine.context.session_id):
            self.core.waiting_for_speech=False
            calls=self.core.speech_result(text,1,detected_speech=bool(text),voice=False)
            self._queue_baseline(calls,requested=True)
            response='Driver response passed to the original crash exchange.' if calls else 'Fresh data for that response is not available yet.'
            self.talk['note']=response
            self.engine.radio.log.record('driver_reply',self.engine.context,text=text,source=source,understood='DRIVER_OK_RESPONSE',response=response)
            return {'understood':'DRIVER_OK_RESPONSE','response':response}
        command = command_for(text) or penalty_command(text) or conditions_command(text) or damage_command(text) or fuel_command(text) or pit_command(text) or position_command(text) or timing_command(text) or tyre_command(text) or laptime_command(text)
        if command is None:
            return None
        ctx = self.engine.context
        if not self.standalone or not self._local_valid(ctx.session_id):
            response = 'Original Crew Chief replies require fresh local telemetry and Paddock audio.'
        elif command == 'HOW_ARE_MY_ENGINE_TEMPS' and self.core.engine_state == 'warming_up':
            response = 'Original engine temperature monitoring needs two minutes of session warm-up.'
        elif command in PENALTY_COMMANDS and self.events.joined_with_penalty:
            response = 'A penalty was already active when monitoring began; its reminder history is unavailable.'
        else:
            self.core.waiting_for_speech=self.talk.get('state') in ('listening','thinking')
            calls = self.core.respond(command,text=fuel_text(text)) if command=='CALCULATE_FUEL_FOR' else (self.events if command in PENALTY_COMMANDS else self.core).respond(command)
            self._queue_baseline(calls,requested=True)
            response = 'Original Crew Chief response queued.' if calls else 'Fresh data for that response is not available yet.'
        self.talk['note'] = response
        self.engine.radio.log.record('driver_reply',ctx,text=text,source=source,
                                     understood=command,response=response)
        return {'understood':command,'response':response}

    def _wheel_replies(self):
        """The driver can answer from the wheel: push-to-talk or a direct confirm/no button."""
        return any(role in self.button_bindings for role in ('ptt', 'confirm', 'negative'))

    def _replies_configured(self):
        """Whether Crew Chief voice replies are set up, without opening the Crew Chief bridge."""
        bridge = self.app._crew_chief
        if bridge is not None:
            return bool(bridge.settings.get('replies_receipt'))
        try:
            saved = json.loads((self.root / 'crew_chief' / 'settings.json').read_text(encoding='utf-8-sig'))
            return isinstance(saved, dict) and bool(saved.get('replies_receipt'))
        except (OSError, ValueError):
            return False

    def _apply_reply(self, intent, source):
        engine = self.engine
        if intent.kind == 'recon':
            record = {'t': engine.context.t if engine.context else None, 'source': source, 'text': intent.text,
                      'understood': intent.describe(), 'response': engine.start_recon()}
            engine.radio.log.record('driver_reply', engine.context, text=intent.text, source=source,
                                    understood=record['understood'], response=record['response'])
            return record
        with engine.radio.requested():
            record = engine.program.reply(intent, engine.radio, engine.context, source)
        engine.radio.log.record('driver_reply', engine.context, text=intent.text, source=source,
                                understood=record['understood'], response=record['response'])
        return record

    def _program_ready(self):
        if not self.running or self.engine is None or self.engine.program is None or self.engine.context is None:
            raise ValueError('Start the live coach while you are in a practice session first.')

    def say(self, text):
        """A typed reply to the engineer, understood the same way as a voice reply."""
        intent = parse_reply(text)
        with self.lock:
            self._program_ready()
            record = self._engine_reply(text, 'typed') or self._apply_reply(intent, 'typed')
        return {'reply': record, **self.status()}

    def set_goal(self, goal):
        with self.lock:
            self._program_ready()
            engine = self.engine
            with engine.radio.requested():
                engine.program.set_goal(goal, engine.radio, engine.context, 'screen')
            engine.radio.log.record('driver_reply', engine.context, text='Session goal chosen on screen: ' + str(goal),
                                    source='screen', understood=goal, response='Set')
        return self.status()

    def _flush_log(self):
        if self.engine:
            try:
                self.engine.radio.log.flush()
            except OSError as exc:
                self.live_error = 'Private radio log failed: '+str(exc)
                self.stop_event.set()

    def _submit_audio(self, delivery):
        ctx = self.engine.context
        try:
            clip = self.voice.get(delivery.text)
            if not clip:
                if not self.tts_fallback:
                    raise ValueError('This phrase has no verified local recording.')
                try:
                    return self._submit_speech(delivery)
                except (OSError, ValueError) as exc:
                    # No clip ticket exists for this call, so record why it stayed silent here.
                    self.engine.radio.log_delivery('speech_withheld', ctx, delivery, str(exc))
                    if self.engine.radio.delivering == delivery:
                        self.engine.radio.acknowledge(delivery, ctx, accepted=False)
                    return
            if not self.app.port:
                raise ValueError('The private audio server is unavailable.')
            ticket = self.audio.issue(delivery, clip, ctx)
            request_id = self.app.crew_chief.submit_audio(f'http://127.0.0.1:{self.app.port}'+self.audio.path(ticket))
            self.engine.radio.log_delivery('audio_queued',ctx,delivery,request_id=request_id)
        except (OSError, ValueError) as exc:
            self.audio.cancel(self.engine.radio, ctx, str(exc))
            if self.engine.radio.delivering == delivery:
                self.engine.radio.acknowledge(delivery, ctx, accepted=False)

    def _submit_local(self, delivery):
        """Paddock's own radio: speak the selected call now, from the voice pack or Windows speech."""
        ctx = self.engine.context
        radio = self.engine.radio
        reason = radio.delivery_reason(delivery, ctx)
        if reason is None and self.local_radio is None:
            reason = 'radio_not_open'
        if reason is None and not self.local_radio.can_say(delivery.text):
            reason = 'no_voice_for_line'
        if reason:
            radio.log_delivery('speech_withheld', ctx, delivery, reason)
            radio.acknowledge(delivery, ctx, accepted=False)
            return
        if radio.acknowledge(delivery, ctx, accepted=True) and self.local_radio.say(delivery.message.id, delivery.text,
                valid=lambda: self._local_valid(delivery.message.session_id) and
                    self.engine.radio.invalid_delivery(delivery, self.engine.context) is None):
            route = 'paddock_voice_pack' if self.voice.duration(delivery.text) is not None else 'windows_speech'
            radio.log_delivery('speech_queued', ctx, delivery, route=route, seconds_estimate=delivery.seconds)

    def _original_prestart_valid(self,session_id):
        """Only a fresh, confirmed original-mapper prestart, never general menus.

        This does not enable Paddock coaching or spotting in menus. Native queue
        validation is still required separately for each original call.
        """
        ctx=self.engine.context if self.engine else None
        latest=self.core.latest
        return bool(ctx and ctx.session=='race' and ctx.reason in ('active','menus')
            and not self.stop_event.is_set() and self.standalone and ctx.session_id==session_id
            and 0<=time.perf_counter()-self.origin-ctx.t<=.5
            and latest and latest.get('session')==session_id and 0<=time.perf_counter()-latest['at']<=.25
            and self.core.lap_counter_available and self.core.lap_counter_state=='monitoring'
            and self.core.lap_counter_data.get('mapped',{}).get('phase') in ('Gridwalk','Countdown','Formation'))

    def _baseline_local_valid(self,session_id,call):
        native_id=call.get('native_id','')
        original=bool(str(native_id).startswith('core:') and self.core.valid_call(native_id))
        finish=call.get('source_event')=='SessionEndMessages_4.19.5.4'
        if finish:
            return original and self._original_finish_valid(session_id)
        return self._local_valid(session_id) or bool(original and self._original_prestart_valid(session_id))

    def _original_finish_valid(self,session_id):
        """Fresh native finish only; does not admit coaching/spotting or general menus."""
        ctx=self.engine.context if self.engine else None
        latest=self.core.latest
        data=getattr(self.core,'session_end_data',{})
        return bool(ctx and ctx.session in ('race','practice','qualify')
            and ctx.reason in ('active','finished','driver_retired','menus')
            and not self.stop_event.is_set() and self.standalone and ctx.session_id==session_id
            and 0<=time.perf_counter()-self.origin-ctx.t<=.5
            and latest and latest.get('session')==session_id and 0<=time.perf_counter()-latest['at']<=.25
            and getattr(ctx,'facts',{}).get('game_state') in (S.GAME_INGAME_PLAYING,S.GAME_INGAME_INMENU_TIME_TICKING)
            and latest.get('game_state')==ctx.facts['game_state']
            and getattr(self.core,'session_end_state',None)=='finish_observed'
            and data.get('handled') is True and data.get('observed_running') is True
            and data.get('phase')=='Finished')

    def _local_valid(self, session_id, *, spotter=False):
        # Called from the playback worker: never acquire the coach lock (stop waits for it).
        engine = self.engine
        ctx = engine.context if engine else None
        latest=getattr(getattr(self,'core',None),'latest',None)
        native_finished=bool(latest and latest.get('session')==session_id
            and 0<=time.perf_counter()-latest['at']<=.25 and latest.get('state',{}).get('phase')=='Finished')
        return bool(ctx and not self.stop_event.is_set() and self.standalone
                    and not native_finished
                    and ctx.session_id == session_id and (ctx.active or not spotter and ctx.pit_radio)
                    and 0 <= time.perf_counter() - self.origin - ctx.t <= .5)

    def _local_events(self):
        """Playback receipts from Paddock's radio thread into the radio log. Playing is not proof of listening."""
        ctx = self.engine.context
        for event in self.local_radio.drain() if self.local_radio else ():
            key=str(event.get('key',''))
            if key.startswith(('cc-events:','cc-penalties:')) and event['event'] in ('playing','finished','failed','dropped'):
                native_id=key.split(':',1)[1]
                self._ack_baseline(native_id,event['event'])
                if event['event']!='playing':self.baseline_inflight.pop(key,None)
            state = {'playing': 'radio_playing', 'finished': 'radio_closed', 'failed': 'radio_failed',
                     'dropped': 'radio_dropped', 'spotter': 'spotter'}[event['event']]
            self.engine.radio.log.record(state, ctx, id=event['key'], source='paddock_radio', heard=False,
                                         voice=event.get('source'),
                                         **{k: v for k, v in event.items() if k in ('seconds', 'reason', 'text')})

    def _submit_speech(self, delivery):
        """Hand a clip-less call to Crew Chief's TTS. It cannot be re-checked at playback,
        so it is re-checked here, against the same context, immediately before sending."""
        ctx = self.engine.context
        radio = self.engine.radio
        if self.audio.pending:
            raise ValueError('A private voice call is already awaiting playback.')
        reason = radio.delivery_reason(delivery, ctx)
        if reason:
            raise ValueError('Withheld before text-to-speech: '+reason.replace('_', ' ')+'.')
        if ctx.radio_busy is not False:
            raise ValueError('Crew Chief radio is not observed idle.')
        request_id = self.app.crew_chief.submit_speech(delivery.text)
        radio.log_delivery('speech_queued', ctx, delivery, request_id=request_id, route='crew_chief_tts',
                           seconds_estimate=delivery.seconds)
        if radio.acknowledge(delivery, ctx, accepted=True):
            self.audio.watch_speech(delivery, ctx, radio)

    def claim_audio(self, path):
        match = TICKET_PATH.fullmatch(path)
        if not match or not self.lock.acquire(timeout=.02):
            return SILENCE
        try:
            if (not self.audio_enabled or not self.running or self.stop_event.is_set()
                    or not self.engine or not self.engine.context or self.live_error):
                return SILENCE
            bridge = self.app._crew_chief
            # Do not wait for the bridge's lock here: its settings/status tools
            # may be inspecting Windows processes. This fetch must stay short.
            if bridge is None or not bridge.settings.get('audio_receipt'):
                self.audio.cancel(self.engine.radio, self.engine.context, 'cached_audio_disabled')
                return SILENCE
            age = time.perf_counter()-self.origin-self.engine.context.t
            return self.audio.claim(match[1], self.engine.radio, self.engine.context, age_s=age)
        except (OSError, ValueError) as exc:
            self.live_error = 'Cached voice delivery failed: '+str(exc)
            self.stop_event.set()
            return SILENCE
        finally:
            self.lock.release()

    def stop(self):
        self.stop_event.set()
        rec = self.app.recorder.rec
        if rec:
            rec.hooks.pop("coach", None)
        self.app.recorder.coach = None
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=5)
        self._engineer_session = None      # live engineering keeps running; stop it on the engineer page
        with self.lock:
            self._close_local_radio()
            self.spotter.close()
            self.events.close()
            self.core.close()
            self.cc_voice.close()
            self.baseline_pending.clear()
            if self.listener is not None:
                self.listener.close()
                self.listener = None
            if self.engine and self.engine.context:
                self.engine.radio.log.record('coach_stopped',self.engine.context,text='Live coach stopped.')
                self.audio.cancel(self.engine.radio, self.engine.context, "stopped")
                self.engine.context = replace(self.engine.context, active=False, reason="stopped")
                self.engine.radio.advance(self.engine.context)
        self._flush_log()
        return self.status()

    def configure(self, body):
        with self.lock:
            if self.closed:
                raise ValueError('The coach is shutting down.')
            if self.pack_busy and (body.get('voice_pack', self.voice_selection) != self.voice_selection
                                   or body.get('reload_voice') is True):
                raise ValueError('A voice change is already in progress. Wait or cancel it first.')
            return self._configure(body)

    def _configure(self, body):
        """Apply settings under the service lock, including worker-owned activation."""
        mode = Policy(mode=body.get("mode", self.mode)).mode
        with self.lock:
            units = self.units.update(body.get('units',{}))
            selection = body.get('voice_pack',self.voice_selection)
            voice = self.voice
            if selection!=self.voice_selection:
                if self.running:
                    raise ValueError('Stop the live coach before changing engineer voice.')
                voice = VoiceCache(self.root) if selection=='jim-private' else self.pack_store.cache(selection)
                if voice.errors or not voice.index:
                    raise ValueError('The selected voice has no verified local clips. Your previous voice was preserved.')
            audio_enabled = body.get('audio_enabled', self.audio_enabled)
            if not isinstance(audio_enabled, bool):
                raise ValueError('Cached speech must be enabled or disabled.')
            tts_fallback = body.get('tts_fallback', self.tts_fallback)
            if not isinstance(tts_fallback, bool):
                raise ValueError('Text-to-speech must be enabled or disabled.')
            output = body.get('output', self.output)
            if output not in OUTPUTS:
                raise ValueError('Choose Paddock or Crew Chief to speak the calls.')
            volume = body.get('volume', self.volume)
            if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 1:
                raise ValueError('Volume must be between 0 and 100%.')
            buttons = body.get('buttons', self.button_bindings)
            if not isinstance(buttons, dict) or any(r not in BUTTON_ROLES or not button_binding(b) for r, b in buttons.items()):
                raise ValueError('Invalid button setting.')
            buttons = {r: button_binding(b) for r, b in buttons.items()}
            for role, b in buttons.items():
                if role.startswith('overlay_') and any(other != role and
                        all(b[k] == value[k] for k in ('mid', 'pid', 'button')) for other, value in buttons.items()):
                    raise ValueError('Use a separate wheel button for each overlay control and radio action.')
            spotter = body.get('spotter', self.spotter_enabled)
            if not isinstance(spotter, bool):
                raise ValueError('The spotter must be on or off.')
            baseline_voice = body.get('baseline_voice', self.baseline_voice)
            if baseline_voice not in ('paddock','original'):
                raise ValueError('Choose the selected Paddock voice or original Crew Chief recordings.')
            fuel_multiplier=body.get('fuel_multiplier',self.fuel_multiplier)
            if type(fuel_multiplier) is not int or not 0<=fuel_multiplier<=10:
                raise ValueError('Fuel multiplier must be an integer from 0 to 10.')
            if fuel_multiplier!=self.fuel_multiplier and self.running:
                raise ValueError('Stop the live coach before changing the fuel multiplier.')
            radio_effect = body.get('radio_effect', self.radio_effect)
            if radio_effect not in RADIO_EFFECTS:
                raise ValueError('Choose a radio effect: off, light or full.')
            windows_voice = body.get('windows_voice', self.windows_voice)
            if windows_voice is not None and (not isinstance(windows_voice, str) or not 0 < len(windows_voice) <= 100):
                raise ValueError('Choose an installed Windows voice.')
            if body.get('reload_voice') is True:
                voice.reload()
                self.cc_voice.prepared_for = None
            if voice is not self.voice or body.get('reload_voice') is True:
                self.cc_voice.prepare(voice, self._cc_folders()+self.cc_voice.number_folders)
            if audio_enabled:
                if not voice.index and not tts_fallback:
                    raise ValueError('No verified voice clips are available. Turn on text-to-speech to hear calls without recordings.')
                if output == 'crew_chief' and not self.app.crew_chief.audio_transport_status()['configured']:
                    raise ValueError('Set up cached audio in the Crew Chief connection panel first, or let Paddock speak the calls itself.')
            path = self.root / "private_coach" / "settings.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps({"mode":mode,"private":True,"audio_enabled":audio_enabled,
                                              'tts_fallback':tts_fallback,'output':output,'volume':volume,
                                              'windows_voice':windows_voice,'buttons':buttons,'radio_effect':radio_effect,
                                              'spotter':spotter, 'baseline_voice':baseline_voice,'fuel_multiplier':fuel_multiplier,
                                              "units":asdict(units),'voice_pack':selection},indent=2),encoding='utf-8')
            temporary.replace(path)
            route_changed = (audio_enabled != self.audio_enabled or output != self.output
                             or tts_fallback != self.tts_fallback or windows_voice != self.windows_voice
                             or voice is not self.voice)
            if route_changed and self.engine and self.engine.context:
                ctx = self.engine.context
                self.engine.radio.log.record('coach_audio_mode_changed',ctx,audio_enabled=audio_enabled,
                    text='Cached speech enabled.' if audio_enabled else 'Silent text preview enabled.')
                self.audio.cancel(self.engine.radio, ctx, 'audio_mode_changed')
                quiet = self.engine.radio.policy.quiet_until_lap
                self.engine.radio.reset(ctx, 'audio_mode_changed')
                self.engine.radio.policy.quiet_until_lap = quiet
            self.audio_enabled = audio_enabled
            self.tts_fallback = tts_fallback
            self.output, self.volume, self.windows_voice = output, float(volume), windows_voice
            self.button_bindings = buttons
            if self.running and 'ptt' in buttons:self._ensure_listener()
            self.radio_effect = radio_effect
            self.spotter_enabled = spotter
            if baseline_voice != self.baseline_voice and self.local_radio:
                self.local_radio.cancel_all()
            self.baseline_voice = baseline_voice
            self.fuel_multiplier=fuel_multiplier
            self.core.settings['__paddock_fuel_multiplier']=str(fuel_multiplier)
            if not spotter:
                self.spotter.reset()
                if self.local_radio:
                    self.local_radio.cancel_all()
            if self.local_radio is not None:
                self.local_radio.effect = radio_effect
            if self.buttons is not None:
                self.buttons.bind(buttons)
            if self.local_radio is not None:
                self.local_radio.volume = self.volume
            if route_changed or not self.standalone:
                self._close_local_radio()
                if not self.standalone:self.cc_voice.close()
                self.core.close()
            self.mode = mode
            self.units = units
            self.voice,self.voice_selection = voice,selection
            if self.running and self.standalone:
                self._open_local_radio()
                self.core.start()
            if self.engine:
                self.engine.radio.policy.mode = mode
                self.engine.radio.voice_duration = self._speech_duration if audio_enabled else None
                self.engine.numbers = Numbers(units)
        return self.status()

    def select_voice(self, key):
        with self.lock:
            if self.closed:
                raise ValueError('The coach is shutting down.')
            if self.running:
                raise ValueError('Stop the live coach before changing engineer voice.')
            if self.pack_busy:
                raise ValueError('A voice change is already in progress. Wait or cancel it first.')
            if key == 'jim-private' or any(p['key'] == key for p in self.pack_store.installed()):
                self._activate_voice(key)
                self.pack_state = {'state': 'complete', 'key': key, 'name': self.voice.voice_name}
                return self.status()
            if isinstance(key, str) and key.startswith('import:'):
                name = key[len('import:'):]
                if not any(e['name'] == name for e in self.pack_store.importable()):
                    raise ValueError('That voice pack is no longer in the voice-imports folder.')
                self.pack_cancel = threading.Event()
                cancel = self.pack_cancel
                self.pack_state = {'state': 'verifying', 'key': key, 'name': name}
                self.pack_thread = threading.Thread(target=self._import_voice, args=(name, cancel),
                                                    name='private-coach-voice-import', daemon=True)
                self.pack_thread.start()
                return self.status()
            spec = next((p for p in self.pack_catalogue if p.key == key), None)
            if spec is None:
                raise ValueError('Choose an installed voice or an available voice pack from the list.')
            self.pack_cancel = threading.Event()
            cancel = self.pack_cancel
            self.pack_state = {'state': 'downloading', 'key': key, 'name': spec.name,
                               'received_bytes': 0, 'total_bytes': spec.archive_bytes}
            self.pack_thread = threading.Thread(target=self._download_voice, args=(spec, cancel),
                                                name='private-coach-voice-download', daemon=True)
            self.pack_thread.start()
            return self.status()

    def _activate_voice(self, key):
        # The previous voice survives download, validation and a failed settings write.
        self._configure({'voice_pack': key})
        try:
            self.voice_pack_warnings = self.pack_store.cleanup_except(self.voice_selection)
        except (OSError, ValueError) as exc:
            self.voice_pack_warnings = ['Voice selected; older pack retained: ' + str(exc)]

    def _download_voice(self, spec, cancel):
        def progress(done, total):
            with self.lock:
                self.pack_state.update(received_bytes=done, total_bytes=total)
                if not cancel.is_set() and done == total:
                    self.pack_state['state'] = 'verifying'
        try:
            key = self.pack_store.download(spec, cancel=cancel, progress=progress)
            with self.lock:
                if cancel.is_set() or self.closed:
                    raise InterruptedError('Voice change cancelled; previous voice kept.')
                if self.running:
                    raise ValueError('Stop the live coach before changing engineer voice.')
                self.pack_state['state'] = 'activating'
                self._activate_voice(key)
                self.pack_state['state'] = 'complete'
        except InterruptedError:
            with self.lock:
                self.pack_state['state'] = 'cancelled'
        except Exception as exc:
            with self.lock:
                self.pack_state.update(state='failed', error=str(exc))

    def _import_voice(self, name, cancel):
        try:
            key, spec = self.pack_store.import_local(name, cancel=cancel)
            with self.lock:
                if cancel.is_set() or self.closed:
                    raise InterruptedError('Voice change cancelled; previous voice kept.')
                if self.running:
                    raise ValueError('Stop the live coach before changing engineer voice.')
                self.pack_state.update(state='activating', name=spec.name)
                self._activate_voice(key)
                self.pack_state.update(state='complete', key=key)
        except InterruptedError:
            with self.lock:
                self.pack_state['state'] = 'cancelled'
        except Exception as exc:
            with self.lock:
                self.pack_state.update(state='failed', error=str(exc))

    def cancel_voice(self):
        with self.lock:
            if self.pack_busy:
                self.pack_cancel.set()
                self.pack_state['state'] = 'cancelling'
            return self.status()

    def quiet(self, laps):
        with self.lock:
            if not self.engine or not self.engine.context or not self.engine.context.active:
                raise ValueError("Start a live preview while you're in your car first.")
            self.engine.radio.quiet(self.engine.context, int(laps))
        return self.status()

    def start_replay(self, recording, *, driver=None, speed=0):
        path = self.app.lib.recording_path(recording)
        if driver is not None and (not isinstance(driver, str) or len(driver) > 64):
            raise ValueError("Invalid driver name.")
        if not isinstance(speed, (float, int)) or (speed != 0 and not 1 <= speed <= 20):
            raise ValueError("Replay speed must be0 (unpaced) or1-20.")
        with self.lock:
            if self.replay_thread and self.replay_thread.is_alive():
                raise ValueError("A coach replay is already running. Stop it before starting another.")
            self.replay_state = {"state": "running", "recording": recording, "ticks": 0}
            self.replay_stop = threading.Event()
            mode,units = self.mode,self.units
            # Pin the selected cache inventory now; replay never produces sound or
            # silently falls back to preview when the selected voice has holes.
            voice_durations=self.voice.duration if self.audio_enabled else None
            voice_id=self.voice.voice_id
            tts_fallback=self.audio_enabled and self.tts_fallback
            spotter_enabled = self.spotter_enabled
            crew_engine_enabled = self.output == 'paddock'
            def update(values):
                with self.lock:
                    self.replay_state.update(values)
            def work():
                try:
                    result = run_replay(path, self.root, driver=driver, speed=speed, mode=mode,units=units,
                                        stop=self.replay_stop, progress=update,voice_durations=voice_durations,voice_id=voice_id,
                                        tts_fallback=tts_fallback, spotter_enabled=spotter_enabled,
                                        crew_engine_enabled=crew_engine_enabled)
                    update({"state": "complete", "result": result})
                except InterruptedError:
                    update({"state": "stopped"})
                except Exception as exc:
                    update({"state": "failed", "error": str(exc)})
            self.replay_thread = threading.Thread(target=work, name="private-coach-replay", daemon=True)
            self.replay_thread.start()
            return self.status()

    def status(self):
        with self.lock:
            live = self.engine.status() if self.engine else None
            events = list(self.engine.radio.log.events)[-120:] if self.engine else []
            if not self.running:
                self.observer.poll()
            sdk = {k: self.observer.value.get(k) for k in ('available','busy','reason','voice_type')}
            coverage=self.voice.coverage(CoachEngine.capabilities()['implemented_rules'])
            session=(live or {}).get('context') or {}
            session=session.get('session')
            counts=(live or {}).get('counts',{})
            recent_holds=[e for e in events if e['state'] in ('held','dropped','cancelled') and e.get('reason')]
            readiness={'session':session,'applicable_rules':[r['id'] for r in coverage if session in r['sessions']],
                       'voice_coverage':coverage,'candidates':counts.get('queued',0),
                       'selected':counts.get('selected',0),'audio_queued':counts.get('audio_queued',0),
                       'clips_served':counts.get('audio_served',0),
                       'speech_queued':counts.get('speech_queued',0),
                       'tts_fallback':self.tts_fallback,
                       'latest_hold':recent_holds[-1]['reason'] if recent_holds else None,
                       'audio_heard_verified':False}
            local = self.local_radio
            if not self.running:
                self._service_buttons()
            talk = {**self.talk, 'bindings': dict(self.button_bindings),
                    'roles': [r for r in BUTTON_ROLES if r != 'overlay_toggle' or r in self.button_bindings],
                    'buttons_error': self.buttons.error if self.buttons else None,
                    'controllers': list(self.buttons.controllers) if self.buttons else None,
                    'speech_error': self.listener.error if self.listener else None}
            talk['recognizer_state']=getattr(self.listener,'state','not_started') if self.listener else 'not_started'
            talk['pending_commands']=['AMS2 tyre-set age/lap history and compound pace comparisons are not mapped; these requests return original no-data.']
            recorder = self.app.recorder
            engineer = {'running': getattr(recorder, 'engineer', None) is not None,
                        'key': getattr(recorder, 'engineer_key', None)}
            return {"private": True, "audio_enabled": self.audio_enabled, "mode": self.mode,
                    'call_controls': self.call_controls.status(self.running, self.core, self.events,
                        CoachEngine.capabilities()['implemented_rules'], standalone=self.standalone),
                    'engineer': engineer, 'overlay': self.app.practice_overlay.status(), 'talk': talk, 'last_error': self.last_error,
                    'tts_fallback': self.tts_fallback, 'output': self.output, 'volume': self.volume,
                    'radio_effect': self.radio_effect, 'spotter': self.spotter_enabled,
                    'baseline_voice': self.baseline_voice,
                    'baseline_audio': self.cc_voice.status(self._cc_folders()),
                    'engine_monitor': {'version':'4.19.5.4', 'state':self.core.engine_state,
                                       'error':self.core.error or self.core.data_error,
                                       'pending':len(self.baseline_pending),
                                       'source':'original_shared_mapper',
                                       'withheld':['AMS2 pressure-warning flags']},
                    'penalties': {'version':'4.19.5.4','state':self.events.state,'error':self.events.error,
                                  'late_join_penalty':self.events.joined_with_penalty},
                    'flags': {'version':'4.19.5.4','state':self.events.flag_state,'error':self.events.error,
                              'scope':'AMS2 local yellow/double-yellow/blue/black/slow-car; landmark incidents pending'},
                    'original_core': {'version':'4.19.5.4','state':self.core.state,'error':self.core.error or self.core.data_error,
                        'ready':self.core.ready.is_set(),'events':['Position','LapCounter','Timings','LapTimes','PitStops','Fuel','RaceTime','TyreMonitor','EngineMonitor','DamageReporting','ConditionsMonitor','SessionEndMessages'],
                        'damage_state':self.core.damage_state,'waiting_for_driver_ok':self.core.waiting_for_driver_ok,
                        'fuel_state':self.core.fuel_state,'race_time_state':self.core.race_time_state,'fuel':self.core.fuel_data,
                        'pit_state':self.core.pit_state,'pit':self.core.pit_data,'background':self.core.background,
                        'position_state':self.core.position_state,'position':self.core.position_data,
                        'lap_counter_state':self.core.lap_counter_state,'lap_counter':self.core.lap_counter_data,
                        'timings_state':self.core.timings_state,'timings':self.core.timings_data,
                        'tyres_state':self.core.tyres_state,'tyres':self.core.tyres_data,
                        'lap_times_state':self.core.lap_times_state,'lap_times':self.core.lap_times_data,
                        'session_end_state':self.core.session_end_state,'session_end':self.core.session_end_data,
                        'queue':self.core.queue_status,
                        'withheld':self.core.withheld,'unsupported':['Brake bias is not mapped by the original AMS2 mapper','AMS2 transmission damage is unavailable; original mapper returns NONE',
                            'AMS2 pit speed limit, limiter and box coordinates are unavailable; since-pit history is withheld',
                            'Original background selection is retained; channel mixing is pending',
                            'AMS2 does not supply the rating-based expected finish position',
                            'Manual formation grid-side bridge is pending; optional manual formation calls are withheld',
                            'Original current/legacy lap-time and gap branches are connected; original Opponents/WatchedOpponents branches remain pending',
                            'Relative on-track and leader gaps require observed crossing history; unavailable splits are withheld',
                            'Finish messages require an observed running-to-finished transition; unmapped AMS2 DNF/retired/invalid outcomes are withheld',
                            'Tyre set age/lap history and compound comparison are not mapped; tyre life estimates require observed nonconstant wear history',
                            'Uncached installed driver-name recordings retain original local audio; full championship-name integration is pending'],
                        'full_parity_complete':False},
                    'radio_names': {**self.names.status(), 'live_mapping': dict(self.spoken_names)},
                    'spotter_status': {'version': '4.19.5.4', 'error': self.spotter.error,
                                       'ready': self.spotter.ready.is_set(), 'overlap': self.spotter.has_overlap,
                                       'settings_source': self.spotter.settings_source},
                    'crew_chief_baseline': {'complete': False, 'spotter': 'original_4.19.5.4',
                        'engine_monitor': 'original_4.19.5.4_on_full_shared_mapper_including_stalled',
                        'penalties':'original_4.19.5.4_with_validation_and_delays',
                        'flags':'original_4.19.5.4_basic_flag_calls',
                        'conditions':'original_4.19.5.4_on_full_shared_mapper',
                        'damage':'original_4.19.5.4_on_full_shared_mapper',
                        'fuel':'original_4.19.5.4_on_full_shared_mapper',
                        'race_time':'original_4.19.5.4_on_full_shared_mapper',
                        'pit_stops':'original_4.19.5.4_with_AMS2_availability_guards',
                        'position':'original_4.19.5.4_with_AMS2_availability_guards',
                        'lap_counter':'original_4.19.5.4_normal_starts_and_remaining_laps_manual_formation_pending',
                        'timings':'original_4.19.5.4_current_and_legacy_with_AMS2_availability_and_crossing_history_guards',
                        'tyres':'original_4.19.5.4_with_AMS2_input_and_history_guards',
                        'lap_times':'original_4.19.5.4_current_and_legacy_with_AMS2_timing_history_guards',
                        'session_end':'original_4.19.5.4_with_fresh_observed_finish_and_class_rank_guards',
                        'pending': ['Full flag incidents', 'Pit strategy', 'Original audio monitor/channel/background mixer', 'Manual formation',
                                    'Opponent reports', 'Full Crew Chief speech grammar and names']},
                    'fuel_multiplier':self.fuel_multiplier,
                    'windows_voice': self.windows_voice,
                    'local_radio': {'open': local is not None, 'busy': bool(local and local.busy),
                                    'error': local.error if local else None,
                                    'speech_error': self.speech.error if self.speech else None,
                                    'windows_voices': list(self.speech.voices) if self.speech else []},
                    'readiness':readiness,
                    "capabilities":CoachEngine.capabilities(),
                    "units":asdict(self.units),"format_examples":Numbers(self.units).examples(),
                    "running": self.running, "error": self.live_error, "live": live,
                    'program_error': self.program_error,
                    "voice": self.voice.status(), "sdk": sdk,
                    'voice_packs':{'selected':self.voice_selection,'installed':self.pack_store.installed(),
                                   'importable':[{'key':'import:'+e['name'],'name':e['name'],'bytes':e['bytes'],
                                                  'parts':e['parts']} for e in self.pack_store.importable()],
                                   'available':[{'key':p.key,'voice_id':p.voice_id,'name':p.name,
                                                 'version':p.version,'bytes':p.archive_bytes}
                                                for p in self.pack_catalogue],
                                   'catalogue_error':self.pack_catalogue_error,
                                   'job':dict(self.pack_state),'busy':self.pack_busy,
                                   'warnings':list(self.voice_pack_warnings)},
                    "dropped_snapshots": self.dropped_snapshots, "events": events,
                    "replay": dict(self.replay_state), "current": self.app.recorder.status().get("current")}

    def review_file(self, run):
        if not re.fullmatch(r"[a-f0-9]{32}", run or ""):
            raise LookupError("Unknown private coach replay.")
        base = (self.root / "private_coach" / "replays").resolve()
        path = (base / run / "review.html").resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise LookupError("Unknown private coach replay.")
        return path

    def route(self, method, path, body, query=None):
        query = query or {}
        if method == 'GET' and path == '/api/coach/names/catalogue':
            return {**self.names.catalogue(), **self.names.status()}
        if method == 'GET' and path == '/api/coach/names/qualifying':
            with self.lock:
                return self.names.review(self.app.lib, query.get('recording', ''), query.get('champ', ''))
        if method == "GET" and path == "/api/coach":
            return self.status()
        if method == "POST":
            if not isinstance(body, dict):
                raise ValueError("Coach requests must be JSON objects.")
            if path == '/api/coach/names/personal':
                with self.lock:
                    return self.names.set_personal(body.get('name', ''), body.get('revision'))
            if path == '/api/coach/names/qualifying':
                with self.lock:
                    return self.names.assign(self.app.lib, body.get('recording', ''), body.get('champ', ''),
                                             body.get('assignments'), body.get('revision'))
            if path == '/api/coach/names/clear':
                with self.lock:
                    return self.names._write({**self.names.data, 'lineup': None}, body.get('revision'))
            if path == "/api/coach/start":
                return self.start(body.get("driver"))
            if path == "/api/coach/stop":
                return self.stop()
            if path == "/api/coach/settings":
                return self.configure(body)
            if path == '/api/coach/calls':
                with self.lock:
                    self.call_controls.save(body)
                    return self.status()
            if path == '/api/coach/voice/select':
                return self.select_voice(body.get('key'))
            if path == '/api/coach/voice/cancel':
                return self.cancel_voice()
            if path == "/api/coach/quiet":
                return self.quiet(body.get("laps", 3))
            if path == '/api/coach/say':
                return self.say(body.get('text'))
            if path == '/api/coach/goal':
                return self.set_goal(body.get('goal'))
            if path == '/api/coach/buttons/capture':
                return self.capture_button(body.get('role'))
            if path == '/api/coach/buttons/clear':
                return self.clear_button(body.get('role'))
            if path == "/api/coach/replay":
                return self.start_replay(body.get("recording", ""), driver=body.get("driver"), speed=body.get("speed", 0))
            if path == "/api/coach/replay/stop":
                self.replay_stop.set()
                return self.status()
        raise LookupError("Unknown coach request.")

    def close(self):
        with self.lock:
            self.closed = True
            self.pack_cancel.set()
        self.stop()
        if self.buttons is not None:
            self.buttons.stop()
        self.observer.close()
        self.replay_stop.set()
        if self.replay_thread:
            self.replay_thread.join(timeout=5)
        if self.pack_thread:
            self.pack_thread.join(timeout=1)
