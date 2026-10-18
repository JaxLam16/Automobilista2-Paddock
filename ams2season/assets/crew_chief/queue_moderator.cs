using System;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Diagnostics;
using CrewChiefV4.GameState;
using CrewChiefV4.Events;
namespace CrewChiefV4.Audio {

public enum Verbosity { SILENT=0, LOW, MED, FULL }
public static class PlaybackModerator {
    private static readonly bool autoVerbosity=UserSettings.GetUserSettings().getBoolean("priortise_messages_depending_on_situation");
    public static readonly bool paceNotesMuteOtherMessages=UserSettings.GetUserSettings().getBoolean("pace_notes_mute_all_messages");
    private static Verbosity verbosity=Verbosity.FULL;
    private static DateTime nextVerbosityUpdate=DateTime.MinValue;
    private static SoundType minPriorityForInterrupt=SoundType.SPOTTER;
    private static Dictionary<Verbosity,int> minPriorityForEachVerbosity=new Dictionary<Verbosity,int> {
        {Verbosity.FULL,0},{Verbosity.MED,5},{Verbosity.LOW,10},{Verbosity.SILENT,20}};
    static void Trace(string message) { }
    public static void Reset() { verbosity=Verbosity.FULL;nextVerbosityUpdate=DateTime.MinValue; }
    public static string CurrentVerbosity { get { return verbosity.ToString(); } }
    public static bool CanPreemptRegular(SoundType type) {
        return minPriorityForInterrupt!=SoundType.OTHER && CanInterrupt(new SoundMetadata(SoundType.REGULAR_MESSAGE,5)) && type<=minPriorityForInterrupt;
    }
public static void UpdateAutoVerbosity(GameStateData currentGameState)
        {
            if (!autoVerbosity || currentGameState == null)
            {
                PlaybackModerator.verbosity = Verbosity.FULL;
                return;
            }

            if (currentGameState.Now < nextVerbosityUpdate)
                return;

            PlaybackModerator.nextVerbosityUpdate = currentGameState.Now.AddSeconds(1);
            PlaybackModerator.verbosity = Verbosity.FULL;
            if (currentGameState.PositionAndMotionData.CarSpeed > 5)
            {
                if (currentGameState.SessionData.SessionType == SessionType.Race)
                {
                    var inCloseTraffic = currentGameState.SessionData.TimeDeltaFront > 0 && currentGameState.SessionData.TimeDeltaFront < 1.5
                        && currentGameState.SessionData.TimeDeltaBehind > 0 && currentGameState.SessionData.TimeDeltaBehind < 1.5;

                    var hasCarVeryClose = (currentGameState.SessionData.TimeDeltaFront > 0 && currentGameState.SessionData.TimeDeltaFront < 1)
                        || (currentGameState.SessionData.TimeDeltaBehind > 0 && currentGameState.SessionData.TimeDeltaBehind < 1);

                    var inTraffic = currentGameState.SessionData.TimeDeltaFront > 0 && currentGameState.SessionData.TimeDeltaFront < 3
                        && currentGameState.SessionData.TimeDeltaBehind > 0 && currentGameState.SessionData.TimeDeltaBehind < 3;

                    var hasCarClose = (currentGameState.SessionData.TimeDeltaFront > 0 && currentGameState.SessionData.TimeDeltaFront < 2)
                        || (currentGameState.SessionData.TimeDeltaBehind > 0 && currentGameState.SessionData.TimeDeltaBehind < 2);

                    if (inCloseTraffic || hasCarVeryClose)
                        PlaybackModerator.verbosity = Verbosity.LOW;
                    else if (inTraffic || hasCarClose)
                        PlaybackModerator.verbosity = Verbosity.MED;
                    else if (currentGameState.SessionData.CompletedLaps == 0
                        || (!currentGameState.SessionData.SessionHasFixedTime && currentGameState.SessionData.SessionLapsRemaining < 2)
                        || (currentGameState.SessionData.SessionHasFixedTime && currentGameState.SessionData.SessionRunningTime + 120 >= currentGameState.SessionData.SessionTotalRunTime))
                        PlaybackModerator.verbosity = Verbosity.MED;
                }
                else if ((currentGameState.SessionData.SessionType == SessionType.Qualify
                          || currentGameState.SessionData.SessionType == SessionType.PrivateQualify)
                    && !currentGameState.PitData.OnOutLap
                    && currentGameState.SessionData.CurrentLapIsValid)
                    PlaybackModerator.verbosity = Verbosity.MED;
            }
        }
public static bool MessageCanBeQueued(QueuedMessage queuedMessage, int currentQueueDepth, DateTime now)
        {
            int priority;
            SoundType type;
            if (queuedMessage.metadata == null)
            {
                PlaybackModerator.Trace("Message " + queuedMessage.messageName + " has no metadata, setting priority and type to default");
                priority = SoundMetadata.DEFAULT_PRIORITY;
                type = SoundType.REGULAR_MESSAGE;
            }
            else
            {
                priority = queuedMessage.metadata.priority;
                type = queuedMessage.metadata.type;
            }
            if (GlobalBehaviourSettings.speakOnlyWhenSpokenTo &&
                !(queuedMessage.metadata.type == SoundType.VOICE_COMMAND_RESPONSE || queuedMessage.metadata.type == SoundType.SPOTTER))
            {
                PlaybackModerator.Trace(string.Format("Message {0} hasn't been queued because we're in 'speak only when spoken to' mode and it's type is {1}", queuedMessage.messageName, queuedMessage.metadata.type));
                return false;
            }
            if (paceNotesMuteOtherMessages
                && (DriverTrainingService.isPlayingPaceNotes || DriverTrainingService.isRecordingPaceNotes)
                && type != SoundType.PACE_NOTE)
            {
                PlaybackModerator.Trace(string.Format("Message {0} hasn't been queued because its not a pace note", queuedMessage.messageName));
                return false;
            }

            var canPlay = queuedMessage.playEvenWhenSilenced || priority >= PlaybackModerator.minPriorityForEachVerbosity[verbosity];
            if (canPlay)
            {
                // not using this Dictionary of played messages so no point in adding data to it. Will leave this code
                // here for now in case i come up with a use-case
                /*
                MessageQueueCounter counter;
                if (PlaybackModerator.queuedMessageCounters.TryGetValue(queuedMessage.messageName, out counter))
                {
                    counter.timeQueued = now;
                    counter.numberOfTimesQueued = counter.numberOfTimesQueued + 1;
                }
                else
                {
                    PlaybackModerator.queuedMessageCounters.Add(queuedMessage.messageName, new MessageQueueCounter(now));
                }
                */
            }
            else
                PlaybackModerator.Trace(string.Format("Message {0} hasn't been queued because its priority is {1} and our verbosity is currently {2}", queuedMessage.messageName, priority, verbosity));

            return canPlay;
        }
public static bool ImmediateMessageCanBeQueued(QueuedMessage queuedMessage)
        {
            if (GlobalBehaviourSettings.speakOnlyWhenSpokenTo &&
                (queuedMessage.metadata == null || !(queuedMessage.metadata.type == SoundType.VOICE_COMMAND_RESPONSE || queuedMessage.metadata.type == SoundType.SPOTTER)))
            {
                PlaybackModerator.Trace(string.Format("Immediate message {0} hasn't been queued because we're in 'speak only when spoken to' mode and it's type is {1}", queuedMessage.messageName, queuedMessage.metadata.type));
                return false;
            }
            return true;
        }
static PlaybackModerator()
        {
            var interruptSetting = UserSettings.GetUserSettings().getString("interrupt_setting_listprop");
            MinPriorityForInterrupt interruptSettingEnum;
            if (Enum.TryParse(interruptSetting, out interruptSettingEnum) && Enum.IsDefined(typeof(MinPriorityForInterrupt), interruptSettingEnum))
            {
                switch (interruptSettingEnum)
                {
                    case MinPriorityForInterrupt.SPOTTER_MESSAGES:
                        minPriorityForInterrupt = SoundType.SPOTTER;
                        break;
                    case MinPriorityForInterrupt.CRITICAL_MESSAGES:
                        minPriorityForInterrupt = SoundType.PACE_NOTE;
                        break;
                    case MinPriorityForInterrupt.IMPORTANT_MESSAGES:
                        minPriorityForInterrupt = SoundType.IMPORTANT_MESSAGE;
                        break;
                    default:
                        minPriorityForInterrupt = SoundType.OTHER;
                        break;
                }
            }
        }
private static Boolean CanInterrupt(SoundMetadata metadata)
        {
            // is this sufficient? Should the spotter be able to interrupt voice comm responses?
            return metadata.type == SoundType.REGULAR_MESSAGE;
        }
    // Channel beep selection is handled by Paddock; not claimed restored here.
    public static void PreProcessAddedKeys(List<string> keys) { }
}

}
