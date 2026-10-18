"""Deterministic radio scheduling with explicit evidence and delivery receipts.

Selecting a call is not proof it was spoken. Consumers acknowledge dispatch and
report start/end; offline replay labels its deliveries as simulated.
"""
from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import json
import threading
from pathlib import Path

from .model import CallPart, Context, Delivery, Message, finite


@dataclass
class Policy:
    mode: str = "full"
    race_coaching_interval: int = 3
    max_pending: int = 48
    max_call_s: float = 6
    quiet_until_lap: int = 0
    # Briefs and debriefs in the pits: no driving workload, so a longer call is allowed.
    max_pit_call_s: float = 16
    # A call first waits for a learned straight with full throttle and the wheel straight. After
    # this long it takes a tighter spot (light throttle or a gentle bend, no braking), because a
    # call in a slightly busier place beats no call (short tracks such as Brands Hatch Indy have
    # few straights long enough). Urgency 0-1 calls take a tighter spot at once.
    relax_after_s: float = 8

    def __post_init__(self):
        if self.mode not in ("full", "race", "quiet", "coach", "silent"):
            raise ValueError("Unknown verbosity mode.")
        if not 1 <= self.max_pending <= 200 or not 1 <= self.race_coaching_interval <= 20:
            raise ValueError("Invalid talk budget.")


class RadioLog:
    def __init__(self, path: Path | None = None, limit=600, deferred=False):
        self.path = Path(path) if path else None
        self.events = deque(maxlen=limit)
        self.counts = Counter()
        self.deferred = deferred
        self._writes = deque()
        self._flush_lock = threading.Lock()

    def record(self, state, ctx, message=None, reason=None, **values):
        event = {"state": state, "t": ctx.t, "session_id": ctx.session_id,
                 "lap": ctx.lap, "distance": ctx.distance}
        if message:
            event.update(id=message.id, code=message.spec.code, key=message.key,
                         urgency=message.spec.urgency, corner=message.corner,
                         evidence=asdict(message.evidence))
        if reason:
            event["reason"] = reason
        event.update(values)
        # Fail loudly on NaN or non-serializable evidence; never write misleading JSON.
        encoded = json.dumps(event, ensure_ascii=False, allow_nan=False)
        if self.path:
            if self.deferred:
                if len(self._writes) >= 2048:
                    raise OSError("The private radio log could not keep up.")
                self._writes.append(encoded+'\n')
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as target:
                    target.write(encoded + "\n")
        self.events.append(event)
        self.counts[state] += 1
        return event

    def flush(self):
        """Called by the live worker, never from CC's audio-fetch request."""
        if not self.path or not self._writes or not self._flush_lock.acquire(blocking=False):
            return
        try:
            batch = [self._writes.popleft() for _ in range(len(self._writes))]
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as target:
                    target.writelines(batch)
            except OSError:
                self._writes.extendleft(reversed(batch))
                raise
        finally:
            self._flush_lock.release()


class Scheduler:
    def __init__(self, policy=None, log=None, voice_duration=None):
        self.policy = policy or Policy()
        self.log = log or RadioLog()
        self.pending: dict[str, Message] = {}
        self.held = {}
        self.session_id = None
        self.was_active = False
        self.last_t = None
        self.last_lap = None
        self.delivering: Delivery | None = None
        self.busy_until = float("-inf")
        self.last_by_key = {}
        self.last_variant = {}
        self.last_text = {}
        self.per_lap = Counter()
        self.last_coaching_lap = -100
        self.voice_duration = voice_duration
        self.last_window = None
        self.call_controls = {}
        self.last_by_code = {}
        self._request_depth = 0

    @contextmanager
    def requested(self):
        self._request_depth += 1
        try:
            yield
        finally:
            self._request_depth -= 1

    def control_reason(self, message, ctx, *, interval=True):
        if message.requested or message.spec.code in ('V-24', 'V-25'):
            return None
        options = self.call_controls.get(message.spec.code, {})
        if options.get('enabled') is False:
            return 'automatic_call_disabled'
        before = self.last_by_code.get(message.spec.code)
        if interval and before is not None and 0 <= ctx.t - before < options.get('min_interval_s', 0):
            return 'automatic_call_interval'
        return None

    def log_delivery(self, state, ctx, delivery, reason=None, **values):
        values.setdefault('text',delivery.text)
        if len(delivery.calls)>1:
            values['bundle_ids'] = [p.message.id for p in delivery.calls]
            values['evidence'] = {'components':[
                {'id':p.message.id,'code':p.message.spec.code,'key':p.message.key,
                 'text':p.text,'evidence':asdict(p.message.evidence)} for p in delivery.calls]}
        return self.log.record(state,ctx,delivery.message,reason,**values)

    def invalid_delivery(self, delivery, ctx):
        return next((reason for part in delivery.calls if (reason := self.invalid(part.message,ctx))),None)

    def reset(self, ctx, reason="session_changed"):
        for message in list(self.pending.values()):
            self.drop(message, ctx, reason)
        if self.delivering:
            self.log_delivery("cancelled", ctx, self.delivering, reason)
        self.delivering = None
        self.busy_until = float("-inf")
        self.last_by_key.clear()
        self.last_by_code.clear()
        self.last_variant.clear()
        self.last_text.clear()
        self.per_lap.clear()
        self.last_coaching_lap = -100
        self.last_window = None
        self.policy.quiet_until_lap = 0
        self.session_id = ctx.session_id

    def advance(self, ctx):
        if (self.session_id != ctx.session_id or
                (self.last_t is not None and ctx.t < self.last_t) or
                (self.last_lap is not None and ctx.lap < self.last_lap)):
            self.reset(ctx)
        if not ctx.active or not self.was_active:
            # Also clear messages queued while suspended: they cannot survive resume.
            # A pit brief or debrief survives the garage menu while the car stays in the pits.
            for message in list(self.pending.values()):
                if not (ctx.pit_radio and message.spec.window == 'pits'):
                    self.drop(message, ctx, ctx.reason if not ctx.active else "resumed")
            if not ctx.active and self.delivering:
                self.log_delivery("cancelled", ctx, self.delivering, ctx.reason)
                self.delivering = None
                self.busy_until = float("-inf")
        self.was_active, self.last_t, self.last_lap = ctx.active, ctx.t, ctx.lap
        # Bound bookkeeping independently of session length.
        for key in list(self.per_lap):
            if key[0] < ctx.lap - 3:
                del self.per_lap[key]
        for message in list(self.pending.values()):
            reason = self.invalid(message, ctx)
            if reason:
                self.drop(message, ctx, reason)

    def invalid(self, message, ctx):
        if message.session_id != ctx.session_id:
            return "session_changed"
        if ctx.t >= message.expires or (message.last_lap is not None and ctx.lap > message.last_lap):
            return "expired"
        if not all(r.satisfied(ctx.facts) for r in message.requirements):
            return "condition_changed"
        return self.control_reason(message, ctx, interval=False)
        return None

    def offer(self, message, ctx):
        if self._request_depth:
            message = replace(message, requested=True)
        self.advance(ctx)
        reason = self.invalid(message, ctx) or self.control_reason(message, ctx)
        if not ctx.active and not (ctx.pit_radio and message.spec.window == 'pits'):
            reason = ctx.reason
        elif message.spec.owner != "paddock":
            reason = "crew_chief_owned"
        elif ctx.session not in message.spec.sessions:
            reason = "wrong_session_type"
        elif message.evidence.confidence == "low":
            reason = "low_confidence"
        elif message.spec.pattern:
            recent = {lap for lap in message.evidence.pattern_laps if ctx.lap - 3 <= lap < ctx.lap}
            if len(recent) < 2 or finite(message.evidence.loss_s, 0) < .05:
                reason = "insufficient_pattern"
        if reason:
            self.log.record("dropped", ctx, message, reason)
            return False
        previous = self.last_by_key.get(message.key)
        if previous and ctx.t - previous["t"] < message.spec.cooldown_s:
            self.log.record("dropped", ctx, message, "cooldown")
            return False
        if message.key in self.pending or (self.delivering and any(p.message.key == message.key for p in self.delivering.calls)):
            self.log.record("dropped", ctx, message, "duplicate")
            return False
        if len(self.pending) >= self.policy.max_pending:
            worst = max(self.pending.values(), key=lambda m: (m.spec.urgency, -m.created))
            if worst.spec.urgency <= message.spec.urgency:
                self.log.record("dropped", ctx, message, "queue_full")
                return False
            self.drop(worst, ctx, "priority_replacement")
        self.pending[message.key] = message
        self.log.record("queued", ctx, message)
        return True

    def drop(self, message, ctx, reason):
        self.pending.pop(message.key, None)
        self.held.pop(message.id, None)
        self.log.record("dropped", ctx, message, reason)

    def hold_reason(self, message, ctx, seconds, *, reserved=False, in_crew_chief=False):
        reason = self.control_reason(message, ctx, interval=not reserved)
        if reason:
            return reason
        urgency = message.spec.urgency
        max_urgency = {"full": 4, "race": 2, "quiet": 1, "coach": 4, "silent": 0}[self.policy.mode]
        if urgency > max_urgency:
            return "verbosity"
        if urgency >= 2 and ctx.lap < self.policy.quiet_until_lap:
            return "quiet_laps"
        if ctx.qualifying_push and urgency > 0 and message.spec.category != 'timing':
            return "qualifying_push"     # a lap time at the line is still given
        if not in_crew_chief and ctx.radio_busy is not False:
            return "radio_busy" if ctx.radio_busy else "radio_state_unknown"
        if (self.delivering is not None and not reserved) or ctx.t < self.busy_until:
            return "engineer_busy"
        pit_call = message.spec.window == 'pits'
        if seconds > (self.policy.max_pit_call_s if pit_call else self.policy.max_call_s):
            return "call_too_long"
        if ctx.t+seconds > message.expires:
            return 'insufficient_lifetime'
        if message.anchor_lap is not None:
            if ctx.lap < message.anchor_lap:
                return "before_corner"
            if (ctx.lap == message.anchor_lap and message.available_after_distance is not None
                    and (ctx.distance is None or ctx.distance < message.available_after_distance)):
                return "before_corner"
        if pit_call:
            # Stopped, under the pit limiter or in the garage menu: no driving workload,
            # straight windows or lap budget apply; on track it waits for the next stop.
            return None if ctx.pit_radio else 'not_in_pits'
        if urgency >= 3:
            if ctx.facts.get("traffic_known") is False:
                return "traffic_unknown"
            if ctx.pit != 0:
                return "pit_lane"
            if ctx.session == "race" and ctx.lap <= 1:
                return "first_lap"
            if ctx.nearest_gap is not None and ctx.nearest_gap <= 1:
                return "close_racing"
            if ctx.since_incident is not None and ctx.since_incident < 30:
                return "recent_incident"
            if ctx.rain is None or ctx.rain >= .45:
                return "rain_or_unknown"
            if (urgency == 3 and ctx.session == "race" and
                    ctx.lap - self.last_coaching_lap < self.policy.race_coaching_interval):
                return "coaching_budget"
        if (urgency>=2 and ctx.nearest_gap is not None and ctx.nearest_gap<=1
                and (ctx.window_id is None or ctx.window_id==self.last_window)):
            return "battle_window_unknown" if ctx.window_id is None else "battle_straight_budget"
        limit = {0: 1000, 1: 3, 2: 2, 3: 8 if self.policy.mode == "coach" else 1, 4: 1}[urgency]
        if message.spec.category != 'recon' and self.per_lap[(ctx.lap, urgency)] >= limit:
            return "lap_budget"
        previous = self.last_by_key.get(message.key)
        if previous and message.corner and ctx.lap - previous["lap"] < 3:
            if message.evidence.severity <= previous["severity"] * 1.2:
                return "corner_cooldown"
        stationary = ctx.speed is not None and ctx.speed < 1 and ctx.pit in (2, 4)
        if message.spec.window in ("stationary", "either") and stationary:
            return None
        if message.spec.window == "stationary":
            return "not_stationary"
        if urgency == 0:
            return None
        strict = self._workload_reason(ctx, seconds)
        if strict is None:
            return None
        if self.pit_lane_calm(ctx):
            return None       # rolling down the pit lane on the limiter: nothing to do but steer
        waited = ctx.t - message.created
        # Urgent calls, and a lap time at the line (it is about the moment), take a tighter spot at once.
        prompt = urgency <= 1 or message.spec.category == 'timing'
        if waited >= (0 if prompt else self.policy.relax_after_s) and self.light_workload(ctx):
            return None
        return strict

    @staticmethod
    def _workload_reason(ctx, seconds):
        if (ctx.pit != 0 or ctx.speed is None or ctx.speed < 10 or ctx.brake is None or ctx.brake > .03
                or ctx.throttle is None or ctx.throttle < .9 or ctx.steering is None or abs(ctx.steering) > .07):
            return "driving_workload"
        if ctx.window_s is None or ctx.window_s < seconds + .5:
            return "no_radio_window"
        return None

    @staticmethod
    def light_workload(ctx):
        """On track, not braking, on some throttle and no more than a gentle bend."""
        return (ctx.pit == 0 and ctx.speed is not None and ctx.speed >= 10 and ctx.brake is not None
                and ctx.brake <= .05 and ctx.throttle is not None and ctx.throttle >= .3
                and ctx.steering is not None and abs(ctx.steering) <= .2)

    @staticmethod
    def pit_lane_calm(ctx):
        """Driving down the pit lane (in or out) at limiter speed, off the brakes."""
        return (ctx.pit in (1, 3) and ctx.speed is not None and 2 <= ctx.speed <= 25
                and ctx.brake is not None and ctx.brake <= .2)

    def _seconds(self, text):
        if self.voice_duration:
            value = finite(self.voice_duration(text))
            return value if value is not None and .3<=value<=20 else None
        return max(1,len(text.split())/2.6+.25)

    def _wording(self, message):
        start = (self.last_variant.get(message.spec.code,-1)+1)%len(message.spec.phrases)
        repeated = False
        for offset in range(len(message.spec.phrases)):
            variant = (start+offset)%len(message.spec.phrases)
            text = message.render(variant)
            seconds = self._seconds(text)
            if seconds is not None:
                if message.spec.vary and text==self.last_text.get(message.spec.code):
                    repeated = True
                    continue
                return CallPart(message,text,variant),seconds,None
        return None,None,'voice_variant_missing' if repeated else 'voice_clip_missing'

    def _bundle(self, first, seconds, ctx, ordered):
        parts, text = [first], first.text
        group = first.message.bundle_key
        if group and first.message.spec.urgency>=2:
            for message in ordered:
                if len(parts)==3:
                    break
                if (any(message.id==p.message.id or message.key==p.message.key for p in parts) or message.bundle_key!=group
                        or message.spec.urgency!=first.message.spec.urgency or self.invalid(message,ctx)):
                    continue
                part,_,reason = self._wording(message)
                if reason:
                    continue
                combined = text+' '+part.text
                duration = self._seconds(combined)
                if duration is None or duration>min(6,self.policy.max_call_s):
                    continue
                proposed = parts+[part]
                if (sum(p.message.spec.fact_count for p in proposed)>3
                        or any(p.message.expires<ctx.t+duration for p in proposed)
                        or any(self.hold_reason(p.message,ctx,duration) for p in proposed)):
                    continue
                parts,text,seconds = proposed,combined,duration
        return Delivery(first.message,text,seconds,first.variant,tuple(parts) if len(parts)>1 else ())

    def select(self, ctx):
        self.advance(ctx)
        if not ctx.active and not ctx.pit_radio:
            return None
        ordered = sorted(self.pending.values(), key=lambda m: (m.spec.urgency, m.created, m.id))
        if not ctx.active:
            ordered = [m for m in ordered if m.spec.window == 'pits']
        for message in ordered:
            part,seconds,reason = self._wording(message)
            reason = reason or self.hold_reason(message,ctx,seconds)
            if reason:
                if self.held.get(message.id) != reason:
                    self.log.record("held", ctx, message, reason)
                    self.held[message.id] = reason
                continue
            # Revalidate here as well: the consumer must dispatch against this exact context.
            reason = self.invalid(message, ctx)
            if reason:
                self.drop(message, ctx, reason)
                continue
            self.delivering = self._bundle(part,seconds,ctx,ordered)
            for member in self.delivering.calls:
                self.pending.pop(member.message.key)
                self.held.pop(member.message.id,None)
            self.log_delivery("selected",ctx,self.delivering)
            return self.delivering
        return None

    def delivery_reason(self, delivery, ctx):
        """Called by the one-use clip endpoint on CC's actual audio-fetch path."""
        if self.delivering != delivery:
            return "delivery_cancelled"
        if not ctx.active and not self._pit_delivery(delivery, ctx):
            return ctx.reason
        reason = self.invalid_delivery(delivery, ctx)
        if reason:
            return reason
        # CC is already preparing this sound inside its own queue. A sampled
        # 'playing' flag can still describe the preceding CC clip. Its queue
        # owns arbitration here; recheck all telemetry/workload gates ourselves.
        return next((reason for part in delivery.calls if (reason := self.hold_reason(
            part.message,ctx,delivery.seconds,reserved=True,in_crew_chief=True))),None)

    @staticmethod
    def _pit_delivery(delivery, ctx):
        return ctx.pit_radio and all(part.message.spec.window == 'pits' for part in delivery.calls)

    def acknowledge(self, delivery, ctx, *, accepted, simulated=False):
        if self.delivering != delivery:
            return False
        if (not accepted or (not ctx.active and not self._pit_delivery(delivery, ctx))
                or self.invalid_delivery(delivery, ctx)):
            self.log_delivery("dropped",ctx,delivery,"delivery_rejected")
            self.delivering = None
            return False
        self.log_delivery("would_say" if simulated else "submitted",ctx,delivery,seconds=delivery.seconds)
        urgencies = set()
        for part in delivery.calls:
            message = part.message
            if not message.requested:
                self.last_by_code[message.spec.code] = ctx.t
            self.last_by_key[message.key] = {"t":ctx.t,"lap":ctx.lap,"severity":message.evidence.severity}
            self.last_variant[message.spec.code] = part.variant
            self.last_text[message.spec.code] = part.text
            urgencies.add(message.spec.urgency)
        if len(self.last_by_key) > 2048:
            oldest = min(self.last_by_key, key=lambda k: self.last_by_key[k]["t"])
            del self.last_by_key[oldest]
        for urgency in {p.message.spec.urgency for p in delivery.calls
                        if p.message.spec.window != 'pits' and p.message.spec.category != 'recon'}:
            # Pit briefs do not use up the on-track talk budget.
            self.per_lap[(ctx.lap,urgency)] += 1
        if 3 in urgencies:
            self.last_coaching_lap = ctx.lap
        if ctx.window_id is not None and max(urgencies)>=2:
            self.last_window = ctx.window_id
        self.busy_until = ctx.t + delivery.seconds
        self.delivering = None
        return True

    def quiet(self, ctx, laps=3):
        if not 1 <= laps <= 20:
            raise ValueError("Quiet duration must be1-20 laps.")
        self.policy.quiet_until_lap = ctx.lap + laps
        self.log.record("setting", ctx, reason="quiet_laps", until_lap=self.policy.quiet_until_lap)
