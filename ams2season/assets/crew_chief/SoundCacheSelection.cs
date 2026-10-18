using System;
using System.IO;
using System.Collections.Generic;
using System.Linq;
using CrewChiefV4.GameState;
namespace CrewChiefV4.Audio { public partial class SoundCache {
        internal Boolean personalisedMessageIsDue()
        {
            double secondsSinceLastPersonalisedMessage = (GameStateData.CurrentTime - lastPersonalisedMessageTime).TotalSeconds;
            Boolean due = false;
            if (minSecondsBetweenPersonalisedMessages == 0)
            {
                due = false;
            }
            else if (secondsSinceLastPersonalisedMessage > minSecondsBetweenPersonalisedMessages)
            {
                // we can now select a personalised message, but we don't always do this - the probability is based
                // on the time since the last one
                due = Utilities.random.NextDouble() < 1.2 - minSecondsBetweenPersonalisedMessages / secondsSinceLastPersonalisedMessage;
            }
            return due;
        }

        public static bool trainee_active()
        {
            return AudioPlayer.TraineeChiefAvailable;
        }

        public void Play(List<String> soundNames, SoundMetadata soundMetadata, bool mute = false)
        {
            List<SingleSound> singleSoundsToPlay = null;
            SoundSet prefix = null;
            SoundSet suffix = null;
            List<string> cacheable = null;
               
            if (trainee_active() && (singleSounds2ndChief.Count > 0 || soundSets2ndChief.Count > 0))
            {
                (singleSoundsToPlay, prefix, suffix, cacheable) = Play_(soundNames, singleSounds2ndChief, soundSets2ndChief);
            }
            if (singleSoundsToPlay == null || singleSoundsToPlay.Count == 0)
            {
                (singleSoundsToPlay, prefix, suffix, cacheable) = Play_(soundNames, SoundCache.singleSounds, SoundCache.soundSets);
            }
            else
            {
                Log.Debug(() => $"trainee crew chief hijacked {String.Join(",", soundNames)}");
            }

            if (singleSoundsToPlay == null || singleSoundsToPlay.Count == 0)
            {
                Console.WriteLine("No playable sounds could be found for " + String.Join(", ", soundNames));
                return;
            }

            try
            {
                foreach (var soundName in cacheable)
                {
                    moveToTopOfCache(soundName);
                }

                if (prefix != null)
                {
                    SingleSound prefixSound = prefix.getSingleSound(false);
                    if (prefixSound != null)
                    {
                        singleSoundsToPlay.Insert(0, prefixSound);
                        lastPersonalisedMessageTime = GameStateData.CurrentTime;
                    }
                }
                if (suffix != null)
                {
                    SingleSound suffixSound = suffix.getSingleSound(false);
                    if (suffixSound != null)
                    {
                        singleSoundsToPlay.Add(suffixSound);
                        lastPersonalisedMessageTime = GameStateData.CurrentTime;
                    }
                }
                if (SubtitleManager.enableSubtitles)
                {
                    SubtitleManager.AddPhrase(singleSoundsToPlay, soundMetadata);
                }

                if (mute)
                {
                    return;
                }

                SoundCache.IS_PLAYING = true;
                int firstSoundPosition = prefix == null ? 0 : 1;
                int lastSoundPosition = suffix == null ? singleSoundsToPlay.Count - 1 : singleSoundsToPlay.Count - 2;
                for (int i=0; i<singleSoundsToPlay.Count; i++)
                {
                    SingleSound singleSound = singleSoundsToPlay[i];
                    if (singleSound.isPause)
                    {
                        Thread.Sleep(singleSound.pauseLength);
                    }
                    else
                    {
                        singleSound.Play(soundMetadata);
                    }
                    // can add a pause between sounds (so not at the start or end of the list), skipping a prefix or suffix (personalisation)
                    bool addPause = SoundCache.pauseBetweenFragments > 0 && i >= firstSoundPosition && i < lastSoundPosition;
                    if (addPause)
                    {
                        Thread.Sleep(SoundCache.pauseBetweenFragments);
                    }
                }
            }
            finally
            {
                SoundCache.IS_PLAYING = false;
            }
        }

        private (List<SingleSound>, SoundSet, SoundSet, List<String>) Play_(
            List<String> soundNames,
            Dictionary<string, SingleSound> singleSounds,
            Dictionary<string, SoundSet> soundSets)
        {
            SoundSet prefix = null;
            SoundSet suffix = null;
            List<SingleSound> singleSoundsToPlay = new List<SingleSound>();
            List<String> cacheable = new List<String>();
            foreach (String soundName in soundNames)
            {
                if (soundName.StartsWith(AudioPlayer.PAUSE_ID))
                {
                    int pauseLength = 500;
                    try
                    {
                        String[] split = soundName.Split(':');
                        if (split.Count() == 2)
                        {
                            pauseLength = int.Parse(split[1]);
                        }
                    }
                    catch (Exception e) { Log.Exception(e); }
                    singleSoundsToPlay.Add(new SingleSound(pauseLength));
                }
                else if (soundName.StartsWith(TTS_IDENTIFIER))
                {
                    SingleSound singleSound = null;
                    if (!singleSounds.TryGetValue(soundName, out singleSound))
                    {
                        singleSound = new SingleSound(soundName.Substring(TTS_IDENTIFIER.Count()));
                        singleSounds.Add(soundName, singleSound);
                    }
                    cacheable.Add(soundName);
                    singleSoundsToPlay.Add(singleSound);
                }
                else if (soundName.StartsWith(DOWNLOAD_IDENTIFIER))
                {
                    SingleSound singleSound = null;
                    if (!singleSounds.TryGetValue(soundName, out singleSound))
                    {
                        singleSound = new SingleSound(soundName.Substring(DOWNLOAD_IDENTIFIER.Count()), true);
                        singleSounds.Add(soundName, singleSound);
                    }
                    cacheable.Add(soundName);
                    singleSoundsToPlay.Add(singleSound);
                }
                else
                {
                    Boolean preferPersonalised = personalisedMessageIsDue();
                    SingleSound singleSound = null;
                    SoundSet soundSet = null;
                    if (soundSets.TryGetValue(soundName, out soundSet))
                    {
                        // double check whether this soundSet wants to allow personalisations at this point -
                        // this prevents the app always choosing the personalised version of a sound if this sound is infrequent
                        if (soundSet.forceNonPersonalisedVersion())
                        {
                            preferPersonalised = false;
                        }
                        singleSound = soundSet.getSingleSound(preferPersonalised);
                        if (!soundSet.cacheSoundPlayersPermanently)
                        {
                            cacheable.Add(soundName);
                        }
                    }
                    else if (singleSounds.TryGetValue(soundName, out singleSound))
                    {
                        if (!singleSound.cacheSoundPlayerPermanently)
                        {
                            cacheable.Add(soundName);
                        }
                    }

                    if (singleSound == null)
                    {
                        return (null, null, null, null);
                    }
                    else
                    {
                        // hack... we double check the prefer setting here and only play the prefix / suffix if it's true.
                        // The list without prefixes and suffixes includes items which have optional ones, so we might want to
                        // play a sound that can have the prefix / suffix, but not the associated prefix / suffix
                        if (preferPersonalised && singleSound.prefixSoundSet != null)
                        {
                            prefix = singleSound.prefixSoundSet;
                        }
                        if (preferPersonalised && singleSound.suffixSoundSet != null)
                        {
                            suffix = singleSound.suffixSoundSet;
                        }
                        singleSoundsToPlay.Add(singleSound);
                    }
                }
            }
            return (singleSoundsToPlay, prefix, suffix, cacheable);
        }

        private void preparePrefixesAndSuffixes(DirectoryInfo personalisationsDirectory, String selectedPersonalisation, bool verbose,
            Dictionary<string, SoundSet> soundSets,
            HashSet<string> availablePrefixesAndSuffixes)
        {
            if(verbose)
            {
                Console.WriteLine("Preparing personalisations for selected name " + selectedPersonalisation);
            }
            DirectoryInfo[] namesFolders = personalisationsDirectory.GetDirectories(selectedPersonalisation);
            foreach (DirectoryInfo namesFolder in namesFolders)
            {
                if (namesFolder.Name.Equals(selectedPersonalisation, StringComparison.InvariantCultureIgnoreCase))
                {
                    DirectoryInfo[] nameSubfolders = namesFolder.GetDirectories();
                    foreach (DirectoryInfo nameSubfolder in nameSubfolders)
                    {
                        if (nameSubfolder.Name.Equals("prefixes_and_suffixes"))
                        {
                            foreach (DirectoryInfo prefixesAndSuffixesFolder in nameSubfolder.GetDirectories())
                            {
                                // the lookup of all soundsets is not used when loading the prefixes/suffixes
                                var disposable = new Dictionary<string, SoundSet>();
                                // always keep the personalisations cached as they're reused frequently, so create the sound players immediately after the files are loaded
                                SoundSet soundSet = new SoundSet(prefixesAndSuffixesFolder, this.useSwearyMessages, this.useMaleSounds,
                                    allowCaching, allowCaching, true, true, disposable);
                                if (soundSet.hasSounds)
                                {
                                    availablePrefixesAndSuffixes.Add(prefixesAndSuffixesFolder.Name);
                                    soundSets.Add(prefixesAndSuffixesFolder.Name, soundSet);
                                }
                            }
                            break;
                        }
                    }
                    break;
                }
            }
            if (verbose)
            {
                Console.WriteLine("Prepare personalisations completed");
            }
        }
} }
