using System;using System.Collections.Generic;using CrewChiefV4.GameState;using CrewChiefV4.Audio;using CrewChiefV4.NumberProcessing;using CrewChiefV4.Events;
namespace CrewChiefV4.Events { public enum GridSide
    {
        UNKNOWN, LEFT, RIGHT
    } }
namespace CrewChiefV4.Audio { public partial class AudioPlayer { public static Boolean canReadName(String rawName, bool allowTTSNameInOnlyWhenNecessaryMode = true)
        {
            if (String.IsNullOrWhiteSpace(rawName)) return false;

            bool allowTTSName = SoundCache.hasSuitableTTSVoice
                && (ttsOption == TTS_OPTION.ANY_TIME || (ttsOption == TTS_OPTION.ONLY_WHEN_NECESSARY && allowTTSNameInOnlyWhenNecessaryMode));
            var usableName = DriverNameHelper.getUsableDriverName(rawName);
            
            return CrewChief.enableDriverNames &&
                (allowTTSName
                || (SoundCache.trainee_active() && SoundCache.availableDriverNamesForTrainee.Contains(usableName)
                || !SoundCache.trainee_active() && SoundCache.availableDriverNames.Contains(usableName)));
        } }
public static partial class SoundCache { public static bool hasSuitableTTSVoice=false; public static bool trainee_active() { return false; } } }
namespace CrewChiefV4.Events { public static partial class Strategy {
public static readonly Boolean enablePitExitPositionEstimates = UserSettings.GetUserSettings().getBoolean("enable_pit_exit_position_estimates");
private const String folderPitStopCostsUsAbout = "strategy/a_pitstop_costs_us_about";
public static List<MessageFragment> MkPitStopTimeLoss(float timeLostForStop)
        {
            Console.WriteLine("Practice pitstop has cost us " + timeLostForStop + " seconds");
            return AbstractEvent.MessageContents(folderPitStopCostsUsAbout, TimeSpanWrapper.FromSeconds(timeLostForStop, Precision.SECONDS));
        }
} }
namespace CrewChiefV4.Events { public class Opponents : AbstractEvent {
public const String folderOneLapAhead = "opponents/one_lap_ahead";
public const String folderOneLapBehind = "opponents/one_lap_behind";
private static readonly bool allowNumberAfterName = UserSettings.GetUserSettings().getBoolean("opponents_number_after_name");
private const String folderCantPronounceName = "opponents/cant_pronounce_name";
private const String folderOpponentPositionIntro = "position/opponent_position_intro";
public const String folderCarNumber = "opponents/car_number";
public static List<MessageFragment> MkOpponentShort(OpponentData opponent, bool preferPosition, bool requestNumber, bool preferCantPronounce, bool allowPosition = true)
        {
            var messages = new List<MessageFragment>();

            bool number_available = !opponent.CarNumber.Equals("-1");
            bool includeNumber = false;

            if (AudioPlayer.canReadName(opponent.DriverRawName))
            {
                messages.Add(MessageFragment.Opponent(opponent));
                includeNumber = requestNumber && allowNumberAfterName && number_available;
            }
            else if (preferPosition)
            {
                messages.AddRange(MkOpponentPosition(opponent.ClassPosition));
                // no includeNumber here, it's too noisy to have multiple numbers
            }
            else if (number_available)
            {
                includeNumber = true;
            }
            else if (preferCantPronounce)
            {
                // unfortunately this audio message can sometimes be "I really don't know" which can be confusing,
                // but at least half the time it is "I can't pronounce the name".
                messages.Add(MessageFragment.Text(folderCantPronounceName));
            }
            else if (allowPosition)
            {
                messages.AddRange(MkOpponentPosition(opponent.ClassPosition));
            }

            if (includeNumber)
            {
                messages.Add(MessageFragment.Text(Opponents.folderCarNumber));
                messages.AddRange(new CarNumber(opponent.CarNumber).getMessageFragments());
            }

            return messages;
        }
public static List<MessageFragment> MkOpponentPosition(int position)
        {
            if (SoundCache.availableSounds.Contains(folderOpponentPositionIntro))
            {
                return MessageContents(folderOpponentPositionIntro, Position.folderStub + position);
            }
            else
            {
                return MessageContents(Position.folderStub + position);
            }
        }
public override void clearState() { throw new NotSupportedException("Full Opponents event pending"); }
protected override void triggerInternal(GameStateData previous,GameStateData current) { throw new NotSupportedException("Full Opponents event pending"); }
} }
namespace CrewChiefV4.Events { public static partial class FrozenOrderMonitor {
public const string folderRollingStartReminder = "frozen_order/thats_a_rolling_start";
public const string folderInTheLeftColumn = "frozen_order/in_the_left_column";
public const string folderInTheRightColumn = "frozen_order/in_the_right_column";
} }
// Explicit boundaries: these branches are iRacing/RF2 only, never AMS2.
namespace CrewChiefV4.Events { public abstract partial class AbstractEvent {

}  }
namespace CrewChiefV4.PitManager { public static class PitManagerVoiceCmds { public static void startOfRace() { throw new NotSupportedException("RF2 pit menu control is unavailable in AMS2"); } } }
namespace CrewChiefV4 { public partial class CrewChief {
    public static object getEvent(string name) { return PaddockOriginalEvents.Lookup(name); }
    // Manual double-file formation requires original grid-side spotter bridge.
    // The adapter withholds this entire optional mode until that is connected.
    public Tuple<GridSide,Dictionary<int,GridSide>> getGridSide() { throw new NotSupportedException("Manual formation grid-side bridge pending"); }
} }
