"""C-26: running wide on a lap the game still counts. A warning, not a penalty call.

AMS2 reports an off-track state (mCrashState 1) while the car is beyond the track
edge. Only the game's own lap-invalid flag decides track limits, so a lap it still
counts stays clean. When the car runs wide at the same spot on two of the last
three laps, including this one, and the lap is still valid a second after it is
back on track, the engineer warns that a little further could cost the lap.

It does not know how close the game's limit is, never says a lap will be deleted,
and stays quiet for impacts, spins, rolls, unknown states, the pit lane, a changed
lap or an invalidated lap.
"""
from collections import Counter, deque
from statistics import median

SPOT_M = 75        # episodes this close together are the same place
CONFIRM_S = 1.0    # the lap must still be valid this long after rejoining
TOKEN_S = 30       # a confirmed warning stays sayable this long


def apart(a, b, length):
    gap = abs(a-b) % length
    return min(gap, length-gap)


class OffTrackWatch:
    def __init__(self):
        self.diagnostics = Counter()
        self.clear()

    def clear(self, reason='learning'):
        self.episodes = deque(maxlen=24)
        self.current = None
        self.pending = None
        self.patterns = {}
        self.reason = reason

    def _drop_current(self, reason):
        if self.current or self.pending:
            self.diagnostics[reason] += 1
        self.current = self.pending = None
        self.reason = reason

    def feed(self, tick, player, *, active=True, reason='inactive'):
        if not active or tick.session not in ('practice', 'qualify', 'race'):
            self._drop_current(reason if not active else 'session_type')
            return []
        if (player is None or player.distance is None or player.laps < 0 or player.pit != 0
                or player.race_state != 2 or not 0 <= player.distance <= tick.length+1):
            self._drop_current('not_on_track')
            return []
        state = tick.local.get('crash_state')
        valid = tick.local.get('local_lap_invalid') is False and not player.invalid
        if state == 1:
            if self.current is None:
                self.current = {'lap': player.laps, 'start_m': player.distance, 'start_t': tick.t,
                                'valid': True}
            if player.laps != self.current['lap']:
                self._drop_current('crossed_the_line_while_wide')
                return []
            self.current.update(end_m=player.distance, end_t=tick.t,
                                valid=self.current['valid'] and valid)
            self.pending = None
            self.reason = 'running_wide'
            return []
        if state != 0:
            # Impact, spin, roll or an unknown channel: not a running-wide moment.
            self._drop_current('incident_or_unknown')
            return []
        if self.current is not None:
            self.pending = {**self.current, 'back_t': tick.t}
            self.current = None
        if self.pending is None or tick.t-self.pending['back_t'] < CONFIRM_S:
            return []
        episode, self.pending = self.pending, None
        if not (valid and episode['valid'] and player.laps == episode['lap']):
            self.diagnostics['lap_invalidated_or_changed'] += 1
            self.reason = 'lap_invalidated_or_changed'
            return []
        episode['seconds'] = episode['end_t']-episode['start_t']
        self.diagnostics['valid_lap_episodes'] += 1
        return self._record(episode, tick)

    def _record(self, episode, tick):
        same = [e for e in self.episodes if episode['lap']-2 <= e['lap'] < episode['lap']
                and apart(e['start_m'], episode['start_m'], tick.length) <= SPOT_M]
        self.episodes.append(episode)
        if not same:
            self.reason = 'first_time_at_this_spot'
            return []
        # Latest earlier lap at this spot, plus this lap: two of the last three.
        earlier = max(same, key=lambda e: e['lap'])
        group = [earlier, episode]
        spot = median(e['start_m'] for e in group)
        key = str(int(round(spot/100.)*100))
        value = {'key': key, 'distance_m': round(spot), 'laps': [e['lap'] for e in group],
                 'episodes': [{k: v for k, v in e.items() if k != 'valid'} for e in group],
                 'source': 'game_offtrack_state_on_valid_laps', 'lap_still_valid': True,
                 'track_limit_margin_known': False, 'cause_attributed': False,
                 'measured_t': tick.t, 'token': f"wide:{key}:{episode['lap']}:{tick.t}"}
        self.patterns[key] = value
        self.reason = 'confirmed_pattern'
        self.diagnostics['confirmed_patterns'] += 1
        return [value]

    def token(self, key, tick, player):
        value = self.patterns.get(key)
        if (value is None or player is None or player.pit != 0 or player.invalid
                or tick.local.get('local_lap_invalid') is not False
                or tick.local.get('crash_state') not in (0, 1)
                or not 0 <= tick.t-value['measured_t'] < TOKEN_S):
            return None
        return value['token']

    def status(self):
        return {'reason': self.reason, 'episodes_on_valid_laps': len(self.episodes),
                'spots': sorted({int(round(e['start_m']/100.)*100) for e in self.episodes}),
                'diagnostics': dict(self.diagnostics)}
