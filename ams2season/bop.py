"""Installed-car comparisons, homologation drafts and manual BOP editing."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import struct
import threading
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .bff import BffArchive, path_uid
from .bop_files import apply_files, sha, transactions, undo_files, value_patches
from .bop_physics import (METRICS, Parameter, change_crd, crd_properties, decode,
                          edit, edit_tyres, metrics, vdfm_references)
from .liveries import _child, _json_write, _relative


@dataclass
class Source:
    file: Path
    canonical: str
    raw: bytes
    packed: bool


@dataclass
class Car:
    id: str
    name: str
    metadata: dict
    sources: dict[str, list[Source]] = field(default_factory=dict)
    parameters: list[Parameter] = field(default_factory=list)
    errors: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    references: dict = field(default_factory=dict)
    blocked: dict[str, str] = field(default_factory=dict)
    turbo_model: bool | None = None
    linked_sources: dict[str, list[Source]] = field(default_factory=dict)
    linked_errors: dict[str, list[str]] = field(default_factory=dict)

    def power_target_reason(self):
        if self.turbo_model is True:
            return 'Turbo boost is not included in the engine-curve power proxy.'
        if self.turbo_model is None:
            return 'The turbo/boost status could not be established from the installed files.'
        if any(k in self.errors for k in ('vdf', 'cdf', 'edf')):
            return 'Complete, matching chassis and engine files are required.'
        if not metrics(self.parameters)[0].get('power_to_weight'):
            return 'Decoded engine power and mass are unavailable.'
        return ''

    @property
    def fingerprint(self):
        digest = hashlib.sha256()
        logical = set()
        for role, sources in sorted(self.sources.items()):
            for source in sources:
                content = json.dumps(crd_properties(source.raw), sort_keys=True, ensure_ascii=False).encode() if role == 'crd' else source.raw
                logical.add((role, source.canonical.lower(), hashlib.sha256(content).hexdigest()))
        # Identical source copies and XML layout do not change league compatibility.
        for item in sorted(logical): digest.update('\0'.join(item).encode() + b'\n')
        return digest.hexdigest()

    def public(self):
        values, curves = metrics(self.parameters)
        return {'id': self.id, 'name': self.name, 'class': self.metadata.get('Vehicle Class', 'Unclassified'),
                'group': self.metadata.get('Vehicle Group', ''), 'grid': self.metadata.get('Grid Grouping', ''),
                'fingerprint': self.fingerprint, 'metrics': values, 'tyres': self.references.get('tyres'),
                'parameters': len([p for p in self.parameters if p.group != 'RPM']),
                'editable_parameters': len([p for p in self.parameters if p.group != 'RPM' and p.offset >= 0 and p.id.split('.')[0] not in self.blocked]),
                'class_editable': bool(self.sources.get('crd')) and not self.errors.get('crd'),
                'notes': self.notes, 'errors': self.errors,
                'turbo_model': self.turbo_model, 'power_target_reason': self.power_target_reason()}


_PHYSICS = {'vdf': ('vehicles', ('vdfm',)), 'cdf': ('chassis', ('cdfbin', 'cdf')),
            'edf': ('engines', ('edfbin', 'edf')), 'gdf': ('gearbox', ('gdfbin', 'gdf'))}
# Native tyre entries use the HDT type tag even when their hashed path ends in
# .hdtbin. Mod packages may instead store the truncated suffix HDTB.
_EXTENSIONS = {b'crd', b'vdfm', b'cdfb', b'edfb', b'gdfb', b'cdf', b'edf', b'gdf', b'tbfb', b'sdfb', b'hdt', b'hdtb', b'cmfb', b'cbfb', b'fmfb', b'xml'}
_LINKED = {'sdf': ('suspension', 'sdfbin'), 'tyres': ('tyres', 'hdtbin'),
           'cmf': ('clutches', 'cmfbin'), 'fmf': ('failures', 'fmfbin'), 'collision': ('collision', 'xml')}
_EDITABLE_CLASS = {'Vehicle Class', 'Vehicle Group', 'Grid Grouping'}


class BopEditor:
    def __init__(self, app_root: Path, library=None):
        self.app_root = Path(app_root)
        self.root = self.app_root / 'balance_of_performance'
        self.library = library
        self.lock = threading.RLock()
        self.game = None
        self.cars = {}
        self.issues = []
        self.prepared = {}
        self.conversion_cache = {}
        self.source_lookup = None
        config = self.root / 'settings.json'
        self.config = json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}

    @property
    def install_dir(self):
        if self.game is None:
            raise ValueError('Choose your AMS2 folder and scan it first.')
        ident = hashlib.sha256(os.path.normcase(str(self.game)).encode()).hexdigest()[:20]
        return self.root / 'installs' / ident

    def config_info(self):
        path = self.config.get('game_path', '')
        previous = self.app_root / 'livery_editor' / 'settings.json'
        if not path and previous.exists():
            try: path = json.loads(previous.read_text(encoding='utf-8')).get('game_path', '')
            except (OSError, ValueError): pass
        return {'game_path': path, 'scanned': self.game is not None, 'cars': len(self.cars)}

    def scan(self, game_path=None):
        with self.lock:
            value = str(game_path or self.config_info()['game_path']).strip().strip('"')
            if not value:
                raise ValueError('Enter the Automobilista 2 installation folder.')
            game = Path(value).expanduser().resolve()
            pak = _child(game, 'Pakfiles')
            vehicles = _child(pak, 'Vehicles')
            if not vehicles.is_dir():
                raise ValueError('Choose the game folder containing Pakfiles/Vehicles.')
            self.game, self.cars, self.issues, self.prepared = game, {}, [], {}
            self.conversion_cache = {}
            self.source_lookup = None
            loose_root = _child(game, 'Vehicles')
            loose = {}
            candidates = {}
            def candidate(folder, stem):
                if not re.fullmatch(r'[A-Za-z0-9_. -]{1,160}', folder + stem):
                    return
                candidates.setdefault((folder.lower(), stem.lower()), (folder, stem))
            if loose_root.is_dir():
                for p in sorted(loose_root.rglob('*')):
                    if not p.is_file() or p.suffix.lower() not in {'.crd', '.vdfm', '.cdfbin', '.edfbin', '.gdfbin', '.cdf', '.edf', '.gdf', '.tbfbin', '.sdfbin', '.hdtbin', '.cmfbin', '.cbfbin', '.fmfbin', '.xml'}:
                        continue
                    name = _relative(game, p).lower()
                    if name in loose:
                        raise ValueError('Duplicate case-insensitive game paths: ' + name)
                    loose[name] = p
                    if p.suffix.lower() == '.crd': candidate(p.parent.name, p.stem)
            for p in sorted(vehicles.iterdir()):
                if p.is_file() and p.suffix.lower() == '.bff' and not p.stem.lower().endswith(('_cockpit', '_livery', 'persistent')):
                    candidate(p.stem, p.stem)
            # Only indexes are read. Textures/geometry never enter the BOP decoder.
            paths = sorted({p for p in vehicles.iterdir() if p.is_file() and p.suffix.lower() == '.bff'
                            and not p.stem.lower().endswith(('_cockpit', '_livery'))} |
                           {p for p in pak.iterdir() if p.is_file() and p.suffix.lower() == '.bff'
                            and ('persistent' in p.stem.lower() or p.stem.lower() in ('bootflow', 'physicsbootflow'))})
            archive_index = defaultdict(list)
            unreadable = []
            for p in paths:
                try:
                    _relative(game, p)
                    archive = BffArchive(p)
                    for entry in archive.entries:
                        if entry.extension.rstrip(b'\0').lower() in _EXTENSIONS:
                            archive_index[entry.uid].append(archive)
                except (OSError, ValueError) as exc:
                    unreadable.append(p)
                    self.issues.append({'file': _relative(game, p), 'message': str(exc)})
            source_cache = {}
            def sources(canonical):
                canonical = canonical.lower()
                if canonical in source_cache: return source_cache[canonical]
                found, errors = [], []
                if canonical in loose:
                    p = loose[canonical]
                    try:
                        if p.stat().st_size > 8 * 1024 * 1024: raise ValueError('Physics file exceeds 8 MB.')
                        found.append(Source(p, canonical, p.read_bytes(), False))
                    except (OSError, ValueError) as exc: errors.append(_relative(game, p) + ': ' + str(exc))
                for archive in archive_index.get(path_uid(canonical), []):
                    try: found.append(Source(archive.path, canonical, archive.read(canonical), True))
                    except (OSError, ValueError) as exc:
                        message = str(exc)
                        if 'unsupported compression' in message:
                            message += ' (Oodle-packed entries are read-only in this editor.)'
                        errors.append(_relative(game, archive.path) + ' :: ' + canonical + ': ' + message)
                source_cache[canonical] = (found, errors)
                return found, errors
            def component(role, stem):
                folder, extensions = _PHYSICS[role]
                for ext in extensions:
                    found, errors = sources(f'vehicles/physics/{folder}/{stem}.{ext}')
                    if found or errors: return found, errors
                return [], ['No installed ' + role.upper() + ' physics file was found.']
            self.source_lookup = sources
            for (_, ident), (folder, stem) in sorted(candidates.items()):
                definitions, errors = sources(f'vehicles/{folder}/{stem}.crd')
                if not definitions:
                    # Packages unrelated to selectable cars are not empty fake cars.
                    if errors: self.issues.append({'file': stem, 'message': '; '.join(errors)})
                    continue
                try:
                    props = crd_properties(definitions[0].raw)
                    if not props.get('Vehicle Class') or not props.get('Vehicle Physics Model'):
                        raise ValueError('CRD is missing Vehicle Class or Vehicle Physics Model.')
                except (ValueError, UnicodeError) as exc:
                    self.issues.append({'file': stem, 'message': str(exc)})
                    continue
                model = props['Vehicle Physics Model']
                if not re.fullmatch(r'[A-Za-z0-9_. -]{1,160}', model):
                    self.issues.append({'file': stem, 'message': 'Invalid physics-model reference.'})
                    continue
                key = ident if ident not in self.cars else folder.lower() + ':' + ident
                car = Car(key, props.get('Vehicle Name') or props.get('Name') or stem.replace('_', ' '), props,
                          sources={'crd': definitions})
                if errors: car.errors['crd'] = errors
                if any(p.stem.lower() == ident or p.stem.lower() in ('bootpersistent', 'physicspersistent') for p in unreadable):
                    car.errors.setdefault('crd', []).append('A car/boot physics package index could not be read; class editing is disabled.')
                for source in definitions:
                    try:
                        other = crd_properties(source.raw)
                        if other.get('Vehicle Physics Model') != model:
                            raise ValueError('CRD copies disagree about the physics model.')
                        if not _EDITABLE_CLASS <= other.keys():
                            raise ValueError('A CRD copy lacks Vehicle Class, Vehicle Group or Grid Grouping.')
                        if any(other.get(k) != props.get(k) for k in _EDITABLE_CLASS):
                            car.notes.append('Class-definition copies disagree; a class change will synchronize them.')
                    except (ValueError, UnicodeError) as exc:
                        car.errors.setdefault('crd', []).append(str(exc))
                vdf, vdf_errors = component('vdf', model)
                if vdf:
                    car.sources['vdf'] = vdf
                    try:
                        car.references = vdfm_references(vdf[0].raw)
                        if any(s.raw != vdf[0].raw for s in vdf): raise ValueError('VDFM copies disagree; restore/reinstall the mod before editing.')
                    except (ValueError, UnicodeError) as exc: vdf_errors.append(str(exc))
                if vdf_errors:
                    car.errors['vdf'] = vdf_errors
                if not car.references:
                    car.notes.append('Physics lookup uses the CRD model name; a decoded VDFM link is unavailable.')
                turbo_name = car.references.get('tbf')
                turbo_files, turbo_errors = [], []
                if turbo_name:
                    for folder in ('turbos', 'turbo'):
                        found, problems = sources('vehicles/physics/' + folder + '/' + turbo_name + '.tbfbin')
                        turbo_files.extend(found); turbo_errors.extend(problems)
                turbo_present = bool(turbo_files)
                if turbo_name:
                    car.linked_sources['tbf'] = turbo_files
                    if turbo_errors: car.linked_errors['tbf'] = turbo_errors
                for linked_role, (linked_folder, linked_ext) in _LINKED.items():
                    ref = car.references.get(linked_role)
                    if not ref: continue
                    found, problems = sources(f'vehicles/physics/{linked_folder}/{ref}.{linked_ext}')
                    if linked_role == 'cmf' and not found and not problems:
                        found, problems = sources(f'vehicles/physics/clutches/{ref}.cbfbin')
                    car.linked_sources[linked_role] = found
                    if problems: car.linked_errors[linked_role] = problems
                if turbo_present:
                    car.notes.append('Turbo model is present. Engine power figures are unboosted file proxies; validate on track.')
                for role in ('cdf', 'edf', 'gdf'):
                    reference = car.references.get(role) or model
                    found, problems = component(role, reference)
                    if found:
                        car.sources[role] = found
                        try:
                            decoded = decode(role, found[0].raw)
                            if not decoded: raise ValueError('No supported parameters were decoded.')
                            if any(s.raw != found[0].raw for s in found):
                                raise ValueError(role.upper() + ' copies disagree; restore/reinstall the mod before editing.')
                            car.parameters.extend(decoded)
                        except (ValueError, UnicodeError, struct.error) as exc: problems.append(str(exc))
                    if problems: car.errors[role] = problems
                    if problems: car.blocked[role] = '; '.join(problems)
                    if any(p.stem.lower() == ident or p.stem.lower() == 'physicspersistent' for p in unreadable):
                        car.blocked[role] = 'A car/physics package index could not be read; editing is disabled.'
                if vdf_errors: car.blocked['vdf'] = '; '.join(vdf_errors)
                boost = {p.id: p.value for p in car.parameters if p.id.startswith('edf.boost_')}
                boost_default = boost.get('edf.boost_range.0.0', 0) + boost.get('edf.boost_range.0.1', 0) * boost.get('edf.boost_setting.0.0', 0)
                if turbo_present or boost_default > 0:
                    car.turbo_model = True
                elif (car.references and not turbo_errors and not any(k in car.errors for k in ('vdf', 'edf'))
                      and car.sources.get('edf') and not any(p.stem.lower() in (ident, 'physicspersistent') for p in unreadable)):
                    car.turbo_model = False
                self.cars[key] = car
            owners = defaultdict(set)
            for car in self.cars.values():
                for role, found in car.sources.items():
                    for source in found: owners[(role, source.canonical)].add(car.id)
            for car in self.cars.values():
                for role, found in car.sources.items():
                    affected = set().union(*(owners[(role, s.canonical)] for s in found)) - {car.id}
                    if affected:
                        names = ', '.join(self.cars[c].name for c in sorted(affected))
                        car.blocked[role] = 'This physics file is shared with ' + names + '. Per-car editing needs a private physics model.'
                        car.notes.append(car.blocked[role])
            self.config['game_path'] = str(game)
            _json_write(self.root / 'settings.json', self.config)
            return self.listing()

    def classes(self):
        groups = defaultdict(list)
        for car in self.cars.values(): groups[car.metadata['Vehicle Class']].append(car)
        result = []
        for name, cars in sorted(groups.items()):
            specification = Counter((c.metadata.get('Vehicle Group', ''), c.metadata.get('Grid Grouping', '')) for c in cars)
            group, grid = specification.most_common(1)[0][0]
            result.append({'id': name, 'name': name.replace('_', ' '), 'count': len(cars), 'group': group, 'grid': grid,
                           'variants': len(specification)})
        return result

    def listing(self):
        from .car_setups import listing as car_setups
        history = [] if self.game is None else [r for _, r in transactions(self.install_dir / 'backups')]
        return {'game_path': str(self.game) if self.game else '', 'cars': [c.public() for c in self.cars.values()],
                'classes': self.classes(), 'issues': self.issues,
                'metrics': [{'id': k, 'name': n, 'unit': u, 'note': d} for k, n, u, d in METRICS],
                'tyre_models': sorted({c.references['tyres'] for c in self.cars.values() if c.references.get('tyres')}),
                'profiles': self.profiles(), 'car_setups': car_setups(self), 'can_undo': any(r.get('status') == 'applied' for r in history),
                'history': [{k: r.get(k) for k in ('id', 'created', 'changes', 'status')} for r in history[:12]]}

    def _car(self, ident):
        if not isinstance(ident, str) or ident not in self.cars: raise ValueError('This installed car is unavailable. Scan the game folder first.')
        return self.cars[ident]

    def detail(self, ident):
        from .bop_tuning import information
        car = self._car(ident)
        values, curves = metrics(car.parameters)
        params = []
        for p in car.parameters:
            if p.group == 'RPM': continue
            public = p.public()
            problem = car.blocked.get(p.id.split('.')[0])
            if problem: public.update(editable=False, reason=problem)
            params.append(public)
        tyre_editable = bool(car.sources.get('vdf')) and 'vdf' not in car.blocked and 'tyres' in car.references
        tyre_reason = car.blocked.get('vdf', '')
        if tyre_editable:
            try: edit_tyres(car.sources['vdf'][0].raw, 'a')
            except ValueError as exc: tyre_editable, tyre_reason = False, str(exc)
        return car.public() | {'parameters': params, 'curves': curves, 'percentage_categories': information(car),
                               'tyres_editable': tyre_editable, 'tyres_reason': tyre_reason,
                               'sources': [{'role': role, 'path': _relative(self.game, s.file), 'canonical': s.canonical,
                                            'kind': 'Package' if s.packed else 'Loose file'}
                                           for role, found in car.sources.items() for s in found]}

    def comparison(self, target_class, exclude=None):
        members = [c.public() for c in self.cars.values() if c.metadata['Vehicle Class'] == target_class and c.id != exclude]
        def summarize(cars):
            result = {}
            for key, *_ in METRICS:
                values = [c['metrics'][key] for c in cars if c['metrics'].get(key) is not None]
                result[key] = {'count': len(values), 'median': statistics.median(values) if values else None,
                               'min': min(values) if values else None, 'max': max(values) if values else None}
            return result
        modified = set()
        if self.game is not None:
            for _, record in transactions(self.install_dir / 'backups'):
                if record.get('status') == 'applied':
                    modified.update(c.get('id') for c in record.get('changes', []) if isinstance(c, dict) and
                                    any(p.get('parameter') not in _EDITABLE_CLASS for p in c.get('parameters', [])))
        references = [c for c in members if c['id'] not in modified]
        power, excluded = [], []
        for c in members:
            reason = 'Modified by an active Paddock transaction; excluded from the automatic class baseline.' if c['id'] in modified else c['power_target_reason']
            if reason: excluded.append({'car': c['id'], 'name': c['name'], 'reason': reason})
            else: power.append(c)
        return {'class': target_class, 'cars': members, 'summary': summarize(members),
                'reference_summary': summarize(references),
                'reference_cars': [{'car': c['id'], 'fingerprint': c['fingerprint']} for c in references],
                'power_target': {'basis': 'nonboosted_curve_proxy', 'verified': False,
                                 'summary': summarize(power),
                                 'used': [{'car': c['id'], 'name': c['name'], 'fingerprint': c['fingerprint']} for c in power],
                                 'excluded': excluded,
                                 'note': 'Automatic power uses unmodified cars with nonboosted engine curves. Restrictors and engine modifiers remain unmodelled; validate output and pace on track.'},
                'notes': ['These are decoded file values and calculated proxies. Unknown metrics remain unavailable.',
                          'Acceleration, top speed, cornering grip, braking distance and lap time need recorded tests.']}

    def reference_basis(self, comparison, strength, selection, reference=None, mode='class'):
        """Save the actual target sources, independently of raw comparison rows."""
        if mode == 'reference':
            references = [{'car': reference.id, 'fingerprint': reference.fingerprint}]
        elif set(selection) & {'mass', 'body_drag', 'wing_lift', 'brakes'}:
            references = comparison['reference_cars']
        elif set(selection) & {'power', 'power_to_weight'}:
            references = [{'car': c['car'], 'fingerprint': c['fingerprint']} for c in comparison['power_target']['used']]
        else:
            references = []
        return {'version': 1, 'class': comparison['class'], 'mode': mode, 'strength': strength,
                'selection': selection,
                'references': references,
                'power': comparison['power_target'] if mode == 'class' else {
                    'basis': 'reference_curve_proxy', 'verified': False,
                    'used': [{'car': reference.id, 'name': reference.name, 'fingerprint': reference.fingerprint}],
                    'excluded': [], 'reason': reference.power_target_reason()}}

    def _target(self, name, group=None, grid=None):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. +\-]{0,79}', name):
            raise ValueError('Enter a class identifier using letters, numbers, spaces, dots, hyphens or underscores.')
        known = next((c for c in self.classes() if c['id'] == name), None)
        group = str(group if group is not None else known['group'] if known else '')
        grid = str(grid if grid is not None else known['grid'] if known else '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. +\-]{0,79}', group):
            raise ValueError('Enter a vehicle group for the target class.')
        if not re.fullmatch(r'\d{1,4}', grid) or not 0 <= int(grid) <= 1000:
            raise ValueError('Enter an integer grid grouping from 0 to 1000.')
        return {'Vehicle Class': name, 'Vehicle Group': group, 'Grid Grouping': grid}

    def propose(self, body):
        with self.lock:
            car = self._car(body.get('car'))
            target = self._target(body.get('target_class'), body.get('group'), body.get('grid'))
            strength = body.get('strength', 0.6)
            if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= 1:
                raise ValueError('Adjustment strength must be between 0 and 1.')
            axes = body.get('axes', ['mass', 'power_to_weight'])
            if not isinstance(axes, list) or any(not isinstance(a, str) for a in axes) or not set(axes) <= {'mass', 'power_to_weight', 'body_drag', 'wing_lift', 'brakes'}:
                raise ValueError('Choose supported comparison metrics.')
            comparison = self.comparison(target['Vehicle Class'], exclude=car.id)
            if not comparison['cars']:
                raise ValueError('No other installed cars are in this class. Set values manually, or choose a class with reference cars.')
            original, _ = metrics(car.parameters)
            lookup = {p.id: p for p in car.parameters}
            changes, notes, reasons = {}, [], []
            def blend(value, goal):
                return value * (goal / value) ** strength
            def set_value(key, value):
                p = lookup.get(key)
                if p is None or key.split('.')[0] in car.blocked: return False
                if p.fmt != 'f' and not p.promotable: value = round(value)
                if not p.minimum <= value <= p.maximum:
                    notes.append(p.label + ': the proposed value exceeds the supported range; adjust it manually.')
                    return False
                changes[key] = value
                return True
            target_summary = comparison['reference_summary'] | {
                key: comparison['power_target']['summary'][key] for key in ('power_hp', 'power_to_weight', 'peak_torque')}
            def goal(metric): return target_summary[metric]['median']
            new_mass = original['mass']
            if 'mass' in axes and new_mass and goal('mass'):
                proposed = blend(new_mass, goal('mass'))
                if set_value('cdf.mass.0.0', proposed):
                    new_mass = changes['cdf.mass.0.0']
                    reasons.append('Mass moves proportionally toward the class median; the adjustment strength retains part of the difference.')
                else: notes.append('Mass could not be proposed because this chassis is unavailable or shared.')
            if 'power_to_weight' in axes:
                ratio = original.get('power_to_weight')
                if car.power_target_reason():
                    notes.append('Power matching was skipped: ' + car.power_target_reason())
                elif ratio and goal('power_to_weight') and new_mass and original.get('power_kw'):
                    desired_kw = blend(ratio, goal('power_to_weight')) * new_mass / 1000
                    factor = desired_kw / original['power_kw']
                    current = lookup.get('cdf.power_multiplier.0.0')
                    if current and set_value(current.id, current.value * factor):
                        reasons.append('The power multiplier changes power per tonne while retaining the engine curve, revs and gearing.')
                    else: notes.append('A private, editable chassis power multiplier is required for automatic power matching.')
                else: notes.append('Power matching was skipped: no qualified nonboosted reference or complete engine/mass data is available.')
                notes.append(comparison['power_target']['note'])
            if 'body_drag' in axes and original.get('body_drag') and goal('body_drag'):
                set_value('cdf.body_drag.0.0', blend(original['body_drag'], goal('body_drag')))
                reasons.append('Only body base drag moves toward the class median; wing drag remains unchanged.')
            if 'wing_lift' in axes and original.get('wing_lift', 0) and goal('wing_lift') and original['wing_lift'] > 0 and goal('wing_lift') > 0:
                factor = blend(original['wing_lift'], goal('wing_lift')) / original['wing_lift']
                for p in car.parameters:
                    if p.id.startswith(('cdf.fw_lift.', 'cdf.rw_lift.')): set_value(p.id, p.value * factor)
                reasons.append('Front and rear wing lift polynomials scale together, preserving their relative balance. Diffuser values stay as installed.')
            if 'brakes' in axes:
                own = [original.get(k) for k in ('front_brake_torque', 'rear_brake_torque')]
                goals = [goal(k) for k in ('front_brake_torque', 'rear_brake_torque')]
                if all(own) and all(goals):
                    factor = blend(sum(own), sum(goals)) / sum(own)
                    for p in car.parameters:
                        if p.id.startswith('cdf.brake_torque.'): set_value(p.id, p.value * factor)
                    reasons.append('All decoded brake torques scale together, retaining the original front/rear ratio.')
                else: notes.append('Brake torque matching was skipped because front/rear data is incomplete.')
            if len(comparison['cars']) == 1: notes.append('This target class has only one other installed reference car.')
            notes += ['This is a starting BOP draft, not a prediction of equal lap times. Test with the same driver, fuel, tyres and conditions.',
                      'Tyres, gearing, suspension and engine-braking curves stay as installed unless you change them manually.']
            request = {'car': car.id, 'fingerprint': car.fingerprint, 'parameters': changes}
            request['reference_basis'] = self.reference_basis(comparison, strength, axes)
            # Keep the legacy API/profile format; the BOP page opts out of class
            # reassignment, which now belongs to the Car Conversion page.
            if body.get('reassign_class', True):
                request.update(target_class=target['Vehicle Class'], group=target['Vehicle Group'], grid=target['Grid Grouping'])
            evaluated = self._evaluate(request)
            return {'edit': request, 'before': evaluated['before'], 'after': evaluated['after'],
                    'comparison': target_summary, 'power_target': comparison['power_target'], 'reasons': reasons, 'notes': notes}

    def _evaluate(self, request):
        if not isinstance(request, dict): raise ValueError('Invalid car edit.')
        car = self._car(request.get('car'))
        if request.get('fingerprint') != car.fingerprint:
            raise ValueError('The car differs from this draft/profile. Rescan and create a new draft for the installed version.')
        from .bop_tuning import validate
        validate(car, request)
        from .car_setups import validate_draft
        setup_guards = validate_draft(self, car, request)
        if 'donor_baseline' in request:
            from .donor import evaluate
            return evaluate(self, car, request)
        reference = request.get('conversion_reference')
        if reference is not None:
            if not isinstance(reference, dict): raise ValueError('Invalid conversion reference.')
            donor = self._car(reference.get('car'))
            if donor.id == car.id or donor.fingerprint != reference.get('fingerprint'):
                raise ValueError('The conversion reference changed. Rescan and build the conversion again.')
        basis = request.get('reference_basis')
        if basis is not None:
            if not isinstance(basis, dict) or basis.get('version') != 1 or not isinstance(basis.get('references'), list) or len(basis['references']) > 500:
                raise ValueError('Invalid automatic reference basis.')
            if len(json.dumps(basis)) > 500000: raise ValueError('Automatic reference basis is too large.')
            for ref in basis['references']:
                if not isinstance(ref, dict): raise ValueError('Invalid automatic reference car.')
                donor = self._car(ref.get('car'))
                if donor.id == car.id or donor.fingerprint != ref.get('fingerprint'):
                    raise ValueError('An automatic target reference changed. Rescan and build the draft again.')
        values = request.get('parameters', {})
        if not isinstance(values, dict) or len(values) > 3000: raise ValueError('Invalid parameter edits.')
        if any(not isinstance(key, str) for key in values): raise ValueError('Invalid parameter identifier.')
        for key in values:
            if key.split('.')[0] in car.blocked: raise ValueError(car.blocked[key.split('.')[0]])
        known = {p.id: p for p in car.parameters if p.group != 'RPM'}
        if not set(values) <= known.keys(): raise ValueError('This draft contains unavailable parameters.')
        if any(known[key].offset < 0 for key in values):
            raise ValueError('A parameter uses zero-default encoding with no stored value; changing it would resize the binary file.')
        grouped = defaultdict(dict)
        for key, value in values.items():
            role = key.split('.')[0]
            if role in car.blocked: raise ValueError(car.blocked[role])
            grouped[role][key] = value
        new_sources, descriptions = [], []
        for role, changed in grouped.items():
            for source in car.sources[role]:
                raw = edit(role, source.raw, changed)
                if raw != source.raw: new_sources.append((source, raw))
            for key, value in changed.items():
                p = known[key]
                if p.value != value: descriptions.append({'parameter': p.label, 'before': p.value, 'after': value, 'unit': p.unit})
        target_name = request.get('target_class')
        if target_name is not None:
            if car.errors.get('crd') or not car.sources.get('crd'):
                raise ValueError('Class definitions for this car are read-only: ' + '; '.join(car.errors.get('crd', [])))
            target = self._target(target_name, request.get('group'), request.get('grid'))
            for source in car.sources['crd']:
                raw = change_crd(source.raw, target)
                if raw != source.raw: new_sources.append((source, raw))
            for key, value in target.items():
                if value != car.metadata.get(key): descriptions.append({'parameter': key, 'before': car.metadata.get(key), 'after': value, 'unit': ''})
        tyre = request.get('tyres')
        if tyre is not None and tyre != car.references.get('tyres'):
            if 'vdf' in car.blocked: raise ValueError(car.blocked['vdf'])
            models = {c.references.get('tyres') for c in self.cars.values()}
            setup_state = request.get('car_setup') or {}
            pinned_tyre = (setup_state.get('tyre_reference') or {}).get('model') == tyre
            if (tyre not in models and not pinned_tyre) or not car.sources.get('vdf'):
                raise ValueError('Choose a decoded tyre reference from another installed car.')
            for source in car.sources['vdf']:
                raw = edit_tyres(source.raw, tyre)
                new_sources.append((source, raw))
            descriptions.append({'parameter': 'Tyre model', 'before': car.references.get('tyres'), 'after': tyre, 'unit': ''})
        after_parameters = []
        for role in ('cdf', 'edf', 'gdf'):
            sources = car.sources.get(role, [])
            if sources and not car.errors.get(role):
                after_parameters += decode(role, edit(role, sources[0].raw, grouped.get(role, {})))
        before, _ = metrics(car.parameters)
        after, _ = metrics(after_parameters)
        if any(k.startswith(('cdf.gear', 'cdf.final_setting', 'cdf.forward_gears')) for k in values):
            options = {key: len([p for p in after_parameters if p.id.startswith('gdf.' + key + '.') and p.id.endswith('.0')])
                       for key in ('gear', 'final')}
            if not options['gear'] or not options['final']:
                raise ValueError('Gearbox options must be decoded before changing chassis gear selections.')
            for key, value in values.items():
                if key.startswith('cdf.gear') and '_setting.' in key and options['gear'] and not 0 <= value < options['gear']:
                    raise ValueError('A gear default selects an unavailable gearbox option.')
                if key.startswith('cdf.final_setting.') and options['final'] and not 0 <= value < options['final']:
                    raise ValueError('The final-drive default selects an unavailable gearbox option.')
                if key.startswith('cdf.forward_gears.') and options['gear'] and value > options['gear']:
                    raise ValueError('The forward gear count exceeds the installed gearbox options.')
        return {'car': car, 'sources': new_sources, 'descriptions': descriptions, 'before': before, 'after': after, 'guards': setup_guards}

    def preview(self, edits):
        with self.lock:
            if not isinstance(edits, list) or not 1 <= len(edits) <= 500:
                raise ValueError('Stage at least one car change before reviewing.')
            if any(not isinstance(e, dict) or not isinstance(e.get('car'), str) for e in edits):
                raise ValueError('Invalid car edit.')
            if len({e['car'] for e in edits}) != len(edits):
                raise ValueError('A car appears more than once in this draft.')
            grouped, changes, guards = {}, [], {}
            for request in edits:
                evaluated = self._evaluate(request)
                car = evaluated['car']
                # All source copies, including unedited references, must still match the scan.
                guarded_sources = list(car.sources.items())
                guarded_sources.append(('setup dependencies', evaluated.get('guards', [])))
                if request.get('conversion_reference'):
                    donor = self._car(request['conversion_reference']['car'])
                    guarded_sources.extend(donor.sources.items())
                for ref in request.get('reference_basis', {}).get('references', []):
                    guarded_sources.extend(self._car(ref['car']).sources.items())
                for role, sources in guarded_sources:
                    for source in sources:
                        _relative(self.game, source.file)
                        if source.file not in guards: guards[source.file] = sha(source.file)
                        current = BffArchive(source.file).read(source.canonical) if source.packed else source.file.read_bytes()
                        if current != source.raw:
                            raise ValueError('Game files changed since scanning. Scan and create the draft again.')
                for source, raw in evaluated['sources']:
                    group = grouped.setdefault(source.file, {'packed': source.packed, 'values': {}, 'raw': None})
                    if source.packed:
                        if source.canonical in group['values'] and group['values'][source.canonical] != raw:
                            raise ValueError('Two changes conflict in a shared physics stream.')
                        group['values'][source.canonical] = raw
                    else: group['raw'] = raw
                if evaluated['descriptions']:
                    changes.append({'id': car.id, 'name': car.name, 'class_before': car.metadata['Vehicle Class'],
                                    'class_after': request.get('target_class') or car.metadata['Vehicle Class'],
                                    'parameters': evaluated['descriptions'], 'before': evaluated['before'], 'after': evaluated['after'],
                                    **({'donor_baseline': evaluated['donor_baseline']} if 'donor_baseline' in evaluated else {}),
                                    **({'reference_basis': request['reference_basis']} if 'reference_basis' in request else {})})
                    if 'percentage_tuning' in request:
                        changes[-1]['percentage_tuning'] = request['percentage_tuning']
                    if 'car_setup' in request:
                        changes[-1]['car_setup'] = request['car_setup']
            files = []
            for path, group in grouped.items():
                before = guards[path]
                if group['packed']:
                    patches, verify = value_patches(BffArchive(path), group['values'], allow_relocation=any('donor_baseline' in c for c in changes))
                    if not patches: continue
                    item = {'path': path, 'before': before, 'patches': patches, 'verify': verify}
                else:
                    if path.read_bytes() == group['raw']: continue
                    item = {'path': path, 'before': before, 'raw': group['raw']}
                if sha(path) != before: raise ValueError('A game file changed during preview.')
                files.append(item)
            for path, expected in guards.items():
                if sha(path) != expected: raise ValueError('A referenced game file changed during preview.')
            token = uuid.uuid4().hex
            self.prepared = {token: {'created': time.monotonic(), 'files': files, 'changes': changes, 'guards': guards}}
            return {'token': token, 'changes': changes, 'files': [_relative(self.game, f['path']) for f in files],
                    'count': len(files), 'backup_bytes': sum(f['path'].stat().st_size for f in files),
                    'notes': ['The full affected files are backed up before any replacements.',
                                                 'Use the same reviewed BOP profile and mod versions on every league machine.']}

    def apply(self, token):
        with self.lock:
            plan = self.prepared.pop(str(token), None)
            if plan is None or time.monotonic() - plan['created'] > 600:
                raise ValueError('This review expired. Review the draft again.')
            if 'class_set_catalog_hash' in plan:
                from .class_sets import catalog_path
                path = catalog_path(self)
                if not path.exists() or sha(path) != plan['class_set_catalog_hash']:
                    raise ValueError('Saved custom classes changed after preview. Review the class changes again.')
            result = apply_files(self.game, self.install_dir / 'backups', plan['files'], plan['changes'], plan['guards'])
            self.scan(str(self.game))
            return result

    def undo(self):
        with self.lock:
            result = undo_files(self.game, self.install_dir / 'backups')
            self.scan(str(self.game))
            return result

    def profiles(self):
        result = []
        for p in sorted((self.root / 'profiles').glob('*.json')):
            try:
                value = json.loads(p.read_text(encoding='utf-8'))
                result.append({'id': p.stem, 'name': value['name'], 'cars': len(value['edits'])})
            except (ValueError, KeyError, OSError): continue
        return result

    def profile(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident): raise ValueError('Invalid profile identifier.')
        path = self.root / 'profiles' / (ident + '.json')
        if not path.exists(): raise ValueError('This BOP profile is unavailable.')
        return json.loads(path.read_text(encoding='utf-8'))

    def import_profile(self, value, save=True):
        with self.lock:
            if not isinstance(value, dict) or value.get('format') != 'ams2season-bop' or value.get('version') != 1:
                raise ValueError('This is not a supported Balance of Performance profile.')
            name = value.get('name')
            edits = value.get('edits')
            if not isinstance(name, str) or not name.strip() or len(name) > 100:
                raise ValueError('Enter a profile name of 1 to 100 characters.')
            if not isinstance(edits, list) or not 1 <= len(edits) <= 500:
                raise ValueError('A profile needs 1 to 500 car edits.')
            if any(not isinstance(e, dict) or not isinstance(e.get('car'), str) for e in edits): raise ValueError('Invalid car edit.')
            if len({e['car'] for e in edits}) != len(edits): raise ValueError('Duplicate car in profile.')
            clean = []
            for request in edits:
                self._evaluate(request)
                clean.append({k: request[k] for k in ('car', 'fingerprint', 'parameters', 'target_class', 'group', 'grid', 'tyres', 'conversion_reference', 'reference_basis', 'donor_baseline', 'percentage_tuning', 'car_setup') if k in request})
            profile = {'format': 'ams2season-bop', 'version': 1, 'name': name.strip(), 'edits': clean}
            if not save: return profile
            ident = uuid.uuid4().hex
            _json_write(self.root / 'profiles' / (ident + '.json'), profile)
            return {'id': ident, 'profile': profile}

    def route(self, method, path, query, body):
        # HTTP server is threaded: reads and writes use one editor lock.
        with self.lock:
            if not isinstance(body, dict): raise ValueError('BOP requests require a JSON object.')
            if method == 'GET' and path == '/api/bop/config': return self.config_info()
            if method == 'POST' and path == '/api/bop/scan': return self.scan(body.get('game_path'))
            if method == 'GET' and path == '/api/bop': return self.listing()
            if method == 'GET' and path == '/api/bop/car': return self.detail(query.get('car'))
            if path.startswith('/api/bop/car-setups'):
                from . import car_setups
                if method == 'GET' and path == '/api/bop/car-setups': return {'setups': car_setups.listing(self)}
                if method == 'GET' and path == '/api/bop/car-setups/file': return car_setups.get(self, query.get('id'))
                if method == 'POST' and path == '/api/bop/car-setups/capture': return car_setups.capture(self, body)
                if method == 'POST' and path == '/api/bop/car-setups/load': return car_setups.prepare(self, body.get('car'), car_setups.get(self, body.get('id')))
                if method == 'POST' and path == '/api/bop/car-setups/import': return car_setups.import_setup(self, body)
            if method == 'GET' and path == '/api/bop/comparison': return self.comparison(query.get('class'), query.get('exclude'))
            if path in ('/api/bop/class-sets', '/api/bop/class-sets/preview'):
                from . import class_sets
                if method == 'GET' and path == '/api/bop/class-sets': return class_sets.listing(self)
                if method == 'POST' and path == '/api/bop/class-sets': return class_sets.create(self, body)
                if method == 'POST' and path == '/api/bop/class-sets/preview': return class_sets.preview(self, body)
            if method == 'POST' and path == '/api/bop/propose': return self.propose(body)
            if method == 'POST' and path == '/api/bop/tune':
                from .bop_tuning import stage
                return stage(self, body)
            if method == 'GET' and path == '/api/bop/conversion/info':
                from .conversion import information
                return information(self, query.get('car'), query.get('class'))
            if method == 'POST' and path == '/api/bop/conversion/propose':
                from .conversion import propose
                return propose(self, body)
            if method == 'GET' and path == '/api/bop/donor/info':
                from .donor import information
                return information(self, query.get('car'))
            if method == 'POST' and path == '/api/bop/donor/capture':
                from .donor import capture
                return capture(self, body)
            if method == 'POST' and path == '/api/bop/donor/propose':
                from .donor import propose
                return propose(self, body)
            if method == 'POST' and path == '/api/bop/evaluate':
                evaluated = self._evaluate(body)
                return {'before': evaluated['before'], 'after': evaluated['after']}
            if method == 'POST' and path == '/api/bop/preview': return self.preview(body.get('edits'))
            if method == 'POST' and path == '/api/bop/apply': return self.apply(body.get('token'))
            if method == 'POST' and path == '/api/bop/undo': return self.undo()
            if method == 'GET' and path == '/api/bop/profile': return self.profile(query.get('id'))
            if method == 'POST' and path == '/api/bop/profiles': return self.import_profile(body)
            if method == 'POST' and path == '/api/bop/profile/validate': return self.import_profile(body, save=False)
            if method == 'GET' and path == '/api/bop/recordings':
                return {'recordings': [r for r in self.library.recordings() if r.get('type') == 'race' and r.get('status') == 'complete' and r.get('raced')]} if self.library else {'recordings': []}
            if method == 'GET' and path == '/api/bop/measured':
                if not self.library: raise ValueError('Recorded race data is unavailable.')
                data = self.library.race_cars_page(query.get('recording'), None)
                return {k: data.get(k) for k in ('meta', 'cars', 'car_extra')}
            raise LookupError('Unknown Balance of Performance request.')
