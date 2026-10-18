// Availability only; original installed TyreMonitor decisions unchanged.
using System;using System.Linq;using System.Reflection;using System.Collections.Generic;
using CrewChiefV4.GameState;using CrewChiefV4.Events;
public static class PaddockTyresHost {
    static bool Range(float[] values,float min,float max) {
        return values!=null && values.Length==4 && values.All(v=>!float.IsNaN(v) && !float.IsInfinity(v) && v>=min && v<=max);
    }
    public static bool InputsKnown(GameStateData state) {
        var r=((CrewChiefV4.AMS2.AMS2SharedMemoryReader.AMS2StructWrapper)state.rawGameData).data;
        return Range(r.mTyreTempLeft,0.01f,200) && Range(r.mTyreTempCenter,0.01f,200) && Range(r.mTyreTempRight,0.01f,200)
            && Range(r.mBrakeTempCelsius,0.01f,2000) && Range(r.mAirPressure,0,2000) && r.mAirPressure.Any(v=>v>0)
            && Range(r.mTyreWear,0,1) && Range(r.mTyreRPS,-10000,10000)
            && state.carClass!=null;
    }
    internal static string Unsupported(TyreMonitor tyres,GameStateData state,string command) {
        // The original AMS2 mapper leaves set age/history and compound-relative
        // performance unpopulated. Their zero/empty defaults are not evidence.
        switch(command) {
            case "HOW_MANY_LAPS_ON_TYRE_SET":case "HOW_OLD_ARE_THESE_TYRES":
                return "AMS2 tyre set age/history not mapped";
            case "WHAT_ARE_THE_RELATIVE_TYRE_PERFORMANCES":
                return "AMS2 compound comparison history not mapped";
            case "HOW_LONG_WILL_THESE_TYRES_LAST":
                var worst=(Tuple<CornerData.Corners,float>)tyres.GetType().GetMethod("getMaxWearPercent",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(tyres,null);
                if(worst.Item2<5)return null; // Original new-tyre/no-data responses.
                bool byLap=state.SessionData.SessionNumberOfLaps>0 || state.SessionData.SessionTotalRunTime==0;
                string suffix=byLap?"BySector":"ByTime";
                string wheel=worst.Item1==CornerData.Corners.FRONT_LEFT?"LF":worst.Item1==CornerData.Corners.FRONT_RIGHT?"RF":worst.Item1==CornerData.Corners.REAR_LEFT?"LR":"RR";
                var values=(List<double>)tyres.GetType().GetField("tyreLifeXPoints"+wheel+"Wear"+suffix,BindingFlags.Instance|BindingFlags.NonPublic).GetValue(tyres);
                if(values.Count<5 || values.Distinct().Count()<3)return "insufficient observed wear trajectory for original polynomial estimate";
                return null;
        }
        return null;
    }
    internal static object State(TyreMonitor tyres,GameStateData state) {
        return new {original_event=tyres.GetType().FullName,inputs_known=state!=null && InputsKnown(state),
            tyre_set_history_available=false,compound_comparison_available=false};
    }
}
