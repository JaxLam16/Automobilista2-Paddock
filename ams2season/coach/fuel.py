"""Measured local fuel use; no assumed multiplier, race length or pit recommendation.

Full midpoint-to-midpoint laps avoid start/finish counter lag and partial laps.
Invalid intervals cannot teach the model. Three fresh, consistent clean samples
are required before exposing a range based on their observed minimum/maximum use.
"""
from collections import Counter, deque
from dataclasses import asdict
from statistics import median

from .gaps import CrossingClock
from .model import finite, incident


class FuelWatch:
    def __init__(self):
        self.diagnostics = Counter()
        self.serial = 0
        self.last_calibration = None
        self.clear()

    def clear(self, reason='learning', *, keep_history=True):
        self.last_reading = None
        self._invalidate(reason, keep_samples=False)
        if not keep_history:
            self.last_calibration = None

    def _invalidate(self, reason, *, keep_samples=True):
        self.clock = CrossingClock()
        self.previous = None
        self.anchor = None
        self.model = None
        self.reason = reason
        if not keep_samples:
            self.samples = deque(maxlen=5)

    def feed(self, tick, player):
        fraction = finite(tick.local.get('fuel_level'))
        capacity = finite(tick.local.get('fuel_capacity'))
        if fraction is None or not 0 <= fraction <= 1 or capacity is None or not 0 < capacity <= 2000:
            self.diagnostics['fuel_channels_unavailable'] += 1
            self.clear('fuel_channels_unavailable')
            return None
        litres = fraction*capacity
        previous_reading = self.last_reading
        self.last_reading = (tick.t,litres,capacity)
        if previous_reading:
            stamp,old_litres,old_capacity = previous_reading
            dt = tick.t-stamp
            reason = ('capacity_changed' if abs(capacity-old_capacity) > .001 else
                      'telemetry_gap' if not 0 < dt <= .5 else
                      'refuel_or_increase' if litres-old_litres > .005 else
                      'fuel_discontinuity' if old_litres-litres > .01+2*dt else None)
            if reason:
                self.diagnostics[reason] += 1
                self._invalidate(reason,keep_samples=False)
                return None
        reason = ('player_state_unavailable' if player is None or player.distance is None or player.laps < 0
                  or not 0 <= player.distance < tick.length else
                  'pit_or_not_running' if player.pit != 0 or player.race_state != 2 else
                  'invalid_lap' if player.invalid or tick.local.get('local_lap_invalid') is not False else
                  'flag_or_caution' if player.flag_colour not in (0,1) or tick.local.get('yellow_flag_state') != 0 else
                  'incident_or_unknown' if incident(tick.local.get('crash_state')) else
                  'weather_unknown' if finite(tick.local.get('rain_density')) is None else None)
        if reason:
            self.diagnostics[reason] += 1
            self._invalidate(reason)
            return None
        previous = self.previous
        self.previous = (tick.t,litres)
        if not self.clock.feed(tick.t,player,tick.length):
            self.diagnostics['distance_or_counter_discontinuity'] += 1
            self._invalidate('distance_or_counter_discontinuity',keep_samples=False)
            return None
        result = None
        if self.clock.crossings:
            crossing = self.clock.crossings[-1]
            if self.anchor is None or crossing.t > self.anchor['t']:
                if previous is not None:
                    stamp,old_litres = previous
                    at_line = old_litres+(litres-old_litres)*(crossing.t-stamp)/(tick.t-stamp)
                    anchor = {'lap':crossing.lap,'t':crossing.t,'litres':at_line}
                    if self.anchor is not None:
                        used = self.anchor['litres']-at_line
                        seconds = crossing.t-self.anchor['t']
                        if crossing.lap == self.anchor['lap']+1 and .01 <= used <= min(capacity,200) and 10 <= seconds <= 1800:
                            sample = {'lap':crossing.lap,'start_t':self.anchor['t'],'end_t':crossing.t,
                                      'start_litres':self.anchor['litres'],'end_litres':at_line,
                                      'used_litres':used,'seconds':seconds}
                            self.samples.append(sample)
                            self.diagnostics['clean_lap_samples'] += 1
                            result = self._calibrate(tick,capacity,litres)
                        else:
                            self.model = None
                            self.reason = 'zero_or_invalid_lap_use'
                            self.diagnostics[self.reason] += 1
                    self.anchor = anchor
        if self.model:
            self.model['fuel_litres'] = litres
            self.model['updated_t'] = tick.t
        return result

    def _calibrate(self, tick, capacity,litres):
        if len(self.samples) < 3:
            self.reason = 'learning'
            return None
        samples = list(self.samples)[-3:]
        # A much older run cannot silently calibrate current driving.
        max_age = max(900,6*samples[-1]['seconds'])
        if tick.t-samples[0]['end_t'] > max_age:
            self.model = None
            self.reason = 'samples_too_old'
            return None
        used = [s['used_litres'] for s in samples]
        typical = median(used)
        if (max(used)-min(used))/typical > .15:
            self.model = None
            self.reason = 'variable_consumption'
            self.diagnostics[self.reason] += 1
            return None
        self.serial += 1
        self.model = {'token':f'fuel:{self.serial}','litres_per_lap':typical,
                      'minimum_litres_per_lap':min(used),'maximum_litres_per_lap':max(used),
                      'spread_litres_per_lap':max(used)-min(used),'capacity_litres':capacity,
                      'fuel_litres':litres,'updated_t':tick.t,
                      'measured_t':samples[-1]['end_t'],'samples':samples,
                      'timing_point_m':tick.length*.5}
        self.reason = 'calibrated'
        # A historical consumption measurement is not a current fuel/range claim.
        self.last_calibration = {'measured_t':self.model['measured_t'],
                                 'lap':samples[-1]['lap']+1,'litres_per_lap':typical}
        self.diagnostics['calibrations'] += 1
        return dict(self.model)

    def estimate(self, now):
        if not self.model:
            return None
        model = self.model
        max_age = max(120,model['samples'][-1]['seconds']*1.5)
        if not 0 <= now-model['measured_t'] <= max_age or not 0 <= now-model['updated_t'] <= .5:
            return None
        return {**model,'range_laps':model['fuel_litres']/model['litres_per_lap'],
                'range_low_laps':model['fuel_litres']/model['maximum_litres_per_lap'],
                'range_high_laps':model['fuel_litres']/model['minimum_litres_per_lap']}

    def token(self, now):
        estimate = self.estimate(now)
        return estimate['token'] if estimate else None

    def status(self, now, numbers):
        estimate = self.estimate(now)
        formatted = None
        if estimate:
            formatted = {'use':asdict(numbers.fuel_burn(estimate['litres_per_lap'])),
                         'remaining_is_estimate':numbers.units.fuel=='laps',
                         'minimum_use':asdict(numbers.fuel_burn(estimate['minimum_litres_per_lap'])),
                         'maximum_use':asdict(numbers.fuel_burn(estimate['maximum_litres_per_lap'])),
                         'remaining':asdict(numbers.fuel_litres(estimate['fuel_litres'],
                                        litres_per_lap=estimate['litres_per_lap']))}
        return {'state':'calibrated' if estimate else 'learning',
                'reason':self.reason if estimate or not self.model else 'calibration_stale',
                'clean_samples':len(self.samples),'required_samples':3,
                'estimate':estimate,'formatted':formatted,'diagnostics':dict(self.diagnostics),
                'last_calibration':{**self.last_calibration,
                    'use':asdict(numbers.fuel_burn(self.last_calibration['litres_per_lap']))}
                    if self.last_calibration else None}
