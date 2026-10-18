using System;
using System.Collections.Generic;
using System.Linq;
using CrewChiefV4.GameState;
using CrewChiefV4.Audio;
using CrewChiefV4.NumberProcessing;
using System.Diagnostics;

namespace CrewChiefV4.Events
{
    class Fuel_legacy : AbstractEvent
    {
        #region consts
        private const String folderOneLapEstimate = "fuel/one_lap_fuel";

        private const String folderTwoLapsEstimate = "fuel/two_laps_fuel";

        private const String folderThreeLapsEstimate = "fuel/three_laps_fuel";

        private const String folderFourLapsEstimate = "fuel/four_laps_fuel";

        private const String folderHalfDistanceGoodFuel = "fuel/half_distance_good_fuel";

        private const String folderHalfDistanceLowFuel = "fuel/half_distance_low_fuel";

        private const String folderHalfTankWarning = "fuel/half_tank_warning";

        private const String folderTenMinutesFuel = "fuel/ten_minutes_fuel";

        private const String folderTwoMinutesFuel = "fuel/two_minutes_fuel";

        private const String folderFiveMinutesFuel = "fuel/five_minutes_fuel";

        private const String folderMinutesRemaining = "fuel/minutes_remaining";

        private const String folderLapsRemaining = "fuel/laps_remaining";

        private const String folderWeEstimate = "fuel/we_estimate";

        public const String folderPlentyOfFuel = "fuel/plenty_of_fuel";

        private const String folderLitresRemaining = "fuel/litres_remaining";

        private const String folderGallonsRemaining = "fuel/gallons_remaining";

        private const String folderOneLitreRemaining = "fuel/one_litre_remaining";

        private const String folderOneGallonRemaining = "fuel/one_gallon_remaining";

        private const String folderHalfAGallonRemaining = "fuel/half_a_gallon_remaining";

        private const String folderAboutToRunOut = "fuel/about_to_run_out";

        private const String folderLitresPerLap = "fuel/litres_per_lap";

        private const String folderGallonsPerLap = "fuel/gallons_per_lap";

        public const String folderLitres = "fuel/litres";

        public const String folderLitre = "fuel/litre";

        public const String folderGallons = "fuel/gallons";

        public const String folderGallon = "fuel/gallon";

        public const String folderWillNeedToStopAgain = "fuel/will_need_to_stop_again";

        private const String folderWillNeedToAdd = "fuel/we_will_need_to_add";

        private const String folderLitresToGetToTheEnd = "fuel/litres_to_get_to_the_end";

        private const String folderGallonsToGetToTheEnd = "fuel/gallons_to_get_to_the_end";

        // no 1 litres equivalent
        private const String folderWillNeedToAddOneGallonToGetToTheEnd = "fuel/need_to_add_one_gallon_to_get_to_the_end";

        private const String folderFuelWillBeTight = "fuel/fuel_will_be_tight";

        private const String folderFuelShouldBeOK = "fuel/fuel_should_be_ok";

        private const String folderFor = "fuel/for";
        private const String folderWeEstimateWeWillNeed = "fuel/we_estimate_we_will_need";

        // Note theserefer to 'absolute' times - 20 minutes from-race-start, not 20 minutes from-current-time.
        private const String folderFuelWindowOpensOnLap = "fuel/pit_window_for_fuel_opens_on_lap";
        private const String folderFuelWindowOpensAfterTime = "fuel/pit_window_for_fuel_opens_after";
        private const String folderAndFuelWindowClosesOnLap = "fuel/and_will_close_on_lap";
        private const String folderAndFuelWindowClosesAfterTime = "fuel/and_closes_after";

        private const String folderWillNeedToPitForFuelByLap = "fuel/pit_window_for_fuel_closes_on_lap";
        private const String folderWillNeedToPitForFuelByTimeIntro = "fuel/we_will_need_to_pit_for_fuel";
        private const String folderWillNeedToPitForFuelByTimeOutro = "fuel/into_the_race";

        private const float NO_FUEL_DATA = float.MaxValue;
        private const float HALF_LAP_RESERVE_DEFAULT = 2f;  // Allow 2L for half a lap unless we have a better estimate

        // check fuel use every 60 seconds
        private const int fuelUseSampleTime = 60;

        #endregion consts
        #region variables
        private static DateTime lastFuelCall = DateTime.MinValue;

        private List<float> historicAverageUsagePerLap = new List<float>();

        private List<float> historicAverageUsagePerMinute = new List<float>();

        private float averageUsagePerLap;

        private float averageUsagePerMinute;

        // fuel in tank 15 seconds after game start
        private float initialFuelLevel;

        private int halfDistance;

        private float halfTime;

        private Boolean playedHalfTankWarning;

        private Boolean initialised;

        private Boolean playedHalfTimeFuelEstimate;

        private Boolean played1LitreWarning;

        private Boolean played2LitreWarning;

        // base fuel use by lap estimates on the last 3 laps
        private int fuelUseByLapsWindowLengthToUse = 3;
        private int fuelUseByLapsWindowLengthVeryShort = 5;
        private int fuelUseByLapsWindowLengthShort = 4;
        private int fuelUseByLapsWindowLengthMedium = 3;
        private int fuelUseByLapsWindowLengthLong = 2;
        private int fuelUseByLapsWindowLengthVeryLong = 1;

        // base fuel use by time estimates on the last 6 samples (6 minutes)
        private int fuelUseByTimeWindowLength = 6;

        private List<float> fuelLevelWindowByLap = new List<float>();

        private List<float> fuelLevelWindowByTime = new List<float>();

        private float gameTimeAtLastFuelWindowUpdate;

        private Boolean playedPitForFuelNow;

        private Boolean playedPitForFuelNowLastWarning;

        private Boolean crossedIntoSector3;

        private Boolean playedTwoMinutesRemaining;

        private Boolean playedFiveMinutesRemaining;

        private Boolean playedTenMinutesRemaining;

        private Boolean fuelUseActive;

        private float currentFuel = -1;

        private float fuelCapacity = 0;

        private float gameTimeWhenFuelWasReset = 0;

        private Boolean enableFuelMessages = UserSettings.GetUserSettings().getBoolean("enable_fuel_messages");

        private Boolean delayResponses = UserSettings.GetUserSettings().getBoolean("enable_delayed_responses");

        private float addAdditionalFuelLaps = UserSettings.GetUserSettings().getFloat("add_additional_fuel");

        private Boolean baseCalculationsOnMaxConsumption = UserSettings.GetUserSettings().getBoolean("prefer_max_consumption_in_fuel_calculations");

        private Boolean reportFuelLapsLeftInTimedRaces = UserSettings.GetUserSettings().getBoolean("report_fuel_laps_left_in_timed_races");

        private Boolean hasBeenRefuelled = false;

        // checking if we need to read fuel messages involves a bit of arithmetic and stuff, so only do this every few seconds
        private DateTime nextFuelStatusCheck = DateTime.MinValue;

        private DateTime nextFuelPitWindowOpenCheck = DateTime.MinValue;

        private TimeSpan fuelStatusCheckInterval = TimeSpan.FromSeconds(5);

        private Boolean sessionHasFixedNumberOfLaps = false;

        // count laps separately for fuel so we always count incomplete and invalid laps
        private int lapsCompletedSinceFuelReset = 0;

        private int lapsRemaining = -1;

        private float secondsRemaining = -1;

        private Boolean gotPredictedPitWindow = false;

        private bool playedPitWindowEstimate = false;

        private bool playedPitWindowOpen = false;

        private int extraLapsAfterTimedSessionComplete = 0;

        private Boolean sessionHasHadFCY = false;

        // in prac and qual, assume it's a low fuel run unless we know otherwise
        private Boolean onLowFuelRun = false;
        private float lapsForLowFuelRun = 4f;

        private float maxConsumptionPerLap = 0;

        // this is derived using the laptime on the lap where we've consumed the most fuel
        private float maxConsumptionPerMinute = 0;
        #endregion variables
        public Fuel_legacy(AudioPlayer audioPlayer)
        {
            this.audioPlayer = audioPlayer;
            Fuel.legacy_inst = this;
            Fuel.inst = new Fuel(audioPlayer); // Niiice!
        }

        public override void clearState()
        {
            initialFuelLevel = 0;
            averageUsagePerLap = 0;
            halfDistance = -1;
            playedHalfTankWarning = false;
            initialised = false;
            halfTime = -1;
            playedHalfTimeFuelEstimate = false;
            fuelLevelWindowByLap = new List<float>();
            fuelLevelWindowByTime = new List<float>();
            gameTimeAtLastFuelWindowUpdate = 0;
            averageUsagePerMinute = 0;
            playedPitForFuelNow = false;
            playedPitForFuelNowLastWarning = false;
            crossedIntoSector3 = false;
            playedFiveMinutesRemaining = false;
            playedTenMinutesRemaining = false;
            playedTwoMinutesRemaining = false;
            played1LitreWarning = false;
            played2LitreWarning = false;
            currentFuel = 0;
            fuelUseActive = false;
            gameTimeWhenFuelWasReset = 0;
            hasBeenRefuelled = false;
            nextFuelStatusCheck = DateTime.MinValue;
            nextFuelPitWindowOpenCheck = DateTime.MinValue;
            sessionHasFixedNumberOfLaps = false;
            lapsCompletedSinceFuelReset = 0;

            lapsRemaining = -1;
            secondsRemaining = -1;
            extraLapsAfterTimedSessionComplete = 0;
            fuelCapacity = 0;
            gotPredictedPitWindow = false;
            playedPitWindowOpen = false;
            playedPitWindowEstimate = false;
            sessionHasHadFCY = false;

            historicAverageUsagePerLap.Clear();
            historicAverageUsagePerMinute.Clear();

            onLowFuelRun = false;
            lapsForLowFuelRun = 4f;

            maxConsumptionPerLap = 0;
            maxConsumptionPerMinute = 0;
        }

        // fuel not implemented for HotLap/LonePractice modes
        public override List<SessionType> applicableSessionTypes
        {
            get { return new List<SessionType> { SessionType.Practice, SessionType.Qualify, SessionType.PrivateQualify, SessionType.Race, SessionType.LonePractice }; }
        }

        public override List<SessionPhase> applicableSessionPhases
        {
            get { return new List<SessionPhase> { SessionPhase.Green, SessionPhase.Countdown, SessionPhase.FullCourseYellow }; }
        }

        public bool fuelReportsInGallons()
        {
            return !GlobalBehaviourSettings.useMetric;
        }

        /// <summary>
        /// Do the fuel consumption calculations (when appropriate)
        /// Warn about fuel levels
        /// </summary>
        override protected void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (!GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.FUEL) ||
                !CrewChief.fuelMultiplier.active)
            {
                return;
            }
            fuelUseActive = currentGameState.FuelData.FuelUseActive;
            extraLapsAfterTimedSessionComplete = currentGameState.SessionData.ExtraLapsAfterTimedSessionComplete;
            // if the fuel level has increased, don't trigger
            if (currentFuel > -1 && currentFuel < currentGameState.FuelData.FuelLeft)
            {
                currentFuel = currentGameState.FuelData.FuelLeft;
                return;
            }
            if (currentGameState.SessionData.SessionHasFixedTime)
            {
                secondsRemaining = currentGameState.SessionData.SessionTimeRemaining;
            }
            else
            {
                lapsRemaining = currentGameState.SessionData.SessionLapsRemaining;
            }
            currentFuel = currentGameState.FuelData.FuelLeft;
            fuelCapacity = currentGameState.FuelData.FuelCapacity;
            // only track fuel data after the session has settled down
            if (fuelUseActive && !GameStateData.onManualFormationLap &&
                currentGameState.SessionData.SessionRunningTime > 15 &&  // seconds

                ((currentGameState.SessionData.SessionType == SessionType.Race &&
                    (currentGameState.SessionData.SessionPhase == SessionPhase.Green ||
                     currentGameState.SessionData.SessionPhase == SessionPhase.FullCourseYellow ||
                     currentGameState.SessionData.SessionPhase == SessionPhase.Checkered)) ||

                 ((currentGameState.SessionData.SessionType == SessionType.Qualify ||
                   currentGameState.SessionData.SessionType == SessionType.PrivateQualify ||
                   currentGameState.SessionData.SessionType == SessionType.Practice ||
                   currentGameState.SessionData.SessionType == SessionType.HotLap ||
                   currentGameState.SessionData.SessionType == SessionType.LonePractice) &&

                    (currentGameState.SessionData.SessionPhase == SessionPhase.Green ||
                     currentGameState.SessionData.SessionPhase == SessionPhase.FullCourseYellow ||
                     currentGameState.SessionData.SessionPhase == SessionPhase.Countdown) &&

                    // don't process fuel data in prac and qual until we're actually moving:
                    currentGameState.PositionAndMotionData.CarSpeed > 10)))
            {
                if (currentGameState.SessionData.SessionPhase == SessionPhase.FullCourseYellow && currentGameState.SessionData.SessionType == SessionType.Race)
                {
                    sessionHasHadFCY = true;
                }
                if (!initialised ||
                    // fuel has increased by at least 1 litre - we only check against the time window here
                    (fuelLevelWindowByTime.Count() > 0 && fuelLevelWindowByTime[0] > 0 && currentGameState.FuelData.FuelLeft > fuelLevelWindowByTime[0] + 1) ||
                    // special case for race session starting in the pitlane. When we exit the pit we might have much less fuel than we did at the start of the session because we took some out
                    // In this case, it'll be a race session with 0 laps completed at pit exit. AFAIK we can only take fuel out if we start from the pitlane
                    ((currentGameState.SessionData.SessionType != SessionType.Race || currentGameState.SessionData.CompletedLaps < 1)
                        && previousGameState != null && previousGameState.PitData.InPitlane && !currentGameState.PitData.InPitlane))
                {
                    // first time in, fuel has increased, or pit exit so initialise our internal state. Note we don't blat the average use data -
                    // this will be replaced when we get our first data point but it's still valid until we do.
                    fuelLevelWindowByTime = new List<float>();
                    fuelLevelWindowByLap = new List<float>();
                    fuelLevelWindowByTime.Add(currentGameState.FuelData.FuelLeft);
                    fuelLevelWindowByLap.Add(currentGameState.FuelData.FuelLeft);
                    initialFuelLevel = currentGameState.FuelData.FuelLeft;
                    gameTimeWhenFuelWasReset = currentGameState.SessionData.SessionRunningTime;
                    gameTimeAtLastFuelWindowUpdate = currentGameState.SessionData.SessionRunningTime;
                    playedPitForFuelNow = false;
                    playedPitForFuelNowLastWarning = false;
                    crossedIntoSector3 = false;
                    playedFiveMinutesRemaining = false;
                    playedTenMinutesRemaining = false;
                    playedTwoMinutesRemaining = false;
                    played1LitreWarning = false;
                    played2LitreWarning = false;
                    lapsCompletedSinceFuelReset = 0;
                    historicAverageUsagePerLap.Clear();
                    historicAverageUsagePerMinute.Clear();
                    // set the onLowFuelRun if we're in prac / qual - asssume we're on a low fuel run until we know otherwise
                    if (currentGameState.SessionData.SessionType == SessionType.Practice || 
                        currentGameState.SessionData.SessionType == SessionType.Qualify ||
                        currentGameState.SessionData.SessionType == SessionType.PrivateQualify)
                    {
                        onLowFuelRun = true;
                        lapsForLowFuelRun = 4f;
                        if (currentGameState.SessionData.TrackDefinition.trackLengthClass == TrackData.TrackLengthClass.LONG)
                        {
                            lapsForLowFuelRun = 3f;
                        }
                        else if (currentGameState.SessionData.TrackDefinition.trackLengthClass == TrackData.TrackLengthClass.VERY_LONG)
                        {
                            lapsForLowFuelRun = 2f;
                        }
                        if (averageUsagePerLap > 0 && initialFuelLevel / averageUsagePerLap > lapsForLowFuelRun)
                        {
                            onLowFuelRun = false;
                        }
                    }
                    else
                    {
                        onLowFuelRun = false;
                    }
                    // if this is the first time we've initialised the fuel stats (start of session), get the half way point of this session
                    if (!initialised)
                    {
                        if (currentGameState.SessionData.TrackDefinition != null)
                        {
                            switch (currentGameState.SessionData.TrackDefinition.trackLengthClass)
                            {
                                case TrackData.TrackLengthClass.VERY_SHORT:
                                    fuelUseByLapsWindowLengthToUse = fuelUseByLapsWindowLengthVeryShort;
                                    break;
                                case TrackData.TrackLengthClass.SHORT:
                                    fuelUseByLapsWindowLengthToUse = fuelUseByLapsWindowLengthShort;
                                    break;
                                case TrackData.TrackLengthClass.MEDIUM:
                                    fuelUseByLapsWindowLengthToUse = fuelUseByLapsWindowLengthMedium;
                                    break;
                                case TrackData.TrackLengthClass.LONG:
                                    fuelUseByLapsWindowLengthToUse = fuelUseByLapsWindowLengthLong;
                                    break;
                                case TrackData.TrackLengthClass.VERY_LONG:
                                    fuelUseByLapsWindowLengthToUse = fuelUseByLapsWindowLengthVeryLong;
                                    break;
                            }
                        }
                        if (currentGameState.SessionData.SessionNumberOfLaps > 1
                            &&
                            // rF2 has "Finish Criteria: Laps and Time", if that's selected then ignore laps
                            //  and calculate fuel based on time (sub-optimal but at least it won't run out of fuel)
                            !(CrewChief.gameDefinition.gameEnum == GameEnum.RF2_64BIT
                                  && currentGameState.SessionData.SessionHasFixedTime)
                            )
                        {
                            sessionHasFixedNumberOfLaps = true;
                            if (halfDistance == -1)
                            {
                                halfDistance = (int)Math.Ceiling(currentGameState.SessionData.SessionNumberOfLaps / 2f);
                            }
                        }
                        else if (currentGameState.SessionData.SessionTotalRunTime > 0)
                        {
                            sessionHasFixedNumberOfLaps = false;
                            if (halfTime == -1)
                            {
                                halfTime = (int)Math.Ceiling(currentGameState.SessionData.SessionTotalRunTime / 2f);
                            }
                        }
                    }
                    Log.Fuel("lgcy: Fuel level initialised, initialFuelLevel = " + litresToUnits(initialFuelLevel, false) + ", halfDistance = " + halfDistance + " halfTime = " + halfTime.ToString("0.00"));

                    initialised = true;
                }

                // OK, it's initialised, do the rest:
                if (previousGameState != null && previousGameState.SessionData.SectorNumber == 2 && currentGameState.SessionData.SectorNumber == 3 && playedPitForFuelNow)
                {
                    crossedIntoSector3 = true;
                }
                if (currentGameState.SessionData.IsNewLap && currentGameState.FuelData.FuelLeft > 0)
                {
                    lapsCompletedSinceFuelReset++;
                    // completed a lap, so store the fuel left at this point:
                    fuelLevelWindowByLap.Insert(0, currentGameState.FuelData.FuelLeft);
                    // if we've got fuelUseByLapsWindowLength + 1 samples (note we initialise the window data with initialFuelLevel so we always
                    // have one extra), get the average difference between each pair of values

                    // only do this if we have a full window of data + one extra start point
                    if (fuelLevelWindowByLap.Count > fuelUseByLapsWindowLengthToUse)
                    {
                        averageUsagePerLap = 0;
                        for (int i = 0; i < fuelUseByLapsWindowLengthToUse; i++)
                        {
                            float thisLapFuelUse = fuelLevelWindowByLap[i + 1] - fuelLevelWindowByLap[i];
                            // the first element in this array is the lap just completed, so check if this is our max consumption per lap.
                            // At this point we must have completed some laps so should have a vague idea as to whether this lap is representative
                            if (i == 0 && thisLapFuelUse > maxConsumptionPerLap && canUseLastLapForMaxPerLapFuelConsumption(currentGameState))
                            {
                                maxConsumptionPerLap = thisLapFuelUse;
                                maxConsumptionPerMinute = 60 * thisLapFuelUse / currentGameState.SessionData.LapTimePrevious;
                            }
                            averageUsagePerLap += thisLapFuelUse;
                        }
                        averageUsagePerLap = averageUsagePerLap / fuelUseByLapsWindowLengthToUse;
                        historicAverageUsagePerLap.Add(averageUsagePerLap);
                        Log.Fuel("lgcy: Fuel use per lap: windowed calc=" +
                            litresToUnits(averageUsagePerLap, true) +
                            ", max per lap=" +
                            litresToUnits(maxConsumptionPerLap, true) +
                            " left=" +
                            litresToUnits(currentGameState.FuelData.FuelLeft, false));
                    }
                    else
                    {
                        averageUsagePerLap = (initialFuelLevel - currentGameState.FuelData.FuelLeft) / lapsCompletedSinceFuelReset;
                        // this first calculation in the session is likely to be quite inaccurate so don't add it to the historic data
                        Log.Fuel("lgcy: Fuel use per lap (basic calc) = " + litresToUnits(averageUsagePerLap, true) + " fuel left = " + litresToUnits(currentGameState.FuelData.FuelLeft, false));
                    }
                    // now check if we need to reset the 'on low fuel run' variable, do this on our 2nd flying lap
                    if (onLowFuelRun && lapsCompletedSinceFuelReset == 2 && averageUsagePerLap > 0 && initialFuelLevel / averageUsagePerLap > lapsForLowFuelRun)
                    {
                        onLowFuelRun = false;
                    }
                }
                if (!currentGameState.PitData.InPitlane && currentGameState.FuelData.FuelLeft > 0
                    && currentGameState.SessionData.SessionRunningTime > gameTimeAtLastFuelWindowUpdate + fuelUseSampleTime)
                {
                    // it's x minutes since the last fuel window check
                    gameTimeAtLastFuelWindowUpdate = currentGameState.SessionData.SessionRunningTime;
                    fuelLevelWindowByTime.Insert(0, currentGameState.FuelData.FuelLeft);
                    // if we've got fuelUseByTimeWindowLength + 1 samples (note we initialise the window data with fuelAt15Seconds so we always
                    // have one extra), get the average difference between each pair of values

                    // only do this if we have a full window of data + one extra start point
                    if (fuelLevelWindowByTime.Count > fuelUseByTimeWindowLength)
                    {
                        averageUsagePerMinute = 0;
                        for (int i = 0; i < fuelUseByTimeWindowLength; i++)
                        {
                            averageUsagePerMinute += (fuelLevelWindowByTime[i + 1] - fuelLevelWindowByTime[i]);
                        }
                        averageUsagePerMinute = 60 * averageUsagePerMinute / (fuelUseByTimeWindowLength * fuelUseSampleTime);
                        historicAverageUsagePerMinute.Add(averageUsagePerMinute);
                        Log.Fuel("lgcy: Fuel use per minute: windowed calc=" + litresToUnits(averageUsagePerMinute, true) +
                            ", max per min calc=" + litresToUnits(maxConsumptionPerMinute, true) +
                            " fuel left=" + litresToUnits(currentGameState.FuelData.FuelLeft, false));
                    }
                    else
                    {
                        averageUsagePerMinute = 60 * (initialFuelLevel - currentGameState.FuelData.FuelLeft) / (gameTimeAtLastFuelWindowUpdate - gameTimeWhenFuelWasReset);
                        // this first calculation in the session is likely to be quite inaccurate so don't add it to the historic data
                        Log.Fuel("lgcy: Fuel use per minute (basic calc) = " + litresToUnits(averageUsagePerMinute, true) + " fuel left = " + litresToUnits(currentGameState.FuelData.FuelLeft, false));
                    }
                }

                // warnings for particular fuel levels
                if (enableFuelMessages && !onLowFuelRun)
                {
                    // warn when one/half a gallon left or two/one litre left
                    {	// (braces just to mark this clause)
						// Warn when two/one litre left but one/half a gallon left (approx 4L/2L)!
                        if (fuelReportsInGallons())
                        {
                            if (Utilities.Conversions.convertLitresToGallons(currentFuel) <= 1 && !played2LitreWarning)
                            {
                                // yes i know its not 2 litres but who really cares.
                                played2LitreWarning = true;
                                if (canPlayFuelMessage())
                                {
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/level", 0, messageFragments: MessageContents(folderOneGallonRemaining), abstractEvent: this, priority: 10));
                                    lastFuelCall = currentGameState.Now;
                                }
                            }
                            else if (Utilities.Conversions.convertLitresToGallons(currentFuel) <= 0.5f && !played1LitreWarning)
                            {
                                //^^
                                played1LitreWarning = true;
                                if (canPlayFuelMessage())
                                {
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/level", 0, messageFragments: MessageContents(folderHalfAGallonRemaining), abstractEvent: this, priority: 10));
                                    lastFuelCall = currentGameState.Now;
                                }
                            }
                        }
                        else
                        {
                            if (currentFuel <= 2 && !played2LitreWarning)
                            {
                                played2LitreWarning = true;
                                if (canPlayFuelMessage())
                                {
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/level", 0, messageFragments: MessageContents(2, folderLitresRemaining), abstractEvent: this, priority: 10));
                                    lastFuelCall = currentGameState.Now;
                                }
                            }
                            else if (currentFuel <= 1 && !played1LitreWarning)
                            {
                                played1LitreWarning = true;
                                if (canPlayFuelMessage())
                                {
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/level", 0, messageFragments: MessageContents(folderOneLitreRemaining), abstractEvent: this, priority: 10));
                                    lastFuelCall = currentGameState.Now;
                                }
                            }
                        }
                    }

                    // warnings for fixed lap sessions
                    float averageUsagePerLapToCheck = getConsumptionPerLap();
                    float averageUsagePerMinuteToCheck = getConsumptionPerMinute();
                    if (currentGameState.SessionData.IsNewLap && averageUsagePerLapToCheck > 0 &&
                        currentGameState.FuelData.FuelLeft > 0 &&
                        (currentGameState.SessionData.SessionNumberOfLaps > 0 ||
                            currentGameState.SessionData.SessionType == SessionType.HotLap ||
                            currentGameState.SessionData.SessionType == SessionType.LonePractice) &&
                        lapsCompletedSinceFuelReset > 0)
                    {
                        int estimatedFuelLapsLeft = (int)Math.Floor(currentGameState.FuelData.FuelLeft / averageUsagePerLapToCheck);
                        if (halfDistance != -1 && currentGameState.SessionData.SessionType == SessionType.Race && currentGameState.SessionData.CompletedLaps == halfDistance)
                        {
                            if (estimatedFuelLapsLeft <= halfDistance)
                            {
                                if (currentGameState.PitData.IsRefuellingAllowed)
                                {
                                    if (canPlayFuelMessage())
                                    {
                                        audioPlayer.playMessage(new QueuedMessage("Fuel/estimate", 0,
                                            messageFragments: MessageContents(RaceTime.folderHalfWayHome,
                                            folderWeEstimate,
                                            MessageFragment.Integer(estimatedFuelLapsLeft, MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)),
                                            folderLapsRemaining),
                                            abstractEvent: this, priority: 7));
                                        lastFuelCall = currentGameState.Now;
                                    }
                                    else
                                    {
                                        audioPlayer.playMessage(new QueuedMessage("Fuel/halfWayHome", 0,
                                            messageFragments: MessageContents(RaceTime.folderHalfWayHome), abstractEvent: this, priority: 7));
                                    }
                                }
                                else
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderHalfDistanceLowFuel, 0, abstractEvent: this, priority: 7));
                                }
                            }
                            else
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderHalfDistanceGoodFuel, 0, abstractEvent: this, priority: 5));
                            }
                        }
                        else if (lapsRemaining > 3 && estimatedFuelLapsLeft == 4)
                        {
                            Log.Fuel("lgcy: 4 laps fuel left, starting fuel = " + litresToUnits(initialFuelLevel, false) +
                                    ", current fuel = " + litresToUnits(currentGameState.FuelData.FuelLeft, false) + ", usage per lap = " + litresToUnits(averageUsagePerLapToCheck, true));
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderFourLapsEstimate, 0, abstractEvent: this, priority: 3));
                                lastFuelCall = currentGameState.Now;
                            }
                        }
                        else if (lapsRemaining > 2 && estimatedFuelLapsLeft == 3)
                        {
                            Log.Fuel("lgcy: 3 laps fuel left, starting fuel = " + litresToUnits(initialFuelLevel, false) +
                                    ", current fuel = " + litresToUnits(currentGameState.FuelData.FuelLeft, false) + ", usage per lap = " + litresToUnits(averageUsagePerLapToCheck, true));
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderThreeLapsEstimate, 0, abstractEvent: this, priority: 5));
                                lastFuelCall = currentGameState.Now;
                            }
                        }
                        else if (lapsRemaining > 1 && estimatedFuelLapsLeft == 2)
                        {
                            Log.Fuel("lgcy: 2 laps fuel left, starting fuel = " + litresToUnits(initialFuelLevel, false) +
                                    ", current fuel = " + litresToUnits(currentGameState.FuelData.FuelLeft, false) + ", usage per lap = " + litresToUnits(averageUsagePerLapToCheck, true));
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderTwoLapsEstimate, 0, abstractEvent: this, priority: 7));
                                lastFuelCall = currentGameState.Now;
                            }
                        }
                        else if (lapsRemaining > 0 && estimatedFuelLapsLeft == 1)
                        {
                            Log.Fuel("lgcy: 1 lap fuel left, starting fuel = " + litresToUnits(initialFuelLevel, false) +
                                    ", current fuel = " + litresToUnits(currentGameState.FuelData.FuelLeft, false) + ", usage per lap = " + litresToUnits(averageUsagePerLapToCheck, true));
                            audioPlayer.playMessage(new QueuedMessage(folderOneLapEstimate, 0, abstractEvent: this, priority: 10));
                            lastFuelCall = currentGameState.Now;
                            // if we've not played the pit-now message, play it with a bit of a delay - should probably wait for sector3 here
                            // but i'd have to move some stuff around and I'm an idle fucker
                            if (((crossedIntoSector3 && !playedPitForFuelNowLastWarning) || !playedPitForFuelNow) && lapsRemaining > 1)
                            {
                                playedPitForFuelNow = true;
                                if (crossedIntoSector3)
                                {
                                    playedPitForFuelNowLastWarning = true;
                                }
                                audioPlayer.playMessage(new QueuedMessage(PitStops.folderMandatoryPitStopsPitThisLap, 0, secondsDelay: 10, abstractEvent: this, priority: 7));
                            }
                        }
                    }

                    // warnings for fixed time sessions - check every 5 seconds
                    else if (currentGameState.Now > nextFuelStatusCheck && currentGameState.FuelData.FuelLeft > 0 &&
                        currentGameState.SessionData.SessionNumberOfLaps <= 0 && currentGameState.SessionData.SessionTotalRunTime > 0 && averageUsagePerMinuteToCheck > 0)
                    {
                        float benchmarkLaptime = currentGameState.TimingData.getPlayerBestLapTime();
                        if (benchmarkLaptime <= 0)
                        {
                            benchmarkLaptime = currentGameState.TimingData.getPlayerClassBestLapTime();
                        }
                        nextFuelStatusCheck = currentGameState.Now.Add(fuelStatusCheckInterval);
                        if (halfTime != -1 && !playedHalfTimeFuelEstimate && currentGameState.SessionData.SessionTimeRemaining <= halfTime &&
                            currentGameState.SessionData.SessionTimeRemaining > halfTime - 30)
                        {
                            Log.Fuel("lgcy: Half race distance. Fuel in tank = " + litresToUnits(currentGameState.FuelData.FuelLeft, false) +
                                ", average usage per minute = " + litresToUnits(averageUsagePerMinuteToCheck, true));
                            playedHalfTimeFuelEstimate = true;
                            if (currentGameState.SessionData.SessionType == SessionType.Race)
                            {
                                float slackAmount = averageUsagePerLapToCheck > 0 ? averageUsagePerLapToCheck : 2f;
                                // need a bit of slack in this estimate:
                                float fuelToEnd = averageUsagePerMinuteToCheck * (halfTime + benchmarkLaptime) / 60;
                                if (fuelToEnd > currentGameState.FuelData.FuelLeft)
                                {
                                    if (currentGameState.PitData.IsRefuellingAllowed)
                                    {
                                        if (canPlayFuelMessage())
                                        {
                                            int minutesLeft = (int)Math.Floor(currentGameState.FuelData.FuelLeft / averageUsagePerMinuteToCheck);
                                            audioPlayer.playMessage(new QueuedMessage("Fuel/estimate", 0,
                                                messageFragments: MessageContents(RaceTime.folderHalfWayHome, folderWeEstimate, minutesLeft, folderMinutesRemaining), abstractEvent: this, priority: 7));
                                            lastFuelCall = currentGameState.Now;
                                        }
                                        else
                                        {
                                            audioPlayer.playMessage(new QueuedMessage("Fuel/halfWayHome", 0,
                                                messageFragments: MessageContents(RaceTime.folderHalfWayHome), abstractEvent: this, priority: 7));
                                        }
                                    }
                                    else
                                    {
                                        audioPlayer.playMessage(new QueuedMessage(folderHalfDistanceLowFuel, 0, abstractEvent: this, priority: 7));
                                    }
                                }
                                else if (currentGameState.FuelData.FuelLeft - fuelToEnd <= slackAmount)
                                {
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/estimate", 0,
                                        messageFragments: MessageContents(RaceTime.folderHalfWayHome, folderFuelWillBeTight), abstractEvent: this, priority: 7));
                                }
                                else
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderHalfDistanceGoodFuel, 0, abstractEvent: this, priority: 7));
                                }
                            }
                        }

                        float estimatedFuelMinutesLeft = currentGameState.FuelData.FuelLeft / averageUsagePerMinuteToCheck;
                        float estimatedFuelTimeRemaining = 2.0f;
                        estimatedFuelTimeRemaining = ((benchmarkLaptime / 60) * 1.1f) + ((benchmarkLaptime - currentGameState.SessionData.LapTimeCurrent) / 60);
                        if (estimatedFuelMinutesLeft < estimatedFuelTimeRemaining && (!playedPitForFuelNow || (!playedPitForFuelNowLastWarning && crossedIntoSector3)))
                        {
                            if (crossedIntoSector3)
                            {
                                playedPitForFuelNowLastWarning = true;
                            }
                            playedPitForFuelNow = true;
                            playedTwoMinutesRemaining = true;
                            playedFiveMinutesRemaining = true;
                            playedTenMinutesRemaining = true;
                            float cutoffForRefuelCall = 120;
                            //  needs to be <= as PlayerLapTimeSessionBest is initialized to -1
                            if (benchmarkLaptime != -1)
                            {
                                cutoffForRefuelCall = benchmarkLaptime * 2;
                            }
                            if (!currentGameState.PitData.InPitlane)
                            {
                                // call the player in to the pit for practice and race sessions, leave him out for qual (he may be doing a low fuel lap)
                                if ((currentGameState.SessionData.SessionType == SessionType.Race || currentGameState.SessionData.SessionType == SessionType.Practice)
                                    && currentGameState.SessionData.SessionTimeRemaining > cutoffForRefuelCall)
                                {
                                    audioPlayer.playMessage(new QueuedMessage("pit_for_fuel_now", 0,
                                        messageFragments: MessageContents(folderAboutToRunOut, PitStops.folderMandatoryPitStopsPitThisLap), abstractEvent: this, priority: 10));
                                }
                                else
                                {
                                    // going to run out, but don't call the player into the pits - it's up to him
                                    audioPlayer.playMessage(new QueuedMessage("about_to_run_out_of_fuel", 0, messageFragments: MessageContents(folderAboutToRunOut), abstractEvent: this, priority: 10));
                                }
                            }
                        }
                        if (estimatedFuelMinutesLeft <= 2 && estimatedFuelMinutesLeft > 1.8 && !playedTwoMinutesRemaining)
                        {
                            playedTwoMinutesRemaining = true;
                            playedFiveMinutesRemaining = true;
                            playedTenMinutesRemaining = true;
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderTwoMinutesFuel, 0, abstractEvent: this, priority: 10));
                                lastFuelCall = currentGameState.Now;
                            }
                        }
                        else if (estimatedFuelMinutesLeft <= 5 && estimatedFuelMinutesLeft > 4.8 && !playedFiveMinutesRemaining)
                        {
                            playedFiveMinutesRemaining = true;
                            playedTenMinutesRemaining = true;
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderFiveMinutesFuel, 0, abstractEvent: this, priority: 7));
                                lastFuelCall = currentGameState.Now;
                            }
                        }
                        else if (estimatedFuelMinutesLeft <= 10 && estimatedFuelMinutesLeft > 9.8 && !playedTenMinutesRemaining)
                        {
                            playedTenMinutesRemaining = true;
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderTenMinutesFuel, 0, abstractEvent: this, priority: 3));
                                lastFuelCall = currentGameState.Now;
                            }
                        }
                        else if (!playedHalfTankWarning && currentGameState.FuelData.FuelLeft / initialFuelLevel <= 0.50 &&
                            currentGameState.FuelData.FuelLeft / initialFuelLevel >= 0.47 && !hasBeenRefuelled)
                        {
                            // warning message for fuel left - these play as soon as the fuel reaches 1/2 tank left
                            playedHalfTankWarning = true;
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderHalfTankWarning, 0, abstractEvent: this, priority: 0));
                                lastFuelCall = currentGameState.Now;
                            }
                        }
                    }

                    // This section only triggers in sessions where there is a single pitstop enforced by fuel limit
                    if (!gotPredictedPitWindow && currentGameState.SessionData.SessionType == SessionType.Race &&
                        !currentGameState.PitData.HasMandatoryPitStop &&
                        previousGameState != null && previousGameState.SessionData.SectorNumber == 1 && currentGameState.SessionData.SectorNumber == 2)
                    {
                        Tuple<int, int> predictedWindow = getPredictedPitWindow(currentGameState);
                        // item1 is the earliest minute / lap we can pit on, item2 is the latest. Note that item1 might be negative if
                        // we *could* have finished the race without refuelling (if we'd filled the tank). It might also be less than the
                        // number of minutes / laps completed

                        if (predictedWindow.Item2 != -1)
                        {
                            if (sessionHasHadFCY)
                            {
                                Console.WriteLine("lgcy: skipping pit window announcement because there's been a full course yellow in this session so the data may be inaccurate");
                            }
                            else if (sessionHasFixedNumberOfLaps)
                            {
                                // sanity check this
                                int lapLimit = 2;
                                if (currentGameState.SessionData.TrackDefinition.trackLengthClass == TrackData.TrackLengthClass.VERY_LONG ||
                                    currentGameState.SessionData.TrackDefinition.trackLengthClass == TrackData.TrackLengthClass.LONG)
                                {
                                    lapLimit = 1;
                                }
                                else if (currentGameState.SessionData.TrackDefinition.trackLengthClass == TrackData.TrackLengthClass.VERY_SHORT ||
                                    currentGameState.SessionData.TrackDefinition.trackLengthClass == TrackData.TrackLengthClass.SHORT)
                                {
                                    lapLimit = 4;
                                }
                                if (predictedWindow.Item2 > currentGameState.SessionData.SessionNumberOfLaps - lapLimit)
                                {
                                    Console.WriteLine("lgcy: Skipping fuel window announcement because we might make it on fuel");
                                }
                                // if item1 is < current minute but item2 is sensible, we want to say "pit window for fuel closes after X laps"
                                else if (predictedWindow.Item1 < currentGameState.SessionData.CompletedLaps)
                                {
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/pit_window_for_fuel", 0, secondsDelay: Utilities.random.Next(8),
                                        messageFragments: MessageContents(folderWillNeedToPitForFuelByLap, predictedWindow.Item2)));
                                    playedPitWindowEstimate = true;
                                }
                                else
                                {
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/pit_window_for_fuel", 0, secondsDelay: Utilities.random.Next(8),
                                        messageFragments: MessageContents(folderFuelWindowOpensOnLap, predictedWindow.Item1, folderAndFuelWindowClosesOnLap, predictedWindow.Item2)));
                                    playedPitWindowEstimate = true;
                                }
                            }
                            else
                            {
                                // sanity check
                                if (predictedWindow.Item2 > (currentGameState.SessionData.SessionTotalRunTime / 60) - 5)
                                {
                                    Console.WriteLine("lgcy: Skipping fuel window announcement because we might make it on fuel");
                                }
                                // if item1 is < current minute, we want to say "pit window for fuel closes after X minutes"
                                else if (predictedWindow.Item1 < currentGameState.SessionData.SessionRunningTime / 60)
                                {
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/pit_window_for_fuel", 0, secondsDelay: Utilities.random.Next(8),
                                        messageFragments: MessageContents(folderWillNeedToPitForFuelByTimeIntro, TimeSpanWrapper.FromMinutes(predictedWindow.Item2, Precision.MINUTES), folderWillNeedToPitForFuelByTimeOutro)));
                                    playedPitWindowEstimate = true;
                                }
                                else
                                {
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/pit_window_for_fuel", 0, secondsDelay: Utilities.random.Next(8),
                                        messageFragments: MessageContents(folderFuelWindowOpensAfterTime, TimeSpanWrapper.FromMinutes(predictedWindow.Item1, Precision.MINUTES),
                                        folderAndFuelWindowClosesAfterTime, TimeSpanWrapper.FromMinutes(predictedWindow.Item2, Precision.MINUTES))));
                                    playedPitWindowEstimate = true;
                                }
                            }
                        }
                    }

                    if (gotPredictedPitWindow && playedPitWindowEstimate && !playedPitWindowOpen && currentGameState.SessionData.SessionType == SessionType.Race &&
                        !currentGameState.PitData.HasMandatoryPitStop &&
                        // check every 5 sec regardless if its a time limited or lap limited race, we want to know this as soon as possible. 
                        currentGameState.Now > nextFuelPitWindowOpenCheck)
                    {
                        nextFuelPitWindowOpenCheck = currentGameState.Now.Add(fuelStatusCheckInterval);
                        float litresNeeded = getAdditionalFuelToEndOfRace(true, false);
                        if (litresNeeded <= fuelCapacity - currentFuel)
                        {
                            //Console.WriteLine($"Pit Window is now open, Litres Needed: {litresNeeded}");
                            playedPitWindowOpen = true;
                            audioPlayer.playMessage(new QueuedMessage(PitStops.folderMandatoryPitStopsPitWindowOpen, 0, abstractEvent: this, priority: 10));
                        }
                    }
                }
            }
        }

        /// <summary>
        /// Speak the mean fuel use per lap
        /// </summary>
        /// <param name="individualResponse">Speak just the fuel use...</param>
        /// <param name="messageFragments">...or add it to the stream of things being said</param>
        /// <returns>false: fuel use is less than 0.1 litres or gallons per lap</returns>
        private Boolean reportFuelConsumption(Boolean individualResponse, List<MessageFragment> messageFragments)
        {
            Boolean haveData = false;
            if (fuelUseActive && averageUsagePerLap > 0)
            {
                // round to 1dp
                float roundedAverageUsePerLap;
                if (fuelReportsInGallons())
                {
                    roundedAverageUsePerLap = ((float)Math.Round(Utilities.Conversions.convertLitresToGallons(averageUsagePerLap, false) * 10f)) / 10f;
                }
                else
                {
                    roundedAverageUsePerLap = ((float)Math.Round(averageUsagePerLap * 10f)) / 10f;
                }
                if (roundedAverageUsePerLap <= 0)
                {
                    // rounded fuel use is < 0.1 litres or gallons per lap - can't really do anything with this.
                    return false;
                }
                Tuple<int, int> wholeandfractional = Utilities.WholeAndFractionalPart(roundedAverageUsePerLap);
                QueuedMessage queuedMessage = null;
                haveData = true;

                if (wholeandfractional.Item2 > 0)
                {
                    if (fuelReportsInGallons())
                    {
                        queuedMessage = new QueuedMessage("Fuel/mean_use_per_lap", 0,
                                messageFragments: MessageContents(wholeandfractional.Item1, NumberReader.folderPoint, wholeandfractional.Item2, folderGallonsPerLap));

                        if (!individualResponse)
                        {
                            messageFragments.AddRange(MessageContents(wholeandfractional.Item1, NumberReader.folderPoint, wholeandfractional.Item2, folderGallonsPerLap));
                        }
                    }
                    else
                    {
                        queuedMessage = new QueuedMessage("Fuel/mean_use_per_lap", 0,
                                messageFragments: MessageContents(wholeandfractional.Item1, NumberReader.folderPoint, wholeandfractional.Item2, folderLitresPerLap));

                        if (!individualResponse)
                        {
                            messageFragments.AddRange(MessageContents(wholeandfractional.Item1, NumberReader.folderPoint, wholeandfractional.Item2, folderLitresPerLap));
                        }
                    }
                }
                else
                {
                    if (fuelReportsInGallons())
                    {
                        queuedMessage = new QueuedMessage("Fuel/mean_use_per_lap", 0,
                                messageFragments: MessageContents(wholeandfractional.Item1, folderGallonsPerLap));

                        if (!individualResponse)
                        {
                            messageFragments.AddRange(MessageContents(wholeandfractional.Item1, folderGallonsPerLap));
                        }
                    }
                    else
                    {
                        queuedMessage = new QueuedMessage("Fuel/mean_use_per_lap", 0,
                                messageFragments: MessageContents(wholeandfractional.Item1, folderLitresPerLap));

                        if (!individualResponse)
                        {
                            messageFragments.AddRange(MessageContents(wholeandfractional.Item1, folderLitresPerLap));
                        }
                    }                    
                }

                Debug.Assert(queuedMessage != null);
                if (individualResponse
                    && queuedMessage != null)
                {
                    if (this.delayResponses && Utilities.random.Next(10) >= 2 && SoundCache.availableSounds.Contains(AudioPlayer.folderStandBy))
                    {
                        this.audioPlayer.pauseQueueAndPlayDelayedImmediateMessage(queuedMessage, 5 /*lowerDelayBoundInclusive*/, 8 /*upperDelayBound*/);
                    }
                    else
                    {
                        this.audioPlayer.playMessageImmediately(queuedMessage);
                    }
                }
            }
            return haveData;
        }

        /// <summary>
        /// Used by "How much fuel for x laps?"
        /// </summary>
        /// <param name="numberOfLaps"></param>
        /// <returns></returns>
        private Boolean reportFuelConsumptionForLaps(int numberOfLaps)
        {
            Boolean haveData = false;
            if (fuelUseActive && averageUsagePerLap > 0)
            {
                // round up
                float totalUsage = 0f;
                if(fuelReportsInGallons())
                {
                    totalUsage = Utilities.Conversions.convertLitresToGallons(averageUsagePerLap * numberOfLaps, true);
                }
                else
                {
                    totalUsage = (float)Math.Ceiling(averageUsagePerLap * numberOfLaps);
                }
                if (totalUsage > 0)
                {
                    haveData = true;
                    // build up the message fragments the verbose way, so we can prevent the number reader from shortening hundreds to
                    // stuff like "one thirty two" - we always want "one hundred and thirty two"
                    List<MessageFragment> messageFragments = new List<MessageFragment>();
                    messageFragments.Add(MessageFragment.Text(folderFor));
                    messageFragments.Add(MessageFragment.Integer(numberOfLaps, false, MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)));
                    messageFragments.Add(MessageFragment.Text(Battery.folderLaps));
                    messageFragments.Add(MessageFragment.Text(folderWeEstimateWeWillNeed));
                    if(fuelReportsInGallons())
                    {
                        // for gallons we want both whole and fractional part cause its a stupid unit.
                        Tuple<int, int> wholeandfractional = Utilities.WholeAndFractionalPart(totalUsage);
                        if (wholeandfractional.Item2 > 0)
                        {
                            messageFragments.AddRange(MessageContents(wholeandfractional.Item1, NumberReader.folderPoint, wholeandfractional.Item2, folderGallons));
                        }
                        else
                        {
                            int usage = Convert.ToInt32(wholeandfractional.Item1);
                            messageFragments.Add(MessageFragment.Integer(usage, false));
                            messageFragments.Add(MessageFragment.Text(usage == 1 ? folderGallon : folderGallons));
                        }
                    }
                    else
                    {
                        int usage = Convert.ToInt32(totalUsage);
                        messageFragments.Add(MessageFragment.Integer(usage, false));
                        messageFragments.Add(MessageFragment.Text(usage == 1 ? folderLitre : folderLitres));
                    }

                    if (messageFragments.Count > 0)
                    {
                        QueuedMessage fuelEstimateMessage = new QueuedMessage("Fuel/estimate", 0, messageFragments: messageFragments);

                        // play this immediately or play "stand by", and queue it to be played in a few seconds
                        if (delayResponses && Utilities.random.Next(10) >= 2 && SoundCache.availableSounds.Contains(AudioPlayer.folderStandBy))
                        {
                            audioPlayer.pauseQueueAndPlayDelayedImmediateMessage(fuelEstimateMessage, 5 /*lowerDelayBoundInclusive*/, 8 /*upperDelayBound*/);
                        }
                        else
                        {
                            audioPlayer.playMessageImmediately(fuelEstimateMessage);
                        }
                    }
                }
            }
            return haveData;
        }
        /// <summary>
        /// Used by "How much fuel for x hours/minutes?"
        /// </summary>
        /// <param name="hours"></param>
        /// <param name="minutes"></param>
        /// <returns></returns>
        private Boolean reportFuelConsumptionForTime(int hours, int minutes)
        {
            Boolean haveData = false;
            float averageUsagePerMinuteToCheck = getConsumptionPerMinute();
            if (fuelUseActive && averageUsagePerMinuteToCheck > 0)
            {
                int timeToUse = (hours * 60) + minutes;
                // round up
                float totalUsage = 0;
                if(fuelReportsInGallons())
                {
                    totalUsage = Utilities.Conversions.convertLitresToGallons(averageUsagePerMinuteToCheck * timeToUse, true);
                }
                else
                {
                    totalUsage = ((float)Math.Ceiling(averageUsagePerMinuteToCheck * timeToUse));
                }
                if (totalUsage > 0)
                {
                    haveData = true;
                    // build up the message fragments the verbose way, so we can prevent the number reader from shortening hundreds to
                    // stuff like "one thirty two" - we always want "one hundred and thirty two"
                    List<MessageFragment> messageFragments = new List<MessageFragment>();
                    messageFragments.Add(MessageFragment.Text(folderFor));
                    messageFragments.Add(MessageFragment.Time(TimeSpanWrapper.FromMinutes(timeToUse, Precision.MINUTES)));
                    messageFragments.Add(MessageFragment.Text(folderWeEstimateWeWillNeed));
                    if (fuelReportsInGallons())
                    {
                        // for gallons we want both whole and fractional part cause its a stupid unit.
                        Tuple<int, int> wholeandfractional = Utilities.WholeAndFractionalPart(totalUsage);
                        if (wholeandfractional.Item2 > 0)
                        {
                            messageFragments.AddRange(MessageContents(wholeandfractional.Item1, NumberReader.folderPoint, wholeandfractional.Item2, folderGallons));
                        }
                        else
                        {
                            int usage = Convert.ToInt32(wholeandfractional.Item1);
                            messageFragments.Add(MessageFragment.Integer(usage, false));
                            messageFragments.Add(MessageFragment.Text(usage == 1 ? folderGallon : folderGallons));
                        }
                    }
                    else
                    {
                        int usage = Convert.ToInt32(totalUsage);
                        messageFragments.Add(MessageFragment.Integer(usage, false));
                        messageFragments.Add(MessageFragment.Text(usage == 1 ? folderLitre : folderLitres));
                    }

                    if (messageFragments.Count > 0)
                    {
                        QueuedMessage fuelEstimateMessage = new QueuedMessage("Fuel/estimate", 0, messageFragments: messageFragments);
                        // play this immediately or play "stand by", and queue it to be played in a few seconds
                        if (delayResponses && Utilities.random.Next(10) >= 2 && SoundCache.availableSounds.Contains(AudioPlayer.folderStandBy))
                        {
                            audioPlayer.pauseQueueAndPlayDelayedImmediateMessage(fuelEstimateMessage, 5 /*lowerDelayBoundInclusive*/, 8 /*upperDelayBound*/);
                        }
                        else
                        {
                            audioPlayer.playMessageImmediately(fuelEstimateMessage);
                        }
                    }
                }
            }
            return haveData;
        }
        /// <summary>
        /// Give the best report of the fuel remaining in laps/time or just litres/gallons
        /// </summary>
        /// <param name="allowNoDataMessage">this is a fuel specific command response
        /// report "Plenty of fuel" if no consumption data is available </param>
        /// <param name="messageFragments">list that may be added to</param>
        /// <returns>Reported something about fuel</returns>
        private Boolean reportFuelRemaining(Boolean allowNoDataMessage, List<MessageFragment> messageFragments)
        {
            Boolean reportedSomething = false;
            float averageUsagePerLapToCheck = getConsumptionPerLap();

            void reportLapsOfFuelLeft()
            {
                int lapsOfFuelLeft = (int)Math.Floor(currentFuel / averageUsagePerLapToCheck);
                messageFragments.Add(MessageFragment.Text(folderWeEstimate));
                messageFragments.Add(MessageFragment.Integer(lapsOfFuelLeft, false, MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)));
                messageFragments.Add(MessageFragment.Text(folderLapsRemaining));
            }

            if (initialised && currentFuel > -1)
            {
                if (sessionHasFixedNumberOfLaps && averageUsagePerLapToCheck > 0)
                {
                    reportedSomething = true;
                    int lapsOfFuelLeft = (int)Math.Floor(currentFuel / averageUsagePerLapToCheck);
                    if (lapsOfFuelLeft <= 1)
                    {
                        messageFragments.Add(MessageFragment.Text(folderAboutToRunOut));
                    }
                    else
                    {
                        reportLapsOfFuelLeft();
                    }
                }
                else if (averageUsagePerMinute > 0)
                {
                    reportedSomething = true;
                    int minutesOfFuelLeft = (int)Math.Floor(currentFuel / averageUsagePerMinute);
                    if (minutesOfFuelLeft <= 1)
                    {
                        messageFragments.Add(MessageFragment.Text(folderAboutToRunOut));
                    }
                    else if (reportFuelLapsLeftInTimedRaces && averageUsagePerLapToCheck > 0)
                    {
                        reportLapsOfFuelLeft();
                    }
                    else
                    {
                        messageFragments.Add(MessageFragment.Text(folderWeEstimate));
                        messageFragments.Add(MessageFragment.Integer(minutesOfFuelLeft, false));
                        messageFragments.Add(MessageFragment.Text(folderMinutesRemaining));
                    }
                }
                if (CrewChief.currentGameState != null && CrewChief.currentGameState.Now != null)
                    lastFuelCall = CrewChief.currentGameState.Now;
            }
            if (!reportedSomething)
            {
                if (!fuelUseActive && allowNoDataMessage)
                {
                    reportedSomething = true;
                    messageFragments.Add(MessageFragment.Text(folderPlentyOfFuel));
                } // else report amount of fuel
                else if (fuelReportsInGallons())
                {
                    float gallons = Utilities.Conversions.convertLitresToGallons(currentFuel);
                    if (gallons >= 2)
                    {
                        reportedSomething = true;
                        // for gallons we want both whole and fractional part cause its a stupid unit.
                        Tuple<int, int> wholeandfractional = Utilities.WholeAndFractionalPart(
                            Utilities.Conversions.convertLitresToGallons(currentFuel, true));
                        if (wholeandfractional.Item2 > 0)
                        {
                            messageFragments.AddRange(MessageContents(wholeandfractional.Item1, NumberReader.folderPoint, wholeandfractional.Item2, folderGallonsRemaining));
                        }
                        else
                        {
                            messageFragments.Add(MessageFragment.Integer(Convert.ToInt32(wholeandfractional.Item1), false));
                            messageFragments.Add(MessageFragment.Text(folderGallonsRemaining));
                        }
                    }
                    else if (gallons >= 1)
                    {
                        reportedSomething = true;
                        messageFragments.Add(MessageFragment.Text(folderOneGallonRemaining));
                    }
                    else if (gallons > 0.5f)
                    {
                        reportedSomething = true;
                        messageFragments.Add(MessageFragment.Text(folderHalfAGallonRemaining));
                    }
                    else if (gallons > 0)
                    {
                        reportedSomething = true;
                        messageFragments.Add(MessageFragment.Text(folderAboutToRunOut));
                    }
                    if (CrewChief.currentGameState != null && CrewChief.currentGameState.Now != null)
                        lastFuelCall = CrewChief.currentGameState.Now;
                }
                else // !fuelReportsInGallon
                {
                    if (currentFuel >= 2)
                    {
                        reportedSomething = true;
                        messageFragments.Add(MessageFragment.Integer((int)currentFuel, false));
                        messageFragments.Add(MessageFragment.Text(folderLitresRemaining));
                    }
                    else if (currentFuel >= 1)
                    {
                        reportedSomething = true;
                        messageFragments.Add(MessageFragment.Text(folderOneLitreRemaining));
                    }
                    else if (currentFuel > 0)
                    {
                        reportedSomething = true;
                        messageFragments.Add(MessageFragment.Text(folderAboutToRunOut));
                    }
                    if (CrewChief.currentGameState != null && CrewChief.currentGameState.Now != null)
                        lastFuelCall = CrewChief.currentGameState.Now;
                }
            }

            return reportedSomething;
        }

        /// <summary>
        /// "Plenty of fuel" / "Fuel will be tight" / "You need to pit" / etc.
        /// </summary>
        /// <param name="allowNoDataMessage">this is fuel specific command response -
        /// "How's my fuel?" or "Report fuel/battery status"</param>
        /// <param name="isRace"></param>
        public void reportFuelStatus(Boolean allowNoDataMessage, Boolean isRace)
        {
            if (!GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.FUEL) ||
                !CrewChief.fuelMultiplier.active)
            {
                if (allowNoDataMessage)
                {
                    this.audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                }
                return;
            }

            var fuelStatusMessageFragments = new List<MessageFragment>();
            Boolean reportedRemaining = reportFuelRemaining(allowNoDataMessage, fuelStatusMessageFragments);
            Boolean reportedConsumption = reportFuelConsumption(false /*individualResponse*/, fuelStatusMessageFragments);
            Boolean reportedFuelNeeded = false;
            Boolean isSufficientTimeToSaveFuel = false;
            Boolean isCloseToRaceEnd = false;
            if (CrewChief.currentGameState != null)
            {
                if (CrewChief.currentGameState.SessionData.SessionHasFixedTime)
                {
                    isSufficientTimeToSaveFuel = CrewChief.currentGameState.SessionData.SessionTimeRemaining > 500;
                    isCloseToRaceEnd = (CrewChief.currentGameState.SessionData.SessionTimeRemaining < 120 && CrewChief.currentGameState.SessionData.SessionTimeRemaining > -1)
                        || CrewChief.currentGameState.SessionData.IsLastLap;
                }
                else
                {
                    switch (CrewChief.currentGameState.SessionData.TrackDefinition.trackLengthClass)
                    {
                        case TrackData.TrackLengthClass.VERY_LONG:
                            isSufficientTimeToSaveFuel = lapsRemaining >= 1;
                            isCloseToRaceEnd = lapsRemaining <= 1;
                            break;
                        case TrackData.TrackLengthClass.LONG:
                            isSufficientTimeToSaveFuel = lapsRemaining >= 2;
                            isCloseToRaceEnd = lapsRemaining <= 2;
                            break;
                        case TrackData.TrackLengthClass.MEDIUM:
                            isSufficientTimeToSaveFuel = lapsRemaining >= 4;
                            isCloseToRaceEnd = lapsRemaining <= 2;
                            break;
                        case TrackData.TrackLengthClass.SHORT:
                            isSufficientTimeToSaveFuel = lapsRemaining >= 5;
                            isCloseToRaceEnd = lapsRemaining <= 2;
                            break;
                        case TrackData.TrackLengthClass.VERY_SHORT:
                            isSufficientTimeToSaveFuel = lapsRemaining >= 6;
                            isCloseToRaceEnd = lapsRemaining <= 3;
                            break;
                    }
                }
            }
            if (isRace)
            {
                float extraFuelToEnd = getAdditionalFuelToEndOfRace(false);
                if (extraFuelToEnd != NO_FUEL_DATA)
                {
                    float halfALap = fuelForHalfALap();

                    // extraFuelToEnd to end is a measure of how much fuel we need to add to get to the end. If it's
                    // negative we have fuel to spare
                    if (extraFuelToEnd <= 0 && extraFuelToEnd * -1 < halfALap)
                    {
                        reportedFuelNeeded = true;
                        // we expect to have sufficient fuel, but it'll be tight. LitresToEnd * -1 is how much we expect
                        // to have left over
                        fuelStatusMessageFragments.Add(MessageFragment.Text(folderFuelShouldBeOK));
                    }
                    else if (extraFuelToEnd > 0)
                    {
                        // we need some fuel - see if we might be able stretch it
                        if (extraFuelToEnd < halfALap && isSufficientTimeToSaveFuel)
                        {
                            reportedFuelNeeded = true;
                            // unlikely to make it, we'll have to fuel save
                            fuelStatusMessageFragments.Add(MessageFragment.Text(folderFuelWillBeTight));
                        }
                        else if (!isCloseToRaceEnd)
                        {
                            if (fuelReportsInGallons())
                            {
                                // for gallons we want both whole and fractional part cause its a stupid unit.
                                float gallonsNeeded = Utilities.Conversions.convertLitresToGallons(extraFuelToEnd, true);
                                Tuple<int, int> wholeandfractional = Utilities.WholeAndFractionalPart(gallonsNeeded);
                                if (wholeandfractional.Item2 > 0)
                                {
                                    reportedFuelNeeded = true;
                                    fuelStatusMessageFragments.AddRange(MessageContents(folderWillNeedToAdd, wholeandfractional.Item1, NumberReader.folderPoint, wholeandfractional.Item2, folderGallonsToGetToTheEnd));
                                }
                                else
                                {
                                    reportedFuelNeeded = true;
                                    int wholeGallons = Convert.ToInt32(wholeandfractional.Item1);
                                    fuelStatusMessageFragments.AddRange(MessageContents(wholeGallons, wholeGallons == 1 ? folderWillNeedToAddOneGallonToGetToTheEnd : folderWillNeedToAdd, wholeGallons, folderGallonsToGetToTheEnd));
                                }
                            }
                            else
                            {
                                reportedFuelNeeded = true;
                                fuelStatusMessageFragments.AddRange(MessageContents(folderWillNeedToAdd, (int)Math.Ceiling(extraFuelToEnd), folderLitresToGetToTheEnd));
                            }
                        }
                    }
                    if (reportedFuelNeeded)
                    {
                        if (CrewChief.currentGameState != null && CrewChief.currentGameState.Now != null)
                            lastFuelCall = CrewChief.currentGameState.Now;
                    }
                }
            }

            if (!reportedConsumption && !reportedRemaining && !reportedFuelNeeded && allowNoDataMessage)
            {
                audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
            }
            else
            {
                if (fuelStatusMessageFragments.Count > 0)
                {
                    if (allowNoDataMessage  // True if this is fuel specific command response.
                        && this.delayResponses && Utilities.random.Next(10) >= 2 && SoundCache.availableSounds.Contains(AudioPlayer.folderStandBy))
                    {
                        this.audioPlayer.pauseQueueAndPlayDelayedImmediateMessage(new QueuedMessage("Fuel/status", 0, messageFragments: fuelStatusMessageFragments), 3 /*lowerDelayBoundInclusive*/, 6 /*upperDelayBound*/);
                    }
                    else
                    {
                        this.audioPlayer.playMessageImmediately(new QueuedMessage("Fuel/status", 0, messageFragments: fuelStatusMessageFragments));
                    }
                }
            }
        }

        /// <summary>
        /// Get a quick n dirty estimate of how many litres for half a lap.
        /// Base this on consumption per lap if we have it, otherwise use track length.
        /// </summary>
        private float fuelForHalfALap()
        {
            float closeFuelAmount = HALF_LAP_RESERVE_DEFAULT;
            float playerBestLapTime = CrewChief.currentGameState != null ? CrewChief.currentGameState.TimingData.getPlayerBestLapTime(): -1;
            float averageUsagePerLapToCheck = getConsumptionPerLap();
            if (averageUsagePerLapToCheck > 0)
            {
                closeFuelAmount = averageUsagePerLapToCheck / 2;
            }
            else if (averageUsagePerMinute > 0 && playerBestLapTime > 0)
            {
                closeFuelAmount = (averageUsagePerMinute * playerBestLapTime / 60f) / 2;
            }
            else if (CrewChief.currentGameState != null && CrewChief.currentGameState.SessionData.TrackDefinition != null)
            {
                switch (CrewChief.currentGameState.SessionData.TrackDefinition.trackLengthClass)
                {
                    case TrackData.TrackLengthClass.VERY_SHORT:
                        closeFuelAmount = 1f;
                        break;
                    case TrackData.TrackLengthClass.LONG:
                        closeFuelAmount = 3f;
                        break;
                    case TrackData.TrackLengthClass.VERY_LONG:
                        closeFuelAmount = 4f;
                        break;
                    default:    // SHORT or MEDIUM
                        closeFuelAmount = HALF_LAP_RESERVE_DEFAULT;
                        break;
                }
            }
            return closeFuelAmount;
        }

        /// <summary>
        /// Respond to voice command
        /// </summary>
        /// <param name="voiceMessage">
        /// WHATS_MY_FUEL_USAGE,
        /// WHATS_MY_FUEL_LEVEL,
        /// HOW_MUCH_FUEL_TO_END_OF_RACE,
        /// CALCULATE_FUEL_FOR x LAPS/MINUTES/HOURS,
        /// HOWS_MY_FUEL,
        /// CAR_STATUS/STATUS
        /// </param>
        public override void respond(String voiceMessage)
        {
            if (!GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.FUEL) ||
                !CrewChief.fuelMultiplier.active)
            {
                this.audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                return;
            }

            if (SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.WHATS_MY_FUEL_USAGE))
            {
                if (!reportFuelConsumption(true /*individualResponse*/, null /*messageFragments*/))
                {
                    audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                }
            }
            else if (SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.WHATS_MY_FUEL_LEVEL))
            {
                QueuedMessage queuedMessage = null;
                if (!fuelUseActive)
                {
                    audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                }
                // TODO: report this in gallons for the metrically challenged users
                else if (currentFuel >= 2)
                {
                    queuedMessage = new QueuedMessage("Fuel/level", 0, messageFragments: MessageContents((int)currentFuel, folderLitresRemaining));
                }
                else
                {
                    queuedMessage = new QueuedMessage(folderAboutToRunOut, 0);
                }
                if (queuedMessage != null)
                {
                    if (delayResponses && Utilities.random.Next(10) >= 4 && SoundCache.availableSounds.Contains(AudioPlayer.folderStandBy))
                    {
                        this.audioPlayer.pauseQueueAndPlayDelayedImmediateMessage(queuedMessage, 3 /*lowerDelayBoundInclusive*/, 6 /*upperDelayBound*/);
                    }
                    else
                    {
                        this.audioPlayer.playMessageImmediately(queuedMessage);
                    }
                }
            }
            else if (SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.HOW_MUCH_FUEL_TO_END_OF_RACE))
            {
                float litresNeeded = getAdditionalFuelToEndOfRace(true);
                float halfALap = fuelForHalfALap();
                QueuedMessage fuelMessage = null;
                if (!fuelUseActive || litresNeeded == NO_FUEL_DATA)
                {
                    audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                }
                else if (litresNeeded < 0)
                {
                    if (litresNeeded * -1 > halfALap)
                    {
                        fuelMessage = new QueuedMessage(folderPlentyOfFuel, 0);
                    }
                    else
                    {
                        fuelMessage = new QueuedMessage(folderFuelShouldBeOK, 0);
                    }
                }
                else
                {
                    if (fuelReportsInGallons())
                    {
                        // for gallons we want both whole and fractional part cause its a stupid unit.
                        float gallonsNeeded = Utilities.Conversions.convertLitresToGallons(litresNeeded, true);
                        Tuple<int, int> wholeandfractional = Utilities.WholeAndFractionalPart(gallonsNeeded);
                        if (wholeandfractional.Item2 > 0)
                        {
                            fuelMessage = new QueuedMessage("fuel_estimate_to_end", 0,
                                messageFragments: MessageContents(wholeandfractional.Item1, NumberReader.folderPoint, wholeandfractional.Item2, folderGallons));
                        }
                        else
                        {
                            int wholeGallons = Convert.ToInt32(wholeandfractional.Item1);
                            fuelMessage = new QueuedMessage("fuel_estimate_to_end", 0, messageFragments: MessageContents(wholeGallons, wholeGallons == 1 ? folderGallon : folderGallons));
                        }
                    }
                    else
                    {
                        int roundedLitresNeeded = (int) Math.Ceiling(litresNeeded);
                        fuelMessage = new QueuedMessage("fuel_estimate_to_end", 0, messageFragments: MessageContents(roundedLitresNeeded, roundedLitresNeeded == 1 ? folderLitre : folderLitres));
                    }
                }

                if (fuelMessage != null)
                {
                    if (delayResponses && Utilities.random.Next(10) >= 2 && SoundCache.availableSounds.Contains(AudioPlayer.folderStandBy))
                    {
                        this.audioPlayer.pauseQueueAndPlayDelayedImmediateMessage(fuelMessage, 5 /*lowerDelayBoundInclusive*/, 8 /*upperDelayBound*/);
                    }
                    else
                    {
                        this.audioPlayer.playMessageImmediately(fuelMessage);
                    }
                }
            }
            else if (SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.CALCULATE_FUEL_FOR))
            {   // Laps, minutes or hours
                int unit = 0;
                foreach (KeyValuePair<String[], int> entry in SpeechRecogniser.numberToNumber)
                {
                    foreach (String numberStr in entry.Key)
                    {
                        if (voiceMessage.Contains(" " + numberStr + " "))
                        {
                            unit = entry.Value;
                            break;
                        }
                    }
                }
                if (unit == 0)
                {
                    audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderDidntUnderstand, 0));
                    return;
                }
                if (SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.LAP) || SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.LAPS))
                {
                    if (!reportFuelConsumptionForLaps(unit))
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                    }
                }
                else if(SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.MINUTE) || SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.MINUTES))
                {
                    if (!reportFuelConsumptionForTime(0, unit))
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                    }
                }
                else if (SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.HOUR) || SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.HOURS))
                {
                    if (!reportFuelConsumptionForTime(unit, 0))
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                    }
                }
            }
            else if (SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.HOWS_MY_FUEL) ||
                SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.CAR_STATUS) ||
                SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.STATUS))
            {
                reportFuelStatus(SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.HOWS_MY_FUEL),
                    (CrewChief.currentGameState != null && CrewChief.currentGameState.SessionData.SessionType == SessionType.Race));
            }
        }

        /// <summary>
        /// Convert litres to a string in selected units and precision
        /// </summary>
        /// <param name="fractions">3 decimal places vs. whole litres/10ths of gals</param>
        /// <returns></returns>
        private string litresToUnits(float litres, bool fractions)
        {
            string fmt = fuelReportsInGallons() ?
                (fractions ? "F3" : "F1") :
                (fractions ? "F3" : "F0");
            return fuelReportsInGallons() ?
                $"{Utilities.Conversions.convertLitresToGallons(litres).ToString(fmt)} gal" :
                $"{litres.ToString(fmt)}L";
        }
        /// <summary>
        /// Get additional litres required to get to the end
        /// </summary>
        /// <param name="addReserve"></param>
        /// <param name="verbose"></param>
        /// <returns>
        /// +ve: Estimated fuel required
        /// -ve: More than enough
        /// NO_FUEL_DATA (int.MaxValue)
        /// </returns>
        public float getAdditionalFuelToEndOfRace(Boolean addReserve, bool verbose = true)
        {
            float additionalLitresNeeded = NO_FUEL_DATA;
            if (fuelUseActive && 
                CrewChief.fuelMultiplier.active &&
                CrewChief.currentGameState != null)
            {
                // OK, here's where' the fuel calculations are a bit awkward. AverageUsagePerLap and AverageUsagePerMinute
                // are based on your recent consumption. If you're stretching the fuel out towards the pitstop, this is going
                // to skew these quantities and the calculation will assume you'll carry on driving like this, which isn't
                // necessarily the case. So if we're asking for the extraFuelToEnd *with* the reserve, assume we want the overall
                // average consumption, not the recent consumption

                // one additional hack (tweak...) here. The opening laps tend to have lower consumption because we're often checking-up
                // for other cars, drafting, crashing, etc. If we don't have a decent amount of data to offset this skew, then
                // take the max per-lap consumption rather than the average
                float averageUsagePerMinuteForCalculation;
                float averageUsagePerLapForCalculation;
                if ((baseCalculationsOnMaxConsumption || GlobalBehaviourSettings.useOvalLogic || sessionHasHadFCY) && maxConsumptionPerLap > 0 && maxConsumptionPerMinute > 0)
                {
                    averageUsagePerLapForCalculation = maxConsumptionPerLap;
                    averageUsagePerMinuteForCalculation = maxConsumptionPerMinute;
                }
                else
                {
                    if (addReserve && historicAverageUsagePerMinute.Count > 0)
                    {
                        // if we're team racing, use the max consumption as we might not get consumption data for laps when we're not driving
                        averageUsagePerMinuteForCalculation = CrewChief.currentGameState.PitData.IsTeamRacing ?
                            maxConsumptionPerMinute : historicAverageUsagePerMinute.Average();
                    }
                    else
                    {
                        averageUsagePerMinuteForCalculation = averageUsagePerMinute;
                    }
                    if (addReserve && historicAverageUsagePerLap.Count > 0)
                    {
                        // for per-lap consumption, get the biggest if we don't have much data or we're team racing
                        averageUsagePerLapForCalculation = CrewChief.currentGameState.PitData.IsTeamRacing || historicAverageUsagePerLap.Count() <= 5 ?
                            maxConsumptionPerLap : historicAverageUsagePerLap.Average();
                    }
                    else
                    {
                        averageUsagePerLapForCalculation = averageUsagePerLap;
                    }
                }

                float additionalFuelLitres = HALF_LAP_RESERVE_DEFAULT;
                if (averageUsagePerLapForCalculation > 0 && addAdditionalFuelLaps > 0)
                {
                    additionalFuelLitres = addAdditionalFuelLaps * averageUsagePerLapForCalculation;
                }
                float reserve = addAdditionalFuelLaps > 0 ? additionalFuelLitres : 2;
                if (sessionHasFixedNumberOfLaps && averageUsagePerLapForCalculation > 0)
                {
                    float totalLitresNeededToEnd = (averageUsagePerLapForCalculation * lapsRemaining) + (addReserve ? reserve : 0);
                    additionalLitresNeeded = totalLitresNeededToEnd - currentFuel;
                    if(verbose)
                    {
                        Log.Fuel("lgcy: Use per lap = " + litresToUnits(averageUsagePerLapForCalculation, true) + " laps to go = " + lapsRemaining + " current fuel = " +
                            litresToUnits(currentFuel, false) + " additional fuel needed = " + litresToUnits(additionalLitresNeeded, false));
                        if (addReserve)
                        {
                            Log.Fuel($"Including {addAdditionalFuelLaps} laps of additional fuel, {litresToUnits(reserve, false)}");
                        }
                    }
                }
                else if (averageUsagePerMinuteForCalculation > 0)
                {
                    if (CrewChief.currentGameState.SessionData.TrackDefinition != null && addAdditionalFuelLaps <= 0)
                    { // Add a bit even if no additional fuel laps requested
                        TrackData.TrackLengthClass trackLengthClass = CrewChief.currentGameState.SessionData.TrackDefinition.trackLengthClass;
                        if (trackLengthClass < TrackData.TrackLengthClass.MEDIUM)
                        {
                            reserve = 1f;
                        }
                        else if (trackLengthClass == TrackData.TrackLengthClass.LONG)
                        {
                            reserve = 3f;
                        }
                        else if (trackLengthClass == TrackData.TrackLengthClass.VERY_LONG)
                        {
                            reserve = 4f;
                        }
                    }
                    float minutesRemaining = secondsRemaining / 60f;
                    float expectedLapTime = CrewChief.currentGameState.TimingData.getPlayerBestLapTime();
                    if (expectedLapTime <= 0)
                    {
                        expectedLapTime = CrewChief.currentGameState.TimingData.getPlayerClassBestLapTime();
                    }
                    float maxMinutesRemaining = (secondsRemaining + ((extraLapsAfterTimedSessionComplete + 1) *  expectedLapTime)) / 60f;
                    float totalLitresNeededToEnd = 0;
                    if (averageUsagePerLapForCalculation > 0)
                    {
                        totalLitresNeededToEnd = (averageUsagePerMinuteForCalculation * minutesRemaining) +
                            ((extraLapsAfterTimedSessionComplete + 1) * averageUsagePerLapForCalculation) +
                            (addReserve ? reserve : 0);
                    }
                    else
                    {
                        totalLitresNeededToEnd = (averageUsagePerMinuteForCalculation * maxMinutesRemaining) + (addReserve ? reserve : 0);
                    }
                    additionalLitresNeeded = totalLitresNeededToEnd - currentFuel;
                    if (verbose)
                    {
                        Log.Fuel("lgcy: Use per minute = " + litresToUnits(averageUsagePerMinuteForCalculation, true) + " estimated minutes to go (including final lap) = " +
                        maxMinutesRemaining.ToString("F1") + " current fuel = " + litresToUnits(currentFuel, false) + " additional fuel needed = " + litresToUnits(additionalLitresNeeded, false));
                        if (addReserve && addAdditionalFuelLaps >= 0)
                        {
                            Log.Fuel($"Including {addAdditionalFuelLaps} laps of additional fuel, {litresToUnits(reserve, false)}");
                        }
                    }
                }
            }
            return additionalLitresNeeded;
        }
        /// <summary>
        /// Try to predict the the earliest possible time/lap and the latest possible time/lap we can come in for our pitstop and still make it to the end.
        /// we need to check if more then one stop is needed to finish the race in this case we dont care about pit window
        /// </summary>
        /// <returns>pit window earliest:latest tuple in laps or minutes</returns>
        private Tuple<int, int> getPredictedPitWindow(GameStateData currentGameState)
        {
            int minLaps;
            switch (currentGameState.SessionData.TrackDefinition.trackLengthClass)
            {
                case TrackData.TrackLengthClass.VERY_LONG:
                    minLaps = sessionHasFixedNumberOfLaps ? 2 : 1;
                    break;
                case TrackData.TrackLengthClass.LONG:
                    minLaps = 2 + Utilities.random.Next(2); // 2 or 3
                    break;
                case TrackData.TrackLengthClass.SHORT:
                    minLaps = 3 + Utilities.random.Next(3); // 3, 4 or 5
                    break;
                case TrackData.TrackLengthClass.VERY_SHORT:
                    minLaps = 4 + Utilities.random.Next(3); // 4, 5 or 6
                    break;
                default:
                    minLaps = 3 + Utilities.random.Next(2); // 3 or 4
                    break;
            }

            Tuple<int, int> pitWindow = new Tuple<int, int>(-1, -1);
            // tweak the fuelCapacity using the requested reserve. That is, the fuel capcity we use for these calcuations is the full
            // tank minus the reserve amount we've set in the Properties
            float averageUsagePerLapToUse = getConsumptionPerLap();
            float fuelCapacityAllowingForReserve;
            if (addAdditionalFuelLaps > 0)
            {
                fuelCapacityAllowingForReserve = fuelCapacity - (averageUsagePerLap * addAdditionalFuelLaps);
            }
            else
            {
                // no reserve set so use the default
                fuelCapacityAllowingForReserve = fuelCapacity - HALF_LAP_RESERVE_DEFAULT;
            }
            if (sessionHasFixedNumberOfLaps)
            {
                if (lapsCompletedSinceFuelReset >= minLaps && averageUsagePerLapToUse > 0)
                {
                    float litresNeeded = getAdditionalFuelToEndOfRace(false);
                    gotPredictedPitWindow = true;
                    if (litresNeeded > 0)
                    {
                        // more then 1 stop needed
                        if (litresNeeded > fuelCapacityAllowingForReserve)
                        {
                            return pitWindow;
                        }
                        int maximumLapsForFullTankOfFuel = (int)Math.Floor(fuelCapacityAllowingForReserve / averageUsagePerLapToUse);
                        // pit window start is just the total race distance - maximumLapsForFullTankOfFuel. It's the earliest we can stop, fill the tank, and still finish
                        int pitWindowStart = currentGameState.SessionData.SessionNumberOfLaps - maximumLapsForFullTankOfFuel;
                        // pit window end is just the lap on which we'll run out of fuel if we don't stop
                        int pitWindowEnd = currentGameState.SessionData.CompletedLaps + (int)Math.Floor(currentFuel / averageUsagePerLap);
                        Log.Fuel("lgcy: calculated fuel window (laps): pitwindowStart = " + pitWindowStart + " pitWindowEnd = " + pitWindowEnd +
                            " maximumLapsForFullTankOfFuel = " + maximumLapsForFullTankOfFuel);

                        // some sanity checks to ensure we're not calling nonsense window data. A negative window start is OK - this just means we're inside the
                        // window at the point where we're doing the calculation
                        if (pitWindowStart <= pitWindowEnd && pitWindowStart < currentGameState.SessionData.SessionNumberOfLaps && pitWindowEnd > 0)
                        {
                            pitWindow = new Tuple<int, int>(pitWindowStart, pitWindowEnd);
                        }
                    }
                }
            }
            else
            {
                float averageUsagePerMinuteToUse = getConsumptionPerMinute();
                if (lapsCompletedSinceFuelReset >= minLaps && averageUsagePerMinuteToUse > 0)
                {
                    float litresNeeded = getAdditionalFuelToEndOfRace(false);
                    gotPredictedPitWindow = true;
                    if (litresNeeded > 0)
                    {
                        // more then 1 stop needed
                        if (litresNeeded > fuelCapacityAllowingForReserve)
                        {
                            return pitWindow;
                        }
                        int sessionTotalRunTimeMinutes = (int)Math.Floor(currentGameState.SessionData.SessionTotalRunTime / 60);
                        int sessionRunningTimeMinutes = (int)Math.Floor(currentGameState.SessionData.SessionRunningTime / 60);
                        int maximumMinutesForFullTankOfFuel = (int)Math.Floor(fuelCapacityAllowingForReserve / averageUsagePerMinuteToUse);
                        // pit window start is just the total race time - maximumMinutesForFullTankOfFuel. It's the earliest we can stop, fill the tank, and still finish
                        int pitWindowStart = sessionTotalRunTimeMinutes - maximumMinutesForFullTankOfFuel;
                        // pit window end is just the minute on which we'll run out of fuel if we don't stop
                        int pitWindowEnd = sessionRunningTimeMinutes + (int)Math.Floor(currentFuel / averageUsagePerMinute);
                        Log.Fuel("lgcy: calculated fuel window (minutes): pitwindowStart = " + pitWindowStart + " pitWindowEnd = " + pitWindowEnd +
                            " maximumMinutesForFullTankOfFuel = " + maximumMinutesForFullTankOfFuel);
                        // some sanity checks to ensure we're not calling nonsense window data. A negative window start is OK - this just means we're inside the
                        // window at the point where we're doing the calculation
                        if (pitWindowStart <= pitWindowEnd && pitWindowStart < sessionTotalRunTimeMinutes && pitWindowEnd > 0)
                        {
                            pitWindow = new Tuple<int, int>(pitWindowStart, pitWindowEnd);
                        }
                    }
                }
            }
            return pitWindow;
        }

        public override int resolveMacroKeyPressCount(String macroName)
        {
            // only used for r3e auto-fuel amount selection at present
            Console.WriteLine("lgcy: Getting fuel requirement keypress count");
            int litresToEnd = (int) Math.Ceiling(getAdditionalFuelToEndOfRace(true));

            // limit the number of key presses to 200 here, or fuelCapacity
            int fuelCapacityInt = (int)fuelCapacity;
            if (fuelCapacityInt > 0 && fuelCapacityInt - currentFuel < litresToEnd)
            {
                // if we have a known fuel capacity and this is less than the calculated amount of fuel we need, warn about it.
                audioPlayer.playMessage(new QueuedMessage(folderWillNeedToStopAgain, 0, secondsDelay: 4, abstractEvent: this, priority: 10));
            }
            int maxPresses = fuelCapacityInt > 0 ? fuelCapacityInt : 200;
            return litresToEnd < 0 ? 0 : litresToEnd > maxPresses ? maxPresses : litresToEnd;
        }

        /// <summary>
        /// must be a valid lap, must not be in pitlane, must have valid laptime data and not be an outlier. Here we assume that an
        /// outlap will be an outlier WRT pace so we don't check that explicitly
        /// </summary>
        private Boolean canUseLastLapForMaxPerLapFuelConsumption(GameStateData currentGameState)
        {
            return currentGameState.SessionData.PreviousLapWasValid && currentGameState.SessionData.LapTimePrevious > 0 &&
                currentGameState.SessionData.PlayerLapTimeSessionBest > 0 && !currentGameState.PitData.InPitlane &&
                currentGameState.SessionData.LapTimePrevious < currentGameState.SessionData.PlayerLapTimeSessionBest + LapTimes.outlierPaceLimits[currentGameState.SessionData.TrackDefinition.trackLengthClass];
        }

        private float getConsumptionPerLap()
        {
            return (baseCalculationsOnMaxConsumption || GlobalBehaviourSettings.useOvalLogic || sessionHasHadFCY) && maxConsumptionPerLap > 0 ? maxConsumptionPerLap : averageUsagePerLap;
        }

        private float getConsumptionPerMinute()
        {
            return (baseCalculationsOnMaxConsumption || GlobalBehaviourSettings.useOvalLogic || sessionHasHadFCY) && maxConsumptionPerMinute > 0 ? maxConsumptionPerMinute : averageUsagePerMinute;
        }

        /// <summary>
        /// don't allow some automatic fuel messages to play if the last fuel message was less than 30 seconds ago
        /// </summary>
        private static Boolean canPlayFuelMessage()
        {
            return CrewChief.currentGameState != null
                && CrewChief.currentGameState.Now != null
                && CrewChief.currentGameState.Now > lastFuelCall.AddSeconds(30);
        }
    }
}
