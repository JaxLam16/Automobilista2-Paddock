"""Awards: every talking point the data supports, grouped and ranked by how interesting it is.

Each award is a dict:
    id, group, title, winner (name or None for whole-race awards), value (short), detail (sentence),
    score (higher = shown first), human (winner is one of you), t (replay time, optional)

`rank()` puts pinned award types first, then sorts by score; humans get a boost because the
debrief is about you and your friends, not the AI.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .race import COUNTED, RaceAnalysis, fmt_time

# id -> (group, title, what it means). Drives the "pin these" settings list.
RACE_CATALOG = {
    # from the newer analyses: errors, overtaking ratings, race pace and driving style
    "error_free": ("Errors", "Error-free", "Most laps without a mistake that cost time"),
    "spin_doctor": ("Errors", "Spin doctor", "Most spins"),
    "late_braker": ("Errors", "Late, later, latest", "Most corners overshot by braking too late"),
    "scenic_route": ("Errors", "Scenic route", "Most trips off the track"),
    "costliest_moment": ("Errors", "Most expensive mistake", "The costliest overshoot or slow corner (spins and offs are Costliest moment)"),
    "clinical": ("Overtaking", "Clinical", "Best pass rate: laps spent attacking that ended in a pass"),
    "immovable": ("Overtaking", "Immovable", "Best hold rate: laps spent defending that kept the place"),
    "opportunist": ("Overtaking", "Opportunist", "Most places picked up from other people's mistakes"),
    "strong_finish": ("Pace", "Strong finish", "Got quicker as the race went on"),
    "traffic_tamer": ("Pace", "Traffic tamer", "Lost the least time stuck behind other cars"),
    "smooth_power": ("Driving style", "Smooth on the power", "Most consistent throttle pickup"),
    "wheel_to_wheel": ("Driving style", "Wheel to wheel", "Most corners spent racing another car"),
    "apex_hunter": ("Driving style", "Apex hunter", "Closest to the apex, corner after corner"),
    "fastest_car": ("Pace", "Fastest car", "Car model with the quickest clean-lap pace"),
    "brake_metronome": ("Consistency", "Same marker every lap", "Most consistent braking points"),
    "track_usage": ("Consistency", "Every inch of road", "Uses the most of the track: kerb at the apex, edge on the way in and out"),
    "battle_of_race": ("Battles", "Battle of the race", "Longest nose-to-tail fight"),
    "swap_fest": ("Battles", "Swap fest", "Battle with the most position swaps"),
    "closest_finish": ("Battles", "Photo finish", "Smallest gap between two cars at the flag"),
    "winning_margin": ("Battles", "Winning margin", "How far the winner won by"),
    "friend_rivalry": ("Battles", "Rivalry of the race", "Two of you who swapped places the most"),
    "the_wall": ("Battles", "The wall", "Most battles defended without losing the place"),
    "most_passes": ("Overtaking", "Most passes", "Most on-track passes made"),
    "net_passing": ("Overtaking", "Best net passing", "Passes made minus passes conceded"),
    "human_hunter": ("Overtaking", "Friend hunter", "Most passes on other humans"),
    "corner_specialist": ("Overtaking", "Corner specialist", "Most passes by one driver at one corner"),
    "hotspot": ("Overtaking", "Overtaking hotspot", "The corner where most passes happened"),
    "clean_operator": ("Overtaking", "Clean operator", "Most passes with none gifted or by contact"),
    "biggest_climber": ("Positions", "Biggest climber", "Most places gained, start to finish"),
    "comeback": ("Positions", "Comeback drive", "Biggest recovery from a driver's lowest position"),
    "late_charge": ("Positions", "Late charge", "Most places gained in the final third"),
    "won_from": ("Positions", "Won from the back", "Winner started well down the grid"),
    "lights_to_flag": ("Positions", "Lights to flag", "Pole and led every lap"),
    "lead_changes": ("Positions", "Lead changes", "How often the lead changed hands"),
    "most_laps_led": ("Positions", "Most laps led", "Laps completed in the lead"),
    "lap1_hero": ("Start", "Lap 1 hero", "Most places gained on the opening lap"),
    "holeshot": ("Start", "Holeshot", "Led lap 1 without starting on pole"),
    "lap1_nightmare": ("Start", "Lap 1 nightmare", "Most places lost on the opening lap"),
    "fastest_lap": ("Pace", "Fastest lap", "Quickest valid lap of the race"),
    "race_pace": ("Pace", "Best race pace", "Lowest median clean lap"),
    "fastest_vs_ai": ("Pace", "Quickest vs the AI", "Human with the best pace relative to the AI"),
    "ultimate_lap": ("Pace", "Ultimate lap", "Best sectors stitched together"),
    "sector_kings": ("Pace", "Sector kings", "Fastest in each sector"),
    "final_lap_flyer": ("Pace", "Final lap flyer", "Quickest last lap among finishers"),
    "got_faster": ("Pace", "Got faster", "Biggest pace improvement from first to second half"),
    "top_speed": ("Pace", "Top speed", "Highest speed reached"),
    "metronome": ("Consistency", "Metronome", "Lowest lap-time spread"),
    "clean_sheet": ("Consistency", "Clean sheet", "Finished with no invalidated laps"),
    "track_limits": ("Consistency", "Track limits", "Most invalidated laps"),
    "fastest_stop": ("Strategy", "Fastest stop", "Quickest trip through the pit lane"),
    "spin_cost": ("Hard luck", "Costliest moment", "Most places lost in one moment (spin or off)"),
    "biggest_faller": ("Hard luck", "Biggest drop", "Most places lost, start to finish"),
    "revolving_door": ("Hard luck", "Revolving door", "Most passes conceded"),
    "retirements": ("Hard luck", "Retirements", "Who didn't make it to the flag"),
    "contact": ("Hard luck", "Contact", "Most contacts (recording driver only)"),
}

SEASON_CATALOG = {
    "s_wins": ("Results", "Most wins", "Overall race wins"),
    "s_podiums": ("Results", "Podium regular", "Overall top-three finishes"),
    "s_field_pct": ("Results", "Field beater", "Best average share of the grid beaten"),
    "s_steady": ("Results", "Mr consistent", "Smallest spread of finishing positions"),
    "s_iron_man": ("Results", "Iron man", "Most races started without a DNF"),
    "s_improved": ("Results", "Most improved", "Finishing position trending up through the season"),
    "s_h2h_king": ("Rivalries", "Head-to-head king", "Best record finishing ahead of the other humans"),
    "s_rivalry": ("Rivalries", "Rivalry of the season", "Two of you who traded the most passes"),
    "s_human_hunter": ("Rivalries", "Friend hunter", "Most passes on other humans"),
    "s_passes": ("Overtaking", "Most passes", "Season total of on-track passes"),
    "s_net_passes": ("Overtaking", "Best net passing", "Passes made minus passes conceded"),
    "s_places": ("Overtaking", "Places gained", "Total places gained from the grid"),
    "s_comeback": ("Overtaking", "Comeback king", "Biggest total recoveries from low points"),
    "s_lap1": ("Overtaking", "Lap 1 specialist", "Average places gained on lap 1"),
    "s_battles": ("Overtaking", "Battle winner", "Best win rate in battles"),
    "s_wall": ("Overtaking", "The wall", "Most battles defended"),
    "s_hotspot": ("Overtaking", "Hotspot of the season", "Track corner with the most passes"),
    "s_pace": ("Pace", "Fastest vs the AI", "Best average pace relative to the AI"),
    "s_fastest_laps": ("Pace", "Fastest lap collector", "Most fastest laps"),
    "s_laps_led": ("Pace", "Most laps led", "Season laps in the lead"),
    "s_top_speed": ("Pace", "Top speed record", "Highest speed of the season"),
    "s_metronome": ("Consistency", "Metronome", "Lowest average lap-time spread"),
    "s_track_limits": ("Consistency", "Track limits", "Most invalidated laps"),
    "s_dnfs": ("Hard luck", "Hard luck", "Most races not finished"),
    "s_conceded": ("Hard luck", "Revolving door", "Most passes conceded"),
}

GROUP_ORDER = ["Battles", "Overtaking", "Positions", "Start", "Results", "Rivalries", "Pace", "Consistency",
               "Strategy", "Hard luck"]


# which race-review page each award belongs on; anything not listed (the race story: results, positions,
# retirements) stays on the race report
PAGE = {
    "fastest_car": "cars", "top_speed": "cars",
    "brake_metronome": "style", "track_usage": "style", "smooth_power": "style", "wheel_to_wheel": "style", "apex_hunter": "style",
    "battle_of_race": "overtakes", "swap_fest": "overtakes", "friend_rivalry": "overtakes", "the_wall": "overtakes", "most_passes": "overtakes",
    "net_passing": "overtakes", "human_hunter": "overtakes", "corner_specialist": "overtakes", "hotspot": "overtakes", "clean_operator": "overtakes",
    "clinical": "overtakes", "immovable": "overtakes", "opportunist": "overtakes", "revolving_door": "overtakes", "lap1_hero": "overtakes",
    "holeshot": "overtakes", "lap1_nightmare": "overtakes",
    "fastest_lap": "pace", "race_pace": "pace", "fastest_vs_ai": "pace", "ultimate_lap": "pace", "sector_kings": "pace", "final_lap_flyer": "pace",
    "got_faster": "pace", "metronome": "pace", "fastest_stop": "pace", "strong_finish": "pace", "traffic_tamer": "pace",
    "clean_sheet": "errors", "track_limits": "errors", "spin_cost": "errors", "contact": "errors", "error_free": "errors", "spin_doctor": "errors",
    "late_braker": "errors", "scenic_route": "errors", "costliest_moment": "errors",
}


def _award(catalog, aid, winner, value, detail, score, human=False, t=None, winners=None):
    group, title, _ = catalog[aid]
    return {"id": aid, "group": group, "title": title, "page": PAGE.get(aid, "report"), "winner": winner, "winners": winners or ([winner] if winner else []),
            "value": value, "detail": detail, "score": round(float(score), 2), "human": bool(human),
            "t": None if t is None or (isinstance(t, float) and math.isnan(t)) else float(t)}


def rank(awards: list[dict], pinned: list[str] | None = None) -> list[dict]:
    pinned = pinned or []
    order = {a: i for i, a in enumerate(pinned)}
    for a in awards:
        a["pinned"] = a["id"] in order
        a["rank_score"] = a["score"] + (3.0 if a["human"] else 0.0)
    return sorted(awards, key=lambda a: (0 if a["pinned"] else 1, order.get(a["id"], 0), -a["rank_score"]))


def _ord(n) -> str:
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _pl(n, w) -> str:
    n = int(n)
    if n == 1:
        return f"{n} {w}"
    return f"{n} {w}es" if w.endswith(("s", "sh", "ch", "x")) else f"{n} {w}s"


def _join(names) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _fmt_lap(x) -> str:
    m, sec = divmod(float(x), 60)
    return f"{int(m)}:{sec:06.3f}" if m else f"{sec:.3f}"


def _gap(g) -> str:
    return "side by side" if g < 0.05 else f"{g:.2f}s"


def _avg_gap(g) -> str:
    return "side by side almost the whole way" if g < 0.1 else f"{g:.2f}s apart on average"


# --------------------------------------------------------------------------- race
def race_awards(ra: RaceAnalysis, pinned: list[str] | None = None) -> list[dict]:
    C = RACE_CATALOG
    st = ra.stats.set_index("name")
    cls = ra.classification
    laps, passes, battles, pits = ra.laps, ra.passes, ra.battles, ra.pits
    counted = passes[passes.kind.isin(COUNTED)]
    is_h = {n: not bool(st.loc[n, "is_ai"]) for n in st.index}
    classified = st[st.status.isin(["finished", "running"])]
    n_laps = int(cls.laps.max()) if len(cls) else 0
    out = []

    def best(df, col, asc=False, min_val=None):
        d = df.dropna(subset=[col])
        if min_val is not None:
            d = d[(d[col] >= min_val) if not asc else (d[col] <= min_val)]
        if not len(d):
            return None
        d = d.sort_values(col, ascending=asc)
        return d.index[0], d.iloc[0]

    # ---- battles
    if len(battles):
        b = battles.sort_values("duration_s", ascending=False).iloc[0]
        loser = b.b if b.winner == b.a else b.a
        verb = "held off" if b.winner == b.a else "got past"
        out.append(_award(C, "battle_of_race", b.winner, f"{b.laps:.1f} laps",
                          f"{b.winner} {verb} {loser} over {b.laps:.1f} laps (laps {b.start_lap}-{b.end_lap}), " + _avg_gap(getattr(b, "avg_gap_s", b.min_gap_s)) + ".",
                          8 + min(b.laps, 6) * 0.3 + b.swaps * 0.5, is_h.get(b.winner) or is_h.get(loser), b.start_t,
                          winners=[b.winner, loser]))
        sw = battles.sort_values(["swaps", "duration_s"], ascending=False).iloc[0]
        if sw.swaps >= 2:
            out.append(_award(C, "swap_fest", sw.winner, f"{sw.swaps} swaps",
                              f"{sw.a} and {sw.b} swapped places {sw.swaps} times on laps {sw.start_lap}-{sw.end_lap}; {sw.winner} came out ahead.",
                              7 + sw.swaps, is_h.get(sw.a) or is_h.get(sw.b), sw.start_t, winners=[sw.a, sw.b]))
        defended = battles[battles.winner == battles.a].groupby("a").size()
        if len(defended):
            who = defended.idxmax()
            out.append(_award(C, "the_wall", who, _pl(defended.max(), "battle"),
                              f"{who} defended {_pl(defended.max(), 'battle')} without losing the place.",
                              5 + defended.max(), is_h.get(who)))
    fin = cls[(cls.status == "finished")].sort_values("pos")
    if len(fin) >= 2:
        gaps = []
        for a, b in zip(fin.itertuples(), list(fin.itertuples())[1:]):
            if a.laps == b.laps and pd.notna(a.total_time) and pd.notna(b.total_time):
                gaps.append((b.total_time - a.total_time, a, b))
        if gaps:
            g, a, b = min(gaps, key=lambda x: x[0])
            t_flag = laps[(laps.name == b.name) & (laps.lap == b.laps)].t_end
            out.append(_award(C, "closest_finish", a.name, f"{g:.3f}s",
                              f"{a.name} held P{a.pos} from {b.name} by {g:.3f}s at the flag.",
                              6 + max(0.0, 3 - g * 3), is_h.get(a.name) or is_h.get(b.name),
                              (float(t_flag.iat[0]) - 8) if len(t_flag) else None, winners=[a.name, b.name]))
        w, r2 = fin.iloc[0], fin.iloc[1]
        if w.laps == r2.laps and pd.notna(r2.gap):
            out.append(_award(C, "winning_margin", w["name"], f"{r2.gap:.3f}s",
                              f"{w['name']} beat {r2['name']} by {r2.gap:.3f}s.", 4 + (3 if r2.gap < 1 else 0),
                              is_h.get(w["name"])))
    hum_passes = counted[counted.passer.map(is_h).fillna(False) & counted.passed.map(is_h).fillna(False)]
    if len(hum_passes):
        pairs = hum_passes.apply(lambda r: tuple(sorted([r.passer, r.passed])), axis=1).value_counts()
        (a, b), n = pairs.index[0], int(pairs.iat[0])
        if n >= 2:
            ab = int(((hum_passes.passer == a) & (hum_passes.passed == b)).sum())
            out.append(_award(C, "friend_rivalry", None, f"{n} passes",
                              f"{a} and {b} passed each other {n} times ({a} {ab}, {b} {n - ab}).", 7 + n * 0.5, True,
                              winners=[a, b]))

    # ---- overtaking
    r = best(st, "passes_made", min_val=1)
    if r:
        n, s = r
        out.append(_award(C, "most_passes", n, str(int(s.passes_made)),
                          f"{n} made {_pl(s.passes_made, 'pass')} ({int(s.passes_clean)} clean, {int(s.passes_gifted)} gifted).",
                          6 + s.passes_made * 0.25, is_h[n]))
    net = (st.passes_made - st.passed_by)
    if len(net) and net.max() > 0:
        n = net.idxmax()
        out.append(_award(C, "net_passing", n, f"+{int(net.max())}",
                          f"{n} made {int(st.loc[n, 'passes_made'])} passes and conceded {int(st.loc[n, 'passed_by'])}.",
                          5 + net.max() * 0.2, is_h[n]))
    r = best(st[~st.is_ai], "passes_on_humans", min_val=1)
    if r:
        n, s = r
        out.append(_award(C, "human_hunter", n, str(int(s.passes_on_humans)),
                          f"{n} passed another human {_pl(s.passes_on_humans, 'time')}.", 6 + s.passes_on_humans * 0.5, True))
    if len(counted) and counted.corner.notna().any():
        byc = counted.groupby(["passer", "corner"]).size().sort_values(ascending=False)
        (n, c), k = byc.index[0], int(byc.iat[0])
        if k >= 2:
            out.append(_award(C, "corner_specialist", n, f"{k} at {c}", f"{n} made {k} of their passes into {c}.",
                              5 + k * 0.5, is_h.get(n)))
        hc = counted.corner.value_counts()
        out.append(_award(C, "hotspot", None, f"{hc.index[0]}",
                          f"{hc.iat[0]} of the race's {len(counted)} passes happened at {hc.index[0]}.", 5 + hc.iat[0] / max(len(counted), 1) * 4))
    clean_ops = st[(st.passes_made >= 3) & (st.passes_gifted == 0) & (st.passes_contact == 0)]
    if len(clean_ops):
        n = clean_ops.passes_made.idxmax()
        out.append(_award(C, "clean_operator", n, f"{int(clean_ops.loc[n, 'passes_made'])} clean",
                          f"All {int(clean_ops.loc[n, 'passes_made'])} of {n}'s passes were clean.", 4, is_h[n]))

    # ---- positions
    r = best(classified, "positions_gained", min_val=1)
    if r:
        n, s = r
        out.append(_award(C, "biggest_climber", n, f"+{int(s.positions_gained)}",
                          f"{n} started {_ord(s.grid)} and finished {_ord(s.finish)}.", 6 + s.positions_gained * 0.4, is_h[n]))
    r = best(classified, "recovery", min_val=3)
    if r:
        n, s = r
        out.append(_award(C, "comeback", n, f"P{int(s.lowest_pos)} to P{int(s.finish)}",
                          f"{n} dropped to {_ord(s.lowest_pos)} and fought back to {_ord(s.finish)}.", 6 + s.recovery * 0.4, is_h[n]))
    if n_laps >= 3:
        cut = int(math.floor(n_laps * 2 / 3))
        at_cut = laps[laps.lap == cut].set_index("name").position
        late = {n: at_cut[n] - st.loc[n, "finish"] for n in classified.index if n in at_cut.index and pd.notna(at_cut[n])}
        if late and max(late.values()) >= 2:
            n = max(late, key=late.get)
            out.append(_award(C, "late_charge", n, f"+{int(late[n])}",
                              f"{n} gained {int(late[n])} places after lap {cut}.", 6 + late[n] * 0.5, is_h[n],
                              float(laps[(laps.name == n) & (laps.lap == cut)].t_end.iat[0])))
    if len(fin):
        w = fin.iloc[0]
        ws = st.loc[w["name"]]
        if pd.notna(w.grid) and w.grid >= 4:
            out.append(_award(C, "won_from", w["name"], f"P{int(w.grid)}", f"{w['name']} won from {_ord(w.grid)} on the grid.",
                              7 + w.grid * 0.3, is_h[w["name"]]))
        if w.grid == 1 and ws.laps_led == w.laps:
            out.append(_award(C, "lights_to_flag", w["name"], "Every lap", f"{w['name']} took pole and led every lap.", 6, is_h[w["name"]]))
    leaders = laps[laps.position == 1].sort_values("lap").drop_duplicates("lap")
    if len(leaders):
        seq = leaders.name.tolist()
        changes = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        names = list(dict.fromkeys(seq))
        out.append(_award(C, "lead_changes", None, str(changes),
                          f"The lead changed hands {_pl(changes, 'time')}" + (f" between {', '.join(names)}." if len(names) > 1 else f"; {names[0]} led throughout."),
                          3 + changes * 1.2))
        r = best(st, "laps_led", min_val=1)
        if r:
            n, s = r
            out.append(_award(C, "most_laps_led", n, _pl(s.laps_led, "lap"), f"{n} led {_pl(s.laps_led, 'lap')} of {n_laps}.",
                              4 + s.laps_led / max(n_laps, 1) * 2, is_h[n]))

    # ---- start
    r = best(st, "lap1_gain", min_val=1)
    if r:
        n, s = r
        out.append(_award(C, "lap1_hero", n, f"+{int(s.lap1_gain)}", f"{n} went from {_ord(s.grid)} to {_ord(s.lap1_pos)} on lap 1.",
                          6 + s.lap1_gain * 0.5, is_h[n], ra.session.green_t))
    l1 = st[(st.lap1_pos == 1) & (st.grid > 1)]
    if len(l1):
        n = l1.index[0]
        out.append(_award(C, "holeshot", n, f"from P{int(l1.loc[n, 'grid'])}",
                          f"{n} led at the end of lap 1 from {_ord(l1.loc[n, 'grid'])} on the grid.", 7, is_h[n], ra.session.green_t))
    r = best(st, "lap1_gain", asc=True, min_val=-2)
    if r:
        n, s = r
        out.append(_award(C, "lap1_nightmare", n, f"{int(s.lap1_gain)}", f"{n} lost {int(-s.lap1_gain)} places on lap 1.",
                          4 - s.lap1_gain * 0.4, is_h[n], ra.session.green_t))

    # ---- pace
    valid = laps[laps.valid & (laps.time > 0)]
    if len(valid):
        fl = valid.sort_values("time").iloc[0]
        out.append(_award(C, "fastest_lap", fl["name"], fmt_time(fl.time), f"{fl['name']} set the fastest lap, {fmt_time(fl.time)} on lap {int(fl.lap)}.",
                          5, is_h.get(fl["name"]), float(fl.t_end - fl.time)))
        sk = []
        for c in ("s1", "s2", "s3"):
            v = valid.dropna(subset=[c])
            if len(v):
                row = v.sort_values(c).iloc[0]
                sk.append((c.upper(), row["name"], row[c]))
        if len(sk) == 3:
            names = [x[1] for x in sk]
            out.append(_award(C, "sector_kings", max(set(names), key=names.count) if len(set(names)) < 3 else None,
                              " / ".join(x[1].split()[0] for x in sk),
                              "; ".join(f"{s} {n} ({v:.3f})" for s, n, v in sk) + ".", 3 + (2 if len(set(names)) == 1 else 0),
                              any(is_h.get(n) for n in names), winners=list(dict.fromkeys(names))))
    r = best(st[st.clean_laps >= 3], "median_clean", asc=True)
    if r:
        n, s = r
        out.append(_award(C, "race_pace", n, fmt_time(s.median_clean), f"{n}'s typical clean lap was {fmt_time(s.median_clean)}.", 5, is_h[n]))
    r = best(st[~st.is_ai], "ai_rel_pace", asc=True)
    if r:
        n, s = r
        pct = (1 - s.ai_rel_pace) * 100
        out.append(_award(C, "fastest_vs_ai", n, f"{s.ai_rel_pace:.3f}x",
                          f"{n} lapped {abs(pct):.1f}% {'quicker' if pct >= 0 else 'slower'} than the AI's median.", 5, True))
    r = best(st, "theoretical_best", asc=True)
    if r:
        n, s = r
        gain = s.best_lap - s.theoretical_best if pd.notna(s.best_lap) else None
        out.append(_award(C, "ultimate_lap", n, fmt_time(s.theoretical_best),
                          f"{n}'s best sectors add up to {fmt_time(s.theoretical_best)}" + (f", {gain:.3f}s under their best lap." if gain else "."),
                          3, is_h[n]))
    last = []
    for n in fin["name"] if len(fin) else []:
        el = laps[(laps.name == n) & laps.valid]
        if len(el) and el.lap.max() == st.loc[n, "laps"]:
            last.append((el.sort_values("lap").iloc[-1].time, n))
    if last:
        v, n = min(last)
        out.append(_award(C, "final_lap_flyer", n, fmt_time(v), f"{n} was quickest on the final lap, {fmt_time(v)}.", 3, is_h[n]))
    imp = {}
    for n, g in laps[laps.clean].groupby("name"):
        if len(g) >= 4:
            half = len(g) // 2
            imp[n] = g.time.iloc[:half].median() - g.time.iloc[half:].median()
    if imp and max(imp.values()) > 0.15:
        n = max(imp, key=imp.get)
        out.append(_award(C, "got_faster", n, f"-{imp[n]:.2f}s", f"{n}'s laps got {imp[n]:.2f}s quicker in the second half.", 3, is_h[n]))
    r = best(st, "top_speed_kph")
    if r:
        n, s = r
        out.append(_award(C, "top_speed", n, f"{s.top_speed_kph:.0f} km/h", f"{n} hit {s.top_speed_kph:.0f} km/h.", 2, is_h[n]))

    # ---- consistency
    r = best(st[st.clean_laps >= 3], "consistency_s", asc=True)
    if r:
        n, s = r
        out.append(_award(C, "metronome", n, f"{s.consistency_s:.3f}s", f"{n}'s clean laps varied by just {s.consistency_s:.3f}s.", 5, is_h[n]))
    cs = st[(st.status == "finished") & (st.invalid_laps == 0)]
    if 0 < len(cs) <= max(3, len(st) // 3):
        names = list(cs.index)
        out.append(_award(C, "clean_sheet", names[0] if len(names) == 1 else None, _pl(len(names), "driver"),
                          f"{', '.join(names)} finished without an invalidated lap.", 3, any(is_h[n] for n in names), winners=names))
    r = best(st, "invalid_laps", min_val=2)
    if r:
        n, s = r
        out.append(_award(C, "track_limits", n, str(int(s.invalid_laps)), f"{n} had {_pl(s.invalid_laps, 'lap')} invalidated.", 3 + s.invalid_laps * 0.3, is_h[n]))

    # ---- strategy
    stops = pits[pits.kind == "stop"]
    if len(stops):
        p = stops.sort_values("lane_time").iloc[0]
        out.append(_award(C, "fastest_stop", p["name"], f"{p.lane_time:.1f}s",
                          f"{p['name']} got through the pit lane in {p.lane_time:.1f}s ({p.stationary_time:.1f}s stationary) on lap {int(p.lap)}.",
                          4, is_h.get(p["name"]), p.entry_t))

    # ---- hard luck
    gifted = passes[passes.kind == "gifted"].sort_values("t")
    worst = None
    for n, g in gifted.groupby("passed"):
        ts = g.t.to_numpy()
        for i in range(len(ts)):
            k = int(((ts >= ts[i]) & (ts <= ts[i] + 15)).sum())
            if worst is None or k > worst[0]:
                worst = (k, n, ts[i], g.iloc[i])
    if worst and worst[0] >= 2:
        k, n, t, row = worst
        out.append(_award(C, "spin_cost", n, f"-{k}", f"{n} lost {k} places in one moment on lap {int(row.lap)}" + (f" at {row.corner}." if row.corner else "."),
                          6 + k * 0.5, is_h.get(n), t - 5))
    r = best(classified, "positions_gained", asc=True, min_val=-2)
    if r:
        n, s = r
        out.append(_award(C, "biggest_faller", n, f"{int(s.positions_gained)}", f"{n} started {_ord(s.grid)} but finished {_ord(s.finish)}.",
                          3 - s.positions_gained * 0.3, is_h[n]))
    r = best(st, "passed_by", min_val=3)
    if r:
        n, s = r
        out.append(_award(C, "revolving_door", n, str(int(s.passed_by)), f"{_pl(s.passed_by, 'car')} went past {n}.", 3, is_h[n]))
    out_cars = cls[cls.status.isin(["dnf", "disconnected", "dsq"])]
    if len(out_cars):
        parts = [f"{r['name']} ({'left' if r.status == 'disconnected' else 'retired' if r.status == 'dnf' else 'disqualified'} after {_pl(r.laps, 'lap')})"
                 for _, r in out_cars.iterrows()]
        out.append(_award(C, "retirements", None, str(len(out_cars)), "; ".join(parts) + ".", 3 + 2 * any(is_h.get(n) for n in out_cars.name),
                          any(is_h.get(n) for n in out_cars.name), winners=list(out_cars.name)))
    r = best(st, "contacts", min_val=1)
    if r:
        n, s = r
        out.append(_award(C, "contact", n, str(int(s.contacts)), f"{n} was involved in {_pl(s.contacts, 'contact')}.", 3, is_h[n]))

    # ---- driving style and cars
    if "brake_consistency" in st.columns:
        b = best(st, "brake_consistency")
        if b and b[1].brake_consistency >= 60:
            who, r = b
            out.append(_award(C, "brake_metronome", who, f"{int(r.brake_consistency)}/100",
                              f"{who} hit the same braking points lap after lap: typically within \u00b1{r.brake_point_sd:.1f} m at each corner.",
                              4 + (r.brake_consistency - 60) / 8, is_h.get(who)))
    if "track_usage" in st.columns:
        u = best(st, "track_usage")
        if u and u[1].track_usage >= 50:
            who, r = u
            apex = ("" if r.apex_gap_m != r.apex_gap_m else ", right on the inside edge at the apex" if r.apex_gap_m < 0.05 else f", typically {r.apex_gap_m:.2f} m from the inside edge at the apex")
            out.append(_award(C, "track_usage", who, f"{int(r.track_usage)}/100", f"{who} used the most of the road{apex}.",
                              4 + (r.track_usage - 50) / 10, is_h.get(who)))
    try:
        from .metrics import car_stats
        cars = [c for c in car_stats(ra.stats, ra.entrants, getattr(ra, "corner_speeds", None)) if c["pace"]]
    except Exception:
        cars = []
    if len(cars) >= 2:
        c0, c1 = cars[0], cars[1]
        out.append(_award(C, "fastest_car", None, c0["car"],
                          f"The {c0['car']} was the quickest car: its drivers' clean laps averaged {_fmt_lap(c0['pace'])}, "
                          f"{abs(c0['pace_vs_field']):.2f}% {'quicker' if c0['pace_vs_field'] < 0 else 'slower'} than the field and "
                          f"{c1['pace'] - c0['pace']:.3f}s a lap ahead of the {c1['car']}.", 3.5, False))
    out += _newer_awards(ra, st)
    return rank(out, pinned)


def _newer_awards(ra, st) -> list[dict]:
    """Awards from the errors, overtaking, race pace and driving style analyses. Each needs enough evidence to
    mean something; anything that can't be worked out for this race is simply left out."""
    C, out = RACE_CATALOG, []
    hum = lambda n: n in st.index and not bool(st.loc[n, "is_ai"])
    num = lambda v: v is not None and v == v
    er = {"errors": [], "drivers": []}
    try:
        from .errors import race_errors
        er = race_errors(ra)
        ds = [d for d in er["drivers"] if d["laps"] >= 3 and num(d["clean_lap_share"])]
        if ds:
            b = max(ds, key=lambda d: (d["clean_lap_share"], -d["errors"], d["laps"]))
            if b["clean_lap_share"] >= 80:
                out.append(_award(C, "error_free", b["name"], f"{b['clean_lap_share']}%", f"{b['name']} drove {b['clean_lap_share']}% of their laps without a mistake that cost time.",
                                  3 + b["clean_lap_share"] / 50, hum(b["name"])))
        for aid, field, what in (("spin_doctor", "spin", "spun"), ("late_braker", "braked_too_late", "overshot a corner braking too late"), ("scenic_route", "off_track", "went off")):
            cand = [d for d in er["drivers"] if d.get(field)]
            if cand:
                b = max(cand, key=lambda d: d[field])
                if b[field] >= (1 if aid == "spin_doctor" else 2):
                    out.append(_award(C, aid, b["name"], b[field], f"{b['name']} {what} {_pl(b[field], 'time')}.", 2 + b[field], hum(b["name"])))
        worst = max(er["errors"], key=lambda e: (e["positions"], e["loss"]), default=None)
        worst = max((e for e in er["errors"] if e["kind"] not in ("spin", "off track")), key=lambda e: (e["positions"], e["loss"]), default=None)
        if worst and (worst["positions"] >= 2 or worst["loss"] >= 3):   # spins and offs: "Costliest moment" already covers them
            out.append(_award(C, "costliest_moment", worst["name"], _pl(worst["positions"], "place") if worst["positions"] else f"{worst['loss']:.1f} s",
                              f"{worst['name']}'s {worst['kind']} at {worst['corner']} on lap {worst['lap']} cost {worst['loss']:.1f} s"
                              + (f" and {_pl(worst['positions'], 'place')}" if worst["positions"] else "") + ".", 3 + worst["positions"], hum(worst["name"]), t=worst["t"]))
    except Exception:
        pass
    try:
        from .overtakes import overtaking
        ov = overtaking(ra)["drivers"]
        att = [d for d in ov if d["attack_laps"] >= 4 and num(d["pass_rate"]) and d["pass_rate"] > 0]
        if att:
            b = max(att, key=lambda d: (d["pass_rate"], d["made"]))
            out.append(_award(C, "clinical", b["name"], f"{b['pass_rate']}%", f"{b['pass_rate']}% of {b['name']}'s {b['attack_laps']} laps spent attacking ended in a pass.", 3 + b["pass_rate"] / 40, hum(b["name"])))
        dfd = [d for d in ov if d["defend_laps"] >= 4 and num(d["hold_rate"])]
        if dfd:
            b = max(dfd, key=lambda d: (d["hold_rate"], d["defend_laps"]))
            out.append(_award(C, "immovable", b["name"], f"{b['hold_rate']}%", f"{b['name']} kept the place on {b['hold_rate']}% of {b['defend_laps']} laps under pressure.", 3 + b["hold_rate"] / 40, hum(b["name"])))
        g = max(ov, key=lambda d: d["gifted_gained"], default=None)
        if g and g["gifted_gained"] >= 2:
            out.append(_award(C, "opportunist", g["name"], g["gifted_gained"], f"{g['name']} picked up {_pl(g['gifted_gained'], 'place')} when someone ahead spun or went off.", 2 + g["gifted_gained"], hum(g["name"])))
    except Exception:
        pass
    try:
        from .metrics import race_pace
        rp = race_pace(ra.laps, {n: bool(st.loc[n, "is_ai"]) for n in st.index})["drivers"]
        mistakes = set()
        try:   # a slow lap from a spin or an off would make the rest look like "getting quicker": leave those drivers out
            mistakes = {e["name"] for e in er["errors"]}
        except Exception:
            pass
        tr = [d for d in rp if num(d.get("trend")) and len(d.get("laps") or []) >= 6 and d["name"] not in mistakes]
        if tr:
            b = min(tr, key=lambda d: d["trend"])
            if b["trend"] < -0.02:
                out.append(_award(C, "strong_finish", b["name"], f"{-b['trend']:.2f} s/lap", f"{b['name']} got {-b['trend']:.2f} s a lap quicker as the race went on.", 3 + min(3, -b["trend"] * 10), hum(b["name"])))
        tc = [d for d in rp if num(d.get("traffic_cost")) and sum(1 for x in (d.get("laps") or []) if isinstance(x, dict) and x.get("air") == "traffic") >= 3]
        if tc:
            b = min(tc, key=lambda d: d["traffic_cost"])
            out.append(_award(C, "traffic_tamer", b["name"], f"{max(0, b['traffic_cost']):.2f} s/lap", f"Stuck behind other cars, {b['name']} lost only {max(0, b['traffic_cost']):.2f} s a lap.", 3, hum(b["name"])))
    except Exception:
        pass
    for aid, col, best_high, fmt, say in (("smooth_power", "throttle_consistency", True, "{:.0f}/100", "picked up the throttle at the same point lap after lap ({})"),
                                          ("wheel_to_wheel", "racing_share", True, "{:.0f}%", "spent {} of their corners racing another car"),
                                          ("apex_hunter", "apex_gap_m", False, "{:.2f} m", "ran a median {} from the apex")):
        if col in st.columns:
            vals = st[col].dropna()
            if aid == "wheel_to_wheel":
                vals = vals[vals >= 30]
            if len(vals):
                n = vals.idxmax() if best_high else vals.idxmin()
                v = float(vals.loc[n])
                shown = "right on the apex" if aid == "apex_hunter" and v < 0.05 else fmt.format(v)
                text = f"{n} ran right on the apex, corner after corner." if shown == "right on the apex" else f"{n} " + say.format(shown) + "."
                out.append(_award(C, aid, n, shown, text, 2.5, hum(n)))
    return out


# --------------------------------------------------------------------------- season
def season_awards(con, cfg, pinned: list[str] | None = None) -> list[dict]:
    from .season import _stats_frame, classified_races, head_to_head
    C = SEASON_CATALOG
    races = classified_races(con, cfg)
    if races.empty:
        return []
    df = _stats_frame(races)
    hum = df[~df.is_ai & df.driver.notna()].copy()
    if hum.empty:
        return []
    hum["classified"] = hum.status.isin(["finished", "running"])
    fastest = df[df.best_lap.notna()].groupby(["round", "race_no"]).best_lap.transform("min")
    df["fastest_lap"] = df.best_lap.eq(fastest.reindex(df.index))
    hum["fastest_lap"] = df.loc[hum.index, "fastest_lap"]
    g = hum.groupby("display")
    n_rounds = races.groupby(["round", "race_no"]).ngroups
    out = []

    def top(series, aid, fmt, detail, score, asc=False, min_val=None, mask=None):
        """detail: callable(who, v) -> sentence for a single winner."""
        s = series.dropna()
        if mask is not None:
            s = s[mask.reindex(s.index).fillna(False).astype(bool)]
        if min_val is not None:
            s = s[s >= min_val] if not asc else s[s <= min_val]
        if not len(s):
            return
        s = s.sort_values(ascending=asc)
        who, v = s.index[0], s.iat[0]
        tied = list(s[np.isclose(s.astype(float), float(v))].index)
        if len(tied) > 1:
            out.append(_award(C, aid, None, fmt.format(v), f"{_join(tied)} are tied on {fmt.format(v)}.", score - 0.5, True,
                              winners=tied))
        else:
            out.append(_award(C, aid, who, fmt.format(v), detail(who, v), score, True))

    races_n = g.size()
    enough = races_n >= max(2, math.ceil(n_rounds / 2))
    top(g.apply(lambda x: (x.finish == 1).sum()), "s_wins", "{:.0f}", lambda w, v: f"{w} won {_pl(v, 'race')} outright.", 7, min_val=1)
    top(g.apply(lambda x: (x.finish <= 3).sum()), "s_podiums", "{:.0f}", lambda w, v: f"{w} finished on the overall podium {_pl(v, 'time')}.", 5, min_val=1)
    top(g.field_pct.mean(), "s_field_pct", "{:.0%}", lambda w, v: f"{w} beat {v:.0%} of the grid on average.", 6, mask=enough)
    top(g.apply(lambda x: x[x.classified].finish.std()), "s_steady", "±{:.1f}", lambda w, v: f"{w}'s finishing positions varied by only ±{v:.1f} places.", 4, asc=True, mask=enough)
    dnf_free = g.apply(lambda x: len(x) if x.classified.all() else 0)
    top(dnf_free, "s_iron_man", "{:.0f} races", lambda w, v: f"{w} finished all {_pl(v, 'race')} they started.", 4, min_val=max(2, n_rounds))
    if n_rounds >= 3:
        slopes = {}
        for who, x in g:
            x = x[x.classified].sort_values(["round", "race_no"])
            if len(x) >= 3:
                slopes[who] = np.polyfit(np.arange(len(x)), x.human_rank.astype(float), 1)[0]
        if slopes and min(slopes.values()) < -0.15:
            who = min(slopes, key=slopes.get)
            out.append(_award(C, "s_improved", who, f"{-slopes[who]:.2f}/race",
                              f"{who} has climbed about {-slopes[who]:.1f} places among the humans per race.", 6, True))
    ahead, pm = head_to_head(con, cfg)
    if len(ahead) > 1:
        wins = ahead.sum(axis=1)
        tot = ahead + ahead.T
        rate = wins / tot.sum(axis=1).replace(0, np.nan)
        top(rate, "s_h2h_king", "{:.0%}", lambda w, v: f"{w} finished ahead of another human in {v:.0%} of head-to-heads.", 7)
        t = pm + pm.T
        tri = np.triu(t.values, 1)
        if tri.max() >= 2:
            a, b = np.unravel_index(np.argmax(tri), tri.shape)
            A, B = t.index[a], t.columns[b]
            out.append(_award(C, "s_rivalry", None, f"{int(tri[a, b])} passes",
                              f"{A} and {B} have passed each other {int(tri[a, b])} times ({A} {pm.loc[A, B]}, {B} {pm.loc[B, A]}).",
                              8, True, winners=[A, B]))
    top(g.passes_on_humans.sum(), "s_human_hunter", "{:.0f}", lambda w, v: f"{w} passed another human {_pl(v, 'time')}.", 6, min_val=1)
    top(g.passes_made.sum(), "s_passes", "{:.0f}", lambda w, v: f"{w} made {_pl(v, 'pass')} this season.", 6, min_val=1)
    top(g.passes_made.sum() - g.passed_by.sum(), "s_net_passes", "{:+.0f}", lambda w, v: f"{w} is {v:+.0f} on passes made versus conceded.", 5, min_val=1)
    top(g.positions_gained.sum(), "s_places", "{:+.0f}", lambda w, v: f"{w} has gained {v:+.0f} places from the grid in total.", 5, min_val=1)
    top(g.recovery.sum(), "s_comeback", "{:.0f}", lambda w, v: f"{w} has clawed back {_pl(v, 'place')} from their low points.", 5, min_val=3)
    top(g.lap1_gain.mean(), "s_lap1", "{:+.1f}", lambda w, v: f"{w} gains {v:+.1f} places on lap 1 on average.", 5, min_val=0.5, mask=enough)
    bt = g.battles.sum()
    rate_b = (g.battles_won.sum() / bt).where(bt >= 3)
    top(rate_b, "s_battles", "{:.0%}", lambda w, v: f"{w} came out ahead in {v:.0%} of their battles.", 5)
    q = """SELECT d.display, COUNT(*) AS n FROM battle b JOIN entrant e ON e.id=b.a_id JOIN driver d ON d.id=e.driver_id
           WHERE b.winner_id=b.a_id GROUP BY d.display"""
    walls = pd.Series({r["display"]: r["n"] for r in con.execute(q)}, dtype=float)
    top(walls, "s_wall", "{:.0f}", lambda w, v: f"{w} defended {_pl(v, 'battle')} without losing the place.", 5, min_val=2)
    hs = con.execute("""SELECT ev.track, p.corner, COUNT(*) AS n FROM pass p JOIN session s ON s.id=p.session_id
                        JOIN event ev ON ev.id=s.event_id WHERE p.kind IN ('clean','gifted','contact') AND p.corner IS NOT NULL
                        GROUP BY 1, 2 ORDER BY n DESC LIMIT 1""").fetchone()
    if hs:
        out.append(_award(C, "s_hotspot", None, f"{hs['corner']}, {hs['track']}",
                          f"{hs['n']} passes have happened at {hs['corner']} at {hs['track']}.", 4))
    top(g.ai_rel_pace.mean(), "s_pace", "{:.3f}x", lambda w, v: f"{w} averages {v:.3f}x the AI's median lap ({abs(1 - v) * 100:.1f}% {'quicker' if v < 1 else 'slower'}).", 5, asc=True, mask=enough)
    top(g.fastest_lap.sum(), "s_fastest_laps", "{:.0f}", lambda w, v: f"{w} has set the fastest lap {_pl(v, 'time')}.", 5, min_val=1)
    top(g.laps_led.sum(), "s_laps_led", "{:.0f}", lambda w, v: f"{w} has led {_pl(v, 'lap')}.", 5, min_val=1)
    top(g.top_speed_kph.max(), "s_top_speed", "{:.0f} km/h", lambda w, v: f"{w} holds the season top speed, {v:.0f} km/h.", 2)
    top(g.consistency_s.mean(), "s_metronome", "{:.3f}s", lambda w, v: f"{w}'s clean laps vary by {v:.3f}s on average.", 4, asc=True, mask=enough)
    top(g.invalid_laps.sum(), "s_track_limits", "{:.0f}", lambda w, v: f"{w} has had {_pl(v, 'lap')} invalidated.", 3, min_val=2)
    top(g.apply(lambda x: (~x.classified).sum()), "s_dnfs", "{:.0f}", lambda w, v: f"{w} has failed to finish {_pl(v, 'race')}.", 3, min_val=1)
    top(g.passed_by.sum(), "s_conceded", "{:.0f}", lambda w, v: f"{_pl(v, 'car')} have gone past {w} this season.", 2, min_val=3)
    return rank(out, pinned)
