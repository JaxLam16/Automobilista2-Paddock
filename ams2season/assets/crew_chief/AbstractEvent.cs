using CrewChiefV4.Audio;
using CrewChiefV4.Events.PubSub;
using CrewChiefV4.GameState;
using CrewChiefV4.NumberProcessing;

using System;
using System.Collections.Generic;

namespace CrewChiefV4.Events
{
    public abstract partial class AbstractEvent
    {
        private static String folderCelsius = "conditions/celsius";
        private static String folderFahrenheit = "conditions/fahrenheit";
        private static String folderPSI = "tyre_monitor/psi";
        private static String folderBar = "tyre_monitor/bar";   // if people grumble about this, 1bar = 100kPa

        protected enum SIMPLE_INCIDENT_DETECTION_SESSIONS { DISABLED, RACE_ONLY, ALL_SESSIONS };
        protected static SIMPLE_INCIDENT_DETECTION_SESSIONS simpleIncidentDetectionSessions = SIMPLE_INCIDENT_DETECTION_SESSIONS.RACE_ONLY;
        protected AudioPlayer audioPlayer;

        protected PearlsOfWisdom pearlsOfWisdom;

        // some convienence methods for building up compound messages
        public static List<MessageFragment> MessageContents(Object o1, Object o2, Object o3, Object o4, Object o5, Object o6, Object o7, Object o8, Object o9)
        {
            List<MessageFragment> messages = new List<MessageFragment>();
            addObjectToMessages(messages, o1);
            addObjectToMessages(messages, o2);
            addObjectToMessages(messages, o3);
            addObjectToMessages(messages, o4);
            addObjectToMessages(messages, o5);
            addObjectToMessages(messages, o6);
            addObjectToMessages(messages, o7);
            addObjectToMessages(messages, o8); 
            addObjectToMessages(messages, o9);
            return messages;
        }
        public static List<MessageFragment> MessageContents(Object o1, Object o2, Object o3, Object o4, Object o5, Object o6, Object o7, Object o8)
        {
            List<MessageFragment> messages = new List<MessageFragment>();
            addObjectToMessages(messages, o1);
            addObjectToMessages(messages, o2);
            addObjectToMessages(messages, o3);
            addObjectToMessages(messages, o4);
            addObjectToMessages(messages, o5);
            addObjectToMessages(messages, o6);
            addObjectToMessages(messages, o7);
            addObjectToMessages(messages, o8);
            return messages;
        }
        public static List<MessageFragment> MessageContents(Object o1, Object o2, Object o3, Object o4, Object o5,Object o6, Object o7)
        {
            List<MessageFragment> messages = new List<MessageFragment>();
            addObjectToMessages(messages, o1);
            addObjectToMessages(messages, o2);
            addObjectToMessages(messages, o3);
            addObjectToMessages(messages, o4);
            addObjectToMessages(messages, o5);
            addObjectToMessages(messages, o6);
            addObjectToMessages(messages, o7);
            return messages;
        }
        public static List<MessageFragment> MessageContents(Object o1, Object o2, Object o3, Object o4, Object o5, Object o6)
        {
            List<MessageFragment> messages = new List<MessageFragment>();
            addObjectToMessages(messages, o1);
            addObjectToMessages(messages, o2);
            addObjectToMessages(messages, o3);
            addObjectToMessages(messages, o4);
            addObjectToMessages(messages, o5);
            addObjectToMessages(messages, o6);
            return messages;
        }
        public static List<MessageFragment> MessageContents(Object o1, Object o2, Object o3, Object o4, Object o5)
        {
            List<MessageFragment> messages = new List<MessageFragment>();
            addObjectToMessages(messages, o1);
            addObjectToMessages(messages, o2);
            addObjectToMessages(messages, o3);
            addObjectToMessages(messages, o4);
            addObjectToMessages(messages, o5);
            return messages;
        }
        public static List<MessageFragment> MessageContents(Object o1, Object o2, Object o3, Object o4)
        {
            List<MessageFragment> messages = new List<MessageFragment>();
            addObjectToMessages(messages, o1);
            addObjectToMessages(messages, o2);
            addObjectToMessages(messages, o3);
            addObjectToMessages(messages, o4);
            return messages;
        }
        public static List<MessageFragment> MessageContents(Object o1, Object o2, Object o3)
        {
            List<MessageFragment> messages = new List<MessageFragment>();
            addObjectToMessages(messages, o1);
            addObjectToMessages(messages, o2);
            addObjectToMessages(messages, o3);
            return messages;
        }
        public static List<MessageFragment> MessageContents(Object o1, Object o2)
        {
            List<MessageFragment> messages = new List<MessageFragment>();
            addObjectToMessages(messages, o1);
            addObjectToMessages(messages, o2);
            return messages;
        }
        public static List<MessageFragment> MessageContents(Object o1)
        {
            List<MessageFragment> messages = new List<MessageFragment>();
            addObjectToMessages(messages, o1);
            return messages;
        }

        public static String Pause(int length)
        {
            return AudioPlayer.PAUSE_ID + ":" + length;
        }

        private static void addObjectToMessages(List<MessageFragment> messageFragments, Object o) {
            Log.SoundDebug($"Add {o.ToString()}");
            if (o == null)
            {
                messageFragments.Add(null);
            }
            else if (o.GetType() == typeof(MessageFragment))
            {
                messageFragments.Add((MessageFragment)o);
            }
            else if (o.GetType() == typeof(String))
            {
                messageFragments.Add(MessageFragment.Text((String)o));
            }
            else if (o.GetType() == typeof(TimeSpan))
            {
                messageFragments.Add(MessageFragment.Time(new TimeSpanWrapper((TimeSpan)o, GlobalBehaviourSettings.useHundredths ? Precision.HUNDREDTHS : Precision.TENTHS)));
            }
            else if (o.GetType() == typeof(TimeSpanWrapper))
            {
                messageFragments.Add(MessageFragment.Time((TimeSpanWrapper)o));
            }
            else if (o.GetType() == typeof(OpponentData))
            {
                messageFragments.Add(MessageFragment.Opponent((OpponentData)o));
            }
            else if (o.GetType() == typeof(CarNumber))
            {
                messageFragments.AddRange(((CarNumber)o).getMessageFragments());
            }
            else if (o.GetType() == typeof(int) || o.GetType() == typeof(short) || o.GetType() == typeof(long) || o.GetType() == typeof(uint))
            {
                messageFragments.Add(MessageFragment.Integer(Convert.ToInt32(o)));
            }
            else if (o.GetType() == typeof(double) || o.GetType() == typeof(float) || o.GetType() == typeof(decimal))
            {
                messageFragments.AddRange(Utilities.WholeAndFractionalMessage(Convert.ToSingle(o), fractions: 2, rounding: true));
            }
            else
            {
                Console.WriteLine("Unexpected message fragment type of " + o.GetType() + " with content " + o.ToString());
            }
        }

        public virtual List<CrewChief.RacingType> applicableRacingTypes
        {
            get { return new List<CrewChief.RacingType> { CrewChief.RacingType.Circuit }; }
        }

        public virtual List<SessionType> applicableSessionTypes
        {
            get { return new List<SessionType> { SessionType.Practice, SessionType.Qualify, SessionType.PrivateQualify, SessionType.Race, SessionType.HotLap, SessionType.LonePractice }; }
        }

        public virtual List<SessionPhase> applicableSessionPhases
        {
            get { return new List<SessionPhase> { SessionPhase.Green, SessionPhase.Countdown }; }
        }

        // this is called on each 'tick' - the event subtype should
        // place its logic in here including calls to audioPlayer.queueClip
        abstract protected void triggerInternal(GameStateData previousGameState, GameStateData currentGameState);

        // reinitialise any state held by the event subtype
        public abstract void clearState();
        public virtual void Dispose()
        {
            EventBus.Unsubscribe(this);
        }
        // Cleardown the event subtype, default is clearState()
        public virtual void teardownState()
        {
            clearState();
        }

        // generally the event subclass can just return true for this, but when a clip is played with
        // a non-zero delay it may be necessary to re-check that the clip is still valid against the current
        // state
        public virtual Boolean isMessageStillValid(String eventSubType, GameStateData currentGameState, Dictionary<String, Object> validationData)
        {
            return currentGameState != null && isApplicableForCurrentSessionAndPhase(currentGameState.SessionData.SessionType, currentGameState.SessionData.SessionPhase);
        }

        public virtual Boolean isApplicableForCurrentSessionAndPhase(SessionType sessionType, SessionPhase sessionPhase)
        {
            return applicableSessionPhases.Contains(sessionPhase) && applicableSessionTypes.Contains(sessionType) && applicableRacingTypes.Contains(GlobalBehaviourSettings.racingType);
        }

        /// <summary>
        /// Check if the event handles the message.
        /// </summary>
        /// <returns>The command committed ID if it handles the message 
        /// else SpeechCommands.ID.NO_COMMAND</returns>
        public virtual SpeechCommands.ID HandlesEvent(String voiceMessage)
        {
            return SpeechCommands.ID.NO_COMMAND;
        }

        //internal SpeechCommands.ID handlesEvent(String voiceMessage, List<SpeechCommands.ID> Commands)
        //{
        //    return SpeechCommands.SpeechToCommand(Commands, voiceMessage);
        //}

        /// <summary>
        /// Handle the message
        /// </summary>
        public virtual void respond(String voiceMessage)
        {
            // no-op, override in the subclasses
        }
        /// <summary>
        /// Handle the message using the SpeechCommands.ID already calculated
        /// </summary>
        public virtual void respond(String voiceMessage, SpeechCommands.ID cmd)
        {
            // no-op, override in the subclasses
        }

        public virtual int resolveMacroKeyPressCount(String macroName)
        {
            // only used for auto-fuel amount selection at present
            return 0;
        }

        // if we've made this request from an explicit voice command ("clarify") and we end up here, it means
        // the event doesn't have a more-information response, so reply "we have no more information".
        public virtual void respondMoreInformation(String voiceMessage, Boolean requestedExplicitly)
        {
            if (requestedExplicitly)
            {
                audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoMoreData, 0));
            }
            // otherwise do nothing
        }

        protected virtual void respondMoreInformationDelayed(String voiceMessage, Boolean requestedExplicitly, List<MessageFragment> messageFragments)
        {
            if (requestedExplicitly)
            {
                messageFragments.Add(MessageFragment.Text(AudioPlayer.folderNoMoreData));
            }
            // otherwise do nothing
        }

        protected void setPearlsOfWisdom(PearlsOfWisdom pearlsOfWisdom)
        {
            this.pearlsOfWisdom = pearlsOfWisdom;
        }

        public void trigger(GameStateData previousGameState, GameStateData currentGameState)
        {
            // common checks here?
            triggerInternal(previousGameState, currentGameState);
        }
        
        protected Boolean messagesHaveSameContent(List<MessageFragment> messages1, List<MessageFragment> messages2)
        {
            if (messages1 == null && messages2 == null) 
            {
                return true;
            }
            if ((messages1 == null && messages2 != null) || (messages1 != null && messages2 == null) ||
                messages1.Count != messages2.Count)
            {
                return false;
            }
            foreach (MessageFragment m1Fragment in messages1)
            {
                Boolean foundMatch = false;
                foreach (MessageFragment m2Fragment in messages2)
                {
                    if (m1Fragment.type == FragmentType.Text && m2Fragment.type == FragmentType.Text && m1Fragment.text.Equals(m2Fragment.text))
                    {
                        foundMatch = true;
                        break;
                    }
                    else if (m1Fragment.type == FragmentType.Time && m2Fragment.type == FragmentType.Time &&
                        m1Fragment.timeSpan.Equals(m2Fragment.timeSpan))
                    {
                        foundMatch = true;
                        break;
                    }
                    else if (m1Fragment.type == FragmentType.Opponent && m2Fragment.type == FragmentType.Opponent &&
                        ((m1Fragment.opponent == null && m2Fragment.opponent == null) ||
                            (m1Fragment.opponent != null && m2Fragment.opponent != null && m1Fragment.opponent.DriverRawName.Equals(m2Fragment.opponent.DriverRawName))))
                    {
                        foundMatch = true;
                        break;
                    }
                }
                if (!foundMatch)
                {
                    return false;
                }
            }
            return true;
        }

        protected String getTempUnit()
        {
            return GlobalBehaviourSettings.useFahrenheit ? folderFahrenheit : folderCelsius;
        }

        protected String getPressureUnit()
        {
            return Game.ACC || !GlobalBehaviourSettings.useMetric ? folderPSI : folderBar;
        }

        protected int convertTemp(float temp)
        {
            return convertTemp(temp, 1);
        }
        
        protected int convertTemp(float temp, int precision)
        {
            return GlobalBehaviourSettings.useFahrenheit ? celciusToFahrenheit(temp, precision) : (int)(Math.Round(temp / (double)precision) * precision);
        }

        protected static int celciusToFahrenheit(float celcius, int precision)
        {
            float temp = (int)Math.Round((celcius * (9f / 5f)) + 32f);
            return (int)(Math.Round(temp / (double)precision) * precision);
        }

        protected float convertPressure(float pressure, int decimalPlaces)
        {
            return Game.ACC || !GlobalBehaviourSettings.useMetric ? kpaToPsi(pressure, decimalPlaces) : kpaToBar(pressure, decimalPlaces);
        }

        private static float kpaToPsi(float kpa, int decimalPlaces)
        {
            return (float) Math.Round(kpa / 6.894f, decimalPlaces);
        }

        private static float kpaToBar(float kpa, int decimalPlaces)
        {
            return (float)Math.Round(kpa / 100f, 2);
        }
    }
}
