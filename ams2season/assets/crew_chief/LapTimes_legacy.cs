using System;
using System.Collections.Generic;
using System.Linq;
using CrewChiefV4.Audio;
using CrewChiefV4.GameState;
using CrewChiefV4.NumberProcessing;

namespace CrewChiefV4.Events
{
	internal class LapTimes_legacy : AbstractEvent
	{
		internal enum Delta
		{
			FAST,
			A_TENTH,
			TWO_TENTHS,
			A_SECOND,
			AUTO_GAPS,
			NONE
		}

		private enum ConsistencyResult
		{
			NOT_APPLICABLE,
			CONSISTENT,
			IMPROVING,
			WORSENING
		}

		private enum LastLapRating
		{
			BEST_OVERALL,
			BEST_IN_CLASS,
			SETTING_CURRENT_PACE,
			CLOSE_TO_CURRENT_PACE,
			PERSONAL_BEST,
			PERSONAL_BEST_CLOSE_TO_OVERALL_LEADER,
			PERSONAL_BEST_CLOSE_TO_CLASS_LEADER,
			PERSONAL_BEST_STILL_SLOW,
			CLOSE_TO_OVERALL_LEADER,
			CLOSE_TO_CLASS_LEADER,
			CLOSE_TO_PERSONAL_BEST,
			MEH,
			BAD,
			NO_DATA,
			OUTLIER
		}

		public enum SectorSet
		{
			ONE,
			TWO,
			THREE,
			NONE
		}

		public enum SectorReportOption
		{
			WORST_ONLY,
			ALL
		}

		private readonly int frequencyOfRaceSectorDeltaReports = UserSettings.GetUserSettings().getInt("frequency_of_race_sector_delta_reports");

		private readonly int frequencyOfPracticeAndQualSectorDeltaReports = UserSettings.GetUserSettings().getInt("frequency_of_prac_and_qual_sector_delta_reports");

		private readonly int frequencyOfPlayerRaceLapTimeReports = UserSettings.GetUserSettings().getInt("frequency_of_player_race_lap_time_reports");

		private readonly int frequencyOfPlayerQualAndPracLapTimeReports = UserSettings.GetUserSettings().getInt("frequency_of_player_prac_and_qual_lap_time_reports");

		private readonly bool raceSectorReportsAtEachSector = UserSettings.GetUserSettings().getBoolean("race_sector_reports_at_each_sector");

		private readonly bool practiceAndQualSectorReportsAtEachSector = UserSettings.GetUserSettings().getBoolean("practice_and_qual_sector_reports_at_each_sector");

		private readonly bool raceSectorReportsAtLapEnd = UserSettings.GetUserSettings().getBoolean("race_sector_reports_at_lap_end");

		private readonly bool practiceAndQualSectorReportsLapEnd = UserSettings.GetUserSettings().getBoolean("practice_and_qual_sector_reports_at_lap_end");

		private readonly bool disablePCarspracAndQualPoleDeltaReports = UserSettings.GetUserSettings().getBoolean("disable_pcars_prac_and_qual_pole_deltas");

		private readonly bool reportAllLaptimesInHotlapMode = UserSettings.GetUserSettings().getBoolean("report_all_laps_in_hotlap_mode");

		private int maxQueueLengthForRaceSectorDeltaReports;

		private int maxQueueLengthForRaceLapTimeReports;

		public static string folderLapTimeIntro = "lap_times/time_intro";

		public static string folderGapIntro = "lap_times/gap_intro";

		public static string folderGapOutroOffPace = "lap_times/gap_outro_off_pace";

		public static string folderSelfGapOutroOffPace = "lap_times/off_the_self_pace";

		private string folderLessThanATenthOffThePace = "lap_times/less_than_a_tenth_off_the_pace";

		private string folderSelfLessThanATenthOffThePace = "lap_times/less_than_a_tenth_off_self_pace";

		private string folderQuickerThanSecondPlace = "lap_times/quicker_than_second_place";

		private string folderPaceOK = "lap_times/pace_ok";

		private string folderPaceBad = "lap_times/pace_bad";

		private string folderNeedToFindOneMoreTenth = "lap_times/need_to_find_one_more_tenth";

		private string folderNeedToFindASecond = "lap_times/need_to_find_a_second";

		private string folderNeedToFindMoreThanASecond = "lap_times/need_to_find_more_than_a_second";

		private string folderNeedToFindAFewMoreTenths = "lap_times/need_to_find_a_few_more_tenths";

		private string folderBestLapInRace = "lap_times/best_lap_in_race";

		private string folderBestLapInRaceForClass = "lap_times/best_lap_in_race_for_class";

		private string folderGoodLap = "lap_times/good_lap";

		private string folderConsistentTimes = "lap_times/consistent";

		private string folderImprovingTimes = "lap_times/improving";

		private string folderWorseningTimes = "lap_times/worsening";

		private string folderPersonalBest = "lap_times/personal_best";

		private string folderSettingCurrentRacePace = "lap_times/setting_current_race_pace";

		private string folderMatchingCurrentRacePace = "lap_times/matching_race_pace";

		public static string folderSector1Fastest = "lap_times/sector1_fastest";

		public static string folderSector2Fastest = "lap_times/sector2_fastest";

		public static string folderSector3Fastest = "lap_times/sector3_fastest";

		public static string folderSector1and2Fastest = "lap_times/sector1_and_2_fastest";

		public static string folderSector2and3Fastest = "lap_times/sector2_and_3_fastest";

		public static string folderSector1and3Fastest = "lap_times/sector1_and_3_fastest";

		public static string folderAllSectorsFastest = "lap_times/sector_all_fastest";

		public static string folderSector1Fast = "lap_times/sector1_fast";

		public static string folderSector2Fast = "lap_times/sector2_fast";

		public static string folderSector3Fast = "lap_times/sector3_fast";

		public static string folderSector1and2Fast = "lap_times/sector1_and_2_fast";

		public static string folderSector2and3Fast = "lap_times/sector2_and_3_fast";

		public static string folderSector1and3Fast = "lap_times/sector1_and_3_fast";

		public static string folderAllSectorsFast = "lap_times/sector_all_fast";

		public static string folderSector1ATenthOffThePace = "lap_times/sector1_a_tenth_off_pace";

		public static string folderSector2ATenthOffThePace = "lap_times/sector2_a_tenth_off_pace";

		public static string folderSector3ATenthOffThePace = "lap_times/sector3_a_tenth_off_pace";

		public static string folderSector1and2ATenthOffThePace = "lap_times/sector1_and_2_a_tenth_off_pace";

		public static string folderSector2and3ATenthOffThePace = "lap_times/sector2_and_3_a_tenth_off_pace";

		public static string folderSector1and3ATenthOffThePace = "lap_times/sector1_and_3_a_tenth_off_pace";

		public static string folderAllSectorsATenthOffThePace = "lap_times/sector_all_a_tenth_off_pace";

		public static string folderSector1TwoTenthsOffThePace = "lap_times/sector1_two_tenths_off_pace";

		public static string folderSector2TwoTenthsOffThePace = "lap_times/sector2_two_tenths_off_pace";

		public static string folderSector3TwoTenthsOffThePace = "lap_times/sector3_two_tenths_off_pace";

		public static string folderSector1and2TwoTenthsOffThePace = "lap_times/sector1_and_2_two_tenths_off_pace";

		public static string folderSector2and3TwoTenthsOffThePace = "lap_times/sector2_and_3_two_tenths_off_pace";

		public static string folderSector1and3TwoTenthsOffThePace = "lap_times/sector1_and_3_two_tenths_off_pace";

		public static string folderAllSectorsTwoTenthsOffThePace = "lap_times/sector_all_two_tenths_off_pace";

		public static string folderSector1ASecondOffThePace = "lap_times/sector1_a_second_off_pace";

		public static string folderSector2ASecondOffThePace = "lap_times/sector2_a_second_off_pace";

		public static string folderSector3ASecondOffThePace = "lap_times/sector3_a_second_off_pace";

		public static string folderSector1and2ASecondOffThePace = "lap_times/sector1_and_2_a_second_off_pace";

		public static string folderSector2and3ASecondOffThePace = "lap_times/sector2_and_3_a_second_off_pace";

		public static string folderSector1and3ASecondOffThePace = "lap_times/sector1_and_3_a_second_off_pace";

		public static string folderAllSectorsASecondOffThePace = "lap_times/sector_all_a_second_off_pace";

		public static string folderSector1Is = "lap_times/sector1_is";

		public static string folderSector2Is = "lap_times/sector2_is";

		public static string folderSector3Is = "lap_times/sector3_is";

		public static string folderSectors1And2Are = "lap_times/sector1_and_2_are";

		public static string folderSectors2And3Are = "lap_times/sector2_and_3_are";

		public static string folderSectors1And3Are = "lap_times/sector1_and_3_are";

		public static string folderAllThreeSectorsAre = "lap_times/sector_all_are";

		public static string folderOffThePace = "lap_times/off_the_pace";

		public static string folderSelfSector1ATenthOffThePace = "lap_times/sector1_a_tenth_off_self_pace";

		public static string folderSelfSector2ATenthOffThePace = "lap_times/sector2_a_tenth_off_self_pace";

		public static string folderSelfSector3ATenthOffThePace = "lap_times/sector3_a_tenth_off_self_pace";

		public static string folderSelfSector1and2ATenthOffThePace = "lap_times/sector1_and_2_a_tenth_off_self_pace";

		public static string folderSelfSector2and3ATenthOffThePace = "lap_times/sector2_and_3_a_tenth_off_self_pace";

		public static string folderSelfSector1and3ATenthOffThePace = "lap_times/sector1_and_3_a_tenth_off_self_pace";

		public static string folderSelfAllSectorsATenthOffThePace = "lap_times/sector_all_a_tenth_off_self_pace";

		public static string folderSelfSector1TwoTenthsOffThePace = "lap_times/sector1_two_tenths_off_self_pace";

		public static string folderSelfSector2TwoTenthsOffThePace = "lap_times/sector2_two_tenths_off_self_pace";

		public static string folderSelfSector3TwoTenthsOffThePace = "lap_times/sector3_two_tenths_off_self_pace";

		public static string folderSelfSector1and2TwoTenthsOffThePace = "lap_times/sector1_and_2_two_tenths_off_self_pace";

		public static string folderSelfSector2and3TwoTenthsOffThePace = "lap_times/sector2_and_3_two_tenths_off_self_pace";

		public static string folderSelfSector1and3TwoTenthsOffThePace = "lap_times/sector1_and_3_two_tenths_off_self_pace";

		public static string folderSelfAllSectorsTwoTenthsOffThePace = "lap_times/sector_all_two_tenths_off_self_pace";

		public static string folderSelfSector1ASecondOffThePace = "lap_times/sector1_a_second_off_self_pace";

		public static string folderSelfSector2ASecondOffThePace = "lap_times/sector2_a_second_off_self_pace";

		public static string folderSelfSector3ASecondOffThePace = "lap_times/sector3_a_second_off_self_pace";

		public static string folderSelfSector1and2ASecondOffThePace = "lap_times/sector1_and_2_a_second_off_self_pace";

		public static string folderSelfSector2and3ASecondOffThePace = "lap_times/sector2_and_3_a_second_off_self_pace";

		public static string folderSelfSector1and3ASecondOffThePace = "lap_times/sector1_and_3_a_second_off_self_pace";

		public static string folderSelfAllSectorsASecondOffThePace = "lap_times/sector_all_a_second_off_self_pace";

		public static string folderSelfOffThePace = "lap_times/off_the_self_pace";

		private float goodLapPercent = 0.3f;

		private float matchingRacePacePercent = 0.1f;

		private float consistencyLimit = 0.5f;

		private List<float> lapTimesWindow = new List<float>();

		private List<Conditions.ConditionsSample> conditionsWindow = new List<Conditions.ConditionsSample>();

		private int lapTimesWindowSize = 5;

		private ConsistencyResult lastConsistencyMessage;

		private int lastConsistencyUpdate;

		private bool lapIsValid;

		private LastLapRating lastLapRating;

		private LastLapRating lastLapSelfRating;

		private TimeSpan deltaPlayerLastToSessionBestInClass;

		private bool deltaPlayerLastToSessionBestInClassSet;

		private int currentPosition;

		private SessionType sessionType;

		private GameStateData currentGameState;

		private int paceCheckLapsWindowForRaceToUse = 3;

		private int paceCheckLapsWindowForRaceVeryShort = 6;

		private int paceCheckLapsWindowForRaceShort = 5;

		private int paceCheckLapsWindowForRaceMedium = 4;

		private int paceCheckLapsWindowForRaceLong = 3;

		private int paceCheckLapsWindowForRaceVeryLong = 2;

		private bool isHotLappingOrLonePractice;

		private TimeSpan lastGapToSecondWhenLeadingPracOrQual;

		private int ClassPositionAtStartOfCurrentLap = -1;

		public static Dictionary<TrackData.TrackLengthClass, float> outlierPaceLimits = new Dictionary<TrackData.TrackLengthClass, float>
		{
			{
				TrackData.TrackLengthClass.VERY_LONG,
				15f
			},
			{
				TrackData.TrackLengthClass.LONG,
				8f
			},
			{
				TrackData.TrackLengthClass.MEDIUM,
				3f
			},
			{
				TrackData.TrackLengthClass.SHORT,
				2f
			},
			{
				TrackData.TrackLengthClass.VERY_SHORT,
				2f
			}
		};

		public static Dictionary<TrackData.TrackLengthClass, int> lapsBeforeAnnouncingGaps = new Dictionary<TrackData.TrackLengthClass, int>
		{
			{
				TrackData.TrackLengthClass.VERY_LONG,
				0
			},
			{
				TrackData.TrackLengthClass.LONG,
				1
			},
			{
				TrackData.TrackLengthClass.MEDIUM,
				2
			},
			{
				TrackData.TrackLengthClass.SHORT,
				3
			},
			{
				TrackData.TrackLengthClass.VERY_SHORT,
				4
			}
		};

		private static readonly List<SpeechCommands.ID> Commands = new List<SpeechCommands.ID>
		{
			SpeechCommands.ID.HOWS_MY_PACE,
			SpeechCommands.ID.HOWS_MY_SELF_PACE,
			SpeechCommands.ID.WHATS_MY_BEST_LAP_TIME,
			SpeechCommands.ID.WHATS_MY_LAST_SECTOR_TIME,
			SpeechCommands.ID.WHATS_THE_FASTEST_LAP_TIME,
			SpeechCommands.ID.WHAT_ARE_MY_SECTOR_TIMES,
			SpeechCommands.ID.WHAT_WAS_MY_LAST_LAP_TIME
		};

		public LapTimes_legacy(AudioPlayer audioPlayer)
		{
			base.audioPlayer = audioPlayer;
			if (frequencyOfRaceSectorDeltaReports > 7)
			{
				maxQueueLengthForRaceSectorDeltaReports = 7;
			}
			else if (frequencyOfRaceSectorDeltaReports > 5)
			{
				maxQueueLengthForRaceSectorDeltaReports = 4;
			}
			else
			{
				maxQueueLengthForRaceSectorDeltaReports = 3;
			}
			if (frequencyOfPlayerRaceLapTimeReports > 7)
			{
				maxQueueLengthForRaceLapTimeReports = 7;
			}
			else if (frequencyOfPlayerRaceLapTimeReports > 5)
			{
				maxQueueLengthForRaceLapTimeReports = 5;
			}
			else
			{
				maxQueueLengthForRaceLapTimeReports = 4;
			}
		}

		public override void clearState()
		{
			lapTimesWindow = new List<float>(lapTimesWindowSize);
			conditionsWindow = new List<Conditions.ConditionsSample>();
			lastConsistencyUpdate = 0;
			lastConsistencyMessage = ConsistencyResult.NOT_APPLICABLE;
			lapIsValid = true;
			lastLapRating = LastLapRating.NO_DATA;
			lastLapSelfRating = LastLapRating.NO_DATA;
			deltaPlayerLastToSessionBestInClass = TimeSpan.MaxValue;
			deltaPlayerLastToSessionBestInClassSet = false;
			currentPosition = -1;
			currentGameState = null;
			isHotLappingOrLonePractice = false;
			lastGapToSecondWhenLeadingPracOrQual = TimeSpan.Zero;
			ClassPositionAtStartOfCurrentLap = -1;
		}

		public override bool isMessageStillValid(string eventSubType, GameStateData currentGameState, Dictionary<string, object> validationData)
		{
			if (PitStops.isPittingThisLap)
			{
				return false;
			}
			if ((eventSubType == folderImprovingTimes || eventSubType == folderConsistentTimes || eventSubType == folderWorseningTimes) && currentGameState.SessionData.SectorNumber != 1)
			{
				return false;
			}
			return base.isMessageStillValid(eventSubType, currentGameState, validationData);
		}

		protected override void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
		{
			if (GameStateData.onManualFormationLap)
			{
				return;
			}
			sessionType = currentGameState.SessionData.SessionType;
			this.currentGameState = currentGameState;
			if (currentGameState.SessionData.IsNewLap)
			{
				ClassPositionAtStartOfCurrentLap = currentGameState.SessionData.ClassPosition;
				if (currentGameState.SessionData.CompletedLaps > 0)
				{
					if (currentGameState.SessionData.LapTimePrevious > 0f)
					{
						Console.WriteLine("lgcy: Laptime: " + TimeSpan.FromSeconds(currentGameState.SessionData.LapTimePrevious).ToString("mm\\:ss\\.fff") + ",  Valid = " + currentGameState.SessionData.PreviousLapWasValid);
					}
					else
					{
						Console.WriteLine("lgcy: Laptime: " + currentGameState.SessionData.LapTimePrevious.ToString("0.000") + ",  Valid = " + currentGameState.SessionData.PreviousLapWasValid);
					}
				}
				if (currentGameState.SessionData.TrackDefinition != null)
				{
					switch (currentGameState.SessionData.TrackDefinition.trackLengthClass)
					{
					case TrackData.TrackLengthClass.VERY_SHORT:
						paceCheckLapsWindowForRaceToUse = paceCheckLapsWindowForRaceVeryShort;
						break;
					case TrackData.TrackLengthClass.SHORT:
						paceCheckLapsWindowForRaceToUse = paceCheckLapsWindowForRaceShort;
						break;
					case TrackData.TrackLengthClass.MEDIUM:
						paceCheckLapsWindowForRaceToUse = paceCheckLapsWindowForRaceMedium;
						break;
					case TrackData.TrackLengthClass.LONG:
						paceCheckLapsWindowForRaceToUse = paceCheckLapsWindowForRaceLong;
						break;
					case TrackData.TrackLengthClass.VERY_LONG:
						paceCheckLapsWindowForRaceToUse = paceCheckLapsWindowForRaceVeryLong;
						break;
					}
				}
				deltaPlayerLastToSessionBestInClassSet = false;
				if (currentGameState.SessionData.LapTimePrevious > 0f)
				{
					if (currentGameState.OpponentData.Count > 0 && currentGameState.SessionData.SessionType != SessionType.LonePractice && currentGameState.SessionData.SessionType != SessionType.HotLap)
					{
						if (currentGameState.SessionData.SessionType == SessionType.Qualify || currentGameState.SessionData.SessionType == SessionType.PrivateQualify)
						{
							float playerClassOpponentBestLapTime = currentGameState.TimingData.getPlayerClassOpponentBestLapTime(TimingData.ConditionsEnum.ANY);
							if (playerClassOpponentBestLapTime > 0f)
							{
								deltaPlayerLastToSessionBestInClass = TimeSpan.FromSeconds(currentGameState.SessionData.LapTimePrevious - playerClassOpponentBestLapTime);
								deltaPlayerLastToSessionBestInClassSet = true;
							}
						}
						else
						{
							float playerClassOpponentBestLapTime2 = currentGameState.TimingData.getPlayerClassOpponentBestLapTime();
							if (playerClassOpponentBestLapTime2 > 0f)
							{
								deltaPlayerLastToSessionBestInClass = TimeSpan.FromSeconds(currentGameState.SessionData.LapTimePrevious - playerClassOpponentBestLapTime2);
								deltaPlayerLastToSessionBestInClassSet = true;
							}
						}
					}
					else if (currentGameState.SessionData.PlayerLapTimeSessionBest > 0f && currentGameState.SessionData.CompletedLaps > 1)
					{
						deltaPlayerLastToSessionBestInClass = TimeSpan.FromSeconds(currentGameState.SessionData.LapTimePrevious - currentGameState.SessionData.PlayerLapTimeSessionBest);
						deltaPlayerLastToSessionBestInClassSet = true;
					}
				}
			}
			currentPosition = currentGameState.SessionData.ClassPosition;
			if (lapIsValid && currentGameState.SessionData.CompletedLaps > 0 && !currentGameState.SessionData.IsNewLap && !currentGameState.SessionData.CurrentLapIsValid)
			{
				lapIsValid = false;
			}
			if (previousGameState != null && previousGameState.SessionData.CompletedLaps <= currentGameState.FlagData.lapCountWhenLastWentGreen)
			{
				return;
			}
			float[] array = new float[4] { -1f, -1f, -1f, -1f };
			float[] array2 = new float[4] { -1f, -1f, -1f, -1f };
			array2 = ((!currentGameState.SessionData.IsNewLap) ? currentGameState.SessionData.getPlayerTimeAndSectorsForBestLap(ignoreLast: false) : currentGameState.SessionData.getPlayerTimeAndSectorsForBestLap(ignoreLast: true));
			if (currentGameState.SessionData.IsNewSector)
			{
				isHotLappingOrLonePractice = currentGameState.SessionData.SessionType == SessionType.HotLap || currentGameState.SessionData.SessionType == SessionType.LonePractice || currentGameState.OpponentData.Count == 0 || (currentGameState.OpponentData.Count == 1 && currentGameState.OpponentData.First().Value.DriverRawName == currentGameState.SessionData.DriverRawName);
				if (isHotLappingOrLonePractice)
				{
					array[0] = array2[0];
					array[1] = array2[1];
					array[2] = array2[2];
					array[3] = array2[3];
				}
				else
				{
					switch (currentGameState.SessionData.SessionType)
					{
					case SessionType.Race:
						array = (currentGameState.TimingData.conditionsHaveChanged ? new float[4]
						{
							currentGameState.TimingData.getPlayerClassOpponentBestLapTime(),
							currentGameState.TimingData.getPlayerClassOpponentBestLapSector1Time(),
							currentGameState.TimingData.getPlayerClassOpponentBestLapSector2Time(),
							currentGameState.TimingData.getPlayerClassOpponentBestLapSector3Time()
						} : currentGameState.getTimeAndSectorsForBestOpponentLapInWindow(paceCheckLapsWindowForRaceToUse, currentGameState.carClass));
						break;
					case SessionType.Practice:
						array = (currentGameState.TimingData.conditionsHaveChanged ? new float[4]
						{
							currentGameState.TimingData.getPlayerClassOpponentBestLapTime(),
							currentGameState.TimingData.getPlayerClassOpponentBestLapSector1Time(),
							currentGameState.TimingData.getPlayerClassOpponentBestLapSector2Time(),
							currentGameState.TimingData.getPlayerClassOpponentBestLapSector3Time()
						} : currentGameState.getTimeAndSectorsForBestOpponentLapInWindow(-1, currentGameState.carClass));
						break;
					case SessionType.Qualify:
					case SessionType.PrivateQualify:
						array = currentGameState.getTimeAndSectorsForBestOpponentLapInWindow(-1, currentGameState.carClass);
						break;
					}
				}
			}
			bool flag;
			if (!currentGameState.PitData.OnInLap && previousGameState != null && !previousGameState.PitData.OnOutLap && !currentGameState.PitData.InPitlane && !currentGameState.FlagData.previousLapWasFCY)
			{
				flag = false;
				if (currentGameState.SessionData.IsNewLap && (((currentGameState.SessionData.SessionType == SessionType.HotLap || currentGameState.SessionData.SessionType == SessionType.LonePractice || currentGameState.SessionData.SessionType == SessionType.Qualify || currentGameState.SessionData.SessionType == SessionType.PrivateQualify) && currentGameState.SessionData.CompletedLaps > 0) || currentGameState.SessionData.CompletedLaps > 1))
				{
					if (lapTimesWindow == null)
					{
						lapTimesWindow = new List<float>(lapTimesWindowSize);
					}
					lastLapRating = getLastLapRating(currentGameState, array, selfPace: false);
					lastLapSelfRating = getLastLapRating(currentGameState, array2, selfPace: true);
					if (currentGameState.SessionData.PreviousLapWasValid && lastLapRating != LastLapRating.OUTLIER)
					{
						lapTimesWindow.Insert(0, currentGameState.SessionData.LapTimePrevious);
						Conditions.ConditionsSample mostRecentConditions = currentGameState.Conditions.getMostRecentConditions();
						if (mostRecentConditions != null)
						{
							conditionsWindow.Insert(0, mostRecentConditions);
						}
						if (lapIsValid && !currentGameState.PitData.InPitlane)
						{
							bool flag2 = false;
							if (isHotLappingOrLonePractice && reportAllLaptimesInHotlapMode)
							{
								audioPlayer.playMessage(new QueuedMessage("laptime", 0, AbstractEvent.MessageContents(folderLapTimeIntro, TimeSpanWrapper.FromSeconds(currentGameState.SessionData.LapTimePrevious, Precision.AUTO_LAPTIMES)), null, null, null, 0, this, null, 10));
								flag2 = true;
							}
							else if (((currentGameState.SessionData.SessionType == SessionType.Qualify || currentGameState.SessionData.SessionType == SessionType.PrivateQualify || currentGameState.SessionData.SessionType == SessionType.Practice) && (double)frequencyOfPlayerQualAndPracLapTimeReports > Utilities.random.NextDouble() * 10.0) || (currentGameState.SessionData.SessionType == SessionType.Race && (double)frequencyOfPlayerRaceLapTimeReports > Utilities.random.NextDouble() * 10.0))
							{
								QueuedMessage queuedMessage = new QueuedMessage("laptime", 0, AbstractEvent.MessageContents(folderLapTimeIntro, TimeSpanWrapper.FromSeconds(currentGameState.SessionData.LapTimePrevious, Precision.AUTO_LAPTIMES)), null, null, null, 0, this, null, 0);
								if (currentGameState.SessionData.SessionType == SessionType.Race)
								{
									queuedMessage.maxPermittedQueueLengthForMessage = maxQueueLengthForRaceLapTimeReports;
								}
								audioPlayer.playMessage(queuedMessage);
								flag2 = true;
							}
							if (deltaPlayerLastToSessionBestInClassSet && (currentGameState.SessionData.SessionType == SessionType.Qualify || currentGameState.SessionData.SessionType == SessionType.PrivateQualify || currentGameState.SessionData.SessionType == SessionType.Practice || currentGameState.SessionData.SessionType == SessionType.HotLap || currentGameState.SessionData.SessionType == SessionType.LonePractice))
							{
								if (currentGameState.SessionData.SessionType == SessionType.HotLap || currentGameState.SessionData.SessionType == SessionType.LonePractice || currentGameState.OpponentData.Count == 0)
								{
									if (currentGameState.SessionData.CompletedLaps > 1)
									{
										bool num;
										if (!isHotLappingOrLonePractice)
										{
											if (lastLapRating == LastLapRating.BEST_IN_CLASS)
											{
												goto IL_082a;
											}
											num = deltaPlayerLastToSessionBestInClass <= TimeSpan.Zero;
										}
										else
										{
											num = lastLapRating == LastLapRating.BEST_OVERALL;
										}
										if (num)
										{
											goto IL_082a;
										}
									}
									if (deltaPlayerLastToSessionBestInClass > TimeSpan.Zero && deltaPlayerLastToSessionBestInClass < TimeSpan.FromMilliseconds(50.0))
									{
										audioPlayer.playMessage(new QueuedMessage(isHotLappingOrLonePractice ? folderSelfLessThanATenthOffThePace : folderLessThanATenthOffThePace, 0, null, null, null, null, 0, this, null, 3));
									}
									else if (deltaPlayerLastToSessionBestInClass > TimeSpan.Zero && deltaPlayerLastToSessionBestInClass < TimeSpan.MaxValue)
									{
										audioPlayer.playMessage(new QueuedMessage("lapTimeNotRaceGap", 0, AbstractEvent.MessageContents(folderGapIntro, new TimeSpanWrapper(deltaPlayerLastToSessionBestInClass, Precision.AUTO_GAPS), isHotLappingOrLonePractice ? folderSelfGapOutroOffPace : folderGapOutroOffPace), null, null, null, 0, this, null, 3));
									}
									goto IL_091d;
								}
								if (currentGameState.SessionData.ClassPosition == 1)
								{
									bool flag3 = false;
									if (previousGameState != null && previousGameState.SessionData.ClassPosition > 1)
									{
										flag3 = true;
									}
									if (deltaPlayerLastToSessionBestInClass < lastGapToSecondWhenLeadingPracOrQual)
									{
										flag3 = true;
										lastGapToSecondWhenLeadingPracOrQual = deltaPlayerLastToSessionBestInClass;
									}
									if (flag3)
									{
										TimeSpan timeSpan = deltaPlayerLastToSessionBestInClass.Negate();
										if ((double)frequencyOfPlayerQualAndPracLapTimeReports > Utilities.random.NextDouble() * 10.0 && (!disablePCarspracAndQualPoleDeltaReports || Game.RACE_ROOM || Game.IRACING || Game.ASSETTO1) && (timeSpan.Seconds > 0 || timeSpan.Milliseconds > 50))
										{
											int num2 = Utilities.random.Next(0, 8);
											audioPlayer.playMessage(new QueuedMessage("lapTimeNotRaceGap", num2 + 6, AbstractEvent.MessageContents(folderGapIntro, new TimeSpanWrapper(timeSpan, Precision.AUTO_GAPS), folderQuickerThanSecondPlace), null, null, null, 0, this));
										}
									}
								}
								else
								{
									if (currentGameState.SessionData.CompletedLaps > 1 && (lastLapRating == LastLapRating.PERSONAL_BEST_STILL_SLOW || lastLapRating == LastLapRating.PERSONAL_BEST_CLOSE_TO_CLASS_LEADER || lastLapRating == LastLapRating.PERSONAL_BEST_CLOSE_TO_OVERALL_LEADER))
									{
										audioPlayer.playMessage(new QueuedMessage(folderPersonalBest, 0, null, null, null, null, 0, this, null, 7));
									}
									if ((double)frequencyOfPlayerQualAndPracLapTimeReports > Utilities.random.NextDouble() * 10.0 && (!disablePCarspracAndQualPoleDeltaReports || Game.RACE_ROOM || Game.IRACING || Game.ASSETTO1) && (deltaPlayerLastToSessionBestInClass.Seconds > 0 || deltaPlayerLastToSessionBestInClass.Milliseconds > 50) && deltaPlayerLastToSessionBestInClass.Seconds < 60)
									{
										audioPlayer.playMessage(new QueuedMessage("lapTimeNotRaceGap", 0, AbstractEvent.MessageContents(folderGapIntro, new TimeSpanWrapper(deltaPlayerLastToSessionBestInClass, Precision.AUTO_GAPS), folderGapOutroOffPace), null, null, null, 0, this));
									}
									if (!GlobalBehaviourSettings.useOvalLogic && practiceAndQualSectorReportsLapEnd && (double)frequencyOfPracticeAndQualSectorDeltaReports > Utilities.random.NextDouble() * 10.0)
									{
										List<MessageFragment> sectorDeltaMessages = getSectorDeltaMessages(SectorReportOption.ALL, currentGameState.SessionData.LastSector1Time, array[1], currentGameState.SessionData.LastSector2Time, array[2], currentGameState.SessionData.LastSector3Time, array[3], comparisonIncludesAllLaps: true, selfPace: false);
										if (sectorDeltaMessages.Count > 0)
										{
											audioPlayer.playMessage(new QueuedMessage("sectorDeltas", 0, sectorDeltaMessages, null, null, null, 0, this));
											flag = true;
										}
									}
								}
							}
							else if (currentGameState.SessionData.SessionType == SessionType.Race && !currentGameState.PitData.InPitlane && !currentGameState.FlagData.isFullCourseYellow)
							{
								bool flag4 = false;
								if ((double)frequencyOfPlayerRaceLapTimeReports > Utilities.random.NextDouble() * 10.0)
								{
									float num3 = ((currentGameState.SessionData.CompletedLaps >= lapsBeforeAnnouncingGaps[currentGameState.SessionData.TrackDefinition.trackLengthClass]) ? 0f : 0.8f);
									switch (lastLapRating)
									{
									case LastLapRating.BEST_OVERALL:
										flag4 = true;
										audioPlayer.playMessage(new QueuedMessage(folderBestLapInRace, 0, null, null, null, null, 0, this, null, 3), PearlsOfWisdom.PearlType.GOOD, num3);
										break;
									case LastLapRating.BEST_IN_CLASS:
										flag4 = true;
										audioPlayer.playMessage(new QueuedMessage(folderBestLapInRaceForClass, 0, null, null, null, null, 0, this, null, 3), PearlsOfWisdom.PearlType.GOOD, num3);
										break;
									case LastLapRating.SETTING_CURRENT_PACE:
										flag4 = true;
										audioPlayer.playMessage(new QueuedMessage(folderSettingCurrentRacePace, 0, null, null, null, null, 0, this, null, 3), PearlsOfWisdom.PearlType.GOOD, num3);
										break;
									case LastLapRating.CLOSE_TO_CURRENT_PACE:
										if (Utilities.random.NextDouble() < 0.5)
										{
											flag4 = true;
											audioPlayer.playMessage(new QueuedMessage(folderMatchingCurrentRacePace, 0, null, null, null, null, 0, this, null, 0), PearlsOfWisdom.PearlType.GOOD, num3);
										}
										break;
									case LastLapRating.PERSONAL_BEST_CLOSE_TO_OVERALL_LEADER:
									case LastLapRating.PERSONAL_BEST_CLOSE_TO_CLASS_LEADER:
										flag4 = true;
										audioPlayer.playMessage(new QueuedMessage(folderGoodLap, 0, null, null, null, null, 0, this, null, 0), PearlsOfWisdom.PearlType.GOOD, num3);
										break;
									case LastLapRating.PERSONAL_BEST_STILL_SLOW:
										flag4 = true;
										audioPlayer.playMessage(new QueuedMessage(folderPersonalBest, 0, null, null, null, null, 0, this, null, 0), PearlsOfWisdom.PearlType.NEUTRAL, num3);
										break;
									case LastLapRating.CLOSE_TO_OVERALL_LEADER:
									case LastLapRating.CLOSE_TO_CLASS_LEADER:
										if (Utilities.random.NextDouble() < 0.2)
										{
											flag4 = true;
											audioPlayer.playMessage(new QueuedMessage(folderGoodLap, 0, null, null, null, null, 0, this, null, 0), PearlsOfWisdom.PearlType.NEUTRAL, num3);
										}
										break;
									}
								}
								if (!GlobalBehaviourSettings.useOvalLogic && currentGameState.SessionData.ClassPosition == ClassPositionAtStartOfCurrentLap && raceSectorReportsAtLapEnd && (double)frequencyOfRaceSectorDeltaReports > Utilities.random.NextDouble() * 15.0)
								{
									double num4 = Utilities.random.NextDouble();
									SectorReportOption reportOption = SectorReportOption.ALL;
									if (flag2 && flag4)
									{
										reportOption = SectorReportOption.WORST_ONLY;
									}
									else if (num4 > 0.5 || ((flag2 || flag4) && num4 > 0.2))
									{
										reportOption = SectorReportOption.WORST_ONLY;
									}
									List<MessageFragment> sectorDeltaMessages2 = getSectorDeltaMessages(reportOption, currentGameState.SessionData.LastSector1Time, array[1], currentGameState.SessionData.LastSector2Time, array[2], currentGameState.SessionData.LastSector3Time, array[3], comparisonIncludesAllLaps: false, selfPace: false);
									if (sectorDeltaMessages2.Count > 0)
									{
										QueuedMessage queuedMessage2 = new QueuedMessage("sectorDeltas", 0, sectorDeltaMessages2, null, null, null, 0, this, null, 0);
										queuedMessage2.maxPermittedQueueLengthForMessage = maxQueueLengthForRaceSectorDeltaReports;
										audioPlayer.playMessage(queuedMessage2);
										flag = true;
									}
								}
								if (!GlobalBehaviourSettings.justTheFacts && (!flag4 || Utilities.random.NextDouble() < 0.25) && currentGameState.SessionData.CompletedLaps >= lastConsistencyUpdate + lapTimesWindowSize && lapTimesWindow.Count >= lapTimesWindowSize)
								{
									int num5 = Utilities.random.Next(0, 8);
									switch (checkAgainstPreviousLaps(currentGameState.SessionData.TrackDefinition.isOval))
									{
									case ConsistencyResult.CONSISTENT:
										lastConsistencyUpdate = currentGameState.SessionData.CompletedLaps;
										audioPlayer.playMessage(new QueuedMessage(folderConsistentTimes, num5 + 10, null, null, null, null, num5, this, null, 0));
										break;
									case ConsistencyResult.IMPROVING:
										lastConsistencyUpdate = currentGameState.SessionData.CompletedLaps;
										audioPlayer.playMessage(new QueuedMessage(folderImprovingTimes, num5 + 10, null, null, null, null, num5, this));
										break;
									case ConsistencyResult.WORSENING:
										if (lastLapRating == LastLapRating.BEST_IN_CLASS || lastLapRating == LastLapRating.BEST_OVERALL || lastLapRating == LastLapRating.SETTING_CURRENT_PACE || lastLapRating == LastLapRating.CLOSE_TO_CURRENT_PACE)
										{
											Console.WriteLine("lgcy: Skipping 'worsening' laptimes message - inconsistent with lap rating");
										}
										else if (currentGameState.SessionData.ClassPosition >= currentGameState.SessionData.ClassPositionAtStartOfCurrentLap)
										{
											lastConsistencyUpdate = currentGameState.SessionData.CompletedLaps;
											if (GlobalBehaviourSettings.complaintsCountInThisSession < GlobalBehaviourSettings.maxComplaintsPerSession)
											{
												audioPlayer.playMessage(new QueuedMessage(folderWorseningTimes, num5 + 10, null, null, null, null, num5, this, new Dictionary<string, object>(), 3));
												GlobalBehaviourSettings.complaintsCountInThisSession++;
											}
										}
										break;
									}
								}
							}
						}
					}
				}
				goto IL_1125;
			}
			goto IL_134f;
			IL_1125:
			if (!flag && currentGameState.SessionData.IsNewSector && !currentGameState.FlagData.isFullCourseYellow && ((currentGameState.SessionData.SessionType == SessionType.Race && raceSectorReportsAtEachSector) || (currentGameState.SessionData.SessionType != SessionType.Race && practiceAndQualSectorReportsAtEachSector)))
			{
				double num6 = Utilities.random.NextDouble() * 10.0;
				bool flag5 = (double)frequencyOfRaceSectorDeltaReports > num6 * 1.5;
				bool flag6 = (double)frequencyOfPracticeAndQualSectorDeltaReports > num6;
				bool flag7 = ((!currentGameState.SessionData.IsNewLap) ? currentGameState.SessionData.CurrentLapIsValid : currentGameState.SessionData.PreviousLapWasValid);
				if (!GlobalBehaviourSettings.useOvalLogic && flag7 && ((currentGameState.SessionData.SessionType == SessionType.Race && flag5) || (((currentGameState.SessionData.SessionType == SessionType.Practice && (currentGameState.OpponentData.Count > 0 || currentGameState.SessionData.CompletedLaps > 1)) || currentGameState.SessionData.SessionType == SessionType.Qualify || currentGameState.SessionData.SessionType == SessionType.PrivateQualify || ((currentGameState.SessionData.SessionType == SessionType.HotLap || currentGameState.SessionData.SessionType == SessionType.LonePractice) && currentGameState.SessionData.CompletedLaps > 1)) && flag6)))
				{
					float playerTime = -1f;
					float comparisonTime = -1f;
					SectorSet sector = SectorSet.NONE;
					switch (currentGameState.SessionData.SectorNumber)
					{
					case 1:
						playerTime = currentGameState.SessionData.LastSector3Time;
						comparisonTime = array[3];
						sector = SectorSet.THREE;
						break;
					case 2:
						playerTime = currentGameState.SessionData.LastSector1Time;
						comparisonTime = array[1];
						sector = SectorSet.ONE;
						break;
					case 3:
						playerTime = currentGameState.SessionData.LastSector2Time;
						comparisonTime = array[2];
						sector = SectorSet.TWO;
						break;
					}
					List<MessageFragment> singleSectorDeltaMessages = getSingleSectorDeltaMessages(sector, playerTime, comparisonTime, isHotLappingOrLonePractice);
					if (singleSectorDeltaMessages.Count > 0)
					{
						int num7 = Utilities.random.Next(2, 4);
						AudioPlayer obj = audioPlayer;
						int expiresAfter = num7 + 10;
						int secondsDelay = num7;
						obj.playMessage(new QueuedMessage("singleSectorDelta", expiresAfter, singleSectorDeltaMessages, null, null, null, secondsDelay, this));
					}
				}
			}
			goto IL_134f;
			IL_082a:
			audioPlayer.playMessage(new QueuedMessage(folderPersonalBest, 0, null, null, null, null, 0, this, null, 3));
			goto IL_091d;
			IL_091d:
			if (!GlobalBehaviourSettings.useOvalLogic && practiceAndQualSectorReportsLapEnd && (double)frequencyOfPracticeAndQualSectorDeltaReports > Utilities.random.NextDouble() * 10.0)
			{
				List<MessageFragment> sectorDeltaMessages3 = getSectorDeltaMessages(SectorReportOption.ALL, currentGameState.SessionData.LastSector1Time, array[1], currentGameState.SessionData.LastSector2Time, array[2], currentGameState.SessionData.LastSector3Time, array[3], comparisonIncludesAllLaps: true, isHotLappingOrLonePractice);
				if (sectorDeltaMessages3.Count > 0)
				{
					audioPlayer.playMessage(new QueuedMessage("sectorsHotLap", 0, sectorDeltaMessages3, null, null, null, 0, this, null, 3));
					flag = true;
				}
			}
			goto IL_1125;
			IL_134f:
			if (currentGameState.SessionData.IsNewLap && !currentGameState.PitData.OnOutLap)
			{
				lapIsValid = true;
			}
		}

		private ConsistencyResult checkAgainstPreviousLaps(bool isOval)
		{
			if (conditionsWindow.Count() >= lapTimesWindowSize && ConditionsHaveChanged(conditionsWindow[0], conditionsWindow[lapTimesWindowSize - 1]))
			{
				return ConsistencyResult.NOT_APPLICABLE;
			}
			bool flag = true;
			bool flag2 = true;
			bool flag3 = true;
			for (int i = 0; i < lapTimesWindowSize - 1; i++)
			{
				if (lapTimesWindow[i] <= 0f)
				{
					Console.WriteLine("lgcy: No data for consistency check");
					lastConsistencyMessage = ConsistencyResult.NOT_APPLICABLE;
					return ConsistencyResult.NOT_APPLICABLE;
				}
				if (lapTimesWindow[i] >= lapTimesWindow[i + 1])
				{
					flag = false;
					break;
				}
			}
			for (int j = 0; j < lapTimesWindowSize - 1; j++)
			{
				if (lapTimesWindow[j] <= lapTimesWindow[j + 1])
				{
					flag2 = false;
				}
			}
			for (int k = 0; k < lapTimesWindowSize - 1; k++)
			{
				float num = lapTimesWindow[k];
				float num2 = lapTimesWindow[k + 1];
				float num3 = num2 * consistencyLimit / 100f;
				if (num > num2 + num3 || num < num2 - num3)
				{
					flag3 = false;
				}
			}
			if (flag)
			{
				if (lastConsistencyMessage != ConsistencyResult.IMPROVING)
				{
					lastConsistencyMessage = ConsistencyResult.IMPROVING;
					return ConsistencyResult.IMPROVING;
				}
				if (flag3)
				{
					lastConsistencyMessage = ConsistencyResult.CONSISTENT;
					return ConsistencyResult.CONSISTENT;
				}
			}
			if (flag2)
			{
				if (isOval)
				{
					return ConsistencyResult.NOT_APPLICABLE;
				}
				if (lastConsistencyMessage != ConsistencyResult.WORSENING)
				{
					lastConsistencyMessage = ConsistencyResult.WORSENING;
					return ConsistencyResult.WORSENING;
				}
				if (flag3)
				{
					lastConsistencyMessage = ConsistencyResult.CONSISTENT;
					return ConsistencyResult.CONSISTENT;
				}
			}
			if (flag3)
			{
				lastConsistencyMessage = ConsistencyResult.CONSISTENT;
				return ConsistencyResult.CONSISTENT;
			}
			return ConsistencyResult.NOT_APPLICABLE;
		}

		private LastLapRating getLastLapRating(GameStateData currentGameState, float[] bestLapComparisonData, bool selfPace)
		{
			if (currentGameState.SessionData.CompletedLaps < 3)
			{
				return LastLapRating.NO_DATA;
			}
			if (currentGameState.SessionData.PreviousLapWasValid && currentGameState.SessionData.LapTimePrevious > 0f)
			{
				float num = currentGameState.SessionData.LapTimePrevious * goodLapPercent / 100f;
				_ = currentGameState.SessionData.LapTimePrevious * matchingRacePacePercent / 100f;
				bool num2 = currentGameState.SessionData.CompletedLaps > 1 && currentGameState.SessionData.LapTimePrevious > 0f && currentGameState.SessionData.PreviousLapWasValid;
				bool flag = ((currentGameState.SessionData.SessionType != SessionType.HotLap && currentGameState.SessionData.SessionType != SessionType.LonePractice && currentGameState.OpponentData.Count > 0) || selfPace) && bestLapComparisonData[0] > 0f;
				if (!num2 && !flag)
				{
					return LastLapRating.NO_DATA;
				}
				if (!selfPace)
				{
					if (currentGameState.SessionData.OverallSessionBestLapTime == currentGameState.SessionData.LapTimePrevious)
					{
						return LastLapRating.BEST_OVERALL;
					}
					if (GameStateData.Multiclass && currentGameState.SessionData.PlayerClassSessionBestLapTime == currentGameState.SessionData.LapTimePrevious)
					{
						return LastLapRating.BEST_IN_CLASS;
					}
					if (currentGameState.SessionData.SessionType == SessionType.Race && bestLapComparisonData[0] > 0f && bestLapComparisonData[0] >= currentGameState.SessionData.LapTimePrevious)
					{
						return LastLapRating.SETTING_CURRENT_PACE;
					}
					if (currentGameState.SessionData.SessionType == SessionType.Race && bestLapComparisonData[0] > 0f && bestLapComparisonData[0] > currentGameState.SessionData.LapTimePrevious - num)
					{
						return LastLapRating.CLOSE_TO_CURRENT_PACE;
					}
					if (currentGameState.SessionData.LapTimePrevious == currentGameState.SessionData.PlayerLapTimeSessionBest)
					{
						if (currentGameState.SessionData.OpponentsLapTimeSessionBestOverall > currentGameState.SessionData.LapTimePrevious - num)
						{
							return LastLapRating.PERSONAL_BEST_CLOSE_TO_OVERALL_LEADER;
						}
						if (currentGameState.SessionData.OpponentsLapTimeSessionBestPlayerClass > currentGameState.SessionData.LapTimePrevious - num)
						{
							return LastLapRating.PERSONAL_BEST_CLOSE_TO_CLASS_LEADER;
						}
						if (currentGameState.SessionData.OpponentsLapTimeSessionBestPlayerClass > 0f || currentGameState.SessionData.OpponentsLapTimeSessionBestOverall > 0f)
						{
							return LastLapRating.PERSONAL_BEST_STILL_SLOW;
						}
					}
					else
					{
						if (currentGameState.SessionData.OpponentsLapTimeSessionBestOverall >= currentGameState.SessionData.LapTimePrevious - num)
						{
							return LastLapRating.CLOSE_TO_OVERALL_LEADER;
						}
						if (currentGameState.SessionData.OpponentsLapTimeSessionBestPlayerClass >= currentGameState.SessionData.LapTimePrevious - num)
						{
							return LastLapRating.CLOSE_TO_CLASS_LEADER;
						}
						if (currentGameState.SessionData.PlayerLapTimeSessionBest >= currentGameState.SessionData.LapTimePrevious - num && currentGameState.SessionData.CompletedLaps > 1)
						{
							return LastLapRating.CLOSE_TO_PERSONAL_BEST;
						}
						if (bestLapComparisonData[0] > 0f && bestLapComparisonData[0] < currentGameState.SessionData.LapTimePrevious - LapTimes.outlierPaceLimits[currentGameState.SessionData.TrackDefinition.trackLengthClass])
						{
							return LastLapRating.OUTLIER;
						}
						if (bestLapComparisonData[0] > 0f && bestLapComparisonData[0] < currentGameState.SessionData.LapTimePrevious - 3f)
						{
							return LastLapRating.BAD;
						}
						if (currentGameState.SessionData.PlayerLapTimeSessionBest > 0f)
						{
							return LastLapRating.MEH;
						}
					}
				}
				else
				{
					if (bestLapComparisonData[0] > 0f && currentGameState.SessionData.LapTimePrevious == bestLapComparisonData[0])
					{
						return LastLapRating.PERSONAL_BEST;
					}
					if (bestLapComparisonData[0] > 0f && bestLapComparisonData[0] >= currentGameState.SessionData.LapTimePrevious - num && currentGameState.SessionData.CompletedLaps > 1)
					{
						return LastLapRating.CLOSE_TO_PERSONAL_BEST;
					}
					if (bestLapComparisonData[0] > 0f && bestLapComparisonData[0] < currentGameState.SessionData.LapTimePrevious - 3f)
					{
						return LastLapRating.BAD;
					}
					if (currentGameState.SessionData.PlayerLapTimeSessionBest > 0f)
					{
						return LastLapRating.MEH;
					}
				}
			}
			return LastLapRating.NO_DATA;
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
			if (!Commands.Contains(cmd))
			{
				Log.Error(cmd.ToString() + " not handled by " + GetType().Name);
				return;
			}
			switch (cmd)
			{
			case SpeechCommands.ID.WHAT_ARE_MY_SECTOR_TIMES:
				if (currentGameState != null && currentGameState.SessionData.LastSector1Time > -1f && currentGameState.SessionData.LastSector2Time > -1f && currentGameState.SessionData.LastSector3Time > -1f)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("sector1Time", 0, AbstractEvent.MessageContents(TimeSpanWrapper.FromSeconds(currentGameState.SessionData.LastSector1Time, Precision.AUTO_LAPTIMES))));
					audioPlayer.playMessageImmediately(new QueuedMessage("sector2Time", 0, AbstractEvent.MessageContents(TimeSpanWrapper.FromSeconds(currentGameState.SessionData.LastSector2Time, Precision.AUTO_LAPTIMES))));
					audioPlayer.playMessageImmediately(new QueuedMessage("sector3Time", 0, AbstractEvent.MessageContents(TimeSpanWrapper.FromSeconds(currentGameState.SessionData.LastSector3Time, Precision.AUTO_LAPTIMES))));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				break;
			case SpeechCommands.ID.WHATS_MY_LAST_SECTOR_TIME:
				if (currentGameState != null && currentGameState.SessionData.SectorNumber == 1 && currentGameState.SessionData.LastSector3Time > -1f)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("sector3Time", 0, AbstractEvent.MessageContents(TimeSpanWrapper.FromSeconds(currentGameState.SessionData.LastSector3Time, Precision.AUTO_LAPTIMES))));
				}
				else if (currentGameState != null && currentGameState.SessionData.SectorNumber == 2 && currentGameState.SessionData.LastSector1Time > -1f)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("sector1Time", 0, AbstractEvent.MessageContents(TimeSpanWrapper.FromSeconds(currentGameState.SessionData.LastSector1Time, Precision.AUTO_LAPTIMES))));
				}
				else if (currentGameState != null && currentGameState.SessionData.SectorNumber == 3 && currentGameState.SessionData.LastSector2Time > -1f)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("sector2Time", 0, AbstractEvent.MessageContents(TimeSpanWrapper.FromSeconds(currentGameState.SessionData.LastSector2Time, Precision.AUTO_LAPTIMES))));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				break;
			case SpeechCommands.ID.WHATS_MY_BEST_LAP_TIME:
			{
				bool flag = false;
				if (CrewChief.currentGameState != null)
				{
					float playerBestLapTime = CrewChief.currentGameState.TimingData.getPlayerBestLapTime(TimingData.ConditionsEnum.ANY);
					if (playerBestLapTime > 0f)
					{
						flag = true;
						audioPlayer.playMessageImmediately(new QueuedMessage("bestLapTime", 0, AbstractEvent.MessageContents(TimeSpanWrapper.FromSeconds(playerBestLapTime, Precision.AUTO_LAPTIMES))));
					}
				}
				if (!flag)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				break;
			}
			case SpeechCommands.ID.WHATS_THE_FASTEST_LAP_TIME:
				if (currentGameState != null && currentGameState.SessionData.PlayerClassSessionBestLapTime > 0f)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("sessionFastestLaptime", 0, AbstractEvent.MessageContents(TimeSpanWrapper.FromSeconds(currentGameState.SessionData.PlayerClassSessionBestLapTime, Precision.AUTO_LAPTIMES))));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				break;
			case SpeechCommands.ID.WHAT_WAS_MY_LAST_LAP_TIME:
				if (CrewChief.currentGameState != null && CrewChief.currentGameState.SessionData.LapTimePrevious > 0f)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("laptime", 0, AbstractEvent.MessageContents(folderLapTimeIntro, TimeSpanWrapper.FromSeconds(CrewChief.currentGameState.SessionData.LapTimePrevious, Precision.AUTO_LAPTIMES))));
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				break;
			case SpeechCommands.ID.HOWS_MY_PACE:
				reportPace(selfPace: false);
				break;
			case SpeechCommands.ID.HOWS_MY_SELF_PACE:
				reportPace(selfPace: true);
				break;
			}
		}

		public void reportPace(bool selfPace)
		{
			if (sessionType == SessionType.Race)
			{
				if (currentGameState == null)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
					return;
				}
				float[] array = (selfPace ? currentGameState.SessionData.getPlayerTimeAndSectorsForBestLap(ignoreLast: false) : ((!currentGameState.TimingData.conditionsHaveChanged) ? currentGameState.getTimeAndSectorsForBestOpponentLapInWindow(paceCheckLapsWindowForRaceToUse, currentGameState.carClass) : new float[4]
				{
					currentGameState.TimingData.getPlayerClassOpponentBestLapTime(),
					currentGameState.TimingData.getPlayerClassOpponentBestLapSector1Time(),
					currentGameState.TimingData.getPlayerClassOpponentBestLapSector2Time(),
					currentGameState.TimingData.getPlayerClassOpponentBestLapSector3Time()
				}));
				if (array[0] > -1f && lastLapRating != LastLapRating.NO_DATA)
				{
					TimeSpan timeSpan = TimeSpan.FromSeconds(currentGameState.SessionData.LapTimePrevious - array[0]);
					string text = null;
					if (timeSpan.Seconds == 0 && timeSpan.Milliseconds < 200)
					{
						text = folderNeedToFindOneMoreTenth;
					}
					else if (timeSpan.Seconds == 0 && timeSpan.Milliseconds < 600)
					{
						text = folderNeedToFindAFewMoreTenths;
					}
					else if ((timeSpan.Seconds == 1 && timeSpan.Milliseconds < 500) || (timeSpan.Seconds == 0 && timeSpan.Milliseconds >= 600))
					{
						text = folderNeedToFindASecond;
					}
					else if ((timeSpan.Seconds == 1 && timeSpan.Milliseconds >= 500) || timeSpan.Seconds > 1)
					{
						text = folderNeedToFindMoreThanASecond;
					}
					List<MessageFragment> list = new List<MessageFragment>();
					if (!selfPace)
					{
						switch (lastLapRating)
						{
						case LastLapRating.BEST_OVERALL:
						case LastLapRating.BEST_IN_CLASS:
						case LastLapRating.SETTING_CURRENT_PACE:
							audioPlayer.playMessageImmediately(new QueuedMessage(folderSettingCurrentRacePace, 0));
							break;
						case LastLapRating.CLOSE_TO_CURRENT_PACE:
						case LastLapRating.PERSONAL_BEST_CLOSE_TO_OVERALL_LEADER:
						case LastLapRating.PERSONAL_BEST_CLOSE_TO_CLASS_LEADER:
						case LastLapRating.PERSONAL_BEST_STILL_SLOW:
						case LastLapRating.CLOSE_TO_OVERALL_LEADER:
						case LastLapRating.CLOSE_TO_CLASS_LEADER:
						case LastLapRating.CLOSE_TO_PERSONAL_BEST:
							if (text == null || text != folderNeedToFindMoreThanASecond)
							{
								if (lastLapRating == LastLapRating.CLOSE_TO_CURRENT_PACE)
								{
									list.Add(MessageFragment.Text(folderMatchingCurrentRacePace));
								}
								else
								{
									list.Add(MessageFragment.Text(folderPaceOK));
								}
							}
							if (text != null)
							{
								list.Add(MessageFragment.Text(text));
							}
							if (list.Count > 0)
							{
								audioPlayer.playMessageImmediately(new QueuedMessage("lapTimeRacePaceReport", 0, list));
							}
							break;
						case LastLapRating.MEH:
							if (text != null)
							{
								list.Add(MessageFragment.Text(text));
							}
							audioPlayer.playMessageImmediately(new QueuedMessage("lapTimeRacePaceReport", 0, list));
							break;
						case LastLapRating.BAD:
							if (GlobalBehaviourSettings.complaintsCountInThisSession < GlobalBehaviourSettings.maxComplaintsPerSession)
							{
								list.Add(MessageFragment.Text(folderPaceBad));
								GlobalBehaviourSettings.complaintsCountInThisSession++;
							}
							if (text != null)
							{
								list.Add(MessageFragment.Text(text));
							}
							audioPlayer.playMessageImmediately(new QueuedMessage("lapTimeRacePaceReport", 0, list));
							break;
						default:
							audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
							break;
						}
					}
					else
					{
						if (currentGameState.SessionData.LapTimePrevious > 0f)
						{
							audioPlayer.playMessageImmediately(new QueuedMessage("laptime", 0, AbstractEvent.MessageContents(folderLapTimeIntro, TimeSpanWrapper.FromSeconds(currentGameState.SessionData.LapTimePrevious, Precision.AUTO_LAPTIMES))));
						}
						switch (lastLapSelfRating)
						{
						case LastLapRating.PERSONAL_BEST:
							audioPlayer.playMessageImmediately(new QueuedMessage(folderPersonalBest, 0));
							break;
						case LastLapRating.CLOSE_TO_PERSONAL_BEST:
							if (text == null || text != folderNeedToFindMoreThanASecond)
							{
								list.Add(MessageFragment.Text(folderPaceOK));
							}
							if (text != null)
							{
								list.Add(MessageFragment.Text(text));
							}
							if (list.Count > 0)
							{
								audioPlayer.playMessageImmediately(new QueuedMessage("lapTimeRacePaceReport", 0, list));
							}
							break;
						case LastLapRating.BAD:
							if (GlobalBehaviourSettings.complaintsCountInThisSession < GlobalBehaviourSettings.maxComplaintsPerSession)
							{
								list.Add(MessageFragment.Text(folderPaceBad));
								GlobalBehaviourSettings.complaintsCountInThisSession++;
							}
							if (text != null)
							{
								list.Add(MessageFragment.Text(text));
							}
							audioPlayer.playMessageImmediately(new QueuedMessage("lapTimeRacePaceReport", 0, list));
							break;
						case LastLapRating.MEH:
							if (text != null)
							{
								list.Add(MessageFragment.Text(text));
							}
							audioPlayer.playMessageImmediately(new QueuedMessage("lapTimeRacePaceReport", 0, list));
							break;
						default:
							audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
							break;
						}
					}
					SectorReportOption reportOption = SectorReportOption.ALL;
					if (Utilities.random.NextDouble() > 0.33)
					{
						reportOption = SectorReportOption.WORST_ONLY;
					}
					List<MessageFragment> sectorDeltaMessages = getSectorDeltaMessages(reportOption, currentGameState.SessionData.LastSector1Time, array[1], currentGameState.SessionData.LastSector2Time, array[2], currentGameState.SessionData.LastSector3Time, array[3], comparisonIncludesAllLaps: false, selfPace);
					if (sectorDeltaMessages.Count > 0)
					{
						audioPlayer.playMessageImmediately(new QueuedMessage("sectorDeltas", 0, sectorDeltaMessages));
					}
				}
				else
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
				}
				return;
			}
			if (deltaPlayerLastToSessionBestInClassSet)
			{
				if (!selfPace)
				{
					if (deltaPlayerLastToSessionBestInClass <= TimeSpan.Zero)
					{
						TimeSpan timeSpan2 = deltaPlayerLastToSessionBestInClass.Negate();
						if (timeSpan2.Seconds > 0 || timeSpan2.Milliseconds > 50)
						{
							audioPlayer.playMessageImmediately(new QueuedMessage("lapTimeNotRaceGap", 0, AbstractEvent.MessageContents(folderGapIntro, new TimeSpanWrapper(timeSpan2, Precision.AUTO_GAPS), folderQuickerThanSecondPlace), null, null, null, 0, this));
						}
					}
					else if (deltaPlayerLastToSessionBestInClass.Seconds == 0 && deltaPlayerLastToSessionBestInClass.Milliseconds < 50)
					{
						audioPlayer.playMessageImmediately(new QueuedMessage(folderLessThanATenthOffThePace, 0));
					}
					else
					{
						audioPlayer.playMessageImmediately(new QueuedMessage("lapTimeNotRaceGap", 0, AbstractEvent.MessageContents(new TimeSpanWrapper(deltaPlayerLastToSessionBestInClass, Precision.AUTO_GAPS), folderGapOutroOffPace)));
					}
				}
				else if (currentGameState.SessionData.LapTimePrevious > 0f)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage("laptime", 0, AbstractEvent.MessageContents(folderLapTimeIntro, TimeSpanWrapper.FromSeconds(currentGameState.SessionData.LapTimePrevious, Precision.AUTO_LAPTIMES))));
					List<MessageFragment> list2 = new List<MessageFragment>();
					switch (lastLapSelfRating)
					{
					case LastLapRating.PERSONAL_BEST:
						audioPlayer.playMessageImmediately(new QueuedMessage(folderPersonalBest, 0));
						break;
					case LastLapRating.CLOSE_TO_PERSONAL_BEST:
						audioPlayer.playMessageImmediately(new QueuedMessage(folderPaceOK, 0));
						break;
					case LastLapRating.MEH:
					case LastLapRating.BAD:
						if (GlobalBehaviourSettings.complaintsCountInThisSession < GlobalBehaviourSettings.maxComplaintsPerSession)
						{
							list2.Add(MessageFragment.Text(folderPaceBad));
							GlobalBehaviourSettings.complaintsCountInThisSession++;
						}
						audioPlayer.playMessageImmediately(new QueuedMessage("lapTimeRacePaceReport", 0, list2));
						break;
					}
				}
				try
				{
					float[] array2 = (selfPace ? currentGameState.SessionData.getPlayerTimeAndSectorsForBestLap(ignoreLast: false) : new float[4]
					{
						currentGameState.TimingData.getPlayerClassOpponentBestLapTime(),
						currentGameState.TimingData.getPlayerClassOpponentBestLapSector1Time(),
						currentGameState.TimingData.getPlayerClassOpponentBestLapSector2Time(),
						currentGameState.TimingData.getPlayerClassOpponentBestLapSector3Time()
					});
					List<MessageFragment> sectorDeltaMessages2 = getSectorDeltaMessages(SectorReportOption.ALL, currentGameState.SessionData.LastSector1Time, array2[1], currentGameState.SessionData.LastSector2Time, array2[2], currentGameState.SessionData.LastSector3Time, array2[3], comparisonIncludesAllLaps: true, selfPace);
					if (sectorDeltaMessages2.Count > 0)
					{
						audioPlayer.playMessageImmediately(new QueuedMessage("sectorDeltas", 0, sectorDeltaMessages2));
					}
					return;
				}
				catch (Exception exception)
				{
					Log.Exception(exception, "Unable to get sector deltas: ");
					return;
				}
			}
			audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
		}

		internal static Delta GetDelta(float delta)
		{
			Delta result = Delta.NONE;
			if (delta < 0.05f)
			{
				result = Delta.FAST;
			}
			else if (delta < 0.15f)
			{
				result = Delta.A_TENTH;
			}
			else if (delta < 0.25f)
			{
				result = Delta.TWO_TENTHS;
			}
			else if (delta > 0.95f && delta < 1.05f)
			{
				result = Delta.A_SECOND;
			}
			else if (delta < 10f)
			{
				result = Delta.AUTO_GAPS;
			}
			return result;
		}

		public static List<MessageFragment> getSingleSectorDeltaMessages(SectorSet sector, float playerTime, float comparisonTime, bool selfPace)
		{
			List<MessageFragment> list = new List<MessageFragment>();
			if (playerTime > 5f && comparisonTime > 5f)
			{
				float num = playerTime - comparisonTime;
				switch (GetDelta(num))
				{
				case Delta.FAST:
					switch (sector)
					{
					case SectorSet.ONE:
						list.Add(MessageFragment.Text(folderSector1Fast));
						break;
					case SectorSet.TWO:
						list.Add(MessageFragment.Text(folderSector2Fast));
						break;
					default:
						list.Add(MessageFragment.Text(folderSector3Fast));
						break;
					}
					break;
				case Delta.A_TENTH:
					switch (sector)
					{
					case SectorSet.ONE:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector1ATenthOffThePace : folderSector1ATenthOffThePace));
						break;
					case SectorSet.TWO:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector2ATenthOffThePace : folderSector2ATenthOffThePace));
						break;
					default:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector3ATenthOffThePace : folderSector3ATenthOffThePace));
						break;
					}
					break;
				case Delta.TWO_TENTHS:
					switch (sector)
					{
					case SectorSet.ONE:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector1TwoTenthsOffThePace : folderSector1TwoTenthsOffThePace));
						break;
					case SectorSet.TWO:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector2TwoTenthsOffThePace : folderSector2TwoTenthsOffThePace));
						break;
					default:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector3TwoTenthsOffThePace : folderSector3TwoTenthsOffThePace));
						break;
					}
					break;
				case Delta.A_SECOND:
					switch (sector)
					{
					case SectorSet.ONE:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector1ASecondOffThePace : folderSector1ASecondOffThePace));
						break;
					case SectorSet.TWO:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector2ASecondOffThePace : folderSector2ASecondOffThePace));
						break;
					default:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector3ASecondOffThePace : folderSector3ASecondOffThePace));
						break;
					}
					break;
				case Delta.AUTO_GAPS:
					if ((double)num < 4.0 + 2.0 * Utilities.random.NextDouble())
					{
						switch (sector)
						{
						case SectorSet.ONE:
							list.Add(MessageFragment.Text(folderSector1Is));
							break;
						case SectorSet.TWO:
							list.Add(MessageFragment.Text(folderSector2Is));
							break;
						default:
							list.Add(MessageFragment.Text(folderSector3Is));
							break;
						}
						list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(num, Precision.AUTO_GAPS)));
						list.Add(MessageFragment.Text(selfPace ? folderSelfOffThePace : folderOffThePace));
					}
					break;
				}
			}
			if (list.Count > 0)
			{
				Console.WriteLine("lgcy: Sector = " + sector.ToString() + " delta (-ve = player faster) = " + (playerTime - comparisonTime).ToString("0.000"));
				Console.WriteLine("lgcy: Resolved delta message: " + string.Join(", ", list));
			}
			else
			{
				Console.WriteLine("lgcy: Skipping sector pace delta message:  Sector = " + sector.ToString() + " delta (-ve = player faster) = " + (playerTime - comparisonTime).ToString("0.000"));
			}
			return list;
		}

		private static float getAutoRoundedDelta(float time1, float time2)
		{
			float num = time1 - time2;
			if ((double)Math.Abs(num) < 0.5)
			{
				return (float)Math.Round(num * 100f) / 100f;
			}
			return (float)Math.Round(num * 10f) / 10f;
		}

		public static List<MessageFragment> getSectorDeltaMessages(SectorReportOption reportOption, float playerSector1, float comparisonSector1, float playerSector2, float comparisonSector2, float playerSector3, float comparisonSector3, bool comparisonIncludesAllLaps, bool selfPace)
		{
			List<MessageFragment> list = new List<MessageFragment>();
			float num = float.MaxValue;
			float num2 = float.MaxValue;
			float num3 = float.MaxValue;
			if (playerSector1 > 5f && comparisonSector1 > 5f)
			{
				num = ((!(playerSector1 < comparisonSector1)) ? getAutoRoundedDelta(playerSector1, comparisonSector1) : (-1f));
			}
			if (playerSector2 > 5f && comparisonSector2 > 5f)
			{
				num2 = ((!(playerSector2 < comparisonSector2)) ? getAutoRoundedDelta(playerSector2, comparisonSector2) : (-1f));
			}
			if (playerSector3 > 5f && comparisonSector3 > 5f)
			{
				num3 = ((!(playerSector3 < comparisonSector3)) ? getAutoRoundedDelta(playerSector3, comparisonSector3) : (-1f));
			}
			if (reportOption == SectorReportOption.WORST_ONLY)
			{
				if (num < float.MaxValue && num > num2 && num > num3)
				{
					num2 = float.MaxValue;
					num3 = float.MaxValue;
				}
				else if (num2 < float.MaxValue && num2 > num && num2 > num3)
				{
					num = float.MaxValue;
					num3 = float.MaxValue;
				}
				else if (num3 < float.MaxValue && num3 > num && num3 > num2)
				{
					num = float.MaxValue;
					num2 = float.MaxValue;
				}
			}
			bool flag = false;
			bool flag2 = false;
			bool flag3 = false;
			if (nearlyEqual(num, num2))
			{
				if (nearlyEqual(num3, num))
				{
					flag = true;
					flag2 = true;
					flag3 = true;
					switch (GetDelta(num))
					{
					case Delta.FAST:
						list.Add(MessageFragment.Text(folderAllSectorsFast));
						break;
					case Delta.A_TENTH:
						list.Add(MessageFragment.Text(selfPace ? folderSelfAllSectorsATenthOffThePace : folderAllSectorsATenthOffThePace));
						break;
					case Delta.TWO_TENTHS:
						list.Add(MessageFragment.Text(selfPace ? folderSelfAllSectorsTwoTenthsOffThePace : folderAllSectorsTwoTenthsOffThePace));
						break;
					case Delta.A_SECOND:
						list.Add(MessageFragment.Text(selfPace ? folderSelfAllSectorsASecondOffThePace : folderAllSectorsASecondOffThePace));
						break;
					case Delta.AUTO_GAPS:
						list.Add(MessageFragment.Text(folderAllThreeSectorsAre));
						list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(num, Precision.AUTO_GAPS)));
						list.Add(MessageFragment.Text(selfPace ? folderSelfOffThePace : folderOffThePace));
						break;
					}
				}
				else
				{
					flag = true;
					flag2 = true;
					switch (GetDelta(num))
					{
					case Delta.FAST:
						list.Add(MessageFragment.Text(folderSector1and2Fast));
						break;
					case Delta.A_TENTH:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector1and2ATenthOffThePace : folderSector1and2ATenthOffThePace));
						break;
					case Delta.TWO_TENTHS:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector1and2TwoTenthsOffThePace : folderSector1and2TwoTenthsOffThePace));
						break;
					case Delta.A_SECOND:
						list.Add(MessageFragment.Text(selfPace ? folderSelfSector1and2ASecondOffThePace : folderSector1and2ASecondOffThePace));
						break;
					case Delta.AUTO_GAPS:
						list.Add(MessageFragment.Text(folderSectors1And2Are));
						list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(num, Precision.AUTO_GAPS)));
						list.Add(MessageFragment.Text(selfPace ? folderSelfOffThePace : folderOffThePace));
						break;
					}
				}
			}
			else if (nearlyEqual(num2, num3))
			{
				flag2 = true;
				flag3 = true;
				switch (GetDelta(num2))
				{
				case Delta.FAST:
					list.Add(MessageFragment.Text(folderSector2and3Fast));
					break;
				case Delta.A_TENTH:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector2and3ATenthOffThePace : folderSector2and3ATenthOffThePace));
					break;
				case Delta.TWO_TENTHS:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector2and3TwoTenthsOffThePace : folderSector2and3TwoTenthsOffThePace));
					break;
				case Delta.A_SECOND:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector2and3ASecondOffThePace : folderSector2and3ASecondOffThePace));
					break;
				case Delta.AUTO_GAPS:
					list.Add(MessageFragment.Text(folderSectors2And3Are));
					list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(num2, Precision.AUTO_GAPS)));
					list.Add(MessageFragment.Text(selfPace ? folderSelfOffThePace : folderOffThePace));
					break;
				}
			}
			else if (nearlyEqual(num, num3))
			{
				flag = true;
				flag3 = true;
				switch (GetDelta(num))
				{
				case Delta.FAST:
					list.Add(MessageFragment.Text(folderSector1and3Fast));
					break;
				case Delta.A_TENTH:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector1and3ATenthOffThePace : folderSector1and3ATenthOffThePace));
					break;
				case Delta.TWO_TENTHS:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector1and3TwoTenthsOffThePace : folderSector1and3TwoTenthsOffThePace));
					break;
				case Delta.A_SECOND:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector1and3ASecondOffThePace : folderSector1and3ASecondOffThePace));
					break;
				case Delta.AUTO_GAPS:
					list.Add(MessageFragment.Text(folderSectors1And3Are));
					list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(num, Precision.AUTO_GAPS)));
					list.Add(MessageFragment.Text(selfPace ? folderSelfOffThePace : folderOffThePace));
					break;
				}
			}
			if (!flag)
			{
				switch (GetDelta(num))
				{
				case Delta.FAST:
					list.Add(MessageFragment.Text(folderSector1Fast));
					break;
				case Delta.A_TENTH:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector1ATenthOffThePace : folderSector1ATenthOffThePace));
					break;
				case Delta.TWO_TENTHS:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector1TwoTenthsOffThePace : folderSector1TwoTenthsOffThePace));
					break;
				case Delta.A_SECOND:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector1ASecondOffThePace : folderSector1ASecondOffThePace));
					break;
				case Delta.AUTO_GAPS:
					list.Add(MessageFragment.Text(folderSector1Is));
					list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(num, Precision.AUTO_GAPS)));
					list.Add(MessageFragment.Text(selfPace ? folderSelfOffThePace : folderOffThePace));
					break;
				}
			}
			if (!flag2)
			{
				switch (GetDelta(num2))
				{
				case Delta.FAST:
					list.Add(MessageFragment.Text(folderSector2Fast));
					break;
				case Delta.A_TENTH:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector2ATenthOffThePace : folderSector2ATenthOffThePace));
					break;
				case Delta.TWO_TENTHS:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector2TwoTenthsOffThePace : folderSector2TwoTenthsOffThePace));
					break;
				case Delta.A_SECOND:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector2ASecondOffThePace : folderSector2ASecondOffThePace));
					break;
				case Delta.AUTO_GAPS:
					list.Add(MessageFragment.Text(folderSector2Is));
					list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(num2, Precision.AUTO_GAPS)));
					list.Add(MessageFragment.Text(selfPace ? folderSelfOffThePace : folderOffThePace));
					break;
				}
			}
			if (!flag3)
			{
				switch (GetDelta(num3))
				{
				case Delta.FAST:
					list.Add(MessageFragment.Text(folderSector3Fast));
					break;
				case Delta.A_TENTH:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector3ATenthOffThePace : folderSector3ATenthOffThePace));
					break;
				case Delta.TWO_TENTHS:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector3TwoTenthsOffThePace : folderSector3TwoTenthsOffThePace));
					break;
				case Delta.A_SECOND:
					list.Add(MessageFragment.Text(selfPace ? folderSelfSector3ASecondOffThePace : folderSector3ASecondOffThePace));
					break;
				case Delta.AUTO_GAPS:
					list.Add(MessageFragment.Text(folderSector3Is));
					list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(num3, Precision.AUTO_GAPS)));
					list.Add(MessageFragment.Text(selfPace ? folderSelfOffThePace : folderOffThePace));
					break;
				}
			}
			if (list.Count > 0)
			{
				Console.WriteLine("lgcy: Player best sectors " + playerSector1.ToString("0.000") + ",    " + playerSector2.ToString("0.000") + ",    " + playerSector3.ToString("0.000"));
				Console.WriteLine("lgcy: Opponent best sectors " + comparisonSector1.ToString("0.000") + ",    " + comparisonSector2.ToString("0.000") + ",    " + comparisonSector3.ToString("0.000"));
				Console.WriteLine("lgcy: S1 delta (-ve = player faster) = " + (playerSector1 - comparisonSector1).ToString("0.000") + "    S2 delta  = " + (playerSector2 - comparisonSector2).ToString("0.000") + "    S3 delta  = " + (playerSector3 - comparisonSector3).ToString("0.000"));
				Console.WriteLine("lgcy: Resolved delta message: " + string.Join(", ", list));
			}
			return list;
		}

		private bool ConditionsHaveChanged(Conditions.ConditionsSample sample1, Conditions.ConditionsSample sample2)
		{
			if (sample1 == null || sample2 == null)
			{
				return false;
			}
			if (ConditionsMonitor.getRainLevel(sample1.RainDensity) == ConditionsMonitor.getRainLevel(sample2.RainDensity))
			{
				return Math.Abs(sample1.TrackTemperature - sample2.TrackTemperature) > 4f;
			}
			return true;
		}

		public static bool nearlyEqual(float a, float b)
		{
			if (a == b)
			{
				return true;
			}
			float num = Math.Abs(a);
			float num2 = Math.Abs(b);
			float num3 = Math.Abs(num - num2);
			float num4 = ((num3 <= 0.1f) ? 0.04f : ((!(num3 <= 0.5f)) ? 0.15f : 0.1f));
			return num3 < num4;
		}
	}
}
