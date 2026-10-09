"""Finite, evidence-backed driver profiles and comparable per-race season history."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .legends import DIMENSIONS, LEGENDS, match, scores_from_raw
from .season import driver_colors, rounds_summary
from .race import _norm
from .weekends import connection

VERSION = 5


def finite(value):
    return None if value is None or isinstance(value, bool) or not isinstance(value, (int, float, np.number)) or not math.isfinite(value) else float(value)


def mean(values):
    numbers = [finite(x) for x in values]
    numbers = [x for x in numbers if x is not None]
    return float(np.mean(numbers)) if numbers else None


def measurements(ra):
    from .errors import race_errors
    from .metrics import race_pace
    from .overtakes import overtaking
    st = ra.stats.set_index('name')
    field = finite(st.median_clean.median())
    ov = {x['name']: x for x in overtaking(ra)['drivers']}
    er = {x['name']: x for x in race_errors(ra)['drivers']}
    rp = {x['name']: x for x in race_pace(ra.laps, dict(zip(ra.entrants.name, ra.entrants.is_ai.astype(bool))))['drivers']}
    out = {}
    for name, s in st.iterrows():
        median, spread = finite(s.get('median_clean')), finite(s.get('consistency_s'))
        grid, size = finite(s.get('grid')), finite(s.get('field_size'))
        start_grid, lap1_position = finite(s.get('start_grid')), finite(s.get('start_lap1_pos'))
        gain = start_grid - lap1_position if start_grid is not None and lap1_position is not None else None
        o, e, pace = ov.get(name, {}), er.get(name, {}), rp.get(name, {})
        trend = finite(pace.get('trend'))
        raw = {'grid_pct': (size - grid) / (size - 1) if size and size > 1 and grid and 1 <= grid <= size else None,
               'pace_rel_pct': (median / field - 1) * 100 if median and field else None,
               'lap_cv_pct': spread / median * 100 if median and spread is not None and spread >= 0 else None,
               'lap1_gain': gain, 'start_score': finite(s.get('start_score')),
               'clean_share': finite(e.get('clean_lap_share')),
               'trend_pct': trend / median * 100 if trend is not None and median else None,
               'pass_rate': 100 * o['pass_laps'] / o['attack_laps'] if o.get('attack_laps') else None,
               'hold_rate': 100 * (1 - o['lost_laps'] / o['defend_laps']) if o.get('defend_laps') else None,
               'tyre_score': None}
        raw.update({k: finite(s.get(k)) for k in ('brake_consistency', 'throttle_consistency', 'track_usage')})
        out[name] = {'raw': raw, 'is_ai': bool(s.get('is_ai')), 'driver_key': ra.session.meta.get('_livery_drivers', {}).get(name),
                     'average_lap': finite(pace.get('average')), 'best_lap': finite(s.get('best_lap')),
                     'start': {k: finite(s.get('start_' + k)) for k in ('grid', 'field_size', 'lap1_pos')},
                     'totals': {'errors': e.get('errors', 0), 'spins': e.get('spin', 0), 'passes': o.get('made', 0)},
                     'opportunities': {k: o.get(k, 0) for k in ('attack_laps', 'pass_laps', 'defend_laps', 'lost_laps')}}
    return out


def build(lib, cid):
    lib._refresh_champ_analysis(cid)
    db = lib._db(cid)
    con = connection(db)
    try:
        con.execute('CREATE TABLE IF NOT EXISTS profile_sample(session_id INTEGER PRIMARY KEY REFERENCES session(id) ON DELETE CASCADE,version INTEGER,data TEXT)')
        cfg = lib._cfg(con)
        rounds = rounds_summary(con, cfg)
        colors = driver_colors(cfg)
        sessions = {(r['round'], r['race_no']): r['id'] for r in con.execute("SELECT s.id,e.round,s.race_no FROM session s JOIN event e ON e.id=s.event_id WHERE s.type='race'")}
        samples = []; problems = []
        for race in rounds:
            sid = sessions[(race['round'], race['race_no'])]
            sample = None
            if race.get('recording_exists'):
                try:
                    sample = measurements(lib._analysis(race['recording'], cid)[0])
                    tyre_race = {r['driver']: r['score'] for r in lib.tyre_care(con, cfg, race['round'], race['race_no'])}
                    aliases_for_tyres = cfg.alias_map()
                    displays_for_tyres = {d['key']: d.get('display', d['key']) for d in cfg.drivers}
                    for name, item in sample.items():
                        display = displays_for_tyres.get(aliases_for_tyres.get(_norm(name)))
                        item['raw']['tyre_score'] = finite(tyre_race.get(display))
                    text = json.dumps(sample, allow_nan=False)
                    prior = con.execute('SELECT version,data FROM profile_sample WHERE session_id=?', (sid,)).fetchone()
                    if not prior or prior['version'] != VERSION or prior['data'] != text:
                        with con:
                            con.execute('INSERT OR REPLACE INTO profile_sample VALUES(?,?,?)', (sid, VERSION, text))
                except Exception as exc:
                    problems.append(f"R{race['round']}: profile analysis unavailable ({exc}).")
            if sample is None:
                cached = con.execute('SELECT data FROM profile_sample WHERE session_id=? AND version=?', (sid, VERSION)).fetchone()
                if cached:
                    sample = json.loads(cached['data'])
                else:
                    problems.append(f"R{race['round']}: no current profile measurements; missing values stay unrated.")
                    continue
            samples.append((race, sample))
        aliases = cfg.alias_map()
        acc = {}
        for race, sample in samples:
            for name, data in sample.items():
                key = data.get('driver_key') if data.get('is_ai') else aliases.get(_norm(name))
                if not key: continue
                raw = data['raw']
                scores = scores_from_raw(raw)
                acc.setdefault(key, []).append({'round': race['round'], 'race_no': race['race_no'],
                    'label': 'R' + str(race['round']) + ('.' + str(race['race_no']) if race['race_no'] > 1 else ''),
                    'track': race['track'], 'date': race['started_at'], 'recording': race['recording'],
                    'raw': raw, 'scores': {k: None if v is None else round(v) for k, v in scores.items()},
                    'start': data.get('start'),
                    'average_lap': data.get('average_lap'), 'best_lap': data.get('best_lap'),
                    'totals': data['totals'], 'opportunities': data['opportunities']})
        profiles = []
        for driver in cfg.drivers:
            history = acc.get(driver['key'], [])
            if not history: continue
            raw = {k: mean([p['raw'].get(k) for p in history]) for k in history[0]['raw']}
            attack = sum(p['opportunities']['attack_laps'] for p in history)
            defend = sum(p['opportunities']['defend_laps'] for p in history)
            raw['pass_rate'] = 100 * sum(p['opportunities']['pass_laps'] for p in history) / attack if attack else None
            raw['hold_rate'] = 100 * (1 - sum(p['opportunities']['lost_laps'] for p in history) / defend) if defend else None
            who = driver.get('display', driver['key'])
            for i, point in enumerate(history):
                prefix = history[:i + 1]
                cumulative = {k: mean([p['raw'].get(k) for p in prefix]) for k in point['raw']}
                attack_so_far = sum(p['opportunities']['attack_laps'] for p in prefix)
                defend_so_far = sum(p['opportunities']['defend_laps'] for p in prefix)
                cumulative['pass_rate'] = 100 * sum(p['opportunities']['pass_laps'] for p in prefix) / attack_so_far if attack_so_far else None
                cumulative['hold_rate'] = 100 * (1 - sum(p['opportunities']['lost_laps'] for p in prefix) / defend_so_far) if defend_so_far else None
                point['cumulative_scores'] = {k: None if v is None else round(v) for k, v in scores_from_raw(cumulative).items()}
            raw['tyre_score'] = mean([p['raw'].get('tyre_score') for p in history])
            scores = scores_from_raw(raw)
            profiles.append({'key': driver['key'], 'driver': who, 'is_ai': driver.get('role') == 'ai',
                             'color': colors.get(driver['key']), 'races': len(history),
                             'raw': {k: None if v is None else round(v, 3) for k, v in raw.items()},
                             'scores': {k: None if v is None else round(v) for k, v in scores.items()}, 'matches': match(scores),
                             'totals': {k: sum(p['totals'][k] for p in history) for k in ('errors', 'spins', 'passes')},
                             'history': history, 'samples': {k: sum(p['scores'].get(k) is not None for p in history) for k, _, _ in DIMENSIONS}})
        return {'version': VERSION, 'dimensions': [{'key': k, 'label': label, 'about': about} for k, label, about in DIMENSIONS],
                'profiles': sorted(profiles, key=lambda p: p['driver'].lower()), 'legends': LEGENDS, 'problems': problems,
                'source': str(lib.root), 'scope': 'Race results only. Practice 1 is a setup reference; Practice 2 is assessed separately for development.'}
    finally:
        con.close()
