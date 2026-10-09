"""Reviewed physics conversion drafts; BOP transactions own all game writes.

No lap-time simulation or speculative AI parameters. Model responses come from
one installed reference car; suspension scaling is a static-load approximation.
"""
from __future__ import annotations

import math

from .bff import BffArchive
from .bop_files import transactions
from .bop_physics import decode, edit, metrics
from .liveries import _relative


MODULES = [
    ('mass', 'Mass', 'Move mass toward the class median or reference car.'),
    ('power', 'Power per tonne', 'Scale your engine while keeping its torque curve and rev limit.'),
    ('tyres', 'Tyre package', 'Select the reference car’s installed tyre model.'),
    ('wings', 'Wing package', 'Use reference lift, drag and wing adjustment settings.'),
    ('underbody', 'Underbody and body aero', 'Use reference diffuser, ride-height, rake, stall and body-drag responses.'),
    ('suspension', 'Springs and dampers', 'Scale reference responses for your car’s axle loads and existing multipliers.'),
    ('roll_control', 'Anti-roll bars', 'Optional: scale spring-based reference bar rates for axle load, retaining your adjustment settings. Requires handling tests.'),
    ('ride_height', 'Ride-height settings', 'Use the reference car’s ride-height ranges and defaults.'),
    ('brakes', 'Brake capacity', 'Scale reference torque per kg while retaining your front/rear ratio.'),
    ('inertia', 'Mass-linked inertia', 'Scale your original rotational inertia with the proposed mass.'),
]

_WINGS = {'fw_range': 3, 'fw_setting': 1, 'fw_drag': 3, 'fw_lift': 3,
          'rw_range': 3, 'rw_setting': 1, 'rw_drag': 3, 'rw_lift': 3,
          'fw_max_height': 1, 'fw_lift_height': 1, 'fw_sideways': 1, 'rw_sideways': 1}
_UNDERBODY = {'diffuser': 3, 'diffuser_front_height': 1, 'diffuser_rake': 3,
              'diffuser_limits': 3, 'diffuser_stall': 2, 'diffuser_sideways': 1,
              'body_drag': 1, 'body_height_drag': 1, 'body_rake_drag': 1, 'body_max_height': 1}
_DAMPERS = ('slow_bump', 'fast_bump', 'slow_rebound', 'fast_rebound')
DEFAULT_MODULES = [k for k, _, _ in MODULES if k != 'roll_control']


def baseline(editor, car):
    cached = editor.conversion_cache.get(car.id)
    if cached is not None: return cached
    current = {p.id: p.value for p in car.parameters}
    result = {'mass': current.get('cdf.mass.0.0'),
              'inertia': [current.get(f'cdf.inertia.0.{i}') for i in range(3)],
              'source': 'Current installed chassis'}
    if editor.game is not None:
        # Earliest still-applied backup avoids compounding inertia scaling and
        # repairs mass-only changes made by the previous BOP editor.
        for journal, record in reversed(transactions(editor.install_dir / 'backups')):
            directory = journal.parent
            if record.get('status') != 'applied' or not any(c.get('id') == car.id for c in record.get('changes', [])):
                continue
            for source in car.sources.get('cdf', []):
                saved = next((f for f in record.get('files', []) if f.get('path', '').lower() == _relative(editor.game, source.file).lower()), None)
                if not saved: continue
                path = directory / saved['backup']
                if not path.resolve().is_relative_to(directory.resolve()): continue
                try:
                    raw = BffArchive(path).read(source.canonical) if source.packed else path.read_bytes()
                    values = {p.id: p.value for p in decode('cdf', raw)}
                    mass = values.get('cdf.mass.0.0')
                    inertia = [values.get(f'cdf.inertia.0.{i}') for i in range(3)]
                    if mass and all(x is not None and x > 0 for x in inertia):
                        result = {'mass': mass, 'inertia': inertia, 'source': 'Original chassis from apply history'}
                        editor.conversion_cache[car.id] = result
                        return result
                except (OSError, ValueError, LookupError):
                    continue
    editor.conversion_cache[car.id] = result
    return result


def information(editor, ident, target_class):
    car = editor._car(ident)
    own = metrics(car.parameters)[0]
    references = [c.public() for c in editor.cars.values() if c.id != car.id]
    members = [c for c in references if c['class'] == target_class]
    share = own.get('rear_weight_share')
    def closeness(c):
        rear = c['metrics'].get('rear_weight_share')
        return (0 if c['metrics'].get('wing_lift') is not None else 1,
                abs(rear - share) if rear is not None and share is not None else 1, c['id'])
    return {'modules': [{'id': k, 'name': n, 'description': d, 'default': k in DEFAULT_MODULES} for k, n, d in MODULES],
            'references': references, 'recommended': min(members, key=closeness)['id'] if members else '',
            'baseline': baseline(editor, car),
            'retained': ['Suspension geometry, bump/rebound travel coordinates and bump stops retain the candidate’s hardware. Matching springs and dampers does not match available wheel travel.',
                         'Differential hardware and setup retain the candidate’s values. Wheel smoke can indicate slip without sustained loss of ground contact.',
                         'Anti-roll-bar matching is optional and uses axle-load scaling, not a simulation of total roll stiffness.']}


def propose(editor, body):
    car = editor._car(body.get('car'))
    target = editor._target(body.get('target_class'), body.get('group'), body.get('grid'))
    selected = body.get('modules', DEFAULT_MODULES)
    if not isinstance(selected, list) or any(not isinstance(k, str) for k in selected) or not set(selected) <= {k for k, _, _ in MODULES}:
        raise ValueError('Choose supported conversion modules.')
    if not isinstance(body.get('move_class', True), bool): raise ValueError('Class reassignment must be on or off.')
    strength = body.get('strength', 1)
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('Performance matching must be between 0 and 100%.')
    mode = body.get('performance_target', 'class')
    if mode not in ('class', 'reference'): raise ValueError('Choose class median or reference performance.')
    reference = editor._car(body['reference']) if body.get('reference') else None
    if reference is car: raise ValueError('Choose a different reference car.')
    own = {p.id: p for p in car.parameters}
    ref = {p.id: p for p in reference.parameters} if reference else {}
    before = metrics(car.parameters)[0]
    ref_metrics = metrics(reference.parameters)[0] if reference else {}
    comparison = editor.comparison(target['Vehicle Class'], exclude=car.id)
    target_summary = comparison['reference_summary'] | {
        key: comparison['power_target']['summary'][key] for key in ('power_hp', 'power_to_weight', 'peak_torque')}
    def goal(key):
        return ref_metrics.get(key) if mode == 'reference' else target_summary[key]['median']
    changes, statuses, reasons, notes = {}, [], [], []
    request = {'car': car.id, 'fingerprint': car.fingerprint, 'parameters': changes}
    if body.get('move_class', True):
        request.update(target_class=target['Vehicle Class'], group=target['Vehicle Group'], grid=target['Grid Grouping'])
    if reference:
        request['conversion_reference'] = {'car': reference.id, 'fingerprint': reference.fingerprint}
    if mode == 'class' or reference:
        request['reference_basis'] = editor.reference_basis(comparison, strength, selected, reference, mode)
    def put(patch, key, value):
        p = own.get(key)
        if p is None: raise ValueError('Required value is unavailable: ' + key)
        if key.split('.')[0] in car.blocked: raise ValueError(car.blocked[key.split('.')[0]])
        if math.isclose(p.value, value, rel_tol=1e-7, abs_tol=1e-9): return
        if p.offset < 0: raise ValueError(p.label + ' uses a fixed zero/default encoding.')
        if p.fmt != 'f' and not p.promotable: value = round(value)
        if not math.isfinite(value) or not p.minimum <= value <= p.maximum: raise ValueError(p.label + ' exceeds its supported range.')
        patch[key] = value
    def rv(key):
        if reference is None or key not in ref: raise ValueError('A reference with decoded ' + key + ' is required.')
        return ref[key].value
    def copy_fields(patch, specification, corners=(0,)):
        for key, count in specification.items():
            for occurrence in corners:
                for i in range(count):
                    ident = f'cdf.{key}.{occurrence}.{i}'
                    put(patch, ident, rv(ident))
    def default(values, key, setting, corner):
        def value(k, i):
            p = values.get(f'cdf.{k}.{corner}.{i}')
            if p is None: raise ValueError('Complete spring, damper and default-setting data is required.')
            return p.value
        return value(key, 0) + value(key, 1) * value(setting, 0)
    for module, name, description in MODULES:
        if module not in selected: continue
        patch = {}
        try:
            if module == 'mass':
                if not before.get('mass') or not goal('mass'): raise ValueError('No decoded mass target is available.')
                put(patch, 'cdf.mass.0.0', before['mass'] * (goal('mass') / before['mass']) ** strength)
            elif module == 'power':
                if car.power_target_reason(): raise ValueError(car.power_target_reason())
                if mode == 'reference' and reference and reference.power_target_reason():
                    raise ValueError('Reference power cannot be matched automatically: ' + reference.power_target_reason())
                ratio, power, target_ratio = before.get('power_to_weight'), before.get('power_kw'), goal('power_to_weight')
                if not ratio or not power or not target_ratio: raise ValueError('Complete engine/mass data and a qualified nonboosted power reference are required.')
                mass = changes.get('cdf.mass.0.0', before['mass'])
                desired_kw = ratio * (target_ratio / ratio) ** strength * mass / 1000
                put(patch, 'cdf.power_multiplier.0.0', own['cdf.power_multiplier.0.0'].value * desired_kw / power)
                notes.append(comparison['power_target']['note'] if mode == 'class' else 'Reference power is an engine-curve proxy. Restrictors and engine modifiers are not simulated; validate on track.')
            elif module == 'tyres':
                if reference is None or not reference.references.get('tyres'): raise ValueError('Choose a reference with a decoded tyre model.')
                if not editor.detail(car.id)['tyres_editable']: raise ValueError(editor.detail(car.id)['tyres_reason'] or 'Tyre reference is unavailable.')
                from .bop_physics import edit_tyres
                edit_tyres(car.sources['vdf'][0].raw, reference.references['tyres'])
                if reference.references['tyres'] != car.references.get('tyres'): request['tyres'] = reference.references['tyres']
            elif module in ('wings', 'underbody'):
                copy_fields(patch, _WINGS if module == 'wings' else _UNDERBODY)
                if module == 'wings' and all(f'cdf.rw_peak_yaw.0.{i}' in own and f'cdf.rw_peak_yaw.0.{i}' in ref for i in range(2)):
                    copy_fields(patch, {'rw_peak_yaw': 2})
            elif module == 'ride_height':
                copy_fields(patch, {'ride_height': 3, 'ride_height_setting': 1}, range(4))
            elif module == 'suspension':
                mass = changes.get('cdf.mass.0.0', before.get('mass'))
                own_rear, ref_rear = before.get('rear_weight_share'), ref_metrics.get('rear_weight_share')
                ref_mass = ref_metrics.get('mass')
                if not mass or not ref_mass or own_rear is None or ref_rear is None or not 0 < own_rear < 1 or not 0 < ref_rear < 1:
                    raise ValueError('Both cars need mass and axle-weight distribution data.')
                for corner in range(4):
                    load_factor = mass * (own_rear if corner >= 2 else 1 - own_rear) / (ref_mass * (ref_rear if corner >= 2 else 1 - ref_rear))
                    for key in ('spring_range',) + _DAMPERS:
                        setting = 'spring_setting' if key == 'spring_range' else key + '_setting'
                        multiplier = 'spring_multiplier' if key == 'spring_range' else 'damper_multiplier'
                        own_mult = own.get(f'cdf.{multiplier}.{corner}.0')
                        if own_mult is None or own_mult.value <= 0: raise ValueError('Positive spring and damper multipliers are required.')
                        own_default = default(own, key, setting, corner)
                        desired = default(ref, key, setting, corner) * rv(f'cdf.{multiplier}.{corner}.0') * load_factor / own_mult.value
                        if own_default <= 0 or desired <= 0: raise ValueError('Positive default spring and damper rates are required.')
                        factor = desired / own_default
                        for i in range(2):
                            ident = f'cdf.{key}.{corner}.{i}'
                            put(patch, ident, own[ident].value * factor)
                notes.append('Suspension uses a static axle-load approximation. Geometry, motion ratios and bump stops still need handling tests.')
            elif module == 'roll_control':
                if own.get('cdf.spring_based_arb.0.0') is None or own['cdf.spring_based_arb.0.0'].value != 1 or rv('cdf.spring_based_arb.0.0') != 1:
                    raise ValueError('Both cars need spring-based bars; diameter-based bars cannot be matched by this approximation.')
                mass = changes.get('cdf.mass.0.0', before.get('mass'))
                own_rear, ref_rear = before.get('rear_weight_share'), ref_metrics.get('rear_weight_share')
                ref_mass = ref_metrics.get('mass')
                if not mass or not ref_mass or own_rear is None or ref_rear is None or not 0 < own_rear < 1 or not 0 < ref_rear < 1:
                    raise ValueError('Both cars need mass and axle-weight distribution data.')
                for axle in ('front', 'rear'):
                    key, setting = axle + '_arb_range', axle + '_arb_setting'
                    for values in (own, ref):
                        count = values.get(f'cdf.{key}.0.2')
                        index = values.get(f'cdf.{setting}.0.0')
                        if count is None or index is None or count.value <= 0 or not 0 <= index.value <= count.value:
                            raise ValueError('Complete, valid anti-roll-bar ranges and defaults are required.')
                    rate = default(own, key, setting, 0)
                    ref_rate = default(ref, key, setting, 0)
                    share = own_rear if axle == 'rear' else 1 - own_rear
                    ref_share = ref_rear if axle == 'rear' else 1 - ref_rear
                    desired = ref_rate * mass * share / (ref_mass * ref_share)
                    if rate <= 0 or desired <= 0: raise ValueError('Positive default anti-roll-bar rates are required.')
                    for i in range(2):
                        ident = f'cdf.{key}.0.{i}'
                        put(patch, ident, own[ident].value * desired / rate)
                notes.append('Anti-roll bars use a static axle-load approximation and retain the candidate’s settings/counts. Travel limits, bump stops, differential and geometry retain the candidate’s values; confirm tyre contact and handling on track.')
            elif module == 'brakes':
                own_values = [before.get(k) for k in ('front_brake_torque', 'rear_brake_torque')]
                reference_values = [ref_metrics.get(k) for k in ('front_brake_torque', 'rear_brake_torque')]
                mass = changes.get('cdf.mass.0.0', before.get('mass'))
                if not all(own_values) or not all(reference_values) or not mass or not ref_metrics.get('mass'):
                    raise ValueError('Both cars need decoded front/rear brake torque and mass.')
                factor = sum(reference_values) / sum(own_values) * mass / ref_metrics['mass']
                for p in car.parameters:
                    if p.id.startswith('cdf.brake_torque.'): put(patch, p.id, p.value * factor)
            elif module == 'inertia':
                original = baseline(editor, car)
                base_mass = body.get('inertia_mass', original['mass'])
                mass = changes.get('cdf.mass.0.0', before.get('mass'))
                if isinstance(base_mass, bool) or not isinstance(base_mass, (float, int)) or not math.isfinite(base_mass) or not 100 <= base_mass <= 10000:
                    raise ValueError('Original mass for inertia scaling must be 100–10,000 kg.')
                if not mass or not all(v is not None and v > 0 for v in original['inertia']): raise ValueError('Original chassis inertia is unavailable.')
                for i, value in enumerate(original['inertia']): put(patch, f'cdf.inertia.0.{i}', value * mass / base_mass)
                notes.append(f'Inertia uses {original["source"].lower()} at {base_mass:g} kg; this assumes the original mass distribution scales uniformly.')
            # Validate the complete selected module before merging any of it.
            if patch and car.sources.get('cdf'): edit('cdf', car.sources['cdf'][0].raw, changes | patch)
            changes.update(patch)
            changed = len(patch) + (1 if module == 'tyres' and 'tyres' in request else 0)
            statuses.append({'id': module, 'name': name, 'status': 'ready' if changed else 'unchanged', 'values': changed, 'message': description})
            reasons.append(name + ': ' + description)
        except (ValueError, KeyError) as exc:
            statuses.append({'id': module, 'name': name, 'status': 'skipped', 'values': 0, 'message': str(exc)})
    evaluated = editor._evaluate(request)
    notes.extend(['Performance matching changes mass and power only. Selected tyre/aero packages use the reference model in full.',
                  'Engine curve, rev limit, gearing, centre of gravity, suspension geometry and aero force positions retain the car’s layout.',
                  'This is a physics conversion draft. Confirm tyre loading, handling and pace with player and AI tests before league use.'])
    return {'edit': request, 'before': evaluated['before'], 'after': evaluated['after'],
            'comparison': target_summary, 'power_target': comparison['power_target'], 'modules': statuses, 'reasons': reasons, 'notes': notes,
            'reference': reference.name if reference else None,
            'changes': evaluated['descriptions'], 'baseline': baseline(editor, car)}
