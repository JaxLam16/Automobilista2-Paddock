using System;
using System.Collections.Generic;

namespace CrewChiefV4
{
    [Flags]
    public enum GameEnum : ulong
    {
        ACC                 = 1 << 0,
        AMS2                = 1 << 1,
        AMS2_NETWORK        = 1 << 2,
        ASSETTO_32BIT       = 1 << 3,
        ASSETTO_64BIT       = 1 << 4,
        ASSETTO_128CARS     = 1 << 5,
        ASSETTO_64BIT_RALLY = 1 << 6,
        ASSETTO_EVO         = 1 << 7,
        ASSETTO_PRO         = 1 << 8,
        DIRT                = 1 << 9,
        DIRT_2              = 1 << 10,
        F1_2018             = 1 << 11,
        F1_2019             = 1 << 12,
        F1_2020             = 1 << 13,
        F1_2021             = 1 << 14,
        F1_2022             = 1 << 15,
        F1_2023             = 1 << 16,
        GTR2                = 1 << 17,
        IRACING             = 1 << 18,
        LMU                 = 1 << 19,
        PCARS2              = 1 << 20,
        PCARS2_NETWORK      = 1 << 21,
        PCARS3              = 1 << 22,
        PCARS_32BIT         = 1 << 23,
        PCARS_64BIT         = 1 << 24,
        PCARS_NETWORK       = 1 << 25,
        RACE_ROOM           = 1 << 26,
        RBR                 = 1 << 27,
        RF1                 = 1 << 28,
        RF2_64BIT           = 1 << 29,
        PMR                 = 1 << 30,
        LFS                 = 1UL << 31,

        // the bitshift operator always only can bitshift int values so do these special values manually
        UNKNOWN             = 0b00100000_00000000_00000000_00000000_00000000_00000000_00000000_00000000,
        NONE                = 0b01000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000,
                                /* NONE allows CC macros to run when an unsupported game is being played, it's selectable from the Games list */
        ANY                 = 0b10000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000
                                /* ANY allows CC macros to be defined that apply to all supported games, it's only selectable from the macro UI */
}
    /// <summary>
    /// GameType groups multiple GameEnum values together.
    /// </summary>
    public enum GameType : ulong
    {
        ACC             = 1 << 0,
        AMS2            = 1 << 1,
        ASSETTO         = 1 << 2,
        ASSETTO_RALLY   = 1 << 3,
        ASSETTO_EVO     = 1 << 4,
        DIRT            = 1 << 5,
        DIRT2           = 1 << 6,
        F1_20S          = 1 << 7,
        GTR2            = 1 << 8,
        IRACING         = 1 << 9,
        LMU             = 1 << 10,
        PCARS2          = 1 << 11,
        PCARS3          = 1 << 12,
        PCARS           = 1 << 13,
        RACE_ROOM       = 1 << 14,
        RBR             = 1 << 15,
        RF1             = 1 << 16,
        RF2             = 1 << 17,
        RF2_LMU         = 1 << 18,
        PMR             = 1 << 19,
        LFS             = 1 << 20,

        // the bitshift operator always only can bitshift int values so do these special values manually
        UNKNOWN         = 0b00100000_00000000_00000000_00000000_00000000_00000000_00000000_00000000,
    }
    public static class Game
    {
        static GameEnum _game = GameEnum.UNKNOWN;
        static GameType _gameType = GameType.UNKNOWN;
        static readonly Dictionary<GameEnum, GameType> gameEnumToGameType = new Dictionary<GameEnum, GameType>()
        {
            { GameEnum.ACC,             GameType.ACC },
            { GameEnum.AMS2,            GameType.AMS2 },
            { GameEnum.AMS2_NETWORK,    GameType.AMS2 },
            { GameEnum.ASSETTO_32BIT,   GameType.ASSETTO },
            { GameEnum.ASSETTO_64BIT,   GameType.ASSETTO },
            { GameEnum.ASSETTO_128CARS, GameType.ASSETTO },
            { GameEnum.ASSETTO_PRO,     GameType.ASSETTO },
            { GameEnum.ASSETTO_EVO,     GameType.ASSETTO_EVO },
            { GameEnum.DIRT,            GameType.DIRT },
            { GameEnum.DIRT_2,          GameType.DIRT2 },
            { GameEnum.F1_2018,         GameType.F1_20S },
            { GameEnum.F1_2019,         GameType.F1_20S },
            { GameEnum.F1_2020,         GameType.F1_20S },
            { GameEnum.F1_2021,         GameType.F1_20S },
            { GameEnum.F1_2022,         GameType.F1_20S },
            { GameEnum.F1_2023,         GameType.F1_20S },
            { GameEnum.GTR2,            GameType.GTR2 },
            { GameEnum.IRACING,         GameType.IRACING },
            { GameEnum.LMU,             GameType.LMU },
            { GameEnum.PCARS2,          GameType.PCARS2 },
            { GameEnum.PCARS2_NETWORK,  GameType.PCARS2 },
            { GameEnum.PCARS3,          GameType.PCARS3 },
            { GameEnum.PCARS_32BIT,     GameType.PCARS },
            { GameEnum.PCARS_64BIT,     GameType.PCARS },
            { GameEnum.PCARS_NETWORK,   GameType.PCARS },
            { GameEnum.RACE_ROOM,       GameType.RACE_ROOM },
            { GameEnum.RBR,             GameType.RBR },
            { GameEnum.RF1,             GameType.RF1 },
            { GameEnum.RF2_64BIT,       GameType.RF2 },
            { GameEnum.PMR,             GameType.PMR },
            { GameEnum.LFS,             GameType.LFS }
        };
        public static GameEnum game { 
            get {
                if (_game == GameEnum.UNKNOWN)
                {
                    var xx = GameDefinition.getGameDefinitionForCommandLineName(
                        UserSettings.GetUserSettings().getString("last_game_definition"));
                    _game = xx != null ? xx.gameEnum : GameEnum.UNKNOWN;
                }
                return _game; }
            set { 
                _game = value;
                _gameType = gameEnumToGameType.ContainsKey(_game) ? gameEnumToGameType[_game] : GameType.UNKNOWN;
            }
        }
        public static GameType gameType
        {
            get
            {
                return _gameType;
            }
        }

        public static bool ACC                 => game == GameEnum.ACC;
        public static bool AMS2                => game == GameEnum.AMS2;
        public static bool AMS2_NETWORK        => game == GameEnum.AMS2_NETWORK;
        public static bool ASSETTO_32BIT       => game == GameEnum.ASSETTO_32BIT;
        public static bool ASSETTO_64BIT       => game == GameEnum.ASSETTO_64BIT;
        public static bool ASSETTO_64BIT_RALLY => game == GameEnum.ASSETTO_64BIT_RALLY;
        public static bool ASSETTO_EVO         => game == GameEnum.ASSETTO_EVO;
        public static bool ASSETTO_PRO         => game == GameEnum.ASSETTO_PRO;
        public static bool DIRT                => game == GameEnum.DIRT;
        public static bool DIRT_2              => game == GameEnum.DIRT_2;
        public static bool F1_2018             => game == GameEnum.F1_2018;
        public static bool F1_2019             => game == GameEnum.F1_2019;
        public static bool F1_2020             => game == GameEnum.F1_2020;
        public static bool F1_2021             => game == GameEnum.F1_2021;
        public static bool F1_2022             => game == GameEnum.F1_2022;
        public static bool F1_2023             => game == GameEnum.F1_2023;
        public static bool GTR2                => game == GameEnum.GTR2;
        public static bool IRACING             => game == GameEnum.IRACING;
        public static bool LMU                 => game == GameEnum.LMU;
        public static bool PCARS2              => game == GameEnum.PCARS2;
        public static bool PCARS2_NETWORK      => game == GameEnum.PCARS2_NETWORK;
        public static bool PCARS3              => game == GameEnum.PCARS3;
        public static bool PCARS_32BIT         => game == GameEnum.PCARS_32BIT;
        public static bool PCARS_64BIT         => game == GameEnum.PCARS_64BIT;
        public static bool PCARS_NETWORK       => game == GameEnum.PCARS_NETWORK;
        public static bool PMR                 => game == GameEnum.PMR;
        public static bool RACE_ROOM           => game == GameEnum.RACE_ROOM;
        public static bool RBR                 => game == GameEnum.RBR;
        public static bool RF1                 => game == GameEnum.RF1;
        public static bool RF2_64BIT           => game == GameEnum.RF2_64BIT;
        public static bool LFS                 => game == GameEnum.LFS;
        public static bool UNKNOWN             => game == GameEnum.UNKNOWN;
        public static bool NONE                => game == GameEnum.NONE;
        public static bool ANY                 => game == GameEnum.ANY;

        public static bool ASSETTO1            => gameType == GameType.ASSETTO;
        public static bool PCARS1              => gameType == GameType.PCARS;
        public static bool PCARS_2_3           => (gameType & (GameType.PCARS2 | GameType.PCARS3)) != 0;
        public static bool PCARS_AMS2          => (gameType & (GameType.PCARS | GameType.PCARS2 | GameType.PCARS3 | GameType.AMS2)) != 0;
        public static bool RF2_LMU             => (gameType & (GameType.RF2 | GameType.LMU)) != 0;
        public static bool F1_20S              => gameType == GameType.F1_20S;

        public static bool HAS_OVALS           => (gameType & (GameType.ACC | GameType.LMU)) == 0;
        public static bool HAS_WEATHER_FORECAST => (gameType & (GameType.ACC | GameType.RF2 | GameType.LMU)) != 0;
        public static bool DEFINES_OVALS       => gameType == GameType.IRACING; // These games define oval tracks as a separate track type, no need for trackLandmarksData.JSON to define them as such.
    }

    /// <summary>
    /// Workarounds for games that have bugs or missing features.
    /// These MAY be a temporary solution until the game developers fix the issues.
    /// </summary>
    public static class GameWorkArounds
    {
        public static bool LMU_FuelMultiplier  => Game.LMU;   // LMU doesn't report FuelMultiplier
        public static bool LMU_PitstopGoGoGo   => Game.LMU;   // LMU sets IsPitCrewDone as soon as car stops.
        public static bool ACE_TimedRace => Game.ASSETTO_EVO; // ACE Static.is_timed_race is flipped
    }
}
