using System;
using System.Collections.Generic;
using System.Linq;

namespace CrewChiefV4
{

    public partial class GameDefinition
    {
        public bool hasPlugin => !string.IsNullOrEmpty(pluginDirectory);

        // Also add any new GameDefinitions to AllGameDefinitions
        private static readonly string showOnlyTheseGames = UserSettings.GetUserSettings().getString("limit_available_games");

        private static List<GameDefinition> filterAvailableGames(List<GameDefinition> gameDefinitions)
        {
            if (showOnlyTheseGames != null && showOnlyTheseGames.Length > 0)
            {
                try
                {
                    string[] filters = showOnlyTheseGames.Split(',');
                    HashSet<GameDefinition> filtered = new HashSet<GameDefinition>();
                    bool anyMatch = false;
                    foreach (string filterItem in filters)
                    {
                        Boolean matched = false;
                        String filter = filterItem.Trim();
                        if (filter.Length > 0)
                        {
                            foreach (GameDefinition gameDefinition in gameDefinitions)
                            {
                                if (filterItem.Length > 0 && (
                                    gameDefinition.friendlyName.Equals(filter) || gameDefinition.lookupName.Equals(filter) || gameDefinition.commandLineName.Equals(filter)))
                                {
                                    filtered.Add(gameDefinition);
                                    matched = true;
                                    anyMatch = true;
                                    break;
                                }
                            }
                            if (!matched)
                            {
                                // no match for this filter, see if we can do an approx match
                                string filterLower = filter.ToLower();
                                foreach (GameDefinition gameDefinition in gameDefinitions)
                                {
                                    if (filterItem.Length > 0 && gameDefinition.alternativeFilterNames != null
                                        && gameDefinition.alternativeFilterNames.Contains(filterLower))
                                    {
                                        filtered.Add(gameDefinition);
                                        matched = true;
                                        anyMatch = true;
                                        Log.Warning($"Limit available games filter '{filter}' should be '{gameDefinition.lookupName}'");
                                        break;
                                    }
                                }
                                if (!matched && 
                                    filter != "ASSETTO_PRO" &&
                                    filter != "ASSETTO_EVO" &&
                                    filter != "PMR" &&
                                    filter != "RACE_REMASTER")
                                {
                                    Log.DontSpam($"Limit available games filter term '{filter}' not recognised", 30).Error();
                                }
                            }
                        }
                    }
                    if (anyMatch)
                    {
                        return filtered.ToList();
                    }
                }
                catch (Exception e) { Log.Exception(e); }
            }
            return gameDefinitions;
        }

        public static List<GameDefinition> AllGameDefinitions => new List<GameDefinition>
                {
                   acc,
                   ams2,
                   arcaSimRacing,
                   assetto128cars,
                   assetto32Bit,
                   assetto64Bit,
                   assetto64BitRallyMode,
                   assettoEvo,
                   //assettoPro,
                   automobilista,
                   dirt,
                   dirt2,
                   f1_2018,
                   f1_2019,
                   f1_2020,
                   f1_2021,
                   f1_2022,
                   f1_2023,
                   ftruck,
                   gameStockCar,
                   gtr2,
                   iracing,
                   lfs,
                   lmu,
                   marcas,
                   none,
                   pCars2,
                   // pCars2Network,   TODO: reinstate this when it actually works
                   pCars3,
                   pCars32Bit,
                   pCars64Bit,
                   pCarsNetwork,
                   pmr,
                   raceRemaster,
                   raceRoom,
                   rbr,
                   rFactor1,
                   rfactor2_64bit
                };

        public static List<GameDefinition> getAllAvailableGameDefinitions(Boolean includeAllSupportedGamesEntry)
        {
            List<GameDefinition> definitions = AllGameDefinitions;
            if (includeAllSupportedGamesEntry) definitions.Add(any);
            return filterAvailableGames(definitions);
        }

        public static GameDefinition getGameDefinitionForFriendlyName(String friendlyName)
        {
            List<GameDefinition> definitions = getAllAvailableGameDefinitions(true);
            foreach (GameDefinition def in definitions)
            {
                if (String.Equals(def.friendlyName, friendlyName, StringComparison.OrdinalIgnoreCase))
                {
                    return def;
                }
            }
            return null;
        }

        public static GameDefinition getGameDefinitionForCommandLineName(String commandLineName)
        {
            List<GameDefinition> definitions = getAllAvailableGameDefinitions(false);
            foreach (GameDefinition def in definitions)
            {
                if (def.commandLineName == commandLineName)
                {
                    return def;
                }
            }
            return null;
        }

        public static String[] getGameDefinitionFriendlyNames()
        {
            List<String> names = new List<String>();
            foreach (GameDefinition def in getAllAvailableGameDefinitions(false))
            {
                names.Add(def.friendlyName);
            }
            names.Sort();
            return names.ToArray();
        }

        public static List<String> getAllGameDefinitionCommandLineNames()
        {
            List<String> names = new List<String>();
            foreach (GameDefinition def in AllGameDefinitions)
            {
                names.Add(def.commandLineName);
            }
            names.Remove("NONE"); // Don't show NONE in the list of command line names
            names.Sort();
            return names;
        }

        public String lookupName;
        public GameEnum gameEnum;
        public String friendlyName;
        public String macroEditorName;
        public readonly CrewChief.RacingType racingType = CrewChief.RacingType.Undefined;
        public String processName;
        public String spotterName;
        public String gameStartCommandProperty;
        public String gameStartCommandOptionsProperty;
        public String gameStartEnabledProperty;
        public String gameInstallPathPropertyName;
        public String gameInstallDirectory;  // Not the full path, only used by games that need to install plugins.
        public String pluginDirectory;       // Used to source plugin if there is one.
        public String[] alternativeProcessNames;
        public String[] alternativeFilterNames;
        public Boolean allowsUserCreatedCars;
        public String commandLineName;

        public enum FuelMultiplierType
        {
            /// <summary>
            /// PCARS3 doesn't have fuel consumption
            /// </summary>
            None,
            
            /// <summary>
            /// Game doesn't have a fuel multiplier, use 1
            /// </summary>
            Fixed,
            
            /// <summary>
            /// rFactor 2 provides the multiplier in shared memory, show it
            /// </summary>
            SharedByGame,
            
            /// <summary>
            /// Game only provides whether fuel consumption is a factor but
            /// doesn't provide the multiplier (if any) so if it's not 0
            /// use the value provided by the user
            /// </summary>
            Variable
        }
        public FuelMultiplierType fuelMultiplierType;

        public GameDefinition(GameEnum gameEnum,
            String lookupName,
            String commandLineName,
            String processName,
            String spotterName,
            String gameStartCommandProperty,
            String gameStartCommandOptionsProperty,
            String gameStartEnabledProperty,
            Boolean allowsUserCreatedCars,
            String gameInstallPathPropertyName,
            String gameInstallDirectory,
            String pluginDirectory,
            String macroEditorName,
            CrewChief.RacingType racingType,
            FuelMultiplierType fuelMultiplierType,
            String[] alternativeProcessNames,
            String[] approxFilterNames
        )
        {
            this.gameEnum = gameEnum;
            this.lookupName = lookupName;
            this.friendlyName = this.macroEditorName = macroEditorName;
            this.processName = processName;
            this.spotterName = spotterName;
            this.gameStartCommandProperty = gameStartCommandProperty;
            this.gameStartCommandOptionsProperty = gameStartCommandOptionsProperty;
            this.gameStartEnabledProperty = gameStartEnabledProperty;
            this.alternativeProcessNames = alternativeProcessNames;
            this.gameInstallPathPropertyName = gameInstallPathPropertyName;
            this.gameInstallDirectory = gameInstallDirectory;
            this.pluginDirectory = pluginDirectory;
            this.allowsUserCreatedCars = allowsUserCreatedCars;
            this.fuelMultiplierType = fuelMultiplierType;
            this.racingType = racingType;
            this.commandLineName = commandLineName == null ? gameEnum.ToString() : commandLineName;
            this.alternativeFilterNames = approxFilterNames;
        }
        /// <summary>
        /// ctor to initialise gameDefinition
        /// </summary>
        public GameDefinition()
        {
            racingType = CrewChief.RacingType.Undefined;
        }
        public bool HasAnyProcessNameAssociated()
        {
            return processName != null
                || (alternativeProcessNames != null && alternativeProcessNames.Length > 0);
        }
    }
}
