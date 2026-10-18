using CrewChiefV4.Audio;
using CrewChiefV4.GameState;
using System;
using System.Collections.Generic;
using CrewChiefV4.LMU;

namespace CrewChiefV4.Events
{
    class DamageReporting : AbstractEvent
    {
        public override List<SessionPhase> applicableSessionPhases
        {
            get { return new List<SessionPhase> { SessionPhase.Green, SessionPhase.Checkered, SessionPhase.FullCourseYellow, SessionPhase.Formation }; }
        }

        public enum DriverOKResponseType { NONE, CLEARLY_OK, NOT_UNDERSTOOD, NO_SPEECH }

        private readonly Boolean delayResponses = UserSettings.GetUserSettings().getBoolean("enable_delayed_responses");

        private readonly Boolean enableDamageMessages = UserSettings.GetUserSettings().getBoolean("enable_damage_messages");
        private readonly Boolean enableBrakeDamageMessages = UserSettings.GetUserSettings().getBoolean("enable_brake_damage_messages");
        private readonly Boolean enableSuspensionDamageMessages = UserSettings.GetUserSettings().getBoolean("enable_suspension_damage_messages");
        private readonly Boolean enableCrashMessages = UserSettings.GetUserSettings().getBoolean("enable_crash_messages");

        private String folderGeneralDamage = "damage_reporting/damage";

        private String folderMinorTransmissionDamage = "damage_reporting/minor_transmission_damage";
        private String folderMinorEngineDamage = "damage_reporting/minor_engine_damage";
        private String folderMinorAeroDamage = "damage_reporting/minor_aero_damage";
        // same as above but filtered to remove sounds that only work when used in a voice command response
        private String folderMinorAeroDamageGeneral = "damage_reporting/minor_aero_damage_general";
        private String folderMinorSuspensionDamage = "damage_reporting/minor_suspension_damage";
        // same as above but filtered to remove sounds that only work when used in a voice command response
        private String folderMinorSuspensionDamageGeneral = "damage_reporting/minor_suspension_damage_general";
        private String folderMinorBrakeDamage = "damage_reporting/minor_brake_damage";

        private String folderSevereTransmissionDamage = "damage_reporting/severe_transmission_damage";
        private String folderSevereEngineDamage = "damage_reporting/severe_engine_damage";
        private String folderSevereAeroDamage = "damage_reporting/severe_aero_damage";
        private String folderSevereBrakeDamage = "damage_reporting/severe_brake_damage";
        private String folderSevereSuspensionDamage = "damage_reporting/severe_suspension_damage";

        private String folderBustedTransmission = "damage_reporting/busted_transmission";
        private String folderBustedEngine = "damage_reporting/busted_engine";
        private String folderBustedSuspension = "damage_reporting/busted_suspension";
        private String folderBustedBrakes = "damage_reporting/busted_brakes";

        private String folderNoTransmissionDamage = "damage_reporting/no_transmission_damage";
        private String folderNoEngineDamage = "damage_reporting/no_engine_damage";
        private String folderNoAeroDamage = "damage_reporting/no_aero_damage"; 
        private String folderNoSuspensionDamage = "damage_reporting/no_suspension_damage"; 
        private String folderNoBrakeDamage = "damage_reporting/no_brake_damage";
        private String folderJustAScratch = "damage_reporting/trivial_aero_damage";
        // same as above but filtered to remove sounds that only work when used in a voice command response
        private String folderJustAScratchGeneral = "damage_reporting/trivial_aero_damage_general";

        private String folderMissingWheel = "damage_reporting/missing_wheel";

        private String folderLeftFrontPuncture = "damage_reporting/left_front_puncture";
        private String folderRightFrontPuncture = "damage_reporting/right_front_puncture";
        private String folderLeftRearPuncture = "damage_reporting/left_rear_puncture";
        private String folderRightRearPuncture = "damage_reporting/right_rear_puncture";

        // "the car's in good shape" / "we have no significant damage" etc
        private String folderNoDamageOnAnyComponent = "damage_reporting/no_damage";

        private String folderRolled = "damage_reporting/rolling";
        private String folderStoppedUpsideDown = "damage_reporting/stopped_upside_down";

        // just a bit of fun...
        private String folderAreYouOKFirstTry = "damage_reporting/are_you_ok_first_try";
        private String folderAreYouOKSecondTry = "damage_reporting/are_you_ok_second_try";
        private String folderAreYouOKThirdTry = "damage_reporting/are_you_ok_third_try";
        public static String folderAcknowledgeDriverIsOK = "damage_reporting/acknowledge_driver_is_ok";
        // separate messages for when we get a response to the "are you OK?" message but it's not understood or expected
        public static String folderAcknowledgeDriverIsOKAnySpeech = "damage_reporting/acknowledge_driver_is_ok_not_understood";
        public static String folderAcknowledgeDriverIsOKNoSpeech = "damage_reporting/acknowledge_driver_is_ok_no_speech";

        private DamageLevel engineDamage;
        private DamageLevel trannyDamage;
        private DamageLevel aeroDamage;
        private DamageLevel maxSuspensionDamage;
        private DamageLevel maxBrakeDamage;
        
        private Boolean isMissingWheel = false;

        private TimeSpan timeToWaitForDamageToSettle = TimeSpan.FromSeconds(3);

        private DateTime timeWhenDamageLastChanged = DateTime.MinValue;

        private DateTime nextPunctureCheck = DateTime.MinValue;

        private CornerData.Corners lastReportedPunctureCorner = CornerData.Corners.NONE;

        private Tuple<Component, DamageLevel> damageToReportNext = null;

        private Dictionary<Component, DamageLevel> reportedDamagesLevels = new Dictionary<Component, DamageLevel>();

        private DamageLevel minDamageToReport = DamageLevel.TRIVIAL;

        private static float punctureThreshold = 30f; // about 5psi

        private Component componentDestroyed = Component.NONE;

        private LinkedList<PositionAndMotionData.Rotation> orientationSamples = new LinkedList<PositionAndMotionData.Rotation>();
        private int orientationSamplesCount = 30;   // 3 seconds of orientation data
        private TimeSpan orientationCheckEvery = TimeSpan.FromSeconds(2);
        private DateTime nextOrientationCheckDue = DateTime.MinValue;
        private Boolean isRolling = false;

        private DateTime timeOfDangerousAcceleration = DateTime.MinValue;
        public static Boolean waitingForDriverIsOKResponse = false;
        private DateTime timeWhenAskedIfDriverIsOK = DateTime.MaxValue;
        private int driverIsOKRequestCount = 0;
        private Boolean playedAreYouOKInThisSession = false;
        private DateTime triggerCheckDriverIsOKForIRacingAfter = DateTime.MaxValue;

        private Boolean waitingAfterPotentiallyDangerousAcceleration = false;
        private DateTime timeToRecheckAfterPotentiallyDangerousAcceleration = DateTime.MaxValue;
        private float speedAfterPotentiallyDangerousAcceleration = float.MaxValue;

        // Validation stuff:
        private const string validateMessageTypeKey = "validateMessageTypeKey";
        private const string validateMessageTypeDamage = "validateMessageTypeDamage";
        private const string validateMessageTypeFlatTire = "validateMessageTypeFlatTire";
        private const string validationComponentKey = "validationComponentKey";
        private const string validationDamageLevelKey = "validationDamageLevelKey";
        private const string validationFlatTireKey = "validationDamageLevelKey";

        /*
         * IMPORTANT: This method is called twice - when the message becomes due, and immediately before playing it (which may have a 
         * delay caused by the length of the queue at the time). So be *very* careful when checking and updating local state in here.
         */
        public override bool isMessageStillValid(string eventSubType, GameStateData currentGameState, Dictionary<String, Object> validationData)
        {
            if (base.isMessageStillValid(eventSubType, currentGameState, validationData))
            {
                if (currentGameState.PitData.InPitlane || currentGameState.PitData.IsInGarage)
                    return false;

                if (validationData == null)
                    return true;

                var vmt = validationData[DamageReporting.validateMessageTypeKey] as string;
                switch (vmt)
                {
                    case DamageReporting.validateMessageTypeFlatTire:
                    {
                        var puncture = (CornerData.Corners)validationData[DamageReporting.validationFlatTireKey];
                        if (this.componentDestroyed != Component.NONE)  // If there is any component already destroyed
                        {
                            // Do not play any message, because it does not matter if tire is flat after suspension is damaged.
                            Console.WriteLine(string.Format("Message no longer valid: flat tire {0} because component {1} is already destroyed", puncture, this.componentDestroyed));
                            return false;
                        }

                        break;
                    }
                    case DamageReporting.validateMessageTypeDamage:
                    {
                        var component = (Component)validationData[DamageReporting.validationComponentKey];
                        var dmgLevel = (DamageLevel)validationData[DamageReporting.validationDamageLevelKey];
                        if (this.componentDestroyed != Component.NONE   // If there is any component already destroyed
                            && component != this.componentDestroyed)  // And it is not the current component
                        {
                            // Do not play any message, because it does not matter if Aero is minor after suspension is damaged.
                            Console.WriteLine(string.Format("Message no longer valid: level {0} component {1} because {2} is already destroyed", dmgLevel, component, this.componentDestroyed));
                            return false;
                        }

                        // Make sure that damage level is still valid.
                        var lastReporteDmgLevel = this.getLastReportedDamageLevel(component);
                        if (lastReporteDmgLevel > dmgLevel)  // triggerInternal() should prevent double messages for the same damage level.
                        {
                            Console.WriteLine(string.Format("Message no longer valid: level {0} component {1} because last reported damage level is {2}", dmgLevel, component, lastReporteDmgLevel));
                            return false;
                        }
                        if (engineDamage == DamageLevel.NONE && trannyDamage == DamageLevel.NONE && aeroDamage == DamageLevel.NONE && maxSuspensionDamage == DamageLevel.NONE && maxBrakeDamage == DamageLevel.NONE
                            && component != Component.NONE && dmgLevel != DamageLevel.NONE)
                        {
                            // the state has probably been reset
                            Console.WriteLine(string.Format("Message no longer valid: level {0} component {1} because damage state has been reset", dmgLevel, component));
                            return false;
                        }

                        break;
                    }
                }

                return true;
            }
            return false;
        }

        public void cancelWaitingForDriverIsOK(DriverOKResponseType responseType)
        {
            DamageReporting.waitingForDriverIsOKResponse = false;
            timeWhenAskedIfDriverIsOK = DateTime.MaxValue;
            driverIsOKRequestCount = 0;
            switch (responseType)
            {
                case DriverOKResponseType.CLEARLY_OK:
                    audioPlayer.playMessageImmediately(new QueuedMessage(folderAcknowledgeDriverIsOK, 0, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                    break;
                case DriverOKResponseType.NOT_UNDERSTOOD:
                    audioPlayer.playMessageImmediately(new QueuedMessage(folderAcknowledgeDriverIsOKAnySpeech, 0, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                    break;
                case DriverOKResponseType.NO_SPEECH:
                    audioPlayer.playMessageImmediately(new QueuedMessage(folderAcknowledgeDriverIsOKNoSpeech, 0, type: SoundType.IMPORTANT_MESSAGE, priority: 0));
                    break;
            }
        }
        
        private enum Component
        {
            ENGINE, TRANNY, AERO, SUSPENSION, BRAKES, NONE
        }
        
        public DamageReporting(AudioPlayer audioPlayer)
        {
            this.audioPlayer = audioPlayer;
        }

        public override void clearState()
        {
            engineDamage = DamageLevel.NONE;
            trannyDamage = DamageLevel.NONE;
            aeroDamage = DamageLevel.NONE;
            maxSuspensionDamage = DamageLevel.NONE;
            maxBrakeDamage = DamageLevel.NONE;
            timeWhenDamageLastChanged = DateTime.MinValue;
            isMissingWheel = false;
            damageToReportNext = null;
            reportedDamagesLevels.Clear();
            minDamageToReport = DamageLevel.TRIVIAL;
            nextPunctureCheck = MapperClock.UtcNow + timeToWaitForDamageToSettle;
            componentDestroyed = Component.NONE;
            orientationSamples.Clear();
            nextOrientationCheckDue = DateTime.MinValue;
            isRolling = false;
            timeOfDangerousAcceleration = DateTime.MinValue;

            timeToRecheckAfterPotentiallyDangerousAcceleration = DateTime.MaxValue;
            cancelWaitingForDriverIsOK(DriverOKResponseType.NONE);
            playedAreYouOKInThisSession = false;
            triggerCheckDriverIsOKForIRacingAfter = DateTime.MaxValue;
            waitingAfterPotentiallyDangerousAcceleration = false;
            speedAfterPotentiallyDangerousAcceleration = float.MaxValue;
        }

        private Boolean hasBeenReported(Component component, DamageLevel damageLevel)
        {
            foreach (KeyValuePair<Component, DamageLevel> componentAndDamageAlreadyReported in reportedDamagesLevels)
            {
                if (component == componentAndDamageAlreadyReported.Key && componentAndDamageAlreadyReported.Value == damageLevel)
                {
                    return true;
                }
            }
            return false;
        }

        // used when damage level decreases
        private void resetReportedDamage(Component component, DamageLevel newDamageLevel)
        {
            if (reportedDamagesLevels.ContainsKey(component))
            {
                reportedDamagesLevels[component] = newDamageLevel;
            }
        }

        private DamageLevel getLastReportedDamageLevel(Component component)
        {
            DamageLevel level = DamageLevel.NONE;
            if (reportedDamagesLevels.TryGetValue(component, out level))
            {
                return level;
            }

            return DamageLevel.NONE;
        }

        public static CornerData.Corners getPuncture(TyreData tyreData)
        {
            // quick sanity check on the data - if all the tyres are the same pressure we have no puncture
            if (tyreData.FrontLeftPressure == tyreData.FrontRightPressure &&
                    tyreData.FrontLeftPressure == tyreData.RearLeftPressure &&
                    tyreData.FrontLeftPressure == tyreData.RearRightPressure)
            {
                return CornerData.Corners.NONE;
            }
            else if (tyreData.FrontLeftPressure < punctureThreshold)
            {
                return CornerData.Corners.FRONT_LEFT;
            }
            else if (tyreData.FrontRightPressure < punctureThreshold)
            {
                return CornerData.Corners.FRONT_RIGHT;
            }
            else if (tyreData.RearLeftPressure < punctureThreshold)
            {
                return CornerData.Corners.REAR_LEFT;
            }
            else if (tyreData.RearRightPressure < punctureThreshold)
            {
                return CornerData.Corners.REAR_RIGHT;
            }
            return CornerData.Corners.NONE;
        }

        override protected void triggerInternal(GameStateData previousGameState, GameStateData currentGameState)
        {
            // if we've crashed hard and are waiting for the player to say they're OK, don't process anything else in this event:
            if (waitingForDriverIsOKResponse)
            {
                if (!currentGameState.PitData.InPitlane && !currentGameState.PitData.IsInGarage)
                {
                    if (timeWhenAskedIfDriverIsOK.Add(TimeSpan.FromSeconds(8)) < currentGameState.Now)
                    {
                        timeWhenAskedIfDriverIsOK = currentGameState.Now;
                        switch (driverIsOKRequestCount)
                        {
                            case 1:
                                audioPlayer.playMessageImmediately(new QueuedMessage(folderAreYouOKSecondTry, 0, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                                driverIsOKRequestCount = 2;
                                break;
                            case 2:
                                // no response after 3 requests, he's dead, jim.
                                audioPlayer.playMessageImmediately(new QueuedMessage(folderAreYouOKThirdTry, 0, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                                cancelWaitingForDriverIsOK(DriverOKResponseType.NONE);
                                break;
                        }
                    }
                }
                else
                {
                    // we're in the pitlane so cancel all the dangerous acceleration stuff
                    waitingForDriverIsOKResponse = false;
                    waitingAfterPotentiallyDangerousAcceleration = false;
                }
                return;
            }

            if (waitingAfterPotentiallyDangerousAcceleration)
            {
                if (currentGameState.PositionAndMotionData.CarSpeed > speedAfterPotentiallyDangerousAcceleration + 5)
                {
                    Console.WriteLine("Car has accelerated, cancelling wait for crash message");
                    waitingAfterPotentiallyDangerousAcceleration = false;
                    timeToRecheckAfterPotentiallyDangerousAcceleration = DateTime.MaxValue;
                }
                else if (timeToRecheckAfterPotentiallyDangerousAcceleration > currentGameState.Now)
                {
                    waitingAfterPotentiallyDangerousAcceleration = false;
                    timeToRecheckAfterPotentiallyDangerousAcceleration = DateTime.MaxValue;
                    timeOfDangerousAcceleration = currentGameState.Now;
                    // special case for iRacing: no damage data so we can't hang this off 'destroyed' components
                    triggerCheckDriverIsOKForIRacingAfter = currentGameState.Now.Add(TimeSpan.FromSeconds(2));
                }
                else
                {
                    // suspend the rest of this event
                    return;
                }
            }
            
            // need to be careful with interval here.
            // Disable these for iRacing, which has some spikes in car speed data that trigger false positives
            if (!Game.IRACING &&
                enableCrashMessages && !playedAreYouOKInThisSession && !currentGameState.PitData.InPitlane && 
                !currentGameState.PitData.IsInGarage && currentGameState.PositionAndMotionData.CarSpeed > 0.001)
            {
                if (previousGameState != null)
                {
                    double interval = (currentGameState.Now - previousGameState.Now).TotalSeconds;
                    if (interval > 0.01)
                    {
                        double calculatedAcceleration = Math.Abs(currentGameState.PositionAndMotionData.CarSpeed - previousGameState.PositionAndMotionData.CarSpeed) / interval;

                        /*Console.WriteLine("Interval = " + interval + 
                            " Current speed = " + currentGameState.PositionAndMotionData.CarSpeed +
                                " previous speed = " + previousGameState.PositionAndMotionData.CarSpeed + " acceleration = " + calculatedAcceleration / 9.8f + "g");*/

                        // if we're subject to > 40G (400m/s2), this is considered dangerous. If we've stopped (or nearly stopped) immediately
                        // after the impact, assume it's a bad 'un. If we're still moving after the impact, track the speed for 3 seconds and 
                        // if it doesn't increase in that time, we can assume it's a bad 'un
                        if (calculatedAcceleration > 400 || (Game.ACC && calculatedAcceleration > 270))
                        {
                            Console.WriteLine("Massive impact. Current speed = " + currentGameState.PositionAndMotionData.CarSpeed.ToString("0.000") +
                                " previous speed = " + previousGameState.PositionAndMotionData.CarSpeed.ToString("0.000") + " acceleration = " + (calculatedAcceleration / 9.8f).ToString("0.0000") + "g");
                            if (currentGameState.PositionAndMotionData.CarSpeed < 3)
                            {
                                timeOfDangerousAcceleration = currentGameState.Now;
                            }
                            else
                            {
                                // massive acceleration but we're still moving
                                timeToRecheckAfterPotentiallyDangerousAcceleration = currentGameState.Now.Add(TimeSpan.FromSeconds(3));
                                waitingAfterPotentiallyDangerousAcceleration = true;
                                speedAfterPotentiallyDangerousAcceleration = currentGameState.PositionAndMotionData.CarSpeed;
                            }
                        }
                    }
                }
            }
            else if(Game.IRACING &&
                // disabling this guard until we have more data to confirm it actually works
                // currentGameState.CarDamageData.OverallGeneralDamage >= DamageLevel.MAJOR &&
                enableCrashMessages && !playedAreYouOKInThisSession && !currentGameState.PitData.InPitlane &&
                !currentGameState.PitData.IsInGarage && currentGameState.PositionAndMotionData.AccelerationVector.LongAccel < -400.00)
            {

                Console.WriteLine("Massive impact. Current CarSpeed = " + currentGameState.PositionAndMotionData.CarSpeed.ToString("0.000") +
                    " acceleration = " + (currentGameState.PositionAndMotionData.AccelerationVector.LongAccel / 9.8f).ToString() + "g");
                if (currentGameState.PositionAndMotionData.CarSpeed < 3)
                {
                    timeOfDangerousAcceleration = currentGameState.Now;
                    // special case for iRacing: no damage data so we can't hang this off 'destroyed' components
                    triggerCheckDriverIsOKForIRacingAfter = currentGameState.Now.Add(TimeSpan.FromSeconds(4));
                }
                else
                {
                    // massive acceleration but we're still moving
                    timeToRecheckAfterPotentiallyDangerousAcceleration = currentGameState.Now.Add(TimeSpan.FromSeconds(3));
                    waitingAfterPotentiallyDangerousAcceleration = true;
                    speedAfterPotentiallyDangerousAcceleration = currentGameState.PositionAndMotionData.CarSpeed;
                }
            }

            Boolean orientationSamplesFull = orientationSamples.Count > orientationSamplesCount;
            if (orientationSamplesFull)
            {
                orientationSamples.RemoveFirst();
            }
            orientationSamples.AddLast(currentGameState.PositionAndMotionData.Orientation);

            // don't check for rolling if we've just had a dangerous acceleration as we don't want both messages to trigger
            if (!GlobalBehaviourSettings.justTheFacts
                && enableCrashMessages && currentGameState.Now > nextOrientationCheckDue && orientationSamplesFull &&
                currentGameState.Now.Subtract(timeOfDangerousAcceleration) > TimeSpan.FromSeconds(10))
            {
                nextOrientationCheckDue = currentGameState.Now.Add(orientationCheckEvery);
                checkOrientation(currentGameState.PositionAndMotionData.CarSpeed);
            }
            
            if (!Game.IRACING && currentGameState.CarDamageData.DamageEnabled && currentGameState.SessionData.SessionRunningTime > 10 && currentGameState.Now > nextPunctureCheck && SessionSettings.NotLMUorLMUcarDamageEnabled)
            {
                nextPunctureCheck = currentGameState.Now + timeToWaitForDamageToSettle;
                CornerData.Corners puncture = getPuncture(currentGameState.TyreData);
                if (puncture != lastReportedPunctureCorner)
                {
                    var validationData = new Dictionary<string, object>();
                    validationData.Add(DamageReporting.validateMessageTypeKey, DamageReporting.validateMessageTypeFlatTire);
                    validationData.Add(DamageReporting.validationFlatTireKey, puncture);

                    lastReportedPunctureCorner = puncture;
                    var msgDelay = Utilities.random.Next(4, 7);
                    var msgExpiration = msgDelay + 10;
                    switch (puncture)
                    {
                        case CornerData.Corners.FRONT_LEFT:
                            audioPlayer.playMessage(new QueuedMessage(folderLeftFrontPuncture, msgExpiration, secondsDelay: msgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                        case CornerData.Corners.FRONT_RIGHT:
                            audioPlayer.playMessage(new QueuedMessage(folderRightFrontPuncture, msgExpiration, secondsDelay: msgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                        case CornerData.Corners.REAR_LEFT:
                            audioPlayer.playMessage(new QueuedMessage(folderLeftRearPuncture, msgExpiration, secondsDelay: msgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                        case CornerData.Corners.REAR_RIGHT:
                            audioPlayer.playMessage(new QueuedMessage(folderRightRearPuncture, msgExpiration, secondsDelay: msgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                    }
                }
            }
            if (currentGameState.CarDamageData.DamageEnabled && SessionSettings.NotLMUorLMUcarDamageEnabled)
            {
                aeroDamage = currentGameState.CarDamageData.OverallAeroDamage;
                trannyDamage = currentGameState.CarDamageData.OverallTransmissionDamage;
                engineDamage = currentGameState.CarDamageData.OverallEngineDamage;
                if (currentGameState.CarDamageData.BrakeDamageStatus.hasValueAtLevel(DamageLevel.DESTROYED))
                {
                    maxBrakeDamage = DamageLevel.DESTROYED;
                }
                else if (currentGameState.CarDamageData.BrakeDamageStatus.hasValueAtLevel(DamageLevel.MAJOR))
                {
                    maxBrakeDamage = DamageLevel.MAJOR;
                }
                else if (currentGameState.CarDamageData.BrakeDamageStatus.hasValueAtLevel(DamageLevel.MINOR))
                {
                    maxBrakeDamage = DamageLevel.MINOR;
                }
                else if (currentGameState.CarDamageData.BrakeDamageStatus.hasValueAtLevel(DamageLevel.TRIVIAL))
                {
                    maxBrakeDamage = DamageLevel.TRIVIAL;
                }
                else
                {
                    maxBrakeDamage = DamageLevel.NONE;
                }
            
                if (currentGameState.CarDamageData.SuspensionDamageStatus.hasValueAtLevel(DamageLevel.DESTROYED))
                {
                    maxSuspensionDamage = DamageLevel.DESTROYED;
                }
                else if (currentGameState.CarDamageData.SuspensionDamageStatus.hasValueAtLevel(DamageLevel.MAJOR))
                {
                    maxSuspensionDamage = DamageLevel.MAJOR;
                }
                else if (currentGameState.CarDamageData.SuspensionDamageStatus.hasValueAtLevel(DamageLevel.MINOR))
                {
                    maxSuspensionDamage = DamageLevel.MINOR;
                }
                else if (currentGameState.CarDamageData.SuspensionDamageStatus.hasValueAtLevel(DamageLevel.TRIVIAL))
                {
                    maxSuspensionDamage = DamageLevel.TRIVIAL;
                }
                else
                {
                    maxSuspensionDamage = DamageLevel.NONE;
                }
                isMissingWheel = !currentGameState.PitData.InPitlane && (!currentGameState.TyreData.LeftFrontAttached || !currentGameState.TyreData.RightFrontAttached ||
                        !currentGameState.TyreData.LeftRearAttached || !currentGameState.TyreData.RightRearAttached);
            
                if (engineDamage < getLastReportedDamageLevel(Component.ENGINE))
                {
                    resetReportedDamage(Component.ENGINE, engineDamage);
                } 
                if (trannyDamage < getLastReportedDamageLevel(Component.TRANNY))
                {
                    resetReportedDamage(Component.TRANNY, trannyDamage);
                } 
                if (maxSuspensionDamage < getLastReportedDamageLevel(Component.SUSPENSION))
                {
                    resetReportedDamage(Component.SUSPENSION, maxSuspensionDamage);
                } 
                if (maxBrakeDamage < getLastReportedDamageLevel(Component.BRAKES))
                {
                    resetReportedDamage(Component.BRAKES, maxBrakeDamage);
                } 
                if (aeroDamage < getLastReportedDamageLevel(Component.AERO))
                {
                    resetReportedDamage(Component.AERO, aeroDamage);
                }

                minDamageToReport = (DamageLevel)Math.Max((int)engineDamage, Math.Max((int)trannyDamage, Math.Max((int)maxSuspensionDamage, Math.Max((int)maxBrakeDamage, (int) aeroDamage))));

                Tuple<Component, DamageLevel> worstUnreportedDamage = getWorstUnreportedDamage();
                if (worstUnreportedDamage != null && worstUnreportedDamage.Item2 >= minDamageToReport)
                {
                    if (damageToReportNext == null || worstUnreportedDamage.Item1 != damageToReportNext.Item1 || worstUnreportedDamage.Item2 != damageToReportNext.Item2)
                    {
                        timeWhenDamageLastChanged = currentGameState.Now;
                        damageToReportNext = worstUnreportedDamage;
                    }
                    else if (timeWhenDamageLastChanged.Add(timeToWaitForDamageToSettle) < currentGameState.Now)
                    {
                        Console.WriteLine("Reporting ...");
                        Console.WriteLine(damageToReportNext.Item1 + ", " + damageToReportNext.Item2);

                        // put *all* the damage levels in the 'reported' set, even though we haven't actually reported them.
                        // This ensure we only ever play the worst damage on the car when damage has just increased
                        // Only do this if the component damage is *less* than the one we just reported
                        if (Component.AERO == damageToReportNext.Item1 || aeroDamage < damageToReportNext.Item2)
                        {
                            addReportedDamage(Component.AERO, aeroDamage);
                        }
                        if (Component.BRAKES == damageToReportNext.Item1 || maxBrakeDamage < damageToReportNext.Item2)
                        {
                            addReportedDamage(Component.BRAKES, maxBrakeDamage);
                        }
                        if (Component.ENGINE == damageToReportNext.Item1 || engineDamage < damageToReportNext.Item2)
                        {
                            addReportedDamage(Component.ENGINE, engineDamage);
                        }
                        if (Component.SUSPENSION == damageToReportNext.Item1 || maxSuspensionDamage < damageToReportNext.Item2)
                        {
                            addReportedDamage(Component.SUSPENSION, maxSuspensionDamage);
                        }
                        if (Component.TRANNY == damageToReportNext.Item1 || trannyDamage < damageToReportNext.Item2)
                        {
                            addReportedDamage(Component.TRANNY, trannyDamage);
                        }
                        if (enableDamageMessages)
                        {
                            playDamageToReport(currentGameState.SessionData.SessionType == SessionType.Race && currentGameState.SessionData.NumCarsOverall > 2,
                                currentGameState.Now, currentGameState.PitData.InPitlane || currentGameState.PitData.IsInGarage);
                        }
                    }
                }
            }

            // hack until iRacing expose a more detailed damage model
            if (Game.IRACING && enableDamageMessages &&
                currentGameState.CarDamageData.OverallGeneralDamage == DamageLevel.MINOR &&
                previousGameState != null & currentGameState.CarDamageData.OverallGeneralDamage > previousGameState.CarDamageData.OverallGeneralDamage)
            {
                var minorDamageMsgDelay = Utilities.random.Next(3, 7);
                audioPlayer.playMessage(new QueuedMessage("damage", 0, MessageContents(folderGeneralDamage), secondsDelay: minorDamageMsgDelay, priority: 15));
            }
            if (Game.IRACING && currentGameState.Now > triggerCheckDriverIsOKForIRacingAfter)
            {
                triggerCheckDriverIsOKForIRacingAfter = DateTime.MaxValue;
                checkIfDriverIsOK(currentGameState.Now, currentGameState.PitData.InPitlane || currentGameState.PitData.IsInGarage);
            }
        }

        private void addReportedDamage(Component component, DamageLevel damageLevel)
        {
            reportedDamagesLevels[component] = damageLevel;
        }

        private QueuedMessage getDamageMessage(Component component, Boolean includeNoDamage)
        {
            QueuedMessage damageMessage = null;
            switch (component)
            {
                case Component.AERO:
                    switch (aeroDamage)
                    {
                        case DamageLevel.NONE:
                        {
                            if (includeNoDamage)
                            {
                                damageMessage = new QueuedMessage(folderNoAeroDamage, 0);
                            }

                            break;
                        }
                        case DamageLevel.MAJOR:
                        case DamageLevel.DESTROYED:
                            damageMessage = new QueuedMessage(folderSevereAeroDamage, 0);
                            break;
                        case DamageLevel.MINOR:
                            damageMessage = new QueuedMessage(includeNoDamage ? folderMinorAeroDamage : folderMinorAeroDamageGeneral, 0);
                            break;
                        case DamageLevel.TRIVIAL:
                            damageMessage = new QueuedMessage(includeNoDamage ? folderJustAScratch : folderJustAScratchGeneral, 0);
                            break;
                    }
                    break;
                case Component.BRAKES:
                    switch (maxBrakeDamage)
                    {
                        case DamageLevel.NONE:
                        case DamageLevel.TRIVIAL:
                        {
                            if (includeNoDamage)
                            {
                                damageMessage = new QueuedMessage(folderNoBrakeDamage, 0);
                            }

                            break;
                        }
                        case DamageLevel.DESTROYED:
                            damageMessage = new QueuedMessage(folderBustedBrakes, 0);
                            break;
                        case DamageLevel.MAJOR:
                            damageMessage = new QueuedMessage(folderSevereBrakeDamage, 0);
                            break;
                        case DamageLevel.MINOR:
                            damageMessage = new QueuedMessage(folderMinorBrakeDamage, 0);
                            break;
                    }
                    break;
                case Component.ENGINE:
                    switch (engineDamage)
                    {
                        case DamageLevel.NONE:
                        case DamageLevel.TRIVIAL:
                        {
                            if (includeNoDamage)
                            {
                                damageMessage = new QueuedMessage(folderNoEngineDamage, 0);
                            }

                            break;
                        }
                        case DamageLevel.DESTROYED:
                            damageMessage = new QueuedMessage(folderBustedEngine, 0);
                            break;
                        case DamageLevel.MAJOR:
                            damageMessage = new QueuedMessage(folderSevereEngineDamage, 0);
                            break;
                        case DamageLevel.MINOR:
                            damageMessage = new QueuedMessage(folderMinorEngineDamage, 0);
                            break;
                    }
                    break;
                case Component.SUSPENSION:
                    if (isMissingWheel)
                    {
                        damageMessage = new QueuedMessage(folderMissingWheel, 0);                        
                    }
                    if ((maxSuspensionDamage == DamageLevel.NONE || maxSuspensionDamage == DamageLevel.TRIVIAL) && !isMissingWheel)
                    {
                        if (includeNoDamage)
                        {
                            damageMessage = new QueuedMessage(folderNoSuspensionDamage, 0);
                        }
                    }
                    else switch (maxSuspensionDamage)
                    {
                        case DamageLevel.DESTROYED:
                            damageMessage = new QueuedMessage(folderBustedSuspension, 0);
                            break;
                        case DamageLevel.MAJOR:
                            damageMessage = new QueuedMessage(folderSevereSuspensionDamage, 0);
                            break;
                        default:
                        {
                            if (maxSuspensionDamage == DamageLevel.MINOR && !isMissingWheel)
                            {
                                damageMessage = new QueuedMessage(includeNoDamage ? folderMinorSuspensionDamage : folderMinorSuspensionDamageGeneral, 0);                        
                            }

                            break;
                        }
                    }
                    break;
                case Component.TRANNY:
                    switch (trannyDamage)
                    {
                        case DamageLevel.NONE:
                        case DamageLevel.TRIVIAL:
                        {
                            if (includeNoDamage)
                            {
                                damageMessage = new QueuedMessage(folderNoTransmissionDamage, 0);
                            }

                            break;
                        }
                        case DamageLevel.DESTROYED:
                            damageMessage = new QueuedMessage(folderBustedTransmission, 0);
                            break;
                        case DamageLevel.MAJOR:
                            damageMessage = new QueuedMessage(folderSevereTransmissionDamage, 0);
                            break;
                        case DamageLevel.MINOR:
                            damageMessage = new QueuedMessage(folderMinorTransmissionDamage, 0);
                            break;
                    }
                    break;
                default:
                    break;
            }
            return damageMessage;
        }

        private void readStatus()
        {
            if (!Game.IRACING)
            {
                List<QueuedMessage> damageMessages = new List<QueuedMessage>();
                switch (lastReportedPunctureCorner)
                {
                    case CornerData.Corners.FRONT_LEFT:
                        damageMessages.Add(new QueuedMessage(folderLeftFrontPuncture, 0));
                        break;
                    case CornerData.Corners.FRONT_RIGHT:
                        damageMessages.Add(new QueuedMessage(folderRightFrontPuncture, 0));
                        break;
                    case CornerData.Corners.REAR_LEFT:
                        damageMessages.Add(new QueuedMessage(folderLeftRearPuncture, 0));
                        break;
                    case CornerData.Corners.REAR_RIGHT:
                        damageMessages.Add(new QueuedMessage(folderRightRearPuncture, 0));
                        break;
                }
                QueuedMessage aero = getDamageMessage(Component.AERO, false);
                if (aero != null)
                {
                    damageMessages.Add(aero);
                }
                QueuedMessage tranny = getDamageMessage(Component.TRANNY, false);
                if (tranny != null)
                {
                    damageMessages.Add(tranny);
                }
                QueuedMessage engine = getDamageMessage(Component.ENGINE, false);
                if (engine != null)
                {
                    damageMessages.Add(engine);
                }
                QueuedMessage sus = getDamageMessage(Component.SUSPENSION, false);
                if (sus != null)
                {
                    damageMessages.Add(sus);
                }
                QueuedMessage brakes = getDamageMessage(Component.BRAKES, false);
                if (brakes != null)
                {
                    damageMessages.Add(brakes);
                }
                if (damageMessages.Count == 0)
                {
                    // no damage
                    damageMessages.Add(new QueuedMessage(folderNoDamageOnAnyComponent, 0));
                }
                foreach (QueuedMessage message in damageMessages)
                {
                    audioPlayer.playMessageImmediately(message);
                }
            }
        }

        private static readonly List<SpeechCommands.ID> Commands = new List<SpeechCommands.ID>
        {
            SpeechCommands.ID.CAR_STATUS,
            SpeechCommands.ID.DAMAGE_REPORT,
            SpeechCommands.ID.HOWS_MY_AERO,
            SpeechCommands.ID.HOWS_MY_BRAKES,
            SpeechCommands.ID.HOWS_MY_ENGINE,
            SpeechCommands.ID.HOWS_MY_SUSPENSION,
            SpeechCommands.ID.HOWS_MY_TRANSMISSION,
            SpeechCommands.ID.STATUS,
        };
        public override SpeechCommands.ID HandlesEvent(String voiceMessage)
        {
            return SpeechCommands.SpeechToCommand(Commands, voiceMessage);
        }

        public override void respond(String voiceMessage)
        {
            respond(voiceMessage, HandlesEvent(voiceMessage));
        }
        public override void respond(String voiceMessage, SpeechCommands.ID cmd)
        {
            switch (cmd)
            {
                case SpeechCommands.ID.CAR_STATUS:
                case SpeechCommands.ID.DAMAGE_REPORT:
                case SpeechCommands.ID.STATUS:
                    readStatus();
                    break;
                default:
                {
                    QueuedMessage damageMessage = null;
                    switch (cmd)
                    {
                        case SpeechCommands.ID.HOWS_MY_AERO:
                            damageMessage = getDamageMessage(Component.AERO, true);
                            break;
                        case SpeechCommands.ID.HOWS_MY_TRANSMISSION:
                            damageMessage = getDamageMessage(Component.TRANNY, true);
                            break;
                        case SpeechCommands.ID.HOWS_MY_ENGINE:
                            damageMessage = getDamageMessage(Component.ENGINE, true);
                            break;
                        case SpeechCommands.ID.HOWS_MY_SUSPENSION:
                            damageMessage = getDamageMessage(Component.SUSPENSION, true);
                            break;
                        case SpeechCommands.ID.HOWS_MY_BRAKES:
                            damageMessage = getDamageMessage(Component.BRAKES, true);
                            break;
                    }

                    if (!Game.IRACING && damageMessage != null)
                    {
                        // play this immediately or play "stand by", and queue it to be played in a few seconds
                        if (delayResponses && Utilities.random.Next(10) >= 2 && SoundCache.availableSounds.Contains(AudioPlayer.folderStandBy))
                        {
                            audioPlayer.pauseQueueAndPlayDelayedImmediateMessage(damageMessage, 5 /*lowerDelayBoundInclusive*/, 11 /*upperDelayBound*/);
                        }
                        else
                        {
                            audioPlayer.playMessageImmediately(damageMessage);
                        }
                    }
                    else if (Game.IRACING && CrewChief.currentGameState != null)
                    {
                        if (CrewChief.currentGameState.CarDamageData.OverallGeneralDamage > DamageLevel.NONE)
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage("damage", 0, MessageContents(folderGeneralDamage), priority: 15));
                        }
                        else
                        {
                            audioPlayer.playMessageImmediately(new QueuedMessage("damage", 0, MessageContents(folderNoDamageOnAnyComponent), priority: 15));
                        }
                    }
                    else
                    {
                        audioPlayer.playMessageImmediately(new QueuedMessage(AudioPlayer.folderNoData, 0));
                        Log.Commentary($"No data for {this.GetType().Name}");
                    }

                    break;
                }
            }
        }

        private Tuple<Component, DamageLevel> getWorstUnreportedDamage()
        {
            List<Tuple<Component, DamageLevel>> componentsWithMoreDamage = new List<Tuple<Component, DamageLevel>>();
            if (engineDamage > getLastReportedDamageLevel(Component.ENGINE))
            {
                componentsWithMoreDamage.Add(new Tuple<Component, DamageLevel> (Component.ENGINE, engineDamage));
            }
            if (trannyDamage > getLastReportedDamageLevel(Component.TRANNY))
            {
                componentsWithMoreDamage.Add(new Tuple<Component, DamageLevel>(Component.TRANNY, trannyDamage));
            }
            if (enableSuspensionDamageMessages && maxSuspensionDamage > getLastReportedDamageLevel(Component.SUSPENSION))
            {
                componentsWithMoreDamage.Add(new Tuple<Component, DamageLevel>(Component.SUSPENSION, maxSuspensionDamage));
            }
            if (enableBrakeDamageMessages && GlobalBehaviourSettings.enabledMessageTypes.Contains(MessageTypes.BRAKE_DAMAGE) &&
                maxBrakeDamage > getLastReportedDamageLevel(Component.BRAKES))
            {
                componentsWithMoreDamage.Add(new Tuple<Component, DamageLevel>(Component.BRAKES, maxBrakeDamage));
            }
            if (aeroDamage > getLastReportedDamageLevel(Component.AERO))
            {
                componentsWithMoreDamage.Add(new Tuple<Component, DamageLevel>(Component.AERO, aeroDamage));
            }
            switch (componentsWithMoreDamage.Count)
            {
                case 0:
                    return null;
                case 1:
                    return componentsWithMoreDamage[0];
                default:
                {
                    Tuple<Component, DamageLevel> worstUnreported = componentsWithMoreDamage[0];
                    for (int i = 1; i < componentsWithMoreDamage.Count; i++)
                    {
                        if (componentsWithMoreDamage[i].Item2 > worstUnreported.Item2)
                        {
                            worstUnreported = componentsWithMoreDamage[i];
                        }
                    }
                    return worstUnreported;
                }
            }
        }

        private void playDamageToReport(Boolean allowRants, DateTime now, Boolean inPitLane)
        {
            if (componentDestroyed != Component.NONE  // If there is any component already destroyed
                && damageToReportNext.Item1 != componentDestroyed)  // And it is not the current component
            {
                // Do not play any message, because it does not matter if Aero is minor after suspension is damaged.
                Console.WriteLine(string.Format("Not reporting damage: level {0} component {1} because {2} is already destroyed", damageToReportNext.Item2, damageToReportNext.Item1, componentDestroyed));
                return;
            }

            if (isMissingWheel || damageToReportNext.Item2 > DamageLevel.MINOR)
            {
                // missing wheel or major damage, so don't play other messages that might be queued - note this won't interrupt an
                // already playing message
                audioPlayer.purgeQueues();
                // if the damage is race-ending switch off pearls-of-wisdom for the remainder of the session
                if (damageToReportNext.Item2 == DamageLevel.DESTROYED)
                {
                    audioPlayer.disablePearlsOfWisdom = true;
                }
            }

            var validationData = new Dictionary<string, object>();
            validationData.Add(DamageReporting.validateMessageTypeKey, DamageReporting.validateMessageTypeDamage);
            validationData.Add(DamageReporting.validationComponentKey, damageToReportNext.Item1);
            validationData.Add(DamageReporting.validationDamageLevelKey, damageToReportNext.Item2);

            var minorDamageMsgDelay = Utilities.random.Next(4, 7);
            var minorDamageMsgExpiration = minorDamageMsgDelay + 10;
            var majorDamageMsgDelay = Utilities.random.Next(3, 6);
            var majorDamageMsgExpiration = majorDamageMsgDelay + 10;

            switch (damageToReportNext.Item1)
            {
                case Component.ENGINE:
                {
                    switch (damageToReportNext.Item2)
                    {
                        case DamageLevel.DESTROYED:
                        {
                            componentDestroyed = Component.ENGINE;
                            if (!checkIfDriverIsOK(now, inPitLane))
                            {
                                playBustedComponentMessage("Damage/busted_engine", folderBustedEngine, majorDamageMsgDelay, majorDamageMsgExpiration, allowRants, validationData);
                            }

                            break;
                        }
                        case DamageLevel.MAJOR:
                            audioPlayer.playMessage(new QueuedMessage(folderSevereEngineDamage, majorDamageMsgExpiration, secondsDelay: majorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                        case DamageLevel.MINOR:
                            audioPlayer.playMessage(new QueuedMessage(folderMinorEngineDamage, minorDamageMsgExpiration, secondsDelay: minorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                    }

                    break;
                }
                case Component.TRANNY:
                {
                    switch (damageToReportNext.Item2)
                    {
                        case DamageLevel.DESTROYED:
                        {
                            componentDestroyed = Component.TRANNY;
                            if (!checkIfDriverIsOK(now, inPitLane))
                            {
                                playBustedComponentMessage("Damage/busted_transmission", folderBustedTransmission, majorDamageMsgDelay, majorDamageMsgExpiration, allowRants, validationData);
                            }

                            break;
                        }
                        case DamageLevel.MAJOR:
                            audioPlayer.playMessage(new QueuedMessage(folderSevereTransmissionDamage, majorDamageMsgExpiration, secondsDelay: majorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                        case DamageLevel.MINOR:
                            audioPlayer.playMessage(new QueuedMessage(folderMinorTransmissionDamage, minorDamageMsgExpiration, secondsDelay: minorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                    }

                    break;
                }
                case Component.SUSPENSION:
                {
                    if (damageToReportNext.Item2 == DamageLevel.DESTROYED)
                    {
                        componentDestroyed = Component.SUSPENSION;
                        if (!checkIfDriverIsOK(now, inPitLane))
                        {
                            playBustedComponentMessage("Damage/busted_suspension", folderBustedSuspension, majorDamageMsgDelay, majorDamageMsgExpiration, allowRants, validationData);
                        }
                    }
                    else if (damageToReportNext.Item2 == DamageLevel.MAJOR || isMissingWheel)
                    {
                        if (isMissingWheel)
                        {
                            audioPlayer.playMessage(new QueuedMessage(folderMissingWheel, majorDamageMsgExpiration, secondsDelay: majorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                        }
                        audioPlayer.playMessage(new QueuedMessage(folderSevereSuspensionDamage, majorDamageMsgExpiration, secondsDelay: majorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                    }
                    else if (damageToReportNext.Item2 == DamageLevel.MINOR && !isMissingWheel)
                    {
                        audioPlayer.playMessage(new QueuedMessage(folderMinorSuspensionDamage, minorDamageMsgExpiration, secondsDelay: minorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                    }

                    break;
                }
                case Component.BRAKES:
                {
                    switch (damageToReportNext.Item2)
                    {
                        case DamageLevel.DESTROYED:
                            componentDestroyed = Component.BRAKES;
                            audioPlayer.playMessage(new QueuedMessage(folderBustedBrakes, majorDamageMsgExpiration, secondsDelay: majorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                        case DamageLevel.MAJOR:
                            audioPlayer.playMessage(new QueuedMessage(folderSevereBrakeDamage, majorDamageMsgExpiration, secondsDelay: majorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                        case DamageLevel.MINOR:
                            audioPlayer.playMessage(new QueuedMessage(folderMinorBrakeDamage, minorDamageMsgExpiration, secondsDelay: minorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                    }

                    break;
                }
                case Component.AERO:
                {
                    switch (damageToReportNext.Item2)
                    {
                        case DamageLevel.DESTROYED:
                        {
                            if (!checkIfDriverIsOK(now, inPitLane))
                            {
                                componentDestroyed = Component.AERO;
                                audioPlayer.playMessage(new QueuedMessage(folderSevereAeroDamage, majorDamageMsgExpiration, secondsDelay: majorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            }

                            break;
                        }
                        case DamageLevel.MAJOR:
                            audioPlayer.playMessage(new QueuedMessage(folderSevereAeroDamage, majorDamageMsgExpiration, secondsDelay: majorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                        case DamageLevel.MINOR:
                            audioPlayer.playMessage(new QueuedMessage(folderMinorAeroDamage, minorDamageMsgExpiration, secondsDelay: minorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData));
                            break;
                        case DamageLevel.TRIVIAL:
                            audioPlayer.playMessage(new QueuedMessage(folderJustAScratch, minorDamageMsgExpiration, secondsDelay: minorDamageMsgDelay, abstractEvent: this, priority: 3, validationData: validationData));
                            break;
                    }

                    break;
                }
            }
        }

        private void playBustedComponentMessage(string messageName, string messageFolder, int majorDamageMsgDelay, int majorDamageMsgExpiration, bool allowRants, Dictionary<string, object> validationData)
        {
            var messageFragments = new List<MessageFragment>();
            messageFragments.Add(MessageFragment.Text(messageFolder));
            var isRantMessage = false;
            if (allowRants)
            {
                isRantMessage = audioPlayer.getDelayedRant(messageFragments);
            }
            var message = new QueuedMessage(messageName, majorDamageMsgExpiration, messageFragments: messageFragments, secondsDelay: majorDamageMsgDelay, abstractEvent: this, priority: 15, validationData: validationData);
            message.isRant = isRantMessage;
            audioPlayer.playMessage(message);
        }

        private void checkOrientation(float speed)
        {
            if (isRolling)
            {
                // we were rolling at the last check
                if (speed < 2 && isUpsideDown(orientationSamples.Last.Value))
                {
                    // we're almost stopped and we're upside down
                    audioPlayer.playMessage(new QueuedMessage(folderStoppedUpsideDown, 0, abstractEvent: this, priority: 3));
                }
                else
                {
                    // we may be rolling, or may have reset and are now racing again:
                    audioPlayer.playMessage(new QueuedMessage(folderRolled, 0, abstractEvent: this, priority: 3));
                }
                // don't check again for a while:
                isRolling = false;
                orientationSamples.Clear();
                nextOrientationCheckDue = nextOrientationCheckDue.Add(TimeSpan.FromMinutes(5));
            }
            else
            {
                // lets see if we're rolling:
                int upsideDownCount = 0;
                foreach (PositionAndMotionData.Rotation orientationSample in orientationSamples)
                {
                    if (isUpsideDown(orientationSample))
                    {
                        upsideDownCount++;
                        if (upsideDownCount > 4)
                        {
                            isRolling = true;
                            break;
                        }
                    }
                }
            }
        }

        // returns whether we've decided to check if the driver is OK
        private Boolean checkIfDriverIsOK(DateTime now, Boolean inPitLane)
        {
            // if we don't have the updated sounds, just return false here
            // note that this check will be 3 seconds *after* the acceleration event because we've waited for
            // the damage to settle
            if (!GlobalBehaviourSettings.justTheFacts
                && SpeechRecogniser.hasMadeVoiceCommandSinceStarting /* don't ask if we're OK if we're not making any voice commands */
                && !playedAreYouOKInThisSession && !inPitLane &&
                SoundCache.availableSounds.Contains(folderAreYouOKFirstTry) && 
                now.Subtract(timeOfDangerousAcceleration) < TimeSpan.FromSeconds(5))
            {
                audioPlayer.purgeQueues();
                audioPlayer.playMessageImmediately(new QueuedMessage(folderAreYouOKFirstTry, 0, type: SoundType.CRITICAL_MESSAGE, priority: 15));
                // only kick off the 'waiting for response' stuff sometimes
                if (MainWindow.voiceOption != MainWindow.VoiceOptionEnum.DISABLED)
                {
                    playedAreYouOKInThisSession = true;
                    waitingForDriverIsOKResponse = true;
                    timeWhenAskedIfDriverIsOK = now;
                    driverIsOKRequestCount = 1;
                }
                return true;
            }
            return false;
        }

        private Boolean isUpsideDown(PositionAndMotionData.Rotation orientation)
        {
            float absRoll = Math.Abs(orientation.Pitch);
            float absPitch = Math.Abs(orientation.Roll);
            // 90 degrees is 1.5708 radians, but require a bit more here to allow for track camber
            return absRoll > 1.7 || absPitch > 1.7;
        }
    }
}
