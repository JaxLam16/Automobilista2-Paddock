using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using CrewChiefV4.GameState;
using CrewChiefV4.Audio;
using CrewChiefV4.NumberProcessing;
using System.Security.Policy;
using System.Diagnostics.Eventing.Reader;

namespace CrewChiefV4.Events
{
    class LapCounter : AbstractEvent
    {
        public static String folderGreenGreenGreen = "lap_counter/green_green_green";

        // used in manual rolling starts (hack...)
        public static String folderLeaderHasCrossedStartLine = "lap_counter/leader_has_crossed_start_line";
        // used in manual rolling starts - if we pass someone play a message. We don't know if we've passed someone because of
        // a disconnection or because we've actually overtaken, so err on the side of caution here
        public static String folderHoldYourPosition = "lap_counter/hold_your_position";
        public static String folderGivePositionBack = "lap_counter/give_that_position_back";
        public static String folderManualStartInitialIntro = "lap_counter/ok_youre_in";
        public static String folderManualStartInitialOutroNoDriverName = "lap_counter/hold_this_position_until_start_line";
        public static String folderManualStartInitialOutroWithDriverName1 = "lap_counter/hold_position_behind";
        public static String folderManualStartInitialOutroWithDriverName2 = "lap_counter/until_start_line";
        public static String folderManualStartRejoinAtBack = "lap_counter/rejoin_at_back";
        public static String folderManualStartFormUpBehind = "lap_counter/form_up_behind";
        public static String folderManualStartStartingOnLeftBehind = "lap_counter/starting_in_left_lane_behind";
        public static String folderManualStartStartingOnRightBehind = "lap_counter/starting_in_right_lane_behind";
        public static String folderManualStartLeaderHasGone = "lap_counter/leader_has_gone";
        public static String folderTookTheWin = "lap_counter/has_taken_the_win";

        // toggle / request acknowledgements when enabling / disabling manual formation lap mode
        public static String folderManualFormationLapModeEnabled = "lap_counter/manual_formation_lap_mode_enabled";
        public static String folderManualFormationLapModeDisabled = "lap_counter/manual_formation_lap_mode_disabled";

        public static String folderStrengthOfField = "lap_counter/strength_of_field_is";
        public static String folderStrengthOfFieldOurClass = "lap_counter/strength_of_field_for_our_class_is";

        public static String folderNoPitstopEstimatesFuel = "mandatory_pit_stops/no_pit_timings_unreliable_fuel_estimates";
        public static String folderNoPitstopEstimatesPosition = "mandatory_pit_stops/no_pit_timings_unreliable_position_estimates";

        public static String folderRaceStartsIn = "lap_counter/race_starts_in";

        // some folks might want to start racing when the leader crosses the line, others might not be allowed to overtake
        // until their car crosses the line
        private readonly Boolean manualFormationGoWhenLeaderCrossesLine = UserSettings.GetUserSettings().getBoolean("manual_formation_go_with_leader");
        private readonly Boolean manualFormationDoubleFile = UserSettings.GetUserSettings().getBoolean("manual_formation_double_file");
        private readonly Boolean manualFormationSplitClasses = UserSettings.GetUserSettings().getBoolean("manual_formation_split_classes");

        private Boolean playedManualStartGetReady = false;
        private Boolean playedManualStartLeaderHasCrossedLine = false;
        private Boolean playedManualStartPlayedGoGoGo = false;
        private Boolean playedManualStartInitialMessage = false;

        private float distanceBeforeLineToStartLeaderAccelerationCheck = 200f;
        private float leaderSpeedAtAccelerationCheckStart = -1;
        private OpponentData poleSitter = null;
        private Boolean leaderHasGone = false;
        private Boolean leaderHasFinished = false;

        private String manualStartOpponentToFollow = null;

        // used by the FrozenOrder event
        public static String folderGetReady = "lap_counter/get_ready";

        private String folderLastLapEU = "lap_counter/last_lap";

        private String folderLastLapUS = "lap_counter/white_flag_last_lap";

        private String folderTwoLeft = "lap_counter/two_to_go";

        private String folderLastLapLeading = "lap_counter/last_lap_leading";

        private String folderLastLapTopThree = "lap_counter/last_lap_top_three";

        private String folderTwoLeftLeading = "lap_counter/two_to_go_leading";

        private String folderTwoLeftTopThree = "lap_counter/two_to_go_top_three";

        private String folderLapsMakeThemCount = "lap_counter/laps_make_them_count";
        private String folderMinutesYouNeedToGetOnWithIt = "lap_counter/minutes_you_need_to_get_on_with_it";
        
        private Boolean playedGetReady;

        public static Boolean playedPreLightsMessage;

        private Boolean purgePreLightsMessages;

        private DateTime lastFinishMessageTime = DateTime.MinValue;

        private readonly Boolean playPreRaceMessagesUntilCancelled = UserSettings.GetUserSettings().getBoolean("play_pre_lights_messages_until_cancelled");

        private readonly Boolean enableGreenLightMessages = UserSettings.GetUserSettings().getBoolean("enable_green_light_messages");

        private Boolean enableRf2AutoClearTyreChange;

        private DateTime nextManualFormationOvertakeWarning = DateTime.MinValue;
        
        // special case for LapCounter - needs access to the CrewChief class to interrogate the spotter
        private CrewChief crewChief;

        private GridSide gridSide = GridSide.UNKNOWN;

        private Dictionary<String, GridSide> opponentsInFrontGridSides = new Dictionary<string, GridSide>();

        private int manualFormationStartingPosition = 0;

        private Boolean playedRejoinAtBackMessage = false;

        private Boolean playedPreLightsRollingStartWarning = false;

        public static bool whiteFlagLastLapAnnounced = false;

        public static bool preStartTempsAnnounced = false;

        private int lastReportedGridWalkTime = Int32.MaxValue;

        public override List<SessionPhase> applicableSessionPhases
        {
            get { return new List<SessionPhase> { SessionPhase.Countdown, SessionPhase.Formation, SessionPhase.Gridwalk, SessionPhase.Green, SessionPhase.Checkered, SessionPhase.Finished }; }
        }

        public override List<SessionType> applicableSessionTypes
        {
            get { return new List<SessionType> { SessionType.Practice, SessionType.Qualify, SessionType.PrivateQualify, SessionType.Race }; }
        }

        public LapCounter(AudioPlayer audioPlayer, CrewChief crewChief)
        {
            this.audioPlayer = audioPlayer;
            this.crewChief = crewChief;
            enableRf2AutoClearTyreChange = UserSettings.GetUserSettings().getBoolean("rf2_enable_auto_clear_tyre_change");
        }

        public override bool isMessageStillValid(string eventSubType, GameStateData currentGameState, Dictionary<String, Object> validationData)
        {
            // this validates that the 'give position back' message
            if (validationData != null) 
            { 
                if (validationData.ContainsKey("PreLights"))
                {
                    // these should have been caught by the purging but sometimes they slip through
                    return currentGameState.SessionData.SessionPhase < SessionPhase.Countdown;
                }

                OpponentData opponentWeOvertook = getOpponent(currentGameState, (String) validationData["OpponentToFollowName"]);
                if (opponentWeOvertook != null && currentGameState.SessionData.ClassPosition > opponentWeOvertook.ClassPosition
                    && !hasOpponentDroppedBack((int) validationData["PlayerPosition"], opponentWeOvertook))
                {
                    return false;
                }     
            }
            return true;
        }

        public override void clearState()
        {
            playedGetReady = false;
            playedPreLightsMessage = false;
            purgePreLightsMessages = false;
            // assume we start on the formation lap if we're using a manual formation lap
            GameStateData.onManualFormationLap = GameStateData.useManualFormationLap;
            playedManualStartGetReady = false;
            playedManualStartLeaderHasCrossedLine = false;
            playedManualStartInitialMessage = false;
            playedManualStartPlayedGoGoGo = false;
            nextManualFormationOvertakeWarning = DateTime.MinValue;
            manualStartOpponentToFollow = null;
            gridSide = GridSide.UNKNOWN;
            manualFormationStartingPosition = 0;
            playedRejoinAtBackMessage = false;
            playedPreLightsRollingStartWarning = false;
            opponentsInFrontGridSides = new Dictionary<string, GridSide>();
            leaderSpeedAtAccelerationCheckStart = -1;
            poleSitter = null;
            leaderHasGone = false;
            leaderHasFinished = false;
            LapCounter.whiteFlagLastLapAnnounced = false;
            LapCounter.preStartTempsAnnounced = false;
        }

        private OpponentData getOpponent(GameStateData currentGameState, String opponentName)
        {
            OpponentData opponent = null;
            if (opponentName != null && currentGameState.OpponentData.TryGetValue(opponentName, out opponent))
            {
                return opponent;
            }
            return null;
        }

        private void playPreLightsMessage(GameStateData currentGameState, int maxNumberToPlay)
        {
            int minutesInSession;
            int lapsInSession;
            if (Game.RACE_ROOM)
            {
                minutesInSession = currentGameState.SessionData.RaceSessionsLengthMinutes[currentGameState.SessionData.SessionIteration];
                // don't set laps in session if minutes is > 0
                lapsInSession = minutesInSession > 0 ? -1 : currentGameState.SessionData.RaceSessionsLengthLaps[currentGameState.SessionData.SessionIteration];
            }
            else
            {
                minutesInSession = (int) (currentGameState.SessionData.SessionTotalRunTime / 60);
                lapsInSession = currentGameState.SessionData.SessionNumberOfLaps;
            }
            playedPreLightsMessage = true;
           /* if ((Game.PCARS_NETWORK || Game.PCARS_64BIT || 
                Game.PCARS_32BIT) && currentGameState.SessionData.SessionNumberOfLaps <= 0 && 
                !playPreRaceMessagesUntilCancelled) 
            {
                // don't play pre-lights messages in PCars if the race is a fixed time, rather than number of laps
                return;
            }*/
            CrewChiefV4.GameState.Conditions.ConditionsSample currentConditions = currentGameState.Conditions.getMostRecentConditions();
            List<QueuedMessage> possibleMessages = new List<QueuedMessage>();
            if (currentConditions != null && currentConditions.TrackTemperature != 0 && currentConditions.AmbientTemperature != 0)
            {
                LapCounter.preStartTempsAnnounced = true;
                Console.WriteLine("Pre-start message for track and air temp");
                var possibleRainMessage = ((ConditionsMonitor)CrewChief.getEvent("ConditionsMonitor")).getRainForPreStartMessage(currentGameState);
                if(possibleRainMessage == null) 
                {
                    possibleMessages.Add(new QueuedMessage("trackAndAirTemp", 0, messageFragments: MessageContents(
                    ConditionsMonitor.folderTrackTempIs,
                        convertTemp(currentConditions.TrackTemperature),
                        getTempUnit(), // say the unit the first time, no need to repeat (it sounds clunky)
                        ConditionsMonitor.folderAirTempIs,
                        convertTemp(currentConditions.AmbientTemperature)),
                        abstractEvent: this, priority: 10));
                }
                else
                {
                    possibleMessages.Add(new QueuedMessage("trackAndAirTemp", 0, messageFragments: MessageContents(
                    ConditionsMonitor.folderTrackTempIs,
                        convertTemp(currentConditions.TrackTemperature),
                        ConditionsMonitor.folderAirTempIs,
                        convertTemp(currentConditions.AmbientTemperature),
                        getTempUnit(),
                        possibleRainMessage),
                        abstractEvent: this, priority: 10));
                }

            }
            if (currentGameState.PitData.HasMandatoryPitStop && currentGameState.PitData.PitWindowStart > 0 && !Game.RF1 && !Game.RF2_LMU && !Game.GTR2)
            {
                if (currentGameState.SessionData.SessionHasFixedTime)
                {
                    Console.WriteLine("Pre-start message for mandatory stop time");
                    possibleMessages.Add(new QueuedMessage("pit_window_time", 0, messageFragments: MessageContents(PitStops.folderMandatoryPitStopsPitWindowOpensAfter,
                        TimeSpanWrapper.FromMinutes(currentGameState.PitData.PitWindowStart, Precision.MINUTES)), abstractEvent: this, priority: 10));
                } 
                else
                {
                    Console.WriteLine("Pre-start message for mandatory stop lap");
                    possibleMessages.Add(new QueuedMessage("pit_window_lap", 0, messageFragments: MessageContents(PitStops.folderMandatoryPitStopsPitWindowOpensOnLap,
                        currentGameState.PitData.PitWindowStart), abstractEvent: this, priority: 10));
                }
            }
            // R3E position data is nonsense during countdown / gridwalk
            if (!Game.RACE_ROOM)
            {
                if (currentGameState.SessionData.ClassPosition == 1)
                {
                    Console.WriteLine("Pre-start message for pole");
                    if (SoundCache.availableSounds.Contains(Position.folderDriverPositionIntro))
                    {
                        possibleMessages.Add(new QueuedMessage("position", 0,
                            messageFragments: MessageContents(Position.folderDriverPositionIntro, Position.folderPole), abstractEvent: this, priority: 10));
                    }
                    else
                    {
                        possibleMessages.Add(new QueuedMessage("position", 0, messageFragments: MessageContents(Pause(200), Position.folderPole),
                            abstractEvent: this, priority: 10));
                    }
                }
                else if (currentGameState.SessionData.ClassPosition > 1)
                {
                    Console.WriteLine("Pre-start message for P " + currentGameState.SessionData.ClassPosition);
                    if (SoundCache.availableSounds.Contains(Position.folderDriverPositionIntro))
                    {
                        possibleMessages.Add(new QueuedMessage("position", 0, messageFragments: MessageContents(Position.folderDriverPositionIntro,
                            Position.folderStub + currentGameState.SessionData.ClassPosition), abstractEvent: this, priority: 10));
                    }
                    else
                    {
                        possibleMessages.Add(new QueuedMessage("position", 0,
                            messageFragments: MessageContents(Pause(200), Position.folderStub + currentGameState.SessionData.ClassPosition), abstractEvent: this, priority: 10));
                    }
                }
            }
            if (lapsInSession > 0) {
                // check how long the race is
                if (currentGameState.SessionData.ClassPosition > 3 && currentGameState.SessionData.TrackDefinition != null && 
                    currentGameState.SessionData.TrackDefinition.trackLength > 0 && 
                    currentGameState.SessionData.TrackDefinition.trackLength * lapsInSession < 30000)
                {
                    // anything less than 20000 metres worth of racing (e.g. 10 laps of Brands Indy) should have a 'make them count'
                    Console.WriteLine("Pre-start message for race laps + get on with it");
                    possibleMessages.Add(new QueuedMessage("race_distance", 0, 
                        messageFragments: MessageContents(lapsInSession, folderLapsMakeThemCount), abstractEvent: this, priority: 10));
                }
                else
                {
                    Console.WriteLine("Pre-start message for race laps");
                    // use the 'Laps' sound from Battery here
                    possibleMessages.Add(new QueuedMessage("race_distance", 0,
                        messageFragments: MessageContents(lapsInSession, Battery.folderLaps), abstractEvent: this, priority: 10));
                }
            }
            else if (!Game.RF1 && /* session time in gridwalk phase isn't usable in rf1 */
                minutesInSession > 0 && minutesInSession <= 100 &&
                !(Game.RF2_LMU && (currentGameState.FrozenOrderData.Phase == FrozenOrderPhase.Rolling || currentGameState.FrozenOrderData.Phase == FrozenOrderPhase.FastRolling)))   // No time available in rF2s rolling.
            {
                if (!Game.RACE_ROOM && currentGameState.SessionData.ClassPosition > 3 && minutesInSession < 20 && minutesInSession > 1)
                {
                    Console.WriteLine("Pre-start message for race time " + minutesInSession + " minutes + get on with it");
                    possibleMessages.Add(new QueuedMessage("race_time", 0,
                        messageFragments: MessageContents(minutesInSession, folderMinutesYouNeedToGetOnWithIt), abstractEvent: this, priority: 10));
                }
                //dont play pre-start message for race time unless its more then 2 minuts
                else
                {
                    Console.WriteLine("Pre-start message for race time:" + minutesInSession + " minutes");
                    possibleMessages.Add(new QueuedMessage("race_time", 0, messageFragments: MessageContents(minutesInSession, Battery.folderMinutes), abstractEvent: this, priority: 10));
                }
            }

            if (currentGameState.SessionData.StrengthOfField > 0)
            {
                int sof = currentGameState.SessionData.StrengthOfField;
                if (Game.IRACING)
                {
                    // round to nearest 100
                    sof = ((sof + 50) / 100) * 100;
                }
                if (Game.IRACING && GameStateData.Multiclass && GlobalBehaviourSettings.sofIsPlayerClass)
                {
                    // guarded to iRacing because it's the only one implementing this logic
                    possibleMessages.Add(new QueuedMessage("sof", 0, MessageContents(folderStrengthOfFieldOurClass, sof), abstractEvent: this, priority: 10));
                }
                else
                {
                    possibleMessages.Add(new QueuedMessage("sof", 0, MessageContents(folderStrengthOfField, sof), abstractEvent: this, priority: 10));
                }

                if (Game.IRACING)
                {
                    // this plays for other games at the end of the quali session, but it feels more natural here in iRacing
                    var prediction = CrewChief.currentGameState.SessionData.expectedFinishingPosition;
                    if (prediction != null && prediction.Item1 > 0 && prediction.Item2 > 0)
                    {
                        var message = Position.reportExpectedFinishPosition(null, prediction, false, false, currentGameState.SessionData.ClassPosition);
                        possibleMessages.Add(new QueuedMessage("finish_prediction", 0, messageFragments: message, abstractEvent: this, priority: 10));
                    }
                }
            }

            // assume that races longer than this many minutes or laps need a pitstop (fuel or tyres).
            // ovals usually do their pits under full course cautions (or stages) so no need to say.
            // the mandatory pitstop flag seems a bit flakey and there have been reported false positives
            if (Strategy.persistBenchmarks && !GlobalBehaviourSettings.useOvalLogic && (lapsInSession >= 30 || minutesInSession >= 35))
            {
                var benchmark = BenchmarkHelper.findPersistedBenchmarkForCombo(-1);
                if (benchmark == null)
                {
                    // these message names are important as they are used to set the nagging flag
                    if (Strategy.enablePitExitPositionEstimates && !currentGameState.SessionData.SessionHasFixedTime && SoundCache.soundSets.ContainsKey(LapCounter.folderNoPitstopEstimatesPosition))
                    {
                        // typically fixed lap races imply formula style races
                        possibleMessages.Add(new QueuedMessage("pitstop_no_benchmark", 0, MessageContents(folderNoPitstopEstimatesPosition), abstractEvent: this, priority: 10));
                    }
                    else if (Fuel.enableFuelMessages && currentGameState.FuelData.FuelUseActive && SoundCache.soundSets.ContainsKey(LapCounter.folderNoPitstopEstimatesFuel))
                    {
                        // typically fixed time races imply sparts car style racing, with fuel stops
                        possibleMessages.Add(new QueuedMessage("pitstop_no_benchmark", 0, MessageContents(Pause(200), folderNoPitstopEstimatesFuel), abstractEvent: this, priority: 10));
                    }
                }
                else
                {
                    possibleMessages.Add(new QueuedMessage("pitstop_benchmark", 0, messageFragments: Strategy.MkPitStopTimeLoss(benchmark.timeLoss), abstractEvent: this, priority: 10));
                }
            }

            if (Game.IRACING)
            {
                if (!currentGameState.PitData.InPitlane && UserSettings.GetUserSettings().getBoolean("enable_tyre_temp_warnings"))
                {
                    // other sims use the TyreMonitor for this but in iRacing we only get the temps when we come into the pits. Getting this message
                    // when starting from the pits is gated by the enable_pit_exit_tyre_temp_warning setting. And is always gated by the tyre_temp
                    // settings since some people might just really hate getting this information and explicitly asked for it to be turned off.
                    possibleMessages.Add(new QueuedMessage("cold_tyres", 0, messageFragments: MessageContents(TyreMonitor.folderColdTyresAllRound), abstractEvent: this, priority: 10));
                }

                // it's possible for these checks the driver might not start, or will start from the pits, which we can't detect.
                // directly behind (assumes double file starts)
                if (currentGameState.SessionData.iRacingStandingStart)
                {
                    var guyBehind = currentGameState.getOpponentAtClassPosition(currentGameState.SessionData.ClassPosition + 2, currentGameState.carClass);
                    bool behind_advice = false; // it's a bit much if we end up noting both directions
                    if (guyBehind != null)
                    {
                        var rep = MkFreshReputationAdvice(guyBehind, opponentIsAhead: false);
                        if (rep.Count > 0)
                        {
                            behind_advice = true;
                            possibleMessages.Add(new QueuedMessage("watch_out_behind", 0, rep, abstractEvent: this, priority: 10));
                        }
                    }
                    var guyAhead = currentGameState.getOpponentAtClassPosition(currentGameState.SessionData.ClassPosition - 2, currentGameState.carClass);
                    if (guyAhead != null && !behind_advice)
                    {
                        var rep = MkFreshReputationAdvice(guyAhead, opponentIsAhead: true);
                        if (rep.Count > 0)
                        {
                            possibleMessages.Add(new QueuedMessage("watch_out_ahead", 0, rep, abstractEvent: this, priority: 10));
                        }
                    }
                }
            }

            // now pick a random selection
            if (possibleMessages.Count > 0)
            {
                int played = 0;
                var shuffled = possibleMessages.OrderBy(item => Utilities.random.Next());
                foreach (var message in shuffled)
                {
                    played++;
                    if (played > maxNumberToPlay)
                    {
                        break;
                    }
                    if (message.messageName == "pitstop_no_benchmark")
                    {
                        // we can't guarantee that this plays, but no harm done
                        Strategy.naggedAboutBenchmarks = true;
                    }

                    Dictionary<String, Object> validationData = new Dictionary<string, object>();
                    validationData.Add("PreLights", true);
                    message.validationData = validationData;
                    audioPlayer.playMessage(message);
                }
            }
        }

        override protected void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (GameStateData.useManualFormationLap)
            {
                // when the session is first cleared, this will be true if we're using manual formation laps:
                if (GameStateData.onManualFormationLap)
                {
                    if (!playedPreLightsRollingStartWarning &&
                        !currentGameState.PitData.InPitlane &&
                        currentGameState.SessionData.SessionType == SessionType.Race &&
                        (currentGameState.SessionData.SessionPhase == SessionPhase.Countdown ||
                         currentGameState.SessionData.SessionPhase == SessionPhase.Formation ||
                         currentGameState.SessionData.SessionPhase == SessionPhase.Gridwalk))
                    {
                        playedPreLightsRollingStartWarning = true;
                        audioPlayer.playMessage(new QueuedMessage(FrozenOrderMonitor.folderRollingStartReminder, 0, abstractEvent: this, priority: 10));
                    }

                    // when the lights change to green, give some info:
                    if (!playedManualStartInitialMessage && previousGameState != null &&
                        !currentGameState.PitData.InPitlane &&
                        currentGameState.SessionData.SessionType == SessionType.Race &&
                        currentGameState.SessionData.SessionPhase == SessionPhase.Green &&
                        (previousGameState.SessionData.SessionPhase == SessionPhase.Formation ||
                         previousGameState.SessionData.SessionPhase == SessionPhase.Countdown))
                    {
                        playManualStartInitialMessage(currentGameState);
                    }
                    // don't bother with any other messages until things have had a few seconds to settle down:
                    else if (currentGameState.SessionData.SessionType == SessionType.Race && currentGameState.SessionData.SessionRunningTime > 10
                        && currentGameState.SessionData.SessionPhase == SessionPhase.Green && !currentGameState.PitData.InPitlane)
                    {
                        checkForIllegalPassesOnFormationLap(currentGameState);
                        checkForManualFormationRaceStart(currentGameState, currentGameState.SessionData.OverallPosition == 1);
                        checkForManualDoubleFileReminder(previousGameState, currentGameState);
                        checkForLeaderHasAccelerated(previousGameState, currentGameState);
                    }
                }
                // now check if we really are on a manual formation lap. We have to do this *after* checking for the race start (above) because
                // this will switch manual formation lap stuff off as soon as we cross the line (so would suppress the 'green green green' message).
                // We want to ensure it's switched off if we're not in a race session, for obvious reasons.
                GameStateData.onManualFormationLap = currentGameState.SessionData.SessionType == SessionType.Race && currentGameState.SessionData.CompletedLaps < 1;
            }
            /*else if (currentGameState.SessionData.StartType == StartType.Rolling)
            {

            }*/
            else
            {
                // for legacy reasons, iracing users may expect the pre-race messages at the very end of the gridwalk stage
                // sometimes SessionTimeRemaining is equal to 7 days (seen on a nascar races in texas, which has a pitlane lineup).
                // We obviously can't do the countdown in that case but we can get on with the gridwalk messages.
                // report upstream https://forums.iracing.com/discussion/60639/
                bool clear_for_messages = !Game.IRACING || currentGameState.SessionData.SessionTimeRemaining < 15 || currentGameState.SessionData.SessionTimeRemaining == 604800;

                // this detects the scenario when we got that bad telemetry AND it's a standing start.
                // when this happens, don't say "get ready" because we are too late.
                bool iracing_hacky_start = Game.IRACING && currentGameState.SessionData.SessionTimeRemaining == 604800 && currentGameState.SessionData.iRacingStandingStart;

                // nasty... 2 separate code paths here - one for the existing pre-lights logic which is a ball of spaghetti I don't fancy unpicking, 
                // one for the 'cancel on control input' version
                if (clear_for_messages && (playPreRaceMessagesUntilCancelled || Game.ACC))
                {
                    if (!playedGetReady)
                    {
                        // in the pre-lights phase
                        if (Game.IRACING && currentGameState.SessionData.iRacingStandingStart && currentGameState.SessionData.SessionTimeRemaining < 1)
                        {
                            // see the notes in the other codepath
                            purgePreLightsMessages = true;
                        }
                        if (purgePreLightsMessages)
                        {
                            // empty the queue and play 'get ready'
                            int purgedCount = audioPlayer.purgeQueues();
                            Log.Debug(() => "Purging pre-lights messages, removed = " + purgedCount + " messages");
                            if (!iracing_hacky_start)
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderGetReady, 0, abstractEvent: this, priority: 10));
                            }
                            playedGetReady = true;
                        }
                        else
                        {
                            if (playedPreLightsMessage && !purgePreLightsMessages)
                            {
                                // we've started playing the pre-lights messages. As soon as the play makes a throttle input purge this queue.
                                // Some games hold the brake at '1' automatically on the grid, so this can't be used
                                //
                                // ACC switches from formation to countdown when we're on the last part of the rolling start but we need to wait a while longer - there's a separate ACC specific variable for this
                                purgePreLightsMessages = currentGameState.SessionData.TriggerStartWarning
                                     || (!Game.ACC && currentGameState.ControlData.ThrottlePedal > 0.2 && previousGameState.ControlData.ThrottlePedal > 0.2);
                            }
                            else
                            {
                                // Play these only for race sessions. Some game-specific rules here:
                                //      Allow messages for countdown phase for any game
                                //      Allow messages for gridwalk phase for any game *except* Raceroom (which treats gridwalk as its own session with different data to the race session)
                                //      Allow messages for formation phase for Raceroom
                                //      Allow messages for formation phase for iRacing
                                //      Allow messages for formation phase for RF1 (AMS), rF2 and GTR2 only when we enter sector 3 of the formation lap.
                                if (currentGameState.SessionData.SessionType == SessionType.Race &&
                                        (currentGameState.SessionData.SessionPhase == SessionPhase.Countdown ||
                                        (currentGameState.SessionData.SessionPhase == SessionPhase.Gridwalk && !Game.RACE_ROOM) ||
                                        (currentGameState.SessionData.SessionPhase == SessionPhase.Formation && Game.RACE_ROOM) ||
                                        (currentGameState.SessionData.SessionPhase == SessionPhase.Formation && Game.IRACING) ||
                                        (currentGameState.SessionData.SessionPhase == SessionPhase.Formation && Game.ACC) ||
                                        (currentGameState.SessionData.SessionPhase == SessionPhase.Formation && (Game.RF1 || Game.RF2_LMU || Game.GTR2) &&
                                        currentGameState.SessionData.SectorNumber == 3)))
                                {
                                    Log.Debug("Queuing pre-lights messages");
                                    LapCounter.preStartTempsAnnounced = false;
                                    playPreLightsMessage(currentGameState, 10); // queue as many messages as we have here, in any order
                                }
                            }
                        }
                    }
                }
                else if (clear_for_messages)
                {
                    int preLightsMessageCount = 2;
                    if (Game.PCARS_32BIT ||
                        Game.PCARS_64BIT ||
                        Game.PCARS_NETWORK ||
                        Game.PCARS2_NETWORK)
                    {
                        preLightsMessageCount = 1;
                    }
                    else if (Game.PCARS2 || Game.AMS2
                        || Game.PCARS3)
                    {
                        preLightsMessageCount = 2 + Utilities.random.Next(6);
                    }
                    else if (Game.RACE_ROOM)
                    {
                        preLightsMessageCount = 2;
                    }
                    else if (Game.IRACING)
                    {
                        preLightsMessageCount = 3;
                    }

                    if (!playedPreLightsMessage && currentGameState.SessionData.SessionType == SessionType.Race && 
                        currentGameState.SessionData.SessionPhase == SessionPhase.Gridwalk && !Game.RF2_LMU && !Game.GTR2) // Not much correct info is available during rF1/rF2's Gridwalk.  In GTR2 it simply does not sound nice.
                    {
                        playPreLightsMessage(currentGameState, preLightsMessageCount);
                        purgePreLightsMessages = true;
                    }

                    // R3E's gridWalk phase isn't useable here - the data during this phase are bollocks
                    if (!playedGetReady && currentGameState.SessionData.SessionType == SessionType.Race && (
                        // in iRacing the countdown phase only happens for standing starts when the red light comes on,
                        // so we prefer to check if we're at the end of the gridwalk when we purge, otherwise we are
                        // too late and it bleeds into the green lights.
                        (Game.IRACING && currentGameState.SessionData.iRacingStandingStart && currentGameState.SessionData.SessionTimeRemaining < 1) ||
                        currentGameState.SessionData.SessionPhase == SessionPhase.Countdown ||
                        (currentGameState.SessionData.SessionPhase == SessionPhase.Formation && Game.RACE_ROOM) ||
                        // play 'get ready' message when entering sector 3 of formation lap in Automobilista
                        (currentGameState.SessionData.SessionPhase == SessionPhase.Formation && Game.RF1 &&
                        currentGameState.SessionData.SectorNumber == 3 && currentGameState.FrozenOrderData.Phase != FrozenOrderPhase.Rolling) ||
                        // play 'get ready' message when entering sector 3 of formation lap in Rolling start of rF2
                        (currentGameState.SessionData.SessionPhase == SessionPhase.Formation && (Game.RF1 || Game.RF2_LMU) &&
                        currentGameState.SessionData.SectorNumber == 3 && (currentGameState.FrozenOrderData.Phase == FrozenOrderPhase.Rolling || currentGameState.FrozenOrderData.Phase == FrozenOrderPhase.FastRolling)) ||
                        // Actually as above, just check for prev sector.  Merge it later with above clause.
                        (currentGameState.SessionData.SessionPhase == SessionPhase.Formation && Game.GTR2 &&
                        previousGameState != null && previousGameState.SessionData.SectorNumber == 2 && currentGameState.SessionData.SectorNumber == 3 && currentGameState.FrozenOrderData.Phase == FrozenOrderPhase.Rolling)))
                    {
                        // If we've not yet played the pre-lights messages, just play one of them here, but not for RaceRoom as the lights will already have started
                        if (!playedPreLightsMessage && !Game.RACE_ROOM)
                        {
                            preLightsMessageCount = !Game.RF2_LMU ? 1 : 2;
                            if (Game.GTR2)
                            {
                                preLightsMessageCount = 3;
                            }

                            playPreLightsMessage(currentGameState, preLightsMessageCount);
                            purgePreLightsMessages = false;
                        }
                        if (purgePreLightsMessages)
                        {
                            int purgedCount = audioPlayer.purgeQueues();
                            Log.Debug(() => "Purging pre-lights messages, removed = " + purgedCount + " messages");
                        }
                        if (!iracing_hacky_start)
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderGetReady, 5, abstractEvent: this, priority: 10));
                        }
                        playedGetReady = true;
                    }
                }
                if (previousGameState != null && 
                    currentGameState.SessionData.SessionType == SessionType.Race &&
                    currentGameState.SessionData.SessionPhase == SessionPhase.Green &&
                    (previousGameState.SessionData.SessionPhase == SessionPhase.Formation ||
                     previousGameState.SessionData.SessionPhase == SessionPhase.Countdown))
                {
                    // ensure we don't play 'get ready' or any pre-lights messages again
                    playedPreLightsMessage = true;
                    playedGetReady = true;
                    int purgeCount = audioPlayer.purgeQueues();
                    Log.Debug(() => "Purged " + purgeCount + " outstanding messages at green light");
                    if (enableGreenLightMessages && !currentGameState.PitData.InPitlane)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderGreenGreenGreen, 2, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                    }
                    audioPlayer.disablePearlsOfWisdom = false;
                    if (enableRf2AutoClearTyreChange && Game.RF2_64BIT)
                    {
                        PitManager.PitManagerVoiceCmds.startOfRace();
                    }
                }
            }

            if (currentGameState.SessionData.SessionType == SessionType.Race &&
                currentGameState.SessionData.SessionPhase == SessionPhase.Gridwalk &&
                currentGameState.SessionData.SessionTimeRemaining > 0)
            {
                int time = (int)currentGameState.SessionData.SessionTimeRemaining;
                if (time < lastReportedGridWalkTime && (time == 90 || time == 60 || time == 30))
                {
                    lastReportedGridWalkTime = time;
                    if (SoundCache.soundSets.ContainsKey(folderRaceStartsIn))
                    {
                        audioPlayer.playMessage(new QueuedMessage($"gridwalk_countdown_{time}", 2, messageFragments: MessageContents(folderRaceStartsIn, time, "timings/seconds")));
                    }
                    else
                    {
                        // while we wait for Jerry to record them...
                        audioPlayer.playMessage(new QueuedMessage($"gridwalk_countdown_{time}", 2, messageFragments: MessageContents(time, "timings/seconds")));
                    }
                }
            }

            // end of start race stuff

            if (currentGameState.SessionData.SessionType == SessionType.Race
                && !leaderHasFinished
                && currentGameState.SessionData.LeaderHasFinishedRace)
            {
                // this plays "X won the race" as it happens. If we want to delay this until we finish the
                // race we will have to rethink how to store that for later retrieval in the post race messages.
                //
                // the intention here is to encourage drivers to congratulate each other over radio
                leaderHasFinished = true;
                if (currentGameState.SessionData.OverallPosition > 1) {
                    var leader = currentGameState.getOpponentAtOverallPosition(1);
                    if (leader != null)
                    {
                        var msg = Opponents.MkOpponentShort(leader, false, false, false, false);
                        msg.Add(MessageFragment.Text(folderTookTheWin));
                        audioPlayer.playMessage(new QueuedMessage("took_the_win", 0, msg));
                    }
                }
            }

            // looks like belt n braces but there's a bug in R3E DTM 2015 race 1 which has a number of laps and a time remaining
            if ((!currentGameState.SessionData.SessionHasFixedTime
                  || Game.RF2_64BIT // (LMU races are all fixed time)
                  || Game.GTR2
                  || Game.IRACING)
                && currentGameState.SessionData.SessionType == SessionType.Race
                && currentGameState.SessionData.IsNewLap
                && currentGameState.SessionData.CompletedLaps > 0
                && currentGameState.SessionData.SessionPhase != SessionPhase.Finished)
            {
                // a new lap has been started in race mode
                if (currentGameState.SessionData.SessionLapsRemaining == 2)
                {
                    // disable pearls for the last part of the race
                    audioPlayer.disablePearlsOfWisdom = true;
                }
                int position = currentGameState.SessionData.ClassPosition;
                if (currentGameState.SessionData.SessionLapsRemaining == 1 || currentGameState.SessionData.IsLastLap)
                {
                    Console.WriteLine("1 lap remaining");
                    if (position == 1)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderLastLapLeading, 10, abstractEvent: this, priority: 10));
                    }
                    else if (position <= 3)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderLastLapTopThree, 10, abstractEvent: this, priority: 10));
                    }
                    else if (position > 3)
                    {
                        LapCounter.whiteFlagLastLapAnnounced = GlobalBehaviourSettings.useAmericanTerms;
                        audioPlayer.playMessage(new QueuedMessage(GlobalBehaviourSettings.useAmericanTerms ? folderLastLapUS : folderLastLapEU, 10, abstractEvent: this, priority: 10));
                    }
                    else
                    {
                        Console.WriteLine("1 lap left but position is < 1");
                    }
                }
                else if (currentGameState.SessionData.SessionLapsRemaining == 2)
                {
                    Console.WriteLine("2 laps remaining");
                    if (position == 1)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderTwoLeftLeading, 10, abstractEvent: this, priority: 10));
                    }
                    else if (position < 4)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderTwoLeftTopThree, 10, abstractEvent: this, priority: 10));
                    }
                    else if (position >= currentGameState.SessionData.SessionStartClassPosition + 5 &&
                        currentGameState.SessionData.LapTimePrevious > currentGameState.TimingData.getPlayerBestLapTime())
                    {
                        // yuk... don't yell at the player for being shit if he's playing Assetto. Because assetto drivers *are* shit, and also the SessionStartClassPosition
                        // might be invalid so perhaps they're really not being shit. At the moment.
                        if (!Game.ASSETTO1)
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderTwoLeft, 10, abstractEvent: this, priority: 10), PearlsOfWisdom.PearlType.BAD, 0.5);
                        }
                    }
                    else if (position >= 4)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderTwoLeft, 10, abstractEvent: this, priority: 10), PearlsOfWisdom.PearlType.NEUTRAL, 0.5);
                    }
                    else
                    {
                        Console.WriteLine("2 laps left but position is < 1");
                    }
                    // 2 laps left, so prevent any further pearls of wisdom being added
                }
            }
        }

        private void playManualStartGreenFlag()
        {
            if (!playedManualStartPlayedGoGoGo)
            {
                audioPlayer.playMessageImmediately(new QueuedMessage(folderGreenGreenGreen, 3, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 15));
            }
            GameStateData.onManualFormationLap = false;
            // reset
            playedManualStartPlayedGoGoGo = false;
            playedManualStartLeaderHasCrossedLine = false;
            playedManualStartGetReady = false;
            playedManualStartInitialMessage = false;
            leaderSpeedAtAccelerationCheckStart = -1;
            poleSitter = null;
            leaderHasGone = false;
            manualStartOpponentToFollow = null;
            manualFormationStartingPosition = 0;
        }

        private void playManualStartGetReady()
        {
            audioPlayer.playMessage(new QueuedMessage(folderGetReady, 3, abstractEvent: this, priority: 10));
            playedManualStartGetReady = true;
        }

        private void setOpponentToFollowAndStartPosition(GameStateData currentGameState, Boolean playerHasCrashed, Boolean getGridSide)
        {
            this.manualFormationStartingPosition = playerHasCrashed ? currentGameState.SessionData.NumCarsOverall : currentGameState.SessionData.OverallPosition;
            if (manualFormationDoubleFile)
            {
                if (getGridSide)
                {
                    Tuple<GridSide, Dictionary<int, GridSide>> playerAndOpponentsInFrontGridSides = this.crewChief.getGridSide();
                    gridSide = playerAndOpponentsInFrontGridSides.Item1;
                    // match up the opponent grid sides to their names
                    foreach (int opponentPosition in playerAndOpponentsInFrontGridSides.Item2.Keys)
                    {
                        foreach (OpponentData opponent in currentGameState.OpponentData.Values)
                        {
                            if (!opponentsInFrontGridSides.ContainsKey(opponent.DriverRawName) && opponent.OverallPosition == opponentPosition)
                            {
                                opponentsInFrontGridSides.Add(opponent.DriverRawName, playerAndOpponentsInFrontGridSides.Item2[opponentPosition]);
                                break;
                            }
                        }
                    }
                }
                if (playerHasCrashed)
                {
                    gridSide = GridSide.UNKNOWN;
                    manualStartOpponentToFollow = null;
                }
                else
                {
                    // get the next opponent in front who started on the same grid side as the player
                    int closestSameSidePosition = 0;
                    String nameOfDriverInFront = null;
                    foreach (String opponentNameInFront in opponentsInFrontGridSides.Keys)
                    {
                        if (opponentsInFrontGridSides[opponentNameInFront] == gridSide &&
                            currentGameState.OpponentData[opponentNameInFront].OverallPosition < manualFormationStartingPosition &&
                            currentGameState.OpponentData[opponentNameInFront].OverallPosition > closestSameSidePosition)
                        {
                            closestSameSidePosition = currentGameState.OpponentData[opponentNameInFront].OverallPosition;
                            nameOfDriverInFront = opponentNameInFront;
                        }
                    }
                    manualStartOpponentToFollow = nameOfDriverInFront;                    
                }
            }
            else
            {
                if (playerHasCrashed)
                {
                    manualStartOpponentToFollow = null;
                }
                else
                {
                    manualStartOpponentToFollow = currentGameState.getOpponentAtOverallPosition(currentGameState.SessionData.OverallPosition - 1).DriverRawName;
                }
            }
        }
        
        private void playManualStartInitialMessage(GameStateData currentGameState)
        {
            setOpponentToFollowAndStartPosition(currentGameState, false, true);
            // in multiclass, 'pole' is the car in p1 for our class
            poleSitter = CrewChief.forceSingleClass || !GameStateData.Multiclass || !manualFormationSplitClasses ? currentGameState.getOpponentAtOverallPosition(1) :
                    currentGameState.getOpponentAtClassPosition(1, currentGameState.carClass);

            // use the driver name in front if we have it - if we're starting on pole the manualStartOpponentAhead var will be null,
            // which will force the audio player to use the secondary message
            List<MessageFragment> messageContentsWithName;
            List<MessageFragment> messageContentsNoName;

            OpponentData opponentToLineUpBehind = getOpponent(currentGameState, manualStartOpponentToFollow);
            if (manualFormationGoWhenLeaderCrossesLine)
            {
                // go when leader crosses line, so make sure we don't say "hold position until the start line"
                messageContentsWithName = MessageContents(folderManualStartInitialIntro,
                        Position.folderStub + currentGameState.SessionData.OverallPosition, folderManualStartInitialOutroWithDriverName1,
                        opponentToLineUpBehind);
                messageContentsNoName = MessageContents(folderManualStartInitialIntro,
                        Position.folderStub + currentGameState.SessionData.OverallPosition, folderHoldYourPosition);
                if (manualFormationDoubleFile && gridSide == GridSide.LEFT)
                {
                    messageContentsWithName.Add(MessageFragment.Text(FrozenOrderMonitor.folderInTheLeftColumn));
                }
                else if (manualFormationDoubleFile && gridSide == GridSide.RIGHT)
                {
                    messageContentsWithName.Add(MessageFragment.Text(FrozenOrderMonitor.folderInTheRightColumn));
                }
            }
            else
            {
                if (manualFormationDoubleFile && gridSide == GridSide.LEFT)
                {
                    messageContentsWithName = MessageContents(folderManualStartInitialIntro,
                            Position.folderStub + currentGameState.SessionData.OverallPosition, folderManualStartStartingOnLeftBehind, opponentToLineUpBehind);
                    messageContentsNoName = MessageContents(folderManualStartInitialIntro,
                            Position.folderStub + currentGameState.SessionData.OverallPosition, FrozenOrderMonitor.folderInTheLeftColumn, folderManualStartInitialOutroNoDriverName);
                }
                else if (manualFormationDoubleFile && gridSide == GridSide.RIGHT)
                {
                    messageContentsWithName = MessageContents(folderManualStartInitialIntro,
                            Position.folderStub + currentGameState.SessionData.OverallPosition, folderManualStartStartingOnRightBehind, opponentToLineUpBehind);
                    messageContentsNoName = MessageContents(folderManualStartInitialIntro,
                            Position.folderStub + currentGameState.SessionData.OverallPosition, FrozenOrderMonitor.folderInTheRightColumn, folderManualStartInitialOutroNoDriverName);
                }
                else
                {
                    messageContentsWithName = MessageContents(folderManualStartInitialIntro,
                            Position.folderStub + currentGameState.SessionData.OverallPosition, folderManualStartInitialOutroWithDriverName1,
                            opponentToLineUpBehind, folderManualStartInitialOutroWithDriverName2);
                    messageContentsNoName = MessageContents(folderManualStartInitialIntro,
                            Position.folderStub + currentGameState.SessionData.OverallPosition, folderManualStartInitialOutroNoDriverName);
                }
            }
            if (opponentToLineUpBehind == null)
            {
                audioPlayer.playMessage(new QueuedMessage("manual_start_intro", 5, messageFragments: messageContentsNoName, abstractEvent: this, priority: 10));
            }
            else
            {
                audioPlayer.playMessage(new QueuedMessage("manual_start_intro", 5, messageFragments: messageContentsWithName,
                    alternateMessageFragments: messageContentsNoName, abstractEvent: this, priority: 10));
            }
            playedManualStartInitialMessage = true;
        }

        private void checkForIllegalPassesOnFormationLap(GameStateData currentGameState)
        {
            if (this.manualStartOpponentToFollow == null || playedManualStartPlayedGoGoGo)
            {
                return;
            }
            OpponentData opponentToFollow = getOpponent(currentGameState, this.manualStartOpponentToFollow);
            if (opponentToFollow == null)
            {
                return;
            }
            if (hasOpponentDroppedBack(currentGameState.SessionData.OverallPosition, opponentToFollow))
            {
                setOpponentToFollowAndStartPosition(currentGameState, false, false);
                OpponentData newOpponentToFollow = getOpponent(currentGameState, manualStartOpponentToFollow);
                if (AudioPlayer.canReadName(newOpponentToFollow.DriverRawName))
                {
                    if (manualFormationDoubleFile)
                    {
                        if (gridSide == GridSide.LEFT)
                        {
                            audioPlayer.playMessage(new QueuedMessage("new_car_to_follow", 3, 
                                messageFragments: MessageContents(folderManualStartInitialOutroWithDriverName1, newOpponentToFollow, FrozenOrderMonitor.folderInTheLeftColumn), 
                                abstractEvent: this, priority: 10));
                        }
                        else
                        {
                            audioPlayer.playMessage(new QueuedMessage("new_car_to_follow", 3, 
                                messageFragments: MessageContents(folderManualStartInitialOutroWithDriverName1, newOpponentToFollow, FrozenOrderMonitor.folderInTheRightColumn),
                                abstractEvent: this, priority: 10));
                        }
                    }
                    else
                    {
                        audioPlayer.playMessage(new QueuedMessage("new_car_to_follow", 3,
                            messageFragments: MessageContents(folderManualStartInitialOutroWithDriverName1, newOpponentToFollow), abstractEvent: this, priority: 10));
                    }
                }
            }
            else if (haveWeDroppedBack(currentGameState))
            {
                if (!playedRejoinAtBackMessage)
                {
                    playedRejoinAtBackMessage = true;
                    audioPlayer.playMessage(new QueuedMessage("rejoin_at_back", 5, messageFragments: MessageContents(folderManualStartRejoinAtBack), abstractEvent: this, priority: 10));
                }
                setOpponentToFollowAndStartPosition(currentGameState, true, false);
            }
            else if (GameStateData.onManualFormationLap && nextManualFormationOvertakeWarning < currentGameState.Now &&
                opponentToFollow != null && opponentToFollow.OverallPosition > currentGameState.SessionData.OverallPosition)
            {
                if (manualFormationDoubleFile)
                {
                    // we've overtaken the guy in we're supposed to be following
                    nextManualFormationOvertakeWarning = currentGameState.Now.AddSeconds(30);
                    Dictionary<String, Object> validationData = new Dictionary<string, object>();
                    validationData.Add("PlayerPosition", currentGameState.SessionData.OverallPosition);
                    validationData.Add("OpponentToFollowName", this.manualStartOpponentToFollow);

                    audioPlayer.playMessage(new QueuedMessage("give_position_back", 10, secondsDelay: 5, validationData: validationData,
                        messageFragments: MessageContents(folderGivePositionBack, folderManualStartInitialOutroWithDriverName1, getOpponent(currentGameState, manualStartOpponentToFollow)),
                        alternateMessageFragments: MessageContents(folderGivePositionBack), abstractEvent: this, priority: 10));                    
                }
            }
        }

        private Boolean hasOpponentDroppedBack(int playerPosition, OpponentData opponent)
        {
            return opponent != null && opponent.OverallPosition > playerPosition + 3;
        }

        private Boolean haveWeDroppedBack(GameStateData currentGameState)
        {
            return currentGameState.SessionData.OverallPosition > manualFormationStartingPosition + 3;
        }

        private void checkForLeaderHasAccelerated(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (leaderHasGone || previousGameState == null || currentGameState.SessionData.TrackDefinition == null ||
                currentGameState.PositionAndMotionData.DistanceRoundTrack == 0 || poleSitter == null || playedManualStartPlayedGoGoGo)
            {
                return;
            }
            float currentDistanceToStartLine = currentGameState.SessionData.TrackDefinition.trackLength - currentGameState.PositionAndMotionData.DistanceRoundTrack;
            if (currentDistanceToStartLine < distanceBeforeLineToStartLeaderAccelerationCheck)
            {
                float previousDistanceToStartLine = currentGameState.SessionData.TrackDefinition.trackLength - previousGameState.PositionAndMotionData.DistanceRoundTrack;
                if (previousDistanceToStartLine > distanceBeforeLineToStartLeaderAccelerationCheck)
                {
                    leaderSpeedAtAccelerationCheckStart = poleSitter.Speed;
                }
                else if (leaderSpeedAtAccelerationCheckStart > 0)
                {
                    if (poleSitter.Speed - leaderSpeedAtAccelerationCheckStart > 5)
                    {
                        Console.WriteLine("Looks like the leader has 'gone'");
                        audioPlayer.playMessage(new QueuedMessage(folderManualStartLeaderHasGone, 2, abstractEvent: this, priority: 10));
                        leaderHasGone = true;
                    }
                }
            }
        }

        private void checkForManualDoubleFileReminder(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (manualFormationDoubleFile && gridSide != GridSide.UNKNOWN && previousGameState != null &&
                previousGameState.SessionData.SectorNumber == 2 && currentGameState.SessionData.SectorNumber == 3)
            {
                // use the driver name in front if we have it - if we're starting on pole the manualStartOpponentAhead var will be null,
                // which will force the audio player to use the secondary message
                List<MessageFragment> messageContentsWithName = null;
                List<MessageFragment> messageContentsNoName = null;
                OpponentData opponentToLineUpBehind = getOpponent(currentGameState, manualStartOpponentToFollow);
                if (manualFormationGoWhenLeaderCrossesLine)
                {
                    if (gridSide == GridSide.LEFT)
                    {
                        messageContentsWithName = MessageContents(folderManualStartFormUpBehind, opponentToLineUpBehind, FrozenOrderMonitor.folderInTheLeftColumn);
                        messageContentsNoName = MessageContents(folderHoldYourPosition, FrozenOrderMonitor.folderInTheLeftColumn);
                    }
                    else
                    {
                        messageContentsWithName = MessageContents(folderManualStartFormUpBehind, opponentToLineUpBehind, FrozenOrderMonitor.folderInTheRightColumn);
                        messageContentsNoName = MessageContents(folderHoldYourPosition, FrozenOrderMonitor.folderInTheRightColumn);
                    }
                }
                else
                {
                    if (gridSide == GridSide.LEFT)
                    {
                        messageContentsWithName = MessageContents(folderManualStartFormUpBehind, opponentToLineUpBehind,
                            FrozenOrderMonitor.folderInTheLeftColumn);
                        messageContentsNoName = MessageContents(folderManualStartInitialOutroNoDriverName, FrozenOrderMonitor.folderInTheLeftColumn);
                    }
                    else
                    {
                        messageContentsWithName = MessageContents(folderManualStartFormUpBehind, opponentToLineUpBehind,
                            FrozenOrderMonitor.folderInTheRightColumn);
                        messageContentsNoName = MessageContents(folderManualStartInitialOutroNoDriverName, FrozenOrderMonitor.folderInTheRightColumn);
                    }
                }
                if (opponentToLineUpBehind == null)
                {
                    audioPlayer.playMessage(new QueuedMessage("manual_start_double_file_reminder", 10, messageFragments: messageContentsNoName, abstractEvent: this, priority: 10));
                }
                else
                {
                    audioPlayer.playMessage(new QueuedMessage("manual_start_double_file_reminder", 10, messageFragments: messageContentsWithName, 
                        alternateMessageFragments: messageContentsNoName, abstractEvent: this, priority: 10));
                }
            }
        }

        private void checkForManualFormationRaceStart(GameStateData currentGameState, Boolean isLeader)
        {
            if (isLeader)
            {
                // we're the leader, so play 'go' when we cross the line and get ready when we're near the line
                if (currentGameState.SessionData.CompletedLaps == 1)
                {
                    playManualStartGreenFlag();
                }
                else if (!playedManualStartGetReady && currentGameState.SessionData.SectorNumber == 3 &&
                    currentGameState.PositionAndMotionData.DistanceRoundTrack > currentGameState.SessionData.TrackDefinition.trackLength - 200)
                {
                    playManualStartGetReady();
                }
            }
            else
            {
                if (manualFormationGoWhenLeaderCrossesLine)
                {
                    // here we're only interested in what the pole sitter is up to
                    if (poleSitter != null)
                    {
                        if (!playedManualStartGetReady && poleSitter.CurrentSectorNumber == 3 &&
                            poleSitter.DistanceRoundTrack > currentGameState.SessionData.TrackDefinition.trackLength - 200)
                        {
                            playManualStartGetReady();
                        }
                        else if (poleSitter.CompletedLaps == 1)
                        {
                            playManualStartGreenFlag();
                        }
                    }
                }
                else
                {
                    // give leader updates then green when we cross the line
                    if (currentGameState.SessionData.CompletedLaps == 1)
                    {
                        playManualStartGreenFlag();
                    }
                    else if (!playedManualStartGetReady && currentGameState.SessionData.SectorNumber == 3 &&
                            currentGameState.PositionAndMotionData.DistanceRoundTrack > currentGameState.SessionData.TrackDefinition.trackLength - 300)
                    {
                        playManualStartGetReady();
                    }
                    else if (currentGameState.SessionData.OverallPosition > 3)
                    {
                        // don't say "leader has crossed the line" if we're right behind him - this would delay the 'go go go' call
                        if (poleSitter != null && !playedManualStartLeaderHasCrossedLine && poleSitter.CompletedLaps == 1)
                        {
                            playedManualStartLeaderHasCrossedLine = true;
                            audioPlayer.playMessageImmediately(new QueuedMessage(folderLeaderHasCrossedStartLine, 2, abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                        }
                    }
                }
            }
        }
    }
}
