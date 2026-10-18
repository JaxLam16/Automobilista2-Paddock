// Read-only AMS2 flag input adapters. No guessed incidents, stock-car rules or names.
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using CrewChiefV4.GameState;

namespace CrewChiefV4 {
    public class CrewChief { public static bool yellowFlagMessagesEnabled=true; }
    public class UserSettings {
        public static Dictionary<string,object> Values;
        static UserSettings instance=new UserSettings();
        public static UserSettings GetUserSettings() { return instance; }
        public int getInt(string key) { return Convert.ToInt32(Values[key],CultureInfo.InvariantCulture); }
        public bool getBoolean(string key) { return Convert.ToBoolean(Values[key]); }
        public string getString(string key) { return Convert.ToString(Values[key]); }
    }
    public class CarData {
        public class CarClass { public string id=""; public string getClassIdentifier() { return id; } }
        public static bool IsCarClassEqual(CarClass a,CarClass b) { return a.id==b.id; }
    }
    public class DriverNameHelper { public static string getUsableDriverName(string name) { return name; } }
    public class TrackData { public static string getLandmarkForLapDistance(TrackDefinition track,float distance) { return null; } }
}
namespace CrewChiefV4.NumberProcessing {
    public class CarNumber {
        public CarNumber(string number) {}
        public List<CrewChiefV4.MessageFragment> getMessageFragments() { throw new NotSupportedException("AMS2 stock-car rules unavailable."); }
    }
}
namespace CrewChiefV4.GameState {
    public class SafetyCarData { public bool fcySafetyCarCallsEnabled; }
    public class DeltaTime { public float totalDistanceTravelled; }
    public class LapData { public bool IsValid=true; }
    public class OpponentData {
        public string DriverRawName, CarNumber, stoppedInLandmark;
        public int ClassPosition, OverallPosition, CompletedLaps, CurrentSectorNumber;
        public float DistanceRoundTrack, Speed;
        public bool InPits, IsNewLap, EnteringPits;
        public CarData.CarClass CarClass=new CarData.CarClass();
        public DeltaTime DeltaTime=new DeltaTime();
        public bool isEnteringPits() { return EnteringPits; }
        public LapData getCurrentLapData() { return null; }
        public bool IsBehindWithinDistance(GameStateData state,float min,float max) { throw new NotSupportedException("AMS2 stock-car rules unavailable."); }
    }
    public partial class GameStateData {
        // Used only by the disabled stock-car rules in the original source.
        public OpponentData getOpponentAtOverallPosition(int position) { return OpponentData.Values.FirstOrDefault(o=>o.OverallPosition==position); }
        public OpponentData getOpponentAtClassPosition(int position,CarData.CarClass cls) { return OpponentData.Values.FirstOrDefault(o=>o.ClassPosition==position && o.CarClass.id==cls.id); }
        public OpponentData getOpponentForName(string name) { return OpponentData.Values.FirstOrDefault(o=>o.DriverRawName==name); }
        public OpponentData getOpponentInFront(CarData.CarClass cls) { return getOpponentAtClassPosition(SessionData.ClassPosition-1,cls); }
    }
}
public class PaddockFlagsAdapter {
    // Same mapping as AMS2GameStateMapper.mapToFlagEnum. Raw red/start-stop and
    // chequered remain silent here; their separate event logic is not invented.
        public static FlagEnum Map(uint highestFlagColour)
        {
            if (highestFlagColour == (uint)eFlagColour.FLAG_COLOUR_CHEQUERED)
            {
                return FlagEnum.CHEQUERED;
            }
            else if (highestFlagColour == (uint)eFlagColour.FLAG_COLOUR_BLACK)
            {
                return FlagEnum.BLACK;
            }
            else if (highestFlagColour == (uint)eFlagColour.FLAG_COLOUR_DOUBLE_YELLOW)
            {
                return FlagEnum.DOUBLE_YELLOW;
            }
            else if (highestFlagColour == (uint)eFlagColour.FLAG_COLOUR_YELLOW)
            {
                return FlagEnum.YELLOW;
            }
            else if (highestFlagColour == (uint)eFlagColour.FLAG_COLOUR_WHITE_SLOW_CAR)
            {
                return FlagEnum.WHITE;
            }
            else if (highestFlagColour == (uint)eFlagColour.FLAG_COLOUR_BLUE)
            {
                return FlagEnum.BLUE;
            }
            else if (highestFlagColour == (uint)eFlagColour.FLAG_COLOUR_GREEN)
            {
                return FlagEnum.GREEN;
            }
            return FlagEnum.UNKNOWN;
        }

    public static void Populate(GameStateData state,Dictionary<string,object> p) {
        state.SessionData.Flag=Map(p.ContainsKey("flag_colour") && Convert.ToInt32(p["flag_colour"])>=0 ? Convert.ToUInt32(p["flag_colour"]) : UInt32.MaxValue);
        state.SessionData.JustGoneGreen=p.ContainsKey("just_green") && (bool)p["just_green"];
        state.SessionData.ClassPosition=p.ContainsKey("class_position") ? Convert.ToInt32(p["class_position"]) : 1000;
        state.SessionData.OverallPosition=p.ContainsKey("position") ? Convert.ToInt32(p["position"]) : 1000;
        state.SessionData.TrackDefinition.trackLength=p.ContainsKey("track_length") ? Convert.ToSingle(p["track_length"]) : 0;
        // Only observed opponents with valid class position/entry state are sent.
        // Landmark timing and class/driver speech are left unavailable until the
        // corresponding original mapper/name integration is restored.
        if(p.ContainsKey("opponents")) foreach(Dictionary<string,object> row in ((IEnumerable)p["opponents"]).Cast<Dictionary<string,object>>()) {
            var o=new OpponentData { DriverRawName=(string)row["name"],
                ClassPosition=Convert.ToInt32(row["class_position"]), OverallPosition=Convert.ToInt32(row["position"]),
                Speed=Convert.ToSingle(row["speed"]), DistanceRoundTrack=Convert.ToSingle(row["distance"]),
                InPits=(bool)row["pit"], EnteringPits=row.ContainsKey("entering_pits") && (bool)row["entering_pits"] };
            state.OpponentData[(string)row["key"]]=o;
        }
    }
}
