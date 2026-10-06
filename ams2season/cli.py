"""ams2season command line.

  app          the desktop app: recorder, championships, standings and race reports in one window
  record       run the shared-memory recorder (Windows, while AMS2 is running)
  report       visual HTML report of a race, opens in your browser (newest race by default)
  inspect      text debrief of a recorded race folder (no database needed)
  ingest       analyse a race recording and store it as a season round
  race         debrief a stored round
  standings    championship table (humans_only / full_field / both)
  stats        season-long driver stats, head-to-head and highlights
  correct      add a stewarding correction (time/position penalty, dsq, points)
  corrections  list corrections
  simulate     generate a fake season of recordings to try everything out
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_colwidth", 28)


def _table(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else (f"{v:.0f}" if float(v).is_integer() else floatfmt.format(v))
        return str(v)
    return df.map(fmt).to_string(index=False)


def print_race(ra, title: str | None = None, top_n: int = 8) -> None:
    from .awards import race_awards
    from .race import COUNTED, fmt_time
    m, cls, st = ra.session.meta, ra.classification, ra.stats.set_index("name")
    n_ai = int(ra.entrants.is_ai.sum())
    print(f"\n=== {title or 'Race'}: {m['track_location']} {m['track_variation']} | "
          f"{int(cls.laps.max())} laps | {len(cls)} cars ({len(cls) - n_ai} human, {n_ai} AI) | "
          f"recorded by {m.get('label') or m.get('hostname')} ===\n")
    rows = []
    for r in cls.itertuples():
        s = st.loc[r.name]
        if r.pos == 1:
            res = fmt_time(r.total_time)
        elif r.status == "finished" and r.laps_down == 0:
            res = f"+{r.gap:.3f}"
        elif r.status == "finished":
            res = f"+{int(r.laps_down)} lap{'s' if r.laps_down > 1 else ''}"
        else:
            res = r.status.upper()
        rows.append({"Pos": r.pos, "Driver": ("" if s.is_ai else "> ") + r.name, "Car": r.car,
                     "Grid": r.grid, "+/-": s.positions_gained, "Laps": r.laps, "Result": res,
                     "Best": fmt_time(s.best_lap), "Passes": f"{int(s.passes_made)}/{int(s.passed_by)}"})
    print(_table(pd.DataFrame(rows)))
    print("  > = human   Passes = made/conceded (on-track, excluding pit cycles)\n")

    hum = ra.stats[~ra.stats.is_ai].sort_values("finish")
    if len(hum):
        cols = {"name": "Driver", "human_rank": "Rank", "finish": "Overall", "grid": "Grid",
                "lap1_gain": "Lap1 +/-", "passes_clean": "Clean", "passes_gifted": "Gifted",
                "passes_on_humans": "On humans", "battles_won": "Battles won", "median_clean": "Median lap",
                "consistency_s": "Spread s", "ai_rel_pace": "vs AI", "field_pct": "Field %"}
        h = hum[list(cols)].rename(columns=cols)
        h["Median lap"] = h["Median lap"].map(fmt_time)
        print("Humans")
        print(_table(h, "{:.3f}") + "\n")

    counted = ra.passes[ra.passes.kind.isin(COUNTED)]
    if len(counted):
        corners = counted.corner.value_counts().reindex([c["name"] for c in ra.corners]).fillna(0).astype(int)
        print("Passes by corner: " + "  ".join(f"{k} {v}" for k, v in corners.items()))
        other = ra.passes.kind.value_counts().to_dict()
        print("Order changes: " + ", ".join(f"{k} {v}" for k, v in other.items()) + "\n")
    if ra.corners:
        print("Corners: " + "  ".join(f"{c['name']} @{c['apex']:.0f}m ({c['apex_kph']:.0f} km/h)" if "apex_kph" in c
                                      else f"{c['name']} @{c['apex']:.0f}m" for c in ra.corners))
        print("  (name them per track in the config's \"corners\" section)\n")
    if len(ra.pits):
        print("Pit stops: " + "; ".join(f"{p.name} L{p.lap} {p.lane_time:.1f}s lane / {p.stationary_time:.1f}s stopped"
                                        for p in ra.pits.itertuples()) + "\n")
    for a in race_awards(ra)[:top_n]:
        print(f" * {a['title']}: {a['detail']}")
    for w in ra.warnings:
        print(" ! " + w)


def cmd_app(a):
    from .app import run_app
    run_app(a.root, port=a.port, open_ui=not a.no_window, keep_alive=a.keep_alive)


def cmd_record(a):
    from .recorder import Recorder
    from .shm import SharedMemoryReader
    rec = Recorder(a.out, hz=a.hz, sessions=tuple(a.sessions.split(",")), label=a.label)
    rec.run(SharedMemoryReader())


def cmd_simulate(a):
    from .simulate import demo_season
    humans = [h.strip() for h in a.humans.split(",")]
    sessions = demo_season(a.out, humans=humans, races=a.races, seed=a.seed)
    print(f"\nWrote {len(sessions)} race recordings and {Path(a.out) / 'season.demo.json'}")
    print("Try:\n"
          f"  ams2season ingest --db demo.db --config {Path(a.out) / 'season.demo.json'} {sessions[0]}\n"
          "  ams2season standings --db demo.db")


def _humans_from(a, session_dir=None):
    """Who is human: --config, then --humans, then ./season.json, else just the recording driver."""
    from .season import SeasonConfig
    if getattr(a, "config", None):
        return SeasonConfig.load(a.config).human_names()
    if getattr(a, "humans", None):
        return {h.strip() for h in a.humans.split(",")}
    if Path("season.json").exists():
        return SeasonConfig.load("season.json").human_names()
    if session_dir is not None:
        import json
        local = json.loads((Path(session_dir) / "session.json").read_text(encoding="utf-8")).get("local", {}).get("name")
        if local:
            print(f"(no season.json here, so only {local} is treated as human; pass --config to fix)")
            return {local}
    return None


def _latest_race(recordings: str) -> Path:
    races = sorted(p for p in Path(recordings).glob("*_race*") if (p / "session.json").exists())
    if not races:
        sys.exit(f"no race recordings found in {Path(recordings).resolve()}")
    return races[-1]


def cmd_inspect(a):
    from .race import analyze_race
    session = a.session or _latest_race(a.recordings)
    ra = analyze_race(session, humans=_humans_from(a, session))
    print_race(ra, title=Path(session).name)


def cmd_report(a):
    import webbrowser
    from .race import analyze_race
    from .report import render_race_report
    if a.db:
        from .season import connect, resolve_config
        con = connect(a.db)
        cfg = resolve_config(con, a.config)
        row = con.execute("""SELECT s.path, ev.track, ev.layout FROM session s JOIN event ev ON ev.id=s.event_id
                             WHERE ev.round=? AND s.race_no=? AND s.type='race'""", (a.round, a.race_no)).fetchone()
        if not row:
            sys.exit(f"round {a.round} not found in {a.db}")
        session = Path(row["path"])
        ra = analyze_race(session, humans=cfg.human_names(),
                          corners_override=cfg.corners_for(row["track"], row["layout"]), params=cfg.pass_params())
    else:
        session = Path(a.session) if a.session else _latest_race(a.recordings)
        humans = _humans_from(a, session)
        corners = params = None
        cfg_path = a.config or ("season.json" if Path("season.json").exists() else None)
        if cfg_path:
            from .season import SeasonConfig
            from .derive import load_session
            cfg = SeasonConfig.load(cfg_path)
            meta = load_session(session).meta
            corners, params = cfg.corners_for(meta["track_location"], meta["track_variation"]), cfg.pass_params()
        ra = analyze_race(session, humans=humans, corners_override=corners, params=params)
    out = Path(a.out) if a.out else session / "report.html"
    render_race_report(ra, out, top_n=a.talking_points)
    print(f"Report written to {out.resolve()}")
    if not a.no_open:
        webbrowser.open(out.resolve().as_uri())


def cmd_ingest(a):
    from .season import connect, ingest, resolve_config
    con = connect(a.db)
    cfg = resolve_config(con, a.config)
    con.close()
    for i, path in enumerate(a.sessions):
        rnd = (a.round + i) if a.round is not None else None
        info = ingest(a.db, cfg, path, round_no=rnd, race_no=a.race_no, note=a.note)
        print(f"Round {info['round']}" + (f" race {info['race_no']}" if info['race_no'] != 1 else "") +
              f": {info['track']} - winner {info['winner']}")
        print(f"  humans: {', '.join(info['humans']) or '(none matched the roster!)'}")
        print(f"  treated as AI ({len(info['ai'])}): {', '.join(info['ai'])}")
        for w in info["warnings"]:
            print(f"  ! {w}")
    print("\nIf a friend shows up in the AI list, add their in-game name to 'aliases' in the config and re-run ingest.")


def cmd_race(a):
    from .race import analyze_race
    from .season import connect, resolve_config
    con = connect(a.db)
    cfg = resolve_config(con, a.config)
    row = con.execute("""SELECT s.path, ev.track, ev.layout FROM session s JOIN event ev ON ev.id=s.event_id
                         WHERE ev.round=? AND s.race_no=? AND s.type='race'""", (a.round, a.race_no)).fetchone()
    if not row:
        sys.exit(f"round {a.round} not found")
    if not Path(row["path"]).exists():
        sys.exit(f"recording moved or deleted: {row['path']}")
    ra = analyze_race(row["path"], humans=cfg.human_names(),
                      corners_override=cfg.corners_for(row["track"], row["layout"]), params=cfg.pass_params())
    print_race(ra, title=f"Round {a.round}")


def cmd_standings(a):
    from .season import connect, resolve_config, standings
    con = connect(a.db)
    cfg = resolve_config(con, a.config)
    policies = ["humans_only", "full_field"] if a.policy == "both" else [a.policy or cfg.ai_policy]
    for pol in policies:
        st = standings(con, cfg, policy=pol, points_name=a.points)
        if st.empty:
            print("no races ingested yet")
            return
        label = {"humans_only": "points by finishing order among humans (AI are traffic)",
                 "full_field": "points by overall finishing position (AI take places, AI points discarded)"}[pol]
        print(f"\n=== {cfg.name} standings | {st.attrs['points']} points | {label} ===\n")
        print(_table(st))
    if cfg.fastest_lap_bonus:
        print(f"\n(+{cfg.fastest_lap_bonus:g} for the fastest lap among classified humans)")


def cmd_stats(a):
    from .season import connect, driver_stats, head_to_head, resolve_config, season_highlights
    con = connect(a.db)
    cfg = resolve_config(con, a.config)
    ds = driver_stats(con, cfg)
    if ds.empty:
        print("no races ingested yet")
        return
    print(f"\n=== {cfg.name}: driver stats ===\n")
    cols = ["driver", "races", "wins", "podiums", "human_wins", "avg_grid", "avg_finish", "avg_human_rank",
            "pos_gained", "avg_lap1_gain", "avg_field_pct", "passes", "clean", "gifted", "on_humans",
            "passed_by", "net_passes", "laps_led", "fastest_laps", "battles_won", "ai_rel_pace",
            "consistency_s", "dnfs"]
    print(_table(ds[cols], "{:.2f}"))
    ahead, passes = head_to_head(con, cfg)
    print("\nHead to head - finished ahead (row beat column):")
    print(ahead.to_string())
    print("\nHead to head - on-track passes (row passed column):")
    print(passes.to_string())
    print()
    for line in season_highlights(con, cfg):
        print(" * " + line)


def cmd_correct(a):
    from .season import add_correction
    cid = add_correction(a.db, a.round, a.driver, a.kind, a.value, a.note, race_no=a.race_no)
    print(f"correction #{cid} added; standings and stats apply it automatically")


def cmd_corrections(a):
    from .season import connect
    con = connect(a.db)
    if a.delete:
        with con:
            con.execute("DELETE FROM correction WHERE id=?", (a.delete,))
        print(f"deleted correction #{a.delete}")
    df = pd.read_sql_query("SELECT id, round, race_no, driver, kind, value, note, created_at FROM correction", con)
    print(df.to_string(index=False) if len(df) else "no corrections")


def main(argv=None):
    p = argparse.ArgumentParser(prog="ams2season", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("app", help="open the AMS2 Season app (recorder, championships, reports)")
    s.add_argument("--root", default=".", help="app folder (recordings/, championships/, settings)")
    s.add_argument("--port", type=int, default=8642)
    s.add_argument("--no-window", action="store_true", help="don't open a window (browse to the printed URL)")
    s.add_argument("--keep-alive", action="store_true", help="keep running after the window closes")
    s.set_defaults(fn=cmd_app)

    s = sub.add_parser("record", help="record sessions from AMS2 shared memory (Windows)")
    s.add_argument("--out", default="recordings")
    s.add_argument("--hz", type=float, default=20.0)
    s.add_argument("--sessions", default="race,qualify", help="comma list: race,qualify,practice")
    s.add_argument("--label", help="whose PC this is (stored in each recording)")
    s.set_defaults(fn=cmd_record)

    s = sub.add_parser("simulate", help="write a fake season of recordings")
    s.add_argument("--out", default="demo_recordings")
    s.add_argument("--races", type=int, default=4)
    s.add_argument("--humans", default="Jax,Mason,Eli,Theo")
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(fn=cmd_simulate)

    s = sub.add_parser("report", help="open a visual HTML report for a race (newest by default)")
    s.add_argument("session", nargs="?", help="race folder (default: newest in --recordings)")
    s.add_argument("--recordings", default="recordings")
    s.add_argument("--config", help="season config (default: ./season.json if present)")
    s.add_argument("--humans", help="comma list of human names, if no config")
    s.add_argument("--db", help="report a stored round instead of a folder")
    s.add_argument("--round", type=int)
    s.add_argument("--race-no", type=int, default=1)
    s.add_argument("--out", help="output file (default: report.html inside the race folder)")
    s.add_argument("--no-open", action="store_true", help="don't open the browser")
    s.add_argument("--talking-points", type=int, default=6, help="awards shown at the top (the rest are under 'See all')")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("inspect", help="text debrief of a recording (newest by default)")
    s.add_argument("session", nargs="?")
    s.add_argument("--recordings", default="recordings")
    s.add_argument("--config", help="season config (to know who is human)")
    s.add_argument("--humans", help="comma list of human names, if no config")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("ingest", help="store race recording(s) as season rounds")
    s.add_argument("sessions", nargs="+")
    s.add_argument("--db", required=True)
    s.add_argument("--config")
    s.add_argument("--round", type=int, help="round number (default: next); increments for multiple paths")
    s.add_argument("--race-no", type=int, default=1, help="for double-header rounds")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("race", help="debrief a stored round")
    s.add_argument("--db", required=True)
    s.add_argument("--round", type=int, required=True)
    s.add_argument("--race-no", type=int, default=1)
    s.add_argument("--config")
    s.set_defaults(fn=cmd_race)

    s = sub.add_parser("standings")
    s.add_argument("--db", required=True)
    s.add_argument("--config")
    s.add_argument("--policy", choices=["humans_only", "full_field", "both"])
    s.add_argument("--points", help="points table name from the config")
    s.set_defaults(fn=cmd_standings)

    s = sub.add_parser("stats")
    s.add_argument("--db", required=True)
    s.add_argument("--config")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("correct", help="stewarding: time_penalty (s), position_penalty (places), dsq, points (+/-)")
    s.add_argument("--db", required=True)
    s.add_argument("--round", type=int, required=True)
    s.add_argument("--race-no", type=int, default=1)
    s.add_argument("--driver", required=True, help="in-game name or roster key")
    s.add_argument("--kind", required=True, choices=["time_penalty", "position_penalty", "dsq", "points"])
    s.add_argument("--value", type=float)
    s.add_argument("--note")
    s.set_defaults(fn=cmd_correct)

    s = sub.add_parser("corrections", help="list (or --delete ID) corrections")
    s.add_argument("--db", required=True)
    s.add_argument("--delete", type=int)
    s.set_defaults(fn=cmd_corrections)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
