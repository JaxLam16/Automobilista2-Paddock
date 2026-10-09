"""Manual livery facts, kept separate from championship driver identities.

Raw recording files are never rewritten. Names are projected into an in-memory
Session; the database retains the original entrant name for steward corrections.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlencode

FILE = 'livery_assignments.json'


def norm(value):
    return ' '.join(str(value).casefold().split())


def entrant_id(name, car):
    return hashlib.sha256(json.dumps([str(name), str(car)], ensure_ascii=False).encode()).hexdigest()[:24]


def read(path):
    file = Path(path) / FILE
    if not file.exists():
        return {'version': 1, 'revision': '', 'reviewed': False, 'assignments': {}}
    return validate_facts(json.loads(file.read_text(encoding='utf-8')))


def validate_facts(data):
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('assignments'), dict):
        raise ValueError('Unsupported recording livery assignments.')
    if not isinstance(data.get('reviewed'), bool) or not re.fullmatch(r'[0-9a-f]{32}', str(data.get('revision', ''))):
        raise ValueError('Invalid recording livery review revision.')
    for ident, fact in data['assignments'].items():
        if not re.fullmatch(r'[0-9a-f]{24}', ident) or not isinstance(fact, dict):
            raise ValueError('Invalid recorded entrant livery assignment.')
        if not all(isinstance(fact.get(k), str) and fact[k] for k in ('car_id', 'livery_id', 'name', 'recorded_car')):
            raise ValueError('A saved livery assignment is missing its car or entrant identity.')
        color_override(fact.get('color_override'))
        color_override(fact.get('color'))
    return data


def revision(path, cfg):
    return read(path)['revision'] if cfg and cfg.livery_ai else ''


def preview_color(data):
    """Estimate a paint accent, ignoring transparent and near-neutral background pixels."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert('RGBA')
            image.thumbnail((80, 50))
            rgba = image.tobytes()
            pixels = [(r, g, b) for r, g, b, a in zip(rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4])
                      if a >= 128 and max(r, g, b) > 24 and min(r, g, b) < 248]
        if not pixels:
            return None
        accents = [p for p in pixels if max(p) - min(p) >= 45]
        samples = accents if len(accents) >= len(pixels) * .12 else pixels
        groups = {}
        for pixel in samples:
            groups.setdefault(tuple(c // 32 for c in pixel), []).append(pixel)
        dominant = max(groups.values(), key=len)
        return '#' + ''.join(f'{round(sum(p[i] for p in dominant) / len(dominant)):02X}' for i in range(3))
    except (ValueError, OSError):
        return None


def color_override(value):
    if value in (None, ''):
        return None
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise ValueError('Replay color must be a six-digit hex color.')
    return value.upper()


def appearance(binding):
    """Small display payload; catalog preview is kept separate from top-down car icons."""
    if not binding or not binding.get('livery_id'):
        return None
    result = {k: binding.get(k) for k in ('car_id', 'car_name', 'livery_id', 'livery_name')}
    result['image'] = ('data:image/png;base64,' + binding['preview']) if binding.get('preview') else (
        '/api/liveries/image?' + urlencode({'car': binding['car_id'], 'livery': binding['livery_id']}))
    result['color'] = color_override(binding.get('color_override')) or color_override(binding.get('color'))
    return result


def snapshot(editor, car_id, livery_id, previous=None):
    if previous and previous.get('car_id') == str(car_id) and previous.get('livery_id') == str(livery_id):
        out = dict(previous)  # historical names/pictures survive later mod catalog changes
        if not out.get('preview'):
            try:
                image = editor.preview_image(str(car_id), str(livery_id))
                if len(image) <= 1024 * 1024:
                    out['preview'] = base64.b64encode(image).decode('ascii')
            except (LookupError, ValueError, OSError):
                pass
        if not out.get('color') and out.get('preview'):
            try:
                out['color'] = preview_color(base64.b64decode(out['preview']))
            except ValueError:
                pass
        return out
    car = editor.cars.get(str(car_id))
    livery = next((x for x in car.liveries if str(x['id']) == str(livery_id)), None) if car else None
    if not livery:
        raise ValueError('That car/livery is not in the installed catalog. Scan liveries first.')
    out = {'car_id': str(car_id), 'car_name': car.name, 'livery_id': str(livery_id), 'livery_name': livery['name']}
    try:
        image = editor.preview_image(str(car_id), str(livery_id))
        if len(image) <= 1024 * 1024:
            out['preview'] = base64.b64encode(image).decode('ascii')
            out['color'] = preview_color(image)
    except (LookupError, ValueError, OSError):
        pass  # missing previews never prevent an explicit assignment
    return out


def validate_roster(drivers):
    names, aliases, paints = set(), {}, set()
    for driver in drivers:
        display = norm(driver['display'])
        if display in names:
            raise ValueError('Each roster driver needs a different display name.')
        names.add(display)
        for name in [driver['display'], driver['key'], *driver.get('aliases', [])]:
            n = norm(name)
            if n in aliases and aliases[n] != driver['key']:
                raise ValueError('A name or alias belongs to more than one roster driver.')
            aliases[n] = driver['key']
        binding = driver.get('livery') or {}
        if driver.get('role', 'human') != 'ai' and not binding:
            continue
        if not all(binding.get(k) for k in ('car_id', 'livery_id', 'recorded_car')):
            raise ValueError('A driver livery selection needs a car, livery and recorded car model.')
        color_override(binding.get('color_override'))
        paint = (binding['car_id'], binding['livery_id'])
        if paint in paints:
            raise ValueError('Two roster drivers cannot share the same car/livery.')
        paints.add(paint)


def driver_mapping(sess, cfg, facts=None):
    """Recorded name -> AI roster record. Human aliases always take precedence."""
    if not cfg or not cfg.livery_ai:
        return {}
    facts = read(sess.path)['assignments'] if facts is None else facts
    roster = {(d['livery']['car_id'], d['livery']['livery_id']): d for d in cfg.drivers
              if d.get('role') == 'ai' and d.get('livery')}
    mapping, used = {}, set()
    present = sess.frames[['name', 'car']].drop_duplicates()
    for name, car in present.itertuples(index=False, name=None):
        fact = facts.get(entrant_id(name, car))
        if not fact or norm(name) in cfg.human_names():
            continue
        driver = roster.get((fact['car_id'], fact['livery_id']))
        if not driver or norm(driver['livery']['recorded_car']) != norm(car):
            continue
        if driver['key'] in used:
            raise ValueError('A fictional driver is assigned to two recorded entrants. Edit livery assignments.')
        if name in mapping or (sess.frames.name == driver['display']).any():
            # An unchanged name is allowed only for that very entrant.
            if driver['display'] != name or name in mapping:
                raise ValueError('A fictional driver name conflicts with a recorded entrant. Rename the fictional driver.')
        used.add(driver['key'])
        mapping[name] = driver
    return mapping


def project_session(path, cfg):
    from .derive import Session, load_session
    sess = load_session(path)
    mapping = driver_mapping(sess, cfg)
    rename = {name: d['display'] for name, d in mapping.items()}
    # Only identity-bearing fields and event grid keys are rewritten in memory.
    def project(value, field=None):
        if isinstance(value, dict):
            return {rename.get(k, k) if field == 'grid' else k: project(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [project(v, field) for v in value]
        return rename.get(value, value) if isinstance(value, str) and field in ('name', 'other', 'driver', 'label') else value
    frames, local = sess.frames.copy(), sess.local.copy()
    for df in (frames, local):
        if 'name' in df:
            df['name'] = df.name.replace(rename)
    meta = project(copy.deepcopy(sess.meta))
    meta['_recorded_names'] = {d['display']: name for name, d in mapping.items()}
    meta['_livery_drivers'] = {d['display']: d['key'] for d in mapping.values()}
    meta['_livery_appearance'] = session_appearance(sess, cfg, rename)
    return Session(sess.path, meta, frames, local, project(sess.events))


def session_appearance(sess, cfg, rename=None):
    if not cfg or not cfg.livery_ai:
        return {}
    facts, out = read(sess.path), {}
    humans = {norm(n): d for d in cfg.drivers if d.get('role', 'human') != 'ai'
              for n in [d['key'], d['display'], *d.get('aliases', [])]}
    for name, car in sess.frames[['name', 'car']].drop_duplicates().itertuples(index=False, name=None):
        binding = facts['assignments'].get(entrant_id(name, car))
        # A reviewed Unknown stays unknown. Human roster defaults apply only before review.
        if not binding and not facts['reviewed']:
            candidate = humans.get(norm(name), {}).get('livery') or {}
            if norm(candidate.get('recorded_car', '')) == norm(car):
                binding = candidate
        display = appearance(binding)
        if display:
            out[(rename or {}).get(name, name)] = display
    return out


def save(path, assignments, entrants, editor, cfg, expected_revision):
    """Replace this review atomically; reject stale windows and ambiguous identities."""
    previous = read(path)
    if expected_revision != previous['revision']:
        raise ValueError('Assignments changed in another window. Reopen the assignment screen.')
    allowed = {e['id']: e for e in entrants}
    if not isinstance(assignments, dict) or set(assignments) - set(allowed):
        raise ValueError('Assignments must refer to recorded entrants in this race.')
    out, used = {}, set()
    for ident, choice in assignments.items():
        if not choice:
            continue
        if not isinstance(choice, dict):
            raise ValueError('Choose a catalog car and livery for each assigned entrant.')
        car_id, livery_id = str(choice.get('car_id', '')), str(choice.get('livery_id', ''))
        paint = (car_id, livery_id)
        if paint in used:
            raise ValueError('Two entrants share this car/livery. Leave the ambiguous entries unknown until resolved.')
        used.add(paint)
        old = previous['assignments'].get(ident)
        fact = snapshot(editor, car_id, livery_id, old)
        override = color_override(choice.get('color_override'))
        fact.pop('color_override', None)
        if override:
            fact['color_override'] = override
        entrant = allowed[ident]
        # Explicit car-model confirmation permits translated SHM vs catalog names.
        if norm(choice.get('recorded_car', '')) != norm(entrant['car']):
            raise ValueError('Confirm the recorded car model for this livery.')
        fact.update({'name': entrant['name'], 'recorded_car': entrant['car']})
        out[ident] = fact
    data = {'version': 1, 'revision': uuid.uuid4().hex, 'reviewed': True, 'assignments': out}
    from .derive import load_session
    driver_mapping(load_session(path), cfg, out)  # validate before replacing the prior review
    target = Path(path) / FILE
    tmp = target.with_name(FILE + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return data
