"""Sanitize actual snapshots and recorded rows into the same coaching input."""
from __future__ import annotations

import math

from .model import Car, Tick, count, finite
from .. import shm as S


def session_name(value):
    return {S.SESSION_PRACTICE: "practice", S.SESSION_TEST: "practice", S.SESSION_QUALIFY: "qualify",
            S.SESSION_RACE: "race", S.SESSION_FORMATION_LAP: "formation",
            S.SESSION_TIME_ATTACK: "time_attack"}.get(value, "invalid")


def valid_float(value, lo=None, hi=None):
    value = finite(value)
    return value if value is not None and (lo is None or value >= lo) and (hi is None or value <= hi) else None


def enum(value, choices):
    value = finite(value)
    return int(value) if value is not None and value in choices else -1


def gear_value(value):
    """AMS2 gear: -1 reverse, 0 neutral (also reported mid-shift), 1+ forward; else unknown."""
    value = finite(value)
    return int(value) if value is not None and value == int(value) and -1 <= value <= 20 else None


WHEELS = ('fl', 'fr', 'rl', 'rr')


def wheel_temps(left, centre, right, whole):
    """Per-wheel surface temperature, degC: the mean across the tread (left, centre, right),
    else the game's single tyre temperature; None when unknown."""
    out = []
    for w in range(4):
        zones = [valid_float(v, -50, 400) for v in (left[w], centre[w], right[w])] if left and centre and right else []
        zones = [v for v in zones if v is not None and v != 0]
        value = sum(zones) / len(zones) if len(zones) == 3 else valid_float(whole[w] if whole else None, -50, 400)
        if value is None:
            return None
        out.append(value)
    return tuple(out)


def brake_temps(values):
    out = tuple(valid_float(v, -50, 2000) for v in values) if values else ()
    return out if len(out) == 4 and all(v is not None for v in out) else None


def race_settings(laps, duration, extra, remaining, version):
    # AMS2 v10+ recordings demonstrate SECONDS for both raw float fields,
    # despite the header/legacy recorder names saying minutes/milliseconds.
    # Do not apply those erroneous scale factors or reinterpret unknown versions.
    known = count(version) >= 10
    return {'race_laps':count(laps),
            'session_duration_s':valid_float(duration,0,604800) if known else None,
            'session_additional_laps':enum(extra,range(11)) if known else -1,
            'event_time_remaining_s':valid_float(remaining,-1,604800) if known else None}


def car_from_row(row):
    return Car(slot=count(row.get("slot")), name=str(row.get("name") or "").strip(),
               car=str(row.get("car") or ""), car_class=str(row.get("car_class") or ""),
               position=count(row.get("race_pos")), laps=count(row.get("laps_completed")),
               distance=valid_float(row.get("lap_dist"), 0), speed=valid_float(row.get("speed"), 0, 160),
               pit=enum(row.get("pit_mode"), range(6)), race_state=enum(row.get("race_state"), range(7)),
               invalid=row.get("lap_invalid") is not False,
               flag_colour=enum(row.get('flag_colour'), range(12)),
               x=valid_float(row.get('x'),-1e7,1e7),z=valid_float(row.get('z'),-1e7,1e7),
               last_lap=valid_float(row.get('last_lap'),1,3600),
               pit_schedule=enum(row.get('pit_schedule'),range(8)),sector=enum(row.get('sector'),range(3)))


def from_snapshot(snap, now, session_id):
    cars = []
    for i in range(max(0, min(int(snap.mNumParticipants), S.STORED_PARTICIPANTS_MAX))):
        p = snap.mParticipantInfo[i]
        if not p.mIsActive:
            continue
        cars.append(car_from_row({"slot": i, "name": S.cstr(p.mName), "car": S.cstr(snap.mCarNames[i]),
            "car_class": S.cstr(snap.mCarClassNames[i]), "race_pos": p.mRacePosition,
            "laps_completed": p.mLapsCompleted, "lap_dist": p.mCurrentLapDistance, "speed": snap.mSpeeds[i],
            "pit_mode": snap.mPitModes[i], "race_state": snap.mRaceStates[i],
            'pit_schedule':snap.mPitSchedules[i], 'sector':p.mCurrentSector,
            "lap_invalid": bool(snap.mLapsInvalidated[i]), 'flag_colour':snap.mHighestFlagColours[i],
            'x':p.mWorldPosition[0],'z':p.mWorldPosition[2],'last_lap':snap.mLastLapTimes[i]}))
    local = {"speed": valid_float(snap.mSpeed, 0, 160), "throttle": valid_float(snap.mThrottle, 0, 1),
             "brake": valid_float(snap.mBrake, 0, 1), "steering": valid_float(snap.mSteering, -1, 1),
             "gear": gear_value(snap.mGear),
             'orientation_yaw': valid_float(snap.mOrientation[1], -math.pi * 2, math.pi * 2),
             'world_velocity': (valid_float(snap.mWorldVelocity[0], -300, 300),
                                valid_float(snap.mWorldVelocity[2], -300, 300)),
             "rain_density": valid_float(snap.mRainDensity, 0, 1), "crash_state": int(snap.mCrashState),
             "local_lap_invalid": bool(snap.mLapInvalidated), "fuel_level": valid_float(snap.mFuelLevel, 0, 1),
             'yellow_flag_state':enum(snap.mYellowFlagState,range(9)),
             'pit_schedule':enum(snap.mPitSchedule,range(8)),
             'flag_colour':enum(snap.mHighestFlagColour,range(12)),
             'race_state':enum(snap.mRaceState,range(7)),
             "fuel_capacity": valid_float(snap.mFuelCapacity, 0, 2000), "game_state": int(snap.mGameState),
             'tyre_c': wheel_temps(list(snap.mTyreTempLeft), list(snap.mTyreTempCenter), list(snap.mTyreTempRight),
                                   list(snap.mTyreTemp)),
             'brake_c': brake_temps(list(snap.mBrakeTempCelsius)), 'compound': S.cstr(snap.mTyreCompound[0]),
             'water_c': valid_float(snap.mWaterTempCelsius, -50, 400), 'oil_c': valid_float(snap.mOilTempCelsius, -50, 400),
             'damage': {'aero': valid_float(snap.mAeroDamage, 0, 1), 'engine': valid_float(snap.mEngineDamage, 0, 1),
                        'suspension': [valid_float(v, 0, 1) for v in snap.mSuspensionDamage],
                        'brakes': [valid_float(v, 0, 1) for v in snap.mBrakeDamage]},
             'local_sample_age_s':0.}
    local.update(race_settings(snap.mLapsInEvent,snap.mSessionDuration,snap.mSessionAdditionalLaps,
                               snap.mEventTimeRemaining,snap.mVersion))
    return Tick(t=float(now), session_id=session_id, session=session_name(snap.mSessionState),
                track=S.cstr(snap.mTrackLocation), layout=S.cstr(snap.mTrackVariation),
                length=valid_float(snap.mTrackLength, 100, 100000) or 0,
                game_state=int(snap.mGameState), viewed_slot=int(snap.mViewedParticipantIndex),
                cars=tuple(c for c in cars if c.name and c.slot >= 0), local=local)


def from_recorded(meta, rows, local, session_id, t):
    local = dict(local or {})
    local.update(race_settings(meta.get('laps_in_event'),meta.get('session_duration_min'),
                              meta.get('session_additional_laps'),local.get('event_time_remaining_ms'),
                              meta.get('shm_version')))
    for key, lo, hi in (("speed", 0, 160), ("throttle", 0, 1), ("brake", 0, 1),
                        ("steering", -1, 1), ("rain_density", 0, 1), ("fuel_level", 0, 1),
                        ("fuel_capacity", 0, 2000)):
        local[key] = valid_float(local.get(key), lo, hi)
    local['gear'] = gear_value(local.get('gear'))  # absent in older recordings: no shift bridging
    if 'pit_schedule' in local:
        local['pit_schedule']=enum(local.get('pit_schedule'),range(8))
    if 'highest_flag_colour' in local:
        local['flag_colour']=enum(local.get('highest_flag_colour'),range(12))
    if 'local_race_state' in local:
        local['race_state']=enum(local.get('local_race_state'),range(7))
    local['orientation_yaw'] = valid_float(local.get('spotter_yaw'), -math.pi * 2, math.pi * 2)
    local['world_velocity'] = (valid_float(local.get('world_vx'), -300, 300),
                               valid_float(local.get('world_vz'), -300, 300))
    zones = [[local.get(f'{k}_{w}') for w in WHEELS] for k in ('tl', 'tc', 'tr', 'ttemp', 'btemp')]
    local['tyre_c'] = wheel_temps(*(z if any(v is not None for v in z) else None for z in zones[:4]))
    local['brake_c'] = brake_temps(zones[4] if any(v is not None for v in zones[4]) else None)
    local['water_c'], local['oil_c'] = valid_float(local.get('water_temp'), -50, 400), valid_float(local.get('oil_temp'), -50, 400)
    # Recordings keep aero, engine and the worst suspension/brake damage only (no per-wheel split).
    if local.get('aero_damage') is not None:
        local['damage'] = None
    # Past-only as-of match. Missing/stale local data suppresses decisions.
    stamp = finite(local.get("t"))
    fresh = stamp is not None and 0 <= t - stamp <= .25
    local['local_sample_age_s']=t-stamp if fresh else None
    return Tick(t=float(t), session_id=session_id, session=meta.get("session_type", "invalid"),
                track=meta.get("track_location", ""), layout=meta.get("track_variation", ""),
                length=valid_float(meta.get("track_length"), 100, 100000) or 0,
                game_state=enum(local.get("game_state"), range(8)), viewed_slot=count(local.get("viewed_slot")),
                cars=tuple(car_from_row(row) for row in rows), local=local, fresh=fresh)
