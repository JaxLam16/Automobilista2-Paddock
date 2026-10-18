"""The live coach's practice programme: typed and voice replies, R&D lookup, setup engineer."""
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

from ams2season import shm as S
from ams2season.development import waiting_plans
from test_coach_program import candidate
from test_coach_service import app_with_current, wait_until


def practice(pit=2, speed=0.0):
    snap = S.SharedMemory()
    snap.mVersion = S.SHARED_MEMORY_VERSION
    snap.mGameState, snap.mSessionState, snap.mRaceState = 2, 1, 2
    snap.mNumParticipants, snap.mViewedParticipantIndex = 1, 0
    snap.mTrackLength = 2000
    snap.mCarName, snap.mCarClassName = b"GT3", b"GT3"
    snap.mTrackLocation, snap.mTrackVariation = b"Track", b"Layout"
    snap.mSpeed, snap.mThrottle, snap.mSteering = speed, 0, 0
    snap.mPitMode = pit
    player = snap.mParticipantInfo[0]
    player.mIsActive, player.mName = True, b"Player"
    player.mLapsCompleted, player.mRacePosition, player.mCurrentLapDistance = 0, 1, 1900
    snap.mCarNames[0].value, snap.mCarClassNames[0].value = b"GT3", b"GT3"
    snap.mRaceStates[0], snap.mSpeeds[0], snap.mPitModes[0] = 2, speed, pit
    snap.mLapsInvalidated[0] = False
    return snap


def drive(app, seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.recorder.rec.step(practice(), time.perf_counter())
        time.sleep(.03)


def events(app, state=None, code=None):
    return [e for e in app.coach.status()['events'] if (state is None or e['state'] == state)
            and (code is None or e.get('code') == code)]


@pytest.fixture
def coach_app(tmp_path, monkeypatch):
    app = app_with_current(tmp_path)
    app.recorder.rec.step(practice(), time.perf_counter())
    monkeypatch.setattr(type(app.coach), '_plan_lookup', lambda self, *args: [candidate()])
    yield app
    app.coach.close()


def test_typed_free_text_sets_the_goal_and_the_engineer_answers(coach_app):
    app = coach_app
    app.route('POST', '/api/coach/start', {}, {})
    drive(app, .3)
    wait_until(lambda: events(app, 'queued', 'B-01'))
    with pytest.raises(ValueError):
        app.route('POST', '/api/coach/say', {}, {'text': ''})
    result = app.route('POST', '/api/coach/say', {}, {'text': 'No, this is practice session 2'})
    assert result['reply']['understood'] == 'Practice 2: R&D objectives' and 'radio' in result['reply']['response']
    program = result['live']['program']
    assert program['goal'] == 'practice2' and program['source'] == 'typed'
    drive(app, .3)
    assert [e for e in events(app, 'driver_reply') if e['source'] == 'typed']
    assert events(app, 'queued', 'B-08')


def test_voice_reply_from_crew_chief_is_picked_up(coach_app):
    app = coach_app
    replies = ['confirm']
    app._crew_chief = SimpleNamespace(settings={'replies_receipt': {'reply_file': 'x'}},
                                      poll_replies=lambda: [replies.pop()] if replies else [],
                                      audio_transport_status=lambda: {'configured': False, 'connected': False})
    app.route('POST', '/api/coach/start', {}, {})
    drive(app, .3)
    wait_until(lambda: (app.coach.status()['live']['program'] or {}).get('goal') == 'practice2')
    program = app.coach.status()['live']['program']
    assert program['source'] == 'voice' and program['replies_enabled']
    assert program['replies'][0]['understood'] == 'Confirm'


def test_screen_choice_and_the_setup_engineer_follows_practice(coach_app, monkeypatch):
    app = coach_app
    started, stopped = [], []
    monkeypatch.setattr(type(app), 'start_live_engineer', lambda self, key=None, started_by=None: started.append(started_by) or 'k')
    monkeypatch.setattr(type(app), 'stop_live_engineer', lambda self, started_by=None: stopped.append(started_by) or True)
    app.route('POST', '/api/coach/start', {}, {})
    drive(app, .2)
    with pytest.raises(ValueError):
        app.route('POST', '/api/coach/goal', {}, {'goal': 'qualifying'})
    app.route('POST', '/api/coach/goal', {}, {'goal': 'practice1'})
    drive(app, .3)
    assert started == ['practice-coach']
    app.recorder.engineer_key = 'k'
    session = {'runs': [{'id': 2, 'measure': {'best_lap': 40.0, 'n_flying': 3},
                         'recommendations': [{'setting': 'brake_bias', 'ticks': 1, 'priority': 1}]}]}
    app.coach.engineer_run_done('k', session)
    drive(app, .3)
    assert [e for e in events(app, 'queued', 'S-03')]
    app.route('POST', '/api/coach/goal', {}, {'goal': 'practice2'})
    drive(app, .3)
    assert stopped == []   # live engineering stays on with the coach in practice; stopped on the engineer page


def test_replies_outside_practice_are_explained_not_applied(tmp_path):
    app = app_with_current(tmp_path)   # a race snapshot
    with pytest.raises(ValueError, match='practice session'):
        app.route('POST', '/api/coach/say', {}, {'text': 'confirm'})
    app.coach.close()


def champ(path, rows):
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE development(id TEXT PRIMARY KEY, round INTEGER NOT NULL, driver TEXT NOT NULL, '
                'car TEXT NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL)')
    for i, (state, plan) in enumerate(rows):
        con.execute('INSERT INTO development VALUES(?,?,?,?,?,?)', (str(i), plan['round'], 'Player', 'GT3', state, json.dumps(plan)))
    con.commit()
    con.close()


def plan(**changes):
    c = candidate()
    value = {'id': 'p', 'round': 2, 'created_at': '2026-10-14', 'projects': c['projects'], 'baseline': c['baseline'],
             'evaluation': None, 'practice2': None}
    value.update(changes)
    return value


def test_waiting_plans_are_read_only_and_exact(tmp_path):
    db = tmp_path / 'season.db'
    champ(db, [('planned', plan()), ('planned', plan(id='q', practice2='rec')), ('assessed', plan(id='r')),
               ('planned', plan(id='s', baseline={**candidate()['baseline'], 'track': 'Other'}))])
    before = db.read_bytes()
    lib = SimpleNamespace(_champ_files=lambda: [db, tmp_path / 'missing.db'])
    found = waiting_plans(lib, driver='Player', car='GT3', track='Track', layout='Layout', length=2000)
    assert [p['plan'] for p in found] == ['p'] and found[0]['champ'] == 'season'
    assert found[0]['projects'][0]['objectives'][1]['kind'] == 'corner'
    assert waiting_plans(lib, driver='Someone', car='GT3', track='Track', layout='Layout') == []
    assert waiting_plans(lib, driver='Player', car='GT3', track='Track', layout='Layout', length=2500) == []
    assert db.read_bytes() == before
