using CrewChiefV4.Events;
using System;
using System.Collections.Generic;

namespace CrewChiefV4.GameState
{
    public abstract class GameStateMapper
    {
        protected SpeechRecogniser speechRecogniser;

        // in race sessions, delay position changes to allow things to settle. This is game-dependent
        private Dictionary<string, PendingRacePositionChange> PendingRacePositionChanges = new Dictionary<string, PendingRacePositionChange>();
        private Dictionary<string, PendingRacePositionChange> PendingRaceClassPositionChanges = new Dictionary<string, PendingRacePositionChange>();
        private TimeSpan PositionChangeLag = TimeSpan.FromMilliseconds(1000);
        class PendingRacePositionChange
        {
            public int newPosition;
            public DateTime positionSettledTime;
            public PendingRacePositionChange(int newPosition, DateTime positionSettledTime)
            {
                this.newPosition = newPosition;
                this.positionSettledTime = positionSettledTime;
            }
        }

        /// <summary>
        /// May return null if the game state raw data is considered invalid
        /// </summary>
        public abstract GameStateData mapToGameStateData(Object memoryMappedFileStruct, GameStateData previousGameState);

        /// <summary>
        /// May throw an exception if data is not available
        /// (depends on which game)
        /// </summary>
        public abstract void versionCheck(Object memoryMappedFileStruct);

        private DateTime nextOpponentBehindPitMessageDue = DateTime.MinValue;
        private DateTime nextOpponentAheadPitMessageDue = DateTime.MinValue;
        private DateTime nextLeaderPitMessageDue = DateTime.MinValue;
        private Boolean resetClassStartPos = false; // an AMS hack - class start pos is incorrect until 1 tick after 'just gone green'

        public virtual void setSpeechRecogniser(SpeechRecogniser speechRecogniser)
        {
            this.speechRecogniser = speechRecogniser;
        }

        // This method populates data derived from the mapped data, that's common to all games.
        // This is specific to race sessions. At the time of writing there's nothing needed for qual and
        // practice, but these may be added later
        public virtual void populateDerivedRaceSessionData(GameStateData currentGameState)
        {
            Boolean singleClass = GameStateData.NumberOfClasses == 1 || CrewChief.forceSingleClass;
            // always set the session start class position and lap start class position:
            if (currentGameState.SessionData.JustGoneGreen || currentGameState.SessionData.IsNewSession || resetClassStartPos)
            {
                // for RF1 the class start pos only appears to be correct on the tick after JustGoneGreen, so allow it to be updated on this tick.
                // for now we'll apply this same hack to RF2 - it shouldn't break anything and the bug may be common to both games
                if (resetClassStartPos)
                {
                    Console.WriteLine("Resetting class start pos from " + currentGameState.SessionData.SessionStartClassPosition + " to " + currentGameState.SessionData.ClassPosition);
                    resetClassStartPos = false;
                }
                else if ((Game.RF1 || Game.RF2_LMU) && currentGameState.SessionData.JustGoneGreen)
                {
                    resetClassStartPos = true;
                }

                // NOTE: on new session, ClassPosition in rF2 is not correct.  It is updated with a bit of a delay.
                // Since this code triggers on JustGoneGreen as well, this is corrected at that point, but I am not yet sure
                // there are no bad side effects.
                currentGameState.SessionData.SessionStartClassPosition = currentGameState.SessionData.ClassPosition;
                if (singleClass)
                {
                    currentGameState.SessionData.NumCarsInPlayerClassAtStartOfSession = currentGameState.SessionData.NumCarsOverallAtStartOfSession;
                }
                // reset the complaints count to zero
                GlobalBehaviourSettings.complaintsCountInThisSession = 0;
            }
            if (currentGameState.SessionData.JustGoneGreen)
            {
                currentGameState.SessionData.JustGoneGreenTime = currentGameState.Now;
            }
            if (currentGameState.SessionData.IsNewLap)
            {
                currentGameState.SessionData.ClassPositionAtStartOfCurrentLap = currentGameState.SessionData.ClassPosition;
            }

            float PitApproachPosition = currentGameState.SessionData.TrackDefinition != null ? currentGameState.SessionData.TrackDefinition.distanceForNearPitEntryChecks : -1;
            
            // sort out all the class position stuff
            int numCarsInPlayerClass = 1;
            int leaderLapsCompleted = currentGameState.SessionData.CompletedLaps;
            foreach (OpponentData opponent in currentGameState.OpponentData.Values)
            {
                if (!opponent.IsActive)
                {
                    continue;
                }
                if (opponent.OverallPosition == 1)
                {
                    leaderLapsCompleted = opponent.CompletedLaps;
                }
                if (singleClass || CarData.IsCarClassEqual(opponent.CarClass, currentGameState.carClass))
                {
                    // special hack for iRacing until we finally kill those bastard opponent pitting spam messages
                    int minSecondsBetweenOpponentPitMessages = Game.IRACING ? 40 : 20;
                    // don't care about other classes
                    numCarsInPlayerClass++;
                    if ((PitApproachPosition != -1
                        && opponent.DistanceRoundTrack < PitApproachPosition + 20
                        && opponent.DistanceRoundTrack > PitApproachPosition - 20 && !Game.IRACING) ||
                        Game.IRACING && opponent.isApporchingPits)
                    {
                        opponent.PositionOnApproachToPitEntry = opponent.ClassPosition;
                    }
                    if (opponent.ClassPosition == 1)
                    {
                        if (opponent.ClassPositionAtPreviousTick != 1)
                        {
                            currentGameState.SessionData.HasLeadChanged = true;
                        }
                        currentGameState.SessionData.LeaderSectorNumber = opponent.CurrentSectorNumber;
                        if (opponent.JustEnteredPits && currentGameState.Now > nextLeaderPitMessageDue && currentGameState.Now > Strategy.nextOpponentPitExitWarningDue)
                        {
                            nextLeaderPitMessageDue = currentGameState.Now.AddSeconds(minSecondsBetweenOpponentPitMessages);
                            currentGameState.PitData.LeaderIsPitting = true;
                            currentGameState.PitData.OpponentForLeaderPitting = opponent;
                        }
                        else
                        {
                            currentGameState.PitData.LeaderIsPitting = false;
                            currentGameState.PitData.OpponentForLeaderPitting = null;
                        }
                    }

                    var deltaOpponent = currentGameState.getOpponentAtClassPositionRaw(opponent.ClassPosition - 1, opponent.CarClass);
                    if(deltaOpponent != null) 
                    {
                        var timeDelta = opponent.DeltaTime.GetAbsoluteTimeDeltaAllowingForLapDifferences(deltaOpponent.DeltaTime);
                        opponent.LapsDeltaFront = timeDelta.Item1;
                        opponent.TimeDeltaFront = timeDelta.Item2;
                    }
                    deltaOpponent = currentGameState.getOpponentAtClassPositionRaw(opponent.ClassPosition + 1, opponent.CarClass);
                    if (deltaOpponent != null)
                    {
                        var timeDelta = opponent.DeltaTime.GetAbsoluteTimeDeltaAllowingForLapDifferences(deltaOpponent.DeltaTime);
                        opponent.LapsDeltaBehind = timeDelta.Item1;
                        opponent.TimeDeltaBehind = timeDelta.Item2;
                    }
                
                    if (opponent.ClassPosition == currentGameState.SessionData.ClassPosition - 1)
                    {
                        var useDerivedDeltas = true;
                        if (singleClass &&
                             (Game.PCARS2
                              || Game.RACE_ROOM
                              || Game.RF2_LMU
                              || Game.RF1   // TBD GTR2 seems to be the same
                              || Game.AMS2
                              || Game.PCARS3))
                        {
                            // special case for R3E, RF1, RF2, AMS2 and PCars2 - gap ahead is provided by the game - use these 
                            // (already set in the mapper) if the opponent is on the same lap and we're racing a single class
                            var lapDifference = opponent.DeltaTime.GetSignedLapDifference(currentGameState.SessionData.DeltaTime);
                            if (lapDifference == 0)
                            {
                                currentGameState.SessionData.LapsDeltaFront = 0;
                                useDerivedDeltas = false;
                            }
                        }
                        if (useDerivedDeltas)
                        {
                            var timeDelta = opponent.DeltaTime.GetAbsoluteTimeDeltaAllowingForLapDifferences(currentGameState.SessionData.DeltaTime);

                            currentGameState.SessionData.LapsDeltaFront = timeDelta.Item1;
                            currentGameState.SessionData.TimeDeltaFront = timeDelta.Item2;
                        }
                        if (opponent.JustEnteredPits && currentGameState.Now > nextOpponentAheadPitMessageDue && currentGameState.Now > Strategy.nextOpponentPitExitWarningDue)
                        {
                            nextOpponentAheadPitMessageDue = currentGameState.Now.AddSeconds(minSecondsBetweenOpponentPitMessages);
                            currentGameState.PitData.CarInFrontIsPitting = true;
                            currentGameState.PitData.OpponentForCarAheadPitting = opponent;
                        }
                        else
                        {
                            currentGameState.PitData.CarInFrontIsPitting = false;
                            currentGameState.PitData.OpponentForCarAheadPitting = null;
                        }
                    }
                    else if (opponent.ClassPosition == currentGameState.SessionData.ClassPosition + 1)
                    {
                        var useDerivedDeltas = true;
                        if (singleClass &&
                            (Game.PCARS2 
                             || Game.RACE_ROOM
                             || Game.AMS2
                             || Game.PCARS3))
                        {
                            // special case for R3E, AMS2 and PCars2 - gap behind is provided by the game - use these 
                            // (already set in the mapper) if the opponent is on the same lap and we're not racing multiclass
                            // (the game-provided gaps may not take car class into account, so they're only safe to use in single class)
                            var lapDifference = opponent.DeltaTime.GetSignedLapDifference(currentGameState.SessionData.DeltaTime);
                            if (lapDifference == 0)
                            {
                                currentGameState.SessionData.LapsDeltaBehind = 0;
                                useDerivedDeltas = false;
                            }
                        }
                        if (useDerivedDeltas)
                        {
                            var timeDelta = opponent.DeltaTime.GetAbsoluteTimeDeltaAllowingForLapDifferences(currentGameState.SessionData.DeltaTime);
                            currentGameState.SessionData.LapsDeltaBehind = timeDelta.Item1;
                            currentGameState.SessionData.TimeDeltaBehind = timeDelta.Item2;
                        }
                        if (opponent.JustEnteredPits && currentGameState.Now > nextOpponentBehindPitMessageDue && currentGameState.Now > Strategy.nextOpponentPitExitWarningDue)
                        {
                            nextOpponentBehindPitMessageDue = currentGameState.Now.AddSeconds(minSecondsBetweenOpponentPitMessages);
                            currentGameState.PitData.CarBehindIsPitting = true;
                            currentGameState.PitData.OpponentForCarBehindPitting = opponent;
                        }
                        else
                        {
                            currentGameState.PitData.CarBehindIsPitting = false;
                            currentGameState.PitData.OpponentForCarBehindPitting = null;
                        }
                    }
                }
            }
            // sanity check the leaderLapsCompleted data
            leaderLapsCompleted = Math.Max(leaderLapsCompleted, currentGameState.SessionData.CompletedLaps);
            if (!currentGameState.SessionData.SessionHasFixedTime)
            {
                // work out the laps remaining
                currentGameState.SessionData.SessionLapsRemaining = currentGameState.SessionData.SessionNumberOfLaps - leaderLapsCompleted;
            }
            
            if (currentGameState.SessionData.JustGoneGreen || currentGameState.SessionData.IsNewSession)
            {
                currentGameState.SessionData.NumCarsInPlayerClassAtStartOfSession = numCarsInPlayerClass;
            }
            currentGameState.SessionData.NumCarsInPlayerClass = numCarsInPlayerClass;

            // now derive some stuff that we always need to derive, using the correct class positions:
            String previousBehindKey;
            String previousAheadKey;
            if (Game.IRACING)
            { // Lovely!
                previousBehindKey = currentGameState.getOpponentKeyBehind(currentGameState.carClass, true);
                previousAheadKey = currentGameState.getOpponentKeyInFront(currentGameState.carClass, true);
            }
            else
            {
                // Assuming game's mapper has copied these...
                previousBehindKey = currentGameState.SessionData.OpponentKeyBehind;
                previousAheadKey = currentGameState.SessionData.OpponentKeyInFront;
            }
            String currentBehindKey = currentGameState.getOpponentKeyBehind(currentGameState.carClass);
            String currentAheadKey = currentGameState.getOpponentKeyInFront(currentGameState.carClass);
            if (currentGameState.SessionData.ClassPosition > 2)
            {
                // if we're first or second we don't care about lead changes
                String previousLeaderKey = currentGameState.getOpponentKeyAtClassPosition(1, currentGameState.carClass, true);
                String currentLeaderKey = currentGameState.getOpponentKeyAtClassPosition(1, currentGameState.carClass);                
            }
            // don't really need this any more:
            /*
            if (CrewChief.Debug.RunningUnderDebugger
                && ((currentBehindKey == null && currentGameState.SessionData.ClassPosition < currentGameState.SessionData.NumCarsInPlayerClass)
                      || (currentAheadKey == null && currentGameState.SessionData.ClassPosition > 1)))
            {
                Console.WriteLine("Non-contiguous class positions");
                List<OpponentData> opponentsInClass = new List<OpponentData>();
                foreach (OpponentData opponent in currentGameState.OpponentData.Values)
                {
                    if (CarData.IsCarClassEqual(opponent.CarClass, currentGameState.carClass))
                    {
                        opponentsInClass.Add(opponent);
                    }
                    Console.WriteLine(String.Join("\n", opponentsInClass.OrderBy(o => o.ClassPosition)));
                }
            }*/


            if (Game.IRACING)// dont allow change to false unless GameTimeAtLastPositionFrontChange has settled for 2 sec
            {
                currentGameState.SessionData.IsRacingSameCarInFront = true; 
                currentGameState.SessionData.IsRacingSameCarBehind = true;
                if (currentAheadKey != previousAheadKey)
                {
                    currentGameState.SessionData.GameTimeAtLastPositionFrontChange = currentGameState.SessionData.SessionRunningTime;
                }
                if (currentAheadKey != currentGameState.SessionData.OpponentKeyInFront && 
                    currentGameState.SessionData.GameTimeAtLastPositionFrontChange + 2 <= currentGameState.SessionData.SessionRunningTime)
                {
                    // TODO: check opponent TimeDeltaBehind against opponent if we are running last 
                    //if (currentGameState.isLast())
                    //{
                    //    currentGameState.SessionData.IsRacingSameCarInFront = false;
                    //    currentGameState.SessionData.OpponentKeyInFront = currentAheadKey;
                    //}
                    //else if (currentGameState.SessionData.TimeDeltaBehind > 0.1)
                    //{
                    Log.Debug(() => $"IsRacingSameCarInFront {currentGameState.SessionData.OpponentKeyInFront} {currentAheadKey}");
                        currentGameState.SessionData.IsRacingSameCarInFront = false;
                        currentGameState.SessionData.OpponentKeyInFront = currentAheadKey;
                    //}
                }

                if (currentBehindKey != previousBehindKey)
                {
                    currentGameState.SessionData.GameTimeAtLastPositionBehindChange = currentGameState.SessionData.SessionRunningTime;
                }
                if (currentBehindKey != currentGameState.SessionData.OpponentKeyBehind && 
                    currentGameState.SessionData.GameTimeAtLastPositionBehindChange + 2 <= currentGameState.SessionData.SessionRunningTime)
                {
                    // TODO: check opponent TimeDeltaBehind against opponent if we are P1
                    Log.Debug(() => $"IsRacingSameCarBehind {currentGameState.SessionData.OpponentKeyBehind} {currentBehindKey}");
                    currentGameState.SessionData.IsRacingSameCarBehind = false;
                    currentGameState.SessionData.OpponentKeyBehind = currentBehindKey;
                }
            }
            else // !iRacing
            {
                currentGameState.SessionData.IsRacingSameCarBehind = currentBehindKey == previousBehindKey;
                currentGameState.SessionData.IsRacingSameCarInFront = currentAheadKey == previousAheadKey;
                if (!currentGameState.SessionData.IsRacingSameCarInFront)
                {
                    currentGameState.SessionData.GameTimeAtLastPositionFrontChange = currentGameState.SessionData.SessionRunningTime;
                    currentGameState.SessionData.OpponentKeyInFront = currentAheadKey;
                    if ((Log.LogMask & Log.LogType.Debug) != 0)
                    {
                        if (currentAheadKey != null)
                        {
                            currentGameState.OpponentData.TryGetValue(currentAheadKey, out OpponentData opponent);
                            Log.Debug(() => $"Car in front changed to {currentAheadKey}, player is P{currentGameState.SessionData.ClassPosition}, opponent {opponent}");
                        }
                        else
                        {
                            string _leading = currentGameState.SessionData.ClassPosition == 1 ? "leading" : "not leading";
                            Log.Debug(() => $"Car in front changed to null, player is P{currentGameState.SessionData.ClassPosition}, {_leading}");
                        }
                    }
                }
                if (!currentGameState.SessionData.IsRacingSameCarBehind)
                {
                    currentGameState.SessionData.GameTimeAtLastPositionBehindChange = currentGameState.SessionData.SessionRunningTime;
                    currentGameState.SessionData.OpponentKeyBehind = currentBehindKey;
                    if ((Log.LogMask & Log.LogType.Debug) != 0)
                    {
                        if (currentBehindKey != null)
                        {
                            currentGameState.OpponentData.TryGetValue(currentBehindKey, out OpponentData opponent);
                            Log.Debug(() => $"Car behind changed to {currentBehindKey}, player is P{currentGameState.SessionData.ClassPosition}, opponent {opponent}");
                        }
                        else
                        {
                            string _last = currentGameState.isLast() ? "last" : "not last";
                            Log.Debug(() => $"Car behind changed to null, player is P{currentGameState.SessionData.ClassPosition}, {_last}");
                        }
                    }
                }
            }

            
        }

        // so far, only the laps remaining is populated for non-race sessions. This is a bit of an edge case anyway - non-race sessions
        // with fixed number of laps is an American thing really.
        //
        // Update - we also need a little car class data in these sessions
        public virtual void populateDerivedNonRaceSessionData(GameStateData currentGameState)
        {
            if (!currentGameState.SessionData.SessionHasFixedTime)
            {
                currentGameState.SessionData.SessionLapsRemaining = currentGameState.SessionData.SessionNumberOfLaps - currentGameState.SessionData.CompletedLaps;
            }
            // just need the car class counts here
            Boolean singleClass = GameStateData.NumberOfClasses == 1 || CrewChief.forceSingleClass;
            int numCarsInPlayerClass = 1;
            foreach (OpponentData opponent in currentGameState.OpponentData.Values)
            {
                if (!opponent.IsActive)
                {
                    continue;
                }
                if (singleClass || CarData.IsCarClassEqual(opponent.CarClass, currentGameState.carClass))
                {
                    numCarsInPlayerClass++;
                }
            }
            currentGameState.SessionData.NumCarsInPlayerClass = numCarsInPlayerClass;
        }

        // filters race position changes by delaying them a short time to prevent bouncing and noise interferring with event logic
        protected int getRacePosition(String driverName, int oldPosition, int newPosition, DateTime now, bool isClassPosition = false)
        {
            var pendingRaceClassPositionChanges = isClassPosition ? PendingRaceClassPositionChanges : PendingRacePositionChanges;
            if (driverName == null || oldPosition < 1)
            {
                return newPosition;
            }
            if (newPosition < 1 && !Game.IRACING)
            { 
                return oldPosition;
            }
            PendingRacePositionChange pendingRacePositionChange = null;
            if (oldPosition == newPosition)
            {
                // clear any pending position change
                pendingRaceClassPositionChanges.Remove(driverName);
                return oldPosition;
            }
            else if (pendingRaceClassPositionChanges.TryGetValue(driverName, out pendingRacePositionChange))
            {
                if (newPosition == pendingRacePositionChange.newPosition)
                {
                    // the game is still reporting this driver is in the same race position, see if it's been long enough...
                    if (now > pendingRacePositionChange.positionSettledTime)
                    {
                        int positionToReturn = newPosition;
                        pendingRaceClassPositionChanges.Remove(driverName);
                        return positionToReturn;
                    }
                    else
                    {
                        return oldPosition;
                    }
                }
                else
                {
                    // the new position is not consistent with the pending position change, bit of an edge case here
                    pendingRacePositionChange.newPosition = newPosition;
                    pendingRacePositionChange.positionSettledTime = now + PositionChangeLag;
                    return oldPosition;
                }
            }
            else
            {
                pendingRaceClassPositionChanges.Add(driverName, new PendingRacePositionChange(newPosition, now + PositionChangeLag));
                return oldPosition;
            }
        }
    }
}
