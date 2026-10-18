using System;
using System.Collections.Generic;
namespace CrewChiefV4.GameState {
    public enum FlagEnum
    {
        // note that chequered isn't used at the moment
        GREEN, YELLOW, DOUBLE_YELLOW, BLUE, WHITE, BLACK, CHEQUERED, UNKNOWN, RED, RED_YELLOW /* red not used yet*/
    }

    public enum FullCourseYellowPhase
    {
        PENDING, IN_PROGRESS, PITS_CLOSED, PITS_OPEN_LEAD_LAP_VEHICLES, PITS_OPEN, LAST_LAP_NEXT, LAST_LAP_CURRENT, RACING
    }

    public enum PassAllowedUnderYellow
    {
        YES, NO, NO_DATA
    }

    public enum StockCarRule
    {
        NONE,
        LUCKY_DOG_PASS_ON_OUTSIDE,
        LUCKY_DOG_ALLOW_TO_PASS_ON_OUTSIDE,
        MOVE_CHOOSE_LANE,
        WAVE_AROUND_CATCH_END_OF_FIELD,
        TWO_TO_GREEN,
        TWO_TO_GREEN_REMIND_LUCKY_DOG,
        PENALTY_EOLL,
        REMIND_LUCKY_DOG,
        LEADER_CHOOSE_LANE,
        LUCKY_DOG_PASS_ON_LEFT,  // Player's LD
        LUCKY_DOG_ALLOW_TO_PASS_ON_LEFT,  // Opponent's LD
        NEW_LUCKY_DOG,
        MOVE_TO_EOLL,
        WAVE_AROUND_PASS_ON_RIGHT  // Or left??
    }

    public class FlagData
    {
        // holds newer (AMS, RF2 & Raceroom) flag data. This is game dependent - only AMS, RF2 and R3E will use this.
        private FlagEnum[] _sectorFlags;
        public FlagEnum[] sectorFlags {
            get
            {
                if (_sectorFlags == null)
                {
                    _sectorFlags = new FlagEnum[] { FlagEnum.GREEN, FlagEnum.GREEN, FlagEnum.GREEN };
                }
                return _sectorFlags;
            }
        }
        public Boolean isFullCourseYellow; // FCY rules apply, no other announcements
        public Boolean isLocalYellow;  // local yellow - no overtaking, slow down
        // note that for RaceRoom we might have to calculate this. < 0 means we've passed the incident.
        public float distanceToNearestIncident = -1;
        public FullCourseYellowPhase fcyPhase = FullCourseYellowPhase.RACING;
        public Boolean currentLapIsFCY;
        public Boolean previousLapWasFCY;
        public int lapCountWhenLastWentGreen = -1;
        // cars passed under yellow - need to give back this many places to avoid penalty (only implemented for R3E)
        public int numCarsPassedIllegally = 0;
        public PassAllowedUnderYellow canOvertakeCarInFront = PassAllowedUnderYellow.NO_DATA;

        // bit of a hack... allow the mapper to decide which flag implemenation to use for yellow calls
        // as this is game dependent and option dependent (i.e. R3E players may have 'full flag rules' off)
        public Boolean useImprovisedIncidentCalling = true;
    }

    public class StockCarRulesData
    {
        public StockCarRule stockCarRuleApplicable = StockCarRule.NONE;
        public String luckyDogNameRaw;
        public String luckyDogNumber = "-1";
        public Boolean stockCarRulesEnabled;
    }

    public partial class GameStateData {
        public string getOpponentKeyBehindOnTrack(Boolean onlyIncludeCarsLappingThePlayer, CarData.CarClass onlyIncludeClass = null)
        {
            string opponentKeyClosestBehind = null;
            string opponentKeyFurthestInFront = null;
            float closestDistanceBehind = SessionData.TrackDefinition.trackLength;
            float furthestDistanceInFront = 0.0f;
            foreach (var opponent in OpponentData)
            {
                if (onlyIncludeClass != null && !CarData.IsCarClassEqual(onlyIncludeClass, opponent.Value.CarClass))
                {
                    continue;
                }
                if (onlyIncludeCarsLappingThePlayer && opponent.Value.ClassPosition > SessionData.ClassPosition)
                {
                    // we're ahead of this car in the race and are only interested in cars lapping us, so ignore him
                    continue;
                }
                if (opponent.Value.Speed > 0.5 && !opponent.Value.isEnteringPits())
                {
                    if (PositionAndMotionData.DistanceRoundTrack > opponent.Value.DistanceRoundTrack &&
                        PositionAndMotionData.DistanceRoundTrack - opponent.Value.DistanceRoundTrack < closestDistanceBehind)
                    {
                        closestDistanceBehind = PositionAndMotionData.DistanceRoundTrack - opponent.Value.DistanceRoundTrack;
                        opponentKeyClosestBehind = opponent.Key;
                    }
                    else if (PositionAndMotionData.DistanceRoundTrack < opponent.Value.DistanceRoundTrack &&
                        opponent.Value.DistanceRoundTrack - PositionAndMotionData.DistanceRoundTrack > furthestDistanceInFront)
                    {
                        furthestDistanceInFront = opponent.Value.DistanceRoundTrack - PositionAndMotionData.DistanceRoundTrack;
                        opponentKeyFurthestInFront = opponent.Key;
                    }
                }
            }
            if (opponentKeyClosestBehind != null)
                return opponentKeyClosestBehind;
            else
                return opponentKeyFurthestInFront;
        }

    }
}

namespace CrewChiefV4.GameState {
    public enum eFlagColour
    {
      FLAG_COLOUR_NONE = 0,             // Not used for actual flags, only for some query functions
      FLAG_COLOUR_GREEN,                // End of danger zone, or race started
      FLAG_COLOUR_BLUE,                 // Faster car wants to overtake the participant
      FLAG_COLOUR_WHITE_SLOW_CAR,       // Slow car in area
      FLAG_COLOUR_WHITE_FINAL_LAP,      // Final Lap
      FLAG_COLOUR_RED,                  // Huge collisions where one or more cars become wrecked and block the track
      FLAG_COLOUR_YELLOW,               // Danger on the racing surface itself
      FLAG_COLOUR_DOUBLE_YELLOW,        // Danger that wholly or partly blocks the racing surface
      FLAG_COLOUR_BLACK_AND_WHITE,      // Unsportsmanlike conduct
      FLAG_COLOUR_BLACK_ORANGE_CIRCLE,  // Mechanical Failure
      FLAG_COLOUR_BLACK,                // Participant disqualified
      FLAG_COLOUR_CHEQUERED,            // Chequered flag
      //-------------
      FLAG_COLOUR_MAX
    };
}
