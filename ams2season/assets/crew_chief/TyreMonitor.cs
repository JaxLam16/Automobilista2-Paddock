using System;
using System.Collections.Generic;
using System.Linq;
using CrewChiefV4.Audio;
using CrewChiefV4.GameState;
using CrewChiefV4.iRacing;
using CrewChiefV4.NumberProcessing;
using CrewChiefV4.UserInterface.TopicWindows;

namespace CrewChiefV4.Events
{
	internal class TyreMonitor : AbstractEvent
	{
		private enum WheelsLockedEnum
		{
			NONE,
			FRONTS,
			LEFT_FRONT,
			RIGHT_FRONT,
			REARS
		}

		private readonly bool delayResponses = UserSettings.GetUserSettings().getBoolean("enable_delayed_responses");

		private readonly bool logStats = UserSettings.GetUserSettings().getBoolean("log_tyre_stats");

		private string folderColdFrontTyres = "tyre_monitor/cold_front_tyres";

		private string folderColdRearTyres = "tyre_monitor/cold_rear_tyres";

		private string folderColdLeftTyres = "tyre_monitor/cold_left_tyres";

		private string folderColdRightTyres = "tyre_monitor/cold_right_tyres";

		public static string folderColdTyresAllRound = "tyre_monitor/cold_tyres_all_round";

		private string folderHotLeftFrontTyre = "tyre_monitor/hot_left_front_tyre";

		private string folderHotLeftRearTyre = "tyre_monitor/hot_left_rear_tyre";

		private string folderHotRightFrontTyre = "tyre_monitor/hot_right_front_tyre";

		private string folderHotRightRearTyre = "tyre_monitor/hot_right_rear_tyre";

		private string folderHotFrontTyres = "tyre_monitor/hot_front_tyres";

		private string folderHotRearTyres = "tyre_monitor/hot_rear_tyres";

		private string folderHotLeftTyres = "tyre_monitor/hot_left_tyres";

		private string folderHotRightTyres = "tyre_monitor/hot_right_tyres";

		private string folderHotTyresAllRound = "tyre_monitor/hot_tyres_all_round";

		public static string folderLeftFront = "tyre_monitor/left_front";

		public static string folderRightFront = "tyre_monitor/right_front";

		public static string folderLeftRear = "tyre_monitor/left_rear";

		public static string folderRightRear = "tyre_monitor/right_rear";

		private string folderCookingLeftFrontTyre = "tyre_monitor/cooking_left_front_tyre";

		private string folderCookingLeftRearTyre = "tyre_monitor/cooking_left_rear_tyre";

		private string folderCookingRightFrontTyre = "tyre_monitor/cooking_right_front_tyre";

		private string folderCookingRightRearTyre = "tyre_monitor/cooking_right_rear_tyre";

		private string folderCookingFrontTyres = "tyre_monitor/cooking_front_tyres";

		private string folderCookingRearTyres = "tyre_monitor/cooking_rear_tyres";

		private string folderCookingLeftTyres = "tyre_monitor/cooking_left_tyres";

		private string folderCookingRightTyres = "tyre_monitor/cooking_right_tyres";

		private string folderCookingTyresAllRound = "tyre_monitor/cooking_tyres_all_round";

		private string folderGoodTyreTemps = "tyre_monitor/good_tyre_temps";

		private string folderColdFrontBrakes = "tyre_monitor/cold_front_brakes";

		private string folderColdRearBrakes = "tyre_monitor/cold_rear_brakes";

		private string folderHotFrontBrakes = "tyre_monitor/hot_front_brakes";

		private string folderHotRearBrakes = "tyre_monitor/hot_rear_brakes";

		private string folderCookingFrontBrakes = "tyre_monitor/hot_front_brakes";

		private string folderCookingRearBrakes = "tyre_monitor/hot_rear_brakes";

		public static string folderColdBrakesAllRound = "tyre_monitor/cold_brakes_all_round";

		private string folderGoodBrakeTemps = "tyre_monitor/good_brake_temps";

		private string folderHotBrakesAllRound = "tyre_monitor/hot_brakes_all_round";

		private string folderCookingBrakesAllRound = "tyre_monitor/cooking_brakes_all_round";

		private string folderKnackeredLeftFront = "tyre_monitor/knackered_left_front";

		private string folderKnackeredLeftRear = "tyre_monitor/knackered_left_rear";

		private string folderKnackeredRightFront = "tyre_monitor/knackered_right_front";

		private string folderKnackeredRightRear = "tyre_monitor/knackered_right_rear";

		private string folderKnackeredFronts = "tyre_monitor/knackered_fronts";

		private string folderKnackeredRears = "tyre_monitor/knackered_rears";

		private string folderKnackeredLefts = "tyre_monitor/knackered_lefts";

		private string folderKnackeredRights = "tyre_monitor/knackered_rights";

		private string folderKnackeredAllRound = "tyre_monitor/knackered_all_round";

		private string folderGoodWear = "tyre_monitor/good_wear";

		private string folderGoodWearGeneral = "tyre_monitor/good_wear_general";

		private string folderMinorWearLeftFront = "tyre_monitor/minor_wear_left_front";

		private string folderMinorWearLeftRear = "tyre_monitor/minor_wear_left_rear";

		private string folderMinorWearRightFront = "tyre_monitor/minor_wear_right_front";

		private string folderMinorWearRightRear = "tyre_monitor/minor_wear_right_rear";

		private string folderMinorWearFronts = "tyre_monitor/minor_wear_fronts";

		private string folderMinorWearRears = "tyre_monitor/minor_wear_rears";

		private string folderMinorWearLefts = "tyre_monitor/minor_wear_lefts";

		private string folderMinorWearRights = "tyre_monitor/minor_wear_rights";

		private string folderMinorWearAllRound = "tyre_monitor/minor_wear_all_round";

		private string folderWornLeftFront = "tyre_monitor/worn_left_front";

		private string folderWornLeftRear = "tyre_monitor/worn_left_rear";

		private string folderWornRightFront = "tyre_monitor/worn_right_front";

		private string folderWornRightRear = "tyre_monitor/worn_right_rear";

		private string folderWornFronts = "tyre_monitor/worn_fronts";

		private string folderWornRears = "tyre_monitor/worn_rears";

		private string folderWornLefts = "tyre_monitor/worn_lefts";

		private string folderWornRights = "tyre_monitor/worn_rights";

		private string folderWornAllRound = "tyre_monitor/worn_all_round";

		public static string folderLapsOnCurrentTyresIntro = "tyre_monitor/laps_on_current_tyres_intro";

		public static string folderLapsOnCurrentTyresOutro = "tyre_monitor/laps_on_current_tyres_outro";

		public static string folderMinutesOnCurrentTyresIntro = "tyre_monitor/minutes_on_current_tyres_intro";

		public static string folderMinutesOnCurrentTyresOutro = "tyre_monitor/minutes_on_current_tyres_outro";

		public static string folderLockingFrontsForLapWarning = "tyre_monitor/locking_fronts_lap_warning";

		public static string folderLockingRearsForLapWarning = "tyre_monitor/locking_rears_lap_warning";

		public static string folderLockingLeftFrontForLapWarning = "tyre_monitor/locking_left_front_lap_warning";

		public static string folderLockingRightFrontForLapWarning = "tyre_monitor/locking_right_front_lap_warning";

		public static string folderLockingLeftRearForLapWarning = "tyre_monitor/locking_left_rear_lap_warning";

		public static string folderLockingRightRearForLapWarning = "tyre_monitor/locking_right_rear_lap_warning";

		public static string folderSpinningFrontsForLapWarning = "tyre_monitor/spinning_fronts_lap_warning";

		public static string folderSpinningRearsForLapWarning = "tyre_monitor/spinning_rears_lap_warning";

		public static string folderSpinningLeftFrontForLapWarning = "tyre_monitor/spinning_left_front_lap_warning";

		public static string folderSpinningRightFrontForLapWarning = "tyre_monitor/spinning_right_front_lap_warning";

		public static string folderSpinningLeftRearForLapWarning = "tyre_monitor/spinning_left_rear_lap_warning";

		public static string folderSpinningRightRearForLapWarning = "tyre_monitor/spinning_right_rear_lap_warning";

		public static string folderDamageToFrontTyres = "tyre_monitor/damage_to_front_tyres";

		public static string folderDamageToRearTyres = "tyre_monitor/damage_to_rear_tyres";

		public static string folderDamageToFrontLeftTyre = "tyre_monitor/damage_to_front_left_tyre";

		public static string folderDamageToFrontRightTyre = "tyre_monitor/damage_to_front_right_tyre";

		public static string folderDamageToRearLeftTyre = "tyre_monitor/damage_to_rear_left_tyre";

		public static string folderDamageToRearRightTyre = "tyre_monitor/damage_to_rear_right_tyre";

		public static string folderFrontsFlatSpotted = "tyre_monitor/fronts_are_flat_spotted";

		public static string folderRearsFlatSpotted = "tyre_monitor/rears_are_flat_spotted";

		public static string folderLeftFrontFlatSpotted = "tyre_monitor/left_front_is_flat_spotted";

		public static string folderRightFrontFlatSpotted = "tyre_monitor/right_front_is_flat_spotted";

		public static string folderLeftRearFlatSpotted = "tyre_monitor/left_rear_is_flat_spotted";

		public static string folderRightRearFlatSpotted = "tyre_monitor/right_rear_is_flat_spotted";

		public static string folderAllTyresDirty = "tyre_monitor/all_tyres_dirty";

		public static string folderLeftTyresDirty = "tyre_monitor/left_tyres_dirty";

		public static string folderRightTyresDirty = "tyre_monitor/right_tyres_dirty";

		private bool enableTyreTempWarnings = UserSettings.GetUserSettings().getBoolean("enable_tyre_temp_warnings");

		private bool enableBrakeTempWarnings = UserSettings.GetUserSettings().getBoolean("enable_brake_temp_warnings");

		private bool enableTyreWearWarnings = UserSettings.GetUserSettings().getBoolean("enable_tyre_wear_warnings");

		private readonly bool enableTyreDirtPickupWarnings = UserSettings.GetUserSettings().getBoolean("enable_tyre_dirt_pickup_warnings");

		private bool enableWheelSpinWarnings = UserSettings.GetUserSettings().getBoolean("enable_wheel_spin_warnings");

		private bool enableBrakeLockWarnings = UserSettings.GetUserSettings().getBoolean("enable_brake_lock_warnings");

		private readonly float initialTotalLapLockupThreshold = UserSettings.GetUserSettings().getFloat("cumulative_lap_lockup_warning_threshold");

		private readonly float initialTotalWheelspinThreshold = UserSettings.GetUserSettings().getFloat("cumulative_lap_wheelspin_warning_threshold");

		private static string folderSpinningLeftFrontForCornerWarning = "tyre_monitor/spinning_left_front_corner_warning";

		private static string folderSpinningRightFrontForCornerWarning = "tyre_monitor/spinning_right_front_corner_warning";

		private static string folderSpinningFrontsForCornerWarning = "tyre_monitor/spinning_fronts_corner_warning";

		private static string folderSpinningLeftRearForCornerWarning = "tyre_monitor/spinning_left_rear_corner_warning";

		private static string folderSpinningRightRearForCornerWarning = "tyre_monitor/spinning_right_rear_corner_warning";

		private static string folderSpinningRearsForCornerWarning = "tyre_monitor/spinning_rears_corner_warning";

		private static string folderLockingLeftFrontForCornerWarning = "tyre_monitor/locking_left_front_corner_warning";

		private static string folderLockingRightFrontForCornerWarning = "tyre_monitor/locking_right_front_corner_warning";

		private static string folderLockingFrontsForCornerWarning = "tyre_monitor/locking_fronts_corner_warning";

		private static string folderLockingRearsForCornerWarning = "tyre_monitor/locking_rears_corner_warning";

		public static string folderHardTyres = "tyre_monitor/hards";

		public static string folderMediumTyres = "tyre_monitor/mediums";

		public static string folderSoftTyres = "tyre_monitor/softs";

		public static string folderSuperSoftTyres = "tyre_monitor/super_softs";

		public static string folderUltraSoftTyres = "tyre_monitor/ultra_softs";

		public static string folderHyperSoftTyres = "tyre_monitor/hyper_softs";

		public static string folderPrimaryTyres = "tyre_monitor/primaries";

		public static string folderAlternateTyres = "tyre_monitor/alternates";

		public static string folderPrimeTyres = "tyre_monitor/primes";

		public static string folderOptionTyres = "tyre_monitor/options";

		public static string folderWetTyres = "tyre_monitor/wets";

		public static string folderIntermediateTyres = "tyre_monitor/intermediates";

		public static string folderSlickTyres = "tyre_monitor/slicks";

		public static string folderAreAbout = "tyre_monitor/are_about";

		public static string folderFasterThan = "tyre_monitor/faster_than";

		public static string folderAverageFrontsIMOSame = "tyre_monitor/average_front_inner_and_outer_same";

		public static string folderAverageRearsIMOSame = "tyre_monitor/average_rear_inner_and_outer_same";

		public static string folderAverageFrontInnerTempsIntro = "tyre_monitor/average_front_inner_temps_are";

		public static string folderAverageRearInnerTempsIntro = "tyre_monitor/average_rear_inner_temps_are";

		public static string folderCelsiusColderThanOuter = "tyre_monitor/celsius_colder_than_outer";

		public static string folderCelsiusColderThanOuters = "tyre_monitor/celsius_colder_than_outers";

		public static string folderCelsiusHotterThanOuter = "tyre_monitor/celsius_hotter_than_outer";

		public static string folderCelsiusHotterThanOuters = "tyre_monitor/celsius_hotter_than_outers";

		public static string folderLFIMOSame = "tyre_monitor/lf_inner_and_outer_are_same";

		public static string folderRFIMOSame = "tyre_monitor/rf_inner_and_outer_are_same";

		public static string folderLRIMOSame = "tyre_monitor/lr_inner_and_outer_are_same";

		public static string folderRRIMOSame = "tyre_monitor/rr_inner_and_outer_are_same";

		public static string folderLFInnerIsRunning = "tyre_monitor/lf_inner_is_running";

		public static string folderRFInnerIsRunning = "tyre_monitor/rf_inner_is_running";

		public static string folderLRInnerIsRunning = "tyre_monitor/lr_inner_is_running";

		public static string folderRRInnerIsRunning = "tyre_monitor/rr_inner_is_running";

		public static string folderNeedMoreNegativeCamber = "tyre_monitor/you_need_more_negative_camber";

		public static string folderNeedMorePositiveCamber = "tyre_monitor/you_need_more_positive_camber";

		public static string folderNeedMoreNegativeCamberOnFronts = "tyre_monitor/you_need_more_negative_camber_on_fronts";

		public static string folderNeedMorePostiveCamberOnFronts = "tyre_monitor/you_need_more_positive_camber_on_fronts";

		public static string folderNeedMoreNegativeCamberOnRears = "tyre_monitor/you_need_more_negative_camber_on_rears";

		public static string folderNeedMorePostiveCamberOnRears = "tyre_monitor/you_need_more_positive_camber_on_rears";

		public static string folderCamberOK = "tyre_monitor/camber_ok";

		public static string folderLeftFrontPressureVeryHigh = "tyre_monitor/left_front_pressure_very_high";

		public static string folderLeftFrontPressureHigh = "tyre_monitor/left_front_pressure_high";

		public static string folderLeftFrontPressureOK = "tyre_monitor/left_front_pressure_ok";

		public static string folderLeftFrontPressureLow = "tyre_monitor/left_front_pressure_low";

		public static string folderLeftFrontPressureVeryLow = "tyre_monitor/left_front_pressure_very_low";

		public static string folderRightFrontPressureVeryHigh = "tyre_monitor/right_front_pressure_very_high";

		public static string folderRightFrontPressureHigh = "tyre_monitor/right_front_pressure_high";

		public static string folderRightFrontPressureOK = "tyre_monitor/right_front_pressure_ok";

		public static string folderRightFrontPressureLow = "tyre_monitor/right_front_pressure_low";

		public static string folderRightFrontPressureVeryLow = "tyre_monitor/right_front_pressure_very_low";

		public static string folderLeftRearPressureVeryHigh = "tyre_monitor/left_rear_pressure_very_high";

		public static string folderLeftRearPressureHigh = "tyre_monitor/left_rear_pressure_high";

		public static string folderLeftRearPressureOK = "tyre_monitor/left_rear_pressure_ok";

		public static string folderLeftRearPressureLow = "tyre_monitor/left_rear_pressure_low";

		public static string folderLeftRearPressureVeryLow = "tyre_monitor/left_rear_pressure_very_low";

		public static string folderRightRearPressureVeryHigh = "tyre_monitor/right_rear_pressure_very_high";

		public static string folderRightRearPressureHigh = "tyre_monitor/right_rear_pressure_high";

		public static string folderRightRearPressureOK = "tyre_monitor/right_rear_pressure_ok";

		public static string folderRightRearPressureLow = "tyre_monitor/right_rear_pressure_low";

		public static string folderRightRearPressureVeryLow = "tyre_monitor/right_rear_pressure_very_low";

		public static string folderFrontPressuresVeryHigh = "tyre_monitor/front_pressures_very_high";

		public static string folderFrontPressuresHigh = "tyre_monitor/front_pressures_high";

		public static string folderFrontPressuresOK = "tyre_monitor/front_pressures_ok";

		public static string folderFrontPressuresLow = "tyre_monitor/front_pressures_low";

		public static string folderFrontPressuresVeryLow = "tyre_monitor/front_pressures_very_low";

		public static string folderRearPressuresVeryHigh = "tyre_monitor/rear_pressures_very_high";

		public static string folderRearPressuresHigh = "tyre_monitor/rear_pressures_high";

		public static string folderRearPressuresOK = "tyre_monitor/rear_pressures_ok";

		public static string folderRearPressuresLow = "tyre_monitor/rear_pressures_low";

		public static string folderRearPressuresVeryLow = "tyre_monitor/rear_pressures_very_low";

		private float[] defaultTargetIODifference = new float[2] { 3f, 6f };

		private static Dictionary<TyreType, float[]> idealCamberValues = new Dictionary<TyreType, float[]>
		{
			{
				TyreType.R3E_2016_HARD,
				new float[2] { 2f, 4f }
			},
			{
				TyreType.R3E_2016_MEDIUM,
				new float[2] { 2f, 4f }
			},
			{
				TyreType.R3E_2016_SOFT,
				new float[2] { 1f, 3f }
			},
			{
				TyreType.R3E_2017_HARD,
				new float[2] { 4f, 7f }
			},
			{
				TyreType.R3E_2017_MEDIUM,
				new float[2] { 4f, 7f }
			},
			{
				TyreType.R3E_2017_SOFT,
				new float[2] { 3f, 6f }
			},
			{
				TyreType.R3E_2017_F5,
				new float[2] { 3f, 6f }
			},
			{
				TyreType.Medium,
				new float[2] { 4f, 7f }
			},
			{
				TyreType.Soft,
				new float[2] { 3f, 6f }
			},
			{
				TyreType.Super_Soft,
				new float[2] { 3f, 5f }
			},
			{
				TyreType.Hyper_Soft,
				new float[2] { 2f, 4f }
			},
			{
				TyreType.Bias_Ply,
				new float[2] { 2f, 4f }
			}
		};

		private int imoSampleFrequency = 1000;

		private DateTime nextIMOSamplesDue = DateTime.MinValue;

		private LinkedList<float> leftFrontInnerSamples = new LinkedList<float>();

		private LinkedList<float> leftFrontMiddleSamples = new LinkedList<float>();

		private LinkedList<float> leftFrontOuterSamples = new LinkedList<float>();

		private LinkedList<float> rightFrontInnerSamples = new LinkedList<float>();

		private LinkedList<float> rightFrontMiddleSamples = new LinkedList<float>();

		private LinkedList<float> rightFrontOuterSamples = new LinkedList<float>();

		private LinkedList<float> leftRearInnerSamples = new LinkedList<float>();

		private LinkedList<float> leftRearMiddleSamples = new LinkedList<float>();

		private LinkedList<float> leftRearOuterSamples = new LinkedList<float>();

		private LinkedList<float> rightRearInnerSamples = new LinkedList<float>();

		private LinkedList<float> rightRearMiddleSamples = new LinkedList<float>();

		private LinkedList<float> rightRearOuterSamples = new LinkedList<float>();

		private float[] leftFrontAverageIMOLastLap;

		private float[] rightFrontAverageIMOLastLap;

		private float[] leftRearAverageIMOLastLap;

		private float[] rightRearAverageIMOLastLap;

		private LinkedList<float> leftFrontPressureSamples = new LinkedList<float>();

		private LinkedList<float> rightFrontPressureSamples = new LinkedList<float>();

		private LinkedList<float> leftRearPressureSamples = new LinkedList<float>();

		private LinkedList<float> rightRearPressureSamples = new LinkedList<float>();

		private float leftFrontAveragePressureLastLap;

		private float rightFrontAveragePressureLastLap;

		private float leftRearAveragePressureLastLap;

		private float rightRearAveragePressureLastLap;

		private int lapsIntoSessionBeforeTempMessage = 2;

		private int checkBrakesAtSector = 3;

		private float lastBrakeTempCheckSessionTime = -1f;

		private float secondsBetweenBrakeTempCheck = 120f;

		private bool reportedTyreWearForCurrentPitEntry;

		private bool reportedEstimatedTimeLeftOneThirdWear;

		private bool reportedEstimatedTimeLeftTwoThirdsWear;

		private float leftFrontWearPercent;

		private float rightFrontWearPercent;

		private float leftRearWearPercent;

		private float rightRearWearPercent;

		private int completedLaps;

		private int lapsInSession;

		private float timeInSession;

		private float timeElapsed;

		private CornerData currentTyreConditionStatus;

		private CornerData currentTyreFlatSpotStatus;

		private CornerData currentTyreDirtPickupStatus;

		private CornerData.Corners lastDirtPickupCorners = CornerData.Corners.NONE;

		private bool waitingForDirtPickupToStabilize;

		private DateTime timeWaitForDirtPickupStarted = DateTime.MinValue;

		private DateTime timeLastDirtPickupMessagePlayed = DateTime.MinValue;

		private CornerData currentTyreTempStatus;

		private CornerData currentBrakeTempStatus;

		private CornerData peakBrakeTempStatus;

		private int lapsBetweenBrakeTempChecks = 1;

		private int lastBrakeTempCheckLap;

		private int lapsBetweenTyreTempChecks = 1;

		private int lastTyreTempCheckLap;

		private List<List<MessageFragment>> tyreTempMessagesPlayed = new List<List<MessageFragment>>();

		private List<List<MessageFragment>> brakeTempMessagesPlayed = new List<List<MessageFragment>>();

		private List<MessageFragment> lastTyreConditionMessage;

		private float peakBrakeTempForLap;

		private float timeLeftFrontIsLockedForLap;

		private float timeRightFrontIsLockedForLap;

		private float timeLeftRearIsLockedForLap;

		private float timeRightRearIsLockedForLap;

		private float timeBothRearsAreLockedForLap;

		private float timeLeftFrontIsSpinningForLap;

		private float timeRightFrontIsSpinningForLap;

		private float timeLeftRearIsSpinningForLap;

		private float timeRightRearIsSpinningForLap;

		private readonly int tickMillis = UserSettings.GetUserSettings().getInt("update_interval");

		private int lockedTicksThreshold = 5;

		private float cornerEntryLockThreshold = 0.25f;

		private int ticksToCheckForLocking = 30;

		private float cornerExitSpinningThreshold = 0.3f;

		private List<bool> leftFrontLockedList = new List<bool>();

		private List<bool> rightFrontLockedList = new List<bool>();

		private List<bool> leftRearLockedList = new List<bool>();

		private List<bool> rightRearLockedList = new List<bool>();

		private string currentCornerName;

		private TimeSpan cornerLockWarningMaxFrequency = TimeSpan.FromSeconds(180.0);

		private TimeSpan cornerSpinningWarningMaxFrequency = TimeSpan.FromSeconds(120.0);

		private Dictionary<string, DateTime> cornerLockWarningsPlayed = new Dictionary<string, DateTime>();

		private Dictionary<string, DateTime> cornerSpinningWarningsPlayed = new Dictionary<string, DateTime>();

		private DateTime nextCornerSpecificSpinningCheck = DateTime.MaxValue;

		private float leftFrontExitStartWheelSpinTime;

		private float rightFrontExitStartWheelSpinTime;

		private float leftRearExitStartWheelSpinTime;

		private float rightRearExitStartWheelSpinTime;

		private bool enableCornerSpecificLockingAndSpinningChecks;

		private float leftFrontTyreTemp;

		private float rightFrontTyreTemp;

		private float leftRearTyreTemp;

		private float rightRearTyreTemp;

		private float leftFrontTyrePressure;

		private float rightFrontTyrePressure;

		private float leftRearTyrePressure;

		private float rightRearTyrePressure;

		private float leftFrontBrakeTemp;

		private float rightFrontBrakeTemp;

		private float leftRearBrakeTemp;

		private float rightRearBrakeTemp;

		private float totalLockupThresholdForNextLap;

		private float totalWheelspinThresholdForNextLap;

		private bool warnedOnLockingForLap;

		private bool warnedOnWheelspinForLap;

		private DateTime nextLockingAndSpinningCheck = DateTime.MinValue;

		private TimeSpan lockingAndSpinningCheckInterval = TimeSpan.FromSeconds(3.0);

		private bool lastBrakeTempCheckOK = true;

		private bool lastTyreTempCheckOK = true;

		private Dictionary<TyreType, float> playerClassSessionBestLapTimeByTyre;

		private int thisLapTyreConditionReportSector = 2;

		private int thisLapTyreTempReportSector = 3;

		private List<double> tyreLifeYPointsTime = new List<double>();

		private List<double> tyreLifeYPointsSectors = new List<double>();

		private List<double> tyreLifeXPointsLFWearBySector = new List<double>();

		private List<double> tyreLifeXPointsLFWearByTime = new List<double>();

		private List<double> tyreLifeXPointsRFWearBySector = new List<double>();

		private List<double> tyreLifeXPointsRFWearByTime = new List<double>();

		private List<double> tyreLifeXPointsLRWearBySector = new List<double>();

		private List<double> tyreLifeXPointsLRWearByTime = new List<double>();

		private List<double> tyreLifeXPointsRRWearBySector = new List<double>();

		private List<double> tyreLifeXPointsRRWearByTime = new List<double>();

		private float lastTyreLifeYPointTime = -1f;

		private CarData.CarClassEnum[] ignoreColdBrakesForClasses = new CarData.CarClassEnum[18]
		{
			CarData.CarClassEnum.FORMULA_E_2018,
			CarData.CarClassEnum.FORMULA_E_2019,
			CarData.CarClassEnum.HISTORIC_TOURING_1,
			CarData.CarClassEnum.HISTORIC_TOURING_2,
			CarData.CarClassEnum.KART_1,
			CarData.CarClassEnum.KART_2,
			CarData.CarClassEnum.KART_F1,
			CarData.CarClassEnum.KART_JUNIOR,
			CarData.CarClassEnum.KART_X30_RENTAL,
			CarData.CarClassEnum.KART_X30_SENIOR,
			CarData.CarClassEnum.NSU_TT,
			CarData.CarClassEnum.ROAD_G,
			CarData.CarClassEnum.ROAD_F,
			CarData.CarClassEnum.ROAD_E,
			CarData.CarClassEnum.VINTAGE_GT_C,
			CarData.CarClassEnum.VINTAGE_GT_D,
			CarData.CarClassEnum.VINTAGE_INDY_65,
			CarData.CarClassEnum.VINTAGE_STOCK_CAR
		};

		private int lapWhenEnteredPits;

		private DateTime timeWhenEnteredPits = DateTime.MinValue;

		private int leftFrontChanged;

		private int rightFrontChanged;

		private int leftRearChanged;

		private int rightRearChanged;

		private static readonly List<SpeechCommands.ID> Commands = new List<SpeechCommands.ID>
		{
			SpeechCommands.ID.CAR_STATUS,
			SpeechCommands.ID.HOWS_MY_FRONT_CAMBER,
			SpeechCommands.ID.HOWS_MY_FRONT_CAMBER_RIGHT_NOW,
			SpeechCommands.ID.HOWS_MY_LEFT_FRONT_CAMBER,
			SpeechCommands.ID.HOWS_MY_LEFT_FRONT_CAMBER_RIGHT_NOW,
			SpeechCommands.ID.HOWS_MY_LEFT_REAR_CAMBER,
			SpeechCommands.ID.HOWS_MY_LEFT_REAR_CAMBER_RIGHT_NOW,
			SpeechCommands.ID.HOWS_MY_REAR_CAMBER,
			SpeechCommands.ID.HOWS_MY_REAR_CAMBER_RIGHT_NOW,
			SpeechCommands.ID.HOWS_MY_RIGHT_FRONT_CAMBER,
			SpeechCommands.ID.HOWS_MY_RIGHT_FRONT_CAMBER_RIGHT_NOW,
			SpeechCommands.ID.HOWS_MY_RIGHT_REAR_CAMBER,
			SpeechCommands.ID.HOWS_MY_RIGHT_REAR_CAMBER_RIGHT_NOW,
			SpeechCommands.ID.HOWS_MY_TYRE_WEAR,
			SpeechCommands.ID.HOW_ARE_MY_BRAKE_TEMPS,
			SpeechCommands.ID.HOW_ARE_MY_FRONT_TYRE_PRESSURES,
			SpeechCommands.ID.HOW_ARE_MY_FRONT_TYRE_PRESSURES_RIGHT_NOW,
			SpeechCommands.ID.HOW_ARE_MY_REAR_TYRE_PRESSURES,
			SpeechCommands.ID.HOW_ARE_MY_REAR_TYRE_PRESSURES_RIGHT_NOW,
			SpeechCommands.ID.HOW_ARE_MY_TYRE_PRESSURES,
			SpeechCommands.ID.HOW_ARE_MY_TYRE_PRESSURES_RIGHT_NOW,
			SpeechCommands.ID.HOW_ARE_MY_TYRE_TEMPS,
			SpeechCommands.ID.HOW_LONG_WILL_THESE_TYRES_LAST,
			SpeechCommands.ID.HOW_MANY_LAPS_ON_TYRE_SET,
			SpeechCommands.ID.HOW_OLD_ARE_THESE_TYRES,
			SpeechCommands.ID.STATUS,
			SpeechCommands.ID.WHAT_ARE_MY_BRAKE_TEMPS,
			SpeechCommands.ID.WHAT_ARE_MY_LEFT_FRONT_SURFACE_TEMPS,
			SpeechCommands.ID.WHAT_ARE_MY_LEFT_REAR_SURFACE_TEMPS,
			SpeechCommands.ID.WHAT_ARE_MY_RIGHT_FRONT_SURFACE_TEMPS,
			SpeechCommands.ID.WHAT_ARE_MY_RIGHT_REAR_SURFACE_TEMPS,
			SpeechCommands.ID.WHAT_ARE_MY_TYRE_PRESSURES,
			SpeechCommands.ID.WHAT_ARE_MY_TYRE_TEMPS,
			SpeechCommands.ID.WHAT_ARE_THE_RELATIVE_TYRE_PERFORMANCES
		};

		public override List<SessionPhase> applicableSessionPhases
		{
			get
			{
				if (Game.IRACING)
				{
					return new List<SessionPhase>
					{
						SessionPhase.Green,
						SessionPhase.FullCourseYellow,
						SessionPhase.Checkered,
						SessionPhase.Finished
					};
				}
				return new List<SessionPhase>
				{
					SessionPhase.Green,
					SessionPhase.Countdown
				};
			}
		}

		public TyreMonitor(AudioPlayer audioPlayer)
		{
			base.audioPlayer = audioPlayer;
			totalLockupThresholdForNextLap = initialTotalLapLockupThreshold;
			totalWheelspinThresholdForNextLap = initialTotalWheelspinThreshold;
		}

		public static string getFolderForTyreType(TyreType tyreType)
		{
			switch (tyreType)
			{
			case TyreType.Hyper_Soft:
				return folderHyperSoftTyres;
			case TyreType.Ultra_Soft:
				return folderUltraSoftTyres;
			case TyreType.Super_Soft:
				return folderSuperSoftTyres;
			case TyreType.Soft:
			case TyreType.R3E_2017_SOFT:
			case TyreType.R3E_2016_SOFT:
				return folderSoftTyres;
			case TyreType.Medium:
			case TyreType.R3E_2017_MEDIUM:
			case TyreType.R3E_2016_MEDIUM:
				return folderMediumTyres;
			case TyreType.Hard:
			case TyreType.R3E_2017_HARD:
			case TyreType.R3E_2016_HARD:
				return folderHardTyres;
			case TyreType.Primary:
				return folderPrimaryTyres;
			case TyreType.Alternate:
				return folderAlternateTyres;
			case TyreType.Prime:
				return folderPrimeTyres;
			case TyreType.Option:
				return folderOptionTyres;
			case TyreType.Wet:
				return folderWetTyres;
			case TyreType.Intermediate:
				return folderIntermediateTyres;
			default:
				return folderSlickTyres;
			}
		}

		public override void clearState()
		{
			reportedTyreWearForCurrentPitEntry = false;
			reportedEstimatedTimeLeftOneThirdWear = false;
			reportedEstimatedTimeLeftTwoThirdsWear = false;
			leftFrontWearPercent = 0f;
			leftRearWearPercent = 0f;
			rightFrontWearPercent = 0f;
			rightRearWearPercent = 0f;
			completedLaps = 0;
			lapsInSession = 0;
			timeInSession = 0f;
			timeElapsed = 0f;
			currentTyreConditionStatus = new CornerData();
			currentTyreFlatSpotStatus = new CornerData();
			currentTyreDirtPickupStatus = new CornerData();
			lastDirtPickupCorners = CornerData.Corners.NONE;
			waitingForDirtPickupToStabilize = false;
			timeWaitForDirtPickupStarted = DateTime.MinValue;
			timeLastDirtPickupMessagePlayed = DateTime.MinValue;
			currentTyreTempStatus = new CornerData();
			currentBrakeTempStatus = new CornerData();
			peakBrakeTempStatus = new CornerData();
			tyreTempMessagesPlayed.Clear();
			brakeTempMessagesPlayed.Clear();
			lapsBetweenBrakeTempChecks = 1;
			lastBrakeTempCheckLap = 0;
			lapsBetweenTyreTempChecks = 1;
			lastTyreTempCheckLap = 0;
			lastTyreConditionMessage = null;
			peakBrakeTempForLap = 0f;
			timeLeftFrontIsLockedForLap = 0f;
			timeRightFrontIsLockedForLap = 0f;
			timeLeftRearIsLockedForLap = 0f;
			timeRightRearIsLockedForLap = 0f;
			timeBothRearsAreLockedForLap = 0f;
			timeLeftFrontIsSpinningForLap = 0f;
			timeRightFrontIsSpinningForLap = 0f;
			timeLeftRearIsSpinningForLap = 0f;
			timeRightRearIsSpinningForLap = 0f;
			totalLockupThresholdForNextLap = initialTotalLapLockupThreshold;
			totalWheelspinThresholdForNextLap = initialTotalWheelspinThreshold;
			warnedOnLockingForLap = false;
			warnedOnWheelspinForLap = false;
			nextLockingAndSpinningCheck = DateTime.MinValue;
			secondsBetweenBrakeTempCheck = 120f;
			leftFrontTyreTemp = 0f;
			rightFrontTyreTemp = 0f;
			leftRearTyreTemp = 0f;
			rightRearTyreTemp = 0f;
			leftFrontTyrePressure = 0f;
			rightFrontTyrePressure = 0f;
			leftRearTyrePressure = 0f;
			rightRearTyrePressure = 0f;
			leftFrontBrakeTemp = 0f;
			rightFrontBrakeTemp = 0f;
			leftRearBrakeTemp = 0f;
			rightRearBrakeTemp = 0f;
			lastBrakeTempCheckOK = true;
			lastTyreTempCheckOK = true;
			lockedTicksThreshold = ((tickMillis == 0) ? 5 : ((int)Math.Ceiling(cornerEntryLockThreshold / ((float)tickMillis / 1000f))));
			ticksToCheckForLocking = ((tickMillis == 0) ? 30 : ((int)Math.Ceiling(3f / ((float)tickMillis / 1000f))));
			leftFrontLockedList.Clear();
			rightFrontLockedList.Clear();
			leftRearLockedList.Clear();
			rightRearLockedList.Clear();
			nextCornerSpecificSpinningCheck = DateTime.MaxValue;
			leftFrontExitStartWheelSpinTime = 0f;
			rightFrontExitStartWheelSpinTime = 0f;
			leftRearExitStartWheelSpinTime = 0f;
			rightRearExitStartWheelSpinTime = 0f;
			cornerLockWarningsPlayed.Clear();
			cornerSpinningWarningsPlayed.Clear();
			currentCornerName = null;
			enableCornerSpecificLockingAndSpinningChecks = false;
			playerClassSessionBestLapTimeByTyre = null;
			lastBrakeTempCheckSessionTime = -1f;
			tyreLifeYPointsTime.Clear();
			tyreLifeYPointsSectors.Clear();
			tyreLifeXPointsLFWearBySector.Clear();
			tyreLifeXPointsRFWearBySector.Clear();
			tyreLifeXPointsLRWearBySector.Clear();
			tyreLifeXPointsRRWearBySector.Clear();
			tyreLifeXPointsLFWearByTime.Clear();
			tyreLifeXPointsRFWearByTime.Clear();
			tyreLifeXPointsLRWearByTime.Clear();
			tyreLifeXPointsRRWearByTime.Clear();
			lastTyreLifeYPointTime = -1f;
			leftFrontInnerSamples.Clear();
			leftFrontMiddleSamples.Clear();
			leftFrontOuterSamples.Clear();
			rightFrontInnerSamples.Clear();
			rightFrontMiddleSamples.Clear();
			rightFrontOuterSamples.Clear();
			leftRearInnerSamples.Clear();
			leftRearMiddleSamples.Clear();
			leftRearOuterSamples.Clear();
			rightRearInnerSamples.Clear();
			rightRearMiddleSamples.Clear();
			rightRearOuterSamples.Clear();
			leftFrontPressureSamples.Clear();
			rightFrontPressureSamples.Clear();
			leftRearPressureSamples.Clear();
			rightRearPressureSamples.Clear();
			leftFrontAverageIMOLastLap = null;
			rightFrontAverageIMOLastLap = null;
			leftRearAverageIMOLastLap = null;
			rightRearAverageIMOLastLap = null;
			leftFrontAveragePressureLastLap = 0f;
			rightFrontAveragePressureLastLap = 0f;
			leftRearAveragePressureLastLap = 0f;
			rightRearAveragePressureLastLap = 0f;
			lapWhenEnteredPits = 0;
			timeWhenEnteredPits = DateTime.MinValue;
			leftFrontChanged = 0;
			rightFrontChanged = 0;
			leftRearChanged = 0;
			rightRearChanged = 0;
			if (Game.IRACING)
			{
				List<CornerData.EnumWithThresholds> tyreTempThresholds = CarData.getTyreTempThresholds(CarData.getCarClassFromEnum(CarData.CarClassEnum.UNKNOWN_RACE));
				currentTyreTempStatus = CornerData.getCornerData(tyreTempThresholds, 45f, 45f, 45f, 45f);
				currentTyreConditionStatus = CornerData.getCornerData(iRacingGameStateMapper.tyreWearThresholds, 0f, 0f, 0f, 0f);
			}
		}

		private bool isBrakeTempPeakForLap(float leftFront, float rightFront, float leftRear, float rightRear)
		{
			if (leftFront > peakBrakeTempForLap || rightFront > peakBrakeTempForLap || leftRear > peakBrakeTempForLap || rightRear > peakBrakeTempForLap)
			{
				peakBrakeTempForLap = Math.Max(leftFront, Math.Max(rightFront, Math.Max(leftRear, rightRear)));
				return true;
			}
			return false;
		}

		private void logTyreStats(TyreData tyreData, int sectorNumber, int lapNumber)
		{
			Console.WriteLine("-------------------------");
			Console.WriteLine("Lap " + (lapNumber + 1) + " sector " + sectorNumber + " tyre temps, Outer, middle, inner  |------|  inner, middle, outer");
			Console.WriteLine("Fronts:    " + Math.Round(tyreData.FrontLeft_LeftTemp, 2) + ", " + Math.Round(tyreData.FrontLeft_CenterTemp, 2) + ", " + Math.Round(tyreData.FrontLeft_RightTemp, 2) + "  |------|  " + Math.Round(tyreData.FrontRight_LeftTemp, 2) + ", " + Math.Round(tyreData.FrontRight_CenterTemp, 2) + ", " + Math.Round(tyreData.FrontRight_RightTemp, 2));
			Console.WriteLine("Rears:    " + Math.Round(tyreData.RearLeft_LeftTemp, 2) + ", " + Math.Round(tyreData.RearLeft_CenterTemp, 2) + ", " + Math.Round(tyreData.RearLeft_RightTemp, 2) + "  |------|  " + Math.Round(tyreData.RearRight_LeftTemp, 2) + ", " + Math.Round(tyreData.RearRight_CenterTemp, 2) + ", " + Math.Round(tyreData.RearRight_RightTemp, 2));
			Console.WriteLine("-------------------------");
			Console.WriteLine("Peak fronts:    " + Math.Round(tyreData.PeakFrontLeftTemperatureForLap, 2) + "  |------|  " + Math.Round(tyreData.PeakFrontRightTemperatureForLap, 2));
			Console.WriteLine("Peak rears:    " + Math.Round(tyreData.PeakRearLeftTemperatureForLap, 2) + "  |------|  " + Math.Round(tyreData.PeakRearRightTemperatureForLap, 2));
			Console.WriteLine("-------------------------");
			Console.WriteLine("Temperature interpretation:");
			foreach (KeyValuePair<Enum, CornerData.Corners> item in tyreData.TyreTempStatus.cornersForEachStatus)
			{
				KeyValuePair<Enum, CornerData.Corners> keyValuePair = item;
				Console.WriteLine("Status: " + keyValuePair.ToString());
			}
			Console.WriteLine("-------------------------");
			Console.WriteLine("Wear, percentage  |------|  percentage");
			Console.WriteLine("Fronts:    " + Math.Round(tyreData.FrontLeftPercentWear, 2) + "  |------|  " + Math.Round(tyreData.FrontRightPercentWear, 2));
			Console.WriteLine("Rears:    " + Math.Round(tyreData.RearLeftPercentWear, 2) + "  |------|  " + Math.Round(tyreData.RearRightPercentWear, 2));
			Console.WriteLine("-------------------------");
			Console.WriteLine("Wear interpretation:");
			foreach (KeyValuePair<Enum, CornerData.Corners> item2 in tyreData.TyreConditionStatus.cornersForEachStatus)
			{
				KeyValuePair<Enum, CornerData.Corners> keyValuePair = item2;
				Console.WriteLine("Status: " + keyValuePair.ToString());
			}
			Console.WriteLine("-------------------------");
			if (tyreData.FlatSpotEmulationActive)
			{
				Console.WriteLine("-------------------------");
				Console.WriteLine("Flat spot severity, percentage  |------|  percentage");
				Console.WriteLine("Fronts:    " + Math.Round(((double)tyreData.FrontLeftFlatSpotSeverity == -1.0) ? 0.0 : ((double)tyreData.FrontLeftFlatSpotSeverity), 2) + "  |------|  " + Math.Round(((double)tyreData.FrontRightFlatSpotSeverity == -1.0) ? 0.0 : ((double)tyreData.FrontRightFlatSpotSeverity), 2));
				Console.WriteLine("Rears:    " + Math.Round(((double)tyreData.RearLeftFlatSpotSeverity == -1.0) ? 0.0 : ((double)tyreData.RearLeftFlatSpotSeverity), 2) + "  |------|  " + Math.Round(((double)tyreData.RearRightFlatSpotSeverity == -1.0) ? 0.0 : ((double)tyreData.RearRightFlatSpotSeverity), 2));
				Console.WriteLine("-------------------------");
				Console.WriteLine("Flat spot severity interpretation:");
				foreach (KeyValuePair<Enum, CornerData.Corners> item3 in tyreData.TyreFlatSpotStatus.cornersForEachStatus)
				{
					KeyValuePair<Enum, CornerData.Corners> keyValuePair = item3;
					Console.WriteLine("Status: " + keyValuePair.ToString());
				}
				Console.WriteLine("-------------------------");
			}
			if (tyreData.DirtPickupEmulationActive)
			{
				Console.WriteLine("-------------------------");
				Console.WriteLine("Dirt pickup severity, percentage  |------|  percentage");
				Console.WriteLine("Fronts:    " + Math.Round(((double)tyreData.FrontLeftDirtPickupSeverity == -1.0) ? 0.0 : ((double)tyreData.FrontLeftDirtPickupSeverity), 2) + "  |------|  " + Math.Round(((double)tyreData.FrontRightDirtPickupSeverity == -1.0) ? 0.0 : ((double)tyreData.FrontRightDirtPickupSeverity), 2));
				Console.WriteLine("Rears:    " + Math.Round(((double)tyreData.RearLeftDirtPickupSeverity == -1.0) ? 0.0 : ((double)tyreData.RearLeftDirtPickupSeverity), 2) + "  |------|  " + Math.Round(((double)tyreData.RearRightDirtPickupSeverity == -1.0) ? 0.0 : ((double)tyreData.RearRightDirtPickupSeverity), 2));
				Console.WriteLine("-------------------------");
			}
		}

		private void getIMOAndPressureAveragesForLap()
		{
			if (leftFrontInnerSamples.Count > 0 && leftFrontMiddleSamples.Count > 0 && leftFrontOuterSamples.Count > 0)
			{
				leftFrontAverageIMOLastLap = new float[3]
				{
					leftFrontInnerSamples.Average(),
					leftFrontMiddleSamples.Average(),
					leftFrontOuterSamples.Average()
				};
			}
			if (rightFrontInnerSamples.Count > 0 && rightFrontMiddleSamples.Count > 0 && rightFrontOuterSamples.Count > 0)
			{
				rightFrontAverageIMOLastLap = new float[3]
				{
					rightFrontInnerSamples.Average(),
					rightFrontMiddleSamples.Average(),
					rightFrontOuterSamples.Average()
				};
			}
			if (leftRearInnerSamples.Count > 0 && leftRearMiddleSamples.Count > 0 && leftRearOuterSamples.Count > 0)
			{
				leftRearAverageIMOLastLap = new float[3]
				{
					leftRearInnerSamples.Average(),
					leftRearMiddleSamples.Average(),
					leftRearOuterSamples.Average()
				};
			}
			if (rightRearInnerSamples.Count > 0 && rightRearMiddleSamples.Count > 0 && rightRearOuterSamples.Count > 0)
			{
				rightRearAverageIMOLastLap = new float[3]
				{
					rightRearInnerSamples.Average(),
					rightRearMiddleSamples.Average(),
					rightRearOuterSamples.Average()
				};
			}
			if (leftFrontPressureSamples.Count > 0)
			{
				leftFrontAveragePressureLastLap = leftFrontPressureSamples.Average();
			}
			if (rightFrontPressureSamples.Count > 0)
			{
				rightFrontAveragePressureLastLap = rightFrontPressureSamples.Average();
			}
			if (leftRearPressureSamples.Count > 0)
			{
				leftRearAveragePressureLastLap = leftRearPressureSamples.Average();
			}
			if (rightRearPressureSamples.Count > 0)
			{
				rightRearAveragePressureLastLap = rightRearPressureSamples.Average();
			}
		}

		private void clearIMOAndPressureData()
		{
			leftFrontInnerSamples.Clear();
			leftFrontMiddleSamples.Clear();
			leftFrontOuterSamples.Clear();
			rightFrontInnerSamples.Clear();
			rightFrontMiddleSamples.Clear();
			rightFrontOuterSamples.Clear();
			leftRearInnerSamples.Clear();
			leftRearMiddleSamples.Clear();
			leftRearOuterSamples.Clear();
			rightRearInnerSamples.Clear();
			rightRearMiddleSamples.Clear();
			rightRearOuterSamples.Clear();
			leftFrontPressureSamples.Clear();
			rightFrontPressureSamples.Clear();
			leftRearPressureSamples.Clear();
			rightRearPressureSamples.Clear();
		}

		private TyreTemp classifyTyreTemp(float temp, List<CornerData.EnumWithThresholds> thresholds)
		{
			foreach (CornerData.EnumWithThresholds threshold in thresholds)
			{
				if (threshold.e is TyreTemp && temp >= threshold.lowerThreshold && temp < threshold.upperThreshold)
				{
					return (TyreTemp)(object)threshold.e;
				}
			}
			return TyreTemp.WARM;
		}

		private string formatTyreTempThresholds(List<CornerData.EnumWithThresholds> thresholds)
		{
			return string.Join(", ", thresholds.Select((CornerData.EnumWithThresholds threshold) => $"{threshold.e}[{threshold.lowerThreshold:0.0},{threshold.upperThreshold:0.0})"));
		}

		private void triggerInternalIracing(GameStateData previousGameState, GameStateData currentGameState, bool valid_tyre_wear, bool valid_tyre_temp)
		{
			if (currentGameState.PitData.IsInGarage)
			{
				clearState();
				return;
			}
			TyreData tyreData = previousGameState.TyreData;
			TyreData tyreData2 = currentGameState.TyreData;
			bool flag = tyreData.FrontLeftMaxTemp() != tyreData2.FrontLeftMaxTemp() || tyreData.FrontRightMaxTemp() != tyreData2.FrontRightMaxTemp() || tyreData.RearLeftMaxTemp() != tyreData2.RearLeftMaxTemp() || tyreData.RearRightMaxTemp() != tyreData2.RearRightMaxTemp();
			flag = flag && valid_tyre_temp;
			bool flag2 = tyreData.FrontLeftPercentWear != tyreData2.FrontLeftPercentWear || tyreData.FrontRightPercentWear != tyreData2.FrontRightPercentWear || tyreData.RearLeftPercentWear != tyreData2.RearLeftPercentWear || tyreData.RearRightPercentWear != tyreData2.RearRightPercentWear;
			flag2 = flag2 && valid_tyre_wear;
			if (!previousGameState.PitData.InPitlane && currentGameState.PitData.InPitlane)
			{
				lapWhenEnteredPits = currentGameState.SessionData.LapCount;
				timeWhenEnteredPits = currentGameState.Now;
			}
			if (flag)
			{
				leftFrontTyreTemp = tyreData2.FrontLeftMaxTemp();
				rightFrontTyreTemp = tyreData2.FrontRightMaxTemp();
				leftRearTyreTemp = tyreData2.RearLeftMaxTemp();
				rightRearTyreTemp = tyreData2.RearRightMaxTemp();
				Log.Debug(() => $"TYRE_TEMPS = {leftFrontTyreTemp} {rightFrontTyreTemp} {leftRearTyreTemp} {rightRearTyreTemp}");
			}
			if (flag2)
			{
				leftFrontWearPercent = tyreData2.FrontLeftPercentWear;
				rightFrontWearPercent = tyreData2.FrontRightPercentWear;
				leftRearWearPercent = tyreData2.RearLeftPercentWear;
				rightRearWearPercent = tyreData2.RearRightPercentWear;
				Log.Debug(() => $"TYRE_WEAR = {leftFrontWearPercent} {rightFrontWearPercent} {leftRearWearPercent} {rightRearWearPercent}");
			}
			bool flag3 = currentGameState.SessionData.SessionPhase > SessionPhase.FullCourseYellow && previousGameState.PitData.InPitlane;
			bool flag4 = currentGameState.SessionData.SessionPhase <= SessionPhase.FullCourseYellow && currentGameState.SessionData.CompletedLaps >= 1;
			if ((enableTyreWearWarnings || enableTyreTempWarnings) && (flag2 || flag) && (flag4 || flag3))
			{
				if (flag3)
				{
					List<MessageFragment> list = mkDetailedTyreTreadMessage(tyreData2, 5.0);
					if (list.Count > 0 && enableTyreWearWarnings)
					{
						audioPlayer.playMessageImmediately(new QueuedMessage("tyre_wear", 0, list));
					}
					else if (enableTyreTempWarnings && valid_tyre_temp)
					{
						list = mkDetailedTyreTempsMessage(tyreData2);
						if (list.Count > 0)
						{
							audioPlayer.playMessageImmediately(new QueuedMessage("tyre_temps", 0, list));
						}
					}
				}
				else if (valid_tyre_wear && valid_tyre_temp)
				{
					audioPlayer.playMessage(new QueuedMessage("tyre_summary", 10, mkSummaryTyreMessage(tyreData2), null, null, null, 3 + Utilities.random.Next(0, 2)));
				}
			}
			bool flag5 = false;
			if (tyreData2.iRacingChangesPossible)
			{
				if (!tyreData.LeftFrontAttached && tyreData2.LeftFrontAttached)
				{
					Log.Debug("detected tyre change on LF");
					flag5 = true;
					leftFrontChanged = lapWhenEnteredPits;
					leftFrontWearPercent = 0f;
					leftFrontTyreTemp = 45f;
				}
				if (!tyreData.RightFrontAttached && tyreData2.RightFrontAttached)
				{
					Log.Debug("detected tyre change on RF");
					flag5 = true;
					rightFrontChanged = lapWhenEnteredPits;
					rightFrontWearPercent = 0f;
					rightFrontTyreTemp = 45f;
				}
				if (!tyreData.LeftRearAttached && tyreData2.LeftRearAttached)
				{
					Log.Debug("detected tyre change on LR");
					flag5 = true;
					leftRearChanged = lapWhenEnteredPits;
					leftRearWearPercent = 0f;
					leftRearTyreTemp = 45f;
				}
				if (!tyreData.RightRearAttached && tyreData2.RightRearAttached)
				{
					Log.Debug("detected tyre change on RR");
					flag5 = true;
					rightRearChanged = lapWhenEnteredPits;
					rightRearWearPercent = 0f;
					rightRearTyreTemp = 45f;
				}
			}
			if (flag || flag2 || flag5)
			{
				List<CornerData.EnumWithThresholds> tyreTempThresholds = CarData.getTyreTempThresholds(currentGameState.carClass);
				currentTyreTempStatus = CornerData.getCornerData(tyreTempThresholds, leftFrontTyreTemp, rightFrontTyreTemp, leftRearTyreTemp, rightRearTyreTemp);
				currentTyreConditionStatus = CornerData.getCornerData(iRacingGameStateMapper.tyreWearThresholds, leftFrontWearPercent, rightFrontWearPercent, leftRearWearPercent, rightRearWearPercent);
			}
		}

		private List<MessageFragment> mkSummaryTyreMessage(TyreData t)
		{
			List<MessageFragment> list = new List<MessageFragment>();
			if (GlobalBehaviourSettings.useOvalLogic)
			{
				if (t.FrontRightPercentWear < 5f && t.FrontLeftPercentWear < 5f)
				{
					list.AddRange(AbstractEvent.MessageContents(folderRightFront, convertTemp(t.FrontRightMaxTemp())));
					list.AddRange(AbstractEvent.MessageContents(getTempUnit()));
					list.AddRange(AbstractEvent.MessageContents(folderLeftFront, convertTemp(t.FrontLeftMaxTemp())));
					list.AddRange(AbstractEvent.MessageContents(getTempUnit()));
				}
				else
				{
					list.AddRange(AbstractEvent.MessageContents(folderRightFront, (int)((double)(100f - t.FrontRightPercentWear) + 0.5)));
					list.AddRange(AbstractEvent.MessageContents("battery/percent"));
					list.AddRange(AbstractEvent.MessageContents(folderLeftFront, (int)((double)(100f - t.FrontLeftPercentWear) + 0.5)));
					list.AddRange(AbstractEvent.MessageContents("battery/percent"));
				}
			}
			else
			{
				if (t.FrontLeftPercentWear < t.FrontRightPercentWear)
				{
					list.AddRange(AbstractEvent.MessageContents(folderRightFront, (int)((double)(100f - t.FrontRightPercentWear) + 0.5)));
				}
				else
				{
					list.AddRange(AbstractEvent.MessageContents(folderLeftFront, (int)((double)(100f - t.FrontLeftPercentWear) + 0.5)));
				}
				list.AddRange(AbstractEvent.MessageContents("battery/percent"));
				if (t.RearLeftPercentWear < t.RearRightPercentWear)
				{
					list.AddRange(AbstractEvent.MessageContents(folderRightRear, (int)((double)(100f - t.RearRightPercentWear) + 0.5)));
				}
				else
				{
					list.AddRange(AbstractEvent.MessageContents(folderLeftRear, (int)((double)(100f - t.RearLeftPercentWear) + 0.5)));
				}
			}
			return list;
		}

		private List<MessageFragment> mkDetailedTyreTreadMessage(TyreData t, double threshold)
		{
			List<MessageFragment> list = new List<MessageFragment>();
			if ((double)t.FrontLeftPercentWear >= threshold)
			{
				list.AddRange(AbstractEvent.MessageContents(folderLeftFront, (int)((double)(100f - t.FrontLeftPercentWear) + 0.5)));
				list.AddRange(AbstractEvent.MessageContents("battery/percent"));
			}
			if ((double)t.FrontRightPercentWear >= threshold)
			{
				list.AddRange(AbstractEvent.MessageContents(folderRightFront, (int)((double)(100f - t.FrontRightPercentWear) + 0.5)));
				list.AddRange(AbstractEvent.MessageContents("battery/percent"));
			}
			if ((double)t.RearLeftPercentWear >= threshold)
			{
				list.AddRange(AbstractEvent.MessageContents(folderLeftRear, (int)((double)(100f - t.RearLeftPercentWear) + 0.5)));
				list.AddRange(AbstractEvent.MessageContents("battery/percent"));
			}
			if ((double)t.RearRightPercentWear >= threshold)
			{
				list.AddRange(AbstractEvent.MessageContents(folderRightRear, (int)((double)(100f - t.RearRightPercentWear) + 0.5)));
				list.AddRange(AbstractEvent.MessageContents("battery/percent"));
			}
			return list;
		}

		private List<MessageFragment> mkDetailedTyreTempsMessage(TyreData t)
		{
			List<MessageFragment> list = new List<MessageFragment>();
			if (t.FrontLeftMaxTemp() <= 0f && t.FrontRightMaxTemp() <= 0f && t.RearLeftMaxTemp() <= 0f && t.RearRightMaxTemp() <= 0f)
			{
				return list;
			}
			list.AddRange(AbstractEvent.MessageContents(folderLeftFront, convertTemp(t.FrontLeftMaxTemp())));
			list.AddRange(AbstractEvent.MessageContents(getTempUnit()));
			list.AddRange(AbstractEvent.MessageContents(folderRightFront, convertTemp(t.FrontRightMaxTemp())));
			list.AddRange(AbstractEvent.MessageContents(folderLeftRear, convertTemp(t.RearLeftMaxTemp())));
			list.AddRange(AbstractEvent.MessageContents(folderRightRear, convertTemp(t.RearRightMaxTemp())));
			return list;
		}

		private List<MessageFragment> mkTyreAgeMessage(GameStateData currentGameState)
		{
			List<MessageFragment> list = new List<MessageFragment>();
			int num = currentGameState.SessionData.CompletedLaps;
			if (leftFrontChanged > num || rightFrontChanged > num || leftRearChanged > num || rightRearChanged > num)
			{
				return list;
			}
			if (leftFrontChanged == rightFrontChanged && leftFrontChanged == leftRearChanged && leftFrontChanged == rightRearChanged)
			{
				list.AddRange(AbstractEvent.MessageContents(num - leftFrontChanged, Battery.folderLaps));
			}
			else if (GlobalBehaviourSettings.useOvalLogic)
			{
				if (rightFrontChanged == rightRearChanged)
				{
					list.AddRange(AbstractEvent.MessageContents(folderRightFront, folderRightRear, num - rightRearChanged, Battery.folderLaps));
				}
				else
				{
					list.AddRange(AbstractEvent.MessageContents(folderRightFront, num - rightFrontChanged, Battery.folderLaps));
					list.AddRange(AbstractEvent.MessageContents(folderRightRear, num - rightRearChanged, Battery.folderLaps));
				}
				if (leftFrontChanged == leftRearChanged)
				{
					list.AddRange(AbstractEvent.MessageContents(folderLeftFront, folderLeftRear, num - leftRearChanged, Battery.folderLaps));
				}
				else
				{
					list.AddRange(AbstractEvent.MessageContents(folderLeftFront, num - leftFrontChanged, Battery.folderLaps));
					list.AddRange(AbstractEvent.MessageContents(folderLeftRear, num - leftRearChanged, Battery.folderLaps));
				}
			}
			else
			{
				if (leftFrontChanged == rightFrontChanged)
				{
					list.AddRange(AbstractEvent.MessageContents(folderLeftFront, folderRightFront, num - rightFrontChanged, Battery.folderLaps));
				}
				else
				{
					list.AddRange(AbstractEvent.MessageContents(folderLeftFront, num - leftFrontChanged, Battery.folderLaps));
					list.AddRange(AbstractEvent.MessageContents(folderRightFront, num - rightFrontChanged, Battery.folderLaps));
				}
				if (leftRearChanged == rightRearChanged)
				{
					list.AddRange(AbstractEvent.MessageContents(folderLeftRear, folderRightRear, num - rightRearChanged, Battery.folderLaps));
				}
				else
				{
					list.AddRange(AbstractEvent.MessageContents(folderLeftRear, num - leftRearChanged, Battery.folderLaps));
					list.AddRange(AbstractEvent.MessageContents(folderRightRear, num - rightRearChanged, Battery.folderLaps));
				}
			}
			return list;
		}

		private void respondIracing(string voiceMessage, GameStateData currentGameState, SpeechCommands.ID cmd)
		{
			switch (cmd)
			{
			case SpeechCommands.ID.HOW_ARE_MY_TYRE_TEMPS:
			{
				List<MessageFragment> list2 = mkDetailedTyreTempsMessage(currentGameState.TyreData);
				if (list2.Count == 0)
				{
					list2.AddRange(AbstractEvent.MessageContents("acknowledge/no_data"));
				}
				audioPlayer.playMessageImmediately(new QueuedMessage("tyres_temps", 0, list2));
				break;
			}
			case SpeechCommands.ID.HOWS_MY_TYRE_WEAR:
			{
				List<MessageFragment> list3 = mkDetailedTyreTreadMessage(currentGameState.TyreData, 1.0);
				if (list3.Count == 0)
				{
					list3.AddRange(AbstractEvent.MessageContents("acknowledge/no_data"));
				}
				audioPlayer.playMessageImmediately(new QueuedMessage("tyres_tread", 0, list3));
				break;
			}
			case SpeechCommands.ID.HOW_OLD_ARE_THESE_TYRES:
			{
				List<MessageFragment> list = mkTyreAgeMessage(currentGameState);
				if (list.Count == 0)
				{
					list.AddRange(AbstractEvent.MessageContents("acknowledge/no_data"));
				}
				audioPlayer.playMessageImmediately(new QueuedMessage("tyres_age", 0, list));
				break;
			}
			}
		}

		private bool sanityCheck(in float min, in float max, in List<float> values)
		{
			foreach (float value in values)
			{
				if (value < min || value > max)
				{
					return false;
				}
			}
			return true;
		}

		protected override void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
		{
			if (GameStateData.onManualFormationLap || Game.PCARS3)
			{
				return;
			}
			TyreData tyreData = currentGameState.TyreData;
			float min = 0f;
			float max = 100f;
			List<float> values = new List<float> { tyreData.FrontLeftPercentWear, tyreData.FrontRightPercentWear, tyreData.RearLeftPercentWear, tyreData.RearRightPercentWear };
			bool flag = sanityCheck(in min, in max, in values);
			min = 0f;
			max = 200f;
			values = new List<float>
			{
				tyreData.FrontLeft_RightTemp, tyreData.FrontLeft_CenterTemp, tyreData.FrontLeft_LeftTemp, tyreData.FrontRight_LeftTemp, tyreData.FrontRight_CenterTemp, tyreData.FrontRight_RightTemp, tyreData.RearLeft_RightTemp, tyreData.RearLeft_CenterTemp, tyreData.RearLeft_LeftTemp, tyreData.RearRight_LeftTemp,
				tyreData.RearRight_CenterTemp, tyreData.RearRight_RightTemp
			};
			bool flag2 = sanityCheck(in min, in max, in values);
			if (Game.IRACING)
			{
				if (previousGameState != null && currentGameState != null)
				{
					triggerInternalIracing(previousGameState, currentGameState, flag, flag2);
				}
				return;
			}
			playerClassSessionBestLapTimeByTyre = currentGameState.SessionData.PlayerClassSessionBestLapTimeByTyre;
			if (logStats && currentGameState.SessionData.IsNewSector)
			{
				logTyreStats(currentGameState.TyreData, currentGameState.SessionData.SectorNumber, currentGameState.SessionData.CompletedLaps);
			}
			if (currentGameState.SessionData.IsNewLap)
			{
				timeLeftFrontIsLockedForLap = 0f;
				timeRightFrontIsLockedForLap = 0f;
				timeLeftRearIsLockedForLap = 0f;
				timeRightRearIsLockedForLap = 0f;
				timeBothRearsAreLockedForLap = 0f;
				timeLeftFrontIsSpinningForLap = 0f;
				timeRightFrontIsSpinningForLap = 0f;
				timeLeftRearIsSpinningForLap = 0f;
				timeRightRearIsSpinningForLap = 0f;
				leftFrontExitStartWheelSpinTime = 0f;
				rightFrontExitStartWheelSpinTime = 0f;
				leftRearExitStartWheelSpinTime = 0f;
				rightRearExitStartWheelSpinTime = 0f;
				if (warnedOnLockingForLap)
				{
					totalLockupThresholdForNextLap += 1f;
				}
				else
				{
					totalLockupThresholdForNextLap = initialTotalLapLockupThreshold;
				}
				if (warnedOnWheelspinForLap)
				{
					totalWheelspinThresholdForNextLap += 1f;
				}
				else
				{
					totalWheelspinThresholdForNextLap = initialTotalWheelspinThreshold;
				}
				warnedOnLockingForLap = false;
				warnedOnWheelspinForLap = false;
				leftFrontLockedList.Clear();
				rightFrontLockedList.Clear();
				leftRearLockedList.Clear();
				rightRearLockedList.Clear();
				currentCornerName = null;
				enableCornerSpecificLockingAndSpinningChecks = currentGameState.SessionData.TrackDefinition != null && currentGameState.SessionData.TrackDefinition.trackLandmarks != null && currentGameState.SessionData.TrackDefinition.trackLandmarks.Count > 0 && currentGameState.carClass != null && currentGameState.carClass.carClassEnum != CarData.CarClassEnum.KART_1 && currentGameState.carClass.carClassEnum != CarData.CarClassEnum.KART_2 && currentGameState.carClass.carClassEnum != CarData.CarClassEnum.KART_F1 && currentGameState.carClass.carClassEnum != CarData.CarClassEnum.KART_JUNIOR;
				checkBrakesAtSector = Utilities.random.Next(1, 4);
				if (Utilities.random.Next(0, 2) == 0)
				{
					thisLapTyreConditionReportSector = 2;
					thisLapTyreTempReportSector = 3;
				}
				else
				{
					thisLapTyreConditionReportSector = 3;
					thisLapTyreTempReportSector = 2;
				}
				getIMOAndPressureAveragesForLap();
				clearIMOAndPressureData();
			}
			else if (previousGameState != null && previousGameState.PitData.InPitlane && !currentGameState.PitData.InPitlane)
			{
				clearIMOAndPressureData();
			}
			else if (!currentGameState.PitData.InPitlane && currentGameState.PositionAndMotionData.CarSpeed > 10f && currentGameState.Now > nextIMOSamplesDue)
			{
				if (flag2)
				{
					nextIMOSamplesDue = currentGameState.Now.AddMilliseconds(imoSampleFrequency);
					leftFrontInnerSamples.AddLast(currentGameState.TyreData.FrontLeft_RightTemp);
					leftFrontMiddleSamples.AddLast(currentGameState.TyreData.FrontLeft_CenterTemp);
					leftFrontOuterSamples.AddLast(currentGameState.TyreData.FrontLeft_LeftTemp);
					rightFrontInnerSamples.AddLast(currentGameState.TyreData.FrontRight_LeftTemp);
					rightFrontMiddleSamples.AddLast(currentGameState.TyreData.FrontRight_CenterTemp);
					rightFrontOuterSamples.AddLast(currentGameState.TyreData.FrontRight_RightTemp);
					leftRearInnerSamples.AddLast(currentGameState.TyreData.RearLeft_RightTemp);
					leftRearMiddleSamples.AddLast(currentGameState.TyreData.RearLeft_CenterTemp);
					leftRearOuterSamples.AddLast(currentGameState.TyreData.RearLeft_LeftTemp);
					rightRearInnerSamples.AddLast(currentGameState.TyreData.RearRight_LeftTemp);
					rightRearMiddleSamples.AddLast(currentGameState.TyreData.RearRight_CenterTemp);
					rightRearOuterSamples.AddLast(currentGameState.TyreData.RearRight_RightTemp);
				}
				leftFrontPressureSamples.AddLast(currentGameState.TyreData.FrontLeftPressure);
				rightFrontPressureSamples.AddLast(currentGameState.TyreData.FrontRightPressure);
				leftRearPressureSamples.AddLast(currentGameState.TyreData.RearLeftPressure);
				rightRearPressureSamples.AddLast(currentGameState.TyreData.RearRightPressure);
			}
			enableWheelSpinWarnings = enableWheelSpinWarnings && GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.LOCKING_AND_SPINNING);
			enableBrakeLockWarnings = enableBrakeLockWarnings && GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.LOCKING_AND_SPINNING);
			enableTyreWearWarnings = enableTyreWearWarnings && GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.TYRE_WEAR) && !PitStops.isPittingThisLap;
			enableTyreTempWarnings = enableTyreTempWarnings && GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.TYRE_TEMPS) && !PitStops.isPittingThisLap;
			enableBrakeTempWarnings = enableBrakeTempWarnings && GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.BRAKE_TEMPS) && !PitStops.isPittingThisLap;
			if (previousGameState != null && currentGameState.Ticks > previousGameState.Ticks)
			{
				addLockingAndSpinningData(currentGameState.TyreData, currentGameState.PitData.InPitlane, hasWheelMissingOrPuncture(currentGameState), previousGameState.Ticks, currentGameState.Ticks, currentGameState.carClass.allMembersAreFWD);
			}
			bool flag3 = false;
			bool flag4 = false;
			if (currentGameState.Now > nextLockingAndSpinningCheck)
			{
				if (!hasWheelMissingOrPuncture(currentGameState) && !currentGameState.PitData.InPitlane)
				{
					if (enableBrakeLockWarnings)
					{
						flag3 = checkLocking(currentGameState.carClass.allMembersAreFWD);
					}
					if (enableWheelSpinWarnings)
					{
						flag4 = checkWheelSpinning(currentGameState.carClass.allMembersAreFWD, currentGameState.carClass.allMembersAreRWD);
					}
				}
				nextLockingAndSpinningCheck = currentGameState.Now.Add(lockingAndSpinningCheckInterval);
			}
			if (enableCornerSpecificLockingAndSpinningChecks && (currentGameState.SessionData.SessionType != SessionType.Race || currentGameState.SessionData.CompletedLaps > 0 || currentGameState.SessionData.SectorNumber != 1))
			{
				if (currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark != null)
				{
					currentCornerName = currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark;
					if (!flag3)
					{
						WheelsLockedEnum cornerEntryLocking = getCornerEntryLocking(lockedTicksThreshold, currentGameState.carClass.allMembersAreFWD);
						if (cornerEntryLocking != WheelsLockedEnum.NONE)
						{
							DateTime value = DateTime.MinValue;
							DateTime dateTime = (cornerLockWarningsPlayed.TryGetValue(currentCornerName, out value) ? value : DateTime.MinValue);
							if (currentGameState.Now > dateTime + cornerLockWarningMaxFrequency)
							{
								cornerLockWarningsPlayed[currentCornerName] = currentGameState.Now;
								Console.WriteLine("Locking " + cornerEntryLocking.ToString() + " into " + currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark);
								int num = Utilities.random.Next(4, 8);
								switch (cornerEntryLocking)
								{
								case WheelsLockedEnum.FRONTS:
								{
									AudioPlayer obj4 = audioPlayer;
									int expiresAfter4 = num + 10;
									int secondsDelay = num;
									obj4.playMessage(new QueuedMessage("corner_locking", expiresAfter4, AbstractEvent.MessageContents(folderLockingFrontsForCornerWarning, "corners/" + currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark), null, null, null, secondsDelay, this, null, 0));
									break;
								}
								case WheelsLockedEnum.LEFT_FRONT:
								{
									AudioPlayer obj3 = audioPlayer;
									int expiresAfter3 = num + 10;
									int secondsDelay = num;
									obj3.playMessage(new QueuedMessage("corner_locking", expiresAfter3, AbstractEvent.MessageContents(folderLockingLeftFrontForCornerWarning, "corners/" + currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark), null, null, null, secondsDelay, this, null, 0));
									break;
								}
								case WheelsLockedEnum.RIGHT_FRONT:
								{
									AudioPlayer obj2 = audioPlayer;
									int expiresAfter2 = num + 10;
									int secondsDelay = num;
									obj2.playMessage(new QueuedMessage("corner_locking", expiresAfter2, AbstractEvent.MessageContents(folderLockingRightFrontForCornerWarning, "corners/" + currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark), null, null, null, secondsDelay, this, null, 0));
									break;
								}
								case WheelsLockedEnum.REARS:
								{
									AudioPlayer obj = audioPlayer;
									int expiresAfter = num + 10;
									int secondsDelay = num;
									obj.playMessage(new QueuedMessage("corner_locking", expiresAfter, AbstractEvent.MessageContents(folderLockingRearsForCornerWarning, "corners/" + currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark), null, null, null, secondsDelay, this, null, 0));
									break;
								}
								}
							}
						}
					}
					leftFrontLockedList.Clear();
					rightFrontLockedList.Clear();
					leftRearLockedList.Clear();
					rightRearLockedList.Clear();
					nextCornerSpecificSpinningCheck = currentGameState.Now + TimeSpan.FromSeconds(3.0);
					leftFrontExitStartWheelSpinTime = timeLeftFrontIsSpinningForLap;
					rightFrontExitStartWheelSpinTime = timeRightFrontIsSpinningForLap;
					leftRearExitStartWheelSpinTime = timeLeftRearIsSpinningForLap;
					rightRearExitStartWheelSpinTime = timeRightRearIsSpinningForLap;
				}
				else if (currentGameState.Now > nextCornerSpecificSpinningCheck)
				{
					nextCornerSpecificSpinningCheck = DateTime.MaxValue;
					if (!flag4 && currentCornerName != null)
					{
						DateTime value2 = DateTime.MinValue;
						DateTime dateTime2 = (cornerSpinningWarningsPlayed.TryGetValue(currentCornerName, out value2) ? value2 : DateTime.MinValue);
						if (currentGameState.Now > dateTime2 + cornerSpinningWarningMaxFrequency)
						{
							float num2 = timeLeftFrontIsSpinningForLap - leftFrontExitStartWheelSpinTime;
							float num3 = timeRightFrontIsSpinningForLap - rightFrontExitStartWheelSpinTime;
							float num4 = timeLeftRearIsSpinningForLap - leftRearExitStartWheelSpinTime;
							float num5 = timeRightRearIsSpinningForLap - rightRearExitStartWheelSpinTime;
							int num6 = Utilities.random.Next(4, 8);
							if (!currentGameState.carClass.allMembersAreRWD && num2 > cornerExitSpinningThreshold && num3 > cornerExitSpinningThreshold)
							{
								Console.WriteLine("Spinning fronts out of " + currentCornerName);
								AudioPlayer obj5 = audioPlayer;
								int expiresAfter5 = num6 + 10;
								int secondsDelay = num6;
								obj5.playMessage(new QueuedMessage("corner_spinning", expiresAfter5, AbstractEvent.MessageContents(folderSpinningFrontsForCornerWarning, "corners/" + currentCornerName), null, null, null, secondsDelay, this, null, 0));
								cornerSpinningWarningsPlayed[currentCornerName] = currentGameState.Now;
							}
							else if (!currentGameState.carClass.allMembersAreFWD && num4 > cornerExitSpinningThreshold && num5 > cornerExitSpinningThreshold)
							{
								Console.WriteLine("Spinning rears out of " + currentCornerName);
								AudioPlayer obj6 = audioPlayer;
								int expiresAfter6 = num6 + 10;
								int secondsDelay = num6;
								obj6.playMessage(new QueuedMessage("corner_spinning", expiresAfter6, AbstractEvent.MessageContents(folderSpinningRearsForCornerWarning, "corners/" + currentCornerName), null, null, null, secondsDelay, this, null, 0));
								cornerSpinningWarningsPlayed[currentCornerName] = currentGameState.Now;
							}
							else if (!currentGameState.carClass.allMembersAreRWD && num2 > cornerExitSpinningThreshold)
							{
								Console.WriteLine("Spinning left front out of " + currentCornerName);
								AudioPlayer obj7 = audioPlayer;
								int expiresAfter7 = num6 + 10;
								int secondsDelay = num6;
								obj7.playMessage(new QueuedMessage("corner_spinning", expiresAfter7, AbstractEvent.MessageContents(folderSpinningLeftFrontForCornerWarning, "corners/" + currentCornerName), null, null, null, secondsDelay, this, null, 0));
								cornerSpinningWarningsPlayed[currentCornerName] = currentGameState.Now;
							}
							else if (!currentGameState.carClass.allMembersAreRWD && num3 > cornerExitSpinningThreshold)
							{
								Console.WriteLine("Spinning right front out of " + currentCornerName);
								AudioPlayer obj8 = audioPlayer;
								int expiresAfter8 = num6 + 10;
								int secondsDelay = num6;
								obj8.playMessage(new QueuedMessage("corner_spinning", expiresAfter8, AbstractEvent.MessageContents(folderSpinningRightFrontForCornerWarning, "corners/" + currentCornerName), null, null, null, secondsDelay, this, null, 0));
								cornerSpinningWarningsPlayed[currentCornerName] = currentGameState.Now;
							}
							else if (!currentGameState.carClass.allMembersAreFWD && num4 > cornerExitSpinningThreshold)
							{
								Console.WriteLine("Spinning left rear out of " + currentCornerName);
								AudioPlayer obj9 = audioPlayer;
								int expiresAfter9 = num6 + 10;
								int secondsDelay = num6;
								obj9.playMessage(new QueuedMessage("corner_spinning", expiresAfter9, AbstractEvent.MessageContents(folderSpinningLeftRearForCornerWarning, "corners/" + currentCornerName), null, null, null, secondsDelay, this, null, 0));
								cornerSpinningWarningsPlayed[currentCornerName] = currentGameState.Now;
							}
							else if (!currentGameState.carClass.allMembersAreFWD && num5 > cornerExitSpinningThreshold)
							{
								Console.WriteLine("Spinning right rear out of " + currentCornerName);
								AudioPlayer obj10 = audioPlayer;
								int expiresAfter10 = num6 + 10;
								int secondsDelay = num6;
								obj10.playMessage(new QueuedMessage("corner_spinning", expiresAfter10, AbstractEvent.MessageContents(folderSpinningRightRearForCornerWarning, "corners/" + currentCornerName), null, null, null, secondsDelay, this, null, 0));
								cornerSpinningWarningsPlayed[currentCornerName] = currentGameState.Now;
							}
						}
					}
				}
			}
			leftFrontBrakeTemp = currentGameState.TyreData.LeftFrontBrakeTemp;
			rightFrontBrakeTemp = currentGameState.TyreData.RightFrontBrakeTemp;
			leftRearBrakeTemp = currentGameState.TyreData.LeftRearBrakeTemp;
			rightRearBrakeTemp = currentGameState.TyreData.RightRearBrakeTemp;
			leftFrontTyreTemp = currentGameState.TyreData.FrontLeft_CenterTemp;
			rightFrontTyreTemp = currentGameState.TyreData.FrontRight_CenterTemp;
			leftRearTyreTemp = currentGameState.TyreData.RearLeft_CenterTemp;
			rightRearTyreTemp = currentGameState.TyreData.RearRight_CenterTemp;
			leftFrontTyrePressure = currentGameState.TyreData.FrontLeftPressure;
			rightFrontTyrePressure = currentGameState.TyreData.FrontRightPressure;
			leftRearTyrePressure = currentGameState.TyreData.RearLeftPressure;
			rightRearTyrePressure = currentGameState.TyreData.RearRightPressure;
			TopicWindowBrakes.SetFLTemp(leftFrontBrakeTemp);
			TopicWindowBrakes.SetFRTemp(rightFrontBrakeTemp);
			TopicWindowBrakes.SetRLTemp(leftRearBrakeTemp);
			TopicWindowBrakes.SetRRTemp(rightRearBrakeTemp);
			TopicWindowTyres.SetFLTemp(leftFrontTyreTemp);
			TopicWindowTyres.SetFRTemp(rightFrontTyreTemp);
			TopicWindowTyres.SetRLTemp(leftRearTyreTemp);
			TopicWindowTyres.SetRRTemp(rightRearTyreTemp);
			currentTyreTempStatus = currentGameState.TyreData.TyreTempStatus;
			currentBrakeTempStatus = currentGameState.TyreData.BrakeTempStatus;
			if (isBrakeTempPeakForLap(currentGameState.TyreData.LeftFrontBrakeTemp, currentGameState.TyreData.RightFrontBrakeTemp, currentGameState.TyreData.LeftRearBrakeTemp, currentGameState.TyreData.RightRearBrakeTemp))
			{
				peakBrakeTempStatus = currentGameState.TyreData.BrakeTempStatus;
			}
			completedLaps = currentGameState.SessionData.CompletedLaps;
			lapsInSession = currentGameState.SessionData.SessionNumberOfLaps;
			timeInSession = currentGameState.SessionData.SessionTotalRunTime;
			timeElapsed = currentGameState.SessionData.SessionRunningTime;
			if (enableTyreTempWarnings && !currentGameState.SessionData.LeaderHasFinishedRace && !currentGameState.PitData.InPitlane && currentGameState.SessionData.CompletedLaps >= lapsIntoSessionBeforeTempMessage && completedLaps >= lastTyreTempCheckLap + lapsBetweenTyreTempChecks && currentGameState.SessionData.IsNewSector && currentGameState.SessionData.SectorNumber == thisLapTyreTempReportSector)
			{
				reportCurrentTyreTempStatus(playImmediately: false);
				lastTyreTempCheckLap = completedLaps;
			}
			if (!currentGameState.SessionData.LeaderHasFinishedRace && ((checkBrakesAtSector == 1 && currentGameState.SessionData.IsNewLap && completedLaps >= lastBrakeTempCheckLap + lapsBetweenBrakeTempChecks) || (currentGameState.SessionData.IsNewSector && currentGameState.SessionData.SectorNumber == checkBrakesAtSector && completedLaps >= lastBrakeTempCheckLap + lapsBetweenBrakeTempChecks)) && (lastBrakeTempCheckSessionTime == -1f || currentGameState.SessionData.SessionRunningTime - lastBrakeTempCheckSessionTime > secondsBetweenBrakeTempCheck))
			{
				if (!currentGameState.PitData.InPitlane && currentGameState.SessionData.CompletedLaps >= lapsIntoSessionBeforeTempMessage && enableBrakeTempWarnings && !GlobalBehaviourSettings.useOvalLogic)
				{
					reportBrakeTempStatus(playImmediately: false, peak: true);
					lastBrakeTempCheckSessionTime = currentGameState.SessionData.SessionRunningTime;
					lastBrakeTempCheckLap = completedLaps;
				}
				peakBrakeTempForLap = 0f;
			}
			currentTyreFlatSpotStatus = currentGameState.TyreData.TyreFlatSpotStatus;
			currentTyreDirtPickupStatus = currentGameState.TyreData.TyreDirtPickupStatus;
			currentTyreConditionStatus = currentGameState.TyreData.TyreConditionStatus;
			if (currentGameState.TyreData.TyreWearActive && flag)
			{
				leftFrontWearPercent = currentGameState.TyreData.FrontLeftPercentWear;
				leftRearWearPercent = currentGameState.TyreData.RearLeftPercentWear;
				rightFrontWearPercent = currentGameState.TyreData.FrontRightPercentWear;
				rightRearWearPercent = currentGameState.TyreData.RearRightPercentWear;
				if (currentGameState.PitData.InPitlane && !currentGameState.SessionData.LeaderHasFinishedRace)
				{
					if (currentGameState.SessionData.SessionType == SessionType.Race && enableTyreWearWarnings && !reportedTyreWearForCurrentPitEntry)
					{
						reportedTyreWearForCurrentPitEntry = true;
					}
				}
				else
				{
					reportedTyreWearForCurrentPitEntry = false;
				}
				if (currentGameState.SessionData.IsNewSector && currentGameState.SessionData.SectorNumber == thisLapTyreConditionReportSector && !currentGameState.PitData.InPitlane && enableTyreWearWarnings && !currentGameState.SessionData.LeaderHasFinishedRace)
				{
					reportCurrentTyreConditionStatus(currentGameState, playImmediately: false, playEvenIfUnchanged: false, delayResponses, tyreStatusRequestOnly: false);
				}
				if (!currentGameState.PitData.InPitlane && enableTyreWearWarnings && !currentGameState.SessionData.LeaderHasFinishedRace && currentGameState.SessionData.SessionType == SessionType.Race)
				{
					if (!reportedEstimatedTimeLeftOneThirdWear)
					{
						reportedEstimatedTimeLeftOneThirdWear = reportEstimatedTyreLife(33f, currentGameState.SessionData.SessionRunningTime, currentGameState.SessionData.SessionTotalRunTime, currentGameState.SessionData.CompletedLaps, currentGameState.SessionData.SessionNumberOfLaps);
					}
					else if (!reportedEstimatedTimeLeftTwoThirdsWear)
					{
						reportedEstimatedTimeLeftTwoThirdsWear = reportEstimatedTyreLife(66f, currentGameState.SessionData.SessionRunningTime, currentGameState.SessionData.SessionTotalRunTime, currentGameState.SessionData.CompletedLaps, currentGameState.SessionData.SessionNumberOfLaps);
						if (reportedEstimatedTimeLeftTwoThirdsWear)
						{
							reportedEstimatedTimeLeftOneThirdWear = true;
						}
					}
				}
				if (currentGameState.SessionData.JustGoneGreen || (previousGameState != null && (currentGameState.TyreData.FrontLeftPercentWear < previousGameState.TyreData.FrontLeftPercentWear || currentGameState.TyreData.FrontRightPercentWear < previousGameState.TyreData.FrontRightPercentWear || currentGameState.TyreData.RearRightPercentWear < previousGameState.TyreData.RearRightPercentWear || currentGameState.TyreData.RearLeftPercentWear < previousGameState.TyreData.RearLeftPercentWear)))
				{
					reportedEstimatedTimeLeftOneThirdWear = false;
					reportedEstimatedTimeLeftTwoThirdsWear = false;
					tyreLifeYPointsTime.Clear();
					tyreLifeYPointsSectors.Clear();
					tyreLifeXPointsLFWearBySector.Clear();
					tyreLifeXPointsRFWearBySector.Clear();
					tyreLifeXPointsLRWearBySector.Clear();
					tyreLifeXPointsRRWearBySector.Clear();
					tyreLifeXPointsLFWearByTime.Clear();
					tyreLifeXPointsRFWearByTime.Clear();
					tyreLifeXPointsLRWearByTime.Clear();
					tyreLifeXPointsRRWearByTime.Clear();
				}
				else if (currentGameState.PositionAndMotionData.CarSpeed > 1f)
				{
					if (currentGameState.SessionData.IsNewSector)
					{
						if (tyreLifeYPointsSectors.Count == 0)
						{
							if (currentGameState.SessionData.SectorNumber == 2)
							{
								tyreLifeYPointsSectors.Add(1 + currentGameState.SessionData.CompletedLaps * 3);
							}
							else
							{
								tyreLifeYPointsSectors.Add(currentGameState.SessionData.CompletedLaps * 3);
							}
						}
						else
						{
							tyreLifeYPointsSectors.Add(tyreLifeYPointsSectors[tyreLifeYPointsSectors.Count - 1] + 1.0);
						}
						tyreLifeXPointsLFWearBySector.Add(currentGameState.TyreData.FrontLeftPercentWear);
						tyreLifeXPointsRFWearBySector.Add(currentGameState.TyreData.FrontRightPercentWear);
						tyreLifeXPointsLRWearBySector.Add(currentGameState.TyreData.RearLeftPercentWear);
						tyreLifeXPointsRRWearBySector.Add(currentGameState.TyreData.RearRightPercentWear);
					}
					if (lastTyreLifeYPointTime == -1f)
					{
						tyreLifeYPointsTime.Add(currentGameState.SessionData.SessionRunningTime);
						lastTyreLifeYPointTime = currentGameState.SessionData.SessionRunningTime;
						tyreLifeXPointsLFWearByTime.Add(currentGameState.TyreData.FrontLeftPercentWear);
						tyreLifeXPointsRFWearByTime.Add(currentGameState.TyreData.FrontRightPercentWear);
						tyreLifeXPointsLRWearByTime.Add(currentGameState.TyreData.RearLeftPercentWear);
						tyreLifeXPointsRRWearByTime.Add(currentGameState.TyreData.RearRightPercentWear);
					}
					else if (currentGameState.SessionData.SessionRunningTime - lastTyreLifeYPointTime > 20f)
					{
						tyreLifeYPointsTime.Add(currentGameState.SessionData.SessionRunningTime);
						lastTyreLifeYPointTime = currentGameState.SessionData.SessionRunningTime;
						tyreLifeXPointsLFWearByTime.Add(currentGameState.TyreData.FrontLeftPercentWear);
						tyreLifeXPointsRFWearByTime.Add(currentGameState.TyreData.FrontRightPercentWear);
						tyreLifeXPointsLRWearByTime.Add(currentGameState.TyreData.RearLeftPercentWear);
						tyreLifeXPointsRRWearByTime.Add(currentGameState.TyreData.RearRightPercentWear);
					}
				}
			}
			if (!currentGameState.TyreData.DirtPickupEmulationActive || !enableTyreDirtPickupWarnings || !(currentGameState.PositionAndMotionData.CarSpeed > 20f))
			{
				return;
			}
			CornerData.Corners cornersForStatus = currentTyreDirtPickupStatus.getCornersForStatus(TyreDirtPickupState.MAJOR);
			if (cornersForStatus != CornerData.Corners.NONE)
			{
				if (cornersForStatus != lastDirtPickupCorners)
				{
					waitingForDirtPickupToStabilize = true;
					timeWaitForDirtPickupStarted = currentGameState.Now;
				}
				lastDirtPickupCorners = cornersForStatus;
				if (!waitingForDirtPickupToStabilize || !((currentGameState.Now - timeWaitForDirtPickupStarted).TotalSeconds > 4.0))
				{
					return;
				}
				waitingForDirtPickupToStabilize = false;
				List<MessageFragment> list = new List<MessageFragment>();
				addTyreDirtPickupStateWarningMessages(currentTyreDirtPickupStatus.getCornersForStatus(TyreDirtPickupState.MAJOR), TyreDirtPickupState.MAJOR, list);
				if (list.Count > 0)
				{
					Console.WriteLine($"Announcing dirt pickup for corners: {cornersForStatus}" + "  FL: " + currentGameState.TyreData.FrontLeftDirtPickupSeverity.ToString("0.000") + "  FR: " + currentGameState.TyreData.FrontRightDirtPickupSeverity.ToString("0.000") + "  RL: " + currentGameState.TyreData.RearLeftDirtPickupSeverity.ToString("0.000") + "  RR: " + currentGameState.TyreData.RearRightDirtPickupSeverity.ToString("0.000"));
					if ((currentGameState.Now - timeLastDirtPickupMessagePlayed).TotalSeconds > 300.0)
					{
						timeLastDirtPickupMessagePlayed = currentGameState.Now;
						audioPlayer.playMessageImmediately(new QueuedMessage("tyres_dirty_warning", 0, list));
					}
					else
					{
						Console.WriteLine("Suppressing dirt pickup message due to time since last message.");
					}
				}
			}
			else
			{
				lastDirtPickupCorners = cornersForStatus;
			}
		}

		public void reportCurrentTyreTempStatus(bool playImmediately, bool allowDelay = true)
		{
			if ((leftFrontTyreTemp == 0f && rightFrontTyreTemp == 0f && leftRearTyreTemp == 0f && rightRearTyreTemp == 0f) || (Game.IRACING && timeWhenEnteredPits.AddMinutes(2.0) < CrewChief.currentGameState.Now))
			{
				return;
			}
			bool includeRears = playImmediately || !CrewChief.currentGameState.carClass.allMembersAreFWD;
			List<MessageFragment> list = new List<MessageFragment>();
			if (!GlobalBehaviourSettings.useOvalLogic || !Game.IRACING)
			{
				addTyreTempWarningMessages(currentTyreTempStatus.getCornersForStatus(TyreTemp.COLD), TyreTemp.COLD, list, includeRears);
			}
			addTyreTempWarningMessages(currentTyreTempStatus.getCornersForStatus(TyreTemp.HOT), TyreTemp.HOT, list, includeRears);
			addTyreTempWarningMessages(currentTyreTempStatus.getCornersForStatus(TyreTemp.COOKING), TyreTemp.COOKING, list, includeRears);
			if (list.Count == 0)
			{
				if (playImmediately || !lastTyreTempCheckOK)
				{
					lastTyreTempCheckOK = true;
					list.Add(MessageFragment.Text(folderGoodTyreTemps));
				}
			}
			else
			{
				lastTyreTempCheckOK = false;
			}
			if (list.Count <= 0)
			{
				return;
			}
			List<MessageFragment> list2 = ((tyreTempMessagesPlayed.Count > 0) ? tyreTempMessagesPlayed.Last() : null);
			if (playImmediately)
			{
				tyreTempMessagesPlayed.Add(list);
				audioPlayer.playMessageImmediately(new QueuedMessage("tyre_temps", 0, list));
			}
			else if (list2 == null || !messagesHaveSameContent(list2, list))
			{
				tyreTempMessagesPlayed.Add(list);
				Console.WriteLine("Tyre temp warning, temps : " + string.Join(", ", list));
				int secondsDelay = 0;
				if (allowDelay)
				{
					secondsDelay = Utilities.random.Next(0, 10);
				}
				audioPlayer.playMessage(new QueuedMessage("tyre_temps", 0, list, null, null, null, secondsDelay, this));
				if (isBouncing(tyreTempMessagesPlayed, 3))
				{
					lapsBetweenTyreTempChecks++;
					Console.WriteLine("This tyre temp message has already been played recently, increasing check interval");
				}
			}
		}

		public void reportBrakeTempStatus(bool playImmediately, bool peak)
		{
			if (Game.IRACING)
			{
				return;
			}
			bool includeRears = playImmediately || !CrewChief.currentGameState.carClass.allMembersAreFWD;
			List<MessageFragment> list = new List<MessageFragment>();
			if (peak)
			{
				if (!GlobalBehaviourSettings.useOvalLogic)
				{
					addBrakeTempWarningMessages(peakBrakeTempStatus.getCornersForStatus(BrakeTemp.COLD), BrakeTemp.COLD, list, includeRears);
				}
				addBrakeTempWarningMessages(peakBrakeTempStatus.getCornersForStatus(BrakeTemp.HOT), BrakeTemp.HOT, list, includeRears);
				addBrakeTempWarningMessages(peakBrakeTempStatus.getCornersForStatus(BrakeTemp.COOKING), BrakeTemp.COOKING, list, includeRears);
			}
			else
			{
				if (!GlobalBehaviourSettings.useOvalLogic)
				{
					addBrakeTempWarningMessages(currentBrakeTempStatus.getCornersForStatus(BrakeTemp.COLD), BrakeTemp.COLD, list, includeRears);
				}
				addBrakeTempWarningMessages(currentBrakeTempStatus.getCornersForStatus(BrakeTemp.HOT), BrakeTemp.HOT, list, includeRears);
				addBrakeTempWarningMessages(currentBrakeTempStatus.getCornersForStatus(BrakeTemp.COOKING), BrakeTemp.COOKING, list, includeRears);
			}
			if (list.Count == 0)
			{
				if (!playImmediately && lastBrakeTempCheckOK)
				{
					return;
				}
				lastBrakeTempCheckOK = true;
				list.Add(MessageFragment.Text(folderGoodBrakeTemps));
			}
			else
			{
				lastBrakeTempCheckOK = false;
			}
			if (list.Count <= 0)
			{
				return;
			}
			List<MessageFragment> list2 = ((brakeTempMessagesPlayed.Count > 0) ? brakeTempMessagesPlayed.Last() : null);
			if (playImmediately)
			{
				brakeTempMessagesPlayed.Add(list);
				audioPlayer.playMessageImmediately(new QueuedMessage("brake_temps", 0, list));
			}
			else if (list2 == null || !messagesHaveSameContent(list2, list))
			{
				brakeTempMessagesPlayed.Add(list);
				audioPlayer.playMessage(new QueuedMessage("brake_temps", 0, list, null, null, null, Utilities.random.Next(0, 10), this));
				if (isBouncing(brakeTempMessagesPlayed, 3))
				{
					lapsBetweenBrakeTempChecks++;
					secondsBetweenBrakeTempCheck += 120f;
					Console.WriteLine("This brake temp message has already been played recently, increasing check interval");
				}
			}
		}

		private bool isBouncing(List<List<MessageFragment>> messages, int messagesToCheck)
		{
			if (messages.Count > 2)
			{
				int num = 0;
				List<MessageFragment> messages2 = messages.Last();
				for (int num2 = messages.Count - 2; num2 >= 0; num2--)
				{
					List<MessageFragment> messages3 = messages[num2];
					if (messagesHaveSameContent(messages2, messages3))
					{
						return true;
					}
					num++;
					if (num >= messagesToCheck)
					{
						break;
					}
				}
			}
			return false;
		}

		private void reportCurrentTyreConditionStatus(GameStateData currentGameState, bool playImmediately, bool playEvenIfUnchanged, bool allowDelayedResponse, bool tyreStatusRequestOnly)
		{
			List<MessageFragment> list = new List<MessageFragment>();
			addTyreConditionWarningMessages(currentTyreConditionStatus.getCornersForStatus(TyreCondition.MINOR_WEAR), TyreCondition.MINOR_WEAR, list);
			addTyreConditionWarningMessages(currentTyreConditionStatus.getCornersForStatus(TyreCondition.MAJOR_WEAR), TyreCondition.MAJOR_WEAR, list);
			addTyreConditionWarningMessages(currentTyreConditionStatus.getCornersForStatus(TyreCondition.WORN_OUT), TyreCondition.WORN_OUT, list);
			if (currentGameState.TyreData.FlatSpotEmulationActive)
			{
				addTyreFlatSpotWarningMessages(currentTyreFlatSpotStatus.getCornersForStatus(TyreFlatSpotState.MAJOR), TyreFlatSpotState.MAJOR, list);
			}
			bool flag = false;
			if (list.Count == 0)
			{
				list.Add(MessageFragment.Text(tyreStatusRequestOnly ? folderGoodWear : folderGoodWearGeneral));
				flag = true;
			}
			if (playImmediately)
			{
				if (allowDelayedResponse && Utilities.random.Next(10) >= 2)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/stand_by", 0));
					int num = Math.Max(5, Utilities.random.Next(11));
					audioPlayer.pauseQueue(num);
					audioPlayer.playDelayedImmediateMessage(new QueuedMessage("tyre_condition", 0, list, null, null, null, num));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("tyre_condition", 0, list));
				}
			}
			else if (playEvenIfUnchanged || (lastTyreConditionMessage != null && !messagesHaveSameContent(lastTyreConditionMessage, list) && !flag))
			{
				audioPlayer.playMessage(new QueuedMessage("tyre_condition", 0, list, null, null, null, Utilities.random.Next(0, 10), this));
			}
			lastTyreConditionMessage = list;
		}

		private void playEstimatedTyreLifeMinutes(int minutesRemainingOnTheseTyres, bool immediate)
		{
			if (immediate)
			{
				if (minutesRemainingOnTheseTyres <= 1)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage(folderKnackeredAllRound, 0));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("minutes_on_current_tyres", 0, AbstractEvent.MessageContents(folderMinutesOnCurrentTyresIntro, minutesRemainingOnTheseTyres, folderMinutesOnCurrentTyresOutro)));
				}
			}
			else if (minutesRemainingOnTheseTyres > 1 && (float)minutesRemainingOnTheseTyres <= 4f + (timeInSession - timeElapsed) / 60f)
			{
				audioPlayer.playMessage(new QueuedMessage("minutes_on_current_tyres", 0, AbstractEvent.MessageContents(folderMinutesOnCurrentTyresIntro, minutesRemainingOnTheseTyres, folderMinutesOnCurrentTyresOutro), null, null, null, 0, this));
			}
		}

		private void playEstimatedTypeLifeLaps(int lapsRemainingOnTheseTyres, bool immediate)
		{
			if (immediate)
			{
				if (lapsRemainingOnTheseTyres <= 1)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage(folderKnackeredAllRound, 0));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("laps_on_current_tyres", 0, AbstractEvent.MessageContents(folderLapsOnCurrentTyresIntro, MessageFragment.Integer(lapsRemainingOnTheseTyres, MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)), folderLapsOnCurrentTyresOutro)));
				}
			}
			else if (lapsRemainingOnTheseTyres > 1 && lapsRemainingOnTheseTyres <= 2 + lapsInSession - completedLaps)
			{
				audioPlayer.playMessage(new QueuedMessage("laps_on_current_tyres", 0, AbstractEvent.MessageContents(folderLapsOnCurrentTyresIntro, MessageFragment.Integer(lapsRemainingOnTheseTyres, MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)), folderLapsOnCurrentTyresOutro), null, null, null, 0, this));
			}
		}

		private int getRemainingTyreLife(float sessionRunningTime, Tuple<CornerData.Corners, float> maxWearPercent)
		{
			if (lapsInSession > 0 || timeInSession == 0f)
			{
				double[] array;
				switch (maxWearPercent.Item1)
				{
				case CornerData.Corners.FRONT_LEFT:
					array = tyreLifeXPointsLFWearBySector.ToArray();
					break;
				case CornerData.Corners.FRONT_RIGHT:
					array = tyreLifeXPointsRFWearBySector.ToArray();
					break;
				case CornerData.Corners.REAR_LEFT:
					array = tyreLifeXPointsLRWearBySector.ToArray();
					break;
				default:
					array = tyreLifeXPointsRRWearBySector.ToArray();
					break;
				}
				if (array.Length < 5 || tyreLifeYPointsSectors.Count != array.Length)
				{
					return -1;
				}
				return (int)Utilities.getYEstimate(array, tyreLifeYPointsSectors.ToArray(), 97.0, 2) / 3 - completedLaps;
			}
			double[] array2;
			switch (maxWearPercent.Item1)
			{
			case CornerData.Corners.FRONT_LEFT:
				array2 = tyreLifeXPointsLFWearByTime.ToArray();
				break;
			case CornerData.Corners.FRONT_RIGHT:
				array2 = tyreLifeXPointsRFWearByTime.ToArray();
				break;
			case CornerData.Corners.REAR_LEFT:
				array2 = tyreLifeXPointsLRWearByTime.ToArray();
				break;
			default:
				array2 = tyreLifeXPointsRRWearByTime.ToArray();
				break;
			}
			if (array2.Length < 5 || tyreLifeYPointsTime.Count != array2.Length)
			{
				return -1;
			}
			return (int)Math.Ceiling((Utilities.getYEstimate(array2, tyreLifeYPointsTime.ToArray(), 95.0, 2) - (double)sessionRunningTime) / 60.0);
		}

		private bool reportEstimatedTyreLife(float maxWearThreshold, float sessionRunningTime, float sessionTotalRunTime, int lapsCompleted, int sessionTotalLaps)
		{
			Tuple<CornerData.Corners, float> maxWearPercent = getMaxWearPercent();
			if (maxWearPercent.Item2 >= maxWearThreshold)
			{
				int remainingTyreLife = getRemainingTyreLife(sessionRunningTime, maxWearPercent);
				if (remainingTyreLife != -1)
				{
					if (lapsInSession > 0 || timeInSession == 0f)
					{
						int num = sessionTotalLaps - lapsCompleted;
						if (remainingTyreLife - num < 2)
						{
							playEstimatedTypeLifeLaps(remainingTyreLife, immediate: false);
						}
					}
					else
					{
						float num2 = (sessionTotalRunTime - sessionRunningTime) / 60f;
						if ((float)remainingTyreLife - num2 < 2f)
						{
							playEstimatedTyreLifeMinutes(remainingTyreLife, immediate: false);
						}
					}
				}
				return true;
			}
			return false;
		}

		private Tuple<CornerData.Corners, float> getMaxWearPercent()
		{
			if (GlobalBehaviourSettings.useOvalLogic)
			{
				if (rightFrontWearPercent > rightRearWearPercent)
				{
					return new Tuple<CornerData.Corners, float>(CornerData.Corners.FRONT_RIGHT, rightFrontWearPercent);
				}
				return new Tuple<CornerData.Corners, float>(CornerData.Corners.REAR_RIGHT, rightRearWearPercent);
			}
			if (rightFrontWearPercent > rightRearWearPercent && rightFrontWearPercent > leftFrontWearPercent && rightFrontWearPercent > leftRearWearPercent)
			{
				return new Tuple<CornerData.Corners, float>(CornerData.Corners.FRONT_RIGHT, rightFrontWearPercent);
			}
			if (rightRearWearPercent > rightFrontWearPercent && rightRearWearPercent > leftFrontWearPercent && rightRearWearPercent > leftRearWearPercent)
			{
				return new Tuple<CornerData.Corners, float>(CornerData.Corners.REAR_RIGHT, rightRearWearPercent);
			}
			if (leftFrontWearPercent > rightRearWearPercent && leftFrontWearPercent > rightFrontWearPercent && leftFrontWearPercent > leftRearWearPercent)
			{
				return new Tuple<CornerData.Corners, float>(CornerData.Corners.FRONT_LEFT, leftFrontWearPercent);
			}
			return new Tuple<CornerData.Corners, float>(CornerData.Corners.REAR_LEFT, leftRearWearPercent);
		}

		private void reportCurrentTyreTemps()
		{
			if (leftFrontTyreTemp == 0f && rightFrontTyreTemp == 0f && leftRearTyreTemp == 0f && rightRearTyreTemp == 0f)
			{
				audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
			}
			else
			{
				audioPlayer.playMessageImmediately(new QueuedMessage("tyre_temps", 0, AbstractEvent.MessageContents(folderLeftFront, convertTemp(leftFrontTyreTemp), folderRightFront, convertTemp(rightFrontTyreTemp), folderLeftRear, convertTemp(leftRearTyreTemp), folderRightRear, convertTemp(rightRearTyreTemp), getTempUnit())));
			}
		}

		private void reportCurrentTyrePressures()
		{
			if (leftFrontTyrePressure == 0f && rightFrontTyrePressure == 0f && leftRearTyrePressure == 0f && rightRearTyrePressure == 0f)
			{
				audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
			}
			else
			{
				audioPlayer.playMessageImmediately(new QueuedMessage("tyre_pressures", 0, AbstractEvent.MessageContents(folderLeftFront, convertPressure(leftFrontTyrePressure, 1), folderRightFront, convertPressure(rightFrontTyrePressure, 1), folderLeftRear, convertPressure(leftRearTyrePressure, 1), folderRightRear, convertPressure(rightRearTyrePressure, 1), getPressureUnit())));
			}
		}

		private void reportCurrentBrakeTemps()
		{
			if (leftFrontBrakeTemp == 0f && rightFrontBrakeTemp == 0f && leftRearBrakeTemp == 0f && rightRearBrakeTemp == 0f)
			{
				audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
			}
			else
			{
				audioPlayer.playMessageImmediately(new QueuedMessage("brake_temps", 0, AbstractEvent.MessageContents(folderLeftFront, convertTemp(leftFrontBrakeTemp, 10), folderRightFront, convertTemp(rightFrontBrakeTemp, 10), folderLeftRear, convertTemp(leftRearBrakeTemp, 10), folderRightRear, convertTemp(rightRearBrakeTemp, 10), getTempUnit())));
			}
		}

		public override SpeechCommands.ID HandlesEvent(string voiceMessage)
		{
			return SpeechCommands.SpeechToCommand(Commands, voiceMessage);
		}

		public override void respond(string voiceMessage)
		{
			respond(voiceMessage, HandlesEvent(voiceMessage));
		}

		public override void respond(string voiceMessage, SpeechCommands.ID cmd)
		{
			GameStateData currentGameState = CrewChief.currentGameState;
			if (Game.IRACING)
			{
				if (voiceMessage != null && currentGameState != null)
				{
					respondIracing(voiceMessage, currentGameState, cmd);
				}
				return;
			}
			switch (cmd)
			{
			case SpeechCommands.ID.HOW_ARE_MY_TYRE_TEMPS:
				if (currentTyreTempStatus != null)
				{
					reportCurrentTyreTempStatus(playImmediately: true);
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				break;
			case SpeechCommands.ID.WHAT_ARE_MY_TYRE_TEMPS:
				reportCurrentTyreTemps();
				break;
			case SpeechCommands.ID.HOW_ARE_MY_BRAKE_TEMPS:
				if (currentBrakeTempStatus != null)
				{
					reportBrakeTempStatus(playImmediately: true, peak: true);
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				break;
			case SpeechCommands.ID.WHAT_ARE_MY_BRAKE_TEMPS:
				reportCurrentBrakeTemps();
				break;
			case SpeechCommands.ID.HOWS_MY_TYRE_WEAR:
				if (currentTyreConditionStatus != null)
				{
					reportCurrentTyreConditionStatus(currentGameState, playImmediately: true, playEvenIfUnchanged: true, delayResponses, tyreStatusRequestOnly: true);
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				break;
			case SpeechCommands.ID.WHAT_ARE_THE_RELATIVE_TYRE_PERFORMANCES:
			{
				foreach (TyrePerformanceContainer item in getRelativeTyrePerformance())
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("tyre_comparison_" + item.type1.ToString() + "-" + item.type2, 0, AbstractEvent.MessageContents(getFolderForTyreType(item.type1), folderAreAbout, TimeSpanWrapper.FromSeconds(item.bestLapDelta, Precision.AUTO_GAPS), folderFasterThan, getFolderForTyreType(item.type2))));
				}
				break;
			}
			case SpeechCommands.ID.CAR_STATUS:
			case SpeechCommands.ID.STATUS:
				if (currentTyreConditionStatus != null)
				{
					reportCurrentTyreConditionStatus(currentGameState, playImmediately: true, playEvenIfUnchanged: true, allowDelayedResponse: false, tyreStatusRequestOnly: false);
				}
				if (currentTyreTempStatus != null)
				{
					reportCurrentTyreTempStatus(playImmediately: true);
				}
				if (currentBrakeTempStatus != null)
				{
					reportBrakeTempStatus(playImmediately: true, peak: true);
				}
				break;
			case SpeechCommands.ID.HOW_LONG_WILL_THESE_TYRES_LAST:
			{
				if (CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				Tuple<CornerData.Corners, float> maxWearPercent = getMaxWearPercent();
				Console.WriteLine("Tyre life estimate, wear active = " + CrewChief.currentGameState.TyreData.TyreWearActive);
				Console.WriteLine("Max wear is " + maxWearPercent.Item2 + "% on " + maxWearPercent.Item1);
				if (maxWearPercent.Item2 < 1f)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage(folderGoodWear, 0));
					break;
				}
				if (maxWearPercent.Item2 < 5f)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				int num2 = ((CrewChief.currentGameState == null) ? (-1) : getRemainingTyreLife(CrewChief.currentGameState.SessionData.SessionRunningTime, maxWearPercent));
				if (num2 != -1)
				{
					if (lapsInSession > 0 || timeInSession == 0f)
					{
						playEstimatedTypeLifeLaps(num2, immediate: true);
					}
					else
					{
						playEstimatedTyreLifeMinutes(num2, immediate: true);
					}
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				break;
			}
			case SpeechCommands.ID.HOWS_MY_LEFT_FRONT_CAMBER_RIGHT_NOW:
			{
				if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float percentageDiff7 = getPercentageDiff(CrewChief.currentGameState.TyreData.FrontLeft_RightTemp, CrewChief.currentGameState.TyreData.FrontLeft_LeftTemp);
				int absoluteDiff7 = (int)Math.Round(CrewChief.currentGameState.TyreData.FrontLeft_RightTemp - CrewChief.currentGameState.TyreData.FrontLeft_LeftTemp);
				Console.WriteLine("camber diff is " + absoluteDiff7 + " (" + percentageDiff7 + ") %");
				playCamberMessage(percentageDiff7, absoluteDiff7, folderLFIMOSame, folderLFInnerIsRunning, folderCelsiusHotterThanOuter, folderCelsiusColderThanOuter, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_LEFT_FRONT_CAMBER:
			{
				if (!hasUsableIMOTempData(useAverageData: true))
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float percentageDiff8 = getPercentageDiff(leftFrontAverageIMOLastLap[0], leftFrontAverageIMOLastLap[2]);
				int absoluteDiff8 = (int)Math.Round(leftFrontAverageIMOLastLap[0] - leftFrontAverageIMOLastLap[2]);
				Console.WriteLine("camber diff is " + absoluteDiff8 + " (" + percentageDiff8 + ") %");
				playCamberMessage(percentageDiff8, absoluteDiff8, folderLFIMOSame, folderLFInnerIsRunning, folderCelsiusHotterThanOuter, folderCelsiusColderThanOuter, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_RIGHT_FRONT_CAMBER_RIGHT_NOW:
			{
				if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float percentageDiff = getPercentageDiff(CrewChief.currentGameState.TyreData.FrontRight_LeftTemp, CrewChief.currentGameState.TyreData.FrontRight_RightTemp);
				int absoluteDiff = (int)Math.Round(CrewChief.currentGameState.TyreData.FrontRight_LeftTemp - CrewChief.currentGameState.TyreData.FrontRight_RightTemp);
				Console.WriteLine("camber diff is " + absoluteDiff + " (" + percentageDiff + ") %");
				playCamberMessage(percentageDiff, absoluteDiff, folderRFIMOSame, folderRFInnerIsRunning, folderCelsiusHotterThanOuter, folderCelsiusColderThanOuter, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_RIGHT_FRONT_CAMBER:
			{
				if (!hasUsableIMOTempData(useAverageData: true))
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float percentageDiff11 = getPercentageDiff(rightFrontAverageIMOLastLap[0], rightFrontAverageIMOLastLap[2]);
				int absoluteDiff11 = (int)Math.Round(rightFrontAverageIMOLastLap[0] - rightFrontAverageIMOLastLap[2]);
				Console.WriteLine("camber diff is " + absoluteDiff11 + " (" + percentageDiff11 + ") %");
				playCamberMessage(percentageDiff11, absoluteDiff11, folderRFIMOSame, folderRFInnerIsRunning, folderCelsiusHotterThanOuter, folderCelsiusColderThanOuter, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_LEFT_REAR_CAMBER_RIGHT_NOW:
			{
				if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float percentageDiff5 = getPercentageDiff(CrewChief.currentGameState.TyreData.RearLeft_RightTemp, CrewChief.currentGameState.TyreData.RearLeft_LeftTemp);
				int absoluteDiff5 = (int)Math.Round(CrewChief.currentGameState.TyreData.RearLeft_RightTemp - CrewChief.currentGameState.TyreData.RearLeft_LeftTemp);
				Console.WriteLine("camber diff is " + absoluteDiff5 + " (" + percentageDiff5 + ") %");
				playCamberMessage(percentageDiff5, absoluteDiff5, folderLRIMOSame, folderLRInnerIsRunning, folderCelsiusHotterThanOuter, folderCelsiusColderThanOuter, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_LEFT_REAR_CAMBER:
			{
				if (!hasUsableIMOTempData(useAverageData: true))
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float percentageDiff6 = getPercentageDiff(leftRearAverageIMOLastLap[0], leftRearAverageIMOLastLap[2]);
				int absoluteDiff6 = (int)Math.Round(leftRearAverageIMOLastLap[0] - leftRearAverageIMOLastLap[2]);
				Console.WriteLine("camber diff is " + absoluteDiff6 + " (" + percentageDiff6 + ") %");
				playCamberMessage(percentageDiff6, absoluteDiff6, folderLRIMOSame, folderLRInnerIsRunning, folderCelsiusHotterThanOuter, folderCelsiusColderThanOuter, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_RIGHT_REAR_CAMBER_RIGHT_NOW:
			{
				if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float percentageDiff3 = getPercentageDiff(CrewChief.currentGameState.TyreData.RearRight_LeftTemp, CrewChief.currentGameState.TyreData.RearRight_RightTemp);
				int absoluteDiff3 = (int)Math.Round(CrewChief.currentGameState.TyreData.RearRight_LeftTemp - CrewChief.currentGameState.TyreData.RearRight_RightTemp);
				Console.WriteLine("camber diff is " + absoluteDiff3 + " (" + percentageDiff3 + ") %");
				playCamberMessage(percentageDiff3, absoluteDiff3, folderRRIMOSame, folderRRInnerIsRunning, folderCelsiusHotterThanOuter, folderCelsiusColderThanOuter, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_RIGHT_REAR_CAMBER:
			{
				if (!hasUsableIMOTempData(useAverageData: true))
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float percentageDiff12 = getPercentageDiff(rightRearAverageIMOLastLap[0], rightRearAverageIMOLastLap[2]);
				int absoluteDiff12 = (int)Math.Round(rightRearAverageIMOLastLap[0] - rightRearAverageIMOLastLap[2]);
				Console.WriteLine("camber diff is " + absoluteDiff12 + " (" + percentageDiff12 + ") %");
				playCamberMessage(percentageDiff12, absoluteDiff12, folderRRIMOSame, folderRRInnerIsRunning, folderCelsiusHotterThanOuter, folderCelsiusColderThanOuter, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_FRONT_CAMBER_RIGHT_NOW:
			{
				if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float num7 = (CrewChief.currentGameState.TyreData.FrontLeft_RightTemp + CrewChief.currentGameState.TyreData.FrontRight_LeftTemp) / 2f;
				float num8 = (CrewChief.currentGameState.TyreData.FrontLeft_LeftTemp + CrewChief.currentGameState.TyreData.FrontRight_RightTemp) / 2f;
				float percentageDiff9 = getPercentageDiff(num7, num8);
				int absoluteDiff9 = (int)Math.Round(num7 - num8);
				Console.WriteLine("camber diff is " + absoluteDiff9 + " (" + percentageDiff9 + ") %");
				playCamberMessage(percentageDiff9, absoluteDiff9, folderAverageFrontsIMOSame, folderAverageFrontInnerTempsIntro, folderCelsiusHotterThanOuters, folderCelsiusColderThanOuters, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_FRONT_CAMBER:
			{
				if (!hasUsableIMOTempData(useAverageData: true))
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float num9 = (leftFrontAverageIMOLastLap[0] + rightFrontAverageIMOLastLap[0]) / 2f;
				float num10 = (leftFrontAverageIMOLastLap[2] + leftFrontAverageIMOLastLap[2]) / 2f;
				float percentageDiff10 = getPercentageDiff(num9, num10);
				int absoluteDiff10 = (int)Math.Round(num9 - num10);
				Console.WriteLine("camber diff from average is " + absoluteDiff10 + " (" + percentageDiff10 + ") %");
				playCamberMessage(percentageDiff10, absoluteDiff10, folderAverageFrontsIMOSame, folderAverageFrontInnerTempsIntro, folderCelsiusHotterThanOuters, folderCelsiusColderThanOuters, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_REAR_CAMBER_RIGHT_NOW:
			{
				if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float num5 = (CrewChief.currentGameState.TyreData.RearLeft_RightTemp + CrewChief.currentGameState.TyreData.RearRight_LeftTemp) / 2f;
				float num6 = (CrewChief.currentGameState.TyreData.RearLeft_LeftTemp + CrewChief.currentGameState.TyreData.RearRight_RightTemp) / 2f;
				float percentageDiff4 = getPercentageDiff(num5, num6);
				int absoluteDiff4 = (int)Math.Round(num5 - num6);
				Console.WriteLine("camber diff is " + absoluteDiff4 + " (" + percentageDiff4 + ") %");
				playCamberMessage(percentageDiff4, absoluteDiff4, folderAverageRearsIMOSame, folderAverageRearInnerTempsIntro, folderCelsiusHotterThanOuters, folderCelsiusColderThanOuters, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOWS_MY_REAR_CAMBER:
			{
				if (!hasUsableIMOTempData(useAverageData: true))
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					break;
				}
				float num3 = (leftRearAverageIMOLastLap[0] + rightRearAverageIMOLastLap[0]) / 2f;
				float num4 = (leftRearAverageIMOLastLap[2] + leftRearAverageIMOLastLap[2]) / 2f;
				float percentageDiff2 = getPercentageDiff(num3, num4);
				int absoluteDiff2 = (int)Math.Round(num3 - num4);
				Console.WriteLine("camber diff is " + absoluteDiff2 + " (" + percentageDiff2 + ") %");
				playCamberMessage(percentageDiff2, absoluteDiff2, folderAverageRearsIMOSame, folderAverageRearInnerTempsIntro, folderCelsiusHotterThanOuters, folderCelsiusColderThanOuters, delayResponses);
				break;
			}
			case SpeechCommands.ID.HOW_ARE_MY_TYRE_PRESSURES_RIGHT_NOW:
				if (Game.ACC)
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(getACCPressureMessage(CornerData.Corners.FRONT_LEFT, useAverageData: false), getACCPressureMessage(CornerData.Corners.FRONT_RIGHT, useAverageData: false), getACCPressureMessage(CornerData.Corners.REAR_LEFT, useAverageData: false), getACCPressureMessage(CornerData.Corners.REAR_RIGHT, useAverageData: false)));
				}
				else if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				else
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(getPressureMessage(CornerData.Corners.FRONT_LEFT, useAverageData: false), getPressureMessage(CornerData.Corners.FRONT_RIGHT, useAverageData: false), getPressureMessage(CornerData.Corners.REAR_LEFT, useAverageData: false), getPressureMessage(CornerData.Corners.REAR_RIGHT, useAverageData: false)));
				}
				break;
			case SpeechCommands.ID.HOW_ARE_MY_TYRE_PRESSURES:
				if (Game.ACC)
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(getACCPressureMessage(CornerData.Corners.FRONT_LEFT, useAverageData: true), getACCPressureMessage(CornerData.Corners.FRONT_RIGHT, useAverageData: true), getACCPressureMessage(CornerData.Corners.REAR_LEFT, useAverageData: true), getACCPressureMessage(CornerData.Corners.REAR_RIGHT, useAverageData: true)));
				}
				else if (!hasUsableIMOTempData(useAverageData: true) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				else
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(getPressureMessage(CornerData.Corners.FRONT_LEFT, useAverageData: true), getPressureMessage(CornerData.Corners.FRONT_RIGHT, useAverageData: true), getPressureMessage(CornerData.Corners.REAR_LEFT, useAverageData: true), getPressureMessage(CornerData.Corners.REAR_RIGHT, useAverageData: true)));
				}
				break;
			case SpeechCommands.ID.HOW_ARE_MY_FRONT_TYRE_PRESSURES_RIGHT_NOW:
				if (Game.ACC)
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(getACCPressureMessage(CornerData.Corners.FRONT_LEFT, useAverageData: false), getACCPressureMessage(CornerData.Corners.FRONT_RIGHT, useAverageData: false), null, null));
				}
				else if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				else
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(getPressureMessage(CornerData.Corners.FRONT_LEFT, useAverageData: false), getPressureMessage(CornerData.Corners.FRONT_RIGHT, useAverageData: false), null, null));
				}
				break;
			case SpeechCommands.ID.HOW_ARE_MY_FRONT_TYRE_PRESSURES:
				if (Game.ACC)
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(getACCPressureMessage(CornerData.Corners.FRONT_LEFT, useAverageData: true), getACCPressureMessage(CornerData.Corners.FRONT_RIGHT, useAverageData: true), null, null));
				}
				else if (!hasUsableIMOTempData(useAverageData: true) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				else
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(getPressureMessage(CornerData.Corners.FRONT_LEFT, useAverageData: true), getPressureMessage(CornerData.Corners.FRONT_RIGHT, useAverageData: true), null, null));
				}
				break;
			case SpeechCommands.ID.HOW_ARE_MY_REAR_TYRE_PRESSURES_RIGHT_NOW:
				if (Game.ACC)
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(null, null, getACCPressureMessage(CornerData.Corners.REAR_LEFT, useAverageData: false), getACCPressureMessage(CornerData.Corners.REAR_RIGHT, useAverageData: false)));
				}
				else if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				else
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(null, null, getPressureMessage(CornerData.Corners.REAR_LEFT, useAverageData: false), getPressureMessage(CornerData.Corners.REAR_RIGHT, useAverageData: false)));
				}
				break;
			case SpeechCommands.ID.HOW_ARE_MY_REAR_TYRE_PRESSURES:
				if (Game.ACC)
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(null, null, getACCPressureMessage(CornerData.Corners.REAR_LEFT, useAverageData: true), getACCPressureMessage(CornerData.Corners.REAR_RIGHT, useAverageData: true)));
				}
				else if (!hasUsableIMOTempData(useAverageData: true) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				else
				{
					playPressureMessage(delayResponses, aggregatePressureMessages(null, null, getPressureMessage(CornerData.Corners.REAR_LEFT, useAverageData: true), getPressureMessage(CornerData.Corners.REAR_RIGHT, useAverageData: true)));
				}
				break;
			case SpeechCommands.ID.WHAT_ARE_MY_TYRE_PRESSURES:
				reportCurrentTyrePressures();
				break;
			case SpeechCommands.ID.WHAT_ARE_MY_LEFT_FRONT_SURFACE_TEMPS:
				if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("left front surface temps", 0, AbstractEvent.MessageContents(convertTemp(CrewChief.currentGameState.TyreData.FrontLeft_LeftTemp, 1), convertTemp(CrewChief.currentGameState.TyreData.FrontLeft_CenterTemp, 1), convertTemp(CrewChief.currentGameState.TyreData.FrontLeft_RightTemp, 1), getTempUnit())));
				}
				break;
			case SpeechCommands.ID.WHAT_ARE_MY_RIGHT_FRONT_SURFACE_TEMPS:
				if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("right front surface temps", 0, AbstractEvent.MessageContents(convertTemp(CrewChief.currentGameState.TyreData.FrontRight_RightTemp, 1), convertTemp(CrewChief.currentGameState.TyreData.FrontRight_CenterTemp, 1), convertTemp(CrewChief.currentGameState.TyreData.FrontRight_LeftTemp, 1), getTempUnit())));
				}
				break;
			case SpeechCommands.ID.WHAT_ARE_MY_LEFT_REAR_SURFACE_TEMPS:
				if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("left rear surface temps", 0, AbstractEvent.MessageContents(convertTemp(CrewChief.currentGameState.TyreData.RearLeft_LeftTemp, 1), convertTemp(CrewChief.currentGameState.TyreData.RearLeft_CenterTemp, 1), convertTemp(CrewChief.currentGameState.TyreData.RearLeft_RightTemp, 1), getTempUnit())));
				}
				break;
			case SpeechCommands.ID.WHAT_ARE_MY_RIGHT_REAR_SURFACE_TEMPS:
				if (!hasUsableIMOTempData(useAverageData: false) || CrewChief.currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("right front surface temps", 0, AbstractEvent.MessageContents(convertTemp(CrewChief.currentGameState.TyreData.RearRight_RightTemp, 1), convertTemp(CrewChief.currentGameState.TyreData.RearRight_CenterTemp, 1), convertTemp(CrewChief.currentGameState.TyreData.RearRight_LeftTemp, 1), getTempUnit())));
				}
				break;
			case SpeechCommands.ID.HOW_MANY_LAPS_ON_TYRE_SET:
			{
				string[] hOW_MANY_LAPS_ON_TYRE_SET = SpeechRecogniser.HOW_MANY_LAPS_ON_TYRE_SET;
				foreach (string text in hOW_MANY_LAPS_ON_TYRE_SET)
				{
					if (voiceMessage.StartsWith(text))
					{
						voiceMessage = voiceMessage.Substring(text.Length);
						break;
					}
				}
				int num = extractInt(voiceMessage) - 1;
				if (num > -1 && CrewChief.currentGameState != null && num <= CrewChief.currentGameState.TyreData.lapsPerSet.Length)
				{
					int integer = CrewChief.currentGameState.TyreData.lapsPerSet[num];
					audioPlayer.playMessageImmediately(new QueuedMessage("laps_on_tyre_set_" + num, 0, AbstractEvent.MessageContents(MessageFragment.Integer(integer, MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)), Battery.folderLaps)));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				break;
			}
			}
		}

		private static int extractInt(string commandFragment)
		{
			foreach (KeyValuePair<string[], int> item in SpeechRecogniser.numberToNumber)
			{
				string[] key = item.Key;
				foreach (string text in key)
				{
					if (commandFragment.Trim() == text)
					{
						return item.Value;
					}
				}
			}
			return -1;
		}

		private void playPressureMessage(bool allowDelayedResponse, string folder)
		{
			playPressureMessage(allowDelayedResponse, new string[1] { folder });
		}

		private void playPressureMessage(bool allowDelayedResponse, string[] folders)
		{
			List<MessageFragment> fragments = new List<MessageFragment>();
			Array.ForEach(folders, delegate(string f)
			{
				fragments.Add(MessageFragment.Text(f));
			});
			if (fragments.Count > 0)
			{
				QueuedMessage queuedMessage = new QueuedMessage("pressures", 0, fragments);
				if (delayResponses && Utilities.random.Next(10) >= 2 && SoundCache.availableSounds.Contains("acknowledge/stand_by"))
				{
					audioPlayer.pauseQueueAndPlayDelayedImmediateMessage(queuedMessage, 5, 7);
				}
				else
				{
					audioPlayer.playMessageImmediately(queuedMessage);
				}
			}
		}

		private string getPressureMessage(CornerData.Corners corners, bool useAverageData)
		{
			switch (corners)
			{
			case CornerData.Corners.FRONT_LEFT:
			{
				float num = (useAverageData ? (leftFrontAverageIMOLastLap[0] + leftFrontAverageIMOLastLap[2] / 2f) : ((CrewChief.currentGameState.TyreData.FrontLeft_LeftTemp + CrewChief.currentGameState.TyreData.FrontLeft_RightTemp) / 2f));
				float num2 = (useAverageData ? leftFrontAverageIMOLastLap[1] : CrewChief.currentGameState.TyreData.FrontLeft_CenterTemp);
				float num3 = 100f * (num2 - num) / num2;
				if (num3 > 10f)
				{
					return folderLeftFrontPressureVeryHigh;
				}
				if (num3 > 4f)
				{
					return folderLeftFrontPressureHigh;
				}
				if (num3 < 4f)
				{
					return folderLeftFrontPressureLow;
				}
				if (num3 < 10f)
				{
					return folderLeftFrontPressureVeryLow;
				}
				return folderLeftFrontPressureOK;
			}
			case CornerData.Corners.FRONT_RIGHT:
			{
				float num = (useAverageData ? (rightFrontAverageIMOLastLap[0] + rightFrontAverageIMOLastLap[2] / 2f) : ((CrewChief.currentGameState.TyreData.FrontRight_LeftTemp + CrewChief.currentGameState.TyreData.FrontRight_RightTemp) / 2f));
				float num2 = (useAverageData ? leftFrontAverageIMOLastLap[1] : CrewChief.currentGameState.TyreData.FrontLeft_CenterTemp);
				float num3 = 100f * (num2 - num) / num2;
				if (num3 > 10f)
				{
					return folderRightFrontPressureVeryHigh;
				}
				if (num3 > 4f)
				{
					return folderRightFrontPressureHigh;
				}
				if (num3 < 4f)
				{
					return folderRightFrontPressureLow;
				}
				if (num3 < 10f)
				{
					return folderRightFrontPressureVeryLow;
				}
				return folderRightFrontPressureOK;
			}
			case CornerData.Corners.REAR_LEFT:
			{
				float num = (useAverageData ? (leftRearAverageIMOLastLap[0] + leftRearAverageIMOLastLap[2] / 2f) : ((CrewChief.currentGameState.TyreData.RearLeft_LeftTemp + CrewChief.currentGameState.TyreData.RearLeft_RightTemp) / 2f));
				float num2 = (useAverageData ? leftFrontAverageIMOLastLap[1] : CrewChief.currentGameState.TyreData.FrontLeft_CenterTemp);
				float num3 = 100f * (num2 - num) / num2;
				if (num3 > 10f)
				{
					return folderLeftRearPressureVeryHigh;
				}
				if (num3 > 4f)
				{
					return folderLeftRearPressureHigh;
				}
				if (num3 < 4f)
				{
					return folderLeftRearPressureLow;
				}
				if (num3 < 10f)
				{
					return folderLeftRearPressureVeryLow;
				}
				return folderLeftRearPressureOK;
			}
			case CornerData.Corners.REAR_RIGHT:
			{
				float num = (useAverageData ? (rightRearAverageIMOLastLap[0] + rightRearAverageIMOLastLap[2] / 2f) : ((CrewChief.currentGameState.TyreData.RearRight_LeftTemp + CrewChief.currentGameState.TyreData.RearRight_RightTemp) / 2f));
				float num2 = (useAverageData ? leftFrontAverageIMOLastLap[1] : CrewChief.currentGameState.TyreData.FrontLeft_CenterTemp);
				float num3 = 100f * (num2 - num) / num2;
				if (num3 > 10f)
				{
					return folderRightRearPressureVeryHigh;
				}
				if (num3 > 4f)
				{
					return folderRightRearPressureHigh;
				}
				if (num3 < 4f)
				{
					return folderRightRearPressureLow;
				}
				if (num3 < 10f)
				{
					return folderRightRearPressureVeryLow;
				}
				return folderRightRearPressureOK;
			}
			default:
				return null;
			}
		}

		private string getACCPressureMessage(CornerData.Corners corners, bool useAverageData)
		{
			int num;
			float num2;
			if (CrewChief.currentGameState.TyreData.TyreTypeName != null && CrewChief.currentGameState.TyreData.TyreTypeName.Length != 0)
			{
				num = ((!CrewChief.currentGameState.TyreData.TyreTypeName.ToLowerInvariant().Contains("wet")) ? 1 : 0);
				if (num == 0)
				{
					num2 = 227.502f;
					goto IL_0060;
				}
			}
			else
			{
				num = 1;
			}
			num2 = 198.5472f;
			goto IL_0060;
			IL_0060:
			float num3 = num2;
			float num4 = ((num != 0) ? 195.10019f : 220.608f);
			float num5 = ((num != 0) ? 187.5168f : 199.926f);
			float num6 = ((num != 0) ? 179.244f : 189.585f);
			float num7 = (useAverageData ? leftFrontAveragePressureLastLap : CrewChief.currentGameState.TyreData.FrontLeftPressure);
			float num8 = (useAverageData ? rightFrontAveragePressureLastLap : CrewChief.currentGameState.TyreData.FrontRightPressure);
			float num9 = (useAverageData ? leftRearAveragePressureLastLap : CrewChief.currentGameState.TyreData.RearLeftPressure);
			float num10 = (useAverageData ? rightRearAveragePressureLastLap : CrewChief.currentGameState.TyreData.RearRightPressure);
			switch (corners)
			{
			case CornerData.Corners.FRONT_LEFT:
				if (num7 > num3)
				{
					return folderLeftFrontPressureVeryHigh;
				}
				if (num7 > num4)
				{
					return folderLeftFrontPressureHigh;
				}
				if (num7 < num5)
				{
					return folderLeftFrontPressureLow;
				}
				if (num7 < num6)
				{
					return folderLeftFrontPressureVeryLow;
				}
				return folderLeftFrontPressureOK;
			case CornerData.Corners.FRONT_RIGHT:
				if (num8 > num3)
				{
					return folderRightFrontPressureVeryHigh;
				}
				if (num8 > num4)
				{
					return folderRightFrontPressureHigh;
				}
				if (num8 < num5)
				{
					return folderRightFrontPressureLow;
				}
				if (num8 < num6)
				{
					return folderRightFrontPressureVeryLow;
				}
				return folderRightFrontPressureOK;
			case CornerData.Corners.REAR_LEFT:
				if (num9 > num3)
				{
					return folderLeftRearPressureVeryHigh;
				}
				if (num9 > num4)
				{
					return folderLeftRearPressureHigh;
				}
				if (num9 < num5)
				{
					return folderLeftRearPressureLow;
				}
				if (num9 < num6)
				{
					return folderLeftRearPressureVeryLow;
				}
				return folderLeftRearPressureOK;
			case CornerData.Corners.REAR_RIGHT:
				if (num10 > num3)
				{
					return folderRightRearPressureVeryHigh;
				}
				if (num10 > num4)
				{
					return folderRightRearPressureHigh;
				}
				if (num10 < num5)
				{
					return folderRightRearPressureLow;
				}
				if (num10 < num6)
				{
					return folderRightRearPressureVeryLow;
				}
				return folderRightRearPressureOK;
			default:
				return null;
			}
		}

		private void playCamberMessage(float percentageDiff, int absoluteDiff, string folderSame, string folderDiffIntro, string folderHotterThanOutersOutro, string folderColderThanOutersOutro, bool allowDelayedResponse)
		{
			float[] targetCamberPercentDiff = getTargetCamberPercentDiff();
			float num = targetCamberPercentDiff[0];
			float num2 = targetCamberPercentDiff[1];
			QueuedMessage queuedMessage = ((Math.Abs(absoluteDiff) <= 1) ? new QueuedMessage("imo_diff", 0, AbstractEvent.MessageContents(folderSame, folderNeedMoreNegativeCamber)) : ((percentageDiff < -1f) ? new QueuedMessage("imo_diff", 0, AbstractEvent.MessageContents(folderDiffIntro, absoluteDiff * -1, folderColderThanOutersOutro, folderNeedMoreNegativeCamber)) : ((percentageDiff > num2) ? new QueuedMessage("imo_diff", 0, AbstractEvent.MessageContents(folderDiffIntro, absoluteDiff, folderHotterThanOutersOutro, folderNeedMorePositiveCamber)) : ((!(percentageDiff < num)) ? new QueuedMessage("imo_diff", 0, AbstractEvent.MessageContents(folderDiffIntro, absoluteDiff, folderHotterThanOutersOutro, folderCamberOK)) : new QueuedMessage("imo_diff", 0, AbstractEvent.MessageContents(folderDiffIntro, absoluteDiff, folderHotterThanOutersOutro, folderNeedMoreNegativeCamber))))));
			if (queuedMessage != null)
			{
				if (delayResponses && Utilities.random.Next(10) >= 2 && SoundCache.availableSounds.Contains("acknowledge/stand_by"))
				{
					audioPlayer.pauseQueueAndPlayDelayedImmediateMessage(queuedMessage, 5, 7);
				}
				else
				{
					audioPlayer.playMessageImmediately(queuedMessage);
				}
			}
		}

		private float getPercentageDiff(float inner, float outer)
		{
			return 100f * (inner - outer) / outer;
		}

		private float[] getTargetCamberPercentDiff()
		{
			if (idealCamberValues.TryGetValue(CrewChief.currentGameState.TyreData.FrontLeftTyreType, out var value))
			{
				return value;
			}
			return defaultTargetIODifference;
		}

		private bool hasUsableIMOTempData(bool useAverageData)
		{
			if (!Game.F1_20S)
			{
				if (!useAverageData || leftFrontAverageIMOLastLap == null || rightFrontAverageIMOLastLap == null || leftRearAverageIMOLastLap == null || rightRearAverageIMOLastLap == null)
				{
					if (!useAverageData && CrewChief.currentGameState != null && CrewChief.currentGameState.TyreData != null)
					{
						return CrewChief.currentGameState.TyreData.FrontLeft_LeftTemp > 30f;
					}
					return false;
				}
				return true;
			}
			return false;
		}

		private void addTyreTempWarningMessages(CornerData.Corners corners, TyreTemp tyreTemp, List<MessageFragment> messageContents, bool includeRears)
		{
			switch (corners)
			{
			case CornerData.Corners.ALL:
				switch (tyreTemp)
				{
				case TyreTemp.COLD:
					messageContents.Add(MessageFragment.Text(folderColdTyresAllRound));
					break;
				case TyreTemp.HOT:
					messageContents.Add(MessageFragment.Text(folderHotTyresAllRound));
					break;
				case TyreTemp.COOKING:
					messageContents.Add(MessageFragment.Text(folderCookingTyresAllRound));
					break;
				case TyreTemp.WARM:
					break;
				}
				break;
			case CornerData.Corners.FRONTS:
				switch (tyreTemp)
				{
				case TyreTemp.COLD:
					messageContents.Add(MessageFragment.Text(folderColdFrontTyres));
					break;
				case TyreTemp.HOT:
					messageContents.Add(MessageFragment.Text(folderHotFrontTyres));
					break;
				case TyreTemp.COOKING:
					messageContents.Add(MessageFragment.Text(folderCookingFrontTyres));
					break;
				case TyreTemp.WARM:
					break;
				}
				break;
			case CornerData.Corners.REARS:
				if (includeRears)
				{
					switch (tyreTemp)
					{
					case TyreTemp.COLD:
						messageContents.Add(MessageFragment.Text(folderColdRearTyres));
						break;
					case TyreTemp.HOT:
						messageContents.Add(MessageFragment.Text(folderHotRearTyres));
						break;
					case TyreTemp.COOKING:
						messageContents.Add(MessageFragment.Text(folderCookingRearTyres));
						break;
					case TyreTemp.WARM:
						break;
					}
				}
				break;
			case CornerData.Corners.LEFTS:
				if (!GlobalBehaviourSettings.useOvalLogic)
				{
					switch (tyreTemp)
					{
					case TyreTemp.COLD:
						messageContents.Add(MessageFragment.Text(folderColdLeftTyres));
						break;
					case TyreTemp.HOT:
						messageContents.Add(MessageFragment.Text(folderHotLeftTyres));
						break;
					case TyreTemp.COOKING:
						messageContents.Add(MessageFragment.Text(folderCookingLeftTyres));
						break;
					case TyreTemp.WARM:
						break;
					}
				}
				break;
			case CornerData.Corners.RIGHTS:
				switch (tyreTemp)
				{
				case TyreTemp.COLD:
					messageContents.Add(MessageFragment.Text(folderColdRightTyres));
					break;
				case TyreTemp.HOT:
					messageContents.Add(MessageFragment.Text(folderHotRightTyres));
					break;
				case TyreTemp.COOKING:
					messageContents.Add(MessageFragment.Text(folderCookingRightTyres));
					break;
				case TyreTemp.WARM:
					break;
				}
				break;
			case CornerData.Corners.FRONT_LEFT:
				if (!GlobalBehaviourSettings.useOvalLogic)
				{
					switch (tyreTemp)
					{
					case TyreTemp.HOT:
						messageContents.Add(MessageFragment.Text(folderHotLeftFrontTyre));
						break;
					case TyreTemp.COOKING:
						messageContents.Add(MessageFragment.Text(folderCookingLeftFrontTyre));
						break;
					}
				}
				break;
			case CornerData.Corners.FRONT_RIGHT:
				switch (tyreTemp)
				{
				case TyreTemp.HOT:
					messageContents.Add(MessageFragment.Text(folderHotRightFrontTyre));
					break;
				case TyreTemp.COOKING:
					messageContents.Add(MessageFragment.Text(folderCookingRightFrontTyre));
					break;
				}
				break;
			case CornerData.Corners.REAR_LEFT:
				if (includeRears && !GlobalBehaviourSettings.useOvalLogic)
				{
					switch (tyreTemp)
					{
					case TyreTemp.HOT:
						messageContents.Add(MessageFragment.Text(folderHotLeftRearTyre));
						break;
					case TyreTemp.COOKING:
						messageContents.Add(MessageFragment.Text(folderCookingLeftRearTyre));
						break;
					}
				}
				break;
			case CornerData.Corners.REAR_RIGHT:
				if (includeRears)
				{
					switch (tyreTemp)
					{
					case TyreTemp.HOT:
						messageContents.Add(MessageFragment.Text(folderHotRightRearTyre));
						break;
					case TyreTemp.COOKING:
						messageContents.Add(MessageFragment.Text(folderCookingRightRearTyre));
						break;
					}
				}
				break;
			}
		}

		private void addTyreConditionWarningMessages(CornerData.Corners corners, TyreCondition tyreCondition, List<MessageFragment> messageContents)
		{
			switch (corners)
			{
			case CornerData.Corners.ALL:
				switch (tyreCondition)
				{
				case TyreCondition.MINOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderMinorWearAllRound));
					break;
				case TyreCondition.MAJOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderWornAllRound));
					break;
				case TyreCondition.WORN_OUT:
					messageContents.Add(MessageFragment.Text(folderKnackeredAllRound));
					break;
				}
				break;
			case CornerData.Corners.FRONTS:
				switch (tyreCondition)
				{
				case TyreCondition.MINOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderMinorWearFronts));
					break;
				case TyreCondition.MAJOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderWornFronts));
					break;
				case TyreCondition.WORN_OUT:
					messageContents.Add(MessageFragment.Text(folderKnackeredFronts));
					break;
				}
				break;
			case CornerData.Corners.REARS:
				switch (tyreCondition)
				{
				case TyreCondition.MINOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderMinorWearRears));
					break;
				case TyreCondition.MAJOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderWornRears));
					break;
				case TyreCondition.WORN_OUT:
					messageContents.Add(MessageFragment.Text(folderKnackeredRears));
					break;
				}
				break;
			case CornerData.Corners.LEFTS:
				switch (tyreCondition)
				{
				case TyreCondition.MINOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderMinorWearLefts));
					break;
				case TyreCondition.MAJOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderWornLefts));
					break;
				case TyreCondition.WORN_OUT:
					messageContents.Add(MessageFragment.Text(folderKnackeredLefts));
					break;
				}
				break;
			case CornerData.Corners.RIGHTS:
				switch (tyreCondition)
				{
				case TyreCondition.MINOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderMinorWearRights));
					break;
				case TyreCondition.MAJOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderWornRights));
					break;
				case TyreCondition.WORN_OUT:
					messageContents.Add(MessageFragment.Text(folderKnackeredRights));
					break;
				}
				break;
			case CornerData.Corners.FRONT_LEFT:
				switch (tyreCondition)
				{
				case TyreCondition.MINOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderMinorWearLeftFront));
					break;
				case TyreCondition.MAJOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderWornLeftFront));
					break;
				case TyreCondition.WORN_OUT:
					messageContents.Add(MessageFragment.Text(folderKnackeredLeftFront));
					break;
				}
				break;
			case CornerData.Corners.FRONT_RIGHT:
				switch (tyreCondition)
				{
				case TyreCondition.MINOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderMinorWearRightFront));
					break;
				case TyreCondition.MAJOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderWornRightFront));
					break;
				case TyreCondition.WORN_OUT:
					messageContents.Add(MessageFragment.Text(folderKnackeredRightFront));
					break;
				}
				break;
			case CornerData.Corners.REAR_LEFT:
				switch (tyreCondition)
				{
				case TyreCondition.MINOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderMinorWearLeftRear));
					break;
				case TyreCondition.MAJOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderWornLeftRear));
					break;
				case TyreCondition.WORN_OUT:
					messageContents.Add(MessageFragment.Text(folderKnackeredLeftRear));
					break;
				}
				break;
			case CornerData.Corners.REAR_RIGHT:
				switch (tyreCondition)
				{
				case TyreCondition.MINOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderMinorWearRightRear));
					break;
				case TyreCondition.MAJOR_WEAR:
					messageContents.Add(MessageFragment.Text(folderWornRightRear));
					break;
				case TyreCondition.WORN_OUT:
					messageContents.Add(MessageFragment.Text(folderKnackeredRightRear));
					break;
				}
				break;
			}
		}

		private void addTyreFlatSpotWarningMessages(CornerData.Corners corners, TyreFlatSpotState tfss, List<MessageFragment> messageContents)
		{
			switch (corners)
			{
			case CornerData.Corners.ALL:
				if (tfss == TyreFlatSpotState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderFrontsFlatSpotted));
					messageContents.Add(MessageFragment.Text(folderRearsFlatSpotted));
				}
				break;
			case CornerData.Corners.FRONTS:
				if (tfss == TyreFlatSpotState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderFrontsFlatSpotted));
				}
				break;
			case CornerData.Corners.REARS:
				if (tfss == TyreFlatSpotState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderRearsFlatSpotted));
				}
				break;
			case CornerData.Corners.LEFTS:
				if (tfss == TyreFlatSpotState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderLeftFrontFlatSpotted));
					messageContents.Add(MessageFragment.Text(folderLeftRearFlatSpotted));
				}
				break;
			case CornerData.Corners.RIGHTS:
				if (tfss == TyreFlatSpotState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderRightFrontFlatSpotted));
					messageContents.Add(MessageFragment.Text(folderRightRearFlatSpotted));
				}
				break;
			case CornerData.Corners.FRONT_LEFT:
				if (tfss == TyreFlatSpotState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderLeftFrontFlatSpotted));
				}
				break;
			case CornerData.Corners.FRONT_RIGHT:
				if (tfss == TyreFlatSpotState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderRightFrontFlatSpotted));
				}
				break;
			case CornerData.Corners.REAR_LEFT:
				if (tfss == TyreFlatSpotState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderLeftRearFlatSpotted));
				}
				break;
			case CornerData.Corners.REAR_RIGHT:
				if (tfss == TyreFlatSpotState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderRightRearFlatSpotted));
				}
				break;
			}
		}

		private void addTyreDirtPickupStateWarningMessages(CornerData.Corners corners, TyreDirtPickupState tdps, List<MessageFragment> messageContents)
		{
			switch (corners)
			{
			case CornerData.Corners.ALL:
				if (tdps == TyreDirtPickupState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderAllTyresDirty));
				}
				break;
			case CornerData.Corners.LEFTS:
				if (tdps == TyreDirtPickupState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderLeftTyresDirty));
				}
				break;
			case CornerData.Corners.RIGHTS:
				if (tdps == TyreDirtPickupState.MAJOR)
				{
					messageContents.Add(MessageFragment.Text(folderRightTyresDirty));
				}
				break;
			}
		}

		private void addBrakeTempWarningMessages(CornerData.Corners corners, BrakeTemp brakeTemp, List<MessageFragment> messageContents, bool includeRears)
		{
			switch (corners)
			{
			case CornerData.Corners.ALL:
				switch (brakeTemp)
				{
				case BrakeTemp.COLD:
					if (!ignoreColdBrakesForClasses.Contains(CrewChief.currentGameState.carClass.carClassEnum))
					{
						messageContents.Add(MessageFragment.Text(folderColdBrakesAllRound));
					}
					break;
				case BrakeTemp.HOT:
					messageContents.Add(MessageFragment.Text(folderHotBrakesAllRound));
					break;
				case BrakeTemp.COOKING:
					messageContents.Add(MessageFragment.Text(folderCookingBrakesAllRound));
					break;
				case BrakeTemp.WARM:
					break;
				}
				break;
			case CornerData.Corners.FRONTS:
				switch (brakeTemp)
				{
				case BrakeTemp.COLD:
					if (!ignoreColdBrakesForClasses.Contains(CrewChief.currentGameState.carClass.carClassEnum))
					{
						messageContents.Add(MessageFragment.Text(folderColdFrontBrakes));
					}
					break;
				case BrakeTemp.HOT:
					messageContents.Add(MessageFragment.Text(folderHotFrontBrakes));
					break;
				case BrakeTemp.COOKING:
					messageContents.Add(MessageFragment.Text(folderCookingFrontBrakes));
					break;
				case BrakeTemp.WARM:
					break;
				}
				break;
			case CornerData.Corners.REARS:
				if (!includeRears)
				{
					break;
				}
				switch (brakeTemp)
				{
				case BrakeTemp.COLD:
					if (!ignoreColdBrakesForClasses.Contains(CrewChief.currentGameState.carClass.carClassEnum))
					{
						messageContents.Add(MessageFragment.Text(folderColdRearBrakes));
					}
					break;
				case BrakeTemp.HOT:
					messageContents.Add(MessageFragment.Text(folderHotRearBrakes));
					break;
				case BrakeTemp.COOKING:
					messageContents.Add(MessageFragment.Text(folderCookingRearBrakes));
					break;
				case BrakeTemp.WARM:
					break;
				}
				break;
			case CornerData.Corners.LEFTS:
			case CornerData.Corners.RIGHTS:
				break;
			}
		}

		private void addLockingAndSpinningData(TyreData tyreData, bool inPitLane, bool hasWheelMissingOrPuncture, long previousTicks, long currentTicks, bool isFWD)
		{
			if (hasWheelMissingOrPuncture || inPitLane)
			{
				return;
			}
			if (enableBrakeLockWarnings)
			{
				if (enableCornerSpecificLockingAndSpinningChecks)
				{
					leftFrontLockedList.Add(tyreData.LeftFrontIsLocked);
					rightFrontLockedList.Add(tyreData.RightFrontIsLocked);
					leftRearLockedList.Add(tyreData.LeftRearIsLocked);
					rightRearLockedList.Add(tyreData.RightRearIsLocked);
				}
				if (tyreData.LeftFrontIsLocked)
				{
					timeLeftFrontIsLockedForLap += (float)(currentTicks - previousTicks) / 10000000f;
				}
				if (tyreData.RightFrontIsLocked)
				{
					timeRightFrontIsLockedForLap += (float)(currentTicks - previousTicks) / 10000000f;
				}
				if (isFWD)
				{
					if (tyreData.LeftRearIsLocked && tyreData.RightRearIsLocked)
					{
						timeBothRearsAreLockedForLap += (float)(currentTicks - previousTicks) / 10000000f;
					}
				}
				else
				{
					if (tyreData.LeftRearIsLocked)
					{
						timeLeftRearIsLockedForLap += (float)(currentTicks - previousTicks) / 10000000f;
					}
					if (tyreData.RightRearIsLocked)
					{
						timeRightRearIsLockedForLap += (float)(currentTicks - previousTicks) / 10000000f;
					}
				}
			}
			if (enableWheelSpinWarnings)
			{
				if (tyreData.LeftFrontIsSpinning)
				{
					timeLeftFrontIsSpinningForLap += (float)(currentTicks - previousTicks) / 10000000f;
				}
				if (tyreData.RightFrontIsSpinning)
				{
					timeRightFrontIsSpinningForLap += (float)(currentTicks - previousTicks) / 10000000f;
				}
				if (tyreData.LeftRearIsSpinning)
				{
					timeLeftRearIsSpinningForLap += (float)(currentTicks - previousTicks) / 10000000f;
				}
				if (tyreData.RightRearIsSpinning)
				{
					timeRightRearIsSpinningForLap += (float)(currentTicks - previousTicks) / 10000000f;
				}
			}
		}

		private bool hasWheelMissingOrPuncture(GameStateData currentState)
		{
			if (currentState.TyreData.LeftFrontAttached && currentState.TyreData.RightFrontAttached && currentState.TyreData.LeftRearAttached && currentState.TyreData.RightRearAttached)
			{
				return DamageReporting.getPuncture(currentState.TyreData) != CornerData.Corners.NONE;
			}
			return true;
		}

		private CornerData.Corners getMostLockedWheelForLap()
		{
			CornerData.Corners result = CornerData.Corners.NONE;
			float num = 0f;
			if (timeLeftFrontIsLockedForLap > num)
			{
				num = timeLeftFrontIsLockedForLap;
				result = CornerData.Corners.FRONT_LEFT;
			}
			if (timeRightFrontIsLockedForLap > num)
			{
				num = timeRightFrontIsLockedForLap;
				result = CornerData.Corners.FRONT_RIGHT;
			}
			if (timeLeftRearIsLockedForLap > num)
			{
				num = timeLeftRearIsLockedForLap;
				result = CornerData.Corners.REAR_LEFT;
			}
			if (timeRightRearIsLockedForLap > num)
			{
				result = CornerData.Corners.REAR_RIGHT;
			}
			return result;
		}

		private bool checkLocking(bool isFWD)
		{
			bool result = false;
			int num = Utilities.random.Next(0, 5);
			if (!warnedOnLockingForLap)
			{
				CornerData.Corners mostLockedWheelForLap = getMostLockedWheelForLap();
				if (mostLockedWheelForLap == CornerData.Corners.FRONT_LEFT && timeLeftFrontIsLockedForLap > totalLockupThresholdForNextLap)
				{
					warnedOnLockingForLap = true;
					if (timeRightFrontIsLockedForLap > totalLockupThresholdForNextLap / 2f)
					{
						audioPlayer.playMessage(new QueuedMessage(folderLockingFrontsForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
					else
					{
						audioPlayer.playMessage(new QueuedMessage(folderLockingLeftFrontForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
				}
				else if (mostLockedWheelForLap == CornerData.Corners.FRONT_RIGHT && timeRightFrontIsLockedForLap > totalLockupThresholdForNextLap)
				{
					warnedOnLockingForLap = true;
					if (timeLeftFrontIsLockedForLap > totalLockupThresholdForNextLap / 2f)
					{
						audioPlayer.playMessage(new QueuedMessage(folderLockingFrontsForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
					else
					{
						audioPlayer.playMessage(new QueuedMessage(folderLockingRightFrontForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
				}
				else if ((mostLockedWheelForLap == CornerData.Corners.REAR_LEFT || mostLockedWheelForLap == CornerData.Corners.REAR_RIGHT) && isFWD && timeBothRearsAreLockedForLap > totalLockupThresholdForNextLap * 2f)
				{
					warnedOnLockingForLap = true;
					audioPlayer.playMessage(new QueuedMessage(folderLockingRearsForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
					result = true;
				}
				else if (mostLockedWheelForLap == CornerData.Corners.REAR_LEFT && !isFWD && timeLeftRearIsLockedForLap > totalLockupThresholdForNextLap)
				{
					warnedOnLockingForLap = true;
					if (timeRightRearIsLockedForLap > totalLockupThresholdForNextLap / 2f)
					{
						audioPlayer.playMessage(new QueuedMessage(folderLockingRearsForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
					else
					{
						audioPlayer.playMessage(new QueuedMessage(folderLockingLeftRearForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
				}
				else if (mostLockedWheelForLap == CornerData.Corners.REAR_RIGHT && !isFWD && timeRightRearIsLockedForLap > totalLockupThresholdForNextLap)
				{
					warnedOnLockingForLap = true;
					if (timeLeftRearIsLockedForLap > totalLockupThresholdForNextLap / 2f)
					{
						audioPlayer.playMessage(new QueuedMessage(folderLockingRearsForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
					else
					{
						audioPlayer.playMessage(new QueuedMessage(folderLockingRightRearForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
				}
			}
			return result;
		}

		private CornerData.Corners getMostSpinningWheelForLap()
		{
			CornerData.Corners result = CornerData.Corners.NONE;
			float num = 0f;
			if (timeLeftFrontIsSpinningForLap > num)
			{
				num = timeLeftFrontIsSpinningForLap;
				result = CornerData.Corners.FRONT_LEFT;
			}
			if (timeRightFrontIsSpinningForLap > num)
			{
				num = timeRightFrontIsSpinningForLap;
				result = CornerData.Corners.FRONT_RIGHT;
			}
			if (timeLeftRearIsSpinningForLap > num)
			{
				num = timeLeftRearIsSpinningForLap;
				result = CornerData.Corners.REAR_LEFT;
			}
			if (timeRightRearIsSpinningForLap > num)
			{
				result = CornerData.Corners.REAR_RIGHT;
			}
			return result;
		}

		private bool checkWheelSpinning(bool isFWD, bool isRWD)
		{
			bool result = false;
			int num = Utilities.random.Next(0, 5);
			if (!warnedOnWheelspinForLap)
			{
				CornerData.Corners mostSpinningWheelForLap = getMostSpinningWheelForLap();
				if (mostSpinningWheelForLap == CornerData.Corners.FRONT_LEFT && !isRWD && timeLeftFrontIsSpinningForLap > totalWheelspinThresholdForNextLap)
				{
					warnedOnWheelspinForLap = true;
					if (timeRightFrontIsSpinningForLap > totalWheelspinThresholdForNextLap / 2f)
					{
						audioPlayer.playMessage(new QueuedMessage(folderSpinningFrontsForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
					else
					{
						audioPlayer.playMessage(new QueuedMessage(folderSpinningLeftFrontForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
				}
				else if (mostSpinningWheelForLap == CornerData.Corners.FRONT_RIGHT && !isRWD && timeRightFrontIsSpinningForLap > totalWheelspinThresholdForNextLap)
				{
					warnedOnWheelspinForLap = true;
					if (timeLeftFrontIsSpinningForLap > totalWheelspinThresholdForNextLap / 2f)
					{
						audioPlayer.playMessage(new QueuedMessage(folderSpinningFrontsForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
					else
					{
						audioPlayer.playMessage(new QueuedMessage(folderSpinningRightFrontForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
				}
				else if (mostSpinningWheelForLap == CornerData.Corners.REAR_LEFT && !isFWD && timeLeftRearIsSpinningForLap > totalWheelspinThresholdForNextLap)
				{
					warnedOnWheelspinForLap = true;
					if (timeRightRearIsSpinningForLap > totalWheelspinThresholdForNextLap / 2f)
					{
						audioPlayer.playMessage(new QueuedMessage(folderSpinningRearsForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
					else
					{
						audioPlayer.playMessage(new QueuedMessage(folderSpinningLeftRearForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
				}
				else if (mostSpinningWheelForLap == CornerData.Corners.REAR_RIGHT && !isFWD && timeRightRearIsSpinningForLap > totalWheelspinThresholdForNextLap)
				{
					warnedOnWheelspinForLap = true;
					if (timeLeftRearIsSpinningForLap > totalWheelspinThresholdForNextLap / 2f)
					{
						audioPlayer.playMessage(new QueuedMessage(folderSpinningRearsForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
					else
					{
						audioPlayer.playMessage(new QueuedMessage(folderSpinningRightRearForLapWarning, num + 6, null, null, null, null, num, this, null, 0));
						result = true;
					}
				}
			}
			return result;
		}

		private WheelsLockedEnum getCornerEntryLocking(int minTicksLocked, bool isFWD)
		{
			int num = (int)Math.Ceiling((float)minTicksLocked / 2f);
			bool flag = false;
			bool flag2 = false;
			bool flag3 = false;
			bool flag4 = false;
			bool flag5 = false;
			bool flag6 = false;
			int num2 = 0;
			int num3 = leftFrontLockedList.Count - 1;
			while (num3 >= ticksToCheckForLocking && num3 >= 0)
			{
				if (leftFrontLockedList[num3])
				{
					num2++;
				}
				num3--;
			}
			flag = num2 >= minTicksLocked;
			num2 = 0;
			int num4 = rightFrontLockedList.Count - 1;
			while (num4 >= ticksToCheckForLocking && num4 >= 0)
			{
				if (rightFrontLockedList[num4])
				{
					num2++;
				}
				num4--;
			}
			flag2 = num2 >= minTicksLocked;
			num2 = 0;
			int num5 = leftRearLockedList.Count - 1;
			while (num5 >= ticksToCheckForLocking && num5 >= 0)
			{
				if (leftRearLockedList[num5])
				{
					num2++;
				}
				num5--;
			}
			flag3 = num2 >= (isFWD ? (minTicksLocked * 4) : minTicksLocked);
			flag5 = num2 >= num;
			num2 = 0;
			int num6 = rightRearLockedList.Count - 1;
			while (num6 >= ticksToCheckForLocking && num6 >= 0)
			{
				if (rightRearLockedList[num6])
				{
					num2++;
				}
				num6--;
			}
			flag4 = num2 >= (isFWD ? (minTicksLocked * 4) : minTicksLocked);
			flag6 = num2 >= num;
			if (flag && flag2)
			{
				return WheelsLockedEnum.FRONTS;
			}
			if (flag)
			{
				return WheelsLockedEnum.LEFT_FRONT;
			}
			if (flag2)
			{
				return WheelsLockedEnum.RIGHT_FRONT;
			}
			if ((flag3 && flag6) || (flag4 && flag5))
			{
				return WheelsLockedEnum.REARS;
			}
			return WheelsLockedEnum.NONE;
		}

		private List<TyrePerformanceContainer> getRelativeTyrePerformance()
		{
			List<TyrePerformanceContainer> list = new List<TyrePerformanceContainer>();
			if (playerClassSessionBestLapTimeByTyre != null && playerClassSessionBestLapTimeByTyre.Count > 1)
			{
				foreach (TyreType value3 in Enum.GetValues(typeof(TyreType)))
				{
					float value = -1f;
					if (!playerClassSessionBestLapTimeByTyre.TryGetValue(value3, out value))
					{
						continue;
					}
					foreach (TyreType value4 in Enum.GetValues(typeof(TyreType)))
					{
						float value2 = -1f;
						if (value3 != value4 && playerClassSessionBestLapTimeByTyre.TryGetValue(value4, out value2) && !comparisonAlreadyPresent(list, value3, value4))
						{
							if (value > value2)
							{
								list.Add(new TyrePerformanceContainer(value4, value3, value - value2));
							}
							else if (value < value2)
							{
								list.Add(new TyrePerformanceContainer(value3, value4, value2 - value));
							}
							break;
						}
					}
				}
			}
			return list;
		}

		private bool comparisonAlreadyPresent(List<TyrePerformanceContainer> performanceData, TyreType tyreType1, TyreType tyreType2)
		{
			foreach (TyrePerformanceContainer performanceDatum in performanceData)
			{
				if ((performanceDatum.type1 == tyreType1 && performanceDatum.type2 == tyreType2) || (performanceDatum.type2 == tyreType1 && performanceDatum.type1 == tyreType2))
				{
					return true;
				}
			}
			return false;
		}

		private string[] aggregatePressureMessages(string frontLeft, string frontRight, string rearLeft, string rearRight)
		{
			List<string> list = new List<string>();
			if (frontLeft != null && frontRight != null)
			{
				if (frontLeft == folderLeftFrontPressureVeryHigh && frontRight == folderRightFrontPressureVeryHigh)
				{
					list.Add(folderFrontPressuresVeryHigh);
				}
				else if (frontLeft == folderLeftFrontPressureHigh && frontRight == folderRightFrontPressureHigh)
				{
					list.Add(folderFrontPressuresHigh);
				}
				else if (frontLeft == folderLeftFrontPressureOK && frontRight == folderRightFrontPressureOK)
				{
					list.Add(folderFrontPressuresOK);
				}
				else if (frontLeft == folderLeftFrontPressureLow && frontRight == folderRightFrontPressureLow)
				{
					list.Add(folderFrontPressuresLow);
				}
				else if (frontLeft == folderLeftFrontPressureVeryLow && frontRight == folderRightFrontPressureVeryLow)
				{
					list.Add(folderFrontPressuresVeryLow);
				}
				else
				{
					list.Add(frontLeft);
					list.Add(frontRight);
				}
			}
			if (rearLeft != null && rearRight != null)
			{
				if (rearLeft == folderLeftRearPressureVeryHigh && rearRight == folderRightRearPressureVeryHigh)
				{
					list.Add(folderRearPressuresVeryHigh);
				}
				else if (rearLeft == folderLeftRearPressureHigh && rearRight == folderRightRearPressureHigh)
				{
					list.Add(folderRearPressuresHigh);
				}
				else if (rearLeft == folderLeftRearPressureOK && rearRight == folderRightRearPressureOK)
				{
					list.Add(folderRearPressuresOK);
				}
				else if (rearLeft == folderLeftRearPressureLow && rearRight == folderRightRearPressureLow)
				{
					list.Add(folderRearPressuresLow);
				}
				else if (rearLeft == folderLeftRearPressureVeryLow && rearRight == folderRightRearPressureVeryLow)
				{
					list.Add(folderRearPressuresVeryLow);
				}
				else
				{
					list.Add(rearLeft);
					list.Add(rearRight);
				}
			}
			return list.ToArray();
		}
	}
}
