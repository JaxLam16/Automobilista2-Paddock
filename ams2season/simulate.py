"""Synthetic multiplayer races that produce genuine `SharedMemory` structs.

Drives the real Recorder, so everything downstream (derive, ingest, standings) is tested
against the same file format the live game produces. Deliberately reproduces awkward
real-world behaviour:
  * mixed grid: front rows ahead of the S/F line, back rows behind it
  * mLapsCompleted ticking over a couple of frames after lap distance wraps
  * last-lap time updating a few frames after the line
  * per-tick speed jitter, so side-by-side cars flicker in order
  * scripted spin (gifted passes), pit stop (pit-cycle swaps), retirement,
    and a mid-race disconnect that shifts every later participant slot down by one
  * a fresh random AI field every race, like AMS2 multiplayer
"""
from __future__ import annotations

import json
import math
import re
import zlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import shm as S
from .recorder import Recorder

DT = 0.05
TRACK = {
    "location": "Simtown", "variation": "GP", "length": 3000.0,
    # (apex lap distance m, apex speed m/s)
    "corners": [(280, 24.0), (820, 36.0), (1300, 27.0), (1900, 40.0), (2350, 22.0), (2750, 34.0)],
    "vmax": 64.0, "width": 110.0,
    "asphalt_half": 5.0, "kerb": 1.0,  # road edges for the simulated circuit (metres from the centre line)
}
AI_FIRST = ["Lucas", "Mateo", "Hugo", "Felipe", "Kenji", "Arvid", "Nico", "Rafael", "Oskar",
            "Tomas", "Dario", "Emil", "Bruno", "Joao", "Ivan", "Pierre", "Marco", "Sven"]
AI_LAST = ["Ferraz", "Lindqvist", "Okafor", "Brandt", "Mori", "Castell", "Duval", "Petrov",
           "Romano", "Haas", "Silva", "Novak", "Keller", "Moreau", "Tanaka", "Ruiz", "Berg"]
CARS = ["Porsche 911 GT3 R", "Mercedes-AMG GT3 Evo", "McLaren 720S GT3 Evo",
        "BMW M4 GT3", "Audi R8 LMS GT3 Evo II", "Lamborghini Huracan GT3 Evo2"]


TRACK["corner_dirs"] = [1, 1, -1, 1, 1, 1]  # T3 is a right-hander


def _build_centreline(step: float = 1.0):
    """Centre line of the simulated circuit. Each corner's curvature comes from its apex speed at about
    1.4 g (radius = v^2 / a), shaped as a smooth bump; the left-handers are scaled so the lap turns
    exactly 360 degrees, and the small closing error is spread round the lap."""
    import numpy as np
    L = TRACK["length"]
    s = np.arange(0.0, L, step)
    kappa = np.zeros_like(s)
    for (apex, vmin), d in zip(TRACK["corners"], TRACK["corner_dirs"]):
        dist = np.abs(s - apex)
        dist = np.minimum(dist, L - dist)
        sigma = 30 + 1.2 * vmin
        kappa += d * (13.5 / vmin ** 2) * np.exp(-0.5 * (dist / sigma) ** 2)
    pos, neg = kappa[kappa > 0].sum() * step, kappa[kappa < 0].sum() * step
    kappa = np.where(kappa > 0, kappa * (2 * np.pi - neg) / pos, kappa)
    heading = np.cumsum(kappa) * step
    x, z = np.cumsum(np.cos(heading)) * step, np.cumsum(np.sin(heading)) * step
    x -= (x[-1] - x[0] + step * np.cos(heading[0])) * s / L
    z -= (z[-1] - z[0] + step * np.sin(heading[0])) * s / L
    heading = np.unwrap(np.arctan2(np.gradient(z), np.gradient(x)))
    return s, x, z, heading, kappa


_CL = None


def centreline(lapd: float):
    """(x, z, heading, curvature) of the circuit centre line at a lap distance."""
    global _CL
    if _CL is None:
        _CL = _build_centreline()
    s, x, z, h, k = _CL
    L = TRACK["length"]
    i = int(lapd % L) % len(s)
    j = (i + 1) % len(s)
    u = (lapd % L) - s[i]
    dh = ((h[j] - h[i] + math.pi) % (2 * math.pi)) - math.pi
    return x[i] + (x[j] - x[i]) * u, z[i] + (z[j] - z[i]) * u, h[i] + dh * u, k[i]


def world_position(lapd: float, offset: float):
    """World x, z of a point `offset` metres to the left of the centre line."""
    x, z, h, _ = centreline(lapd)
    return x - math.sin(h) * offset, z + math.cos(h) * offset


def v_ref(lap_dist: float) -> float:
    L, vmax, w = TRACK["length"], TRACK["vmax"], TRACK["width"]
    v = vmax
    for apex, vmin in TRACK["corners"]:
        d = abs(lap_dist - apex)
        d = min(d, L - d)
        v = min(v, vmax - (vmax - vmin) * math.exp(-(d / w) ** 2))
    return v


def in_overtake_zone(lap_dist: float) -> bool:
    return any(apex - 170 <= lap_dist <= apex - 10 for apex, _ in TRACK["corners"])


@dataclass
class Car:
    name: str
    car: str
    is_ai: bool
    pace: float
    s: float
    state: int = S.RACESTATE_NOT_STARTED
    pit_mode: int = 0
    v: float = 0.0
    laps_reported: int = 0
    lc_pending: int = 0
    lc_delay: int = 0
    lap_start_t: float = 0.0
    lap_noise: float = 0.0
    s1: float = -1.0
    s2: float = -1.0
    s3: float = -1.0
    last_lap: float = -1.0
    last_lap_pending: float = -1.0
    last_lap_delay: int = 0
    fastest: float = -1.0
    lap_invalid: bool = False
    finish_t: float | None = None
    finish_laps: int = 0
    spin_until: float = -1.0
    pit_until: float = 0.0
    pit_done: bool = False
    gone: bool = False


@dataclass
class RaceScript:
    laps: int = 5
    n_ai: int = 12
    ai_strength: float = 1.0          # multiplies AI pace around 1.0
    spin: tuple | None = None          # (car_name_or_index, lap, lap_dist)
    pit: tuple | None = None           # (car_name_or_index, lap)
    retire: tuple | None = None        # (car_name_or_index, lap, lap_dist)
    disconnect: tuple | None = None    # (car_name_or_index, lap, lap_dist)
    local_collision_lap: int | None = 2
    with_qualifying: bool = False
    ghost_duplicate: bool = False      # a stale second copy of one AI driver (seen in real multiplayer data)
    mass_invalid_at_start: bool = False  # the game invalidates every car's first lap a few seconds in
    glitch_rate: float = 0.0           # chance per car per tick that lap distance flickers to 0 for a frame
    report_track_length: float | None = None  # pretend the game reports a wrong track length
    count_grid_lap: bool = False       # game counts the grid-to-line run as a completed lap
    extra: dict = field(default_factory=dict)


class RaceSim:
    def __init__(self, humans: list[str], script: RaceScript, seed: int = 0,
                 local_human: str | None = None):
        self.rng = random.Random(seed)
        self.script = script
        self.L = TRACK["length"]
        self.t = 0.0
        self.humans = humans
        self.local_name = local_human or humans[0]
        self.events: list[dict] = []
        ai_names = set()
        while len(ai_names) < script.n_ai:
            ai_names.add(f"{self.rng.choice(AI_FIRST)} {self.rng.choice(AI_LAST)}")
        entries = [(h, False) for h in humans] + [(n, True) for n in sorted(ai_names)]
        self.rng.shuffle(entries)  # random grid order
        self.cars: list[Car] = []
        for gpos, (name, ai) in enumerate(entries):
            pace = self.rng.uniform(0.975, 1.012) * (script.ai_strength if ai else 1.0)
            if not ai:
                pace = self.rng.uniform(0.982, 1.015)
            # mixed grid: P1 30 m past the line, 8 m per slot
            self.cars.append(Car(name=name, car=self.rng.choice(CARS), is_ai=ai, pace=pace,
                                 s=30.0 - 8.0 * gpos))
        self.grid = [c.name for c in self.cars]
        self.slots: list[Car] = list(self.cars)
        self.green_t = None
        self.chequered_t = None
        self.done_t = None
        self.collision = (-1, 0.0)
        self.local_damage = 0.0
        self.mapping_side = None

    # -------------------------------------------------------------- helpers
    def _resolve(self, ref):
        if ref is None:
            return None
        if isinstance(ref, int):
            return self.cars[ref % len(self.cars)]
        return next(c for c in self.cars if c.name == ref)

    def _order(self) -> list[Car]:
        active = [c for c in self.cars if not c.gone]
        fin = sorted([c for c in active if c.finish_t is not None], key=lambda c: (-c.finish_laps, c.finish_t))
        run = sorted([c for c in active if c.finish_t is None and c.state != S.RACESTATE_RETIRED], key=lambda c: -c.s)
        ret = sorted([c for c in active if c.state == S.RACESTATE_RETIRED and c.finish_t is None], key=lambda c: -c.s)
        return fin + run + ret

    # -------------------------------------------------------------- physics
    def advance(self, t_green: float):
        self.t += DT
        t = self.t
        if self.script.mass_invalid_at_start and self.green_t is not None and abs(t - (self.green_t + 4.0)) < DT / 2:
            for c in self.cars:  # every car's first lap marked invalid at the same moment
                c.lap_invalid = True
        if self.green_t is None and t >= t_green:
            self.green_t = t
            for c in self.cars:
                c.state = S.RACESTATE_RACING
                c.lap_start_t = t
        if self.green_t is None:
            return
        sc = self.script
        spin_car, pit_car = self._resolve(sc.spin and sc.spin[0]), self._resolve(sc.pit and sc.pit[0])
        ret_car, dc_car = self._resolve(sc.retire and sc.retire[0]), self._resolve(sc.disconnect and sc.disconnect[0])

        movers = sorted([c for c in self.cars if not c.gone and c.state != S.RACESTATE_RETIRED], key=lambda c: -c.s)
        for i, c in enumerate(movers):
            lap_idx = math.floor(c.s / self.L)
            lapd = c.s - lap_idx * self.L
            v = v_ref(lapd) * c.pace * (1 + c.lap_noise) * (1 + self.rng.gauss(0, 0.003))
            if c.finish_t is not None:
                v *= 0.45
            # following / overtaking: stuck behind unless in a braking zone with a pace edge
            if c.finish_t is None and i > 0:
                ahead = movers[i - 1]
                gap = ahead.s - c.s
                ahead_blocking = ahead.finish_t is None and ahead.pit_mode == 0 and not (
                    ahead.spin_until > 0 and t < ahead.spin_until + 1.0)
                if 0 < gap < 12 and ahead_blocking and v > ahead.v:
                    if not (in_overtake_zone(lapd) and c.pace > ahead.pace * 1.002):
                        v = ahead.v * (0.995 + 0.01 * self.rng.random())
            # scripted spin
            if spin_car is c and c.spin_until < 0 and lap_idx + 1 == sc.spin[1] and lapd >= sc.spin[2]:
                c.spin_until = t + 4.0
                c.lap_invalid = True
                self.events.append({"t": t, "type": "spin", "name": c.name, "lap": sc.spin[1]})
            if c.spin_until > 0 and t < c.spin_until:
                v = 2.0
            # scripted pit stop
            if pit_car is c and not c.pit_done:
                pit_line = sc.pit[1] * self.L
                if c.pit_mode == 0 and pit_line - 300 <= c.s < pit_line - 80:
                    c.pit_mode = S.PIT_MODE_DRIVING_INTO_PITS
                if c.pit_mode == S.PIT_MODE_DRIVING_INTO_PITS:
                    v = min(v, 22.0)
                    if c.s >= pit_line - 80:
                        c.pit_mode, c.pit_until = S.PIT_MODE_IN_PIT, t + 18.0
                        self.events.append({"t": t, "type": "pit", "name": c.name, "lap": sc.pit[1]})
                if c.pit_mode == S.PIT_MODE_IN_PIT:
                    v = 0.0
                    if t >= c.pit_until:
                        c.pit_mode = S.PIT_MODE_DRIVING_OUT_OF_PITS
                if c.pit_mode == S.PIT_MODE_DRIVING_OUT_OF_PITS:
                    v = min(v, 22.0)
                    if c.s >= pit_line + 250:
                        c.pit_mode, c.pit_done = 0, True
            # scripted retirement
            if ret_car is c and lap_idx + 1 == sc.retire[1] and lapd >= sc.retire[2]:
                c.state, v = S.RACESTATE_RETIRED, 0.0
                self.events.append({"t": t, "type": "retire", "name": c.name, "lap": sc.retire[1]})
            # scripted disconnect: slot removed, later slots shift down
            if dc_car is c and not c.gone and lap_idx + 1 == sc.disconnect[1] and lapd >= sc.disconnect[2]:
                c.gone = True
                self.slots.remove(c)
                self.events.append({"t": t, "type": "disconnect", "name": c.name, "lap": sc.disconnect[1]})
                continue
            c.prev_v = c.v
            c.v = max(0.0, v)
            self._move(c, t)

        # local collision with the nearest car once, mid-race
        local = next((c for c in self.cars if c.name == self.local_name and not c.gone), None)
        if local and sc.local_collision_lap and self.collision[0] < 0:
            if math.floor(local.s / self.L) + 1 == sc.local_collision_lap:
                near = min((c for c in self.cars if c is not local and not c.gone),
                           key=lambda c: abs(c.s - local.s))
                if abs(near.s - local.s) < 40:
                    self.collision = (self.slots.index(near), 2.4)
                    self.local_damage = 0.12
                    self.events.append({"t": t, "type": "local_collision", "other": near.name})

        # chequered flag / end of session
        running = [c for c in self.cars if not c.gone and c.state == S.RACESTATE_RACING]
        if self.done_t is None and (not running or (self.chequered_t and t > self.chequered_t + 120)):
            self.done_t = t

    def _move(self, c: Car, t: float):
        old_s = c.s
        c.s += c.v * DT
        L = self.L
        old_lap, new_lap = math.floor(old_s / L), math.floor(c.s / L)
        old_d, new_d = old_s - old_lap * L, c.s - new_lap * L
        if new_lap == old_lap and c.s >= 0:
            if old_d < L / 3 <= new_d:
                c.s1 = t - c.lap_start_t
            if old_d < 2 * L / 3 <= new_d:
                c.s2 = t - c.lap_start_t - c.s1
        if self.script.count_grid_lap and old_lap == -1 and new_lap == 0:
            c.lc_pending, c.lc_delay = 1, 2  # game counts the grid run as lap 1 completed
            c.grid_lap_bonus = 1
        if new_lap > old_lap and new_lap >= 1:  # completed lap number new_lap
            lap_time = t - c.lap_start_t
            c.s3 = lap_time - max(c.s1, 0) - max(c.s2, 0)
            c.last_lap_pending, c.last_lap_delay = lap_time, 3
            if not c.lap_invalid and (c.fastest < 0 or lap_time < c.fastest):
                c.fastest = lap_time
            c.lap_start_t = t
            c.s1 = c.s2 = -1.0
            c.lap_invalid = False
            c.lap_noise = self.rng.gauss(0, 0.004)
            c.lc_pending, c.lc_delay = new_lap + getattr(c, "grid_lap_bonus", 0), 2
            if c.finish_t is None and c.state == S.RACESTATE_RACING:
                if self.chequered_t is None and new_lap >= self.script.laps:
                    self.chequered_t = t
                if self.chequered_t is not None:
                    c.finish_t, c.finish_laps = t, new_lap
                    c.state = S.RACESTATE_FINISHED
        if c.lc_delay > 0:
            c.lc_delay -= 1
            if c.lc_delay == 0:
                c.laps_reported = c.lc_pending
        if c.last_lap_delay > 0:
            c.last_lap_delay -= 1
            if c.last_lap_delay == 0:
                c.last_lap = c.last_lap_pending
                c.s3 = -1.0

    # -------------------------------------------------------------- snapshot
    def _line_offset(self, c, lapd: float) -> float:
        """Lateral position of the car's centre, metres left of the centre line. Out-in-out lines that
        use the road: wide on entry, kerb at the apex, wide on exit; the best drivers use all of it.
        A mapping lap hugs one edge with a small weave so the wheels keep crossing the white line."""
        edge = TRACK["asphalt_half"]
        if self.mapping_side and c.name == self.local_name:
            wobble = 0.35 * math.sin(2 * math.pi * lapd / 37.0)
            return (edge - 0.85 if self.mapping_side == "left" else -(edge - 0.85)) + wobble
        if not hasattr(c, "line_seed"):
            r = random.Random(zlib.crc32(c.name.encode()))
            # how much of the road this driver uses, a phase for small weaves, and their turn-in habits
            c.line_seed = (r.uniform(0.55, 1.0), r.uniform(0, 2 * math.pi), [r.uniform(-15, 15) for _ in TRACK["corners"]])
            pts = []
            for (apex, vmin), d, jit in zip(TRACK["corners"], TRACK["corner_dirs"], c.line_seed[2]):
                sigma = 30 + 1.2 * vmin  # the corner's length scale (same as the centre line)
                pts += [((apex - 1.6 * sigma + jit) % self.L, -d * 4.2),  # turn-in: out at the edge
                        (apex % self.L, d * 4.6),                           # apex: inside, wheels on the kerb
                        ((apex + 1.8 * sigma + jit) % self.L, -d * 4.2)]    # track-out: back out to the edge
            c.line_pts = sorted(pts)
        amp, phase, _ = c.line_seed
        pts, L = c.line_pts, self.L
        u = lapd % L
        k = next((i for i, p in enumerate(pts) if p[0] > u), len(pts))
        (sa, va), (sb, vb) = pts[k - 1], pts[k % len(pts)]
        span = (sb - sa) % L or L
        f = ((u - sa) % L) / span
        o = va + (vb - va) * (1 - math.cos(math.pi * f)) / 2
        return o * amp + 0.25 * math.sin(2 * math.pi * lapd / L * 3 + phase)

    # ------------------------------------------------------------------ the recording car's feet and tyres
    def _corner_plan(self, c, lap: int, k: int):
        """This lap's way of taking corner k: braking point, pressure, trail and throttle pickup, varied
        lap to lap by the driver's consistency (metres of scatter)."""
        key = (lap, k)
        plans = c.__dict__.setdefault("plans", {})
        if key not in plans:
            r = random.Random(zlib.crc32(f"{c.name}:{lap}:{k}:{self.script.extra.get('seed', 0)}".encode()))
            sd = self.script.extra.get("consistency", {}).get(c.name, 4.0) * (1.6 if k == 1 else 1.0)  # T2 is the tricky one
            apex, vmin = TRACK["corners"][k]
            v_in = v_ref((apex - 320) % self.L)
            brake_len = max(40.0, (v_in ** 2 - vmin ** 2) / (2 * 14.0))
            plans[key] = {"onset": apex - brake_len + r.gauss(0, sd), "peak": min(1.0, max(0.5, r.gauss(0.88, 0.03 + sd * 0.008))),
                          "attack": max(6.0, r.gauss(14, 2 + sd * 0.4)), "release": apex - 8 + r.gauss(0, sd * 0.8),
                          "pickup": apex + 12 + r.gauss(0, sd * 1.2), "ramp": max(40.0, r.gauss(90, 10 + sd * 2)),
                          "lockup": r.random() < self.script.extra.get("lockup_rate", {}).get(c.name, 0.05),
                          "spin": r.random() < self.script.extra.get("spin_rate", {}).get(c.name, 0.05)}
        return plans[key]

    def _pedals(self, c, lapd: float):
        lap = math.floor(c.s / self.L)
        brake, throttle = 0.0, 1.0
        for k, (apex, _) in enumerate(TRACK["corners"]):
            p = self._corner_plan(c, lap, k)
            if p["onset"] <= lapd <= p["release"]:
                u = lapd - p["onset"]
                peak_at = p["onset"] + p["attack"]
                if lapd <= peak_at:
                    brake = p["peak"] * u / p["attack"]
                else:  # trail off towards the apex
                    brake = p["peak"] * max(0.0, (p["release"] - lapd) / max(1.0, p["release"] - peak_at)) ** 1.4
                throttle = 0.0
            elif p["release"] < lapd < p["pickup"]:
                throttle = 0.0 if lapd < apex else 0.15
            elif p["pickup"] <= lapd < p["pickup"] + p["ramp"]:
                throttle = min(throttle, 0.2 + 0.8 * (lapd - p["pickup"]) / p["ramp"])
        return max(0.0, min(1.0, brake)), max(0.0, min(1.0, throttle))

    def _tyres(self, m, c, lapd: float):
        """A small thermal model, enough to exercise the tyre analysis: heat from cornering load, braking,
        traction and slip; spread across the tread by camber and pressure; surface zones that react in
        seconds, a tread, carcass and internal air that lag behind, and pressure following the air (ideal
        gas). Tyres come out of the pits cold."""
        lap = math.floor(c.s / self.L)
        load = 1 - v_ref(lapd) / TRACK["vmax"]  # how hard the car is working (corners)
        care = self.script.extra.get("tyre_wear", {}).get(c.name, 1.0)  # >1 = harder on tyres
        setup = self.script.extra.get("tyre_setup", {}).get(c.name, {})
        amb = 31.0
        if not hasattr(c, "wear"):
            c.wear, c.btemp = [0.0] * 4, [250.0] * 4
            t0 = self.script.extra.get("tyre_start_temp", 62.0)
            c.tz = [[t0] * 3 for _ in range(4)]
            c.tread, c.carc, c.air, c.rim = [t0] * 4, [t0 - 4] * 4, [t0 - 8] * 4, [t0 - 10] * 4
            c.p_cold = [21.5 + setup.get("press", 0.0)] * 4   # psi; reported in kPa like the real game
            c.t_cold = 25.0
        if c.pit_mode == S.PIT_MODE_IN_PIT:  # fresh, cold tyres
            c.tz = [[45.0] * 3 for _ in range(4)]
            c.tread, c.carc, c.air, c.rim = [45.0] * 4, [42.0] * 4, [38.0] * 4, [40.0] * 4
            c.wear = [0.0] * 4
        brake, thr = m.mBrake, m.mThrottle
        kap = centreline(lapd)[3]
        turn = 1 if kap > 1e-4 else -1 if kap < -1e-4 else 0
        for w in range(4):
            front, right_side = w < 2, w % 2 == 1
            outside = (turn > 0 and right_side) or (turn < 0 and not right_side)
            lw = load * (1.0 + (0.3 if outside else -0.2 if turn else 0.0))
            rate = (0.6 + 1.6 * load + (1.2 * brake if front else 1.0 * thr * load)) * care * 0.000005
            c.wear[w] = min(1.0, c.wear[w] + rate * c.v * DT)
            c.btemp[w] += (brake * (520 if front else 380) - (c.btemp[w] - 150) * 0.11) * DT
            radius = 0.335 if front else 0.345
            slip = 0.0
            k = min(range(len(TRACK["corners"])), key=lambda i: abs(TRACK["corners"][i][0] - lapd))
            p = self._corner_plan(c, lap, k)
            if front and p["lockup"] and brake > 0.6:
                slip = -0.35  # locked front under heavy braking
            if not front and p["spin"] and p["pickup"] <= lapd < p["pickup"] + 35:
                slip = 0.25   # rear wheelspin on the exit
            q = (2.0 * lw + 2.4 * brake * (1.0 if front else 0.25) + (0.7 * thr * load if not front else 0.0) + 8.0 * abs(slip)) * care * (c.v / 50.0)
            cam = -1.0 + setup.get("camber", 0.0)  # more negative = more camber = hotter inside
            dp = (c.p_cold[w] - 21.5)              # over-inflated = hotter centre
            inner = 0.34 - 0.025 * cam - 0.015 * dp
            outer = 0.30 + 0.025 * cam - 0.015 * dp + (0.04 if outside else 0.0)
            shares = (inner, 1.0 - inner - outer, outer)
            for z in range(3):
                Tz = c.tz[w][z]
                c.tz[w][z] = Tz + (q * shares[z] * 62.0 - (Tz - c.tread[w]) * 0.45 - (Tz - amb) * 0.0045 * c.v) * DT
            surf = sum(c.tz[w]) / 3
            c.tread[w] += ((surf - c.tread[w]) * 0.10 - (c.tread[w] - c.carc[w]) * 0.02) * DT
            c.carc[w] += (c.tread[w] - c.carc[w]) * 0.025 * DT
            c.air[w] += (c.carc[w] - c.air[w]) * 0.02 * DT
            c.rim[w] += ((0.12 * c.btemp[w] + 0.88 * c.air[w]) - c.rim[w]) * 0.012 * DT
            m.mTyreWear[w] = c.wear[w]
            inner_t, mid_t, outer_t = c.tz[w]
            # the game reports the tyre's own left / centre / right; inside is the right side on left wheels
            left_t, right_t = (outer_t, inner_t) if not right_side else (inner_t, outer_t)
            m.mTyreTempLeft[w], m.mTyreTempCenter[w], m.mTyreTempRight[w] = left_t, mid_t, right_t
            m.mTyreTemp[w] = surf
            m.mTyreTreadTemp[w] = c.tread[w] + 273.15
            m.mTyreLayerTemp[w] = (c.tread[w] + c.carc[w]) / 2 + 273.15
            m.mTyreCarcassTemp[w] = c.carc[w] + 273.15
            m.mTyreRimTemp[w] = c.rim[w] + 273.15
            m.mTyreInternalAirTemp[w] = c.air[w] + 273.15
            m.mAirPressure[w] = c.p_cold[w] * 6.89476 * (c.air[w] + 273.15) / (c.t_cold + 273.15)
            m.mBrakeTempCelsius[w] = c.btemp[w]
            m.mRideHeight[w] = 5.5 - 2.2 * load - (1.6 * brake if front else 0.6 * thr * load)
            m.mSuspensionTravel[w] = 0.035 + 0.03 * lw
            m.mTyreRPS[w] = c.v * (1 + slip) / (2 * math.pi * radius)
        for w in range(4):
            m.mTyreCompound[w].value = b"Soft"

    def _terrain(self, lateral: float) -> int:
        d = abs(lateral)
        if d <= TRACK["asphalt_half"]:
            return 0   # TERRAIN_ROAD
        if d <= TRACK["asphalt_half"] + TRACK["kerb"]:
            return 10  # TERRAIN_RUMBLE_STRIPS
        return 7       # TERRAIN_GRASS

    def snapshot(self, game_state: int, session_state: int) -> S.SharedMemory:
        m = S.SharedMemory()
        m.mVersion = S.SHARED_MEMORY_VERSION
        m.mBuildVersionNumber = 1
        m.mGameState = game_state
        m.mSessionState = session_state
        m.mSequenceNumber = int(self.t / DT) * 2
        m.mTrackLocation = TRACK["location"].encode()
        m.mTrackVariation = TRACK["variation"].encode()
        m.mTranslatedTrackLocation = TRACK["location"].encode()
        m.mTranslatedTrackVariation = TRACK["variation"].encode()
        m.mTrackLength = self.script.report_track_length or self.L
        m.mNumSectors = 3
        m.mLapsInEvent = self.script.laps
        if game_state == S.GAME_FRONT_END:
            return m
        order = self._order()
        pos = {id(c): i + 1 for i, c in enumerate(order)}
        m.mNumParticipants = len(self.slots)
        local_slot = -1
        for i, c in enumerate(self.slots):
            p = m.mParticipantInfo[i]
            p.mIsActive = True
            p.mName = c.name.encode()
            lap_idx = math.floor(c.s / self.L)
            lapd = c.s - lap_idx * self.L
            p.mWorldPosition[0], p.mWorldPosition[2] = world_position(lapd, self._line_offset(c, lapd))
            p.mCurrentLapDistance = 0.0 if (self.script.glitch_rate and self.rng.random() < self.script.glitch_rate) else lapd
            heading = centreline(lapd)[2]  # direction of travel, world x-z plane
            m.mOrientations[i][1] = -heading  # game-style yaw: different sign/offset; the replay calibrates it
            p.mRacePosition = pos[id(c)]
            p.mLapsCompleted = c.laps_reported
            p.mCurrentLap = c.laps_reported + 1
            p.mCurrentSector = min(2, int(lapd / (self.L / 3)))
            m.mSpeeds[i] = c.v
            m.mRaceStates[i] = c.state
            m.mPitModes[i] = c.pit_mode
            m.mLapsInvalidated[i] = c.lap_invalid
            m.mLastLapTimes[i] = c.last_lap
            m.mFastestLapTimes[i] = c.fastest
            m.mCurrentSector1Times[i] = c.s1
            m.mCurrentSector2Times[i] = c.s2
            m.mCurrentSector3Times[i] = c.s3
            m.mCarNames[i].value = c.car.encode()
            m.mCarClassNames[i].value = b"GT3"
            if c.name == self.local_name:
                local_slot = i
        if self.script.ghost_duplicate and self.green_t is not None:
            src = next(c for c in self.cars if c.is_ai)
            gi = len(self.slots)
            gp = m.mParticipantInfo[gi]
            gp.mIsActive = True
            gp.mName = src.name.encode()
            gp.mWorldPosition[0], gp.mWorldPosition[2] = world_position(10.0, 25.0)
            gp.mCurrentLapDistance = (self.t * 977.0) % self.L  # nonsense lap distance
            gp.mRacePosition = len(self.slots) + 1
            m.mRaceStates[gi] = S.RACESTATE_RACING
            m.mCarNames[gi].value = src.car.encode()
            m.mCarClassNames[gi].value = b"GT3"
            m.mNumParticipants = gi + 1
        m.mViewedParticipantIndex = local_slot
        m.mRaceState = self.slots[local_slot].state if local_slot >= 0 else 0
        if local_slot >= 0:
            lc = self.slots[local_slot]
            m.mSpeed = lc.v
            lapd_l = lc.s - math.floor(lc.s / self.L) * self.L
            m.mBrake, m.mThrottle = self._pedals(lc, lapd_l)
            m.mGear = max(1, min(6, 1 + int(lc.v / 11)))
            self._tyres(m, lc, lapd_l)
            k_here = centreline(lapd_l)[3]  # steering left (negative) in left-handers, right in right-handers
            m.mSteering = max(-1.0, min(1.0, -k_here * 45.0 + 0.01 * math.sin(self.t * 7.3)))
            o_car = self._line_offset(lc, lapd_l)
            for wi, side in enumerate((1, -1, 1, -1)):  # FL, FR, RL, RR (left wheels are to the left)
                m.mTerrain[wi] = self._terrain(o_car + side * 0.85)
            m.mCarName = lc.car.encode()
            m.mCarClassName = b"GT3"
            m.mLapInvalidated = lc.lap_invalid
            m.mCrashState = S.CRASH_DAMAGE_SPINNING if (lc.spin_until > 0 and self.t < lc.spin_until) else 0
            m.mAeroDamage = self.local_damage
            m.mFuelLevel = 0.8
        m.mLastOpponentCollisionIndex = self.collision[0]
        m.mLastOpponentCollisionMagnitude = self.collision[1]
        m.mTrackTemperature, m.mAmbientTemperature = 31.0, 22.0
        return m


def run_race(out_dir: str | Path, humans: list[str], script: RaceScript, seed: int = 0,
             start: datetime | None = None, log=lambda *_: None, local_human: str | None = None) -> list[Path]:
    """Simulate one race weekend through the real Recorder. Returns recorded session dirs.
    `local_human` records the same weekend from another driver's PC (same seed = same session)."""
    start = start or datetime(2026, 10, 3, 20, 0, 0)
    sim = RaceSim(humans, script, seed=seed, local_human=local_human)
    clock = {"now": 0.0}
    rec = Recorder(out_dir, hz=1 / DT, sessions=("race", "qualify"), label=sim.local_name,
                   flush_s=30.0, grace_s=10.0, log=log,
                   wallclock=lambda: start + timedelta(seconds=clock["now"]))

    def tick(snap):
        clock["now"] += DT
        rec.step(snap, clock["now"])

    for _ in range(int(2 / DT)):  # main menu
        tick(sim.snapshot(S.GAME_FRONT_END, S.SESSION_INVALID))

    if script.with_qualifying:
        qsim = RaceSim(humans, RaceScript(laps=99, n_ai=script.n_ai), seed=seed + 1000)
        qsim.grid, qsim.cars = sim.grid, [  # same field, spread around the lap
            Car(name=c.name, car=c.car, is_ai=c.is_ai, pace=c.pace, s=200.0 + 150.0 * i)
            for i, c in enumerate(sim.cars)]
        qsim.slots = list(qsim.cars)
        qsim.local_name = sim.local_name
        qsim.script.local_collision_lap = None
        for _ in range(int(340 / DT)):  # long enough for several flying laps each
            qsim.advance(t_green=0.0)
            tick(qsim.snapshot(S.GAME_INGAME_PLAYING, S.SESSION_QUALIFY))
        for _ in range(int(3 / DT)):  # brief loading screen, shorter than the grace period
            tick(sim.snapshot(S.GAME_FRONT_END, S.SESSION_INVALID))

    t_green = 4.0
    while sim.done_t is None or sim.t < sim.done_t + 5.0:
        sim.advance(t_green)
        tick(sim.snapshot(S.GAME_INGAME_PLAYING, S.SESSION_RACE))
        if sim.t > 3600:
            raise RuntimeError("simulation did not finish")
    for _ in range(int(12 / DT)):  # back to menus; recorder closes after grace period
        tick(sim.snapshot(S.GAME_FRONT_END, S.SESSION_INVALID))
    rec.close(clock["now"])

    race_dir = next(p for p in rec.completed if re.search(r"_race(_\d+)?$", p.name))
    finish = [c.name for c in sim._order()]
    truth = {
        "humans": humans, "grid": sim.grid,
        "classification": finish + [c.name for c in sim.cars if c.gone],
        "gone": [c.name for c in sim.cars if c.gone],
        "retired": [c.name for c in sim.cars if c.state == S.RACESTATE_RETIRED],
        "events": sim.events, "laps": script.laps, "ai_strength": script.ai_strength,
    }
    (race_dir / "truth.json").write_text(json.dumps(truth, indent=2))
    return rec.completed


def demo_season(out_dir: str | Path, humans: list[str] | None = None, races: int = 4,
                seed: int = 7, log=print) -> list[Path]:
    """Write a few simulated rounds plus a matching season config, for trying the tools."""
    humans = humans or ["Jax", "Mason", "Eli", "Theo"]
    rng = random.Random(seed)
    out = Path(out_dir)
    sessions = []
    for r in range(races):
        others = [h for h in humans]
        script = RaceScript(
            laps=rng.choice([5, 6]), n_ai=rng.randint(8, 14), ai_strength=rng.uniform(0.985, 1.01),
            spin=(rng.choice(others), 2, rng.choice([300, 1320, 2370])),
            pit=(rng.randint(4, 10), 3) if r % 2 == 0 else None,
            retire=(rng.randint(5, 12), 4, 1500.0) if r % 2 == 1 else None,
            disconnect=(humans[-1], 3, 900.0) if r == races - 1 else None,
            with_qualifying=(r == 0),
        )
        start = datetime(2026, 10, 3, 20, 0, 0) + timedelta(days=7 * r)
        done = run_race(out, humans, script, seed=seed * 100 + r, start=start, log=lambda *_: None)
        race = next(p for p in done if p.name.endswith("_race"))
        sessions.append(race)
        log(f"[sim] round {r + 1}: {race.name}  ({script.n_ai} AI, {script.laps} laps)")
    config = {
        "name": "Demo GT3 Season",
        "drivers": [{"key": h.lower(), "display": h, "aliases": [h]} for h in humans],
        "points": {"f1": [25, 18, 15, 12, 10, 8, 6, 4, 2, 1], "linear": [10, 8, 6, 5, 4, 3, 2, 1]},
        "default_points": "f1",
        "ai_policy": "humans_only",
        "fastest_lap_bonus": 1,
        "drop_rounds": 0,
        "points_for_dnf": False,
    }
    (out / "season.demo.json").write_text(json.dumps(config, indent=2))
    return sessions


def mapping_drive(driver: str = "Jax", sides=("left", "right"), seed: int = 0):
    """Yield (snapshot, t) for a practice session in which `driver` drives one lap along each edge,
    wheels on the white line, as the app's track-mapping instructions ask."""
    sim = RaceSim([driver], RaceScript(laps=999, n_ai=0, local_collision_lap=None), seed=seed)
    sim.cars[0].s = 50.0
    t = 0.0
    for side in sides:
        sim.mapping_side = side
        start = sim.cars[0].s
        while sim.cars[0].s < start + sim.L:
            sim.advance(t_green=0.0)
            t += DT
            yield sim.snapshot(S.GAME_INGAME_PLAYING, S.SESSION_PRACTICE), t


def practice_drive(driver: str = "Jax", laps: int = 8, seed: int = 0, consistency: float = 4.0, tyre_wear: float = 1.0,
                   tyre_setup: dict | None = None,
                   invalid_laps=(3,), lockup_rate: float = 0.06, spin_rate: float = 0.06, start_s: float = -150.0):
    """Yield (snapshot, t) for a solo practice session: out of the pits, `laps` flying laps. Lap times
    vary with the driver's consistency; laps in `invalid_laps` (1-based) get invalidated."""
    extra = {"seed": seed, "consistency": {driver: consistency}, "tyre_wear": {driver: tyre_wear},
             "tyre_setup": {driver: tyre_setup or {}}, "tyre_start_temp": 40.0,
             "lockup_rate": {driver: lockup_rate}, "spin_rate": {driver: spin_rate}}
    sim = RaceSim([driver], RaceScript(laps=999, n_ai=0, local_collision_lap=None, extra=extra), seed=seed)
    car = sim.cars[0]
    car.s = start_s
    car.pace = 1.0
    t, done = 0.0, 0
    while done < laps:
        before = math.floor(car.s / sim.L)
        sim.advance(t_green=0.0)
        t += DT
        lap_now = math.floor(car.s / sim.L)
        if lap_now > before:
            done = lap_now
            car.lap_noise = random.Random(seed * 1000 + lap_now).gauss(0, 0.004 * consistency / 4.0)
        if (lap_now + 1) in invalid_laps and car.s - lap_now * sim.L > 1500:
            car.lap_invalid = True
        yield sim.snapshot(S.GAME_INGAME_PLAYING, S.SESSION_PRACTICE), t
