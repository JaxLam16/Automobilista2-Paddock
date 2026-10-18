"""Driver replies, spoken through Crew Chief or typed in Paddock."""
import pytest

from ams2season.coach.intents import parse
from ams2season.crew_chief import REPLY_MACROS


@pytest.mark.parametrize('text,kind,goal', [
    ('No, this is practice session 2', 'goal', 'practice2'),
    ("it's P2", 'goal', 'practice2'),
    ('this is FP2', 'goal', 'practice2'),
    ('second practice', 'goal', 'practice2'),
    ('R&D run', 'goal', 'practice2'),
    ('free practice 2', 'goal', 'practice2'),       # numbered free practice is a series session
    ('Nope, practice one', 'goal', 'practice1'),
    ("I'm doing setup work", 'goal', 'practice1'),
    ('learning the track', 'goal', 'practice1'),
    ('free practice', 'goal', 'free'),
    ('no plan', 'goal', 'free'),
    ('Yes', 'confirm', None),
    ("yeah that's right", 'confirm', None),
    ('copy that', 'confirm', None),
    ('No', 'deny', None),
    ("What's the plan?", 'plan', None),
    ('what are my objectives', 'plan', None),
    ('how am I doing', 'progress', None),
    ('Debrief please', 'debrief', None),
    ('what setup changes do you want', 'unknown', None),
    ('banana', 'unknown', None),
])
def test_free_text(text, kind, goal):
    intent = parse(text)
    assert (intent.kind, intent.goal) == (kind, goal)


def test_a_no_that_names_the_wrong_goal():
    intent = parse("No, it's not practice 2")
    assert intent.kind == 'deny' and intent.excluded == 'practice2'
    assert parse('No, this is practice session 2').negated


@pytest.mark.parametrize('token', [token for token, _ in REPLY_MACROS])
def test_every_voice_macro_token_parses_to_its_own_intent(token):
    intent = parse(token)
    expected = {'confirm': ('confirm', None), 'negative': ('deny', None), 'practice1': ('goal', 'practice1'),
                'practice2': ('goal', 'practice2'), 'free': ('goal', 'free'), 'plan': ('plan', None),
                'progress': ('progress', None), 'debrief': ('debrief', None), 'recon': ('recon', None)}[token]
    assert (intent.kind, intent.goal) == expected


@pytest.mark.parametrize('token,phrases', REPLY_MACROS)
def test_every_spoken_phrase_would_mean_the_same_if_typed(token, phrases):
    for phrase in phrases:
        assert (parse(phrase).kind, parse(phrase).goal) == (parse(token).kind, parse(token).goal), phrase


@pytest.mark.parametrize('bad', ['', '   ', 'x' * 201, 'line\nbreak', 7])
def test_invalid_replies_are_refused(bad):
    with pytest.raises(ValueError):
        parse(bad)
