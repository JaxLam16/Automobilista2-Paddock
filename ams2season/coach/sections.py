"""C-01: the biggest repeated section loss in practice, with measured phase facts only.

Self-comparison against the same exact-5m speed traces C-09 uses. Bends come from
the two fastest earlier clean intervals; the three most recent intervals are
compared with them. Each lap is split halfway between learned bends, and no
section crosses start/finish or the midpoint timing line where intervals begin.

A section qualifies when it is at least 0.15 s slower on two of the last three
intervals, including the latest, and both references agree on its time. The
largest such loss is reported only when at least two sections were measured, so
"biggest" is a real ranking. Phase facts (earlier braking, lower or higher
minimum speed, lower exit speed) must hold on every losing lap. Nothing here
attributes a cause, recommends a technique or compensates for tyre temperature.
"""
from collections import Counter
import math
from statistics import median

from .corner_speed import CornerSpeedWatch
from .model import finite, PRACTICE_SUMMARY_S


LOSS_S = .15          # repeated loss per section
REF_AGREE_S = .15     # both references agree on the section time
SPEED_KPH = 4         # a phase fact needs at least this speed difference
REF_SPEED_AGREE = .6  # m/s: both references agree on the speed they describe
EXIT_CELLS = 12       # exit speed is read 60 m after the bend's minimum
EDGE_M = 10           # sections stay this far from start/finish and the midpoint line
MAX_WORDS = 14        # every phrasing must fit a 6 s straight at the preview speaking rate


def partition(bends, length):
    """Cell ranges (lo, hi) per bend: halfway to its neighbours, never across a barrier."""
    barriers = (0., length/2, float(length))
    bends = sorted(bends)
    result = {}
    for i, bend in enumerate(bends):
        d = bend*5
        below = max(x for x in barriers if x < d)
        above = min(x for x in barriers if x > d)
        lo, hi = below+EDGE_M, above-EDGE_M
        if i > 0:
            lo = max(lo, (bends[i-1]*5+d)/2)
        if i+1 < len(bends):
            hi = min(hi, (bends[i+1]*5+d)/2)
        lo_i, hi_i = math.ceil(lo/5), math.floor(hi/5)
        if bend-lo_i >= 4 and hi_i-bend >= 4:   # at least 20 m either side of the minimum
            result[bend] = (lo_i, hi_i)
    return result


def measure(record, bend, lo, hi):
    cells = record['cells']
    if not all(i in cells for i in range(lo, hi+1)) or not all(i in cells for i in range(bend-3, bend+4)):
        return None
    exit_i = bend+EXIT_CELLS
    exit_speed = (median(cells[i]['speed'] for i in range(exit_i-1, exit_i+2)) if exit_i+1 <= hi else None)
    return {'lap': record['lap'], 'start_t': cells[lo]['t'], 'end_t': cells[hi]['t'],
            'seconds': cells[hi]['t']-cells[lo]['t'],
            'minimum_m_s': min(cells[i]['speed'] for i in range(bend-3, bend+4)),
            'exit_m_s': exit_speed}


def spoken(numbers, pattern, phrases):
    """Radio slots: the section, the loss, and at most one measured fact if it still fits."""
    turn = 'the bend near '+numbers.distance_m(pattern['distance_m']).speech
    loss = numbers.tenths(pattern['loss_s']).speech
    detail = ', '+pattern['facts'][0]['phrase'] if pattern['facts'] else ''
    if detail and max(len(p.format(turn=turn, loss=loss, detail=detail).split()) for p in phrases) > MAX_WORDS:
        detail = ''
    return {'turn': turn, 'loss': loss, 'detail': detail}


class SectionLossWatch:
    """Evaluated once per completed interval of the C-09 corner-speed watch."""

    def __init__(self):
        self.diagnostics = Counter()
        self.clear()

    def clear(self, reason='learning'):
        self.patterns = {}
        self.reason = reason
        self.ranking = []

    def evaluate(self, speed_watch, tick, brakes=None):
        """Return at most one confirmed C-01 pattern for the interval that just completed.

        brakes maps a bend key to a C-05 pattern confirmed on this same interval; it
        is the only source of a braking fact, so brake inputs keep C-05's own bars.
        """
        self.patterns, self.ranking = {}, []
        history, earlier, chosen = speed_watch.comparison_set(tick)
        if len(history) < 5 or not all(r['clean'] for r in history[-3:]):
            self.reason = 'need_five_clean_intervals'
            return []
        if len(earlier) < 2:
            self.reason = 'need_two_earlier_references'
            return []
        sections = partition(chosen, tick.length)
        references = sorted(earlier, key=lambda r: r['seconds'])[:2]
        recent_records = history[-3:]
        measured, candidates = [], []
        for bend, (lo, hi) in sections.items():
            self.diagnostics['sections_checked'] += 1
            refs = [measure(r, bend, lo, hi) for r in references]
            recent = [measure(r, bend, lo, hi) for r in recent_records]
            if any(r is None for r in refs+recent):
                self.diagnostics['incomplete_sections'] += 1
                continue
            if abs(refs[0]['seconds']-refs[1]['seconds']) > REF_AGREE_S:
                self.diagnostics['reference_sections_disagree'] += 1
                continue
            base = median(r['seconds'] for r in refs)
            for r in recent:
                r['slower_by_s'] = r['seconds']-base
            item = {'bend': bend, 'lo': lo, 'hi': hi, 'refs': refs, 'recent': recent}
            measured.append(item)
            misses = [r for r in recent if r['slower_by_s'] >= LOSS_S]
            if len(misses) >= 2 and recent[-1] in misses:
                item['misses'] = misses
                item['loss_s'] = min(r['slower_by_s'] for r in misses)
                candidates.append(item)
        self.ranking = [{'distance_m': m['bend']*5, 'latest_slower_by_s': round(m['recent'][-1]['slower_by_s'], 3)}
                        for m in sorted(measured, key=lambda m: m['recent'][-1]['slower_by_s'], reverse=True)]
        if not sections:
            self.reason = 'no_repeatable_bends'
            return []
        if len(measured) < 2:
            self.reason = 'need_two_measured_sections'
            return []
        if not candidates:
            self.reason = 'no_repeated_section_loss'
            return []
        best = max(candidates, key=lambda m: (m['loss_s'], -m['bend']))
        facts = self.facts(best, (brakes or {}).get(str(best['bend'])))
        bend, misses = best['bend'], best['misses']
        key = str(bend)
        value = {'key': key, 'distance_m': bend*5, 'section_start_m': best['lo']*5,
                 'section_end_m': best['hi']*5, 'loss_s': best['loss_s'],
                 'latest_loss_s': best['recent'][-1]['slower_by_s'],
                 'reference_sections': best['refs'], 'recent': best['recent'],
                 'pattern_laps': [r['lap'] for r in misses], 'facts': facts,
                 'measured_sections': len(measured), 'ranking': self.ranking[:5],
                 'source': 'earlier_local_speed_and_steering',
                 'scope': 'practice_local_self_comparison',
                 'cause_attributed': False, 'technique_recommended': False,
                 'thermal_compensation': False, 'measured_t': tick.t,
                 'token': f"section:{bend}:{history[-1]['lap']}:{tick.t}"}
        self.patterns[key] = value
        self.reason = 'confirmed_pattern'
        self.diagnostics['confirmed_patterns'] += 1
        return [value]

    @staticmethod
    def facts(item, brake=None):
        """Phase facts that hold on every losing lap, strongest-evidence first."""
        refs, misses, facts = item['refs'], item['misses'], []
        if brake is not None:
            facts.append({'fact': 'earlier_braking', 'phrase': 'earlier braking',
                          'earlier_by_m': brake['earlier_by_m'], 'source': 'C-05'})
        minima = [r['minimum_m_s'] for r in refs]
        if max(minima)-min(minima) <= REF_SPEED_AGREE:
            down = [(min(minima)-r['minimum_m_s'])*3.6 for r in misses]
            up = [(r['minimum_m_s']-max(minima))*3.6 for r in misses]
            if min(down) >= SPEED_KPH:
                facts.append({'fact': 'lower_minimum_speed', 'phrase': 'lower minimum speed',
                              'down_kph': min(down)})
            elif min(up) >= SPEED_KPH:
                facts.append({'fact': 'higher_minimum_speed', 'phrase': 'higher minimum speed',
                              'up_kph': min(up)})
        exits = [r['exit_m_s'] for r in refs]
        if all(finite(e) is not None for e in exits) and max(exits)-min(exits) <= REF_SPEED_AGREE:
            down = [(min(exits)-r['exit_m_s'])*3.6 if r['exit_m_s'] is not None else None for r in misses]
            if all(d is not None for d in down) and min(down) >= SPEED_KPH:
                facts.append({'fact': 'lower_exit_speed', 'phrase': 'lower exit speed',
                              'down_kph': min(down), 'measured_m_after_minimum': EXIT_CELLS*5})
        return facts

    def token(self, key, tick, player):
        value = self.patterns.get(key)
        return (value['token'] if value and CornerSpeedWatch.safe(tick, player)
                and 0 <= tick.t-value['measured_t'] < PRACTICE_SUMMARY_S else None)

    def status(self):
        return {'reason': self.reason, 'ranking': self.ranking[:5],
                'diagnostics': dict(self.diagnostics)}
