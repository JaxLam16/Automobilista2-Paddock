using CrewChiefV4.Audio;
using CrewChiefV4.GameState;
using CrewChiefV4.NumberProcessing;
using CrewChiefV4.R3E;

using System;
using System.Collections.Generic;
using System.Linq;

namespace CrewChiefV4.Events
{
    public abstract partial class AbstractEvent
    {
        // Online only messages for cases where an opponent has a poor reputation
        private const String folderOpponentAheadBadReputation = "timings/opponent_ahead_has_bad_reputation";
        private const String folderOpponentAheadSketchyReputation = "timings/opponent_ahead_has_below_average_reputation";
        private const String folderOpponentBehindBadReputation = "timings/opponent_behind_has_bad_reputation";
        private const String folderOpponentBehindSketchyReputation = "timings/opponent_behind_has_below_average_reputation";

        // R3E reputation thresholds, to be refined
        private const float r3eBadReputationThreshold = 65;
        private const float r3eSketchyReputationThreshold = 78;
        private const int minRacesForReputationToBeInteresting = 7;

        protected readonly bool iRacingReputations = UserSettings.GetUserSettings().getBoolean("iracing_reputations");
        protected readonly string iRacingClubReputationsBadRaw = UserSettings.GetUserSettings().getString("iracing_reputations_flair_bad");
        protected readonly string iRacingClubReputationsGoodRaw = UserSettings.GetUserSettings().getString("iracing_reputations_flair_good");
        protected readonly string iRacingMinRatingRaw = UserSettings.GetUserSettings().getString("iracing_reputations_ratings");
        private readonly int iRacingMinDivision = UserSettings.GetUserSettings().getInt("iracing_reputations_division");
        private readonly float iRacingSafetyRelative = UserSettings.GetUserSettings().getFloat("iracing_reputations_safety");
        // Language note: these have to be static to make them unique,
        // otherwise each belongs to the class that inherits them
        protected static HashSet<string> iRacingBadClubs = new HashSet<string>();
        protected static HashSet<string> iRacingOkClubs = new HashSet<string>();
        protected static List<int> iRacingBadDrivers = new List<int>();
        protected static int iRacingMinRating = 0;

        protected static HashSet<string> driverReputationWarningChecksInThisSession = new HashSet<string>();

        // it is unfortunate that the ahead/behind is embedded into the voice sounds...
        //
        // "short_form" was patched in later and requires users to manually the sound pack update. It gives short words like "bad rep"
        // that can be used as a prefix to the user's name.
        protected List<MessageFragment> MkFreshReputationAdvice(OpponentData opponent, Boolean opponentIsAhead, Boolean short_form = false)
        {
            var message = new List<MessageFragment>();
            if (!Game.RACE_ROOM && !Game.IRACING)
            {
                return message;
            }
            // we should really only do this once we know the message has been heard, but we have no way of getting
            // that feedback with the current architecture. Only calls to MkReputationAdvice will have this message
            // de-duped, so only use MkFreshReputationAdvice sparingly.
            driverReputationWarningChecksInThisSession.Add(opponent.DriverRawName);

            bool bad_rep = false;
            bool sketchy_rep = false;

            switch (Game.game)
            {
                case GameEnum.RACE_ROOM:
                    if (opponent.r3eUserId != -1)
                    {
                        R3ERatingData opponentRating = R3ERatings.getRatingForUserId(opponent.r3eUserId);
                        if (opponentRating != null && opponentRating.reputation > 0 && opponentRating.racesCompleted > minRacesForReputationToBeInteresting)
                        {
                            bad_rep = opponentRating.reputation < r3eBadReputationThreshold;
                            sketchy_rep = opponentRating.reputation < r3eSketchyReputationThreshold;
                        }
                    }
                    break;
                case GameEnum.IRACING:
                    if (iRacingReputations && opponent.CostId > 0)
                    {
                        // delayed so we don't parse on every tick of the telemetry
                        int division = -1;
                        if (opponent.iDiv != null && opponent.iDiv.Length > 0)
                        {
                            if (opponent.iDiv.Equals("Rookie"))
                            {
                                division = 11;
                            }
                            else try
                            {
                                division = Int32.Parse(opponent.iDiv.Split(' ').Last());
                            }
                            catch (Exception e)
                            {
                            }
                        }

                        var my_safety = CrewChief.currentGameState.SessionData.SafetyRating();
                        Log.Debug(() => $"iRacing Reputation check for {opponent.DriverRawName} ({opponent.CostId}) '{opponent.iFlair}' in division {division} with rating {opponent.iRating}");
                        sketchy_rep = (iRacingMinRating > 0 && opponent.iRating > 0 && opponent.iRating < iRacingMinRating) ||
                                      (iRacingMinDivision > 0 && division > 0 && division > iRacingMinDivision) ||
                                      (opponent.iFlair != null && iRacingOkClubs.Count > 0 && !iRacingOkClubs.Contains(opponent.iFlair.ToLower()));

                        bad_rep = iRacingBadDrivers.Contains(opponent.CostId) ||
                                  (iRacingSafetyRelative > 0 && my_safety - opponent.SafetyRating() >= iRacingSafetyRelative) ||
                                  (opponent.iFlair != null && iRacingBadClubs.Contains(opponent.iFlair.ToLower()));
                    }
                    break;
            }

            if (bad_rep)
            {
                Log.Debug(() => "Warning about bad driver reputation for " + opponent.DriverRawName);
                if (short_form)
                {
                    message.Add(MessageFragment.Text("timings/bad_reputation"));
                }
                else
                {
                    message.AddRange(MessageContents(Pause(500), opponentIsAhead ? folderOpponentAheadBadReputation : folderOpponentBehindBadReputation));
                }
            }
            else if (sketchy_rep)
            {
                Log.Debug(() => "Warning about sketchy driver reputation for " + opponent.DriverRawName);
                if (short_form)
                {
                    message.Add(MessageFragment.Text("timings/below_average_reputation"));
                }
                else
                {
                    message.AddRange(MessageContents(Pause(500), opponentIsAhead ? folderOpponentAheadSketchyReputation : folderOpponentBehindSketchyReputation));
                }
            }

            return message;
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
        //
        // includeLapInfo allows the lap diff information to be excluded if it is obvious from the context, e.g. in calls about faster cars
        // coming from behind to lap the driver or gaps to multiclass cars generally.
        //
        // If this API is too complex to use, a more convenience wrapper is available which takes OpponentData as input and makes sensible
        // decisions for most cases. However, many callers have already obtained lapDifference / timeDelta and may wish to make use of it.
        protected static List<MessageFragment> MkOpponentDelta(
            int lapDifference,
            float timeDelta,
            int expectedDeltaSign,
            bool includeLapInfo)
        {
            var message = new List<MessageFragment>();
            message.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(Math.Abs(timeDelta), Precision.AUTO_GAPS)));

            if (timeDelta < 0 && expectedDeltaSign >= 0)
            {
                message.Add(MessageFragment.Text(Position.folderAhead));
            }
            else if (timeDelta > 0 && expectedDeltaSign <= 0)
            {
                message.Add(MessageFragment.Text(Position.folderBehind));
            }

            if (!includeLapInfo)
            {
                return message;
            }

            message.AddRange(MkLapDifferenceMessage(lapDifference));

            return message;
        }

        protected static List<MessageFragment> MkLapDifferenceMessage(int lapDifference)
        {
            var message = new List<MessageFragment>();

            if (lapDifference == 1)
            {
                message.Add(MessageFragment.Text(Opponents.folderOneLapBehind));
            }
            else if (lapDifference > 1)
            {
                message.Add(MessageFragment.Integer(lapDifference, MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)));
                message.Add(MessageFragment.Text(Position.folderLapsBehind));
            }
            else if (lapDifference == -1)
            {
                message.Add(MessageFragment.Text(Opponents.folderOneLapAhead));
            }
            else if (lapDifference < -1)
            {
                message.Add(MessageFragment.Integer(Math.Abs(lapDifference), MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)));
                message.Add(MessageFragment.Text(Position.folderLapsAhead));
            }

            return message;
        }
    }
}
