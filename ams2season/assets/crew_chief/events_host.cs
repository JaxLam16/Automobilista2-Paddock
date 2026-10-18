// AMS2 event adapters. Original Penalties.cs owns every decision and validation.
using System.IO;
using System;
using System.Linq;
using System.Collections.Generic;
using System.Collections;
using System.Globalization;
using System.Web.Script.Serialization;

namespace CrewChiefV4.GameState {
    // Preserve the original session-phase ordering for comparisons in events.
    public enum SessionPhase { Unavailable, Garage, Gridwalk, Formation, Countdown, Green, FullCourseYellow, Checkered, Finished }
    public enum SessionType { Unavailable, Practice, Qualify, PrivateQualify, Race, HotLap, LonePractice }
    public enum ControlType { Unavailable, Player, AI, Remote, Replay }
    public class TrackDefinition { public float raceroomRollingStartLapDistance = -1, trackLength; }
    public class SessionData {
        public float SessionRunningTime;
        public int CompletedLaps, CurrentIncidentCount, MaxIncidentCount, SectorNumber;
        public bool HasLimitedIncidents, IsNewLap, CurrentLapIsValid;
        public bool JustGoneGreen, iRacingLoneQualify, IsLastLap;
        public int ClassPosition, OverallPosition, LapCount, LeaderSectorNumber;
        public string DriverRawName, PlayerCarNr, stoppedInLandmark;
        public FlagEnum Flag = FlagEnum.UNKNOWN;
        public DeltaTime DeltaTime = new DeltaTime();
        public SessionType SessionType;
        public SessionPhase SessionPhase;
        public TrackDefinition TrackDefinition = new TrackDefinition();
    }
    public class PitData { public bool InPitlane, OnOutLap, HasRequestedPitStop; }
    public class MotionData { public float CarSpeed, DistanceRoundTrack; }
    public class ControlData { public ControlType ControlType = ControlType.Player; }
    public partial class GameStateData {
        public DateTime Now;
        public SessionData SessionData = new SessionData();
        public PitData PitData = new PitData();
        public MotionData PositionAndMotionData = new MotionData();
        public ControlData ControlData = new ControlData();
        public PenatiesData PenaltiesData = new PenatiesData();
        public static bool onManualFormationLap;
        public FlagData FlagData = new FlagData();
        public StockCarRulesData StockCarRulesData = new StockCarRulesData();
        public SafetyCarData SafetyCarData = new SafetyCarData();
        public Dictionary<string,OpponentData> OpponentData = new Dictionary<string,OpponentData>();
        public CarData.CarClass carClass = new CarData.CarClass();
    }
    public class GlobalBehaviourSettings {
        public static bool cutTrackWarningsEnabled=true, justTheFacts, useAmericanTerms;
        public static int complaintsCountInThisSession, maxComplaintsPerSession;
    }
}
namespace CrewChiefV4 {
    // Other games' branches are compiled but never selected by this AMS2 host.
    public class Game { public static readonly bool AMS2=true, RF1=false, RF2_LMU=false, GTR2=false, RACE_ROOM=false, IRACING=false, ACC=false; }
    public class Utilities { public static Random random = new Random(); }
    public class Log { public static void Debug(Func<string> message) {} }
    public class SpeechCommands {
        public enum ID { NONE, DO_I_HAVE_A_PENALTY, DO_I_STILL_HAVE_A_PENALTY, HAVE_I_SERVED_MY_PENALTY, SESSION_STATUS, STATUS }
        public static ID SpeechToCommand(List<ID> commands,string text) {
            ID id; return Enum.TryParse<ID>(text,out id) && commands.Contains(id) ? id : ID.NONE;
        }
    }
    public delegate void DelayedMessage(GameState.GameStateData state,List<MessageFragment> messages,List<MessageFragment> alt);
    public class MessageFragment {
        public object value;
        public static MessageFragment Text(string text) { return new MessageFragment {value=text}; }
    }
    public class QueuedMessage {
        public string name;
        public int expiresAfter, delay, priority;
        public List<MessageFragment> fragments;
        public Events.AbstractEvent owner;
        public Dictionary<string,object> validationData;
        public Audio.SoundType type;
        public QueuedMessage(string messageName,int expiresAfter,List<MessageFragment> messageFragments=null,
                             int secondsDelay=0,Events.AbstractEvent abstractEvent=null,int priority=0,
                             DelayedMessage delayedMessage=null,Audio.SoundType type=Audio.SoundType.REGULAR_MESSAGE,
                             Dictionary<string,object> validationData=null) {
            if(delayedMessage!=null) throw new NotSupportedException("Non-AMS2 delayed message callback.");
            name=messageName; this.expiresAfter=expiresAfter; delay=secondsDelay;
            fragments=messageFragments ?? new List<MessageFragment> {MessageFragment.Text(messageName)};
            owner=abstractEvent; this.priority=priority;
            this.type=type; this.validationData=validationData;
        }
    }
}
namespace CrewChiefV4.Audio {
    public enum SoundType { REGULAR_MESSAGE, IMPORTANT_MESSAGE, CRITICAL_MESSAGE }
    public class SoundCache { public static HashSet<string> availableSounds = new HashSet<string>(); }
    public class AudioPlayer {
        public static bool canReadName(string name,bool allowTts=true) { return false; }
        public static string folderYes="acknowledge/yes", folderNo="acknowledge/no";
        public double now;
        long serial;
        public Dictionary<string,CrewChiefV4.QueuedMessage> issued=new Dictionary<string,CrewChiefV4.QueuedMessage>();
        public Dictionary<string,double> created=new Dictionary<string,double>();
        public List<object> calls=new List<object>();
        void Capture(CrewChiefV4.QueuedMessage m,bool immediate) {
            string id=(++serial).ToString(CultureInfo.InvariantCulture);
            issued[id]=m; created[id]=now;
            calls.Add(new {id=id,folder=m.name,fragments=m.fragments.Select(f=>f.value).ToList(),
                expires_s=m.expiresAfter,delay_s=m.delay,priority=m.priority,immediate=immediate,
                sound_type=m.type.ToString(),source_event=(m.owner is CrewChiefV4.Events.FlagsMonitor ? "FlagsMonitor" : "Penalties")+"_4.19.5.4"});
        }
        public void playMessage(CrewChiefV4.QueuedMessage m) { Capture(m,false); }
        public void playMessageImmediately(CrewChiefV4.QueuedMessage m) { Capture(m,true); }
        public void removeQueuedMessage(string folder) {
            foreach(var id in issued.Where(p=>p.Value.name==folder).Select(p=>p.Key).ToList()) Forget(id);
        }
        // The installed profile's rant setting is not mapped yet. Keep ordinary
        // fallback wording; do not claim this optional rant path as verified parity.
        public bool playRant(string id,List<CrewChiefV4.MessageFragment> fragments) { return false; }
        public void Forget(string id) { issued.Remove(id); created.Remove(id); }
        public List<string> Validate(CrewChiefV4.GameState.GameStateData state,bool penaltiesAvailable,bool flagsAvailable) {
            foreach(var p in issued.ToList()) {
                var m=p.Value;
                bool expired=m.expiresAfter>0 && now>=created[p.Key]+m.expiresAfter;
                bool valid=(m.owner is CrewChiefV4.Events.FlagsMonitor ? flagsAvailable : penaltiesAvailable) &&
                    (m.owner==null || m.owner.isMessageStillValid(m.name,state,m.validationData));
                if(expired || !valid) Forget(p.Key);
            }
            return issued.Keys.ToList();
        }
    }
}
namespace CrewChiefV4.Events {
    public class LapCounter { public static bool whiteFlagLastLapAnnounced; }
    public class Opponents { public static string folderCarNumber="opponents/car_number"; }
    public class WatchedOpponents { public static HashSet<string> watchedOpponentKeys = new HashSet<string>(); }
    public class PitStops { public static bool isPittingThisLap; public static string folderMandatoryPitStopsPitThisLap="mandatory_pit_stops/pit_this_lap"; }
    public class Ratings { public static string folderYouHave="",folderincidentPoints=""; }
    public class SessionEndMessages { public static string overrideDetailedDisqualifiedMessage; }
    public abstract class AbstractEvent {
        protected enum SIMPLE_INCIDENT_DETECTION_SESSIONS { DISABLED, RACE_ONLY, ALL_SESSIONS };
        protected static SIMPLE_INCIDENT_DETECTION_SESSIONS simpleIncidentDetectionSessions=SIMPLE_INCIDENT_DETECTION_SESSIONS.RACE_ONLY;
        protected Audio.AudioPlayer audioPlayer;
        public virtual List<GameState.SessionPhase> applicableSessionPhases { get { return new List<GameState.SessionPhase> {GameState.SessionPhase.Green,GameState.SessionPhase.Countdown}; } }
        public virtual List<GameState.SessionType> applicableSessionTypes { get { return new List<GameState.SessionType> {GameState.SessionType.Practice,GameState.SessionType.Qualify,GameState.SessionType.PrivateQualify,GameState.SessionType.Race,GameState.SessionType.HotLap,GameState.SessionType.LonePractice}; } }
        public bool isApplicableForCurrentSessionAndPhase(GameState.SessionType type,GameState.SessionPhase phase) { return applicableSessionTypes.Contains(type) && applicableSessionPhases.Contains(phase); }
        public virtual bool isMessageStillValid(string subtype,GameState.GameStateData state,Dictionary<string,object> data) { return state!=null && isApplicableForCurrentSessionAndPhase(state.SessionData.SessionType,state.SessionData.SessionPhase); }
        public abstract void clearState();
        protected abstract void triggerInternal(GameState.GameStateData previous,GameState.GameStateData current);
        public void trigger(GameState.GameStateData previous,GameState.GameStateData current) { triggerInternal(previous,current); }
        public virtual SpeechCommands.ID HandlesEvent(string text) { return SpeechCommands.ID.NONE; }
        public virtual void respond(string text) {}
        public virtual void respond(string text,SpeechCommands.ID cmd) {}
        public static List<MessageFragment> MessageContents(params object[] values) { return values.Select(v=>new MessageFragment {value=v}).ToList(); }
    }
}
public class PaddockEventsHost {
    static JavaScriptSerializer json=new JavaScriptSerializer();
    static double Number(Dictionary<string,object> p,string key) { return Convert.ToDouble(p[key],CultureInfo.InvariantCulture); }
    public static void Run(string settings,string sounds) {
        var output=Console.Out; Console.SetOut(TextWriter.Null);
        var config=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(settings));
        CrewChiefV4.UserSettings.Values=config;
        CrewChiefV4.CrewChief.yellowFlagMessagesEnabled=(bool)config["enable_yellow_flag_messages"];
        CrewChiefV4.GameState.GlobalBehaviourSettings.justTheFacts=(bool)config["just_the_facts"];
        CrewChiefV4.GameState.GlobalBehaviourSettings.cutTrackWarningsEnabled=(bool)config["play_cut_track_warnings"];
        CrewChiefV4.GameState.GlobalBehaviourSettings.maxComplaintsPerSession=Convert.ToInt32(config["max_complaints_per_session"]);
        CrewChiefV4.GameState.GlobalBehaviourSettings.useAmericanTerms=(bool)config["use_american_terms"];
        string newer=Path.Combine(sounds,"voice/penalties/cut_track_race_1");
        if(Directory.Exists(newer) && Directory.GetFiles(newer,"*.wav").Length>0) CrewChiefV4.Audio.SoundCache.availableSounds.Add("penalties/cut_track_race_1");
        var audio=new CrewChiefV4.Audio.AudioPlayer();
        var monitor=new CrewChiefV4.Events.Penalties(audio);
        var flags=new CrewChiefV4.Events.FlagsMonitor(audio);
        CrewChiefV4.GameState.GameStateData previous=null;
        CrewChiefV4.GameState.GameStateData previousPenalty=null;
        Action<object> reply=v=>{ output.WriteLine(json.Serialize(v)); output.Flush(); };
        reply(new {ready=true,version="4.19.5.4"});
        string line;
        while((line=Console.ReadLine())!=null) {
            try {
                var p=json.Deserialize<Dictionary<string,object>>(line);
                if((bool)p["reset"]) { monitor.clearState(); flags.clearState(); previous=null; previousPenalty=null; audio.issued.Clear(); audio.created.Clear(); }
                if(p.ContainsKey("ack")) foreach(object id in (IEnumerable)p["ack"]) audio.Forget((string)id);
                var state=new CrewChiefV4.GameState.GameStateData();
                audio.now=Number(p,"t"); audio.calls.Clear();
                state.Now=new DateTime(2026,1,1,0,0,0,DateTimeKind.Utc).AddSeconds(audio.now);
                state.SessionData.SessionRunningTime=Convert.ToSingle(p["running_s"]);
                state.SessionData.SessionType=(CrewChiefV4.GameState.SessionType)Enum.Parse(typeof(CrewChiefV4.GameState.SessionType),(string)p["session"]);
                state.SessionData.SessionPhase=(CrewChiefV4.GameState.SessionPhase)Enum.Parse(typeof(CrewChiefV4.GameState.SessionPhase),(string)p["phase"]);
                state.SessionData.CompletedLaps=Convert.ToInt32(p["laps"]);
                state.SessionData.SectorNumber=Convert.ToInt32(p["sector"]);
                state.SessionData.CurrentLapIsValid=(bool)p["lap_valid"];
                state.SessionData.IsNewLap=(bool)p["new_lap"];
                state.PitData.InPitlane=(bool)p["pit"];
                state.PitData.OnOutLap=(bool)p["out_lap"];
                state.PositionAndMotionData.CarSpeed=Convert.ToSingle(p["speed"]);
                state.PositionAndMotionData.DistanceRoundTrack=Convert.ToSingle(p["distance"]);
                state.PenaltiesData.HasDriveThrough=(bool)p["drive_through"];
                state.PenaltiesData.HasStopAndGo=(bool)p["stop_go"];
                state.PenaltiesData.CutTrackWarnings=Convert.ToInt32(p["cuts"]);
                PaddockFlagsAdapter.Populate(state,p);
                bool penaltiesAvailable=!p.ContainsKey("penalties_available") || (bool)p["penalties_available"];
                bool flagsAvailable=p.ContainsKey("flag_colour") && Convert.ToInt32(p["flag_colour"])>=0 && Convert.ToInt32(p["flag_colour"])<12;
                if(p.ContainsKey("command")) monitor.respond((string)p["command"]);
                else {
                    // The original event assumes a previous state in its cut branch.
                    // Seed a new session without inventing a previous invalidation.
                    if(penaltiesAvailable) {
                        if(previousPenalty!=null && monitor.isApplicableForCurrentSessionAndPhase(state.SessionData.SessionType,state.SessionData.SessionPhase)) monitor.trigger(previousPenalty,state);
                        previousPenalty=state;
                    } else {
                        monitor.clearState(); previousPenalty=null;
                    }
                    if(flagsAvailable && flags.isApplicableForCurrentSessionAndPhase(state.SessionData.SessionType,state.SessionData.SessionPhase)) flags.trigger(previous,state);
                    previous=state;
                }
                reply(new {calls=audio.calls,valid=audio.Validate(state,penaltiesAvailable,flagsAvailable)});
            } catch(Exception e) { reply(new {error=e.GetType().Name+": "+e.Message}); }
        }
    }
}
