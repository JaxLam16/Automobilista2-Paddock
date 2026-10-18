"""Practice programme: session goal question, briefs, live R&D objective progress, debriefs."""
from statistics import median

import numpy as np
import pytest

from ams2season.coach.engine import CoachEngine
from ams2season.coach.intents import parse
from ams2season.coach.model import Car, Tick
from ams2season.coach.numbers import Numbers
from ams2season.coach.program import ObjectiveTracker, PracticeProgram, change_words
from ams2season.coach.radio import Scheduler
from ams2season.engineer.catalog import BY_KEY

L = 2000.


def candidate(objectives=None, corner_kph=177.0):
    return {'champ': 'season', 'round': 2, 'plan': 'p', 'created_at': '2026-10-14',
            'projects': [{'category': 'front_aero', 'name': 'Front aero', 'objectives': objectives or [
                {'id': 'repeatability', 'kind': 'clean_lap', 'target': 1, 'text': 'One clean lap.'},
                {'id': 'performance', 'kind': 'corner', 'corners': ['T1'], 'target': 4.0, 'text': '4 km/h at T1.'}]}],
            'baseline': {'driver': 'Player', 'car': 'GT3', 'track': 'Track', 'layout': 'Layout', 'length': L,
                         'median': 40.0, 'average': 40.0, 'fuel_used': 2.0, 'corner_speeds': {'T1': corner_kph, 'T2': 170.0},
                         'corners': [{'name': 'T1', 'apex': 500.0}, {'name': 'T2', 'apex': 1500.0}],
                         'kinds': {'fast': ['T1'], 'corner': ['T2'], 'exit': ['T2']}}}


class Sim:
    """A 2000 m practice lap at a steady 50 m/s (40 s laps), starting in the pit box."""

    def __init__(self, engine, *, session_id='live:1', fuel=60.0):
        self.engine, self.session_id = engine, session_id
        self.t, self.d, self.laps, self.last_lap, self.lap_start, self.fuel = 0.0, 1900.0, 0, None, None, fuel
        self.spoken, self.invalid = [], False

    def run(self, seconds, *, pit, speed, game=2, burn=0.0):
        for _ in range(int(round(seconds * 10))):
            car = Car(0, 'Player', 'GT3', 'GT3', 1, self.laps, self.d, speed, pit, 2, self.invalid, 0, last_lap=self.last_lap)
            local = {'speed': speed, 'throttle': 1.0 if speed > 15 else 0.3, 'brake': 0.0, 'steering': 0.0, 'gear': 5,
                     'rain_density': 0.0, 'crash_state': 0, 'local_lap_invalid': self.invalid, 'yellow_flag_state': 0,
                     'fuel_capacity': 100.0, 'fuel_level': self.fuel / 100}
            tick = Tick(self.t, self.session_id, 'practice', 'Track', 'Layout', L, game, 0, (car,), local)
            call = self.engine.feed(tick, radio_busy=False)
            if call:
                self.engine.radio.acknowledge(call, self.engine.context, accepted=True, simulated=True)
                self.spoken.append((round(self.t, 1), call.message.spec.code, call.text))
            self.t = round(self.t + .1, 1)
            if speed:
                self.d += speed * .1
                self.fuel -= burn * speed * .1 / L
                if self.d >= L:
                    self.d -= L
                    self.laps += 1
                    if self.lap_start is not None:
                        self.last_lap = round(self.t - self.lap_start, 3)
                    self.lap_start = self.t
                    self.invalid = False

    def codes(self, code):
        return [text for _, c, text in self.spoken if c == code]

    def planned(self, code):
        """The first wording of each line the programme offered (the radio rotates wordings)."""
        return [line['text'] for line in self.engine.program.lines if line['code'] == code]


def engine_with(plans=(), engineer=None, replies=True):
    program = PracticeProgram(Numbers(), plan_lookup=lambda *args: list(plans), engineer_state=engineer, settings=BY_KEY)
    program.replies_enabled = replies
    return CoachEngine('Player', Scheduler(), program=program)


def reply(engine, text, source='typed'):
    return engine.program.reply(parse(text), engine.radio, engine.context, source)


def test_practice_two_is_detected_from_a_waiting_plan_asked_and_confirmed_by_voice():
    engine = engine_with([candidate()])
    sim = Sim(engine)
    sim.run(3, pit=2, speed=0)
    question = sim.codes('B-01')
    assert question == ['Looks like practice two, for the front aero research. Confirm?']
    assert engine.program.goal is None and engine.program.status()['question_open']
    result = reply(engine, 'confirm', 'voice')
    assert result['response'] == 'Session set to Practice 2: R&D objectives.'
    sim.run(30, pit=2, speed=0)
    assert sim.codes('B-01')[-1] in ('Copy, practice two.', 'Understood, practice two.', 'Got it, practice two.')
    brief = sim.codes('B-08')
    assert brief[0].startswith('Practice two') and 'front aero research' in brief[0] and 'wo objectives' in brief[0]
    assert 'Objective one: one clean flying lap.' in brief
    assert 'Objective two: average four kilometres an hour faster than practice one through turn one.' in brief
    assert engine.program.goal == 'practice2' and engine.program.source == 'voice'


def test_no_answer_uses_the_detected_goal_and_still_briefs():
    engine = engine_with([candidate()])
    sim = Sim(engine)
    sim.run(40, pit=2, speed=0)
    assert engine.program.goal == 'practice2' and engine.program.source == 'assumed'
    assert any(t.startswith('Objective two') for t in sim.codes('B-08'))


def test_without_voice_replies_it_states_the_goal_instead_of_asking():
    engine = engine_with([], replies=False)
    sim = Sim(engine)
    sim.run(3, pit=2, speed=0)
    assert sim.codes('B-01') == ['Treating this as practice one: setup work and learning the track. Change it on the coach page if not.']


@pytest.mark.parametrize('text,plans,goal', [
    ('No, this is practice session 2', [candidate()], 'practice2'),
    ("no it's not practice two", [candidate()], 'practice1'),
    ('negative', [candidate()], 'practice1'),
    ('free practice', [candidate()], 'free'),
    ('negative', [], 'free'),
    ('this is practice 2', [], 'practice1'),   # no waiting plan: it cannot be practice 2
])
def test_free_text_and_voice_replies_set_the_goal(text, plans, goal):
    engine = engine_with(plans)
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    reply(engine, text)
    assert engine.program.goal == goal
    sim.run(20, pit=2, speed=0)
    if text == 'this is practice 2':
            assert sim.codes('B-01')[-1].startswith('No R&D plan is waiting for this car and track')


def test_unknown_text_changes_nothing_and_says_so():
    engine = engine_with([candidate()])
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    result = reply(engine, 'what do you think about the weather')
    assert result['understood'] == 'Not understood' and engine.program.goal is None


def test_live_corner_objective_matches_the_rd_method_and_reports_after_the_corner():
    engine = engine_with([candidate(corner_kph=177.0)])
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    reply(engine, 'confirm', 'voice')
    sim.run(20, pit=2, speed=0)
    sim.run(3, pit=3, speed=15)          # pit lane
    sim.run(130, pit=0, speed=50)        # out-lap and three flying laps
    queued = [e for e in engine.radio.log.events if e['state'] == 'queued' and e.get('code') == 'C-43'
              and 'mean_kph' in e['evidence']['values']]
    assert queued, 'a corner result is offered after turn one on a flying lap'
    values = queued[0]['evidence']['values']
    assert values['mean_kph'] == pytest.approx(180.0 - 177.0)
    assert values['method'] == 'median_speed_10m_grid_within_20m_of_apex_vs_practice1'
    assert queued[0]['distance'] == pytest.approx(530, abs=10)  # right after the corner
    spoken = sim.codes('C-43')
    assert any(t == 'Turn one plus three point zero that lap, one point zero short.' or 'one point zero short' in t for t in spoken)
    assert any('Clean lap done' in t for t in spoken)
    status = engine.program.status()['objectives']
    corner = next(o for o in status if o['kind'] == 'corner')
    assert corner['laps'] >= 2 and corner['actual'] == pytest.approx(3.0) and not corner['met']
    assert next(o for o in status if o['kind'] == 'clean_lap')['met']


def test_corner_speed_uses_the_rd_grid_median_on_a_varying_trace():
    tracker = ObjectiveTracker(candidate())
    profile = lambda s: 40 + 0.01 * ((s - 500) ** 2) ** .5 + 0.37 * np.sin(s / 7)  # m/s
    xs = np.arange(0, 1000, 3.3)
    for x in xs:
        tracker.samples.append((float(x), float(profile(x) * 3.6)))
    got = tracker._corner_speed(500.0)
    grid = np.arange(0, L, 10.0)
    near = grid[np.abs(grid - 500) <= 20]
    expected = float(np.median(np.interp(near, xs, profile(xs) * 3.6)))
    assert got == pytest.approx(expected, rel=1e-9)


def test_invalid_or_out_laps_never_report_progress():
    engine = engine_with([candidate()])
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    reply(engine, 'confirm', 'voice')
    sim.run(20, pit=2, speed=0)
    sim.run(3, pit=3, speed=15)
    sim.invalid = True                   # the game invalidates the out-lap and the next lap
    sim.run(2, pit=0, speed=50)
    events = [e for e in engine.radio.log.events if e.get('code') == 'C-43']
    assert not events
    sim.run(45, pit=0, speed=50)  # crosses the line: the invalid flag resets, but the out-lap never counts
    assert not [e for e in engine.radio.log.events if e.get('code') == 'C-43' and e['state'] == 'queued'
                and e['evidence']['values'].get('lap') == 0]


def test_pace_and_fuel_objectives_report_each_lap():
    objectives = [{'id': 'performance', 'kind': 'pace', 'target': 39.7, 'text': 'pace'}]
    fuel = [{'id': 'performance', 'kind': 'fuel', 'target': 1.99, 'text': 'fuel'}]
    for goals, expect in ((objectives, 'Lap forty zero, three tenths short.'), (fuel, 'Fuel two point zero zero litres that lap, over by zero point zero one.')):
        engine = engine_with([candidate(goals)])
        sim = Sim(engine)
        sim.run(2, pit=2, speed=0)
        reply(engine, 'confirm', 'voice')
        sim.run(25, pit=2, speed=0)
        sim.run(3, pit=3, speed=15)
        sim.run(140, pit=0, speed=50, burn=2.0)
        texts = [e['text'] for e in engine.radio.log.events if e.get('code') == 'C-43' and e.get('text')]
        assert any(expect.rstrip('.') in t or t == expect for t in texts + sim.codes('C-43')), (texts, sim.codes('C-43'))


@pytest.mark.parametrize('goals,expect', [
    ([{'id': 'performance', 'kind': 'pace', 'target': 39.7, 'text': 'pace'}], 'lap time average forty zero over'),
    ([{'id': 'performance', 'kind': 'fuel', 'target': 1.99, 'text': 'fuel'}], 'fuel two point zero zero litres a lap over'),
    ([{'id': 'performance', 'kind': 'endurance', 'target': 1, 'text': 'endurance'}], 'clean lap within three seconds done'),
])
def test_every_objective_kind_has_a_debrief_and_answers(goals, expect):
    engine = engine_with([candidate(goals)])
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    reply(engine, 'confirm', 'voice')
    sim.run(25, pit=2, speed=0)
    sim.run(3, pit=3, speed=15)
    sim.run(130, pit=0, speed=50, burn=2.0)
    reply(engine, 'how am I doing', 'voice')
    reply(engine, "what's the plan", 'voice')
    sim.run(4, pit=1, speed=20)
    sim.run(30, pit=2, speed=0)
    assert any(expect in t.lower() for t in sim.planned('D-01')), sim.planned('D-01')
    assert sim.planned('V-24')


def test_run_end_debrief_in_the_pits_and_garage_menu_then_next_brief():
    engine = engine_with([candidate()])
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    reply(engine, 'confirm', 'voice')
    sim.run(25, pit=2, speed=0)
    sim.run(3, pit=3, speed=15)
    sim.run(90, pit=0, speed=50)
    sim.run(4, pit=1, speed=20)          # pit entry
    sim.run(3, pit=2, speed=0)
    sim.run(40, pit=4, speed=0, game=4)  # straight into the garage menu
    debrief = sim.codes('D-01')
    assert debrief and debrief[0].startswith('Run one done.')
    assert 'turn one plus three point zero average over' in debrief[0].lower()
    assert 'Final credit is assessed when you add this session to the weekend.' in sim.planned('D-01')
    assert len(debrief) == 2
    assert not any('Still' in t for t in sim.codes('B-08'))   # no repeat straight after the debrief
    sim.run(10, pit=2, speed=0)                                  # back in the car after the garage
    assert sim.planned('B-08')[-1].startswith('Run two. Still to do: turn one plus three point zero average, one point zero short')


def test_pit_lines_are_dropped_when_the_car_leaves_and_never_spend_the_lap_budget():
    engine = engine_with([candidate()])
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    reply(engine, 'confirm', 'voice')
    sim.run(0.3, pit=2, speed=0)       # the acknowledgement starts; the brief waits behind it
    sim.run(3, pit=3, speed=15)
    sim.run(60, pit=0, speed=50)       # leaves before the brief is finished
    spoken = [(t, c) for t, c, _ in sim.spoken if c == 'B-08']
    assert all(t < 5.3 for t, _ in spoken)  # nothing from the brief once on track
    dropped = [e for e in engine.radio.log.events if e.get('code') == 'B-08' and e['state'] == 'dropped']
    assert dropped and all(e['reason'] == 'condition_changed' for e in dropped)
    sim.run(4, pit=1, speed=20)
    sim.run(10, pit=2, speed=0)
    assert not [c for t, c, text in sim.spoken if c == 'B-08' and text.startswith('Objective')and t > 60]
    assert all(lap_count == 0 for (lap, urgency), lap_count in engine.radio.per_lap.items() if urgency == 1)


def test_on_track_questions_get_short_answers():
    engine = engine_with([candidate()])
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    reply(engine, 'confirm', 'voice')
    sim.run(25, pit=2, speed=0)
    sim.run(3, pit=3, speed=15)
    sim.run(110, pit=0, speed=50)            # radio windows are learned from two clean laps
    reply(engine, "what's the plan", 'voice')
    reply(engine, 'how am I doing', 'voice')
    sim.run(30, pit=0, speed=50)
    answers = sim.codes('V-24')
    assert 'Objectives: one clean lap and turn one plus four.' in answers
    assert all(len(a.split()) <= 13 for a in answers)


def test_practice_one_engineer_debrief_groups_wheels_and_waits_to_brief():
    state = {'runs': 1, 'next_run': {'fuel_l': 45, 'laps': 5, 'objective': 'Try the 2 changes below and confirm they help.'},
             'pending_changes': [{'setting': 'downforce_rear', 'ticks': 1}]}
    engine = engine_with([], engineer=lambda: state)
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    reply(engine, 'confirm', 'voice')
    sim.run(25, pit=2, speed=0)
    first = sim.codes('B-08')
    assert sim.planned('B-08') == ['Practice one, run two: five laps on forty-five litres. Try the 2 changes below and confirm they help.',
                                   'Your confirmed setup changes are logged for this run.']
    assert len(first) == 2 and 'confirmed setup changes' in first[1]
    sim.run(3, pit=3, speed=15)
    sim.run(50, pit=0, speed=50)
    sim.run(3, pit=1, speed=20)
    sim.run(2, pit=2, speed=0)
    engine.program.engineer_result({'run': 2, 'best_lap': 40.0, 'laps': 1, 'recommendations': [
        {'setting': 'pressure_fl', 'ticks': -2, 'priority': 1}, {'setting': 'pressure_fr', 'ticks': -2, 'priority': 1},
        {'setting': 'brake_bias', 'ticks': 1, 'priority': 2}, {'setting': 'downforce_rear', 'ticks': 1, 'priority': 3, 'test': True}]},
        engine.radio, engine.context)
    sim.run(20, pit=2, speed=0)
    debrief = sim.codes('S-03')
    assert debrief[0] == 'Run two analysed: one flying lap, best forty zero.'
    assert sim.planned('S-03')[1] == "The tyre pressures need attention. There are braking or traction changes to try. I've got some setup changes for you. Take a look at the garage checklist."
    assert 'garage checklist' in debrief[1] and 'clicks' not in debrief[1]
    assert len(sim.codes('B-08')) == 2  # the next brief waits for the garage or the car to roll
    sim.run(5, pit=4, speed=0, game=4)
    sim.run(10, pit=2, speed=0)
    assert len(sim.codes('B-08')) == 4


def test_change_words_groups_matching_wheels():
    words = change_words([{'setting': k, 'ticks': -1} for k in ('pressure_fl', 'pressure_fr', 'pressure_rl', 'pressure_rr')]
                         + [{'setting': 'camber_fl', 'ticks': 2}, {'setting': 'camber_fr', 'ticks': 2},
                            {'setting': 'arb_rear', 'ticks': -1}, {'setting': 'nonsense', 'ticks': 3}], BY_KEY)
    assert words == ['all four tyre pressures down one click', 'front camber more negative two clicks',
                     'rear anti-roll bar softer one click']


def test_lookup_failure_falls_back_to_practice_one_and_reports_it():
    def broken(*args):
        raise OSError('championship locked')
    program = PracticeProgram(Numbers(), plan_lookup=broken)
    engine = CoachEngine('Player', Scheduler(), program=program)
    Sim(engine).run(1, pit=2, speed=0)
    status = engine.status()['program']
    assert status['detected'] == 'practice1' and 'locked' in status['lookup_error']


def test_other_sessions_and_replays_without_a_programme_are_unchanged():
    engine = CoachEngine('Player', Scheduler())
    sim = Sim(engine)
    sim.run(5, pit=2, speed=0)
    assert engine.status()['program'] is None and not sim.spoken


def test_a_telemetry_gap_in_the_pits_repeats_the_unheard_brief():
    engine = engine_with([candidate()])
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    reply(engine, 'confirm', 'voice')
    sim.run(1.5, pit=2, speed=0)
    sim.t += 3                             # capture gap: the radio queue is cleared
    sim.run(40, pit=2, speed=0)
    dropped = [e for e in engine.radio.log.events if e.get('code') == 'B-08' and e.get('reason') == 'telemetry_gap']
    assert dropped
    assert any(t.startswith('Objective two') for t in sim.codes('B-08'))


def test_a_gap_after_the_brief_was_heard_does_not_repeat_it():
    engine = engine_with([candidate()])
    sim = Sim(engine)
    sim.run(2, pit=2, speed=0)
    reply(engine, 'confirm', 'voice')
    sim.run(40, pit=2, speed=0)
    heard = len(sim.codes('B-08'))
    sim.t += 3
    sim.run(30, pit=2, speed=0)
    assert len(sim.codes('B-08')) == heard
