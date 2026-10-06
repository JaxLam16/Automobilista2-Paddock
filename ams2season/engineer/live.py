"""The engineer on track: collects the recording car's channels from every shared-memory snapshot, works out
when a run starts (leaving the pits or garage) and ends (back in), and hands each finished run over for
analysis. Also reports what it can see right now for the live panel."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

PIT_NONE, PIT_IN, PIT_OUT, PIT_GARAGE, PIT_OUT_GARAGE = 0, 2, 3, 4, 5
WHEELS = range(4)
W = ("fl", "fr", "rl", "rr")


class EngineerTracker:
    def __init__(self, on_run_end=None, min_laps: int = 1):
        self.on_run_end = on_run_end
        self.min_laps = min_laps
        self.rows, self.state = [], "garage"
        self.last_snap_t = None
        self.info = {}
        self.runs_done = 0
        self.last_result = None

    def feed(self, snap, now: float) -> None:
        try:
            i = max(0, int(getattr(snap, "mViewedParticipantIndex", 0)))
            p = snap.mParticipantInfo[i]
            pit = int(getattr(snap, "mPitMode", 0))
            moving = snap.mSpeed > 2.0
            self.last_snap_t = time.time()
            self.info = {"session_state": int(getattr(snap, "mSessionState", 0)), "pit_mode": pit, "speed_kph": round(snap.mSpeed * 3.6),
                         "fuel_l": round(snap.mFuelLevel * snap.mFuelCapacity, 1) if snap.mFuelCapacity else None,
                         "time_remaining_s": round(snap.mEventTimeRemaining) if getattr(snap, "mEventTimeRemaining", -1) > 0 else None,
                         "track_length": float(getattr(snap, "mTrackLength", 0) or 0),
                         "car": snap.mCarName.decode(errors="ignore").split("\x00")[0] if hasattr(snap.mCarName, "decode") else None,
                         "track": snap.mTrackLocation.decode(errors="ignore").split("\x00")[0] if hasattr(snap.mTrackLocation, "decode") else None,
                         "layout": snap.mTrackVariation.decode(errors="ignore").split("\x00")[0] if hasattr(snap.mTrackVariation, "decode") else None}
            in_box = pit in (PIT_IN, PIT_GARAGE) or (not moving and pit != PIT_NONE)
            if self.state == "garage" and moving and pit in (PIT_NONE, PIT_OUT, PIT_OUT_GARAGE):
                self.state, self.rows = "running", []
            if self.state == "running":
                self.rows.append(self._row(snap, p, now, pit))
                if in_box:
                    self._finish()
        except Exception:
            pass

    def _row(self, snap, p, now, pit) -> dict:
        r = {"t": now, "speed": snap.mSpeed, "steering": snap.mSteering, "throttle": snap.mThrottle, "brake": snap.mBrake,
             "yaw_rate": snap.mAngularVelocity[1], "acc_lat": snap.mLocalAcceleration[0], "acc_long": snap.mLocalAcceleration[2],
             "lap_dist": p.mCurrentLapDistance, "local_lap": int(p.mLapsCompleted), "local_lap_invalid": bool(snap.mLapInvalidated),
             "x": p.mWorldPosition[0], "z": p.mWorldPosition[2], "gear": snap.mGear, "rpm": snap.mRpm, "max_rpm": snap.mMaxRPM,
             "num_gears": snap.mNumGears, "fuel_level": snap.mFuelLevel, "fuel_capacity": snap.mFuelCapacity, "brake_bias": snap.mBrakeBias,
             "abs_setting": snap.mAntiLockSetting, "tc_setting": snap.mTractionControlSetting, "abs_active": bool(snap.mAntiLockActive),
             "water_temp": snap.mWaterTempCelsius, "oil_temp": snap.mOilTempCelsius, "pit_mode": pit,
             "compound": snap.mTyreCompound[0].value.decode(errors="ignore") if hasattr(snap.mTyreCompound[0], "value") else None}
        for k, w in enumerate(W):
            r.update({f"rps_{w}": snap.mTyreRPS[k], f"tl_{w}": snap.mTyreTempLeft[k], f"tc_{w}": snap.mTyreTempCenter[k], f"tr_{w}": snap.mTyreTempRight[k],
                      f"press_{w}": snap.mAirPressure[k], f"ride_{w}": snap.mRideHeight[k], f"susp_{w}": snap.mSuspensionTravel[k],
                      f"svel_{w}": snap.mSuspensionVelocity[k], f"hag_{w}": snap.mTyreHeightAboveGround[k], f"btemp_{w}": snap.mBrakeTempCelsius[k],
                      f"wear_{w}": snap.mTyreWear[k]})
        return r

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def _finish(self) -> None:
        df = self.frame()
        self.state, self.rows = "garage", []
        laps = df.local_lap.nunique() - 1 if len(df) else 0
        if laps >= self.min_laps and self.on_run_end:
            self.runs_done += 1
            try:
                self.last_result = self.on_run_end(df, self.info)
            except Exception as exc:
                self.last_result = {"error": str(exc)}

    def status(self) -> dict:
        df = self.rows
        laps_done, last_lap, best = 0, None, None
        if df:
            lap = np.array([r["local_lap"] for r in df]); t = np.array([r["t"] for r in df])
            starts = [t[np.argmax(lap == k)] for k in np.unique(lap)]
            times = np.diff(starts)
            laps_done = len(times)
            if len(times):
                last_lap, best = float(times[-1]), float(times[1:].min()) if len(times) > 1 else None
        fresh = self.last_snap_t is not None and time.time() - self.last_snap_t < 3
        return {"active": True, "connected": fresh, "state": self.state, "laps": laps_done, "last_lap": last_lap, "best_lap": best,
                "runs_done": self.runs_done, **self.info, "last_result": self.last_result}
