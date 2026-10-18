"""Practice programme: the session goal, run briefs, R&D objective progress and pit debriefs.

B-01  In the pits at the start of practice the engineer says what he thinks the session is
      for and asks for confirmation. Practice 2 is detected only from an R&D plan that is
      locked and still waiting for its Practice 2 for this driver, car, track and layout;
      otherwise it is Practice 1 (setup and learning the track). The driver can answer by
      voice through Crew Chief (see crew_chief.REPLY_MACROS) or by typing in Paddock. With no
      answer, the detected goal is used.
B-08  Before each run, in the pits: the R&D objectives (Practice 2) or the setup engineer's
      plan for the next run and the changes to try (Practice 1).
C-43  Practice 2, on track: after each flying lap's objective corners, or at the end of the
      lap for pace, fuel and clean-lap objectives, whether the target was met and by how
      much. Corner speeds use the R&D assessment's own method (median speed over the 10 m
      grid points within 20 m of each apex, against the Practice 1 reference), so the live
      numbers match what the assessment will see. Only flying laps the game still counts.
S-03  Practice 1, back in the pits: the setup engineer's suggestions from that run.
D-01  Practice 2, back in the pits: where each objective stands.

Nothing here assesses, credits or applies R&D: that still happens when Practice 2 is filed
in the weekend. Unknown inputs withhold the call.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import deque
from decimal import Decimal
import math
import re
from statistics import median

from .catalogue import CATALOGUE
from .model import Evidence, Message, Requirement, finite
from .numbers import decimal_words, integer_words, rounded

GOAL_LABEL = {'practice1': 'Practice 1: setup and learning the track',
              'practice2': 'Practice 2: R&D objectives', 'free': 'Free practice: no plan'}
GOAL_SPEECH = {'practice1': 'practice one', 'practice2': 'practice two', 'free': 'free practice'}
SETUP_TRENDS = {
    'pressures': 'The tyre pressures need attention',
    'camber': 'The tyre temperatures suggest a camber adjustment',
    'ground_clearance': 'The platform data suggests ground clearance changes',
    'chassis_balance': 'There are balance changes to try',
    'aero_balance': 'There are aero balance changes to try',
    'downforce': 'There are downforce changes to try',
    'braking_traction': 'There are braking or traction changes to try',
    'thermals': 'The cooling needs attention', 'gearing': 'The gearing needs attention',
    'pit_strategy': 'There are fuel changes to look at'}
SETUP_REVIEW_PARTS = ("I've got some setup changes for you.", 'Take a look at the garage checklist.')
SETUP_REVIEW_LINE = ' '.join(SETUP_REVIEW_PARTS)
REPLY_S = 20          # a question stays answerable this long after it is spoken
CORNER_WINDOW_M = 20  # the R&D assessment's half-width around each apex
GRID_M = 10           # the R&D assessment's speed grid
VERBS = {'more': ('up', 'down'), 'stiff': ('stiffer', 'softer'), 'height': ('up', 'down'),
         'camber': ('more negative', 'less negative'), 'aero': ('up', 'down'), 'bias': ('forward', 'rearward'),
         'open': ('more open', 'more closed'), 'gear': ('shorter', 'longer'), 'lock': ('more locking', 'less locking'),
         'toe': ('more toe-in', 'less toe-in')}
CORNERS = {'fl': 'front left', 'fr': 'front right', 'rl': 'rear left', 'rr': 'rear right'}


# ------------------------------------------------------------------------- spoken pieces
def number_words(value, places=1):
    return decimal_words(rounded(Decimal(str(value)), places))


def ordinal(n):
    return {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six'}.get(n, integer_words(n))


def turn_words(names):
    spoken = []
    for name in names:
        m = re.fullmatch(r'T(\d{1,3})', str(name), re.IGNORECASE)
        spoken.append(integer_words(int(m[1])) if m else str(name))
    if len(spoken) == 1:
        return 'turn ' + spoken[0]
    return 'turns ' + ', '.join(spoken[:-1]) + ' and ' + spoken[-1]


def lap_words(numbers, seconds):
    return numbers.lap_time(seconds).speech


def change_words(changes, settings):
    """'front tyre pressures down two clicks', grouping matching wheels."""
    items = []
    for c in changes:
        key, ticks = c.get('setting'), int(c.get('ticks') or 0)
        spec = settings.get(key)
        if not spec or not ticks:
            continue
        items.append((key, ticks, spec))
    used, out = set(), []
    for key, ticks, spec in items:
        if key in used:
            continue
        base, _, wheel = key.rpartition('_')
        label = spec['label'].lower()
        if wheel in CORNERS and base:
            same = [(k, t) for k, t, _ in items if k.rpartition('_')[0] == base and t == ticks and k not in used]
            wheels = {k.rpartition('_')[2] for k, _ in same}
            noun = label.replace(CORNERS[wheel] + ' ', '')
            plural = noun + 's' if noun.endswith(('pressure', 'rate', 'height', 'stop')) else noun
            if wheels == set(CORNERS):
                label, group = 'all four ' + plural, [k for k, _ in same]
            elif wheels >= {'fl', 'fr'} and not wheels & {'rl', 'rr'}:
                label, group = 'front ' + plural, [base + '_fl', base + '_fr']
            elif wheels >= {'rl', 'rr'} and not wheels & {'fl', 'fr'}:
                label, group = 'rear ' + plural, [base + '_rl', base + '_rr']
            else:
                group = [key]
        else:
            group = [key]
        used.update(group)
        up, down = VERBS.get(spec.get('verbs'), ('up', 'down'))
        n = abs(ticks)
        out.append(f"{label} {up if ticks > 0 else down} {integer_words(n)} click{'s' if n != 1 else ''}")
    return out


def join(items):
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' and ' + items[-1]


def sentence(text):
    text = text.strip()
    return text[0].upper() + text[1:] + ('' if text.endswith(('.', '?', '!')) else '.')


# ------------------------------------------------------------------- objective tracking
class ObjectiveTracker:
    """Measures Practice 2 laps live against a locked R&D plan's Practice 1 reference."""

    def __init__(self, candidate):
        base = candidate['baseline']
        self.length = float(base['length'])
        self.reference = float(base.get('average') or base['median'])
        self.apex = {c['name']: float(c['apex']) for c in base.get('corners') or []}
        self.reference_kph = {k: float(v) for k, v in (base.get('corner_speeds') or {}).items()}
        self.goals = []
        for project in candidate['projects']:
            for goal in project['objectives']:
                kind = goal.get('kind')
                if kind == 'clean_lap' and any(g['kind'] == 'clean_lap' for g in self.goals):
                    continue  # one clean lap serves every project
                g = {'id': f"{project['category']}:{goal.get('id')}", 'kind': kind, 'target': float(goal['target']),
                     'project': project.get('name') or project['category'], 'text': goal.get('text', '')}
                if kind == 'corner':
                    g['corners'] = [n for n in goal.get('corners', []) if n in self.apex and n in self.reference_kph]
                    if not g['corners']:
                        continue  # without a reference corner there is nothing honest to measure
                    speeds = [self.reference_kph[n] for n in g['corners']]
                    g['group'] = ('fast corners' if min(speeds) >= 160 else 'slow corners' if max(speeds) < 160 else 'corners')
                if kind in ('clean_lap', 'endurance', 'corner', 'pace', 'fuel'):
                    self.goals.append(g)
        self.results = {g['id']: [] for g in self.goals}  # eligible completed-lap values
        self.awaiting_time = None
        self.prev_last = None
        self.best = None
        self.met_once = set()
        self._reset()

    # --- the corner speed the R&D assessment would compute for this lap -----------------
    def _corner_speed(self, centre):
        if len(self.samples) < 4:
            return None
        s = [p[0] for p in self.samples]
        lo, hi = centre - CORNER_WINDOW_M - 5, centre + CORNER_WINDOW_M + 5
        i, j = bisect_left(s, lo), bisect_left(s, hi)
        if i == 0 or j >= len(s) or s[i-1] > lo:
            return None
        window = s[i-1:j+1]
        if any(b - a > 15 for a, b in zip(window, window[1:])):
            return None  # a capture gap: no interpolation across it
        values = []
        n = math.ceil(self.length / GRID_M)
        apex = centre % self.length
        for k in range(n):
            d = ((k * GRID_M - apex + self.length / 2) % self.length) - self.length / 2
            if abs(d) <= CORNER_WINDOW_M:
                x = centre + d
                m = bisect_left(s, x)
                if m == 0 or m >= len(s):
                    return None
                (x0, v0), (x1, v1) = self.samples[m-1], self.samples[m]
                values.append(v0 + (v1 - v0) * (x - x0) / (x1 - x0) if x1 > x0 else v1)
        return median(values) if values else None

    def _new_lap(self, laps, flying, fuel, t):
        self.lap = {'n': laps, 'flying': flying, 'valid': True, 'pit': False, 'fuel_start': fuel,
                    'start_t': t, 'start_s': self.wraps * self.length, 'corners': {}, 'reported': set()}

    def _reset(self):
        self.lap, self.samples, self.prev_d, self.wraps = None, deque(maxlen=6000), None, 0

    def feed(self, tick, player, active):
        """Return events: ('corners', goal, result) after a flying lap's objective corners and
        ('lap', record) once the game reports that lap's time. Laps follow the geometric line
        crossing; the game's lap counter can lag it by a few samples."""
        events = []
        if player is None or player.distance is None or player.laps < 0 or not active:
            self._reset()
            self.prev_last = player.last_lap if player is not None else None
            return events
        L, d = self.length, player.distance
        speed = finite(tick.local.get('speed'))
        capacity, level = finite(tick.local.get('fuel_capacity')), finite(tick.local.get('fuel_level'))
        fuel = capacity * level if capacity and level is not None and capacity > 0 else None
        crossed = False
        if self.prev_d is None:
            self._new_lap(player.laps, False, fuel, tick.t)  # joined mid-lap: not a flying lap
        elif self.prev_d > .85 * L and d < .15 * L:
            crossed = True
        elif d < self.prev_d - 50 or d > self.prev_d + 250:
            # Reset, teleport or capture jump: the lap in progress is no longer a flying lap.
            self.samples = deque(maxlen=6000)
            self.lap['flying'] = False
        if crossed:
            record = dict(self.lap, fuel_end=fuel, end_t=tick.t, laps_completed=player.laps)
            self.awaiting_time = (record, tick.t, self.prev_last)
            self.wraps += 1
            self._new_lap(player.laps, player.pit == 0, fuel, tick.t)  # crossing the line on track
        self.prev_d = d
        s = self.wraps * L + d
        if speed is not None and (not self.samples or s > self.samples[-1][0]):
            self.samples.append((s, speed * 3.6))
        lap = self.lap
        lap['valid'] &= tick.local.get('local_lap_invalid') is False and not player.invalid
        if player.pit != 0:
            lap['pit'] = True
        for goal in self.goals:
            if goal['kind'] != 'corner' or goal['id'] in lap['reported']:
                continue
            for name in goal['corners']:
                centre = lap['start_s'] + self.apex[name]
                if name not in lap['corners'] and s >= centre + CORNER_WINDOW_M + 10:
                    lap['corners'][name] = self._corner_speed(centre)
            if all(n in lap['corners'] for n in goal['corners']):
                lap['reported'].add(goal['id'])
                values = [lap['corners'][n] for n in goal['corners']]
                if lap['flying'] and lap['valid'] and not lap['pit'] and all(v is not None for v in values):
                    deltas = {n: lap['corners'][n] - self.reference_kph[n] for n in goal['corners']}
                    events.append(('corners', goal, {'lap': self.wraps, 'deltas': deltas,
                                                     'mean': sum(deltas.values()) / len(deltas)}))
        if self.awaiting_time:
            record, crossed_t, previous = self.awaiting_time
            current = player.last_lap
            own = record['end_t'] - record['start_t']  # line-to-line timing, to one sample
            if current is not None and (current != previous or (tick.t - crossed_t > 1.5 and abs(current - own) < .15)):
                # The game's own lap time. An unchanged value is accepted only when it matches
                # this lap's crossing-to-crossing timing (two identical lap times).
                self.awaiting_time = None
                events.append(('lap', self._complete(record, current)))
            elif tick.t - crossed_t > 4:
                self.awaiting_time = None  # the game never reported this lap's time: not counted
        self.prev_last = player.last_lap
        return events

    def _complete(self, record, time):
        eligible = record['flying'] and record['valid'] and not record['pit'] and 10 < time < 3600
        if eligible:
            self.best = time if self.best is None else min(self.best, time)
        used = (record['fuel_start'] - record['fuel_end']
                if record['fuel_start'] is not None and record['fuel_end'] is not None else None)
        result = {'lap': record['laps_completed'], 'time': time, 'eligible': eligible, 'fuel_used': used if used and used > 0 else None,
                  'corner_means': {}}
        if eligible:
            for goal in self.goals:
                if goal['kind'] == 'corner':
                    values = [record['corners'].get(n) for n in goal['corners']]
                    if all(v is not None for v in values):
                        mean = sum(v - self.reference_kph[n] for v, n in zip(values, goal['corners'])) / len(values)
                        result['corner_means'][goal['id']] = mean
                        self.results[goal['id']].append({'lap': result['lap'], 'time': time, 'value': mean})
                elif goal['kind'] == 'pace':
                    self.results[goal['id']].append({'lap': result['lap'], 'time': time, 'value': time})
                elif goal['kind'] == 'fuel' and result['fuel_used'] is not None and abs(time - self.reference) <= 1:
                    self.results[goal['id']].append({'lap': result['lap'], 'time': time, 'value': result['fuel_used']})
                elif goal['kind'] == 'clean_lap':
                    self.results[goal['id']].append({'lap': result['lap'], 'time': time, 'value': 1})
                elif goal['kind'] == 'endurance' and abs(time - self.reference) <= 3:
                    self.results[goal['id']].append({'lap': result['lap'], 'time': time, 'value': 1})
        return result

    def summary(self, goal):
        """The assessment's aggregate over laps within 105% of the best clean lap so far."""
        rows = [r for r in self.results[goal['id']] if self.best is None or r['time'] <= self.best * 1.05]
        if goal['kind'] in ('clean_lap', 'endurance'):
            return {'laps': len(rows), 'actual': len(rows), 'met': len(rows) >= 1}
        if not rows:
            return {'laps': 0, 'actual': None, 'met': False}
        actual = sum(r['value'] for r in rows) / len(rows)
        met = actual >= goal['target'] - 1e-8 if goal['kind'] == 'corner' else actual <= goal['target'] + 1e-8
        return {'laps': len(rows), 'actual': actual, 'met': met}

    def status(self):
        out = []
        for goal in self.goals:
            row = {k: goal[k] for k in ('id', 'kind', 'project', 'text', 'target')}
            row.update(self.summary(goal))
            if goal['kind'] == 'corner':
                row['corners'] = goal['corners']
            out.append(row)
        return out


# ------------------------------------------------------------------------- the programme
class PracticeProgram:
    def __init__(self, numbers, *, plan_lookup=None, engineer_state=None, settings=None):
        self.numbers = numbers
        self.plan_lookup = plan_lookup          # (driver, car, track, layout, length) -> waiting R&D plans
        self.engineer_state = engineer_state    # () -> the live setup-engineer session summary, or None
        self.settings = settings or {}          # setup setting catalogue, for spoken changes
        self.replies_enabled = False
        self.personal_name = ''
        self.sequence = 0
        self.lookup_error = None
        self.reset(None)

    # --- lifecycle -----------------------------------------------------------------------
    def reset(self, session_id):
        self.session_id = session_id
        self.candidates, self.candidate = [], None
        self.detected = self.goal = self.source = None
        self.version = 0
        self.question = None              # {'id': message id, 'asked': spoken at, or None}
        self.replies = deque(maxlen=8)
        self.lines = deque(maxlen=14)
        self.run = 0                      # completed runs this session
        self.in_run = False
        self.run_started = None
        self.brief_due = True
        self.brief_wait = None            # 'leave_or_garage': wait for garage changes or the car rolling
        self.was_garage = False
        self.tracker = None
        self.last_engineer = None
        self.engineer_wanted = False
        self.facts = {}                   # latest objective result per objective, kept across ticks
        self.phase = 'pits:0'             # pit lines belong to one stop and are dropped once the car leaves
        self.brief_keys = []              # the latest brief's lines, to repeat it if the radio queue was cleared

    def begin(self, tick, player):
        self.reset(tick.session_id)
        if tick.session != 'practice' or player is None:
            return
        self.lookup_error = None
        if self.plan_lookup:
            try:
                self.candidates = list(self.plan_lookup(player.name, player.car, tick.track, tick.layout, tick.length))
            except Exception as exc:  # an unreadable championship must not stop the coach
                self.candidates, self.lookup_error = [], str(exc)[:300]
        self.candidate = self.candidates[-1] if self.candidates else None
        self.detected = 'practice2' if self.candidate else 'practice1'

    @property
    def active(self):
        return self.session_id is not None and self.detected is not None

    def goal_token(self):
        return f"{self.goal or 'undecided'}:{self.version}"

    def update_facts(self, ctx):
        ctx.facts.update(self.facts)
        ctx.facts['program:goal'] = self.goal_token()
        ctx.facts['program:phase'] = self.phase

    # --- messages ------------------------------------------------------------------------
    def _offer(self, radio, ctx, code, variants, *, key=None, requirements=(), evidence=None):
        if self.personal_name and key == 'program:question':
            variants = [self.personal_name + ', ' + v for v in variants]
        variants = [sentence(v) for v in variants] or ['']
        while len(variants) < 3:
            variants.append(variants[-1])
        self.sequence += 1
        spec = CATALOGUE[code]
        if spec.window == 'pits':
            requirements = (Requirement('program:phase', self.phase),) + tuple(requirements)
        message = Message(f'{code}:p{self.sequence}', spec, ctx.session_id, ctx.t + self.sequence * 1e-6,
                          ctx.t + spec.ttl_s, key or f'{code}:p{self.sequence}',
                          {'a': variants[0], 'b': variants[1], 'c': variants[2]},
                          Evidence('high', {'source': 'practice_programme', 'goal': self.goal,
                                            'detected': self.detected, **(evidence or {})}),
                          (Requirement('program:goal', self.goal_token()),) + tuple(requirements))
        self.lines.append({'t': ctx.t, 'code': code, 'text': variants[0]})
        if code == 'B-08':
            self.brief_keys.append(message.key)
        radio.offer(message, ctx)
        return message

    def _projects(self):
        names = [p.get('name') or p['category'] for p in (self.candidate or {}).get('projects', [])]
        return join([n.lower() for n in names]) if names else 'R&D'

    def _plural(self, n, word):
        return f"{integer_words(n)} {word}{'s' if n != 1 else ''}"

    def _ask(self, radio, ctx):
        if self.detected == 'practice2':
            what = 'practice two, for the ' + self._projects() + ' research'
        else:
            what = 'practice one: setup work and learning the track'
        if self.replies_enabled:
            variants = (f'Looks like {what}. Confirm?', f'I have this as {what}. Confirm?',
                        f'This should be {what}. Confirm?')
        else:
            variants = (f'Treating this as {what}. Change it on the coach page if not.',
                        f'I have this as {what}. You can change it on the coach page.',
                        f'This looks like {what}. Change it on the coach page if that is wrong.')
        if not self.replies_enabled:
            # Nothing to wait for: the statement stands and the brief follows straight away.
            self._set_goal(self.detected, 'assumed', radio, ctx, announce=False)
            self._offer(radio, ctx, 'B-01', variants, key='program:question')
            return
        message = self._offer(radio, ctx, 'B-01', variants, key='program:question')
        self.question = {'id': message.id, 'asked': None}

    def _set_goal(self, goal, source, radio, ctx, *, announce=True, note=None):
        changed = goal != self.goal
        self.goal, self.source = goal, source
        self.version += 1
        self.question = None
        if ctx is not None:
            self.update_facts(ctx)  # lines offered from now on belong to the new goal
        if changed:
            self.brief_due, self.brief_wait = True, None
        self.engineer_wanted = goal == 'practice1'
        if goal == 'practice2' and self.candidate and (self.tracker is None or changed):
            self.tracker = ObjectiveTracker(self.candidate)
        if not announce:
            return
        spoken = GOAL_SPEECH[goal]
        extra = {'practice1': ' Setup work and learning the track.', 'practice2': '',
                 'free': ' No plan, just the usual calls.'}[goal]
        on_track = not ctx.pit_radio
        if on_track:
            extra = ''
        variants = (note,) if note else (f'Copy, {spoken}.{extra}', f'Understood, {spoken}.{extra}',
                                         f'Got it, {spoken}.{extra}')
        self._offer(radio, ctx, 'V-24' if on_track else 'B-01', variants)

    # --- replies -------------------------------------------------------------------------
    def reply(self, intent, radio, ctx, source):
        """Apply one driver reply. Returns what was understood and the engineer's answer."""
        record = {'t': ctx.t if ctx else None, 'source': source, 'text': intent.text,
                  'understood': intent.describe(), 'response': None}
        self.replies.append(record)
        if not self.active or ctx is None:
            record['response'] = 'Practice plans apply in a practice session with the live coach running.'
            return record
        on_track = not ctx.pit_radio
        kind = intent.kind
        if kind == 'confirm':
            if self.goal is None or self.question:
                self._set_goal(self.detected, source, radio, ctx)
                record['response'] = 'Session set to ' + GOAL_LABEL[self.goal] + '.'
            else:
                record['response'] = 'Nothing to confirm right now; the session is ' + GOAL_LABEL[self.goal] + '.'
        elif kind == 'deny':
            current = self.goal or self.detected
            if intent.excluded and intent.excluded != current:
                new = current  # "it's not practice one" while I have practice two confirms it
            elif current == 'practice2':
                new = 'practice1'
            elif current == 'practice1':
                new = 'practice2' if self.candidate else 'free'
            else:
                new = 'practice2' if self.candidate else 'practice1'
            self._set_goal(new, source, radio, ctx)
            record['response'] = 'Changed to ' + GOAL_LABEL[new] + '.'
        elif kind == 'goal':
            if intent.goal == 'practice2' and not self.candidate:
                self._set_goal('practice1', source, radio, ctx, note=(
                    'No R&D plan is waiting for this car and track, so I have this as practice one. '
                    'Lock your goals on the R&D page first.' if not on_track else
                    'No R&D plan waiting here. Staying with practice one.'))
                record['response'] = 'No locked R&D plan is waiting for this driver, car and track; kept Practice 1.'
            else:
                self._set_goal(intent.goal, source, radio, ctx)
                record['response'] = 'Done; the engineer confirms on the radio.'
        elif kind == 'plan':
            self.brief(radio, ctx, on_track=on_track, requested=True)
            record['response'] = 'Plan repeated on the radio.'
        elif kind in ('progress', 'debrief'):
            self.debrief(radio, ctx, on_track=on_track, requested=True)
            record['response'] = 'Status given on the radio.'
        else:
            record['response'] = ('Not understood. Try "this is practice two", "confirm", "negative", '
                                  '"what\'s the plan", "how am I doing" or "debrief".')
        return record

    def set_goal(self, goal, radio, ctx, source='screen'):
        if goal not in GOAL_LABEL:
            raise ValueError('Choose Practice 1, Practice 2 or free practice.')
        if not self.active or ctx is None:
            raise ValueError('Practice plans apply in a practice session with the live coach running.')
        if goal == 'practice2' and not self.candidate:
            raise ValueError('No locked R&D plan is waiting for Practice 2 with this driver, car, track and layout.')
        self._set_goal(goal, source, radio, ctx)

    # --- spoken content ------------------------------------------------------------------
    def _where(self, goal, short=False):
        if len(goal['corners']) == 1 or (not short and len(goal['corners']) <= 4):
            return turn_words(goal['corners'])
        return goal['group'] if short else f"the {integer_words(len(goal['corners']))} {goal['group']}"

    def _objective_line(self, goal, n):
        t = goal['target']
        if goal['kind'] == 'corner':
            body = (f"average {integer_words(int(round(t)))} kilometres an hour faster than practice one "
                    f"through {self._where(goal)}")
        elif goal['kind'] == 'pace':
            body = (f"average under {lap_words(self.numbers, t)}, "
                    f"{self.numbers.tenths(max(0, self.tracker.reference - t)).speech} faster than practice one")
        elif goal['kind'] == 'fuel':
            body = f"use under {self.numbers.fuel_burn(t).speech} on laps within a second of practice one pace"
        elif goal['kind'] == 'endurance':
            body = 'one clean flying lap within three seconds of practice one pace'
        else:
            body = 'one clean flying lap'
        return f'Objective {ordinal(n)}: {body}'

    def _short_goal(self, goal):
        t = goal['target']
        if goal['kind'] == 'corner':
            return f"{self._where(goal, short=True)} plus {integer_words(int(round(t)))}"
        if goal['kind'] == 'pace':
            return 'under ' + lap_words(self.numbers, t)
        if goal['kind'] == 'fuel':
            return 'fuel under ' + number_words(t, 2)
        return 'one clean lap' if goal['kind'] == 'clean_lap' else 'a clean lap within three seconds'

    def _status(self, goal, short=False):
        s = self.tracker.summary(goal)
        if goal['kind'] in ('clean_lap', 'endurance'):
            what = 'clean lap' if goal['kind'] == 'clean_lap' else 'clean lap within three seconds'
            return f'{what} done' if s['met'] else f'{what} still needed'
        if goal['kind'] == 'corner':
            name = self._where(goal, short=True) if short else self._where(goal)
        else:
            name = 'lap time' if goal['kind'] == 'pace' else 'fuel'
        if s['actual'] is None:
            return f'{name}: no counted laps yet'
        over = '' if short else ' over ' + self._plural(s['laps'], 'lap')
        if goal['kind'] == 'corner':
            sign = 'plus' if s['actual'] >= 0 else 'minus'
            verdict = 'met' if s['met'] else f"{number_words(goal['target'] - s['actual'])} short"
            return f"{name} {sign} {number_words(abs(s['actual']))} average{over}, {verdict}"
        if goal['kind'] == 'pace':
            verdict = 'met' if s['met'] else f"{self.numbers.tenths(s['actual'] - goal['target']).speech} short"
            return f"{name} average {lap_words(self.numbers, s['actual'])}{over}, {verdict}"
        verdict = 'met' if s['met'] else 'over target'
        return f"fuel {number_words(s['actual'], 2)} litres a lap{over}, {verdict}"

    # --- briefs and debriefs -------------------------------------------------------------
    def radio_reset(self, radio):
        """The engine cleared the radio queue (session change or telemetry gap). An unheard
        question or brief is offered again while the car is still in the same stop."""
        if self.question and self.question['asked'] is None:
            self.question = None
        if (self.goal and self.phase.startswith('pits') and self.brief_keys
                and any(key not in radio.last_by_key for key in self.brief_keys)):
            self.brief_due, self.brief_keys = True, []

    def brief(self, radio, ctx, *, on_track=False, requested=False):
        """The run plan in the pits; on track only when asked, as short answers."""
        self.brief_due, self.brief_wait = False, None
        self.brief_keys = []
        if self.goal == 'practice2' and self.tracker:
            goals = self.tracker.goals
            if on_track:
                self._offer(radio, ctx, 'V-24', ('Objectives: ' + join([self._short_goal(g) for g in goals]),))
                return
            open_goals = [g for g in goals if not self.tracker.summary(g)['met']]
            if self.run == 0 or requested:
                count = self._plural(len(goals), 'objective').capitalize()
                self._offer(radio, ctx, 'B-08', (f'Practice two, {self._projects()} research. {count}.',
                                                 f'Practice two plan: {self._projects()} research, {count.lower()}.',
                                                 f'Right, practice two for the {self._projects()} research. {count}.'))
                for n, goal in enumerate(goals, 1):
                    self._offer(radio, ctx, 'B-08', (self._objective_line(goal, n),))
                if self.run == 0:
                    self._offer(radio, ctx, 'B-08', ("Only flying laps the game counts. I'll tell you how each one compares.",
                                                     "Flying laps the game counts only. I'll report after each one.",
                                                     "Clean flying laps count. You'll get the numbers after each one."))
            elif not open_goals:
                self._offer(radio, ctx, 'B-08', ('Every objective is met so far. Extra clean laps add to the averages.',
                                                 'All objectives met so far. More clean laps firm up the averages.',
                                                 'Objectives all met. Extra clean laps just add to the averages.'))
            else:
                todo = join([self._status(g, short=True) for g in open_goals])
                run = integer_words(self.run + 1)
                self._offer(radio, ctx, 'B-08', (f'Run {run}. Still to do: {todo}', f'Still open for run {run}: {todo}',
                                                 f'For run {run}, still to do: {todo}'))
            return
        if self.goal == 'practice1':
            code = 'V-24' if on_track else 'B-08'
            state = self._engineer()
            if not state:
                self._offer(radio, ctx, code, ('Practice one. Settle in and learn the track; the engineer analyses each run when you come in.',
                                               'Practice one: learn the track and build up. I analyse each run when you come in.',
                                               'Practice one. Build up and learn the track; each run gets analysed when you come in.')
                            if not on_track else ('Practice one: learn the track, setup analysis at each stop.',))
                return
            plan = state.get('next_run') or {}
            run = integer_words(int(state.get('runs') or 0) + 1)
            laps, fuel = plan.get('laps'), plan.get('fuel_l')
            amount = (f'{self._plural(int(laps), "lap")} on {integer_words(int(fuel))} litres. ' if laps and fuel
                      else f'{self._plural(int(laps), "lap")} on whatever fuel is in. ' if laps else '')
            objective = str(plan.get('objective') or '').strip()
            if on_track:
                self._offer(radio, ctx, code, (f'Run {run}: {amount}'.strip(),))
                return
            self._offer(radio, ctx, code, (f'Practice one, run {run}: {amount}{objective}',
                                           f'Run {run}: {amount}{objective}', f'Next is run {run}. {amount}{objective}'))
            changes = change_words(state.get('pending_changes') or [], self.settings)
            if changes:
                self._offer(radio, ctx, code, ('Your confirmed setup changes are logged for this run.',))
            return
        if requested:
            self._offer(radio, ctx, 'V-24' if on_track else 'B-01', ('Free practice, no plan. Just the usual calls.',))

    def debrief(self, radio, ctx, *, on_track=False, requested=False):
        if self.goal == 'practice2' and self.tracker:
            if on_track:
                lines = [self._status(g, short=True) for g in self.tracker.goals if not self.tracker.summary(g)['met']]
                for line in lines or ['every objective met so far']:
                    self._offer(radio, ctx, 'V-24', (line,))
                return
            lines = [self._status(g) for g in self.tracker.goals]
            head = f'Run {integer_words(self.run)} done. ' if not requested and self.run else ''
            parts, chunk = [], []
            for line in lines:
                if chunk and len(' '.join(chunk + [line]).split()) > 30:
                    parts.append(chunk)
                    chunk = []
                chunk.append(line)
            if chunk:
                parts.append(chunk)
            for i, chunk in enumerate(parts):
                text = ('' if i else head) + '. '.join(sentence(x).rstrip('.') for x in chunk)
                self._offer(radio, ctx, 'D-01', (text,))
            if not requested and self.run == 1:
                self._offer(radio, ctx, 'D-01', ('Final credit is assessed when you add this session to the weekend.',
                                                 'The official assessment happens when this session is filed in the weekend.',
                                                 'Credit is only assessed once you file this session in the weekend.'))
            return
        if self.goal == 'practice1':
            code = 'V-24' if on_track else 'S-03'
            if not self.last_engineer:
                self._offer(radio, ctx, code, ('No run analysed yet. That happens when you come back in.',))
            else:
                self._engineer_lines(radio, ctx, self.last_engineer, code, short=on_track)
            return
        if requested:
            self._offer(radio, ctx, 'V-24' if on_track else 'B-01', ('Free practice, so no plan to report on.',))

    def _engineer(self):
        if not self.engineer_state:
            return None
        try:
            return self.engineer_state()
        except Exception:
            return None

    def _engineer_lines(self, radio, ctx, info, code, short=False):
        recs = [r for r in info.get('recommendations') or [] if not r.get('test')]
        recs.sort(key=lambda r: (r.get('priority', 2), -abs(int(r.get('ticks') or 0))))
        trends = []
        for r in recs:
            setting = r.get('setting') or ''
            if setting.startswith('pressure_'):
                trend = SETUP_TRENDS['pressures']
            elif setting.startswith('camber_'):
                trend = SETUP_TRENDS['camber']
            else:
                category = r.get('category') or (self.settings.get(setting) or {}).get('category')
                trend = SETUP_TRENDS.get(category)
            if trend and trend not in trends:
                trends.append(trend)
        if short:
            self._offer(radio, ctx, code, ('There are setup changes to review when you come in.' if recs else 'No setup changes suggested.',))
            return
        best, laps = info.get('best_lap'), info.get('laps')
        detail = []
        if laps:
            detail.append(self._plural(int(laps), 'flying lap'))
        if best:
            detail.append('best ' + lap_words(self.numbers, best))
        head = f"Run {integer_words(int(info.get('run') or 1))} analysed"
        self._offer(radio, ctx, code, (head + (': ' + ', '.join(detail) if detail else ''),))
        if not recs:
            self._offer(radio, ctx, code, ('No setup changes suggested from that run.', 'Nothing to change from that run.',
                                           'The engineer has no changes from that run.'))
            return
        summary = '. '.join(trends[:2]) + '. ' if trends else ''
        self._offer(radio, ctx, code, (summary + SETUP_REVIEW_LINE,))

    def engineer_result(self, info, radio, ctx):
        """The setup engineer analysed a Practice 1 run."""
        self.last_engineer = info
        if self.goal not in ('practice1', 'practice2') or ctx is None or not self.active:
            return
        self._engineer_lines(radio, ctx, info, 'S-03')
        self.brief_due, self.brief_wait = True, 'leave_or_garage'

    # --- per tick ------------------------------------------------------------------------
    def feed(self, tick, player, ctx, radio):
        if not self.active or tick.session_id != self.session_id or tick.session != 'practice':
            return
        if self.question and self.question['asked'] is None:
            spoken = radio.last_by_key.get('program:question')
            if spoken is not None:
                self.question['asked'] = spoken['t']
        if self.goal is None:
            if self.question and self.question['asked'] is not None and ctx.t - self.question['asked'] > REPLY_S:
                self._set_goal(self.detected, 'assumed', radio, ctx, announce=False)  # no answer
            elif player is not None and player.pit == 0 and ctx.active:
                self._set_goal(self.detected, 'assumed', radio, ctx, announce=False)  # left without answering
            elif self.question is None and ctx.pit_radio and player is not None:
                self._ask(radio, ctx)
        garage = ctx.pit_radio and not ctx.active
        on_track = bool(ctx.active and player is not None and player.pit == 0)
        if on_track and not self.in_run:
            self.in_run, self.run_started = True, ctx.t
            self.phase = f'track:{self.run}'
            self.update_facts(ctx)
            if self.brief_due and self.goal:
                self.brief_due, self.brief_wait = False, None  # not heard before leaving: not while driving
        elif self.in_run and player is not None and player.pit in (1, 2, 4) and (ctx.active or ctx.pit_radio):
            self.in_run = False
            self.phase = f'pits:{self.run + 1}'
            self.update_facts(ctx)
            if ctx.t - self.run_started > 20:
                self.run += 1
                if self.goal == 'practice2':
                    self.debrief(radio, ctx)
                    # The reminder for the next run waits for the garage or the car rolling again.
                    self.brief_due, self.brief_wait = True, 'leave_or_garage'
        if self.tracker and self.goal == 'practice2':
            for kind, *payload in self.tracker.feed(tick, player, ctx.active):
                self._progress(kind, payload, radio, ctx)
        if self.goal and self.goal != 'free' and self.brief_due and ctx.pit_radio and not self.in_run:
            if self.brief_wait == 'leave_or_garage':
                # Rolling out of the box or garage, not still arriving down the pit lane.
                leaving = player is not None and (player.pit in (3, 5) or (player.pit in (2, 4) and finite(ctx.speed, 0) > 1))
                if (self.was_garage and ctx.active) or leaving:
                    self.brief(radio, ctx)
            else:
                self.brief(radio, ctx)
        self.was_garage = garage or (self.was_garage and not ctx.active)

    def _progress(self, kind, payload, radio, ctx):
        n = self.numbers
        if kind == 'corners':
            goal, result = payload
            mean, target = result['mean'], goal['target']
            where = self._where(goal, short=True)
            value = f"{'plus' if mean >= 0 else 'minus'} {number_words(abs(mean))}"
            if mean >= target - 1e-8:
                verdict = 'target met' if mean - target < .5 else f'target met by {number_words(mean - target)}'
            else:
                verdict = f'{number_words(target - mean)} short'
            self._lap_call(radio, ctx, goal, result['lap'], (f'{where} {value} that lap, {verdict}',
                                                            f'That lap, {where} {value}, {verdict}',
                                                            f'{where}: {value}, {verdict}'),
                           {'deltas_kph': {k: round(v, 2) for k, v in result['deltas'].items()},
                            'mean_kph': round(mean, 2), 'target_kph': target,
                            'method': 'median_speed_10m_grid_within_20m_of_apex_vs_practice1'})
            return
        (result,) = payload
        if not result['eligible']:
            return
        for goal in self.tracker.goals:
            if goal['kind'] == 'pace':
                t, target = result['time'], goal['target']
                verdict = 'under target' if t <= target else f'{n.tenths(t - target).speech} short'
                self._lap_call(radio, ctx, goal, result['lap'], (f'Lap {lap_words(n, t)}, {verdict}',
                                                                f'{lap_words(n, t)} that lap, {verdict}',
                                                                f'Lap time {lap_words(n, t)}, {verdict}'),
                               {'time': t, 'target': target})
            elif goal['kind'] == 'fuel' and result['fuel_used'] is not None and abs(result['time'] - self.tracker.reference) <= 1:
                used, target = result['fuel_used'], goal['target']
                verdict = 'under target' if used <= target else f'over by {number_words(used - target, 2)}'
                self._lap_call(radio, ctx, goal, result['lap'],
                               (f'Fuel {number_words(used, 2)} litres that lap, {verdict}',),
                               {'fuel_used': used, 'target': target, 'time': result['time']})
            elif goal['kind'] in ('clean_lap', 'endurance') and goal['id'] not in self.tracker.met_once:
                if goal['kind'] == 'endurance' and abs(result['time'] - self.tracker.reference) > 3:
                    continue
                self.tracker.met_once.add(goal['id'])
                what = 'Clean lap done' if goal['kind'] == 'clean_lap' else 'Clean lap within three seconds'
                self._lap_call(radio, ctx, goal, result['lap'], (f'{what}. Objective met', f'{what}, objective met',
                                                                f'{what}. That one is met'), {'time': result['time']})

    def _lap_call(self, radio, ctx, goal, lap, variants, evidence):
        key = 'objective:' + goal['id']
        # A newer result for the same objective replaces one still waiting for a straight.
        self.facts[key] = ctx.facts[key] = f"{goal['id']}:{lap}"
        self._offer(radio, ctx, 'C-43', variants, requirements=(Requirement(key, ctx.facts[key]),),
                    evidence={'objective': goal['id'], 'lap': lap, **evidence})

    def status(self):
        if not self.active:
            return {'active': False, 'lookup_error': self.lookup_error}
        cand = self.candidate
        return {'active': True, 'goal': self.goal, 'goal_label': GOAL_LABEL.get(self.goal), 'source': self.source,
                'detected': self.detected, 'question_open': bool(self.question), 'replies_enabled': self.replies_enabled,
                'candidate': {'champ': cand['champ'], 'round': cand['round'],
                              'projects': [p.get('name') or p['category'] for p in cand['projects']]} if cand else None,
                'other_candidates': max(0, len(self.candidates) - 1), 'lookup_error': self.lookup_error,
                'run': self.run, 'objectives': self.tracker.status() if self.tracker else [],
                'engineer': {'wanted': self.engineer_wanted, 'last': {k: self.last_engineer.get(k) for k in ('run', 'best_lap', 'laps')}
                             if self.last_engineer else None},
                'replies': list(self.replies), 'lines': list(self.lines)}
