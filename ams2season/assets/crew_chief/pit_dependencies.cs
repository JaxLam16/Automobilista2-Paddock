using System;
// Original Strategy state: updated only by the RF1 branch, never AMS2.
namespace CrewChiefV4.Events { public static partial class Strategy { public static bool pitStallIsBlocked = false; } }
namespace CrewChiefV4.Audio { public partial class AudioPlayer { public const String folderYes = "acknowledge/yes";
public const String folderNo = "acknowledge/no";
public const String dtmPitWindowOpenBackground = "dtm_pit_window_open.wav";
public const String dtmPitWindowClosedBackground = "dtm_pit_window_closed.wav";
public void setBackgroundSound(String backgroundSoundName)
        {
            this.backgroundPlayer.setBackgroundSound(backgroundSoundName);
        } } }
namespace CrewChiefV4.Events { public static partial class FrozenOrderMonitor { public const string folderKilometresPerHour = "frozen_order/kilometres_per_hour";
public const string folderMilesPerHour = "frozen_order/miles_per_hour"; } }
namespace CrewChiefV4.Events { public static partial class Battery { public static readonly string folderMinutes = "battery/minutes"; } }
