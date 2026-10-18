// Read-only host for the original shared GameState and AMS2 mapper.
// Only explicit Facade operations are exposed. No installed application, UI,
// sound device, telemetry connection, preferences writer or editor is created.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using Newtonsoft.Json;

namespace CrewChiefV4 {
    public static class MapperClock { public static DateTime UtcNow=DateTime.UtcNow; }
    public static class Log {
        [Flags] public enum LogType { Debug=1 }
        public static LogType LogMask = 0;
        public static void Verbose(Func<string> value) { }
        public static void Debug(string value) { }
        public static void Debug(Func<string> value) { }
        public static void SoundDebug(string value) { }
        public static void SoundDebug(Func<string> value) { }
        public static void Sound(string value) { }
        public static void Sound(Func<string> value) { }
        public static void Fuel(string value) { }
        public static void Fuel(Func<string> value) { }
        public static void Commentary(string value) { }
        public static void Warning(string value) { }
        public static void Error(string value) { }
        public static void Fatal(string value) { throw new InvalidOperationException(value); }
        public static void Exception(Exception error, string value="") { Console.Error.WriteLine(value + error.Message); }
        public static Suppressed DontSpam(string value, int seconds) { return new Suppressed(); }
        public static void Debug(Suppressed value) { }
        public class Suppressed { public void Error() { } }
    }
    public sealed class UserSettings {
        static readonly UserSettings instance = new UserSettings();
        public static readonly Dictionary<string,string> Values = new Dictionary<string,string>();
        public static UserSettings GetUserSettings() { return instance; }
        string Value(string key) {
            string value;
            if (!Values.TryGetValue(key, out value)) throw new KeyNotFoundException("Unknown CC setting: " + key);
            return value;
        }
        public string getString(string key) { return Value(key); }
        public bool getBoolean(string key) { return bool.Parse(Value(key)); }
        public int getInt(string key) { return int.Parse(Value(key), CultureInfo.InvariantCulture); }
        public float getFloat(string key) { return float.Parse(Value(key), CultureInfo.InvariantCulture); }
    }
    public partial class CrewChief {
        public enum RacingType { Undefined, Circuit, Rally }
        public static bool forceSingleClass, enableDriverNames = true, viewingReplay;
        public static bool readOpponentDeltasForEveryLap=false;
        public static int maxUnknownClassesForAC=1;
        public static string trackName;
        public static float distanceRoundTrack;
        public static CarData.CarClassEnum carClass;
        public static GameDefinition gameDefinition;
        public static GameState.GameStateData currentGameState;
        public static class Debug { public static bool RunningUnderDebugger { get { return false; } } }
    }
    public sealed partial class SpeechRecogniser { public static int sreSessionId; public static bool hasMadeVoiceCommandSinceStarting; public void addNewOpponentName(string name, string number) { } }
    public static partial class DataFiles {
        public static string default_carClassData, carClassData, default_track_landmarks, track_landmarksFolder, unvocalized_driver_names;
    }
    public static class JsonFiles {
        public enum Comments { Strip }
        public static T ReadFile<T>(string path, Comments comments, bool ignored=true) {
            string text = string.Join("\n", File.ReadAllLines(path).Where(line => !line.TrimStart().StartsWith("#")));
            return JsonConvert.DeserializeObject<T>(text);
        }
        public static void WriteFile(string path, object data) { throw new NotSupportedException("Crew Chief writes disabled"); }
        public static void WriteFilteredFile(string path, object data) {
            // The mapper may auto-classify an unknown oval. Keep its in-memory
            // decision, but never persist it into Crew Chief's documents folder.
            PaddockMapperHost.SuppressedWrites.Add(path);
        }
    }
    public static partial class Utilities {
        public static Random random=new Random();
        public static readonly Dictionary<string,int> queuedMessageIds=new Dictionary<string,int>();
        public static void TraceEventClass(GameState.GameStateData state) { }
        public static void TryBackupBrokenFile(string path, string suffix, string reason) { throw new NotSupportedException(reason); }
        public static void AddLinesToFile(string path, IEnumerable<string> lines) { throw new NotSupportedException("Crew Chief name writes disabled"); }
        public static class FileNames { public static string MakeValidForPathName(string value) { throw new NotSupportedException("Track editor disabled"); } }
    }
    public sealed partial class MainWindow {
        public enum VoiceOptionEnum { DISABLED, HOLD }
        public static VoiceOptionEnum voiceOption=VoiceOptionEnum.DISABLED;
        public static readonly MainWindow instance=new MainWindow();
        public void BeginInvoke(Delegate action) { /* Deliberately never opens the track editor UI. */ }
    }
    public sealed class ForegroundWindowManager { public void SaveForegroundWindow() { } public void RestoreForegroundWindow() { } }
}
namespace CrewChiefV4.PCars { public static class PCarsGameStateMapper { public const string NULL_CHAR_STAND_IN = "?"; } }
namespace CrewChiefV4.Events {
    public static partial class Strategy { public static DateTime nextOpponentPitExitWarningDue = DateTime.MinValue; }
    public class CoDriver { public enum PacenoteType { unknown } public enum PacenoteModifier { none } public void PlayFinishMessage() { throw new NotSupportedException("Rally unsupported by AMS2-only host"); } }
}
namespace CrewChiefV4.Audio {
    public partial class AudioPlayer { public static bool delayMessagesInHardParts=UserSettings.GetUserSettings().getBoolean("enable_delayed_messages_on_hardparts"); public const string folderBreathIn="breath_in"; }
    public static partial class SoundCache {
        public static readonly Dictionary<string,object> soundSets = new Dictionary<string,object>();
        public static readonly HashSet<string> availableSounds = new HashSet<string>();
        public static readonly HashSet<string> availableDriverNames = new HashSet<string>();
        public static readonly HashSet<string> availableDriverNamesForTrainee = new HashSet<string>();
        public static string[] availableDriverNamesForUIAsArray = new string[0];
        public const string TTS_IDENTIFIER="TTS_IDENTIFIER",DOWNLOAD_IDENTIFIER="DOWNLOAD_IDENTIFIER";
        public static bool hasSingleSound(string name) { return availableDriverNames.Contains(name); }
        public static void loadDriverNameSound(string name) { }
    }
}
namespace CrewChiefV4.AMS2 {
    public class AMS2SharedMemoryReader {
        public class AMS2StructWrapper { public ams2APIStruct data; public long ticksWhenRead; }
    }
}
public static class PaddockMapperHost {
    public static readonly List<string> SuppressedWrites = new List<string>();
    static CrewChiefV4.AMS2.AMS2GameStateMapper mapper;
    static CrewChiefV4.GameState.GameStateData state;
    static CrewChiefV4.GameState.GameStateData previousMappedState;
    static CrewChiefV4.GameState.GameStateData previousPositionMappedState;
    static bool initialised;
    public static void Reset() {
        mapper=new CrewChiefV4.AMS2.AMS2GameStateMapper();
        state=null;
        previousPositionMappedState=null;
        CrewChiefV4.CrewChief.currentGameState=null;
        CrewChiefV4.GameState.GameStateData.NumberOfClasses=1;
        CrewChiefV4.GameState.GameStateData.Multiclass=false;
        SuppressedWrites.Clear();
        PaddockOriginalEvents.Reset();
    }
    public static void Initialise(string settingsJson, string classFile, string extraClassFile, string landmarkFile, string extraLandmarkFolder) {
        var values = JsonConvert.DeserializeObject<Dictionary<string,string>>(File.ReadAllText(settingsJson));
        foreach(var item in values) CrewChiefV4.UserSettings.Values[item.Key]=item.Value;
        CrewChiefV4.DataFiles.default_carClassData=classFile;
        CrewChiefV4.DataFiles.carClassData=extraClassFile;
        CrewChiefV4.DataFiles.default_track_landmarks=landmarkFile;
        CrewChiefV4.DataFiles.track_landmarksFolder=extraLandmarkFolder;
        CrewChiefV4.Game.game=CrewChiefV4.GameEnum.AMS2;
        CrewChiefV4.CrewChief.gameDefinition=CrewChiefV4.GameDefinition.ams2;
        CrewChiefV4.CrewChief.forceSingleClass=CrewChiefV4.UserSettings.GetUserSettings().getBoolean("force_single_class");
        CrewChiefV4.CrewChief.enableDriverNames=CrewChiefV4.UserSettings.GetUserSettings().getBoolean("enable_driver_names");
        CrewChiefV4.CrewChief.maxUnknownClassesForAC=CrewChiefV4.UserSettings.GetUserSettings().getInt("max_unknown_car_classes_for_assetto");
        CrewChiefV4.GameState.GlobalBehaviourSettings.reloadSettings();
        CrewChiefV4.GameState.GlobalBehaviourSettings.racingType=CrewChiefV4.CrewChief.gameDefinition.racingType;
        CrewChiefV4.CarData.loadCarClassData();
        CrewChiefV4.TrackData.loadTrackLandmarksData();
        Reset();
        initialised=true;
    }
    public static string Layout() {
        var raw = typeof(CrewChiefV4.AMS2.ams2APIStruct);
        var fields=raw.GetFields().ToDictionary(f=>f.Name, f=>(int)Marshal.OffsetOf(raw,f.Name));
        var participant=typeof(CrewChiefV4.AMS2.ams2APIParticipantStruct);
        return JsonConvert.SerializeObject(new {size=Marshal.SizeOf(raw),fields=fields, participantSize=Marshal.SizeOf(participant), participantFields=participant.GetFields().ToDictionary(f=>f.Name,f=>(int)Marshal.OffsetOf(participant,f.Name))});
    }
    public static string NormaliseName(string name) { return CrewChiefV4.DriverNameHelper.validateAndCleanUpName(name); }
    public static CrewChiefV4.GameState.GameStateData Map(CrewChiefV4.AMS2.ams2APIStruct raw, long ticks) {
        if (!initialised) throw new InvalidOperationException("Mapper is not initialised");
        if(raw.mGameState==(uint)CrewChiefV4.AMS2.eGameState.GAME_INGAME_INMENU_TIME_TICKING &&
            CrewChiefV4.AMS2.AMS2GameStateMapper.getPlayerIndex(raw)!=raw.mViewedParticipantIndex) return null;
        CrewChiefV4.MapperClock.UtcNow=new DateTime(ticks,DateTimeKind.Utc);
        var positionPrevious=CrewChiefV4.PositionHost.Capture(state);
        var next = mapper.mapToGameStateData(new CrewChiefV4.AMS2.AMS2SharedMemoryReader.AMS2StructWrapper { data=raw, ticksWhenRead=ticks }, state);
        if (next == null || object.ReferenceEquals(next,state)) return null;
        previousMappedState=state;
        previousPositionMappedState=positionPrevious;
        state=next;
        CrewChiefV4.CrewChief.currentGameState=state;
        if (state.SessionData.SessionType==CrewChiefV4.GameState.SessionType.Race) mapper.populateDerivedRaceSessionData(state);
        else mapper.populateDerivedNonRaceSessionData(state);
        return state;
    }
    static object Snapshot(CrewChiefV4.GameState.GameStateData next) {
        if (next==null) return new { mapped=false };
        var session=next.SessionData;
        var raw=((CrewChiefV4.AMS2.AMS2SharedMemoryReader.AMS2StructWrapper)next.rawGameData).data;
        return new {
            mapped=true, now=next.Now.Ticks,
            session_type=session.SessionType.ToString(), phase=session.SessionPhase.ToString(),
            new_session=session.IsNewSession, new_lap=session.IsNewLap, new_sector=session.IsNewSector,
            laps=session.CompletedLaps, sector=session.SectorNumber, position=session.OverallPosition,
            class_position=session.ClassPosition, classes=CrewChiefV4.GameState.GameStateData.NumberOfClasses,
            class_name=next.carClass.carClassEnum.ToString(), car_name=next.carName,
            track=session.TrackDefinition.name, length=session.TrackDefinition.trackLength,
            remaining=session.SessionTimeRemaining, duration=session.SessionTotalRunTime,
            running=session.SessionRunningTime,
            fuel=next.FuelData.FuelLeft,
            oil=next.EngineData.EngineOilTemp, water=next.EngineData.EngineWaterTemp,
            rpm=next.EngineData.EngineRpm, stalled=next.EngineData.EngineStalledWarning,
            engine_damage=next.CarDamageData.OverallEngineDamage.ToString(),
            suspension_destroyed=next.CarDamageData.SuspensionDamageStatus.hasValueAtLevel(CrewChiefV4.GameState.DamageLevel.DESTROYED),
            oil_limit=next.carClass.maxSafeOilTemp,water_limit=next.carClass.maxSafeWaterTemp,
            battery=next.carClass.isBatteryPowered,
            transmission=next.CarDamageData.OverallTransmissionDamage.ToString(),
            tyre_type=next.TyreData.FrontLeftTyreType.ToString(),
            brake_temps=new [] {next.TyreData.LeftFrontBrakeTemp,next.TyreData.RightFrontBrakeTemp,next.TyreData.LeftRearBrakeTemp,next.TyreData.RightRearBrakeTemp},
            tyre_tread=new [] {
                new [] {next.TyreData.FrontLeft_LeftTemp,next.TyreData.FrontLeft_CenterTemp,next.TyreData.FrontLeft_RightTemp},
                new [] {next.TyreData.FrontRight_LeftTemp,next.TyreData.FrontRight_CenterTemp,next.TyreData.FrontRight_RightTemp},
                new [] {next.TyreData.RearLeft_LeftTemp,next.TyreData.RearLeft_CenterTemp,next.TyreData.RearLeft_RightTemp},
                new [] {next.TyreData.RearRight_LeftTemp,next.TyreData.RearRight_CenterTemp,next.TyreData.RearRight_RightTemp}},
            raw_tail=new {abs=raw.mAntiLockSetting,tc=raw.mTractionControlSetting,ers=raw.mErsDeploymentMode,ers_auto=raw.mErsAutoModeEnabled,
                clutch_temp=raw.mClutchTemp,clutch_wear=raw.mClutchWear,clutch_overheated=raw.mClutchOverheated,clutch_slipping=raw.mClutchSlipping,yellow=raw.mYellowFlagState},
            in_pits=next.PitData.InPitlane,
            leader_pitting=next.PitData.LeaderIsPitting, ahead_pitting=next.PitData.CarInFrontIsPitting, behind_pitting=next.PitData.CarBehindIsPitting,
            flag=session.Flag.ToString(), fcy=next.FlagData.fcyPhase.ToString(),
            frozen_phase=next.FrozenOrderData.Phase.ToString(), frozen_action=next.FrozenOrderData.Action.ToString(),
            opponents=next.OpponentData.ToDictionary(p=>p.Key,p=>(object)new {
                name=p.Value.DriverRawName, position=p.Value.OverallPosition, class_position=p.Value.ClassPosition,
                car_class=p.Value.CarClass.carClassEnum.ToString(), in_pits=p.Value.InPits,
                entered_pits=p.Value.JustEnteredPits, laps=p.Value.CompletedLaps, sector=p.Value.CurrentSectorNumber,
                new_lap=p.Value.IsNewLap
            }),
            suppressed_writes=SuppressedWrites.ToArray()
        };
    }
    public static string Execute(string input) {
        var item=JsonConvert.DeserializeObject<Newtonsoft.Json.Linq.JObject>(input);
        string op=(string)item["op"];
        if(op=="layout") return Layout();
        if(op=="reset") { Reset(); return "{\"reset\":true}"; }
        if(op=="name") return JsonConvert.SerializeObject(new {name=NormaliseName((string)item["name"])});
        if(op=="queue_test") return JsonConvert.SerializeObject(PaddockOriginalEvents.QueueTest(item,state));
        if(op=="command") {
            CrewChiefV4.SpeechRecogniser.sreSessionId++;
            PaddockOriginalEvents.SetWaitingForSpeech((bool?)item["waiting_for_speech"]==true);
            return JsonConvert.SerializeObject(PaddockOriginalEvents.Command((string)item["command"],state,item["ack"],(string)item["text"]));
        }
        if(op=="speech_result") {
            PaddockOriginalEvents.SetWaitingForSpeech((bool?)item["waiting_for_speech"]==true);
            return JsonConvert.SerializeObject(PaddockOriginalEvents.SpeechResult(
                state,(bool?)item["recognised"]==true,(bool?)item["clearly_ok"]==true,
                (bool?)item["detected_speech"]==true,(bool?)item["voice_enabled"]==true,item["ack"]));
        }
        if(op=="map") {
            var raw=item["raw"].ToObject<CrewChiefV4.AMS2.ams2APIStruct>();
            var next=Map(raw,(long)item["ticks"]);
            var result=Newtonsoft.Json.Linq.JObject.FromObject(Snapshot(next));
            if((bool?)item["events"]==true) {
                PaddockOriginalEvents.SetWaitingForSpeech((bool?)item["waiting_for_speech"]==true);
                CrewChiefV4.GameState.GlobalBehaviourSettings.useFahrenheit=(bool?)item["fahrenheit"]==true;
                CrewChiefV4.GameState.GlobalBehaviourSettings.useMetric=(bool?)item["fuel_gallons"]!=true;
                CrewChiefV4.MainWindow.voiceOption=(bool?)item["voice_enabled"]==true?CrewChiefV4.MainWindow.VoiceOptionEnum.HOLD:CrewChiefV4.MainWindow.VoiceOptionEnum.DISABLED;
                var events=PaddockOriginalEvents.Process(previousMappedState,next,previousPositionMappedState,(bool?)item["weather_available"]==true,(bool?)item["engine_available"]==true,(bool?)item["damage_available"]==true,
                    (bool?)item["fuel_available"]==true,(bool?)item["race_time_available"]==true,(bool?)item["pit_available"]==true,
                    raw.mEnforcedPitStopLap>=0 || next.PitData.HasMandatoryPitStop,
                    raw.mPitSchedule==(uint)CrewChiefV4.AMS2.ePitSchedule.PIT_SCHEDULE_PLAYER_REQUESTED || raw.mPitSchedule==(uint)CrewChiefV4.AMS2.ePitSchedule.PIT_SCHEDULE_PITSPOT_OCCUPIED,
                    (bool?)item["position_available"]==true,(bool?)item["lap_counter_available"]==true,(bool?)item["timings_available"]==true,(bool?)item["tyres_available"]==true,(bool?)item["lap_times_available"]==true,item["ack"]);
                result["events"]=Newtonsoft.Json.Linq.JObject.FromObject(events);
            }
            return result.ToString(Newtonsoft.Json.Formatting.None);
        }
        throw new ArgumentException("Unknown mapper operation");
    }
    public static void Run(string defaults, string sounds, string installation) {
        var output=Console.Out;
        Console.SetOut(Console.Error); // Original diagnostics never contaminate JSON.
        try {
            var documents=Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            Initialise(defaults,Path.Combine(installation,"carClassData.json"),
                Path.Combine(documents,"CrewChiefV4","carClassData.json"),
                Path.Combine(installation,"trackLandmarksData.json"),
                Path.Combine(documents,"CrewChiefV4","Track_landmarks"));
            // Read the installed corner sound inventory as metadata. Do not load
            // SoundCache (it can construct player devices and create name files).
            string corners=Path.Combine(sounds,"voice","corners");
            if(Directory.Exists(corners)) foreach(string folder in Directory.GetDirectories(corners))
                if(Directory.EnumerateFiles(folder,"*.wav").Any()) CrewChiefV4.Audio.SoundCache.soundSets["corners/"+Path.GetFileName(folder)]=null;
            PaddockOriginalEvents.Initialise(sounds);
            PaddockMapperStartup.Prepare();
            output.WriteLine("{\"ready\":true}"); output.Flush();
            string line;
            while((line=Console.ReadLine())!=null) {
                try { output.WriteLine(Execute(line)); }
                catch(Exception error) { output.WriteLine(JsonConvert.SerializeObject(new {error=error.ToString()})); }
                output.Flush();
            }
        } catch(Exception error) { output.WriteLine(JsonConvert.SerializeObject(new {error=error.ToString()})); output.Flush(); }
    }
}
