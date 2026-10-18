"""Standalone race-engineer basics: lap times at the line, deleted laps, tyre and brake
temperatures, and low fuel. These are the calls Crew Chief makes; with Paddock speaking
for itself they come from here.

Every call is built from the game's own telemetry for the driver's car. Lap times are
the game's last-lap time (with the line-to-line time as a check when two laps are
identical); a lap counts as deleted only when the game invalidates it. Temperatures are
smoothed over a few seconds so one hot braking zone is not called a hot tyre. Hot-brake
calls need a car whose brake type is known from its class (iron brakes); otherwise they
stay quiet rather than guess.
"""
from __future__ import annotations

from collections import Counter, deque

from .model import finite

WHEELS = ('fl', 'fr', 'rl', 'rr')
AXLES = {'front': (0, 1), 'rear': (2, 3)}
TYRE_WINDOW = {'temp_lo': 80.0, 'temp_hi': 100.0}   # surface degC, unless the car has its own window

TYRE_EMA_S = 4.0          # smoothing for surface temperatures
HOT_MARGIN_C = 5.0        # this far above the window ...
HOT_HOLD_S = 15.0         # ... for this long is a hot axle
HOT_REPEAT_S = 180.0
COLD_MARGIN_C = 15.0      # this far below the window, after being warm ...
COLD_HOLD_S = 30.0        # ... for this long is an axle that has cooled
READY_HOLD_S = 5.0        # all four in the window this long: tyres are up to temperature
PIT_COLD_TYRE_C = 50.0    # leaving the pits below this: cold tyres
PIT_COLD_BRAKE_C = 150.0  # front brakes below this leaving the pits: cold brakes
IRON_BRAKE_HOT_C = {'front': 850.0, 'rear': 750.0}   # lap peak, on two laps running
IRON_CLASSES = ('gt3', 'gt4', 'gte', 'gt1', 'gt2', 'gts', 'cup', 'stock', 'touring', 'tcr', 'tc ', 'super v8',
                'copa', 'mini', 'ginetta', 'caterham', 'camaro', 'trans am', 'turismo')
LAP_ACCEPT_S = 3.0        # the game's last-lap time must arrive this soon after the line
SAME_LAP_S = .15          # an unchanged last-lap time counts if the line-to-line time agrees
SAME_WAIT_S = 1.5         # ... and it has stayed unchanged this long after the line


def iron_brakes(car_class):
    name = ' ' + str(car_class or '').lower() + ' '
    return any(token in name for token in IRON_CLASSES)


def wet_compound(compound):
    name = str(compound or '').lower()
    return 'wet' in name or 'rain' in name


class LapWatch:
    """C-35 lap time at the line, with how it compares; Q-09 when the game deletes the lap."""

    def __init__(self):
        self.diagnostics = Counter()
        self.best = None
        self.clear()

    def clear(self, keep_best=True):
        self.laps = None
        self.flags = None
        self.pending = None
        self.last_seen = None
        self.previous = None
        self.crossings = deque(maxlen=3)
        if not keep_best:
            self.best = None

    def _crossing(self, tick, player):
        """Interpolated time the car crossed the start/finish line, from the lap-distance wrap."""
        previous = self.previous
        self.previous = (tick.t, player.distance)
        if previous is None or player.distance is None or previous[1] is None or tick.length <= 0:
            return None
        t0, d0 = previous
        if not (d0 > .8 * tick.length and player.distance < .2 * tick.length) or not 0 < tick.t - t0 <= .5:
            return None
        before, after = tick.length - d0, player.distance
        return t0 + (tick.t - t0) * before / max(before + after, 1e-6)

    @staticmethod
    def _flags(player, invalid):
        return {'pit': player.pit != 0, 'invalid': invalid, 'deleted_said': False}

    def feed(self, tick, player, *, active=True):
        """At most one event: {'kind': 'lap', ...} after the line, or {'kind': 'deleted'} mid-lap."""
        if not active or player is None or player.laps < 0:
            self.laps = self.flags = self.pending = self.previous = None
            self.crossings.clear()
            return None
        crossing = self._crossing(tick, player)
        if crossing is not None:
            self.crossings.append(crossing)
        invalid_now = tick.local.get('local_lap_invalid') is True
        event = None
        if self.laps is None:
            self.laps, self.last_seen = player.laps, player.last_lap
            self.flags = self._flags(player, invalid_now)
            self.flags['pit'] = True          # joined mid-lap: not a full timed lap
            return None
        if player.laps == self.laps + 1:
            self.pending = {'lap': player.laps, 'flags': self.flags, 'since': tick.t, 'previous': self.last_seen}
            self.laps = player.laps
            self.flags = self._flags(player, invalid_now)
        elif player.laps != self.laps:
            self.diagnostics['lap_counter_jump'] += 1
            self.laps, self.pending = player.laps, None
            self.flags = self._flags(player, invalid_now)
            self.flags['pit'] = True
        else:
            flags = self.flags
            flags['pit'] = flags['pit'] or player.pit != 0
            if invalid_now and not flags['invalid'] and not flags['pit']:
                flags['deleted_said'] = True
                event = {'kind': 'deleted', 'lap': player.laps + 1, 'distance': player.distance}
            flags['invalid'] = flags['invalid'] or invalid_now
        if self.pending is not None:
            lap_event = self._resolve(tick, player)
            if lap_event is not None:
                return lap_event
        if player.last_lap is not None and self.pending is None:
            self.last_seen = player.last_lap
        return event

    def _measured(self):
        """Line-to-line time of the lap just finished, when both crossings were seen."""
        pending = self.pending
        if len(self.crossings) >= 2 and abs(self.crossings[-1] - pending['since']) <= 2:
            return self.crossings[-1] - self.crossings[-2]
        return None

    def _resolve(self, tick, player):
        pending = self.pending
        game = player.last_lap
        measured = self._measured()
        time = None
        if game is not None and game != pending['previous']:
            time = game
        elif (game is not None and measured is not None and abs(game - measured) <= SAME_LAP_S
              and tick.t - pending['since'] >= SAME_WAIT_S):
            # Unchanged well after the line and the line-to-line time agrees: two identical laps.
            # (Straight after the line it is still the previous lap's time, however close.)
            time = game
        elif tick.t - pending['since'] > LAP_ACCEPT_S:
            self.pending = None
            self.diagnostics['lap_time_not_reported'] += 1
            return None
        if time is None:
            return None
        self.pending = None
        self.last_seen = game
        flags = pending['flags']
        if flags['pit']:
            self.diagnostics['out_or_in_lap'] += 1
            return None
        valid = not flags['invalid']    # the game's own flag for the driver's lap, seen during the lap
        best = self.best
        event = {'kind': 'lap', 'lap': pending['lap'], 'time': time, 'valid': valid, 'best_before': best,
                 'deleted_said': flags['deleted_said'], 'measured': measured}
        if valid and (best is None or time < best):
            self.best = time
        return event


class TempWatch:
    """W-02 cold tyres/brakes leaving the pits, W-05 tyres up to temperature, M-02 hot or cooled
    tyres, M-10 hot iron brakes."""

    def __init__(self, window_for=None):
        self.window_for = window_for or (lambda car: dict(TYRE_WINDOW))
        self.diagnostics = Counter()
        self.clear()

    def clear(self):
        self.ema = None
        self.last_t = None
        self.in_pits = True
        self.stint = None
        self.axle = {a: {'hot_since': None, 'hot_said_t': None, 'hot_said_c': None, 'cool_since': None,
                         'warm': False, 'cool_said': False} for a in AXLES}
        self.brake_laps = {a: [] for a in AXLES}
        self.lap = None
        self.lap_peak = {a: None for a in AXLES}

    @staticmethod
    def _values(tick, key):
        values = tick.local.get(key)
        if not isinstance(values, (tuple, list)) or len(values) != 4:
            return None
        values = [finite(v) for v in values]
        return values if all(v is not None and -50 < v < 2000 for v in values) else None

    def feed(self, tick, player, *, active=True):
        if not active or player is None:
            self.ema = self.last_t = None
            return []
        events = []
        tyres, brakes = self._values(tick, 'tyre_c'), self._values(tick, 'brake_c')
        window = {**TYRE_WINDOW, **(self.window_for(player.car) or {})}
        lo, hi = float(window['temp_lo']), float(window['temp_hi'])
        dt = tick.t - self.last_t if self.last_t is not None else None
        self.last_t = tick.t
        if tyres is not None:
            if self.ema is None or dt is None or not 0 < dt <= 1:
                self.ema = list(tyres)
            else:
                k = min(1., dt / TYRE_EMA_S)
                self.ema = [e + (v - e) * k for e, v in zip(self.ema, tyres)]
        pit = player.pit
        if pit != 0:
            if not self.in_pits:
                self.stint = None
            self.in_pits = True
            # Leaving: driving out of the pits (3) or out of the garage (5), moving.
            if pit in (3, 5) and self.stint is None and (finite(tick.local.get('speed')) or 0) > 2:
                self.stint = {'start_t': tick.t, 'cold': False, 'ready_since': None, 'ready_said': False}
                cold_tyres = self.ema is not None and max(self.ema) < PIT_COLD_TYRE_C
                cold_brakes = brakes is not None and max(brakes[0], brakes[1]) < PIT_COLD_BRAKE_C
                self.stint['cold'] = cold_tyres
                for a in AXLES:
                    self.axle[a].update(warm=False, cool_since=None, cool_said=False, hot_since=None)
                if cold_tyres or cold_brakes:
                    events.append({'kind': 'pit_exit_cold', 'tyres': cold_tyres, 'brakes': cold_brakes,
                                   'tyre_c': max(self.ema) if self.ema else None,
                                   'brake_c': max(brakes[0], brakes[1]) if brakes else None})
            return events
        if self.in_pits and self.stint is None:
            # Joined the track without a pit-exit sample (started on track): no warm-up call.
            self.stint = {'start_t': tick.t, 'cold': False, 'ready_since': None, 'ready_said': True}
        self.in_pits = False
        speed = finite(tick.local.get('speed')) or 0
        slick = not wet_compound(tick.local.get('compound'))
        if self.ema is not None and speed > 15 and tick.session in ('practice', 'qualify', 'race'):
            stint = self.stint
            if stint['cold'] and not stint['ready_said']:
                if min(self.ema) >= lo:
                    stint['ready_since'] = stint['ready_since'] or tick.t
                    if tick.t - stint['ready_since'] >= READY_HOLD_S:
                        stint['ready_said'] = True
                        events.append({'kind': 'tyres_ready', 'tyre_c': min(self.ema)})
                else:
                    stint['ready_since'] = None
            for name, (i, j) in AXLES.items():
                temp = (self.ema[i] + self.ema[j]) / 2
                state = self.axle[name]
                if temp >= lo:
                    state['warm'], state['cool_since'], state['cool_said'] = True, None, False
                if not slick:
                    continue
                if temp > hi + HOT_MARGIN_C:
                    state['hot_since'] = state['hot_since'] or tick.t
                    repeat = (state['hot_said_t'] is None or tick.t - state['hot_said_t'] >= HOT_REPEAT_S
                              or temp >= (state['hot_said_c'] or 0) + 5)
                    if tick.t - state['hot_since'] >= HOT_HOLD_S and repeat:
                        state['hot_said_t'], state['hot_said_c'] = tick.t, temp
                        events.append({'kind': 'tyres_hot', 'axle': name, 'tyre_c': temp, 'window_hi': hi})
                elif temp < hi:
                    state['hot_since'] = None
                if state['warm'] and temp < lo - COLD_MARGIN_C and not state['cool_said']:
                    state['cool_since'] = state['cool_since'] or tick.t
                    if tick.t - state['cool_since'] >= COLD_HOLD_S:
                        state['cool_said'] = True
                        events.append({'kind': 'tyres_cooled', 'axle': name, 'tyre_c': temp, 'window_lo': lo})
        events += self._brakes(tick, player, brakes)
        return events

    def _brakes(self, tick, player, brakes):
        events = []
        if self.lap is not None and player.laps != self.lap:
            if player.laps == self.lap + 1 and iron_brakes(player.car_class):
                for name in AXLES:
                    peak = self.lap_peak[name]
                    laps = self.brake_laps[name]
                    laps.append(peak)
                    del laps[:-2]
                    if len(laps) == 2 and all(p is not None and p > IRON_BRAKE_HOT_C[name] for p in laps):
                        events.append({'kind': 'brakes_hot', 'axle': name, 'brake_c': max(laps)})
                        laps.clear()
            self.lap_peak = {a: None for a in AXLES}
        self.lap = player.laps
        if brakes is not None:
            for name, (i, j) in AXLES.items():
                value = max(brakes[i], brakes[j])
                self.lap_peak[name] = value if self.lap_peak[name] is None else max(self.lap_peak[name], value)
        return events


class FuelLeftWatch:
    """M-17: low fuel, from the measured burn: about three, two and one laps left."""

    def __init__(self):
        self.clear()

    def clear(self):
        self.laps = None
        self.said = set()

    def feed(self, tick, player, estimate):
        if player is None or player.laps < 0:
            self.laps = None
            return None
        completed = self.laps is not None and player.laps == self.laps + 1
        self.laps = player.laps
        if not completed or estimate is None or player.pit != 0:
            return None
        left = estimate['fuel_litres'] / estimate['litres_per_lap']
        if left > 3.5:
            self.said.clear()        # refuelled
            return None
        whole = max(0, int(left + .25))
        if whole in self.said or whole > 3:
            return None
        self.said.add(whole)
        return {'kind': 'fuel_low', 'laps_left': left, 'whole': whole, 'litres': estimate['fuel_litres'],
                'litres_per_lap': estimate['litres_per_lap']}


RECON_LEAD_S = 4.0        # call a corner this long before reaching its apex ...
RECON_LEAD_M = (90.0, 350.0)   # ... within these distances
RECON_JOIN_M = 130.0      # corners whose apexes are this close are called together


class ReconGuide:
    """V-25 recon lap: on request, each corner is called just before the car reaches it,
    for one full lap. Corners come from the track map (or the setup engineer's corner list);
    with neither, the engineer says so instead of guessing."""

    def __init__(self):
        self.active = False
        self.corners = []
        self.said = set()

    def start(self, corners):
        """corners: [(apex_m, spoken label)]. Returns False when there is nothing to call."""
        self.corners = sorted((float(a), str(label)) for a, label in corners if a is not None)
        self.said = set()
        self.active = bool(self.corners)
        return self.active

    def stop(self):
        self.active = False

    def feed(self, tick, player, *, active=True):
        if not self.active or not active or player is None or player.distance is None or tick.length <= 0:
            return None
        speed = finite(tick.local.get('speed')) or 0
        lead = max(RECON_LEAD_M[0], min(RECON_LEAD_M[1], speed * RECON_LEAD_S))
        for i, (apex, label) in enumerate(self.corners):
            if i in self.said:
                continue
            ahead = (apex - player.distance) % tick.length
            if 0 < ahead <= lead:
                group = [i]
                while (group[-1] + 1 < len(self.corners) and group[-1] + 1 not in self.said
                       and self.corners[group[-1] + 1][0] - self.corners[group[-1]][0] <= RECON_JOIN_M):
                    group.append(group[-1] + 1)
                self.said.update(group)
                if len(self.said) == len(self.corners):
                    self.active = False
                return {'kind': 'recon_corner', 'labels': [self.corners[j][1] for j in group],
                        'apex': apex, 'last': not self.active}
        return None


DAMAGE_STEP = .05         # a jump of this much (0-1 scale) within a few seconds is new damage
DAMAGE_SETTLE_S = 2.5     # report once the numbers stop changing after the hit
WATER_HOT_C, OIL_HOT_C = 108.0, 130.0
ENGINE_HOT_HOLD_S = 10.0
ENGINE_REPEAT_S = 180.0
WHEEL_NAMES = {0: 'front left', 1: 'front right', 2: 'rear left', 3: 'rear right'}


def severity(value):
    return 'minor' if value < .15 else 'significant' if value < .4 else 'heavy'


class HealthWatch:
    """M-23 damage reports after a hit (aero, suspension per wheel, brakes per wheel, engine) and
    M-13 engine temperatures well above normal. From the game's own damage and temperature values."""

    def __init__(self):
        self.clear()

    def clear(self):
        self.baseline = None
        self.hit = None             # {'t', 'last_change'} while damage is still settling
        self.hot = {'water': None, 'oil': None}
        self.hot_said = {'water': (None, None), 'oil': (None, None)}

    @staticmethod
    def _damage(tick):
        d = tick.local.get('damage')
        if not isinstance(d, dict):
            return None
        try:
            return {'aero': float(d['aero']), 'engine': float(d['engine']),
                    'suspension': [float(v) for v in d['suspension']], 'brakes': [float(v) for v in d['brakes']]}
        except (KeyError, TypeError, ValueError):
            return None

    def feed(self, tick, player, *, active=True):
        if not active or player is None:
            return []
        events = []
        damage = self._damage(tick)
        if damage is not None:
            if self.baseline is None or player.pit in (2, 4):
                self.baseline, self.hit = damage, None          # repaired or first look
            else:
                changes = self._changes(self.baseline, damage)
                if changes:
                    if self.hit is None:
                        self.hit = {'t': tick.t, 'last': damage, 'since': tick.t}
                    elif damage != self.hit['last']:
                        self.hit.update(last=damage, since=tick.t)
                    elif tick.t - self.hit['since'] >= DAMAGE_SETTLE_S:
                        events.append({'kind': 'damage', 'changes': changes})
                        self.baseline, self.hit = damage, None
        speed = finite(tick.local.get('speed')) or 0
        for name, limit in (('water', WATER_HOT_C), ('oil', OIL_HOT_C)):
            value = finite(tick.local.get(name + '_c'))
            if value is None or player.pit != 0 or speed < 10:
                self.hot[name] = None
                continue
            if value >= limit:
                self.hot[name] = self.hot[name] or tick.t
                said_t, said_c = self.hot_said[name]
                if tick.t - self.hot[name] >= ENGINE_HOT_HOLD_S and (
                        said_t is None or tick.t - said_t >= ENGINE_REPEAT_S or value >= said_c + 3):
                    self.hot_said[name] = (tick.t, value)
                    events.append({'kind': 'engine_hot', 'what': name, 'temp_c': value})
            else:
                self.hot[name] = None
        return events

    @staticmethod
    def _changes(before, after):
        out = []
        if after['aero'] - before['aero'] >= DAMAGE_STEP:
            out.append({'part': 'aero', 'level': severity(after['aero']), 'value': after['aero']})
        if after['engine'] - before['engine'] >= DAMAGE_STEP:
            out.append({'part': 'engine', 'level': severity(after['engine']), 'value': after['engine']})
        for key, part in (('suspension', 'suspension'), ('brakes', 'brake')):
            for i, (a, b) in enumerate(zip(before[key], after[key])):
                if b - a >= DAMAGE_STEP:
                    out.append({'part': part, 'wheel': WHEEL_NAMES[i], 'level': severity(b), 'value': b})
        return out
