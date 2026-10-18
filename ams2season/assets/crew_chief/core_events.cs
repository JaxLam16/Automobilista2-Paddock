// Original events and queue planner, with asynchronous device-free playback
// receipts. Full original AudioPlayer monitor/channel/pacing remains pending.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using CrewChiefV4.GameState;
using CrewChiefV4.Events;
using CrewChiefV4.Audio;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace CrewChiefV4 {
    public static class Configuration {
        public static Dictionary<string,string> NumberConfig=new Dictionary<string,string>();
        public static string getSoundConfigOption(string key) { return NumberConfig[key]; }
    }
    public static class NumberReaderFactory {
        public static bool IS_ENGLISH=true;
        public static NumberReader GetNumberReader() { return new NumberProcessing.NumberReaderEn(); }
    }
}
namespace CrewChiefV4.Events.PubSub { public static class EventBus { public static void Unsubscribe(object value) { } } }
namespace CrewChiefV4.ACC { public static class ACCGameStateMapper { public static float clockMultiplierGuess=1; } }
namespace CrewChiefV4.LMU {
    // This host only accepts AMS2. LMU damage configuration is never inferred.
    public static class SessionSettings { public static bool NotLMUorLMUcarDamageEnabled { get { return !CrewChiefV4.Game.LMU; } } }
}
namespace CrewChiefV4.Events {
    public static partial class Battery { public const string folderPercent="battery/percent",folderLaps="battery/laps"; }
}
namespace CrewChiefV4.Audio {
    public static class SoundPackVersionsHelper { public static float currentSoundPackVersion; }
    public partial class AudioPlayer {
        public const string PAUSE_ID="insert_pause",folderNoData="acknowledge/no_data",folderNoMoreData="acknowledge/no_more_data",folderAcknowlegeOK="acknowledge/OK";
        public static string soundPackLanguage="en";
        public enum TTS_OPTION { NEVER, ONLY_WHEN_NECESSARY, ANY_TIME }
        public static TTS_OPTION ttsOption=TTS_OPTION.NEVER;

    }
}
public static class PaddockOriginalEvents {
    static readonly AudioPlayer audio=new AudioPlayer();
    static ConditionsMonitor weather;
    static TyreMonitor tyres;
    static bool tyreWasAvailable;
    static string tyreState="waiting_for_telemetry";
    static EngineMonitor engine;
    static DamageReporting damage;
    static Fuel fuel;
    static RaceTime raceTime;
    static PitStops pitStops;
    static Position position;
    static AbstractEvent timings;
    static AbstractEvent lapTimes;
    static bool lapTimesWasAvailable;
    static string lapTimesState="waiting_for_telemetry";
    static bool timingWasAvailable;
    static string timingState="waiting_for_telemetry";
    static LapCounter lapCounter;
    static SessionEndMessages sessionEnd;
    static bool sessionFinished,finishObservedRunning;
    static string finishState="waiting_for_telemetry";
    static bool lapCounterWasAvailable;
    static string lapCounterState="waiting_for_telemetry";
    public static object Lookup(string name) { if(name=="ConditionsMonitor")return weather; throw new NotSupportedException("Event not connected: "+name); }
    static bool positionWasAvailable;
    static string positionState="waiting_for_telemetry";
    static bool pitWasAvailable;
    static bool legacyFuel;
    static readonly HashSet<string> availableEvents=new HashSet<string>();
    public static void SetWaitingForSpeech(bool waiting) {audio.WaitingForSpeech=waiting;}
    static string engineState="waiting_for_telemetry";
    static string damageState="waiting_for_telemetry";
    static string fuelState="waiting_for_telemetry",raceTimeState="waiting_for_telemetry";
    static string pitState="waiting_for_telemetry";
    public static void Initialise(string sounds) {
        string options;
        if(CrewChiefV4.UserSettings.Values.TryGetValue("__paddock_number_config",out options))
            CrewChiefV4.Configuration.NumberConfig=JsonConvert.DeserializeObject<Dictionary<string,string>>(options);
        else CrewChiefV4.Configuration.NumberConfig=new Dictionary<string,string> {
            {"prefix_hundred_and_thousand_with_one","true"},{"say_and_between_hundred_and_units","true"},
            {"say_and_between_thousand_and_units","true"},{"allow_short_hundreds","true"},{"always_use_thousands","false"}};
        float version;
        string versionFile=Path.Combine(sounds,"sound_pack_version_info.txt");
        if(File.Exists(versionFile) && float.TryParse(File.ReadAllText(versionFile).Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out version)) SoundPackVersionsHelper.currentSoundPackVersion=version;
        foreach(var family in new [] {"tyre_monitor","conditions","engine_monitor","damage_reporting","fuel","race_time","position","lap_times","lap_counter","timings","opponents","strategy","mandatory_pit_stops","frozen_order","numbers","acknowledge","battery","rants","pearls_of_wisdom","penalties"}) {
            string directory=Path.Combine(sounds,"voice",family);
            if(!Directory.Exists(directory)) continue;
            foreach(var folder in Directory.GetDirectories(directory)) if(Directory.EnumerateFiles(folder,"*.wav").Any())
            {
                string name=family+"/"+Path.GetFileName(folder);
                SoundCache.availableSounds.Add(name);SoundCache.soundSets[name]=null;
            }
        }
        string driverNames=Path.Combine(sounds,"driver_names");
        if(Directory.Exists(driverNames)) foreach(string file in Directory.GetFiles(driverNames,"*.wav"))
            SoundCache.availableDriverNames.Add(Path.GetFileNameWithoutExtension(file).ToLowerInvariant());
        audio.InitialiseQueueMetadata();
        CrewChiefV4.FuelHost.Initialise();
        CrewChiefV4.PitHost.Initialise();
        tyres=new TyreMonitor(audio);weather=new ConditionsMonitor(audio);engine=new EngineMonitor(audio);damage=new DamageReporting(audio);
        fuel=new Fuel(audio);raceTime=new RaceTime(audio);
        timings=CrewChiefV4.UserSettings.GetUserSettings().getBoolean("revert_to_legacy_version_of_refactored_code")
            ?(AbstractEvent)new Timings_legacy(audio):new Timings(audio);
        lapTimes=CrewChiefV4.UserSettings.GetUserSettings().getBoolean("revert_to_legacy_version_of_refactored_code")
            ?(AbstractEvent)new LapTimes_legacy(audio):new LapTimes(audio);
        pitStops=new PitStops(audio);
        position=new Position(audio);
        lapCounter=new LapCounter(audio,new CrewChiefV4.CrewChief());
        sessionEnd=new SessionEndMessages(audio);
        legacyFuel=CrewChiefV4.UserSettings.GetUserSettings().getBoolean("legacy_fuel");Reset();
    }
    public static void Reset() {
        if(tyres!=null)tyres.clearState();tyreWasAvailable=false;tyreState="waiting_for_telemetry";
        if(weather!=null) weather.clearState();
        if(engine!=null) engine.clearState();
        if(damage!=null) damage.clearState();
        if(fuel!=null) {fuel.clearState();Fuel.legacy_inst.clearState();BenchmarkHelper.loadBenchmarks();}
        if(raceTime!=null) raceTime.clearState();
        if(pitStops!=null)pitStops.clearState();
        if(position!=null)position.clearState();
        if(timings!=null)timings.clearState();PaddockTimingsHost.Reset();timingWasAvailable=false;timingState="waiting_for_telemetry";
        if(lapTimes!=null)lapTimes.clearState();lapTimesWasAvailable=false;lapTimesState="waiting_for_telemetry";
        if(lapCounter!=null)lapCounter.clearState();
        lapCounterWasAvailable=false;lapCounterState="waiting_for_telemetry";
        positionWasAvailable=false;positionState="waiting_for_telemetry";
        CrewChiefV4.PitHost.Reset();pitWasAvailable=false;pitState="waiting_for_telemetry";
        audio.PaddockResetBackground();
        audio.ResetQueue();availableEvents.Clear();
        sessionFinished=finishObservedRunning=false;finishState="waiting_for_telemetry";
        engineState="waiting_for_telemetry";
        damageState="waiting_for_telemetry";
        fuelState=raceTimeState="waiting_for_telemetry";
    }
    static object Result(GameStateData current) {
        audio.Pump(current,availableEvents);
        return new {calls=audio.calls,valid=audio.Validate(current,availableEvents),withheld=audio.withheld,engine_state=engineState,
            damage_state=damageState,waiting_for_driver_ok=DamageReporting.waitingForDriverIsOKResponse,
            has_made_voice_command=CrewChiefV4.SpeechRecogniser.hasMadeVoiceCommandSinceStarting,queue=audio.QueueStatus(),
            fuel_state=fuelState,race_time_state=raceTimeState,
            pit_state=pitState,pit=CrewChiefV4.PitHost.State(pitStops,current),background=audio.PaddockBackgroundState(),
            lap_counter_state=lapCounterState,lap_counter=CrewChiefV4.LapCounterHost.State(lapCounter,current),
            tyre_state=tyreState,tyres=PaddockTyresHost.State(tyres,current),
            lap_times_state=lapTimesState,lap_times=PaddockLapTimesHost.State(lapTimes,current),
            timings_state=timingState,timings=PaddockTimingsHost.State(timings,current),
            session_end_state=finishState,session_end=new {handled=sessionFinished,observed_running=finishObservedRunning,
                enabled=sessionEnd.enableSessionEndMessages,phase=current==null?null:current.SessionData.SessionPhase.ToString(),
                class_position=current==null?0:current.SessionData.ClassPosition,
                start_class_position=current==null?0:current.SessionData.SessionStartClassPosition,
                class_cars_at_start=current==null?0:current.SessionData.NumCarsInPlayerClassAtStartOfSession},
            position_state=positionState,position=CrewChiefV4.PositionHost.State(position,current),
            fuel=new {mode=legacyFuel?"legacy":"current",multiplier=CrewChiefV4.CrewChief.fuelMultiplier.multiplier,
                data=legacyFuel?null:fuel.PaddockState(),state_directory=CrewChiefV4.DataFiles.fuel_usage,
                pit_strategy_complete=false},
        };
    }
    public static object Process(GameStateData previous,GameStateData current,GameStateData positionPreviousSnapshot,bool weatherAvailable,bool engineAvailable,bool damageAvailable,bool fuelAvailable,bool raceTimeAvailable,bool pitAvailable,bool mandatoryKnown,bool occupancyKnown,bool positionAvailable,bool lapCounterAvailable,bool timingAvailable,bool tyreAvailable,bool lapTimesAvailable,JToken ack) {
        audio.calls.Clear();audio.withheld.Clear();audio.Ack(ack);
        if(current!=null && current.SessionData.IsNewSession) Reset();
        availableEvents.Clear();
        if(current!=null) {availableEvents.Add("AudioPlayer");PlaybackModerator.UpdateAutoVerbosity(current);}
        // Original CrewChief main-loop finish path precedes ordinary events.
        // The exact installed caller/argument provenance is recorded separately.
        if(current!=null && current.SessionData.SessionPhase==SessionPhase.Finished) {
            availableEvents.Add("SessionEndMessages");audio.SourceEvent="SessionEndMessages";
            var raw=((CrewChiefV4.AMS2.AMS2SharedMemoryReader.AMS2StructWrapper)current.rawGameData).data;
            bool rawRaceKnown=current.SessionData.SessionType!=SessionType.Race ||
                raw.mRaceState==(uint)CrewChiefV4.AMS2.eRaceState.RACESTATE_FINISHED ||
                raw.mRaceState==(uint)CrewChiefV4.AMS2.eRaceState.RACESTATE_DISQUALIFIED;
            if(!sessionFinished) {
                if(!finishObservedRunning || previous==null || previous.SessionData.SessionPhase==SessionPhase.Finished || current.SessionData.IsNewSession)finishState="withheld_unobserved_finish";
                else if(!positionAvailable || previous.SessionData.ClassPosition<1 ||
                    current.SessionData.SessionType==SessionType.Race && previous.SessionData.NumCarsInPlayerClassAtStartOfSession<1)
                    finishState="withheld_position_inputs";
                // Installed AMS2 mapper does not set IsDNF. Do not turn the
                // mapper's false sentinel into a congratulation on raw DNF.
                else if(!rawRaceKnown)finishState="withheld_unmapped_finish_status";
                else {
                    audio.purgeQueues();
                    sessionEnd.trigger(previous.SessionData.SessionRunningTime,previous.SessionData.SessionType,current.SessionData.SessionPhase,
                        previous.SessionData.SessionStartClassPosition,previous.SessionData.ClassPosition,
                        previous.SessionData.NumCarsInPlayerClassAtStartOfSession,previous.SessionData.CompletedLaps,
                        current.SessionData.expectedFinishingPosition,current.SessionData.IsDisqualified,current.SessionData.IsDNF,current.Now);
                    audio.holdChannelOpen=false;audio.wakeMonitorThreadForRegularMessages(current.Now);
                    audio.disablePearlsOfWisdom=false;sessionFinished=true;
                    finishState=sessionEnd.enableSessionEndMessages?"finish_observed":"disabled_by_preference";
                }
            }
            return Result(current);
        }
        if(current!=null && positionAvailable && (current.SessionData.SessionPhase==SessionPhase.Green ||
            current.SessionData.SessionPhase==SessionPhase.FullCourseYellow || current.SessionData.SessionPhase==SessionPhase.Checkered)) {
            finishObservedRunning=true;finishState="monitoring";
        }
        // Original eventsList order among implemented shared events.
        if(positionAvailable && current!=null) {
            availableEvents.Add("Position");audio.SourceEvent="Position";
            bool applicable=position.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase);
            GameStateData positionPrevious=positionWasAvailable?positionPreviousSnapshot:null;
            // Original Position reads the previous tick during pass detection.
            // Wait for an observed valid pair instead of supplying a fake tick.
            if(applicable && positionPrevious!=null)position.trigger(positionPrevious,CrewChiefV4.PositionHost.Current(current));
            positionState=!applicable?"inactive_session_phase":positionPrevious==null?"warming_up":"monitoring";
            positionWasAvailable=true;
        } else {if(positionWasAvailable)position.clearState();positionWasAvailable=false;positionState="position_telemetry_unavailable";}
        if(lapCounterAvailable && current!=null && !GameStateData.useManualFormationLap) {
            availableEvents.Add("LapCounter");audio.SourceEvent="LapCounter";
            bool applicable=lapCounter.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase);
            GameStateData lapPrevious=lapCounterWasAvailable?previous:null;
            if(applicable && lapPrevious!=null)lapCounter.trigger(lapPrevious,current);
            lapCounterState=!applicable?"inactive_session_phase":lapPrevious==null?"warming_up":"monitoring";
            lapCounterWasAvailable=true;
        } else {
            if(lapCounterWasAvailable)lapCounter.clearState();lapCounterWasAvailable=false;
            lapCounterState=GameStateData.useManualFormationLap?"manual_formation_bridge_pending":"lap_counter_telemetry_unavailable";
        }
        if(timingAvailable && current!=null) {
            availableEvents.Add("Timings");audio.SourceEvent="Timings";
            PaddockTimingsHost.Observe(current);
            bool applicable=timings.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase);
            bool known=PaddockTimingsHost.AutomaticInputsKnown(current);
            if(!known)timings.clearState();
            else if(applicable && timingWasAvailable && previous!=null)timings.trigger(previous,current);
            timingState=!applicable?"inactive_session_phase":!timingWasAvailable?"warming_up":!known?"learning_crossings":"monitoring";
            timingWasAvailable=true;
        } else {if(timingWasAvailable)timings.clearState();PaddockTimingsHost.Reset();timingWasAvailable=false;
            timingState="timing_telemetry_unavailable";}
        if(lapTimesAvailable && current!=null && !GameStateData.onManualFormationLap) {
            availableEvents.Add("LapTimes");audio.SourceEvent="LapTimes";
            bool applicable=lapTimes.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase);
            if(applicable && lapTimesWasAvailable && previous!=null)lapTimes.trigger(previous,current);
            lapTimesState=!applicable?"inactive_session_phase":!lapTimesWasAvailable?"warming_up":"monitoring";
            lapTimesWasAvailable=true;
        } else {lapTimes.clearState();lapTimesWasAvailable=false;
            lapTimesState=GameStateData.onManualFormationLap?"manual_formation_bridge_pending":"lap_times_telemetry_unavailable";}
        if(pitAvailable && current!=null) {
            availableEvents.Add("PitStops");audio.SourceEvent="PitStops";
            bool applicable=pitStops.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase);
            GameStateData pitPrevious=pitWasAvailable?previous:null;
            CrewChiefV4.PitHost.Observe(pitPrevious,current,mandatoryKnown,occupancyKnown);
            if(applicable)pitStops.trigger(pitPrevious,current);
            pitState=!applicable?"inactive_session_phase":pitPrevious==null?"warming_up":"monitoring";
            pitWasAvailable=true;
        } else {pitStops.clearState();CrewChiefV4.PitHost.Reset();pitWasAvailable=false;pitState="pit_telemetry_unavailable";}
        if(fuelAvailable && current!=null) {
            availableEvents.Add("Fuel");audio.SourceEvent="Fuel";
            AbstractEvent selected=legacyFuel?(AbstractEvent)Fuel.legacy_inst:fuel;
            bool applicable=selected.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase);
            if(applicable) selected.trigger(previous,current);
            fuelState=!applicable?"inactive_session_phase":!CrewChiefV4.CrewChief.fuelMultiplier.active?"disabled_fuel_multiplier":
                !GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.FUEL)?"disabled_for_car_class":
                legacyFuel?(CrewChiefV4.FuelHost.LegacyInitialised?"monitoring_legacy":"warming_up"):fuel.PaddockInitialised?"monitoring":"warming_up";
        } else {fuel.clearState();Fuel.legacy_inst.clearState();fuelState="fuel_telemetry_unavailable";}
        if(raceTimeAvailable && current!=null) {
            availableEvents.Add("RaceTime");audio.SourceEvent="RaceTime";
            bool applicable=raceTime.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase);
            if(applicable)raceTime.trigger(previous,current);
            raceTimeState=applicable?"monitoring":"inactive_session_phase";
        } else {raceTime.clearState();raceTimeState="race_time_telemetry_unavailable";}
        if(tyreAvailable && current!=null && PaddockTyresHost.InputsKnown(current)) {
            availableEvents.Add("TyreMonitor");audio.SourceEvent="TyreMonitor";
            bool applicable=tyres.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase);
            if(applicable && tyreWasAvailable && previous!=null)tyres.trigger(previous,current);
            tyreState=!applicable?"inactive_session_phase":!tyreWasAvailable?"warming_up":"monitoring";
            tyreWasAvailable=true;
        } else {tyres.clearState();tyreWasAvailable=false;tyreState="tyre_telemetry_unavailable";}
        if(engineAvailable && current!=null) {
            availableEvents.Add("EngineMonitor");
            audio.SourceEvent="EngineMonitor";
            bool applicable=engine.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase);
            if(applicable) engine.trigger(previous,current);
            engineState=!applicable?"inactive_session_phase":
                current.SessionData.SessionRunningTime>60*current.EngineData.MinutesIntoSessionBeforeMonitoring?"monitoring":"warming_up";
        } else { engine.clearState();engineState="engine_telemetry_unavailable"; }
        if(damageAvailable && current!=null) {
            availableEvents.Add("DamageReporting");audio.SourceEvent="DamageReporting";
            bool applicable=damage.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase);
            if(applicable) damage.trigger(previous,current);
            damageState=applicable?"monitoring":"inactive_session_phase";
        } else {damage.clearState();damageState="damage_telemetry_unavailable";}
        if(weatherAvailable && current!=null) {
            availableEvents.Add("ConditionsMonitor");audio.SourceEvent="ConditionsMonitor";
            if(weather.isApplicableForCurrentSessionAndPhase(current.SessionData.SessionType,current.SessionData.SessionPhase))weather.trigger(previous,current);
        } else {weather.clearState();}
        return Result(current);
    }
    public static object SpeechResult(GameStateData current,bool recognised,bool clearlyOK,bool detectedSpeech,bool voiceEnabled,JToken ack) {
        audio.calls.Clear();audio.withheld.Clear();audio.Ack(ack);
        CrewChiefV4.MainWindow.voiceOption=voiceEnabled?CrewChiefV4.MainWindow.VoiceOptionEnum.HOLD:CrewChiefV4.MainWindow.VoiceOptionEnum.DISABLED;
        if(recognised) CrewChiefV4.SpeechRecogniser.hasMadeVoiceCommandSinceStarting=true;
        if(current!=null && availableEvents.Contains("DamageReporting") && DamageReporting.waitingForDriverIsOKResponse) {
            audio.SourceEvent="DamageReporting";
            damage.cancelWaitingForDriverIsOK(clearlyOK?DamageReporting.DriverOKResponseType.CLEARLY_OK:
                detectedSpeech?DamageReporting.DriverOKResponseType.NOT_UNDERSTOOD:DamageReporting.DriverOKResponseType.NO_SPEECH);
        }
        return Result(current);
    }
    public static object Command(string command,GameStateData current,JToken ack,string text=null) {
        audio.calls.Clear();audio.withheld.Clear();audio.Ack(ack);
        if(current!=null) {
            audio.SourceEvent="AudioPlayer";
            switch(command) {
                case "KEEP_QUIET":audio.enableKeepQuietMode();break;
                case "KEEP_ME_INFORMED":audio.disableKeepQuietMode();break;
                case "REPEAT_LAST_MESSAGE":audio.repeatLastMessage();break;
            }
            if(availableEvents.Contains("Position") && position.HandlesEvent(command)!=CrewChiefV4.SpeechCommands.ID.NO_COMMAND) {
                audio.SourceEvent="Position";
                if(positionState!="monitoring")audio.playMessageImmediately(new CrewChiefV4.QueuedMessage(AudioPlayer.folderNoData,0));
                else position.respond(command);
            }
            if(availableEvents.Contains("Timings") && timings.HandlesEvent(command)!=CrewChiefV4.SpeechCommands.ID.NO_COMMAND) {
                audio.SourceEvent="Timings";
                string reason=timingState!="monitoring" && timingState!="learning_crossings"?timingState:PaddockTimingsHost.Unsupported(current,command);
                if(reason!=null){audio.withheld.Add("Timings:"+command+": "+reason);
                    if(command!="STATUS" && command!="SESSION_STATUS")audio.playMessageImmediately(new CrewChiefV4.QueuedMessage(AudioPlayer.folderNoData,0));}
                else timings.respond(command);
            }
            if(lapTimes.HandlesEvent(command)!=CrewChiefV4.SpeechCommands.ID.NO_COMMAND) {
                audio.SourceEvent="LapTimes";
                string reason=lapTimesState!="monitoring"?lapTimesState:PaddockLapTimesHost.Unsupported(current,command);
                if(reason!=null) {
                    audio.withheld.Add("LapTimes:"+command+": "+reason);
                    if(!availableEvents.Contains("LapTimes"))audio.SourceEvent="AudioPlayer";
                    audio.playMessageImmediately(new CrewChiefV4.QueuedMessage(AudioPlayer.folderNoData,0));
                } else lapTimes.respond(command);
            }
            if(availableEvents.Contains("PitStops") && pitStops.HandlesEvent(command)!=CrewChiefV4.SpeechCommands.ID.NO_COMMAND) {
                audio.SourceEvent="PitStops";
                string reason=pitState=="inactive_session_phase"?"inactive session phase":CrewChiefV4.PitHost.Unsupported(pitStops,current,command);
                if(reason!=null){
                    audio.withheld.Add("PitStops:"+command+": "+reason);
                    if(command!="STATUS" && command!="SESSION_STATUS")audio.playMessageImmediately(new CrewChiefV4.QueuedMessage(AudioPlayer.folderNoData,0));
                } else pitStops.respond(command);
            }
            if(availableEvents.Contains("Fuel") && fuel.HandlesEvent(command)!=CrewChiefV4.SpeechCommands.ID.NO_COMMAND) {
                audio.SourceEvent="Fuel";
                string originalText=text;
                if(String.IsNullOrWhiteSpace(originalText)) {
                    string[] phrases;
                    originalText=CrewChiefV4.SpeechRecogniser.FuelPhrases.TryGetValue(command,out phrases)?phrases[0]:command;
                }
                if(fuelState=="warming_up") {
                    // The original numeric fields start at zero before the first
                    // processed pair of samples. That is not measured empty fuel.
                    if(command!="CAR_STATUS" && command!="STATUS")audio.playMessageImmediately(new CrewChiefV4.QueuedMessage(AudioPlayer.folderNoData,0));
                } else if(legacyFuel)Fuel.legacy_inst.respond(originalText.ToLowerInvariant());
                else fuel.respond(originalText.ToLowerInvariant(),fuel.HandlesEvent(command));
            }
            if(availableEvents.Contains("RaceTime") && raceTime.HandlesEvent(command)!=CrewChiefV4.SpeechCommands.ID.NO_COMMAND) {
                audio.SourceEvent="RaceTime";
                if(raceTimeState=="inactive_session_phase") {
                    if(command!="STATUS" && command!="SESSION_STATUS")audio.playMessageImmediately(new CrewChiefV4.QueuedMessage(AudioPlayer.folderNoData,0));
                } else raceTime.respond(command);
            }
            string tyreCommand=command=="PADDOCK_TYRE_STATUS"?"CAR_STATUS":command;
            if(tyres.HandlesEvent(tyreCommand)!=CrewChiefV4.SpeechCommands.ID.NO_COMMAND || command=="WHAT_TYRES_AM_I_ON") {
                audio.SourceEvent="TyreMonitor";
                string reason=tyreState!="monitoring"?tyreState:command=="WHAT_TYRES_AM_I_ON"?"compound query owner Opponents not connected":PaddockTyresHost.Unsupported(tyres,current,tyreCommand);
                if(reason!=null) {
                    audio.withheld.Add("TyreMonitor:"+command+": "+reason);
                    if(!availableEvents.Contains("TyreMonitor"))audio.SourceEvent="AudioPlayer";
                    if(command!="STATUS" && command!="CAR_STATUS")audio.playMessageImmediately(new CrewChiefV4.QueuedMessage(AudioPlayer.folderNoData,0));
                } else tyres.respond(tyreCommand,tyres.HandlesEvent(tyreCommand));
            }
            if(availableEvents.Contains("ConditionsMonitor") && weather.HandlesEvent(command)!=CrewChiefV4.SpeechCommands.ID.NO_COMMAND) {
                audio.SourceEvent="ConditionsMonitor";weather.respond(command);
            }
            if(availableEvents.Contains("EngineMonitor") && engine.HandlesEvent(command)!=CrewChiefV4.SpeechCommands.ID.NO_COMMAND) {
                audio.SourceEvent="EngineMonitor";engine.respond(command);
            }
            if(availableEvents.Contains("DamageReporting") && damage.HandlesEvent(command)!=CrewChiefV4.SpeechCommands.ID.NO_COMMAND) {
                audio.SourceEvent="DamageReporting";
                // Original AMS2 mapper explicitly cannot derive transmission
                // damage. Do not turn its NONE sentinel into a healthy gearbox.
                if(command=="HOWS_MY_TRANSMISSION") audio.playMessageImmediately(new CrewChiefV4.QueuedMessage(AudioPlayer.folderNoData,0));
                else damage.respond(command);
            }
        }
        return Result(current);
    }
    public static object QueueTest(JObject item,GameStateData current) {
        if(current==null) throw new InvalidOperationException("Queue test needs mapped state");
        audio.calls.Clear();audio.withheld.Clear();audio.Ack(item["ack"]);
        audio.SourceEvent="AudioPlayer";
        audio.TestActions(item["actions"],current);
        return Result(current);
    }
}
