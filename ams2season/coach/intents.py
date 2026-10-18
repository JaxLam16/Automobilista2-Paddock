"""What the driver told the engineer, from a Crew Chief voice reply or typed text.

Crew Chief's speech recognition only matches phrases it has been given, so a voice
reply arrives as one of the tokens written by Paddock's reply macros (see
crew_chief.REPLY_MACROS). Typed text is free-form; this parser understands the
same intents from ordinary sentences such as "No, this is practice session 2".
Anything it cannot place is returned as unknown and never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

GOALS = ('practice1', 'practice2', 'free')
MAX_TEXT = 200

_NUMBER = {'one': '1', 'first': '1', '1st': '1', 'two': '2', 'second': '2', '2nd': '2'}
_YES = r'(yes|yeah|yep|yup|confirm(ed)?|affirm(ative)?|copy( that)?|correct|that\'?s (right|correct)|right|ok(ay)?|roger|sure|go ahead)'
_NO = r'(no|nope|nah|negative|wrong|that\'?s wrong|not (quite|right|correct))'


@dataclass(frozen=True)
class Intent:
    kind: str                 # confirm, deny, goal, plan, progress, debrief, recon, unknown
    goal: str | None = None   # practice1, practice2 or free for kind 'goal'
    negated: bool = False     # the reply started with a no ("No, this is practice two")
    text: str = ''
    excluded: str | None = None  # "it's not practice two": a no that names the wrong goal

    def describe(self):
        return {'confirm': 'Confirm', 'deny': 'No', 'plan': 'Repeat the plan', 'progress': 'Objective progress',
                'debrief': 'Debrief now', 'recon': 'Recon lap: call the corners', 'unknown': 'Not understood'}.get(self.kind) or {
            'practice1': 'Practice 1: setup and learning the track', 'practice2': 'Practice 2: R&D objectives',
            'free': 'Free practice: no plan'}[self.goal]


def _normalise(text):
    text = text.lower().replace('&', ' and ').replace('’', "'")
    text = re.sub(r"[^a-z0-9' ]+", ' ', text)
    words = [_NUMBER.get(w, w) for w in text.split()]
    return ' '.join(words)


def _goal(text):
    # Numbered sessions first: in most series "free practice 2" is the second practice.
    if re.search(r'\b(p|fp|practi[cs]e|free practi[cs]e|session)\s*(session\s*)?(number\s*)?2\b', text) \
            or re.search(r'\b2 practi[cs]e\b', text) \
            or re.search(r'\b(r and d|r ?n ?d|research|development|objectives? (run|session)|test(ing)? the upgrades?)\b', text):
        return 'practice2'
    if re.search(r'\b(p|fp|practi[cs]e|free practi[cs]e|session)\s*(session\s*)?(number\s*)?1\b', text) \
            or re.search(r'\b1 practi[cs]e\b', text) \
            or re.search(r'\b((setup|set up) (run|work|session)|doing (the )?setup|learn(ing)?( the)? track|track learning|baseline run)\b', text):
        return 'practice1'
    if re.search(r'\b(free practi[cs]e|no plan|just (driving|practi[cs]ing|practi[cs]e|lapping)|hot ?laps?|fun run)\b', text):
        return 'free'
    return None


def parse(text):
    """Return the driver's intent. Voice tokens (confirm, practice2...) parse to themselves."""
    if not isinstance(text, str):
        raise ValueError('Replies must be text.')
    raw = text.strip()
    if not raw or len(raw) > MAX_TEXT or any(ord(c) < 32 for c in raw):
        raise ValueError(f'Type a short reply of at most {MAX_TEXT} characters.')
    words = _normalise(raw)
    if words in GOALS:
        return Intent('goal', words, text=raw)
    if words in ('plan', 'progress', 'debrief', 'recon'):
        return Intent(words, text=raw)
    if re.search(r"\b(recon|reconnaissance|talk me (through|round) the (corners|track|lap)|call( out)? the corners|corner names|track guide|guide me (round|around) the track)\b", words):
        return Intent('recon', text=raw)
    negated = bool(re.match(_NO + r'\b', words))
    goal = _goal(words)
    if goal and re.search(r"\b(not|isn'?t|it'?s not|this isn'?t)\b", words):
        # "It's not practice two": the named goal is the one that is wrong.
        return Intent('deny', negated=True, text=raw, excluded=goal)
    if goal:
        return Intent('goal', goal, negated, raw)
    if re.search(r'\b(debrief|sum (it )?up|summary)\b', words):
        return Intent('debrief', text=raw)
    if re.search(r"\b(how am i doing|how('s| is) it going|progress|status|how are the objectives|did i (meet|make|hit) (it|the target|the objective))\b", words):
        return Intent('progress', text=raw)
    if re.search(r"\b(what'?s the plan|what is the plan|(what are )?(my |the )?objectives|brief( me)?|what am i doing|run plan|remind me)\b", words):
        return Intent('plan', text=raw)
    if negated:
        return Intent('deny', negated=True, text=raw)
    if re.match(_YES + r'\b', words):
        return Intent('confirm', text=raw)
    return Intent('unknown', text=raw)
