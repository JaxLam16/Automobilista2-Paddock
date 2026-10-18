using System;
using System.Collections.Generic;

using CrewChiefV4.GameState;
using CrewChiefV4.Audio;
using CrewChiefV4.NumberProcessing;

namespace CrewChiefV4.Events
{
    class FlagsMonitor : AbstractEvent
    {
        private const String folderBlueFlag = "flags/blue_flag";
        private const String folderYellowFlag = "flags/yellow_flag";
        private const String folderDoubleYellowFlag = "flags/double_yellow_flag";
        private const String folderWhiteFlagEU = "flags/white_flag";
        private const String folderBlackFlag = "flags/black_flag";

        private DateTime disableYellowFlagUntil = DateTime.MinValue;
        private DateTime disableBlackFlagUntil = DateTime.MinValue;
        private DateTime disableWhiteFlagUntil = DateTime.MinValue;
        private DateTime disableBlueFlagUntil = DateTime.MinValue;
        private DateTime disableRedYellowFlagUntil = DateTime.MinValue;

        private readonly TimeSpan timeBetweenYellowFlagMessages = TimeSpan.FromSeconds(25);
        private readonly TimeSpan timeBetweenBlueFlagMessages = TimeSpan.FromSeconds(15);
        private readonly TimeSpan timeBetweenBlackFlagMessages = TimeSpan.FromSeconds(15);
        private readonly TimeSpan timeBetweenWhiteFlagMessages = TimeSpan.FromSeconds(15);
        private readonly TimeSpan timeBetweenRedYellowFlagMessages = TimeSpan.FromSeconds(minSecsDebrisFlag);

        private readonly String folderFCYellowStart = GlobalBehaviourSettings.useAmericanTerms ? "flags/fc_yellow_start_usa" : "flags/fc_yellow_start_eu";
        private readonly String folderFCYellowStartNoSafetyCar = GlobalBehaviourSettings.useAmericanTerms ? "flags/fc_yellow_start_usa_no_safetycar" : "flags/fc_yellow_start_eu_no_safetycar";
        private readonly String folderFCYellowPitsClosed = GlobalBehaviourSettings.useAmericanTerms ? "flags/fc_yellow_pits_closed_usa" : "flags/fc_yellow_pits_closed_eu";
        private readonly String folderFCYellowPitsOpenLeadLapCars = GlobalBehaviourSettings.useAmericanTerms ? "flags/fc_yellow_pits_open_lead_lap_cars_usa" : "flags/fc_yellow_pits_open_lead_lap_cars_eu";
        private readonly String folderFCYellowPitsOpen = GlobalBehaviourSettings.useAmericanTerms ? "flags/fc_yellow_pits_open_usa" : "flags/fc_yellow_pits_open_eu";
        private readonly String folderFCYellowLastLapNext = GlobalBehaviourSettings.useAmericanTerms ? "flags/fc_yellow_last_lap_next_usa" : "flags/fc_yellow_last_lap_next_eu";
        private readonly String folderFCYellowLastLapCurrent = GlobalBehaviourSettings.useAmericanTerms ? "flags/fc_yellow_last_lap_current_usa" : "flags/fc_yellow_last_lap_current_eu";
        private readonly String folderFCYellowPrepareForGreen = GlobalBehaviourSettings.useAmericanTerms ? "flags/fc_yellow_prepare_for_green_usa" : "flags/fc_yellow_prepare_for_green_eu";
        private readonly String folderFCYellowInProgress = GlobalBehaviourSettings.useAmericanTerms ? "flags/fc_yellow_in_progress_usa" : "flags/fc_yellow_in_progress_eu";
        private const String folderFCYellowGreenFlag = "flags/fc_yellow_green_flag";
        public  const String folderPaceCarIsIn = "flags/the_pace_car_is_in_turn";

        private readonly String[] folderYellowFlagSectors = new String[] { "flags/yellow_flag_sector_1", "flags/yellow_flag_sector_2", "flags/yellow_flag_sector_3" };
        private readonly String[] folderDoubleYellowFlagSectors = new String[] { "flags/double_yellow_flag_sector_1", "flags/double_yellow_flag_sector_2", "flags/double_yellow_flag_sector_3" };
        private readonly String[] folderGreenFlagSectors = new String[] { "flags/green_flag_sector_1", "flags/green_flag_sector_2", "flags/green_flag_sector_3" };

        private const String folderLocalYellow = "flags/local_yellow_flag";
        private const String folderLocalYellowClear = "flags/local_yellow_clear";
        private const String folderLocalYellowAhead = "flags/local_yellow_ahead";

        private const String folderRedYellowFlag = "flags/red-yellow-flag";
        private const String folderSlippySurfaceFlag = "flags/slippery-surface-flag";

        public static readonly String[] folderPositionHasGoneOff = new String[] { "flags/position1_has_gone_off", "flags/position2_has_gone_off", "flags/position3_has_gone_off", 
                                                                   "flags/position4_has_gone_off", "flags/position5_has_gone_off", "flags/position6_has_gone_off", };
        private readonly String[] folderPositionHasGoneOffIn = new String[] { "flags/position1_has_gone_off_in", "flags/position2_has_gone_off_in", "flags/position3_has_gone_off_in", 
                                                                   "flags/position4_has_gone_off_in", "flags/position5_has_gone_off_in", "flags/position6_has_gone_off_in", };
        private const String folderNameHasGoneOffIntro = "flags/name_has_gone_off_intro";
        private const String folderNameHasGoneOffOutro = "flags/name_has_gone_off_outro";
        //  used when we know the corner name:
        private const String folderNameHasGoneOffInOutro = "flags/name_has_gone_off_in_outro";

        private const String folderNamesHaveGoneOffOutro = "flags/names_have_gone_off_outro";
        private const String folderNamesHaveGoneOffInOutro = "flags/names_have_gone_off_in_outro";
        private const String folderAnd = "flags/and";

        private const String folderPileupInCornerIntro = "flags/pileup_in_corner_intro";

        private const String folderIncidentInCornerIntro = "flags/incident_in_corner_intro";
        private const String folderIncidentInCornerDriverIntro = "flags/incident_in_corner_with_driver_intro";

        private const String folderGivePositionsBackFirstWarningIntro = "flags/give_positions_back_first_warning_intro";
        private const String folderGivePositionsBackNextWarningIntro = "flags/give_positions_back_next_warning_intro";
        private const String folderGiveOnePositionBackFirstWarning = "flags/give_one_position_back_first_warning";
        private const String folderGiveOnePositionsBackNextWarning = "flags/give_one_position_back_next_warning";
        private const String folderGivePositionsBackFirstWarningOutro = "flags/give_positions_back_first_warning_outro";
        private const String folderGivePositionsBackNextWarningOutro = "flags/give_positions_back_next_warning_outro";
        private const String folderGivePositionsBackCompleted = "flags/give_positions_back_completed";

        private const String folderNoOvertaking = "flags/no_overtaking";
        private const String folderClearToOvertake = "flags/clear_to_overtake";

        // StockCarRulesData states
        private const String folderLeaderChooseLane = "flags/choose_a_lane_by_staying_left_or_right";
        private const String folderOpponentIsLuckyDog = "flags/is_the_lucky_dog";
        private const String folderAllowLuckyDogPass = "flags/let_the_lucky_dog_pass_on_left";
        private const String folderWeAreLuckyDog = "flags/we_are_the_lucky_dog";
        private const String folderEOLLPenalty = "flags/move_to_end_of_longest_line_for_penalty";
        private const String folderWeHaveBeenWavedAround = "flags/we_have_been_waved_around";
        private const String folderPassDriverForLuckyDogPositionIntro = "flags/pass_drivername_for_lucky_dog_position_intro";
        private const String folderPassDriverForLuckyDogPositionOutro = "flags/pass_drivername_for_lucky_dog_position_outro";
        private const String folderPassCarAheadForLuckyPositionDog = "flags/pass_this_guy_to_get_lucky_dog_position";
        private const String folderWeAreInLuckyDogPosition = "flags/we_are_in_lucky_dog_position";
        private const String folderLuckyDogPassOnOutside = "flags/lucky_dog_pass_on_outside";
        private const String folderLuckyDogAllowPassOnOutside = "flags/lucky_dog_allow_pass_on_outside";
        private const String folderMoveToChooseLane = "flags/move_to_choose_lane";
        private const String folderWaveAroundCatchEndOfField = "flags/wave_around_catch_end_of_field";
        private const String folderRemindLuckyDog = "flags/remind_lucky_dog";
        private const String folderTwoToGreen = "flags/two_to_green";
        private const String folderTwoToGreenRemindLuckyDog = "flags/two_to_green_remind_lucky_dog";

        // green flag lucky-dog tracking
        private enum GreenFlagLuckyDogStatus { NONE, PASS_FOR_LUCKY_DOG, WE_ARE_IN_LUCKY_DOG }
        private readonly TimeSpan minTimeBetweenGreenFlagLuckyDogMessages = TimeSpan.FromMinutes(2);
        private readonly TimeSpan greenFlagLuckyDogCheckInterval = TimeSpan.FromSeconds(15);
        private const int maxGreenFlagLuckyDogMessagesPerSession = 2;
        private GreenFlagLuckyDogStatus lastGreenFlagLuckyDogStatusAnnounced = GreenFlagLuckyDogStatus.NONE;
        private DateTime nextGreenFlagLuckyDogCheckDue = DateTime.MinValue;
        private int greenFlagLuckyDogMessageCountInSession = 0;

        private readonly int maxDistanceMovedForYellowAnnouncement = UserSettings.GetUserSettings().getInt("max_distance_moved_for_yellow_announcement");
        private static readonly int minSecsDebrisFlag = UserSettings.GetUserSettings().getInt("min_secs_for_debris_flag");
        private readonly Boolean reportAllowedOvertakesUnderYellow = UserSettings.GetUserSettings().getBoolean("report_allowed_overtakes_under_yellow");

        private readonly Boolean overrideIracingLuckyDog = UserSettings.GetUserSettings().getBoolean("iracing_override_luckydog");
        private readonly Boolean disableIracingLuckyDog = UserSettings.GetUserSettings().getBoolean("iracing_disable_luckydog");

        // for new (RF2 and R3E) impl
        private FlagEnum[] lastSectorFlags = new FlagEnum[] { FlagEnum.GREEN, FlagEnum.GREEN, FlagEnum.GREEN };
        private FlagEnum[] lastSectorFlagsReported = new FlagEnum[] { FlagEnum.GREEN, FlagEnum.GREEN, FlagEnum.GREEN };
        private DateTime[] lastSectorFlagsReportedTime = new DateTime[] { DateTime.MinValue, DateTime.MinValue, DateTime.MinValue };
        private FullCourseYellowPhase lastFCYAnnounced = FullCourseYellowPhase.RACING;
        public DateTime lastFCYAccountedTime = DateTime.MinValue;
        private TimeSpan timeBetweenYellowAndClearFlagMessages = TimeSpan.FromSeconds(3);
        private TimeSpan minTimeBetweenNewYellowFlagMessages = TimeSpan.FromSeconds(10);

        // do we need this?
        private DateTime lastLocalYellowAnnouncedTime = DateTime.MinValue;
        private DateTime lastLocalYellowClearAnnouncedTime = DateTime.MinValue;
        private DateTime lastOvertakeAllowedReportTime = DateTime.MinValue;
        private Boolean isUnderLocalYellow = false;
        private Boolean hasReportedIsUnderLocalYellow = false;
        private Boolean hasWarnedOfUpcomingIncident = false;

        private DateTime nextIncidentDriversCheck = DateTime.MaxValue;

        private readonly TimeSpan fcyStatusReminderMinTime = TimeSpan.FromSeconds(UserSettings.GetUserSettings().getInt("time_between_caution_period_status_reminders"));

        private readonly Boolean reportYellowsInAllSectors = UserSettings.GetUserSettings().getBoolean("report_yellows_in_all_sectors");
              
        private readonly Boolean enableOpponentCrashMessages = UserSettings.GetUserSettings().getBoolean("enable_opponent_crash_messages");
        private readonly Boolean enableBlueFlagMessages = UserSettings.GetUserSettings().getBoolean("enable_blue_flag_messages");

        private readonly int simpleIncidentReportDelay = UserSettings.GetUserSettings().getInt("simple_incident_detection_report_delay");

        private const float maxDistanceToWarnOfLocalYellow = 300;    // metres - externalise? Is this sufficient? Make it speed-dependent?
        private const float minDistanceToWarnOfLocalYellow = 50;    // metres - externalise? Is this sufficient? Make it speed-dependent?

        List<IncidentCandidate> incidentCandidates = new List<IncidentCandidate>();

        private int playerClassPositionAtStartOfIncident = int.MaxValue;

        private Dictionary<string, DateTime> incidentWarnings = new Dictionary<string, DateTime>();

        private readonly TimeSpan incidentRepeatFrequency = TimeSpan.FromSeconds(30);

        private int getInvolvedInIncidentAttempts = 0;

        private const int maxFCYGetInvolvedInIncidentAttempts = 5;

        private readonly TimeSpan incidentDriversCheckInterval = TimeSpan.FromSeconds(1.5);

        private const int maxLocalYellowGetInvolvedInIncidentAttempts = 2;

        private const int maxDriversToReportAsInvolvedInIncident = 3;

        private const int pileupDriverCount = 4;

        int waitingForCrashedDriverInSector = -1;

        private Dictionary<string, float> lastIncidentPositionForOpponents = new Dictionary<string, float>();

        private List<NamePositionPair> driversInvolvedInCurrentIncident = new List<NamePositionPair>();

        private String waitingForCrashedDriverInCorner = null;
        private List<String> driversCrashedInCorner = new List<String>();
        private DateTime waitingForCrashedDriverInCornerFinishTime = DateTime.MaxValue;

        // this will be initialised to something sensible once a yellow has been shown - if no yellow is ever 
        // shown we never want to check for illegal passes
        private DateTime nextIllegalPassWarning = DateTime.MaxValue;
        private TimeSpan illegalPassRepeatInterval = TimeSpan.FromSeconds(7);
        private int illegalPassCarsCountAtLastAnnouncement = 0;
        private Boolean hasAlreadyWarnedAboutIllegalPass = false;

        private TimeSpan incidentAheadSettlingTime = TimeSpan.FromSeconds(2);
        private DateTime incidentAheadSettledTime = DateTime.MinValue;
        private Boolean waitingToWarnOfIncident = false;

        private const String validationSectorNumberKey = "sectorNumber";
        private const String validationSectorFlagKey = "sectorFlag";
        private const String validationIsLocalYellowKey = "isLocalYellow";
        private const String sectorFlagChangeMessageKeyStart = "sectorFlagChange_Sector";
        private const String localFlagChangeMessageKey = "localFlagChange";
        private const String isValidatingSectorMessage = "isValidatingSectorMessage";

        private PassAllowedUnderYellow lastReportedOvertakeAllowed = PassAllowedUnderYellow.NO_DATA;

        private int blueFlagWarningCountForSingleDriver = 0;
        private String opponentWhoTriggeredLastBlueFlag = null;

        // keep track of who's stopped where so we don't repeat warnings
        private Dictionary<OpponentData, string> alreadyAnnouncedStoppedOpponentCorners = new Dictionary<OpponentData, string>();

        public FlagsMonitor(AudioPlayer audioPlayer)
        {
            Enum.TryParse(UserSettings.GetUserSettings().getString("enable_simple_incident_detection_listprop"), out simpleIncidentDetectionSessions);
            this.audioPlayer = audioPlayer;
        }

        public override List<SessionType> applicableSessionTypes
        {
            get { return new List<SessionType> { SessionType.Practice, SessionType.Qualify, SessionType.Race }; }
        }

        public override List<SessionPhase> applicableSessionPhases
        {
            get { return new List<SessionPhase> { SessionPhase.Green, SessionPhase.Checkered, SessionPhase.FullCourseYellow }; }
        }

        /*
         * IMPORTANT: This method is called twice - when the message becomes due, and immediately before playing it (which may have a 
         * delay caused by the length of the queue at the time). So be *very* careful when checking and updating local state in here.
         */
        public override bool isMessageStillValid(string eventSubType, GameStateData currentGameState, Dictionary<String, Object> validationData)
        {
            if (base.isMessageStillValid(eventSubType, currentGameState, validationData))
            {
                if (currentGameState.PitData.InPitlane)
                {
                    return false;
                }
                if (eventSubType == folderFCYellowPitsClosed)
                {
                    return currentGameState.FlagData.fcyPhase == FullCourseYellowPhase.PITS_CLOSED;
                }
                else if (eventSubType == folderFCYellowPitsOpen)
                {
                    return currentGameState.FlagData.fcyPhase == FullCourseYellowPhase.PITS_OPEN;
                }
                if (validationData == null) {
                    return true;
                }
                if ((Boolean) validationData[isValidatingSectorMessage])
                {
                    int sectorIndex = (int)validationData[validationSectorNumberKey];
                    FlagEnum sectorFlagWhenQueued = (FlagEnum)validationData[validationSectorFlagKey];
                    if (lastSectorFlags[sectorIndex] == sectorFlagWhenQueued)
                    {
                        lastSectorFlagsReported[sectorIndex] = sectorFlagWhenQueued;
                        lastSectorFlagsReportedTime[sectorIndex] = currentGameState.Now;
                        //Console.WriteLine("FLAG_DEBUG: transition to sector " + (sectorIndex + 1) + " " + sectorFlagWhenQueued + " is valid at " + currentGameState.Now.ToString("HH:mm:ss"));
                        return true;
                    }
                    else
                    {
                        // reset the last reported flag and the time so we can report this flag transition when it's actually valid:
                        lastSectorFlagsReported[sectorIndex] = sectorFlagWhenQueued == FlagEnum.YELLOW ? FlagEnum.GREEN : FlagEnum.YELLOW;
                        lastSectorFlagsReportedTime[sectorIndex] = DateTime.MinValue;
                        //Console.WriteLine("FLAG_DEBUG: transition to sector " + (sectorIndex + 1) + " " + sectorFlagWhenQueued + " is NOT valid at " + currentGameState.Now.ToString("HH:mm:ss"));
                        return false;
                    }
                }
                else
                {
                    Boolean wasLocalYellow = (Boolean)validationData[validationIsLocalYellowKey];
                    if (currentGameState.FlagData.isLocalYellow && wasLocalYellow)
                    {
                        hasReportedIsUnderLocalYellow = true;
                        lastSectorFlagsReported[currentGameState.SessionData.SectorNumber - 1] = FlagEnum.YELLOW;
                        lastSectorFlagsReportedTime[currentGameState.SessionData.SectorNumber - 1] = currentGameState.Now;
                        //Console.WriteLine("FLAG_DEBUG: transition to local YELLOW is valid at " + currentGameState.Now.ToString("HH:mm:ss"));
                        return true;
                    }
                    else if (!currentGameState.FlagData.isLocalYellow && !wasLocalYellow && !currentGameState.PitData.InPitlane)
                    {
                        hasReportedIsUnderLocalYellow = false;
                        // don't change the local sector state to green here - it might remain yellow after we pass the incident
                        // lastSectorFlagsReported[currentGameState.SessionData.SectorNumber - 1] = FlagEnum.GREEN;
                        lastSectorFlagsReportedTime[currentGameState.SessionData.SectorNumber - 1] = currentGameState.Now;
                        //Console.WriteLine("FLAG_DEBUG: transition to local GREEN is valid at " + currentGameState.Now.ToString("HH:mm:ss"));
                        return true;
                    }
                    else
                    {
                       // Console.WriteLine("FLAG_DEBUG: transition to local " + (wasLocalYellow ? "YELLOW" : "GREEN") + " is NOT valid at " + currentGameState.Now.ToString("HH:mm:ss"));
                    }
                }
            }
            return false;           
        }

        public override void clearState()
        {
            disableYellowFlagUntil = DateTime.MinValue;
            disableWhiteFlagUntil = DateTime.MinValue;
            disableBlackFlagUntil = DateTime.MinValue;
            disableBlueFlagUntil = DateTime.MinValue;
            disableRedYellowFlagUntil = DateTime.MinValue;

            lastSectorFlags = new FlagEnum[] { FlagEnum.GREEN, FlagEnum.GREEN, FlagEnum.GREEN };
            lastSectorFlagsReported = new FlagEnum[] { FlagEnum.GREEN, FlagEnum.GREEN, FlagEnum.GREEN };
            lastSectorFlagsReportedTime = new DateTime[] { DateTime.MinValue, DateTime.MinValue, DateTime.MinValue };
            nextIncidentDriversCheck = DateTime.MaxValue;
            lastFCYAnnounced = FullCourseYellowPhase.RACING;
            lastFCYAccountedTime = DateTime.MinValue;
            lastLocalYellowAnnouncedTime = DateTime.MinValue;
            lastLocalYellowClearAnnouncedTime = DateTime.MinValue;
            lastOvertakeAllowedReportTime = DateTime.MinValue;
            isUnderLocalYellow = false;
            hasWarnedOfUpcomingIncident = false;
            playerClassPositionAtStartOfIncident = int.MaxValue;
            incidentCandidates.Clear();
            incidentWarnings.Clear();
            getInvolvedInIncidentAttempts = 0;
            driversInvolvedInCurrentIncident.Clear();
            waitingForCrashedDriverInSector = -1;

            waitingForCrashedDriverInCorner = null;
            driversCrashedInCorner.Clear();
            alreadyAnnouncedStoppedOpponentCorners.Clear();
            waitingForCrashedDriverInCornerFinishTime = DateTime.MaxValue;

            nextIllegalPassWarning = DateTime.MaxValue;
            illegalPassCarsCountAtLastAnnouncement = 0;
            hasAlreadyWarnedAboutIllegalPass = false;

            lastReportedOvertakeAllowed = PassAllowedUnderYellow.NO_DATA;

            incidentAheadSettledTime = DateTime.MinValue;
            waitingToWarnOfIncident = false;
            hasReportedIsUnderLocalYellow = false;

            lastGreenFlagLuckyDogStatusAnnounced = GreenFlagLuckyDogStatus.NONE;
            greenFlagLuckyDogMessageCountInSession = 0;
            nextGreenFlagLuckyDogCheckDue = DateTime.MinValue;

            lastIncidentPositionForOpponents.Clear();

            opponentWhoTriggeredLastBlueFlag = null;
            blueFlagWarningCountForSingleDriver = 0;

            previousLuckyDogNameRaw = null;
            previousStockCarRuleApplicable = StockCarRule.NONE;
            luckyDogCalled = false;
    }

    override protected void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (currentGameState.PitData.InPitlane || currentGameState.SessionData.SessionRunningTime < 10 || GameStateData.onManualFormationLap)
            {
                // don't process if we're in the pits or just started a session
                return;
            }
            if (currentGameState.SessionData.JustGoneGreen)
            {
                // ensure blue & white flags aren't enabled immediately:
                disableBlueFlagUntil = currentGameState.Now.Add(timeBetweenBlueFlagMessages + TimeSpan.FromSeconds(Utilities.random.Next(0, 11)));
            }

            if (previousGameState != null && currentGameState.FlagData.useImprovisedIncidentCalling != previousGameState.FlagData.useImprovisedIncidentCalling)
            {
                Log.Debug(() => $"improvised incident calling is now {currentGameState.FlagData.useImprovisedIncidentCalling}");
            }
            if (currentGameState.FlagData.useImprovisedIncidentCalling)
            {
                improvisedYellowFlagImplementation(previousGameState, currentGameState);
            }
            else
            {
                gameDataYellowFlagImplementation(previousGameState, currentGameState);
            }
            //  now other flags
            if (currentGameState.PositionAndMotionData.CarSpeed < 1)
            {
                return;
            }
            
            if (currentGameState.SessionData.Flag == FlagEnum.RED_YELLOW && minSecsDebrisFlag >= 0)
            {
                if (currentGameState.Now > disableRedYellowFlagUntil)
                {
                    disableRedYellowFlagUntil = currentGameState.Now.Add(timeBetweenRedYellowFlagMessages);
                    if (Game.IRACING && Utilities.random.NextDouble() > 0.5)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderSlippySurfaceFlag, 0, abstractEvent: this, priority: 10));
                    }
                    else
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderRedYellowFlag, 0, abstractEvent: this, priority: 10));
                    }
                }
            }
            else if (currentGameState.SessionData.Flag == FlagEnum.BLACK)
            {
                if (currentGameState.Now > disableBlackFlagUntil)
                {
                    disableBlackFlagUntil = currentGameState.Now.Add(timeBetweenBlackFlagMessages + TimeSpan.FromSeconds(Utilities.random.Next(0, 8)));
                    audioPlayer.playMessage(new QueuedMessage(folderBlackFlag, 0, abstractEvent: this, priority: 10));
                }
            }
            else if (!currentGameState.PitData.InPitlane && currentGameState.SessionData.Flag == FlagEnum.BLUE && enableBlueFlagMessages)
            {
                if (currentGameState.Now > disableBlueFlagUntil)
                {
                    disableBlueFlagUntil = currentGameState.Now.Add(timeBetweenBlueFlagMessages + TimeSpan.FromSeconds(Utilities.random.Next(0, 8)));
                    String opponentKeyBehind = currentGameState.getOpponentKeyBehindOnTrack(true);
                    // if the last 3 warnings are for this same driver, don't call the blue flag. Note that it's unsafe to 
                    // assume opponentKeyBehind is never null
                    if (opponentWhoTriggeredLastBlueFlag == null || !opponentWhoTriggeredLastBlueFlag.Equals(opponentKeyBehind) || blueFlagWarningCountForSingleDriver < 3)
                    {
                        // only update this stuff if we were able to derive the opponent behind on track
                        if (opponentKeyBehind != null)
                        {
                            opponentWhoTriggeredLastBlueFlag = opponentKeyBehind;
                            blueFlagWarningCountForSingleDriver++;
                        }
                        // immediate to prevent it being delayed by the hard-parts logic
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderBlueFlag, 6, abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                    }
                }
            }
            // In iRacing White flag is set on last lap, this causes white flag to be announched every 40 sec on last lap.
            else if (currentGameState.SessionData.Flag == FlagEnum.WHITE
                     && !Game.IRACING
                     && !LapCounter.whiteFlagLastLapAnnounced)
            {
                if (currentGameState.Now > disableWhiteFlagUntil)
                {
                    disableWhiteFlagUntil = currentGameState.Now.Add(timeBetweenWhiteFlagMessages + TimeSpan.FromSeconds(Utilities.random.Next(0, 11)));
                    audioPlayer.playMessageImmediately(new QueuedMessage(folderWhiteFlagEU, 2, abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                }
            }
            if (currentGameState.FlagData.numCarsPassedIllegally >= 0
                && currentGameState.Now > nextIllegalPassWarning && currentGameState.FlagData.numCarsPassedIllegally != illegalPassCarsCountAtLastAnnouncement)
            {
                processIllegalOvertakes(previousGameState, currentGameState);
                illegalPassCarsCountAtLastAnnouncement = currentGameState.FlagData.numCarsPassedIllegally;
            }

            processsStockCarRules(previousGameState, currentGameState);
        }

        // for some sims we calculate these values, so we cache them here
        private volatile string previousLuckyDogNameRaw;
        private volatile StockCarRule previousStockCarRuleApplicable;
        private volatile bool luckyDogCalled;

        private void processsStockCarRules(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (previousGameState == null || !currentGameState.StockCarRulesData.stockCarRulesEnabled)
            {
                return;
            }

            if (GlobalBehaviourSettings.useAmericanTerms && currentGameState.SessionData.SessionType == SessionType.Race)
            {
                if (currentGameState.SessionData.SessionPhase == SessionPhase.FullCourseYellow)
                {

                    string luckyDogNameRaw = null;
                    string luckyDogNumber = null;

                    if (!previousGameState.FlagData.isFullCourseYellow)
                    {
                        luckyDogCalled = false;
                    }

                    // When a FCY comes out, the pit lane closes. The pit lane opens again when enough cars have caught
                    // the pace car. Then, the next time the leader (or, equivalently, the pace car) passes the start/finish
                    // the lucky dog is calculated and allowed to pass the pace car. The lucky dog is the car closest to the
                    // lead lap who was not involved in the incident that brought out the FCY (and in iRacing, any additional
                    // incidents since then including bumping the walls or going offtrack). It is impossible to calculate the final
                    // part in CrewChief because we don't have access to opponent incidents and we are blind to 0x.
                    // (thanks to "foughtabear" for reverse engineering this)
                    bool pitsOpen = currentGameState.FlagData.fcyPhase == FullCourseYellowPhase.PITS_OPEN;
                    bool leaderNewLap = currentGameState.getOpponentAtOverallPosition(1).IsNewLap;
                    bool readyToCallLuckyDog = !luckyDogCalled && pitsOpen && (!overrideIracingLuckyDog || leaderNewLap);

                    // only calculate the FCY lucky dog one time for iRacing, allow other games to dynamically update it.
                    // we can get rid of this if the iRacing telemetry becomes more reliable and don't need the override.
                    if (!Game.IRACING || readyToCallLuckyDog)
                    {
                        (luckyDogNameRaw, luckyDogNumber) = getLuckyDog(currentGameState, Game.IRACING && overrideIracingLuckyDog);
                    }
                    else
                    {
                        luckyDogNameRaw = previousLuckyDogNameRaw;
                    }

                    if (luckyDogNameRaw != previousLuckyDogNameRaw)
                    {
                        Log.Debug(() => $"LUCKY DOG CHANGED FROM {previousLuckyDogNameRaw} TO {luckyDogNameRaw}");
                    }

                    // iracing hack to allow the stock car rules to be overridden (when to call the lucky dog is different to calculating who the lucky dog actually is)
                    StockCarRule stockCarRuleApplicable = currentGameState.StockCarRulesData.stockCarRuleApplicable;
                    if (Game.IRACING)
                    {
                        stockCarRuleApplicable = iracingOverrideStockCarRule(previousGameState, currentGameState, luckyDogNameRaw, readyToCallLuckyDog);
                    }

                    int delay = Utilities.random.Next(1, 5);
                    if (!luckyDogCalled && !string.IsNullOrWhiteSpace(luckyDogNameRaw) && (stockCarRuleApplicable == StockCarRule.NEW_LUCKY_DOG || readyToCallLuckyDog))
                    {
                        luckyDogCalled = true;
                        nextGreenFlagLuckyDogCheckDue = currentGameState.Now.Add(greenFlagLuckyDogCheckInterval);
                        if (luckyDogNameRaw.Equals(currentGameState.SessionData.DriverRawName))
                        {
                            audioPlayer.playMessage(new QueuedMessage("flags/lucky_dog_is", delay + 10, secondsDelay: delay, messageFragments: MessageContents(folderRemindLuckyDog), priority: 10));
                        }
                        else
                        {
                            var lucky_dog = new List<MessageFragment>();
                            if (luckyDogNumber != null && !luckyDogNumber.Equals("-1"))
                            {
                                lucky_dog.Add(MessageFragment.Text(Opponents.folderCarNumber));
                                lucky_dog.AddRange(new CarNumber(luckyDogNumber).getMessageFragments());
                            }
                            else if (AudioPlayer.canReadName(luckyDogNameRaw))
                            {
                                lucky_dog.Add(MessageFragment.Text(DriverNameHelper.getUsableDriverName(luckyDogNameRaw)));
                            }

                            if (lucky_dog.Count > 0) {
                                lucky_dog.Add(MessageFragment.Text(folderOpponentIsLuckyDog));
                                audioPlayer.playMessage(new QueuedMessage("flags/lucky_dog_is", delay + 10, secondsDelay: delay, messageFragments: lucky_dog, abstractEvent: this, priority: 10));
                            }
                        }
                    }

                    // See if rule has changed.
                    if (previousStockCarRuleApplicable != stockCarRuleApplicable)
                    {
                        Console.WriteLine("Stock Car Rule triggered: " + stockCarRuleApplicable);
                        switch (stockCarRuleApplicable)
                        {
                            case StockCarRule.LUCKY_DOG_PASS_ON_OUTSIDE:
                                audioPlayer.playMessage(new QueuedMessage(folderLuckyDogPassOnOutside, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.LUCKY_DOG_ALLOW_TO_PASS_ON_OUTSIDE:
                                audioPlayer.playMessage(new QueuedMessage(folderLuckyDogAllowPassOnOutside, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.MOVE_CHOOSE_LANE:
                                audioPlayer.playMessage(new QueuedMessage(folderMoveToChooseLane, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.WAVE_AROUND_CATCH_END_OF_FIELD:
                                audioPlayer.playMessage(new QueuedMessage(folderWaveAroundCatchEndOfField, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.TWO_TO_GREEN:
                                audioPlayer.playMessage(new QueuedMessage(folderTwoToGreen, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.TWO_TO_GREEN_REMIND_LUCKY_DOG:
                                audioPlayer.playMessage(new QueuedMessage(folderTwoToGreenRemindLuckyDog, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.PENALTY_EOLL:
                                audioPlayer.playMessage(new QueuedMessage(folderEOLLPenalty, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.REMIND_LUCKY_DOG:
                                audioPlayer.playMessage(new QueuedMessage(folderRemindLuckyDog, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.LUCKY_DOG_PASS_ON_LEFT:
                                audioPlayer.playMessage(new QueuedMessage(folderWeAreLuckyDog, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.LUCKY_DOG_ALLOW_TO_PASS_ON_LEFT:
                                audioPlayer.playMessage(new QueuedMessage(folderAllowLuckyDogPass, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.LEADER_CHOOSE_LANE:
                                audioPlayer.playMessage(new QueuedMessage(folderLeaderChooseLane, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.WAVE_AROUND_PASS_ON_RIGHT:
                                audioPlayer.playMessage(new QueuedMessage(folderWeHaveBeenWavedAround, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                            case StockCarRule.MOVE_TO_EOLL:
                                audioPlayer.playMessage(new QueuedMessage(folderEOLLPenalty, delay + 10, secondsDelay: delay, abstractEvent: this, priority: 10));
                                break;
                        }
                    }

                    previousLuckyDogNameRaw = luckyDogNameRaw;
                    previousStockCarRuleApplicable = stockCarRuleApplicable;
                }
                else if (greenFlagLuckyDogMessageCountInSession < maxGreenFlagLuckyDogMessagesPerSession
                    && currentGameState.Now > nextGreenFlagLuckyDogCheckDue
                    && currentGameState.SessionData.CompletedLaps > 1
                    && currentGameState.SessionData.SessionPhase == SessionPhase.Green)
                {
                    // always allow calculation here since no game sends green flag lucky dog telemetry
                    var (luckyDogNameRaw, luckyDogNumber) = getLuckyDog(currentGameState, true);
                    GreenFlagLuckyDogStatus currentGreenFlagLuckyDogStatus = getGreenFlagLuckyDogPosition(currentGameState, luckyDogNameRaw);
                    if (currentGreenFlagLuckyDogStatus != GreenFlagLuckyDogStatus.NONE
                        && currentGreenFlagLuckyDogStatus != lastGreenFlagLuckyDogStatusAnnounced)
                    {
                        switch (currentGreenFlagLuckyDogStatus)
                        {
                            case GreenFlagLuckyDogStatus.WE_ARE_IN_LUCKY_DOG:
                                Console.WriteLine("Stock Car Rule triggered: " + currentGreenFlagLuckyDogStatus);
                                audioPlayer.playMessage(new QueuedMessage(folderWeAreInLuckyDogPosition, 10, abstractEvent: this, priority: 10));
                                break;
                            case GreenFlagLuckyDogStatus.PASS_FOR_LUCKY_DOG:
                            {
                                OpponentData carAhead = currentGameState.getOpponentAtOverallPosition(currentGameState.SessionData.OverallPosition - 1);
                                Console.WriteLine("Stock Car Rule triggered: " + currentGreenFlagLuckyDogStatus + " driver to pass: " + (carAhead != null ? carAhead.DriverRawName : "not found"));

                                if (carAhead != null && Game.IRACING)
                                {
                                        Log.Debug(() => $"our position = {currentGameState.SessionData.ClassPosition}, their_position = {carAhead.ClassPosition}, lead_lap = {currentGameState.getOpponentAtOverallPosition(1).CompletedLaps + 1}, our_lap = {currentGameState.SessionData.LapCount}, their_lap = {carAhead.CompletedLaps + 1}");

                                        var msg = new List<MessageFragment>();
                                        msg.Add(MessageFragment.Text(folderPassDriverForLuckyDogPositionIntro));
                                        msg.Add(MessageFragment.Text(Opponents.folderCarNumber));
                                        msg.AddRange(new CarNumber(luckyDogNumber).getMessageFragments());
                                        msg.Add(MessageFragment.Text(folderPassDriverForLuckyDogPositionOutro));
                                        audioPlayer.playMessage(new QueuedMessage("push_to_pass_lucky_dog", 6, messageFragments: msg, abstractEvent: this, priority: 10));
                                }
                                else if (carAhead != null && AudioPlayer.canReadName(carAhead.DriverRawName, false))
                                {
                                    audioPlayer.playMessage(new QueuedMessage("push_to_pass_lucky_dog", 6,
                                        messageFragments: MessageContents(folderPassDriverForLuckyDogPositionIntro, carAhead, folderPassDriverForLuckyDogPositionOutro),
                                        abstractEvent: this, priority: 10));
                                }
                                else
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderPassCarAheadForLuckyPositionDog, 6, abstractEvent: this, priority: 10));
                                }

                                break;
                            }
                        }
                        greenFlagLuckyDogMessageCountInSession++;
                        lastGreenFlagLuckyDogStatusAnnounced = currentGreenFlagLuckyDogStatus;
                        nextGreenFlagLuckyDogCheckDue = currentGameState.Now.Add(minTimeBetweenGreenFlagLuckyDogMessages);
                    }
                    else
                    {
                        nextGreenFlagLuckyDogCheckDue = currentGameState.Now.Add(greenFlagLuckyDogCheckInterval);
                    }

                    if (luckyDogNameRaw != previousLuckyDogNameRaw)
                    {
                        Log.Debug(() => $"GREEN FLAG LUCKY DOG CHANGED FROM {previousLuckyDogNameRaw} TO {luckyDogNameRaw}");
                    }
                    previousLuckyDogNameRaw = luckyDogNameRaw;
                    previousStockCarRuleApplicable = StockCarRule.NONE;
                }
            }
        }

        // (name, number) of the current lucky dog. If name is null it means there is no (known) lucky dog.
        //
        // This may be provided by telemetry or it may be calculated.
        private (string, string) getLuckyDog(GameStateData cgs, bool allowCalculation)
        {
            if (Game.IRACING && disableIracingLuckyDog)
            {
                return (null, null);
            }
            // indycar ends up being treated like stock cars a lot... but it's not the same.
            // we should probably include series like ARCA that don't have restarts
            // but that's getting really series specific and would break leagues.
            if (cgs.carClass.getClassIdentifier().Contains("INDYCAR"))
            {
                return (null, null);
            }
            if (!allowCalculation)
            {
                return (cgs.StockCarRulesData.luckyDogNameRaw, cgs.StockCarRulesData.luckyDogNumber);
            }
           
            // for multi-class we assume every class runs their own independent set of lucky dog rules.
            OpponentData leader = cgs.getOpponentAtClassPosition(1, cgs.carClass);
            float one_lap = cgs.SessionData.TrackDefinition.trackLength;
            if (leader == null || one_lap <= 0)
            {
                return (null, null);
            }
            float lead = leader.DeltaTime.totalDistanceTravelled;
            // Log.Debug(() => $"LEADER TRAVELLED {lead} for {one_lap} lap race");

            string candidate_name = null;
            string candidate_number = null;
            float candidate_distance = -1;

            float distance = cgs.SessionData.DeltaTime.totalDistanceTravelled;
            // Log.Debug(() => $"WE HAVE TRAVELLED {distance}");
            if (distance < lead - one_lap && distance > candidate_distance && !cgs.PitData.InPitlane)
            {
                candidate_name = cgs.SessionData.DriverRawName;
                candidate_number = cgs.SessionData.PlayerCarNr;
                candidate_distance = distance;
            }

            foreach (var opponent in cgs.OpponentData) {
                distance = opponent.Value.DeltaTime.totalDistanceTravelled;
                // Log.Debug(() => $"{opponent.Value.DriverRawName} HAS TRAVELLED {distance}");
                if (distance < lead - one_lap && distance > candidate_distance && !opponent.Value.InPits)
                {
                    candidate_name = opponent.Value.DriverRawName;
                    candidate_number = opponent.Value.CarNumber;
                    candidate_distance = distance;
                }
            }

            return (candidate_name, candidate_number);
        }

        // readyToCallLuckyDog should be instantatious pulse when the pace car passes the line under open pits
        private StockCarRule iracingOverrideStockCarRule(GameStateData pgs, GameStateData cgs, string luckyDogName, bool readyToCallLuckyDog)
        {
            if (disableIracingLuckyDog)
            {
                if (cgs.StockCarRulesData.stockCarRuleApplicable == StockCarRule.LUCKY_DOG_PASS_ON_OUTSIDE || cgs.StockCarRulesData.stockCarRuleApplicable == StockCarRule.LUCKY_DOG_ALLOW_TO_PASS_ON_OUTSIDE)
                {
                    // erase the telemetry
                    return StockCarRule.NONE;
                }
            }

            if (overrideIracingLuckyDog)
            {
                if (!String.IsNullOrEmpty(luckyDogName) && cgs.FlagData.isFullCourseYellow && cgs.FlagData.fcyPhase < FullCourseYellowPhase.LAST_LAP_CURRENT && readyToCallLuckyDog)
                {
                    if (luckyDogName.Equals(cgs.SessionData.DriverRawName))
                    {
                        return StockCarRule.LUCKY_DOG_PASS_ON_OUTSIDE;
                    }
                    else
                    {
                        var dog = cgs.getOpponentForName(luckyDogName);
                        if (dog == null || dog.IsBehindWithinDistance(cgs, 1, cgs.SessionData.TrackDefinition.trackLength / 2))
                        {
                            return StockCarRule.LUCKY_DOG_ALLOW_TO_PASS_ON_OUTSIDE;
                        }
                    }
                }
                if (cgs.StockCarRulesData.stockCarRuleApplicable == StockCarRule.LUCKY_DOG_PASS_ON_OUTSIDE || cgs.StockCarRulesData.stockCarRuleApplicable == StockCarRule.LUCKY_DOG_ALLOW_TO_PASS_ON_OUTSIDE)
                {
                    // we don't think there is a lucky dog rule, but iracing telemetry does...
                    return StockCarRule.NONE;
                }
            }

            return cgs.StockCarRulesData.stockCarRuleApplicable;
        }

        private GreenFlagLuckyDogStatus getGreenFlagLuckyDogPosition(GameStateData cgs, string luckyDogName)
        {
            if (luckyDogName == null || cgs.PitData.InPitlane)
            {
                return GreenFlagLuckyDogStatus.NONE;
            }
            if (luckyDogName.Equals(cgs.SessionData.DriverRawName))
            {
                return GreenFlagLuckyDogStatus.WE_ARE_IN_LUCKY_DOG;
            }

            var opponent = cgs.getOpponentInFront(cgs.carClass);
            if (opponent != null && !opponent.InPits && opponent.DriverRawName.Equals(luckyDogName))
            {
                float their_distance = opponent.DeltaTime.totalDistanceTravelled;
                float our_distance = cgs.SessionData.DeltaTime.totalDistanceTravelled;
                float one_lap = cgs.SessionData.TrackDefinition.trackLength;

                if (our_distance > their_distance - one_lap)
                {
                    return GreenFlagLuckyDogStatus.PASS_FOR_LUCKY_DOG;
                }
            }

            return GreenFlagLuckyDogStatus.NONE;
        }

        // note that these messages still play even if the yellow flag messages are disabled - I suppose they're penalty related
        private void processIllegalOvertakes(GameStateData previousGameState, GameStateData currentGameState)
        {
            // some uncertainty here - once a penalty has been applied, does the numCarsPassedIllegally reset or remain non-zero?
            if (illegalPassCarsCountAtLastAnnouncement > 0 && previousGameState.PenaltiesData.NumOutstandingPenalties > currentGameState.PenaltiesData.NumOutstandingPenalties)
            {
                Console.WriteLine("numCarsPassedIllegally has changed from " + illegalPassCarsCountAtLastAnnouncement +
                    " to  " + currentGameState.FlagData.numCarsPassedIllegally + " and penalty count has increased");
                hasAlreadyWarnedAboutIllegalPass = false;
                // If we have a new penalty delay the next check for a while
                nextIllegalPassWarning = currentGameState.Now + TimeSpan.FromSeconds(30);
            }
            else
            {
                nextIllegalPassWarning = currentGameState.Now + illegalPassRepeatInterval;
                if (currentGameState.FlagData.numCarsPassedIllegally > 0)
                {
                    if (hasAlreadyWarnedAboutIllegalPass)
                    {
                        if (currentGameState.FlagData.numCarsPassedIllegally == 1)
                        {
                            // don't allow any other message to override this one:
                            audioPlayer.playMessageImmediately(new QueuedMessage("give_position_back_repeat", 3,
                                messageFragments: MessageContents(folderGiveOnePositionsBackNextWarning), type: SoundType.IMPORTANT_MESSAGE, priority: 10));
                        }
                        else
                        {
                            // don't allow any other message to override this one:
                            audioPlayer.playMessageImmediately(new QueuedMessage("give_positions_back_repeat", 3,
                                messageFragments: MessageContents(folderGivePositionsBackNextWarningIntro, currentGameState.FlagData.numCarsPassedIllegally, folderGivePositionsBackNextWarningOutro),
                                type: SoundType.IMPORTANT_MESSAGE, priority: 10));
                        }
                    }
                    else
                    {
                        hasAlreadyWarnedAboutIllegalPass = true;
                        if (currentGameState.FlagData.numCarsPassedIllegally == 1)
                        {
                            // don't allow any other message to override this one:
                            audioPlayer.playMessageImmediately(new QueuedMessage("give_position_back", 3,
                                messageFragments: MessageContents(folderGiveOnePositionBackFirstWarning), type: SoundType.IMPORTANT_MESSAGE, priority: 10));
                        }
                        else
                        {
                            // don't allow any other message to override this one:
                            audioPlayer.playMessageImmediately(new QueuedMessage("give_positions_back", 0,
                                messageFragments: MessageContents(folderGivePositionsBackFirstWarningIntro, currentGameState.FlagData.numCarsPassedIllegally, folderGivePositionsBackFirstWarningOutro),
                                type: SoundType.IMPORTANT_MESSAGE, priority: 10));
                        }
                    }
                }
                else
                {
                    // more guesswork :(
                    if (currentGameState.PenaltiesData.NumOutstandingPenalties == 0)
                    {
                        // don't allow any other message to override this one:
                        audioPlayer.playMessageImmediately(new QueuedMessage("give_positions_back_completed", 5,
                            messageFragments: MessageContents(folderGivePositionsBackCompleted), type: SoundType.IMPORTANT_MESSAGE, priority: 10));
                    }
                    hasAlreadyWarnedAboutIllegalPass = false;
                }
            }
        }

        private void gameDataYellowFlagImplementation(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (previousGameState != null)
            {
                Boolean playerStartedSector3 = previousGameState.SessionData.SectorNumber == 2 && currentGameState.SessionData.SectorNumber == 3;
                Boolean leaderStartedSector3 = previousGameState.SessionData.LeaderSectorNumber == 2 && currentGameState.SessionData.LeaderSectorNumber == 3;
                if (announceFCYPhase(previousGameState.FlagData.fcyPhase, currentGameState.FlagData.fcyPhase, currentGameState.Now, playerStartedSector3))
                {
                    lastFCYAnnounced = currentGameState.FlagData.fcyPhase;
                    lastFCYAccountedTime = currentGameState.Now;
                    int delay = Utilities.random.Next(1, 4);
                    switch (currentGameState.FlagData.fcyPhase)
                    {
                        case FullCourseYellowPhase.PENDING:
                            // don't allow any other message to override this one:
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                // if we have info about the safety car we want to use it else we will skip to default and call out safetycar along with FCY
                                if (Game.IRACING && currentGameState.SafetyCarData.fcySafetyCarCallsEnabled)
                                {
                                    audioPlayer.playMessageImmediately(new QueuedMessage(folderFCYellowStartNoSafetyCar, 0,
                                        abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                                }
                                else
                                {
                                    audioPlayer.playMessageImmediately(new QueuedMessage(folderFCYellowStart, 0,
                                        abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                                }
                            }
                            // start working out who's gone off
                            if (enableOpponentCrashMessages)
                            {
                                findInitialIncidentCandidateKeys(-1, currentGameState.OpponentData);
                                playerClassPositionAtStartOfIncident = currentGameState.SessionData.ClassPosition;
                                nextIncidentDriversCheck = currentGameState.Now + incidentDriversCheckInterval;
                                getInvolvedInIncidentAttempts = 0;
                                driversInvolvedInCurrentIncident.Clear();
                            }
                            break;
                        case FullCourseYellowPhase.PITS_CLOSED:
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderFCYellowPitsClosed,
                                    delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                            }
                            break;
                        case FullCourseYellowPhase.PITS_OPEN_LEAD_LAP_VEHICLES:
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderFCYellowPitsOpenLeadLapCars,
                                    delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                            }
                            break;
                        case FullCourseYellowPhase.PITS_OPEN:
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                // WIP AMS2 logic - state goes RACING -> PITS_OPEN with nothing in between so queue 'yellow' then 'pit open' some time later
                                if (Game.AMS2 && previousGameState.FlagData.fcyPhase == FullCourseYellowPhase.RACING)
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderFCYellowStart,
                                        5, secondsDelay: 0, abstractEvent: this, priority: 10));
                                    audioPlayer.playMessage(new QueuedMessage(folderFCYellowPitsOpen,
                                        15, secondsDelay: 8, abstractEvent: this, priority: 10));
                                }
                                else
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderFCYellowPitsOpen,
                                        delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                                }
                            }
                            break;
                        case FullCourseYellowPhase.IN_PROGRESS:
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderFCYellowInProgress,
                                    delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                            }
                            break;
                        case FullCourseYellowPhase.LAST_LAP_NEXT:
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderFCYellowLastLapNext,
                                    delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                            }
                            break;
                        case FullCourseYellowPhase.LAST_LAP_CURRENT:
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderFCYellowLastLapCurrent,
                                    delay + 6, secondsDelay: delay, abstractEvent: this, priority: 10));
                            }
                            break;
                        case FullCourseYellowPhase.RACING:
                            // don't allow any other message to override this one:
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage(folderFCYellowGreenFlag, 0, type: SoundType.IMPORTANT_MESSAGE, priority: 10));
                            }
                            break;
                        default:
                            break;
                    }
                }
                else if ((currentGameState.FlagData.fcyPhase == FullCourseYellowPhase.LAST_LAP_CURRENT && leaderStartedSector3 && !Game.IRACING) ||
                    (Game.IRACING && !currentGameState.SafetyCarData.fcySafetyCarCallsEnabled && 
                    currentGameState.FlagData.fcyPhase == FullCourseYellowPhase.LAST_LAP_CURRENT && leaderStartedSector3))
                {
                    // last sector, safety car coming in
                    // don't allow any other message to override this one:
                    if (CrewChief.yellowFlagMessagesEnabled)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderFCYellowPrepareForGreen, 0,
                            abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                    }
                }
                else if ((currentGameState.FlagData.fcyPhase == FullCourseYellowPhase.PENDING ||
                              currentGameState.FlagData.fcyPhase == FullCourseYellowPhase.PITS_CLOSED) && 
                          currentGameState.Now > nextIncidentDriversCheck)
                {
                    if (enableOpponentCrashMessages)
                    {
                        if (getInvolvedInIncidentAttempts >= maxFCYGetInvolvedInIncidentAttempts)
                        {
                            // we've collected as many involved drivers as we're going to get, so report them
                            reportYellowFlagDrivers(currentGameState.OpponentData, currentGameState.SessionData.TrackDefinition);
                            nextIncidentDriversCheck = DateTime.MaxValue;
                            playerClassPositionAtStartOfIncident = int.MaxValue;
                            incidentCandidates.Clear();
                            getInvolvedInIncidentAttempts = 0;
                            driversInvolvedInCurrentIncident.Clear();
                        }
                        else
                        {
                            // get more involved drivers and schedule the next check
                            nextIncidentDriversCheck = currentGameState.Now + incidentDriversCheckInterval;
                            driversInvolvedInCurrentIncident.AddRange(getInvolvedIncidentCandidates(-1, currentGameState.OpponentData));
                        }
                        getInvolvedInIncidentAttempts++;
                    }
                }
                else
                {
                    // Console.WriteLine("Track lap distance: "  + currentGameState.PositionAndMotionData.DistanceRoundTrack + 
                    //    " distanceToNearestIncident: " + currentGameState.FlagData.distanceToNearestIncident);
                    // local yellows
                    // note the 'allSectorsAreGreen' check - we can be under local yellow with no yellow sectors in the hairpin at Macau
                    if (!isUnderLocalYellow && currentGameState.FlagData.isLocalYellow && !allSectorsAreGreen(currentGameState.FlagData))
                    {
                        //Console.WriteLine("FLAG_DEBUG: local yellow at " + currentGameState.Now.ToString("HH:mm:ss"));
                        isUnderLocalYellow = true;
                        // ensure the last state is updated, even if we don't actually read the transition
                        lastSectorFlags[currentGameState.SessionData.SectorNumber - 1] = FlagEnum.YELLOW;

                        nextIllegalPassWarning = currentGameState.Now;
                        // we might not have warned of an incident ahead - no point in warning about it now we've actually reached it
                        hasWarnedOfUpcomingIncident = true;
                        waitingToWarnOfIncident = false;
                        Dictionary<String, Object> validationData = new Dictionary<String, Object>();
                        validationData.Add(validationIsLocalYellowKey, true);
                        validationData.Add(isValidatingSectorMessage, false);
                        if (CrewChief.yellowFlagMessagesEnabled && !currentGameState.PitData.InPitlane && !hasReportedIsUnderLocalYellow)
                        {
                            //Console.WriteLine("FLAG_DEBUG: queuing local yellow " + " at " + currentGameState.Now.ToString("HH:mm:ss"));
                            // immediate to prevent it being delayed by the hard-parts logic
                            audioPlayer.playMessageImmediately(new QueuedMessage(localFlagChangeMessageKey + "_yellow", 3, secondsDelay: 1,
                                messageFragments: MessageContents(folderLocalYellow), abstractEvent: this, validationData: validationData, type: SoundType.IMPORTANT_MESSAGE, priority: 10));
                        }
                    }
                    else if (isUnderLocalYellow && !currentGameState.FlagData.isLocalYellow)
                    {
                        //Console.WriteLine("FLAG_DEBUG: local green at " + currentGameState.Now.ToString("HH:mm:ss"));
                        isUnderLocalYellow = false;
                        // we've passed the incident so allow warnings of other incidents approaching
                        hasWarnedOfUpcomingIncident = false;
                        waitingToWarnOfIncident = false;
                        lastReportedOvertakeAllowed = PassAllowedUnderYellow.NO_DATA;
                        Dictionary<String, Object> validationData = new Dictionary<String, Object>();
                        validationData.Add(validationIsLocalYellowKey, false);
                        validationData.Add(isValidatingSectorMessage, false);
                        if (CrewChief.yellowFlagMessagesEnabled && !currentGameState.PitData.InPitlane && hasReportedIsUnderLocalYellow)
                        {
                            //Console.WriteLine("FLAG_DEBUG: queuing local green " + " at " + currentGameState.Now.ToString("HH:mm:ss"));
                            audioPlayer.playMessageImmediately(
                                new QueuedMessage(localFlagChangeMessageKey + "_clear", 3, secondsDelay: 1,
                                    messageFragments: MessageContents(folderLocalYellowClear), abstractEvent: this, validationData: validationData, type: SoundType.IMPORTANT_MESSAGE, priority: 10));
                        }
                    }
                    else if (allSectorsAreGreen(currentGameState.FlagData))
                    {
                        // if all the sectors are clear the local and warning booleans. This ensures we don't sit waiting for a 'clear' that never comes.
                        // Console.WriteLine("FLAG_DEBUG: all sectors green at " + currentGameState.Now.ToString("HH:mm:ss"));
                        isUnderLocalYellow = false;
                        hasWarnedOfUpcomingIncident = false;
                        waitingToWarnOfIncident = false;
                        lastReportedOvertakeAllowed = PassAllowedUnderYellow.NO_DATA;
                    }
                    // This produces false-positives. Not sure why - TODO: work out what the issue is here - perhaps
                    // the data doesn't contain what I think it contains
                    /*else if (!isUnderLocalYellow && !hasWarnedOfUpcomingIncident)
                    {
                        if (waitingToWarnOfIncident)
                        {
                            if (shouldWarnOfUpComingYellow(currentGameState))
                            {
                                if (currentGameState.Now > incidentAheadSettledTime)
                                {
                                    waitingToWarnOfIncident = false;
                                    hasWarnedOfUpcomingIncident = true;
                                    if (CrewChief.yellowFlagMessagesEnabled && !currentGameState.PitData.InPitlane)
                                    {
                                        audioPlayer.playMessageImmediately(new QueuedMessage(folderLocalYellowAhead, 0));
                                    }
                                }
                            }
                            else
                            {
                                waitingToWarnOfIncident = false;
                            }
                        }
                        else if (shouldWarnOfUpComingYellow(currentGameState))
                        {
                            waitingToWarnOfIncident = true;
                            incidentAheadSettledTime = currentGameState.Now + incidentAheadSettlingTime;
                        }
                    }*/
                    // sector yellows
                    for (int i = 0; i < 3; i++)
                    {
                        //  Yellow Flags:
                        // * Only announce Yellow if
                        //      - Not in pits
                        //      - Enough time ellapsed since last announcement
                        //      - Yellow is in current or next sector (relative to player's sector).
                        //      - For current sector, sometimes announce yellow without sector number.
                        // * Only announce Clear message if
                        //      - Not in pits
                        //      - Enough time passed since Yellow was announced
                        //      - Yellow went away in or next sector (relative to player's sector).
                        //      - Announce delayed message and drop it if sector or sector flag changes

                        // we've announced this, so see if we can add more information
                        if (enableOpponentCrashMessages && i == waitingForCrashedDriverInSector && 
                            currentGameState.Now > nextIncidentDriversCheck)
                        {
                            if (getInvolvedInIncidentAttempts >= maxLocalYellowGetInvolvedInIncidentAttempts)
                            {
                                // we've collected as many involved drivers as we're going to get, so report them
                                reportYellowFlagDrivers(currentGameState.OpponentData, currentGameState.SessionData.TrackDefinition);
                                nextIncidentDriversCheck = DateTime.MaxValue;
                                playerClassPositionAtStartOfIncident = int.MaxValue;
                                incidentCandidates.Clear();
                                getInvolvedInIncidentAttempts = 0;
                                driversInvolvedInCurrentIncident.Clear();
                                waitingForCrashedDriverInSector = -1;
                            }
                            else
                            {
                                // get more involved drivers and schedule the next check
                                nextIncidentDriversCheck = currentGameState.Now + incidentDriversCheckInterval;
                                driversInvolvedInCurrentIncident.AddRange(getInvolvedIncidentCandidates(waitingForCrashedDriverInSector + 1, currentGameState.OpponentData));
                            }
                            getInvolvedInIncidentAttempts++;
                        }

                        FlagEnum sectorFlag = currentGameState.FlagData.sectorFlags[i];
                        if (sectorFlag != lastSectorFlags[i] && (reportYellowsInAllSectors || isCurrentSector(currentGameState, i) || isNextSector(currentGameState, i)))
                        {
                            // Console.WriteLine("FLAG_DEBUG: sector " + (i + 1) + " " + sectorFlag + " at " + currentGameState.Now.ToString("HH:mm:ss"));
                            lastSectorFlags[i] = sectorFlag;
                            Dictionary<String, Object> validationData = new Dictionary<String, Object>();
                            validationData.Add(validationSectorNumberKey, i);
                            validationData.Add(validationSectorFlagKey, sectorFlag);
                            validationData.Add(isValidatingSectorMessage, true);
                            if ((sectorFlag == FlagEnum.YELLOW || sectorFlag == FlagEnum.DOUBLE_YELLOW) && 
                                currentGameState.Now > lastSectorFlagsReportedTime[i].Add(minTimeBetweenNewYellowFlagMessages))
                            {
                                // Sector i changed to yellow - don't announce this if we're in a local yellow
                                if (!currentGameState.FlagData.isLocalYellow && lastSectorFlagsReported[i] != sectorFlag && 
                                    !incidentIsInCurrentSectorButBehind(i + 1, currentGameState))
                                {                                            
                                    hasAlreadyWarnedAboutIllegalPass = false;
                                    
                                    // don't call sector yellow if we've in a local yellow
                                    if (!Game.RACE_ROOM && isCurrentSector(currentGameState, i) && 4 > Utilities.random.NextDouble() * 10)
                                    {
                                        // If in current, sometimes announce without sector number.
                                        if (CrewChief.yellowFlagMessagesEnabled && !currentGameState.PitData.InPitlane)
                                        {
                                            //Console.WriteLine("FLAG_DEBUG: queuing sector " + (i + 1) + " " + sectorFlag + " at " + currentGameState.Now.ToString("HH:mm:ss"));
                                            // immediate to prevent it being delayed by the hard-parts logic
                                            audioPlayer.playMessageImmediately(new QueuedMessage(sectorFlagChangeMessageKeyStart + (i + 1), 6, secondsDelay: 3,
                                                messageFragments: MessageContents(sectorFlag == FlagEnum.YELLOW ? folderYellowFlag : folderDoubleYellowFlag), 
                                                abstractEvent: this, validationData: validationData, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                                        }
                                    }
                                    else if (CrewChief.yellowFlagMessagesEnabled && !currentGameState.PitData.InPitlane)
                                    {
                                        //Console.WriteLine("FLAG_DEBUG: queuing sector " + (i + 1) + " " + sectorFlag + " at " + currentGameState.Now.ToString("HH:mm:ss"));
                                        // immediate to prevent it being delayed by the hard-parts logic
                                        audioPlayer.playMessageImmediately(new QueuedMessage(sectorFlagChangeMessageKeyStart + (i + 1), 6, secondsDelay: 3,
                                            messageFragments: MessageContents(sectorFlag == FlagEnum.YELLOW ? folderYellowFlagSectors[i] : folderDoubleYellowFlagSectors[i]),
                                            abstractEvent: this, validationData: validationData, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                                    }
                                }
                                if (enableOpponentCrashMessages)
                                {
                                    // start working out who's gone off
                                    findInitialIncidentCandidateKeys(i + 1, currentGameState.OpponentData);
                                    playerClassPositionAtStartOfIncident = currentGameState.SessionData.ClassPosition;
                                    nextIncidentDriversCheck = currentGameState.Now + incidentDriversCheckInterval;
                                    getInvolvedInIncidentAttempts = 0;
                                    driversInvolvedInCurrentIncident.Clear();
                                    waitingForCrashedDriverInSector = i;
                                }
                            }
                            else if (sectorFlag == FlagEnum.GREEN)
                            {
                                // Sector i changed to green.  Check time since last announcement.
                                if (lastSectorFlagsReported[i] != sectorFlag &&
                                    currentGameState.Now > lastSectorFlagsReportedTime[i].Add(timeBetweenYellowAndClearFlagMessages))
                                {
                                    if (CrewChief.yellowFlagMessagesEnabled && !currentGameState.PitData.InPitlane)
                                    {
                                        // hack the message key if we're reporting green in the current sector. This prevents
                                        // a duplicate clear for local sectors
                                        //Console.WriteLine("FLAG_DEBUG: queuing sector " + (i + 1) + " " + sectorFlag + " at " + currentGameState.Now.ToString("HH:mm:ss"));
                                        String messageKey = i == currentGameState.SessionData.SectorNumber - 1 ? localFlagChangeMessageKey+ "_clear" : sectorFlagChangeMessageKeyStart + (i + 1);
                                        audioPlayer.playMessageImmediately(new QueuedMessage(messageKey, 5, secondsDelay: Utilities.random.Next(2, 4),
                                            messageFragments: MessageContents(folderGreenFlagSectors[i]), 
                                            abstractEvent: this, validationData: validationData, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                                    }
                                }
                            }
                        }
                    }
                }                

                if (isUnderLocalYellow && reportAllowedOvertakesUnderYellow)
                {
                    if (currentGameState.FlagData.canOvertakeCarInFront == PassAllowedUnderYellow.YES
                        && lastReportedOvertakeAllowed == PassAllowedUnderYellow.NO && lastOvertakeAllowedReportTime.Add(TimeSpan.FromSeconds(3)) < currentGameState.Now)
                    {
                        if (CrewChief.yellowFlagMessagesEnabled)
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage(folderClearToOvertake, 2, abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                        }
                        lastReportedOvertakeAllowed = PassAllowedUnderYellow.YES;
                        lastOvertakeAllowedReportTime = currentGameState.Now;
                    }
                    else if (currentGameState.FlagData.canOvertakeCarInFront == PassAllowedUnderYellow.NO
                        && lastReportedOvertakeAllowed == PassAllowedUnderYellow.YES && lastOvertakeAllowedReportTime.Add(TimeSpan.FromSeconds(3)) < currentGameState.Now)
                    {
                        if (CrewChief.yellowFlagMessagesEnabled)
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage(folderNoOvertaking, 2, abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                        }
                        lastReportedOvertakeAllowed = PassAllowedUnderYellow.NO;
                        lastOvertakeAllowedReportTime = currentGameState.Now;                                               
                    }
                }
            }
        }

        private Boolean incidentIsInCurrentSectorButBehind(int sector, GameStateData currentGameState) 
        {
            return currentGameState.SessionData.SectorNumber == sector && 
                currentGameState.FlagData.distanceToNearestIncident > currentGameState.SessionData.TrackDefinition.trackLength - currentGameState.PositionAndMotionData.DistanceRoundTrack;
        }

        private Boolean allSectorsAreGreen(FlagData flagData)
        {
            return flagData.sectorFlags[0] == FlagEnum.GREEN && flagData.sectorFlags[1] == FlagEnum.GREEN &&
                        flagData.sectorFlags[2] == FlagEnum.GREEN;
        }

        private Boolean shouldWarnOfUpComingYellow(GameStateData gameState)
        {
            return gameState != null && gameState.FlagData.distanceToNearestIncident > 0 &&
                gameState.FlagData.distanceToNearestIncident > minDistanceToWarnOfLocalYellow && 
                    gameState.FlagData.distanceToNearestIncident < maxDistanceToWarnOfLocalYellow;
        }

        private bool isCurrentSector(GameStateData currentGameState, int sectorIndex)
        {
            return currentGameState.SessionData.SectorNumber == sectorIndex + 1;
        }

        private bool isNextSector(GameStateData currentGameState, int sectorIndex)
        {
            int nextSector = currentGameState.SessionData.SectorNumber == 3 ? 1 : currentGameState.SessionData.SectorNumber + 1;
            return nextSector == sectorIndex + 1;
        }

        private Boolean announceFCYPhase(FullCourseYellowPhase previousPhase, FullCourseYellowPhase currentPhase, DateTime now, Boolean startedSector3)
        {
            // reminder announcements for pit status at the start of sector 3, if we've not announce it for a while
            return (previousPhase != currentPhase && currentPhase != lastFCYAnnounced) ||
                ((currentPhase == FullCourseYellowPhase.PITS_CLOSED ||
                 currentPhase == FullCourseYellowPhase.PITS_OPEN_LEAD_LAP_VEHICLES ||
                 currentPhase == FullCourseYellowPhase.PITS_OPEN ||
                 currentPhase == FullCourseYellowPhase.IN_PROGRESS) && now > lastFCYAccountedTime + fcyStatusReminderMinTime && startedSector3);
        }

        /**
         * Used by all other games, legacy code.
         */
        private void improvisedYellowFlagImplementation(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (currentGameState.PositionAndMotionData.CarSpeed < 1)
            {
                return;
            }
            else if (currentGameState.SessionData.iRacingLoneQualify)
            {
                return;
            }
            else if (!currentGameState.PitData.InPitlane && currentGameState.SessionData.Flag == FlagEnum.YELLOW)
            {
                if (currentGameState.Now > disableYellowFlagUntil)
                {
                    disableYellowFlagUntil = currentGameState.Now.Add(timeBetweenYellowFlagMessages + TimeSpan.FromSeconds(Utilities.random.Next(0, 11)));
                    if (CrewChief.yellowFlagMessagesEnabled
                        // just cars stopping after their race, even if we still need to finish
                        && currentGameState.SessionData.SessionPhase < SessionPhase.Checkered)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderYellowFlag, 3, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 10));
                    }
                }
            }
            else if (!currentGameState.PitData.InPitlane && currentGameState.SessionData.Flag == FlagEnum.DOUBLE_YELLOW)
            {
                if (currentGameState.Now > disableYellowFlagUntil &&
                    // AMS specific hack until RF2 FCY stuff is ported - don't spam the double yellow during caution periods, just report it once per lap
                    (!Game.RF1 || currentGameState.SessionData.IsNewLap))
                {
                    disableYellowFlagUntil = currentGameState.Now.Add(timeBetweenYellowFlagMessages + TimeSpan.FromSeconds(Utilities.random.Next(0, 11)));
                    if (CrewChief.yellowFlagMessagesEnabled)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderDoubleYellowFlag, 3, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 10));
                    }
                }
            }
            // now check for stopped cars
            if (simpleIncidentDetectionSessions == SIMPLE_INCIDENT_DETECTION_SESSIONS.ALL_SESSIONS || 
                (simpleIncidentDetectionSessions == SIMPLE_INCIDENT_DETECTION_SESSIONS.RACE_ONLY && currentGameState.SessionData.SessionType == SessionType.Race))
            {
                if (waitingForCrashedDriverInCorner == null)
                {
                    // get the first stopped car and his corner
                    foreach (KeyValuePair<String, OpponentData> entry in currentGameState.OpponentData)
                    {
                        String opponentId = entry.Key;
                        OpponentData opponent = entry.Value;

                        // this is typically people parking after passing the line, we may miss the occassional call if we are just ahead
                        // of the leader as they pass the line and we need to go one more lap under checkered conditions but that seems
                        // a fair price to pay to avoid this very common noise.
                        if ((currentGameState.SessionData.SessionPhase == SessionPhase.Checkered && opponent.CurrentSectorNumber == 1)
                            || (currentGameState.SessionData.IsLastLap && opponent.CurrentSectorNumber < currentGameState.SessionData.SectorNumber))
                        {
                            continue;
                        }

                        Boolean isApproaching = false;
                        float distanceToIncident = float.MaxValue;
                        if (opponent.DistanceRoundTrack > currentGameState.PositionAndMotionData.DistanceRoundTrack)
                        {
                            distanceToIncident = opponent.DistanceRoundTrack - currentGameState.PositionAndMotionData.DistanceRoundTrack;
                        }
                        else
                        {
                            distanceToIncident = opponent.DistanceRoundTrack -
                                (currentGameState.PositionAndMotionData.DistanceRoundTrack - currentGameState.SessionData.TrackDefinition.trackLength);

                        }
                        isApproaching = distanceToIncident < 1000;
                        String landmark = opponent.stoppedInLandmark;
                        if (landmark == null)
                        {
                            // this opponent isn't stopped so clear him from the dict of already announced opponent -> corner
                            alreadyAnnouncedStoppedOpponentCorners.Remove(opponent);
                        }
                        // is this car in an interesting part of the track?     
                        if (landmark != null && !landmark.Equals(currentGameState.SessionData.stoppedInLandmark))
                        {                                                 
                            // are we fighting with him and can we call him by name?
                            Boolean isInteresting = WatchedOpponents.watchedOpponentKeys.Contains(entry.Key);
                            if (!isInteresting && CarData.IsCarClassEqual(currentGameState.carClass, opponent.CarClass) && currentGameState.SessionData.ClassPosition < 1000 && opponent.ClassPosition < 1000)
                            {
                                isInteresting = Math.Abs(currentGameState.SessionData.ClassPosition - opponent.ClassPosition) <= 2 &&
                                (AudioPlayer.canReadName(opponent.DriverRawName, false) || opponent.ClassPosition <= folderPositionHasGoneOff.Length) && 
                                currentGameState.SessionData.SessionType == SessionType.Race; // only call out interesting incidents in race sessions 
                            }
                            DateTime incidentWarningTime = DateTime.MinValue;
                            if ((isApproaching || isInteresting) &&
                                (!incidentWarnings.TryGetValue(landmark, out incidentWarningTime) || incidentWarningTime + incidentRepeatFrequency < currentGameState.Now))
                            {
                                waitingForCrashedDriverInCorner = landmark;
                                driversCrashedInCorner.Add(opponentId);
                                // if the gap to the incident is in front and the incident delay is set higher set the timer so we warn next update interval. 
                                if (Math.Abs(distanceToIncident) < 200 && isApproaching)
                                {
                                    waitingForCrashedDriverInCornerFinishTime = currentGameState.Now;
                                }
                                else
                                {
                                    waitingForCrashedDriverInCornerFinishTime = currentGameState.Now + TimeSpan.FromMilliseconds(simpleIncidentReportDelay);
                                }                                
                                break;
                            }
                        }
                    }
                }
                else if (currentGameState.Now < waitingForCrashedDriverInCornerFinishTime)
                {
                    // get more stopped cars
                    foreach (KeyValuePair<String, OpponentData> entry in currentGameState.OpponentData)
                    {
                        OpponentData opponent = entry.Value;
                        String landmark = opponent.stoppedInLandmark;
                        if (landmark == waitingForCrashedDriverInCorner && !driversCrashedInCorner.Contains(entry.Key))
                        {
                            driversCrashedInCorner.Add(entry.Key);
                        }
                    }
                }
                else
                {
                    // finished waiting, get the results and play 'em
                    List<OpponentData> crashedOpponents = new List<OpponentData>();
                    foreach (String opponentKey in driversCrashedInCorner)
                    {
                        if (currentGameState.OpponentData.ContainsKey(opponentKey) && !currentGameState.OpponentData[opponentKey].InPits)
                        {
                            // don't add this opponent if we've already announced that they've stopped in this corner.
                            // This should catch cases where a broken car is just sat by the side of the track lap after lap
                            bool alreadyAnnounced = alreadyAnnouncedStoppedOpponentCorners.TryGetValue(currentGameState.OpponentData[opponentKey], out string stoppedIn)
                                && stoppedIn == waitingForCrashedDriverInCorner;
                            if (alreadyAnnounced)
                            {
                                Console.WriteLine("Driver " + opponentKey + " is still stopped in " + waitingForCrashedDriverInCorner + " but this call has already been made");
                            }
                            else
                            {
                                crashedOpponents.Add(currentGameState.OpponentData[opponentKey]);
                            }
                        }
                    }
                    incidentWarnings[waitingForCrashedDriverInCorner] = currentGameState.Now;
                    if (crashedOpponents.Count >= pileupDriverCount)
                    {
                        // report pileup
                        if (CrewChief.yellowFlagMessagesEnabled)
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage("pileup_in_corner", 6, secondsDelay: 0,
                                messageFragments: MessageContents(folderPileupInCornerIntro, "corners/" +
                                waitingForCrashedDriverInCorner), abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 0));
                        }
                    }
                    else
                    {
                        List<OpponentData> opponentNamesToRead = new List<OpponentData>();
                        int positionToRead = -1;
                        if (enableOpponentCrashMessages)
                        {
                            foreach (OpponentData opponent in crashedOpponents)
                            {
                                if (CarData.IsCarClassEqual(opponent.CarClass, currentGameState.carClass))
                                {
                                    if (AudioPlayer.canReadName(opponent.DriverRawName, false))
                                    {
                                        opponentNamesToRead.Add(opponent);
                                    }
                                    else if (opponent.ClassPosition <= folderPositionHasGoneOff.Length && positionToRead == -1 && opponent.ClassPosition > 0)
                                    {
                                        positionToRead = opponent.ClassPosition;
                                    }
                                }
                            }
                        }
                        if (opponentNamesToRead.Count > 0)
                        {
                            // one or more names to read
                            List<MessageFragment> messageContents = new List<MessageFragment>();
                            messageContents.AddRange(MessageContents(folderIncidentInCornerIntro));
                            messageContents.AddRange(MessageContents("corners/" + waitingForCrashedDriverInCorner));
                            messageContents.AddRange(MessageContents(folderIncidentInCornerDriverIntro));
                            int andIndex = opponentNamesToRead.Count > 1 ? opponentNamesToRead.Count - 1 : -1;
                            List<String> namesToDebug = new List<string>();
                            for (int i = 0; i < opponentNamesToRead.Count; i++)
                            {
                                // record that we've called this driver / corner combo so we don't call it again (unless he gets going)
                                alreadyAnnouncedStoppedOpponentCorners[opponentNamesToRead[i]] = waitingForCrashedDriverInCorner;
                                if (i == andIndex)
                                {
                                    messageContents.AddRange(MessageContents(folderAnd));
                                }
                                namesToDebug.Add(opponentNamesToRead[i].DriverRawName);
                                messageContents.AddRange(MessageContents(opponentNamesToRead[i]));
                            }
                            Console.WriteLine("Incident in " + waitingForCrashedDriverInCorner + " for drivers " + String.Join(",", namesToDebug));
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage("incident_corner_with_driver", 4,
                                    messageFragments: messageContents, abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 0));
                            }
                        }
                        else if (positionToRead != -1)
                        {
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage("incident_corner_with_driver", 4,
                                    messageFragments: MessageContents(folderPositionHasGoneOffIn[positionToRead - 1], "corners/" + waitingForCrashedDriverInCorner), abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 0));
                            }
                        }
                        else
                        {
                            Console.WriteLine("Incident in " + waitingForCrashedDriverInCorner);
                            if (CrewChief.yellowFlagMessagesEnabled)
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage("incident_corner", 5,
                                    messageFragments: MessageContents(folderIncidentInCornerIntro, "corners/" + waitingForCrashedDriverInCorner), abstractEvent: this, type: SoundType.CRITICAL_MESSAGE, priority: 0));
                            }
                        }
                    }
                    waitingForCrashedDriverInCorner = null;
                    driversCrashedInCorner.Clear();
                }
            }
        }

        void findInitialIncidentCandidateKeys(int flagSector, Dictionary<string, OpponentData> opponents)
        {
            incidentCandidates.Clear();
            foreach (KeyValuePair<string, OpponentData> entry in opponents)
            {
                string opponentKey = entry.Key;
                OpponentData opponentData = entry.Value;
                if (opponentData.DistanceRoundTrack == 0 || opponentData.ClassPosition <= 0 || opponentData.ClassPosition >= 1000)
                {
                    // fuck's sake... pCARS2's data *and iRacing* data is so shit. 
                    // for pCars2, DistanceRoundTrack value will be 0 when a car enters the pitlane.
                    // for iRacing ClassPosition can be 0 or -1 or 1000 in some edge cases where the position logic screws up,
                    // hopefully this will never happen but this check is harmless
                    continue;
                }
                if ((flagSector == -1 || opponentData.CurrentSectorNumber == flagSector) && !opponentData.InPits)
                {
                    LapData lapData = opponentData.getCurrentLapData();
                    incidentCandidates.Add(new IncidentCandidate(opponentKey, opponentData.DistanceRoundTrack, opponentData.ClassPosition,
                        opponentData.OverallPosition, lapData == null || lapData.IsValid));
                }
            }
        }

        // get incident candidates who are involved - they've lost lots of position or haven't really moved since the last check
        List<NamePositionPair> getInvolvedIncidentCandidates(int flagSector, Dictionary<string, OpponentData> opponents)
        {
            List<NamePositionPair> involvedDrivers = new List<NamePositionPair>();
            List<IncidentCandidate> remainingIncidentCandidates = new List<IncidentCandidate>();
            foreach (IncidentCandidate incidentCandidate in incidentCandidates)
            {
                OpponentData opponent = null;
                if (opponents.TryGetValue(incidentCandidate.opponentDataKey, out opponent))
                {
                    if (opponent.DistanceRoundTrack == 0)
                    {
                        // fuck's sake... pCARS2's data is so shit. This value will be 0 when a car enters the pitlane.
                        continue;
                    }
                    if (flagSector == -1 || opponent.CurrentSectorNumber == flagSector)
                    {
                        if ((Math.Abs(opponent.DistanceRoundTrack - incidentCandidate.distanceRoundTrackAtStartOfIncident) < maxDistanceMovedForYellowAnnouncement) ||
                                opponent.OverallPosition > incidentCandidate.overallPositionAtStartOfIncident + 3)
                        {
                            // this guy is in the same sector as the yellow but has only travelled 10m in 2 seconds or has lost a load of places so he's probably involved.
                            // Only add him if we've not reported him already in this spot on the track
                            Boolean canAdd = true;
                            float distanceRoundTrackAtIncident = -1.0f;
                            if (lastIncidentPositionForOpponents.TryGetValue(opponent.DriverRawName, out distanceRoundTrackAtIncident))
                            {
                                // we've already reported on this guy in this session - if he's not really moved since this report, don't report him again

                                // this check doesn't make sense when the incident is within 20m of the start line, but it's an edge case and this check isn't
                                // really essential anyway so let's not worry about it
                                if (Math.Abs(opponent.DistanceRoundTrack - distanceRoundTrackAtIncident) < 20)
                                {
                                    canAdd = false;
                                }
                            }
                            if (canAdd)
                            {
                                lastIncidentPositionForOpponents[opponent.DriverRawName] = opponent.DistanceRoundTrack;
                                involvedDrivers.Add(new NamePositionPair(opponent.DriverRawName, incidentCandidate.classPositionAtStartOfIncident,
                                    incidentCandidate.overallPositionAtStartOfIncident, opponent.DistanceRoundTrack, AudioPlayer.canReadName(opponent.DriverRawName, false), 
                                    incidentCandidate.opponentDataKey));
                            }
                        }
                        else
                        {
                            // update incident candidate element to reflect the current state ready for the next check
                            incidentCandidate.overallPositionAtLastCheck = opponent.OverallPosition;
                            incidentCandidate.distanceRoundTrackAtLastCheck = opponent.DistanceRoundTrack;
                            remainingIncidentCandidates.Add(incidentCandidate);
                        }
                    }
                }
            }
            incidentCandidates = remainingIncidentCandidates;
            return involvedDrivers;
        }

        void reportYellowFlagDrivers(Dictionary<string, OpponentData> opponents, TrackDefinition currentTrack)
        {
            // remove driver who are no longer in the opponentdata or who have pitted
            List<NamePositionPair> driversInvolvedAndConnected = new List<NamePositionPair>();
            foreach (NamePositionPair driverInvolved in driversInvolvedInCurrentIncident)
            {
                if (opponents.ContainsKey(driverInvolved.opponentKey) && !opponents[driverInvolved.opponentKey].InPits)
                {
                    driversInvolvedAndConnected.Add(driverInvolved);
                }
            }
            driversInvolvedInCurrentIncident = driversInvolvedAndConnected;
            if (driversInvolvedInCurrentIncident.Count == 0 || checkForAndReportPileup(currentTrack))
            {
                return;
            }
            
            // no pileup so read name / positions / corners as appropriate
            // there may be many of these, so we need to sort the list then pick the top few
            driversInvolvedInCurrentIncident.Sort(new NamePositionPairComparer(playerClassPositionAtStartOfIncident));
            // get the landmark and other data off the first item
            String landmark = TrackData.getLandmarkForLapDistance(currentTrack, driversInvolvedInCurrentIncident[0].distanceRoundTrack);
            float distanceRoundTrackOfFirstDriver = driversInvolvedInCurrentIncident[0].distanceRoundTrack;
            List<OpponentData> opponentsToRead = new List<OpponentData>();
            opponentsToRead.Add(opponents[driversInvolvedInCurrentIncident[0].opponentKey]);
            // if the first item is a position (we have no name for him), don't process the others
            Boolean namesMode = driversInvolvedInCurrentIncident[0].canReadName;
            int position = driversInvolvedInCurrentIncident[0].classPosition;
            if (namesMode)
            {
                for (int i = 1; i < driversInvolvedInCurrentIncident.Count; i++)
                {
                    if (opponentsToRead.Count == maxDriversToReportAsInvolvedInIncident)
                    {
                        break;
                    }
                    if (driversInvolvedInCurrentIncident[i].canReadName)
                    {                        
                        String thisLandmark = TrackData.getLandmarkForLapDistance(currentTrack, driversInvolvedInCurrentIncident[i].distanceRoundTrack);
                        if (landmark == thisLandmark || Math.Abs(distanceRoundTrackOfFirstDriver - driversInvolvedInCurrentIncident[i].distanceRoundTrack) < 300)
                        {
                            opponentsToRead.Add(opponents[driversInvolvedInCurrentIncident[i].opponentKey]);
                            if (landmark == null)
                            {
                                landmark = thisLandmark;
                            }
                        }
                    }
                }
            }
            // now we have the opponents to read and the landmark - all the drivers in the list are in or close to the landmark
            List<MessageFragment> messageContents = new List<MessageFragment>();
            if (namesMode)
            {
                messageContents.AddRange(MessageContents(folderNameHasGoneOffIntro));
                int andIndex = opponentsToRead.Count > 1 ? opponentsToRead.Count - 1 : -1;
                for (int i = 0; i < opponentsToRead.Count; i++)
                {
                    if (i == andIndex)
                    {
                        messageContents.AddRange(MessageContents(folderAnd));
                    }
                    messageContents.AddRange(MessageContents(opponentsToRead[i]));
                }
                if (andIndex != -1)
                {
                    if (landmark != null)
                    {
                        messageContents.AddRange(MessageContents(folderNamesHaveGoneOffInOutro));
                        messageContents.AddRange(MessageContents("corners/" + landmark));
                    }
                    else
                    {
                        messageContents.AddRange(MessageContents(folderNamesHaveGoneOffOutro));
                    }
                }
                else
                {
                    if (landmark != null)
                    {
                        messageContents.AddRange(MessageContents(folderNameHasGoneOffInOutro));
                        messageContents.AddRange(MessageContents("corners/" + landmark));
                    }
                    else
                    {
                        messageContents.AddRange(MessageContents(folderNameHasGoneOffOutro));
                    }
                }
            }
            else if (landmark != null && position <= folderPositionHasGoneOffIn.Length/* && position >= 1*/)
            {
                messageContents.AddRange(MessageContents(folderPositionHasGoneOffIn[position - 1]));
                messageContents.AddRange(MessageContents("corners/" + landmark));
            }
            else if (position <= folderPositionHasGoneOffIn.Length/* && position >= 1*/)
            {
                messageContents.AddRange(MessageContents(folderPositionHasGoneOff[position - 1]));
            }
            if (messageContents.Count > 0 && CrewChief.yellowFlagMessagesEnabled)
            {
                // immediate to prevent it being delayed by the hard-parts logic
                audioPlayer.playMessageImmediately(new QueuedMessage("incident_drivers", 5, messageFragments: messageContents, abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
            }
        }

        Boolean checkForAndReportPileup(TrackDefinition currentTrack)
        {
            if (driversInvolvedInCurrentIncident.Count >= pileupDriverCount)
            {
                Dictionary<String, int> crashedInLandmarkCounts = new Dictionary<string, int>();
                foreach (NamePositionPair driver in driversInvolvedInCurrentIncident)
                {
                    String crashLandmark = TrackData.getLandmarkForLapDistance(currentTrack, driver.distanceRoundTrack);
                    if (crashLandmark != null)
                    {
                        int numCrashesInLandmark = -1;
                        if (crashedInLandmarkCounts.TryGetValue(crashLandmark, out numCrashesInLandmark))
                        {
                            crashedInLandmarkCounts[crashLandmark] = ++numCrashesInLandmark;
                        }
                        else
                        {
                            crashedInLandmarkCounts.Add(crashLandmark, 1);
                        }
                    }
                }
                // now see if any exceed the limit
                foreach (String crashedInLandmarkKey in crashedInLandmarkCounts.Keys)
                {
                    if (crashedInLandmarkCounts[crashedInLandmarkKey] >= pileupDriverCount)
                    {
                        // report the pileup
                        if (CrewChief.yellowFlagMessagesEnabled)
                        {
                            // immediate to prevent it being delayed by the hard-parts logic
                            audioPlayer.playMessageImmediately(new QueuedMessage("pileup_in_corner", 5, messageFragments: MessageContents(folderPileupInCornerIntro, "corners/" + crashedInLandmarkKey),
                                abstractEvent: this, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                        }
                        return true;
                    }
                }
            }
            return false;
        }
    }

    class NamePositionPair
    {
        public String name;
        public int classPosition;
        public int overallPosition;
        public float distanceRoundTrack;
        public Boolean canReadName;
        public string opponentKey;

        public NamePositionPair(String name, int classPosition, int overallPosition, float distanceRoundTrack, Boolean canReadName, string opponentKey)
        {
            this.name = name;
            this.classPosition = classPosition;
            this.overallPosition = overallPosition;
            this.distanceRoundTrack = distanceRoundTrack;
            this.canReadName = canReadName;
            this.opponentKey = opponentKey;
        }
    }

    class NamePositionPairComparer : IComparer<NamePositionPair>
    {
        private int playerClassPosition;

        public NamePositionPairComparer(int playerClassPosition)
        {
            this.playerClassPosition = playerClassPosition;
        }
        public int Compare(NamePositionPair a, NamePositionPair b)
        {
            if (a.canReadName == b.canReadName)
            {
                // can (or can't) read both names, return the one closest but preferably in front
                if (a.classPosition > playerClassPosition && b.classPosition > playerClassPosition)
                {
                    return a.classPosition > b.classPosition ? 1 : -1;
                }
                else if (a.classPosition < playerClassPosition && b.classPosition < playerClassPosition)
                {
                    return a.classPosition < b.classPosition ? 1 : -1;
                }
                else if (a.classPosition < playerClassPosition && b.classPosition > playerClassPosition)
                {
                    return 1;
                }
                else if (a.classPosition > playerClassPosition && b.classPosition < playerClassPosition)
                {
                    return -1;
                }
                else
                {
                    return Math.Abs(a.classPosition - playerClassPosition) < Math.Abs(b.classPosition - playerClassPosition) ? 1 : -1;
                }
            }
            else
            {
                // we have one name
                if (a.canReadName)
                {
                    // can't read b's name but he still might be in a more interesting position
                    return b.classPosition <= FlagsMonitor.folderPositionHasGoneOff.Length && b.classPosition < playerClassPosition && a.classPosition > playerClassPosition ? -1 : 1;
                }
                else
                {
                    // can't read a's name but he still might be in a more interesting position
                    return a.classPosition <= FlagsMonitor.folderPositionHasGoneOff.Length && a.classPosition < playerClassPosition && b.classPosition > playerClassPosition ? 1 : -1;
                }
            }
        }
    }

    class IncidentCandidate
    {
        public string opponentDataKey;
        public float distanceRoundTrackAtStartOfIncident;
        public float distanceRoundTrackAtLastCheck;
        public Boolean lapValidAtStartOfIncident;
        public int overallPositionAtStartOfIncident;
        public int classPositionAtStartOfIncident;
        public int overallPositionAtLastCheck;
        public IncidentCandidate(string opponentDataKey, float distanceRoundTrackAtStartOfIncident, int classPositionAtStartOfIncident,
            int overallPositionAtStartOfIncident, Boolean lapValidAtStartOfIncident)
        {
            this.opponentDataKey = opponentDataKey;
            this.distanceRoundTrackAtStartOfIncident = distanceRoundTrackAtStartOfIncident;
            this.classPositionAtStartOfIncident = classPositionAtStartOfIncident;
            this.overallPositionAtStartOfIncident = overallPositionAtStartOfIncident;
            this.lapValidAtStartOfIncident = lapValidAtStartOfIncident;
            this.overallPositionAtLastCheck = overallPositionAtStartOfIncident;
            this.distanceRoundTrackAtLastCheck = distanceRoundTrackAtStartOfIncident;
        }
    }
}
