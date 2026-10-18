"""Observed race settings and bounded leader finish estimates, never a fuel plan.

Overall leader, not class leader. Timed forecasts use three complete observed
start/finish laps and verified seconds countdown. No distance/speed extrapolation.
"""
from collections import Counter, deque
from math import ceil

from .model import count, finite


class RaceLengthWatch:
    def __init__(self):
        self.diagnostics = Counter()
        self.last_estimate = None
        self.clear()

    def clear(self, reason='learning', *, keep_history=True):
        self.key = None
        self.reading = None
        self.reason = reason
        self.timer_previous = self.timer_anchor = None
        self.timer_verified = False
        self.expiry_t = None
        self.expired = False
        self._clear_pace()
        if not keep_history:
            self.last_estimate = None

    def _clear_pace(self):
        self.previous = self.anchor = self.pending = None
        self.samples = deque(maxlen=3)
        self.first_after_expiry = None
        self.expiry_crossing_ambiguous = False

    def _timer(self, t, remaining):
        previous = self.timer_previous
        if remaining is None or (remaining < 0 and remaining != -1):
            return 'timer_unknown'
        if remaining == -1:
            if self.expired:
                return None
            if (previous and self.timer_verified and 0 < t-previous[0] <= .5
                    and 0 <= previous[1] <= t-previous[0]+.15):
                self.expiry_t = previous[0]+previous[1]
                self.expired = True
                return None
            return 'timer_expiry_unobserved'
        if self.expired:
            if remaining == 0:
                return None
            return 'timer_restarted'
        if previous:
            dt = t-previous[0]
            if not 0 < dt <= .5 or abs((previous[1]-remaining)-dt) > .5:
                return 'timer_discontinuity'
        if self.timer_anchor is None:
            self.timer_anchor = (t,remaining)
        elapsed = t-self.timer_anchor[0]
        if elapsed >= 2:
            rate = (self.timer_anchor[1]-remaining)/elapsed
            if not .9 <= rate <= 1.1:
                return 'timer_rate_unverified'
            self.timer_verified = True
        self.timer_previous = (t,remaining)
        self.expiry_t = t+remaining
        if remaining == 0 and self.timer_verified:
            self.expired = True
        return None if self.timer_verified else 'verifying_countdown'

    def _lap(self, tick, leader):
        previous = self.previous
        self.previous = (tick.t,leader)
        if previous is None:
            return None
        stamp,old = previous
        dt = tick.t-stamp
        # Recorded track length is rounded; AMS2 also briefly reports an endpoint
        # up to a few decimetres beyond it before the distance wraps. Only the last
        # metre is bounded to the endpoint; counter confirmation is still required.
        old_distance = min(old.distance,tick.length)
        distance = min(leader.distance,tick.length)
        wrap = old_distance > .85*tick.length and distance < .15*tick.length
        delta = distance-old_distance+(tick.length if wrap else 0)
        if (not 0 < dt <= .5 or not 0 <= delta <= max(20,dt*180)
                or leader.laps-old.laps not in (0,1)
                or (leader.laps != old.laps and not (wrap or self.pending))):
            return 'leader_geometry_discontinuity'
        if wrap:
            if self.pending:
                return 'leader_counter_ambiguous'
            crossing_t = stamp+dt*(tick.length-old_distance)/delta if delta>0 else stamp
            self.pending = {'lap':old.laps+1,'t':crossing_t}
        if self.pending:
            if leader.laps == self.pending['lap']:
                crossing = self.pending
                self.pending = None
                if self.anchor:
                    seconds = crossing['t']-self.anchor['t']
                    if crossing['lap'] != self.anchor['lap']+1 or not 10 <= seconds <= 1800:
                        return 'leader_lap_discontinuity'
                    self.samples.append({'start_t':self.anchor['t'],'end_t':crossing['t'],
                                         'lap':crossing['lap'],'seconds':seconds})
                    if self.expiry_t is not None:
                        if abs(crossing['t']-self.expiry_t) <= .5:
                            self.expiry_crossing_ambiguous = True
                        elif self.anchor['t'] < self.expiry_t < crossing['t']:
                            self.first_after_expiry = crossing['lap']
                self.anchor = crossing
            elif tick.t-self.pending['t'] > 1 or leader.laps > self.pending['lap']:
                return 'leader_counter_unconfirmed'
        return None

    def feed(self, tick, player, *, active=True, reason='inactive'):
        if not active or tick.session != 'race':
            self.clear(reason if not active else 'not_race')
            return None
        laps = count(tick.local.get('race_laps'))
        duration = finite(tick.local.get('session_duration_s'))
        extra = count(tick.local.get('session_additional_laps'))
        mode = ('laps' if laps > 0 and duration == 0 else
                'timed' if laps == 0 and duration is not None and 0 < duration <= 604800 else None)
        leaders = [c for c in tick.cars if c.position == 1 and c.race_state in (2,3)]
        if mode is None or len(leaders) != 1 or player is None:
            self.clear('race_settings_unknown' if mode is None else 'overall_leader_unknown')
            return None
        leader = leaders[0]
        key = (tick.session_id,player.identity,leader.identity,mode,laps,duration,extra)
        if key != self.key:
            self.clear('learning',keep_history=False)
            self.key = key
        self.reading = None
        base = {'mode':mode,'leader':leader.identity,'leader_name':leader.name,
                'leader_class':leader.car_class,'scope':'overall_leader',
                'scheduled_laps':laps if mode=='laps' else None,
                'duration_s':duration,'additional_laps':extra if extra>=0 else None,'updated_t':tick.t}
        if leader.laps < 0:
            self.reason = 'leader_lap_unknown'
            return None
        if leader.race_state == 3:
            if leader.laps < 1:
                self.reason = 'leader_finish_counter_unknown'
                return None
            return self._publish({**base,'state':'observed_finish','finish_lap_low':leader.laps,
                                  'finish_lap_high':leader.laps,'source':'observed_leader_finished'})
        if mode == 'laps':
            return self._publish({**base,'state':'scheduled','finish_lap_low':laps,'finish_lap_high':laps,
                                  'source':'reported_lap_limit'})
        if extra < 0 or extra > 10:
            self.reason = 'additional_laps_unknown'
            return None
        remaining = finite(tick.local.get('event_time_remaining_s'))
        if remaining is not None and remaining > duration+.5:
            remaining = None
        timer_reason = self._timer(tick.t,remaining)
        if timer_reason not in (None,'verifying_countdown'):
            self.diagnostics[timer_reason] += 1
            self.clear(timer_reason)
            return None
        safe = (leader.pit==0 and not leader.invalid and leader.flag_colour in (0,1)
                and tick.local.get('yellow_flag_state')==0 and leader.distance is not None
                and 0 <= leader.distance <= tick.length+1)
        if not safe:
            self._clear_pace()
            self.reason = 'leader_pit_invalid_flag_or_unknown'
            return None
        lap_reason = self._lap(tick,leader)
        if lap_reason:
            self.diagnostics[lap_reason] += 1
            self._clear_pace()
            self.reason = lap_reason
            return None
        if timer_reason or len(self.samples) < 3 or not self.anchor:
            self.reason = timer_reason or 'learning_leader_laps'
            return None
        times = [s['seconds'] for s in self.samples]
        if max(times)/min(times) > 1.15 or tick.t-self.anchor['t'] > max(times)*1.5:
            self.reason = 'leader_pace_variable_or_stale'
            return None
        if self.expired and self.expiry_crossing_ambiguous:
            self.reason = 'timer_finish_line_boundary_ambiguous'
            return None
        if self.first_after_expiry is not None:
            low = high = self.first_after_expiry+extra
            if leader.laps >= high:
                self.reason = 'awaiting_finish_state'
                return None
        elif self.anchor['t'] < self.expiry_t:
            # A half-second boundary band avoids a false exact lap at timer/SF ties.
            delta = self.expiry_t-self.anchor['t']
            low = self.anchor['lap']+ceil(max(0,delta-.5)/max(times))+extra
            high = self.anchor['lap']+ceil((delta+.5)/min(times))+extra
        else:
            self.reason = 'expiry_crossing_unobserved'
            return None
        low,high = max(low,leader.laps+1),max(high,leader.laps+1)
        return self._publish({**base,'state':'estimated','source':'observed_leader_finish_line_laps',
            'finish_lap_low':low,'finish_lap_high':high,'expiry_t':self.expiry_t,
            'timer_expired':self.expired,'anchor':dict(self.anchor),'samples':list(self.samples),
            'minimum_lap_s':min(times),'maximum_lap_s':max(times),'boundary_band_s':.5,
            'finish_line_geometry_tolerance_m':1.0})

    def _publish(self, reading):
        self.reading = reading
        self.last_estimate = dict(reading)
        self.reason = reading['state']
        return reading

    def status(self, now):
        current = self.reading if self.reading and 0 <= now-self.reading['updated_t'] <= .5 else None
        return {'state':current['state'] if current else 'unavailable','reason':self.reason if not self.reading or current else 'stale',
                'current':current,'last_estimate':self.last_estimate,
                'clean_leader_samples':len(self.samples),'required_samples':3,'diagnostics':dict(self.diagnostics)}
