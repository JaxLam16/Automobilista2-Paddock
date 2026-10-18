using System;
using System.Collections.Generic;
using System.Linq;
using CrewChiefV4.GameState;
using CrewChiefV4.Audio;
using CrewChiefV4.NumberProcessing;
using CrewChiefV4.R3E;
using System.IO;
using Newtonsoft.Json;

namespace CrewChiefV4.Events
{
    class Timings : AbstractEvent
    {
        // R3E reputation thresholds, to be refined

        // we will never report a gap (unless requested) that is smaller than
        // this because the spotter should be telling us all about it
        private static readonly float minGapToReport = 0.05f;

        public const String folderGapInFrontIncreasing = "timings/gap_in_front_increasing";
        public const String folderGapInFrontDecreasing = "timings/gap_in_front_decreasing";
        private const String folderGapInFrontIsNow = "timings/gap_in_front_is_now";

        private const String folderHeIsSlowerThroughCorner = "timings/he_is_slower_through_corner";
        private const String folderHeIsFasterThroughCorner = "timings/he_is_faster_through_corner";
        private const String folderHeIsSlowerEnteringCorner = "timings/he_is_slower_entering_corner";
        private const String folderHeIsFasterEnteringCorner = "timings/he_is_faster_entering_corner";

        public const String folderGapBehindIncreasing = "timings/gap_behind_increasing";
        public const String folderGapBehindDecreasing = "timings/gap_behind_decreasing";
        private const String folderGapBehindIsNow = "timings/gap_behind_is_now";

        // for when we have a driver name...
        public const String folderTheGapTo = "timings/the_gap_to";   // "the gap to..."
        public const String folderAheadIsIncreasing = "timings/ahead_is_increasing"; // [bob] "ahead is increasing, it's now..."
        private const String folderBehindIsIncreasing = "timings/behind_is_increasing"; // [bob] "behind is increasing, it's now..."

        private const String folderAheadIsNow = "timings/ahead_is_now"; // [bob] "ahead is increasing, it's now..."
        private const String folderBehindIsNow = "timings/behind_is_now"; // [bob] "behind is increasing, it's now..."

        private const String folderYoureReeling = "timings/youre_reeling";    // "you're reeling..."
        private const String folderInTheGapIsNow = "timings/in_the_gap_is_now";  // [bob] "in, the gap is now..."

        private const String folderIsReelingYouIn = "timings/is_reeling_you_in";    // [bob] "is reeling you in, the gap is now...."

        private const String folderCarBehindLappingUs = "timings/car_behind_is_lapping_us";
        private const String folderCarBehindUnlapping = "timings/car_behind_is_unlapping_itself";

        private readonly String folderBeingHeldUp = "timings/being_held_up";
        private String folderBeingPressured = "timings/being_pressured";

        // R3E online only messages for cases where an opponent has a poor reputation

        private readonly int gapAheadReportFrequency = UserSettings.GetUserSettings().getInt("frequency_of_gap_ahead_reports");
        private readonly int gapBehindReportFrequency = UserSettings.GetUserSettings().getInt("frequency_of_gap_behind_reports");
        private readonly int gapBehindOnTrackReportFrequency = UserSettings.GetUserSettings().getInt("frequency_of_gap_behind_on_track_reports");


        private Dictionary<String, DateTime> lastLappingWarning = new Dictionary<String, DateTime>();

        // if true, don't give as many gap reports at the start/finish - stops the lap start getting too crowded with messages
        private Boolean preferGapReportsMidLap = true;

        private class Gap
        {
            // signing takes the same convention as the DeltaTime whereby
            // negatives are ahead and positives are behind.
            public readonly float signedTimeDelta;
            public readonly int signedLapDelta;

            public readonly String opponentKey;

            // backwards compat, context of the kind of gap is used in places allowing for unsigned comparisons
            public readonly float timeDelta;
            public readonly float lapDelta;

            public Gap(float signedTimeDelta, int signedLapDelta, String opponentKey)
            {
                this.signedTimeDelta = signedTimeDelta;
                this.signedLapDelta = signedLapDelta;
                this.opponentKey = opponentKey;
                this.timeDelta = Math.Abs(signedTimeDelta);
                this.lapDelta = Math.Abs(signedLapDelta);
            }
        }

        private List<Gap> gapsInFront;
        private List<Gap> gapsBehind;
        private List<Gap> gapsBehindOnTrack;

        private volatile float gapInFrontAtLastReport;
        private volatile int sectorsSinceLastGapAheadReport;
        private volatile int sectorsUntilNextGapAheadReport;

        private volatile float gapBehindAtLastReport;
        private volatile int sectorsSinceLastGapBehindReport;
        private volatile int sectorsUntilNextGapBehindReport;

        private volatile float gapBehindOnTrackAtLastReport;
        private volatile int sectorsSinceLastGapBehindOnTrackReport;
        private volatile int sectorsUntilNextGapBehindOnTrackReport;

        private readonly Boolean enableGapMessages = UserSettings.GetUserSettings().getBoolean("enable_gap_messages");
        private readonly int gapMessageRandomness = UserSettings.GetUserSettings().getInt("gap_message_randomness");

        private int gapAheadMinSectorWait;
        private int gapAheadMaxSectorWait;
        private int gapBehindMinSectorWait;
        private int gapBehindMaxSectorWait;
        private int gapBehindOnTrackMinSectorWait;
        private int gapBehindOnTrackMaxSectorWait;

        // don't play the same warning for the same guy more than once
        private Dictionary<String, DateTime> trackLandmarkAttackDriverNamesUsed = new Dictionary<String, DateTime>();
        private Dictionary<String, DateTime> trackLandmarkDefendDriverNamesUsed = new Dictionary<String, DateTime>();

        // don't repeat a message about where to attack or defend from the same opponent within 3 minutes - 
        // really important that these messages don't 'spam'
        private TimeSpan minTimeBetweenAttackOrDefendByDriver = TimeSpan.FromMinutes(3);

        private class DriverAtTime
        {
            public readonly DateTime started;
            public readonly String driver;
            public DriverAtTime(DateTime started, String driver)
            {
                this.started = started;
                this.driver = driver;
            }
        }
        private volatile DriverAtTime holdingUsUp = null;
        private volatile string lappingUs = null; // or unlapping themselves


        private enum GapStatus
        {
            CLOSE, INCREASING, DECREASING, OTHER, NONE
        }

        private class gapToOpponent
        {
            internal GapStatus? status;
            internal Gap gap;
            internal OpponentData opponent;

            internal gapToOpponent(Gap gap = null, OpponentData opponent = null, GapStatus? gapStatus = GapStatus.NONE)
            {
                status = gapStatus;
                this.gap = gap;
                this.opponent = opponent;
            }
        }

        class Gaps
        {
            internal gapToOpponent inFront;
            internal gapToOpponent behind;
            internal gapToOpponent behindOnTrack;

            internal Gaps()
            {
                inFront = new gapToOpponent();
                behind = new gapToOpponent();
                behindOnTrack = new gapToOpponent();
            }
        }

        public Timings(AudioPlayer audioPlayer)
        {
            this.audioPlayer = audioPlayer;

            var r = Math.Min(Math.Max(1, gapMessageRandomness), 10);

            gapAheadMinSectorWait = 11 - Math.Min(Math.Max(1, gapAheadReportFrequency), 10);
            gapAheadMaxSectorWait = gapAheadMinSectorWait + r;

            gapBehindMinSectorWait = 11 - Math.Min(Math.Max(1, gapBehindReportFrequency), 10);
            gapBehindMaxSectorWait = gapBehindMinSectorWait + r;

            gapBehindOnTrackMinSectorWait = 11 - Math.Min(Math.Max(1, gapBehindOnTrackReportFrequency), 10);
            gapBehindOnTrackMaxSectorWait = gapBehindOnTrackMinSectorWait + r;
        }

        public override void clearState()
        {
            gapsInFront = new List<Gap>();
            gapsBehind = new List<Gap>();
            gapsBehindOnTrack = new List<Gap>();

            gapInFrontAtLastReport = -1;
            gapBehindAtLastReport = -1;
            gapBehindOnTrackAtLastReport = -1;

            sectorsSinceLastGapAheadReport = 0;
            sectorsSinceLastGapBehindReport = 0;
            sectorsSinceLastGapBehindOnTrackReport = 0;

            if (gapAheadReportFrequency == 0)
            {
                sectorsUntilNextGapAheadReport = int.MaxValue;
            }
            else
            {
                sectorsUntilNextGapAheadReport = gapAheadMinSectorWait;
            }

            if (gapBehindReportFrequency == 0)
            {
                sectorsUntilNextGapBehindReport = int.MaxValue;
            }
            else
            {
                sectorsUntilNextGapBehindReport = gapBehindMinSectorWait;
            }

            if (gapBehindOnTrackReportFrequency == 0)
            {
                sectorsUntilNextGapBehindOnTrackReport = int.MaxValue;
            }
            else
            {
                sectorsUntilNextGapBehindOnTrackReport = gapBehindOnTrackMinSectorWait;
            }

            holdingUsUp = null;
            lappingUs = null;
            driverReputationWarningChecksInThisSession.Clear();
            lastLappingWarning.Clear();

            trackLandmarkAttackDriverNamesUsed.Clear();
            trackLandmarkDefendDriverNamesUsed.Clear();

            iRacingBadClubs.Clear();
            iRacingOkClubs.Clear();
            iRacingBadDrivers.Clear();
            iRacingMinRating = 0;

            initialized = false;
        }

        // adds 0, 1, or 2 to the sectors to wait. This means there's a 2 in 3 chance that a gap report
        // scheduled for the lap end will be moved to a sector
        private int adjustForMidLapPreference(int currentSector, int sectorsTillNextReport)
        {
            if (preferGapReportsMidLap && (currentSector + sectorsTillNextReport - 1) % 3 == 0)
            {
                // note the 0 here - we allow *some* gap reports to remain at the lap end
                int adjustment = Utilities.random.Next(0, 3);
                Log.Debug(() => "Adjusting gap report wait from " + sectorsTillNextReport + " to " + (sectorsTillNextReport + adjustment));
                return sectorsTillNextReport + adjustment;
            }
            return sectorsTillNextReport;
        }

        private int nextReport(GameStateData currentGameState, int minSectorWait, int maxSectorWait)
        {
            int next = Utilities.random.Next(minSectorWait, maxSectorWait);
            if (currentGameState.SessionData.TrackDefinition.gapPoints.Count() <= 0)
            {
                // only prefer mid-lap gap reports if we're on a track with no ad-hoc gapPoints
                next = adjustForMidLapPreference(currentGameState.SessionData.SectorNumber, next);
            }
            return next;
        }

        private Boolean isNearRaceEnd(GameStateData currentGameState)
        {
            if (!currentGameState.SessionData.SessionHasFixedTime)
            {
                if (currentGameState.SessionData.SessionLapsRemaining == 0)
                {
                    // on last lap - check track length 
                    if (currentGameState.SessionData.TrackDefinition.trackLengthClass == TrackData.TrackLengthClass.LONG)
                    {
                        return currentGameState.SessionData.SectorNumber > 1;
                    }
                    if (currentGameState.SessionData.TrackDefinition.trackLengthClass == TrackData.TrackLengthClass.VERY_LONG)
                    {
                        return currentGameState.SessionData.SectorNumber == 3;
                    }
                    return true;
                }
            }
            else if (currentGameState.SessionData.SessionTimeRemaining > -1 && currentGameState.SessionData.SessionTimeRemaining < 120)
            {
                return true;
            }
            return false;
        }

        // This should be protected with a call to ensure that the player is not leading the race.
        //
        // Note that the deltaTime is always in the direction in front, which can result in wrap
        // around where the car is actually behind us.
        // The deltaLap can be momentarily incorrect when crossing the start/finish.
        private gapToOpponent mkGapFrontInRace(GameStateData currentGameState)
        {
            String key = currentGameState.SessionData.OpponentKeyInFront;
            var gap = new Gap(
                -currentGameState.SessionData.TimeDeltaFront,
                -currentGameState.SessionData.LapsDeltaFront,
                key);
            OpponentData opponent = null;
            if (key != null)
            {
                currentGameState.OpponentData.TryGetValue(key, out opponent);
            }
            return new gapToOpponent(gap, opponent);
        }

        // should be protected with a call to ensure that the player is not last.
        //
        // The same caveats as the "in front" variant (wraparound and lap delta) apply.
        private gapToOpponent mkGapBehindInRace(GameStateData currentGameState)
        {
            String key = currentGameState.SessionData.OpponentKeyBehind;
            var gap = new Gap(
                currentGameState.SessionData.TimeDeltaBehind,
                currentGameState.SessionData.LapsDeltaBehind,
                key);
            OpponentData opponent = null;
            if (key != null)
            {
                currentGameState.OpponentData.TryGetValue(key, out opponent);
            }
            return new gapToOpponent(gap, opponent);
        }

        /// <summary>
        /// The car behind in our class, but only if it is not the car that is behind us in the race. 
        /// </summary>
        /// <param name="currentGameState"></param>
        /// <param name="onlyIncludeCarsLappingThePlayer"></param>
        /// <returns>null gapToOpponent if there is no valid data (which could mean that the car that is
        /// technically behind on track by wrapping around is actually closer to being ahead on track).</returns>
        //
        // note that the deltaTime is always positive (which is conveniently also the convention for signed deltas),
        // but the lapDelta may be negative if the car is ahead in the race.
        private gapToOpponent mkGapBehindOnTrack(GameStateData currentGameState, bool onlyIncludeCarsLappingThePlayer = false)
        {
            gapToOpponent result = new gapToOpponent();
            String excludingKey = currentGameState.getOpponentKeyBehind(currentGameState.carClass);
            String key = currentGameState.getOpponentKeyBehindOnTrack(
                onlyIncludeCarsLappingThePlayer: onlyIncludeCarsLappingThePlayer,
                onlyIncludeClass: currentGameState.carClass);
            if (key != null && !key.Equals(excludingKey) && // car is not the same class
                currentGameState.OpponentData.TryGetValue(key, out OpponentData opponent))
            {
                var (lapDiff, deltaTime) = currentGameState.SessionData.DeltaTime.GetRelativeDelta(opponent.DeltaTime);
                if (deltaTime >= 0) // only consider cars actually behind us
                {
                    var gap = new Gap(
                        deltaTime,
                        lapDiff, // could be negative
                        key);
                    result.gap = gap;
                    result.opponent = opponent;
                }
            }
            return result;
        }

        private bool isNotRacing(GameStateData currentGameState)
        {
            return currentGameState.FlagData.currentLapIsFCY
                || currentGameState.FlagData.isLocalYellow
                || currentGameState.SessionData.Flag == FlagEnum.BLUE
                || currentGameState.PitData.InPitlane
                || PitStops.isPittingThisLap;
        }

        private bool putPersistedBadDriver(OpponentData opponent)
        {
            // don't repeat it back to us!
            driverReputationWarningChecksInThisSession.Add(opponent.DriverRawName);

            var rep = new PersistedIRacingBadReputation();
            rep.customer_id = opponent.CostId;
            rep.name = opponent.DriverRawName;
            rep.carClass = opponent.CarClass.carClassEnumString;
            rep.date = DateTime.UtcNow.ToString("yyyy-MM-dd");
            rep.comment = "added by CrewChief";

            try
            {
                var db = getPersistedBadDrivers();
                db.Add(rep);

                String rawJson = JsonConvert.SerializeObject(db, Formatting.Indented);
                if (!File.Exists(DataFiles.iracing_reputations) || !rawJson.Equals(File.ReadAllText(DataFiles.iracing_reputations)))
                {
                    File.WriteAllText(DataFiles.iracing_reputations, rawJson);
                    return true;
                }
            }
            catch (Exception e)
            {
                Console.WriteLine($"Error when updating the iRacing reputation data: {e}");
            }
            return false;
        }

        private List<PersistedIRacingBadReputation> getPersistedBadDrivers()
        {
            if (File.Exists(DataFiles.iracing_reputations))
            {
                return JsonConvert.DeserializeObject<List<PersistedIRacingBadReputation>>(File.ReadAllText(DataFiles.iracing_reputations));
            }
            return new List<PersistedIRacingBadReputation>();
        }

        private volatile bool initialized = false;
        protected override void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (previousGameState == null || currentGameState == null)
            {
                return;
            }

            // do the corner names stuff first, if it's enabled
            if (currentGameState.readLandmarksForThisLap && currentGameState.SessionData.trackLandmarksTiming != null &&
                currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark != null)
            {
                // mid-point it true for only 1 tick so this should be safe
                audioPlayer.playMessage(new QueuedMessage("corners/" + currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark, 2, priority: 10));
            }
            if (GameStateData.onManualFormationLap)
            {
                return;
            }

            if (!initialized)
            {
                _iRacingReputationsInit();
                initialized = true;
            }

            if (!currentGameState.SessionData.IsRacingSameCarInFront)
            {
                gapsInFront.Clear();
                gapInFrontAtLastReport = -1;
                holdingUsUp = null;
            }
            if (!currentGameState.SessionData.IsRacingSameCarBehind)
            {
                gapsBehind.Clear();
                gapBehindAtLastReport = -1;
            }
            // there's no equivalent fast check for the car behind on track;
            // don't iterate the opponents list until we're in a new sector

            if (!enableGapMessages
                || previousGameState.SessionData.CompletedLaps <= currentGameState.FlagData.lapCountWhenLastWentGreen
                || currentGameState.SessionData.SessionType != SessionType.Race
                || isNotRacing(currentGameState)
                || isNearRaceEnd(currentGameState))
            {
                return;
            }

            // we want to keep updating the deltas whether we are reading deltas every lap or not,
            // so that the data is available when the user needs it. Note that this does not imply
            // a new lap, so code should always conservatively check that the gap data is not null.
            var isGapPoint = IsNewSectorOrGapPoint(previousGameState, currentGameState);

            if (isGapPoint)
            {
                Gaps gaps = _getGaps(currentGameState);
                if (!CrewChief.readOpponentDeltasForEveryLap)
                {
                    _announceGaps(currentGameState, gaps);
                }
            }

            if (CrewChief.readOpponentDeltasForEveryLap && currentGameState.SessionData.IsNewLap)
            {
                // no need to repeat the opponent name in these variants of the gap messages, they must be terse
                var message = new List<MessageFragment>();

                if (currentGameState.SessionData.ClassPosition != 1)
                {
                    var gap = mkGapFrontInRace(currentGameState);
                    if (gap.gap.timeDelta > minGapToReport)
                    {
                        gapInFrontAtLastReport = gap.gap.timeDelta;
                        message.AddRange(MessageContents(folderGapInFrontIsNow));
                        message.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(gap.gap.timeDelta, Precision.AUTO_GAPS)));
                    }
                }

                if (!currentGameState.isLast())
                {
                    var gap = mkGapBehindInRace(currentGameState);
                    if (gap.gap.timeDelta > minGapToReport)
                    {
                        gapBehindAtLastReport = gap.gap.timeDelta;
                        message.AddRange(MessageContents(folderGapBehindIsNow));
                        message.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(gap.gap.timeDelta, Precision.AUTO_GAPS)));
                    }
                }

                {
                    // since we have no easy way to exclude cars that we just overtook, we only consider cars ahead in
                    // the race which means we also ignore cars that might be unlapping themselves.
                    var bot = mkGapBehindOnTrack(currentGameState, onlyIncludeCarsLappingThePlayer: true);
                    if (bot != null && bot?.gap.timeDelta > minGapToReport)
                    {
                        message.Add(MessageFragment.Text(folderTheGapTo));
                        message.AddRange(Opponents.MkOpponentPosition(bot.opponent.ClassPosition));
                        message.Add(MessageFragment.Text(folderBehindIsNow));
                        // in the interests of brevity, don't include their lap diff
                        message.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(bot.gap.timeDelta, Precision.AUTO_GAPS)));
                    }
                }

                var queued = new QueuedMessage("Timings/gaps_for_laps", 5, message, priority: 10);
                queued.playEvenWhenSilenced = true;
                audioPlayer.playMessage(queued);
            }
        }

        private void _iRacingReputationsInit()
        {
            if (iRacingReputations && Game.IRACING)
            {
                var raw_bad = GlobalBehaviourSettings.useOvalLogic ? iRacingClubReputationsBadRaw.Replace(';', ',') : iRacingClubReputationsBadRaw.Split(';')[0];
                foreach (var entry in raw_bad.Split(','))
                {
                    var sanitized = entry.Trim().ToLower();
                    if (!sanitized.Equals(""))
                    {
                        Log.Verbose(() => $"Reputations: considering '{sanitized}' to be a bad flair");
                        iRacingBadClubs.Add(sanitized);
                        if (sanitized.Equals("international") || sanitized.Equals("iracing"))
                        {
                            // iRacing renamed International to Global at some point, but people
                            // may not have updated their settings.
                            iRacingBadClubs.Add("global");
                        }
                    }
                }

                var raw_good = GlobalBehaviourSettings.useOvalLogic ? iRacingClubReputationsGoodRaw.Split(';')[0] : iRacingClubReputationsGoodRaw.Replace(';', ',');
                foreach (var entry in raw_good.Split(','))
                {
                    var sanitized = entry.Trim().ToLower();
                    if (!sanitized.Equals(""))
                    {
                        Log.Verbose(() => $"Reputations: considering '{sanitized}' to be an approved flair");
                        iRacingOkClubs.Add(sanitized);
                    }
                }

                if (iRacingMinRatingRaw.Length > 0)
                {
                    var ratings = iRacingMinRatingRaw.Split(',').Select(r => r.Trim()).ToArray();
                    if (ratings.Length > 1 && GlobalBehaviourSettings.useOvalLogic)
                    {
                        iRacingMinRating = int.Parse(ratings[1]);
                    }
                    else
                    {
                        iRacingMinRating = int.Parse(ratings[0]);
                    }
                }

                try
                {
                    foreach (var entry in getPersistedBadDrivers())
                    {
                        iRacingBadDrivers.Add(entry.customer_id);
                    }
                }
                catch (Exception e)
                {
                    Console.WriteLine($"Error when loading the iRacing reputation data: {e}");
                }
            }
        }

        private Gaps _getGaps(in GameStateData currentGameState)
        {
            var gaps = new Gaps();
            gaps.inFront.gap = null;
            if (currentGameState.SessionData.ClassPosition != 1)
            {
                Log.Debug( $"Gap in front: not leading, P{currentGameState.SessionData.ClassPosition}");
                var _inFront = mkGapFrontInRace(currentGameState);
                // AMS / RF1 hack - sometimes the gap data is stale, so don't put the exact same gap in the list
                if (_inFront.opponent != null && (gapsInFront.Count == 0 || gapsInFront[0].timeDelta != _inFront.gap.timeDelta))
                {
                    gaps.inFront.gap = _inFront.gap;
                    gaps.inFront.opponent = _inFront.opponent;
                    gapsInFront.Insert(0, gaps.inFront.gap);
                    gaps.inFront.status = getGapStatus(gapsInFront, gapInFrontAtLastReport);
                    Log.Debug(() => $"Gap in front: opponent '{gaps.inFront.opponent} {-gaps.inFront.gap.signedTimeDelta}S ahead, status {gaps.inFront.status}");

                    if (gaps.inFront.status == GapStatus.CLOSE && !gaps.inFront.opponent.DriverRawName.Equals(holdingUsUp?.driver))
                    {
                        holdingUsUp = new DriverAtTime(currentGameState.Now, gaps.inFront.opponent.DriverRawName);
                    }
                }
            }

            if (!currentGameState.isLast())
            {
                //Log.Debug(() => $"Gap in front: not last");
                var _behind = mkGapBehindInRace(currentGameState);
                // AMS / RF1 hack - sometimes the gap data is stale, so don't put the exact same gap in the list
                gaps.behind.gap = _behind.gap;
                gaps.behind.opponent = _behind.opponent;
                gaps.behind.status = getGapStatus(gapsBehind, gapBehindAtLastReport);
                Log.Debug(() => $"Gap behind: opponent '{gaps.behind.opponent} {gaps.behind.gap.signedTimeDelta}S ahead, status {gaps.behind.status}");
                if (_behind.opponent != null && (gapsBehind.Count == 0 || gapsBehind[0].timeDelta != _behind.gap.timeDelta))
                {
                    gapsBehind.Insert(0, gaps.behind.gap);
                }
            }

            gaps.behindOnTrack = mkGapBehindOnTrack(currentGameState);
            if (gaps.behindOnTrack?.opponent != null)
            {
                if (!gaps.behindOnTrack.gap.opponentKey.Equals(lappingUs))
                {
                    gapsBehindOnTrack.Clear();
                    gapBehindOnTrackAtLastReport = -1;
                    lappingUs = gaps.behindOnTrack?.gap.opponentKey;
                    sectorsSinceLastGapBehindOnTrackReport = sectorsUntilNextGapBehindOnTrackReport;
                }
                if (gapsBehindOnTrack.Count == 0 || gapsBehindOnTrack[0].timeDelta != gaps.behindOnTrack.gap.timeDelta)
                {
                    gapsBehindOnTrack.Insert(0, gaps.behindOnTrack?.gap);
                    gaps.behindOnTrack.status = getGapStatus(gapsBehindOnTrack, gapBehindOnTrackAtLastReport);
                }
            }
            else
            {
                lappingUs = null;
            }
            return gaps;
        }

        private void _announceGaps(in GameStateData currentGameState, Gaps gaps)
        {
            sectorsSinceLastGapAheadReport++;
            sectorsSinceLastGapBehindReport++;
            sectorsSinceLastGapBehindOnTrackReport++;

            // Play which ever is the smaller gap, even if the other one is ready to be played
            // as this avoids splitting the player's concentration. Don't mention racing gaps
            // if we have a car about to lap us.
            bool lappingCarNear = gapBehindOnTrackReportFrequency > 0
                                  && gaps.behindOnTrack.gap != null
                                  && gaps.behindOnTrack.gap.timeDelta <= 5                  // they're close,
                                  && ((gaps.behindOnTrack.status == GapStatus.DECREASING || // closing or
                                      gaps.behindOnTrack.status == GapStatus.CLOSE) &&      // very close
                                      gaps.behindOnTrack.opponent.OverallPosition < currentGameState.SessionData.OverallPosition)   // and ahead of us
                                  && !(gaps.behindOnTrack.status == GapStatus.CLOSE && GlobalBehaviourSettings.justTheFacts);
            bool canPlayGapInFront = gapAheadReportFrequency > 0
                                     && gaps.inFront.status != GapStatus.NONE
                                     && !(gaps.inFront.status == GapStatus.CLOSE && (GlobalBehaviourSettings.justTheFacts || GlobalBehaviourSettings.useOvalLogic))
                                     && gaps.behindOnTrack.status != GapStatus.CLOSE
                                     && gaps.inFront.gap.lapDelta == 0;
            bool canPlayGapBehind = gapBehindReportFrequency > 0
                                    && gaps.behind.status != GapStatus.NONE
                                    && !(gaps.behind.status == GapStatus.CLOSE && (GlobalBehaviourSettings.justTheFacts || GlobalBehaviourSettings.useOvalLogic))
                                    && !lappingCarNear
                                    && gaps.behind.gap.lapDelta == 0;
            bool closerInFront = gapsInFront.Count > 0 && gapsBehind.Count > 0 && (gapsInFront[0].timeDelta < gapsBehind[0].timeDelta);

            // always prefer the gap behind on track because it implies immediate attention. Restricting to DECREASING/CLOSE
            // should exclude cars that we are lapping, but let through cars that are fast enough to unlap themselves.
            if (lappingCarNear && sectorsSinceLastGapBehindOnTrackReport >= sectorsUntilNextGapBehindOnTrackReport)
            {
                DelayedMessage callback = delegate (GameStateData futureGameState, List<MessageFragment> primary, List<MessageFragment> alt) { _lappingCarNear(gaps, futureGameState, primary); };
                audioPlayer.playMessage(new QueuedMessage("Timings/gap_behind_on_track", 5, delayedMessage: callback, priority: 5));
            }
            else if (canPlayGapInFront && (closerInFront || gapBehindReportFrequency <= 0) && sectorsSinceLastGapAheadReport >= sectorsUntilNextGapAheadReport)
            {
                DelayedMessage callback = delegate (GameStateData futureGameState, List<MessageFragment> msg, List<MessageFragment> alt_) { _gapInFront(gaps, futureGameState, msg); };
                audioPlayer.playMessage(new QueuedMessage("Timings/gap_in_front", 5, delayedMessage: callback, priority: 5));
            }
            else if (canPlayGapBehind && (!closerInFront || gapAheadReportFrequency <= 0) && sectorsSinceLastGapBehindReport >= sectorsUntilNextGapBehindReport)
            {
                DelayedMessage callback = delegate (GameStateData futureGameState, List<MessageFragment> msg, List<MessageFragment> alt_) { _gapBehind(gaps, futureGameState, msg); };
                audioPlayer.playMessage(new QueuedMessage("Timings/gap_behind", 5, delayedMessage: callback, priority: 5));
            }
        }

        private void _lappingCarNear(Gaps gaps, GameStateData futureGameState, List<MessageFragment> primary)
        {
            if (isNotRacing(futureGameState))
            {
                Log.Debug("gap_behind_on_track invalidated because we're not racing");
                return;
            }
            var gap = mkGapBehindOnTrack(futureGameState);
            if (gap == null || !gaps.behindOnTrack.gap.opponentKey.Equals(gap.gap.opponentKey))
            {
                Log.Debug("gap_behind_on_track invalidated because opponent changed");
                return;
            }
            if (gap.gap.timeDelta < minGapToReport)
            {
                Log.Debug("gap_behind_on_track not reported because opponent is so close");
                return;
            }

            // it would be good to have custom sounds such as "they are not our fight", "make it easy", "stay predictable",
            // "they are lapping us", "they want to unlap themselves" which would also allow us to revisit if we want to
            // include the car position and lap delta. Instead, we use the car position and lap delta to imply that we need
            // to get out of their way.
            if (gaps.behindOnTrack.status == GapStatus.CLOSE)
            {
                lastLappingWarning.TryGetValue(gap.gap.opponentKey, out var lastLappingWarning_);
                if (lastLappingWarning_ == null ||
                    futureGameState.Now.Subtract(lastLappingWarning_) > TimeSpan.FromMinutes(5))
                {
                    lastLappingWarning.Add(gap.gap.opponentKey, futureGameState.Now);
                    if (gap.opponent.OverallPosition < futureGameState.SessionData.OverallPosition)
                    {
                        // they are lapping us. It would be good to be able to more intelligently work out if
                        // we are actually racing them or not (e.g. we just pitted) but maybe that's best just
                        // implemented through more appropriate voice messages that give the context without
                        // a suggested action.
                        if (SoundCache.soundSets.ContainsKey(folderCarBehindLappingUs))
                        {
                            primary.Add(MessageFragment.Text(folderCarBehindLappingUs));
                        }
                        else
                        {
                            // temporary until Jerry records this
                            primary.Add(MessageFragment.Text(FrozenOrderMonitor.folderAllowGuyBehindToPass));
                        }
                    }
                    else
                    {
                        // potentially unlapping. It can be annoying to report on this if the car behind is
                        // sticking with us for our draft.
                        if (SoundCache.soundSets.ContainsKey(folderCarBehindUnlapping))
                        {
                            primary.Add(MessageFragment.Text(folderCarBehindUnlapping));
                        }
                        else
                        {
                            // temporary until Jerry records this
                            primary.AddRange(Opponents.MkOpponentPosition(gap.opponent.ClassPosition));
                            primary.Add(MessageFragment.Text(Position.folderBehind)); // "is behind" would be better
                        }
                    }
                }
            }
            else
            {
                primary.Add(MessageFragment.Text(folderTheGapTo));
                primary.AddRange(Opponents.MkOpponentPosition(gap.opponent.ClassPosition));
                primary.Add(MessageFragment.Text(folderBehindIsNow));
                primary.AddRange(MkOpponentRelativeDelta(gap?.opponent, expectedSign: 1, includeLapInfo: true));
            }

            gapBehindOnTrackAtLastReport = gap.gap.timeDelta;
            sectorsSinceLastGapBehindOnTrackReport = 0;
            sectorsUntilNextGapBehindOnTrackReport = nextReport(futureGameState, gapBehindOnTrackMinSectorWait, gapBehindOnTrackMaxSectorWait);
        }

        private void _gapInFront(Gaps gaps, GameStateData futureGameState, List<MessageFragment> msg)
        {
            if (isNotRacing(futureGameState))
            {
                Log.Debug("gap_in_front invalidated because we're not racing");
                return;
            }
            if (futureGameState.SessionData.ClassPosition <= 1)
            {
                Log.Debug("gap_in_front invalidated because we are first");
                return;
            }
            var futureGapInFront = mkGapFrontInRace(futureGameState);
            if (!gaps.inFront.gap.opponentKey.Equals(futureGapInFront.gap.opponentKey))
            {
                Log.Debug("gap_in_front invalidated because opponent changed");
                return;
            }

            var gapMessage = MessageFragment.Time(TimeSpanWrapper.FromSeconds(futureGapInFront.gap.timeDelta, Precision.AUTO_GAPS));
            List<MessageFragment> opponentName;

            if (Utilities.random.Next(0, 3) == 0)
            {
                opponentName = Opponents.MkOpponentPosition(gaps.inFront.opponent.ClassPosition);
            }
            else
            {
                opponentName = Opponents.MkOpponentShort(gaps.inFront.opponent, preferPosition: false, requestNumber: false, preferCantPronounce: false);
            }

            if (gaps.inFront.status == GapStatus.CLOSE)
            {
                if (holdingUsUp != null && (futureGameState.Now - holdingUsUp.started).TotalSeconds > 60)
                {
                    msg.AddRange(MessageContents(folderBeingHeldUp));
                    if (futureGapInFront.gap.timeDelta < 6)
                    {
                        msg.AddRange(mkAttackAdvice(futureGapInFront.opponent, futureGameState));
                    }
                }
                msg.AddRange(mkReputationAdvice(futureGapInFront.opponent, opponentIsAhead: true));
            }
            else if (gaps.inFront.status == GapStatus.INCREASING && futureGapInFront.gap.timeDelta > minGapToReport)
            {
                msg.Add(MessageFragment.Text(folderTheGapTo));
                msg.AddRange(opponentName);
                msg.Add(MessageFragment.Text(folderAheadIsIncreasing));
                msg.Add(gapMessage);
            }
            else if (gaps.inFront.status == GapStatus.DECREASING && futureGapInFront.gap.timeDelta > minGapToReport)
            {
                msg.Add(MessageFragment.Text(folderYoureReeling));
                msg.AddRange(opponentName);
                msg.Add(MessageFragment.Text(folderInTheGapIsNow));
                msg.Add(gapMessage);

                if (futureGapInFront.gap.timeDelta < 6)
                {
                    msg.AddRange(mkAttackAdvice(futureGapInFront.opponent, futureGameState));
                }
                if (futureGapInFront.gap.timeDelta < 2)
                {
                    msg.AddRange(mkReputationAdvice(futureGapInFront.opponent, opponentIsAhead: true));
                }
            }
            else if (gaps.inFront.status == GapStatus.OTHER && futureGapInFront.gap.timeDelta > minGapToReport)
            {
                if (Utilities.random.Next(0, 3) == 0)
                {
                    msg.AddRange(MessageContents(folderGapInFrontIsNow));
                }
                else
                {
                    msg.Add(MessageFragment.Text(folderTheGapTo));
                    msg.AddRange(opponentName);
                    msg.Add(MessageFragment.Text(folderAheadIsNow));
                }
                msg.Add(gapMessage);
            }
            else
            {
                Console.WriteLine("Invalid inFront.status(" + gaps.inFront.status + ") with gap " + futureGapInFront.gap.timeDelta);
            }

            gapInFrontAtLastReport = futureGapInFront.gap.timeDelta;
            sectorsSinceLastGapAheadReport = 0;
            sectorsUntilNextGapAheadReport = nextReport(futureGameState, gapAheadMinSectorWait, gapAheadMaxSectorWait);
        }

        private void _gapBehind(Gaps gaps, GameStateData futureGameState, List<MessageFragment> msg)
        {
            if (isNotRacing(futureGameState))
            {
                Log.Debug("gap_behind invalidated because we're not racing");
                return;
            }
            if (futureGameState.isLast())
            {
                Log.Debug("gap_behind invalidated because we are last");
                return;
            }
            var futureGapBehind = mkGapBehindInRace(futureGameState);
            if (!gaps.behind.gap.opponentKey.Equals(futureGapBehind.gap.opponentKey))
            {
                Log.Debug("gap_behind invalidated because opponent changed");
                return;
            }

            var gapMessage = MessageFragment.Time(TimeSpanWrapper.FromSeconds(futureGapBehind.gap.timeDelta, Precision.AUTO_GAPS));
            List<MessageFragment> opponentName;
            if (Utilities.random.Next(0, 3) == 0)
            {
                opponentName = Opponents.MkOpponentPosition(gaps.behind.opponent.ClassPosition);
            }
            else
            {
                opponentName = Opponents.MkOpponentShort(gaps.behind.opponent, preferPosition: false, requestNumber: false, preferCantPronounce: false);
            }

            if (gaps.behind.status == GapStatus.CLOSE)
            {
                msg.AddRange(MessageContents(folderBeingPressured));
                msg.AddRange(mkDefendAdvice(futureGapBehind.opponent, futureGameState));
                msg.AddRange(mkReputationAdvice(futureGapBehind.opponent, opponentIsAhead: false));
            }
            else if (gaps.behind.status == GapStatus.INCREASING && futureGapBehind.gap.timeDelta > minGapToReport)
            {
                msg.Add(MessageFragment.Text(folderTheGapTo));
                msg.AddRange(opponentName);
                msg.Add(MessageFragment.Text(folderBehindIsIncreasing));
                msg.Add(gapMessage);
            }
            else if (gaps.behind.status == GapStatus.DECREASING && futureGapBehind.gap.timeDelta > minGapToReport)
            {
                msg.AddRange(opponentName);
                msg.Add(MessageFragment.Text(folderIsReelingYouIn));
                msg.Add(gapMessage);
                msg.AddRange(mkDefendAdvice(futureGapBehind.opponent, futureGameState));

                if (futureGapBehind.gap.timeDelta < 2)
                {
                    // it makes sense to have this check as they are closing on us, because
                    // they might be liable to do a divebomb
                    msg.AddRange(mkReputationAdvice(futureGapBehind.opponent, opponentIsAhead: false));
                }
            }
            else if (gaps.behind.status == GapStatus.OTHER && futureGapBehind.gap.timeDelta > minGapToReport)
            {
                if (Utilities.random.Next(0, 3) == 0)
                {
                    msg.AddRange(MessageContents(folderGapBehindIsNow));
                }
                else
                {
                    msg.Add(MessageFragment.Text(folderTheGapTo));
                    msg.AddRange(opponentName);
                    msg.Add(MessageFragment.Text(folderBehindIsNow));
                }
                msg.Add(gapMessage);
            }
            else
            {
                Console.WriteLine("Invalid behind.status(" + gaps.behind.status + ") with gap " + futureGapBehind.gap.timeDelta);
            }

            gapBehindAtLastReport = futureGapBehind.gap.timeDelta;
            sectorsSinceLastGapBehindReport = 0;
            sectorsUntilNextGapBehindReport = nextReport(futureGameState, gapBehindMinSectorWait, gapBehindMaxSectorWait);
        }

        private List<MessageFragment> mkAttackAdvice(OpponentData opponent, GameStateData st)
        {
            var message = new List<MessageFragment>();
            if (opponent == null ||
                st.SessionData.trackLandmarksTiming == null)
            {
                Log.Warning("mkAttackAdvice called with null opponent or null trackLandmarksTiming");
                return message;
            }
            DateTime lastTimeDriverNameUsed = DateTime.MinValue;
            if (!trackLandmarkAttackDriverNamesUsed.TryGetValue(opponent.DriverRawName, out lastTimeDriverNameUsed) ||
                lastTimeDriverNameUsed + minTimeBetweenAttackOrDefendByDriver < st.Now)
            {
                TrackLandmarksTiming.LandmarkAndDeltaType landmarkAndDeltaType =
                    st.SessionData.trackLandmarksTiming.getLandmarkWhereIAmFaster(opponent.trackLandmarksTiming, true, false);
                if (landmarkAndDeltaType.landmarkName != null)
                {
                    var cornerFolder = "corners/" + landmarkAndDeltaType.landmarkName;
                    // this check may be excessive, but it seems more likely that landmark data would be missing
                    // than anything else.
                    // It would be good to have turn/straight numbers available as backups.
                    if (!SoundCache.soundSets.ContainsKey(cornerFolder))
                    {
                        Console.WriteLine("Skipping overtaking advice; no sound for landmark: " + cornerFolder);
                    }
                    {
                        // either we're faster on entry or faster through
                        String attackFolder = landmarkAndDeltaType.deltaType == TrackLandmarksTiming.DeltaType.Time ? folderHeIsSlowerThroughCorner : folderHeIsSlowerEnteringCorner;
                        message.AddRange(MessageContents(Pause(500), attackFolder, cornerFolder));
                        trackLandmarkAttackDriverNamesUsed[opponent.DriverRawName] = st.Now;
                    }
                }
            }
            return message;
        }

        private List<MessageFragment> mkDefendAdvice(OpponentData opponent, GameStateData st)
        {
            var message = new List<MessageFragment>();
            if (opponent == null || 
                st.SessionData.trackLandmarksTiming == null)
            {
                Log.Warning("mkDefendAdvice called with null opponent or null trackLandmarksTiming");
                return message;
            }
            DateTime lastTimeDriverNameUsed = DateTime.MinValue;
            if (!trackLandmarkDefendDriverNamesUsed.TryGetValue(opponent.DriverRawName, out lastTimeDriverNameUsed) ||
                lastTimeDriverNameUsed + minTimeBetweenAttackOrDefendByDriver < st.Now)
            {
                TrackLandmarksTiming.LandmarkAndDeltaType landmarkAndDeltaType =
                        st.SessionData.trackLandmarksTiming.getLandmarkWhereIAmSlower(opponent.trackLandmarksTiming, true, false);
                if (landmarkAndDeltaType.landmarkName != null)
                {
                    var cornerFolder = "corners/" + landmarkAndDeltaType.landmarkName;
                    if (!SoundCache.soundSets.ContainsKey(cornerFolder))
                    {
                        Console.WriteLine("Skipping defence advice; no sound for landmark: " + cornerFolder);
                    }
                    {
                        // either we're slower on entry or slower through
                        String defendFolder = landmarkAndDeltaType.deltaType == TrackLandmarksTiming.DeltaType.Time ? folderHeIsFasterThroughCorner : folderHeIsFasterEnteringCorner;
                        message.AddRange(MessageContents(Pause(500), defendFolder, cornerFolder));
                        trackLandmarkDefendDriverNamesUsed[opponent.DriverRawName] = st.Now;
                    }
                }
            }
            return message;
        }

        // adds a "take care, this guy is a menace" type message for opponents with bad rep (R3E / iRacing only)
        private List<MessageFragment> mkReputationAdvice(OpponentData opponent, Boolean opponentIsAhead)
        {
            if (driverReputationWarningChecksInThisSession.Contains(opponent.DriverRawName))
            {
                return new List<MessageFragment>();
            }
            return MkFreshReputationAdvice(opponent, opponentIsAhead);
        }

        private GapStatus getGapStatus(List<Gap> gaps, float lastReportedGap)
        {
            // when comparing gaps round to 1 decimal place
            if (gaps.Count < 3  // if we have less than 3 gaps in the list
                || gaps[0].timeDelta <= 0 || gaps[1].timeDelta <= 0 || gaps[2].timeDelta <= 0 // or not fully initialized
                || gaps[0].timeDelta > 20  // or the last gap is too big
                || Math.Abs(gaps[0].timeDelta - gaps[1].timeDelta) > 5)  // or the change in the gap is too big, we don't want to report anything
            {
                return GapStatus.NONE;
            }
            else
            {
                if (!isSameCar(gaps, 3))
                {
                    // the gaps we're looking at don't all refer to the same car
                    return GapStatus.NONE;
                }
                if ((gaps[0].timeDelta < 0.5 && gaps[1].timeDelta < 0.5) ||
                         (gaps.Count > 2 && gaps[0].timeDelta < 0.7 && gaps[1].timeDelta < 0.7 && gaps[2].timeDelta < 0.7) ||
                         (gaps.Count > 3 && gaps[0].timeDelta < 0.8 && gaps[1].timeDelta < 0.8 && gaps[2].timeDelta < 0.8 && gaps[3].timeDelta < 0.8))
                {
                    // this car has been very close for 2 sectors, pretty close for 3 or fairly close for 4 sectors
                    return GapStatus.CLOSE;
                }
                else if ((lastReportedGap == -1 || Math.Round(gaps[0].timeDelta, 1) > Math.Round(lastReportedGap)) &&
                    Math.Round(gaps[0].timeDelta, 1) > Math.Round(gaps[1].timeDelta, 1) && Math.Round(gaps[1].timeDelta, 1) > Math.Round(gaps[2].timeDelta, 1))
                {
                    return GapStatus.INCREASING;
                }
                else if ((lastReportedGap == -1 || Math.Round(gaps[0].timeDelta, 1) < Math.Round(lastReportedGap)) &&
                    Math.Round(gaps[0].timeDelta, 1) < Math.Round(gaps[1].timeDelta, 1) && Math.Round(gaps[1].timeDelta, 1) < Math.Round(gaps[2].timeDelta, 1))
                {
                    return GapStatus.DECREASING;
                }
                else if (Math.Abs(gaps[0].timeDelta - gaps[1].timeDelta) < 1 && Math.Abs(gaps[0].timeDelta - gaps[2].timeDelta) < 1)
                {
                    // If the gap hasn't changed by more than a second we can report it with no 'increasing' or 'decreasing' prefix
                    return GapStatus.OTHER;
                }
                else
                {
                    return GapStatus.NONE;
                }
            }
        }

        private Boolean isSameCar(List<Gap> gaps, int gapsToCheck)
        {
            String mostRecentOpponentKey = null;
            for (int i = 0; i < gapsToCheck; i++)
            {
                String thisOpponentKey = gaps[0].opponentKey;
                if (thisOpponentKey == null)
                {
                    return false;
                }
                if (i == 0)
                {
                    mostRecentOpponentKey = thisOpponentKey;
                }
                else if (thisOpponentKey != mostRecentOpponentKey)
                {
                    return false;
                }
            }
            return true;
        }

        // takes timeDelta and lapDifference from GetSignedDeltaTimeWithLapDifference, which (unconventionally) uses positive
        // lapDifference / timeDelta for cars that are behind.
        //
        // the expectedSign is an adhoc enum to indicate the context that the request has been made, to allow for obvious information
        // to be omitted and for contextual information to be added (especially when there is a lap delta):
        //
        //  -1) expected opponent ahead on track
        //   0) no context known
        //   1) opponent behind on track

        // returns null if the message could not be created
        private static List<MessageFragment> MkOpponentRelativeDelta(OpponentData opponent, int expectedSign, bool includeLapInfo)
        {
            if (opponent != null)
            {
                var cgs = CrewChief.currentGameState;
                var (lapDiff, deltaTime) = cgs.SessionData.DeltaTime.GetRelativeDelta(opponent.DeltaTime);
                if (!(lapDiff == 0 && deltaTime == 0.0f))
                {
                    return MkOpponentDelta(
                        lapDifference: lapDiff,
                        timeDelta: deltaTime,
                        expectedDeltaSign: expectedSign,
                        includeLapInfo: includeLapInfo);
                }
            }
            return null;
        }

        private static readonly List<SpeechCommands.ID> Commands = new List<SpeechCommands.ID>
        {
            SpeechCommands.ID.NOTE_BAD_DRIVER_AHEAD_ON_TRACK,
            SpeechCommands.ID.NOTE_BAD_DRIVER_BEHIND_ON_TRACK,
            SpeechCommands.ID.SESSION_STATUS,
            SpeechCommands.ID.STATUS,
            SpeechCommands.ID.WHATS_MY_GAP_BEHIND,
            SpeechCommands.ID.WHATS_MY_GAP_BEHIND_ON_TRACK,
            SpeechCommands.ID.WHATS_MY_GAP_IN_FRONT,
            SpeechCommands.ID.WHATS_MY_GAP_IN_FRONT_ON_TRACK,
            SpeechCommands.ID.WHATS_MY_GAP_TO_LEADER,
            SpeechCommands.ID.WHATS_THE_LEADER_LAP,
            SpeechCommands.ID.WHERE_AM_I_FASTER,
            SpeechCommands.ID.WHERE_AM_I_SLOWER,
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
            var currentGameState = CrewChief.currentGameState;
            if (currentGameState == null)
            {
                // defensive guard, now everything can assume it is non-null
                return;
            }
            bool isLeading = currentGameState.SessionData.ClassPosition == 1;
            bool isRace = currentGameState.SessionData.SessionType == SessionType.Race;
            bool haveData = false;

            switch (cmd)
            {
                case SpeechCommands.ID.SESSION_STATUS:
                case SpeechCommands.ID.STATUS:
                    {
                        haveData = true; // Don't say "No data"
                        if (isLeading)
                        {
                            var behind = mkGapBehindInRace(currentGameState);
                            if (behind.gap.timeDelta > 2)
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_behind", 0,
                                        messageFragments: MessageContents(folderGapBehindIsNow, TimeSpanWrapper.FromMilliseconds(behind.gap.timeDelta * 1000, Precision.AUTO_GAPS))));
                            }
                        }
                        else if (!currentGameState.isLast())
                        {
                            var inFront = mkGapFrontInRace(currentGameState);
                            if (inFront.gap.timeDelta > 2)
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_in_front", 0,
                                        messageFragments: MessageContents(folderGapInFrontIsNow, TimeSpanWrapper.FromMilliseconds(inFront.gap.timeDelta * 1000, Precision.AUTO_GAPS))));
                            }
                        }

                        break;
                    }

                case SpeechCommands.ID.WHERE_AM_I_FASTER:
                    {
                        if (!isLeading)
                        {
                            OpponentData opponent = currentGameState.getOpponentAtClassPosition(currentGameState.SessionData.ClassPosition - 1, currentGameState.carClass);
                            var advice = mkAttackAdvice(opponent, currentGameState);
                            if (advice.Count() > 0)
                            {
                                haveData = true;
                                audioPlayer.playMessageImmediately(new QueuedMessage("Timings/corner_to_attack_in", 0, advice));
                            }
                        }

                        break;
                    }

                case SpeechCommands.ID.WHERE_AM_I_SLOWER:
                    {
                        if (!currentGameState.isLast())
                        {
                            OpponentData opponent = currentGameState.getOpponentAtClassPosition(currentGameState.SessionData.ClassPosition + 1, currentGameState.carClass);
                            var advice = mkDefendAdvice(opponent, currentGameState);
                            if (advice.Count() > 0)
                            {
                                haveData = true;
                                audioPlayer.playMessageImmediately(new QueuedMessage("Timings/corner_to_defend_in", 0, advice));
                            }
                        }

                        break;
                    }

                case SpeechCommands.ID.WHATS_MY_GAP_IN_FRONT:
                    {
                        if (isRace)
                        {
                            if (isLeading)
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage(Position.folderLeading, 0));
                                haveData = true;
                            }
                            else
                            {
                                var gap = mkGapFrontInRace(currentGameState);
                                if (gap.gap.timeDelta != 0.0)
                                {
                                    gapInFrontAtLastReport = gap.gap.timeDelta;
                                    var message = MkOpponentDelta(
                                            lapDifference: gap.gap.signedLapDelta,
                                            timeDelta: gap.gap.signedTimeDelta,
                                            expectedDeltaSign: -1,
                                            includeLapInfo: true);
                                    audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_to_opponent", 0, messageFragments: message));
                                    haveData = true;
                                }
                            }
                        }

                        break;
                    }

                case SpeechCommands.ID.WHATS_MY_GAP_BEHIND:
                    {
                        if (isRace)
                        {
                            if (currentGameState.isLastInStandings())
                            {
                                audioPlayer.playMessageImmediately(new QueuedMessage(Position.folderLast, 0));
                                haveData = true;
                            }
                            else
                            {
                                var gap = mkGapBehindInRace(currentGameState);
                                if (gap.gap.timeDelta != 0.0)
                                {
                                    gapBehindAtLastReport = gap.gap.timeDelta;
                                    var message = MkOpponentDelta(
                                            lapDifference: gap.gap.signedLapDelta,
                                            timeDelta: gap.gap.signedTimeDelta,
                                            expectedDeltaSign: 1,
                                            includeLapInfo: true);
                                    audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_to_opponent", 0, messageFragments: message));
                                    haveData = true;
                                }
                            }
                        }

                        break;
                    }

                case SpeechCommands.ID.WHATS_MY_GAP_IN_FRONT_ON_TRACK:
                    {
                        var opponentKey = currentGameState.getOpponentKeyInFrontOnTrack();
                        if (opponentKey != null && currentGameState.OpponentData.TryGetValue(opponentKey, out OpponentData opponent))
                        {
                            var (lapDiff, timeDelta) = currentGameState.SessionData.DeltaTime.GetRelativeDelta(opponent.DeltaTime);
                            if (timeDelta < 0.0)
                            {
                                var message = MkOpponentDelta(
                                        lapDifference: lapDiff,
                                        timeDelta: timeDelta,
                                        expectedDeltaSign: -1,
                                        includeLapInfo: true);
                                audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_to_opponent", 0, messageFragments: message));
                                haveData = true;
                            }
                        }

                        break;
                    }

                case SpeechCommands.ID.WHATS_MY_GAP_BEHIND_ON_TRACK:
                    {
                        var opponentKey = currentGameState.getOpponentKeyBehindOnTrack();
                        if (opponentKey != null && currentGameState.OpponentData.TryGetValue(opponentKey, out OpponentData opponent))
                        {
                            var (lapDiff, timeDelta) = currentGameState.SessionData.DeltaTime.GetRelativeDelta(opponent.DeltaTime);
                            if (timeDelta > 0.0)
                            {
                                if (!opponentKey.Equals(currentGameState.getOpponentKeyBehind(currentGameState.carClass))
                                    && CarData.IsCarClassEqual(opponent.CarClass, currentGameState.carClass))
                                {
                                    gapBehindOnTrackAtLastReport = timeDelta;
                                }
                                var message = MkOpponentDelta(
                                        lapDifference: lapDiff,
                                        timeDelta: timeDelta,
                                        expectedDeltaSign: 1,
                                        includeLapInfo: true);
                                audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_to_opponent", 0, messageFragments: message));
                                haveData = true;
                            }
                        }

                        break;
                    }

                case SpeechCommands.ID.WHATS_THE_LEADER_LAP when currentGameState.SessionData.SessionType == SessionType.Race:
                    {
                        // we don't have a bare "lap" fragment, so we have to say "X laps" instead of "lap X".
                        var messages = new List<MessageFragment>();
                        if (isLeading)
                        {
                            int laps = currentGameState.SessionData.LapCount;
                            messages.AddRange(MessageContents(Position.folderLeading, Pause(200), laps, Battery.folderLaps));
                        }
                        else
                        {
                            var opponent = currentGameState.getOpponentAtClassPosition(1, currentGameState.carClass);
                            if (opponent != null)
                            {
                                int laps = opponent.CompletedLaps + 1;
                                messages.AddRange(MessageContents(laps, Battery.folderLaps));

                                var (lapDiff, _) = currentGameState.SessionData.DeltaTime.GetSignedDeltaTimeWithLapDifference(opponent.DeltaTime);
                                if (lapDiff != 0)
                                {
                                    messages.Add(MessageFragment.Text(Pause(500)));
                                    messages.AddRange(MkLapDifferenceMessage(lapDiff));
                                }
                            }
                        }
                        if (messages.Count > 0)
                        {
                            haveData = true;
                            audioPlayer.playMessageImmediately(new QueuedMessage("timings_leader_lap", 0, messageFragments: messages));
                        }

                        break;
                    }

                case SpeechCommands.ID.WHATS_MY_GAP_TO_LEADER:
                    {
                        // no isRace check because this can be used in qualifying to get the gap to pole
                        if (isLeading)
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage(Position.folderLeading, 0));
                            haveData = true;
                        }
                        else
                        {
                            var opponent = currentGameState.getOpponentAtClassPosition(1, currentGameState.carClass);
                            if (opponent != null)
                            {
                                // it is useful to use the relative here because we might be wanting to know when they will catch us.
                                // If the player wants to know the lap difference to the leader, they will have to do some mental arithmetic
                                // so it is best to have a dedicated command for that.
                                var (lapDiff, timeDelta) = currentGameState.SessionData.DeltaTime.GetRelativeDelta(opponent.DeltaTime);
                                if (timeDelta != 0.0)
                                {
                                    var message = MkOpponentDelta(
                                            lapDifference: lapDiff,
                                            timeDelta: timeDelta,
                                            expectedDeltaSign: 0, // can't assume the context of the query, include the direction in the response
                                            includeLapInfo: true);
                                    audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_to_opponent", 0, messageFragments: message));
                                    haveData = true;
                                }
                            }
                        }

                        break;
                    }

                case SpeechCommands.ID.NOTE_BAD_DRIVER_AHEAD_ON_TRACK when Game.IRACING:
                    {
                        var opponentKey = currentGameState.getOpponentKeyInFrontOnTrack();
                        if (opponentKey != null && currentGameState.OpponentData.TryGetValue(opponentKey, out OpponentData opponent))
                        {
                            haveData = putPersistedBadDriver(opponent);
                            if (haveData)
                            {
                                // custom audio here would be nice
                                audioPlayer.playMessageImmediately(new QueuedMessage("Timings/bad_driver_ahead", 0, messageFragments: MessageContents(AudioPlayer.folderAcknowlegeOK)));
                            }
                        }

                        break;
                    }

                case SpeechCommands.ID.NOTE_BAD_DRIVER_BEHIND_ON_TRACK when Game.IRACING:
                    {
                        var opponentKey = currentGameState.getOpponentKeyBehindOnTrack();
                        if (opponentKey != null && currentGameState.OpponentData.TryGetValue(opponentKey, out OpponentData opponent))
                        {
                            haveData = putPersistedBadDriver(opponent);
                            if (haveData)
                            {
                                // custom audio here would be nice
                                audioPlayer.playMessageImmediately(new QueuedMessage("Timings/bad_driver_behind", 0, messageFragments: MessageContents(AudioPlayer.folderAcknowlegeOK)));
                            }
                        }

                        break;
                    }
            }

            if (!haveData)
            {
                audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
            }
        }



        // note that a new sector is not necessarilly triggered when it is a new lap
        private static Boolean IsNewSectorOrGapPoint(GameStateData previousGameState, GameStateData currentGameState)
        {
            if (currentGameState.SessionData.TrackDefinition != null &&
                currentGameState.SessionData.TrackDefinition.gapPoints != null &&
                currentGameState.SessionData.TrackDefinition.gapPoints.Count() > 0)
            {
                // the current track definition has 'gapPoints', so use them
                if (currentGameState.PositionAndMotionData.DistanceRoundTrack > 0 &&
                    currentGameState.PositionAndMotionData.DistanceRoundTrack > previousGameState.PositionAndMotionData.DistanceRoundTrack)
                {
                    foreach (float gapPoint in currentGameState.SessionData.TrackDefinition.gapPoints)
                    {
                        if (currentGameState.PositionAndMotionData.DistanceRoundTrack >= gapPoint &&
                            previousGameState.PositionAndMotionData.DistanceRoundTrack < gapPoint)
                        {
                            return true;
                        }
                    }
                }
                return false;
            }
            else
            {
                return currentGameState.SessionData.IsNewSector;
            }
        }
    }

    class PersistedIRacingBadReputation
    {
        public int customer_id { get; set; }

        // this is all just for manual inspection
        public String date { get; set; }
        public String carClass { get; set; }
        public String name { get; set; }
        public String comment { get; set; }
    }

}
