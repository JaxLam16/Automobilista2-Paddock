using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using CrewChiefV4.Events;
using CrewChiefV4.GameState;
using CrewChiefV4.Audio;
using CrewChiefV4.NumberProcessing;

namespace CrewChiefV4.Events
{
    class RaceTime : AbstractEvent
    {
        private String folder5mins = "race_time/five_minutes_left";
        private String folder5minsLeading = "race_time/five_minutes_left_leading";
        private String folder5minsPodium = "race_time/five_minutes_left_podium";
        private String folder2mins = "race_time/two_minutes_left";
        private String folder0mins = "race_time/zero_minutes_left";

        private String folder10mins = "race_time/ten_minutes_left";
        private String folder15mins = "race_time/fifteen_minutes_left";
        private String folder20mins = "race_time/twenty_minutes_left";
        public static String folderHalfWayHome = "race_time/half_way";
        private String folderLastLap = "race_time/last_lap";
        private String folderLastLapLeading = "race_time/last_lap_leading";
        private String folderLastLapPodium = "race_time/last_lap_top_three";

        public static String folderRemaining = "race_time/remaining";
        private String folderLapsLeft = "race_time/laps_remaining";

        private String folderLessThanOneMinute = "race_time/less_than_one_minute";

        private String folderThisIsTheLastLap = "race_time/this_is_the_last_lap";

        private String folderOneMinuteRemaining = "race_time/one_minute_remaining";

        private String folderOneLapAfterThisOne = "race_time/one_more_lap_after_this_one";

        private Boolean played0mins, played2mins, played5mins, played10mins, played15mins, played20mins, playedHalfWayHome, playedLastLap;

        private float halfTime;

        private Boolean gotHalfTime;

        private int lapsLeft;
        private float timeLeft;

        private int extraLapsAfterTimedSessionComplete;

        private int extraLapsRemaining = 0;

        private Boolean leaderHasFinishedRace;

        private bool leaderOnSameLap;

        private Boolean sessionLengthIsTime;

        // allow condition messages during caution periods
        public override List<SessionPhase> applicableSessionPhases
        {
            get { return new List<SessionPhase> { SessionPhase.Green, SessionPhase.Checkered, SessionPhase.FullCourseYellow, SessionPhase.Formation }; }
        }

        public RaceTime(AudioPlayer audioPlayer)
        {
            this.audioPlayer = audioPlayer;
        }

        public override void clearState()
        {
            played0mins = false; played2mins = false; played5mins = false; played10mins = false; played15mins = false;
            played20mins = false; playedHalfWayHome = false; playedLastLap = false;
            halfTime = 0;
            gotHalfTime = false;
            lapsLeft = -1;
            timeLeft = 0;
            sessionLengthIsTime = false;
            leaderHasFinishedRace = false;
            extraLapsAfterTimedSessionComplete = 0;
            extraLapsRemaining = 0;
        }
        
        override protected void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            // For now, scope Formation phase to GTR2 only.
            if (!Game.GTR2
                && currentGameState.SessionData.SessionPhase == SessionPhase.Formation)
                return;
            if (previousGameState != null &&
                currentGameState.SessionData.SessionPhase == SessionPhase.Green &&
                (currentGameState.SessionData.SessionType != previousGameState.SessionData.SessionType ||
                 currentGameState.SessionData.SessionPhase != previousGameState.SessionData.SessionPhase))
            {
                Log.Commentary("Starting new session/phase");
            }


            if (Game.IRACING
                && currentGameState.SessionData.SessionType == SessionType.Race
                && previousGameState != null
                && currentGameState.SessionData.SessionHasFixedTime
                && previousGameState.SessionData.SessionTimeRemaining == -1
                && currentGameState.SessionData.SessionTimeRemaining > 0
                // when the white flags drops in iRacing, the session timer may be reset (e.g. to extend the session
                // to allow slower classes to finish) but don't re-call the countdown: this is the last lap.
                // It can also be reset when it reaches 0
                && !CrewChief.currentGameState.SessionData.IsLastLap
                && currentGameState.SessionData.SessionPhase != SessionPhase.Checkered)
            {
                Log.Commentary("Clear out iRacing minute warning flags");
                played0mins = false; played2mins = false; played5mins = false; played10mins = false; played15mins = false;
                played20mins = false; playedHalfWayHome = false; playedLastLap = false; gotHalfTime = false;
            }
            // store this in a local var so it's available for voice command responses
            extraLapsAfterTimedSessionComplete = currentGameState.SessionData.ExtraLapsAfterTimedSessionComplete;
            leaderHasFinishedRace = currentGameState.SessionData.LeaderHasFinishedRace;
            timeLeft = currentGameState.SessionData.SessionTimeRemaining;
            if (!currentGameState.SessionData.SessionHasFixedTime)
            {
                lapsLeft = currentGameState.SessionData.SessionLapsRemaining;
                sessionLengthIsTime = false;
            }
            else
            {
                sessionLengthIsTime = true;
            }
            if (sessionLengthIsTime)
            {
                if (timeLeft > 0)
                {
                    extraLapsRemaining = extraLapsAfterTimedSessionComplete;
                }
                if (extraLapsAfterTimedSessionComplete > 0 && gotHalfTime && timeLeft <= 0 && currentGameState.SessionData.IsNewLap)
                {
                    extraLapsRemaining--;
                }
                if (!gotHalfTime
                    && (!Game.GTR2 || currentGameState.inCar))  // No timed session length in GTR2 until we are in the realtime.
                {
                    Console.WriteLine("Session time remaining = " + timeLeft + "  (" + TimeSpan.FromSeconds(timeLeft).ToString(@"hh\:mm\:ss\:fff") + ")");
                    halfTime = timeLeft / 2;
                    gotHalfTime = true;
                    if (currentGameState.FuelData.FuelUseActive)
                    {
                        // don't allow the half way message to play if fuel use is active - there's already one in there
                        playedHalfWayHome = true;
                    }
                }
                PearlsOfWisdom.PearlType pearlType = PearlsOfWisdom.PearlType.NONE;
                if (currentGameState.SessionData.SessionType == SessionType.Race 
                    && currentGameState.SessionData.CompletedLaps >= LapTimes.lapsBeforeAnnouncingGaps[currentGameState.SessionData.TrackDefinition.trackLengthClass])
                {
                    pearlType = PearlsOfWisdom.PearlType.NEUTRAL;
                    if (currentGameState.SessionData.ClassPosition < 4)
                    {
                        pearlType = PearlsOfWisdom.PearlType.GOOD;
                    }
                    else if (currentGameState.SessionData.ClassPosition > currentGameState.SessionData.SessionStartClassPosition + 5 &&
                        !currentGameState.PitData.OnOutLap && !currentGameState.PitData.InPitlane &&
                        currentGameState.SessionData.LapTimePrevious > currentGameState.TimingData.getPlayerBestLapTime() &&
                        // yuk... AC SessionStartPosition is suspect so don't allow "you're shit" messages based on it.
                        !Game.ASSETTO1)
                    {
                        // don't play bad-pearl if we're on an out lap or are pitting
                        pearlType = PearlsOfWisdom.PearlType.BAD;
                    }
                }

                if (currentGameState.SessionData.SessionType == SessionType.Race && currentGameState.SessionData.IsNewLap &&
                    currentGameState.SessionData.SessionRunningTime > 60 && !playedLastLap)
                {
                    Boolean timeWillBeZeroAtEndOfLeadersLap = false;
                    if (currentGameState.SessionData.OverallPosition == 1)
                    {
                        float playerBest = currentGameState.TimingData.getPlayerBestLapTime();
                        timeWillBeZeroAtEndOfLeadersLap = timeLeft > 0 && playerBest > 0 &&
                            timeLeft < playerBest - 5;
                    }
                    else
                    {
                        OpponentData leader = currentGameState.getOpponentAtClassPosition(1, currentGameState.carClass);
                        timeWillBeZeroAtEndOfLeadersLap = leader != null && leader.isProbablyLastLap;
                    }
                    if ((extraLapsAfterTimedSessionComplete > 0 && extraLapsRemaining == 0 && timeLeft <= 0) ||
                        (extraLapsAfterTimedSessionComplete == 0 && timeWillBeZeroAtEndOfLeadersLap)) {
                        playedLastLap = true;
                        played2mins = true;
                        played5mins = true;
                        played10mins = true;
                        played15mins = true;
                        played20mins = true;
                        playedHalfWayHome = true;
                        // rF2 and iR implement SessionData.IsLastLap so last lap logic is handled in LapCounter.
                        if (!Game.RF2_LMU && !Game.IRACING)
                        {
                            if (currentGameState.SessionData.ClassPosition == 1)
                            {
                                // don't add a pearl here - the audio clip already contains encouragement
                                audioPlayer.playMessage(new QueuedMessage(folderLastLapLeading, 10, abstractEvent: this, priority: 5), pearlType, 0);
                            }
                            else if (currentGameState.SessionData.ClassPosition < 4)
                            {
                                // don't add a pearl here - the audio clip already contains encouragement
                                audioPlayer.playMessage(new QueuedMessage(folderLastLapPodium, 10, abstractEvent: this, priority: 5), pearlType, 0);
                            }
                            else
                            {
                                audioPlayer.playMessage(new QueuedMessage(folderLastLap, 10, abstractEvent: this, priority: 5));
                            }
                        }
                    }
                }
                if (currentGameState.SessionData.SessionRunningTime > 60 && timeLeft / 60 < 3 && timeLeft / 60 > 2.9)
                {
                    // disable pearls for the last part of the race
                    audioPlayer.disablePearlsOfWisdom = true;
                }
                // Console.WriteLine("Session time left = " + timeLeft + " SessionRunningTime = " + currentGameState.SessionData.SessionRunningTime);
                if (currentGameState.SessionData.ExtraLapsAfterTimedSessionComplete == 0 && 
                    currentGameState.SessionData.SessionRunningTime > 0 && !played0mins && timeLeft <= 0.2)
                {
                    played0mins = true;
                    played2mins = true;
                    played5mins = true;
                    played10mins = true;
                    played15mins = true;
                    played20mins = true;
                    playedHalfWayHome = true;
                    audioPlayer.suspendPearlsOfWisdom();
                    // PCars hack - don't play this if it's an unlimited session - no lap limit and no time limit
                    if (!currentGameState.SessionData.SessionHasFixedTime && currentGameState.SessionData.SessionNumberOfLaps <= 0)
                    {
                        Console.WriteLine("Skipping session end messages for unlimited session");
                    }
                    else if (currentGameState.SessionData.SessionType != SessionType.Race
                        && !(!Game.RACE_ROOM &&
                             (currentGameState.SessionData.SessionType == SessionType.Qualify
                             || currentGameState.SessionData.SessionType == SessionType.PrivateQualify)))
                    {
                        // don't play the chequered flag message in race sessions or in R3E qual sessions (where the session end trigger takes care if things)
                        audioPlayer.playMessage(new QueuedMessage("session_complete", 5,
                            messageFragments: MessageContents(folder0mins, Position.folderStub + currentGameState.SessionData.ClassPosition), abstractEvent: this, priority: 10));
                    }
                } 
                if (currentGameState.SessionData.SessionRunningTime > 60 && !played2mins && timeLeft / 60 < 2 && timeLeft / 60 > 1.9)
                {
                    played2mins = true;
                    played5mins = true;
                    played10mins = true;
                    played15mins = true;
                    played20mins = true;
                    playedHalfWayHome = true;
                    audioPlayer.suspendPearlsOfWisdom();
                    audioPlayer.playMessage(new QueuedMessage(folder2mins, 15, abstractEvent: this, priority: 10));
                }
                if (currentGameState.SessionData.SessionRunningTime > 120 && !played5mins && timeLeft / 60 < 5 && timeLeft / 60 > 4.9)
                {
                    played5mins = true;
                    played10mins = true;
                    played15mins = true;
                    played20mins = true;
                    playedHalfWayHome = true;
                    if (currentGameState.SessionData.SessionType == SessionType.Race && currentGameState.SessionData.ClassPosition == 1)
                    {
                        // don't add a pearl here - the audio clip already contains encouragement
                        audioPlayer.playMessage(new QueuedMessage(folder5minsLeading, 20, abstractEvent: this, priority: 5), pearlType, 0);
                    }
                    else if (currentGameState.SessionData.SessionType == SessionType.Race && currentGameState.SessionData.ClassPosition < 4)
                    {
                        // don't add a pearl here - the audio clip already contains encouragement
                        audioPlayer.playMessage(new QueuedMessage(folder5minsPodium, 20, abstractEvent: this, priority: 5), pearlType, 0);
                    }
                    else
                    {
                        audioPlayer.playMessage(new QueuedMessage(folder5mins, 20, abstractEvent: this, priority: 5), pearlType, 0.7);
                    }
                }
                if (currentGameState.SessionData.SessionRunningTime > 120 && !played10mins && timeLeft / 60 < 10 && timeLeft / 60 > 9.9)
                {
                    played10mins = true;
                    played15mins = true;
                    played20mins = true;
                    if (currentGameState.SessionData.CompletedLaps > 0)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folder10mins, 20, abstractEvent: this, priority: 3), pearlType, 0.7);
                    }
                }
                if (currentGameState.SessionData.SessionRunningTime > 120 && !played15mins && timeLeft / 60 < 15 && timeLeft / 60 > 14.9)
                {
                    played15mins = true;
                    played20mins = true;
                    if (currentGameState.SessionData.CompletedLaps > 0)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folder15mins, 20, abstractEvent: this, priority: 3), pearlType, 0.7);
                    }
                }
                if (currentGameState.SessionData.SessionRunningTime > 120 && !played20mins && timeLeft / 60 < 20 && timeLeft / 60 > 19.9)
                {
                    played20mins = true;
                    if (currentGameState.SessionData.CompletedLaps > 0)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folder20mins, 20, abstractEvent: this, priority: 3), pearlType, 0.7);
                    }
                }
                else if (currentGameState.SessionData.SessionType == SessionType.Race &&
                    currentGameState.SessionData.SessionRunningTime > 120 && !playedHalfWayHome && timeLeft > 0 && timeLeft < halfTime)
                {
                    // this one sounds weird in practice and qual sessions, so skip it
                    playedHalfWayHome = true;
                    audioPlayer.playMessage(new QueuedMessage(folderHalfWayHome, 20, abstractEvent: this, priority: 3), pearlType, 0.7);
                }
            }
            OpponentData _leader = currentGameState.getOpponentAtOverallPosition(1);
            if (_leader != null) {
                leaderOnSameLap = currentGameState.PositionAndMotionData.DistanceRoundTrack <
                    _leader.DistanceRoundTrack;
            }
        }

        private static readonly List<SpeechCommands.ID> Commands = new List<SpeechCommands.ID>
        {
            SpeechCommands.ID.HOW_LONGS_LEFT,
            SpeechCommands.ID.SESSION_STATUS,
            SpeechCommands.ID.STATUS,
            SpeechCommands.ID.WHAT_LAP_AM_I_ON,
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
            if (CrewChief.currentGameState == null)
            {
                return;
            }

            switch (cmd)
            {
                case SpeechCommands.ID.HOW_LONGS_LEFT:
                case SpeechCommands.ID.SESSION_STATUS:
                case SpeechCommands.ID.STATUS:
                    {
                        var messages = new List<MessageFragment>();

                        // some sims have fixed length sessions with a time cap and it's useful to report the time cap as well
                        // when it is getting near.
                        if (sessionLengthIsTime || (timeLeft > 0 && timeLeft < 600))
                        {
                            if (Game.RF2_LMU
                                && CrewChief.currentGameState.SessionData.SessionType == SessionType.Race
                                && (CrewChief.currentGameState.FrozenOrderData.Phase == FrozenOrderPhase.FastRolling
                                    || CrewChief.currentGameState.FrozenOrderData.Phase == FrozenOrderPhase.Rolling
                                    || CrewChief.currentGameState.SessionData.SessionPhase == SessionPhase.Formation
                                    || CrewChief.currentGameState.SessionData.SessionPhase == SessionPhase.Garage
                                    || CrewChief.currentGameState.SessionData.SessionPhase == SessionPhase.Gridwalk))
                            {
                                // rF2 data is shit for above cases.
                                audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                                return;
                            }

                            if (sessionLengthIsTime && leaderHasFinishedRace)
                            {
                                messages.Add(MessageFragment.Text(folderThisIsTheLastLap));
                            }
                            else if (timeLeft >= 120)
                            {
                                int minutesLeft = (int)Math.Round(timeLeft / 60f);
                                messages.AddRange(MessageContents(TimeSpanWrapper.FromMinutes(minutesLeft, Precision.MINUTES), folderRemaining));
                            }
                            else if (timeLeft >= 60)
                            {
                                messages.Add(MessageFragment.Text(folderOneMinuteRemaining));
                            }
                            else if (timeLeft <= 0)
                            {
                                if (extraLapsAfterTimedSessionComplete > 0 && extraLapsRemaining == 1)
                                {
                                    messages.Add(MessageFragment.Text(folderOneLapAfterThisOne));
                                }
                                else if (extraLapsAfterTimedSessionComplete > 0 && extraLapsRemaining > 1)
                                {
                                    messages.AddRange(MessageContents(extraLapsRemaining, folderLapsLeft));
                                }
                                else
                                {
                                    messages.Add(MessageFragment.Text(folderThisIsTheLastLap));
                                }
                            }
                            else if (timeLeft < 60)
                            {
                                messages.Add(MessageFragment.Text(folderLessThanOneMinute));
                            }

                            if (sessionLengthIsTime && (lapsLeft = Fuel.LapsRemaining) > 2)
                            {
                                // this will also fall through to the lapsLeft checks below...
                                messages.Add(MessageFragment.Text("fuel/we_estimate"));
                            }
                        }

                        // falls through from above, since lapsLeft may be estimated for timed sessions
                        if (lapsLeft > 2)
                        {
                            messages.AddRange(MessageContents(lapsLeft, folderLapsLeft));
                        }
                        else if (lapsLeft > 0) // (lapsLeft == 0 is a special case, dunno what)
                        { // "This is the last lap" only makes sense if the leader
                          // is on the same lap as us - if they're a lap ahead,
                          // then we have one more lap to go after this one.
                            switch (leaderOnSameLap ? lapsLeft : lapsLeft + 1)
                            {
                                case 2:
                                    messages.Add(MessageFragment.Text(folderOneLapAfterThisOne));
                                    break;
                                case 1:
                                    messages.Add(MessageFragment.Text(folderThisIsTheLastLap));
                                    break;
                            }
                        }

                        // this is useful context if the driver meant "how long's left [in this stint]"
                        if (Fuel.LapsUntilRefuel > 0)
                        {
                            messages.AddRange(
                                MessageContents(
                                    Pause(200),
                                    "fuel/we_estimate",
                                    MessageFragment.Integer(Fuel.LapsUntilRefuel, MessageFragment.Genders("pt-br", NumberReader.ARTICLE_GENDER.FEMALE)),
                                    folderLapsLeft));
                        }

                        audioPlayer.playMessageImmediately(new QueuedMessage("RaceTime/how_longs_left", 0, messageFragments: messages));
                        break;
                    }
                case SpeechCommands.ID.WHAT_LAP_AM_I_ON:
                    // would benefit from a "lap" prefix sound
                    audioPlayer.playMessageImmediately(new QueuedMessage("RaceTime/lap", 0,
                        messageFragments: MessageContents(CrewChief.currentGameState.SessionData.LapCount)));
                    break;
            }
        }
    }
}
