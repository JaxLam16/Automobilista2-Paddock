"""Cached private speech, truthful durations and last-moment cancellation."""
from dataclasses import replace
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import wave

import pytest

from ams2season.coach.audio import AudioTickets, SILENCE
from ams2season.coach.crew_sdk import CrewChiefObserver, decode
from ams2season.coach.radio import Scheduler
from ams2season.coach.voice import VoiceCache, wav_duration
from test_coach_radio import context, message


def audio(seconds=1.5, rate=22050):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(b"".join(struct.pack("<h", int(3000*math.sin(i*.2))) for i in range(int(seconds*rate))))
    return output.getvalue()


def voice_batch(root, texts=None):
    directory = root / "private_coach" / "samples"
    directory.mkdir(parents=True)
    data = audio()
    (directory / "sample.wav").write_bytes(data)
    manifest = {"private": True, "publish_allowed": False, "clips": [
        {"id": str(i), "text": text, "radio": "sample.wav", "seconds": 1.5,
         "radio_sha256": hashlib.sha256(data).hexdigest()} for i, text in enumerate(texts or ["The car ahead is pitting."])]}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return directory, manifest


def test_private_cache_matches_exact_wording_and_uses_real_wav_length(tmp_path):
    voice_batch(tmp_path)
    cache = VoiceCache(tmp_path)
    clip = cache.get("THE CAR AHEAD IS PITTING")
    assert clip.seconds == 1.5 and wav_duration(clip.data) == 1.5
    assert cache.get("The car ahead is not pitting.") is None
    assert cache.get("Looks like the car ahead is pitting.") is None
    assert cache.status()["clips"] == 1 and not cache.errors


@pytest.mark.parametrize("fault", ["path", "checksum", "duration", "public", "bad_wav", "nan_duration"])
def test_bad_voice_batches_fail_closed_without_touching_originals(tmp_path, fault):
    directory, manifest = voice_batch(tmp_path)
    original = (directory / "sample.wav").read_bytes()
    if fault == "path":
        manifest["clips"][0]["radio"] = "../../../outside.wav"
    if fault == "checksum":
        manifest["clips"][0]["radio_sha256"] = "0"*64
    if fault == "duration":
        manifest["clips"][0]["seconds"] = 2.5
    if fault == "public":
        manifest["private"] = False
    if fault == 'bad_wav':
        original=b'RIFF\0\0'
        (directory/'sample.wav').write_bytes(original)
        manifest['clips'][0]['radio_sha256']=hashlib.sha256(original).hexdigest()
    if fault == 'nan_duration':
        manifest['clips'][0]['seconds']=float('nan')
    (directory / "manifest.json").write_text(json.dumps(manifest))
    cache = VoiceCache(tmp_path)
    assert cache.status()["clips"] == 0 and cache.errors
    assert (directory / "sample.wav").read_bytes() == original


def test_voice_change_after_indexing_is_detected_before_dispatch(tmp_path):
    directory, _ = voice_batch(tmp_path)
    cache = VoiceCache(tmp_path)
    (directory / "sample.wav").write_bytes(audio(.5))
    with pytest.raises(ValueError, match="changed"):
        cache.get("The car ahead is pitting.")


def selected_voice(tmp_path):
    voice_batch(tmp_path)
    cache = VoiceCache(tmp_path)
    radio, ctx = Scheduler(voice_duration=cache.duration), context(window_s=2.1)
    radio.offer(message(ctx), ctx)
    selected = radio.select(ctx)
    assert selected is not None and selected.seconds == 1.5
    return cache, radio, ctx, selected


def test_actual_clip_duration_controls_window_and_unavailable_variants_wait(tmp_path):
    cache, radio, ctx, selected = selected_voice(tmp_path)
    assert selected.text == "The car ahead is pitting."
    empty = Scheduler(voice_duration=lambda _: None)
    empty.offer(message(ctx), ctx)
    assert empty.select(ctx) is None
    assert empty.log.events[-1]["reason"] == "voice_clip_missing"


def test_one_cached_variant_does_not_repeat_until_an_alternative_is_available(tmp_path):
    cache,radio,ctx,selected=selected_voice(tmp_path)
    assert radio.acknowledge(selected,ctx,accepted=True)
    ctx=replace(ctx,t=ctx.t+40,lap=ctx.lap+1)
    radio.offer(message(ctx,id='second'),ctx)
    assert radio.select(ctx) is None
    assert radio.log.events[-1]['reason']=='voice_variant_missing'
    # New variant uses its own exact duration; no repeated-text fallback.
    radio.voice_duration=lambda text:1.5 if text in (selected.text,'The car ahead is entering the pits.') else None
    alternate=radio.select(ctx)
    assert alternate.text=='The car ahead is entering the pits.'


def test_missing_sdk_after_transfer_is_eventually_logged_as_unconfirmed(tmp_path):
    cache,radio,ctx,selected=selected_voice(tmp_path)
    now=[0]
    broker=AudioTickets(clock=lambda:now[0])
    ticket=broker.issue(selected,cache.get(selected.text),ctx)
    broker.claim(ticket.token,radio,ctx,age_s=0)
    now[0]=20
    broker.observe({'available':False,'busy':None},radio,replace(ctx,t=ctx.t+20))
    assert broker.observing is None
    assert radio.log.events[-1]['state']=='playback_unconfirmed'
    assert not any(e['state']=='heard' for e in radio.log.events)


def test_one_use_ticket_serves_verified_pcm_without_claiming_heard(tmp_path):
    cache, radio, ctx, selected = selected_voice(tmp_path)
    broker = AudioTickets(clock=lambda: 0)
    ticket = broker.issue(selected, cache.get(selected.text), ctx)
    data = broker.claim(ticket.token, radio, ctx, age_s=.05)
    assert data == cache.get(selected.text).data and data != SILENCE
    assert broker.claim(ticket.token, radio, ctx, age_s=.05) == SILENCE
    assert radio.log.events[-1]["state"] == "audio_served"
    assert not any(e["state"] == "heard" for e in radio.log.events)


@pytest.mark.parametrize("fault", ["expired", "passed", "braking", "paused", "stale", "window_closed", "quiet"])
def test_fetch_rechecks_conditions_when_cc_was_delayed(tmp_path, fault):
    cache, radio, ctx, selected = selected_voice(tmp_path)
    now = [0.]
    broker = AudioTickets(clock=lambda: now[0])
    ticket = broker.issue(selected, cache.get(selected.text), ctx)
    age = .01
    if fault == "expired":
        now[0] = 11
    if fault == "passed":
        ctx = replace(ctx, facts={"pit:a": 3})
    if fault == "braking":
        ctx = replace(ctx, brake=.8)
    if fault == "paused":
        ctx = replace(ctx, active=False, reason="paused")
    if fault == "stale":
        age = .5
    if fault == "window_closed":
        ctx = replace(ctx, window_s=1)
    if fault == "quiet":
        radio.quiet(ctx)
    assert broker.claim(ticket.token, radio, ctx, age_s=age) == SILENCE
    assert not radio.per_lap and radio.delivering is None
    assert radio.log.events[-1]["state"] == "audio_withheld"


def test_sdk_playback_observation_is_distinct_from_download_and_yields_to_spotter(tmp_path):
    cache, radio, ctx, selected = selected_voice(tmp_path)
    broker = AudioTickets(clock=lambda: 0)
    ticket = broker.issue(selected, cache.get(selected.text), ctx)
    broker.claim(ticket.token, radio, ctx, age_s=.05)
    state = {"available": True, "busy": True, "phrase": "http://127.0.0.1:8642"+broker.path(ticket), "sequence": 7}
    broker.observe(state, radio, ctx)
    assert radio.log.events[-1]["state"] == "radio_observed"
    assert radio.log.events[-1]["heard"] is False
    broker.observe({**state, "phrase": "Car right", "voice_type": 1, "sequence": 8}, radio, ctx)
    assert radio.log.events[-1]["state"] == "radio_interrupted"


def sdk_bytes(tick=1, playing=False, status=2):
    definitions = [("updateStatus", 3, 4, 1), ("tickRate", 3, 4, 1), ("tickCount", 3, 4, 1),
        ("numTotalPhrases", 3, 4, 1), ("lastPhraseIndex", 3, 4, 1), ("phraseSequenceIds", 3, 4, 10),
        ("phrasesVoiceType", 3, 4, 10), ("phrasePhrases", 8, 8192, 10), ("phraseIsPlaying", 1, 1, 1)]
    buffer = 16 + 400*len(definitions)
    data = bytearray(500000)
    struct.pack_into("<4i", data, 0, 1, len(definitions), 16, buffer)
    pos = 0
    for i, (name, kind, width, count) in enumerate(definitions):
        at = 16+i*400
        struct.pack_into("<4i", data, at, kind, width, pos, count)
        encoded = name.encode("utf-16-le")
        data[at+16:at+16+len(encoded)] = encoded
        value = {"updateStatus": status, "tickRate": 50, "tickCount": tick, "numTotalPhrases": 1,
                 "lastPhraseIndex": 0, "phraseSequenceIds": 8, "phrasesVoiceType": 1}.get(name)
        if value is not None:
            struct.pack_into("<i", data, buffer+pos, value)
        if name == "phraseIsPlaying":
            data[buffer+pos] = int(playing)
        if name == "phrasePhrases":
            text = "Car right".encode("utf-16-le")
            data[buffer+pos:buffer+pos+len(text)] = text
        pos += width*count
    return bytes(data)


def test_sdk_dynamic_layout_busy_state_and_stale_mapping_are_not_assumed_idle():
    class Reader:
        data = sdk_bytes()
        def read(self): return self.data
        def close(self): pass
    reader, now = Reader(), [0.]
    observer = CrewChiefObserver(reader, lambda: now[0])
    assert observer.poll()["busy"] is None  # Need a progressing heartbeat.
    reader.data = sdk_bytes(2, True)
    assert observer.poll()["busy"] is True
    assert observer.value["voice_type"] == 1 and observer.value["phrase"] == "Car right"
    now[0] = 2
    assert observer.poll()["busy"] is None
    reader.data = sdk_bytes(3, False)
    assert observer.poll()["busy"] is False
    reader.data = None
    assert observer.poll()["busy"] is None


def test_bad_sdk_offsets_and_versions_are_rejected():
    for position, value in ((0, 2), (4, 500000), (12, -1), (16+8, 999999)):
        data = bytearray(sdk_bytes())
        struct.pack_into("<i", data, position, value)
        with pytest.raises(ValueError):
            decode(data)


def test_live_log_can_defer_disk_io_until_outside_the_audio_fetch(tmp_path):
    from ams2season.coach.radio import RadioLog
    log = RadioLog(tmp_path/'radio.jsonl', deferred=True)
    log.record('audio_served', context(), message())
    assert not log.path.exists()
    log.flush()
    assert json.loads(log.path.read_text())['state'] == 'audio_served'


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows named mapping')
def test_sdk_native_mapping_is_read_only_and_missing_mapping_is_never_created():
    import ctypes as C
    import uuid
    from ams2season.coach.crew_sdk import ReadOnlyMapping, SIZE
    name = 'Local\\PaddockSyntheticSDK-'+uuid.uuid4().hex
    reader = ReadOnlyMapping(name)
    assert reader.read() is None
    assert not reader.k32.OpenFileMappingW(4, False, name)
    k32 = reader.k32
    k32.CreateFileMappingW.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32, C.c_wchar_p]
    k32.CreateFileMappingW.restype = C.c_void_p
    handle = k32.CreateFileMappingW(C.c_void_p(-1), None, 4, 0, SIZE, name)
    assert handle
    view = k32.MapViewOfFile(handle, 2, 0, 0, SIZE)
    try:
        assert view
        payload = sdk_bytes(5, True)
        C.memmove(view, payload, len(payload))
        assert decode(reader.read())['playing'] is True
    finally:
        reader.close()
        if view: k32.UnmapViewOfFile(view)
        k32.CloseHandle(handle)
