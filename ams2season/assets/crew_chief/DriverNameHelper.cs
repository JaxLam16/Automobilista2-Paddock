using FuzzySharp;
using Phonix;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;

using CrewChiefV4.Audio;
using System.Text.RegularExpressions;

[assembly: InternalsVisibleTo("UnitTest")]
/**
 * Utility class to ease some of the pain of managing driver names.
 */
namespace CrewChiefV4
{
    /// <summary>
    /// Mapping the game's driver names to sound files.
    /// </summary>
    class DriverNameHelper
    {
        public static HashSet<String> unvocalizedNames = new HashSet<string>();

        private static readonly String[] middleBits = {
            "de la", "de le", "van der", "van de", "van", "de", "da", "le", "la", "von", "di",
            "eg", "du", "el", "del", "saint", "st",
            "mac", "mc" // mac and mc may have been split off during CamelCase processing
        };

        // need a special case here for "junior" and "senior"
        // - if it's "Something Junior" then allow it, it it's "Something Somthingelse Junior" then remove it
        //
        // 2 part suffix list - remove these even if the name only has one other part
        private static readonly String[] ignored2PartSuffixes = {
            "jr", "sr", "vr", "uk", "us", "fr", "de", "sw", "es", "dk", "rp", "div", "proam", "am", "pro", "arg",
            "ii", "iii", "iv", "v"
        };

        // 3 part suffix list - remove these if the name has 2 or more other parts
        private static readonly String[] ignored3PartSuffixes = {
            "junior", "senior", "division", "group"
        };

        // provide a hint to the phonics matcher - only allow names whose first letters match these pairs
        private static readonly (string, string)[] closeFirstLetters = {
            ( "C", "K" ), ( "J", "G" ), ( "W", "V" ), ( "Z", "S" ),
            ( "Sh", "Ch" ), ( "Ch", "Sch" ), ( "Th", "T" ), ( "Ts", "S" ),
            ( "X", "Z" ), ( "Dj", "J" ) };

        private static readonly (char, char)[] numberLetterSubstitutions = {
            ( '0', 'o' ), ( '1', 'l' ), ( '3', 'b' ), ( '5', 's' ) };
        // brackets could have the same treatment
        // all the above could be in a JSON file...

        internal static Dictionary<String, String> lowerCaseRawNameToUsableName = new Dictionary<String, String>();
        internal static Dictionary<String, String> lowerCaseLastNameToFuzzyMatchedName = new Dictionary<String, String>();

        private static Dictionary<String, String> usableNamesForSession = new Dictionary<String, String>();

        private static HashSet<string> failingNames = new HashSet<string>(); 

        private static HashSet<string> suppressFuzzyMatchesOnTheseNames = new HashSet<string>();

        private static string guessedDriverNamesPath;
        private static string driverNamesPath;
        private static string soundsFolderName = null;

        public static bool useFuzzyDrivernameMatching { get; set; } = UserSettings.GetUserSettings().getBoolean("use_fuzzy_driver_name_matching");
        public static bool allowFirstNames { get; set; } = UserSettings.GetUserSettings().getBoolean("allow_first_names");
        public static bool preferFirstNames { get; set; } = UserSettings.GetUserSettings().getBoolean("prefer_first_names");

        /// <summary>
        /// Specific opponent names used by the game can be mapped to specific 
        /// sound files as well as the straight name match.
        /// There is more than one file containing mappings
        /// </summary>
        /// <param name="soundsFolderName">Where the lists are stored</param>
        /// Loads the list of driver name : sound file mappings into lowerCaseRawNameToUsableName{}
        public static void ReadDriverNameMappings(String _soundsFolderName = null)
        {
            if (soundsFolderName == null)
            {
                if (_soundsFolderName == null)
                {
                    Log.Fatal("soundsFolderName not set");
                }
                soundsFolderName = _soundsFolderName;
            }
            lowerCaseRawNameToUsableName.Clear();
            suppressFuzzyMatchesOnTheseNames.Clear();
            readRawNamesToUsableNamesFile(soundsFolderName, @"driver_names\additional_names.txt", lowerCaseRawNameToUsableName);
            readRawNamesToUsableNamesFile(soundsFolderName, @"driver_names\names.txt", lowerCaseRawNameToUsableName);
            driverNamesPath = Path.Combine(soundsFolderName, @"driver_names\names.txt");
            if (useFuzzyDrivernameMatching)
            {
                // Generating fuzzy match driver names is costly so they're stored once
                // they're guessed
                readRawNamesToUsableNamesFile(soundsFolderName, @"driver_names\guessed_names.txt", lowerCaseLastNameToFuzzyMatchedName);
                guessedDriverNamesPath = Path.Combine(soundsFolderName, @"driver_names\guessed_names.txt");
            }
        }
        public static Dictionary<string, string> getGuessedDriverNames()
        {
            Dictionary<String, String> lowerCaseGuessedNameToUsableName = new Dictionary<string, string>();
            if (useFuzzyDrivernameMatching)
            {
                readRawNamesToUsableNamesFile(soundsFolderName, @"driver_names\guessed_names.txt", lowerCaseGuessedNameToUsableName);
                // Append any ignored names
                foreach (var name in suppressFuzzyMatchesOnTheseNames)
                {
                    if (!lowerCaseGuessedNameToUsableName.ContainsKey(name))
                    {
                        lowerCaseGuessedNameToUsableName.Add(name, "");
                    }
                }
            }
            return lowerCaseGuessedNameToUsableName;
        }

        internal static void readRawNamesToUsableNamesFile(String soundsFolderName, String filename, Dictionary<String, String> lowerCaseRawNameToUsableNameToUse)
        {
            Log.Commentary("Reading driver name mappings");
            int counter = 0;
            string line;
            try
            {
                StreamReader file = new StreamReader(Path.Combine(soundsFolderName, filename));
                while ((line = file.ReadLine()) != null)
                {
                    if (line.Length > 1 && line.Trim().EndsWith(":"))
                    {
                        string suppressedName = line.Trim(':');
                        if (suppressedName.Length > 0)
                        {
                            suppressFuzzyMatchesOnTheseNames.Add(suppressedName.ToLower());
                        }
                    }
                    else
                    {
                        int separatorIndex = line.LastIndexOf(":");
                        if (separatorIndex > 0 && line.Length > separatorIndex + 1)
                        {
                            String lowerCaseRawName = line.Substring(0, separatorIndex).ToLower();
                            String usableName = line.Substring(separatorIndex + 1).Trim().ToLower();
                            if (usableName != null && usableName.Length > 0)
                            {
                                // add new or replace the existing mapping - last one wins
                                lowerCaseRawNameToUsableNameToUse[lowerCaseRawName] = usableName;
                            }
                        }
                    }
                    counter++;
                }
                file.Close();
                Log.Commentary("Read " + counter + " driver name mappings");
            }
            catch (IOException)
            {}
        }

        /// <returns>lower case name</returns>
        public static String validateAndCleanUpName(String name)
        {
            try
            {
                name = replaceObviousChars(name);
                name = cleanBrackets(name);
                if (name.Count() < 2)
                {
                    return null;
                }
                name = undoNumberSubstitutions(name);
                name = trimNumbersOffEnd(name);
                if (name.Count() < 2)
                {
                    return null;
                }
                name = trimNumbersOffStart(name);
                if (name.Count() < 2)
                {
                    return null;
                }
                Boolean allCharsValid = true;
                String charsFromName = "";
                for (int i = 0; i < name.Count(); i++)
                {
                    char ch = name[i];
                    if (Char.IsLetter(ch) || ch == ' ' || ch == '\'')
                    {
                        charsFromName = charsFromName + ch;
                    }
                    else
                    {
                        allCharsValid = false;
                    }
                }
                string validCharsOnly = null;
                // at this point we may have a name like BobSmith or garyMcShit.
                // Before we lower case it, see if there's a split hiding in the case (PascalCase or camelCase)
                if (allCharsValid && name.Trim().Count() > 1)
                {
                    validCharsOnly = SpacesFromCamel(name.Trim()).ToLower();
                }
                else if (charsFromName.Trim().Count() > 1)
                {
                    validCharsOnly = SpacesFromCamel(charsFromName.Trim()).ToLower();
                }
                return validCharsOnly;
            }
            catch (Exception)
            {
                
            }
            return null;
        }
        private static String replaceObviousChars(String name)
        {
            name = name.Replace('_', ' ');
            // be a bit careful with hypens - if it's before the first space, just remove it as
            // it's a separated firstname
            if (name.IndexOf(' ') > 0 && name.IndexOf('-') > 0 && name.IndexOf('-') < name.IndexOf(' '))
            {
                name = name.Replace("-", "");
            }
            name = name.Replace('-', ' ');
            name = name.Replace('.', ' ');
            name = name.Replace('|', ' ');
            name = name.Replace("$", "s");
            // trim the string and replace any multiple whitespace chars with a single space
            return Regex.Replace(name.Trim(), @"\s+", " ");
        }
        private static string cleanBrackets(string name)
        {
            name = Regex.Replace(name, @"\[.*\]", string.Empty);
            name = Regex.Replace(name, @"\<.*\>", string.Empty);
            name = Regex.Replace(name, @"\(.*\)", string.Empty);
            name = Regex.Replace(name, @"\{.*\}", string.Empty);
            return name.Trim();
        }
        private static String undoNumberSubstitutions(String name)
        {
            // handle letter -> number substitutions
            String nameWithLetterSubstitutions = "";
            for (int i = 0; i < name.Count(); i++)
            {
                char ch = name[i];
                Boolean changedNumberForLetter = false;
                // see if this is a letter -> number subtitution - can only handle one of these
                if (i > 0 && i < name.Count() - 1)
                {
                    if (Char.IsNumber(ch) && Char.IsLetter(name[i - 1]) && Char.IsLetter(name[i + 1]))
                    {
                        foreach (var nls in numberLetterSubstitutions)
                        {
                            if (ch == nls.Item1)
                            {
                                changedNumberForLetter = true;
                                nameWithLetterSubstitutions = nameWithLetterSubstitutions + nls.Item2;
                                break;
                            }
                        }
                    }
                }
                if (!changedNumberForLetter)
                {
                    nameWithLetterSubstitutions = nameWithLetterSubstitutions + ch;
                }
            }
            return nameWithLetterSubstitutions;
        }

        private static String trimNumbersOffEnd(String name)
        {
            // trim numbers off the end
            while (name.Count() > 2 && char.IsNumber(name[name.Count() - 1]))
            {
                name = name.Substring(0, name.Count() - 1);
            }
            return name;
        }

        private static String trimNumbersOffStart(String name)
        {
            int index = 0;
            while (name.Count() > 2 && index < name.Count() - 1 && char.IsNumber(name[index]))
            {
                name = name.Substring(index + 1);
            }
            return name;
        }

        private static Dictionary<string, string> rawDriverNameSurname = new Dictionary<string, string>();
        /// <summary>
        /// Get the driver's surname (suitable for SRE use).
        /// </summary>
        /// <param name="rawDriverName"></param>
        /// <returns>Surname or null</returns>
        public static String getUsableDriverNameForSRE(String rawDriverName)
        {
            if (!rawDriverNameSurname.ContainsKey(rawDriverName))
            {
                // this will populate the rawDriverNameSurname dict with the last name (regardless of the fuzzy match).
                // It may return a fuzzy-matched name, which we don't want - allow it to populate then use the last name from the dict
                tryToMatchDriverName(rawDriverName);
            }
            if (rawDriverNameSurname.ContainsKey(rawDriverName))
            {
                return rawDriverNameSurname[rawDriverName];
            }
            return null;
        }
        /// <summary>
        /// Get the driver's sound file if there is one.
        /// </summary>
        /// <param name="rawDriverName">From game</param>
        /// <param name="returnSurnameIfNoSoundExists"></param>
        /// <returns>Driver's sound file name or null if there isn't one.
        /// Or... the driver's surname if returnSurnameIfNoSoundExists is true.  Lovely.
        /// </returns>
        public static String getUsableDriverName(String rawDriverName, bool returnSurnameIfNoSoundExists = false)
        {
            // in most cases this method is called when we want to get a driver's sound file so if there's no sound file
            // we return null. For TTS we actually want the last name even if there's no sound
            if (rawDriverName == null || !returnSurnameIfNoSoundExists && failingNames.Contains(rawDriverName))
            {
                return null;
            }
            string matchedDriverName = null;
            if (usableNamesForSession.ContainsKey(rawDriverName))
            {   // We found a match previously
                matchedDriverName = usableNamesForSession[rawDriverName];
            }
            else if (!failingNames.Contains(rawDriverName))
            {
                // we might be asking for a driver name for TTS, in which case we want to check if we already established that this
                // driver has no match
                matchedDriverName = tryToMatchDriverName(rawDriverName);
                if (matchedDriverName == null)
                {
                    failingNames.Add(rawDriverName);
                }
                else
                {
                    try
                    {
                        usableNamesForSession.Add(rawDriverName, matchedDriverName);
                    }
                    catch (ArgumentException) // "key already added" reported by user
                    {
                        Log.Commentary($"Driver name '{rawDriverName}' already exists in usableNamesForSession");
                    }
                    catch (Exception ex)
                    {
                        Log.Exception(ex, $"Adding '{rawDriverName}' to usableNamesForSession");
                    }
                }
            }
            if (returnSurnameIfNoSoundExists && matchedDriverName == null && rawDriverNameSurname.ContainsKey(rawDriverName))
            {
                return rawDriverNameSurname[rawDriverName];
            }
            return matchedDriverName;
        }
        /// <summary>
        /// Attempts to find a standardized or mapped driver name that corresponds to the specified raw driver name.
        /// </summary>
        /// <remarks>The method first attempts to find a direct mapping for the provided raw driver name.
        /// If no direct match is found, it applies normalization and various matching strategies, including using first
        /// or last names, depending on configuration. If no match is found, the method returns null and caches the
        /// unmapped name.</remarks>
        /// <param name="rawDriverName">The raw driver name to match. Obtained from the game and may require
        /// normalization or mapping.</param>
        /// <returns>A standardized driver name if a suitable match is found; otherwise, null.</returns>
        private static string tryToMatchDriverName(string rawDriverName)
        {
            // Multiple returns from a method are usually a no-no but
            // returns are used here to reduce confusing indenting
            String matchedDriverName = null;
            if (lowerCaseRawNameToUsableName.TryGetValue(rawDriverName.ToLower(), out matchedDriverName))
            {   // Clause 1: A straight match
                Log.Commentary("Using mapped drivername " + matchedDriverName + " for raw driver name " + rawDriverName);
                rawDriverNameSurname[rawDriverName] = matchedDriverName;
                return matchedDriverName;
            }

            string lowerCaseUsableDriverName = validateAndCleanUpName(rawDriverName);
            if (lowerCaseUsableDriverName == null)
            {   // Clause 2: an error
                Log.Warning("Unable to create a usable driver name for " + rawDriverName);
                return null;
            }

            if (lowerCaseRawNameToUsableName.TryGetValue(lowerCaseUsableDriverName, out matchedDriverName))
            {   // Clause 3: Using mapped driver name for cleaned up driver name
                Log.Commentary("Using mapped driver name " + matchedDriverName + " for cleaned up raw driver name " + rawDriverName);
                rawDriverNameSurname[rawDriverName] = matchedDriverName;
                return matchedDriverName;
            }

            // Nothing mapped, see if there is a last name
            // (if not use the whole name)
            String anyFirstNamesRemoved = getUnambiguousLastName(lowerCaseUsableDriverName);
            String firstName = String.Concat(lowerCaseUsableDriverName.TakeWhile(c => Char.IsLetter(c)));
            if (preferFirstNames && firstName.Length > 0)
            {
                if ((matchedDriverName = MatchDriverName(rawDriverName, firstName, "(preferred) first ", anyFirstNamesRemoved)) != null)
                {
                    rawDriverNameSurname[rawDriverName] = firstName;
                    return matchedDriverName;
                }
            }

            if (anyFirstNamesRemoved != null && anyFirstNamesRemoved.Count() > 1)
            {
                if ((matchedDriverName = MatchDriverName(rawDriverName, anyFirstNamesRemoved, "")) != null)
                {
                    rawDriverNameSurname[rawDriverName] = anyFirstNamesRemoved;
                    return matchedDriverName;
                }
            }

            if (allowFirstNames && !Game.ACC) // ACC only shows the first name as letter e.g. J.Doe
            {
                if ((matchedDriverName = MatchDriverName(rawDriverName, firstName, "first ", anyFirstNamesRemoved)) != null)
                {
                    rawDriverNameSurname[rawDriverName] = firstName;
                    return matchedDriverName;
                }
            }

            if (anyFirstNamesRemoved != null && anyFirstNamesRemoved.Count() > 1)
            {
                // Clause 8: Using unmapped driver last name for raw driver name
                Log.Commentary("Using unvocalised driver (last) name " + anyFirstNamesRemoved + " for raw driver name " + rawDriverName);
                rawDriverNameSurname[rawDriverName] = anyFirstNamesRemoved;
                unvocalizedNames.Add(anyFirstNamesRemoved);
                return null;
            }

            Log.Commentary("Using unvocalised drivername " + lowerCaseUsableDriverName + " for raw driver name " + rawDriverName);
            rawDriverNameSurname[rawDriverName] = lowerCaseUsableDriverName;
            unvocalizedNames.Add(lowerCaseUsableDriverName);
            return null;
        }

        private static string MatchDriverName(in string rawDriverName, in string driverName, in string ifFirstName, in string lastName = null)
        {
            if (string.IsNullOrEmpty(rawDriverName) || string.IsNullOrEmpty(driverName))
            {   // Trap exception caused by null driverName reported by user
                // after this code had been used for years already!
                Log.Error($"rawDriverName '{rawDriverName}' driverName '{driverName}'");
                return null;
            }
            string matchedDriverName = null;
            if (SoundCache.availableDriverNames.Contains(driverName) || SoundCache.availableDriverNamesForTrainee.Contains(driverName))
            {
                // Clause 5: We have a sound file for the driver name
                Log.Commentary($"Using driver name {driverName} for driver raw {ifFirstName}name {rawDriverName} {lastName}");
                rawDriverNameSurname[rawDriverName] = driverName;
                return driverName;
            }

            if (lowerCaseRawNameToUsableName.TryGetValue(driverName.ToLower(), out matchedDriverName))
            {
                // Clause 6: Using mapped driver name for cleaned up driver name
                Log.Commentary($"Using mapped driver name {matchedDriverName} for cleaned up driver {ifFirstName}name {driverName} {lastName}");
                rawDriverNameSurname[rawDriverName] = matchedDriverName;
                return matchedDriverName;
            }

            if (lowerCaseLastNameToFuzzyMatchedName.TryGetValue(driverName.ToLower(), out matchedDriverName))
            {
                // Clause 4: we have a saved fuzzy match
                Log.Commentary($"Using fuzzy mapped driver name {matchedDriverName} for cleaned up driver {ifFirstName}name {driverName} {lastName}");
                rawDriverNameSurname[rawDriverName] = driverName;
                return matchedDriverName;
            }

            var fuzzyDriverLastName = MatchForOpponentName(driverName);
            if (fuzzyDriverLastName.matched)
            {
                matchedDriverName = fuzzyDriverLastName.driverNameMatches[0].ToLower();
                // Clause 7: Using fuzzy matched driver name for cleaned up driver name
                if (guessedDriverNamesPath != null) Utilities.AddLinesToFile(guessedDriverNamesPath, new List<string> { $"{driverName}:{matchedDriverName}" });
                Log.Commentary($"Adding fuzzy mapping for name {driverName}:{matchedDriverName}");
                // add the newly-mapped name to the list
                lowerCaseLastNameToFuzzyMatchedName[driverName] = matchedDriverName;
                rawDriverNameSurname[rawDriverName] = driverName;
                return matchedDriverName;
            }

            return matchedDriverName;
        }

        // For unit testing
        internal static int GetSize_usableNamesForSession()
        {
            return usableNamesForSession.Count;
        }

        public struct FuzzyDriverNameResult
        {
            public List<string> driverNameMatches;
            public int matchLevel;
            public bool matched;
            public int fuzzyConfidence;
        }
        private static string[] getAvailableNamesWithCloseFirstLetters(string driverName, string[] availableDriverNames)
        {
            driverName = char.ToUpper(driverName[0]) + driverName.Substring(1);
            List<string> names = new List<string>();
            int minNameLength = driverName.Length / 2;
            int maxNameLength = driverName.Length * 2;
            foreach (string name in availableDriverNames)
            {
                if (name.Length > minNameLength && name.Length < maxNameLength &&
                        (name[0] == driverName[0] || firstLettersCloseEnough(driverName, name)))
                {
                    names.Add(name);
                }
            }
            return names.ToArray<string>();
        }
        public static FuzzyDriverNameResult MatchForOpponentName(string driverName, string[] availableDriverNames = null)
        {
            if (!useFuzzyDrivernameMatching || suppressFuzzyMatchesOnTheseNames.Contains(driverName.ToLower()))
            {
                var emptyResult = new FuzzyDriverNameResult();
                emptyResult.driverNameMatches = new List<string>();
                emptyResult.matched = false;
                return emptyResult;
            }
            if (availableDriverNames == null)
            {
                availableDriverNames = SoundCache.availableDriverNamesForUIAsArray; // files in AppData\Local\CrewChiefV4\sounds\driver_names
            }
            return PhonixFuzzyMatches(driverName, getAvailableNamesWithCloseFirstLetters(driverName, availableDriverNames), 1);
        }
        private static void writeGuessedDriverName(string driverName, string wavFileName)
        {
            Utilities.AddLinesToFile(guessedDriverNamesPath,
                                        new List<string> { $"{driverName}:{wavFileName}" });
        }
        private const int numberOfPhonixMethods = 4;
        public static FuzzyDriverNameResult PhonixFuzzyMatches(string driverName, string[] availableDriverNames, int numberOfNamesRqd = 1)
        {
            bool multipleMatchesRequested = numberOfNamesRqd > 1;
            FuzzyDriverNameResult result = new FuzzyDriverNameResult();
            result.driverNameMatches = new List<string>();
            result.matched = false;
            if (driverName.Length < 2)
            {
                return result;
            }
            var soundex = new Soundex();
            var doubleMetaphone = new DoubleMetaphone();
            var matchRatingApproach = new MatchRatingApproach();
            var caverPhone = new CaverPhone();
            var metaphone = new Metaphone();

            // keep track of what we've matched so we don't add the same result twice
            HashSet<string> allMatches = new HashSet<string>();

            // Try to find a name where at least 2 algorithms find a match
            for (int matchesThreshold = numberOfPhonixMethods; matchesThreshold > 1; matchesThreshold--)
            {
                List<string> matchesForThisThreshold = new List<string>();
                foreach (var availableName in availableDriverNames)
                {
                    string[] array = new string[] { driverName, availableName };
                    int matches = 0;
                    try
                    {
                        if (soundex.IsSimilar(array))
                        {
                            matches++;
                        }
                        if (doubleMetaphone.IsSimilar(array))
                        {
                            matches++;
                        }
                        //if (matchRatingApproach.IsSimilar(array))  Throws IndexOutOfRange a lot
                        //{
                        //    matches++;
                        //}
                        if (availableName.Length > 2 && driverName.Length > 2)
                        {
                            try
                            {
                                if (caverPhone.IsSimilar(array))
                                {
                                    matches++;
                                }
                            }
                            catch (Exception)
                            {
                                // CaverPhone can throw ArgumentOutOfRangeException on non-standard character combinations
                            }
                        }
                        if (metaphone.IsSimilar(array))
                        {
                            matches++;
                        }
                    }
                    catch (Exception ex)
                    {
                        Log.Debug(() => "Phonix dll exception comparing \"" + driverName + "\" with \"" + availableName + "\": " + ex.Message);
                    }
                    if (matches >= matchesThreshold && allMatches.Add(availableName))
                    {
                        // multiple match mode - add this match to the set and stop looking if we have enough
                        if (multipleMatchesRequested)
                        {
                            result.driverNameMatches.Add(availableName);
                            result.matched = true;
                            result.matchLevel = matches;
                            if (result.driverNameMatches.Count > numberOfNamesRqd)
                            {
                                // we have enough, stop looking and return - no need to do another run at a lower threshold
                                return result;
                            }
                        }
                        else
                        {
                            matchesForThisThreshold.Add(availableName);
                        }
                    }
                }
                // single match mode - get the best we have and stop looking
                if (!multipleMatchesRequested && matchesForThisThreshold.Count() > 0)
                {
                    // fuzzy match threshold can be more lenient when we have a great phonic match
                    int matchScoreThreshold = matchesThreshold == numberOfPhonixMethods ? 60 : matchesThreshold == numberOfPhonixMethods - 1 ? 72 : 75;
                    // get the best match from what we have, if it's good enough stop.
                    // "good enough" means it has to have a decent fuzzy match, and it can't be massively longer or shorter than the original
                    var fuzzyMatchesForThisThreshold = Process.ExtractTop(driverName, matchesForThisThreshold.ToArray(), limit: 1);
                    if (fuzzyMatchesForThisThreshold.Count() > 0 && fuzzyMatchesForThisThreshold.First().Score > matchScoreThreshold
                        && Math.Abs(fuzzyMatchesForThisThreshold.First().Value.Length - driverName.Length) < 5)
                    {
                        result.driverNameMatches.Add(fuzzyMatchesForThisThreshold.First().Value);
                        result.matched = true;
                        result.matchLevel = matchesThreshold;
                        result.fuzzyConfidence = fuzzyMatchesForThisThreshold.First().Score;
                        break;
                    }
                }
            }
            return result;
        }

        public static void writeGuessedDriverNames(Dictionary<string, string> guessedOpponentNames)
        {
            File.Delete(guessedDriverNamesPath);
            foreach (var driver in guessedOpponentNames.Keys)
            {
                Utilities.AddLinesToFile(guessedDriverNamesPath,
                                            new List<string> { $"{driver}:{guessedOpponentNames[driver]}" });
            }
        }
        public static void EditGuessedNames()
        {
            var process = new System.Diagnostics.Process
            {
                StartInfo = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "notepad.exe",
                    Arguments = guessedDriverNamesPath
                }
            };
            process.Start();
            process.WaitForExit();
        }

        public static void EditNames()
        {
            System.Diagnostics.Process.Start("notepad.exe", driverNamesPath);
        }

        public static HashSet<String> getUsableDriverNameSounds(List<String> rawDriverNames)
        {
            usableNamesForSession.Clear();
            foreach (String rawDriverName in rawDriverNames)
            {
                getUsableDriverName(rawDriverName);                
            }
            return usableNamesForSession.Values.ToHashSet();
        }
        public static List<String> getUsableDriverNamesForSRE(List<String> rawDriverNames)
        {
            List<string> namesForSre = new List<string>();
            foreach (String rawDriverName in rawDriverNames)
            {
                namesForSre.Add(getUsableDriverNameForSRE(rawDriverName));
            }
            return namesForSre;
        }
        private static bool firstLettersCloseEnough(string s1, string s2)
        {
            foreach (var pairs in closeFirstLetters)
            {
                if ((s1.StartsWith(pairs.Item1) && s2.StartsWith(pairs.Item2)) ||
                    (s1.StartsWith(pairs.Item2) && s2.StartsWith(pairs.Item1)))
                {
                    return true;
                }
            }
            return false;
        }
        /// <summary>
        /// See if there is a last name (if not use the whole name)
        /// </summary>
        internal static String getUnambiguousLastName(String fullName)
        {
            if (fullName.Count(Char.IsWhiteSpace) == 0)
            {
                return fullName;
            }
            else
            {
                String[] fullNameSplit = null;
                bool gotFromMiddleBit = false;
                foreach (String middleBit in middleBits)
                {
                    // if we have a something van der somethingelse, we want this to be { "something", "van der", "somethingelse" }
                    string middleBitWithSpaces = " " + middleBit + " ";
                    if (fullName.Contains(middleBitWithSpaces))
                    {
                        string start = fullName.Substring(0, fullName.IndexOf(middleBitWithSpaces));
                        string end = fullName.Substring(fullName.IndexOf(middleBitWithSpaces) + middleBitWithSpaces.Length);
                        List<string> splitList = new List<string>();
                        splitList.AddRange(start.Split(' '));
                        splitList.Add(middleBit);
                        splitList.AddRange(end.Split(' '));
                        fullNameSplit = splitList.ToArray();
                        gotFromMiddleBit = true;
                        break;
                    }
                }
                if (!gotFromMiddleBit)
                {
                    fullNameSplit = trimEmptyStrings(fullName.Split(' '));
                }
                // if the last part is 'uk' or something and there are 2 or more parts, lose the 'uk'.
                if (fullNameSplit.Length > 1 && ignored2PartSuffixes.Contains(fullNameSplit[fullNameSplit.Count() - 1]))
                {
                    fullNameSplit = fullNameSplit.Take(fullNameSplit.Count() - 1).ToArray();
                }
                // Lose the 'junior' only if there are 3 or more parts (note this is done separately so we fix cases
                // like "jim britton junior uk"
                if (fullNameSplit.Length > 2 && ignored3PartSuffixes.Contains(fullNameSplit[fullNameSplit.Count() - 1]))
                {
                    fullNameSplit = fullNameSplit.Take(fullNameSplit.Count() - 1).ToArray();
                }
                if (fullNameSplit.Count() == 1)
                {
                    return fullNameSplit[0];
                }
                if (fullNameSplit.Count() == 2)
                {
                    if (fullNameSplit[1].Count() > 1)
                    {
                        // "something somthingelse", just return "somethingelse"
                        return fullNameSplit[1];
                    }
                    else
                    {
                        // second part is 0 or 1 char, return the first part
                        return fullNameSplit[0];
                    }
                }
                else if (middleBits.Contains(fullNameSplit[fullNameSplit.Count() - 2]))
                {
                    return fullNameSplit[fullNameSplit.Count() - 2] + " " + fullNameSplit[fullNameSplit.Count() - 1];
                }
                else if (fullNameSplit[fullNameSplit.Count() - 2].Length == 1)
                {
                    return fullNameSplit[fullNameSplit.Count() - 1];
                }
                else if (fullNameSplit.Length > 3 && middleBits.Contains((fullNameSplit[fullNameSplit.Count() - 3] + " " + fullNameSplit[fullNameSplit.Count() - 2])))
                {
                    return fullNameSplit[fullNameSplit.Count() - 3] + " " + fullNameSplit[fullNameSplit.Count() - 2] + " " + fullNameSplit[fullNameSplit.Count() - 1];
                }
                // if there are more than 2 names, and the second to last name isn't one of the common middle bits, 
                // use the last part
                return fullNameSplit[fullNameSplit.Count() - 1];
            }
        }
        private static string SpacesFromCamel(string value)
        {
            if (value.Length > 2)
            {
                var result = new List<char>();
                char[] array = value.ToCharArray();
                result.Add(array[0]);
                for (int i = 1; i < array.Length - 1; i++)
                {
                    var prevItem = array[i - 1];
                    var item = array[i];
                    var nextItem = array[i + 1];
                    if (char.IsUpper(item)
                        && nextItem != ' ' && prevItem != ' '
                        && char.IsLower(prevItem)
                        && result.Count > 0)
                    {
                        result.Add(' ');
                    }
                    result.Add(item);
                    if (i == array.Length - 2)
                    {
                        result.Add(nextItem);
                    }
                }
                return new string(result.ToArray());
            }
            return value;
        }
        private static String[] trimEmptyStrings(String[] strings)
        {
            List<String> trimmedList = new List<string>();
            foreach (String str in strings) {
                if (str.Trim().Length > 0)
                {
                    trimmedList.Add(str.Trim());
                }
            }
            return trimmedList.ToArray();
        }

        public static void dumpUnvocalizedNames()
        {
            HashSet<String> existingNamesInFile = getNamesAlreadyInFile(DataFiles.unvocalized_driver_names);
            existingNamesInFile.UnionWith(unvocalizedNames);
            List<String> namesToAdd = new List<String>(existingNamesInFile);
            namesToAdd.RemoveAll(alreadyRecorded => SoundCache.availableDriverNames.Contains(alreadyRecorded));
            namesToAdd.Sort();
            Utilities.AddLinesToFile(DataFiles.unvocalized_driver_names, namesToAdd);
        }

        private static HashSet<String> getNamesAlreadyInFile(String fullFilePath)
        {
            HashSet<String> names = new HashSet<string>();
            StreamReader file = null;
            try
            {
                file = new StreamReader(fullFilePath);
                String line;
                while ((line = file.ReadLine()) != null)
                {
                    names.Add(line.Trim());
                }
            }
            catch (Exception)
            {
                // ignore - file doesn't exist so it'll be created
            }
            finally
            {
                if (file != null)
                {
                    file.Close();
                }
            }
            return names;
        }
    }
}
