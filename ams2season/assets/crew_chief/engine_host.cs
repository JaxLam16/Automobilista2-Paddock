// Isolated adapters for original EngineMonitor.cs. No devices, profiles or UI.
using System.IO;
using System.Collections;
using System.Globalization;
using System.Web.Script.Serialization;

namespace CrewChiefV4.GameState {
    public enum SessionPhase { Green, Checkered, FullCourseYellow }
    public enum SessionType { Practice, Qualify, PrivateQualify, Race, HotLap }
    public enum DamageLevel { UNKNOWN, NONE, TRIVIAL, MINOR, MAJOR, DESTROYED }
    public class DamageStatus { public bool hasValueAtLevel(DamageLevel d) { return false; } }
    public class DamageData {
        public DamageLevel OverallEngineDamage = DamageLevel.UNKNOWN;
        public DamageLevel OverallTransmissionDamage = DamageLevel.UNKNOWN;
        public DamageStatus SuspensionDamageStatus = new DamageStatus();
    }
    public class SessionInfo { public double SessionRunningTime; public SessionType SessionType; }
    public class PitInfo { public bool InPitlane; }
    public class MotionInfo { public float CarSpeed; }
    public class CarClass {
        public float maxSafeWaterTemp, maxSafeOilTemp;
        public bool isBatteryPowered;
    }
    public class EngineInfo {
        public float EngineOilTemp, EngineWaterTemp, EngineOilPressure;
        public int MinutesIntoSessionBeforeMonitoring = 2;
        // The AMS2 mapper does not populate pressure/water warnings. Keep false.
        public bool EngineOilPressureWarning, EngineFuelPressureWarning, EngineWaterTempWarning, EngineStalledWarning;
    }
    public class GameStateData {
        public DateTime Now;
        public CarClass carClass = new CarClass();
        public SessionInfo SessionData = new SessionInfo();
        public PitInfo PitData = new PitInfo();
        public MotionInfo PositionAndMotionData = new MotionInfo();
        public DamageData CarDamageData = new DamageData();
        public EngineInfo EngineData = new EngineInfo();
    }
    public class GlobalBehaviourSettings { public static bool justTheFacts, useFahrenheit; }
}
namespace CrewChiefV4 {
    public class CrewChief { public static GameState.GameStateData currentGameState; }
    public class Log { public static void Commentary(string s) {} }
    public class SpeechCommands {
        public enum ID { NONE, CAR_STATUS, HOW_ARE_MY_ENGINE_TEMPS, STATUS, WHAT_ARE_MY_ENGINE_TEMPS,
                         WHAT_IS_MY_OIL_TEMP, WHAT_IS_MY_WATER_TEMP }
        public static ID SpeechToCommand(List<ID> commands, string text) {
            ID id;
            return Enum.TryParse<ID>(text, out id) && commands.Contains(id) ? id : ID.NONE;
        }
    }
    public class QueuedMessage {
        public string name; public int expiry, priority; public List<object> fragments;
        public QueuedMessage(string name, int expiry, List<object> fragments = null,
                             object abstractEvent = null, int priority = 0) {
            this.name=name; this.expiry=expiry; this.priority=priority;
            this.fragments=fragments ?? new List<object> { name };
        }
    }
}
namespace CrewChiefV4.Audio {
    public class SoundCache { public static HashSet<string> availableSounds = new HashSet<string>(); }
    public class AudioPlayer {
        public static string folderNoData = "acknowledge/no_data";
        public List<object> calls = new List<object>();
        void Capture(CrewChiefV4.QueuedMessage m, bool immediate) {
            calls.Add(new { folder=m.name, fragments=m.fragments, expires_s=m.expiry,
                            priority=m.priority, immediate=immediate });
        }
        public void playMessage(CrewChiefV4.QueuedMessage m) { Capture(m, false); }
        public void playMessageImmediately(CrewChiefV4.QueuedMessage m) { Capture(m, true); }
    }
}
namespace CrewChiefV4.Events {
    public abstract class AbstractEvent {
        protected CrewChiefV4.Audio.AudioPlayer audioPlayer;
        public virtual List<GameState.SessionPhase> applicableSessionPhases { get { return null; } }
        public abstract void clearState();
        protected abstract void triggerInternal(GameState.GameStateData previous, GameState.GameStateData current);
        public void trigger(GameState.GameStateData previous, GameState.GameStateData current) { triggerInternal(previous,current); }
        public virtual SpeechCommands.ID HandlesEvent(string text) { return SpeechCommands.ID.NONE; }
        public virtual void respond(string text) {}
        public virtual void respond(string text, SpeechCommands.ID cmd) {}
        public static List<object> MessageContents(params object[] items) { return new List<object>(items); }
        protected string getTempUnit() { return GameState.GlobalBehaviourSettings.useFahrenheit ? "conditions/fahrenheit" : "conditions/celsius"; }
        protected int convertTemp(float temp, int precision) {
            if (GameState.GlobalBehaviourSettings.useFahrenheit) temp=(int)Math.Round(temp*9f/5f+32f);
            return (int)(Math.Round(temp/(double)precision)*precision);
        }
    }
}

public class PaddockEngineHost {
    static JavaScriptSerializer json = new JavaScriptSerializer();
    static float Number(Dictionary<string,object> p, string key) { return Convert.ToSingle(p[key],CultureInfo.InvariantCulture); }
    public static void Run(string sounds) {
        var output=Console.Out; Console.SetOut(TextWriter.Null);
        foreach (string folder in new [] { "engine_monitor/oil_temp_intro", "engine_monitor/water_temp_intro" })
            if (Directory.Exists(Path.Combine(sounds,"voice",folder)) &&
                Directory.GetFiles(Path.Combine(sounds,"voice",folder),"*.wav").Length>0)
                CrewChiefV4.Audio.SoundCache.availableSounds.Add(folder);
        var audio = new CrewChiefV4.Audio.AudioPlayer();
        var monitor = new CrewChiefV4.Events.EngineMonitor(audio);
        CrewChiefV4.GameState.GameStateData previous = null;
        Action<object> reply = value => { output.WriteLine(json.Serialize(value)); output.Flush(); };
        reply(new { ready=true, version="4.19.5.4" });
        string line;
        while ((line=Console.ReadLine())!=null) {
            try {
                var p=json.Deserialize<Dictionary<string,object>>(line);
                if ((bool)p["reset"]) { monitor.clearState(); previous=null; }
                var state = new CrewChiefV4.GameState.GameStateData();
                state.Now=new DateTime(2026,1,1,0,0,0,DateTimeKind.Utc).AddSeconds(Number(p,"t"));
                state.SessionData.SessionRunningTime=Number(p,"running_s");
                state.SessionData.SessionType=(CrewChiefV4.GameState.SessionType)Enum.Parse(typeof(CrewChiefV4.GameState.SessionType),(string)p["session"]);
                state.EngineData.EngineOilTemp=Number(p,"oil_c");
                state.EngineData.EngineWaterTemp=Number(p,"water_c");
                state.EngineData.EngineOilPressure=Number(p,"oil_pressure");
                state.carClass.maxSafeOilTemp=Number(p,"oil_limit");
                state.carClass.maxSafeWaterTemp=Number(p,"water_limit");
                state.carClass.isBatteryPowered=(bool)p["battery"];
                state.PositionAndMotionData.CarSpeed=Number(p,"speed");
                state.PitData.InPitlane=(bool)p["pit"];
                // Stalled requires transmission/suspension health not fully supplied
                // by the current adapter. Withheld rather than assuming healthy.
                state.EngineData.EngineStalledWarning=false;
                CrewChiefV4.GameState.GlobalBehaviourSettings.useFahrenheit=(bool)p["fahrenheit"];
                CrewChiefV4.CrewChief.currentGameState=state;
                audio.calls.Clear();
                if (p.ContainsKey("command")) monitor.respond((string)p["command"]);
                else monitor.trigger(previous,state);
                previous=state;
                reply(new { calls=audio.calls });
            } catch(Exception e) { reply(new {error=e.GetType().Name+": "+e.Message}); }
        }
    }
}
