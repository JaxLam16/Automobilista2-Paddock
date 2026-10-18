"""Original Crew Chief 4.19.5.4 spotter with read-only, local Paddock adapters."""
from __future__ import annotations

import json
import fnmatch
import math
import os
from pathlib import Path
import queue
import random
import re
import subprocess
import sys
import threading
import time
import wave
from collections import deque

import numpy as np

from .model import finite
from .voice import RATE, pcm_wav

ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'crew_chief'
DEFAULTS = json.loads((ASSETS / 'defaults.json').read_text(encoding='utf-8'))
WORDS = {'car_left': 'Car left.', 'car_right': 'Car right.', 'car_inside': 'Car inside.',
         'car_outside': 'Car outside.', 'in_the_middle': "Three wide, you're in the middle.",
         'three_wide_on_left': "Three wide, you're on the left.",
         'three_wide_on_right': "Three wide, you're on the right.",
         'three_wide_on_inside': "Three wide, you're on the inside.",
         'three_wide_on_outside': "Three wide, you're on the outside.",
         'still_there': 'Still there.', 'hold_your_line': 'Hold your line.',
         'clear_left': 'Clear left.', 'clear_right': 'Clear right.',
         'clear_inside': 'Clear inside.', 'clear_outside': 'Clear outside.',
         'clear_all_round': 'Clear all round.'}


def sounds_path():
    configured = Path(os.environ.get('LOCALAPPDATA', '')) / 'CrewChiefV4' / 'Sounds'
    if configured.is_dir():
        return configured
    # Sandboxed helpers may receive a redirected LOCALAPPDATA, while Crew Chief
    # was installed under the real user's profile.
    physical = Path.home() / 'AppData/Local/CrewChiefV4/Sounds'
    return physical if physical.is_dir() else configured


class CrewChiefSounds:
    """Read original local WAV variants. Never modify or download them."""
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else sounds_path()
        self.last = {}
        self.classes = []
        self.ovals = set()
        try:
            from ..crew_chief import discover_exe
            path = Path(discover_exe()).parent / 'carClassData.json'
            text = '\n'.join(line for line in path.read_text(encoding='utf-8-sig').splitlines()
                             if not line.lstrip().startswith('#'))
            # Crew Chief's Newtonsoft reader accepts trailing commas. Only strip
            # them outside JSON strings, leaving class names exactly as written.
            quoted = r'"(?:[^"\\]|\\.)*"'
            text = re.sub(quoted + r'|,(?=\s*[}\]])',
                          lambda match: '' if match[0] == ',' else match[0], text)
            self.classes = json.loads(text).get('CarClasses', [])
            track_data = json.loads((path.parent / 'trackLandmarksData.json').read_text(encoding='utf-8-sig'))
            self.ovals = {d['ams2TrackName'] for d in track_data.get('trackLandmarksData', [])
                          if d.get('isOval') and d.get('ams2TrackName')}
        except (OSError, ValueError, TypeError):
            pass

    def dimensions(self, car_class):
        # CC starts AMS2 at 4.4 m, then applies GlobalBehaviourSettings' 4.5 m
        # default / car-class overrides once the mapper identifies the class.
        exact, wildcard = [], []
        for cls in self.classes:
            for pattern in cls.get('ams2ClassNames') or []:
                if pattern.casefold() == car_class.casefold():
                    exact.append(cls)
                elif fnmatch.fnmatchcase(car_class.casefold(), pattern.casefold()):
                    wildcard.append(cls)
        cls = (exact or wildcard or [{}])[0]
        return (float(cls.get('spotterVehicleLength') or 4.5), float(cls.get('spotterVehicleWidth') or 1.8))

    def get(self, folder):
        bits = folder.split('/')
        if len(bits) != 2 or bits[1] not in WORDS or not (bits[0] == 'spotter' or bits[0].startswith('spotter_')):
            raise ValueError('Unknown Crew Chief spotter sound.')
        base = (self.root / 'voice' / folder).resolve()
        if not base.is_relative_to((self.root / 'voice').resolve()):
            raise ValueError('Invalid sound folder.')
        files = sorted(p for p in base.glob('*.wav') if not p.name.startswith(('_', '.')))
        if not files:
            raise OSError('Original Crew Chief spotter sounds are unavailable on this PC.')
        choice = random.choice([p for p in files if p != self.last.get(folder)] or files)
        self.last[folder] = choice
        return self.read_file(choice)

    def read_file(self, choice):
        with wave.open(str(choice)) as source:
            if source.getsampwidth() != 2 or source.getnchannels() not in (1, 2):
                raise ValueError('Unsupported Crew Chief sound format.')
            rate, channels = source.getframerate(), source.getnchannels()
            data = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(float)
        if channels == 2:
            data = data.reshape(-1, 2).mean(axis=1)
        if rate != RATE:
            data = np.interp(np.arange(round(len(data) * RATE / rate)) * rate / RATE,
                             np.arange(len(data)), data)
        return pcm_wav(np.clip(data, -32768, 32767).round().astype('<i2').tobytes())


class Spotter:
    host_script = 'spotter_host.ps1'
    host_name = 'spotter'
    defaults_file = 'defaults.json'
    request_timeout = .15
    def __init__(self, *, sounds=None, host=None, root=None):
        self.sounds = CrewChiefSounds(sounds)
        self.host = host
        self.root = Path(root) if root is not None else None
        self.settings = dict(DEFAULTS)
        self.settings_source = 'Crew Chief 4.19.5.4 defaults'
        if self.root is not None:
            try:
                from ..crew_chief import documents_folder
                profile = documents_folder() / 'CrewChiefV4/Profiles/Paddock.json'
                values = json.loads(profile.read_text(encoding='utf-8-sig'))['userSettings']
                for key, default in DEFAULTS.items():
                    v = values.get(key, default)
                    if isinstance(v, type(default)) and (not isinstance(v, (float, int)) or
                            isinstance(v, bool) or math.isfinite(v) and 0 <= v <= 100000):
                        self.settings[key] = v
                self.settings_source = str(profile) + ' (read only)'
            except (OSError, ValueError, TypeError, KeyError):
                pass
        self.process = None
        self.replies = queue.Queue()
        self.ready = threading.Event()
        self.error = None
        self._starting = False
        self._session = None
        self._roster = None
        self._last_t = None
        self._race_state = None
        self._start_after = float('-inf')
        self._reset = True
        self.has_overlap = False
        self.left = self.right = 0
        self._closing = False
        self.stderr_tail = ''
        self._readers = ()

    def start(self):
        if self.host is not None or self._starting or self.process is not None or self.error:
            return
        if sys.platform != 'win32':
            self.error = 'The original Crew Chief spotter host requires Windows.'
            return
        self._starting = True
        self.replies = queue.Queue()
        self.stderr_tail = ''
        defaults = ASSETS / self.defaults_file
        if self.root is not None:
            defaults = self.root / 'private_coach' / ('crew-chief-' + self.host_name + '-settings.json')
            defaults.parent.mkdir(parents=True, exist_ok=True)
            defaults.write_text(json.dumps(self.settings, indent=2), encoding='utf-8')
        shell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        process = self.process = subprocess.Popen([str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(ASSETS / self.host_script), '-Defaults', str(defaults), '-Sounds', str(self.sounds.root)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
        diagnostics=deque(maxlen=4)
        diagnostics_done=threading.Event()
        def read_diagnostics():
            # Original events write diagnostics throughout a session. Drain the
            # pipe continuously so logging cannot block a timing/spotter reply.
            try:
                while True:
                    chunk=process.stderr.read(1024)
                    if not chunk:break
                    diagnostics.append(chunk)
                    if self.process is process:self.stderr_tail=''.join(diagnostics)
            except (OSError,ValueError):
                pass
            finally:
                diagnostics_done.set()
        def read():
            try:
                for line in process.stdout:
                    if self.process is not process:break
                    try:
                        item = json.loads(line.lstrip('\ufeff'))
                        if item.get('ready'):
                            self.ready.set()
                        else:
                            self.replies.put(item)
                    except ValueError:
                        self.error = 'Invalid response from Crew Chief '+self.host_name+' host.'
            except (OSError,ValueError):
                pass
            if self.process is process and not self._closing:
                diagnostics_done.wait(.1)
                detail=''.join(diagnostics)[-1000:].strip()
                self.error = self.error or ('Crew Chief '+self.host_name+' host closed.'+(' '+detail if detail else ''))
        self._readers=(threading.Thread(target=read_diagnostics,daemon=True,name='crew-chief-'+self.host_name+'-diagnostics'),
                       threading.Thread(target=read,daemon=True,name='crew-chief-'+self.host_name+'-output'))
        for worker in self._readers:worker.start()

    @staticmethod
    def active(tick, player):
        age = finite(tick.local.get('local_sample_age_s'))
        return bool(tick.fresh and tick.game_state == 2 and player is not None
                    and player.slot == tick.viewed_slot and player.pit == 0
                    and tick.session in ('practice', 'qualify', 'race', 'time_attack')
                    and age is not None and 0 <= age <= .25)

    def reset(self):
        self._reset = True
        self.has_overlap = False
        self.left = self.right = 0

    def valid_call(self, folder):
        kind = folder.split('/')[-1]
        left, right = self.left, self.right
        if kind in ('car_left', 'car_inside'): return left > 0
        if kind in ('car_right', 'car_outside'): return right > 0
        if kind == 'in_the_middle': return left > 0 and right > 0
        if kind in ('three_wide_on_left', 'three_wide_on_inside'): return left == 0 and right > 1
        if kind in ('three_wide_on_right', 'three_wide_on_outside'): return right == 0 and left > 1
        if kind in ('clear_left', 'clear_inside'): return left == 0
        if kind in ('clear_right', 'clear_outside'): return right == 0
        if kind == 'clear_all_round': return left == right == 0
        return kind in ('still_there', 'hold_your_line') and (left > 0 or right > 0)

    def _request(self, payload):
        if self.host is not None:
            return self.host(payload)
        self.start()
        if not self.ready.is_set():
            return None
        self.process.stdin.write(json.dumps(payload, allow_nan=False) + '\n')
        self.process.stdin.flush()
        try:
            # Off the recorder thread. Disable a timed-out host instead of letting
            # a late overlap response survive into a newer snapshot.
            return self.replies.get(timeout=self.request_timeout)
        except queue.Empty:
            self.error = 'Crew Chief '+self.host_name+' host stopped responding.'
            self.close()
            return None

    def feed(self, tick, player, *, busy=False):
        active = self.active(tick, player)
        changed = (tick.session_id != self._session or self._last_t is not None and
                   (tick.t <= self._last_t or tick.t - self._last_t > .5))
        if changed:
            self.reset()
            self._start_after = tick.t
            self._race_state = None
        self._session, self._last_t = tick.session_id, tick.t
        oval = (tick.track + ':' + tick.layout) in self.sounds.ovals
        deprioritize = oval and self.settings['enable_oval_spotter_enhancements']
        if player and player.race_state == 2 and self._race_state is not None and self._race_state != 2:
            self._start_after = tick.t + (2 if deprioritize else self.settings['time_after_race_start_for_spotter'])
        self._race_state = player.race_state if player else None
        if (not active or player.race_state < 0 or tick.t < self._start_after
                or tick.session == 'race' and player.race_state == 0
                or tick.session == 'time_attack' and not self.settings['enable_spotter_in_timetrial']
                or tick.session == 'qualify' and self.settings['spotter_off_during_qualifying']):
            self.reset()
            return []
        yaw = finite(tick.local.get('orientation_yaw'))
        velocity = tick.local.get('world_velocity')
        speed = finite(tick.local.get('speed'))
        if (yaw is None or not velocity or len(velocity) != 2 or
                any(finite(v) is None for v in velocity) or speed is None or player.x is None or player.z is None):
            self.reset()
            return []
        opponents, used, roster = [], {player.position}, []
        for car in sorted(tick.cars, key=lambda c: c.slot):
            if car.slot == player.slot or car.position in used or car.x is None or car.z is None:
                continue
            used.add(car.position)
            opponents.append([car.x, car.z])
            roster.append(car.identity)
        roster = tuple(roster)
        if self._roster != roster:
            self.reset()  # Upstream caches opponent velocity by list index.
        self._roster = roster
        length, width = self.sounds.dimensions(player.car_class)
        payload = {'t': tick.t, 'rotation': (-yaw) % (2 * math.pi),
                   'position': [player.x, player.z], 'velocity': [speed, *velocity],
                   'opponents': opponents, 'length': length, 'width': width,
                   'oval': oval, 'deprioritize': deprioritize, 'busy': bool(busy), 'reset': self._reset}
        try:
            result = self._request(payload)
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self.close()
            return []
        if result is None:
            return []
        if result.get('error'):
            self.error = result['error']
            return []
        self._reset = False
        self.has_overlap = bool(result.get('overlap'))
        self.left, self.right = result.get('left', 0), result.get('right', 0)
        return result.get('calls', [])

    def close(self):
        self._closing = True
        process, self.process = self.process, None
        self.ready.clear()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            process.stdin.close()
            for worker in self._readers:
                if worker is not threading.current_thread():worker.join(.5)
            process.stdout.close()
            process.stderr.close()
        self._readers=()
