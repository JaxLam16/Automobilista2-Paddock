//#define UPDATE_DEFAULT_TRACKLANDMARKS
using CrewChiefV4.Audio;

using Newtonsoft.Json;

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace CrewChiefV4
{
    public class TrackLandMarksRecorder
    {
        public static Boolean isRecordingTrackLandmarks = false;
        private static TrackLandmarksForTrack currentRecording = null;
        private static TrackLandmarksData trackLandmarksDataRecording = null;
        private static Boolean hasStartedNewTrackLandmark = false;
        private static TrackLandmark currentLandmark = null;
        private static String folderPathForTrackLandmark;

        public static void startRecordingTrackLandmarks(GameEnum gameEnum, String trackName, int trackId)
        {
            isRecordingTrackLandmarks = true;
            folderPathForTrackLandmark = getLandMarkSpecificFolderPath(gameEnum, trackName);
            Boolean createDirectory = true;
            Boolean fileBroken = true;
            if (Directory.Exists(folderPathForTrackLandmark))
            {
                createDirectory = false;
                String fileName = Path.Combine(folderPathForTrackLandmark, "trackLandmarks.json");
                if(File.Exists(fileName))
                {
                    try
                    {
                        trackLandmarksDataRecording = JsonFiles.ReadFile<TrackLandmarksData>(fileName, JsonFiles.Comments.Strip);
                        currentRecording = trackLandmarksDataRecording.trackLandmarksData.FirstOrDefault();
                        fileBroken = false;
                        Console.WriteLine("Recording started found existing tracklandmarksdata - appending to" + fileName);
                    }
                    catch (Exception e)
                    {
                        Utilities.TryBackupBrokenFile(fileName, "json_broken", "Unable to load existing tracklandmarksdata: " + e.Message);
                        fileBroken = true;
                    }
                }
            }
            if (createDirectory || fileBroken)
            {
                if (createDirectory)
                {
                    Directory.CreateDirectory(folderPathForTrackLandmark);
                }
                trackLandmarksDataRecording = new TrackLandmarksData();
                currentRecording = new TrackLandmarksForTrack();
                switch (gameEnum)
                {
                    case GameEnum.ASSETTO_32BIT:
                    case GameEnum.ASSETTO_64BIT:
                    case GameEnum.ASSETTO_128CARS:
                    case GameEnum.ASSETTO_PRO:
                        currentRecording.acTrackNames = new string[] { trackName };
                        break;
                    case GameEnum.ASSETTO_EVO:
                        currentRecording.aceTrackNames = new string[] { trackName };
                        break;
                    case GameEnum.PCARS_32BIT:
                    case GameEnum.PCARS_64BIT:
                    case GameEnum.PCARS_NETWORK:
                        currentRecording.pcarsTrackName = trackName;
                        break;
                    case GameEnum.PCARS2:
                    case GameEnum.PCARS2_NETWORK:
                    case GameEnum.PCARS3:
                        currentRecording.pcars2TrackName = trackName;
                        break;
                    case GameEnum.AMS2:
                    case GameEnum.AMS2_NETWORK:
                        currentRecording.ams2TrackName = trackName;
                        break;
                    case GameEnum.RF1:
                        currentRecording.rf1TrackNames = new string[] { trackName };
                        break;
                    case GameEnum.RF2_64BIT:
                        currentRecording.rf2TrackNames = new string[] { trackName };
                        break;
                    case GameEnum.LMU:
                        currentRecording.lmuTrackName = trackName;
                        break;
                    case GameEnum.GTR2:
                        currentRecording.gtr2TrackNames = new string[] { trackName };
                        break;
                    case GameEnum.IRACING:
                        currentRecording.irTrackName = trackName;
                        break;
                    case GameEnum.RACE_ROOM:
                        currentRecording.raceroomLayoutId = trackId;
                        break;
                    case GameEnum.ACC:
                        currentRecording.accTrackName = trackName;
                        break;
                    default:
                        break;
                }
                Console.WriteLine("Recording track landmark data for game " + gameEnum + " and track " + trackName);
            }

        }
        private static List<TrackLandmark> removeOverlappingLandmarks( TrackLandmark landmark )
        {
            List<TrackLandmark> landmarksToKeep = new List<TrackLandmark>();
            foreach(var lm in currentRecording.trackLandmarks)
            {
                //starting inside another landmark
                if((landmark.distanceRoundLapStart >= lm.distanceRoundLapStart && landmark.distanceRoundLapStart <= lm.distanceRoundLapEnd) ||
                    //wraps around another landmark
                    (landmark.distanceRoundLapStart <= lm.distanceRoundLapStart && landmark.distanceRoundLapEnd >= lm.distanceRoundLapEnd) ||
                    //ends inside another landmark
                    (landmark.distanceRoundLapEnd >= lm.distanceRoundLapStart && landmark.distanceRoundLapEnd <= lm.distanceRoundLapEnd))
                {
                    Console.WriteLine("Found overlapping landmark at " + lm.landmarkName + " so removing it");
                    continue;
                }
                else
                {
                    landmarksToKeep.Add(lm);
                }
            }
            landmarksToKeep.Add(landmark);
            return landmarksToKeep;
        }
        public static void addLandmark(float distanceRoundTrack)
        {
            if (currentRecording == null || !isRecordingTrackLandmarks)
            {
                Console.WriteLine("Please start a track landmark recoding session before adding landmarks");
                return;
            }
            if(!hasStartedNewTrackLandmark)
            {
                Console.WriteLine("Setting landmark start point at " + distanceRoundTrack + "m");
                hasStartedNewTrackLandmark = true;
                currentLandmark = new TrackLandmark();
                currentLandmark.distanceRoundLapStart = distanceRoundTrack;
                currentLandmark.isCommonOvertakingSpot = false;
            }
            else
            {
                Console.WriteLine("Setting landmark end point at " + distanceRoundTrack + "m");
                currentLandmark.distanceRoundLapEnd = distanceRoundTrack;
                currentRecording.trackLandmarks = removeOverlappingLandmarks(currentLandmark);
                hasStartedNewTrackLandmark = false;
            }
        }

        public static void completeRecordingTrackLandmarks()
        {
            if (isRecordingTrackLandmarks)
            {
                //re-order landmarks by distanceRoundLapStart
                int turn = 1;
                List<TrackLandmark> tml = currentRecording.trackLandmarks.OrderBy(e => e.distanceRoundLapStart).ToList();
                foreach (TrackLandmark lm in tml)
                {
                    if (lm.landmarkName == null || lm.landmarkName.Length == 0)
                    {
                        lm.landmarkName = "turn" + turn;
                    }
                    turn++;
                }
                currentRecording.trackLandmarks = tml;
                trackLandmarksDataRecording.trackLandmarksData.Clear();
                trackLandmarksDataRecording.trackLandmarksData.Add(currentRecording);
                try
                {
                    var trackLandmarkPath = Path.Combine(folderPathForTrackLandmark, "trackLandmarks.json");
                    JsonFiles.WriteFile(trackLandmarkPath, trackLandmarksDataRecording);

                    Console.WriteLine("Done Recording track landmark data to " + trackLandmarkPath);
                }
                catch (Exception e)
                {
                    Log.Exception(e, "Unable to complete landmark recording session : ");
                }
            }
            isRecordingTrackLandmarks = false;
        }

        private static String getLandMarkSpecificFolderPath(GameEnum gameEnum, String trackName)
        {
            return Path.Combine(DataFiles.track_landmarksFolder,
                Utilities.FileNames.MakeValidForPathName(gameEnum.ToString()), Utilities.FileNames.MakeValidForPathName(trackName));
        }
    }

    public class TrackLandmark
    {
        [JsonIgnore]
        private String _landmarkname;

        // this was not marked JsonRequired in the older version of the file format,
        // so we have to oblige the old behaviour.
        [JsonIgnore]
        public String landmarkName {
            get
            {
                if (_landmarkname != null) {
                    return _landmarkname.Equals("") ? null : _landmarkname;
                }
                var found = landmarkNames.Find(e => SoundCache.soundSets.ContainsKey("corners/" + e));
                _landmarkname = found == null ? "" : found;
                return found;
            }
            set
            {
                landmarkNames.Insert(0, value);
            }
        }

        [JsonRequired] // won't complain if it's empty, but at least it'll require that it exists
        public List<String> landmarkNames { get; set; } = new List<string>();
        public float distanceRoundLapStart { get; set; }
        public float distanceRoundLapEnd { get; set; }
        public Boolean isCommonOvertakingSpot { get; set; }
        public float midPoint = -1;

        public Boolean isStraight { get; set; }

        public float getMidPoint()
        {
            if (midPoint == -1)
            {
                midPoint = distanceRoundLapStart + ((distanceRoundLapEnd - distanceRoundLapStart) / 2);
            }
            return midPoint;
        }
    }

    /// <summary>
    /// Contains the data for a track, particularly the track landmarks
    /// for a particular track in ANY game.
    /// </summary>
    internal class TrackLandmarksForTrack
    {
        public String genericTrackName { get; set; }
        public String[] rf1TrackNames { get; set; }
        public String[] rf2TrackNames { get; set; }
        public String lmuTrackName { get; set; }
        public String[] gtr2TrackNames { get; set; }
        public String[] acTrackNames { get; set; }
        public String[] aceTrackNames { get; set; }
        public String irTrackName { get; set; }
        public String pcarsTrackName { get; set; }
        public String pcars2TrackName { get; set; }
        public String ams2TrackName { get; set; }
        public String accTrackName { get; set; }
        public int raceroomLayoutId { get; set; }
        public float approximateTrackLength { get; set; }   // this is optional and used to differentiate duplicated names
        public List<TrackLandmark> trackLandmarks { get; set; }
        /// <summary>
        /// iRacing provides SessionData.Track.IsOval and ignores this.<br/>
        /// Other games get it from trackLandmarksData.json, and if it's not
        /// specified there we try to work it out from the track name.
        /// </summary>
        public Boolean isOval { get; set; }
        public float raceroomRollingStartLapDistance { get; set; }   // this is optional and used to detect "this lap invalidated" vs "this and next lap invalidated" in R3E
        public float iracingPitEntranceDistanceRoundTrack { get; set; }
        public float[] pitApproachPoint { get; set; }   // this is optional and used to detect "approaching pit state" in R3E.  Game {LapDist;X;Z} world values.
        public TrackLandmarksForTrack()
        {
            this.trackLandmarks = new List<TrackLandmark>();
            this.raceroomLayoutId = -1;
            this.approximateTrackLength = -1.0f;
            this.acTrackNames = null;
            this.aceTrackNames = null;
            this.rf1TrackNames = null;
            this.rf2TrackNames = null;
            this.lmuTrackName = null;
            this.gtr2TrackNames = null;
            this.pcarsTrackName = null;
            this.pcars2TrackName = null;
            this.ams2TrackName = null;
            this.irTrackName = null;
            this.accTrackName = null;
            this.isOval = false;
            this.raceroomRollingStartLapDistance = -1.0f;
            this.iracingPitEntranceDistanceRoundTrack = -1.0f;
            this.pitApproachPoint = null;
        }
        public void SetTrackNames(string[] value)
        {
            switch (Game.gameType)
            {
                case GameType.ASSETTO:
                    this.acTrackNames = value;
                    break;
                case GameType.ASSETTO_EVO:
                    this.aceTrackNames = value;
                    break;
                case GameType.PCARS:
                    this.pcarsTrackName = value[0];
                    break;
                case GameType.PCARS2:
                case GameType.PCARS3:
                    this.pcars2TrackName = value[0];
                    break;
                case GameType.AMS2:
                    this.ams2TrackName = value[0];
                    break;
                case GameType.RF1:
                    this.rf1TrackNames = value;
                    break;
                case GameType.RF2:
                    this.rf2TrackNames = value;
                    break;
                case GameType.LMU:
                    this.lmuTrackName = value[0];
                    break;
                case GameType.GTR2:
                    this.gtr2TrackNames = value;
                    break;
                case GameType.IRACING:
                    this.irTrackName = value[0];
                    break;
                case GameType.ACC:
                    this.accTrackName = value[0];
                    break;
                default:
                Log.Error("Unable to set track names for game type " + Game.gameType);
                break;
            }
        }
    }

    /// <summary>
    /// Contains the data for a track, particularly the track landmarks
    /// for a particular track in the CURRENT game.
    /// </summary>
    public class TrackDataContainer
    {
        public List<TrackLandmark> trackLandmarks;
        public Boolean isOval = false;
        public float raceroomRollingStartLapDistance = -1.0f;
        public Boolean isDefinedInTracklandmarksData = true;
        public float iracingPitEntranceDistanceRoundTrack = -1.0f;
        public float[] pitApproachPoint = null;
        public TrackDataContainer(
            List<TrackLandmark> trackLandmarks,
            Boolean isOval,
            Boolean isDefinedInTracklandmarksData = true,
            float raceroomRollingStartLapDistance = -1.0f,
            float iracingPitEntranceDistanceRoundTrack = -1.0f,
            float[] pitApproachPoint = null)
        {
            this.trackLandmarks = trackLandmarks;
            this.isOval = isOval;
            this.raceroomRollingStartLapDistance = raceroomRollingStartLapDistance;
            this.isDefinedInTracklandmarksData = isDefinedInTracklandmarksData;
            this.iracingPitEntranceDistanceRoundTrack = iracingPitEntranceDistanceRoundTrack;
            this.pitApproachPoint = pitApproachPoint;
        }
    }

    internal class TrackLandmarksData
    {
        public List<TrackLandmarksForTrack> trackLandmarksData { get; set; }
        public TrackLandmarksData()
        {
            this.trackLandmarksData = new List<TrackLandmarksForTrack>();
        }

        private Boolean checkForAndMatchOnLength(float lengthFromGame, float approximateLengthFromJSON)
        {
            if (lengthFromGame == -1 || approximateLengthFromJSON == -1)
            {
                return true;
            }
            else
            {
                // if an approximate length is specified in the JSON, check that the length from the game is close to this
                // pretty lenient here as it has to work for multiple games each with their own inaccuracies.
                return Math.Abs(lengthFromGame - approximateLengthFromJSON) < 200;
            }
        }

        /// <summary>
        /// Don't do all this again if it's the same game and track
        /// </summary>
        private class cache
        {
            internal string trackName;
            internal GameEnum gameEnum;
            internal TrackDataContainer trackDataContainer;
        }
        private static cache cachedResult;

        public TrackDataContainer getTrackDataForTrackName(String trackName, float lengthFromGame)
        {
            if (cachedResult != null)
            {
                if (cachedResult.gameEnum == CrewChief.gameDefinition.gameEnum &&
                    String.Equals(cachedResult.trackName, trackName, StringComparison.OrdinalIgnoreCase))
                {
                    return cachedResult.trackDataContainer;
                }
                cachedResult = null;
            }
            TrackDataContainer result = null;
            foreach (TrackLandmarksForTrack trackLandmarksForTrack in trackLandmarksData)
            {
                switch (Game.gameType)
                {
                    case GameType.ASSETTO:
                        if (trackLandmarksForTrack.acTrackNames != null)
                        {
                            foreach (String acTrackName in trackLandmarksForTrack.acTrackNames)
                            {
                                if (String.Equals(acTrackName, trackName, StringComparison.OrdinalIgnoreCase)
                                    && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                                {
                                    Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                                    return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval);
                                }
                            }
                        }
                        break;
                    case GameType.ASSETTO_EVO:
                        if (trackLandmarksForTrack.aceTrackNames != null)
                        {
                            foreach (String aceTrackName in trackLandmarksForTrack.aceTrackNames)
                            {
                                if (String.Equals(aceTrackName, trackName, StringComparison.OrdinalIgnoreCase)
                                    && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                                {
                                    Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                                    return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval);
                                }
                            }
                        }
                        break;

                    case GameType.PCARS:
                        if (String.Equals(trackLandmarksForTrack.pcarsTrackName, trackName, StringComparison.OrdinalIgnoreCase)
                            && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                        {
                            Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                            return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval);
                        }
                        break;
                    case GameType.PCARS2:
                    case GameType.PCARS3:
                        if (String.Equals(trackLandmarksForTrack.pcars2TrackName, trackName, StringComparison.OrdinalIgnoreCase)
                            && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                        {
                            Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                            return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval);
                        }
                        break;
                    case GameType.AMS2:
                        if (String.Equals(trackLandmarksForTrack.ams2TrackName, trackName, StringComparison.OrdinalIgnoreCase)
                            && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                        {
                            Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                            return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval);
                        }
                        break;
                    case GameType.RF1:
                        if (trackLandmarksForTrack.rf1TrackNames != null)
                        {
                            foreach (String rf1TrackName in trackLandmarksForTrack.rf1TrackNames)
                            {
                                if (String.Equals(rf1TrackName, trackName, StringComparison.OrdinalIgnoreCase)
                                    && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                                {
                                    Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                                    return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval);
                                }
                            }
                        }
                        break;
                    case GameType.RF2:
                        if (trackLandmarksForTrack.rf2TrackNames != null)
                        {
                            foreach (String rf2TrackName in trackLandmarksForTrack.rf2TrackNames)
                            {
                                if (String.Equals(rf2TrackName, trackName, StringComparison.OrdinalIgnoreCase)
                                    && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                                {
                                    Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                                    return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval);
                                }
                            }
                        }
                        break;
                    case GameType.LMU:
                        if (String.Equals(trackLandmarksForTrack.lmuTrackName, trackName, StringComparison.OrdinalIgnoreCase)
                            && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                        {
                            Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                            return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval);
                        }
                        break;
                    case GameType.GTR2:
                        if (trackLandmarksForTrack.gtr2TrackNames != null)
                        {
                            foreach (String gtr2TrackName in trackLandmarksForTrack.gtr2TrackNames)
                            {
                                if (String.Equals(gtr2TrackName, trackName, StringComparison.OrdinalIgnoreCase)
                                    && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                                {
                                    Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                                    return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval);
                                }
                            }
                        }
                        break;
                    case GameType.IRACING:
                        if(trackLandmarksForTrack.irTrackName != null)
                        {
                            if (String.Equals(trackLandmarksForTrack.irTrackName, trackName, StringComparison.OrdinalIgnoreCase)
                                && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                            {
                                Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                                return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval, true, -1.0f, trackLandmarksForTrack.iracingPitEntranceDistanceRoundTrack);
                            }
                        }
                        break;
                    case GameType.ACC:
                        if (trackLandmarksForTrack.accTrackName != null && trackLandmarksForTrack.accTrackName.Length > 0)
                        {
                            if (String.Equals(trackLandmarksForTrack.accTrackName, trackName, StringComparison.OrdinalIgnoreCase)
                                && checkForAndMatchOnLength(lengthFromGame, trackLandmarksForTrack.approximateTrackLength))
                            {
                                Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                                return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval);
                            }
                        }
                        break;
                    default:
                        break;
                }

                if (result != null)
                {
                    break;
                }
            }

            if (result == null)
            {
                result = new TrackDataContainer(new List<TrackLandmark>(), isOvalTrack(trackName), false);
            }
            if (result.trackLandmarks.Count == 0)
            {
                Console.WriteLine("No landmarks defined for this track");
            }
            cachedResult = new cache
            {
                gameEnum = CrewChief.gameDefinition.gameEnum,
                trackName = trackName,
                trackDataContainer = result
            };
            return result;
        }

        public TrackDataContainer getTrackDataForTrackLayoutId(int raceroomLayoutId)
        {
            foreach (TrackLandmarksForTrack trackLandmarksForTrack in trackLandmarksData)
            {
                if (trackLandmarksForTrack.raceroomLayoutId == raceroomLayoutId)
                {
                    Console.WriteLine(trackLandmarksForTrack.trackLandmarks.Count + " landmarks defined for this track");
                    return new TrackDataContainer(trackLandmarksForTrack.trackLandmarks, trackLandmarksForTrack.isOval, true, trackLandmarksForTrack.raceroomRollingStartLapDistance, -1.0f, trackLandmarksForTrack.pitApproachPoint);
                }
            }
            return new TrackDataContainer(new List<TrackLandmark>(), false, false);
        }

        internal static TrackLandmarksData getTrackLandmarksDataFromFile(String filePath)
        {
            TrackLandmarksData result = new TrackLandmarksData();
            if (!File.Exists(filePath))
            {
                return result;
            }
            try
            {
                result = JsonFiles.ReadFile<TrackLandmarksData>(filePath, JsonFiles.Comments.Strip, false);
            }
            catch (Exception)
            {
            }
            return result;

            string[] stringToArray(string s)
            {
                return String.IsNullOrEmpty(s) ? null : new string[] { s };
            }
            string[] stringArray(string[] s)
            {
                return s ?? null;
            }
        }

        /// <summary>
        /// Oval / Non-oval dialog.
        /// </summary>
        /// <param name="trackName"></param>
        /// <param name="suggestedValue"> The probable answer</param>
        /// <returns>true: it is an oval, false: it is not</returns>
        internal static void ShowOvalConfirmationForm(string trackName, bool suggestedValue)
        {
            var manager = new ForegroundWindowManager();
            Form form = new Form();

            // This form uses explicit positions and sizes, so don't let WinForms
            // rescale the controls independently on a high-DPI monitor.
            form.AutoScaleMode = AutoScaleMode.None;

            Font biggerFont = new Font(
                SystemFonts.MessageBoxFont.FontFamily,
                SystemFonts.MessageBoxFont.Size * 1.2f,
                FontStyle.Regular);
            form.Font = biggerFont;

            manager.SaveForegroundWindow();
            form.TopMost = true;

            ComponentResourceManager resources = new System.ComponentModel.ComponentResourceManager(typeof(MainWindow));
            form.Icon = ((Icon)(resources.GetObject("$this.Icon")));

            form.Text = "Confirm Track Type";

            // Specify the usable area rather than the overall window size.
            // This avoids DPI-dependent title bar/border sizes reducing the
            // space available for the controls.
            form.ClientSize = new Size(510, 300);

            form.StartPosition = FormStartPosition.CenterScreen;

            Label label = new Label();
            label.Left = 20;
            label.Top = 20;
            label.Width = 440;
            label.AutoSize = true;
            label.MaximumSize = new Size(440, 0);
            label.Text =
                $"'{trackName}' is not in the track database.\n\n" +
                $"It's probably {(suggestedValue ? "an Oval" : "not an Oval")} but you choose and I'll add it:";

            Button ovalButton = new Button();
            ovalButton.Text = "Oval";
            ovalButton.Left = 80;
            ovalButton.Top = 190;
            ovalButton.Height = 50;
            ovalButton.Width = 120;

            Button notOvalButton = new Button();
            notOvalButton.Text = "Not Oval";
            notOvalButton.Left = label.Width - ovalButton.Left - ovalButton.Width;
            notOvalButton.Top = ovalButton.Top;
            notOvalButton.Height = ovalButton.Height;
            notOvalButton.Width = ovalButton.Width;

            form.Controls.Add(label);
            form.Controls.Add(ovalButton);
            form.Controls.Add(notOvalButton);

            ovalButton.Click += delegate
            {
                UpdateTrackInJson(trackName, true);
                form.Close();
                manager.RestoreForegroundWindow();
            };

            notOvalButton.Click += delegate
            {
                UpdateTrackInJson(trackName, false);
                form.Close();
                manager.RestoreForegroundWindow();
            };

            // Put the suggested answer first in the tab order. WinForms will
            // therefore give it initial focus and Enter will select it.
            if (suggestedValue)
            {
                ovalButton.TabIndex = 0;
                notOvalButton.TabIndex = 1;
            }
            else
            {
                notOvalButton.TabIndex = 0;
                ovalButton.TabIndex = 1;
            }

            form.Shown += delegate
            {
                form.SelectNextControl(
                    null,
                    true,
                    true,
                    true,
                    true);
            };

            // This is modeless, so dispose the resources when the user
            // eventually closes the form.
            form.FormClosed += delegate
            {
                biggerFont.Dispose();
                form.Dispose();
            };

            form.ResumeLayout(true);
            form.PerformLayout();
            form.Show();
        }
        private bool isOvalTrack(string trackName)
        {
            if (!Game.HAS_OVALS || Game.DEFINES_OVALS)
            {
                return false;
            }
            bool maybe = maybeOval(trackName);
            if (UserSettings.GetUserSettings().getBoolean("auto_is_oval"))
            {
                UpdateTrackInJson(trackName, maybe);
            }
            else
            {
                MainWindow.instance.BeginInvoke(new Action(() =>
                {
                    ShowOvalConfirmationForm(trackName, maybe);
                }));
            }
            return maybe;
        }
        private static void UpdateTrackInJson(string trackName, bool confirmedIsOval)
        {
            TrackLandmarksForTrack trackLandmarksData = new TrackLandmarksForTrack { isOval = confirmedIsOval };
            trackLandmarksData.SetTrackNames(new[] { trackName });

            // Add it to the user's data (Documents\CrewChiefV4\Track_landmarks\trackLandmarksData.json)
            string userTrackLandmarksDataPath = Path.Combine(
                DataFiles.track_landmarksFolder, "trackLandmarksData.json");

            TrackLandmarksData data = TrackLandmarksData.getTrackLandmarksDataFromFile(userTrackLandmarksDataPath);
            data.trackLandmarksData.Add(trackLandmarksData);
            JsonFiles.WriteFilteredFile(userTrackLandmarksDataPath, data);
        }

        private bool maybeOval(string trackName)
        { // We want to know if the track is an oval or not, only iRacing provides it
          // and it's not in our track definitions data. So just check if the track
          // name suggests it's an oval track.
            if (string.IsNullOrWhiteSpace(trackName))
            {
                return false;
            }

            string name = trackName.Trim().ToLowerInvariant();

            // Generic keywords commonly associated with oval tracks
            string[] ovalKeywords =
            {
                "speedway",
                "superspeedway",
                "oval",
                "raceway",
            };
            // Specific tracks that aren't ovals even if the name is ambiguous
            string[] notOvalTracks =
            {
                "adelaide", // except for Adelaide International Raceway Super Speedway Bowl
                "fuji",
                "tokachi",
                "sebring",
                "clark",    // Clark International Speedway, Phillipines
            };


            string keyword = ovalKeywords
                .FirstOrDefault(h => name.Contains(h));

            if (keyword != null)
            {
                string notOvalKeyword = notOvalTracks
                    .FirstOrDefault(h => name.Contains(h));

                if (notOvalKeyword != null)
                {
                    Log.Commentary($"Track name contains oval keyword '{keyword}', but is not an oval: " + trackName);
                    return false;
                }
                Log.Commentary($"Track name contains oval keyword '{keyword}', treating as oval: " + trackName);
                return true;
            }

            string[] roadCourseHints =
            {
                "road",
                "gp",
                "grand prix",
                "club",
                "national",
            };

            keyword = roadCourseHints
                .FirstOrDefault(h => name.Contains(h));

            if (keyword != null)
            {
                Log.Commentary($"Track name contains road course hint '{keyword}', treating as non-oval: " + trackName);
                return false;
            }

            // Specific tracks that might be oval even if the name is ambiguous
            // Munged from https://www.racingcircuits.info/find-a-circuit/circuit-configuration.html
            string[] maybeOvalTracks =
            {
                "atlanta",
                "bristol",
                "brooklands",   // Don't think they had spotters there!
                "cajititlan",
                "cajititlán",
                "calder",       // Calder Park Raceway
                "charlotte",
                "chicagoland",
                "cristais",
                "darlington",
                "daytona",
                "disney",       // Walt Disney World Speedway
                "dover",
                "fontana",
                "gateway",
                "hampshire",
                "homestead",    // Homestead-Miami Speedway
                "indianapolis",
                "iowa",
                "jacarepaguá",
                "kansas",
                "kentucky",
                "killarney",
                "langhorne",
                "lausitzring",
                "luanda",
                "mallory",
                "martinsville",
                "memorial",     // LA Memorial Coliseum
                "michigan",
                "milwaukee",
                "monterrey",
                "motegi",
                "nashville",
                "nring",
                "ontario",
                "oxford",
                "penbay",
                "phakisa",
                "phoenix",
                "pocono",
                "potosino",
                "puebla",
                "reem",
                "richmond",
                "rockingham",
                "sanair",
                "talladega",
                "texas",
                "trenton",
                "vegas",        // Las Vegas Motor Speedway
                "wilkesboro",
                "zhuzhou",
            };

            keyword = maybeOvalTracks
                .FirstOrDefault(h => name.Contains(h));

            if (keyword != null)
            {
                Log.Commentary($"Track name contains known oval track keyword '{keyword}': " + trackName);
            }

            return keyword != null;
        }
    }

    public partial class TrackData
    {
        // any track over 3500 metres will use gap points
        public const float gapPointsThreshold = 3300f;
        public const float gapPointSpacing = 780f;

        internal static TrackLandmarksData TRACK_LANDMARKS_DATA;

        // very long track = anything more than 20000 metres, long = anything more than 10000 metres, short track = anything less than 1.5 mile (2400 metres),
        // very short track = anything less than 1000 metres, medium = everything else
        // This allows a quick sanity check of some messages without having to fart about with track length. Expected use (to be done...)
        // is when checking how many laps to wait for enabling some messages like gaps and laps
        public enum TrackLengthClass { VERY_SHORT, SHORT, MEDIUM, LONG, VERY_LONG }

        #region FixedTrackDefinitions // For ACS, ACC and PCARS
        private static List<TrackDefinition> pCarsTracks = new List<TrackDefinition>()
        {
            new TrackDefinition("Autodromo Nazionale Monza:Grand Prix", 3, 5782.521f, new float[] {22.20312f, -437.1672f}, new float[] {63.60915f, -1.117797f}),
            new TrackDefinition("Autodromo Nazionale Monza:Short", 3, 2422.831f, new float[] {22.20312f, -437.1672f}, new float[] {63.60915f, -1.117797f}),
            new TrackDefinition("Azure Circuit:Grand Prix", 2f, 3325.762f, new float[] {-203.8109f, 613.3162f}, new float[] {105.2057f, 525.9147f}),
            new TrackDefinition("Bathurst:", 2, 6238.047f, new float[] {80.84997f, 7.21405f}, new float[] {-368.7227f, 12.93535f}),
            new TrackDefinition("Brands Hatch:Indy", 2.5f, 1924.475f, new float[] {-329.1295f, 165.8752f}, new float[] {-36.68332f, 355.611f}),
            new TrackDefinition("Brands Hatch:Grand Prix", 2.5f, 3890.407f, new float[] {-329.1295f, 165.8752f}, new float[] {-36.68332f, 355.611f}),
            new TrackDefinition("Brno:", 3, 5377.732f, new float[] {-194.1228f, -11.41852f}, new float[] {139.6739f, 0.06169825f}),
            new TrackDefinition("Cadwell:Club Circuit", 2346.271f),
            new TrackDefinition("Cadwell:Woodland", 2, 1335.426f, new float[] {45.92422f, 72.04858f}, new float[] {-10.31487f, -40.43255f}),
            new TrackDefinition("Cadwell:Grand Prix", 2, 3453.817f, new float[] {45.92422f, 72.04858f}, new float[] {-10.31487f, -40.43255f}),
            new TrackDefinition("Circuit de Barcelona-Catalunya:Club", 1691.681f),
            new TrackDefinition("Circuit de Barcelona-Catalunya:Grand Prix", 3, 4630.515f, new float[] {622.7108f, -137.3975f}, new float[] {26.52858f, -167.9301f}),
            new TrackDefinition("Circuit de Barcelona-Catalunya:National", 3, 2948.298f, new float[] {622.7108f, -137.3975f}, new float[] {26.52858f, -167.9301f}),
            new TrackDefinition("Circuit de Spa-Francorchamps:", 2.5f, 6997.816f, new float[] {-685.1871f, 1238.607f}, new float[] {-952.3125f, 1656.81f}),
            new TrackDefinition("Le Mans:Circuit des 24 Heures du Mans", 3, 13595.01f, new float[] {-737.9395f, 1107.367f}, new float[] {-721.3452f, 1582.873f}),
            new TrackDefinition("Dubai Autodrome:Club", 3, 2525.363f, new float[] {971.8023f, 199.1564f}, new float[] {452.5084f, 126.7626f}),
            new TrackDefinition("Dubai Autodrome:Grand Prix", 3, 5372.706f, new float[] {971.8023f, 199.1564f}, new float[] {452.5084f, 126.7626f}),
            new TrackDefinition("Dubai Autodrome:International", 3, 4290.958f, new float[] {971.8023f, 199.1564f}, new float[] {452.5084f, 126.7626f}),
            new TrackDefinition("Dubai Autodrome:National", 3, 3570.053f, new float[] {971.8023f, 199.1564f}, new float[] {452.5084f, 126.7626f}),
            new TrackDefinition("Donington Park:Grand Prix", 2, 3982.949f, new float[] {200.8843f, 144.8465f}, new float[] {486.4654f, 119.9713f}),
            new TrackDefinition("Donington Park:National", 2, 3175.802f, new float[] {200.8843f, 144.8465f}, new float[] {486.4654f, 119.9713f}),
            new TrackDefinition("Hockenheim:Grand Prix", 3, 4563.47f, new float[] {-483.1076f, -428.47f}, new float[] {-704.3397f, 11.15407f}),
            new TrackDefinition("Hockenheim:Short", 3, 2593.466f, new float[] {-483.1076f, -428.47f}, new float[] {-704.3397f, 11.15407f}),
            new TrackDefinition("Hockenheim:National", 3, 3685.798f, new float[] {-483.1076f, -428.47f}, new float[] {-704.3397f, 11.15407f}),
            new TrackDefinition("Imola:Grand Prix", 3, 4847.88f, new float[] {311.259f, 420.3269f}, new float[] {-272.6198f, 418.3795f}),
            new TrackDefinition("Le Mans:Le Circuit Bugatti", 3, 4149.839f, new float[] {-737.9395f, 1107.367f}, new float[] {-721.3452f, 1582.873f}),
            new TrackDefinition("Mazda Raceway:Laguna Seca", 2, 3593.582f, new float[] {-70.22401f, 432.3777f}, new float[] {-279.2681f, 228.165f}),
            new TrackDefinition("Nordschleife:Full", 3, 20735.4f,  new float[] {599.293f, 606.7135f}, new float[] {391.6694f, 694.4844f}),
            new TrackDefinition("Nürburgring:Grand Prix", 2.5f, 5122.845f, new float[] {443.6332f, 527.8024f}, new float[] {66.84711f, 96.7378f}),
            new TrackDefinition("Nurburgring:GP", 2.5f, 5122.845f, new float[] {443.6332f, 527.8024f}, new float[] {66.84711f, 96.7378f}),
            new TrackDefinition("Nürburgring:MuellenBach", 1488.941f),
            new TrackDefinition("Nürburgring:Sprint", 2.5f, 3603.18f, new float[] {443.6332f, 527.8024f}, new float[] {66.84711f, 96.7378f}),
            new TrackDefinition("Nürburgring:Sprint Short", 2.5f, 3083.551f, new float[] {443.6332f, 527.8024f}, new float[] {66.84711f, 96.7378f}),
            new TrackDefinition("Oschersleben:C Circuit", 1061.989f),
            new TrackDefinition("Oschersleben:Grand Prix", 3, 3656.855f, new float[] {-350.7033f, 31.39084f}, new float[] {239.3137f, 91.73861f}),
            new TrackDefinition("Oschersleben:National", 3, 2417.65f, new float[] {-350.7033f, 31.39084f}, new float[] {239.3137f, 91.73861f}),
            new TrackDefinition("Oulton Park:Fosters", 2, 2649.91f, new float[] {46.9972f, 80.40176f}, new float[] {114.8132f, -165.5994f}),
            new TrackDefinition("Oulton Park:International", 2, 4302.739f, new float[] {46.9972f, 80.40176f}, new float[] {114.8132f, -165.5994f}),
            new TrackDefinition("Oulton Park:Island", 2, 3547.586f, new float[] {46.9972f, 80.40176f}, new float[] {114.8132f, -165.5994f}),
            new TrackDefinition("Road America:", 3.5f, 6482.489f, new float[] {430.8689f, 245.7329f}, new float[] {451.5659f, -330.7411f}),
            new TrackDefinition("Sakitto:Grand Prix", 2.5f, 5383.884f, new float[] {576.6671f, -142.1608f}, new float[] {607.291f, -646.9218f}),
            new TrackDefinition("Sakitto:International", 2, 2845.161f, new float[] {-265.1671f, 472.4344f}, new float[] {-154.9505f, 278.1627f}),
            new TrackDefinition("Sakitto:National", 2, 3100.48f, new float[] {-265.1671f, 472.4344f}, new float[] {-154.9505f, 278.1627f}),
            new TrackDefinition("Sakitto:Sprint", 2.5f, 3539.384f, new float[] {576.6671f -142.1608f}, new float[] {607.291f, -646.9218f}),
            new TrackDefinition("Silverstone:Grand Prix", 3, 5809.965f, new float[] {-504.739f, -1274.686f}, new float[] {-273.1427f, -861.1436f}),
            new TrackDefinition("Silverstone:International", 3, 2978.349f, new float[] {-504.739f, -1274.686f}, new float[] {-273.1427f, -861.1436f}),
            new TrackDefinition("Silverstone:National", 2, 2620.891f, new float[] {-323.1119f, -115.6939f},new float[] {157.4515f, 0.4208831f}),
            new TrackDefinition("Silverstone:Stowe", 2, 1712.277f, new float[] {-75.90499f, -1396.183f}, new float[] {-0.5095776f, -1096.397f}),
            new TrackDefinition("Snetterton:100 Circuit", 1544.868f),
            new TrackDefinition("Snetterton:200 Circuit", 2, 3170.307f, new float[] {228.4838f, -25.23679f}, new float[] {-44.5122f, -55.82156f}),
            new TrackDefinition("Snetterton:300 Circuit", 2, 4747.875f, new float[] {228.4838f, -25.23679f}, new float[] {-44.5122f, -55.82156f}),
            new TrackDefinition("Sonoma Raceway:Grand Prix", 2, 4025.978f, new float[] {-592.7792f, 87.43731f}, new float[] {-152.6224f, -30.71386f}),
            new TrackDefinition("Sonoma Raceway:National", 2, 3792.239f, new float[] {-592.7792f, 87.43731f}, new float[] {-152.6224f, -30.71386f}),
            new TrackDefinition("Sonoma Raceway:Short", 2, 3174.824f, new float[] {-592.7792f, 87.43731f}, new float[] {-152.6224f, -30.71386f}),
            new TrackDefinition("Watkins Glen International:Grand Prix", 3, 5112.122f, new float[] {589.6273f, -928.2814f}, new float[] {542.0042f, -1410.464f}),
            new TrackDefinition("Watkins Glen International:Short Circuit", 3, 3676.561f, new float[] {589.6273f, -928.2814f}, new float[] {542.0042f, -1410.464f}),
            new TrackDefinition("Willow Springs:Short Circuit", 3, 1627.787f, new float[] {-386.1919f, 818.131f}, new float[] {-317.1366f, 641.947f}),
            new TrackDefinition("Willow Springs:International Raceway", 3, 4038.008f, new float[] {319.4275f, -21.51243f}, new float[] {-44.84023f -23.41344f}),
            new TrackDefinition("Zhuhai:International Circuit", 3, 4293.098f, new float[] {-193.7068f, 123.679f}, new float[] {64.56277f, -71.51254f}),
            new TrackDefinition("Zolder:Grand Prix", 4, 4146.733f, new float[] {138.3811f, 132.7747f}, new float[] {682.2009f, 179.8147f}),

            new TrackDefinition("Bannochbrae:Road Circuit", 4, 7251.9004f, new float[]{-175f, 16f}, new float[]{131f, 14.5f}),
            new TrackDefinition("Rouen Les Essarts:", 4, 6499.198f, new float[]{117.25f, 25.5f}, new float[]{-84.75f, -13.5f}),
            new TrackDefinition("Rouen Les Essarts:Short", 4, 5390.12939f, new float[]{117.25f, 25.5f}, new float[]{-84.75f, -13.5f}),
            // this is the classic version. Which has *exactly* the same name as the non-classic version. Not cool.
            new TrackDefinition("Silverstone:Grand Prix", 3, 4697.72656f, new float[] {-347f, -165f}, new float[] {152.75f, -1.25f}),
            new TrackDefinition("Hockenheim:Classic", 3, 6763.425f, new float[] {-533f, -318.25f}, new float[] {-705.5f, -2f})
        };

        private static List<TrackDefinition> accTracks = new List<TrackDefinition>()
        {
            new TrackDefinition("Spa:track config", 7004f, 3, new float[] { 2329.3f, 5032.354f}),
            new TrackDefinition("monza:track config", 5793f, 3, new float[] {1952.014f, 3854.782f}),
            new TrackDefinition("Zolder:track config", 4011f, 3, new float[] {1464.437f, 2755.968f}),
            new TrackDefinition("brands_hatch:track config", 3908f, 3, new float[] {1136.084f, 2208.08f}),
            new TrackDefinition("Silverstone:track config", 5891f, 3, new float[] {1874.756f, 4170.74f}),
            new TrackDefinition("Paul_Ricard:track config", 5842f, 3, new float[] { 1540.441f, 3484.919f}),
            new TrackDefinition("misano:track config", 4226f, 3, new float[] { 941.0679f, 2632.186f}),
            new TrackDefinition("Hungaroring:track config", 4381f, 3, new float[] { 1743.39f, 3279.477f}),
            new TrackDefinition("nurburgring:track config", 5137f, 3, new float[] { 2328.185f, 4422.274f}),
            new TrackDefinition("Barcelona:track config", 4655f, 3, new float[] { 1620.319f, 3411.963f})
        };

        private static List<TrackDefinition> assettoTracks = new List<TrackDefinition>()
        {
            new TrackDefinition("spa:", 6946.062f, 3, new float[] {2265f, 5036f}),
            new TrackDefinition("ks_barcelona:layout_gp", 4591.887f, 3, new float[] {1643f, 3383f}),
            new TrackDefinition("ks_barcelona:layout_moto", 4683.986f, 3, new float[] {1643f, 3376f}),
            new TrackDefinition("acu_bathurst:", 6215.709f, 3, new float[] {2233f, 4262}),
            new TrackDefinition("ks_black_cat_county:layout_int", 4683.986f, 3, new float[] {1594f, 3781f}),
            new TrackDefinition("ks_black_cat_county:layout_long", 11176.96f, 3, new float[] {3618f, 7162f}),
            new TrackDefinition("ks_black_cat_county:layout_short", 6453.315f, 3, new float[] {2778f, 4813f}),
            new TrackDefinition("ks_brands_hatch:gp", 3887.807f, 3, new float[] {1082f, 2196f}),
            new TrackDefinition("ks_brands_hatch:indy", 1915.786f, 2, new float[] {1083f, 0f}),
            new TrackDefinition("circuit_de_la_sarthe:24hours", 13613.44f, 3, new float[] {4535f, 9090f}),
            new TrackDefinition("circuit_de_la_sarthe:nochicane", 13565.71f, 3, new float[] {4515f, 9036f}),
            new TrackDefinition("doningtonpark:gp", 3904.841f, 3, new float[] {1276f, 2402f}),
            new TrackDefinition("doningtonpark:national", 3126.198f, 3, new float[] {1274f, 2402f}),
            new TrackDefinition("imola:", 4864.107f, 3, new float[] {1533f, 3291f}),
            new TrackDefinition("magione:", 2455.794f, 2, new float[] {1291f, 0f}),
            new TrackDefinition("monza:", 5758.661f, 3, new float[] {2122f, 3879f}),
            new TrackDefinition("ks_monza66:full", 10019.83f, 3, new float[] {3213f, 5310f}),
            new TrackDefinition("ks_monza66:junior", 2395.745f, 3, new float[] {742f, 1532f}),
            new TrackDefinition("ks_monza66:road", 5758.69f, 3, new float[] {1989f, 3843f}),
            new TrackDefinition("mugello:", 5197.331f, 3, new float[] {1299f, 2889f}),
            new TrackDefinition("ks_nordschleife:endurance", 25358.28f, 3, new float[] {9690f, 16469f}),
            new TrackDefinition("ks_nordschleife:endurance_cup", 24315.77f, 3, new float[] {8659f, 15435f}),
            new TrackDefinition("ks_nordschleife:nordschleife", 20801.37f, 3, new float[] {5424f, 12200f}),
            new TrackDefinition("ks_nurburgring:layout_gp_a", 5077.904f, 3, new float[] {1454f, 3274f}),
            new TrackDefinition("ks_nurburgring:layout_sprint_a", 3566.685f, 2, new float[] {1609f, 0f}),
            new TrackDefinition("ks_nurburgring:layout_sprint_b", 3559.989f, 2, new float[] {1611f, 0f}),
            new TrackDefinition("ks_red_bull_ring:layout_gp", 4286.527f, 3, new float[] {1100f, 2701f}),
            new TrackDefinition("ks_red_bull_ring:layout_national", 2317.448f, 2, new float[] {1206f, 0f}),
            new TrackDefinition("ks_silverstone:gp", 5803.997f, 3, new float[] {1502f, 4152}),
            new TrackDefinition("ks_silverstone:international", 2941.82f, 2, new float[] {1290f, 0f}),
            new TrackDefinition("ks_silverstone:national", 2600.262f, 2, new float[] {1422f, 0f}),
            new TrackDefinition("tor_poznanl:laser", 4029.902f, 3, new float[] {1563f, 2919f}),
            new TrackDefinition("trento-bondone:", 17183.77f, 1, new float[] {0f, 0f}),
            new TrackDefinition("ks_vallelunga:classic_circuit", 3180.26f, 3, new float[] {1235f, 2197f}),
            new TrackDefinition("ks_vallelunga:club_circuit", 1720.172f, 2, new float[] {734f, 0f}),
            new TrackDefinition("ks_vallelunga:extended_circuit", 4030.934f, 3, new float[] {1749f, 3044f}),
            new TrackDefinition("vir:full course", 5221.266f, 3, new float[] {1608f, 3777f}),
            new TrackDefinition("vir:grand east course", 6383.806f, 3, new float[] {2152f, 4229f}),
            new TrackDefinition("vir:grand west course", 6564.385f, 3, new float[] {3061f, 4877f}),
            new TrackDefinition("vir:north course", 3614.832f, 3, new float[] {1599f, 2371f}),
            new TrackDefinition("vir:patriot course", 1535.824f, 2, new float[] {837f, 0f}),
            new TrackDefinition("vir:patriot reverse course", 1543.93f, 2, new float[] {704f, 3376f}),
            new TrackDefinition("vir:south course", 2586.035f, 2, new float[] {1370f, 0f}),
            new TrackDefinition("ks_zandvoort:", 4189.691f, 2, new float[] {1986f, 0f}),
            new TrackDefinition("paul_ricard:gt_24h", 5776.583f, 3, new float[] {2971.514f, 4184.762f}),
            new TrackDefinition("paul_ricard:wtcc", 3804.753f, 3, new float[] {759.0595f, 2207.232f})

        };
        #endregion

        /// <summary>
        /// Get track landmarks data from the default file, and then from any
        /// user created files in the track landmarks folder. User created files
        /// will be prepended to the list so they will be checked first when
        /// looking for landmarks for a track.
        /// </summary>
        public static void loadTrackLandmarksData()
        {
            TRACK_LANDMARKS_DATA = TrackLandmarksData.getTrackLandmarksDataFromFile(DataFiles.default_track_landmarks);
#if DEBUG
            checkForDuplicates();
#endif

            loadUserCreatedTrackLandmarkFiles();
#if UPDATE_DEFAULT_TRACKLANDMARKS
    #if DEBUG
            UpdateDefaultTrackLandmarks();
    #endif
#endif
        }
        static void loadUserCreatedTrackLandmarkFiles()
        {
            String userLandmarks = DataFiles.track_landmarksFolder;
            if(Directory.Exists(userLandmarks))
            {
                ProcessDirectory(userLandmarks);
            }
            else
            {
                Console.WriteLine("No user defined landmarks found");
            }
        }

        private static void ProcessDirectory(string targetDirectory)
        {
            string[] fileEntries = Directory.GetFiles(targetDirectory, "*.json");

            foreach (string fileName in fileEntries)
            {
                TrackLandmarksData data = TrackLandmarksData.getTrackLandmarksDataFromFile(fileName);
                if (TRACK_LANDMARKS_DATA == null)
                {
                    TRACK_LANDMARKS_DATA = data;
                }
                else
                {
#if CHECK_FOR_DUPLICATES  // temporary code used once and saved for possible future use
                    var endIndex = TRACK_LANDMARKS_DATA.trackLandmarksData.Count;
                    foreach (var trackLandmark in data.trackLandmarksData)
                    {
                        bool alreadyExists = false;
                        // If this entry has an AMS2 track name, prefer matching on that to avoid duplicates
                        if (!string.IsNullOrEmpty(trackLandmark.ams2TrackName))
                        {
                            alreadyExists = TRACK_LANDMARKS_DATA.trackLandmarksData
                                .Any(t => !string.IsNullOrEmpty(t.ams2TrackName) &&
                                          String.Equals(t.ams2TrackName, trackLandmark.ams2TrackName, StringComparison.OrdinalIgnoreCase));
                        }

                        if (!alreadyExists)
                        {
                            if (trackLandmark.aceTrackNames != null)
                            {
                                alreadyExists = TRACK_LANDMARKS_DATA.trackLandmarksData
                                .Any(t => t.aceTrackNames != null &&
                                          String.Equals(t.aceTrackNames[0], trackLandmark.aceTrackNames[0], StringComparison.OrdinalIgnoreCase));
                            }
                        }
                        if (!alreadyExists)
                        {
                            TRACK_LANDMARKS_DATA.trackLandmarksData.Insert(endIndex++, trackLandmark);
                        }
                        else
                        {
                            Console.WriteLine("Skipping duplicate track landmarks for " + trackLandmark.ams2TrackName);
                        }
                    }
                }
#else
                    TRACK_LANDMARKS_DATA.trackLandmarksData.InsertRange(0, data.trackLandmarksData);
#endif
                }

                string[] subdirectoryEntries = Directory.GetDirectories(targetDirectory);
                foreach (string subdirectory in subdirectoryEntries)
                {
                    ProcessDirectory(subdirectory);
                }
            }
        }

        public static bool useTurnNumbers { get; set; } = UserSettings.GetUserSettings().getBoolean("use_turn_numbers");
        public static String getLandmarkForLapDistance(TrackDefinition currentTrack, float lapDistance)
        {
            if (currentTrack != null && lapDistance > 0 && currentTrack.trackLandmarks != null)
            {
                foreach (TrackLandmark trackLandmark in currentTrack.trackLandmarks)
                {
                    if (lapDistance > trackLandmark.distanceRoundLapStart && lapDistance < trackLandmark.distanceRoundLapEnd)
                    {
                        return useTurnNumbers && trackLandmark.landmarkNames.Count > 1 ? 
                            trackLandmark.landmarkNames[1] :
                            trackLandmark.landmarkName;
                    }
                }
                // check again with more generous limits
                foreach (TrackLandmark trackLandmark in currentTrack.trackLandmarks)
                {
                    if (lapDistance > (Math.Max(0, trackLandmark.distanceRoundLapStart - 70)) &&
                        lapDistance < Math.Min(currentTrack.trackLength, trackLandmark.distanceRoundLapEnd + 70))
                    {
                        return useTurnNumbers && trackLandmark.landmarkNames.Count > 1 ?
                            trackLandmark.landmarkNames[1] :
                            trackLandmark.landmarkName;
                    }
                }

            }
            return null;
        }

        /// <summary>
        /// R3E: get an empty track definition with the name and id
        /// </summary>
        public static TrackDefinition getTrackDefinition(String trackName, int trackId, float trackLength)
        {
            var definition = new TrackDefinition(trackName, trackId, trackLength);
            return definition;
        }
        /// <summary>
        /// Other games: get an empty track definition with the name and length
        /// AMS2, iRacing, PCARS2, PPMR, R3E, Dirt
        /// </summary>
        public static TrackDefinition getTrackDefinition(String trackName, float trackLength)
        {
            TrackDefinition definition;
            if (trackName != null)
            {
                definition = new TrackDefinition(trackName, trackLength);
            }
            else
            {
                definition = new TrackDefinition("unknown track , length = " + trackLength, trackLength);
            }
            return definition;
        }

        /// <summary>
        /// Get one of the fixed track definitions (used by assetto, acc and pCars)
        /// </summary>
        public static TrackDefinition getTrackDefinition(String trackName, float trackLength, int sectorsOnTrack = 3)
        {
            TrackDefinition definition = null;
            List<TrackDefinition> tracks = null;
            switch (Game.gameType)
            {
                case GameType.ACC:
                    tracks = accTracks;
                    break;
                case GameType.ASSETTO:
                    tracks = assettoTracks;
                    break;
                case GameType.PCARS:
                    {
                        List<TrackDefinition> defsWhichMatchName = new List<TrackDefinition>();
                        foreach (TrackDefinition def in pCarsTracks)
                        {
                            if (def.name == trackName)
                            {
                                defsWhichMatchName.Add(def);
                            }
                        }
                        if (defsWhichMatchName.Count == 1)
                        {
                            definition = defsWhichMatchName[0];
                        }
                        TrackDefinition defGuessedFromLength = null;
                        if (defsWhichMatchName.Count > 1)
                        {
                            defGuessedFromLength = getTrackDefinitionForLength(defsWhichMatchName, trackLength, 2);
                        }
                        else
                        {
                            defGuessedFromLength = getTrackDefinitionForLength(pCarsTracks, trackLength, 2);
                        }
                        if (defGuessedFromLength != null)
                        {
                            definition = defGuessedFromLength;
                        }
                        String nameToUse = trackName != null ? trackName : "unknown track (no name)";
                        definition = new TrackDefinition(nameToUse, trackLength);
                    }
                    break;
                default:
                    tracks = new List<TrackDefinition>();
                    break;
            }
            foreach (TrackDefinition def in tracks)
            {
                if (def.name.Equals(trackName))
                {
                    definition = def;
                    break;
                }
            }
            if (definition == null)
            {
                definition = new TrackDefinition(trackName, trackLength, sectorsOnTrack, new float[] { 0f, 0f });
                definition.unknownTrack = true;
                definition.setSectorPointsForUnknownTracks();
            }

            return definition;
        }

        private static TrackDefinition getTrackDefinitionForLength(List<TrackDefinition> possibleDefinitions, float trackLength, int maxError)
        {
            TrackDefinition closestLengthDef = null;
            float closestLengthDifference = float.MaxValue;
            foreach (TrackDefinition def in possibleDefinitions)
            {
                if (def.trackLength == trackLength)
                {
                    return def;
                }
                else
                {
                    float thisDiff = Math.Abs(trackLength - def.trackLength);
                    if (thisDiff < maxError)
                    {
                        if (closestLengthDef == null || thisDiff < closestLengthDifference)
                        {
                            closestLengthDef = def;
                            closestLengthDifference = thisDiff;
                        }
                    }
                }
            }
            return closestLengthDef;
        }

        internal static TrackLengthClass getLengthClass(float length)
        {
            if (length > 20000)
            {
                return TrackLengthClass.VERY_LONG;
            }
            if (length > 10000)
            {
                return TrackLengthClass.LONG;
            }
            if (length < 1000)
            {
                return TrackLengthClass.VERY_SHORT;
            }
            if (length < 2400)
            {
                return TrackLengthClass.SHORT;
            }
            return TrackLengthClass.MEDIUM;
        }
    }

    /// <summary>
    /// Contains the data for a track, particularly the track landmarks
    /// for a particular track in the CURRENT game. Very like TrackDataContainer...
    /// </summary>
    public class TrackDefinition
    {
        // TrackDataContainer
        public List<TrackLandmark> trackLandmarks;
        public Boolean isOval = false;
        public float raceroomRollingStartLapDistance = -1.0f;
        public Boolean isDefinedInTracklandmarksData = true;
        public float iracingPitEntranceDistanceRoundTrack = -1.0f;
        public float[] pitApproachPoint = null;

        // plus
        public int id;
        public String name = "";
        public float trackLength;
        public Boolean hasPitLane;
        public float[] pitEntryPoint = new float[] { 0, 0 };
        public float[] pitExitPoint = new float[] { 0, 0 };
        public float[] gapPoints = new float[] { };
        public float pitEntryExitPointsDiameter = 3;   // if we're within this many metres of the pit entry point, we're entering the pit
        public int sectorsOnTrack = 3;
        public float[] sectorPoints = new float[] { 0, 0 };
        public Boolean unknownTrack = false;
        // this is the distance round the track where we save the opponent's race position before he slows for pit entry
        public float distanceForNearPitEntryChecks;
        public TrackData.TrackLengthClass trackLengthClass = TrackData.TrackLengthClass.MEDIUM;
        public float iracingTrackNorthOffset = -1;

        internal TrackDefinition(String name, float pitEntryExitPointsDiameter, float trackLength, float[] pitEntryPoint, float[] pitExitPoint)
        {
            defaultTrackDefinition(name, trackLength);
            this.hasPitLane = true;
            this.pitEntryPoint = pitEntryPoint;
            this.pitExitPoint = pitExitPoint;
            this.pitEntryExitPointsDiameter = pitEntryExitPointsDiameter;
        }

        internal TrackDefinition(String name, float trackLength)
        {
            defaultTrackDefinition(name, trackLength);
        }

        internal TrackDefinition(String name, int id, float trackLength)
        {
            defaultTrackDefinition(name, trackLength);
            this.id = id;
        }

        internal TrackDefinition(String name, float trackLength, int sectorsOnTrack, float[] sectorPoints)
        {
            defaultTrackDefinition(name, trackLength);
            this.hasPitLane = true;
            this.sectorsOnTrack = sectorsOnTrack;
            this.sectorPoints = sectorPoints;
        }

        private void defaultTrackDefinition(String name, float trackLength)
        {
            this.name = name;
            this.trackLength = trackLength;
            this.trackLengthClass = TrackData.getLengthClass(trackLength);
            // hard-code this to 300metres before start line for now, but it needs to be overrideable on a per-track basis
            this.distanceForNearPitEntryChecks = trackLength - 300;
            this.hasPitLane = false;
        }

        public void setGapPoints()
        {
            // special case for 2 sector tracks
            if (sectorsOnTrack == 2)
            {
                gapPoints = new float[] {(float)Math.Round(trackLength / 2f), trackLength - 50};
            }
            else if (trackLength > TrackData.gapPointsThreshold)
            {
                float totalGaps = 0;
                List<float> gaps = new List<float>();
                while (totalGaps < trackLength)
                {
                    totalGaps += TrackData.gapPointSpacing;
                    if (totalGaps < trackLength - TrackData.gapPointSpacing)
                    {
                        gaps.Add(totalGaps);
                    }
                    else
                    {
                        break;
                    }
                }
                // the gapPoints are used instead of the sector / start-finish line for opponent gaps.
                // We need to ensure our 1st gap point is near, but not on, the start-finish line (so the lap
                // distance between previous and current game states has increased). Yes. A hack.
                // This final gap point is just before the start-finish line
                gaps.Add(trackLength - 50);

                gapPoints = gaps.ToArray();
            }
        }

        public void adjustGapPoints(List<Tuple<float,float>> hardParts)
        {
            if (trackLength > TrackData.gapPointsThreshold)
            {
                float totalGaps = 0;
                List<float> gaps = new List<float>();
                while (totalGaps < trackLength)
                {
                    totalGaps += TrackData.gapPointSpacing;
                    if (totalGaps < trackLength - TrackData.gapPointSpacing)
                    {
                        foreach(Tuple<float,float> hardPart in hardParts)
                        {
                            if (totalGaps >= hardPart.Item1 && totalGaps <= hardPart.Item2)
                            {
                                totalGaps = hardPart.Item2;
                            }
                        }
                        gaps.Add(totalGaps);
                    }
                    else
                    {
                        break;
                    }
                }
                // the gapPoints are used instead of the sector / start-finish line for opponent gaps.
                // We need to ensure our 1st gap point is near, but not on, the start-finish line (so the lap
                // distance between previous and current game states has increased). Yes. A hack.
                // This final gap point is just before the start-finish line
                gaps.Add(trackLength - 50);

                gapPoints = gaps.ToArray();
            }
        }
        public void setSectorPointsForUnknownTracks()
        {
            // tracks can be 2 or 3 sectors long, nothing else. If the game reports 2 sectors we assume that's correct,
            // but for anything else we default to 3 sectors
            if (sectorsOnTrack != 2)
            {
                sectorsOnTrack = 3;
            }
            float sectorSpacing = trackLength / sectorsOnTrack;
            sectorPoints[0] = sectorSpacing;
            sectorPoints[1] = sectorSpacing * 2;
        }

        public Boolean isAtPitEntry(float x, float y)
        {
            return hasPitLane && Math.Abs(pitEntryPoint[0] - x) < pitEntryExitPointsDiameter &&
                Math.Abs(pitEntryPoint[1] - y) < pitEntryExitPointsDiameter;
        }

        public Boolean isAtPitExit(float x, float y)
        {
            return hasPitLane && Math.Abs(pitExitPoint[0] - x) < pitEntryExitPointsDiameter &&
                Math.Abs(pitExitPoint[1] - y) < pitEntryExitPointsDiameter;
        }
    }
}
