"""Original shared mapper + events; complete snapshots stay on the coach worker."""
from __future__ import annotations

import json
import math
import re
import time

from .crew_mapper import Mapper
from .crew_engine import COMMANDS as ENGINE_COMMANDS
from .crew_damage import COMMANDS as DAMAGE_COMMANDS, clearly_ok
from .crew_fuel import COMMANDS as FUEL_COMMANDS,TIME_COMMANDS
from .crew_pits import COMMANDS as PIT_COMMANDS
from .crew_position import COMMANDS as POSITION_COMMANDS
from .crew_timings import COMMANDS as TIMING_COMMANDS
from .crew_tyres import COMMANDS as TYRE_COMMANDS
from .crew_laptimes import COMMANDS as LAPTIME_COMMANDS
from .model import finite
from .. import shm as S

COMMANDS = {
    'WHATS_THE_AIR_TEMP': ("what's the air temp", "what's the air temperature"),
    'WHATS_THE_TRACK_TEMP': ("what's the track temp", "what's the track temperature"),
    'WHATS_MY_BRAKE_BIAS': ("what's my brake bias",),
}
RADIO_COMMANDS = {
    'KEEP_QUIET': ('keep quiet','shut up',"I know what I'm doing",'leave me alone','minimal talking'),
    'KEEP_ME_INFORMED': ('keep me updated','keep me informed','keep me posted'),
    'REPEAT_LAST_MESSAGE': ('repeat last message','say again'),
}
RADIO_FOLDERS = ('acknowledge/keepQuietEnabled','acknowledge/keepQuietDisabled','acknowledge/stand_by')
FOLDERS = tuple('conditions/'+name for name in (
    'air_temp_is_now','air_temp_is','track_temp_is','track_temp_is_now',
    'air_and_track_temp_increasing','air_and_track_temp_decreasing',
    'air_temp_increasing_its_now','air_temp_decreasing_its_now',
    'track_temp_increasing_its_now','track_temp_decreasing_its_now',
    'celsius','fahrenheit','seeing_some_rain','we_expect_rain_in_the_next',
    'drizzle_increasing','light_rain_increasing','mid_rain_increasing',
    'heavy_rain_increasing','maximum_rain','heavy_rain_decreasing',
    'mid_rain_decreasing','light_rain_decreasing','drizzle_decreasing','stopped_raining')) + (
    'acknowledge/no_data','battery/percent')


def command_for(text):
    clean=lambda s: ' '.join(re.sub(r'[^a-z0-9 ]','',str(s).casefold()).split())
    return next((key for key,phrases in {**COMMANDS,**RADIO_COMMANDS}.items() if clean(text) in map(clean,phrases)),None)


def position_inputs_available(snapshot):
    """Validate real rank/identity inputs without constructing a substitute grid."""
    if not 1<=snapshot.mNumParticipants<=S.STORED_PARTICIPANTS_MAX:return False
    active=[i for i in range(snapshot.mNumParticipants) if snapshot.mParticipantInfo[i].mIsActive]
    if snapshot.mViewedParticipantIndex not in active:return False
    ranks=[snapshot.mParticipantInfo[i].mRacePosition for i in active]
    names=[S.cstr(snapshot.mParticipantInfo[i].mName).strip().casefold() for i in active]
    return (bool(active) and all(1<=p<=snapshot.mNumParticipants for p in ranks)
        and len(set(ranks))==len(ranks) and all(names) and len(set(names))==len(names)
        and all(S.cstr(snapshot.mCarNames[i]) or S.cstr(snapshot.mCarClassNames[i]) for i in active)
        and 0<=snapshot.mHighestFlagColour<=11
        and all(finite(v) is not None and v>=-1 for v in (snapshot.mSplitTimeAhead,snapshot.mSplitTimeBehind))
        and all(finite(snapshot.mSpeeds[i]) is not None and snapshot.mSpeeds[i]>=0 for i in active))


def lap_counter_inputs_available(snapshot):
    """Only observed rank, lap, phase, pit, pedal and prestart weather inputs.

    Session clock history is additionally checked by feed_snapshot; unknown
    timed-session duration cannot become a prestart race-distance announcement.
    """
    if not position_inputs_available(snapshot):return False
    active=[i for i in range(snapshot.mNumParticipants) if snapshot.mParticipantInfo[i].mIsActive]
    return (0<=snapshot.mRaceState<=8 and 0<=snapshot.mPitMode<=5
        and 0<=snapshot.mLapsInEvent<=9999 and 0<=snapshot.mSessionAdditionalLaps<=100
        and all(finite(v) is not None and lo<=v<=hi for v,lo,hi in (
            (snapshot.mThrottle,0,1),(snapshot.mAmbientTemperature,-50,80),
            (snapshot.mTrackTemperature,-50,150),(snapshot.mRainDensity,0,1),
            (snapshot.mCloudBrightness,0,2)))
        and all(0<=snapshot.mParticipantInfo[i].mLapsCompleted<=9999
            and 0<=snapshot.mParticipantInfo[i].mCurrentSector<=2
            and finite(snapshot.mParticipantInfo[i].mCurrentLapDistance) is not None
            and 0<=snapshot.mParticipantInfo[i].mCurrentLapDistance<=snapshot.mTrackLength for i in active))


def timing_inputs_available(snapshot):
    """Real rank, sector, lap, pit and crossing inputs; no guessed gap channels."""
    if not position_inputs_available(snapshot):return False
    if finite(snapshot.mTrackLength) is None or snapshot.mTrackLength<20:return False
    active=[i for i in range(snapshot.mNumParticipants) if snapshot.mParticipantInfo[i].mIsActive]
    return (0<=snapshot.mRaceState<=8 and 0<=snapshot.mPitMode<=5 and 1<=snapshot.mNumSectors<=3
        and 0<=snapshot.mLapsInEvent<=9999
        and all(0<=snapshot.mParticipantInfo[i].mLapsCompleted<=9999
            and 0<=snapshot.mParticipantInfo[i].mCurrentSector<snapshot.mNumSectors
            and finite(snapshot.mParticipantInfo[i].mCurrentLapDistance) is not None
            and 0<=snapshot.mParticipantInfo[i].mCurrentLapDistance<=snapshot.mTrackLength for i in active))


def tyre_inputs_available(snapshot):
    """Observed raw Celsius/kPa/wear/rotation inputs, never zero-filled history."""
    return (all(finite(v) is not None and .01<=v<=200 for a in (
                snapshot.mTyreTempLeft,snapshot.mTyreTempCenter,snapshot.mTyreTempRight) for v in a)
        and all(finite(v) is not None and .01<=v<=2000 for v in snapshot.mBrakeTempCelsius)
        and all(finite(v) is not None and 0<=v<=2000 for v in snapshot.mAirPressure)
        and any(v>0 for v in snapshot.mAirPressure)
        and all(finite(v) is not None and 0<=v<=1 for v in snapshot.mTyreWear)
        and all(finite(v) is not None and abs(v)<=10000 for v in snapshot.mTyreRPS))


def lap_time_inputs_available(snapshot):
    """Accept real timing sentinels; never fill unavailable lap/sector histories."""
    if not timing_inputs_available(snapshot):return False
    active=[i for i in range(snapshot.mNumParticipants) if snapshot.mParticipantInfo[i].mIsActive]
    times=[snapshot.mLastLapTime,snapshot.mBestLapTime]
    for i in active:
        times.extend(a[i] for a in (snapshot.mLastLapTimes,snapshot.mFastestLapTimes,
            snapshot.mCurrentSector1Times,snapshot.mCurrentSector2Times,snapshot.mCurrentSector3Times))
    return all(finite(v) is not None and -1<=v<=86400 for v in times)


class Core(Mapper):
    host_name='core'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from .crew_audio import AudioMetadata
        metadata=AudioMetadata(root=self.root,sounds=self.sounds.root)
        self.settings['__paddock_number_config']=json.dumps(metadata.settings['number_config'])
        if self.root is not None:self.settings['__paddock_state_directory']=str((self.root/'private_coach/crew_chief_state').resolve())
        self._clock_origin=time.perf_counter()
        self._utc_origin=621355968000000000+round(time.time()*10000000)
        self.valid_ids=set()
        self.acknowledged=[]
        self.withheld=[]
        self.latest=None
        self.weather_available=False
        self.engine_available=False
        self.engine_state='waiting_for_telemetry'
        self.damage_available=False
        self.damage_state='waiting_for_telemetry'
        self.fuel_available=False
        self.race_time_available=False
        self.fuel_state='waiting_for_telemetry'
        self.race_time_state='waiting_for_telemetry'
        self.fuel_data={}
        self.pit_available=False
        self.pit_state='waiting_for_telemetry'
        self.pit_data={}
        self.background={}
        self.position_available=False
        self.position_state='waiting_for_telemetry'
        self.position_data={}
        self.lap_counter_available=False
        self.lap_counter_state='waiting_for_telemetry'
        self.lap_counter_data={}
        self.timings_available=False
        self.timings_state='waiting_for_telemetry'
        self.timings_data={}
        self.lap_times_available=False
        self.lap_times_state='waiting_for_telemetry'
        self.lap_times_data={}
        self.tyres_available=False
        self.tyres_state='waiting_for_telemetry'
        self.tyres_data={}
        self.session_end_state='waiting_for_telemetry'
        self.session_end_data={}
        self.waiting_for_driver_ok=False
        self.voice_enabled=False
        self._needs_reset=False
        self._confirmed=None
        self.queue_status={}
        self.play_order=[]
        self.waiting_for_speech=False
        self._interval_due=None
        self._interval_state=None

    def start(self):
        if self.process is None and not self.error:
            self._closing=False
            self._starting=False
        super().start()

    def reset(self):
        super().reset()
        if hasattr(self,'valid_ids'):
            self.valid_ids.clear()
            self.latest=None
            self.engine_available=False
            self.weather_available=False
            self.engine_state='waiting_for_telemetry'
            self.damage_available=False
            self.damage_state='waiting_for_telemetry'
            self.fuel_available=self.race_time_available=False
            self.fuel_state=self.race_time_state='waiting_for_telemetry'
            self.fuel_data={}
            self.pit_available=False
            self.pit_state='waiting_for_telemetry'
            self.pit_data={}
            self.background={}
            self.position_available=False
            self.position_state='waiting_for_telemetry'
            self.position_data={}
            self.lap_counter_available=False
            self.lap_counter_state='waiting_for_telemetry'
            self.lap_counter_data={}
            self.timings_available=False
            self.timings_state='waiting_for_telemetry'
            self.timings_data={}
            self.lap_times_available=False
            self.lap_times_state='waiting_for_telemetry'
            self.lap_times_data={}
            self.tyres_available=False
            self.tyres_state='waiting_for_telemetry'
            self.tyres_data={}
            self.session_end_state='waiting_for_telemetry'
            self.session_end_data={}
            self.waiting_for_driver_ok=False
            self.queue_status={}
            self.play_order=[]
            self._needs_reset=True
            self._interval_due=None
            self._interval_state=None

    def invalidate(self, reason='telemetry_unavailable'):
        self.reset()
        self.state=reason
        self.engine_state=reason

    def _request(self,payload):
        if payload.get('op')=='map':
            payload={**payload,'events':True,'weather_available':self.weather_available,'engine_available':self.engine_available,
                     'damage_available':self.damage_available,'voice_enabled':self.voice_enabled,
                     'fuel_available':self.fuel_available,'race_time_available':self.race_time_available,
                     'pit_available':self.pit_available,
                     'position_available':self.position_available,
                     'lap_counter_available':self.lap_counter_available,
                     'timings_available':self.timings_available,
                     'tyres_available':self.tyres_available,
                     'lap_times_available':self.lap_times_available,
                     'fuel_gallons':getattr(self,'_fuel_gallons',False),
                     'fahrenheit':getattr(self,'_fahrenheit',False),'ack':self.acknowledged[:]}
        if payload.get('op') in ('map','command','speech_result'):
            payload={**payload,'waiting_for_speech':self.waiting_for_speech}
        result=super()._request(payload)
        if result is not None and payload.get('op') in ('map','command','speech_result'):
            self.acknowledged.clear()
        return result

    def valid_call(self, native_id):
        return str(native_id).removeprefix('core:') in self.valid_ids

    def acknowledge(self, native_id, outcome='finished'):
        native_id=str(native_id).removeprefix('core:')
        if outcome!='playing':self.valid_ids.discard(native_id)
        self.acknowledged.append({'id':native_id,'outcome':outcome})

    def order(self, native_id):
        try:return self.play_order.index(str(native_id).removeprefix('core:'))
        except ValueError:return None

    def _events(self, result):
        self.valid_ids=set(result.get('valid',()))
        self.withheld=list(result.get('withheld',()))
        self.engine_state=result.get('engine_state',self.engine_state)
        self.damage_state=result.get('damage_state',self.damage_state)
        self.fuel_state=result.get('fuel_state',self.fuel_state)
        self.race_time_state=result.get('race_time_state',self.race_time_state)
        self.fuel_data=dict(result.get('fuel',{}))
        self.pit_state=result.get('pit_state',self.pit_state)
        self.pit_data=dict(result.get('pit',{}))
        self.background=dict(result.get('background',{}))
        self.position_state=result.get('position_state',self.position_state)
        self.position_data=dict(result.get('position',{}))
        self.lap_counter_state=result.get('lap_counter_state',self.lap_counter_state)
        self.lap_counter_data=dict(result.get('lap_counter',{}))
        self.timings_state=result.get('timings_state',self.timings_state)
        self.timings_data=dict(result.get('timings',{}))
        self.lap_times_state=result.get('lap_times_state',self.lap_times_state)
        self.lap_times_data=dict(result.get('lap_times',{}))
        self.tyres_state=result.get('tyre_state',self.tyres_state)
        self.tyres_data=dict(result.get('tyres',{}))
        self.session_end_state=result.get('session_end_state',self.session_end_state)
        self.session_end_data=dict(result.get('session_end',{}))
        self.waiting_for_driver_ok=bool(result.get('waiting_for_driver_ok',False))
        self.queue_status=dict(result.get('queue',{}))
        self.play_order=list(self.queue_status.get('play_order',()))
        return [{**call,'id':call.get('source_event','original')+':'+call['id'],'native_id':'core:'+call['id']}
                for call in result.get('calls',())]

    def feed_snapshot(self, snapshot, tick, player, sampled_at, *, fahrenheit=False,fuel_gallons=False,respect_update_interval=False):
        age=time.perf_counter()-sampled_at
        identity=(player.slot,player.name,tick.track,tick.layout,S.cstr(snapshot.mCarName)) if player is not None else None
        if (player is None or not 0<=player.slot<min(snapshot.mNumParticipants,S.STORED_PARTICIPANTS_MAX)
                or player.slot!=tick.viewed_slot or not tick.fresh or age<0 or age>.25
                or S.cstr(snapshot.mParticipantInfo[player.slot].mName)!=player.name):
            self.invalidate('withheld_stale_or_wrong_player')
            return []
        pregrid=snapshot.mGameState==S.GAME_INGAME_INMENU_TIME_TICKING
        if snapshot.mGameState!=S.GAME_INGAME_PLAYING and (not pregrid or identity!=self._confirmed):
            self.invalidate('withheld_unconfirmed_pregrid_player')
            return []
        if self._needs_reset:
            if not self.reset_mapping(): return []
            self._needs_reset=False
        self.weather_available=(all(finite(v) is not None for v in (snapshot.mAmbientTemperature,snapshot.mTrackTemperature,snapshot.mRainDensity,snapshot.mCloudBrightness))
            and -50<=snapshot.mAmbientTemperature<=80 and -50<=snapshot.mTrackTemperature<=150
            and 0<=snapshot.mRainDensity<=1 and 0<=snapshot.mCloudBrightness<=2
            and (snapshot.mAmbientTemperature!=0 or snapshot.mTrackTemperature!=0))
        # These channels feed the original mapper's stall/health exclusions as
        # well as its temperature monitor. Missing/invalid health must not be
        # replaced by an invented healthy engine or suspension.
        self.engine_available=(all(finite(v) is not None for v in (
            snapshot.mOilTempCelsius,snapshot.mWaterTempCelsius,snapshot.mRpm,snapshot.mMaxRPM,
            snapshot.mSpeed,snapshot.mEngineDamage,*snapshot.mSuspensionDamage))
            and 0<snapshot.mOilTempCelsius<=300 and 0<snapshot.mWaterTempCelsius<=250
            and snapshot.mRpm>=0 and snapshot.mMaxRPM>0
            and snapshot.mSpeed>=0 and 0<=snapshot.mEngineDamage<=1
            and all(0<=v<=1 for v in snapshot.mSuspensionDamage))
        self.damage_available=(all(finite(v) is not None and 0<=v<=1 for v in (
            snapshot.mEngineDamage,snapshot.mAeroDamage,*snapshot.mSuspensionDamage,*snapshot.mBrakeDamage))
            and all(finite(v) is not None and 0<=v<=2000 for v in snapshot.mAirPressure)
            and all(finite(v) is not None and abs(v)<=4*3.141593 for v in snapshot.mOrientation)
            and finite(snapshot.mSpeed) is not None and snapshot.mSpeed>=0)
        self.fuel_available=(finite(snapshot.mFuelLevel) is not None and 0<=snapshot.mFuelLevel<=1
            and finite(snapshot.mFuelCapacity) is not None and 0<snapshot.mFuelCapacity<=10000)
        known_timed=bool(identity==self._confirmed and self.latest and self.latest['state'].get('duration',0)>0)
        self.race_time_available=(finite(snapshot.mEventTimeRemaining) is not None
            and (snapshot.mLapsInEvent>0 or snapshot.mEventTimeRemaining>=0 or known_timed))
        # Negative enforced-stop lap means unknown, not proof there is no stop.
        # Speed, box coordinates and limiter remain the original mapper's unknown
        # sentinels. Occupancy/history receive separate native evidence guards.
        self.pit_available=(0<=snapshot.mPitMode<=5 and 0<=snapshot.mPitSchedule<=7
            and -1<=snapshot.mEnforcedPitStopLap<=9999
            and finite(snapshot.mSpeed) is not None and snapshot.mSpeed>=0
            and finite(snapshot.mTrackLength) is not None and snapshot.mTrackLength>0
            and finite(snapshot.mParticipantInfo[player.slot].mCurrentLapDistance) is not None
            and 0<=snapshot.mParticipantInfo[player.slot].mCurrentLapDistance<=snapshot.mTrackLength)
        self.position_available=position_inputs_available(snapshot)
        self.lap_counter_available=(self.pit_available and self.race_time_available
            and lap_counter_inputs_available(snapshot))
        self.timings_available=self.pit_available and self.race_time_available and timing_inputs_available(snapshot)
        self.lap_times_available=self.pit_available and lap_time_inputs_available(snapshot)
        self.tyres_available=self.pit_available and self.race_time_available and tyre_inputs_available(snapshot)
        # The live recorder can supply 20+ samples/s; original event processing
        # uses CC's update_interval (100ms by default). Keep its sample-count
        # windows intact. Explicit diagnostic maps remain caller-clocked.
        interval=max(0,int(self.settings['update_interval']))/1000
        interval_state=(identity,snapshot.mSessionState,snapshot.mRaceState,snapshot.mGameState,
                        self.weather_available,self.engine_available,self.damage_available,self.fuel_available,self.race_time_available,self.pit_available,self.position_available,self.lap_counter_available,self.timings_available,self.tyres_available,self.lap_times_available,
                        bool(fahrenheit),bool(fuel_gallons),interval)
        same_interval_state=self._interval_state==interval_state
        if (respect_update_interval and same_interval_state and self._interval_due is not None
                and sampled_at<self._interval_due-1e-6):
            return []
        # Match Paddock's explicitly chosen units without changing CC's profile.
        self._fahrenheit=bool(fahrenheit)
        self._fuel_gallons=bool(fuel_gallons)
        ticks=self._utc_origin+round((sampled_at-self._clock_origin)*10000000)
        result=self.map_snapshot(snapshot,ticks=ticks,local_slot=player.slot,sample_age=age,allow_pregrid=pregrid)
        if not result or not result.get('mapped'):
            self.valid_ids.clear()
            self.latest=None
            self.engine_state=self.state
            self.damage_state=self.state
            self.fuel_state=self.race_time_state=self.state
            self.pit_state=self.state
            self.pit_data={}
            self.background={}
            self.position_state=self.state
            self.position_data={}
            self.lap_counter_state=self.state
            self.lap_counter_data={}
            self.timings_state=self.state
            self.timings_data={}
            self.lap_times_state=self.state
            self.lap_times_data={}
            self.tyres_state=self.state
            self.tyres_data={}
            self.session_end_state=self.state
            self.session_end_data={}
            self.waiting_for_driver_ok=False
            self._needs_reset=True
            return []
        if snapshot.mGameState==S.GAME_INGAME_PLAYING:
            self._confirmed=identity
        self.latest={'at':sampled_at,'session':tick.session_id,'state':result,'game_state':int(snapshot.mGameState)}
        if same_interval_state and self._interval_due is not None and interval>0:
            self._interval_due+=max(1,math.floor((sampled_at-self._interval_due)/interval)+1)*interval
        else:self._interval_due=sampled_at+interval
        self._interval_state=interval_state
        self.state='monitoring' if self.weather_available else 'weather_telemetry_unavailable'
        return self._events(result.get('events',{}))

    def respond(self,command,text=None):
        if (command not in COMMANDS and command not in ENGINE_COMMANDS and command not in RADIO_COMMANDS and command not in DAMAGE_COMMANDS and command not in FUEL_COMMANDS and command not in TIME_COMMANDS and command not in PIT_COMMANDS and command not in POSITION_COMMANDS and command not in TIMING_COMMANDS and command not in TYRE_COMMANDS and command not in LAPTIME_COMMANDS and command!='PADDOCK_TYRE_STATUS') or self.latest is None or time.perf_counter()-self.latest['at']>.25:
            self.valid_ids.clear()
            return []
        try:
            result=self._request({'op':'command','command':command,'text':text,'ack':self.acknowledged[:]})
            if result is None: return []
            if result.get('error'): raise ValueError(result['error'])
            return self._events(result)
        except (OSError,ValueError) as exc:
            self.error=str(exc);self.invalidate('error');return []

    def speech_result(self,text,confidence=0,*,detected_speech=False,voice=True):
        """Pass real recognition/timeout outcomes to the original crash exchange.

        Typed replies can answer a pending question, but never claim that a
        microphone was used. System.Speech uses CC's Windows threshold.
        """
        if self.latest is None or not 0<=time.perf_counter()-self.latest['at']<=.25:
            return []
        try:
            threshold=float(self.settings['minimum_voice_recognition_confidence_system_sre'])
            if not 0<=threshold<=1:threshold=.7
            recognised=bool(text) and finite(confidence) is not None
            understood=recognised and confidence>=threshold
            result=self._request({'op':'speech_result','recognised':bool(voice and recognised),
                'clearly_ok':bool(understood and clearly_ok(text)),
                'detected_speech':bool(detected_speech or text),'voice_enabled':self.voice_enabled,
                'ack':self.acknowledged[:]})
            if result is None:return []
            if result.get('error'):raise ValueError(result['error'])
            return self._events(result)
        except (OSError,ValueError) as exc:
            self.error=str(exc);self.invalidate('error');return []

    def close(self):
        self.reset()
        self._confirmed=None
        super().close()
