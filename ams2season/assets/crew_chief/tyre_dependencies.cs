// Device-free topic values and unreachable iRacing boundary for the original AMS2 tyre event.
using System;using System.Collections.Generic;using CrewChiefV4.GameState;using CrewChiefV4.Events;
namespace CrewChiefV4.iRacing { public static class iRacingGameStateMapper {
public static List<CornerData.EnumWithThresholds> tyreWearThresholds { get {
throw new NotSupportedException("iRacing thresholds are unreachable in the AMS2 host"); } } } }
namespace CrewChiefV4.UserInterface.TopicWindows {
public static class TopicWindowBrakes {public static float FL,FR,RL,RR;
public static void SetFLTemp(float v){FL=v;}public static void SetFRTemp(float v){FR=v;}
public static void SetRLTemp(float v){RL=v;}public static void SetRRTemp(float v){RR=v;}}
public static class TopicWindowTyres {public static float FL,FR,RL,RR;
public static void SetFLTemp(float v){FL=v;}public static void SetFRTemp(float v){FR=v;}
public static void SetRLTemp(float v){RL=v;}public static void SetRRTemp(float v){RR=v;}}}
namespace CrewChiefV4 { public sealed partial class SpeechRecogniser { public static string[] HOW_MANY_LAPS_ON_TYRE_SET=new[]{"how many laps on tire set","how many laps are on tire set"}; } }
