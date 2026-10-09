"""One call per race: `analyze_race(session_dir, humans)` -> RaceAnalysis with every table and
per-entrant stat the season layer needs."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import shm as S
from .derive import (Session, add_distance, all_laps, classify, curvature_profile, detect_corners, effective_track_length,
                     load_session, pit_stops, reference_lap_xy, speed_profile)
from .passes import PassParams, build_grid, detect_battles, detect_passes

COUNTED = ("clean", "gifted", "contact")  # pass kinds that count as passes


@dataclass
class RaceAnalysis:
    session: Session
    entrants: pd.DataFrame
    classification: pd.DataFrame
    laps: pd.DataFrame
    passes: pd.DataFrame
    battles: pd.DataFrame
    pits: pd.DataFrame
    incidents: pd.DataFrame
    corners: list[dict]
    stats: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    frames: pd.DataFrame | None = None  # raw frames + continuous race distance (for replays)


def _norm(name: str) -> str:
    return " ".join(str(name).lower().split())


def find_ghosts(fr: pd.DataFrame, laps: pd.DataFrame, green_t: float, humans: set[str]) -> dict[str, str]:
    """Entries that aren't real cars: stale duplicate slots, frozen entries, or impossible lap times.
    Humans on the roster are never dropped (their impossible laps are just invalidated)."""
    ghosts = {}
    after = fr[fr.t >= green_t]
    ref = laps[laps.lap > 1].time
    field_med = float(ref.median()) if len(ref) >= 5 else (float(laps.time.median()) if len(laps) else np.nan)
    names = set(after.name.unique())
    for name, g in after.groupby("name"):
        if _norm(name) in humans:
            continue
        spread = float(np.hypot(np.ptp(g.x.to_numpy(float)), np.ptp(g.z.to_numpy(float)))) if len(g) else 0.0
        el = laps[laps.name == name]
        base = re.sub(r" \[[^\]]*\]$", "", name)
        if g.speed.max() < 2 and spread < 30:
            ghosts[name] = "never moved"
        elif len(el) and field_med == field_med and el.time.median() < 0.5 * field_med:
            ghosts[name] = "impossible lap times"
        elif base != name and base in names:
            moved_little = spread < 0.25 * float(np.hypot(np.ptp(fr.x), np.ptp(fr.z)))
            if moved_little or len(el) == 0 or (len(el) and el.time.median() < 0.8 * field_med):
                ghosts[name] = f"duplicate entry of {base}"
    return ghosts


def incidents_from_events(sess: Session) -> pd.DataFrame:
    """Contacts and crash states seen by *this* recorder's car (shared memory only exposes the
    local car's damage). Run the recorder on every friend's PC to cover everyone."""
    local = sess.meta.get("local", {}).get("name", "")
    rows = []
    for ev in sess.events:
        if ev.get("type") == "local_collision":
            rows.append({"t": ev["t"], "name": local, "other": ev.get("other"), "kind": "contact",
                         "magnitude": ev.get("magnitude")})
        elif ev.get("type") == "local_crash_state" and ev.get("value") in (
                S.CRASH_DAMAGE_OFFTRACK, S.CRASH_DAMAGE_SPINNING, S.CRASH_DAMAGE_ROLLING, S.CRASH_DAMAGE_LARGE_PROP):
            kind = {S.CRASH_DAMAGE_OFFTRACK: "off_track", S.CRASH_DAMAGE_SPINNING: "spin",
                    S.CRASH_DAMAGE_ROLLING: "rollover", S.CRASH_DAMAGE_LARGE_PROP: "hit_object"}[ev["value"]]
            rows.append({"t": ev["t"], "name": local, "other": None, "kind": kind, "magnitude": None})
    return pd.DataFrame(rows, columns=["t", "name", "other", "kind", "magnitude"])


NO_RACE = ("This race recording has no racing in it: it ends before or just after the start. "
           "That usually means the session was left before the green flag, so there's nothing to analyse or score.")


def analyze_race(path_or_session, humans: set[str] | None = None,
                 corners_override: list[dict] | None = None,
                 params: PassParams | None = None, racing_mode: str = "reduced") -> RaceAnalysis:
    sess = path_or_session if isinstance(path_or_session, Session) else load_session(path_or_session)
    if sess.type != "race":
        raise ValueError(f"{sess.path.name} is a {sess.type} session; analyze_race needs a race")
    warnings = []
    green_t = sess.green_t
    if green_t is None:
        raise ValueError(NO_RACE)
    after = sess.frames[sess.frames.t > green_t + 1]
    if after.empty or (int(after.laps_completed.max()) < 1 and sess.end_t - green_t < 90):
        raise ValueError(NO_RACE)
    if sess.meta.get("status") != "complete":
        warnings.append("recording did not close cleanly (recorder crash?); using available parts")
    params = params or PassParams()
    hum = {_norm(h) for h in humans} if humans else set()

    L, why = effective_track_length(sess.frames, sess.L)
    if why:
        warnings.append(why)
        sess.meta["track_length"] = L
    fr = add_distance(sess.frames, L, green_t)
    laps = all_laps(fr, L, green_t)
    ghosts = find_ghosts(fr, laps, green_t, hum)
    if ghosts:
        fr = fr[~fr.name.isin(ghosts)].copy()
        sess.frames = sess.frames[~sess.frames.name.isin(ghosts)].copy()
        laps = laps[~laps.name.isin(ghosts)].copy()
        laps["gap_to_leader"] = laps.t_end - laps.groupby("lap").t_end.transform("min")
        warnings.append("ignored " + "; ".join(f"{n} ({why})" for n, why in ghosts.items()))
    if len(laps):  # no lap under half the field's typical lap counts for anything
        ref = laps[laps.lap > 1].time
        floor = 0.5 * float(ref.median() if len(ref) >= 5 else laps.time.median())
        bad = laps.time < floor
        laps.loc[bad, ["valid", "clean"]] = False
    cls = classify(sess, fr, laps)
    if cls is None or cls.empty:
        raise ValueError(NO_RACE)
    pits = pit_stops(fr, L, green_t)
    profile = speed_profile(fr, L)
    ref_xy = reference_lap_xy(fr, laps, green_t)
    kap = curvature_profile(*ref_xy, L) if ref_xy else None
    from .derive import custom_corners
    corners = custom_corners(corners_override, profile, kap) if corners_override else detect_corners(profile, curvature=kap)
    incidents = incidents_from_events(sess)
    contacts = [(r.t, r.name, r.other) for r in incidents.itertuples() if r.kind == "contact"]
    grid = build_grid(fr, green_t, params.grid_dt)
    passes = detect_passes(grid, L, corners, profile, contacts=contacts, p=params)
    battles = detect_battles(grid, L, params)

    entrants = cls[["name", "car", "car_class"]].copy()
    entrants["is_ai"] = ~entrants.name.map(_norm).isin(hum) if humans is not None else False
    ai_names = set(entrants.loc[entrants.is_ai, "name"])

    if (cls.grid.isna()).any():
        late = cls.loc[cls.grid.isna(), "name"].tolist()
        warnings.append(f"no grid slot for {late} (joined after the start?)")
    unconfirmed = int((passes.kind == "unconfirmed").sum())
    if unconfirmed:
        warnings.append(f"{unconfirmed} distance-based order changes disagreed with game positions and were ignored")

    stats = _entrant_stats(cls, laps, passes, battles, pits, incidents, fr, ai_names, green_t,
                           start_grid=_observed_start_grid(sess, fr))
    try:  # driving style for every car: braking/throttle point consistency and track usage
        from .metrics import driving_metrics
        from .trackmap import recording_edge_samples, track_geometry
        edges = None
        if ref_xy is not None:
            normal = {(r.name, int(r.lap) - 1) for r in laps[laps.clean].itertuples()}
            geo = track_geometry(fr, *ref_xy, L, normal=normal, samples=recording_edge_samples(sess), cloud_points=0)
            edges = geo.get("offsets")
            if edges:
                edges = dict(edges, source=geo.get('edges', {}).get('source', 'estimated'))
        from .metrics import strength_columns
        dm, corner_speeds = driving_metrics(fr, laps, corners, L, ref_xy, edges, mode=racing_mode)
        stats = stats.merge(dm, on="name", how="left")
        stats = stats.merge(strength_columns(stats, laps, corner_speeds, corners), on="name", how="left")
    except Exception as exc:  # never let the extra metrics break a race analysis
        warnings.append(f"driving metrics unavailable: {exc}")
    try:
        from .technique import technique_report, throttle_consistency_summary
        pedal_report = technique_report(sess, corners_override, mode=racing_mode)
        driver = pedal_report.get('driver') or (sess.meta.get('local') or {}).get('name')
        channel = throttle_consistency_summary(pedal_report)
        measured = stats.name == driver
        stats['throttle_rating_source'] = 'acceleration'
        if measured.any() and channel.get(racing_mode) is not None:
            stats.loc[measured, 'throttle_consistency'] = channel[racing_mode]
            stats.loc[measured, 'throttle_rating_source'] = 'pedals'
            # Pickup scatter remains a separately named distance measurement;
            # it is not the scale used by the pedal shape rating.
            for mode, score in channel.items():
                stats.loc[measured, f'throttle_consistency_{mode}'] = score
            scatter = [c['scatter_by_mode'][racing_mode]['pickup_sd'] for c in pedal_report.get('corners', [])
                       if c['scatter_by_mode'][racing_mode].get('throttle_marker_laps', 0) >= 2]
            stats.loc[measured, 'throttle_point_sd'] = float(np.median(scatter)) if scatter else np.nan
        elif measured.any() and sess.local is not None and {'throttle', 'brake'} <= set(sess.local):
            stats.loc[measured, 'throttle_rating_source'] = 'unavailable'
            for column in ['throttle_consistency', 'throttle_point_sd'] + [f'throttle_consistency_{m}' for m in ('equal', 'reduced', 'excluded')]:
                stats.loc[measured, column] = np.nan
    except Exception as exc:
        warnings.append(f'pedal throttle rating unavailable: {exc}')
    ra = RaceAnalysis(sess, entrants, cls, laps, passes, battles, pits, incidents, corners, stats, warnings, fr)
    ra.racing_mode = racing_mode
    ra.corner_speeds = locals().get("corner_speeds", pd.DataFrame(columns=["name", "corner", "vmin"]))
    return ra


def _observed_start_grid(sess: Session, fr: pd.DataFrame) -> dict[str, int]:
    """Actual game grid, without treating a mid-race distance order as a start.

    Some AMS2 recordings open on the first racing tick and mark the green event
    late. Accept that grid only if the whole observed field is still stationary
    on lap zero. A genuinely late recording has no trustworthy starting grid.
    """
    green_t = sess.green_t
    if green_t is None:
        return {}
    events = [e for e in sess.events if e.get('type') == 'green']
    event = events[0] if events else None
    if event is not None:
        grid = event.get('grid') or {}
        if event.get('late'):
            near = fr[(fr.t >= green_t) & (fr.t <= green_t + 0.5)]
            first = near.sort_values('t', kind='stable').groupby('name', sort=False).first()
            if (first.empty or 'laps_completed' not in first or 'speed' not in first
                    or not first.laps_completed.eq(0).all()
                    or not first.speed.between(0, 2.5).all()):
                return {}
    else:
        # Legacy sessions may have no event journal. Require real pre-green
        # observations; the sample at inferred green can already be mid-race.
        before = fr[(fr.t < green_t) & (fr.race_pos > 0)]
        if 'race_state' in before:
            before = before[before.race_state == S.RACESTATE_NOT_STARTED]
        if before.empty:
            return {}
        last_t = before.t.max()
        grid = before[before.t >= last_t - 0.5].groupby('name').race_pos.last().to_dict()
    if not isinstance(grid, dict):
        return {}
    out = {}
    for name, position in grid.items():
        if (isinstance(position, bool) or not isinstance(position, (int, float, np.number))
                or not math.isfinite(position) or float(position) != int(position) or position < 1):
            return {}
        out[name] = int(position)
    # Missing or duplicate grid slots make the number of opportunities unknown.
    if set(out.values()) != set(range(1, len(out) + 1)) or len(set(out.values())) != len(out):
        return {}
    return out


def _start_lap1_position(el: pd.DataFrame, g: pd.DataFrame, green_t: float, size: int):
    """A first-lap position needs complete start-to-line recording coverage."""
    first = el[el.lap == 1]
    if first.empty or size < 2 or 'laps_completed' not in g:
        return np.nan
    end = float(first.t_end.iat[0])
    if not math.isfinite(end) or end <= green_t:
        return np.nan
    segment = g[(g.t >= green_t) & (g.t <= end + 1.0)].sort_values('t', kind='stable')
    if (len(segment) < 2 or segment.t.iat[0] > green_t + 2.0
            or segment.laps_completed.iat[0] != 0
            or np.diff(segment.t.to_numpy(float)).max() > 2.0):
        return np.nan
    crossing = segment[(segment.t >= end) & (segment.laps_completed >= 1)]
    pos = crossing.loc[crossing.race_pos.between(1, size), 'race_pos']
    if pos.empty:
        return np.nan
    # A sustained game position around the line avoids one corrupt/outlying tick.
    modes = pos.mode()
    chosen = pos[pos.isin(modes)].iat[-1]
    return float(chosen) if float(chosen) == int(chosen) else np.nan


def _entrant_stats(cls, laps, passes, battles, pits, incidents, fr, ai_names, green_t,
                   start_grid: dict[str, int] | None = None) -> pd.DataFrame:
    counted = passes[passes.kind.isin(COUNTED)]
    field_size = len(cls)
    clean = laps[laps.clean]
    med_clean = clean.groupby("name").time.median()
    ai_meds = med_clean[med_clean.index.isin(ai_names)]
    ai_ref = float(ai_meds.median()) if len(ai_meds) else np.nan
    human_order = [n for n in cls.name if n not in ai_names]
    after_green = fr[fr.t >= green_t + 1.0]
    start_grid = start_grid or {}
    start_size = len(start_grid)
    from .legends import start_score

    rows = []
    for r in cls.itertuples():
        n = r.name
        el = laps[laps.name == n]
        ec = clean[clean.name == n]
        valid = el[el.valid]
        made = counted[counted.passer == n]
        recv = counted[counted.passed == n]
        bt = battles[(battles.a == n) | (battles.b == n)]
        pos_after_l1 = el.loc[el.lap >= 1, "position"].dropna()
        lowest = int(pos_after_l1.max()) if len(pos_after_l1) else np.nan
        best_sectors = [valid[c].min() for c in ("s1", "s2", "s3")] if len(valid) else [np.nan] * 3
        classified = r.status in ("finished", "running")
        g = after_green[after_green.name == n]
        inc = incidents[incidents.name == n]
        involved = incidents[(incidents.kind == "contact") & ((incidents.name == n) | (incidents.other == n))]
        start_position = start_grid.get(n)
        first_lap_position = _start_lap1_position(el, fr[fr.name == n], green_t, start_size)
        rows.append({
            "name": n, "is_ai": n in ai_names, "grid": r.grid, "finish": r.pos, "status": r.status,
            "laps": r.laps, "human_rank": (human_order.index(n) + 1) if n in human_order else np.nan,
            "positions_gained": (r.grid - r.pos) if pd.notna(r.grid) else np.nan,
            "lap1_pos": el.loc[el.lap == 1, "position"].iat[0] if (el.lap == 1).any() else np.nan,
            "start_grid": start_position, "start_field_size": start_size if start_position else np.nan,
            "start_lap1_pos": first_lap_position if start_position else np.nan,
            "start_score": start_score(start_position, first_lap_position, start_size),
            "best_lap": float(valid.time.min()) if len(valid) else np.nan,
            "median_clean": float(ec.time.median()) if len(ec) else np.nan,
            "consistency_s": float(ec.time.std()) if len(ec) > 2 else np.nan,
            "clean_laps": len(ec),
            "theoretical_best": float(np.sum(best_sectors)) if not np.isnan(best_sectors).any() else np.nan,
            "invalid_laps": int((~el.valid).sum()),
            "laps_led": int((el.position == 1).sum()),
            "passes_made": len(made), "passes_clean": int((made.kind == "clean").sum()),
            "passes_gifted": int((made.kind == "gifted").sum()), "passes_contact": int((made.kind == "contact").sum()),
            "passes_lap1": int(made.lap1.sum()),
            "passes_on_humans": int((~made.passed.isin(ai_names)).sum()),
            "passes_on_ai": int(made.passed.isin(ai_names).sum()),
            "passed_by": len(recv), "passed_by_humans": int((~recv.passer.isin(ai_names)).sum()),
            "battles": len(bt), "battles_won": int((bt.winner == n).sum()),
            "battle_time_s": float(bt.duration_s.sum()),
            "pit_stops": int((pits.name == n).sum()),
            "pit_lane_time": float(pits.loc[pits.name == n, "lane_time"].sum()),
            "top_speed_kph": float(g.speed.max() * 3.6) if len(g) else np.nan,
            "lowest_pos": lowest,
            "recovery": (lowest - r.pos) if (pd.notna(lowest) and classified) else np.nan,
            "field_size": field_size,
            "field_pct": ((field_size - r.pos) / (field_size - 1)) if (classified and field_size > 1) else np.nan,
            "ai_rel_pace": (float(med_clean[n]) / ai_ref) if (n in med_clean.index and ai_ref == ai_ref) else np.nan,
            "gap_to_winner": r.gap, "total_time": r.total_time,
            "contacts": len(involved), "spins": int((inc.kind == "spin").sum()),
            "off_tracks": int((inc.kind == "off_track").sum()),
        })
    stats = pd.DataFrame(rows)
    if len(stats):
        stats["lap1_gain"] = stats.grid - stats.lap1_pos
    return stats


def race_highlights(ra: RaceAnalysis) -> list[str]:
    """A few debrief one-liners for the group chat."""
    s, out = ra.stats, []
    hum = s[~s.is_ai]

    def best(df, col, label, fmt, asc=False):
        d = df.dropna(subset=[col])
        if len(d):
            r = d.sort_values(col, ascending=asc).iloc[0]
            out.append(f"{label}: {r['name']} ({fmt.format(r[col])})")

    best(s, "positions_gained", "Biggest climber", "{:+.0f} places")
    best(s, "passes_made", "Most passes", "{:.0f}")
    best(s, "lap1_gain", "Lap 1 hero", "{:+.0f} places on lap 1")
    best(s[s.clean_laps >= 3], "consistency_s", "Metronome", "{:.3f}s lap-time spread", asc=True)
    best(hum, "ai_rel_pace", "Fastest human vs AI", "{:.3f}x AI median", asc=True)
    if len(ra.battles):
        b = ra.battles.sort_values(["duration_s"], ascending=False).iloc[0]
        loser = b.b if b.winner == b.a else b.a
        verb = "held off" if b.winner == b.a else "got the better of"
        swaps = f"{b.swaps} swap{'s' if b.swaps != 1 else ''}"
        out.append(f"Battle of the race: {b.winner} {verb} {loser} over {b.laps:.1f} laps "
                   f"(min gap {b.min_gap_s:.2f}s, {swaps})")
    counted = ra.passes[ra.passes.kind.isin(COUNTED)]
    if len(counted) and counted.corner.notna().any():
        c = counted.corner.value_counts()
        out.append(f"Overtaking hotspot: {c.index[0]} ({c.iat[0]} passes)")
    fl = s.dropna(subset=["best_lap"]).sort_values("best_lap")
    if len(fl):
        out.append(f"Fastest lap: {fl.name.iat[0]} ({fmt_time(fl.best_lap.iat[0])})")
    return out


def fmt_time(x) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    m, s = divmod(float(x), 60)
    return f"{int(m)}:{s:06.3f}" if m else f"{s:.3f}"
