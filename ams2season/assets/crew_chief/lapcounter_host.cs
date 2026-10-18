// Read-only diagnostics; original event fields are never changed here.
using System;using System.Collections.Generic;using CrewChiefV4.Events;using CrewChiefV4.GameState;
namespace CrewChiefV4 { public static class LapCounterHost {
    internal static object State(LapCounter counter,GameStateData state) {
        var data=new Dictionary<string,object>();
        foreach(string name in new [] {"playedGetReady","purgePreLightsMessages","leaderHasFinished","lastReportedGridWalkTime","playedPreLightsRollingStartWarning"})
            data[name]=typeof(LapCounter).GetField(name,System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic).GetValue(counter);
        return new {data=data,LapCounter.playedPreLightsMessage,LapCounter.preStartTempsAnnounced,LapCounter.whiteFlagLastLapAnnounced,
            manual_formation_supported=false,mapped=state==null?null:new {state.SessionData.SessionNumberOfLaps,state.SessionData.SessionHasFixedTime,
                state.SessionData.SessionLapsRemaining,state.SessionData.CompletedLaps,state.SessionData.IsNewLap,state.SessionData.IsLastLap,
                state.SessionData.SessionTimeRemaining,state.SessionData.LeaderHasFinishedRace,phase=state.SessionData.SessionPhase.ToString()}};
    }
} }
