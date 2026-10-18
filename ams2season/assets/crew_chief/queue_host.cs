// Device-free boundary for original queue methods. Original planning is in
// queue_original.cs; audio is retained until actual Paddock playback receipts.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Globalization;
using System.Linq;
using System.Threading;
using CrewChiefV4.GameState;
using CrewChiefV4.Events;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace CrewChiefV4 {
    public static class DriverTrainingService { public static bool isPlayingPaceNotes,isRecordingPaceNotes; }
}
namespace CrewChiefV4.Events {
    // Constants only; these event implementations are still pending.
    // Original SessionEndMessages is compiled separately.
    public static class SmokeTest { public const string SMOKE_TEST="smoke_test_chief",SMOKE_TEST_SPOTTER="smoke_test_spotter"; }
}
namespace CrewChiefV4.Audio {
    public sealed class QueueSoundMetadata {
        public readonly HashSet<string> Personalised=new HashSet<string>();
        public bool eventHasPersonalisedPrefixOrSuffix(string name) { return Personalised.Contains(name); }
    }
    public partial class AudioPlayer {
        public const string folderAcknowlegeEnableKeepQuiet="acknowledge/keepQuietEnabled",
            folderAcknowlegeDisableKeepQuiet="acknowledge/keepQuietDisabled",folderStandBy="acknowledge/stand_by",
            folderDidntUnderstand="acknowledge/didnt_understand",RETAIN_ON_SESSION_END="retain_on_session_end",
            folderAcknowledgeEnableDelayInHardParts="acknowledge/keep_quiet_in_corners_enabled",
            folderAcknowledgeDisableDelayInHardParts="acknowledge/keep_quiet_in_corners_disabled";
        public bool disablePearlsOfWisdom=false,mute=false,holdChannelOpen=false;
        bool playedRantInThisSession=false,allowPearlsOnNextPlay=true,keepQuiet=false,useShortBeepWhenOpeningChannel=false;
        bool regularQueuePaused=false;
        // No monitor thread is created. One original planning scan per pump,
        // rather than original synchronous recursive playback on that thread.
        public bool monitorRunning=false;
        static readonly bool enableRants=UserSettings.GetUserSettings().getBoolean("enable_rants");
        static float rantLikelihood=enableRants?0.1f:0;
        public static bool rantWaitingToPlay=false;
        const string folderRants="rants/general";
        readonly bool sweary=UserSettings.GetUserSettings().getBoolean("use_sweary_messages");
        readonly bool allowImportantMessagesInKeepQuietMode=UserSettings.GetUserSettings().getBoolean("allow_important_messages_even_when_silenced");
        readonly TimeSpan minTimeBetweenPearlsOfWisdom=TimeSpan.FromSeconds(UserSettings.GetUserSettings().getInt("minimum_time_between_pearls_of_wisdom"));
        readonly bool rejectWhileTalking=UserSettings.GetUserSettings().getBoolean("reject_message_when_talking");
        readonly bool respondWhileOpen=UserSettings.GetUserSettings().getBoolean("sre_respond_while_channel_still_open");
        readonly OrderedDictionary queuedClips=new OrderedDictionary(),immediateClips=new OrderedDictionary();
        readonly PearlsOfWisdom pearlsOfWisdom=new PearlsOfWisdom();
        readonly QueueSoundMetadata soundCache=new QueueSoundMetadata();
        readonly AutoResetEvent monitorQueueWakeUpEvent=new AutoResetEvent(false);
        DateTime nextWakeupCheckTime=DateTime.MinValue,timeLastPearlOfWisdomPlayed=GameStateData.CurrentTime;
        DateTime lastImmediateMessageTime=DateTime.MinValue,timeOfLastMessageEnd=DateTime.MinValue;
        string lastImmediateMessageName;
        QueuedMessage lastMessagePlayed;
        DateTime pausedUntil=DateTime.MinValue,heldUntil=DateTime.MinValue;
        readonly Dictionary<QueuedMessage,string> sourceOwners=new Dictionary<QueuedMessage,string>();
        readonly Dictionary<QueuedMessage,string> exported=new Dictionary<QueuedMessage,string>();
        readonly HashSet<string> started=new HashSet<string>();
        readonly List<Tuple<QueuedMessage,DateTime>> delayed=new List<Tuple<QueuedMessage,DateTime>>();
        readonly List<string> readyOrder=new List<string>();
        long serial;
        bool sampleClockSeeded;
        string sourceEvent;
        public bool WaitingForSpeech;
        public string SourceEvent {
            get { return sourceEvent; }
            set { TrackOwners();sourceEvent=value; }
        }
        public readonly Dictionary<string,QueuedMessage> issued=new Dictionary<string,QueuedMessage>();
        public readonly Dictionary<string,string> owners=new Dictionary<string,string>();
        public readonly List<object> calls=new List<object>();
        public readonly List<string> withheld=new List<string>();

        void TrackOwners() {
            foreach(QueuedMessage message in queuedClips.Values.Cast<QueuedMessage>().Concat(immediateClips.Values.Cast<QueuedMessage>()).Concat(delayed.Select(x=>x.Item1)))
                if(!sourceOwners.ContainsKey(message)) sourceOwners[message]=sourceEvent??"AudioPlayer";
        }
        public void InitialiseQueueMetadata() {
            string folders;
            if(UserSettings.Values.TryGetValue("__paddock_personalised_folders",out folders))
                foreach(string folder in JsonConvert.DeserializeObject<List<string>>(folders)) soundCache.Personalised.Add(folder);
        }
        static long NowMs { get { return GameStateData.CurrentTime.Ticks/TimeSpan.TicksPerMillisecond; } }
        // This is the playback I/O boundary, not a substitute event algorithm.
        // Export folders once, preserve original queue order, and keep the items
        // in their original queues until an actual finished/dropped receipt.
        List<string> playSounds(List<string> names,bool immediate,out bool interrupted) {
            interrupted=false;
            var processed=new List<string>();
            var queue=immediate?immediateClips:queuedClips;
            foreach(string name in names) {
                if(!queue.Contains(name)) continue;
                var message=(QueuedMessage)queue[name];
                if(rejectWhileTalking && WaitingForSpeech && !(respondWhileOpen && message.metadata.type!=SoundType.VOICE_COMMAND_RESPONSE)) continue;
                if(message.delayMessageResolution) message.resolveDelayedContents();
                if(!message.canBePlayed || mute) {
                    withheld.Add(name+(!message.canBePlayed?": original sound fragment unavailable":": muted"));
                    processed.Add(name);continue;
                }
                string id;
                if(!exported.TryGetValue(message,out id)) {
                    id="q"+(++serial).ToString(CultureInfo.InvariantCulture);
                    exported[message]=id;issued[id]=message;owners[id]=sourceOwners[message];
                    calls.Add(new {id=id,folder=message.messageName??name,fragments=message.messageFolders??new List<string>{name},
                        folders_resolved=true,queue_managed=true,original_message_id=message.messageId,
                        play_even_when_silenced=message.playEvenWhenSilenced,
                        expires_s=message.expiryTime==0?0:Math.Max(0.001,(message.expiryTime-NowMs)/1000.0),
                        delay_s=0,priority=message.metadata.priority,immediate=immediate,
                        interrupts_regular=immediate && PlaybackModerator.CanPreemptRegular(message.metadata.type),
                        sound_type=message.metadata.type.ToString(),source_event=owners[id]+"_4.19.5.4"});
                }
                readyOrder.Add(id);
            }
            return processed;
        }
        void openRadioChannelInternal() { /* Actual channel/device work stays in Paddock. */ }
        void startHangingChannelCloseThread() { heldUntil=GameStateData.CurrentTime.AddSeconds(6); }
        public void pauseQueue(int seconds) {
            if(!regularQueuePaused) { regularQueuePaused=true;pausedUntil=GameStateData.CurrentTime.AddSeconds(Math.Max(0,seconds)); }
        }
        public void unpauseQueue() { regularQueuePaused=false;monitorQueueWakeUpEvent.Set(); }
        public void playDelayedImmediateMessage(QueuedMessage message) {
            delayed.Add(Tuple.Create(message,GameStateData.CurrentTime.AddSeconds(Math.Max(0,message.secondsDelay))));
            TrackOwners();
        }
        void RemoveReference(OrderedDictionary queue,QueuedMessage message) {
            foreach(string key in queue.Keys.Cast<string>().ToArray()) if(Object.ReferenceEquals(queue[key],message)) queue.Remove(key);
        }
        bool InQueue(QueuedMessage message) {
            return queuedClips.Values.Cast<QueuedMessage>().Concat(immediateClips.Values.Cast<QueuedMessage>()).Contains(message);
        }
        public void Forget(string id) {
            QueuedMessage message;
            if(issued.TryGetValue(id,out message)) {
                RemoveReference(queuedClips,message);RemoveReference(immediateClips,message);
                exported.Remove(message);sourceOwners.Remove(message);
            }
            issued.Remove(id);owners.Remove(id);readyOrder.Remove(id);
            started.Remove(id);
        }
        QueuedMessage PlaybackSnapshot(QueuedMessage message) {
            // The original synchronous player caches this message just before
            // Play. At this asynchronous boundary keep a snapshot, so preparing
            // a repeat cannot mutate the still-playing transport queue item.
            var copy=(QueuedMessage)typeof(object).GetMethod("MemberwiseClone",System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic).Invoke(message,null);
            if(message.messageFolders!=null) copy.messageFolders=new List<string>(message.messageFolders);
            if(message.metadata!=null) copy.metadata=new SoundMetadata {
                messageId=message.metadata.messageId,type=message.metadata.type,priority=message.metadata.priority,
                speechRecognitionSessionID=message.metadata.speechRecognitionSessionID,isListenStartBeep=message.metadata.isListenStartBeep};
            return copy;
        }
        public void Ack(JToken acknowledgements) {
            if(acknowledgements==null) return;
            foreach(var ack in acknowledgements) {
                string id=ack.Type==JTokenType.String?(string)ack:(string)ack["id"];
                string outcome=ack.Type==JTokenType.String?"finished":(string)ack["outcome"];
                QueuedMessage message;
                if(id!=null && issued.TryGetValue(id,out message) && (outcome=="playing" || outcome=="finished" && !started.Contains(id))) {
                    if(message.messageName!=folderDidntUnderstand && message.messageName!=folderStandBy && message.metadata.type!=SoundType.SPOTTER) lastMessagePlayed=PlaybackSnapshot(message);
                    if(clipIsPearlOfWisdom(message.messageName??"")) timeLastPearlOfWisdomPlayed=GameStateData.CurrentTime;
                    started.Add(id);
                }
                if(outcome=="playing") continue;
                if(outcome=="finished") timeOfLastMessageEnd=GameStateData.CurrentTime;
                if(id!=null) Forget(id);
            }
        }
        public void ResetQueue() {
            queuedClips.Clear();immediateClips.Clear();delayed.Clear();issued.Clear();owners.Clear();
            sourceOwners.Clear();exported.Clear();calls.Clear();withheld.Clear();readyOrder.Clear();
            started.Clear();
            regularQueuePaused=false;holdChannelOpen=false;lastMessagePlayed=null;lastImmediateMessageName=null;
            nextWakeupCheckTime=DateTime.MinValue;lastImmediateMessageTime=DateTime.MinValue;
            monitorQueueWakeUpEvent.Reset();PlaybackModerator.Reset();
        }
        public List<string> Validate(GameStateData state,HashSet<string> available) {
            foreach(var pair in issued.ToArray()) {
                var message=pair.Value;
                if(!InQueue(message) || !available.Contains(owners[pair.Key]) || state==null ||
                    message.expiryTime>0 && NowMs>message.expiryTime || !message.isMessageStillValid(message.messageName,state)) Forget(pair.Key);
            }
            return issued.Keys.ToList();
        }
        public void Pump(GameStateData state,HashSet<string> available) {
            if(state!=null && !sampleClockSeeded) { timeLastPearlOfWisdomPlayed=state.Now;sampleClockSeeded=true; }
            TrackOwners();readyOrder.Clear();
            foreach(var item in delayed.ToArray()) {
                if(!available.Contains(sourceOwners[item.Item1])) { delayed.Remove(item);continue; }
                if(GameStateData.CurrentTime>=item.Item2) {
                    delayed.Remove(item);
                    string saved=sourceEvent;sourceEvent=sourceOwners[item.Item1];
                    playMessageImmediately(item.Item1);sourceEvent=saved;
                }
            }
            foreach(var queue in new []{queuedClips,immediateClips}) foreach(string key in queue.Keys.Cast<string>().ToArray())
                if(!available.Contains(sourceOwners[(QueuedMessage)queue[key]])) queue.Remove(key);
            if(regularQueuePaused && GameStateData.CurrentTime>=pausedUntil) unpauseQueue();
            if(holdChannelOpen && GameStateData.CurrentTime>=heldUntil) holdChannelOpen=false;
            wakeMonitorThreadForRegularMessages(GameStateData.CurrentTime);
            bool regularWake=monitorQueueWakeUpEvent.WaitOne(0);
            if(immediateClips.Count>0) {
                if(!WaitingForSpeech || respondWhileOpen) playQueueContents(immediateClips,true);
            } else if(!regularQueuePaused && !holdChannelOpen && regularWake && queuedClips.Count>0) {
                playQueueContents(queuedClips,false);allowPearlsOnNextPlay=true;
            }
            Validate(state,available);
            // Drop references left only by rejected/purged/expired items.
            foreach(var message in sourceOwners.Keys.ToArray()) if(!InQueue(message) && !exported.ContainsKey(message) && !delayed.Any(x=>Object.ReferenceEquals(x.Item1,message))) sourceOwners.Remove(message);
        }
        public object QueueStatus() {
            return new {regular=queuedClips.Count,immediate=immediateClips.Count,delayed=delayed.Count,
                awaiting_receipt=issued.Count,keep_quiet=keepQuiet,paused=regularQueuePaused,
                verbosity=PlaybackModerator.CurrentVerbosity,play_order=readyOrder,
                regular_names=queuedClips.Keys.Cast<string>().ToArray(),immediate_names=immediateClips.Keys.Cast<string>().ToArray(),
                full_audio_player_restored=false};
        }
        bool testTrigger=true;
        public void TestActions(JToken actions,GameStateData state) {
            string enabled;
            if(!UserSettings.Values.TryGetValue("__paddock_queue_test",out enabled) || !Boolean.Parse(enabled)) throw new NotSupportedException("Queue test facade disabled");
            foreach(var action in actions??new JArray()) {
                string op=(string)action["action"];
                switch(op) {
                    case "enqueue":case "delayed": {
                        string folder=(string)action["folder"];
                        if(!SoundCache.availableSounds.Contains(folder)) throw new ArgumentException("Test sound unavailable");
                        Func<GameStateData,bool> trigger=(bool?)action["trigger"]==true?(Func<GameStateData,bool>)(x=>testTrigger):null;
                        var message=new QueuedMessage((string)action["name"]??folder,(int?)action["expiry"]??30,
                            messageFragments:AbstractEvent.MessageContents(folder),secondsDelay:(int?)action["delay"]??0,
                            priority:(int?)action["priority"]??5,type:action["type"]==null?SoundType.AUTO:(SoundType)Enum.Parse(typeof(SoundType),(string)action["type"]),triggerFunction:trigger);
                        message.maxPermittedQueueLengthForMessage=(int?)action["max_queue"]??0;
                        message.playEvenWhenSilenced=(bool?)action["even_silenced"]==true;
                        if(op=="delayed") playDelayedImmediateMessage(message);
                        else if((bool?)action["immediate"]==true) playMessageImmediately(message);
                        else playMessage(message);
                        break;
                    }
                    case "quiet":enableKeepQuietMode();break;
                    case "inform":disableKeepQuietMode();break;
                    case "purge":purgeQueues((int?)action["retain_sre"]??-1);break;
                    case "repeat":repeatLastMessage();break;
                    case "pause":pauseQueue((int?)action["seconds"]??1);break;
                    case "unpause":unpauseQueue();break;
                    case "trigger":testTrigger=(bool)action["value"];break;
                    case "advance":
                        state.Now=state.Now.AddSeconds((double)action["seconds"]);state.Ticks=state.Now.Ticks;
                        GameStateData.CurrentTime=state.Now;MapperClock.UtcNow=state.Now;break;
                    case "hard_part":
                        state.hardPartsOnTrackData.hardPartsMapped=true;
                        state.hardPartsOnTrackData.processedHardPartsForBestLap=new List<Tuple<float,float>> {Tuple.Create((float)action["start"],(float)action["end"])};break;
                    case "gaps":
                        state.SessionData.TimeDeltaFront=(float)action["front"];state.SessionData.TimeDeltaBehind=(float)action["behind"];
                        PlaybackModerator.UpdateAutoVerbosity(state);break;
                    case "stand_by": {
                        string folder=(string)action["folder"];
                        if(!SoundCache.availableSounds.Contains(folder)) throw new ArgumentException("Test sound unavailable");
                        pauseQueueAndPlayDelayedImmediateMessage(new QueuedMessage(folder,0),(int)action["min"],(int)action["max"]);break;
                    }
                    default:throw new ArgumentException("Unknown queue test action");
                }
                TrackOwners();
            }
        }
    }
}
