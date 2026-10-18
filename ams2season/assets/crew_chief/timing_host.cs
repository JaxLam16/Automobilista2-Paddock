// Availability/diagnostics only. Original Timings and delta algorithms unchanged.
using System;using System.Collections.Generic;using System.Reflection;
using CrewChiefV4.GameState;using CrewChiefV4.Events;
public static class PaddockTimingsHost {
    static readonly Dictionary<string,DateTime> firstSeen=new Dictionary<string,DateTime>();
    static readonly Dictionary<string,DeltaTime> observedDeltas=new Dictionary<string,DeltaTime>();
    public static void Reset(){firstSeen.Clear();observedDeltas.Clear();}
    static void ObserveDelta(string key,DeltaTime value,DateTime now){
        DeltaTime old;
        if(!observedDeltas.TryGetValue(key,out old) || !Object.ReferenceEquals(old,value))firstSeen[key]=now;
        observedDeltas[key]=value;
    }
    public static void Observe(GameStateData state){
        foreach(string key in new List<string>(firstSeen.Keys))if(key.StartsWith("opponent:") && !state.OpponentData.ContainsKey(key.Substring(9))){firstSeen.Remove(key);observedDeltas.Remove(key);}
        ObserveDelta("__player",state.SessionData.DeltaTime,state.Now);
        foreach(var item in state.OpponentData)ObserveDelta("opponent:"+item.Key,item.Value.DeltaTime,state.Now);
    }
    static bool History(GameStateData state,string key){
        OpponentData other;DateTime playerSeen,otherSeen;
        if(key==null || !state.OpponentData.TryGetValue(key,out other) || !firstSeen.TryGetValue("__player",out playerSeen) || !firstSeen.TryGetValue("opponent:"+key,out otherSeen))return false;
        var a=state.SessionData.DeltaTime;var b=other.DeltaTime;
        if(a==null || b==null || a.deltaPoints==null || b.deltaPoints==null || a.deltaPoints.Length!=b.deltaPoints.Length)return false;
        int i=a.currentDeltaPointIndex,j=b.currentDeltaPointIndex;
        return i>=0 && j>=0 && i<a.deltaPoints.Length && j<a.deltaPoints.Length &&
            a.deltaPoints[i]>playerSeen && a.deltaPoints[j]>playerSeen && b.deltaPoints[i]>otherSeen && b.deltaPoints[j]>otherSeen;
    }
    static bool GapKnown(GameStateData state,bool front){
        string key=front?state.SessionData.OpponentKeyInFront:state.SessionData.OpponentKeyBehind;
        OpponentData other=null;
        if(key!=null)state.OpponentData.TryGetValue(key,out other);
        if(other==null){
            // The original key helper excludes the final grid slot in a small
            // field. A valid game split is still usable if the actual adjacent
            // class entrant is uniquely present; do not change the event's key.
            int rank=state.SessionData.ClassPosition+(front?-1:1);
            foreach(var item in state.OpponentData)if(item.Value.ClassPosition==rank && CrewChiefV4.CarData.IsCarClassEqual(item.Value.CarClass,state.carClass)){
                if(other!=null)return false;key=item.Key;other=item.Value;
            }
        }
        if(other==null)return false;
        var raw=((CrewChiefV4.AMS2.AMS2SharedMemoryReader.AMS2StructWrapper)state.rawGameData).data;
        int lapDelta=front?state.SessionData.LapsDeltaFront:state.SessionData.LapsDeltaBehind;
        return !GameStateData.Multiclass && lapDelta==0 ? (front?raw.mSplitTimeAhead:raw.mSplitTimeBehind)>=0 : History(state,key);
    }
    public static bool AutomaticInputsKnown(GameStateData state){
        // A negative game split is an unavailable sentinel, never a one-second gap.
        if(state.SessionData.ClassPosition>1 && state.SessionData.OpponentKeyInFront!=null && !GapKnown(state,true))return false;
        if(!state.isLast() && state.SessionData.OpponentKeyBehind!=null && !GapKnown(state,false))return false;
        return true;
    }
    public static string Unsupported(GameStateData state,string command){
        switch(command){
            case "WHERE_AM_I_FASTER":
            case "WHERE_AM_I_SLOWER":
                var other=state.getOpponentAtClassPosition(state.SessionData.ClassPosition+(command=="WHERE_AM_I_FASTER"?-1:1),state.carClass);
                return other==null || state.SessionData.trackLandmarksTiming==null || other.trackLandmarksTiming==null
                    ?"corner comparison opponent or landmark data unavailable":null;
            case "WHATS_MY_GAP_IN_FRONT":return state.SessionData.ClassPosition==1 || GapKnown(state,true)?null:"gap ahead unavailable";
            case "WHATS_MY_GAP_BEHIND":return state.isLastInStandings() || GapKnown(state,false)?null:"gap behind unavailable";
            case "WHATS_MY_GAP_IN_FRONT_ON_TRACK":return History(state,state.getOpponentKeyInFrontOnTrack())?null:"on-track crossing history unavailable";
            case "WHATS_MY_GAP_BEHIND_ON_TRACK":return History(state,state.getOpponentKeyBehindOnTrack())?null:"on-track crossing history unavailable";
            case "WHATS_MY_GAP_TO_LEADER":return state.SessionData.ClassPosition==1 || History(state,state.getOpponentKeyAtClassPosition(1,state.carClass))?null:"leader crossing history unavailable";
        }
        return null;
    }
    internal static object State(AbstractEvent timings,GameStateData state) {
        var fields=new Dictionary<string,object>();
        foreach(string name in new[]{"gapInFrontAtLastReport","gapBehindAtLastReport","sectorsSinceLastGapAheadReport","sectorsSinceLastGapBehindReport","sectorsUntilNextGapAheadReport","sectorsUntilNextGapBehindReport"})
            fields[name]=timings.GetType().GetField(name,BindingFlags.Instance|BindingFlags.NonPublic).GetValue(timings);
        var s=state==null?null:state.SessionData;
        return new {mode=timings is Timings_legacy?"legacy":"current",fields=fields,mapped=s==null?null:new {s.TimeDeltaFront,s.TimeDeltaBehind,s.LapsDeltaFront,s.LapsDeltaBehind,
            s.OpponentKeyInFront,s.OpponentKeyBehind,s.IsRacingSameCarInFront,s.IsRacingSameCarBehind,s.IsNewSector,s.SectorNumber,
            s.ClassPosition,s.CompletedLaps,s.SessionLapsRemaining,phase=s.SessionPhase.ToString()}};
    }
}
