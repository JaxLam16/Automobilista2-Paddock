// Original event is unchanged; reject unavailable zero sector durations.
using System;using CrewChiefV4.GameState;using CrewChiefV4.Events;
public static class PaddockLapTimesHost {
    public static string Unsupported(GameStateData state,string command) {
        var s=state.SessionData;
        if(command=="WHAT_ARE_MY_SECTOR_TIMES" && (s.LastSector1Time<=0 || s.LastSector2Time<=0 || s.LastSector3Time<=0))return "complete positive sector times unavailable";
        if(command=="WHATS_MY_LAST_SECTOR_TIME") {
            float value=s.SectorNumber==1?s.LastSector3Time:s.SectorNumber==2?s.LastSector1Time:s.LastSector2Time;
            if(value<=0)return "positive last sector time unavailable";
        }
        return null;
    }
    public static object State(AbstractEvent selected,GameStateData state) {
        var s=state==null?null:state.SessionData;
        return new {mode=selected is LapTimes_legacy?"legacy":"current",type=selected.GetType().FullName,
            mapped=s==null?null:new {s.LapTimePrevious,s.PlayerLapTimeSessionBest,s.PlayerClassSessionBestLapTime,
                s.LastSector1Time,s.LastSector2Time,s.LastSector3Time,s.CompletedLaps,s.SectorNumber,
                s.CurrentLapIsValid,s.PreviousLapWasValid,s.IsNewLap,s.IsNewSector,
                phase=s.SessionPhase.ToString(),session=s.SessionType.ToString(),s.SessionTimeRemaining,s.SessionTotalRunTime}};
    }
}
