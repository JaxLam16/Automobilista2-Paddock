using System;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Diagnostics;
using CrewChiefV4.GameState;
using CrewChiefV4.Events;
namespace CrewChiefV4.Audio {
public partial class AudioPlayer {
public void enableKeepQuietMode()
        {
            playMessageImmediately(new QueuedMessage(folderAcknowlegeEnableKeepQuiet, 0));
            keepQuiet = true;
        }
public void disableKeepQuietMode()
        {
            playMessageImmediately(new QueuedMessage(folderAcknowlegeDisableKeepQuiet, 0));
            keepQuiet = false;
        }
private bool messageFunctionIsEmptyOrTrue(QueuedMessage queuedMessage)
        {
            // if we have a function, execute it and return the resut, otherwise return true
            if (CrewChief.currentGameState != null && queuedMessage.triggerFunction != null)
            {
                return queuedMessage.triggerFunction.Invoke(CrewChief.currentGameState);
            }
            else
            {
                return true;
            }
        }
private void playQueueContents(OrderedDictionary queueToPlay, Boolean isImmediateMessages)
        {
            long milliseconds = GameStateData.CurrentTime.Ticks / TimeSpan.TicksPerMillisecond;
            List<String> keysToPlay = new List<String>();
            List<String> soundsProcessed = new List<String>();

            Boolean oneOrMoreEventsEnabled = false;

            QueuedMessage higherPriorityDelayedMessage = null;

            lock (queueToPlay)
            {
                int willBePlayedCount = queueToPlay.Count;
                String firstMovableEventWithPrefixOrSuffix = null;
                foreach (String key in queueToPlay.Keys)
                {
                    QueuedMessage queuedMessage = (QueuedMessage)queueToPlay[key];
                    if (isImmediateMessages || queuedMessage.dueTime <= milliseconds)
                    {
                        Boolean blockedByKeepQuietMode;
                        if (allowImportantMessagesInKeepQuietMode)
                        {
                            blockedByKeepQuietMode = keepQuiet && !queuedMessage.playEvenWhenSilenced && !isImmediateMessages;
                        }
                        else
                        {
                            blockedByKeepQuietMode = keepQuiet && !queuedMessage.playEvenWhenSilenced &&
                                (queuedMessage.metadata == null ||
                                (queuedMessage.metadata.type != SoundType.SPOTTER && queuedMessage.metadata.type != SoundType.VOICE_COMMAND_RESPONSE));
                        }

                        Boolean blockedByDelayedHigherPriorityMessage = false;
                        if (higherPriorityDelayedMessage != null)
                        {
                            Debug.Assert(!AudioPlayer.delayMessagesInHardParts);
                            if (higherPriorityDelayedMessage.metadata.priority > queuedMessage.metadata.priority)
                            {
                                blockedByDelayedHigherPriorityMessage = true;
                            }
                        }

                        Boolean messageHasExpired = queuedMessage.expiryTime != 0 && queuedMessage.expiryTime < milliseconds;
                        Boolean messageIsStillValid = queuedMessage.isMessageStillValid(key, CrewChief.currentGameState);
                        Boolean queueTooLongForMessage = queuedMessage.maxPermittedQueueLengthForMessage != 0 && willBePlayedCount > queuedMessage.maxPermittedQueueLengthForMessage;
                        Boolean hasJustPlayedAsAnImmediateMessage = !isImmediateMessages && lastImmediateMessageName != null &&
                            key == lastImmediateMessageName && GameStateData.CurrentTime - lastImmediateMessageTime < TimeSpan.FromSeconds(5);
                        Boolean messageFunctionIsEmptyOrTrue = this.messageFunctionIsEmptyOrTrue(queuedMessage);
                        Boolean isAlreadyQueuedToPlay = keysToPlay.Contains(key);
                        // can we actually play the message?
                        if (!blockedByKeepQuietMode
                            && queuedMessage.canBePlayed
                            && !blockedByDelayedHigherPriorityMessage
                            && messageIsStillValid
                            && !isAlreadyQueuedToPlay
                            && !queueTooLongForMessage
                            && !messageHasExpired
                            && !hasJustPlayedAsAnImmediateMessage
                            && messageFunctionIsEmptyOrTrue)
                        {
                            // special case for 'get ready' event here - we don't want to move this to the top of the queue because
                            // it makes it sound shit. Bit of a hack, needs a better solution
                            if (firstMovableEventWithPrefixOrSuffix == null && key != LapCounter.folderGetReady && soundCache.eventHasPersonalisedPrefixOrSuffix(key))
                            {
                                firstMovableEventWithPrefixOrSuffix = key;
                            }
                            else
                            {
                                keysToPlay.Add(key);
                            }
                        }
                        else
                        {
                            if (blockedByKeepQuietMode)
                            {
                                Log.Sound(() => "Clip " + key + " will not be played because we're in 'keep quiet' mode");
                                soundsProcessed.Add(key);   // add this to the set processed so it's removed from the queue
                            }
                            else if (!messageIsStillValid)
                            {
                                Log.SoundDebug(() => "Clip " + key + " is no longer valid");
                                soundsProcessed.Add(key);   // add this to the set processed so it's removed from the queue
                            }
                            else if (messageHasExpired)
                            {
                                Log.SoundDebug(() => "Clip " + key + " has expired after being queued for " + queuedMessage.getAge() + " milliseconds");
                                soundsProcessed.Add(key);   // add this to the set processed so it's removed from the queue
                            }
                            else if (queueTooLongForMessage)
                            {
                                List<String> keysToDisplay = new List<string>();
                                foreach (String keyToDisplay in queueToPlay.Keys)
                                {
                                    keysToDisplay.Add(keyToDisplay);
                                }
                                Log.Warning("Queue is too long to play clip " + key + " max permitted items for this message = "
                                    + queuedMessage.maxPermittedQueueLengthForMessage + " queue: " + String.Join(", ", keysToDisplay));
                                soundsProcessed.Add(key);   // add this to the set processed so it's removed from the queue
                            }
                            else if (!queuedMessage.canBePlayed)
                            {
                                Log.Warning("Clip " + key + " has some missing sound files");
                                soundsProcessed.Add(key);   // add this to the set processed so it's removed from the queue
                            }
                            else if (hasJustPlayedAsAnImmediateMessage)
                            {
                                Log.SoundDebug(() => "Clip " + key + " has just been played in response to a voice command, skipping");
                                soundsProcessed.Add(key);   // add this to the set processed so it's removed from the queue
                            }
                            else if (blockedByDelayedHigherPriorityMessage)
                            {
                                Log.SoundDebug(() => "Clip " + key + "will not be played because higher priority message is waiting to be played: " + higherPriorityDelayedMessage.messageName);
                                soundsProcessed.Add(key);   // add this to the set processed so it's removed from the queue - TODO: can we leave this in the queue for the next iteration?
                            }
                            else if (isAlreadyQueuedToPlay)
                            {
                                Log.SoundDebug(() => "Clip " + key + " will not be played because it's already about to be played");
                                soundsProcessed.Add(key);   // add this to the set processed so it's removed from the queue
                            }
                            else if (!messageFunctionIsEmptyOrTrue)
                            {
                                // special case for messages which would otherwise be ready to play, but that have
                                // an associated function which hasn't (yet) evaluated to true
                                // Log.Sound("wait...");
                            }
                            willBePlayedCount--;
                        }
                    }
                    else if (queuedMessage.dueTime > milliseconds)
                    {
                        if (!AudioPlayer.delayMessagesInHardParts  // Do not delay messages based on priority if hard parts feature is in use.
                            && (higherPriorityDelayedMessage == null
                                || higherPriorityDelayedMessage.metadata.priority < queuedMessage.metadata.priority))
                        {
                            higherPriorityDelayedMessage = queuedMessage;
                        }
                    }

                    // if we've just processed a 'rant' here, set the flag to false
                    if (queuedMessage.isRant)
                    {
                        AudioPlayer.rantWaitingToPlay = false;
                    }
                }
                if (firstMovableEventWithPrefixOrSuffix != null)
                {
                    keysToPlay.Insert(0, firstMovableEventWithPrefixOrSuffix);
                }
                if (keysToPlay.Count > 0)
                {
                    if (keysToPlay.Count == 1 && clipIsPearlOfWisdom(keysToPlay[0]))
                    {
                        if (hasPearlJustBeenPlayed())
                        {
                            Log.SoundDebug(() => "Rejecting pearl of wisdom " + keysToPlay[0] +
                                " because one has been played in the last " + minTimeBetweenPearlsOfWisdom + " seconds");
                            soundsProcessed.Add(keysToPlay[0]);
                        }
                        else if (disablePearlsOfWisdom)
                        {
                            Log.SoundDebug(() => "Rejecting pearl of wisdom " + keysToPlay[0] +
                                   " because pearls have been disabled for the last phase of the race");
                            soundsProcessed.Add(keysToPlay[0]);
                        }
                    }
                    else
                    {
                        oneOrMoreEventsEnabled = true;
                    }
                }
            }

            Boolean wasInterrupted = false;
            if (oneOrMoreEventsEnabled)
            {
                PlaybackModerator.PreProcessAddedKeys(keysToPlay);

                openRadioChannelInternal();
                soundsProcessed.AddRange(playSounds(keysToPlay, isImmediateMessages, out wasInterrupted));
            }
            else
            {
                soundsProcessed.AddRange(keysToPlay);
            }
            if (soundsProcessed.Count > 0)
            {
                lock (queueToPlay)
                {
                    foreach (String key in soundsProcessed)
                    {
                        if (queueToPlay.Contains(key))
                        {
                            queueToPlay.Remove(key);
                        }
                    }
                }
            }

            // now we go back and play anything else that's been inserted into the queue since we started, but only if
            // we've not been interrupted
            if (queueHasDueMessages(queueToPlay, isImmediateMessages) && (isImmediateMessages || !wasInterrupted) && this.monitorRunning)
            {
                Log.SoundDebug(() => "There are " + queueToPlay.Count + " more events in the queue, playing them...");
                playQueueContents(queueToPlay, isImmediateMessages);
            }
        }
private Boolean queueHasDueMessages(OrderedDictionary queueToCheck, Boolean isImmediateMessages)
        {
            if (isImmediateMessages)
            {
                // immediate messages can't be delayed so no point in checking their due times
                return queueToCheck.Count > 0;
            }
            else if (queueToCheck.Count == 0)
            {
                return false;
            }
            else
            {
                long milliseconds = GameStateData.CurrentTime.Ticks / TimeSpan.TicksPerMillisecond;
                lock (queueToCheck)
                {
                    foreach (String key in queueToCheck.Keys)
                    {
                        QueuedMessage message = (QueuedMessage)queueToCheck[key];
                        if (message.dueTime <= milliseconds && messageFunctionIsEmptyOrTrue(message))
                        {
                            return true;
                        }
                    }
                }
                return false;
            }
        }
public int purgeQueues(int retainMessagesWithSreSessionId = -1)
        {
            return purgeQueue(queuedClips, false) + purgeQueue(immediateClips, true, retainMessagesWithSreSessionId);
        }
private int purgeQueue(OrderedDictionary queue, bool isImmediateQueue, int retainMessagesWithSreSessionId = -1)
        {
            Log.SoundDebug(() => "Purging " + (isImmediateQueue ? "immediate" : "regular") + " queue" );
            int purged = 0;
            lock (queue)
            {
                ArrayList keysToPurge = new ArrayList(queue.Keys);
                foreach (String keyStr in keysToPurge)
                {
                    try
                    {
                        if (retainMessagesWithSreSessionId != -1 && isImmediateQueue)
                        {
                            QueuedMessage message = (QueuedMessage)queue[keyStr];
                            if (message.metadata != null && message.metadata.type == SoundType.VOICE_COMMAND_RESPONSE
                                && retainMessagesWithSreSessionId == message.metadata.speechRecognitionSessionID)
                            {
                                continue;
                            }
                        }

                        if (!keyStr.Contains(SessionEndMessages.sessionEndMessageIdentifier) &&
                            !keyStr.Contains(SmokeTest.SMOKE_TEST) &&
                            !keyStr.Contains(SmokeTest.SMOKE_TEST_SPOTTER) &&
                            !keyStr.Contains(AudioPlayer.RETAIN_ON_SESSION_END))
                        {
                            queue.Remove(keyStr);
                            purged++;
                        }
                    }
                    catch (Exception)
                    {
                        // ignore - not sure why I'm try-catching here :)
                    }
                }
            }
            return purged;
        }
public void playMessage(QueuedMessage queuedMessage)
        {
            if (GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.NONE))
            {
                Log.Sound(() => "All messages disabled for this car class. Message " + queuedMessage.messageName + " will not be played");
            }
            else
            {
                playMessage(queuedMessage, PearlsOfWisdom.PearlType.NONE, 0);
            }
        }
public Boolean playRant(String messageIdentifier, List<MessageFragment> messagesToPlayBeforeRanting)
        {
            if (sweary && !playedRantInThisSession && Utilities.random.NextDouble() < rantLikelihood)
            {
                playedRantInThisSession = true;
                AudioPlayer.rantWaitingToPlay = true;
                List<MessageFragment> messageContents = new List<MessageFragment>();
                if (messagesToPlayBeforeRanting != null)
                {
                    messageContents.AddRange(messagesToPlayBeforeRanting);
                }
                messageContents.Add(MessageFragment.Text(folderRants));
                QueuedMessage rant = new QueuedMessage(messageIdentifier, 0, messageFragments: messageContents);
                rant.isRant = true;
                playMessage(rant, PearlsOfWisdom.PearlType.NONE, 0);
                return true;
            }
            return false;
        }
public Boolean getDelayedRant(List<MessageFragment> messageFragments)
        {
            if (sweary && !playedRantInThisSession && Utilities.random.NextDouble() < rantLikelihood)
            {
                playedRantInThisSession = true;
                AudioPlayer.rantWaitingToPlay = true;
                messageFragments.Add(MessageFragment.Text(folderRants));
                return true;
            }
            return false;
        }
public SoundType getPriortyOfFirstWaitingImmediateMessage()
        {
            QueuedMessage message = getFirstWaitingImmediateMessage(SoundType.OTHER);
            return message == null ? SoundType.OTHER : message.metadata.type;
        }
public QueuedMessage getFirstWaitingImmediateMessage(SoundType minType)
        {
            lock (immediateClips)
            {
                foreach (Object value in immediateClips.Values)
                {
                    QueuedMessage message = (QueuedMessage)value;
                    if (message.metadata.type <= minType)
                    {
                        return message;
                    }
                }
            }
            return null;
        }
public void playMessageImmediately(QueuedMessage queuedMessage, Boolean keepChannelOpen = false)
        {
            if (CrewChief.Debug.RunningUnderDebugger && queuedMessage.messageName != null)
            {
                int count;
                if (Utilities.queuedMessageIds.TryGetValue(queuedMessage.messageName, out count))
                {
                    Utilities.queuedMessageIds[queuedMessage.messageName] = count++;
                }
                else
                {
                    Utilities.queuedMessageIds.Add(queuedMessage.messageName, 1);
                }
                Log.SoundDebug($"playMessageImmediately: Queued message IDs: {string.Join(", ", Utilities.queuedMessageIds.Select(kvp => kvp.Key + "=" + kvp.Value))}");
            }
            if (queuedMessage.canBePlayed)
            {
                if (queuedMessage.metadata.type == SoundType.AUTO)
                {
                    queuedMessage.metadata.type = SoundType.VOICE_COMMAND_RESPONSE;
                    queuedMessage.metadata.speechRecognitionSessionID = SpeechRecogniser.sreSessionId;
                }
                lock (immediateClips)
                {
                    if (immediateClips.Contains(queuedMessage.messageName))
                    {
                        Log.SoundDebug(() => "Clip for event " + queuedMessage.messageName + " is already queued, ignoring");
                        return;
                    }
                    else if (PlaybackModerator.ImmediateMessageCanBeQueued(queuedMessage))
                    {
                        lastImmediateMessageName = queuedMessage.messageName;
                        lastImmediateMessageTime = GameStateData.CurrentTime;
                        this.useShortBeepWhenOpeningChannel = false;
                        this.holdChannelOpen = keepChannelOpen;
                        if (this.holdChannelOpen)
                        {
                            startHangingChannelCloseThread();
                        }

                        // sanity check...
                        if (queuedMessage.metadata.type == SoundType.REGULAR_MESSAGE)
                        {
                            // a regular message will not play from the immediate queue
                            Log.SoundDebug(() => "Message " + queuedMessage.messageName + " is in the immediate queue but is type 'regular' - this will not play. Setting the type to 'important'");
                            queuedMessage.metadata.type = SoundType.IMPORTANT_MESSAGE;
                        }
                        immediateClips.Insert(getInsertionIndex(immediateClips, queuedMessage), queuedMessage.messageName, queuedMessage);

                        // wake up the monitor thread immediately
                        monitorQueueWakeUpEvent.Set();
                    }
                }
            }
        }
private int getInsertionIndex(OrderedDictionary queue, QueuedMessage queuedMessage)
        {
            int index = 0;
            foreach (Object value in queue.Values)
            {
                int existingMessagePriority = ((QueuedMessage)value).metadata.priority;
                if (queuedMessage.metadata.priority > existingMessagePriority)
                {
                    // the existing message is lower priorty than the one we're adding so we've found the index we want
                    break;
                }
                index++;
            }
            return index;
        }
public void playMessage(QueuedMessage queuedMessage, PearlsOfWisdom.PearlType pearlType, double pearlMessageProbability)
        {
            if (CrewChief.Debug.RunningUnderDebugger && queuedMessage.messageName != null)
            {
                int count;
                if (Utilities.queuedMessageIds.TryGetValue(queuedMessage.messageName, out count))
                {
                    Utilities.queuedMessageIds[queuedMessage.messageName] = count++;
                }
                else
                {
                    Utilities.queuedMessageIds.Add(queuedMessage.messageName, 1);
                }
                Log.SoundDebug($"playMessage: Queued message IDs: {string.Join(", ", Utilities.queuedMessageIds.Select(kvp => kvp.Key + "=" + kvp.Value))}");
            }
            if (queuedMessage.canBePlayed)
            {
                if (queuedMessage.metadata.type == SoundType.AUTO)
                {
                    queuedMessage.metadata.type = SoundType.REGULAR_MESSAGE;
                }
                lock (queuedClips)
                {
                    if (queuedClips.Contains(queuedMessage.messageName))
                    {
                        Log.SoundDebug(() => "Clip for event " + queuedMessage.messageName + " is already queued, ignoring");
                        return;
                    }
                    else
                    {
                        DateTime now = CrewChief.currentGameState == null ? DateTime.UtcNow : CrewChief.currentGameState.Now;
                        if (PlaybackModerator.MessageCanBeQueued(queuedMessage, queuedClips.Count, now))
                        {
                            PearlsOfWisdom.PearlMessagePosition pearlPosition = PearlsOfWisdom.PearlMessagePosition.NONE;
                            if (pearlType != PearlsOfWisdom.PearlType.NONE && checkPearlOfWisdomValid(pearlType))
                            {
                                pearlPosition = pearlsOfWisdom.getMessagePosition(pearlMessageProbability);
                            }

                            int insertionIndex = getInsertionIndex(queuedClips, queuedMessage);
                            if (pearlPosition == PearlsOfWisdom.PearlMessagePosition.BEFORE)
                            {
                                QueuedMessage pearlQueuedMessage = new QueuedMessage(queuedMessage.abstractEvent);
                                pearlQueuedMessage.metadata = queuedMessage.metadata;
                                pearlQueuedMessage.dueTime = queuedMessage.dueTime;
                                pearlQueuedMessage.triggerFunction = queuedMessage.triggerFunction;
                                queuedClips.Insert(insertionIndex, PearlsOfWisdom.getMessageFolder(pearlType), pearlQueuedMessage);
                                insertionIndex++;
                            }
                            queuedClips.Insert(insertionIndex, queuedMessage.messageName, queuedMessage);
                            if (pearlPosition == PearlsOfWisdom.PearlMessagePosition.AFTER)
                            {
                                QueuedMessage pearlQueuedMessage = new QueuedMessage(queuedMessage.abstractEvent);
                                pearlQueuedMessage.dueTime = queuedMessage.dueTime;
                                pearlQueuedMessage.metadata = queuedMessage.metadata;
                                pearlQueuedMessage.triggerFunction = queuedMessage.triggerFunction;
                                insertionIndex++;
                                queuedClips.Insert(insertionIndex, PearlsOfWisdom.getMessageFolder(pearlType), pearlQueuedMessage);
                            }

                            // note that we don't wake the monitor Thread here - we wait until all the events have completed on this tick
                            // then check the queue
                        }
                    }
                }
            }
        }
public Boolean removeQueuedMessage(String eventName)
        {
            lock (queuedClips)
            {
                if (queuedClips.Contains(eventName))
                {
                    queuedClips.Remove(eventName);
                    return true;
                }
                return false;
            }
        }
public void removeImmediateMessages(List<String> eventNames)
        {
            lock (immediateClips)
            {
                foreach (String eventName in eventNames)
                {
                    if (immediateClips.Contains(eventName))
                    {
                        Log.SoundDebug(() => "Removing immediate clip " + eventName);
                        immediateClips.Remove(eventName);
                    }
                }
            }
        }
private Boolean checkPearlOfWisdomValid(PearlsOfWisdom.PearlType newPearlType)
        {
            if (GlobalBehaviourSettings.justTheFacts)
            {
                return false;
            }
            if (newPearlType == PearlsOfWisdom.PearlType.BAD)
            {
                if (GlobalBehaviourSettings.complaintsCountInThisSession >= GlobalBehaviourSettings.maxComplaintsPerSession)
                {
                    return false;
                }
            }
            Boolean isValid = true;
            if (queuedClips != null && queuedClips.Count > 0)
            {
                List<String> pearlsToPurge = new List<string>();
                foreach (String eventName in queuedClips.Keys)
                {
                    if (clipIsPearlOfWisdom(eventName))
                    {
                        Log.SoundDebug("There's already a pearl in the queue, can't add another");
                        isValid = false;
                        if (eventName != PearlsOfWisdom.getMessageFolder(newPearlType))
                        {
                            pearlsToPurge.Add(eventName);
                        }
                    }
                }
                foreach (String pearlToPurge in pearlsToPurge)
                {
                    queuedClips.Remove(pearlToPurge);
                    Log.SoundDebug(() => "Queue contains a pearl " + pearlToPurge + " which conflicts with " + newPearlType);
                }
            }
            if (isValid && newPearlType == PearlsOfWisdom.PearlType.BAD)
            {
                GlobalBehaviourSettings.complaintsCountInThisSession++;
            }
            return isValid;
        }
private Boolean clipIsPearlOfWisdom(String eventName)
        {
            foreach (PearlsOfWisdom.PearlType pearlType in Enum.GetValues(typeof(PearlsOfWisdom.PearlType)))
            {
                if (pearlType != PearlsOfWisdom.PearlType.NONE && PearlsOfWisdom.getMessageFolder(pearlType) == eventName)
                {
                    return true;
                }
            }
            return false;
        }
private Boolean hasPearlJustBeenPlayed()
        {
            return timeLastPearlOfWisdomPlayed.Add(minTimeBetweenPearlsOfWisdom) > GameStateData.CurrentTime;
        }
public void suspendPearlsOfWisdom()
        {
            allowPearlsOnNextPlay = false;
        }
public void repeatLastMessage()
        {
            if (lastMessagePlayed != null)
            {
                // clear the validation, expiry and other data
                lastMessagePlayed.prepareToBeRepeated();
                playMessageImmediately(lastMessagePlayed);
            }
        }
internal void pauseQueueAndPlayDelayedImmediateMessage(QueuedMessage queuedMessage, int lowerDelayBoundInclusive, int upperDelayBound)
        {
            this.playMessageImmediately(new QueuedMessage(AudioPlayer.folderStandBy, 0));

            var secondsDelay = Utilities.random.Next(lowerDelayBoundInclusive, upperDelayBound);
            this.pauseQueue(secondsDelay);

            queuedMessage.dueTime = queuedMessage.creationTime + (secondsDelay * 1000) + queuedMessage.updateInterval;
            queuedMessage.secondsDelay = secondsDelay;
            queuedMessage.expiryTime = queuedMessage.creationTime + (secondsDelay + 10) * 1000;

            this.playDelayedImmediateMessage(queuedMessage);
        }
public void wakeMonitorThreadForRegularMessages(DateTime now)
        {
            if (now > nextWakeupCheckTime && queuedClips.Count > 0)
            {
                Boolean doHardPartsCheck = delayMessagesInHardParts &&
                            CrewChief.currentGameState != null &&
                            CrewChief.currentGameState.PositionAndMotionData.CarSpeed > 5 &&
                            (CrewChief.currentGameState.SessionData.SessionPhase == SessionPhase.Green || CrewChief.currentGameState.SessionData.SessionPhase == SessionPhase.Checkered) &&
                            !GameStateData.onManualFormationLap;
                if (!doHardPartsCheck ||
                    !CrewChief.currentGameState.hardPartsOnTrackData.isInHardPart(CrewChief.currentGameState.PositionAndMotionData.DistanceRoundTrack))
                {
                    monitorQueueWakeUpEvent.Set();
                }
                nextWakeupCheckTime = now.AddMilliseconds(200);
            }
        }
} }
