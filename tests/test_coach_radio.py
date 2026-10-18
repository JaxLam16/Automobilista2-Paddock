"""Behavioral radio checks: stale advice, workload, evidence and receipt handling."""
from dataclasses import replace
import json

import pytest

from ams2season.coach.catalogue import CATALOGUE
from ams2season.coach.model import Context, Evidence, Message, MessageSpec, Requirement
from ams2season.coach.radio import RadioLog, Policy, Scheduler


def context(**changes):
    return replace(Context(100, "race-a", lap=5, distance=500, active=True, reason="active",
                           speed=55, throttle=1, brake=0, steering=.01, pit=0, rain=0,
                           nearest_gap=5, since_incident=60, window_s=12, radio_busy=False,
                           facts={"ahead": "a", "pit:a": 1}), **changes)


def message(ctx=None, code="X-15", **changes):
    ctx = ctx or context()
    spec = CATALOGUE[code]
    return replace(Message("one", spec, ctx.session_id, ctx.t, ctx.t + spec.ttl_s,
                           code + ":a", {"relation": "car ahead", "turn": "turn nine"},
                           Evidence("high", {"observed_pit": 1}, (2, 3, 4), .2, 1),
                           (Requirement("pit:a", (1, 2), "in"),)), **changes)


def play(scheduler, ctx):
    selected = scheduler.select(ctx)
    assert selected is not None
    assert scheduler.acknowledge(selected, ctx, accepted=True, simulated=True)
    return selected


def test_revalidates_pit_state_and_rival_identity_before_speaking():
    ctx = context()
    radio = Scheduler()
    m = message(ctx, requirements=(Requirement("ahead", "a"), Requirement("pit:a", (1, 2), "in")))
    assert radio.offer(m, ctx)
    assert radio.select(replace(ctx, t=101, facts={"ahead": "b", "pit:a": 1})) is None
    assert radio.log.events[-1]["reason"] == "condition_changed"
    assert not radio.pending


def test_expiry_is_absolute_and_does_not_extend_while_waiting():
    ctx = context(radio_busy=True)
    radio = Scheduler()
    radio.offer(message(ctx), ctx)
    assert radio.select(ctx) is None
    assert radio.select(replace(ctx, t=110, radio_busy=False)) is None
    assert radio.log.events[-1]["reason"] == "expired"


@pytest.mark.parametrize("reason", ["paused", "replay", "menus", "spectating", "disconnected"])
def test_suspension_drops_waiting_calls_and_never_replays_them(reason):
    radio, ctx = Scheduler(), context()
    radio.offer(message(ctx), ctx)
    radio.advance(replace(ctx, active=False, reason=reason))
    assert radio.select(replace(ctx, t=101)) is None
    assert any(e.get("reason") == reason for e in radio.log.events)


def test_session_change_and_clock_rewind_clear_cooldowns_and_pending():
    radio, ctx = Scheduler(), context()
    radio.offer(message(ctx), ctx)
    play(radio, ctx)
    newer = replace(ctx, t=1, session_id="race-b", lap=1)
    assert radio.offer(message(newer, id="two"), newer)
    assert play(radio, newer).variant == 0


def test_priority_and_safety_do_not_cut_over_crew_chief():
    ctx, radio = context(), Scheduler()
    high = replace(CATALOGUE["X-15"], code="F-04", urgency=0)
    radio.offer(message(ctx), ctx)
    radio.offer(message(ctx, id="safety", key="hazard", spec=high), ctx)
    assert radio.select(replace(ctx, radio_busy=True)) is None
    assert radio.select(replace(ctx, radio_busy=None)) is None
    assert play(radio, replace(ctx, window_s=None, brake=1)).message.id == "safety"


def test_only_actual_accepted_dispatch_counts_against_budget_or_cooldown():
    radio, ctx = Scheduler(), context()
    m = message(ctx)
    radio.offer(m, ctx)
    selected = radio.select(ctx)
    assert not radio.acknowledge(selected, ctx, accepted=False)
    assert not radio.last_by_key and not radio.per_lap
    radio.offer(replace(m, id="retry"), replace(ctx, t=101))
    play(radio, replace(ctx, t=101))
    assert not radio.offer(replace(m, id="duplicate"), replace(ctx, t=104))
    assert radio.log.events[-1]["reason"] == "cooldown"


def test_transport_receipt_never_claims_audible_playback():
    radio, ctx = Scheduler(), context()
    radio.offer(message(ctx), ctx)
    selected = radio.select(ctx)
    assert radio.acknowledge(selected, ctx, accepted=True)
    assert radio.log.events[-1]["state"] == "submitted"
    assert not any(e["state"] == "spoken" for e in radio.log.events)


@pytest.mark.parametrize("changes,reason", [
    ({"lap": 1}, "first_lap"), ({"pit": 1}, "pit_lane"),
    ({"nearest_gap": .8}, "close_racing"), ({"since_incident": 10}, "recent_incident"),
    ({"rain": .8}, "rain_or_unknown"), ({"rain": None}, "rain_or_unknown"),
    ({"qualifying_push": True}, "qualifying_push"), ({"window_s": 1}, "no_radio_window"),
    ({"brake": .5}, "driving_workload"), ({"steering": None}, "driving_workload"),
])
def test_low_priority_holds_for_real_workload(changes, reason):
    ctx, radio = context(**changes), Scheduler()
    # Isolate workload from pattern generation, covered separately below.
    spec = replace(CATALOGUE["C-10"], pattern=False)
    radio.offer(message(ctx, code="C-10", spec=spec), ctx)
    assert radio.select(ctx) is None
    assert any(e.get("reason") == reason for e in radio.log.events)


def test_coaching_needs_two_distinct_recent_clean_laps_and_meaningful_loss():
    ctx, radio = context(), Scheduler()
    for laps, loss in [((4, 4), .2), ((0, 1), .2), ((3, 4), .01)]:
        assert not radio.offer(message(ctx, code="C-10", evidence=Evidence("high", {}, laps, loss)), ctx)
    assert radio.offer(message(ctx, code="C-10", evidence=Evidence("medium", {}, (3, 4), .2)), ctx)
    assert play(radio, ctx).text.startswith("Looks like ")


def test_three_lap_coaching_budget_and_variant_rotation():
    ctx, radio = context(), Scheduler()
    m = message(ctx, code="C-10", corner="T9")
    radio.offer(m, ctx)
    first = play(radio, ctx)
    later = replace(ctx, t=200, lap=6)
    next_m = message(later, code="C-10", id="two", corner="T9",
                     evidence=Evidence("high", {}, (4, 5), .2, 1))
    radio.offer(next_m, later)
    assert radio.select(later) is None
    assert radio.log.events[-1]["reason"] == "coaching_budget"
    later = replace(ctx, t=300, lap=8)
    radio.offer(message(later, code="C-10", id="three", corner="T9",
                        evidence=Evidence("high", {}, (6, 7), .2, 1)), later)
    assert play(radio, later).text != first.text


def test_verbosity_quiet_laps_and_owner():
    ctx, radio = context(), Scheduler(Policy(mode="quiet"))
    radio.offer(message(ctx), ctx)
    assert radio.select(ctx) is None
    assert radio.log.events[-1]["reason"] == "verbosity"
    radio.policy.mode = "full"
    radio.quiet(ctx, 3)
    assert radio.select(ctx) is None
    assert radio.log.events[-1]["reason"] == "quiet_laps"
    cc_owned = replace(CATALOGUE["X-15"], owner="crew_chief")
    assert not radio.offer(message(ctx, id="cc", key="cc", spec=cc_owned), ctx)
    assert radio.log.events[-1]["reason"] == "crew_chief_owned"


def test_corner_note_waits_until_the_corner_has_passed():
    ctx, radio = context(), Scheduler()
    radio.offer(message(ctx, code="C-10", anchor_lap=5, available_after_distance=900), ctx)
    assert radio.select(ctx) is None
    assert radio.log.events[-1]["reason"] == "before_corner"
    assert play(radio, replace(ctx, distance=1000))


def test_logs_both_holds_and_decisions_without_20hz_spam(tmp_path):
    ctx = context(radio_busy=True)
    log = RadioLog(tmp_path / "radio.jsonl", limit=4)
    radio = Scheduler(log=log)
    radio.offer(message(ctx), ctx)
    for i in range(20):
        radio.select(replace(ctx, t=100+i*.05))
    assert log.counts["held"] == 1
    play(radio, replace(ctx, t=102, radio_busy=False))
    events = [json.loads(line) for line in log.path.read_text().splitlines()]
    assert [e["state"] for e in events] == ["queued", "held", "selected", "would_say"]
    assert events[-1]["evidence"]["values"]["observed_pit"] == 1


def test_queue_bound_keeps_more_urgent_information():
    ctx, radio = context(), Scheduler(Policy(max_pending=1))
    radio.offer(message(ctx, code="C-10"), ctx)
    radio.offer(message(ctx), ctx)
    assert list(radio.pending.values())[0].spec.code == "X-15"
    assert any(e.get("reason") == "priority_replacement" for e in radio.log.events)


def test_a_waiting_call_takes_a_tighter_spot_rather_than_none():
    # No learned straight long enough (a short track) and part throttle in a gentle bend.
    ctx, radio = context(window_s=1, throttle=.6, steering=.15), Scheduler()
    spec = replace(CATALOGUE["C-10"], pattern=False)
    radio.offer(message(ctx, code="C-10", spec=spec), ctx)
    assert radio.select(ctx) is None and radio.log.events[-1]["reason"] == "driving_workload"
    later = replace(ctx, t=ctx.t + radio.policy.relax_after_s)
    assert radio.select(replace(later, brake=.3)) is None          # never in a braking zone
    assert radio.select(replace(later, steering=.5)) is None       # nor a real corner
    assert play(radio, later).message.spec.code == "C-10"


def test_pit_lane_on_the_limiter_is_a_calm_spot():
    ctx, radio = context(pit=3, speed=16, throttle=.4, steering=.1, window_s=None), Scheduler()
    spec = replace(CATALOGUE["X-15"], urgency=2)
    radio.offer(message(ctx, spec=spec), ctx)
    assert play(radio, ctx).message.spec.code == "X-15"
