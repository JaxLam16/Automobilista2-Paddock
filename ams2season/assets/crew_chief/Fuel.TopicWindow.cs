using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using CrewChiefV4.GameState;
using CrewChiefV4.UserInterface.TopicWindows;

namespace CrewChiefV4.Events
{
    partial class Fuel
    {
        private readonly Queue<float> topicEnergyMinuteSamples = new Queue<float>();
        private int topicEnergyLapNumber = -1;
        private DateTime topicEnergyLapTime;
        private float topicEnergyLapRemainingTime = -1f;
        private readonly Queue<float> topicEnergyLapSamples = new Queue<float>();
        private int topicPreviousEnergy = -1;
        private int topicEnergyAtLapStart = -1;
        private bool topicEnergyLapClean;
        private int topicFuelRatio;
        private bool topicEnergySeen;
        private readonly Queue<float> topicTraceFuelSamples = new Queue<float>();
        private float topicTraceLapStartFuel = -1f;
        private bool topicTraceLapClean;
        private float topicTracePreviousFuel = -1f;
        private DateTime topicNextRatioRead = DateTime.MinValue;

        private void ResetTopicWindowData(bool clearDisplay = false)
        {
            topicEnergyLapSamples.Clear();
            topicEnergyMinuteSamples.Clear();
            topicEnergyLapNumber = -1;
            topicPreviousEnergy = -1;
            topicEnergyAtLapStart = -1;
            topicEnergyLapClean = false;
            topicFuelRatio = 0;
            topicEnergySeen = false;
            topicNextRatioRead = DateTime.MinValue;
            topicTraceFuelSamples.Clear();
            topicTraceLapStartFuel = -1f;
            topicTracePreviousFuel = -1f;
            topicTraceLapClean = false;
            if (clearDisplay)
            {
                TopicWindowFuel.ResetData();
            }
        }

        private void UpdateTopicWindow(GameStateData previousGameState, GameStateData state)
        {
            if (state == null)
            {
                return;
            }
            // Retain the last usable snapshot after the finish, including end-of-trace reset calls.
            if (state.SessionData.SessionPhase >= SessionPhase.Finished)
            {
                return;
            }
            if (previousGameState == null ||
                previousGameState.carClass?.carClassEnumString != state.carClass?.carClassEnumString ||
                state.SessionData.CompletedLaps < previousGameState.SessionData.CompletedLaps)
            {
                ResetTopicWindowData(true);
            }
            if (CrewChief.viewingReplay && !CrewChief.loadDataFromFile)
            {
                return;
            }

            // Called before Fuel's early returns so levels still update in the pits and while refuelling.
            // Consumption and timed-race lap estimates use the latest completed calculation.

            bool fuelActive = state.FuelData.FuelUseActive || CrewChief.loadDataFromFile;
            TopicWindowFuel.SetFuelUseActive(fuelActive);
            if (!fuelActive)
            {
                return;
            }
            float tracePerLap = CrewChief.loadDataFromFile ? UpdateTraceFuelConsumption(state) : float.NaN;
            float perLap = getConsumptionPerLap();
            if (perLap <= 0 && tracePerLap > 0)
            {
                perLap = tracePerLap;
            }
            if (perLap <= 0)
            {
                perLap = float.NaN;
            }
            float lapTime = estimateFutureAverageLapTime(state);
            float perMinute = lapTime > 0 ? 60f * perLap / lapTime : float.NaN;
            int energy = LMU.VirtualEnergy.Read();
            if (energy > 0 && energy <= 100)
            {
                topicEnergySeen = true;
            }
            bool energyAvailable = topicEnergySeen;
            bool energyReadingValid = energy >= 0 && energy <= 100;
            float energyPerLap = UpdateTopicEnergyConsumption(state, energyAvailable && energyReadingValid ? energy : -1);
            float energyPerMinute = topicEnergyMinuteSamples.Count > 0
                ? topicEnergyMinuteSamples.Average() : float.NaN;

            float range = perLap > 0 ? state.FuelData.FuelLeft / perLap : float.NaN;
            if (energyAvailable && energyReadingValid && energyPerLap > 0)
            {
                float energyRange = energy / energyPerLap;
                range = range >= 0 ? Math.Min(range, energyRange) : energyRange;
            }
            float? targetLaps = null;
            bool finishTarget = false;
            bool race = state.SessionData.SessionType == SessionType.Race;
            // A trace can begin mid-race without the green-flag/new-lap callbacks that normally initialise this.
            if (race && state.SessionData.SessionHasFixedTime && lapsRemaining < 0 && lapTime > 0 &&
                (state.SessionData.OverallPosition == 1 || estimateFutureAverageLapTimeForLeader(state) > 0))
            {
                estimateLapsForFixedTimeRace(state);
            }
            int remaining = state.SessionData.SessionHasFixedTime ? lapsRemaining : state.SessionData.SessionLapsRemaining;
            if (race && state.SessionData.SessionHasFixedTime && remaining < 0 && lapTime > 0 &&
                state.SessionData.SessionTimeRemaining > 0)
            {
                // Display-only approximation when the leader data required by Fuel's estimator is absent.
                remaining = (int)Math.Ceiling(state.SessionData.SessionTimeRemaining / lapTime) + 1;
            }
            float fraction = state.SessionData.TrackDefinition != null && state.SessionData.TrackDefinition.trackLength > 0
                ? Math.Max(0f, Math.Min(1f, state.PositionAndMotionData.DistanceRoundTrack / state.SessionData.TrackDefinition.trackLength)) : 0f;
            float timeLeft = float.NaN;
            if (race && state.SessionData.SessionHasFixedTime)
            {
                timeLeft = state.SessionData.SessionTimeRemaining;
            }
            else if (race && remaining >= 0 && lapTime > 0)
            {
                timeLeft = Math.Max(0f, remaining - fraction) * lapTime;
            }
            if (state.SessionData.SessionPhase >= SessionPhase.Finished)
            {
                timeLeft = 0f;
            }
            TopicWindowFuel.SetTimeLeft(timeLeft);
            if (race && remaining >= 0)
            {
                float toFinish = Math.Max(0f, remaining - fraction);
                if (state.SessionData.SessionPhase >= SessionPhase.Finished)
                {
                    toFinish = 0f;
                }
                if (!(range >= 0) || range >= toFinish)
                {
                    targetLaps = toFinish;
                    finishTarget = true;
                }
            }
            // No planned stop is supplied by Fuel.cs: use the last complete lap within the limiting resource range.
            if (!targetLaps.HasValue && range >= 0)
            {
                targetLaps = (float)Math.Floor(range);
            }

            TopicWindowFuel.SetFuelData(state.FuelData.FuelLeft,
                state.FuelData.FuelCapacity > 0 ? (int)Math.Round(state.FuelData.FuelCapacity) : 0,
                perLap, perMinute, targetLaps, finishTarget);
            if (energyAvailable)
            {
                try
                {
                    UpdateTopicFuelRatio();
                }
                catch (Exception exception)
                {
                    // An optional display value must not interrupt fuel processing.
                    topicFuelRatio = 0;
                    Log.Fuel("Unable to read topic-window fuel ratio: " + exception.Message);
                }
            }
            else
            {
                topicFuelRatio = 0;
                topicNextRatioRead = DateTime.MinValue;
            }
            TopicWindowFuel.SetVirtualEnergyData(energyAvailable, energyReadingValid ? energy : float.NaN, topicFuelRatio,
                energyPerLap, energyPerMinute, targetLaps, finishTarget);
        }

        private float UpdateTopicEnergyConsumption(GameStateData state, int energy)
        {
            if (energy < 0)
            {
                topicEnergyAtLapStart = -1;
                topicEnergyLapNumber = -1;
                topicEnergyLapClean = false;
                return topicEnergyLapSamples.Count > 0 ? topicEnergyLapSamples.Average() : float.NaN;
            }
            if ((topicPreviousEnergy >= 0 && energy > topicPreviousEnergy) ||
                state.PitData.InPitlane || state.PitData.IsInGarage || state.PitData.JumpedToPits)
            {
                topicEnergyLapClean = false;
            }
            int completed = state.SessionData.CompletedLaps;
            if (completed != topicEnergyLapNumber)
            {
                int lapCount = completed - topicEnergyLapNumber;
                float used = topicEnergyAtLapStart - energy;
                double elapsed = state.SessionData.SessionHasFixedTime && topicEnergyLapRemainingTime >= 0
                    ? topicEnergyLapRemainingTime - state.SessionData.SessionTimeRemaining
                    : (state.Now - topicEnergyLapTime).TotalSeconds;
                if (topicEnergyLapClean && topicEnergyAtLapStart >= 0 && lapCount > 0 && used > 0 && elapsed > 0)
                {
                    topicEnergyLapSamples.Enqueue(used / lapCount);
                    topicEnergyMinuteSamples.Enqueue((float)(60 * used / elapsed));
                    while (topicEnergyLapSamples.Count > 3)
                    {
                        topicEnergyLapSamples.Dequeue();
                        topicEnergyMinuteSamples.Dequeue();
                    }
                }
                topicEnergyAtLapStart = energy;
                topicEnergyLapNumber = completed;
                topicEnergyLapTime = state.Now;
                topicEnergyLapRemainingTime = state.SessionData.SessionTimeRemaining;
                // The first observation may be mid-lap; only subsequent crossing-to-crossing samples are complete.
                topicEnergyLapClean = state.SessionData.IsNewLap && !state.PitData.InPitlane && !state.PitData.IsInGarage;
                if (topicPreviousEnergy >= 0 && lapCount > 0 && topicEnergyLapTime != DateTime.MinValue)
                {
                    topicEnergyLapClean = !state.PitData.InPitlane && !state.PitData.IsInGarage;
                }
            }
            topicPreviousEnergy = energy;
            return topicEnergyLapSamples.Count > 0 ? topicEnergyLapSamples.Average() : float.NaN;
        }

        private float UpdateTraceFuelConsumption(GameStateData state)
        {
            float fuel = state.FuelData.FuelLeft;
            if (fuel < 0 || (topicTracePreviousFuel >= 0 && fuel > topicTracePreviousFuel + 0.01f) ||
                state.PitData.InPitlane || state.PitData.IsInGarage || state.PitData.JumpedToPits)
            {
                topicTraceLapClean = false;
            }
            if (state.SessionData.IsNewLap)
            {
                float used = topicTraceLapStartFuel - fuel;
                if (topicTraceLapClean && topicTraceLapStartFuel >= 0 && used > 0)
                {
                    topicTraceFuelSamples.Enqueue(used);
                    while (topicTraceFuelSamples.Count > 3)
                    {
                        topicTraceFuelSamples.Dequeue();
                    }
                }
                topicTraceLapStartFuel = fuel;
                topicTraceLapClean = fuel >= 0 && !state.PitData.InPitlane && !state.PitData.IsInGarage;
            }
            topicTracePreviousFuel = fuel;
            return topicTraceFuelSamples.Count > 0 ? topicTraceFuelSamples.Average() : float.NaN;
        }

        private void UpdateTopicFuelRatio()
        {
            if (MapperClock.UtcNow < topicNextRatioRead)
            {
                return;
            }
            topicNextRatioRead = MapperClock.UtcNow.AddSeconds(1);
            var api = PitMenuAPI.LMUPitMenuAbstractionLayer.inst?.pmc as LMU.LMUPitMenuAPI;
            if (api == null)
            {
                return;
            }
            // The cache getter may initialise the cache; never force a REST refresh or select a menu category.
            var entry = api.cachedPitMenu?.FirstOrDefault(item => item.name == "FUEL RATIO:");
            if (entry == null || entry.settings == null)
            {
                return;
            }
            int setting = (int)entry.currentSetting;
            if (setting < 0 || setting >= entry.settings.Count)
            {
                return;
            }
            float ratio;
            string text = entry.settings[setting].text?.Trim().TrimEnd('%');
            if (float.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out ratio) && ratio > 0)
            {
                topicFuelRatio = (int)Math.Round(ratio);
            }
        }
    }
}
