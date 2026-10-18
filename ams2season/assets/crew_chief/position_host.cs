// Diagnostics only: event fields are read, never changed by the adapter.
using System;
using System.Collections.Generic;
using System.Linq;
using CrewChiefV4.Events;
using CrewChiefV4.GameState;
namespace CrewChiefV4 {
    public static class PositionHost {
        static readonly System.Reflection.MethodInfo clone=typeof(object).GetMethod("MemberwiseClone",System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic);
        public static GameStateData Current(GameStateData state) {
            if(state==null)return null;
            var copy=(GameStateData)clone.Invoke(state,null);
            copy.FlagData=(FlagData)clone.Invoke(state.FlagData,null);
            // AMS2 maps its actual driver-highest flag into SessionData.Flag,
            // but leaves the separate local/sector flag fields unset. Preserve
            // a known yellow for Position's original clean-pass/start gates.
            copy.FlagData.isLocalYellow=state.FlagData.isLocalYellow ||
                state.SessionData.Flag==FlagEnum.YELLOW || state.SessionData.Flag==FlagEnum.DOUBLE_YELLOW;
            return copy;
        }
        public static GameStateData Capture(GameStateData state) {
            if(state==null)return null;
            // The mapper deliberately reuses/mutates OpponentData objects. Keep
            // real preceding ranks/laps/speeds for the original Position event,
            // which reads its previous argument during candidate detection.
            var copy=Current(state);
            copy.OpponentData=state.OpponentData.ToDictionary(p=>p.Key,p=>(OpponentData)clone.Invoke(p.Value,null));
            return copy;
        }
        internal static object State(Position position,GameStateData state) {
            var data=new Dictionary<string,object>();
            foreach(string name in new [] {"currentPosition","previousPosition","numberOfLapsInLastPlace",
                "playedRaceStartMessage","startMessageTime","isLastInStandings","lastPassCheck",
                "lastOvertakeMessageTime","timeWhenWeMadeAPass","timeWhenWeWerePassed","lastOvertakeWasClean",
                "opponentKeyForCarWeJustPassed","opponentKeyForCarThatJustPassedUs","canPlayPositionReminder",
                "lapForPositionReminder","sectorForPositionReminder","opponentAheadKey","opponentBehindKey"})
                data[name]=typeof(Position).GetField(name,System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic).GetValue(position);
            var flags=System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic;
            return new {data=data,previous_opponents_preserved=true,
                gap_samples_ahead=((List<float>)typeof(Position).GetField("gapsAhead",flags).GetValue(position)).Count,
                gap_samples_behind=((List<float>)typeof(Position).GetField("gapsBehind",flags).GetValue(position)).Count,
                mapped=state==null?null:new {
                state.SessionData.ClassPosition,state.SessionData.OverallPosition,state.SessionData.SessionStartClassPosition,
                state.SessionData.NumCarsInPlayerClass,state.SessionData.TimeDeltaFront,state.SessionData.TimeDeltaBehind,
                state.SessionData.LapsDeltaFront,state.SessionData.LapsDeltaBehind,
                state.SessionData.JustGoneGreen,state.SessionData.JustGoneGreenTime,
                highest_flag=state.SessionData.Flag.ToString(),position_yellow=Current(state).FlagData.isLocalYellow,
                expected_finish=state.SessionData.expectedFinishingPosition,opponents=state.OpponentData.Count}};
        }
    }
}
