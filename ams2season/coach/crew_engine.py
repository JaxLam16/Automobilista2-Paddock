"""Original EngineMonitor, isolated from Crew Chief's UI/preferences/audio devices.

Temperature decisions and responses are original C#. AMS2's unsupported pressure
warning flags and stalled calls requiring unmapped health channels are withheld.
"""
from __future__ import annotations

import re

from .crew_spotter import Spotter
from .model import finite

COMMANDS = {
    'HOW_ARE_MY_ENGINE_TEMPS': ('how are my engine temps', 'how are my engine temperatures'),
    'WHAT_IS_MY_WATER_TEMP': ('whats my water temp', 'whats my water temperature'),
    'WHAT_IS_MY_OIL_TEMP': ('whats my oil temp', 'whats my oil temperature'),
    'WHAT_ARE_MY_ENGINE_TEMPS': ('what are my engine temps', 'what are my engine temperatures'),
}
FOLDERS = tuple('engine_monitor/'+name for name in
                ('all_clear', 'hot_water', 'hot_oil', 'hot_oil_and_water', 'oil_temp_intro', 'water_temp_intro', 'stalled'))


def command_for(text):
    key = ' '.join(re.sub(r"[^a-z0-9 ]", '', str(text).casefold().replace('’', "'")).split())
    return next((cmd for cmd, phrases in COMMANDS.items() if key in phrases), None)


class EngineMonitor(Spotter):
    host_script = 'engine_host.ps1'
    host_name = 'engine'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started_at = None
        self.last_payload = None
        self.state = 'waiting_for_telemetry'

    def limits(self, car_class):
        exact, wildcard = [], []
        import fnmatch
        for cls in self.sounds.classes:
            for name in cls.get('ams2ClassNames') or []:
                if name.casefold() == car_class.casefold():
                    exact.append(cls)
                elif fnmatch.fnmatchcase(car_class.casefold(), name.casefold()):
                    wildcard.append(cls)
        cls = (exact or wildcard or [{}])[0]
        # Original CarData.CarClass constructor defaults, not guessed thresholds.
        return (float(cls.get('maxSafeOilTemp') or 130), float(cls.get('maxSafeWaterTemp') or 115),
                bool(cls.get('isBatteryPowered', False)))

    @staticmethod
    def available(tick, player):
        age = finite(tick.local.get('local_sample_age_s'))
        return bool(tick.fresh and tick.game_state == 2 and player is not None
                    and player.slot == tick.viewed_slot and player.race_state in (2, 3)
                    and tick.session in ('practice', 'qualify', 'race', 'time_attack')
                    and age is not None and 0 <= age <= .25)

    def feed(self, tick, player, *, fahrenheit=False):
        changed = tick.session_id != self._session
        gap = self._last_t is not None and (tick.t <= self._last_t or tick.t-self._last_t > .5)
        if changed or gap:
            self.reset()
        if changed or self.started_at is None:
            self.started_at = tick.t
        self._session, self._last_t = tick.session_id, tick.t
        self.last_payload = None
        oil, water, speed = (finite(tick.local.get(k)) for k in ('oil_c','water_c','speed'))
        if not self.available(tick, player) or any(v is None for v in (oil,water,speed)) or oil <= 0 or water <= 0:
            self.state = 'missing_or_inactive_telemetry'
            self.reset()
            return []
        oil_limit, water_limit, battery = self.limits(player.car_class)
        payload = {'reset':self._reset, 't':tick.t, 'running_s':tick.t-self.started_at,
                   'session':{'practice':'Practice','qualify':'Qualify','race':'Race','time_attack':'HotLap'}[tick.session],
                   'oil_c':oil, 'water_c':water, 'oil_pressure':finite(tick.local.get('oil_pressure_kpa'),0),
                   'oil_limit':oil_limit, 'water_limit':water_limit, 'battery':battery,
                   'speed':speed, 'pit':player.pit != 0, 'fahrenheit':bool(fahrenheit)}
        result = self._send(payload)
        if result is None:
            self.state = 'starting' if not self.error else 'host_error'
            return []
        self._reset = False
        self.last_payload = payload
        self.state = 'monitoring' if payload['running_s'] > 120 else 'warming_up'
        return result

    def _send(self, payload):
        try:
            result = self._request(payload)
            if result and result.get('error'):
                self.error = result['error']
                return None
            return result.get('calls', []) if result is not None else None
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self.close()
            return None

    def respond(self, command):
        if command not in COMMANDS or self.last_payload is None:
            return []
        # Responses must not re-sample the temperature average.
        return self._send({**self.last_payload, 'reset':False, 'command':command}) or []
