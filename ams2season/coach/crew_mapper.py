"""Original AMS2 mapper foundation, used by the live shared event core.

The C# struct has ABI differences from the verified AMS2 header. Bridge by named
fields; never marshal its memory layout over the game's bytes. Complete actual
snapshots are required: the reduced coach Tick/old recordings cannot provide all
the original mapper's inputs and must not be filled with invented values.
"""
from __future__ import annotations

import base64
import ctypes as C
import json
import math

from .. import shm as S
from .crew_spotter import ASSETS, Spotter

DEFAULTS = json.loads((ASSETS / 'mapper_defaults.json').read_text(encoding='utf-8'))
# Original MMF-only spellings and flattened arrays retain their exact semantics.
ALIASES = {'mParticipantData': 'mParticipantInfo', **{
    'mmfOnly_' + name: name for name in (
        'mNumSectors', 'mBestLapTime', 'mCurrentTime', 'mCurrentSector1Time',
        'mCurrentSector2Time', 'mCurrentSector3Time', 'mFastestSector1Time',
        'mFastestSector2Time', 'mFastestSector3Time')}}
COMPOUNDS = ('mLFTyreCompoundName', 'mRFTyreCompoundName', 'mLRTyreCompoundName', 'mRRTyreCompoundName')


def _value(value):
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(value).decode('ascii')
    if isinstance(value, C.Structure):
        out = {}
        for name, typ in value._fields_:
            item = getattr(value, name)
            if issubclass(typ, C.Array) and typ._type_ is C.c_char:
                item = C.string_at(C.addressof(value) + getattr(type(value), name).offset, C.sizeof(typ))
            out[name] = _value(item)
        return out
    if isinstance(value, C.Array):
        if value._type_ is C.c_char:
            return _value(bytes(value))
        return [_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Non-finite AMS2 snapshot field')
    return value


def snapshot_payload(snapshot):
    """Map every native input by name, with exact byte/array widths and no scaling."""
    if not isinstance(snapshot, S.SharedMemory):
        raise TypeError('Original mapper requires a complete AMS2 SharedMemory snapshot')
    data = _value(snapshot)
    for target, source in ALIASES.items():
        data[target] = data.pop(source)
    # Native class/car names and orientations are flat contiguous arrays.
    for name in ('mCarNames', 'mCarClassNames'):
        data[name] = base64.b64encode(b''.join(bytes(row) for row in getattr(snapshot, name))).decode('ascii')
    data['mOrientations'] = [float(v) for row in snapshot.mOrientations for v in row]
    data['mLapsInvalidated'] = _value(bytes(snapshot.mLapsInvalidated))
    data.pop('mTyreCompound')
    for index, name in enumerate(COMPOUNDS):
        data[name] = _value(bytes(snapshot.mTyreCompound[index]))
    # Source declares these two button masks as bytes; mapper never uses them.
    # Preserve its type without shifting subsequent real ABS/ERS/clutch fields.
    for name in ('mJoyPad0', 'mDPad'):
        data[name] &= 0xff
    return data


class Mapper(Spotter):
    host_script = 'mapper_host.ps1'
    host_name = 'mapper'
    defaults_file = 'mapper_defaults.json'
    request_timeout = .5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.settings = dict(DEFAULTS)
        self.state = 'not_started'
        self.data_error = None
        self._last_ticks = None
        if self.root is not None:
            from ..crew_chief import discover_exe, documents_folder
            installation = discover_exe()
            if installation:
                from pathlib import Path
                self.settings['__paddock_installation'] = str(Path(installation).parent)
            try:
                profile = json.loads((documents_folder() / 'CrewChiefV4/Profiles/Paddock.json').read_text(encoding='utf-8-sig'))['userSettings']
                for name, default in DEFAULTS.items():
                    value = profile.get(name)
                    if (isinstance(value, (bool, str, int, float))
                            and (not isinstance(value, float) or math.isfinite(value))):
                        self.settings[name] = str(value)
            except (OSError, ValueError, KeyError, TypeError):
                pass

    def map_snapshot(self, snapshot, *, ticks, local_slot, sample_age, fresh=True, allow_pregrid=False):
        """Explicit freshness/identity gate; returns diagnostic state, never calls."""
        if not isinstance(snapshot, S.SharedMemory):
            raise TypeError('A complete AMS2 snapshot is required')
        valid = (fresh and type(ticks) is int and 0 < ticks < 3155378976000000000
                 and isinstance(sample_age, (int, float)) and math.isfinite(sample_age) and 0 <= sample_age <= .25
                 and snapshot.mVersion >= 14 and snapshot.mSequenceNumber % 2 == 0
                 and (snapshot.mGameState == S.GAME_INGAME_PLAYING or allow_pregrid and snapshot.mGameState == S.GAME_INGAME_INMENU_TIME_TICKING)
                 and snapshot.mSessionState in (S.SESSION_PRACTICE, S.SESSION_TEST, S.SESSION_QUALIFY, S.SESSION_RACE, S.SESSION_FORMATION_LAP, S.SESSION_TIME_ATTACK)
                 and type(local_slot) is int and 0 <= local_slot < snapshot.mNumParticipants <= S.STORED_PARTICIPANTS_MAX
                 and snapshot.mViewedParticipantIndex == local_slot
                 and snapshot.mParticipantInfo[local_slot].mIsActive
                 and math.isfinite(snapshot.mTrackLength) and snapshot.mTrackLength > 0
                 and (self._last_ticks is None or ticks > self._last_ticks))
        if not valid:
            self.state = 'withheld_invalid_or_stale_snapshot'
            return None
        try:
            raw=snapshot_payload(snapshot)
        except ValueError as exc:
            self.data_error=str(exc)
            self.state='withheld_invalid_snapshot'
            return None
        self.data_error=None
        try:
            result = self._request({'op': 'map', 'ticks': ticks, 'raw': raw})
            if result is None:
                self.state = 'starting' if not self.error else 'error'
                return None
            if result.get('error'):
                raise ValueError(result['error'])
            self._last_ticks = ticks
            self.state = 'mapped' if result.get('mapped') else 'unchanged'
            return result
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self.state = 'error'
            self.close()
            return None

    def reset_mapping(self):
        """Explicit replay restart; monotonic-sample protection remains on by default."""
        result = self._request({'op': 'reset'})
        if result and result.get('reset'):
            self._last_ticks = None
            self.state = 'reset'
            return True
        return False
