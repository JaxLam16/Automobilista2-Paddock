// Headless I/O only. All fuel/event/benchmark decisions are original sources.
using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;
using CrewChiefV4.GameState;

namespace CrewChiefV4 {
    public static partial class DataFiles { public static string fuel_usage,pit_benchmarks; }
    public partial class CrewChief { public static bool loadDataFromFile=false; }
    public sealed partial class MainWindow {
        // Private equivalent of the original numeric control; never creates UI
        // or reads/writes the installed application's preferences.
        public sealed class PrivateFuelControl { public string Text="1"; }
        public readonly PrivateFuelControl numericUpDownfuelMultiplier=new PrivateFuelControl();
    }
    public sealed partial class SpeechRecogniser {
        public static Dictionary<string,string[]> FuelPhrases=new Dictionary<string,string[]>();
        public static Dictionary<string[],int> numberToNumber=new Dictionary<string[],int>();
        public static string[] LAP,LAPS,MINUTE,MINUTES,HOUR,HOURS,WHATS_MY_FUEL_LEVEL,WHATS_MY_FUEL_USAGE,
            HOW_MUCH_FUEL_TO_END_OF_RACE,CALCULATE_FUEL_FOR,HOWS_MY_FUEL,CAR_STATUS,STATUS;
        public static void InitialiseFuelSpeech(string json) {
            FuelPhrases=JsonConvert.DeserializeObject<Dictionary<string,string[]>>(json);
            numberToNumber.Clear();for(int i=1;i<=199;i++) numberToNumber.Add(FuelPhrases[i.ToString()],i);
            LAP=FuelPhrases["LAP"];LAPS=FuelPhrases["LAPS"];MINUTE=FuelPhrases["MINUTE"];MINUTES=FuelPhrases["MINUTES"];
            HOUR=FuelPhrases["HOUR"];HOURS=FuelPhrases["HOURS"];WHATS_MY_FUEL_LEVEL=FuelPhrases["WHATS_MY_FUEL_LEVEL"];
            WHATS_MY_FUEL_USAGE=FuelPhrases["WHATS_MY_FUEL_USAGE"];HOW_MUCH_FUEL_TO_END_OF_RACE=FuelPhrases["HOW_MUCH_FUEL_TO_END_OF_RACE"];
            CALCULATE_FUEL_FOR=FuelPhrases["CALCULATE_FUEL_FOR"];HOWS_MY_FUEL=FuelPhrases["HOWS_MY_FUEL"];
            CAR_STATUS=FuelPhrases["CAR_STATUS"];STATUS=FuelPhrases["STATUS"];
        }
    }
    public static class FuelHost {
        public static bool LegacyInitialised {get{return (bool)typeof(CrewChiefV4.Events.Fuel_legacy).GetField("initialised",System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Instance).GetValue(CrewChiefV4.Events.Fuel.legacy_inst);}}
        public static void Initialise() {
            string directory,speech;
            if(UserSettings.Values.TryGetValue("__paddock_state_directory",out directory)) {
                directory=Path.GetFullPath(directory);Directory.CreateDirectory(directory);
                DataFiles.fuel_usage=Path.Combine(directory,"fuel_usage.json");
                DataFiles.pit_benchmarks=Path.Combine(directory,"pit_benchmarks.json");
            }
            if(!UserSettings.Values.TryGetValue("__paddock_fuel_speech",out speech))
                speech=File.ReadAllText(Path.Combine(Path.GetDirectoryName(typeof(FuelHost).Assembly.Location),"fuel_speech.json"));
            SpeechRecogniser.InitialiseFuelSpeech(speech);
            CrewChief.fuelMultiplier=new CrewChief.FuelMultiplier(CrewChief.gameDefinition.fuelMultiplierType);
            string multiplier;
            if(UserSettings.Values.TryGetValue("__paddock_fuel_multiplier",out multiplier)) {
                int value;if(!int.TryParse(multiplier,out value)||value<0||value>10)throw new ArgumentException("Invalid private fuel multiplier");
                MainWindow.instance.numericUpDownfuelMultiplier.Text=value.ToString();
            }
            CrewChiefV4.Events.BenchmarkHelper.loadBenchmarks();
        }
    }
}
namespace CrewChiefV4.Events {
    partial class Fuel {
        public bool PaddockInitialised {get{return initialised;}}
        public object PaddockState() {return new {initialised,currentFuel,fuelCapacity,averageUsagePerLap,
            consumptionPerLap=getConsumptionPerLap(),lapsRemaining,sessionNumberOfLaps,reserveMultiplier,
            savedSamples=persistedAverageUsagePerLap.Count,measuredSamples=historicAverageUsagePerLap.Count,
            LapsRemaining,LapsUntilRefuel,FuelAddedInLastStop};}
    }
    public static partial class Strategy {
        public static readonly bool persistBenchmarks=CrewChiefV4.UserSettings.GetUserSettings().getBoolean("persist_pitstop_benchmark_times");
        public static bool naggedAboutBenchmarks=false,playPitPositionEstimates=false;
    }
}
namespace CrewChiefV4.UserInterface.TopicWindows {
    // Actual original topic calculations still run; retain display values without
    // constructing original WinForms windows. No topic data is used as advice.
    public static class TopicWindowFuel {
        public static bool Active;public static float TimeLeft;
        public static object Fuel,Energy;
        public static void ResetData() {Active=false;TimeLeft=float.NaN;Fuel=Energy=null;}
        public static void SetFuelUseActive(bool value) {Active=value;}
        public static void SetTimeLeft(float value) {TimeLeft=value;}
        public static void SetFuelData(float remaining,int capacity,float perLap,float perMinute,float? target,bool finish) {
            Fuel=new {remaining,capacity,perLap,perMinute,target,finish};
        }
        public static void SetVirtualEnergyData(bool available,float remaining,int ratio,float perLap,float perMinute,float? target,bool finish) {
            Energy=new {available,remaining,ratio,perLap,perMinute,target,finish};
        }
    }
}
namespace CrewChiefV4.LMU {
    public static class VirtualEnergy { public static int Read() {if(!CrewChiefV4.Game.LMU)return -1;throw new NotSupportedException("This host only supports AMS2");} }
    // Unreachable LMU-only compile boundary; no HTTP or pit-menu client exists.
    public class LMUPitMenuAPI {public List<Entry> cachedPitMenu;public class Entry {public string name;public double currentSetting;public List<Setting> settings;}public class Setting {public string text;}}
}
namespace CrewChiefV4.PitMenuAPI { public class LMUPitMenuAbstractionLayer { public object pmc;public static LMUPitMenuAbstractionLayer inst {get{throw new NotSupportedException("LMU pit menu unavailable in AMS2 host");}} } }
namespace CrewChiefV4.LFS { public static class LFSInSimReader {
    public static void SendFuelStatus(float current,float usage,int laps,float needed){throw new NotSupportedException("LFS unavailable in AMS2 host");}
    public static string GetLocalizedMessage(string key,string fallback,params object[] values){throw new NotSupportedException("LFS unavailable in AMS2 host");}
    public static void SendMessageLocal(string text){throw new NotSupportedException("LFS unavailable in AMS2 host");}
} }
