using System;
namespace CrewChiefV4.GameState {
    public class PenatiesData
    {
        public Boolean HasDriveThrough;

        public Boolean HasStopAndGo;

        // used for iRacing where we don't know the pit action required to serve the penalty
        public Boolean HasPitStop;

        // iRacing only
        public Boolean HasMeatballFlag;

        public Boolean HasTimeDeduction;

        public Boolean HasSlowDown;

        // Number of outstanding (unserved) penalties pending for the player
        // For some games (e.g. ACC) this will either be 0 (no penalty to serve) or 1 (1 or more to serve).
        // It is *not* a cumulative number of penalties acquired (and potentially served) during a session
        public int NumOutstandingPenalties;

        // Total number of cut track warnings
        public int CutTrackWarnings;

        public Boolean IsOffRacingSurface;

        public Boolean PossibleTrackLimitsViolation;

        // Below fields are one tick triggers.
        public enum DetailedPenaltyType
        {
            NONE,
            STOP_AND_GO,
            DRIVE_THROUGH,
            TEN_SECONDS
        }
        public DetailedPenaltyType PenaltyType = DetailedPenaltyType.NONE;

        public enum DetailedPenaltyCause
        {
            NONE,
            SPEEDING_IN_PITLANE,
            FALSE_START,
            CUT_TRACK,
            EXITING_PITS_UNDER_RED,
            ILLEGAL_PASS_ROLLING_BEFORE_GREEN,
            ILLEGAL_PASS_FCY_BEFORE_GREEN,
            IGNORED_BLUE_FLAG,
            EXCEEDED_SINGLE_DRIVER_STINT_LIMIT,
            EXCEEDED_TOTAL_DRIVER_STINT_LIMIT
        }
        public DetailedPenaltyCause PenaltyCause = DetailedPenaltyCause.NONE;

        public enum WarningMessage
        {
            NONE,
            WRONG_WAY,
            DRIVING_TOO_SLOW,
            HEADLIGHTS_REQUIRED,
            HEADLIGHTS_REQUIRED_WHEN_RAINING,
            ENTER_PITS_TO_AVOID_EXCEEDING_LAPS, // Prac/Quali.
            DISQUALIFIED_DRIVING_WITHOUT_HEADLIGHTS_IN_DARK,
            DISQUALIFIED_DRIVING_WITHOUT_HEADLIGHTS,
            DISQUALIFIED_EXCEEDING_ALLOWED_LAP_COUNT, // Prac/Quali.
            ONE_LAP_TO_SERVE_DRIVE_THROUGH,
            ONE_LAP_TO_SERVE_STOP_AND_GO,
            BLUE_MOVE_OR_BE_PENALIZED,
            DISQUALIFIED_IGNORED_STOP_AND_GO,
            DISQUALIFIED_IGNORED_DRIVE_THROUGH,
            ENTER_PITS_TO_SERVE_PENALTY,
            UNSPORTSMANLIKE_DRIVING,
            POINTS_WILL_BE_AWARDED_THIS_LAP
        }
        public WarningMessage Warning = WarningMessage.NONE;
    }

}
