"""Immutable inputs and messages. Unknown telemetry is explicit, never a zero."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from string import Formatter
from typing import Any


# AMS2 mCrashState: 0 none, 1 off track, 2 large impact, 3 spinning, 4 rolling.
# Track limits are judged only by the game's own lap-invalid flags (the driver's
# local flag and each car's participant flag). A brief off-track state on a lap the
# game still counts, such as kerbs and exits used at full commitment, is driving,
# not an incident. Impacts, spins and rolls are incidents; an unknown state is
# never treated as clean.
ON_TRACK_STATES = (0, 1)

# Practice summaries (fuel use, section loss, braking, corner speed, apex) are measured
# at the halfway timing line. They wait for a radio window until a newer measurement
# replaces them, never longer than this; corner calls also end at the start/finish
# line. On a short lap the only usable straight can be more than 20 s after the
# halfway line (Brands Hatch Indy: about 16 s to Brabham Straight).
PRACTICE_SUMMARY_S = 90


def incident(crash_state):
    return crash_state not in ON_TRACK_STATES


def finite(value, default=None):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError, OverflowError):
        return default


def count(value, default=-1):
    result = finite(value)
    if result is None or not result.is_integer():
        return default
    result = int(result)
    if 0 <= result < 10000:
        return result
    masked = result & 0x7fffffff
    return masked if 0 <= result <= 0xffffffff and masked < 10000 else default


@dataclass(frozen=True)
class Car:
    slot: int
    name: str
    car: str = ""
    car_class: str = ""
    position: int = -1
    laps: int = -1
    distance: float | None = None
    speed: float | None = None
    pit: int = -1
    race_state: int = -1
    invalid: bool = True
    flag_colour: int = -1
    x: float | None = None
    z: float | None = None
    last_lap: float | None = None   # the game's last lap time, seconds; None when unknown
    pit_schedule: int = -1
    sector: int = -1             # AMS2 raw sector is zero-indexed

    @property
    def identity(self):
        # Slot alone is unsafe after a leave/join or in another session.
        return f"{self.slot}:{self.name}:{self.car}"


@dataclass(frozen=True)
class Tick:
    t: float
    session_id: str
    session: str
    track: str
    layout: str
    length: float
    game_state: int
    viewed_slot: int
    cars: tuple[Car, ...]
    local: dict[str, Any] = field(default_factory=dict)
    fresh: bool = True

    def player(self, expected_name):
        matches = [c for c in self.cars if c.name == expected_name]
        return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class Context:
    t: float
    session_id: str
    session: str = "race"
    lap: int = 1
    distance: float | None = None
    active: bool = False
    reason: str = "no_telemetry"
    speed: float | None = None
    throttle: float | None = None
    brake: float | None = None
    steering: float | None = None
    pit: int = -1
    rain: float | None = None
    nearest_gap: float | None = None
    since_incident: float | None = None
    qualifying_push: bool = False
    window_s: float | None = None
    window_id: str | None = None
    # None means CC/spotter activity is unobserved, not that the radio is idle.
    radio_busy: bool | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    # In the pit lane under the limiter, stopped in the box, or in the garage menu with the
    # car in the pits: briefs and debriefs may be spoken here (window 'pits').
    pit_radio: bool = False


@dataclass(frozen=True)
class Requirement:
    key: str
    value: Any
    op: str = "eq"

    def __post_init__(self):
        if self.op not in ("eq", "in", "ge", "le"):
            raise ValueError("Unsupported evidence comparison.")

    def satisfied(self, facts):
        actual = facts.get(self.key)
        if actual is None:
            return False
        if self.op == "eq":
            return actual == self.value
        if self.op == "in":
            return actual in self.value
        a, b = finite(actual), finite(self.value)
        return a is not None and b is not None and (a >= b if self.op == "ge" else a <= b)


@dataclass(frozen=True)
class Evidence:
    confidence: str = "low"
    values: dict[str, Any] = field(default_factory=dict)
    pattern_laps: tuple[int, ...] = ()
    loss_s: float | None = None
    severity: float = 0

    def __post_init__(self):
        if self.confidence not in ("low", "medium", "high"):
            raise ValueError("Invalid confidence.")
        if finite(self.severity) is None or self.severity < 0:
            raise ValueError("Invalid evidence severity.")


@dataclass(frozen=True)
class MessageSpec:
    code: str
    category: str
    urgency: int
    phrases: tuple[str, ...]
    sessions: tuple[str, ...] = ("practice", "qualify", "race", "time_attack")
    cooldown_s: float = 45
    ttl_s: float = 12
    owner: str = "paddock"
    pattern: bool = False
    window: str = "straight"
    fact_count: int = 1
    # False for scripted lines (briefs, answers): a driver may ask for the same line twice.
    vary: bool = True

    def __post_init__(self):
        if not re.fullmatch(r"[A-Z]-\d{2}", self.code) or not 0 <= self.urgency <= 4:
            raise ValueError("Invalid message ID or urgency.")
        if len(self.phrases) < 3 or len(set(self.phrases)) != len(self.phrases):
            raise ValueError("A message needs at least three distinct phrasings.")
        if self.window not in ("straight", "stationary", "either", "pits"):
            raise ValueError("Invalid radio window.")
        if self.owner not in ("paddock", "crew_chief"):
            raise ValueError("Invalid message owner.")
        if type(self.fact_count) is not int or not 1 <= self.fact_count <= 20:
            raise ValueError('Invalid message fact count.')
        if finite(self.cooldown_s) is None or self.cooldown_s < 0 or finite(self.ttl_s) is None or self.ttl_s <= 0:
            raise ValueError("Invalid message lifetime.")
        for phrase in self.phrases:
            if len(phrase) > 256 or not phrase.strip():
                raise ValueError("Invalid radio wording.")
            for _, name, fmt, conversion in Formatter().parse(phrase):
                if name is not None and (not re.fullmatch(r"[a-z_]+", name) or fmt or conversion):
                    raise ValueError("Slots must be plain names.")


@dataclass(frozen=True)
class Message:
    id: str
    spec: MessageSpec
    session_id: str
    created: float
    expires: float
    key: str
    slots: dict[str, str]
    evidence: Evidence
    requirements: tuple[Requirement, ...] = ()
    last_lap: int | None = None
    corner: str | None = None
    anchor_lap: int | None = None
    available_after_distance: float | None = None
    bundle_key: str | None = None
    requested: bool = False  # Explicit driver reply; automatic-call controls do not suppress it.

    def __post_init__(self):
        if finite(self.created) is None or finite(self.expires) is None or self.expires <= self.created:
            raise ValueError("Invalid message timestamps.")
        if not self.id or not self.key:
            raise ValueError("Messages need an ID and a deduplication key.")
        if self.bundle_key is not None and (not isinstance(self.bundle_key,str) or not 1 <= len(self.bundle_key) <= 200):
            raise ValueError('Invalid related-fact group.')
        # Validate render inputs once, before they reach a live delivery path.
        for phrase in self.spec.phrases:
            rendered = phrase.format_map(self.slots)
            if len(rendered) > 300 or any(ord(c) < 32 for c in rendered):
                raise ValueError("Invalid message slots.")

    def render(self, variant):
        text = self.spec.phrases[variant % len(self.spec.phrases)].format_map(self.slots)
        if self.evidence.confidence == "medium":
            text = "Looks like " + text[0].lower() + text[1:]
        return text


@dataclass(frozen=True)
class CallPart:
    message: Message
    text: str
    variant: int


@dataclass(frozen=True)
class Delivery:
    message: Message
    text: str
    seconds: float
    variant: int
    parts: tuple[CallPart,...] = ()

    def __post_init__(self):
        if self.parts and (not 1 <= len(self.parts) <= 3 or self.parts[0].message != self.message
                           or self.parts[0].variant != self.variant
                           or len({p.message.id for p in self.parts}) != len(self.parts)
                           or len({p.message.key for p in self.parts}) != len(self.parts)
                           or (len(self.parts)>1 and sum(p.message.spec.fact_count for p in self.parts)>3)
                           or any(p.message.session_id != self.message.session_id for p in self.parts)):
            raise ValueError('Invalid related-fact delivery.')

    @property
    def calls(self):
        return self.parts or (CallPart(self.message,self.text,self.variant),)

    @property
    def expires(self):
        return min(p.message.expires for p in self.calls)
