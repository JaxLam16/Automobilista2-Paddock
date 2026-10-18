"""Optional local radio connection to an existing Crew Chief installation.

The connection uses that installation's MQTTnet 3.x library in a hidden host.
It never launches, closes or reconfigures Crew Chief just by viewing a page.
"""
from __future__ import annotations

import ctypes
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import uuid
import re
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

PROFILE = 'Paddock.json'
PORT = 48643
TEST_MESSAGE = 'Paddock radio check. Your Crew Chief connection is working.'

# Voice replies (V-24). Crew Chief recognises these phrases while its radio button is
# held and runs a macro that presses two spare keys: F24, then one of F13-F20. Paddock
# watches the keyboard passively (Windows raw input: a copy of each key event, nothing
# is intercepted, blocked or sent) and turns the pair into the reply. No window opens,
# so the game keeps focus. F13-F24 aren't on ordinary keyboards and AMS2 ignores them
# unless they are bound. None of the phrases is a built-in Crew Chief 4.19 voice command
# ("say again" and "yes" are, so they are not used).
# Version 1 ran a command per reply (`cmd /c`), which opened a console window and took
# focus from the game; a setup made with it is upgraded in place from the Crew Chief page.
REPLY_MACROS = (
    ('confirm', ('confirm', 'affirmative', 'copy that', "that's correct")),
    ('negative', ('negative', "that's wrong")),
    ('practice1', ('practice one', 'this is practice one', 'no, this is practice one', "it's practice one",
                   'practice session one', 'first practice', 'setup run')),
    ('practice2', ('practice two', 'this is practice two', 'no, this is practice two', "it's practice two",
                   'practice session two', 'second practice', 'research run')),
    ('free', ('free practice', 'no plan', 'just practice')),
    ('plan', ("what's the plan", 'what are my objectives', 'brief me')),
    ('progress', ('how am I doing', 'objective status', 'how are the objectives')),
    ('debrief', ('debrief', 'give me the debrief')),
    ('recon', ('recon lap', 'reconnaissance lap', 'talk me through the corners', 'call the corners')),
)
REPLY_TOKENS = frozenset(token for token, _ in REPLY_MACROS)
REPLY_PREFIX = 'Paddock reply: '
REPLY_METHOD = 'keys-v2'
PREFIX_KEY = 'F24'
REPLY_KEYS = dict(zip((token for token, _ in REPLY_MACROS), ('F13', 'F14', 'F15', 'F16', 'F17', 'F18', 'F19', 'F20', 'F21')))
# Crew Chief's key names are Windows virtual-key codes; it sends them as scan codes.
KEY_VK = {'F13': 0x7C, 'F14': 0x7D, 'F15': 0x7E, 'F16': 0x7F, 'F17': 0x80, 'F18': 0x81, 'F19': 0x82, 'F20': 0x83,
          'F21': 0x84, 'F24': 0x87}
KEY_SCAN = {'F13': 0x64, 'F14': 0x65, 'F15': 0x66, 'F16': 0x67, 'F17': 0x68, 'F18': 0x69, 'F19': 0x6A, 'F20': 0x6B,
            'F21': 0x6C, 'F24': 0x76}
SEQUENCE_S = 1.0       # F24, then the reply key within this long (the macro presses them 70 ms apart)
LEGACY_REPLY_FILE = 'voice_replies.txt'   # version 1 only: its command appended the token here
MACROS_FILE = 'saved_command_macros.json'
REPLY_SETTINGS = ('enable_command_macros',)
MISSING = '__missing__'
# With Paddock speaking for itself, Crew Chief keeps its spotter, flags, damage and race calls
# but leaves these to Paddock, so the two don't both call lap times, temperatures and fuel.
# Applied to the Paddock profile only, and restored exactly.
SPOTTER_ONLY = {'frequency_of_player_prac_and_qual_lap_time_reports': 0, 'frequency_of_player_race_lap_time_reports': 0,
                'enable_tyre_temp_warnings': False, 'enable_brake_temp_warnings': False,
                'enable_pit_exit_tyre_temp_warning': False, 'enable_pit_exit_brake_temp_warning': False,
                'enable_fuel_messages': False, 'enable_tyre_wear_warnings': False, 'enable_pearls_of_wisdom': False}


def reply_macros():
    """Crew Chief macros pressing F24 and then one reply key each, for AMS2."""
    return [{'name': REPLY_PREFIX + token,
             'description': f'Paddock voice reply: presses {PREFIX_KEY} then {REPLY_KEYS[token]}, which Paddock listens for. '
                            'Added by Paddock voice-reply setup; Remove voice replies in Paddock takes it out.',
             'voiceTriggers': list(phrases),
             'commandSets': [{'description': 'AMS2 version', 'gameDefinition': 'AMS2',
                              'actionSequence': [PREFIX_KEY, REPLY_KEYS[token]], 'keyPressTime': 40,
                              'waitBetweenEachCommand': 30, 'autoExecuteStartChatMacro': False,
                              'autoExecuteEndChatMacro': False}]}
            for token, phrases in REPLY_MACROS]


class ReplyKeyDecoder:
    """Turns the macro's key pair into a reply: F24 arms, then F13-F20 within SEQUENCE_S names it.
    Keys are matched on the virtual key Windows reports, or the scan code when it reports none."""
    REPEAT_S = .5

    def __init__(self):
        self._vk = {code: name for name, code in KEY_VK.items()}
        self._scan = {code: name for name, code in KEY_SCAN.items()}
        self._token = {key: token for token, key in REPLY_KEYS.items()}
        self._armed = None
        self._down = {}

    def feed(self, scan, vk, down, t):
        name = self._vk.get(vk) or (self._scan.get(scan) if vk in (0, 0xFF) else None)
        if name is None:
            return None
        if not down:
            self._down.pop(name, None)
            return None
        held = self._down.get(name)
        self._down[name] = t
        if held is not None and t - held < self.REPEAT_S:
            return None               # auto-repeat of a key that is still down
        if name == PREFIX_KEY:
            self._armed = t
            return None
        armed, self._armed = self._armed, None
        if armed is not None and 0 <= t - armed <= SEQUENCE_S:
            return self._token.get(name)
        return None


class RawKeyListener(threading.Thread):
    """Passive keyboard watcher for voice replies. Windows raw input with RIDEV_INPUTSINK gives a hidden,
    message-only window a copy of each key event while another program (the game) has focus. Nothing is
    intercepted, delayed or sent, and no window is ever shown. Windows only."""

    def __init__(self, on_key):
        super().__init__(name='paddock-voice-replies', daemon=True)
        self.on_key = on_key
        self.error = None
        self.ready = threading.Event()
        self._halt = threading.Event()
        self._thread_id = None

    def stop(self, timeout=2.0):
        self._halt.set()
        self.ready.wait(timeout)
        if self._thread_id:
            ctypes.WinDLL('user32').PostThreadMessageW(self._thread_id, 0x0012, 0, 0)   # WM_QUIT
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout)

    def run(self):
        try:
            self._loop()
        except Exception as exc:   # reported in the Crew Chief status; typed replies still work
            self.error = f'Voice replies could not watch the keyboard: {exc}'
        finally:
            self.ready.set()

    def _loop(self):
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.UINT), ('style', wintypes.UINT), ('lpfnWndProc', WNDPROC),
                        ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE),
                        ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                        ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR), ('hIconSm', wintypes.HICON)]

        class RAWINPUTDEVICE(ctypes.Structure):
            _fields_ = [('usUsagePage', wintypes.USHORT), ('usUsage', wintypes.USHORT), ('dwFlags', wintypes.DWORD),
                        ('hwndTarget', wintypes.HWND)]

        class RAWINPUTHEADER(ctypes.Structure):
            _fields_ = [('dwType', wintypes.DWORD), ('dwSize', wintypes.DWORD), ('hDevice', wintypes.HANDLE),
                        ('wParam', wintypes.WPARAM)]

        class RAWKEYBOARD(ctypes.Structure):
            _fields_ = [('MakeCode', wintypes.USHORT), ('Flags', wintypes.USHORT), ('Reserved', wintypes.USHORT),
                        ('VKey', wintypes.USHORT), ('Message', wintypes.UINT), ('ExtraInformation', wintypes.ULONG)]

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        user32.RegisterClassExW.restype = wintypes.ATOM
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
        user32.RegisterRawInputDevices.restype = wintypes.BOOL
        user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                           ctypes.POINTER(wintypes.UINT), wintypes.UINT]
        user32.GetRawInputData.restype = wintypes.UINT
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        WM_INPUT, RID_INPUT, RIM_TYPEKEYBOARD, RI_KEY_BREAK = 0x00FF, 0x10000003, 1, 1
        RIDEV_INPUTSINK, RIDEV_REMOVE, HWND_MESSAGE = 0x00000100, 0x00000001, wintypes.HWND(-3)
        header_size = ctypes.sizeof(RAWINPUTHEADER)
        need = header_size + ctypes.sizeof(RAWKEYBOARD)

        def read(handle):
            size = wintypes.UINT(0)
            if user32.GetRawInputData(handle, RID_INPUT, None, ctypes.byref(size), header_size) != 0 \
                    or not need <= size.value <= 1024:
                return
            buffer = ctypes.create_string_buffer(size.value)
            if user32.GetRawInputData(handle, RID_INPUT, buffer, ctypes.byref(size), header_size) != size.value:
                return
            if RAWINPUTHEADER.from_buffer_copy(buffer).dwType != RIM_TYPEKEYBOARD:
                return
            key = RAWKEYBOARD.from_buffer_copy(buffer, header_size)
            self.on_key(key.MakeCode, key.VKey, not key.Flags & RI_KEY_BREAK, time.monotonic())

        def procedure(hwnd, message, wparam, lparam):
            if message == WM_INPUT:
                try:
                    read(wintypes.HANDLE(lparam))
                except Exception:
                    pass   # one unreadable event never stops the listener
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        self._procedure = WNDPROC(procedure)   # kept referenced for the window's lifetime
        instance = kernel32.GetModuleHandleW(None)
        name = f'PaddockVoiceReplies{os.getpid()}_{id(self)}'
        window_class = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._procedure,
                                   hInstance=instance, lpszClassName=name)
        if not user32.RegisterClassExW(ctypes.byref(window_class)):
            raise ctypes.WinError(ctypes.get_last_error())
        hwnd = None
        registered = False
        try:
            hwnd = user32.CreateWindowExW(0, name, 'Paddock voice replies', 0, 0, 0, 0, 0, HWND_MESSAGE, None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            device = RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, hwnd)   # generic desktop: keyboard
            if not user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(RAWINPUTDEVICE)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            self._thread_id = kernel32.GetCurrentThreadId()
            self.ready.set()
            message = wintypes.MSG()
            while not self._halt.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0 or result == -1:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if registered:
                remove = RAWINPUTDEVICE(0x01, 0x06, RIDEV_REMOVE, None)
                user32.RegisterRawInputDevices(ctypes.byref(remove), 1, ctypes.sizeof(RAWINPUTDEVICE))
            if hwnd:
                user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(name, instance)


def _write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_bytes(data)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def _read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def documents_folder():
    if sys.platform == 'win32':
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:
            return Path(buffer.value)
    return Path.home() / 'Documents'


def discover_exe():
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'),
                 r'C:\Program Files (x86)', r'C:\Program Files'):
        if base:
            path = Path(base) / 'Britton IT Ltd/CrewChiefV4/CrewChiefV4.exe'
            if path.is_file():
                return str(path)
    return ''


class CrewChief:
    def __init__(self, root: Path, documents=None):
        self.dir = Path(root) / 'crew_chief'
        self.documents = Path(documents) if documents is not None else documents_folder() / 'CrewChiefV4'
        self.settings_path = self.dir / 'settings.json'
        self.error = None
        try:
            self.settings = _read_json(self.settings_path) if self.settings_path.exists() else {}
            if not isinstance(self.settings, dict):
                raise ValueError('Expected a settings object.')
        except (OSError, ValueError):
            self.settings = {}
            self.error = 'Could not read the saved Crew Chief connection. The existing settings file was preserved.'
        self.lock = threading.RLock()
        self.process = None
        self.ready = threading.Event()
        self.clients = set()
        self._host_ready = False
        self.last_test = None
        self.last_test_at = 0
        self.audio_receipts = {}
        self._running_cache = (0, False)
        self._reply_lock = threading.Lock()
        self._reply_offset = None      # version 1 reply file
        self._reply_decoder = ReplyKeyDecoder()
        self._reply_tokens = []
        self._reply_listener = None
        self._reply_retry_at = 0.0

    @property
    def exe(self):
        return Path(self.settings.get('exe') or discover_exe())

    @property
    def mqtt_path(self):
        return self.documents / 'mqtt_telemetry.json'

    @property
    def profile_path(self):
        return self.documents / 'Profiles' / PROFILE

    def _save(self):
        _write(self.settings_path, _json_bytes(self.settings))

    def _is_running(self, fresh=False):
        now = time.monotonic()
        if not fresh and now - self._running_cache[0] < 2:
            return self._running_cache[1]
        if sys.platform != 'win32':
            return False
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq CrewChiefV4.exe', '/FO', 'CSV', '/NH'],
                                capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError('Could not check whether Crew Chief is running. Close it before configuring the connection.')
        running = b'crewchiefv4.exe' in result.stdout.lower()
        self._running_cache = (now, running)
        return running

    def _require_closed(self):
        if self._is_running(fresh=True):
            raise ValueError('Close Crew Chief first so its current settings are saved, then try again.')

    def _validate_exe(self, value):
        exe = Path(str(value)).expanduser()
        if exe.is_dir():
            exe /= 'CrewChiefV4.exe'
        exe = exe.resolve()
        if exe.name.lower() != 'crewchiefv4.exe' or not exe.is_file():
            raise ValueError('Choose the installed CrewChiefV4.exe or its installation folder.')
        if not (exe.parent / 'MQTTnet.dll').is_file() or not (exe.parent / 'mqtt_telemetry.json').is_file():
            raise ValueError('This Crew Chief installation does not include the MQTT connection files.')
        return exe

    def profiles(self):
        return sorted(p.name for p in (self.documents / 'Profiles').glob('*.json') if p.name != PROFILE)

    def status(self):
        with self.lock:
            alive = self.process is not None and self.process.poll() is None
            return {'installed': self.exe.is_file(), 'exe': str(self.exe) if str(self.exe) != '.' else '',
                    'profiles': self.profiles(), 'configured': bool(self.settings.get('receipt')),
                    'enabled': bool(self.settings.get('enabled')), 'listening': alive and self._host_ready,
                    'connected': alive and bool(self.clients), 'port': self.settings.get('port', PORT),
                    'running': self._is_running(), 'error': self.error,
                    'last_test': dict(self.last_test) if self.last_test else None,
                    'profile': PROFILE, 'profile_exists': self.profile_path.is_file(),
                    'cached_audio_configured': bool(self.settings.get('audio_receipt')),
                    'voice_replies': self._replies_status(),
                    'spotter_only': bool(self.settings.get('spotter_receipt')),
                    'backups': str(self.dir / 'backups')}

    def configure(self, body):
        with self.lock:
            self._require_closed()
            if self.settings.get('receipt'):
                raise ValueError('Connection already configured. Restore previous settings before changing its installation or port.')
            exe = self._validate_exe(body.get('exe') or str(self.exe))
            try:
                port = int(body.get('port', PORT))
            except (TypeError, ValueError):
                raise ValueError('Choose a local port from 1024 to 65535.') from None
            if not 1024 <= port <= 65535:
                raise ValueError('Choose a local port from 1024 to 65535.')
            if self.profile_path.exists():
                # A new Paddock installation may not yet have a local receipt,
                # while Crew Chief still has the previous Paddock profile.
                # Reuse that profile's preferences; the transaction below backs
                # it up just like the shared MQTT configuration.
                source = self.profile_path
                profile_label = 'The existing Paddock.json profile'
            else:
                profile = body.get('base_profile') or 'defaultSettings.json'
                if profile not in self.profiles():
                    raise ValueError('Choose an existing Crew Chief profile. Open Crew Chief once if none are listed.')
                source = self.documents / 'Profiles' / profile
                profile_label = 'The selected Crew Chief profile'
            try:
                base = _read_json(source)
            except (OSError, ValueError):
                raise ValueError(profile_label + ' is not readable. Its existing files were preserved.') from None
            if not isinstance(base, dict) or not isinstance(base.get('userSettings'), dict):
                raise ValueError(profile_label + ' is not readable. Its existing files were preserved.')
            base['userSettings'].update(enable_mqtt_telemetry=True, mqtt_topic_drivername='Paddock')
            mqtt = _read_json(self.mqtt_path if self.mqtt_path.exists() else exe.parent / 'mqtt_telemetry.json')
            if not isinstance(mqtt, dict):
                raise ValueError('Crew Chief MQTT settings must be a JSON object.')
            token = secrets.token_urlsafe(32)
            mqtt.update(Server='127.0.0.1', Port=port, Login='paddock', Password=token,
                        Topic='paddock/telemetry', SubscribeTopic='/paddock/coach', UseTLS=False,
                        AllowSoundDownload=False, DebugResponse=True, UpdateRateLimit=59, Channels=[])
            updated = [(self.mqtt_path, _json_bytes(mqtt)), (self.profile_path, _json_bytes(base))]
            checkpoint = self.dir / 'backups' / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
            checkpoint.mkdir(parents=True)
            receipt = {'directory': checkpoint.relative_to(self.dir).as_posix(), 'files': []}
            for i, (path, data) in enumerate(updated):
                old = path.read_bytes() if path.exists() else None
                if old is not None:
                    (checkpoint / f'{i}.original').write_bytes(old)
                receipt['files'].append({'path': str(path), 'backup': f'{i}.original' if old is not None else None,
                                         'applied_sha256': _digest(data),
                                         'original_sha256': _digest(old) if old is not None else None})
                (checkpoint / f'{i}.applied').write_bytes(data)
                receipt['files'][-1]['applied'] = f'{i}.applied'
            _write(checkpoint / 'receipt.json', _json_bytes(receipt))
            previous = dict(self.settings)
            try:
                for path, data in updated:
                    _write(path, data)
                self.settings = {'exe': str(exe), 'port': port, 'token': token, 'enabled': False, 'receipt': receipt}
                self._save()
            except Exception:
                self.stop(persist=False)
                for item in reversed(receipt['files']):
                    path = Path(item['path'])
                    if item['backup']:
                        _write(path, (checkpoint / item['backup']).read_bytes())
                    else:
                        path.unlink(missing_ok=True)
                self.settings = previous
                self._save()
                raise
            return self.status()

    def _host_event(self, event):
        with self.lock:
            kind = event.get('type')
            if kind == 'ready':
                self._host_ready = True
                self.ready.set()
            elif kind == 'subscribed':
                self.clients.add(event['client'])
            elif kind == 'disconnected':
                self.clients.discard(event['client'])
            elif kind == 'error':
                self.error = str(event.get('error', 'Connection host failed.'))[:500]
                self.ready.set()
            elif kind == 'sent':
                if event.get('id') in self.audio_receipts:
                    self.audio_receipts[event['id']]['sent'] = True
            elif kind == 'ack':
                try:
                    ack = json.loads(event['payload'])
                    response = ack.get('response', '')
                    response = json.loads(response) if isinstance(response, str) and response.startswith('{') else {}
                    if self.last_test and response.get('message') == self.last_test['message']:
                        self.last_test['received'] = True
                    for item in self.audio_receipts.values():
                        if response.get('message') == item['url']:
                            item['received'] = True
                except (ValueError, TypeError, AttributeError):
                    pass

    def start(self):
        # Wait outside the lock: the output reader needs it to report readiness.
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            if not self.settings.get('receipt'):
                raise ValueError('Set up the Crew Chief connection first.')
            if sys.platform != 'win32':
                raise ValueError('Crew Chief radio requires Windows.')
            exe = self._validate_exe(str(self.exe))
            self.error = None
            self._host_ready = False
            self.ready.clear()
            self.clients.clear()
            script = Path(__file__).parent / 'assets' / 'crew_chief_host.ps1'
            powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            self.process = subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                             '-File', str(script), '-Library', str(exe.parent / 'MQTTnet.dll')],
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
            process = self.process
            process.stdin.write(json.dumps({'port': self.settings['port'], 'token': self.settings['token'],
                                            'allow_audio': bool(self.settings.get('audio_receipt'))}) + '\n')
            process.stdin.flush()

            def output():
                for line in process.stdout:
                    try:
                        if self.process is process:
                            self._host_event(json.loads(line.lstrip('\ufeff')))
                    except (ValueError, TypeError):
                        pass  # compiler diagnostics are not application events
                if self.process is process:
                    self._host_ready = False
                    self.clients.clear()
                    self.ready.set()
            threading.Thread(target=output, name='crew-chief-radio', daemon=True).start()
        if not self.ready.wait(20) or not self._host_ready or process.poll() is not None or self.error:
            error = self.error or 'Could not start the local radio host. Check the port and the installed MQTTnet version.'
            self.stop(persist=False)
            raise ValueError(error)
        with self.lock:
            self.settings['enabled'] = True
            self._save()

    def stop(self, persist=True):
        # Reader callbacks acquire self.lock, so don't wait on it during shutdown.
        process = self.process
        self.process = None
        if process and process.poll() is None:
            try:
                process.stdin.close()  # EOF stops just our host, never Crew Chief
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                process.wait(timeout=5)
        self.clients.clear()
        self._host_ready = False
        self.ready.clear()
        if persist and self.settings:
            self.settings['enabled'] = False
            self._save()

    def launch(self):
        exe = self._validate_exe(str(self.exe))
        if self._is_running(fresh=True):
            return {'opened': False, 'message': 'Crew Chief is already running.'}
        args = [str(exe), '-game', 'AMS2']
        if self.settings.get('receipt'):
            self.start()
            args += ['-profile', Path(PROFILE).stem]
        subprocess.Popen(args, cwd=exe.parent, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._running_cache = (0, False)
        return {'opened': True, 'message': 'Select the Paddock profile, then start Crew Chief for AMS2.'}

    def test(self):
        with self.lock:
            if not self.clients or not self.process or self.process.poll() is not None:
                raise ValueError('Wait for Crew Chief to connect. Open it with the Paddock profile and start its AMS2 application.')
            if time.monotonic() - self.last_test_at < 5:
                raise ValueError('Wait a few seconds before another radio check.')
            test = {'id': uuid.uuid4().hex, 'message': TEST_MESSAGE, 'sent': False, 'received': False, 'heard': False}
            try:
                self.process.stdin.write(json.dumps({'type': 'say', 'id': test['id'], 'text': TEST_MESSAGE}) + '\n')
                self.process.stdin.flush()
            except (OSError, ValueError):
                raise ValueError('The radio connection closed. Start the connection again.') from None
            test['sent'] = True
            self.last_test = test
            self.last_test_at = time.monotonic()
            return dict(test)

    def heard(self, test_id):
        with self.lock:
            if not self.last_test or self.last_test['id'] != test_id:
                raise ValueError('Send a radio check first, then confirm that check.')
            self.last_test['heard'] = True
            return dict(self.last_test)

    def submit_audio(self, url):
        """Only a one-use Paddock loopback clip may enter CC's regular queue."""
        parsed = urlparse(url)
        try:
            port = parsed.port
        except ValueError:
            port = None
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password
                or not port or not 1024 <= port <= 65535 or parsed.query or parsed.fragment
                or not re.fullmatch(r'/api/coach/audio/[a-f0-9]{48}\.wav', parsed.path)
                or url != f'http://127.0.0.1:{port}'+parsed.path):
            raise ValueError('Cached speech must use Paddock’s one-use local audio endpoint.')
        with self.lock:
            if not self.settings.get('audio_receipt'):
                raise ValueError('Set up cached audio in Crew Chief first.')
            if not self.clients or not self.process or self.process.poll() is not None:
                raise ValueError('Crew Chief is disconnected.')
            request_id = uuid.uuid4().hex
            self.audio_receipts[request_id] = {'url': url, 'sent': False, 'received': False}
            if len(self.audio_receipts) > 64:
                self.audio_receipts.pop(next(iter(self.audio_receipts)))
            try:
                self.process.stdin.write(json.dumps({'type': 'bind_audio', 'port': port})+'\n')
                self.process.stdin.write(json.dumps({'type': 'audio', 'id': request_id, 'url': url})+'\n')
                self.process.stdin.flush()
            except (OSError, ValueError):
                self.audio_receipts.pop(request_id, None)
                raise ValueError('The radio connection closed before the audio request was sent.') from None
            return request_id

    def submit_speech(self, text):
        """A coaching call with no recorded clip, read by Crew Chief's text-to-speech.

        It joins CC's regular queue (not the immediate path the radio check uses), so
        its spotter keeps priority. Unlike a clip there is no fetch to re-check at
        playback, so the coach sends these only while CC's radio is observed idle.
        """
        if (not isinstance(text, str) or not text.strip() or len(text) > 256
                or any(ord(c) < 32 for c in text) or text.lstrip().lower().startswith('http')):
            raise ValueError('Coach speech must be plain text of at most 256 characters.')
        with self.lock:
            if not self.settings.get('audio_receipt'):
                raise ValueError('Set up cached audio in Crew Chief first.')
            if not self.clients or not self.process or self.process.poll() is not None:
                raise ValueError('Crew Chief is disconnected.')
            request_id = uuid.uuid4().hex
            self.audio_receipts[request_id] = {'url': text, 'kind': 'speech', 'sent': False, 'received': False}
            if len(self.audio_receipts) > 64:
                self.audio_receipts.pop(next(iter(self.audio_receipts)))
            try:
                self.process.stdin.write(json.dumps({'type': 'speak', 'id': request_id, 'text': text})+'\n')
                self.process.stdin.flush()
            except (OSError, ValueError):
                self.audio_receipts.pop(request_id, None)
                raise ValueError('The radio connection closed before the speech request was sent.') from None
            return request_id

    def audio_transport_status(self):
        with self.lock:
            return {'configured': bool(self.settings.get('audio_receipt')),
                    'connected': bool(self.clients and self.process and self.process.poll() is None)}

    def prepare_audio(self):
        """Explicit opt-in; layer immutable backups over the existing connection."""
        restart = False
        with self.lock:
            self._require_closed()
            if not self.settings.get('receipt'):
                raise ValueError('Set up the Paddock connection first.')
            if self.settings.get('audio_receipt'):
                return self.status()
            profile, mqtt = _read_json(self.profile_path), _read_json(self.mqtt_path)
            if not isinstance(profile, dict) or not isinstance(profile.get('userSettings'), dict) or not isinstance(mqtt, dict):
                raise ValueError('Existing Crew Chief settings are invalid and were preserved.')
            expected = {'Server': '127.0.0.1', 'Port': self.settings['port'], 'Login': 'paddock',
                        'Password': self.settings['token'], 'SubscribeTopic': '/paddock/coach', 'UseTLS': False}
            prefs = profile['userSettings']
            if (any(mqtt.get(key) != value for key, value in expected.items())
                    or prefs.get('enable_mqtt_telemetry') is not True
                    or prefs.get('mqtt_topic_drivername') != 'Paddock'):
                raise ValueError('Crew Chief connection settings changed. Existing files were preserved; repair the Paddock connection before setting up cached audio.')
            profile['userSettings']['enable_shared_memory'] = True
            mqtt['AllowSoundDownload'] = True
            folder = self.dir / 'backups' / (datetime.now().strftime('%Y%m%d-%H%M%S-audio-')+uuid.uuid4().hex[:8])
            folder.mkdir(parents=True)
            receipt = {'directory': folder.relative_to(self.dir).as_posix(), 'files': []}
            for i, (path, data) in enumerate(((self.mqtt_path, _json_bytes(mqtt)), (self.profile_path, _json_bytes(profile)))):
                old = path.read_bytes()
                (folder / f'{i}.original').write_bytes(old)
                (folder / f'{i}.applied').write_bytes(data)
                receipt['files'].append({'path': str(path), 'backup': f'{i}.original',
                    'applied': f'{i}.applied', 'original_sha256': _digest(old), 'applied_sha256': _digest(data)})
            _write(folder / 'receipt.json', _json_bytes(receipt))
            previous = dict(self.settings)
            try:
                for item in receipt['files']:
                    _write(Path(item['path']), (folder / item['applied']).read_bytes())
                self.settings['audio_receipt'] = receipt
                self._save()
                restart = bool(previous.get('enabled'))
                self.stop(persist=False)
            except Exception:
                for item in receipt['files']:
                    _write(Path(item['path']), (folder / item['backup']).read_bytes())
                self.settings = previous
                self._save()
                raise
        if restart:
            try:
                self.start()
            except (OSError, ValueError) as exc:
                self.error = 'Cached audio is configured; restart the local connection: '+str(exc)
        return self.status()

    def _audio_backup(self):
        receipt = self.settings.get('audio_receipt')
        if not receipt:
            return None
        folder = (self.dir / receipt['directory']).resolve()
        expected = {self.profile_path.resolve(), self.mqtt_path.resolve()}
        if (not folder.is_relative_to((self.dir / 'backups').resolve())
                or {Path(item['path']).resolve() for item in receipt['files']} != expected):
            raise ValueError('Invalid cached-audio backup. Existing settings were preserved.')
        for item in receipt['files']:
            for field, digest in (('backup', 'original_sha256'), ('applied', 'applied_sha256')):
                path = (folder / item[field]).resolve()
                if path.parent != folder or _digest(path.read_bytes()) != item[digest]:
                    raise ValueError('Cached-audio backup changed. Existing settings were preserved.')
            if _read_json(Path(item['path'])) != _read_json(folder / item['applied']):
                raise ValueError('Crew Chief settings changed after audio setup. Existing files and backups were preserved.')
        return folder, receipt['files']

    # ------------------------------------------------------------------ voice replies
    @property
    def macros_path(self):
        return self.documents / MACROS_FILE

    @staticmethod
    def _macros(data, label):
        try:
            value = json.loads(data.decode('utf-8-sig'))
        except (UnicodeDecodeError, ValueError):
            raise ValueError(label + ' is not readable. Existing files were preserved.') from None
        if not isinstance(value, dict) or not isinstance(value.get('macros'), list) \
                or not all(isinstance(m, dict) for m in value['macros']):
            raise ValueError(label + ' is not a Crew Chief macro list. Existing files were preserved.')
        return value

    def prepare_replies(self):
        """Explicit opt-in, with Crew Chief closed. Adds Paddock's reply macros to the shared
        macro file and turns command macros on in the Paddock profile only. A version 1 setup
        (a console command per reply) is removed first, which also switches Crew Chief's
        "run commands from macros" preference back to what it was."""
        with self.lock:
            self._require_closed()
            if not self.settings.get('receipt'):
                raise ValueError('Set up the Paddock connection first.')
            existing = self.settings.get('replies_receipt')
            if existing and existing.get('method') == REPLY_METHOD:
                return self.status()
            if existing:
                self._restore_replies()
            ours = reply_macros()
            try:
                profile = _read_json(self.profile_path)
            except (OSError, ValueError):
                raise ValueError('The Paddock Crew Chief profile is not readable. Existing files were preserved.') from None
            if not isinstance(profile, dict) or not isinstance(profile.get('userSettings'), dict):
                raise ValueError('The Paddock Crew Chief profile is not readable. Existing files were preserved.')
            existed = self.macros_path.is_file()
            if existed:
                original_macros = self.macros_path.read_bytes()
                macros = self._macros(original_macros, 'Your Crew Chief macro file')
            else:
                default = self._validate_exe(str(self.exe)).parent / MACROS_FILE
                if not default.is_file():
                    raise ValueError("Crew Chief's default macro file was not found. Existing files were preserved.")
                original_macros = None
                macros = self._macros(default.read_bytes(), "Crew Chief's default macro file")
            others = [m for m in macros['macros'] if not str(m.get('name', '')).startswith(REPLY_PREFIX)]
            taken = {str(v).strip().lower() for m in others for v in (m.get('voiceTriggers') or [])}
            clash = sorted(p for _, phrases in REPLY_MACROS for p in phrases if p.lower() in taken)
            if clash:
                raise ValueError('These reply phrases are already used by your Crew Chief macros: '
                                 + ', '.join(clash) + '. Existing files were preserved.')
            macros['macros'] = others + ours
            prefs = profile['userSettings']
            values = {key: prefs.get(key, MISSING) for key in REPLY_SETTINGS}
            prefs.update({key: True for key in REPLY_SETTINGS})
            original_profile = self.profile_path.read_bytes()
            folder = self.dir / 'backups' / (datetime.now().strftime('%Y%m%d-%H%M%S-replies-') + uuid.uuid4().hex[:8])
            folder.mkdir(parents=True)
            applied = [(self.profile_path, original_profile, _json_bytes(profile), 'profile'),
                       (self.macros_path, original_macros, _json_bytes(macros), 'macros')]
            receipt = {'directory': folder.relative_to(self.dir).as_posix(), 'files': [], 'method': REPLY_METHOD,
                       'profile_values': values, 'macros_existed': existed,
                       'macro_names': [m['name'] for m in ours], 'keys': [PREFIX_KEY, *REPLY_KEYS.values()]}
            for path, old, new, name in applied:
                if old is not None:
                    (folder / (name + '.original')).write_bytes(old)
                (folder / (name + '.applied')).write_bytes(new)
                receipt['files'].append({'path': str(path), 'backup': name + '.original' if old is not None else None,
                                         'applied': name + '.applied', 'original_sha256': _digest(old) if old is not None else None,
                                         'applied_sha256': _digest(new)})
            _write(folder / 'receipt.json', _json_bytes(receipt))
            previous = dict(self.settings)
            try:
                for path, _, new, _ in applied:
                    _write(path, new)
                self.settings['replies_receipt'] = receipt
                self._save()
            except Exception:
                for path, old, _, _ in applied:
                    if old is not None:
                        _write(path, old)
                    else:
                        path.unlink(missing_ok=True)
                self.settings = previous
                self._save()
                raise
            with self._reply_lock:
                self._reply_tokens.clear()
                self._reply_retry_at = 0.0
            return self.status()

    def _restore_replies(self):
        """Remove only what reply setup added: Paddock's macros and its profile values.
        Byte-exact originals are written back when nothing else changed since."""
        receipt = self.settings.get('replies_receipt')
        if not receipt:
            raise ValueError('Voice replies are not set up.')
        self._stop_reply_listener()
        folder = (self.dir / receipt['directory']).resolve()
        if not folder.is_relative_to((self.dir / 'backups').resolve()):
            raise ValueError('Voice-reply backup path is outside the connection backup folder.')
        backups = {item['applied']: item for item in receipt['files']}
        for item in receipt['files']:
            for field, digest in (('backup', 'original_sha256'), ('applied', 'applied_sha256')):
                if item.get(field) and _digest((folder / item[field]).read_bytes()) != item[digest]:
                    raise ValueError('Voice-reply backup changed. Existing settings were preserved.')
        planned = []
        names = set(receipt['macro_names'])
        if self.macros_path.is_file():
            current = self._macros(self.macros_path.read_bytes(), 'Your Crew Chief macro file')
            remainder = dict(current, macros=[m for m in current['macros'] if m.get('name') not in names])
            if receipt['macros_existed']:
                original = (folder / backups['macros.applied']['backup']).read_bytes()
                same = self._macros(original, 'The macro backup') == remainder
                planned.append((self.macros_path, original if same else _json_bytes(remainder)))
            else:
                default = self.exe.parent / MACROS_FILE
                same = default.is_file() and self._macros(default.read_bytes(), 'The default macro file') == remainder
                planned.append((self.macros_path, None if same else _json_bytes(remainder)))
        try:
            profile = _read_json(self.profile_path)
        except (OSError, ValueError):
            raise ValueError('The Paddock Crew Chief profile is not readable. Existing files were preserved.') from None
        if not isinstance(profile, dict) or not isinstance(profile.get('userSettings'), dict):
            raise ValueError('The Paddock Crew Chief profile is not readable. Existing files were preserved.')
        for key, value in receipt['profile_values'].items():
            if value == MISSING:
                profile['userSettings'].pop(key, None)
            else:
                profile['userSettings'][key] = value
        original = (folder / backups['profile.applied']['backup']).read_bytes()
        planned.append((self.profile_path, original if json.loads(original.decode('utf-8-sig')) == profile
                        else _json_bytes(profile)))
        current = [(path, path.read_bytes() if path.exists() else None) for path, _ in planned]
        try:
            for path, data in planned:
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    _write(path, data)
            self.settings.pop('replies_receipt', None)
            self._save()
        except Exception:
            for path, data in current:
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    _write(path, data)
            self.settings['replies_receipt'] = receipt
            raise

    def restore_replies(self):
        with self.lock:
            self._require_closed()
            self._restore_replies()
            return self.status()

    def _replies_status(self):
        receipt = self.settings.get('replies_receipt') or {}
        method = receipt.get('method') or ('command-v1' if receipt else None)
        listener = self._reply_listener
        return {'configured': bool(receipt), 'method': method,
                'needs_update': bool(receipt) and method != REPLY_METHOD,
                'listening': bool(listener and listener.is_alive()),
                'error': listener.error if listener and not listener.is_alive() else None,
                'phrases': [{'token': t, 'phrases': list(p), 'keys': [PREFIX_KEY, REPLY_KEYS[t]]} for t, p in REPLY_MACROS]}

    def _on_reply_key(self, scan, vk, down, t):
        token = self._reply_decoder.feed(scan, vk, down, t)
        if token:
            with self._reply_lock:
                self._reply_tokens = (self._reply_tokens + [token])[-8:]

    def _stop_reply_listener(self):
        with self._reply_lock:
            listener, self._reply_listener = self._reply_listener, None
            self._reply_tokens = []
        if listener is not None:
            listener.stop()

    def close(self):
        """Stop the keyboard listener (the radio host stops with stop())."""
        self._stop_reply_listener()

    def poll_replies(self):
        """New voice-reply tokens since the last poll, oldest first. Only replies given while
        Paddock is listening count: an answer is for the question that is current."""
        receipt = self.settings.get('replies_receipt')
        if not receipt:
            return []
        if receipt.get('method') != REPLY_METHOD:
            return self._poll_reply_file()
        now = time.monotonic()
        with self._reply_lock:
            listener = self._reply_listener
            if sys.platform == 'win32' and (listener is None or not listener.is_alive()) and now >= self._reply_retry_at:
                self._reply_retry_at = now + 30          # a failed listener is retried, not hammered
                self._reply_tokens = []
                self._reply_listener = RawKeyListener(self._on_reply_key)
                self._reply_listener.start()
            tokens, self._reply_tokens = self._reply_tokens, []
        return tokens

    def _poll_reply_file(self):
        """Version 1 (until the setup is updated): tokens appended to the reply file by a command."""
        path = self.dir / LEGACY_REPLY_FILE
        with self._reply_lock:
            try:
                size = path.stat().st_size
            except OSError:
                return []
            if self._reply_offset is None:
                self._reply_offset = size
                return []
            if size < self._reply_offset:
                self._reply_offset = 0
            if size == self._reply_offset:
                return []
            try:
                with path.open('rb') as handle:
                    handle.seek(self._reply_offset)
                    data = handle.read(min(size - self._reply_offset, 4096))
            except OSError:
                return []
            end = data.rfind(b'\n')
            if end < 0:
                return []  # the line is still being written
            self._reply_offset += end + 1
            tokens = [line.strip().decode('ascii', 'replace').lower() for line in data[:end].split(b'\n')]
            return [t for t in tokens if t in REPLY_TOKENS][-8:]

    # ------------------------------------------------------------------ Paddock speaks, Crew Chief spots
    def _profile(self):
        try:
            profile = _read_json(self.profile_path)
        except (OSError, ValueError):
            raise ValueError('The Paddock Crew Chief profile is not readable. Existing files were preserved.') from None
        if not isinstance(profile, dict) or not isinstance(profile.get('userSettings'), dict):
            raise ValueError('The Paddock Crew Chief profile is not readable. Existing files were preserved.')
        return profile

    def prepare_spotter_only(self):
        """Explicit opt-in, Crew Chief closed: turn off Crew Chief's lap-time, temperature, fuel,
        tyre-wear and pace calls in the Paddock profile only. Its spotter and everything else stay."""
        with self.lock:
            self._require_closed()
            if not self.settings.get('receipt'):
                raise ValueError('Set up the Paddock connection first.')
            if self.settings.get('spotter_receipt'):
                return self.status()
            original = self.profile_path.read_bytes()
            profile = self._profile()
            prefs = profile['userSettings']
            values = {key: prefs.get(key, MISSING) for key in SPOTTER_ONLY}
            prefs.update(SPOTTER_ONLY)
            folder = self.dir / 'backups' / (datetime.now().strftime('%Y%m%d-%H%M%S-spotter-') + uuid.uuid4().hex[:8])
            folder.mkdir(parents=True)
            (folder / 'profile.original').write_bytes(original)
            receipt = {'directory': folder.relative_to(self.dir).as_posix(), 'profile_values': values,
                       'original_sha256': _digest(original)}
            _write(folder / 'receipt.json', _json_bytes(receipt))
            _write(self.profile_path, _json_bytes(profile))
            try:
                self.settings['spotter_receipt'] = receipt
                self._save()
            except Exception:
                _write(self.profile_path, original)
                self.settings.pop('spotter_receipt', None)
                raise
            return self.status()

    def _restore_spotter_only(self):
        receipt = self.settings.get('spotter_receipt')
        if not receipt:
            raise ValueError("Crew Chief's own calls are not switched off.")
        profile = self._profile()
        for key, value in receipt['profile_values'].items():
            if value == MISSING:
                profile['userSettings'].pop(key, None)
            else:
                profile['userSettings'][key] = value
        folder = (self.dir / receipt['directory']).resolve()
        backup = folder / 'profile.original'
        exact = (folder.is_relative_to((self.dir / 'backups').resolve()) and backup.is_file()
                 and _digest(backup.read_bytes()) == receipt['original_sha256']
                 and json.loads(backup.read_bytes().decode('utf-8-sig')) == profile)
        _write(self.profile_path, backup.read_bytes() if exact else _json_bytes(profile))
        self.settings.pop('spotter_receipt', None)
        self._save()

    def restore_spotter_only(self):
        with self.lock:
            self._require_closed()
            self._restore_spotter_only()
            return self.status()

    def restore(self):
        with self.lock:
            self._require_closed()
            receipt = self.settings.get('receipt')
            if not receipt:
                raise ValueError('There is no Paddock connection to restore.')
            if self.settings.get('spotter_receipt'):
                self._restore_spotter_only()
            if self.settings.get('replies_receipt'):
                self._restore_replies()
            folder = (self.dir / receipt['directory']).resolve()
            if not folder.is_relative_to((self.dir / 'backups').resolve()):
                raise ValueError('Backup path is outside the connection backup folder.')
            expected_paths = {self.mqtt_path.resolve(), self.profile_path.resolve()}
            if {Path(item['path']).resolve() for item in receipt['files']} != expected_paths:
                raise ValueError('Connection backup does not cover the expected settings files.')
            audio = self._audio_backup()
            audio_items = {Path(i['path']).resolve(): i for i in audio[1]} if audio else {}
            for item in receipt['files']:
                path = Path(item['path']).resolve()
                applied = (folder / item['applied']).resolve()
                if applied.parent != folder or _digest(applied.read_bytes()) != item['applied_sha256']:
                    raise ValueError('Connection backup is incomplete or changed.')
                expected_applied = applied
                if audio:
                    layer = audio_items[path]
                    if _read_json(audio[0] / layer['backup']) != _read_json(applied):
                        raise ValueError('Newer Crew Chief preferences existed before audio setup. Existing settings were preserved; restore manually to keep those changes.')
                    expected_applied = audio[0] / layer['applied']
                if path not in expected_paths or not path.is_file() or _read_json(path) != _read_json(expected_applied):
                    raise ValueError('Crew Chief settings changed after connection setup. Existing files and backups were preserved; restore them manually to keep your newer changes.')
                if item['backup'] and (folder / item['backup']).resolve().parent != folder:
                    raise ValueError('Invalid backup file path.')
                if item['backup'] and not (folder / item['backup']).is_file():
                    raise ValueError('Connection backup is missing. Existing settings were preserved.')
                if item['backup'] and _digest((folder / item['backup']).read_bytes()) != item['original_sha256']:
                    raise ValueError('Connection backup changed. Existing settings were preserved.')
            self.stop(persist=False)
            current = [(Path(item['path']), Path(item['path']).read_bytes()) for item in receipt['files']]
            previous = dict(self.settings)
            try:
                for item in receipt['files']:
                    path = Path(item['path'])
                    if item['backup']:
                        _write(path, (folder / item['backup']).read_bytes())
                    else:
                        path.unlink()
                self.settings = {'exe': str(self.exe), 'port': self.settings.get('port', PORT), 'enabled': False}
                self._save()
            except Exception:
                for path, data in current:
                    _write(path, data)
                self.settings = previous
                raise
            return self.status()

    def route(self, method, path, body):
        if method == 'GET' and path == '/api/crew-chief':
            return self.status()
        if method == 'POST':
            if not isinstance(body, dict):
                raise ValueError('Crew Chief requests must be JSON objects.')
            actions = {'configure': lambda: self.configure(body), 'start': lambda: (self.start(), self.status())[1],
                       'stop': lambda: (self.stop(), self.status())[1], 'launch': self.launch, 'test': self.test,
                       'heard': lambda: self.heard(body.get('id')), 'restore': self.restore,
                       'prepare-audio': self.prepare_audio, 'prepare-replies': self.prepare_replies,
                       'restore-replies': self.restore_replies, 'prepare-spotter-only': self.prepare_spotter_only,
                       'restore-spotter-only': self.restore_spotter_only}
            action = path.rsplit('/', 1)[-1]
            if action in actions:
                return actions[action]()
        raise LookupError('Unknown Crew Chief request.')
