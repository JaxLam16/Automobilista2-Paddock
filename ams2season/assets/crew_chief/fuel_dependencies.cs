using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using CrewChiefV4.GameState;
using CrewChiefV4.Events;
using CrewChiefV4.Audio;
using Newtonsoft.Json;
using static CrewChiefV4.GameDefinition;
namespace CrewChiefV4 { public partial class CrewChief { public class FuelMultiplier
        {
            public bool showMultiplier { get; private set; }
            private readonly FuelMultiplierType _fuelMultiplierType;

            public FuelMultiplier(FuelMultiplierType fuelMultiplierType)
            {
                _fuelMultiplierType = fuelMultiplierType;
                _fuelMultiplier = 0; // to initialise numericUpDownfuelMultiplier
                multiplier = 1; // until we know otherwise
                switch (fuelMultiplierType)
                {
                    case FuelMultiplierType.None:
                        showMultiplier = false;
                        break;
                    case FuelMultiplierType.Fixed:
                        showMultiplier = false;
                        break;
                    case FuelMultiplierType.SharedByGame:
                    case FuelMultiplierType.Variable:
                        showMultiplier = true;
                        break;
                }
            }
            private static volatile int _fuelMultiplier;
            public int multiplier
            {
                get
                {
                    int _multiplier;
                    switch (_fuelMultiplierType)
                    {
                        case FuelMultiplierType.None:
                        default:
                            _multiplier = 0;
                            break;
                        case FuelMultiplierType.Fixed:
                            _multiplier = 1;
                            break;
                        case FuelMultiplierType.SharedByGame:
                            _multiplier = _fuelMultiplier;
                            break;
                        case FuelMultiplierType.Variable:
                            _multiplier = int.TryParse(MainWindow.instance.numericUpDownfuelMultiplier.Text, out _multiplier) ? _multiplier : 0;
                            break;
                    }
                    return _multiplier;
                }
                set
                {
                    if (_fuelMultiplier != value)
                    {
                        switch (_fuelMultiplierType)
                        {
                            case FuelMultiplierType.None:
                                _fuelMultiplier = 0;
                                break;
                            case FuelMultiplierType.Fixed:
                                _fuelMultiplier = 1;
                                break;
                            case FuelMultiplierType.SharedByGame:
                                MainWindow.instance.numericUpDownfuelMultiplier.Text = value.ToString();
                                _fuelMultiplier = value;
                                break;
                            case FuelMultiplierType.Variable:
                                if (value == 0)
                                {   // Game says fuel consumption is now inactive
                                    MainWindow.instance.numericUpDownfuelMultiplier.Text = "0";
                                    _fuelMultiplier = 0;
                                }
                                else
                                {   // Game says fuel consumption is now active (but doesn't provide the multiplier)
                                    MainWindow.instance.numericUpDownfuelMultiplier.Text = "1";
                                    _fuelMultiplier = 1;
                                }
                                break;
                        }
                    }
                }
            }
            /// <summary>
            /// Fuel consumption is active in the game
            /// </summary>
            public bool active => fuelMultiplier.multiplier > 0;
            /// <summary>
            /// If the user entered the fuel multiplier and did it wrongly it
            /// will mess up the the data
            /// </summary>
            public bool dontSaveFuelData
            {
                get
                {
                    return _fuelMultiplierType == FuelMultiplierType.Variable &&
                           !UserSettings.GetUserSettings().getBoolean("save_all_fuel_data");
                }
            }
        }
 public static FuelMultiplier fuelMultiplier; } }
namespace CrewChiefV4 { public static partial class Utilities { public class Conversions { const float litresPerUSgallon=3.78541f; public static float convertLitresToGallons(float litres, Boolean roundTo1dp = false)
            {
                if (litres <= 0)
                {
                    return 0f;
                }
                float gallons = litres / litresPerUSgallon;
                if (roundTo1dp)
                { // Mainly used for reporting so round up to 1/10 gallon
                    return ((float)Math.Ceiling(gallons * 10f)) / 10f;
                }
                return gallons;
            } } } }
namespace CrewChiefV4.Events { public static partial class Strategy { public static float getExpectedPlayerTimeLossFallback(float fuelToTheEnd)
        {
            if (Game.IRACING)
            {
                // massive hack, but this is accurate to a few seconds for IMSA/GT3/NASCAR etc...
                // some data points: porsche 963 (gtp) is 1.8 litres / second
                //                   porsche 992 (gt3) is 2.1 litres / second
                return 20f + Math.Max(0f, fuelToTheEnd) / 2f;
            }
            return -1;
        } }
class PersistedBenchmark
    {
        public String game { get; set; }
        public String carClassId { get; set; }
        public String trackName { get; set; }
        public float timeLoss { get; set; }

        // added in later schemas, must be prepared to read default values
        public int fuelLitres { get; set; }
        public string carName { get; set; }
        public ConditionsMonitor.TrackWetness conditions { get; set; }

        public Boolean isForThisCombo(String game, String carClassId, String trackName)
        {
            return this.game != null && this.game.Equals(game) &&
                this.carClassId != null && this.carClassId.Equals(carClassId) &&
                this.trackName != null && this.trackName.Equals(trackName);
        }

        public Boolean isForThisExactCombo(String game, String carName, String trackName)
        {
            return this.game != null && this.game.Equals(game) &&
                this.carName != null && this.carName.Equals(carName) &&
                this.trackName != null && this.trackName.Equals(trackName);
        }

    }
class BenchmarkHelper
    {
        private static String fullPath = DataFiles.pit_benchmarks;
        private static List<PersistedBenchmark> persistedBenchmarks;

        // a cache of all the benchmarks that are relevant for the current session. This should be accessed through
        // findPersistedBenchmarkForCombo.
        private volatile static List<PersistedBenchmark> benchmarksForThisCombo = null;

        private static void saveBenchmarks()
        {
            try
            {
                string jsonRaw = JsonConvert.SerializeObject(BenchmarkHelper.persistedBenchmarks, Formatting.Indented);
                if (BenchmarkHelper.persistedBenchmarks.Count > 0 && (!File.Exists(fullPath) || !jsonRaw.Equals(File.ReadAllText(fullPath))))
                {
                    Console.WriteLine("Saving " + BenchmarkHelper.persistedBenchmarks.Count + " pit benchmarks");
                    File.WriteAllText(fullPath, jsonRaw);
                }
            }
            catch (Exception e)
            {
                Log.Exception(e, "Unable to save pit benchmark : ");
            }
        }

        public static void loadBenchmarks()
        {
            BenchmarkHelper.persistedBenchmarks = null;
            BenchmarkHelper.benchmarksForThisCombo = null;
            if (File.Exists(fullPath))
            {
                try
                {
                    BenchmarkHelper.persistedBenchmarks = JsonConvert.DeserializeObject<List<PersistedBenchmark>>(File.ReadAllText(fullPath));
                    if (BenchmarkHelper.persistedBenchmarks != null)
                    {
                        Console.WriteLine("Loaded " + BenchmarkHelper.persistedBenchmarks.Count() + " saved pitstop time loss benchmarks");
                        return;
                    }
                }
                catch (Exception)
                {
                    Console.WriteLine("Unable to load existing benchmarkdata");
                }
            }
            BenchmarkHelper.persistedBenchmarks = new List<PersistedBenchmark>();
        }

        // the estimatedFuel allows us to have multiple benchmarks that we can query to find
        // the one that is the most accurate for the given stop. Of course fuel isn't the
        // only thing that can be done in a pitstop but (after damage repair) is usually
        // the most dominant part of a green flag pitstop (stock car drivers often take alternating
        // left / right tyres, with most other series getting a free tyre change on a full tank).
        //
        // If fuel is not relevant then it may be left out and the most recent persisted benchmark
        // will be used.
        public static PersistedBenchmark findPersistedBenchmarkForCombo(float estimatedFuelLitres)
        {
            if (CrewChief.currentGameState == null)
            {
                return null;
            }
            if (benchmarksForThisCombo == null)
            {
                // the only way this can be null is if a new Strategy instance was created, which means we need to recreate the cache
                BenchmarkHelper.benchmarksForThisCombo = new List<PersistedBenchmark>();

                var game = CrewChief.gameDefinition.gameEnum.ToString();
                var carClassId = CrewChief.currentGameState.carClass.getClassIdentifier();
                var carName = CrewChief.currentGameState.carName;
                var trackName = CrewChief.currentGameState.SessionData.TrackDefinition.name;
                // first try for the exact car
                foreach (PersistedBenchmark persistedBenchmark in BenchmarkHelper.persistedBenchmarks)
                {
                    if (persistedBenchmark.isForThisExactCombo(game, carName, trackName))
                    {
                        BenchmarkHelper.benchmarksForThisCombo.Add(persistedBenchmark);
                    }
                }
                // then fall back to the car class, which won't be ideal for series with a big fuel difference
                if (BenchmarkHelper.benchmarksForThisCombo.Count == 0)
                {
                    foreach (PersistedBenchmark persistedBenchmark in BenchmarkHelper.persistedBenchmarks)
                    {
                        if (persistedBenchmark.isForThisCombo(game, carClassId, trackName))
                        {
                            BenchmarkHelper.benchmarksForThisCombo.Add(persistedBenchmark);
                        }
                    }
                }
                Console.WriteLine("Found " + benchmarksForThisCombo.Count + " persisted benchmark(s) for car / track / game combo");
            }

            // now we can return the one that is the most relevant
            if (BenchmarkHelper.benchmarksForThisCombo.Count < 1)
            {
                return null;
            }
            else if (estimatedFuelLitres < 0 || estimatedFuelLitres == int.MaxValue)
            {
                // the quickest one
                PersistedBenchmark quickest = null;
                foreach (var b in BenchmarkHelper.benchmarksForThisCombo)
                {
                    if (quickest == null || b.timeLoss < quickest.timeLoss)
                    {
                        quickest = b;
                    }
                }
                return quickest;
            }
            else
            {
                // there is an opportunity here to interpolate between pitstops, but for now
                // we just pick the benchmark with the smallest absolute difference in fuel.
                float nearestFuelDiff = -1;
                PersistedBenchmark nearest = null;

                foreach (var b in BenchmarkHelper.benchmarksForThisCombo)
                {
                    float fuelDiff = Math.Abs(estimatedFuelLitres - b.fuelLitres);
                    if (nearest == null || fuelDiff < nearestFuelDiff)
                    {
                        nearestFuelDiff = fuelDiff;
                        nearest = b;
                    }
                }
                Console.Write($"pit estimate differs from the benchmark by {nearestFuelDiff} litres");
                return nearest;
            }
        }

        public static void updatePersistedBenchmark(float timeLoss, float fuelLitres, ConditionsMonitor.TrackWetness conditions)
        {
            var game = CrewChief.gameDefinition.gameEnum.ToString();
            var carClassId = CrewChief.currentGameState.carClass.getClassIdentifier();
            var trackName = CrewChief.currentGameState.SessionData.TrackDefinition.name;
            var carName = CrewChief.currentGameState.carName;

            Console.WriteLine("Saving new time loss benchmark");
            PersistedBenchmark newBenchmark = new PersistedBenchmark();
            newBenchmark.game = game;
            newBenchmark.carClassId = carClassId;
            newBenchmark.trackName = trackName;
            newBenchmark.timeLoss = timeLoss;
            newBenchmark.conditions = conditions;
            if (fuelLitres < 0)
            {
                fuelLitres = 0;
            }
            newBenchmark.fuelLitres = (int)Math.Ceiling(fuelLitres);
            newBenchmark.carName = carName;

            // we might want to think about truncating the DB, but since this is always a result of a user request and the data
            // is small we might want to just allow the user to manually curate their data. Last thing we want to do is delete
            // data that they wanted to keep.
            BenchmarkHelper.persistedBenchmarks.Add(newBenchmark);
            if (BenchmarkHelper.benchmarksForThisCombo != null)
            {
                BenchmarkHelper.benchmarksForThisCombo.Add(newBenchmark);
            }
            saveBenchmarks();
        }
    } }
namespace CrewChiefV4 { public sealed partial class SpeechRecogniser { public static Boolean ResultContains(String result, String[] alternatives, Boolean logMatch = false)
        {
            result = result.ToLower();
            foreach (String alternative in alternatives)
            {
                if (result == alternative.ToLower())
                {
                    if (logMatch)
                    {
                        Console.WriteLine("Matching entire response: \"" + alternative + "\"");
                    }
                    return true;
                }
            }
            // no result with == so try contains
            foreach (String alternative in alternatives)
            {
                String alternativeLower = alternative.ToLower();
                if (result.Contains(alternativeLower))
                {
                    if (logMatch)
                    {
                        Console.WriteLine("matching partial response " + alternativeLower);
                    }
                    return true;
                }
            }
            return false;
        } } }
namespace CrewChiefV4.Audio { public partial class AudioPlayer { public void playMessageOrFallback(string sound, string fallback, bool immediately = true,
            int priority = 0, AbstractEvent abstractEvent = null)
        {
            var message = new QueuedMessage(
                SoundCache.availableSounds.Contains(sound) ? sound : fallback,
                0,
                abstractEvent: abstractEvent,
                priority: priority);
            if (immediately)
            {
                playMessageImmediately(message);
            }
            else
            {
                playMessage(message);
            }
        } } }
