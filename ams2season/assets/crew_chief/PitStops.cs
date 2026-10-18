using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using CrewChiefV4.GameState;
using CrewChiefV4.Audio;
using CrewChiefV4.NumberProcessing;
using CrewChiefV4.R3E;
using System.Threading;

namespace CrewChiefV4.Events
{
    class PitStops : AbstractEvent
    {
        private static float metresToFeet = 3.28084f;

        private readonly Boolean pitBoxPositionCountdownEnabled = UserSettings.GetUserSettings().getBoolean("pit_box_position_countdown");
        private readonly Boolean pitBoxTimeCountdownEnabled = UserSettings.GetUserSettings().getBoolean("pit_box_time_countdown");
        private readonly Boolean pitBoxPositionCountdownInFeet = UserSettings.GetUserSettings().getBoolean("pit_box_position_countdown_in_feet");

        private readonly int pitCountdownEndDistance = UserSettings.GetUserSettings().getInt("pit_box_time_countdown_end_position");

        public static String folderMandatoryPitStopsPitWindowOpensOnLap = "mandatory_pit_stops/pit_window_opens_on_lap";
        public static String folderMandatoryPitStopsPitWindowOpensAfter = "mandatory_pit_stops/pit_window_opens_after";

        public static String folderMandatoryPitStopsFitPrimesThisLap = "mandatory_pit_stops/box_to_fit_primes_now";

        public static String folderMandatoryPitStopsFitOptionsThisLap = "mandatory_pit_stops/box_to_fit_options_now";

        public static String folderMandatoryPitStopsPrimeTyres = "mandatory_pit_stops/prime_tyres";

        public static String folderMandatoryPitStopsOptionTyres = "mandatory_pit_stops/option_tyres";

        private String folderMandatoryPitStopsCanNowFitPrimes = "mandatory_pit_stops/can_now_fit_primes";

        private String folderMandatoryPitStopsCanNowFitOptions = "mandatory_pit_stops/can_now_fit_options";

        private String folderMandatoryPitStopsPitWindowOpening = "mandatory_pit_stops/pit_window_opening";

        private String folderMandatoryPitStopsPitWindowOpen1Min = "mandatory_pit_stops/pit_window_opens_1_min";

        private String folderMandatoryPitStopsPitWindowOpen2Min = "mandatory_pit_stops/pit_window_opens_2_min";

        public static String folderMandatoryPitStopsPitWindowOpen = "mandatory_pit_stops/pit_window_open";

        private String folderMandatoryPitStopsPitWindowCloses1min = "mandatory_pit_stops/pit_window_closes_1_min";

        private String folderMandatoryPitStopsPitWindowCloses2min = "mandatory_pit_stops/pit_window_closes_2_min";

        private String folderMandatoryPitStopsPitWindowClosing = "mandatory_pit_stops/pit_window_closing";

        private String folderMandatoryPitStopsPitWindowClosed = "mandatory_pit_stops/pit_window_closed";

        public static String folderMandatoryPitStopsPitThisLap = "mandatory_pit_stops/pit_this_lap";

        private String folderMandatoryPitStopsPitThisLapTooLate = "mandatory_pit_stops/pit_this_lap_too_late";

        private String folderMandatoryPitStopsPitNow = "mandatory_pit_stops/pit_now";

        private String folderEngageLimiter = "mandatory_pit_stops/engage_limiter";
        private String folderDisengageLimiter = "mandatory_pit_stops/disengage_limiter";

        // for voice responses
        public static String folderMandatoryPitStopsYesStopOnLap = "mandatory_pit_stops/yes_stop_on_lap";
        public static String folderMandatoryPitStopsYesStopAfter = "mandatory_pit_stops/yes_stop_after";
        public static String folderMandatoryPitStopsMissedStop = "mandatory_pit_stops/missed_stop";

        // pit stop messages
        private String folderWatchYourPitSpeed = "mandatory_pit_stops/watch_your_pit_speed";
        private String folderPitCrewReady = "mandatory_pit_stops/pit_crew_ready";
        public static String folderPitStallOccupied = "mandatory_pit_stops/pit_stall_occupied";
        public static String folderPitStallAvailable = "mandatory_pit_stops/pit_stall_available";
        private String folderStopCompleteGo = "mandatory_pit_stops/stop_complete_go";
        private String folderPitStopRequestReceived = "mandatory_pit_stops/pit_stop_requested";
        private String folderPitStopRequestCancelled = "mandatory_pit_stops/pit_request_cancelled";

        // messages used when a pit request or cancel pit request isn't relevant (pcars2 only):
        public static String folderPitAlreadyRequested = "mandatory_pit_stops/pit_stop_already_requested";
        public static String folderPitNotRequested = "mandatory_pit_stops/pit_stop_not_requested";

        private String folderMetres = "mandatory_pit_stops/metres";
        private String folderFeet = "mandatory_pit_stops/feet";
        private String folderBoxPositionIntro = "mandatory_pit_stops/box_in";
        private String folderBoxNow = "mandatory_pit_stops/box_now";

        // separate sounds for "100 metres" and "50 metres" for a nicer pit countdown
        private String folderOneHundredMetreWarning = "mandatory_pit_stops/one_hundred_metres";
        private String folderThreeHundredFeetWarning = "mandatory_pit_stops/three_hundred_feet";
        private String folderFiftyMetreWarning = "mandatory_pit_stops/fifty_metres";
        private String folderOneHundredFeetWarning = "mandatory_pit_stops/one_hundred_feet";

        private String folderPitSpeedLimit = "mandatory_pit_stops/pit_speed_limit";
        private String folderNoPitSpeedLimit = "mandatory_pit_stops/no_pit_speed_limit";

        // R3E pit menu specials
        private String folderWillChangeAllFourTyres = "mandatory_pit_stops/will_change_all_four_tyres"; // "we're changing all 4 tyres"
        private String folderWillChangeFrontTyresOnly = "mandatory_pit_stops/will_change_front_tyres_only"; // "we're changing front tyres only"
        private String folderWillChangeRearTyresOnly = "mandatory_pit_stops/will_change_rear_tyres_only"; // "we're changing rear tyres only"
        private String folderNoTyresThisTime = "mandatory_pit_stops/no_tyres_this_time"; // "we're not changing tyres"
        private String folderWillPutFuelIn = "mandatory_pit_stops/will_put_fuel_in"; // "we're putting fuel in"
        private String folderNoFuelThisTime = "mandatory_pit_stops/no_fuel_this_time"; // "no fuel this time"
        private String folderWillFixFrontAndRearAero = "mandatory_pit_stops/will_fix_front_and_rear_aero"; // "we'll fix the front and rear aero"
        private String folderWillFixFrontAndLeaveRearAero = "mandatory_pit_stops/will_fix_front_and_leave_rear_aero"; // "we'll fix the front aero and leave the rear"
        private String folderWillFixFrontAero = "mandatory_pit_stops/will_fix_front_aero"; // "we'll fix the front aero"
        private String folderWillFixRearAndLeaveFrontAero = "mandatory_pit_stops/will_fix_rear_and_leave_front_aero";  // "we'll fix the rear and leave the front"
        private String folderWillFixRearAero = "mandatory_pit_stops/will_fix_rear_aero";  // "we'll fix the rear aero"
        private String folderWillFixSuspension = "mandatory_pit_stops/will_fix_suspension"; // "we'll fix the suspension"
        private String folderWillLeaveSuspension = "mandatory_pit_stops/will_leave_suspension"; // "we'll leave the suspension"
        private String folderWillBeServingPenalty = "mandatory_pit_stops/will_be_serving_penalty";  // "we'll be serving the penalty"
        // combined fuel and tyres for common cases:
        private String folderWillChangeAllFourTyresAndRefuel = "mandatory_pit_stops/will_change_all_four_tyre_and_refuel"; // "we're refuelling and will change all four tyres"
        private String folderWillChangeAllFourTyresNoFuel = "mandatory_pit_stops/will_change_all_four_tyre_no_fuel"; // "we'll change all four tyres, no fuel this time"
        private String folderWillPutFuelInNoTyresThisTime = "mandatory_pit_stops/will_put_fuel_in_no_tyres"; // "we're putting fuel in, no tyres this time"
        private String folderNoTyresOrFuelThisTime = "mandatory_pit_stops/no_tyres_or_fuel"; // "no tyres or fuel this time"

        // for mandatory stops with minimum duration
        private String folderMandatoryPitstopMinimumTimeIntro = "mandatory_pit_stops/min_pitstop_time_intro";
        private String folderWaitForMandatoryStopTimerIntro = "mandatory_pit_stops/wait_intro";
        private String folderWaitForMandatoryWait = "mandatory_pit_stops/wait";
        private String folderWaitForMandatoryWait5Seconds = "mandatory_pit_stops/wait_5_seconds";
        private String folderLeftPitTooSoon = "mandatory_pit_stops/left_pit_too_soon";

        private int pitWindowOpenLap;

        private int pitWindowClosedLap;

        private Boolean inPitWindow;

        private float pitWindowOpenTime;

        private float pitWindowClosedTime;

        private Boolean pitDataInitialised;

        private Boolean playBoxNowMessage;

        private Boolean playOpenNow;

        private Boolean play1minOpenWarning;

        private Boolean play2minOpenWarning;

        private Boolean playClosedNow;

        private Boolean play1minCloseWarning;

        private Boolean play2minCloseWarning;

        private Boolean playPitThisLap;

        private Boolean mandatoryStopCompleted;

        private Boolean mandatoryStopBoxThisLap;

        private Boolean mandatoryStopMissed;

        private TyreType mandatoryTyreChangeTyreType = TyreType.Unknown_Race;

        private Boolean hasMandatoryTyreChange;

        private Boolean hasMandatoryPitStop;

        private float minDistanceOnCurrentTyre;

        private float maxDistanceOnCurrentTyre;

        private DateTime timeOfLastLimiterWarning = DateTime.MinValue;

        private DateTime timeOfDisengageCheck = DateTime.MaxValue;

        private DateTime timeOfPitRequestOrCancel = DateTime.MinValue;

        private DateTime timeSpeedInPitsWarning = DateTime.MinValue;

        private const int minSecondsBetweenPitRequestCancel = 5;

        private Boolean enableWindowWarnings = true;

        private Boolean pitStallOccupied = false;

        private Boolean warnedAboutOccupiedPitOnThisLap = false;
        public static Boolean playedRequestPitOnThisLap = false;
        public static Boolean playedPitRequestCancelledOnThisLap = false;
        public static Boolean isPittingThisLap = false;

        private float previousDistanceToBox = -1;
        private Boolean playedLimiterLineToPitBoxDistanceWarning = false;
        private Boolean played100MetreOr300FeetWarning = false;
        private Boolean played50MetreOr100FeetWarning = false;

        private float estimatedPitSpeed = 20;

        // box in 5, 4, 3, 2, 1, BOX
        private float[] pitCountdownTriggerPoints = new float[6];
        private Boolean playedBoxIn = false;
        private int nextPitDistanceIndex = 0;
        private DateTime pitEntryDistancePlayedTime = DateTime.MinValue;
        private DateTime pitEntryTime = DateTime.MinValue;
        private int pitEntryLap = 0;
        private Boolean getPitCountdownTimingPoints = false;

        private DateTime timeStartedAppoachingPitsCheck = DateTime.MaxValue;

        // Announce pit speed limit once per session.  Voice command response also counts.
        private bool pitLaneSpeedWarningAnnounced = false;

        private bool playedMandatoryStopMinWaitTime = false;
        public static bool waitingForMandatoryStopTimer = false;    // can be used by other events to suppress sounds when this timer is ticking
        private bool playedWait5Seconds = false;
        private DateTime nextWaitWarningDue = DateTime.MaxValue;

        // this is not cleared between sessions. We need the pit exit location in order
        // to estimate the time between leaving the pit stall and reaching the pit exit in R3E with a min stop time.
        // The array contains the x/z world position coordinates
        private Dictionary<string, float[]> pitExitPoints = new Dictionary<string, float[]>();
        // time take to get from the box to the pit end, assuming we run on the limiter the whole way
        private float timeFromBoxToEndOfPitLane = 0;
        // calculated time to wait in the box allowing for the time taken exit the pitlane
        private float mandatoryPitTimeToWait = 0;
        // but i'm not sure if the above is actually needed - either the min stop duration covers the entire pit process (entry, stop, exit)
        // or it covers only the stop part, or it covers the entry-and-stop
        private bool includeExitTimeInStopDuration = true;

        private string trackNameInitialPitSpeedLimitAnnounced = null;
        private float lastInitialPitspeedLimitAnnounced = -1.0f;

        public PitStops(AudioPlayer audioPlayer)
        {
            this.audioPlayer = audioPlayer;
        }

        public override List<SessionType> applicableSessionTypes
        {
            get { return new List<SessionType> { SessionType.Practice, SessionType.Qualify, SessionType.PrivateQualify, SessionType.Race, SessionType.LonePractice }; }
        }

        public override List<SessionPhase> applicableSessionPhases
        {
            get { return new List<SessionPhase> { SessionPhase.Green, SessionPhase.Countdown, SessionPhase.Finished, SessionPhase.Checkered, SessionPhase.FullCourseYellow, SessionPhase.Garage /*rF2 Garage phase sticks while exiting pits in practice/qualification, so we need to handle it*/ }; }
        }

        public override void clearState()
        {
            timeOfLastLimiterWarning = DateTime.MinValue;
            timeOfDisengageCheck = DateTime.MaxValue;
            timeOfPitRequestOrCancel = DateTime.MinValue;
            timeStartedAppoachingPitsCheck = DateTime.MaxValue;
            timeSpeedInPitsWarning = DateTime.MinValue;
            pitWindowOpenLap = 0;
            pitWindowClosedLap = 0;
            pitWindowOpenTime = 0;
            pitWindowClosedTime = 0;
            inPitWindow = false;
            pitDataInitialised = false;
            playBoxNowMessage = false;
            play2minOpenWarning = false;
            play2minCloseWarning = false;
            play1minOpenWarning = false;
            play1minCloseWarning = false;
            playClosedNow = false;
            playOpenNow = false;
            playPitThisLap = false;
            mandatoryStopCompleted = false;
            mandatoryStopBoxThisLap = false;
            mandatoryStopMissed = false;
            mandatoryTyreChangeTyreType = TyreType.Unknown_Race;
            hasMandatoryPitStop = false;
            hasMandatoryTyreChange = false;
            minDistanceOnCurrentTyre = -1;
            maxDistanceOnCurrentTyre = -1;
            enableWindowWarnings = true;
            pitStallOccupied = false;
            warnedAboutOccupiedPitOnThisLap = false;
            previousDistanceToBox = -1;
            played100MetreOr300FeetWarning = false;
            played50MetreOr100FeetWarning = false;
            playedLimiterLineToPitBoxDistanceWarning = false;
            playedRequestPitOnThisLap = false;
            playedPitRequestCancelledOnThisLap = false;
            estimatedPitSpeed = 20;
            pitCountdownTriggerPoints = new float[6];
            playedBoxIn = false;
            pitEntryDistancePlayedTime = DateTime.MinValue;
            pitEntryTime = DateTime.MinValue;
            pitEntryLap = 0;
            nextPitDistanceIndex = 0;
            getPitCountdownTimingPoints = false;
            pitLaneSpeedWarningAnnounced = false;
            playedMandatoryStopMinWaitTime = false;
            waitingForMandatoryStopTimer = false;
            nextWaitWarningDue = DateTime.MaxValue;
            playedWait5Seconds = false;
            mandatoryPitTimeToWait = 0;
            timeFromBoxToEndOfPitLane = 0;
            // AMS (RF1) uses the pit window calculations to make 'box now' calls for scheduled stops, but we don't want
            // the pit window opening / closing warnings.
            // Try also applying the same approach to rF2.
            if (Game.RF1 ||
                Game.RF2_LMU ||
                Game.GTR2)
            {
                enableWindowWarnings = false;
            }
        }

        public override bool isMessageStillValid(String eventSubType, GameStateData currentGameState, Dictionary<String, Object> validationData)
        {
            if (base.isMessageStillValid(eventSubType, currentGameState, validationData))
            {
                if (eventSubType == folderPitStopRequestReceived)
                {
                    return currentGameState.PitData.HasRequestedPitStop;
                }
                else if (eventSubType == folderPitStopRequestCancelled)
                {
                    return !currentGameState.PitData.HasRequestedPitStop;
                }
                else if (eventSubType == folderDisengageLimiter)
                {
                    return currentGameState.PitData.limiterStatus == PitData.LimiterStatus.ACTIVE;
                }
            }
            else
            {
                return false;
            }

            return true;
        }

        private float getDistanceToBox(GameStateData currentGameState)
        {
            if (currentGameState.PitData.PitBoxLocationEstimate == null || currentGameState.PositionAndMotionData.WorldPosition == null)
            {
                float distanceToBox = currentGameState.PitData.PitBoxPositionEstimate - currentGameState.PositionAndMotionData.DistanceRoundTrack;
                if (distanceToBox < 0)
                {
                    distanceToBox = currentGameState.SessionData.TrackDefinition.trackLength + distanceToBox;
                }
                return distanceToBox;
            }
            else
            {
                return (float) Math.Sqrt(Math.Pow(currentGameState.PitData.PitBoxLocationEstimate[0] - currentGameState.PositionAndMotionData.WorldPosition[0], 2)
                    + Math.Pow(currentGameState.PitData.PitBoxLocationEstimate[2] - currentGameState.PositionAndMotionData.WorldPosition[2], 2));
            }
        }

        private void getPitCountdownTriggerPoints(float pitlaneSpeed)
        {
            float secondsBetweenEachCall = 1f;
            // we want the 0 (or 'BOX!') call to come at, say 20metres, so the last element is at 20 metres from the box
            float distance = pitCountdownEndDistance;
            for (int i = pitCountdownTriggerPoints.Length - 1; i >= 0; i--)
            {
                pitCountdownTriggerPoints[i] = distance;
                distance = distance + (pitlaneSpeed * secondsBetweenEachCall);
            }
            playedBoxIn = false;
            nextPitDistanceIndex = 0;
        }

        override protected void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (currentGameState.SessionData.SessionPhase == SessionPhase.Finished
                && currentGameState.ControlData.ControlType == ControlType.AI)
            {
                return;
            }

            if (!currentGameState.inCar)
            {
                // Reset pit countdown in games that detect being in the garage.
                previousDistanceToBox = -1;
                return;
            }

            if (Game.PCARS3)
            {
                return;
            }

            // for r3e get the pit exit point for mandatory stop timing
            if (Game.RACE_ROOM
                && previousGameState != null && previousGameState.PitData.InPitlane && !currentGameState.PitData.InPitlane
                && currentGameState.SessionData.TrackDefinition != null && currentGameState.PositionAndMotionData.CarSpeed > 10)
            {
                pitExitPoints[currentGameState.SessionData.TrackDefinition.name] = new float[]{
                    currentGameState.PositionAndMotionData.WorldPosition[0], currentGameState.PositionAndMotionData.WorldPosition[2] };
            }

            this.pitStallOccupied = currentGameState.PitData.PitStallOccupied;
            if (currentGameState.SessionData.IsNewLap)
            {
                warnedAboutOccupiedPitOnThisLap = false;
                playedRequestPitOnThisLap = false;
                playedPitRequestCancelledOnThisLap = false;
            }

            // in R3E, if we've requested a pitstop announce the expected actions when we're between 200 and 300 metres from the start line
            // and haven't just made the request
            if (Game.RACE_ROOM && R3EPitMenuManager.outstandingPitstopRequest
               && currentGameState.PositionAndMotionData.DistanceRoundTrack > currentGameState.SessionData.TrackDefinition.trackLength - 700
               && currentGameState.PositionAndMotionData.DistanceRoundTrack < currentGameState.SessionData.TrackDefinition.trackLength - 300
               && currentGameState.Now > R3EPitMenuManager.timeWeCanAnnouncePitActions)
            {
                announceR3EPitActions(currentGameState.PitData.InPitlane, false);
            }

            if (previousGameState != null && (pitBoxPositionCountdownEnabled || pitBoxTimeCountdownEnabled) &&
                currentGameState.PositionAndMotionData.CarSpeed > 2 &&
                (currentGameState.PitData.PitBoxPositionEstimate > 0 || currentGameState.PitData.PitBoxLocationEstimate != null ) &&
                !currentGameState.PenaltiesData.HasDriveThrough &&
                !((Game.RF2_LMU ||
                   Game.GTR2) &&
                   currentGameState.PitData.OnOutLap && currentGameState.SessionData.SessionType != SessionType.Race))  // In rF2 countdown pit countdown messages get triggered on exit from the garage.
            {
                if (previousGameState.PitData.InPitlane && !currentGameState.PitData.InPitlane)
                {
                    playedLimiterLineToPitBoxDistanceWarning = false;
                }

                float distanceToBox = getDistanceToBox(currentGameState);
                if (!previousGameState.PitData.InPitlane && currentGameState.PitData.InPitlane)
                {
                    // just entered the pitlane
                    pitEntryTime = currentGameState.Now;
                    pitEntryLap = currentGameState.SessionData.LapCount;
                    getPitCountdownTimingPoints = pitBoxTimeCountdownEnabled;

                    previousDistanceToBox = 0;
                    played100MetreOr300FeetWarning = false;
                    played50MetreOr100FeetWarning = false;
                    if (pitBoxPositionCountdownEnabled)
                    {
                        // here we assume that being >250 metres from the box means the time countdown won't interfere enough to make it
                        // unless - note that <250 metres will result in a truncated countdown starting at 3 or 4
                        if (distanceToBox > 250 && !playedLimiterLineToPitBoxDistanceWarning)
                        {
                            int distanceToBoxInt = (int)(distanceToBox * (pitBoxPositionCountdownInFeet ? metresToFeet : 1f));
                            int distanceToBoxRounded;
                            if (distanceToBoxInt % 10 == 0)
                                distanceToBoxRounded = distanceToBoxInt;
                            else
                                distanceToBoxRounded = (10 - distanceToBoxInt % 10) + distanceToBoxInt;

                            List<MessageFragment> messageContents = new List<MessageFragment>();
                            messageContents.Add(MessageFragment.Text(folderBoxPositionIntro));
                            messageContents.Add(MessageFragment.Integer(distanceToBoxRounded, false));   // explicity disable short hundreds here, forcing the full "one hundred" sound
                            messageContents.Add(MessageFragment.Text(pitBoxPositionCountdownInFeet ? folderFeet : folderMetres));
                            QueuedMessage firstPitCountdown = new QueuedMessage("pit_entry_to_box_distance_warning", 2, messageFragments: messageContents, abstractEvent: this, priority: 10);
                            audioPlayer.playMessage(firstPitCountdown);
                            pitEntryDistancePlayedTime = currentGameState.Now;
                        }
                        playedLimiterLineToPitBoxDistanceWarning = true;
                    }
                }
                else if (previousGameState.PitData.InPitlane && currentGameState.PitData.InPitlane && previousDistanceToBox > -1)
                {
                    if (pitBoxTimeCountdownEnabled)
                    {
                        // first get the timing point positions
                        if (getPitCountdownTimingPoints)
                        {
                            if ((currentGameState.Now - pitEntryTime).TotalSeconds > 0.5 && (currentGameState.Now - pitEntryTime).TotalSeconds < 1)
                            {
                                getPitCountdownTriggerPoints(estimatedPitSpeed);
                                getPitCountdownTimingPoints = false;
                            }
                        }
                        else
                        {
                            if ((currentGameState.Now - pitEntryDistancePlayedTime).TotalSeconds > 3)
                            {
                                // the first item takes longer to play because it's preceeded by "box in.."
                                float pointAdjustment = playedBoxIn ? 0 : currentGameState.PositionAndMotionData.CarSpeed * 1.3f;
                                for (int i = nextPitDistanceIndex; i < pitCountdownTriggerPoints.Length; i++)
                                {
                                    if (distanceToBox < pitCountdownTriggerPoints[i] + pointAdjustment && distanceToBox > pitCountdownTriggerPoints[i] + pointAdjustment - 5)
                                    {
                                        // ensure an unplayed distance message isn't still hanging around in the queue
                                        int purgeCount = audioPlayer.purgeQueues();
                                        Console.WriteLine("removed " + purgeCount + " messages from the queues before triggering pit countdown");
                                        nextPitDistanceIndex = i + 1;
                                        if (i < pitCountdownTriggerPoints.Length - 2 && !playedBoxIn)
                                        {
                                            audioPlayer.pauseQueue(10);
                                            // box in 5...
                                            int num = pitCountdownTriggerPoints.Length - (i + 1);
                                            Console.WriteLine("BOX IN " + num + " at " + distanceToBox);
                                            audioPlayer.playMessageImmediately(new QueuedMessage("pit_time_countdown_" + num, 1,
                                                messageFragments: MessageContents(folderBoxPositionIntro, num), type: SoundType.CRITICAL_MESSAGE, priority: 10), true);
                                            playedBoxIn = true;
                                        }
                                        else if (i == pitCountdownTriggerPoints.Length - 1)
                                        {
                                            // BOX
                                            Console.WriteLine("BOX IN NOW at " + distanceToBox);
                                            audioPlayer.playMessageImmediately(new QueuedMessage("pit_time_countdown_end", 1,
                                                messageFragments: MessageContents(folderBoxNow), type: SoundType.CRITICAL_MESSAGE, priority: 10));
                                            audioPlayer.unpauseQueue();
                                        }
                                        else if (playedBoxIn)
                                        {
                                            // 4, 3, 2, 1
                                            int num = pitCountdownTriggerPoints.Length - (i + 1);
                                            Console.WriteLine("BOX IN ... " + num + " at " + distanceToBox);
                                            audioPlayer.playMessageImmediately(new QueuedMessage("pit_time_countdown_" + num, 1,
                                                messageFragments: MessageContents(num), type: SoundType.CRITICAL_MESSAGE, priority: 10), true);
                                        }
                                        break;
                                    }
                                }
                                previousDistanceToBox = distanceToBox;
                            }
                        }
                    }
                    else
                    {
                        float adjustment = pitBoxPositionCountdownInFeet ? 30f : 10f; // as we're moving at like 20m/s, move the warnings back half a second
                        float distanceUpperFor100MetreOr300FeetWarning = pitBoxPositionCountdownInFeet ? 300f / metresToFeet : 100f;
                        float distanceLowerFor100MetreOr300FeetWarning = distanceUpperFor100MetreOr300FeetWarning - adjustment;

                        float distanceUpperFor50MetreOr100FeetWarning = pitBoxPositionCountdownInFeet ? 100f / metresToFeet : 50f;
                        float distanceLowerFor50MetreOr100FeetWarning = distanceUpperFor50MetreOr100FeetWarning - adjustment;

                        if (!played100MetreOr300FeetWarning && distanceToBox < distanceUpperFor100MetreOr300FeetWarning && previousDistanceToBox > distanceLowerFor100MetreOr300FeetWarning)
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage(
                                pitBoxPositionCountdownInFeet ? folderThreeHundredFeetWarning : folderOneHundredMetreWarning, 0, abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                            previousDistanceToBox = distanceToBox;
                            played100MetreOr300FeetWarning = true;
                        }
                        // VL: I see some tracks with pit stall as close as 35 meters to the entrance.  Shall we add "less than 30 meters" message if nothing played before?
                        else if (!played50MetreOr100FeetWarning && distanceToBox < distanceUpperFor50MetreOr100FeetWarning && previousDistanceToBox > distanceLowerFor50MetreOr100FeetWarning)
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage(
                                 pitBoxPositionCountdownInFeet ? folderOneHundredFeetWarning : folderFiftyMetreWarning, 0, abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE,priority: 0));
                            previousDistanceToBox = distanceToBox;
                            played50MetreOr100FeetWarning = true;
                        }
                        else if (previousDistanceToBox > -1)
                        {
                            previousDistanceToBox = distanceToBox;
                        }
                    }
                }
            }

            if (!mandatoryStopCompleted && currentGameState.PitData.MandatoryPitStopCompleted)
            {
                mandatoryStopCompleted = true;
                mandatoryStopMissed = false;
                playPitThisLap = false;
                playBoxNowMessage = false;
                mandatoryStopBoxThisLap = false;
            }
            if (currentGameState.PitData.limiterStatus != PitData.LimiterStatus.NOT_AVAILABLE && currentGameState.Now > timeOfLastLimiterWarning + TimeSpan.FromSeconds(30))
            {
                if ((currentGameState.SessionData.SectorNumber == 1 &&
                    currentGameState.Now > timeOfDisengageCheck && !currentGameState.PitData.InPitlane && currentGameState.PitData.limiterStatus == PitData.LimiterStatus.ACTIVE &&
                    !( Game.RF2_LMU && currentGameState.SessionData.SessionPhase == SessionPhase.Finished) // In rF2, Sector number is not updated on cooldown lap, hence ignore disengage limiter logic.
                    && !Game.IRACING) ||
                    (  Game.IRACING &&
                    currentGameState.Now > timeOfDisengageCheck && currentGameState.PitData.OnOutLap && !currentGameState.PitData.InPitlane &&
                    currentGameState.PitData.limiterStatus == PitData.LimiterStatus.ACTIVE && !currentGameState.PitData.IsApproachingPitlane))
                {
                    // in S1 but have exited pits, and we're expecting the limit to have been turned off
                    timeOfDisengageCheck = DateTime.MaxValue;
                    timeOfLastLimiterWarning = currentGameState.Now;
                    audioPlayer.playMessageImmediately(new QueuedMessage(folderDisengageLimiter, 5, abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 7));
                }
                else if (previousGameState != null)
                {
                    if (!previousGameState.PitData.InPitlane && currentGameState.PitData.InPitlane)
                    {
                        if (currentGameState.PitData.limiterStatus == PitData.LimiterStatus.INACTIVE && currentGameState.PositionAndMotionData.CarSpeed > 1
                            && (currentGameState.PitData.PitSpeedLimit == -1.0f || currentGameState.PitData.pitlaneHasSpeedLimit()))
                        {
                            // just entered the pit lane with no limiter active
                            audioPlayer.playMessageImmediately(new QueuedMessage(folderEngageLimiter, 1, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                            timeOfLastLimiterWarning = currentGameState.Now;
                        }
                    }
                    else if ((currentGameState.SessionData.SectorNumber == 1 &&
                        previousGameState.PitData.InPitlane && !currentGameState.PitData.InPitlane && currentGameState.PitData.limiterStatus == PitData.LimiterStatus.ACTIVE && !Game.IRACING)
                        || (currentGameState.PitData.IsAtPitExit && currentGameState.PitData.limiterStatus == PitData.LimiterStatus.ACTIVE && Game.IRACING))
                    {
                        // just left the pitlane with the limiter active - wait 2 seconds then warn
                        timeOfDisengageCheck = currentGameState.Now + TimeSpan.FromSeconds(2);
                    }
                }
                // make sure we reset the disengage timer if we left the pits and disabled the limiter in time.
                if (timeOfDisengageCheck != DateTime.MaxValue && currentGameState.PitData.limiterStatus == PitData.LimiterStatus.INACTIVE && !currentGameState.PitData.InPitlane)
                {
                    timeOfDisengageCheck = DateTime.MaxValue;
                }
            }
            else if (previousGameState != null
                && currentGameState.PitData.limiterStatus == PitData.LimiterStatus.NOT_AVAILABLE
                && !previousGameState.PitData.InPitlane && currentGameState.PitData.InPitlane  // Just entered the pits
                && currentGameState.Now > timeSpeedInPitsWarning + TimeSpan.FromSeconds(120)  // We did not play this on pit approach
                && previousGameState.PositionAndMotionData.CarSpeed > 2.0f && currentGameState.PositionAndMotionData.CarSpeed > 2.0f  // Guard against tow, teleport, returning to ISI game's Monitor and other bullshit
                && currentGameState.SessionData.SessionRunningTime > 30.0f  // Sanity check !inPts -> inPits flip on session start.
                && (currentGameState.PitData.PitSpeedLimit == -1.0f || currentGameState.PitData.pitlaneHasSpeedLimit()))
            {
                if (currentGameState.PitData.PitSpeedLimit == -1.0f
                    || pitLaneSpeedWarningAnnounced)  // Announce pitlane speed limit automatically only once per session
                {
                    if (currentGameState.PitData.PitSpeedLimit == -1.0f  // Only announce "watch your speed" message if we have no pit speed data.
                        || currentGameState.PitData.pitlaneHasSpeedLimit())  // Or, if we know for sure there's a speed limit.
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderWatchYourPitSpeed, 2, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                }
                else
                {
                    announcePitlaneSpeedLimit(currentGameState, false /*possiblyPlayIntro*/, false /*voiceResponse*/);
                    pitLaneSpeedWarningAnnounced = true;
                }
            }
            if (currentGameState.SessionData.SessionType == SessionType.Race && currentGameState.PitData.HasMandatoryPitStop &&
                (currentGameState.SessionData.SessionPhase == SessionPhase.Green || currentGameState.SessionData.SessionPhase == SessionPhase.FullCourseYellow))
            {
                // allow this data to be reinitialised during a race (hack for AMS)
                if (!pitDataInitialised || currentGameState.PitData.ResetEvents)
                {
                    mandatoryStopCompleted = false;
                    mandatoryStopBoxThisLap = false;
                    mandatoryStopMissed = false;
                    Console.WriteLine("Pit start = " + currentGameState.PitData.PitWindowStart + ", pit end = " + currentGameState.PitData.PitWindowEnd);

                    hasMandatoryPitStop = currentGameState.PitData.HasMandatoryPitStop;
                    hasMandatoryTyreChange = currentGameState.PitData.HasMandatoryTyreChange;
                    mandatoryTyreChangeTyreType = currentGameState.PitData.MandatoryTyreChangeRequiredTyreType;
                    maxDistanceOnCurrentTyre = currentGameState.PitData.MaxPermittedDistanceOnCurrentTyre;
                    minDistanceOnCurrentTyre = currentGameState.PitData.MinPermittedDistanceOnCurrentTyre;

                    if (currentGameState.SessionData.SessionNumberOfLaps > 0)
                    {
                        pitWindowOpenLap = (int) currentGameState.PitData.PitWindowStart;
                        pitWindowClosedLap = (int) currentGameState.PitData.PitWindowEnd;
                        playPitThisLap = true;
                    }
                    else if (currentGameState.SessionData.SessionTimeRemaining > 0)
                    {
                        pitWindowOpenTime = currentGameState.PitData.PitWindowStart;
                        pitWindowClosedTime = currentGameState.PitData.PitWindowEnd;
                        if (pitWindowOpenTime > 0)
                        {
                            play2minOpenWarning = pitWindowOpenTime > 2;
                            play1minOpenWarning = pitWindowOpenTime > 1;
                            playOpenNow = true;
                        }
                        if (pitWindowClosedTime > 0)
                        {
                            play2minCloseWarning = pitWindowClosedTime > 2;
                            play1minCloseWarning = pitWindowClosedTime > 1;
                            playClosedNow = true;
                            playPitThisLap = true;
                        }
                    }
                    else
                    {
                        Console.WriteLine("Error getting pit data");
                    }
                    pitDataInitialised = true;
                }
                else
                {
                    // Local var to make logic clearer
                    float raceRunningTime = currentGameState.SessionData.SessionTotalRunTime - currentGameState.SessionData.SessionTimeRemaining;

                    if (currentGameState.SessionData.IsNewLap && currentGameState.SessionData.CompletedLaps > 0)
                    {
                        if (currentGameState.SessionData.SessionNumberOfLaps > 0)
                        {   // Fixed length race
                            if (currentGameState.PitData.PitWindow != PitWindow.StopInProgress &&
                                currentGameState.PitData.PitWindow != PitWindow.Completed && !currentGameState.PitData.InPitlane)
                            {
                                int delay = Utilities.random.Next(0, 20);
                                if (maxDistanceOnCurrentTyre > 0 && currentGameState.SessionData.CompletedLaps == maxDistanceOnCurrentTyre && playPitThisLap)
                                {
                                    playBoxNowMessage = true;
                                    playPitThisLap = false;
                                    mandatoryStopBoxThisLap = true;
                                    switch (mandatoryTyreChangeTyreType)
                                    {
                                        case TyreType.Prime:
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsFitPrimesThisLap, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                            break;
                                        case TyreType.Option:
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsFitOptionsThisLap, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                            break;
                                        default:
                                            Log.Commentary("Pit this lap (mandatory tyre stop in fixed length race)");
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitThisLap, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                            break;
                                    }
                                }
                                else if (minDistanceOnCurrentTyre > 0 && currentGameState.SessionData.CompletedLaps == minDistanceOnCurrentTyre)
                                {
                                    switch (mandatoryTyreChangeTyreType)
                                    {
                                        case TyreType.Prime:
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsCanNowFitPrimes, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 5));
                                            break;
                                        case TyreType.Option:
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsCanNowFitOptions, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 5));
                                            break;
                                    }
                                }
                            }

                            if (pitWindowOpenLap > 0 && currentGameState.SessionData.CompletedLaps == pitWindowOpenLap - 1)
                            {
                                // note this is a 'pit window opens at the end of this lap' message,
                                // so we play it 1 lap before the window opens
                                if (enableWindowWarnings)
                                {
                                    int delay = Utilities.random.Next(0, 20);
                                    audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitWindowOpening, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                }
                            }
                            else if (pitWindowOpenLap > 0 && currentGameState.SessionData.CompletedLaps == pitWindowOpenLap)
                            {
                                inPitWindow = true;
                                if (enableWindowWarnings)
                                {
                                    audioPlayer.setBackgroundSound(AudioPlayer.dtmPitWindowOpenBackground);
                                    audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitWindowOpen, 0, abstractEvent: this, priority: 10));
                                }
                            }
                            else if (pitWindowClosedLap > 0 && currentGameState.SessionData.CompletedLaps == pitWindowClosedLap - 1)
                            {
                                int delay = Utilities.random.Next(0, 20);
                                if (enableWindowWarnings)
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitWindowClosing, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                }
                                if (currentGameState.PitData.PitWindow != PitWindow.Completed && !currentGameState.PitData.InPitlane &&
                                    currentGameState.PitData.PitWindow != PitWindow.StopInProgress)
                                {
                                    playBoxNowMessage = true;
                                    switch (mandatoryTyreChangeTyreType)
                                    {
                                        case TyreType.Prime:
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsFitPrimesThisLap, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                            break;
                                        case TyreType.Option:
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsFitOptionsThisLap, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                            break;
                                        default:
                                            Log.Commentary("Pit this lap (pit window, fixed length race)");
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitThisLap, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                            break;
                                    }
                                }
                            }
                            else if (pitWindowClosedLap > 0 && currentGameState.SessionData.CompletedLaps == pitWindowClosedLap)
                            {
                                mandatoryStopBoxThisLap = false;
                                inPitWindow = false;
                                if (currentGameState.PitData.PitWindow != PitWindow.Completed)
                                {
                                    mandatoryStopMissed = true;
                                }
                                if (enableWindowWarnings)
                                {
                                    audioPlayer.setBackgroundSound(AudioPlayer.dtmPitWindowClosedBackground);
                                    audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitWindowClosed, 0, abstractEvent: this, priority: 10));
                                }
                            }
                        }
                        else if (currentGameState.SessionData.SessionTimeRemaining > 0)
                        {   // Timed race
                            if (pitWindowClosedTime > 0 && currentGameState.PitData.PitWindow != PitWindow.StopInProgress &&
                                !currentGameState.PitData.InPitlane &&
                                currentGameState.PitData.PitWindow != PitWindow.Completed &&
                                pitWindowOpenTime > 0 &&
                                raceRunningTime > pitWindowOpenTime * 60 &&
                                raceRunningTime < pitWindowClosedTime * 60)
                            {
                                double timeLeftToPit = pitWindowClosedTime * 60 - raceRunningTime;
                                if (playPitThisLap && currentGameState.SessionData.PlayerLapTimeSessionBest + 10 > timeLeftToPit)
                                {
                                    // oh dear, we might have missed the pit window.
                                    playBoxNowMessage = true;
                                    playPitThisLap = false;
                                    mandatoryStopBoxThisLap = true;
                                    if (enableWindowWarnings)
                                    {
                                        audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitThisLapTooLate, 0, abstractEvent: this, priority: 10));
                                    }
                                }
                                else if (playPitThisLap && currentGameState.SessionData.PlayerLapTimeSessionBest + 10 < timeLeftToPit &&
                                         (currentGameState.SessionData.PlayerLapTimeSessionBest * 2) + 10 > timeLeftToPit)
                                {
                                    // we probably won't make it round twice - pit at the end of this lap
                                    playBoxNowMessage = true;
                                    playPitThisLap = false;
                                    mandatoryStopBoxThisLap = true;
                                    int delay = Utilities.random.Next(0, 20);
                                    switch (mandatoryTyreChangeTyreType)
                                    {
                                        case TyreType.Prime:
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsFitPrimesThisLap, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                            break;
                                        case TyreType.Option:
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsFitOptionsThisLap, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                            break;
                                        default:
                                            Log.Commentary("Pit this lap (pit window, timed race)");
                                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitThisLap, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                            break;
                                    }
                                }
                            }
                        }
                    }

                    if (playOpenNow && currentGameState.SessionData.SessionTimeRemaining > 0 &&
                        (raceRunningTime > (pitWindowOpenTime * 60) ||
                         currentGameState.PitData.PitWindow == PitWindow.Open))
                    {
                        playOpenNow = false;
                        play1minOpenWarning = false;
                        play2minOpenWarning = false;
                        if (enableWindowWarnings)
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitWindowOpen, 0, abstractEvent: this, priority: 10));
                        }
                    }
                    else if (play1minOpenWarning && currentGameState.SessionData.SessionTimeRemaining > 0 &&
                        raceRunningTime > ((pitWindowOpenTime - 1) * 60))
                    {
                        play1minOpenWarning = false;
                        play2minOpenWarning = false;
                        if (enableWindowWarnings)
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitWindowOpen1Min, 20, abstractEvent: this, priority: 3));
                        }
                    }
                    else if (play2minOpenWarning && currentGameState.SessionData.SessionTimeRemaining > 0 &&
                        raceRunningTime > ((pitWindowOpenTime - 2) * 60))
                    {
                        play2minOpenWarning = false;
                        if (enableWindowWarnings)
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitWindowOpen2Min, 30, abstractEvent: this, priority: 10));
                        }
                    }
                    else if (pitWindowClosedTime > 0 && playClosedNow && currentGameState.SessionData.SessionTimeRemaining > 0 &&
                        raceRunningTime > (pitWindowClosedTime * 60))
                    {
                        playClosedNow = false;
                        playBoxNowMessage = false;
                        play1minCloseWarning = false;
                        play2minCloseWarning = false;
                        playPitThisLap = false;
                        mandatoryStopBoxThisLap = false;
                        if (currentGameState.PitData.PitWindow != PitWindow.Completed)
                        {
                            mandatoryStopMissed = true;
                        }
                        if (enableWindowWarnings)
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitWindowClosed, 0, abstractEvent: this, priority: 10));
                        }
                    }
                    else if (pitWindowClosedTime > 0 && play1minCloseWarning && currentGameState.SessionData.SessionTimeRemaining > 0 &&
                        raceRunningTime > ((pitWindowClosedTime - 1) * 60))
                    {
                        play1minCloseWarning = false;
                        play2minCloseWarning = false;
                        if (enableWindowWarnings)
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitWindowCloses1min, 20, abstractEvent: this, priority: 10));
                        }
                    }
                    else if (pitWindowClosedTime > 0 && play2minCloseWarning && currentGameState.SessionData.SessionTimeRemaining > 0 &&
                        raceRunningTime > ((pitWindowClosedTime - 2) * 60))
                    {
                        play2minCloseWarning = false;
                        if (enableWindowWarnings)
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitWindowCloses2min, 30, abstractEvent: this, priority: 10));
                        }
                    }

                    // for Automobilista, sector update lag time means sometimes we miss the pit entrance before this message plays
                    if (playBoxNowMessage && currentGameState.SessionData.SectorNumber == 2 &&
                        Game.RF1)
                    {
                        playBoxNowMessage = false;
                        // pit entry is right at sector 3 timing line, play message part way through sector 2 to give us time to pit
                        int messageDelay = currentGameState.SessionData.PlayerBestSector2Time > 0 ? (int)(currentGameState.SessionData.PlayerBestSector2Time * 0.7) : 15;
                        audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitNow, messageDelay + 6, secondsDelay: messageDelay, abstractEvent: this, priority: 10));
                    }

                    if (playBoxNowMessage && currentGameState.SessionData.SectorNumber == 3)
                    {
                        playBoxNowMessage = false;
                        if (!currentGameState.PitData.InPitlane && currentGameState.PitData.PitWindow != PitWindow.StopInProgress &&
                            currentGameState.PitData.PitWindow != PitWindow.Completed)
                        {
                            switch (mandatoryTyreChangeTyreType)
                            {
                                case TyreType.Prime:
                                    audioPlayer.playMessage(new QueuedMessage("box_now_for_primes", 9, secondsDelay: 3,
                                        messageFragments: MessageContents(folderMandatoryPitStopsPitNow, folderMandatoryPitStopsPrimeTyres), abstractEvent: this, priority: 10));
                                    break;
                                case TyreType.Option:
                                    audioPlayer.playMessage(new QueuedMessage("box_now_for_options", 9, secondsDelay: 3,
                                        messageFragments: MessageContents(folderMandatoryPitStopsPitNow, folderMandatoryPitStopsOptionTyres), abstractEvent: this, priority: 10));
                                    break;
                                default:
                                    audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitNow, 9, secondsDelay: 3, abstractEvent: this, priority: 10));
                                    break;
                            }
                        }
                    }
                }
            }
            if (previousGameState != null)
            {
                if (currentGameState.SessionData.SessionType == SessionType.Race
                    || currentGameState.SessionData.SessionType == SessionType.Qualify
                    || currentGameState.SessionData.SessionType == SessionType.PrivateQualify
                    || currentGameState.SessionData.SessionType == SessionType.Practice
                    || currentGameState.SessionData.SessionType == SessionType.LonePractice)
                {
                    if ((!previousGameState.PitData.IsApproachingPitlane
                        && currentGameState.PitData.IsApproachingPitlane && !Game.IRACING)
                        // Here we need to make sure that the player has intended to go into the pit's sometimes this trows if we are getting in this zone while overtaking or just defending the line.
                        || (currentGameState.PitData.IsApproachingPitlane && Game.IRACING
                            && currentGameState.Now > timeStartedAppoachingPitsCheck
                            // looking for no braking only avoids problems with fast last corners
                            && currentGameState.ControlData.BrakePedal <= 0
                            // short ovals (especially dirt) are the worst offenders, we never want to fire on approach
                            && currentGameState.SessionData.TrackDefinition.trackLengthClass > TrackData.TrackLengthClass.SHORT))
                    {
                        timeStartedAppoachingPitsCheck = DateTime.MaxValue;
                        timeSpeedInPitsWarning = currentGameState.Now;

                        if (currentGameState.PitData.PitSpeedLimit == -1.0f
                            || pitLaneSpeedWarningAnnounced)  // Announce pitlane speed limit automatically only once per session
                        {
                            if (currentGameState.PitData.PitSpeedLimit == -1.0f  // Only announce "watch your speed" message if we have no pit speed data.
                                || currentGameState.PitData.pitlaneHasSpeedLimit())  // Or, if we know for sure there's a speed limit.
                                audioPlayer.playMessageImmediately(new QueuedMessage(folderWatchYourPitSpeed, 2, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                        }
                        else
                        {
                            announcePitlaneSpeedLimit(currentGameState, true /*possiblyPlayIntro*/, false /*voiceResponse*/);
                            pitLaneSpeedWarningAnnounced = true;
                        }
                    }
                    if (!previousGameState.PitData.IsApproachingPitlane
                        && currentGameState.PitData.IsApproachingPitlane && timeStartedAppoachingPitsCheck == DateTime.MaxValue)
                    {
                        timeStartedAppoachingPitsCheck = currentGameState.Now + TimeSpan.FromSeconds(2);
                    }
                    // different logic for PCars2 pit-crew-ready checks
                    if (Game.PCARS2 ||
                        Game.PCARS2_NETWORK ||
                        Game.AMS2)
                    {
                        int delay = Utilities.random.Next(1, 3);
                        if (!previousGameState.PitData.PitStallOccupied && currentGameState.PitData.PitStallOccupied)
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderPitStallOccupied, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                            warnedAboutOccupiedPitOnThisLap = true;
                        }
                        if (currentGameState.SessionData.SectorNumber == 3 &&
                            previousGameState.SessionData.SectorNumber == 2 &&
                            currentGameState.PitData.HasRequestedPitStop)
                        {
                            if (currentGameState.PitData.PitStallOccupied)
                            {
                                if (!warnedAboutOccupiedPitOnThisLap)
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderPitStallOccupied, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                    warnedAboutOccupiedPitOnThisLap = true;
                                }
                            }
                            else
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderPitCrewReady, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                            }
                        }
                    }
                    else if (!previousGameState.PitData.IsPitCrewReady
                        && currentGameState.PitData.IsPitCrewReady)
                    {
                        int delay = Utilities.random.Next(1, 3);
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderPitCrewReady, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                    }
                    if (currentGameState.PitData.IsMakingMandatoryPitStop && currentGameState.PositionAndMotionData.CarSpeed < 1
                        && currentGameState.PitData.MandatoryPitMinDurationLeft > 0 && !playedMandatoryStopMinWaitTime && currentGameState.SessionData.SessionType == SessionType.Race)
                    {
                        // work out how long we need to remain stationary in order to fulfil the mandatory stop limit
                        if (includeExitTimeInStopDuration
                            && currentGameState.PitData.MandatoryPitMinDurationLeft > 0
                            && currentGameState.PitData.PitSpeedLimit > 0)
                        {
                            // estimate how long it'll take us to reach the end of the pit lane using our pit exit distance estimate
                            float distanceToEndOfPitlane = getDistanceToEndOfPitlane(currentGameState.SessionData.TrackDefinition.name, currentGameState.SessionData.TrackDefinition.trackLength,
                                currentGameState.PositionAndMotionData.DistanceRoundTrack, currentGameState.PositionAndMotionData.WorldPosition);
                            timeFromBoxToEndOfPitLane = (distanceToEndOfPitlane / currentGameState.PitData.PitSpeedLimit) + 1;  // TODO: allowing 1 second additional time for acceleration to pit speed limit - risky
                            mandatoryPitTimeToWait = currentGameState.PitData.MandatoryPitMinDurationLeft - timeFromBoxToEndOfPitLane;
                            Console.WriteLine("it'll take " + timeFromBoxToEndOfPitLane + " seconds to leave the pitlane, so we have to wait here another " + mandatoryPitTimeToWait + " seconds");
                        }
                        else if (!includeExitTimeInStopDuration)
                        {
                            mandatoryPitTimeToWait = currentGameState.PitData.MandatoryPitMinDurationLeft;
                        }
                        Console.WriteLine("total stop time has to be at least " + currentGameState.PitData.MandatoryPitMinDurationTotal +
                            ", we have " + mandatoryPitTimeToWait + " remaining stationary");
                        playedMandatoryStopMinWaitTime = true;
                        audioPlayer.playMessageImmediately(new QueuedMessage("mandatory_stop_minimum_time", 0,  messageFragments: MessageContents(folderMandatoryPitstopMinimumTimeIntro,
                            new TimeSpanWrapper(TimeSpan.FromSeconds(mandatoryPitTimeToWait), Precision.SECONDS)), abstractEvent: this));
                    }
                    if (currentGameState.SessionData.SessionPhase == SessionPhase.Green && !previousGameState.PitData.IsPitCrewDone
                        && currentGameState.PitData.IsPitCrewDone)
                    {
                        mandatoryPitTimeToWait = currentGameState.PitData.MandatoryPitMinDurationLeft - timeFromBoxToEndOfPitLane;
                        Console.WriteLine("Crew is done, stop time remaining is " + mandatoryPitTimeToWait);

                        // we might have to keep waiting here if the mandatory stop timer hasn't reached zero
                        // If we have 6 seconds or more to wait make a proper call
                        if (mandatoryPitTimeToWait >= 6)
                        {
                            waitingForMandatoryStopTimer = true;
                            // note that the timeleft - 1 here is because it takes about 1 seconds to say this longer intro
                            audioPlayer.playMessageImmediately(new QueuedMessage("mandatory_stop_wait", 0, messageFragments: MessageContents(folderWaitForMandatoryStopTimerIntro,
                                new TimeSpanWrapper(TimeSpan.FromSeconds(mandatoryPitTimeToWait - 1), Precision.SECONDS)),
                                abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                            nextWaitWarningDue = currentGameState.Now.AddSeconds(5);
                            playedWait5Seconds = currentGameState.PitData.MandatoryPitMinDurationLeft <= 7; // don't allow the 5 second warning if we're already close to it
                        }
                        else if (mandatoryPitTimeToWait > 0)
                        {
                            waitingForMandatoryStopTimer = true;
                            audioPlayer.playMessageImmediately(new QueuedMessage("mandatory_stop_wait", 0, messageFragments: MessageContents(folderWaitForMandatoryWait,
                                new TimeSpanWrapper(TimeSpan.FromSeconds(mandatoryPitTimeToWait), Precision.SECONDS)),
                                abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                            nextWaitWarningDue = currentGameState.Now.AddSeconds(5);
                            playedWait5Seconds = true;
                        }
                        else
                        {
                            waitingForMandatoryStopTimer = false;
                            if (!GameWorkArounds.LMU_PitstopGoGoGo)  // LMU triggers this as soon as car stops.
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage(folderStopCompleteGo, 1, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                            }
                        }
                    }
                    if (currentGameState.SessionData.SessionPhase == SessionPhase.Green && currentGameState.PitData.IsPitCrewDone && waitingForMandatoryStopTimer)
                    {
                        // we've made the first "wait 12 seconds" call, so we're now on to the "wait... wait... 5 seconds ... wait... GO" phase
                        float waitTimeRemaining = currentGameState.PitData.MandatoryPitMinDurationLeft - timeFromBoxToEndOfPitLane;
                        if (waitTimeRemaining <= 0)
                        {
                            if (currentGameState.PositionAndMotionData.CarSpeed < 1)
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage(folderStopCompleteGo, 1, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                            }
                            waitingForMandatoryStopTimer = false;
                            nextWaitWarningDue = DateTime.MaxValue;
                        }
                        else if (!playedWait5Seconds && waitTimeRemaining <= 5.2 && waitTimeRemaining > 4.8)
                        {
                            if (currentGameState.PositionAndMotionData.CarSpeed < 1)
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage(folderWaitForMandatoryWait5Seconds, 1, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                            }
                            nextWaitWarningDue = currentGameState.Now.AddSeconds(3);
                            playedWait5Seconds = true;
                        }
                        else if (currentGameState.Now > nextWaitWarningDue)
                        {
                            if (waitTimeRemaining < 3)
                            {
                                nextWaitWarningDue = DateTime.MaxValue;
                            }
                            else
                            {
                                if (currentGameState.PositionAndMotionData.CarSpeed < 1)
                                {
                                    Console.WriteLine("waiting - remaining from game is " + currentGameState.PitData.MandatoryPitMinDurationLeft + " with exit time is  " + waitTimeRemaining);
                                    audioPlayer.playMessageImmediately(new QueuedMessage(folderWaitForMandatoryWait, 1, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                                }
                                nextWaitWarningDue = currentGameState.Now.AddSeconds(4);
                            }
                        }
                    }
                    else if (currentGameState.SessionData.SessionPhase == SessionPhase.Green &&
                        waitingForMandatoryStopTimer && previousGameState.PitData.MandatoryPitMinDurationLeft > 0 && currentGameState.PitData.MandatoryPitMinDurationLeft == -1)
                    {
                        // in R3E if we're waiting for the stop timer and the time remaining goes from >0 to -1 it means we've exited too soon
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderLeftPitTooSoon, 0, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                        Console.WriteLine("Exited pit before stop timer reached zero - left " + previousGameState.PitData.MandatoryPitMinDurationLeft + " seconds early");
                        waitingForMandatoryStopTimer = false;
                    }

                    if (!previousGameState.PitData.HasRequestedPitStop
                        && currentGameState.PitData.HasRequestedPitStop
                        && !playedRequestPitOnThisLap
                        && (currentGameState.Now - timeOfPitRequestOrCancel).TotalSeconds > minSecondsBetweenPitRequestCancel)
                    {
                        timeOfPitRequestOrCancel = currentGameState.Now;
                        playedRequestPitOnThisLap = true;

                        isPittingThisLap = true;
                        // respond immediately to this request
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderPitStopRequestReceived, 0));
                    }
                    // don't play pit request cancelled in pCars2 because the request often cancels itself for no reason at all (other than pcars2 being a mess)
                    // - the pit crew may or may not be ready for you when this happens. It's just one of the many mysteries of pCars2.
                    if ((!Game.PCARS2 &&
                         !Game.PCARS2_NETWORK &&
                         !Game.AMS2)
                        && !currentGameState.PitData.InPitlane && !previousGameState.PitData.InPitlane  // Make sure we're not in pits.  More checks might be needed.
                        && !playedPitRequestCancelledOnThisLap
                        && previousGameState.PitData.HasRequestedPitStop
                        && !currentGameState.PitData.HasRequestedPitStop
                        && (currentGameState.Now - timeOfPitRequestOrCancel).TotalSeconds > minSecondsBetweenPitRequestCancel)
                    {
                        timeOfPitRequestOrCancel = currentGameState.Now;
                        playedPitRequestCancelledOnThisLap = true;
                        int delay = Utilities.random.Next(1, 3);
                        audioPlayer.playMessage(new QueuedMessage(folderPitStopRequestCancelled, delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));

                        isPittingThisLap = false;
                    }
                }
                else if ((Game.PCARS2 ||
                          Game.PCARS2_NETWORK ||
                          Game.AMS2) &&
                        !playedRequestPitOnThisLap &&
                        !previousGameState.PitData.HasRequestedPitStop && currentGameState.PitData.HasRequestedPitStop &&
                         (currentGameState.Now - timeOfPitRequestOrCancel).TotalSeconds > minSecondsBetweenPitRequestCancel)
                {
                    timeOfPitRequestOrCancel = currentGameState.Now;
                    playedRequestPitOnThisLap = true;

                    isPittingThisLap = true;
                    // respond immediately to this request
                    audioPlayer.playMessageImmediately(new QueuedMessage(folderPitStopRequestReceived, 2, abstractEvent: this));
                }
            }

            if (Game.RF2_LMU ||
                Game.GTR2 ||
                Game.RACE_ROOM ||
                Game.IRACING)
            {
                if (!pitLaneSpeedWarningAnnounced
                    && (currentGameState.SessionData.SessionType == SessionType.LonePractice 
                        || currentGameState.SessionData.SessionType == SessionType.Practice 
                        || currentGameState.SessionData.SessionType == SessionType.Qualify
                        || currentGameState.SessionData.SessionType == SessionType.PrivateQualify)
                    && currentGameState.PitData.InPitlane
                    && currentGameState.PositionAndMotionData.CarSpeed > 0.5f
                    && !DriverTrainingService.isPlayingPaceNotes
                    && !DriverTrainingService.isRecordingPaceNotes)
                {
                    pitLaneSpeedWarningAnnounced = true;
                    if (currentGameState.PitData.PitSpeedLimit != -1.0f
                        && (this.trackNameInitialPitSpeedLimitAnnounced != currentGameState.SessionData.TrackDefinition.name
                            || this.lastInitialPitspeedLimitAnnounced != currentGameState.PitData.PitSpeedLimit))  // Don't re-announce initial pit lane speed info unless track or limit actually changed.
                    {
                        this.trackNameInitialPitSpeedLimitAnnounced = currentGameState.SessionData.TrackDefinition.name;
                        this.lastInitialPitspeedLimitAnnounced = currentGameState.PitData.PitSpeedLimit;
                        announcePitlaneSpeedLimit(currentGameState, false /*possiblyPlayIntro*/, false /*voiceResponse*/);
                    }
                }

                if (previousGameState != null
                    && currentGameState.SessionData.SessionType == SessionType.Race
                    && currentGameState.PitData.HasRequestedPitStop)
                {
                    if (!previousGameState.PitData.PitStallOccupied && currentGameState.PitData.PitStallOccupied)
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderPitStallOccupied, 0));
                    else if (previousGameState.PitData.PitStallOccupied && !currentGameState.PitData.PitStallOccupied)
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderPitStallAvailable, 0));
                }
            }
        }

        private float getDistanceToEndOfPitlane(string trackName, float trackLength, float currentLapDistance, float[] currentWorldPosition)
        {
            float[] recordedPitExitData;
            if (pitExitPoints.TryGetValue(trackName, out recordedPitExitData))
            {
                // we have recorded a position and lap distance for the pit exit point so use it
                // we want recordedPitExitData[0] (x pos) and currentWorldPosition[0] (x-pos) and recordedPitExitData[1] (z pos) and currentWorldPosition[2] (z-pos),
                return (float)Math.Sqrt(
                    Math.Pow((double)recordedPitExitData[0] - currentWorldPosition[0], 2) +
                    Math.Pow((double)recordedPitExitData[1] - currentWorldPosition[2], 2));
            }
            else
            {
                // we don't know where the pit exit is so make a risky assumption that it's 30 metres from the start line or
                // 30 metres past the box position and just use that
                float guessedPitExitLapDistance;
                float minPitExitPositionEstimate = 30;
                if (currentLapDistance + 500 > trackLength)
                {
                    // our box is before the start line so assume exit is at 30 metres
                    guessedPitExitLapDistance = minPitExitPositionEstimate;
                }
                else
                {
                    // our box is after the start line to assume exit is at box position + 30 metres
                    guessedPitExitLapDistance = currentLapDistance + minPitExitPositionEstimate;
                }
                Console.WriteLine("No data for " + trackName + " pit exit position, assuming it's " + guessedPitExitLapDistance + " metres past the start line");
                if (guessedPitExitLapDistance > currentLapDistance)
                {
                    return guessedPitExitLapDistance - currentLapDistance;
                }
                else
                {
                    return guessedPitExitLapDistance + (trackLength - currentLapDistance);
                }
            }
        }

        private void announceR3EPitActions(Boolean inPitLane, Boolean fromVoiceRequest)
        {
            if (fromVoiceRequest)
            {
                // block the automatic announcement for a while
                if (CrewChief.currentGameState != null && CrewChief.currentGameState.Now != null)
                    R3EPitMenuManager.timeWeCanAnnouncePitActions = CrewChief.currentGameState.Now.AddSeconds(10);
            }
            else
            {
                // this is an automated announcement so block further announcements of this set of actions until pit-in is requested again
                R3EPitMenuManager.outstandingPitstopRequest = false;
            }
            if (!R3EPitMenuManager.hasStateForCurrentSession)
            {
                // if the menu isn't open, pop it for a moment to get a snapshot of its state. This is an edge case - either we'll be invoking
                // this from the SRE (we asked "what's the pit stop plan" before we requested a pitstop) or something has gone rather wrong
                R3EPitMenuManager.openPitMenuIfClosed();
                Thread.Sleep(100);
                if (!inPitLane)
                {
                    R3EPitMenuManager.closePitMenuIfOpen(0);
                }
            }
            Boolean doneFuel = false;
            Boolean doneTyres = false;
            Boolean haveData = false;
            if (R3EPitMenuManager.latestState[SelectedItem.Fronttires] == PitSelectionState.SELECTED
                && R3EPitMenuManager.latestState[SelectedItem.Reartires] == PitSelectionState.SELECTED)
            {
                // "we're changing all 4 tyres"
                doneFuel = true;
                doneTyres = true;
                haveData = true;
                switch (R3EPitMenuManager.latestState[SelectedItem.Fuel])
                {
                    case PitSelectionState.SELECTED:
                        audioPlayer.playMessage(new QueuedMessage(folderWillChangeAllFourTyresAndRefuel, 0));
                        break;
                    case PitSelectionState.AVAILABLE:
                        audioPlayer.playMessage(new QueuedMessage(folderWillChangeAllFourTyresNoFuel, 0));
                        break;
                    default:
                        audioPlayer.playMessage(new QueuedMessage(folderWillChangeAllFourTyres, 0));
                        break;
                }
            }
            else if (R3EPitMenuManager.latestState[SelectedItem.Fronttires] == PitSelectionState.AVAILABLE
                && R3EPitMenuManager.latestState[SelectedItem.Reartires] == PitSelectionState.AVAILABLE)
            {
                // "no tyres this time"
                doneFuel = true;
                doneTyres = true;
                haveData = true;
                switch (R3EPitMenuManager.latestState[SelectedItem.Fuel])
                {
                    case PitSelectionState.SELECTED:
                        audioPlayer.playMessage(new QueuedMessage(folderWillPutFuelInNoTyresThisTime, 0));
                        break;
                    case PitSelectionState.AVAILABLE:
                        audioPlayer.playMessage(new QueuedMessage(folderNoTyresOrFuelThisTime, 0));
                        break;
                    default:
                        audioPlayer.playMessage(new QueuedMessage(folderNoTyresThisTime, 0));
                        break;
                }
            }
            if (!doneTyres)
            {
                if (R3EPitMenuManager.latestState[SelectedItem.Fronttires] == PitSelectionState.SELECTED && R3EPitMenuManager.latestState[SelectedItem.Reartires] == PitSelectionState.AVAILABLE)
                {
                    // "we're changing front tyres only"
                    audioPlayer.playMessage(new QueuedMessage(folderWillChangeFrontTyresOnly, 0));
                    haveData = true;
                }
                else if (R3EPitMenuManager.latestState[SelectedItem.Fronttires] == PitSelectionState.AVAILABLE && R3EPitMenuManager.latestState[SelectedItem.Reartires] == PitSelectionState.SELECTED)
                {
                    // "we're changing rear tyres only"
                    audioPlayer.playMessage(new QueuedMessage(folderWillChangeRearTyresOnly, 0));
                    haveData = true;
                }
                else if (R3EPitMenuManager.latestState[SelectedItem.Fronttires] == PitSelectionState.AVAILABLE && R3EPitMenuManager.latestState[SelectedItem.Reartires] == PitSelectionState.AVAILABLE)
                {
                    // "we're not changing tyres"
                    audioPlayer.playMessage(new QueuedMessage(folderNoTyresThisTime, 0));
                    haveData = true;
                }
            }
            if (!doneFuel)
            {
                switch (R3EPitMenuManager.latestState[SelectedItem.Fuel])
                {
                    case PitSelectionState.SELECTED:
                        // "we're putting fuel in"
                        audioPlayer.playMessage(new QueuedMessage(folderWillPutFuelIn, 0));
                        haveData = true;
                        break;
                    case PitSelectionState.AVAILABLE:
                        // "no fuel this time"
                        audioPlayer.playMessage(new QueuedMessage(folderNoFuelThisTime, 0));
                        haveData = true;
                        break;
                }
            }
            if (R3EPitMenuManager.latestState[SelectedItem.Frontwing] == PitSelectionState.SELECTED)
            {
                haveData = true;
                switch (R3EPitMenuManager.latestState[SelectedItem.Rearwing])
                {
                    case PitSelectionState.SELECTED:
                        // "we'll fix the front and rear aero"
                        audioPlayer.playMessage(new QueuedMessage(folderWillFixFrontAndRearAero, 0));
                        break;
                    case PitSelectionState.AVAILABLE:
                        // "we'll fix the front aero and leave the rear"
                        audioPlayer.playMessage(new QueuedMessage(folderWillFixFrontAndLeaveRearAero, 0));
                        break;
                    default:
                        // "we'll fix the front aero"
                        audioPlayer.playMessage(new QueuedMessage(folderWillFixFrontAero, 0));
                        break;
                }
            }
            else if (R3EPitMenuManager.latestState[SelectedItem.Rearwing] == PitSelectionState.SELECTED)
            {
                haveData = true;
                if (R3EPitMenuManager.latestState[SelectedItem.Frontwing] == PitSelectionState.AVAILABLE)
                {
                    // "we'll fix the rear and leave the front"
                    audioPlayer.playMessage(new QueuedMessage(folderWillFixRearAndLeaveFrontAero, 0));
                }
                else
                {
                    // "we'll fix the rear aero"
                    audioPlayer.playMessage(new QueuedMessage(folderWillFixRearAero, 0));
                }
            }
            switch (R3EPitMenuManager.latestState[SelectedItem.Suspension])
            {
                case PitSelectionState.SELECTED:
                    // "we'll fix the suspension"
                    audioPlayer.playMessage(new QueuedMessage(folderWillFixSuspension, 0));
                    haveData = true;
                    break;
                case PitSelectionState.AVAILABLE:
                    // "we'll leave the suspension"
                    audioPlayer.playMessage(new QueuedMessage(folderWillLeaveSuspension, 0));
                    haveData = true;
                    break;
            }
            if (R3EPitMenuManager.latestState[SelectedItem.Penalty] == PitSelectionState.SELECTED)
            {
                // "we'll be serving the penalty"
                audioPlayer.playMessage(new QueuedMessage(folderWillBeServingPenalty, 0));
                haveData = true;
            }
            if (fromVoiceRequest && !haveData)
            {
                audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
            }
            else
            {
                // announced automatically and we have data. If we're not in the pitlane sometimes play a 'box now'
                if (!inPitLane && !playBoxNowMessage && Utilities.random.Next(10) >= 5)
                {
                    audioPlayer.playMessage(new QueuedMessage(folderMandatoryPitStopsPitNow, 0));
                }
            }
        }

        private void announcePitlaneSpeedLimit(GameStateData currentGameState, bool possiblyPlayIntro, bool voiceResponse)
        {
            if (GlobalBehaviourSettings.playPitSpeedLimitWarnings)
            {
                if (currentGameState.PitData.pitlaneHasSpeedLimit())
                {
                    if (possiblyPlayIntro && Utilities.random.NextDouble() < 0.66)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderWatchYourPitSpeed, 2, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                    }

                    var kmPerHour = currentGameState.PitData.PitSpeedLimit * 3.6f;
                    var messageFragments = new List<MessageFragment>();

                    if (!voiceResponse)
                    {
                        messageFragments.Add(MessageFragment.Text(folderPitSpeedLimit));
                    }

                    if (!GlobalBehaviourSettings.useMetric)
                    {
                        var milesPerHour = kmPerHour * 0.621371f;
                        messageFragments.Add(MessageFragment.Integer((int)Math.Round(milesPerHour), false));
                        messageFragments.Add(MessageFragment.Text(FrozenOrderMonitor.folderMilesPerHour));
                    }
                    else
                    {
                        messageFragments.Add(MessageFragment.Integer((int)Math.Round(kmPerHour), false));
                        messageFragments.Add(MessageFragment.Text(FrozenOrderMonitor.folderKilometresPerHour));
                    }

                    audioPlayer.playMessageImmediately(new QueuedMessage(folderPitSpeedLimit, 4, messageFragments: messageFragments, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                }
                else
                {
                    audioPlayer.playMessageImmediately(new QueuedMessage(folderNoPitSpeedLimit, 2, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                }
            }
        }

        private static readonly List<SpeechCommands.ID> Commands = new List<SpeechCommands.ID>
        {
            SpeechCommands.ID.DO_I_HAVE_A_MANDATORY_PIT_STOP,
            SpeechCommands.ID.HOW_MANY_LAPS_SINCE_PITTING,
            SpeechCommands.ID.IS_MY_PIT_BOX_OCCUPIED,
            SpeechCommands.ID.SESSION_STATUS,
            SpeechCommands.ID.STATUS,
            SpeechCommands.ID.WHATS_PITLANE_SPEED_LIMIT,
            SpeechCommands.ID.WHAT_ARE_THE_PIT_ACTIONS,
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
                case SpeechCommands.ID.WHAT_ARE_THE_PIT_ACTIONS:
                {
                    if (!Game.RACE_ROOM || CrewChief.currentGameState == null)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                    }
                    else
                    {
                        announceR3EPitActions(CrewChief.currentGameState.PitData.InPitlane, true);
                    }

                    break;
                }
                case SpeechCommands.ID.IS_MY_PIT_BOX_OCCUPIED:
                {
                    if (this.pitStallOccupied || Strategy.pitStallIsBlocked)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderPitStallOccupied, 0));
                    }
                    else
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNo, 0));
                    }

                    break;
                }
                case SpeechCommands.ID.SESSION_STATUS:
                case SpeechCommands.ID.STATUS:
                {
                    if (enableWindowWarnings && pitDataInitialised)
                    {
                        if (mandatoryStopMissed)
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage(folderMandatoryPitStopsMissedStop, 0));
                        }
                        else if (hasMandatoryPitStop && !mandatoryStopCompleted)
                        {
                            if (!inPitWindow)
                            {
                                if (pitWindowOpenLap > 0)
                                {
                                    audioPlayer.playMessageImmediately(new QueuedMessage("pit_window_open_lap", 0,
                                        messageFragments: MessageContents(folderMandatoryPitStopsPitWindowOpensOnLap, pitWindowOpenLap)));
                                }
                                else if (pitWindowOpenTime > 0)
                                {
                                    audioPlayer.playMessageImmediately(new QueuedMessage("pit_window_open_time", 0,
                                        messageFragments: MessageContents(folderMandatoryPitStopsPitWindowOpensAfter, TimeSpanWrapper.FromMinutes(pitWindowOpenTime, Precision.MINUTES))));
                                }
                            }
                            else
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage("pit_window_open", 0,
                                    messageFragments: MessageContents(folderMandatoryPitStopsPitWindowOpen, pitWindowOpenLap)));
                            }
                        }
                    }

                    break;
                }
                case SpeechCommands.ID.WHATS_PITLANE_SPEED_LIMIT:
                {
                    var currentGameState = CrewChief.currentGameState;
                    if (currentGameState == null || currentGameState.PitData.PitSpeedLimit == -1.0f)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                    }
                    else
                    {
                        announcePitlaneSpeedLimit(currentGameState, false /*possiblyPlayIntro*/, true /*voiceResponse*/);
                        pitLaneSpeedWarningAnnounced = true;
                    }

                    break;
                }
                case SpeechCommands.ID.HOW_MANY_LAPS_SINCE_PITTING:
                {
                    var currentGameState = CrewChief.currentGameState;
                    var messages = new List<MessageFragment>();

                    int lap_diff = currentGameState.SessionData.LapCount - pitEntryLap - 1;
                    if (lap_diff > 0)
                    {
                        messages.AddRange(MessageContents(lap_diff, Battery.folderLaps));
                    }

                    // if we haven't pitted yet, the player probably wants to know how long they've gone
                    // since they got fresh tires, so report since the race start instead of the pit.
                    var entryTime = pitEntryTime;
                    if (entryTime < currentGameState.SessionData.SessionStartTime)
                    {
                        entryTime = currentGameState.SessionData.SessionStartTime;
                    }
                
                    int time_diff = (int)(currentGameState.Now - entryTime).TotalMinutes;
                    if (time_diff > 0 && time_diff < 120)
                    {
                        messages.AddRange(MessageContents(time_diff, Battery.folderMinutes));
                    }

                    if (messages.Count > 0)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage("pitstops_time_since_pitting", 0, messageFragments: messages));
                    }

                    break;
                }
                case SpeechCommands.ID.DO_I_HAVE_A_MANDATORY_PIT_STOP:
                {
                    // for ACC use the data in the game state directly here because they'll be correct even on the formation lap
                    bool hasStop = Game.ACC ? CrewChief.currentGameState.PitData.HasMandatoryPitStop : hasMandatoryPitStop;
                    bool stopCompleted = Game.ACC ? CrewChief.currentGameState.PitData.MandatoryPitStopCompleted : mandatoryStopCompleted;
                    float windowOpenTime = Game.ACC ? CrewChief.currentGameState.PitData.PitWindowStart : pitWindowOpenTime;
                    if (!hasStop || stopCompleted || !enableWindowWarnings)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNo, 0));
                    }
                    else if (mandatoryStopMissed)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderMandatoryPitStopsMissedStop, 0));
                    }
                    else if (mandatoryStopBoxThisLap)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage("yesBoxThisLap", 0,
                            messageFragments: MessageContents(AudioPlayer.folderYes, folderMandatoryPitStopsPitThisLap)));
                    }
                    else if (pitWindowOpenLap > 0)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage("yesBoxOnLap", 0,
                            messageFragments: MessageContents(folderMandatoryPitStopsYesStopOnLap, pitWindowOpenLap)));
                    }
                    else if (windowOpenTime > 0)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage("yesBoxAfter", 0,
                            messageFragments: MessageContents(folderMandatoryPitStopsYesStopAfter, TimeSpanWrapper.FromMinutes(windowOpenTime, Precision.MINUTES))));
                    }
                    else if (hasStop && !stopCompleted)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderYes, 0));
                    }
                    else
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                    }

                    break;
                }
                default:
                    break;
            }
        }
    }
}
