"""Percentage category drafts, materialized through the normal BOP transaction path."""
from __future__ import annotations

import copy
import math

STEP = 0.25
LIMIT = 50
VERSION = 1

_SPECS = [
    ('power', 'Power', 'Scale the chassis power multiplier; engine curve and rev limit stay as set.',
     ['cdf.power_multiplier.0.0']),
    ('mass', 'Mass', 'Positive adds weight; negative removes weight. Inertia stays as set.', ['cdf.mass.0.0']),
    ('wings', 'Wing downforce', 'Scale front and rear wing lift together, retaining their balance and current drag.',
     [f'cdf.{axle}_lift.0.{i}' for axle in ('fw', 'rw') for i in range(3)]),
    ('drag', 'Body and wing drag', 'Scale base body drag and both wing drag polynomials; underbody responses stay as set.',
     ['cdf.body_drag.0.0'] + [f'cdf.{axle}_drag.0.{i}' for axle in ('fw', 'rw') for i in range(3)]),
    ('brakes', 'Brake torque', 'Scale all four brake torques together, retaining front/rear balance.',
     [f'cdf.brake_torque.{i}.0' for i in range(4)]),
    ('springs', 'Spring stiffness', 'Scale all four spring multipliers; ranges, settings and suspension travel stay as set.',
     [f'cdf.spring_multiplier.{i}.0' for i in range(4)]),
    ('dampers', 'Damping', 'Scale all four damper multipliers; bump/rebound balance and settings stay as set.',
     [f'cdf.damper_multiplier.{i}.0' for i in range(4)]),
    ('bars', 'Anti-roll bars', 'Scale spring-based front/rear bar range bases and steps; balance and adjustment counts stay as set.',
     [f'cdf.{axle}_arb_range.0.{i}' for axle in ('front', 'rear') for i in range(2)]),
    ('cg', 'CG height', 'Positive raises the centre of gravity; negative lowers it. Weight distribution stays as set.',
     ['cdf.cg_height.0.0']),
]


def _fields(car):
    return {p.id: p for p in car.parameters if p.group != 'RPM'}


def information(car):
    known = _fields(car)
    categories = []
    for ident, name, description, ids in _SPECS:
        reason = ''
        if any(key not in known for key in ids):
            reason = 'The complete set of required values is not decoded for this car.'
        elif any(key.split('.')[0] in car.blocked for key in ids):
            reason = 'These values use a shared physics file; per-car editing is unavailable.'
        elif any(known[key].offset < 0 and known[key].value != 0 for key in ids):
            reason = 'A required value has no writable numeric bytes.'
        elif not any(known[key].value != 0 for key in ids):
            reason = 'All required values are zero, so percentage scaling would have no effect.'
        elif ident == 'bars' and known.get('cdf.spring_based_arb.0.0', None) is None:
            reason = 'The anti-roll-bar model is not decoded.'
        elif ident == 'bars' and known['cdf.spring_based_arb.0.0'].value != 1:
            reason = 'Percentage bar-rate scaling requires spring-based anti-roll bars.'
        categories.append({'id': ident, 'name': name, 'description': description, 'parameters': ids,
                           'available': not reason, 'reason': reason, 'step': STEP, 'minimum': -LIMIT, 'maximum': LIMIT})
    return categories


def _category(car, ident):
    if not isinstance(ident, str):
        raise ValueError('Choose a supported percentage category.')
    category = next((c for c in information(car) if c['id'] == ident), None)
    if not category:
        raise ValueError('Choose a supported percentage category.')
    if not category['available']:
        raise ValueError(category['name'] + ': ' + category['reason'])
    return category


def _percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Enter a finite percentage.')
    if not -LIMIT <= value <= LIMIT or not math.isclose(value / STEP, round(value / STEP), abs_tol=1e-9):
        raise ValueError(f'Use {STEP:g}% increments from {-LIMIT:g}% to {LIMIT:g}%.')
    return float(value)


def _number(p, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Enter a finite starting value for ' + p.label + '.')
    if not p.minimum <= value <= p.maximum or (p.fmt != 'f' and not p.promotable and int(value) != value):
        raise ValueError('Percentage tuning exceeds the supported range for ' + p.label + '.')
    return value


def _scaled(p, base, percent):
    value = base * (1 + percent / 100)
    # Stored mass/brake integers need representable values; real-valued parameters
    # retain the existing decoder's documented numeric widening support.
    if p.fmt != 'f' and not p.promotable:
        value = math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)
    return _number(p, value)


def validate(car, request):
    """Prevent percentage labels drifting from the actual reviewed parameter draft."""
    state = request.get('percentage_tuning')
    if state is None:
        return
    if 'donor_baseline' in request:
        raise ValueError('Apply or reset the complete donor draft before percentage tuning installed values.')
    if not isinstance(state, dict) or state.get('version') != VERSION or set(state) != {'version', 'categories'}:
        raise ValueError('Invalid percentage tuning state.')
    entries = state['categories']
    if not isinstance(entries, dict) or len(entries) > len(_SPECS):
        raise ValueError('Invalid percentage tuning categories.')
    known = _fields(car)
    values = request.get('parameters', {})
    if not isinstance(values, dict):
        raise ValueError('Invalid parameter edits.')
    for ident, entry in entries.items():
        category = _category(car, ident)
        if not isinstance(entry, dict) or set(entry) != {'percent', 'base'}:
            raise ValueError('Invalid percentage tuning baseline.')
        percent = _percent(entry['percent'])
        base = entry['base']
        if not isinstance(base, dict) or set(base) != set(category['parameters']):
            raise ValueError('Percentage tuning requires the complete category baseline.')
        if ident == 'bars' and values.get('cdf.spring_based_arb.0.0', known['cdf.spring_based_arb.0.0'].value) != 1:
            raise ValueError('Percentage bar-rate scaling requires spring-based anti-roll bars.')
        for key in category['parameters']:
            p = known[key]
            expected = _scaled(p, _number(p, base[key]), percent)
            actual = values.get(key, p.value)
            if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-9):
                raise ValueError('Percentage tuning and manual values disagree. Reset that category or rebuild the draft.')


def stage(editor, body):
    request = body.get('edit')
    if not isinstance(request, dict):
        raise ValueError('Provide the current car draft.')
    if 'donor_baseline' in request:
        raise ValueError('Apply or reset the complete donor draft before percentage tuning installed values.')
    editor._evaluate(request)
    car = editor._car(request.get('car'))
    category = _category(car, body.get('category'))
    percent = _percent(body.get('percent'))
    result = copy.deepcopy(request)
    values = result.setdefault('parameters', {})
    state = result.setdefault('percentage_tuning', {'version': VERSION, 'categories': {}})
    entries = state['categories']
    known = _fields(car)
    base = entries.get(category['id'], {}).get('base')
    if base is None:
        base = {key: values.get(key, known[key].value) for key in category['parameters']}
    for key in category['parameters']:
        p = known[key]
        value = _scaled(p, base[key], percent)
        if math.isclose(value, p.value, rel_tol=1e-8, abs_tol=1e-9):
            values.pop(key, None)
        else:
            values[key] = value
    if percent:
        entries[category['id']] = {'percent': percent, 'base': base}
    else:
        entries.pop(category['id'], None)
    if not entries:
        result.pop('percentage_tuning', None)
    evaluated = editor._evaluate(result)
    return {'edit': result, 'before': evaluated['before'], 'after': evaluated['after']}
