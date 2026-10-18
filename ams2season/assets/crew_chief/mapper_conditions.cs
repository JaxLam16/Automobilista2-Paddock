using System;
namespace CrewChiefV4.Events { public class ConditionsMonitor {
        private static float drizzleMin = 0.01f;
        private static float drizzleMax = 0.15f;
        private static float lightRainMax = 0.3f;
        private static float midRainMax = 0.6f;
        private static float heavyRainMax = 0.75f;
        private static float maxRainChangeRate = -1;
        public static TimeSpan ConditionsSampleFrequency = TimeSpan.FromSeconds(10);
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
} }
