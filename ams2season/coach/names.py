"""Private spoken identities. Recording and championship names remain untouched."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from ..identities import entrant_id
from .crew_spotter import sounds_path


class RadioNames:
    def __init__(self, root, *, sounds=None):
        self.path = Path(root) / 'private_coach' / 'radio_names.json'
        self.sounds = Path(sounds) if sounds is not None else sounds_path()
        self.data = {'revision': '', 'personal': '', 'lineup': None}
        self.error = None
        self.runtime_error = None
        self.bound_race = None
        self.catalog = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(data, dict) or not isinstance(data.get('personal', ''), str):
                    raise ValueError('Invalid radio name settings.')
                self.data.update(data)
            except (OSError, ValueError) as exc:
                self.error = str(exc)
        self.runtime_path = self.path.with_name('radio_name_runtime.json')
        try:
            runtime = json.loads(self.runtime_path.read_text(encoding='utf-8'))
            if runtime.get('lineup') == (self.data.get('lineup') or {}).get('id'):
                self.bound_race = runtime.get('race')
        except (OSError, ValueError, TypeError):
            pass

    def catalogue(self):
        if self.catalog is None:
            base = self.sounds / 'personalisations'
            personal = sorted((p.name for p in base.iterdir() if p.is_dir()), key=str.casefold) if base.is_dir() else []
            base = self.sounds / 'driver_names'
            drivers = sorted({p.stem for p in base.glob('*.wav')}, key=str.casefold)
            self.catalog = {'personal_names': personal, 'drivers': drivers,
                            'source': 'Installed Crew Chief sounds (read only)',
                            'available': bool(personal), 'private': True}
        return self.catalog

    def _write(self, data, revision):
        if self.error:
            raise ValueError('The saved radio name file could not be read; it has been preserved: ' + self.error)
        disk_revision = json.loads(self.path.read_text(encoding='utf-8')).get('revision', '') if self.path.exists() else ''
        if revision != self.data['revision'] or revision != disk_revision:
            raise ValueError('Radio names changed in another window. Reload before saving.')
        data = {**data, 'revision': uuid.uuid4().hex}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)
        if self.data.get('lineup') != data.get('lineup'):
            self.bound_race = None
        self.data, self.error, self.runtime_error = data, None, None
        return self.status()

    def set_personal(self, name, revision):
        if not isinstance(name, str) or name and name not in self.catalogue()['personal_names']:
            raise ValueError('Choose a personal name from the installed name catalogue.')
        return self._write({**self.data, 'personal': name}, revision)

    @staticmethod
    def qualifying(lib, recording):
        path = lib.recording_path(recording)
        raw = (path / 'session.json').read_bytes()
        meta = json.loads(raw)
        if meta.get('session_type') != 'qualify' or meta.get('status') != 'complete':
            raise ValueError('Choose a completed qualifying recording.')
        entrants, names = [], set()
        final = sorted(meta.get('final') or [], key=lambda p: (
            float(p.get('fastest_lap') or 1e9) if (p.get('fastest_lap') or 0) > 0 else 1e9,
            int(p.get('race_pos') or 999)))
        for i, p in enumerate(final):
            name, car = str(p.get('name') or '').strip(), str(p.get('car') or '').strip()
            if not name or not car or name in names:
                raise ValueError('Qualifying has missing or ambiguous entrant identities.')
            names.add(name)
            entrants.append({'id': entrant_id(name, car), 'name': name, 'car': car, 'position': i + 1,
                             'best_lap': p.get('fastest_lap') if (p.get('fastest_lap') or 0) > 0 else None})
        if not entrants:
            raise ValueError('This qualifying recording has no recorded entrants.')
        return {'recording': recording, 'fingerprint': hashlib.sha256(raw).hexdigest(),
                'track': meta.get('track_location'), 'layout': meta.get('track_variation'),
                'length': meta.get('track_length'), 'started_at': meta.get('started_at'),
                'local_name': (meta.get('local') or {}).get('name'), 'entrants': entrants}

    def review(self, lib, recording, champ):
        source = self.qualifying(lib, recording)
        cfg = lib.champ_config(champ)
        if cfg is None:
            raise ValueError('Choose a championship with a driver roster.')
        lineup = self.data.get('lineup') or {}
        choices = lineup.get('assignments', {}) if (lineup.get('champ') == champ and
            lineup.get('source', {}).get('fingerprint') == source['fingerprint']) else {}
        return {**source, 'champ': champ, 'champ_name': cfg.name, 'drivers': cfg.drivers,
                'revision': self.data['revision'], 'assignments': choices}

    def assign(self, lib, recording, champ, assignments, revision):
        review = self.review(lib, recording, champ)
        if not isinstance(assignments, dict):
            raise ValueError('Choose a championship driver for each assigned entrant.')
        entrants = {p['id']: p for p in review['entrants']}
        drivers = {d['key']: d for d in review['drivers']}
        if set(assignments) - entrants.keys():
            raise ValueError('Unknown qualifying entrant.')
        used, chosen, spoken = set(), {}, {}
        for ident, key in assignments.items():
            if key in ('', None):
                continue
            if not isinstance(key, str) or key not in drivers or key in used:
                raise ValueError('Assign each championship driver at most once.')
            used.add(key)
            chosen[ident] = key
            spoken[ident] = {'recorded_name': entrants[ident]['name'], 'car': entrants[ident]['car'],
                             'display': drivers[key].get('display') or key, 'driver_key': key}
        # Unassigned entrants use their AMS2 names. Do not allow one alias to sound
        # like another still-unassigned entrant (especially a human friend).
        audible = [spoken.get(p['id'], {}).get('display', p['name']).casefold() for p in review['entrants']]
        if len(audible) != len(set(audible)):
            raise ValueError('Two entrants would have the same spoken name. Resolve that conflict first.')
        source = {k: v for k, v in review.items() if k not in ('drivers', 'champ_name', 'revision', 'assignments', 'champ')}
        return self._write({**self.data, 'lineup': {'id': uuid.uuid4().hex, 'champ': champ, 'source': source,
                            'assignments': chosen, 'spoken': spoken}}, revision)

    def live_mapping(self, tick, driver, *, now=None, race_id=None):
        lineup = self.data.get('lineup') or {}
        source = lineup.get('source') or {}
        if tick.session not in ('qualify', 'race') or not tick.fresh:
            return {}
        if (source.get('track'), source.get('layout'), source.get('local_name')) != (tick.track, tick.layout, driver):
            return {}
        try:
            stamp = datetime.fromisoformat(source['started_at'])
            if stamp.tzinfo is None:
                stamp = stamp.astimezone()
            age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
            if not 0 <= age <= 4 * 3600 or abs(float(source['length']) - tick.length) > 5:
                return {}
        except (ValueError, TypeError, KeyError):
            return {}
        if tick.session == 'race':
            race_id = race_id or tick.session_id
            if self.bound_race is None:
                temporary = self.runtime_path.with_name(self.runtime_path.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    temporary.write_text(json.dumps({'lineup': lineup.get('id'), 'race': race_id}), encoding='utf-8')
                    os.replace(temporary, self.runtime_path)
                except OSError as exc:
                    self.runtime_error = 'Race name binding could not be saved; using AMS2 names: ' + str(exc)
                    return {}
                finally:
                    temporary.unlink(missing_ok=True)
                self.bound_race = race_id
            if self.bound_race != race_id:
                return {}
        keys = [(c.name, c.car) for c in tick.cars]
        out = {}
        for fact in (lineup.get('spoken') or {}).values():
            pair = (fact['recorded_name'], fact['car'])
            if keys.count(pair) == 1 and sum(c.name == pair[0] for c in tick.cars) == 1:
                out[pair[0]] = fact['display']
        return out

    def status(self):
        lineup = self.data.get('lineup') or {}
        source = lineup.get('source') or {}
        return {'revision': self.data['revision'], 'personal': self.data['personal'],
                'error': self.error or self.runtime_error, 'lineup': {'champ': lineup.get('champ'), 'recording': source.get('recording'),
                'track': source.get('track'), 'layout': source.get('layout'),
                'assigned': len(lineup.get('assignments') or {}), 'bound_race': self.bound_race}}
