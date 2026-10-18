"""One-use local audio tickets, claimed only while the advice is still valid."""
from __future__ import annotations

from dataclasses import dataclass
import re
import secrets
import time

from .voice import Clip, silence_wav, text_key


SILENCE = silence_wav()
TICKET_PATH = re.compile(r"^/api/coach/audio/([a-f0-9]{48})\.wav$")


@dataclass
class Ticket:
    token: str
    delivery: object
    clip: Clip
    deadline: float
    context_t: float
    state: str = "issued"
    reason: str | None = None
    spoken_text: str | None = None  # text-to-speech: matched against CC's subtitle, no clip

    @property
    def seconds(self):
        return self.clip.seconds if self.clip else self.delivery.seconds


class AudioTickets:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.pending: Ticket | None = None
        self.observing: Ticket | None = None
        self.observed_start = None
        self.observed_sequence = None

    def issue(self, delivery, clip, ctx):
        if self.pending:
            raise ValueError("A private voice call is already awaiting playback.")
        if abs(delivery.seconds-clip.seconds) > .03:
            raise ValueError("The queued duration does not match its cached voice.")
        ticket = Ticket(secrets.token_hex(24), delivery, clip,
                        self.clock()+max(0, min(10, delivery.expires-ctx.t)), ctx.t)
        self.pending = ticket
        return ticket

    @staticmethod
    def path(ticket):
        return "/api/coach/audio/"+ticket.token+".wav"

    def watch_speech(self, delivery, ctx, radio):
        """Follow a text-to-speech call in Crew Chief's SDK. Sending it is not proof it was heard."""
        if self.observing:
            radio.log_delivery("playback_unconfirmed", ctx, self.observing.delivery,
                               "next_call_sent_without_end_observation")
        self.observing = Ticket("", delivery, None, self.clock()+max(0, min(10, delivery.expires-ctx.t)),
                                ctx.t, state="sent", spoken_text=text_key(delivery.text))
        self.observed_start = self.observed_sequence = None

    def cancel(self, radio, ctx, reason):
        ticket = self.pending
        if not ticket:
            return
        self.pending = None
        ticket.state, ticket.reason = "dropped", reason
        if radio.delivering == ticket.delivery:
            radio.acknowledge(ticket.delivery, ctx, accepted=False)
        radio.log_delivery("audio_withheld",ctx,ticket.delivery,reason)

    def sweep(self, radio, ctx):
        ticket = self.pending
        if ticket:
            reason = radio.invalid_delivery(ticket.delivery, ctx)
            if self.clock() >= ticket.deadline:
                reason = "expired_before_fetch"
            if radio.delivering != ticket.delivery:
                reason = "delivery_cancelled"
            if not ctx.active:
                reason = ctx.reason
            if reason:
                self.cancel(radio, ctx, reason)

    def claim(self, token, radio, ctx, *, age_s):
        ticket = self.pending
        if ticket is None or not secrets.compare_digest(token, ticket.token):
            return SILENCE
        reason = radio.delivery_reason(ticket.delivery, ctx)
        if not 0 <= age_s <= .25:
            reason = "telemetry_stale_at_fetch"
        if self.clock() >= ticket.deadline:
            reason = "expired_before_fetch"
        if reason:
            self.cancel(radio, ctx, reason)
            return SILENCE
        self.pending = None
        if not radio.acknowledge(ticket.delivery, ctx, accepted=True):
            return SILENCE
        ticket.state = "served"
        if self.observing:
            radio.log_delivery("playback_unconfirmed", ctx, self.observing.delivery,
                             "next_clip_requested_without_end_observation")
        self.observing = ticket
        self.observed_start = self.observed_sequence = None
        radio.log_delivery("audio_served", ctx, ticket.delivery,
                         sha256=ticket.clip.sha256, seconds=ticket.clip.seconds)
        # No 'heard' claim: this is proof of transfer into CC, not listening.
        return ticket.clip.data

    def observe(self, state, radio, ctx):
        ticket = self.observing
        if not ticket:
            return
        if self.clock() > ticket.deadline+ticket.seconds+2:
            radio.log_delivery("playback_unconfirmed", ctx, ticket.delivery,
                             "radio_end_not_observed" if self.observed_start is not None else "no_sdk_playback_observation")
            self.observing = None
            return
        if not state.get("available"):
            return
        phrase = state.get("phrase", "")
        if ticket.spoken_text is not None:
            ours = bool(phrase) and text_key(phrase) == ticket.spoken_text
        else:
            ours = phrase.endswith(self.path(ticket))
        if ours and state.get("busy") is True and self.observed_start is None:
            self.observed_start, self.observed_sequence = self.clock(), state.get("sequence")
            radio.log_delivery("radio_observed", ctx, ticket.delivery, source="crew_chief_sdk",
                             scope="channel_and_matching_subtitle", heard=False)
        elif self.observed_start is not None:
            interrupted = state.get("busy") is True and not ours
            finished = state.get("busy") is False
            if interrupted or finished:
                radio.log_delivery("radio_interrupted" if interrupted else "radio_closed", ctx,
                                   ticket.delivery,source="crew_chief_sdk",heard=False)
                self.observing = None
