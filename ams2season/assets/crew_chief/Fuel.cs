using System;
using System.Collections.Generic;
using System.Linq;
using CrewChiefV4.GameState;
using CrewChiefV4.Audio;
using CrewChiefV4.NumberProcessing;
using Newtonsoft.Json;
using System.IO;

namespace CrewChiefV4.Events
{
    partial class Fuel : AbstractEvent
    {
        #region consts
        private const String folderOneLapEstimate = "fuel/one_lap_fuel";

        private const String folderTwoLapsEstimate = "fuel/two_laps_fuel";

        private const String folderThreeLapsEstimate = "fuel/three_laps_fuel";

        private const String folderFourLapsEstimate = "fuel/four_laps_fuel";

        private const String folderHalfDistanceGoodFuel = "fuel/half_distance_good_fuel";

        private const String folderHalfDistanceLowFuel = "fuel/half_distance_low_fuel";

        private const String folderHalfTankWarning = "fuel/half_tank_warning";

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

        private const String folderNotEnoughLapsForAverage = "fuel/not_enough_laps_for_average";

        public const float NO_FUEL_DATA = float.MaxValue;
        private const float HALF_LAP_RESERVE_DEFAULT = 2f;  // Allow 2L for half a lap unless we have a better estimate

        #endregion consts
        #region variables
        private static DateTime lastFuelCall = DateTime.MinValue;

        private List<float> persistedAverageUsagePerLap = new List<float>();
        private List<float> historicAverageUsagePerLap = new List<float>();
        private List<FuelSample> usagePerLapOutgoing = new List<FuelSample>();
        private ConditionsMonitor.TrackWetness worstConditionsOnLap = ConditionsMonitor.TrackWetness.UNKNOWN;
        private Boolean lapInvalidated = false;

        private float averageUsagePerLap;

        // fuel in tank 15 seconds after game start
        private float initialFuelLevel;

        private int halfDistance;
        private Boolean playedHalfDistance;

        private Boolean playedHalfTankWarning;

        private Boolean initialised;

        private Boolean played1LitreWarning;

        private Boolean played2LitreWarning;

        // base fuel use by lap estimates on the last 3 laps
        private int fuelUseByLapsWindowLengthToUse = 3;
        private const int fuelUseByLapsWindowLengthVeryShort = 5;
        private const int fuelUseByLapsWindowLengthShort = 4;
        private const int fuelUseByLapsWindowLengthMedium = 3;
        private const int fuelUseByLapsWindowLengthLong = 2;
        private const int fuelUseByLapsWindowLengthVeryLong = 1;

        private List<float> fuelLevelWindowByLap = new List<float>();

        private Boolean playPitForFuelNow, playedPitForFuelNow;

        private float currentFuel = -1;

        private float fuelCapacity = 0;

        public static readonly Boolean enableFuelMessages = UserSettings.GetUserSettings().getBoolean("enable_fuel_messages");

        private readonly Boolean delayResponses = UserSettings.GetUserSettings().getBoolean("enable_delayed_responses");

        // we could have voice commands that allow the user to change the fuel scale on the fly,
        // e.g. if they expect to be doing fuel saving or flat out depending on in-race strategy.
        private readonly float fuelPercentile = UserSettings.GetUserSettings().getFloat("fuel_percentile");
        private readonly float fuelPercentileOval = UserSettings.GetUserSettings().getFloat("fuel_percentile_oval");
        private readonly float fuelReserveLapsShort = UserSettings.GetUserSettings().getFloat("fuel_reserve_laps_short");
        private readonly float fuelReserveLapsMedium = UserSettings.GetUserSettings().getFloat("fuel_reserve_laps_medium");
        private readonly float fuelReserveLapsLong = UserSettings.GetUserSettings().getFloat("fuel_reserve_laps_long");
        private readonly float fuelExtraLapsOval = UserSettings.GetUserSettings().getFloat("fuel_extra_laps_oval");
        private readonly float fuelExtraLapsEndurance = UserSettings.GetUserSettings().getFloat("fuel_extra_laps_endurance");
        private readonly Boolean experimentalLapEstimatorMulticlass = UserSettings.GetUserSettings().getBoolean("fuel_experimental_lap_estimator_multiclass");
        private readonly Boolean reportFuelLapsLeftInTimedRaces = UserSettings.GetUserSettings().getBoolean("report_fuel_laps_left_in_timed_races");

        // how much percentage of our current fuel can we reasonably expect to save by driving differently
        private readonly float fuel_saving_coefficient = UserSettings.GetUserSettings().getFloat("fuel_saving_percentage") / 100f;

        private DateTime nextFuelPitWindowOpenCheck = DateTime.MinValue;

        private readonly TimeSpan fuelStatusCheckInterval = TimeSpan.FromSeconds(5);

        // this is used to indicate that the session either has a fixed number of laps
        // or we are inferring a fixed number of laps for a fixed time.
        // All logic should use these instead of checking the gamestate.
        //
        // Note that we may have a positive sessionNumberOfLaps but fixed number may be false,
        // which for some simulators means a session with a lap and time limit but we
        // prefer to treat it as a timed session.
        //
        // lapsRemaining = totalLaps - leaderCompletedLaps
        // (i.e. laps to go, including this one, for the player). When the player
        // crosses into the pit lane the data on the game state may be off by
        // one (depending on where the leader is) until they cross the start / finish line,
        // which could be before or after the pit stall. This field corrects for this error,
        // but all Events that make use of this class must be registered AFTER so that
        // they see the impact of the workaround.
        private volatile int sessionNumberOfLaps = -1;
        private volatile int lapsRemaining = -1;
        private volatile float reserveMultiplier = -1;
        private volatile bool suppressLapsRemainingUpdate = false;
        private volatile float fuelOnPitEntry = -1;
        private DateTime lastFuelUseRecorded;

        // workarounds for bad telemetry...
        private volatile float _our_lap_time, _leader_lap_time = -1;

        // count laps separately for fuel so we always count incomplete and invalid laps
        private int lapsCompletedSinceFuelReset = 0;

        private bool playedPitWindowEstimate = false;

        private bool playedPitWindowOpen = false;

        private int extraLapsAfterTimedSessionComplete = 0;

        private volatile bool greenLap;

        // in prac and qual, assume it's a low fuel run unless we know otherwise
        private Boolean onLowFuelRun = false;
        private float lapsForLowFuelRun = 4f;

        private readonly List<float> virtualEnergyUsageByLap = new List<float>();
        private float virtualEnergyAtLapStart = -1;
        private int previousVirtualEnergy = -1;
        private int virtualEnergyLap = -1;
        private bool virtualEnergyLapWasGreen = false;
        private int lastVirtualEnergyLapWarning = 5;
        private bool playedVirtualEnergyEmptyWarning;
        private bool playedVirtualEnergyPitWarning;
        private bool pitForVirtualEnergy;

        public static Fuel inst;
        public static Fuel_legacy legacy_inst;
        #endregion variables

        public Fuel(AudioPlayer audioPlayer)
        {
            this.audioPlayer = audioPlayer;
            inst = this;
            if (legacy_inst == null)
            {
                legacy_inst = new Fuel_legacy(audioPlayer); // Niiice!
            }
        }

        public override void clearState()
        {
            virtualEnergyUsageByLap.Clear();
            virtualEnergyAtLapStart = -1;
            previousVirtualEnergy = -1;
            virtualEnergyLap = -1;
            virtualEnergyLapWasGreen = false;
            resetVirtualEnergyWarnings();
            ResetTopicWindowData();
            initialFuelLevel = 0;
            averageUsagePerLap = 0;
            halfDistance = -1;
            playedHalfDistance = false;
            playedHalfTankWarning = false;
            initialised = false;
            fuelLevelWindowByLap = new List<float>();
            playPitForFuelNow = false;
            playedPitForFuelNow = false;
            played1LitreWarning = false;
            played2LitreWarning = false;
            currentFuel = 0;
            nextFuelPitWindowOpenCheck = DateTime.MinValue;
            sessionNumberOfLaps = -1;
            lapsCompletedSinceFuelReset = 0;
            suppressLapsRemainingUpdate = false;

            reserveMultiplier = 1.0f;
            lapsRemaining = -1;
            extraLapsAfterTimedSessionComplete = 0;
            fuelCapacity = 0;
            playedPitWindowOpen = false;
            playedPitWindowEstimate = false;
            greenLap = true;

            persistedAverageUsagePerLap.Clear();
            historicAverageUsagePerLap.Clear();
            usagePerLapOutgoing.Clear();
            worstConditionsOnLap = ConditionsMonitor.TrackWetness.UNKNOWN;
            lapInvalidated = false;

            onLowFuelRun = false;
            lapsForLowFuelRun = 4f;
            fuelOnPitEntry = -1;

            _our_lap_time = -1f;
            _leader_lap_time = -1f;

            lastFuelUseRecorded = DateTime.MinValue;

            LapsRemaining = 0;
            LapsUntilRefuel = 0;
            FuelAddedInLastStop = -1;
        }

        // fuel not implemented for HotLap/LonePractice modes
        public override List<SessionType> applicableSessionTypes
        {
            get
            {
                return new List<SessionType>
                {
                    SessionType.Practice,
                    SessionType.Qualify,
                    SessionType.PrivateQualify,
                    SessionType.Race,
                    SessionType.LonePractice
                };
            }
        }

        public override List<SessionPhase> applicableSessionPhases
        {
            get
            {
                return new List<SessionPhase>
                {
                    SessionPhase.Countdown,
                    SessionPhase.Green,
                    SessionPhase.FullCourseYellow,
                    SessionPhase.Checkered,
                    SessionPhase.Finished
                };
            }
        }

        private List<PersistedFuel> getAllPersistedFuel()
        {
            if (!File.Exists(DataFiles.fuel_usage))
            {
                return new List<PersistedFuel>();
            }
            return JsonConvert.DeserializeObject<List<PersistedFuel>>(File.ReadAllText(DataFiles.fuel_usage));
        }

        // to avoid growing the file infinitely, we only keep the last 5 sessions for this combo
        private void savePersistedFuelUsage(GameStateData currentGameState)
        {
            if (usagePerLapOutgoing.Count == 0)
            {
                Log.Commentary("Not saving fuel usage because there are no valid laps to save");
                return;
            }
            if (CrewChief.fuelMultiplier.dontSaveFuelData)
            {
                Log.Warning($"Not saving fuel usage because {CrewChief.gameDefinition.friendlyName} needs you to have set the fuel multiplier and you haven't ticked 'Save all fuel data'");
                return;
            }

            var game = CrewChief.gameDefinition.gameEnum.ToString();
            var carName = currentGameState.carName;
            var trackName = currentGameState.SessionData.TrackDefinition.name;

            var thisCombo = new List<PersistedFuel>();
            var entries = new List<PersistedFuel>();
            foreach (var datum in getAllPersistedFuel())
            {
                if (datum.isForThisCombo(game, carName, trackName))
                {
                    thisCombo.Add(datum);
                }
                else
                {
                    entries.Add(datum);
                }
            }

            var entry = new PersistedFuel();
            entry.game = game;
            entry.carName = carName;
            entry.trackName = trackName;
            entry.fuel = usagePerLapOutgoing;

            thisCombo.Insert(0, entry);
            entries.AddRange(thisCombo.Take(5).Reverse());

            Log.Fuel(() => $"Persisting fuel usage for {usagePerLapOutgoing.Count} green laps");
            string jsonRaw = JsonConvert.SerializeObject(entries, Formatting.Indented);
            File.WriteAllText(DataFiles.fuel_usage, jsonRaw);
            usagePerLapOutgoing.Clear();
        }

        // there are potentially a lot of data points in the file, there's nothing stopping the user from
        // manually curating it with external data. But even so, we don't want historic data to overwhelm
        // the actual race data, so we randomly select 5 entries out of all the viable candidates.
        private List<float> getPersistedFuelUsage(GameStateData currentGameState)
        {
            var game = CrewChief.gameDefinition.gameEnum.ToString();
            var carName = currentGameState.carName;
            var trackName = currentGameState.SessionData.TrackDefinition.name;

            var conditions = ConditionsMonitor.TrackWetness.Dry;

            if (currentGameState.Conditions.CurrentConditions != null)
            {
                var wetness = currentGameState.Conditions.CurrentConditions.TrackWetness;
                if (wetness > conditions)
                {
                    conditions = wetness;
                }
            }

            var relevant = new List<FuelSample>();
            foreach (var datum in getAllPersistedFuel())
            {
                if (datum.isForThisCombo(game, carName, trackName))
                {
                    foreach (var data_point in datum.fuel)
                    {
                        if (data_point.litres < 0.25)
                        {
                            // ignore fuel data that is very low because it is likely junk
                            // and if it's not junk then we'll figure out the usage
                            // pretty quickly anyway. We could be a lot more advanced than
                            // this, looking for really bad outliers (e.g. as a result of
                            // active reset and other issues) but this is a decent first pass.
                            continue;
                        }
                        if (data_point.conditions != ConditionsMonitor.TrackWetness.UNKNOWN && data_point.conditions != conditions)
                        {
                            // condition based fuel estimates are not really implemented (we have
                            // no forecasts and timing to lap estimate is all off), but
                            // we can at least only load data that is the same as current session.
                            continue;
                        }
                        data_point.litres *= CrewChief.fuelMultiplier.multiplier;
                        relevant.Add(data_point);
                    }
                }
            }
            var rng = new Random();
            var chosen = relevant.OrderBy(x => rng.Next()).Take(10).ToList().ConvertAll(s => s.litres);
            var debug_values = String.Join(",", chosen);
            Log.Fuel(() => $"Loaded {relevant.Count} fuel usage samples for this combination: {debug_values}");
            if (CrewChief.gameDefinition.fuelMultiplierType == GameDefinition.FuelMultiplierType.Variable)
            {
                Log.Fuel(() => $"Fuel multiplier is not reported by {CrewChief.gameDefinition.friendlyName}, so fuel usage depends on what you set it to");
            }
            return chosen;
        }

        public static bool fuelReportsInGallons
        {
            get { return !GlobalBehaviourSettings.useMetric; }
            set { GlobalBehaviourSettings.useMetric = !value; }
        }

        /// <summary>
        /// Do the fuel consumption calculations (when appropriate)
        /// Warn about fuel levels
        /// </summary>
        override protected void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (!GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.FUEL) ||
                !CrewChief.fuelMultiplier.active ||
                !currentGameState.FuelData.FuelUseActive
                )
            {
                return;
            }

            if (previousGameState == null)
            {
                return;
            }

            if (CrewChief.viewingReplay)
            {
                // could also be in the garage, or watching other drivers in an endurance race.
                // the data here tends to be junk so make sure we skip it.
                return;
            }

            UpdateTopicWindow(previousGameState, currentGameState);

            bool isPractice = currentGameState.SessionData.SessionType == SessionType.LonePractice || currentGameState.SessionData.SessionType == SessionType.Practice;
            bool isQualify = currentGameState.SessionData.SessionType == SessionType.Qualify || currentGameState.SessionData.SessionType == SessionType.PrivateQualify;
            bool isRace = currentGameState.SessionData.SessionType == SessionType.Race;

            bool isFinish = currentGameState.SessionData.SessionPhase == SessionPhase.Finished && previousGameState.SessionData.SessionPhase != SessionPhase.Finished;
            bool enteredPits = !previousGameState.PitData.InPitlane && currentGameState.PitData.InPitlane;
            int green_laps = usagePerLapOutgoing.Count;

            if (isRace && isFinish)
            {
                Log.Fuel(() => $"Fuel at the finish = {litresToUnits(currentGameState.FuelData.FuelLeft, true)}");
                int VirtualEnergy = LMU.VirtualEnergy.Read();
                if (VirtualEnergy >= 0 && VirtualEnergy <= 100)
                {
                    Log.Fuel(() => $"Virtual Energy at the finish = {VirtualEnergy}%");
                }
            }
            if (currentGameState.SessionData.SessionPhase == SessionPhase.Finished && !isFinish)
            { // Race is over
                return;
            }

            extraLapsAfterTimedSessionComplete = currentGameState.SessionData.ExtraLapsAfterTimedSessionComplete;

            // if the fuel level has increased, don't trigger
            if (currentFuel > -1 && currentFuel < currentGameState.FuelData.FuelLeft)
            {
                currentFuel = currentGameState.FuelData.FuelLeft;
                return;
            }
            if (!currentGameState.SessionData.SessionHasFixedTime && !suppressLapsRemainingUpdate)
            {
                lapsRemaining = currentGameState.SessionData.SessionLapsRemaining;
            }

            bool _pitEntry = !previousGameState.PitData.InPitlane && currentGameState.PitData.InPitlane;
            bool _pitExit =   previousGameState.PitData.InPitlane && !currentGameState.PitData.InPitlane;
            // see the note on lapsRemaining
            if (_pitEntry)
            {
                fuelOnPitEntry = currentGameState.FuelData.FuelLeft;
                suppressLapsRemainingUpdate = true;
                if (currentGameState.SessionData.SessionHasFixedTime || currentGameState.SessionData.OverallPosition == 1
                    || (currentGameState.getOpponentAtOverallPosition(1) != null && currentGameState.PositionAndMotionData.DistanceRoundTrack < currentGameState.getOpponentAtOverallPosition(1).DistanceRoundTrack))
                {
                    // for fixed lap races, if the leader has already crossed the line ahead of us then we don't need to change anything
                    lapsRemaining = Math.Max(1, lapsRemaining - 1);
                }
            }
            else if (_pitExit)
            {
                FuelAddedInLastStop = currentGameState.FuelData.FuelLeft - fuelOnPitEntry;
                fuelOnPitEntry = -1;
                Log.Fuel(() => $"Fuel added during pitstop {litresToUnits(FuelAddedInLastStop, true)}");
                suppressLapsRemainingUpdate = false;
            }

            currentFuel = currentGameState.FuelData.FuelLeft;
            fuelCapacity = currentGameState.FuelData.FuelCapacity;

            if (greenLap
                && (!(currentGameState.SessionData.SessionPhase == SessionPhase.Green || currentGameState.SessionData.SessionPhase == SessionPhase.Checkered)
                   || currentGameState.PitData.InPitlane
                   || currentGameState.PitData.JumpedToPits
                   || currentGameState.PitData.IsInGarage
                   || ((isPractice || isQualify) && !currentGameState.SessionData.CurrentLapIsValid)))
            {
                // Log.Fuel("Marking lap as NOT GREEN.");
                greenLap = false;
            }

            // specifically tracked for debugging
            if (greenLap && previousGameState.FuelData.FuelLeft < currentFuel)
            {
                Log.Fuel(() => $"detected possible rewind / active reset, marking lap as not green: {previousGameState.FuelData.FuelLeft} => {currentFuel}");
                greenLap = false;
            }

            // only track fuel data after the session has settled down
            if (!GameStateData.onManualFormationLap &&

                ((currentGameState.SessionData.SessionType == SessionType.Race &&
                    (currentGameState.SessionData.SessionPhase >= SessionPhase.Green)) ||

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
                if (!initialised ||
                    // fuel has increased by at least 1 litre
                    (fuelLevelWindowByLap.Count() > 0 && fuelLevelWindowByLap[0] > 0 && currentGameState.FuelData.FuelLeft > fuelLevelWindowByLap[0] + 1) ||
                    // special case for race session starting in the pitlane. When we exit the pit we might have much less fuel than we did at the start of the session because we took some out
                    // In this case, it'll be a race session with 0 laps completed at pit exit. AFAIK we can only take fuel out if we start from the pitlane
                    ((currentGameState.SessionData.SessionType != SessionType.Race || currentGameState.SessionData.CompletedLaps < 1)
                        && previousGameState.PitData.InPitlane && !currentGameState.PitData.InPitlane))
                {
                    // first time in, fuel has increased, or pit exit so initialise our internal state. Note we don't blat the average use data -
                    // this will be replaced when we get our first data point but it's still valid until we do.
                    fuelLevelWindowByLap = new List<float>();
                    fuelLevelWindowByLap.Add(currentGameState.FuelData.FuelLeft);
                    initialFuelLevel = currentGameState.FuelData.FuelLeft;
                    greenLap = true;
                    playPitForFuelNow = false;
                    playedPitForFuelNow = false;
                    played1LitreWarning = false;
                    played2LitreWarning = false;
                    lapsCompletedSinceFuelReset = 0;
                    playedHalfTankWarning = false;
                    if (historicAverageUsagePerLap.Count == 0)
                    {
                        try
                        {
                            persistedAverageUsagePerLap = getPersistedFuelUsage(currentGameState);
                        }
                        catch (Exception e)
                        {
                            Log.Fuel(() => $"There was an error when opening the persisted fuel data: {e}");
                        }
                    }
                    // set the onLowFuelRun if we're in prac / qual - asssume we're on a low fuel run until we know otherwise
                    if (isPractice || isQualify)
                    {
                        onLowFuelRun = true;
                        lapsForLowFuelRun = 4f;
                        switch (currentGameState.SessionData.TrackDefinition.trackLengthClass)
                        {
                            case TrackData.TrackLengthClass.LONG:
                                lapsForLowFuelRun = 3f;
                                break;
                            case TrackData.TrackLengthClass.VERY_LONG:
                                lapsForLowFuelRun = 2f;
                                break;
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
                        sessionNumberOfLaps = currentGameState.SessionData.SessionNumberOfLaps;
                        if (sessionNumberOfLaps > 1
                            &&
                            // rF2 has "Finish Criteria: Laps and Time", if that's selected then ignore laps
                            //  and calculate fuel based on time (sub-optimal but at least it won't run out of fuel)
                            !(Game.RF2_LMU
                                  && currentGameState.SessionData.SessionHasFixedTime)
                            )
                        {
                            if (halfDistance == -1)
                            {
                                halfDistance = (int)Math.Ceiling(sessionNumberOfLaps / 2f);
                            }
                        }
                    }
                    Log.Fuel(() => "Fuel level initialised, initialFuelLevel = " + litresToUnits(initialFuelLevel, false));

                    initialised = true;
                }

                var enteredSector3 = previousGameState.SessionData.SectorNumber == 2 && currentGameState.SessionData.SectorNumber == 3;

                // "box now" as we approach the pits
                if (playPitForFuelNow &&
                    !playedPitForFuelNow &&
                    (GlobalBehaviourSettings.useOvalLogic ||
                      currentGameState.SessionData.TrackDefinition.trackLengthClass < TrackData.TrackLengthClass.MEDIUM ||
                      enteredSector3))
                {
                    playPitForFuelNow = false;
                    playedPitForFuelNow = true;
                    Log.Fuel("Pit this lap");
                    int delay = currentGameState.SessionData.SectorNumber == 1 ? 10 : 0;
                    audioPlayer.playMessage(new QueuedMessage(PitStops.folderMandatoryPitStopsPitThisLap, 0, abstractEvent: this, secondsDelay: delay, priority: 10));
                }

                if (enteredSector3 && currentGameState.SessionData.SessionType == SessionType.Race &&
                    currentFuel > 0 && averageUsagePerLap > 0 &&
                    currentFuel < 3 && currentFuel < averageUsagePerLap / 3.0)
                {
                    audioPlayer.playMessage(new QueuedMessage(folderAboutToRunOut, 0, abstractEvent: this, secondsDelay: 5, priority: 10));
                }

                var currentConditions = currentGameState.Conditions.CurrentConditions;
                if (currentConditions != null && currentConditions.TrackWetness > worstConditionsOnLap)
                {
                    worstConditionsOnLap = currentConditions.TrackWetness;
                }

                if (!lapInvalidated && !currentGameState.SessionData.CurrentLapIsValid)
                {
                    lapInvalidated = true;
                }

                if (previousGameState.SessionData.SessionPhase == SessionPhase.Countdown &&
                    currentGameState.SessionData.SessionHasFixedTime &&
                    currentGameState.FuelData.FuelLeft > 0 &&
                    currentGameState.SessionData.SessionPhase == SessionPhase.Green)
                {
                    // sometimes the NewLap logic below kicks in before the green flag,
                    // and the session time remaining is not available, so we do this
                    // one-time extra check when the green flag falls. Whichever of the
                    // two calculations comes second will win.
                    estimateLapsForFixedTimeRace(currentGameState);
                }

                updateVirtualEnergyUsage(currentGameState);

                bool _newLap_soRecordStats = currentGameState.SessionData.IsNewLap && currentGameState.FuelData.FuelLeft > 0;
                if (_newLap_soRecordStats)
                {
                    lapsCompletedSinceFuelReset++;
                    // completed a lap, so store the fuel left at this point:
                    fuelLevelWindowByLap.Insert(0, currentGameState.FuelData.FuelLeft);
                    // if we've got fuelUseByLapsWindowLength + 1 samples (note we initialise the window data with initialFuelLevel so we always
                    // have one extra), get the average difference between each pair of values

                    bool lastLapWasGreen = greenLap;
                    greenLap = true;

                    if (currentGameState.SessionData.SessionHasFixedTime)
                    {
                        estimateLapsForFixedTimeRace(currentGameState);
                    }
                    Log.Fuel(() => $"lapsRemaining = {lapsRemaining}");

                    if (currentGameState.SessionData.CompletedLaps > 0 && fuelLevelWindowByLap.Count >= 2 && lastLapWasGreen)
                    {
                        float thisLapFuelUse = fuelLevelWindowByLap[1] - fuelLevelWindowByLap[0];
                        // it is possible that junk data can get here (e.g. from telemetry missing a beat)
                        // so it is important to do some basic validation. We are still prone to errors when
                        // recording the first few laps of data so it is conceivable that a player somewhere
                        // may one day have to clean up or delete their persisted fuel data. The worst error
                        // would be to miss a lap and then get about double what we should have had.
                        if (thisLapFuelUse <= 0 || lastFuelUseRecorded == DateTime.MinValue)
                        {
                            Log.Fuel("Fuel was not initialised correctly");
                        }
                        else
                        {
                            // Log.Fuel(() => "This lap fuel = " + litresToUnits(thisLapFuelUse, true));
                            historicAverageUsagePerLap.Add(thisLapFuelUse);

                            // we never persist invalid laps, it just adds too much noise and might include all
                            // kinds of transient issues like active reset, but it's still useful for the race.
                            if (lapInvalidated)
                            {
                                Log.Fuel(() => $"Not persisting fuel use for an invalid lap {litresToUnits(thisLapFuelUse, true)}");
                            }
                            else
                            {
                                Log.Fuel(() => $"Queuing fuel use for valid lap: {litresToUnits(thisLapFuelUse, true)}");
                                var sample = new FuelSample();
                                sample.litres = thisLapFuelUse / CrewChief.fuelMultiplier.multiplier;
                                sample.conditions = worstConditionsOnLap;
                                sample.lap_time = (float)(currentGameState.Now - lastFuelUseRecorded).TotalSeconds;
                                usagePerLapOutgoing.Add(sample);
                            }
                        }
                    }
                    worstConditionsOnLap = ConditionsMonitor.TrackWetness.UNKNOWN;
                    lapInvalidated = false;
                    lastFuelUseRecorded = currentGameState.Now;
                    updateAverageFuelUsage(currentGameState);
                    // now check if we need to reset the 'on low fuel run' variable, do this on our 2nd flying lap
                    if (onLowFuelRun && lapsCompletedSinceFuelReset == 2 && averageUsagePerLap > 0 && initialFuelLevel / averageUsagePerLap > lapsForLowFuelRun)
                    {
                        onLowFuelRun = false;
                    }
                }

                warnAboutVirtualEnergy(previousGameState, currentGameState);

                if ((isRace && (isFinish || enteredPits)) || (isPractice && enteredPits))
                {
                    playPitForFuelNow = false;

                    if (green_laps >= fuelUseByLapsWindowLengthToUse)
                    {
                        savePersistedFuelUsage(currentGameState);
                    }
                    else if (isPractice)
                    {
                        // don't aggregate practice stints, otherwise we track low fuel runs
                        usagePerLapOutgoing.Clear();
                    }

                    return;
                }

                if (!enableFuelMessages
                    || !currentGameState.FuelData.FuelUseActive
                    || onLowFuelRun
                    || currentGameState.PitData.InPitlane
                    || currentFuel <= 0)
                {
                    return;
                }

                // warnings for particular fuel levels

                // warn when one/half a gallon left (approx 4L/2L!) or two/one litre left
                {   // (braces just to mark this clause)
                    if (fuelReportsInGallons)
                    {
                        float gallons = Utilities.Conversions.convertLitresToGallons(currentFuel);
                        if (gallons <= 0.5f && !played1LitreWarning)
                        {
                            //^^
                            played1LitreWarning = true;
                            played2LitreWarning = true;
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage("Fuel/level", 0, messageFragments: MessageContents(folderHalfAGallonRemaining), abstractEvent: this, priority: 10));
                                lastFuelCall = currentGameState.Now;
                                NotifyLFSFuel();
                            }
                        }
                        else if (gallons <= 1 && !played2LitreWarning)
                        {
                            // yes i know its not 2 litres but who really cares.
                            played2LitreWarning = true;
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage("Fuel/level", 0, messageFragments: MessageContents(folderOneGallonRemaining), abstractEvent: this, priority: 10));
                                lastFuelCall = currentGameState.Now;
                                NotifyLFSFuel();
                            }
                        }
                    }
                    else
                    {
                        if (currentFuel <= 1 && !played1LitreWarning)
                        {
                            played1LitreWarning = true;
                            played2LitreWarning = true;
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage("Fuel/level", 0, messageFragments: MessageContents(folderOneLitreRemaining), abstractEvent: this, priority: 10));
                                lastFuelCall = currentGameState.Now;
                                NotifyLFSFuel();
                            }
                        }
                        else if (currentFuel <= 2 && !played2LitreWarning)
                        {
                            played2LitreWarning = true;
                            if (canPlayFuelMessage())
                            {
                                audioPlayer.playMessage(new QueuedMessage("Fuel/level", 0, messageFragments: MessageContents(2, folderLitresRemaining), abstractEvent: this, priority: 10));
                                lastFuelCall = currentGameState.Now;
                                NotifyLFSFuel();
                            }
                        }
                    }
                }

                {  // warnings for fixed lap sessions
                    float averageUsagePerLapToCheck = getConsumptionPerLap();

                    bool _checkForFuelWarnings = (averageUsagePerLapToCheck > 0 &&
                        currentGameState.FuelData.FuelLeft > 0 &&
                        lapsCompletedSinceFuelReset > 0);

                    if (_checkForFuelWarnings)
                    {
                        int estimatedFuelLapsLeft = (int)Math.Floor(currentGameState.FuelData.FuelLeft / averageUsagePerLapToCheck);
                        bool _checkIfHalfDistance = !playedHalfDistance
                            && halfDistance > 0
                            && lapsRemaining > 0
                            && estimatedFuelLapsLeft > 1
                            && currentGameState.SessionData.SessionType == SessionType.Race;

                        if (currentGameState.SessionData.IsNewLap)
                        {
                            int VirtualEnergy = LMU.VirtualEnergy.Read();
                            if (VirtualEnergy >= 0 && VirtualEnergy <= 100)
                            {
                                Log.Fuel(() => $"Virtual Energy: {VirtualEnergy}%");
                            }
                            if (_checkIfHalfDistance)
                            {
                                var _raceHasEvenLaps = (currentGameState.SessionData.SessionNumberOfLaps & 1) == 0 || // even number of laps
                                                        currentGameState.SessionData.SessionNumberOfLaps >= 6;        // or at least 6 laps
                                if (currentGameState.SessionData.CompletedLaps == halfDistance &&
                                    _raceHasEvenLaps)
                                {
                                    reportHalfDistance(currentGameState, estimatedFuelLapsLeft);
                                    NotifyLFSFuel();
                                }
                            }
                            else if (lapsRemaining > 4 && estimatedFuelLapsLeft == 4)
                            {
                                Log.Fuel(() => "4 laps fuel left, starting fuel = " + litresToUnits(initialFuelLevel, false) +
                                        ", current fuel = " + litresToUnits(currentGameState.FuelData.FuelLeft, false) + ", usage per lap = " + litresToUnits(averageUsagePerLapToCheck, true));
                                if (canPlayFuelMessage())
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderFourLapsEstimate, 0, abstractEvent: this, priority: 3));
                                    lastFuelCall = currentGameState.Now;
                                }
                            }
                            else if (lapsRemaining > 3 && estimatedFuelLapsLeft == 3)
                            {
                                Log.Fuel(() => "3 laps fuel left, starting fuel = " + litresToUnits(initialFuelLevel, false) +
                                        ", current fuel = " + litresToUnits(currentGameState.FuelData.FuelLeft, false) + ", usage per lap = " + litresToUnits(averageUsagePerLapToCheck, true));
                                if (canPlayFuelMessage())
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderThreeLapsEstimate, 0, abstractEvent: this, priority: 5));
                                    lastFuelCall = currentGameState.Now;
                                    NotifyLFSFuel();
                                }
                            }
                            else if (lapsRemaining > 2 && estimatedFuelLapsLeft == 2)
                            {
                                Log.Fuel(() => "2 laps fuel left, starting fuel = " + litresToUnits(initialFuelLevel, false) +
                                        ", current fuel = " + litresToUnits(currentGameState.FuelData.FuelLeft, false) + ", usage per lap = " + litresToUnits(averageUsagePerLapToCheck, true));
                                if (canPlayFuelMessage())
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderTwoLapsEstimate, 0, abstractEvent: this, priority: 7));
                                    lastFuelCall = currentGameState.Now;
                                    NotifyLFSFuel();
                                }
                            }
                            else if (lapsRemaining > 1 && estimatedFuelLapsLeft == 1)
                            {
                                // these lapsRemaining checks seem like they are off-by-one because they will say "X laps of fuel left"
                                // when there are X laps left in the race. But people might like to be reassured. We disable the last
                                // lap one only because it is very weird to get a call to pit the next lap when it's our last lap.
                                Log.Fuel(() => "1 lap fuel left, starting fuel = " + litresToUnits(initialFuelLevel, false) +
                                        ", current fuel = " + litresToUnits(currentGameState.FuelData.FuelLeft, false) + ", usage per lap = " + litresToUnits(averageUsagePerLapToCheck, true));
                                if (canPlayFuelMessage())
                                {
                                    audioPlayer.playMessage(new QueuedMessage(folderOneLapEstimate, 0, abstractEvent: this, priority: 10));
                                    lastFuelCall = currentGameState.Now;
                                }
                                playPitForFuelNow = true;
                            }
                        }
                        else // not a new lap, but we might be part way round
                             // the half way lap of a race of few laps
                        {
                            var _halfLapIsh = previousGameState.SessionData.SectorNumber == 1 &&
                                              currentGameState.SessionData.SectorNumber == 2;    // part way round the lap (half way round would be better but that info is not immediately apparent)
                            if (_checkIfHalfDistance &&
                                currentGameState.SessionData.CompletedLaps == halfDistance - 1 &&
                                _halfLapIsh)
                            {   // part way round the half way lap 
                                reportHalfDistance(currentGameState, estimatedFuelLapsLeft);
                            }
                        }
                    }
                }

                // these are useful messages even in fixed timed races and races without pitstops because it prompts to
                // consider car balance issues, such as brake bias.
                //
                // It would be good if we also had a "you have half a tank left" message looking at capacity rather than
                // stint fuel, since that would be a more consistent message in terms of car balance.
                if (!playedHalfTankWarning
                    && (currentGameState.SessionData.TrackDefinition.trackLengthClass > TrackData.TrackLengthClass.MEDIUM || lapsRemaining > 2)
                    && currentGameState.FuelData.FuelLeft / initialFuelLevel <= 0.50
                    && currentGameState.FuelData.FuelLeft / initialFuelLevel >= 0.47)
                {
                    playedHalfTankWarning = true;
                    if (canPlayFuelMessage() && currentGameState.SessionData.CompletedLaps > 1)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderHalfTankWarning, 0, abstractEvent: this, priority: 0));
                        lastFuelCall = currentGameState.Now;
                        if (Game.LFS)
                        {
                            CrewChiefV4.LFS.LFSInSimReader.SendMessageLocal(
                                CrewChiefV4.LFS.LFSInSimReader.GetLocalizedMessage("lfs_msg_half_tank", "^3[CrewChief] Half tank: {0:0.0}%", currentFuel));
                        }
                    }
                }

                // detects pitstops enforced by fuel limit
                if (!playedPitWindowEstimate && currentGameState.SessionData.SessionType == SessionType.Race &&
                    !currentGameState.PitData.HasMandatoryPitStop &&
                    previousGameState.SessionData.SectorNumber != currentGameState.SessionData.SectorNumber)
                {
                    Tuple<int, int> predictedWindow = getPredictedPitWindow(currentGameState);
                    // item1 is the earliest minute / lap we can pit on, item2 is the latest. Note that item1 might be negative if
                    // we *could* have finished the race without refuelling (if we'd filled the tank). It might also be less than the
                    // number of minutes / laps completed

                    int lapsUntilWindowCheck = 3;
                    if (currentGameState.SessionData.TrackDefinition.trackLengthClass < TrackData.TrackLengthClass.MEDIUM)
                    {
                        lapsUntilWindowCheck = 5;
                    }
                    else if (currentGameState.SessionData.TrackDefinition.trackLengthClass > TrackData.TrackLengthClass.MEDIUM)
                    {
                        lapsUntilWindowCheck = 1;
                    }

                    // Skip the check if we don't have enough data.
                    //
                    // Also, if we think we might make it on fuel without a stop, then cancel the pit window announcement.
                    // This avoids the situation when we pit with an extremely tight margin, and immediately get "pit window open".
                    if (currentGameState.SessionData.CompletedLaps < lapsUntilWindowCheck || getAdditionalFuelToEndOfRace(false, verbose: false) <= 0)
                    {
                        predictedWindow = new Tuple<int, int>(-1, -1);
                    }

                    if (predictedWindow.Item2 != -1)
                    {
                        {
                            if (predictedWindow.Item2 > sessionNumberOfLaps)
                            {
                                Console.WriteLine("Skipping fuel window announcement because we might make it on fuel");
                            }
                            else if (playedPitForFuelNow || currentGameState.PitData.InPitlane)
                            {
                                // this can happen at long tracks when laps remaining kicks in before the estimate
                                // so we have technically already given the player this information (albeit in a different form)
                                // or they already figured it out themselves and dived into the pits.
                                Log.Fuel("Skipping fuel window announcement because we already know that we need to stop");
                                playedPitWindowEstimate = true;
                                playedPitForFuelNow = true;
                                playedPitWindowOpen = true;
                            }
                            else if (predictedWindow.Item1 == currentGameState.SessionData.CompletedLaps
                                && predictedWindow.Item1 != predictedWindow.Item2
                                && predictedWindow.Item2 != sessionNumberOfLaps)
                            {
                                // corner case where we just calculated that the pit window opens this lap (can happen at longer tracks as early as lap 2).
                                // we want to avoid playing an additional "pit window is open" message so we flag it as played. We don't play this
                                // if the window closes on the same lap to avoid spamming when fuel saving.
                                Log.Fuel("We know the pit window opens this lap, so bundle all the messages together");
                                var fragments = MessageContents(PitStops.folderMandatoryPitStopsPitWindowOpen, folderWillNeedToPitForFuelByLap, predictedWindow.Item2, Pause(200));
                                if (Strategy.persistBenchmarks && !Strategy.naggedAboutBenchmarks && BenchmarkHelper.findPersistedBenchmarkForCombo(-1) == null
                                    && SoundCache.soundSets.ContainsKey(LapCounter.folderNoPitstopEstimatesFuel))
                                {
                                    // see below
                                    Strategy.naggedAboutBenchmarks = true;
                                    fragments.Add(MessageFragment.Text(LapCounter.folderNoPitstopEstimatesFuel));
                                }
                                audioPlayer.playMessage(new QueuedMessage("Fuel/pit_window_for_fuel", 0, secondsDelay: Utilities.random.Next(8), messageFragments: fragments));
                                playedPitWindowEstimate = true;
                                playedPitWindowOpen = true;
                                Strategy.playPitPositionEstimates = true;
                            }
                            // if item1 is < current minute but item2 is sensible, we want to say "pit window for fuel closes after X laps"
                            else if (predictedWindow.Item1 < currentGameState.SessionData.CompletedLaps)
                            {
                                if (predictedWindow.Item2 == sessionNumberOfLaps)
                                {
                                    // really very marginal to the end
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/pit_window_for_fuel", 0, secondsDelay: Utilities.random.Next(8), messageFragments: MessageContents(folderFuelWillBeTight)));
                                }
                                else
                                {
                                    var msg = MessageContents(folderWillNeedToPitForFuelByLap, predictedWindow.Item2, Pause(200));
                                    if (Strategy.persistBenchmarks && !Strategy.naggedAboutBenchmarks && BenchmarkHelper.findPersistedBenchmarkForCombo(-1) == null
                                        && SoundCache.soundSets.ContainsKey(LapCounter.folderNoPitstopEstimatesFuel))
                                    {
                                        // we could be better here and detect how much fuel our benchmark used and if it is not within 5 litres
                                        // of reality we could play this. But for now, just play it if we have no estimates... it's on the driver
                                        // if they didn't do the benchmark for race conditions.
                                        Strategy.naggedAboutBenchmarks = true;
                                        msg.Add(MessageFragment.Text(LapCounter.folderNoPitstopEstimatesFuel));
                                    }
                                    audioPlayer.playMessage(new QueuedMessage("Fuel/pit_window_for_fuel", 0, secondsDelay: Utilities.random.Next(8), messageFragments: msg));
                                }
                                playedPitWindowEstimate = true;
                            }
                            else
                            {
                                var msg = MessageContents(folderFuelWindowOpensOnLap, predictedWindow.Item1, folderAndFuelWindowClosesOnLap, predictedWindow.Item2, Pause(200));
                                if (Strategy.persistBenchmarks && !Strategy.naggedAboutBenchmarks && BenchmarkHelper.findPersistedBenchmarkForCombo(-1) == null
                                    && SoundCache.soundSets.ContainsKey(LapCounter.folderNoPitstopEstimatesFuel))
                                {
                                    // see above
                                    Strategy.naggedAboutBenchmarks = true;
                                    msg.Add(MessageFragment.Text(LapCounter.folderNoPitstopEstimatesFuel));
                                }
                                audioPlayer.playMessage(new QueuedMessage("Fuel/pit_window_for_fuel", 0, secondsDelay: Utilities.random.Next(8), messageFragments: msg));
                                playedPitWindowEstimate = true;
                            }
                        }
                    }
                }

                if (playedPitWindowEstimate && !playedPitWindowOpen && currentGameState.SessionData.SessionType == SessionType.Race &&
                    !currentGameState.PitData.HasMandatoryPitStop &&
                    // check every 5 sec regardless if its a time limited or lap limited race, we want to know this as soon as possible. 
                    currentGameState.Now > nextFuelPitWindowOpenCheck)
                {
                    nextFuelPitWindowOpenCheck = currentGameState.Now.Add(fuelStatusCheckInterval);
                    float litresNeeded = getAdditionalFuelToEndOfRace(true, verbose: false);
                    if (litresNeeded <= currentFuel * fuel_saving_coefficient)
                    {
                        playedPitWindowOpen = true;
                    }
                    else if (litresNeeded <= fuelCapacity - currentFuel)
                    {
                        Console.WriteLine($"Pit Window is now open, Litres Needed: {litresNeeded}");
                        playedPitWindowOpen = true;
                        audioPlayer.playMessage(new QueuedMessage(PitStops.folderMandatoryPitStopsPitWindowOpen, 0, abstractEvent: this, priority: 10));
                        Strategy.playPitPositionEstimates = true; // this might come before or instead of the "pit window is open" call, but that's ok.
                    }
                }
            }
        }

        private void resetVirtualEnergyWarnings()
        {
            lastVirtualEnergyLapWarning = 5;
            playedVirtualEnergyEmptyWarning = false;
            playedVirtualEnergyPitWarning = false;
            pitForVirtualEnergy = false;
        }

        private void updateVirtualEnergyUsage(GameStateData currentGameState)
        {
            int energy = LMU.VirtualEnergy.Read();
            if (energy < 0 || energy > 100)
            {
                // Missing telemetry must not turn the next sample into a multi-lap sample.
                previousVirtualEnergy = -1;
                virtualEnergyAtLapStart = -1;
                virtualEnergyLapWasGreen = false;
                return;
            }

            bool replenished = previousVirtualEnergy >= 0 && energy > previousVirtualEnergy;
            if (previousVirtualEnergy < 0 || replenished || currentGameState.PitData.JumpedToPits)
            {
                virtualEnergyAtLapStart = -1;
                resetVirtualEnergyWarnings();
                if (currentGameState.PitData.JumpedToPits)
                {
                    virtualEnergyUsageByLap.Clear();
                }
            }
            previousVirtualEnergy = energy;
            bool clean = greenLap && !currentGameState.PitData.InPitlane &&
                !currentGameState.PitData.IsInGarage;
            virtualEnergyLapWasGreen &= clean;

            if (!currentGameState.SessionData.IsNewLap ||
                virtualEnergyLap == currentGameState.SessionData.CompletedLaps)
            {
                return;
            }
            int completedLaps = currentGameState.SessionData.CompletedLaps;
            if (virtualEnergyAtLapStart >= 0 && virtualEnergyLapWasGreen &&
                completedLaps == virtualEnergyLap + 1)
            {
                float used = virtualEnergyAtLapStart - energy;
                if (used > 0)
                {
                    virtualEnergyUsageByLap.Add(used);
                    int window = Math.Max(1, fuelUseByLapsWindowLengthToUse);
                    while (virtualEnergyUsageByLap.Count > window)
                    {
                        virtualEnergyUsageByLap.RemoveAt(0);
                    }
                    Log.Fuel(() => $"Virtual energy usage: {used}% this lap, {virtualEnergyUsageByLap.Average():0.00}% average");
                }
            }
            virtualEnergyAtLapStart = energy;
            virtualEnergyLap = completedLaps;
            virtualEnergyLapWasGreen = !currentGameState.PitData.InPitlane &&
                !currentGameState.PitData.IsInGarage &&
                (currentGameState.SessionData.SessionPhase == SessionPhase.Green ||
                 currentGameState.SessionData.SessionPhase == SessionPhase.Checkered);
        }

        private void warnAboutVirtualEnergy(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (!enableFuelMessages || onLowFuelRun || currentGameState.PitData.InPitlane ||
                currentGameState.PitData.IsInGarage ||
                currentGameState.SessionData.SessionPhase >= SessionPhase.Finished || previousVirtualEnergy < 0)
            {
                return;
            }
            float energy = previousVirtualEnergy;
            float usage = virtualEnergyUsageByLap.Count == 0 ? 0 : virtualEnergyUsageByLap.Average();
            bool enteredSector3 = previousGameState.SessionData.SectorNumber == 2 &&
                currentGameState.SessionData.SectorNumber == 3;
            // Warn before depletion causes a penalty, regardless of the current sector.
            if (!playedVirtualEnergyEmptyWarning && 
                usage > 0 &&
                energy > 0 &&
                energy < usage / 3f)
            {
                playedVirtualEnergyEmptyWarning = true;
                playVirtualEnergyWarning("fuel/about_to_run_out", 10);
            }
            if (pitForVirtualEnergy &&
                !playedVirtualEnergyPitWarning &&
                (enteredSector3 ||
                 GlobalBehaviourSettings.useOvalLogic ||
                 currentGameState.SessionData.TrackDefinition.trackLengthClass < TrackData.TrackLengthClass.MEDIUM))
            {
                playedVirtualEnergyPitWarning = true;
                playVirtualEnergyWarning("mandatory_pit_stops/pit_this_lap", 10);
            }
            if (usage > 0 && currentGameState.SessionData.IsNewLap)
            {
                int energyLaps = (int)Math.Floor(energy / usage);
                if (energyLaps >= 1
                    && energyLaps <= 2
                    && energyLaps < lastVirtualEnergyLapWarning
                    && (lapsRemaining < 0 || lapsRemaining > energyLaps))
                {
                    lastVirtualEnergyLapWarning = energyLaps;
                    string[] sounds =
                    {
                        "", "one_lap", "two_laps" //, "three_laps", "four_laps"
                    };
                    playVirtualEnergyWarning("fuel/virtual_energy_" + sounds[energyLaps],
                        energyLaps == 1 ? 10 : energyLaps == 2 ? 7 : energyLaps == 3 ? 5 : 3);
                    pitForVirtualEnergy = energyLaps == 1;
                }
            }
        }

        private void playVirtualEnergyWarning(string sound, int priority)
        {
            // VE warnings have independent flags and are not suppressed by lastFuelCall.
            audioPlayer.playMessageOrFallback(sound, AudioPlayer.folderAcknowlegeOK,
                immediately: false, priority: priority, abstractEvent: this);
        }

        private void reportHalfDistance(GameStateData currentGameState, int estimatedFuelLapsLeft)
        {
            playedHalfDistance = true;

            var litresNeededExact = getAdditionalFuelToEndOfRace(false);
            if (canPlayFuelMessage() && litresNeededExact > 0 && litresNeededExact < currentFuel * fuel_saving_coefficient)
            {
                audioPlayer.playMessage(new QueuedMessage("Fuel/estimate", 0,
                    messageFragments: MessageContents(RaceTime.folderHalfWayHome, folderFuelWillBeTight),
                    abstractEvent: this, priority: 7));
                lastFuelCall = currentGameState.Now;
            }
            else if (estimatedFuelLapsLeft < lapsRemaining)
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
                    lastFuelCall = currentGameState.Now;
                }
            }
            else
            {
                audioPlayer.playMessage(new QueuedMessage(folderHalfDistanceGoodFuel, 0, abstractEvent: this, priority: 5));
                lastFuelCall = currentGameState.Now;
            }
        }

        /// <summary>
        /// Used by "How much fuel for x laps?"
        /// </summary>
        /// <param name="numberOfLaps"></param>
        /// <returns></returns>
        private Boolean reportFuelConsumptionForLaps(int numberOfLaps)
        {
            Boolean haveData = false;
            if (averageUsagePerLap > 0)
            {
                // round up
                float totalUsage = 0f;
                if (fuelReportsInGallons)
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
                    if (fuelReportsInGallons)
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
            if (averageUsagePerMinuteToCheck > 0)
            {
                int timeToUse = (hours * 60) + minutes;
                // round up
                float totalUsage = 0;
                if (fuelReportsInGallons)
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
                    if (fuelReportsInGallons)
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
        /// "Plenty of fuel" / "Fuel will be tight" / "You need to pit" / etc.
        /// </summary>
        /// <param name="allowNoDataMessage">this is fuel specific command response -
        /// "How's my fuel?" or "Report fuel/battery status"</param>
        /// <param name="isRace"></param>
        public static void ReportFuelStatus(Boolean allowNoDataMessage, Boolean isRace)
        {
            if (!CrewChief.fuelMultiplier.active) 
            {
                return;
            }
            if (!UserSettings.GetUserSettings().getBoolean("legacy_fuel"))
            {
                var fragments = inst.reportFuelStatus(true);
                if (fragments.Count > 0)
                {
                    inst.audioPlayer.playMessageImmediately(new QueuedMessage("fuel_status", 0, messageFragments: fragments));
                    lastFuelCall = CrewChief.currentGameState.Now;
                }
                else if (allowNoDataMessage)
                {
                    inst.audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                }
            }
            else
            {
                legacy_inst.reportFuelStatus(allowNoDataMessage, isRace);
            }
        }

        // tells us when we need to pit, and (optionally) how much we'll add, or "fuel is ok".
        private List<MessageFragment> reportFuelStatus(Boolean giveExtraContext)
        {
            var fragments = new List<MessageFragment>();
            if (!initialised || currentFuel < 0 || CrewChief.currentGameState == null || averageUsagePerLap <= 0)
            {
                return fragments;
            }

            // this is about how much fuel is needed to be added to get to the end,
            // not how much literally to the end from here.
            float litresNeededExact = getAdditionalFuelToEndOfRace(false, verbose: false); // no reserve so we don't suggest a false pit
            float litresNeededWithMargin = getAdditionalFuelToEndOfRace(true); // recalculate with reserve for accurate numbers

            if (litresNeededExact == NO_FUEL_DATA)
            {
                return fragments;
            }
            else if (litresNeededWithMargin < 0)
            {
                fragments.Add(MessageFragment.Text(folderPlentyOfFuel));
            }
            else if (litresNeededExact < 0)
            {
                fragments.Add(MessageFragment.Text(folderFuelShouldBeOK));
            }
            else if (giveExtraContext && litresNeededExact < currentFuel * fuel_saving_coefficient)
            {
                fragments.Add(MessageFragment.Text(folderFuelWillBeTight));
            }
            else
            {
                if (giveExtraContext)
                {
                    fragments.Add(MessageFragment.Text(folderWillNeedToPitForFuelByTimeIntro));
                    // this could be annoying
                    if (litresNeededWithMargin > fuelCapacity)
                    {
                        fragments.Add(MessageFragment.Text("flags/and"));
                        fragments.Add(MessageFragment.Text(folderWillNeedToStopAgain));
                    }
                }

                float fuelStartingThisLap = currentFuel;
                if (fuelLevelWindowByLap.Count > 0)
                {
                    fuelStartingThisLap = fuelLevelWindowByLap.First();
                }
                int lapsOfFuelLeft = (int)Math.Floor(fuelStartingThisLap / averageUsagePerLap);
                int minutesOfFuelLeft = -1;
                float consumption_per_minute = getConsumptionPerMinute();
                if (consumption_per_minute > 0) // might have struggled to get a lap time estimate...
                {
                    minutesOfFuelLeft = (int)Math.Floor(currentFuel / consumption_per_minute);
                }

                if (giveExtraContext)
                {
                    if (lapsOfFuelLeft <= 1)
                    {
                        fragments.Add(MessageFragment.Text(folderAboutToRunOut));
                    }
                    else if (!reportFuelLapsLeftInTimedRaces && CrewChief.currentGameState.SessionData.SessionHasFixedTime && minutesOfFuelLeft > 5 && lapsOfFuelLeft > 3)
                    {
                        // we have custom recordings for 2, 5 and 10 minutes but it's hardly worth coding them up
                        fragments.Add(MessageFragment.Integer(minutesOfFuelLeft, false, MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)));
                        fragments.Add(MessageFragment.Text(folderMinutesRemaining));
                    }
                    else
                    {
                        // when the race is fixed laps, or we get really close to the stop, we'd prefer to think about it in terms of laps
                        fragments.Add(MessageFragment.Text(folderWeEstimate));
                        fragments.Add(MessageFragment.Integer(lapsOfFuelLeft, false, MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)));
                        fragments.Add(MessageFragment.Text(folderLapsRemaining));
                    }
                }

                fragments.Add(MessageFragment.Text(folderWillNeedToAdd));
                if (fuelReportsInGallons)
                {
                    // for gallons we want both whole and fractional part cause its a stupid unit.
                    float gallonsNeeded = Utilities.Conversions.convertLitresToGallons(litresNeededWithMargin, true);
                    fragments.AddRange(Utilities.WholeAndFractionalMessage(gallonsNeeded));
                    fragments.Add(MessageFragment.Text(folderGallons));
                }
                else
                {
                    int litresNeeded = (int)Math.Ceiling(litresNeededWithMargin);
                    fragments.Add(MessageFragment.Integer(litresNeeded));
                    fragments.Add(MessageFragment.Text(folderLitres));
                }

                if (giveExtraContext && litresNeededWithMargin <= fuelCapacity - currentFuel)
                {
                    fragments.Add(MessageFragment.Text(PitStops.folderMandatoryPitStopsPitWindowOpen));
                }
                NotifyLFSFuel(litresNeededWithMargin);
            }
            return fragments;
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
        private static readonly List<SpeechCommands.ID> Commands = new List<SpeechCommands.ID>
        {
            SpeechCommands.ID.CALCULATE_FUEL_FOR,
            SpeechCommands.ID.CAR_STATUS,
            SpeechCommands.ID.HOWS_MY_FUEL,
            SpeechCommands.ID.HOW_MUCH_FUEL_TO_END_OF_RACE,
            SpeechCommands.ID.SET_FUEL_STRATEGY_CAUTIOUS,
            SpeechCommands.ID.SET_FUEL_STRATEGY_RESET,
            SpeechCommands.ID.SET_FUEL_STRATEGY_RISKY,
            SpeechCommands.ID.STATUS,
            SpeechCommands.ID.WHATS_MY_FUEL_LEVEL,
            SpeechCommands.ID.WHATS_MY_FUEL_USAGE,
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
            if (!GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.FUEL) ||
                !CrewChief.fuelMultiplier.active)
            {
                if (cmd != SpeechCommands.ID.CAR_STATUS && cmd != SpeechCommands.ID.STATUS)
                {
                    this.audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                    Log.Commentary($"No data for {this.GetType().Name}");
                }
                return;
            }

            switch (cmd)
            {
                case SpeechCommands.ID.WHATS_MY_FUEL_USAGE:
                {
                        var fragments = new List<MessageFragment>();
                        if (averageUsagePerLap > 0)
                    {
                            if (fuelReportsInGallons)
                        {
                                // for gallons we want both whole and fractional part cause its a stupid unit.
                                float gallons = Utilities.Conversions.convertLitresToGallons(averageUsagePerLap, true);
                                fragments.AddRange(Utilities.WholeAndFractionalMessage(gallons));
                                fragments.Add(MessageFragment.Text(folderGallonsPerLap));
                        }
                        else
                        {
                                float litres = averageUsagePerLap;
                                fragments.AddRange(Utilities.WholeAndFractionalMessage(litres));
                                fragments.Add(MessageFragment.Text(folderLitresPerLap));
                        }
                    }
                        if (fragments.Count > 0)
                    {
                            audioPlayer.playMessageImmediately(new QueuedMessage("Fuel/mean_use_per_lap", 0, fragments));
                            NotifyLFSFuel();
                    }
                    else
                    {
                            audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                    }

                        break;
                }
                case SpeechCommands.ID.WHATS_MY_FUEL_LEVEL:
                {
                        var message = new List<MessageFragment>();
                        if (currentFuel < 2)
                    {
                            message.AddRange(MessageContents(folderAboutToRunOut));
                    }
                    else if (fuelReportsInGallons)
                    {
                            message.AddRange(Utilities.WholeAndFractionalMessage(
                                Utilities.Conversions.convertLitresToGallons(currentFuel)));
                            message.AddRange(MessageContents(folderGallonsRemaining));
                    }
                    else
                    {
                            message.AddRange(MessageContents((int)currentFuel, folderLitresRemaining));
                    }

                        audioPlayer.playMessageImmediately(new QueuedMessage("fuel_level", 0, message));
                        NotifyLFSFuel();
                        break;
                }
                case SpeechCommands.ID.SET_FUEL_STRATEGY_CAUTIOUS:
                case SpeechCommands.ID.SET_FUEL_STRATEGY_RISKY:
                case SpeechCommands.ID.SET_FUEL_STRATEGY_RESET:
                {
                    if (cmd == SpeechCommands.ID.SET_FUEL_STRATEGY_CAUTIOUS)
                    {
                            reserveMultiplier = 2.0f;
                    }
                    else if (cmd == SpeechCommands.ID.SET_FUEL_STRATEGY_RISKY)
                    {
                            reserveMultiplier = 0.5f; // we might even want to go to 0 here
                    }
                    else
                    {
                            reserveMultiplier = 1.0f;
                    }
                    updateAverageFuelUsage(CrewChief.currentGameState);
                    // we don't have a dedicated voice response here, so just forward :-(
                    respond(voiceMessage, SpeechCommands.ID.HOW_MUCH_FUEL_TO_END_OF_RACE);
                    break;
                }
                case SpeechCommands.ID.CALCULATE_FUEL_FOR:
                { // Laps, minutes or hours
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
                                report_not_enough_laps();
                        }
                    }
                    else if (SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.MINUTE) || SpeechRecogniser.ResultContains(voiceMessage, SpeechRecogniser.MINUTES))
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

                    break;
                }
                case SpeechCommands.ID.HOW_MUCH_FUEL_TO_END_OF_RACE:
                case SpeechCommands.ID.HOWS_MY_FUEL:
                {
                        var fragments = reportFuelStatus(cmd != SpeechCommands.ID.HOW_MUCH_FUEL_TO_END_OF_RACE);
                        if (fragments.Count > 0)
                    {
                            this.audioPlayer.playMessageImmediately(new QueuedMessage("fuel_status", 0, messageFragments: fragments));
                            lastFuelCall = CrewChief.currentGameState.Now;
                    }
                    else
                    {
                            report_not_enough_laps();
                    }
                        break;
                }
                case SpeechCommands.ID.CAR_STATUS:
                case SpeechCommands.ID.STATUS:
                {
                        // Same as above but no "no data" message
                        var fragments = reportFuelStatus(true);
                        if (fragments.Count > 0)
                    {
                            this.audioPlayer.playMessageImmediately(new QueuedMessage("fuel_status", 0, messageFragments: fragments));
                            lastFuelCall = CrewChief.currentGameState.Now;
                    }
                        break;
                }
            }
        }

        private void report_not_enough_laps()
        {
            if (SoundCache.availableSounds.Contains(folderNotEnoughLapsForAverage))
            {
                audioPlayer.playMessageImmediately(new QueuedMessage(folderNotEnoughLapsForAverage, 0));
            }
            else
            {
                audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
            }
        }

        /// <summary>
        /// Convert litres to a string in selected units and precision
        /// </summary>
        /// <param name="fractions">3 decimal places vs. whole litres/10ths of gals</param>
        /// <returns></returns>
        private string litresToUnits(float litres, bool fractions)
        {
            string fmt = fuelReportsInGallons ?
                (fractions ? "F3" : "F1") :
                (fractions ? "F3" : "F0");
            return fuelReportsInGallons ?
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
        public static float GetAdditionalFuelToEndOfRace(Boolean addReserve, bool verbose = true, int lapAdjustment = 0)
        {
            // if (!CrewChief.fuelMultiplier.active) leave it to getAdditionalFuelToEndOfRace()
            // to deal with that.

            if (!UserSettings.GetUserSettings().getBoolean("legacy_fuel"))
            {
                return inst.getAdditionalFuelToEndOfRace(addReserve, verbose, lapAdjustment);
            }
            else
            {
                return legacy_inst.getAdditionalFuelToEndOfRace(addReserve, verbose);
            }
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
        private float getAdditionalFuelToEndOfRace(Boolean addReserve, bool verbose = true, int lapAdjustment = 0)
        {
            float additionalLitresNeeded = NO_FUEL_DATA;
            if (CrewChief.fuelMultiplier.active &&
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
                float averageUsagePerLapForCalculation;
                averageUsagePerLapForCalculation = getConsumptionPerLap();

                float reserve = HALF_LAP_RESERVE_DEFAULT;
                var _trackLengthClass = CrewChief.currentGameState.SessionData.TrackDefinition.trackLengthClass;
                float extra = fuelReserveLapsMedium;

                if (_trackLengthClass > TrackData.TrackLengthClass.MEDIUM)
                {
                    extra = fuelReserveLapsLong;
                }
                else if (_trackLengthClass < TrackData.TrackLengthClass.MEDIUM)
                {
                    extra = fuelReserveLapsShort;
                }

                if (GlobalBehaviourSettings.useOvalLogic)
                {
                    extra += fuelExtraLapsOval;
                }
                else if (CrewChief.currentGameState.SessionData.SessionTotalRunTime >= 60f * 60f &&
                    _trackLengthClass < TrackData.TrackLengthClass.LONG)
                {
                    extra += fuelExtraLapsEndurance;
                }

                reserve = extra * averageUsagePerLapForCalculation;

                reserve = reserveMultiplier * reserve;

                if (averageUsagePerLapForCalculation > 0 && lapsRemaining > 0)
                {
                    float lapsToFill = lapsRemaining;
                    lapsToFill += lapAdjustment;

                    float totalLitresNeededToEnd = (averageUsagePerLapForCalculation * lapsToFill) + (addReserve ? reserve : 0);

                    float fuelThisLap = 0f;
                    if (!CrewChief.currentGameState.PitData.InPitlane)
                    {
                        // deduct the fuel to get to the pits, which can be very significant at larger tracks.
                        // There's two ways to do this: either we deduct one lap and add the fuel to get
                        // to the end of this lap, or we estimate the full amount and discount the amount
                        // fuel burnt on this lap. We know exactly how much fuel we've burnt this lap
                        // so we prefer to use that approach. In effect, we reset the currentFuel back to what
                        // it was at the start of this lap.
                        if (fuelLevelWindowByLap.Count > 0)
                        {
                            fuelThisLap = Math.Max(0f, fuelLevelWindowByLap.First() - currentFuel);
                        }
                    }

                    additionalLitresNeeded = totalLitresNeededToEnd - (currentFuel + fuelThisLap);
                    if (verbose)
                    {
                        var reserve_part = "";
                        if (addReserve)
                        {
                            reserve_part = $" reserve = {litresToUnits(reserve, true)}";
                        }
                        Log.Fuel(
                            "Use per lap = " + litresToUnits(averageUsagePerLapForCalculation, true) +
                            " laps to fill = " + lapsToFill +
                            " current fuel = " + litresToUnits(currentFuel, true) +
                            " fuel this lap = " + litresToUnits(fuelThisLap, true) +
                            " additional fuel needed = " + litresToUnits(additionalLitresNeeded, true) +
                            reserve_part);
                        int VirtualEnergy = LMU.VirtualEnergy.Read();
                        if (VirtualEnergy >= 0 && VirtualEnergy <= 100)
                        {
                            Log.Fuel(() => $"Virtual Energy = {VirtualEnergy}%");
                        }
                    }
                }
            }
            return additionalLitresNeeded;
        }

        // We want to estimate the average lap time that we are expected to put in
        // for the rest of the session. Even ignoring changes in weather and track
        // conditions, this is difficult to estimate because the player may be stuck
        // behind traffic, gaining a draft advantage, fuel saving and after pitting
        // they may be on faster / slower tyres and have gained or lost draft.
        //
        // Estimating a lower lap time than what will actually happen is the
        // conservative thing to do and will typically result in sometimes putting
        // one lap extra of fuel in for the refuel. The easiest way to achieve this
        // is to always pick the fastest lap in the session so far, which does attempt
        // to take current track conditions into account. We could go even further
        // and use persisted data including for quali / low fuel runs.
        private float estimateFutureAverageLapTime(GameStateData currentGameState)
        {
            if (currentGameState == null)
            {
                return -1;
            }
            float dirty = currentGameState.SessionData.LapTimePreviousEstimateForInvalidLap;
            float best = currentGameState.TimingData.getPlayerClassBestLapTime();
            float estimated = currentGameState.SessionData.EstimatedLapTime;

            if (estimated > 0 && currentGameState.SessionData.CompletedLaps < 2)
            {
                return estimated;
            }

            if (best > 0)
            {
                return best;
            }
            else if (dirty > 0)
            {
                return dirty;
            }
            else if (estimated > 0)
            {
                return estimated;
            }

            return -1;
        }

        private float estimateFutureAverageLapTimeForLeader(GameStateData currentGameState)
        {
            if (currentGameState == null)
            {
                return -1;
            }

            var leader = currentGameState.getOpponentAtOverallPosition(1);
            if (leader == null)
            {
                return -1;
            }

            float session_best = currentGameState.SessionData.OverallSessionBestLapTime;
            float best = leader.CurrentBestLapTime; // no tracking of leader class best laptime
            float estimated = leader.EstimatedLapTime; // iRacing always has this

            if (estimated > 0 && currentGameState.SessionData.CompletedLaps < 2)
            {
                return estimated;
            }

            if (session_best > 0)
            {
                return session_best;
            }
            else if (best > 0)
            {
                return best;
            }
            else if (estimated > 0)
            {
                return estimated;
            }

            return -1;
        }


        /// <summary>
        /// Try to predict the the earliest possible time/lap and the latest possible time/lap we can come in for our pitstop and still make it to the end.
        /// we need to check if more then one stop is needed to finish the race in this case we dont care about pit window
        /// </summary>
        /// <returns>pit window earliest:latest tuple in laps or minutes</returns>
        private Tuple<int, int> getPredictedPitWindow(GameStateData currentGameState)
        {

            Tuple<int, int> pitWindow = new Tuple<int, int>(-1, -1);
            // tweak the fuelCapacity using the requested reserve. That is, the fuel capcity we use for these calcuations is the full
            // tank minus the reserve amount we've set in the Properties
            float averageUsagePerLapToUse = getConsumptionPerLap();
            float fuelCapacityAllowingForReserve;
            // we do all our reserve calculations in getAdditionalFuelToEndOfRace, no need to duplicate the logic
            fuelCapacityAllowingForReserve = fuelCapacity;
            {
                if (averageUsagePerLapToUse > 0)
                {
                    float litresNeeded = getAdditionalFuelToEndOfRace(true);
                    if (litresNeeded > 0)
                    {
                        // more then 1 stop needed
                        if (litresNeeded > fuelCapacityAllowingForReserve)
                        {
                            return pitWindow;
                        }
                        int maximumLapsForFullTankOfFuel = (int)Math.Floor(fuelCapacityAllowingForReserve / averageUsagePerLapToUse);
                        // pit window start is just the total race distance - maximumLapsForFullTankOfFuel. It's the earliest we can stop, fill the tank, and still finish
                        int pitWindowStart = sessionNumberOfLaps - maximumLapsForFullTankOfFuel;
                        // pit window end is just the lap on which we'll run out of fuel if we don't stop
                        int pitWindowEnd = currentGameState.SessionData.CompletedLaps + (int)Math.Floor(currentFuel / averageUsagePerLap);
                        Log.Fuel(() => "calculated fuel window (laps): pitwindowStart = " + pitWindowStart + " pitWindowEnd = " + pitWindowEnd +
                            " maximumLapsForFullTankOfFuel = " + maximumLapsForFullTankOfFuel);

                        // some sanity checks to ensure we're not calling nonsense window data. A negative window start is OK - this just means we're inside the
                        // window at the point where we're doing the calculation
                        if (pitWindowStart <= pitWindowEnd && pitWindowStart < sessionNumberOfLaps && pitWindowEnd > 0)
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
            Console.WriteLine("Getting fuel requirement keypress count");
            int litresToEnd = (int)Math.Ceiling(getAdditionalFuelToEndOfRace(true));

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

        private float getConsumptionPerLap()
        {
            return averageUsagePerLap;
        }

        private float getConsumptionPerMinute()
        {
            var our_lap_time = estimateFutureAverageLapTime(CrewChief.currentGameState);
            if (averageUsagePerLap <= 0 || our_lap_time <= 0)
            {
                return -1;
            }
            return 60.0f * averageUsagePerLap / our_lap_time;
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

        // instead of having two separate algorithms for fuel usage: one based on laps and another based on time,
        // the new algorithm estimates laps remaining in a fixed time race, then has a single codepath for the fuel
        // calculation.
        private void estimateLapsForFixedTimeRace(GameStateData currentGameState)
        {
            if (currentGameState.SessionData.SessionPhase >= SessionPhase.Finished || currentGameState.SessionData.SessionTimeRemaining <= 0)
            {
                Log.Fuel("session is finished");
                lapsRemaining = 0;
                LapsRemaining = 0;
                LapsUntilRefuel = 0;
                return;
            }

            bool leading = currentGameState.SessionData.OverallPosition == 1;

            // Here we turn the session fixed time into a lap estimate.
            var our_lap_time = estimateFutureAverageLapTime(currentGameState);
            float leader_lap_time = our_lap_time;
            if (!leading)
            {
                leader_lap_time = estimateFutureAverageLapTimeForLeader(currentGameState);
            }

            // when the telemetry connection is super flakey, these can sometimes get reset to -1
            // which is really bad. The real fix is in the game state mapper but these values are
            // too important so let's always just cache the last reasonable value.
            if (our_lap_time < 0)
            {
                our_lap_time = _our_lap_time;
            }
            else
            {
                _our_lap_time = our_lap_time;
            }
            if (leader_lap_time < 0)
            {
                leader_lap_time = _leader_lap_time;
            }
            else
            {
                _leader_lap_time = leader_lap_time;
            }

            if (our_lap_time < 0 || leader_lap_time < 0)
            {
                Log.Fuel(() => $"skipping lap estimation because our_lap_time={our_lap_time} leader_lap_time={leader_lap_time}");
            }
            else
            {
                // the algorithm to estimate how many laps remain requires:
                //
                // - how long for the leader to finish their current lap (i.e. position on track)
                // - the leader's average lap time
                // - how long will be spent in pit stops for the remainder of the race.
                //
                // plus the same for ourselves. We assume that the leader has not pitted and will be in the pits for the
                // shortest record time in our benchmarks, and only if we are the same class as them.
                //
                // We could allow the user to record additional benchmarks for other classes, but that starts to get
                // very complicated. The extra headroom means we sometimes predict a lap extra of fuel when we are the slower
                // class but that's the safest thing to do.
                //
                // Weather is taken into account only in the sense that the lap time estimates might take track
                // conditions into account, but we are often so scarce on estimates that it's not worth overthinking it.
                //
                // Using this information, we estimate when the leader will be shown the white flag. We will then get
                // the white flag at the end of that lap. However, if the leader overtakes us on that final lap, we
                // will have one less lap to do. We consider this a conservative built-in safety margin that we may
                // try to optimise in the future.
                //
                // If we are the leader, we can skip some of the logic.
                //
                // There is an edge case where the leader (who might be us) has not pitted yet, but a car behind them on
                // track is the expected race winner. This could (in very rare cases) lead us to estimate one more lap
                // than is necessary, but that's the safe thing to do. We could try estimating the race winner instead
                // of the current leader to workaround this in the general case.
                var length = currentGameState.SessionData.TrackDefinition.trackLength;
                var our_pct = currentGameState.PositionAndMotionData.DistanceRoundTrack / length;
                float leader_pct = our_pct;
                int leader_pitstops = currentGameState.PitData.NumPitStops;
                var leader_class = currentGameState.carClass;
                if (!leading)
                {
                    var leader = currentGameState.getOpponentAtOverallPosition(1);
                    leader_pct = leader.DistanceRoundTrack / length;
                    leader_class = leader.CarClass;
                }

                var sessionTimeRemaining = currentGameState.SessionData.SessionTimeRemaining;
                // we'd like to be able to estimate the leader's pit time and our pit time separately, and take conditions,
                // into account, but we're lucky to even have this. Not having the data results in a conservative overestimate
                // of laps remaining, which is what we want.
                if ((experimentalLapEstimatorMulticlass || leading || CarData.IsCarClassEqual(leader_class, currentGameState.carClass)) &&
                    Strategy.persistBenchmarks && !currentGameState.PitData.InPitlane &&
                    (leading || leader_pitstops <= currentGameState.PitData.NumPitStops))
                {
                    // it's possible the leader has not stopped, but we have, which means our "extra" estimate
                    // is much lower... but in that case the next step will skip the pit deduction, although
                    // our estimate of who will win is probably incorrect.
                    float extra = Math.Min(fuelCapacity, getAdditionalFuelToEndOfRace(false, verbose: false));
                    var benchmark = BenchmarkHelper.findPersistedBenchmarkForCombo(extra);
                    float timeloss = benchmark == null ? 0 : benchmark.timeLoss;
                    if (timeloss <= 0)
                    {
                        timeloss = Strategy.getExpectedPlayerTimeLossFallback(extra);
                        if (timeloss > 0)
                        {
                            Log.Fuel(() => $"guessing a pitstop will cost us {timeloss} seconds for {extra} litres");
                        }
                    }

                    // we should really check that the estimate is good enough for our purpose by checking the litres
                    // it uses, e.g. using a full tank endurance estimate in a sprint race is potentially going to
                    // result in one lap less estimated than it should be.
                    if (timeloss > 0 && extra > currentFuel * fuel_saving_coefficient)
                    {
                        int pitstops = (int)Math.Ceiling(extra / fuelCapacity);
                        float loss = timeloss * pitstops;
                        Log.Fuel(() => $"Deducting pitstop time loss of {loss} (for {extra} litres) for {pitstops} stop(s). They have stopped {leader_pitstops} times (we have stopped {currentGameState.PitData.NumPitStops} times).");
                        sessionTimeRemaining -= loss;
                    }
                }

                var time_left_for_leader_lap = leader_lap_time * (1.0 - leader_pct);

                // One might intuitively think that as soon as the session times out,
                // the next time the leader crosses the line is the end of the race but iRacing requires a white flag lap
                // and that can sometimes result in a lap more than you'd expect. The details are not made public
                // but seem to be based on whether the leader will finish the next lap under the time limit based on
                // their average (or best) lap time.
                //
                // https://www.reddit.com/r/iRacing/comments/pawpiy/how_is_white_flag_calculated_in_timed_events/
                //
                // We add some margin to account for that known case of crossing the line just before the timeout.
                var hackExtraLapTime = Game.IRACING ? 10f : 0f;
                var leader_laps_until_last = (sessionTimeRemaining + hackExtraLapTime - time_left_for_leader_lap) / leader_lap_time;
                var leader_full_laps_until_last = Math.Floor(leader_laps_until_last);

                if (leader_laps_until_last <= 0)
                {
                    if (leading || our_pct <= leader_pct)
                    {
                        // leading or on the same lap as the leader
                        lapsRemaining = 1;
                    }
                    else
                    {
                        // we are ahead of the leader on track, for now, but we
                        // might want to look into estimating if we'll be lapped
                        // by the end.
                        lapsRemaining = 2;
                    }
                }
                else if (leading)
                {
                    // well, that was easy! Add one for the current lap, then the final one.
                    lapsRemaining = (int)leader_full_laps_until_last + 2;

                    Log.Fuel(() => $"[LAP_ESTIMATE] remaining={sessionTimeRemaining}, leader_lap_time={leader_lap_time}, leader_pct={leader_pct}, time_left_for_leader_lap={time_left_for_leader_lap}, leader_full_laps_until_last={leader_full_laps_until_last}");
                }
                else
                {
                    // we work out how long it'll be until the leader starts their last lap...
                    var time_until_leader_last_lap = time_left_for_leader_lap + leader_full_laps_until_last * leader_lap_time;
                    // figure out how many laps we will do in that time
                    // (using the slowest lap of us and the leader, or we could overshoot)
                    var lap_time = Math.Max(our_lap_time, leader_lap_time);
                    var our_full_laps_until_last = Math.Floor(time_until_leader_last_lap / lap_time);
                    // now we know how many full laps remain, so we add this lap and the final lap
                    lapsRemaining = (int)our_full_laps_until_last + 2;

                    Log.Fuel(() => $"[LAP_ESTIMATE] remaining={sessionTimeRemaining}, our_lap_time={our_lap_time}, our_pct={our_pct}, leader_lap_time={leader_lap_time}, leader_pct={leader_pct}, time_left_for_leader_lap={time_left_for_leader_lap}, leader_full_laps_until_last={leader_full_laps_until_last}, time_until_leader_last_lap={time_until_leader_last_lap}, our_full_laps_until_last={our_full_laps_until_last}");
                }

                // never predict less than 1 lap (the current lap)
                lapsRemaining = Math.Max(lapsRemaining, 1);

                if (extraLapsAfterTimedSessionComplete > 0)
                {
                    lapsRemaining += extraLapsAfterTimedSessionComplete;
                }

                // if the telemetry says it's the last lap, believe it
                // but this is not available for all sims (e.g. raceroom)
                if (currentGameState.SessionData.IsLastLap)
                {
                    lapsRemaining = 1;
                }

                sessionNumberOfLaps = currentGameState.SessionData.CompletedLaps + lapsRemaining;
                halfDistance = (int)Math.Ceiling(sessionNumberOfLaps / 2f);

                Log.Commentary("Estimating " + lapsRemaining + " laps remaining (total " + sessionNumberOfLaps + ")");
                if (CrewChief.fuelMultiplier.active)
                {
                    var _ = getAdditionalFuelToEndOfRace(false); // to log out the fuel estimate

                    float perLap = getConsumptionPerLap();
                    LapsRemaining = perLap == 0 || lapsRemaining * perLap > currentFuel ? 0 : lapsRemaining;
                    LapsUntilRefuel = LapsRemaining > 0 ? 0 : (int)(currentFuel / perLap);
                }
                else
                {
                    LapsRemaining = lapsRemaining;
                    LapsUntilRefuel = Int32.MaxValue;
                }
            }
        }

        /// <summary>
        /// Return the probable number of remaining laps in a timed race
        /// 0 => more than we can manage without pitting
        /// </summary>
        public static int LapsRemaining { get; private set; }
        /// <summary>
        /// Return the probable number of remaining laps until we have to refuel
        /// 0 => We don't have to refuel
        /// </summary>
        public static int LapsUntilRefuel { get; private set; }

        /// <summary>
        /// The fuel we last added
        /// </summary>
        public static float FuelAddedInLastStop { get; private set; }

        // this is where we apply the fuel percentile values, saving it into the legacy "average" field
        private void updateAverageFuelUsage(GameStateData currentGameState)
        {
            if (historicAverageUsagePerLap.Count + persistedAverageUsagePerLap.Count > 0)
            {
                var all_data = new List<float>();
                all_data.AddRange(historicAverageUsagePerLap);
                all_data.AddRange(persistedAverageUsagePerLap);
                if (all_data.Count() == 1)
                {
                    averageUsagePerLap = all_data.First();
                    return;
                }

                all_data.Sort();

                float percentile = fuelPercentile;
                if (GlobalBehaviourSettings.useOvalLogic)
                {
                    percentile = fuelPercentileOval;
                }

                // risky / cautious strategies move the percentile a fixed amount.
                // this can move it to be less than the median! (intentional)
                if (reserveMultiplier < 1)
                {
                    percentile -= 25;
                }
                else if (reserveMultiplier > 1)
                {
                    percentile += 25;
                }

                percentile = Math.Max(0f, Math.Min(percentile, 100f));

                int size = all_data.Count();
                float gap = 100f / size;
                float found = all_data.Last();
                for (int i = 0; i < size; i++)
                {
                    if ((float)(i + 1) * gap > percentile)
                    {
                        // we could interpolate between the last and the current value
                        // here if we wanted to oblige the percentile more accurately.
                        // otherwise we always pick the value that falls just under the
                        // percentile (nearest without going over).
                        found = all_data[i];
                        break;
                    }
                }
                averageUsagePerLap = found;
            }
        }

        private void NotifyLFSFuel(float refuelNeeded = -1)
        {
            if (Game.LFS)
            {
                CrewChiefV4.LFS.LFSInSimReader.SendFuelStatus(currentFuel, getConsumptionPerLap(), lapsRemaining, refuelNeeded);
            }
        }
    }

    class FuelSample
    {
        public float litres { get; set; }
        public float lap_time { get; set; }
        public ConditionsMonitor.TrackWetness conditions { get; set; }
    }

    class PersistedFuel
    {
        public String game { get; set; }
        public String carName { get; set; }
        public String trackName { get; set; }
        public List<FuelSample> fuel { get; set; }

        public PersistedFuel()
        {
            fuel = new List<FuelSample>();
        }

        public Boolean isForThisCombo(String game, String carName, String trackName)
        {
            return this.game != null && this.game.Equals(game) &&
                this.carName != null && this.carName.Equals(carName) &&
                this.trackName != null && this.trackName.Equals(trackName);
        }
    }
}
