"""Explicit recording slots for a championship weekend; P1 never earns points."""
from __future__ import annotations

import json
from pathlib import Path

from .season import connect, ingest

SCHEMA = """
CREATE TABLE IF NOT EXISTS weekend(round INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
    track TEXT, layout TEXT, practice1 TEXT, practice2 TEXT, qualify TEXT, race TEXT);
CREATE TABLE IF NOT EXISTS development(id TEXT PRIMARY KEY, round INTEGER NOT NULL,
    driver TEXT NOT NULL, car TEXT NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL);
"""
ROLES = {'practice1': 'practice', 'practice2': 'practice', 'qualify': 'qualify', 'race': 'race'}


def connection(db):
    con = connect(db)
    con.executescript(SCHEMA)
    return con


def weekends(lib, cid):
    con = connection(lib._db(cid))
    try:
        rows = {r['round']: dict(r) for r in con.execute('SELECT * FROM weekend ORDER BY round')}
        # Existing races remain visible without rewriting their results or notes.
        for r in con.execute("SELECT e.round,e.track,e.layout,s.path FROM session s JOIN event e ON e.id=s.event_id WHERE s.type='race' AND s.race_no=1 ORDER BY e.round"):
            rows.setdefault(r['round'], dict(round=r['round'], name='', track=r['track'], layout=r['layout'],
                                            practice1=None, practice2=None, qualify=None, race=Path(r['path']).name))
        for w in rows.values():
            w['sessions'] = {}
            for role in ROLES:
                name = w.get(role)
                if name:
                    try:
                        w['sessions'][role] = lib.recording_summary(lib.recording_path(name))
                    except LookupError:
                        w['sessions'][role] = {'id': name, 'missing': True}
            w['development'] = [dict(id=r['id'], state=r['state'], car=r['car'], driver=r['driver'])
                                for r in con.execute('SELECT id,state,car,driver FROM development WHERE round=?', (w['round'],))]
        return list(rows.values())
    finally:
        con.close()


def assign(lib, cid, body):
    rnd = body.get('round')
    if isinstance(rnd, bool) or not isinstance(rnd, int) or not 1 <= rnd <= 999:
        raise ValueError('Choose a weekend number between 1 and 999.')
    supplied = {k: body[k] or None for k in ROLES if k in body}
    con = connection(lib._db(cid))
    try:
        prior = next((x for x in weekends(lib, cid) if x['round'] == rnd), {})
        row = {k: prior.get(k) for k in ROLES} | supplied
        if row['practice1'] and row['practice1'] == row['practice2']:
            raise ValueError('Practice 1 and Practice 2 need separate recordings.')
        meta = {}
        for role, name in row.items():
            if name is None:
                continue
            if not isinstance(name, str):
                raise ValueError('Choose a recording from the list.')
            path = lib.recording_path(name)
            m = lib.recording_summary(path)
            if m['type'] != ROLES[role]:
                raise ValueError(role.replace('practice', 'Practice ') + ' needs a ' + ROLES[role] + ' recording.')
            meta[role] = m
        tracks = {(m['track_raw'], m['layout_raw']) for m in meta.values()}
        if len(tracks) > 1:
            raise ValueError('Every recording in a weekend must use the same track and layout.')
        plans = [json.loads(r['data']) for r in con.execute('SELECT data FROM development WHERE round=?', (rnd,))]
        if plans and row['practice1'] != prior.get('practice1'):
            raise ValueError('Practice 1 is locked as the reference for this weekend’s development plan.')
        if any(p.get('evaluation') for p in plans) and row['practice2'] != prior.get('practice2'):
            raise ValueError('This Practice 2 has already been assessed; keep its development history.')
        # Pair the qualifying recording automatically when a race is selected.
        if row['race'] and 'qualify' not in supplied and not row['qualify']:
            race = next((r for r in lib.recordings() if r['id'] == row['race']), {})
            row['qualify'] = race.get('quali')
        if row['race'] != prior.get('race'):
            if prior.get('race'):
                raise ValueError('Remove the existing race result before replacing this weekend’s race.')
            if row['race']:
                ingest(lib._db(cid), lib.champ_config(cid), lib.recording_path(row['race']), round_no=rnd)
        track, layout = next(iter(tracks), (prior.get('track'), prior.get('layout')))
        name = str(body.get('name', prior.get('name', ''))).strip()[:100]
        with con:
            con.execute('INSERT INTO weekend VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(round) DO UPDATE SET name=excluded.name,track=excluded.track,layout=excluded.layout,practice1=excluded.practice1,practice2=excluded.practice2,qualify=excluded.qualify,race=excluded.race',
                        (rnd, name, track, layout, row['practice1'], row['practice2'], row['qualify'], row['race']))
            if row['practice1']:
                p1 = lib.recording_path(row['practice1'])
                for practice in con.execute('SELECT id,path FROM practice').fetchall():
                    if Path(practice['path']).resolve() == p1.resolve():
                        con.execute('DELETE FROM practice_award WHERE practice_id=?', (practice['id'],))
        lib._report_cache.clear()
        return next(w for w in weekends(lib, cid) if w['round'] == rnd)
    finally:
        con.close()
