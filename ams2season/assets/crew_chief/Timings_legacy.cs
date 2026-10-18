using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using CrewChiefV4.Audio;
using CrewChiefV4.GameState;
using CrewChiefV4.NumberProcessing;
using Newtonsoft.Json;

namespace CrewChiefV4.Events
{
	internal class Timings_legacy : AbstractEvent
	{
		private class Gap
		{
			public readonly float signedTimeDelta;

			public readonly int signedLapDelta;

			public readonly string opponentKey;

			public readonly float timeDelta;

			public readonly float lapDelta;

			public Gap(float signedTimeDelta, int signedLapDelta, string opponentKey)
			{
				this.signedTimeDelta = signedTimeDelta;
				this.signedLapDelta = signedLapDelta;
				this.opponentKey = opponentKey;
				timeDelta = Math.Abs(signedTimeDelta);
				lapDelta = Math.Abs(signedLapDelta);
			}
		}

		private class DriverAtTime
		{
			public readonly DateTime started;

			public readonly string driver;

			public DriverAtTime(DateTime started, string driver)
			{
				this.started = started;
				this.driver = driver;
			}
		}

		private enum GapStatus
		{
			CLOSE,
			INCREASING,
			DECREASING,
			OTHER,
			NONE
		}

		private float badReputationThreshold = 65f;

		private float sketchyReputationThreshold = 75f;

		private int minRacesForReputationToBeInteresting = 12;

		private static readonly float minGapToReport = 0.05f;

		public static string folderGapInFrontIncreasing = "timings/gap_in_front_increasing";

		public static string folderGapInFrontDecreasing = "timings/gap_in_front_decreasing";

		public static string folderGapInFrontIsNow = "timings/gap_in_front_is_now";

		public static string folderHeIsSlowerThroughCorner = "timings/he_is_slower_through_corner";

		public static string folderHeIsFasterThroughCorner = "timings/he_is_faster_through_corner";

		public static string folderHeIsSlowerEnteringCorner = "timings/he_is_slower_entering_corner";

		public static string folderHeIsFasterEnteringCorner = "timings/he_is_faster_entering_corner";

		public static string folderGapBehindIncreasing = "timings/gap_behind_increasing";

		public static string folderGapBehindDecreasing = "timings/gap_behind_decreasing";

		public static string folderGapBehindIsNow = "timings/gap_behind_is_now";

		public static string folderTheGapTo = "timings/the_gap_to";

		public static string folderAheadIsIncreasing = "timings/ahead_is_increasing";

		public static string folderBehindIsIncreasing = "timings/behind_is_increasing";

		public static string folderAheadIsNow = "timings/ahead_is_now";

		public static string folderBehindIsNow = "timings/behind_is_now";

		public static string folderYoureReeling = "timings/youre_reeling";

		public static string folderInTheGapIsNow = "timings/in_the_gap_is_now";

		public static string folderIsReelingYouIn = "timings/is_reeling_you_in";

		private readonly string folderBeingHeldUp = "timings/being_held_up";

		private string folderBeingPressured = "timings/being_pressured";

		private string folderOpponentAheadBadReputation = "timings/opponent_ahead_has_bad_reputation";

		private string folderOpponentAheadSketchyReputation = "timings/opponent_ahead_has_below_average_reputation";

		private string folderOpponentBehindBadReputation = "timings/opponent_behind_has_bad_reputation";

		private string folderOpponentBehindSketchyReputation = "timings/opponent_behind_has_below_average_reputation";

		private readonly int gapAheadReportFrequency = UserSettings.GetUserSettings().getInt("frequency_of_gap_ahead_reports");

		private readonly int gapBehindReportFrequency = UserSettings.GetUserSettings().getInt("frequency_of_gap_behind_reports");

		private readonly int gapBehindOnTrackReportFrequency = UserSettings.GetUserSettings().getInt("frequency_of_gap_behind_on_track_reports");

		private new readonly bool iRacingReputations = UserSettings.GetUserSettings().getBoolean("iracing_reputations");

		private readonly string iRacingClubReputationsRaw = UserSettings.GetUserSettings().getString("iracing_reputations_flair_bad");

		private new readonly int iRacingMinRating = UserSettings.GetUserSettings().getInt("iracing_reputations_rating");

		private readonly int iRacingMinDivision = UserSettings.GetUserSettings().getInt("iracing_reputations_division");

		private HashSet<string> iRacingSketchyClubs = new HashSet<string>();

		private new List<int> iRacingBadDrivers = new List<int>();

		private new HashSet<string> driverReputationWarningChecksInThisSession = new HashSet<string>();

		private bool preferGapReportsMidLap = true;

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

		private readonly bool enableGapMessages = UserSettings.GetUserSettings().getBoolean("enable_gap_messages");

		private readonly int gapMessageRandomness = UserSettings.GetUserSettings().getInt("gap_message_randomness");

		private int gapAheadMinSectorWait;

		private int gapAheadMaxSectorWait;

		private int gapBehindMinSectorWait;

		private int gapBehindMaxSectorWait;

		private int gapBehindOnTrackMinSectorWait;

		private int gapBehindOnTrackMaxSectorWait;

		private Dictionary<string, DateTime> trackLandmarkAttackDriverNamesUsed = new Dictionary<string, DateTime>();

		private Dictionary<string, DateTime> trackLandmarkDefendDriverNamesUsed = new Dictionary<string, DateTime>();

		private TimeSpan minTimeBetweenAttackOrDefendByDriver = TimeSpan.FromMinutes(3.0);

		private volatile DriverAtTime holdingUsUp;

		private volatile string lappingUs;

		private volatile bool initialized;

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
			SpeechCommands.ID.WHERE_AM_I_SLOWER
		};

		public Timings_legacy(AudioPlayer audioPlayer)
		{
			base.audioPlayer = audioPlayer;
			int num = Math.Min(Math.Max(1, gapMessageRandomness), 10);
			gapAheadMinSectorWait = 11 - Math.Min(Math.Max(1, gapAheadReportFrequency), 10);
			gapAheadMaxSectorWait = gapAheadMinSectorWait + num;
			gapBehindMinSectorWait = 11 - Math.Min(Math.Max(1, gapBehindReportFrequency), 10);
			gapBehindMaxSectorWait = gapBehindMinSectorWait + num;
			gapBehindOnTrackMinSectorWait = 11 - Math.Min(Math.Max(1, gapBehindOnTrackReportFrequency), 10);
			gapBehindOnTrackMaxSectorWait = gapBehindOnTrackMinSectorWait + num;
		}

		public override void clearState()
		{
			gapsInFront = new List<Gap>();
			gapsBehind = new List<Gap>();
			gapsBehindOnTrack = new List<Gap>();
			gapInFrontAtLastReport = -1f;
			gapBehindAtLastReport = -1f;
			gapBehindOnTrackAtLastReport = -1f;
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
			trackLandmarkAttackDriverNamesUsed.Clear();
			trackLandmarkDefendDriverNamesUsed.Clear();
			iRacingSketchyClubs.Clear();
			iRacingBadDrivers.Clear();
			initialized = false;
		}

		private int adjustForMidLapPreference(int currentSector, int sectorsTillNextReport)
		{
			if (preferGapReportsMidLap && (currentSector + sectorsTillNextReport - 1) % 3 == 0)
			{
				int num = Utilities.random.Next(0, 3);
				Log.Debug("lgcy: Adjusting gap report wait from " + sectorsTillNextReport + " to " + (sectorsTillNextReport + num));
				return sectorsTillNextReport + num;
			}
			return sectorsTillNextReport;
		}

		private int nextReport(GameStateData currentGameState, int minSectorWait, int maxSectorWait)
		{
			int num = Utilities.random.Next(minSectorWait, maxSectorWait);
			if (currentGameState.SessionData.TrackDefinition.gapPoints.Count() <= 0)
			{
				num = adjustForMidLapPreference(currentGameState.SessionData.SectorNumber, num);
			}
			return num;
		}

		private bool isNearRaceEnd(GameStateData currentGameState)
		{
			if (!currentGameState.SessionData.SessionHasFixedTime)
			{
				if (currentGameState.SessionData.SessionLapsRemaining == 0)
				{
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
			else if (currentGameState.SessionData.SessionTimeRemaining > -1f && currentGameState.SessionData.SessionTimeRemaining < 120f)
			{
				return true;
			}
			return false;
		}

		private (Gap, OpponentData) mkGapFrontInRace(GameStateData currentGameState)
		{
			string opponentKeyInFront = currentGameState.SessionData.OpponentKeyInFront;
			Gap item = new Gap(0f - currentGameState.SessionData.TimeDeltaFront, -currentGameState.SessionData.LapsDeltaFront, opponentKeyInFront);
			OpponentData value = null;
			if (opponentKeyInFront != null)
			{
				currentGameState.OpponentData.TryGetValue(opponentKeyInFront, out value);
			}
			return (item, value);
		}

		private (Gap, OpponentData) mkGapBehindInRace(GameStateData currentGameState)
		{
			string opponentKeyBehind = currentGameState.SessionData.OpponentKeyBehind;
			Gap item = new Gap(currentGameState.SessionData.TimeDeltaBehind, currentGameState.SessionData.LapsDeltaBehind, opponentKeyBehind);
			OpponentData value = null;
			if (opponentKeyBehind != null)
			{
				currentGameState.OpponentData.TryGetValue(opponentKeyBehind, out value);
			}
			return (item, value);
		}

		private (Gap, OpponentData)? mkGapBehindOnTrack(GameStateData currentGameState, bool onlyIncludeCarsLappingThePlayer = false)
		{
			string opponentKeyBehind = currentGameState.getOpponentKeyBehind(currentGameState.carClass);
			string opponentKeyBehindOnTrack = currentGameState.getOpponentKeyBehindOnTrack(onlyIncludeCarsLappingThePlayer, currentGameState.carClass);
			if (opponentKeyBehindOnTrack != null && !opponentKeyBehindOnTrack.Equals(opponentKeyBehind) && currentGameState.OpponentData.TryGetValue(opponentKeyBehindOnTrack, out var value))
			{
				var (signedLapDelta, num) = currentGameState.SessionData.DeltaTime.GetRelativeDelta(value.DeltaTime);
				if (num >= 0f)
				{
					return (new Gap(num, signedLapDelta, opponentKeyBehindOnTrack), value);
				}
			}
			return null;
		}

		private bool isNotRacing(GameStateData currentGameState)
		{
			if (!currentGameState.FlagData.currentLapIsFCY && !currentGameState.FlagData.isLocalYellow && currentGameState.SessionData.Flag != FlagEnum.BLUE && !currentGameState.PitData.InPitlane)
			{
				return PitStops.isPittingThisLap;
			}
			return true;
		}

		private bool putPersistedBadDriver(OpponentData opponent)
		{
			driverReputationWarningChecksInThisSession.Add(opponent.DriverRawName);
			PersistedIRacingBadReputation persistedIRacingBadReputation = new PersistedIRacingBadReputation();
			persistedIRacingBadReputation.customer_id = opponent.CostId;
			persistedIRacingBadReputation.name = opponent.DriverRawName;
			persistedIRacingBadReputation.carClass = opponent.CarClass.carClassEnumString;
			persistedIRacingBadReputation.date = DateTime.UtcNow.ToString("yyyy-MM-dd");
			persistedIRacingBadReputation.comment = "added by CrewChief";
			try
			{
				List<PersistedIRacingBadReputation> persistedBadDrivers = getPersistedBadDrivers();
				persistedBadDrivers.Add(persistedIRacingBadReputation);
				string text = JsonConvert.SerializeObject(persistedBadDrivers, Formatting.Indented);
				if (!File.Exists(DataFiles.iracing_reputations) || !text.Equals(File.ReadAllText(DataFiles.iracing_reputations)))
				{
					File.WriteAllText(DataFiles.iracing_reputations, text);
					return true;
				}
			}
			catch (Exception arg)
			{
				Console.WriteLine($"Error when updating the iRacing reputation data: {arg}");
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

		protected override void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
		{
			if (previousGameState == null || currentGameState == null)
			{
				return;
			}
			if (currentGameState.readLandmarksForThisLap && currentGameState.SessionData.trackLandmarksTiming != null && currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark != null)
			{
				audioPlayer.playMessage(new QueuedMessage("corners/" + currentGameState.SessionData.trackLandmarksTiming.atMidPointOfLandmark, 2, null, null, null, null, 0, null, null, 10));
			}
			if (GameStateData.onManualFormationLap)
			{
				return;
			}
			if (!initialized)
			{
				if (iRacingReputations && Game.IRACING)
				{
					string[] array = (GlobalBehaviourSettings.useOvalLogic ? iRacingClubReputationsRaw.Replace(';', ',') : iRacingClubReputationsRaw.Split(';')[0]).Split(',');
					for (int i = 0; i < array.Length; i++)
					{
						string text = array[i].Trim().ToLower();
						if (!text.Equals(""))
						{
							Console.WriteLine("Reputations: considering '" + text + "' to be a sketchy club");
							iRacingSketchyClubs.Add(text);
						}
					}
					try
					{
						foreach (PersistedIRacingBadReputation persistedBadDriver in getPersistedBadDrivers())
						{
							iRacingBadDrivers.Add(persistedBadDriver.customer_id);
						}
					}
					catch (Exception arg)
					{
						Console.WriteLine($"Error when loading the iRacing reputation data: {arg}");
					}
				}
				initialized = true;
			}
			if (!currentGameState.SessionData.IsRacingSameCarInFront)
			{
				gapsInFront.Clear();
				gapInFrontAtLastReport = -1f;
				holdingUsUp = null;
			}
			if (!currentGameState.SessionData.IsRacingSameCarBehind)
			{
				gapsBehind.Clear();
				gapBehindAtLastReport = -1f;
			}
			if (!enableGapMessages || previousGameState.SessionData.CompletedLaps <= currentGameState.FlagData.lapCountWhenLastWentGreen || currentGameState.SessionData.SessionType != SessionType.Race || isNotRacing(currentGameState) || isNearRaceEnd(currentGameState))
			{
				return;
			}
			bool num = IsNewSectorOrGapPoint(previousGameState, currentGameState);
			GapStatus gapInFrontStatus = GapStatus.NONE;
			Gap currentGapInFront = null;
			OpponentData opponentInFront = null;
			GapStatus gapBehindStatus = GapStatus.NONE;
			Gap currentGapBehind = null;
			OpponentData opponentBehind = null;
			GapStatus gapBehindOnTrackStatus = GapStatus.NONE;
			(Gap, OpponentData)? behindOnTrack = null;
			if (num)
			{
				if (currentGameState.SessionData.ClassPosition != 1)
				{
					var (gap, opponentData) = mkGapFrontInRace(currentGameState);
					if (opponentData != null && (gapsInFront.Count == 0 || gapsInFront[0].timeDelta != gap.timeDelta))
					{
						currentGapInFront = gap;
						opponentInFront = opponentData;
						gapsInFront.Insert(0, currentGapInFront);
						gapInFrontStatus = getGapStatus(gapsInFront, gapInFrontAtLastReport);
						if (gapInFrontStatus == GapStatus.CLOSE && !opponentInFront.DriverRawName.Equals(holdingUsUp?.driver))
						{
							holdingUsUp = new DriverAtTime(currentGameState.Now, opponentInFront.DriverRawName);
						}
					}
				}
				if (!currentGameState.isLast())
				{
					var (gap2, opponentData2) = mkGapBehindInRace(currentGameState);
					if (opponentData2 != null && (gapsBehind.Count == 0 || gapsBehind[0].timeDelta != gap2.timeDelta))
					{
						currentGapBehind = gap2;
						opponentBehind = opponentData2;
						gapsBehind.Insert(0, currentGapBehind);
						gapBehindStatus = getGapStatus(gapsBehind, gapBehindAtLastReport);
					}
				}
				behindOnTrack = mkGapBehindOnTrack(currentGameState);
				if (behindOnTrack?.Item2 != null)
				{
					if (!behindOnTrack.Value.Item1.opponentKey.Equals(lappingUs))
					{
						gapsBehindOnTrack.Clear();
						gapBehindOnTrackAtLastReport = -1f;
						lappingUs = behindOnTrack?.Item1.opponentKey;
						sectorsSinceLastGapBehindOnTrackReport = sectorsUntilNextGapBehindOnTrackReport;
					}
					if (gapsBehindOnTrack.Count == 0 || gapsBehindOnTrack[0].timeDelta != behindOnTrack.Value.Item1.timeDelta)
					{
						gapsBehindOnTrack.Insert(0, behindOnTrack?.Item1);
						gapBehindOnTrackStatus = getGapStatus(gapsBehindOnTrack, gapBehindOnTrackAtLastReport);
					}
				}
				else
				{
					lappingUs = null;
				}
			}
			if (num && !CrewChief.readOpponentDeltasForEveryLap)
			{
				sectorsSinceLastGapAheadReport++;
				sectorsSinceLastGapBehindReport++;
				sectorsSinceLastGapBehindOnTrackReport++;
				bool flag = gapBehindOnTrackReportFrequency > 0 && (gapBehindOnTrackStatus == GapStatus.DECREASING || (gapBehindOnTrackStatus == GapStatus.CLOSE && behindOnTrack.Value.Item2.ClassPosition < currentGameState.SessionData.ClassPosition)) && (gapBehindOnTrackStatus != GapStatus.CLOSE || !GlobalBehaviourSettings.justTheFacts) && behindOnTrack.Value.Item1.timeDelta <= 5f;
				bool flag2 = gapAheadReportFrequency > 0 && gapInFrontStatus != GapStatus.NONE && (gapInFrontStatus != GapStatus.CLOSE || (!GlobalBehaviourSettings.justTheFacts && !GlobalBehaviourSettings.useOvalLogic)) && gapBehindOnTrackStatus != GapStatus.CLOSE && currentGapInFront.lapDelta == 0f;
				bool flag3 = gapBehindReportFrequency > 0 && gapBehindStatus != GapStatus.NONE && (gapBehindStatus != GapStatus.CLOSE || (!GlobalBehaviourSettings.justTheFacts && !GlobalBehaviourSettings.useOvalLogic)) && !flag && currentGapBehind.lapDelta == 0f;
				bool flag4 = gapsInFront.Count > 0 && gapsBehind.Count > 0 && gapsInFront[0].timeDelta < gapsBehind[0].timeDelta;
				if (flag && sectorsSinceLastGapBehindOnTrackReport >= sectorsUntilNextGapBehindOnTrackReport)
				{
					DelayedMessage delayedMessage = delegate(GameStateData futureGameState, List<MessageFragment> primary, List<MessageFragment> alt)
					{
						if (isNotRacing(futureGameState))
						{
							Log.Debug("lgcy: gap_behind_on_track invalidated because we're not racing");
						}
						else
						{
							(Gap, OpponentData)? tuple4 = mkGapBehindOnTrack(futureGameState);
							if (!tuple4.HasValue || !behindOnTrack.Value.Item1.opponentKey.Equals(tuple4.Value.Item1.opponentKey))
							{
								Log.Debug("lgcy: gap_behind_on_track invalidated because opponent changed");
							}
							else if (tuple4.Value.Item1.timeDelta < minGapToReport)
							{
								Log.Debug("lgcy: gap_behind_on_track invalidated because opponent moved");
							}
							else
							{
								if (gapBehindOnTrackStatus == GapStatus.CLOSE)
								{
									if (tuple4.Value.Item2.ClassPosition < futureGameState.SessionData.ClassPosition)
									{
										primary.Add(MessageFragment.Text("frozen_order/allow_guy_behind_to_pass"));
									}
									else
									{
										primary.AddRange(Opponents.MkOpponentPosition(tuple4.Value.Item2.ClassPosition));
										primary.Add(MessageFragment.Text(Position.folderBehind));
									}
								}
								else
								{
									primary.Add(MessageFragment.Text(folderTheGapTo));
									primary.AddRange(Opponents.MkOpponentPosition(tuple4.Value.Item2.ClassPosition));
									primary.Add(MessageFragment.Text(folderBehindIsNow));
									primary.AddRange(MkOpponentRelativeDelta(tuple4?.Item2, 1, includeLapInfo: true));
								}
								gapBehindOnTrackAtLastReport = tuple4.Value.Item1.timeDelta;
								sectorsSinceLastGapBehindOnTrackReport = 0;
								sectorsUntilNextGapBehindOnTrackReport = nextReport(futureGameState, gapBehindOnTrackMinSectorWait, gapBehindOnTrackMaxSectorWait);
							}
						}
					};
					audioPlayer.playMessage(new QueuedMessage("Timings/gap_behind_on_track", 5, null, null, null, delayedMessage));
				}
				else if (flag2 && (flag4 || gapBehindReportFrequency <= 0) && sectorsSinceLastGapAheadReport >= sectorsUntilNextGapAheadReport)
				{
					DelayedMessage delayedMessage2 = delegate(GameStateData futureGameState, List<MessageFragment> msg, List<MessageFragment> alt_)
					{
						if (isNotRacing(futureGameState))
						{
							Log.Debug("lgcy: gap_in_front invalidated because we're not racing");
						}
						else if (futureGameState.SessionData.ClassPosition <= 1)
						{
							Log.Debug("lgcy: gap_in_front invalidated because we are first");
						}
						else
						{
							var (gap3, opponent) = mkGapFrontInRace(futureGameState);
							if (!currentGapInFront.opponentKey.Equals(gap3.opponentKey))
							{
								Log.Debug("lgcy: gap_in_front invalidated because opponent changed");
							}
							else
							{
								MessageFragment item3 = MessageFragment.Time(TimeSpanWrapper.FromSeconds(gap3.timeDelta, Precision.AUTO_GAPS));
								List<MessageFragment> collection = ((Utilities.random.Next(0, 3) != 0) ? Opponents.MkOpponentShort(opponentInFront, preferPosition: false, requestNumber: false, preferCantPronounce: false) : Opponents.MkOpponentPosition(opponentInFront.ClassPosition));
								if (gapInFrontStatus == GapStatus.CLOSE)
								{
									if (holdingUsUp != null && (futureGameState.Now - holdingUsUp.started).TotalSeconds > 60.0)
									{
										msg.AddRange(AbstractEvent.MessageContents(folderBeingHeldUp));
										if (gap3.timeDelta < 6f)
										{
											msg.AddRange(mkAttackAdvice(opponent, futureGameState));
										}
									}
									msg.AddRange(mkReputationAdvice(opponent, opponentIsAhead: true));
								}
								else if (gapInFrontStatus == GapStatus.INCREASING && gap3.timeDelta > minGapToReport)
								{
									msg.Add(MessageFragment.Text(folderTheGapTo));
									msg.AddRange(collection);
									msg.Add(MessageFragment.Text(folderAheadIsIncreasing));
									msg.Add(item3);
								}
								else if (gapInFrontStatus == GapStatus.DECREASING && gap3.timeDelta > minGapToReport)
								{
									msg.Add(MessageFragment.Text(folderYoureReeling));
									msg.AddRange(collection);
									msg.Add(MessageFragment.Text(folderInTheGapIsNow));
									msg.Add(item3);
									if (gap3.timeDelta < 6f)
									{
										msg.AddRange(mkAttackAdvice(opponent, futureGameState));
									}
									if (gap3.timeDelta < 2f)
									{
										msg.AddRange(mkReputationAdvice(opponent, opponentIsAhead: true));
									}
								}
								else if (gapInFrontStatus == GapStatus.OTHER && gap3.timeDelta > minGapToReport)
								{
									if (Utilities.random.Next(0, 3) == 0)
									{
										msg.AddRange(AbstractEvent.MessageContents(folderGapInFrontIsNow));
									}
									else
									{
										msg.Add(MessageFragment.Text(folderTheGapTo));
										msg.AddRange(collection);
										msg.Add(MessageFragment.Text(folderAheadIsNow));
									}
									msg.Add(item3);
								}
								else
								{
									Console.WriteLine("lgcy: Invalid gapInFrontStatus(" + gapInFrontStatus.ToString() + ") with gap " + gap3.timeDelta);
								}
								gapInFrontAtLastReport = gap3.timeDelta;
								sectorsSinceLastGapAheadReport = 0;
								sectorsUntilNextGapAheadReport = nextReport(futureGameState, gapAheadMinSectorWait, gapAheadMaxSectorWait);
							}
						}
					};
					audioPlayer.playMessage(new QueuedMessage("Timings/gap_in_front", 5, null, null, null, delayedMessage2));
				}
				else if (flag3 && (!flag4 || gapAheadReportFrequency <= 0) && sectorsSinceLastGapBehindReport >= sectorsUntilNextGapBehindReport)
				{
					DelayedMessage delayedMessage3 = delegate(GameStateData futureGameState, List<MessageFragment> msg, List<MessageFragment> alt_)
					{
						if (isNotRacing(futureGameState))
						{
							Log.Debug("lgcy: gap_behind invalidated because we're not racing");
						}
						else if (futureGameState.isLast())
						{
							Log.Debug("lgcy: gap_behind invalidated because we are last");
						}
						else
						{
							var (gap3, opponent) = mkGapBehindInRace(futureGameState);
							if (!currentGapBehind.opponentKey.Equals(gap3.opponentKey))
							{
								Log.Debug("lgcy: gap_behind invalidated because opponent changed");
							}
							else
							{
								MessageFragment item3 = MessageFragment.Time(TimeSpanWrapper.FromSeconds(gap3.timeDelta, Precision.AUTO_GAPS));
								List<MessageFragment> collection = ((Utilities.random.Next(0, 3) != 0) ? Opponents.MkOpponentShort(opponentBehind, preferPosition: false, requestNumber: false, preferCantPronounce: false) : Opponents.MkOpponentPosition(opponentBehind.ClassPosition));
								if (gapBehindStatus == GapStatus.CLOSE)
								{
									msg.AddRange(AbstractEvent.MessageContents(folderBeingPressured));
									msg.AddRange(mkDefendAdvice(opponent, futureGameState));
									msg.AddRange(mkReputationAdvice(opponent, opponentIsAhead: false));
								}
								else if (gapBehindStatus == GapStatus.INCREASING && gap3.timeDelta > minGapToReport)
								{
									msg.Add(MessageFragment.Text(folderTheGapTo));
									msg.AddRange(collection);
									msg.Add(MessageFragment.Text(folderBehindIsIncreasing));
									msg.Add(item3);
								}
								else if (gapBehindStatus == GapStatus.DECREASING && gap3.timeDelta > minGapToReport)
								{
									msg.AddRange(collection);
									msg.Add(MessageFragment.Text(folderIsReelingYouIn));
									msg.Add(item3);
									msg.AddRange(mkDefendAdvice(opponent, futureGameState));
									if (gap3.timeDelta < 2f)
									{
										msg.AddRange(mkReputationAdvice(opponent, opponentIsAhead: false));
									}
								}
								else if (gapBehindStatus == GapStatus.OTHER && gap3.timeDelta > minGapToReport)
								{
									if (Utilities.random.Next(0, 3) == 0)
									{
										msg.AddRange(AbstractEvent.MessageContents(folderGapBehindIsNow));
									}
									else
									{
										msg.Add(MessageFragment.Text(folderTheGapTo));
										msg.AddRange(collection);
										msg.Add(MessageFragment.Text(folderBehindIsNow));
									}
									msg.Add(item3);
								}
								else
								{
									Console.WriteLine("lgcy: Invalid gapBehindStatus(" + gapBehindStatus.ToString() + ") with gap " + gap3.timeDelta);
								}
								gapBehindAtLastReport = gap3.timeDelta;
								sectorsSinceLastGapBehindReport = 0;
								sectorsUntilNextGapBehindReport = nextReport(futureGameState, gapBehindMinSectorWait, gapBehindMaxSectorWait);
							}
						}
					};
					audioPlayer.playMessage(new QueuedMessage("Timings/gap_behind", 5, null, null, null, delayedMessage3));
				}
			}
			if (!CrewChief.readOpponentDeltasForEveryLap || !currentGameState.SessionData.IsNewLap)
			{
				return;
			}
			List<MessageFragment> list = new List<MessageFragment>();
			if (currentGameState.SessionData.ClassPosition != 1)
			{
				Gap item = mkGapFrontInRace(currentGameState).Item1;
				if (item.timeDelta > minGapToReport)
				{
					gapInFrontAtLastReport = item.timeDelta;
					list.AddRange(AbstractEvent.MessageContents(folderGapInFrontIsNow));
					list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(item.timeDelta, Precision.AUTO_GAPS)));
				}
			}
			if (!currentGameState.isLast())
			{
				Gap item2 = mkGapBehindInRace(currentGameState).Item1;
				if (item2.timeDelta > minGapToReport)
				{
					gapBehindAtLastReport = item2.timeDelta;
					list.AddRange(AbstractEvent.MessageContents(folderGapBehindIsNow));
					list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(item2.timeDelta, Precision.AUTO_GAPS)));
				}
			}
			(Gap, OpponentData)? tuple3 = mkGapBehindOnTrack(currentGameState, onlyIncludeCarsLappingThePlayer: true);
			if (tuple3.HasValue && tuple3?.Item1.timeDelta > minGapToReport)
			{
				list.Add(MessageFragment.Text(folderTheGapTo));
				list.AddRange(Opponents.MkOpponentPosition(tuple3.Value.Item2.ClassPosition));
				list.Add(MessageFragment.Text(folderBehindIsNow));
				list.Add(MessageFragment.Time(TimeSpanWrapper.FromSeconds(tuple3.Value.Item1.timeDelta, Precision.AUTO_GAPS)));
			}
			QueuedMessage queuedMessage = new QueuedMessage("Timings/gaps_for_laps", 5, list, null, null, null, 0, null, null, 10);
			queuedMessage.playEvenWhenSilenced = true;
			audioPlayer.playMessage(queuedMessage);
		}

		private List<MessageFragment> mkAttackAdvice(OpponentData opponent, GameStateData st)
		{
			List<MessageFragment> list = new List<MessageFragment>();
			DateTime value = DateTime.MinValue;
			if (!trackLandmarkAttackDriverNamesUsed.TryGetValue(opponent.DriverRawName, out value) || value + minTimeBetweenAttackOrDefendByDriver < st.Now)
			{
				TrackLandmarksTiming.LandmarkAndDeltaType landmarkWhereIAmFaster = st.SessionData.trackLandmarksTiming.getLandmarkWhereIAmFaster(opponent.trackLandmarksTiming, preferCommonOvertakingSpots: true, forVoiceCommand: false);
				if (landmarkWhereIAmFaster.landmarkName != null)
				{
					string text = "corners/" + landmarkWhereIAmFaster.landmarkName;
					if (!SoundCache.hasSingleSound(text))
					{
						Console.WriteLine("lgcy: Skipping overtaking advice; no sound for landmark: " + text);
					}
					string o = ((landmarkWhereIAmFaster.deltaType == TrackLandmarksTiming.DeltaType.Time) ? folderHeIsSlowerThroughCorner : folderHeIsSlowerEnteringCorner);
					list.AddRange(AbstractEvent.MessageContents(AbstractEvent.Pause(500), o, text));
					trackLandmarkAttackDriverNamesUsed[opponent.DriverRawName] = st.Now;
				}
			}
			return list;
		}

		private List<MessageFragment> mkDefendAdvice(OpponentData opponent, GameStateData st)
		{
			List<MessageFragment> list = new List<MessageFragment>();
			DateTime value = DateTime.MinValue;
			if (!trackLandmarkDefendDriverNamesUsed.TryGetValue(opponent.DriverRawName, out value) || value + minTimeBetweenAttackOrDefendByDriver < st.Now)
			{
				TrackLandmarksTiming.LandmarkAndDeltaType landmarkWhereIAmSlower = st.SessionData.trackLandmarksTiming.getLandmarkWhereIAmSlower(opponent.trackLandmarksTiming, preferCommonOvertakingSpots: true, forVoiceCommand: false);
				if (landmarkWhereIAmSlower.landmarkName != null)
				{
					string text = "corners/" + landmarkWhereIAmSlower.landmarkName;
					if (!SoundCache.hasSingleSound(text))
					{
						Console.WriteLine("lgcy: Skipping defence advice; no sound for landmark: " + text);
					}
					string o = ((landmarkWhereIAmSlower.deltaType == TrackLandmarksTiming.DeltaType.Time) ? folderHeIsFasterThroughCorner : folderHeIsFasterEnteringCorner);
					list.AddRange(AbstractEvent.MessageContents(AbstractEvent.Pause(500), o, text));
					trackLandmarkDefendDriverNamesUsed[opponent.DriverRawName] = st.Now;
				}
			}
			return list;
		}

		private List<MessageFragment> mkReputationAdvice(OpponentData opponent, bool opponentIsAhead)
		{
			if (driverReputationWarningChecksInThisSession.Contains(opponent.DriverRawName))
			{
				return new List<MessageFragment>();
			}
			return MkFreshReputationAdvice(opponent, opponentIsAhead);
		}

		private GapStatus getGapStatus(List<Gap> gaps, float lastReportedGap)
		{
			if (gaps.Count < 3 || gaps[0].timeDelta <= 0f || gaps[1].timeDelta <= 0f || gaps[2].timeDelta <= 0f || gaps[0].timeDelta > 20f || Math.Abs(gaps[0].timeDelta - gaps[1].timeDelta) > 5f)
			{
				return GapStatus.NONE;
			}
			if (!isSameCar(gaps, 3))
			{
				return GapStatus.NONE;
			}
			if (((double)gaps[0].timeDelta < 0.5 && (double)gaps[1].timeDelta < 0.5) || (gaps.Count > 2 && (double)gaps[0].timeDelta < 0.7 && (double)gaps[1].timeDelta < 0.7 && (double)gaps[2].timeDelta < 0.7) || (gaps.Count > 3 && (double)gaps[0].timeDelta < 0.8 && (double)gaps[1].timeDelta < 0.8 && (double)gaps[2].timeDelta < 0.8 && (double)gaps[3].timeDelta < 0.8))
			{
				return GapStatus.CLOSE;
			}
			if ((lastReportedGap == -1f || Math.Round(gaps[0].timeDelta, 1) > Math.Round(lastReportedGap)) && Math.Round(gaps[0].timeDelta, 1) > Math.Round(gaps[1].timeDelta, 1) && Math.Round(gaps[1].timeDelta, 1) > Math.Round(gaps[2].timeDelta, 1))
			{
				return GapStatus.INCREASING;
			}
			if ((lastReportedGap == -1f || Math.Round(gaps[0].timeDelta, 1) < Math.Round(lastReportedGap)) && Math.Round(gaps[0].timeDelta, 1) < Math.Round(gaps[1].timeDelta, 1) && Math.Round(gaps[1].timeDelta, 1) < Math.Round(gaps[2].timeDelta, 1))
			{
				return GapStatus.DECREASING;
			}
			if (Math.Abs(gaps[0].timeDelta - gaps[1].timeDelta) < 1f && Math.Abs(gaps[0].timeDelta - gaps[2].timeDelta) < 1f)
			{
				return GapStatus.OTHER;
			}
			return GapStatus.NONE;
		}

		private bool isSameCar(List<Gap> gaps, int gapsToCheck)
		{
			string text = null;
			for (int i = 0; i < gapsToCheck; i++)
			{
				string opponentKey = gaps[0].opponentKey;
				if (opponentKey == null)
				{
					return false;
				}
				if (i == 0)
				{
					text = opponentKey;
				}
				else if (opponentKey != text)
				{
					return false;
				}
			}
			return true;
		}

		public static List<MessageFragment> MkOpponentRelativeDelta(OpponentData opponent, int expectedSign, bool includeLapInfo)
		{
			if (opponent != null)
			{
				var (num, num2) = CrewChief.currentGameState.SessionData.DeltaTime.GetRelativeDelta(opponent.DeltaTime);
				if (num != 0 || num2 != 0f)
				{
					return AbstractEvent.MkOpponentDelta(num, num2, expectedSign, includeLapInfo);
				}
			}
			return null;
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
			GameStateData currentGameState = CrewChief.currentGameState;
			if (currentGameState == null)
			{
				return;
			}
			bool flag = currentGameState.SessionData.ClassPosition == 1;
			bool flag2 = currentGameState.SessionData.SessionType == SessionType.Race;
			if (cmd == SpeechCommands.ID.SESSION_STATUS || cmd == SpeechCommands.ID.STATUS)
			{
				if (flag)
				{
					Gap item = mkGapBehindInRace(currentGameState).Item1;
					if (item.timeDelta > 2f)
					{
						audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_behind", 0, AbstractEvent.MessageContents(folderGapBehindIsNow, TimeSpanWrapper.FromMilliseconds(item.timeDelta * 1000f, Precision.AUTO_GAPS))));
					}
				}
				else if (!currentGameState.isLast())
				{
					Gap item2 = mkGapFrontInRace(currentGameState).Item1;
					if (item2.timeDelta > 2f)
					{
						audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_in_front", 0, AbstractEvent.MessageContents(folderGapInFrontIsNow, TimeSpanWrapper.FromMilliseconds(item2.timeDelta * 1000f, Precision.AUTO_GAPS))));
					}
				}
				return;
			}
			bool flag3 = false;
			if (cmd == SpeechCommands.ID.WHERE_AM_I_FASTER)
			{
				if (!flag)
				{
					OpponentData opponentAtClassPosition = currentGameState.getOpponentAtClassPosition(currentGameState.SessionData.ClassPosition - 1, currentGameState.carClass);
					List<MessageFragment> list = mkAttackAdvice(opponentAtClassPosition, currentGameState);
					if (list.Count() > 0)
					{
						flag3 = true;
						audioPlayer.playMessageImmediately(new QueuedMessage("Timings/corner_to_attack_in", 0, list));
					}
				}
			}
			else if (cmd == SpeechCommands.ID.WHERE_AM_I_SLOWER)
			{
				if (!currentGameState.isLast())
				{
					OpponentData opponentAtClassPosition2 = currentGameState.getOpponentAtClassPosition(currentGameState.SessionData.ClassPosition + 1, currentGameState.carClass);
					List<MessageFragment> list2 = mkDefendAdvice(opponentAtClassPosition2, currentGameState);
					if (list2.Count() > 0)
					{
						flag3 = true;
						audioPlayer.playMessageImmediately(new QueuedMessage("Timings/corner_to_defend_in", 0, list2));
					}
				}
			}
			else if (cmd == SpeechCommands.ID.WHATS_MY_GAP_IN_FRONT)
			{
				if (flag2)
				{
					if (flag)
					{
						audioPlayer.playMessageImmediately(new QueuedMessage(Position.folderLeading, 0));
						flag3 = true;
					}
					else
					{
						Gap item3 = mkGapFrontInRace(currentGameState).Item1;
						if ((double)item3.timeDelta != 0.0)
						{
							gapInFrontAtLastReport = item3.timeDelta;
							List<MessageFragment> messageFragments = AbstractEvent.MkOpponentDelta(item3.signedLapDelta, item3.signedTimeDelta, -1, includeLapInfo: true);
							audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_to_opponent", 0, messageFragments));
							flag3 = true;
						}
					}
				}
			}
			else if (cmd == SpeechCommands.ID.WHATS_MY_GAP_BEHIND)
			{
				if (flag2)
				{
					if (currentGameState.isLastInStandings())
					{
						audioPlayer.playMessageImmediately(new QueuedMessage(Position.folderLast, 0));
						flag3 = true;
					}
					else
					{
						Gap item4 = mkGapBehindInRace(currentGameState).Item1;
						if ((double)item4.timeDelta != 0.0)
						{
							gapBehindAtLastReport = item4.timeDelta;
							List<MessageFragment> messageFragments2 = AbstractEvent.MkOpponentDelta(item4.signedLapDelta, item4.signedTimeDelta, 1, includeLapInfo: true);
							audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_to_opponent", 0, messageFragments2));
							flag3 = true;
						}
					}
				}
			}
			else if (cmd == SpeechCommands.ID.WHATS_MY_GAP_IN_FRONT_ON_TRACK)
			{
				string opponentKeyInFrontOnTrack = currentGameState.getOpponentKeyInFrontOnTrack();
				if (opponentKeyInFrontOnTrack != null && currentGameState.OpponentData.TryGetValue(opponentKeyInFrontOnTrack, out var value))
				{
					var (lapDifference, num) = currentGameState.SessionData.DeltaTime.GetRelativeDelta(value.DeltaTime);
					if ((double)num < 0.0)
					{
						List<MessageFragment> messageFragments3 = AbstractEvent.MkOpponentDelta(lapDifference, num, -1, includeLapInfo: true);
						audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_to_opponent", 0, messageFragments3));
						flag3 = true;
					}
				}
			}
			else if (cmd == SpeechCommands.ID.WHATS_MY_GAP_BEHIND_ON_TRACK)
			{
				string opponentKeyBehindOnTrack = currentGameState.getOpponentKeyBehindOnTrack();
				if (opponentKeyBehindOnTrack != null && currentGameState.OpponentData.TryGetValue(opponentKeyBehindOnTrack, out var value2))
				{
					var (lapDifference2, num2) = currentGameState.SessionData.DeltaTime.GetRelativeDelta(value2.DeltaTime);
					if ((double)num2 > 0.0)
					{
						if (!opponentKeyBehindOnTrack.Equals(currentGameState.getOpponentKeyBehind(currentGameState.carClass)) && CarData.IsCarClassEqual(value2.CarClass, currentGameState.carClass))
						{
							gapBehindOnTrackAtLastReport = num2;
						}
						List<MessageFragment> messageFragments4 = AbstractEvent.MkOpponentDelta(lapDifference2, num2, 1, includeLapInfo: true);
						audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_to_opponent", 0, messageFragments4));
						flag3 = true;
					}
				}
			}
			else if (cmd == SpeechCommands.ID.WHATS_THE_LEADER_LAP && currentGameState.SessionData.SessionType == SessionType.Race)
			{
				List<MessageFragment> list3 = new List<MessageFragment>();
				if (flag)
				{
					int lapCount = currentGameState.SessionData.LapCount;
					list3.AddRange(AbstractEvent.MessageContents(Position.folderLeading, AbstractEvent.Pause(200), lapCount, Battery.folderLaps));
				}
				else
				{
					OpponentData opponentAtClassPosition3 = currentGameState.getOpponentAtClassPosition(1, currentGameState.carClass);
					if (opponentAtClassPosition3 != null)
					{
						int num3 = opponentAtClassPosition3.CompletedLaps + 1;
						list3.AddRange(AbstractEvent.MessageContents(num3, Battery.folderLaps));
						var (num6, _) = currentGameState.SessionData.DeltaTime.GetSignedDeltaTimeWithLapDifference(opponentAtClassPosition3.DeltaTime);
						if (num6 != 0)
						{
							list3.Add(MessageFragment.Text(AbstractEvent.Pause(500)));
							list3.AddRange(AbstractEvent.MkLapDifferenceMessage(num6));
						}
					}
				}
				if (list3.Count > 0)
				{
					flag3 = true;
					audioPlayer.playMessageImmediately(new QueuedMessage("timings_leader_lap", 0, list3));
				}
			}
			else if (cmd == SpeechCommands.ID.WHATS_MY_GAP_TO_LEADER)
			{
				if (flag)
				{
					audioPlayer.playMessageImmediately(new QueuedMessage(Position.folderLeading, 0));
					flag3 = true;
				}
				else
				{
					OpponentData opponentAtClassPosition4 = currentGameState.getOpponentAtClassPosition(1, currentGameState.carClass);
					if (opponentAtClassPosition4 != null)
					{
						var (lapDifference3, num7) = currentGameState.SessionData.DeltaTime.GetRelativeDelta(opponentAtClassPosition4.DeltaTime);
						if ((double)num7 != 0.0)
						{
							List<MessageFragment> messageFragments5 = AbstractEvent.MkOpponentDelta(lapDifference3, num7, 0, includeLapInfo: true);
							audioPlayer.playMessageImmediately(new QueuedMessage("Timings/gap_to_opponent", 0, messageFragments5));
							flag3 = true;
						}
					}
				}
			}
			else if (cmd == SpeechCommands.ID.NOTE_BAD_DRIVER_AHEAD_ON_TRACK && Game.IRACING)
			{
				string opponentKeyInFrontOnTrack2 = currentGameState.getOpponentKeyInFrontOnTrack();
				if (opponentKeyInFrontOnTrack2 != null && currentGameState.OpponentData.TryGetValue(opponentKeyInFrontOnTrack2, out var value3))
				{
					flag3 = putPersistedBadDriver(value3);
					if (flag3)
					{
						audioPlayer.playMessageImmediately(new QueuedMessage("Timings/bad_driver_ahead", 0, AbstractEvent.MessageContents("acknowledge/OK")));
					}
				}
			}
			else if (cmd == SpeechCommands.ID.NOTE_BAD_DRIVER_BEHIND_ON_TRACK && Game.IRACING)
			{
				string opponentKeyBehindOnTrack2 = currentGameState.getOpponentKeyBehindOnTrack();
				if (opponentKeyBehindOnTrack2 != null && currentGameState.OpponentData.TryGetValue(opponentKeyBehindOnTrack2, out var value4))
				{
					flag3 = putPersistedBadDriver(value4);
					if (flag3)
					{
						audioPlayer.playMessageImmediately(new QueuedMessage("Timings/bad_driver_behind", 0, AbstractEvent.MessageContents("acknowledge/OK")));
					}
				}
			}
			if (!flag3)
			{
				audioPlayer.playMessageImmediately(new QueuedMessage("acknowledge/no_data", 0));
			}
		}

		public static bool IsNewSectorOrGapPoint(GameStateData previousGameState, GameStateData currentGameState)
		{
			if (currentGameState.SessionData.TrackDefinition.gapPoints.Count() > 0)
			{
				if (currentGameState.PositionAndMotionData.DistanceRoundTrack > 0f && currentGameState.PositionAndMotionData.DistanceRoundTrack > previousGameState.PositionAndMotionData.DistanceRoundTrack)
				{
					float[] gapPoints = currentGameState.SessionData.TrackDefinition.gapPoints;
					foreach (float num in gapPoints)
					{
						if (currentGameState.PositionAndMotionData.DistanceRoundTrack >= num && previousGameState.PositionAndMotionData.DistanceRoundTrack < num)
						{
							return true;
						}
					}
				}
				return false;
			}
			return currentGameState.SessionData.IsNewSector;
		}
	}
}
