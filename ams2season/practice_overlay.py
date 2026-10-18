"""Passive garage checklist. Recorder hook only copies scalar state; work stays off its thread.

No game inputs, setup writes, or guessed P1/P2 numbering. R&D follows the coach's
explicit Practice 2 programme. A separate no-activate Windows window reads a small
expiring state file, and also checks that AMS2 owns the foreground window.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from . import shm as S
from .coach.model import finite
from .engineer.catalog import BY_KEY, CAT_LABEL, action_text, garage_hint
from .engineer.store import recommendation_token, setup_review

MENU = (('next', 'Next instruction'), ('applied', 'Applied'), ('skipped', 'Skip / decline'),
        ('maxed', 'Maxed out'), ('unavailable', 'Not available on this car'), ('hide', 'Hide checklist'))


def garage_sample(snap, sampled_at):
    i = int(snap.mViewedParticipantIndex)
    valid = (snap.mSessionState in (S.SESSION_PRACTICE, S.SESSION_TEST)
             and snap.mGameState in (S.GAME_INGAME_PLAYING, S.GAME_INGAME_PAUSED,
                                     S.GAME_INGAME_INMENU_TIME_TICKING)
             and 0 <= i < min(snap.mNumParticipants, S.STORED_PARTICIPANTS_MAX)
             and snap.mParticipantInfo[i].mIsActive)
    car, track, layout = (S.cstr(getattr(snap, k)).strip() for k in
                          ('mCarName', 'mTrackLocation', 'mTrackVariation'))
    speed = finite(snap.mSpeed)
    # InPit includes a pit stop: only InGarage is sufficient to open the overlay.
    return {'at': sampled_at, 'garage': bool(valid and car and track and snap.mTrackLength > 0
            and int(snap.mPitMode) == S.PIT_MODE_IN_GARAGE and speed is not None and 0 <= speed < .5),
            'car': car, 'track': track, 'layout': layout or track,
            'driver': S.cstr(snap.mParticipantInfo[i].mName).strip() if valid else ''}


def checklist(session, programme=None):
    """Current advice with a revision token for explicit, single-card setup decisions."""
    cards = []
    run = (session.get('runs') or [None])[-1] if session else None
    if run:
        recs = sorted(run.get('recommendations') or [],
                      key=lambda r: (r.get('priority', 2), r.get('test', False), -abs(r.get('ticks') or 0)))
        for r in recs:
            key, ticks = r.get('setting'), r.get('ticks')
            if key not in BY_KEY or not ticks or r.get('info') or (run.get('decisions') or {}).get(r.get('id')):
                continue
            spec = BY_KEY[key]
            cards.append({'id': f"setup:{run['id']}:{r['id']}:{ticks}", 'kind': 'setup',
                'engineer_key': session.get('key'), 'run_id': run['id'], 'rec_id': r['id'],
                'token': recommendation_token(session, run, r),
                'heading': spec['label'], 'location': spec['tab'], 'action': action_text(key, ticks),
                'detail': garage_hint(key, ticks), 'why': str(r.get('why') or ''),
                'tag': ('Test • ' if r.get('test') else '') + CAT_LABEL.get(r.get('category'), '')
                       + ' • ' + str(r.get('confidence') or 'unknown') + ' confidence'})
        review = setup_review(session)
        if review and (review['items'] or review['pending_changes']):
            counts = review['counts']
            plan = review['next_run']
            cards.append({'id': f"review:{run['id']}", 'kind': 'review',
                'engineer_key': session.get('key'), 'run_id': run['id'], 'token': review['token'],
                'can_submit': review['can_submit'], 'submitted': review['submitted'],
                'heading': 'Submitted to engineer' if review['submitted'] else 'Review setup changes',
                'location': f"Setup • after run {run['id']}",
                'action': 'Changes logged for the next run.' if review['submitted'] else
                          f"Review {review['remaining']} remaining instruction(s)." if review['remaining'] else 'Submit to engineer',
                'detail': f"{counts['applied']} applied • {counts['skipped']} skipped • "
                          f"{counts['maxed']} maxed out • {counts['unavailable']} unavailable.",
                'why': ('Next run: ' + str(plan.get('objective'))) if plan.get('objective') else
                       'Each confirmation is already saved. Submitting records the final review for the next run.',
                'tag': 'Submitted' if review['submitted'] else 'Final review'})
    # Never use 'detected': an unconfirmed plan waiting in a championship isn't P2.
    if (programme and programme.get('active') and programme.get('goal') == 'practice2'
            and programme.get('source') in ('screen', 'typed', 'voice', 'button')):
        for g in programme.get('objectives') or []:
            actual = g.get('actual')
            progress = ('Target met' if g.get('met') else 'Still to do')
            progress += f" • {int(g.get('laps') or 0)} eligible lap(s)"
            if actual is not None:
                progress += f" • measured {actual}"
            cards.append({'id': 'rd:' + str(g['id']), 'kind': 'rd', 'heading': str(g.get('project') or 'R&D goal'),
                'location': 'Practice 2 • next run', 'action': str(g.get('text') or ''),
                'detail': progress, 'why': 'R&D credit is assessed when this recording is filed in the championship.',
                'tag': 'R&D • Practice 2'})
    return cards


class PracticeOverlay:
    def __init__(self, app, *, native_factory=None):
        self.app, self.root = app, app.lib.root
        self.lock = threading.RLock()
        self.enabled, self.position = False, 'right'
        self.sample = None
        self.display_at = None
        self.cards, self.index, self.signature = [], 0, None
        self.menu_index, self.pending, self.decision = 0, False, None
        self.note, self.after_decision = None, None
        self.dismissed, self.was_garage, self.visit = False, False, 0
        self.identity = None
        self.error = None
        self.reason = 'disabled'
        self.visible = False
        self.halt = threading.Event()
        self.thread, self.native = None, None
        self.enable_requested = False
        self.native_factory = native_factory or NativeOverlay
        self._load()

    def _load(self):
        try:
            data = json.loads((self.root / 'private_coach/overlay/settings.json').read_text(encoding='utf-8'))
            self.enabled = data.get('enabled') is True
            self.position = data.get('position') if data.get('position') in ('left', 'right') else 'right'
        except (OSError, ValueError, TypeError):
            pass

    def configure(self, body):
        enabled, position = body.get('enabled', self.enabled), body.get('position', self.position)
        if not isinstance(enabled, bool) or position not in ('left', 'right'):
            raise ValueError('Choose overlay on/off and a left or right position.')
        with self.lock:
            directory = self.root / 'private_coach/overlay'
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / 'settings.json'
            path.with_suffix('.tmp').write_text(json.dumps({'enabled': enabled, 'position': position}), encoding='utf-8')
            path.with_suffix('.tmp').replace(path)
            self.enabled, self.position = enabled, position
            if not enabled:
                self.visible, self.reason = False, 'disabled'
            if enabled:
                self.error = None
                self.dismissed = False
                self.start()
        return self.status()

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.halt.clear()
            self.thread = threading.Thread(target=self._run, name='practice-overlay', daemon=True)
            self.thread.start()

    def feed(self, snap, now):
        # Called on recorder thread: no disk, model, process, UI or coach lock.
        self.sample = garage_sample(snap, now)

    def command(self, action):
        action = {'left':'previous', 'right':'next'}.get(action, action)
        if action not in ('next', 'previous', 'toggle', 'up', 'down', 'confirm'):
            raise ValueError('Choose left, right, up, down or confirm.')
        with self.lock:
            sample = self.sample
            in_garage = bool(sample and sample['garage'] and self.app.recorder.running
                             and 0 <= time.perf_counter() - sample['at'] <= .75)
            if action == 'confirm' and not self.enabled and in_garage:
                # A deliberate wheel press may re-enable the checklist. Persist
                # on the worker, never on the button/recorder thread. This press
                # only opens it; it cannot also apply the selected setup change.
                self.enable_requested = True
                self.dismissed = False
                self.note = 'Opening checklist…'
                self.start()
                return self.status()
            if self.display_at is not None and time.perf_counter() - self.display_at > .75:
                self.visible, self.reason, self.was_garage = False, 'stale', False
            if not self.was_garage or self.reason in ('stale', 'not_in_garage', 'disabled'):
                return self.status()
            if self.pending:
                return self.status()
            if action == 'confirm' and self.dismissed:
                self.dismissed, self.menu_index = False, 0
                self.visible = bool(self.enabled and self.cards)
                self.reason = 'ready' if self.cards else 'no_advice'
                self.note = 'Checklist reopened.'
                return self.status()
            if action == 'toggle':
                self.dismissed = not self.dismissed
            elif self.cards and not self.dismissed:
                if action in ('up', 'down'):
                    self.menu_index = (self.menu_index + (1 if action == 'down' else -1)) % len(self._menu())
                    return self.status()
                if action == 'confirm':
                    choice = self._menu()[self.menu_index][0]
                    if choice == 'hide':
                        self.dismissed = True
                        self.visible = False
                        self.reason = 'dismissed'
                        return self.status()
                    if choice != 'next':
                        self.decision = {'card': dict(self.cards[self.index]), 'choice': choice,
                                         'identity': self.identity, 'index': self.index}
                        self.pending, self.note = True, ('Submitting setup review…' if choice == 'submit' else 'Saving setup decision…')
                        return self.status()
                    action = 'next'
                self.index = (self.index + (1 if action == 'next' else -1)) % len(self.cards)
                self.menu_index = 0
            self.visible = bool(self.enabled and self.was_garage and not self.dismissed and self.cards)
            self.reason = 'dismissed' if self.dismissed else ('ready' if self.cards else 'no_advice')
            return self.status()

    def _menu(self):
        card = self.cards[self.index] if self.cards else None
        if card and card['kind'] == 'setup':
            return MENU
        if card and card['kind'] == 'review' and card.get('can_submit') and not card.get('submitted'):
            return (('submit', 'Submit to engineer'), MENU[0], MENU[-1])
        return (MENU[0], MENU[-1])

    def _save_decision(self, store):
        # Runs only on the overlay worker, outside the coach/recorder locks.
        with self.lock:
            request, self.decision = self.decision, None
        if request is None:
            return
        card = request['card']
        def valid():
            sample = self.sample
            return bool(self.enabled and not self.halt.is_set() and self.app.recorder.running and sample
                and 0 <= time.perf_counter() - sample['at'] <= .75 and sample['garage']
                and tuple(sample.get(k) for k in ('car','track','layout','driver')) == request['identity']
                and getattr(self.app.recorder, 'engineer_key', None) == card['engineer_key'])
        try:
            if request['choice'] == 'submit':
                store.submit_changes(card['engineer_key'], card['run_id'], card['token'], guard=valid)
                note = 'Submitted to engineer. Your confirmed setup changes are logged for this run.'
            else:
                result = store.decide_recommendation(card['engineer_key'], card['run_id'], card['rec_id'],
                    card['token'], request['choice'], guard=valid)
                note = f"Saved: {card['heading']} — {dict(MENU)[result['decision']]}."
            with self.lock:
                self.note = note
                self.after_decision = request['index']
        except (OSError, ValueError, LookupError, TypeError) as exc:
            with self.lock:
                self.note = str(exc)
        finally:
            with self.lock:
                self.pending, self.menu_index = False, 0

    def update(self, sample, session=None, programme=None, *, now=None, recorder_running=True):
        now = time.perf_counter() if now is None else now
        fresh = bool(sample and 0 <= now - sample['at'] <= .75 and recorder_running)
        garage = bool(fresh and sample['garage'])
        with self.lock:
            self.display_at = sample['at'] if sample else None
            identity = tuple(sample.get(k) for k in ('car', 'track', 'layout', 'driver')) if fresh else None
            if garage and (not self.was_garage or identity != self.identity):
                self.visit += 1
                self.dismissed, self.index = False, 0
                self.menu_index = 0
                self.after_decision = None
            self.was_garage, self.identity = garage, identity
            matching = bool(garage and session and all(session.get(k) == sample[k] for k in ('car', 'track', 'layout')))
            cards = checklist(session if matching else None, programme if garage else None)
            signature = tuple((c['id'],c.get('token')) for c in cards)
            if signature != self.signature:
                self.signature = signature
                self.index = min(self.after_decision or 0, max(0, len(cards)-1))
                self.after_decision, self.menu_index = None, 0
            self.cards = cards
            self.visible = bool(self.enabled and garage and cards and not self.dismissed)
            self.reason = ('disabled' if not self.enabled else 'stale' if not fresh else 'not_in_garage' if not garage
                           else 'dismissed' if self.dismissed else 'no_advice' if not cards else 'ready')
            return self.status()

    def status(self):
        with self.lock:
            return {'enabled': self.enabled, 'position': self.position, 'visible': self.visible,
                    'reason': self.reason, 'error': self.error, 'index': self.index, 'total': len(self.cards),
                    'card': dict(self.cards[self.index]) if self.cards else None, 'visit': self.visit,
                    'menu': [{'action': key, 'label': label} for key, label in self._menu()],
                    'menu_index': self.menu_index, 'pending': self.pending, 'note': self.note,
                    'native_running': bool(self.native and self.native.running),
                    'display_delayed': bool(getattr(self.native, 'publication_delayed', False)),
                    'requires_borderless': True}

    def _run(self):
        from .engineer.store import EngineerStore
        store = EngineerStore(self.root)
        try:
            while not self.halt.wait(.2):
                with self.lock:
                    enable, self.enable_requested = self.enable_requested, False
                if enable:
                    self.configure({'enabled': True})
                sample, session, programme = self.sample, None, None
                coach = self.app._coach
                if coach is not None:
                    with coach.lock:
                        if not coach.running:
                            if coach.button_bindings:
                                coach._ensure_buttons()
                            coach._service_buttons()
                        if coach.running and coach.engine and coach.engine.program:
                            p = coach.engine.program
                            # A programme must still belong to this exact local driver/session.
                            ctx = coach.engine.context
                            previous = getattr(coach.engine, 'previous', None)
                            if (sample and ctx and ctx.session == 'practice' and ctx.session_id == p.session_id
                                    and coach.engine.driver == sample['driver'] and ctx.pit_radio
                                    and previous and previous.track == sample['track']
                                    and (previous.layout or previous.track) == sample['layout']
                                    and previous.player(coach.engine.driver)
                                    and previous.player(coach.engine.driver).car == sample['car']
                                    and time.perf_counter() - coach.origin - ctx.t < .75):
                                programme = p.status()
                key = getattr(self.app.recorder, 'engineer_key', None)
                self._save_decision(store)
                if self.enabled and key and sample and sample['garage']:
                    try:
                        session = store.get(key)
                    except (OSError, ValueError, LookupError):
                        pass   # a concurrent run write is retried; never show stale advice
                state = self.update(sample, session, programme, recorder_running=self.app.recorder.running)
                if state['enabled'] and self.native is None and self.error is None:
                    try:
                        self.native = self.native_factory(self.root)
                    except (OSError, ValueError) as exc:
                        self.error = str(exc)
                if self.native:
                    try:
                        bindings = coach.button_bindings if coach else {}
                        state['controls'] = ' • '.join(label + ': ' +
                            (('B'+str(bindings['overlay_'+role]['button']) if bindings['overlay_'+role]['button']<=32 else
                              {33:'Hat↑',34:'Hat→',35:'Hat↓',36:'Hat←'}[bindings['overlay_'+role]['button']])
                             if 'overlay_'+role in bindings else 'not bound')
                            for role, label in (('previous','Left'),('next','Right'),('up','Up'),('down','Down'),('confirm','Confirm')))
                        self.native.publish(state)
                    except (OSError, ValueError) as exc:
                        self.error = str(exc)
                        self.native.close()
                        self.native = None
                if not self.enabled and self.native:
                    self.native.close()
                    self.native = None
        except Exception as exc:
            with self.lock:
                self.visible = False
                self.error = 'Garage overlay stopped: ' + str(exc)[:200]
        finally:
            if self.native:
                self.native.close()
                self.native = None

    def close(self):
        self.halt.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)


class NativeOverlay:
    def __init__(self, root, *, kind='garage'):
        if sys.platform != 'win32':
            raise OSError('The garage overlay needs Windows.')
        if kind not in ('garage','skills'):raise ValueError('Invalid overlay kind.')
        executable = Path(__file__).parent / ('assets/skill_overlay.exe' if kind=='skills' else 'assets/practice_overlay.exe')
        if not executable.is_file():
            raise OSError('Garage overlay helper is missing. Rebuild or update Paddock.')
        directory = Path(root) / ('private_coach/skills' if kind=='skills' else 'private_coach/overlay')
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f'live-{os.getpid()}.json'
        self.path.write_text('{}', encoding='utf-8')
        self.process = subprocess.Popen([str(executable), str(self.path), str(os.getpid())],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.publication_delayed = False

    @property
    def running(self):
        return self.process.poll() is None

    def publish(self, state):
        if not self.running:
            raise OSError('Garage overlay helper stopped. Switch the overlay off and on to retry.')
        data = {**state, 'expires_utc': time.time() + 1.5}
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data), encoding='utf-8')
        try:
            tmp.replace(self.path)
        except PermissionError:
            # Windows readers/AV can briefly deny file replacement. Keep this
            # helper alive and retry the latest state on the next worker tick.
            # Its existing expiry still hides stale advice if contention lasts.
            self.publication_delayed = True
            return
        self.publication_delayed = False

    def close(self):
        if self.running:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        # Only this process's ephemeral display state; settings/advice remain.
        self.path.unlink(missing_ok=True)
