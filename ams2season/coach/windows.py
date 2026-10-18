"""Learn conservative radio windows from two completed clean laps, without hindsight."""
from __future__ import annotations

from collections import deque
import hashlib
import json
import math
from pathlib import Path
import time

from .model import finite, incident

# AMS2 reports the gearbox's own throttle cut during an upshift: one or two samples of
# reduced throttle while the gear reads neutral, then the next gear. That is not the
# driver lifting. Bridge it only when the brake stays off, the wheel stays straight,
# the throttle was full immediately before and is full again within this time, and the
# gear afterwards is higher. Same bounds as the shift filter in technique.py. Without
# gear data, or for anything longer or different, the stretch stays unsafe.
SHIFT_S = .35
SHIFT_LINK_S = .2


class WindowLearner:
    def __init__(self, length, bin_m=10):
        self.length = float(length)
        if not 100 <= self.length <= 100000:
            raise ValueError("Invalid track length.")
        self.bin_m = max(5, float(bin_m))
        self.n = math.ceil(self.length / self.bin_m)
        self.laps = deque(maxlen=2)
        self.provenance = deque(maxlen=2)
        self.completed = 0
        self.needs_current_lap = False
        self.lap = None
        self.cells = {}
        self.clean = True
        self.last_distance = None
        self.last_t = None
        self.start_distance = None
        self._radio_cursor = None
        self._radio_serial = 0
        self._radio_gap_t = None
        self._radio_gap_m = 0
        self._shift = None
        self._last_full = None
        self.shifts_bridged = 0

    def clear_current(self, *, keep_radio=False):
        self.lap = None
        self.cells = {}
        self.clean = True
        self.last_distance = self.last_t = self.start_distance = None
        self._shift = None
        self._last_full = None
        if not keep_radio:
            self._radio_cursor = None
            self._radio_gap_t = None
            self._radio_gap_m = 0

    @staticmethod
    def calm(local):
        brake, steer, speed = (finite(local.get(k)) for k in ("brake", "steering", "speed"))
        return (brake is not None and brake <= .03 and steer is not None and abs(steer) <= .06
                and speed is not None and speed >= 15)

    @staticmethod
    def safe(local):
        throttle = finite(local.get("throttle"))
        return WindowLearner.calm(local) and throttle is not None and throttle >= .93

    def _mark(self, index, safe, speed):
        old = self.cells.get(index)
        self.cells[index] = ((old[0] if old else True) and safe is not False, max(speed, old[1] if old else 0))

    def _fail_shift(self):
        shift, self._shift = self._shift, None
        if shift:
            for index in shift["bins"]:
                self._mark(index, False, 0)

    def _shift_continues(self, local, gear, now):
        throttle = finite(local.get("throttle"))
        if not self.calm(local) or throttle is None or gear is None:
            return False
        if self._shift is None:
            last = self._last_full
            if last is None or last[1] is None or last[1] < 1 or not 0 < now - last[0] <= SHIFT_LINK_S:
                return False
            self._shift = {"start_t": now, "last_t": now, "gear_before": last[1], "bins": set()}
        elif not 0 < now - self._shift["last_t"] <= SHIFT_LINK_S:
            return False
        if now - self._shift["start_t"] > SHIFT_S:
            return False
        self._shift["last_t"] = now
        return True

    def _end_shift(self, gear, now):
        shift, self._shift = self._shift, None
        if shift is None:
            return
        if (gear is not None and gear > shift["gear_before"] and 0 < now - shift["last_t"] <= SHIFT_LINK_S):
            self.shifts_bridged += 1
            return
        self._shift = shift
        self._fail_shift()

    def feed(self, tick, car):
        d = car.distance
        if d is None or not 0 <= d <= self.length or car.laps < 0:
            self.clear_current()
            return
        lap = car.laps
        wrapped = (self.last_distance is not None and self.last_distance > self.length * .85
                   and d < self.length * .15 and self.last_t is not None
                   and 0 < tick.t - self.last_t <= .5
                   and d + self.length - self.last_distance < max(20, (tick.t - self.last_t) * 180))
        if wrapped:
            self._fail_shift()  # an unresolved interruption at the line stays unsafe
            if (self.clean and self.start_distance is not None
                    and self.start_distance < self.length * .08 and self.last_distance > self.length * .92
                    and len(self.cells) >= self.n * .85):
                self.laps.append(dict(self.cells))
                self.provenance.append({'session_id':tick.session_id, 'completed_at_t':tick.t,
                                        'reported_laps_completed':car.laps})
                self.completed += 1
                self.needs_current_lap = False
            self.clear_current(keep_radio=True)
        elif self.lap is not None and (lap < self.lap or lap > self.lap + 1):
            self.clear_current()
        if self.lap is None:
            self.lap, self.start_distance = lap, d
        else:
            # mLapsCompleted can change a few snapshots before/after the distance
            # wraps. The geometric crossing, not the counter, ends a learned lap.
            self.lap = lap
        if (car.invalid or tick.local.get("local_lap_invalid") is not False or car.pit != 0
                or incident(tick.local.get("crash_state", -1))):
            self.clean = False
        if self.last_t is not None and (tick.t <= self.last_t or tick.t - self.last_t > .5):
            self.clean = False
        if self.last_distance is not None and d < self.last_distance - 8:
            # Lap counters can lag line crossings. Do not learn the mixed lap.
            self.clean = False
        index = min(self.n - 1, int(d / self.bin_m))
        speed = finite(tick.local.get("speed"), 0)
        gear = tick.local.get("gear")
        gear = gear if type(gear) is int else None
        if self.safe(tick.local):
            self._end_shift(gear, tick.t)
            self._mark(index, True, speed)
            self._last_full = (tick.t, gear)
        elif self._shift_continues(tick.local, gear, tick.t):
            # Provisional: decided when full throttle returns (or not) within SHIFT_S.
            self._shift["bins"].add(index)
            self._mark(index, None, speed)
        else:
            self._fail_shift()
            self._mark(index, False, speed)
            self._last_full = None
        self.last_distance, self.last_t = d, tick.t

    def seconds(self, distance, current_speed):
        if (len(self.laps) < 2 or self.needs_current_lap or distance is None
                or current_speed is None or current_speed < 10):
            return None
        if not 0 <= distance <= self.length:
            return None
        index = min(self.n - 1, int(distance / self.bin_m))
        seconds = 0.0
        # Stop at the first unknown/unsafe bin in either lap, with a 1s guard.
        for offset in range(self.n):
            b = (index + offset) % self.n
            data = [lap.get(b) for lap in self.laps]
            if any(cell is None or not cell[0] for cell in data):
                break
            distance_left = self.bin_m - distance % self.bin_m if offset == 0 else self.bin_m
            seconds += distance_left / max(current_speed * 1.15, *(cell[1] for cell in data), 10)
            if seconds > 25:
                break
        return max(0, seconds - 1)

    def _safe_bin(self, index):
        return all(lap.get(index,(False,0))[0] for lap in self.laps)

    def window_id(self, distance, now):
        """A contiguous learned straight, including one that crosses the start line.

        Short lifts/gaps cannot earn a second call on the same straight. Up to
        60m/1s is bridged for the budget only: unsafe bins still cannot authorize
        speech. Larger gaps, corners and capture discontinuities end the span.
        """
        if (len(self.laps)<2 or self.needs_current_lap or distance is None
                or not 0 <= distance <= self.length):
            self._radio_cursor = None
            self._radio_gap_t = None
            self._radio_gap_m = 0
            return None
        index = min(self.n-1,int(distance/self.bin_m))
        safe = self._safe_bin(index)
        previous = self._radio_cursor
        continuous = False
        travel = 0
        if previous:
            old_distance,old_t,serial = previous
            travel = (distance-old_distance)%self.length
            dt = now-old_t
            if 0 < dt <= .5 and travel <= max(20,dt*180):
                old_index = min(self.n-1,int(old_distance/self.bin_m))
                steps = (index-old_index)%self.n
                unsafe_m = self.bin_m*sum(not self._safe_bin((old_index+i)%self.n) for i in range(steps+1))
                continuous = unsafe_m<=60
        if not safe:
            if continuous:
                if self._radio_gap_t is None:
                    self._radio_gap_t = now
                    self._radio_gap_m = 0
                self._radio_gap_m += travel
                if now-self._radio_gap_t<=1 and self._radio_gap_m<=60:
                    self._radio_cursor = (distance,now,self._radio_serial)
                    return None
            self._radio_cursor = None
            self._radio_gap_t = None
            self._radio_gap_m = 0
            return None
        if self._radio_gap_t is not None:
            continuous = continuous and now-self._radio_gap_t<=1 and self._radio_gap_m+travel<=60
        if not continuous:
            self._radio_serial += 1
        self._radio_gap_t = None
        self._radio_gap_m = 0
        self._radio_cursor = (distance,now,self._radio_serial)
        return str(self._radio_serial)


def weather_key(rain):
    rain = finite(rain)
    if rain is None or not 0 <= rain <= 1:
        return 'unknown'
    return 'dry' if rain <= .05 else 'damp' if rain < .45 else 'wet'


class WindowStore:
    """Derived sidecars beside track files; never modify track geometry or recordings.

    Cached laps cannot authorize a call until a new complete clean lap validates
    current conditions. Offline replay deliberately does not use this live store.
    """
    def __init__(self, root, clock=time.time):
        self.directory = Path(root)/'tracks'/'private_coach'/'radio-windows'
        self.clock = clock

    @staticmethod
    def identity(tick, player):
        weather = weather_key(tick.local.get('rain_density'))
        if not player or not player.name or not player.car or not tick.track or weather == 'unknown':
            return None
        return {'track':tick.track,'layout':tick.layout,'length_m':round(tick.length,1),
                'driver':player.name,'car':player.car,'weather':weather,'bin_m':10}

    def path(self, identity):
        digest = hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return self.directory/(digest+'.json')

    def load(self, identity, learner):
        if identity is None:
            return False
        path = self.path(identity)
        if not path.is_file():
            return False
        if path.stat().st_size > 2 << 20:
            raise ValueError('Saved radio windows are too large.')
        data = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data,dict) or data.get('schema') != 1
                or data.get('method') != 'clean-lap-radio-v1' or data.get('identity') != identity
                or learner.bin_m != identity['bin_m'] or round(learner.length,1) != identity['length_m']):
            raise ValueError('Saved radio windows use a different track/car or learning method.')
        saved = finite(data.get('saved_at'))
        if saved is None or not 0 <= self.clock()-saved <= 30*86400:
            return False
        if not isinstance(data.get('laps'),list) or len(data['laps']) != 2:
            raise ValueError('Two complete reference laps are required.')
        laps, provenance = [], []
        for lap in data['laps']:
            cells = {}
            for index,safe,speed in lap['cells']:
                if (type(index) is not int or not 0 <= index < learner.n or index in cells
                        or type(safe) is not bool or type(speed) not in (float,int)
                        or finite(speed) is None or not 0 <= speed <= 160):
                    raise ValueError('Invalid radio-window sample.')
                cells[index] = (safe,float(speed))
            source = lap['source']
            if (len(cells) < learner.n*.85 or not isinstance(source,dict)
                    or not isinstance(source.get('session_id'),str) or not source['session_id']
                    or finite(source.get('completed_at_t')) is None):
                raise ValueError('Incomplete radio-window provenance.')
            laps.append(cells)
            provenance.append(source)
        learner.laps.extend(laps)
        learner.provenance.extend(provenance)
        learner.needs_current_lap = True
        return True

    def save(self, identity, learner):
        if identity is None or learner.needs_current_lap or len(learner.laps) != 2:
            return
        data = {'schema':1,'method':'clean-lap-radio-v1','identity':identity,'saved_at':self.clock(),
                'laps':[{'source':source,'cells':[[i,safe,speed] for i,(safe,speed) in sorted(lap.items())]}
                        for lap,source in zip(learner.laps,learner.provenance)]}
        self.directory.mkdir(parents=True,exist_ok=True)
        path = self.path(identity)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        temporary.replace(path)
