"""Wheel and button-box buttons for talking to the engineer (Windows game controllers).

Reads controller buttons passively through Windows' joystick API (winmm joyGetPosEx), the
same buttons a game sees, 50 times a second. Nothing is sent to the game or blocked. A
button is remembered by the controller's maker/product IDs and its number, so it still
works when Windows numbers the controllers differently another day. The first 32
physical buttons and the controller's four POV-hat directions are available.

Roles: 'ptt' (hold to talk; speech is recognised while it is held) and direct answers
('confirm', 'negative', 'plan', 'progress', 'debrief', 'recon').
"""
from __future__ import annotations

from collections import deque
import ctypes
import sys
import threading
import time

ROLES = ('ptt', 'confirm', 'negative', 'plan', 'progress', 'debrief', 'recon',
         'overlay_previous', 'overlay_next', 'overlay_up', 'overlay_down', 'overlay_confirm', 'overlay_toggle',
         'skill_previous', 'skill_next', 'skill_toggle')
MAX_CONTROLLERS = 16
POLL_S = .02


def binding(value):
    """A saved button: {'mid', 'pid', 'button', 'label'} or None."""
    if not isinstance(value, dict):
        return None
    try:
        mid, pid, button = int(value['mid']), int(value['pid']), int(value['button'])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= mid <= 0xFFFF and 0 <= pid <= 0xFFFF and 1 <= button <= 36):
        return None
    label = str(value.get('label') or '')[:80]
    return {'mid': mid, 'pid': pid, 'button': button, 'label': label}


class WinmmControllers:
    """Snapshot of every connected controller: {id: (mid, pid, name, buttons_bitmask)}."""

    def __init__(self):
        from ctypes import wintypes
        self.winmm = ctypes.WinDLL('winmm')

        class JOYINFOEX(ctypes.Structure):
            _fields_ = [(name, wintypes.DWORD) for name in (
                'dwSize', 'dwFlags', 'dwXpos', 'dwYpos', 'dwZpos', 'dwRpos', 'dwUpos', 'dwVpos', 'dwButtons',
                'dwButtonNumber', 'dwPOV', 'dwReserved1', 'dwReserved2')]

        class JOYCAPSW(ctypes.Structure):
            _fields_ = [('wMid', wintypes.WORD), ('wPid', wintypes.WORD), ('szPname', wintypes.WCHAR * 32),
                        *[(name, wintypes.UINT) for name in (
                            'wXmin', 'wXmax', 'wYmin', 'wYmax', 'wZmin', 'wZmax', 'wNumButtons', 'wPeriodMin',
                            'wPeriodMax', 'wRmin', 'wRmax', 'wUmin', 'wUmax', 'wVmin', 'wVmax', 'wCaps', 'wMaxAxes',
                            'wNumAxes', 'wMaxButtons')],
                        ('szRegKey', wintypes.WCHAR * 32), ('szOEMVxD', wintypes.WCHAR * 260)]
        self.JOYINFOEX, self.JOYCAPSW = JOYINFOEX, JOYCAPSW
        self.caps = {}
        self.caps_at = 0.

    def _refresh_caps(self):
        caps = {}
        for i in range(MAX_CONTROLLERS):
            info = self.JOYCAPSW()
            if self.winmm.joyGetDevCapsW(i, ctypes.byref(info), ctypes.sizeof(info)) == 0:
                caps[i] = (info.wMid, info.wPid, info.szPname or f'Controller {i + 1}', bool(info.wCaps & 0x10))
        self.caps, self.caps_at = caps, time.monotonic()

    def read(self):
        if time.monotonic() - self.caps_at > 5:
            self._refresh_caps()              # controllers plugged in or out
        state = {}
        for i, (mid, pid, name, has_pov) in self.caps.items():
            info = self.JOYINFOEX(dwSize=ctypes.sizeof(self.JOYINFOEX), dwFlags=0x80 | (0x40 if has_pov else 0), dwPOV=0xFFFF)
            if self.winmm.joyGetPosEx(i, ctypes.byref(info)) == 0:
                buttons = int(info.dwButtons)
                state[i] = (mid, pid, name, with_pov(buttons, int(info.dwPOV)) if has_pov else buttons)
        return state


def with_pov(buttons, angle):
    """Reserve buttons 33..36 for Up/Right/Down/Left; diagonals choose one direction."""
    if 0 <= angle < 36000:
        direction = ((angle + 4500) // 9000) % 4
        buttons |= 1 << (32 + direction)
    return buttons


class ButtonWatch(threading.Thread):
    """Polls controller buttons; reports presses and releases of bound buttons, or captures the
    next press for binding. Events are drained by the coach thread."""

    def __init__(self, bindings=None, *, reader=None):
        super().__init__(name='paddock-radio-buttons', daemon=True)
        self.bindings = {role: b for role, b in (bindings or {}).items() if role in ROLES and binding(b)}
        self.reader = reader
        self.events = deque(maxlen=64)
        self.error = None
        self.capture = None            # (role, deadline)
        self.captured = None
        self.halt = threading.Event()
        self.previous = {}
        self.controllers = []        # names of the controllers Windows reports, for the setup screen
        self.lock = threading.Lock()

    def bind(self, bindings):
        with self.lock:
            self.bindings = {role: b for role, b in bindings.items() if role in ROLES and binding(b)}

    def start_capture(self, role, seconds=10.):
        if role not in ROLES:
            raise ValueError('Unknown button role.')
        with self.lock:
            self.capture, self.captured = (role, time.monotonic() + seconds), None

    def drain(self):
        out = []
        while self.events:
            out.append(self.events.popleft())
        return out

    def run(self):
        try:
            if self.reader is None:
                if sys.platform != 'win32':
                    raise OSError('Wheel buttons need Windows.')
                self.reader = WinmmControllers()
            while not self.halt.wait(POLL_S):
                self._step(self.reader.read())
        except Exception as exc:
            self.error = 'Wheel buttons are unavailable: ' + str(exc)[:200]

    def _step(self, state):
        now = time.monotonic()
        self.controllers = sorted({name for _, _, name, _ in state.values()})
        with self.lock:
            bindings = dict(self.bindings)
            capture = self.capture
        if capture and now > capture[1]:
            with self.lock:
                self.capture = None
            self.events.append({'event': 'capture_timeout', 'role': capture[0]})
            capture = None
        for index, (mid, pid, name, buttons) in state.items():
            before = self.previous.get((mid, pid, index), 0)
            pressed, released = buttons & ~before, before & ~buttons
            self.previous[(mid, pid, index)] = buttons
            for bit in range(36):
                mask = 1 << bit
                if not (pressed | released) & mask:
                    continue
                down = bool(pressed & mask)
                if capture and down:
                    label = f'{name} button {bit + 1}' if bit < 32 else f'{name} hat {("up","right","down","left")[bit-32]}'
                    found = {'mid': mid, 'pid': pid, 'button': bit + 1, 'label': label}
                    with self.lock:
                        self.capture, self.captured = None, (capture[0], found)
                    self.events.append({'event': 'captured', 'role': capture[0], 'binding': found})
                    capture = None
                    continue
                for role, b in bindings.items():
                    if b['mid'] == mid and b['pid'] == pid and b['button'] == bit + 1:
                        self.events.append({'event': 'down' if down else 'up', 'role': role, 't': now})

    def stop(self):
        self.halt.set()
