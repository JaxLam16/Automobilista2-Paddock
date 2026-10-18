using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using CrewChiefV4.GameState;
using CrewChiefV4.Audio;

namespace CrewChiefV4.Events
{
    class Position : AbstractEvent
    {
        private String positionValidationKey = "CURRENT_POSITION";

        public static String folderLeading = "position/leading";
        public static String folderPole = "position/pole";
        private static String folderQuickestOverall = "lap_times/quickest_overall"; // this has been moved from the LapTimes event
        public static String folderStub = "position/p";
        public static String folderLast = "position/last";
        public static String folderAhead = "position/ahead";
        public static String folderBehind = "position/behind";
        public static String folderLapsAhead = "position/laps_ahead";
        public static String folderLapsBehind = "position/laps_behind";
        private static String folderOvertaking = "position/overtaking";
        private static String folderBeingOvertaken = "position/being_overtaken";

        private TimeSpan minTimeToWaitBeforeReportingPass = TimeSpan.FromSeconds(4);
        public static int maxSecondsToWaitBeforeReportingPass = 7;
        private TimeSpan maxTimeToWaitBeforeReportingPass = TimeSpan.FromSeconds(maxSecondsToWaitBeforeReportingPass);

        private String folderConsistentlyLast = "position/consistently_last";
        private String folderGoodStart = "position/good_start";
        private String folderOKStart = "position/ok_start";
        private String folderBadStart = "position/bad_start";
        private String folderTerribleStart = "position/terrible_start";

        // optional intro for driver position message (not used in English)
        public static String folderDriverPositionIntro = "position/driver_position_intro";
        
        // messages for expected finish position for the end of Q:
        private static String folderExpectedFinishPositionIntroStrongField = "position/expected_position_intro_strong_field";  // it's a strong field, we'll be happy if we finish in the top...
        private static String folderExpectedFinishPositionIntroWeakField = "position/expected_position_intro_weak_field";      // we should do well here, we should aim to finish in the top...
        private static String folderExpectedFinishPositionIntroMediumField = "position/expected_position_intro_medium_field";  // this should be close, we're aiming to finish in the top...
        // used when the field is too small for a strong / weak / matched message to make sense:
        private static String folderExpectedFinishPositionIntroSmallField = "position/expected_position_intro_small_field";  // we're aiming to finish in the top...
        private static String folderExpectedFinishPositionWin = "position/expected_position_win";      // "we should aim to win this"
        // messages for expected finish position for mid-race:
        private static String folderCurrentPositionIntro = "position/expected_position_current_position_intro"; // we're running in P...
        private static String folderCurrentPositionIntroLeading = "position/expected_position_current_position_leading";    // we're currently leading
        private static String folderExpectedFinishPositionIntroMidRace = "position/expected_position_intro_mid_race";       // "we expected to finish in the top..."
        private static String folderExpectedFinishPositionIntroWinMidRace = "position/expected_position_win_mid_race";      // "we expected to win this"

        private int currentPosition;

        private int previousPosition;

        private SessionType sessionType;

        private int numberOfLapsInLastPlace;

        private Boolean playedRaceStartMessage;

        private readonly Boolean enableRaceStartMessages = UserSettings.GetUserSettings().getBoolean("enable_race_start_messages");

        private readonly Boolean enablePositionMessages = UserSettings.GetUserSettings().getBoolean("enable_position_messages");

        private readonly int frequencyOfOvertakingMessages = UserSettings.GetUserSettings().getInt("frequency_of_overtaking_messages");
        private readonly int frequencyOfBeingOvertakenMessages = UserSettings.GetUserSettings().getInt("frequency_of_being_overtaken_messages");

        private int startMessageTime;

        private Boolean isLastInStandings;

        private List<float> gapsAhead = new List<float>();
        private List<float> gapsBehind = new List<float>();
        private TimeSpan passCheckInterval = TimeSpan.FromSeconds(1);

        private float minAverageGapForPassMessage;
        private float minAverageGapForBeingPassedMessage;
        private int passCheckSamplesToCheck = 100;
        private int beingPassedCheckSamplesToCheck = 100;
        private float maxSpeedDifferenceForReportablePass = 0;
        private float maxSpeedDifferenceForReportableBeingPassed = 0;
        private float minTimeDeltaForPassToBeCompleted = 0.15f;
        private TimeSpan minTimeBetweenOvertakeMessages;

        private DateTime lastPassCheck;

        private DateTime lastOvertakeMessageTime;

        private DateTime timeWhenWeMadeAPass;
        private DateTime timeWhenWeWerePassed;

        private const int secondsToCheckForDamageOrOfftrackOnPass = 10;
        private const int secondsToCheckForYellowOnPass = 3;
        private float lastOffTrackSessionTime = -1.0f;
        private float lastYellowFlagTime = -1.0f;
        private bool lastOvertakeWasClean = true;

        private string opponentAheadKey = null;
        private string opponentBehindKey = null;

        private string opponentKeyForCarWeJustPassed;

        private string opponentKeyForCarThatJustPassedUs;

        private Boolean canPlayPositionReminder = true;
        private int lapForPositionReminder = Utilities.random.Next(2, 5);
        private int sectorForPositionReminder = Utilities.random.Next(1, 4);

        public Position(AudioPlayer audioPlayer)
        {
            this.audioPlayer = audioPlayer;
            // frequency of 5 means you need to be < 2.5 seconds apart for at least 20 seconds
            // 9 means you need to be < 4.5 seconds apart for at least 11 seconds
            minAverageGapForPassMessage = 0.5f * (float)frequencyOfOvertakingMessages;
            minAverageGapForBeingPassedMessage = 0.5f * (float)frequencyOfBeingOvertakenMessages;
            if (frequencyOfOvertakingMessages > 0)
            {
                passCheckSamplesToCheck = (int)(100 / frequencyOfOvertakingMessages);
                maxSpeedDifferenceForReportablePass = frequencyOfOvertakingMessages + 15;
            }
            if (frequencyOfBeingOvertakenMessages > 0)
            {
                beingPassedCheckSamplesToCheck = (int)(100 / frequencyOfBeingOvertakenMessages);
                maxSpeedDifferenceForReportableBeingPassed = frequencyOfBeingOvertakenMessages + 15;
            }

            minTimeBetweenOvertakeMessages = TimeSpan.FromSeconds(20);
        }

        public override List<SessionType> applicableSessionTypes
        {
            get { return new List<SessionType> { SessionType.Practice, SessionType.Qualify, SessionType.Race }; }
        }

        public override void clearState()
        {
            currentPosition = 0;
            sessionType = SessionType.Unavailable;
            previousPosition = 0;
            numberOfLapsInLastPlace = 0;
            playedRaceStartMessage = false;
            startMessageTime = Utilities.random.Next(30, 50);
            isLastInStandings = false;
            lastPassCheck = DateTime.MinValue;
            gapsAhead.Clear();
            gapsBehind.Clear();
            opponentKeyForCarWeJustPassed = null;
            opponentKeyForCarThatJustPassedUs = null;
            timeWhenWeWerePassed = DateTime.MinValue;
            timeWhenWeMadeAPass = DateTime.MinValue;
            lastOvertakeMessageTime = DateTime.MinValue;
            lastOffTrackSessionTime = -1.0f;
            lastYellowFlagTime = -1.0f;

            // prime the position reminder stuff so it'll play the position a few laps after the race start
            // even if we've not changed positions. Note that this is reset if we do change positions
            canPlayPositionReminder = true;
            lapForPositionReminder = Utilities.random.Next(2, 5);
            sectorForPositionReminder = Utilities.random.Next(1, 4);
        }

        public override bool isMessageStillValid(string eventSubType, GameStateData currentGameState, Dictionary<String, Object> validationData)
        {
            // drop any messages while we're in the pitlane
            if (base.isMessageStillValid(eventSubType, currentGameState, validationData) && !currentGameState.PitData.InPitlane)
            {
                if (validationData != null)
                {
                    object positionValidationData = null;
                    if (validationData.TryGetValue(positionValidationKey, out positionValidationData))
                    {
                        int positionWhenQueued = (int) positionValidationData;
                        if (eventSubType == folderTerribleStart || eventSubType == folderBadStart)
                        {
                            // bad start message, so allow to play as long as we've not improved since we queued this message
                            return positionWhenQueued <= currentGameState.SessionData.ClassPosition;
                        }
                        else if (eventSubType == folderGoodStart || eventSubType == folderOKStart)
                        {
                            // good start message, so allow to play as long as we've not lost position(s) since we queued this message
                            return positionWhenQueued >= currentGameState.SessionData.ClassPosition;
                        }
                        else
                        {
                            // position message so we must be in the same position for it to still be valid
                            return positionWhenQueued == currentGameState.SessionData.ClassPosition;
                        }
                    }
                }
                // no validation data so it's valid
                return true;
            }
            else
            {
                return false;
            }
        }

        private Boolean isPassMessageCandidate(List<float> gapsList, int samplesToCheck, float minAverageGap)
        {
            return gapsList.Count >= samplesToCheck &&
                    gapsList.GetRange(gapsList.Count - samplesToCheck, samplesToCheck).Average() < minAverageGap;
        }

        private void checkForNewOvertakes(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (currentGameState.PenaltiesData.IsOffRacingSurface)
            {
                lastOffTrackSessionTime = currentGameState.SessionData.SessionRunningTime;
            }

            Boolean currentSectorIsYellow = currentGameState.SessionData.SectorNumber > 0 && currentGameState.SessionData.SectorNumber < 4 &&
                currentGameState.FlagData.sectorFlags[currentGameState.SessionData.SectorNumber - 1] == FlagEnum.YELLOW;
            if (currentGameState.FlagData.isLocalYellow || currentSectorIsYellow)
            {
                lastYellowFlagTime = currentGameState.SessionData.SessionRunningTime;
            }
            if (currentGameState.SessionData.SessionPhase == SessionPhase.Green &&
                currentGameState.SessionData.SessionType == SessionType.Race && currentGameState.SessionData.CompletedLaps > 0)
            {                
                if (!GlobalBehaviourSettings.justTheFacts && currentGameState.Now > lastPassCheck.Add(passCheckInterval))
                {
                    lastPassCheck = currentGameState.Now;
                    if (currentGameState.SessionData.TimeDeltaFront > 0)
                    {
                        gapsAhead.Add(currentGameState.SessionData.TimeDeltaFront);
                    }
                    if (currentGameState.SessionData.TimeDeltaBehind > 0) 
                    {
                        gapsBehind.Add(currentGameState.SessionData.TimeDeltaBehind);
                    }
                    string currentOpponentAheadKey = currentGameState.getOpponentKeyInFront(currentGameState.carClass);
                    string currentOpponentBehindKey = currentGameState.getOpponentKeyBehind(currentGameState.carClass);
                    // seems like belt and braces, but as Raceroom names aren't unique we need to double check a pass actually happened here:
                    if (frequencyOfOvertakingMessages > 0 && currentOpponentAheadKey != opponentAheadKey)
                    {
                        if (currentOpponentBehindKey != null &&
                            currentGameState.SessionData.CurrentLapIsValid && !currentGameState.PitData.InPitlane &&
                            currentOpponentBehindKey == opponentAheadKey && isPassMessageCandidate(gapsAhead, passCheckSamplesToCheck, minAverageGapForPassMessage))
                        {
                            OpponentData carWeJustPassed = currentGameState.OpponentData[currentOpponentBehindKey];
                            if (carWeJustPassed.CompletedLaps == currentGameState.SessionData.CompletedLaps &&
                                CarData.IsCarClassEqual(carWeJustPassed.CarClass, currentGameState.carClass))
                            {
                                timeWhenWeMadeAPass = currentGameState.Now;
                                opponentKeyForCarWeJustPassed = currentOpponentBehindKey;
                                lastOvertakeWasClean = true;
                                if (currentGameState.CarDamageData.LastImpactTime > 0.0f && (currentGameState.SessionData.SessionRunningTime - currentGameState.CarDamageData.LastImpactTime) < secondsToCheckForDamageOrOfftrackOnPass)
                                {
                                    lastOvertakeWasClean = false;
                                    Console.WriteLine("Overtake considered not clean due to vehicle damage.");
                                }
                                else if (lastOffTrackSessionTime > 0.0f && (currentGameState.SessionData.SessionRunningTime - lastOffTrackSessionTime) < secondsToCheckForDamageOrOfftrackOnPass)
                                {
                                    lastOvertakeWasClean = false;
                                    Console.WriteLine("Overtake considered not clean due to vehicle off track.");
                                }
                                else if (lastYellowFlagTime > 0.0f && (currentGameState.SessionData.SessionRunningTime - lastYellowFlagTime) < secondsToCheckForYellowOnPass)
                                {
                                    lastOvertakeWasClean = false;
                                    Console.WriteLine("Overtake considered not clean due to yellow flag.");
                                }
                            }
                        }
                        gapsAhead.Clear();
                    }
                    if (frequencyOfBeingOvertakenMessages > 0 && opponentBehindKey != currentOpponentBehindKey)
                    {
                        if (currentOpponentAheadKey != null &&
                            !currentGameState.PitData.InPitlane && currentOpponentAheadKey == opponentBehindKey && 
                            isPassMessageCandidate(gapsBehind, beingPassedCheckSamplesToCheck, minAverageGapForBeingPassedMessage))
                        {
                            OpponentData carThatJustPassedUs = currentGameState.OpponentData[currentOpponentAheadKey];
                            if (carThatJustPassedUs.CompletedLaps == currentGameState.SessionData.CompletedLaps &&
                                CarData.IsCarClassEqual(carThatJustPassedUs.CarClass, currentGameState.carClass))
                            {
                                timeWhenWeWerePassed = currentGameState.Now;
                                opponentKeyForCarThatJustPassedUs = currentOpponentAheadKey;
                            }                            
                        }
                        gapsBehind.Clear();
                    }
                    opponentAheadKey = currentOpponentAheadKey;
                    opponentBehindKey = currentOpponentBehindKey;
                }
            }
        }

        private void checkCompletedOvertake(GameStateData currentGameState)
        {
            if (opponentKeyForCarWeJustPassed != null)
            {
                OpponentData carWeJustPassed = null;
                if (currentGameState.OpponentData.TryGetValue(opponentKeyForCarWeJustPassed, out carWeJustPassed) &&
                    currentGameState.Now < timeWhenWeMadeAPass.Add(maxTimeToWaitBeforeReportingPass) && lastOvertakeWasClean)
                {
                    Boolean reported = false;
                    if (currentGameState.Now > timeWhenWeMadeAPass.Add(minTimeToWaitBeforeReportingPass))
                    {                                 
                        if (currentGameState.Now > lastOvertakeMessageTime.Add(minTimeBetweenOvertakeMessages) &&
                            carWeJustPassed.ClassPosition > currentGameState.SessionData.ClassPosition && currentGameState.SessionData.TimeDeltaBehind > minTimeDeltaForPassToBeCompleted)
                        {
                            lastOvertakeMessageTime = currentGameState.Now;
                            Console.WriteLine("Reporting overtake on car " + carWeJustPassed.DriverRawName);
                            opponentKeyForCarWeJustPassed = null;
                            gapsAhead.Clear();
                            // adding a 'good' pearl with 0 probability of playing seems odd, but this forces the app to only
                            // allow an existing queued pearl to be played if it's type is 'good'
                            Dictionary<String, Object> validationData = new Dictionary<String, Object>();
                            validationData.Add(positionValidationKey, currentGameState.SessionData.ClassPosition);
                            QueuedMessage overtakingMessage = new QueuedMessage(folderOvertaking, 3, abstractEvent: this, validationData: validationData, priority: 10);
                            audioPlayer.playMessage(overtakingMessage, PearlsOfWisdom.PearlType.GOOD, 0);
                            reported = true;
                        }
                    }
                    if (!reported)
                    {
                        // check the pass is still valid
                        if (!currentGameState.SessionData.CurrentLapIsValid || carWeJustPassed.isEnteringPits() || currentGameState.PitData.InPitlane ||
                                currentGameState.PositionAndMotionData.CarSpeed - carWeJustPassed.Speed > maxSpeedDifferenceForReportablePass)
                        {
                            opponentKeyForCarWeJustPassed = null;
                            gapsAhead.Clear();
                        }
                    }
                }
                else
                {
                    opponentKeyForCarWeJustPassed = null;
                    gapsAhead.Clear();
                }
            }
            if (opponentKeyForCarThatJustPassedUs != null)
            {
                OpponentData carThatJustPassedUs = null;
                if (currentGameState.OpponentData.TryGetValue(opponentKeyForCarThatJustPassedUs, out carThatJustPassedUs) && 
                    currentGameState.Now < timeWhenWeWerePassed.Add(maxTimeToWaitBeforeReportingPass))
                {
                    Boolean reported = false;
                    if (currentGameState.Now > timeWhenWeWerePassed.Add(minTimeToWaitBeforeReportingPass))
                    {
                        if (currentGameState.Now > lastOvertakeMessageTime.Add(minTimeBetweenOvertakeMessages) &&
                            carThatJustPassedUs.ClassPosition < currentGameState.SessionData.ClassPosition && currentGameState.SessionData.TimeDeltaFront > minTimeDeltaForPassToBeCompleted)
                        {
                            lastOvertakeMessageTime = currentGameState.Now;
                            Console.WriteLine("Reporting being overtaken by car " + carThatJustPassedUs.DriverRawName);
                            opponentKeyForCarThatJustPassedUs = null;
                            gapsBehind.Clear();
                            // adding a 'bad' pearl with 0 probability of playing seems odd, but this forces the app to only
                            // allow an existing queued pearl to be played if it's type is 'bad'
                            Dictionary<String, Object> validationData = new Dictionary<String, Object>();
                            validationData.Add(positionValidationKey, currentGameState.SessionData.ClassPosition);
                            bool hasPenalty = currentGameState.PenaltiesData.HasSlowDown
                                || currentGameState.PenaltiesData.HasStopAndGo
                                || currentGameState.PenaltiesData.HasDriveThrough
                                || currentGameState.PenaltiesData.PenaltyType == PenatiesData.DetailedPenaltyType.DRIVE_THROUGH
                                || currentGameState.PenaltiesData.PenaltyType == PenatiesData.DetailedPenaltyType.STOP_AND_GO;
                            if (GlobalBehaviourSettings.complaintsCountInThisSession < GlobalBehaviourSettings.maxComplaintsPerSession && !hasPenalty)
                            {
                                QueuedMessage beingOvertakenMessage = new QueuedMessage(folderBeingOvertaken, 3, abstractEvent: this, validationData: validationData, priority: 10);
                                audioPlayer.playMessage(beingOvertakenMessage, PearlsOfWisdom.PearlType.BAD, 0);
                                GlobalBehaviourSettings.complaintsCountInThisSession++;
                            }
                            reported = true;
                        }
                    }
                    if (!reported)
                    {
                        // check the pass is still valid - no lap validity check here because we're being passed
                        if (carThatJustPassedUs.isEnteringPits() ||
                                carThatJustPassedUs.Speed - currentGameState.PositionAndMotionData.CarSpeed > maxSpeedDifferenceForReportableBeingPassed)
                        {
                            opponentKeyForCarThatJustPassedUs = null;
                            gapsBehind.Clear();
                        }
                    }
                }
                else
                {
                    opponentKeyForCarThatJustPassedUs = null;
                    gapsBehind.Clear();
                }
            }
        }

        protected override void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (GameStateData.onManualFormationLap)
            {
                return;
            }
            // edge case here - if we're the only can in the session, don't bother with this event
            if (currentGameState.OpponentData.Count == 0)
            {
                currentPosition = 1;
                return;
            }

            if (!GlobalBehaviourSettings.useOvalLogic && opponentKeyForCarThatJustPassedUs == null && opponentKeyForCarWeJustPassed == null)
            {
                checkForNewOvertakes(currentGameState, previousGameState);
            }
            checkCompletedOvertake(currentGameState);
            currentPosition = currentGameState.SessionData.ClassPosition;
            sessionType = currentGameState.SessionData.SessionType;
            isLastInStandings = currentGameState.isLastInStandings();

            if (previousPosition == 0)
            {
                previousPosition = currentPosition;
            }
            if (currentGameState.SessionData.SessionPhase == SessionPhase.Green || currentGameState.SessionData.SessionPhase == SessionPhase.FullCourseYellow)
            {
                if (currentGameState.SessionData.SessionType == SessionType.Race &&
                    enableRaceStartMessages && !playedRaceStartMessage &&
                    currentGameState.SessionData.CompletedLaps == 0 &&
                    (currentGameState.SessionData.JustGoneGreenTime != DateTime.MaxValue && currentGameState.Now > currentGameState.SessionData.JustGoneGreenTime.AddSeconds(startMessageTime)) &&
                    !currentGameState.FlagData.isLocalYellow)
                {
                    playedRaceStartMessage = true;
                    Console.WriteLine("Race start message... isLastInStandings = " + isLastInStandings +
                        " session start pos = " + currentGameState.SessionData.SessionStartClassPosition + " current pos = " + currentGameState.SessionData.ClassPosition);
                    bool hasrFactorPenaltyPending = (Game.RF1 || Game.RF2_LMU) && currentGameState.PenaltiesData.NumOutstandingPenalties > 0;
                    if (!GlobalBehaviourSettings.justTheFacts &&
                        currentGameState.SessionData.SessionStartClassPosition > 0 &&
                            !currentGameState.PenaltiesData.HasDriveThrough && !currentGameState.PenaltiesData.HasStopAndGo &&
                            !hasrFactorPenaltyPending)
                    {
                        Dictionary<String, Object> validationData = new Dictionary<String, Object>();
                        validationData.Add(positionValidationKey, currentGameState.SessionData.ClassPosition);
                        if (currentGameState.SessionData.ClassPosition > currentGameState.SessionData.SessionStartClassPosition + 5)
                        {
                            if (GlobalBehaviourSettings.complaintsCountInThisSession < GlobalBehaviourSettings.maxComplaintsPerSession)
                            {
                                GlobalBehaviourSettings.complaintsCountInThisSession++;
                                audioPlayer.playMessage(new QueuedMessage(folderTerribleStart, 10, abstractEvent: this, priority: 5, validationData: validationData));
                            }
                        }
                        else if (currentGameState.SessionData.ClassPosition > currentGameState.SessionData.SessionStartClassPosition + 3)
                        {
                            if (GlobalBehaviourSettings.complaintsCountInThisSession < GlobalBehaviourSettings.maxComplaintsPerSession)
                            {
                                GlobalBehaviourSettings.complaintsCountInThisSession++;
                                audioPlayer.playMessage(new QueuedMessage(folderBadStart, 10, abstractEvent: this, priority: 5, validationData: validationData));
                            }
                        }
                        else if (!isLastInStandings && (currentGameState.SessionData.ClassPosition == 1 || currentGameState.SessionData.ClassPosition < currentGameState.SessionData.SessionStartClassPosition - 1))
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderGoodStart, 10, abstractEvent: this, priority: 5, validationData: validationData));
                        }
                        else if (!isLastInStandings && Utilities.random.NextDouble() > 0.6)
                        {
                            // only play the OK start message sometimes
                            audioPlayer.playMessage(new QueuedMessage(folderOKStart, 10, abstractEvent: this, priority: 5, validationData: validationData));
                        }
                    }
                }
            }
            if (enablePositionMessages && currentGameState.SessionData.SessionPhase != SessionPhase.Countdown && !currentGameState.PitData.InPitlane)
            {
                if (canPlayPositionReminder && currentGameState.SessionData.IsNewSector &&
                    currentGameState.SessionData.CompletedLaps == lapForPositionReminder && currentGameState.SessionData.SectorNumber == sectorForPositionReminder)
                {
                    if (!GlobalBehaviourSettings.justTheFacts)
                    {
                        playCurrentPositionMessage(PearlsOfWisdom.PearlType.NONE, 0f, true);
                    }
                    canPlayPositionReminder = false;
                }
                if (currentGameState.SessionData.IsNewLap)
                {
                    if (currentGameState.SessionData.CompletedLaps > 0)
                    {
                        playedRaceStartMessage = true;
                    }
                    if (isLastInStandings)
                    {
                        numberOfLapsInLastPlace++;
                    }
                    else
                    {
                        numberOfLapsInLastPlace = 0;
                    }
                    if (previousPosition == 0 && currentGameState.SessionData.ClassPosition > 0)
                    {
                        previousPosition = currentGameState.SessionData.ClassPosition;
                    }
                    else
                    {
                        if (previousPosition != currentGameState.SessionData.ClassPosition && currentGameState.SessionData.CompletedLaps > 0)
                        {
                            if (currentGameState.SessionData.CompletedLaps > 1)
                            {
                                canPlayPositionReminder = true;
                                lapForPositionReminder = currentGameState.SessionData.CompletedLaps + Utilities.random.Next(3, 6);
                                sectorForPositionReminder = Utilities.random.Next(1, 4);
                            }
                            PearlsOfWisdom.PearlType pearlType = PearlsOfWisdom.PearlType.NONE;
                            float pearlLikelihood = 0.2f;
                            if (currentGameState.SessionData.SessionType == SessionType.Race && currentGameState.SessionData.ClassPosition > 0)
                            {
                                if (!isLastInStandings && (previousPosition > currentGameState.SessionData.ClassPosition + 5 ||
                                    (previousPosition > currentGameState.SessionData.ClassPosition && currentGameState.SessionData.ClassPosition <= 5)))
                                {
                                    pearlType = PearlsOfWisdom.PearlType.GOOD;
                                    pearlLikelihood = 0.8f;
                                }
                                else if (!isLastInStandings && previousPosition < currentGameState.SessionData.ClassPosition &&
                                    currentGameState.SessionData.ClassPosition > 5 && !previousGameState.PitData.OnOutLap &&
                                    !currentGameState.PitData.OnOutLap && !currentGameState.PitData.InPitlane &&
                                    currentGameState.SessionData.LapTimePrevious > currentGameState.SessionData.PlayerLapTimeSessionBest)
                                {
                                    // don't play bad-pearl if the lap just completed was an out lap or are in the pit

                                    // note that we don't play a pearl for being last - there's a special set of 
                                    // insults reserved for this
                                    pearlType = PearlsOfWisdom.PearlType.BAD;
                                    pearlLikelihood = 0.5f;
                                }
                                else if (!isLastInStandings)
                                {
                                    pearlType = PearlsOfWisdom.PearlType.NEUTRAL;
                                }
                            }
                            // Workaround for bad R3E data.  Do not play position message in Quali on completion of very first lap completed out of pits.
                            if (!(Game.RACE_ROOM
                                && currentGameState.SessionData.CompletedLaps == 1
                                && currentGameState.SessionData.SessionType == SessionType.Qualify
                                && previousGameState != null
                                && previousGameState.PitData.OnOutLap))
                            {
                                playCurrentPositionMessage(pearlType, pearlLikelihood, false);
                            }
                        }
                    }
                }
            }
        }

        // read the position message. This is may be part of a long message queue so it can be a few seconds before it triggers.
        // Because of this, we use a delayed message event - when the message reaches the top of the queue it uses the latest 
        // position, rather than the position when it was inserted into the queue.

        private void playCurrentPositionMessage(PearlsOfWisdom.PearlType pearlType, float pearlLikelihood, Boolean isReminder)
        {
            int delaySeconds = Game.RF2_LMU ||
                                Game.GTR2 ||
                                Game.ASSETTO1 ||
                                Game.ACC ? 1 : 0;
            DelayedMessageEvent delayedMessageEvent = new DelayedMessageEvent("getPositionMessages", new Object[] { currentPosition, isReminder }, this);
            audioPlayer.playMessage(new QueuedMessage("position", 10, delayedMessageEvent: delayedMessageEvent, secondsDelay: delaySeconds, priority: 10), pearlType, pearlLikelihood);
        }

        public Tuple<List<MessageFragment>, List<MessageFragment>> getPositionMessages(int positionWhenQueued, Boolean isReminder)
        {
            // the position might have changed between queueing this messasge and processing it, so update the
            // previousPosition here. We should probably do the same with the lapNumberAtLastMessage, but this won't
            // change quickly enough for it to be a problem
            previousPosition = currentPosition;
            // if the position has changed since we queued this message, prevent the pearls playing as they may be out of date
            // We also don't berate the player for being crap in message *and* any associated pearl
            if (isLastInStandings || positionWhenQueued != this.currentPosition)
            {
                audioPlayer.suspendPearlsOfWisdom();
                if (isReminder)
                {
                    // send an empty message here, which won't play
                    return new Tuple<List<MessageFragment>, List<MessageFragment>>(new List<MessageFragment>(), null);
                }
            }
            if (this.currentPosition == 1)
            {
                switch (this.sessionType)
                {
                    case SessionType.Race:
                        return new Tuple<List<MessageFragment>, List<MessageFragment>>(MessageContents(folderLeading), null);
                    case SessionType.Qualify:
                        return new Tuple<List<MessageFragment>, List<MessageFragment>>(MessageContents(folderPole), null);
                    default:
                        return new Tuple<List<MessageFragment>, List<MessageFragment>>(MessageContents(folderQuickestOverall), null);
                }
            }
            else if (this.isLastInStandings && !GlobalBehaviourSettings.justTheFacts && GlobalBehaviourSettings.complaintsCountInThisSession < GlobalBehaviourSettings.maxComplaintsPerSession)
            {
                if (this.numberOfLapsInLastPlace > 5 &&
                    CrewChief.currentGameState.SessionData.LapTimePrevious > CrewChief.currentGameState.SessionData.PlayerLapTimeSessionBest &&
                    CrewChief.currentGameState.SessionData.ClassPosition > 3)
                {
                    GlobalBehaviourSettings.complaintsCountInThisSession++;
                    return new Tuple<List<MessageFragment>, List<MessageFragment>>(MessageContents(folderConsistentlyLast), null);
                }
                else
                {
                    return new Tuple<List<MessageFragment>, List<MessageFragment>>(MessageContents(folderLast), null);
                }
            }
            else if (SoundCache.availableSounds.Contains(folderDriverPositionIntro))
            {
                return new Tuple<List<MessageFragment>, List<MessageFragment>>(MessageContents(folderDriverPositionIntro, folderStub + this.currentPosition), null);
            }
            else
            {
                return new Tuple<List<MessageFragment>, List<MessageFragment>>(MessageContents(folderStub + this.currentPosition), null);
            }
        }

        private static readonly List<SpeechCommands.ID> Commands = new List<SpeechCommands.ID>
        {
            SpeechCommands.ID.WHATS_MY_EXPECTED_FINISH_POSITION,
            SpeechCommands.ID.WHATS_MY_POSITION,
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
                case SpeechCommands.ID.WHATS_MY_EXPECTED_FINISH_POSITION:
                {
                    bool raceUnderway = CrewChief.currentGameState != null
                                        && CrewChief.currentGameState.SessionData.SessionType == SessionType.Race
                                        && (CrewChief.currentGameState.SessionData.SessionPhase == SessionPhase.Green || CrewChief.currentGameState.SessionData.SessionPhase == SessionPhase.Checkered || CrewChief.currentGameState.SessionData.SessionPhase == SessionPhase.FullCourseYellow)
                                        && CrewChief.currentGameState.SessionData.SessionRunningTime > 60;
                    reportExpectedFinishPosition(audioPlayer, CrewChief.currentGameState.SessionData.expectedFinishingPosition, true, raceUnderway, currentPosition);
                    break;
                }
                case SpeechCommands.ID.WHATS_MY_POSITION:
                {
                    if (isLastInStandings && GlobalBehaviourSettings.complaintsCountInThisSession < GlobalBehaviourSettings.maxComplaintsPerSession)
                    {
                        GlobalBehaviourSettings.complaintsCountInThisSession++;
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderLast, 0));
                    }
                    else if (currentPosition == 1)
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(folderLeading, 0));
                    }
                    else if (currentPosition > 0)
                    {
                        if (SoundCache.availableSounds.Contains(folderDriverPositionIntro))
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage("position", 0,
                                messageFragments: MessageContents(folderDriverPositionIntro, folderStub + currentPosition)));
                        }
                        else
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage(folderStub + currentPosition, 0));
                        }
                    }
                    else
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                    }

                    break;
                }
            }
        }

        // if audioPlayer is null then the message will not be played. Contents are always returned.
        public static List<MessageFragment> reportExpectedFinishPosition(AudioPlayer audioPlayer, Tuple<int, int> expectedFinish, bool fromVoiceCommand, bool raceUnderway, int currentPosition)
        {
            List<MessageFragment> messageContents = new List<MessageFragment>();
            if (expectedFinish.Item1 > 0 && expectedFinish.Item2 > 0)
            {
                // once we're into the race, the responses are simple stuff like "we're running in P4, we expected to finish in the top N".
                if (raceUnderway)
                {
                    if (currentPosition == 1)
                    {
                        messageContents.Add(MessageFragment.Text(Position.folderCurrentPositionIntroLeading));
                    }
                    else
                    {
                        messageContents.Add(MessageFragment.Text(Position.folderCurrentPositionIntro));
                        messageContents.Add(MessageFragment.Integer(currentPosition));
                    }
                    if (expectedFinish.Item1 == 1)
                    {
                        messageContents.Add(MessageFragment.Text(Position.folderExpectedFinishPositionIntroWinMidRace));
                    }
                    else
                    {
                        messageContents.Add(MessageFragment.Text(Position.folderExpectedFinishPositionIntroMidRace));
                        messageContents.Add(MessageFragment.Integer(expectedFinish.Item1));
                    }
                }
                else
                {
                    // when triggered at the end of Q, be a little more descriptive. If we're not expected to win, we need the field strength
                    if (expectedFinish.Item1 == 1)
                    {
                        messageContents.Add(MessageFragment.Text(Position.folderExpectedFinishPositionWin));
                    }
                    else
                    {
                        if (expectedFinish.Item2 > 3)
                        {
                            // no point in doing this if we have too few participants
                            float expectedFinishRatio = (float)expectedFinish.Item1 / (float)expectedFinish.Item2;
                            // >= 0.66 means "strong field"
                            // <= 0.33 means "weak field"
                            if (expectedFinishRatio >= 0.66f)
                            {
                                messageContents.Add(MessageFragment.Text(Position.folderExpectedFinishPositionIntroStrongField));
                            }
                            else if (expectedFinishRatio <= 0.33f)
                            {
                                messageContents.Add(MessageFragment.Text(Position.folderExpectedFinishPositionIntroWeakField));
                            }
                            else
                            {
                                messageContents.Add(MessageFragment.Text(Position.folderExpectedFinishPositionIntroMediumField));
                            }
                        }
                        else
                        {
                            messageContents.Add(MessageFragment.Text(Position.folderExpectedFinishPositionIntroSmallField));
                        }
                        messageContents.Add(MessageFragment.Integer(expectedFinish.Item1));
                    }
                }
                if (audioPlayer == null)
                {
                    // guard
                }
                else if (fromVoiceCommand)
                {
                    audioPlayer.playMessageImmediately(new QueuedMessage("expected_position_response", 0, messageFragments: messageContents));
                }
                else
                {
                    // if this isn't from a voice command it's been triggered as a result of ending the Q session, so we want this to play
                    // when we enter the subsequent race session.
                    //
                    // this message will survive the session end purge and will play when the triggerFunction evaluates to true. It expires after 2 minutes
                    audioPlayer.playMessage(new QueuedMessage(AudioPlayer.RETAIN_ON_SESSION_END + "_expected_position", 120, messageFragments: messageContents, 
                        triggerFunction: (GameStateData gsd) => 
                            gsd.SessionData.TrackDefinition != null 
                            && gsd.SessionData.TrackDefinition.name == CrewChief.currentGameState.SessionData.TrackDefinition.name
                            && gsd.SessionData.SessionType == SessionType.Race
                            && gsd.SessionData.SessionPhase != SessionPhase.Green));
                }
            }
            else if (fromVoiceCommand && audioPlayer != null)
            {
                audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
            }
            return messageContents;
        }
    }
}
