"""Headless recorder: polls shared memory, splits sessions automatically, writes raw frames.

Output per session (one folder):
    session.json   metadata + final snapshot
    events.jsonl   green flag (with grid), joins/leaves, race-state changes, local collisions
    frames.parquet one row per participant per tick (everyone, AI included)
    local.parquet  one row per tick for the car this PC is driving (damage, inputs, weather)

While recording, frames are flushed to frames_parts/ every `flush_s` seconds so a crash
loses at most that much; parts are compacted into single files when the session closes.

`Recorder.step(snapshot, now)` is pure with respect to time, so the simulator and tests
drive exactly the same code path as the live game.
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import __version__
from . import shm as S

FRAME_SCHEMA = pa.schema([
    ("t", pa.float64()), ("slot", pa.int16()), ("name", pa.string()),
    ("car", pa.string()), ("car_class", pa.string()),
    ("race_pos", pa.int16()), ("laps_completed", pa.int16()), ("current_lap", pa.int16()),
    ("lap_dist", pa.float32()), ("sector", pa.int8()),
    ("x", pa.float32()), ("y", pa.float32()), ("z", pa.float32()),
    ("speed", pa.float32()), ("race_state", pa.int8()), ("pit_mode", pa.int8()),
    ("pit_schedule", pa.int8()), ("lap_invalid", pa.bool_()),
    ("last_lap", pa.float32()), ("fastest_lap", pa.float32()),
    ("cur_s1", pa.float32()), ("cur_s2", pa.float32()), ("cur_s3", pa.float32()),
    ("flag_colour", pa.int8()), ("flag_reason", pa.int8()), ("nationality", pa.int64()),
    ("ox", pa.float32()), ("oy", pa.float32()), ("oz", pa.float32()),  # orientation (Euler angles)
])

TYRE_EXTRA = ("tl", "tc", "tr", "tread", "layer", "carc", "rim", "air", "ride", "susp")
# per-wheel dynamics for the race engineer: damper (pushrod) velocity and tyre height above the ground (wheel lift)
WHEEL_DYN = ("svel", "hag")
# whole-car channels for the race engineer
ENGINEER_COLS = (
    ("rpm", pa.float32()), ("max_rpm", pa.float32()), ("num_gears", pa.int8()), ("clutch", pa.float32()),
    ("engine_torque", pa.float32()), ("water_temp", pa.float32()), ("oil_temp", pa.float32()), ("oil_press", pa.float32()),
    ("fuel_capacity", pa.float32()), ("brake_bias", pa.float32()), ("abs_setting", pa.int8()), ("tc_setting", pa.int8()),
    ("abs_active", pa.bool_()), ("boost", pa.float32()),
    ("yaw_rate", pa.float32()), ("roll_rate", pa.float32()), ("pitch_rate", pa.float32()),   # rad/s (mAngularVelocity y, z, x)
    ("acc_lat", pa.float32()), ("acc_vert", pa.float32()), ("acc_long", pa.float32()),        # m/s2, car frame (mLocalAcceleration x, y, z)
    ("vel_lat", pa.float32()), ("vel_long", pa.float32()),                                   # m/s, car frame (slip angle)
)


def _k2c(v: float) -> float:
    """Kelvin to Celsius; the game leaves unset values at 0 K."""
    return v - 273.15 if v > 1.0 else float("nan")

LOCAL_SCHEMA = pa.schema([
    ("t", pa.float64()), ("game_state", pa.int8()), ("session_state", pa.int8()),
    ("race_state", pa.int8()), ("viewed_slot", pa.int16()), ("num_participants", pa.int16()),
    ("event_time_remaining_ms", pa.float32()), ("speed", pa.float32()),
    ("throttle", pa.float32()), ("brake", pa.float32()), ("steering", pa.float32()),
    ("gear", pa.int8()), ("crash_state", pa.int8()),
    ("aero_damage", pa.float32()), ("engine_damage", pa.float32()),
    ("susp_damage_max", pa.float32()), ("brake_damage_max", pa.float32()),
    ("last_collision_slot", pa.int16()), ("last_collision_mag", pa.float32()),
    ("lap_invalid", pa.bool_()), ("fuel_level", pa.float32()), ("tyre_wear_avg", pa.float32()),
    ("rain_density", pa.float32()), ("track_temp", pa.float32()), ("ambient_temp", pa.float32()),
    ("yellow_flag_state", pa.int8()),
    ("x", pa.float32()), ("z", pa.float32()), ("lap_dist", pa.float32()),  # the recording car itself
    ("terrain_fl", pa.int16()), ("terrain_fr", pa.int16()), ("terrain_rl", pa.int16()), ("terrain_rr", pa.int16()),
    # tyres of the recording car (the game only shares these for the local car)
    *[(f"{k}_{w}", pa.float32()) for k in ("wear", "ttemp", "press", "btemp", "rps") for w in ("fl", "fr", "rl", "rr")],
    # surface across the tread (the tyre's own left / centre / right, degC), the layers beneath it (degC),
    # ride height (cm) and suspension travel (m), all per wheel
    *[(f"{k}_{w}", pa.float32()) for k in TYRE_EXTRA for w in ("fl", "fr", "rl", "rr")],
    *[(f"{k}_{w}", pa.float32()) for k in WHEEL_DYN for w in ("fl", "fr", "rl", "rr")],
    *ENGINEER_COLS,
    ("compound", pa.string()), ("local_lap", pa.int16()), ("local_lap_invalid", pa.bool_()),
])

FRAME_COLUMNS = FRAME_SCHEMA.names
LOCAL_COLUMNS = LOCAL_SCHEMA.names

RECORDABLE_GAME_STATES = {S.GAME_INGAME_PLAYING, S.GAME_INGAME_PAUSED, S.GAME_INGAME_INMENU_TIME_TICKING}


TOP_BIT = 0x80000000


def _bounds(t: pa.DataType) -> tuple[int, int]:
    bits = t.bit_width
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def _to_table(buf: dict, schema: pa.Schema, note) -> pa.Table:
    """Build a table without ever raising on game data: integers outside the column's range
    become -1 (reported through `note`), floats overflow to inf, and a half-written trailing
    row is dropped."""
    n = min((len(v) for v in buf.values()), default=0)
    cols = []
    for f in schema:
        vals = buf[f.name][:n]
        if pa.types.is_integer(f.type):
            arr = np.asarray(vals, dtype=np.int64) if vals else np.zeros(0, np.int64)
            lo, hi = _bounds(f.type)
            bad = (arr < lo) | (arr > hi)
            if bad.any():
                note(f.name, int(arr[bad][0]), int(bad.sum()))
                arr = np.where(bad, -1, arr)
            cols.append(pa.array(arr.astype(f.type.to_pandas_dtype()), type=f.type))
        elif pa.types.is_floating(f.type):
            with np.errstate(over="ignore", invalid="ignore"):
                arr = np.asarray(vals, dtype=np.float64).astype(np.float32)
            cols.append(pa.array(arr, type=f.type))
        else:
            cols.append(pa.array(vals, type=f.type))
    return pa.Table.from_arrays(cols, schema=schema)


def session_type(session_state: int) -> str:
    return {
        S.SESSION_PRACTICE: "practice", S.SESSION_TEST: "practice",
        S.SESSION_QUALIFY: "qualify",
        S.SESSION_FORMATION_LAP: "race", S.SESSION_RACE: "race",
        S.SESSION_TIME_ATTACK: "time_attack",
    }.get(session_state, "invalid")


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:40] or "unknown"


@dataclass
class _Active:
    key: tuple
    path: Path
    t0: float
    meta: dict
    frames: dict = field(default_factory=lambda: {f.name: [] for f in FRAME_SCHEMA})
    local: dict = field(default_factory=lambda: {f.name: [] for f in LOCAL_SCHEMA})
    part: int = 0
    last_flush: float = 0.0
    last_ok: float = 0.0
    last_status: float = 0.0
    green_t: float | None = None
    prev_pos: dict = field(default_factory=dict)
    prev_states: dict = field(default_factory=dict)
    prev_names: set = field(default_factory=set)
    prev_session_state: int = -1
    prev_collision: tuple = (-1, 0.0)
    prev_crash: int = 0
    max_leader_laps: int = 0
    rows: int = 0
    ticks: int = 0
    last_participants: list = field(default_factory=list)
    out_of_range: dict = field(default_factory=dict)


class Recorder:
    def __init__(self, out_dir: str | Path, hz: float = 20.0,
                 sessions: tuple[str, ...] = ("race", "qualify", "practice"), label: str | None = None,
                 flush_s: float = 30.0, grace_s: float = 10.0, log=print,
                 wallclock=datetime.now):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.hz = hz
        self.sessions = set(sessions)
        self.label = label
        self.flush_s = flush_s
        self.grace_s = grace_s
        self.log = log
        self.wallclock = wallclock
        self.active: _Active | None = None
        self.completed: list[Path] = []
        self._version_warned = False
        self.game_connected = False
        self.game_state: int | None = None
        self.on_snapshot = None  # single listener (kept for compatibility)
        self.hooks: dict = {}    # named live listeners: the track mapper, the practice tracker

    # ------------------------------------------------------------------ public
    def status(self, now: float | None = None) -> dict:
        """Live state for a UI: is the game there, and what's being recorded."""
        now = time.perf_counter() if now is None else now
        a = self.active
        session = None
        if a:
            session = {"folder": a.path.name, "track": a.key[0], "layout": a.key[1], "type": a.key[2],
                       "elapsed_s": round(now - a.t0, 1), "cars": len(a.last_participants), "rows": a.rows,
                       "green": a.green_t is not None, "warnings": sorted(a.out_of_range)}
        return {"connected": self.game_connected, "game_state": self.game_state, "session": session,
                "completed": [p.name for p in self.completed]}

    def step(self, snap: S.SharedMemory | None, now: float) -> None:
        if snap is not None:
            for hook in list(self.hooks.values()) + ([self.on_snapshot] if self.on_snapshot else []):
                try:
                    hook(snap, now)
                except Exception:
                    pass
        self.game_connected = snap is not None and snap.mGameState != S.GAME_EXITED
        self.game_state = None if snap is None else int(snap.mGameState)
        if snap is not None and snap.mGameState == S.GAME_INGAME_RESTARTING:
            if self.active:
                self._end(now, "restart")
            return

        ok = (snap is not None and snap.mGameState in RECORDABLE_GAME_STATES
              and snap.mSessionState != S.SESSION_INVALID and snap.mTrackLength > 0
              and snap.mNumParticipants > 0)
        if not ok:
            if self.active and now - self.active.last_ok > self.grace_s:
                self._end(now, "left_session")
            return

        if not self._version_warned and snap.mVersion < S.SHARED_MEMORY_VERSION:
            self.log(f"[warn] game reports shared memory v{snap.mVersion}; this recorder expects "
                     f"v{S.SHARED_MEMORY_VERSION}+. Update AMS2 or check field mappings.")
            self._version_warned = True

        stype = session_type(snap.mSessionState)
        key = (S.cstr(snap.mTrackLocation), S.cstr(snap.mTrackVariation), stype)

        if self.active and (self.active.key != key or self._restarted(snap)):
            self._end(now, "session_change" if self.active.key != key else "restart")
        if stype not in self.sessions:
            return
        if not self.active:
            self._start(snap, now, key)

        a = self.active
        a.last_ok = now
        if snap.mGameState == S.GAME_INGAME_PAUSED:
            return  # single-player pause: don't write duplicate frames
        self._capture(snap, now)

    def close(self, now: float | None = None) -> None:
        if self.active:
            self._end(time.perf_counter() if now is None else now, "recorder_stopped")

    def run(self, reader, stop_event=None) -> None:
        """Live loop for the real game. Ctrl+C to stop."""
        period = 1.0 / self.hz
        self.log(f"[rec] waiting for AMS2 shared memory; writing to {self.out.resolve()}")
        next_t = time.perf_counter()
        last_err = -1e9
        try:
            while not (stop_event and stop_event.is_set()):
                now = time.perf_counter()
                snap = reader.snapshot()
                try:
                    self.step(snap, now)
                except Exception:
                    if now - last_err > 10:  # rate-limited, keep recording
                        last_err = now
                        self.log("[error] unexpected problem, recording continues:\n" + traceback.format_exc())
                if snap is None and not self.active:
                    time.sleep(1.0)
                    next_t = time.perf_counter()
                    continue
                next_t += period
                delay = next_t - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_t = time.perf_counter()
        except KeyboardInterrupt:
            pass
        finally:
            self.close()

    # ----------------------------------------------------------------- session
    def _restarted(self, snap: S.SharedMemory) -> bool:
        """Race restarts in MP don't always pass through GAME_INGAME_RESTARTING."""
        a = self.active
        if not a or a.key[2] != "race" or a.green_t is None:
            return False
        states, laps = [], []
        for i in range(S.STORED_PARTICIPANTS_MAX):
            p = snap.mParticipantInfo[i]
            if p.mIsActive:
                states.append(snap.mRaceStates[i])
                laps.append(p.mLapsCompleted)
        if states and all(s == S.RACESTATE_NOT_STARTED for s in states):
            return True
        # leader lap count going backwards by 2+ (a single drop can just be the leader leaving)
        return bool(laps) and max(laps) <= a.max_leader_laps - 2

    def _start(self, snap: S.SharedMemory, now: float, key: tuple) -> None:
        wall = self.wallclock()
        track, variation, stype = key
        path = self.out / f"{wall:%Y%m%d-%H%M%S}_{_slug(track)}_{_slug(variation)}_{stype}"
        n = 1
        while path.exists():
            n += 1
            path = path.with_name(f"{path.name}_{n}")
        (path / "frames_parts").mkdir(parents=True)
        (path / "local_parts").mkdir(parents=True)
        viewed = snap.mViewedParticipantIndex
        local_name = (S.cstr(snap.mParticipantInfo[viewed].mName)
                      if 0 <= viewed < S.STORED_PARTICIPANTS_MAX else "")
        meta = {
            "format": 1, "recorder_version": __version__, "label": self.label,
            "hostname": platform.node(), "hz": self.hz,
            "shm_version": snap.mVersion, "build_version": snap.mBuildVersionNumber,
            "started_at": wall.isoformat(timespec="seconds"), "session_type": stype,
            "track_location": track, "track_variation": variation,
            "track_location_translated": S.cstr(snap.mTranslatedTrackLocation),
            "track_variation_translated": S.cstr(snap.mTranslatedTrackVariation),
            "track_length": round(float(snap.mTrackLength), 2),
            "num_sectors": snap.mNumSectors, "laps_in_event": snap.mLapsInEvent,
            "session_duration_min": round(float(snap.mSessionDuration), 2),
            "session_additional_laps": snap.mSessionAdditionalLaps,
            "local": {"name": local_name, "car": S.cstr(snap.mCarName),
                      "car_class": S.cstr(snap.mCarClassName)},
            "status": "recording",
        }
        self.active = _Active(key=key, path=path, t0=now, meta=meta, last_flush=now,
                              last_ok=now, last_status=now)
        self._write_meta(self.active)
        self.log(f"[rec] started {stype} at {track} {variation} -> {path.name}")

    def _end(self, now: float, reason: str) -> None:
        a = self.active
        self.active = None
        if a is None:
            return
        self._flush(a)
        duration = now - a.t0
        if a.ticks < max(3 * self.hz, 10) and a.green_t is None:
            shutil.rmtree(a.path, ignore_errors=True)  # menu flicker, not a session
            return
        self._compact(a.path, "frames", FRAME_SCHEMA)
        self._compact(a.path, "local", LOCAL_SCHEMA)
        a.meta.update({
            "status": "complete", "end_reason": reason,
            "ended_at": self.wallclock().isoformat(timespec="seconds"),
            "duration_s": round(duration, 2), "green_t": a.green_t, "ticks": a.ticks,
            "final": a.last_participants,
        })
        self._write_meta(a)
        self.completed.append(a.path)
        self.log(f"[rec] closed {a.path.name} ({reason}, {duration/60:.1f} min, "
                 f"{len(a.last_participants)} cars, {a.rows:,} rows)")

    # ----------------------------------------------------------------- capture
    def _capture(self, snap: S.SharedMemory, now: float) -> None:
        a = self.active
        t = round(now - a.t0, 4)
        a.ticks += 1
        F = a.frames
        seen: dict[str, int] = {}
        participants = []
        slot_names = {}
        for i in range(S.STORED_PARTICIPANTS_MAX):
            p = snap.mParticipantInfo[i]
            if not p.mIsActive:
                continue
            name = S.cstr(p.mName)
            if not name:
                continue
            car = S.cstr(snap.mCarNames[i])
            if name in seen:  # duplicate display names (rare, AI pools): disambiguate by car
                name = f"{name} [{car or i}]"
            seen[name] = i
            slot_names[i] = name
            race_pos = self._count(a, "race_pos", p.mRacePosition, name)
            laps = self._count(a, "laps_completed", p.mLapsCompleted, name)
            cur_lap = self._count(a, "current_lap", p.mCurrentLap, name)
            race_state = self._enum(a, "race_state", snap.mRaceStates[i], name)
            row = (t, i, name, car, S.cstr(snap.mCarClassNames[i]),
                   race_pos, laps, cur_lap, p.mCurrentLapDistance,
                   self._enum(a, "sector", p.mCurrentSector, name),
                   p.mWorldPosition[0], p.mWorldPosition[1], p.mWorldPosition[2],
                   snap.mSpeeds[i], race_state,
                   self._enum(a, "pit_mode", snap.mPitModes[i], name),
                   self._enum(a, "pit_schedule", snap.mPitSchedules[i], name),
                   bool(snap.mLapsInvalidated[i]), snap.mLastLapTimes[i], snap.mFastestLapTimes[i],
                   snap.mCurrentSector1Times[i], snap.mCurrentSector2Times[i], snap.mCurrentSector3Times[i],
                   self._enum(a, "flag_colour", snap.mHighestFlagColours[i], name),
                   self._enum(a, "flag_reason", snap.mHighestFlagReasons[i], name),
                   snap.mNationalities[i],
                   snap.mOrientations[i][0], snap.mOrientations[i][1], snap.mOrientations[i][2])
            for col, v in zip(FRAME_COLUMNS, row):
                F[col].append(v)
            participants.append({
                "name": name, "car": car, "car_class": S.cstr(snap.mCarClassNames[i]), "race_pos": race_pos, "laps_completed": laps,
                "race_state": S.RACESTATE_NAMES.get(race_state, "?"),
                "fastest_lap": round(float(snap.mFastestLapTimes[i]), 3),
            })
        a.rows += len(participants)

        e = lambda field_, v: self._enum(a, field_, v, "(local)")
        local_row = (
            t, e("game_state", snap.mGameState), e("session_state", snap.mSessionState),
            e("local_race_state", snap.mRaceState), snap.mViewedParticipantIndex, snap.mNumParticipants,
            snap.mEventTimeRemaining, snap.mSpeed, snap.mThrottle, snap.mBrake, snap.mSteering,
            max(-1, min(127, snap.mGear)), e("crash_state", snap.mCrashState),
            snap.mAeroDamage, snap.mEngineDamage, max(snap.mSuspensionDamage), max(snap.mBrakeDamage),
            snap.mLastOpponentCollisionIndex, snap.mLastOpponentCollisionMagnitude,
            bool(snap.mLapInvalidated), snap.mFuelLevel, sum(snap.mTyreWear) / 4.0,
            snap.mRainDensity, snap.mTrackTemperature, snap.mAmbientTemperature,
            max(-1, min(127, snap.mYellowFlagState)),
            *self._local_pos(snap), *(int(snap.mTerrain[w]) if 0 <= snap.mTerrain[w] < 1000 else -1 for w in range(4)),
            *(snap.mTyreWear[w] for w in range(4)), *(snap.mTyreTemp[w] for w in range(4)),
            *(snap.mAirPressure[w] for w in range(4)), *(snap.mBrakeTempCelsius[w] for w in range(4)),
            *(snap.mTyreRPS[w] for w in range(4)),
            *(snap.mTyreTempLeft[w] for w in range(4)), *(snap.mTyreTempCenter[w] for w in range(4)),
            *(snap.mTyreTempRight[w] for w in range(4)), *(_k2c(snap.mTyreTreadTemp[w]) for w in range(4)),
            *(_k2c(snap.mTyreLayerTemp[w]) for w in range(4)), *(_k2c(snap.mTyreCarcassTemp[w]) for w in range(4)),
            *(_k2c(snap.mTyreRimTemp[w]) for w in range(4)), *(_k2c(snap.mTyreInternalAirTemp[w]) for w in range(4)),
            *(snap.mRideHeight[w] for w in range(4)), *(snap.mSuspensionTravel[w] for w in range(4)),
            *(snap.mSuspensionVelocity[w] for w in range(4)), *(snap.mTyreHeightAboveGround[w] for w in range(4)),
            snap.mRpm, snap.mMaxRPM, snap.mNumGears, snap.mClutch, snap.mEngineTorque,
            snap.mWaterTempCelsius, snap.mOilTempCelsius, snap.mOilPressureKPa, snap.mFuelCapacity,
            snap.mBrakeBias, snap.mAntiLockSetting, snap.mTractionControlSetting, bool(snap.mAntiLockActive), snap.mTurboBoostPressure,
            snap.mAngularVelocity[1], snap.mAngularVelocity[2], snap.mAngularVelocity[0],
            snap.mLocalAcceleration[0], snap.mLocalAcceleration[1], snap.mLocalAcceleration[2],
            snap.mLocalVelocity[0], snap.mLocalVelocity[2],
            S.cstr(snap.mTyreCompound[0]),
            self._local_lap(snap), bool(snap.mLapInvalidated))
        for col, v in zip(LOCAL_COLUMNS, local_row):
            a.local[col].append(v)

        self._events(snap, t, participants, slot_names)
        a.last_participants = participants

        if now - a.last_flush >= self.flush_s:
            self._flush(a)
            a.last_flush = now
        if now - a.last_status >= 15:
            a.last_status = now
            self.log(f"[rec] {a.key[0]} {a.key[2]} t={t:,.0f}s cars={len(participants)} rows={a.rows:,}")

    def _events(self, snap, t, participants, slot_names) -> None:
        a = self.active
        if snap.mSessionState != a.prev_session_state:
            self._event({"t": t, "type": "session_state", "value": int(snap.mSessionState)})
            a.prev_session_state = snap.mSessionState

        names = {p["name"] for p in participants}
        for n in sorted(names - a.prev_names):
            if a.ticks > 1:
                self._event({"t": t, "type": "join", "name": n})
        for n in sorted(a.prev_names - names):
            self._event({"t": t, "type": "leave", "name": n})
        a.prev_names = names

        for p in participants:
            prev = a.prev_states.get(p["name"])
            if prev is not None and prev != p["race_state"]:
                self._event({"t": t, "type": "race_state", "name": p["name"],
                             "from": prev, "to": p["race_state"]})
            a.prev_states[p["name"]] = p["race_state"]

        if a.key[2] == "race" and a.green_t is None and any(p["race_state"] == "racing" for p in participants):
            a.green_t = t
            grid = a.prev_pos or {p["name"]: p["race_pos"] for p in participants}
            self._event({"t": t, "type": "green", "grid": grid, "late": not a.prev_pos})
        if a.green_t is None:
            a.prev_pos = {p["name"]: p["race_pos"] for p in participants if p["race_pos"] > 0}
        if participants:
            a.max_leader_laps = max(a.max_leader_laps, max(p["laps_completed"] for p in participants))

        col = (snap.mLastOpponentCollisionIndex, round(float(snap.mLastOpponentCollisionMagnitude), 3))
        if col != a.prev_collision and col[0] >= 0 and a.ticks > 1:
            self._event({"t": t, "type": "local_collision", "other": slot_names.get(col[0], f"slot{col[0]}"),
                         "magnitude": col[1]})
        a.prev_collision = col
        if snap.mCrashState != a.prev_crash:
            self._event({"t": t, "type": "local_crash_state", "value": int(snap.mCrashState)})
            a.prev_crash = snap.mCrashState

    # ----------------------------------------------------------------- storage
    def _event(self, ev: dict) -> None:
        with open(self.active.path / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")

    @staticmethod
    def _write_meta(a: _Active) -> None:
        (a.path / "session.json").write_text(json.dumps(a.meta, indent=2), encoding="utf-8")

    @staticmethod
    def _local_lap(snap) -> int:
        i = snap.mViewedParticipantIndex
        if 0 <= i < S.STORED_PARTICIPANTS_MAX:
            v = snap.mParticipantInfo[i].mLapsCompleted
            return v if 0 <= v < 10000 else (v & 0x7FFFFFFF if (v & 0x7FFFFFFF) < 10000 else -1)
        return -1

    @staticmethod
    def _local_pos(snap) -> tuple:
        i = snap.mViewedParticipantIndex
        if 0 <= i < S.STORED_PARTICIPANTS_MAX:
            p = snap.mParticipantInfo[i]
            return p.mWorldPosition[0], p.mWorldPosition[2], p.mCurrentLapDistance
        return float("nan"), float("nan"), float("nan")

    def _note(self, a: _Active, field_: str, raw: int, who: str, count: int = 1, stored=-1) -> None:
        """Record (and report once per session) a value the game sent outside the documented range."""
        info = a.out_of_range.get(field_)
        if info is None:
            a.out_of_range[field_] = {"example_raw": raw, "example_hex": hex(raw & 0xFFFFFFFF),
                                      "first_driver": who, "first_tick": a.ticks, "count": count, "stored_as": stored}
            self.log(f"[warn] {field_} = {raw} ({hex(raw & 0xFFFFFFFF)}) for {who}; stored as {stored}. "
                     f"Recording continues; details saved in session.json")
        else:
            info["count"] += count

    def _count(self, a: _Active, field_: str, v: int, who: str) -> int:
        """Positions / lap counters. Some PCars-lineage counters carry a flag in the top bit;
        mask it off if what remains is a sane count, otherwise treat as unset (-1)."""
        if 0 <= v < 10000:
            return v
        masked = v & ~TOP_BIT & 0xFFFFFFFF
        stored = masked if masked < 10000 else -1
        self._note(a, field_, v, who, stored=stored)
        return stored

    def _enum(self, a: _Active, field_: str, v: int, who: str) -> int:
        if -1 <= v <= 127:
            return v
        self._note(a, field_, v, who)
        return -1

    def _flush(self, a: _Active) -> None:
        for kind, buf, schema in (("frames", a.frames, FRAME_SCHEMA), ("local", a.local, LOCAL_SCHEMA)):
            if not buf["t"]:
                continue
            target = a.path / f"{kind}_parts" / f"part-{a.part:05d}"
            try:
                table = _to_table(buf, schema, lambda f, raw, n: self._note(a, f, raw, "(flush)", n))
                pq.write_table(table, target.with_suffix(".parquet"), compression="zstd")
            except Exception as exc:  # never lose a race to one bad write: dump raw rows instead
                self.log(f"[error] could not write {kind} parquet ({exc!r}); saved raw JSON instead")
                try:
                    target.with_suffix(".json").write_text(json.dumps(buf, default=float), encoding="utf-8")
                except Exception as exc2:
                    self.log(f"[error] raw JSON fallback failed too: {exc2!r}")
            for v in buf.values():
                v.clear()
        a.part += 1
        if a.out_of_range:
            a.meta["out_of_range"] = a.out_of_range
            self._write_meta(a)

    @staticmethod
    def _compact(path: Path, kind: str, schema: pa.Schema) -> None:
        tables = []
        for p in sorted((path / f"{kind}_parts").glob("part-*.*")):
            try:
                if p.suffix == ".parquet":
                    tables.append(pq.read_table(p))
                elif p.suffix == ".json":
                    tables.append(_to_table(json.loads(p.read_text(encoding="utf-8")), schema, lambda *_: None))
            except Exception:
                continue
        table = pa.concat_tables(tables) if tables else schema.empty_table()
        pq.write_table(table, path / f"{kind}.parquet", compression="zstd")
        shutil.rmtree(path / f"{kind}_parts", ignore_errors=True)
