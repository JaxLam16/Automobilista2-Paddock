"""Causal gaps from matched timing-point crossings, never distance divided by speed.

The midpoint avoids the lap-counter lag observed around start/finish. This is a
measured gap trend only: no catch forecast, tyre diagnosis or tactical instruction.
"""
from collections import Counter, deque
from dataclasses import dataclass

from .model import incident


@dataclass(frozen=True)
class Crossing:
    lap: int
    t: float


class CrossingClock:
    def __init__(self, *, allow_reverse=False):
        self.previous = None
        self.crossings = deque(maxlen=4)
        self.allow_reverse = allow_reverse
        self.reversed_step = False

    def feed(self, t, car, length):
        previous = self.previous
        self.previous = (t, car)
        if previous is None:
            return True
        last_t, last = previous
        dt = t-last_t
        delta = car.distance-last.distance
        wrapped = last.distance > .85*length and car.distance < .15*length
        if wrapped:
            delta += length
        lap_change = car.laps-last.laps
        near_line = last.distance > .85*length or car.distance < .15*length
        limit = max(20,dt*180)
        self.reversed_step = delta < 0
        if (not 0 < dt <= .5 or not (-limit if self.allow_reverse else 0) <= delta <= limit
                or lap_change not in (0, 1) or (lap_change and not near_line)):
            self.crossings.clear()
            return False
        marker = length*.5
        if delta < 0 and last.distance >= marker > car.distance:
            # Multiple crossings on one lap have no unambiguous timing timestamp.
            self.crossings.clear()
            return False
        if not wrapped and last.distance < marker <= car.distance:
            if lap_change or delta <= 0:
                self.crossings.clear()
                return False
            crossing = Crossing(car.laps, last_t+dt*(marker-last.distance)/delta)
            if self.crossings and crossing.lap != self.crossings[-1].lap+1:
                self.crossings.clear()
                self.crossings.append(crossing)
                return False
            self.crossings.append(crossing)
        return True


class GapWatch:
    def __init__(self, relation='car behind', *, clean_intervals=True, max_gap_s=20):
        if (relation not in ('car ahead','car behind') or type(clean_intervals) is not bool
                or type(max_gap_s) not in (int,float) or not .25 <= max_gap_s <= 300):
            raise ValueError('Choose the same-class car ahead or behind.')
        self.relation = relation
        self.clean_intervals = clean_intervals
        self.max_gap_s = max_gap_s
        self.diagnostics = Counter()
        self.clear()

    def clear(self):
        self.rival = None
        self.pair = None
        self.clocks = (CrossingClock(allow_reverse=not self.clean_intervals),
                       CrossingClock(allow_reverse=not self.clean_intervals))
        self.samples = deque(maxlen=3)
        self.latest = None
        self.current_safe = False
        self.affected_interval = False

    @staticmethod
    def safe(car, length):
        return (car is not None and car.pit == 0 and car.race_state == 2 and not car.invalid
                and car.flag_colour in (0, 1) and car.laps >= 0 and car.distance is not None
                and 0 <= car.distance < length)

    def feed(self, tick, player, rival):
        geometry_valid = (player is not None and rival is not None and all(
            c.pit==0 and c.race_state==2 and c.laps>=0 and c.distance is not None
            and 0 <= c.distance < tick.length for c in (player,rival)))
        reason = ('not_racing' if tick.session != 'race' else
                  'no_same_class_'+self.relation.replace(' ','_') if rival is None else
                  'pair_invalid_pit_flag_or_unknown' if not geometry_valid else
                  'class_unmatched_or_unknown' if not player.car_class or player.car_class != rival.car_class else
                  'position_unmatched_or_unknown' if player.position <= 0 or rival.position <= 0
                  or (rival.position >= player.position if self.relation=='car ahead' else rival.position <= player.position) else
                  'flag_or_incident_channels_unknown' if any(c.flag_colour not in range(12) for c in (player,rival))
                  or tick.local.get('crash_state') not in range(5) or tick.local.get('yellow_flag_state') not in range(9) else
                  'pair_invalid_pit_flag_or_unknown' if self.clean_intervals and (not self.safe(player,tick.length) or not self.safe(rival,tick.length)) else
                  'local_lap_invalid_or_unknown' if self.clean_intervals and tick.local.get('local_lap_invalid') is not False else
                  'local_incident_or_unknown' if self.clean_intervals and incident(tick.local.get('crash_state')) else
                  'caution_or_unknown' if self.clean_intervals and tick.local.get('yellow_flag_state') != 0 else None)
        if reason:
            self.diagnostics[reason] += 1
            self.clear()
            return None
        pair = (player.identity,rival.identity)
        if pair != self.pair:
            self.diagnostics['rival_baseline_started'] += 1
            self.clear()
            self.rival, self.pair = rival.identity, pair
        self.current_safe = (all(c.flag_colour in (0,1) for c in (player,rival))
                             and not incident(tick.local.get('crash_state')) and tick.local.get('yellow_flag_state')==0)
        if not self.current_safe:
            self.diagnostics['current_radio_conditions_unsafe'] += 1
        self.affected_interval |= (not self.current_safe or player.invalid or rival.invalid
                                   or tick.local.get('local_lap_invalid') is not False)
        front_car, back_car = (player,rival) if self.relation=='car behind' else (rival,player)
        continuous = [clock.feed(tick.t,car,tick.length) for clock,car in zip(self.clocks,(front_car,back_car))]
        self.affected_interval |= any(clock.reversed_step for clock in self.clocks)
        if not all(continuous):
            self.diagnostics['continuity_reset'] += 1
            self.clear()
            return None
        front_clock, back_clock = self.clocks
        if not front_clock.crossings or not back_clock.crossings:
            return None
        back = back_clock.crossings[-1]
        front = next((c for c in front_clock.crossings if c.lap == back.lap), None)
        if (front is None or not 0 <= tick.t-back.t <= .5 or not .25 <= back.t-front.t <= self.max_gap_s
                or (self.latest and back.lap <= self.latest['lap'])):
            return None
        sample = {'lap':back.lap,'player_crossing_t':front.t if self.relation=='car behind' else back.t,
                  'rival_crossing_t':back.t if self.relation=='car behind' else front.t,
                  'measured_t':back.t,'gap_s':back.t-front.t,
                  'affected_interval':bool(self.affected_interval)}
        if self.samples and sample['lap'] != self.samples[-1]['lap']+1:
            self.samples.clear()
        self.samples.append(sample)
        self.affected_interval = False
        self.diagnostics['matched_gap_samples'] += 1
        self.latest = {**sample,'token':f'{self.relation}:{rival.identity}:{back.lap}'}
        if len(self.samples) != 3 or not self.current_safe:
            return None
        changes = [b['gap_s']-a['gap_s'] for a,b in zip(self.samples,list(self.samples)[1:])]
        trend = ('steady' if max(abs(d) for d in changes) <= .1 else
                 'closing' if max(changes) <= -.15 else
                 'opening' if min(changes) >= .15 else None)
        if trend is None:
            self.diagnostics['inconsistent_trend'] += 1
            return None
        self.diagnostics['confirmed_trends'] += 1
        return {**self.latest,'rival':rival.identity,'rival_name':rival.name,'relation':self.relation,'trend':trend,
                'scope':'clean_gap_trend' if self.clean_intervals else 'observed_past_gap_change',
                'change_per_lap_s':sum(changes)/2,'timing_point_m':tick.length*.5,
                'samples':[dict(s) for s in self.samples]}

    def token(self, now):
        return self.latest['token'] if self.latest and self.current_safe and 0 <= now-self.latest['measured_t'] < 12 else None
