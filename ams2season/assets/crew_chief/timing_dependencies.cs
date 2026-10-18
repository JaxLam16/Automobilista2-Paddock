using System;
namespace CrewChiefV4.R3E {
    public class R3ERatingData { public float reputation;public int racesCompleted; }
    public static class R3ERatings { public static R3ERatingData getRatingForUserId(int id) {
        throw new NotSupportedException("R3E ratings unavailable in this AMS2-only host"); } }
}
namespace CrewChiefV4 { public static partial class DataFiles {
    public static string iracing_reputations { get { throw new NotSupportedException("iRacing reputation files unavailable in AMS2 host"); } }
} }
namespace CrewChiefV4.Events { public static partial class FrozenOrderMonitor {
public const string folderAllowGuyBehindToPass = "frozen_order/allow_guy_behind_to_pass";
} }
