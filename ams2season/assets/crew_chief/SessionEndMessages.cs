using System;
using CrewChiefV4.Audio;
using CrewChiefV4.GameState;

namespace CrewChiefV4.Events
{
	internal class SessionEndMessages
	{
		public const string sessionEndMessageIdentifier = "SESSION_END";

		public static string overrideDetailedDisqualifiedMessage = null;

		public static string folderPodiumFinish = "lap_counter/podium_finish";

		private const string folderWonRace = "lap_counter/won_race";

		private const string folderFinishedRace = "lap_counter/finished_race";

		private const string folderGoodFinish = "lap_counter/finished_race_good_finish";

		private const string folderFinishedRaceLast = "lap_counter/finished_race_last";

		public const string folderEndOfSession = "lap_counter/end_of_session";

		private const string folderEndOfSessionPole = "lap_counter/end_of_session_pole";

		public readonly bool enableSessionEndMessages = UserSettings.GetUserSettings().getBoolean("enable_session_end_messages");

		private AudioPlayer audioPlayer;

		private const int minSessionRunTimeForEndMessages = 60;

		private DateTime lastSessionEndMessagesPlayedAt = DateTime.MinValue;

		public SessionEndMessages(AudioPlayer audioPlayer)
		{
			this.audioPlayer = audioPlayer;
		}

		public void trigger(float sessionRunningTime, SessionType sessionType, SessionPhase lastSessionPhase, int startPosition, int finishPosition, int numCars, int completedLaps, Tuple<int, int> expectedFinishPosition, bool isDisqualified, bool isDNF, DateTime now)
		{
			if (!enableSessionEndMessages)
			{
				Console.WriteLine("Session end, position = " + finishPosition + ", session end messages are disabled");
				return;
			}
			if (lastSessionEndMessagesPlayedAt.AddSeconds(10.0) > now)
			{
				Console.WriteLine("Skipping duplicate session end message call - last call was " + (now - lastSessionEndMessagesPlayedAt).TotalSeconds.ToString("0.00") + " seconds ago");
				return;
			}
			switch (sessionType)
			{
			case SessionType.Race:
				if (sessionRunningTime >= 60f || completedLaps > 0)
				{
					if (lastSessionPhase == SessionPhase.Finished)
					{
						lastSessionEndMessagesPlayedAt = now;
						playFinishMessage(sessionType, startPosition, finishPosition, numCars, isDisqualified, isDNF, completedLaps, expectedFinishPosition);
					}
					else
					{
						Console.WriteLine("Skipping race session end message because the previous phase wasn't Finished");
					}
				}
				else
				{
					Console.WriteLine("Skipping race session end message because it didn't run for a lap or " + 60 + " seconds");
				}
				break;
			case SessionType.Practice:
			case SessionType.Qualify:
			case SessionType.PrivateQualify:
				if (sessionRunningTime >= 60f)
				{
					if (lastSessionPhase == SessionPhase.Green || lastSessionPhase == SessionPhase.FullCourseYellow || lastSessionPhase == SessionPhase.Finished || lastSessionPhase == SessionPhase.Checkered)
					{
						lastSessionEndMessagesPlayedAt = now;
						playFinishMessage(sessionType, startPosition, finishPosition, numCars, isDisqualified, isDNF, completedLaps, expectedFinishPosition);
					}
					else
					{
						Console.WriteLine("Skipping non-race session end message because the previous phase wasn't green, finished, or checkered");
					}
				}
				else
				{
					Console.WriteLine("Skipping non-race session end message because the session didn't run for " + 60 + " seconds");
				}
				break;
			}
		}

		private void playFinishMessage(SessionType sessionType, int startPosition, int position, int numCars, bool isDisqualified, bool isDNF, int completedLaps, Tuple<int, int> expectedFinishingPosition)
		{
			audioPlayer.suspendPearlsOfWisdom();
			switch (GlobalBehaviourSettings.racingType)
			{
			case CrewChief.RacingType.Circuit:
				if (position < 1)
				{
					Console.WriteLine("Session finished but position is < 1");
				}
				else if (isDisqualified)
				{
					bool flag = false;
					if (completedLaps > 1)
					{
						flag = audioPlayer.playRant("SESSION_END", AbstractEvent.MessageContents(Penalties.folderDisqualified));
					}
					if (!flag)
					{
						string o = ((overrideDetailedDisqualifiedMessage == null) ? Penalties.folderDisqualified : overrideDetailedDisqualifiedMessage);
						overrideDetailedDisqualifiedMessage = null;
						audioPlayer.playMessage(new QueuedMessage("SESSION_END", 0, AbstractEvent.MessageContents(o), null, null, null, 0, null, null, 10));
					}
				}
				else if (sessionType == SessionType.Race)
				{
					bool flag2 = position == numCars;
					if (isDNF)
					{
						audioPlayer.playMessage(new QueuedMessage("SESSION_END", 0, AbstractEvent.MessageContents("lap_counter/finished_race_last"), null, null, null, 0, null, null, 10));
					}
					else if (position == 1)
					{
						audioPlayer.playMessage(new QueuedMessage("SESSION_END", 0, AbstractEvent.MessageContents("lap_counter/won_race"), null, null, null, 0, null, null, 10));
					}
					else if (position < 4)
					{
						audioPlayer.playMessage(new QueuedMessage("SESSION_END", 0, AbstractEvent.MessageContents(folderPodiumFinish), null, null, null, 0, null, null, 10));
					}
					else if (position >= 4 && !flag2)
					{
						if (GlobalBehaviourSettings.maxComplaintsPerSession <= 0 || (expectedFinishingPosition.Item1 != -1 && expectedFinishingPosition.Item1 >= position) || (startPosition > position && ((startPosition <= 6 && position <= 5) || (startPosition <= 10 && position <= 6) || startPosition - position >= 4)))
						{
							audioPlayer.playMessage(new QueuedMessage("SESSION_END", 0, AbstractEvent.MessageContents(Position.folderStub + position, "lap_counter/finished_race_good_finish"), null, null, null, 0, null, null, 10));
							break;
						}
						bool flag3 = false;
						int num = position - startPosition;
						bool flag4 = expectedFinishingPosition.Item1 != -1 && expectedFinishingPosition.Item1 + 5 < position;
						if (numCars > 2 && completedLaps > 1 && (flag4 || (num > 8 && (float)num / (float)numCars >= 0.5f)))
						{
							flag3 = audioPlayer.playRant("SESSION_END", AbstractEvent.MessageContents(Position.folderStub + position));
						}
						if (!flag3)
						{
							audioPlayer.playMessage(new QueuedMessage("SESSION_END", 0, AbstractEvent.MessageContents(Position.folderStub + position, "lap_counter/finished_race"), null, null, null, 0, null, null, 10));
						}
					}
					else
					{
						if (!flag2)
						{
							break;
						}
						if (GlobalBehaviourSettings.maxComplaintsPerSession <= 0)
						{
							audioPlayer.playMessage(new QueuedMessage("SESSION_END", 0, AbstractEvent.MessageContents(Position.folderStub + position, "lap_counter/finished_race"), null, null, null, 0, null, null, 10));
							break;
						}
						bool flag5 = false;
						if (numCars > 5 && completedLaps > 1)
						{
							flag5 = audioPlayer.playRant("SESSION_END", AbstractEvent.MessageContents(Position.folderStub + position));
						}
						if (!flag5)
						{
							audioPlayer.playMessage(new QueuedMessage("SESSION_END", 0, AbstractEvent.MessageContents("lap_counter/finished_race_last"), null, null, null, 0, null, null, 10));
						}
					}
				}
				else
				{
					if ((sessionType == SessionType.Qualify || sessionType == SessionType.PrivateQualify) && position == 1)
					{
						audioPlayer.playMessage(new QueuedMessage("lap_counter/end_of_session_pole", 0));
					}
					else
					{
						audioPlayer.playMessage(new QueuedMessage("SESSION_END", 0, AbstractEvent.MessageContents("lap_counter/end_of_session", Position.folderStub + position), null, null, null, 0, null, null, 10));
					}
					if (!Game.IRACING && (sessionType == SessionType.Qualify || sessionType == SessionType.PrivateQualify) && CrewChief.currentGameState != null)
					{
						Position.reportExpectedFinishPosition(audioPlayer, CrewChief.currentGameState.SessionData.expectedFinishingPosition, fromVoiceCommand: false, raceUnderway: false, CrewChief.currentGameState.SessionData.ClassPosition);
					}
				}
				break;
			case CrewChief.RacingType.Rally:
				if (!isDNF)
				{
					((CoDriver)CrewChief.getEvent("CoDriver")).PlayFinishMessage();
				}
				break;
			}
		}
	}
}
