"""AMS2 shared memory: ctypes layout (mirrors SharedMemory.h, SHARED_MEMORY_VERSION 14)
and a read-only Windows reader.

The layout is verified field-by-field against the real header by tests/test_layout.py.
AMS2 only ever appends fields, so mapping sizeof(SharedMemory) bytes of a newer
build is safe: we simply read a prefix of a larger block.

In game: Options > System > Shared Memory must be set to "Project CARS 2".
"""
from __future__ import annotations

import ctypes as C
import sys
import time

SHM_TAGNAME = "$pcars2$"
SHARED_MEMORY_VERSION = 14
STRING_LENGTH_MAX = 64
STORED_PARTICIPANTS_MAX = 64
TYRE_COMPOUND_NAME_LENGTH_MAX = 40
TYRE_MAX = 4
VEC_MAX = 3

# --- enums we actually use -------------------------------------------------
# GameState
GAME_EXITED, GAME_FRONT_END, GAME_INGAME_PLAYING, GAME_INGAME_PAUSED, \
    GAME_INGAME_INMENU_TIME_TICKING, GAME_INGAME_RESTARTING, GAME_INGAME_REPLAY, \
    GAME_FRONT_END_REPLAY = range(8)
# SessionState
SESSION_INVALID, SESSION_PRACTICE, SESSION_TEST, SESSION_QUALIFY, \
    SESSION_FORMATION_LAP, SESSION_RACE, SESSION_TIME_ATTACK = range(7)
# RaceState
RACESTATE_INVALID, RACESTATE_NOT_STARTED, RACESTATE_RACING, RACESTATE_FINISHED, \
    RACESTATE_DISQUALIFIED, RACESTATE_RETIRED, RACESTATE_DNF = range(7)
# PitMode
PIT_MODE_NONE, PIT_MODE_DRIVING_INTO_PITS, PIT_MODE_IN_PIT, PIT_MODE_DRIVING_OUT_OF_PITS, \
    PIT_MODE_IN_GARAGE, PIT_MODE_DRIVING_OUT_OF_GARAGE = range(6)
# PitSchedule (subset)
PIT_SCHEDULE_DRIVE_THROUGH, PIT_SCHEDULE_STOP_GO = 5, 6
# CrashState
CRASH_DAMAGE_NONE, CRASH_DAMAGE_OFFTRACK, CRASH_DAMAGE_LARGE_PROP, \
    CRASH_DAMAGE_SPINNING, CRASH_DAMAGE_ROLLING = range(5)
# FlagReason
FLAG_REASON_NONE, FLAG_REASON_SOLO_CRASH, FLAG_REASON_VEHICLE_CRASH, \
    FLAG_REASON_VEHICLE_OBSTRUCTION = range(4)

RACESTATE_NAMES = {0: "invalid", 1: "not_started", 2: "racing", 3: "finished",
                   4: "dsq", 5: "retired", 6: "dnf"}

_P = STORED_PARTICIPANTS_MAX
_Str = C.c_char * STRING_LENGTH_MAX
_Vec = C.c_float * VEC_MAX
_T4f = C.c_float * TYRE_MAX
_T4u = C.c_uint * TYRE_MAX


class ParticipantInfo(C.Structure):
    _fields_ = [
        ("mIsActive", C.c_bool),
        ("mName", _Str),
        ("mWorldPosition", _Vec),
        ("mCurrentLapDistance", C.c_float),
        ("mRacePosition", C.c_uint),
        ("mLapsCompleted", C.c_uint),
        ("mCurrentLap", C.c_uint),
        ("mCurrentSector", C.c_int),
    ]


class SharedMemory(C.Structure):
    _fields_ = [
        ("mVersion", C.c_uint),
        ("mBuildVersionNumber", C.c_uint),
        ("mGameState", C.c_uint),
        ("mSessionState", C.c_uint),
        ("mRaceState", C.c_uint),
        ("mViewedParticipantIndex", C.c_int),
        ("mNumParticipants", C.c_int),
        ("mParticipantInfo", ParticipantInfo * _P),
        ("mUnfilteredThrottle", C.c_float),
        ("mUnfilteredBrake", C.c_float),
        ("mUnfilteredSteering", C.c_float),
        ("mUnfilteredClutch", C.c_float),
        ("mCarName", _Str),
        ("mCarClassName", _Str),
        ("mLapsInEvent", C.c_uint),
        ("mTrackLocation", _Str),
        ("mTrackVariation", _Str),
        ("mTrackLength", C.c_float),
        ("mNumSectors", C.c_int),
        ("mLapInvalidated", C.c_bool),
        ("mBestLapTime", C.c_float),
        ("mLastLapTime", C.c_float),
        ("mCurrentTime", C.c_float),
        ("mSplitTimeAhead", C.c_float),
        ("mSplitTimeBehind", C.c_float),
        ("mSplitTime", C.c_float),
        ("mEventTimeRemaining", C.c_float),
        ("mPersonalFastestLapTime", C.c_float),
        ("mWorldFastestLapTime", C.c_float),
        ("mCurrentSector1Time", C.c_float),
        ("mCurrentSector2Time", C.c_float),
        ("mCurrentSector3Time", C.c_float),
        ("mFastestSector1Time", C.c_float),
        ("mFastestSector2Time", C.c_float),
        ("mFastestSector3Time", C.c_float),
        ("mPersonalFastestSector1Time", C.c_float),
        ("mPersonalFastestSector2Time", C.c_float),
        ("mPersonalFastestSector3Time", C.c_float),
        ("mWorldFastestSector1Time", C.c_float),
        ("mWorldFastestSector2Time", C.c_float),
        ("mWorldFastestSector3Time", C.c_float),
        ("mHighestFlagColour", C.c_uint),
        ("mHighestFlagReason", C.c_uint),
        ("mPitMode", C.c_uint),
        ("mPitSchedule", C.c_uint),
        ("mCarFlags", C.c_uint),
        ("mOilTempCelsius", C.c_float),
        ("mOilPressureKPa", C.c_float),
        ("mWaterTempCelsius", C.c_float),
        ("mWaterPressureKPa", C.c_float),
        ("mFuelPressureKPa", C.c_float),
        ("mFuelLevel", C.c_float),
        ("mFuelCapacity", C.c_float),
        ("mSpeed", C.c_float),
        ("mRpm", C.c_float),
        ("mMaxRPM", C.c_float),
        ("mBrake", C.c_float),
        ("mThrottle", C.c_float),
        ("mClutch", C.c_float),
        ("mSteering", C.c_float),
        ("mGear", C.c_int),
        ("mNumGears", C.c_int),
        ("mOdometerKM", C.c_float),
        ("mAntiLockActive", C.c_bool),
        ("mLastOpponentCollisionIndex", C.c_int),
        ("mLastOpponentCollisionMagnitude", C.c_float),
        ("mBoostActive", C.c_bool),
        ("mBoostAmount", C.c_float),
        ("mOrientation", _Vec),
        ("mLocalVelocity", _Vec),
        ("mWorldVelocity", _Vec),
        ("mAngularVelocity", _Vec),
        ("mLocalAcceleration", _Vec),
        ("mWorldAcceleration", _Vec),
        ("mExtentsCentre", _Vec),
        ("mTyreFlags", _T4u),
        ("mTerrain", _T4u),
        ("mTyreY", _T4f),
        ("mTyreRPS", _T4f),
        ("mTyreSlipSpeed", _T4f),
        ("mTyreTemp", _T4f),
        ("mTyreGrip", _T4f),
        ("mTyreHeightAboveGround", _T4f),
        ("mTyreLateralStiffness", _T4f),
        ("mTyreWear", _T4f),
        ("mBrakeDamage", _T4f),
        ("mSuspensionDamage", _T4f),
        ("mBrakeTempCelsius", _T4f),
        ("mTyreTreadTemp", _T4f),
        ("mTyreLayerTemp", _T4f),
        ("mTyreCarcassTemp", _T4f),
        ("mTyreRimTemp", _T4f),
        ("mTyreInternalAirTemp", _T4f),
        ("mCrashState", C.c_uint),
        ("mAeroDamage", C.c_float),
        ("mEngineDamage", C.c_float),
        ("mAmbientTemperature", C.c_float),
        ("mTrackTemperature", C.c_float),
        ("mRainDensity", C.c_float),
        ("mWindSpeed", C.c_float),
        ("mWindDirectionX", C.c_float),
        ("mWindDirectionY", C.c_float),
        ("mCloudBrightness", C.c_float),
        # PCars2 additions (v8+)
        ("mSequenceNumber", C.c_uint),
        ("mWheelLocalPositionY", _T4f),
        ("mSuspensionTravel", _T4f),
        ("mSuspensionVelocity", _T4f),
        ("mAirPressure", _T4f),
        ("mEngineSpeed", C.c_float),
        ("mEngineTorque", C.c_float),
        ("mWings", C.c_float * 2),
        ("mHandBrake", C.c_float),
        ("mCurrentSector1Times", C.c_float * _P),
        ("mCurrentSector2Times", C.c_float * _P),
        ("mCurrentSector3Times", C.c_float * _P),
        ("mFastestSector1Times", C.c_float * _P),
        ("mFastestSector2Times", C.c_float * _P),
        ("mFastestSector3Times", C.c_float * _P),
        ("mFastestLapTimes", C.c_float * _P),
        ("mLastLapTimes", C.c_float * _P),
        ("mLapsInvalidated", C.c_bool * _P),
        ("mRaceStates", C.c_uint * _P),
        ("mPitModes", C.c_uint * _P),
        ("mOrientations", _Vec * _P),
        ("mSpeeds", C.c_float * _P),
        ("mCarNames", _Str * _P),
        ("mCarClassNames", _Str * _P),
        ("mEnforcedPitStopLap", C.c_int),
        ("mTranslatedTrackLocation", _Str),
        ("mTranslatedTrackVariation", _Str),
        ("mBrakeBias", C.c_float),
        ("mTurboBoostPressure", C.c_float),
        ("mTyreCompound", (C.c_char * TYRE_COMPOUND_NAME_LENGTH_MAX) * TYRE_MAX),
        ("mPitSchedules", C.c_uint * _P),
        ("mHighestFlagColours", C.c_uint * _P),
        ("mHighestFlagReasons", C.c_uint * _P),
        ("mNationalities", C.c_uint * _P),
        ("mSnowDensity", C.c_float),
        # AMS2 additions (v10+)
        ("mSessionDuration", C.c_float),
        ("mSessionAdditionalLaps", C.c_int),
        ("mTyreTempLeft", _T4f),
        ("mTyreTempCenter", _T4f),
        ("mTyreTempRight", _T4f),
        ("mDrsState", C.c_uint),
        ("mRideHeight", _T4f),
        ("mJoyPad0", C.c_uint),
        ("mDPad", C.c_uint),
        ("mAntiLockSetting", C.c_int),
        ("mTractionControlSetting", C.c_int),
        ("mErsDeploymentMode", C.c_int),
        ("mErsAutoModeEnabled", C.c_bool),
        ("mClutchTemp", C.c_float),
        ("mClutchWear", C.c_float),
        ("mClutchOverheated", C.c_bool),
        ("mClutchSlipping", C.c_bool),
        ("mYellowFlagState", C.c_int),
        ("mSessionIsPrivate", C.c_bool),
        ("mLaunchStage", C.c_int),
    ]


SEQ_OFFSET = SharedMemory.mSequenceNumber.offset


def cstr(raw) -> str:
    """Decode a fixed-size C char array.

    Struct fields of type c_char[N] come back from ctypes as bytes, but elements of a 2D
    array (mCarNames[i], mCarClassNames[i]) come back as c_char_Array objects, so handle both.
    """
    if hasattr(raw, "value") and not isinstance(raw, (bytes, bytearray)):
        raw = raw.value
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw).split(b"\0", 1)[0].decode("utf-8", "replace").strip()
    return str(raw).strip()


class SharedMemoryReader:
    """Read-only reader for the AMS2 shared memory block (Windows only).

    Uses OpenFileMappingW rather than mmap(-1, size, tagname): Python's mmap would
    *create* the mapping if the game isn't running yet, and a mapping we create with
    our (possibly smaller) size would then be inherited by the game. Opening read-only
    and retrying is the safe approach.
    """

    FILE_MAP_READ = 0x0004

    def __init__(self, tagname: str = SHM_TAGNAME):
        if sys.platform != "win32":
            raise OSError("SharedMemoryReader only works on Windows (where AMS2 runs).")
        self.tagname = tagname
        self.size = C.sizeof(SharedMemory)
        self._k32 = C.WinDLL("kernel32", use_last_error=True)
        self._k32.OpenFileMappingW.restype = C.c_void_p
        self._k32.OpenFileMappingW.argtypes = [C.c_uint32, C.c_bool, C.c_wchar_p]
        self._k32.MapViewOfFile.restype = C.c_void_p
        self._k32.MapViewOfFile.argtypes = [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32, C.c_size_t]
        self._k32.UnmapViewOfFile.argtypes = [C.c_void_p]
        self._k32.CloseHandle.argtypes = [C.c_void_p]
        self._handle = None
        self._view = None

    def open(self) -> bool:
        if self._view:
            return True
        h = self._k32.OpenFileMappingW(self.FILE_MAP_READ, False, self.tagname)
        if not h:
            return False
        v = self._k32.MapViewOfFile(h, self.FILE_MAP_READ, 0, 0, self.size)
        if not v:
            self._k32.CloseHandle(h)
            return False
        self._handle, self._view = h, v
        return True

    def close(self) -> None:
        if self._view:
            self._k32.UnmapViewOfFile(self._view)
        if self._handle:
            self._k32.CloseHandle(self._handle)
        self._handle = self._view = None

    def snapshot(self, retries: int = 20) -> SharedMemory | None:
        """Return a consistent copy of the block, or None if the game isn't available.

        The game increments mSequenceNumber before and after each write (odd = mid-write).
        We copy only when it's even and unchanged across the copy.
        """
        if not self.open():
            return None
        seq_ptr = C.c_uint.from_address(self._view + SEQ_OFFSET)
        out = SharedMemory()
        for _ in range(retries):
            s1 = seq_ptr.value
            if s1 & 1:
                time.sleep(0.0005)
                continue
            C.memmove(C.addressof(out), self._view, self.size)
            if seq_ptr.value == s1 and out.mSequenceNumber == s1:
                return out
        return out  # best effort; rare torn reads are tolerated downstream

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
