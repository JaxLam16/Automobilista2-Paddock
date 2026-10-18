"""Paddock's own radio: plays engineer calls itself, without Crew Chief.

A call is spoken from the selected voice pack when every word is covered (exact clips or
composed fragments); otherwise Windows' built-in speech reads it, through a small
PowerShell host that stays open. Each call is played as a team radio would sound: key
click and squelch, compressed band-limited voice, static and pit-wall noise behind it, a
release click (strength: off, light or full). It plays on Windows' default output device,
one call at a time. Speech recognition for push-to-talk is in WindowsListener; no speech
model runs here.
"""
from __future__ import annotations

from collections import deque
import base64
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import wave

import numpy as np

from .voice import RATE, pcm_wav, tts_estimate


def _pcm(data):
    with wave.open(io.BytesIO(data)) as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, RATE):
            raise ValueError('Expected mono 16-bit 22050 Hz speech.')
        return np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(np.float64) / 32768


def _band(signal, lo, hi):
    """Zero-phase band-pass by FFT mask with soft edges."""
    n = len(signal)
    if n < 8:
        return signal
    spectrum = np.fft.rfft(signal)
    freq = np.fft.rfftfreq(n, 1 / RATE)
    gain = np.clip((freq - lo * .7) / (lo * .3), 0, 1) * np.clip((hi * 1.3 - freq) / (hi * .3), 0, 1)
    return np.fft.irfft(spectrum * gain, n)


def _click(seconds, seed, level):
    """A short squelch click, like a radio key opening or closing."""
    n = int(RATE * seconds)
    noise = np.random.default_rng(seed).normal(0, 1, n) * np.exp(-np.linspace(0, 7, n))
    shaped = _band(noise, 700, 3800)
    return shaped / max(float(np.max(np.abs(shaped))), 1e-9) * level


def _squelch(seconds, seed, level):
    """The hiss burst of a channel opening or dropping: band-limited static with a fast fade."""
    n = int(RATE * seconds)
    rng = np.random.default_rng(seed)
    hiss = _band(rng.normal(0, 1, n), 1200, 5000)
    hiss = hiss / max(float(np.max(np.abs(hiss))), 1e-9)
    return hiss * np.exp(-np.linspace(0, 5, n)) * level


OPEN_CLICK = _click(.045, 3, .22)
CLOSE_CLICK = _click(.07, 5, .28)
# Strength of the radio colour: 'off' (clicks only), 'light', 'full' (pit-wall radio).
EFFECTS = ('off', 'light', 'full')
_LEVELS = {'off': (0., 0., 0.), 'light': (.012, .006, .3), 'full': (.022, .014, .55)}   # static, pit ambience, drive


def _compress(audio, threshold=.08, ratio=4.0):
    """Radio-style compression: a fast RMS envelope (10 ms), 4:1 above the threshold, make-up gain."""
    window = max(1, int(RATE * .01))
    envelope = np.sqrt(np.convolve(audio ** 2, np.ones(window) / window, mode='same')) + 1e-9
    gain = np.where(envelope > threshold, (threshold * (envelope / threshold) ** (1 / ratio)) / envelope, 1.)
    smooth = max(1, int(RATE * .005))
    gain = np.convolve(gain, np.ones(smooth) / smooth, mode='same')
    out = audio * gain
    return out * (.32 / max(float(np.max(np.abs(out))), 1e-9))


def _pit_wall(n, rng):
    """Background of a pit wall on an open mic: a low rumble, wind, and now and then a car
    going by down the straight (a rising then falling engine note)."""
    rumble = _band(np.cumsum(rng.normal(0, 1, n)) * .02, 40, 300)
    wind = _band(rng.normal(0, 1, n), 300, 1500) * .3
    bed = rumble / max(float(np.max(np.abs(rumble))), 1e-9) + wind / max(float(np.max(np.abs(wind))), 1e-9) * .4
    if rng.random() < .45 and n > RATE:
        t = np.arange(n) / RATE
        centre = rng.uniform(.25, .75) * n / RATE
        shift = np.tanh((t - centre) * 2.5)                     # Doppler: higher coming, lower going
        pitch = rng.uniform(110, 180) * (1 + .12 * -shift)
        phase = np.cumsum(2 * np.pi * pitch / RATE)
        engine = np.sign(np.sin(phase)) * .6 + np.sin(2 * phase) * .4
        engine = _band(engine, 120, 2500) * np.exp(-((t - centre) / .9) ** 2)
        bed = bed + engine / max(float(np.max(np.abs(engine))), 1e-9) * .8
    return bed / max(float(np.max(np.abs(bed))), 1e-9)


def radio_call(data, volume=1.0, effect='full', seed=None):
    """The call as it sounds over a team radio, at the chosen volume, as WAV bytes: key click and
    squelch, compressed band-limited voice with a little drive, static and the pit wall behind it,
    then the release click."""
    effect = effect if effect in EFFECTS else 'full'
    static_level, ambience_level, drive = _LEVELS[effect]
    rng = np.random.default_rng(seed)
    voice = _pcm(data)
    if effect != 'off':
        voice = _band(_compress(voice), 300, 3400)
        voice = np.tanh(voice * (1 + drive * 3)) / np.tanh(1 + drive * 3)
    gap = np.zeros(int(RATE * .06))
    body = np.concatenate([gap, voice, gap])
    if effect != 'off':
        n = len(body)
        static = _band(rng.normal(0, 1, n), 1500, 6000)
        static = static / max(float(np.max(np.abs(static))), 1e-9)
        crackle = np.zeros(n)
        for at in rng.integers(0, n, size=int(n / RATE * 6)):
            width = int(rng.integers(20, 120))
            crackle[at:at + width] += rng.normal(0, 1, len(crackle[at:at + width])) * rng.uniform(.3, 1)
        body = body + static * static_level + _band(crackle, 1000, 5000) * static_level * 2 \
            + _pit_wall(n, rng) * ambience_level
        tail = _squelch(.12, 7, .05 if effect == 'light' else .08)
        head = _squelch(.08, 11, .03 if effect == 'light' else .05)
    else:
        head = tail = np.zeros(0)
    out = np.concatenate([OPEN_CLICK, head, body, CLOSE_CLICK, tail]) * max(0., min(1., float(volume)))
    return pcm_wav((np.clip(out, -1, 1) * 32767).round().astype('<i2').tobytes())


def key_sound(pressed, volume=1.0, effect='full'):
    """What the driver hears pressing or releasing the radio button: a click with a short squelch."""
    if pressed:
        sound = np.concatenate([_click(.03, 13, .25), _squelch(.1, 17, .06 if effect != 'off' else 0)])
    else:
        sound = np.concatenate([_click(.05, 19, .3), _squelch(.14, 23, .07 if effect != 'off' else 0)])
    sound = sound * max(0., min(1., float(volume)))
    return pcm_wav((np.clip(sound, -1, 1) * 32767).round().astype('<i2').tobytes())


def master_speech(pcm_bytes):
    """Windows speech (raw 22050 Hz PCM) mastered like the voice packs: speech band and level."""
    from ..coach_audio import master_radio
    audio = np.frombuffer(pcm_bytes, dtype='<i2').astype(np.float64) / 32768
    mastered, rate = master_radio(audio, RATE, strength=.6, target_rms=.12)
    return pcm_wav((np.clip(mastered, -1, 1) * 32767).round().astype('<i2').tobytes())


class WindowsSpeech:
    """Windows' built-in text-to-speech (System.Speech) through one long-lived PowerShell host.
    Text in, 22050 Hz mono PCM out. Start-up is lazy and off the coach thread."""

    def __init__(self, voice=None, rate=1):
        self.voice = voice
        self.rate = rate
        self.process = None
        self.voices = []
        self.error = None
        self.error_at = 0.
        self.lock = threading.Lock()
        self.serial = 0

    @property
    def available(self):
        # A failure is retried after a minute rather than ending speech for the session.
        return sys.platform == 'win32' and (self.error is None or time.monotonic() - self.error_at > 60)

    def _start(self):
        script = Path(__file__).resolve().parents[1] / 'assets' / 'paddock_speech_host.ps1'
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        self.process = subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                         '-File', str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                        creationflags=subprocess.CREATE_NO_WINDOW)
        ready = self._read(20)
        if ready.get('event') != 'ready':
            raise OSError('Windows speech did not start: ' + str(ready.get('error') or ready))
        self.voices = [v for v in ready.get('voices') or [] if isinstance(v, str)]

    def _read(self, timeout):
        result = {}
        done = threading.Event()
        process = self.process

        def read():
            try:
                for line in process.stdout:
                    line = line.lstrip('\ufeff').strip()
                    if line.startswith('{'):
                        result.update(json.loads(line))
                        break
            except (OSError, ValueError):
                pass
            done.set()
        threading.Thread(target=read, daemon=True).start()
        if not done.wait(timeout):
            raise TimeoutError('Windows speech stopped responding.')
        if not result:
            raise OSError('Windows speech closed.')
        return result

    def request(self, payload, timeout=8.0):
        """One request to the host and its reply (a dict). One request at a time."""
        if sys.platform != 'win32':
            raise OSError('Windows speech needs Windows.')
        with self.lock:
            try:
                if self.process is None or self.process.poll() is not None:
                    self._start()
                self.serial += 1
                self.process.stdin.write(json.dumps({**payload, 'id': self.serial}) + '\n')
                self.process.stdin.flush()
                reply = self._read(timeout)
            except Exception as exc:
                self.error = 'Windows speech is unavailable: ' + str(exc)[:200]
                self.error_at = time.monotonic()
                self.close()
                raise OSError(self.error) from None
            if reply.get('id') != self.serial or reply.get('event') == 'error':
                raise OSError('Windows speech: ' + str(reply.get('error') or 'unexpected reply')[:200])
            self.error = None
            return reply

    def warm(self):
        """Start the host ahead of the first call (it takes a second or two)."""
        try:
            with self.lock:
                if sys.platform == 'win32' and (self.process is None or self.process.poll() is not None):
                    self._start()
        except Exception as exc:
            self.error, self.error_at = 'Windows speech is unavailable: ' + str(exc)[:200], time.monotonic()

    def speak(self, text, timeout=8.0):
        """Raw PCM for the text, or an exception."""
        reply = self.request({'cmd': 'say', 'text': text, 'voice': self.voice or '', 'rate': self.rate}, timeout)
        if reply.get('event') != 'audio':
            raise OSError('Windows speech could not read that line.')
        return base64.b64decode(reply['pcm'])

    def close(self):
        process, self.process = self.process, None
        if process and process.poll() is None:
            try:
                process.stdin.close()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()


class WindowsListener:
    """Push-to-talk speech recognition with Windows' own recogniser (System.Speech), limited to
    the reply phrases. press() starts listening on the default microphone, release() stops and
    queues what was heard: (phrase, confidence) or (None, reason). Its own host process, so a
    call being read out never delays listening."""

    def __init__(self, phrases, *, host=None):
        self.phrases = sorted({p for p in phrases if isinstance(p, str) and p.strip()})
        self.host = host or WindowsSpeech()
        self.work = queue.Queue()
        self.results = queue.Queue()
        self.ready = False
        self.state = 'preparing'
        self.error = None
        self.events = queue.Queue()
        self.closed = threading.Event()
        self.pressed = threading.Event()
        self.work.put('prepare')
        self.thread = threading.Thread(target=self._run, name='paddock-push-to-talk', daemon=True)
        self.thread.start()

    def press(self):
        self.pressed.set()
        self.work.put('start')

    def release(self):
        self.pressed.clear()
        self.work.put('stop')

    def close(self):
        self.closed.set()
        self.work.put(None)
        self.host.close()
        if self.thread is not threading.current_thread():self.thread.join(timeout=3)

    def heard(self):
        return [(item['text'],item['confidence'] if item['text'] else item.get('problem') or 'nothing recognised')
                for item in self.heard_details()]

    def heard_details(self):
        """Keep silence, rejected speech and device errors distinct for crash replies."""
        out = []
        while True:
            try:
                out.append(self.results.get_nowait())
            except queue.Empty:
                return out

    def drain_events(self):
        out = []
        while True:
            try:out.append(self.events.get_nowait())
            except queue.Empty:return out

    def _run(self):
        listening = False
        while True:
            command = self.work.get()
            if command is None or self.closed.is_set():
                self.host.close()
                return
            try:
                if not self.ready:
                    self.host.request({'cmd': 'listen_setup', 'phrases': self.phrases}, 20)
                    self.ready = True
                if self.closed.is_set():
                    self.host.close()
                    return
                if command == 'start' and not listening and self.pressed.is_set():
                    self.host.request({'cmd': 'listen_start'}, 5)
                    listening = True
                    self.state = 'listening'
                    self.events.put({'event': 'listening'})
                elif command == 'stop' and listening:
                    listening = False
                    self.state = 'thinking'
                    reply = self.host.request({'cmd': 'listen_stop'}, 5)
                    text = reply.get('text')
                    if isinstance(text, str) and text:
                        self.results.put({'text':text,'confidence':float(reply.get('confidence') or 0),
                                          'detected_speech':True,'problem':reply.get('problem')})
                    else:
                        self.results.put({'text':None,'confidence':0,
                                          'detected_speech':bool(reply.get('detected_speech')),'problem':reply.get('problem')})
                elif command == 'stop':
                    self.results.put({'text':None,'confidence':0,'detected_speech':False,
                        'problem':'Radio button released before the microphone was ready. Hold it and wait for the click.'})
                if not listening:self.state = 'ready'
                self.error = None
            except Exception as exc:
                listening, self.ready = False, False
                self.state = 'error'
                self.error = 'Push-to-talk speech is unavailable: ' + str(exc)[:200]
                if command == 'stop':
                    self.results.put({'text':None,'confidence':0,'detected_speech':False,'problem':self.error})


def winsound_sink():
    """Play WAV bytes on the default output device; blocks until the clip ends."""
    import winsound

    def play(data):
        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)

    def stop():
        winsound.PlaySound(None, 0)
    return play, stop


class LocalRadio:
    """One call at a time, in order. The coach thread hands over (id, text); rendering and playback
    happen here so a slow Windows speech request never stalls telemetry."""

    def __init__(self, voice, *, speech=None, sink=None, volume=1.0, effect='full', clock=time.monotonic):
        self.voice = voice
        self.speech = speech
        self.volume = volume
        self.effect = effect
        self.clock = clock
        self._play, self._stop = sink if sink is not None else (winsound_sink() if sys.platform == 'win32'
                                                                else (lambda data: None, lambda: None))
        self.queue = queue.Queue(maxsize=8)
        self.events = deque(maxlen=200)
        self.current = None
        self.error = None
        self.closed = threading.Event()
        self._generation = 0
        self._state_lock = threading.RLock()
        self.thread = threading.Thread(target=self._run, name='paddock-radio', daemon=True)
        self.thread.start()

    @property
    def busy(self):
        return self.current is not None or not self.queue.empty()

    def can_say(self, text):
        return self.voice.duration(text) is not None or bool(self.speech and self.speech.available)

    def duration(self, text):
        """Spoken length without the clicks: a pack clip's real length, else a speech estimate."""
        seconds = self.voice.duration(text)
        if seconds is None and self.speech is not None and self.speech.available:
            seconds = tts_estimate(text)
        return seconds

    def say(self, key, text, *, valid=None, deadline=None, data=None, source='crew_chief_recording'):
        with self._state_lock:
            if self.closed.is_set():
                return False
            try:
                self.queue.put_nowait((key, text, self._generation, valid, deadline, data, source))
                return True
            except queue.Full:
                self.events.append({'event': 'dropped', 'key': key, 'reason': 'radio_queue_full'})
                return False

    def cancel_all(self):
        with self._state_lock:
            # Rendering may still be in progress. Invalidate that work as well as the queue.
            self._generation += 1
            while True:
                try:
                    key, *_ = self.queue.get_nowait()
                    self.events.append({'event': 'dropped', 'key': key, 'reason': 'cancelled'})
                except queue.Empty:
                    break
            if self.current is not None:
                self._stop()

    def spot(self, text, *, valid=None, deadline=None, data=None, source='crew_chief_recording'):
        """Interrupt the engineer; let an already-playing spotter phrase finish (CC behaviour)."""
        with self._state_lock:
            if self.current == 'spot':
                while True:
                    try:
                        key, *_ = self.queue.get_nowait()
                        self.events.append({'event': 'dropped', 'key': key, 'reason': 'spotter_replaced'})
                    except queue.Empty:
                        break
            else:
                self.cancel_all()
            return self.say('spot', text, valid=valid, deadline=deadline, data=data, source=source)

    def cue(self, pressed):
        """The radio-button click, played at once (the engineer has already been cut off)."""
        return self.say('key', pressed)

    def urgent(self, key, text, **kwargs):
        """Original immediate engineer calls may cut the chief, never the spotter."""
        with self._state_lock:
            if self.current == 'spot':
                return False
            self.cancel_all()
            return self.say(key,text,**kwargs)

    def drain(self):
        out = []
        while self.events:
            out.append(self.events.popleft())
        return out

    def _render(self, text):
        clip = self.voice.get(text)
        if clip is not None:
            return clip.data, 'voice_pack'
        if self.speech is None:
            raise OSError('No voice clip covers this line and Windows speech is off.')
        return master_speech(self.speech.speak(text)), 'windows_speech'

    def _run(self):
        if self.speech is not None:
            self.speech.warm()
        while not self.closed.is_set():
            try:
                key, text, generation, valid, deadline, supplied, supplied_source = self.queue.get(timeout=.25)
            except queue.Empty:
                continue
            self.current = key
            try:
                def reason():
                    if self.closed.is_set() or generation != self._generation:
                        return 'cancelled'
                    if deadline is not None and self.clock() >= deadline:
                        return 'expired'
                    if valid is not None and not valid():
                        return 'context_changed'
                    return None
                problem = reason()
                if problem:
                    self.events.append({'event': 'dropped', 'key': key, 'reason': problem})
                    continue
                if key == 'key':
                    call, source = key_sound(text, self.volume, self.effect), 'radio_key'
                else:
                    data, source = (supplied, supplied_source) if supplied is not None else self._render(text)
                    effect = 'light' if key == 'spot' and self.effect != 'off' else self.effect
                    call = radio_call(data, self.volume, effect)
                # Recheck after potentially slow synthesis and DSP, immediately before playback.
                problem = reason()
                if problem:
                    self.events.append({'event': 'dropped', 'key': key, 'reason': problem})
                    continue
                if key != 'key':
                    with wave.open(io.BytesIO(call)) as wav:
                        seconds = wav.getnframes() / RATE
                    self.events.append({'event': 'spotter' if key == 'spot' else 'playing', 'key': key,
                                        'text': text, 'source': source, 'seconds': round(seconds, 2), 't': self.clock()})
                self._play(call)
                if key not in ('key', 'spot'):
                    problem=reason()
                    self.events.append({'event':'dropped' if problem else 'finished','key':key,
                                        'reason':problem,'t':self.clock()})
            except Exception as exc:
                self.error = str(exc)[:300]
                self.events.append({'event': 'failed', 'key': key, 'reason': self.error})
            finally:
                self.current = None

    def close(self):
        self.closed.set()
        self.cancel_all()
        if self.speech is not None:
            self.speech.close()
