using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using CrewChiefV4.GameState;
using CrewChiefV4.Audio;
using CrewChiefV4.NumberProcessing;
using CrewChiefV4.ACC;

namespace CrewChiefV4.Events
{
    public class ConditionsMonitor : AbstractEvent
    {
        // allow condition messages during caution periods
        public override List<SessionPhase> applicableSessionPhases
        {
            get { return new List<SessionPhase> { SessionPhase.Green, SessionPhase.Checkered, SessionPhase.FullCourseYellow, SessionPhase.Formation, SessionPhase.Countdown, SessionPhase.Gridwalk }; }
        }

        // we have overrides for these in iRacing... inlined below
        private static float drizzleMin = 0.01f;
        private static float drizzleMax = 0.15f;
        private static float lightRainMax = 0.3f;
        private static float midRainMax = 0.6f;
        private static float heavyRainMax = 0.75f;

        public enum RainLevel
        {
            NONE, DRIZZLE, LIGHT, MID, HEAVY, STORM
        }

        public enum TrackStatus
        {
            GREEN, FAST, OPTIMUM, GREASY, DAMP, WET, FLOODED, UNKNOWN
        }
        public enum TrackWetness
        {
            UNKNOWN = 0,
            Dry,
            MostlyDry,
            VeryLightlyWet,
            LightlyWet,
            ModeratelyWet,
            VeryWet,
            ExtremelyWet
        };
        private readonly Boolean enableTrackAndAirTempReports = UserSettings.GetUserSettings().getBoolean("enable_track_and_air_temp_reports");
        private readonly Boolean enablePCarsRainPrediction = UserSettings.GetUserSettings().getBoolean("pcars_enable_rain_prediction");

        public static TimeSpan ConditionsSampleFrequency = TimeSpan.FromSeconds(10);
        private TimeSpan AirTemperatureReportMaxFrequency = TimeSpan.FromSeconds(UserSettings.GetUserSettings().getInt("ambient_temp_check_interval_seconds"));
        private TimeSpan TrackTemperatureReportMaxFrequency = TimeSpan.FromSeconds(UserSettings.GetUserSettings().getInt("track_temp_check_interval_seconds"));

        // don't report rain changes more that 2 minutes apart for RF2
        // ACC using the pCars2 value here, needs to be tested
        private TimeSpan RainReportMaxFrequencyRF2 = TimeSpan.FromSeconds(120);
        private TimeSpan RainReportMaxFrequencyPCars = TimeSpan.FromSeconds(10);

        private readonly float minTrackTempDeltaToReport = UserSettings.GetUserSettings().getFloat("report_ambient_temp_changes_greater_than");
        private readonly float minAirTempDeltaToReport = UserSettings.GetUserSettings().getFloat("report_track_temp_changes_greater_than");

        private DateTime lastAirTempReport;
        private DateTime lastTrackTempReport;
        private DateTime lastRainReport;

        private float airTempAtLastReport;
        private float trackTempAtLastReport;
        private float rainAtLastReport;

        public static String folderAirAndTrackTempIncreasing = "conditions/air_and_track_temp_increasing";
        public static String folderAirAndTrackTempDecreasing = "conditions/air_and_track_temp_decreasing";
        public static String folderTrackTempIsNow = "conditions/track_temp_is_now";
        public static String folderAirTempIsNow = "conditions/air_temp_is_now"; 
        public static String folderTrackTempIs = "conditions/track_temp_is";
        public static String folderAirTempIs = "conditions/air_temp_is";
        public static String folderAirTempIncreasing = "conditions/air_temp_increasing_its_now";
        public static String folderAirTempDecreasing = "conditions/air_temp_decreasing_its_now";
        public static String folderTrackTempIncreasing = "conditions/track_temp_increasing_its_now";
        public static String folderTrackTempDecreasing = "conditions/track_temp_decreasing_its_now";
        public static String folderCelsius = "conditions/celsius";
        public static String folderFahrenheit = "conditions/fahrenheit";

        // this is for PCars, where the 'rain' flag is boolean
        public static String folderSeeingSomeRain = "conditions/seeing_some_rain";
        // this is for PCars2, where we try to interpret a drop in CloudDensity value to mean "rain approaching"
        public static String folderExpectRain = "conditions/we_expect_rain_in_the_next";
        
        // these are for RF2 where the rain varies from 0 (dry), 0.5 (rain) to 1.0 (storm).
        public static String folderDrizzleIncreasing = "conditions/drizzle_increasing";
        public static String folderRainLightIncreasing = "conditions/light_rain_increasing";
        public static String folderRainMidIncreasing = "conditions/mid_rain_increasing";
        public static String folderRainHeavyIncreasing = "conditions/heavy_rain_increasing";
        public static String folderRainMax = "conditions/maximum_rain"; // "completely pissing it down"
        public static String folderRainHeavyDecreasing = "conditions/heavy_rain_decreasing";
        public static String folderRainMidDecreasing = "conditions/mid_rain_decreasing";
        public static String folderRainLightDecreasing = "conditions/light_rain_decreasing";
        public static String folderDrizzleDecreasing = "conditions/drizzle_decreasing";

        // this is used for RF2 and PCars
        public static String folderStoppedRaining = "conditions/stopped_raining";

        // ACC, RF2 and LMU forecast messages
        private static string folderExpectNoRain = "conditions/we_expect_rain_to_stop_in_the_next";
        private string folderExpectDrizzle = "conditions/we_expect_drizzle_in_the_next";
        private string folderExpectLightRain = "conditions/we_expect_light_rain_in_the_next";
        private string folderExpectMediumRain = "conditions/we_expect_medium_rain_in_the_next";
        private string folderExpectHeavyRain = "conditions/we_expect_heavy_rain_in_the_next";
        private string folderExpectVeryHeavyRain = "conditions/we_expect_very_heavy_rain_in_the_next";

        private Conditions.ConditionsSample currentConditions;
        private Conditions.ConditionsSample conditionsAtStartOfThisLap;

        private float rainDensityAtLastCheck = -1;

        // PCars2 only
        private DateTime timeWhenCloudIncreased = DateTime.MinValue;
        private DateTime timeWhenRainExpected = DateTime.MinValue;
        private Boolean waitingForRainEstimate = false;

        // units here are 'rain quantity per second', where rain quantity is 0 -> 1, direct from the pcars2 or rf2 game data.
        // The number is always positive (it's the absolute change)
        private static float maxRainChangeRate = -1;

        // ACC, RF2 and LMU
        private RainLevel rainLevelFor10MinuteForecast = RainLevel.NONE;
        private RainLevel rainLevelFor30MinuteForecast = RainLevel.NONE;
        private DateTime next10MinuteForecastReportDue = DateTime.MinValue;
        private DateTime next30MinuteForecastReportDue = DateTime.MinValue;
        private TimeSpan forecastCheck10MinInterval = TimeSpan.FromSeconds(30); // check for changes in the 10 minute forecast this often
        private TimeSpan forecastCheck30MinInterval = TimeSpan.FromSeconds(180); // check for changes in the 30 minute forecast this often

        public ConditionsMonitor(AudioPlayer audioPlayer)
        {
            this.audioPlayer = audioPlayer;
        }

        public override void clearState()
        {
            lastRainReport = DateTime.MinValue;
            lastAirTempReport = DateTime.MaxValue;
            lastTrackTempReport = DateTime.MaxValue;
            airTempAtLastReport = float.MinValue;
            trackTempAtLastReport = float.MinValue;
            rainAtLastReport = float.MinValue;
            currentConditions = null;
            conditionsAtStartOfThisLap = null;
            timeWhenCloudIncreased = DateTime.MinValue;
            timeWhenRainExpected = DateTime.MinValue;
            waitingForRainEstimate = false;
            rainDensityAtLastCheck = -1;
            maxRainChangeRate = -1;
            rainLevelFor10MinuteForecast = RainLevel.NONE;
            rainLevelFor30MinuteForecast = RainLevel.NONE;
            next10MinuteForecastReportDue = DateTime.MinValue;
            next30MinuteForecastReportDue = DateTime.MinValue;
        }

        private string getForecastFolder(RainLevel currentRainLevel, RainLevel forecastRainLevel, RainLevel rainLevelAtLastForecastCall)
        {
            if (forecastRainLevel != currentRainLevel && forecastRainLevel != rainLevelAtLastForecastCall)
            {
                switch (forecastRainLevel)
                {
                    case RainLevel.NONE:
                        return folderExpectNoRain;
                    case RainLevel.DRIZZLE:
                        return folderExpectDrizzle;
                    case RainLevel.LIGHT:
                        return folderExpectLightRain;
                    case RainLevel.MID:
                        return folderExpectMediumRain;
                    case RainLevel.HEAVY:
                        return folderExpectHeavyRain;
                    case RainLevel.STORM:
                        return folderExpectVeryHeavyRain;
                }
            }
            return null;
        }
        public string getRainForPreStartMessage(GameStateData currentGameState)
        {
            currentConditions = currentGameState.Conditions.getMostRecentConditions();
            float trackTempToUse = Game.PCARS_AMS2 && conditionsAtStartOfThisLap != null ? conditionsAtStartOfThisLap.TrackTemperature : currentConditions.TrackTemperature;
            if (airTempAtLastReport == float.MinValue)
            {
                airTempAtLastReport = currentConditions.AmbientTemperature;
                trackTempAtLastReport = trackTempToUse;
                rainAtLastReport = currentConditions.RainDensity;
                lastRainReport = currentGameState.Now;
                lastTrackTempReport = currentGameState.Now;
                lastAirTempReport = currentGameState.Now;
            }
            switch (getRainLevel(currentConditions.RainDensity))
            {
                case RainLevel.NONE:
                    return null;
                case RainLevel.DRIZZLE:
                case RainLevel.LIGHT:
                case RainLevel.MID:
                case RainLevel.HEAVY:
                case RainLevel.STORM:
                    return folderSeeingSomeRain;                  
            }
            return null;
        }
        override protected void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            currentConditions = currentGameState.Conditions.getMostRecentConditions();
            // ACC specific - if we didn't have conditions to announce at the session start, announce them now
            if (Game.ACC
                && currentConditions != null
                && (currentGameState.SessionData.SessionPhase == SessionPhase.Formation || currentGameState.SessionData.SessionPhase == SessionPhase.Countdown)
                && !LapCounter.preStartTempsAnnounced)
            {
                audioPlayer.playMessage(new QueuedMessage("trackAndAirTemp", 15, messageFragments: MessageContents(
                    ConditionsMonitor.folderTrackTempIs,
                    convertTemp(currentConditions.TrackTemperature),
                    ConditionsMonitor.folderAirTempIs,
                    convertTemp(currentConditions.AmbientTemperature),
                    getTempUnit()),
                    abstractEvent: this, priority: 10, secondsDelay: 10));
                LapCounter.preStartTempsAnnounced = true;
            }
            if (currentGameState.SessionData.IsNewLap)
            {
                conditionsAtStartOfThisLap = currentConditions;
            }
            // the above is the only pre-start trigger that's valid for this event so don't allow any of the other gubbins to trigger in formation or countdown:
            if (currentGameState.SessionData.SessionPhase < SessionPhase.Green ||
                currentGameState.SessionData.SessionPhase >= SessionPhase.Checkered ||
                currentGameState.SessionData.IsLastLap)
            {
                return;
            }
            if (Game.HAS_WEATHER_FORECAST)
            {
                if (currentGameState.SessionData.JustGoneGreen)
                {
                    next10MinuteForecastReportDue = currentGameState.Now.AddMinutes(1);
                    next30MinuteForecastReportDue = currentGameState.Now.AddMinutes(2);
                }
                if (currentGameState.Now > next10MinuteForecastReportDue)
                {
                    string forecastFolder = getForecastFolder(currentGameState.Conditions.rainLevelNow, currentGameState.Conditions.rainLevelIn10Mins, this.rainLevelFor10MinuteForecast);
                    if (forecastFolder != null)
                    {
                        float minutes = 10f;
                        if (Game.ACC && ACCGameStateMapper.clockMultiplierGuess > 1)
                        {
                            minutes = minutes / ACCGameStateMapper.clockMultiplierGuess;
                        }
                        if ((int)Math.Ceiling(minutes) > 0)
                        {
                            audioPlayer.playMessage(new QueuedMessage("acc_10_min_forecast", 10, messageFragments: MessageContents(forecastFolder,
                                            new TimeSpanWrapper(TimeSpan.FromMinutes((int)Math.Ceiling(minutes)), Precision.MINUTES)), abstractEvent: this));
                        }
                    }
                    this.rainLevelFor10MinuteForecast = currentGameState.Conditions.rainLevelIn10Mins;
                    next10MinuteForecastReportDue = currentGameState.Now.Add(forecastCheck10MinInterval);
                }
                if (currentGameState.Now > next30MinuteForecastReportDue)
                {
                    string forecastFolder = getForecastFolder(currentGameState.Conditions.rainLevelNow, currentGameState.Conditions.rainLevelIn30Mins, this.rainLevelFor30MinuteForecast);
                    if (forecastFolder != null)
                    {
                        float minutes = 30f;
                        if (Game.ACC && ACCGameStateMapper.clockMultiplierGuess > 1)
                        {
                            minutes = minutes / ACCGameStateMapper.clockMultiplierGuess;
                        }
                        if ((int)Math.Ceiling(minutes) > 0)
                        {
                            audioPlayer.playMessage(new QueuedMessage("acc_30_min_forecast", 10, messageFragments: MessageContents(forecastFolder,
                                            new TimeSpanWrapper(TimeSpan.FromMinutes((int)Math.Ceiling(minutes)), Precision.MINUTES)), abstractEvent: this));
                        }
                    }
                    this.rainLevelFor30MinuteForecast = currentGameState.Conditions.rainLevelIn30Mins;
                    next30MinuteForecastReportDue = currentGameState.Now.Add(forecastCheck30MinInterval);                    
                }
            }
            if (currentConditions != null) 
            {
                // for pcars track temp, we're only interested in changes at the start line (a single point on the track) because the track
                // temp is localised. The air temp is (probably) localised too, but will be less variable
                float trackTempToUse = Game.PCARS_AMS2 && conditionsAtStartOfThisLap != null ? conditionsAtStartOfThisLap.TrackTemperature : currentConditions.TrackTemperature;
                if (airTempAtLastReport == float.MinValue)
                {
                    airTempAtLastReport = currentConditions.AmbientTemperature;
                    trackTempAtLastReport = trackTempToUse;
                    rainAtLastReport = currentConditions.RainDensity;
                    lastRainReport = currentGameState.Now;
                    lastTrackTempReport = currentGameState.Now;
                    lastAirTempReport = currentGameState.Now;
                }
                else
                {
                    Boolean canReportAirChange = enableTrackAndAirTempReports &&
                        currentGameState.Now > lastAirTempReport.Add(AirTemperatureReportMaxFrequency);
                    Boolean canReportTrackChange = enableTrackAndAirTempReports &&
                        currentGameState.Now > lastTrackTempReport.Add(TrackTemperatureReportMaxFrequency);
                    Boolean reportedCombinedTemps = false;
                    TimeSpan rainReportFrequency = (Game.RF2_LMU || Game.GTR2 || Game.IRACING) ? RainReportMaxFrequencyRF2 : RainReportMaxFrequencyPCars;
                    if (canReportAirChange || canReportTrackChange)
                    {
                        if (trackTempToUse > trackTempAtLastReport + minTrackTempDeltaToReport && currentConditions.AmbientTemperature > airTempAtLastReport + minAirTempDeltaToReport)
                        {
                            airTempAtLastReport = currentConditions.AmbientTemperature;
                            trackTempAtLastReport = trackTempToUse;
                            lastAirTempReport = currentGameState.Now;
                            lastTrackTempReport = currentGameState.Now;
                            // do the reporting
                            audioPlayer.playMessage(new QueuedMessage("airAndTrackTemp", 10, messageFragments: MessageContents
                                (folderAirAndTrackTempIncreasing, folderAirTempIsNow, convertTemp(currentConditions.AmbientTemperature),
                                folderTrackTempIsNow, convertTemp(trackTempToUse), getTempUnit()), abstractEvent: this, priority: 0));
                            reportedCombinedTemps = true;
                        }
                        else if (trackTempToUse < trackTempAtLastReport - minTrackTempDeltaToReport && currentConditions.AmbientTemperature < airTempAtLastReport - minAirTempDeltaToReport)
                        {
                            airTempAtLastReport = currentConditions.AmbientTemperature;
                            trackTempAtLastReport = trackTempToUse;
                            lastAirTempReport = currentGameState.Now;
                            lastTrackTempReport = currentGameState.Now;
                            // do the reporting
                            audioPlayer.playMessage(new QueuedMessage("airAndTrackTemp", 10, messageFragments: MessageContents
                                (folderAirAndTrackTempDecreasing, folderAirTempIsNow, convertTemp(currentConditions.AmbientTemperature),
                                folderTrackTempIsNow, convertTemp(trackTempToUse), getTempUnit()), abstractEvent: this, priority: 0));
                            reportedCombinedTemps = true;
                        }
                    }
                    if (!reportedCombinedTemps && canReportAirChange)
                    {
                        if (currentConditions.AmbientTemperature > airTempAtLastReport + minAirTempDeltaToReport)
                        {
                            airTempAtLastReport = currentConditions.AmbientTemperature;
                            lastAirTempReport = currentGameState.Now;
                            // do the reporting
                            audioPlayer.playMessage(new QueuedMessage("airTemp", 10, messageFragments: MessageContents
                                (folderAirTempIncreasing, convertTemp(currentConditions.AmbientTemperature), getTempUnit()), abstractEvent: this, priority: 0));
                        }
                        else if (currentConditions.AmbientTemperature < airTempAtLastReport - minAirTempDeltaToReport)
                        {
                            airTempAtLastReport = currentConditions.AmbientTemperature;
                            lastAirTempReport = currentGameState.Now;
                            // do the reporting
                            audioPlayer.playMessage(new QueuedMessage("airTemp", 10, messageFragments: MessageContents
                                (folderAirTempDecreasing, convertTemp(currentConditions.AmbientTemperature), getTempUnit()), abstractEvent: this, priority: 0));
                        }
                    }
                    if (!reportedCombinedTemps && canReportTrackChange)
                    {
                        if (trackTempToUse > trackTempAtLastReport + minTrackTempDeltaToReport)
                        {
                            trackTempAtLastReport = trackTempToUse;
                            lastTrackTempReport = currentGameState.Now;
                            // do the reporting
                            audioPlayer.playMessage(new QueuedMessage("trackTemp", 10, messageFragments: MessageContents
                                (folderTrackTempIncreasing, convertTemp(trackTempToUse), getTempUnit()), abstractEvent: this, priority: 0));
                        }
                        else if (trackTempToUse < trackTempAtLastReport - minTrackTempDeltaToReport)
                        {
                            trackTempAtLastReport = trackTempToUse;
                            lastTrackTempReport = currentGameState.Now;
                            // do the reporting
                            audioPlayer.playMessage(new QueuedMessage("trackTemp", 10, messageFragments: MessageContents
                                (folderTrackTempDecreasing, convertTemp(trackTempToUse), getTempUnit()), abstractEvent: this, priority: 0));
                        }
                    }
                    //pcars2 test warning
                    if (enablePCarsRainPrediction && Game.PCARS_AMS2)
                    {
                        if (previousGameState != null && currentGameState.SessionData.SessionRunningTime > 10)
                        {
                            if (currentGameState.RainDensity == 0)
                            {
                                // not raining so see if we can guess when it might start
                                if (!waitingForRainEstimate)
                                {
                                    if (previousGameState.CloudBrightness == 2 && currentGameState.CloudBrightness < 2)
                                    {
                                        timeWhenCloudIncreased = previousGameState.Now;
                                        waitingForRainEstimate = true;
                                    }
                                }
                                else if (currentGameState.CloudBrightness < 1.98)
                                {
                                    // big enough change to calculate expected rain time
                                    TimeSpan timeDelta = currentGameState.Now - timeWhenCloudIncreased;
                                    // assume rain just after it hits 1.9
                                    float millisTillRain = (float)timeDelta.TotalMilliseconds * 6f;
                                    // this is usually really inaccurate and can go either way
                                    timeWhenRainExpected = timeWhenCloudIncreased.AddMilliseconds(millisTillRain);
                                    waitingForRainEstimate = false;
                                    timeWhenCloudIncreased = DateTime.MinValue;
                                    DateTime when = currentGameState.Now.AddMilliseconds(millisTillRain);
                                    Console.WriteLine("It is now " + currentGameState.Now + ", we expect rain at game time " + when);
                                    int minutes = (int)Math.Round(millisTillRain / 60000);

                                    if (minutes > 2)
                                    {
                                        audioPlayer.playMessage(new QueuedMessage("expecting_rain", 10, messageFragments: MessageContents(folderExpectRain,
                                            new TimeSpanWrapper(TimeSpan.FromMinutes(minutes), Precision.MINUTES)), abstractEvent: this));
                                    }
                                }
                            }
                            else
                            {
                                // cancel waiting for rain
                                waitingForRainEstimate = false;
                                timeWhenCloudIncreased = DateTime.MinValue;
                            }
                        }
                    }
                    if (currentGameState.Now > lastRainReport.Add(rainReportFrequency))
                    {
                        // for PCars mRainDensity value is 0 or 1
                        if (Game.PCARS1)
                        {
                            if (currentGameState.RainDensity == 0 && rainAtLastReport == 1)
                            {
                                rainAtLastReport = currentGameState.RainDensity;
                                lastRainReport = currentGameState.Now;
                                audioPlayer.playMessage(new QueuedMessage(folderStoppedRaining, 10, abstractEvent: this, priority: 2));
                            }
                            else if (currentConditions.RainDensity == 1 && rainAtLastReport == 0)
                            {
                                rainAtLastReport = currentGameState.RainDensity;
                                lastRainReport = currentGameState.Now;
                                audioPlayer.playMessage(new QueuedMessage(folderSeeingSomeRain, 10, abstractEvent: this, priority: 5));
                            }
                        }
                        else if (Game.RF2_LMU
                            || Game.GTR2
                            || Game.PCARS2
                            || Game.ACC
                            || Game.AMS2
                            || Game.PCARS3
                            || Game.IRACING)
                        {
                            if (rainDensityAtLastCheck != -1 && rainDensityAtLastCheck != currentConditions.RainDensity)
                            {
                                float rainChangeRate = (float) (Math.Abs(rainDensityAtLastCheck - currentConditions.RainDensity) / rainReportFrequency.TotalSeconds);
                                if (rainChangeRate > ConditionsMonitor.maxRainChangeRate)
                                {
                                    ConditionsMonitor.maxRainChangeRate = rainChangeRate;
                                }
                            }
                            rainDensityAtLastCheck = currentConditions.RainDensity;
                            RainLevel currentRainLevel = getRainLevel(currentConditions.RainDensity);
                            RainLevel lastReportedRainLevel = getRainLevel(rainAtLastReport);                            
                            if (currentRainLevel != lastReportedRainLevel)
                            {
                                Boolean increasing = currentConditions.RainDensity > rainAtLastReport;
                                switch (currentRainLevel)
                                {
                                    case RainLevel.DRIZZLE:
                                        audioPlayer.playMessageImmediately(new QueuedMessage(increasing ? folderDrizzleIncreasing : folderDrizzleDecreasing, 0, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                                        break;
                                    case RainLevel.LIGHT:
                                        audioPlayer.playMessageImmediately(new QueuedMessage(increasing ? folderRainLightIncreasing : folderRainLightDecreasing, 0, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                                        break;
                                    case RainLevel.MID:
                                        audioPlayer.playMessageImmediately(new QueuedMessage(increasing ? folderRainMidIncreasing : folderRainMidDecreasing, 0, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                                        break;
                                    case RainLevel.HEAVY:
                                        audioPlayer.playMessageImmediately(new QueuedMessage(increasing ? folderRainHeavyIncreasing : folderRainHeavyDecreasing, 0, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                                        break;
                                    case RainLevel.STORM:
                                        audioPlayer.playMessageImmediately(new QueuedMessage(folderRainMax, 0, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                                        break;
                                    case RainLevel.NONE:
                                        audioPlayer.playMessage(new QueuedMessage(folderStoppedRaining, 10, abstractEvent: this, priority: 3));
                                        break;
                                }
                                lastRainReport = currentGameState.Now;
                                rainAtLastReport = currentConditions.RainDensity;
                            }
                        }
                    }
                }
            }
        }

        public static RainLevel getRainLevel(float amount)
        {
            if (Game.IRACING)
            {
                return getRainLevel_iRacing(amount);
            }
            if (amount > drizzleMin && amount <= drizzleMax)
            {
                return RainLevel.DRIZZLE;
            }
            else if (amount > drizzleMax && amount <= lightRainMax)
            {
                return RainLevel.LIGHT;
            }
            else if (amount > lightRainMax && amount <= midRainMax)
            {
                return RainLevel.MID;
            }
            else if (amount > midRainMax && amount <= heavyRainMax)
            {
                return RainLevel.HEAVY;
            }
            else if (amount > heavyRainMax)
            {
                return RainLevel.STORM;
            }
            else
            {
                return RainLevel.NONE;
            }
        }

        // measured from a practice session with known levels of rain
        // https://forums.iracing.com/discussion/71002/precipitation-mappings
        //
        // "spotty" is random
        // "light rain" peaks at roughly 0.25
        // "rain" is roughly 0.4
        // "heavy rain" peaks out at about 0.78
        //
        // This only has an aestetic impact on the car, but it can change the
        // TrackWetness enum, which is what actually impacts car control.
        public static RainLevel getRainLevel_iRacing(float amount)
        {
            if (amount < 0.001) { return RainLevel.NONE; }
            if (amount < 0.10) { return RainLevel.DRIZZLE; }
            if (amount < 0.25) { return RainLevel.LIGHT; }
            if (amount < 0.50) { return RainLevel.MID; }
            if (amount < 0.75) { return RainLevel.HEAVY; }
            return RainLevel.STORM;
        }

        public static TimeSpan getTrackConditionsChangeDelay()
        {
            // maxRainChangeRate is in rain-points-per-second, so *60 gives us rain-points-per-minute.
            if (ConditionsMonitor.maxRainChangeRate == -1)
            {
                return TimeSpan.FromMinutes(2); // complete guesswork - this applies to pcars1 rain changes, and any other changes that
                                                // don't involve rain (i.e. the delay between ambient temp changes and track condition changes)
            }
            // numbers i pulled out of my botty.
            return TimeSpan.FromMinutes(0.3 / (ConditionsMonitor.maxRainChangeRate * 60));
        }

        private static readonly List<SpeechCommands.ID> Commands = new List<SpeechCommands.ID>
        {
            SpeechCommands.ID.WHATS_THE_AIR_TEMP,
            SpeechCommands.ID.WHATS_THE_TRACK_TEMP,
            SpeechCommands.ID.WHATS_MY_BRAKE_BIAS, // super weird to have it here, I know, but where else?
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
            if (currentConditions == null)
            {
                audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                Log.Commentary($"No data for {this.GetType().Name}");
            }
            else
            {
                switch (cmd)
                {
                    case SpeechCommands.ID.WHATS_THE_AIR_TEMP:
                        audioPlayer.playMessageImmediately(new QueuedMessage("airTemp", 0,
                            messageFragments: MessageContents(folderAirTempIsNow, convertTemp(currentConditions.AmbientTemperature), getTempUnit())));
                        break;
                    case SpeechCommands.ID.WHATS_THE_TRACK_TEMP:
                    {
                        var message = MessageContents(folderTrackTempIsNow, convertTemp(currentConditions.TrackTemperature), getTempUnit());
                        audioPlayer.playMessageImmediately(new QueuedMessage("trackTemp", 0,
                            messageFragments: message));
                        break;
                    }
                    case SpeechCommands.ID.WHATS_MY_BRAKE_BIAS:
                    {
                            var cgs = CrewChief.currentGameState;
                            if (cgs == null || cgs.ControlData.BrakeBias <= 0f)
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                                return;
                            }
                            var message = new List<MessageFragment>();
                            message.AddRange(Utilities.WholeAndFractionalMessage(cgs.ControlData.BrakeBias));
                            message.AddRange(MessageContents(Battery.folderPercent));
                            audioPlayer.playMessageImmediately(new QueuedMessage("brake_bias", 0, messageFragments: message));
                            break;
                    }
                }
            }
        }
    }
}
