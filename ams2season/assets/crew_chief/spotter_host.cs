// Paddock adapters for the unmodified Crew Chief 4.19.5.4 spotter algorithm.
// No game access, audio devices, user profiles, network access or preference writes.
using System;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Web.Script.Serialization;

namespace CrewChiefV4.RaceRoom.RaceRoomData { public class Unused {} }
namespace CrewChiefV4.Events { public class Unused {} }
namespace CrewChiefV4.iRacing {
    public enum CarLeftRight { irsdk_LROff, irsdk_LRClear, irsdk_LRCarLeft, irsdk_LRCarRight,
        irsdk_LRCarLeftRight, irsdk_LR2CarsLeft, irsdk_LR2CarsRight }
}
namespace CrewChiefV4.GameState {
    public class GameStateData { public static bool onManualFormationLap; }
    public class GlobalBehaviourSettings {
        public static CrewChiefV4.CrewChief.RacingType racingType = CrewChiefV4.CrewChief.RacingType.Circuit;
        public static bool useOvalLogic, ovalSpotterMode;
    }
}
namespace CrewChiefV4 {
    public class CrewChief { public enum RacingType { Circuit } }
    public class Utilities { public static Random random = new Random(0); }
    public class PaddockClock { public static DateTime UtcNow; }
    public class UserSettings {
        public static Dictionary<string, object> Values;
        static UserSettings instance = new UserSettings();
        public static UserSettings GetUserSettings() { return instance; }
        public float getFloat(string key) { return Convert.ToSingle(Values[key], CultureInfo.InvariantCulture); }
        public int getInt(string key) { return Convert.ToInt32(Values[key], CultureInfo.InvariantCulture); }
        public bool getBoolean(string key) { return Convert.ToBoolean(Values[key]); }
        public string getString(string key) { return Convert.ToString(Values[key]); }
        public void setProperty(string key, object value) { throw new InvalidOperationException("Preferences are read-only."); }
        public void saveUserSettings() { throw new InvalidOperationException("Preferences are read-only."); }
    }
    public class QueuedMessage {
        public string folder; public int expires;
        public QueuedMessage(string folder, int expires) { this.folder = folder; this.expires = expires; }
    }
}
namespace CrewChiefV4.Audio {
    public class AudioPlayer {
        public static string soundFilesPathNoChiefOverride;
        public bool busy;
        public List<object> calls = new List<object>();
        public void removeImmediateMessages(List<string> folders) {
            calls.RemoveAll(c => folders.Contains((string)((Dictionary<string, object>)c)["folder"]));
        }
        public bool isChannelOpen() { return busy; }
        public void playSpotterMessage(CrewChiefV4.QueuedMessage message, bool keepOpen) {
            calls.Add(new Dictionary<string, object> { {"folder", message.folder},
                {"expires_ms", message.expires}, {"keep_open", keepOpen} });
        }
    }
}

public class PaddockSpotterHost {
    static JavaScriptSerializer json = new JavaScriptSerializer();
    static CrewChiefV4.NoisyCartesianCoordinateSpotter spotter;
    static CrewChiefV4.Audio.AudioPlayer audio = new CrewChiefV4.Audio.AudioPlayer();
    static float[] Floats(object value) {
        return ((IEnumerable)value).Cast<object>().Select(v => Convert.ToSingle(v, CultureInfo.InvariantCulture)).ToArray();
    }
    static void Write(object value) { Console.Out.WriteLine(json.Serialize(value)); Console.Out.Flush(); }
    public static void Run(string defaults, string sounds) {
        var protocol = Console.Out;
        // Upstream uses Console.WriteLine for debug logs; keep stdout exclusively JSON.
        Console.SetOut(TextWriter.Null);
        CrewChiefV4.UserSettings.Values = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(defaults));
        CrewChiefV4.Audio.AudioPlayer.soundFilesPathNoChiefOverride = sounds;
        Action<object> reply = value => { protocol.WriteLine(json.Serialize(value)); protocol.Flush(); };
        reply(new { ready = true, version = "4.19.5.4" });
        string line;
        while ((line = Console.ReadLine()) != null) {
            try {
                var request = json.Deserialize<Dictionary<string, object>>(line);
                double seconds = Convert.ToDouble(request["t"], CultureInfo.InvariantCulture);
                CrewChiefV4.PaddockClock.UtcNow = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(seconds);
                if (spotter == null || (request.ContainsKey("reset") && (bool)request["reset"]))
                    spotter = new CrewChiefV4.NoisyCartesianCoordinateSpotter(audio, true,
                        Convert.ToSingle(request["length"]), Convert.ToSingle(request["width"]));
                audio.calls.Clear();
                audio.busy = request.ContainsKey("busy") && (bool)request["busy"];
                CrewChiefV4.GameState.GlobalBehaviourSettings.useOvalLogic = (bool)request["oval"];
                CrewChiefV4.GameState.GlobalBehaviourSettings.ovalSpotterMode = (bool)request["deprioritize"];
                CrewChiefV4.GameState.GameStateData.onManualFormationLap = false;
                if (!request.ContainsKey("suspend") || !(bool)request["suspend"]) {
                    var opponents = ((IEnumerable)request["opponents"]).Cast<object>().Select(Floats).ToList();
                    spotter.triggerInternal(Convert.ToSingle(request["rotation"]), Floats(request["position"]),
                        Floats(request["velocity"]), opponents);
                }
                var flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic;
                int left = (int)spotter.GetType().GetField("carsOnLeftAtPreviousTick", flags).GetValue(spotter);
                int right = (int)spotter.GetType().GetField("carsOnRightAtPreviousTick", flags).GetValue(spotter);
                reply(new { calls = audio.calls, overlap = spotter.hasOverlap, left = left, right = right });
            } catch (Exception e) { reply(new { error = e.GetType().Name + ": " + e.Message }); }
        }
    }
}
