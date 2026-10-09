"""One-car physics presets: installed settings plus drafts, staged before apply."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import struct
import uuid

from .bop_physics import crd_properties, decode, edit, edit_tyres
from .liveries import _json_write

FORMAT = 'ams2season-car-setup'
VERSION = 1
_CLASS = {'Vehicle Class', 'Vehicle Group', 'Grid Grouping'}
_CONTEXT = ('percentage_tuning', 'conversion_reference', 'reference_basis')


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100:
        raise ValueError('Enter a car setup name of 1 to 100 characters.')
    return value.strip()


def _editable(car):
    return {p.id: p for p in car.parameters if p.group != 'RPM' and p.offset >= 0 and p.id.split('.')[0] not in car.blocked}


def _normal(role, raw, blocked):
    if role == 'crd':
        return json.dumps({k: v for k, v in crd_properties(raw).items() if k not in _CLASS}, sort_keys=True).encode()
    if not blocked and role in ('cdf', 'edf', 'gdf'):
        # Canonicalize editable numbers, including documented integer-to-float
        # widening. Unknown data, engine RPM axes and zero-default records stay
        # byte-exact, so tuning is portable but a different mod version is not.
        values = {}
        for p in decode(role, raw):
            if p.group == 'RPM' or p.offset < 0:
                continue
            if p.fmt == 'f' or p.promotable:
                values[p.id] = .125 if p.minimum <= .125 <= p.maximum else min(p.minimum + .125, p.maximum)
            else:
                values[p.id] = math.ceil(p.minimum)
        return edit(role, raw, values)
    if role == 'vdf' and not blocked:
        try: return edit_tyres(raw, 'a')
        except ValueError: pass  # Read-only tyre links retain their exact version.
    return raw


def compatibility(editor, car):
    key = ('car-setup-compatibility', car.fingerprint, tuple(sorted(car.blocked)))
    if key not in editor.conversion_cache:
        logical = set()
        for role, sources in car.sources.items():
            for source in sources:
                raw = _normal(role, source.raw, role in car.blocked)
                logical.add((role, source.canonical, hashlib.sha256(raw).hexdigest()))
        for role, sources in car.linked_sources.items():
            if role == 'tyres': continue
            for source in sources:
                logical.add((role, source.canonical, hashlib.sha256(source.raw).hexdigest()))
        editor.conversion_cache[key] = hashlib.sha256(json.dumps(sorted(logical)).encode()).hexdigest()
    return editor.conversion_cache[key]


def _tyres(editor, model):
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}', model) or not editor.source_lookup:
        return [], None
    sources, errors = editor.source_lookup(f'vehicles/physics/tyres/{model}.hdtbin')
    if not sources or errors or len({s.raw for s in sources}) != 1:
        return [], None
    return sources, hashlib.sha256(sources[0].raw).hexdigest()


def validate_draft(editor, car, request):
    """Retain version and dependency guards through subsequent manual edits."""
    state = request.get('car_setup')
    if state is None: return []
    if not isinstance(state, dict) or set(state) - {'version', 'name', 'compatibility', 'tyre_reference'} or type(state.get('version')) is not int or state.get('version') != VERSION:
        raise ValueError('Invalid car setup draft metadata.')
    _name(state.get('name'))
    if state.get('compatibility') != compatibility(editor, car):
        raise ValueError('This car setup uses a different physics model or mod version. Rescan and use a matching setup.')
    guards = [s for sources in car.linked_sources.values() for s in sources]
    pin = state.get('tyre_reference')
    if pin is not None:
        model = request.get('tyres', car.references.get('tyres'))
        if not isinstance(pin, dict) or set(pin) != {'model', 'hash'} or pin.get('model') != model:
            raise ValueError('The car setup tyre reference differs from this draft.')
        sources, digest = _tyres(editor, model)
        if not sources or digest != pin['hash']:
            raise ValueError('The car setup tyre model is missing, unreadable or changed. Use a matching installed tyre version.')
        guards.extend(sources)
    return guards


def listing(editor):
    result = []
    for path in sorted((editor.root / 'car_setups').glob('*.json')):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if value.get('format') != FORMAT or value.get('version') != VERSION or not isinstance(value.get('car'), str): continue
            result.append({'id': path.stem, 'name': _name(value['name']), 'car': value['car'],
                           'car_name': value.get('car_name', value['car']), 'kind': value.get('kind')})
        except (OSError, ValueError, KeyError, AttributeError): continue
    return result


def get(editor, ident):
    if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise ValueError('Invalid car setup identifier.')
    path = editor.root / 'car_setups' / (ident + '.json')
    if not path.exists(): raise ValueError('This saved car setup is unavailable.')
    return json.loads(path.read_text(encoding='utf-8'))


def _save(editor, setup):
    ident = uuid.uuid4().hex
    _json_write(editor.root / 'car_setups' / (ident + '.json'), setup)
    return {'id': ident, 'setup': setup}


def capture(editor, body, save=True):
    car = editor._car(body.get('car'))
    request = body.get('edit')
    if request is None: request = {'car': car.id, 'fingerprint': car.fingerprint, 'parameters': {}}
    if not isinstance(request, dict) or request.get('car') != car.id:
        raise ValueError('Save a draft for the selected car only.')
    editor._evaluate(request)
    setup = {'format': FORMAT, 'version': VERSION, 'name': _name(body.get('name')), 'car': car.id, 'car_name': car.name}
    if 'donor_baseline' in request:
        # Whole donor drafts retain their local snapshot identity and strict
        # starting fingerprint. Export contains references, never game binaries.
        setup.update(kind='donor-draft', edit=copy.deepcopy(request))
    else:
        values = request.get('parameters', {})
        settings = {'parameters': {key: values.get(key, p.value) for key, p in _editable(car).items()},
                    'target_class': request.get('target_class', car.metadata['Vehicle Class']),
                    'group': request.get('group', car.metadata['Vehicle Group']),
                    'grid': request.get('grid', car.metadata['Grid Grouping']),
                    'tyres': request.get('tyres', car.references.get('tyres'))}
        context = {key: copy.deepcopy(request[key]) for key in _CONTEXT if key in request}
        setup.update(kind='settings', compatibility=compatibility(editor, car), settings=settings, context=context)
        _, digest = _tyres(editor, settings['tyres'])
        if digest: setup['tyre_reference'] = {'model': settings['tyres'], 'hash': digest}
    # Also validate snapshots with no draft, including complete numeric captures.
    prepare(editor, car.id, setup)
    return _save(editor, setup) if save else setup


def _same(p, value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value): return False
    if p.fmt == 'f' or p.promotable and int(value) != value:
        try: value = struct.unpack('<f', struct.pack('<f', value))[0]
        except (OverflowError, struct.error): return False
    return value == p.value


def prepare(editor, ident, value):
    car = editor._car(ident)
    if not isinstance(value, dict) or value.get('format') != FORMAT or type(value.get('version')) is not int or value.get('version') != VERSION:
        raise ValueError('Choose a supported individual car setup file.')
    if len(json.dumps(value)) > 2 * 1024 * 1024: raise ValueError('Car setups must be smaller than 2 MB.')
    if value.get('car') != car.id:
        raise ValueError('This setup belongs to a different car. Select its car before importing or loading it.')
    name = _name(value.get('name'))
    if value.get('kind') == 'donor-draft':
        request = copy.deepcopy(value.get('edit'))
        if not isinstance(request, dict) or request.get('car') != car.id or 'donor_baseline' not in request:
            raise ValueError('Invalid complete donor car draft.')
    elif value.get('kind') == 'settings':
        if value.get('compatibility') != compatibility(editor, car):
            raise ValueError('This car setup uses a different physics model or mod version. Rescan and use a matching setup.')
        settings, context = value.get('settings'), value.get('context', {})
        known = _editable(car)
        if not isinstance(settings, dict) or set(settings) != {'parameters', 'target_class', 'group', 'grid', 'tyres'} or not isinstance(settings['parameters'], dict) or set(settings['parameters']) != set(known):
            raise ValueError('The car setup must contain the complete set of supported, private parameters.')
        if not isinstance(context, dict) or set(context) - set(_CONTEXT): raise ValueError('Invalid car setup context.')
        parameters = settings['parameters']
        # Validate even unchanged saved values; pruning must not hide malformed
        # values or values outside the current decoder's supported bounds.
        grouped = {role: {key: v for key, v in parameters.items() if key.startswith(role + '.')} for role in ('cdf', 'edf', 'gdf')}
        for role, changed in grouped.items():
            if changed: edit(role, car.sources[role][0].raw, changed)
        request = {'car': car.id, 'fingerprint': car.fingerprint, 'parameters': {}, **copy.deepcopy(context),
                   'car_setup': {'version': VERSION, 'name': name, 'compatibility': value['compatibility']}}
        for key, target in parameters.items():
            # Preserve exact percentage math when storage rounding differs from
            # a metadata baseline, even if it encodes to the installed float.
            if not _same(known[key], target) or 'percentage_tuning' in context and not math.isclose(known[key].value, target, rel_tol=1e-8, abs_tol=1e-9):
                request['parameters'][key] = target
        target = editor._target(settings['target_class'], settings['group'], settings['grid'])
        if any(car.metadata.get(key) != v for key, v in target.items()):
            request.update({key: settings[key] for key in ('target_class', 'group', 'grid')})
        tyre = settings['tyres']
        if tyre is not None and (not isinstance(tyre, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}', tyre)):
            raise ValueError('Invalid car setup tyre model.')
        if tyre is None and car.references.get('tyres') is not None:
            raise ValueError('A car setup cannot remove the installed tyre model reference.')
        if tyre != car.references.get('tyres'): request['tyres'] = tyre
        if 'tyre_reference' in value: request['car_setup']['tyre_reference'] = copy.deepcopy(value['tyre_reference'])
    else: raise ValueError('Unsupported car setup kind.')
    evaluated = editor._evaluate(request)
    return {'edit': request, 'before': evaluated['before'], 'after': evaluated['after']}


def import_setup(editor, body):
    value = body.get('setup')
    if isinstance(value, dict) and value.get('format') == 'ams2season-bop':
        legacy = editor.import_profile(value, save=False)
        if len(legacy['edits']) != 1:
            raise ValueError('Use the league profile importer for files containing multiple cars.')
        value = capture(editor, {'car': body.get('car'), 'name': legacy['name'], 'edit': legacy['edits'][0]}, save=False)
    result = prepare(editor, body.get('car'), value)
    return _save(editor, copy.deepcopy(value)) | result
