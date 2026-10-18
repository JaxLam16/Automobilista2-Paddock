using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using CrewChiefV4.GameState;
using CrewChiefV4.Audio;
using System.Diagnostics;

namespace CrewChiefV4.Events
{
    class Penalties : AbstractEvent
    {
        // time (in seconds) to delay messages about penalty laps to go -
        // we need this because the play might cross the start line while serving
        // a penalty, so we should wait before telling them how many laps they have to serve it
        private int pitstopDelay = 20;

        private String folderNewPenaltyStopGo = "penalties/new_penalty_stopgo";

        private String folderNewPenaltyDriveThrough = "penalties/new_penalty_drivethrough";

        // for iracing we don't know if it's a drive through or a stop-go, so use a generic message
        private String folderBlackFlag = "penalties/new_penalty_black_flag";
        // for iracing - meatball flag
        private String folderBlackAndOrangeFlag = "penalties/meatball_flag";

        private String folderNewPenaltySlowDown = "penalties/new_penalty_slowdown";

        private String folderSlowDownPenaltyClear = "penalties/slow_down_penalty_clear";

        private String folderThreeLapsToServe = "penalties/penalty_three_laps_left";

        private String folderTwoLapsToServe = "penalties/penalty_two_laps_left";

        private String folderOneLapToServeStopGo = "penalties/penalty_one_lap_left_stopgo";

        private String folderOneLapToServeDriveThrough = "penalties/penalty_one_lap_left_drivethrough";

        // for iRacing where we don't know if it's a DT or a S&G
        private String folderOneLapToServe = "penalties/penalty_one_lap_left_to_pit";

        public static String folderDisqualified = "penalties/penalty_disqualified";

        private String folderPitNowStopGo = "penalties/pit_now_stop_go";

        private String folderPitNowDriveThrough = "penalties/pit_now_drive_through";

        private String folderTimePenalty = "penalties/time_penalty";

        private String folderPossibleTrackLimitsViolation = "penalties/possible_track_limits_warning";

        private String folderPenaltyNotServed = "penalties/penalty_not_served";

        // for voice requests
        private String folderYouStillHavePenalty = "penalties/you_still_have_a_penalty";

        private String folderYouStillHaveToServeDriveThrough = "penalties/still_have_to_serve_drive_through";

        private String folderYouStillHaveToServeStopGo = "penalties/still_have_to_serve_stop_go";

        private String folderYouHavePenalty = "penalties/you_have_a_penalty";

        private String folderPenaltyServed = "penalties/penalty_served";

        // Detailed penalty messages
        private String folderYouDontHaveAPenalty = "penalties/you_dont_have_a_penalty";

        private String folderStopGoSpeedingInPitlane = "penalties/stop_go_penalty_speeding_in_pit_lane";

        private String folderStopGoCutTrack = "penalties/stop_go_penalty_cutting_track";

        private String folderStopGoFalseStart = "penalties/stop_go_penalty_false_start";

        private String folderStopGoExitingPitsUnderRed = "penalties/stop_go_exitting_pits_on_red";

        private String folderStopGoRollingPassBeforeGreen = "penalties/stop_go_penalty_overtaking_on_formation_lap";

        private String folderStopGoFCYPassBeforeGreenEU = "penalties/stop_go_penalty_overtaking_under_safety_car";

        private String folderStopGoFCYPassBeforeGreenUS = "penalties/stop_go_penalty_overtaking_under_pace_car";

        private String folderDisqualifiedDrivingWithoutHeadlightsInDark = "penalties/disqualified_driving_without_headlights";

        private String folderDisqualifiedDrivingWithoutHeadlights = "penalties/disqualified_no_headlights";

        private String folderDisqualifiedExceededAllowedLapCount = "penalties/disqualified_exceeded_allowed_lap_count";

        private String folderDriveThroughSpeedingInPitlane = "penalties/drive_through_speeding_in_pit_lane";

        private String folderDriveThroughCutTrack = "penalties/drive_through_cutting_track";

        private String folderDriveThroughIgnoredBlueFlag = "penalties/drive_through_ignored_blue";

        private String folderDriveThroughFalseStart = "penalties/drive_through_false_start";

        private String folderWarningDrivingTooSlow = "penalties/warning_driving_too_slow";

        private String folderWarningWrongWay = "penalties/warning_wrong_way";

        private String folderWarningHeadlightsRequired = "penalties/warning_headlights_required";

        private String folderWarningHeadlightsRequiredWhenRaining = "penalties/warning_headlights_required_when_raining";

        private String folderWarningEnterPitsToAvoidExceedingLaps = "penalties/warning_enter_pits_to_avoid_exceeding_laps";

        private String folderWarningOneLapToServeDriveThrough = "penalties/one_lap_to_serve_drive_through";

        private String folderWarningOneLapToServeStopAndGo = "penalties/one_lap_to_serve_stop_go";

        private String folderWarningBlueFlagMoveOrBePenalized = "penalties/blue_move_now_or_be_penalized";

        private String folderWarningPointsWillBeAwardedThisLap = "penalties/points_will_be_awarded_this_lap";

        private String folderDisqualifiedIgnoredStopAndGo = "penalties/disqualified_ignored_stop_and_go";

        private String folderDisqualifiedIgnoredDriveThrough = "penalties/disqualified_ignored_drive_through";

        private String folderWarningEnterPitsNowToServePenalty = "penalties/warning_enter_pits_to_serve_penalty";

        private String folderWarningUnsportsmanlikeDriving = "penalties/warning_unsportsmanlike_driving";

        private String folderDriveThroughExceedingSingleStintTime = "penalties/drive_through_exceeding_single_stint_time";

        private String folderStopGoExceedingSingleStintTime = "penalties/stop_go_exceeding_single_stint_time";

        // deprecated cut track sounds, keeps these so the new cut stuff doesn't break unofficial sound packs
        public static String folderCutTrackInRace = "penalties/cut_track_in_race";
        public static String folderLapDeleted = "penalties/lap_deleted";
        public static String folderCutTrackPracticeOrQual = "penalties/cut_track_in_prac_or_qual";
        private static bool useNewCutTrackSounds = false;

        public static String folderCutTrackPracticeOrQualNextLapInvalid = "penalties/cut_track_in_prac_or_qual_next_invalid";

        public static String folderCarToCarCollision = "penalties/car_to_car_collision";
        public static String folderTooManyCarToCarCollisions = "penalties/too_many_car_to_car_collisions";
        public static String folderWillBeKickedAfterOneMoreCollision = "penalties/one_more_collision_before_kick";
        public static String folderWillBeKickedAfterOneMoreOffTrack = "penalties/one_more_off_track_before_kick";

        // 1, 2, 3, 4 versions of race cut ("track limits...") and non-race cut ("lap deleted") messages. For non-race,
        // "lap deleted" are combined with "track limits". 1, 2, 3, 4 are the taking-piss levels where 1 is few or zero cuts up to
        // 4 which is taking-the-piss
        private Dictionary<TrackLimitsMode, string> cutFoldersForRace = new Dictionary<TrackLimitsMode, string>
        {
            { TrackLimitsMode.OK, "penalties/cut_track_race_1" },
            { TrackLimitsMode.MINOR_CUTTING, "penalties/cut_track_race_2" },
            { TrackLimitsMode.EXCESSIVE_CUTTING, "penalties/cut_track_race_3" },
            { TrackLimitsMode.TAKING_PISS, "penalties/cut_track_race_4" }
        };

        private Dictionary<TrackLimitsMode, string> cutFoldersForNonRace = new Dictionary<TrackLimitsMode, string>
        {
            { TrackLimitsMode.OK, "penalties/cut_track_prac_or_qual_1" },
            { TrackLimitsMode.MINOR_CUTTING, "penalties/cut_track_prac_or_qual_2" },
            { TrackLimitsMode.EXCESSIVE_CUTTING, "penalties/cut_track_prac_or_qual_3" },
            { TrackLimitsMode.TAKING_PISS, "penalties/cut_track_prac_or_qual_4" }
        };

        private Boolean hasHadAPenalty;

        private int penaltyLap;

        private int lapsCompleted;

        private Boolean playedPitNow;

        private Boolean hasOutstandingPenalty = false;
        private PenatiesData.DetailedPenaltyType outstandingPenaltyType = PenatiesData.DetailedPenaltyType.NONE;
        private PenatiesData.DetailedPenaltyCause outstandingPenaltyCause = PenatiesData.DetailedPenaltyCause.NONE;

        private Boolean playedTimePenaltyMessage;

        private int cutTrackWarningsCount;

        private TimeSpan cutTrackWarningFrequency = TimeSpan.FromSeconds(30);

        private Boolean playedTrackCutWarningInPracticeOrQualOnThisLap = false;

        private DateTime lastCutTrackWarningTime;

        private Boolean playedNotServedPenalty;

        private Boolean warnedOfPossibleTrackLimitsViolationOnThisLap = false;

        private Boolean waitingToNotifyOfSlowdown = false;

        private DateTime timeToNotifyOfSlowdown = DateTime.MinValue;

        private Boolean playedSlowdownNotificationOnThisLap = false;

        private Boolean waitingToClearSlowDown = false;

        private int incidentPointsForCarToCarCollision = 4;

        private int tooManyCarToCarCollisionsThreshold = 3;   // get really cranky after this many significant car-to-car collisions

        private double carToCarCollisionSpeedChangeThreshold = -1.5;    // a car to car collision resulting in this (or greater) speed change is considered significant
        // note this is negative so we're only interested in collisions that slow the player down

        private int carToCarCollisionCount = 0;

        private DateTime nextCarToCarCollisionCallDue = DateTime.MinValue;

        private bool playedKickWarning = false;

        private enum TrackLimitsMode
        {
            OK,                 // initial setting - no excessive or persistent cutting
            MINOR_CUTTING,      // some repeated track limits violations, nothing too serious
            EXCESSIVE_CUTTING,  // lots of violations, likely penalty
            TAKING_PISS         // no regard of track limits
        }

        // this isn't necessarily the same as the announced warnings - in some cases we don't bother to announce
        private int totalAnnouncableCutWarnings = 0;

        private List<DateTime> cutTimesInSession = new List<DateTime>();

        private TrackLimitsMode trackLimitsMode = TrackLimitsMode.OK;

        public override List<SessionPhase> applicableSessionPhases
        {
            get { return new List<SessionPhase> { SessionPhase.Green, SessionPhase.Countdown, SessionPhase.Garage /*Apparently rF2 issues penalties in garage too :)*/, SessionPhase.FullCourseYellow /*Some rF2 warnings come up under FCY*/, SessionPhase.Gridwalk /*Announce some rF2 warnings during gridwalk*/}; }
        }

        public Penalties(AudioPlayer audioPlayer)
        {
            this.audioPlayer = audioPlayer;
            useNewCutTrackSounds = SoundCache.availableSounds.Contains("penalties/cut_track_race_1");
        }

        public override void clearState()
        {
            clearPenaltyState();
            lastCutTrackWarningTime = DateTime.MinValue;
            cutTrackWarningsCount = 0;
            hasHadAPenalty = false;
            warnedOfPossibleTrackLimitsViolationOnThisLap = false;
            playedTrackCutWarningInPracticeOrQualOnThisLap = false;
            waitingToNotifyOfSlowdown = false;
            timeToNotifyOfSlowdown = DateTime.MinValue;
            playedSlowdownNotificationOnThisLap = false;
            waitingToClearSlowDown = false;
            PitStops.isPittingThisLap = false;
            trackLimitsMode = TrackLimitsMode.OK;
            totalAnnouncableCutWarnings = 0;
            // not used (yet) - might be helpful for establishing trends?
            cutTimesInSession.Clear();
            carToCarCollisionCount = 0;
            nextCarToCarCollisionCallDue = DateTime.MinValue;
            playedKickWarning = false;
        }

        private void clearPenaltyState()
        {
            penaltyLap = -1;
            lapsCompleted = -1;
            hasOutstandingPenalty = false;
            outstandingPenaltyType = PenatiesData.DetailedPenaltyType.NONE;
            outstandingPenaltyCause = PenatiesData.DetailedPenaltyCause.NONE;
            // edge case here: if a penalty is given and immediately served (slow down penalty), then
            // the player gets another within the next 20 seconds, the 'you have 3 laps to come in to serve'
            // message would be in the queue and would be made valid again, so would play. So we explicity
            // remove this message from the queue
            audioPlayer.removeQueuedMessage(folderThreeLapsToServe);
            playedPitNow = false;
            playedTimePenaltyMessage = false;
            playedNotServedPenalty = false;
            waitingToNotifyOfSlowdown = false;
            waitingToClearSlowDown = false;
            timeToNotifyOfSlowdown = DateTime.MinValue;
        }

        public override bool isMessageStillValid(String eventSubType, GameStateData currentGameState, Dictionary<String, Object> validationData)
        {
            if (base.isMessageStillValid(eventSubType, currentGameState, validationData))
            {
                if (eventSubType == folderCarToCarCollision
                    || eventSubType == folderTooManyCarToCarCollisions
                    || eventSubType == folderWillBeKickedAfterOneMoreCollision
                    || eventSubType == folderWillBeKickedAfterOneMoreOffTrack
                    || eventSubType == folderBlackAndOrangeFlag)
                {
                    return currentGameState.SessionData.SessionPhase != SessionPhase.Finished;
                }
                if (eventSubType == folderPossibleTrackLimitsViolation)
                {
                    return currentGameState.PositionAndMotionData.CarSpeed > 10;
                }
                // When a new penalty is given we queue a 'three laps left to serve' delayed message.
                // If, the moment message is about to play, the player has started a new lap, this message is no longer valid so shouldn't be played
                if (eventSubType == folderThreeLapsToServe)
                {
                    Console.WriteLine("Checking penalty validity, pen lap = " + penaltyLap + ", completed =" + lapsCompleted);
                    return hasOutstandingPenalty && lapsCompleted == penaltyLap && currentGameState.SessionData.SessionPhase != SessionPhase.Finished;
                }
                else if (cutFoldersForRace.Values.Contains(eventSubType))
                {
                    return !hasOutstandingPenalty
                        && currentGameState.SessionData.SessionPhase != SessionPhase.Finished
                        && !currentGameState.PitData.InPitlane
                        && currentGameState.PositionAndMotionData.CarSpeed > 10;
                }
                else if (eventSubType == folderCutTrackPracticeOrQualNextLapInvalid || cutFoldersForNonRace.Values.Contains(eventSubType))
                {
                    return currentGameState.SessionData.SessionPhase != SessionPhase.Finished
                        && !currentGameState.PitData.InPitlane
                        && currentGameState.PositionAndMotionData.CarSpeed > 10;
                }
                else if (eventSubType == folderNewPenaltySlowDown)
                {
                    return currentGameState.PenaltiesData.HasSlowDown;
                }
                else if (eventSubType == folderSlowDownPenaltyClear)
                {
                    return !currentGameState.PenaltiesData.HasSlowDown;
                }
                else if (eventSubType == folderPenaltyServed &&
                    (Game.RF1 || Game.RF2_LMU || Game.GTR2))
                {
                    // Don't validate "Penalty served" in rF1/rF2, hasOutstandingPenalty is false by the time we get here.
                    return true;
                }
                else if (eventSubType == folderTimePenalty && Game.RACE_ROOM && currentGameState.SessionData.SessionPhase != SessionPhase.Finished)
                {
                    return true;
                }
                else
                {
                    return hasOutstandingPenalty && currentGameState.SessionData.SessionPhase != SessionPhase.Finished;
                }
            }
            else
            {
                return false;
            }
        }

        override protected void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            bool raceRoomOrIRacing = (Game.RACE_ROOM || Game.IRACING);
            // some incident point testing
            if (previousGameState != null && currentGameState.SessionData.CurrentIncidentCount > previousGameState.SessionData.CurrentIncidentCount)
            {
                Console.WriteLine("incident points increased from " + previousGameState.SessionData.CurrentIncidentCount + " to " + currentGameState.SessionData.CurrentIncidentCount);
                // note that in dirt ovals, it's only 2 points, so we need some extra logic for that
                bool car_to_car_collision = currentGameState.SessionData.CurrentIncidentCount - previousGameState.SessionData.CurrentIncidentCount >= incidentPointsForCarToCarCollision;
                // for R3E/iRacing we have no idea what type of incident has occurred - we know it's
                // 4 points for a car-to-car collision so we can, at least, do *something* with it
                if (raceRoomOrIRacing && car_to_car_collision)
                {
                    // this isn't as reliable as it might be - there may be an edge case where multiple car-to-wall collisions occur in the same tick,
                    // but this is unlikely.
                    // if our speed has changed substantially in this tick, it's probably a severe collision - maybe wire up x/z velocity and check it properly but
                    // this will do for now. Where our speed has increased as a result of the collision, we assume the player has been hit from behind so it's not
                    // his fault - these collisions are ignored
                    float speedChange = currentGameState.PositionAndMotionData.CarSpeed - previousGameState.PositionAndMotionData.CarSpeed;
                    Console.WriteLine("car to car collision, speed change = " + speedChange);
                    if (speedChange < carToCarCollisionSpeedChangeThreshold)
                    {
                        carToCarCollisionCount++;
                        Console.WriteLine("we appear to have re-ended another car, collision count = " + carToCarCollisionCount);
                        if (currentGameState.Now > nextCarToCarCollisionCallDue)
                        {
                            nextCarToCarCollisionCallDue = currentGameState.Now.AddSeconds(60);
                            if (carToCarCollisionCount == tooManyCarToCarCollisionsThreshold)
                            {
                                // we've hit our 'stop crashing into people' threshold
                                audioPlayer.playMessage(new QueuedMessage(folderTooManyCarToCarCollisions, 0, abstractEvent: this));
                            }
                            else
                            {
                                // we've not reached the threshold or have already grumbled about it
                                audioPlayer.playMessage(new QueuedMessage(folderCarToCarCollision, 0, abstractEvent: this));
                            }
                        }
                    }
                }
                if (!playedKickWarning && currentGameState.SessionData.MaxIncidentCount > 0 && currentGameState.SessionData.SessionType == SessionType.Race
                    && raceRoomOrIRacing )
                {
                    // old code had 2 here for race room with a comment that it needed more testing. It's definitely 1 in iRacing.
                    int to_go = Game.RACE_ROOM ? 2 : 1;
                    // how close to being kicked are we?
                    if (currentGameState.SessionData.CurrentIncidentCount + to_go >= currentGameState.SessionData.MaxIncidentCount)
                    {
                        // shit we're close, one or two more anything and we're out
                        Console.WriteLine("2 incident points from a kick");
                        audioPlayer.playMessage(new QueuedMessage(folderWillBeKickedAfterOneMoreOffTrack, 0, abstractEvent: this, priority: 10));
                        playedKickWarning = true;
                    }
                    else if (currentGameState.SessionData.CurrentIncidentCount + 4 >= currentGameState.SessionData.MaxIncidentCount)
                    {
                        // one more car contact and we're out
                        Console.WriteLine("4 incident points (one car-car collision) from a kick");
                        audioPlayer.playMessage(new QueuedMessage(folderWillBeKickedAfterOneMoreCollision, 0, abstractEvent: this, priority: 10));
                        playedKickWarning = true;
                    }
                }

                // When you're starting to think your incidents might be affecting your safety rating,
                // Jim knows what you're thinking.
                if (raceRoomOrIRacing && currentGameState.SessionData.SessionType == SessionType.Race
                    && GlobalBehaviourSettings.cutTrackWarningsEnabled // people who don't want cut warnings typically don't want this either
                    && currentGameState.SessionData.HasLimitedIncidents
                    && currentGameState.SessionData.CurrentIncidentCount > 4
                    && !playedKickWarning
                    && (car_to_car_collision || Utilities.random.Next(0, 2) == 0))
                {
                    DelayedMessage callback = delegate (GameStateData futureGameState, List<MessageFragment> msg, List<MessageFragment> alt)
                    {
                        msg.AddRange(MessageContents(Ratings.folderYouHave, futureGameState.SessionData.CurrentIncidentCount, Ratings.folderincidentPoints));
                    };
                    audioPlayer.playMessage(new QueuedMessage("penalties/incidents", 10, secondsDelay: 5, delayedMessage: callback));
                }
            }
            // Play warning messages:
            if (currentGameState.PenaltiesData.Warning != PenatiesData.WarningMessage.NONE)
            {
                string warningMsg = null;
                switch (currentGameState.PenaltiesData.Warning)
                {
                    case PenatiesData.WarningMessage.WRONG_WAY:
                        warningMsg = folderWarningWrongWay;
                        break;
                    case PenatiesData.WarningMessage.DRIVING_TOO_SLOW:
                        warningMsg = folderWarningDrivingTooSlow;
                        break;
                    case PenatiesData.WarningMessage.HEADLIGHTS_REQUIRED:
                        warningMsg = folderWarningHeadlightsRequired;
                        break;
                    case PenatiesData.WarningMessage.HEADLIGHTS_REQUIRED_WHEN_RAINING:
                        warningMsg = folderWarningHeadlightsRequiredWhenRaining;
                        break;
                    case PenatiesData.WarningMessage.ENTER_PITS_TO_AVOID_EXCEEDING_LAPS:
                        if (!currentGameState.PitData.HasRequestedPitStop)
                        {
                            warningMsg = folderWarningEnterPitsToAvoidExceedingLaps;
                            PitStops.isPittingThisLap = true;
                        }
                        break;
                    case PenatiesData.WarningMessage.DISQUALIFIED_DRIVING_WITHOUT_HEADLIGHTS_IN_DARK:
                        SessionEndMessages.overrideDetailedDisqualifiedMessage = folderDisqualifiedDrivingWithoutHeadlightsInDark;
                        break;
                    case PenatiesData.WarningMessage.DISQUALIFIED_DRIVING_WITHOUT_HEADLIGHTS:
                        SessionEndMessages.overrideDetailedDisqualifiedMessage = folderDisqualifiedDrivingWithoutHeadlights;
                        break;
                    case PenatiesData.WarningMessage.DISQUALIFIED_EXCEEDING_ALLOWED_LAP_COUNT:
                        SessionEndMessages.overrideDetailedDisqualifiedMessage = folderDisqualifiedExceededAllowedLapCount;
                        break;
                    case PenatiesData.WarningMessage.ONE_LAP_TO_SERVE_DRIVE_THROUGH:
                        warningMsg = folderWarningOneLapToServeDriveThrough;
                        PitStops.isPittingThisLap = true;
                        break;
                    case PenatiesData.WarningMessage.ONE_LAP_TO_SERVE_STOP_AND_GO:
                        warningMsg = folderWarningOneLapToServeStopAndGo;
                        PitStops.isPittingThisLap = true;
                        break;
                    case PenatiesData.WarningMessage.BLUE_MOVE_OR_BE_PENALIZED:
                        warningMsg = folderWarningBlueFlagMoveOrBePenalized;
                        break;
                    case PenatiesData.WarningMessage.POINTS_WILL_BE_AWARDED_THIS_LAP:
                        warningMsg = folderWarningPointsWillBeAwardedThisLap;
                        break;
                    case PenatiesData.WarningMessage.DISQUALIFIED_IGNORED_STOP_AND_GO:
                        SessionEndMessages.overrideDetailedDisqualifiedMessage = folderDisqualifiedIgnoredStopAndGo;
                        break;
                    case PenatiesData.WarningMessage.DISQUALIFIED_IGNORED_DRIVE_THROUGH:
                        SessionEndMessages.overrideDetailedDisqualifiedMessage = folderDisqualifiedIgnoredDriveThrough;
                        break;
                    case PenatiesData.WarningMessage.ENTER_PITS_TO_SERVE_PENALTY:
                        warningMsg = folderWarningEnterPitsNowToServePenalty;
                        break;
                    case PenatiesData.WarningMessage.UNSPORTSMANLIKE_DRIVING:
                        warningMsg = folderWarningUnsportsmanlikeDriving;
                        break;
                    default:
                        Debug.Assert(false, "Unhandled warning");
                        Console.WriteLine("Penalties: unhandled warning: " + currentGameState.PenaltiesData.Warning);
                        break;
                }

                if (!String.IsNullOrWhiteSpace(warningMsg))
                {
                    audioPlayer.playMessageImmediately(new QueuedMessage(warningMsg, 0, priority: 15));
                }
            }

            if (!Game.RF2_LMU && !Game.GTR2
                && currentGameState.SessionData.SessionPhase == SessionPhase.FullCourseYellow)
            {
                // Do not allow penalty/warning messagess under FCY unless this is rF2.
                return;
            }

            if (currentGameState.SessionData.IsNewLap)
            {
                warnedOfPossibleTrackLimitsViolationOnThisLap = false;
                playedTrackCutWarningInPracticeOrQualOnThisLap = false;
                playedSlowdownNotificationOnThisLap = false;
                PitStops.isPittingThisLap = false;
            }
            if (!Game.ACC &&
                (currentGameState.SessionData.SessionType == SessionType.Race || Game.IRACING) && previousGameState != null &&
                (currentGameState.PenaltiesData.HasDriveThrough || currentGameState.PenaltiesData.HasStopAndGo || currentGameState.PenaltiesData.HasTimeDeduction ||
                currentGameState.PenaltiesData.HasPitStop || currentGameState.PenaltiesData.HasMeatballFlag))
            {
                if (currentGameState.PenaltiesData.HasDriveThrough && !previousGameState.PenaltiesData.HasDriveThrough)
                {
                    lapsCompleted = currentGameState.SessionData.CompletedLaps;
                    // this is a new penalty
                    audioPlayer.playMessage(new QueuedMessage(folderNewPenaltyDriveThrough, 0, abstractEvent: this, priority: 10));
                    // queue a '3 laps to serve penalty' message - this might not get played
                    audioPlayer.playMessage(new QueuedMessage(folderThreeLapsToServe, 0, secondsDelay: pitstopDelay, abstractEvent: this, priority: 10));
                    // we don't already have a penalty
                    if (penaltyLap == -1 || !hasOutstandingPenalty)
                    {
                        penaltyLap = currentGameState.SessionData.CompletedLaps;
                    }
                    hasOutstandingPenalty = true;
                    hasHadAPenalty = true;
                    // don't know if this is for cutting, just in case we reset the cutting data
                    trackLimitsMode = TrackLimitsMode.OK;
                    totalAnnouncableCutWarnings = 0;
                    cutTimesInSession.Clear();
                }
                else if (currentGameState.PenaltiesData.HasStopAndGo && !previousGameState.PenaltiesData.HasStopAndGo)
                {
                    lapsCompleted = currentGameState.SessionData.CompletedLaps;
                    // this is a new penalty
                    audioPlayer.playMessage(new QueuedMessage(folderNewPenaltyStopGo, 0, abstractEvent: this, priority: 10));
                    // queue a '3 laps to serve penalty' message - this might not get played
                    audioPlayer.playMessage(new QueuedMessage(folderThreeLapsToServe, 0, secondsDelay: pitstopDelay, abstractEvent: this, priority: 10));
                    // we don't already have a penalty
                    if (penaltyLap == -1 || !hasOutstandingPenalty)
                    {
                        penaltyLap = currentGameState.SessionData.CompletedLaps;
                    }
                    hasOutstandingPenalty = true;
                    hasHadAPenalty = true;
                    // don't know if this is for cutting, just in case we reset the cutting data
                    trackLimitsMode = TrackLimitsMode.OK;
                    totalAnnouncableCutWarnings = 0;
                    cutTimesInSession.Clear();
                }
                else if (Game.IRACING && currentGameState.PenaltiesData.HasPitStop && !previousGameState.PenaltiesData.HasPitStop)
                {
                    lapsCompleted = currentGameState.SessionData.CompletedLaps;
                    // this is a new penalty
                    audioPlayer.playMessage(new QueuedMessage(folderBlackFlag, 0, abstractEvent: this, priority: 10));
                    // queue a '3 laps to serve penalty' message - this might not get played
                    audioPlayer.playMessage(new QueuedMessage(folderThreeLapsToServe, 0, secondsDelay: pitstopDelay, abstractEvent: this, priority: 10));
                    // we don't already have a penalty
                    if (penaltyLap == -1 || !hasOutstandingPenalty)
                    {
                        penaltyLap = currentGameState.SessionData.CompletedLaps;
                    }
                    hasOutstandingPenalty = true;
                    hasHadAPenalty = true;
                    // don't know if this is for cutting, just in case we reset the cutting data
                    trackLimitsMode = TrackLimitsMode.OK;
                    totalAnnouncableCutWarnings = 0;
                    cutTimesInSession.Clear();
                }
                else if (Game.IRACING && currentGameState.PenaltiesData.HasMeatballFlag && !previousGameState.PenaltiesData.HasMeatballFlag)
                {
                    audioPlayer.playMessage(new QueuedMessage(folderBlackAndOrangeFlag, 0, abstractEvent: this, priority: 10));
                }
                else if (currentGameState.PitData.InPitlane && currentGameState.PitData.OnOutLap && !playedNotServedPenalty &&
                    (currentGameState.PenaltiesData.HasStopAndGo || currentGameState.PenaltiesData.HasDriveThrough))
                {
                    // we've exited the pits but there's still an outstanding penalty
                    audioPlayer.playMessage(new QueuedMessage(folderPenaltyNotServed, 0, secondsDelay: 3, abstractEvent: this, priority: 10));
                    playedNotServedPenalty = true;
                }
                else if (currentGameState.SessionData.IsNewLap && (currentGameState.PenaltiesData.HasStopAndGo || currentGameState.PenaltiesData.HasDriveThrough || currentGameState.PenaltiesData.HasPitStop))
                {
                    lapsCompleted = currentGameState.SessionData.CompletedLaps;
                    if (lapsCompleted - penaltyLap == 3 && !currentGameState.PitData.InPitlane)
                    {
                        // run out of laps, and not in the pitlane
                        if (!audioPlayer.playRant("disqualified_rant", MessageContents(folderDisqualified)))
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderDisqualified, 0, secondsDelay: 5, abstractEvent: this, priority: 10));
                        }
                    }
                    else if (lapsCompleted - penaltyLap == 2 && currentGameState.PenaltiesData.HasDriveThrough)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderOneLapToServeDriveThrough, 0, secondsDelay: pitstopDelay, abstractEvent: this, priority: 10));
                    }
                    else if (lapsCompleted - penaltyLap == 2 && currentGameState.PenaltiesData.HasStopAndGo)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderOneLapToServeStopGo, 0, secondsDelay: pitstopDelay, abstractEvent: this, priority: 10));
                    }
                    else if (lapsCompleted - penaltyLap == 2 && currentGameState.PenaltiesData.HasPitStop)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderOneLapToServe, 0, secondsDelay: pitstopDelay, abstractEvent: this, priority: 10));
                    }
                    else if (lapsCompleted - penaltyLap == 1)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderTwoLapsToServe, 0, secondsDelay: pitstopDelay, abstractEvent: this, priority: 10));
                    }
                }
                else if (!playedPitNow && currentGameState.SessionData.SectorNumber == 3 && currentGameState.PenaltiesData.HasStopAndGo && lapsCompleted - penaltyLap == 2)
                {
                    playedPitNow = true;
                    audioPlayer.playMessage(new QueuedMessage(folderPitNowStopGo, 14, secondsDelay: 6, abstractEvent: this, priority: 10));
                }
                else if (!playedPitNow && currentGameState.SessionData.SectorNumber == 3 && currentGameState.PenaltiesData.HasDriveThrough && lapsCompleted - penaltyLap == 2)
                {
                    playedPitNow = true;
                    audioPlayer.playMessage(new QueuedMessage(folderPitNowDriveThrough, 14, secondsDelay: 6, abstractEvent: this, priority: 10));
                }
                else if (!playedTimePenaltyMessage && currentGameState.PenaltiesData.HasTimeDeduction)
                {
                    playedTimePenaltyMessage = true;
                    audioPlayer.playMessage(new QueuedMessage(folderTimePenalty, 0, abstractEvent: this, priority: 10));
                }
            }
            else if (currentGameState.PositionAndMotionData.CarSpeed > 10 && GlobalBehaviourSettings.cutTrackWarningsEnabled &&
                !currentGameState.PitData.OnOutLap &&
                currentGameState.PenaltiesData.CutTrackWarnings > cutTrackWarningsCount &&
                currentGameState.PenaltiesData.NumOutstandingPenalties == previousGameState.PenaltiesData.NumOutstandingPenalties)  // Make sure we've no new penalty for this cut.
            {
                cutTrackWarningsCount = currentGameState.PenaltiesData.CutTrackWarnings;
                if (currentGameState.ControlData.ControlType != ControlType.AI &&
                    // test/quali have their own frequency handling logic, so lastCutTrackWarningTime is only relevant for races
                    (currentGameState.SessionData.SessionType != SessionType.Race || lastCutTrackWarningTime.Add(cutTrackWarningFrequency) < currentGameState.Now))
                {
                    string cutMessage = getCutTrackMessage(currentGameState);
                    if (cutMessage != null)
                    {
                        audioPlayer.playMessage(new QueuedMessage(cutMessage, 5, secondsDelay: Utilities.random.Next(2, 4), abstractEvent: this, priority: 10));
                    }
                }
            }
            else if (currentGameState.PositionAndMotionData.CarSpeed > 10 && GlobalBehaviourSettings.cutTrackWarningsEnabled && currentGameState.SessionData.SessionType != SessionType.Race &&
              !currentGameState.SessionData.CurrentLapIsValid && previousGameState != null && previousGameState.SessionData.CurrentLapIsValid &&
                /*!Game.IRACING &&*/ !currentGameState.PitData.OnOutLap)
            {
                // JB: don't think we need this block - the previous block should always trigger in preference to this, but we'll leave it here just in case
                cutTrackWarningsCount = currentGameState.PenaltiesData.CutTrackWarnings;
                // don't warn about cut track if the AI is driving
                if (currentGameState.ControlData.ControlType != ControlType.AI &&
                    lastCutTrackWarningTime.Add(cutTrackWarningFrequency) < currentGameState.Now)
                {
                    string cutMessage = getCutTrackMessage(currentGameState);
                    if (cutMessage != null)
                    {
                        audioPlayer.playMessage(new QueuedMessage(cutMessage, 5, secondsDelay: Utilities.random.Next(2, 4), abstractEvent: this, priority: 10));
                    }
                }
            }
            else if ((currentGameState.SessionData.SessionType == SessionType.Race || 
                      currentGameState.SessionData.SessionType == SessionType.Qualify ||
                      currentGameState.SessionData.SessionType == SessionType.PrivateQualify ||
                      currentGameState.SessionData.SessionType == SessionType.Practice ||
                      currentGameState.SessionData.SessionType == SessionType.LonePractice)
                    && previousGameState != null && currentGameState.PenaltiesData.NumOutstandingPenalties > 0
                    && (Game.RF1 || Game.RF2_LMU || Game.ACC || Game.GTR2 ||
                (raceRoomOrIRacing && currentGameState.PenaltiesData.PenaltyType != PenatiesData.DetailedPenaltyType.NONE)))
            {
                if (currentGameState.PenaltiesData.NumOutstandingPenalties > previousGameState.PenaltiesData.NumOutstandingPenalties)
                {
                    lapsCompleted = currentGameState.SessionData.CompletedLaps;
                    // this is a new penalty
                    int delay1 = Utilities.random.Next(1, 5);
                    int delay2 = Utilities.random.Next(7, 12);
                    outstandingPenaltyType = currentGameState.PenaltiesData.PenaltyType;
                    outstandingPenaltyCause = currentGameState.PenaltiesData.PenaltyCause;

                    var message = getPenaltyMessge(outstandingPenaltyType, outstandingPenaltyCause);
                    audioPlayer.playMessage(new QueuedMessage(message, delay1 + 10, secondsDelay: delay1, abstractEvent: this, priority: 15));

                    // queue a '3 laps to serve penalty' message - this might not get played if player crosses s/f line before
                    audioPlayer.playMessage(new QueuedMessage(folderThreeLapsToServe, delay2 + 6, secondsDelay: delay2, abstractEvent: this, priority: 12));

                    // we don't already have a penalty
                    if (penaltyLap == -1 || !hasOutstandingPenalty)
                    {
                        penaltyLap = currentGameState.SessionData.CompletedLaps;
                    }

                    hasOutstandingPenalty = true;
                    hasHadAPenalty = true;
                    // don't know if this is for cutting, just in case we reset the cutting enum
                    trackLimitsMode = TrackLimitsMode.OK;
                }
                else if (previousGameState.PitData.InPitlane && !currentGameState.PitData.InPitlane && !playedNotServedPenalty &&
                    currentGameState.PenaltiesData.NumOutstandingPenalties > 0)
                {
                    // we've exited the pits but there's still an outstanding penalty
                    audioPlayer.playMessage(new QueuedMessage(folderPenaltyNotServed, 0, secondsDelay: 3, abstractEvent: this, priority: 10));
                    playedNotServedPenalty = true;
                }
                else if (currentGameState.SessionData.IsNewLap && currentGameState.PenaltiesData.NumOutstandingPenalties > 0)
                {
                    lapsCompleted = currentGameState.SessionData.CompletedLaps;
                    if (lapsCompleted - penaltyLap >= 2 && !currentGameState.PitData.InPitlane)
                    {
                        // run out of laps, an not in the pitlane
                        if (Utilities.random.NextDouble() < 0.2)
                        {
                            // For variety, sometimes just play basic reminder.
                            audioPlayer.playMessage(new QueuedMessage(folderYouStillHavePenalty, 0, secondsDelay: 5, abstractEvent: this, priority: 10));
                        }
                        else
                        {
                            var message = getOutstandingPenaltyMessage();
                            if (!String.IsNullOrWhiteSpace(message))
                            {
                                audioPlayer.playMessage(new QueuedMessage(message, 0, secondsDelay: 5, abstractEvent: this, priority: 10));
                            }
                        }
                    }
                    else if (lapsCompleted - penaltyLap == 1)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderTwoLapsToServe, pitstopDelay + 6, secondsDelay: pitstopDelay, abstractEvent: this, priority: 10));
                    }
                }
            }
            else if (currentGameState.PenaltiesData.PossibleTrackLimitsViolation
                && GlobalBehaviourSettings.cutTrackWarningsEnabled
                && !warnedOfPossibleTrackLimitsViolationOnThisLap
                && currentGameState.PositionAndMotionData.CarSpeed > 10)
            {
                warnedOfPossibleTrackLimitsViolationOnThisLap = true;
                audioPlayer.playMessage(new QueuedMessage(folderPossibleTrackLimitsViolation, 4, secondsDelay: Utilities.random.Next(2, 4), abstractEvent: this, priority: 0));
            }
            else if ((currentGameState.SessionData.SessionType == SessionType.Race || Game.IRACING) && currentGameState.PenaltiesData.HasSlowDown && !playedSlowdownNotificationOnThisLap)
            {
                if (!waitingToNotifyOfSlowdown)
                {
                    waitingToNotifyOfSlowdown = true;
                    timeToNotifyOfSlowdown = currentGameState.Now.AddSeconds(4);
                }
                else if (currentGameState.Now > timeToNotifyOfSlowdown)
                {
                    playedSlowdownNotificationOnThisLap = true;
                    audioPlayer.playMessage(new QueuedMessage(folderNewPenaltySlowDown, 0, abstractEvent: this));
                    waitingToClearSlowDown = true;
                    waitingToNotifyOfSlowdown = false;
                    timeToNotifyOfSlowdown = DateTime.MinValue;
                }
            }
            else
            {
                if (waitingToClearSlowDown)
                {
                    audioPlayer.playMessage(new QueuedMessage(folderSlowDownPenaltyClear, 0, abstractEvent: this));
                }
                clearPenaltyState();
                // always keep the local cut count up to date even if we've not triggered any warnings.
                cutTrackWarningsCount = currentGameState.PenaltiesData.CutTrackWarnings;
            }
            if ((currentGameState.SessionData.SessionType == SessionType.Race ||
                currentGameState.SessionData.SessionType == SessionType.Qualify ||
                currentGameState.SessionData.SessionType == SessionType.PrivateQualify ||
                currentGameState.SessionData.SessionType == SessionType.Practice ||
                currentGameState.SessionData.SessionType == SessionType.LonePractice) && previousGameState != null &&
                ((previousGameState.PenaltiesData.HasStopAndGo && !currentGameState.PenaltiesData.HasStopAndGo) ||
                (previousGameState.PenaltiesData.HasDriveThrough && !currentGameState.PenaltiesData.HasDriveThrough) ||
                // can't read penalty type in Automobilista (and presumably in rF2).
                (previousGameState.PenaltiesData.NumOutstandingPenalties > currentGameState.PenaltiesData.NumOutstandingPenalties &&
                (Game.RF1 || Game.RF2_LMU || Game.GTR2))))
            {
                audioPlayer.playMessage(new QueuedMessage(folderPenaltyServed, 0, abstractEvent: this, priority: 10));
            }
        }

        private void updateCuttingEnum(GameStateData currentGameState)
        {
            if (currentGameState.SessionData.SessionRunningTime < 60 || GlobalBehaviourSettings.justTheFacts
                || GlobalBehaviourSettings.complaintsCountInThisSession >= GlobalBehaviourSettings.maxComplaintsPerSession)
            {
                trackLimitsMode = TrackLimitsMode.OK;
                return;
            }
            float cutsPerMinute = (60f * (float)totalAnnouncableCutWarnings) / currentGameState.SessionData.SessionRunningTime;
            TrackLimitsMode newTrackLimitsMode = trackLimitsMode;
            switch (trackLimitsMode)
            {
                case TrackLimitsMode.OK:
                    if (totalAnnouncableCutWarnings > 1 && cutsPerMinute > 0.5)
                    {
                        newTrackLimitsMode = TrackLimitsMode.MINOR_CUTTING;
                    }
                    break;
                case TrackLimitsMode.MINOR_CUTTING:
                    if (cutsPerMinute < 0.3)
                    {
                        newTrackLimitsMode = TrackLimitsMode.OK;
                    }
                    else if (totalAnnouncableCutWarnings > 5 && cutsPerMinute > 0.5)
                    {
                        newTrackLimitsMode = TrackLimitsMode.EXCESSIVE_CUTTING;
                    }
                    break;
                case TrackLimitsMode.EXCESSIVE_CUTTING:
                    if (cutsPerMinute < 0.5)
                    {
                        newTrackLimitsMode = TrackLimitsMode.MINOR_CUTTING;
                    }
                    else if (totalAnnouncableCutWarnings > 7 && cutsPerMinute > 0.7)
                    {
                        newTrackLimitsMode = TrackLimitsMode.TAKING_PISS;
                    }
                    break;
                case TrackLimitsMode.TAKING_PISS:
                    if (cutsPerMinute < 0.4)
                    {
                        newTrackLimitsMode = TrackLimitsMode.MINOR_CUTTING;
                    }
                    else if (cutsPerMinute < 0.6)
                    {
                        newTrackLimitsMode = TrackLimitsMode.EXCESSIVE_CUTTING;
                    }
                    break;
            }
            if (trackLimitsMode != newTrackLimitsMode)
            {
                Console.WriteLine("Track limits mode changed from " + trackLimitsMode + " to " + newTrackLimitsMode + " total cuts = " + totalAnnouncableCutWarnings + " cuts-per-minute = " + cutsPerMinute);
            }
            trackLimitsMode = newTrackLimitsMode;
        }

        private string getCutTrackMessage(GameStateData currentGameState)
        {
            if (currentGameState.SessionData.SessionType == SessionType.Race)
            {
                if (!useNewCutTrackSounds)
                {
                    // old cut messages - just use the cutTrackInRace folder:
                    return folderCutTrackInRace;
                }
                else
                {
                    totalAnnouncableCutWarnings++;
                    cutTimesInSession.Add(currentGameState.Now);
                    updateCuttingEnum(currentGameState);
                    return getCutTrackMessage(true, currentGameState.Now);
                }
            }
            else if (!playedTrackCutWarningInPracticeOrQualOnThisLap)
            {
                playedTrackCutWarningInPracticeOrQualOnThisLap = true;
                if (!useNewCutTrackSounds)
                {
                    // old cut track messages - copy-paste of old logic for choosing lapDeleted / cutInPracOrQual / cutInPracOrQualNextLapInvalid:
                    if (Game.RACE_ROOM
                                    && currentGameState.SessionData.TrackDefinition.raceroomRollingStartLapDistance != -1.0f
                                    && currentGameState.PositionAndMotionData.DistanceRoundTrack > currentGameState.SessionData.TrackDefinition.raceroomRollingStartLapDistance)
                    {
                        return Utilities.random.NextDouble() < 0.3 ? folderLapDeleted : folderCutTrackPracticeOrQualNextLapInvalid;
                    }
                    else
                    {
                        return Utilities.random.NextDouble() < 0.3 ? folderLapDeleted : folderCutTrackPracticeOrQual;
                    }
                }
                else
                {
                    lastCutTrackWarningTime = currentGameState.Now;
                    cutTimesInSession.Add(currentGameState.Now);
                    totalAnnouncableCutWarnings++;
                    updateCuttingEnum(currentGameState);
                    if (Game.RACE_ROOM
                        && currentGameState.SessionData.TrackDefinition.raceroomRollingStartLapDistance != -1.0f
                        && currentGameState.PositionAndMotionData.DistanceRoundTrack > currentGameState.SessionData.TrackDefinition.raceroomRollingStartLapDistance)
                    {
                        return folderCutTrackPracticeOrQualNextLapInvalid;
                    }
                    else
                    {
                        return getCutTrackMessage(false, currentGameState.Now);
                    }
                }
            }
            else
            {
                return null;
            }
        }

        private string getCutTrackMessage(bool isRace, DateTime now)
        {
            string messageToPlay = isRace ? cutFoldersForRace[trackLimitsMode] : cutFoldersForNonRace[trackLimitsMode];
            // whether we actually want to play this is down to the taking-the-piss-o-meter setting, the last cut message time
            // and the total number of cuts in this session
            if (totalAnnouncableCutWarnings == 20)
            {
                // before giving up rant at least once
                return cutFoldersForNonRace[TrackLimitsMode.TAKING_PISS];
            }
            if (totalAnnouncableCutWarnings > 20
                || (trackLimitsMode == TrackLimitsMode.TAKING_PISS && (now - lastCutTrackWarningTime).TotalSeconds < 300)
                || (trackLimitsMode == TrackLimitsMode.EXCESSIVE_CUTTING && (now - lastCutTrackWarningTime).TotalSeconds < 200))
            {
                return null;
            }
            else
            {
                return messageToPlay;
            }
        }

        private static readonly List<SpeechCommands.ID> Commands = new List<SpeechCommands.ID>
        {
            SpeechCommands.ID.DO_I_HAVE_A_PENALTY,
            SpeechCommands.ID.DO_I_STILL_HAVE_A_PENALTY,
            SpeechCommands.ID.HAVE_I_SERVED_MY_PENALTY,
            SpeechCommands.ID.SESSION_STATUS,
            SpeechCommands.ID.STATUS,
        };
        public override SpeechCommands.ID HandlesEvent(String voiceMessage)
        {
            return SpeechCommands.SpeechToCommand(Commands, voiceMessage);
        }

        public override void respond(String voiceMessage)
        {
            respond(voiceMessage, HandlesEvent(voiceMessage));
        }
        public override void respond(String voiceMessage, SpeechCommands.ID cmd)
        {
            switch (cmd)
            {
                case SpeechCommands.ID.SESSION_STATUS:
                case SpeechCommands.ID.STATUS:
                {
                    if (hasOutstandingPenalty)
                    {
                        var penaltyMessage = getPenaltyMessge(outstandingPenaltyType, outstandingPenaltyCause);
                        if (lapsCompleted - penaltyLap == 2)
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage("youHaveAPenaltyBoxThisLap", 0,
                                messageFragments: MessageContents(penaltyMessage, PitStops.folderMandatoryPitStopsPitThisLap)));
                        }
                        else
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage(penaltyMessage, 0));
                        }
                    }

                    break;
                }
                default:
                {
                    if (!hasHadAPenalty)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderYouDontHaveAPenalty, 0));
                        return;
                    }

                    switch (cmd)
                    {
                        case SpeechCommands.ID.DO_I_HAVE_A_PENALTY:
                        {
                            if (hasOutstandingPenalty)
                            {
                                var penaltyMessage = getPenaltyMessge(outstandingPenaltyType, outstandingPenaltyCause);
                                if (lapsCompleted - penaltyLap == 2)
                                {
                                    audioPlayer.playMessageImmediately(new QueuedMessage("youHaveAPenaltyBoxThisLap", 0,
                                        messageFragments: MessageContents(penaltyMessage, PitStops.folderMandatoryPitStopsPitThisLap)));
                                }
                                else
                                {
                                    audioPlayer.playMessageImmediately(new QueuedMessage(penaltyMessage, 0));
                                }
                            }
                            else
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage(folderYouDontHaveAPenalty, 0));
                            }

                            break;
                        }
                        case SpeechCommands.ID.HAVE_I_SERVED_MY_PENALTY:
                        {
                            if (hasOutstandingPenalty)
                            {
                                List<MessageFragment> messages = new List<MessageFragment>();
                                messages.Add(MessageFragment.Text(AudioPlayer.folderNo));
                                messages.Add(MessageFragment.Text(getOutstandingPenaltyMessage()));
                                if (lapsCompleted - penaltyLap == 2)
                                {
                                    messages.Add(MessageFragment.Text(PitStops.folderMandatoryPitStopsPitThisLap));
                                }
                                audioPlayer.playMessageImmediately(new QueuedMessage("noYouStillHaveAPenalty", 0, messageFragments: messages));
                            }
                            else
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage("yesYouServedYourPenalty", 0,
                                    messageFragments: MessageContents(AudioPlayer.folderYes, folderPenaltyServed)));
                            }

                            break;
                        }
                        case SpeechCommands.ID.DO_I_STILL_HAVE_A_PENALTY:
                        {
                            if (hasOutstandingPenalty)
                            {
                                List<MessageFragment> messages = new List<MessageFragment>();
                                messages.Add(MessageFragment.Text(AudioPlayer.folderYes));
                                messages.Add(MessageFragment.Text(getOutstandingPenaltyMessage()));
                                if (lapsCompleted - penaltyLap == 2)
                                {
                                    messages.Add(MessageFragment.Text(PitStops.folderMandatoryPitStopsPitThisLap));
                                }
                                audioPlayer.playMessageImmediately(new QueuedMessage("yesYouStillHaveAPenalty", 0, messageFragments: messages));
                            }
                            else
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage("noYouServedYourPenalty", 0,
                                    messageFragments: MessageContents(AudioPlayer.folderNo, folderPenaltyServed)));
                            }

                            break;
                        }
                    }

                    break;
                }
            }
        }

        private String getPenaltyMessge(PenatiesData.DetailedPenaltyType penaltyType, PenatiesData.DetailedPenaltyCause penaltyCause)
        {
            switch (penaltyType)
            {
                case PenatiesData.DetailedPenaltyType.STOP_AND_GO:
                    switch (penaltyCause)
                    {
                        case PenatiesData.DetailedPenaltyCause.NONE:
                            Debug.Assert(false, "Penalty without cause.");
                            break;
                        case PenatiesData.DetailedPenaltyCause.SPEEDING_IN_PITLANE:
                            return folderStopGoSpeedingInPitlane;
                        case PenatiesData.DetailedPenaltyCause.FALSE_START:
                            return folderStopGoFalseStart;
                        case PenatiesData.DetailedPenaltyCause.CUT_TRACK:
                            return folderStopGoCutTrack;
                        case PenatiesData.DetailedPenaltyCause.EXITING_PITS_UNDER_RED:
                            return folderStopGoExitingPitsUnderRed;
                        case PenatiesData.DetailedPenaltyCause.ILLEGAL_PASS_ROLLING_BEFORE_GREEN:
                            return folderStopGoRollingPassBeforeGreen;
                        case PenatiesData.DetailedPenaltyCause.ILLEGAL_PASS_FCY_BEFORE_GREEN:
                            return GlobalBehaviourSettings.useAmericanTerms ? folderStopGoFCYPassBeforeGreenUS : folderStopGoFCYPassBeforeGreenEU;
                        case PenatiesData.DetailedPenaltyCause.EXCEEDED_SINGLE_DRIVER_STINT_LIMIT:
                            return folderStopGoExceedingSingleStintTime;
                        default:
                            Debug.Assert(false, "Unhandled penalty cause");
                            Console.WriteLine("Penalties: unhandled stop/go penalty cause: " + penaltyCause);
                            break;
                    }

                    break;
                case PenatiesData.DetailedPenaltyType.DRIVE_THROUGH:
                    switch (penaltyCause)
                    {
                        case PenatiesData.DetailedPenaltyCause.NONE:
                            Debug.Assert(false, "Penalty without cause.");
                            break;
                        case PenatiesData.DetailedPenaltyCause.SPEEDING_IN_PITLANE:
                            return folderDriveThroughSpeedingInPitlane;
                        case PenatiesData.DetailedPenaltyCause.FALSE_START:
                            return folderDriveThroughFalseStart;
                        case PenatiesData.DetailedPenaltyCause.CUT_TRACK:
                            return folderDriveThroughCutTrack;
                        case PenatiesData.DetailedPenaltyCause.IGNORED_BLUE_FLAG:
                            return folderDriveThroughIgnoredBlueFlag;
                        case PenatiesData.DetailedPenaltyCause.EXCEEDED_SINGLE_DRIVER_STINT_LIMIT:
                            return folderDriveThroughExceedingSingleStintTime;
                        default:
                            Debug.Assert(false, "Unhandled penalty cause");
                            Console.WriteLine("Penalties: unhandled stop/go penalty cause: " + penaltyCause);
                            break;
                    }

                    break;
            }

            // If no detailed message available, play basic message.
            return folderYouHavePenalty;
        }

        private String getOutstandingPenaltyMessage()
        {
            if (hasOutstandingPenalty)
            {
                switch (outstandingPenaltyType)
                {
                    case PenatiesData.DetailedPenaltyType.NONE:
                        return folderYouStillHavePenalty;
                    case PenatiesData.DetailedPenaltyType.STOP_AND_GO:
                        return folderYouStillHaveToServeStopGo;
                    case PenatiesData.DetailedPenaltyType.DRIVE_THROUGH:
                        return folderYouStillHaveToServeDriveThrough;
                    default:
                        Debug.Assert(false, "Unhandled penalty cause");
                        break;
                }
            }

            return String.Empty;
        }
    }
}
