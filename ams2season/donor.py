"""Complete physical donors and absolute tuning from local immutable snapshots."""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import struct
import uuid
from datetime import datetime, timezone

from .bff import BffArchive
from .bop_physics import change_crd, decode, edit, metrics, private_donor_vdf, vdfm_references
from .liveries import _json_write, _relative

CORE = ('cdf', 'edf', 'gdf', 'vdf')
CONTROLS = (
    ('power', 'Straight-line power', 'Scales the donor chassis power multiplier. Engine maps, boost and gearing stay together.'),
    ('aero', 'Wing downforce', 'Scales both donor wing lift polynomials. Wing balance, drag and underbody settings remain at the donor baseline.'),
    ('braking', 'Braking', 'Scales all four donor brake torques, retaining their balance. Stored integer torques round to the nearest Nm.'),
    ('cornering', 'Cornering / lower CG', 'Reduces the donor centre-of-gravity height by this percentage. Tyre grip and suspension geometry remain at the donor baseline.'),
)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _core(car, *, destination=False):
    for role in CORE:
        found = car.sources.get(role, [])
        if not found:
            raise ValueError(car.name + ': no readable ' + role.upper() + ' file was found. ' + '; '.join(car.errors.get(role, [])))
        if car.errors.get(role):
            raise ValueError(car.name + ': ' + role.upper() + ' cannot be used as a destination: ' + '; '.join(car.errors[role]))
        if any(s.raw != found[0].raw for s in found):
            raise ValueError(car.name + ': destination ' + role.upper() + ' copies disagree. Restore matching candidate files before transfer.')
        if destination and role in car.blocked: raise ValueError(car.blocked[role])
        if len({s.canonical.lower() for s in found}) != 1:
            raise ValueError('The candidate needs one private canonical path per core component.')
    if not {'cdf', 'edf', 'gdf'} <= car.references.keys():
        raise ValueError('The car needs mapped chassis, engine and gearbox references.')


def _donor_components(editor, car):
    """A read-only donor can supply a chosen version without repairing its copies.

    Linked components remain strict: they are referenced in place, whereas the
    four core streams are frozen and copied to every writable candidate copy.
    No loose/packed loader precedence is assumed.
    """
    components, notes = [], []
    for role in CORE:
        found = car.sources.get(role, [])
        groups, issues = {}, []
        if len({s.canonical.lower() for s in found}) > 1:
            raise ValueError(car.name + ': ' + role.upper() + ' has multiple component paths; a coherent donor map is required.')
        for source in found:
            try:
                if role == 'vdf':
                    refs = vdfm_references(source.raw)
                    if not {'cdf', 'edf', 'gdf'} <= refs.keys():
                        raise ValueError('Mapped chassis, engine and gearbox links are required.')
                    if refs != car.references:
                        raise ValueError('VDFM copies reference different components; restore one consistent component map before capture.')
                    parameters = []
                else:
                    parameters = decode(role, source.raw)
                    if not parameters: raise ValueError('No supported parameters were decoded.')
            except (ValueError, UnicodeError, struct.error) as exc:
                if role == 'vdf' and 'different components' in str(exc): raise
                issues.append(_relative(editor.game, source.file) + ': ' + str(exc)); continue
            ident = _hash(source.raw)
            if ident not in groups:
                groups[ident] = {'id': ident, 'sources': [], 'metrics': metrics(parameters)[0]}
            groups[ident]['sources'].append({'path': _relative(editor.game, source.file),
                                           'canonical': source.canonical, 'packed': source.packed})
        # A failed packed read is not evidence that the readable donor version is
        # unusable. The original scan's write blocks still apply to destinations.
        issues += [e for e in car.errors.get(role, []) if 'copies disagree' not in e and e not in issues]
        versions = list(groups.values())
        reason = '' if versions else car.name + ': no usable ' + role.upper() + ' donor file. ' + ('; '.join(issues) or 'The installed component is missing.')
        if len(versions) > 1:
            notes.append(role.upper() + ' copies differ. Choose the version to copy; the app cannot confirm which copy AMS2 currently loads.')
        if issues and versions:
            notes.append(role.upper() + ': capture uses a readable, validated version. Other scan issues: ' + '; '.join(issues))
        components.append({'role': role, 'versions': versions, 'reason': reason})
    return components, notes


def _selected_core(editor, car, choices):
    if not isinstance(choices, dict) or not set(choices) <= set(CORE):
        raise ValueError('Invalid donor component selections.')
    components, notes = _donor_components(editor, car)
    raw, selected = {}, []
    for component in components:
        if component['reason']: raise ValueError(component['reason'])
        role, versions = component['role'], component['versions']
        choice = choices.get(role)
        if choice is None:
            if len(versions) != 1: raise ValueError('Choose a ' + role.upper() + ' donor version before capturing the baseline.')
            choice = versions[0]['id']
        if not isinstance(choice, str) or choice not in {v['id'] for v in versions}:
            raise ValueError('The selected ' + role.upper() + ' donor version is unavailable. Scan and choose it again.')
        copies = [s for s in car.sources[role] if _hash(s.raw) == choice]
        raw[role] = copies[0].raw
        selected.append({'role': role, 'sha': choice, 'copies': next(v['sources'] for v in versions if v['id'] == choice)})
    return raw, selected, notes


def _dependencies(car):
    result, notes = [], []
    for role in ('sdf', 'tyres', 'cmf', 'tbf', 'fmf', 'collision'):
        ref = car.references.get(role)
        if not ref: continue
        found = car.linked_sources.get(role, [])
        if car.linked_errors.get(role) or found and any(s.raw != found[0].raw for s in found):
            raise ValueError('Donor ' + role.upper() + ' copies are unreadable or disagree. Restore them before capturing a baseline.')
        if not found:
            if role in ('sdf', 'tyres', 'cmf') or role == 'tbf' and car.turbo_model is not False:
                raise ValueError('Donor ' + role.upper() + ' reference ' + ref + ' is unavailable. A complete transfer cannot omit it.')
            if role != 'tbf': notes.append(role.upper() + ' reference ' + ref + ' is retained from the donor; its installed bytes could not be independently pinned.')
            continue
        result.extend((role, source) for source in found)
    return result, notes


def _check_current(source):
    current = BffArchive(source.file).read(source.canonical) if source.packed else source.file.read_bytes()
    if current != source.raw:
        raise ValueError('Game files changed since scanning. Scan again before capturing or tuning a donor.')


def _public(record, raw):
    parameters = decode('cdf', raw['cdf']); controls = []
    for key, label, note in CONTROLS:
        if key == 'power': selected = [p for p in parameters if p.id == 'cdf.power_multiplier.0.0']
        elif key == 'aero': selected = [p for p in parameters if p.id.startswith(('cdf.fw_lift.', 'cdf.rw_lift.'))]
        elif key == 'braking': selected = [p for p in parameters if p.id.startswith('cdf.brake_torque.')]
        else: selected = [p for p in parameters if p.id == 'cdf.cg_height.0.0']
        complete = len(selected) == {'power': 1, 'aero': 6, 'braking': 4, 'cornering': 1}[key]
        supported = complete and all(p.offset >= 0 and (p.fmt == 'f' or p.promotable or key == 'braking') for p in selected)
        controls.append({'id': key, 'name': label, 'note': note, 'available': supported,
                         'reason': '' if supported else 'This donor does not expose the complete supported values for this control.',
                         'min': 0, 'max': 10, 'step': .5})
    all_parameters = parameters + decode('edf', raw['edf']) + decode('gdf', raw['gdf'])
    return {k: record[k] for k in ('id', 'car', 'donor', 'donor_name', 'created', 'fingerprint', 'class', 'group', 'grid', 'notes')} | {
        'metrics': metrics(all_parameters)[0], 'references': vdfm_references(raw['vdf']), 'controls': controls,
        'sources': record.get('sources', []),
        'pinned_components': sorted({d['role'] for d in record['dependencies']})}


def _identity(record):
    return {k: record[k] for k in ('car', 'donor', 'fingerprint', 'streams', 'targets', 'aliases', 'class', 'group', 'grid')} | {
        'dependencies': sorted({(d['role'], d['canonical'].lower(), d['sha']) for d in record['dependencies']})}


def _load(editor, ident, car):
    if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise ValueError('Invalid donor baseline identifier.')
    directory = editor.install_dir / 'donor_baselines' / ident
    try:
        record = json.loads((directory / 'baseline.json').read_text(encoding='utf-8'))
        if record.get('version') != 1 or record.get('id') != ident or record.get('car') != car.id:
            raise ValueError('This donor baseline belongs to another car or version.')
        raw = {role: (directory / (role + '.bin')).read_bytes() for role in CORE}
        if any(_hash(raw[role]) != record['streams'][role] for role in CORE):
            raise ValueError('Saved donor baseline bytes changed. Restore the snapshot or capture a different donor version.')
        if any(not car.sources.get(role) for role in CORE):
            raise ValueError('The candidate is missing core physics files. Scan and restore its files before using a saved baseline.')
        if record['targets'] != {role: car.sources[role][0].canonical.lower() for role in CORE}:
            raise ValueError('The candidate physics paths changed. Capture a new baseline after scanning.')
        if _hash(json.dumps(_identity(record), sort_keys=True).encode())[:32] != ident:
            raise ValueError('The saved donor baseline metadata changed. Restore the snapshot or capture a different donor version.')
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError('This donor baseline is unavailable. Capture the same installed donor locally before loading its profile.') from exc
    return record, raw


def information(editor, ident):
    car = editor._car(ident); baselines = []
    for file in sorted((editor.install_dir / 'donor_baselines').glob('*/baseline.json')):
        try:
            record, raw = _load(editor, file.parent.name, car); baselines.append(_public(record, raw))
        except (ValueError, KeyError): continue
    baselines.sort(key=lambda b: b['created'], reverse=True)
    active = None
    from .bop_files import transactions
    for _, journal in transactions(editor.install_dir / 'backups'):
        if journal.get('status') != 'applied': continue
        change = next((c for c in journal.get('changes', []) if c.get('id') == car.id), None)
        if change:
            active = change.get('donor_baseline'); break
    donors = []
    for donor in editor.cars.values():
        if donor.id == car.id: continue
        reason, components, notes = '', [], []
        try:
            components, notes = _donor_components(editor, donor)
            reason = next((c['reason'] for c in components if c['reason']), '')
            _dependencies(donor)
        except ValueError as exc: reason = str(exc)
        donors.append(donor.public() | {'available': not reason, 'reason': reason, 'components': components,
                                       'source_notes': notes, 'requires_selection': any(len(c['versions']) > 1 for c in components)})
    try: _core(car, destination=True); reason = ''
    except ValueError as exc: reason = str(exc)
    return {'car': car.id, 'baselines': baselines, 'active': active, 'donors': donors, 'reason': reason}


def capture(editor, request):
    car, donor = editor._car(request.get('car')), editor._car(request.get('donor'))
    if car.id == donor.id: raise ValueError('Choose a different car as the donor.')
    if request.get('fingerprint') != car.fingerprint or request.get('donor_fingerprint') != donor.fingerprint:
        raise ValueError('The candidate or donor changed. Scan and choose the donor again.')
    _core(car, destination=True)
    raw, selected, source_notes = _selected_core(editor, donor, request.get('sources', {}))
    dependencies, notes = _dependencies(donor)
    for source in [s for c in (car, donor) for found in c.sources.values() for s in found] + [s for _, s in dependencies]:
        _check_current(source)
    record = {'version': 1, 'car': car.id, 'donor': donor.id, 'donor_name': donor.name,
              'created': datetime.now(timezone.utc).isoformat(), 'fingerprint': donor.fingerprint,
              'streams': {role: _hash(data) for role, data in raw.items()},
              'targets': {role: car.sources[role][0].canonical.lower() for role in CORE},
              'aliases': {role: car.references[role] for role in ('cdf', 'edf', 'gdf')},
              'class': donor.metadata['Vehicle Class'], 'group': donor.metadata.get('Vehicle Group', ''),
              'grid': donor.metadata.get('Grid Grouping', ''), 'notes': notes + source_notes, 'sources': selected,
              'dependencies': [{'role': role, 'canonical': s.canonical, 'path': _relative(editor.game, s.file),
                                'packed': s.packed, 'sha': _hash(s.raw)} for role, s in dependencies]}
    # Identical donors reproduce an identity across machines: paths, timestamps
    # and identical source-copy counts do not contribute to the content ID.
    record['id'] = _hash(json.dumps(_identity(record), sort_keys=True).encode())[:32]
    root = editor.install_dir / 'donor_baselines'; directory = root / record['id']
    if not directory.exists():
        temporary = root / ('.capture-' + uuid.uuid4().hex); temporary.mkdir(parents=True)
        try:
            for role, data in raw.items(): (temporary / (role + '.bin')).write_bytes(data)
            _json_write(temporary / 'baseline.json', record); temporary.replace(directory)
        finally:
            if temporary.exists(): shutil.rmtree(temporary)
    saved, saved_raw = _load(editor, record['id'], car)
    return {'baseline': _public(saved, saved_raw)}


def _offsets(value):
    if not isinstance(value, dict) or not set(value) <= {c[0] for c in CONTROLS}:
        raise ValueError('Invalid donor tuning controls.')
    result = {}
    for key, *_ in CONTROLS:
        v = value.get(key, 0)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 10 or v * 2 != round(v * 2):
            raise ValueError('Donor controls use 0.5% steps from 0% to 10%.')
        result[key] = v
    return result


def evaluate(editor, car, request):
    _core(car, destination=True); value = request['donor_baseline']
    if not isinstance(value, dict): raise ValueError('Invalid donor baseline request.')
    if request.get('parameters') or any(k in request for k in ('tyres', 'conversion_reference', 'reference_basis')):
        raise ValueError('Donor controls cannot be mixed with a manual or median conversion draft. Apply it first, then use manual tuning.')
    record, raw = _load(editor, value.get('id'), car); offsets = _offsets(value.get('offsets', {}))
    baseline = _public(record, raw)
    for control in baseline['controls']:
        if offsets[control['id']] and not control['available']: raise ValueError(control['name'] + ': ' + control['reason'])
    guards = []
    from .bop import Source
    for dep in record['dependencies']:
        path = editor.game / dep['path']; _relative(editor.game, path)
        try: current = BffArchive(path).read(dep['canonical']) if dep['packed'] else path.read_bytes()
        except (ValueError, OSError, LookupError) as exc:
            raise ValueError('A pinned donor component is unavailable. Restore it or capture a new baseline.') from exc
        if _hash(current) != dep['sha']:
            raise ValueError('A pinned donor component changed. Restore it or capture a new baseline; tuning stopped.')
        guards.append(Source(path, dep['canonical'], current, dep['packed']))
    changed = {}
    for p in decode('cdf', raw['cdf']):
        factor = None
        if p.id == 'cdf.power_multiplier.0.0' and offsets['power']: factor = 1 + offsets['power'] / 100
        elif p.id.startswith(('cdf.fw_lift.', 'cdf.rw_lift.')) and offsets['aero']: factor = 1 + offsets['aero'] / 100
        elif p.id.startswith('cdf.brake_torque.') and offsets['braking']: factor = 1 + offsets['braking'] / 100
        elif p.id == 'cdf.cg_height.0.0' and offsets['cornering']: factor = 1 - offsets['cornering'] / 100
        if factor is not None: changed[p.id] = p.value * factor if p.fmt == 'f' or p.promotable else round(p.value * factor)
    physical = raw | {'cdf': edit('cdf', raw['cdf'], changed), 'vdf': private_donor_vdf(raw['vdf'], record['aliases'])}
    replacements, descriptions = [], []
    names = {'cdf': 'Complete donor chassis', 'edf': 'Complete donor engine', 'gdf': 'Complete donor gearbox', 'vdf': 'Complete donor vehicle geometry and component links'}
    for role in CORE:
        for source in car.sources[role]:
            if source.raw != physical[role]: replacements.append((source, physical[role]))
        if car.sources[role][0].raw != physical[role]:
            descriptions.append({'parameter': names[role], 'before': _hash(car.sources[role][0].raw), 'after': _hash(physical[role]), 'unit': 'SHA-256'})
    for key, label, _ in CONTROLS:
        if offsets[key]: descriptions.append({'parameter': label + ' relative to ' + record['donor_name'], 'before': 0, 'after': offsets[key], 'unit': '%'})
    if request.get('target_class') is not None:
        if car.errors.get('crd') or not car.sources.get('crd'): raise ValueError('Candidate class definitions are read-only.')
        target = editor._target(request['target_class'], request.get('group'), request.get('grid'))
        for source in car.sources['crd']:
            out = change_crd(source.raw, target)
            if source.raw != out: replacements.append((source, out))
        for key, v in target.items():
            if car.metadata.get(key) != v: descriptions.append({'parameter': key, 'before': car.metadata.get(key), 'after': v, 'unit': ''})
    after_params = [p for role in ('cdf', 'edf', 'gdf') for p in decode(role, physical[role])]
    return {'car': car, 'sources': replacements, 'guards': guards, 'descriptions': descriptions,
            'before': metrics(car.parameters)[0], 'after': metrics(after_params)[0],
            'donor_baseline': {'id': record['id'], 'donor': record['donor'], 'name': record['donor_name'], 'offsets': offsets}}


def propose(editor, request):
    car = editor._car(request.get('car'))
    staged = {'car': car.id, 'fingerprint': car.fingerprint, 'parameters': {},
              'donor_baseline': {'id': request.get('baseline'), 'offsets': _offsets(request.get('offsets', {}))}}
    move = request.get('move_class', True)
    if not isinstance(move, bool): raise ValueError('Class reassignment must be true or false.')
    if move:
        record, _ = _load(editor, request.get('baseline'), car)
        staged.update(target_class=request.get('target_class') or record['class'],
                      group=request.get('group', record['group']), grid=request.get('grid', record['grid']))
    evaluated = editor._evaluate(staged)
    return {'edit': staged, 'before': evaluated['before'], 'after': evaluated['after'], 'changes': evaluated['descriptions']}
