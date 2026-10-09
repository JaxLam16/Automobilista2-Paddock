"""Telemetry-backed development projects and exactly-once, journalled physics upgrades.

These are small campaign rewards, not predictions of lap-time gains. Only decoded
installed parameters are edited; unsupported systems are shown explicitly.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .bop_files import transactions
from .derive import load_session
from .technique import recording_laps, corners_from_laps
from .weekends import connection, weekends

# id, name, description, parameter prefixes, factor per level, objective, requirements
CATALOG = [
    ('power', 'Engine power', 'Power multiplier +0.20% per level.', ('cdf.power_multiplier.',), 1.002, 'pace', 'positive'),
    ('response', 'Engine response', 'Rotating engine inertia −0.20% per level.', ('edf.engine_inertia.',), .998, 'exit', 'positive'),
    ('efficiency', 'Fuel efficiency', 'Fuel-consumption coefficient −0.20% per level.', ('edf.fuel_consumption.',), .998, 'fuel', 'positive'),
    ('cooling', 'Engine cooling', 'Radiator cooling +0.25% per level.', ('edf.radiator_cooling.',), 1.0025, 'endurance', 'positive'),
    ('reliability', 'Engine durability', 'Engine lifetime +0.50% per level.', ('edf.lifetime.',), 1.005, 'endurance', 'positive'),
    ('drag', 'Aero efficiency', 'Body drag −0.20% per level.', ('cdf.body_drag.',), .998, 'pace', 'positive'),
    ('front_aero', 'Front aero', 'Front wing lift coefficients +0.20% in magnitude, retaining their shape.', ('cdf.fw_lift.',), 1.002, 'fast', 'negative_lift'),
    ('rear_aero', 'Rear aero', 'Rear wing lift coefficients +0.20% in magnitude, retaining their shape.', ('cdf.rw_lift.',), 1.002, 'fast', 'negative_lift'),
    ('underbody', 'Floor and diffuser', 'Underbody development needs a verified downforce upgrade mapping.', (), 1, 'fast', 'unavailable'),
    ('aero_balance', 'Aero yaw stability', 'Yaw-dependent aero changes need a verified direction of improvement.', (), 1, 'fast', 'unavailable'),
    ('brakes', 'Brake hardware', 'Brake torque +0.25% at every wheel; front/rear balance is preserved.', ('cdf.brake_torque.',), 1.0025, 'braking', 'four_wheels'),
    ('brake_cooling', 'Brake cooling', 'Decoded brake-cooling coefficients +0.25% per level.', ('cdf.brake_cooling.',), 1.0025, 'endurance', 'positive'),
    ('weight', 'Lightweight chassis', 'Chassis mass −0.20% per level.', ('cdf.mass.',), .998, 'pace', 'positive'),
    ('cg', 'Centre of gravity', 'Centre-of-gravity height −0.20% per level.', ('cdf.cg_height.',), .998, 'corner', 'positive'),
    ('shifts', 'Gearbox actuation', 'Up/downshift delays −0.50% per level.', ('cdf.upshift_delay.', 'cdf.downshift_delay.'), .995, 'exit', 'all_prefixes'),
    ('clutch', 'Clutch capacity', 'Clutch torque capacity +0.25% per level.', ('cdf.clutch_torque.',), 1.0025, 'exit', 'positive'),
    ('springs', 'Spring platform', 'Spring multiplier +0.20% per level for a firmer platform; handling depends on setup.', ('cdf.spring_multiplier.',), 1.002, 'corner', 'positive'),
    ('dampers', 'Damper platform', 'Damper multiplier +0.20% per level for firmer control; handling depends on setup.', ('cdf.damper_multiplier.',), 1.002, 'corner', 'positive'),
    ('geometry', 'Suspension geometry', 'Geometry needs a verified, editable upgrade mapping.', (), 1, 'corner', 'unavailable'),
    ('differential', 'Differential', 'Differential upgrades need decoded friction/locking parameters.', (), 1, 'exit', 'unavailable'),
    ('gearing', 'Gear ratios', 'Ratio selection is a setup trade-off; a hardware-efficiency mapping is needed.', (), 1, 'pace', 'unavailable'),
    ('tyres', 'Tyres and compounds', 'Tyre grip upgrades need a verified tyre-physics decoder.', (), 1, 'corner', 'unavailable'),
    ('electronics', 'TC and ABS calibration', 'Assist switches are decoded, but performance calibration maps are not.', (), 1, 'braking', 'unavailable'),
]
BY_ID = {x[0]: x for x in CATALOG}
MAX_LEVEL = 8


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(path, include_metadata=True):
    h = hashlib.sha256()
    for name in (('session.json',) if include_metadata else ()) + ('frames.parquet', 'local.parquet'):
        p = Path(path) / name
        if not p.is_file():
            raise ValueError('The recording needs session metadata, field frames and your own telemetry.')
        h.update(name.encode())
        with p.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(chunk)
    return h.hexdigest()


def eligible_fields(car, category):
    _, _, _, prefixes, _, _, requirement = BY_ID[category]
    if not prefixes:
        return [], BY_ID[category][2]
    fields = [p for p in car.parameters if p.id.startswith(prefixes) and p.offset >= 0
              and p.id.split('.')[0] not in car.blocked and math.isfinite(p.value)]
    if not fields:
        return [], 'No editable parameter for this upgrade was decoded in this installed car.'
    if requirement == 'four_wheels' and len({p.id.split('.')[2] for p in fields}) != 4:
        return [], 'All four wheel brake torques must be decoded to preserve brake balance.'
    if requirement == 'all_prefixes' and not all(any(p.id.startswith(k) and p.value > 0 for p in fields) for k in prefixes):
        return [], 'Both upshift and downshift delays must be decoded and positive.'
    if requirement == 'negative_lift' and not any(p.value < 0 for p in fields):
        return [], 'The wing has no verified negative lift coefficient to strengthen.'
    if requirement != 'negative_lift':
        fields = [p for p in fields if p.value > 0]
    if not fields:
        return [], 'This parameter has no positive installed value to develop.'
    factor = BY_ID[category][4]
    def changed(p):
        target = p.value * factor
        return (round(target) if p.fmt != 'f' and not p.promotable else target) != p.value
    if not any(changed(p) for p in fields):
        return [], 'The installed numeric encoding is too coarse to represent a minor upgrade.'
    return fields, None


def measure(path, reference=None):
    sess = load_session(path)
    if sess.type != 'practice':
        raise ValueError('R&D uses a practice recording with your own car telemetry.')
    driver, laps, length = recording_laps(sess)
    if not driver:
        raise ValueError('This recording has no driving telemetry for its recording driver.')
    usable = [x for x in laps if x['valid'] and math.isfinite(x['time']) and x['time'] > 10
              and x['ld'].max() >= length * .97 and x['ld'].min() <= length * .03]
    if not usable:
        raise ValueError('No complete valid flying laps were found in this practice.')
    best = min(x['time'] for x in usable)
    usable = [x for x in usable if x['time'] <= best * 1.05]
    if len(usable) < 3:
        raise ValueError('Record at least three clean flying laps within 5% of the best lap.')
    car = (sess.meta.get('local') or {}).get('car')
    ref_lap = min(usable, key=lambda x: x['time'])
    fr = sess.frames[(sess.frames.name == driver) & (sess.frames.t >= ref_lap['t0']) & (sess.frames.t <= ref_lap['t'][-1])]
    xy = (fr.lap_dist.to_numpy(float), fr.x.to_numpy(float), fr.z.to_numpy(float)) if len(fr) > 50 else None
    corners = reference['corners'] if reference else corners_from_laps(usable, length, xy)
    grid = np.arange(0, length, 10.)
    per_lap = []
    lo = sess.local
    for lp in usable:
        row = {'n': lp['n'], 'time': lp['time'], 'speeds': {}, 'fuel_used': None}
        speed = np.interp(grid, lp['ld'], lp['speed'])
        for c in corners:
            apex = c['apex']
            dist = (grid - apex + length / 2) % length - length / 2
            row['speeds'][c['name']] = round(float(np.median(speed[np.abs(dist) <= 20])), 3)
        mask = (lo.t >= lp['t0']) & (lo.t <= lp['t'][-1])
        seg = lo[mask]
        if {'fuel_level', 'fuel_capacity'} <= set(seg.columns) and len(seg):
            fuel = seg.fuel_level.to_numpy(float) * float(seg.fuel_capacity.median())
            used = fuel[0] - fuel[-1]
            if math.isfinite(used) and used > 0:
                row['fuel_used'] = float(used)
        fuel_load = float(np.median(fuel)) if {'fuel_level', 'fuel_capacity'} <= set(seg.columns) and len(seg) else None
        row['fuel_load'] = fuel_load if fuel_load is not None and math.isfinite(fuel_load) else None
        per_lap.append(row)
    selected = sorted(per_lap, key=lambda x: (x['time'], x['n']))[:3]
    medians = {c['name']: round(float(np.median([x['speeds'][c['name']] for x in selected])), 3) for c in corners}
    kinds = {'fast': [k for k, v in medians.items() if v >= 160],
             'corner': [k for k, v in medians.items() if v < 160],
             'exit': [k for k, v in medians.items() if v < 160]}
    def finite_median(vals):
        vals = [v for v in vals if v is not None and math.isfinite(v)]
        return float(np.median(vals)) if vals else None
    return {'driver': driver, 'car': car, 'track': sess.meta['track_location'], 'layout': sess.meta['track_variation'],
            'started_at': sess.meta.get('started_at'), 'length': length, 'hash': fingerprint(path), 'credit_hash': fingerprint(path, False),
            'clean_laps': len(per_lap), 'total_laps': len(laps), 'laps': per_lap,
            'reference_laps': [x['n'] for x in selected], 'median': round(float(np.median([x['time'] for x in selected])), 3),
            'fuel_used': finite_median([x['fuel_used'] for x in selected]),
            'fuel_load': finite_median([x['fuel_load'] for x in selected]),
            'corner_speeds': medians, 'kinds': kinds, 'corners': corners}


def objectives(category, baseline):
    mode = BY_ID[category][5]
    goals = [{'id': 'repeatability', 'kind': 'repeatability', 'target': 1.,
              'text': 'Drive 3 consecutive clean laps within 1.000 s of one another, each within 3 s of the P1 reference.'}]
    if mode in ('fast', 'corner', 'exit') and baseline['kinds'][mode]:
        names = baseline['kinds'][mode]
        delta = 4. if mode == 'fast' else 2.
        goals.append({'id': 'performance', 'kind': 'corner', 'corners': names, 'target': delta,
                      'text': 'Over 3 clean laps, average ' + str(int(delta)) + ' km/h faster through ' + ', '.join(names) + ' than P1.'})
    elif mode == 'fuel' and baseline.get('fuel_used'):
        goals.append({'id': 'performance', 'kind': 'fuel', 'target': baseline['fuel_used'] * .995,
                      'text': 'Use at least 0.5% less fuel per lap over 3 clean laps, staying within 1 s of the P1 reference.'})
    elif mode == 'endurance':
        goals.append({'id': 'performance', 'kind': 'endurance', 'target': 5,
                      'text': 'Complete 5 consecutive clean flying laps, each within 3 s of the P1 reference.'})
    else:
        goals.append({'id': 'performance', 'kind': 'pace', 'target': baseline['median'] - .3,
                      'text': 'Over 3 clean laps, beat the P1 reference median by at least 0.300 s.'})
    return goals


def evaluate(projects, baseline, session):
    for key in ('driver', 'car', 'track', 'layout'):
        if session.get(key) != baseline.get(key):
            raise ValueError('Practice 2 must use the same driver, car, track and layout as Practice 1.')
    if abs(session['length'] - baseline['length']) > 10:
        raise ValueError('Practice 2 track length differs from the reference.')
    if baseline['hash'] == session['hash'] or (baseline.get('credit_hash') and baseline['credit_hash'] == session.get('credit_hash')):
        raise ValueError('Practice 2 must be a new recording, not the Practice 1 reference.')
    if baseline.get('started_at') and session.get('started_at'):
        def timestamp(value):
            date = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()
        if timestamp(session['started_at']) <= timestamp(baseline['started_at']):
            raise ValueError('Practice 2 must have been recorded after Practice 1.')
    laps = sorted(session['laps'], key=lambda x: x['n'])
    windows = [laps[i:i + 3] for i in range(len(laps) - 2)
               if laps[i + 2]['n'] - laps[i]['n'] == 2]
    outcomes = []
    for project in projects:
        goals = []
        for goal in project['objectives']:
            kind = goal['kind']; actual = None; samples = []
            if kind == 'repeatability':
                groups = [g for g in windows if all(abs(x['time'] - baseline['median']) <= 3 for x in g)]
                if groups:
                    group = min(groups, key=lambda g: max(x['time'] for x in g) - min(x['time'] for x in g))
                    actual = max(x['time'] for x in group) - min(x['time'] for x in group)
                    samples = [x['n'] for x in group]
                passed = actual is not None and actual <= goal['target'] + 1e-8
            elif kind == 'endurance':
                run = []; longest = []
                for lp in laps:
                    if abs(lp['time'] - baseline['median']) > 3:
                        run = []; continue
                    if run and lp['n'] != run[-1]['n'] + 1:
                        run = []
                    run.append(lp)
                    if len(run) > len(longest): longest = list(run)
                actual = len(longest); samples = [x['n'] for x in longest]
                passed = actual >= goal['target']
            else:
                candidates = []
                for group in windows:
                    if kind == 'pace':
                        val = float(np.median([x['time'] for x in group]))
                    elif kind == 'fuel':
                        if any(x.get('fuel_used') is None or abs(x['time'] - baseline['median']) > 1 for x in group): continue
                        val = float(np.median([x['fuel_used'] for x in group]))
                    else:
                        names = goal['corners']
                        val = float(np.mean([x['speeds'][k] - baseline['corner_speeds'][k] for x in group for k in names]))
                    candidates.append((val, group))
                if candidates:
                    actual, group = (max if kind == 'corner' else min)(candidates, key=lambda x: x[0])
                    samples = [x['n'] for x in group]
                passed = actual is not None and (actual >= goal['target'] - 1e-8 if kind == 'corner' else actual <= goal['target'] + 1e-8)
            goals.append(goal | {'passed': bool(passed), 'actual': None if actual is None else round(float(actual), 4), 'laps': samples})
        outcomes.append({'category': project['category'], 'objectives': goals, 'points': sum(x['passed'] for x in goals)})
    return {'assessed_at': now(), 'recording_hash': session.get('credit_hash', session['hash']), 'clean_laps': session['clean_laps'], 'projects': outcomes}


class Development:
    def __init__(self, app):
        self.app = app
        self.lib = app.lib
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.worker = None

    @property
    def editor(self):
        if self.app._bop_editor is None:
            from .bop import BopEditor
            self.app._bop_editor = BopEditor(self.lib.root, self.lib)
        return self.app._bop_editor

    def config(self, cid, body=None):
        con = connection(self.lib._db(cid))
        try:
            row = con.execute("SELECT value FROM meta WHERE key='development_config'").fetchone()
            cfg = json.loads(row['value']) if row else {}
            if body is not None:
                car = self.editor._car(body.get('car'))
                if not isinstance(body.get('automatic', True), bool):
                    raise ValueError('Automatic application must be on or off.')
                if cfg.get('car') and cfg['car'] != car.id and self.plans(cid):
                    raise ValueError('This championship already has development for its bound car.')
                telemetry_car = str(body.get('telemetry_car') or cfg.get('telemetry_car') or car.name).strip()
                cfg = {'car': car.id, 'name': car.name, 'telemetry_car': telemetry_car, 'automatic': body.get('automatic', True),
                       'expected_fingerprint': car.fingerprint}
                with con:
                    con.execute("INSERT INTO meta VALUES('development_config',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(cfg),))
            return cfg
        finally:
            con.close()

    def plans(self, cid):
        con = connection(self.lib._db(cid))
        try:
            return [json.loads(r['data']) for r in con.execute('SELECT data FROM development ORDER BY round,id')]
        finally:
            con.close()

    def save(self, cid, plan):
        con = connection(self.lib._db(cid))
        try:
            data = json.dumps(plan, allow_nan=False)
            row = con.execute('SELECT data FROM development WHERE id=?', (plan['id'],)).fetchone()
            if row and row['data'] == data: return
            with con:
                con.execute('INSERT INTO development VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,data=excluded.data',
                            (plan['id'], plan['round'], plan['driver'], plan['car'], plan['state'], data))
        finally:
            con.close()

    def receipts(self):
        root = self.lib.root / 'balance_of_performance'
        root.mkdir(exist_ok=True)
        con = sqlite3.connect(root / 'development_receipts.db')
        con.execute('CREATE TABLE IF NOT EXISTS receipt(hash TEXT PRIMARY KEY,champ TEXT NOT NULL,plan TEXT NOT NULL)')
        return con

    def reserve(self, cid, plan, content_hash):
        con = self.receipts()
        try:
            with con:
                row = con.execute('SELECT champ,plan FROM receipt WHERE hash=?', (content_hash,)).fetchone()
                if row and row != (cid, plan['id']):
                    raise ValueError('This Practice 2 recording has already earned research credit. Uploading a copy cannot earn it again.')
                con.execute('INSERT OR IGNORE INTO receipt VALUES(?,?,?)', (content_hash, cid, plan['id']))
        finally:
            con.close()

    def overview(self, cid):
        with self.lock, self.lib.lock, self.editor.lock:
            return self._overview(cid)

    def _overview(self, cid):
        cfg = self.config(cid)
        ed = self.editor
        car = ed.cars.get(cfg.get('car'))
        plans = self.plans(cid)
        # The shared BOP editor can also undo an R&D transaction. Keep the
        # championship ledger tied to the physics journal, retaining research.
        if ed.game is not None:
            journal = {}
            for _, record in transactions(ed.install_dir / 'backups'):
                for change in record.get('changes', []):
                    ref = change.get('development', {})
                    if ref.get('champ') == cid:
                        journal.setdefault(ref.get('plan'), record)
            for p in plans:
                record = journal.get(p['id'])
                if p['state'] in ('applied', 'applying') and record and record.get('status') == 'undone':
                    p.update(state='reverted', reverted_at=now(), error=None)
                    self.save(cid, p)
        earned = {k: 0 for k in BY_ID}; applied = {k: 0 for k in BY_ID}
        for p in plans:
            for x in (p.get('evaluation') or {}).get('projects', []): earned[x['category']] += x['points']
            if p['state'] == 'applied':
                for k, n in p.get('upgrades', {}).items(): applied[k] += n
        catalog = []
        for ident, name, desc, _, factor, _, _ in CATALOG:
            fields, reason = eligible_fields(car, ident) if car else ([], 'Scan AMS2 and bind your installed car to this championship.')
            catalog.append({'id': ident, 'name': name, 'description': desc, 'available': bool(fields), 'reason': reason,
                            'points': earned[ident], 'unlocked': min(MAX_LEVEL, earned[ident] // 2),
                            'applied': applied[ident], 'max_level': MAX_LEVEL,
                            'step_pct': round((factor - 1) * 100, 3)})
        return {'config': cfg, 'physics': ed.config_info(), 'cars': [c.public() for c in ed.cars.values()],
                'catalog': catalog, 'plans': plans, 'weekends': weekends(self.lib, cid)}

    def create(self, cid, body):
        with self.lock, self.lib.lock, self.editor.lock:
            cfg = self.config(cid)
            car = self.editor._car(cfg.get('car'))
            selected = body.get('categories')
            if not isinstance(selected, list) or not 1 <= len(selected) <= 2 or len(set(selected)) != len(selected) or any(k not in BY_ID for k in selected):
                raise ValueError('Choose one or two different R&D areas.')
            rnd = body.get('round')
            w = next((w for w in weekends(self.lib, cid) if w['round'] == rnd), None)
            if not w or not w.get('practice1'):
                raise ValueError('Assign Practice 1 to this weekend before choosing development goals.')
            if w.get('practice2'):
                raise ValueError('Choose your development goals before assigning Practice 2.')
            if any(p['round'] == rnd for p in self.plans(cid)):
                raise ValueError('This weekend already has a locked development plan.')
            if any(p['state'] in ('queued', 'applying', 'blocked') for p in self.plans(cid)):
                raise ValueError('Apply or resolve the previous pending upgrades before starting another development plan.')
            if car.fingerprint != cfg.get('expected_fingerprint'):
                raise ValueError('The car changed outside this championship. Bind its current physics in R&D before creating a plan.')
            progress = {c['id']: c for c in self.overview(cid)['catalog']}
            for k in selected:
                fields, reason = eligible_fields(car, k)
                if not fields: raise ValueError(BY_ID[k][1] + ': ' + reason)
                if progress[k]['unlocked'] >= MAX_LEVEL: raise ValueError(BY_ID[k][1] + ' is fully developed.')
            ref = measure(self.lib.recording_path(w['practice1']))
            import re
            normalize = lambda value: re.sub(r'[^a-z0-9]', '', str(value).lower())
            if normalize(ref['car']) != normalize(cfg['telemetry_car']):
                raise ValueError('The P1 car does not match the bound installed car. Set its exact telemetry name in Installed car before planning development.')
            plan = {'id': uuid.uuid4().hex, 'round': rnd, 'driver': ref['driver'], 'car': car.id, 'car_name': car.name,
                    'state': 'planned', 'created_at': now(), 'practice1': w['practice1'], 'practice2': None,
                    'baseline': ref, 'projects': [{'category': k, 'name': BY_ID[k][1], 'objectives': objectives(k, ref)} for k in selected],
                    'expected_fingerprint': car.fingerprint, 'evaluation': None, 'upgrades': {}, 'error': None}
            self.save(cid, plan)
            return plan

    def submit(self, cid, body):
        with self.lock, self.lib.lock:
            plan = next((p for p in self.plans(cid) if p['id'] == body.get('plan')), None)
            if not plan: raise ValueError('Choose an existing development plan.')
            if plan.get('evaluation'): return plan  # retries cannot award twice
            w = next(w for w in weekends(self.lib, cid) if w['round'] == plan['round'])
            if not w.get('practice2'): raise ValueError('Assign a Practice 2 recording to this weekend first.')
            if fingerprint(self.lib.recording_path(plan['practice1'])) != plan['baseline']['hash']:
                raise ValueError('Practice 1 changed after the goals were locked. The original reference must be restored.')
            session = measure(self.lib.recording_path(w['practice2']), plan['baseline'])
            ev = evaluate(plan['projects'], plan['baseline'], session)
            self.reserve(cid, plan, ev['recording_hash'])
            before = {k: 0 for k in BY_ID}
            for p in self.plans(cid):
                if p['id'] != plan['id']:
                    for x in (p.get('evaluation') or {}).get('projects', []): before[x['category']] += x['points']
            upgrades = {x['category']: min(MAX_LEVEL, (before[x['category']] + x['points']) // 2) - min(MAX_LEVEL, before[x['category']] // 2)
                        for x in ev['projects']}
            plan.update(evaluation=ev, practice2=w['practice2'], upgrades={k: n for k, n in upgrades.items() if n},
                        state='queued' if any(upgrades.values()) else 'assessed', error=None)
            self.save(cid, plan)
            if self.config(cid).get('automatic', True): self.apply(cid, plan['id'])
            self.start_worker()
            return next(p for p in self.plans(cid) if p['id'] == plan['id'])

    def journal(self, cid, ident):
        try:
            for path, record in transactions(self.editor.install_dir / 'backups'):
                if any(x.get('development', {}).get('champ') == cid and x.get('development', {}).get('plan') == ident for x in record.get('changes', [])):
                    return record
        except ValueError:
            pass
        return None

    def apply(self, cid, ident, retry=False):
        with self.lock, self.lib.lock, self.editor.lock:
            plan = next((p for p in self.plans(cid) if p['id'] == ident), None)
            if not plan or plan['state'] not in ('queued', 'applying', 'blocked'):
                return plan
            if plan['state'] == 'blocked' and not retry: return plan
            ed = self.editor
            try:
                if ed.game is None: ed.scan()
                record = self.journal(cid, ident)
                if record and record['status'] == 'applied':
                    plan.update(state='applied', transaction=record['id'], applied_at=record['created'], error=None)
                    self.save(cid, plan)
                    self.config(cid, {'car': plan['car'], 'automatic': self.config(cid).get('automatic', True)})
                    return plan
                if record and record['status'] == 'undone':
                    plan.update(state='reverted', error=None)
                    self.save(cid, plan); return plan
                from .liveries import _game_running
                if _game_running():
                    plan.update(state='queued', error='Close AMS2; these earned upgrades will apply automatically when the game exits.')
                    self.save(cid, plan); return plan
                car = ed._car(plan['car'])
                if car.fingerprint != plan['expected_fingerprint']:
                    raise ValueError('Installed physics differ from the locked plan. Rescan and explicitly adopt the current car in R&D before retrying.')
                changes = {}
                for k, n in plan['upgrades'].items():
                    fields, reason = eligible_fields(car, k)
                    if not fields: raise ValueError(BY_ID[k][1] + ': ' + reason)
                    factor = BY_ID[k][4] ** n
                    for field in fields:
                        value = field.value * factor
                        if field.fmt in ('B', 'i', 'I', 'h', 'H') and not field.promotable: value = round(value)
                        if value != field.value: changes[field.id] = value
                if not changes: raise ValueError('These upgrades are smaller than the stored parameter precision; no changes were applied.')
                preview = ed.preview([{'car': car.id, 'fingerprint': car.fingerprint, 'parameters': changes}])
                if not preview['count']: raise ValueError('The physics file encoding cannot represent these upgrades.')
                for change in ed.prepared[preview['token']]['changes']:
                    change['development'] = {'champ': cid, 'plan': ident, 'recording_hash': plan['evaluation']['recording_hash']}
                plan.update(state='applying', physics_changes=preview['changes'], error=None)
                self.save(cid, plan)  # journal recovery handles interruption after game writes
                result = ed.apply(preview['token'])
                plan.update(state='applied', transaction=result['transaction'], backup=result['backup'], applied_at=now(), error=None)
                self.save(cid, plan)
                self.config(cid, {'car': car.id, 'automatic': self.config(cid).get('automatic', True)})
            except (OSError, ValueError, LookupError) as exc:
                # Journal an interrupted completed write before deciding it failed.
                record = self.journal(cid, ident)
                if record and record['status'] == 'applied':
                    plan.update(state='applying', error='Recovering the completed physics transaction.')
                else:
                    plan.update(state='blocked', error=str(exc))
                self.save(cid, plan)
            return plan

    def retry(self, cid, body):
        with self.lock:
            if self.editor.game is None: self.editor.scan()
            plan = next((p for p in self.plans(cid) if p['id'] == body.get('plan')), None)
            if not plan: raise ValueError('Choose an existing development plan.')
            if body.get('adopt_current'):
                plan['expected_fingerprint'] = self.editor._car(plan['car']).fingerprint
                self.save(cid, plan)
            return self.apply(cid, plan['id'], retry=True)

    def undo(self, cid, body):
        with self.lock, self.editor.lock:
            plan = next((p for p in self.plans(cid) if p['id'] == body.get('plan')), None)
            if not plan or plan['state'] != 'applied': raise ValueError('Choose an applied development upgrade.')
            latest = next((r for _, r in transactions(self.editor.install_dir / 'backups') if r.get('status') == 'applied'), None)
            if not latest or latest['id'] != plan.get('transaction'):
                raise ValueError('Undo later BOP or development changes first; this upgrade is not the latest physics transaction.')
            result = self.editor.undo()
            plan.update(state='reverted', reverted_at=now())
            self.save(cid, plan)
            self.config(cid, {'car': plan['car'], 'automatic': self.config(cid).get('automatic', True)})
            return result

    def start_worker(self):
        if self.worker and self.worker.is_alive(): return
        def run():
            while not self.stop.wait(5):
                for db in self.lib._champ_files():
                    try:
                        if not self.config(db.stem).get('automatic'): continue
                        for p in self.plans(db.stem):
                            if p['state'] in ('queued', 'applying'): self.apply(db.stem, p['id'])
                    except Exception:
                        # A bad/missing championship must not stop other queues.
                        continue
        self.worker = threading.Thread(target=run, name='development-upgrades', daemon=True)
        self.worker.start()

    def route(self, cid, method, action, body):
        self.start_worker()
        if method == 'GET' and action == '': return self.overview(cid)
        if method == 'POST' and action == 'configure':
            with self.lock, self.lib.lock, self.editor.lock: return self.config(cid, body)
        if method == 'POST' and action == 'plan': return self.create(cid, body)
        if method == 'POST' and action == 'submit': return self.submit(cid, body)
        if method == 'POST' and action == 'retry': return self.retry(cid, body)
        if method == 'POST' and action == 'undo': return self.undo(cid, body)
        raise LookupError('Unknown championship development request.')
