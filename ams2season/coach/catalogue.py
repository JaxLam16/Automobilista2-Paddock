"""Implemented messages only. IDs follow the user's feature planning reference."""
from .model import MessageSpec, PRACTICE_SUMMARY_S


# Practice programme (coach/program.py). Its lines are composed from measured or planned
# content, so the programme supplies three wordings of each line as slots {a} {b} {c}.
_SCRIPTED = ('{a}', '{b}', '{c}')

CATALOGUE = {
    # Session goal question and its acknowledgements, in the pits or the garage menu.
    'B-01': MessageSpec('B-01','briefing',1,_SCRIPTED,sessions=('practice',),cooldown_s=0,ttl_s=180,window='pits',vary=False),
    # Run plan before leaving the pits: R&D objectives or the setup engineer's next run.
    'B-08': MessageSpec('B-08','briefing',2,_SCRIPTED,sessions=('practice',),cooldown_s=0,ttl_s=600,window='pits',vary=False),
    # Live R&D objective progress, on a straight after the measured corner or lap.
    'C-43': MessageSpec('C-43','coaching',2,_SCRIPTED,sessions=('practice',),cooldown_s=0,
                        ttl_s=PRACTICE_SUMMARY_S,vary=False),
    # Setup engineer's suggestions after a Practice 1 run, in the pits.
    'S-03': MessageSpec('S-03','setup',2,_SCRIPTED,sessions=('practice',),cooldown_s=0,ttl_s=600,window='pits',vary=False),
    # Objective status after a Practice 2 run, in the pits.
    'D-01': MessageSpec('D-01','debrief',2,_SCRIPTED,sessions=('practice',),cooldown_s=0,ttl_s=600,window='pits',vary=False),
    # An answer to the driver on track ("what's the plan?", "how am I doing?").
    'V-24': MessageSpec('V-24','briefing',2,_SCRIPTED,sessions=('practice',),cooldown_s=0,ttl_s=60,vary=False),
    # Standalone engineer basics (coach/car_status.py), worded live, three variants each.
    # Lap time at the line, with the comparison to the session best (race: best laps only).
    'C-35': MessageSpec('C-35','timing',2,_SCRIPTED,sessions=('practice','qualify','race'),cooldown_s=0,ttl_s=20,vary=False),
    # The game has deleted the lap (its own lap-invalid flag).
    'Q-09': MessageSpec('Q-09','timing',2,_SCRIPTED,sessions=('practice','qualify','race'),cooldown_s=0,ttl_s=15,vary=False),
    # Cold tyres and/or brakes as the car leaves the pits.
    'W-02': MessageSpec('W-02','car',2,_SCRIPTED,sessions=('practice','qualify','race'),cooldown_s=0,ttl_s=25,vary=False),
    # Tyres reached their window after leaving cold.
    'W-05': MessageSpec('W-05','car',2,_SCRIPTED,sessions=('practice','qualify','race'),cooldown_s=0,ttl_s=30,vary=False),
    # An axle's tyres running hot, or cooled well below the window after being warm.
    'M-02': MessageSpec('M-02','car',2,_SCRIPTED,sessions=('practice','qualify','race'),cooldown_s=0,ttl_s=30,vary=False),
    # Iron brakes over their range two laps running.
    'M-10': MessageSpec('M-10','car',2,_SCRIPTED,sessions=('practice','qualify','race'),cooldown_s=0,ttl_s=40,vary=False),
    # About three, two, one laps of fuel left, from the measured burn.
    'M-17': MessageSpec('M-17','car',1,_SCRIPTED,sessions=('practice','qualify','race'),cooldown_s=0,ttl_s=40,vary=False),
    # Damage after a hit (the game's own damage values), and engine temperatures well above normal.
    'M-23': MessageSpec('M-23','car',1,_SCRIPTED,sessions=('practice','qualify','race'),cooldown_s=0,ttl_s=30,vary=False),
    'M-13': MessageSpec('M-13','car',2,_SCRIPTED,sessions=('practice','qualify','race'),cooldown_s=0,ttl_s=30,vary=False),
    # Five consecutive counted laps within a few tenths.
    'C-30': MessageSpec('C-30','coaching',4,_SCRIPTED,sessions=('practice',),cooldown_s=0,ttl_s=30,vary=False),
    # Recon lap on request: each corner called just before the car reaches it.
    'V-25': MessageSpec('V-25','recon',1,_SCRIPTED,sessions=('practice','qualify','race','time_attack'),cooldown_s=0,ttl_s=10,vary=False),
    # {detail} is empty or one measured phase fact, e.g. ", lower minimum speed".
    'C-01': MessageSpec('C-01','coaching',3,(
        'Biggest loss: {turn}, {loss}{detail}.',
        'Main loss: {turn}, {loss}{detail}.',
        'Largest loss: {turn}, {loss}{detail}.'),
        sessions=('practice',),pattern=True,cooldown_s=120,ttl_s=PRACTICE_SUMMARY_S),
    # A warning from the game's own off-track state on a lap it still counts.
    'C-26': MessageSpec('C-26','coaching',3,(
        'Wide again {place}. Careful, track limits.',
        'Running wide {place}. Watch the track limits.',
        'Wide {place} again. A little further, track limits.'),
        sessions=('practice','qualify','race'),cooldown_s=120,ttl_s=20),
    'C-05': MessageSpec('C-05','coaching',3,(
        'Braking starts about {amount} earlier at {turn}.',
        'Your braking begins about {amount} earlier at {turn}.',
        'Brake input starts about {amount} earlier at {turn}.'),
        sessions=('practice',),pattern=True,cooldown_s=90,ttl_s=PRACTICE_SUMMARY_S),
    'C-09': MessageSpec('C-09','coaching',3,(
        'Minimum speed is down at {turn}.',
        'Your minimum speed is lower at {turn}.',
        'You are slowing more at {turn}.'),sessions=('practice',),pattern=True,cooldown_s=90,ttl_s=PRACTICE_SUMMARY_S),
    'G-01': MessageSpec('G-01','racecraft',2,(
        'Timing gap: {gap} ahead, {trend}.',
        'Measured gap: {gap} ahead, {trend}.',
        '{gap} ahead at timing, {trend}.'),
        sessions=('race',),cooldown_s=90,ttl_s=12,fact_count=2),
    'S-16': MessageSpec('S-16','coaching',3,(
        'Measured fuel use {use}.',
        'Fuel use is averaging {use}.',
        'Your measured burn is {use}.'),
        sessions=('practice',),cooldown_s=180,ttl_s=PRACTICE_SUMMARY_S),
    'G-18': MessageSpec('G-18','racecraft',2,(
        'Timing gap behind {gap}, {trend}.',
        'Measured gap behind {gap}, {trend}.',
        'Gap behind at the timing point: {gap}, {trend}.'),
        sessions=('race',),cooldown_s=90,ttl_s=12,fact_count=2),
    "X-15": MessageSpec("X-15", "rivals", 2, (
        "The {relation} is pitting.", "The {relation} is entering the pits.",
        "Pit entry for the {relation}."), sessions=("race",), cooldown_s=30, ttl_s=10),
    "C-10": MessageSpec("C-10", "coaching", 3, (
        "You're missing the apex at {turn}.", "Aim closer to the apex at {turn}.",
        "Bring the car closer to the apex at {turn}."), pattern=True, cooldown_s=60, ttl_s=PRACTICE_SUMMARY_S),
    "G-08": MessageSpec("G-08", "racecraft", 2, (
        "You're gaining on the car ahead through {turn}.",
        "You're quicker than the car ahead through {turn}.",
        "Your advantage over the car ahead is through {turn}."),
        sessions=("race",), pattern=True, cooldown_s=90, ttl_s=15),
    "X-02": MessageSpec("X-02", "racecraft", 2, (
        "You're losing time to the car ahead on the exit of {turn}.",
        "The car ahead is gaining time on the exit of {turn}.",
        "Watch your exit at {turn}. The car ahead is gaining there."),
        sessions=("race",), pattern=True, cooldown_s=90, ttl_s=15),
}
