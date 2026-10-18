"""Private automatic-radio preferences. Never write the installed CC profile.

Changes are staged until the next coach Start: original events read many values
at construction, and replacing them mid-session would lose their history.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from .catalogue import CATALOGUE


# Only settings consumed by connected event paths belong here. A family mute is
# independent of the original switch so requested replies remain available.
FAMILIES = {
    'fuel': ('Fuel', 'Fuel', 'enable_fuel_messages'),
    'lap_times': ('Lap times, sector deltas and pace', 'LapTimes', None),
    'gaps': ('Gaps and pressure', 'Timings', 'enable_gap_messages'),
    'position': ('Position, passes and start feedback', 'Position', 'enable_position_messages'),
    'laps': ('Race starts and remaining laps', 'LapCounter', None),
    'finish': ('Session finish and congratulations', 'SessionEndMessages', 'enable_session_end_messages'),
    'pits': ('Pit stops and mandatory windows', 'PitStops', None),
    'race_time': ('Race time', 'RaceTime', None),
    'engine': ('Engine monitoring', 'EngineMonitor', None),
    'tyres': ('Tyres, brakes and wheel slip', 'TyreMonitor', None),
    'damage': ('Damage and crash checks', 'DamageReporting', 'enable_damage_messages'),
    'weather': ('Weather and temperatures', 'ConditionsMonitor', 'enable_track_and_air_temp_reports'),
    'flags': ('Basic flag calls', 'FlagsMonitor', None),
    'penalties': ('Penalties and track limits', 'Penalties', None),
}

# (family, label, minimum, maximum); None bounds mean an original boolean.
NATIVE = {
    'frequency_of_player_prac_and_qual_lap_time_reports': ('lap_times', 'Practice / qualifying lap-time frequency', 0, 10),
    'frequency_of_player_race_lap_time_reports': ('lap_times', 'Race lap-time frequency', 0, 10),
    'frequency_of_prac_and_qual_sector_delta_reports': ('lap_times', 'Practice / qualifying sector delta frequency', 0, 10),
    'frequency_of_race_sector_delta_reports': ('lap_times', 'Race sector delta frequency', 0, 10),
    'practice_and_qual_sector_reports_at_each_sector': ('lap_times', 'Practice / qualifying sectors at each sector', None, None),
    'practice_and_qual_sector_reports_at_lap_end': ('lap_times', 'Practice / qualifying sectors at lap end', None, None),
    'race_sector_reports_at_each_sector': ('lap_times', 'Race sectors at each sector', None, None),
    'race_sector_reports_at_lap_end': ('lap_times', 'Race sectors at lap end', None, None),
    'report_all_laps_in_hotlap_mode': ('lap_times', 'Every lap in hotlap mode', None, None),
    'disable_pcars_prac_and_qual_pole_deltas': ('lap_times', 'Disable pCARS-family practice / qualifying pole deltas', None, None),
    'enable_fuel_messages': ('fuel', 'Original fuel updates', None, None),
    'enable_gap_messages': ('gaps', 'Original gap updates', None, None),
    'frequency_of_gap_ahead_reports': ('gaps', 'Gap ahead frequency', 0, 10),
    'frequency_of_gap_behind_reports': ('gaps', 'Gap behind frequency', 0, 10),
    'frequency_of_gap_behind_on_track_reports': ('gaps', 'Behind on track frequency', 0, 10),
    'enable_position_messages': ('position', 'Original position updates', None, None),
    'enable_race_start_messages': ('position', 'Start performance feedback', None, None),
    'frequency_of_overtaking_messages': ('position', 'Completed pass frequency', 0, 10),
    'frequency_of_being_overtaken_messages': ('position', 'Being passed frequency', 0, 10),
    'enable_green_light_messages': ('laps', 'Green light call', None, None),
    'enable_session_end_messages': ('finish', 'Finish result call', None, None),
    'enable_damage_messages': ('damage', 'Original damage reports', None, None),
    'enable_brake_damage_messages': ('damage', 'Brake damage reports', None, None),
    'enable_suspension_damage_messages': ('damage', 'Suspension damage reports', None, None),
    'enable_crash_messages': ('damage', 'Crash checks', None, None),
    'enable_tyre_temp_warnings': ('tyres', 'Tyre temperature warnings', None, None),
    'enable_tyre_wear_warnings': ('tyres', 'Tyre wear warnings', None, None),
    'enable_brake_temp_warnings': ('tyres', 'Brake temperature warnings', None, None),
    'enable_brake_lock_warnings': ('tyres', 'Wheel locking warnings', None, None),
    'enable_wheel_spin_warnings': ('tyres', 'Wheel spin warnings', None, None),
    'enable_track_and_air_temp_reports': ('weather', 'Air and track temperature updates', None, None),
    'ambient_temp_check_interval_seconds': ('weather', 'Air temperature check interval (seconds)', 1, 3600),
    'track_temp_check_interval_seconds': ('weather', 'Track temperature check interval (seconds)', 1, 3600),
    'enable_blue_flag_messages': ('flags', 'Blue flag calls', None, None),
    'enable_yellow_flag_messages': ('flags', 'Yellow flag calls', None, None),
}


def empty():
    return {'families': {}, 'native': {}, 'paddock': {}}


def validate(value):
    if not isinstance(value, dict) or set(value) - {'families', 'native', 'paddock'}:
        raise ValueError('Unknown automatic-call preferences.')
    out = empty()
    for group, allowed in (('families', FAMILIES), ('native', NATIVE), ('paddock', CATALOGUE)):
        entries = value.get(group, {})
        if not isinstance(entries, dict) or set(entries) - set(allowed):
            raise ValueError('Unknown ' + group + ' call control.')
        for key, setting in entries.items():
            if setting is None:
                continue
            if group == 'native':
                _, _, lo, hi = NATIVE[key]
                if (lo is None and type(setting) is not bool or lo is not None
                        and (type(setting) is not int or not lo <= setting <= hi)):
                    raise ValueError('Invalid original setting: ' + key)
                out[group][key] = setting
            else:
                if not isinstance(setting, dict) or set(setting) - {'enabled', 'min_interval_s'}:
                    raise ValueError('Invalid call options: ' + key)
                enabled, interval = setting.get('enabled', True), setting.get('min_interval_s', 0)
                if type(enabled) is not bool or type(interval) is not int or not 0 <= interval <= 3600:
                    raise ValueError('Call options need an on/off switch and a 0–3600 second minimum interval.')
                if group == 'paddock' and key in ('V-24', 'V-25'):
                    raise ValueError('Requested answers and recon calls are controlled by the driver, not automatic-call settings.')
                if not enabled or interval:
                    out[group][key] = {'enabled': enabled, 'min_interval_s': interval}
    return out


class CallControls:
    def __init__(self, root):
        self.path = Path(root) / 'private_coach' / 'call_preferences.json'
        self.saved = empty()
        self.revision = 0
        self.error = None
        try:
            if self.path.is_file():
                raw = json.loads(self.path.read_text(encoding='utf-8'))
                if raw.get('version') != 1 or type(raw.get('revision')) is not int or raw['revision'] < 0:
                    raise ValueError('Invalid automatic-call preference version or revision.')
                self.saved = validate(raw['overrides'])
                self.revision = raw['revision']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = 'Automatic-call preferences could not be loaded: ' + str(exc)
        self.active = deepcopy(self.saved)
        self.base = {}
        self._session = None
        self.last_native = {}

    def save(self, body):
        if type(body.get('revision')) is not int or body['revision'] != self.revision:
            raise ValueError('Call preferences changed. Refresh the page before saving.')
        if set(body) - {'revision', 'overrides', 'preset'} or ('overrides' in body) == ('preset' in body):
            raise ValueError('Choose call overrides or one preset.')
        if 'preset' in body:
            preset = body['preset']
            if preset == 'inherit':
                values = empty()
            elif preset == 'less_chatter':
                values = {'families': {k: {'enabled': True, 'min_interval_s': 120}
                          for k in ('gaps', 'position', 'weather')}, 'native': {},
                          'paddock': {k: {'enabled': True, 'min_interval_s': 180}
                          for k, spec in CATALOGUE.items() if spec.category in ('coaching', 'racecraft')}}
            else:
                raise ValueError('Unknown automatic-call preset.')
        else:
            values = body['overrides']
        values = validate(values)
        payload = {'version': 1, 'private': True, 'revision': self.revision + 1, 'overrides': values}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        temporary.replace(self.path)
        self.saved, self.revision, self.error = values, payload['revision'], None

    def activate(self, core, events):
        """Run only before starting new original hosts, never reset a running host."""
        self.active = deepcopy(self.saved)
        self.base = {k: core.settings[k] for k in NATIVE}
        self.last_native.clear()
        self._session = None
        for key, value in self.active['native'].items():
            core.settings[key] = str(value)
            if key in events.settings:
                events.settings[key] = value

    def family_for(self, call):
        source = call.get('source_event', '').removesuffix('_4.19.5.4')
        return next((k for k, (_, event, _) in FAMILIES.items() if event == source), None)

    def native_reason(self, call, session_id, t):
        # A real native reply is not an automatic call, even when its source is
        # muted or throttled. Immediate critical warnings are still automatic.
        if self.requested(call):
            return None
        if session_id != self._session:
            self._session, self.last_native = session_id, {}
        family = self.family_for(call)
        options = self.active['families'].get(family, {})
        if options.get('enabled') is False:
            return 'automatic_call_disabled'
        before = self.last_native.get(family)
        if before is not None and 0 <= t - before < options.get('min_interval_s', 0):
            return 'automatic_call_interval'
        return None

    def native_submitted(self, call, session_id, t):
        if not self.requested(call):
            if session_id != self._session:
                self._session, self.last_native = session_id, {}
            family = self.family_for(call)
            if family:
                self.last_native[family] = t

    @staticmethod
    def requested(call):
        # The separate original penalty host does not have a voice-response enum.
        # Preserve explicit driver origin independently of its transport metadata.
        return call.get('requested') is True or call.get('sound_type') == 'VOICE_COMMAND_RESPONSE'

    def status(self, running, core, events, rules, *, standalone=False):
        base = self.base
        native = []
        for key, (family, label, lo, hi) in NATIVE.items():
            raw = base[key]
            inherited = str(raw).lower() == 'true' if lo is None else int(raw)
            native.append({'key': key, 'family': family, 'label': label,
                           'type': 'boolean' if lo is None else 'integer', 'min': lo, 'max': hi,
                           'imported': inherited, 'active': self.active['native'].get(key, inherited)})
        managed={}
        if standalone and hasattr(core,'lap_times_state'):
            managed.update({'C-35':'lap_times','C-30':'lap_times'})
        if standalone and hasattr(core,'tyres_state'):
            managed.update({k:'tyres' for k in ('W-02','W-05','M-02','M-10')})
        return {'managed_by_original':managed, 'revision': self.revision, 'saved': deepcopy(self.saved), 'active': deepcopy(self.active),
                'pending': running and self.saved != self.active, 'error': self.error,
                'applies': 'next_coach_start', 'families': [
                    {'id': key, 'label': label, 'primary_setting': primary}
                    for key, (label, _, primary) in FAMILIES.items()],
                'native': native, 'paddock': [r for r in rules if r['id'] not in ('V-24', 'V-25') and r['id'] not in managed],
                'protected': ['Requested answers', 'Driver-requested recon laps', 'Spotter uses its own switch'],
                'note': 'Automatic calls only. Original triggers, freshness and workload rules still apply. '
                        'Minimum intervals can reduce chatter; they do not create more reports. '
                        'Changes apply on the next Stop/Start of the live coach; the recorder is not restarted.'}
