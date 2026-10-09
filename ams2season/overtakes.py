"""Overtaking and defending: who passes, who holds position, and where.

Gaps come from the line: at the end of every lap, the time to the car that crossed just before (the car ahead)
and just after (the car behind). A lap ending within 1 s of the car ahead is a lap spent attacking; one with a
car within 1 s behind is a lap spent defending.
  A lap on which a pass was made also counts as attacking (passes happen mid-lap), and one on which you were
  passed counts as defending. Lap 1 is left out: the start is its own thing.
  pass rate = laps spent attacking that ended with a pass / laps spent attacking
  hold rate = laps spent defending without losing the place / laps spent defending
Gifted passes (the other driver spun or went off) are counted separately and don't move either rating.
"""
from __future__ import annotations

import pandas as pd

ATTACK_S = 1.0


def overtaking(ra) -> dict:
    from .race import COUNTED
    laps = ra.laps.sort_values(["lap", "t_end"]).copy()
    laps["gap_ahead"] = laps.groupby("lap").t_end.diff()
    laps["gap_behind"] = -laps.groupby("lap").t_end.diff(-1)
    passes = ra.passes if ra.passes is not None else pd.DataFrame(columns=["passer", "passed", "kind", "corner", "lap"])
    passes = passes[passes.kind.isin(COUNTED)]  # pit cycles and unconfirmed/lap-traffic changes are not passes
    is_ai = dict(zip(ra.entrants.name, ra.entrants.is_ai.astype(bool)))
    cls = ra.classification
    grid = dict(zip(cls.name, cls.grid)) if "grid" in cls else {}
    finish = dict(zip(cls.name, cls.pos)) if "pos" in cls else {}
    out = []
    for n in cls.name:
        mine = laps[(laps.name == n) & (laps.lap > 1)]
        made = passes[(passes.passer == n) & (passes.kind != "gifted")]
        lost = passes[(passes.passed == n) & (passes.kind != "gifted")]
        # a lap spent attacking: ended within 1 s of the car ahead, or a pass was made on it (passes happen mid-lap)
        pass_laps, lost_laps = set(made.lap.astype(int)) - {1}, set(lost.lap.astype(int)) - {1}
        attack_set = set(mine[mine.gap_ahead < ATTACK_S].lap.astype(int)) | pass_laps
        defend_set = set(mine[mine.gap_behind < ATTACK_S].lap.astype(int)) | lost_laps
        attack, defend = len(attack_set), len(defend_set)
        gift_in = int(((passes.passer == n) & (passes.kind == "gifted")).sum())
        gift_out = int(((passes.passed == n) & (passes.kind == "gifted")).sum())
        rate = round(100 * len(pass_laps) / attack) if attack else None          # laps attacking that ended in a pass
        hold = round(100 * (1 - len(lost_laps) / defend)) if defend else None     # laps defending that kept the place
        fav = made.corner.value_counts() if len(made) else pd.Series(dtype=int)
        weak = lost.corner.value_counts() if len(lost) else pd.Series(dtype=int)
        g, f = grid.get(n), finish.get(n)
        out.append({"name": n, "is_ai": bool(is_ai.get(n, True)), "made": int(len(made)), "made_contact": int((made.kind == "contact").sum()),
                    "pass_laps": len(pass_laps), "lost_laps": len(lost_laps),
                    "lost": int(len(lost)), "gifted_gained": gift_in, "gifted_lost": gift_out,
                    "attack_laps": attack, "defend_laps": defend, "pass_rate": rate, "hold_rate": hold,
                    "lap1_gain": int(((passes.passer == n) & (passes.lap == 1)).sum() - ((passes.passed == n) & (passes.lap == 1)).sum()),
                    "net": None if g is None or f is None or g != g or f != f else int(g - f),
                    "favourite": None if fav.empty else {"corner": fav.index[0], "passes": int(fav.iloc[0])},
                    "weak_spot": None if weak.empty else {"corner": weak.index[0], "passes": int(weak.iloc[0])},
                    "victims": sorted(set(made.passed)), "passed_by": sorted(set(lost.passer))})
    return {"drivers": out}
