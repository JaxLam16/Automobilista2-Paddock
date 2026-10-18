"""Read-only, streaming test bench for the same decisions used by live coaching.

python -m ams2season.coach.replay RECORDING --root PADDOCK --speed 0
Speed0 is unpaced;1-20 reproduces session time at the requested wall-clock rate.
No speech is played, no Crew Chief connection is made, and source files are not edited.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import html
from itertools import groupby
import json
from pathlib import Path
import time
import uuid

from .engine import CoachEngine
from .model import finite
from .numbers import Numbers
from .radio import Policy, RadioLog, Scheduler
from .telemetry import from_recorded
from .apex import ApexMapStore,map_path
from .voice import text_key, tts_estimate


def sources(directory, kind):
    full = directory / (kind + ".parquet")
    if full.is_file():
        return [full]
    return sorted(p for p in (directory / (kind + "_parts")).glob("part-*.*")
                  if p.suffix in (".parquet", ".json"))


def rows(paths, desired):
    import pyarrow.parquet as pq
    last_t = float("-inf")
    for path in paths:
        if path.suffix == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            if "t" not in raw:
                raise ValueError("Recording has no sample timestamps: " + path.name)
            columns = [c for c in desired if c in raw]
            batches = [({c: raw[c][i] for c in columns} for i in range(min(map(len, raw.values()))))]
        else:
            file = pq.ParquetFile(path)
            available = file.schema_arrow.names
            if "t" not in available:
                raise ValueError("Recording has no sample timestamps: " + path.name)
            batches = (batch.to_pylist() for batch in file.iter_batches(
                batch_size=8192, columns=[c for c in desired if c in available]))
        for batch in batches:
            for row in batch:
                t = finite(row.get("t"))
                if t is None or t < last_t:
                    raise ValueError("Recording timestamps are invalid or out of order: " + path.name)
                last_t = t
                yield row


FRAME_COLS = ("t", "slot", "name", "car", "car_class", "race_pos", "laps_completed", "lap_dist",
              "speed", "pit_mode", "race_state", "lap_invalid", 'flag_colour','x','z','last_lap','pit_schedule','sector')
LOCAL_COLS = ("t", "game_state", "session_state", "viewed_slot", "speed", "throttle", "brake", "steering", "gear",
              "rain_density", "crash_state", "local_lap_invalid", "fuel_level", "fuel_capacity", 'yellow_flag_state',
              'event_time_remaining_ms', 'compound', 'water_temp', 'oil_temp', 'aero_damage',
              'spotter_yaw', 'world_vx', 'world_vz',
              'pit_schedule','local_race_state','highest_flag_colour',
              *(f'{k}_{w}' for k in ('tl', 'tc', 'tr', 'ttemp', 'btemp') for w in ('fl', 'fr', 'rl', 'rr')))


def ticks(directory, meta):
    local_rows = iter(rows(sources(directory, "local"), LOCAL_COLS))
    following = next(local_rows, None)
    current = None
    for t, group in groupby(rows(sources(directory, "frames"), FRAME_COLS), key=lambda r: float(r["t"])):
        while following is not None and following["t"] <= t:
            current, following = following, next(local_rows, None)
        yield from_recorded(meta, list(group), current, directory.name, t)


def fingerprint(path):
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    stat = path.stat()
    return {"file": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest.hexdigest()}


def explain_result(engine, counts, events):
    capabilities=engine['capabilities']
    diagnostics=engine['diagnostics']
    calls=counts.get('would_say',0)
    if calls:
        reason=f'{calls} simulated call'+('s' if calls!=1 else '')+' from the implemented rules.'
        code='calls_generated'
    elif not diagnostics.get('active_ticks'):
        reason='No usable in-car telemetry matched the selected driver. Check the exact local driver name and pause/replay/spectator state.'
        code='no_active_telemetry'
    elif any(diagnostics.get(key) for key in ('fuel_call_candidates','confirmed_gap_trends',
            'confirmed_ahead_gap_trends','confirmed_apex_patterns','confirmed_corner_speed_patterns','confirmed_early_brake_patterns',
            'confirmed_section_losses','confirmed_offtrack_warnings')):
        held=Counter(e.get('reason') for e in events if e['state']=='held' and e.get('reason'))
        detail=', '.join(key.replace('_',' ') for key,_ in held.most_common(3))
        label='Section-loss' if diagnostics.get('confirmed_section_losses') else 'Running-wide' if diagnostics.get('confirmed_offtrack_warnings') else 'Earlier-brake-input' if diagnostics.get('confirmed_early_brake_patterns') else 'Corner-speed' if diagnostics.get('confirmed_corner_speed_patterns') else 'Mapped-apex' if diagnostics.get('confirmed_apex_patterns') else 'Fuel-use' if diagnostics.get('fuel_call_candidates') else 'Measured gap-trend'
        reason=label+' candidates were generated but none reached a simulated delivery.'+(' Holds: '+detail+'.' if detail else ' See the evidence timeline for dropped calls.')
        code='calls_withheld'
    elif not diagnostics.get('active_race_ticks'):
        if diagnostics.get('active_practice_ticks'):
            reason='No practice fuel-use calibration qualified. It needs three full clean measured laps with consistent consumption and known fuel/flag channels. Rival/pit calls apply only to races.'
            clean=engine.get('fuel',{}).get('diagnostics',{}).get('clean_lap_samples',0)
            reason+=f' {clean} full clean fuel intervals were measured overall; menus, refuelling or capture interruptions can restart calibration.'
            code='insufficient_fuel_evidence'
            apex=engine.get('apex',{})
            reason+=' Mapped apex checks: '+str(apex.get('map_reason') if apex.get('map_reason')!='mapped' else apex.get('reason','learning')).replace('_',' ')+'.'
            if apex.get('map_reason')=='mapped':
                reason+=f" {apex.get('clean_intervals_completed',0)} clean full-lap intervals checked; a pattern needs two earlier reference intervals and three recent eligible intervals."
            speed=engine.get('corner_speed',{})
            reason+=f" Corner-speed checks: {speed.get('clean_intervals_completed',0)} clean full-lap intervals; five are needed for earlier references and a repeated pattern."
            braking=engine.get('braking',{})
            reason+=' Brake-input checks: '+str(braking.get('comparison_reason','learning')).replace('_',' ')+'.'
            sections=engine.get('sections',{})
            reason+=' Section-loss checks: '+str(sections.get('reason','learning')).replace('_',' ')+'.'
        else:
            reason='Implemented calls currently cover races and selected practice measurements. In qualifying only running-wide warnings apply, and none was confirmed: that needs the same spot on two of the last three laps with the lap still valid.'
            code='no_applicable_rules'
    elif not diagnostics.get('racing_pit_entry_samples'):
        reason='No car showed pit entry during active racing. No reliable gap trend was confirmed either, so no call candidates were generated.'
        behind=engine.get('gap_diagnostics',{}).get('matched_gap_samples',0)
        ahead=engine.get('ahead_gap_diagnostics',{}).get('matched_gap_samples',0)
        reason+=f' Gap checks matched {ahead} ahead and {behind} behind timing samples; a trend needs three consecutive comparisons with the same rival and uninterrupted valid telemetry.'
        code='no_pit_entry_samples'
    elif not diagnostics.get('observed_relevant_pit_entries'):
        reason='Pit data was present, but no sustained entry by the current same-class car ahead, car behind or class leader was confirmed.'
        code='no_relevant_pit_entry'
    else:
        held=Counter(e.get('reason') for e in events if e['state']=='held' and e.get('reason'))
        detail=', '.join(key.replace('_',' ') for key,_ in held.most_common(3))
        reason='Pit-entry candidates were generated but none reached a simulated delivery.'+(' Holds: '+detail+'.' if detail else ' See the evidence timeline for dropped calls.')
        code='calls_withheld'
    if not calls and diagnostics.get('confirmed_fuel_calibrations') and not diagnostics.get('fuel_call_candidates'):
        reason+=' A fuel measurement is available in the evidence log; basic fuel-remaining speech stays with Crew Chief.'
    return {'code':code,'text':reason,'capabilities':capabilities}


def write_report(directory, report, events):
    (directory / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    esc = lambda value: html.escape(str(value if value is not None else ""))
    table = []
    for event in events:
        table.append("<tr><td>" + esc(round(event["t"], 2)) + "</td><td>" + esc(event["lap"]) + "</td><td>"
                     + esc(event.get("code")) + "</td><td>" + esc(event["state"]) + "</td><td>"
                     + esc(event.get("text") or event.get("reason")) + "</td><td><details><summary>Evidence</summary><pre>"
                     + esc(json.dumps(event.get("evidence", {}), indent=2, ensure_ascii=False)) + "</pre></details></td></tr>")
    race = report['engine'].get('race_length',{})
    race_value = race.get('current') or race.get('last_estimate')
    race_text = ''
    if race_value:
        race_text = ('<p>Overall leader finish: '+esc(race_value['state'].replace('_',' '))+' lap '
                     +esc(race_value['finish_lap_low'])+'–'+esc(race_value['finish_lap_high'])
                     +(' (historical reading)' if not race.get('current') else '')
                     +'. This is not your personal finish lap or a fuel-to-finish plan.</p>')
    content = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
               "<title>Paddock private coach replay</title><style>body{background:#151b22;color:#edf0f4;font:15px system-ui;margin:24px}"
               "table{width:100%;border-collapse:collapse}td,th{padding:9px;text-align:left;border-bottom:1px solid #38404a}"
               "pre{white-space:pre-wrap;max-width:440px}section{max-width:1300px;margin:auto}</style><section>"
               "<h1>Private coach replay</h1><p>Simulated decisions only. No audio was played or sent to Crew Chief. "
               "Radio activity was assumed idle for this offline test. Each decision uses current and earlier samples only.</p><p>"
               + ('Selected cached voice inventory checked; missing exact phrases remain silent.' if report.get('speech_simulation')=='cached_voice'
                  else 'Selected cached voice checked; phrases without a recording use an estimated Crew Chief text-to-speech length.'
                  if report.get('speech_simulation')=='cached_voice_with_tts'
                  else 'Text preview only; cached voice availability was not tested.') + '</p><p>'
               + esc(report["recording"]) + " · " + esc(report["driver"]) + " · " + esc(report["ticks"]) + " samples</p><p>"
               + esc(report['explanation']['text']) + '</p><p>Development preview. Implemented: '
               + esc(', '.join(x['label'] for x in report['explanation']['capabilities']['implemented_rules']))
               + '. Still being built: '+esc(', '.join(report['explanation']['capabilities']['not_yet_available']))+'</p><p>'
               + esc(report["counts"]) + "</p>"+race_text+"<table><thead><tr><th>Time (s)</th><th>Lap</th><th>ID</th><th>Decision</th>"
               "<th>Call or reason</th><th>Numbers behind it</th></tr></thead><tbody>" + "".join(table) + "</tbody></table></section>")
    (directory / "review.html").write_text(content, encoding="utf-8")


def run_replay(recording, root, *, driver=None, speed=0, mode="full", units=None, stop=None, progress=None,
               voice_durations=None, voice_id=None, tts_fallback=False, practice_plans=None, spotter_enabled=False,
               crew_engine_enabled=False):
    recording, root = Path(recording).resolve(), Path(root).resolve()
    if speed != 0 and not 1 <= speed <= 20:
        raise ValueError("Replay speed must be0 (unpaced) or1-20.")
    meta = json.loads((recording / "session.json").read_text(encoding="utf-8"))
    if meta.get("status") == "recording":
        raise ValueError("Wait until the recording has finished before replaying its coaching.")
    driver = (driver or (meta.get("local") or {}).get("name") or "").strip()
    if not driver:
        raise ValueError("The recording has no local driver name. Select the exact driver.")
    if not sources(recording, "frames") or not sources(recording, "local"):
        raise ValueError("Coaching replay needs both all-car and local telemetry.")
    target = root / "private_coach" / "replays" / uuid.uuid4().hex
    if target.is_relative_to(recording):
        raise ValueError("Replay results must be outside the original recording.")
    inputs = [recording / "session.json", *sources(recording, "frames"), *sources(recording, "local")]
    edge_map=map_path(root,meta.get('track_location',''),meta.get('track_variation',''))
    if edge_map.is_file() and not edge_map.is_symlink() and edge_map.resolve().parent==(root/'tracks').resolve():
        inputs.append(edge_map)
    before = [fingerprint(path) for path in inputs]
    target.mkdir(parents=True, exist_ok=False)
    log = RadioLog(target / "radio.jsonl")
    apex_store=ApexMapStore(root,frozen=True)
    apex_store.load(meta.get('track_location',''),meta.get('track_variation',''),finite(meta.get('track_length'),0))
    def duration(text):
        # Pinned recorded inventory; a missing phrase is silent unless Crew Chief TTS reads it.
        seconds = voice_durations(text) if callable(voice_durations) else voice_durations.get(text_key(text))
        return tts_estimate(text) if seconds is None and tts_fallback else seconds
    if voice_durations is None:
        duration = None
    program = None
    if practice_plans is not None:
        # Offline bench for the practice programme: these R&D plans stand in for the
        # championship lookup. With no reply, the detected goal is used, as live.
        from .program import PracticeProgram
        from ..engineer.catalog import BY_KEY
        program = PracticeProgram(Numbers(units), plan_lookup=lambda *args: list(practice_plans), settings=BY_KEY)
    engine = CoachEngine(driver, Scheduler(Policy(mode=mode), log,voice_duration=duration),numbers=Numbers(units),apex_store=apex_store,
                         program=program)
    first_t, latest_t, first_wall, processed = None, None, time.monotonic(), 0
    events = []
    from .crew_spotter import Spotter, WORDS
    spotter = Spotter() if spotter_enabled else None
    spotter_calls, spotter_inputs = 0, 0
    from .crew_engine import EngineMonitor
    cc_engine = EngineMonitor() if crew_engine_enabled else None
    from .crew_events import Events
    cc_events = Events(root=root) if crew_engine_enabled else None
    cc_engine_calls, cc_engine_inputs = 0, 0
    penalty_calls, penalty_inputs, penalty_requested, penalty_withdrawn = 0,0,0,0
    flag_calls, flag_inputs, flag_requested, flag_withdrawn = 0,0,0,0
    penalty_pending = []
    if cc_engine:
        cc_engine.start()
        cc_engine.ready.wait(10)
        engine.original_engine_monitor = cc_engine.ready.is_set()
        cc_events.start()
        cc_events.ready.wait(10)
        engine.original_penalties=cc_events.ready.is_set()
    try:
        for tick in ticks(recording, meta):
            if stop is not None and stop.is_set():
                raise InterruptedError("Replay stopped. Its original recording is unchanged.")
            if first_t is None:
                first_t = tick.t
            if speed:
                delay = first_wall + (tick.t-first_t)/speed - time.monotonic()
                while delay > 0:
                    if stop is not None:
                        if stop.wait(min(delay, 1)):
                            raise InterruptedError("Replay stopped.")
                    else:
                        time.sleep(min(delay, 1))
                    delay = first_wall + (tick.t-first_t)/speed - time.monotonic()
            delivery = engine.feed(tick, radio_busy=False)
            if cc_engine:
                if cc_engine.available(tick, tick.player(driver)) and all(
                        finite(tick.local.get(k)) is not None for k in ('oil_c','water_c','speed')):
                    cc_engine_inputs += 1
                for call in cc_engine.feed(tick, tick.player(driver),fahrenheit=engine.numbers.units.temperature=='f'):
                    cc_engine_calls += 1
                    log.record('would_say',engine.context,code='CC-ENGINE',text=call['folder'],
                        sound_folder=call['folder'],simulated=True,audio_played=False,
                        transcript='Original sound request; variants resolved from local subtitles at playback',
                        evidence={'source':'Crew Chief 4.19.5.4 original EngineMonitor',**call})
            if cc_events:
                requests=cc_events.feed(tick,tick.player(driver))
                if cc_events.last_payload is not None and cc_events.last_payload['penalties_available']: penalty_inputs+=1
                if cc_events.last_payload is not None and cc_events.last_payload['flag_colour'] in range(12): flag_inputs+=1
                for call in requests:
                    is_flag=call.get('source_event')=='FlagsMonitor_4.19.5.4'
                    if is_flag: flag_requested+=1
                    else: penalty_requested+=1
                    penalty_pending.append({**call,'available_at':tick.t+call['delay_s'],
                        'expires':tick.t+call['expires_s'] if call['expires_s'] else None})
                    log.record('crew_chief_requested',engine.context,code='CC-FLAGS' if is_flag else 'CC-PENALTIES',text=call['folder'],
                               evidence=call,simulated=True,audio_played=False)
                valid=[c for c in penalty_pending if cc_events.valid_call(c['native_id'])
                       and (c['expires'] is None or tick.t<c['expires'])]
                removed=[c for c in penalty_pending if c not in valid]
                flag_withdrawn+=sum(c.get('source_event')=='FlagsMonitor_4.19.5.4' for c in removed)
                penalty_withdrawn+=sum(c.get('source_event')!='FlagsMonitor_4.19.5.4' for c in removed)
                penalty_pending=valid
                eligible=[c for c in valid if tick.t>=c['available_at']]
                if eligible:
                    call=max(eligible,key=lambda c:(c['immediate'],c['priority']))
                    penalty_pending.remove(call)
                    cc_events.acknowledge(call['native_id'])
                    is_flag=call.get('source_event')=='FlagsMonitor_4.19.5.4'
                    if is_flag: flag_calls+=1
                    else: penalty_calls+=1
                    log.record('would_say',engine.context,code='CC-FLAGS' if is_flag else 'CC-PENALTIES',text=call['folder'],
                        sound_folder=call['folder'],simulated=True,audio_played=False,
                        transcript='Original sound request; local subtitle variant resolved at playback',evidence=call)
            if spotter is not None:
                if tick.local.get('orientation_yaw') is not None and all(v is not None for v in tick.local.get('world_velocity', ())):
                    spotter_inputs += 1
                    if spotter_inputs == 1:
                        spotter.start()
                        spotter.ready.wait(10)
                for call in spotter.feed(tick, tick.player(driver)):
                    spotter_calls += 1
                    log.record('would_say', engine.context, code='CC-SPOTTER',
                        text=WORDS[call['folder'].split('/')[-1]], sound_folder=call['folder'],
                        simulated=True, audio_played=False, transcript='logical label; recorded variants differ',
                        evidence={'source':'Crew Chief 4.19.5.4 original spotter', **call})
            if delivery:
                engine.radio.acknowledge(delivery, engine.context, accepted=True, simulated=True)
            latest_t, processed = tick.t, processed+1
            if progress is not None and processed % 1000 == 0:
                progress({"ticks": processed, "time_s": tick.t, "learned_laps": engine.status()["learned_laps"]})
        # Flush otherwise-still-pending notes to an explicit terminal decision.
        if engine.context:
            engine.context = replace(engine.context, active=False, reason="recording_ended")
            engine.radio.advance(engine.context)
        after = [fingerprint(path) for path in inputs]
        if before != after:
            raise ValueError("The recording changed during replay. Results are not a verified pass.")
        events = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()] if log.path.exists() else []
        report = {"version": 1, "private": True, "simulated": True, "audio_played": False,
                  "radio_assumption": "idle for offline simulation only", "recording": recording.name,
                  "driver": driver, "ticks": processed, "first_t": first_t, "last_t": latest_t,
                  "wall_seconds": time.monotonic()-first_wall, "speed": speed,
                  'units':asdict(engine.numbers.units),'mode':mode,
                  'speech_simulation':('cached_voice_with_tts' if tts_fallback else 'cached_voice') if voice_durations is not None else 'text_preview',
                  'voice_id':voice_id if voice_durations is not None else None,
                  'spotter': {'enabled': spotter_enabled, 'calls': spotter_calls,
                              'input_samples': spotter_inputs, 'error': spotter.error if spotter else None,
                              'status': 'disabled' if not spotter else 'missing_heading_or_world_velocity'
                                  if not spotter_inputs else 'host_error' if spotter.error else 'simulated'},
                  'crew_chief_engine': {'enabled':crew_engine_enabled,'calls':cc_engine_calls,
                      'input_samples':cc_engine_inputs,'error':cc_engine.error if cc_engine else None,
                      'status':'disabled' if not cc_engine else 'host_error' if cc_engine.error else
                          'missing_temperature_telemetry' if not cc_engine_inputs else 'simulated',
                      'scope':'Original temperature monitoring; pressure and stalled unavailable'},
                  'crew_chief_penalties':{'enabled':crew_engine_enabled,'calls':penalty_calls,
                      'requested':penalty_requested,'withdrawn':penalty_withdrawn,'input_samples':penalty_inputs,
                      'error':cc_events.error if cc_events else None,
                      'status':'disabled' if not cc_events else 'host_error' if cc_events.error else
                          'missing_pit_schedule_or_sector' if not penalty_inputs else 'simulated'},
                  'crew_chief_flags':{'enabled':crew_engine_enabled,'calls':flag_calls,
                      'requested':flag_requested,'withdrawn':flag_withdrawn,'input_samples':flag_inputs,
                      'error':cc_events.error if cc_events else None,
                      'status':'disabled' if not cc_events else 'host_error' if cc_events.error else
                          'missing_flag_colour_or_event_inputs' if not flag_inputs else 'simulated',
                      'scope':'Original AMS2 local flag calls; landmark incidents/full mapper pending'},
                  "counts": dict(log.counts), "reasons": dict(Counter(e.get("reason") for e in events if e.get("reason"))),
                  "inputs_unchanged": True, "inputs": before, "engine": engine.status(),
                  "review": str(target / "review.html"), "directory": str(target)}
        report['explanation'] = explain_result(report['engine'],report['counts'],events)
        if spotter_enabled and not spotter_inputs:
            report['explanation']['text'] += ' Original Crew Chief spotter unavailable: this older recording lacks the exact local heading or world velocity. New recordings now capture these channels.'
        write_report(target, report, events)
        return report
    except Exception as exc:
        (target / "failure.json").write_text(json.dumps({"error": str(exc), "ticks": processed}), encoding="utf-8")
        raise
    finally:
        if spotter is not None:
            spotter.close()
        if cc_engine is not None:
            cc_engine.close()
        if cc_events is not None:
            cc_events.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--driver")
    parser.add_argument("--speed", type=float, default=0)
    parser.add_argument("--mode", default="full", choices=("full", "race", "quiet", "coach", "silent"))
    parser.add_argument('--crew-engine',action='store_true',help='Silently simulate original temperature, penalty and flag events')
    args = parser.parse_args()
    report = run_replay(args.recording, args.root, driver=args.driver, speed=args.speed, mode=args.mode,
                        crew_engine_enabled=args.crew_engine)
    print(json.dumps({k: report[k] for k in ("ticks", "counts", "inputs_unchanged", "review")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
