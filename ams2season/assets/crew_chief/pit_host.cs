// Headless boundary for unsupported, unreachable R3E pit menu operations.
using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;
using CrewChiefV4.GameState;
using CrewChiefV4.Events;
namespace CrewChiefV4 {
    public sealed partial class SpeechRecogniser {
        public static Dictionary<string,string[]> PitPhrases;
    }
    public static class PitHost {
        public static bool ObservedPair,MandatoryKnown,OccupancyKnown;
        static object Field(PitStops pit,string name) {
            return typeof(PitStops).GetField(name,System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic).GetValue(pit);
        }
        public static void Initialise() {
            SpeechRecogniser.PitPhrases=JsonConvert.DeserializeObject<Dictionary<string,string[]>>(
                File.ReadAllText(Path.Combine(Path.GetDirectoryName(typeof(PitHost).Assembly.Location),"pit_speech.json")));
        }
        public static void Reset(){ObservedPair=MandatoryKnown=OccupancyKnown=false;}
        public static void Observe(GameStateData previous,GameStateData current,bool mandatoryKnown,bool occupancyKnown){
            ObservedPair=previous!=null;
            MandatoryKnown=mandatoryKnown;
            OccupancyKnown=occupancyKnown;
        }
        internal static string Unsupported(PitStops pit,GameStateData state,string command) {
            if(!ObservedPair)return "pit history is warming up";
            if(command=="DO_I_HAVE_A_MANDATORY_PIT_STOP" && (!MandatoryKnown ||
                state.PitData.HasMandatoryPitStop && !(bool)Field(pit,"pitDataInitialised")))
                return "mandatory stop history or window is not confirmed";
            if(command=="IS_MY_PIT_BOX_OCCUPIED" && !OccupancyKnown)
                return "AMS2 has not confirmed pit-stall availability";
            if(command=="HOW_MANY_LAPS_SINCE_PITTING" && (DateTime)Field(pit,"pitEntryTime")==DateTime.MinValue)
                return "original mapper cannot establish the last pit timestamp without box coordinates";
            return null;
        }
        internal static object State(PitStops pit,GameStateData state) {
            var data=new Dictionary<string,object>();
            foreach(string name in new [] {"pitDataInitialised","hasMandatoryPitStop","mandatoryStopCompleted","mandatoryStopMissed",
                "pitWindowOpenLap","pitWindowClosedLap","pitWindowOpenTime","pitWindowClosedTime","inPitWindow","pitStallOccupied","pitEntryTime","pitEntryLap"})data[name]=Field(pit,name);
            return new {observed_pair=ObservedPair,mandatory_known=MandatoryKnown,occupancy_known=OccupancyKnown,data=data,
                mapped=state==null?null:new {state.PitData.InPitlane,state.PitData.HasRequestedPitStop,state.PitData.IsPitCrewReady,
                    state.PitData.IsPitCrewDone,state.PitData.PitStallOccupied,state.PitData.PitSpeedLimit,
                    state.PitData.PitBoxPositionEstimate,limiter=state.PitData.limiterStatus.ToString()}};
        }
    }
}
namespace CrewChiefV4.R3E {
    public enum SelectedItem { Fronttires,Reartires,Fuel,Frontwing,Rearwing,Suspension,Penalty }
    public enum PitSelectionState { SELECTED,AVAILABLE,UNAVAILABLE }
    public static class R3EPitMenuManager {
        static Exception Unsupported(){return new NotSupportedException("R3E pit menu is unavailable in the AMS2-only host");}
        public static bool outstandingPitstopRequest {get{throw Unsupported();}set{throw Unsupported();}}
        public static DateTime timeWeCanAnnouncePitActions {get{throw Unsupported();}set{throw Unsupported();}}
        public static bool hasStateForCurrentSession {get{throw Unsupported();}}
        public static Dictionary<SelectedItem,PitSelectionState> latestState {get{throw Unsupported();}}
        public static void openPitMenuIfClosed(){throw Unsupported();}
        public static void closePitMenuIfOpen(int delay){throw Unsupported();}
    }
}
namespace CrewChiefV4.Audio {
    // Original background selection is retained for the pending channel mixer.
    // No device or sound preference is opened by this metadata-only boundary.
    public sealed class MetadataBackgroundPlayer {
        public string Selected;
        public void setBackgroundSound(string name){Selected=name;}
    }
    public partial class AudioPlayer {
        readonly MetadataBackgroundPlayer backgroundPlayer=new MetadataBackgroundPlayer();
        public object PaddockBackgroundState(){return new {selected=backgroundPlayer.Selected,mixed=false};}
        public void PaddockResetBackground(){backgroundPlayer.Selected=null;}
    }
}
