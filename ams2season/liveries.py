"""Installed livery catalog, reversible selections, and league presets.

The catalog remembers the RCFs seen before restrictions, so turning a livery
back on does not depend on a name that has already been removed from the game.
All state is separate from race-analysis settings and championship databases.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .bff import BffArchive, path_uid


_ID = re.compile(r'^[0-9]+$')
_ATTRS = re.compile(r'([\w:-]+)\s*=\s*([\'"])(.*?)\2', re.S)


def _attrs(tag: str) -> dict:
    return {k.upper(): html.unescape(v) for k, _, v in _ATTRS.findall(tag)}


def rcf_liveries(raw: bytes) -> list[dict]:
    if len(raw) > 8 * 1024 * 1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsupported RCF document.')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError('Invalid RCF XML: ' + str(exc)) from exc
    names = next((e for e in root.iter('NAMES') if e.get('INPUT', '').upper() == 'LIVERY'), None)
    if names is None:
        raise ValueError('The RCF has no livery list.')
    rows = [{'id': e.get('LIVERY', ''), 'name': e.get('NAME', '')}
            for e in names.findall('NAME')]
    if not rows or len(rows) > 10_000 or any(not _ID.fullmatch(e['id']) for e in rows):
        raise ValueError('The RCF has unsupported livery IDs.')
    if len({e['id'] for e in rows}) != len(rows):
        raise ValueError('The RCF has duplicate livery IDs.')
    return rows


def select_rcf(raw: bytes, enabled: list[str]) -> bytes:
    """Keep source formatting and all material/tire/dirt declarations intact."""
    catalog = rcf_liveries(raw)
    keep = set(enabled)
    if not keep or not keep <= {e['id'] for e in catalog}:
        raise ValueError('Choose at least one livery from the saved catalog.')
    text = raw.decode('utf-8-sig').rstrip()
    def input_count(match):
        tag = match.group(0)
        if _attrs(tag).get('NAME', '').upper() != 'LIVERY':
            return tag
        return re.sub(r'(\bOPTIONS\s*=\s*)([\'"])[^\'"]*\2',
                      lambda m: m[1] + m[2] + str(len(keep)) + m[2], tag, flags=re.I)
    text = re.sub(r'<INPUT\b[^>]*?/\s*>', input_count, text, flags=re.I)
    def names(match):
        block = match.group(0)
        if _attrs(block.split('>', 1)[0]).get('INPUT', '').upper() != 'LIVERY':
            return block
        return re.sub(r'<NAME\b[^>]*?/\s*>',
                      lambda m: m[0] if _attrs(m[0]).get('LIVERY') in keep else '', block, flags=re.I)
    text = re.sub(r'<NAMES\b[^>]*>.*?</NAMES\s*>', names, text, flags=re.I | re.S)
    def condition(match):
        block = match.group(0)
        ident = _attrs(block.split('>', 1)[0]).get('LIVERY')
        return '' if ident is not None and ident not in keep else block
    text = re.sub(r'<CONDITION\b[^>]*>.*?</CONDITION\s*>', condition, text, flags=re.I | re.S)
    out = text.encode('utf-8')
    result = rcf_liveries(out)
    if {r['id'] for r in result} != keep:
        raise ValueError('Could not build the requested livery list.')
    root = ET.fromstring(out)
    inp = next((e for e in root.iter('INPUT') if e.get('NAME') == 'LIVERY'), None)
    if inp is None or inp.get('OPTIONS') != str(len(keep)):
        raise ValueError('Could not update the livery count.')
    return out


def _sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _json_write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _child(parent: Path, name: str) -> Path:
    p = parent / name
    if p.exists() or not parent.is_dir():
        return p
    return next((x for x in parent.iterdir() if x.name.casefold() == name.casefold()), p)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError('A game file resolves outside the chosen game folder.') from exc


def _game_running() -> bool:
    if os.name != 'nt':
        return False
    try:
        result = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True,
                                text=True, timeout=8, creationflags=0x08000000)
        names = {row[0].lower() for row in csv.reader(io.StringIO(result.stdout)) if row}
        return bool(names & {'ams2.exe', 'ams2avx.exe', 'ams2avx2.exe'})
    except (OSError, subprocess.SubprocessError):
        return False


def _crd_metadata(raw: bytes) -> dict:
    # Some Thunderflash CRDs include a stray closing tag: read only prop tags.
    props = {}
    for tag in re.findall(r'<prop\b[^>]*>', raw.decode('utf-8', errors='replace'), re.I):
        attrs = _attrs(tag)
        if 'DATA' in attrs:
            props[attrs.get('NAME', '')] = attrs['DATA']
    return {'name': props.get('Vehicle Name') or props.get('ShortVehicleName'),
            'class': (props.get('Vehicle Class') or '').replace('_', ' ')}


@dataclass
class Source:
    file: Path
    canonical: str
    raw: bytes
    kind: str


@dataclass
class Car:
    id: str
    name: str
    car_class: str
    stem: str
    sources: list[Source]
    baseline: dict[str, bytes]
    liveries: list[dict]
    enabled: list[str]
    errors: list[str] = field(default_factory=list)

    def public(self):
        active = set(self.enabled)
        return {'id': self.id, 'name': self.name, 'class': self.car_class or 'Unclassified',
                'liveries': [{**e, 'enabled': e['id'] in active} for e in self.liveries],
                'enabled': self.enabled, 'total': len(self.liveries),
                'sources': sorted({s.kind for s in self.sources}),
                'editable': not self.errors, 'errors': self.errors,
                'needs_sync': any({r['id'] for r in rcf_liveries(s.raw)} != active for s in self.sources)}


class LiveryEditor:
    def __init__(self, app_root: Path):
        self.root = Path(app_root) / 'livery_editor'
        self.lock = threading.RLock()
        self.game: Path | None = None
        self.cars: dict[str, Car] = {}
        self.issues: list[dict] = []
        self.prepared = {}
        self.preview_cache = {}
        self.preview_archives = {}
        self.config_file = self.root / 'settings.json'
        self.config = json.loads(self.config_file.read_text()) if self.config_file.exists() else {}

    @property
    def install_dir(self):
        if self.game is None:
            raise ValueError('Choose your Automobilista 2 folder and scan it first.')
        ident = hashlib.sha256(os.path.normcase(str(self.game)).encode()).hexdigest()[:20]
        return self.root / 'installs' / ident

    def config_info(self):
        suggestions = []
        if os.name == 'nt':
            bases = [Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Steam']
            bases += [Path(letter + ':\\SteamLibrary') for letter in 'CDEFGHIJKLMNOPQRSTUVWXYZ']
            for base in bases:
                candidate = base / 'steamapps' / 'common' / 'Automobilista 2'
                if candidate.is_dir():
                    suggestions.append(str(candidate))
        return {'game_path': self.config.get('game_path', ''), 'suggestions': suggestions,
                'scanned': self.game is not None, 'cars': len(self.cars)}

    def _archive(self, path: Path, cache: dict) -> BffArchive | None:
        if path in cache:
            return cache[path]
        try:
            cache[path] = BffArchive(path)
        except (ValueError, OSError) as exc:
            cache[path] = None
            self.issues.append({'file': path.name, 'message': str(exc)})
        return cache[path]

    def scan(self, game_path: str | None = None):
        with self.lock:
            value = str(game_path or self.config.get('game_path') or '').strip().strip('"')
            if not value:
                raise ValueError('Enter the Automobilista 2 installation folder.')
            game = Path(value).expanduser().resolve()
            pak = _child(game, 'Pakfiles')
            packed_cars = _child(pak, 'Vehicles')
            if not packed_cars.is_dir():
                raise ValueError('Choose the game folder containing Pakfiles/ Vehicles, not the app or MODS folder.')
            self.game, self.cars, self.issues = game, {}, []
            self.prepared.clear()
            self.preview_cache.clear()
            self.preview_archives.clear()
            self.config['game_path'] = str(game)
            _json_write(self.config_file, self.config)
            cache, candidates = {}, {}
            loose_root = _child(game, 'Vehicles')
            main_files = {p.stem.lower(): p for p in packed_cars.iterdir()
                          if p.is_file() and p.suffix.lower() == '.bff'
                          and not p.stem.lower().endswith(('_cockpit', '_livery', 'persistent'))}
            def candidate(folder, stem):
                key = (folder.lower(), stem.lower())
                candidates.setdefault(key, {'folder': folder, 'stem': stem, 'loose': {}, 'crd': None})
                return candidates[key]
            for stem in main_files:
                candidate(stem, stem)
            if loose_root.is_dir():
                for folder in sorted(loose_root.iterdir()):
                    if not folder.is_dir():
                        continue
                    for p in folder.iterdir():
                        if not p.is_file():
                            continue
                        if p.suffix.lower() == '.rcf':
                            stem = re.sub(r'_hr$', '', p.stem, flags=re.I)
                            row = candidate(folder.name, stem)
                            row['loose'][p.stem.lower().endswith('_hr')] = p
                        elif p.suffix.lower() == '.crd':
                            candidate(folder.name, p.stem)['crd'] = p
            shared, menu_errors = [], []
            for folder in (packed_cars, pak):
                for p in folder.iterdir():
                    if p.is_file() and p.suffix.lower() == '.bff' and p.stem.lower() == 'vehiclespersistent':
                        archive = self._archive(p, cache)
                        if archive:
                            shared.append(archive)
                        else:
                            menu_errors.append('The shared menu package could not be read; editing is disabled.')
            for (folder, stem), row in sorted(candidates.items()):
                sources, errors = [], list(menu_errors)
                metadata = {}
                main = main_files.get(stem)
                archives = list(shared)
                if main:
                    archive = self._archive(main, cache)
                    if archive:
                        archives.append(archive)
                    else:
                        errors.append('The car package could not be read; editing this car is disabled.')
                for hr in (False, True):
                    canonical = 'vehicles/' + folder + '/' + stem + ('_hr' if hr else '') + '.rcf'
                    for archive in archives:
                        if not archive.has(canonical):
                            continue
                        try:
                            raw = archive.read(canonical)
                            rcf_liveries(raw)
                            kind = 'Menu package' if archive in shared else 'Car package'
                            sources.append(Source(archive.path, canonical, raw, kind))
                        except (ValueError, OSError) as exc:
                            errors.append(str(exc))
                    if hr in row['loose']:
                        try:
                            p = row['loose'][hr]
                            raw = p.read_bytes()
                            rcf_liveries(raw)
                            sources.append(Source(p, canonical, raw, 'Loose RCF'))
                        except (ValueError, OSError) as exc:
                            errors.append(str(exc))
                if not sources:
                    continue
                try:
                    if row['crd']:
                        metadata = _crd_metadata(row['crd'].read_bytes())
                    else:
                        crd_name = 'vehicles/' + folder + '/' + stem + '.crd'
                        for archive in archives:
                            if archive.has(crd_name):
                                metadata = _crd_metadata(archive.read(crd_name))
                                break
                except (ValueError, OSError):
                    pass
                baseline = {}
                for canonical in {s.canonical for s in sources}:
                    best = max((s.raw for s in sources if s.canonical == canonical), key=lambda raw: len(rcf_liveries(raw)))
                    saved = self.install_dir / 'catalog' / (format(path_uid(canonical), '016x') + '.rcf')
                    if saved.exists():
                        old = saved.read_bytes()
                        old_ids = {e['id'] for e in rcf_liveries(old)}
                        new_ids = {e['id'] for e in rcf_liveries(best)}
                        if new_ids < old_ids:
                            best = old
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    if not saved.exists() or saved.read_bytes() != best:
                        saved.write_bytes(best)
                    baseline[canonical] = best
                normal = next((s for s in sources if not s.canonical.lower().endswith('_hr.rcf')), sources[0])
                liveries = rcf_liveries(baseline[normal.canonical])
                enabled = [e['id'] for e in rcf_liveries(normal.raw)]
                for canonical, raw in baseline.items():
                    if not {e['id'] for e in liveries} <= {e['id'] for e in rcf_liveries(raw)}:
                        errors.append('Normal and HR livery IDs differ; this car needs manual review.')
                car_id = stem if folder == stem else folder + '--' + stem
                self.cars[car_id] = Car(car_id, metadata.get('name') or stem.replace('_', ' ').title(),
                                        metadata.get('class') or '', stem, sources, baseline, liveries, enabled,
                                        list(dict.fromkeys(errors)))
            return self.overview()

    def overview(self):
        return {**self.config_info(), 'cars': [c.public() for c in sorted(self.cars.values(), key=lambda c: c.name.lower())],
                'issues': self.issues, 'presets': self.presets(), 'can_undo': self._last_transaction() is not None}

    def import_catalog(self, original_path: str):
        """Recover pre-editor restrictions from a user's original BFF/RCF backup."""
        with self.lock:
            if not self.cars:
                raise ValueError('Scan the installed cars before importing their original catalog.')
            path = Path(str(original_path).strip().strip('"')).expanduser()
            if not path.is_file():
                raise ValueError('Enter the full path to an original BFF or RCF file.')
            with path.open('rb') as file:
                packed = file.read(4) == b' KAP'
            archive = BffArchive(path) if packed else None
            if archive is None and path.suffix.lower() != '.rcf':
                raise ValueError('Choose an original BFF or RCF file.')
            updates, touched = {}, set()
            for car in self.cars.values():
                for canonical in car.baseline:
                    if archive:
                        if not archive.has(canonical):
                            continue
                        raw = archive.read(canonical)
                    elif Path(canonical).name.lower() == path.name.lower():
                        raw = path.read_bytes()
                    else:
                        continue
                    original = rcf_liveries(raw)
                    lookup = {e['id']: e['name'] for e in original}
                    installed = {e['id']: e['name'] for s in car.sources if s.canonical == canonical for e in rcf_liveries(s.raw)}
                    if any(lookup.get(key) != name for key, name in installed.items()):
                        raise ValueError('This original has different livery IDs or names for ' + car.name + '. No catalog was imported.')
                    if not {e['id'] for e in rcf_liveries(car.baseline[canonical])} <= set(lookup):
                        continue
                    updates[canonical] = raw
                    touched.add(car.id)
            if not updates:
                raise ValueError('No matching installed car RCFs were found in this original file.')
            for canonical, raw in updates.items():
                target = self.install_dir / 'catalog' / (format(path_uid(canonical), '016x') + '.rcf')
                target.write_bytes(raw)
            result = self.scan(str(self.game))
            result['imported_cars'] = len(touched)
            return result

    def _selections(self, selections) -> dict[str, list[str]]:
        if not isinstance(selections, dict) or not selections:
            raise ValueError('Choose at least one car to update.')
        result = {}
        for key, values in selections.items():
            car = self.cars.get(key)
            if car is None:
                raise ValueError('A selected car is not installed: ' + str(key))
            if car.errors:
                raise ValueError(car.name + ': ' + car.errors[0])
            if not isinstance(values, list) or any(not isinstance(x, (int, str)) or isinstance(x, bool) for x in values):
                raise ValueError('Livery selections must be lists of IDs.')
            ids = [str(x) for x in values]
            if len(set(ids)) != len(ids) or not ids or not set(ids) <= {e['id'] for e in car.liveries}:
                raise ValueError('Keep at least one known livery for ' + car.name + '.')
            result[key] = [e['id'] for e in car.liveries if e['id'] in set(ids)]
        return result

    def preview(self, selections):
        with self.lock:
            selected = self._selections(selections)
            grouped, expected, summaries = {}, {}, []
            for ident, ids in selected.items():
                car = self.cars[ident]
                summaries.append({'id': ident, 'name': car.name, 'before': len(car.enabled), 'after': len(ids)})
                for source in car.sources:
                    _relative(self.game, source.file)
                    data = select_rcf(car.baseline[source.canonical], ids)
                    group = grouped.setdefault(source.file, {'kind': source.kind, 'rcfs': {}, 'loose': None})
                    if source.kind == 'Loose RCF':
                        if source.file.read_bytes() != source.raw:
                            raise ValueError('Game files changed since the scan. Scan again before applying.')
                        group['loose'] = data
                    else:
                        group['rcfs'][source.canonical] = data
                    expected[(source.file, source.canonical)] = source.raw
            files = []
            for path, group in grouped.items():
                before = _sha(path)
                if group['loose'] is not None:
                    if path.read_bytes().rstrip() == group['loose'].rstrip():
                        continue
                    patches = None
                else:
                    archive = BffArchive(path)
                    for name in group['rcfs']:
                        if archive.read(name) != expected[(path, name)]:
                            raise ValueError('Game files changed since the scan. Scan again before applying.')
                    patches = archive.patches(group['rcfs'])
                    if not patches:
                        continue
                if _sha(path) != before:
                    raise ValueError('Game files changed during preview. Scan again.')
                files.append({'path': path, 'before': before, 'kind': group['kind'], 'patches': patches,
                              'loose': group['loose'], 'verify': group['rcfs']})
            token = uuid.uuid4().hex
            self.prepared = {token: {'created': time.monotonic(), 'files': files, 'cars': summaries}}
            return {'token': token, 'cars': summaries, 'files': [{'path': _relative(self.game, f['path']), 'kind': f['kind']} for f in files],
                    'count': len(files), 'liveries': sum(len(x) for x in selected.values())}

    def apply(self, token: str):
        with self.lock:
            plan = self.prepared.pop(str(token), None)
            if plan is None or time.monotonic() - plan['created'] > 600:
                raise ValueError('The preview expired. Preview your selection again.')
            if _game_running():
                raise ValueError('Close Automobilista 2 before applying livery changes.')
            files = plan['files']
            if not files:
                return {'ok': True, 'changed': 0, 'message': 'These selections are already installed.'}
            for item in files:
                if _sha(item['path']) != item['before']:
                    raise ValueError('Game files changed after preview. Scan and preview again.')
            tx_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
            directory = self.install_dir / 'backups' / tx_id
            directory.mkdir(parents=True)
            record = {'id': tx_id, 'created': datetime.now(timezone.utc).isoformat(),
                      'game_path': str(self.game), 'cars': plan['cars'], 'files': [], 'status': 'prepared'}
            staged, committed = [], []
            try:
                # Finish every backup and validate every staged file before replacing any game file.
                for index, item in enumerate(files):
                    target = item['path']
                    backup = directory / (str(index) + '.original')
                    shutil.copy2(target, backup)
                    if _sha(backup) != item['before']:
                        raise ValueError('A game file changed while making its backup. Nothing was applied.')
                    tmp = target.with_name('.' + target.name + '.livery-' + uuid.uuid4().hex + '.tmp')
                    staged.append(tmp)
                    if item['patches'] is None:
                        tmp.write_bytes(item['loose'])
                        rcf_liveries(tmp.read_bytes())
                    else:
                        shutil.copy2(backup, tmp)
                        with tmp.open('r+b') as f:
                            for offset, data in item['patches']:
                                f.seek(offset)
                                f.write(data)
                            f.flush()
                            os.fsync(f.fileno())
                        check = BffArchive(tmp)
                        for name, raw in item['verify'].items():
                            if check.read(name).rstrip() != raw.rstrip():
                                raise ValueError('Staged BFF verification failed. Nothing was applied.')
                    record['files'].append({'path': _relative(self.game, target), 'backup': backup.name,
                                            'before': item['before'], 'after': _sha(tmp)})
                _json_write(directory / 'transaction.json', record)
                for item in files:
                    if _sha(item['path']) != item['before']:
                        raise ValueError('Game files changed before applying. Nothing was applied.')
                for item, tmp in zip(files, staged):
                    os.replace(tmp, item['path'])
                    committed.append(item['path'])
                record['status'] = 'applied'
                _json_write(directory / 'transaction.json', record)
            except Exception as exc:
                rollback_errors = []
                for target in reversed(committed):
                    index = [f['path'] for f in files].index(target)
                    try:
                        shutil.copy2(directory / (str(index) + '.original'), target)
                    except OSError as problem:
                        rollback_errors.append(str(problem))
                record['status'] = 'rollback_failed' if rollback_errors else 'rolled_back'
                _json_write(directory / 'transaction.json', record)
                if rollback_errors:
                    raise ValueError('Apply failed. Some files need restoring from ' + str(directory)) from exc
                raise ValueError('No livery changes were kept. Close AMS2 and your content manager, then try again. ' + str(exc)) from exc
            finally:
                for tmp in staged:
                    tmp.unlink(missing_ok=True)
            self.scan(str(self.game))
            return {'ok': True, 'changed': len(files), 'backup': str(directory), 'cars': plan['cars']}

    def _last_transaction(self):
        if self.game is None:
            return None
        directory = self.install_dir / 'backups'
        if not directory.exists():
            return None
        for file in sorted(directory.glob('*/transaction.json'), reverse=True):
            try:
                value = json.loads(file.read_text())
                if value.get('status') == 'applied':
                    return file, value
            except (OSError, ValueError):
                continue
        return None

    def undo(self):
        with self.lock:
            pair = self._last_transaction()
            if pair is None:
                raise ValueError('There is no livery apply to undo.')
            if _game_running():
                raise ValueError('Close Automobilista 2 before restoring livery changes.')
            journal, record = pair
            staged, committed = [], []
            current_dir = journal.parent / 'undo-current'
            current_dir.mkdir(exist_ok=True)
            try:
                targets = []
                for index, item in enumerate(record['files']):
                    target = self.game / item['path']
                    _relative(self.game, target)
                    original = journal.parent / item['backup']
                    if _sha(target) != item['after'] or _sha(original) != item['before']:
                        raise ValueError('Files changed since the last apply. Undo stopped to preserve those changes.')
                    shutil.copy2(target, current_dir / str(index))
                    tmp = target.with_name('.' + target.name + '.livery-' + uuid.uuid4().hex + '.tmp')
                    staged.append(tmp)
                    shutil.copy2(original, tmp)
                    targets.append(target)
                for target, item in zip(targets, record['files']):
                    if _sha(target) != item['after']:
                        raise ValueError('Files changed during restore. Undo stopped.')
                for target, tmp in zip(targets, staged):
                    os.replace(tmp, target)
                    committed.append(target)
                record['status'] = 'undone'
                _json_write(journal, record)
            except Exception:
                for index, target in reversed(list(enumerate(committed))):
                    shutil.copy2(current_dir / str(index), target)
                raise
            finally:
                for tmp in staged:
                    tmp.unlink(missing_ok=True)
            self.scan(str(self.game))
            return {'ok': True, 'restored': len(committed)}

    def presets(self):
        if self.game is None:
            return []
        folder = self.install_dir / 'presets'
        result = []
        for path in sorted(folder.glob('*.json')):
            try:
                data = json.loads(path.read_text())
                result.append({'id': path.stem, 'name': data['name'], 'cars': len(data['selections'])})
            except (OSError, ValueError, KeyError):
                continue
        return result

    def save_preset(self, body):
        with self.lock:
            name = str(body.get('name', '')).strip()
            if not name or len(name) > 80:
                raise ValueError('Give the preset a name of 1–80 characters.')
            selections = self._selections(body.get('selections'))
            ident = hashlib.sha256(name.casefold().encode()).hexdigest()[:20]
            data = {'format': 'ams2season-liveries', 'version': 1, 'name': name, 'selections': selections}
            _json_write(self.install_dir / 'presets' / (ident + '.json'), data)
            return {'ok': True, 'id': ident, 'presets': self.presets()}

    def load_preset(self, ident):
        with self.lock:
            if not re.fullmatch(r'[a-f0-9]{20}', str(ident)):
                raise LookupError('Preset not found.')
            path = self.install_dir / 'presets' / (ident + '.json')
            if not path.exists():
                raise LookupError('Preset not found.')
            return json.loads(path.read_text())

    def preview_image(self, car_id: str, ident: str) -> bytes:
        from PIL import Image
        with self.lock:
            car = self.cars.get(car_id)
            if car is None or ident not in {e['id'] for e in car.liveries}:
                raise LookupError('Livery preview not found.')
            key = (car_id, ident)
            if key in self.preview_cache:
                return self.preview_cache[key]
            relative = f'gui/vehicleimages/vehicleimages_{car.stem}/{car.stem}_livery_{ident}.dds'
            folder = self.game
            for part in relative.split('/'):
                folder = _child(folder, part)
            raw = folder.read_bytes() if folder.is_file() else None
            if raw is None:
                pak = _child(self.game, 'Pakfiles')
                for file in pak.iterdir():
                    if not file.is_file() or file.suffix.lower() != '.bff' or 'vehicleimages' not in file.stem.lower():
                        continue
                    archive = self.preview_archives.get(file)
                    if archive is False:
                        continue
                    if archive is None:
                        try:
                            archive = BffArchive(file)
                            self.preview_archives[file] = archive
                        except (ValueError, OSError):
                            self.preview_archives[file] = False
                            continue
                    if archive.has(relative):
                        try:
                            raw = archive.read(relative, limit=32 * 1024 * 1024)
                        except (ValueError, OSError):
                            continue
                        break
            if raw is None:
                raise LookupError('No installed preview image for this livery.')
            try:
                image = Image.open(io.BytesIO(raw)).convert('RGBA')
                image.thumbnail((640, 320))
                buffer = io.BytesIO()
                image.save(buffer, format='PNG')
            except (OSError, ValueError) as exc:
                raise LookupError('This livery preview format cannot be displayed.') from exc
            self.preview_cache[key] = buffer.getvalue()
            return self.preview_cache[key]

    def route(self, method: str, path: str, query: dict, body: dict):
        if method == 'GET' and path == '/api/liveries/config':
            return self.config_info()
        if method == 'POST' and path == '/api/liveries/scan':
            return self.scan(body.get('game_path'))
        if method == 'POST' and path == '/api/liveries/catalog-import':
            return self.import_catalog(body.get('original_path', ''))
        if method == 'GET' and path == '/api/liveries':
            return self.overview()
        if method == 'POST' and path == '/api/liveries/preview':
            return self.preview(body.get('selections'))
        if method == 'POST' and path == '/api/liveries/apply':
            return self.apply(body.get('token'))
        if method == 'POST' and path == '/api/liveries/undo':
            return self.undo()
        if method == 'POST' and path == '/api/liveries/presets':
            return self.save_preset(body)
        if method == 'GET' and path == '/api/liveries/presets':
            return {'presets': self.presets()}
        if method == 'GET' and path == '/api/liveries/preset':
            return self.load_preset(query.get('id', ''))
        raise LookupError('Unknown livery editor request.')
