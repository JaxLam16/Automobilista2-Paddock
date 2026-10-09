"""Driving-style fingerprints of 20 famous F1 drivers, and how close your own measured style is to each.

The legends aren't measured. There's no telemetry for Fangio or Senna on these metrics, so each one is a
fingerprint of their well-known strengths, from 0 to 10 on the same dimensions the app measures for you
(10 = a defining trait). Matching compares the SHAPE of two profiles (what stands out for you, relative to
your own average, against what stands out for them), not their level, so nobody is compared on raw pace
with a world champion.
"""
from __future__ import annotations

import math
import numpy as np

DIMENSIONS = [
    ("qualifying", "Qualifying", "Where you start: your average grid slot against the field."),
    ("race_pace", "Race pace", "Your typical clean lap against the field's."),
    ("consistency", "Consistency", "How little your clean laps vary: 2% lap-time variation scores 50; under 0.5% scores over 94."),
    ("braking", "Braking precision", "Hitting the same braking points lap after lap."),
    ("throttle", "Throttle control", "Repeatable power application and commitment. Recorded pedals filter brief shift transients and allow small modulation; other cars use a speed-derived pickup proxy."),
    ("track_usage", "Track usage", "Sustained wheel clearance at entry, apex and exit. Supported linked corners and intended narrow exits are exempt from wide-exit scoring."),
    ("overtaking", "Overtaking", "Laps spent attacking that ended with a pass."),
    ("defending", "Defending", "Laps spent defending that kept the place."),
    ("starts", "Starts", "First-lap position against the observed starting grid. Holding position scores 50, holding pole scores 100. Gains and losses are scaled to the places available ahead or behind; missing start evidence stays unrated."),
    ("clean", "Clean driving", "Percentage of race laps without a detected mistake that cost time."),
    ("tyres", "Tyre management", "Tyre wear and lock-ups against the field (needs your own recordings)."),
    ("late_race", "Late-race pace", "Whether your laps get quicker or slower as a race goes on."),
]
LABEL = {k: l for k, l, _ in DIMENSIONS}

LEGENDS = [
    {"key": "fangio", "name": "Juan Manuel Fangio", "years": "1950-1958", "blurb": "Five titles in the sport's first decade: relentless race pace, mechanical sympathy and almost no mistakes.",
     "style": {"qualifying": 8, "race_pace": 10, "consistency": 9, "braking": 8, "throttle": 9, "track_usage": 6, "overtaking": 7, "defending": 7, "starts": 7, "clean": 9, "tyres": 9, "late_race": 9}},
    {"key": "clark", "name": "Jim Clark", "years": "1960-1968", "blurb": "Effortless and silky: led from the front with a delicacy on the throttle few have matched.",
     "style": {"qualifying": 10, "race_pace": 10, "consistency": 9, "braking": 8, "throttle": 10, "track_usage": 6, "overtaking": 6, "defending": 6, "starts": 8, "clean": 9, "tyres": 8, "late_race": 8}},
    {"key": "stewart", "name": "Jackie Stewart", "years": "1965-1973", "blurb": "Precise, tidy and safety-minded: won by being smoother and making fewer errors than anyone.",
     "style": {"qualifying": 7, "race_pace": 8, "consistency": 9, "braking": 9, "throttle": 9, "track_usage": 5, "overtaking": 6, "defending": 7, "starts": 7, "clean": 10, "tyres": 9, "late_race": 8}},
    {"key": "lauda", "name": "Niki Lauda", "years": "1971-1985", "blurb": "Analytical and metronomic: drove to the limit he'd calculated, never past it.",
     "style": {"qualifying": 7, "race_pace": 8, "consistency": 10, "braking": 9, "throttle": 8, "track_usage": 4, "overtaking": 5, "defending": 7, "starts": 6, "clean": 9, "tyres": 9, "late_race": 8}},
    {"key": "hunt", "name": "James Hunt", "years": "1973-1979", "blurb": "Fast, flamboyant and on the edge: brilliant on his day, scrappy on others.",
     "style": {"qualifying": 9, "race_pace": 7, "consistency": 4, "braking": 6, "throttle": 6, "track_usage": 9, "overtaking": 8, "defending": 6, "starts": 8, "clean": 3, "tyres": 5, "late_race": 6}},
    {"key": "villeneuve", "name": "Gilles Villeneuve", "years": "1977-1982", "blurb": "Pure commitment: never gave an inch, wheel to wheel or on the kerbs, whatever the risk.",
     "style": {"qualifying": 8, "race_pace": 7, "consistency": 3, "braking": 5, "throttle": 4, "track_usage": 10, "overtaking": 9, "defending": 9, "starts": 10, "clean": 2, "tyres": 3, "late_race": 6}},
    {"key": "prost", "name": "Alain Prost", "years": "1980-1993", "blurb": "Nicknamed 'The Professor': smooth, calculating and easy on his tyres, winning without seeming to hurry.",
     "style": {"qualifying": 5, "race_pace": 9, "consistency": 10, "braking": 8, "throttle": 10, "track_usage": 4, "overtaking": 6, "defending": 6, "starts": 6, "clean": 10, "tyres": 10, "late_race": 9}},
    {"key": "senna", "name": "Ayrton Senna", "years": "1984-1994", "blurb": "The ultimate one-lap driver: total commitment, kerb to kerb, and uncompromising in combat.",
     "style": {"qualifying": 10, "race_pace": 9, "consistency": 7, "braking": 9, "throttle": 8, "track_usage": 10, "overtaking": 9, "defending": 9, "starts": 8, "clean": 6, "tyres": 6, "late_race": 8}},
    {"key": "mansell", "name": "Nigel Mansell", "years": "1980-1995", "blurb": "Nicknamed 'Il Leone': a fearless, bruising racer who loved a pass round the outside.",
     "style": {"qualifying": 8, "race_pace": 8, "consistency": 5, "braking": 6, "throttle": 6, "track_usage": 9, "overtaking": 10, "defending": 7, "starts": 7, "clean": 5, "tyres": 5, "late_race": 8}},
    {"key": "schumacher", "name": "Michael Schumacher", "years": "1991-2012", "blurb": "Relentless: lap after lap at qualifying pace, ferocious in defence and strongest late in a race.",
     "style": {"qualifying": 8, "race_pace": 10, "consistency": 9, "braking": 9, "throttle": 8, "track_usage": 8, "overtaking": 7, "defending": 9, "starts": 8, "clean": 8, "tyres": 8, "late_race": 10}},
    {"key": "hakkinen", "name": "Mika Häkkinen", "years": "1991-2001", "blurb": "Nicknamed 'The Flying Finn': devastating over one lap, calm and quick in the race.",
     "style": {"qualifying": 10, "race_pace": 9, "consistency": 7, "braking": 8, "throttle": 8, "track_usage": 8, "overtaking": 7, "defending": 6, "starts": 6, "clean": 7, "tyres": 7, "late_race": 7}},
    {"key": "raikkonen", "name": "Kimi Räikkönen", "years": "2001-2021", "blurb": "Nicknamed 'The Iceman': cool, quick in the race, kind to tyres and sharp off the line.",
     "style": {"qualifying": 6, "race_pace": 9, "consistency": 7, "braking": 7, "throttle": 8, "track_usage": 8, "overtaking": 7, "defending": 6, "starts": 9, "clean": 7, "tyres": 8, "late_race": 8}},
    {"key": "alonso", "name": "Fernando Alonso", "years": "2001-", "blurb": "A master of racecraft: rocket starts, a near-impossible car to pass, and always fast at the end.",
     "style": {"qualifying": 6, "race_pace": 9, "consistency": 9, "braking": 8, "throttle": 8, "track_usage": 7, "overtaking": 8, "defending": 10, "starts": 10, "clean": 8, "tyres": 9, "late_race": 9}},
    {"key": "button", "name": "Jenson Button", "years": "2000-2017", "blurb": "Silky smooth: the gentlest hands on the wheel and feet on the pedals, superb on worn tyres.",
     "style": {"qualifying": 4, "race_pace": 6, "consistency": 8, "braking": 6, "throttle": 10, "track_usage": 4, "overtaking": 7, "defending": 6, "starts": 8, "clean": 9, "tyres": 10, "late_race": 8}},
    {"key": "vettel", "name": "Sebastian Vettel", "years": "2007-2022", "blurb": "At his best out front: blistering qualifying laps and a rhythm nobody could live with.",
     "style": {"qualifying": 9, "race_pace": 8, "consistency": 7, "braking": 8, "throttle": 8, "track_usage": 7, "overtaking": 6, "defending": 5, "starts": 8, "clean": 6, "tyres": 7, "late_race": 7}},
    {"key": "hamilton", "name": "Lewis Hamilton", "years": "2007-", "blurb": "Complete: fastest over one lap, precise on the brakes, and able to look after his tyres while still attacking.",
     "style": {"qualifying": 10, "race_pace": 9, "consistency": 8, "braking": 9, "throttle": 9, "track_usage": 7, "overtaking": 9, "defending": 7, "starts": 6, "clean": 8, "tyres": 9, "late_race": 9}},
    {"key": "ricciardo", "name": "Daniel Ricciardo", "years": "2011-2024", "blurb": "Nicknamed 'The Honey Badger': the late-braking lunge was his signature move.",
     "style": {"qualifying": 6, "race_pace": 7, "consistency": 6, "braking": 9, "throttle": 6, "track_usage": 7, "overtaking": 10, "defending": 5, "starts": 7, "clean": 6, "tyres": 6, "late_race": 7}},
    {"key": "verstappen", "name": "Max Verstappen", "years": "2015-", "blurb": "Ruthless and fast everywhere: uses every inch of track and gives none away in a fight.",
     "style": {"qualifying": 9, "race_pace": 10, "consistency": 8, "braking": 9, "throttle": 8, "track_usage": 10, "overtaking": 9, "defending": 9, "starts": 7, "clean": 6, "tyres": 7, "late_race": 9}},
    {"key": "leclerc", "name": "Charles Leclerc", "years": "2018-", "blurb": "A qualifying specialist: on the edge over one lap, kerb to kerb, though the race can bite back.",
     "style": {"qualifying": 10, "race_pace": 7, "consistency": 5, "braking": 8, "throttle": 7, "track_usage": 9, "overtaking": 7, "defending": 7, "starts": 6, "clean": 4, "tyres": 4, "late_race": 5}},
    {"key": "norris", "name": "Lando Norris", "years": "2019-", "blurb": "Quick and smooth: a strong qualifier with tidy, well-rounded race pace.",
     "style": {"qualifying": 9, "race_pace": 8, "consistency": 7, "braking": 7, "throttle": 8, "track_usage": 7, "overtaking": 6, "defending": 6, "starts": 5, "clean": 6, "tyres": 7, "late_race": 7}},
]


def _clip(v):
    return None if v is None or not math.isfinite(v) else float(max(0.0, min(100.0, v)))


def start_score(grid, lap1_position, field_size):
    """Rate one observed start, adjusting improvement for the places available.

    A place gained from second uses the sole available passing opportunity, whereas
    one gained from twentieth uses only one of nineteen. Neither simply starting
    near the back nor field size grants points. Holding pole is the best attainable
    result, and every loss remains below 50 even when it starts from pole.
    """
    values = (grid, lap1_position, field_size)
    if any(isinstance(v, bool) or not isinstance(v, (int, float, np.number))
           or not math.isfinite(v) or float(v) != int(v) for v in values):
        return None
    grid, position, size = map(int, values)
    if size < 2 or not 1 <= grid <= size or not 1 <= position <= size:
        return None
    gain = grid - position
    if gain == 0:
        return 100.0 if grid == 1 else 50.0
    if gain > 0:
        return 50.0 + 50.0 * math.sqrt(gain / (grid - 1))
    return 50.0 - 50.0 * math.sqrt(-gain / (size - grid))


def scores_from_raw(raw: dict) -> dict:
    """Your measurements on a 0-100 scale per dimension (50 = roughly typical), None where there's no data."""
    def g(key):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float, np.number)) or not math.isfinite(value):
            return None
        if key in ('lap_cv_pct', 'grid_pct', 'clean_share') and value < 0:
            return None
        return float(value)
    return {
        "qualifying": _clip(100 * g("grid_pct")) if g("grid_pct") is not None else None,
        "race_pace": _clip(50 - 25 * g("pace_rel_pct")) if g("pace_rel_pct") is not None else None,
        "consistency": _clip(100 / (1 + (g("lap_cv_pct") / 2.0) ** 2)) if g("lap_cv_pct") is not None else None,
        "braking": _clip(g("brake_consistency")),
        "throttle": _clip(g("throttle_consistency")),
        "track_usage": _clip(g("track_usage")),
        "overtaking": _clip(20 + g("pass_rate")) if g("pass_rate") is not None else None,
        "defending": _clip((g("hold_rate") - 50) * 2) if g("hold_rate") is not None else None,
        # Current profiles store the opportunity-adjusted score per race before
        # averaging. Keep the old gain-only API for older standalone callers, but
        # explicit missing start evidence must never fall back to a made-up score.
        "starts": _clip(g("start_score")) if "start_score" in raw else
                  (_clip(50 + 50 * math.tanh(g("lap1_gain") / 4)) if g("lap1_gain") is not None else None),
        "clean": _clip(g("clean_share")),
        "tyres": _clip(g("tyre_score")),
        "late_race": _clip(50 - 300 * g("trend_pct")) if g("trend_pct") is not None else None,
    }


def match(scores: dict, min_dims: int = 6) -> list[dict]:
    """Every legend, most similar first. Similarity is the correlation between the two profiles' shapes
    (each centred on its own average) over the dimensions you have data for, shown as 0-100%."""
    dims = [k for k, _, _ in DIMENSIONS if scores.get(k) is not None]
    if len(dims) < min_dims:
        return []
    you = np.array([scores[k] for k in dims], float)
    yc = you - you.mean()
    out = []
    for lg in LEGENDS:
        them = np.array([lg["style"][k] * 10 for k in dims], float)
        tc = them - them.mean()
        den = np.linalg.norm(yc) * np.linalg.norm(tc)
        r = float(yc @ tc / den) if den > 1e-9 else 0.0
        prod = sorted(((yc[i] * tc[i], dims[i], yc[i], tc[i]) for i in range(len(dims))), reverse=True)
        shared_hi = [{"dim": d, "label": LABEL[d], "you": round(scores[d]), "them": lg["style"][d]} for p, d, a, b in prod if a > 0 and b > 0][:3]
        shared_lo = [{"dim": d, "label": LABEL[d], "you": round(scores[d]), "them": lg["style"][d]} for p, d, a, b in prod[::-1] if a < 0 and b < 0][:2]
        diff = sorted(((abs(yc[i] - tc[i]), dims[i], yc[i], tc[i]) for i in range(len(dims))), reverse=True)
        differs = [{"dim": d, "label": LABEL[d], "you": round(scores[d]), "them": lg["style"][d], "you_higher": bool(a > b)} for _, d, a, b in diff[:2]]
        out.append({"key": lg["key"], "name": lg["name"], "similarity": round((r + 1) / 2 * 100), "r": round(r, 3),
                    "shared_strengths": shared_hi, "shared_weaknesses": shared_lo, "differences": differs})
    return sorted(out, key=lambda m: -m["r"])
