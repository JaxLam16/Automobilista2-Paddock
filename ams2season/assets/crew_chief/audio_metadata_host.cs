// Read-only metadata adapters: original selection/number logic, no devices/TTS/network.
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using CrewChiefV4.Audio;
using CrewChiefV4.NumberProcessing;

namespace CrewChiefV4 {
    public class Utilities { public static Random random=new Random(); }
    public class Game { public static readonly bool IRACING=false; }
    public class Configuration {
        public static Dictionary<string,object> Values;
        public static string getSoundConfigOption(string key) { return Convert.ToString(Values[key]); }
    }
    public class NumberReaderFactory { public static bool IS_ENGLISH=true; }
    public class MessageFragment {
        public object value;
        public static MessageFragment Text(string value) { return new MessageFragment{value=value}; }
        public static MessageFragment Integer(int value) { return new MessageFragment{value=value}; }
    }
    public class NoisyCartesianCoordinateSpotter { public static string folderSpotterRadioCheckBSlash; }
    public class Log { public static void Debug(Func<string> text) {} public static void Exception(Exception e,string text="") {} }
}
namespace CrewChiefV4.GameState {
    public class GameStateData { public static DateTime CurrentTime=DateTime.MinValue; }
    public class GlobalBehaviourSettings { public static bool noMinutesInLapTimes,useHundredths,useOvalLogic; }
}
namespace CrewChiefV4.Events {
    public class AbstractEvent { public static string Pause(int length) { return "insert_pause:"+length; } }
}
namespace CrewChiefV4.Audio {
    public class SoundPackVersionsHelper { public static float currentSoundPackVersion; }
    public class AudioPlayer {
        public const string PAUSE_ID="insert_pause";
        public static bool playWithNAudio=false,rantWaitingToPlay=false,TraineeChiefAvailable=false;
    }
    public class SoundMetadata {}
    public class SubtitleManager {
        public static bool enableSubtitles=false;
        public static void AddPhrase(List<SingleSound> sounds,SoundMetadata metadata) {}
    }
    // Original SoundCache.Play calls Thread.Sleep only for pauses. Export those
    // pauses as metadata; the real Paddock audio worker renders them into PCM.
    public class Thread { public static void Sleep(int milliseconds) { AudioCapture.Pause(milliseconds); } }
    public class AudioCapture {
        public static List<object> Parts=new List<object>();
        public static void Pause(int milliseconds) { Parts.Add(new {pause_ms=milliseconds}); }
    }
    public class SingleSound {
        public string fullPath;
        public bool isSweary,isSpotter,isBleep,isPause,cacheSoundPlayerPermanently;
        public int pauseLength;
        public SoundSet prefixSoundSet,suffixSoundSet;
        public SingleSound(string path,bool cacheData,bool cachePlayer,bool permanent) { fullPath=path;cacheSoundPlayerPermanently=permanent; }
        public SingleSound(int milliseconds) { isPause=true;pauseLength=milliseconds; }
        public SingleSound(string text) { throw new NotSupportedException("No live TTS in original audio metadata host."); }
        public SingleSound(string url,bool download) { throw new NotSupportedException("No downloads in original audio metadata host."); }
        public void LoadAndCacheSound() {} public void LoadAndCacheFile() {}
        public bool UnLoad() { return true; } public void Stop() {}
        public void Play(SoundMetadata metadata) { AudioCapture.Parts.Add(new {file=fullPath}); }
    }
    public partial class SoundCache {
        public const string TTS_IDENTIFIER="TTS_IDENTIFIER",DOWNLOAD_IDENTIFIER="DOWNLOAD_IDENTIFIER";
        public static bool IS_PLAYING,recordVarietyData;
        public static int prefixesAndSuffixesCount,swearySoundsSkipped,maleSoundsSkipped,pauseBetweenFragments;
        public static DateTime lastSwearyMessageTime=DateTime.MinValue;
        public static HashSet<string> availablePrefixesAndSuffixes=new HashSet<string>(),availableSounds=new HashSet<string>();
        public static Dictionary<string,SingleSound> singleSounds=new Dictionary<string,SingleSound>();
        public static Dictionary<string,SoundSet> soundSets=new Dictionary<string,SoundSet>();
        Dictionary<string,SingleSound> singleSounds2ndChief=new Dictionary<string,SingleSound>();
        Dictionary<string,SoundSet> soundSets2ndChief=new Dictionary<string,SoundSet>();
        bool useSwearyMessages,useMaleSounds;
        static bool allowCaching=false;
        double minSecondsBetweenPersonalisedMessages;
        DateTime lastPersonalisedMessageTime=DateTime.MinValue;
        string root;
        readonly Dictionary<string,string> driverFiles=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
        public static void addUseToVarietyData(string folder,int count) {}
        private void moveToTopOfCache(string name) {}
        public SoundCache(string root,bool sweary,bool male,int minimumPersonalisationSeconds,string personalisation) {
            this.root=Path.GetFullPath(root);this.useSwearyMessages=sweary;this.useMaleSounds=male;
            minSecondsBetweenPersonalisedMessages=minimumPersonalisationSeconds;
            string names=Path.Combine(this.root,"driver_names");
            if(Directory.Exists(names))foreach(string file in Directory.GetFiles(names,"*.wav"))
                driverFiles[Path.GetFileNameWithoutExtension(file)]=file;
            if(!String.IsNullOrEmpty(personalisation)) {
                if(personalisation.IndexOfAny(Path.GetInvalidFileNameChars())>=0 || personalisation.Contains("..")) throw new ArgumentException("Invalid personalisation name.");
                var directory=new DirectoryInfo(Path.Combine(root,"personalisations"));
                if(directory.Exists) preparePrefixesAndSuffixes(directory,personalisation,false,soundSets,availablePrefixesAndSuffixes);
            }
        }
        public bool Prepare(string folder) {
            string driverFile;
            if(driverFiles.TryGetValue(folder,out driverFile)) {
                if(!singleSounds.ContainsKey(folder))singleSounds[folder]=new SingleSound(driverFile,false,false,false);
                return true;
            }
            if(!Regex.IsMatch(folder,@"^(spotter(?:_[A-Za-z0-9 _-]+)?|engine_monitor|tyre_monitor|lap_times|damage_reporting|fuel|race_time|position|timings|penalties|flags|numbers|conditions|acknowledge|mandatory_pit_stops|rants|pearls_of_wisdom)/[A-Za-z0-9_-]+$|^battery/(percent|laps|minutes)$|^lap_counter/[A-Za-z0-9_]+$|^opponents/(car_number|one_lap_ahead|one_lap_behind)$|^strategy/a_pitstop_costs_us_about$|^frozen_order/(kilometres_per_hour|miles_per_hour|thats_a_rolling_start|in_the_left_column|in_the_right_column|allow_guy_behind_to_pass)$")) throw new ArgumentException("Unsupported sound folder.");
            if(soundSets.ContainsKey(folder)) return soundSets[folder].hasSounds;
            var path=new DirectoryInfo(Path.Combine(root,"voice",folder));
            if(!path.Exists) return false;
            var set=new SoundSet(path,useSwearyMessages,useMaleSounds,false,false,false,false,soundSets);
            soundSets[folder]=set;if(set.hasSounds) availableSounds.Add(folder);
            return set.hasSounds;
        }
    }
}
public class PaddockAudioHost {
    static JavaScriptSerializer json=new JavaScriptSerializer();
    static List<string> Expand(object value,CrewChiefV4.NumberReader reader,bool last) {
        if(value is string) return new List<string>{(string)value};
        if(value is Dictionary<string,object>) {
            var p=(Dictionary<string,object>)value;
            string kind=(string)p["type"];
            if(kind=="time") {
                var precision=(Precision)Enum.Parse(typeof(Precision),(string)p["precision"]);
                double seconds=Convert.ToDouble(p["seconds"],CultureInfo.InvariantCulture);
                if(Double.IsNaN(seconds)||Double.IsInfinity(seconds)||seconds<0||seconds>=86400) throw new ArgumentException("Invalid original time fragment.");
                return reader.ConvertTimeToSounds(new TimeSpanWrapper(TimeSpan.FromSeconds(seconds),precision),!last);
            }
            if(kind=="car_number") {
                string number=(string)p["value"];
                if(!Regex.IsMatch(number,@"^\d{1,5}$")) throw new ArgumentException("Invalid car number.");
                return new CarNumber(number).getMessageFragments().SelectMany(f=>Expand(f.value,reader,last)).ToList();
            }
            if(kind=="integer") return reader.GetIntegerSounds(Convert.ToInt32(p["value"]),!p.ContainsKey("short")||(bool)p["short"],!last);
            throw new ArgumentException("Unknown original audio fragment.");
        }
        if(value is int || value is long || value is decimal || value is double) {
            double number=Convert.ToDouble(value,CultureInfo.InvariantCulture);
            if(number!=Math.Truncate(number)||number < -99999||number>99999) throw new ArgumentException("Invalid integer fragment.");
            return reader.GetIntegerSounds((int)number,true,!last);
        }
        throw new ArgumentException("Unsupported original audio fragment.");
    }
    public static void Run(string defaults,string sounds) {
        var output=Console.Out;Console.SetOut(TextWriter.Null);
        var config=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(defaults));
        CrewChiefV4.Configuration.Values=(Dictionary<string,object>)config["number_config"];
        SoundPackVersionsHelper.currentSoundPackVersion=Convert.ToSingle(config["sound_pack_version"]);
        SoundCache.pauseBetweenFragments=Convert.ToInt32(config["pause_between_message_fragments"]);
        var cache=new SoundCache(sounds,(bool)config["use_sweary_messages"],!(bool)config["block_male_sounds"],Convert.ToInt32(config["min_time_between_personalised_messages"]),(string)config["personalisation"]);
        var reader=new NumberReaderEn();
        // CarNumber's leading-zero choices inspect the loaded sound inventory.
        cache.Prepare("numbers/zerozero");cache.Prepare("numbers/double_oh");
        Action<object> reply=p=>{ output.WriteLine(json.Serialize(p));output.Flush(); };
        reply(new {ready=true,version="4.19.5.4"});
        string line;
        while((line=Console.ReadLine())!=null) {
            try {
                var p=json.Deserialize<Dictionary<string,object>>(line);
                string operation=(string)p["op"];
                if(operation=="prepare") {
                    var available=new List<string>();foreach(string folder in (IEnumerable)p["folders"]) if(cache.Prepare(folder)) available.Add(folder);
                    reply(new {available=available,personalised=available.Where(f=>SoundCache.soundSets.ContainsKey(f) && SoundCache.soundSets[f].hasPrefixOrSuffix).ToArray()});continue;
                }
                CrewChiefV4.GameState.GameStateData.CurrentTime=new DateTime(2026,1,1,0,0,0,DateTimeKind.Utc).AddSeconds(Convert.ToDouble(p["t"]));
                CrewChiefV4.GameState.GlobalBehaviourSettings.useHundredths=p.ContainsKey("hundredths") && (bool)p["hundredths"];
                CrewChiefV4.GameState.GlobalBehaviourSettings.useOvalLogic=p.ContainsKey("oval") && (bool)p["oval"];
                CrewChiefV4.GameState.GlobalBehaviourSettings.noMinutesInLapTimes=(bool)config["no_minutes_in_lap_times"];
                var fragments=((IEnumerable)p["fragments"]).Cast<object>().ToList();var names=new List<string>();
                for(int i=0;i<fragments.Count;i++) {
                    // Original QueuedMessage ignores a trailing literal pause.
                    if(i==fragments.Count-1 && fragments[i] is string && ((string)fragments[i]).StartsWith(AudioPlayer.PAUSE_ID)) break;
                    var expanded=Expand(fragments[i],reader,i==fragments.Count-1);
                    if(expanded.Count==0) throw new ArgumentException("Original number reader found no playable sounds.");
                    names.AddRange(expanded);
                }
                if(names.Count==0) throw new ArgumentException("Empty original sound request.");
                if(operation=="expand") { reply(new {folders=names});continue; }
                foreach(var name in names) if(!name.StartsWith(AudioPlayer.PAUSE_ID) && !cache.Prepare(name)) throw new ArgumentException("Original sound unavailable: "+name);
                AudioCapture.Parts.Clear();cache.Play(names,new SoundMetadata());
                reply(new {parts=AudioCapture.Parts,folders=names});
            } catch(Exception e) { reply(new {error=e.GetType().Name+": "+e.Message}); }
        }
    }
}
