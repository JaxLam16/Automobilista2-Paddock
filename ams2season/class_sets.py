"""Saved custom classes; original assignments follow the reversible BOP journal.

Only CRD class/group/grid properties are edited. Removing a member restores
those properties against the current files, so subsequent tuning is retained.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from .bop_files import sha, transactions
from .liveries import _json_write


FIELDS = ('Vehicle Class', 'Vehicle Group', 'Grid Grouping')
FORMAT = 'ams2season-class-sets'


def catalog_path(editor):
    return editor.install_dir / 'class_sets.json'


def _catalog(editor):
    path = catalog_path(editor)
    if not path.exists():
        return {'format': FORMAT, 'version': 1, 'classes': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if (data.get('format') != FORMAT or data.get('version') != 1 or
                not isinstance(data.get('classes'), list) or len(data['classes']) > 100):
            raise ValueError()
        ids, names = set(), set()
        for item in data['classes']:
            if not re.fullmatch(r'[a-f0-9]{32}', item['id']):
                raise ValueError()
            editor._target(item['name'], item['group'], item['grid'])
            if item['id'] in ids or item['name'].casefold() in names:
                raise ValueError()
            ids.add(item['id'])
            names.add(item['name'].casefold())
        return data
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Saved custom classes are invalid. Keep class_sets.json and its backups for recovery.') from exc


def _assignment(car):
    return {key: car.metadata.get(key) for key in FIELDS}


def _members(editor):
    """Replay successful applies in order; Undo automatically removes their effect."""
    members = {}
    for _, record in reversed(transactions(editor.install_dir / 'backups')):
        if record.get('status') != 'applied':
            continue
        for change in record.get('changes', []):
            tag = change.get('class_set')
            if tag is None:
                continue
            try:
                if (tag['version'] != 1 or not isinstance(tag['member'], bool) or
                        not re.fullmatch(r'[a-f0-9]{32}', tag['id']) or
                        any(set(tag[key]) != set(FIELDS) or
                            any(not isinstance(v, str) for v in tag[key].values())
                            for key in ('original', 'assigned'))):
                    raise ValueError()
                if tag['member']:
                    members[change['id']] = tag
                else:
                    members.pop(change['id'], None)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ValueError('A custom-class backup record is invalid. Preserve the backup for recovery.') from exc
    return members


def listing(editor):
    catalog = _catalog(editor)
    members = _members(editor)
    by_id = {c['id']: c for c in catalog['classes']}
    by_name = {c['name'].casefold(): c for c in catalog['classes']}
    rows = []
    for ident in sorted(set(editor.cars) | set(members)):
        car, tag = editor.cars.get(ident), members.get(ident)
        owner = by_id.get(tag['id']) if tag else None
        reason = ''
        if not car:
            reason = 'Car is missing from this scan. Restore its files and scan again before removing it.'
        elif tag and (_assignment(car) != tag['assigned'] or not owner):
            reason = 'Class assignment changed outside this manager. Restore the saved assignment and scan again before moving this car.'
        elif not tag and car.metadata.get('Vehicle Class', '').casefold() in by_name:
            reason = 'Already in a custom class without a saved original assignment. Move it to its original class in Car Conversion first.'
        elif not car.sources.get('crd') or car.errors.get('crd'):
            reason = 'Class definitions are unavailable or disagree. ' + '; '.join(car.errors.get('crd', []))
        rows.append({'id': ident, 'name': car.name if car else ident,
                     'class': car.metadata.get('Vehicle Class', '') if car else 'Unavailable',
                     'original_class': tag['original']['Vehicle Class'] if tag else None,
                     'member_of': tag['id'] if tag else None,
                     'member_name': owner['name'] if owner else None,
                     'fingerprint': car.fingerprint if car else None, 'reason': reason})
    result = {'classes': [dict(c, members=[r['id'] for r in rows if r['member_of'] == c['id']])
                          for c in catalog['classes']], 'cars': rows}
    result['revision'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def create(editor, body):
    catalog = _catalog(editor)
    name = body.get('name')
    if not isinstance(name, str):
        raise ValueError('Enter a name for the new class.')
    name = name.strip()
    seed = next((c for c in editor.classes() if c['id'] == body.get('base_class')), None)
    if not seed:
        raise ValueError('Choose an installed class to use as the starting group.')
    target = editor._target(name, seed['group'], seed['grid'])
    if any(c['id'].casefold() == name.casefold() for c in editor.classes()) or any(
            c['name'].casefold() == name.casefold() for c in catalog['classes']):
        raise ValueError('That class name already exists. Choose a new name.')
    if len(catalog['classes']) >= 100:
        raise ValueError('This installation already has 100 saved custom classes.')
    ident = uuid.uuid4().hex
    catalog['classes'].append({'id': ident, 'name': target['Vehicle Class'],
                               'group': target['Vehicle Group'], 'grid': target['Grid Grouping'],
                               'created': datetime.now(timezone.utc).isoformat()})
    _json_write(catalog_path(editor), catalog)
    return {'id': ident, **listing(editor)}


def preview(editor, body):
    current = listing(editor)
    if body.get('revision') != current['revision']:
        raise ValueError('The car list or saved classes changed. Reopen Manage classes and choose the cars again.')
    selected = next((c for c in current['classes'] if c['id'] == body.get('id')), None)
    if not selected:
        raise ValueError('Choose a saved custom class.')
    desired = body.get('members')
    if (not isinstance(desired, list) or len(desired) > 500 or
            any(not isinstance(ident, str) for ident in desired) or len(set(desired)) != len(desired)):
        raise ValueError('Choose up to 500 different cars for the class.')
    rows = {c['id']: c for c in current['cars']}
    if not set(desired) <= rows.keys():
        raise ValueError('A selected car is unavailable. Scan the game again.')
    added = set(desired) - set(selected['members'])
    removed = set(selected['members']) - set(desired)
    if not added and not removed:
        raise ValueError('No class changes to review.')
    if len(added | removed) > 500:
        raise ValueError('Change up to 500 cars at a time.')
    active, edits, tags = _members(editor), [], {}
    for ident in sorted(added | removed):
        if rows[ident]['reason']:
            raise ValueError(rows[ident]['name'] + ': ' + rows[ident]['reason'])
        car = editor.cars[ident]
        original = active[ident]['original'] if ident in active else _assignment(car)
        target = dict(zip(FIELDS, (selected['name'], selected['group'], selected['grid']))) if ident in added else original
        edits.append({'car': ident, 'fingerprint': car.fingerprint, 'parameters': {},
                      'target_class': target[FIELDS[0]], 'group': target[FIELDS[1]], 'grid': target[FIELDS[2]]})
        tags[ident] = {'version': 1, 'id': selected['id'], 'member': ident in added,
                       'original': original, 'assigned': target}
    plan = editor.preview(edits)
    # Membership metadata is server-generated, never imported from physics profiles.
    for change in plan['changes']:
        change['class_set'] = tags[change['id']]
    editor.prepared[plan['token']]['class_set_catalog_hash'] = sha(catalog_path(editor))
    plan['notes'] = ['Only class assignments change. Removing a car restores its remembered class, group and grid.',
                     'Current physics, tuning and liveries are retained. Full-file backups support Undo last apply.']
    return plan
