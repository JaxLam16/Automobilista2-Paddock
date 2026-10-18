using System;
using System.IO;
using System.Collections.Generic;
using System.Linq;
using CrewChiefV4.GameState;
namespace CrewChiefV4.Audio {
    public class SoundSet
    {
        private List<SingleSound> singleSoundsNoPrefixOrSuffix = new List<SingleSound>();
        private List<SingleSound> singleSoundsWithPrefixOrSuffix = new List<SingleSound>();
        private DirectoryInfo soundFolder;
        private Boolean useSwearyMessages;
        private Boolean useMaleSounds;
        private Boolean cacheSoundPlayers;
        private Boolean cacheFileData;
        private Boolean eagerlyCreateSoundPlayers;
        internal Boolean cacheSoundPlayersPermanently;
        internal Boolean hasSounds = false;
        private int soundsCount;
        internal Boolean hasPrefixOrSuffix = false;
        private List<int> prefixOrSuffixIndexes = null;
        private int prefixOrSuffixIndexesPosition = 0;
        private List<int> indexes = null;
        private int indexesPosition = 0;
        const String OPTIONAL_PREFIX_IDENTIFIER = "op_prefix";
        const String OPTIONAL_SUFFIX_IDENTIFIER = "op_suffix";
        const String REQUIRED_PREFIX_IDENTIFIER = "rq_prefix";
        const String REQUIRED_SUFFIX_IDENTIFIER = "rq_suffix";

        // allow the non-personalised versions of this soundset to play, if it's not frequent and has personalisations
        private Boolean lastVersionWasPersonalised = false;

        internal SoundSet(DirectoryInfo soundFolder, Boolean useSwearyMessages, Boolean useMaleSounds, Boolean cacheFileData, Boolean cacheSoundPlayers,
            Boolean cacheSoundPlayersPermanently, Boolean eagerlyCreateSoundPlayers, Dictionary<String, SoundSet> allSoundSets)
        {
            this.soundsCount = 0;
            this.soundFolder = soundFolder;
            this.useSwearyMessages = useSwearyMessages;
            this.useMaleSounds = useMaleSounds;
            this.cacheFileData = cacheFileData;
            this.cacheSoundPlayers = cacheSoundPlayers;
            this.eagerlyCreateSoundPlayers = eagerlyCreateSoundPlayers;
            this.cacheSoundPlayersPermanently = cacheSoundPlayersPermanently;
            initialise(allSoundSets);
        }

        internal Boolean forceNonPersonalisedVersion()
        {
            return lastVersionWasPersonalised && singleSoundsNoPrefixOrSuffix.Count > 0;
        }

        private void shuffle(List<int> list)
        {
            int n = list.Count;
            while (n > 1)
            {
                n--;
                int k = Utilities.random.Next(n + 1);
                int value = list[k];
                list[k] = list[n];
                list[n] = value;
            }
        }

        internal void loadAll()
        {
            foreach (SingleSound sound in singleSoundsNoPrefixOrSuffix)
            {
                if (eagerlyCreateSoundPlayers && !AudioPlayer.playWithNAudio)
                {
                    sound.LoadAndCacheSound();
                }
                else
                {
                    sound.LoadAndCacheFile();
                }
            }
            foreach (SingleSound sound in singleSoundsWithPrefixOrSuffix)
            {
                if (eagerlyCreateSoundPlayers && !AudioPlayer.playWithNAudio)
                {
                    sound.LoadAndCacheSound();
                }
                else
                {
                    sound.LoadAndCacheFile();
                }
            }
        }

        // allSoundSets is used to lookup prefixes and suffixes, in a very convoluted manner.
        // To facilitate this, it is expected that all the prefixes and suffixes have been
        // loaded first.
        private void initialise(Dictionary<String, SoundSet> allSoundSets)
        {
            try
            {
                FileInfo[] soundFiles = this.soundFolder.GetFiles("*.wav");
                foreach (FileInfo soundFile in soundFiles)
                {
                    Boolean isSweary = soundFile.Name.Contains("sweary");
                    Boolean isMale = soundFile.Name.Contains("male");   // the sound uses a term like 'he', 'man', 'fella' etc
                    Boolean isBleep = soundFile.Name.Contains("bleep");
                    Boolean isSpotter = soundFile.FullName.Contains(@"\spotter");
                    Boolean isOptional = soundFile.Name.Contains(OPTIONAL_PREFIX_IDENTIFIER) || soundFile.Name.Contains(OPTIONAL_SUFFIX_IDENTIFIER);
                    if (!isSpotter && NoisyCartesianCoordinateSpotter.folderSpotterRadioCheckBSlash != null)
                    {
                        isSpotter = soundFile.FullName.Contains(NoisyCartesianCoordinateSpotter.folderSpotterRadioCheckBSlash);
                    }
                    if ((this.useSwearyMessages || !isSweary) && (this.useMaleSounds || !isMale))
                    {
                        if (soundFile.Name.Contains(REQUIRED_PREFIX_IDENTIFIER) || soundFile.Name.Contains(REQUIRED_SUFFIX_IDENTIFIER) ||
                            isOptional)
                        {
                            foreach (String prefixSuffixName in SoundCache.availablePrefixesAndSuffixes)
                            {
                                SoundSet additionalSoundSet = null;
                                if (soundFile.Name.Contains(prefixSuffixName) && allSoundSets.TryGetValue(prefixSuffixName, out additionalSoundSet))
                                {
                                    if (additionalSoundSet.hasSounds)
                                    {
                                        hasPrefixOrSuffix = true;
                                        hasSounds = true;
                                        SingleSound singleSound = new SingleSound(soundFile.FullName, this.cacheFileData, this.cacheSoundPlayers, this.cacheSoundPlayersPermanently);
                                        if (eagerlyCreateSoundPlayers)
                                        {
                                            if (!AudioPlayer.playWithNAudio)
                                            {
                                                singleSound.LoadAndCacheSound();
                                            }
                                            else
                                            {
                                                singleSound.LoadAndCacheFile();
                                            }
                                        }
                                        singleSound.isSweary = isSweary;
                                        if (soundFile.Name.Contains(OPTIONAL_SUFFIX_IDENTIFIER) || soundFile.Name.Contains(REQUIRED_SUFFIX_IDENTIFIER))
                                        {
                                            singleSound.suffixSoundSet = additionalSoundSet;
                                        }
                                        else
                                        {
                                            singleSound.prefixSoundSet = additionalSoundSet;
                                        }
                                        singleSoundsWithPrefixOrSuffix.Add(singleSound);
                                        SoundCache.prefixesAndSuffixesCount++;
                                        soundsCount++;
                                    }
                                    break;
                                }
                            }
                            if (isOptional)
                            {
                                hasSounds = true;
                                SingleSound singleSound = new SingleSound(soundFile.FullName, this.cacheFileData, this.cacheSoundPlayers, this.cacheSoundPlayersPermanently);
                                if (eagerlyCreateSoundPlayers)
                                {
                                    if (!AudioPlayer.playWithNAudio)
                                    {
                                        singleSound.LoadAndCacheSound();
                                    }
                                    else
                                    {
                                        singleSound.LoadAndCacheFile();
                                    }
                                }
                                singleSound.isSweary = isSweary;
                                singleSound.isSpotter = isSpotter;
                                singleSound.isBleep = isBleep;
                                singleSoundsNoPrefixOrSuffix.Add(singleSound);
                                soundsCount++;
                            }
                        }
                        else
                        {
                            hasSounds = true;
                            SingleSound singleSound = new SingleSound(soundFile.FullName, this.cacheFileData, this.cacheSoundPlayers, this.cacheSoundPlayersPermanently);
                            if (eagerlyCreateSoundPlayers)
                            {
                                if (!AudioPlayer.playWithNAudio)
                                {
                                    singleSound.LoadAndCacheSound();
                                }
                                else
                                {
                                    singleSound.LoadAndCacheFile();
                                }
                            }
                            singleSound.isSweary = isSweary;
                            singleSound.isSpotter = isSpotter;
                            singleSound.isBleep = isBleep;
                            singleSoundsNoPrefixOrSuffix.Add(singleSound);
                            soundsCount++;
                        }
                    }
                    else if (isSweary && !this.useSwearyMessages)
                    {
                        SoundCache.swearySoundsSkipped++;
                    }
                    else if (isMale && !this.useMaleSounds)
                    {
                        SoundCache.maleSoundsSkipped++;
                    }
                }
            }
            catch (DirectoryNotFoundException)
            {
                Console.WriteLine("Unable to find sounds folder for sound set " + this.soundFolder.FullName);
            }
            catch (Exception e)
            {
                Log.Exception(e, "Failed to load sounds for sound set " + this.soundFolder.FullName + " exception: ");
            }
        }

        internal SingleSound getSingleSound(Boolean preferPersonalised)
        {
            if (SoundCache.recordVarietyData)
            {
                SoundCache.addUseToVarietyData(this.soundFolder.FullName, this.soundsCount);
            }
            if (!AudioPlayer.rantWaitingToPlay && preferPersonalised && singleSoundsWithPrefixOrSuffix.Count > 0)
            {
                if (prefixOrSuffixIndexes == null || prefixOrSuffixIndexesPosition == prefixOrSuffixIndexes.Count)
                {
                    prefixOrSuffixIndexes = createIndexes(singleSoundsWithPrefixOrSuffix.Count());
                    prefixOrSuffixIndexesPosition = 0;
                }
                SingleSound ss = null;
                while (prefixOrSuffixIndexesPosition < prefixOrSuffixIndexes.Count())
                {
                    ss = singleSoundsWithPrefixOrSuffix[prefixOrSuffixIndexes[prefixOrSuffixIndexesPosition]];
                    prefixOrSuffixIndexesPosition++;
                    if (!ss.isSweary)
                    {
                        break;
                    }
                    else
                    {
                        // this is a sweary message - can we play it? do we have to play it?
                        if (prefixOrSuffixIndexesPosition == prefixOrSuffixIndexes.Count || GameStateData.CurrentTime > SoundCache.lastSwearyMessageTime + TimeSpan.FromSeconds(10))
                        {
                            SoundCache.lastSwearyMessageTime = GameStateData.CurrentTime;
                            break;
                        }
                    }
                }
                lastVersionWasPersonalised = true;
                return ss;
            }
            else if (singleSoundsNoPrefixOrSuffix.Count > 0)
            {
                if (indexes == null || indexesPosition == indexes.Count)
                {
                    indexes = createIndexes(singleSoundsNoPrefixOrSuffix.Count());
                    indexesPosition = 0;
                }
                SingleSound ss = null;
                while (indexesPosition < indexes.Count())
                {
                    ss = singleSoundsNoPrefixOrSuffix[indexes[indexesPosition]];
                    indexesPosition++;
                    if (!ss.isSweary)
                    {
                        break;
                    }
                    else
                    {
                        // this is a sweary message - can we play it? do we have to play it?
                        if (indexesPosition == indexes.Count || GameStateData.CurrentTime > SoundCache.lastSwearyMessageTime + TimeSpan.FromSeconds(10))
                        {
                            SoundCache.lastSwearyMessageTime = GameStateData.CurrentTime;
                            break;
                        }
                    }
                }
                lastVersionWasPersonalised = false;
                return ss;
            }
            else
            {
                return null;
            }
        }

        private List<int> createIndexes(int count)
        {
            List<int> indexes = new List<int>();
            for (int i = 0; i < count; i++)
            {
                indexes.Add(i);
            }
            shuffle(indexes);
            return indexes;
        }

        internal int UnLoadAll()
        {
            int unloadedCount = 0;
            foreach (SingleSound singleSound in singleSoundsNoPrefixOrSuffix)
            {
                if (singleSound.UnLoad())
                {
                    unloadedCount++;
                }
            }
            foreach (SingleSound singleSound in singleSoundsWithPrefixOrSuffix)
            {
                if (singleSound.UnLoad())
                {
                    unloadedCount++;
                }
            }
            return unloadedCount;
        }

        internal void StopAll()
        {
            foreach (SingleSound singleSound in singleSoundsNoPrefixOrSuffix)
            {
                singleSound.Stop();
            }
            foreach (SingleSound singleSound in singleSoundsWithPrefixOrSuffix)
            {
                singleSound.Stop();
            }
        }
    }

}
